"""Run a small disclosed synthetic baseline; does not train models or use real returns."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import time


from intelligence import VERSION, READ_VERSION, RANK_VERSION, GATE_VERSION, SCREEN_VERSION, RELEVANCE, Engine, validate_ranking


def evaluate(engine, dataset, clusters_only=False):
    results = []
    anchor = {'event_id': 'event-contract', 'event_title': '한빛에너지 전력변압기 공급 계약', 'entities': ['한빛에너지'], 'published_at': '2026-11-11', 'summary': dataset['readings'][0]['body'] if dataset.get('readings') else ''}
    for case in (dataset['clusters'] if clusters_only else dataset['readings'] + dataset['clusters']):
        started = time.monotonic()
        output = None
        try:
            article={'id':f'article-{len(results)+1}','title':case.get('title','원문 기사')} if clusters_only else {'id':case['id'],'title':case.get('title',case['id'])}
            output = engine.extract_reading(case['body'],article,case.get('anchors',[anchor]))
            if 'expected_match' in case:
                checks = {'same_event': output['match_event_id'] == case['expected_match']}
            else:
                expected = case['expected']
                checks = {'certainty': output['certainty'] == expected['certainty'],
                          'entities': all(any(e in entity for entity in output['entities']) for e in expected['entities'])}
                if expected.get('amount_contains'):
                    checks['amount'] = expected['amount_contains'] in output['amount']
            results.append({'id': case['id'], 'valid': True, 'checks': checks, 'output': output, 'seconds': round(time.monotonic()-started, 2)})
        except Exception as error:
            results.append({'id': case['id'], 'valid': False, 'error': type(error).__name__, 'output': output, 'seconds': round(time.monotonic()-started, 2)})
        print(engine.model, results[-1]['id'], results[-1].get('checks', results[-1].get('error')), flush=True)
    for sector in (() if clusters_only else ('energy', 'technology')):
        started = time.monotonic()
        try:
            events = [{'event_id':'material','evidence':['한빛에너지 확정 공급 계약 3000억원, 최근 연매출의 30%, 공시 확인']},
                      {'event_id':'ceremony','evidence':['새봄반도체 사내 친목 행사 개최, 계약·매출 변화 정보 없음']}]
            market = {'active_sector': sector, 'note':'가상 시장 맥락이며 실제 시세가 아님. 단순 업종 유행만으로 사건의 실질을 대체하지 말 것.'}
            rows=engine.rank(events,market)
            output={'ranking':rows}
            results.append({'id':'ranking-'+sector, 'valid':True, 'checks':{'material_before_ceremony':rows[0]['event_id']=='material'}, 'output':output, 'seconds':round(time.monotonic()-started,2)})
        except Exception as error:
            results.append({'id':'ranking-'+sector,'valid':False,'error':type(error).__name__,'seconds':round(time.monotonic()-started,2)})
        print(engine.model, results[-1]['id'], results[-1].get('checks',results[-1].get('error')),flush=True)
    return {'model':engine.model,'provider':engine.provider,'cases':results,'valid':sum(r['valid'] for r in results),
            'all_checks_pass':sum(r['valid'] and all(r.get('checks',{}).values()) for r in results), 'total':len(results), 'usage':engine.usage()}


def evaluate_ranking(engine,dataset):
    cases=[{'id':c['id'],'body':c['summary'],'expected':c['expected']} for c in dataset['equity_screening']]
    readings={c['id']:c for c in dataset.get('readings',[])}
    cases.extend({'id':c['id'],'body':readings[c['id']]['body'],'expected':c['expected']} for c in dataset.get('ranking_readings',[]))
    if not cases or any(not isinstance(c['id'],str) or not c['id'] for c in cases) or len({c['id'] for c in cases})!=len(cases):
        raise ValueError('순위 평가 자료 없음·중복')
    if any(not isinstance(c['body'],str) or len(c['body'])<8 or c['expected'] not in RELEVANCE for c in cases):
        raise ValueError('순위 평가 본문·기대 분류 오류')
    as_of=datetime.now(timezone.utc).isoformat()
    labels={f'E{i+1}':c for i,c in enumerate(cases)}
    events=[{'event_id':label,'evidence':[c['body']],'published_at':as_of,'first_published_at':as_of} for label,c in labels.items()]
    market={'observations':[],'limitations':'가상 평가용 시장 관측 없음. 실제 시황 재현 아님.'}
    before=engine.usage();started=time.monotonic();rows=[];error=None
    try:
        rows=validate_ranking({'ranking':engine.rank(events,market)},set(labels))
    except Exception as failure:
        error=type(failure).__name__
    actual={r['event_id']:r for r in rows} if not error else {}
    checks=[{'id':c['id'],'event_id':label,'expected':c['expected'],'actual':actual.get(label,{}).get('stock_relevance'),
             'pass':actual.get(label,{}).get('stock_relevance')==c['expected']} for label,c in labels.items()]
    after=engine.usage()
    for row in checks:print(engine.model,row,flush=True)
    return {'model':engine.model,'provider':engine.provider,'valid':error is None,'error':error,
            'checks':checks,'passed':sum(c['pass'] for c in checks),'total':len(checks),'ranking':rows,'inputs':events,'market':market,
            'seconds':round(time.monotonic()-started,2),'call_delta':after.get('calls_today',0)-before.get('calls_today',0),
            'output_tokens_delta':after.get('output_tokens',0)-before.get('output_tokens',0),'usage':after,
            'limitations':'개발자 가상 자료의 최종 순위 경로만 검증. 수집·본문 읽기·적합성은 실행하지 않고 시장 관측도 비워 둠. 전문가 정답·독립 일반화·투자 성과 평가 아님.'}


def evaluate_equity(engine,dataset):
    cases=dataset['equity_screening']
    checks=[]
    for case in cases:
        row={'id':case['id'],'expected':case['expected'],'pass':False}
        try:
            output=engine.screen({'event_title':case['id'],'summary':case['summary'],'entities':[],
                'certainty':'확정','amount':'본문 확인','timing':'당일·수일','evidence':[case['summary']]})
            row.update(actual=output['stock_relevance'],output=output,
                       **{'pass':output['stock_relevance']==case['expected']})
        except Exception as error:
            row['error']=type(error).__name__
        checks.append(row)
        print(engine.model,{k:v for k,v in row.items() if k!='output'},flush=True)
    return {'model':engine.model,'provider':engine.provider,'checks':checks,
            'passed':sum(c['pass'] for c in checks),'total':len(checks),'usage':engine.usage()}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models',nargs='+',default=['ax4-light:latest'])
    parser.add_argument('--dataset',default='tests/fixtures/model_eval.json')
    stage=parser.add_mutually_exclusive_group()
    stage.add_argument('--equity-only',action='store_true',help='주식 판단 재료와 상품 안내의 구분만 검증')
    stage.add_argument('--ranking-only',action='store_true',help='운영과 같은 최종 순위 경로의 분류만 격리 검증')
    stage.add_argument('--clusters-only',action='store_true',help='운영 본문 읽기 경로에서 사건 연결만 격리 검증')
    parser.add_argument('--output',default='.data/model-evaluation.json')
    args=parser.parse_args()
    os.environ['LLM_ENABLED']='1'
    dataset_bytes=Path(args.dataset).read_bytes()
    dataset=json.loads(dataset_bytes)
    report={'prompt_version':VERSION,'read_policy_version':READ_VERSION,'rank_policy_version':RANK_VERSION,'gate_policy_version':GATE_VERSION,'screen_policy_version':SCREEN_VERSION,'dataset_sha256':sha256(dataset_bytes).hexdigest(),'as_of':datetime.now(timezone.utc).isoformat(),'limitations':dataset['note'],'results':[]}
    for model in args.models:
        os.environ['LLM_MODEL']=model
        engine=Engine('.data/evaluation-usage.sqlite3')
        report['results'].append(evaluate_ranking(engine,dataset) if args.ranking_only else evaluate_equity(engine,dataset) if args.equity_only else evaluate(engine,dataset,args.clusters_only))
        target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('Saved',args.output,flush=True)
