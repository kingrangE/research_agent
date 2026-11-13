"""Run a small disclosed synthetic baseline; does not train models or use real returns."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time


from intelligence import VERSION, READ_VERSION, RANK_VERSION, GATE_VERSION, SCREEN_VERSION, Engine, RANK_SCHEMA, validate_ranking


def evaluate(engine, dataset):
    results = []
    anchor = {'event_id': 'event-contract', 'event_title': '한빛에너지 전력변압기 공급 계약', 'entities': ['한빛에너지'], 'published_at': '2026-11-11', 'summary': dataset['readings'][0]['body']}
    for case in dataset['readings'] + dataset['clusters']:
        started = time.monotonic()
        output = None
        try:
            output = engine.extract_reading(case['body'],{'id':case['id'],'title':case['id']},[anchor])
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
    for sector in ('energy', 'technology'):
        started = time.monotonic()
        try:
            events = [{'event_id':'material','evidence':['한빛에너지 확정 공급 계약 3000억원, 최근 연매출의 30%, 공시 확인']},
                      {'event_id':'ceremony','evidence':['새봄반도체 사내 친목 행사 개최, 계약·매출 변화 정보 없음']}]
            market = {'active_sector': sector, 'note':'가상 시장 맥락이며 실제 시세가 아님. 단순 업종 유행만으로 사건의 실질을 대체하지 말 것.'}
            output = engine.call('rank', {'task':'주식 투자 판단용 사건을 먼저 배치하라. 모든 ID를 한 번씩 나열하고 reason, stock_relevance, watch_for를 채워라. 계약의 기업 실적 영향을 설명하고 행사는 배경·상품 안내로 구분하라.', 'events':events, 'market':market}, RANK_SCHEMA)
            rows=validate_ranking(output, {'material','ceremony'})
            results.append({'id':'ranking-'+sector, 'valid':True, 'checks':{'material_before_ceremony':rows[0]['event_id']=='material'}, 'output':output, 'seconds':round(time.monotonic()-started,2)})
        except Exception as error:
            results.append({'id':'ranking-'+sector,'valid':False,'error':type(error).__name__,'seconds':round(time.monotonic()-started,2)})
        print(engine.model, results[-1]['id'], results[-1].get('checks',results[-1].get('error')),flush=True)
    return {'model':engine.model,'provider':engine.provider,'cases':results,'valid':sum(r['valid'] for r in results),
            'all_checks_pass':sum(r['valid'] and all(r.get('checks',{}).values()) for r in results), 'total':len(results), 'usage':engine.usage()}


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
    parser.add_argument('--equity-only',action='store_true',help='주식 판단 재료와 상품 안내의 구분만 검증')
    parser.add_argument('--output',default='.data/model-evaluation.json')
    args=parser.parse_args()
    os.environ['LLM_ENABLED']='1'
    dataset=json.loads(Path(args.dataset).read_text())
    report={'prompt_version':VERSION,'read_policy_version':READ_VERSION,'rank_policy_version':RANK_VERSION,'gate_policy_version':GATE_VERSION,'screen_policy_version':SCREEN_VERSION,'as_of':datetime.now(timezone.utc).isoformat(),'limitations':dataset['note'],'results':[]}
    for model in args.models:
        os.environ['LLM_MODEL']=model
        engine=Engine('.data/evaluation-usage.sqlite3')
        report['results'].append(evaluate_equity(engine,dataset) if args.equity_only else evaluate(engine,dataset))
        target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('Saved',args.output,flush=True)
