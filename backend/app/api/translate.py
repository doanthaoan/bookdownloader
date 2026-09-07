from fastapi import APIRouter, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.responses import FileResponse
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
)
from app.config import TRUYENWIKI

router = APIRouter()
db = get_database()


def _source_dir() -> Path:
    base_dir = Path(__file__).parent.parent.parent
    src = db.get_setting("translate_source_path") or "./data/translate_src"
    path = base_dir / src
    path.mkdir(parents=True, exist_ok=True)
    return path


# --- Preparation / files ---

@router.get("/prepare")
async def prepare():
    """Return translation settings and the effective method WITHOUT probing the API.
    Cheap call used on page load. The actual availability check happens on demand
    via GET /check (or implicitly when a run starts)."""
    has_cookies = False
    raw_cookies = db.get_setting("translate_cookies") or ""
    if raw_cookies.strip():
        try:
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
async def check():
    """Probe the translation API availability (slow — only called on demand)."""
    t = Translator()
    api_ok = t.api_available()
    t.close()
    return {
        "api_available": api_ok,
        "method": "api" if api_ok else "web",
        "source_path": str(_source_dir()),
    }


@router.get("/source-files")
async def list_source_files():
    """List raw TXT files available in the source folder."""
    src = _source_dir()
    files = []
    for f in sorted(src.iterdir()):
        if f.is_file() and f.suffix.lower() in (".txt", ".text"):
            files.append({
                "filename": f.name,
                "size": f.stat().st_size,
                "modified": f.stat().st_mtime,
            })
    return {"files": files, "source_path": str(src)}


@router.post("/upload")
async def upload_source_file(file: UploadFile = File(...)):
    """Upload a raw TXT file into the source folder."""
    filename = file.filename or "upload.txt"
    if not filename.lower().endswith((".txt", ".text")):
        raise HTTPException(status_code=400, detail="Only .txt files are supported")
    # Sanitize filename
    safe_name = os.path.basename(filename)
    dest = _source_dir() / safe_name
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return {"filename": safe_name, "size": dest.stat().st_size}


@router.delete("/source-files/{filename}")
async def delete_source_file(filename: str):
    """Delete a raw TXT file from the source folder."""
    dest = _source_dir() / filename
    if not dest.exists():
        raise HTTPException(status_code=404, detail="File not found")
    dest.unlink()
    return {"message": f"Deleted {filename}"}


@router.post("/parse")
async def parse_file(filename: str):
    """Parse a raw TXT file and return book info + chapter titles (raw, untranslated)."""
    dest = _source_dir() / filename
    if not dest.exists():
        raise HTTPException(status_code=404, detail="File not found")
    result = parse_raw_file(str(dest))
    result["filename"] = filename
    return result


# --- Text helpers ---

class TranslateTextRequest(BaseModel):
    text: str
    method: Optional[str] = "api"


@router.post("/text")
async def translate_single_text(req: TranslateTextRequest):
    """Translate an arbitrary block of text (e.g. a book title)."""
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Empty text")
    try:
        translated = translate_text(req.text, method=req.method)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        print(f"{Fore.RED}Unexpected translation error: {e}")
        raise HTTPException(status_code=502, detail=f"Translation failed: {e}")
    return {"translated": translated}


# --- Book creation ---

class CreateBookRequest(BaseModel):
    filename: str
    title: str
    author: Optional[str] = ""


@router.post("/books")
async def create_translated_book(req: CreateBookRequest, background_tasks: BackgroundTasks):
    """Create a book + chapters from a parsed raw file. Chapters keep raw content
    in chapters.chapter_content; translation happens later in the run step.

    If the file has intro/summary text before the first chapter, we TRY to
    translate it for the book summary. If translation fails, the book is STILL
    saved (without a summary) — summary is best-effort only.
    """
    dest = _source_dir() / req.filename
    if not dest.exists():
        raise HTTPException(status_code=404, detail="File not found")
    parsed = parse_raw_file(str(dest))
    if not parsed["chapters"]:
        raise HTTPException(status_code=400, detail="No chapters found in file")

    # Prevent duplicate titles (seo_title_full is unique)
    existing = db.get_book_by_title(req.title)
    if existing:
        raise HTTPException(status_code=400, detail="A book with this title already exists")

    book_id = db.add_book(
        title=req.title,
        author=req.author or parsed["author"] or None,
        book_web_status="Parsed",
        short_description=f"Translated from {req.filename}",
    )
    db.update_book_info(book_id, source_file=req.filename, is_translated=1, total_chapters=len(parsed["chapters"]))

    for ch in parsed["chapters"]:
        placeholder_url = f"translate://{book_id}/{ch['order']}"
        db.add_chapter_with_content(
            book_id, ch["order"], ch["title"], placeholder_url, ch["content"]
        )

    # Best-effort: translate the intro/summary text. Never block book creation.
    summary = parsed.get("summary") or ""
    if summary:
        def translate_summary():
            try:
                t = Translator()
                translated = t.translate(summary)
                if translated and translated.strip():
                    db.update_book_info(book_id, short_description=translated.strip())
                    print(f"📝 Summary translated for book {book_id}")
                t.close()
            except Exception as e:
                print(f"{Fore.YELLOW}Summary translation failed (book saved without summary): {e}")
        background_tasks.add_task(translate_summary)

    return {"book_id": book_id, "message": f"Book '{req.title}' created with {len(parsed['chapters'])} chapters."}


