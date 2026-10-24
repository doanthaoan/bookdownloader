"""
Chapter downloader — fetches chapter pages from the book site with Selenium
and stores the cleaned text in the database.

How a download works (big picture):
1. The API creates a `TruyenWikiDownloader(book_id)` in a background thread.
2. A run method (`run`, `run_redownload`, `run_single`) picks the chapters to
   fetch, then enters `_job()`, which:
     - registers the downloader in `_active_downloads` (one job per book),
     - opens Chrome and starts with the first access identity (guest),
     - ALWAYS closes Chrome and unregisters at the end, even on errors.
3. `_process_batch()` loops over the chapters. For each one,
   `process_chapter()` loads the page, applies the GLOBAL text-cleaning rules
   and saves title + body to the `chapters` table (the DB is the source of
   truth; see docx_exporter.py).
   When the site answers "Đã hết lượt truy cập" (access limit reached), the
   chapter is NOT marked failed: the job switches to the next identity
   (guest → primary account → extra accounts) and retries the same chapter.
   When every identity is used up it stops ('paused') or waits and starts
   over, depending on the `access_limit_action` setting.
4. At the end the DOCX is rendered from the DB (if the book's
   `auto_export_docx` flag is on) and the book status is updated.

The API polls `get_download_progress()` to show live progress in the UI.
"""

import json
import random
import threading
import time
from contextlib import contextmanager
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from colorama import Fore, init
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from app.config import (COOKIE_KEYS, STATIC_COOKIES, TRUYENWIKI, book_dir,
                        get_cookies, logs_dir)
from app.database import get_database
from app.services.browser import inject_site_cookies, load_page, make_driver
from app.services.docx_exporter import (build_book_docx, build_render_rules,
                                        collapse_blank_lines)
from app.services.text_cleaner import TextCleaner

# colorama: makes the Fore.* colour codes work in the Windows console.
# autoreset=True resets the colour after every print().
init(autoreset=True)

# Extra pause (seconds, random in this range) between two chapters, ON TOP of
# the configurable `download_delay_min/max` that is waited after each page load.
# Kept on purpose so the request rate stays the same as before (being gentle
# with the site protects the account from rate limits).
# TODO: make this a setting (e.g. `download_pause_min/max`) if you want to tune it from the UI.
BETWEEN_CHAPTER_PAUSE = (2, 4)

# Text the site shows instead of the chapter when the current identity (guest
# or account) has used up its access quota:
#   <div style="margin-top: 2rem; text-align: center">Đã hết lượt truy cập.</div>
ACCESS_LIMIT_MARKER = "Đã hết lượt truy cập"


class AccessLimitError(Exception):
    """The site refused the chapter because the access quota is used up.

    Deliberately NOT a ValueError: callers treat it as "switch identity and
    retry", not as "this chapter is broken".
    """

# ---------------------------------------------------------------------------
# Active-download registry
# ---------------------------------------------------------------------------
# Maps book_id -> TruyenWikiDownloader for every download that is running now.
# Used for: progress polling, cancellation, and the "one job per book" rule.
# Downloads run in background threads, so access is guarded by a Lock:
# without it, two threads could both see "not running" and both register.
_active_downloads = {}
_registry_lock = threading.Lock()


def register_download(book_id: int, downloader) -> bool:
    """Register a downloader as the active job for a book.

    Returns:
        True if registered; False (and nothing registered) if a download is
        already running for this book, so a second run cannot race the first
        on cookies / DB writes.
    """
    # `with lock:` acquires the lock and releases it automatically when the
    # block ends (even if an exception happens inside).
    with _registry_lock:
        if book_id in _active_downloads:
            return False
        _active_downloads[book_id] = downloader
        return True


def unregister_download(book_id: int):
    """Remove a book from the registry. `pop(key, None)` = no error if absent."""
    with _registry_lock:
        _active_downloads.pop(book_id, None)


