"""Text Cleaning API: CRUD for the GLOBAL text-cleaning rules, plus a test tool
that downloads one chapter, cleans it and saves a throw-away DOCX.

Mounted in main.py under the prefix ``/api/text-cleaning``, so ``@router.get("/")``
here is really ``GET /api/text-cleaning/``.

All endpoints are plain ``def`` on purpose: FastAPI runs them in a thread pool,
so blocking work (sqlite, and /test which drives a real Chrome via Selenium)
does not freeze the asyncio event loop.

How the rules are used (see app/services/docx_exporter.py docstring):
  * downloaded books: rules are applied ONCE when a chapter is saved;
  * translated books: rules are applied at DOCX render time only (never stored).

Parameters here are all simple scalars with no ``Body(...)``, so FastAPI reads
them from the URL query string, e.g. ``POST /api/text-cleaning/?rule_type=..``.
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
import random
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from docx import Document
from app.database import get_database
from app.config import TRUYENWIKI, book_dir
from app.services.browser import inject_site_cookies, load_page, make_driver
from app.services.downloader import parse_chapter_html
from app.services.text_cleaner import TextCleaner

router = APIRouter()
db = get_database()

# Test files (test_<timestamp>.docx) are written to the book folder: config.book_dir().


@router.get("/")
def list_rules():
    """GET /api/text-cleaning/ -- list ALL rules (enabled and disabled).

    Response: list of rule dicts (id, rule_type, match_type, find_text,
    replace_text, enabled, sort_order, description, ...).
    """
    return db.get_text_cleaning_rules(enabled_only=False)


@router.post("/")
def add_rule(rule_type: str, match_type: str, find_text: str,
             replace_text: str = '', enabled: int = 1,
             sort_order: int = None, description: str = ''):
    """POST /api/text-cleaning/ -- create a rule (all fields as query params).

    Required: rule_type, match_type (e.g. plain text vs regex), find_text.
    Optional: replace_text (default '' = delete the match), enabled (1/0),
    sort_order (None = append at the end), description.

    Response: ``{"id": new_rule_id, "message": "Rule added"}``.
    Side effect: inserts a row in the rules table.
    """
    rule_id = db.add_text_cleaning_rule(
        rule_type=rule_type, match_type=match_type,
        find_text=find_text, replace_text=replace_text,
        enabled=enabled, sort_order=sort_order, description=description
    )
    return {"id": rule_id, "message": "Rule added"}


@router.put("/{rule_id}")
def update_rule(rule_id: int, rule_type: str = None, match_type: str = None,
                find_text: str = None, replace_text: str = None,
                enabled: int = None, sort_order: int = None, description: str = None):
    """PUT /api/text-cleaning/{rule_id} -- partial update of a rule.

    Only the query params actually sent (non-None) are changed.
    Errors: 404 if the rule does not exist.
    Side effect: updates the rule row.
    """
    # Python idiom: at the very start of a function, locals() is a dict of just
    # its parameters. Filtering out rule_id and None values leaves exactly the
    # fields the client sent, ready to pass on as **kwargs.
    # Caveat: this means a field can never be set to NULL via this endpoint.
    # (Any new local variable defined above this line would leak into kwargs.)
    kwargs = {k: v for k, v in locals().items() if k != 'rule_id' and v is not None}
    ok = db.update_text_cleaning_rule(rule_id, **kwargs)
    if not ok:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"message": "Rule updated"}


@router.put("/{rule_id}/reorder")
def reorder_rule(rule_id: int, new_order: int):
    """PUT /api/text-cleaning/{rule_id}/reorder?new_order=N -- move a rule.

    Rules run in sort_order, and order matters (one rule's output is the next
    rule's input). Side effect: renumbers sort_order in the DB.
    """
    db.reorder_text_cleaning_rule(rule_id, new_order)
    return {"message": "Rule reordered"}


@router.delete("/{rule_id}")
def delete_rule(rule_id: int):
    """DELETE /api/text-cleaning/{rule_id} -- delete a rule.

    Returns success even if the id did not exist (no 404 check).
    Side effect: deletes the rule row. Already-downloaded chapters keep the
    text they were cleaned into (cleaning happened at save time).
    """
    db.delete_text_cleaning_rule(rule_id)
    return {"message": "Rule deleted"}


@router.post("/test")
def test_cleaning(chapter_url: str):
    """
    Fetch a chapter URL synchronously, apply all enabled cleaning rules,
    and save as test.docx. Uses a unique filename per run so new rules
    always produce a fresh file.

    POST /api/text-cleaning/test?chapter_url=<absolute URL or site-relative path>

    Response: ``{"message", "filename": "test_<unix_ts>.docx",
    "download_url": "/api/text-cleaning/test/<filename>"}``.

    Errors: 500 if the page has no ``content-body-wrapper`` div; Selenium
    timeouts surface as a 500 too.

    Side effects: OPENS a headless Chrome (blocks this request for the whole
    page load), writes a new DOCX to the book folder (config.book_dir()). Old test files are never deleted.
    Does NOT touch the database.
    """
    ts = int(time.time())  # seconds since 1970 -> unique name per run
    filename = f"test_{ts}.docx"
    test_docx = book_dir() / filename

    # Same browser + parser as a real download (browser.make_driver and
    # downloader.parse_chapter_html), so the test shows exactly what would be stored.
    driver = make_driver(headless=True)
    # try/finally: driver.quit() ALWAYS runs, even on errors, so no orphan
    # Chrome processes are left behind.
    try:
        inject_site_cookies(driver)  # log in with the stored cookies

        full_url = chapter_url if chapter_url.startswith("http") else TRUYENWIKI['book_domain'] + chapter_url
        load_page(driver, full_url)
        # Wait up to 15 s for the chapter body to appear, then a small random pause
        # (human-like, and lets late JS finish).
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CLASS_NAME, "content-body-wrapper")))
        time.sleep(random.randint(2, 3))

        try:
            title, body = parse_chapter_html(driver.page_source, TextCleaner())
        except ValueError as e:  # the page has no chapter content
            raise HTTPException(status_code=500, detail=str(e))

        # One DOCX paragraph per stored paragraph (stored paragraphs are separated by a blank line).
        doc = Document()
        if title:
            doc.add_heading(title, level=1)
        for para in body.split("\n\n"):
            if para.strip():
                doc.add_paragraph(para)
        doc.save(str(test_docx))
        print(f"✅ Test DOCX saved to {test_docx}")

    finally:
        driver.quit()

    return {
        "message": "Test complete",
        "filename": filename,
        "download_url": f"/api/text-cleaning/test/{filename}"
    }


@router.get("/test/{filename}")
def get_test_docx(filename: str):
    """GET /api/text-cleaning/test/{filename} -- download a DOCX made by POST /test.

    Errors: 400 for a suspicious filename, 404 if the file does not exist.
    Response: the file itself (``FileResponse`` streams it from disk and sets the
    Content-Disposition header so the browser saves it as ``filename``).
    """
    # Guard against path traversal
    # The name must be a bare "test_..." file name: no "/" or "\" means it cannot
    # climb out of the book folder with "../". (A plain {filename} path param cannot
    # contain "/" anyway, but a URL-encoded "\" would reach us on Windows.)
    if '/' in filename or '\\' in filename or not filename.startswith('test_'):
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = book_dir() / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Test file not found. Run a test first.")
    return FileResponse(
        path=str(path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
