-- Database Schema for Vietnamese Novel Download Tool
-- SQLite database schema replacing Excel file management

PRAGMA foreign_keys = ON;

-- Books table stores metadata about each novel
CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stt TEXT,                    -- Original serial number from Excel
    title TEXT NOT NULL,                  -- Full book title
    seo_title_basic TEXT,                 -- Basic SEO title (unidecode, lowercase)
    seo_title_full TEXT NOT NULL UNIQUE,  -- Full SEO title with STT and .html
    book_status TEXT DEFAULT 'planning',  -- planning, active, completed, on_hold
    download_status TEXT DEFAULT 'pending',  -- pending, in_progress, completed, failed
    book_url TEXT,                        -- URL to book's main page on website
    author TEXT,                          -- Author name from book info page
    book_web_status TEXT,                 -- Web status: Hoàn thành, Còn tiếp, Tạm Ngưng, Chưa xác minh
    last_chapter_url TEXT,                -- URL of the latest chapter from book info page
    last_chapter_title TEXT,              -- Title of the latest chapter
    last_update_date TEXT,                -- Last update date string from book info page
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_accessed TIMESTAMP,
    total_chapters INTEGER DEFAULT 0,
    downloaded_chapters INTEGER DEFAULT 0,
    notes TEXT                            -- For any additional information
);

-- Chapters table tracks individual chapter download status
CREATE TABLE IF NOT EXISTS chapters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL,
    chapter_order INTEGER NOT NULL,       -- Order within the book (1, 2, 3...)
    chapter_title TEXT NOT NULL,          -- Title of the chapter
    chapter_url TEXT NOT NULL,            -- URL to access the chapter
    download_status TEXT DEFAULT 'pending',  -- pending, in_progress, completed, failed
    downloaded_at TIMESTAMP,
    retry_count INTEGER DEFAULT 0,
    file_path TEXT,                       -- Relative path to saved files
    error_message TEXT,                   -- Error details if download failed
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (book_id) REFERENCES books (id) ON DELETE CASCADE,
    UNIQUE(book_id, chapter_url)          -- Prevent duplicate chapters per book
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_books_status ON books(download_status);
CREATE INDEX IF NOT EXISTS idx_books_url ON books(book_url);
CREATE INDEX IF NOT EXISTS idx_chapters_book_id ON chapters(book_id);
CREATE INDEX IF NOT EXISTS idx_chapters_status ON chapters(download_status);
CREATE INDEX IF NOT EXISTS idx_chapters_order ON chapters(book_id, chapter_order);

-- Settings table for application configuration
CREATE TABLE IF NOT EXISTS application_settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Initial data for application settings
INSERT OR IGNORE INTO application_settings (key, value, description) VALUES
('download_delay_min', '4', 'Minimum delay between chapter downloads (seconds)'),
('download_delay_max', '6', 'Maximum delay between chapter downloads (seconds)'),
('save_interval', '10', 'Save DOCX file every N successful chapters'),
('page_load_timeout', '15', 'Seconds to wait for page to load'),
('user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36', 'User agent string for web requests'),
('account_username', '', 'Account username for auto-login'),
('account_password', '', 'Account password for auto-login'),
('login_url', 'https://forum.dichtienghoa.com/login', 'Login form submission URL'),
('login_domain', 'forum.dichtienghoa.com', 'Login page domain'),
('login_trigger_selector', 'a[data-action="login"]', 'CSS selector for the login trigger element on homepage'),
('domain', 'wikicv.org', 'Main site domain (e.g., wikicv.org)'),
('book_path', './data', 'Directory to save downloaded DOCX files'),
('logs_path', './data/logs', 'Directory to save log files');

-- Trigger to automatically update updated_at timestamp
CREATE TRIGGER IF NOT EXISTS update_books_timestamp 
AFTER UPDATE ON books
BEGIN
    UPDATE books SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_chapters_timestamp 
AFTER UPDATE ON chapters
BEGIN
    UPDATE chapters SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

-- Views for common reporting needs
CREATE VIEW IF NOT EXISTS vw_books_progress AS
SELECT 
    b.id,
    b.stt,
    b.title,
    b.seo_title_full,
    b.book_status,
    b.download_status,
    b.total_chapters,
    b.downloaded_chapters,
    CASE 
        WHEN b.total_chapters = 0 THEN 0
        ELSE ROUND((b.downloaded_chapters * 100.0) / b.total_chapters, 2)
    END as progress_percentage,
    b.updated_at
FROM books b;

CREATE VIEW IF NOT EXISTS vw_chapters_progress AS
SELECT 
    c.id,
    c.book_id,
    b.title as book_title,
    c.chapter_order,
    c.chapter_title,
    c.chapter_url,
    c.download_status,
    c.downloaded_at,
    c.retry_count,
    c.file_path
FROM chapters c
JOIN books b ON c.book_id = b.id
ORDER BY b.title, c.chapter_order;