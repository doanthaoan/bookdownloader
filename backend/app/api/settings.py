"""Settings API: site configuration, login cookies, generic key/value settings
and Selenium auto-login.

Mounted in main.py under the prefix ``/api/settings``, so ``@router.get("/")``
here is really ``GET /api/settings/``.

All endpoints are plain ``def`` on purpose: FastAPI runs them in a thread pool,
so blocking work (sqlite writes, and /auto-login which drives a real Chrome via
Selenium for many seconds) does not freeze the asyncio event loop.

Parameter style: scalar params (``key: str``) with no ``Body(...)`` are read
from the URL query string (e.g. ``PUT /update-setting?key=a&value=b``). A dict
param such as ``cookies: Dict[str, str]`` is read from the JSON request body.
"""
from fastapi import APIRouter, HTTPException
from app.database import get_database
from app.config import TRUYENWIKI, COOKIE_KEYS, get_cookies, load_truyenwiki_config
from app.services.login import auto_login
import json
from typing import Dict

router = APIRouter()

# Settings that feed the in-memory TRUYENWIKI dict (see config.load_truyenwiki_config).
SITE_CONFIG_KEYS = {"domain", "book_path", "logs_path"}
db = get_database()


@router.get("/")
def get_settings():
    """GET /api/settings/ -- fetch the current configuration and cookies.

    Response:
        ``{"truyenwiki": {site config dict}, "cookies": {name: value},
        "cookie_keys": [allowed cookie names], "db_settings": [rows of application_settings]}``

    Read-only.
    """
    # TODO: this returns secrets (session cookies, and any stored password) to the
    # UI in plain text. Mask values (e.g. "abc…xyz") and only send them when asked.
    return {
        "truyenwiki": TRUYENWIKI,
        "cookies": get_cookies(),
        "cookie_keys": COOKIE_KEYS,
        "db_settings": db.execute_query("SELECT * FROM application_settings")
    }


@router.get("/cookies")
def get_all_cookies():
    """GET /api/settings/cookies -- all cookie values (merged from env + DB).

    Response: ``{cookie_name: value, ...}``. Same secret-exposure caveat as
    get_settings (see TODO there).
    """
    return get_cookies()


@router.put("/cookies")
def update_cookies(cookies: Dict[str, str]):
    """PUT /api/settings/cookies -- batch update cookies at once.

    Body (JSON object): ``{"cookie_name": "value", ...}``. Because the parameter
    type is a dict, FastAPI reads it from the request body, not the query string.

    Names not listed in COOKIE_KEYS are silently ignored (allow-list), so a
    client cannot write arbitrary settings through this endpoint.

    Response: ``{"message": "Updated N cookies: a, b"}``.
    Side effect: writes ``cookie_<name>`` rows in the settings table.
    """
    saved = []
    # .items() yields (key, value) pairs; tuple-unpacked into name, value.
    for name, value in cookies.items():
        if name in COOKIE_KEYS:
            db.update_setting(f"cookie_{name}", value)
            saved.append(name)
    return {"message": f"Updated {len(saved)} cookies: {', '.join(saved)}"}


@router.put("/update-cookie")
def update_cookie(cookie_name: str, cookie_value: str):
    """PUT /api/settings/update-cookie?cookie_name=..&cookie_value=.. -- update one cookie.

    Errors: 400 if cookie_name is not in COOKIE_KEYS.
    Side effect: writes the ``cookie_<name>`` setting.
    """
    if cookie_name not in COOKIE_KEYS:
        raise HTTPException(status_code=400, detail=f"Unknown cookie: {cookie_name}")
    db.update_setting(f"cookie_{cookie_name}", cookie_value)
    return {"message": f"Cookie {cookie_name} updated successfully."}


@router.put("/update-setting")
def update_setting(key: str, value: str):
    """PUT /api/settings/update-setting?key=..&value=.. -- set any application setting.

    Generic key/value write used by many UI pages (translate options, chapter
    limits, ...). No allow-list: any key is accepted.
    Side effects: upserts one row in the settings table; for the site keys
    (domain / book_path / logs_path) also refreshes the in-memory TRUYENWIKI
    config, so the change applies without restarting the server.
    """
    db.update_setting(key, value)
    if key in SITE_CONFIG_KEYS:
        load_truyenwiki_config()
    return {"message": f"Setting {key} updated successfully."}


