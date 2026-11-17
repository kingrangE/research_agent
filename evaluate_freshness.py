"""Issue #25: evaluate explicit version traces without inventing missing timestamps."""

from collections import Counter
from datetime import datetime
from hashlib import sha256
import argparse
import json
import math
from pathlib import Path

STAGES = ('published_at', 'portal_display_at', 'observed_at', 'stored_at',
          'processed_at', 'api_at', 'browser_at', 'traded_at', 'browser_checked_at')
PAIRS = {'published_to_display': ('published_at', 'browser_at'),
         'portal_to_observed': ('portal_display_at', 'observed_at'),
         'observed_to_stored': ('observed_at', 'stored_at'),
         'stored_to_processed': ('stored_at', 'processed_at'),
         'processed_to_api': ('processed_at', 'api_at'),
         'api_to_display': ('api_at', 'browser_at'),
         'observed_to_display': ('observed_at', 'browser_at'),
         'observed_to_api': ('observed_at', 'api_at'),
         'trade_to_observed': ('traded_at', 'observed_at'),
         'trade_to_display': ('traded_at', 'browser_at')}
STATUSES = {'ok', 'delayed', 'failed', 'missing', 'unsupported', 'closed', 'no_trade'}


def moment(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError('timestamp must be an ISO string or null')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timestamp requires timezone')
    return parsed.timestamp()


def distribution(values, total):
    ordered = sorted(values)
    return {'samples': len(values), 'denominator': total,
            **{f'p{p}_seconds': ordered[math.ceil(p / 100 * len(ordered)) - 1] if ordered else None
               for p in (50, 95, 99)}}


def ratio(count, total):
    return {'count': count, 'denominator': total, 'ratio': count / total if total else None}


def summarize(rows, cutoff):
    parsed = [{k: moment(row.get(k)) for k in STAGES} for row in rows]
    stages = {}
    for name, (start, end) in PAIRS.items():
        values = [p[end] - p[start] for p in parsed
                  if p[start] is not None and p[end] is not None
                  and p[start] <= p[end] <= cutoff]
        stages[name] = distribution(values, len(rows))
        stages[name]['negative'] = sum(p[start] is not None and p[end] is not None and p[end] < p[start] for p in parsed)
    # Both processing and API availability must precede a measured display.
    ready = [max(p['processed_at'], p['api_at']) if p['processed_at'] is not None and p['api_at'] is not None else None for p in parsed]
    eligible = [(r, p, at) for r, p, at in zip(rows, parsed, ready)
                if r['kind'] in ('article', 'correction') and r['status'] == 'ok']
    values = [p['browser_at'] - at for _, p, at in eligible
              if at is not None and p['browser_at'] is not None and at <= p['browser_at'] <= cutoff]
    budget = distribution(values, len(eligible))
    budget['negative'] = sum(at is not None and p['browser_at'] is not None and p['browser_at'] < at for _, p, at in eligible)
    budget['target_p95_seconds'] = 10
    budget['status'] = ('unmet' if values and budget['p95_seconds'] > 10 else
                        'unverified' if not eligible or len(values) != len(eligible) else 'met')
    collected = [p for r, p in zip(rows, parsed) if p['stored_at'] is not None and p['stored_at'] <= cutoff]
    statuses = Counter(r['status'] for r in rows)
    displayed = sum(p['browser_at'] is not None and p['stored_at'] <= p['browser_at'] <= cutoff for p in collected)
    unknown = sum(not any(p[k] is not None and p['stored_at'] <= p[k] <= cutoff
                          for k in ('browser_at', 'browser_checked_at')) for p in collected)
    display = {**ratio(displayed, len(collected)), 'unknown': unknown,
               'confirmed_lower_bound': displayed / len(collected) if collected else None}
    if unknown:
        display['ratio'] = None
    return {'rows': len(rows), 'status': {s: ratio(statuses[s], len(rows)) for s in sorted(STATUSES)},
            'timestamp_unknown': {k: ratio(sum(p[k] is None for p in parsed), len(rows)) for k in STAGES},
            'future_timestamps': {k: sum(p[k] is not None and p[k] > cutoff for p in parsed) for k in STAGES},
            'latency': stages, 'ready_to_display': budget,
            'trade_age_at_cutoff': distribution([cutoff - p['traded_at'] for p in parsed if p['traded_at'] is not None and p['traded_at'] <= cutoff], len(rows)),
            'collected_versions_displayed': display}


def evaluate(data):
    if data.get('mode') not in ('synthetic_replay', 'real_observation'):
        raise ValueError('mode must distinguish synthetic replay from real observation')
    cutoff = moment(data['as_of'])
    if cutoff is None:
        raise ValueError('as_of required')
    rows = data['traces']; keys = set()
    for row in rows:
        key = (row['kind'], row['id'], row['version'], row['market'])
        if key in keys or row['kind'] not in ('article', 'correction', 'quote') or row['market'] not in ('KR', 'US') or row['status'] not in STATUSES:
            raise ValueError('duplicate version or invalid kind/market/status')
        if not row['id'] or not row['version']:
            raise ValueError('explicit id and source version required')
        if row['kind'] == 'quote' and row.get('instrument') not in ('stock', 'benchmark_etf'):
            raise ValueError('quote instrument required')
        keys.add(key)
    result = {'version': 'freshness-evaluation-v1', 'mode': data['mode'], 'as_of': data['as_of'],
              'input_sha256': sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
              'all': summarize(rows, cutoff), 'groups': {}}
    for market in ('KR', 'US'):
        for kind in ('article', 'correction', 'quote'):
            subset = [r for r in rows if r['market'] == market and r['kind'] == kind]
            result['groups'][market + '/' + kind] = summarize(subset, cutoff)
    result['time_domains'] = {domain: summarize([r for r in rows if r.get('time_domain', 'recorded') == domain], cutoff)
                              for domain in sorted({r.get('time_domain', 'recorded') for r in rows})}
    inventory = data.get('tracked_status', []); seen = set()
    for row in inventory:
        key = (row['market'], row['code'], row['at'])
        if key in seen or row['market'] not in ('KR', 'US') or row['status'] not in STATUSES or row['instrument'] not in ('stock', 'benchmark_etf'):
            raise ValueError('invalid or duplicate tracked security observation')
        moment(row['at']); seen.add(key)
    result['tracked_status'] = {}
    for market in ('KR', 'US'):
        for instrument in ('stock', 'benchmark_etf'):
            subset = [r for r in inventory if r['market'] == market and r['instrument'] == instrument]
            counts = Counter(r['status'] for r in subset)
            result['tracked_status'][market + '/' + instrument] = {s: ratio(counts[s], len(subset)) for s in sorted(STATUSES)}
    minutes = data.get('five_minute', []); seen = set()
    for row in minutes:
        key = (row['market'], row['code'], row['at'])
        if key in seen or row['market'] not in ('KR', 'US') or row['instrument'] not in ('stock', 'benchmark_etf') or moment(row['at']) % 60:
            raise ValueError('five-minute denominator requires unique UTC minute / security')
        if row['status'] not in ('ok', 'pending', 'stale', 'outside_session', 'session_unverified', 'observation_gap', 'large_move_unverified', 'unsupported'):
            raise ValueError('unknown five-minute outcome')
        seen.add(key)
    result['five_minute'] = {}
    for market in ('KR', 'US'):
        for instrument in ('stock', 'benchmark_etf'):
            subset = [r for r in minutes if r['market'] == market and r['instrument'] == instrument]
            counts = Counter(r['status'] for r in subset)
            result['five_minute'][market + '/' + instrument] = {
                'available': ratio(counts['ok'], len(subset)),
                'reasons': {s: ratio(n, len(subset)) for s, n in sorted(counts.items())}}
    expected = data.get('independent_source_targets')
    if expected is None:
        result['source_omission'] = {'status': 'unverified', 'count': None, 'denominator': None, 'ratio': None}
    else:
        targets = {(r['kind'], r['id'], r['version'], r['market']) for r in expected}
        if len(targets) != len(expected):
            raise ValueError('duplicate independent source target')
        collected = {(r['kind'], r['id'], r['version'], r['market']) for r in rows
                     if r.get('stored_at') is not None and moment(r['stored_at']) <= cutoff}
        result['source_omission'] = {**ratio(len(targets - collected), len(targets)),
                                     'status': 'measured_in_declared_scope' if targets else 'unverified',
                                     'scope': data.get('source_scope'), 'complete_source_recall_claim': False}
    violations = sum(r.get('published_at_inferred', False) or
                     (r['status'] != 'ok' and r.get('reported_change_percent') == 0) for r in rows)
    minute_violations = sum(r['status'] != 'ok' and r.get('reported_change_percent') == 0 for r in minutes)
    violations += minute_violations
    result['false_normal_or_publication_fill'] = {'count': violations, 'denominator': len(rows) + len(minutes),
                                                 'status': 'unmet' if violations else 'no_violation_in_supplied_traces_only'}
    result['real_market_coverage'] = {}
    for market in ('KR', 'US'):
        coverage = [r for r in data.get('observation_windows', []) if r['market'] == market and r.get('normal_open_day_verified') and r['date'] <= data['as_of'][:10]]
        dates = {r['date'] for r in coverage if r.get('phase') in ('opening', 'intraday', 'closing')}
        complete = [day for day in dates if {'opening', 'intraday', 'closing', 'outside'} <= {r['phase'] for r in coverage if r['date'] == day}]
        result['real_market_coverage'][market] = {'complete_days': len(complete) if data['mode'] == 'real_observation' else 0,
                                                 'status': 'met' if data['mode'] == 'real_observation' and len(complete) >= 3 else 'unverified'}
    result['release_approved'] = False
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace', type=Path)
    args = parser.parse_args()
    print(json.dumps(evaluate(json.loads(args.trace.read_text())), ensure_ascii=False, indent=2))
