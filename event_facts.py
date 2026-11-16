"""Deterministic source-bound event proposals and auditable local review operations."""

import argparse
from contextlib import contextmanager
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3

import archive
import business_ontology
import relations
import macro_events
from analysis_store import epoch

PATH=Path(__file__).resolve().parent/'.data'/'event_facts.sqlite3'
RULE_VERSION='event-rules-v2.1'
STAGES={'unknown','planned','mou','announced','approved','execution','cancelled','denied'}


def encode(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def digest(value):
    return sha256(encode(value).encode()).hexdigest()


def now():return datetime.now(timezone.utc).isoformat()


def entities(text):
    candidates=[]
    securities={s['code']:s for s in business_ontology.KNOWLEDGE['securities']}
    aliases=[(s['issuer_id'],s['code'],a) for s in securities.values() for a in (s['name'],s['provider_symbol'])]
    aliases += [(securities[e['code']]['issuer_id'] if e['code'] in securities else e['id'],e['code'],a)
                for e in relations.KNOWLEDGE['entities'] for a in e['aliases'] if len(a)>=3]
    for entity_id,code,alias in sorted(aliases,key=lambda x:-len(x[2])):
        if alias.isdigit():continue
        if alias in ('Claude','클로드','Alphabet','알파벳','Gemini','제미나이') and not re.search(r'AI|LLM|모델|클라우드',text,re.I):continue
        pattern=re.escape(alias)
        if re.search('[a-zA-Z]',alias):pattern=r'(?<![a-zA-Z])'+pattern+r'(?![a-zA-Z])'
        for match in re.finditer(pattern,text,re.I):
            if any(match.start()<c['end'] and match.end()>c['start'] for c in candidates):continue
            candidates.append({'entity_id':entity_id,'code':code,'name':match.group(),
                               'start':match.start(),'end':match.end(),'role':'mentioned_only'})
    return sorted(candidates,key=lambda c:c['start'])


def infra(text):
    facilities=r'데이터\s*센터|AIDC|data\s*cent(?:er|re)|반도체\s*(?:공장|팹)|\bfab\b|변압기\s*공장|발전소|전력망|송전|배전'
    action=r'투자|증설|건설|착공|구축|가동|발주|수주|계약|MOU|양해각서|취소|철회|부인'
    compute=bool(re.search(r'(?:컴퓨팅|GPU|서버).{0,25}(?:구매|용량|계약|발주)',text,re.I))
    if (not re.search(facilities,text,re.I) and not compute) or not re.search(action,text,re.I):return None
    if re.search(r'지분|투자유치|투자 유치|출자|펀딩',text):kind='equity_investment'
    elif re.search(r'(?:컴퓨팅|GPU|서버).{0,25}(?:구매|계약|발주)',text,re.I):kind='compute_purchase'
    else:kind='facility_investment'
    stage=('denied' if re.search(r'부인|사실무근|체결.{0,5}사실.{0,5}없',text) else
           'cancelled' if re.search(r'취소|철회|무산',text) else
           'mou' if re.search(r'MOU|양해각서',text,re.I) else
           'planned' if re.search(r'검토|예정|계획|추진|전망|논의',text) else
           'approved' if re.search(r'승인|의결',text) else
           'execution' if re.search(r'착공|가동|집행|완공',text) else
           'announced' if re.search(r'체결|발표|수주|발주|건설한다|투자한다',text) else 'unknown')
    return {'axis':'infrastructure','event_type':kind,'stage':stage,
            'product':'data_center' if re.search(r'데이터\s*센터|AIDC|data\s*cent',text,re.I) else 'semiconductor_facility' if re.search(r'반도체|fab',text,re.I) else 'power_infrastructure'}


def extract(article,body=None,body_version=None):
    sections={'title':article['title'],'body':body or ''}
    chosen=None
    title=re.sub(r'\[[^\]]{1,40}\]\s*$','',article['title']).strip()
    headline_fact=infra(title)
    headline_rate=macro_events.rates(title)
    reference=macro_events.official(article['url'],body or '')
    primary=bool(headline_fact or (entities(title) and re.search(r'투자|증설|건설|착공|구축|발주|수주|계약',title)))
    if re.search(r'피소|소송|고소|쇼크|급등|급락|코스피|코스닥|뉴욕증시',title):primary=False
    if re.search(r'투자\s*(?:적기|기회|매력|전략)|투자금.{0,10}(?:썰물|유출|유입)|수혜주|추천주',title):primary=False
    if re.search(r'투자의견|목표주가|목표가(?:[^가-힣]|$)|목표가(?:유지|상향|하향)',title):primary=False
    if not headline_fact and re.search(r'주식|주가|목표가|투자의견|ETF|수익률',title,re.I):primary=False
    classifiers=([macro_events.rates] if headline_rate else [])+([infra] if primary else [])
    if reference:
        match=macro_events.reference_match(reference,body)
        chosen=('body',match,macro_events.from_official(reference))
    for section in (() if chosen else ('body','title')):
        for match in re.finditer(r'.+?(?:\n|[。!?]|(?<![0-9])\.(?![0-9])|$)',sections[section],re.S):
            for classifier in classifiers:
                facts=classifier(match.group())
                if not facts:continue
                if facts['axis']=='rates' and headline_rate:
                    h,c=headline_rate['details'],facts['details']
                    if h['country'] and c['country'] and h['country']!=c['country']:continue
                    if headline_rate['stage'] in ('planned','denied') and headline_rate['stage']!=facts['stage']:continue
                    if h['instrument']=='sovereign_yield' and c['instrument']!='sovereign_yield':continue
                    if not c['country'] and h['country']:
                        facts={**facts,'product':h['instrument'],'details':{**c,'country':h['country'],'currency':h['currency'],
                              'authority':h['authority'],'instrument':h['instrument'],'context_basis':'headline'}}
                chosen=(section,match,facts);break
            if chosen:break
        if chosen:break
    source_key=digest({'id':article['id'],'title':article['title'],'url':article['url'],
                       'body_version':body_version or (digest(body) if body else None),'published_at':article.get('published_at')})
    facts={'axis':None,'event_type':'unclassified','stage':'unknown','product':None}
    evidence=[];amounts=[];actors=[];project_id=None
    if chosen:
        section,match,facts=chosen
        text=match.group()
        if facts['axis']=='rates' and not reference:
            facts={**facts,'details':macro_events.compare_reference(facts['details'],
                article.get('published_at') if article.get('timestamp_basis')!='portal_display' else None,facts['stage']=='planned')}
        evidence=[{'section':section,'start':match.start(),'end':match.end(),'quote':text}]
        if facts['axis']=='infrastructure' and headline_fact and headline_fact['stage']!='unknown' and facts['stage']!='unknown' and headline_fact['stage']!=facts['stage']:
            facts={**facts,'stage':'unknown','stage_conflict':True}
            evidence.append({'section':'title','start':0,'end':len(title),'quote':title})
        actors=entities(text)
        if actors:
            actors=[{**a,'section':section,'start':a['start']+match.start(),'end':a['end']+match.start()} for a in actors]
        else:actors=[{**a,'section':'title'} for a in entities(article['title'])]
        for m in re.finditer(r'(?<![0-9])([0-9][0-9,.]*)\s*(조|억|만)?\s*(달러|원|USD|KRW)(?![a-zA-Z])',text):
            amounts.append({'raw':m.group(),'number':m.group(1),'scale':m.group(2),'currency':m.group(3),
                            'section':section,'start':match.start()+m.start(),'end':match.start()+m.end()})
        identifier=re.search(r'(?:프로젝트|사업|계약)\s*(?:번호|ID)\s*[:：#]\s*([A-Za-z0-9_-]{3,40})',text,re.I)
        project_id=identifier.group(1) if identifier else None
    group={'source':source_key}
    if chosen and len(body or '')>=80 and actors:
        group={'exact_body':digest(re.sub(r'\s+',' ',body).strip()),'actors':sorted({a['entity_id'] for a in actors}),**facts}
    if project_id and actors:
        group={'project':project_id,'actors':sorted({a['entity_id'] for a in actors}),**facts}
    return {'id':digest([source_key,RULE_VERSION]),'source_key':source_key,'event_id':'fact-'+digest(group)[:24],
        'rule_version':RULE_VERSION,'article_id':article['id'],'article_title':article['title'],'url':article['url'],
        'published_at':article.get('published_at') if article.get('timestamp_basis')!='portal_display' else None,
        'portal_display_at':article.get('published_at') if article.get('timestamp_basis')=='portal_display' else None,
        'first_seen_at':article.get('first_seen_at'),
        'source_version_at':article.get('_version_at'),'body_version':body_version,'processed_at':now(),
        'available_at':now(),'evidence':evidence,'actors':actors,'amounts':amounts,'project_id':project_id,
        'region':None,'review_status':'pending_review' if chosen else 'unclassified',
        'unclassified_reason':None if chosen else 'no_primary_supported_event',
        'source_quality':'body_title_binding_unverified' if body else 'title_only',
        'merge_basis':'strong_project_id' if project_id and actors else 'exact_body_and_scope' if 'exact_body' in group else 'independent_source',
        **facts}


@contextmanager
def db():
    PATH.parent.mkdir(parents=True,exist_ok=True)
    connection=sqlite3.connect(PATH,timeout=10);connection.row_factory=sqlite3.Row
    try:
        with connection:
            connection.executescript('''CREATE TABLE IF NOT EXISTS proposals (
                id TEXT PRIMARY KEY,source_key TEXT,article_id TEXT,url TEXT,version TEXT,source_epoch REAL,payload TEXT);
                CREATE INDEX IF NOT EXISTS facts_article ON proposals(version,article_id,source_epoch);
                CREATE INDEX IF NOT EXISTS facts_source ON proposals(source_key);
                CREATE TABLE IF NOT EXISTS cursors (version TEXT,kind TEXT,value INTEGER,PRIMARY KEY(version,kind));
                CREATE TABLE IF NOT EXISTS reviews (id TEXT PRIMARY KEY,payload TEXT,applied_at TEXT);
                CREATE TABLE IF NOT EXISTS overrides (source_key TEXT PRIMARY KEY,event_id TEXT,changes TEXT,review_id TEXT);''')
            yield connection
    finally:connection.close()


def ingest(limit=100):
    if type(limit) is not int or not 1<=limit<=500:raise ValueError('회차 건수는 1~500')
    with db() as connection:
        cursors={r['kind']:r['value'] for r in connection.execute('SELECT kind,value FROM cursors WHERE version=?',(RULE_VERSION,))}
    records,updated=archive.analysis_batch(cursors,limit)
    provenance=archive.provenance(list(dict.fromkeys(r['article']['url'] for r in records)))
    for r in records:r['article']['first_seen_at']=provenance.get(r['article']['url'],{}).get('first_seen_at')
    proposals=[extract(r['article'],r.get('body'),r.get('body_version')) for r in records]
    with db() as connection:
        for p in proposals:
            connection.execute('INSERT OR IGNORE INTO proposals VALUES(?,?,?,?,?,?,?)',
                (p['id'],p['source_key'],p['article_id'],p['url'],RULE_VERSION,epoch(p['source_version_at']),encode(p)))
        for kind,value in updated.items():
            connection.execute('INSERT INTO cursors VALUES(?,?,?) ON CONFLICT(version,kind) DO UPDATE SET value=max(value,excluded.value)',
                               (RULE_VERSION,kind,value))
    return {'processed':len(proposals),'classified':sum(p['axis'] is not None for p in proposals),'cursors':updated,'version':RULE_VERSION}


def apply_review(review):
    if (review.get('action') not in ('merge','split','correct') or not isinstance(review.get('source_keys'),list) or not 1<=len(review['source_keys'])<=100 or
            review.get('reviewer_kind') not in ('human','agent') or not review.get('reviewer') or not review.get('reason')):
        raise ValueError('검토 동작·대상·검토자·사유 필요')
    changes=review.get('changes',{})
    allowed={'axis','event_type','stage','product','region','actors','amounts','details'}
    if not isinstance(changes,dict) or set(changes)-allowed or ('stage' in changes and changes['stage'] not in STAGES):
        raise ValueError('허용하지 않는 사건 정정')
    if 'axis' in changes and changes['axis'] not in (None,'infrastructure','rates','fx','tariff'):raise ValueError('사건 축 정정 오류')
    if 'details' in changes and not isinstance(changes['details'],dict):raise ValueError('상세 정정 형식 오류')
    if any(field in changes and (not isinstance(changes[field],list) or any(not isinstance(x,dict) for x in changes[field])) for field in ('actors','amounts')):
        raise ValueError('당사자·금액 정정 형식 오류')
    if any(field in changes and changes[field] is not None and (not isinstance(changes[field],str) or len(changes[field])>100) for field in ('event_type','product','region')):
        raise ValueError('사건 필드 정정 형식 오류')
    review_id=digest(review)
    with db() as connection:
        if connection.execute('SELECT 1 FROM reviews WHERE id=?',(review_id,)).fetchone():return review_id
        sources=[]
        for key in review['source_keys']:
            row=connection.execute('SELECT payload FROM proposals WHERE source_key=? ORDER BY rowid DESC LIMIT 1',(key,)).fetchone()
            if not row:raise ValueError('검토 원문 버전 미확인')
            source=json.loads(row[0]);sources.append(source)
            proof=review.get('evidence',[])
            if not proof:raise ValueError('검토 근거 구절 필요')
            texts={'title':source['article_title'],'body':archive.analysis_body(source['url'],source['body_version']) if source['body_version'] else ''}
            if not any(isinstance(e,dict) and isinstance(e.get('quote'),str) and len(e['quote'].strip())>=4 and
                       e['quote'] in (texts.get(e.get('section')) or '') for e in proof):
                raise ValueError('검토 인용이 보존 원문과 일치하지 않음')
        event_id=review.get('event_id') or ('review-'+review_id[:24])
        if review['action']=='merge' and len({(changes.get('axis',p['axis']),changes.get('event_type',p['event_type']),changes.get('stage',p['stage'])) for p in sources})>1:
            raise ValueError('사건 축·유형·상태가 다름 · 먼저 근거와 함께 정정 필요')
        if not isinstance(event_id,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{3,100}',event_id):raise ValueError('사건 식별자 오류')
        before=[dict(r) for key in review['source_keys'] for r in connection.execute('SELECT * FROM overrides WHERE source_key=?',(key,))]
        for key in review['source_keys']:
            previous=connection.execute('SELECT changes,event_id FROM overrides WHERE source_key=?',(key,)).fetchone()
            merged={**(json.loads(previous['changes']) if previous else {}),**changes}
            assigned=(previous['event_id'] if previous else next(p['event_id'] for p in sources if p['source_key']==key)) if review['action']=='correct' else event_id
            connection.execute('INSERT OR REPLACE INTO overrides VALUES(?,?,?,?)',(key,assigned,encode(merged),review_id))
        connection.execute('INSERT INTO reviews VALUES(?,?,?)',(review_id,encode({'review':review,'before':before}),now()))
    return review_id


def snapshot(article_ids=None,axis=None,limit=100):
    if axis not in (None,'infrastructure','rates','fx','tariff'):raise ValueError('사건 축 오류')
    if type(limit) is not int or not 1<=limit<=500:raise ValueError('사건 조회 건수 오류')
    if not PATH.exists():return {'version':RULE_VERSION,'events':[],'proposals':[],'reviews':0}
    with db() as connection:
        where='p.version=?';args=[RULE_VERSION]
        if article_ids is not None:
            if not article_ids:return {'version':RULE_VERSION,'events':[],'proposals':[],'reviews':0}
            if len(article_ids)>500:raise ValueError('기사 조회 건수 초과')
            where+=' AND p.article_id IN ('+','.join('?' for _ in article_ids)+')';args.extend(article_ids)
        if axis:
            where+=" AND CASE WHEN json_type(o.changes,'$.axis') IS NOT NULL THEN json_extract(o.changes,'$.axis') ELSE json_extract(p.payload,'$.axis') END=?"
            args.append(axis)
        rows=connection.execute(f'''SELECT p.* FROM proposals p LEFT JOIN overrides o ON o.source_key=p.source_key WHERE {where}
            AND p.rowid=(SELECT rowid FROM proposals WHERE version=p.version AND article_id=p.article_id ORDER BY source_epoch DESC,rowid DESC LIMIT 1)
            ORDER BY p.source_epoch DESC,p.rowid DESC LIMIT ?''',(*args,limit)).fetchall()
        proposals=[]
        for row in rows:
            p=json.loads(row['payload'])
            override=connection.execute('SELECT * FROM overrides WHERE source_key=?',(p['source_key'],)).fetchone()
            if override:
                review=connection.execute('SELECT payload FROM reviews WHERE id=?',(override['review_id'],)).fetchone()
                metadata=json.loads(review[0])['review']
                p.update(json.loads(override['changes']),event_id=override['event_id'],review_status='reviewed',
                         review_id=override['review_id'],reviewer_kind=metadata['reviewer_kind'])
            history=connection.execute("SELECT id,payload,applied_at FROM reviews WHERE EXISTS(SELECT 1 FROM json_each(payload,'$.review.source_keys') WHERE value=?) ORDER BY applied_at",(p['source_key'],)).fetchall()
            p['review_history']=[{'id':r['id'],'applied_at':r['applied_at'],**json.loads(r['payload'])['review']} for r in history]
            versions=connection.execute('SELECT payload FROM proposals WHERE version=? AND article_id=? ORDER BY source_epoch DESC,rowid DESC LIMIT 10',(RULE_VERSION,p['article_id'])).fetchall()
            p['source_history']=[{k:v.get(k) for k in ('id','source_key','event_id','article_title','stage','source_version_at','body_version')} for v in [json.loads(r[0]) for r in versions]]
            related=connection.execute("SELECT payload FROM proposals WHERE version=? AND json_extract(payload,'$.project_id')=? AND id!=? LIMIT 20",(RULE_VERSION,p['project_id'],p['id'])).fetchall() if p['project_id'] else []
            p['related_event_ids']=list(dict.fromkeys(json.loads(v[0])['event_id'] for v in related if json.loads(v[0])['event_id']!=p['event_id']))
            p['related_event_basis']='같은 명시적 프로젝트 식별자 · 변경 관계는 검토 필요' if related else None
            if not axis or p['axis']==axis:proposals.append(p)
        count=connection.execute('SELECT count(*) FROM reviews').fetchone()[0]
    groups={}
    for p in proposals:
        group=groups.setdefault(p['event_id'],{'event_id':p['event_id'],'axis':p['axis'],'event_type':p['event_type'],
            'stage':p['stage'],'article_ids':[],'source_keys':[],'source_urls':[],
            'first_public_status':'observed_sources_only','observed_public_times':[]})
        group['article_ids'].append(p['article_id']);group['source_keys'].append(p['source_key']);group['source_urls'].append(p['url'])
        if p['published_at']:group['observed_public_times'].append(p['published_at'])
    return {'version':RULE_VERSION,'events':list(groups.values()),'proposals':proposals,'reviews':count,
            'scope':'현재 규칙 버전의 최신 기사별 제안 · 미검수 결과는 확인된 사건이 아님'}


def attach(articles):
    result=snapshot([a['id'] for a in articles],limit=max(1,len(articles)))
    by_id={p['article_id']:p for p in result['proposals']}
    for a in articles:
        p=by_id.get(a['id'])
        if p and p['article_title']==a['title']:a['structured_event']=p
    return articles


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='AI 없는 사건 제안·검수')
    sub=parser.add_subparsers(dest='action',required=True)
    ingest_parser=sub.add_parser('ingest');ingest_parser.add_argument('--batches',type=int,default=1)
    review_parser=sub.add_parser('review');review_parser.add_argument('--file',required=True)
    args=parser.parse_args()
    if args.action=='ingest':
        if not 1<=args.batches<=100:parser.error('회차 수는 1~100')
        for _ in range(args.batches):
            result=ingest();print(encode(result))
            if not result['processed']:break
    else:
        print(encode({'review_id':apply_review(json.loads(Path(args.file).read_text()))}))
