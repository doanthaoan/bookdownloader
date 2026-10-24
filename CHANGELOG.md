# Changelog

All notable changes to this project are documented here.

## Versioning scheme

| Segment         | Meaning                                             | Example    |
| --------------- | --------------------------------------------------- | ---------- |
| **Major** | Architecture/API change (multi-source, DB overhaul) | v2.0       |
| **Minor** | New features, backward-compatible                   | v1.1, v1.2 |
| **Patch** | Bug fixes, UI polish, small tweaks                  | v1.0.1     |

---

## [1.7.0] — 2026-10-25

### Added

- **Chapter status filter on Book Details.** A dropdown in the Chapters table header shows only `pending`, `in_progress`, `completed` or `failed` chapters, with a count next to each status. The filter is applied in the browser, so polling updates still show while it is set.

## [1.6.1] — 2026-10-25

### Changed

- **DOCX is only exported when you click Export.** Download, re-download, single-chapter download, update-full, translate, re-translate and continue no longer write any DOCX. Review and correct the book first, then use **Export Corrected** (`POST /api/books/{id}/export-corrected`), which is now the only DOCX writer.
- **Removed the outputs of the old auto-export.** The **Auto DOCX** toggle, the **Open DOCX** / **Open Redownload DOCX** / **Open Re-translate DOCX** buttons and their endpoints are gone (`toggle-auto-export`, `docx`, `docx-info`, `redownload-docx(-info)`, `retranslate-docx(-info)`). Old files on disk are left untouched. The `auto_export_docx` column is no longer read or written, and chapters no longer store a DOCX file name.

### Fixed

- **Exporting long books is fast.** python-docx searched the whole document for every new paragraph, so export time grew quadratically. Book 51 (3274 chapters) took more than 10 minutes and now takes about 19 s. Paragraphs are inserted in constant time (`_append_paragraph`). The output XML is byte-identical, with all corrections and global rules still applied. This is covered by `check_fast_docx_matches_python_docx`.

## [1.6.0] — 2026-10-21

### Added

- **Automatic account switching on the access limit.** When a chapter page shows "Đã hết lượt truy cập", the download no longer marks it as failed and moves on. It switches to the next identity and retries the same chapter. The order is guest → primary account → extra accounts. The Book Details progress line shows which identity is in use (`_build_identities`, `_use_identity`, `AccessLimitError`).
- **Extra Accounts on the Settings page.** You can add, log in and delete fallback accounts. Their cookies are stored in a new `site_accounts` table (endpoints: `GET/POST /api/settings/accounts`, `DELETE /api/settings/accounts/{id}`, `POST /api/settings/accounts/{id}/login`).
- **Choose what happens when every identity is limited.** `access_limit_action` = `stop` (default) sets the book to `paused`, and the chapters that were not downloaded stay pending. `wait` sleeps `access_limit_wait_minutes` (default 60), then starts over from guest. Cancel works during the wait.
- **`limited` request status.** Access-limit hits are logged separately in Statistics. Until now they counted as failures.

### Changed

- **The `request_session_mode` setting was removed from the UI.** Downloads always start as guest and switch to accounts automatically.

### Fixed

- **Empty chapters are no longer saved as completed.** A chapter page without any text is marked `failed` with the note "Empty content…", so it shows up for Re-download (`parse_chapter_html`).
- **The limit page no longer waits for the page-load timeout.** The chapter wait stops when either the content or the limit notice appears.

## [1.5.0] — 2026-10-19

### Added

- **Chapter list extraction resumes where it stopped.** When a book already has chapters, `extract_chapter_list()` jumps to the page that should hold the newest saved chapter and continues from there. Earlier pages are not re-read. If that chapter is not on that page (the site removed or reordered chapters), it falls back to a full scan from page 1.

### Changed

- **The chapter list is saved page by page.** `extract_chapter_list(book_url, book_id)` calls `append_new_chapters()` after each page of 501 chapters and returns `(added, ok)`. An error on a later page keeps the pages already read, and those chapters can be downloaded straight away. Extraction, Continue Extract and Update & Download all use it. Update & Download still downloads what was added when the list stops part-way.
- **Faster page reading.** Chapter links are parsed once from the page HTML with BeautifulSoup (`_read_chapter_page`) instead of about 1,000 WebDriver calls per page. The chapter-link selector that works is tried first on later pages, so a selector that doesn't match only costs its 20 s timeout once.
- **Removed the 10,000-chapter safety stop.** The loop can only move forward now, so books with more chapters are no longer cut off.

