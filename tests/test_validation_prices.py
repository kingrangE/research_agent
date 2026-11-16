from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,Mock

import event_corpus
import market_history as h
import validation_prices as v


class ValidationPriceTest(unittest.TestCase):
    def test_merged_windows_cover_every_probe_without_duplicate_days(self):
        corpus=event_corpus.load();jobs=v.plan(corpus)
        for job in jobs:self.assertLessEqual((date.fromisoformat(job['until'])-date.fromisoformat(job['since'])).days,366)
        for market,symbol in {(j['market'],j['symbol']) for j in jobs}:
            ordered=sorted((j for j in jobs if (j['market'],j['symbol'])==(market,symbol)),key=lambda j:j['since'])
            for a,b in zip(ordered,ordered[1:]):self.assertLess(a['until'],b['since'])
        for p in v.probes(corpus):
            for symbol in (p['symbol'],p['benchmark']):
                relevant=[j for j in jobs if (j['market'],j['symbol'])==(p['market'],symbol)]
                self.assertTrue(any(j['since']<=p['since']<=j['until'] for j in relevant))
                self.assertTrue(any(j['since']<=p['until']<=j['until'] for j in relevant))
        self.assertLess(len(jobs),len(corpus['cases']))

    def test_partial_resumes_and_provider_error_stops_without_success(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        spec={'market':'KR','symbol':'KOSPI','since':'2024-01-01','until':'2024-01-31'}
        with patch.object(h,'PATH',Path(tmp.name)/'market.sqlite3'),patch.object(v,'PROGRESS',Path(tmp.name)/'progress.json'),patch.object(v,'plan',return_value=[spec]),patch.object(h,'Toss') as client,patch.object(h,'collect',side_effect=[{'status':'partial'},{'status':'error','error':'HTTP 429'}]),patch('builtins.print'):
            result=v.collect()
            self.assertEqual(result['completed'],0);self.assertEqual(result['error'],'HTTP 429')
            self.assertEqual(h.collect.call_count,2)
            self.assertEqual(client.call_count,1)
        self.assertRaises(ValueError,v.collect,0)

    def test_price_check_compares_original_values_and_preserves_missing_time(self):
        import json
        from tests.test_market_history import candle,page
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        corpus={'cases':[{'id':'fx-case','axis':'fx','published_date':'2024-01-02','published_at':None,'gold':{'listed_exposures':[]}}]}
        raw=candle(day='2024-01-02');normalized=h.normalize(page([raw]),'KR','005930',False)[0][0]
        observation={**normalized,'response_id':1,'revision':1}
        with patch.object(h,'PATH',Path(tmp.name)/'market.sqlite3'),patch.object(v,'PROGRESS',Path(tmp.name)/'progress.json'),patch.object(event_corpus,'load',return_value=corpus),patch.object(h,'observations',return_value=[observation]),patch.object(h,'source_response',return_value={'payload':json.dumps(page([raw]))}):
            result=v.verify()
            self.assertEqual(result['source_verified_cases'],1)
            self.assertEqual(result['verified_daily_return_cases'],0)
            self.assertEqual(result['complete_coverage_cases'],0)
            saved=json.loads((Path(tmp.name)/'price_checks'/(result['run_id']+'.json')).read_text())
            self.assertEqual(saved['cases'][0]['status'],'exact_publication_time_unknown')
            altered={**raw,'closePrice':'101'}
            with patch.object(h,'source_response',return_value={'payload':json.dumps(page([altered]))}):
                self.assertEqual(v.verify()['source_verified_cases'],0)
            self.assertTrue((Path(tmp.name)/'price_checks'/(result['run_id']+'.json')).exists())

    def test_publication_metadata_does_not_replace_date_only_or_migration_timestamps(self):
        import json
        from datetime import datetime
        data=json.loads((Path(v.__file__).parent/'data/evaluation/publication_metadata_v1.json').read_text())
        corpus={r['id']:r for r in event_corpus.load()['cases']}
        self.assertEqual(len({r['case_id'] for r in data['entries']}),len(data['entries']))
        for row in data['entries']:
            self.assertEqual(row['source_sha256'],corpus[row['case_id']]['source']['sha256'])
            stamp=datetime.fromisoformat(row['published_at'])
            self.assertIsNotNone(stamp.tzinfo);self.assertGreaterEqual(stamp.year,2000)
            self.assertEqual(row['time_quality'],'source_reported_metadata_first_publication_unverified')
        self.assertFalse(any(r['case_id'].startswith('tsmc-') for r in data['entries']))
        self.assertFalse(any(r['case_id']=='ls-bastrop' for r in data['entries']))

    def test_actual_endpoint_fraction_check_is_separate_from_model_estimation(self):
        import json
        from tests.test_market_history import candle,page,calendar
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        corpus={'cases':[{'id':'price-fixture','independent_event_id':'price-fixture','axis':'rates','published_date':'2024-01-09','published_at':'2024-01-09T10:00:00+09:00',
                          'source':{'sha256':'a'*64},'gold':{'listed_exposures':[{'code':'005930'}]}}],'version':'fixture'}
        raw=[candle(day='2024-01-08',close='100'),candle(day='2024-01-09',close='105'),candle(day='2024-01-10',close='106')]
        observations=[{**row,'response_id':1,'revision':i+1} for i,row in enumerate(h.normalize(page(raw),'KR','005930',False)[0])]
        with patch.object(h,'PATH',Path(tmp.name)/'market.sqlite3'),patch.object(v,'PROGRESS',Path(tmp.name)/'progress.json'),patch.object(event_corpus,'load',return_value=corpus),patch.object(h,'observations',return_value=observations),patch.object(h,'source_response',return_value={'payload':json.dumps(page(raw))}):
            with h.db() as db:
                for day in ('2024-01-08','2024-01-09','2024-01-10'):h.save_calendar(db,'KR',day,calendar(day))
            result=v.verify();self.assertEqual(result['verified_daily_return_cases'],1)
            saved=json.loads((Path(tmp.name)/'price_checks'/(result['run_id']+'.json')).read_text())
            entry=saved['cases'][0]
            self.assertAlmostEqual(entry['calculation']['windows'][1]['raw_return'],.05)
            self.assertIsNone(entry['calculation']['windows'][1]['abnormal_return'])
            self.assertIn('inputs',entry)
