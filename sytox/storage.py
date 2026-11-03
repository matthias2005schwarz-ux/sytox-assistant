"""Local-first SQLite chat, memory, tasks and audit storage."""
from __future__ import annotations
import json
from contextlib import contextmanager
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def default_data_dir() -> Path:
    return Path(os.environ.get('APPDATA') or (Path.home() / '.local' / 'share')) / 'SytoxAssistant'


class Store:
    """Each operation opens its own connection so worker threads are safe."""
    def __init__(self, path=None):
        self.path = Path(path) if path else default_data_dir() / 'assistant.db'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.path), timeout=20)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA busy_timeout=20000')
            db.execute('PRAGMA journal_mode=WAL')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _initialize(self):
        with self._connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS chats(
              id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS messages(
              id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL, role TEXT NOT NULL,
              content TEXT NOT NULL, created_at TEXT NOT NULL,
              FOREIGN KEY(chat_id) REFERENCES chats(id));
            CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id,id);
            CREATE TABLE IF NOT EXISTS memories(
              id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tasks(
              id TEXT PRIMARY KEY, chat_id TEXT NOT NULL, goal TEXT NOT NULL, mode TEXT NOT NULL,
              deadline TEXT, status TEXT NOT NULL, checkpoint TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS journal(
              id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT, event TEXT NOT NULL,
              details TEXT NOT NULL, created_at TEXT NOT NULL);
            ''')
            try:
                db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS message_search USING fts5(content, chat_id UNINDEXED)')
                db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS memory_search USING fts5(content, memory_id UNINDEXED)')
            except sqlite3.OperationalError:
                pass  # old Python builds may lack FTS5

    def create_chat(self, title='Neuer Chat'):
        cid = uuid.uuid4().hex
        with self._lock, self._connect() as db:
            db.execute('INSERT INTO chats VALUES(?,?,?,?)', (cid,title,now(),now()))
        return cid

    def chats(self):
        with self._connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM chats ORDER BY updated_at DESC')]

    def rename_chat(self, cid, title):
        with self._lock, self._connect() as db:
            db.execute('UPDATE chats SET title=?,updated_at=? WHERE id=?', (title[:100], now(),cid))

    def delete_chat(self, cid):
        with self._lock, self._connect() as db:
            db.execute('DELETE FROM message_search WHERE chat_id=?', (cid,)) if self._fts_available(db,'message_search') else None
            db.execute('DELETE FROM messages WHERE chat_id=?',(cid,))
            db.execute('DELETE FROM tasks WHERE chat_id=?',(cid,))
            db.execute('DELETE FROM chats WHERE id=?',(cid,))

    def _fts_available(self, db, table):
        return db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone() is not None

    def add_message(self, cid, role, content):
        with self._lock, self._connect() as db:
            cur=db.execute('INSERT INTO messages(chat_id,role,content,created_at) VALUES(?,?,?,?)',
                           (cid,role,content,now()))
            if self._fts_available(db,'message_search'):
                db.execute('INSERT INTO message_search(content,chat_id) VALUES(?,?)', (content,cid))
            db.execute('UPDATE chats SET updated_at=? WHERE id=?',(now(),cid))
            return cur.lastrowid

    def messages(self, cid, limit=200):
        with self._connect() as db:
            rows=db.execute('SELECT * FROM (SELECT * FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT ?) ORDER BY id',
                            (cid,limit)).fetchall()
            return [dict(r) for r in rows]

    def add_memory(self, text):
        text=str(text).strip()[:1000]
        if not text: raise ValueError('Leere Erinnerung')
        with self._lock,self._connect() as db:
            cur=db.execute('INSERT OR IGNORE INTO memories(content,created_at) VALUES(?,?)',(text,now()))
            mid=cur.lastrowid
            if cur.rowcount and self._fts_available(db,'memory_search'):
                db.execute('INSERT INTO memory_search(content,memory_id) VALUES(?,?)',(text,str(mid)))
        return text

    def list_memories(self):
        with self._connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM memories ORDER BY id DESC')]

    def delete_memory(self, mid):
        with self._lock,self._connect() as db:
            db.execute('DELETE FROM memories WHERE id=?',(mid,))
            if self._fts_available(db,'memory_search'):
                db.execute('DELETE FROM memory_search WHERE memory_id=?',(str(mid),))

    def related_context(self, query, exclude_chat=None, limit=6):
        """Cross-chat recall; this is lexical FTS, not perfect semantic memory."""
        tokens=re.findall(r'[^\W_]{3,}',query,flags=re.UNICODE)[:8]
        if not tokens: return []
        expr=' OR '.join('"'+t.replace('"','')+'"' for t in tokens)
        results=[]
        with self._connect() as db:
            if self._fts_available(db,'message_search'):
                try:
                    rows=db.execute('''SELECT content,chat_id FROM message_search
                      WHERE message_search MATCH ? AND chat_id != ? ORDER BY rank LIMIT ?''',
                      (expr, exclude_chat or '',limit)).fetchall()
                    results += [{'source':'Vorheriger Chat','content':r['content'][:900]} for r in rows]
                except sqlite3.OperationalError: pass
            if self._fts_available(db,'memory_search'):
                try:
                    rows=db.execute('''SELECT content FROM memory_search
                      WHERE memory_search MATCH ? ORDER BY rank LIMIT ?''',(expr,limit)).fetchall()
                    results += [{'source':'Erinnerung','content':r['content'][:900]} for r in rows]
                except sqlite3.OperationalError: pass
            # Provide a small amount of pinned memory regardless of matching vocabulary.
            for r in db.execute('SELECT content FROM memories ORDER BY id DESC LIMIT 8'):
                if not any(x['content']==r['content'] for x in results):
                    results.append({'source':'Erinnerung','content':r['content'][:900]})
        return results[:limit+8]

    def create_task(self,cid,goal,mode='once',deadline=None):
        tid=uuid.uuid4().hex
        with self._lock,self._connect() as db:
            db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?)',
                       (tid,cid,goal,mode,deadline,'running','{}',now(),now()))
        return tid

    def extend_task(self, tid, deadline):
        """Extend a timed task when resuming a session whose prior time expired."""
        with self._lock, self._connect() as db:
            db.execute('UPDATE tasks SET deadline=?,updated_at=? WHERE id=?',
                       (deadline, now(), tid))

    def update_task(self,tid,status,checkpoint=None):
        with self._lock,self._connect() as db:
            if checkpoint is None:
                db.execute('UPDATE tasks SET status=?, updated_at=? WHERE id=?',(status,now(),tid))
            else:
                db.execute('UPDATE tasks SET status=?, checkpoint=?, updated_at=? WHERE id=?',
                           (status,json.dumps(checkpoint,ensure_ascii=False),now(),tid))

    def tasks(self,cid=None):
        with self._connect() as db:
            if cid: rows=db.execute('SELECT * FROM tasks WHERE chat_id=? ORDER BY created_at DESC',(cid,))
            else: rows=db.execute('SELECT * FROM tasks ORDER BY created_at DESC')
            return [dict(r) for r in rows]

    def interrupted_tasks(self):
        with self._lock,self._connect() as db:
            db.execute("UPDATE tasks SET status='paused',updated_at=? WHERE status='running'",(now(),))

    def log(self,event,details,cid=None):
        with self._lock,self._connect() as db:
            db.execute('INSERT INTO journal(chat_id,event,details,created_at) VALUES(?,?,?,?)',
                       (cid,event,str(details)[:3500],now()))

    def logs(self,cid=None,limit=100):
        with self._connect() as db:
            if cid:
                rows=db.execute('SELECT * FROM journal WHERE chat_id=? ORDER BY id DESC LIMIT ?',(cid,limit))
            else:
                rows=db.execute('SELECT * FROM journal ORDER BY id DESC LIMIT ?',(limit,))
            return [dict(r) for r in rows]
