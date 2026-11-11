import sqlite3
from pathlib import Path
import json 
DB_Path = Path(__file__).resolve().parent/"chat.db"

def get_connection():
    connection = sqlite3.connect(DB_Path)
    return connection

def init_connection():
    connection = get_connection()
    try:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS agent_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                message_json TEXT NOT NULL
            )
        """)
        connection.commit()
    finally:
        connection.close()

def save_turn(session_id,messages):
    connection = get_connection()
    try:
        for message in messages:            #messages是列表，message是列表中的字典
            message_json = json.dumps(message , ensure_ascii = False)
            connection.execute(
                """
                INSERT INTO agent_messages (session_id, message_json)
                VALUES (?, ?)
                """,
                (session_id,message_json))

        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

def get_history(session_id):
    connection = get_connection()
    try:
        cursor = connection.execute(
                   """
            SELECT message_json
            FROM agent_messages
            WHERE session_id = ?
            ORDER BY id ASC
            """,(session_id,)
                    )
        rows = cursor.fetchall()        #rows是一个列表，里面每项是“一行数据”的元组；元组里才放着JSON字符串。
        history = []                    #rows = [('{"role": "user", "content": "你好"}',),('{"role": "assistant", "content": "你好呀"}',)]
        for row in rows:
            message_json = row[0]
            message = json.loads(message_json)
            history.append(message)
        return history
    finally:
        connection.close()


        
        