def cancel_download(book_id: int) -> bool:
    """Ask an active download to stop.

    Cancellation is cooperative: we only set a flag. The download loop checks
    the flag before each chapter, so the current chapter finishes first.

    Returns:
        True if a download was running (flag set), False otherwise.
    """
    downloader = _active_downloads.get(book_id)
    if downloader:
        downloader._cancel_flag = True
        return True
    return False


def cancel_all_downloads():
    """Cancel every active download (called on server shutdown)."""
    # list(...) makes a copy of the keys, because the dict may change while we loop.
    for book_id in list(_active_downloads.keys()):
        cancel_download(book_id)


def is_download_active(book_id: int) -> bool:
    """True if a downloader is currently registered for this book."""
    return book_id in _active_downloads


def get_download_progress(book_id: int) -> dict | None:
    """Return live progress info for an active download, or None if not active.

    The counters are plain attributes on the downloader object that the
    background thread updates while it works; reading them from the API
    thread is safe enough for display purposes (ints are replaced atomically).
    """
    dl = _active_downloads.get(book_id)
    if not dl:
        return None
    return {
        "book_id": book_id,
        "cancelled": dl._cancel_flag,
        "success_count": dl._success_count,
        "fail_count": dl._fail_count,
        "total": dl._remaining_count,
        "current_index": dl._current_index,
        "current_title": dl._current_title,
        # Which identity is downloading now ('guest', 'primary account', username).
        "identity": dl._identities[dl._identity_idx]['label'] if dl._identities else '',
        # Seconds left while waiting for the access quota to reset, else 0.
        "wait_seconds": max(0, int(dl._waiting_until - time.time())) if dl._waiting_until else 0,
    }


def parse_chapter_html(html: str, cleaner: TextCleaner) -> tuple:
    """Extract and globally clean the title + body of a chapter page.

    Used by the downloader AND by the Text Cleaning "Test" endpoint, so the
    test always shows exactly what a real download would store.

    Args:
        html: full page HTML (driver.page_source).
        cleaner: a TextCleaner; only the GLOBAL Text Cleaning rules are applied.
            Per-book corrections are applied later, at DOCX export time, so they
            stay idempotent (the DB keeps the un-corrected text).

    Returns:
        (title_text, body_text). body_text holds the paragraphs joined by a blank
        line ("\\n\\n"), the storage format for downloaded books.

    Raises:
        AccessLimitError: if the page is the site's "access limit reached" notice.
        ValueError: if the page has no chapter content div, or it holds no text.
    """
    soup = BeautifulSoup(html, 'html.parser')

    # Checked first: the notice may replace the content div or sit inside it.
    # `string=lambda ...` makes find() match a <div> whose own text contains the marker.
    if soup.find('div', string=lambda t: t and ACCESS_LIMIT_MARKER in t):
        raise AccessLimitError(f"Access limit reached ({ACCESS_LIMIT_MARKER}).")

    content_tag = soup.find('div', {'class': 'content-body-wrapper'})
    if not content_tag:
        raise ValueError("Could not find content-body-wrapper after waiting.")

    # The page has two <p class="book-title">: [0] = book name, [1] = chapter title.
    title_tags = soup.find_all('p', {'class': 'book-title'})
    if len(title_tags) > 1:
        title_tag = title_tags[1]
    elif title_tags:
        title_tag = title_tags[0]
    else:
        title_tag = None  # the caller falls back to "Chương N" at export time
    title_text = cleaner.clean(title_tag.get_text()).strip() if title_tag else ""

    # List comprehension: clean every non-empty <p> inside the content div.
    cleaned_paragraphs = [
        cleaner.clean(p.get_text()).strip()
        for p in content_tag.find_all('p')
        if p.get_text().strip()
    ]
    if not cleaned_paragraphs:
        # Saving "" would mark the chapter completed with no text; fail it instead
        # so it shows up for Re-download (the message becomes its error note).
        raise ValueError("Empty content: the chapter page has no text paragraphs.")
    # Collapse blank-line runs so stored content never has several empty lines.
    body_text = collapse_blank_lines("\n\n".join(cleaned_paragraphs))
    return title_text, body_text


