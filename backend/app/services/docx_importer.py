"""
DOCX importer — fills chapters that have no stored content from a book DOCX.

Use cases: books downloaded before content was stored in the DB (see
docx_exporter), or a book obtained elsewhere whose DOCX uses the same chapter
titles. Once the text is in the DB, the book can be exported with corrections.

The DOCX must use the layout the exporter writes: a "Heading 1" paragraph per
chapter title, then the body paragraphs until the next heading. The source is
the largest "{book_id}_*.docx" in config.book_dir().

Matching a DOCX heading to a chapter row (any download_status):
  1. By normalized title (case, spaces and punctuation ignored), in reading
     order, so duplicate titles are paired first-to-first.
  2. If NO title matched but the DOCX has exactly one heading per chapter,
     pair them by position.
Imported chapters become 'completed'; unmatched ones stay empty.

Jobs run in a background thread and are registered in the DOWNLOAD registry
(downloader.register_download) with an ImportJob, so the existing progress
polling, the Cancel button and the one-job-per-book rule work unchanged.

Caveat: old DOCX text may already contain the corrections of that time.
Re-applying a correction at render time is harmless unless its replacement
contains its own find text.
"""

import re
from collections import defaultdict
from pathlib import Path

from docx import Document

from app.config import book_dir
from app.database import get_database
from app.services.docx_exporter import collapse_blank_lines
from app.services.downloader import register_download, unregister_download


class ImportJob:
    """Progress/cancel state of one import, shaped like the fields that
    downloader.get_download_progress() reads from a TruyenWikiDownloader."""

    def __init__(self):
        self._cancel_flag = False      # set by downloader.cancel_download()
        self._remaining_count = 0      # chapters to write (0 while reading the DOCX)
        self._success_count = 0
        self._fail_count = 0           # always 0: an import has no per-chapter failures
        self._current_index = 0
        self._current_title = ""
        self._identities = []          # no site identities: progress shows identity ''
        self._identity_idx = 0
        self._waiting_until = None


def parse_orders(text: str):
    """Parse a chapter selection like "1,3,4-20" into a set of chapter orders.

    Args:
        text: comma-separated numbers and inclusive "a-b" ranges; blank = all.

    Returns:
        set[int] | None: the selected chapter_order values, or None for "all".

    Raises:
        ValueError: on anything that is not a number or a valid range.
    """
    if not (text or "").strip():
        return None
    orders = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue  # tolerate "1,,3" and a trailing comma
        # partition("-") -> ("4", "-", "20") for a range, ("7", "", "") for a number.
        lo, dash, hi = part.partition("-")
        lo = int(lo)  # int() raises ValueError on junk like "a"
        hi = int(hi) if dash else lo
        if lo < 1 or hi < lo:
            raise ValueError(f"Invalid range: {part}")
        # set.update(range(...)) adds every number lo..hi (range's end is exclusive).
        orders.update(range(lo, hi + 1))
    return orders


def find_source_docx(book_id: int):
    """Pick the largest DOCX of a book as the import source.

    A book may have several files ("{id}_{seo}.docx", "..._redownload.docx",
    "..._corrected.docx"); the biggest one holds the most chapter text.

    Args:
        book_id: books.id (file names start with "{book_id}_").

    Returns:
        Path | None: the largest matching file, or None if there is none.
    """
    # The "_" after the id keeps book 1 from matching "10_...docx".
    files = list(book_dir().glob(f"{book_id}_*.docx"))
    # max(..., key=...) picks the item with the largest key; default=None for an empty list.
    return max(files, key=lambda p: p.stat().st_size, default=None)


