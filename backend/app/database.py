"""
Database Manager for Vietnamese Novel Download Tool
Handles all SQLite database operations (this replaced an older Excel-file
based workflow).

The DB file is backend/data/novel_downloader.db and is the source of truth:
books, chapters (incl. chapter_content / translated_content), per-book
corrections, tags, global text-cleaning rules, settings and request logs.
DOCX files are always re-rendered from it.

Usage: everyone shares ONE `NovelDatabase` instance via `get_database()`
(module-level singleton at the bottom of this file).

Connections, threads and WAL — why it is built this way
--------------------------------------------------------
FastAPI handles requests on a thread pool, and downloads/translations run in
their own background threads. A single sqlite3.Connection shared by all of
them would interleave transactions (one thread's commit() ending another's
transaction -> "cannot commit - no transaction is active"). So each thread
gets its own connection, stored in a `threading.local()` object: an object
whose attributes are private per thread (thread A's `self._local.connection`
is a different value from thread B's).

Several connections writing the same file need WAL mode
(`PRAGMA journal_mode=WAL`, write-ahead log). Writes are appended to the
`-wal` side file, so readers are not blocked by a writer and only writers
take turns. The mode is stored in the DB file itself, so it persists.

Schema changes
--------------
data/database_schema.sql creates the base tables (`CREATE TABLE IF NOT
EXISTS`, safe to re-run). Everything added later lives in `_run_migrations()`
as idempotent steps that run on every startup — never edit the .sql file
to change an existing DB.
"""

import sqlite3
import os
import threading
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from urllib.parse import urlparse
import logging

# `__name__` is this module's dotted name ("app.database"), so log lines
# show where they came from.
logger = logging.getLogger(__name__)


