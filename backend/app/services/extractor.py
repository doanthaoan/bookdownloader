"""
Book info + chapter list extractor (Selenium).

Given a book page URL on the site, this module:
  - scrapes the book metadata (author, status, latest chapter, cover, tags,
    description) — `scrape_book_info`
  - collects the chapter list, following the site's pagination
    (501 chapters per page), saving each page to the DB as soon as it is
    read — `extract_chapter_list`
  - saves the book + chapters to the DB — `process_book_chapters`

Chapters are only ever APPENDED (`append_new_chapters`): existing chapter
rows, and the content already downloaded into them, are never deleted.
"""

import os
import time
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from app.config import TRUYENWIKI, book_dir
from app.database import get_database
from app.services.browser import inject_site_cookies, load_page, make_driver

# Chapters per page of the site's chapter list (pagination data-start step).
PAGE_SIZE = 501


def download_cover_image(book_id: int, seo_title_basic: str, image_url: str, save_dir=None) -> str | None:
    """Download a book cover image to the book folder.

    Args:
        book_id, seo_title_basic: used to build the file name `{id}_{seo}{ext}`
            (the same name GET /books/{id}/cover and the DOCX exporter look for).
        image_url: absolute URL of the image.
        save_dir: folder to save into; defaults to config.book_dir().

    Returns:
        The saved file name, or None on failure (errors are logged, not raised,
        because a missing cover must never break book extraction).
    """
    if not image_url:
        return None
    db = get_database()
    save_dir = save_dir or book_dir()
    domain_host = urlparse(TRUYENWIKI['book_domain']).hostname or 'wikicv.org'
    # Take the extension from the URL path (ignore any "?query"); default to .jpg.
    # os.path.splitext("a/b.png") -> ("a/b", ".png")
    ext = os.path.splitext(image_url.split('?')[0])[1] or '.jpg'
    filename = f"{book_id}_{seo_title_basic}{ext}"
    filepath = os.path.join(save_dir, filename)
    t0 = time.time()
    try:
        # A plain HTTP GET is enough for images (no browser / login needed).
        r = requests.get(image_url, timeout=15)
        r.raise_for_status()  # raises an exception for 4xx/5xx responses
        with open(filepath, 'wb') as f:  # 'wb' = write binary (image bytes)
            f.write(r.content)
        db.log_request("cover_image", "success", session_type="non_session",
                       domain=domain_host, url=image_url, book_id=book_id,
                       duration_ms=int((time.time() - t0) * 1000))
        print(f"🖼️ Cover image saved: {filepath}")
        return filename
    except Exception as e:
        db.log_request("cover_image", "failed", session_type="non_session",
                       domain=domain_host, url=image_url, book_id=book_id,
                       error=str(e), duration_ms=int((time.time() - t0) * 1000))
        print(f"⚠️ Failed to download cover image: {e}")
        return None


def normalize_url(url: str) -> str:
    """Convert an absolute URL to a relative one (path + query).

    "https://wikicv.org/truyen/abc?x=1" -> "/truyen/abc?x=1".
    Relative URLs are returned unchanged. Storing relative URLs keeps the DB
    valid if the site changes its domain.
    """
    if not url:
        return url
    parsed = urlparse(url)
    if parsed.scheme:  # has "https" → absolute URL
        relative = parsed.path
        if parsed.query:
            relative += '?' + parsed.query
        return relative
    return url


