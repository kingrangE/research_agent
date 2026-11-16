"""Trade-policy claims retain jurisdiction, product scope and legal stage separately."""

from datetime import date,datetime,timedelta,timezone
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

REFERENCES=json.loads((Path(__file__).parent/'data/trade_measures.json').read_text())
COUNTRIES={'미국':'US','중국':'CN','한국':'KR','일본':'JP','대만':'TW','EU':'EU','유럽연합':'EU'}
PRODUCTS={'semiconductor':r'반도체|semiconductor','ai_accelerator':r'AI\s*(?:반도체|가속기)|GPU|advanced computing',
          'ai_model':r'AI\s*모델|model weights','transformer':r'변압기','solar_equipment':r'태양광.{0,8}(?:장비|설비)|solar manufacturing equipment'}


def extract(text):
    if not re.search(r'관세|수출\s*(?:규제|통제|제한|금지)|수입\s*(?:규제|제한|금지)|수출허가|export control|tariff',text,re.I):return None
    stage=('denied' if re.search(r'부인|사실무근|시행.{0,4}않',text) else
           'withdrawn' if re.search(r'철회|폐지|취소|rescission|rescind',text,re.I) else
           'deferred' if re.search(r'유예|연기|집행\s*중단|not to enforce|suspend',text,re.I) else
           'exempt' if re.search(r'면제|예외|제외|exclu|exempt',text,re.I) else
           'proposed' if re.search(r'검토|제안|추진|전망|예상|가능성|propos',text,re.I) else
           'in_force_reported' if re.search(r'시행|발효|적용\s*시작|effective',text,re.I) else
           'finalized_reported' if re.search(r'확정|최종|final',text,re.I) else 'announcement_reported')
    countries=list(dict.fromkeys(COUNTRIES[k] for k in COUNTRIES if re.search(r'(?<![A-Za-z])'+re.escape(k)+r'(?![A-Za-z])',text)))
    def country_role(pattern):
        found={COUNTRIES[m[1]] for m in re.finditer(pattern,text)}
        return next(iter(found)) if len(found)==1 else None
    names='|'.join(COUNTRIES)
    origin=country_role(r'('+names+r')\s*(?:산|원산지|에서\s*생산)')
    destination=country_role(r'('+names+r')\s*(?:향|으로\s*수출|에\s*수출)')
    issuer=country_role(r'('+names+r')\s*(?:정부|상무부|무역대표부|당국|은|이)')
    products=[key for key,pattern in PRODUCTS.items() if re.search(pattern,text,re.I)]
    if 'ai_accelerator' in products and 'semiconductor' in products:products.remove('semiconductor')
    rates=[{'raw':m.group(),'value':m[1],'unit':'percent','basis':'additional' if re.search(r'추가\s*관세|additional',text,re.I) else 'total' if re.search(r'총\s*(?:관세|세율)|total tariff',text,re.I) else 'unknown'}
           for m in re.finditer(r'([0-9]+(?:\.[0-9]+)?)\s*%(?!\s*(?:p|포인트))',text)]
    codes=[{'scheme':m[1].upper(),'code':m[2]} for m in re.finditer(r'\b(HTSUS|HTS|HS|ECCN)\s*[:：]?\s*([0-9][A-Za-z0-9.]{3,15})\b',text,re.I)]
    dates=[]
    for m in re.finditer(r'(20\d{2})\s*(?:년|-)\s*(\d{1,2})\s*(?:월|-)\s*(\d{1,2})(?:일)?',text):
        try:dates.append({'date':date(*map(int,m.groups())).isoformat(),'context':text[max(0,m.start()-12):m.end()+15]})
        except ValueError:pass
    effective=[d['date'] for d in dates if re.search(r'(?:일부터|부터|발효|시행|적용)',d['context'])]
    normalized={'proposed':'planned','withdrawn':'cancelled','deferred':'deferred','exempt':'exempt','denied':'denied',
                'in_force_reported':'execution','finalized_reported':'approved'}.get(stage,'announced')
    return {'axis':'tariff','event_type':'tariff_report' if '관세' in text or re.search('tariff',text,re.I) else 'export_control_report',
        'stage':normalized,'product':products[0] if len(products)==1 else None,'details':{'kind':'trade','regulatory_stage':stage,
        'issuer_country':issuer,'mentioned_countries':countries,'origin_country':origin,'destination_country':destination,
        'products':products,'classification_codes':codes,'rates':rates,'combined_tariff_rate':None,
        'effective_date':effective[0] if len(set(effective))==1 else None,'dates':dates,'exceptions':None,
        'verification':'news_claim_unverified','company_impact':'unconfirmed_scope_and_exposure','company_candidates':[],
        'policy_id':None,'followup_ids':[],'conflicting_conditions':len(products)>1 or len(set(effective))>1}}


def snapshot(as_of=None):
    moment=datetime.fromisoformat(as_of) if as_of else None
    if moment and moment.tzinfo is None:raise ValueError('규제 조회 기준에는 시간대 필요')
    visible=[]
    for r in REFERENCES['measures']:
        # Date-only publication is usable from the next UTC day; never infer intraday release.
        known=datetime.fromisoformat(r['published_date'])+timedelta(days=1)
        if moment and moment.timestamp()<known.replace(tzinfo=timezone.utc).timestamp():continue
        stage=r['regulatory_stage']
        if stage=='finalized' and r['effective_at'] and moment:
            stage='in_force_by_recorded_schedule' if moment>=datetime.fromisoformat(r['effective_at']) else 'finalized_not_yet_effective'
        if r.get('effective_until') and moment and moment>=datetime.fromisoformat(r['effective_until']):stage='expired_by_recorded_schedule'
        visible.append({**r,'status_as_of':stage,'company_candidates':[],'company_impact':'unconfirmed_scope_and_exposure',
                        'verification':'agent_curated_official_source','full_current_law_verified':False})
    for r in visible:
        r['followups']=[x['id'] for x in visible if r['id'] in x.get('updates',[])]
    return {'version':REFERENCES['version'],'as_of':as_of,'measures':visible,
            'scope':'검토한 과거 공식 자료 일부 · 현행 법령 전체가 아님',
            'notes':['공식 보도자료의 집행 중단과 법령의 정식 폐지를 구분합니다.',
                     '소급 효력일과 공개 시점을 분리합니다. 미래 공개 예외는 과거 조회에서 제외합니다.',
                     '전체 세율·기존 관세와의 합산·기업 직접 영향은 미확정입니다.']}


def official(url,text):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.username or parsed.password or parsed.port not in (None,443):return None
    matches=[r for r in REFERENCES['measures'] if r['url']==url and r['quote'] in text]
    # Multi-measure documents need a reviewed per-measure record rather than an arbitrary first match.
    if len(matches)!=1:return None
    r=matches[0]
    return {'axis':'tariff','event_type':r['measure_type'],'stage':{'proposed':'planned','deferred':'deferred','withdrawn':'cancelled','exempt':'exempt'}.get(r['regulatory_stage'],'approved'),
            'product':r['product'],'details':{'kind':'trade',**r,'verification':'agent_curated_official_source','company_candidates':[],'company_impact':'unconfirmed_scope_and_exposure'}}
