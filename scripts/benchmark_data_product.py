"""Fixed SQLite backup + warm HTTP workload; intentionally no collectors or providers."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from hashlib import sha256
import argparse
import json
import math
import os
from pathlib import Path
import platform
import sqlite3
import sys
import tempfile
import threading
import time
from urllib.request import urlopen

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import archive
import data_worker
import event_facts
import market_history
import server
import stocks
from llm_provider import Provider


def p95(values):return sorted(values)[math.ceil(.95*len(values))-1] if values else None


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--snapshot');args=parser.parse_args()
    source_paths=[(archive,'news'),(event_facts,'facts'),(market_history,'market'),(data_worker,'jobs')]
    root=archive.PATH.parent/'validation';root.mkdir(parents=True,exist_ok=True)
    directory=args.snapshot or tempfile.mkdtemp(prefix='benchmark-',dir=root)
    expected=json.loads((Path(directory)/'manifest.json').read_text()) if args.snapshot else None
    with nullcontext(directory):
        hashes={}
        for module,name in source_paths:
            target=Path(directory)/(name+'.sqlite3')
            if not args.snapshot:
                source=sqlite3.connect(module.PATH);destination=sqlite3.connect(target)
                try:source.backup(destination)
                finally:source.close();destination.close()
            hashes[name]=sha256(target.read_bytes()).hexdigest();module.PATH=target
        if expected and hashes!=expected:raise ValueError('고정 DB 지문 불일치')
        (Path(directory)/'manifest.json').write_text(json.dumps(hashes,sort_keys=True))
        calls={'llm':0,'toss':0}
        def blocked(kind):
            def call(*args,**kwargs):calls[kind]+=1;raise AssertionError('provider call in read benchmark')
            return call
        Provider.request=blocked('llm');market_history.Toss.request=blocked('toss')
        os.environ['PRODUCT_MODE']='data';os.environ['LLM_ENABLED']='0'
        catalogue={s['code']:{**s,'products':''} for s in server.business_ontology.KNOWLEDGE['securities']}
        stocks.CATALOGUE=catalogue;stocks.NAME_MATCHER,stocks.NAME_CODES=stocks.compile_names(catalogue)
        server.STATE.update(articles=archive.restore(),sources=[],collecting=False)
        paths=['/api/dashboard','/api/articles?limit=30','/api/business','/api/supply','/api/theme-statistics','/api/events?limit=30']
        with data_worker.db() as db:row=db.execute("SELECT payload FROM work WHERE state='complete' LIMIT 1").fetchone()
        if row:
            work=json.loads(row[0]);paths+=['/api/reactions?article_id='+work['article_id']]
        class Handler(server.Handler):
            def log_message(self,*args):pass
        http=server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        def request(path):
            started=time.perf_counter()
            try:
                with urlopen('http://127.0.0.1:'+str(http.server_port)+path,timeout=15) as response:
                    payload=response.read();status=response.status
                return {'path':path,'seconds':time.perf_counter()-started,'status':status,'bytes':len(payload)}
            except Exception as error:return {'path':path,'seconds':time.perf_counter()-started,'error':type(error).__name__}
        try:
            warmups=[request(path) for path in paths]
            with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(request,paths*10))
        finally:http.shutdown();http.server_close();thread.join()
        groups={path:p95([r['seconds'] for r in results if r['path']==path]) for path in paths}
        errors=[r for r in [*warmups,*results] if r.get('status')!=200]
        report={'version':'data-product-http-benchmark-v1','hardware':{'platform':platform.platform(),'machine':platform.machine(),'logical_cpus':os.cpu_count()},
            'snapshot_hashes':hashes,'snapshot_directory':str(directory),'archive':archive.summary(),'catalogue_securities':len(catalogue),'concurrency':2,
            'timed_requests':len(results),'cache':'process/SQLite warmed by one request per endpoint; HTTP no-store; no application cache',
            'p95_seconds':p95([r['seconds'] for r in results]),'endpoint_p95':groups,'errors':errors,
            'limited_workload_goal':'met' if not errors and all(v<1 for v in groups.values()) else 'unmet',
            'llm_calls':calls['llm'],'toss_calls':calls['toss'],'embedding_calls':0,'release_approved':False,
            'limitations':['단일 Linux Docker 환경의 짧은 측정','등록 16종목의 고정 목록만 사용 · 운영 전체 상장 목록의 성능은 미검증','OS 콜드 캐시·장기 부하·수집부터 반영까지의 지연은 측정하지 않음']}
        output=Path(__file__).resolve().parents[1]/'.data/validation/http_benchmark_v1.json'
        output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
        encoded=json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)
        (Path(directory)/('report-'+sha256(encoded.encode()).hexdigest()+'.json')).write_text(encoded)
        print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