@router.get("/books/{book_id}")
async def get_translated_book(book_id: int):
    """Get a translated book plus its chapter list (raw titles + translation status)."""
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

@router.get("/books/{book_id}/corrections")
async def get_corrections(book_id: int):
    return db.get_book_corrections(book_id)


class CorrectionsRequest(BaseModel):
    corrections: List[Dict]


@router.put("/books/{book_id}/corrections")
async def set_corrections(book_id: int, req: CorrectionsRequest):
    db.set_book_corrections(book_id, req.corrections)
    return {"message": "Corrections saved."}


class CopyCorrectionsRequest(BaseModel):
    source_book_id: int


@router.post("/books/{book_id}/corrections/copy")
async def copy_corrections(book_id: int, req: CopyCorrectionsRequest):
    """Replace this book's corrections with ALL corrections of another book."""
    if req.source_book_id == book_id:
        raise HTTPException(status_code=400, detail="Source and target are the same book.")
    source = db.get_book(req.source_book_id)
    if not source:
        raise HTTPException(status_code=404, detail=f"Source book {req.source_book_id} not found.")
    corrections = db.get_book_corrections(req.source_book_id)
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

@router.post("/books/{book_id}/run")
async def run_translation(book_id: int, method: str = "api", max_chapters: int = None):
    """Start translating pending chapters of a book in the background.
    Mirrors the downloader: only 'pending' chapters are processed; passing
    max_chapters limits the session (book status becomes 'paused' if more remain).
    """
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    if not book.get("is_translated"):
        raise HTTPException(status_code=400, detail="Not a translated book")
    existing = get_translation_progress(book_id)
    if existing and existing.get("active"):
        raise HTTPException(status_code=400, detail="Translation already running for this book")
    translate_book(book_id, method=method, run_async=True, max_chapters=max_chapters)
    msg = f"Translation started for {book['title']}."
    if max_chapters:
        msg += f" Limited to {max_chapters} chapters."
    return {"message": msg}


@router.post("/books/{book_id}/retranslate")
async def run_retranslation(book_id: int, method: str = "api"):
    """Re-translate failed chapters into a separate _retranslate.docx."""
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    if not book.get("is_translated"):
        raise HTTPException(status_code=400, detail="Not a translated book")
    existing = get_translation_progress(book_id)
    if existing and existing.get("active"):
        raise HTTPException(status_code=400, detail="Translation already running for this book")
    retranslate_book(book_id, method=method, run_async=True)
    return {"message": f"Re-translation started for {book['title']}. Output goes to _retranslate.docx."}


@router.post("/books/{book_id}/continue")
async def run_continue(book_id: int, method: str = "api"):
    """Resume failed chapters into the MAIN DOCX. Use after updating a stale
    cf_clearance cookie: failed chapters are reset to pending and re-translated,
    appending to {book_id}_{seo}.docx (not a separate retranslate file)."""
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    if not book.get("is_translated"):
        raise HTTPException(status_code=400, detail="Not a translated book")
    existing = get_translation_progress(book_id)
    if existing and existing.get("active"):
        raise HTTPException(status_code=400, detail="Translation already running for this book")
    return continue_book(book_id, method=method, run_async=True)


@router.post("/refresh-cookies")
async def refresh_cookies():
    """Open a real Chrome so Cloudflare issues a fresh cf_clearance, then save it.
    Run this manually when the automatic refresh limit was reached."""
    return refresh_cookies_manually()


@router.get("/books/{book_id}/retranslate-docx-info")
async def retranslate_docx_info(book_id: int):
    """Check if _retranslate.docx exists for a translated book."""
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    file_name = f"{book_id}_{book['seo_title_basic']}_retranslate.docx"
    base_dir = Path(__file__).parent.parent.parent
    file_path = base_dir / (db.get_setting("book_path") or TRUYENWIKI["book_path"]) / file_name
    return {
        "exists": file_path.exists(),
        "file_name": file_name,
        "file_path": str(file_path.resolve()) if file_path.exists() else None,
        "size": file_path.stat().st_size if file_path.exists() else 0,
    }


@router.get("/books/{book_id}/retranslate-docx")
async def retranslate_docx(book_id: int):
    """Download the _retranslate.docx file."""
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    file_name = f"{book_id}_{book['seo_title_basic']}_retranslate.docx"
    base_dir = Path(__file__).parent.parent.parent
    file_path = base_dir / (db.get_setting("book_path") or TRUYENWIKI["book_path"]) / file_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Retranslate DOCX file not found.")
    return FileResponse(
        path=str(file_path),
        filename=file_name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


@router.get("/books/{book_id}/progress")
async def translation_progress(book_id: int):
    """Get real-time translation progress for a book."""
    progress = get_translation_progress(book_id)
    if not progress:
        book = db.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")
        return {
            "active": False,
            "download_status": book["download_status"],
            "downloaded_chapters": book["downloaded_chapters"] or 0,
            "total_chapters": book["total_chapters"] or 0,
        }
    return progress


@router.post("/books/{book_id}/cancel")
async def cancel_translation_task(book_id: int):
    cancelled = cancel_translation(book_id)
    if cancelled:
        return {"message": "Cancellation requested for translation."}
    raise HTTPException(status_code=404, detail="No active translation for this book.")