@router.put("/update-truyenwiki")
def update_truyenwiki(domain: str = None, book_path: str = None, logs_path: str = None):
    """Update site configuration. Only 'domain' is required; paths use defaults.

    PUT /api/settings/update-truyenwiki?domain=..&book_path=..&logs_path=..
    (each query param is optional; only the ones given are changed).

    Side effects:
      * persists each given value in the settings table, AND
      * reloads the in-memory ``TRUYENWIKI`` dict (load_truyenwiki_config) so
        the change takes effect immediately without restarting the server.

    Why mutating works: ``TRUYENWIKI`` is one dict object shared by every module
    that imported it, so changing its keys in place is visible everywhere.
    (Reassigning ``TRUYENWIKI = {...}`` here would NOT be.)
    """
    # locals() trick avoided on purpose: an explicit dict is easier to read.
    # Only the values that were actually sent (truthy) are saved.
    for key, value in {"domain": domain, "book_path": book_path, "logs_path": logs_path}.items():
        if value:
            db.update_setting(key, value.strip())
    # Rebuild TRUYENWIKI from the DB with the same code as at startup
    # (config.normalize_domain), so the two paths can never disagree.
    load_truyenwiki_config()

    return {"message": "Site configuration updated successfully."}


@router.post("/auto-login")
def auto_login_endpoint(username: str, password: str):
    """
    Auto-login using Selenium.
    Launches a browser, fills in credentials, extracts cookies, and saves them to DB.

    POST /api/settings/auto-login?username=..&password=..

    Response: the result dict from ``auto_login`` (success flag, message, cookies).
    Side effects: OPENS CHROME (blocks this request for the whole login flow),
    writes cookie settings to the DB.
    """
    # TODO: the password travels in the URL query string, which ends up in server
    # access logs and browser history. Accept it in a JSON body (pydantic model) instead.
    result = auto_login(username, password)
    # TODO: this print may dump fresh session cookies into the console log.
    print(f"Auto-login result: {result}")
    return result


@router.put("/login-config")
def update_login_config(login_url: str = None, login_domain: str = None, trigger_selector: str = None):
    """Update the auto-login configuration (URL, domain, trigger selector).

    PUT /api/settings/login-config?login_url=..&login_domain=..&trigger_selector=..
    Each query param is optional; empty/missing ones are left unchanged
    (so this endpoint cannot clear a value).
    trigger_selector: CSS selector of the element that opens the login form.
    Side effect: writes the corresponding settings rows.
    """
    if login_url:
        db.update_setting("login_url", login_url)
    if login_domain:
        db.update_setting("login_domain", login_domain)
    if trigger_selector:
        db.update_setting("login_trigger_selector", trigger_selector)
    return {"message": "Login configuration updated successfully."}


# ---------------------------------------------------------------------------
# Extra site accounts (fallbacks when the site's access limit is reached)
# ---------------------------------------------------------------------------

@router.get("/accounts")
def list_accounts():
    """GET /api/settings/accounts -- list the extra site accounts.

    Response: ``[{"id", "username", "cookie_count", "created_at"}, ...]``.
    Passwords and cookie values are NOT returned (only how many cookies are
    stored, so the UI can show whether the account is logged in).
    """
    return [
        {"id": a["id"], "username": a["username"], "created_at": a["created_at"],
         # json.loads(...) parses the stored JSON text back into a dict.
         "cookie_count": len(json.loads(a["cookies"] or "{}"))}
        for a in db.get_site_accounts()
    ]


@router.post("/accounts")
def add_account(account: Dict[str, str]):
    """POST /api/settings/accounts -- add an extra account (not logged in yet).

    Body (JSON): ``{"username": "...", "password": "..."}`` — a JSON body, so
    the password does not end up in the URL / access logs.
    Errors: 400 if username or password is missing.
    Side effect: INSERT into site_accounts.
    """
    username = (account.get("username") or "").strip()
    password = account.get("password") or ""
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required.")
    # TODO: the password is stored in plaintext, like account_password (PLAN.md Phase 3).
    return {"id": db.add_site_account(username, password)}


@router.delete("/accounts/{account_id}")
def delete_account(account_id: int):
    """DELETE /api/settings/accounts/{id} -- remove an extra account. 404 if missing."""
    if not db.delete_site_account(account_id):
        raise HTTPException(status_code=404, detail="Account not found.")
    return {"message": "Account deleted."}


@router.post("/accounts/{account_id}/login")
def login_account(account_id: int):
    """POST /api/settings/accounts/{id}/login -- auto-login with the stored credentials.

    Response: the result dict from ``auto_login``.
    Side effects: OPENS CHROME (blocks this request for the whole login flow),
    writes the harvested cookies into ``site_accounts.cookies``.
    Errors: 404 if the account does not exist.
    """
    # next(generator, None) = first matching row, or None.
    account = next((a for a in db.get_site_accounts() if a["id"] == account_id), None)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found.")
    return auto_login(account["username"], account["password"], account_id=account_id)
