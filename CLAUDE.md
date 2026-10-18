@AGENTS.md

# Claude notes

Personal, local-only app. Optimize for: small diffs, no new deps, keep the DB-as-source-of-truth invariant.

## Do not read (token + privacy)

Enforced by `.claude/settings.json` deny rules + `.claude/hooks/guard.py`:
- `backend/data/downloads/**`, any `*.docx`, `raw/**`, `backend/data/translate_src/**`
- `backend/data/novel_downloader.db*` as a file — query it via the `db` skill instead
- `backend/data/logs/*.txt` — only open ONE specific log when the task needs it (`{book_id}_{seo}_success|failure.txt`)
- `frontend/package-lock.json`, `backend/.venv`, `node_modules`, `frontend/dist`

## Code map (read only what the task touches)

Backend (`backend/app/`):

| File | Owns |
|---|---|
| `database.py` | `NovelDatabase` (thread-local sqlite), `_run_migrations`, all CRUD + request-log stats |
| `config.py` | `TRUYENWIKI` dict (domain/paths, loaded from DB at startup), `get_cookies()`, `get_user_agent()` |
| `services/browser.py` | `make_driver()` (the ONLY place Chrome is created), `inject_site_cookies()`, `load_page()`, ad blocklist |
| `services/extractor.py` | `ChapterListExtractor`: `scrape_book_info`, `extract_chapter_list` (pagination by `data-start`), `process_book_chapters`; `download_cover_image` |
| `services/downloader.py` | `parse_chapter_html()`, `TruyenWikiDownloader` (`run` / `run_redownload` / `run_single` → `_job()` + `_process_batch()`), `_active_downloads` registry + progress |
| `services/translator.py` | `parse_raw_file`, `Translator` (api via curl_cffi → web Selenium fallback, Cloudflare cookie refresh), `translate_book` / `retranslate_book` (→ `_start_job` + `_run_book_job` + `_final_status`) / `continue_book`, `_active_translations` |
| `services/docx_exporter.py` | `build_render_rules`, `apply_rules/apply_paragraphs`, `diff_rules` (preview), `collapse_blank_lines`, `build_book_docx` |
| `services/text_cleaner.py` | `TextCleaner.clean()` — global rules at download-save time |
| `services/login.py` | `auto_login` (headless Selenium → cookies to settings) |
| `api/books.py` | `get_book_or_404`, `docx_path/docx_info/docx_response` helpers; books CRUD, extract, download/redownload/single, progress, docx/redownload/corrected file endpoints, preview, cover, refresh-info, updates/check, update-full, continue-extract |
| `api/translate.py` | source files, parse, create translated book, corrections (+copy), run/retranslate/continue/cancel/progress, refresh-cookies |
| `api/settings.py`, `text_cleaning.py`, `logs.py`, `stats.py` | as named |

Frontend (`frontend/src/`): `api/index.js` (all endpoints), `App.jsx` (state-based page switch, no router), `constants.js` (status colors), `pages/*.jsx` (one file per page). Book Details is split: `pages/BookDetails.jsx` (data + wiring) and `pages/book-details/*` (`useBookProgress` polling hook, toolbar, header, actions, modals, chapter table). Shared values live in `constants.js` (`POLL_MS`, statuses, `isTranslated`).

## Rules that prevent past bugs

- API endpoints are plain `def` (FastAPI thread pool). Never use `async def` for anything that touches Selenium, the network, or sqlite.
- Folders: always use `config.book_dir()` / `logs_dir()` (absolute, relative to `backend/`). Never build paths from `TRUYENWIKI['book_path']`.
- Chrome is created only through `browser.make_driver()`, and chapter HTML is parsed only by `downloader.parse_chapter_html()`. Don't copy either into a new module.
- Chapters are only ever added with `extractor.append_new_chapters()`. Never delete chapter rows to "refresh" a list.
- `db.update_book_info()` only writes keys in its `allowed` set. Passing `None` clears the column.
- Background jobs: register in the request thread (`register_download` / `register_task` return False if one is already running) and unregister in `finally` (`downloader._job()`, `translator._start_job()`).
- The services module `translate.py` no longer exists. The translator lives in `translator.py`.

## Adding things

- Endpoint: route in `app/api/<x>.py` (no prefix) → wrapper in `frontend/src/api/index.js` → page. Slow work → `BackgroundTasks` or `def`.
- Setting: read with `db.get_setting(key) or <default>`. It appears in the Settings page via `db_settings`.
- Column: append to the `migrations` list in `database.py`. Add it to `update_book_info.allowed` if it is editable.
- Finish with the `ship` skill (verify + CHANGELOG + commit message).