def append_new_chapters(book_id: int, extracted: list) -> int:
    """Add extracted chapters that are not in the DB yet. Never deletes anything.

    Shared by first extraction, re-extraction of an existing title,
    Continue Extract and Update & Download.

    Args:
        book_id: the book to append to.
        extracted: list of {'title', 'url'} in site order (one page of
            extract_chapter_list(), or any longer list).

    Returns:
        Number of chapters added.

    Side effects:
        - inserts rows into `chapters` with chapter_order continuing after
          the current maximum,
        - updates books.total_chapters,
        - sets download_status='ready_for_download' when the book had no
          chapters before (first extraction, or an earlier list failure).
    """
    db = get_database()
    existing = db.get_chapters_by_book(book_id)
    # A set gives O(1) "is this URL already known?" checks. We also add each
    # new URL to it, so a URL listed twice on the site is inserted only once
    # (the table has UNIQUE(book_id, chapter_url), a duplicate would crash).
    known_urls = {c['chapter_url'] for c in existing}
    # max(..., default=0) avoids an error when the book has no chapters yet.
    next_order = max((c['chapter_order'] for c in existing), default=0)

    added = 0
    for ch in extracted:
        if ch['url'] in known_urls:
            continue
        known_urls.add(ch['url'])
        next_order += 1
        db.add_chapter(book_id=book_id, chapter_order=next_order,
                       chapter_title=ch['title'], chapter_url=ch['url'])
        added += 1

    # download_status=None means "leave unchanged" (see update_book_status).
    # TODO: a 'completed' book that gets new chapters keeps status 'completed'
    #       although it now has pending chapters; consider switching it to 'paused'.
    db.update_book_status(book_id=book_id, total_chapters=len(existing) + added,
                          download_status=None if existing else 'ready_for_download')
    print(f"💾 Added {added} new chapter(s) to book ID {book_id} (total: {len(existing) + added})")
    return added


