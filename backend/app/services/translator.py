"""
Translation service for raw TXT novels.
Translates Chinese raw text to Vietnamese via the dichtienghoa.com API,
with a Selenium web-method fallback if the API is not callable.

Overview:
- parse_raw_file() splits an uploaded TXT novel into title/author/summary and
  chapters (the API layer stores them in the DB).
- Translator.translate_book() / retranslate_book() translate the stored
  chapters in a background thread, saving the RAW translation into
  chapters.translated_content and rendering the DOCX via docx_exporter.

Two translation methods:
- 'api': a direct HTTP POST to the site's AJAX endpoint (fast). The site sits
  behind Cloudflare, so the request must carry a valid `cf_clearance` cookie.
- 'web': drives a real Chrome via Selenium — types text into the page and
  clicks "translate" (slow, but behaves like a human user).
  When 'api' fails for a chunk, translate() falls back to 'web' automatically.

Cloudflare and cf_clearance:
  Cloudflare gives a browser that passes its "Just a moment..." challenge a
  `cf_clearance` cookie. That cookie is only accepted from a client that looks
  the same as the one that earned it: same User-Agent AND same TLS fingerprint
  (the way the TLS handshake is built). Python's `requests` has a very
  non-browser TLS fingerprint, so it gets 403 even with the cookie. That is why
  the API call uses `curl_cffi` with `impersonate="chrome"` (it copies Chrome's
  TLS handshake) and sends the browser's UA (translate_browser_ua setting).
  When the cookie is stale, a real Chrome is opened to earn a new one
  (_maybe_refresh_cookies), at most `translate_cookie_refresh_max` times per
  Translator instance, so a blocked site can never cause an endless loop.
"""

import os
import re
import time
import random
import threading
import requests
from pathlib import Path
from urllib.parse import urlparse

from colorama import Fore, init

from app.config import book_dir, get_user_agent
from app.database import get_database
from app.services.browser import load_page, make_driver

# colorama: autoreset=True resets the color after each print (Fore.RED etc.).
init(autoreset=True)

# Task registry: book_id -> TranslateTask for every running translation.
# The API reads progress from here and sets the cancel flag through it.
# The dict is shared between the request threads and the worker threads, so
# every access goes through `_lock`. `with _lock:` acquires the lock and always
# releases it at the end of the block (even on an exception), so only one
# thread at a time can check-and-modify the dict.
_active_translations = {}
_lock = threading.Lock()

# Chapter title pattern used when parsing raw TXT files.
# Matches lines like "12. 第1章 xxx" or "第1章 xxx"
# (第…章 / 第…话 = "chapter N" in Chinese).
# Both alternatives are LOOKAHEADS `(?=...)`: they match an empty position just
# BEFORE a heading without consuming any characters, so re.split() cuts the
# text there and the heading stays at the start of the next part (it is not
# thrown away as the separator).
#   alt 1: "\b\d+\.\s第\d+[章话]"   -> "12. 第1章" anywhere at a word boundary
#   alt 2: "^[ \t　]*第\s*\d+\s*[章话]" -> "第 1 章" at a line start, allowing
#          leading spaces/tabs and the full-width space "　".
# re.MULTILINE makes `^` match at the start of EVERY line, not just the text.
CHAPTER_SPLIT_RE = re.compile(r"(?=\b\d+\.\s第\d+[章话])|(?=^[ \t　]*第\s*\d+\s*[章话])", re.MULTILINE)
# Captures the chapter NUMBER from a heading (group 1), with an optional "12. " prefix.
CHAPTER_NO_RE = re.compile(r"^(?:\d+\.\s)?第\s*(\d+)\s*[章话]")

# Split text into translation chunks at paragraph boundaries (avoids very long single requests).
MAX_CHUNK_CHARS = 1200


class CloudflareBlockedError(RuntimeError):
    """Raised when a translation request cannot pass the Cloudflare check after
    all cookie-refresh attempts. The run should STOP at the current chapter
    (marking it failed) so the user can refresh the cookie and click Continue —
    it must NOT move on to the next chapter and fail the whole batch."""


class TranslationRunningError(RuntimeError):
    """Raised when a translation is started for a book that already has one
    running. The API turns it into HTTP 409 Conflict."""


class TranslateTask:
    """State of one running translation job (one per book).

    Attributes:
        book_id: the book being translated.
        cancelled: set to True by cancel_translation(); the run loop checks it
            between chapters and stops.
        progress: dict returned as-is by the progress API endpoint.
    """

    def __init__(self, book_id: int):
        """Create a task with zeroed progress.

        Args:
            book_id: id of the book this task translates.
        """
        self.book_id = book_id
        self.cancelled = False
        self.progress = {
            "active": True,
            "success_count": 0,
            "fail_count": 0,
            "total": 0,
            "current_index": 0,
            "current_title": "",
            "cancelled": False,
            "method": "api",
            "message": "",
        }

    def set(self, **kwargs):
        """Update progress fields, e.g. task.set(total=10, message="...").

        `**kwargs` collects keyword arguments into a dict, which is merged
        into self.progress (new keys such as 'blocked' are added).
        """
        self.progress.update(kwargs)


def register_task(task: TranslateTask) -> bool:
    """Register a translation job. Returns False (nothing registered) if one is
    already running for the same book — mirrors downloader.register_download().

    Args:
        task: the new task.

    Returns:
        bool: True if registered, False if the book already has a running job.

    Side effects:
        Adds the task to the module-level _active_translations registry.
    """
    # Check and insert under the same lock, so two simultaneous requests
    # cannot both see "not running" and both start a job.
    with _lock:
        if task.book_id in _active_translations:
            return False
        _active_translations[task.book_id] = task
        return True


def unregister_task(book_id: int):
    """Remove a book's task from the registry (no error if it is not there).

    Args:
        book_id: the book whose task finished.
    """
    with _lock:
        # pop(key, None): remove if present, return None instead of raising KeyError.
        _active_translations.pop(book_id, None)


def cancel_translation(book_id: int) -> bool:
    """Ask a running translation to stop after the current chapter.

    Args:
        book_id: the book to cancel.

    Returns:
        bool: True if a running task was found and flagged, else False.

    Side effects:
        Sets task.cancelled; the worker thread notices it and exits its loop.
    """
    with _lock:
        task = _active_translations.get(book_id)
    if not task:
        return False
    task.cancelled = True
    task.progress["cancelled"] = True
    return True


