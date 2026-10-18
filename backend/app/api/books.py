"""Books API: list/search books, extract chapter lists, download chapters,
export DOCX files, corrections preview, covers, tags and "check for updates".

Mounted in main.py under the prefix ``/api/books``, so ``@router.get("/{book_id}")``
here is really ``GET /api/books/{book_id}``.

Why every endpoint is a plain ``def`` (not ``async def``): FastAPI runs plain
``def`` endpoints in a thread pool. Much of the work here blocks for a long time
(sqlite queries, Selenium driving a real Chrome to scrape the site), and doing
that inside ``async def`` would freeze the single asyncio event loop -- i.e.
every other request, including the progress polling, would hang.

Long jobs (extract, download, update) are handed to FastAPI ``BackgroundTasks``:
the task function runs AFTER the HTTP response has been sent, so the browser
gets "started" right away and polls ``/{book_id}/progress`` afterwards.

Invariant (see app/services/docx_exporter.py): the DB is the source of truth.
DOCX files are always derived from it; corrections are applied at render time
and never written back into chapter content.

Route ORDER matters: FastAPI tries routes in the order they are declared and
uses the first one whose path matches. ``/tags`` must be declared before
``/{book_id}``, otherwise "tags" would match ``{book_id}`` and fail int
validation with a 422.
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks, Query, Body, UploadFile, File
from pathlib import Path
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from typing import List, Dict, Optional
import os
import sqlite3
import shutil
from app.database import get_database
from app.services.extractor import ChapterListExtractor, append_new_chapters, extract_chapters_for_book
from app.services.downloader import (download_book, cancel_download, get_download_progress,
                                     is_download_active, redownload_book, download_single_chapter)
from app.services.translator import get_translation_progress
from app.services.docx_exporter import (build_book_docx, build_render_rules,
                                        apply_rules, apply_paragraphs,
                                        collapse_blank_lines,
                                        diff_rules, diff_paragraphs, chapter_text)
from app.config import book_dir

router = APIRouter()
# Module-level singleton DB helper shared by all endpoints in this file.
db = get_database()



# ---------------------------------------------------------------------------
# DOCX file helpers — every book DOCX is named {book_id}_{seo_title_basic}{suffix}.docx
# in config.book_dir(). Suffixes in use:
#   ""             main file (download / translate)
#   "_redownload"  re-downloaded chapters
#   "_corrected"   Export Corrected
#   "_retranslate" re-translated chapters (used by api/translate.py)
# ---------------------------------------------------------------------------

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def get_book_or_404(book_id: int) -> dict:
    """Load a book row, or raise HTTP 404 if it doesn't exist."""
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    return book


def docx_path(book: dict, suffix: str = "") -> Path:
    """Absolute path of one of a book's DOCX files (the file may not exist yet)."""
    return book_dir() / f"{book['id']}_{book['seo_title_basic']}{suffix}.docx"


def docx_info(book: dict, suffix: str = "") -> dict:
    """File info used by the *-docx-info endpoints.

    Returns:
        {"exists": bool, "file_name": str, "file_path": absolute path or None,
         "size": bytes (0 if missing)}. A missing FILE is not an error.
    """
    path = docx_path(book, suffix)
    exists = path.exists()
    return {
        "exists": exists,
        "file_name": path.name,
        "file_path": str(path.resolve()) if exists else None,
        "size": path.stat().st_size if exists else 0,
    }


def docx_response(book: dict, suffix: str, missing_detail: str) -> FileResponse:
    """Stream one of a book's DOCX files to the browser, or raise 404 with `missing_detail`.

    `FileResponse` reads the file from disk; `filename=` sets the
    Content-Disposition header so the browser saves it under that name.
    """
    path = docx_path(book, suffix)
    if not path.exists():
        raise HTTPException(status_code=404, detail=missing_detail)
    return FileResponse(path=str(path), filename=path.name, media_type=DOCX_MEDIA_TYPE)

def _ensure_idle(book_id: int):
    """Raise HTTP 409 Conflict if a download or translation is running for this book.

    Used by endpoints that change a book's chapters (delete, continue-extract,
    update-full) so they can't interfere with a job reading/writing them.

    Raising HTTPException from a helper works because FastAPI catches it
    wherever it is raised during the request and turns it into the error response.
    """
    if is_download_active(book_id):
        raise HTTPException(status_code=409, detail="A download is running for this book. Cancel it first.")
    progress = get_translation_progress(book_id)
    if progress and progress.get("active"):
        raise HTTPException(status_code=409, detail="A translation is running for this book. Cancel it first.")


class UpdateBookInfoRequest(BaseModel):
    """JSON body for PUT /api/books/{book_id}.

    Every field is Optional with default None, so the client sends only what it
    wants to change. None = "leave as is"; an empty/blank string = "clear it"
    (except title, which can't be cleared).
    """
    title: Optional[str] = None
    author: Optional[str] = None
    short_description: Optional[str] = None
    # Status shown on the source site, e.g. 'Còn tiếp' (Vietnamese: "ongoing").
    book_web_status: Optional[str] = None
    cover_image_url: Optional[str] = None

