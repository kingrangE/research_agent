"""Instrument-aware monetary observations; levels and changes have distinct units."""

from decimal import Decimal
from datetime import date,datetime
import json
from pathlib import Path
import re
from urllib.parse import urlsplit,parse_qs

REFERENCES=json.loads((Path(__file__).parent/'data/rate_decisions.json').read_text())
N=r'(?:[0-9]+-[0-9]+/[0-9]+|[0-9]+/[0-9]+|[0-9]+(?:\.[0-9]+)?)'


def number(raw):
    if raw.startswith('-'):return -number(raw[1:])
    if '-' in raw:
        whole,fraction=raw.split('-',1);return Decimal(whole)+number(fraction)
    if '/' in raw:
        a,b=raw.split('/');return Decimal(a)/Decimal(b)
    return Decimal(raw)


def decimal_text(value):return format(value.normalize(),'f')


def reference_match(reference,text):
    return re.search(r'\s+'.join(re.escape(word) for word in reference['quote'].split()),text)


for _reference in REFERENCES['decisions']:
    if urlsplit(_reference['url']).hostname not in ('www.federalreserve.gov','www.bok.or.kr'):
        raise ValueError('등록된 공식 금리 출처가 아님')
    date.fromisoformat(_reference['decision_date'])
    if len(_reference['previous_level'])!=len(_reference['new_level']) or any(
        (number(new)-number(old))*100!=number(_reference['delta_bp'])
        for old,new in zip(_reference['previous_level'],_reference['new_level'])):
        raise ValueError('공식 금리 참조의 수준·변화량 불일치')


def official(url,text):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.username or parsed.password or parsed.port not in (None,443):return None
    for r in REFERENCES['decisions']:
        source=urlsplit(r['url'])
        same=(parsed.hostname==source.hostname and parsed.path==source.path and
              (parse_qs(parsed.query).get('nttId')==parse_qs(source.query).get('nttId')))
        if same and reference_match(r,text):return r
    return None


