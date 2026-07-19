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
- [x] Final testing and cleanup.

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

## Future Considerations (v3)

- **Encrypted password storage** in profiles.
- **Proxy support** per source/profile.
- **Headless mode toggle** per source.
- **Export/import** source+profile config as JSON.
- **Webhook notifications** on download completion.

## Known Issues

- **SQLite transaction error on concurrent writes**: When multiple background tasks (extract + download) hit the DB simultaneously, SQLite may throw `cannot commit - no transaction is active`. **Fix applied**: thread-local connections via `threading.local()` so each thread gets its own connection. If it reappears, consider switching to a queue-based write pattern or using a proper connection pool.