@router.get("/")
def get_all_books(search: str = None, status: str = None, author: str = None,
                         book_web_status: str = None, sent: int = None, tag: str = None,
                         page: int = 1, per_page: int = 50):
    """Fetch all books with optional search, status filter, author, book_web_status, sent, and pagination.

    GET /api/books/

    Query params (all optional, combined with AND):
        search:          substring of title or seo_title_basic
        status:          exact download_status ('pending', 'completed', ...)
        author:          substring of author
        book_web_status: exact site status (e.g. 'Còn tiếp' = ongoing)
        sent:            1/0 -- the "sent" flag
        tag:             exact tag name
        page, per_page:  1-based pagination (default 1, 50)

    Response: ``{"total", "page", "per_page", "total_pages", "books": [{... book
    columns ..., "tags": [names]}]}``. Favorites first, then newest first.

    How the dynamic WHERE is built (and why it is safe):
        Each active filter appends a SQL fragment containing only ``?``
        placeholders to ``conditions`` and its value to ``params``, in the same
        order. The fragments are fixed strings written in this file, never user
        text, so the f-string only ever splices trusted SQL; user values travel
        separately through ``params`` and sqlite binds them safely. That is what
        prevents SQL injection -- never f-string a user value into SQL.
        Example: search="abc", sent=1 ->
            WHERE (title LIKE ? OR seo_title_basic LIKE ?) AND is_sent = ?
            params = ["%abc%", "%abc%", 1]
    """
    # TODO: page/per_page are unvalidated: per_page=0 crashes with ZeroDivisionError
    # (HTTP 500) in total_pages. Declare them as Query(1, ge=1) / Query(50, ge=1, le=200).
    conn = db._get_connection()
    # Row factory makes rows behave like dicts (row['title']) so dict(r) works below.
    # Note: this sets it on the shared per-thread connection, not just this query.
    conn.row_factory = sqlite3.Row

    conditions = []
    params = []

    if search:
        conditions.append("(title LIKE ? OR seo_title_basic LIKE ?)")
        # % is the SQL LIKE wildcard: "%abc%" = contains "abc".
        params.extend([f"%{search}%", f"%{search}%"])
    if status:
        conditions.append("download_status = ?")
        params.append(status)
    if author:
        conditions.append("author LIKE ?")
        params.append(f"%{author}%")
    if book_web_status:
        conditions.append("book_web_status = ?")
        params.append(book_web_status)
    # `is not None` (not just `if sent:`) so that sent=0 still filters.
    if sent is not None:
        conditions.append("is_sent = ?")
        params.append(sent)
    if tag:
        # Sub-query: ids of books linked to a tag with this name (many-to-many table).
        conditions.append("id IN (SELECT book_id FROM book_tags bt JOIN tags t ON t.id = bt.tag_id WHERE t.name = ?)")
        params.append(tag)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    # Total count
    count_row = conn.execute(f"SELECT COUNT(*) FROM books {where}", params).fetchone()
    total = count_row[0]

    # Paginated results — favorites first, then by creation date
    offset = (page - 1) * per_page
    # LIMIT/OFFSET values are also bound as placeholders; `params + [...]` builds
    # a new list so the count query's params stay untouched.
    rows = conn.execute(
        f"SELECT * FROM books {where} ORDER BY is_favorite DESC, created_at DESC LIMIT ? OFFSET ?",
        params + [per_page, offset]
    ).fetchall()

    books = [dict(r) for r in rows]

    # Batch-load tags for all returned books
    # One query for all books instead of one per book (avoids the "N+1 query"
    # problem). `','.join('?' * 3)` -> "?,?,?" : one placeholder per id.
    if books:
        book_ids = [b['id'] for b in books]
        placeholders = ','.join('?' * len(book_ids))
        tag_rows = conn.execute(f"""
            SELECT bt.book_id, t.name FROM book_tags bt
            JOIN tags t ON t.id = bt.tag_id
            WHERE bt.book_id IN ({placeholders})
            ORDER BY t.name
        """, book_ids).fetchall()
        # setdefault(key, []) returns the existing list or inserts a new empty one,
        # so we can append in one line: {book_id: [tag names]}.
        tags_by_book = {}
        for tr in tag_rows:
            tags_by_book.setdefault(tr['book_id'], []).append(tr['name'])
        for b in books:
            b['tags'] = tags_by_book.get(b['id'], [])

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        # Ceiling division with integers: (a + b - 1) // b == ceil(a / b).
        "total_pages": max(1, (total + per_page - 1) // per_page),
        "books": books,
    }

# Declared BEFORE "/{book_id}" on purpose -- see the route-order note at the top.
@router.get("/tags")
def list_all_tags():
    """GET /api/books/tags -- list all tags with book counts.

    Response: list of ``{"name", "count", ...}`` from ``db.get_all_tags()``.
    """
    return db.get_all_tags()

