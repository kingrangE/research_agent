"""Offline issue #28 evaluator. Inputs and row-level outputs belong outside git."""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import platform
import random
import subprocess
import time
from unittest.mock import patch

import stocks
import server

ROOT = Path(__file__).resolve().parent
RULE_FILES = ('server.py', 'stocks.py', 'relations.py', 'data/relations.json', 'web/app.js')
KINDS = {'direct', 'documented', 'theme'}
CRITICAL = {'wrong_security', 'future_evidence', 'denial_promoted'}


def fingerprint(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def rule_hashes():
    return {p: sha256((ROOT / p).read_bytes()).hexdigest() for p in RULE_FILES}


def environment():
    def command(*args):
        result = subprocess.run(args, text=True, capture_output=True, check=False)
        return {'exit_code': result.returncode, 'value': result.stdout.strip()}
    return {'head': command('git', 'rev-parse', 'HEAD'), 'branch': command('git', 'branch', '--show-current'),
            'worktree': str(ROOT), 'os': platform.platform(), 'python': platform.python_version(),
            'cpu_memory': command('sysctl', '-n', 'machdep.cpu.brand_string', 'hw.physicalcpu', 'hw.logicalcpu', 'hw.memsize') if platform.system() == 'Darwin' else command('uname', '-a'),
            'captured_at_utc': datetime.now(timezone.utc).isoformat(), 'local_timezone': time.tzname,
            'clock_sync': 'not independently verified', 'mode': 'offline single process; no server or DB',
            'cache': 'fresh Python process; OS file cache uncontrolled', 'resource_contention': 'four other host workers; not isolated performance',
            'llm_calls': 0, 'embedding_calls': 0, 'network_calls': 0, 'rules': rule_hashes(),
            'evaluator_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
            'budget': {'bootstrap_repeats': 1000, 'seed': 28, 'network_calls': 0}}


def instant(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('Evidence timestamps need timezone')
    return parsed


def kind(value):
    return 'direct' if value == 'body' else 'theme' if value in ('theme', 'value_chain', 'business') else value


def fraction(n, d):
    return {'numerator': n, 'denominator': d, 'value': n / d if d else None}


def quantile(values, p):
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * p
    lower = int(index)
    return ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * (index - lower)


def validate_inputs(manifest, articles, catalogue):
    if manifest['rules'] != rule_hashes():
        raise ValueError('Frozen rule fingerprints differ; do not retune on final labels')
    if manifest['articles_sha256'] != fingerprint(articles) or manifest['catalogue_sha256'] != fingerprint(catalogue):
        raise ValueError('Frozen input fingerprint mismatch')
    if any(stock['code'] != code for code, stock in catalogue.items()):
        raise ValueError('Catalogue code/key mismatch')
    if manifest['candidate_codes'] != sorted(catalogue):
        raise ValueError('Recall universe must equal frozen reviewed catalogue')
    if len({a['id'] for a in articles}) != len(articles):
        raise ValueError('Duplicate article ID')
    if not manifest['listing_archive_sha256'] or not manifest['relation_archives_sha256']:
        raise ValueError('Listing and public relation archives required')
    instant(manifest['frozen_at'])
    development = set(manifest['development_event_ids'])
    groups = defaultdict(set)
    for a in articles:
        instant(a['published_at'])
        if not manifest['final_start'] <= a['published_at'][:10] <= manifest['final_end'] or a['event_id'] in development:
            raise ValueError('Period/event leakage')
        if a['sample'] not in ('normal', 'challenge') or a['market'] not in ('KR', 'US'):
            raise ValueError('Unknown sampling stratum')
        groups[a['event_id']].add(a['sample'])
        if not a['source_url'].startswith(('https://', 'http://')) or not a['source_archive_sha256'] or not a['body']:
            raise ValueError('Frozen full article and provenance required')
    if any(len(values) != 1 for values in groups.values()):
        raise ValueError('An event cannot cross normal/challenge samples')
    if manifest['development_end'] >= manifest['final_start']:
        raise ValueError('Final period must follow development')
    actual = dict(Counter(f"{a['sample']}|{a['market']}|{a['theme']}" for a in articles))
    if actual != manifest['strata_counts']:
        raise ValueError('Preregistered strata counts differ')
    for field in ('primary_type', 'challenge_tag'):
        if dict(Counter(a[field] for a in articles)) != manifest[field + '_counts']:
            raise ValueError('Preregistered relation/challenge counts differ')


def predict(articles, catalogue):
    """Reuse the screen classification path with optional frozen preexisting readings."""
    matcher, names = stocks.compile_names(catalogue)
    rows = []
    with patch.multiple(stocks, CATALOGUE=catalogue, NAME_MATCHER=matcher, NAME_CODES=names):
        for a in articles:
            started = time.perf_counter()
            baseline = [{'code': m['code'], 'relation': 'direct', 'sources': []} for m in stocks.direct_mentions(a['title'])]
            current = server.classify({'id': a['id'], 'title': a['title'], 'url': a['source_url'],
                                       'published_at': a['published_at']}, now=instant(a['published_at']),
                                      reading=a.get('reading'))['related_stocks']
            rows.append({'id': a['id'], 'event_id': a['event_id'], 'sample': a['sample'], 'market': a['market'],
                         'theme': a['theme'], 'published_at': a['published_at'], 'source_url': a['source_url'],
                         'baseline': baseline, 'current': current, 'reading_available': bool(a.get('reading')), 'elapsed_ms': (time.perf_counter() - started) * 1000})
    return rows


def validate_gold(gold, articles, manifest):
    if set(gold) != {a['id'] for a in articles}:
        raise ValueError('Gold must explicitly cover every article, including undecidable')
    universe = set(manifest['candidate_codes'])
    for a in articles:
        g = gold[a['id']]
        if g['status'] not in ('reviewed', 'undecidable', 'hold') or not isinstance(g['complete'], bool):
            raise ValueError('Invalid gold review status')
        codes = [v['code'] for v in g['links']]
        if len(set(codes)) != len(codes) or not set(codes) <= universe or set(codes) & set(g['negative_codes']):
            raise ValueError('Gold securities outside universe or conflicting labels')
        if not set(g['negative_codes']) <= universe:
            raise ValueError('Negative labels outside universe')
        for link in g['links']:
            if link['type'] not in KINDS or not link['quote'] or link['quote'] not in a['title'] + '\n' + a['body']:
                raise ValueError('Gold type/evidence quote invalid')
            if instant(link['known_at']) > instant(a['published_at']) or not link['source_url'] or not link['source_archive_sha256']:
                raise ValueError('Future/missing gold evidence')
        for code, tags in g['critical_codes'].items():
            if code not in universe or not set(tags) <= CRITICAL:
                raise ValueError('Invalid adjudicated critical errors')


def decision_fingerprint(gold):
    return fingerprint({key: gold[key] for key in ('status', 'complete', 'links', 'negative_codes', 'critical_codes')})


def review_summary(gold):
    eligible = agreed = reconciled = 0
    for g in gold.values():
        reviews = g['reviews']
        independent = len(reviews) == 2 and len({r['reviewer'] for r in reviews}) == 2 and all(
            r['human'] is True and r['prediction_blind'] is True and r['record_sha256'] and r['reviewed_at'] and r['decision_sha256'] for r in reviews)
        if not independent:
            continue
        eligible += 1
        same = reviews[0]['decision_sha256'] == reviews[1]['decision_sha256']
        agreed += same
        final = decision_fingerprint(g)
        resolution = g.get('adjudication', {})
        reconciled += (same and reviews[0]['decision_sha256'] == final) or bool(
            resolution.get('record_sha256') and resolution.get('decision_sha256') == final)
    return {'two_human_blind_reviews': eligible, 'agreement': fraction(agreed, eligible),
            'resolved_articles': reconciled, 'kappa': None, 'kappa_reason': 'set-valued article labels; exact decision agreement reported'}


def score_rows(rows, gold, method, top=None):
    tp = fp = fn = unknown = recall_tp = total_gold = 0
    abstained = held = negative = false_alarm = evidence = predicted = critical_count = 0
    confusion = Counter()
    per_article = []
    for row in rows:
        g = gold[row['id']]
        links = row[method][:top] if top else row[method]
        labels = {v['code']: v['type'] for v in g['links']}
        codes = {v['code'] for v in links}
        if len(codes) != len(links):
            raise ValueError('Duplicate predicted security')
        evaluable = g['status'] == 'reviewed'
        valid = codes & labels.keys() if evaluable else set()
        wrong = (codes - labels.keys()) if evaluable and g['complete'] else codes & set(g['negative_codes']) if evaluable else set()
        missing = labels.keys() - codes if evaluable and g['complete'] else set()
        tp += len(valid); fp += len(wrong); fn += len(missing)
        unknown += len(codes - valid - wrong)
        if evaluable and g['complete']:
            recall_tp += len(valid); total_gold += len(labels)
        abstained += not codes
        held += not evaluable
        is_negative = evaluable and g['complete'] and not labels
        negative += is_negative; false_alarm += is_negative and bool(codes)
        predicted += len(links)
        critical_details = []
        for link in links:
            sources = link.get('sources', [])
            checked = bool(sources) and all(s.get('url', '').startswith(('https://', 'http://')) and s.get('published_on') and s['published_on'] <= row['published_at'][:10] for s in sources)
            evidence += checked
            tags = set(g['critical_codes'].get(link['code'], [])) if evaluable else set()
            if any((s.get('published_on') or '') > row['published_at'][:10] for s in sources):
                tags.add('future_evidence')
            critical_count += bool(tags)
            if tags:
                critical_details.append({'code': link['code'], 'tags': sorted(tags)})
            if link['code'] in valid:
                confusion[f"{labels[link['code']]}->{kind(link['relation'])}"] += 1
        precision = len(valid) / (len(valid) + len(wrong)) if valid or wrong else None
        recall = len(valid) / len(labels) if evaluable and g['complete'] and labels else None
        per_article.append({'id': row['id'], 'wrong': len(wrong), 'missing': len(missing) if evaluable and g['complete'] else None,
                            'wrong_codes': sorted(wrong), 'missing_codes': sorted(missing) if evaluable and g['complete'] else None,
                            'unknown_codes': sorted(codes - valid - wrong), 'critical': critical_details, 'precision': precision, 'recall': recall,
                            'f1': 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else 0 if precision == 0 and recall == 0 else None})
    p = fraction(tp, tp + fp); r = fraction(recall_tp, total_gold)
    def mean(field):
        values = [v[field] for v in per_article if v[field] is not None]
        return {'value': sum(values) / len(values) if values else None, 'articles': len(values)}
    return {'articles': len(rows), 'events': len({r['event_id'] for r in rows}), 'true_positive': tp, 'false_positive': fp,
            'false_negative': fn, 'unknown_predictions': unknown, 'predictions': predicted, 'precision': p, 'recall': r,
            'f1': 2 * p['value'] * r['value'] / (p['value'] + r['value']) if p['value'] is not None and r['value'] is not None and p['value'] + r['value'] else 0 if p['value'] == 0 and r['value'] == 0 else None,
            'macro': {f: mean(f) for f in ('precision', 'recall', 'f1')}, 'abstention': fraction(abstained, len(rows)),
            'hold_or_undecidable': fraction(held, len(rows)), 'gold_negative': fraction(negative, len(rows)),
            'gold_negative_false_alarm': fraction(false_alarm, negative), 'evidence_time_verifiable': fraction(evidence, predicted),
            'critical_predictions': critical_count, 'type_confusion': dict(confusion), 'per_article': per_article}


def bootstrap(rows, gold, method, repeats=1000, seed=28, top=None):
    events = defaultdict(list)
    for row in rows:
        events[row['event_id']].append(row)
    if len(events) < 2:
        return {'precision': None, 'recall': None, 'f1': None, 'replicates': repeats, 'events': len(events)}
    rng = random.Random(seed)
    values = defaultdict(list)
    keys = list(events)
    for _ in range(repeats):
        sample = [r for event in rng.choices(keys, k=len(keys)) for r in events[event]]
        score = score_rows(sample, gold, method, top=top)
        for field in ('precision', 'recall', 'f1'):
            value = score[field]['value'] if field != 'f1' else score[field]
            if value is not None:
                values[field].append(value)
    return {**{f: {'low': quantile(values[f], .025), 'high': quantile(values[f], .975), 'valid_replicates': len(values[f])} for f in ('precision', 'recall', 'f1')},
            'replicates': repeats, 'events': len(events), 'seed': seed, 'unit': 'independent event cluster; percentile 95%'}


def evaluate(rows, gold, manifest):
    review = review_summary(gold)
    results = {}
    for method in ('baseline', 'current'):
        overall = score_rows(rows, gold, method)
        groups = {}
        for dimension in ('sample', 'market', 'theme'):
            groups[dimension] = {label: score_rows([r for r in rows if r[dimension] == label], gold, method) for label in sorted({r[dimension] for r in rows})}
        # Type strata use the union of reference/predicted types, retaining false positives and misses.
        groups['type'] = {}
        for relation in sorted(KINDS):
            typed_gold = {key: {**g, 'links': [v for v in g['links'] if v['type'] == relation]} for key, g in gold.items()}
            typed_rows = [{**r, method: [v for v in r[method] if kind(v['relation']) == relation]} for r in rows
                          if typed_gold[r['id']]['links'] or any(kind(v['relation']) == relation for v in r[method])]
            groups['type'][relation] = score_rows(typed_rows, typed_gold, method)
            groups['type'][relation]['ci95'] = bootstrap(typed_rows, typed_gold, method)
        for dimension in ('sample', 'market', 'theme'):
            for label, metrics in groups[dimension].items():
                metrics['ci95'] = bootstrap([r for r in rows if r[dimension] == label], gold, method)
        groups['macro_strata'] = {}
        for dimension in ('sample', 'market', 'theme', 'type'):
            groups['macro_strata'][dimension] = {}
            for field in ('precision', 'recall', 'f1'):
                values = [s[field] if field == 'f1' else s[field]['value'] for s in groups[dimension].values()]
                values = [v for v in values if v is not None]
                groups['macro_strata'][dimension][field] = {'value': sum(values) / len(values) if values else None, 'strata': len(values)}
        results[method] = {'overall': overall, 'top8': score_rows(rows, gold, method, top=8),
                           'top8_ci95': bootstrap(rows, gold, method, top=8), 'groups': groups, 'ci95': bootstrap(rows, gold, method)}
    current = results['current']['overall']
    coverage = ({r['market'] for r in rows} == {'KR', 'US'}
                and {r['sample'] for r in rows} == {'normal', 'challenge'}
                and len({r['theme'] for r in rows}) == 4)
    eligible = (coverage and len({r['event_id'] for r in rows}) >= 100 and review['resolved_articles'] == len(rows)
                and all(g['status'] == 'reviewed' and g['complete'] for g in gold.values())
                and manifest.get('independent_final') is True and manifest.get('ui_review_sha256'))
    def goal(value, target):
        return 'unverified' if not eligible or value is None else 'met' if value >= target else 'unmet'
    results['goals'] = {'precision_95': goal(current['precision']['value'], .95), 'recall_80': goal(current['recall']['value'], .8),
                        'source_reproducibility_100': goal(current['evidence_time_verifiable']['value'], 1),
                        'challenge_critical_zero': 'unverified' if not eligible else 'met' if results['current']['groups']['sample'].get('challenge', {}).get('critical_predictions') == 0 else 'unmet'}
    results['reviews'] = review
    results['final_quality_verified'] = bool(eligible)
    results['latency_ms'] = {'n': len(rows), **{f'p{int(p*100)}': quantile([r['elapsed_ms'] for r in rows], p) for p in (.5, .95, .99)}, 'scope': 'baseline+current sequential offline diagnostic; not service latency'}
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path); parser.add_argument('--articles', type=Path)
    parser.add_argument('--catalogue', type=Path); parser.add_argument('--gold', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--audit', action='store_true', help='Record missing final data; no quality score')
    args = parser.parse_args()
    destination = args.output.resolve()
    if destination == ROOT or ROOT in destination.parents:
        parser.error('Raw outputs must be outside repository')
    if destination.exists():
        parser.error('Use a new output directory; do not overwrite a frozen run')
    destination.mkdir(parents=True, mode=0o700)
    env = environment()
    (destination / 'environment.json').write_text(json.dumps(env, ensure_ascii=False, indent=2))
    if args.audit:
        result = {'issue': 28, 'status': 'unverified', 'articles': 0, 'events': 0, 'human_reviews': 0,
                  'precision': None, 'recall': None, 'f1': None, 'p50': None, 'p95': None, 'p99': None,
                  'blockers': ['No frozen independent Korean full-article corpus supplied', 'No two-human blind gold or actual screen review supplied', 'No contemporaneous complete listing snapshot supplied'],
                  'llm_calls': 0, 'embedding_calls': 0, 'network_calls': 0}
    else:
        if not all((args.manifest, args.articles, args.catalogue)):
            parser.error('--manifest, --articles, --catalogue required unless --audit')
        load = lambda p: json.loads(p.read_text())
        manifest, articles, catalogue = map(load, (args.manifest, args.articles, args.catalogue))
        validate_inputs(manifest, articles, catalogue)
        # Gold is opened only after predictions have been materialized.
        rows = predict(articles, catalogue)
        (destination / 'predictions.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2))
        result = {'status': 'predictions_only', 'articles': len(rows)}
        if args.gold:
            gold = load(args.gold)
            validate_gold(gold, articles, manifest)
            result = evaluate(rows, gold, manifest)
            result['status'] = 'scored' if result['final_quality_verified'] else 'diagnostic_unverified'
            result['gold_sha256'] = fingerprint(gold)
        result['input_sha256'] = {str(p): sha256(p.read_bytes()).hexdigest() for p in (args.manifest, args.articles, args.catalogue)}
    (destination / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({'output': str(destination), 'status': result.get('status'), 'final_quality_verified': result.get('final_quality_verified', False)}))


if __name__ == '__main__':
    main()
