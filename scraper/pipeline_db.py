# scraper/pipeline_db.py
import sqlite3
from pathlib import Path


_DEFAULT_DB = Path("data/pipeline.db")


class PipelineDB:
    """SQLite-backed cross-step status tracker for crawl and indexing progress."""

    def __init__(self, db_path: Path = _DEFAULT_DB):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pages (
                    url TEXT PRIMARY KEY,
                    domain TEXT,
                    page_type TEXT,
                    word_count INTEGER DEFAULT 0,
                    scraped_at TEXT,
                    cleaned_at TEXT,
                    indexed_at TEXT,
                    chunk_count INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'scraped'
                )
            """)

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def upsert_scraped(self, url: str, domain: str, page_type: str,
                       word_count: int, scraped_at: str) -> None:
        """Record a successfully scraped page."""
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO pages (url, domain, page_type, word_count, scraped_at, status)
                VALUES (?, ?, ?, ?, ?, 'scraped')
                ON CONFLICT(url) DO UPDATE SET
                    page_type=excluded.page_type,
                    word_count=excluded.word_count,
                    scraped_at=excluded.scraped_at,
                    status='scraped'
            """, (url, domain, page_type, word_count, scraped_at))

    def mark_cleaned(self, url: str, cleaned_at: str, chunk_count: int) -> None:
        """Mark a page as cleaned."""
        with self._conn() as conn:
            conn.execute("""
                UPDATE pages SET cleaned_at=?, chunk_count=?, status='cleaned'
                WHERE url=?
            """, (cleaned_at, chunk_count, url))

    def mark_indexed(self, url: str, indexed_at: str) -> None:
        """Mark a page as indexed into vector DB."""
        with self._conn() as conn:
            conn.execute("""
                UPDATE pages SET indexed_at=?, status='indexed'
                WHERE url=?
            """, (indexed_at, url))

    def get_pages(self, domain: str | None = None) -> list[dict]:
        """Return all pages, optionally filtered by domain."""
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            if domain:
                rows = conn.execute(
                    "SELECT * FROM pages WHERE domain=? ORDER BY scraped_at DESC",
                    (domain,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM pages ORDER BY scraped_at DESC"
                ).fetchall()
        return [dict(row) for row in rows]

    def get_stats(self, domain: str | None = None) -> dict:
        """Return counts by status."""
        pages = self.get_pages(domain)
        return {
            "total": len(pages),
            "scraped": sum(1 for p in pages if p["status"] == "scraped"),
            "cleaned": sum(1 for p in pages if p["status"] == "cleaned"),
            "indexed": sum(1 for p in pages if p["status"] == "indexed"),
        }
