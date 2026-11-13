"""Persistent analysis jobs and immutable per-version event evidence."""
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
import time


def epoch(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z','+00:00'))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).timestamp()
    except (ValueError,TypeError,AttributeError):
        return 0


class Store:
    def __init__(self, path, namespace):
        self.path = Path(path)
        self.namespace = namespace
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS analysis_jobs (
                    id INTEGER PRIMARY KEY, job_key TEXT UNIQUE, namespace TEXT, article_id TEXT,
                    url TEXT, title TEXT, body_version TEXT, article TEXT, body TEXT, published_epoch REAL,
                    status TEXT, attempts INTEGER DEFAULT 0, available_at REAL DEFAULT 0,
                    enqueued_at REAL, started_at REAL, finished_at REAL, last_error TEXT,
                    event_id TEXT, result TEXT, assessment TEXT);
                CREATE INDEX IF NOT EXISTS analysis_queue ON analysis_jobs(namespace,status,available_at,id);
                CREATE INDEX IF NOT EXISTS analysis_events ON analysis_jobs(namespace,event_id,id);
                CREATE INDEX IF NOT EXISTS analysis_articles ON analysis_jobs(namespace,article_id,id);
                CREATE INDEX IF NOT EXISTS analysis_completed ON analysis_jobs(namespace,status,finished_at);
                CREATE TABLE IF NOT EXISTS analysis_cursors (
                    namespace TEXT, name TEXT, value INTEGER, PRIMARY KEY(namespace,name));
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def cursors(self):
        with self.db() as db:
            return dict(db.execute('SELECT name,value FROM analysis_cursors WHERE namespace=?', (self.namespace,)))

    def enqueue(self, records, cursors=None):
        with self.db() as db:
            for record in records:
                article = {k:v for k,v in record['article'].items() if k != 'feed_xml'}
                version = record.get('body_version', '')
                if not version and db.execute('''SELECT 1 FROM analysis_jobs WHERE namespace=? AND url=?
                        AND title=? AND body_version!='' LIMIT 1''', (self.namespace,article['url'],article['title'])).fetchone():
                    continue
                key = sha256(json.dumps([self.namespace,article['url'],article['title'],version],ensure_ascii=False).encode()).hexdigest()
                db.execute('''INSERT OR IGNORE INTO analysis_jobs
                    (job_key,namespace,article_id,url,title,body_version,article,body,published_epoch,status,enqueued_at)
                    VALUES(?,?,?,?,?,?,?,?,?, 'pending',?)''',
                    (key,self.namespace,article['id'],article['url'],article['title'],version,
                     json.dumps(article,ensure_ascii=False),record.get('body'),epoch(article.get('published_at')),time.time()))
                if version:
                    db.execute('''UPDATE analysis_jobs SET status='superseded' WHERE namespace=? AND url=? AND title=?
                        AND body_version='' AND status IN ('pending','error')''', (self.namespace,article['url'],article['title']))
            for name,value in (cursors or {}).items():
                db.execute('INSERT OR REPLACE INTO analysis_cursors VALUES(?,?,?)',(self.namespace,name,value))

    def claim(self):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE analysis_jobs SET status='pending' WHERE namespace=? AND status='processing' AND available_at<=?", (self.namespace,time.time()))
            row = db.execute("SELECT value FROM analysis_cursors WHERE namespace=? AND name='dispatch'", (self.namespace,)).fetchone()
            dispatch = row[0] if row else 0
            reviewed = db.execute("SELECT value FROM analysis_cursors WHERE namespace=? AND name='review_dispatch'",(self.namespace,)).fetchone()
            review = None
            if dispatch and dispatch%3==0 and (not reviewed or reviewed[0]!=dispatch):
                review = db.execute('''SELECT * FROM analysis_jobs WHERE namespace=? AND status IN ('pending','error')
                    AND available_at<=? AND job_key LIKE 'screen-review:%' ORDER BY published_epoch DESC,id DESC LIMIT 1''',
                    (self.namespace,time.time())).fetchone()
            # One oldest job for every two newest jobs prevents backlog starvation.
            order = 'id ASC' if dispatch % 3 == 0 else 'published_epoch DESC,id DESC'
            job = review or db.execute(f'''SELECT * FROM analysis_jobs WHERE namespace=? AND status IN ('pending','error')
                AND available_at<=? AND job_key NOT LIKE 'screen-review:%' ORDER BY {order} LIMIT 1''',(self.namespace,time.time())).fetchone()
            if not job:
                job = db.execute('''SELECT * FROM analysis_jobs WHERE namespace=? AND status IN ('pending','error')
                    AND available_at<=? AND job_key LIKE 'screen-review:%' ORDER BY published_epoch DESC,id DESC LIMIT 1''',
                    (self.namespace,time.time())).fetchone()
            if not job:
                return None
            db.execute("UPDATE analysis_jobs SET status='processing',attempts=attempts+1,started_at=?,available_at=? WHERE id=?",
                       (time.time(),time.time()+300,job['id']))
            name,value=('review_dispatch',dispatch) if job['job_key'].startswith('screen-review:') else ('dispatch',dispatch+1)
            db.execute('INSERT OR REPLACE INTO analysis_cursors VALUES(?,?,?)',(self.namespace,name,value))
        return {**dict(job),'article':json.loads(job['article']),'attempts':job['attempts']+1}

    def complete(self, job, reading, assessment):
        reading = {**reading,'source_version_at':(job['article'].get('_version_at') if job['body'] is not None else reading.get('source_version_at')) or reading.get('published_at'),
                   'body_version':job['body_version'] or reading.get('body_version','')}
        with self.db() as db:
            db.execute('''UPDATE analysis_jobs SET status='done',finished_at=?,last_error=NULL,event_id=?,result=?,assessment=?
                WHERE id=? AND namespace=? AND status='processing' AND attempts=?''',(time.time(),reading['event_id'],json.dumps(reading,ensure_ascii=False),
                json.dumps(assessment,ensure_ascii=False),job['id'],self.namespace,job['attempts']))

    def retry(self, job, error):
        delay = min(3600, 300 * 2 ** min(job['attempts']-1,4))
        with self.db() as db:
            db.execute("UPDATE analysis_jobs SET status='error',available_at=?,last_error=? WHERE id=? AND namespace=? AND status='processing' AND attempts=?",
                       (time.time()+delay,str(error)[:300],job['id'],self.namespace,job['attempts']))

    def _latest(self, articles):
        if not articles:
            return {}
        current = {a['id']:a for a in articles}
        with self.db() as db:
            rows = []
            ids = list(current)
            for offset in range(0,len(ids),400):
                chunk = ids[offset:offset+400]
                placeholders = ','.join('?' for _ in chunk)
                rows.extend(db.execute(f"SELECT * FROM analysis_jobs WHERE namespace=? AND article_id IN ({placeholders}) AND status!='superseded' ORDER BY id DESC",[self.namespace,*chunk]).fetchall())
        latest = {}
        for row in rows:
            article = json.loads(row['article'])
            if row['article_id'] not in current or row['title'] != current[row['article_id']]['title']:
                continue
            version = (epoch(article.get('_version_at') or article.get('published_at')),row['id'])
            old = latest.get(row['article_id'])
            if old is None or version > old[0]:
                latest[row['article_id']] = (version,row)
        return {key:value[1] for key,value in latest.items()}

    def enqueue_reviews(self, articles, policy):
        latest=self._latest(articles)
        with self.db() as db:
            for article in articles:
                row=latest.get(article['id'])
                if row is None or row['status']!='done' or json.loads(row['assessment']).get('screen_policy_version')==policy:
                    continue
                key='screen-review:'+sha256(json.dumps([row['job_key'],policy]).encode()).hexdigest()
                db.execute('''INSERT OR IGNORE INTO analysis_jobs
                    (job_key,namespace,article_id,url,title,body_version,article,body,published_epoch,status,enqueued_at,result)
                    VALUES(?,?,?,?,?,?,?,?,?,'pending',?,?)''',
                    (key,self.namespace,row['article_id'],row['url'],row['title'],row['body_version'],row['article'],
                     row['body'],row['published_epoch'],time.time(),row['result']))
                break

    def readings(self, articles, limit=None):
        latest=self._latest(articles)
        selected = [latest[a['id']] for a in articles if a['id'] in latest and latest[a['id']]['status']=='done'][:limit]
        return [json.loads(row['result']) for row in selected], [dict(json.loads(row['assessment']),event_id=row['event_id']) for row in selected]

    def anchors(self, article, limit=6):
        # shortcut: scan 500 recent analyses; add embedding retrieval after recall evaluation.
        tokens = set(re.findall(r'[가-힣A-Za-z0-9]{2,}',article['title'].lower()))
        with self.db() as db:
            rows = db.execute('''SELECT event_id,result FROM analysis_jobs WHERE namespace=? AND status='done'
                ORDER BY finished_at DESC LIMIT 500''',(self.namespace,)).fetchall()
        candidates = {}
        with self.db() as db:
            own_events = {row[0] for row in db.execute("SELECT DISTINCT event_id FROM analysis_jobs WHERE namespace=? AND article_id=? AND status='done'",(self.namespace,article['id']))}
        for row in rows:
            if row['event_id'] in own_events:
                continue
            r = json.loads(row['result'])
            if epoch(article.get('published_at')) and epoch(r.get('published_at')) > epoch(article['published_at']):
                continue
            if epoch(article.get('_version_at')) and epoch(r.get('source_version_at')) > epoch(article['_version_at']):
                continue
            words = set(re.findall(r'[가-힣A-Za-z0-9]{2,}',(' '.join(r.get('entities',[]))+' '+r.get('event_title','')).lower()))
            overlap = len(tokens & words)
            if overlap and row['event_id'] not in candidates:
                candidates[row['event_id']] = (overlap,r)
        return [{k:r.get(k) for k in ('event_id','event_title','entities','published_at','summary','certainty','event_type','amount','timing')}
                for _,r in sorted(candidates.values(),key=lambda x:x[0],reverse=True)[:limit]]

    def first_published(self, event_ids):
        result = {}
        with self.db() as db:
            for event_id in event_ids:
                rows = db.execute("SELECT result FROM analysis_jobs WHERE namespace=? AND event_id=? AND status='done'",(self.namespace,event_id)).fetchall()
                dates = [json.loads(row[0]).get('published_at') for row in rows]
                dates = [date for date in dates if epoch(date)>0]
                if dates:
                    result[event_id] = min(dates,key=epoch)
        return result

    def history(self, event_id, limit=10):
        with self.db() as db:
            rows = db.execute('''SELECT id,article_id,event_id,body_version,result,finished_at,assessment,job_key FROM analysis_jobs
                WHERE namespace=? AND status='done' AND (event_id=? OR article_id IN
                (SELECT article_id FROM analysis_jobs WHERE namespace=? AND event_id=?))
                ORDER BY id DESC LIMIT ?''',(self.namespace,event_id,self.namespace,event_id,limit)).fetchall()
        return [{'revision':r['id'],'article_id':r['article_id'],'event_id':r['event_id'],
                 'body_version':r['body_version'],'assessment_review':r['job_key'].startswith('screen-review:'),
                 'reviewed_at':json.loads(r['assessment']).get('assessed_at') if r['job_key'].startswith('screen-review:') else None,
                 'stock_relevance':json.loads(r['assessment']).get('stock_relevance'),
                 'assessment_reason':json.loads(r['assessment']).get('reason'),
                 **{k:json.loads(r['result']).get(k) for k in
                 ('event_title','summary','certainty','amount','timing','source_url','published_at','analyzed_at','evidence')}} for r in reversed(rows)]

    def summary(self):
        with self.db() as db:
            counts = dict(db.execute('SELECT status,count(*) FROM analysis_jobs WHERE namespace=? GROUP BY status',(self.namespace,)))
            oldest = db.execute("SELECT min(enqueued_at) FROM analysis_jobs WHERE namespace=? AND status IN ('pending','processing','error')",(self.namespace,)).fetchone()[0]
            elapsed = db.execute("SELECT finished_at-enqueued_at FROM analysis_jobs WHERE namespace=? AND status='done' ORDER BY finished_at DESC LIMIT 100",(self.namespace,)).fetchall()
            events = db.execute("SELECT count(DISTINCT event_id) FROM analysis_jobs WHERE namespace=? AND status='done'",(self.namespace,)).fetchone()[0]
        delays = sorted(row[0] for row in elapsed)
        return {'pending':counts.get('pending',0),'processing':counts.get('processing',0),'retrying':counts.get('error',0),
                'done':counts.get('done',0),'event_count':events,'oldest_wait_seconds':round(max(0,time.time()-oldest)) if oldest else 0,
                'recent_p95_seconds':round(delays[(len(delays)*95+99)//100-1]) if delays else None}
