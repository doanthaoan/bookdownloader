import os
from dotenv import load_dotenv

load_dotenv()

# Base default config (will be overridden from DB)
TRUYENWIKI = {
    'book_domain': 'https://wikicv.org',
    'cookie_domain': '.wikicv.org',
    'book_path': './data',
    'logs_path': './data/logs',
}

# All known cookie keys for the site
COOKIE_KEYS = [
    '_uidcms', '__uif', 'express.sid', 'rigelcdp_session_id',
    '_ga', 'FCNEC', 'FCCDCF', 'cto_bundle'
]

# Static cookies that don't change
STATIC_COOKIES = {
    '__RC': '4', '__UF': '-1', '__R': '1', '__tb': '0',
    '__tr_geo': '{%22country%22:{%22name%22:%22Vietnam%22%2C%22code%22:%22VN%22}%2C%22city%22:%22Hanoi%22}',
    'bs_onshow': '1'
}

# Env fallback defaults
ENV_COOKIES = {key: os.getenv(key.upper()) for key in COOKIE_KEYS}


def load_truyenwiki_config():
    """Load TRUYENWIKI config from DB, with env fallback."""
    from app.database import get_database
    db = get_database()

    domain = db.get_setting('domain') or os.getenv('DOMAIN') or ''
    book_path = db.get_setting('book_path') or './data'
    logs_path = db.get_setting('logs_path') or './data/logs'

    if domain:
        domain = domain.strip()
        if not domain.startswith('http'):
            TRUYENWIKI['book_domain'] = f'https://{domain}'
        else:
            TRUYENWIKI['book_domain'] = domain
        TRUYENWIKI['cookie_domain'] = f'.{domain.lstrip(".")}' if not domain.startswith('.') else domain
    TRUYENWIKI['book_path'] = book_path
    TRUYENWIKI['logs_path'] = logs_path


def get_cookies():
    """
    Get all cookies from DB with env fallback.
    Returns a combined dict of dynamic + static cookies.
    """
    from app.database import get_database
    db = get_database()
    result = {}
    for key in COOKIE_KEYS:
        val = db.get_setting(f"cookie_{key}") or ENV_COOKIES.get(key)
        if val:
            result[key] = val
    result.update(STATIC_COOKIES)
    return result
