import copy
import unittest

import evaluate_freshness as e


class FreshnessEvaluationTest(unittest.TestCase):
    def trace(self, **changes):
        return dict({'kind': 'article', 'id': 'synthetic', 'version': 'v1', 'market': 'KR', 'status': 'ok',
                     'portal_display_at': '2026-11-16T00:00:00Z', 'observed_at': '2026-11-16T00:00:05Z',
                     'stored_at': '2026-11-16T00:00:06Z', 'processed_at': '2026-11-16T00:00:07Z',
                     'api_at': '2026-11-16T00:00:08Z', 'browser_at': '2026-11-16T00:00:13Z'}, **changes)

    def data(self, *rows, **changes):
        return dict({'mode': 'synthetic_replay', 'as_of': '2026-11-17T00:00:00Z', 'traces': list(rows)}, **changes)

    def test_missing_publication_is_not_replaced_with_portal_or_collection(self):
        data = self.data(self.trace())
        before = copy.deepcopy(data); result = e.evaluate(data)['all']
        self.assertEqual(data, before)
        self.assertEqual(result['latency']['portal_to_observed']['p95_seconds'], 5)
        self.assertIsNone(result['latency']['published_to_display']['p95_seconds'])
        self.assertEqual(result['timestamp_unknown']['published_at']['ratio'], 1)
        self.assertEqual(result['ready_to_display']['p95_seconds'], 5)
        self.assertEqual(result['ready_to_display']['status'], 'met')

    def test_incomplete_display_denominator_blocks_passing_budget(self):
        result = e.evaluate(self.data(self.trace(), self.trace(version='v2', kind='correction', browser_at=None)))
        self.assertEqual(result['all']['ready_to_display']['denominator'], 2)
        self.assertEqual(result['all']['ready_to_display']['samples'], 1)
        self.assertEqual(result['all']['ready_to_display']['status'], 'unverified')
        self.assertIsNone(result['all']['collected_versions_displayed']['ratio'])
        self.assertEqual(result['all']['collected_versions_displayed']['confirmed_lower_bound'], .5)
        self.assertEqual(result['all']['collected_versions_displayed']['unknown'], 1)
        self.assertEqual(result['groups']['KR/correction']['rows'], 1)
        self.assertEqual(e.evaluate(self.data(self.trace(browser_at='2026-11-16T00:00:19Z')))['all']['ready_to_display']['status'], 'unmet')

    def test_negative_and_future_are_counted_and_not_clamped_to_zero(self):
        result = e.evaluate(self.data(self.trace(browser_at='2026-11-16T00:00:04Z'),
                                      self.trace(version='future', browser_at='2026-11-18T00:00:00Z')))['all']
        self.assertEqual(result['latency']['observed_to_display']['negative'], 1)
        self.assertEqual(result['future_timestamps']['browser_at'], 1)
        self.assertIsNone(result['latency']['api_to_display']['p50_seconds'])
        self.assertEqual(result['ready_to_display']['negative'], 1)
        self.assertEqual(result['ready_to_display']['status'], 'unverified')

    def test_unobserved_browser_is_unknown_but_completed_probe_can_confirm_absence(self):
        result = e.evaluate(self.data(self.trace(browser_at=None)))['all']['collected_versions_displayed']
        self.assertIsNone(result['ratio']); self.assertEqual(result['unknown'], 1)
        result = e.evaluate(self.data(self.trace(browser_at=None, browser_checked_at='2026-11-17T00:00:00Z')))['all']['collected_versions_displayed']
        self.assertEqual(result['ratio'], 0); self.assertEqual(result['unknown'], 0)

    def test_independent_omission_requires_explicit_expected_versions(self):
        self.assertIsNone(e.evaluate(self.data(self.trace()))['source_omission']['ratio'])
        targets = [{'kind': 'article', 'id': 'synthetic', 'version': v, 'market': 'KR'} for v in ('v1', 'v2')]
        result = e.evaluate(self.data(self.trace(), independent_source_targets=targets))['source_omission']
        self.assertEqual(result['denominator'], 2)
        self.assertEqual(result['ratio'], .5)
        self.assertFalse(result['complete_source_recall_claim'])

    def test_quote_trade_age_and_collection_delay_are_separate(self):
        row = self.trace(kind='quote', instrument='stock', traded_at='2026-11-16T00:00:00Z')
        result = e.evaluate(self.data(row))['all']
        self.assertEqual(result['latency']['trade_to_observed']['p95_seconds'], 5)
        self.assertEqual(result['trade_age_at_cutoff']['p95_seconds'], 86400)
        self.assertEqual(result['ready_to_display']['denominator'], 0)

    def test_five_minute_retains_all_reasons_and_etf_denominator(self):
        minutes = [{'market': 'KR', 'instrument': instrument, 'code': code, 'at': f'2026-11-16T00:0{i}:00Z', 'status': status}
                   for instrument, code in [('stock', 'synthetic'), ('benchmark_etf', 'synthetic-etf')]
                   for i, status in enumerate(['ok', 'pending', 'observation_gap', 'outside_session', 'stale'])]
        result = e.evaluate(self.data(five_minute=minutes))['five_minute']
        self.assertEqual(result['KR/stock']['available'], {'count': 1, 'denominator': 5, 'ratio': .2})
        self.assertEqual(result['KR/benchmark_etf']['reasons']['pending']['count'], 1)
        self.assertIsNone(result['US/stock']['available']['ratio'])
        self.assertRaises(ValueError, e.evaluate, self.data(five_minute=minutes + minutes[:1]))

    def test_tracked_security_denominator_keeps_missing_and_failure(self):
        rows = [{'market': 'KR', 'code': str(i), 'instrument': 'stock', 'at': '2026-11-16T00:00:00Z', 'status': status}
                for i, status in enumerate(['ok', 'failed', 'missing', 'unsupported', 'delayed', 'closed', 'no_trade'])]
        result = e.evaluate(self.data(tracked_status=rows))['tracked_status']['KR/stock']
        self.assertEqual(result['missing']['count'], 1)
        self.assertEqual(result['ok']['denominator'], 7)
        self.assertRaises(ValueError, e.evaluate, self.data(tracked_status=rows + rows[:1]))
        minute = {'market': 'KR', 'code': 'synthetic', 'instrument': 'stock', 'at': '2026-11-16T00:00:00Z',
                  'status': 'pending', 'reported_change_percent': 0}
        self.assertEqual(e.evaluate(self.data(five_minute=[minute]))['false_normal_or_publication_fill']['status'], 'unmet')

    def test_invalid_mode_timestamp_version_and_normalized_failure_are_detected(self):
        for data in (self.data(self.trace(), mode='live-ish'), self.data(self.trace(observed_at='2026-11-16T00:00:00')),
                     self.data(self.trace(), self.trace()), self.data(self.trace(kind='quote'))):
            with self.assertRaises(ValueError):
                e.evaluate(data)
        result = e.evaluate(self.data(self.trace(status='failed', reported_change_percent=0),
                                      self.trace(version='v2', published_at_inferred=True)))
        self.assertEqual(result['false_normal_or_publication_fill']['count'], 2)
        self.assertFalse(result['release_approved'])

    def test_synthetic_windows_never_satisfy_real_market_coverage(self):
        windows = [{'market': market, 'date': f'2026-11-{day}', 'phase': phase, 'normal_open_day_verified': True}
                   for market in ('KR', 'US') for day in (11, 12, 13)
                   for phase in ('opening', 'intraday', 'closing', 'outside')]
        result = e.evaluate(self.data(observation_windows=windows))
        self.assertEqual(result['real_market_coverage']['KR']['complete_days'], 0)
        result = e.evaluate(self.data(observation_windows=windows, mode='real_observation'))
        self.assertEqual(result['real_market_coverage']['US']['complete_days'], 3)
        self.assertEqual(result['real_market_coverage']['US']['status'], 'met')


if __name__ == '__main__':
    unittest.main()
