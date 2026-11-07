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

from .memory_engine import extract_facts, tokens, is_continuation_request, project_scopes, memory_topics


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
              id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              kind TEXT NOT NULL DEFAULT 'chat', model_mode TEXT NOT NULL DEFAULT 'fast');
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
            CREATE TABLE IF NOT EXISTS task_changes(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              chat_id TEXT NOT NULL, task_id TEXT,
              instruction TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              FOREIGN KEY(chat_id) REFERENCES chats(id));
            CREATE INDEX IF NOT EXISTS idx_task_changes_active
              ON task_changes(chat_id,status,id);
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
            # Non-destructive migration: old user databases keep every chat/message.
            fields = {row['name'] for row in db.execute('PRAGMA table_info(chats)')}
            if 'kind' not in fields:
                db.execute("ALTER TABLE chats ADD COLUMN kind TEXT NOT NULL DEFAULT 'chat'")
            if 'model_mode' not in fields:
                db.execute("ALTER TABLE chats ADD COLUMN model_mode TEXT NOT NULL DEFAULT 'fast'")
            try:
                db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS message_search USING fts5(content, chat_id UNINDEXED)')
                db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS memory_search USING fts5(content, memory_id UNINDEXED)')
            except sqlite3.OperationalError:
                pass  # old Python builds may lack FTS5

    def create_chat(self, title='Neuer Chat', kind='chat', model_mode=None):
        if kind not in ('chat', 'project'):
            raise ValueError('Unbekannter Chattyp')
        if model_mode is None:
            model_mode = 'project' if kind == 'project' else 'auto'
        if model_mode not in ('auto', 'fast', 'project'):
            raise ValueError('Unbekannter Modellmodus')
        cid = uuid.uuid4().hex
        with self._lock, self._connect() as db:
            db.execute('''INSERT INTO chats(id,title,created_at,updated_at,kind,model_mode)
                          VALUES(?,?,?,?,?,?)''',
                       (cid, title[:100], now(), now(), kind, model_mode))
        return cid

    def chat_kind(self, cid):
        with self._connect() as db:
            row = db.execute('SELECT kind FROM chats WHERE id=?', (cid,)).fetchone()
        return row['kind'] if row else None

    def chat_model_mode(self, cid):
        with self._connect() as db:
            row = db.execute('SELECT kind,model_mode FROM chats WHERE id=?', (cid,)).fetchone()
        if row is None:
            return None
        return 'project' if row['kind'] == 'project' else row['model_mode']

    def set_chat_model_mode(self, cid, model_mode):
        if model_mode not in ('auto', 'fast', 'project'):
            raise ValueError('Unbekannter Modellmodus')
        with self._lock, self._connect() as db:
            db.execute('''UPDATE chats SET model_mode=?,updated_at=?
                          WHERE id=? AND kind='chat' ''',
                       (model_mode, now(), cid))

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
            db.execute('DELETE FROM task_changes WHERE chat_id=?',(cid,))
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

    def matching_chat_ids(self, query):
        """Search message contents, treating user input as text, never FTS syntax."""
        text = str(query or '').strip()
        if not text:
            return set()
        terms = re.findall(r'[^\W_]+', text, flags=re.UNICODE)
        with self._connect() as db:
            if terms and self._fts_available(db, 'message_search'):
                expression = ' AND '.join('"' + term + '"*' for term in terms)
                try:
                    rows = db.execute('''SELECT DISTINCT s.chat_id
                        FROM message_search AS s JOIN chats AS c ON c.id=s.chat_id
                        WHERE message_search MATCH ?''', (expression,)).fetchall()
                    return {row['chat_id'] for row in rows}
                except sqlite3.OperationalError:
                    pass  # Older SQLite builds may lack a usable FTS index.
            literal = text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            rows = db.execute('''SELECT DISTINCT m.chat_id
                FROM messages AS m JOIN chats AS c ON c.id=m.chat_id
                WHERE m.content LIKE ? ESCAPE '\\' ''', ('%' + literal + '%',)).fetchall()
            return {row['chat_id'] for row in rows}

    def chat_export_text(self, cid):
        """Export one saved conversation in full; personal memory is separate."""
        with self._connect() as db:
            rows = db.execute('''SELECT c.title,m.id,m.role,m.content
                FROM chats AS c LEFT JOIN messages AS m ON m.chat_id=c.id
                WHERE c.id=? ORDER BY m.id''', (cid,)).fetchall()
        if not rows:
            raise ValueError('Unbekannter Chat.')
        parts = ['SYTOX Assistant – Chat-Export\nTitel: ' + rows[0]['title']]
        labels = {'user': 'Du', 'assistant': 'SYTOX', 'system': 'System', 'tool': 'Werkzeug'}
        for row in rows:
            if row['id'] is not None:
                parts.append(labels.get(row['role'], 'Nachricht') + ':\n' + row['content'])
        return '\n\n'.join(parts) + '\n'

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

    @staticmethod
    def _recall_terms(query):
        generic = {'projekt', 'project', 'welche', 'welcher', 'welches', 'welchen',
                   'bevorzuge', 'bevorzugte', 'erinnerung', 'erinnerungen', 'weißt',
                   'weiss', 'gespeichert', 'über', 'mich', 'bitte'}
        return set(tokens(query)) - generic

    @staticmethod
    def _uncovered_user_text(content, facts):
        """Remove covered fact sentences, retaining independent user constraints.

        Keep untouched excerpts verbatim. When one sentence is superseded, its
        neighbours retain their separators and indentation instead of dropping
        the whole original message.
        """
        pieces = re.split(r'((?<=[.!?])\s+|\n+)', content)
        kept, removed = [], False
        for index in range(0, len(pieces), 2):
            sentence = pieces[index]
            covered = any((fact['scope'], fact['fact_key']) in facts
                          for fact in extract_facts(sentence))
            if covered:
                removed = True
                continue
            kept.append(sentence)
            if index + 1 < len(pieces):
                kept.append(pieces[index + 1])
        return ''.join(kept).strip('\r\n') if removed else content

    def related_context(self, query, exclude_chat=None, limit=6, *, current_chat_id=None):
        """Rank local user facts and excerpts; never mix unrelated project contexts.

        This remains deterministic lexical retrieval, not semantic understanding.
        All returned material is context, not new instructions or verified actions.
        """
        limit = max(0, min(int(limit), 50))
        if not limit or not str(query or '').strip():
            return []
        current_chat_id = current_chat_id or exclude_chat
        terms, topics = self._recall_terms(query), memory_topics(query)
        expr = ' OR '.join('"' + term + '"' for term in sorted(terms)[:12])
        candidates, pinned = [], []
        with self._connect() as db:
            chats = {row['id']: row['kind'] for row in db.execute('SELECT id,kind FROM chats')}
            facts = db.execute('SELECT * FROM memory_facts ORDER BY updated_at DESC,id DESC LIMIT 450').fetchall()
            latest = {(row['scope'], row['fact_key']): row for row in facts}
            requested = project_scopes(query)
            # Existing stored scope names also work without the word "Projekt".
            for fact in facts:
                scope = fact['scope']
                if scope.startswith('project:') and re.search(
                        r'(?<!\w)' + re.escape(scope[8:]) + r'(?!\w)', str(query), re.IGNORECASE):
                    requested.add(scope)
            source_scopes = {}
            for fact in facts:
                if fact['scope'].startswith('project:'):
                    source_scopes.setdefault(fact['source_chat_id'], set()).add(fact['scope'])

            def allowed(content, scope='global', source=None):
                named = project_scopes(content)
                if scope.startswith('project:'):
                    named.add(scope)
                if requested:
                    if named and not named.intersection(requested):
                        return False
                    if chats.get(source) == 'project' and source != current_chat_id:
                        return bool((named | source_scopes.get(source, set())).intersection(requested))
                    return True
                if chats.get(current_chat_id) == 'project':
                    return source == current_chat_id if named or chats.get(source) == 'project' else True
                return not named and chats.get(source) != 'project'

            for fact in facts:
                if not allowed(fact['content'], fact['scope'], fact['source_chat_id']):
                    continue
                overlap = len(terms.intersection(tokens(fact['content'])))
                topic = fact['fact_key'] in topics
                named = fact['scope'] in requested
                if not (overlap or topic or named):
                    continue
                score = 100 + 8 * overlap + 12 * topic + 20 * named
                score += 10 * (fact['source_chat_id'] == current_chat_id)
                score += 6 * (fact['kind'] in ('correction', 'edited'))
                candidates.append((score, fact['id'], {
                    'source': 'Langzeitgedächtnis ' + fact['scope'] + ' (Nutzerangabe)',
                    'content': fact['content'][:350], 'kind': 'fact',
                    'scope': fact['scope'], 'chat_id': fact['source_chat_id']}))

            rows = []
            fallback = not self._fts_available(db, 'message_search')
            if terms and not fallback:
                try:
                    rows = db.execute('''SELECT DISTINCT m.id,m.content,m.chat_id
                        FROM message_search AS s JOIN messages AS m
                          ON m.chat_id=s.chat_id AND m.content=s.content
                        WHERE message_search MATCH ? AND m.role='user' AND m.chat_id != ?
                        ORDER BY m.id DESC LIMIT 80''', (expr, exclude_chat or '')).fetchall()
                except sqlite3.OperationalError:
                    fallback = True
            if terms and fallback:
                rows = db.execute("SELECT id,content,chat_id FROM messages WHERE role='user' "
                                  'AND chat_id != ? ORDER BY id DESC LIMIT 600', (exclude_chat or '',)).fetchall()
            for row in rows:
                if row['chat_id'] not in chats or not allowed(row['content'], source=row['chat_id']):
                    continue
                content = self._uncovered_user_text(row['content'], latest)
                overlap = len(terms.intersection(tokens(content)))
                topic = bool(topics.intersection(memory_topics(content)))
                if overlap or topic:
                    candidates.append((30 + 6 * overlap + 2 * topic, row['id'], {
                        'source': 'Frühere Nutzerangabe (unbestätigter Chat-Auszug)',
                        'content': content[:900], 'kind': 'excerpt', 'chat_id': row['chat_id']}))

            manual = {row['id']: row for row in db.execute(
                'SELECT id,content FROM memories ORDER BY id DESC LIMIT 200')}
            if terms and self._fts_available(db, 'memory_search'):
                try:
                    for row in db.execute('''SELECT m.id,m.content FROM memory_search AS s
                        JOIN memories AS m ON m.id=s.memory_id
                        WHERE memory_search MATCH ? ORDER BY rank LIMIT 80''', (expr,)):
                        manual[row['id']] = row
                except sqlite3.OperationalError:
                    pass
            for row in manual.values():
                if not allowed(row['content']):
                    continue
                overlap = len(terms.intersection(tokens(row['content'])))
                item = {'source': 'Erinnerung (manuell gespeichert)', 'content': row['content'][:900],
                        'kind': 'manual'}
                if overlap:
                    candidates.append((60 + 6 * overlap, row['id'], item))
                else:
                    pinned.append(item)
        ordered = [item for _score, _id, item in sorted(candidates, key=lambda item: (item[0], item[1]), reverse=True)]
        ordered += pinned[:2]  # Pinned notes share the caller's limit instead of overflowing it.
        result, seen = [], set()
        for item in ordered:
            key = ' '.join(item['content'].casefold().split())
            if key not in seen:
                result.append(item)
                seen.add(key)
            if len(result) >= limit:
                break
        return result

    def current_chat_context(self, query, chat_id, recent_messages=12, limit=4):
        """Recall relevant older user statements beyond the recent-turn window."""
        limit = max(0, min(int(limit), 20))
        terms, topics = self._recall_terms(query), memory_topics(query)
        if not limit or not chat_id or not (terms or topics):
            return []
        with self._connect() as db:
            recent = db.execute('SELECT id FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT ?',
                                (chat_id, max(1, int(recent_messages)))).fetchall()
            if not recent:
                return []
            cutoff = min(row['id'] for row in recent)
            facts = {(row['scope'], row['fact_key']): row for row in db.execute(
                'SELECT * FROM memory_facts ORDER BY updated_at DESC,id DESC LIMIT 450')}
            rows = []
            if terms and self._fts_available(db, 'message_search'):
                expr = ' OR '.join('"' + term + '"' for term in sorted(terms)[:12])
                try:
                    rows = db.execute('''SELECT DISTINCT m.id,m.content FROM message_search AS s
                        JOIN messages AS m ON m.chat_id=s.chat_id AND m.content=s.content
                        WHERE message_search MATCH ? AND m.chat_id=? AND m.role='user' AND m.id<?
                        ORDER BY m.id DESC LIMIT 100''', (expr, chat_id, cutoff)).fetchall()
                except sqlite3.OperationalError:
                    pass
            # Topic-word variants and non-FTS installations still recall bounded old user context.
            if not rows:
                rows = db.execute("SELECT id,content FROM messages WHERE chat_id=? AND role='user' "
                                  'AND id<? ORDER BY id DESC LIMIT 600', (chat_id, cutoff)).fetchall()
            ranked = []
            for row in rows:
                content = self._uncovered_user_text(row['content'], facts)
                if not content:
                    continue
                overlap = len(terms.intersection(tokens(content)))
                topic = bool(topics.intersection(memory_topics(content)))
                if overlap or topic:
                    ranked.append((overlap * 4 + topic * 2, row['id'], content))
        result, seen = [], set()
        for _score, _id, content in sorted(ranked, reverse=True):
            key = ' '.join(content.casefold().split())
            if key not in seen:
                result.append({'source': 'Frühere Nutzerangabe im aktuellen Chat (unverifiziert, ggf. überholt)',
                               'content': content[:1200], 'kind': 'excerpt', 'chat_id': chat_id})
                seen.add(key)
            if len(result) >= limit:
                break
        return result

    def create_task(self,cid,goal,mode='once',deadline=None):
        tid=uuid.uuid4().hex
        with self._lock,self._connect() as db:
            db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?)',
                       (tid,cid,goal,mode,deadline,'running','{}',now(),now()))
            # Attach requests given between starting the worker and task creation.
            db.execute('UPDATE task_changes SET task_id=?,updated_at=? '
                       'WHERE chat_id=? AND task_id IS NULL AND status=\'queued\'',
                       (tid, now(), cid))
        return tid

    def set_task_mode(self, tid, mode):
        if mode not in ('once', 'until_done', 'timed'):
            raise ValueError('Unbekannter Arbeitsmodus.')
        with self._lock, self._connect() as db:
            db.execute('UPDATE tasks SET mode=?, updated_at=? WHERE id=?',
                       (mode, now(), tid))

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

    def add_task_change(self, cid, instruction):
        """Atomically enqueue work only while a coding task is active."""
        instruction = str(instruction or '').strip()
        if not instruction or len(instruction) > 2000:
            raise ValueError('Änderungswunsch muss 1 bis 2000 Zeichen haben.')
        with self._lock, self._connect() as db:
            active = db.execute(
                "SELECT id FROM tasks WHERE chat_id=? AND status='running' "
                "ORDER BY created_at DESC LIMIT 1", (cid,)
            ).fetchone()
            if not active:
                # The worker may have started but not yet inserted its task.
                # Store temporarily unattached; create_task binds it atomically.
                task_id = None
            else:
                task_id = active['id']
            cursor = db.execute(
                'INSERT INTO task_changes(chat_id,task_id,instruction,status,created_at,updated_at) '
                "VALUES(?,?,?,'queued',?,?)",
                (cid, task_id, instruction, now(), now()),
            )
            return cursor.lastrowid

    def task_changes(self, tid, include_applied=False):
        """Chronological, persistent amendments for exactly one task."""
        with self._connect() as db:
            query = ('SELECT id, chat_id, task_id, instruction, status '
                     'FROM task_changes WHERE task_id=?')
            if not include_applied:
                query += " AND status IN ('queued','in_progress')"
            query += ' ORDER BY id'
            return [dict(r) for r in db.execute(query, (tid,))]

    def claim_next_change(self, tid):
        """Claim one queued amendment; resume an in-progress amendment first."""
        with self._lock, self._connect() as db:
            record = db.execute(
                "SELECT * FROM task_changes WHERE task_id=? "
                "AND status IN ('queued','in_progress') "
                'ORDER BY id LIMIT 1', (tid,)
            ).fetchone()
            if not record:
                return None
            if record['status'] == 'queued':
                db.execute(
                    "UPDATE task_changes SET status='in_progress',updated_at=? WHERE id=?",
                    (now(), record['id']),
                )
            return {**dict(record), 'status': 'in_progress'}

    def finish_change(self, tid, change_id):
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE task_changes SET status='applied',updated_at=? "
                "WHERE task_id=? AND id=? AND status='in_progress'",
                (now(), tid, change_id),
            )

    def complete_task_if_queue_empty(self, tid, checkpoint):
        """Prevents a new amendment racing with final user-facing completion."""
        with self._lock, self._connect() as db:
            if db.execute(
                "SELECT id FROM task_changes WHERE task_id=? "
                "AND status IN ('queued','in_progress') LIMIT 1", (tid,)
            ).fetchone():
                return False
            db.execute(
                "UPDATE tasks SET status='done',checkpoint=?,updated_at=? "
                "WHERE id=? AND status='running'",
                (json.dumps(checkpoint, ensure_ascii=False), now(), tid),
            )
            return True

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
