import copy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,Mock

import event_reactions as r
import market_history as h
import server


def inputs(count=130):
    calendar={};stock=[];benchmark=[];s=b=100.;start=datetime(2025,1,1,tzinfo=timezone.utc)
    k=0
    for offset in range(count*2):
        d=(start+timedelta(days=offset)).date().isoformat()
        if datetime.fromisoformat(d).weekday()>4:
            calendar[d]={'regular_open':False};continue
        x=.001*(1 if k%2 else -1);y=.002+2*x;s*=1+y;b*=1+x
        calendar[d]={'regular_open':True,'integrated':{'regularMarket':{'startTime':d+'T09:00:00+09:00','endTime':d+'T15:30:00+09:00'}}}
        common={'day':d,'volume':'100','completion':'past_day','zero_ohlc':False,'adjusted':False,'revision':k+1,'response_id':k+1,'observed_at':'2026-01-01T00:00:00Z'}
        stock.append({**common,'closePrice':str(s)});benchmark.append({**common,'closePrice':str(b)});k+=1
        if k>=count:break
    day=stock[-3]['day']
    return {'event':{'article_id':'a','event_id':'e','source_key':'s','rule_version':'test','review_status':'pending_review',
                     'published_at':day+'T10:00:00+09:00','available_at':day+'T17:00:00+09:00'},
            'market':'KR','symbol':'005930','benchmark':'KOSPI','basis':'public','adjusted':False,
            'as_of':'2026-01-02T00:00:00Z','calendar':calendar,'stock_prices':stock,'benchmark_prices':benchmark}