def read_docx_chapters(path, job: ImportJob = None) -> list:
    """Split a book DOCX into chapters.

    Args:
        path: .docx file path.
        job: optional ImportJob; reading stops early (returns []) once it is cancelled.

    Returns:
        list[tuple[str, str]]: (title, body) per "Heading 1" paragraph, in file
        order. body = the following non-empty paragraphs joined by "\\n\\n"
        (the downloaded-book storage format). Text before the first heading
        (cover, book title, author) is ignored.
    """
    chapters = []
    for p in Document(str(path)).paragraphs:
        # `p._p.style` is the raw style id ("Heading1") read straight from the
        # XML; `p.style.name` would look the style up in styles.xml for every
        # paragraph, which is slow on 200k-paragraph books.
        if p._p.style == "Heading1":
            if job and job._cancel_flag:
                return []
            chapters.append((p.text.strip(), []))
        elif chapters and (text := p.text.strip()):
            # Walrus `:=` strips once and tests the result in the same line.
            chapters[-1][1].append(text)
    return [(title, collapse_blank_lines("\n\n".join(paras))) for title, paras in chapters]


def _norm(title: str) -> str:
    """Normalize a title for matching: lower-case words only, so
    "Chương 1: Sớm tới" and "chương 1 sớm  tới" compare equal."""
    # \w+ = runs of letters/digits (Unicode-aware, so Vietnamese letters count).
    return " ".join(re.findall(r"\w+", (title or "").casefold()))


def match_chapters(doc_chapters: list, db_chapters: list, wanted_ids: set) -> tuple:
    """Pair DOCX chapters with the DB chapter rows that should be filled.

    Args:
        doc_chapters: [(title, body)] from read_docx_chapters.
        db_chapters: ALL chapter dicts of the book, in chapter_order (needed so
            duplicate titles and positions line up with the DOCX).
        wanted_ids: ids of the chapters to fill (empty + selected).

    Returns:
        tuple[list[tuple[dict, str]], str]: ([(chapter_row, body)], mode) where
        mode is "title", "position" or "none".
    """
    # defaultdict(list): a missing key starts as an empty list, so we can append directly.
    bodies = defaultdict(list)
    for title, body in doc_chapters:
        bodies[_norm(title)].append(body)
    pairs = []
    for ch in db_chapters:
        queue = bodies.get(_norm(ch.get("chapter_title")))
        if queue:
            # pop(0) for EVERY chapter with this title (filled or not), so the
            # n-th "Ngoại truyện" in the DB gets the n-th one in the DOCX.
            body = queue.pop(0)
            if ch["id"] in wanted_ids and body:
                pairs.append((ch, body))
    if pairs:
        return pairs, "title"
    if len(doc_chapters) == len(db_chapters):
        # zip() walks both lists in step.
        pairs = [(ch, body) for ch, (_, body) in zip(db_chapters, doc_chapters)
                 if body and ch["id"] in wanted_ids]
        return pairs, "position"
    return [], "none"


def import_book(db, book: dict, orders: set = None, job: ImportJob = None) -> dict:
    """Fill a book's chapters that have no content from its largest DOCX.

    Args:
        db: Database instance.
        book: book row as a dict.
        orders: chapter_order values to import (None = every empty chapter).
            Chapters that already have content are never overwritten.
        job: optional ImportJob for progress + cancel.

    Returns:
        dict: {"book_id", "file", "doc_chapters", "missing", "imported", "mode",
        "cancelled", "skipped" (reason when nothing was attempted)}.

    Side effects: UPDATE chapters.chapter_content + status 'completed' for each
    matched chapter; then the book's downloaded count (and status 'completed'
    once no pending/failed chapter is left).
    """
    job = job or ImportJob()
    report = {"book_id": book["id"], "file": None, "doc_chapters": 0, "missing": 0,
              "imported": 0, "mode": "none", "cancelled": False, "skipped": None}
    if book.get("is_translated"):
        report["skipped"] = "translated book"
        return report
    chapters = db.get_chapters_by_book(book["id"])
    # Set comprehension `{x for ...}`: O(1) `in` checks in match_chapters.
    wanted = {c["id"] for c in chapters if not c.get("chapter_content")
              and (orders is None or c["chapter_order"] in orders)}
    report["missing"] = len(wanted)
    if not wanted:
        report["skipped"] = "no selected chapter without content"
        return report
    path = find_source_docx(book["id"])
    if not path:
        report["skipped"] = "no DOCX file found"
        return report
    report["file"] = Path(path).name

    job._current_title = f"Reading {report['file']}"
    doc_chapters = read_docx_chapters(path, job)
    pairs, mode = match_chapters(doc_chapters, chapters, wanted)
    report.update(doc_chapters=len(doc_chapters), mode=mode)

    job._remaining_count = len(pairs)
    # enumerate(..., 1) yields (1, pair1), (2, pair2), ... — index starts at 1.
    for index, (ch, body) in enumerate(pairs, 1):
        if job._cancel_flag:
            break
        job._current_index = index
        job._current_title = ch["chapter_title"]
        db.update_chapter_content(ch["id"], body)
        if ch["download_status"] != "completed":
            db.update_chapter_status(ch["id"], "completed")
        job._success_count += 1
    report.update(imported=job._success_count, cancelled=job._cancel_flag)

    if job._success_count:
        statuses = [c["download_status"] for c in db.get_chapters_by_book(book["id"])]
        db.update_book_status(
            book_id=book["id"],
            # None = keep the current book status (see update_book_status).
            download_status=None if ("pending" in statuses or "failed" in statuses) else "completed",
            downloaded_chapters=statuses.count("completed"))
    return report


