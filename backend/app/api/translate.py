"""Translate API: turn a raw (e.g. Chinese) TXT file into a "translated book".

Flow used by the Translate page:
  1. upload / list raw TXT files in the source folder (/upload, /source-files)
  2. /parse a file -> preview book info + chapter titles
  3. POST /books -> create the book + chapters in the DB (raw text, untranslated)
  4. POST /books/{id}/run -> translate pending chapters in a background thread
  5. poll /books/{id}/progress; cancel with /books/{id}/cancel

Mounted in main.py under the prefix ``/api/translate``, so ``@router.get("/prepare")``
here is really ``GET /api/translate/prepare``.

All endpoints are plain ``def`` on purpose: FastAPI runs them in a thread pool,
so blocking work (sqlite, HTTP calls to the translation API, Selenium) does not
freeze the asyncio event loop that serves every other request.

Storage invariant (see app/services/docx_exporter.py): the raw source text lives
in ``chapters.chapter_content``; the raw translation goes to
``chapters.translated_content`` as "<viet_title>\\n<viet_body>". Global cleaning
rules and per-book corrections are applied only when a DOCX is rendered.
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks, UploadFile, File
from pydantic import BaseModel
from typing import List, Dict, Optional
import os
import shutil
from pathlib import Path
from colorama import Fore, init
from app.database import get_database
from app.services.translator import (
    translate_text,
    parse_raw_file,
    translate_book,
    retranslate_book,
    continue_book,
    refresh_cookies_manually,
    cancel_translation,
    get_translation_progress,
    Translator,
    TranslationRunningError,
)
from app.config import BACKEND_DIR

router = APIRouter()
db = get_database()


def _source_dir() -> Path:
    """Folder holding the raw TXT files (``translate_source_path`` setting).

    Relative paths are resolved against backend/. The folder is created if it
    does not exist yet (``parents=True`` = like ``mkdir -p``; ``exist_ok=True``
    = no error if it is already there).
    """
    src = db.get_setting("translate_source_path") or "./data/translate_src"
    path = BACKEND_DIR / src  # an absolute `src` wins over BACKEND_DIR in a Path join
    path.mkdir(parents=True, exist_ok=True)
    return path


def _source_file(filename: str) -> Path:
    """Safe path of a raw TXT file inside the source folder (path-traversal guard).

    The filename comes from the client (URL, query string or JSON body), so it
    could be something like "..\\..\\app\\config.py" trying to reach files
    outside the folder. Two layers stop that:
      1. os.path.basename() keeps only the last part ("config.py"), dropping
         any folders the client tried to add.
      2. resolve() makes the path absolute (following "..") and
         is_relative_to() checks it is still inside the source folder.

    Args:
        filename: name sent by the client.

    Returns:
        Absolute Path inside the source folder (the file may not exist).

    Raises:
        HTTPException 400: empty or invalid name.
    """
    folder = _source_dir().resolve()
    name = os.path.basename(filename or "")
    path = (folder / name).resolve()
    if not name or not path.is_relative_to(folder) or path == folder:
        raise HTTPException(status_code=400, detail="Invalid filename")
    return path


# --- Preparation / files ---

@router.get("/prepare")
def prepare():
    """Return translation settings and the effective method WITHOUT probing the API.
    Cheap call used on page load. The actual availability check happens on demand
    via GET /check (or implicitly when a run starts).

    GET /api/translate/prepare

    Response: ``{"method": "api"|"web", "source_path": str, "settings": {...}}``
    where ``settings`` holds every translate_* setting plus ``has_cookies``.
    Read-only (apart from _source_dir() creating the folder).
    """
    # The cookie setting is normally a JSON list/dict; if it isn't valid JSON we
    # fall back to "any non-blank text counts as cookies".
    has_cookies = False
    raw_cookies = db.get_setting("translate_cookies") or ""
    if raw_cookies.strip():
        try:
            # TODO: move this import to the top of the file (stdlib, always available).
            import json
            has_cookies = bool(json.loads(raw_cookies))
        except Exception:
            has_cookies = bool(raw_cookies.strip())
    # When cookies are present the API method can pass Cloudflare (curl_cffi +
    # cookie), so try it FIRST — translate() auto-falls-back to web if the API
    # fails. Without cookies only the web method can work.
    return {
        "method": "api" if has_cookies else "web",
        "source_path": str(_source_dir()),
        "settings": {
            "translate_source_path": db.get_setting("translate_source_path"),
            "translate_api_endpoint": db.get_setting("translate_api_endpoint"),
            "translate_site": db.get_setting("translate_site"),
            "translate_target_lang": db.get_setting("translate_target_lang"),
            "translate_click_delay": db.get_setting("translate_click_delay"),
            "translate_retry_delay": db.get_setting("translate_retry_delay"),
            "translate_max_retries": db.get_setting("translate_max_retries"),
            "translate_browser_ua": db.get_setting("translate_browser_ua"),
            "translate_impersonate": db.get_setting("translate_impersonate"),
            "translate_cookie_wait": db.get_setting("translate_cookie_wait"),
            "translate_cookie_refresh_max": db.get_setting("translate_cookie_refresh_max"),
            "has_cookies": has_cookies,
        },
    }


@router.get("/check")
def check():
    """GET /api/translate/check -- probe the translation API availability (slow — only called on demand).

    Response: ``{"api_available": bool, "method": "api"|"web", "source_path": str}``.
    Side effect: makes a real network request to the translation API.
    """
    t = Translator()
    # try/finally: close() runs even if the probe raises, so no Chrome is leaked.
    try:
        api_ok = t.api_available()
    finally:
        t.close()
    return {
        "api_available": api_ok,
        "method": "api" if api_ok else "web",
        "source_path": str(_source_dir()),
    }


@router.get("/source-files")
def list_source_files():
    """GET /api/translate/source-files -- list raw TXT files available in the source folder.

    Response: ``{"files": [{"filename", "size", "modified"}, ...], "source_path": str}``
    (sorted by file name; only .txt / .text files).
    """
    src = _source_dir()
    files = []
    # iterdir() yields Path objects for every entry in the folder.
    for f in sorted(src.iterdir()):
        if f.is_file() and f.suffix.lower() in (".txt", ".text"):
            files.append({
                "filename": f.name,
                "size": f.stat().st_size,
                "modified": f.stat().st_mtime,
            })
    return {"files": files, "source_path": str(src)}


@router.post("/upload")
def upload_source_file(file: UploadFile = File(...)):
    """POST /api/translate/upload -- upload a raw TXT file into the source folder.

    Body: multipart/form-data with a ``file`` field. ``UploadFile = File(...)``
    tells FastAPI to read it from the form (``...`` = required). ``file.file``
    is a file-like object, so it can be streamed to disk without loading it
    all into memory.

    Response: ``{"filename": saved_name, "size": bytes}``.
    Errors: 400 if the name does not end in .txt / .text.
    Side effect: writes (or overwrites!) a file in the source folder.
    """
    filename = file.filename or "upload.txt"
    if not filename.lower().endswith((".txt", ".text")):
        raise HTTPException(status_code=400, detail="Only .txt files are supported")
    # Sanitize filename
    # basename() drops any directory part a client might send ("../../x.txt" ->
    # "x.txt"), so the upload cannot be written outside the source folder.
    dest = _source_file(filename)  # same guard as delete/parse/create
    safe_name = dest.name
    # copyfileobj streams the upload to disk in chunks.
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return {"filename": safe_name, "size": dest.stat().st_size}


@router.delete("/source-files/{filename}")
def delete_source_file(filename: str):
    """DELETE /api/translate/source-files/{filename} -- delete a raw TXT file from the source folder.

    Errors: 404 if the file does not exist.
    Side effect: deletes the file from disk (books already created from it are untouched).
    """
    dest = _source_file(filename)
    if not dest.exists():
        raise HTTPException(status_code=404, detail="File not found")
    dest.unlink()
    return {"message": f"Deleted {filename}"}


@router.post("/parse")
def parse_file(filename: str):
    """POST /api/translate/parse?filename=.. -- parse a raw TXT file and return
    book info + chapter titles (raw, untranslated).

    Response: the dict from ``parse_raw_file`` (title/author/summary/chapters)
    plus ``"filename"``. Errors: 404 if the file is missing.
    Read-only: nothing is saved yet.
    """
    dest = _source_file(filename)
    if not dest.exists():
        raise HTTPException(status_code=404, detail="File not found")
    result = parse_raw_file(str(dest))
    result["filename"] = filename
    return result


# --- Text helpers ---

class TranslateTextRequest(BaseModel):
    """JSON body for POST /text.

    A pydantic ``BaseModel`` declares the expected JSON shape; FastAPI parses
    and validates the body into an instance (422 on wrong types/missing ``text``).
    """
    text: str
    # "api" (HTTP translation API) or "web" (browser automation).
    method: Optional[str] = "api"


@router.post("/text")
def translate_single_text(req: TranslateTextRequest):
    """POST /api/translate/text -- translate an arbitrary block of text (e.g. a book title).

    Body: ``{"text": "...", "method": "api"|"web"}``.
    Response: ``{"translated": "..."}``.
    Errors: 400 for empty text; 502 Bad Gateway when the upstream translator
    fails (502 = "a server we depend on failed", not our own bug).
    """
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Empty text")
    try:
        translated = translate_text(req.text, method=req.method)
    except RuntimeError as e:
        # Expected failure raised by the translator with a user-readable message.
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        print(f"{Fore.RED}Unexpected translation error: {e}")
        raise HTTPException(status_code=502, detail=f"Translation failed: {e}")
    return {"translated": translated}


# --- Book creation ---

class CreateBookRequest(BaseModel):
    """JSON body for POST /books: which source file, and the (translated) title/author."""
    filename: str
    title: str
    author: Optional[str] = ""


@router.post("/books")
def create_translated_book(req: CreateBookRequest, background_tasks: BackgroundTasks):
    """Create a book + chapters from a parsed raw file. Chapters keep raw content
    in chapters.chapter_content; translation happens later in the run step.

    If the file has intro/summary text before the first chapter, we TRY to
    translate it for the book summary. If translation fails, the book is STILL
    saved (without a summary) — summary is best-effort only.

    POST /api/translate/books
    Body: ``{"filename": str, "title": str, "author": str}``.
    Response: ``{"book_id": int, "message": str}``.
    Errors: 404 file missing, 400 no chapters found / title already exists.
    Side effects: inserts the book (is_translated=1, status "Parsed") and one
    chapter row per parsed chapter; schedules a background summary translation.
    """
    dest = _source_file(req.filename)
    if not dest.exists():
        raise HTTPException(status_code=404, detail="File not found")
    parsed = parse_raw_file(str(dest))
    if not parsed["chapters"]:
        raise HTTPException(status_code=400, detail="No chapters found in file")

    # Prevent duplicate titles (seo_title_full is unique)
    existing = db.get_book_by_title(req.title)
    if existing:
        raise HTTPException(status_code=400, detail="A book with this title already exists")

    # `a or b or None`: first truthy value wins -- the user's author, else the one
    # parsed from the file, else NULL in the DB.
    book_id = db.add_book(
        title=req.title,
        author=req.author or parsed["author"] or None,
        book_web_status="Parsed",
        short_description=f"Translated from {req.filename}",
    )
    db.update_book_info(book_id, source_file=req.filename, is_translated=1, total_chapters=len(parsed["chapters"]))

    # Translated chapters have no web URL, but chapter_url is used as an identity
    # key, so we invent a unique fake one: "translate://<book_id>/<order>".
    # TODO: one INSERT (and commit) per chapter; a single executemany/transaction
    # would be much faster for books with thousands of chapters.
    for ch in parsed["chapters"]:
        placeholder_url = f"translate://{book_id}/{ch['order']}"
        db.add_chapter_with_content(
            book_id, ch["order"], ch["title"], placeholder_url, ch["content"]
        )

    # Best-effort: translate the intro/summary text. Never block book creation.
    summary = parsed.get("summary") or ""
    if summary:
        # Nested function (closure): it "captures" summary and book_id from this
        # scope. BackgroundTasks runs it AFTER the HTTP response has been sent,
        # so the client gets its book_id immediately.
        def translate_summary():
            t = Translator()
            # try/except/finally: `except` reports the error (the book is already
            # saved, the summary is best-effort); `finally` ALWAYS closes the
            # Translator, so a browser opened by the web method is never leaked.
            try:
                translated = t.translate(summary)
                if translated and translated.strip():
                    db.update_book_info(book_id, short_description=translated.strip())
                    print(f"📝 Summary translated for book {book_id}")
            except Exception as e:
                print(f"{Fore.YELLOW}Summary translation failed (book saved without summary): {e}")
            finally:
                t.close()
        background_tasks.add_task(translate_summary)

    return {"book_id": book_id, "message": f"Book '{req.title}' created with {len(parsed['chapters'])} chapters."}


@router.get("/books/{book_id}")
def get_translated_book(book_id: int):
    """GET /api/translate/books/{book_id} -- a translated book plus its chapter
    list (raw titles + translation status).

    Response: ``{"book": {...}, "chapters": [{"id", "order", "title",
    "has_content", "status"}, ...]}`` -- a slim chapter list (no content) to keep
    the payload small. Errors: 404 if the book does not exist.
    """
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    chapters = db.get_chapters_by_book(book_id)
    return {
        "book": book,
        "chapters": [
            {
                "id": c["id"],
                "order": c["chapter_order"],
                "title": c["chapter_title"],
                "has_content": bool(c.get("chapter_content")),
                "status": c["download_status"],
            }
            for c in chapters
        ],
    }


# --- Corrections ---
# Per-book find/replace rules (table book_corrections). They are applied only
# when rendering (DOCX export / preview), never written into chapter content.

@router.get("/books/{book_id}/corrections")
def get_corrections(book_id: int):
    """GET /api/translate/books/{book_id}/corrections -- list this book's corrections.

    Response: list of ``{"id", "find_text", "replace_text", "enabled", ...}``.
    Works for downloaded books too (the route just lives in this router).
    No 404: an unknown book simply returns ``[]``.
    """
    return db.get_book_corrections(book_id)


class CorrectionsRequest(BaseModel):
    """JSON body for PUT corrections: ``{"corrections": [{find_text, replace_text, enabled}, ...]}``."""
    # TODO: List[Dict] accepts any dict shape; a small Correction(BaseModel) would
    # validate the field names/types.
    corrections: List[Dict]


@router.put("/books/{book_id}/corrections")
def set_corrections(book_id: int, req: CorrectionsRequest):
    """PUT /api/translate/books/{book_id}/corrections -- REPLACE all corrections of a book.

    Body: see CorrectionsRequest. The list sent becomes the full new set
    (rows not in it are deleted). No 404 check on book_id.
    Side effect: rewrites the book's rows in book_corrections.
    """
    db.set_book_corrections(book_id, req.corrections)
    return {"message": "Corrections saved."}


class CopyCorrectionsRequest(BaseModel):
    """JSON body for the copy endpoint: ``{"source_book_id": int}``."""
    source_book_id: int


@router.post("/books/{book_id}/corrections/copy")
def copy_corrections(book_id: int, req: CopyCorrectionsRequest):
    """Replace this book's corrections with ALL corrections of another book.

    POST /api/translate/books/{book_id}/corrections/copy
    Body: ``{"source_book_id": int}``.

    Response: ``{"message", "copied": count, "source_title",
    "corrections": [the target book's new list]}`` -- the new list is returned so
    the open Corrections modal can update its state directly (otherwise the
    BookDetails progress polling would clobber it).

    Errors: 400 if source == target, 404 if the source book is missing.
    Side effect: OVERWRITES the target book's corrections.
    """
    if req.source_book_id == book_id:
        raise HTTPException(status_code=400, detail="Source and target are the same book.")
    source = db.get_book(req.source_book_id)
    if not source:
        raise HTTPException(status_code=404, detail=f"Source book {req.source_book_id} not found.")
    corrections = db.get_book_corrections(req.source_book_id)
    # Keep only the content fields: id/book_id of the source rows must not be copied.
    db.set_book_corrections(book_id, [
        {"find_text": c["find_text"], "replace_text": c["replace_text"], "enabled": bool(c["enabled"])}
        for c in corrections
    ])
    return {
        "message": f"Copied {len(corrections)} correction(s) from \"{source['title']}\".",
        "copied": len(corrections),
        "source_title": source["title"],
        "corrections": db.get_book_corrections(book_id),
    }


# --- Run / progress ---
# Note: unlike the downloader endpoints in books.py, these do NOT use FastAPI's
# BackgroundTasks. translate_book(..., run_async=True) starts its own thread and
# returns immediately, so the job is registered before this response is sent.

@router.post("/books/{book_id}/run")
def run_translation(book_id: int, method: str = "api", max_chapters: int = None):
    """Start translating pending chapters of a book in the background.
    Mirrors the downloader: only 'pending' chapters are processed; passing
    max_chapters limits the session (book status becomes 'paused' if more remain).

    POST /api/translate/books/{book_id}/run?method=api|web&max_chapters=N
    Response: ``{"message": str}``.
    Errors: 404 no book, 400 not a translated book, 409 a translation is
    already running for this book.
    Side effects: background thread writes translated_content + statuses to the
    DB (no DOCX is built); may open Chrome for the "web" method or to refresh
    Cloudflare cookies.
    """
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    if not book.get("is_translated"):
        raise HTTPException(status_code=400, detail="Not a translated book")
    # Fast-path check for a friendly 409 ...
    existing = get_translation_progress(book_id)
    if existing and existing.get("active"):
        raise HTTPException(status_code=409, detail="Translation already running for this book")
    # ... but two clicks can both pass the check above; translate_book does the
    # real atomic registration and raises TranslationRunningError for the loser.
    try:
        translate_book(book_id, method=method, run_async=True, max_chapters=max_chapters)
    except TranslationRunningError as e:  # lost the race against a double click
        raise HTTPException(status_code=409, detail=str(e))
    msg = f"Translation started for {book['title']}."
    if max_chapters:
        msg += f" Limited to {max_chapters} chapters."
    return {"message": msg}


@router.post("/books/{book_id}/retranslate")
def run_retranslation(book_id: int, method: str = "api"):
    """Re-translate failed chapters (translations are stored in the DB).

    POST /api/translate/books/{book_id}/retranslate?method=api|web
    Response: ``{"message": str}``. Errors: 404 / 400 / 409 as for /run.
    Side effects: background thread updates failed chapters in the DB.
    """
    # TODO: the 404/400/409 preamble is copy-pasted in /run, /retranslate and
    # /continue; a small _ensure_translatable(book_id) helper would remove it.
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    if not book.get("is_translated"):
        raise HTTPException(status_code=400, detail="Not a translated book")
    existing = get_translation_progress(book_id)
    if existing and existing.get("active"):
        raise HTTPException(status_code=409, detail="Translation already running for this book")
    try:
        retranslate_book(book_id, method=method, run_async=True)
    except TranslationRunningError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"message": f"Re-translation started for {book['title']}."}


@router.post("/books/{book_id}/continue")
def run_continue(book_id: int, method: str = "api"):
    """Resume failed chapters. Use after updating a stale cf_clearance cookie:
    failed chapters are reset to pending and re-translated.

    POST /api/translate/books/{book_id}/continue?method=api|web
    Response: whatever ``continue_book`` returns (message + counts).
    Errors: 404 / 400 / 409 as for /run.
    Side effects: resets failed chapters to pending in the DB, starts a
    background translation thread.
    """
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    if not book.get("is_translated"):
        raise HTTPException(status_code=400, detail="Not a translated book")
    existing = get_translation_progress(book_id)
    if existing and existing.get("active"):
        raise HTTPException(status_code=409, detail="Translation already running for this book")
    try:
        return continue_book(book_id, method=method, run_async=True)
    except TranslationRunningError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/refresh-cookies")
def refresh_cookies():
    """Open a real Chrome so Cloudflare issues a fresh cf_clearance, then save it.
    Run this manually when the automatic refresh limit was reached.

    POST /api/translate/refresh-cookies
    Response: result dict from ``refresh_cookies_manually`` (success + message).
    Side effects: OPENS a visible Chrome and blocks this request until done;
    saves the new cookies to the ``translate_cookies`` setting.
    """
    return refresh_cookies_manually()


@router.get("/books/{book_id}/progress")
def translation_progress(book_id: int):
    """GET /api/translate/books/{book_id}/progress -- real-time translation progress (polled by the UI).

    Response:
      * while a job is tracked: the live progress dict from the translator
        (``active``, counts, current chapter, ...);
      * otherwise: a fallback built from the DB row:
        ``{"active": False, "download_status", "downloaded_chapters", "total_chapters"}``.
    Errors: 404 only when no job is tracked AND the book does not exist.
    """
    progress = get_translation_progress(book_id)
    if not progress:
        book = db.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")
        # `x or 0` turns a NULL column into 0 for the UI.
        return {
            "active": False,
            "download_status": book["download_status"],
            "downloaded_chapters": book["downloaded_chapters"] or 0,
            "total_chapters": book["total_chapters"] or 0,
        }
    return progress


@router.post("/books/{book_id}/cancel")
def cancel_translation_task(book_id: int):
    """POST /api/translate/books/{book_id}/cancel -- ask a running translation to stop.

    Cancellation is cooperative: a flag is set and the worker stops after the
    current chapter, so the response returns before the job has actually ended.
    Errors: 404 if no translation is active for this book.
    """
    cancelled = cancel_translation(book_id)
    if cancelled:
        return {"message": "Cancellation requested for translation."}
    raise HTTPException(status_code=404, detail="No active translation for this book.")
