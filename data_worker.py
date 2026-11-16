"""Bounded data-only processing, separate from the fast news collector."""

import argparse
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sqlite3
import time

import business_ontology as business
import event_facts
import event_reactions as reactions
import market_history as h
from news_ingestion import lease
import supply
import theme_statistics as themes

PATH=Path(__file__).parent/'.data/data_jobs.sqlite3'
VERSION='data-worker-v1'


@contextmanager
def db():
    PATH.parent.mkdir(parents=True,exist_ok=True)
    connection=sqlite3.connect(PATH,timeout=10);connection.row_factory=sqlite3.Row
    try:
        with connection:
            connection.executescript('''CREATE TABLE IF NOT EXISTS work (
                id TEXT PRIMARY KEY,payload TEXT,state TEXT,reason TEXT,due REAL,created TEXT,updated TEXT,
                fingerprint TEXT,result_id TEXT,attempts INTEGER DEFAULT 0);
                CREATE INDEX IF NOT EXISTS work_due ON work(state,due);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY,payload TEXT);
                CREATE TABLE IF NOT EXISTS work_history (id TEXT PRIMARY KEY,work_id TEXT,payload TEXT,at TEXT);''')
            yield connection
    finally:connection.close()


def put_metadata(key,value):
    with db() as connection:connection.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',(key,h.encode(value)))


def metadata(key,default=None):
    with db() as connection:row=connection.execute('SELECT payload FROM metadata WHERE key=?',(key,)).fetchone()
    return json.loads(row[0]) if row else default


def universe():
    return {(s['country'],s['provider_symbol']):s for s in business.KNOWLEDGE['securities']}


def enqueue(facts):
    securities=universe();by_code={s['code']:k for k,s in securities.items()}
    relation_version=event_facts.digest([business.KNOWLEDGE,supply.KNOWLEDGE])
    stamp=h.now();count=0
    with db() as connection:
        for fact in facts:
            if not fact.get('axis'):continue
            codes={a.get('code') for a in fact.get('actors',[])}
            targets=[by_code[c] for c in sorted(c for c in codes if c in by_code)]
            coverage='mentioned_security_not_beneficiary'
            if fact['axis'] in ('rates','fx','tariff'):
                targets=list(securities);coverage='tracked_universe_observation_not_related_stock_claim'
            if not targets:
                targets=[(None,None)];coverage='no_supported_listed_security'
            for market,symbol in targets:
                for basis in ('public','available'):
                    payload={'article_id':fact['article_id'],'source_key':fact['source_key'],'event_id':fact['event_id'],
                             'rule_version':fact['rule_version'],'review_id':fact.get('review_id'),'relation_version':relation_version,
                             'market':market,'symbol':symbol,'basis':basis,'coverage':coverage,'version':VERSION,
                             'priority_at':fact.get('first_seen_at') or fact.get('available_at'),
                             'calculation_version':reactions.VERSION,'calendar_policy':h.CALENDAR_POLICY}
                    key=event_facts.digest(payload)
                    state='pending' if market else 'unsupported'
                    connection.execute("UPDATE work SET state='superseded',reason='new_source_rule_review_or_relation',updated=? WHERE id!=? AND json_extract(payload,'$.article_id')=? AND json_extract(payload,'$.market') IS ? AND json_extract(payload,'$.symbol') IS ? AND json_extract(payload,'$.basis')=? AND state!='superseded'",
                        (stamp,key,fact['article_id'],market,symbol,basis))
                    count+=connection.execute('INSERT OR IGNORE INTO work(id,payload,state,reason,due,created,updated) VALUES(?,?,?,?,?,?,?)',
                        (key,h.encode(payload),state,coverage,0,stamp,stamp)).rowcount
    return count


