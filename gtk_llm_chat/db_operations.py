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
import sqlite_utils
from llm.migrations import migrate

_ = gettext.gettext

def debug_print(*args, **kwargs):
    logging.debug(*args, **kwargs)

class ChatHistory:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            # Use llm.user_dir() to get the directory
            user_dir = llm.user_dir()
            # Ensure the directory exists
            os.makedirs(user_dir, exist_ok=True)
            db_path = os.path.join(user_dir, "logs.db")
        self.db_path = db_path
        self._thread_local = threading.local()

        # Ensure the database schema is up-to-date using llm's migrations
        self._run_llm_migrations()

    def _run_llm_migrations(self):
        """Ensures the database schema is managed by llm's migrations."""
        db_utils = None
        try:
            db_utils = sqlite_utils.Database(self.db_path)
            # Ejecutar las migraciones de llm
            migrate(db_utils)
            logging.info(f"LLM migrations applied successfully to {self.db_path}")
        except Exception as e:
            logging.error(f"Error running LLM migrations on {self.db_path}: {e}", exc_info=True)
            # Considerar si se debe relanzar el error o manejarlo de otra forma
            # raise RuntimeError(f"Failed to apply LLM migrations: {e}") from e
        finally:
            # Asegurarse de cerrar la conexión usada por sqlite_utils
            if db_utils and hasattr(db_utils, 'conn') and db_utils.conn:
                try:
                    db_utils.conn.close()
                except Exception as close_err:
                    logging.error(f"Error closing sqlite_utils connection after migration: {close_err}", exc_info=True)


    def get_connection(self):
        """Gets a sqlite3 connection for the current thread."""
        # ... (resto del método sin cambios) ...
        if not hasattr(self._thread_local, "conn") or self._thread_local.conn is None:
            try:
                # Antes de conectar, asegurémonos que la BD y tablas existen
                # (La migración ya se corrió en __init__, pero esto es una doble verificación
                # por si algo falló silenciosamente o el archivo fue borrado)
                if not os.path.exists(self.db_path):
                     self._run_llm_migrations() # Intentar correr migraciones de nuevo si no existe

                self._thread_local.conn = sqlite3.connect(self.db_path)
                self._thread_local.conn.row_factory = sqlite3.Row
            except sqlite3.Error as e:
                # Podríamos intentar correr migraciones aquí si el error es "no such table"
                if "no such table" in str(e):
                    logging.warning(f"Table not found error on connect, attempting migrations again: {e}")
                    try:
                        self._run_llm_migrations()
                        # Reintentar la conexión después de la migración
                        self._thread_local.conn = sqlite3.connect(self.db_path)
                        self._thread_local.conn.row_factory = sqlite3.Row
                    except Exception as migrate_err:
                         logging.error(f"Failed to run migrations on 'no such table' error: {migrate_err}", exc_info=True)
                         raise ConnectionError(_(f"Error al conectar a la base de datos después de fallo de migración: {e}")) from migrate_err
                else:
                    raise ConnectionError(_(f"Error al conectar a la base de datos: {e}")) from e
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
        try:
            cursor.execute("""
                SELECT * FROM conversations
                ORDER BY id DESC
                LIMIT ? OFFSET ?
            """, (limit, offset))
        except sqlite3.OperationalError:
            return []

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

    def create_conversation_if_not_exists(self, conversation_id, name: str, model: Optional[str] = None):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO conversations (id, name, model)
                VALUES (?, ?, ?)
            """, (conversation_id, name, model))
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
                # Obtener el ID entero del fragmento
                fragment_id: int = self._get_or_create_fragment(fragment_content, source=fragment_specifier) # source podría ser mejorado
                cursor.execute(f"""
                    INSERT INTO {table_name} (response_id, fragment_id, "order")
                    VALUES (?, ?, ?)
                """, (response_id, fragment_id, order)) # Usar el ID entero
            except ValueError as e:
                print(f"Error adding fragment '{fragment_specifier}': {e}")
            except sqlite3.IntegrityError as e:
                 # Manejar posibles errores de PK duplicado si la lógica de orden/ID es incorrecta
                 print(f"Integrity error adding fragment '{fragment_specifier}' for response {response_id}: {e}")
            except sqlite3.Error as e:
                 print(f"Database error adding fragment '{fragment_specifier}': {e}")
        conn.commit()

    def _get_or_create_fragment(self, fragment_content: str, source: str = None) -> int: # &lt;-- Devuelve int
        conn = self.get_connection()
        cursor = conn.cursor()
        content_hash = hashlib.sha256(fragment_content.encode('utf-8')).hexdigest()
        cursor.execute("SELECT id FROM fragments WHERE hash = ?", (content_hash,))
        row = cursor.fetchone()
        if row:
            return row['id'] # Devuelve el ID entero existente
        else:
            # Usar datetime para el timestamp UTC como lo hace llm
            timestamp_utc = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                "INSERT INTO fragments (content, hash, source, datetime_utc) VALUES (?, ?, ?, ?)",
                (fragment_content, content_hash, source, timestamp_utc)
            )
            conn.commit()
            # Obtener el ID recién insertado
            fragment_id = cursor.lastrowid
            if fragment_id is None:
                 # Fallback por si lastrowid no funciona (raro en SQLite con PK entero)
                 cursor.execute("SELECT id FROM fragments WHERE hash = ?", (content_hash,))
                 row = cursor.fetchone()
                 if row:
                     fragment_id = row['id']
                 else:
                     # Esto no debería pasar si la inserción fue exitosa
                     raise sqlite3.Error("Could not retrieve fragment ID after insertion.")
            return fragment_id # Devuelve el nuevo ID entero

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

        # 1. Check if it's a hash (64 hex chars)
        if len(specifier) == 64 and all(c in '0123456789abcdef' for c in specifier):
            cursor.execute("SELECT content FROM fragments WHERE hash = ?", (specifier,))
            hash_row = cursor.fetchone()
            if hash_row:
                return hash_row['content']
            # If not found by hash, continue (maybe it's an alias that looks like a hash)

        # 2. Check if it's an alias
        cursor.execute("""
            SELECT fragments.content
            FROM fragment_aliases
            JOIN fragments ON fragment_aliases.fragment_id = fragments.id
            WHERE fragment_aliases.alias = ?
        """, (specifier,))
        alias_row = cursor.fetchone()
        if alias_row:
            return alias_row['content']

        # 3. Check if it's a URL or existing file path
        try:
            if specifier.startswith(('http://', 'https://')):
                 try:
                     with urllib.request.urlopen(specifier, timeout=10) as response:
                         if response.status == 200:
                             charset = response.headers.get_content_charset() or 'utf-8'
                             content = response.read().decode(charset)
                             # Considerar si guardar fragmentos de URL en la BD automáticamente
                             # self._get_or_create_fragment(content, source=specifier)
                             return content
                         else:
                             raise ValueError(f"Failed to fetch URL '{specifier}': HTTP status {response.status}")
                 except urllib.error.URLError as e:
                     raise ValueError(f"Failed to fetch URL '{specifier}': {e}") from e

            elif os.path.exists(specifier):
                 try:
                     with open(specifier, 'r', encoding='utf-8') as f:
                         content = f.read()
                         # Ensure fragment exists in DB when resolved from file
                         self._get_or_create_fragment(content, source=specifier)
                         return content
                 except UnicodeDecodeError as e:
                     raise ValueError(f"Failed to decode file '{specifier}' as UTF-8: {e}") from e
                 except PermissionError as e:
                     raise ValueError(f"Permission error accessing file '{specifier}': {e}") from e
                 except Exception as e: # Captura más genérica para errores de lectura
                     raise ValueError(f"Error reading file '{specifier}': {e}") from e

            # 4. Check if it's a fragment ID (integer)
            elif specifier.isdigit():
                try:
                    fragment_id_int = int(specifier)
                    cursor.execute("SELECT content FROM fragments WHERE id = ?", (fragment_id_int,))
                    id_row = cursor.fetchone()
                    if id_row:
                        return id_row['content']
                    # If not found by ID, fall through to treating as raw content
                except ValueError:
                    # Not a valid integer, treat as raw content below
                    pass

            # 5. If none of the above, treat as raw content
            # Consider if raw content should be automatically added as a fragment
            # self._get_or_create_fragment(specifier, source='raw') # Opcional
            return specifier

        except ValueError as e:
             # Re-raise specific ValueErrors for clarity
             logging.warning(f"ChatHistory: Could not resolve fragment '{specifier}': {e}")
             raise
        except Exception as e:
             # Catch unexpected errors during resolution
             logging.error(f"ChatHistory: Unexpected error resolving fragment '{specifier}': {e}", exc_info=True)
             raise ValueError(f"Unexpected error resolving fragment '{specifier}': {e}") from e

    def update_conversation_model(self, cid, model_id):
        """Actualiza el modelo asociado a una conversación existente."""
        if not cid:
            logging.warning("No conversation ID provided to update model.")
            return
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE conversations SET model = ? WHERE id = ?",
                (model_id, cid)
            )
            conn.commit()