### Fixed

- **No more silently missed chapter pages.** After clicking to the next page, `_click_page_toward()` waits until the chapter list actually changes instead of sleeping a fixed 2–4 s. On a slow reload it used to re-read the old page and could stop early. Now it fails with an error, and the pages already read stay saved.

---

## [1.4.12] — 2026-10-19

### Fixed

- **Downloaded chapters no longer show the title twice.** Many source pages repeat the heading as the first paragraph. The new `docx_exporter.drop_repeated_title()` (called from `chapter_text()`, so it covers the DOCX and the preview) removes the first paragraph when it has the same "Chương N" number as the title and is at most twice as long. This happens at render time, so books already downloaded (e.g. book 49) are fixed on the next export without changing the DB.
- `tests/test_render.py` has a new check (`check_drop_repeated_title`), for 10 in total.

---

## [1.4.11] — 2026-10-19

### Fixed

- **A domain typed with `https://` works.** The new `config.normalize_domain()` turns `wikicv.org`, `.wikicv.org` or `https://wikicv.org/` into the same page URL and cookie domain. The cookie domain used to come out as `.https://…`.
- **A domain change applies without a restart.** Saving `domain`, `book_path` or `logs_path` (through `update-setting` or `update-truyenwiki`) reloads the config with the same code that runs at startup.
- **`GET /api/books/?per_page=0` no longer crashes.** `page` and `per_page` are validated (`page` ≥ 1, `per_page` 1–1000) and invalid values get HTTP 422.
- **Path-traversal guards.** Translate source files (parse, delete, create book, upload) go through one `_source_file()` guard: the folder part is dropped and the path must stay inside the source folder. The log viewer now uses an exact `is_relative_to` check instead of a string prefix.
- **No leaked Chrome.** The translate `/check` probe and the summary translation now close the Translator in `finally`.
- **Cover images are served with the right type** (`image/gif`, `image/webp`, …) via `mimetypes`.
- `tests/test_render.py` has 2 new checks (domain normalizer, filename guard), for 9 in total.

---

## [1.4.10] — 2026-10-18

### Changed (refactor — no new features)

- **One Selenium factory.** `browser.make_driver(headless, custom_ua, harden)` and `inject_site_cookies()` replace the five copied Chrome setups (downloader, extractor, translator, login, text-cleaning test). The translator keeps Chrome's real UA (`custom_ua=False`) and login stays unhardened. The downloader no longer prints secret cookie values.
- **One chapter parser.** `downloader.parse_chapter_html()` is shared with the Text Cleaning "Test" endpoint. The test DOCX now matches a real download exactly, title heading included. A page without a chapter title no longer fails the chapter (export falls back to "Chương N").
- **One translator job.** `translate_book` and `retranslate_book` share `_run_book_job()`, and the final status comes from one function, `_final_status()`.
- **DOCX file endpoints** (`*-docx`, `*-docx-info`, including the retranslate ones) share `docx_path` / `docx_info` / `docx_response`. URLs and responses are unchanged.
- **Book Details split.** `BookDetails.jsx` (970 lines) is now 271 lines plus 9 components and a `useBookProgress` polling hook in `pages/book-details/`. The Edit Info form and the Corrections modal keep their own state. Closing them without saving now discards the edits, and correction rows have stable keys.
- **Shared frontend constants** (`POLL_MS`, web statuses, `isTranslated()`), and a `<SettingRow>` component on the Settings page.
- **New `backend/tests/test_render.py`**: 7 plain-assert checks covering render rules, the preview diff, blank-line collapsing, both parsers and the status table.

## [1.4.9] — 2026-10-18

### Fixed