def discover():
    version=event_facts.digest([event_facts.RULE_VERSION,business.KNOWLEDGE,supply.KNOWLEDGE,reactions.VERSION,h.CALENDAR_POLICY])
    cursor_key='discovery_cursor:'+version
    cursor=metadata(cursor_key,0)
    with event_facts.db() as connection:
        rows=connection.execute('SELECT rowid,article_id FROM proposals WHERE version=? AND rowid>? ORDER BY rowid LIMIT 100',(event_facts.RULE_VERSION,cursor)).fetchall()
        recent=connection.execute('SELECT article_id FROM proposals WHERE version=? ORDER BY rowid DESC LIMIT 50',(event_facts.RULE_VERSION,)).fetchall()
        revised=connection.execute('SELECT p.article_id FROM proposals p JOIN overrides o ON p.source_key=o.source_key WHERE p.version=?',(event_facts.RULE_VERSION,)).fetchall()
    ids=list(dict.fromkeys([r['article_id'] for r in [*recent,*rows,*revised]]))
    count=0
    for offset in range(0,len(ids),500):count+=enqueue(event_facts.snapshot(ids[offset:offset+500])['proposals'])
    # Enqueue commits before advancing; replay after termination only repeats INSERT OR IGNORE.
    if rows:put_metadata(cursor_key,rows[-1]['rowid'])
    return count


def update(identifier,state,reason,fingerprint=None,result_id=None,delay=60):
    with db() as connection:
        connection.execute('UPDATE work SET state=?,reason=?,due=?,updated=?,fingerprint=coalesce(?,fingerprint),result_id=coalesce(?,result_id) WHERE id=?',
                           (state,reason,time.time()+delay,h.now(),fingerprint,result_id,identifier))
        record={'state':state,'reason':reason,'fingerprint':fingerprint,'result_id':result_id}
        connection.execute('INSERT OR IGNORE INTO work_history VALUES(?,?,?,?)',
                           (event_facts.digest([identifier,record]),identifier,h.encode(record),h.now()))


def observe(job):
    payload=json.loads(job['payload']);identifier=job['id']
    facts=event_facts.snapshot([payload['article_id']])['proposals']
    current=facts[0] if facts else None
    versions=(payload.get('relation_version')==event_facts.digest([business.KNOWLEDGE,supply.KNOWLEDGE]) and
              payload.get('calculation_version')==reactions.VERSION and payload.get('calendar_policy')==h.CALENDAR_POLICY)
    if not current or not versions or any(current.get(k)!=payload.get(k) for k in ('source_key','event_id','rule_version','review_id')):
        update(identifier,'superseded','source_or_review_changed',delay=86400);return
    inputs=reactions.load_inputs(payload['article_id'],payload['market'],payload['symbol'],basis=payload['basis'])
    stable={k:v for k,v in inputs.items() if k!='as_of'}
    # A newly closed session can change readiness without a new stored price yet.
    stable['closed_sessions']=[p['day'] for p in reactions.sessions(inputs['calendar'],payload['market']) if h.timestamp(p['close'])<=h.timestamp(inputs['as_of'])]
    fingerprint=event_facts.digest(stable)
    if job['fingerprint']==fingerprint and job['state'] not in ('running','error'):
        update(identifier,job['state'],job['reason'],delay=300);return
    result=reactions.run(payload['article_id'],payload['market'],payload['symbol'],basis=payload['basis'],as_of=inputs['as_of'])
    windows=result['windows'];complete=bool(windows) and all(w['raw_return'] is not None for w in windows)
    if complete:state,reason='complete','observed_with_quality_limits'
    elif result['status']=='event_time_unknown':state,reason='unsupported','event_time_unknown'
    else:
        state='waiting'
        reason='window_not_closed' if any(w.get('end') and h.timestamp(w['end']['close'])>h.timestamp(inputs['as_of']) for w in windows) else ';'.join(sorted({w['status'] for w in windows})) or result['status']
    update(identifier,state,reason,fingerprint,result['run_id'],delay=3600 if complete else 300)