def get_translation_progress(book_id: int):
    """Return the progress dict of a running translation.

    Args:
        book_id: the book to look up.

    Returns:
        dict | None: the live progress dict, or None if nothing is running.
    """
    with _lock:
        task = _active_translations.get(book_id)
    return task.progress if task else None


def translate_text(text: str, method: str = "api") -> str:
    """Translate a block of text. method: 'api' or 'web'.

    Args:
        text: Chinese text.
        method: 'api' (falls back to web on failure) or 'web'.

    Returns:
        str: the Vietnamese translation.

    Raises:
        Exception: whatever the last attempted method raised.

    Side effects:
        Network requests; may open Chrome; logs requests to the DB.
    """
    # TODO: creates a new Translator (DB settings reads, maybe a Chrome) per
    # call; reuse one instance when translating many snippets.
    return Translator().translate(text, method=method)


def _read_text_file(path: str) -> str:
    """Read a text file, trying multiple encodings. Handles UTF-8 BOM,
    UTF-16 (LE/BE), and common Chinese encodings (GBK).

    Args:
        path: file path.

    Returns:
        str: decoded text with line endings normalized to "\\n".

    Note:
        The order matters: strict encodings are tried first because a wrong
        one usually raises UnicodeDecodeError. GBK/GB18030 cover Simplified
        Chinese files, Big5 Traditional Chinese. latin-1 maps every byte to a
        character, so it never fails — it is the "give up" fallback (the text
        will be garbled, but the upload does not crash).
    """
    raw = None
    # "rb" = read bytes: decode manually instead of guessing one encoding.
    with open(path, "rb") as f:
        raw = f.read()
    # Strip BOMs if present (EF BB BF = UTF-8 byte-order mark, added by Notepad)
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
        text = raw.decode("utf-8")
        # Windows "\r\n" and old-Mac "\r" line endings -> "\n".
        return text.replace("\r\n", "\n").replace("\r", "\n")
    for enc in ("utf-8", "utf-16", "gbk", "gb18030", "big5", "latin-1"):
        try:
            text = raw.decode(enc)
            return text.replace("\r\n", "\n").replace("\r", "\n")
        except (UnicodeDecodeError, LookupError):
            continue
    # Last resort: latin-1 never fails
    return raw.decode("latin-1").replace("\r\n", "\n").replace("\r", "\n")


def parse_raw_file(path: str) -> dict:
    """Parse a raw TXT novel into book info + chapters.
    Returns {'raw_title', 'author', 'summary', 'chapters': [{order, title, content}]}.
    'summary' is the intro/meta text before the first chapter (minus title/author
    lines) — used as the book summary, translated on save.

    Args:
        path: path of the TXT file.

    Returns:
        dict: as above; 'chapters' is empty if no heading was found.

    How it works:
        1. CHAPTER_SPLIT_RE splits the file just before every chapter heading.
           parts[0] is the meta block (title, author, intro); the rest are
           chapters whose first line is the heading.
        2. Many raw files repeat the heading, e.g.
               第1章 xxx          <- heading
               第1章：xxx         <- same heading again, different punctuation
           A repeat directly under the heading is dropped. A repeat further
           down splits off as its own part; since it has the same chapter
           NUMBER as the previous chapter, its text is merged back into that
           chapter instead of creating a duplicate one. Comparing numbers
           (not full titles) is what makes the punctuation differences harmless.
    """
    content = _read_text_file(path)

    # List comprehension with a filter: keep stripped parts that are not empty.
    parts = [p.strip() for p in CHAPTER_SPLIT_RE.split(content) if p.strip()]
    if not parts:
        return {"raw_title": os.path.basename(path), "author": "", "summary": "", "chapters": []}

    meta = parts[0]
    lines = [l.strip() for l in meta.split("\n") if l.strip()]

    # First non-empty line of the meta block is taken as the book title.
    raw_title = lines[0] if lines else os.path.basename(path)
    # Try to detect an author line from common patterns
    # ("Tác giả" = Vietnamese, "作者"/"著者" = Chinese for "author";
    # "：" is the full-width colon used in Chinese text).
    author = ""
    summary_lines = []
    for l in lines[1:]:
        m = re.match(r"^\s*(?:Tác giả|作者|著者)\s*[:：]?\s*(.+)$", l)
        if m and m.group(1) and not author:
            author = m.group(1).strip()
            continue
        summary_lines.append(l)

    chapters = []
    # Nested helper function: only used inside parse_raw_file.
    def chapter_no(line: str):
        """Return the chapter number (as a str) of a heading line, or None."""
        m = CHAPTER_NO_RE.match(line.strip())
        return m.group(1) if m else None

    for part in parts[1:]:
        # str.partition(sep) -> (before, sep, after), split at the FIRST sep.
        # Unlike split it always returns 3 items, even without a newline
        # (then after == ""). `_` is the convention for "value not used".
        title, _, content = part.partition("\n")
        title, content = title.strip(), content.strip()
        # Drop the title if it's repeated as the first line of the content
        # (compared by chapter number — the repeat often differs in punctuation)
        first, _, rest = content.partition("\n")
        if chapter_no(first) and chapter_no(first) == chapter_no(title):
            content = rest.strip()
        # A repeated heading line splits off as its own part — merge it into the previous chapter
        if chapters and chapter_no(title) == chapter_no(chapters[-1]["title"]):
            # filter(None, [...]) drops empty strings so no stray blank line is added.
            chapters[-1]["content"] = "\n".join(filter(None, [chapters[-1]["content"], content]))
            continue
        chapters.append({"order": len(chapters) + 1, "title": title, "content": content})

    return {
        "raw_title": raw_title,
        "author": author,
        "summary": "\n".join(summary_lines).strip(),
        "chapters": chapters,
    }


