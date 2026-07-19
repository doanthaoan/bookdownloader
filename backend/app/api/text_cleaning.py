from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
import os
import random
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
from docx import Document
from app.database import get_database
from app.config import TRUYENWIKI, get_cookies
from app.services.text_cleaner import TextCleaner

router = APIRouter()
db = get_database()

TEST_OUTPUT = "./data/downloads/truyen"


@router.get("/")
def list_rules():
    return db.get_text_cleaning_rules(enabled_only=False)


@router.post("/")
def add_rule(rule_type: str, match_type: str, find_text: str,
             replace_text: str = '', enabled: int = 1,
             sort_order: int = None, description: str = ''):
    rule_id = db.add_text_cleaning_rule(
        rule_type=rule_type, match_type=match_type,
        find_text=find_text, replace_text=replace_text,
        enabled=enabled, sort_order=sort_order, description=description
    )
    return {"id": rule_id, "message": "Rule added"}


@router.put("/{rule_id}")
def update_rule(rule_id: int, rule_type: str = None, match_type: str = None,
                find_text: str = None, replace_text: str = None,
                enabled: int = None, sort_order: int = None, description: str = None):
    kwargs = {k: v for k, v in locals().items() if k != 'rule_id' and v is not None}
    ok = db.update_text_cleaning_rule(rule_id, **kwargs)
    if not ok:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"message": "Rule updated"}


@router.put("/{rule_id}/reorder")
def reorder_rule(rule_id: int, new_order: int):
    db.reorder_text_cleaning_rule(rule_id, new_order)
    return {"message": "Rule reordered"}


@router.delete("/{rule_id}")
def delete_rule(rule_id: int):
    db.delete_text_cleaning_rule(rule_id)
    return {"message": "Rule deleted"}


@router.post("/test")
def test_cleaning(chapter_url: str):
    """
    Fetch a chapter URL synchronously, apply all enabled cleaning rules,
    and save as test.docx. Uses a unique filename per run so new rules
    always produce a fresh file.
    """
    import time as time_mod
    ts = int(time_mod.time())
    filename = f"test_{ts}.docx"
    output_path = Path(__file__).parent.parent.parent / TEST_OUTPUT
    os.makedirs(output_path, exist_ok=True)
    test_docx = output_path / filename

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=chrome_options
    )
    try:
        driver.get(TRUYENWIKI['book_domain'])
        cookie_map = get_cookies()
        for name, value in cookie_map.items():
            if value:
                try:
                    driver.add_cookie({'name': name, 'value': value, 'domain': TRUYENWIKI['cookie_domain']})
                except Exception:
                    pass

        full_url = chapter_url if chapter_url.startswith("http") else TRUYENWIKI['book_domain'] + chapter_url
        driver.get(full_url)
        wait = WebDriverWait(driver, 15)
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "content-body-wrapper")))
        time.sleep(random.randint(2, 3))

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        content_tag = soup.find('div', {'class': 'content-body-wrapper'})
        if not content_tag:
            raise HTTPException(status_code=500, detail="Could not find content-body-wrapper")

        cleaner = TextCleaner()
        doc = Document()
        for p in content_tag.find_all('p'):
            cleaned = cleaner.clean(p.get_text())
            if cleaned:
                doc.add_paragraph(cleaned)
        doc.save(str(test_docx.resolve()))
        print(f"✅ Test DOCX saved to {test_docx}")

    finally:
        driver.quit()

    return {
        "message": "Test complete",
        "filename": filename,
        "download_url": f"/api/text-cleaning/test/{filename}"
    }


@router.get("/test/{filename}")
def get_test_docx(filename: str):
    # Guard against path traversal
    if '/' in filename or '\\' in filename or not filename.startswith('test_'):
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = Path(__file__).parent.parent.parent / TEST_OUTPUT / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Test file not found. Run a test first.")
    return FileResponse(
        path=str(path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
