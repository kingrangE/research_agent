"""Read-only Toss daily candles, immutable source responses and coverage quality."""

import argparse
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, HTTPRedirectHandler, build_opener
from zoneinfo import ZoneInfo

PATH = Path(__file__).resolve().parent / '.data' / 'market.sqlite3'
BASE = 'https://openapi.tossinvest.com'
SPEC = BASE + '/openapi-docs/latest/openapi.json'
POLICY = 'toss-daily-v1'
ZONES = {'KR':'Asia/Seoul', 'US':'America/New_York'}
INDICES = {'KOSPI', 'KOSDAQ'}


def now():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':'), allow_nan=False)


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('시각에 시간대가 없습니다')
    return parsed


def identity(market, symbol):
    pattern = r'[0-9][A-Z0-9]{5}' if market == 'KR' else r'[A-Z][A-Z0-9.-]{0,14}'
    if (market not in ZONES or (symbol in INDICES and market!='KR') or
            (not (market == 'KR' and symbol in INDICES) and not re.fullmatch(pattern, symbol))):
        raise ValueError('지원하지 않는 시장·종목 식별자')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('시세 API 리다이렉트 거부')


class RateLimited(ValueError):
    def __init__(self, seconds):
        self.retry_at = time.time()+seconds
        super().__init__(f'토스 HTTP 429 · {seconds}초 후 재시도 가능')


class Toss:
    def __init__(self):
        self.token = None
        self.expires = 0
        self.last_request = 0
        self.open = build_opener(NoRedirect()).open

    def request(self, path, params=None, auth=False):
        # Fixed host and allowlisted read routes keep tokens away from arbitrary URLs/orders.
        allowed = path in ('/api/v1/candles','/api/v1/stocks','/api/v1/exchange-rate') or path in (
            '/api/v1/market-calendar/KR','/api/v1/market-calendar/US',
            '/api/v1/market-indicators/KOSPI/candles','/api/v1/market-indicators/KOSDAQ/candles')
        if not (auth and path == '/oauth2/token') and not (not auth and allowed):
            raise ValueError('허용되지 않은 시세 조회 경로')
        if not auth and (not self.token or time.monotonic() >= self.expires):
            client_id, secret = os.environ.get('TOSS_CLIENT_ID'), os.environ.get('TOSS_CLIENT_SECRET')
            if not client_id or not secret:
                raise ValueError('TOSS_CLIENT_ID·TOSS_CLIENT_SECRET 설정 필요')
            token = self.request('/oauth2/token', {'grant_type':'client_credentials',
                'client_id':client_id,'client_secret':secret}, auth=True)
            if (not isinstance(token.get('access_token'),str) or not re.fullmatch(r'[A-Za-z0-9._~+/=-]{1,16384}',token['access_token']) or
                    token.get('token_type') != 'Bearer' or type(token.get('expires_in')) is not int or token['expires_in'] <= 0):
                raise ValueError('토스 인증 응답 형식 오류')
            self.token = token['access_token']
            self.expires = time.monotonic() + max(1, token['expires_in']-60)
        time.sleep(max(0, .4-(time.monotonic()-self.last_request)))
        headers = {'Accept':'application/json'}
        body = None
        url = BASE + path
        if auth:
            body = urlencode(params).encode()
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        else:
            headers['Authorization'] = 'Bearer ' + self.token
            if params:
                url += '?' + urlencode(params)
        self.last_request = time.monotonic()
        try:
            with self.open(Request(url, data=body, headers=headers), timeout=20) as response:
                raw = response.read(2_000_001)
            if len(raw)>2_000_000:
                raise ValueError('토스 응답 크기 초과')
            result = json.loads(raw)
        except HTTPError as error:
            retry = error.headers.get('Retry-After','')
            if error.code == 429:
                raise RateLimited(max(1,int(retry)) if retry.isdecimal() else 60) from None
            delay = f' · Retry-After {retry}초' if retry.isdecimal() else ''
            raise ValueError(f'토스 HTTP {error.code}{delay} · 인증·허용 IP·호출 한도 확인') from None
        except (OSError, json.JSONDecodeError):
            raise ValueError('토스 연결 또는 JSON 응답 오류') from None
        if not isinstance(result,dict) or ('error' in result and result['error']):
            raise ValueError('토스 응답 오류 · 원문 오류 내용은 비밀 보호를 위해 출력하지 않음')
        return result


