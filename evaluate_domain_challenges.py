"""Executable domain counterexamples, separate from real-event count and accuracy."""

import json
from pathlib import Path

import event_facts
import event_reactions
import supply
import trade_events

PATH=Path(__file__).parent/'data/evaluation/challenges_v1.json'


def check(case):
    kind=case['type']
    if kind=='entities':return event_facts.entities(case['input'])==case['expected']
    if kind=='event':
        result=event_facts.extract({'id':case['id'],'url':'https://example.invalid/fixture','title':case['input']})
        return all(result.get(k)==v for k,v in case['expected'].items())
    if kind=='supply':
        claims=supply.snapshot(**case['query'])['claims'];target=next((c for c in claims if c['id']==case['claim']),None)
        return bool(target and target['event_link_status']==case['expected_status'] and case['expected_reason'] in target['blocked_reasons'] and not target['beneficiary_confirmed'])
    if kind=='trade_asof':return case['forbidden_id'] not in {c['id'] for c in trade_events.snapshot(case['input'])['measures']}
    if kind=='market_alignment':
        given=case['input'];calendar={d:{'regular_open':False} for d in given['closed_days']}
        calendar.update({d:{'regular_open':True,'integrated':{'regularMarket':{'startTime':d+'T09:00:00+09:00','endTime':d+'T15:30:00+09:00'}}} for d in given['sessions']})
        result=event_reactions.calculate({'event':{'article_id':'fixture','event_id':'fixture','source_key':'fixture','rule_version':'fixture','review_status':'fixture','published_at':given['event_time']},
            'market':'KR','symbol':'005930','benchmark':'KOSPI','basis':'public','adjusted':False,'as_of':given['as_of'],'calendar':calendar,'stock_prices':[],'benchmark_prices':[]})
        window=next(w for w in result['windows'] if w['name']=='event_day')
        return window['end']['day']==case['expected_end_day'] and window['raw_return']==case['expected_raw_return'] and window['status']=='missing_price'
    raise ValueError('지원하지 않는 도전 자료 유형')


def run():
    data=json.loads(PATH.read_text());ids=[c['id'] for c in data['cases']]
    if len(ids)!=len(set(ids)) or data['counts_as_real_corpus_events']:raise ValueError('도전 자료의 식별·수량 경계 오류')
    results=[]
    for c in data['cases']:
        try:passed=check(c);error=None
        except (ValueError,KeyError,StopIteration) as e:passed=False;error=type(e).__name__
        results.append({'id':c['id'],'passed':passed,'synthetic':c['synthetic'],'error':error})
    return {'version':data['version'],'reviewer_kind':data['reviewer_kind'],'cases':results,
            'samples':len(results),'failed':sum(not r['passed'] for r in results),'real_event_accuracy':None,
            'scope':'수작업 반례 확인 · 전문가 정답·실제 사건 전체 정확도·매매 성과가 아님'}


if __name__=='__main__':
    result=run();print(json.dumps(result,ensure_ascii=False,indent=2));raise SystemExit(1 if result['failed'] else 0)