class ChapterListExtractor:
    """Owns one Chrome session for scraping book pages. Call close() when done."""

    def __init__(self):
        self.driver = None  # created lazily on first use
        self.db = get_database()
        self.domain_host = urlparse(TRUYENWIKI['book_domain']).hostname or 'wikicv.org'
        self.session_type = 'session'  # extraction always uses the logged-in cookies

    def _ensure_driver(self):
        """Start Chrome (browser.make_driver) and log in with the stored cookies,
        the first time a page is needed. Later calls reuse the same browser."""
        if not self.driver:
            self.driver = make_driver()
            inject_site_cookies(self.driver)

    def scrape_book_info(self, book_url: str) -> dict:
        """Scrape book metadata from the book's info page.

        Returns:
            dict with any of: cover_image_url, tags (list[str]),
            short_description, author, book_web_status, last_chapter_url,
            last_chapter_title, last_update_date. Keys that are not found on
            the page are simply missing. Returns {} (or a partial dict) on
            failure — errors are logged, not raised.

        The labels matched below ('Tác giả:', 'Tình trạng:', ...) are the
        Vietnamese texts shown on the site, so they must stay in Vietnamese.
        """
        self._ensure_driver()

        info = {}
        t0 = time.time()
        try:
            load_page(self.driver, book_url)
            time.sleep(3)  # give the page's JavaScript time to fill in the content
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')

            # --- Cover image --- (CSS selector: <img> inside <div class="cover-wrapper">)
            img_tag = soup.select_one('div.cover-wrapper img')
            if img_tag and img_tag.get('src'):
                src = img_tag['src']
                if src.startswith('/'):  # relative URL → make it absolute for requests.get
                    src = TRUYENWIKI['book_domain'] + src
                info['cover_image_url'] = src

            # --- Tags ("Thể loại:" = genre, the first <p> of div.book-desc) ---
            book_desc = soup.find('div', class_='book-desc')
            if book_desc:
                first_p = book_desc.find('p')
                if first_p and first_p.get_text(strip=True).startswith('Thể loại:'):
                    tags = [a.get_text(strip=True) for a in first_p.find_all('a') if a.get_text(strip=True)]
                    if tags:
                        info['tags'] = tags

            # --- Short description ---
            desc_tag = soup.find('div', class_='book-desc-detail')
            if desc_tag:
                # get_text('\n') puts a newline between child elements, keeping paragraphs.
                raw = desc_tag.get_text('\n')
                info['short_description'] = '\n\n'.join(
                    line.strip() for line in raw.split('\n') if line.strip()
                )

            # --- Fields inside div.cover-info ---
            cover = soup.find('div', class_='cover-info')
            if not cover:
                print("⚠️ Could not find cover-info section")
                return info

            for p in cover.find_all('p'):
                text = p.get_text(strip=True)

                if text.startswith('Tác giả:'):            # Author
                    a = p.find('a')
                    if a:
                        info['author'] = a.get_text(strip=True)

                elif text.startswith('Tình trạng:'):       # Status (ongoing/completed...)
                    a = p.find('a')
                    if a:
                        info['book_web_status'] = a.get_text(strip=True)

                elif text.startswith('Mới nhất:'):         # Latest chapter
                    a = p.find('a')
                    if a:
                        info['last_chapter_url'] = normalize_url(a.get('href', ''))
                        info['last_chapter_title'] = a.get_text(strip=True)

                elif text.startswith('Thời gian đổi mới:'):  # Last update time
                    span = p.find('span')
                    if span:
                        info['last_update_date'] = span.get_text(strip=True)

            print(f"📖 Book info scraped: author={info.get('author')}, status={info.get('book_web_status')}")
            self.db.log_request("book_page", "success", session_type=self.session_type,
                                domain=self.domain_host, url=book_url,
                                duration_ms=int((time.time() - t0) * 1000))
        except Exception as e:
            self.db.log_request("book_page", "failed", session_type=self.session_type,
                                domain=self.domain_host, url=book_url, error=str(e),
                                duration_ms=int((time.time() - t0) * 1000))
            print(f"❌ Failed to scrape book info: {e}")

        return info

    def _read_chapter_page(self, selectors: list) -> list:
        """Read the chapter links currently shown in the browser.

        Args:
            selectors: candidate CSS selectors, tried in order. The first one
                that matches is moved to the front of the list (the list is
                mutated in place), so later pages don't pay the 20 s timeout
                for each selector that misses.

        Returns:
            [{'title', 'url'}, ...] in page order, or [] if no selector matched.
        """
        wait = WebDriverWait(self.driver, 20)
        for selector in selectors:
            try:
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
            except TimeoutException:
                continue  # selector not on the page → try the next one
            # Parse the HTML once with BeautifulSoup instead of asking Chrome
            # for href + text of each link (2 WebDriver calls per chapter).
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            page = []
            for a in soup.select(selector):
                url = normalize_url(a.get('href', ''))
                if url:
                    page.append({'title': a.get_text(strip=True) or "Untitled Chapter", 'url': url})
            selectors.remove(selector)
            selectors.insert(0, selector)
            return page  # safe: we leave the loop right after mutating the list
        return []

    def _click_page_toward(self, current: int, target: int, selector: str) -> int | None:
        """Click the pagination link that gets closest to page `target`
        without passing it, and wait until the chapter list shows that page.

        Args:
            current: data-start of the page shown now.
            target: data-start we want to reach (current + PAGE_SIZE = next page).
            selector: the chapter-link selector known to work (used to detect
                that the list really changed).

        Returns:
            The data-start of the page now shown, or None if no pagination
            link moves forward (last page reached / jump not possible).

        Raises:
            TimeoutException if the list did not change within 20 s. Better to
            fail (pages so far are saved) than to re-read the old page and
            then miss the real next one.
        """
        # Pagination links carry data-start (0, 501, 1002, ...). Keep the
        # numeric ones strictly between current and target (inclusive).
        starts = {}
        for link in self.driver.find_elements(By.CSS_SELECTOR, ".volume-list ul.pagination a"):
            ds = link.get_attribute('data-start') or ''
            if ds.isdigit() and current < int(ds) <= target:
                starts[int(ds)] = link
        if not starts:
            return None
        best = max(starts)  # the furthest page we can reach in one click

        # Remember the first chapter URL shown now, to notice when the AJAX
        # reload has replaced the list.
        try:
            old_first = normalize_url(self.driver.find_element(By.CSS_SELECTOR, selector).get_attribute('href'))
        except NoSuchElementException:
            old_first = None

        print(f"📄 Loading chapter page (start={best})...")
        starts[best].click()
        if old_first is None:
            time.sleep(3)  # nothing to compare against → fall back to a fixed wait
        else:
            # Poll (every 0.5 s by default) until the first link is a different
            # chapter. While the list is being replaced, the element can be
            # missing or "stale" (removed from the page) — ignore those and retry.
            WebDriverWait(self.driver, 20,
                          ignored_exceptions=(NoSuchElementException, StaleElementReferenceException)
                          ).until(lambda d: normalize_url(
                              d.find_element(By.CSS_SELECTOR, selector).get_attribute('href')) != old_first)
        return best

    def extract_chapter_list(self, book_url: str, book_id: int) -> tuple[int, bool]:
        """Collect the chapter links of a book, following pagination, and
        save each page to the DB (append_new_chapters) as soon as it is read.

        Saving per page means an error on page N keeps pages 1..N-1, so a
        retry (Continue Extract) only adds what is still missing.

        Resume: if the book already has chapters, we jump straight to the
        page that should hold our newest saved chapter and continue from
        there. If that chapter is not on that page (the site removed or
        reordered chapters), we fall back to a full scan from page 1.

        Args:
            book_url: the book's page on the site.
            book_id: the DB book the chapters are appended to.

        Returns:
            (added, ok): number of NEW chapters saved, and False if the run
            failed or found nothing (logged). `added` can be > 0 with ok=False
            when it failed part-way.
        """
        self._ensure_driver()

        t0 = time.time()
        found = added = 0  # chained assignment: both start at 0
        try:
            # scrape_book_info usually just loaded this page — skip the second request.
            if self.driver.current_url.rstrip('/') != book_url.rstrip('/'):
                print(f"🔍 Loading book page: {book_url}")
                load_page(self.driver, book_url)

            # Candidate CSS selectors for chapter links (see _read_chapter_page).
            selectors = [
                "ul.chapter-list a",
                "div.chapter-list a",
                "li.chapter-name a",
                ".list-chapter a",
                "#chapter-list a",
                "a[href*='chapter']",          # fallback: any link with 'chapter' in the URL
            ]

            current_start = 0
            page = self._read_chapter_page(selectors)  # page 1 (also finds the selector)

            # --- Resume from the page holding our newest saved chapter ---
            existing = self.db.get_chapters_by_book(book_id)
            # Our chapter_order is 1..N in site order, so chapter N sits on the
            # page starting at (N-1)//PAGE_SIZE*PAGE_SIZE (// = integer division).
            resume_start = (len(existing) - 1) // PAGE_SIZE * PAGE_SIZE if existing else 0
            if resume_start and page:
                newest_url = max(existing, key=lambda c: c['chapter_order'])['chapter_url']
                # Walk toward the page; usually one click if the link is shown.
                # Walrus `:=` assigns and tests in one expression.
                while (current_start < resume_start and
                       (nxt := self._click_page_toward(current_start, resume_start, selectors[0])) is not None):
                    current_start = nxt
                page = self._read_chapter_page(selectors)
                if any(c['url'] == newest_url for c in page):
                    print(f"⏩ Resumed at page start={current_start} (skipped {current_start} known chapters)")
                else:
                    print("↩️ Newest saved chapter not on the expected page — full scan from page 1")
                    load_page(self.driver, book_url)
                    current_start = 0
                    page = self._read_chapter_page(selectors)

            while True:
                # Save this page now, so an error on a later page doesn't lose it.
                if page:
                    found += len(page)
                    added += append_new_chapters(book_id, page)
                else:
                    print(f"⚠️ No chapter links found on page start={current_start}")

                # Next page, if any. _click_page_toward only moves forward,
                # so this loop always ends.
                nxt = self._click_page_toward(current_start, current_start + PAGE_SIZE, selectors[0])
                if nxt is None:
                    break
                current_start = nxt
                page = self._read_chapter_page(selectors)

            if not found:
                raise Exception("No chapters found on the page")

            # `found` counts scanned chapters only (pages skipped by resume are not included).
            print(f"✅ Successfully extracted {found} chapters ({added} new).")
            self.db.log_request("chapter_list", "success", session_type=self.session_type,
                                domain=self.domain_host, url=book_url, book_id=book_id,
                                detail=f"{found} chapters, {added} new",
                                duration_ms=int((time.time() - t0) * 1000))
            return added, True

        except Exception as e:
            # Pages read before the error are already saved; report them.
            self.db.log_request("chapter_list", "failed", session_type=self.session_type,
                                domain=self.domain_host, url=book_url, book_id=book_id,
                                error=f"{e} (saved {found} found / {added} new before failing)",
                                duration_ms=int((time.time() - t0) * 1000))
            print(f"❌ Failed to extract chapter list from {book_url} after {found} chapters: {e}")
            return added, False

    def save_book_info(self, book_id: int, seo_title_basic: str, info: dict):
        """Store scraped metadata on an existing book: fields, tags and cover image.

        Shared by extraction, Refresh Info, Continue Extract and Update & Download.
        """
        if info:
            self.db.update_book_info(book_id, **info)  # `**info` passes the dict as keyword args
        if info.get('tags'):
            self.db.set_book_tags(book_id, info['tags'])
        if info.get('cover_image_url'):
            download_cover_image(book_id, seo_title_basic, info['cover_image_url'])

    def process_book_chapters(self, book_url: str, book_title: str) -> bool:
        """Full extraction for the Extraction page: book info + chapter list → DB.

        If a book with this title already exists, its info is refreshed and only
        NEW chapters are appended (downloaded content is kept).

        Returns:
            True on success, False if the chapter list could not be extracted
            (the book row is still saved, so Continue Extract can retry later).
        """
        print(f"\n📖 Processing book: {book_title}")
        print(f"🔗 URL: {book_url}")

        try:
            # 1. Scrape metadata first.
            book_info = self.scrape_book_info(book_url)

            # 2. Get or create the book row.
            # TODO: match on book_url instead of title — two different books can share a title.
            book = self.db.get_book_by_title(book_title)
            if book:
                book_id = book['id']
                print(f"📚 Found existing book in DB: {book_title} (ID: {book_id})")
                self.save_book_info(book_id, book['seo_title_basic'], book_info)
            else:
                book_id = self.db.add_book(
                    title=book_title,
                    book_url=book_url,
                    author=book_info.get('author'),
                    book_web_status=book_info.get('book_web_status'),
                    last_chapter_url=book_info.get('last_chapter_url'),
                    last_chapter_title=book_info.get('last_chapter_title'),
                    last_update_date=book_info.get('last_update_date'),
                    cover_image_url=book_info.get('cover_image_url'),
                    short_description=book_info.get('short_description')
                )
                new_book = self.db.get_book(book_id)
                if book_info.get('tags'):
                    self.db.set_book_tags(book_id, book_info['tags'])
                if book_info.get('cover_image_url'):
                    download_cover_image(book_id, new_book['seo_title_basic'], book_info['cover_image_url'])
                print(f"📚 Added new book to DB: {book_title} (ID: {book_id})")
                self.db.log_request("book_added", "success", session_type=self.session_type,
                                    domain=self.domain_host, url=book_url, book_id=book_id,
                                    detail=book_title)

            # 3. Extract chapters AFTER the book is saved, so a chapter-list failure
            #    keeps the book info; chapters can be fetched later via Continue Extract.
            #    Each page is appended as it is read (only chapters we don't have yet).
            added, ok = self.extract_chapter_list(book_url, book_id)
            if not ok:
                print(f"⚠️ Book saved (ID: {book_id}) but chapter list incomplete for {book_title} "
                      f"({added} saved). Use Continue Extract to finish.")
                self.db.log_request("book_extract", "failed", session_type=self.session_type,
                                    domain=self.domain_host, url=book_url, book_id=book_id,
                                    error=f"Book info saved, chapter list incomplete ({added} chapters saved)")
                return False

            self.db.log_request("book_extract", "success", session_type=self.session_type,
                                domain=self.domain_host, url=book_url, book_id=book_id,
                                detail=f"{added} new chapters")
            print(f"✅ Successfully processed {book_title}: {added} new")
            return True

        except Exception as e:
            self.db.log_request("book_extract", "failed", session_type=self.session_type,
                                domain=self.domain_host, url=book_url, error=str(e))
            print(f"❌ Failed to process book {book_title}: {e}")
            return False

    def close(self):
        """Quit Chrome (safe to call more than once)."""
        if self.driver:
            self.driver.quit()
            self.driver = None


def extract_chapters_for_book(book_url: str, book_title: str) -> bool:
    """Run a full extraction with its own Chrome session (always closed afterwards).

    `try/finally` guarantees close() runs even when process_book_chapters raises.
    """
    extractor = ChapterListExtractor()
    try:
        return extractor.process_book_chapters(book_url, book_title)
    finally:
        extractor.close()
