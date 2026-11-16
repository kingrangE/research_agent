"""Reproducible daily observations, not post-discovery trading returns or causal effects."""

import argparse
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from hashlib import sha256
import json
import math
import re

import event_facts
import market_history as h

VERSION='daily-reaction-v1'


def sessions(calendar,market):
    result=[]
    for day,row in sorted(calendar.items()):
        if not row['regular_open'] or row.get('calendar_unverified'):continue
        session=(row.get('integrated') or {}).get('regularMarket') if market=='KR' else row.get('regularMarket')
        if not session:raise ValueError('개장 캘린더에 세션 누락')
        result.append({'day':day,'open':session['startTime'],'close':session['endTime'],'response_id':row.get('response_id'),
                       **({'calendar_reference':row['calendar_reference'],'calendar_source_conflict':row.get('calendar_source_conflict',False)} if row.get('calendar_reference') else {})})
    return result


def fit_model(pairs):
    if len(pairs)<60:return {'status':'insufficient_estimation','samples':len(pairs),'alpha':None,'beta':None}
    ys,xs=zip(*pairs);mx=math.fsum(xs)/len(xs);my=math.fsum(ys)/len(ys)
    variance=math.fsum((x-mx)**2 for x in xs)
    if variance<=1e-20:return {'status':'zero_market_variance','samples':len(pairs),'alpha':None,'beta':None}
    beta=math.fsum((x-mx)*(y-my) for y,x in pairs)/variance
    return {'status':'estimated','samples':len(pairs),'alpha':my-beta*mx,'beta':beta}


def ratio(a,b):return float(Decimal(b)/Decimal(a)-1)


def price_return(rows,start,end,clock):
    a,b=rows.get(start['day']),rows.get(end['day'])
    if not a or not b:return None,'missing_price'
    if h.timestamp(end['close'])>clock:return None,'window_not_closed'
    if any(r.get('completion')!='past_day' for r in (a,b)):return None,'provisional_price'
    if any(r.get('zero_ohlc') or Decimal(r['volume'])<=0 for r in (a,b)):return None,'zero_volume_or_suspension'
    if any(r.get('corporate_action') for r in (a,b)):return None,'corporate_action_unresolved'
    value=ratio(a['closePrice'],b['closePrice'])
    if not b['adjusted'] and abs(value)>.4:return None,'large_move_corporate_action_unverified'
    return value,'observed_with_quality_limits'


def calendar_complete(calendar,start,end):
    current=datetime.fromisoformat(start).date();last=datetime.fromisoformat(end).date()
    while current<=last:
        if current.isoformat() not in calendar or calendar[current.isoformat()].get('calendar_unverified'):return False
        current+=timedelta(days=1)
    return True


