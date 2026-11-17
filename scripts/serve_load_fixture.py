"""Issue 27: actual application Handler with isolated, deterministic synthetic input."""
import argparse
import base64
from contextlib import closing
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import sqlite3
import threading
import time
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import archive
import data_worker
import event_facts
import market_history
import price_tracking
import server
import stocks
from llm_provider import Provider

CLOCK = '2026-11-17T05:00:00+00:00'


def article(i):
    return dict(id=f'load27_{i:05}', title=f'합성 부하 기사 {i:05} 반도체',
                url=f'https://load27.invalid/{i:05}', source='합성 입력', source_id='load27',
                kind='news', published_at=CLOCK, collected_at=CLOCK, copies=1)


def fixture_manifest(port):
    result=dict(isolated=True,external_egress_blocked=True,product_mode='data',
                base_url=f'http://127.0.0.1:{port}',browser_trace_calibrated=False,synthetic=True)
    def item(path,checks):
        return {'path':path,'assertions':[{'pointer':k,'equals':v} for k,v in checks]}
    result['dashboard']=[item('/api/dashboard',[('/product_mode','data'),('/articles/0/id','load27_00000')])]
    result['market']=[item('/api/market-watch?market=KR',[('/market','KR'),('/tracked',7)])]
    result['feed']=[item(f'/api/articles?q={i:05}',[('/total',1),('/articles/0/id',f'load27_{i:05}')]) for i in [10,20,30,40]]
    cursor=base64.urlsafe_b64encode(json.dumps([int(datetime.fromisoformat(CLOCK).timestamp()),'https://load27.invalid/00970']).encode()).decode()
    result['feed'] += [item('/api/articles',[('/total',1000),('/articles/0/id','load27_00999')]),
                       item('/api/articles?'+urlencode({'cursor':cursor}),[('/total',1000),('/articles/0/id','load27_00969')]),
                       item('/api/articles?theme=semiconductor',[('/total',1000),('/articles/0/id','load27_00999')]),
                       item('/api/articles?theme=energy',[('/total',0)])]
    result['quotes']=[item('/api/quotes?codes='+str(100000+i),[(f'/quotes/{100000+i}/code',str(100000+i)),
                       (f'/quotes/{100000+i}/price',100+int(sha256(str(100000+i).encode()).hexdigest()[:4],16)%100),
                       (f'/quotes/{100000+i}/status','ok')]) for i in range(4)]
    result['timeline']=[item('/api/stock-timeline?code='+str(100000+i),[('/code',str(100000+i)),('/status','observed'),('/points/59/price',100.59)]) for i in range(4)]
    result['detail']=[item(f'/api/price-movement?article_id=load27_{i:05}',[('/article_id',f'load27_{i:05}')]) for i in [10,20,30,40]]
    return result


def configure(root):
    for module, name in [(archive,'news'),(data_worker,'jobs'),(event_facts,'facts'),
                         (market_history,'market'),(price_tracking,'tracking')]:
        module.PATH = root / (name+'.sqlite3')
    os.environ.update(PRODUCT_MODE='data', LLM_ENABLED='0')
    for key in list(os.environ):
        if any(part in key for part in ('TOKEN','SECRET','API_KEY','TOSS_CLIENT')):
            os.environ.pop(key)
    def denied(*args, **kwargs):
        raise RuntimeError('external provider disabled by load harness')
    Provider.request = denied
    market_history.Toss.request = denied
    def audit(event, args):
        if event == 'socket.getaddrinfo' and args[0] not in ('127.0.0.1','::1','localhost'):
            raise RuntimeError('external DNS disabled by load harness')
        if event == 'socket.connect':
            address=args[1]
            if not isinstance(address,tuple) or address[0] not in ('127.0.0.1','::1'):
                raise RuntimeError('external socket egress disabled by load harness')
    sys.addaudithook(audit)
    catalogue={f'{100000+i}':dict(code=f'{100000+i}',name=f'합성기업{i:05}',country='KR',market='KOSPI',products='') for i in range(10000)}
    catalogue.update({s['code']:{**s,'products':''} for s in server.business_ontology.KNOWLEDGE['securities']})
    stocks.CATALOGUE=catalogue
    stocks.NAME_MATCHER,stocks.NAME_CODES=stocks.compile_names(catalogue)
    price_tracking.now_text=lambda:CLOCK
    def replay(code):
        state=json.loads((root/'fault.json').read_text()) if (root/'fault.json').exists() else {}
        if state.get('provider')=='429':raise ValueError('synthetic external HTTP 429')
        if state.get('provider')=='5xx':raise ValueError('synthetic external HTTP 503')
        if state.get('provider')=='timeout':time.sleep(2);raise TimeoutError('synthetic provider timeout')
        if state.get('provider')=='missing':raise ValueError('synthetic price missing')
        return dict(code=code,name=catalogue[code]['name'],price=100+(int(sha256(code.encode()).hexdigest()[:4],16)%100),
                    change_percent=1,currency='USD' if code[0].isalpha() else 'KRW',
                    traded_at=CLOCK,fetched_at=datetime.now(timezone.utc).isoformat(),
                    market_status='OPEN',delay_label='SYNTHETIC REPLAY',source='Npay 증권',status='ok')
    stocks.collect_quote=replay
    server.STATE.update(articles=[article(i) for i in range(30)],sources=[],collecting=False,updated_at=CLOCK)
    return catalogue


