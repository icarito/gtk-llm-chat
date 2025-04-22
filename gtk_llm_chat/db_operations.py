import sqlite3
from typing import List, Dict, Optional
import subprocess
import json
from datetime import datetime, timezone
from ulid import ULID
import gettext
import os
import urllib.request
import urllib.error
import threading
import hashlib
import logging
import llm

_ = gettext.gettext

def debug_print(*args, **kwargs):
    logging.debug(*args, **kwargs)

class ChatHistory:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            # Use llm.user_dir() to get the directory
            user_dir = llm.user_dir()
            db_path = os.path.join(user_dir, "logs.db")
        self.db_path = db_path
        self._thread_local = threading.local()

    def get_connection(self):
        """Gets a connection for the current thread."""
        if not hasattr(self._thread_local, "conn") or self._thread_local.conn is None:
            try:
                self._thread_local.conn = sqlite3.connect(self.db_path)
                self._thread_local.conn.row_factory = sqlite3.Row
            except sqlite3.Error as e:
                raise ConnectionError(_(f"Error al conectar a la base de datos: {e}"))
        return self._thread_local.conn

    def close_connection(self):
        """Closes the connection for the current thread."""
        if hasattr(self._thread_local, "conn") and self._thread_local.conn is not None:
            self._thread_local.conn.close()
            self._thread_local.conn = None

    def get_conversation_history(self, conversation_id: str) -> List[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT r.*, c.name as conversation_name
            FROM responses r
            JOIN conversations c ON r.conversation_id = c.id
            WHERE r.conversation_id = ?
            ORDER BY datetime_utc ASC
        """, (conversation_id,))

        history = []
        for row in cursor.fetchall():
            entry = dict(row)
            if entry['prompt_json']:
                entry['prompt_json'] = json.loads(entry['prompt_json'])
            if entry['response_json']:
                entry['response_json'] = json.loads(entry['response_json'])
            if entry['options_json']:
                entry['options_json'] = json.loads(entry['options_json'])
            history.append(entry)
        return history

    def get_last_conversation(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM conversations ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_conversation(self, conversation_id: str):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def _sanitize_title(self, title: str) -> str:
        """Sanitizes the conversation title."""
        # Basic sanitization: remove leading/trailing whitespace
        return title.strip()

    def set_conversation_title(self, conversation_id: str, title: str):
        """Sets the title (name) for a specific conversation."""
        sanitized_title = self._sanitize_title(title)
        query = "UPDATE conversations SET name = ? WHERE id = ?"  # Use 'name' column
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(query, (sanitized_title, conversation_id))
            conn.commit()
        finally:
            cursor.close()

    def delete_conversation(self, conversation_id: str):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM conversations WHERE id = ?", (conversation_id,))
        cursor.execute(
            "DELETE FROM responses WHERE conversation_id = ?",
            (conversation_id,))
        conn.commit()

    def get_conversations(self, limit: int, offset: int) -> List[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM conversations
            ORDER BY id DESC
            LIMIT ? OFFSET ?
        """, (limit, offset))

        conversations = []
        for row in cursor.fetchall():
            conversations.append(dict(row))

        return conversations

    def add_history_entry(
        self, conversation_id: str, prompt: str, response_text: str,
        model_id: str, fragments: List[str] = None, system_fragments: List[str] = None
    ):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            response_id = str(ULID()).lower()

            # Use datetime for UTC timestamp
            timestamp_utc = datetime.now(timezone.utc).isoformat()

            cursor.execute("""
                INSERT INTO responses
                (id, model, prompt, response, conversation_id, datetime_utc)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                response_id,
                model_id,
                prompt,
                response_text,
                conversation_id,
                timestamp_utc
            ))
            conn.commit()
            # Handle fragments
            if fragments:
                self._add_fragments(response_id, fragments, 'prompt_fragments')
            if system_fragments:
                self._add_fragments(response_id, system_fragments, 'system_fragments')

        except sqlite3.Error as e:
            print(_(f"Error adding entry to history: {e}"))
            conn.rollback()

    def create_conversation_if_not_exists(self, conversation_id, name: str):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO conversations (id, name)
                VALUES (?, ?)
            """, (conversation_id, name))
            conn.commit()
        except sqlite3.Error as e:
            print(_(f"Error creating conversation record: {e}"))
            conn.rollback()

    def _add_fragments(self, response_id: str, fragments: List[str], table_name: str):
        conn = self.get_connection()
        cursor = conn.cursor()
        for order, fragment_specifier in enumerate(fragments):
            try:
                fragment_content = self.resolve_fragment(fragment_specifier)
                fragment_id = self._get_or_create_fragment(fragment_content)
                cursor.execute(f"""
                    INSERT INTO {table_name} (response_id, fragment_id, "order")
                    VALUES (?, ?, ?)
                """, (response_id, fragment_id, order))
            except ValueError as e:
                print(f"Error adding fragment '{fragment_specifier}': {e}")
        conn.commit()

    def _get_or_create_fragment(self, fragment_content: str, source: str = None) -> str:
        conn = self.get_connection()
        cursor = conn.cursor()
        content_hash = hashlib.sha256(fragment_content.encode('utf-8')).hexdigest()
        cursor.execute("SELECT id FROM fragments WHERE hash = ?", (content_hash,))
        row = cursor.fetchone()
        if row:
            return row['id']
        else:
            cursor.execute("INSERT INTO fragments (content, hash, source) VALUES (?, ?, ?)", (fragment_content, content_hash, source))
            conn.commit()
            return hash

    def get_fragments_for_response(self, response_id: str, table_name: str) -> List[str]:
        conn = self.get_connection()
        cursor = conn.cursor()
        query = f"""
            SELECT fragments.content
            FROM {table_name}
            JOIN fragments ON {table_name}.fragment_id = fragments.id
            WHERE {table_name}.response_id = ?
            ORDER BY {table_name}."order"
        """
        cursor.execute(query, (response_id,))
        return [row['content'] for row in cursor.fetchall()]

    def resolve_fragment(self, specifier: str) -> str:
        """
        Resolves a fragment specifier to its content.

        Args:
            specifier: The fragment specifier (URL, file path, alias, or raw content).

        Returns:
            The content of the fragment.

        Raises:
            ValueError: If the specifier is invalid or the fragment cannot be resolved.
        """
        specifier = specifier.strip()

        if not specifier:
            raise ValueError("Empty fragment specifier")

        conn = self.get_connection()
        cursor = conn.cursor()

        # Check if it's a hash
        if len(specifier) == 64 and all(c in '0123456789abcdef' for c in specifier):
            cursor.execute("SELECT content FROM fragments WHERE hash = ?", (specifier,))
            hash_row = cursor.fetchone()
            if hash_row:
                return hash_row['content']
            else:
                # Check if it's a fragment id
                pass
        else:
            # Check if it's an alias
            cursor.execute("SELECT fragment_id FROM fragment_aliases WHERE alias = ?", (specifier,))
            alias_row = cursor.fetchone()
            if alias_row:
                fragment_id = alias_row['fragment_id']
                cursor.execute("SELECT content FROM fragments WHERE id = ?", (fragment_id,))
                fragment_row = cursor.fetchone()
                if fragment_row:
                    return fragment_row['content']
                else:
                    raise ValueError(f"Fragment alias '{specifier}' points to a non-existent fragment.")

            try:
                if specifier.startswith(('http://', 'https://')):
                    # Handle URL
                    try:
                        with urllib.request.urlopen(specifier, timeout=10) as response:
                            if response.status == 200:
                                charset = response.headers.get_content_charset() or 'utf-8'
                                return response.read().decode(charset)
                            else:
                                raise ValueError(f"Failed to fetch URL '{specifier}': HTTP status {response.status}")
                    except urllib.error.URLError as e:
                        raise ValueError(f"Failed to fetch URL '{specifier}': {e}") from e
                elif os.path.exists(specifier):
                    # Handle file path
                    try:
                        with open(specifier, 'r', encoding='utf-8') as f:
                            content = f.read()
                            self._get_or_create_fragment(content, specifier)
                            return content
                    except UnicodeDecodeError as e:
                        raise ValueError(f"Failed to decode file '{specifier}' as UTF-8: {e}") from e
                    except PermissionError as e:
                        raise ValueError(f"Permission error accessing file '{specifier}': {e}") from e
                else:
                    # Check if it's a fragment id
                    cursor.execute("SELECT content FROM fragments WHERE id = ?", (specifier,))
                    id_row = cursor.fetchone()
                    if id_row:
                        return id_row['content']
                    else:
                        return specifier
            except ValueError as e:
                print(f"ChatHistory: Error resolving fragment '{specifier}': {e}")
                raise
            except Exception as e:
                print(f"ChatHistory: Unexpected error resolving fragment '{specifier}': {e}")
                raise ValueError(f"Unexpected error resolving fragment '{specifier}': {e}") from e