@router.get("/{book_id}")
def get_book(book_id: int):
    """GET /api/books/{book_id} -- fetch one book by ID.

    The ``book_id: int`` annotation makes FastAPI convert the path segment to an
    int (and return 422 if it isn't one).
    Response: the book row as a dict. Errors: 404 if not found.
    """
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    return book

@router.post("/extract")
def extract_book(book_title: str, book_url: str, background_tasks: BackgroundTasks):
    """
    Start extraction process for a book.
    Runs in background to avoid HTTP timeout.

    POST /api/books/extract?book_title=..&book_url=..

    ``background_tasks: BackgroundTasks`` is not a query param: FastAPI sees the
    type and injects a task queue that runs after the response is sent.

    Response: ``{"message": str}`` immediately (the result is not reported; the
    UI re-fetches the book list later).
    Side effects (in background): OPENS CHROME, scrapes book info + the full
    chapter list, creates or updates the book and appends new chapter rows.
    """
    # TODO: an existing book is matched by TITLE (inside extract_chapters_for_book),
    # so two different books with the same title get merged, and a renamed book
    # is extracted again as a new one. Matching by book_url would be safer.
    # Nested function (closure) capturing book_url/book_title; a lambda or
    # add_task(extract_chapters_for_book, book_url, book_title) would also work.
    def run_extraction():
        extract_chapters_for_book(book_url, book_title)

    background_tasks.add_task(run_extraction)
    return {"message": f"Extraction started for {book_title}. Please check back in a moment."}

@router.get("/{book_id}/chapters")
def get_chapters(book_id: int):
    """GET /api/books/{book_id}/chapters -- all chapters of a book (ordered rows,
    including content). No 404: an unknown book returns ``[]``.
    """
    chapters = db.get_chapters_by_book(book_id)
    return chapters

@router.post("/{book_id}/download")
def download_book_task(book_id: int, background_tasks: BackgroundTasks, max_chapters: int = None):
    """
    Start downloading the book to DOCX.
    Runs in background.
    max_chapters: Limit the number of chapters to download in this session (for rate limiting).

    POST /api/books/{book_id}/download?max_chapters=N

    Response: ``{"message": str}``.
    Errors: 404 no book; 409 a download is already running; 400 for translated
    books (their content comes from the Translate tool, not the website).
    Side effects (in background): OPENS CHROME, downloads pending chapters,
    writes chapter content/status to the DB, builds the main DOCX.
    """
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    # Friendly early 409. The downloader's register_download() is the real
    # one-job-per-book lock, in case two requests slip past this check.
    if get_download_progress(book_id):
        raise HTTPException(status_code=409, detail="A download is already running for this book.")
    if book.get('is_translated'):
        raise HTTPException(status_code=400, detail="Translated book — content is produced by the Translate tool, not by web download.")

    # Exceptions in a background task can't reach the client any more (the
    # response is already sent), so catch and log them here.
    def run_download():
        try:
            download_book(book_id, max_chapters=max_chapters)
        except Exception as e:
            print(f"Download failed: {e}")

    background_tasks.add_task(run_download)
    msg = f"Download started for {book['title']}."
    if max_chapters:
        msg += f" Limited to {max_chapters} chapters."
    return {"message": msg}

@router.post("/{book_id}/cancel-download")
def cancel_download_task(book_id: int):
    """
    Cancel an active download for a book.
    The downloader will finish the current chapter and stop.

    POST /api/books/{book_id}/cancel-download
    Response: ``{"message": str}``. Errors: 404 if no download is active.
    Side effect: sets the job's cancel flag (cooperative cancellation).
    """
    cancelled = cancel_download(book_id)
    if cancelled:
        return {"message": f"Cancellation requested for download task {book_id}."}
    raise HTTPException(status_code=404, detail="No active download found for this book.")

@router.post("/{book_id}/redownload")
def redownload_book_task(book_id: int, background_tasks: BackgroundTasks,
                               all_chapters: bool = False, count: int = None,
                               start_order: int = None, end_order: int = None):
    """Re-download chapters into a separate _redownload.docx.

    By default only re-downloads failed chapters.
    Set all_chapters=true to re-download every chapter (fresh copy).
    Set count=N to re-download only the first N chapters.
    Set start_order/end_order to re-download a chapter range (inclusive).

    POST /api/books/{book_id}/redownload?all_chapters=..&count=..&start_order=..&end_order=..
    (FastAPI parses "true"/"false"/"1"/"0" into the bool param.)

    Response: ``{"message": str}`` describing which chapters were selected.
    Errors: 404 no book, 409 a download is already running.
    Side effects (in background): OPENS CHROME, updates chapter rows,
    writes {book_id}_{seo}_redownload.docx.
    """
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    if get_download_progress(book_id):
        raise HTTPException(status_code=409, detail="A download is already running for this book.")

    def run():
        try:
            redownload_book(book_id, all_chapters=all_chapters,
                            count=count, start_order=start_order,
                            end_order=end_order)
        except Exception as e:
            print(f"Redownload failed: {e}")

    background_tasks.add_task(run)
    # Human-readable label for the response; precedence mirrors redownload_book:
    # count > range > all > failed-only.
    if count is not None and count > 0:
        label = f"first {count} chapters"
    elif start_order is not None or end_order is not None:
        label = f"chapters {start_order or 1} to {end_order or 'last'}"
    elif all_chapters:
        label = "all chapters"
    else:
        label = "failed chapters"
    return {"message": f"Re-download started for {book['title']} ({label}). Output goes to _redownload.docx."}

