import copy
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import market_history as h
import theme_statistics as t
from tests.test_event_reactions import inputs


def fixture():
    source=inputs(200);points=source['stock_prices'];a=[];b=[];market=[];pa=pb=pm=100
    for i,row in enumerate(points):
        x=(.006 if i%2 else -.006);e=(.001 if i%3 else -.002)
        pa*=1+2*x+e;pb*=1+3*x-e;pm*=1+x
        common={**row,'volume':'10000'}
        a.append({**common,'closePrice':str(pa)});b.append({**common,'closePrice':str(pb)});market.append({**common,'closePrice':str(pm)})
    members=[{'theme':theme,'code':code,'kind':'business','security':{'issuer_id':issuer,'country':'KR'}}
             for theme in ('semiconductor','data_center') for code,issuer in (('005930','samsung'),('000660','hynix'))]
    # A second share class and repeated evidence must not add another company to a theme denominator.
    members.append({'theme':'semiconductor','code':'005935','kind':'business','security':{'issuer_id':'samsung','country':'KR'}})
    return {'as_of':points[-1]['day']+'T20:00:00+09:00','membership_basis':'as_of',
            'business':{'as_of':points[-1]['day'],'version':'fixture','memberships':members,
                        'themes':[{'id':'semiconductor','name':'반도체'},{'id':'data_center','name':'데이터센터'}]},
            'markets':{'KR':{'calendar':source['calendar'],'prices':{'005930':a,'000660':b},'benchmark_prices':market}}}


class ThemeTest(unittest.TestCase):
    def test_returns_market_adjustment_and_company_deduplication(self):
        result=t.calculate(fixture())
        self.assertEqual(result['unique_issuers'],2)
        for row in result['themes']:
            self.assertEqual(row['members'],2);self.assertEqual(row['observed_members'],2)
            self.assertIsNone(row['turnover_change']);self.assertIsNone(row['independent_new_events'])
            for pair in row['pairs']:
                self.assertGreater(pair['raw']['value'],.9)
                self.assertLess(pair['market_adjusted']['value'],-.99)
                self.assertGreaterEqual(pair['models']['005930']['samples'],60)
        self.assertEqual(result['themes'][0]['duplicate_securities_excluded'],['005935'])

    def test_synchronized_dates_missing_and_low_volume(self):
        self.assertEqual(t.correlation({'a':1,'b':2},{'b':3,'c':4},2)['status'],'insufficient_pairs')
        self.assertIsNone(t.correlation({'a':1,'b':1},{'a':2,'b':2},2)['value'])
        data=fixture()
        for p in data['markets']['KR']['prices']['005930']:p['volume']='1'
        result=t.calculate(data)
        self.assertEqual(result['themes'][0]['observed_members'],1)
        self.assertTrue(all(p['raw']['value'] is None for p in result['themes'][0]['pairs']))
        data=fixture();data['markets']['KR']['prices']={}
        row=t.calculate(data)['themes'][0]
        self.assertIsNone(row['up_fraction']);self.assertEqual(row['status'],'missing_latest_prices')

    def test_different_market_sessions_never_form_a_pair_and_models_use_prior_window(self):
        data=fixture();data['business']['memberships'].append({'theme':'semiconductor','code':'NVDA.O','kind':'business','security':{'issuer_id':'nvda','country':'US'}})
        data['markets']['US']={'calendar':{},'prices':{},'benchmark_prices':[]}
        result=t.calculate(data)
        us=next(row for row in result['themes'] if row['market']=='US')
        self.assertEqual(us['pairs'],[])
        first=result['themes'][0]['pairs'][0]['models']
        changed=copy.deepcopy(data)
        for price in changed['markets']['KR']['prices']['005930'][-20:]:price['closePrice']=str(float(price['closePrice'])*1.1)
        self.assertEqual(t.calculate(changed)['themes'][0]['pairs'][0]['models'],first)

    def test_frozen_input_run_and_empty_store(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        with patch.object(h,'PATH',Path(tmp.name)/'market.sqlite3'),patch.object(t,'load_inputs',return_value=fixture()):
            self.assertEqual(t.snapshot()['runs'],[])
            result=t.run();self.assertEqual(t.run()['run_id'],result['run_id'])
            self.assertEqual(t.snapshot()['runs'][0],{**result,'calendar_policy_current':False})
        self.assertRaises(ValueError,t.load_inputs,membership_basis='unsupported')
