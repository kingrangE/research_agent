from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import minute_volume as volume
import market_history as history

class MinuteVolumeTest(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        p=patch.object(history,'PATH',Path(temp.name)/'market.sqlite3');p.start();self.addCleanup(p.stop)
    def candle(self,quantity='1000'):
        return {'timestamp':'2026-11-16T15:00:00+00:00','openPrice':'10','highPrice':'11','lowPrice':'9','closePrice':'10','volume':quantity,'currency':'USD'}
    def test_duplicate_correction_and_reversion_keep_actual_latest_version(self):
        def save(quantity):return volume.store('US','NVDA',{'result':{'candles':[self.candle(quantity)]}},{},'2026-11-16T15:01:00Z')
        self.assertEqual(save('1000'),1);self.assertEqual(save('1000'),0)
        self.assertEqual(save('2000'),1);self.assertEqual(save('1000'),1)
        with history.db() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM minute_bars').fetchone()[0],3)
    def test_invalid_batch_does_not_store_partial_success(self):
        invalid=self.candle('-1')
        with self.assertRaises(ValueError):
            volume.store('US','NVDA',{'result':{'candles':[self.candle(),invalid]}},{},'2026-11-16T15:01:00Z')
        with history.db() as connection:
            volume.prepare(connection)
            self.assertEqual(connection.execute('SELECT count(*) FROM minute_bars').fetchone()[0],0)
    def test_unknown_calendar_or_missing_history_is_not_zero_ratio(self):
        result=volume.compare('US','NVDA','2026-11-16T15:01:00Z')
        self.assertEqual(result['status'],'collecting');self.assertIsNone(result['ratio'])
        self.assertEqual(result['valid_days'],0)
    def test_collector_reuses_injected_client_and_persists_progress(self):
        class Client:
            def request(self,path,params):
                self.params=params
                return {'result':{'candles':[],'nextBefore':None}}
        client=Client()
        self.assertEqual(volume.collect(client)['state'],'source_exhausted')
        self.assertEqual(client.params['interval'],'1m')
        self.assertEqual(volume.collect(client)['state'],'source_exhausted')

    def test_same_session_offset_uses_fifteen_prior_days_and_withholds_unreviewed_ratio(self):
        from datetime import date,timedelta
        now='2026-11-16T15:05:00+00:00';days=[];day=date(2026,11,16)
        while len(days)<16:
            if day.weekday()<5:days.append(day.isoformat())
            day-=timedelta(days=1)
        calendars={d:{'regular_open':True,'regularMarket':{'startTime':d+'T15:00:00+00:00','endTime':d+'T21:00:00+00:00'}} for d in days}
        for d in days:
            candles=[{**self.candle('3000' if d==days[0] else '1000'),'timestamp':d+f'T15:0{i}:00+00:00'} for i in range(1,6)]
            volume.store('US','NVDA',{'result':{'candles':candles}},{},now)
        with patch.object(history,'calendar_snapshot',return_value=calendars):
            result=volume.compare('US','NVDA',now)
        self.assertEqual(result['valid_days'],15)
        self.assertEqual(result['unreviewed_ratio'],3)
        self.assertEqual(result['status'],'review_required')
        self.assertIsNone(result['ratio'])