@contextmanager
def db():
    PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS responses (
                    id INTEGER PRIMARY KEY, market TEXT, symbol TEXT, kind TEXT, params TEXT,
                    payload TEXT, fingerprint TEXT, observed_at TEXT);
                CREATE TABLE IF NOT EXISTS bars (
                    id INTEGER PRIMARY KEY, market TEXT, symbol TEXT, adjusted INTEGER, day TEXT,
                    fingerprint TEXT, payload TEXT, response_id INTEGER, observed_at TEXT, last_seen TEXT);
                CREATE INDEX IF NOT EXISTS bars_series ON bars(market,symbol,adjusted,day,id);
                CREATE TABLE IF NOT EXISTS calendars (
                    market TEXT, day TEXT, payload TEXT, response_id INTEGER, PRIMARY KEY(market,day));
                CREATE TABLE IF NOT EXISTS jobs (key TEXT PRIMARY KEY, payload TEXT);
            ''')
            yield connection
    finally:
        connection.close()


def save_response(connection, market, symbol, kind, params, response):
    payload = encode(response)
    return connection.execute('INSERT INTO responses(market,symbol,kind,params,payload,fingerprint,observed_at) VALUES(?,?,?,?,?,?,?)',
        (market,symbol,kind,encode(params),payload,sha256(payload.encode()).hexdigest(),now())).lastrowid


def normalize(response, market, symbol, adjusted):
    identity(market,symbol)
    result = response.get('result')
    if not isinstance(result,dict) or not isinstance(result.get('candles'),list) or len(result['candles'])>200:
        raise ValueError('일봉 목록 형식 오류')
    rows, seen = [], set()
    for item in result['candles']:
        if not isinstance(item,dict) or not isinstance(item.get('timestamp'),str):
            raise ValueError('일봉 항목 형식 오류')
        stamp = timestamp(item['timestamp'])
        local = stamp.astimezone(ZoneInfo(ZONES[market]))
        if symbol not in INDICES and (local.hour,local.minute,local.second,local.microsecond)!=(0,0,0,0):
            raise ValueError('일봉 현지 거래일 자정 기준 불일치')
        day = local.date().isoformat()
        if day in seen:
            raise ValueError('응답 내 일봉 날짜 중복')
        seen.add(day)
        values = {}
        for key in ('openPrice','highPrice','lowPrice','closePrice','volume'):
            raw = item.get(key)
            if not isinstance(raw,str) or len(raw)>30 or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?',raw):
                raise ValueError('가격·거래량 형식 오류')
            try:
                value = Decimal(raw)
            except InvalidOperation:
                raise ValueError('가격·거래량 숫자 오류') from None
            if not value.is_finite() or value<0:
                raise ValueError('가격·거래량 범위 오류')
            values[key] = value
        if (values['lowPrice']>min(values['openPrice'],values['closePrice']) or
                values['highPrice']<max(values['openPrice'],values['closePrice']) or values['closePrice']<=0):
            raise ValueError('OHLC 가격 관계 오류')
        currency = 'POINT' if symbol in INDICES else item.get('currency')
        if currency != ('POINT' if symbol in INDICES else 'KRW' if market=='KR' else 'USD'):
            raise ValueError('시장과 통화 불일치')
        rows.append({'day':day,'timestamp':item['timestamp'],
            **{k:str(v) for k,v in values.items()},'currency':currency,
            'turnover':None,'adjusted':adjusted,'policy_version':POLICY,
            'completion':'provisional' if day>=datetime.now(ZoneInfo(ZONES[market])).date().isoformat() else 'past_day',
            'suspension':'unknown','corporate_actions':'unavailable',
            'zero_ohlc':any(values[k]==0 for k in ('openPrice','highPrice','lowPrice'))})
    cursor = result.get('nextBefore')
    if cursor is not None:
        timestamp(cursor)
    return rows, cursor


def save_page(connection, market, symbol, adjusted, params, response, since, until):
    rows, cursor = normalize(response,market,symbol,adjusted)
    response_id = save_response(connection,market,symbol,'candles',params,response)
    inserted = 0
    for row in rows:
        if not since<=row['day']<=until:
            continue
        payload = encode(row)
        fingerprint = sha256(payload.encode()).hexdigest()
        previous = connection.execute('SELECT id,fingerprint FROM bars WHERE market=? AND symbol=? AND adjusted=? AND day=? ORDER BY id DESC LIMIT 1',
            (market,symbol,int(adjusted),row['day'])).fetchone()
        if previous and previous['fingerprint']==fingerprint:
            connection.execute('UPDATE bars SET last_seen=? WHERE id=?',(now(),previous['id']))
        else:
            connection.execute('''INSERT INTO bars(market,symbol,adjusted,day,fingerprint,payload,response_id,observed_at,last_seen)
                VALUES(?,?,?,?,?,?,?,?,?)''',(market,symbol,int(adjusted),row['day'],fingerprint,payload,response_id,now(),now()))
            inserted += 1
    return rows, cursor, inserted


def save_calendar(connection, market, requested, response):
    result = response.get('result')
    if not isinstance(result,dict) or not isinstance(result.get('today'),dict) or result['today'].get('date')!=requested:
        raise ValueError('거래일 캘린더 기준일 불일치')
    response_id = save_response(connection,market,'','calendar',{'date':requested},response)
    for key in ('today','previousBusinessDay','nextBusinessDay'):
        item = result.get(key)
        if not isinstance(item,dict):
            raise ValueError('거래일 캘린더 형식 오류')
        date.fromisoformat(item['date'])
        if (market=='KR' and ('integrated' not in item or item['integrated'] is not None and not isinstance(item['integrated'],dict))) or (market=='US' and 'regularMarket' not in item):
            raise ValueError('거래일 개장·휴장 상태 미확인')
        sessions = item.get('integrated') if market=='KR' else item
        session = sessions.get('regularMarket') if isinstance(sessions,dict) else None
        if session is not None:
            if timestamp(session['startTime'])>=timestamp(session['endTime']):
                raise ValueError('거래 세션 시각 오류')
        payload = {**item,'regular_open':session is not None}
        connection.execute('INSERT OR REPLACE INTO calendars VALUES(?,?,?,?)',(market,item['date'],encode(payload),response_id))


def collect(market, symbol, since, until, pages=3, adjusted=False, client=None):
    identity(market,symbol)
    start,end = date.fromisoformat(since),date.fromisoformat(until)
    if start>end or (end-start).days>366 or type(pages) is not int or not 1<=pages<=100:
        raise ValueError('수집 기간은 최대 367일, 페이지는 1~100이어야 합니다')
    key = encode([market,symbol,since,until,adjusted,POLICY])
    with db() as connection:
        previous = connection.execute('SELECT payload FROM jobs WHERE key=?',(key,)).fetchone()
    job = json.loads(previous[0]) if previous else {}
    if job.get('retry_after',0)>time.time():
        return job
    if job.get('status')=='complete':
        job = {}
    zone = ZoneInfo(ZONES[market])
    before = job.get('before') or datetime.combine(end,datetime.max.time(),zone).isoformat()
    job.update(market=market,symbol=symbol,since=since,until=until,adjusted=adjusted,status='running',error=None,retry_after=0,
               policy_version=POLICY,updated_at=now(),before=before)
    client = client or Toss()
    try:
        if symbol not in INDICES:
            meta = client.request('/api/v1/stocks',{'symbols':symbol})
            matches = [x for x in meta.get('result',[]) if isinstance(x,dict) and x.get('symbol')==symbol]
            if (len(matches)!=1 or len(meta.get('result',[]))!=1 or matches[0].get('currency')!=('KRW' if market=='KR' else 'USD') or
                    matches[0].get('market') not in (('KOSPI','KOSDAQ','KR_ETC') if market=='KR' else ('NYSE','NASDAQ','AMEX','US_ETC'))):
                raise ValueError('종목 기본정보·시장 불일치')
            for field in ('listDate','delistDate'):
                if matches[0].get(field) is not None:
                    date.fromisoformat(matches[0][field])
            with db() as connection:
                save_response(connection,market,symbol,'security',{'symbols':symbol},meta)
        for _ in range(0 if job.get('prices_complete') else pages):
            params = {'interval':'1d','count':200,'before':before}
            if symbol not in INDICES:
                params.update(symbol=symbol,adjusted=str(adjusted).lower())
            path = f'/api/v1/market-indicators/{symbol}/candles' if symbol in INDICES else '/api/v1/candles'
            response = client.request(path,params)
            rows, cursor = normalize(response,market,symbol,adjusted)
            if any(timestamp(x['timestamp'])>timestamp(before) for x in rows):
                raise ValueError('페이지 기준 이후 일봉 응답')
            if cursor is not None and timestamp(cursor)>=timestamp(before):
                raise ValueError('페이지 커서 진행 없음')
            complete = not rows or cursor is None or min(x['day'] for x in rows)<=since
            with db() as connection:
                save_page(connection,market,symbol,adjusted,params,response,since,until)
                job.update(before=cursor,prices_complete=complete,updated_at=now())
                connection.execute('INSERT OR REPLACE INTO jobs VALUES(?,?)',(key,encode(job)))
            if complete:
                break
            before = cursor
        # Bounded calendar reconciliation; repeated runs resume uncovered dates.
        requested = start
        calls = 0
        while requested<=end:
            day = requested.isoformat()
            with db() as connection:
                known = connection.execute('SELECT 1 FROM calendars WHERE market=? AND day=?',(market,day)).fetchone()
            if not known:
                if calls>=20:
                    break
                response = client.request(f'/api/v1/market-calendar/{market}',{'date':day})
                with db() as connection:
                    save_calendar(connection,market,day,response)
                calls += 1
            requested += timedelta(days=1)
        job.update(calendar_complete=requested>end,status='complete' if requested>end and job.get('prices_complete') else 'partial')
    except Exception as error:
        message = str(error) if isinstance(error,ValueError) else f'수집 오류 ({type(error).__name__})'
        job.update(status='error',error=message)
        if isinstance(error,RateLimited):
            job['retry_after'] = error.retry_at
    job['updated_at'] = now()
    with db() as connection:
        connection.execute('INSERT OR REPLACE INTO jobs VALUES(?,?)',(key,encode(job)))
    return job


def coverage(market=None, symbol=None):
    if market is not None:
        identity(market,symbol)
    if not PATH.exists():
        jobs,series = [],[]
    else:
        with db() as connection:
            jobs = [json.loads(r[0]) for r in connection.execute('SELECT payload FROM jobs')]
            for job in jobs:
                calendar = connection.execute('SELECT day,payload FROM calendars WHERE market=? AND day BETWEEN ? AND ?',
                    (job['market'],job['since'],job['until'])).fetchall()
                days = {r[0] for r in connection.execute('SELECT DISTINCT day FROM bars WHERE market=? AND symbol=? AND adjusted=? AND day BETWEEN ? AND ?',
                    (job['market'],job['symbol'],int(job['adjusted']),job['since'],job['until']))}
                meta=connection.execute("SELECT payload FROM responses WHERE market=? AND symbol=? AND kind='security' ORDER BY id DESC LIMIT 1",(job['market'],job['symbol'])).fetchone()
                security=json.loads(meta[0])['result'][0] if meta else {}
                outside=[r[0] for r in calendar if (security.get('listDate') and r[0]<security['listDate']) or
                         (security.get('delistDate') and r[0]>security['delistDate'])]
                job.update(missing_open_days=[r[0] for r in calendar if json.loads(r[1])['regular_open'] and r[0] not in days and r[0] not in outside],
                    outside_current_master_listing_days=outside,
                    calendar_unknown_days=(date.fromisoformat(job['until'])-date.fromisoformat(job['since'])).days+1-len(calendar))
                job['coverage_status']='incomplete' if job['calendar_unknown_days'] or not job.get('prices_complete') else 'gaps' if job['missing_open_days'] else 'checked'
            series = []
            for row in connection.execute('SELECT market,symbol,adjusted,count(DISTINCT day) days,count(*) versions,min(day) first,max(day) last,max(last_seen) updated_at FROM bars GROUP BY market,symbol,adjusted'):
                item = dict(row)
                current = connection.execute('''SELECT payload FROM bars b WHERE market=? AND symbol=? AND adjusted=?
                    AND id=(SELECT max(id) FROM bars WHERE market=b.market AND symbol=b.symbol AND adjusted=b.adjusted AND day=b.day) ORDER BY day''',
                    (row['market'],row['symbol'],row['adjusted'])).fetchall()
                days = {json.loads(x[0])['day'] for x in current}
                calendar = connection.execute('SELECT day,payload FROM calendars WHERE market=? AND day BETWEEN ? AND ?',
                    (row['market'],row['first'],row['last'])).fetchall()
                known = {r[0]:json.loads(r[1]) for r in calendar}
                meta = connection.execute("SELECT id,payload,observed_at FROM responses WHERE market=? AND symbol=? AND kind='security' ORDER BY id DESC LIMIT 1",(row['market'],row['symbol'])).fetchone()
                security = json.loads(meta['payload'])['result'][0] if meta else None
                item.update(missing_open_days=[day for day,v in known.items() if v['regular_open'] and day not in days],
                    calendar_days_checked=len(known),suspension_history='unavailable',corporate_actions='unavailable',turnover='unavailable',
                    timezone=ZONES[row['market']],security=security,security_response_id=meta['id'] if meta else None,
                    security_observed_at=meta['observed_at'] if meta else None,
                    historical_identity='current_metadata_only',
                    adjustment_policy='provider_adjusted_at_retrieval_not_point_in_time' if row['adjusted'] else 'raw_no_corporate_action_correction')
                series.append(item)
    if market:
        jobs=[j for j in jobs if j['market']==market and j['symbol']==symbol]
        series=[s for s in series if s['market']==market and s['symbol']==symbol]
    return {'provider':'Toss Open API','spec_url':SPEC,'policy_version':POLICY,
        'configured':bool(os.environ.get('TOSS_CLIENT_ID') and os.environ.get('TOSS_CLIENT_SECRET')),
        'usage':'개인투자자 본인 매매 목적 · 제3자 제공·상업적 활용 미지원',
        'minute_history':'not_implemented','us_index_history':'unsupported_by_selected_api',
        'corporate_actions':'unavailable','jobs':jobs,'series':series}


def observations(market,symbol,adjusted=False,until=None):
    identity(market,symbol)
    if until is not None:date.fromisoformat(until)
    if not PATH.exists():
        return []
    with db() as connection:
        rows = connection.execute('''SELECT b.* FROM bars b WHERE market=? AND symbol=? AND adjusted=? AND (? IS NULL OR day<=?)
            AND id=(SELECT max(id) FROM bars WHERE market=b.market AND symbol=b.symbol AND adjusted=b.adjusted AND day=b.day)
            ORDER BY day DESC LIMIT 400''',(market,symbol,int(adjusted),until,until)).fetchall()
    return [{**json.loads(r['payload']),'revision':r['id'],'response_id':r['response_id'],
             'observed_at':r['observed_at'],'last_seen':r['last_seen']} for r in rows]


def source_response(response_id):
    if type(response_id) is not int or response_id<=0:
        raise ValueError('응답 식별자 오류')
    if not PATH.exists():
        return None
    with db() as connection:
        row=connection.execute('SELECT * FROM responses WHERE id=?',(response_id,)).fetchone()
    if not row:
        return None
    result=dict(row)
    path = (f'/api/v1/market-calendar/{row["market"]}' if row['kind']=='calendar' else
            '/api/v1/stocks' if row['kind']=='security' else
            '/api/v1/exchange-rate' if row['kind']=='fx' else
            f'/api/v1/market-indicators/{row["symbol"]}/candles' if row['symbol'] in INDICES else '/api/v1/candles')
    result['source_url']=BASE+path+'?'+urlencode(json.loads(row['params']))
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description='토스 과거 일봉 수집 · 주문/계좌 API 미사용')
    parser.add_argument('--market',choices=('KR','US'),required=True)
    parser.add_argument('--symbol',required=True)
    parser.add_argument('--since',required=True)
    parser.add_argument('--until',required=True)
    parser.add_argument('--pages',type=int,default=3)
    parser.add_argument('--adjusted',action='store_true')
    args=parser.parse_args()
    try:
        result=collect(args.market,args.symbol,args.since,args.until,args.pages,args.adjusted)
        print(encode(result))
        raise SystemExit(1 if result['status']=='error' else 0)
    except ValueError as error:
        print(str(error))
        raise SystemExit(1)
