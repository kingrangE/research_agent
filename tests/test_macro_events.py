import unittest
from unittest.mock import Mock
import json

import macro_events as m
import event_facts as f
import server


class RateTest(unittest.TestCase):
    def test_levels_and_changes_have_different_units(self):
        a=m.rates('한국은행 기준금리 25bp 인하 결정')
        b=m.rates('한국은행 기준금리 0.25%p 인하 결정')
        self.assertEqual(a['details']['changes'][0]['basis_points'],b['details']['changes'][0]['basis_points'])
        level=m.rates('한은 기준금리 0.25% 동결')
        self.assertEqual(level['details']['new_level'],['0.25'])
        self.assertEqual(level['details']['changes'],[])
        self.assertIsNone(a['details']['surprise_bp'])
        self.assertEqual(str(m.number('-25')),'-25')

    def test_forecast_hold_denial_and_market_yield(self):
        self.assertEqual(m.rates('한은 기준금리 인하 예상')['stage'],'planned')
        self.assertEqual(m.rates('한은 기준금리 동결 결정')['details']['direction'],'hold')
        self.assertEqual(m.rates('한은 기준금리 인하하지 않았다')['stage'],'denied')
        no_expectation=m.rates('연준 금리 인하 가능성 없다')
        self.assertEqual(no_expectation['stage'],'planned')
        self.assertIsNone(no_expectation['details']['direction'])
        market=m.rates('미국 국채 10년물 금리 4.25%로 하락')
        self.assertEqual(market['details']['tenor_years'],10)
        self.assertEqual(market['details']['direction'],'down')
        self.assertIsNone(m.rates('개인투자용국채 만기 수익률 162% 청약'))
        self.assertIsNone(m.rates('한국은행과 미국 연준 기준금리 비교')['details']['country'])
        self.assertIsNone(m.rates('미국 국채 2년물과 10년물 금리 비교')['details']['tenor_years'])

    def test_range_fraction_and_conflicting_numbers(self):
        self.assertEqual(m.rates('연준 기준금리 4.25~4.50%로 인하')['details']['new_level'],['4.25','4.5'])
        english=m.rates('Federal Reserve lower federal funds rate by 1/4 percentage point to 4-1/2 to 4-3/4 percent')
        self.assertEqual(english['details']['new_level'],['4.5','4.75'])
        self.assertEqual(english['details']['changes'][0]['basis_points'],'-25')
        conflicting=m.rates('한은 기준금리 3.50%에서 3.25%로 0.50%p 인하')
        self.assertTrue(conflicting['details']['numeric_conflict'])
        self.assertEqual(conflicting['stage'],'unknown')

    def test_official_proof_is_not_inferred_from_news_keywords(self):
        ref=m.REFERENCES['decisions'][0]
        self.assertIsNone(m.official('https://news.example/fed',ref['quote']))
        self.assertIsNone(m.official(ref['url'].replace('https:','http:'),ref['quote']))
        article={'id':'official','url':ref['url'],'title':'Federal Reserve issues FOMC statement'}
        proposal=f.extract(article,ref['quote'])
        self.assertEqual(proposal['details']['verification'],'official_registry')
        self.assertEqual(proposal['details']['published_at'],ref['published_at'])
        self.assertIsNone(proposal['details']['effective_at'])
        forecast=f.extract({'id':'news','url':'https://example.com/a','title':'한은 기준금리 인하 예상'},'한국은행 기준금리 3.5%에서 3.25%로 인하 결정.')
        self.assertEqual(forecast['stage'],'planned')
        self.assertEqual(forecast['details']['verification'],'official_unverified')
        handler=object.__new__(server.Handler);handler.respond=Mock();handler.path='/api/rate-decisions';handler.do_GET()
        self.assertEqual(len(json.loads(handler.respond.call_args.args[0])['decisions']),4)

    def test_matching_values_does_not_turn_forecast_into_official_confirmation(self):
        details=m.rates('연준은 2024년 11월 7일 기준금리를 4.50~4.75%로 25bp 인하했다')['details']
        matched=m.compare_reference(details,'2024-11-07T20:00:00+00:00')
        self.assertEqual(matched['reference_id'],'fed-20241107')
        self.assertEqual(m.compare_reference(details,'2024-11-07T18:00:00+00:00')['verification'],'official_unverified')
        self.assertEqual(m.compare_reference(details,'2024-11-07T20:00:00+00:00',forecast=True)['verification'],'official_unverified')