def collect_one(client):
    clock=datetime.now(timezone.utc);until=(clock+timedelta(days=7)).date().isoformat();since=(clock-timedelta(days=280)).date().isoformat()
    series=[*universe(),('KR','KOSPI'),('US','SPY')]
    states=metadata('series',{})
    market,symbol=min(series,key=lambda item:states.get(h.encode(item),{}).get('due',0))
    key=h.encode((market,symbol))
    if states.get(key,{}).get('due',0)>time.time():return None
    result=h.collect(market,symbol,since,until,pages=1,client=client)
    states[key]={'due':time.time()+(3600 if result['status']=='complete' else 60),'updated':h.now(),
                 'status':result['status'],'error':result.get('error'),'market':market,'symbol':symbol}
    put_metadata('series',states)
    return states[key]


def refresh_themes():
    inputs=themes.load_inputs();stable={k:v for k,v in inputs.items() if k!='as_of'}
    stable['day']=inputs['as_of'][:10];key=event_facts.digest(stable)
    if metadata('theme_fingerprint')==key:return
    result=themes.run(as_of=inputs['as_of']);put_metadata('theme_fingerprint',key)
    put_metadata('theme',{'run_id':result['run_id'],'updated_at':h.now(),
                          'observed_members':sum(t['observed_members'] for t in result['themes'])})


def cycle(client=None,network=True):
    with lease('data-product.lock') as acquired:
        if not acquired:return {'state':'busy'}
        started=time.monotonic();put_metadata('started',h.now())
        try:
            ingested=event_facts.ingest(100);added=discover()
            price=collect_one(client or h.Toss()) if network else None
            with db() as connection:
                # A killed process leaves running rows; the OS lease makes their retry exclusive.
                oldest=connection.execute("SELECT * FROM work WHERE state IN ('pending','waiting','error','complete','running') AND due<=? ORDER BY CASE WHEN state='running' THEN 0 ELSE 1 END,due,created LIMIT 4",(time.time(),)).fetchall()
                newest=connection.execute("SELECT * FROM work WHERE state='pending' AND due<=? ORDER BY julianday(json_extract(payload,'$.priority_at')) DESC,created DESC LIMIT 2",(time.time(),)).fetchall()
                jobs=list({j['id']:j for j in [*oldest[:2],*newest,*oldest[2:]]}.values())[:4]
            for job in jobs:
                with db() as connection:connection.execute("UPDATE work SET state='running',attempts=attempts+1,updated=? WHERE id=?",(h.now(),job['id']))
                try:observe(job)
                except Exception as error:update(job['id'],'error',type(error).__name__,delay=60)
            refresh_themes()
            result={'state':'ok','last_success':h.now(),'seconds':round(time.monotonic()-started,3),
                    'ingestion':ingested,'enqueued':added,'observed_jobs':len(jobs),'price':price,'ai_calls':0}
            put_metadata('last_cycle',result);return result
        except Exception as error:
            result={'state':'error','error':type(error).__name__,'at':h.now(),'ai_calls':0}
            put_metadata('last_error',result);return result


def status():
    if not PATH.exists():return {'version':VERSION,'state':'not_started','ai_calls':0}
    with db() as connection:
        counts={r[0]:r[1] for r in connection.execute('SELECT state,count(*) FROM work GROUP BY state')}
        oldest=connection.execute("SELECT min(created) FROM work WHERE state IN ('pending','waiting','error','running')").fetchone()[0]
        recent=[dict(r) for r in connection.execute("SELECT state,reason,updated FROM work WHERE state!='complete' ORDER BY updated DESC LIMIT 10")]
    return {'version':VERSION,'counts':counts,'oldest_unfinished':oldest,'recent_states':recent,'last_cycle':metadata('last_cycle'),
            'last_error':metadata('last_error'),'series':list(metadata('series',{}).values()),'theme':metadata('theme'),
            'ai_calls':0,'scope':'등록 종목 관측 · 매수·수혜 판정 아님 · 분봉 미지원'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='AI 없는 사건·일봉·통계 작업자')
    parser.add_argument('mode',choices=('worker','once','reconcile'));args=parser.parse_args()
    client=h.Toss()
    while True:
        print(json.dumps(cycle(client,network=args.mode!='reconcile'),ensure_ascii=False),flush=True)
        if args.mode!='worker':break
        time.sleep(30)
