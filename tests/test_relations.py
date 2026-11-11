from datetime import datetime
import unittest

import relations
from tests_catalogue import catalogue_for_research


class RelatedResearchTest(unittest.TestCase):
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
