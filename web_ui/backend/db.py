import sqlite3
import json
import uuid
from datetime import datetime
from pathlib import Path

DB_PATH = Path("/app/data/chat_history.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Таблиця чатів
    c.execute('''CREATE TABLE IF NOT EXISTS chats
                 (id TEXT PRIMARY KEY, title TEXT, created_at TEXT)''')
    # Таблиця повідомлень
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id TEXT PRIMARY KEY, chat_id TEXT, role TEXT, content TEXT, 
                  sources TEXT, created_at TEXT,
                  FOREIGN KEY(chat_id) REFERENCES chats(id))''')
    conn.commit()
    conn.close()

def create_chat(title="Новий чат"):
    chat_id = str(uuid.uuid4())
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO chats VALUES (?, ?, ?)", 
              (chat_id, title, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return chat_id

def add_message(chat_id, role, content, sources=None):
    msg_id = str(uuid.uuid4())
    sources_json = json.dumps(sources) if sources else None
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?)", 
              (msg_id, chat_id, role, content, sources_json, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_chats():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM chats ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_messages(chat_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM messages WHERE chat_id=? ORDER BY created_at ASC", (chat_id,))
    rows = c.fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        if d['sources']: d['sources'] = json.loads(d['sources'])
        result.append(d)
    return result

def delete_chat(chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM messages WHERE chat_id=?", (chat_id,))
    c.execute("DELETE FROM chats WHERE id=?", (chat_id,))
    conn.commit()
    conn.close()

# Ініціалізація при імпорті
init_db()
