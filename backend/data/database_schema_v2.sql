-- Database Schema v2 – Multi-source / Multi-profile
-- Extends the v1 schema with source definitions, dynamic selectors, and download profiles.
-- All v1 tables remain unchanged; new tables are added alongside.

PRAGMA foreign_keys = ON;

-- ============================================================
-- v2 NEW TABLES
-- ============================================================

-- Sources: each represents a content website (e.g. TruyenWiki, SStruyen)
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,                   -- Display name, e.g. "TruyenWiki"
    domain TEXT NOT NULL,                        -- e.g. "wikicv.org"
    book_domain TEXT NOT NULL,                   -- e.g. "https://wikicv.org"
    base_url TEXT NOT NULL,                      -- e.g. "https://wikicv.org/truyen"
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Source selectors: CSS/XPath selectors for scraping each element type
CREATE TABLE IF NOT EXISTS source_selectors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    key TEXT NOT NULL,                           -- e.g. "book_title", "chapter_title", "chapter_content", "chapter_list_link", "author"
    selector TEXT NOT NULL,                      -- CSS or XPath selector string
    selector_type TEXT NOT NULL DEFAULT 'css',   -- "css" or "xpath"
    sort_order INTEGER DEFAULT 0,
    UNIQUE(source_id, key)
);

-- Login profiles: stored credentials + cookies per source
CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,                          -- e.g. "My Main Account", "Alt Account"
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    username TEXT DEFAULT '',
    password TEXT DEFAULT '',                     -- Stored as-is (consider encryption later)
    cookies TEXT DEFAULT '{}',                    -- JSON object: {"cookie_name": "value", ...}
    is_active INTEGER DEFAULT 0,                 -- Only one active profile per source
    login_url TEXT DEFAULT '',                    -- e.g. "https://forum.example.com/login"
    login_domain TEXT DEFAULT '',
    login_trigger_selector TEXT DEFAULT '',       -- CSS selector for the login trigger element
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name, source_id)
);

-- ============================================================
-- v1 EXTENSIONS — add FK columns to existing tables
-- ============================================================

-- Add source_id and profile_id to books (nullable for backward compat)
ALTER TABLE books ADD COLUMN source_id INTEGER REFERENCES sources(id);
ALTER TABLE books ADD COLUMN profile_id INTEGER REFERENCES profiles(id);

-- Add source_id to chapters for per-chapter source tracking (optional)
ALTER TABLE chapters ADD COLUMN source_id INTEGER REFERENCES sources(id);

-- ============================================================
-- INDEXES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_source_selectors_source ON source_selectors(source_id);
CREATE INDEX IF NOT EXISTS idx_profiles_source ON profiles(source_id);
CREATE INDEX IF NOT EXISTS idx_books_source ON books(source_id);
CREATE INDEX IF NOT EXISTS idx_books_profile ON books(profile_id);

-- ============================================================
-- SEED DATA — migrate existing TRUYENWIKI config into a default source
-- ============================================================

INSERT OR IGNORE INTO sources (id, name, domain, book_domain, base_url, notes)
VALUES (
    1,
    'TruyenWiki',
    'wikicv.org',
    'https://wikicv.org',
    'https://wikicv.org/truyen',
    'Default source (migrated from v1 config)'
);

-- Seed the selectors that the current extractor/downloader hardcodes
INSERT OR IGNORE INTO source_selectors (source_id, key, selector, selector_type) VALUES
(1, 'book_title',            'p.book-title',                          'css'),
(1, 'chapter_title',         'p.book-title',                          'css'),
(1, 'chapter_content',       'div.content-body-wrapper',              'css'),
(1, 'chapter_list_link',     'ul.list-chapters a',                    'css'),
(1, 'login_trigger',         'a[data-action="login"]',                'css'),
(1, 'username_field',        'input[name="username"], input[name="email"], input[name="login"]', 'css'),
(1, 'password_field',        'input[name="password"], input[type="password"]', 'css'),
(1, 'submit_button',         'button[type="submit"], input[type="submit"]', 'css');

-- Create a default profile if none exists (migrates v1 cookie/settings)
INSERT OR IGNORE INTO profiles (id, name, source_id, is_active, login_url, login_domain, login_trigger_selector)
SELECT
    1,
    'Default Profile',
    1,
    1,
    COALESCE((SELECT value FROM application_settings WHERE key = 'login_url'), 'https://forum.dichtienghoa.com/login'),
    COALESCE((SELECT value FROM application_settings WHERE key = 'login_domain'), 'forum.dichtienghoa.com'),
    COALESCE((SELECT value FROM application_settings WHERE key = 'login_trigger_selector'), 'a[data-action="login"]');

-- Copy existing cookies into the default profile's cookies JSON
UPDATE profiles SET
    username = COALESCE((SELECT value FROM application_settings WHERE key = 'account_username'), ''),
    password = COALESCE((SELECT value FROM application_settings WHERE key = 'account_password'), ''),
    cookies = (
        SELECT '{"' || group_concat(key, '","') || '"}'
        FROM application_settings WHERE key LIKE 'cookie_%'
    )
WHERE id = 1;

-- Point existing books to the default source
UPDATE books SET source_id = 1 WHERE source_id IS NULL;

-- ============================================================
-- TRIGGERS
-- ============================================================

CREATE TRIGGER IF NOT EXISTS update_sources_timestamp
AFTER UPDATE ON sources
BEGIN
    UPDATE sources SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_profiles_timestamp
AFTER UPDATE ON profiles
BEGIN
    UPDATE profiles SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

-- ============================================================
-- VIEWS
-- ============================================================

CREATE VIEW IF NOT EXISTS vw_books_with_source AS
SELECT
    b.*,
    s.name AS source_name,
    s.domain AS source_domain,
    p.name AS profile_name
FROM books b
LEFT JOIN sources s ON b.source_id = s.id
LEFT JOIN profiles p ON b.profile_id = p.id;
