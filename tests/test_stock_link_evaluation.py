"""Synthetic accounting tests only; these are never a Korean article quality corpus."""
import copy
import unittest
from unittest.mock import patch

import evaluate_stock_links as e


def label(links=(), complete=True, status='reviewed'):
    return {'links': [{'code': code, 'type': relation} for code, relation in links], 'complete': complete,
            'status': status, 'negative_codes': [], 'critical_codes': {}, 'reviews': []}


def row(id, codes=(), event=None, sample='normal'):
    return {'id': id, 'event_id': event or id, 'sample': sample, 'market': 'KR', 'theme': 'semiconductors',
            'published_at': '2026-11-17T10:00:00+09:00', 'elapsed_ms': 1,
            'current': [{'code': c, 'relation': k, 'sources': []} for c, k in codes], 'baseline': []}


class StockLinkEvaluationTest(unittest.TestCase):
    def test_code_precision_type_confusion_abstention_and_negative_false_alarm(self):
        rows = [row('1', [('A', 'documented'), ('B', 'theme')]), row('2'), row('3', [('B', 'theme')])]
        gold = {'1': label([('A', 'direct')]), '2': label([('A', 'direct')]), '3': label()}
        score = e.score_rows(rows, gold, 'current')
        self.assertEqual((score['true_positive'], score['false_positive'], score['false_negative']), (1, 2, 1))
        self.assertEqual(score['precision']['value'], 1/3)
        self.assertEqual(score['recall']['value'], .5)
        self.assertEqual(score['type_confusion'], {'direct->documented': 1})
        self.assertEqual(score['gold_negative_false_alarm']['value'], 1)
        self.assertEqual(score['abstention']['numerator'], 1)
        self.assertEqual(score['per_article'][0]['wrong_codes'], ['B'])

    def test_incomplete_and_hold_are_not_automatic_false_positives_or_recall(self):
        rows = [row('1', [('A', 'direct'), ('B', 'theme')]), row('2', [('A', 'direct')])]
        gold = {'1': label([('A', 'direct')], complete=False), '2': label(status='hold')}
        result = e.score_rows(rows, gold, 'current')
        self.assertEqual(result['unknown_predictions'], 2)
        self.assertEqual(result['precision']['value'], 1)
        self.assertIsNone(result['recall']['value'])
        self.assertEqual(result['false_positive'], 0)
        self.assertEqual(result['per_article'][0]['missing_codes'], None)

    def test_no_prediction_precision_is_not_one(self):
        result = e.score_rows([row('1')], {'1': label([('A', 'direct')])}, 'current')
        self.assertIsNone(result['precision']['value'])
        self.assertEqual(result['recall']['value'], 0)

    def test_top8_and_future_evidence_are_counted(self):
        r = row('1', [(str(n), 'direct') for n in range(9)])
        r['current'][0]['sources'] = [{'url': 'https://example.test', 'published_on': '2026-11-18'}]
        g = {'1': label([(str(n), 'direct') for n in range(9)])}
        result = e.score_rows([r], g, 'current', top=8)
        self.assertEqual(result['predictions'], 8)
        self.assertEqual(result['recall']['value'], 8/9)
        self.assertEqual(result['critical_predictions'], 1)
        self.assertEqual(result['per_article'][0]['critical'][0]['tags'], ['future_evidence'])

    def test_missing_source_date_is_unverified_instead_of_crashing(self):
        r = row('1', [('A', 'direct')])
        r['current'][0]['sources'] = [{'url': 'https://example.test', 'published_on': None}]
        result = e.score_rows([r], {'1': label([('A', 'direct')])}, 'current')
        self.assertEqual(result['evidence_time_verifiable']['value'], 0)
        self.assertEqual(result['critical_predictions'], 0)

    def test_cluster_bootstrap_keeps_retransmissions_in_same_unit(self):
        rows = [row('1', [('A', 'direct')], event='same'), row('2', [('B', 'direct')], event='same'), row('3', [('A', 'direct')])]
        g = {r['id']: label([('A', 'direct')]) for r in rows}
        one = e.bootstrap(rows, g, 'current', repeats=30)
        self.assertEqual(one, e.bootstrap(rows, g, 'current', repeats=30))
        self.assertEqual(one['events'], 2)
        self.assertEqual(one['precision']['valid_replicates'], 30)
        self.assertIsNone(e.bootstrap(rows[:2], g, 'current')['precision'])

    def test_no_human_review_never_certifies_quality(self):
        rows = [row('1', [('A', 'direct')])]
        g = {'1': label([('A', 'direct')])}
        result = e.evaluate(rows, g, {'independent_final': True, 'ui_review_sha256': 'claimed'})
        self.assertFalse(result['final_quality_verified'])
        self.assertEqual(set(result['goals'].values()), {'unverified'})

    def test_two_reviewers_need_human_blind_and_resolution(self):
        base = {'human': True, 'prediction_blind': True, 'record_sha256': 'record', 'reviewed_at': 'date'}
        g = label()
        g['reviews'] = [{**base, 'reviewer': 'one', 'decision_sha256': 'a'}, {**base, 'reviewer': 'two', 'decision_sha256': 'b'}]
        self.assertEqual(e.review_summary({'a': g})['resolved_articles'], 0)
        g['adjudication'] = {'record_sha256': 'resolution', 'decision_sha256': e.decision_fingerprint(g)}
        self.assertEqual(e.review_summary({'a': g})['resolved_articles'], 1)
        g['reviews'][1]['human'] = False
        self.assertEqual(e.review_summary({'a': g})['two_human_blind_reviews'], 0)

    def test_production_title_only_path_is_reused_without_network(self):
        articles = [{'id': 'x', 'event_id': 'x', 'sample': 'normal', 'market': 'KR', 'theme': 'semiconductors',
                     'title': '삼성전자 실적 발표', 'body': '엔비디아', 'published_at': '2026-11-17T10:00:00+09:00', 'source_url': 'https://example.test'}]
        catalogue = {'005930': {'code': '005930', 'name': '삼성전자', 'products': '', 'country': 'KR'}}
        before = copy.deepcopy(articles)
        with patch.object(e.stocks, 'fetch', side_effect=AssertionError('No network')):
            result = e.predict(articles, catalogue)
        self.assertEqual(result[0]['baseline'][0]['code'], '005930')
        self.assertEqual(result[0]['current'][0]['relation'], 'direct')
        self.assertEqual(articles, before)
        self.assertNotEqual(e.stocks.CATALOGUE, catalogue)

    def test_existing_body_reading_follows_actual_screen_path(self):
        articles = [{'id': 'x', 'event_id': 'x', 'sample': 'normal', 'market': 'KR', 'theme': 'semiconductors',
                     'title': '기업 실적 발표', 'body': '삼성전자가 실적을 발표했다.', 'published_at': '2026-11-17T10:00:00+09:00',
                     'source_url': 'https://example.test', 'reading': {'article_title': '기업 실적 발표',
                     'entity_mentions': [{'name': '삼성전자', 'evidence': '삼성전자가 실적을 발표했다.'}]}}]
        catalogue = {'005930': {'code': '005930', 'name': '삼성전자', 'products': '', 'country': 'KR'}}
        with patch.object(e.stocks, 'fetch', side_effect=AssertionError('No network')):
            result = e.predict(articles, catalogue)
        self.assertEqual(result[0]['baseline'], [])
        self.assertEqual(result[0]['current'][0]['relation'], 'body')
        self.assertEqual(e.kind('body'), 'direct')

    def test_manifest_fingerprints_period_strata_and_event_leakage(self):
        a = [{'id': 'a', 'event_id': 'event', 'sample': 'normal', 'market': 'KR', 'theme': 'semiconductors',
              'published_at': '2026-11-17T10:00:00+09:00', 'source_url': 'https://example.test',
              'body': 'private article fixture', 'source_archive_sha256': 'archive', 'primary_type': 'direct', 'challenge_tag': 'none'}]
        catalogue = {'A': {'code': 'A'}}
        m = {'rules': e.rule_hashes(), 'articles_sha256': e.fingerprint(a), 'catalogue_sha256': e.fingerprint(catalogue),
             'candidate_codes': ['A'], 'development_event_ids': [], 'development_end': '2026-11-16',
             'final_start': '2026-11-17', 'final_end': '2026-11-18', 'frozen_at': '2026-11-16T00:00:00+00:00',
             'listing_archive_sha256': 'archive', 'relation_archives_sha256': 'archives',
             'strata_counts': {'normal|KR|semiconductors': 1}, 'primary_type_counts': {'direct': 1}, 'challenge_tag_counts': {'none': 1}}
        e.validate_inputs(m, a, catalogue)
        for changed in ({'development_event_ids': ['event']}, {'strata_counts': {}}, {'rules': {}}, {'articles_sha256': 'wrong'}):
            with self.assertRaises(ValueError):
                e.validate_inputs({**m, **changed}, a, catalogue)

    def test_gold_future_timestamp_and_quote_validation(self):
        a = [{'id': 'a', 'title': 'abc', 'body': 'def', 'published_at': '2026-11-17T10:00:00+09:00'}]
        g = label([('A', 'direct')])
        g['links'][0].update(quote='abc', known_at='2026-11-17T00:59:00+00:00', source_url='https://example.test', source_archive_sha256='archive')
        e.validate_gold({'a': g}, a, {'candidate_codes': ['A']})
        g['links'][0]['known_at'] = '2026-11-17T02:00:00+00:00'
        with self.assertRaises(ValueError):
            e.validate_gold({'a': g}, a, {'candidate_codes': ['A']})


if __name__ == '__main__':
    unittest.main()
