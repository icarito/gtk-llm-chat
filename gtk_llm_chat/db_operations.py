import sqlite3
from typing import List, Dict, Optional
import subprocess
import json

class ChatHistory:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            # Obtener la ruta de la base de datos usando el comando llm
            result = subprocess.run(['llm', 'logs', 'path'], capture_output=True, text=True)
            self.db_path = result.stdout.strip()
        else:
            self.db_path = db_path
        
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

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
            raise ValueError(f"No se encontró la conversación con ID: {conversation_id}")

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

    def close(self):
        """Cierra la conexión a la base de datos."""
        self.conn.close() 