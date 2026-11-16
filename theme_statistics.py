"""Same-market daily return co-movement; no sector bonuses or predictive theme score."""

import argparse
from datetime import date,datetime,timedelta,timezone
from hashlib import sha256
from itertools import combinations
import json
import math
import re

import business_ontology as business
import event_reactions as reactions
import market_history as h

VERSION='theme-returns-v1'
MIN_PAIRS={20:16,60:48}
MIN_VOLUME=1000


def correlation(a,b,minimum):
    days=sorted(set(a)&set(b));values=[(a[d],b[d]) for d in days]
    if len(values)<minimum:return {'value':None,'samples':len(values),'status':'insufficient_pairs'}
    xs,ys=zip(*values);mx=math.fsum(xs)/len(xs);my=math.fsum(ys)/len(ys)
    vx=math.fsum((x-mx)**2 for x in xs);vy=math.fsum((y-my)**2 for y in ys)
    if vx<=1e-20 or vy<=1e-20:return {'value':None,'samples':len(values),'status':'zero_variance'}
    value=math.fsum((x-mx)*(y-my) for x,y in values)/math.sqrt(vx*vy)
    return {'value':max(-1,min(1,value)),'samples':len(values),'status':'observed','first':days[0],'last':days[-1]}


def daily_returns(rows,points,calendar,clock,stock=True):
    by_day={r['day']:r for r in rows};values={}
    for a,b in zip(points,points[1:]):
        if not reactions.calendar_complete(calendar,a['day'],b['day']):continue
        value,_=reactions.price_return(by_day,a,b,clock)
        if value is None:continue
        if stock and any(float(by_day[p['day']]['volume'])<MIN_VOLUME for p in (a,b)):continue
        values[b['day']]=value
    return values


def calculate(inputs):
    clock=h.timestamp(inputs['as_of']);members=inputs['business']['memberships']
    output={'version':VERSION,'as_of':inputs['as_of'],'membership_as_of':inputs['business']['as_of'],
        'membership_basis':inputs['membership_basis'],'membership_version':inputs['business']['version'],
        'frequency':'daily_regular_session','minimum_pairs':{str(k):v for k,v in MIN_PAIRS.items()},'minimum_daily_volume_shares':MIN_VOLUME,
        'themes':[],'unique_issuers':len({m['security']['issuer_id'] for m in members if m['kind']=='business'}),
        'notes':['시장별 현지 거래일 수익률을 동기화합니다. 국내·미국 간 동시 상관은 계산하지 않습니다.',
                 '시장 모형은 각 관측 창 이전 최대 120일·최소 60일로 추정합니다. 업종 보정은 하지 않습니다.',
                 '거래량 1,000주 미만인 시작·종료 봉은 제외합니다. 실제 거래대금이 없어 완전한 유동성 검증은 아닙니다.',
                 '일 단위 관측이며 장중 확산·선행 예측·인과·합성 테마 점수가 아닙니다.']}
    if inputs.get('calendar_policy'):output['calendar_policy']=inputs['calendar_policy']
    for theme in inputs['business']['themes']:
        for market in ('KR','US'):
            selected={};duplicates=[]
            for m in sorted(members,key=lambda m:m['code']):
                if m['theme']!=theme['id'] or m['kind']!='business' or m['security']['country']!=market:continue
                issuer=m['security']['issuer_id']
                if issuer in selected:duplicates.append(m['code'])
                else:selected[issuer]=m
            if not selected:continue
            source=inputs['markets'][market];calendar=source['calendar']
            points=[p for p in reactions.sessions(calendar,market) if h.timestamp(p['close'])<=clock]
            # A date-only membership source is not an intraday availability guarantee.
            last=points[-1]['day'] if points else None
            localday=clock.astimezone(h.ZoneInfo(h.ZONES[market])).date().isoformat()
            if any(v.get('calendar_unverified') and d<=localday and (not last or d>=last) for d,v in calendar.items()):points=[];last=None
            series={m['code']:daily_returns(source['prices'].get(m['code'],[]),points,calendar,clock) for m in selected.values()}
            benchmark=daily_returns(source['benchmark_prices'],points,calendar,clock,False)
            latest={code:values[last] for code,values in series.items() if last in values} if last else {}
            baseline={code:{r['day']:r for r in source['prices'].get(code,[])} for code in series}
            volume_changes=[]
            if last:
                for code in latest:
                    previous=[float(baseline[code][p['day']]['volume']) for p in points[-21:-1] if p['day'] in baseline[code] and float(baseline[code][p['day']]['volume'])>=MIN_VOLUME]
                    if len(previous)>=5:volume_changes.append(float(baseline[code][last]['volume'])/(math.fsum(previous)/len(previous))-1)
            row={'theme':theme['id'],'name':theme['name'],'market':market,'members':len(selected),'codes':list(series),
                 'duplicate_securities_excluded':duplicates,'last_session':last,'observed_members':len(latest),
                 'up_fraction':sum(v>0 for v in latest.values())/len(latest) if latest else None,
                 'down_fraction':sum(v<0 for v in latest.values())/len(latest) if latest else None,
                 'unchanged_fraction':sum(v==0 for v in latest.values())/len(latest) if latest else None,
                 'mean_market_difference':math.fsum(v-benchmark[last] for v in latest.values())/len(latest) if latest and last in benchmark else None,
                 'mean_volume_change':math.fsum(volume_changes)/len(volume_changes) if volume_changes else None,
                 'volume_members':len(volume_changes),'turnover_change':None,
                 'independent_new_events':None,'new_events_status':'independence_review_not_available',
                 'pairs':[],'status':'observed_partial_universe' if latest else 'missing_latest_prices'}
            for window,minimum in MIN_PAIRS.items():
                days={p['day'] for p in points[-window:]};prior_days={p['day'] for p in points[-window-120:-window]}
                trimmed={code:{d:v for d,v in values.items() if d in days} for code,values in series.items()}
                residuals={};models={}
                for code,values in series.items():
                    eligible=sorted(set(values)&set(benchmark)&prior_days)
                    model=reactions.fit_model([(values[d],benchmark[d]) for d in eligible]);models[code]=model
                    residuals[code]={d:v-model['alpha']-model['beta']*benchmark[d] for d,v in trimmed[code].items() if d in benchmark} if model['status']=='estimated' else {}
                for a,b in combinations(series,2):
                    row['pairs'].append({'a':a,'b':b,'window_sessions':window,'minimum':minimum,
                        'raw':correlation(trimmed[a],trimmed[b],minimum),
                        'market_adjusted':correlation(residuals[a],residuals[b],minimum),
                        'models':{a:models[a],b:models[b]},'calendar_window_first':min(days) if days else None,
                        'calendar_window_last':max(days) if days else None})
            output['themes'].append(row)
    return output


