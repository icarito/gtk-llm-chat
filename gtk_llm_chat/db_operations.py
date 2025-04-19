import sqlite3
from typing import List, Dict, Optional
import subprocess
import json
from datetime import datetime, timezone
from ulid import ULID
import gettext
_ = gettext.gettext


class ChatHistory:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            # Get the database path using the llm command
            result = subprocess.run(
                ['llm', 'logs', 'path'], capture_output=True, text=True)
            self.db_path = result.stdout.strip()
        else:
            self.db_path = db_path

        try:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
        except sqlite3.Error as e:
            raise ConnectionError(_(f"Error al conectar a la base de datos: {e}"))

    def get_conversation_history(self, conversation_id: str) -> List[Dict]:
        '''Gets the complete history of a specific conversation.'''
        cursor = self.conn.cursor()

        # First, we verify if the conversation exists
        cursor.execute(
            "SELECT * FROM conversations WHERE id = ?",
            (conversation_id,)
        )
        conversation = cursor.fetchone()
        if not conversation:
            raise ValueError(_(
                f"Conversation with ID: {conversation_id} not found"))

        # Get all responses from the conversation
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
        '''Gets the last conversation ID.'''
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM conversations ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_conversation(self, conversation_id: str):
        '''Gets a specific conversation.'''
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def set_conversation_title(self, conversation_id: str, title: str):
        '''Sets the title of a conversation.'''
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE conversations SET name = ? WHERE id = ?",
            (title, conversation_id)
        )
        self.conn.commit()

    def delete_conversation(self, conversation_id: str):
        '''Deletes a specific conversation.'''
        cursor = self.conn.cursor()
        cursor.execute(
            "DELETE FROM conversations WHERE id = ?", (conversation_id,))
        cursor.execute(
            "DELETE FROM responses WHERE conversation_id = ?",
            (conversation_id,))
        self.conn.commit()

    def get_conversations(self, limit: int, offset: int) -> List[Dict]:
        '''Gets a list of the latest conversations'''
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

    def add_history_entry(
        self, conversation_id: str, prompt: str, response_text: str,
        model_id: str
    ):
        '''Adds a new prompt/response entry to the database.'''
        if not conversation_id:
            print(_("Error: conversation_id is required to add to history."))
            return

        cursor = self.conn.cursor()
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
            self.conn.commit()
            #print(_(f"Entry added to conversation {conversation_id}"))
        except sqlite3.Error as e:
            print(_(f"Error adding entry to history: {e}"))
            self.conn.rollback()  # Undo changes in case of error

    def close(self):
        '''Closes the connection to the database.'''
        self.conn.close()

    def create_conversation_if_not_exists(self, conversation_id, name: str):
        '''Creates an entry in the conversations table if it does not exist.

        Args:
            conversation_id: The unique ID of the conversation.
            name: The initial name for the conversation.
        '''
        if not conversation_id:
            print(_("Error: conversation_id is required to create the conversation."))
            return

        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO conversations (id, name)
                VALUES (?, ?)
            """, (conversation_id, name))
            self.conn.commit()
            # Optional: verify if a row was inserted
            # if cursor.rowcount > 0:
            #     print(f"Conversation record created for ID: {conversation_id}")
        except sqlite3.Error as e:
            print(_(f"Error creating conversation record: {e}"))
            self.conn.rollback()
