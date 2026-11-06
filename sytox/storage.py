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

from .memory_engine import extract_facts, tokens, is_continuation_request


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
            CREATE TABLE IF NOT EXISTS memory_facts(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              scope TEXT NOT NULL, fact_key TEXT NOT NULL,
              content TEXT NOT NULL, kind TEXT NOT NULL,
              source_chat_id TEXT NOT NULL,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              UNIQUE(scope, fact_key));
            CREATE INDEX IF NOT EXISTS idx_memory_facts_updated
              ON memory_facts(updated_at DESC);
            CREATE TABLE IF NOT EXISTS preferences(
              key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')
            # Add a chat kind without deleting or reclassifying existing chats.
            # The default PROJECT preserves the historic 30B agent behavior.
            existing_cols = {row['name'] for row in db.execute('PRAGMA table_info(chats)')}
            if 'mode' not in existing_cols:
                db.execute("ALTER TABLE chats ADD COLUMN mode TEXT NOT NULL DEFAULT 'project'")
            try:
                db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS message_search USING fts5(content, chat_id UNINDEXED)')
                db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS memory_search USING fts5(content, memory_id UNINDEXED)')
            except sqlite3.OperationalError:
                pass  # old Python builds may lack FTS5

    def create_chat(self, title='Neuer Chat', mode='project'):
        if mode not in ('quick', 'project'):
            raise ValueError('Ungültiger Chat-Typ.')
        cid = uuid.uuid4().hex
        with self._lock, self._connect() as db:
            db.execute('''INSERT INTO chats(id,title,created_at,updated_at,mode)
                          VALUES(?,?,?,?,?)''', (cid,title,now(),now(),mode))
        return cid

    def chat_mode(self, cid):
        with self._connect() as db:
            result = db.execute('SELECT mode FROM chats WHERE id=?', (cid,)).fetchone()
            return result['mode'] if result and result['mode'] == 'quick' else 'project'

    def chats(self):
        with self._connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM chats ORDER BY updated_at DESC')]

    def rename_chat(self, cid, title):
        with self._lock, self._connect() as db:
            db.execute('UPDATE chats SET title=?,updated_at=? WHERE id=?', (title[:100], now(),cid))

    def delete_chat(self, cid):
        with self._lock, self._connect() as db:
            db.execute('DELETE FROM message_search WHERE chat_id=?', (cid,)) if self._fts_available(db,'message_search') else None
            db.execute('DELETE FROM memory_facts WHERE source_chat_id=?',(cid,))
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
            if role == 'user':
                enabled = db.execute("SELECT value FROM preferences WHERE key='auto_memory'").fetchone()
                if enabled is None or enabled['value'] == '1':
                    for fact in extract_facts(content):
                        moment = now()
                        db.execute('''INSERT INTO memory_facts
                            (scope,fact_key,content,kind,source_chat_id,created_at,updated_at)
                            VALUES (?,?,?,?,?,?,?)
                            ON CONFLICT(scope,fact_key) DO UPDATE SET
                              content=excluded.content,kind=excluded.kind,
                              source_chat_id=excluded.source_chat_id,
                              updated_at=excluded.updated_at
                            WHERE content != excluded.content''',
                            (fact['scope'],fact['fact_key'],fact['content'],
                             fact['kind'],cid,moment,moment))
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

    def auto_memory_enabled(self):
        with self._connect() as db:
            row = db.execute("SELECT value FROM preferences WHERE key='auto_memory'").fetchone()
            return row is None or row['value'] == '1'

    def set_auto_memory_enabled(self, enabled):
        with self._lock, self._connect() as db:
            db.execute('''INSERT INTO preferences(key,value) VALUES('auto_memory',?)
                       ON CONFLICT(key) DO UPDATE SET value=excluded.value''',
                       ('1' if enabled else '0',))

    def list_memory_facts(self, limit=500):
        with self._connect() as db:
            return [dict(r) for r in db.execute(
                'SELECT * FROM memory_facts ORDER BY updated_at DESC,id DESC LIMIT ?',
                (max(1,min(int(limit),500)),))]

    def delete_memory_fact(self, fact_id):
        with self._lock, self._connect() as db:
            db.execute('DELETE FROM memory_facts WHERE id=?',(int(fact_id),))

    def update_memory_fact(self, fact_id, content):
        """Manual edits never inherit a claim of automated verification."""
        content = str(content).strip()[:350]
        if not content:
            raise ValueError('Erinnerung darf nicht leer sein.')
        with self._lock, self._connect() as db:
            db.execute('UPDATE memory_facts SET content=?,kind=?,updated_at=? WHERE id=?',
                       (content,'edited',now(),int(fact_id)))

    def recent_project_context(self, query, exclude_task_id=None, limit=2):
        """Summaries of actual stored tasks, not model guesses about progress."""
        if not is_continuation_request(query):
            return []
        terms=set(tokens(query))
        with self._connect() as db:
            tasks=db.execute('''SELECT id, goal, status, checkpoint, updated_at
                 FROM tasks WHERE status IN ('paused','failed','time_elapsed','done')
                 ORDER BY updated_at DESC LIMIT 70''').fetchall()
        results=[]
        for t in tasks:
            if t['id'] == exclude_task_id:
                continue
            matches=set(tokens(t['goal'])) & terms
            generic=bool(re.search(
                r'(?i)\b(?:letztes?\s+projekt|vorherig\w*\s+projekt|wo\s+waren\s+wir)\b',
                str(query or '')))
            if len(terms)>2 and not matches and not generic:
                continue
            try:
                checkpoint=json.loads(t['checkpoint'] or '{}')
                if not isinstance(checkpoint,dict):
                    checkpoint={}
            except (TypeError, ValueError):
                checkpoint={}
            notes=checkpoint.get('progress_notes',[])
            if not isinstance(notes,list):
                notes=[]
            results.append({
                'source':'Projektverlauf ('+t['status']+')',
                'content':('Auftrag: '+t['goal'][:450]+
                  '\nZuletzt gespeichert: '+str(t['updated_at'])+
                  '\nLetzter Statusbericht (unverifiziert): '+
                  str(checkpoint.get('last_result',''))[:500]+
                  '\nNotizen (unverifiziert): '+
                  json.dumps(notes[-2:],ensure_ascii=False)[:650])
            })
            if len(results)>=limit:
                break
        return results

    def related_context(self, query, exclude_chat=None, limit=6):
        """Cross-chat recall; this is lexical FTS, not perfect semantic memory."""
        query_words=re.findall(r'[^\W_]{3,}',str(query or ''),flags=re.UNICODE)[:8]
        if not query_words: return []
        expr=' OR '.join('"'+t.replace('"','')+'"' for t in query_words)
        results=[]
        with self._connect() as db:
            # Newest per-topic facts take precedence over older chat snippets.
            term_set=set(tokens(query))
            matching=[]
            for fact in db.execute(
                    'SELECT * FROM memory_facts ORDER BY updated_at DESC LIMIT 450'):
                content_terms=set(tokens(fact['content']))
                overlap=len(term_set & content_terms)
                scope=fact['scope']
                if scope.startswith('project:') and scope[8:] in str(query).casefold():
                    overlap+=3
                # Preferences apply across chats; other facts require relevance.
                if overlap or (scope=='global' and fact['kind']=='explicit'):
                    matching.append((overlap,fact))
            matching.sort(key=lambda pair:pair[0],reverse=True)
            for score,fact in matching[:6]:
                results.append({'source':'Langzeitgedächtnis '+fact['scope'],
                                'content':fact['content'][:350]})
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
