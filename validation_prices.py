"""Offline price evidence acquisition for the fixed corpus; never a live ranking input."""

import argparse
from datetime import date,datetime,timedelta,timezone
from fractions import Fraction
import json

import event_reactions
from pathlib import Path

import event_corpus
import market_history as h

PROGRESS=Path(__file__).parent/'.data/validation/price_progress.json'


def probes(corpus):
    rows=[]
    for case in corpus['cases']:
        exposure=case['gold']['listed_exposures']
        code=exposure[0]['code'] if exposure else '005930' if case['axis']=='fx' else 'AAPL' if case['axis']=='rates' else 'NVDA.O'
        market='KR' if code.isdigit() else 'US';symbol=code.removesuffix('.O')
        benchmark='KOSPI' if market=='KR' else 'SPY'
        day=date.fromisoformat(case['published_date'])
        rows.append({'case_id':case['id'],'market':market,'symbol':symbol,'benchmark':benchmark,
                     'since':(day-timedelta(days=210)).isoformat(),'until':(day+timedelta(days=10)).isoformat(),
                     'purpose':'observation_probe_not_beneficiary_or_gold_related_stock'})
    return rows


def plan(corpus):
    intervals={}
    for probe in probes(corpus):
        for symbol in (probe['symbol'],probe['benchmark']):
            intervals.setdefault((probe['market'],symbol),[]).append((date.fromisoformat(probe['since']),date.fromisoformat(probe['until'])))
    jobs=[]
    for (market,symbol),ranges in sorted(intervals.items(),key=lambda x:(x[0][0],x[0][1] not in ('KOSPI','SPY'),x[0][1])):
        merged=[]
        for start,end in sorted(ranges):
            if merged and start<=merged[-1][1]+timedelta(days=1):merged[-1]=(merged[-1][0],max(merged[-1][1],end))
            else:merged.append((start,end))
        for start,end in merged:
            while start<=end:
                stop=min(end,start+timedelta(days=366))
                jobs.append({'market':market,'symbol':symbol,'since':start.isoformat(),'until':stop.isoformat()})
                start=stop+timedelta(days=1)
    return jobs


def collect(max_jobs=1):
    if type(max_jobs) is not int or not 1<=max_jobs<=100:raise ValueError('회차 작업 수 1~100')
    corpus=event_corpus.load();jobs=plan(corpus);client=h.Toss()
    with h.db() as db:
        done={r['key']:json.loads(r['payload']) for r in db.execute('SELECT * FROM jobs')}
    completed=0;attempted=0;error=None
    for spec in jobs:
        key=h.encode([spec['market'],spec['symbol'],spec['since'],spec['until'],False,h.POLICY])
        if done.get(key,{}).get('status')=='complete':completed+=1;continue
        if attempted>=max_jobs:break
        attempted+=1
        for _ in range(40):
            result=h.collect(**spec,pages=3,client=client)
            status=result['status']
            print(json.dumps({'job':spec,'status':status,'prices_complete':result.get('prices_complete'),
                              'calendar_complete':result.get('calendar_complete'),'error':result.get('error')},ensure_ascii=False),flush=True)
            PROGRESS.parent.mkdir(parents=True,exist_ok=True)
            progress={'version':'corpus-prices-v1','corpus_fingerprint':event_corpus.fingerprint(corpus),
                      'planned_jobs':len(jobs),'completed_before_current':completed,'current':spec,'status':status,'updated_at':h.now()}
            temp=PROGRESS.with_suffix('.tmp');temp.write_text(h.encode(progress));temp.replace(PROGRESS)
            if status in ('complete','error'):
                if status=='complete':completed+=1
                else:error=result.get('error')
                break
        if error:break
    return {'planned':len(jobs),'completed':completed,'attempted':attempted,'error':error}


