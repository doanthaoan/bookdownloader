from fastapi import APIRouter, HTTPException
from app.database import get_database
from app.config import TRUYENWIKI, COOKIE_KEYS, get_cookies
from app.services.login import auto_login
from typing import Dict

router = APIRouter()
db = get_database()

@router.get("/")
async def get_settings():
    """Fetch current configuration and cookies"""
    return {
        "truyenwiki": TRUYENWIKI,
        "cookies": get_cookies(),
        "cookie_keys": COOKIE_KEYS,
        "db_settings": db.execute_query("SELECT * FROM application_settings")
    }

@router.get("/cookies")
async def get_all_cookies():
    """Get all cookie values (merged from env + DB)"""
    return get_cookies()

@router.put("/cookies")
async def update_cookies(cookies: Dict[str, str]):
    """Batch update all cookies at once"""
    saved = []
    for name, value in cookies.items():
        if name in COOKIE_KEYS:
            db.update_setting(f"cookie_{name}", value)
            saved.append(name)
    return {"message": f"Updated {len(saved)} cookies: {', '.join(saved)}"}

@router.put("/update-cookie")
async def update_cookie(cookie_name: str, cookie_value: str):
    """Update a single cookie"""
    if cookie_name not in COOKIE_KEYS:
        raise HTTPException(status_code=400, detail=f"Unknown cookie: {cookie_name}")
    db.update_setting(f"cookie_{cookie_name}", cookie_value)
    return {"message": f"Cookie {cookie_name} updated successfully."}

@router.put("/update-setting")
async def update_setting(key: str, value: str):
    """Update a general application setting"""
    db.update_setting(key, value)
    return {"message": f"Setting {key} updated successfully."}

@router.put("/update-truyenwiki")
async def update_truyenwiki(domain: str = None, book_path: str = None, logs_path: str = None):
    """Update site configuration. Only 'domain' is required; paths use defaults."""
    if domain:
        domain = domain.strip()
        db.update_setting("domain", domain)
        derived_domain = f'https://{domain}' if not domain.startswith('http') else domain
        cookie_domain = f'.{domain.lstrip(".")}' if not domain.startswith('.') else domain
        TRUYENWIKI['book_domain'] = derived_domain
        TRUYENWIKI['cookie_domain'] = cookie_domain
    if book_path:
        db.update_setting("book_path", book_path)
        TRUYENWIKI['book_path'] = book_path
    if logs_path:
        db.update_setting("logs_path", logs_path)
        TRUYENWIKI['logs_path'] = logs_path

    return {"message": "Site configuration updated successfully."}

@router.post("/auto-login")
async def auto_login_endpoint(username: str, password: str):
    """
    Auto-login using Selenium.
    Launches a browser, fills in credentials, extracts cookies, and saves them to DB.
    """
    result = auto_login(username, password)
    print(f"Auto-login result: {result}")
    return result

@router.put("/login-config")
async def update_login_config(login_url: str = None, login_domain: str = None, trigger_selector: str = None):
    """Update the auto-login configuration (URL, domain, trigger selector)."""
    if login_url:
        db.update_setting("login_url", login_url)
    if login_domain:
        db.update_setting("login_domain", login_domain)
    if trigger_selector:
        db.update_setting("login_trigger_selector", trigger_selector)
    return {"message": "Login configuration updated successfully."}
