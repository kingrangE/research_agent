import json
import unittest
from unittest.mock import Mock

import event_facts as f
import trade_events as t
import server


class TradeTest(unittest.TestCase):
    def test_stage_and_scope(self):
        cases=[('미국은 중국산 반도체 추가 관세 50% 제안','planned','proposed'),
               ('미국은 중국산 반도체 관세 시행','execution','in_force_reported'),
               ('미국은 중국산 반도체 관세 유예','deferred','deferred'),
               ('미국은 중국산 반도체 관세 철회','cancelled','withdrawn'),
               ('미국은 태양광 장비 관세 예외','exempt','exempt')]
        for text,stage,legal in cases:
            proposal=t.extract(text)
            self.assertEqual((proposal['stage'],proposal['details']['regulatory_stage']),(stage,legal))
            self.assertEqual(proposal['details']['issuer_country'],'US')
            self.assertIsNone(proposal['details']['combined_tariff_rate'])
        r=t.extract(cases[0][0])['details']
        self.assertEqual(r['origin_country'],'CN');self.assertEqual(r['rates'][0]['basis'],'additional')
        self.assertEqual(t.extract('중국 정부 미국산 반도체 관세 50%')['details']['origin_country'],'US')
        self.assertIsNone(t.extract('삼성전자 반도체 주가 상승'))
        self.assertEqual(t.extract('미국은 중국산 반도체 HTSUS 8542.31.00 관세 시행')['details']['classification_codes'][0]['code'],'8542.31.00')
        self.assertIsNone(t.extract('미국 반도체 관세 50%')['details']['issuer_country'])

    def test_future_exceptions_and_followups_do_not_leak(self):
        early=t.snapshot('2024-08-01T00:00:00+00:00')['measures']
        self.assertEqual([r['id'] for r in early],['s301-semi-proposal-20240514'])
        self.assertEqual(early[0]['followups'],[])
        self.assertFalse(any(r['regulatory_stage']=='exempt' for r in early))
        self.assertEqual(len(t.snapshot('2024-09-18T23:59:00+00:00')['measures']),1)
        later=t.snapshot('2024-09-20T00:00:00+00:00')['measures']
        self.assertEqual(later[0]['followups'],['s301-semi-final-20240918'])
        self.assertEqual(later[1]['status_as_of'],'finalized_not_yet_effective')
        self.assertEqual(later[2]['effective_at'][:10],'2024-01-01')
        current=t.snapshot('2025-06-02T00:00:00+00:00')['measures']
        self.assertEqual(current[1]['status_as_of'],'in_force_by_recorded_schedule')
        self.assertEqual(current[2]['status_as_of'],'expired_by_recorded_schedule')
        self.assertFalse(current[3]['legal_rescission_verified'])
        self.assertRaises(ValueError,t.snapshot,'2025-01-01')

    def test_companies_and_separate_country_products_are_never_assumed(self):
        def article(title):return {'id':'x','url':'https://example.com/x','title':title}
        a=f.extract(article('미국은 중국산 반도체 관세 시행'))
        b=f.extract(article('미국은 한국산 반도체 관세 시행'))
        c=f.extract(article('미국은 중국산 변압기 관세 시행'))
        self.assertEqual(a['axis'],'tariff')
        self.assertEqual(len({p['event_id'] for p in (a,b,c)}),3)
        self.assertEqual(a['details']['company_candidates'],[])
        p=f.extract(article('미국은 중국산 반도체 관세 유예'),'미국은 중국산 반도체 관세를 시행했다.')
        self.assertEqual(p['stage'],'deferred')
        # Matching an official URL without exact evidence does not authenticate a news claim.
        ref=t.REFERENCES['measures'][-1]
        self.assertIsNone(t.official(ref['url'],'다른 문장'))
        official=f.extract({'id':'o','url':ref['url'],'title':'AI diffusion rule update'},ref['quote'])
        self.assertEqual(official['details']['verification'],'agent_curated_official_source')
        self.assertFalse(official['details']['legal_rescission_verified'])

    def test_api_rejects_unzoned_historical_queries(self):
        h=object.__new__(server.Handler);h.respond=Mock();h.path='/api/trade-measures?as_of=2025-01-01';h.do_GET()
        self.assertEqual(h.respond.call_args.args[2],400)
        h.path='/api/trade-measures?as_of=2024-08-01T00:00:00Z';h.do_GET()
        self.assertEqual(len(json.loads(h.respond.call_args.args[0])['measures']),1)
