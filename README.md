# Book Downloader App

A full-stack application to manage and download books from TruyenWiki.

## 🚀 Tech Stack
- **Backend**: Python (FastAPI)
- **Frontend**: React (Vite + Tailwind CSS)
- **Database**: SQLite
- **Automation**: Selenium + BeautifulSoup

## 📁 Project Structure
```
/
├── backend/              # FastAPI application
│   ├── app/              # Core logic
│   │   ├── services/     # Extractor and Downloader logic
│   │   ├── api/          # API Endpoints
│   │   └── database.py   # DB Manager
│   ├── data/             # Downloaded files and DB
│   └── main.py           # Entry point
├── frontend/             # React application
│   ├── src/              # Frontend source code
│   └── package.json
├── .env                  # Configuration variables
└── README.md
```

## 🛠️ Setup
1. **Backend**:
   - Navigate to `/backend`
   - Install dependencies: `pip install -r requirements.txt`
   - Run: `uvicorn main:app --reload`
2. **Frontend**:
   - Navigate to `/frontend`
   - Install dependencies: `npm install`
   - Run: `npm run dev`
