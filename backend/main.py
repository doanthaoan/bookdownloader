"""
FastAPI application entry point.

Run with `uvicorn main:app --reload` from the backend/ folder; uvicorn imports
this module and serves the `app` object on 127.0.0.1:8000.

This file only wires things together:
  - CORS so the React dev server (a different origin/port) may call the API.
  - Every router from app/api/*.py, each mounted under its URL prefix. The
    route decorators inside those files omit the prefix, so "/api/books" etc.
    is declared ONLY here.
  - Startup/shutdown hooks: load site config from the DB, and stop background
    download/translate threads when the server exits.
"""
from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from app.api.books import router as books_router
from app.api.settings import router as settings_router
from app.api.logs import router as logs_router
from app.api.text_cleaning import router as text_cleaning_router
from app.api.translate import router as translate_router
from app.api.stats import router as stats_router
from app.config import load_truyenwiki_config
from app.services.downloader import cancel_all_downloads
from app.services.translator import cancel_all_translations

# The ASGI application object that uvicorn serves. `title` shows up in the
# auto-generated docs at /docs.
app = FastAPI(title="Book Downloader API")

# CORS middleware to allow React frontend to communicate with FastAPI.
# Browsers block cross-origin requests unless the server sends CORS headers;
# the frontend runs on Vite's port, so it is a different origin.
# "*" = allow everything. Fine for a local single-user tool.
# TODO: restrict allow_origins to the Vite dev URL if this is ever exposed beyond localhost.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount each router under its prefix. `tags` only groups endpoints in /docs.
app.include_router(books_router, prefix="/api/books", tags=["Books"])
app.include_router(settings_router, prefix="/api/settings", tags=["Settings"])
app.include_router(logs_router, prefix="/api/logs", tags=["Logs"])
app.include_router(text_cleaning_router, prefix="/api/text-cleaning", tags=["Text Cleaning"])
app.include_router(translate_router, prefix="/api/translate", tags=["Translate"])
app.include_router(stats_router, prefix="/api/stats", tags=["Stats"])

# TODO: `@app.on_event` is deprecated in recent FastAPI; migrate to a `lifespan`
# async context manager passed to FastAPI(lifespan=...).
@app.on_event("startup")
async def startup():
    """Run once when the server starts.

    Reads the site domain and folder settings from the DB into the global
    `TRUYENWIKI` dict (see app/config.py) so services use the saved values
    instead of the hardcoded defaults.

    Side effects: reads the DB; mutates the module-level TRUYENWIKI dict.
    """
    load_truyenwiki_config()
    print("TRUYENWIKI config loaded from DB")

@app.on_event("shutdown")
async def shutdown():
    """Run once when the server stops (Ctrl+C or a --reload restart).

    Signals every background download/translate thread to cancel, so their
    Selenium Chrome windows are closed instead of being left orphaned.

    Side effects: sets cancel flags on active jobs (threads then quit Chrome).
    """
    print("Shutting down — cancelling all active downloads...")
    cancel_all_downloads()
    cancel_all_translations()

@app.get("/")
async def root():
    """Health check: GET / returns a fixed message so you can see the API is up.

    Returns:
        dict, which FastAPI serializes to JSON automatically.
    """
    return {"message": "Book Downloader API is running"}