class Translator:
    """Translates text using dichtienghoa API or web method.

    One instance = one translation session: it owns at most one Selenium
    driver (created lazily) and counts cookie refreshes. Always call close()
    when done (the job runner does it in its `finally`).
    """

    def __init__(self):
        """Load all translation settings from the DB.

        Side effects:
            DB reads only. No browser is started here (see _ensure_driver).
        """
        self.db = get_database()
        # `a or b` returns b when a is empty/None: the settings value with a default.
        self.api_endpoint = self.db.get_setting("translate_api_endpoint") or "https://dichtienghoa.com/transtext"
        self.site = self.db.get_setting("translate_site") or "https://dichtienghoa.com"
        self.target_lang = self.db.get_setting("translate_target_lang") or "vi"
        # Settings are stored as strings; convert to numbers.
        self.click_delay = float(self.db.get_setting("translate_click_delay") or 3)
        self.retry_delay = float(self.db.get_setting("translate_retry_delay") or 10)
        self.max_retries = int(self.db.get_setting("translate_max_retries") or 3)
        # The UA must match the browser that earned cf_clearance (see module docstring).
        self.browser_ua = (self.db.get_setting("translate_browser_ua") or "").strip() or get_user_agent()
        # curl_cffi impersonation target (which browser's TLS fingerprint to copy).
        self.impersonate = (self.db.get_setting("translate_impersonate") or "chrome").strip() or "chrome"
        self.cookies = self._load_cookies()
        self.driver = None
        # Auto cookie-refresh when Cloudflare blocks a request. A real Chrome
        # (Selenium) is opened, the challenge is passed (possibly auto), and the
        # fresh cf_clearance is harvested and saved so the process does not stop.
        self.cookie_wait = float(self.db.get_setting("translate_cookie_wait") or 60)
        self.cookie_refresh_max = int(self.db.get_setting("translate_cookie_refresh_max") or 1)
        self._cookie_refresh_count = 0

    def _load_cookies(self) -> dict:
        """Read the stored cookie dict (JSON in the translate_cookies setting).

        Returns:
            dict: cookie name -> value; {} if unset or the JSON is invalid.
        """
        raw = self.db.get_setting("translate_cookies") or "{}"
        try:
            import json
            return json.loads(raw) or {}
        except Exception:
            return {}

    def _save_cookies(self, cookies: dict):
        """Persist a fresh cookie set to settings AND update this instance.

        Args:
            cookies: cookie name -> value.

        Side effects:
            DB write of the translate_cookies setting (JSON).
        """
        import json
        self.cookies = cookies
        self.db.update_setting("translate_cookies", json.dumps(cookies))

    # --- API method ---

    def api_available(self) -> bool:
        """Quickly probe whether the API endpoint responds to a tiny request.

        Returns:
            bool: True if "你好" ("hello") came back translated.

        Side effects:
            One network request (may trigger a cookie refresh in Chrome).
        """
        try:
            r = self._api_call("你好", timeout=15)
            return bool(r and r.strip())
        except Exception as e:
            print(f"{Fore.YELLOW}Translation API probe failed: {e}")
            return False

    def _request_api(self, data: dict, headers: dict, timeout: int):
        """Issue the API POST request using curl_cffi (with fallback to requests).

        Args:
            data: form fields to POST.
            headers: HTTP headers (UA etc.).
            timeout: seconds before giving up.

        Returns:
            A response object (curl_cffi's or requests' — same basic API:
            .status_code, .text, .json(), .raise_for_status()).

        Side effects:
            Network request.
        """
        try:
            # Imported here (not at the top) so the module still works when
            # curl_cffi is not installed: the ImportError is caught below.
            from curl_cffi import requests as cffi_requests
            return cffi_requests.post(
                self.api_endpoint, data=data, headers=headers,
                # `self.cookies or None`: pass None instead of an empty dict.
                cookies=self.cookies or None, impersonate=self.impersonate,
                timeout=timeout,
            )
        except ImportError:
            # Plain requests has a non-browser TLS fingerprint, so Cloudflare
            # will usually reject it even with a valid cf_clearance.
            return requests.post(self.api_endpoint, data=data, headers=headers,
                                 cookies=self.cookies or None, timeout=timeout)

    def _api_call(self, text: str, timeout: int = 60) -> str:
        """Send form-encoded request to the translation API.
        Expected response: {"data": "...", "err": 0}

        Uses curl_cffi with Chrome TLS impersonation + the real browser UA so a
        stored cf_clearance cookie (bound to that fingerprint) can pass Cloudflare.
        Falls back to plain requests if curl_cffi is unavailable.

        If Cloudflare blocks (403), the cookie is auto-refreshed from a real
        Chrome (up to cookie_refresh_max times) and the request is retried.

        Args:
            text: text to translate (one chunk).
            timeout: request timeout in seconds.

        Returns:
            str: the translated text.

        Raises:
            CloudflareBlockedError: still blocked after all cookie refreshes.
            RuntimeError: the API answered with err != 0.
            HTTPError: any other non-2xx status (from raise_for_status).

        Side effects:
            Network requests; may open Chrome and save new cookies to the DB.
        """
        # Headers copy what the site's own JavaScript sends for its AJAX call.
        headers = {
            "User-Agent": self.browser_ua,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": self.site + "/",
        }
        # t = text, tt = target language (the site's form field names).
        data = {"t": text, "tt": self.target_lang}

        # Bounded retry loop: 1 normal try + one retry per allowed cookie
        # refresh. It ends by returning (success), raising (API error), or
        # falling out of the loop -> CloudflareBlockedError below.
        attempts = self.cookie_refresh_max + 1
        for attempt in range(1, attempts + 1):
            r = self._request_api(data, headers, timeout)
            # A Cloudflare block is a 403 whose body is the challenge page.
            if r.status_code == 403 and ("Just a moment" in (r.text or "") or "cf_clearance" in (r.text or "")):
                print(f"{Fore.YELLOW}[api] Cloudflare block (attempt {attempt}/{attempts}). Refreshing cookie...")
                if not self._maybe_refresh_cookies():
                    break
                continue
            r.raise_for_status()
            result = r.json()
            if result.get("err") == 0:
                return str(result.get("data") or "").strip()
            raise RuntimeError(f"Translation API error: {result}")
        raise CloudflareBlockedError(
            f"API translation blocked by Cloudflare after {attempts} attempt(s). "
            f"Auto cookie refresh limit ({self.cookie_refresh_max}) reached. "
            f"Update translate_cookies under Settings (or click 'Continue' on the book)."
        )

    # --- Web method (Selenium) ---

    def _ensure_driver(self):
        """Start a visible Chrome WebDriver if this instance has none yet.

        Side effects:
            May download chromedriver; starts a Chrome process stored in
            self.driver (closed by close()).
        """
        if self.driver is not None:
            return
        # custom_ua=False: do NOT force a custom user-agent here. cf_clearance
        # cookies are bound to the exact UA + TLS fingerprint that solved the
        # Cloudflare challenge, so Chrome must keep its real UA.
        self.driver = make_driver(custom_ua=False)

    def _inject_cookies(self, driver):
        """Inject stored cookies (e.g. cf_clearance) into the current page.

        Selenium only accepts cookies for the domain currently loaded, so a
        page of the site must be open before calling this.

        Args:
            driver: the Selenium WebDriver.

        Side effects:
            Adds cookies to the browser; failures are printed, not raised.
        """
        if not self.cookies:
            return
        domain = urlparse(self.site).hostname
        for name, value in self.cookies.items():
            try:
                driver.add_cookie({"name": name, "value": value, "domain": domain})
            except Exception as e:
                print(f"{Fore.YELLOW}Could not add translate cookie {name}: {e}")

    def _maybe_refresh_cookies(self) -> bool:
        """Open a real Chrome, let Cloudflare issue a fresh cf_clearance, save it.
        Guarded by cookie_refresh_max so we never loop forever (anti-blocking).

        Returns:
            bool: True if fresh cookies were stored; False if the limit is
            reached or no cookie could be obtained.

        Side effects:
            Increments the per-instance refresh counter; see
            _refresh_cookies_from_browser.
        """
        if self._cookie_refresh_count >= self.cookie_refresh_max:
            print(f"{Fore.RED}[cookie] Refresh limit reached ({self.cookie_refresh_max}).")
            return False
        self._cookie_refresh_count += 1
        print(f"{Fore.CYAN}[cookie] Opening real Chrome to obtain a fresh cf_clearance "
              f"({self._cookie_refresh_count}/{self.cookie_refresh_max})...")
        return self._refresh_cookies_from_browser()

    def _refresh_cookies_from_browser(self) -> bool:
        """Open the site in a real (visible) Chrome, wait for the Cloudflare
        challenge to pass and the translation page to load (txtOriginal present),
        capture the cookies, and save them. Leaves the driver ON the loaded page
        so callers can continue immediately. Returns True if fresh cookies stored.

        The browser is visible on purpose: if Cloudflare shows a checkbox, the
        user can click it within `cookie_wait` seconds.

        Side effects:
            Starts Chrome if needed; network; DB write of translate_cookies.
        """
        from selenium.webdriver.common.by import By

        self._ensure_driver()
        driver = self.driver
        # Load once to get a page context, add stored cookies, load again with them.
        load_page(driver, self.site)
        self._inject_cookies(driver)
        load_page(driver, self.site)

        # Poll once per second until the page is past the challenge or time runs out.
        deadline = time.time() + self.cookie_wait
        loaded = None
        while time.time() < deadline:
            # Dict comprehension: {key: value for item in iterable}.
            cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
            try:
                # Page fully loaded past the challenge (txtOriginal present).
                driver.find_element(By.ID, "txtOriginal")
                loaded = cookies
                break
            except Exception:
                pass
            time.sleep(1)

        if loaded is None:
            # Page didn't finish loading, but we may still have captured a cookie.
            cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
            if cookies.get("cf_clearance"):
                loaded = cookies
            else:
                print(f"{Fore.RED}[cookie] No page load / cf_clearance within {self.cookie_wait}s.")
                return False
        self._save_cookies(loaded)
        print(f"{Fore.GREEN}[cookie] Fresh cf_clearance captured and saved.")
        return True

    def _web_call(self, text: str, timeout: int = 120) -> str:
        """Translate text by driving the website in Chrome.

        Flow: open the site -> type the text into #txtOriginal -> click the
        translate button -> poll #txtTranslation until it has a value.

        Retries, from inner to outer:
          1. Click retries: clicking too soon after typing often does nothing,
             so up to `max_retries` clicks are made (first after click_delay,
             then every retry_delay), each followed by polling up to `timeout`s.
          2. Cookie refresh: if the page itself shows a challenge, or all
             clicks produced nothing (the AJAX call is being blocked), a fresh
             cookie is fetched and the whole flow repeats. This `while True`
             loop is bounded because _maybe_refresh_cookies returns False once
             cookie_refresh_max is reached, which raises.

        Args:
            text: text to translate (one chunk).
            timeout: seconds to wait for output after each click.

        Returns:
            str: the translated text.

        Raises:
            CloudflareBlockedError: blocked and no more cookie refreshes allowed.

        Side effects:
            Starts/uses Chrome; network; saves working cookies to the DB.
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        self._ensure_driver()
        driver = self.driver
        load_page(driver, self.site)

        # Inject cookies after first navigation (page context exists), then reload
        self._inject_cookies(driver)
        load_page(driver, self.site)

        wait = WebDriverWait(driver, 30)

        # Outer loop: the page may load fine while the translate request itself is
        # blocked (Cloudflare 403 on the AJAX call). When the click retries produce
        # no output, refresh the Cloudflare cookie and retry the whole flow. Every
        # refresh goes through _maybe_refresh_cookies (bounded by cookie_refresh_max),
        # so the loop can never run forever.
        while True:
            try:
                input_el = wait.until(EC.presence_of_element_located((By.ID, "txtOriginal")))
            except Exception:
                # Cloudflare challenge present — try to auto-refresh the cookie once
                # (the user may need to click the challenge). On success the driver is
                # ALREADY on the loaded page, so we continue from there — no reload.
                print(f"{Fore.YELLOW}[web] Cloudflare challenge detected. Attempting cookie refresh...")
                if not self._maybe_refresh_cookies():
                    raise CloudflareBlockedError(
                        "Translation site blocked (Cloudflare challenge) and cookie "
                        "refresh limit reached. Update translate_cookies under Settings "
                        "or click 'Continue' on the book."
                    )
                try:
                    input_el = wait.until(EC.presence_of_element_located((By.ID, "txtOriginal")))
                except Exception:
                    raise CloudflareBlockedError(
                        "Translation site still blocked (Cloudflare challenge) after "
                        "cookie refresh. Update translate_cookies under Settings or "
                        "click 'Continue' on the book."
                    )
            input_el.clear()
            input_el.send_keys(text)

            # Click the translate button (anchor with btnTranslateClick handler);
            # the second selector is a fallback in case the onclick markup changes.
            try:
                btn = driver.find_element(By.CSS_SELECTOR, "a[onclick='btnTranslateClick()'], a[onclick=\"btnTranslateClick()\"]")
            except Exception:
                btn = driver.find_element(By.CSS_SELECTOR, "a.btn.cyan")

            output_el = wait.until(EC.presence_of_element_located((By.ID, "txtTranslation")))

            # Clicking too fast can result in no translation. Wait a moment before the
            # first click, then retry the click (after a delay) if no result appears.
            max_attempts = max(1, self.max_retries)
            for attempt in range(1, max_attempts + 1):
                if attempt == 1:
                    time.sleep(self.click_delay)
                else:
                    print(f"{Fore.YELLOW}[web] attempt {attempt}: no result yet, "
                          f"retrying click in {self.retry_delay}s...")
                    time.sleep(self.retry_delay)

                try:
                    btn.click()
                except Exception as e:
                    print(f"{Fore.RED}[web] click failed on attempt {attempt}: {e}")
                    continue

                # Poll until the translation text appears
                # (textarea content is read via its "value" attribute).
                deadline = time.time() + timeout
                while time.time() < deadline:
                    value = output_el.get_attribute("value") or ""
                    if value.strip():
                        # Successful load also proves the current cookie works — refresh it
                        try:
                            self._save_cookies({c["name"]: c["value"] for c in driver.get_cookies()})
                        except Exception:
                            pass
                        return value.strip()
                    time.sleep(1)

            # All click attempts produced no result — the translate request itself is
            # likely being blocked (Cloudflare 403 on the AJAX call, while the page
            # loaded fine). Refresh the cookie and retry the whole flow. If the
            # refresh fails (cookie_refresh_max reached / no fresh cookie), stop.
            print(f"{Fore.YELLOW}[web] No result after {max_attempts} click attempts. "
                  f"Refreshing Cloudflare cookie and retrying...")
            if not self._maybe_refresh_cookies():
                raise CloudflareBlockedError(
                    f"Web translation blocked: the translate request returned no "
                    f"result after {max_attempts} click attempts and the cookie "
                    f"refresh limit ({self.cookie_refresh_max}) was reached. Update "
                    f"translate_cookies under Settings or click 'Continue' on the book."
                )
            # Cookie refreshed — _refresh_cookies_from_browser left the driver on the
            # freshly loaded page, so loop back and re-type / re-click the text.

    def translate(self, text: str, method: str = "api") -> str:
        """Translate a block of text. Falls back api -> web automatically.
        Logs which method actually produced the result (one line per call).

        The text is split into chunks (_chunk_text). For each chunk:
          method='api': try the API; on ANY error log it and retry that chunk
                        with the web method; if web also fails, re-raise.
          method='web': web only, no fallback.
        The fallback is per chunk, so later chunks still try the API first.

        Args:
            text: text to translate.
            method: 'api' or 'web'.

        Returns:
            str: translated chunks joined by "\\n" ("" for empty input).

        Raises:
            Exception: the web method's error when no method succeeded
            (often CloudflareBlockedError).

        Side effects:
            Network; maybe Chrome; one request_logs DB row per attempt.
        """
        text = (text or "").strip()
        if not text:
            return ""
        chunks = self._chunk_text(text)
        results = []
        used = None
        for i, chunk in enumerate(chunks):
            if method == "api":
                t0 = time.time()
                try:
                    results.append(self._api_call(chunk))
                    used = "api"
                    self._log_translate_request("api", True, duration_ms=int((time.time() - t0) * 1000))
                except Exception as e:
                    self._log_translate_request("api", False, error=str(e),
                                                duration_ms=int((time.time() - t0) * 1000))
                    print(f"{Fore.YELLOW}API translate failed, falling back to web: {e}")
                    t0 = time.time()
                    try:
                        results.append(self._web_call(chunk))
                        used = "web"
                        self._log_translate_request("web", True, duration_ms=int((time.time() - t0) * 1000))
                    except Exception as e2:
                        self._log_translate_request("web", False, error=str(e2),
                                                    duration_ms=int((time.time() - t0) * 1000))
                        # Bare `raise` re-raises the current exception (e2)
                        # with its original traceback.
                        raise
            else:
                t0 = time.time()
                try:
                    results.append(self._web_call(chunk))
                    used = "web"
                    self._log_translate_request("web", True, duration_ms=int((time.time() - t0) * 1000))
                except Exception as e2:
                    self._log_translate_request("web", False, error=str(e2),
                                                duration_ms=int((time.time() - t0) * 1000))
                    raise
            if i < len(chunks) - 1:
                # Small random pause between chunks so requests don't look robotic.
                time.sleep(random.uniform(0.5, 1.5))
        if used:
            print(f"[{used}] translated {len(text)} chars")
        return "\n".join(results)

    def _log_translate_request(self, method: str, success: bool, error: str = None,
                               duration_ms: int = None):
        """Record a translation-site request for statistics (separate domain from
        the book site, so it never counts against the book chapter limit).

        Args:
            method: 'api' or 'web'.
            success: whether the request produced a translation.
            error: error text for failures.
            duration_ms: how long the attempt took.

        Side effects:
            DB write (request_logs).
        """
        domain = urlparse(self.site).hostname or 'dichtienghoa.com'
        self.db.log_request(
            f"translate_{method}",
            "success" if success else "failed",
            session_type="session", domain=domain,
            url=self.api_endpoint if method == "api" else self.site,
            error=error, duration_ms=duration_ms,
        )

    def _chunk_text(self, text: str) -> list[str]:
        """Split text into chunks no larger than MAX_CHUNK_CHARS at paragraph boundaries.

        Lines are packed greedily into the current chunk until the next line
        would overflow it. A single line longer than the limit becomes its own
        (oversized) chunk — lines are never cut in the middle.

        Args:
            text: text with "\\n"-separated paragraphs.

        Returns:
            list[str]: chunks, each joined back with "\\n".
        """
        paragraphs = text.split("\n")
        chunks = []
        current = []
        current_len = 0
        for p in paragraphs:
            # `+ 1` accounts for the "\n" that join() will put between lines.
            if current and current_len + len(p) + 1 > MAX_CHUNK_CHARS:
                chunks.append("\n".join(current))
                current = []
                current_len = 0
            current.append(p)
            current_len += len(p) + 1
        if current:
            chunks.append("\n".join(current))
        return chunks

    def close(self):
        """Quit the Chrome driver if one is running (safe to call repeatedly).

        Side effects:
            Closes the browser process; errors while quitting are ignored.
        """
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    # --- Book-level translation ---

    def _probe_method(self, method: str) -> bool:
        """Verify the chosen translation method works before starting a run.

        Translates "测试" ("test") so a broken setup fails fast instead of
        marking every chapter failed.

        Args:
            method: 'api' or 'web'.

        Returns:
            bool: True if the probe returned text.
        """
        try:
            probe = self.translate("测试", method=method)
            return bool(probe and probe.strip())
        except Exception as e:
            print(f"{Fore.RED}Translation method '{method}' not usable: {e}")
            return False

    def _export_docx(self, book: dict, output_docx: Path):
        """Render the book DOCX from DB content (source of truth), applying
        global cleaning + per-book corrections at render time. Idempotent — safe
        to call any time after chapters have been translated/downloaded.

        Args:
            book: book row dict.
            output_docx: target file path.

        Returns:
            Path: the written DOCX path.

        Raises:
            Exception: any DOCX/IO error (see _export_docx_safe for the
            non-raising variant).

        Side effects:
            Writes the DOCX file. No DB writes.
        """
        # Imported inside the function (lazy import) — commonly done to avoid
        # circular imports or loading python-docx until it is needed.
        from app.services.docx_exporter import build_book_docx, build_render_rules
        chapters = self.db.get_chapters_by_book(book["id"])
        rules = build_render_rules(self.db, book)
        return build_book_docx(book, chapters, rules, output_docx)

    def _translate_run(self, book_id: int, method: str, chapters_to_process: list,
                       output_docx: Path, task: TranslateTask):
        """Shared loop: translate each chapter, save the RAW (uncorrected)
        translation to the DB (source of truth), and update statuses.
        Per-book corrections are applied later at DOCX export time (idempotent
        re-renders), so they can be edited and previewed without re-translating.
        Original Chinese chapter content is NEVER overwritten.

        Args:
            book_id: the book being translated.
            method: 'api' or 'web'.
            chapters_to_process: chapter row dicts to translate, in order.
            output_docx: DOCX path (its file name is stored on each chapter).
            task: the running TranslateTask (progress + cancel flag).

        Returns:
            tuple[int, int]: (success_count, fail_count).

        Raises:
            RuntimeError: the probe failed (book status set to 'failed').

        Side effects:
            Network; DB writes per chapter (translated_content, status);
            updates task.progress; sets task.progress['blocked'] when stopped
            by Cloudflare.
        """
        total = len(chapters_to_process)
        task.set(total=total, message="Probing translation method...")

        if not self._probe_method(method):
            msg = f"Translation method '{method}' not usable."
            self.db.update_book_status(book_id, "failed")
            task.set(active=False, message=msg)
            raise RuntimeError(msg)
        task.set(message="Probe OK, starting chapters...")

        success_count = 0
        fail_count = 0

        # enumerate(items, 1) yields (index, item) with the index starting at 1.
        for idx, ch in enumerate(chapters_to_process, 1):
            if task.cancelled:
                task.set(message="Translation cancelled")
                break
            task.set(current_index=idx, current_title=ch["chapter_title"])
            try:
                # Fallback title "Chương N" = "Chapter N" in Vietnamese.
                raw_title = ch["chapter_title"] or f"Chương {ch['chapter_order']}"
                raw_content = ch.get("chapter_content") or ""

                # ONE request per chapter: send title + content together so we
                # don't make two requests. The first line of the output is the
                # translated title; the rest is the translated content.
                combined = f"{raw_title}\n{raw_content}" if raw_content else raw_title
                translated = self.translate(combined, method=method)
                if "\n" in translated:
                    translated_title, translated_content = translated.split("\n", 1)
                else:
                    translated_title, translated_content = translated, ""
                # Safety: if the content came back empty (split edge case),
                # translate it separately so the chapter is not lost.
                if raw_content and not translated_content.strip():
                    print(f"{Fore.YELLOW}[run] Title+content split empty; "
                          f"translating content separately.")
                    translated_content = self.translate(raw_content, method=method)

                # Store the RAW (uncorrected) translation; corrections are
                # applied at DOCX export time so they are idempotent.
                self.db.update_chapter_translated_content(
                    ch["id"], f"{translated_title}\n{translated_content}")

                self.db.update_chapter_status(ch["id"], "completed", file_path=output_docx.name)
                success_count += 1
                task.set(success_count=success_count, message=f"Translated: {translated_title}")
                print(f"{Fore.GREEN}Translated: {translated_title} ({idx}/{total})")
            # Order matters: the specific CloudflareBlockedError must be caught
            # before the generic Exception, or it would never be reached.
            except CloudflareBlockedError as e:
                # Cloudflare needs a new session. Mark the CURRENT chapter
                # failed and STOP — do NOT move on to the next chapter (it
                # would fail too). The user refreshes the cookie and clicks
                # 'Continue', which retries failed chapters.
                self.db.update_chapter_status(ch["id"], "failed", error_message=str(e))
                fail_count += 1
                task.set(fail_count=fail_count,
                         message=f"Cloudflare blocked chapter {ch['chapter_order']} — stopped. "
                                 f"Refresh the cookie and click Continue.")
                print(f"{Fore.RED}Cloudflare blocked chapter {ch['chapter_order']} — "
                      f"STOPPING run. Refresh the cookie and click Continue.")
                task.set(blocked=True)
                break
            except Exception as e:
                # Any other error: fail just this chapter and keep going.
                self.db.update_chapter_status(ch["id"], "failed", error_message=str(e))
                fail_count += 1
                task.set(fail_count=fail_count, message=f"Failed chapter {ch['chapter_order']}: {e}")
                print(f"{Fore.RED}Chapter {ch['chapter_order']} failed: {e}")

            # Random pause between chapters (be gentle with the site).
            time.sleep(random.uniform(0.5, 1.5))

        return success_count, fail_count

    # ------------------------------------------------------------------
    # Job runner (registration, threading, cleanup) — shared by all runs
    # ------------------------------------------------------------------

    def _start_job(self, task: TranslateTask, job, *args, run_async: bool = True,
                   started_msg: str = ""):
        """Run `job(task, *args)` with guaranteed cleanup, in a thread or inline.

        The task must already be registered (done by the caller in the
        REQUEST thread, so two quick clicks can't both start a run).

        Args:
            task: the registered TranslateTask (progress + cancel flag).
            job: the bound method doing the real work, e.g. self._run_book_job.
            *args: extra positional arguments passed through to `job`
                (`*args` collects any number of positional arguments into a tuple).
            run_async: True → start a daemon thread and return immediately
                (daemon=True: the thread won't keep the server alive at shutdown).
            started_msg: message returned to the API when run_async is True.

        Returns:
            dict: {"message": ...} — started_msg (async) or the final progress
            message (inline).

        Whatever happens inside `job`, the `finally` block marks the task
        inactive, closes Chrome and unregisters the task, so the book can
        never stay "running" forever.

        Note: run_async/started_msg come AFTER *args, so they are keyword-only
        (they can only be passed as run_async=..., never positionally).
        """
        # `guarded` is a closure: a function defined inside another function
        # that "remembers" the outer variables (task, job, args, self) even
        # after _start_job has returned and the thread runs it later.
        def guarded():
            """Run the job, record any error in the task, always clean up."""
            try:
                # `*args` here does the opposite: unpacks the tuple back into
                # separate positional arguments.
                job(task, *args)
            except Exception as e:
                # Errors are not re-raised: in a thread nobody could catch them.
                # They go into the progress message the UI shows instead.
                print(f"{Fore.RED}Translation job failed: {e}")
                task.set(message=f"Translation run failed: {e}")
            finally:
                task.set(active=False)
                self.close()
                unregister_task(task.book_id)

        if run_async:
            # target= is the function the new thread runs; start() returns at once.
            threading.Thread(target=guarded, daemon=True).start()
            return {"message": started_msg}
        guarded()
        return {"message": task.progress.get("message", "")}

    def _new_task(self, book_id: int, method: str) -> tuple:
        """Load the book and register a new TranslateTask for it.

        Args:
            book_id: book to translate.
            method: 'api' or 'web' (recorded in progress).

        Returns:
            (book, task)

        Raises:
            ValueError: book not found.
            TranslationRunningError: a translation is already running for it.
        """
        book = self.db.get_book(book_id)
        if not book:
            raise ValueError("Book not found")
        task = TranslateTask(book_id)
        task.set(method=method)
        if not register_task(task):
            raise TranslationRunningError("Translation already running for this book")
        return book, task

    def _export_docx_safe(self, book: dict, output_docx: Path, note: str = ""):
        """Export the DOCX, printing (not raising) any error — a failed export
        must never hide the translation result.

        Args:
            book: book row dict.
            output_docx: target file path.
            note: extra text for the log line, e.g. " (partial)".

        Side effects:
            Writes the DOCX file.
        """
        try:
            self._export_docx(book, output_docx)
            print(f"{Fore.CYAN}--- DOCX exported{note}: {output_docx.name} ---")
        except Exception as e:
            print(f"{Fore.RED}DOCX export failed: {e}")

    def translate_book(self, book_id: int, method: str = "api", run_async: bool = True,
                       max_chapters: int = None):
        """Translate PENDING chapters into the main `{book_id}_{seo}.docx`.

        Mirrors downloader.run(): only 'pending' chapters are processed and the
        book status ends as completed / paused / cancelled / failed / ...

        Args:
            book_id: book to translate.
            method: 'api' (fast, needs Cloudflare cookie) or 'web' (Selenium).
            run_async: run in a background thread (the API always uses True).
            max_chapters: limit for this session; if more remain → 'paused'.

        Returns:
            dict: {"message": ...} from _start_job.

        Raises:
            ValueError / TranslationRunningError — see _new_task.
        """
        # Registration happens HERE, in the caller's (request) thread, so a
        # duplicate start fails immediately with 409 instead of inside the thread.
        book, task = self._new_task(book_id, method)
        task.set(message=f"Starting translation of {book['title']}")
        return self._start_job(task, self._run_book_job, book, method, False, max_chapters,
                               run_async=run_async,
                               started_msg=f"Translation started for {book['title']}")

    def retranslate_book(self, book_id: int, method: str = "api", run_async: bool = True):
        """Re-translate FAILED chapters into a separate `{book_id}_{seo}_retranslate.docx`.

        Mirrors downloader.run_redownload(). The original Chinese content is never overwritten.

        Args:
            book_id: book to re-translate.
            method: 'api' or 'web'.
            run_async: run in a background thread.

        Returns:
            dict: {"message": ...} from _start_job.

        Raises:
            ValueError / TranslationRunningError — see _new_task.
        """
        book, task = self._new_task(book_id, method)
        task.set(message=f"Re-translating failed chapters of {book['title']}")
        return self._start_job(task, self._run_book_job, book, method, True,
                               run_async=run_async,
                               started_msg=f"Re-translation started for {book['title']}")

    def _run_book_job(self, task: TranslateTask, book: dict, method: str,
                      retranslate: bool = False, max_chapters: int = None):
        """Body of translate_book AND retranslate_book (runs inside _start_job's
        guarded wrapper). The two modes differ only in a few settings:

            mode         chapters picked   output file                 session limit
            translate    'pending'         {id}_{seo}.docx              max_chapters
            retranslate  'failed'          {id}_{seo}_retranslate.docx  none

        Args:
            task: the registered task (progress + cancel flag).
            book: book row dict.
            method: 'api' or 'web'.
            retranslate: False = translate mode, True = retranslate mode.
            max_chapters: optional session limit (translate mode only).

        Raises:
            Exception: re-raised from _translate_run after marking the book failed.

        Side effects:
            DB writes (book + chapter statuses, translations); writes the DOCX.
        """
        book_id = book["id"]
        # Conditional expressions (`a if cond else b`) pick the mode's settings.
        pick_status = "failed" if retranslate else "pending"
        suffix = "_retranslate" if retranslate else ""
        output_docx = book_dir() / f"{book_id}_{book['seo_title_basic']}{suffix}.docx"

        all_chapters = self.db.get_chapters_by_book(book_id)
        chapters_to_process = [c for c in all_chapters if c["download_status"] == pick_status]

        if not chapters_to_process:
            # Nothing to do: just (re)render the DOCX. The status is not touched,
            # so the book doesn't get stuck in 'in_progress'.
            msg = "No failed chapters to re-translate." if retranslate else "All chapters already translated."
            print(f"{Fore.GREEN}{msg} ('{book['title']}')")
            self._export_docx_safe(book, output_docx)
            task.set(message=msg)
            return

        print(f"📚 {len(all_chapters)} total chapters, {len(chapters_to_process)} {pick_status}.")

        # bool(max_chapters) treats None and 0 as "no limit".
        limited = (not retranslate) and bool(max_chapters) and len(chapters_to_process) > max_chapters
        if limited:
            chapters_to_process = chapters_to_process[:max_chapters]
            print(f"🔢 Session limited to {max_chapters} chapters.")

        self.db.update_book_status(book_id, "in_progress", total_chapters=book.get("total_chapters"))
        try:
            success, fail = self._translate_run(book_id, method, chapters_to_process, output_docx, task)
        except Exception:
            # e.g. the probe failed: mark failed, keep whatever was translated,
            # re-raise so _start_job records the message.
            self.db.update_book_status(book_id, "failed")
            self._export_docx_safe(book, output_docx, " (partial)")
            raise

        fresh = self.db.get_chapters_by_book(book_id)
        new_status = self._final_status(task, retranslate, limited, success, fail, fresh)
        # Count completed chapters fresh from the DB (failed ones are not "done").
        # sum(1 for ...) is a generator expression that counts matching items.
        done = sum(1 for c in fresh if c["download_status"] == "completed")
        self.db.update_book_status(book_id, new_status, downloaded_chapters=done)
        label = "re-translation" if retranslate else "translation"
        task.set(message=f"Finished {label}: {success}/{len(chapters_to_process)} chapters ({new_status})")
        self._export_docx_safe(book, output_docx)

    @staticmethod
    def _final_status(task: TranslateTask, retranslate: bool, limited: bool,
                      success: int, fail: int, chapters: list) -> str:
        """Decide the book's download_status after a run (first matching row wins).

        Translate mode:
            task cancelled                  -> 'cancelled'
            stopped by Cloudflare (blocked) -> 'paused'   (Continue after a cookie refresh)
            hit the max_chapters limit      -> 'paused'   (more pending remain)
            no failures                     -> 'completed'
            no successes                    -> 'failed'
            some of each                    -> 'completed_with_errors'

        Retranslate mode:
            task cancelled                  -> 'cancelled'
            'pending' chapters remain       -> 'paused'
            no failures this run            -> 'completed'
            otherwise                       -> 'completed_with_errors'

        `@staticmethod` = a function that lives in the class but doesn't need
        `self` (it only uses its arguments), which also makes it easy to test.
        """
        if task.cancelled:
            return "cancelled"
        if retranslate:
            # any(...) is True as soon as one chapter matches (stops early).
            if any(c["download_status"] == "pending" for c in chapters):
                return "paused"
            return "completed" if fail == 0 else "completed_with_errors"
        if task.progress.get("blocked") or limited:
            return "paused"
        if fail == 0:
            return "completed"
        if success == 0:
            return "failed"
        return "completed_with_errors"


def translate_book(book_id: int, method: str = "api", run_async: bool = True,
                   max_chapters: int = None):
    """Module-level helper so the API router doesn't need to instantiate.

    See Translator.translate_book for args, return value and exceptions.
    """
    return Translator().translate_book(book_id, method=method, run_async=run_async,
                                       max_chapters=max_chapters)


def retranslate_book(book_id: int, method: str = "api", run_async: bool = True):
    """Module-level helper for re-translating failed chapters.

    See Translator.retranslate_book for args, return value and exceptions.
    """
    return Translator().retranslate_book(book_id, method=method, run_async=run_async)


def cancel_all_translations():
    """Flag every running translation as cancelled (e.g. on server shutdown).

    Side effects:
        Sets the cancel flag on all registered tasks.
    """
    # Copy the keys under the lock, then cancel outside it: cancel_translation
    # takes the same lock, and threading.Lock is not re-entrant (taking it
    # twice in one thread would deadlock).
    with _lock:
        ids = list(_active_translations.keys())
    for bid in ids:
        cancel_translation(bid)


def continue_book(book_id: int, method: str = "api", run_async: bool = True):
    """Reset failed chapters back to 'pending' and resume them into the MAIN DOCX.
    Use this after updating a stale cf_clearance cookie: it appends the retried
    chapters to {book_id}_{seo}.docx instead of a separate _retranslate.docx.

    Args:
        book_id: book to continue.
        method: 'api' or 'web'.
        run_async: run in a background thread.

    Returns:
        dict: {"message": ..., "reset": 0} if nothing failed, otherwise the
        result of translate_book.

    Raises:
        ValueError / TranslationRunningError — see Translator._new_task.

    Side effects:
        DB write: failed chapters -> 'pending'; then starts a translation job.
    """
    t = Translator()
    try:
        reset = t.db.reset_failed_chapters(book_id)
        if reset == 0:
            return {"message": "No failed chapters to continue.", "reset": 0}
        # translate_book() below creates its OWN Translator; `t` is only used
        # for the DB reset. close() is harmless when no driver was started.
        # TODO: the explicit close() is redundant with the `finally`, and `t`
        # could simply be reused instead of creating a second Translator.
        t.close()
        return translate_book(book_id, method=method, run_async=run_async)
    finally:
        t.close()


def refresh_cookies_manually() -> dict:
    """Open a real Chrome and capture a fresh cf_clearance cookie. Returns result info.

    Returns:
        dict: {"ok": bool, "has_cookies": bool}.

    Side effects:
        Opens a visible Chrome (closed afterwards); network; DB write of
        translate_cookies on success.
    """
    t = Translator()
    try:
        ok = t._refresh_cookies_from_browser()
        return {"ok": ok, "has_cookies": bool(t.cookies)}
    finally:
        t.close()
