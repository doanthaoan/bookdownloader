# Development Plan - Book Downloader App

## Goal
Convert a collection of Python scripts into a managed web application with a React frontend and FastAPI backend.

## Phase 1: Infrastructure & Backend
- [x] Define folder structure and documentation.
- [x] Initialize FastAPI project.
- [x] Refactor `db_manager.py` into a service layer.
- [x] Move existing logic from `chapter_extractor.py` and `wikicv_docx_db.py` into FastAPI services.
- [x] Fix file storage paths (removing deep nested directories).
- [x] Implement REST endpoints:
    - Books: List, Create (Extract), Update Status, Delete.
    - Chapters: List by book, Update status.
    - Settings: Get/Set configuration.
- [x] Implement background tasks for long-running downloads.

## Phase 2: Frontend Development
- [x] Setup React with Vite and Tailwind CSS.
- [x] Build Dashboard (Book list + overall progress).
- [x] Build Book Details page (Chapter management).
- [x] Build Extraction page (URL input).
- [x] Build Settings page (Env variables & Cookies).
- [x] Integrate with Backend API using Axios.

## Phase 3: Polish & Advanced Features
- [x] Implement a "Cookie Auto-fetcher" (User/Pass -> Selenium login -> Save cookies).
- [x] Add detailed logs view in the UI.
- [x] Improve "Resume/Redownload" granularity.
- [x] Search/filter book list + pagination.
- [x] Real-time download progress.
- [x] Re-download All / per-chapter retry + `_redownload.docx`.
- [x] Add book title heading in DOCX output.
- [x] Updates page — check all ongoing books for new chapters.
- [x] Continue Extract — append new chapters without re-extracting everything.
- [x] Update & Download — one-click re-scrape → extract new → download new.
- [x] Relative URLs everywhere — domain-independent chapter storage for portability.
- [x] User-configurable global text cleaning rules (remove/replace, simple/regex, reorderable, enabled toggle).
- [x] Test cleaning rules — fetch a chapter URL synchronously, apply rules, download result.
- [x] Final testing and cleanup.

---

# Version 1.1 — Quality-of-Life Features

## Goal
Add user-facing enhancements to the book list, DOCX output, and settings UI, plus fix accumulated bugs.

## Changes (v1.0 → v1.1)

### Application Settings
- [x] Created `get_user_agent()` shared helper — all Selenium entry points (downloader, extractor, login, text_cleaning) read `user_agent` from DB.
- [x] Removed `ENV_COOKIES` and `dotenv` dependency from `config.py` — cookies come strictly from DB now.
- [x] Removed orphaned `SAVE_INTERVAL` module constant from `downloader.py`.
- [x] Frontend Settings page: **Download Settings** subsection (delays, timeout, save interval) with descriptions.
- [x] Frontend Settings page: **Browser Settings** subsection with User Agent dropdown (6 presets + Custom).

### Book Management
- [x] Added `is_favorite` and `is_sent` columns to books table (with auto-migration).
- [x] Backend: `toggle-favorite` and `toggle-sent` endpoints + `GET /books` sorts favorites first.
- [x] Frontend: **Favorite star (★)** toggle in Book List and Book Details — favorites display on top.
- [x] Frontend: **Sent checkmark (✓)** toggle with visual indicator — filterable in Book List (All/Sent/Not sent).

### Book Cover & Description
- [x] Added `cover_image_url` and `short_description` columns to books table (with auto-migration).
- [x] Extractor now scrapes cover image URL from `div.cover-wrapper img` and short description from `div.book-desc-detail`.
- [x] Cover image downloaded to book directory on extraction, served via `GET /api/books/{id}/cover`.
- [x] Book List: small cover thumbnail before title.
- [x] Book Details: larger cover image on the left, short description in an accordion below.
- [x] DOCX: cover image added to first page (centered, 3.5in wide).

### DOCX Output
- [x] Author line (`Tác giả: **[name]**`) added after book title, italic with bold author name.
- [x] Cover image added to first page of DOCX (centered, below author line).