- **Re-extracting an existing book no longer deletes its chapters.** `POST /api/books/extract` with a title that already exists used to run `DELETE FROM chapters`, wiping downloaded content. All extraction paths (Extract, Continue Extract, Update & Download) now share `append_new_chapters()`, which only adds chapters whose URL isn't in the DB yet. It also skips URLs listed twice on the site.
- **Server no longer freezes during Selenium work.** Every endpoint is now a plain `def`, which FastAPI runs in a thread pool. Previously `refresh-info`, `updates/check`, `translate/check`, `translate/text`, `translate/refresh-cookies` and `settings/auto-login` ran on the event loop and blocked every other request, including progress polling.
- **Editing a book's title works.** `update_book_info` now allows `title`, and passing `None` clears a field (author, summary…) instead of being ignored. The file-name slug (`seo_title_*`) is kept, so existing DOCX and cover files still match.
- **A download can't get stuck as "running".** The downloader looks books up by id instead of title. A job registers before Chrome opens, and the new `_job()` context manager always closes Chrome and unregisters. Before, an error could leave the book returning 409 until restart. `run()` also no longer leaves a book `in_progress` when nothing is pending, and the downloaded count no longer includes failed chapters.
- **No double translation runs.** `register_task()` refuses a second job for the same book, and registration happens in the request thread. The API returns **409** (was 400). A guarded runner always unregisters the task and closes Chrome.
- **One place resolves the data folders.** New `config.book_dir()` and `logs_dir()` resolve `book_path` / `logs_path` relative to `backend/`. The downloader used to resolve them relative to the current working directory. The Logs page now honors the `logs_path` setting.
- **409 guards**: deleting a book, Continue Extract and Update & Download are refused while a download or translation runs for that book.
- **Translation API method works.** `curl_cffi` was missing from the venv and `requirements.txt`, so every API call silently fell back to plain `requests`, failed Cloudflare, and dropped to the slow Selenium web method.

- **Frontend**:
  - Text Cleaning: "Download Result" no longer 404s (the link now uses the API origin).
  - Settings: values save on blur/Enter instead of on every keystroke, so inputs no longer lag or save stale values.
  - Book Details: polling stops correctly. It also starts after re-download, single-chapter download, Update & Download, Continue Extract and the translate actions. It no longer overwrites the Edit Info form while you edit.
  - Translate: no leaked polling interval on a double Start.
  - Statistics: "today" uses local time (it was UTC, off by one day before 07:00). Refresh also reloads the log table.
  - Book List: one fetch per search; the author filter is debounced; the status filter includes `ready_for_download`/`paused`; clicking a tag filters in place.
  - Dashboard: no crash when settings fail to load.
  - Errors now show the backend's message everywhere (`errMsg()`).

### Changed

- Removed dead code and files: the legacy `services/translate.py` script (it ran on import and held a hardcoded cookie), `DESIGN_OLD.md`, unused DB/cleaner/login/utils helpers, and the unused `save_interval` setting. `python-dotenv` was dropped from requirements. Removed unused frontend API wrappers and the dead re-download-count UI. `familytree.md` moved to `notes/`.
- The pause between chapters is now the named constant `BETWEEN_CHAPTER_PAUSE` (2–4 s, in addition to `download_delay_min/max`). The pacing is unchanged.
- All backend and frontend code now has English docstrings/JSDoc and comments, plus `TODO` markers that point to PLAN.md items.

## [1.4.8] — 2026-10-18

### Fixed