def verify():
    corpus=event_corpus.load();results=[];responses={}
    metadata=json.loads((Path(__file__).parent/'data/evaluation/publication_metadata_v1.json').read_text())
    reported={r['case_id']:r for r in metadata['entries']}
    metadata_fingerprint=event_corpus.fingerprint(metadata)
    with h.db() as db:
        calendars={market:{row['day']:{**json.loads(row['payload']),'response_id':row['response_id']} for row in db.execute('SELECT * FROM calendars WHERE market=?',(market,))} for market in ('KR','US')}
    for case,probe in zip(corpus['cases'],probes(corpus)):
        market=probe['market'];symbol=probe['symbol'];benchmark=probe['benchmark']
        supplement=reported.get(case['id'])
        if supplement and supplement['source_sha256']!=case['source']['sha256']:raise ValueError('공개 시각 보충 자료의 원문 버전 불일치')
        event_time=case['published_at'] or (supplement['published_at'] if supplement else None)
        stock=h.observations(market,symbol,until=probe['until']);bench=h.observations(market,benchmark,until=probe['until'])
        selected=[r for r in stock if probe['since']<=r['day']<=probe['until']]
        source_valid=bool(selected);checked=0
        for observation in selected:
            rid=observation['response_id']
            if rid not in responses:
                response=h.source_response(rid)
                responses[rid]={r['timestamp']:r for r in json.loads(response['payload'])['result']['candles']} if response else {}
            raw=responses[rid].get(observation['timestamp'])
            matches=bool(raw and all(Fraction(raw[key])==Fraction(observation[key]) for key in ('openPrice','highPrice','lowPrice','closePrice','volume')))
            source_valid=source_valid and matches;checked+=matches
        expected={d for d,r in calendars[market].items() if probe['since']<=d<=probe['until'] and r['regular_open']}
        observed={r['day'] for r in selected}
        total_days=(date.fromisoformat(probe['until'])-date.fromisoformat(probe['since'])).days+1
        known=sum(probe['since']<=d<=probe['until'] for d in calendars[market])
        entry={'case_id':case['id'],'market':market,'symbol':symbol,'source_verified_days':checked,
               'source_values_match':source_valid,'calendar_unknown_days':total_days-known,
               'missing_open_days':sorted(expected-observed),'coverage_complete':known==total_days and expected<=observed,'price_references':[{'day':r['day'],'revision':r['revision'],'response_id':r['response_id']} for r in selected],
               'status':'exact_publication_time_unknown' if not event_time else 'price_missing',
               'time_quality':'explicit_official_release' if case['published_at'] else supplement['time_quality'] if supplement else 'date_only',
               'return_matches':False,'reviewer_kind':'agent','comparison_method':'source_OHLCV_fraction_check_and_independent_endpoint_fraction'}
        if event_time and source_valid:
            inputs={'event':{'article_id':case['id'],'event_id':case['independent_event_id'],'source_key':case['source']['sha256'],
                            'rule_version':corpus['version'],'review_status':'single_agent_source_review','published_at':event_time},
                    'market':market,'symbol':symbol,'benchmark':benchmark,'basis':'public','adjusted':False,'as_of':h.now(),
                    'stock_prices':stock,'benchmark_prices':bench,'calendar':calendars[market]}
            result=event_reactions.calculate(inputs)
            event_window=next((w for w in result['windows'] if w['name']=='event_day'),None)
            entry['calculation']=result;entry['inputs']=inputs
            if event_window and event_window['raw_return'] is not None:
                prices={r['day']:r for r in stock};a=prices[event_window['start']['day']]['closePrice'];b=prices[event_window['end']['day']]['closePrice']
                independent=float(Fraction(b)/Fraction(a)-1)
                entry['return_matches']=abs(independent-event_window['raw_return'])<1e-12
                entry['status']='source_verified_daily_return' if entry['return_matches'] else 'return_mismatch'
            elif event_window:entry['status']=event_window['status']
            else:entry['status']=result['status']
        results.append(entry)
    output={'version':'corpus-price-check-v1','corpus_fingerprint':event_corpus.fingerprint(corpus),'publication_metadata_fingerprint':metadata_fingerprint,'checked_at':h.now(),
            'cases':results,'scope':'오프라인 개발 검수 · 최종 자료는 실시간 검색·추천 표본으로 사용하지 않음',
            'source_verified_cases':sum(r['source_values_match'] for r in results),
            'verified_daily_return_cases':sum(r['return_matches'] for r in results),
            'not_expert_or_second_reviewer':True,'price_vintage':'retrieved_version_not_point_in_time'}
    identifier=event_corpus.fingerprint(output)
    archive=PROGRESS.parent/'price_checks';archive.mkdir(parents=True,exist_ok=True)
    frozen=archive/(identifier+'.json')
    if not frozen.exists():frozen.write_text(h.encode(output))
    summary={k:v for k,v in output.items() if k!='cases'}
    summary.update(run_id=identifier,complete_coverage_cases=sum(r['coverage_complete'] for r in results))
    target=PROGRESS.with_name('price_ground_truth.json');temp=target.with_suffix('.tmp')
    temp.write_text(h.encode(summary));temp.replace(target)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='고정 검수 자료의 개인용 과거 가격 증거 수집 · 정답은 별도 검토')
    actions=parser.add_mutually_exclusive_group();actions.add_argument('--collect',action='store_true');actions.add_argument('--verify',action='store_true');parser.add_argument('--jobs',type=int,default=1);args=parser.parse_args()
    result=verify() if args.verify else collect(args.jobs) if args.collect else {'jobs':plan(event_corpus.load()),'mode':'plan_only_no_network'}
    print(json.dumps(result,ensure_ascii=False))
