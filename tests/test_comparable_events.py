import copy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,Mock

import comparable_events as c
import market_history as h
import event_reactions
import server


def fact(axis='rates',identifier='past'):
    base={'article_id':identifier,'article_title':identifier,'event_id':identifier,'source_key':identifier,
          'rule_version':'test','url':'https://example.com/'+identifier,'review_status':'pending_review',
          'published_at':'2024-01-01T12:00:00Z','available_at':'2024-01-01T12:01:00Z','processed_at':'2024-01-01T12:02:00Z',
          'axis':axis,'event_type':'decision','stage':'announced','product':'policy_rate',
          'details':{'country':'US','currency':'USD','instrument':'policy_rate','direction':'cut','level_unit':'percent','changes':[{'basis_points':'-25'}]}}
    if axis=='fx':base.update(product='USD/KRW',details={'base_currency':'USD','quote_currency':'KRW','unit':'KRW per 1 USD','direction':'up','observation_window':'previous_close','quote_type':'unspecified_news_quote'})
    if axis=='infrastructure':base.update(event_type='facility_investment',product='data_center',region='US',amounts=[{'currency':'USD'}],details={})
    if axis=='tariff':base.update(product='chip',details={'issuer_country':'US','origin_country':'CN','destination_country':'US','regulatory_stage':'in_force_reported','classification_codes':[{'scheme':'HS','code':'8542'}]})
    return base


def run(f):
    return {'article_id':f['article_id'],'event_id':f['event_id'],'source_key':f['source_key'],'event_rule_version':'test',
            'run_id':'a'*64,'market':'US','symbol':'AAPL','basis':'public','as_of':'2024-01-03T00:00:00Z',
            'calendar_policy':h.CALENDAR_POLICY,'windows':[{'name':'event_day','raw_return':-.02,'status':'observed_with_quality_limits',
             'start':{'close':'2024-01-01T21:00:00Z'},'end':{'close':'2024-01-02T21:00:00Z'}}]}


