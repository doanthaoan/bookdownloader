"""
DOCX exporter — renders a book DOCX from the database (source of truth).

The DB stores CLEAN text (globally cleaned, but NOT per-book corrected) so that
per-book corrections can be re-applied idempotently at every render. This module
is shared by the downloader, the translator, and the export-corrected endpoint.

Storage conventions:
- Download books: chapter_title holds the globally cleaned page title,
  chapter_content holds the body as "<p>" paragraphs joined by "\\n\\n".
- Translated books: chapter_content holds the Chinese raw text and
  translated_content holds "<viet_title>\\n<viet_body>" (first line is the title).
"""

from pathlib import Path

import re

from docx import Document
from docx.shared import Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH

from app.services.translator import apply_corrections


def _find_cover_image(save_dir, book_id: int, seo_basic: str):
    basename = f"{book_id}_{seo_basic}"
    for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
        path = Path(save_dir) / f"{basename}{ext}"
        if path.exists():
            return str(path)
    return None


def chapter_text(ch, is_translated: bool) -> tuple:
    """Return (title, body) for a chapter from DB content (pre-corrections)."""
    if is_translated:
        raw = ch.get("translated_content") or ""
        if "\n" in raw:
            title, body = raw.split("\n", 1)
        else:
            title, body = raw, ""
    else:
        title = ch.get("chapter_title") or f"Chương {ch.get('chapter_order')}"
        body = ch.get("chapter_content") or ""
    return title, body


def diff_corrections(text: str, corrections: list) -> list:
    """Split text into segments showing what each per-book correction replaced.

    Mirrors apply_corrections exactly (sequential, case-insensitive), producing:
      {'type': 'text',     'text': <unchanged text>}
      {'type': 'removed',  'text': <original matched text>}
      {'type': 'replaced', 'text': <replacement text>}
    Used by the correction-preview UI to strike through the original and
    highlight the replacement. 'removed' segments are not re-scanned by later
    rules (they no longer exist in the string apply_corrections continues with);
    'replaced' and 'text' segments are.
    """
    segments = [{"type": "text", "text": text}]
    for c in corrections:
        if not c.get("enabled", True):
            continue
        find_text = c.get("find_text") or ""
        replace_text = c.get("replace_text") or ""
        if not find_text:
            continue
        new_segments = []
        for seg in segments:
            if seg["type"] == "removed":
                new_segments.append(seg)
                continue
            seg_text = seg["text"]
            last = 0
            for m in re.finditer(re.escape(find_text), seg_text, flags=re.IGNORECASE):
                if m.start() > last:
                    new_segments.append({"type": seg["type"], "text": seg_text[last:m.start()]})
                new_segments.append({"type": "removed", "text": m.group(0)})
                new_segments.append({"type": "replaced", "text": replace_text})
                last = m.end()
            if last < len(seg_text):
                new_segments.append({"type": seg["type"], "text": seg_text[last:]})
        segments = new_segments
    return segments


def build_book_docx(book: dict, chapters: list, corrections: list, output_path,
                    chapter_ids=None) -> Path:
    """Render a DOCX from DB chapter content, applying per-book corrections at
    render time. chapter_ids: optional list of chapter ids to include (empty/None
    = whole book). Nothing in the DB is modified.
    """
    doc = Document()
    for p in list(doc.paragraphs):
        p._element.getparent().remove(p._element)

    cover = _find_cover_image(Path(output_path).parent, book["id"], book["seo_title_basic"])
    if cover:
        img_p = doc.add_paragraph()
        img_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = img_p.add_run()
        run.add_picture(cover, width=Inches(3.5))

    doc.add_heading(book["title"], level=0)
    if book.get("author"):
        p = doc.add_paragraph()
        run_label = p.add_run("Tác giả: ")
        run_label.italic = True
        run_author = p.add_run(book["author"])
        run_author.bold = True
        run_author.italic = True

    is_translated = bool(book.get("is_translated"))
    for ch in chapters:
        if chapter_ids and ch["id"] not in chapter_ids:
            continue
        title, body = chapter_text(ch, is_translated)
        title = apply_corrections(title, corrections).strip()
        body = apply_corrections(body, corrections)
        if title:
            doc.add_heading(title, level=1)
        if is_translated:
            paragraphs = body.split("\n")
        else:
            paragraphs = body.split("\n\n")
        for para in paragraphs:
            para = para.strip()
            if para:
                doc.add_paragraph(para)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    return out