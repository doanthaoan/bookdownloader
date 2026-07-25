from fastapi import APIRouter, HTTPException, BackgroundTasks, Query, Body
from fastapi.responses import FileResponse, RedirectResponse
from typing import List, Dict, Optional
import os
import sqlite3
from pathlib import Path
from app.database import get_database
from app.services.extractor import ChapterListExtractor, extract_chapters_for_book
from app.services.downloader import download_book, cancel_download, get_download_progress, redownload_book, download_single_chapter
from app.config import TRUYENWIKI

router = APIRouter()
db = get_database()

@router.get("/")
async def get_all_books(search: str = None, status: str = None, author: str = None,
                         book_web_status: str = None, sent: int = None, tag: str = None,
                         page: int = 1, per_page: int = 50):
    """Fetch all books with optional search, status filter, author, book_web_status, sent, and pagination."""
    conn = db._get_connection()
    conn.row_factory = sqlite3.Row

    conditions = []
    params = []

    if search:
        conditions.append("(title LIKE ? OR seo_title_basic LIKE ?)")
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
    if sent is not None:
        conditions.append("is_sent = ?")
        params.append(sent)
    if tag:
        conditions.append("id IN (SELECT book_id FROM book_tags bt JOIN tags t ON t.id = bt.tag_id WHERE t.name = ?)")
        params.append(tag)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    # Total count
    count_row = conn.execute(f"SELECT COUNT(*) FROM books {where}", params).fetchone()
    total = count_row[0]

    # Paginated results — favorites first, then by creation date
    offset = (page - 1) * per_page
    rows = conn.execute(
        f"SELECT * FROM books {where} ORDER BY is_favorite DESC, created_at DESC LIMIT ? OFFSET ?",
        params + [per_page, offset]
    ).fetchall()

    books = [dict(r) for r in rows]

    # Batch-load tags for all returned books
    if books:
        book_ids = [b['id'] for b in books]
        placeholders = ','.join('?' * len(book_ids))
        tag_rows = conn.execute(f"""
            SELECT bt.book_id, t.name FROM book_tags bt
            JOIN tags t ON t.id = bt.tag_id
            WHERE bt.book_id IN ({placeholders})
            ORDER BY t.name
        """, book_ids).fetchall()
        tags_by_book = {}
        for tr in tag_rows:
            tags_by_book.setdefault(tr['book_id'], []).append(tr['name'])
        for b in books:
            b['tags'] = tags_by_book.get(b['id'], [])

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
        "books": books,
    }

@router.get("/tags")
async def list_all_tags():
    """List all tags with book counts."""
    return db.get_all_tags()

@router.get("/{book_id}")
async def get_book(book_id: int):
    """Fetch a specific book by ID"""
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    return book

@router.post("/extract")
async def extract_book(book_title: str, book_url: str, background_tasks: BackgroundTasks):
    """
    Start extraction process for a book.
    Runs in background to avoid HTTP timeout.
    """
    def run_extraction():
        extract_chapters_for_book(book_url, book_title)
    
    background_tasks.add_task(run_extraction)
    return {"message": f"Extraction started for {book_title}. Please check back in a moment."}

@router.get("/{book_id}/chapters")
async def get_chapters(book_id: int):
    """Get all chapters for a specific book"""
    chapters = db.get_chapters_by_book(book_id)
    return chapters

@router.post("/{book_id}/download")
async def download_book_task(book_id: int, background_tasks: BackgroundTasks, max_chapters: int = None):
    """
    Start downloading the book to DOCX.
    Runs in background.
    max_chapters: Limit the number of chapters to download in this session (for rate limiting).
    """
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    
    def run_download():
        try:
            download_book(book['title'], max_chapters=max_chapters)
        except Exception as e:
            print(f"Download failed: {e}")

    background_tasks.add_task(run_download)
    msg = f"Download started for {book['title']}."
    if max_chapters:
        msg += f" Limited to {max_chapters} chapters."
    return {"message": msg}

