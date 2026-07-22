import sqlite3
import os
import threading
import json
from typing import Dict, Optional
from datetime import datetime, timezone

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
    attachment_url TEXT,
    attachment_mime_type TEXT,
    attachment_duration REAL,
    attachment_local_path TEXT,
    attachment_state TEXT,
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
            self.cleanup_expired_action_metadata()
            self.cleanup_superseded_approval_metadata()
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
            conn.execute(
                "UPDATE messages SET quick_responses = NULL, commands = NULL "
                "WHERE request_id IS NULL "
                "AND (quick_responses IS NOT NULL OR commands IS NOT NULL)"
            )
        if "attachment_url" not in columns:
            conn.execute("ALTER TABLE messages ADD COLUMN attachment_url TEXT")
        if "attachment_mime_type" not in columns:
            conn.execute("ALTER TABLE messages ADD COLUMN attachment_mime_type TEXT")
        if "attachment_duration" not in columns:
            conn.execute("ALTER TABLE messages ADD COLUMN attachment_duration REAL")
        if "attachment_local_path" not in columns:
            conn.execute("ALTER TABLE messages ADD COLUMN attachment_local_path TEXT")
        if "attachment_state" not in columns:
            conn.execute("ALTER TABLE messages ADD COLUMN attachment_state TEXT")
        conn.commit()

    def record_message(self, bare_jid: str, body: str, direction: str,
                       timestamp: str, mam_id: Optional[str] = None,
                       quick_responses=None, commands=None,
                       request_id: Optional[str] = None,
                       attachment_url: Optional[str] = None,
                       attachment_mime_type: Optional[str] = None,
                       attachment_duration: Optional[float] = None,
                       attachment_local_path: Optional[str] = None,
                       attachment_state: Optional[str] = None):
        conn = self.get_connection()
        quick_json = self._encode_metadata(quick_responses)
        commands_json = self._encode_metadata(commands)
        if direction == "in":
            self._resolve_prior_approvals(
                conn, bare_jid, body, quick_responses, commands)
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
            "(bare_jid, body, direction, timestamp, mam_id, quick_responses, commands, request_id, "
            "attachment_url, attachment_mime_type, attachment_duration, attachment_local_path, attachment_state) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (bare_jid, body, direction, timestamp, mam_id, quick_json, commands_json, request_id,
             attachment_url, attachment_mime_type, attachment_duration, attachment_local_path, attachment_state),
        )
        conn.commit()
        return cursor.rowcount > 0

    def _resolve_prior_approvals(self, conn, bare_jid: str, body: str,
                                 quick_responses=None, commands=None,
                                 exclude_id=None) -> int:
        """Clear older approval actions once a later inbound message exists.

        OpenClaw allows only one pending exec approval per session. Therefore
        a new approval supersedes the previous one, while any ordinary agent
        reply proves the previous wait has completed. Messages stay intact;
        only their obsolete interactive metadata is removed.
        """
        current_actions = list(quick_responses or []) + list(commands or [])
        current_is_approval = (self._actions_look_like_approval(current_actions)
                               or (bool(current_actions)
                                   and self._body_looks_like_approval(body)))
        rows = conn.execute(
            "SELECT id, body, quick_responses, commands FROM messages "
            "WHERE bare_jid = ? AND direction = 'in' "
            "AND (quick_responses IS NOT NULL OR commands IS NOT NULL)",
            (bare_jid,),
        ).fetchall()
        stale_ids = []
        for row in rows:
            if exclude_id is not None and row["id"] == exclude_id:
                continue
            actions = (self._decode_metadata(row["quick_responses"])
                       + self._decode_metadata(row["commands"]))
            if (self._actions_look_like_approval(actions)
                    or (bool(actions)
                        and self._body_looks_like_approval(row["body"]))):
                stale_ids.append(row["id"])
        # A later approval and a later ordinary response both resolve all
        # earlier approvals. Empty protocol/status stanzas never reach here.
        if not stale_ids or (not current_is_approval and not str(body or "").strip()):
            return 0
        placeholders = ",".join("?" for _ in stale_ids)
        cursor = conn.execute(
            f"UPDATE messages SET quick_responses = NULL, commands = NULL "
            f"WHERE id IN ({placeholders})",
            stale_ids,
        )
        return cursor.rowcount

    def cleanup_superseded_approval_metadata(self) -> int:
        """Reconcile cached/MAM cards with later messages in each chat."""
        conn = self._thread_local.conn
        rows = conn.execute(
            "SELECT id, bare_jid, body, direction, quick_responses, commands "
            "FROM messages ORDER BY bare_jid, timestamp, id"
        ).fetchall()
        pending_by_jid = {}
        stale_ids = []
        for row in rows:
            if row["direction"] != "in" or not str(row["body"] or "").strip():
                continue
            actions = (self._decode_metadata(row["quick_responses"])
                       + self._decode_metadata(row["commands"]))
            is_approval = (self._actions_look_like_approval(actions)
                           or (bool(actions)
                               and self._body_looks_like_approval(row["body"])))
            previous = pending_by_jid.pop(row["bare_jid"], None)
            if previous is not None:
                stale_ids.append(previous)
            if is_approval:
                pending_by_jid[row["bare_jid"]] = row["id"]
        if not stale_ids:
            return 0
        placeholders = ",".join("?" for _ in stale_ids)
        cursor = conn.execute(
            f"UPDATE messages SET quick_responses = NULL, commands = NULL "
            f"WHERE id IN ({placeholders})",
            stale_ids,
        )
        conn.commit()
        return cursor.rowcount

    def get_recent(self, bare_jid: str, limit: int = 50, verified_only: bool = False):
        conn = self.get_connection()
        verified_clause = "AND mam_id IS NOT NULL " if verified_only else ""
        cursor = conn.execute(
            "SELECT body, direction, timestamp, quick_responses, commands, request_id, "
            "attachment_url, attachment_mime_type, attachment_duration, attachment_local_path, attachment_state FROM ("
            "SELECT body, direction, timestamp, quick_responses, commands, request_id, "
            "attachment_url, attachment_mime_type, attachment_duration, attachment_local_path, attachment_state FROM messages "
            f"WHERE bare_jid = ? {verified_clause}ORDER BY timestamp DESC LIMIT ?"
            ") ORDER BY timestamp ASC",
            (bare_jid, limit),
        )
        return [self._decode_row(row) for row in cursor.fetchall()]

    def get_before(self, bare_jid: str, before_timestamp: str, limit: int = 50):
        conn = self.get_connection()
        cursor = conn.execute(
            "SELECT body, direction, timestamp, quick_responses, commands, request_id, "
            "attachment_url, attachment_mime_type, attachment_duration, attachment_local_path, attachment_state FROM ("
            "SELECT body, direction, timestamp, quick_responses, commands, request_id, "
            "attachment_url, attachment_mime_type, attachment_duration, attachment_local_path, attachment_state FROM messages "
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

    def get_latest_timestamps(self) -> Dict[str, str]:
        """Última actividad de cada conversación, en una sola consulta.

        Para ordenar el roster por actividad reciente: hacerlo con un
        get_latest_timestamp() por contacto son N consultas cada vez que se
        repinta la lista.
        """
        conn = self.get_connection()
        rows = conn.execute(
            "SELECT bare_jid, MAX(timestamp) AS ts FROM messages GROUP BY bare_jid",
        ).fetchall()
        return {row["bare_jid"]: row["ts"] for row in rows if row["ts"]}

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

    def has_recent_outgoing(self, bare_jid: str, body: str,
                            within_seconds: int = 120) -> bool:
        """¿Ya grabamos este mensaje saliente hace nada?

        El servidor nos devuelve por carbon (XEP-0280) hasta lo que enviamos
        desde esta misma ventana, que ya quedó registrado al enviarlo. Sin este
        filtro, cada mensaje propio se duplicaría.
        """
        text = (body or '').strip()
        if not text:
            return False
        conn = self.get_connection()
        rows = conn.execute(
            "SELECT timestamp FROM messages WHERE bare_jid = ? "
            "AND direction = 'out' AND body = ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (bare_jid, text),
        ).fetchall()
        if not rows:
            return False
        recorded = self._parse_timestamp(rows[0]["timestamp"])
        if recorded is None:
            return True
        from datetime import datetime, timezone
        age = (datetime.now(timezone.utc) - recorded).total_seconds()
        return age <= within_seconds

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

    def cleanup_expired_action_metadata(self) -> int:
        """Elimina metadata de acciones que ya no pueden resolverse.

        Esto evita que caches viejas vuelvan a pintar approval cards muertas
        cada vez que se reabre el chat. No borra los mensajes, sólo las listas
        quick_responses/commands asociadas a ellos.
        """
        conn = self._thread_local.conn
        rows = conn.execute(
            "SELECT id, body, timestamp, quick_responses, commands FROM messages "
            "WHERE quick_responses IS NOT NULL OR commands IS NOT NULL"
        ).fetchall()
        changed = 0
        for row in rows:
            quick = self._filter_live_actions(
                self._decode_metadata(row["quick_responses"]),
                row["timestamp"],
                approval_fallback=self._body_looks_like_approval(row["body"]),
            )
            commands = self._filter_live_actions(
                self._decode_metadata(row["commands"]),
                row["timestamp"],
                approval_fallback=True,
            )
            quick_json = self._encode_metadata(quick)
            commands_json = self._encode_metadata(commands)
            if quick_json == row["quick_responses"] and commands_json == row["commands"]:
                continue
            conn.execute(
                "UPDATE messages SET quick_responses = ?, commands = ? WHERE id = ?",
                (quick_json, commands_json, row["id"]),
            )
            changed += 1
        if changed:
            conn.commit()
        return changed

    @classmethod
    def _filter_live_actions(cls, actions, timestamp: str, approval_fallback: bool):
        if not actions:
            return []
        return [
            action for action in actions
            if not cls._action_metadata_is_expired(action, timestamp, approval_fallback)
        ]

    @classmethod
    def _action_metadata_is_expired(cls, action, timestamp: str, approval_fallback: bool) -> bool:
        if not isinstance(action, dict):
            return True
        raw_expiry = action.get("expires_at_ms")
        if raw_expiry not in (None, ""):
            try:
                return int(raw_expiry) <= int(datetime.now(timezone.utc).timestamp() * 1000)
            except (TypeError, ValueError):
                return False
        ts = cls._parse_timestamp(timestamp)
        if ts is None:
            return False
        if ts.tzinfo is None:
            ts = ts.astimezone()
        age_ms = int(datetime.now(timezone.utc).timestamp() * 1000) - int(ts.timestamp() * 1000)
        is_approval = approval_fallback or cls._actions_look_like_approval([action])
        # OpenClaw exec.approval.waitDecision vive 30 minutos. Caducar la UI
        # antes no resuelve el pending remoto y hace imposible contestarlo.
        fallback_ms = 30 * 60 * 1000 if is_approval else 15 * 60 * 1000
        return age_ms > fallback_ms

    @staticmethod
    def _actions_look_like_approval(actions) -> bool:
        labels = {
            str(action.get("label") or action.get("name") or "").strip().lower()
            for action in actions or []
            if isinstance(action, dict)
        }
        nodes = [
            str(action.get("node") or "").lower()
            for action in actions or []
            if isinstance(action, dict)
        ]
        approval_words = ("allow", "approve", "deny", "reject", "permitir",
                          "aprobar", "denegar", "rechazar")
        if any(any(word in label for word in approval_words)
               for label in labels):
            return True
        return any("approve" in node or "approval" in node for node in nodes)

    @staticmethod
    def _body_looks_like_approval(body) -> bool:
        text = str(body or "").lower()
        return ("approval" in text or "aprobación" in text
                or "aprobacion" in text or "pending command" in text
                or "🔒" in text)

    def attach_mam_to_recent_outgoing(self, bare_jid: str, body: str,
                                      timestamp: str, mam_id: str,
                                      window_seconds: int = 120) -> bool:
        return self.attach_mam_to_recent_message(
            bare_jid, body, 'out', timestamp, mam_id, window_seconds)

    def attach_mam_to_request_id(self, bare_jid: str, request_id: str,
                                 timestamp: str, mam_id: str) -> bool:
        """Adjunta el mam_id del archivo a una fila local por su stanza id.

        Un seed de streaming guardado en vivo ya no tiene el body original
        (las correcciones XEP-0308 lo reescribieron), así que el match por
        body de attach_mam_to_recent_message nunca lo encuentra y MAM
        acababa insertando una segunda fila con el texto viejo. El request_id
        es estable entre el stanza en vivo y su copia archivada.
        """
        if not request_id or not mam_id:
            return False
        conn = self.get_connection()
        try:
            cursor = conn.execute(
                "UPDATE messages SET mam_id = ?, timestamp = ? "
                "WHERE bare_jid = ? AND request_id = ? AND direction = 'in' "
                "AND mam_id IS NULL",
                (mam_id, timestamp, bare_jid, request_id),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            # Ese mam_id ya estaba en otra fila: no es esta.
            return False
        return cursor.rowcount > 0

    def attach_mam_to_recent_message(self, bare_jid: str, body: str,
                                     direction: str, timestamp: str,
                                     mam_id: str, window_seconds: int = 120,
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
        # De los candidatos dentro de la ventana (holgada: el reloj local y
        # el del archivo pueden ir bastante desfasados) elegir el MÁS
        # CERCANO en el tiempo, no el más reciente — con mensajes idénticos
        # repetidos ("ok" dos veces), quedarse con el más nuevo asignaba el
        # mam_id a la fila equivocada y dejaba la otra como sombra.
        best_id = None
        best_delta = None
        for row in cursor.fetchall():
            candidate = self._parse_timestamp(row["timestamp"])
            if candidate is None:
                continue
            delta = abs((target - candidate).total_seconds())
            if delta > window_seconds:
                continue
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best_id = row["id"]
        if best_id is None:
            return False
        try:
            if direction == "in":
                self._resolve_prior_approvals(
                    conn, bare_jid, body, quick_responses, commands,
                    exclude_id=best_id)
            conn.execute(
                "UPDATE messages SET timestamp = ?, mam_id = ?, "
                "quick_responses = COALESCE(?, quick_responses), "
                "commands = COALESCE(?, commands), "
                "request_id = COALESCE(?, request_id) WHERE id = ?",
                (timestamp, mam_id, quick_json, commands_json,
                 request_id, best_id),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            pass
        return True

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

    def update_attachment_state(self, bare_jid: str, body: str,
                                direction: str, attachment_state: str,
                                attachment_url: Optional[str] = None):
        conn = self.get_connection()
        conn.execute(
            "UPDATE messages SET attachment_state = ?"
            + (", attachment_url = ?" if attachment_url else "")
            + " WHERE bare_jid = ? AND body = ? AND direction = ? AND id = ("
            "SELECT id FROM messages WHERE bare_jid = ? AND body = ? AND direction = ? "
            "ORDER BY timestamp DESC LIMIT 1)",
            tuple(filter(None, [
                attachment_state,
                attachment_url,
                bare_jid, body, direction,
                bare_jid, body, direction,
            ])),
        )
        conn.commit()

    def get_failed_attachments(self, bare_jid: str):
        conn = self.get_connection()
        cursor = conn.execute(
            "SELECT body, direction, timestamp, attachment_url, attachment_mime_type, "
            "attachment_duration, attachment_local_path, attachment_state FROM messages "
            "WHERE bare_jid = ? AND attachment_state = 'failed' "
            "ORDER BY timestamp DESC",
            (bare_jid,),
        )
        return [dict(row) for row in cursor.fetchall()]
