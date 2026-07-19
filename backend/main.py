from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from app.api.books import router as books_router
from app.api.settings import router as settings_router
from app.api.logs import router as logs_router
from app.api.text_cleaning import router as text_cleaning_router
from app.config import load_truyenwiki_config
from app.services.downloader import cancel_all_downloads

app = FastAPI(title="Book Downloader API")

# CORS middleware to allow React frontend to communicate with FastAPI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(books_router, prefix="/api/books", tags=["Books"])
app.include_router(settings_router, prefix="/api/settings", tags=["Settings"])
app.include_router(logs_router, prefix="/api/logs", tags=["Logs"])
app.include_router(text_cleaning_router, prefix="/api/text-cleaning", tags=["Text Cleaning"])

@app.on_event("startup")
async def startup():
    load_truyenwiki_config()
    print("TRUYENWIKI config loaded from DB")

@app.on_event("shutdown")
async def shutdown():
    print("Shutting down — cancelling all active downloads...")
    cancel_all_downloads()

@app.get("/")
async def root():
    return {"message": "Book Downloader API is running"}