class ReactionTest(unittest.TestCase):
    def test_ols_and_hand_calculated_return(self):
        model=r.fit_model([(.002+2*x,x) for x in [.01,-.01]*30])
        self.assertAlmostEqual(model['alpha'],.002);self.assertAlmostEqual(model['beta'],2)
        self.assertEqual(r.fit_model([(0,0)]*60)['status'],'zero_market_variance')
        self.assertEqual(r.fit_model([(0,.01)]*59)['status'],'insufficient_estimation')
        data=inputs();result=r.calculate(data)
        self.assertEqual(result['model']['samples'],120)
        self.assertLess(result['model']['last_day'],result['windows'][1]['end']['day'])
        event=result['windows'][1]
        prices=data['stock_prices'];expected=float(prices[-3]['closePrice'])/float(prices[-4]['closePrice'])-1
        self.assertAlmostEqual(event['raw_return'],expected)
        self.assertAlmostEqual(event['abnormal_return'],0,places=12)
        self.assertTrue(event['includes_pre_event_movement'])
        self.assertEqual(event['volume_change'],0)
        self.assertIsNone(event['turnover_change'])
        changed=copy.deepcopy(data);changed['stock_prices'][-1]['closePrice']='99999999'
        self.assertEqual(r.calculate(changed)['model'],result['model'])

    def test_public_available_after_close_weekend_and_dst(self):
        data=inputs();public=r.calculate(data)
        data['basis']='available';later=r.calculate(data)
        self.assertGreater(later['windows'][1]['end']['day'],public['windows'][1]['end']['day'])
        data=inputs();day=next(d for d,c in data['calendar'].items() if datetime.fromisoformat(d).weekday()==5)
        data['event']['published_at']=day+'T10:00:00+09:00'
        weekend=r.calculate(data)
        self.assertEqual(datetime.fromisoformat(weekend['windows'][1]['end']['day']).weekday(),0)
        # Exact provider session timestamps cross US daylight saving without a fixed UTC open.
        data=inputs(6);data['market']='US';data['calendar']={
            '2025-03-07':{'regular_open':True,'regularMarket':{'startTime':'2025-03-07T09:30:00-05:00','endTime':'2025-03-07T16:00:00-05:00'}},
            '2025-03-08':{'regular_open':False},'2025-03-09':{'regular_open':False},
            '2025-03-10':{'regular_open':True,'regularMarket':{'startTime':'2025-03-10T09:30:00-04:00','endTime':'2025-03-10T16:00:00-04:00'}}}
        data['event']['published_at']='2025-03-10T13:35:00Z'
        self.assertEqual(r.calculate(data)['alignment'],'intraday')
        data['event']['published_at']='2025-03-07T21:00:00Z'
        self.assertEqual(r.calculate(data)['windows'][1]['end']['day'],'2025-03-10')

    def test_incomplete_missing_suspension_split_and_calendar_gaps(self):
        data=inputs(8);day=data['stock_prices'][-3]['day'];data['as_of']=day+'T11:00:00+09:00'
        self.assertIsNone(r.calculate(data)['windows'][1]['raw_return'])
        self.assertEqual(r.calculate(data)['windows'][1]['status'],'window_not_closed')
        data=inputs(8);data['stock_prices'][-3]['completion']='provisional'
        self.assertEqual(r.calculate(data)['windows'][1]['status'],'provisional_price')
        data=inputs(8);data['stock_prices'][-3]['volume']='0'
        self.assertEqual(r.calculate(data)['windows'][1]['status'],'zero_volume_or_suspension')
        data=inputs(8);data['stock_prices'][-3]['closePrice']='10'
        self.assertEqual(r.calculate(data)['windows'][1]['status'],'large_move_corporate_action_unverified')
        data=inputs(8);data['benchmark_prices']=[]
        e=r.calculate(data)['windows'][1];self.assertIsNone(e['abnormal_return']);self.assertIsNone(e['market_return'])
        self.assertIsNotNone(e['raw_return'])
        data=inputs(8);data['event']['published_at']=None
        self.assertEqual(r.calculate(data)['status'],'event_time_unknown')
        data=inputs(8);del data['calendar'][data['stock_prices'][-3]['day']]
        self.assertEqual(r.calculate(data)['status'],'calendar_or_future_session_missing')

    def test_real_calendar_consumer_uses_exchange_holiday_without_rewriting_vendor(self):
        from tests.test_market_history import calendar
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        event={'article_id':'holiday','event_id':'holiday','source_key':'source','rule_version':'fixture','review_status':'fixture','axis':'rates',
               'published_at':'2020-12-25T10:00:00-05:00','available_at':None,'url':'https://example.com'}
        with patch.object(h,'PATH',Path(tmp.name)/'market.sqlite3'),patch.object(r.event_facts,'snapshot',return_value={'proposals':[event]}):
            with h.db() as db:
                for day,opened in [('2020-12-24',True),('2020-12-25',True),('2020-12-26',False),('2020-12-27',False),('2020-12-28',True)]:
                    response=calendar(day,market='US',opened=opened)
                    if opened:response['result']['today']['regularMarket']={'startTime':day+'T09:30:00-05:00','endTime':day+'T16:00:00-05:00'}
                    h.save_calendar(db,'US',day,response)
                original=json.loads(db.execute('SELECT payload FROM calendars WHERE market=? AND day=?',('US','2020-12-25')).fetchone()[0])
            data=r.load_inputs('holiday','US','AAPL',as_of='2021-01-02T00:00:00Z')
            observed=r.calculate(data)
            self.assertEqual(observed['windows'][1]['end']['day'],'2020-12-28')
            self.assertTrue(any(c['day']=='2020-12-25' and c['source_conflict'] for c in observed['windows'][1]['calendar_evidence']))
            event['published_at']='2020-12-24T14:00:00-05:00'
            after_early_close=r.calculate(r.load_inputs('holiday','US','AAPL',as_of='2021-01-02T00:00:00Z'))
            self.assertEqual(after_early_close['windows'][1]['end']['day'],'2020-12-28')
            self.assertEqual(after_early_close['windows'][1]['start']['close'],'2020-12-24T13:00:00-05:00')
            self.assertTrue(original['regular_open'])
            self.assertIsNone(observed['windows'][1]['raw_return'])

    def test_frozen_replay_api_and_missing_run(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        with patch.object(h,'PATH',Path(tmp.name)/'market.sqlite3'),patch.object(r,'load_inputs',return_value=inputs()):
            result=r.run('a','KR','005930');self.assertTrue(r.replay(result['run_id']))
            self.assertEqual(r.run('a','KR','005930')['run_id'],result['run_id'])
            self.assertEqual(len(r.snapshot('a')['runs']),1)
            self.assertFalse(r.snapshot('a')['runs'][0]['calendar_policy_current'])
            self.assertEqual(r.snapshot(run_id=result['run_id'],include_inputs=True)['runs'][0]['inputs'],inputs())
            self.assertRaises(ValueError,r.snapshot,include_inputs=True)
            handler=object.__new__(server.Handler);handler.respond=Mock();handler.path='/api/reactions?article_id=a';handler.do_GET()
            self.assertEqual(json.loads(handler.respond.call_args.args[0])['runs'][0]['run_id'],result['run_id'])
            self.assertRaises(ValueError,r.snapshot,run_id='bad')
        self.assertRaises(ValueError,r.load_inputs,'a','KR','005930',basis='invented')
