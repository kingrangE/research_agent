"""Reviewed business membership, separate from news mentions and price observations."""

from datetime import date, datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlsplit

KNOWLEDGE=json.loads((Path(__file__).parent/'data/business_ontology.json').read_text())


def validate(data):
    themes={t['id'] for t in data['themes']}
    entities={e['id'] for e in data['entities']}
    securities={s['code']:s for s in data['securities']}
    if len(entities)!=len(data['entities']) or len(securities)!=len(data['securities']):
        raise ValueError('기업·증권 식별자 중복')
    for s in securities.values():
        if s['issuer_id'] not in entities or s['country'] not in ('KR','US'):
            raise ValueError('증권 발행사·시장 오류')
    ids=set()
    for m in data['memberships']:
        if (m['id'] in ids or m['theme'] not in themes or m['code'] not in securities or m['subject_id'] not in entities
                or m['kind'] not in ('business','market_association') or m['status']!='reviewed' or not m['sources']):
            raise ValueError('검토된 사업 소속 형식 오류')
        ids.add(m['id'])
        for field in ('valid_from','valid_to','reviewed_on'):
            if m.get(field): date.fromisoformat(m[field])
        if m['valid_from'] and m['valid_to'] and m['valid_from']>m['valid_to']:
            raise ValueError('관계 유효 기간 역전')
        for sid in m['sources']:
            source=data['sources'][sid]
            parsed=urlsplit(source['url'])
            if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or not source['excerpt']:
                raise ValueError('출처·근거 부족')
            for field in ('published_on','checked_on'):
                if source.get(field): date.fromisoformat(source[field])
    return data


validate(KNOWLEDGE)


def snapshot(as_of=None,theme=None,code=None):
    day=date.fromisoformat(as_of) if as_of else datetime.now(timezone.utc).date()
    themes={t['id']:t for t in KNOWLEDGE['themes']}
    securities={s['code']:s for s in KNOWLEDGE['securities']}
    entities={e['id']:e for e in KNOWLEDGE['entities']}
    if (theme and theme not in themes) or (code and code not in securities):
        raise ValueError('등록되지 않은 테마·증권')
    members=[]
    for m in KNOWLEDGE['memberships']:
        if (theme and m['theme']!=theme) or (code and m['code']!=code):continue
        if (m['valid_from'] and day.isoformat()<m['valid_from']) or (m['valid_to'] and day.isoformat()>m['valid_to']):continue
        sources=[dict(id=sid,**KNOWLEDGE['sources'][sid]) for sid in m['sources']]
        # Undated web pages establish knowledge only from their actual review date.
        if any((s.get('published_on') or s['checked_on'])>day.isoformat() for s in sources):continue
        members.append({**m,'security':securities[m['code']],'subject':entities[m['subject_id']],
            'evidence':sources,'temporal_precision':'day','validity_note':'종료 시점 미확인' if not m['valid_to'] else None,
            'claim_status':'공개 사업 근거 검토 · 기사 수혜 미판정'})
    counts=[]
    for t in themes.values():
        rows=[m for m in members if m['theme']==t['id'] and m['kind']=='business']
        counts.append({**t,'memberships':len(rows),'issuers':len({r['security']['issuer_id'] for r in rows}),
            'countries':{c:len({r['security']['issuer_id'] for r in rows if r['security']['country']==c}) for c in ('KR','US')}})
    return {'version':KNOWLEDGE['version'],'as_of':day.isoformat(),'themes':counts,'memberships':members,
            'unique_issuers':len({m['security']['issuer_id'] for m in members}),
            'unique_securities':len({m['code'] for m in members}),
            'scope':'검토된 사업 소속 · 전체 시장을 포괄하지 않음 · 날짜 단위 공개 근거'}
