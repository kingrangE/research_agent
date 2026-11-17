"""Toss stock 1m candles end at timestamp; keep immutable inputs and abstain on gaps."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import statistics
import json
import time
import re
from zoneinfo import ZoneInfo
import business_ontology as business
import market_history as h


def prepare(connection):
    connection.executescript('''
        CREATE TABLE IF NOT EXISTS minute_bars(market TEXT,symbol TEXT,ended REAL,payload TEXT,fingerprint TEXT,response_id INTEGER,observed_at TEXT,
            CHECK(ended>0));
        CREATE INDEX IF NOT EXISTS minute_series ON minute_bars(market,symbol,ended);
        CREATE TABLE IF NOT EXISTS minute_progress(market TEXT,symbol TEXT,cursor TEXT,attempted REAL,state TEXT,PRIMARY KEY(market,symbol));
    ''')


def store(market,symbol,response,params,now=None):
    h.identity(market,symbol);clock=h.timestamp(now or h.now()).astimezone(timezone.utc)
    candles=response.get('result',{}).get('candles')
    if not isinstance(candles,list) or len(candles)>200:raise ValueError('분봉 응답 오류')
    parsed=[]
    for candle in candles:
        for key in ('openPrice','highPrice','lowPrice','closePrice','volume'):
            raw=candle.get(key)
            if not isinstance(raw,str) or len(raw)>30 or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?',raw):
                raise ValueError('분봉 숫자 형식 오류')
        end=h.timestamp(candle['timestamp']).astimezone(timezone.utc)
        volume=Decimal(candle['volume'])
        if (end.second or end.microsecond or end>clock or not volume.is_finite() or volume<0 or
            candle.get('currency')!=('KRW' if market=='KR' else 'USD')):raise ValueError('분봉 시각·거래량 오류')
        for key in ('openPrice','highPrice','lowPrice','closePrice'):
            value=Decimal(candle[key])
            if not value.is_finite() or value<=0:raise ValueError('분봉 가격 오류')
        values={key:Decimal(candle[key]) for key in ('openPrice','highPrice','lowPrice','closePrice')}
        if not values['lowPrice']<=min(values['openPrice'],values['closePrice'])<=max(values['openPrice'],values['closePrice'])<=values['highPrice']:
            raise ValueError('분봉 고가·저가 오류')
        payload=h.encode(candle);parsed.append((end.timestamp(),payload,sha256(payload.encode()).hexdigest()))
    with h.db() as connection:
        prepare(connection)
        fresh=[]
        for row in parsed:
            previous=connection.execute('SELECT fingerprint FROM minute_bars WHERE market=? AND symbol=? AND ended=? ORDER BY rowid DESC LIMIT 1',(market,symbol,row[0])).fetchone()
            if not previous or previous['fingerprint']!=row[2]:fresh.append(row)
        if fresh:
            source=h.save_response(connection,market,symbol,'stock-minute-end-v1',params,response)
            for end,payload,fingerprint in fresh:
                connection.execute('INSERT OR IGNORE INTO minute_bars VALUES(?,?,?,?,?,?,?)',(market,symbol,end,payload,fingerprint,source,clock.isoformat()))
    return len(fresh)


def compare(market,symbol,now=None):
    h.identity(market,symbol);clock=h.timestamp(now or h.now()).astimezone(timezone.utc);end=int(clock.timestamp()//60)*60
    result={'status':'collecting','ratio':None,'valid_days':0,'required_days':15,'source':'토스증권 Open API','as_of':clock.isoformat()}
    zone=ZoneInfo(h.ZONES[market]);day=clock.astimezone(zone).date()
    with h.db() as connection:
        prepare(connection)
        calendars=h.calendar_snapshot(connection,market,(day-timedelta(days=45)).isoformat(),day.isoformat())
        rows=connection.execute('SELECT * FROM minute_bars WHERE market=? AND symbol=? AND ended>=? AND ended<=? AND observed_at<=? ORDER BY rowid',
                                (market,symbol,end-46*86400,end,clock.isoformat())).fetchall()
    bars={r['ended']:r for r in rows}
    def interval(calendar,offset=None):
        if not calendar or not calendar.get('regular_open') or calendar.get('calendar_unverified'):return None
        session=(calendar.get('integrated') or {}).get('regularMarket') if market=='KR' else calendar.get('regularMarket')
        if not session:return None
        opened=h.timestamp(session['startTime']).timestamp();closed=h.timestamp(session['endTime']).timestamp()
        stop=end if offset is None else opened+offset
        if not opened<=stop-300<stop<=closed:return None
        selected=[bars.get(stop-60*i) for i in range(5)]
        if any(row is None for row in selected):return None
        volume=sum(Decimal(json.loads(row['payload'])['volume']) for row in selected)
        return volume,stop-opened,selected
    current=interval(calendars.get(day.isoformat()))
    if not current:return result
    prior=[]
    dates=sorted((d for d,c in calendars.items() if d<day.isoformat() and c.get('regular_open')),reverse=True)[:20]
    for date in dates:
        sample=interval(calendars[date],current[1])
        if sample:prior.append(sample[0])
    result['valid_days']=len(prior)
    if len(prior)<15:return result
    base=statistics.median(prior)
    # shortcut: volume-only comparison cannot fully verify corporate actions, withhold until reviewed.
    if base<1000:return {**result,'status':'low_liquidity'}
    return {**result,'status':'review_required','baseline_volume':str(base),'current_volume':str(current[0]),
            'unreviewed_ratio':float(current[0]/base),'ratio':None,
            'reason':'기업행동·거래정지 비교 검수 전'}


def collect(client):
    """One bounded page per worker turn; never create a parallel token owner."""
    members=business.snapshot()['memberships']
    targets=sorted({(m['security']['country'],m['security']['provider_symbol']) for m in members if m['kind']=='business'})
    with h.db() as connection:
        prepare(connection)
        attempts={(r['market'],r['symbol']):dict(r) for r in connection.execute('SELECT * FROM minute_progress')}
    if attempts.get(('*','*'),{}).get('attempted',0)>time.time():return {'state':'rate_limited'}
    market,symbol=min(targets,key=lambda pair:attempts.get(pair,{}).get('attempted',0))
    previous=attempts.get((market,symbol),{});cursor=previous.get('cursor')
    params={'symbol':symbol,'interval':'1m','count':200,'adjusted':'false'}
    if cursor:params['before']=cursor
    state='error';next_cursor=cursor
    try:
        response=client.request('/api/v1/candles',params)
        store(market,symbol,response,params)
        candidate=response.get('result',{}).get('nextBefore')
        if candidate is None:next_cursor=None
        if candidate:
            parsed=h.timestamp(candidate)
            next_cursor=candidate
            if parsed < datetime.now(timezone.utc)-timedelta(days=45) or (cursor and parsed>=h.timestamp(cursor)):next_cursor=None
        state='collecting' if next_cursor else 'source_exhausted'
        return {'state':state,'market':market,'symbol':symbol}
    except h.RateLimited as error:
        with h.db() as connection:
            prepare(connection)
            connection.execute('INSERT OR REPLACE INTO minute_progress VALUES(?,?,?,?,?)',('*','*',None,error.retry_at,'rate_limited'))
        raise
    except ValueError as error:
        message=str(error)
        if message.startswith(('분봉','토스 HTTP','토스 연결','토스 응답')):state='error:'+message[:120]
        raise
    finally:
        with h.db() as connection:
            prepare(connection)
            connection.execute('INSERT OR REPLACE INTO minute_progress VALUES(?,?,?,?,?)',(market,symbol,next_cursor,time.time(),state))
