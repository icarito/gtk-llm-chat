import sqlite3
import os
import threading
import json
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
    quick_responses TEXT,
    commands TEXT,
    request_id TEXT,
    UNIQUE(bare_jid, mam_id)
);
CREATE INDEX IF NOT EXISTS idx_messages_jid_ts ON messages(bare_jid, timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_jid_request ON messages(bare_jid, request_id);
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
        self._cleanup_done = False

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
            self._migrate_db()
            self.cleanup_mam_shadow_duplicates()
        return self._thread_local.conn

    def close_connection(self):
        if hasattr(self._thread_local, "conn") and self._thread_local.conn is not None:
            self._thread_local.conn.close()
            self._thread_local.conn = None

    def _migrate_db(self):
        conn = self._thread_local.conn
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(messages)").fetchall()
        }
        if "quick_responses" not in columns:
            conn.execute("ALTER TABLE messages ADD COLUMN quick_responses TEXT")
        if "commands" not in columns:
            conn.execute("ALTER TABLE messages ADD COLUMN commands TEXT")
        if "request_id" not in columns:
            conn.execute("ALTER TABLE messages ADD COLUMN request_id TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_jid_request "
                "ON messages(bare_jid, request_id)"
            )
            # Filas de antes de esta migración con quick_responses/commands
            # pendientes no tienen request_id para correlacionar con una
            # futura corrección XEP-0308 — darlas por resueltas de una vez
            # en lugar de dejarlas convivir indefinidamente con el
            # heurístico de texto+tiempo viejo.
            conn.execute(
                "UPDATE messages SET quick_responses = NULL, commands = NULL "
                "WHERE request_id IS NULL "
                "AND (quick_responses IS NOT NULL OR commands IS NOT NULL)"
            )
        conn.commit()

    def record_message(self, bare_jid: str, body: str, direction: str,
                       timestamp: str, mam_id: Optional[str] = None,
                       quick_responses=None, commands=None,
                       request_id: Optional[str] = None):
        conn = self.get_connection()
        quick_json = self._encode_metadata(quick_responses)
        commands_json = self._encode_metadata(commands)
        if mam_id:
            existing = conn.execute(
                "SELECT id FROM messages WHERE bare_jid = ? AND mam_id = ?",
                (bare_jid, mam_id),
            ).fetchone()
            if existing is not None:
                conn.execute(
                    "UPDATE messages SET "
                    "quick_responses = COALESCE(?, quick_responses), "
                    "commands = COALESCE(?, commands), "
                    "request_id = COALESCE(?, request_id) WHERE id = ?",
                    (quick_json, commands_json, request_id, existing["id"]),
                )
                conn.commit()
                return False
        cursor = conn.execute(
            "INSERT OR IGNORE INTO messages "
            "(bare_jid, body, direction, timestamp, mam_id, quick_responses, commands, request_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (bare_jid, body, direction, timestamp, mam_id, quick_json, commands_json, request_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    def get_recent(self, bare_jid: str, limit: int = 50, verified_only: bool = False):
        conn = self.get_connection()
        verified_clause = "AND mam_id IS NOT NULL " if verified_only else ""
        cursor = conn.execute(
            "SELECT body, direction, timestamp, quick_responses, commands, request_id FROM ("
            "SELECT body, direction, timestamp, quick_responses, commands, request_id FROM messages "
            f"WHERE bare_jid = ? {verified_clause}ORDER BY timestamp DESC LIMIT ?"
            ") ORDER BY timestamp ASC",
            (bare_jid, limit),
        )
        return [self._decode_row(row) for row in cursor.fetchall()]

    def get_before(self, bare_jid: str, before_timestamp: str, limit: int = 50):
        conn = self.get_connection()
        cursor = conn.execute(
            "SELECT body, direction, timestamp, quick_responses, commands, request_id FROM ("
            "SELECT body, direction, timestamp, quick_responses, commands, request_id FROM messages "
            "WHERE bare_jid = ? AND timestamp < ? "
            "ORDER BY timestamp DESC LIMIT ?"
            ") ORDER BY timestamp ASC",
            (bare_jid, before_timestamp, limit),
        )
        return [self._decode_row(row) for row in cursor.fetchall()]

    def get_latest_timestamp(self, bare_jid: str) -> Optional[str]:
        conn = self.get_connection()
        row = conn.execute(
            "SELECT timestamp FROM messages WHERE bare_jid = ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (bare_jid,),
        ).fetchone()
        return row["timestamp"] if row else None

    def get_latest_mam_id(self, bare_jid: str) -> Optional[str]:
        """Ancla RSM (`after=`) para el catch-up de MAM: pedir sólo lo
        posterior al último mensaje ya verificado por el archivo, en vez
        del overlap fijo por tiempo (ver XmppConversation.load_history_from_mam)."""
        conn = self.get_connection()
        row = conn.execute(
            "SELECT mam_id FROM messages WHERE bare_jid = ? AND mam_id IS NOT NULL "
            "ORDER BY timestamp DESC LIMIT 1",
            (bare_jid,),
        ).fetchone()
        return row["mam_id"] if row else None

    def has_outgoing_after(self, bare_jid: str, timestamp: str, bodies) -> bool:
        target = self._parse_timestamp(timestamp)
        values = [str(body) for body in bodies if body]
        if target is None or not values:
            return False
        placeholders = ",".join("?" for _ in values)
        conn = self.get_connection()
        rows = conn.execute(
            "SELECT body, timestamp FROM messages "
            f"WHERE bare_jid = ? AND direction = 'out' AND body IN ({placeholders})",
            (bare_jid, *values),
        ).fetchall()
        for row in rows:
            candidate = self._parse_timestamp(row["timestamp"])
            if candidate is not None and candidate > target:
                return True
        return False

    def update_by_request_id(self, bare_jid: str, request_id: str, body: str) -> bool:
        """Corrige el body de la pregunta original identificada por
        request_id y limpia quick_responses/commands (ya resuelta — que
        _restore_history_actions no vuelva a mostrar la card al reabrir)."""
        conn = self.get_connection()
        cursor = conn.execute(
            "UPDATE messages SET body = ?, quick_responses = NULL, commands = NULL "
            "WHERE bare_jid = ? AND request_id = ?",
            (body, bare_jid, request_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    def mark_resolved_by_request_id(self, bare_jid: str, request_id: str) -> bool:
        """Limpia quick_responses/commands sin tocar el body — usado cuando
        una señal secundaria (carbon de la propia respuesta) resuelve la
        pregunta antes de que llegue la corrección XEP-0308 con el texto
        final; a diferencia de update_by_request_id, aquí no hay texto de
        corrección que escribir."""
        conn = self.get_connection()
        cursor = conn.execute(
            "UPDATE messages SET quick_responses = NULL, commands = NULL "
            "WHERE bare_jid = ? AND request_id = ?",
            (bare_jid, request_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    def attach_mam_to_recent_outgoing(self, bare_jid: str, body: str,
                                      timestamp: str, mam_id: str,
                                      window_seconds: int = 30) -> bool:
        return self.attach_mam_to_recent_message(
            bare_jid, body, 'out', timestamp, mam_id, window_seconds)

    def attach_mam_to_recent_message(self, bare_jid: str, body: str,
                                     direction: str, timestamp: str,
                                     mam_id: str, window_seconds: int = 30,
                                     quick_responses=None, commands=None,
                                     request_id: Optional[str] = None) -> bool:
        target = self._parse_timestamp(timestamp)
        if target is None or not mam_id:
            return False
        quick_json = self._encode_metadata(quick_responses)
        commands_json = self._encode_metadata(commands)
        conn = self.get_connection()
        cursor = conn.execute(
            "SELECT id, timestamp FROM messages "
            "WHERE bare_jid = ? AND direction = ? AND body = ? AND mam_id IS NULL "
            "ORDER BY timestamp DESC LIMIT 10",
            (bare_jid, direction, body),
        )
        for row in cursor.fetchall():
            candidate = self._parse_timestamp(row["timestamp"])
            if candidate is None:
                continue
            if abs((target - candidate).total_seconds()) <= window_seconds:
                try:
                    conn.execute(
                        "UPDATE messages SET timestamp = ?, mam_id = ?, "
                        "quick_responses = COALESCE(?, quick_responses), "
                        "commands = COALESCE(?, commands), "
                        "request_id = COALESCE(?, request_id) WHERE id = ?",
                        (timestamp, mam_id, quick_json, commands_json,
                         request_id, row["id"]),
                    )
                    conn.commit()
                except sqlite3.IntegrityError:
                    pass
                return True
        return False

    def cleanup_mam_shadow_duplicates(self, window_seconds: int = 30):
        if self._cleanup_done:
            return
        self._cleanup_done = True
        conn = self.get_connection()
        rows = conn.execute(
            "SELECT id, bare_jid, body, direction, timestamp FROM messages "
            "WHERE mam_id IS NOT NULL"
        ).fetchall()
        delete_ids = []
        for row in rows:
            target = self._parse_timestamp(row["timestamp"])
            if target is None:
                continue
            shadows = conn.execute(
                "SELECT id, timestamp FROM messages "
                "WHERE bare_jid = ? AND body = ? AND direction = ? "
                "AND mam_id IS NULL",
                (row["bare_jid"], row["body"], row["direction"]),
            ).fetchall()
            for shadow in shadows:
                candidate = self._parse_timestamp(shadow["timestamp"])
                if candidate is None:
                    continue
                if abs((target - candidate).total_seconds()) <= window_seconds:
                    delete_ids.append(shadow["id"])
        if not delete_ids:
            return
        conn.executemany(
            "DELETE FROM messages WHERE id = ?",
            [(message_id,) for message_id in set(delete_ids)],
        )
        conn.commit()

    @staticmethod
    def _parse_timestamp(value):
        try:
            return datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _encode_metadata(value):
        if not value:
            return None
        return json.dumps(value)

    @staticmethod
    def _decode_metadata(value):
        if not value:
            return []
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return []
        return decoded if isinstance(decoded, list) else []

    @classmethod
    def _decode_row(cls, row):
        item = dict(row)
        item["quick_responses"] = cls._decode_metadata(item.get("quick_responses"))
        item["commands"] = cls._decode_metadata(item.get("commands"))
        return item
