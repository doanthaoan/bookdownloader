"""
Database Manager for Vietnamese Novel Download Tool
Handles all SQLite database operations replacing Excel file management
"""

import sqlite3
import os
import threading
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from urllib.parse import urlparse
import logging

logger = logging.getLogger(__name__)


class NovelDatabase:
    def __init__(self, db_path: str = None):
        """
        Initialize database manager.
        Uses thread-local connections so each thread gets its own connection,
        avoiding "cannot commit - no transaction is active" errors.

        Args:
            db_path: Path to SQLite database file
        """
        if db_path is None:
            base_dir = Path(__file__).parent.parent / "data"
            self.db_path = str(base_dir / "novel_downloader.db")
        else:
            self.db_path = db_path

        self._local = threading.local()
        self._schema_initialized = False
        self._initialize_database()

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create a thread-local database connection."""
        conn = getattr(self._local, 'connection', None)
        if conn is None:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            conn = sqlite3.connect(
                self.db_path,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
                check_same_thread=False
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode=WAL")
            self._local.connection = conn
        return conn

    def close(self):
        """Close the current thread's database connection."""
        conn = getattr(self._local, 'connection', None)
        if conn:
            conn.close()
            self._local.connection = None

    def _initialize_database(self):
        """Create database schema if it doesn't exist (runs once)."""
        if self._schema_initialized:
            return
        schema_path = Path(__file__).parent.parent / "data" / "database_schema.sql"
        try:
            with open(schema_path, 'r', encoding='utf-8') as f:
                schema_sql = f.read()
            conn = self._get_connection()
            conn.executescript(schema_sql)
            conn.commit()
            self._run_migrations(conn)
            self._schema_initialized = True
            logger.info(f"Database initialized at {self.db_path}")
        except FileNotFoundError:
            logger.error(f"Schema file not found: {schema_path}")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

    def _run_migrations(self, conn):
        """Run incremental schema migrations, ignoring errors if already applied."""
        migrations = [
            "ALTER TABLE books ADD COLUMN author TEXT",
            "ALTER TABLE books ADD COLUMN book_web_status TEXT",
            "ALTER TABLE books ADD COLUMN last_chapter_url TEXT",
            "ALTER TABLE books ADD COLUMN last_chapter_title TEXT",
            "ALTER TABLE books ADD COLUMN last_update_date TEXT",
            "CREATE INDEX IF NOT EXISTS idx_books_author ON books(author)",
            "CREATE INDEX IF NOT EXISTS idx_books_web_status ON books(book_web_status)",
            "ALTER TABLE books ADD COLUMN is_favorite INTEGER DEFAULT 0",
            "ALTER TABLE books ADD COLUMN is_sent INTEGER DEFAULT 0",
            "ALTER TABLE books ADD COLUMN cover_image_url TEXT",
            "ALTER TABLE books ADD COLUMN short_description TEXT",
            "ALTER TABLE books ADD COLUMN source_file TEXT",
            "ALTER TABLE books ADD COLUMN is_translated INTEGER DEFAULT 0",
            "ALTER TABLE chapters ADD COLUMN chapter_content TEXT",
            "ALTER TABLE chapters ADD COLUMN translated_content TEXT",
        ]
        for sql in migrations:
            try:
                conn.execute(sql)
                conn.commit()
            except Exception as e:
                logger.debug(f"Migration skipped (already applied?): {sql[:60]}... → {e}")

        # Migrate existing absolute URLs to relative (domain-independent)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row

        # Fix chapters.chapter_url
        for row in conn.execute("SELECT id, chapter_url FROM chapters WHERE chapter_url LIKE 'http%'").fetchall():
            parsed = urlparse(row['chapter_url'])
            relative = parsed.path
            if parsed.query:
                relative += '?' + parsed.query
            conn.execute("UPDATE chapters SET chapter_url = ? WHERE id = ?", (relative, row['id']))
            logger.info(f"Normalized chapter URL (id={row['id']}): {row['chapter_url'][:60]} → {relative[:60]}")

        # Fix books.last_chapter_url
        for row in conn.execute("SELECT id, last_chapter_url FROM books WHERE last_chapter_url LIKE 'http%'").fetchall():
            parsed = urlparse(row['last_chapter_url'])
            relative = parsed.path
            if parsed.query:
                relative += '?' + parsed.query
            conn.execute("UPDATE books SET last_chapter_url = ? WHERE id = ?", (relative, row['id']))
            logger.info(f"Normalized book last_chapter_url (id={row['id']})")

        # Create book_corrections table (idempotent)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS book_corrections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_id INTEGER NOT NULL,
                    find_text TEXT NOT NULL,
                    replace_text TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
                )
            """)
        except Exception as e:
            logger.debug(f"book_corrections creation skipped: {e}")

        # Create tags and book_tags tables (idempotent)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS book_tags (
                    book_id INTEGER NOT NULL,
                    tag_id INTEGER NOT NULL,
                    PRIMARY KEY (book_id, tag_id),
                    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
                    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
                )
            """)
        except Exception as e:
            logger.debug(f"tags/book_tags creation skipped: {e}")

        # Create text_cleaning_rules table (idempotent)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS text_cleaning_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rule_type TEXT NOT NULL CHECK(rule_type IN ('remove', 'replace')),
                    match_type TEXT NOT NULL CHECK(match_type IN ('simple', 'regex')),
                    find_text TEXT NOT NULL,
                    replace_text TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    description TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("PRAGMA table_info(text_cleaning_rules)")
        except Exception as e:
            logger.debug(f"text_cleaning_rules creation skipped: {e}")

        # Seed defaults if table is empty
        existing = conn.execute("SELECT COUNT(*) FROM text_cleaning_rules").fetchone()[0]
        if existing == 0:
            defaults = [
                ("remove", "regex",  r"[\x00-\x1F\x7F]", "",   1, 0,  "Invalid XML characters"),
                ("remove", "simple", "·",                      "",   1, 1,  "Specific dot character"),
                ("remove", "simple", "║༺☆༻ Convert by DuFengYu on Wikidich ༺☆༻║", "", 1, 2, "Converter signature"),
                ("replace", "simple", "—", "...",                1, 3,  "Em dash to three dots"),
                ("remove", "regex",  r"(Chương|chương)\s+(\d+)\s+\1\s+\2", "", 1, 4, "Deduplicate chapter number in title"),
            ]
            for r in defaults:
                conn.execute(
                    "INSERT INTO text_cleaning_rules (rule_type, match_type, find_text, replace_text, enabled, sort_order, description) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    r
                )
        conn.commit()
    
    # === BOOK OPERATIONS ===
    
    def add_book(self, title: str, stt: str = None, book_url: str = None, 
                 notes: str = None, author: str = None,
                 book_web_status: str = None,
                 last_chapter_url: str = None,
                 last_chapter_title: str = None,
                 last_update_date: str = None,
                 cover_image_url: str = None,
                 short_description: str = None) -> int:
        """
        Add a new book to the database
        
        Returns:
            ID of the newly inserted book
        """
        from app.utils import clean_title
        
        seo_basic = clean_title(title)
        seo_full = f"{seo_basic}.html"
        
        conn = self._get_connection()
        cursor = conn.execute("""
            INSERT INTO books (stt, title, seo_title_basic, seo_title_full, 
                             book_url, notes, author, book_web_status,
                             last_chapter_url, last_chapter_title, last_update_date, cover_image_url, short_description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (stt, title, seo_basic, seo_full, book_url, notes,
              author, book_web_status, last_chapter_url, last_chapter_title, last_update_date, cover_image_url, short_description))
        
        conn.commit()
        book_id = cursor.lastrowid
        logger.info(f"Added book: {title} (ID: {book_id})")
        return book_id

    def update_book_info(self, book_id: int, **kwargs):
        """Update metadata fields on a book (author, web_status, etc.)."""
        allowed = {'author', 'book_web_status', 'last_chapter_url',
                   'last_chapter_title', 'last_update_date', 'total_chapters',
                   'is_favorite', 'is_sent', 'cover_image_url', 'short_description',
                   'source_file', 'is_translated', 'notes'}
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not updates:
            return
        set_clause = ', '.join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [book_id]
        conn = self._get_connection()
        conn.execute(f"UPDATE books SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", params)
        conn.commit()
    
    def get_book(self, book_id: int) -> Optional[Dict]:
        """Get book by ID"""
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def get_book_by_title(self, title: str) -> Optional[Dict]:
        """Get book by title"""
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM books WHERE title = ?", (title,))
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def get_books_by_status(self, status: str) -> List[Dict]:
        """Get all books with specific download status"""
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("""
            SELECT * FROM books 
            WHERE download_status = ? 
            ORDER BY title
        """, (status,))
        return [dict(row) for row in cursor.fetchall()]
    
    def update_book_status(self, book_id: int, download_status: str = None, 
                          total_chapters: int = None, 
                          downloaded_chapters: int = None):
        """Book progress and status tracking updates. Any omitted field is left
        untouched (download_status is only changed when explicitly passed)."""
        update_fields = ["updated_at = CURRENT_TIMESTAMP"]
        params = []
        
        if download_status is not None:
            update_fields.append("download_status = ?")
            params.append(download_status)
            
        if total_chapters is not None:
            update_fields.append("total_chapters = ?")
            params.append(total_chapters)
            
        if downloaded_chapters is not None:
            update_fields.append("downloaded_chapters = ?")
            params.append(downloaded_chapters)
        
        params.append(book_id)
        
        conn = self._get_connection()
        conn.execute(f"""
            UPDATE books 
            SET {', '.join(update_fields)}
            WHERE id = ?
        """, params)
        conn.commit()
    
    # === CHAPTER OPERATIONS ===
    
    def add_chapter(self, book_id: int, chapter_order: int, 
                   chapter_title: str, chapter_url: str) -> int:
        """
        Add a chapter to a book
        
        Returns:
            ID of the newly inserted chapter
        """
        conn = self._get_connection()
        cursor = conn.execute("""
            INSERT INTO chapters (book_id, chapter_order, chapter_title, chapter_url)
            VALUES (?, ?, ?, ?)
        """, (book_id, chapter_order, chapter_title, chapter_url))
        
        conn.commit()
        chapter_id = cursor.lastrowid
        logger.debug(f"Added chapter: {chapter_title} (ID: {chapter_id})")
        return chapter_id
    
    def add_chapter_with_content(self, book_id: int, chapter_order: int,
                             chapter_title: str, chapter_url: str,
                             chapter_content: str = None) -> int:
        """
        Add a chapter to a book, optionally storing raw/translated content.
        
        Returns:
            ID of the newly inserted chapter
        """
        conn = self._get_connection()
        cursor = conn.execute("""
            INSERT INTO chapters (book_id, chapter_order, chapter_title, chapter_url, chapter_content)
            VALUES (?, ?, ?, ?, ?)
        """, (book_id, chapter_order, chapter_title, chapter_url, chapter_content))
        conn.commit()
        chapter_id = cursor.lastrowid
        logger.debug(f"Added chapter: {chapter_title} (ID: {chapter_id})")
        return chapter_id

    def update_chapter_content(self, chapter_id: int, chapter_content: str):
        """Store translated content for a chapter."""
        conn = self._get_connection()
        conn.execute("UPDATE chapters SET chapter_content = ? WHERE id = ?", (chapter_content, chapter_id))
        conn.commit()

    def update_chapter_title(self, chapter_id: int, chapter_title: str):
        """Store the cleaned page title for a chapter (used when exporting the DOCX)."""
        conn = self._get_connection()
        conn.execute("UPDATE chapters SET chapter_title = ? WHERE id = ?", (chapter_title, chapter_id))
        conn.commit()

    def update_chapter_translated_content(self, chapter_id: int, translated_content: str):
        """Store the Vietnamese translation for a chapter.

        Format: "<viet_title>\\n<viet_body>" so the DOCX exporter can split the
        heading from the body without a separate column. Corrections are NOT
        applied here — they are applied at DOCX export time.
        """
        conn = self._get_connection()
        conn.execute("UPDATE chapters SET translated_content = ? WHERE id = ?", (translated_content, chapter_id))
        conn.commit()

    def get_book_corrections(self, book_id: int) -> List[Dict]:
        """Get all corrections for a book, ordered by sort_order."""
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT * FROM book_corrections WHERE book_id = ?
            ORDER BY sort_order, id
        """, (book_id,)).fetchall()
        return [dict(r) for r in rows]

    def set_book_corrections(self, book_id: int, corrections: List[Dict]):
        """Replace all corrections for a book.
        Each item: {'find_text': str, 'replace_text': str, 'enabled': bool}
        """
        conn = self._get_connection()
        conn.execute("DELETE FROM book_corrections WHERE book_id = ?", (book_id,))
        for i, c in enumerate(corrections):
            find_text = (c.get('find_text') or '').strip()
            if not find_text:
                continue
            conn.execute("""
                INSERT INTO book_corrections (book_id, find_text, replace_text, enabled, sort_order)
                VALUES (?, ?, ?, ?, ?)
            """, (book_id, find_text, c.get('replace_text') or '', 1 if c.get('enabled', True) else 0, i))
        conn.commit()

    def get_chapters_by_book(self, book_id: int, 
                            status: str = None) -> List[Dict]:
        """Get all chapters for a book, optionally filtered by status"""
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        
        if status:
            cursor = conn.execute("""
                SELECT * FROM chapters 
                WHERE book_id = ? AND download_status = ?
                ORDER BY chapter_order
            """, (book_id, status))
        else:
            cursor = conn.execute("""
                SELECT * FROM chapters 
                WHERE book_id = ?
                ORDER BY chapter_order
            """, (book_id,))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def get_pending_chapters(self, limit: int = None) -> List[Dict]:
        """Get chapters pending download"""
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        
        if limit:
            cursor = conn.execute("""
                SELECT c.*, b.title as book_title, b.seo_title_full
                FROM chapters c
                JOIN books b ON c.book_id = b.id
                WHERE c.download_status = 'pending'
                ORDER BY b.title, c.chapter_order
                LIMIT ?
            """, (limit,))
        else:
            cursor = conn.execute("""
                SELECT c.*, b.title as book_title, b.seo_title_full
                FROM chapters c
                JOIN books b ON c.book_id = b.id
                WHERE c.download_status = 'pending'
                ORDER BY b.title, c.chapter_order
            """)
        
        return [dict(row) for row in cursor.fetchall()]
    
    def update_chapter_status(self, chapter_id: int, status: str, 
                             file_path: str = None, 
                             error_message: str = None):
        """Update chapter download status"""
        update_fields = ["download_status = ?", "updated_at = CURRENT_TIMESTAMP"]
        params = [status]
        
        if status == 'completed':
            update_fields.append("downloaded_at = CURRENT_TIMESTAMP")
            if file_path:
                update_fields.append("file_path = ?")
                params.append(file_path)
        elif status == 'failed':
            if error_message:
                update_fields.append("error_message = ?")
                params.append(error_message)
        
        params.append(chapter_id)
        
        conn = self._get_connection()
        conn.execute(f"""
            UPDATE chapters 
            SET {', '.join(update_fields)}
            WHERE id = ?
        """, params)
        conn.commit()
    
    def reset_failed_chapters(self, book_id: int) -> int:
        """Set all 'failed' chapters of a book back to 'pending' so a run can
        resume them into the main DOCX. Returns how many chapters were reset."""
        conn = self._get_connection()
        cursor = conn.execute("""
            UPDATE chapters 
            SET download_status = 'pending', error_message = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE book_id = ? AND download_status = 'failed'
        """, (book_id,))
        conn.commit()
        return cursor.rowcount
    
    # === SETTINGS OPERATIONS ===
    
    def get_setting(self, key: str, default: str = None) -> str:
        """Get application setting value"""
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT value FROM application_settings WHERE key = ?", 
            (key,)
        )
        row = cursor.fetchone()
        return row[0] if row else default
    
    def update_setting(self, key: str, value: str):
        """Update application setting"""
        conn = self._get_connection()
        conn.execute("""
            INSERT OR REPLACE INTO application_settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """, (key, value))
        conn.commit()
    
    # === TAG OPERATIONS ===

    def add_tag(self, name: str) -> int:
        """Get or create a tag by name, return its id."""
        conn = self._get_connection()
        row = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
        if row:
            return row[0]
        cursor = conn.execute("INSERT INTO tags (name) VALUES (?)", (name,))
        conn.commit()
        return cursor.lastrowid

    def set_book_tags(self, book_id: int, tag_names: List[str]):
        """Replace all tags for a book with the given list of tag names."""
        conn = self._get_connection()
        conn.execute("DELETE FROM book_tags WHERE book_id = ?", (book_id,))
        for name in tag_names:
            name = name.strip()
            if name:
                tag_id = self.add_tag(name)
                conn.execute("INSERT OR IGNORE INTO book_tags (book_id, tag_id) VALUES (?, ?)", (book_id, tag_id))
        conn.commit()

    def get_book_tags(self, book_id: int) -> list[str]:
        """Get all tag names for a book."""
        conn = self._get_connection()
        rows = conn.execute("""
            SELECT t.name FROM tags t
            JOIN book_tags bt ON bt.tag_id = t.id
            WHERE bt.book_id = ?
            ORDER BY t.name
        """, (book_id,)).fetchall()
        return [r[0] for r in rows]

    def get_all_tags(self) -> list[dict]:
        """List all tags with book count."""
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT t.id, t.name, COUNT(bt.book_id) as book_count
            FROM tags t
            LEFT JOIN book_tags bt ON bt.tag_id = t.id
            GROUP BY t.id
            ORDER BY t.name
        """).fetchall()
        return [dict(r) for r in rows]

    def get_books_by_tag(self, tag_name: str) -> list[int]:
        """Get book IDs that have a given tag."""
        conn = self._get_connection()
        rows = conn.execute("""
            SELECT bt.book_id FROM book_tags bt
            JOIN tags t ON t.id = bt.tag_id
            WHERE t.name = ?
        """, (tag_name,)).fetchall()
        return [r[0] for r in rows]

    # === TEXT CLEANING RULES OPERATIONS ===

    def get_text_cleaning_rules(self, enabled_only: bool = False) -> List[Dict]:
        """Get all text cleaning rules, ordered by sort_order."""
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        if enabled_only:
            rows = conn.execute("SELECT * FROM text_cleaning_rules WHERE enabled = 1 ORDER BY sort_order").fetchall()
        else:
            rows = conn.execute("SELECT * FROM text_cleaning_rules ORDER BY sort_order").fetchall()
        return [dict(r) for r in rows]

    def add_text_cleaning_rule(self, rule_type: str, match_type: str, find_text: str,
                               replace_text: str = '', enabled: int = 1,
                               sort_order: int = None, description: str = '') -> int:
        conn = self._get_connection()
        if sort_order is None:
            row = conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM text_cleaning_rules").fetchone()
            sort_order = row[0]
        conn.execute("""
            INSERT INTO text_cleaning_rules (rule_type, match_type, find_text, replace_text, enabled, sort_order, description)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (rule_type, match_type, find_text, replace_text, enabled, sort_order, description))
        conn.commit()
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def update_text_cleaning_rule(self, rule_id: int, **kwargs) -> bool:
        allowed = {'rule_type', 'match_type', 'find_text', 'replace_text', 'enabled', 'sort_order', 'description'}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False
        set_clause = ', '.join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [rule_id]
        conn = self._get_connection()
        conn.execute(f"UPDATE text_cleaning_rules SET {set_clause} WHERE id = ?", params)
        conn.commit()
        return True

    def delete_text_cleaning_rule(self, rule_id: int) -> bool:
        conn = self._get_connection()
        conn.execute("DELETE FROM text_cleaning_rules WHERE id = ?", (rule_id,))
        conn.commit()
        return True

    def reorder_text_cleaning_rule(self, rule_id: int, new_order: int):
        """Move a rule to a new position and shift others accordingly."""
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        rules = conn.execute("SELECT id, sort_order FROM text_cleaning_rules ORDER BY sort_order").fetchall()
        orders = [r['sort_order'] for r in rules]
        ids = [r['id'] for r in rules]
        if rule_id not in ids:
            return
        old_idx = ids.index(rule_id)
        new_idx = max(0, min(len(rules) - 1, new_order))
        ids.pop(old_idx)
        ids.insert(new_idx, rule_id)
        for i, rid in enumerate(ids):
            conn.execute("UPDATE text_cleaning_rules SET sort_order = ? WHERE id = ?", (i, rid))
        conn.commit()

    # === REQUEST LOG OPERATIONS ===

    def log_request(self, request_type: str, status: str, session_type: str = "session",
                    domain: str = None, url: str = None, book_id: int = None,
                    chapter_id: int = None, detail: str = None, error: str = None,
                    duration_ms: int = None):
        """Record a site request or business event for statistics.

        request_type: chapter, book_page, chapter_list, cover_image,
                      book_added, book_download, translate_api, translate_web.
        status: success / failed. Timestamps are stored in LOCAL time so the
        daily grouping ("today") lines up with the user's clock.
        """
        conn = self._get_connection()
        conn.execute("""
            INSERT INTO request_logs
                (created_at, request_type, status, session_type, domain, url,
                 book_id, chapter_id, detail, error, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), request_type, status,
              session_type, domain, url, book_id, chapter_id, detail, error, duration_ms))
        conn.commit()

    def _build_log_filter(self, start=None, end=None, request_type=None, status=None,
                          session_type=None, domain=None, prefix: str = "") -> tuple:
        """Build WHERE clause + params for request_logs queries.

        prefix: table alias to qualify columns with (e.g. 'r.' when the query
        joins another table that also has a created_at column).
        """
        conds, params = [], []
        created = f"{prefix}created_at"
        if start:
            conds.append(f"date({created}) >= date(?)")
            params.append(start)
        if end:
            conds.append(f"date({created}) <= date(?)")
            params.append(end)
        if request_type:
            conds.append(f"{prefix}request_type = ?")
            params.append(request_type)
        if status:
            conds.append(f"{prefix}status = ?")
            params.append(status)
        if session_type:
            conds.append(f"{prefix}session_type = ?")
            params.append(session_type)
        if domain:
            conds.append(f"{prefix}domain = ?")
            params.append(domain)
        return (" AND ".join(conds), params)

    def get_request_stats(self, start: str = None, end: str = None, request_type: str = None,
                          status: str = None, session_type: str = None, domain: str = None) -> Dict:
        """Aggregate request-log stats over a date range (inclusive)."""
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        where, params = self._build_log_filter(start, end, request_type, status, session_type, domain)
        where_sql = ("WHERE " + where) if where else ""
        total = conn.execute(f"SELECT COUNT(*) FROM request_logs {where_sql}", params).fetchone()[0]
        by_status = {r['status']: r['n'] for r in conn.execute(
            f"SELECT status, COUNT(*) as n FROM request_logs {where_sql} GROUP BY status", params)}
        by_type = {r['request_type']: r['n'] for r in conn.execute(
            f"SELECT request_type, COUNT(*) as n FROM request_logs {where_sql} GROUP BY request_type", params)}
        by_session = {r['session_type']: r['n'] for r in conn.execute(
            f"SELECT session_type, COUNT(*) as n FROM request_logs {where_sql} GROUP BY session_type", params)}
        by_day = [dict(r) for r in conn.execute(f"""
            SELECT date(created_at) as day, COUNT(*) as total,
                   SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
                   SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
            FROM request_logs {where_sql} GROUP BY day ORDER BY day
        """, params)]
        return {
            "total": total,
            "by_status": by_status,
            "by_type": by_type,
            "by_session": by_session,
            "by_day": by_day,
        }

    def get_request_logs(self, start: str = None, end: str = None, request_type: str = None,
                         status: str = None, session_type: str = None, domain: str = None,
                         page: int = 1, per_page: int = 50) -> Dict:
        """Paginated request log entries, newest first."""
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        where, params = self._build_log_filter(start, end, request_type, status, session_type, domain, prefix="r.")
        where_sql = ("WHERE " + where) if where else ""
        total = conn.execute(f"SELECT COUNT(*) FROM request_logs r {where_sql}", params).fetchone()[0]
        offset = (page - 1) * per_page
        rows = conn.execute(f"""
            SELECT r.*, b.title as book_title
            FROM request_logs r
            LEFT JOIN books b ON b.id = r.book_id
            {where_sql}
            ORDER BY r.id DESC
            LIMIT ? OFFSET ?
        """, params + [per_page, offset]).fetchall()
        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": max(1, (total + per_page - 1) // per_page),
            "logs": [dict(r) for r in rows],
        }

    def get_daily_chapter_counts(self, start_day: str = None, end_day: str = None,
                                 session_type: str = None) -> List[Dict]:
        """Daily chapter-request counts (success/failed) for a date range,
        grouped by session_type. Used for the daily-limit estimate."""
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        conds = ["request_type = 'chapter'"]
        params = []
        if start_day:
            conds.append("date(created_at) >= date(?)")
            params.append(start_day)
        if end_day:
            conds.append("date(created_at) <= date(?)")
            params.append(end_day)
        if session_type:
            conds.append("session_type = ?")
            params.append(session_type)
        rows = conn.execute(f"""
            SELECT date(created_at) as day, session_type, COUNT(*) as total,
                   SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
                   SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
            FROM request_logs
            WHERE {' AND '.join(conds)}
            GROUP BY date(created_at), session_type
            ORDER BY day
        """, params).fetchall()
        return [dict(r) for r in rows]

    def get_request_log_meta(self) -> Dict:
        """Distinct values present in the log (for filter dropdowns)."""
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        def distinct(col):
            return [r[0] for r in conn.execute(
                f"SELECT DISTINCT {col} FROM request_logs WHERE {col} IS NOT NULL AND {col} != '' ORDER BY {col}").fetchall()]
        return {
            "request_types": distinct("request_type"),
            "statuses": distinct("status"),
            "session_types": distinct("session_type"),
            "domains": distinct("domain"),
        }

    # === UTILITY METHODS ===
    
    def get_download_stats(self) -> Dict:
        """Get overall download statistics"""
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        
        # Book-level stats
        book_cursor = conn.execute("""
            SELECT 
                COUNT(*) as total_books,
                SUM(CASE WHEN download_status = 'completed' THEN 1 ELSE 0 END) as completed_books,
                SUM(CASE WHEN download_status = 'in_progress' THEN 1 ELSE 0 END) as in_progress_books,
                SUM(CASE WHEN download_status = 'pending' THEN 1 ELSE 0 END) as pending_books,
                SUM(CASE WHEN download_status = 'failed' THEN 1 ELSE 0 END) as failed_books
            FROM books
        """)
        book_stats = dict(book_cursor.fetchone())
        
        # Chapter-level stats
        chapter_cursor = conn.execute("""
            SELECT 
                COUNT(*) as total_chapters,
                SUM(CASE WHEN download_status = 'completed' THEN 1 ELSE 0 END) as completed_chapters,
                SUM(CASE WHEN download_status = 'in_progress' THEN 1 ELSE 0 END) as in_progress_chapters,
                SUM(CASE WHEN download_status = 'pending' THEN 1 ELSE 0 END) as pending_chapters,
                SUM(CASE WHEN download_status = 'failed' THEN 1 ELSE 0 END) as failed_chapters
            FROM chapters
        """)
        chapter_stats = dict(chapter_cursor.fetchone())
        
        return {
            'books': book_stats,
            'chapters': chapter_stats
        }
    
    def execute_query(self, query: str, params: tuple = ()) -> List[Dict]:
        """Execute custom query and return results as list of dicts"""
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

# Global database instance
db = NovelDatabase()

def get_database() -> NovelDatabase:
    """Get global database instance"""
    return db