@router.post("/{book_id}/chapters/{chapter_id}/download")
def download_single_chapter_task(book_id: int, chapter_id: int, background_tasks: BackgroundTasks):
    """POST /api/books/{book_id}/chapters/{chapter_id}/download -- download a
    single chapter and append to _redownload.docx.

    Response: ``{"message": str}``. Errors: 404 no book, 409 download running.
    Side effects (in background): OPENS CHROME, updates that chapter row,
    appends to {book_id}_{seo}_redownload.docx.
    """
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    if get_download_progress(book_id):
        raise HTTPException(status_code=409, detail="A download is already running for this book.")

    def run():
        try:
            download_single_chapter(book_id, chapter_id)
        except Exception as e:
            print(f"Single chapter download failed: {e}")

    background_tasks.add_task(run)
    return {"message": f"Download started for chapter {chapter_id} of '{book['title']}'."}

@router.get("/{book_id}/redownload-docx-info")
def get_redownload_docx_info(book_id: int):
    """GET /api/books/{book_id}/redownload-docx-info -- check if _redownload.docx exists.

    Response: ``{"exists": bool, "file_name": str, "file_path": abs path|None, "size": bytes}``.
    Errors: 404 only if the BOOK is missing (a missing file is ``exists: false``).
    """
    return docx_info(get_book_or_404(book_id), "_redownload")


@router.get("/{book_id}/redownload-docx")
def get_redownload_docx(book_id: int):
    """GET /api/books/{book_id}/redownload-docx -- download the _redownload.docx file.

    Response: the file. ``FileResponse`` streams it from disk; ``filename=`` sets
    the Content-Disposition header so the browser saves it under that name.
    Errors: 404 if the book or the file is missing.
    """
    return docx_response(get_book_or_404(book_id), "_redownload",
                         "Redownload DOCX file not found.")


@router.get("/{book_id}/progress")
def get_progress(book_id: int):
    """GET /api/books/{book_id}/progress -- real-time download progress (polled by BookDetails).

    Response, two shapes:
      * job running: ``{"active": True, "download_status": "in_progress",
        "success_count", "fail_count", "total", "current_index",
        "current_title", "cancelled"}`` from the in-memory job tracker;
      * idle: ``{"active": False, "download_status", "downloaded_chapters",
        "total_chapters"}`` read from the DB row.
    Errors: 404 only when idle AND the book does not exist.
    """
    progress = get_download_progress(book_id)
    if not progress:
        book = db.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")
        return {
            "active": False,
            "download_status": book['download_status'],
            "downloaded_chapters": book['downloaded_chapters'] or 0,
            "total_chapters": book['total_chapters'] or 0,
        }
    return {
        "active": True,
        "download_status": "in_progress",
        "success_count": progress["success_count"],
        "fail_count": progress["fail_count"],
        "total": progress["total"],
        "current_index": progress["current_index"],
        "current_title": progress["current_title"],
        "cancelled": progress["cancelled"],
    }

@router.get("/{book_id}/docx")
def get_docx(book_id: int):
    """GET /api/books/{book_id}/docx -- download the main DOCX file for a book.

    Errors: 404 if the book is missing or the DOCX has not been built yet.
    """
    return docx_response(get_book_or_404(book_id), "",
                         "DOCX file not found. Please download the book first.")


@router.get("/{book_id}/docx-info")
def get_docx_info(book_id: int):
    """GET /api/books/{book_id}/docx-info -- check if the main DOCX exists and return its info.

    Response: ``{"exists", "file_name", "file_path", "size"}`` (see redownload-docx-info).
    Errors: 404 if the book is missing.
    """
    return docx_info(get_book_or_404(book_id), "")


