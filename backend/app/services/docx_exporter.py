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

Render pipeline (via build_render_rules / apply_rules / diff_rules):
- Global Text Cleaning rules are only re-applied for TRANSLATED books, because
  download books already had them applied when their content was saved.
  Regex-based cleaning rules transform the text but are not highlighted in the
  preview diff (a regex match cannot be shown as a simple find→replace).
- Per-book corrections are then applied (case-insensitive) to every book.
"""

from pathlib import Path

import re

from docx import Document
from docx.shared import Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH


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


def build_render_rules(db, book: dict) -> list:
    """Build the ordered transform rules for rendering a book's stored text.

    Each rule: {'find_text', 'replace_text', 'regex', 'case_sensitive', 'highlight'}.
    - Global Text Cleaning rules are included only for translated books (download
      books were already globally cleaned at save time). Regex rules are applied
      but not highlighted.
    - Per-book corrections follow (case-insensitive, highlighted).
    """
    rules = []
    if book.get("is_translated"):
        for r in db.get_text_cleaning_rules(enabled_only=True):
            find_text = (r.get("find_text") or "").strip()
            if not find_text:
                continue
            regex = r.get("match_type") == "regex"
            replace_text = r.get("replace_text") or ""
            if r.get("rule_type") == "remove":
                replace_text = ""
            rules.append({
                "find_text": find_text,
                "replace_text": replace_text,
                "regex": regex,
                "case_sensitive": not regex,
                "highlight": not regex,
            })
    for c in db.get_book_corrections(book["id"]):
        if not c.get("enabled", True):
            continue
        find_text = (c.get("find_text") or "").strip()
        if not find_text:
            continue
        rules.append({
            "find_text": find_text,
            "replace_text": c.get("replace_text") or "",
            "regex": False,
            "case_sensitive": False,
            "highlight": True,
        })
    return rules


def _apply_rule(text: str, rule: dict) -> str:
    """Apply a single rule to text (transform only, no highlight)."""
    if rule["regex"]:
        try:
            return re.sub(rule["find_text"], rule["replace_text"], text)
        except re.error:
            return text
    if rule["case_sensitive"]:
        return text.replace(rule["find_text"], rule["replace_text"])
    return re.sub(re.escape(rule["find_text"]),
                  lambda m: rule["replace_text"], text, flags=re.IGNORECASE)


def apply_rules(text: str, rules: list) -> str:
    """Apply the render rules in order and return the transformed text."""
    for r in rules:
        text = _apply_rule(text, r)
    return text


def apply_paragraphs(text: str, rules: list, preserve_newlines: bool = False) -> str:
    """Apply rules, preserving newline paragraph separators if requested.

    Global cleaning rules can match newlines (e.g. a control-character rule), so
    translated text is cleaned per-paragraph to avoid collapsing the structure.
    Download books are not re-cleaned this way (their content was already cleaned
    per-paragraph at save time), so preserve_newlines is False for them.
    """
    if not preserve_newlines:
        return apply_rules(text, rules)
    paras = text.split("\n")
    return "\n".join(apply_rules(p, rules) for p in paras)


def diff_paragraphs(text: str, rules: list) -> list:
    """diff_rules per paragraph, joined with literal newline segments so that
    cleaning rules matching newlines cannot collapse the paragraph structure."""
    paras = text.split("\n")
    out = []
    for i, p in enumerate(paras):
        if i > 0:
            out.append({"type": "text", "text": "\n"})
        out.extend(diff_rules(p, rules))
    return out


def diff_rules(text: str, rules: list) -> list:
    """Transform text through the rules, returning highlight segments.

    Mirrors apply_rules exactly (concatenating the non-'removed' segments equals
    apply_rules output):
      {'type': 'text',     'text': <unchanged text>}
      {'type': 'removed',  'text': <original matched text>}   → struck through
      {'type': 'replaced', 'text': <replacement text>}        → highlighted
    'removed' segments are not re-scanned by later rules (they no longer exist in
    the string apply_rules continues with). Rules with highlight=False (regex
    cleaning) transform text without emitting highlight segments.
    """
    segments = [{"type": "text", "text": text}]
    for r in rules:
        new_segments = []
        for seg in segments:
            if seg["type"] == "removed":
                new_segments.append(seg)
                continue
            seg_text = seg["text"]
            if not r.get("highlight", True):
                new_segments.append({"type": seg["type"], "text": _apply_rule(seg_text, r)})
                continue
            flags = 0 if r.get("case_sensitive") else re.IGNORECASE
            last = 0
            for m in re.finditer(re.escape(r["find_text"]), seg_text, flags=flags):
                if m.start() > last:
                    new_segments.append({"type": seg["type"], "text": seg_text[last:m.start()]})
                new_segments.append({"type": "removed", "text": m.group(0)})
                new_segments.append({"type": "replaced", "text": r["replace_text"]})
                last = m.end()
            if last < len(seg_text):
                new_segments.append({"type": seg["type"], "text": seg_text[last:]})
        segments = new_segments
    return segments


def build_book_docx(book: dict, chapters: list, rules: list, output_path,
                    chapter_ids=None) -> Path:
    """Render a DOCX from DB chapter content, applying the render rules at
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
        title = apply_rules(title, rules).strip()
        body = apply_paragraphs(body, rules, preserve_newlines=is_translated)
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