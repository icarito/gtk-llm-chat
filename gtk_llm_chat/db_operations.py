import sqlite3
from typing import List, Dict, Optional
import subprocess
import json


class ChatHistory:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            # Obtener la ruta de la base de datos usando el comando llm
            result = subprocess.run(
                ['llm', 'logs', 'path'], capture_output=True, text=True)
            self.db_path = result.stdout.strip()
        else:
            self.db_path = db_path

        try:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
        except sqlite3.Error as e:
            raise ConnectionError(f"Error al conectar a la base de datos: {e}")

    def get_conversation_history(self, conversation_id: str) -> List[Dict]:
        """Obtiene el historial completo de una conversación específica."""
        cursor = self.conn.cursor()

        # Primero verificamos si la conversación existe
        cursor.execute(
            "SELECT * FROM conversations WHERE id = ?",
            (conversation_id,)
        )
        conversation = cursor.fetchone()
        if not conversation:
            raise ValueError(
                f"No se encontró la conversación con ID: {conversation_id}")

        # Obtenemos todas las respuestas de la conversación
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
        """Obtiene el último ID de conversación."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM conversations ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_conversation(self, conversation_id: str):
        """Obtiene una conversación específica."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def set_conversation_title(self, conversation_id: str, title: str):
        """Establece el título de una conversación."""
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE conversations SET name = ? WHERE id = ?",
            (title, conversation_id)
        )
        self.conn.commit()

    def delete_conversation(self, conversation_id: str):
        """Elimina una conversación específica."""
        cursor = self.conn.cursor()
        cursor.execute(
            "DELETE FROM conversations WHERE id = ?", (conversation_id,))
        cursor.execute(
            "DELETE FROM responses WHERE conversation_id = ?",
            (conversation_id,))
        self.conn.commit()

    def get_conversations(self, limit: int, offset: int) -> List[Dict]:
        """Obtiene una lista de las últimas conversaciones"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM conversations
            ORDER BY id DESC
            LIMIT ? OFFSET ?
        """, (limit, offset))

        conversations = []
        for row in cursor.fetchall():
            conversations.append(dict(row))

        return conversations

    def close(self):
        """Cierra la conexión a la base de datos."""
        self.conn.close()