@router.post("/{book_id}/cancel-download")
async def cancel_download_task(book_id: int):
    """
    Cancel an active download for a book.
    The downloader will finish the current chapter and stop.
    """
    cancelled = cancel_download(book_id)
    if cancelled:
        return {"message": f"Cancellation requested for download task {book_id}."}
    raise HTTPException(status_code=404, detail="No active download found for this book.")

@router.post("/{book_id}/redownload")
async def redownload_book_task(book_id: int, background_tasks: BackgroundTasks, all_chapters: bool = False):
    """Re-download chapters into a separate _redownload.docx.
    
    By default only re-downloads failed chapters.
    Set all_chapters=true to re-download every chapter (fresh copy).
    """
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    def run():
        try:
            redownload_book(book['title'], all_chapters=all_chapters)
        except Exception as e:
            print(f"Redownload failed: {e}")

    background_tasks.add_task(run)
    label = "all chapters" if all_chapters else "failed chapters"
    return {"message": f"Re-download started for {book['title']} ({label}). Output goes to _redownload.docx."}

@router.post("/{book_id}/chapters/{chapter_id}/download")
async def download_single_chapter_task(book_id: int, chapter_id: int, background_tasks: BackgroundTasks):
    """Download a single chapter and append to _redownload.docx."""
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    def run():
        try:
            download_single_chapter(book['title'], chapter_id)
        except Exception as e:
            print(f"Single chapter download failed: {e}")

    background_tasks.add_task(run)
    return {"message": f"Download started for chapter {chapter_id} of '{book['title']}'."}

@router.get("/{book_id}/redownload-docx-info")
async def get_redownload_docx_info(book_id: int):
    """Check if _redownload.docx file exists."""
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    file_name = f"{book_id}_{book['seo_title_basic']}_redownload.docx"
    base_dir = Path(__file__).parent.parent.parent
    file_path = base_dir / TRUYENWIKI['book_path'] / file_name
    return {
        "exists": file_path.exists(),
        "file_name": file_name,
        "file_path": str(file_path.resolve()) if file_path.exists() else None,
        "size": file_path.stat().st_size if file_path.exists() else 0,
    }

@router.get("/{book_id}/redownload-docx")
async def get_redownload_docx(book_id: int):
    """Download the _redownload.docx file."""
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    file_name = f"{book_id}_{book['seo_title_basic']}_redownload.docx"
    base_dir = Path(__file__).parent.parent.parent
    file_path = base_dir / TRUYENWIKI['book_path'] / file_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Redownload DOCX file not found.")
    return FileResponse(
        path=str(file_path),
        filename=file_name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

@router.get("/{book_id}/progress")
async def get_progress(book_id: int):
    """Get real-time download progress for a book."""
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
async def get_docx(book_id: int):
    """Download the DOCX file for a book"""
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    
    file_name = f"{book_id}_{book['seo_title_basic']}.docx"
    base_dir = Path(__file__).parent.parent.parent
    print(f"Looking for DOCX file at: {base_dir / TRUYENWIKI['book_path'] / file_name}")
    file_path = base_dir / TRUYENWIKI['book_path'] / file_name
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="DOCX file not found. Please download the book first.")
    
    return FileResponse(
        path=str(file_path),
        filename=file_name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

@router.get("/{book_id}/docx-info")
async def get_docx_info(book_id: int):
    """Check if DOCX file exists and return its info"""
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    
    file_name = f"{book_id}_{book['seo_title_basic']}.docx"
    base_dir = Path(__file__).parent.parent.parent
    file_path = base_dir / TRUYENWIKI['book_path'] / file_name
    
    return {
        "exists": file_path.exists(),
        "file_name": file_name,
        "file_path": str(file_path.resolve()) if file_path.exists() else None,
        "size": file_path.stat().st_size if file_path.exists() else 0,
    }

@router.get("/{book_id}/cover")
async def get_cover_image(book_id: int):
    """Serve the cover image for a book.
    
    Searches for a local file matching {book_id}_{seo_title_basic}.{ext}
    in the book directory. Falls back to redirecting to the remote URL
    if stored. Returns 404 only if nothing exists.
    """
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    base_dir = Path(__file__).parent.parent.parent
    save_dir = base_dir / (db.get_setting('book_path') or TRUYENWIKI['book_path'])

    # Try local file with common extensions
    basename = f"{book_id}_{book['seo_title_basic']}"
    for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
        local_file = save_dir / f"{basename}{ext}"
        if local_file.exists():
            media_type = "image/jpeg" if local_file.suffix.lower() in ('.jpg', '.jpeg') else "image/png"
            return FileResponse(path=str(local_file), media_type=media_type)

    # No local file — redirect to remote URL if stored
    if book.get('cover_image_url'):
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=book['cover_image_url'])

    raise HTTPException(status_code=404, detail="No cover image available for this book")