### Bug Fixes
- [x] `downloaded_chapters` count now cumulative (pre-existing + session) instead of session-only.
- [x] Progress bar total now shows **remaining chapters in current session**, not total book chapters.
- [x] Progress text reads `"chapter X of Y in this session"` for clarity.

### UI Polish
- [x] Book List: action buttons replaced with icons (📋 ⬇ ⏳) to save column space.
- [x] Book List: title and author columns truncated with full text on hover (`title` attribute).
- [x] Fixed column widths with `w-*` classes for a tighter, consistent layout.
- [x] Sent filter dropdown (All / Sent / Not sent) in Book List filter bar.

### Planned (v1.2)
- [ ] **Google Profile Login** — launch visible Chrome with user's profile for interactive Google OAuth login. Hybrid auto-detect + manual Stop button. Full plan at `.opencode/plans/profile-login-implementation.md`.

---

# Version 2 — Multi-source & Multi-profile

## Goal
Extend the app to support multiple content sources (websites), each with its own:
- Domain configuration
- CSS/XPath selectors for scraping
- Login profiles (credentials + cookies)

## Migration: v1 → v2 Schema

A migration script (`backend/data/database_schema_v2.sql`) adds three new tables:

| Table | Purpose |
|---|---|
| `sources` | Each content website (domain, base URL) |
| `source_selectors` | Per-source CSS/XPath selectors for extraction |
| `profiles` | Login credentials + cookies, linked to a source |

Existing `books` and `chapters` tables get nullable `source_id` / `profile_id` columns.
A default "TruyenWiki" source + profile is seeded, and existing books are linked to it.

## Phase 4: Backend Refactor (v2)

- [ ] **Database layer**: create `SourceManager`, `ProfileManager` classes.
- [ ] **Remove `config.py` globals**: replace `TRUYENWIKI` with `SourceManager` that loads from DB.
- [ ] **Refactor `extractor.py`**: accept selector set from `source_selectors` instead of hardcoded class names.
- [ ] **Refactor `downloader.py`**: accept `profile_id` to load the right cookies; accept `source_id` for domain + selectors.
- [ ] **Refactor `login.py`**: accept profile config (login URL, trigger selector) from the `profiles` table.
- [ ] **New API endpoints**:
    - `GET/POST/PUT/DELETE /api/sources`
    - `GET/POST/PUT/DELETE /api/sources/{id}/selectors`
    - `GET/POST/PUT/DELETE /api/profiles`
    - `PUT /api/books/{id}/source` — reassign book to a source
    - `PUT /api/books/{id}/profile` — reassign book to a profile
- [ ] **Migration script** that runs automatically on startup to apply v2 schema.

## Phase 5: Frontend (v2)

- [ ] **Sources page** — CRUD for sources, assign selectors per element type.
- [ ] **Profiles page** — CRUD for login profiles, cookie editor per profile.
- [ ] **Extraction form** — add source/profile dropdowns.
- [ ] **Book List / Details** — show which source/profile a book belongs to.
- [ ] **Settings page** — slim down to only general settings; source/profile config moved to new pages.

## Phase 6: Per-Book Text Cleaning Rules

- [ ] **Database layer**: `book_cleaning_rules` junction table linking rules to books, or add a `scope` (global/book) + `book_id` column to `text_cleaning_rules`.
- [ ] **Override strategy**: decide whether per-book rules run *in addition to* global rules, or replace them.
- [ ] **Backend**: `TextCleaner.clean(text, book_id=None)` loads book-scoped rules when a book_id is given.
- [ ] **Frontend**: per-book rule management on Book Details page, or a book selector on the Text Cleaning page.

## Future Considerations (v3+)

- **Encrypted password storage** in profiles.
- **Proxy support** per source/profile.
- **Headless mode toggle** per source.
- **Export/import** source+profile config as JSON.
- **Webhook notifications** on download completion.

## Known Issues

- **SQLite transaction error on concurrent writes**: When multiple background tasks (extract + download) hit the DB simultaneously, SQLite may throw `cannot commit - no transaction is active`. **Fix applied**: thread-local connections via `threading.local()` so each thread gets its own connection. If it reappears, consider switching to a queue-based write pattern or using a proper connection pool.
