import aiosqlite
import json
import logging
from typing import Any, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class AconPersistence:
    """
    Handles SQLite-based persistence for Acon crawl sessions.
    Allows pausing and resuming crawls across process restarts.
    """
    
    def __init__(self, db_path: str = "acon_session.db"):
        self.db_path = db_path
        self._initialized = False

    async def initialize(self):
        """Setup tables if they don't exist."""
        if self._initialized:
            return
        
        async with aiosqlite.connect(self.db_path) as db:
            # Table for found URLs and their metadata
            await db.execute("""
                CREATE TABLE IF NOT EXISTS crawl_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fetch_url TEXT UNIQUE,
                    dedup_key TEXT,
                    depth INTEGER,
                    page_type TEXT,
                    page_weight REAL,
                    status TEXT DEFAULT 'pending', -- pending, processing, completed, failed
                    last_attempt_at TEXT
                )
            """)
            
            # Table for results
            await db.execute("""
                CREATE TABLE IF NOT EXISTS page_results (
                    url TEXT PRIMARY KEY,
                    data JSON,
                    created_at TEXT
                )
            """)
            
            # Table for session metadata
            await db.execute("""
                CREATE TABLE IF NOT EXISTS session_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            
            await db.commit()
        self._initialized = True
        logger.info(f"Persistence initialized at {self.db_path}")

    async def save_queue_entry(self, fetch_url: str, dedup_key: str, depth: int, page_type: str, page_weight: float):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR IGNORE INTO crawl_queue (fetch_url, dedup_key, depth, page_type, page_weight)
                VALUES (?, ?, ?, ?, ?)
            """, (fetch_url, dedup_key, depth, page_type, page_weight))
            await db.commit()

    async def mark_status(self, fetch_url: str, status: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE crawl_queue SET status = ?, last_attempt_at = ? WHERE fetch_url = ?
            """, (status, datetime.now(timezone.utc).isoformat(), fetch_url))
            await db.commit()

    async def save_result(self, url: str, data: dict[str, Any]):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO page_results (url, data, created_at)
                VALUES (?, ?, ?)
            """, (url, json.dumps(data), datetime.now(timezone.utc).isoformat()))
            await db.commit()

    async def get_pending_entries(self) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM crawl_queue WHERE status = 'pending'") as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def clear_session(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM crawl_queue")
            await db.execute("DELETE FROM page_results")
            await db.commit()
