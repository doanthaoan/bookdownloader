# Book Downloader

A personal, local-only web app that saves web novels as DOCX files for offline reading.

- **Download**: paste a book URL (TruyenWiki / wikicv). The app scrapes the book info and chapter list, downloads the chapters with Selenium, and stores the cleaned text in SQLite.
- **Translate**: import a raw Chinese TXT novel. The app splits it into chapters and translates them to Vietnamese (dichtienghoa API, with a browser fallback).
- **Export**: DOCX files are always rendered from the database. Global Text Cleaning rules and per-book corrections (find → replace) are applied at render time, so you can fix names and re-export at any time.
- **Extras**: tags, favorites, an "updates" check for ongoing books, re-download (failed, first N chapters, or a range), request statistics with daily limits, and a log viewer.

## Tech stack
- **Backend**: Python 3.13, FastAPI, Selenium + BeautifulSoup, python-docx, SQLite (`backend/`)
- **Frontend**: React 19, Vite, Tailwind CSS (`frontend/`)

## Setup (Windows)

```powershell
# Backend: always use the project venv
cd backend
C:\laragon\bin\python\python-3.13\python.exe -m venv .venv   # first time only
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload        # http://127.0.0.1:8000  (API docs: /docs)

# Frontend
cd frontend
npm install
npm run dev                      # http://localhost:5173
```

Google Chrome must be installed. The matching chromedriver is downloaded automatically.

## Project docs
- [AGENTS.md](AGENTS.md): architecture invariants, commands, gotchas, and the code-comment rules
- [PLAN.md](PLAN.md): refactor plan and future features
- [CHANGELOG.md](CHANGELOG.md): version history
- [CLAUDE.md](CLAUDE.md): code map and notes for Claude Code

## Data (not in git)
`backend/data/` holds the database (`novel_downloader.db`), downloaded DOCX files and covers (`downloads/truyen/`), per-book logs (`logs/`), and raw TXT files for translation (`translate_src/`).
