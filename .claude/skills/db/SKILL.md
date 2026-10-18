---
name: db
description: Inspect the live SQLite DB (books, chapters, corrections, settings, request_logs) read-only, or safely back up/restore rows before a write smoke test. Use instead of reading database.py or the .db file.
---

# Live DB access

The DB holds real data (~44 books, ~14k chapters with full content). Read-only by default.

```bash
backend/.venv/Scripts/python.exe .claude/skills/db/q.py "SELECT id,title,download_status,total_chapters,downloaded_chapters FROM books ORDER BY id"
```
- Opens with `mode=ro`, so writes fail. Cells are cut to 120 chars (2nd arg changes it), at most 200 rows.
- Never `SELECT chapter_content`/`translated_content` without `substr(...,1,300)` or `length(...)`.

## Schema (after migrations)

- `books`: id, title, seo_title_basic, seo_title_full (UNIQUE), book_url, download_status, total_chapters, downloaded_chapters, author, book_web_status, last_chapter_url, last_chapter_title, last_update_date, is_favorite, is_sent, cover_image_url, short_description, source_file, is_translated, auto_export_docx, notes, stt, book_status, created_at, updated_at
- `chapters`: id, book_id, chapter_order, chapter_title, chapter_url (UNIQUE per book; `translate://{book}/{order}` for translated), download_status, error_message, file_path, retry_count, chapter_content, translated_content, downloaded_at
- `book_corrections`: id, book_id, find_text, replace_text, enabled, sort_order
- `text_cleaning_rules`: id, rule_type(remove|replace), match_type(simple|regex), find_text, replace_text, enabled, sort_order, description
- `tags`(id,name) + `book_tags`(book_id,tag_id)
- `request_logs`: created_at (local time), request_type, status, session_type, domain, url, book_id, chapter_id, detail, error, duration_ms
- `application_settings`: key, value. Keys include domain, book_path, logs_path, user_agent, cookie_*, download_delay_min/max, page_load_timeout, request_session_mode, chapter_limit_session/nonsession, login_*, translate_* (api_endpoint, site, cookies JSON, browser_ua, impersonate, click/retry delay, max_retries, cookie_wait, cookie_refresh_max, source_path, target_lang). The sensitive keys are `account_password` and `cookie_*`/`translate_cookies`: never print their values.
- Views: `vw_books_progress`, `vw_chapters_progress`.

Book `download_status` values: pending, ready_for_download, in_progress, paused, completed, completed_with_errors, failed, cancelled. Chapter values: pending, completed, failed.

## Before a write smoke test

1. Dump the rows the endpoint will change, e.g. `q.py "SELECT * FROM book_corrections WHERE book_id=5" 100000 > %scratchpad%/bk.txt`. Or copy the whole DB with the server stopped: `cp backend/data/novel_downloader.db <scratchpad>/`.
2. Run the endpoint.
3. Restore through the same API (e.g. PUT corrections back), or with a short venv-python script that writes with a normal connection.
4. Never run DELETE/UPDATE without a WHERE on book_id/id.