def calculate(inputs):
    event,market=inputs['event'],inputs['market'];clock=h.timestamp(inputs['as_of'])
    points=sessions(inputs['calendar'],market)
    stocks={r['day']:r for r in inputs['stock_prices']};bench={r['day']:r for r in inputs['benchmark_prices']}
    source_time=event.get('published_at') if inputs['basis']=='public' else event.get('available_at')
    result={'version':VERSION,'article_id':event['article_id'],'event_id':event['event_id'],'source_key':event['source_key'],
        'market':market,'symbol':inputs['symbol'],'benchmark':inputs['benchmark'],'basis':inputs['basis'],'as_of':inputs['as_of'],
        'event_time':source_time,'event_rule_version':event['rule_version'],'event_review_status':event['review_status'],
        'price_vintage':'retrieved_versions_not_point_in_time',
        'benchmark_kind':'ETF_proxy_not_index' if inputs['benchmark']=='SPY' else 'domestic_index',
        'adjusted':inputs['adjusted'],'windows':[],'alignment':None,'status':'event_time_unknown',
        'quality':['corporate_actions_unavailable','historical_suspension_unavailable','concurrent_events_not_excluded'],
        'claim':'가격 반응 관측 · 기사 발견 이후 매매 수익이나 인과 효과가 아님'}
    if inputs.get('calendar_policy'):result['calendar_policy']=inputs['calendar_policy']
    if any(c.get('calendar_source_conflict') for c in inputs['calendar'].values()):result['quality'].append('vendor_calendar_conflicts_corrected_with_exchange_sources')
    if not source_time:return result
    event_time=h.timestamp(source_time)
    if event_time>clock:return {**result,'status':'event_not_yet_available'}
    localday=event_time.astimezone(h.ZoneInfo(h.ZONES[market])).date().isoformat()
    i=next((i for i,p in enumerate(points) if h.timestamp(p['close'])>event_time),None)
    if i is None or not calendar_complete(inputs['calendar'],localday,points[i]['day']):
        return {**result,'status':'calendar_or_future_session_missing'}
    result['alignment']='intraday' if h.timestamp(points[i]['open'])<=event_time else 'before_open_or_closed_market'
    model_pairs=[];model_days=[]
    for k in range(max(1,i-120),i):
        a,b=points[k-1],points[k]
        if not calendar_complete(inputs['calendar'],a['day'],b['day']):continue
        y,_=price_return(stocks,a,b,clock);x,_=price_return(bench,a,b,clock)
        if y is not None and x is not None:model_pairs.append((y,x));model_days.append(b['day'])
    model=fit_model(model_pairs)
    model.update(window_target=120,minimum=60,first_day=model_days[0] if model_days else None,last_day=model_days[-1] if model_days else None)
    result['model']=model;result['status']='calculated'
    for name,left,right in (('pre_event',i-2,i-1),('event_day',i-1,i),('next_session',i,i+1)):
        window={'name':name,'raw_return':None,'market_return':None,'abnormal_return':None,'volume_change':None,'turnover_change':None,
                'start':None,'end':None,'status':'session_missing','input_prices':[],
                'includes_pre_event_movement':name=='event_day' and result['alignment']=='intraday'}
        if left>=0 and right<len(points):
            start,end=points[left],points[right];window.update(start=start,end=end)
            if not calendar_complete(inputs['calendar'],start['day'],end['day']):
                window['status']='calendar_gap'
            else:
                raw,status=price_return(stocks,start,end,clock);market_return,market_status=price_return(bench,start,end,clock)
                window.update(raw_return=raw,market_return=market_return,status=status,market_status=market_status)
                if raw is not None and market_return is not None and model['status']=='estimated':
                    window['abnormal_return']=raw-model['alpha']-model['beta']*market_return
                window['input_prices']=[{'series':label,**rows[p['day']]} for label,rows in (('stock',stocks),('benchmark',bench)) for p in (start,end) if p['day'] in rows]
                if raw is not None:
                    baseline=[Decimal(stocks[p['day']]['volume']) for p in points[max(0,right-20):right] if p['day'] in stocks and stocks[p['day']]['completion']=='past_day' and Decimal(stocks[p['day']]['volume'])>0]
                    if len(baseline)>=5:
                        mean=sum(baseline)/len(baseline)
                        window['volume_change']=float(Decimal(stocks[end['day']]['volume'])/mean-1)
                    window['volume_baseline_samples']=len(baseline)
        if inputs.get('calendar_policy') and window['start'] and window['end']:
            window['calendar_evidence']=[{'day':d,'response_id':c.get('response_id'),'reference':c['calendar_reference'],'source_conflict':c.get('calendar_source_conflict',False)}
                for d,c in inputs['calendar'].items() if window['start']['day']<=d<=window['end']['day'] and c.get('calendar_reference')]
        result['windows'].append(window)
    return result


def load_inputs(article_id,market,symbol,benchmark=None,basis='public',adjusted=False,as_of=None):
    h.identity(market,symbol)
    benchmark=benchmark or ('KOSPI' if market=='KR' else 'SPY');h.identity(market,benchmark)
    if benchmark not in (('KOSPI','KOSDAQ') if market=='KR' else ('SPY',)):raise ValueError('지원하지 않는 시장 기준')
    if basis not in ('public','available') or type(adjusted) is not bool:raise ValueError('반응 기준 오류')
    moment=h.timestamp(as_of or h.now())
    proposals=event_facts.snapshot([article_id])['proposals']
    event=next((p for p in proposals if p['axis']),None)
    if not event:raise ValueError('분류된 사건 제안 없음')
    event_time=event.get('published_at') if basis=='public' else event.get('available_at')
    day=h.timestamp(event_time).astimezone(h.ZoneInfo(h.ZONES[market])).date() if event_time else None
    with h.db() as db:
        calendar=h.calendar_snapshot(db,market,(day-timedelta(days=210)).isoformat(),(day+timedelta(days=10)).isoformat()) if day else {}
    after=[p for p in sessions(calendar,market) if event_time and h.timestamp(p['close'])>h.timestamp(event_time)]
    until=after[min(1,len(after)-1)]['day'] if after else h.timestamp(event_time).astimezone(h.ZoneInfo(h.ZONES[market])).date().isoformat() if event_time else None
    return {'event':{k:event.get(k) for k in ('article_id','event_id','source_key','rule_version','published_at','available_at','review_status','url')},
        'calendar_policy':h.CALENDAR_POLICY,'market':market,'symbol':symbol,'benchmark':benchmark,'basis':basis,'adjusted':adjusted,'as_of':moment.isoformat(),
        'stock_prices':h.observations(market,symbol,adjusted,until=until) if day else [],
        'benchmark_prices':h.observations(market,benchmark,adjusted if market=='US' else False,until=until) if day else [],'calendar':calendar}