@router.post("/{book_id}/refresh-info")
async def refresh_book_info(book_id: int):
    """Re-scrape book metadata (cover image URL, description, author, etc.)
    from the web and update the local DB. Does NOT re-extract chapters.
    Useful for backfilling cover_image_url / short_description on books
    that were extracted before those columns existed.
    """
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    if not book.get('book_url'):
        raise HTTPException(status_code=400, detail="Book has no URL to scrape from")

    from app.services.extractor import ChapterListExtractor
    from app.services.extractor import download_cover_image

    extractor = ChapterListExtractor()
    try:
        info = extractor.scrape_book_info(book['book_url'])
        if not info:
            raise HTTPException(status_code=500, detail="Failed to scrape book info")
        db.update_book_info(book_id, **info)
        # Save tags
        if info.get('tags'):
            db.set_book_tags(book_id, info['tags'])
        # Download cover image if we got a URL
        if info.get('cover_image_url'):
            save_dir = db.get_setting('book_path') or TRUYENWIKI['book_path']
            download_cover_image(book_id, book['seo_title_basic'], info['cover_image_url'], save_dir)
        return {
            "message": "Book info refreshed",
            "updated_fields": list(info.keys()),
        }
    finally:
        extractor.close()

@router.get("/{book_id}/tags")
async def get_book_tags(book_id: int):
    """Get tags for a specific book."""
    if not db.get_book(book_id):
        raise HTTPException(status_code=404, detail="Book not found")
    return {"tags": db.get_book_tags(book_id)}

@router.put("/{book_id}/tags")
async def update_book_tags(book_id: int, tags: List[str] = Body(...)):
    """Replace all tags for a book."""
    if not db.get_book(book_id):
        raise HTTPException(status_code=404, detail="Book not found")
    db.set_book_tags(book_id, tags)
    return {"tags": db.get_book_tags(book_id), "message": "Tags updated"}

@router.post("/{book_id}/toggle-favorite")
async def toggle_favorite(book_id: int):
    """Toggle the favorite status of a book."""
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    new_val = 0 if book.get('is_favorite') else 1
    db.update_book_info(book_id, is_favorite=new_val)
    return {"is_favorite": new_val, "message": "Favorite updated" if new_val else "Removed from favorites"}

@router.post("/{book_id}/toggle-sent")
async def toggle_sent(book_id: int):
    """Toggle the sent status of a book."""
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    new_val = 0 if book.get('is_sent') else 1
    db.update_book_info(book_id, is_sent=new_val)
    return {"is_sent": new_val, "message": "Marked as sent" if new_val else "Marked as not sent"}

@router.delete("/{book_id}")
async def delete_book(book_id: int):
    """Delete a book and its associated chapters"""
    conn = db._get_connection()
    conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
    conn.commit()
    return {"message": "Book deleted successfully"}