@router.post("/{book_id}/export-corrected")
def export_corrected(book_id: int, chapter_ids: List[int] = Body(default=[])):
    """Render a corrected DOCX from DB content (source of truth), applying per-book
    corrections at render time. Nothing in the DB is modified. chapter_ids: optional
    list of chapter ids to include (empty = whole book).

    POST /api/books/{book_id}/export-corrected
    Body: a bare JSON array, e.g. ``[12, 13, 14]`` (or ``[]`` / no body).
    ``Body(default=[])`` forces FastAPI to read a list param from the request
    body; with a single Body param and no ``embed=True`` the body IS the list,
    not ``{"chapter_ids": [...]}``.

    Response: ``{"exists": True, "file_name", "file_path", "size", "chapter_count"}``.
    Errors: 404 no book, 400 book has no chapters.
    Side effect: (over)writes {book_id}_{seo}_corrected.docx on disk, synchronously
    (the request waits for the render). DB untouched.
    """
    book = get_book_or_404(book_id)
    chapters = db.get_chapters_by_book(book_id)
    if not chapters:
        raise HTTPException(status_code=400, detail="No chapters to export.")
    file_path = docx_path(book, "_corrected")
    # Global cleaning (translated books only) + per-book corrections, in order.
    rules = build_render_rules(db, book)
    # `chapter_ids or None`: an empty list means "all chapters" to build_book_docx.
    build_book_docx(book, chapters, rules, file_path, chapter_ids=chapter_ids or None)
    # `{**a, "k": v}` builds a new dict: all keys of `a` plus one extra key.
    return {**docx_info(book, "_corrected"),
            "chapter_count": len(chapter_ids) if chapter_ids else len(chapters)}

@router.get("/{book_id}/export-corrected-docx")
def get_export_corrected_docx(book_id: int):
    """GET /api/books/{book_id}/export-corrected-docx -- download the corrected DOCX file.

    Errors: 404 if the book is missing or POST export-corrected has not been run.
    """
    return docx_response(get_book_or_404(book_id), "_corrected",
                         "Corrected DOCX file not found. Export it first.")


@router.get("/{book_id}/export-corrected-docx-info")
def get_export_corrected_docx_info(book_id: int):
    """GET /api/books/{book_id}/export-corrected-docx-info -- check if the
    corrected DOCX file exists and return its info.

    Response: ``{"exists", "file_name", "file_path", "size"}``. Errors: 404 no book.
    """
    return docx_info(get_book_or_404(book_id), "_corrected")


@router.post("/{book_id}/preview-correction")
def preview_correction(book_id: int, chapter_id: int):
    """Preview the corrected text of a single chapter. Rendered in memory only —
    the result is NOT saved to the database or disk.

    POST /api/books/{book_id}/preview-correction?chapter_id=N

    Response:
        ``{"chapter_id", "chapter_order",
           "title": corrected title, "content": corrected body,
           "title_segments": [...], "content_segments": [...]}``

    The *segments* lists let the UI highlight what the rules changed. Each
    segment is ``{"type": "text"|"removed"|"replaced", "text": str}``:
      * "text"     -- unchanged text,
      * "removed"  -- original text a rule matched (shown struck through),
      * "replaced" -- the replacement text (shown highlighted).
    Joining every segment except "removed" gives exactly ``title``/``content``.
    ``diff_paragraphs`` works per line and inserts literal "\\n" text segments,
    so a rule can never merge two paragraphs.

    Errors: 404 if the book or chapter is missing.
    """
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    # next(generator, default) returns the first match or None -- a one-line "find".
    # TODO: loads every chapter (with content) just to pick one; add a
    # db.get_chapter(book_id, chapter_id) helper (it does not exist yet).
    chapter = next((c for c in db.get_chapters_by_book(book_id) if c["id"] == chapter_id), None)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    rules = build_render_rules(db, book)
    is_translated = bool(book.get("is_translated"))
    # chapter_text() picks the right source: translated_content split into
    # (title, body) for translated books, chapter_title/chapter_content otherwise.
    title, content = chapter_text(chapter, is_translated)
    # Same blank-line normalization as every other render path, so the preview
    # matches the exported DOCX.
    title = collapse_blank_lines(title)
    content = collapse_blank_lines(content)
    return {
        "chapter_id": chapter_id,
        "chapter_order": chapter["chapter_order"],
        "title": apply_rules(title, rules),
        # preserve_newlines only for translated books: their raw text is one
        # paragraph per line, and global rules must not match across lines.
        "content": apply_paragraphs(content, rules, preserve_newlines=is_translated),
        "title_segments": diff_rules(title, rules),
        "content_segments": diff_paragraphs(content, rules),
    }

@router.get("/{book_id}/cover")
def get_cover_image(book_id: int):
    """Serve the cover image for a book.

    Searches for a local file matching {book_id}_{seo_title_basic}.{ext}
    in the book directory. Falls back to redirecting to the remote URL
    if stored. Returns 404 only if nothing exists.

    GET /api/books/{book_id}/cover -- used directly as an <img src>.
    Response: the image file, or a 307 redirect to cover_image_url.
    """
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    save_dir = book_dir()

    # Try local file with common extensions
    basename = f"{book_id}_{book['seo_title_basic']}"
    for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
        local_file = save_dir / f"{basename}{ext}"
        if local_file.exists():
            # TODO: gif/webp are served as image/png; mimetypes.guess_type() would
            # give the right type (browsers usually sniff it anyway).
            media_type = "image/jpeg" if local_file.suffix.lower() in ('.jpg', '.jpeg') else "image/png"
            return FileResponse(path=str(local_file), media_type=media_type)

    # No local file — redirect to remote URL if stored
    if book.get('cover_image_url'):
        # TODO: redundant -- RedirectResponse is already imported at the top.
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=book['cover_image_url'])

    raise HTTPException(status_code=404, detail="No cover image available for this book")

