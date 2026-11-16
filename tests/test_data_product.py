from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import archive
import data_product
import server


class DataProductTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        for p in (patch('archive.PATH', Path(temp.name)/'news.sqlite3'),
                  patch.dict('os.environ', {'PRODUCT_MODE':'data'})):
            p.start()
            self.addCleanup(p.stop)
        self.article = {'id':'a','url':'https://example.com/a','source_id':'naver','source':'포털',
                        'title':'일반 금융 안내','published_at':'2026-11-16T00:00:00+00:00',
                        'timestamp_basis':'portal_display','kind':'news'}

    def test_source_versions_separate_portal_time_and_do_not_invent_publication(self):
        archive.store([self.article])
        archive.save_body(self.article['url'], text='보존된 원문 본문입니다.')
        with patch('server.intelligence.snapshot', side_effect=AssertionError('model snapshot')):
            result = server.archive_snapshot({})['articles'][0]
        evidence = result['evidence']
        self.assertIsNone(evidence['published_at'])
        self.assertEqual(evidence['portal_display_at'], self.article['published_at'])
        self.assertEqual(evidence['classification_status'], 'unclassified')
        self.assertEqual(evidence['assessment_status'], 'not_analyzed')
        self.assertEqual(evidence['source_status'], 'body_available')
        self.assertIn('보존된 원문', evidence['body_excerpt'])
        self.assertIn(':', evidence['body_version'])
        first_seen = evidence['first_seen_at']
        archive.store([{**self.article,'title':'제목 변경'}])
        changed = data_product.attach([{**self.article,'themes':[]}])[0]['evidence']
        self.assertEqual(changed['source_status'], 'source_missing')
        self.assertIsNone(changed['source_excerpt'])
        current = server.archive_snapshot({})['articles'][0]['evidence']
        self.assertEqual(current['first_seen_at'], first_seen)
        self.assertNotEqual(current['article_version'], evidence['article_version'])

    def test_missing_source_and_unknown_publication_stay_missing(self):
        a = {**self.article,'published_at':None,'themes':[]}
        e = data_product.attach([a])[0]['evidence']
        self.assertEqual(e['source_status'], 'source_missing')
        self.assertIsNone(e['published_at'])
        self.assertIsNone(e['first_seen_at'])

    def test_startup_and_background_targets_have_no_model_worker(self):
        with patch('server.threading.Thread') as thread, \
             patch('server.intelligence.collector', side_effect=AssertionError('model worker')):
            server.start_workers('data')
            self.assertEqual(thread.call_count, 3)
            targets = [call.kwargs['target'] for call in thread.call_args_list]
            self.assertNotIn(server.intelligence.collector, targets)
        archive.store([self.article])
        with patch('server.intelligence.snapshot', side_effect=AssertionError('model snapshot')), \
             patch('server.stocks.related_stocks', return_value=[]), \
             patch('server.news_ingestion.status', return_value={}), \
             patch.dict(server.STATE, {'articles':[],'sources':[]}):
            self.assertEqual(server.snapshot()['product_mode'], 'data')
            self.assertEqual(len(server.archive_snapshot({})['articles']), 1)
        with patch('server.threading.Thread') as thread:
            server.start_workers('model')
            self.assertEqual(thread.call_count, 4)


if __name__ == '__main__':
    unittest.main()
