"""Explicit exchange-published US cash exceptions; retain conflicting vendor evidence."""

from copy import deepcopy
from datetime import date,datetime
from hashlib import sha256
import json
from pathlib import Path
from zoneinfo import ZoneInfo

KNOWLEDGE=json.loads((Path(__file__).parent/'data/us_cash_calendar.json').read_text())
POLICY='vendor-with-us-cash-exceptions-v1:'+sha256(json.dumps(KNOWLEDGE,sort_keys=True).encode()).hexdigest()[:12]

for _day,_item in KNOWLEDGE['exceptions'].items():
    if date.fromisoformat(_day).weekday()>=5 or _item['state'] not in ('closed','early_close') or not _item['sources']:
        raise ValueError('거래소 예외 날짜·상태 오류')
    for _source in _item['sources']:
        date.fromisoformat(KNOWLEDGE['sources'][_source]['published_on'])


def resolve(market,payload):
    result=deepcopy(payload)
    if market!='US' or payload['date'] not in KNOWLEDGE['exceptions']:return result
    reference=KNOWLEDGE['exceptions'][payload['date']]
    original=payload.get('regularMarket');session=deepcopy(original)
    if reference['state']=='closed':session=None
    elif session:
        session['endTime']=datetime.fromisoformat(payload['date']+'T'+reference['close_time']).replace(tzinfo=ZoneInfo(KNOWLEDGE['timezone'])).isoformat()
    else:result['calendar_unverified']=True
    changed=bool(original)!=bool(session)
    if original and session:changed=datetime.fromisoformat(original['endTime'])!=datetime.fromisoformat(session['endTime'])
    result.update(regularMarket=session,regular_open=bool(session),vendor_regular_session=original,
                  calendar_reference={'version':KNOWLEDGE['version'],'state':reference['state'],
                    'sources':[KNOWLEDGE['sources'][s] for s in reference['sources']],
                    'reviewed_on':KNOWLEDGE['reviewed_on'],'point_in_time_page_version':False},
                  calendar_source_conflict=changed)
    return result
