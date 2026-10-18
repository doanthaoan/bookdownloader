"""
Book info + chapter list extractor (Selenium).

Given a book page URL on the site, this module:
  - scrapes the book metadata (author, status, latest chapter, cover, tags,
    description) — `scrape_book_info`
  - collects the full chapter list, following the site's pagination
    (501 chapters per page) — `extract_chapter_list`
  - saves the book + chapters to the DB — `process_book_chapters`

Chapters are only ever APPENDED (`append_new_chapters`): existing chapter
rows, and the content already downloaded into them, are never deleted.
"""

import os
import random
import time
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from app.config import TRUYENWIKI, book_dir
from app.database import get_database
from app.services.browser import inject_site_cookies, load_page, make_driver


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
        extracted: list of {'title', 'url', 'order'} from extract_chapter_list().

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

    def extract_chapter_list(self, book_url: str) -> list:
        """Collect every chapter link of a book, following pagination.

        Returns:
            [{'order': 1, 'title': 'Chương 1 ...', 'url': '/truyen/.../chuong-1'}, ...]
            or [] if nothing was found / an error happened (logged).

        Pagination: the site shows 501 chapters per page; the pagination links
        carry a `data-start` attribute (0, 501, 1002, ...). We click the link
        whose data-start is the next page's start until there is none.
        """
        self._ensure_driver()

        t0 = time.time()
        try:
            # scrape_book_info usually just loaded this page — skip the second request.
            if self.driver.current_url.rstrip('/') != book_url.rstrip('/'):
                print(f"🔍 Loading book page: {book_url}")
                load_page(self.driver, book_url)
            all_chapters = []
            wait = WebDriverWait(self.driver, 20)

            # Candidate CSS selectors for chapter links, tried in order. The
            # first one that matches is used for the page.
            # TODO: each miss waits up to 20 s; once the working selector is known
            #       (likely "li.chapter-name a"), put it first or keep only it.
            chapter_selectors = [
                "ul.chapter-list a",
                "div.chapter-list a",
                "li.chapter-name a",
                ".list-chapter a",
                "#chapter-list a",
                "a[href*='chapter']",          # fallback: any link with 'chapter' in the URL
            ]

            current_start = 0
            while True:
                for selector in chapter_selectors:
                    try:
                        elements = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, selector)))
                        if elements:
                            for el in elements:
                                url = normalize_url(el.get_attribute('href'))
                                title = el.text.strip() or "Untitled Chapter"
                                if url:
                                    all_chapters.append({'order': len(all_chapters) + 1, 'title': title, 'url': url})
                            break  # stop trying selectors for this page
                    except TimeoutException:
                        continue  # selector not on the page → try the next one

                # --- Go to the next page of the chapter list, if any ---
                try:
                    pagination_links = self.driver.find_elements(By.CSS_SELECTOR, ".volume-list ul.pagination a")
                    next_start = current_start + 501
                    # Find the link for the next page (None if this is the last page).
                    target_link = next((link for link in pagination_links
                                        if link.get_attribute('data-start') == str(next_start)), None)
                    if target_link:
                        print(f"📄 Loading next page (start={next_start})...")
                        target_link.click()
                        current_start = next_start
                        # TODO: the list is reloaded by AJAX; waiting for the old
                        #       elements to go stale would be safer than a fixed sleep.
                        time.sleep(random.randint(2, 4))
                    else:
                        break
                except NoSuchElementException:
                    break

                if len(all_chapters) > 10000:  # safety stop against an endless loop
                    break

            if not all_chapters:
                raise Exception("No chapters found on the page")

            print(f"✅ Successfully extracted {len(all_chapters)} chapters.")
            self.db.log_request("chapter_list", "success", session_type=self.session_type,
                                domain=self.domain_host, url=book_url,
                                detail=f"{len(all_chapters)} chapters",
                                duration_ms=int((time.time() - t0) * 1000))
            return all_chapters

        except Exception as e:
            self.db.log_request("chapter_list", "failed", session_type=self.session_type,
                                domain=self.domain_host, url=book_url, error=str(e),
                                duration_ms=int((time.time() - t0) * 1000))
            print(f"❌ Failed to extract chapter list from {book_url}: {e}")
            return []

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
            chapters = self.extract_chapter_list(book_url)
            if not chapters:
                print(f"⚠️ Book saved (ID: {book_id}) but no chapters extracted for {book_title}. Retry later.")
                self.db.log_request("book_extract", "failed", session_type=self.session_type,
                                    domain=self.domain_host, url=book_url, book_id=book_id,
                                    error="Book info saved, chapter list extraction failed")
                return False

            # 4. Append only chapters we don't have yet (never deletes existing ones).
            added = append_new_chapters(book_id, chapters)

            self.db.log_request("book_extract", "success", session_type=self.session_type,
                                domain=self.domain_host, url=book_url, book_id=book_id,
                                detail=f"{len(chapters)} chapters, {added} new")
            print(f"✅ Successfully processed {book_title}: {len(chapters)} found, {added} new")
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
