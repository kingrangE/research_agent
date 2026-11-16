"""Versioned personal-use Toss reference FX; never interprets spreads as returns."""

import argparse
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path
import re

import market_history as h

POLICY='toss-fx-mid-v1'
EXPOSURES=json.loads((Path(__file__).parent/'data/currency_exposures.json').read_text())


def pair(base,quote):
    if {base,quote}!={'USD','KRW'}:raise ValueError('현재 USD/KRW와 역호가만 지원')


def normalize(response,base,quote,at=None):
    pair(base,quote)
    r=response.get('result')
    if not isinstance(r,dict) or (r.get('baseCurrency'),r.get('quoteCurrency'))!=(base,quote):raise ValueError('통화쌍 불일치')
    for field in ('rate','midRate'):
        if not isinstance(r.get(field),str) or not re.fullmatch(r'[0-9]{1,12}(?:\.[0-9]{1,15})?',r[field]) or Decimal(r[field])<=0:
            raise ValueError('환율 값 오류')
    start,end=h.timestamp(r['validFrom']),h.timestamp(r['validUntil'])
    if end<=start:raise ValueError('환율 유효 구간 오류')
    if at and not start<=h.timestamp(at)<end:raise ValueError('요청 시각을 포함하지 않는 환율')
    return {'base_currency':base,'quote_currency':quote,'unit':f'{quote} per 1 {base}',
        'mid_rate':r['midRate'],'buy_rate':r['rate'],'provider_spread_bp':r.get('basisPoint'),
        'valid_from':r['validFrom'],'valid_until':r['validUntil'],'source':'toss','quote_type':'interbank_mid',
        'canonical_usd_krw':format(Decimal(r['midRate']) if base=='USD' else 1/Decimal(r['midRate']),'f'),
        'policy_version':POLICY,'usage':'personal_only_no_redistribution'}


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS fx_values (
        id INTEGER PRIMARY KEY,base TEXT,quote TEXT,start TEXT,end TEXT,payload TEXT,response_id INTEGER,observed_at TEXT,last_seen TEXT)''')


def collect(base='USD',quote='KRW',at=None,client=None):
    pair(base,quote)
    if at:h.timestamp(at)
    params={'baseCurrency':base,'quoteCurrency':quote,**({'dateTime':at} if at else {})}
    response=(client or h.Toss()).request('/api/v1/exchange-rate',params)
    value=normalize(response,base,quote,at)
    payload=h.encode(value)
    with h.db() as db:
        schema(db)
        rid=h.save_response(db,'FX',base+'/'+quote,'fx',params,response)
        previous=db.execute('SELECT id,payload FROM fx_values WHERE base=? AND quote=? AND start=? AND end=? ORDER BY id DESC LIMIT 1',
            (base,quote,value['valid_from'],value['valid_until'])).fetchone()
        if previous and previous['payload']==payload:
            db.execute('UPDATE fx_values SET last_seen=? WHERE id=?',(h.now(),previous['id']))
        else:db.execute('INSERT INTO fx_values(base,quote,start,end,payload,response_id,observed_at,last_seen) VALUES(?,?,?,?,?,?,?,?)',
            (base,quote,value['valid_from'],value['valid_until'],payload,rid,h.now(),h.now()))
    return snapshot(base,quote)


def compare(previous,current):
    if any(previous[k]!=current[k] for k in ('base_currency','quote_currency','source','quote_type')):raise ValueError('서로 다른 환율 기준')
    if h.timestamp(previous['valid_until'])>h.timestamp(current['valid_from']):raise ValueError('겹치거나 역전된 관측 구간')
    old,new=Decimal(previous['mid_rate']),Decimal(current['mid_rate'])
    canonical=Decimal(current['canonical_usd_krw'])-Decimal(previous['canonical_usd_krw'])
    return {'previous_value':str(old),'new_value':str(new),'delta':str(new-old),'change_percent':str((new-old)/old*100),
        'previous_observed_at':previous['valid_from'],'observed_at':current['valid_from'],
        'won_strength':'weak' if canonical>0 else 'strong' if canonical<0 else 'unchanged',
        'basis':'same_provider_mid_two_explicit_windows','day_change':False}


def exposures(code=None,as_of=None):
    day=date.fromisoformat(as_of) if as_of else date.today()
    return [r for r in EXPOSURES['claims'] if (not code or code==r['code']) and date.fromisoformat(r['known_from'])<=day]


def snapshot(base='USD',quote='KRW',code=None,as_of=None):
    pair(base,quote)
    values=[]
    if h.PATH.exists():
        with h.db() as db:
            schema(db)
            rows=db.execute('SELECT * FROM fx_values WHERE base=? AND quote=? ORDER BY id DESC LIMIT 1000',(base,quote)).fetchall()
        seen=set()
        for r in rows:
            value=json.loads(r['payload']);key=(h.timestamp(value['valid_from']),h.timestamp(value['valid_until']))
            if key in seen:continue
            seen.add(key)
            values.append({**value,'revision':r['id'],'response_id':r['response_id'],'retrieved_at':r['observed_at'],'last_seen':r['last_seen']})
    values.sort(key=lambda r:h.timestamp(r['valid_from']),reverse=True)
    current=values[0] if values else None
    previous=next((v for v in values[1:] if h.timestamp(v['valid_until'])<=h.timestamp(current['valid_from'])),None) if current else None
    return {'policy_version':POLICY,'current':current,'previous':previous,'comparison':compare(previous,current) if previous else None,
        'observations':values[:20],'exposures':exposures(code,as_of),'corporate_impact':None,
        'comparison_to_news':'unmatched_time_or_quote_type','usage':'personal_only_no_redistribution',
        'notes':['매수환율·중간환율 분리. 공급자 bp는 스프레드이며 등락이 아님.',
                 '두 관측 구간 사이 변화이며 전일 대비가 아님. 기사와 시각·호가 기준이 다르면 수치 대조 보류.',
                 '기업 근거 미등록은 노출이 없다는 뜻이 아님. 헤지 이후 순노출·수혜 방향 미확정.'],
        'reference_url':'https://www.bok.or.kr/portal/bbs/B0000217/view.do?menuNo=200144&nttId=10087668'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='개인용 토스 기준환율 보관 · 외부 재배포 금지')
    parser.add_argument('--base',default='USD');parser.add_argument('--quote',default='KRW');parser.add_argument('--at')
    args=parser.parse_args()
    try:
        result=collect(args.base,args.quote,args.at)
        print(json.dumps({'saved':result['current'] is not None,'comparison_available':result['comparison'] is not None},ensure_ascii=False))
    except (ValueError,KeyError) as error:parser.exit(1,str(error)+'\n')
