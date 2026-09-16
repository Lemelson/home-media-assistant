"""Durable Telegram intake with per-user ordering and bounded daemon workers.

Only one process may own a state directory. Completed IDs remain for deduplication;
the corresponding message/contact payload is erased immediately on completion.
"""
import json
import queue
import sqlite3
import threading
import time
from pathlib import Path
from contextlib import contextmanager


class Inbox:
    def __init__(self, state_dir, handle_update, on_failure=None, max_workers=4, max_pending=1000, on_receipt=None, async_receipts=False, reserve_controls=False):
        self.path=Path(state_dir)/'inbox.db'
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.path.touch(mode=0o600,exist_ok=True)
        self.path.chmod(0o600)
        self.handle_update=handle_update
        self.on_failure=on_failure
        self.reserve_controls=reserve_controls
        self.async_receipts=async_receipts
        self._receipts=queue.Queue()
        self.on_receipt=on_receipt
        self.max_workers=max(1,min(4,int(max_workers)))
        self.max_pending=max(1,min(1000,int(max_pending)))
        self._condition=threading.Condition(threading.RLock())
        self._active=set()
        self._stopped=False
        self._ready=queue.Queue()
        with self._db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS inbox (
                update_id INTEGER PRIMARY KEY, lane TEXT NOT NULL, chat_id INTEGER,
                payload TEXT, status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0
            )''')
            db.execute("CREATE INDEX IF NOT EXISTS inbox_pending ON inbox(status,update_id)")
            db.execute("UPDATE inbox SET status='pending' WHERE status IN ('running','receiving')")

        if self.async_receipts and self.on_receipt:
            for _ in range(2):
                threading.Thread(target=self._receipt_worker,name="media-receipt",daemon=True).start()

        for _ in range(self.max_workers):
            threading.Thread(target=self._worker,name='media-inbox',daemon=True).start()

    def _worker(self):
        while True:
            row=self._ready.get()
            if row is None:return
            self._run(row)

    @contextmanager
    def _db(self):
        db=sqlite3.connect(self.path,timeout=10)
        db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()

    @staticmethod
    def _routing(update):
        callback=update.get('callback_query') or {}
        message=callback.get('message') or update.get('message') or {}
        uid=(callback.get('from') or message.get('from') or {}).get('id',0)
        chat_id=(message.get('chat') or {}).get('id')
        data=callback.get('data','')
        text=message.get('text','').strip().casefold()
        fast=(data in ('downloads','library','status') if callback else
              (text.split(maxsplit=1)[0] if text else '') == '/ai_stats' or text in ('/downloads','/library','/status','загрузки','статус','библиотека','мои фильмы','🎬 мои фильмы','⬇️ загрузки'))
        if callback and data.startswith(('download-page:','downloads-page:','download:','library-page:')):
            fast=True
        if data.startswith(('priority:','pause:','resume:')):
            return str(uid)+':control',chat_id
        if data.startswith('media:'):
            return str(uid)+':release-search',chat_id
        if data.startswith(('release:','catalog:')):
            return str(uid)+':release-download',chat_id
        return str(uid)+(':fast' if fast else ':dialog'),chat_id

    def enqueue(self,update):
        """Accept durably, including already-seen IDs; False means apply backpressure."""
        update_id=update.get('update_id')
        if type(update_id) is not int:raise ValueError('invalid_update_id')
        lane,chat_id=self._routing(update)
        payload=json.dumps(update,ensure_ascii=False)
        needs_receipt=bool(self.on_receipt and not (self.async_receipts and (update.get('callback_query') or lane.endswith((':fast',':control')))))
        with self._condition, self._db() as db:
            if self._stopped:return False
            if db.execute('SELECT 1 FROM inbox WHERE update_id=?',(update_id,)).fetchone():return True
            callback=update.get('callback_query') or {}
            if callback.get('data','').startswith('media:'):
                active=db.execute("SELECT payload FROM inbox WHERE lane=? AND status!='done'",(lane,)).fetchall()
                if any((json.loads(row['payload']).get('callback_query') or {}).get('data')==callback['data'] for row in active):
                    # Remember this update ID as consumed; a later click after the
                    # active search finishes remains a fresh, independent retry.
                    db.execute("INSERT INTO inbox(update_id,lane,chat_id,payload,status) VALUES(?,?,?,NULL,'done')",(update_id,lane,chat_id))
                    return True
            count=db.execute("SELECT COUNT(*) FROM inbox WHERE status!='done'").fetchone()[0]
            if count>=self.max_pending:return False
            db.execute('INSERT INTO inbox(update_id,lane,chat_id,payload,status) VALUES(?,?,?,?,?)',
                       (update_id,lane,chat_id,payload,'receiving' if needs_receipt else 'pending'))
        if needs_receipt:
            if self.async_receipts:
                self._receipts.put((update_id,payload))
            else:
                self._receive(update_id,payload)
        if self.async_receipts:
            self.pump()
        return True

    def _receipt_worker(self):
        while True:
            item=self._receipts.get()
            if item is None:return
            self._receive(*item)
            self.pump()

    def _receive(self,update_id,payload):
        # Receipt I/O never owns the intake or scheduler lock.
        accepted=json.loads(payload)
        try:
            message_id=self.on_receipt(accepted)
            if type(message_id) is int and message_id>0 and 'message' in accepted:
                accepted['message']['_receipt_message_id']=message_id
        except Exception:
            pass
        with self._condition, self._db() as db:
            db.execute("UPDATE inbox SET payload=?,status='pending' WHERE update_id=?",
                       (json.dumps(accepted,ensure_ascii=False),update_id))
            self._condition.notify_all()

    def pump(self):
        """Schedule available lanes without waiting for handlers or network requests."""
        scheduled=[]
        with self._condition:
            if self._stopped:return 0
            with self._db() as db:
                rows=db.execute("SELECT * FROM inbox WHERE status='pending' ORDER BY update_id").fetchall()
                receiving={row['lane']:row['first_id'] for row in db.execute("SELECT lane,MIN(update_id) AS first_id FROM inbox WHERE status='receiving' GROUP BY lane")}
                # Fast controls first, preserving FIFO within each individual lane.
                rows.sort(key=lambda row:(0 if row['lane'].endswith(':control') else 1 if row['lane'].endswith(':fast') else 2,row['update_id']))
                for row in rows:
                    if len(self._active)>=self.max_workers:break
                    if (self.reserve_controls and not row['lane'].endswith((':fast',':control'))
                            and len(self._active)>=max(1,self.max_workers-1)):continue
                    if row['lane'] in self._active:continue
                    if receiving.get(row['lane'],row['update_id']+1)<row['update_id']:continue
                    self._active.add(row['lane'])
                    db.execute("UPDATE inbox SET status='running' WHERE update_id=?",(row['update_id'],))
                    scheduled.append(dict(row))
            for row in scheduled:
                self._ready.put(row)
        return len(scheduled)

    def _run(self,row):
        failed=False
        try:self.handle_update(json.loads(row['payload']))
        except Exception:failed=True
        notify=False
        with self._condition:
            with self._db() as db:
                attempts=row['attempts']+1
                if failed and attempts<3:
                    db.execute("UPDATE inbox SET status='pending',attempts=? WHERE update_id=?",(attempts,row['update_id']))
                else:
                    db.execute("UPDATE inbox SET status='done',payload=NULL,attempts=? WHERE update_id=?",(attempts,row['update_id']))
                    notify=failed
            # Keep this worker counted while best-effort notification runs.
        if notify and self.on_failure:
            try:self.on_failure(row['chat_id'])
            except Exception:pass
        with self._condition:
            self._active.discard(row['lane'])
            self.pump()
            self._condition.notify_all()

    def pending_count(self):
        with self._condition, self._db() as db:
            return db.execute("SELECT COUNT(*) FROM inbox WHERE status!='done'").fetchone()[0]

    def idle(self):
        with self._condition:return not self._active and self.pending_count()==0

    def wait_idle(self,timeout=5):
        """Bounded condition wait, primarily for shutdown callers and deterministic tests."""
        deadline=time.monotonic()+timeout
        with self._condition:
            while not self.idle():
                remaining=deadline-time.monotonic()
                if remaining<=0:return False
                self._condition.wait(remaining)
            return True

    def stop(self):
        """Stop scheduling; active daemon handlers finish and pending rows survive."""
        with self._condition:
            if self._stopped:return
            self._stopped=True
            if self.async_receipts and self.on_receipt:
                for _ in range(2):self._receipts.put(None)
            for _ in range(self.max_workers):self._ready.put(None)
            self._condition.notify_all()
