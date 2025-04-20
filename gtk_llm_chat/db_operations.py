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
import threading  # Import the threading module

_ = gettext.gettext


class ChatHistory:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            result = subprocess.run(
                ['llm', 'logs', 'path'], capture_output=True, text=True)
            self.db_path = result.stdout.strip()
        else:
            self.db_path = db_path
        self._thread_local = threading.local()  # Thread-local storage

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
        # ... (rest of your code, using 'cursor' and 'conn')
        # ...
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

    def set_conversation_title(self, conversation_id: str, title: str):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE conversations SET name = ? WHERE id = ?",
            (title, conversation_id)
        )
        conn.commit()

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
        # ... (rest of your code, using 'cursor' and 'conn')
        # ...
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
            conn.rollback()  # Undo changes in case of error

    def create_conversation_if_not_exists(self, conversation_id, name: str):
        conn = self.get_connection()
        cursor = conn.cursor()
        # ... (rest of your code, using 'cursor' and 'conn')
        # ...
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
        # ... (rest of your code, using 'cursor' and 'conn')
        # ...
        for order, fragment_content in enumerate(fragments):
            fragment_id = self._get_or_create_fragment(fragment_content)
            cursor.execute(f"""
                INSERT INTO {table_name} (response_id, fragment_id, "order")
                VALUES (?, ?, ?)
            """, (response_id, fragment_id, order))
        conn.commit()

    def _get_or_create_fragment(self, fragment_content: str) -> str:
        conn = self.get_connection()
        cursor = conn.cursor()
        # ... (rest of your code, using 'cursor' and 'conn')
        # ...
        cursor.execute("SELECT id FROM fragments WHERE content = ?", (fragment_content,))
        row = cursor.fetchone()
        if row:
            return row['id']
        else:
            fragment_id = str(ULID()).lower()
            cursor.execute("INSERT INTO fragments (id, content) VALUES (?, ?)", (fragment_id, fragment_content))
            conn.commit()
            return fragment_id

    def get_fragments_for_response(self, response_id: str, table_name: str) -> List[str]:
        conn = self.get_connection()
        cursor = conn.cursor()
        # ... (rest of your code, using 'cursor' and 'conn')
        # ...
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
            specifier: The fragment specifier (URL, file path, or raw content).

        Returns:
            The content of the fragment.

        Raises:
            ValueError: If the specifier is invalid or the fragment cannot be resolved.
        """
        specifier = specifier.strip()  # Remove leading/trailing whitespace

        if not specifier:
            raise ValueError("Empty fragment specifier")

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
                        return f.read()
                except UnicodeDecodeError as e:
                    raise ValueError(f"Failed to decode file '{specifier}' as UTF-8: {e}") from e
                except PermissionError as e:
                    raise ValueError(f"Permission error accessing file '{specifier}': {e}") from e
            else:
                # Assume it's raw content
                return specifier
        except ValueError as e:
            print(f"ChatHistory: Error resolving fragment '{specifier}': {e}")
            raise
        except Exception as e:
            print(f"ChatHistory: Unexpected error resolving fragment '{specifier}': {e}")
            raise ValueError(f"Unexpected error resolving fragment '{specifier}': {e}") from e

