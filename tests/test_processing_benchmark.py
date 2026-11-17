"""The benchmark must preserve meaning and isolate writes, even without real price data."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import archive
from scripts import benchmark_processing as benchmark


class ProcessingBenchmarkTest(unittest.TestCase):
    def run_case(self, scenario, cache='on', instrument=True):
        with tempfile.TemporaryDirectory(prefix='test-eval26-') as directory:
            return benchmark.replay(Path(directory), benchmark.synthetic(2), scenario, cache, instrument)

    def test_deterministic_expansion_and_quantile_denominators(self):
        articles = benchmark.synthetic(2)
        self.assertEqual(articles, benchmark.synthetic(2))
        expanded = benchmark.expand(articles, 10)
        self.assertEqual(len({a['id'] for a in expanded}), 20)
        self.assertEqual(len({a['title'] for a in expanded}), 20)
        self.assertEqual(len({a['url'] for a in expanded}), 20)
        self.assertEqual(benchmark.distribution([]), {'n': 0, 'p50': None, 'p95': None, 'p99': None})
        self.assertEqual(benchmark.distribution([3, 1, 2]), {'n': 3, 'p50': 2, 'p95': 3, 'p99': 3})

    def test_new_preserves_source_semantics_and_no_observation_becomes_success(self):
        source_path = archive.PATH
        result = self.run_case('new')
        self.assertEqual(archive.PATH, source_path)
        self.assertTrue(result['checks']['new_preserves_semantics'])
        self.assertEqual(result['processed_article_versions'], 2)
        self.assertEqual(result['calculated_complete_jobs'], 0)
        self.assertGreater(result['counts_after']['states'].get('waiting', 0), 0)
        self.assertGreater(result['counts_after']['states'].get('unsupported', 0), 0)
        self.assertEqual(result['backlog_samples'][-1]['executable'], 0)
        self.assertGreater(result['peak_executable_backlog'], 0)
        self.assertEqual(result['sql_instrumented']['errors'], 0)

    def test_repeat_cache_and_correction_invalidation(self):
        cached = self.run_case('repeat')
        uncached = self.run_case('repeat', 'off')
        native = self.run_case('repeat', instrument=False)
        self.assertTrue(cached['checks']['repeat_preserves_counts'])
        self.assertTrue(cached['checks']['repeat_preserves_semantics'])
        self.assertEqual(cached['computations']['reactions'], 0)
        self.assertGreater(uncached['computations']['reactions'], 0)
        self.assertIsNone(native['sql_instrumented'])
        self.assertIsNone(native['computations'])
        self.assertEqual(native['queue_monotonic_seconds']['n'], 0)
        for scenario in ('correction', 'rules'):
            with self.subTest(scenario=scenario):
                result = self.run_case(scenario)
                self.assertFalse(result['failures'])
                if scenario == 'correction':
                    self.assertEqual(result['stages_inclusive_seconds']['classify_link']['n'], 1)
                self.assertTrue(all(v is not False for v in result['checks'].values()))

    def test_supported_synthetic_uses_storage_and_preserves_full_price_windows(self):
        with tempfile.TemporaryDirectory(prefix='test-eval26-supported-') as directory:
            root = Path(directory)
            manifest = benchmark.seed_supported_market(root/'market.sqlite3')
            self.assertEqual(sum(manifest['bars'].values()), 879)
            articles = benchmark.supported_articles(1)
            for scenario in ('new','repeat','correction','rules'):
                with self.subTest(scenario=scenario):
                    # Each scenario owns its DB copy; source fixtures never overwrite production data.
                    run = root/scenario; run.mkdir()
                    source=benchmark.sqlite3.connect(root/'market.sqlite3'); target=benchmark.sqlite3.connect(run/'market.sqlite3')
                    try: source.backup(target)
                    finally: source.close(); target.close()
                    result = benchmark.replay(run, articles, scenario, 'on', True, True)
                    self.assertTrue(all(v is not False for v in result['checks'].values()), result['checks'])
                    self.assertEqual(result['calculated_complete_jobs'], 4)
                    self.assertEqual(result['counts_after']['bodies'], 1)
                    self.assertEqual(result['supported_results']['observed_adjusted_pairs'], 2)
                    if scenario == 'repeat':
                        self.assertEqual(result['computations']['reactions'], 0)
                        self.assertEqual(result['computations']['observation_attempts'], 4)
                    if scenario == 'new':
                        with patch.object(benchmark.market_history,'PATH',run/'market.sqlite3'):
                            prices={r['day']:r for r in benchmark.market_history.observations('KR','005930')}
                            runs=benchmark.event_reactions.snapshot(articles[0]['id'])['runs']
                        public=next(r for r in runs if r['basis']=='public' and r['symbol']=='005930')
                        window=next(w for w in public['windows'] if w['name']=='event_day')
                        expected=float(prices['2026-11-05']['closePrice'])/float(prices['2026-11-04']['closePrice'])-1
                        self.assertAlmostEqual(window['raw_return'],expected,places=12)
                        self.assertEqual(public['model']['samples'],120)

    def test_external_call_attempt_is_blocked_and_reported(self):
        def accidental_network(job):
            with benchmark.socket.socket() as client:
                client.connect(('127.0.0.1', 9))
        with patch.object(benchmark.worker, 'observe', accidental_network):
            result = self.run_case('new')
        self.assertEqual(result['calculated_complete_jobs'], 0)
        self.assertGreater(result['counts_after']['states']['error'], 0)


if __name__ == '__main__':
    unittest.main()