- **Extraction "Read timed out"** — Selenium now uses the `eager` page-load strategy with a 60s page-load timeout (below Selenium's 120s HTTP read timeout). If a page never finishes loading, the partially loaded DOM is used instead of failing. The chapter list reuses the book page that `scrape_book_info` already loaded instead of requesting it a second time.
- **Book info kept when the chapter list fails** — `process_book_chapters` now saves the book (info, tags, cover) before extracting chapters. If the chapter list fails, the book stays in the DB and its chapters can be fetched later with Continue Extract, which also sets `ready_for_download` on a book that had no chapters.
- `extract_chapter_list` no longer returns a truthy `(False, msg)` tuple when no chapters are found.
- **Ad/tracker blocking in all Selenium sessions** — a new `app/services/browser.py` holds the shared helpers. The extractor, downloader and translator all use them:
  - `AD_BLOCK_PATTERNS`: ad and tracker hosts blocked through Chrome DevTools `Network.setBlockedURLs`. It covers hosts seen on wikicv book and chapter pages (tpmedia, Google Tag Manager/Analytics, DoubleClick, Facebook widget), common ad networks, and Vietnamese ad networks (admicro, eclick, adtima…). Cloudflare hosts are never blocked.
  - `harden_options` / `harden_driver`: `eager` page-load strategy, a 60s page-load timeout, and the ad block.
  - `load_page`: a `driver.get()` that falls back to the partially loaded DOM on timeout. This protects chapter downloads and translator page loads from the same "Read timed out" hang.

## [1.4.7] — 2026-08-23

### Added

- **Copy corrections between books** — new `POST /api/translate/books/{book_id}/corrections/copy` endpoint replaces the target book's corrections with ALL corrections of a source book (validates source exists, rejects same-book copy, preserves enabled state and order). In Book Details → Corrections popup, a "Copy from another book" section accepts a source book ID and copies with a confirmation prompt.

## [1.4.6] — 2026-08-17

### Added

- **Multi-empty-line cleanup** — new `collapse_blank_lines` helper collapses runs of 2+ consecutive newlines down to a single paragraph break (keeps at most one blank line) and strips leading/trailing blanks. Applied in every render path so all outputs share the same behavior:
  - Downloader save time (downloaded books are stored globally cleaned, so new content never carries blank-line runs).
  - DOCX export (`build_book_docx` — covers auto-export, export-corrected, and re-download exports for both book types).
  - Correction preview (preview now matches the exported DOCX).

## [1.4.5] — 2026-08-17

### Added

- **Export Corrected DOCX for translated books** — the translated-book Book Details page now shows the "Export Corrected" button and "Open Corrected DOCX" link (same backend endpoint as non-translated books; applies global Text Cleaning rules + per-book corrections at render time without touching the DB).

## [1.4.4] — 2026-08-17

### Changed

- **Book Details action buttons grouped into labeled sections** — the download-area controls are now laid out in three labeled rows: **Download** (Max input, Download All, Cancel), **Re-download** (failed, N, Range, All), and **Others** (Update & Download, Refresh Info, Continue Extract, Open DOCX, Open Redownload DOCX, Export Corrected, Open Corrected DOCX).

## [1.4.3] — 2026-08-17

### Changed

- **Re-download now available on partially-downloaded books** — the N / Range / All re-download controls show whenever a book is not actively downloading, not only when it's fully downloaded. Use it to re-fetch any range of chapters even while the book still has pending/failed chapters.
- **No status mislabeling on partial re-download** — `run_redownload` no longer forces the book status to `paused`/`completed`. The book keeps its pre-redownload status unless the re-download actually finishes the whole book (no pending/failed chapters remain).
- **Concurrent download guard** — `register_download` now refuses to register a second downloader for the same book, and `POST /books/{id}/download`, `/redownload`, and `/chapters/{id}/download` return 409 when a download is already running for that book. Prevents two Selenium drivers racing on cookie injection and DB writes.

## [1.4.2] — 2026-08-17

### Added

- **Partial / ranged re-download** — the Re-download section on the Book Details page now supports three modes (all taken by `POST /api/books/{id}/redownload`):
  - `count=N` — re-download only the first N chapters.
  - `start_order` / `end_order` — re-download only chapters within a given order range (inclusive).
  - `all_chapters=true` — the existing "Re-download All" behavior (all chapters into `_redownload.docx`).

## [1.4.1] — 2026-08-17

### Added

- **Per-book Auto DOCX export toggle** — new `books.auto_export_docx` column (default on, matching previous behavior). A checkbox on the Book Details page controls whether the DOCX is rendered automatically after a download/redownload/single-chapter download finishes. When unchecked, chapters are still saved to the DB but the DOCX export step is skipped. Backed by `POST /api/books/{id}/toggle-auto-export`.

---

## [1.4] — 2026-08-15

### Added

- **Request statistics** — every site request is now recorded in a new `request_logs` table and shown on a Statistics page (`/api/stats`):
  - Logged types: `chapter` (download), `book_page`, `chapter_list`, `cover_image`, `book_added`, `book_extract`, `book_download`, `translate_api`, `translate_web` — each with status (success/failed), access type, domain, URL, book/chapter, duration, and error.
  - Filters: date range, request type, status, access type (session/non-session), domain. Aggregates: totals, success/failed, by type, by access, and a daily bar chart.
  - Paginated request log table with book titles.
- **Non-session (free) download mode** — new global setting `request_session_mode` (`session` or `non_session`). In non-session mode the downloader **skips cookie injection**, so chapter requests count against the site's separate free/guest quota instead of the logged-in user's. Lets you double your daily chapter budget by mixing both modes. Each chapter request is tagged with its access type in the log (prepares for multi-profile in v2).
- **Daily chapter-request limits & alerts** — new settings `chapter_limit_session` / `chapter_limit_nonsession` (0 = no limit). The Statistics page shows today's chapter usage vs the limit per access type with a colored bar (green <70%, amber 70–89%, red ≥90%/at-limit) and "N remaining today".
- **Limit estimator** — pick a look-back window (N days) and an access type; the app computes the per-day chapter-request counts and suggests **max daily count** as the limit, with a one-click "Apply max as limit" button (writes back to the limit setting).
- Settings page: new **Request Settings** section for the access mode and both limits.

---

## [1.3] — 2026-08-15

### Added

- **DB is now the source of truth; DOCX is a derived artifact.**
  - Downloads store the globally-cleaned chapter text in `chapters.chapter_content` (and the cleaned page title in `chapter_title`); the incremental checkpoint DOCX writes were removed.
  - Translations store the raw Vietnamese result in the new `chapters.translated_content` column (format `<viet_title>\n<viet_body>`); per-book corrections are no longer burned in at translate time.
  - New shared `app/services/docx_exporter.py` renders a book DOCX from DB content and re-applies per-book corrections **idempotently** at render time. Used by the downloader, the translator, and the new export endpoint.
  - Download / translate / re-download / re-translate / continue runs now **auto-export the DOCX on completion** (from DB) with the same filename rules as before (`{book_id}_{seo}.docx`, `_redownload.docx`, `_retranslate.docx`).
- **Export Corrected DOCX**: `POST /api/books/{id}/export-corrected` (whole book or a selected list of `chapter_ids`) → `{book_id}_{seo}_corrected.docx`, served via `GET /api/books/{id}/export-corrected-docx`. Nothing in the DB is modified.
- **Correction preview**: `POST /api/books/{id}/preview-correction?chapter_id=N` returns the corrected chapter text rendered **in memory only** (never saved), so corrections can be checked before exporting. Now opens in a popup modal and shows a diff — the original matched text is struck through and the replacement is highlighted in yellow. Global Text Cleaning rules are included in the preview highlight too (plain rules only; regex rules are applied to the text but skipped in the diff because they can't be shown as a simple find→replace). Translated books now also get Global Text Cleaning applied at DOCX render time (per-paragraph, so paragraph breaks are preserved), matching the corrections-panel note that corrections run "after the global Text Cleaning rules".
- **Web-method Cloudflare recovery**: when the translate button keeps returning no result (Cloudflare 403 on the AJAX call even though the page loaded), the web method now — after exhausting the click retries (`translate_max_retries`) — refreshes the Cloudflare cookie (`_maybe_refresh_cookies`, bounded by `translate_cookie_refresh_max`) and retries the whole translate flow. If the refresh fails or the limit is reached, the run stops with a `CloudflareBlockedError` (book pauses, "Continue" after updating the cookie). The refresh budget is per run, so the next stuck chapter/run can refresh again; the `_cookie_refresh_count` guard prevents an infinite loop.
- Book Details UI: sticky top toolbar with "Export Corrected" / "Open Corrected DOCX" buttons, per-chapter "Preview" and "Export" actions, and the Corrections editor opened from a sticky button into a modal.
- `chapters.translated_content` migration (idempotent `ALTER TABLE`).

---

## [1.2] — 2026-08-14

### Added

- **Translate Novels** (`/api/translate` + Translate page): convert raw Chinese TXT novels to Vietnamese DOCX.
  - Scan/upload raw TXT files from `translate_source_path` (default `./data/translate_src`).
  - Parse raw files into book info + chapters (`第\d+章` splitter, author detection, summary from pre-chapter intro).
  - Create translated book + chapters in DB (raw content kept in `chapters.chapter_content`).
  - Per-book find/replace corrections (`book_corrections` table, applied to translated text).
  - Translation via dichtienghoa API (`POST /transtext`, form-encoded) with Selenium web fallback.
  - Web method uses stored `translate_cookies` (e.g. `cf_clearance`) to pass Cloudflare; cookie bound to the real browser UA, so the driver no longer forces a custom user-agent.
  - Background translation with progress polling + cancel; periodic DOCX checkpoint saves.
  - Output DOCX mirrors downloader structure: cover → title → author → chapter headings.
- `books.source_file` / `books.is_translated` columns to track translated books.
- Settings UI: Translation Settings section (source path, API endpoint, site, target lang, cookies).
- **Book Details**: "Edit Info" panel to update title, author, web status, tags, cover image (upload), and summary.
- **Book Details**: "Corrections" panel to view/edit per-book find/replace corrections for any book.
- **Per-book corrections on download**: downloader now applies the book's corrections after the global Text Cleaning rules.
- **Summary translation on save**: when a translated book is created, the pre-chapter intro is translated for the summary (best-effort; book still saves if translation fails).
- **Web translation retry**: before clicking the translate button the driver waits `translate_click_delay` (default 3s); if the result textarea stays empty it retries the click after `translate_retry_delay` (default 10s), up to `translate_max_retries` (default 3) times to avoid hammering the server. All three are configurable under Settings → Translation Settings.
- **API method passes Cloudflare**: `_api_call` now uses `curl_cffi` with Chrome TLS impersonation (`translate_impersonate`, e.g. `chrome146`) plus your real browser User-Agent (`translate_browser_ua`), so the stored `cf_clearance` cookie (bound to that fingerprint) validates — no Selenium needed for the API path. Falls back to plain `requests` if `curl_cffi` is missing.
- **Auto cookie refresh when Cloudflare blocks**: if the API request returns 403 (or the web method hits the challenge), a real (visible) Chrome is opened so Cloudflare issues a fresh `cf_clearance`, which is captured and saved to `translate_cookies`; the blocked request is then retried. Guarded by `translate_cookie_refresh_max` (default 1) so the process never loops forever and never hammers the server; `translate_cookie_wait` (default 60s) controls how long we wait for the fresh cookie.
- **Continue / Refresh Cookie buttons (Book Details)**: `POST /api/translate/books/{id}/continue` resets failed chapters back to `pending` so they are retried into the MAIN DOCX (after you update the cookie manually); `POST /api/translate/refresh-cookies` opens Chrome to capture a fresh cookie on demand.
- **Web method continues after cookie refresh**: previously, when the web method hit the Cloudflare challenge and auto-refreshed the cookie, it then reloaded the page (re-triggering the challenge) and gave up. Now the refresh leaves the driver on the already-loaded page and translation continues immediately.
- `/api/translate/text` returns a clean **502** with the actual failure message instead of an unhandled **500** ASGI exception when both API and web methods are blocked.
- **One request per chapter**: title + content are now sent in a single translation request (first output line = title) instead of two requests.
- **API tried first**: `GET /api/translate/prepare` now recommends `api` when cookies are present (curl_cffi + cookie), falling back to web only when there are no cookies; `translate()` still auto-falls-back api→web per call. Book title translation no longer probes the API (no extra Chrome window per click).
- **Method log line**: each translation prints a single `[api]`/`[web]` line showing which method produced the result.
- **Cancel fix**: `translate_book` no longer references an undefined `total` variable (would crash the background thread on cancel and leave the task registered, freezing the UI on "Cancel Translate").
- **Stop on Cloudflare mid-run**: if Cloudflare requires a new session during a run, the current chapter is marked `failed` and the run STOPS (book → `paused`) instead of moving to the next chapter and failing the whole batch. Refresh the cookie and click **Continue**, which retries the failed chapter into the main DOCX.

### Fixed

- Translation API now sends `application/x-www-form-urlencoded` body (was JSON, which the site rejects).
- Removed hardcoded/expired cookies from old `translate.py`; cookies come from DB settings.
- **Corrections now case-insensitive**: a name at the start of a paragraph or right after an opening quote (which Vietnamese capitalizes) now matches the lower-cased `find_text` (e.g. `lộ khi` matches `Lộ khi`).

---

### Fixed

* Missing cover at first extraction
* Missing description at first extraction

### Changed

* Remove old plan

## [1.1] — 2026-07-25

### Added

- **Book Management**: `is_favorite` and `is_sent` columns, toggle endpoints, sort favorites first.
- **Book List**: Favorite star (★), sent checkmark (✓) columns; Sent filter dropdown.
- **Book Details**: Favorite and Sent toggle buttons in header.
- **Settings UI**: Download Settings subsection (delays, timeout, save interval).
- **Settings UI**: Browser Settings subsection with User Agent dropdown (6 presets + Custom).
- **DOCX**: Author line (`Tác giả: **[name]**`) after book title.
- **DOCX**: Cover image on first page (centered, before title).
- **Book Cover & Description**: `cover_image_url` and `short_description` columns; extracted from site on scrape.
- **Book List**: Small cover thumbnail before title.
- **Book Details**: Large cover image on the left + short description in accordion.
- `get_user_agent()` shared helper — all Selenium entry points read from DB.
- `download_cover_image()` helper + `GET /api/books/{id}/cover` endpoint.
- **Tags system**: `tags` and `book_tags` tables; extracted from site (`Thể loại:` paragraph); full CRUD API.
- **Book List**: Tag filter dropdown, tag badges in each row.
- **Book Details**: Tags displayed as clickable badges.
- **Refresh Info**: `POST /api/books/{id}/refresh-info` endpoint + button to backfill metadata and download cover image.

### Changed

- Cookies come strictly from DB — removed `ENV_COOKIES` and `dotenv` dependency.
- Book List action buttons replaced with icons (📋 ⬇ ⏳) to save space.
- Title and author columns truncated with full text on hover.
- Progress text: `"chapter X of Y in this session"` for clarity.
- **Cover endpoint**: No longer requires `cover_image_url` in DB — searches filesystem by extension first.
- **Description scraping**: Uses `get_text('\n')` to preserve multiple paragraphs.
- **DOCX**: Cover image moved before book title.
- **Book list response**: Includes `tags` array (batch-loaded) for each book.

### Fixed

- `downloaded_chapters` count now cumulative (pre-existing + session), not session-only.
- Progress `total` reflects remaining chapters in current session, not total book chapters.
- Removed orphaned `SAVE_INTERVAL` module constant from `downloader.py`.
- Removed env fallback references from `config.py` docstrings/imports.
- **Cover 404**: Existing books with local cover files but no `cover_image_url` in DB now serve correctly.
- **Description missing**: Existing books pre-column show description after clicking Refresh Info.
- **Route conflict**: `GET /api/books/tags` now correctly routed (was caught by `/{book_id}` parameter).
- **JSX syntax**: Fixed unclosed template literal in BookList tag rendering.

### Planned (next)

- Google Profile Login — visible Chrome with user profile for interactive Google OAuth.
  Full plan at `.opencode/plans/profile-login-implementation.md`.

---

## [1.0] — 2026-07-19 to 2026-07-21

### Infrastructure & Backend

- FastAPI project with REST endpoints (Books, Chapters, Settings).
- SQLite database with WAL mode + thread-local connections.
- Selenium-based chapter extractor and DOCX downloader.
- Background task support for long-running downloads.

### Frontend

- React + Vite + Tailwind CSS.
- Dashboard (book list, filters, pagination).
- Book Details page (chapter list, download controls, progress).
- Settings page (cookies, auto-login, site config).
- Updates page, Continue Extract, Update & Download.

### Features

- Cookie auto-fetcher (username/password → Selenium login → save cookies).
- Real-time download progress with polling.
- Re-download (failed chapters or all).
- User-configurable global text cleaning rules (remove/replace, simple/regex).
- Test cleaning rules endpoint.
- Relative URLs for portable chapter storage.
- DOCX output with chapter headings.
- Search, filter, pagination on book list.

### Known Issues (at v1.0)

- `downloaded_chapters` count session-only instead of cumulative _(fixed in v1.1)_.
- Progress bar shows total book chapters instead of remaining _(fixed in v1.1)_.