@router.post("/{book_id}/refresh-info")
def refresh_book_info(book_id: int):
    """Re-scrape book metadata (cover image URL, description, author, etc.)
    from the web and update the local DB. Does NOT re-extract chapters.
    Useful for backfilling cover_image_url / short_description on books
    that were extracted before those columns existed.

    POST /api/books/{book_id}/refresh-info
    Response: ``{"message", "updated_fields": [scraped keys]}``.
    Errors: 404 no book, 400 book has no URL, 500 scraping returned nothing.
    Side effects: OPENS CHROME synchronously (the request waits), updates book
    columns + tags, downloads the cover image to disk.
    """
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    if not book.get('book_url'):
        raise HTTPException(status_code=400, detail="Book has no URL to scrape from")

    extractor = ChapterListExtractor()
    # try/finally: Chrome is closed even when we raise the 500 below or scraping crashes.
    try:
        info = extractor.scrape_book_info(book['book_url'])
        if not info:
            # TODO: 502 (upstream site failed) would describe this better than 500.
            raise HTTPException(status_code=500, detail="Failed to scrape book info")
        # Shared helper: saves fields + tags + downloads the cover image.
        extractor.save_book_info(book_id, book['seo_title_basic'], info)
        return {
            "message": "Book info refreshed",
            "updated_fields": list(info.keys()),
        }
    finally:
        extractor.close()

@router.get("/{book_id}/tags")
def get_book_tags(book_id: int):
    """GET /api/books/{book_id}/tags -- tags of one book.

    Response: ``{"tags": [names]}``. Errors: 404 if the book is missing.
    """
    if not db.get_book(book_id):
        raise HTTPException(status_code=404, detail="Book not found")
    return {"tags": db.get_book_tags(book_id)}

@router.put("/{book_id}/tags")
def update_book_tags(book_id: int, tags: List[str] = Body(...)):
    """PUT /api/books/{book_id}/tags -- replace ALL tags of a book.

    Body: a bare JSON array of names, e.g. ``["Tiên hiệp", "Hài"]``.
    ``Body(...)``: the ``...`` (Ellipsis) means "required, no default".
    Response: ``{"tags": [new names], "message"}``. Errors: 404 no book.
    Side effect: rewrites book_tags links (creating new tag names as needed).
    """
    if not db.get_book(book_id):
        raise HTTPException(status_code=404, detail="Book not found")
    db.set_book_tags(book_id, tags)
    return {"tags": db.get_book_tags(book_id), "message": "Tags updated"}

@router.post("/{book_id}/toggle-favorite")
def toggle_favorite(book_id: int):
    """POST /api/books/{book_id}/toggle-favorite -- flip the favorite flag (0 <-> 1).

    Response: ``{"is_favorite": 0|1, "message"}``. Errors: 404 no book.
    Side effect: updates books.is_favorite (favorites sort first in the list).
    """
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    # SQLite has no bool type, so flags are stored as 0/1 integers.
    new_val = 0 if book.get('is_favorite') else 1
    db.update_book_info(book_id, is_favorite=new_val)
    return {"is_favorite": new_val, "message": "Favorite updated" if new_val else "Removed from favorites"}

@router.post("/{book_id}/toggle-sent")
def toggle_sent(book_id: int):
    """POST /api/books/{book_id}/toggle-sent -- flip the "sent" flag (0 <-> 1).

    Response: ``{"is_sent": 0|1, "message"}``. Errors: 404 no book.
    Side effect: updates books.is_sent.
    """
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    new_val = 0 if book.get('is_sent') else 1
    db.update_book_info(book_id, is_sent=new_val)
    return {"is_sent": new_val, "message": "Marked as sent" if new_val else "Marked as not sent"}

@router.post("/{book_id}/toggle-auto-export")
def toggle_auto_export(book_id: int):
    """POST /api/books/{book_id}/toggle-auto-export -- toggle whether a DOCX is
    exported automatically after download.

    Response: ``{"auto_export_docx": 0|1, "message"}``. Errors: 404 no book.
    Side effect: updates books.auto_export_docx.
    """
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    new_val = 0 if book.get('auto_export_docx') else 1
    db.update_book_info(book_id, auto_export_docx=new_val)
    return {"auto_export_docx": new_val,
            "message": "Auto DOCX export enabled" if new_val else "Auto DOCX export disabled"}

