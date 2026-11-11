"""Unfiltered RSS revisions and public article bodies, independent of recommendation."""
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import time

PATH = Path(__file__).resolve().parent / '.data' / 'news.sqlite3'


@contextmanager
def db():
    PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(PATH, timeout=10)
    try:
        with connection:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS items (
                    source_id TEXT, url TEXT, fingerprint TEXT, payload TEXT,
                    first_seen TEXT, last_seen TEXT, PRIMARY KEY(source_id,url,fingerprint));
                CREATE INDEX IF NOT EXISTS items_seen ON items(source_id,last_seen);
                CREATE TABLE IF NOT EXISTS bodies (
                    url TEXT, fingerprint TEXT, text TEXT, fetched_at TEXT, last_seen TEXT, PRIMARY KEY(url,fingerprint));
                CREATE TABLE IF NOT EXISTS body_fetches (
                    url TEXT PRIMARY KEY, status TEXT, fetched_at TEXT, retry_after REAL, error TEXT);
            ''')
            yield connection
    finally:
        connection.close()


def store(articles):
    observed = datetime.now(timezone.utc).isoformat()
    with db() as connection:
        for article in articles:
            # Poll time does not make an otherwise unchanged RSS item a new revision.
            original = {k:v for k,v in article.items() if k not in ('collected_at','copies')}
            payload = json.dumps(original, ensure_ascii=False, sort_keys=True)
            fingerprint = sha256(payload.encode()).hexdigest()
            key = (article['source_id'], article['url'], fingerprint)
            exists = connection.execute('SELECT 1 FROM items WHERE source_id=? AND url=? AND fingerprint=?', key).fetchone()
            connection.execute('''INSERT INTO items VALUES(?,?,?,?,?,?) ON CONFLICT(source_id,url,fingerprint)
                DO UPDATE SET last_seen=excluded.last_seen''', (*key,payload,observed,observed))
            if not exists:
                connection.execute('''INSERT INTO body_fetches VALUES(?, 'pending', NULL, 0, NULL)
                    ON CONFLICT(url) DO UPDATE SET status='pending',retry_after=0,error=NULL''', (article['url'],))


def restore():
    """Restore the last successful feed for each source, not all historical revisions."""
    with db() as connection:
        rows = connection.execute('''SELECT payload,last_seen FROM items AS item WHERE last_seen=
            (SELECT max(last_seen) FROM items WHERE source_id=item.source_id)''').fetchall()
    return [{**json.loads(payload),'collected_at':seen,'copies':1} for payload,seen in rows]


def get_body(url):
    if not PATH.exists():
        return None
    with db() as connection:
        row = connection.execute('SELECT text FROM bodies WHERE url=? ORDER BY last_seen DESC LIMIT 1',(url,)).fetchone()
    return row[0] if row else None


def pending():
    with db() as connection:
        row = connection.execute("SELECT url FROM body_fetches WHERE status!='ok' AND retry_after<=? ORDER BY retry_after,url LIMIT 1", (time.time(),)).fetchone()
    return row[0] if row else None


def save_body(url, text=None, error=None):
    fetched = datetime.now(timezone.utc).isoformat()
    with db() as connection:
        if text:
            fingerprint = sha256(text.encode()).hexdigest()
            connection.execute('INSERT INTO bodies VALUES(?,?,?,?,?) ON CONFLICT(url,fingerprint) DO UPDATE SET last_seen=excluded.last_seen',(url,fingerprint,text,fetched,fetched))
        connection.execute('''INSERT INTO body_fetches VALUES(?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET
            status=excluded.status,fetched_at=excluded.fetched_at,retry_after=excluded.retry_after,error=excluded.error''',
            (url,'ok' if text else 'error',fetched,0 if text else time.time()+3600,error))


def summary():
    if not PATH.exists():
        return {'status':'pending','articles':0,'revisions':0,'bodies':0,'pending':0,'errors':0}
    try:
        with db() as connection:
            articles = connection.execute('SELECT count(DISTINCT url) FROM items').fetchone()[0]
            revisions = connection.execute('SELECT count(*) FROM items').fetchone()[0]
            bodies = connection.execute('SELECT count(DISTINCT url) FROM bodies').fetchone()[0]
            statuses = dict(connection.execute('SELECT status,count(*) FROM body_fetches GROUP BY status'))
        return {'status':'ok','articles':articles,'revisions':revisions,'bodies':bodies,
                'pending':statuses.get('pending',0),'errors':statuses.get('error',0)}
    except sqlite3.Error:
        return {'status':'error','message':'누적 보관 상태 조회 실패'}


def body_collector():
    import intelligence
    while True:
        try:
            url = pending()
            if url:
                try:
                    save_body(url, intelligence.read_article(url))
                except Exception as error:
                    save_body(url,error=f'공개 본문 수집 실패 ({type(error).__name__})')
            time.sleep(1 if url else 5)
        except Exception:
            time.sleep(10)
