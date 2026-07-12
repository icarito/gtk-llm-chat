import sqlite3
import os
import threading
from typing import Optional
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bare_jid TEXT NOT NULL,
    body TEXT NOT NULL,
    direction TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    mam_id TEXT,
    UNIQUE(bare_jid, mam_id)
);
CREATE INDEX IF NOT EXISTS idx_messages_jid_ts ON messages(bare_jid, timestamp);
"""


class XmppHistory:
    """Local cache for XMPP messages, per contact (bare JID).

    Own SQLite file, own schema — never touches llm's logs.db.
    Mirrors db_operations.py's thread-local-connection pattern
    (threading.local(), lazy connect, get_connection()), but no
    shared base class with ChatHistory.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._thread_local = threading.local()

    def _ensure_db(self):
        if not os.path.exists(self.db_path):
            conn = sqlite3.connect(self.db_path)
            conn.executescript(SCHEMA)
            conn.commit()
            conn.close()

    def get_connection(self):
        if not hasattr(self._thread_local, "conn") or self._thread_local.conn is None:
            self._ensure_db()
            self._thread_local.conn = sqlite3.connect(self.db_path)
            self._thread_local.conn.row_factory = sqlite3.Row
            self._thread_local.conn.execute("PRAGMA journal_mode=WAL")
        return self._thread_local.conn

    def close_connection(self):
        if hasattr(self._thread_local, "conn") and self._thread_local.conn is not None:
            self._thread_local.conn.close()
            self._thread_local.conn = None

    def record_message(self, bare_jid: str, body: str, direction: str,
                       timestamp: str, mam_id: Optional[str] = None):
        conn = self.get_connection()
        cursor = conn.execute(
            "INSERT OR IGNORE INTO messages (bare_jid, body, direction, timestamp, mam_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (bare_jid, body, direction, timestamp, mam_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    def get_recent(self, bare_jid: str, limit: int = 50):
        conn = self.get_connection()
        cursor = conn.execute(
            "SELECT body, direction, timestamp FROM ("
            "SELECT body, direction, timestamp FROM messages "
            "WHERE bare_jid = ? ORDER BY timestamp DESC LIMIT ?"
            ") ORDER BY timestamp ASC",
            (bare_jid, limit),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_before(self, bare_jid: str, before_timestamp: str, limit: int = 50):
        conn = self.get_connection()
        cursor = conn.execute(
            "SELECT body, direction, timestamp FROM ("
            "SELECT body, direction, timestamp FROM messages "
            "WHERE bare_jid = ? AND timestamp < ? "
            "ORDER BY timestamp DESC LIMIT ?"
            ") ORDER BY timestamp ASC",
            (bare_jid, before_timestamp, limit),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_latest_timestamp(self, bare_jid: str) -> Optional[str]:
        conn = self.get_connection()
        row = conn.execute(
            "SELECT timestamp FROM messages WHERE bare_jid = ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (bare_jid,),
        ).fetchone()
        return row["timestamp"] if row else None

    def update_last_body(self, bare_jid: str, body: str):
        conn = self.get_connection()
        latest = conn.execute(
            "SELECT id FROM messages WHERE bare_jid = ? AND direction = 'in' "
            "ORDER BY timestamp DESC LIMIT 1",
            (bare_jid,),
        ).fetchone()
        if latest is None:
            return
        conn.execute(
            "UPDATE messages SET body = ? WHERE id = ?",
            (body, latest["id"]),
        )
        conn.commit()

    def attach_mam_to_recent_outgoing(self, bare_jid: str, body: str,
                                      timestamp: str, mam_id: str,
                                      window_seconds: int = 30) -> bool:
        target = self._parse_timestamp(timestamp)
        if target is None or not mam_id:
            return False
        conn = self.get_connection()
        cursor = conn.execute(
            "SELECT id, timestamp FROM messages "
            "WHERE bare_jid = ? AND direction = 'out' AND body = ? AND mam_id IS NULL "
            "ORDER BY timestamp DESC LIMIT 10",
            (bare_jid, body),
        )
        for row in cursor.fetchall():
            candidate = self._parse_timestamp(row["timestamp"])
            if candidate is None:
                continue
            if abs((target - candidate).total_seconds()) <= window_seconds:
                conn.execute(
                    "UPDATE messages SET timestamp = ?, mam_id = ? WHERE id = ?",
                    (timestamp, mam_id, row["id"]),
                )
                conn.commit()
                return True
        return False

    @staticmethod
    def _parse_timestamp(value):
        try:
            return datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