class TruyenWikiDownloader:
    """Downloads the chapters of ONE book. Create one instance per job."""

    def __init__(self, book_id: int, redownload: bool = False):
        """Load the book, its chapters and the download settings from the DB.

        Chrome is NOT started here — it is started inside `_job()` only after
        the job is registered, so a refused duplicate job never opens a browser.

        Args:
            book_id: id of the book to download.
            redownload: True → output goes to `{id}_{seo}_redownload.docx`
                instead of the main `{id}_{seo}.docx`.

        Raises:
            ValueError: if the book does not exist.
        """
        self._cancel_flag = False
        self._redownload = redownload

        self.db = get_database()
        self.cleaner = TextCleaner()

        self.book = self.db.get_book(book_id)
        if not self.book:
            raise ValueError(f"Book id={book_id} not found in database.")

        self.book_id = book_id
        # seo_title_basic is the ASCII slug (e.g. "su-ton-nguoi-mau") used in file names.
        self.book_name = self.book['seo_title_basic']
        # Per-book flag: render the DOCX automatically after a download finishes.
        # `bool(x)` turns the SQLite integer 0/1 into False/True.
        self.auto_export_docx = bool(self.book.get('auto_export_docx', 1))
        self.domain = TRUYENWIKI['book_domain']
        # urlparse("https://wikicv.org").hostname -> "wikicv.org" (used in request logs)
        self.domain_host = urlparse(self.domain).hostname or 'wikicv.org'
        # Access identities, tried in order when the site's access limit is hit:
        # guest first, then the primary account, then the extra accounts.
        # Built in _start_browser(); session_type follows the identity in use
        # ('non_session' = guest, 'session' = an account) for the request logs.
        self._identities = []
        self._identity_idx = 0
        self.session_type = 'non_session'
        # What to do when every identity is limited: 'stop' (book → paused) or
        # 'wait' (sleep N minutes, then start over from guest).
        # `(a or 'x').strip() or 'x'` = use the default when the setting is missing OR blank.
        self.limit_action = (self.db.get_setting('access_limit_action') or 'stop').strip() or 'stop'
        self.limit_wait_minutes = int(self.db.get_setting('access_limit_wait_minutes') or '60')
        self._limit_reached = False   # True once every identity is used up and we stop
        self._waiting_until = None    # epoch seconds while waiting for the quota to reset

        # Timing settings (strings in the DB → converted to int).
        self.page_load_timeout = int(self.db.get_setting('page_load_timeout') or '15')
        self.delay_min = int(self.db.get_setting('download_delay_min') or '4')
        self.delay_max = int(self.db.get_setting('download_delay_max') or '6')

        # Output paths. book_dir()/logs_dir() return absolute Path objects;
        # `Path / "name"` joins a file name onto the folder.
        suffix = "_redownload" if redownload else ""
        self.output_docx = book_dir() / f"{self.book_id}_{self.book_name}{suffix}.docx"
        self.success_log = logs_dir() / f"{self.book_id}_{self.book_name}_success.txt"
        self.failure_log = logs_dir() / f"{self.book_id}_{self.book_name}_failure.txt"

        self.driver = None  # created in _job()

        # Progress counters read by get_download_progress(). Initialised here so
        # polling works even before the first chapter starts.
        self._remaining_count = 0
        self._success_count = 0
        self._fail_count = 0
        self._current_index = 0
        self._current_title = ''

        # All chapters of the book, ordered by chapter_order (DB is the source of truth).
        self.chapters = self.db.get_chapters_by_book(self.book_id)
        if not self.chapters:
            print(f"{Fore.YELLOW}Warning: no chapters found for book id={book_id}. "
                  f"Run chapter extraction first.")

    # ------------------------------------------------------------------
    # Browser setup
    # ------------------------------------------------------------------

    def _start_browser(self):
        """Open Chrome (browser.make_driver) and start with the first identity (guest)."""
        self.driver = make_driver()
        self._identities = self._build_identities()
        self._use_identity(0)

    def _build_identities(self) -> list:
        """List the access identities in fallback order: guest, primary, extras.

        Returns:
            list of dicts {'label', 'session_type', 'cookies'}; cookies is None
            for guest, else the {name: value} dict to inject.

        An account without login cookies (never logged in) is skipped.
        """
        identities = [{'label': 'guest', 'session_type': 'non_session', 'cookies': None}]
        # get_cookies() always contains STATIC_COOKIES, so look for a real login cookie.
        primary = get_cookies()
        if any(primary.get(k) for k in COOKIE_KEYS):
            identities.append({'label': 'primary account', 'session_type': 'session', 'cookies': primary})
        for acc in self.db.get_site_accounts():
            cookies = json.loads(acc['cookies'] or '{}')
            if cookies:
                # `{**a, **b}` merges two dicts; b (static cookies) wins on duplicates,
                # matching get_cookies().
                identities.append({'label': acc['username'], 'session_type': 'session',
                                   'cookies': {**cookies, **STATIC_COOKIES}})
        return identities

    def _use_identity(self, idx: int):
        """Switch the browser to identity number `idx` (no Chrome restart).

        Side effects: deletes the browser's cookies for the current site, then
        (for an account) loads the home page and injects that account's cookies.
        """
        ident = self._identities[idx]
        self._identity_idx = idx
        self.session_type = ident['session_type']
        try:
            self.driver.delete_all_cookies()
        except Exception:  # fresh browser on a blank page: nothing to delete
            pass
        if ident['cookies']:
            inject_site_cookies(self.driver, ident['cookies'])
        print(f"{Fore.CYAN}Access identity: {ident['label']} ({idx + 1}/{len(self._identities)})")

    def _wait_for_limit_reset(self) -> bool:
        """Called when every identity is limited. Wait if the settings say so.

        Returns:
            True after waiting `access_limit_wait_minutes` (the caller starts
            over from guest); False when the action is 'stop' or the user
            cancelled during the wait.

        Sleeps in 1-second steps so Cancel takes effect quickly.
        """
        if self.limit_action != 'wait':
            return False
        self._waiting_until = time.time() + self.limit_wait_minutes * 60
        print(f"{Fore.YELLOW}All identities limited — waiting {self.limit_wait_minutes} min before retrying.")
        try:
            while time.time() < self._waiting_until and not self._cancel_flag:
                time.sleep(1)
        finally:
            self._waiting_until = None
        return not self._cancel_flag

    @contextmanager
    def _job(self):
        """Context manager wrapping one download job. Use as `with self._job(): ...`.

        `@contextmanager` turns this generator into a `with` block helper:
          - code before `yield` runs when the `with` block starts,
          - the body of the `with` block runs at the `yield`,
          - code in `finally` runs when the block ends — normally OR because
            of an exception.

        This guarantees the two invariants that used to break:
          1. Chrome is always closed (no orphan chrome.exe processes).
          2. The book is always unregistered (otherwise it stays "active"
             forever and every new download returns HTTP 409).

        Raises:
            RuntimeError: if a download is already running for this book.
        """
        if not register_download(self.book_id, self):
            raise RuntimeError(f"A download is already running for book id={self.book_id}.")
        try:
            self._start_browser()
            yield
        finally:
            if self.driver:
                try:
                    self.driver.quit()
                except Exception as e:  # browser may already be dead; never mask the real error
                    print(f"{Fore.YELLOW}Could not close Chrome cleanly: {e}")
                self.driver = None
            unregister_download(self.book_id)

    # ------------------------------------------------------------------
    # Per-chapter work
    # ------------------------------------------------------------------

    def log_event(self, log_path, message: str):
        """Append a timestamped line to a per-book log file (write-only audit trail).

        `'a'` opens the file in append mode (created if missing).
        `time.strftime('%X %x')` = local time + date, e.g. "14:03:12 10/18/26".
        """
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(f"{time.strftime('%X %x')}: {message}\n")

    def process_chapter(self, chapter: dict) -> tuple:
        """Download one chapter page, clean it, and save it to the DB.

        Args:
            chapter: a row from the `chapters` table (dict).

        Returns:
            (chapter_title, full_url)

        Raises:
            ValueError: for translated chapters (they have no web page).
            Exception: if the page fails to load or has no content.

        Side effects: updates chapters.chapter_title / chapter_content and
        writes a row to request_logs (success or failure).
        """
        chapter_url = chapter['chapter_url']
        # Translated books use placeholder URLs like "translate://12/3".
        if chapter_url.startswith("translate://"):
            raise ValueError(
                "Translated chapter — cannot be downloaded from the web. "
                "This book was created by the Translate tool; its DOCX is built by translation."
            )
        # Chapter URLs are stored relative ("/truyen/abc/chuong-1") so the domain
        # can change; old absolute URLs are still accepted.
        full_url = chapter_url if chapter_url.startswith("http") else self.domain + chapter_url

        # --- Load the page and wait for the chapter text ---
        t0 = time.time()
        try:
            load_page(self.driver, full_url)
            # WebDriverWait polls the page until the condition is true or the
            # timeout (seconds) passes; then it raises TimeoutException.
            # any_of = stop waiting as soon as EITHER the chapter text OR the
            # access-limit notice is on the page (no 15 s timeout on the limit page).
            wait = WebDriverWait(self.driver, self.page_load_timeout)
            wait.until(EC.any_of(
                EC.presence_of_element_located((By.CLASS_NAME, "content-body-wrapper")),
                EC.text_to_be_present_in_element((By.TAG_NAME, "body"), ACCESS_LIMIT_MARKER),
            ))
            duration_ms = int((time.time() - t0) * 1000)
        except Exception as e:
            duration_ms = int((time.time() - t0) * 1000)
            self.db.log_request("chapter", "failed", session_type=self.session_type,
                                domain=self.domain_host, url=full_url, book_id=self.book_id,
                                chapter_id=chapter["id"], error=str(e), duration_ms=duration_ms)
            raise  # bare `raise` re-raises the same exception to the caller

        # Anti-bot cooldown: random delay from DB settings (randint includes both ends).
        time.sleep(random.randint(self.delay_min, self.delay_max))

        # --- Parse + clean the rendered HTML (shared with the Text Cleaning test) ---
        try:
            title_text, body_text = parse_chapter_html(self.driver.page_source, self.cleaner)
        except AccessLimitError as e:
            # Own status so Statistics can tell quota hits from real failures.
            self.db.log_request("chapter", "limited", session_type=self.session_type,
                                domain=self.domain_host, url=full_url, book_id=self.book_id,
                                chapter_id=chapter["id"], error=str(e), duration_ms=duration_ms,
                                detail=self._identities[self._identity_idx]['label'])
            raise
        except ValueError as e:
            self.db.log_request("chapter", "failed", session_type=self.session_type,
                                domain=self.domain_host, url=full_url, book_id=self.book_id,
                                chapter_id=chapter["id"], error=str(e), duration_ms=duration_ms)
            raise

        self.db.update_chapter_title(chapter['id'], title_text)
        self.db.update_chapter_content(chapter['id'], body_text)

        self.db.log_request("chapter", "success", session_type=self.session_type,
                            domain=self.domain_host, url=full_url, book_id=self.book_id,
                            chapter_id=chapter["id"], detail=title_text, duration_ms=duration_ms)

        return title_text, full_url

    def _export_docx(self):
        """Render the book DOCX from DB content (the source of truth).

        Skipped when the book's `auto_export_docx` flag is off. Errors are
        printed, not raised: a failed export must not hide the download result.
        """
        if not self.auto_export_docx:
            print(f"{Fore.CYAN}Auto DOCX export disabled — skipping export.")
            return
        try:
            # Re-read chapters: their content changed during the batch.
            chapters = self.db.get_chapters_by_book(self.book_id)
            rules = build_render_rules(self.db, self.book)
            build_book_docx(self.book, chapters, rules, self.output_docx)
            print(f"{Fore.CYAN}--- DOCX exported: {self.output_docx} ---")
        except Exception as e:
            print(f"{Fore.RED}DOCX export failed: {e}")

    def _process_batch(self, chapters: list, log_tag: str = "") -> tuple:
        """Download a list of chapters one by one (shared by all run modes).

        Args:
            chapters: chapter rows to download, in order.
            log_tag: prefix for success-log lines, e.g. "[REDOWNLOAD] ".

        Returns:
            (success_count, fail_count, cancelled)

        A failure on one chapter is recorded (chapter → 'failed') and the loop
        continues with the next one. An access-limit page is NOT a failure:
        the chapter stays as it was, the next identity is used and the SAME
        chapter is retried; when no identity is left, `_wait_for_limit_reset`
        either waits and starts over, or sets `_limit_reached` and the loop stops. The DOCX is exported in `finally`, so
        whatever was downloaded is preserved even if the loop crashes.
        """
        self._remaining_count = len(chapters)
        self._success_count = self._fail_count = 0  # chained assignment: both become 0
        docx_label = self.output_docx.name  # `.name` = file name without folder
        cancelled = False

        try:
            # enumerate(..., 1) yields (1, ch1), (2, ch2), ... — index starts at 1.
            for index, chapter in enumerate(chapters, 1):
                self._current_index = index
                self._current_title = chapter['chapter_title']

                if self._cancel_flag:
                    print(f"{Fore.YELLOW}Download cancelled by user.")
                    cancelled = True
                    break

                # `while True` retries the same chapter: `continue` = try again
                # with the new identity, `break` = done with this chapter.
                while True:
                    try:
                        title, full_url = self.process_chapter(chapter)
                        self.log_event(self.success_log, f"{log_tag}{full_url}")
                        self.db.update_chapter_status(chapter_id=chapter['id'], status='completed',
                                                      file_path=docx_label)
                        self._success_count += 1
                        print(f"{Fore.GREEN}Success: {Fore.WHITE}{title} ({index}/{len(chapters)})")
                    except AccessLimitError:
                        label = self._identities[self._identity_idx]['label']
                        self.log_event(self.failure_log,
                                       f"{log_tag}{chapter['chapter_url']} | ACCESS LIMIT ({label})")
                        print(f"{Fore.YELLOW}Access limit reached for {label}.")
                        if self._identity_idx + 1 < len(self._identities):
                            self._use_identity(self._identity_idx + 1)
                            continue
                        if self._wait_for_limit_reset():
                            self._use_identity(0)
                            continue
                        # Stop only if the user did not cancel (cancel is handled below).
                        self._limit_reached = not self._cancel_flag
                    except Exception as e:
                        self.log_event(self.failure_log, f"{log_tag}{chapter['chapter_url']} | Error: {e}")
                        self.db.update_chapter_status(chapter_id=chapter['id'], status='failed',
                                                      error_message=str(e))
                        self._fail_count += 1
                        print(f"{Fore.RED}Failed: {chapter['chapter_title']} | Error: {e}")
                    break

                if self._limit_reached:
                    print(f"{Fore.YELLOW}Every access identity is limited — stopping.")
                    self.log_event(self.success_log, f"{log_tag}ACCESS LIMIT REACHED — stopped")
                    break

                # Be gentle with the server; no pause after the last chapter.
                if index < len(chapters):
                    # `*BETWEEN_CHAPTER_PAUSE` unpacks the tuple into two arguments.
                    time.sleep(random.randint(*BETWEEN_CHAPTER_PAUSE))
        finally:
            self._export_docx()

        # `or self._cancel_flag`: a cancel during the limit wait on the LAST
        # chapter never reaches the check at the top of the loop.
        return self._success_count, self._fail_count, cancelled or self._cancel_flag

    def _count_status(self, status: str) -> int:
        """Count this book's chapters with the given status (fresh from the DB)."""
        return sum(1 for c in self.db.get_chapters_by_book(self.book_id)
                   if c['download_status'] == status)

    def _finish(self, new_status: str | None, started: float, total: int):
        """Write the final book status + counts, log the run, print a summary.

        Args:
            new_status: final download_status, or None to leave it unchanged.
            started: time.time() when the batch started.
            total: number of chapters attempted in this run.
        """
        self.db.update_book_status(book_id=self.book_id, download_status=new_status,
                                   downloaded_chapters=self._count_status('completed'))
        if new_status:
            self.db.log_request(
                "book_download",
                "success" if new_status in ("completed", "completed_with_errors") else "failed",
                session_type=self.session_type, domain=self.domain_host,
                book_id=self.book_id, detail=new_status,
            )
        self._print_summary(self._success_count, self._fail_count, total, time.time() - started)

    # ------------------------------------------------------------------
    # Run modes (called by the module-level helpers below)
    # ------------------------------------------------------------------

    def run(self, max_chapters: int = None):
        """Download all PENDING chapters into the main DOCX.

        Args:
            max_chapters: process at most this many chapters in this session
                (rate limiting). None = no limit. If more remain, the book
                status becomes 'paused'.
        """
        if not self.chapters:
            print(f"{Fore.RED}No chapters to process for '{self.book_name}'. Extract chapters first.")
            return

        # Only 'pending' chapters (failed ones need Re-download).
        chapters_to_process = [c for c in self.chapters if c['download_status'] == 'pending']
        if not chapters_to_process:
            print(f"{Fore.GREEN}All chapters already downloaded for '{self.book_name}'!")
            return

        print(f"📚 Found {len(self.chapters)} total chapters. "
              f"{len(chapters_to_process)} pending.")

        limited = bool(max_chapters) and len(chapters_to_process) > max_chapters
        if limited:
            chapters_to_process = chapters_to_process[:max_chapters]  # slice: first N items
            print(f"🔢 Session limited to {max_chapters} chapters.")

        with self._job():
            self.db.update_book_status(book_id=self.book_id, download_status='in_progress')
            self.log_event(self.success_log, "RESUMING/STARTING SESSION")
            started = time.time()
            success, fail, cancelled = self._process_batch(chapters_to_process)

            if cancelled:
                new_status = 'cancelled'
            elif limited or self._limit_reached:
                # Unfinished chapters stay 'pending'; Download resumes from them.
                new_status = 'paused'
            elif fail == 0:
                new_status = 'completed'
            elif success == 0:
                new_status = 'failed'
            else:
                new_status = 'completed_with_errors'
            self._finish(new_status, started, len(chapters_to_process))

    def run_redownload(self, all_chapters: bool = False, count: int = None,
                       start_order: int = None, end_order: int = None):
        """Re-download chapters into the separate `_redownload.docx`.

        Selection (first match wins):
            count=N           → the first N chapters (by order)
            start/end_order   → chapters whose chapter_order is in [start, end]
            all_chapters=True → every chapter
            otherwise         → only 'failed' chapters

        The book status is only changed if the whole book ends up complete;
        a partial re-download keeps the previous status.
        """
        if not self.chapters:
            print(f"{Fore.RED}No chapters found for '{self.book_name}'")
            return

        if count is not None and count > 0:
            chapters_to_process = list(self.chapters[:count])
            label = f"first {count}"
        elif start_order is not None or end_order is not None:
            lo = start_order or 0
            hi = end_order or 10**9  # 10**9 = "no upper bound"
            # Chained comparison `lo <= x <= hi` = `lo <= x and x <= hi`.
            chapters_to_process = [c for c in self.chapters if lo <= c['chapter_order'] <= hi]
            label = f"order {lo}-{hi}"
        elif all_chapters:
            chapters_to_process = list(self.chapters)
            label = "all"
        else:
            chapters_to_process = [c for c in self.chapters if c['download_status'] == 'failed']
            label = "failed"

        if not chapters_to_process:
            print(f"{Fore.GREEN}No {label} chapters to re-download.")
            return

        print(f"{Fore.YELLOW}Re-downloading {len(chapters_to_process)} {label} chapter(s) into {self.output_docx}")
        with self._job():
            # Remember the status so a partial re-download doesn't mislabel the book.
            pre_status = self.book.get('download_status')
            self.db.update_book_status(book_id=self.book_id, download_status='in_progress')
            started = time.time()
            _, fail, cancelled = self._process_batch(chapters_to_process, log_tag="[REDOWNLOAD] ")

            # `_` is the conventional name for a value we don't need.
            remaining = self._count_status('pending') + self._count_status('failed')
            if cancelled:
                new_status = 'cancelled'
            elif not remaining:
                new_status = 'completed' if fail == 0 else 'completed_with_errors'
            else:
                new_status = pre_status or 'pending'
            self._finish(new_status, started, len(chapters_to_process))

    def run_single(self, chapter_id: int):
        """Download one chapter (from the chapter table's ⬇ button) into `_redownload.docx`.

        The book's download_status is left unchanged; only the downloaded count is refreshed.
        """
        # next(generator, default) returns the first match, or None if nothing matches.
        chapter = next((c for c in self.chapters if c['id'] == chapter_id), None)
        if not chapter:
            print(f"{Fore.RED}Chapter id={chapter_id} not found for book '{self.book_name}'")
            return

        with self._job():
            started = time.time()
            success, _, _ = self._process_batch([chapter], log_tag="[SINGLE] ")
            self.db.log_request("book_download", "success" if success else "failed",
                                session_type=self.session_type, domain=self.domain_host,
                                book_id=self.book_id, chapter_id=chapter_id,
                                detail="completed" if success else "failed")
            self._finish(None, started, 1)

    def _print_summary(self, success: int, fail: int, total: int, duration: float):
        """Print a run summary to the console."""
        print("\n" + "=" * 50)
        print("DOWNLOAD SESSION SUMMARY")
        print("=" * 50)
        print(f"{Fore.GREEN}Succeeded: {success}/{total}")
        print(f"{Fore.RED}Failed: {fail}/{total}")
        print(f"{Fore.CYAN}Duration: {duration:.2f} s")  # :.2f = 2 decimal places
        print(f"{Fore.YELLOW}Book: {self.book_name}")
        print(f"{Fore.BLUE}DOCX file: {self.output_docx}")


# ---------------------------------------------------------------------------
# Module-level helpers used by the API (each runs inside a background thread)
# ---------------------------------------------------------------------------

def download_book(book_id: int, max_chapters: int = None):
    """Download the pending chapters of a book (see TruyenWikiDownloader.run)."""
    TruyenWikiDownloader(book_id).run(max_chapters=max_chapters)


def redownload_book(book_id: int, all_chapters: bool = False,
                    count: int = None, start_order: int = None,
                    end_order: int = None):
    """Re-download chapters into _redownload.docx (see run_redownload for the selection rules)."""
    TruyenWikiDownloader(book_id, redownload=True).run_redownload(
        all_chapters=all_chapters, count=count, start_order=start_order, end_order=end_order)


def download_single_chapter(book_id: int, chapter_id: int):
    """Download one chapter into _redownload.docx."""
    TruyenWikiDownloader(book_id, redownload=True).run_single(chapter_id)
