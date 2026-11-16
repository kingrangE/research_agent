"""Frozen source-fragment diagnostics, deliberately separate from live retrieval."""

from collections import Counter
from hashlib import sha256
import argparse
import json
import math
from pathlib import Path
from unittest.mock import patch

import business_ontology as business
import event_corpus
import event_facts
import evaluate_domain_challenges
import stocks

VERSION='data-product-evaluation-v1'


def interval(success,total):
    if not total:return None
    z=1.959963984540054;p=success/total;denominator=1+z*z/total
    center=(p+z*z/(2*total))/denominator
    radius=z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/denominator
    return [max(0,center-radius),min(1,center+radius)]


def metric(rows,field):
    tp=fp=fn=abstained=0
    for row in rows:
        gold=set(row['gold'][field]);pred=set(row['predicted'][field])
        tp+=len(gold&pred);fp+=len(pred-gold);fn+=len(gold-pred);abstained+=not pred
    return {'cases':len(rows),'true_positive':tp,'false_positive':fp,'false_negative':fn,'abstained_cases':abstained,
            'precision':tp/(tp+fp) if tp+fp else None,'recall':tp/(tp+fn) if tp+fn else None,
            'precision_wilson_95':interval(tp,tp+fp),'recall_wilson_95':interval(tp,tp+fn)}


def evaluate(data,split='final'):
    if split not in ('development','validation','final'):raise ValueError('평가 분할 오류')
    cases=[c for c in data['cases'] if c['split']==split];rows=[]
    catalogue={s['code']:{**s,'products':''} for s in business.KNOWLEDGE['securities']}
    matcher,names=stocks.compile_names(catalogue)
    with patch.multiple(stocks,CATALOGUE=catalogue,NAME_MATCHER=matcher,NAME_CODES=names):
        for case in cases:
            source=case['source'];proof=source['proof']
            article={'id':case['id'],'url':source['url'],'title':proof,'published_at':case.get('published_at')}
            proposal=event_facts.extract(article,proof)
            codes={a['code'] for a in proposal['actors'] if a.get('code') in catalogue}
            memberships={m['theme'] for code in codes for m in business.snapshot(case['published_date'],code=code)['memberships']}
            legacy={s['code'] for s in stocks.related_stocks(proof,as_of=case['published_date'])}
            gold=case['gold']
            rows.append({'id':case['id'],'event_id':case['independent_event_id'],'axis':case['axis'],'url':source['url'],
                'markets':sorted({'KR' if e['code'].isdigit() else 'US' for e in gold['listed_exposures']}) or ['no_listed_label'],
                'themes':gold['themes'] or ['no_theme_label'],
                'gold':{'axis':[gold['axis']],'type':[gold['event_type']],'stage':[gold['stage']],
                        'listed_candidate':[e['code'] for e in gold['listed_exposures']],'theme':gold['themes']},
                'predicted':{'axis':[proposal['axis']] if proposal['axis'] else [],
                             'type':[proposal['event_type']] if proposal['axis'] else [],
                             'stage':[proposal['stage']] if proposal['axis'] and proposal['stage']!='unknown' else [],
                             'listed_candidate':sorted(codes),'theme':sorted(memberships)},
                'legacy_listed_candidates':sorted(legacy)})
    fields=('axis','type','stage','listed_candidate','theme')
    metrics={f:metric(rows,f) for f in fields}
    groups={}
    for dimension in ('axis','markets','themes'):
        required={'axis':event_corpus.AXES,'markets':{'KR','US'},'themes':{t['id'] for t in business.KNOWLEDGE['themes']}}[dimension]
        labels=sorted(required | {v for r in rows for v in ([r[dimension]] if dimension=='axis' else r[dimension])})
        groups[dimension]={label:{f:metric([r for r in rows if label in ([r[dimension]] if dimension=='axis' else r[dimension])],f) for f in fields} for label in labels}
    baseline=[{**r,'predicted':{'listed_candidate':r['legacy_listed_candidates']}} for r in rows]
    goals={f:{'status':'unmet' if (m['precision'] is not None and m['precision']<.95) or (m['recall'] is not None and m['recall']<.8) else 'unverified' if m['precision'] is None or m['recall'] is None else 'met_on_limited_labels',
              'precision_target':.95,'recall_target':.8} for f,m in metrics.items()}
    challenges=evaluate_domain_challenges.run()
    modules=['event_facts.py','macro_events.py','trade_events.py','business_ontology.py','stocks.py','relations.py','data/business_ontology.json','data/relations.json']
    hashes={p:sha256((Path(__file__).parent/p).read_bytes()).hexdigest() for p in modules}
    return {'version':VERSION,'split':split,'cases':len(rows),'corpus_fingerprint':event_corpus.fingerprint(data),
        'split_fingerprint':event_corpus.fingerprint(cases),'implementation_hashes':hashes,'metrics':metrics,'groups':groups,
        'legacy_listed_candidate_diagnostic':metric(baseline,'listed_candidate'),'goals':goals,'domain_challenges':challenges,
        'llm_calls':0,'embedding_calls':0,'release_approved':False,'rows':rows,
        'release_checks':{'precision_recall':'unmet' if any(g['status']=='unmet' for g in goals.values()) else 'unverified',
                          'finite_domain_challenges':'met' if challenges['failed']==0 else 'unmet',
                          'expert_company_or_related_stock_utility':'unverified','latency':'separate_benchmark_report',
                          'human_median_time_reduction_30_percent':'unverified'},
        'unverified':['실제 한국어 포털 전문·독립 전문가 정답·문서 전체 기업 식별','관련주 유용성·공급망 연결의 독립 정답','조회 지연·전체 수집 반영 지연·사람의 탐색 시간은 별도 측정'],
        'limitations':['공식 영문 주요 구절 입력 진단이며 전체 본문 성능이 아님','단독 에이전트 라벨이며 구축 과정에서 정답을 열람했으므로 완전한 맹검이 아님',
                      '최종 정답은 live 규칙·관계·검색 입력에 사용하지 않음 · 평가 후 규칙을 고치면 새 독립 평가가 필요',
                      '상장 노출 후보 라벨은 모든 관련주·법적 당사자·수혜 정답이 아님','Wilson 구간은 라벨별 근사이며 사건 계열 의존·검수 오류를 해결하지 않음',
                      '보류는 분모에서 제거하지 않음 · 음성 사례가 적어 정밀도 해석이 제한됨']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='고정 시간 분할 자료의 AI 없는 제한 범위 진단')
    parser.add_argument('--split',choices=('development','validation','final'),default='final');parser.add_argument('--sources',required=True)
    args=parser.parse_args();data=event_corpus.load();result=evaluate(data,args.split)
    result['source_checks']=dict(Counter(c['status'] for c in event_corpus.source_check(data,args.sources)))
    print(json.dumps(result,ensure_ascii=False,indent=2))