@router.get("/updates/check")
async def check_for_updates():
    """
    Check all ongoing/unknown books to see if they have new chapters.
    Returns a list of books that have updates.
    """
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
async def update_book_full(book_id: int, background_tasks: BackgroundTasks, max_chapters: int = None):
    """
    One-click update: re-scrape book info, extract new chapters, and download them.
    Combines check-updates + continue-extract + download into a single endpoint.
    """
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    def run():
        from app.services.extractor import ChapterListExtractor
        extractor = ChapterListExtractor()
        new_chapters = []
        try:
            # Step 1: Re-scrape book info (cheap — one page load)
            info = extractor.scrape_book_info(book['book_url'])
            if not info or not info.get('last_chapter_url'):
                print(f"⚠️ Could not scrape book info for {book['title']}")
                return

            db.update_book_info(book_id, **info)
            if info.get('tags'):
                db.set_book_tags(book_id, info['tags'])

            # Step 2: Check if their latest chapter is already in OUR chapters table
            their_latest = info['last_chapter_url']
            conn = db._get_connection()
            row = conn.execute(
                "SELECT 1 FROM chapters WHERE book_id = ? AND chapter_url = ? LIMIT 1",
                (book_id, their_latest)
            ).fetchone()
            if row:
                print(f"ℹ️ No new chapters for {book['title']} (latest chapter already in DB)")
                return

            # Step 3: New chapter detected — extract full list and diff
            chapters = extractor.extract_chapter_list(book['book_url'])
            if not chapters:
                print(f"⚠️ No chapters found for {book['title']}")
                return

            existing = db.get_chapters_by_book(book_id)
            existing_urls = {c['chapter_url'] for c in existing}

            new_chapters = [c for c in chapters if c['url'] not in existing_urls]
            if new_chapters:
                max_order = max((c['chapter_order'] for c in existing), default=0)
                for i, ch in enumerate(new_chapters, 1):
                    db.add_chapter(
                        book_id=book_id,
                        chapter_order=max_order + i,
                        chapter_title=ch['title'],
                        chapter_url=ch['url']
                    )
                total = len(existing) + len(new_chapters)
                db.update_book_status(book_id=book_id, total_chapters=total)
                print(f"✅ Added {len(new_chapters)} new chapters to {book['title']} (total: {total})")
            else:
                print(f"ℹ️ No new chapters for {book['title']}")

        finally:
            extractor.close()

        # Step 4: Download new chapters
        if new_chapters:
            from app.services.downloader import download_book
            try:
                download_book(book['title'], max_chapters=max_chapters)
            except Exception as e:
                print(f"❌ Download failed: {e}")

    background_tasks.add_task(run)
    return {"message": f"Full update started for {book['title']}. Checking & downloading new chapters..."}


@router.post("/{book_id}/continue-extract")
async def continue_extract(book_id: int, background_tasks: BackgroundTasks):
    """
    Continue extracting new chapters for a book that has been updated.
    Saves to a new extraction (existing chapters preserved, new ones appended).
    """
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    def run():
        from app.services.extractor import ChapterListExtractor
        extractor = ChapterListExtractor()
        try:
            # First re-scrape book info
            info = extractor.scrape_book_info(book['book_url'])
            if info:
                db.update_book_info(book_id, **info)
                if info.get('tags'):
                    db.set_book_tags(book_id, info['tags'])

            # Extract fresh chapter list
            chapters = extractor.extract_chapter_list(book['book_url'])
            if not chapters:
                print(f"No chapters found for {book['title']}")
                return

            # Get existing chapter URLs
            existing = db.get_chapters_by_book(book_id)
            existing_urls = {c['chapter_url'] for c in existing}

            # Find new chapters
            new_chapters = [c for c in chapters if c['url'] not in existing_urls]
            if not new_chapters:
                print(f"No new chapters for {book['title']}")
                return

            # Append new chapters to DB
            max_order = max((c['chapter_order'] for c in existing), default=0)
            for i, ch in enumerate(new_chapters, 1):
                db.add_chapter(
                    book_id=book_id,
                    chapter_order=max_order + i,
                    chapter_title=ch['title'],
                    chapter_url=ch['url']
                )

            total = len(existing) + len(new_chapters)
            db.update_book_status(book_id=book_id, total_chapters=total)
            print(f"✅ Added {len(new_chapters)} new chapters to {book['title']} (total: {total})")

        finally:
            extractor.close()

    background_tasks.add_task(run)
    return {"message": f"Continue extraction started for {book['title']}. Checking for new chapters..."}
