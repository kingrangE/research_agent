"""Record a no-network workload plan and preflight evidence for issue #27."""

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
BASELINE = 'f7b9190c5bba1166cba2166d4361f2cb0712ed86'


def command(*args):
    result = subprocess.run(args, text=True, capture_output=True)
    return {'exit_code': result.returncode, 'stdout': result.stdout.strip()}


def fingerprint(path):
    # Stream large private DB copies without loading them into memory.
    digest = sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def expectation(users, seconds):
    """Exact planned count for whole 30-second cycles; no observed throughput."""
    if users < 1 or users > 10000 or users % 100 or seconds < 30 or seconds % 30:
        raise ValueError('use 100-session multiples and whole 30-second cycles')
    counts = {'dashboard': users * seconds // 5,
              'market': users * 60 // 100 * seconds // 5,
              'feed': users * 25 // 100 * seconds // 5,
              'timeline': users * 15 // 100 * seconds // 5,
              'quotes': users * seconds // 10,
              'detail': users * 15 // 100 * seconds // 30}
    return {'configured_sessions': users, 'seconds': seconds, 'expected_requests': sum(counts.values()),
            'expected_endpoint_requests': counts, 'expected_rps': sum(counts.values()) / seconds}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--input', action='append', type=Path, default=[], help='private immutable input file to fingerprint; repeat per DB/catalogue/rules/manifest/trace')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('refusing to overwrite an existing preflight record')
    head = command('git', '-C', str(ROOT), 'rev-parse', 'HEAD')['stdout']
    memory = command('sysctl', '-n', 'hw.memsize') if platform.system() == 'Darwin' else command('getconf', 'PHYS_PAGES')
    if platform.system() != 'Darwin' and memory['exit_code'] == 0:
        memory['stdout'] = str(int(memory['stdout']) * os.sysconf('SC_PAGE_SIZE'))
    result = {
        'version': 'active-sessions-v1', 'issue': 27, 'mode': 'plan-only-no-http',
        'baseline_required': BASELINE, 'head': head, 'baseline_matches': head == BASELINE,
        'branch': command('git', '-C', str(ROOT), 'branch', '--show-current')['stdout'],
        'worktree': str(ROOT), 'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
        'clock': {'scheduling': 'k6 monotonic executor; session cadence Date.now wall clock',
                  'python_monotonic': time.get_clock_info('monotonic').implementation,
                  'timezone': list(time.tzname), 'TZ': os.environ.get('TZ'), 'sync_offset_ms': None},
        'hardware': {'os': platform.platform(), 'machine': platform.machine(),
                     'logical_cpus': os.cpu_count(), 'physical_memory_bytes': memory,
                     'python': platform.python_version(), 'node': command('node', '--version'),
                     'k6': command('k6', 'version') if shutil.which('k6') else None},
        'workload_sha256': fingerprint(ROOT / 'scripts/load_active_sessions.js'),
        'ui_sha256': fingerprint(ROOT / 'web/app.js'), 'seed': 27,
        'budgets_fixed_before_run': {'normal_endpoint_p95_ms': 1000, 'normal_endpoint_p99_ms': 3000,
                                    'failure_per_attempt': .001, 'recovery_seconds': 60,
                                    'lost_articles_corrections_wrong_symbols_false_normal_values': 0},
        'inputs': [{'path': str(p.resolve()), 'bytes': p.stat().st_size, 'sha256': fingerprint(p)} for p in args.input],
        'stages': [expectation(n, 600) for n in [100, 1000, 5000]] + [expectation(10000, 1800), expectation(10000, 7200)],
        'configuration': {'target': None, 'generator': 'this shared host; no HTTP run',
                          'server_workers': None, 'writer_workers': None, 'cache': 'not established',
                          'full_listing_count': None, 'article_count': None, 'price_count': None,
                          'relationship_rules': None, 'browser_trace': None},
        'observed': {'active_sessions': None, 'attempted_requests': 0, 'completed_requests': 0,
                     'rps': None, 'p50_ms': None, 'p95_ms': None, 'p99_ms': None,
                     'failure_rate': None, 'missed_expected_requests': None, 'recovery_seconds': None},
        'goal_10000': 'unverified', 'llm_calls': 0, 'embedding_calls': 0,
        'limitations': ['Plan counts are not attempted or missed requests: no load was scheduled.',
                        'Provisional request mix from source; browser trace calibration absent.',
                        'No isolated generator/target, recorded input copies, writers or telemetry supplied.',
                        'Concurrent workers share the host; no isolated performance claim.']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'output': str(args.output), 'goal_10000': result['goal_10000'], 'baseline_matches': result['baseline_matches']}))


if __name__ == '__main__':
    main()
