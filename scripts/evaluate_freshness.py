"""Isolated synthetic replay of issue #25; no real supplier or browser measurements."""

from contextlib import ExitStack
from datetime import datetime, timezone
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path
import platform
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from unittest.mock import patch
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import archive
import business_ontology
import evaluate_freshness as evaluation
import event_facts
import market_history
import news_ingestion
import price_tracking
import server
import stocks
from llm_provider import Provider

EXPECTED_HEAD = 'f7b9190c5bba1166cba2166d4361f2cb0712ed86'
SECURITIES = [('KR', '018260', 'stock'), ('KR', '069500', 'benchmark_etf'),
              ('US', 'NVDA.O', 'stock'), ('US', 'SPY', 'benchmark_etf')]
INPUTS = [
    {'id': 'replay-25', 'title': '삼성SDS 데이터센터 투자 계획', 'published_at': '2026-11-16T00:00:00Z', 'timestamp_basis': 'portal_display'},
    {'id': 'replay-25', 'title': '삼성SDS 데이터센터 투자 취소', 'published_at': '2026-11-16T00:00:00Z', 'timestamp_basis': 'portal_display'},
    {'id': 'late-25', 'title': '엔비디아 데이터센터 투자 계획', 'published_at': '2026-11-13T14:30:00Z'},
    {'id': 'unknown-25', 'title': '공개 시각 미확인 자료', 'published_at': None},
]


