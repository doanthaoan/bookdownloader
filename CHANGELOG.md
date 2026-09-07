# Changelog

All notable changes to this project are documented here.

## Versioning scheme

| Segment         | Meaning                                             | Example    |
| --------------- | --------------------------------------------------- | ---------- |
| **Major** | Architecture/API change (multi-source, DB overhaul) | v2.0       |
| **Minor** | New features, backward-compatible                   | v1.1, v1.2 |
| **Patch** | Bug fixes, UI polish, small tweaks                  | v1.0.1     |

---

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
