import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

import fx_data as fx
import macro_events as m
import event_facts as f
import market_history as h
import server


def response(mid='1400',start='2026-11-16T09:00:00+09:00',end='2026-11-16T09:01:00+09:00',base='USD',quote='KRW'):
    return {'result':{'baseCurrency':base,'quoteCurrency':quote,'rate':mid,'midRate':mid,'basisPoint':'40',
                      'validFrom':start,'validUntil':end}}


class FXTest(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        p=patch.object(h,'PATH',Path(tmp.name)/'fx.sqlite3');p.start();self.addCleanup(p.stop)

    def test_news_amount_forecast_and_inverse(self):
        self.assertIsNone(m.fx('오픈AI에 10억 달러 투자한다'))
        a=m.fx('원/달러 환율 1,400원에서 1,414원으로 상승')['details']
        self.assertEqual((a['won_strength'],a['change_percent']),('weak','1'))
        b=m.fx('KRW/USD 환율 0.001달러에서 0.0009달러로 하락')['details']
        self.assertEqual((b['won_strength'],b['usd_krw_direction']),('weak','up'))
        self.assertEqual(m.fx('달러/원 환율 상승 예상')['stage'],'planned')
        self.assertIsNone(m.fx('원화 약세')['details']['base_currency'])
        self.assertIsNone(m.fx('USD/KRW 및 KRW/USD 환율 상승')['details']['direction'])
        self.assertIsNone(m.fx('원/달러 환율 상승하지 않았다')['details']['won_strength'])
        self.assertIsNone(m.fx('원/달러 환율 전일 대비 10원 상승')['details']['new_value'])
        article={'id':'fx','url':'https://example.com/fx','title':'원/달러 환율 상승 예상'}
        self.assertEqual(f.extract(article,'원/달러 환율 1400원에서 1414원으로 상승했다.')['stage'],'planned')
        unrelated={'id':'other','url':'https://example.com/a','title':'비트코인, 금리·AI주 충격에 흔들'}
        self.assertIsNone(f.extract(unrelated,'연준이 기준금리를 인하했다.')['axis'])

    def test_korean_closing_quotes_and_per_currency_units(self):
        down=m.fx('원·달러 환율, 1.0원 내린 1335.7원 마감')['details']
        self.assertEqual((down['direction'],down['won_strength'],down['new_value']),('down','strong','1335.7'))
        self.assertIsNone(down['change_percent']);self.assertIsNone(down['previous_value'])
        up=m.fx('원·달러 환율, 6.0원 오른 1336.7원 마감')['details']
        self.assertEqual((up['direction'],up['won_strength']),('up','weak'))
        self.assertEqual(m.fx('환율은 1달러당 1,300원으로 하락')['product'],'USD/KRW')
        self.assertEqual(m.fx('환율은 달러당 1,300원으로 하락')['details']['new_value'],'1300')
        self.assertEqual(m.fx('환율은 1원당 0.001달러로 하락')['product'],'KRW/USD')
        self.assertIsNone(m.fx('환율은 100 달러당 130000원으로 하락'))
        self.assertIsNone(m.fx('환율은 0.1달러당 130원으로 하락'))

    def test_exact_windows_source_types_and_spread(self):
        a=fx.normalize(response(),'USD','KRW')
        b=fx.normalize(response('1414','2026-11-16T09:01:00+09:00','2026-11-16T09:02:00+09:00'),'USD','KRW')
        self.assertEqual(fx.compare(a,b)['change_percent'],'1.00')
        self.assertEqual(fx.compare(a,b)['won_strength'],'weak')
        self.assertFalse(fx.compare(a,b)['day_change'])
        self.assertEqual(a['provider_spread_bp'],'40')
        self.assertRaises(ValueError,fx.compare,b,a)
        wrong={**b,'quote_type':'buy'};self.assertRaises(ValueError,fx.compare,a,wrong)
        for invalid in (response('0'),response('-1'),response('NaN'),response(base='KRW',quote='USD')):
            self.assertRaises(ValueError,fx.normalize,invalid,'USD','KRW')
        self.assertRaises(ValueError,fx.normalize,response(),'USD','KRW','2026-11-16T09:02:00+09:00')
        inverse=fx.normalize(response('0.001',base='KRW',quote='USD'),'KRW','USD')
        self.assertEqual(inverse['canonical_usd_krw'],'1000')

    def test_immutable_revisions_and_source_response(self):
        client=Mock()
        for r in (response(),response(),response('1410'),response()):
            client.request.return_value=copy.deepcopy(r);fx.collect(client=client)
        with h.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM fx_values').fetchone()[0],3)
        value=fx.snapshot()['current']
        self.assertEqual(value['mid_rate'],'1400')
        self.assertIsNone(fx.snapshot()['comparison'])
        self.assertIn('/api/v1/exchange-rate?',h.source_response(value['response_id'])['source_url'])
        client.request.return_value=response('1414','2026-11-16T09:01:00+09:00','2026-11-16T09:02:00+09:00')
        self.assertEqual(fx.collect(client=client)['comparison']['change_percent'],'1.00')

    def test_missing_exposure_and_point_in_time(self):
        empty=fx.snapshot(code='005930')
        self.assertIsNone(empty['current']);self.assertIsNone(empty['corporate_impact'])
        self.assertEqual(empty['exposures'],[])
        self.assertEqual(fx.exposures('MSFT.O','2026-11-15'),[])
        claim=fx.exposures('MSFT.O','2026-11-16')[0]
        self.assertIsNone(claim['benefit_direction']);self.assertEqual(claim['currency'],'EUR')
        handler=object.__new__(server.Handler);handler.respond=Mock();handler.path='/api/fx';handler.do_GET()
        self.assertIsNone(json.loads(handler.respond.call_args.args[0])['current'])
        handler.path='/api/fx?base=EUR';handler.do_GET();self.assertEqual(handler.respond.call_args.args[2],400)
