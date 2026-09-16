"""Bounded model timing/usage ledger. Never stores prompts, replies or user IDs."""
import json
import math
import sqlite3
import statistics
import time
from pathlib import Path


def number(value, integer=False):
    if type(value) not in (int,float) or not math.isfinite(value) or value<0:
        return None
    return int(value) if integer else float(value)


class ModelMetrics:
    def __init__(self,path,limit=300):
        self.path=Path(path)
        self.limit=max(1,min(300,int(limit)))
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.path.touch(mode=0o600,exist_ok=True)
        self.path.chmod(0o600)
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY, timestamp REAL NOT NULL, model TEXT NOT NULL,
                effort TEXT NOT NULL, seconds REAL NOT NULL, prompt_tokens INTEGER,
                completion_tokens INTEGER, reasoning_tokens INTEGER, cached_tokens INTEGER,
                cost_usd REAL, error TEXT NOT NULL)''')

    def connect(self):
        # sqlite context manager commits but doesn't close: callers use this wrapper.
        return _Database(self.path)

    def record(self,model,effort,seconds,usage=None,error=''):
        usage=usage if isinstance(usage,dict) else {}
        completion=usage.get('completion_tokens_details') or {}
        prompt=usage.get('prompt_tokens_details') or {}
        if not isinstance(completion,dict):completion={}
        if not isinstance(prompt,dict):prompt={}
        with self.connect() as db:
            db.execute('''INSERT INTO requests(timestamp,model,effort,seconds,prompt_tokens,
                completion_tokens,reasoning_tokens,cached_tokens,cost_usd,error)
                VALUES(?,?,?,?,?,?,?,?,?,?)''',
                (time.time(),str(model)[:160],str(effort)[:30],number(seconds) or 0,
                 number(usage.get('prompt_tokens'),True),number(usage.get('completion_tokens'),True),
                 number(completion.get('reasoning_tokens'),True),number(prompt.get('cached_tokens'),True),
                 number(usage.get('cost')),error if error in ('provider_request_failed','invalid_model_response') else ('request_failed' if error else '')))
            db.execute('DELETE FROM requests WHERE id NOT IN (SELECT id FROM requests ORDER BY id DESC LIMIT ?)',(self.limit,))

    def recent(self,limit=300):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM requests ORDER BY id DESC LIMIT ?',
                                                   (max(1,min(self.limit,int(limit))),))]

    def summary(self,model,effort):
        rows=[r for r in self.recent() if r['model']==model and r['effort']==effort and not r['error']]
        times=[r['seconds'] for r in rows]
        return {'count':len(times),'median_seconds':statistics.median(times) if times else None,
                'mean_seconds':statistics.mean(times) if times else None}


class _Database:
    def __init__(self,path):self.path=path
    def __enter__(self):
        self.db=sqlite3.connect(self.path,timeout=5)
        self.db.row_factory=sqlite3.Row
        return self.db
    def __exit__(self,kind,error,tb):
        try:
            if kind is None:self.db.commit()
            else:self.db.rollback()
        finally:self.db.close()


def format_report(metrics,limit=100):
    rows=metrics.recent(limit)
    if not rows:return 'Запросов к модели пока нет. Сохраню последние 300 обращений.'
    lines=['Последние %d запросов к модели (лимит хранения — 300).' % len(rows)]
    # Bound Telegram output even when many models have been compared.
    groups=list(dict.fromkeys((r['model'],r['effort']) for r in rows))[:8]
    for model,effort in groups:
        group=[r for r in rows if (r['model'],r['effort'])==(model,effort)]
        times=[r['seconds'] for r in group if not r['error']]
        errors=sum(bool(r['error']) for r in group)
        lines.append('\n%s · %s: %d запросов, ошибок %d.' % (model,effort,len(group),errors))
        if times:lines.append('Медиана %.1f с; среднее %.1f с.' % (statistics.median(times),statistics.mean(times)))
        costs=[r['cost_usd'] for r in group if r['cost_usd'] is not None]
        lines.append('Известная стоимость: $%.6f (%d/%d запросов).' % (sum(costs),len(costs),len(group)) if costs else 'Стоимость пока неизвестна.')
        tokens=[r for r in group if r['prompt_tokens'] is not None and r['completion_tokens'] is not None]
        if tokens:lines.append('Токены: вход %d, выход %d (%d/%d запросов).' % (sum(r['prompt_tokens'] for r in tokens),sum(r['completion_tokens'] for r in tokens),len(tokens),len(group)))
    lines.append('\nПоследние обращения:')
    for row in rows[:8]:
        lines.append('%s · %.1f с · %s' % (row['model'][:60],row['seconds'],row['error'] or 'успешно'))
    lines.append('\n/ai_stats 100 · /ai_stats 200 · /ai_stats 300')
    return '\n'.join(lines)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path');parser.add_argument('--last',type=int,default=100)
    args=parser.parse_args()
    metrics=ModelMetrics(args.path)
    rows=metrics.recent(args.last)
    groups=sorted({(r['model'],r['effort']) for r in rows})
    print(json.dumps({'summary':[{ 'model':model,'effort':effort,**metrics.summary(model,effort)} for model,effort in groups],
                      'requests':rows},ensure_ascii=False,indent=2))
