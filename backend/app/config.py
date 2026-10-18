"""
Site and folder configuration.

Holds hardcoded defaults for the source site (wikicv) plus helpers that read
the user's saved values from the DB `application_settings` table:
  - TRUYENWIKI: module-level dict of domain/paths, refreshed by
    load_truyenwiki_config() once at server startup (main.py). Note:
    book_dir()/logs_dir() re-read their settings from the DB on every call,
    but book_domain/cookie_domain only change after a restart.
  - get_cookies() / get_user_agent(): browser identity for Selenium sessions.
  - book_dir() / logs_dir(): the ONE place that decides where files go.

`from app.database import get_database` is done inside each function rather
than at the top: database.py is imported by many modules, and a top-level
import here could create a circular import at startup.
"""
import os
from pathlib import Path
from urllib.parse import urlparse

# Absolute path of the `backend/` folder. `__file__` is backend/app/config.py,
# so `.parent` is backend/app and `.parent.parent` is backend/.
# All relative paths stored in settings (e.g. "./data/logs") are resolved
# against this folder, so the app works no matter which directory uvicorn
# was started from.
BACKEND_DIR = Path(__file__).resolve().parent.parent

# Base default config (will be overridden from DB).
# Other modules read e.g. TRUYENWIKI['book_domain']. Because a dict is mutable,
# load_truyenwiki_config() updates it in place and every importer sees the
# new values (rebinding the name would NOT propagate to `from ... import`).
# TODO: multi-source v2 (PLAN.md) replaces this single-site global with
# per-source config.
TRUYENWIKI = {
    'book_domain': 'https://wikicv.org',
    'cookie_domain': '.wikicv.org',
    'book_path': './data',
    'logs_path': './data/logs',
}

# All known cookie keys for the site. Each is stored in the DB as a
# setting named "cookie_<key>" (see get_cookies()).
COOKIE_KEYS = [
    '_uidcms', '__uif', 'express.sid', 'rigelcdp_session_id',
    '_ga', 'FCNEC', 'FCCDCF', 'cto_bundle'
]

# Static cookies that don't change. __tr_geo is a URL-encoded JSON blob
# (%22 = ", %2C = ,) saying the visitor is in Hanoi, Vietnam.
STATIC_COOKIES = {
    '__RC': '4', '__UF': '-1', '__R': '1', '__tb': '0',
    '__tr_geo': '{%22country%22:{%22name%22:%22Vietnam%22%2C%22code%22:%22VN%22}%2C%22city%22:%22Hanoi%22}',
    'bs_onshow': '1'
}

# Adjacent string literals inside parentheses are joined into one string by
# Python at compile time — a tidy way to split a long string over lines.
USER_AGENT_DEFAULT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def normalize_domain(domain: str) -> tuple:
    """Turn whatever the user typed as the site domain into the two forms we need.

    Accepts "wikicv.org", ".wikicv.org", "https://wikicv.org" or
    "https://wikicv.org/some/path" — all give the same result.

    Args:
        domain: the raw setting value.

    Returns:
        (book_domain, cookie_domain), e.g. ("https://wikicv.org", ".wikicv.org").
        book_domain is used to build page URLs; cookie_domain (leading dot)
        makes Selenium cookies valid for the site and all its subdomains.

    Pure function (no DB, no globals), so tests/test_render.py can check it.
    """
    domain = domain.strip()
    # urlparse only finds the host when a scheme is present ("//" part), so add
    # one when the user typed a bare host name.
    url = domain if '://' in domain else f'https://{domain.lstrip(".")}'
    parsed = urlparse(url)
    # .hostname is the host only (no scheme, port or path), lower-cased.
    host = (parsed.hostname or '').lstrip('.')
    return f'{parsed.scheme}://{host}', f'.{host}'


def load_truyenwiki_config():
    """Refresh the TRUYENWIKI dict from DB settings.

    Domain priority: DB setting 'domain' -> env var DOMAIN (from optional .env)
    -> '' (keep the hardcoded default). `a or b or c` returns the first truthy
    value, so empty strings/None fall through to the next option.

    The domain may be saved as "wikicv.org" or "https://wikicv.org"; both
    produce book_domain "https://wikicv.org". cookie_domain gets a leading "."
    so the cookie is valid for all subdomains.

    Side effects: reads the DB; mutates the module-level TRUYENWIKI dict.

    Called at startup AND by the Settings API after 'domain' / 'book_path' /
    'logs_path' are saved, so a change applies without restarting the server.
    """
    from app.database import get_database
    db = get_database()

    domain = db.get_setting('domain') or os.getenv('DOMAIN') or ''
    book_path = db.get_setting('book_path') or './data'
    logs_path = db.get_setting('logs_path') or './data/logs'

    if domain.strip():
        # Tuple unpacking: normalize_domain returns two values at once.
        TRUYENWIKI['book_domain'], TRUYENWIKI['cookie_domain'] = normalize_domain(domain)
    TRUYENWIKI['book_path'] = book_path
    TRUYENWIKI['logs_path'] = logs_path


def get_cookies():
    """Build the cookie dict to inject into Selenium for the site login.

    Returns:
        dict of cookie name -> value: every non-empty "cookie_<key>" setting
        from the DB, plus STATIC_COOKIES. `dict.update()` runs last, so a
        static cookie overrides a DB value with the same name.

    Side effects: one DB read per key in COOKIE_KEYS.
    """
    from app.database import get_database
    db = get_database()
    result = {}
    for key in COOKIE_KEYS:
        val = db.get_setting(f"cookie_{key}")
        if val:
            result[key] = val
    result.update(STATIC_COOKIES)
    return result


def get_user_agent():
    """Return the browser User-Agent string.

    Returns:
        DB setting 'user_agent', or USER_AGENT_DEFAULT if unset/empty.
    """
    from app.database import get_database
    db = get_database()
    return db.get_setting('user_agent') or USER_AGENT_DEFAULT


def _resolve_dir(setting_key: str, fallback: str) -> Path:
    """Turn a path setting into an absolute folder Path and make sure it exists.

    Args:
        setting_key: key in `application_settings` (e.g. 'book_path').
        fallback: value used when the setting is empty (e.g. './data').

    Returns:
        Absolute Path. Relative values are joined onto BACKEND_DIR; absolute
        values (e.g. 'D:/Books') are used unchanged.

    Side effect: creates the folder if it is missing (`mkdir(parents=True,
    exist_ok=True)` = like `mkdir -p`, no error if it already exists).
    """
    from app.database import get_database  # imported here to avoid a circular import
    raw = get_database().get_setting(setting_key) or fallback
    path = Path(raw)
    # `Path / Path` joins paths; an absolute right-hand side wins automatically,
    # but we check explicitly to keep the intent readable.
    path = path if path.is_absolute() else BACKEND_DIR / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def book_dir() -> Path:
    """Folder where DOCX files and cover images are saved (setting 'book_path').

    Single source of truth for the book folder — every module (downloader,
    translator, extractor, API) must use this instead of building the path
    itself, so they never disagree about where files live.

    Returns:
        Absolute Path (created if missing; see _resolve_dir).
    """
    return _resolve_dir('book_path', TRUYENWIKI['book_path'])


def logs_dir() -> Path:
    """Folder for per-book success/failure log files (setting 'logs_path').

    Returns:
        Absolute Path (created if missing; see _resolve_dir).
    """
    return _resolve_dir('logs_path', TRUYENWIKI['logs_path'])
