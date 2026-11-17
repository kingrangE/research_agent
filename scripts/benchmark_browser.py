"""Issue #24: private SQLite snapshots, offline server and Chromium journey runner."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256, file_digest
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DATABASES = ['news.sqlite3', 'event_facts.sqlite3', 'market.sqlite3', 'data_jobs.sqlite3', 'price_tracking.sqlite3']


def serve(directory, clock):
    sys.path.insert(0, str(ROOT))
    os.environ.update(PRODUCT_MODE='data', LLM_ENABLED='0')
    import archive
    import data_worker
    import event_facts
    import market_history
    import price_tracking
    import server
    import stocks
    import socket
    from llm_provider import Provider

    for module, name in zip([archive, event_facts, market_history, data_worker, price_tracking], DATABASES):
        module.PATH = Path(directory) / name
    # No collectors; fail closed even if a read endpoint unexpectedly calls a provider.
    def blocked(*args, **kwargs):
        raise RuntimeError('External provider disabled in browser evaluation')
    Provider.request = blocked
    market_history.Toss.request = blocked
    stocks.fetch = blocked
    connect = socket.socket.connect
    def local_only(sock, address):
        if not isinstance(address, tuple) or address[0] not in ('127.0.0.1', '::1'):
            raise RuntimeError('External socket disabled in browser evaluation')
        return connect(sock, address)
    socket.socket.connect = local_only
    price_tracking.now_text = lambda: clock
    catalogue = {s['code']: {**s, 'products': ''} for s in server.business_ontology.KNOWLEDGE['securities']}
    stocks.CATALOGUE = catalogue
    stocks.NAME_MATCHER, stocks.NAME_CODES = stocks.compile_names(catalogue)
    stocks.CATALOGUE_STATUS.update(status='ready', count=len(catalogue))
    # Replay only recorded prices, preserving their original timestamps and stale state.
    def recorded_quotes(codes):
        result = {}
        with price_tracking.db() as db:
            for code in codes:
                row = db.execute('SELECT payload FROM samples WHERE code=? AND observed<=? ORDER BY observed DESC,id DESC LIMIT 1',
                                 (code, datetime.fromisoformat(clock).timestamp())).fetchone()
                result[code] = {**json.loads(row[0]), 'status': 'stale'} if row else {'code': code, 'status': 'pending'}
        return result
    stocks.get_quotes = recorded_quotes
    server.STATE.update(articles=archive.restore(), sources=[], collecting=False)
    class Handler(server.Handler):
        def log_message(self, *args):
            pass
    http = server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    print(json.dumps({'port': http.server_port}), flush=True)
    http.serve_forever()


def fingerprint(directory):
    result = {}
    for name in DATABASES:
        path = Path(directory) / name
        with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as db:
            tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            counts = {table: db.execute('SELECT count(*) FROM "' + table.replace('"', '""') + '"').fetchone()[0] for table in tables}
        with path.open('rb') as source:
            checksum = file_digest(source, 'sha256').hexdigest()
        result[name] = {'sha256': checksum, 'bytes': path.stat().st_size, 'rows': counts}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-container', help='Discover source volume/image; backup in a separate resource-limited helper with source mounted read-only')
    parser.add_argument('--snapshot', type=Path, help='Reuse an immutable snapshot containing manifest.json')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--as-of', help='Offset timestamp for price observation replay; default: current UTC fixed before measurement')
    parser.add_argument('--repetitions', type=int, default=100)
    parser.add_argument('--stock-only', action='store_true', help='Supplemental real news → stock chart journey; never merge with market/theme results')
    parser.add_argument('--playwright-module', required=False, default='playwright')
    parser.add_argument('--chrome', required=False)
    parser.add_argument('--serve', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    clock = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(timezone.utc)
    if clock.tzinfo is None:
        parser.error('--as-of must have an offset')
    if args.serve:
        serve(args.serve, clock.isoformat())
        return
    if args.repetitions < 1 or bool(args.snapshot) == bool(args.source_container):
        parser.error('choose exactly one --snapshot or --source-container, and repetitions >= 1')
    os.umask(0o077)
    parent = ROOT / '.data/validation/browser24'
    parent.mkdir(parents=True, exist_ok=True)
    output = args.output.resolve() if args.output else Path(tempfile.mkdtemp(prefix='run-', dir=parent))
    output.mkdir(parents=True, exist_ok=True)
    snapshot = output / 'snapshot'
    snapshot.mkdir()  # Refuse overwriting evidence from an earlier run.
    if args.snapshot:
        expected = json.loads((args.snapshot / 'manifest.json').read_text())
        if fingerprint(args.snapshot) != expected:
            raise ValueError('Snapshot fingerprint mismatch')
        for name in DATABASES:
            shutil.copyfile(args.snapshot / name, snapshot / name)
    else:
        source = json.loads(subprocess.check_output(['docker', 'inspect', args.source_container], text=True))[0]
        mount = next(m for m in source['Mounts'] if m['Destination'] == '/opt/research/.data' and m['Type'] == 'volume')
        code = "import sqlite3; names=" + repr(DATABASES) + ";\nfor name in names:\n s=sqlite3.connect('file:/source/'+name+'?mode=ro',uri=True); d=sqlite3.connect('/output/'+name); s.backup(d,pages=256); d.close(); s.close(); print(name,flush=True)"
        # Source is read-only; the short-lived helper owns all writes and has no network.
        subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--cpus', '1', '--memory', '256m',
                        '--mount', 'type=volume,src='+mount['Name']+',dst=/source,readonly',
                        '--mount', 'type=bind,src='+str(snapshot)+',dst=/output',
                        '--entrypoint', 'python3', source['Image'], '-c', code], check=True)
    manifest = fingerprint(snapshot)
    if args.snapshot and manifest != expected:
        raise ValueError('Copied snapshot differs from the fixed input')
    (snapshot / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    def git(*command):
        return subprocess.check_output(['git', *command], cwd=ROOT, text=True).strip()
    hardware = {'os': platform.platform(), 'cpu': platform.processor(), 'logical_cpus': os.cpu_count(), 'python': sys.version}
    if sys.platform == 'darwin':
        for key in ('hw.memsize', 'machdep.cpu.brand_string'):
            hardware[key] = subprocess.check_output(['sysctl', '-n', key], text=True).strip()
    metadata = {'issue': 24, 'baseline': git('rev-parse', 'HEAD'), 'branch': git('branch', '--show-current'),
                'expected_start_head': 'f7b9190c5bba1166cba2166d4361f2cb0712ed86',
                'dirty': bool(git('status', '--porcelain')), 'worktree': str(ROOT), 'as_of': clock.isoformat(),
                'started_at': datetime.now(timezone.utc).isoformat(), 'timezone': 'Asia/Seoul', 'hardware': hardware,
                'mode': 'data; recorded SQLite observations; no collectors; external sockets/providers blocked',
                'source': args.source_container or str(args.snapshot), 'snapshot': manifest,
                'rules': {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest() for p in [ROOT/'data/business_ontology.json', ROOT/'data/relations.json']},
                'code_hashes': {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest() for p in [*ROOT.glob('*.py'), *sorted((ROOT/'web').glob('*')), Path(__file__).resolve(), ROOT/'scripts/benchmark_browser.mjs'] if p.is_file()},
                'clock_policy': 'Recorded price as-of fixed; browser wall clock live, duration clock monotonic; no clock synchronization claim',
                'snapshot_policy': 'Consistent backup per SQLite database; five backups are sequential, not one cross-database transaction',
                'configuration': {'server_processes': 1, 'http_threads': 'ThreadingHTTPServer', 'collectors': 0, 'browser_journeys_in_parallel': 1,
                                  'shared_host': True, 'isolated_performance': False, 'llm_calls': 0, 'embedding_calls': 0, 'toss_calls': 0},
                'plan': {'scenario': 'supplemental_news_to_stock' if args.stock_only else 'market_journey',
                         'sample_unit': 'stock modal open/close; warm samples share one prepared browser context' if args.stock_only else 'complete journey in fresh browser context',
                         'warm_repetitions_per_device_network': args.repetitions, 'restart_repetitions_per_device_network': 1,
                         'warmup_journeys': 1, 'budgets_ms': {'api_p95': 1000, 'first_information_p95': 2500, 'theme_information_p95': 1000},
                         'memory_only_reset': 'unsupported: no independent reset hook; do not equate to restart',
                         'derived_cache_absent': 'unverified: stored derived results retained; do not delete observations',
                         'os_disk_cache': 'not cleared; never OS cold', 'timeout_ms': 20000}}
    (output/'preflight.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
    config = {'output': str(output), 'snapshot': str(snapshot), 'clock': clock.isoformat(), 'python': sys.executable,
              'serverScript': str(Path(__file__).resolve()), 'repetitions': args.repetitions, 'chrome': args.chrome,
              'playwrightModule': args.playwright_module, 'stockOnly': args.stock_only}
    (output/'config.json').write_text(json.dumps(config))
    result = subprocess.run(['node', str(ROOT/'scripts/benchmark_browser.mjs'), str(output/'config.json')], cwd=ROOT)
    print(json.dumps({'output': str(output), 'runner_exit_code': result.returncode}))
    sys.exit(result.returncode)


if __name__ == '__main__':
    main()
