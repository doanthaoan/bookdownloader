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

Why rendering is idempotent:
  The DB text is never modified by a render. Every export starts again from
  the stored text and applies the CURRENT rule list, so rendering twice gives
  the same file, and editing a correction just means "render again" — no
  re-download or re-translation needed. If rules were baked into the DB
  instead, a rule like "A" -> "AB" would grow on every run, and removing a
  correction could never undo it.

Typical call sequence:
    rules = build_render_rules(db, book)
    build_book_docx(book, chapters, rules, path)      # real file
    diff_paragraphs(body, rules)                      # preview with highlights
"""

from pathlib import Path

import re

from docx import Document
from docx.shared import Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH


def _find_cover_image(save_dir, book_id: int, seo_basic: str):
    """Find the book's cover image next to the DOCX.

    Args:
        save_dir: folder to look in (str or Path).
        book_id: book id (first part of the file name).
        seo_basic: the book's seo_title_basic (second part of the file name).

    Returns:
        str | None: path of the first existing `{book_id}_{seo_basic}.<ext>`
        image, or None if there is no cover.
    """
    basename = f"{book_id}_{seo_basic}"
    for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
        # Path / "name" joins path parts (pathlib overloads the / operator).
        path = Path(save_dir) / f"{basename}{ext}"
        if path.exists():
            return str(path)
    return None


def chapter_text(ch, is_translated: bool) -> tuple:
    """Return (title, body) for a chapter from DB content (pre-corrections).

    Args:
        ch: chapter row as a dict.
        is_translated: True for translated books (read translated_content,
            whose first line is the title); False for downloaded books
            (read chapter_title + chapter_content).

    Returns:
        tuple[str, str]: (title, body), with no rules applied yet.
    """
    if is_translated:
        raw = ch.get("translated_content") or ""
        if "\n" in raw:
            # split(sep, 1) splits only at the FIRST newline -> exactly 2 parts.
            title, body = raw.split("\n", 1)
        else:
            title, body = raw, ""
    else:
        # Fallback title "Chương N" (Vietnamese for "Chapter N") if none stored.
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

    Args:
        db: Database instance (reads text-cleaning rules and book corrections).
        book: book row as a dict (needs 'id' and 'is_translated').

    Returns:
        list[dict]: rules in the order they must be applied. Read-only — no DB writes.
    """
    rules = []
    if book.get("is_translated"):
        for r in db.get_text_cleaning_rules(enabled_only=True):
            find_text = (r.get("find_text") or "").strip()
            if not find_text:
                # An empty pattern would match everywhere — skip it.
                continue
            regex = r.get("match_type") == "regex"
            replace_text = r.get("replace_text") or ""
            if r.get("rule_type") == "remove":
                # "remove" rules are just a replace with an empty string.
                replace_text = ""
            rules.append({
                "find_text": find_text,
                "replace_text": replace_text,
                "regex": regex,
                # Plain-text cleaning rules match case-sensitively; regex rules
                # carry their own flags inside the pattern if needed.
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
    """Apply a single rule to text (transform only, no highlight).

    Args:
        text: input text.
        rule: one rule dict from build_render_rules.

    Returns:
        str: the transformed text. An invalid regex leaves the text unchanged
        (re.error is swallowed so one bad user rule cannot break an export).
    """
    if rule["regex"]:
        try:
            return re.sub(rule["find_text"], rule["replace_text"], text)
        except re.error:
            return text
    if rule["case_sensitive"]:
        return text.replace(rule["find_text"], rule["replace_text"])
    # Case-insensitive literal replace: re.escape() turns the find text into a
    # literal pattern (so "." or "(" are not regex syntax), and the replacement
    # is given as a function `lambda m: ...` instead of a string. re.sub treats
    # a replacement STRING as a template ("\1", "\g<name>", backslashes), but a
    # function's return value is inserted verbatim — so user text containing
    # backslashes is not misinterpreted.
    return re.sub(re.escape(rule["find_text"]),
                  lambda m: rule["replace_text"], text, flags=re.IGNORECASE)


def apply_rules(text: str, rules: list) -> str:
    """Apply the render rules in order and return the transformed text.

    Args:
        text: input text.
        rules: ordered rule list from build_render_rules.

    Returns:
        str: text after every rule; each rule sees the output of the previous one.
    """
    for r in rules:
        text = _apply_rule(text, r)
    return text


def collapse_blank_lines(text: str, max_blank: int = 1) -> str:
    """Collapse runs of 2+ consecutive newlines down to a single paragraph
    break (``\\n\\n``), leaving at most `max_blank` empty line(s) between
    paragraphs, and strip leading/trailing blank lines. Idempotent.

    Args:
        text: input text (empty / None is returned as-is).
        max_blank: maximum number of empty lines allowed between paragraphs.

    Returns:
        str: the normalized text.
    """
    if not text:
        return text
    # With max_blank=1 the pattern is r"\n{3,}" -> replaced by "\n\n":
    # any run of 3+ newlines (2+ empty lines) becomes one empty line.
    text = re.sub(r"\n{" + str(max_blank + 2) + r",}", "\n" * (max_blank + 1), text)
    return text.strip("\n")


def apply_paragraphs(text: str, rules: list, preserve_newlines: bool = False) -> str:
    """Apply rules, preserving newline paragraph separators if requested.

    Global cleaning rules can match newlines (e.g. a control-character rule), so
    translated text is cleaned per-paragraph to avoid collapsing the structure.
    Download books are not re-cleaned this way (their content was already cleaned
    per-paragraph at save time), so preserve_newlines is False for them.

    Args:
        text: input text.
        rules: ordered rule list.
        preserve_newlines: True -> split on "\\n", apply rules to each line,
            join back (rules can never see or delete a newline).

    Returns:
        str: the transformed text.
    """
    if not preserve_newlines:
        return apply_rules(text, rules)
    paras = text.split("\n")
    # Generator expression `(f(p) for p in paras)` feeds join() lazily
    # without building an intermediate list.
    return "\n".join(apply_rules(p, rules) for p in paras)


def diff_paragraphs(text: str, rules: list) -> list:
    """diff_rules per paragraph, joined with literal newline segments so that
    cleaning rules matching newlines cannot collapse the paragraph structure.

    This is the preview counterpart of apply_paragraphs(preserve_newlines=True).

    Args:
        text: input text.
        rules: ordered rule list.

    Returns:
        list[dict]: highlight segments (see diff_rules), with
        {'type': 'text', 'text': '\\n'} between paragraphs.
    """
    paras = text.split("\n")
    out = []
    for i, p in enumerate(paras):
        if i > 0:
            out.append({"type": "text", "text": "\n"})
        # extend() appends every item of the list (append would nest the list).
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

    How it mirrors apply_rules: the text is held as a list of segments. Each
    rule is run over every live segment ('text' and 'replaced'); a match splits
    the segment into  before | removed(match) | replaced(new) | after.  Since
    'replaced' segments are re-scanned, a later rule can change a replacement,
    exactly as apply_rules would see it in the string.
    Known edge: a match that would span two segments is not found here
    (apply_rules would find it in the joined string).

    Args:
        text: input text.
        rules: ordered rule list from build_render_rules.

    Returns:
        list[dict]: segments as described above.
    """
    segments = [{"type": "text", "text": text}]
    for r in rules:
        new_segments = []
        for seg in segments:
            if seg["type"] == "removed":
                # Removed text is gone from the real output; keep it only for display.
                new_segments.append(seg)
                continue
            seg_text = seg["text"]
            if not r.get("highlight", True):
                # Regex cleaning rule: transform in place, keep the segment type.
                new_segments.append({"type": seg["type"], "text": _apply_rule(seg_text, r)})
                continue
            flags = 0 if r.get("case_sensitive") else re.IGNORECASE
            last = 0  # end index of the previous match in seg_text
            for m in re.finditer(re.escape(r["find_text"]), seg_text, flags=flags):
                if m.start() > last:
                    # Unchanged text between the previous match and this one.
                    new_segments.append({"type": seg["type"], "text": seg_text[last:m.start()]})
                new_segments.append({"type": "removed", "text": m.group(0)})
                new_segments.append({"type": "replaced", "text": r["replace_text"]})
                last = m.end()
            if last < len(seg_text):
                # Tail after the last match (or the whole segment if no match).
                new_segments.append({"type": seg["type"], "text": seg_text[last:]})
        segments = new_segments
    return segments


def build_book_docx(book: dict, chapters: list, rules: list, output_path,
                    chapter_ids=None) -> Path:
    """Render a DOCX from DB chapter content, applying the render rules at
    render time. chapter_ids: optional list of chapter ids to include (empty/None
    = whole book). Nothing in the DB is modified.

    Args:
        book: book row as a dict (id, title, author, seo_title_basic, is_translated).
        chapters: chapter rows (dicts) in reading order.
        rules: ordered rule list from build_render_rules.
        output_path: where to write the .docx (str or Path).
        chapter_ids: optional subset of chapter ids to include.

    Returns:
        Path: the written file path.

    Side effects:
        Writes (overwrites) the DOCX file; creates its parent folder if needed.
    """
    doc = Document()
    # The default template starts with an empty paragraph; remove it so the
    # document begins with our content. `list(...)` copies the paragraphs
    # first, because we must not modify a collection while iterating it.
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
        # "Tác giả: " = Vietnamese for "Author: ".
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
        # Translated text is cleaned per line (see apply_paragraphs), then blank
        # runs left behind by removals are collapsed.
        body = collapse_blank_lines(apply_paragraphs(body, rules, preserve_newlines=is_translated))
        if title:
            doc.add_heading(title, level=1)
        # Paragraph separator differs by storage convention (see module docstring):
        # translated = one paragraph per line, downloaded = blank-line separated.
        if is_translated:
            paragraphs = body.split("\n")
        else:
            paragraphs = body.split("\n\n")
        for para in paragraphs:
            para = para.strip()
            if para:
                doc.add_paragraph(para)

    out = Path(output_path)
    # parents=True creates missing parent folders; exist_ok=True: no error if it exists.
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    return out
