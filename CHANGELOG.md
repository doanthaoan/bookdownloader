# Changelog

All notable changes to this project are documented here.

## Versioning scheme

| Segment         | Meaning                                             | Example    |
| --------------- | --------------------------------------------------- | ---------- |
| **Major** | Architecture/API change (multi-source, DB overhaul) | v2.0       |
| **Minor** | New features, backward-compatible                   | v1.1, v1.2 |
| **Patch** | Bug fixes, UI polish, small tweaks                  | v1.0.1     |

---

## [1.1.1] — 2026-08-04

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
