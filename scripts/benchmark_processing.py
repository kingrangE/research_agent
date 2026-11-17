"""Issue #26: offline processing replay, never HTTP latency or a production load test."""
import argparse
from contextlib import ExitStack
import cProfile
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import platform
import resource
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import archive
import business_ontology
import data_product
import data_worker as worker
import event_facts
import event_reactions
import market_history
import news_ingestion
import relations
import supply
import theme_statistics
from llm_provider import Provider

BASELINE = 'f7b9190c5bba1166cba2166d4361f2cb0712ed86'
# Budgets fixed before measurement; allocation is provisional pending production arrival data.
BUDGET = {'cycle': 30, 'ingest': 8, 'discover': 4, 'observe': 12, 'themes': 4, 'response': 2}
AS_OF = '2026-11-17T00:00:00+00:00'
SOURCE_TIME = '2026-11-05T08:00:00+00:00'
MODULES = {'news': archive, 'facts': event_facts, 'market': market_history, 'jobs': worker}


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def distribution(values):
    ordered = sorted(values)
    return {'n': len(values), **{f'p{q}': ordered[math.ceil(q / 100 * len(ordered)) - 1] if ordered else None for q in (50, 95, 99)}}


def synthetic(count):
    rows = [{'officeId': '001', 'articleId': f'{i:010d}', 'officeHname': 'synthetic',
             'title': f'삼성전자 데이터센터 건설 발표 프로젝트 번호: EVAL{i:06d}',
             'datetime': '2025-01-02 10:00:00'} for i in range(count)]
    return [{k:v for k,v in a.items() if k not in ('collected_at','copies')} for a in news_ingestion.parse_articles(rows, '2025-01-02')]


def expand(articles, scale):
    result = []
    for copy in range(scale):
        for a in articles:
            result.append(dict(a) if copy == 0 else {**a, 'id': digest([a['id'], copy])[:16],
                'url': a['url'] + f'?eval26={copy}', 'title': a['title'] + f' 확장사례 {copy}-{a["id"]}'})
    return result



def supported_articles(count):
    return [{**a, 'title': f'삼성전자 SK하이닉스 데이터센터 건설 발표 프로젝트 번호: SUCCESS{i:06d}',
             'published_at': '2026-11-05T10:00:00+09:00', 'timestamp_basis': 'publisher'}
            for i,a in enumerate(synthetic(count))]


def body(article):
    return article['title'] + ' 양사는 서버와 메모리 설비를 함께 구축하고 단계적으로 투자한다는 구체적인 사업 내용을 공개했다. 투자 규모는 100억원이며 개별 프로젝트의 진행 상황을 별도로 확인해야 한다.'