@router.put("/{book_id}")
def update_book_info(book_id: int, req: UpdateBookInfoRequest):
    """PUT /api/books/{book_id} -- update editable book metadata (title, author,
    summary, web status, cover URL).

    Body: JSON matching UpdateBookInfoRequest; only non-null fields are applied.
    Blank strings clear a field (``.strip() or None`` -> NULL); a blank title is ignored.

    Response: ``{"message", "updated_fields": [changed column names]}``.
    Errors: 404 no book, 400 another book already has the new title.
    Side effect: updates the book row. Files on disk are named by
    seo_title_basic, which this does not change, so they stay linked.
    """
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    # Collect only real changes, then do a single UPDATE via **updates
    # (dict unpacked into keyword arguments).
    updates = {}
    if req.title is not None and req.title.strip():
        if req.title.strip() != book.get('title'):
            existing = db.get_book_by_title(req.title.strip())
            if existing and existing['id'] != book_id:
                raise HTTPException(status_code=400, detail="A book with this title already exists")
            updates['title'] = req.title.strip()
    if req.author is not None:
        updates['author'] = req.author.strip() or None
    if req.short_description is not None:
        updates['short_description'] = req.short_description.strip() or None
    if req.book_web_status is not None:
        updates['book_web_status'] = req.book_web_status.strip() or None
    if req.cover_image_url is not None:
        updates['cover_image_url'] = req.cover_image_url.strip() or None

    if updates:
        db.update_book_info(book_id, **updates)
    return {"message": "Book info updated", "updated_fields": list(updates.keys())}


@router.post("/{book_id}/cover")
def upload_cover(book_id: int, file: UploadFile = File(...)):
    """Upload a cover image for a book. Saved as {book_id}_{seo_title_basic}.{ext}
    in the book directory so GET /{book_id}/cover serves it locally.

    POST /api/books/{book_id}/cover
    Body: multipart/form-data with a ``file`` field (``UploadFile = File(...)``;
    ``...`` = required). Only the extension is checked, not the real content.

    Response: ``{"message": "Cover saved as <name>"}``.
    Errors: 404 no book, 400 unsupported extension.
    Side effects: deletes older covers with a different extension, writes the new file.
    """
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    # splitext("a/b.JPG") -> ("a/b", ".JPG"); only the extension of the client's
    # name is used -- the saved name is built by us, so no path-traversal risk.
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
        raise HTTPException(status_code=400, detail="Cover must be jpg/png/gif/webp")

    save_dir = book_dir()

    # Remove existing cover with a different extension
    # (GET /cover returns the first extension it finds, so a stale .jpg would
    # otherwise keep hiding a newly uploaded .png).
    basename = f"{book_id}_{book['seo_title_basic']}"
    for old_ext in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
        old = save_dir / f"{basename}{old_ext}"
        if old.exists() and old.suffix.lower() != ext:
            old.unlink()

    dest = save_dir / f"{basename}{ext}"
    # Stream the upload to disk in chunks instead of reading it all into memory.
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return {"message": f"Cover saved as {dest.name}"}

@router.delete("/{book_id}")
def delete_book(book_id: int):
    """Delete a book and its associated chapters (CASCADE also removes
    corrections/tags links). Files on disk are kept. 409 while a job runs.

    DELETE /api/books/{book_id}
    Response: ``{"message"}`` -- also returned for an id that doesn't exist (no 404).
    Side effect: deletes the book row; ON DELETE CASCADE (enabled by
    ``PRAGMA foreign_keys = ON`` in database.py) removes child rows.
    """
    # TODO: DOCX and cover files stay on disk forever; delete
    # {book_id}_{seo_title_basic}*.docx / cover images too (or offer it as an option).
    _ensure_idle(book_id)
    conn = db._get_connection()
    conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
    conn.commit()
    return {"message": "Book deleted successfully"}

# Two path segments, so "/{book_id}" (one segment) can't swallow it; still, keep
# fixed paths like this away from patterns such as "/{book_id}/check".
@router.get("/updates/check")
def check_for_updates():
    """
    Check all ongoing/unknown books to see if they have new chapters.
    Returns a list of books that have updates.

    GET /api/books/updates/check

    Looks at books whose site status is 'Còn tiếp' (Vietnamese: "ongoing") or
    'Chưa xác minh' ("not verified"), scrapes each book page and compares the
    site's latest-chapter URL with the one stored in the DB.

    Response: ``{"updated": count, "books": [{"id", "title", "old_last_chapter",
    "new_last_chapter", "author", "book_web_status"}]}``.

    Side effects: OPENS CHROME (one session reused for all books) and, for
    each book with news, updates its info + tags in the DB. Chapters are NOT
    extracted or downloaded (that's /update-full). Note it is a GET with writes.
    """
    # TODO: runs every book sequentially inside ONE request -- slow (minutes)
    # and the browser just waits. Make it a background job with progress polling.
    # TODO: redundant import; ChapterListExtractor is already imported at the top.
    from app.services.extractor import ChapterListExtractor

    conn = db._get_connection()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM books WHERE book_web_status IN ('Còn tiếp', 'Chưa xác minh') ORDER BY title"
    ).fetchall()
    books = [dict(r) for r in rows]

    extractor = ChapterListExtractor()
    updated = []
    try:
        for book in books:
            # Translated / manually created books have no URL to check.
            if not book.get('book_url'):
                continue
            print(f"🔍 Checking updates for: {book['title']}")
            info = extractor.scrape_book_info(book['book_url'])
            if not info:
                continue

            # Check if the latest chapter URL is different
            old_url = book.get('last_chapter_url') or ''
            new_url = info.get('last_chapter_url') or ''
            if new_url and new_url != old_url:
                # Update book info in DB
                db.update_book_info(book['id'], **info)
                if info.get('tags'):
                    db.set_book_tags(book['id'], info['tags'])
                updated.append({
                    "id": book['id'],
                    "title": book['title'],
                    "old_last_chapter": book.get('last_chapter_title'),
                    "new_last_chapter": info.get('last_chapter_title'),
                    "author": book.get('author'),
                    "book_web_status": info.get('book_web_status', book.get('book_web_status')),
                })
                print(f"✅ Update found: {book['title']}: {book.get('last_chapter_title')} → {info.get('last_chapter_title')}")
    finally:
        extractor.close()

    return {"updated": len(updated), "books": updated}

