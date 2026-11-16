"""Strict, descriptive comparisons of stored observations; no evaluation corpus input."""

from decimal import Decimal
import json
import math
import random
import statistics

import event_facts
import event_reactions
import market_history as h

VERSION='comparable-events-v1'


def scope(fact):
    d=fact.get('details') or {}
    values={k:fact.get(k) for k in ('axis','event_type','stage','product')}
    if values['axis']=='rates':
        keys=['country','currency','instrument','direction','level_unit']
        if d.get('instrument')=='sovereign_yield':keys+=['tenor_years','observation_window']
        else:
            changes=[format(abs(Decimal(str(v['basis_points']))).normalize(),'f') for v in d.get('changes',[]) if v.get('basis_points') is not None]
            values['absolute_change_bp']=h.encode(sorted(changes)) if changes else None
    elif values['axis']=='fx':keys=['base_currency','quote_currency','unit','direction','observation_window','quote_type']
    elif values['axis']=='tariff':
        keys=['issuer_country','origin_country','destination_country','regulatory_stage']
        values['classification_codes']=h.encode(sorted(d.get('classification_codes',[]),key=h.encode)) if d.get('classification_codes') else None
    elif values['axis']=='infrastructure':
        currencies={a['currency'] for a in fact.get('amounts',[]) if a.get('currency')}
        currencies={ {'달러':'USD','원':'KRW'}.get(c,c) for c in currencies }
        values.update(region=fact.get('region'),currency=next(iter(currencies)) if len(currencies)==1 else None)
        keys=[]
    else:keys=[]
    values.update({k:d.get(k) for k in keys})
    if any(d.get(k) for k in ('numeric_conflict','mixed_country_context','multiple_tenors','ambiguous_pair_or_direction','conflicting_conditions')):
        values['conflicting_scope']=None
    return values


def summarize(rows):
    values=[r['value'] for r in rows]
    clusters=[]
    for row in sorted(rows,key=lambda r:h.timestamp(r['start'])):
        end=h.timestamp(row['end'])
        if clusters and h.timestamp(row['start'])<clusters[-1]['end']:
            clusters[-1]['rows'].append(row);clusters[-1]['end']=max(clusters[-1]['end'],end)
        else:clusters.append({'end':end,'rows':[row]})
    result={'events':len(rows),'nonoverlapping_clusters':len(clusters),'positive':sum(v>0 for v in values),
            'negative':sum(v<0 for v in values),'zero':sum(v==0 for v in values),
            'median':statistics.median(values) if values else None,
            'range':[min(values),max(values)] if values else None,'cluster_bootstrap_median_95':None,
            'status':'insufficient_sample' if len(clusters)<30 else 'descriptive_only',
            'sign_definition':'종가 비율의 정확한 0 기준 · 거래비용·유의성 기준 아님'}
    if len(clusters)>=30:
        rng=random.Random(0)
        medians=sorted(statistics.median(r['value'] for c in rng.choices(clusters,k=len(clusters)) for r in c['rows']) for _ in range(500))
        result['cluster_bootstrap_median_95']=[medians[12],medians[487]]
    return result