def seed_supported_market(path):
    """Deterministic synthetic weekdays/candles through real validation/storage APIs."""
    until = datetime.fromisoformat(AS_OF).date() - timedelta(days=1)
    since = until - timedelta(days=410)
    bars = {symbol: [] for symbol in ('005930', '000660', 'KOSPI')}
    prices = {symbol: 100.0 for symbol in bars}; k = 0; calendar = []
    def session(day):
        key = day.isoformat()
        return {'date': key, 'integrated': {'regularMarket': {'startTime': key+'T09:00:00+09:00',
                    'endTime': key+'T15:30:00+09:00'}} if day.weekday() < 5 else None}
    with patch.object(market_history, 'PATH', path), patch.object(market_history, 'now', return_value=AS_OF):
        with market_history.db() as db:
            for offset in range((until-since).days+2):
                day = since + timedelta(days=offset)
                previous = day-timedelta(days=1); following = day+timedelta(days=1)
                while previous.weekday() > 4: previous -= timedelta(days=1)
                while following.weekday() > 4: following += timedelta(days=1)
                response = {'result': {'today': session(day), 'previousBusinessDay': session(previous), 'nextBusinessDay': session(following)}}
                calendar.append(response)
                market_history.save_calendar(db, 'KR', day.isoformat(), response)
                if day > until or day.weekday() > 4: continue
                x = .006 if k % 2 else -.006; e = .001 if k % 3 else -.002
                for symbol, change in (('005930',2*x+e), ('000660',3*x-e), ('KOSPI',x)):
                    prices[symbol] *= 1+change
                    close = f'{prices[symbol]:.8f}'
                    bars[symbol].append({'timestamp':day.isoformat()+'T00:00:00+09:00',
                        'openPrice':close,'highPrice':close,'lowPrice':close,'closePrice':close,
                        'volume':'10000','currency':'KRW'})
                k += 1
            for symbol, rows in bars.items():
                for offset in range(0,len(rows),200):
                    market_history.save_page(db,'KR',symbol,False,{'synthetic':'eval26-supported-v1'},
                        {'result':{'candles':rows[offset:offset+200],'nextBefore':None}},since.isoformat(),until.isoformat())
    return {'version':'eval26-supported-v1','as_of':AS_OF,'source_time':SOURCE_TIME,
            'since':since.isoformat(),'until':until.isoformat(),'bars':{s:len(v) for s,v in bars.items()},
            'calendar_requests':len(calendar),'logical_fingerprint':digest([calendar,bars]),
            'synthetic_calendar':'KR weekdays, not an actual exchange calendar',
            'price_rule':'x=+/-0.006, e=0.001 unless k%3==0 then -0.002; Samsung=2x+e, Hynix=3x-e, KOSPI=x; volume=10000'}


def supported_results():
    with market_history.db() as db:
        event_reactions.schema(db); theme_statistics.schema(db)
        reactions = [json.loads(r[0]) for r in db.execute('SELECT result FROM reaction_runs ORDER BY id')]
        themes = [json.loads(r[0]) for r in db.execute('SELECT result FROM theme_runs ORDER BY id')]
    pairs = [p for run in themes for t in run['themes'] for p in t['pairs']]
    return {'latest_events':len(event_facts.snapshot()['events']), 'reaction_runs':len(reactions),'complete_reaction_runs':sum(bool(r['windows']) and all(w['raw_return'] is not None for w in r['windows']) for r in reactions),
            'estimated_reaction_models':sum(r.get('model',{}).get('status')=='estimated' for r in reactions),
            'observed_theme_members':sum(t['observed_members'] for run in themes for t in run['themes']),
            'observed_raw_pairs':sum(p['raw']['value'] is not None for p in pairs),
            'observed_adjusted_pairs':sum(p['market_adjusted']['value'] is not None for p in pairs),
            'reaction_values_fingerprint':digest(reactions),'theme_values_fingerprint':digest(themes)}

def counts():
    with archive.db() as db:
        revisions = db.execute('SELECT count(*) FROM items').fetchone()[0]
        bodies = db.execute('SELECT count(DISTINCT url) FROM bodies').fetchone()[0]
    with event_facts.db() as db:
        proposals = db.execute('SELECT count(*) FROM proposals').fetchone()[0]
    with worker.db() as db:
        states = dict(db.execute('SELECT state,count(*) FROM work GROUP BY state'))
    return {'revisions': revisions, 'bodies': bodies, 'proposals': proposals, 'states': states}


def semantic():
    proposals = event_facts.snapshot()['proposals']
    # Processing/availability timestamps are observations, not deterministic classification outputs.
    fields = ('article_id', 'source_key', 'event_id', 'axis', 'stage', 'actors', 'rule_version')
    return digest(sorted([{k: p.get(k) for k in fields} for p in proposals], key=lambda p: p['article_id']))