@router.post("/{book_id}/update-full")
def update_book_full(book_id: int, background_tasks: BackgroundTasks, max_chapters: int = None):
    """
    One-click update: re-scrape book info, extract new chapters, and download them.
    Combines check-updates + continue-extract + download into a single endpoint.

    POST /api/books/{book_id}/update-full?max_chapters=N

    Background flow (each step can stop early, cheapest checks first):
      1. scrape the book page (one page load) and save info/tags/cover;
      2. if the site's latest chapter URL is already in OUR chapters table
         -> nothing new, stop (skips the expensive full list scrape);
      3. otherwise scrape the full chapter list and append only unknown chapters;
      4. close that Chrome, then if anything was added run the normal
         download (which opens its own Chrome) limited to max_chapters.

    Response: ``{"message"}`` immediately.
    Errors: 404 no book, 409 a download/translation is running.
    Side effects: opens Chrome (twice, sequentially), writes book info, new
    chapter rows, chapter content and the DOCX.
    """
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    _ensure_idle(book_id)

    def run():
        extractor = ChapterListExtractor()
        # Defined before the try so it exists for step 4 even if we return early.
        added = 0
        try:
            # Step 1: Re-scrape book info (cheap — one page load)
            info = extractor.scrape_book_info(book['book_url'])
            if not info or not info.get('last_chapter_url'):
                print(f"⚠️ Could not scrape book info for {book['title']}")
                # `return` inside try still runs the finally block below.
                return
            extractor.save_book_info(book_id, book['seo_title_basic'], info)

            # Step 2: Is their latest chapter already in OUR chapters table?
            conn = db._get_connection()
            row = conn.execute(
                "SELECT 1 FROM chapters WHERE book_id = ? AND chapter_url = ? LIMIT 1",
                (book_id, info['last_chapter_url'])
            ).fetchone()
            if row:
                print(f"ℹ️ No new chapters for {book['title']} (latest chapter already in DB)")
                return

            # Step 3: New chapter detected — extract the full list, append only new ones
            chapters = extractor.extract_chapter_list(book['book_url'])
            if not chapters:
                print(f"⚠️ No chapters found for {book['title']}")
                return
            added = append_new_chapters(book_id, chapters)
        finally:
            # Close the extractor's Chrome before the downloader opens its own.
            extractor.close()

        # Step 4: Download the new chapters
        # Note: _ensure_idle ran at request time; a download started between then
        # and here is caught by the downloader's own register_download() lock.
        if added:
            try:
                download_book(book_id, max_chapters=max_chapters)
            except Exception as e:
                print(f"❌ Download failed: {e}")

    background_tasks.add_task(run)
    return {"message": f"Full update started for {book['title']}. Checking & downloading new chapters..."}


@router.post("/{book_id}/continue-extract")
def continue_extract(book_id: int, background_tasks: BackgroundTasks):
    """
    Continue extracting new chapters for a book that has been updated.
    Saves to a new extraction (existing chapters preserved, new ones appended).

    POST /api/books/{book_id}/continue-extract
    Response: ``{"message"}`` immediately.
    Errors: 404 no book, 409 a download/translation is running.
    Side effects (in background): OPENS CHROME, updates book info, appends new
    chapter rows (never deletes). Does not download content -- see /update-full.
    """
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    _ensure_idle(book_id)

    def run():
        extractor = ChapterListExtractor()
        try:
            # First re-scrape book info
            info = extractor.scrape_book_info(book['book_url'])
            if info:
                extractor.save_book_info(book_id, book['seo_title_basic'], info)

            # Extract a fresh chapter list and append only the chapters we don't have
            chapters = extractor.extract_chapter_list(book['book_url'])
            if not chapters:
                print(f"No chapters found for {book['title']}")
                return
            append_new_chapters(book_id, chapters)
        finally:
            extractor.close()

    background_tasks.add_task(run)
    return {"message": f"Continue extraction started for {book['title']}. Checking for new chapters..."}
