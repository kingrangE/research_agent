from datetime import datetime
import unittest
from unittest.mock import patch

import relations
from tests_catalogue import catalogue_for_research


class RelatedResearchTest(unittest.TestCase):
    def test_legal_identity_is_exact_sourced_and_not_a_group_or_brand_alias(self):
        self.assertEqual(relations.legal_identity('Alphabet, Inc.','2026-11-11'),'alphabet_inc')
        self.assertEqual(relations.legal_identity('google l.l.c.','2026-11-11'),'google_llc')
        self.assertEqual(relations.legal_identity('Amazon Web Services Inc.','2026-11-11'),'amazon_web_services_inc')
        self.assertNotEqual(relations.legal_identity('Google LLC','2026-11-11'),relations.legal_identity('Alphabet Inc.','2026-11-11'))
        for name in ('Google','AWS','Amazon','미등록 법인','',None):
            self.assertIsNone(relations.legal_identity(name,'2026-11-11'))
        self.assertIsNone(relations.legal_identity('Google LLC','2025-03-17'))
        self.assertIsNone(relations.legal_identity('Amazon Web Services EMEA SARL','2026-10-28'))
        self.assertIsNone(relations.legal_identity('Google LLC','invalid-date'))
        self.assertEqual(relations.legal_identity('Google','2026-11-11',source='Google LLC와 공급 계약을 체결했다.'),'google_llc')
        self.assertIsNone(relations.legal_identity('AWS','2026-11-11',source='Amazon Web Services, Inc.를 AWS라고 지칭했다.'))
        self.assertIsNone(relations.legal_identity('Amazon','2026-11-11',source='Amazon.com, Inc.와 Amazon Web Services, Inc.를 함께 언급했다.'))

    def test_legal_identity_abstains_when_ambiguous_or_without_sources(self):
        base={'id':'a','names':['Example LLC'],'sources':['alphabet_legal_entities']}
        for records in ([base,{**base,'id':'b'}],[{**base,'sources':[]}]):
            with patch.dict(relations.KNOWLEDGE,{'legal_entities':records}):
                self.assertIsNone(relations.legal_identity('Example LLC','2026-11-11'))

    def test_new_legal_sources_do_not_refresh_old_source_review_dates(self):
        self.assertEqual(relations.source_records(['krx'],'2026-11-15')[0]['checked_on'],'2026-11-11')
        self.assertEqual(relations.source_records(['alphabet_legal_entities'],'2026-11-15')[0]['checked_on'],'2026-11-15')
        ids=[e['id'] for e in relations.KNOWLEDGE['legal_entities']]
        self.assertEqual(len(ids),len(set(ids)))
        for entity in relations.KNOWLEDGE['legal_entities']:
            self.assertTrue(entity['names'] and entity['sources'])
            self.assertTrue(all(s in relations.SOURCES for s in entity['sources']))

    def setUp(self):
        self.catalogue = catalogue_for_research()

    def infer(self, title, as_of="2026-11-11", direct=None):
        return relations.infer(title, self.catalogue, direct or [], as_of)

    def test_ai_unicorn_policy_returns_both_markets_and_software_without_claiming_recipient(self):
        candidates, analysis = self.infer("정부, AI 유니콘을 키운다")
        self.assertIn("policy", {e["id"] for e in analysis["events"]})
        self.assertEqual({c["country"] for c in candidates}, {"KR", "US"})
        self.assertIn("035420", {c["code"] for c in candidates})
        self.assertIn("018260", {c["code"] for c in candidates})
        self.assertTrue(all(c["relation"] == "theme" for c in candidates))
        self.assertTrue(all("지원 대상" in c["mechanism"] and c["impact"] == "영향 미정" for c in candidates))

    def test_specific_chip_scope_does_not_expand_to_unrelated_software_roles(self):
        chip_roles={'memory','foundry','packaging','accelerator'}
        profiles={p['code']:p for p in relations.KNOWLEDGE['profiles']}
        for title in ("'대체불가' 삼전닉스 AI 반도체…세계 4위 수출대국 견인",
                      'AI GPU 수요 확대', '정부, AI 반도체 유니콘 육성',
                      'AI semiconductor 수요 확대', 'AI TPU 공급 계약'):
            with self.subTest(title=title):
                rows,_=self.infer(title)
                self.assertTrue(rows)
                self.assertIn('005930',{r['code'] for r in rows})
                self.assertIn('000660',{r['code'] for r in rows})
                self.assertTrue(all(set(profiles[r['code']]['roles']) & chip_roles for r in rows))
                self.assertTrue(all(r['code'] not in {'035420','017670','018260','MSFT.O'} for r in rows))
                self.assertTrue(all('반도체' in r['path'] for r in rows))
                self.assertTrue(all(r['impact']=='영향 미정' and r['sources'] for r in rows))

    def test_specific_product_scope_preserves_direct_and_documented_connections(self):
        direct=[{**self.catalogue['035420'],'reason':'제목의 NAVER 직접 언급'}]
        rows,_=self.infer('NAVER, AI 반도체 공급 계약',direct=direct)
        self.assertEqual(rows[0]['code'],'035420')
        self.assertEqual(rows[0]['relation'],'direct')
        rows,_=self.infer('Anthropic AI 반도체 공급 계약')
        self.assertTrue(any(r['relation']=='documented' and r['code']=='AMZN.O' for r in rows))

    def test_tsmc_investment_keeps_direct_issuer_and_expands_to_models_and_chips(self):
        title = "TSMC, 오픈 AI·엔트로픽에 10억달러 투자"
        candidates, analysis = self.infer(title)
        codes = {c["code"] for c in candidates}
        self.assertIn("TSM", codes)
        self.assertIn("000660", codes)
        self.assertTrue(codes & {"MSFT.O", "GOOGL.O", "018260"})
        self.assertTrue(codes & {"NVDA.O", "AVGO.O", "AMD.O"})
        self.assertTrue(any(c["relation"] == "documented" for c in candidates))
        self.assertFalse(any(c["name"] in ("OpenAI", "Anthropic") for c in candidates))
        self.assertTrue(any("투자금" in check for check in analysis["checks"]))
        self.assertTrue(all(c["impact"] == "영향 미정" for c in candidates))

    def test_direct_company_does_not_prevent_related_company_expansion(self):
        direct = [{**self.catalogue["NVDA.O"], "reason": "제목에서 엔비디아 언급"}]
        candidates, _ = self.infer("엔비디아, AI GPU 수요 확대에 투자 늘려", direct=direct)
        self.assertEqual(candidates[0]["code"], "NVDA.O")
        self.assertIn("000660", {c["code"] for c in candidates})
        self.assertEqual(len(candidates), len({c["code"] for c in candidates}))

    def test_future_relationship_cannot_be_used_in_a_historical_article(self):
        candidates, _ = self.infer("OpenAI 기업용 AI 서비스 도입 확대", as_of="2025-01-01")
        self.assertFalse(any(c["relation"] == "documented" and c["code"] == "018260" for c in candidates))
        for candidate in candidates:
            self.assertTrue(all(not s["published_on"] or s["published_on"] <= "2025-01-01" for s in candidate["sources"]))

    def test_denial_and_plan_never_become_confirmed_revenue_or_positive_calls(self):
        candidates, analysis = self.infer("OpenAI, AI GPU 투자 계약 체결설 부인")
        self.assertTrue(analysis["disputed"])
        self.assertTrue(all(c["impact"] == "영향 미정" and "부인·취소" in c["required_checks"][0] for c in candidates))
        _, plan = self.infer("OpenAI, AI 데이터센터 증설 검토")
        self.assertEqual(plan["event_state"], "계획·전망 포함")

    def test_private_entities_are_metadata_without_fake_tradeable_instruments(self):
        candidates, analysis = self.infer("OpenAI와 Anthropic, AI 투자 확대")
        private = [e for e in analysis["entities"] if e["name"] in ("OpenAI", "Anthropic")]
        self.assertTrue(all(e["code"] is None and e["listing_note"] for e in private))
        self.assertTrue(all(c["code"] in self.catalogue for c in candidates))

    def test_non_business_homonyms_and_missing_entities_abstain(self):
        for title in ["아마존강 열대우림 보호 계획", "클로드 모네 전시 공개", "알파벳 쓰기를 배우는 아이들", "AI라는 영화의 배우 소식", "전쟁 우려 속 환율 상승"]:
            with self.subTest(title=title):
                candidates, _ = self.infer(title)
                self.assertEqual(candidates, [])

    def test_missing_listing_never_creates_an_unverified_stock(self):
        candidates, _ = relations.infer("AI 유니콘 육성 정책 발표", {}, [], "2026-11-11")
        self.assertEqual(candidates, [])

    def test_all_inferred_connections_have_traceable_sources_and_no_fake_materiality(self):
        for title in ["AI 유니콘 육성", "TSMC OpenAI Anthropic 투자", "HBM 수요 증가", "LLM API 가격 인하", "OpenAI AI 칩 수출 규제"]:
            for candidate in self.infer(title)[0]:
                with self.subTest(title=title, code=candidate["code"]):
                    self.assertTrue(candidate["sources"])
                    self.assertTrue(candidate["path"])
                    self.assertTrue(candidate["required_checks"])
                    self.assertIn("미산정", candidate["materiality"])
                    self.assertTrue(all(s["url"].startswith("https://") and s["checked_on"] for s in candidate["sources"]))

    def test_knowledge_integrity(self):
        for source in relations.SOURCES.values():
            self.assertTrue(source["url"].startswith("https://"))
            if source["published_on"]:
                datetime.fromisoformat(source["published_on"])
        for relationship in relations.KNOWLEDGE["relationships"]:
            self.assertTrue(all(s in relations.SOURCES for s in relationship["sources"]))
        for issuer in relations.KNOWLEDGE.get('issuer_aliases',[]):
            self.assertTrue(issuer['issuer'] and issuer['aliases'] and issuer['sources'])
            self.assertEqual(len(issuer['sources']),len(set(issuer['sources'])))
            self.assertTrue(all(s in relations.SOURCES for s in issuer['sources']))

    def test_investment_type_distinguishes_equity_capex_and_unknown_use(self):
        def events(title):
            return {e["id"] for e in relations.context(title)["events"]}
        self.assertIn("equity", events("TSMC, OpenAI에 10억달러 투자"))
        self.assertIn("capacity", events("삼성전자, AI 데이터센터에 투자"))
        self.assertNotIn("equity", events("삼성전자, AI 데이터센터에 투자"))
        self.assertIn("investment", events("AI 기업 투자 확대 계획"))
        self.assertNotIn("equity", events("AI investment expansion"))
        self.assertNotIn("investment", events("NVIDIA investigation"))


if __name__ == "__main__":
    unittest.main()
