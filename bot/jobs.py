"""Durable delivery to an intermittently connected Mac; explicit delete consent."""

import json
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


class JobStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(mode=0o600, exist_ok=True)
        self.path.chmod(0o600)
        with self.connection() as db:
            had_notifications = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='job_notifications'").fetchone()
            db.executescript('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, source TEXT UNIQUE NOT NULL,
                    user_id INTEGER NOT NULL, payload TEXT NOT NULL,
                    result TEXT, created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS confirmations (
                    token TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
                    hash TEXT NOT NULL, expires INTEGER NOT NULL, consumed INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS job_notifications (job_id TEXT PRIMARY KEY);
            ''')
            if 'payload' not in {row['name'] for row in db.execute('PRAGMA table_info(confirmations)')}:
                db.execute('ALTER TABLE confirmations ADD COLUMN payload TEXT')
            if not had_notifications:
                db.execute('INSERT OR IGNORE INTO job_notifications SELECT id FROM jobs WHERE result IS NOT NULL')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def enqueue(self, source, user_id, payload):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT id FROM jobs WHERE source=?', (source,)).fetchone()
            if row:
                return row['id']
            job_id = secrets.token_hex(12)
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,NULL,?)',
                       (job_id, source, user_id, json.dumps(payload), int(time.time())))
            return job_id

    def enqueue_priority_mode(self, source, user_id, torrent_hash):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            previous=db.execute('SELECT id FROM jobs WHERE source=?',(source,)).fetchone()
            if previous:return previous['id']
            def read(key,default):
                row=db.execute('SELECT value FROM state WHERE key=?',(key,)).fetchone()
                return json.loads(row['value']) if row else default
            state=read('transfer:%s:%s'%(user_id,torrent_hash),{})
            confirmed=read('priority-confirmed:'+torrent_hash,{})
            desired_key='priority-desired:%s:%s'%(user_id,torrent_hash)
            desired=read(desired_key,{})
            current=desired.get('mode',2 if confirmed.get('paused',state.get('paused')) else confirmed.get('priority',state.get('priority',0)))
            mode={-1:0,0:1,1:2,2:-1}[current]
            job_id=secrets.token_hex(12)
            payload={'action':'bandwidth_priority','hash':torrent_hash,'mode':mode}
            # Supersede waiting absolute targets; an in-flight old target may finish,
            # but its result cannot replace the newer desired state.
            db.execute("INSERT OR IGNORE INTO job_notifications SELECT id FROM jobs WHERE result IS NULL AND user_id=? AND json_extract(payload,'$.action')='bandwidth_priority' AND json_extract(payload,'$.hash')=? AND json_type(payload,'$.mode') IS NOT NULL",(user_id,torrent_hash))
            db.execute("UPDATE jobs SET result=? WHERE result IS NULL AND user_id=? AND json_extract(payload,'$.action')='bandwidth_priority' AND json_extract(payload,'$.hash')=? AND json_type(payload,'$.mode') IS NOT NULL",(json.dumps({'ok':True,'superseded':True}),user_id,torrent_hash))
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,NULL,?)',(job_id,source,user_id,json.dumps(payload),int(time.time())))
            db.execute('INSERT INTO state VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(desired_key,json.dumps({'mode':mode,'job_id':job_id})))
            return job_id

    @staticmethod
    def decode(row):
        if row is None:
            return None
        result = dict(row)
        result['payload'] = json.loads(result['payload'])
        result['result'] = json.loads(result['result']) if result['result'] else None
        return result

    def get(self, job_id):
        with self.connection() as db:
            return self.decode(db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())

    def pending_priorities(self):
        with self.connection() as db:
            return [self.decode(row) for row in db.execute(
                "SELECT * FROM jobs WHERE result IS NULL AND json_extract(payload,'$.action')='bandwidth_priority' ORDER BY created_at,rowid LIMIT 100")]

    def pending(self):
        with self.connection() as db:
            return [self.decode(row) for row in db.execute(
                'SELECT * FROM jobs WHERE result IS NULL ORDER BY created_at,rowid LIMIT 20')]

    def finish(self, job_id, result):
        with self.connection() as db:
            db.execute('UPDATE jobs SET result=? WHERE id=? AND result IS NULL', (json.dumps(result), job_id))

    def unnotified(self):
        with self.connection() as db:
            return [self.decode(row) for row in db.execute('''SELECT jobs.* FROM jobs
                LEFT JOIN job_notifications n ON n.job_id=jobs.id
                WHERE jobs.result IS NOT NULL AND n.job_id IS NULL ORDER BY jobs.created_at LIMIT 20''')]

    def successful_adds(self):
        """Recent ownership evidence for adopting in-flight downloads after an upgrade."""
        with self.connection() as db:
            jobs = [self.decode(row) for row in db.execute(
                'SELECT * FROM jobs WHERE result IS NOT NULL ORDER BY created_at DESC,rowid DESC LIMIT 1000')]
        return [job for job in jobs if job['payload'].get('action') == 'add'
                and job['result'].get('ok') and job['result'].get('hash')]

    def mark_notified(self, job_id):
        with self.connection() as db:
            db.execute('INSERT OR IGNORE INTO job_notifications VALUES(?)', (job_id,))

    def read_states(self, prefix):
        with self.connection() as db:
            return {row['key']: json.loads(row['value']) for row in db.execute(
                'SELECT key,value FROM state WHERE substr(key,1,?)=?', (len(prefix), prefix))}

    def offer_delete(self, user_id, torrent_hash, now=None):
        if not re.fullmatch(r'[a-fA-F0-9]{40}', torrent_hash):
            raise ValueError('invalid_torrent_hash')
        return self.offer_action(user_id, {'action': 'delete', 'hash': torrent_hash}, now)

    def offer_action(self, user_id, payload, now=None):
        action = payload.get('action')
        field = {'delete': 'hash', 'delete_library': 'inventory_id'}.get(action)
        if (field is None or set(payload) != {'action', field}
                or not isinstance(payload.get(field), str)
                or not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', payload[field])):
            raise ValueError('invalid_confirmation_action')
        now = int(time.time()) if now is None else now
        token = secrets.token_hex(12)
        with self.connection() as db:
            db.execute('INSERT INTO confirmations(token,user_id,hash,expires,payload) VALUES(?,?,?,?,?)',
                       (token, user_id, payload.get('hash', ''), now + 300, json.dumps(payload)))
        return token

    def cancel_confirmation(self, user_id, token=None):
        with self.connection() as db:
            if token is None:
                changed = db.execute('UPDATE confirmations SET consumed=1 WHERE user_id=? AND consumed=0', (user_id,))
            else:
                changed = db.execute('UPDATE confirmations SET consumed=1 WHERE user_id=? AND token=? AND consumed=0', (user_id, token))
            return changed.rowcount > 0

    def confirm_delete(self, user_id, token, now=None):
        now = int(time.time()) if now is None else now
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM confirmations WHERE token=? AND user_id=? AND consumed=0 AND expires>=?',
                             (token, user_id, now)).fetchone()
            if row is None:
                return None
            job_id = secrets.token_hex(12)
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,NULL,?)',
                       (job_id, 'delete:' + token, user_id,
                        row['payload'] or json.dumps({'action': 'delete', 'hash': row['hash']}), now))
            db.execute('UPDATE confirmations SET consumed=1 WHERE token=?', (token,))
            return job_id

    def read_state(self, key, default=None):
        with self.connection() as db:
            row = db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
            return json.loads(row['value']) if row else default

    def write_state(self, key, value):
        with self.connection() as db:
            db.execute('INSERT INTO state VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                       (key, json.dumps(value)))

    def append_context(self, user_id, role, text):
        if role not in ('user', 'assistant'):
            raise ValueError('invalid_context_role')
        key = 'conversation:' + str(user_id)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
            context = json.loads(row['value']) if row else []
            context = (context + [{'role': role, 'content': str(text)[:5000]}])[-16:]
            db.execute('INSERT INTO state VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                       (key, json.dumps(context)))
