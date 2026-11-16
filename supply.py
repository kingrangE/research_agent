"""Source claims about transactions; never a transitive financial-benefit rule."""

from datetime import date,datetime,timezone
import json
import os
from pathlib import Path

import relations
import business_ontology

KNOWLEDGE=json.loads((Path(__file__).parent/'data/supply_claims.json').read_text())


def validate(data):
    codes={s['code'] for s in business_ontology.KNOWLEDGE['securities']}
    ids={c['id'] for c in data['claims']}
    if len(ids)!=len(data['claims']):raise ValueError('관계 주장 중복')
    for c in data['claims']:
        if c['status'] not in ('announced_contract','planned','mou','investment','ownership','cancelled','denied'):
            raise ValueError('주장 상태 오류')
        if c['kind'] not in ('supply','distribution','technology','investment','ownership'):raise ValueError('거래 종류 오류')
        if not c['sources'] or not c['parties'] or not set(c['security_codes'])<=codes:raise ValueError('관계 근거·증권 오류')
        for sid in c['sources']:
            s=data['sources'][sid]
            if not s.get('excerpt') or not s['url'].startswith('https://'):raise ValueError('관계 출처 부족')
        for field in ('supersedes','disputes'):
            if c[field] and (c[field] not in ids or c[field]==c['id']):raise ValueError('후속 주장 연결 오류')
        for field in ('valid_from','valid_to'):
            if c[field]:date.fromisoformat(c[field])
        if c['valid_from'] and c['valid_to'] and c['valid_from']>c['valid_to']:raise ValueError('관계 유효 기간 역전')
    return data


validate(KNOWLEDGE)


def snapshot(as_of=None,code=None,product=None,generation=None,region=None,stage=None,version=None):
    day=date.fromisoformat(as_of).isoformat() if as_of else datetime.now(timezone.utc).date().isoformat()
    selected=version or os.environ.get('SUPPLY_VERSION','reviewed-v1')
    if selected not in ('reviewed-v1','legacy'):raise ValueError('지원하지 않는 관계 버전')
    if code and code not in {s['code'] for s in business_ontology.KNOWLEDGE['securities']}:
        raise ValueError('등록되지 않은 증권')
    if stage not in (None,'purchase','investment','technology','distribution'):raise ValueError('단계 조건 오류')
    if selected=='legacy':
        return {'version':'legacy','claims':[r for r in relations.KNOWLEDGE['relationships'] if not code or r['code']==code],
                'as_of':day,'mode':'legacy_unvalidated','note':'원본 사전 조회 · 제품·유효 기간 검증 미적용'}
    results=[]
    for c in KNOWLEDGE['claims']:
        if code and code not in c['security_codes']:continue
        evidence=[{'id':sid,**KNOWLEDGE['sources'][sid]} for sid in c['sources']]
        reasons=[];blocked=[]
        if any((s.get('published_on') or s['checked_on'])>day for s in evidence):blocked.append('기준일 이후 공개 근거')
        if c['valid_from'] and c['valid_from']>day:blocked.append('관계 시작 전')
        if c['valid_to'] and c['valid_to']<day:blocked.append('관계 유효 기간 종료')
        if c['status'] in ('cancelled','denied'):blocked.append('취소·부인된 주장')
        for newer in KNOWLEDGE['claims']:
            if c['id'] not in (newer.get('supersedes'),newer.get('disputes')):continue
            if all((KNOWLEDGE['sources'][s].get('published_on') or KNOWLEDGE['sources'][s]['checked_on'])<=day for s in newer['sources']):
                blocked.append('후속 변경·상충 주장 존재')
        for label,requested,actual in [('제품',product,c['product']),('세대',generation,c['generation']),('지역',region,c['region'])]:
            if requested and actual and requested!=actual:blocked.append(label+' 불일치')
            elif requested and not actual:reasons.append(label+' 미확인')
        if stage=='purchase' and (c['kind']!='supply' or c['status']!='announced_contract'):
            reasons.append('구매 확정으로 승격 불가')
        if stage and stage!='purchase' and stage!=c['kind']:blocked.append('거래 종류 불일치')
        if not c['valid_to']:reasons.append('유효 종료 시점 미확인')
        if c['legal_identity']!='verified':reasons.append('정확한 계약 법인 미확인')
        results.append({**c,'evidence':evidence,'event_link_status':'blocked' if blocked else 'conditional',
            'blocked_reasons':blocked,'required_checks':reasons+['이번 사건의 신규 주문·손익 영향 미산정'],
            'financial_impact':None,'beneficiary_confirmed':False,'path_hops':1})
    return {'version':selected,'migration_parent':KNOWLEDGE['migration_parent'],'as_of':day,'claims':results,
            'note':'공개 발표 주장과 이번 사건 영향은 별도 · 공급자의 공급자로 자동 확장하지 않음'}