def compare(query,facts,runs,market,symbol,basis='public',window='event_day',as_of=None):
    h.identity(market,symbol)
    if basis not in ('public','available') or window not in ('event_day','next_session','pre_event'):raise ValueError('비교 관측 기준 오류')
    clock=h.timestamp(as_of or h.now());target=scope(query)
    unknown=[k for k,v in target.items() if v in (None,'unknown','unclassified')]
    query_times=[query.get(k) for k in ('published_at','available_at','processed_at')]
    if any(not t or h.timestamp(t)>clock for t in query_times):unknown.append('query_not_available_at_cutoff')
    excluded=[];included=[];baseline=[];seen=set()
    # Latest stored calculation per article at the requested knowledge cutoff.
    latest={}
    for run in sorted(runs,key=lambda r:h.timestamp(r['as_of']),reverse=True):
        if (run['market'],run['symbol'],run['basis'])==(market,symbol,basis) and h.timestamp(run['as_of'])<=clock and h.timestamp(run.get('stored_at',run['as_of']))<=clock:
            latest.setdefault(run['article_id'],run)
    for fact in facts:
        reasons=[];candidate=scope(fact);run=latest.get(fact['article_id'])
        if fact['event_id']==query['event_id']:reasons.append('same_event_as_query')
        times=[fact.get('published_at'),fact.get('available_at'),fact.get('processed_at')]
        times += [r.get('applied_at') for r in fact.get('review_history',[])]
        if any(not t for t in times[:3]):reasons.append('source_time_unknown')
        elif any(h.timestamp(t)>clock for t in times if t):reasons.append('source_or_review_not_available_at_query')
        mismatches=[k for k,v in target.items() if k!='direction' and (v is None or candidate.get(k)!=v)]
        if mismatches:reasons.append('scope_mismatch:'+','.join(mismatches))
        if unknown:reasons.append('query_scope_unknown:'+','.join(unknown))
        if not run:reasons.append('observation_missing_or_not_available')
        elif run.get('source_key')!=fact['source_key'] or run.get('event_id')!=fact['event_id'] or run.get('event_rule_version')!=fact['rule_version']:
            reasons.append('source_or_event_revision_changed')
        elif run.get('calendar_policy')!=h.CALENDAR_POLICY:reasons.append('calendar_policy_outdated')
        observation=next((w for w in (run or {}).get('windows',[]) if w['name']==window),None)
        if run and (not observation or not observation.get('end') or h.timestamp(observation['end']['close'])>clock):reasons.append('window_missing_or_unfinished')
        elif observation and (observation.get('raw_return') is None or not math.isfinite(observation['raw_return'])):reasons.append('return_missing:'+observation['status'])
        item={'article_id':fact['article_id'],'event_id':fact['event_id'],'title':fact.get('article_title'),
              'url':fact['url'],'review_status':fact.get('review_status'),'scope':candidate,'reasons':reasons}
        if reasons:excluded.append(item);continue
        if fact['event_id'] in seen:
            excluded.append({**item,'reasons':['duplicate_event']});continue
        seen.add(fact['event_id'])
        item.update(value=observation['raw_return'],start=observation['start']['close'],end=observation['end']['close'],
                    run_id=run['run_id'],input_url='/api/reactions?run_id='+run['run_id']+'&inputs=true')
        baseline.append(item)
        if target.get('direction')!=candidate.get('direction'):
            excluded.append({**item,'reasons':['direction_mismatch_separate_baseline']});continue
        included.append(item)
    stats=summarize(included);reference=summarize(baseline)
    p=lambda s:s['positive']/s['events'] if s['events'] else None
    difference=p(stats)-p(reference) if stats['events'] and reference['events'] else None
    return {'version':VERSION,'as_of':clock.isoformat(),'query_article_id':query['article_id'],'scope':target,
            'market':market,'symbol':symbol,'basis':basis,'window':window,'summary':stats,
            'included':included,'excluded':excluded,'query_unknown_fields':unknown,
            'baseline':{'definition':'방향 조건만 완화한 별도 집단 · 같은 종목·시장·사건 종류·상태·관측 구간의 저장 사례',
                        'summary':reference,'positive_frequency_difference':difference,'causal_or_significant_difference':False},
            'claim':'과거 관측 분포 · 미래 상승 확률·매수 추천·인과 효과가 아님',
            'limitations':['가격은 사후 수집 버전이며 당시 가용 가격을 보장하지 않음','검수 전 사건 제안을 포함하며 현재 보관된 사례에 한정',
                          '중첩 관측은 묶지만 기업·정책 계열의 모든 의존성을 제거하지 못함','30개 이상도 신뢰 판정 아님 · 순위 가점 없음']}


def snapshot(article_id,market,symbol,basis='public',window='event_day',as_of=None):
    if not article_id or len(article_id)>100:raise ValueError('비교할 기사 필요')
    target=event_facts.snapshot([article_id])['proposals']
    if not target:raise ValueError('비교할 사건 제안 없음')
    query=target[0];runs=[];truncated=False
    if h.PATH.exists():
        with h.db() as db:
            event_reactions.schema(db)
            rows=db.execute('SELECT result,created_at FROM reaction_runs WHERE market=? AND symbol=? AND basis=? ORDER BY created_at DESC LIMIT 1001',(market,symbol,basis)).fetchall()
            truncated=len(rows)>1000;runs=[{**json.loads(r[0]),'stored_at':r[1]} for r in rows[:1000]]
    ids=list(dict.fromkeys([r['article_id'] for r in runs]+[article_id]));facts=[]
    for offset in range(0,len(ids),500):facts+=event_facts.snapshot(ids[offset:offset+500])['proposals']
    result=compare(query,facts,runs,market,symbol,basis,window,as_of)
    result['stored_run_limit']=1000;result['truncated']=truncated
    return result