def run_import_job(book_id: int, job: ImportJob, orders: set = None):
    """Background-thread body for one book. The caller has ALREADY registered
    `job` (register_download in the request thread); this always unregisters it.

    Side effects: see import_book; prints the report to the console.
    """
    try:
        db = get_database()
        print(f"DOCX import: {import_book(db, db.get_book(book_id), orders, job)}")
    finally:
        # try/finally: the book must never stay "active" (every later job would get 409).
        unregister_download(book_id)


def run_import_all():
    """Background-thread body: import every downloaded book that has chapters
    without content, one book at a time. Books with a running job are skipped.
    Each book is registered while it imports, so its Book Details page shows
    progress and its Cancel button stops that book (the loop moves on).

    TODO: no single "cancel all" — add one if the all-books run gets too long.
    """
    db = get_database()
    # Ad-hoc query: ids of downloaded books with at least one empty chapter.
    rows = db._get_connection().execute("""
        SELECT DISTINCT c.book_id FROM chapters c JOIN books b ON b.id = c.book_id
        WHERE b.is_translated = 0 AND (c.chapter_content IS NULL OR c.chapter_content = '')
        ORDER BY c.book_id
    """).fetchall()
    for (book_id,) in rows:  # each row is a 1-tuple; unpack it in the for target
        job = ImportJob()
        if register_download(book_id, job):
            run_import_job(book_id, job)


if __name__ == "__main__":
    # Self-check of the pure logic (no DB, no files).
    assert parse_orders(" ") is None
    assert parse_orders("1,3,4-6,") == {1, 3, 4, 5, 6}
    for bad in ("a", "5-2", "0"):
        try:
            parse_orders(bad)
            raise AssertionError(bad)
        except ValueError:
            pass

    doc = [("Chương 1: Mở đầu", "a\n\nb"), ("Ngoại truyện", "c"), ("Ngoại truyện", "d")]
    rows = [{"id": 1, "chapter_title": "chương 1 mở đầu"},
            {"id": 2, "chapter_title": "Ngoại truyện"},   # has content -> not wanted
            {"id": 3, "chapter_title": "ngoại  truyện"}]
    pairs, mode = match_chapters(doc, rows, {1, 3})
    # Chapter 3 gets the SECOND "Ngoại truyện" body even though 2 is skipped.
    assert mode == "title" and [(c["id"], b) for c, b in pairs] == [(1, "a\n\nb"), (3, "d")]
    # No title matches + same count -> positional, only wanted rows.
    rows2 = [{"id": 7, "chapter_title": "Phần 1"}, {"id": 8, "chapter_title": "Phần 2"},
             {"id": 9, "chapter_title": "Phần 3"}]
    pairs, mode = match_chapters(doc, rows2, {7, 9})
    assert mode == "position" and [(c["id"], b) for c, b in pairs] == [(7, "a\n\nb"), (9, "d")]
    assert match_chapters(doc[:1], rows2, {7}) == ([], "none")
    print("docx_importer self-check OK")