def replay(directory, articles, scenario, cache, instrument=True, supported=False):
    timings = {}; queue = []; arrivals = {}; cycles = []; backlog = []; failures = []; processed = []
    stored_at = None; intake_queue = []
    computations = {'reactions': 0, 'themes': 0, 'observation_attempts': 0}
    sql = {'statements': 0, 'writes': 0, 'errors': 0, 'execute_seconds': 0.0, 'write_execute_seconds': 0.0, 'lock_errors': 0}
    original_connect = sqlite3.connect
    reference_extract = event_facts.extract

    class Connection(sqlite3.Connection):
        def execute(self, *args, **kwargs):
            started = time.perf_counter()
            try:
                return super().execute(*args, **kwargs)
            except sqlite3.Error as error:
                sql['errors'] += 1
                sql['lock_errors'] += int('locked' in str(error).lower() or 'busy' in str(error).lower())
                raise
            finally:
                duration = time.perf_counter() - started
                sql['execute_seconds'] += duration
                if args[0].lstrip().split(' ', 1)[0].upper() in ('INSERT','UPDATE','DELETE','REPLACE'):
                    sql['write_execute_seconds'] += duration

    def connect(*args, **kwargs):
        kwargs['factory'] = Connection
        connection = original_connect(*args, **kwargs)
        def trace(statement):
            sql['statements'] += 1
            if statement.lstrip().split(' ', 1)[0].upper() in ('INSERT', 'UPDATE', 'DELETE', 'REPLACE'):
                sql['writes'] += 1
        connection.set_trace_callback(trace)
        return connection

    def timed(name, fn):
        def call(*args, **kwargs):
            started = time.perf_counter()
            if name == 'classify_link' and stored_at is not None:
                intake_queue.append(started - stored_at)
            try:
                return fn(*args, **kwargs)
            finally:
                timings.setdefault(name, []).append(time.perf_counter() - started)
        return call

    with ExitStack() as stack:
        for name, module in MODULES.items():
            stack.enter_context(patch.object(module, 'PATH', directory / (name + '.sqlite3')))
        if supported:
            class SourceDatetime(datetime):
                @classmethod
                def now(cls, tz=None):
                    return datetime.fromisoformat(SOURCE_TIME).astimezone(tz)
            stack.enter_context(patch.object(archive, 'datetime', SourceDatetime))
            stack.enter_context(patch.object(event_facts, 'now', return_value=SOURCE_TIME))
            stack.enter_context(patch.object(market_history, 'now', return_value=AS_OF))
        def store_articles(items):
            archive.store(items)
            if supported:
                for article in items: archive.save_body(article['url'], body(article))
        # Safety boundary: block sockets, providers, and collector before processing anything.
        def denied(*args, **kwargs):
            raise AssertionError('external call forbidden in processing replay')
        stack.enter_context(patch.object(socket.socket, 'connect', denied))
        stack.enter_context(patch.object(socket.socket, 'connect_ex', denied))
        stack.enter_context(patch.object(Provider, 'request', denied))
        stack.enter_context(patch.object(market_history.Toss, 'request', denied))
        stack.enter_context(patch.object(worker, 'collect_one', denied))
        if instrument:
            stack.enter_context(patch.object(sqlite3, 'connect', connect))
            for module, attr, label in ((event_facts, 'ingest', 'ingest'), (event_facts, 'extract', 'classify_link'),
                    (worker, 'discover', 'discover'), (worker, 'observe', 'observe'),
                    (event_reactions, 'calculate', 'reaction_compute'), (worker, 'refresh_themes', 'themes'),
                    (theme_statistics, 'calculate', 'theme_compute')):
                stack.enter_context(patch.object(module, attr, timed(label, getattr(module, attr))))
        for module, attr, key in (((event_reactions, 'run', 'reactions'), (theme_statistics, 'run', 'themes')) if instrument else ()):
            original = getattr(module, attr)
            def counted(*args, _fn=original, _key=key, **kwargs):
                computations[_key] += 1
                return _fn(*args, **kwargs)
            stack.enter_context(patch.object(module, attr, counted))
        original_enqueue = worker.enqueue
        original_observe = worker.observe
        def enqueue(facts):
            result = original_enqueue(facts)
            with worker.db() as db:
                for row in db.execute("SELECT id FROM work WHERE state='pending'"):
                    arrivals.setdefault(row[0], time.perf_counter())
                backlog.append({'executable': db.execute("SELECT count(*) FROM work WHERE state IN ('pending','running','error') AND due<=?",(time.time(),)).fetchone()[0],
                                'observation_waiting': db.execute("SELECT count(*) FROM work WHERE state='waiting'").fetchone()[0]})
            return result
        def observe(job):
            if job['id'] in arrivals:
                queue.append(time.perf_counter() - arrivals.pop(job['id']))
            computations['observation_attempts'] += 1
            return original_observe({**dict(job), 'fingerprint': None} if cache == 'off' else job)
        if instrument:
            stack.enter_context(patch.object(worker, 'enqueue', enqueue))
            stack.enter_context(patch.object(worker, 'observe', observe))
        if cache == 'off':
            original_refresh = worker.refresh_themes
            def refresh():
                with worker.db() as db:
                    db.execute("DELETE FROM metadata WHERE key='theme_fingerprint'")
                    db.execute('UPDATE work SET fingerprint=NULL')
                return original_refresh()
            stack.enter_context(patch.object(worker, 'refresh_themes', refresh))

        due_states = "('pending','running','error','complete')" if supported else "('pending','running','error')"
        def drain():
            # Finite new-work replay: waiting/complete rows retain their real future due time.
            for _ in range(max(10, len(articles) * 3)):
                if cache == 'off' and not instrument:
                    with worker.db() as db:
                        db.execute('UPDATE work SET fingerprint=NULL')
                started = time.perf_counter()
                result = worker.cycle(network=False)
                cycles.append(time.perf_counter() - started)
                processed.append(result.get('ingestion', {}).get('processed', 0))
                if result['state'] != 'ok':
                    failures.append(result); break
                with worker.db() as db:
                    executable = db.execute("SELECT count(*) FROM work WHERE state IN "+due_states+" AND due<=?", (time.time(),)).fetchone()[0]
                    waiting = db.execute("SELECT count(*) FROM work WHERE state='waiting'").fetchone()[0]
                backlog.append({'executable': executable, 'observation_waiting': waiting})
                if not executable and not result['ingestion']['processed'] and not result['enqueued']:
                    return
            else:
                failures.append({'state': 'timeout', 'reason': 'cycle_cap'})

        # Existing snapshot is a source only. Derived facts/jobs are always rebuilt in this private run.
        store_articles(articles)
        drain()
        before = counts(); before_semantic = semantic()
        before_values = supported_results() if supported else None
        timings.clear(); queue.clear(); cycles.clear(); backlog.clear(); processed.clear(); sql.update(statements=0, writes=0, errors=0, execute_seconds=0.0, write_execute_seconds=0.0, lock_errors=0)
        for key in computations:
            computations[key] = 0
        if scenario == 'new':
            # New source and derived rows; market snapshot is kept fixed.
            for name in ('news', 'facts', 'jobs'):
                MODULES[name].PATH.unlink(missing_ok=True)
            if supported:
                with market_history.db() as db:
                    db.execute('DELETE FROM reaction_runs'); db.execute('DELETE FROM theme_runs')
        elif scenario == 'correction':
            corrected = [{**a, 'title': a['title'].replace('발표', '취소') + ' 정정'} for a in articles[:max(1, len(articles)//10)]]
        elif scenario == 'rules':
            knowledge = {**supply.KNOWLEDGE, 'evaluation_relation_revision': 'eval26-invalidation-only'}
            stack.enter_context(patch.object(supply, 'KNOWLEDGE', knowledge))
        elif scenario != 'repeat':
            raise ValueError('unknown scenario')
        # Re-run existing observations when replaying identical inputs or changed rules.
        with worker.db() as db:
            db.execute('UPDATE work SET due=0 WHERE state IN (\'waiting\',\'complete\')')
            for row in db.execute("SELECT id FROM work WHERE state IN ('pending','waiting','complete')"):
                arrivals[row[0]] = time.perf_counter()
        start = time.perf_counter(); cpu = time.process_time()
        if scenario == 'new':
            timed('store', store_articles)(articles)
            stored_at = time.perf_counter()
        elif scenario == 'correction':
            timed('store', store_articles)(corrected)
            stored_at = time.perf_counter()
        drain()
        drained = time.perf_counter() - start
        response_start = time.perf_counter()
        response = archive.browse(limit=30)
        data_product.attach(response['articles'])
        timings.setdefault('response', []).append(time.perf_counter() - response_start)
        elapsed = time.perf_counter() - start; cpu = time.process_time() - cpu
        after = counts(); after_semantic = semantic()
        corrected_facts = event_facts.snapshot([a['id'] for a in corrected])['proposals'] if scenario == 'correction' else []
        provenance = archive.provenance([a['url'] for a in corrected]) if scenario == 'correction' and supported else {}
        expected_corrections = {a['id']: reference_extract(a, body(a) if supported else None, provenance.get(a['url'],{}).get('body_version')) for a in corrected} if scenario == 'correction' else {}
        values = supported_results() if supported else None
        checks = {'new_preserves_semantics': after_semantic == before_semantic if scenario == 'new' else None,
                  'repeat_preserves_counts': after == before if scenario == 'repeat' else None,
                  'repeat_preserves_semantics': after_semantic == before_semantic if scenario == 'repeat' else None,
                  'correction_adds_expected_revisions': after['revisions'] == before['revisions'] + max(1, len(articles)//10) if scenario == 'correction' else None,
                  'correction_visible': len(corrected_facts) == len(expected_corrections) and all(p['source_key'] == expected_corrections[p['article_id']]['source_key'] and p['stage'] == expected_corrections[p['article_id']]['stage'] for p in corrected_facts) if scenario == 'correction' else None,
                  'rules_supersede_old_jobs': after['states'].get('superseded', 0) > 0 if scenario == 'rules' and sum(before['states'].values()) else None}
        if supported:
            checks.update(independent_events=values['latest_events']==len(articles), successful_jobs=after['states'].get('complete',0)==len(articles)*4,
                full_reaction_windows=values['reaction_runs']>0 and values['complete_reaction_runs']==values['reaction_runs'],
                estimated_models=values['estimated_reaction_models']==values['reaction_runs'],
                observed_theme_pairs=values['observed_raw_pairs']>=2 and values['observed_adjusted_pairs']>=2,
                unchanged_values=values==before_values if scenario in ('new','repeat','rules') else None)
        return {'supported_synthetic': supported, 'supported_results': values, 'scenario': scenario, 'cache': cache, 'instrumented': instrument, 'elapsed_seconds': elapsed,
                'cpu_seconds': cpu, 'cycle_seconds': distribution(cycles), 'stages_inclusive_seconds': {k: distribution(v) for k,v in timings.items()},
                'stage_budget_p95': {k: ('met' if distribution(v)['p95'] <= (BUDGET[k]/4 if k == 'observe' else BUDGET[k]) else 'unmet') for k,v in timings.items() if k in BUDGET},
                'stored_to_classify_start_seconds': distribution(intake_queue), 'queue_monotonic_seconds': distribution(queue), 'counts_before': before, 'counts_after': after,
                'backlog_samples': backlog, 'peak_executable_backlog': max((b['executable'] for b in backlog), default=0),
                'drain_seconds': drained if backlog and backlog[-1]['executable'] == 0 else None,
                'processed_article_versions': sum(processed), 'processed_article_versions_per_second': sum(processed)/elapsed,
                'input_articles_per_second': len(articles)/elapsed if scenario == 'new' else None,
                'computations': computations if instrument else None, 'external_wait_seconds': None, 'sql_instrumented': sql if instrument else None, 'semantic_fingerprint': after_semantic,
                'checks': checks, 'failures': failures,
                'calculated_complete_jobs': after['states'].get('complete',0),
                'cycle_budget': 'met' if cycles and distribution(cycles)['p95'] <= BUDGET['cycle'] else 'unmet'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path, help='private directory containing news.sqlite3 and market.sqlite3; never modified')
    parser.add_argument('--base-count', type=int, default=10)
    parser.add_argument('--repetitions', type=int, default=3)
    parser.add_argument('--profile', action='store_true')
    parser.add_argument('--supported-synthetic', action='store_true', help='synthetic bodies, historical prices and full windows; never real market evidence')
    args = parser.parse_args()
    if args.snapshot and args.supported_synthetic:
        parser.error('snapshot and supported-synthetic are separate datasets')
    if not 1 <= args.base_count <= 1000 or not 1 <= args.repetitions <= 20:
        parser.error('base-count 1..1000, repetitions 1..20')
    args.output.mkdir(parents=True, exist_ok=False)
    os.chmod(args.output, 0o700)
    environment = {'baseline_expected': BASELINE, 'head': subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip(),
        'harness_sha256': sha256(Path(__file__).read_bytes()).hexdigest(), 'mode': 'offline-single-worker-shared-host', 'os': platform.platform(), 'cpu': platform.processor(),
        'logical_cpus': os.cpu_count(), 'machine': platform.machine(), 'load_average_at_start': os.getloadavg(), 'python': sys.version, 'sqlite': sqlite3.sqlite_version,
        'memory_bytes': os.sysconf('SC_PAGE_SIZE')*os.sysconf('SC_PHYS_PAGES'),
        'timezone': time.tzname, 'wall_clock_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'clock': vars(time.get_clock_info('perf_counter')), 'workers': 1, 'servers': 0, 'llm_calls': 0, 'embedding_calls': 0,
        'budgets_seconds': BUDGET, 'budget_basis': '30s worker sleep; provisional allocation, observe=12s/4 jobs=3s per invocation; not production-approved SLA', 'warmup': 'one complete preconditioning drain per case; new then deletes news/facts/jobs; process and OS cache remain warm',
        'repetitions': args.repetitions, 'scales': [1,3,10], 'source': 'snapshot' if args.snapshot else 'synthetic_supported' if args.supported_synthetic else 'synthetic_no_prices',
        'knowledge_hashes': {name: digest(module.KNOWLEDGE) for name,module in [('business',business_ontology),('relations',relations),('supply',supply)]},
        'registered_securities': len(business_ontology.KNOWLEDGE['securities']), 'snapshot_hashes': {}}
    (args.output/'environment.json').write_text(json.dumps(environment,ensure_ascii=False,indent=2))
    results = []
    with tempfile.TemporaryDirectory(prefix='eval26-', dir=args.output) as temp:
        root = Path(temp)
        if args.snapshot:
            for name in ('news','market'):
                source_path=(args.snapshot/(name+'.sqlite3')).resolve()
                source=sqlite3.connect(source_path.as_uri()+'?mode=ro',uri=True)
                destination=sqlite3.connect(root/(name+'.sqlite3'))
                try: source.backup(destination)
                finally: source.close(); destination.close()
                environment['snapshot_hashes'][name]=sha256((root/(name+'.sqlite3')).read_bytes()).hexdigest()
            with patch.object(archive,'PATH',root/'news.sqlite3'):
                articles=archive.browse(limit=None)['articles']
        else:
            articles=supported_articles(args.base_count) if args.supported_synthetic else synthetic(args.base_count)
            if args.supported_synthetic:
                environment['supported_fixture']=seed_supported_market(root/'market.sqlite3')
        if not articles:
            raise ValueError('empty input is not a processing evaluation')
        environment['input_articles']=len(articles);environment['input_fingerprint']=digest(articles)
        for scale in (1,3,10):
            scaled=supported_articles(args.base_count*scale) if args.supported_synthetic else expand(articles,scale)
            for scenario in ('new','repeat','correction','rules'):
                for cache in ('on','off'):
                    for repetition in range(args.repetitions):
                        for instrument in (True,False):
                            directory=root/f'{scale}-{scenario}-{cache}-{repetition}-{instrument}';directory.mkdir()
                            if args.snapshot or args.supported_synthetic:
                                source=sqlite3.connect(root/'market.sqlite3');destination=sqlite3.connect(directory/'market.sqlite3')
                                try: source.backup(destination)
                                finally: source.close();destination.close()
                            result=replay(directory,scaled,scenario,cache,instrument,args.supported_synthetic)
                            results.append({'scale':scale,'repetition':repetition,'input_fingerprint':digest(scaled),**result})
                            with (args.output/'measurements.jsonl').open('a') as stream: stream.write(json.dumps(results[-1],ensure_ascii=False)+'\n')
                            if args.supported_synthetic: time.sleep(.25)  # Share CPU with the concurrent issue #27 run; outside measured intervals.
        if args.profile:
            directory=root/'profile';directory.mkdir()
            if args.snapshot or args.supported_synthetic:
                source=sqlite3.connect(root/'market.sqlite3');destination=sqlite3.connect(directory/'market.sqlite3')
                try: source.backup(destination)
                finally: source.close();destination.close()
            profiler=cProfile.Profile();profiler.runcall(replay,directory,articles,'new','on',True,args.supported_synthetic)
            profiler.dump_stats(str(args.output/'processing.prof'))
    environment['max_rss_bytes_process_lifetime']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024)
    (args.output/'environment.json').write_text(json.dumps(environment,ensure_ascii=False,indent=2))
    invalid=[r for r in results if r['failures'] or r['counts_after']['states'].get('error', 0) or any(v is False for v in r['checks'].values())]
    groups = []
    for scale in (1,3,10):
        for scenario in ('new','repeat','correction','rules'):
            for cache in ('on','off'):
                for instrument in (True,False):
                    rows = [r for r in results if (r['scale'],r['scenario'],r['cache'],r['instrumented']) == (scale,scenario,cache,instrument)]
                    groups.append({'scale':scale,'scenario':scenario,'cache':cache,'instrumented':instrument,
                        'elapsed_seconds':distribution([r['elapsed_seconds'] for r in rows]),
                        'cpu_seconds':distribution([r['cpu_seconds'] for r in rows]),
                        'cycle_budget': 'met' if all(r['cycle_budget']=='met' for r in rows) else 'unmet'})
    summary={'groups':groups,'cases':len(results),'failed_cases':len(invalid),'performance_goal':'unverified',
        'limitations':['No operational arrival trace or full listed catalogue; no long-term stability claim.',
            'Scales 3/10 are synthetic expansions; snapshot prices/securities do not scale.',
            'No synthetic price observations are treated as real successful calculations.',
            'Cache off clears worker fingerprints only; OS page cache is uncontrolled; no process-memory cache exists in this path.',
            'SQL time includes execution and potential lock wait; lock wait is not independently observable.',
            'Stage times inclusive; native cache-on cycle repeats omit wrappers, SQL trace and queue instrumentation. Total drain still includes between-cycle sampling; cache-off includes invalidation treatment cost.',
            'Single worker on shared host; operational DB contention, external latency, price corrections and semantic relation changes unverified.',
            'Default replay is title-only; supported-synthetic adds generated bodies/prices; real archived bodies/raw portal parsing are not replayed.',
            'rules case changes relation fingerprint only; it tests invalidation, not changed relation correctness.',
            'Finite burst queue drain is not sustained normal arrival throughput; waiting/unsupported are not calculation successes.']}
    (args.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in summary.items() if k != 'groups'},ensure_ascii=False))
    return 1 if invalid else 0


if __name__ == '__main__':
    raise SystemExit(main())
