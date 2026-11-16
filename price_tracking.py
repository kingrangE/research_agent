"""Persist observed Npay quotes for news-linked stocks; never backdate a baseline."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import sqlite3
import time

import archive
import stocks
import business_ontology
import market_history
from zoneinfo import ZoneInfo
from news_ingestion import lease

PATH=Path(__file__).resolve().parent/'.data'/'price_tracking.sqlite3'
ACTIVE_SECONDS=26*3600


def moment(value):
    value=datetime.fromisoformat(value.replace('Z','+00:00'))
    if value.tzinfo is None:raise ValueError('시각에 시간대 필요')
    return value.astimezone(timezone.utc)


def now_text():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def db():
    PATH.parent.mkdir(parents=True,exist_ok=True)
    connection=sqlite3.connect(PATH,timeout=10)
    connection.row_factory=sqlite3.Row
    try:
        with connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS tracked_articles(
                    id TEXT PRIMARY KEY,reference_at TEXT,reference_basis TEXT,stocks TEXT,last_seen REAL);
                CREATE TABLE IF NOT EXISTS samples(
                    id INTEGER PRIMARY KEY,code TEXT,trade_time REAL,observed REAL,payload TEXT);
                CREATE INDEX IF NOT EXISTS samples_series ON samples(code,trade_time,id);
                CREATE TABLE IF NOT EXISTS polls(code TEXT PRIMARY KEY,attempted REAL,status TEXT);
            """)
            yield connection
    finally:connection.close()


def register(article,related,first_seen=None,now=None):
    clock=moment(now or now_text())
    reference=article.get('published_at') or first_seen or clock.isoformat()
    basis=('portal_display' if article.get('timestamp_basis')=='portal_display' else 'published') if article.get('published_at') else 'first_seen' if first_seen else 'tracking_started'
    try:reference=moment(reference)
    except (ValueError,TypeError,AttributeError):
        reference=clock;basis='tracking_started'
    securities=[{k:s.get(k) for k in ('code','name','country')} for s in related]
    if any(not re.fullmatch(r'(?:[0-9][0-9A-Z]{5}|[A-Z][A-Z0-9]{0,5}(?:\.O)?)',s.get('code') or '') for s in securities):
        raise ValueError('종목코드 오류')
    with db() as connection:
        connection.execute('INSERT OR REPLACE INTO tracked_articles VALUES(?,?,?,?,?)',
                           (article['id'],reference.isoformat(),basis,json.dumps(securities,ensure_ascii=False),clock.timestamp()))


def record(code,quote,now=None):
    clock=moment(now or now_text());valid=False
    try:
        fetched=moment(quote['fetched_at']);traded=moment(quote['traded_at'])
        valid=(quote.get('code')==code and quote.get('status')=='ok' and
               quote.get('currency')==('USD' if code[0].isalpha() else 'KRW') and
               quote.get('source')=='Npay 증권' and isinstance(quote.get('price'),(int,float)) and
               not isinstance(quote['price'],bool) and math.isfinite(quote['price']) and quote['price']>0 and
               traded<=fetched<=clock and (clock-fetched).total_seconds()<=90)
    except (KeyError,ValueError,TypeError,AttributeError):valid=False
    with db() as connection:
        connection.execute('INSERT OR REPLACE INTO polls VALUES(?,?,?)',(code,clock.timestamp(),'ok' if valid else 'error'))
        if not valid:return False
        previous=connection.execute('SELECT payload FROM samples WHERE code=? AND trade_time=? ORDER BY id DESC LIMIT 1',(code,traded.timestamp())).fetchone()
        if previous and all(json.loads(previous['payload']).get(key)==quote.get(key)
                            for key in ('price','currency','market_status','delay_label')):
            # Re-polling the same trade is a freshness check, not a second price observation.
            return True
        saved={k:quote.get(k) for k in ('code','price','currency','traded_at','fetched_at','market_status','source','delay_label')}
        connection.execute('INSERT INTO samples(code,trade_time,observed,payload) VALUES(?,?,?,?)',
                           (code,traded.timestamp(),clock.timestamp(),json.dumps(saved,ensure_ascii=False)))
    return True


def snapshot(article_id,now=None):
    clock=moment(now or now_text())
    result={'article_id':article_id,'as_of':clock.isoformat(),'stocks':[]}
    with db() as connection:
        article=connection.execute('SELECT * FROM tracked_articles WHERE id=?',(article_id,)).fetchone()
        if not article:return result
        result.update(reference_at=article['reference_at'],reference_basis=article['reference_basis'])
        reference=moment(article['reference_at']).timestamp()
        for security in json.loads(article['stocks']):
            code=security['code']
            valid="code=? AND observed<=? AND trade_time<=?"
            values=(code,clock.timestamp(),clock.timestamp())
            latest=connection.execute('SELECT * FROM samples WHERE '+valid+' ORDER BY trade_time DESC,id DESC LIMIT 1',values).fetchone()
            base=connection.execute('SELECT * FROM samples WHERE '+valid+' AND trade_time>=? ORDER BY trade_time,id DESC LIMIT 1',(*values,reference)).fetchone()
            poll=connection.execute('SELECT * FROM polls WHERE code=?',(code,)).fetchone()
            row={**security,'baseline':json.loads(base['payload']) if base else None,
                 'latest':json.loads(latest['payload']) if latest else None,'change_percent':None,'points':[],
                 'collection_status':poll['status'] if poll else 'pending',
                 'stale':not poll or clock.timestamp()-poll['attempted']>90 or poll['status']!='ok',
                 'checked_at':datetime.fromtimestamp(poll['attempted'],timezone.utc).isoformat() if poll else None,
                 'status':'waiting_for_trade' if latest else 'pending'}
            if base and latest:
                row['status']='baseline_only'
                row['baseline_delay_seconds']=base['trade_time']-reference
                if latest['trade_time']>base['trade_time']:
                    change=100*(row['latest']['price']/row['baseline']['price']-1)
                    if abs(change)>40:
                        row['status']='large_move_unverified'
                    else:row.update(status='tracking',change_percent=change)
                points=connection.execute('SELECT * FROM (SELECT *,row_number() OVER(PARTITION BY trade_time ORDER BY id DESC) n FROM samples WHERE '+valid+' AND trade_time>=?) WHERE n=1 ORDER BY trade_time DESC LIMIT 120',(*values,base['trade_time'])).fetchall()
                points=list(reversed(points))
                if points and points[0]['trade_time']!=base['trade_time']:points.insert(0,base)
                row['points']=[{'at':p['trade_time'],'price':json.loads(p['payload'])['price']} for p in points]
            result['stocks'].append(row)
    return result


