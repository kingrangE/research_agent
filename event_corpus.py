"""Offline corpus audit; labels are never imported by live extraction or retrieval."""

import argparse
from collections import Counter
from datetime import date,datetime
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

PATH=Path(__file__).parent/'data/evaluation/event_corpus_v1.json'
LOCK=PATH.with_suffix('.lock.json')
AXES={'rates','fx','tariff','infrastructure'}
SPLITS={'development','validation','final','excluded'}


def fingerprint(data):return sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def validate(data):
    ids=set();events=set();families={};urls=set()
    for c in data['cases']:
        day=date.fromisoformat(c['published_date'])
        if c['id'] in ids or c['independent_event_id'] in events or c['source']['url'] in urls:raise ValueError('사례·독립 사건·원문 중복')
        ids.add(c['id']);events.add(c['independent_event_id']);urls.add(c['source']['url'])
        if c['axis'] not in AXES or c['split'] not in SPLITS or c['gold']['axis']!=c['axis']:raise ValueError('축·분할·정답 불일치')
        source=c['source'];parsed=urlsplit(source['url'])
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:raise ValueError('원문 URL 오류')
        if not re.fullmatch('[a-f0-9]{64}',source['sha256']) or sha256(source['proof'].encode()).hexdigest()!=source['proof_sha256']:raise ValueError('원문·근거 지문 오류')
        if Path(source['cached_file']).name!=source['cached_file']:raise ValueError('보관 경로 오류')
        if c['published_at']:
            stamp=datetime.fromisoformat(c['published_at'])
            if stamp.tzinfo is None or not c.get('publication_time_evidence'):raise ValueError('공개 시각의 시간대·근거 누락')
        if c['review']['reviewer_kind'] not in ('agent','human') or not c['review']['reviewer']:raise ValueError('검토자 누락')
        if c['split']=='excluded':
            if not c.get('exclusion'):raise ValueError('제외 사유 누락')
        else:
            expected='development' if day<date(2024,1,1) else 'validation' if day<date(2025,1,1) else 'final'
            if c['split']!=expected:raise ValueError('시간 분할 위반')
            previous=families.setdefault(c['family_id'],c['split'])
            if previous!=c['split']:raise ValueError('동일 사건 계열의 분할 유출')
    return data


def load():
    data=validate(json.loads(PATH.read_text()))
    lock=json.loads(LOCK.read_text())
    if fingerprint(data)!=lock['sha256']:raise ValueError('고정 자료 지문 변경 · 검토 후 새 버전 필요')
    for split in SPLITS:
        if fingerprint([c for c in data['cases'] if c['split']==split])!=lock['splits'][split]:raise ValueError('분할 지문 불일치')
    return data


def source_check(data,root):
    root=Path(root);results=[]
    for c in data['cases']:
        path=root/c['source']['cached_file']
        status='missing' if not path.exists() else 'matched' if sha256(path.read_bytes()).hexdigest()==c['source']['sha256'] else 'hash_mismatch'
        results.append({'id':c['id'],'status':status})
    return results


def report(data):
    usable=[c for c in data['cases'] if c['split']!='excluded'];axis=Counter(c['axis'] for c in data['cases'])
    return {'version':data['version'],'fingerprint':fingerprint(data),'real_independent_cases':len(data['cases']),
        'usable_time_split_cases':len(usable),'axes':dict(axis),'usable_axes':dict(Counter(c['axis'] for c in usable)),
        'splits':dict(Counter(c['split'] for c in data['cases'])),
        'period':[min(c['published_date'] for c in data['cases']),max(c['published_date'] for c in data['cases'])],
        'themes':dict(Counter(theme for c in data['cases'] for theme in c['gold']['themes'])),
        'listed_market_scope':dict(Counter('KR' if e['code'].isdigit() else 'US' for c in data['cases'] for e in c['gold']['listed_exposures'])),
        'rate_directions':dict(Counter(c['gold']['details']['direction'] for c in data['cases'] if c['axis']=='rates')),
        'exact_publication_times':sum(bool(c['published_at']) for c in data['cases']),
        'collection_failures_or_exclusions':data['collection_attempts'],'annotators':sorted({c['review']['reviewer_kind'] for c in data['cases']}),
        'independent_second_reviews':sum(c['review']['independent_second_review'] for c in data['cases']),
        'price_ground_truth_cases':sum(c['gold']['price_ground_truth'] is not None for c in data['cases']),
        'source_count_goal_met':len(data['cases'])>=100 and all(axis[a]>=10 for a in AXES),
        'ready_for_final_evaluation':False,
        'open_requirements':['실제 가격 반응 정답 대조','실행 가능한 도전 자료와 근거 검수','공급 경로 정답의 독립 검수','한국어 포털 기사·AI/소프트웨어 사례 보강'],
        'limitations':data['limitations']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='실제 사건 검수 자료의 수량·분할·지문·공백 점검')
    parser.add_argument('--sources');args=parser.parse_args()
    result=load();summary=report(result)
    if args.sources:summary['source_checks']=dict(Counter(r['status'] for r in source_check(result,args.sources)))
    print(json.dumps(summary,ensure_ascii=False,indent=2))
