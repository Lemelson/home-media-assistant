"""Permanent local per-torrent timeline; network responses carry summaries only."""
import json
from contextlib import contextmanager
import sqlite3
import time
from pathlib import Path
from bot.download_forecast import observe

LIMIT=300_000_000

class DownloadJournal:
    def __init__(self,directory,limit=LIMIT):
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.path=self.directory/'history.sqlite3';self.limit=limit
        with self.connection() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS torrents(hash TEXT PRIMARY KEY, updated REAL, record TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS samples(hash TEXT, at REAL, done INTEGER, status INTEGER, interval_seconds REAL, bytes INTEGER, speed REAL, seeders INTEGER, leechers INTEGER, PRIMARY KEY(hash,at));
CREATE TABLE IF NOT EXISTS additions(id INTEGER PRIMARY KEY AUTOINCREMENT, hash TEXT UNIQUE, at REAL, over_limit INTEGER);''')
        self.path.chmod(0o600)
    @contextmanager
    def connection(self):
        db=sqlite3.connect(self.path,timeout=5);db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()
    def register(self,h,metadata,now=None):
        now=time.time() if now is None else now
        over=self.size_bytes()>self.limit
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT record FROM torrents WHERE hash=?',(h,)).fetchone()
            record=json.loads(row[0]) if row else dict(hash=h,started=now)
            quality=metadata.get('quality',{})
            record.update(name=metadata.get('name',record.get('name','')),media=metadata.get('media',record.get('media',{})))
            for key in ('seeders','leechers'):
                if quality.get(key) is not None:record[key]=quality[key]
            db.execute('INSERT OR REPLACE INTO torrents VALUES(?,?,?)',(h,now,json.dumps(record)))
            db.execute('INSERT OR IGNORE INTO additions(hash,at,over_limit) VALUES(?,?,?)',(h,now,int(over)))
    def record(self,torrents,now=None):
        now=time.time() if now is None else now
        seen=set()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            for t in torrents:
                h=t['hashString'];seen.add(h)
                row=db.execute('SELECT record FROM torrents WHERE hash=?',(h,)).fetchone()
                record=json.loads(row[0]) if row else dict(hash=h)
                status=t.get('status',-1)
                complete=t.get('percentDone',0)>=1 and t.get('leftUntilDone',1)==0 and status not in (1,2) and not t.get('errorString')
                if record.get('completed') and complete:continue
                if now-record.get('sampled',-1000)<30 and status==record.get('status') and not complete:continue
                old_bytes=record.get('bytes',0);old_seconds=record.get('seconds',0)
                observe(record,t,now)
                record.update(sampled=now,status=status)
                done=max(0,(t.get('sizeWhenDone') or t.get('totalSize') or 0)-t.get('leftUntilDone',0))
                record.setdefault('first_observed_bytes',done)
                dt=record.get('seconds',0)-old_seconds;amount=record.get('bytes',0)-old_bytes
                db.execute('INSERT OR IGNORE INTO samples VALUES(?,?,?,?,?,?,?,?,?)',
                           (h,now,done,status,dt,amount,amount/dt if dt else None,t.get('seeders',record.get('seeders')),t.get('leechers',record.get('leechers'))))
                db.execute('INSERT OR REPLACE INTO torrents VALUES(?,?,?)',(h,now,json.dumps(record)))
            for row in db.execute('SELECT hash,record FROM torrents').fetchall():
                r=json.loads(row['record'])
                if row['hash'] not in seen and r.pop('last',None) is not None:
                    db.execute('UPDATE torrents SET record=? WHERE hash=?',(json.dumps(r),row['hash']))
    def unavailable(self):
        # Drop baselines so recovery never interprets an unobserved interval as speed.
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            for row in db.execute('SELECT hash,record FROM torrents').fetchall():
                record=json.loads(row['record'])
                if record.pop('last',None) is not None:
                    db.execute('UPDATE torrents SET record=? WHERE hash=?',(json.dumps(record),row['hash']))
    def summaries(self):
        with self.connection() as db:
            rows=db.execute('SELECT record FROM torrents ORDER BY updated DESC LIMIT 12').fetchall()
        return [json.loads(row[0]) for row in rows]
    def size_bytes(self):
        return sum(p.stat().st_size for p in self.directory.iterdir() if p.is_file() and not p.is_symlink())
    def storage(self):
        with self.connection() as db:
            rows=db.execute('SELECT id,over_limit FROM additions ORDER BY id DESC LIMIT 100').fetchall()
        size=self.size_bytes()
        return dict(bytes=size,limit=self.limit,over_limit=size>self.limit,events=[dict(r) for r in reversed(rows)])
    def sample_count(self):
        with self.connection() as db:return db.execute('SELECT COUNT(*) FROM samples').fetchone()[0]