def recent(code,now=None):
    """Compare observed quotes at fixed UTC minute boundaries, never interpolate gaps."""
    clock=moment(now or now_text());end=int(clock.timestamp()//60)*60;start=end-300
    result={'status':'pending','change_percent':None,'start_at':datetime.fromtimestamp(start,timezone.utc).isoformat(),
            'end_at':datetime.fromtimestamp(end,timezone.utc).isoformat(),'source':'Npay 증권','tolerance_seconds':30}
    market='US' if code[0].isalpha() else 'KR'
    day=clock.astimezone(ZoneInfo(market_history.ZONES[market])).date().isoformat()
    with market_history.db() as connection:
        calendar=market_history.calendar_snapshot(connection,market,day,day).get(day)
    session=((calendar or {}).get('integrated') or {}).get('regularMarket') if market=='KR' else (calendar or {}).get('regularMarket')
    if not session or (calendar or {}).get('calendar_unverified'):
        return {**result,'status':'session_unverified'}
    if not moment(session['startTime']).timestamp()<=start<end<min(moment(session['endTime']).timestamp(),clock.timestamp()+1):
        return {**result,'status':'outside_session'}
    with db() as connection:
        poll=connection.execute('SELECT * FROM polls WHERE code=?',(code,)).fetchone()
        if not poll or poll['status']!='ok' or not 0<=clock.timestamp()-poll['attempted']<=90:
            return {**result,'status':'stale'}
        rows=connection.execute('SELECT * FROM (SELECT *,row_number() OVER(PARTITION BY trade_time ORDER BY id DESC) n FROM samples WHERE code=? AND observed<=? AND trade_time BETWEEN ? AND ?) WHERE n=1 ORDER BY trade_time',
                                (code,clock.timestamp(),start-30,end)).fetchall()
    points=[{'at':r['trade_time'],**json.loads(r['payload'])} for r in rows]
    first=[p for p in points if start-30<=p['at']<=start]
    last=[p for p in points if end-30<=p['at']<=end]
    if not first or not last:return result
    first,last=first[-1],last[-1]
    selected=[p for p in points if first['at']<=p['at']<=last['at']]
    if (first['at']<moment(session['startTime']).timestamp() or
            any(p.get('market_status')!='OPEN' for p in selected) or
            any(b['at']-a['at']>90 for a,b in zip(selected,selected[1:]))):
        return {**result,'status':'observation_gap'}
    change=100*(last['price']/first['price']-1)
    if abs(change)>40:return {**result,'status':'large_move_unverified'}
    return {**result,'status':'ok','change_percent':change,
            'actual_start_at':first['traded_at'],'actual_end_at':last['traded_at'],'observations':len(selected)}


def cycle():
    clock=now_text();epoch=moment(clock).timestamp()
    articles=archive.browse(limit=60)['articles']
    provenance=archive.provenance([a['url'] for a in articles])
    for article in articles:
        first_seen=provenance.get(article['url'],{}).get('first_seen_at')
        try:reference=moment(article.get('published_at') or first_seen or clock).timestamp()
        except (ValueError,TypeError,AttributeError):continue
        if not 0<=epoch-reference<=ACTIVE_SECONDS:continue
        related=stocks.related_stocks(article['title'],article.get('published_at'))
        register(article,related,first_seen,clock)
    # Keep reviewed theme members observable even without a new article mentioning them.
    members=business_ontology.snapshot()['memberships']
    securities={m['code']:m['security'] for m in members if m['kind']=='business'}
    register({'id':'market-watch','published_at':clock},list(securities.values()),now=clock)
    with db() as connection:
        # Round-robin by last attempt keeps a popular ticker from starving other active stocks.
        codes=[r['code'] for r in connection.execute("""
            SELECT DISTINCT json_extract(s.value,'$.code') code,coalesce(p.attempted,0) attempted
            FROM tracked_articles a,json_each(a.stocks) s
            LEFT JOIN polls p ON p.code=json_extract(s.value,'$.code')
            WHERE a.last_seen>=? ORDER BY attempted,code LIMIT 20""",(epoch-ACTIVE_SECONDS,))]
    with stocks.LOCK:codes=[c for c in codes if c in stocks.CATALOGUE]
    if codes:
        quotes=stocks.get_quotes(codes)
        for code in codes:record(code,quotes.get(code,{}))
    return len(codes)


def collector():
    with lease('price-tracker.lock') as acquired:
        if not acquired:return
        while True:
            try:cycle()
            except Exception as error:
                print('뉴스 시세 추적 재시도: '+type(error).__name__,flush=True)
            time.sleep(10)