class NovelDatabase:
    """All SQLite access for the app: books, chapters, corrections, tags,
    text-cleaning rules, settings and request logs.

    Rows are returned as plain dicts (`dict(row)`), so callers never depend
    on sqlite3 types. Every write method commits immediately.
    """

    def __init__(self, db_path: str = None):
        """
        Initialize database manager.
        Uses thread-local connections so each thread gets its own connection,
        avoiding "cannot commit - no transaction is active" errors.

        Args:
            db_path: Path to SQLite database file. None (default) means
                backend/data/novel_downloader.db.

        Raises:
            FileNotFoundError / sqlite3.Error: from _initialize_database().

        Side effects: creates the data folder/DB file if missing, runs the
        schema script and all migrations (may write to the live DB).
        """
        if db_path is None:
            base_dir = Path(__file__).parent.parent / "data"
            self.db_path = str(base_dir / "novel_downloader.db")
        else:
            self.db_path = db_path

        # Per-thread storage; see the module docstring for why.
        self._local = threading.local()
        self._schema_initialized = False
        self._initialize_database()

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create a thread-local database connection.

        The first call in each thread opens a new connection; later calls in
        the same thread reuse it. Also usable for ad-hoc queries from other
        modules (there is no db.get_chapter()).

        Returns:
            sqlite3.Connection with row_factory=sqlite3.Row, foreign keys on
            and WAL journal mode.

        Side effects: may create the data folder and DB file.
        """
        # getattr(obj, name, default) returns `default` instead of raising
        # AttributeError — true the first time a given thread gets here.
        conn = getattr(self._local, 'connection', None)
        if conn is None:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            conn = sqlite3.connect(
                self.db_path,
                # Convert columns declared e.g. TIMESTAMP into Python datetime
                # objects (`|` combines the two flag bits).
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
                # sqlite3 normally refuses use from a thread other than the
                # creator. Each thread has its own connection here anyway;
                # this just disables the safety check.
                check_same_thread=False
            )
            # sqlite3.Row lets you read columns by name (row['title']) as
            # well as by index (row[0]), and `dict(row)` converts it.
            conn.row_factory = sqlite3.Row
            # SQLite ignores FOREIGN KEY / ON DELETE CASCADE unless this is
            # turned on per connection.
            conn.execute("PRAGMA foreign_keys = ON")
            # Write-ahead log: concurrent readers + one writer (see module docstring).
            conn.execute("PRAGMA journal_mode=WAL")
            self._local.connection = conn
        return conn

    def close(self):
        """Close the current thread's database connection.

        Only affects the calling thread; other threads keep theirs. The next
        _get_connection() in this thread opens a fresh one.
        """
        conn = getattr(self._local, 'connection', None)
        if conn:
            conn.close()
            self._local.connection = None

    def _initialize_database(self):
        """Create database schema if it doesn't exist (runs once per process).

        Runs data/database_schema.sql, then _run_migrations().

        Raises:
            FileNotFoundError: the schema .sql file is missing.
            Exception: any SQL error is logged and re-raised (the app should
                not start on a broken DB).

        Side effects: DDL and migration writes on the live DB.
        """
        if self._schema_initialized:
            return
        schema_path = Path(__file__).parent.parent / "data" / "database_schema.sql"
        try:
            # `with` = context manager: the file is closed automatically when
            # the block ends, even if an exception is raised inside it.
            with open(schema_path, 'r', encoding='utf-8') as f:
                schema_sql = f.read()
            conn = self._get_connection()
            # executescript() runs many ';'-separated statements at once
            # (execute() accepts only one). It COMMITs any pending transaction first.
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
            # Bare `raise` re-raises the current exception with its traceback.
            raise

    def _run_migrations(self, conn):
        """Run incremental schema migrations, ignoring errors if already applied.

        Strategy: there is no "schema version" table. Every step is written so
        running it twice is harmless (idempotent), and the whole list runs on
        every startup:
          - `ALTER TABLE ... ADD COLUMN` fails with "duplicate column" once
            applied; each runs in its own try/except and the error is ignored.
          - `CREATE ... IF NOT EXISTS` is a no-op the second time.
          - Data fixes (URL normalization) only match rows not yet fixed.
          - Default text-cleaning rules are seeded only when the table is empty.
        To change the schema, APPEND a new step here; never edit or reorder
        existing ones.

        Args:
            conn: the connection from _get_connection().

        Side effects: may add columns/tables/indexes, rewrite URL columns and
        insert default rules in the live DB.
        """
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
            "ALTER TABLE books ADD COLUMN auto_export_docx INTEGER DEFAULT 1",
            "ALTER TABLE chapters ADD COLUMN chapter_content TEXT",
            "ALTER TABLE chapters ADD COLUMN translated_content TEXT",
        ]
        for sql in migrations:
            try:
                conn.execute(sql)
                conn.commit()
            except Exception as e:
                # sql[:60] = slice: first 60 characters, keeps the log short.
                # TODO: this also hides real errors (typos, locked DB); check
                # for "duplicate column name" and re-raise anything else.
                logger.debug(f"Migration skipped (already applied?): {sql[:60]}... → {e}")

        # Migrate existing absolute URLs to relative (domain-independent).
        # Old rows stored "https://wikicv.org/truyen/x/chuong-1"; the site
        # changes domain from time to time, so we now store only
        # "/truyen/x/chuong-1" (+ "?query") and prepend TRUYENWIKI['book_domain']
        # when building a request. `LIKE 'http%'` (% = any characters) selects
        # only rows still absolute, so after the first run this finds nothing.
        # urlparse() splits a URL into scheme, netloc (host), path, query, ...
        # (This PRAGMA is redundant — _get_connection() already set WAL.)
        conn.execute("PRAGMA journal_mode=WAL")

        # Fix chapters.chapter_url
        # .fetchall() loads all matches first, so we are not updating the
        # table while still iterating over a live cursor on it.
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
            # PRAGMA table_info lists a table's columns; the result is unused
            # here (leftover). TODO: remove, or use it to check for columns.
            conn.execute("PRAGMA table_info(text_cleaning_rules)")
        except Exception as e:
            logger.debug(f"text_cleaning_rules creation skipped: {e}")

        # Extra site accounts used by the downloader when the site's access limit
        # is reached (guest → primary cookie_* settings → these, in id order).
        # `cookies` is a JSON object {name: value} filled by auto-login.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS site_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                password TEXT NOT NULL DEFAULT '',
                cookies TEXT NOT NULL DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Seed defaults if table is empty (so deleting all rules on purpose
        # brings the defaults back on the next restart).
        # fetchone()[0] = first column of the single result row.
        existing = conn.execute("SELECT COUNT(*) FROM text_cleaning_rules").fetchone()[0]
        if existing == 0:
            # Tuples in column order: (rule_type, match_type, find_text,
            # replace_text, enabled, sort_order, description).
            # r"..." = raw string: backslashes are kept literally, which is
            # what regex patterns need. [\x00-\x1F\x7F] = ASCII control chars
            # (invalid in DOCX XML). In the last rule, \1 and \2 are
            # back-references: "Chương 5 Chương 5" -> matches the repeat.
            defaults = [
                ("remove", "regex",  r"[\x00-\x1F\x7F]", "",   1, 0,  "Invalid XML characters"),
                ("remove", "simple", "·",                      "",   1, 1,  "Specific dot character"),
                ("remove", "simple", "║༺☆༻ Convert by DuFengYu on Wikidich ༺☆༻║", "", 1, 2, "Converter signature"),
                ("replace", "simple", "—", "...",                1, 3,  "Em dash to three dots"),
                ("remove", "regex",  r"(Chương|chương)\s+(\d+)\s+\1\s+\2", "", 1, 4, "Deduplicate chapter number in title"),
            ]
            for r in defaults:
                # `?` placeholders: sqlite3 fills them from the tuple and
                # escapes values safely (never build SQL values with f-strings).
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

        Args:
            title: display title (Vietnamese). Also used to derive
                seo_title_basic (slug) and seo_title_full ("<slug>.html").
            stt, book_url, notes, author, book_web_status, last_chapter_url,
            last_chapter_title, last_update_date, cover_image_url,
            short_description: optional metadata; None is stored as NULL.

        Returns:
            ID of the newly inserted book

        Raises:
            sqlite3.IntegrityError: if a schema UNIQUE/NOT NULL constraint fails.

        Side effects: INSERT into `books` + commit.
        """
        # Imported inside the function (a "local import") to avoid a
        # circular import between app.utils and app.database.
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
        # lastrowid = the AUTOINCREMENT id SQLite assigned to the new row.
        book_id = cursor.lastrowid
        logger.info(f"Added book: {title} (ID: {book_id})")
        return book_id

    def update_book_info(self, book_id: int, **kwargs):
        """Update metadata fields on a book.

        Args:
            book_id: id of the book row to update.
            **kwargs: column=value pairs, e.g. `update_book_info(5, author="X")`.
                `**kwargs` collects any keyword arguments into a dict.
                Keys outside `allowed` are silently ignored (protects against
                SQL injection through column names and against callers that
                pass extra keys such as the scraped `tags` list).
                Passing a key with value None CLEARS that column (writes NULL)
                — callers that don't want to touch a column must not pass it.

        Side effects: writes to the `books` table and bumps `updated_at`.

        Note: `seo_title_basic`/`seo_title_full` are intentionally NOT editable.
        They are used in file names ({id}_{seo}.docx, cover image), so changing
        them would orphan existing files. Editing `title` only changes the
        display title.
        """
        allowed = {'title', 'author', 'book_web_status', 'last_chapter_url',
                   'last_chapter_title', 'last_update_date', 'total_chapters',
                   'is_favorite', 'is_sent', 'cover_image_url', 'short_description',
                   'source_file', 'is_translated', 'notes', 'auto_export_docx'}
        # Dict comprehension: keep only the allowed keys. We filter on key
        # presence (not on `v is not None`) so a caller can clear a field.
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        # Generator expression inside join(): "author = ?, title = ?".
        set_clause = ', '.join(f"{k} = ?" for k in updates)
        # Values in the same order as the dict keys (dicts keep insertion order).
        params = list(updates.values()) + [book_id]
        conn = self._get_connection()
        # The f-string only inserts column NAMES, and those come from the
        # `allowed` whitelist above, never from user input. All VALUES go
        # through `?` placeholders. So this dynamic SQL is injection-safe.
        # TODO: keep this pattern (whitelist names + ? values) for any new
        # dynamic SQL; never f-string a value.
        conn.execute(f"UPDATE books SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", params)
        conn.commit()
    
    def get_book(self, book_id: int) -> Optional[Dict]:
        """Get book by ID.

        Args:
            book_id: books.id.

        Returns:
            The row as a dict (column name -> value), or None if not found.
            `Optional[Dict]` in the signature means "Dict or None".
        """
        conn = self._get_connection()
        # `(book_id,)` — the trailing comma makes a 1-element tuple;
        # `(book_id)` would just be the int in parentheses.
        cursor = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_book_by_title(self, title: str) -> Optional[Dict]:
        """Get book by exact title (first match if several share it).

        Used by the extract/translate flows to detect an already-added book.

        Args:
            title: exact display title (case- and accent-sensitive).

        Returns:
            Book dict or None.

        TODO: titles are not unique and the user can edit them; match books
        by book_url or id instead (PLAN.md).
        """
        conn = self._get_connection()
        cursor = conn.execute("SELECT * FROM books WHERE title = ?", (title,))
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def update_book_status(self, book_id: int, download_status: str = None, 
                          total_chapters: int = None, 
                          downloaded_chapters: int = None):
        """Book progress and status tracking updates. Any omitted field is left
        untouched (download_status is only changed when explicitly passed).

        Args:
            book_id: books.id.
            download_status: new status string, or None to keep it.
            total_chapters / downloaded_chapters: new counts, or None to keep.
                `is not None` (not just truthiness) so 0 is a valid value.

        Side effects: UPDATE books (always bumps updated_at) + commit.
        """
        # Build the SET list piece by piece; only fixed column names are ever
        # put into the SQL text, values go through `?`.
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
        Add a chapter to a book (no content yet; status uses the schema default).

        Args:
            book_id: owning books.id.
            chapter_order: 1-based position in the book (used for ORDER BY).
            chapter_title: title from the chapter list.
            chapter_url: site-relative URL ("/truyen/..."), see _run_migrations.

        Returns:
            ID of the newly inserted chapter

        Side effects: INSERT into `chapters` + commit.
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
        Add a chapter to a book, optionally storing its content in one step.

        Args:
            book_id, chapter_order, chapter_title, chapter_url: as add_chapter().
            chapter_content: text for chapters.chapter_content, or None.
                The translate import (api/translate.py) uses this to store the
                raw source-language text parsed from an uploaded file, with a
                fake "translate://<book_id>/<order>" chapter_url.

        Returns:
            ID of the newly inserted chapter

        Side effects: INSERT into `chapters` + commit.
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
        """Store the content for a chapter in `chapters.chapter_content`.

        For downloaded books this is the globally-cleaned text as <p>
        paragraphs joined by "\\n\\n". Per-book corrections must NOT be baked
        in here; they are applied at DOCX render time.
        (Translations go to update_chapter_translated_content instead.)

        Args:
            chapter_id: chapters.id.
            chapter_content: the text to store.

        Side effects: UPDATE chapters + commit.
        """
        conn = self._get_connection()
        conn.execute("UPDATE chapters SET chapter_content = ? WHERE id = ?", (chapter_content, chapter_id))
        conn.commit()

    def update_chapter_title(self, chapter_id: int, chapter_title: str):
        """Store the cleaned page title for a chapter (used when exporting the DOCX).

        Args:
            chapter_id: chapters.id.
            chapter_title: new title text.

        Side effects: UPDATE chapters + commit.
        """
        conn = self._get_connection()
        conn.execute("UPDATE chapters SET chapter_title = ? WHERE id = ?", (chapter_title, chapter_id))
        conn.commit()

    def update_chapter_translated_content(self, chapter_id: int, translated_content: str):
        """Store the Vietnamese translation for a chapter.

        Format: "<viet_title>\\n<viet_body>" so the DOCX exporter can split the
        heading from the body without a separate column. Corrections and
        global Text Cleaning are NOT applied here — both are applied at DOCX
        export time.

        Args:
            chapter_id: chapters.id.
            translated_content: raw translation in the format above.

        Side effects: UPDATE chapters + commit.
        """
        conn = self._get_connection()
        conn.execute("UPDATE chapters SET translated_content = ? WHERE id = ?", (translated_content, chapter_id))
        conn.commit()

    def get_book_corrections(self, book_id: int) -> List[Dict]:
        """Get all corrections for a book, ordered by sort_order.

        Args:
            book_id: books.id.

        Returns:
            List of book_corrections rows as dicts (includes disabled ones;
            `id` breaks ties between equal sort_order values).
        """
        conn = self._get_connection()
        rows = conn.execute("""
            SELECT * FROM book_corrections WHERE book_id = ?
            ORDER BY sort_order, id
        """, (book_id,)).fetchall()
        # List comprehension: convert each sqlite3.Row into a plain dict.
        return [dict(r) for r in rows]

    def set_book_corrections(self, book_id: int, corrections: List[Dict]):
        """Replace all corrections for a book.
        Each item: {'find_text': str, 'replace_text': str, 'enabled': bool}

        Items with an empty/whitespace find_text are skipped. sort_order is
        taken from the list position. `enabled` defaults to True if missing.

        Args:
            book_id: books.id.
            corrections: the full new list (anything not in it is deleted).

        Side effects: DELETE + INSERTs on book_corrections, one commit at the
        end (so the replace is all-or-nothing within this connection).
        """
        conn = self._get_connection()
        conn.execute("DELETE FROM book_corrections WHERE book_id = ?", (book_id,))
        # enumerate() yields (index, item) pairs: 0, first; 1, second; ...
        for i, c in enumerate(corrections):
            # `x or ''` turns None into '' so .strip() never fails on None.
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
        """Get all chapters for a book, optionally filtered by status.

        Args:
            book_id: books.id.
            status: e.g. 'pending' / 'completed' / 'failed'; None or '' = all.

        Returns:
            List of chapter dicts in chapter_order (includes content columns,
            so this can be large for big books).
        """
        conn = self._get_connection()
        
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
    
    def update_chapter_status(self, chapter_id: int, status: str, 
                             file_path: str = None, 
                             error_message: str = None):
        """Update chapter download status.

        Args:
            chapter_id: chapters.id.
            status: new download_status. 'completed' also stamps downloaded_at
                (and file_path if given); 'failed' also stores error_message
                (if given). Other statuses only change the status.
            file_path: optional, only used with 'completed'.
            error_message: optional, only used with 'failed'.

        Side effects: UPDATE chapters + commit. Column names in the f-string
        are fixed literals; values use `?`, so it is injection-safe.
        """
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
        resume them into the main DOCX. Returns how many chapters were reset.

        Args:
            book_id: books.id.

        Returns:
            int — cursor.rowcount is the number of rows the UPDATE changed.

        Side effects: UPDATE chapters + commit.
        """
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
        """Get application setting value.

        Args:
            key: application_settings.key (e.g. 'domain', 'cookie_express.sid').
            default: returned when the key does not exist.

        Returns:
            The stored value (str), or `default`. Note an existing key with an
            empty value returns '' (not `default`); callers use `or` for that.
        """
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT value FROM application_settings WHERE key = ?", 
            (key,)
        )
        row = cursor.fetchone()
        return row[0] if row else default
    
    def update_setting(self, key: str, value: str):
        """Create or overwrite one application setting.

        Args:
            key: setting name.
            value: new value (stored as text).

        Side effects: INSERT OR REPLACE into application_settings + commit.
        "INSERT OR REPLACE" = upsert: if `key` (the primary key) already
        exists, the old row is deleted and the new one inserted.

        TODO: secrets such as 'account_password' (saved by services/login.py)
        and cookies are stored here in plaintext; encrypt them or use the OS
        keyring.
        """
        conn = self._get_connection()
        conn.execute("""
            INSERT OR REPLACE INTO application_settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """, (key, value))
        conn.commit()
    
    # === SITE ACCOUNT OPERATIONS ===

    def get_site_accounts(self) -> List[Dict]:
        """List the extra site accounts, oldest first (= fallback order).

        Returns:
            list of dicts with id, username, password, cookies (JSON text), created_at.
        """
        conn = self._get_connection()
        # dict(row) works because _get_connection() sets row_factory = sqlite3.Row.
        return [dict(r) for r in conn.execute("SELECT * FROM site_accounts ORDER BY id")]

    def add_site_account(self, username: str, password: str) -> int:
        """Insert an extra site account (no cookies until it is logged in).

        Returns: the new row id. Side effects: INSERT + commit.
        """
        conn = self._get_connection()
        cur = conn.execute("INSERT INTO site_accounts (username, password) VALUES (?, ?)",
                           (username, password))
        conn.commit()
        return cur.lastrowid

    def set_site_account_cookies(self, account_id: int, cookies_json: str):
        """Store the cookies (JSON text) harvested by auto-login for one account.

        Side effects: UPDATE + commit.
        """
        conn = self._get_connection()
        conn.execute("UPDATE site_accounts SET cookies = ? WHERE id = ?", (cookies_json, account_id))
        conn.commit()

    def delete_site_account(self, account_id: int) -> bool:
        """Delete one extra site account. Returns True if a row was deleted."""
        conn = self._get_connection()
        cur = conn.execute("DELETE FROM site_accounts WHERE id = ?", (account_id,))
        conn.commit()
        return cur.rowcount > 0

    # === TAG OPERATIONS ===

    def add_tag(self, name: str) -> int:
        """Get or create a tag by name, return its id.

        Args:
            name: exact tag name (tags.name is UNIQUE).

        Returns:
            Existing or new tags.id.

        Side effects: may INSERT into tags + commit.
        """
        conn = self._get_connection()
        row = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
        if row:
            return row[0]
        cursor = conn.execute("INSERT INTO tags (name) VALUES (?)", (name,))
        conn.commit()
        return cursor.lastrowid

    def set_book_tags(self, book_id: int, tag_names: List[str]):
        """Replace all tags for a book with the given list of tag names.

        Args:
            book_id: books.id.
            tag_names: names to attach; blank names are skipped, unknown
                names are created as new tags.

        Side effects: DELETE/INSERT on book_tags, may INSERT into tags; commits.
        Unused tags are left in `tags` (they just show book_count 0).
        """
        conn = self._get_connection()
        conn.execute("DELETE FROM book_tags WHERE book_id = ?", (book_id,))
        # INSERT OR IGNORE below skips duplicates (same tag listed twice)
        # instead of raising on the (book_id, tag_id) primary key.
        # Note: add_tag() commits, which also commits the DELETE above early.
        for name in tag_names:
            name = name.strip()
            if name:
                tag_id = self.add_tag(name)
                conn.execute("INSERT OR IGNORE INTO book_tags (book_id, tag_id) VALUES (?, ?)", (book_id, tag_id))
        conn.commit()

    def get_book_tags(self, book_id: int) -> list[str]:
        """Get all tag names for a book.

        Args:
            book_id: books.id.

        Returns:
            Alphabetical list of tag name strings (`list[str]` is the
            built-in generic form of typing.List[str]).
        """
        conn = self._get_connection()
        rows = conn.execute("""
            SELECT t.name FROM tags t
            JOIN book_tags bt ON bt.tag_id = t.id
            WHERE bt.book_id = ?
            ORDER BY t.name
        """, (book_id,)).fetchall()
        return [r[0] for r in rows]

    def get_all_tags(self) -> list[dict]:
        """List all tags with book count.

        Returns:
            List of {'id', 'name', 'book_count'} dicts sorted by name.
            LEFT JOIN keeps tags with no books (count 0).
        """
        conn = self._get_connection()
        rows = conn.execute("""
            SELECT t.id, t.name, COUNT(bt.book_id) as book_count
            FROM tags t
            LEFT JOIN book_tags bt ON bt.tag_id = t.id
            GROUP BY t.id
            ORDER BY t.name
        """).fetchall()
        return [dict(r) for r in rows]

    # === TEXT CLEANING RULES OPERATIONS ===

    def get_text_cleaning_rules(self, enabled_only: bool = False) -> List[Dict]:
        """Get all text cleaning rules, ordered by sort_order.

        Args:
            enabled_only: True = only rules with enabled = 1 (what
                TextCleaner applies); False = all (for the settings page).

        Returns:
            List of text_cleaning_rules rows as dicts.
        """
        conn = self._get_connection()
        if enabled_only:
            rows = conn.execute("SELECT * FROM text_cleaning_rules WHERE enabled = 1 ORDER BY sort_order").fetchall()
        else:
            rows = conn.execute("SELECT * FROM text_cleaning_rules ORDER BY sort_order").fetchall()
        return [dict(r) for r in rows]

    def add_text_cleaning_rule(self, rule_type: str, match_type: str, find_text: str,
                               replace_text: str = '', enabled: int = 1,
                               sort_order: int = None, description: str = '') -> int:
        """Insert a global text-cleaning rule.

        Args:
            rule_type: 'remove' or 'replace' (CHECK constraint in the table).
            match_type: 'simple' (plain substring) or 'regex'.
            find_text: text or regex pattern to find.
            replace_text: replacement (ignored for 'remove').
            enabled: 1 or 0.
            sort_order: position; None = append after the current last rule.
            description: free-text label for the UI.

        Returns:
            The new rule's id.

        Raises:
            sqlite3.IntegrityError: rule_type/match_type outside allowed values.

        Side effects: INSERT into text_cleaning_rules + commit.
        """
        conn = self._get_connection()
        if sort_order is None:
            # COALESCE(x, -1) returns -1 when MAX() is NULL (empty table),
            # so the first rule gets sort_order 0.
            row = conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM text_cleaning_rules").fetchone()
            sort_order = row[0]
        conn.execute("""
            INSERT INTO text_cleaning_rules (rule_type, match_type, find_text, replace_text, enabled, sort_order, description)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (rule_type, match_type, find_text, replace_text, enabled, sort_order, description))
        conn.commit()
        # Same value as cursor.lastrowid; works because the connection is
        # per-thread, so no other insert can sneak in between.
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def update_text_cleaning_rule(self, rule_id: int, **kwargs) -> bool:
        """Update some fields of a text-cleaning rule.

        Args:
            rule_id: text_cleaning_rules.id.
            **kwargs: column=value pairs; keys outside `allowed` are ignored.

        Returns:
            False if no allowed field was given, else True (also True when
            rule_id does not exist — the UPDATE just matches 0 rows).

        Side effects: UPDATE text_cleaning_rules + commit. As in
        update_book_info, the f-string only injects whitelisted column names,
        values go through `?`, so it is injection-safe.
        """
        allowed ={'rule_type', 'match_type', 'find_text', 'replace_text', 'enabled', 'sort_order', 'description'}
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
        """Delete a text-cleaning rule.

        Args:
            rule_id: text_cleaning_rules.id.

        Returns:
            Always True (even if the id did not exist).
            TODO: return cursor.rowcount > 0 so the API can answer 404.

        Side effects: DELETE + commit. Remaining sort_order values may have
        a gap; that is harmless because only their order matters.
        """
        conn = self._get_connection()
        conn.execute("DELETE FROM text_cleaning_rules WHERE id = ?", (rule_id,))
        conn.commit()
        return True

    def reorder_text_cleaning_rule(self, rule_id: int, new_order: int):
        """Move a rule to a new position and shift others accordingly.

        Algorithm: load ids in current order, remove `rule_id` from the list,
        insert it at `new_order`, then rewrite every rule's sort_order as
        0, 1, 2, ... (this also closes any gaps).

        Args:
            rule_id: rule to move. Unknown id = silently does nothing.
            new_order: 0-based target index; clamped into the valid range.

        Side effects: one UPDATE per rule + a single commit.
        """
        conn = self._get_connection()
        rules = conn.execute("SELECT id, sort_order FROM text_cleaning_rules ORDER BY sort_order").fetchall()
        # TODO: `orders` is never used; safe to delete.
        orders = [r['sort_order'] for r in rules]
        ids = [r['id'] for r in rules]
        if rule_id not in ids:
            return
        old_idx = ids.index(rule_id)
        # Clamp: max(0, min(last_index, x)) keeps x within [0, last_index].
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
        (That is why created_at is passed explicitly: SQLite's
        CURRENT_TIMESTAMP default is UTC.)

        Other args (all optional, stored as NULL when None):
            session_type: which browser session/account made the request.
            domain, url: what was requested.
            book_id, chapter_id: related rows (not foreign-keyed).
            detail / error: free text; duration_ms: elapsed time.

        Side effects: INSERT into request_logs + commit.
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

        Args:
            start / end: inclusive 'YYYY-MM-DD' bounds (compared with SQLite
                date(), which drops the time part).
            request_type, status, session_type, domain: exact-match filters.
            Any falsy filter (None or '') is skipped.
            prefix: table alias to qualify columns with (e.g. 'r.' when the query
                joins another table that also has a created_at column).

        Returns:
            (where_sql_without_WHERE, params) — e.g.
            ("date(created_at) >= date(?) AND status = ?", ['2026-01-01', 'failed']).
            The string is "" when no filter is set. Only fixed column names
            (+ the code-supplied prefix) go into the SQL text; filter values
            are always `?` params, so it is injection-safe.
        """
        # Tuple unpacking: two new empty lists in one line.
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
        """Aggregate request-log stats over a date range (inclusive).

        Args:
            Same filters as _build_log_filter().

        Returns:
            dict with:
              total: int row count;
              by_status / by_type / by_session: {value: count} dicts;
              by_day: [{'day', 'total', 'success', 'failed'}, ...] sorted by day.

        Runs 5 aggregate queries with the same WHERE clause.
        """
        conn = self._get_connection()
        where, params = self._build_log_filter(start, end, request_type, status, session_type, domain)
        where_sql = ("WHERE " + where) if where else ""
        total = conn.execute(f"SELECT COUNT(*) FROM request_logs {where_sql}", params).fetchone()[0]
        # Dict comprehensions over the cursor (a cursor is iterable row by
        # row). SUM(CASE WHEN ... THEN 1 ELSE 0 END) below counts matching rows.
        by_status ={r['status']: r['n'] for r in conn.execute(
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
        """Paginated request log entries, newest first.

        Args:
            Same filters as _build_log_filter(), plus:
            page: 1-based page number.
            per_page: rows per page.

        Returns:
            {'total', 'page', 'per_page', 'total_pages', 'logs'} where each log
            dict also has 'book_title' (NULL if the book was deleted —
            LEFT JOIN keeps the log row).
        """
        conn = self._get_connection()
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
            # `//` is integer (floor) division; (a + b - 1) // b rounds UP.
            # max(1, ...) so an empty result still reports 1 page.
            "total_pages": max(1, (total + per_page - 1) // per_page),
            "logs": [dict(r) for r in rows],
        }

    def get_daily_chapter_counts(self, start_day: str = None, end_day: str = None,
                                 session_type: str = None) -> List[Dict]:
        """Daily chapter-request counts (success/failed) for a date range,
        grouped by session_type. Used for the daily-limit estimate.

        Args:
            start_day / end_day: inclusive 'YYYY-MM-DD' bounds, optional.
            session_type: optional exact filter.

        Returns:
            [{'day', 'session_type', 'total', 'success', 'failed'}, ...]
            sorted by day — one row per (day, session_type) pair.

        TODO: could reuse _build_log_filter(request_type='chapter', ...)
        instead of duplicating the condition building.
        """
        conn = self._get_connection()
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
        """Distinct values present in the log (for filter dropdowns).

        Returns:
            {'request_types', 'statuses', 'session_types', 'domains'}, each a
            sorted list of non-empty distinct values.
        """
        conn = self._get_connection()
        # Nested helper function; it can use `conn` from the enclosing scope
        # (a closure). `col` is always one of the four literals below, never
        # user input, so the f-string SQL is safe.
        def distinct(col):
            """Return sorted non-empty distinct values of request_logs.<col>."""
            return [r[0] for r in conn.execute(
                f"SELECT DISTINCT {col} FROM request_logs WHERE {col} IS NOT NULL AND {col} != '' ORDER BY {col}").fetchall()]
        return {
            "request_types": distinct("request_type"),
            "statuses": distinct("status"),
            "session_types": distinct("session_type"),
            "domains": distinct("domain"),
        }

    # === UTILITY METHODS ===
    
    def execute_query(self, query: str, params: tuple = ()) -> List[Dict]:
        """Execute custom query and return results as list of dicts.

        Args:
            query: SQL text with `?` placeholders. Must come from code, never
                from user input.
            params: values for the placeholders.

        Returns:
            All result rows as dicts ([] for statements returning no rows).

        Note: does NOT commit, so it is meant for SELECTs; a write would stay
        uncommitted until some later commit on this thread's connection.
        """
        conn = self._get_connection()
        cursor = conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

# Global database instance.
# Created once, the first time any module imports app.database (Python caches
# imported modules, so this line runs only once per process). Importing this
# module therefore opens the DB and runs migrations as a side effect.
db = NovelDatabase()

def get_database() -> NovelDatabase:
    """Get global database instance (the shared singleton above).

    Returns:
        The process-wide NovelDatabase. Safe to call from any thread; each
        thread still gets its own sqlite3 connection internally.
    """
    return db