def initialize(root,catalogue):
    if archive.PATH.exists() and (not (root/'inputs.json').exists() or
            json.loads((root/'inputs.json').read_text()).get('synthetic') is not True):
        raise ValueError('refuse existing database without synthetic fixture marker')
    if not archive.PATH.exists():
        archive.store([article(i) for i in range(1000)])
        with market_history.db() as db:
            day='2026-11-17'
            row=dict(date=day,regular_open=True,integrated={'regularMarket':dict(startTime='2026-11-17T00:00:00Z',endTime='2026-11-17T06:30:00Z')})
            market_history.save_calendar(db,'KR',day,{'result':{'today':row,'previousBusinessDay':{**row,'date':'2026-11-16'},'nextBusinessDay':{**row,'date':'2026-11-18'}}})
        clock=datetime.fromisoformat(CLOCK)
        codes=list(catalogue)[:20]+[s['code'] for s in server.business_ontology.KNOWLEDGE['securities']]
        with price_tracking.db() as db:
            for code in codes:
                for i in range(60):
                    at=(clock-timedelta(seconds=(59-i)*30)).timestamp()
                    payload=dict(price=100+i/100,market_status='OPEN',traded_at=datetime.fromtimestamp(at,timezone.utc).isoformat())
                    db.execute('INSERT INTO samples(code,trade_time,observed,payload) VALUES(?,?,?,?)',(code,at,at,json.dumps(payload)))
                db.execute('INSERT OR REPLACE INTO polls VALUES(?,?,?)',(code,clock.timestamp(),'ok'))
        with event_facts.db():pass
        with data_worker.db():pass
    initial={p.name:sha256(p.read_bytes()).hexdigest() for p in root.glob('*.sqlite3')}
    if not (root/'inputs.json').exists():
        (root/'inputs.json').write_text(json.dumps(dict(synthetic=True,articles=1000,catalogue=len(catalogue),tracked_codes=36,points_per_code=60,clock=CLOCK,initial_sha256=initial),indent=2))


def writer(root):
    with archive.db() as db:
        previous=db.execute("SELECT max(json_extract(payload,'$.synthetic_revision')) FROM items").fetchone()[0]
    iteration=0 if previous is None else previous+1
    with (root/'writer.jsonl').open('a',buffering=1) as log:
        while True:
            started=time.monotonic()
            try:
                archive.store([{**article(999),'synthetic_revision':iteration}])
                result='ok'
            except Exception as error:result=type(error).__name__
            log.write(json.dumps(dict(at=time.time(),iteration=iteration,seconds=time.monotonic()-started,result=result))+'\n')
            if result=='ok':iteration+=1
            time.sleep(5)


def verify_fixture(root,baseline=None):
    metadata=json.loads((root/'inputs.json').read_text())
    if metadata.get('synthetic') is not True or metadata.get('articles')!=1000:
        raise ValueError('this checker accepts only the issue27 synthetic fixture')
    with closing(sqlite3.connect(f'file:{root}/news.sqlite3?mode=ro',uri=True)) as db:
        stored=list(db.execute('SELECT fingerprint,payload FROM items'))
    keys={fingerprint for fingerprint,payload in stored}
    revisions=set()
    for _,value in stored:
        payload=json.loads(value)
        if 'synthetic_revision' in payload:revisions.add(payload['synthetic_revision'])
    revisions=sorted(revisions)
    def fingerprint(value):
        return sha256(json.dumps({k:v for k,v in value.items() if k not in ('collected_at','copies')},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    with closing(sqlite3.connect(f'file:{root}/tracking.sqlite3?mode=ro',uri=True)) as db:
        samples=list(db.execute('SELECT code,trade_time,payload FROM samples ORDER BY code,trade_time,id'))
    result={'base_payloads_missing':sum(fingerprint(article(i)) not in keys for i in range(1000)),
            'correction_payloads_missing':sum(fingerprint({**article(999),'synthetic_revision':i}) not in keys for i in range(max(revisions)+1)) if revisions else 0,
            'correction_versions':len(revisions),'stored_payload_fingerprint_mismatches':sum(sha256(value.encode()).hexdigest()!=key for key,value in stored),
            'sample_rows':len(samples),'samples_preserved':sha256(json.dumps(samples).encode()).hexdigest()==json.loads(baseline.read_text())['sample_rows_sha256'] if baseline else None}
    result['baseline_supplied']=baseline is not None
    writes=[json.loads(line) for line in (root/'writer.jsonl').read_text().splitlines()]
    successful=[row['iteration'] for row in writes if row['result']=='ok']
    result['successful_writes_missing']=len(set(successful)-set(revisions))
    result['duplicate_successful_write_keys']=len(successful)-len(set(successful))
    result['integrity_ok']=not any(result[k] for k in ['base_payloads_missing','correction_payloads_missing','stored_payload_fingerprint_mismatches','successful_writes_missing','duplicate_successful_write_keys']) and result['samples_preserved'] is not False
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--port',type=int,default=19227)
    parser.add_argument('--verify',action='store_true');parser.add_argument('--baseline',type=Path)
    args=parser.parse_args();root=args.root.resolve()
    if args.verify:
        result=verify_fixture(root,args.baseline);print(json.dumps(result));sys.exit(0 if result['integrity_ok'] else 2)
    root.mkdir(parents=True,exist_ok=True)
    catalogue=configure(root);initialize(root,catalogue)
    class Handler(server.Handler):
        def log_message(self,*args):pass
    http=server.ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    (root/'manifest.json').write_text(json.dumps(fixture_manifest(http.server_port),ensure_ascii=False,indent=2))
    threading.Thread(target=writer,args=(root,),daemon=True).start()
    print(json.dumps(dict(pid=os.getpid(),port=http.server_port,synthetic=True,root=str(root))),flush=True)
    http.serve_forever()


if __name__=='__main__':main()
