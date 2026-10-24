# Plan — Book Downloader

The living plan: refactor, fixes, and future features. Shipped history lives in `CHANGELOG.md` and git; the old v1.0/v1.1 checklists were removed from this file (see git history before 2026-10-18).

Rules for every item: keep the DB as the source of truth (AGENTS.md), make the smallest diff, add no new dependencies unless an item says so, and run the `ship` skill when done. Size: **S** < 30 min, **M** about 1–2 h, **L** half a day or more.

---

## Phase 0 — Cleanup (no behavior change)

- [x] **S** Delete `backend/app/services/translate.py`. It is a legacy script that runs at import, holds an old hardcoded `cf_clearance` cookie, and reads `D:\An\...\new_1.txt`.
- [x] **S** Delete the stray files: root `__pycache__/` (old `db_manager`/`truyen_taodanhsach` pyc), `backend/.claude/codediff.txt` (172 KB), and `DESIGN_OLD.md`, which describes the pre-web Excel/HTML toolkit.
- [x] **S** `requirements.txt`: **add `curl_cffi`** (see Phase 1 #1) and remove `python-dotenv`, which nothing imports.
- [x] **S** Remove dead backend code:
  - `extractor.py`: `update_book_html_template` (418–499), the large commented selector block (243–333), and the `__main__` input() demo.
  - `database.py`: `get_books_by_status`, `get_pending_chapters`, `get_books_by_tag`, `get_download_stats`, and the redundant `conn.row_factory = sqlite3.Row` lines (already set in `_get_connection`).
  - `text_cleaner.py`: `clean_with_all_rules`, `clean_custom_rules`. `utils.py`: `format_stt`. `login.py`: `_extract_cookies`, `_save_config`.
  - `downloader.py`: unused `re`/`signal` imports, `save_interval` (read but never used; remove it from the Settings UI too), and the `__main__` demo.
- [x] **S** Remove dead frontend code: the unused API wrappers `settingsApi.getCookies/updateCookie/updateLoginConfig`, `statsApi.daily`, and `translateApi.getBook`; `redownloadCount` plus the commented UI in `BookDetails.jsx`; the commented block and `console.log` in `Dashboard.jsx`; unused imports in `Extraction.jsx` and `Translate.jsx`.
- [x] **S** Move `backend/data/familytree.md` (a reading note) out of `backend/data/`, e.g. into a `notes/` folder.
- [x] **S** Bring `README.md` up to date: features list, venv setup, and links to AGENTS.md and PLAN.md.

## Phase 1 — Real bugs (ranked)

Backend:
1. [x] **S** **curl_cffi missing from the venv.** `Translator._request_api` falls back to plain `requests`, and that can't pass Cloudflare with `cf_clearance` (the cookie is bound to the TLS fingerprint). So the API method probably always fails and drops to slow Selenium. Fix: `pip install curl_cffi` and add it to requirements.
2. [x] **M** **Data loss on re-extract.** `POST /books/extract` with an existing title → `process_book_chapters` → `save_chapters_to_db` runs `DELETE FROM chapters`, which wipes every downloaded chapter's content and status. Fix: when the book exists, append only the new chapters (same logic as continue-extract; see Phase 2 `append_new_chapters`).
3. [x] **S** **Blocking endpoints freeze the server.** These `async def` endpoints run Selenium or network calls on the event loop: `books.refresh-info`, `books.updates/check`, `translate.check`, `translate.text`, `translate.refresh-cookies` (up to 60s), and `settings.auto-login`. While one runs, every other request, including progress polling, hangs. Fix: change `async def` to `def` in all `app/api/*.py`. Everything there is sync sqlite anyway, so FastAPI will run them in its threadpool.
4. [x] **S** **Title edit is silently ignored.** `PUT /books/{id}` reports `updated_fields: ['title']`, but `db.update_book_info` has no `title` in `allowed`. Clearing author/summary/status (`""` → `None`) is also dropped by the `v is not None` filter. Fix: add `title` (keep `seo_title_*` unchanged so file names stay stable), and let callers pass `None` explicitly (filter on key presence, not on value).
5. [x] **M** **Download registry can get stuck.** `TruyenWikiDownloader.__init__` opens Chrome before `register_download` is checked. Any exception after registering and before the trailing `unregister_download` leaves the book "active" forever, so it returns 409 until restart. Fix: register first, then `try/finally: unregister`. Also look the book up by **id**, not title (`download_book(book['title'])` → `book_id`).
6. [x] **S** **Translator allows double runs.** `register_task` doesn't refuse an existing task, and registration happens inside the new thread, so two quick clicks start two runs. An exception before `_translate_run` (e.g. a DB error) also leaves the task registered. Fix: register in the request thread and return False if one already exists, mirroring `register_download`; then `try/finally: unregister`.
7. [x] **S** **Inconsistent `book_path` resolution.** The downloader uses it relative to the CWD. The API and translator use it relative to `backend/` and read `TRUYENWIKI['book_path']` vs `db.get_setting('book_path')` inconsistently. Fix: one `config.book_dir() -> Path` (backend-relative, read from DB) used everywhere.
8. [x] **S** `logs.py` computes `LOGS_PATH` at import, before `load_truyenwiki_config()`, so the `logs_path` setting is ignored. Fix: use the `config.logs_dir()` helper.
9. [x] **S** **Double delay per chapter.** `process_chapter` sleeps `download_delay_min..max`, then the loop sleeps another hardcoded 2–4s, so the configured delay isn't what happens. Fix: keep only the configured one, or add the extra pause as an explicit setting.
10. [x] **S** `DELETE /books/{id}` and `continue-extract`/`update-full` don't check `is_download_active`. Return 409 like the download endpoints.

Frontend:
11. [x] **S** `TextCleaning.jsx:241`: the relative `download_url` resolves against the Vite origin and 404s. Prefix it with the API base.
12. [x] **S** `Settings.jsx`: there is a PUT on every keystroke (`handleSettingChange`), which lags inputs and can save stale values out of order. Fix: keep local state and save on blur (or with a Save button).
13. [x] **M** `BookDetails.jsx` polling has a stale `downloading` closure, so polling can run forever. Polling also doesn't start after redownload, update-full, or continue-extract. Each poll clobbers the Edit Info form; only corrections are guarded. Fix: stop on `!progress.active` and start polling from every action. This is mostly solved by the Phase 2 split.
14. [x] **S** `Translate.jsx:155`: a double Start leaks an interval. Clear the old interval before setting a new one.
15. [x] **S** `Statistics.jsx`: "today" uses `toISOString()` (UTC), so it's off by a day before 07:00 local. Refresh also doesn't reload the log table.
16. [x] **S** `BookList.jsx`: search fires two fetches (stale `page` plus `setPage(1)`). The author filter fetches on every keystroke. The status filter is missing `ready_for_download`/`paused`. Tag links `/?tag=` are read by nothing.
17. [x] **S** `Dashboard.jsx`: crashes if `getSettings` fails (`siteConfig = {}` then `.filter`).
18. [x] **S** About 15 call sites show only `err.message` and lose the backend `detail`. Fix: add one `errMsg(err)` helper in `api/index.js`.

Follow-ups found during the 1.4.9 comment pass (each has a `TODO` in the code):
19. [x] **S** `config.py` / `settings.update_truyenwiki`: a domain saved with `https://` gives the cookie domain `.https://…`. Strip the scheme first. (The current setting `wikicv.org` is not affected.)
20. [x] **S** `GET /books/?per_page=0` crashes with ZeroDivisionError. Validate `page` / `per_page` with `Query(ge=1)`.
21. [x] **S** `translate.py` `delete_source_file`, `/parse` and `POST /books` don't `os.path.basename()` the filename (path traversal). `logs.py` checks with `startswith`; use `Path.is_relative_to`.
22. [x] **S** `translate.py` `/check` and the summary task call `t.close()` outside `finally`, so an error leaks a Chrome process.
23. [x] **S** Changing the domain needs a server restart. Re-run `load_truyenwiki_config()` after saving it.
24. [x] **S** `get_cover_image` serves gif/webp covers as `image/png`. Use `mimetypes.guess_type`.

## Phase 2 — Structural refactor (dedupe)

Do these after Phase 1. Each one deletes more code than it adds.

- [x] **M** **One Selenium factory.** `browser.make_driver(headless=False, custom_ua=True)` plus `browser.inject_site_cookies(driver)` replace 5 copies: downloader, extractor, translator, login, and the text-cleaning test. As a side effect, the text-cleaning test and login get the ad-block and timeouts.
- [x] **S** **One chapter parser.** `parse_chapter_html(html) -> (title, paragraphs)` is shared by `downloader.process_chapter` and `text_cleaning.test_cleaning`, so the test then matches real downloads.
- [x] **M** **One downloader loop.** `run`, `run_redownload` and `run_single` are about 90% the same. Collapse them into `_run_batch(chapters, log_tag)`, plus a selection function per mode and one final-status function. Expect about −150 lines.
- [x] **M** **One translator job runner.** The tails of `translate_book` and `retranslate_book` (export, close, unregister, status) are copy-pasted. Collapse them into `_run_job(book_id, select_fn, suffix, status_fn)`. Also drop the `finally: pass` in `_translate_run`.
- [x] **S** **`append_new_chapters(book_id, extracted)`** in extractor, used by continue-extract, update-full, and re-extract of an existing book (this fixes bug #2). It also sets `ready_for_download` and the total in one place.
- [x] **S** **DOCX file endpoints.** Seven near-identical `*-docx` / `*-docx-info` handlers become one `_docx_file(book, suffix)` helper. Keep the URLs, because the frontend uses them.
- [x] **M** **Split `BookDetails.jsx`** (970 lines) into `BookToolbar`, `EditInfoForm` (owns its own form state, which fixes the clobber bug), `CorrectionsModal` (removes `correctionsOpenRef`), `BookHeader`, `DownloadActions`, `TranslateActions`, `DocxLinks` (shared), `CorrectionPreviewModal`, and `ChapterTable`, all under `pages/book-details/`.
- [x] **S** Frontend constants: web-status strings and colors, `POLL_MS = 2000`, the status list derived from `bookStatusColors`, and an `isTranslated(book)` helper.
- [x] **S** `Settings.jsx`: a `<SettingRow k label type />` replaces 5 copied input blocks.
- [x] **S** **One runnable check.** `backend/tests/test_render.py`, plain asserts with no framework, covering the pure functions: `apply_rules` == concatenation of non-removed `diff_rules` segments, `collapse_blank_lines` idempotence, case-insensitive corrections, and `parse_raw_file` splitting with a repeated title on a tiny inline sample. Run it with `.venv/Scripts/python.exe tests/test_render.py`, and add that to the AGENTS.md commands.

## Phase 3 — Features (pick when wanted)

Near-term, building on what exists:
- [ ] **M** **Enforce the daily chapter limits.** Today `chapter_limit_session/nonsession` are only displayed. The downloader should stop (book → `paused`) when today's count for its `session_type` reaches the limit, with a clear message.
- [x] **S** **Auto-switch access mode** when the session quota is exhausted (opt-in setting). This depends on the item above.
- [ ] **M** **Hash-based routing** (`#/book/12`, `#/?tag=x`) in `App.jsx` without a router dependency, so refresh keeps the page and tag links work.
- [ ] **S** **Book notes.** The `books.notes` column exists but isn't shown. Add a textarea in Edit Info (e.g. for series/family-tree notes).
- [ ] **S** **Batch "Update & Download"** from the Updates page for all books with new chapters, run sequentially (one Chrome at a time).

Bigger, only when a real need appears:
- [ ] **L** **Multi-source (v2).** This only matters once a second site is used. Sketch: `sources` table (domain, selectors JSON), `books.source_id`, extractor/downloader read selectors from the source. `backend/data/database_schema_v2.sql` holds an older draft; apply it via `_run_migrations`, not the SQL file.
- [ ] **L** **Google profile login.** Draft: `.opencode/plans/profile-login-implementation.md`. The current auto-login only does user/password.
- [ ] **S** Stop storing `account_password` in plaintext, or simply don't persist it (only the cookies are needed after login).

Dropped from the old plan: "Phase 6 — per-book text cleaning". It is covered by `book_corrections` (v1.2–v1.4.7).

## Known issues

- SQLite "cannot commit – no transaction is active" under concurrent threads was fixed with thread-local connections. If it comes back, serialize writes through a single writer thread.