def stamp():
    return datetime.now(timezone.utc).isoformat()


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def command(*args):
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def run(directory):
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    os.chmod(directory, 0o700)
    hardware = {'os': platform.platform(), 'machine': platform.machine(), 'logical_cpus': os.cpu_count(),
                'python': sys.version, 'cpu': platform.processor()}
    if sys.platform == 'darwin':
        hardware.update(cpu=command('sysctl', '-n', 'machdep.cpu.brand_string'), memory_bytes=int(command('sysctl', '-n', 'hw.memsize')))
    else:
        hardware['memory_bytes'] = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')
    files = ['archive.py', 'event_facts.py', 'data_product.py', 'price_tracking.py', 'server.py',
             'stocks.py', 'web/app.js', 'data/business_ontology.json', 'data/relations.json',
             'evaluate_freshness.py', 'scripts/evaluate_freshness.py']
    manifest = {'issue': 25, 'baseline_head': command('git', 'rev-parse', 'HEAD'), 'expected_head': EXPECTED_HEAD,
                'branch': command('git', 'branch', '--show-current'), 'worktree': str(ROOT), 'frozen_at': stamp(),
                'mode': 'synthetic_replay', 'hardware': hardware, 'timezone': time.tzname,
                'clock': 'host UTC wall clock for local stages; fixed UTC synthetic quote clock; NTP error unmeasured',
                'server_workers': 'one local ThreadingHTTPServer; sequential client; no collectors started',
                'cache': 'new empty private SQLite files; process imports warm; OS cache uncontrolled',
                'contention': 'other Orca workers on same host; not isolated performance',
                'initial_db_counts': {'articles': 0, 'quotes': 0, 'facts': 0},
                'production_db_copy': None, 'catalogue_mode': 'fixed 16 security ontology; not full exchange listings',
                'catalogue_sha256': sha256(json.dumps(business_ontology.KNOWLEDGE['securities'], sort_keys=True).encode()).hexdigest(),
                'catalogue_count': len(business_ontology.KNOWLEDGE['securities']),
                'input_articles': len(INPUTS), 'quote_securities': len(SECURITIES),
                'input_sha256': sha256(json.dumps([INPUTS, SECURITIES], sort_keys=True).encode()).hexdigest(),
                'quote_schedule': {'session_date': '2026-11-16', 'sample_minutes': [m for m in range(1, 13) if m != 7],
                                   'gap_minute': 7, 'poll_minutes': list(range(13)) + [15, -1],
                                   'price': '100 + minute / 10; recovery 100', 'session_boundaries': 'KR 00:00-06:30Z; US 14:30-21:00Z (synthetic)'},
                'file_sha256': {f: sha256((ROOT / f).read_bytes()).hexdigest() for f in files},
                'budgets': {'ready_to_display_p95_seconds': 10,
                            'KR': {'external_quote_age_budget_seconds': None, 'status': 'unverified_no_live_observation'},
                            'US': {'external_quote_age_budget_seconds': None, 'status': 'unverified_no_live_observation'},
                            'browser_poll_seconds': 5, 'quote_cache_seconds': stocks.QUOTE_TTL,
                            'quote_collector_seconds': 10, 'news_collector_seconds': 10,
                            'rss_collector_seconds': server.INTERVAL, 'listing_failure_retry_seconds': 300}}
    write(directory / 'manifest-before.json', manifest)
    calls = {'external_network': 0, 'llm': 0, 'embedding': 0}
    def blocked(*args, **kwargs):
        calls['llm'] += 1
        raise AssertionError('LLM disabled in freshness evaluation')
    original_connect = socket.socket.connect
    def connect(sock, address):
        if not isinstance(address, tuple) or address[0] != '127.0.0.1':
            calls['external_network'] += 1
            raise AssertionError('external network disabled')
        return original_connect(sock, address)
    traces = []; minutes = []; inventory = []; checks = {}
    with ExitStack() as stack:
        for module, name in ((archive, 'news'), (event_facts, 'facts'), (price_tracking, 'quotes'), (market_history, 'market')):
            stack.enter_context(patch.object(module, 'PATH', directory / (name + '.sqlite3')))
        stack.enter_context(patch.dict(os.environ, {'PRODUCT_MODE': 'data', 'LLM_ENABLED': '0'}))
        stack.enter_context(patch.object(Provider, 'request', blocked))
        stack.enter_context(patch.object(socket.socket, 'connect', connect))
        catalogue = {s['code']: {**s, 'products': ''} for s in business_ontology.KNOWLEDGE['securities']}
        matcher, names = stocks.compile_names(catalogue)
        stack.enter_context(patch.multiple(stocks, CATALOGUE=catalogue, NAME_MATCHER=matcher, NAME_CODES=names))
        class Handler(server.Handler):
            def log_message(self, *args):
                pass
        http = server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True); thread.start()
        def request(path):
            with urlopen('http://127.0.0.1:' + str(http.server_port) + path, timeout=10) as response:
                return json.load(response)
        try:
            for index, source in enumerate(INPUTS):
                article = {**source, 'source_id': 'synthetic', 'source': 'synthetic replay', 'kind': 'news',
                           'url': 'https://example.invalid/freshness/' + source['id']}
                observed = stamp(); archive.store([article]); stored = stamp()
                version = archive.provenance([article['url']])[article['url']]['article_version']
                event_facts.ingest(); processed = stamp()
                payload = request('/api/articles?limit=30')
                found = next(a for a in payload['articles'] if a['id'] == article['id'])
                assert found['title'] == article['title'] and found['evidence']['article_version'] == version
                api = stamp()
                assert found['evidence']['published_at'] == (source['published_at'] if source.get('timestamp_basis') != 'portal_display' else None)
                traces.append({'kind': 'correction' if index == 1 else 'article', 'id': article['id'], 'version': version,
                               'market': 'US' if index == 2 else 'KR', 'status': 'ok', 'time_domain': 'host_stage_elapsed', 'observed_at': observed,
                               'stored_at': stored, 'processed_at': processed, 'api_at': api, 'browser_at': None,
                               'published_at': found['evidence']['published_at'], 'portal_display_at': found['evidence']['portal_display_at']})
            checks['correction_new_version'] = traces[0]['version'] != traces[1]['version']
            checks['unknown_publication_preserved'] = traces[-1]['published_at'] is None
            day = '2026-11-16'
            with patch.object(news_ingestion, 'fetch_page', side_effect=TimeoutError('synthetic failure')):
                try:
                    news_ingestion.collect_day(day)
                except TimeoutError:
                    pass
                else:
                    raise AssertionError('supplier failure swallowed')
            checks['supplier_failure_explicit'] = news_ingestion.status(day)['failures'] == 1
            checks['failure_backoff_preserved'] = news_ingestion.collect_day(day)['status'] == 'backoff'
            with archive.db() as connection:
                connection.execute('UPDATE news_collection SET retry_after=0 WHERE day=?', (day,))
            with patch.object(news_ingestion, 'fetch_page', return_value=[]):
                checks['supplier_recovery'] = news_ingestion.collect_day(day)['status'] == 'complete'
            for market, code, instrument in SECURITIES:
                start = '2026-11-16T00:00:00Z' if market == 'KR' else '2026-11-16T14:30:00Z'
                end = '2026-11-16T06:30:00Z' if market == 'KR' else '2026-11-16T21:00:00Z'
                session = {'regularMarket': {'startTime': start, 'endTime': end}}
                if market == 'KR':
                    session = {'integrated': session}
                base = evaluation.moment(start)
                def at(offset):
                    return datetime.fromtimestamp(base + offset, timezone.utc).isoformat()
                def quote(offset, price=100):
                    return {'code': code, 'price': price, 'currency': 'KRW' if market == 'KR' else 'USD',
                            'status': 'ok', 'source': 'Npay 증권', 'traded_at': at(offset), 'fetched_at': at(offset), 'market_status': 'OPEN'}
                # Deliberate gap at minute 7; comparison starts empty, becomes valid, then gaps/stales.
                for minute in range(13):
                    if 1 <= minute <= 12 and minute != 7:
                        q = quote(minute * 60, 100 + minute / 10)
                        assert price_tracking.record(code, q, now=at(minute * 60))
                        traces.append({'kind': 'quote', 'id': code, 'version': q['traded_at'], 'market': market,
                                       'instrument': instrument, 'status': 'ok', 'time_domain': 'controlled_quote_clock', 'traded_at': q['traded_at'],
                                       'observed_at': at(minute * 60), 'stored_at': at(minute * 60), 'browser_at': None})
                    with patch.object(market_history, 'calendar_snapshot', return_value={day: session}):
                        result = price_tracking.recent(code, now=at(minute * 60))
                    minutes.append({'market': market, 'instrument': instrument, 'code': code, 'at': at(minute * 60),
                                    'status': result['status'], 'reported_change_percent': result['change_percent']})
                with patch.object(market_history, 'calendar_snapshot', return_value={day: session}):
                    for offset in (15 * 60, -60):
                        result = price_tracking.recent(code, now=at(offset))
                        minutes.append({'market': market, 'instrument': instrument, 'code': code, 'at': at(offset),
                                        'status': result['status'], 'reported_change_percent': result['change_percent']})
                price_tracking.register({'id': code}, [{'code': code}], now=at(12 * 60))
                assert not price_tracking.record(code, {}, now=at(12 * 60))
                before = price_tracking.snapshot(code, now=at(12 * 60))['stocks'][0]
                inventory.append({'market': market, 'instrument': instrument, 'code': code, 'at': at(12 * 60), 'status': 'failed'})
                checks[code + '_failure_preserves_last_price'] = before['collection_status'] == 'error' and before['latest'] is not None
                # Reopening SQLite connections verifies persisted state, not a process/container restart.
                after = price_tracking.snapshot(code, now=at(12 * 60))['stocks'][0]
                checks[code + '_reopen_preserves_state'] = before == after
                assert price_tracking.record(code, quote(13 * 60), now=at(13 * 60))
                checks[code + '_quote_recovery'] = price_tracking.snapshot(code, now=at(13 * 60))['stocks'][0]['collection_status'] == 'ok'
                inventory.append({'market': market, 'instrument': instrument, 'code': code, 'at': at(13 * 60), 'status': 'ok'})
                inventory.append({'market': market, 'instrument': instrument, 'code': code, 'at': at(16 * 60), 'status': 'delayed'})
                checks[code + '_stale_not_normal'] = price_tracking.snapshot(code, now=at(16 * 60))['stocks'][0]['stale']
            # A cold catalogue filters stock codes before any quote request, even if tracking persisted.
            with patch.object(stocks, 'CATALOGUE', {}), patch.object(stocks, 'get_quotes', return_value={}) as fetch:
                price_tracking.cycle()
                checks['cold_catalogue_excludes_stocks'] = all(c in stocks.MARKET_CODES for c in fetch.call_args.args[0]) if fetch.called else True
            with patch.object(stocks, 'get_quotes', return_value={}) as fetch:
                price_tracking.cycle()
                checks['catalogue_restore_resumes_stock_attempts'] = fetch.called and any(c not in stocks.MARKET_CODES for c in fetch.call_args.args[0])
        finally:
            http.shutdown(); http.server_close(); thread.join()
    with patch.object(price_tracking, 'PATH', directory / 'quotes.sqlite3'):
        write(directory / 'restart-expected-private.json', price_tracking.snapshot('018260', now='2026-11-16T00:13:00Z')['stocks'][0])
    # Fresh interpreter verifies local HTTP/SQLite recovery with an empty listing catalogue.
    probe = r"""
import json, os, socket, sys, threading
from llm_provider import Provider
from pathlib import Path
from urllib.request import urlopen
import archive, event_facts, price_tracking, market_history, server, stocks
counters = {'network': 0, 'llm': 0}
original_connect = socket.socket.connect
def connect(sock, address):
    if not isinstance(address, tuple) or address[0] != '127.0.0.1':
        counters['network'] += 1
        raise AssertionError('external network disabled in restart probe')
    return original_connect(sock, address)
def blocked(*args, **kwargs):
    counters['llm'] += 1
    raise AssertionError('LLM disabled in restart probe')
socket.socket.connect = connect
Provider.request = blocked
root = Path(sys.argv[1])
for module, name in ((archive,'news'), (event_facts,'facts'), (price_tracking,'quotes'), (market_history,'market')):
    module.PATH = root / (name + '.sqlite3')
os.environ.update(PRODUCT_MODE='data', LLM_ENABLED='0')
class Handler(server.Handler):
    def log_message(self, *args): pass
http = server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
thread = threading.Thread(target=http.serve_forever, daemon=True); thread.start()
try:
    with urlopen('http://127.0.0.1:' + str(http.server_port) + '/api/articles?limit=30', timeout=10) as response:
        articles = json.load(response)['articles']
    quote = price_tracking.snapshot('018260', now='2026-11-16T00:13:00Z')['stocks'][0]
    print(json.dumps({'fresh_process_http_correction_persisted': any(a['id']=='replay-25' and a['title'].endswith('취소') for a in articles),
                      'fresh_process_quote_persisted': quote == json.loads((root / 'restart-expected-private.json').read_text()),
                      'fresh_process_catalogue_empty': not stocks.CATALOGUE,
                      'fresh_process_no_external_calls': not any(counters.values())}))
finally:
    http.shutdown(); http.server_close(); thread.join()
"""
    checks.update(json.loads(subprocess.check_output([sys.executable, '-c', probe, str(directory)], cwd=ROOT, text=True)))
    data = {'mode': 'synthetic_replay' , 'as_of': stamp(), 'traces': traces, 'five_minute': minutes,
            'independent_source_targets': None, 'observation_windows': [],
            'tracked_status': inventory, 'clock_uncertainty_seconds': None, 'external_provider_delay_seconds': None}
    write(directory / 'traces-private.json', data)
    counts = {}
    for name, file, table in [('article_versions', 'news.sqlite3', 'items'), ('proposals', 'facts.sqlite3', 'proposals'), ('quote_versions', 'quotes.sqlite3', 'samples')]:
        connection = sqlite3.connect('file:' + str(directory / file) + '?mode=ro', uri=True)
        try:
            counts[name] = connection.execute('SELECT count(*) FROM ' + table).fetchone()[0]
        finally:
            connection.close()
    report = evaluation.evaluate(data)
    report.update(checks=checks, calls=calls, manifest='manifest-before.json',
                  scope='synthetic input through real SQLite/rule/loopback HTTP; quote timestamps controlled; browser absent',
                  db_counts=counts,
                  db_fingerprints={p.name: sha256(p.read_bytes()).hexdigest() for p in directory.glob('*.sqlite3')})
    write(directory / 'report.json', report)
    if not all(checks.values()) or any(calls.values()):
        raise AssertionError('replay checks failed; inspect report.json')
    print(json.dumps({'output': str(directory), 'checks': checks, 'calls': calls}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path, help='new private directory; refuses overwrite')
    run(parser.parse_args().output)