def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS reaction_runs (id TEXT PRIMARY KEY,article_id TEXT,market TEXT,symbol TEXT,basis TEXT,inputs TEXT,result TEXT,created_at TEXT)')


def run(article_id,market,symbol,**kwargs):
    inputs=load_inputs(article_id,market,symbol,**kwargs);encoded=h.encode(inputs)
    identifier=sha256((VERSION+encoded).encode()).hexdigest();result={**calculate(inputs),'run_id':identifier}
    with h.db() as db:
        schema(db);db.execute('INSERT OR IGNORE INTO reaction_runs VALUES(?,?,?,?,?,?,?,?)',
            (identifier,article_id,market,symbol,inputs['basis'],encoded,h.encode(result),h.now()))
    return result


def snapshot(article_id=None,run_id=None,include_inputs=False):
    if include_inputs and not run_id:raise ValueError('전체 입력 조회에는 실행 식별자 필요')
    if not h.PATH.exists():return {'version':VERSION,'runs':[]}
    if run_id and not re.fullmatch('[a-f0-9]{64}',run_id):raise ValueError('관측 실행 식별자 오류')
    with h.db() as db:
        schema(db)
        columns='result,inputs'
        rows=db.execute(f'SELECT {columns} FROM reaction_runs WHERE (? IS NULL OR article_id=?) AND (? IS NULL OR id=?) ORDER BY created_at DESC LIMIT 20',
                        (article_id,article_id,run_id,run_id)).fetchall()
    runs=[]
    for row in rows:
        result=json.loads(row['result']);inputs=json.loads(row['inputs'])
        checks=[h.revisions_current(inputs['market'],inputs['symbol'],inputs['stock_prices'],inputs['adjusted']),
                h.revisions_current(inputs['market'],inputs['benchmark'],inputs['benchmark_prices'],inputs['adjusted'] if inputs['market']=='US' else False)]
        runs.append({**result,'calendar_policy_current':result.get('calendar_policy')==h.CALENDAR_POLICY,
                     'price_revisions_current':False if False in checks else True if all(c is True for c in checks) else None,
                     **({'inputs':inputs} if include_inputs else {})})
    return {'version':VERSION,'runs':runs}


def replay(identifier):
    with h.db() as db:
        schema(db);row=db.execute('SELECT inputs,result FROM reaction_runs WHERE id=?',(identifier,)).fetchone()
    if not row:raise ValueError('보관 계산 없음')
    return {**calculate(json.loads(row['inputs'])),'run_id':identifier}==json.loads(row['result'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='사건 전후 일봉 반응 보관 · 매매 수익 아님')
    parser.add_argument('--article-id',required=True);parser.add_argument('--market',choices=('KR','US'),required=True)
    parser.add_argument('--symbol',required=True);parser.add_argument('--basis',choices=('public','available'),default='public')
    parser.add_argument('--benchmark');parser.add_argument('--adjusted',action='store_true');parser.add_argument('--as-of')
    args=parser.parse_args()
    try:
        result=run(args.article_id,args.market,args.symbol,benchmark=args.benchmark,basis=args.basis,adjusted=args.adjusted,as_of=args.as_of)
        print(json.dumps({'run_id':result['run_id'],'status':result['status'],'windows':[{k:w[k] for k in ('name','status','raw_return','abnormal_return')} for w in result['windows']], 'replay_matches':replay(result['run_id'])},ensure_ascii=False))
    except ValueError as e:parser.exit(1,str(e)+'\n')
