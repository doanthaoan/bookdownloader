# AGENTS.md

Two independent apps in one repo: `backend/` (FastAPI + Selenium + SQLite) and `frontend/` (React 19 + Vite + Tailwind). Developed/run on Windows.

## Commands

There are no tests. Verification = compile-check backend + build frontend:

```powershell
# backend (run from backend/)
python -m py_compile app/api/<file>.py app/services/<file>.py
uvicorn main:app --reload            # dev server on 127.0.0.1:8000

# frontend (run from frontend/)
npm run build                        # tsc && vite build — catches syntax/import errors
```

- `npm run build` is the only frontend check: sources are plain `.jsx` (`allowJs`, `checkJs: false`), so tsc validates almost nothing but vite fails on real errors.
- Backend deps: `pip install -r requirements.txt`. `.env` is optional (only `DOMAIN` fallback).

## Architecture invariants

The DB is the source of truth; DOCX files are always derived at render time. Never persist corrections or global-cleaning output into chapter content. Details in the `app/services/docx_exporter.py` module docstring:

- Downloaded books: `chapters.chapter_content` stores globally-cleaned text as `<p>` paragraphs joined by `\n\n`. Render applies only per-book corrections.
- Translated books: `translated_content` stores raw translation as `<viet_title>\n<viet_body>`. Global Text Cleaning rules AND per-book corrections are applied only at render (idempotent).
- Per-book find/replace rules live in `book_corrections`; global regex rules live in DB settings tables. Both are applied via `build_render_rules()` → `apply_paragraphs()` / `apply_rules()`.
- Blank-line normalization (`collapse_blank_lines`) happens both at download-save time and in every render path.

## Backend gotchas

- Router prefixes are declared in `main.py` (`/api/books`, `/api/translate`, `/api/settings`, `/api/logs`, `/api/text-cleaning`, `/api/stats`); route decorators inside `app/api/*.py` omit them.
- Downloads/translates run in background threads, tracked per book in `_active_downloads`. One active job per book: `register_download()` returns `False` if already running; API endpoints return **409** when a download is active.
- Schema changes go through idempotent migrations in `app/database.py` (`_run_migrations`, `ALTER TABLE ... ADD COLUMN` wrapped in try/except), not by editing `data/database_schema*.sql`.
- `db.get_chapter()` does NOT exist. For ad-hoc queries use `db._get_connection()` with `conn.row_factory = sqlite3.Row`.

## Live data warning

`backend/data/novel_downloader.db` (+ `-wal`/`-shm`) contains real books/chapters. Smoke tests that call write endpoints mutate it — back up affected rows first and restore after (see `set_book_corrections` round-trip pattern).

## Frontend gotchas

- The API base URL is hardcoded to `http://127.0.0.1:8000/api` in `src/api/index.js` (no Vite proxy, no env var) — port changes require editing this file. All endpoints are wrapped there; pages never call axios directly.
- `BookDetails.jsx` polls progress; writes made while its Corrections modal is open must update local state from the response or polling will clobber them.

## Conventions

- Add a `CHANGELOG.md` entry for every feature/fix: minor bump = feature, patch = fix/tweak (scheme table at top of file).
- Commit messages summarize multiple features in one line; recent history uses squash merges from short-lived branches.
