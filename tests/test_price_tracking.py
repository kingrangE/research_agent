from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import price_tracking as tracking


class PriceTrackingTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.patch=patch.object(tracking,'PATH',Path(self.temp.name)/'quotes.sqlite3')
        self.patch.start();self.addCleanup(self.patch.stop)
        self.article={'id':'news','title':'엔비디아 새 소식','url':'https://example.com','published_at':'2026-11-16T14:40:00Z','timestamp_basis':'portal_display'}
        self.stock={'code':'NVDA.O','name':'엔비디아','country':'US'}
        self.clock='2026-11-16T14:45:00Z'

    def quote(self,price=100,traded='2026-11-16T14:41:00Z',**extra):
        return dict(code='NVDA.O',name='엔비디아',price=price,currency='USD',status='ok',source='Npay 증권',
                    traded_at=traded,fetched_at=self.clock,delay_label='실시간',market_status='OPEN',**extra)

    def register(self):
        tracking.register(self.article,[self.stock],now=self.clock)

    def test_unclassified_news_tracks_first_actual_price_and_subsequent_change(self):
        self.register()
        tracking.record('NVDA.O',self.quote(),now=self.clock)
        tracking.record('NVDA.O',self.quote(103,'2026-11-16T14:42:00Z'),now=self.clock)
        result=tracking.snapshot('news',now=self.clock)
        row=result['stocks'][0]
        self.assertEqual(row['status'],'tracking')
        self.assertAlmostEqual(row['change_percent'],3)
        self.assertEqual(row['baseline']['price'],100)
        self.assertEqual(result['reference_basis'],'portal_display')
        self.assertEqual(len(row['points']),2)
        self.assertEqual(row['baseline_delay_seconds'],60)

    def test_pre_news_closed_quote_does_not_become_post_news_baseline(self):
        self.register()
        tracking.record('NVDA.O',self.quote(traded='2026-11-16T13:00:00Z'),now=self.clock)
        row=tracking.snapshot('news',now=self.clock)['stocks'][0]
        self.assertEqual(row['status'],'waiting_for_trade')
        self.assertIsNone(row['change_percent'])
        self.assertEqual(row['latest']['price'],100)

    def test_one_trade_is_a_start_not_measured_zero_change(self):
        self.register()
        tracking.record('NVDA.O',self.quote(),now=self.clock)
        tracking.record('NVDA.O',self.quote(),now=self.clock)
        row=tracking.snapshot('news',now=self.clock)['stocks'][0]
        self.assertEqual(row['status'],'baseline_only')
        self.assertIsNone(row['change_percent'])
        tracking.record('NVDA.O',self.quote(100,'2026-11-16T14:42:00Z'),now=self.clock)
        self.assertEqual(tracking.snapshot('news',now=self.clock)['stocks'][0]['change_percent'],0)

    def test_invalid_or_failed_quotes_preserve_previous_data_without_inventing_zero(self):
        self.register()
        tracking.record('NVDA.O',self.quote(),now=self.clock)
        for changes in ({'price':0},{'price':float('nan')},{'currency':'KRW'},{'status':'stale'},
                        {'traded_at':'2026-11-17T00:00:00Z'},{'traded_at':'2026-11-16T14:42:00'},
                        {'fetched_at':'2026-11-17T00:00:00Z'}):
            quote={**self.quote(),**changes}
            tracking.record('NVDA.O',quote,now=self.clock)
        row=tracking.snapshot('news',now=self.clock)['stocks'][0]
        self.assertEqual(row['latest']['price'],100)
        self.assertIsNone(row['change_percent'])
        self.assertEqual(row['collection_status'],'error')

    def test_same_time_correction_is_retained_and_latest_revision_used(self):
        self.register()
        tracking.record('NVDA.O',self.quote(),now=self.clock)
        tracking.record('NVDA.O',self.quote(101),now=self.clock)
        tracking.record('NVDA.O',self.quote(103,'2026-11-16T14:42:00Z'),now=self.clock)
        row=tracking.snapshot('news',now=self.clock)['stocks'][0]
        self.assertEqual(row['baseline']['price'],101)
        self.assertAlmostEqual(row['change_percent'],100*(103/101-1))
        self.assertEqual(len(row['points']),2)

    def test_unknown_publication_uses_first_seen_not_an_invented_publication(self):
        article={**self.article,'published_at':None}
        tracking.register(article,[self.stock],first_seen='2026-11-16T14:39:00Z',now=self.clock)
        r=tracking.snapshot('news',now=self.clock)
        self.assertEqual(r['reference_basis'],'first_seen')
        self.assertEqual(r['reference_at'],'2026-11-16T14:39:00+00:00')

    def test_old_sample_is_explicitly_stale_and_restart_preserves_baseline(self):
        self.register()
        tracking.record('NVDA.O',self.quote(),now=self.clock)
        tracking.record('NVDA.O',self.quote(102,'2026-11-16T14:42:00Z'),now=self.clock)
        row=tracking.snapshot('news',now='2026-11-16T14:48:00Z')['stocks'][0]
        self.assertTrue(row['stale'])
        self.assertEqual(row['baseline']['price'],100)
        self.assertEqual(tracking.snapshot('missing',now=self.clock)['stocks'],[])


    def test_background_cycle_polls_related_stocks_without_event_classification(self):
        self.register()
        with patch('price_tracking.archive.browse',return_value={'articles':[self.article]}),patch('price_tracking.archive.provenance',return_value={}),patch('price_tracking.stocks.related_stocks',return_value=[self.stock]),patch.dict('price_tracking.stocks.CATALOGUE',{'NVDA.O':self.stock}),patch('price_tracking.stocks.get_quotes',return_value={'NVDA.O':self.quote()}),patch('price_tracking.now_text',return_value=self.clock):
            self.assertEqual(tracking.cycle(),1)
        self.assertEqual(tracking.snapshot('news',now=self.clock)['stocks'][0]['status'],'baseline_only')

    def test_http_registers_an_unclassified_archived_article_and_rejects_unknown_ids(self):
        import archive
        import json
        import server
        from http.server import ThreadingHTTPServer
        import threading
        from urllib.request import urlopen
        from urllib.error import HTTPError
        with patch.object(archive,'PATH',Path(self.temp.name)/'news.sqlite3'),patch('server.classify',return_value={'related_stocks':[self.stock]}):
            archive.store([{**self.article,'source_id':'test'}])
            http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
            thread=threading.Thread(target=lambda:http.serve_forever(poll_interval=.01),daemon=True);thread.start()
            try:
                base='http://127.0.0.1:'+str(http.server_port)
                with urlopen(base+'/api/price-movement?article_id=news') as response:
                    result=json.load(response)
                self.assertEqual(result['stocks'][0]['code'],'NVDA.O')
                self.assertIsNone(result['stocks'][0]['change_percent'])
                for path,status in [('/api/price-movement',400),('/api/price-movement?article_id=missing',404)]:
                    with self.assertRaises(HTTPError) as error:urlopen(base+path)
                    self.assertEqual(error.exception.code,status)
            finally:http.shutdown();http.server_close();thread.join()

    def test_same_price_with_market_close_preserves_the_new_session_state(self):
        self.register()
        tracking.record('NVDA.O',self.quote(),now=self.clock)
        tracking.record('NVDA.O',{**self.quote(),'market_status':'CLOSE'},now=self.clock)
        row=tracking.snapshot('news',now=self.clock)['stocks'][0]
        self.assertEqual(row['latest']['market_status'],'CLOSE')
        self.assertEqual(len(row['points']),1)
        self.assertIsNone(row['change_percent'])