def rates(text):
    policy=bool(re.search(r'기준금리|정책금리|연준|FOMC|한국은행|한은|federal funds|Federal Reserve',text,re.I))
    market=bool(re.search(r'(?:국채|국고채|Treasury).{0,25}(?:금리|수익률|yield)|(?:금리|yield).{0,20}(?:국채|Treasury)',text,re.I))
    if not (policy or market):return None
    if re.search(r'개인투자용|만기\s*수익률|청약|재산승계|신탁',text) and not policy:return None
    if not re.search(r'금리|rate|yield|federal funds',text,re.I):return None
    us=bool(re.search(r'연준|FOMC|미국|미\s*국채|Treasury|Federal Reserve|federal funds',text,re.I))
    kr=bool(re.search(r'한국은행|한은|국고채|한국',text))
    country='US' if us and not kr else 'KR' if kr and not us else None
    instrument='sovereign_yield' if market and not re.search(r'기준금리|정책금리|federal funds',text,re.I) else 'federal_funds_target' if country=='US' else 'kr_base_rate' if country=='KR' else 'policy_rate_unidentified'
    direction='hold' if re.search(r'동결|유지|unchanged|maintain',text,re.I) else 'cut' if re.search(r'인하|하향|하락|낮|lower|decreas|fell|fall',text,re.I) else 'raise' if re.search(r'인상|상향|상승|올|rais|increas|rose',text,re.I) else None
    negated=bool(re.search(r'(?:인하|인상|동결|결정).{0,8}(?:않|없|부인)|사실무근|not.{0,15}(?:cut|raise)',text,re.I))
    forecast=bool(re.search(r'전망|예상|가능성|기대|관측|could|expected|likely',text,re.I))
    stage='planned' if forecast else 'denied' if negated else 'announced' if direction else 'unknown'
    changes=[]
    for m in re.finditer(r'('+N+r')\s*(bp|bps|베이시스포인트|%\s*p|%\s*포인트|퍼센트포인트|percentage points?)',text,re.I):
        value=number(m.group(1))*(1 if m.group(2).lower() in ('bp','bps','베이시스포인트') else 100)
        if direction=='cut':value=-value
        changes.append({'raw':m.group(),'basis_points':decimal_text(value) if direction and not negated else None})
    previous=[];new=[]
    old_new=re.search(r'('+N+r')\s*%\s*(?:에서|→|->)\s*('+N+r')\s*%(?!\s*(?:p|포인트))',text,re.I)
    if old_new:
        previous=[decimal_text(number(old_new.group(1)))];new=[decimal_text(number(old_new.group(2)))]
    else:
        ranged=re.search(r'('+N+r')\s*(?:~|∼|–|to|-)\s*('+N+r')\s*(?:%(?!\s*(?:p|포인트))|percent\b)',text,re.I)
        if ranged:new=[decimal_text(number(ranged.group(1))),decimal_text(number(ranged.group(2)))]
        else:
            levels=re.findall(r'(?<![0-9.])('+N+r')\s*%(?!\s*(?:p|포인트))',text,re.I)
            if len(levels)==1:new=[decimal_text(number(levels[0]))]
    tenors={int(next(g for g in m.groups() if g)) for m in re.finditer(r'(\d{1,2})\s*년물|(\d{1,2})[- ]year',text,re.I)}
    conflict=False
    if len(previous)==len(new)==1 and not negated:
        derived=(Decimal(new[0])-Decimal(previous[0]))*100
        if changes and any(c['basis_points'] is not None and Decimal(c['basis_points'])!=derived for c in changes):conflict=True
        elif not changes:changes=[{'raw':old_new.group(),'basis_points':decimal_text(derived),'basis':'derived_from_levels'}]
        if direction is None:direction='cut' if derived<0 else 'raise' if derived>0 else 'hold'
    if conflict:stage='unknown'
    observed_direction={'cut':'down','raise':'up'}.get(direction,direction) if instrument=='sovereign_yield' else direction
    dates=re.findall(r'(20[0-9]{2})\s*(?:년|-)\s*([0-9]{1,2})\s*(?:월|-)\s*([0-9]{1,2})(?:일)?',text)
    decision_date=None
    if len(dates)==1:
        try:decision_date=date(*map(int,dates[0])).isoformat()
        except ValueError:pass
    return {'axis':'rates','event_type':'market_rate_report' if instrument=='sovereign_yield' else 'policy_rate_forecast' if forecast else 'policy_rate_report',
            'stage':stage,'product':instrument,'details':{'country':country,'currency':'USD' if country=='US' else 'KRW' if country=='KR' else None,
            'authority':'Federal Reserve' if policy and country=='US' else '한국은행' if policy and country=='KR' else None,
            'instrument':instrument,'tenor_years':next(iter(tenors)) if len(tenors)==1 else None,
            'mixed_country_context':us and kr,'multiple_tenors':len(tenors)>1,
            'previous_level':previous,'new_level':new,'level_unit':'percent','changes':changes,
            'direction':None if negated or conflict else observed_direction,'denied_direction':direction if negated else None,
            'numeric_conflict':conflict,'forecast_negated':forecast and negated,
            'verification':'official_unverified','decision_date':decision_date,'published_at':None,'effective_at':None,
            'observation_window':'previous_close' if re.search(r'전일\s*대비|전장\s*대비',text) else 'intraday' if '장중' in text else None,
            'expected_change_bp':None,'surprise_bp':None}}


def from_official(reference):
    return {'axis':'rates','event_type':'policy_rate_decision','stage':'announced','product':reference['instrument'],
        'details':{**reference,'reference_id':reference['id'],'verification':'official_registry',
                   'level_unit':'percent','changes':[{'raw':reference['delta_bp']+' bp','basis_points':reference['delta_bp']}]}}


def compare_reference(details,article_time=None,forecast=False):
    if forecast or details.get('numeric_conflict') or details.get('denied_direction'):return details
    for r in REFERENCES['decisions']:
        if not (r['country']==details['country'] and r['instrument']==details['instrument'] and r['decision_date']==details['decision_date']):continue
        if [number(v) for v in r['new_level']]!=[number(v) for v in details['new_level']]:continue
        if details['changes'] and any(v['basis_points']!=r['delta_bp'] for v in details['changes']):continue
        if r['published_at'] and article_time:
            if datetime.fromisoformat(r['published_at'])>datetime.fromisoformat(article_time):continue
        return {**details,'reference_id':r['id'],'reference_url':r['url'],
                'verification':'matched_official_values' if r['published_at'] and article_time else 'matched_values_publication_time_unverified',
                'official_published_at':r['published_at'],'effective_at':r['effective_at']}
    return details