def load_inputs(as_of=None,membership_basis='as_of'):
    moment=h.timestamp(as_of or h.now())
    if membership_basis not in ('as_of','current'):raise ValueError('소속 기준 오류')
    known_day=moment.astimezone(timezone.utc).date().isoformat() if membership_basis=='as_of' else datetime.now(timezone.utc).date().isoformat()
    knowledge=business.snapshot(known_day);markets={}
    for market in ('KR','US'):
        benchmark='KOSPI' if market=='KR' else 'SPY'
        with h.db() as db:
            day=moment.astimezone(h.ZoneInfo(h.ZONES[market])).date()
            calendar=h.calendar_snapshot(db,market,(day-timedelta(days=400)).isoformat(),day.isoformat())
        codes={m['security']['provider_symbol']:m['code'] for m in knowledge['memberships'] if m['security']['country']==market}
        markets[market]={'calendar':calendar,'benchmark':benchmark,'benchmark_prices':h.observations(market,benchmark,until=moment.astimezone(h.ZoneInfo(h.ZONES[market])).date().isoformat()),
                         'prices':{code:h.observations(market,symbol,until=moment.astimezone(h.ZoneInfo(h.ZONES[market])).date().isoformat()) for symbol,code in codes.items()}}
    return {'calendar_policy':h.CALENDAR_POLICY,'as_of':moment.isoformat(),'membership_basis':membership_basis,'business':knowledge,'markets':markets}


def schema(db):db.execute('CREATE TABLE IF NOT EXISTS theme_runs (id TEXT PRIMARY KEY,as_of TEXT,inputs TEXT,result TEXT,created_at TEXT)')


def run(as_of=None,membership_basis='as_of'):
    inputs=load_inputs(as_of,membership_basis);encoded=h.encode(inputs)
    identifier=sha256((VERSION+encoded).encode()).hexdigest();result={**calculate(inputs),'run_id':identifier}
    with h.db() as db:
        schema(db);db.execute('INSERT OR IGNORE INTO theme_runs VALUES(?,?,?,?,?)',(identifier,inputs['as_of'],encoded,h.encode(result),h.now()))
    return result


def snapshot(as_of=None,run_id=None,include_inputs=False):
    if as_of:date.fromisoformat(as_of)
    if run_id and not re.fullmatch('[a-f0-9]{64}',run_id):raise ValueError('통계 실행 식별자 오류')
    if not h.PATH.exists():return {'version':VERSION,'runs':[]}
    with h.db() as db:
        schema(db);rows=db.execute("SELECT id,inputs,result FROM theme_runs WHERE (? IS NULL OR json_extract(result,'$.membership_as_of')=?) AND (? IS NULL OR id=?) ORDER BY created_at DESC LIMIT 2",(as_of,as_of,run_id,run_id)).fetchall()
    return {'version':VERSION,'runs':[{**json.loads(r['result']),'calendar_policy_current':json.loads(r['result']).get('calendar_policy')==h.CALENDAR_POLICY,**({'inputs':json.loads(r['inputs'])} if include_inputs else {})} for r in rows]}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='테마별 일 단위 동조·확산 계산 · 실시간 매매 신호 아님')
    parser.add_argument('--as-of');parser.add_argument('--membership-basis',choices=('as_of','current'),default='as_of');args=parser.parse_args()
    try:
        result=run(args.as_of,args.membership_basis)
        print(json.dumps({'run_id':result['run_id'],'theme_markets':len(result['themes']),'observed_members':sum(t['observed_members'] for t in result['themes']),
                          'correlations':sum(p['raw']['value'] is not None for t in result['themes'] for p in t['pairs'])},ensure_ascii=False))
    except ValueError as e:parser.exit(1,str(e)+'\n')
