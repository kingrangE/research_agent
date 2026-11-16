import copy
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import market_history as h


def candle(day='2026-11-06', market='KR', close='100'):
    return {'timestamp':day+('T00:00:00+09:00' if market=='KR' else 'T00:00:00-05:00'),
        'openPrice':'100','highPrice':'110','lowPrice':'90','closePrice':close,'volume':'1200',
        'currency':'KRW' if market=='KR' else 'USD'}


def page(rows, cursor=None):
    return {'result':{'candles':rows,'nextBefore':cursor}}


def calendar(day, market='KR', opened=True):
    item={'date':day}
    session={'startTime':day+'T09:00:00+09:00','endTime':day+'T15:30:00+09:00'}
    if market=='KR':
        item['integrated']={'regularMarket':session} if opened else None
    else:
        item['regularMarket']=session if opened else None
    return {'result':{k:copy.deepcopy(item) for k in ('today','previousBusinessDay','nextBusinessDay')}}


class HistoryTest(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        p=patch.object(h,'PATH',Path(temp.name)/'market.sqlite3')
        p.start(); self.addCleanup(p.stop)

    def test_neighbor_calendar_cannot_overwrite_direct_holiday(self):
        direct=calendar('2020-12-25',market='US',opened=False)
        later=calendar('2020-12-27',market='US',opened=False)
        later['result']['previousBusinessDay']=calendar('2020-12-25',market='US',opened=True)['result']['today']
        with h.db() as db:
            h.save_calendar(db,'US','2020-12-25',direct)
            h.save_calendar(db,'US','2020-12-27',later)
            saved=db.execute('SELECT payload FROM calendars WHERE market=? AND day=?',('US','2020-12-25')).fetchone()
        import json
        self.assertFalse(json.loads(saved[0])['regular_open'])

    def test_historical_cutoff_precedes_recent_row_limit(self):
        with h.db() as db:
            rows=[('2020-01-02','100')]+[((datetime(2025,1,1)+timedelta(days=i)).date().isoformat(),'105') for i in range(401)]
            for day,close in rows:
                h.save_page(db,'KR','005930',False,{},page([candle(day=day,close=close)]),'2020-01-01','2026-11-13')
        rows=h.observations('KR','005930',until='2020-01-03')
        self.assertEqual([r['day'] for r in rows],['2020-01-02'])
        self.assertEqual(len(h.observations('KR','005930')),400)
        self.assertRaises(ValueError,h.observations,'KR','005930',until='bad')

    def test_revision_replay_and_unchanged_reimport(self):
        a=page([candle()])
        for response in (a,a,page([candle(close='105')]),a):
            with h.db() as db:
                h.save_page(db,'KR','005930',False,{},response,'2026-11-01','2026-11-10')
        series=h.coverage()['series'][0]
        self.assertEqual((series['days'],series['versions']),(1,3))
        current=h.observations('KR','005930')[0]
        self.assertEqual(current['closePrice'],'100')
        self.assertEqual(current['revision'],3)
        original=h.source_response(current['response_id'])
        self.assertEqual(h.encode(a),original['payload'])
        self.assertIsNone(current['turnover'])

    def test_normalization_market_timezone_and_invalid_input(self):
        rows,_=h.normalize(page([candle(market='US')]),'US','AAPL',True)
        self.assertEqual(rows[0]['day'],'2026-11-06')
        self.assertTrue(rows[0]['adjusted'])
        for change in ({'closePrice':'NaN'},{'closePrice':'1e100'},{'volume':'-1'},{'highPrice':'99'},
                       {'currency':'USD'},{'timestamp':'2026-11-06'},{'volume':True}):
            self.assertRaises(ValueError,h.normalize,page([{**candle(),**change}]),'KR','005930',False)
        self.assertRaises(ValueError,h.normalize,page([candle(),candle()]),'KR','005930',False)

    def test_calendar_distinguishes_holiday_missing_price_and_unknown(self):
        with h.db() as db:
            h.save_page(db,'KR','005930',False,{},page([candle()]),'2026-11-06','2026-11-09')
            h.save_calendar(db,'KR','2026-11-07',calendar('2026-11-07',opened=False))
            h.save_calendar(db,'KR','2026-11-09',calendar('2026-11-09'))
            job={'market':'KR','symbol':'005930','adjusted':False,'since':'2026-11-06','until':'2026-11-09'}
            db.execute('INSERT INTO jobs VALUES(?,?)',('test',h.encode(job)))
        result=h.coverage()['jobs'][0]
        self.assertEqual(result['missing_open_days'],['2026-11-09'])
        self.assertEqual(result['calendar_unknown_days'],2)
        self.assertRaises(ValueError,h.save_calendar,None,'KR','2026-11-08',calendar('2026-11-09'))

    def test_collect_atomic_pages_resume_and_safe_metadata(self):
        class Client:
            def __init__(self): self.calls=[]
            def request(self,path,params):
                self.calls.append((path,dict(params)))
                if path.endswith('/stocks'):
                    return {'result':[{'symbol':'005930','currency':'KRW','market':'KOSPI'}]}
                if 'calendar' in path: return calendar(params['date'])
                if params['before'].startswith('2026-11-09T23'):
                    return page([candle('2026-11-09')],'2026-11-08T00:00:00+09:00')
                return page([candle('2026-11-06')])
        client=Client()
        first=h.collect('KR','005930','2026-11-06','2026-11-09',1,client=client)
        self.assertEqual(first['status'],'partial')
        second=h.collect('KR','005930','2026-11-06','2026-11-09',1,client=client)
        self.assertEqual(second['status'],'complete')
        self.assertEqual(len(h.observations('KR','005930')),2)
        self.assertEqual(h.coverage()['series'][0]['security']['market'],'KOSPI')

    def test_repeated_cursor_does_not_commit_bad_page(self):
        class Client:
            def request(self,path,params):
                if path.endswith('/stocks'): return {'result':[{'symbol':'AAPL','currency':'USD','market':'NASDAQ'}]}
                return page([candle(market='US')],params['before'])
        job=h.collect('US','AAPL','2026-11-06','2026-11-09',client=Client())
        self.assertEqual(job['status'],'error')
        self.assertIn('커서 진행',job['error'])
        self.assertEqual(h.observations('US','AAPL'),[])

    def test_auth_redacts_errors_and_reuses_token(self):
        client=h.Toss()
        calls=[]
        def open_request(request,timeout):
            calls.append(request)
            if request.full_url.endswith('/oauth2/token'):
                return BytesIO(h.encode({'access_token':'private-token','token_type':'Bearer','expires_in':3600}).encode())
            return BytesIO(b'{"result":{}}')
        with patch.dict('os.environ',{'TOSS_CLIENT_ID':'private-id','TOSS_CLIENT_SECRET':'private-secret'}),patch.object(client,'open',side_effect=open_request),patch('market_history.time.sleep'):
            client.request('/api/v1/stocks',{'symbols':'005930'})
            client.request('/api/v1/stocks',{'symbols':'AAPL'})
        self.assertEqual(len(calls),3)
        self.assertIn(b'client_secret=private-secret',calls[0].data)
        self.assertTrue(all('private-secret' not in r.full_url for r in calls))
        self.assertEqual(calls[1].get_header('Authorization'),'Bearer private-token')
        client.token='private-token';client.expires=float('inf')
        with patch.object(client,'open',side_effect=HTTPError('https://x',403,'private-secret',{},BytesIO(b'private-secret'))),patch('market_history.time.sleep'):
            with self.assertRaises(ValueError) as error: client.request('/api/v1/candles')
            self.assertNotIn('private-secret',str(error.exception))
        self.assertRaises(ValueError,client.request,'/api/v1/orders')
        self.assertRaises(ValueError,h.NoRedirect().redirect_request,None,None,302,'',{},'https://evil')

    def test_rate_limit_records_deadline_and_does_not_repeat_requests(self):
        class Client:
            def __init__(self):self.calls=0
            def request(self,path,params):self.calls+=1;raise h.RateLimited(60)
        client=Client()
        first=h.collect('KR','005930','2026-11-06','2026-11-09',client=client)
        second=h.collect('KR','005930','2026-11-06','2026-11-09',client=client)
        self.assertEqual(client.calls,1)
        self.assertEqual(first,second)
        self.assertGreater(first['retry_after'],0)

    def test_invalidated_token_is_cleared_for_the_next_worker_attempt(self):
        client=h.Toss();client.token='private-token';client.expires=float('inf')
        with patch.object(client,'open',side_effect=HTTPError('https://x',401,'private',{},BytesIO(b'private'))),patch('market_history.time.sleep'):
            with self.assertRaises(ValueError):client.request('/api/v1/stocks',{'symbols':'AAPL'})
        self.assertIsNone(client.token);self.assertEqual(client.expires,0)

    def test_saved_reaction_price_vintage_detects_a_correction(self):
        with h.db() as db:h.save_page(db,'KR','005930',False,{},page([candle()]),'2026-11-01','2026-11-10')
        old=h.observations('KR','005930');self.assertTrue(h.revisions_current('KR','005930',old))
        corrected=candle();corrected['closePrice']='101';corrected['highPrice']='102'
        with h.db() as db:h.save_page(db,'KR','005930',False,{},page([corrected]),'2026-11-01','2026-11-10')
        self.assertFalse(h.revisions_current('KR','005930',old))
        self.assertIsNone(h.revisions_current('KR','005930',[]))

    def test_history_http_routes_only_read_saved_data_and_validate_queries(self):
        from unittest.mock import Mock
        import server
        with h.db() as db:
            h.save_page(db,'KR','005930',False,{},page([candle()]),'2026-11-01','2026-11-10')
        handler=object.__new__(server.Handler)
        handler.respond=Mock()
        with patch.object(h.Toss,'request',side_effect=AssertionError('network on GET')):
            handler.path='/api/history?market=KR&symbol=005930'
            handler.do_GET()
            import json
            body=json.loads(handler.respond.call_args.args[0])
            self.assertEqual(len(body['observations']),1)
            handler.path='/api/history?response_id=1'
            handler.do_GET()
            self.assertIn('payload',json.loads(handler.respond.call_args.args[0]))
            for query in ('market=OTHER&symbol=AAPL','market=US','market=KR&symbol=005930&adjusted=bad','response_id=bad'):
                handler.path='/api/history?'+query
                handler.do_GET()
                self.assertEqual(handler.respond.call_args.args[2],400)
        self.assertRaises(ValueError,h.identity,'US','KOSPI')


if __name__=='__main__': unittest.main()
