from datetime import date
from pathlib import Path
import tempfile
import unittest
import json
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError

import archive
import news_ingestion as news


class NewsCollectionTest(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        p=patch.object(archive,'PATH',Path(temp.name)/'news.sqlite3');p.start();self.addCleanup(p.stop)
        p=patch('news_ingestion.time.sleep');p.start();self.addCleanup(p.stop)

    def rows(self,start,count=15):
        return [{'officeId':'001','articleId':str(i).zfill(10),'officeHname':'테스트신문',
                 'title':f'일반 금융 기사 {i}','datetime':'2026-11-12 10:00:00','subcontent':'안내'} for i in range(start,start+count)]

    def test_bounded_sweep_restarts_at_first_page_and_resumes_incomplete_range(self):
        pages={1:self.rows(1),2:self.rows(16),3:self.rows(31,2)}
        with patch.object(news,'fetch_page',side_effect=lambda d,p:pages[p]) as fetch:
            self.assertEqual(news.collect_day('2026-11-12',2)['status'],'partial')
            self.assertEqual(news.status('2026-11-12')['next_page'],3)
            self.assertEqual(news.collect_day('2026-11-12',2)['status'],'complete')
            self.assertEqual([c.args[1] for c in fetch.call_args_list],[1,2,1,3])
        self.assertEqual(archive.summary()['articles'],32)
        self.assertEqual(archive.summary()['revisions'],32)

    def test_later_page_failure_retains_checkpoint_and_records_backoff(self):
        with patch.object(news,'fetch_page',side_effect=[self.rows(1),ValueError('changed')]):
            self.assertRaises(ValueError,news.collect_day,'2026-11-12',3)
        state=news.status('2026-11-12')
        self.assertEqual(state['next_page'],2)
        self.assertIn('changed',state['last_error'])
        with patch.object(news,'fetch_page') as fetch:
            self.assertEqual(news.collect_day('2026-11-12')['status'],'backoff')
            fetch.assert_not_called()

    def test_storage_and_checkpoint_commit_together(self):
        original=archive.store
        def fail(rows,db):
            original(rows,db)
            raise OSError('disk')
        with patch.object(news,'fetch_page',return_value=self.rows(1)),patch.object(archive,'store',side_effect=fail):
            self.assertRaises(OSError,news.collect_day,'2026-11-12')
        self.assertEqual(archive.summary()['articles'],0)
        self.assertEqual(news.status('2026-11-12')['next_page'],1)

    def test_page_schema_date_and_ids_are_validated(self):
        for bad in [{**self.rows(1,1)[0],'articleId':'../bad'},{**self.rows(1,1)[0],'datetime':'2026-11-11 10:00:00'},
                    {**self.rows(1,1)[0],'title':''}]:
            self.assertRaises(ValueError,news.parse_articles,[bad],'2026-11-12')

    def test_rate_limit_retry_after_and_busy_lease_do_not_advance(self):
        error=HTTPError('https://stock.naver.com',429,'limited',{'Retry-After':'1800'},None)
        with patch('news_ingestion.time.time',return_value=1000),patch.object(news,'fetch_page',side_effect=error):
            self.assertRaises(HTTPError,news.collect_day,'2026-11-12')
        self.assertEqual(news.status('2026-11-12')['retry_after'],2800)
        with news.lease('news-collection.lock'):
            self.assertEqual(news.collect_day('2026-11-12')['status'],'busy')

    def test_reconciliation_reports_partial_instead_of_false_success(self):
        with patch.object(news,'today',return_value=date(2026,11,12)),patch.object(news,'collect_day',return_value={'status':'partial'}) as collect:
            self.assertRaises(RuntimeError,news.reconcile)
            self.assertEqual([c.args[0] for c in collect.call_args_list],['2026-11-12','2026-11-11'])

    def test_fast_lane_stores_latest_news_while_recovery_holds_the_sweep_lease(self):
        with news.lease('news-collection.lock'),patch.object(news,'fetch_page',return_value=self.rows(1,2)):
            result=news.collect_day('2026-11-12',latest_on_busy=True)
        self.assertEqual(result['status'],'latest_only')
        self.assertEqual(archive.summary()['articles'],2)
        self.assertEqual(news.status('2026-11-12')['next_page'],1)

    def test_unfinished_days_are_not_forgotten_when_the_date_changes(self):
        news.status('2026-11-09')
        with archive.db() as db:db.execute("INSERT INTO news_collection(day,next_page) VALUES('2026-11-09',20)")
        with patch.object(news,'today',return_value=date(2026,11,12)),patch.object(news,'collect_day',return_value={'status':'complete'}) as collect:
            news.reconcile()
        self.assertEqual([c.args[0] for c in collect.call_args_list],['2026-11-12','2026-11-09'])

    def test_provider_date_boundary_can_include_a_second_page_from_previous_day(self):
        current=self.rows(1,10)
        previous=[{**r,'datetime':'2026-11-11 20:00:00'} for r in self.rows(11,15)]
        response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps({'articles':current+previous,'date':'20261111','isFirstDate':False}).encode()
        with patch.object(news,'urlopen',return_value=response):
            rows=news.fetch_page('2026-11-12',73)
        self.assertEqual(rows,current)
        with patch.object(news,'fetch_page',return_value=rows):
            self.assertEqual(news.collect_day('2026-11-12')['status'],'complete')
