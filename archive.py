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
            has_versions = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='body_versions'").fetchone()
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS items (
                    source_id TEXT, url TEXT, fingerprint TEXT, payload TEXT,
                    first_seen TEXT, last_seen TEXT, PRIMARY KEY(source_id,url,fingerprint));
                CREATE INDEX IF NOT EXISTS items_seen ON items(source_id,last_seen);
                CREATE TABLE IF NOT EXISTS bodies (
                    url TEXT, fingerprint TEXT, text TEXT, fetched_at TEXT, last_seen TEXT, PRIMARY KEY(url,fingerprint));
                CREATE TABLE IF NOT EXISTS body_versions (
                    id INTEGER PRIMARY KEY, url TEXT, fingerprint TEXT, observed_at TEXT);
                CREATE INDEX IF NOT EXISTS body_versions_url ON body_versions(url,id);
                CREATE TABLE IF NOT EXISTS body_fetches (
                    url TEXT PRIMARY KEY, status TEXT, fetched_at TEXT, retry_after REAL, error TEXT);
            ''')
            if not has_versions:
                connection.execute('''INSERT INTO body_versions(url,fingerprint,observed_at)
                    SELECT url,fingerprint,fetched_at FROM bodies ORDER BY fetched_at,rowid''')
                latest = connection.execute('''SELECT url,fingerprint,last_seen FROM bodies AS b WHERE rowid=
                    (SELECT rowid FROM bodies WHERE url=b.url ORDER BY last_seen DESC,rowid DESC LIMIT 1)''').fetchall()
                for url,fingerprint,seen in latest:
                    previous = connection.execute('SELECT fingerprint FROM body_versions WHERE url=? ORDER BY id DESC LIMIT 1',(url,)).fetchone()
                    if previous and previous[0] != fingerprint:
                        connection.execute('INSERT INTO body_versions(url,fingerprint,observed_at) VALUES(?,?,?)',(url,fingerprint,seen))
            yield connection
    finally:
        connection.close()


def store(articles, connection=None):
    if connection is None:
        with db() as connection:
            return store(articles, connection)
    observed = datetime.now(timezone.utc).isoformat()
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


def browse(limit=30, before=None, query='', source='', since='', until='', words=(), kind='all', source_id=''):
    """Latest version of every stored URL; model assessments never filter this path."""
    conditions=['n=1']; values=[]
    if query:
        conditions.append("(instr(lower(json_extract(payload,'$.title')),lower(?))>0 OR instr(lower(json_extract(payload,'$.source')),lower(?))>0)")
        values.extend([query,query])
    if source:
        conditions.append("json_extract(payload,'$.source')=?"); values.append(source)
    if source_id:
        conditions.append("json_extract(payload,'$.source_id')=?");values.append(source_id)
    for date,operator in [(since,'>='),(until,'<=')]:
        if date:
            conditions.append(f"date(json_extract(payload,'$.published_at'),'+9 hours'){operator}?"); values.append(date)
    if words:
        conditions.append('('+' OR '.join("instr(lower(json_extract(payload,'$.title')),lower(?))>0" for _ in words)+')');values.extend(words)
    if kind!='all':
        conditions.append("json_extract(payload,'$.kind')=?");values.append(kind)
    base="""WITH latest AS (SELECT payload,url,last_seen,
        coalesce(cast(strftime('%s',json_extract(payload,'$.published_at')) AS integer),0) AS published,
        row_number() OVER(PARTITION BY url ORDER BY last_seen DESC,rowid DESC) AS n FROM items) """
    where=' AND '.join(conditions)
    with db() as connection:
        total=connection.execute(base+'SELECT count(*) FROM latest WHERE '+where,values).fetchone()[0]
        sources=[r[0] for r in connection.execute("SELECT DISTINCT json_extract(payload,'$.source') FROM items ORDER BY 1") if r[0]]
        if before:
            where+=' AND (published<? OR (published=? AND url<?))';values.extend([before[0],before[0],before[1]])
        rows=connection.execute(base+'SELECT payload,last_seen,published,url FROM latest WHERE '+where+' ORDER BY published DESC,url DESC LIMIT ?',[*values,limit+1]).fetchall()
    return {'articles':[{**json.loads(r[0]),'collected_at':r[1],'copies':1} for r in rows[:limit]],
            'total':total,'sources':sources,'next':list(rows[limit-1][2:]) if len(rows)>limit else None}


def get_body(url):
    if not PATH.exists():
        return None
    with db() as connection:
        row = connection.execute('SELECT text FROM bodies WHERE url=? ORDER BY last_seen DESC LIMIT 1',(url,)).fetchone()
    return row[0] if row else None


def body_snapshot(url):
    if not PATH.exists():
        return None
    with db() as connection:
        row = connection.execute('''SELECT b.text,b.fingerprint,b.last_seen,f.status FROM bodies b
            LEFT JOIN body_fetches f ON f.url=b.url WHERE b.url=? ORDER BY b.last_seen DESC,b.rowid DESC LIMIT 1''',(url,)).fetchone()
        metadata = connection.execute('SELECT payload FROM items WHERE url=? ORDER BY last_seen DESC,rowid DESC LIMIT 1',(url,)).fetchone()
    return {'text':row[0],'fingerprint':row[1],'observed_at':row[2],'status':row[3],
            'title':json.loads(metadata[0])['title'] if metadata else None} if row else None


def pending():
    with db() as connection:
        row = connection.execute("SELECT url FROM body_fetches WHERE status!='ok' AND retry_after<=? ORDER BY retry_after,url LIMIT 1", (time.time(),)).fetchone()
    return row[0] if row else None


def save_body(url, text=None, error=None):
    fetched = datetime.now(timezone.utc).isoformat()
    with db() as connection:
        if text:
            fingerprint = sha256(text.encode()).hexdigest()
            previous = connection.execute('SELECT fingerprint FROM body_versions WHERE url=? ORDER BY id DESC LIMIT 1',(url,)).fetchone()
            if previous is None or previous[0] != fingerprint:
                connection.execute('INSERT INTO body_versions(url,fingerprint,observed_at) VALUES(?,?,?)',(url,fingerprint,fetched))
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


def analysis_batch(cursors, limit=100):
    """Replay every stored RSS/body revision using durable row cursors."""
    records, updated = [], {}
    with db() as connection:
        items = connection.execute('SELECT rowid,payload,first_seen FROM items WHERE rowid>? ORDER BY rowid LIMIT ?',
                                   (cursors.get('archive_items',0),limit)).fetchall()
        for revision,payload,seen in items:
            records.append({'article':{**json.loads(payload),'_version_at':seen}})
            updated['archive_items'] = revision
        bodies = connection.execute('''SELECT v.id,v.url,v.fingerprint,substr(b.text,1,6000),v.observed_at
            FROM body_versions v JOIN bodies b ON b.url=v.url AND b.fingerprint=v.fingerprint
            WHERE v.id>? ORDER BY v.id LIMIT ?''',(cursors.get('archive_versions',0),limit)).fetchall()
        for revision,url,fingerprint,text,fetched in bodies:
            item = connection.execute('''SELECT payload FROM items WHERE url=? AND first_seen<=?
                ORDER BY first_seen DESC,rowid DESC LIMIT 1''',(url,fetched)).fetchone()
            if item is None:
                item = connection.execute('SELECT payload FROM items WHERE url=? ORDER BY first_seen,rowid LIMIT 1',(url,)).fetchone()
            if item:
                records.append({'article':{**json.loads(item[0]),'_version_at':fetched},'body':text,'body_version':f'{revision}:{fingerprint}'})
            updated['archive_versions'] = revision
    return records, updated
