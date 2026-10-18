"""Self-checks for the pure text logic (no browser, no network, no DB writes).

Run from backend/ with the project venv:
    .venv\\Scripts\\python.exe tests\\test_render.py

Plain `assert` statements, no test framework: if a check fails, Python stops
with an AssertionError that shows the failing line. "All checks passed" means OK.

Note: importing app.services.* opens the real database (read-only use here —
the schema/migration step at import is idempotent and changes no data).
"""
import sys
import tempfile
from pathlib import Path

# Make `import app...` work when this file is run directly: put backend/ (the
# parent of tests/) at the front of Python's module search path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.docx_exporter import (apply_paragraphs, apply_rules,  # noqa: E402
                                        collapse_blank_lines, diff_rules)
from app.services.downloader import parse_chapter_html  # noqa: E402
from app.services.translator import Translator, TranslateTask, parse_raw_file  # noqa: E402


def rule(find, replace, regex=False, case_sensitive=False, highlight=True):
    """Build one render rule dict in the shape build_render_rules() produces."""
    return {"find_text": find, "replace_text": replace, "regex": regex,
            "case_sensitive": case_sensitive, "highlight": highlight}


def visible_text(segments):
    """Join diff segments the way the preview shows the RESULT (struck-out text hidden)."""
    return "".join(seg["text"] for seg in segments if seg["type"] != "removed")


def check_corrections():
    """Per-book corrections: case-insensitive, applied in order."""
    rules = [rule("lộ khi", "Lộ Thời"), rule("Thời", "Thì")]
    # "Lộ khi" at a sentence start is capitalised but must still match.
    assert apply_rules("Lộ khi đi.", rules) == "Lộ Thì đi."
    # A case-sensitive rule (global plain cleaning rule) must NOT match other casing.
    assert apply_rules("ABC abc", [rule("abc", "x", case_sensitive=True)]) == "ABC x"


def check_diff_matches_apply():
    """The preview (diff_rules) must show exactly what apply_rules produces."""
    rules = [rule("a", "b"), rule("x", "Y"), rule(r"\d+", "#", regex=True, highlight=False)]
    for text in ["aax 12", "no match", "", "AAA a1x"]:
        assert visible_text(diff_rules(text, rules)) == apply_rules(text, rules), text

    # Known limitation (preview only — the exported DOCX uses apply_rules and is
    # always right): a later rule can't match text that spans an earlier
    # replacement, because the preview keeps each replacement as its own segment.
    # "aab" -> rule 1 -> "bbb"; rule 2 "bb" would match across two replaced "b"s.
    # TODO: re-scan the joined text if this ever matters for real corrections.
    chained = [rule("a", "b"), rule("bb", "C")]
    assert apply_rules("aab", chained) == "Cb"
    assert visible_text(diff_rules("aab", chained)) == "bbb"  # preview shows the intermediate text


def check_blank_lines():
    """collapse_blank_lines keeps at most one empty line and is idempotent."""
    raw = "\n\nA\n\n\n\nB\nC\n\n\n"
    once = collapse_blank_lines(raw)
    assert once == "A\n\nB\nC"
    assert collapse_blank_lines(once) == once  # idempotent: running twice changes nothing


def check_translated_paragraphs():
    """Translated text is cleaned per line, so a rule can't delete line breaks."""
    rules = [rule(r"\s+", " ", regex=True, highlight=False)]
    assert apply_paragraphs("a  b\nc", rules, preserve_newlines=True) == "a b\nc"


class _NoCleaning:
    """Stand-in for TextCleaner that leaves text unchanged (avoids reading DB rules)."""

    def clean(self, text):
        return text


def check_chapter_parser():
    """parse_chapter_html: second book-title is the chapter title, empty <p> dropped."""
    html = """<p class="book-title">Book</p><p class="book-title">Chương 1</p>
              <div class="content-body-wrapper"><p>One</p><p>  </p><p>Two</p></div>"""
    assert parse_chapter_html(html, _NoCleaning()) == ("Chương 1", "One\n\nTwo")
    try:
        parse_chapter_html("<p>no content</p>", _NoCleaning())
        raise AssertionError("expected ValueError for a page without content")
    except ValueError:
        pass


def check_raw_parser():
    """parse_raw_file: author/summary detection, chapter split, repeated heading removed."""
    raw = ("我的书\n作者：某人\n简介文字\n"
           "第1章 开始\n第1章 开始\n内容一\n"
           "第2章 继续\n内容二\n")
    with tempfile.TemporaryDirectory() as d:  # deleted automatically afterwards
        path = Path(d) / "book.txt"
        path.write_text(raw, encoding="utf-8")
        parsed = parse_raw_file(str(path))
    assert parsed["raw_title"] == "我的书"
    assert parsed["author"] == "某人"
    assert parsed["summary"] == "简介文字"
    assert [c["title"] for c in parsed["chapters"]] == ["第1章 开始", "第2章 继续"]
    assert parsed["chapters"][0]["content"] == "内容一"  # repeated title line dropped


def check_final_status():
    """Book status decision table after a translation run."""
    status = Translator._final_status
    task = TranslateTask(0)
    done = [{"download_status": "completed"}]
    assert status(task, False, False, 3, 0, done) == "completed"
    assert status(task, False, True, 3, 0, done) == "paused"          # hit max_chapters
    assert status(task, False, False, 0, 2, done) == "failed"
    assert status(task, False, False, 1, 1, done) == "completed_with_errors"
    assert status(task, True, False, 1, 0, [{"download_status": "pending"}]) == "paused"
    task.cancelled = True
    assert status(task, False, False, 3, 0, done) == "cancelled"


if __name__ == "__main__":
    # Run every function whose name starts with "check_" (in definition order).
    checks = [f for name, f in list(globals().items()) if name.startswith("check_")]
    for f in checks:
        f()
        print(f"ok  {f.__name__}")
    print(f"All {len(checks)} checks passed")