class ComparisonTest(unittest.TestCase):
    def compare(self,facts,runs,query=None,**kwargs):
        return c.compare(query or fact(identifier='query'),facts,runs,'US','AAPL',as_of=kwargs.get('as_of','2025-01-01T00:00:00Z'))

    def test_four_axes_require_exact_scope_and_stage(self):
        for axis in ('rates','fx','tariff','infrastructure'):
            with self.subTest(axis=axis):
                f=fact(axis);q=fact(axis,'query');bad=copy.deepcopy(f);bad['stage']='planned';bad['article_id']='bad';bad['event_id']='bad'
                result=self.compare([f,bad],[run(f),run(bad)],q)
                self.assertEqual(result['summary']['events'],1)
                self.assertTrue(any('stage' in r for r in result['excluded'][0]['reasons']))
                bad=copy.deepcopy(f);bad['event_type']='equity_investment' if axis=='infrastructure' else 'forecast'
                self.assertEqual(self.compare([bad],[run(bad)],q)['summary']['events'],0)

    def test_missing_future_revised_unfinished_and_duplicates_are_not_zero(self):
        f=fact();r=run(f)
        self.assertEqual(self.compare([f],[])['summary']['events'],0)
        for mutate in (lambda x:x.update(as_of='2026-01-01T00:00:00Z'),lambda x:x.update(source_key='changed'),
                       lambda x:x.update(stored_at='2026-01-01T00:00:00Z'),
                       lambda x:x.update(calendar_policy='old'),lambda x:x['windows'][0].update(raw_return=None,status='missing_price'),
                       lambda x:x['windows'][0]['end'].update(close='2026-01-01T00:00:00Z')):
            bad=copy.deepcopy(r);mutate(bad);self.assertEqual(self.compare([f],[bad])['summary']['events'],0)
        twin={**f,'article_id':'copy'};a=self.compare([f,twin],[r,run(twin)])
        self.assertEqual(a['summary']['negative'],1);self.assertEqual(a['summary']['zero'],0)
        self.assertEqual(a['excluded'][0]['reasons'],['duplicate_event'])
        future=copy.deepcopy(f);future['review_history']=[{'applied_at':'2026-01-01T00:00:00Z'}]
        self.assertEqual(self.compare([future],[r])['summary']['events'],0)

    def test_unknown_query_and_rate_tenors_withhold(self):
        q=fact(identifier='query');q['details']['country']=None
        self.assertEqual(self.compare([fact()],[run(fact())],q)['summary']['events'],0)
        q=fact(identifier='query');q['processed_at']='2026-01-01T00:00:00Z'
        self.assertIn('query_not_available_at_cutoff',self.compare([],[],q)['query_unknown_fields'])
        q=fact(identifier='query');q['details'].update(instrument='sovereign_yield',tenor_years=10,observation_window='previous_close')
        f=copy.deepcopy(q);f.update(article_id='past',event_id='past',source_key='past');f['details']['tenor_years']=2
        self.assertEqual(self.compare([f],[run(f)],q)['summary']['events'],0)
        q=fact(identifier='query');f=fact();f['details']['changes']=[{'basis_points':'-50'}]
        self.assertEqual(self.compare([f],[run(f)],q)['summary']['events'],0)

    def test_direction_relaxation_is_separate_and_hand_calculation_matches(self):
        a=fact();b=fact(identifier='other');b['details']['direction']='raise'
        b['details']['changes']=[{'basis_points':'25'}]
        rb=run(b);rb['windows'][0]['raw_return']=.04
        result=self.compare([a,b],[run(a),rb])
        self.assertEqual(result['summary']['median'],-.02)
        self.assertEqual(result['baseline']['positive_frequency_difference'],-.5)
        self.assertEqual(result['summary']['status'],'insufficient_sample')
        self.assertIsNone(result['summary']['cluster_bootstrap_median_95'])

    def test_overlap_clusters_and_bootstrap_are_reproducible(self):
        day=datetime(2024,1,1,tzinfo=timezone.utc)
        rows=[{'start':(day+timedelta(days=i)).isoformat(),'end':(day+timedelta(days=i+1)).isoformat(),'value':(-1)**i*.01} for i in range(30)]
        a=c.summarize(rows);self.assertEqual(a,c.summarize(rows));self.assertEqual(a['nonoverlapping_clusters'],30)
        self.assertIsNotNone(a['cluster_bootstrap_median_95'])
        rows[1]['start']=rows[0]['start'];self.assertEqual(c.summarize(rows)['nonoverlapping_clusters'],29)

    def test_validation(self):
        with self.assertRaises(ValueError):c.compare(fact(),[],[],'US','AAPL',window='5m')
        with self.assertRaises(ValueError):c.snapshot('', 'US','AAPL')

    def test_stored_input_trace_and_http_without_network_or_corpus(self):
        f=fact();q=fact(identifier='query');r=run(f)
        with tempfile.TemporaryDirectory() as directory,patch.object(h,'PATH',Path(directory)/'market.sqlite3'),patch.object(c.event_facts,'snapshot',side_effect=[{'proposals':[q]},{'proposals':[q,f]}]):
            with h.db() as db:
                event_reactions.schema(db)
                db.execute('INSERT INTO reaction_runs VALUES(?,?,?,?,?,?,?,?)',(r['run_id'],'past','US','AAPL','public','{}',h.encode(r),'2024-01-03T00:00:00Z'))
            result=c.snapshot('query','US','AAPL',as_of='2025-01-01T00:00:00Z')
            self.assertEqual(result['summary']['events'],1)
            self.assertTrue(result['included'][0]['input_url'].endswith('&inputs=true'))
        handler=object.__new__(server.Handler);handler.respond=Mock();handler.path='/api/comparable-events?article_id=query&market=US&symbol=AAPL'
        with patch.object(c,'snapshot',return_value=result):handler.do_GET()
        self.assertEqual(json.loads(handler.respond.call_args.args[0])['summary']['median'],-.02)
        handler.path='/api/comparable-events'
        handler.do_GET();self.assertEqual(handler.respond.call_args.args[2],400)


if __name__=='__main__':unittest.main()
