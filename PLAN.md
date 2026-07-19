# Development Plan - Book Downloader App

## Goal
Convert a collection of Python scripts into a managed web application with a React frontend and FastAPI backend.

## Phase 1: Infrastructure & Backend (Current)
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
- [ ] Search/filter book list + pagination.
- [ ] Real-time download progress.
- [ ] Final testing and cleanup.

## Known Issues
- **SQLite transaction error on concurrent writes**: When multiple background tasks (extract + download) hit the DB simultaneously, SQLite may throw `cannot commit - no transaction is active`. **Fix applied**: thread-local connections via `threading.local()` so each thread gets its own connection. If it reappears, consider switching to a queue-based write pattern or using a proper connection pool.
