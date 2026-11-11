import unittest
from unittest.mock import patch

import stocks


CATALOGUE = {
    "003470": {"code": "003470", "name": "유안타증권", "market": "유가증권", "industry": "금융", "products": "증권 중개"},
    "005930": {"code": "005930", "name": "삼성전자", "market": "유가증권", "industry": "전자", "products": "반도체"},
    "000660": {"code": "000660", "name": "SK하이닉스", "market": "유가증권", "industry": "전자", "products": "메모리 반도체"},
    "000880": {"code": "000880", "name": "한화", "market": "유가증권", "industry": "화학", "products": "화학"},
    "042660": {"code": "042660", "name": "한화오션", "market": "유가증권", "industry": "조선", "products": "선박"},
    "001680": {"code": "001680", "name": "대상", "market": "유가증권", "industry": "식품", "products": "식품"},
    "217500": {"code": "217500", "name": "러셀", "market": "코스닥", "industry": "전자", "products": "반도체 장비"},
    "030200": {"code": "030200", "name": "케이티", "market": "유가증권", "industry": "통신", "products": "통신"},
}
QUOTE = {"itemCode": "003470", "stockName": "유안타증권", "closePrice": "3,935", "fluctuationsRatio": "2.88",
         "compareToPreviousPrice": {"code": "2"}, "localTradedAt": "2026-11-11T15:42:16+09:00", "delayTimeName": "실시간", "marketStatus": "OPEN"}


class StocksTest(unittest.TestCase):
    def setUp(self):
        matcher, names = stocks.compile_names(CATALOGUE)
        for name, value in [("CATALOGUE", dict(CATALOGUE)), ("NAME_MATCHER", matcher), ("NAME_CODES", names), ("QUOTES", {})]:
            patcher = patch.object(stocks, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_krx_parser_preserves_leading_zero_and_alphanumeric_codes(self):
        html = '<table><tr><th>회사명</th><th>시장구분</th><th>종목코드</th><th>업종</th><th>주요제품</th></tr><tr><td>유안타증권</td><td>유가증권</td><td>003470</td><td>금융</td><td>증권 &amp; 신탁</td></tr><tr><td>새회사</td><td>코스닥</td><td>0153R0</td><td>정보</td><td>플랫폼</td></tr></table>'
        result = stocks.parse_catalogue(html)
        self.assertEqual(set(result), {"003470", "0153R0"})
        self.assertEqual(result["003470"]["products"], "증권 & 신탁")
        self.assertRaises(ValueError, stocks.parse_catalogue, "<html>오류 페이지</html>")

    def test_article_example_maps_to_correct_company_and_keeps_reason(self):
        related = stocks.related_stocks("유안타증권, 재산승계신탁 '가온' 출시")
        self.assertEqual([s["code"] for s in related], ["003470"])
        self.assertEqual(related[0]["relation"], "direct")
        self.assertIn("유안타증권", related[0]["reason"])

    def test_longest_name_aliases_and_particles(self):
        self.assertEqual([s["code"] for s in stocks.related_stocks("한화오션, 신규 수주 발표")], ["042660"])
        self.assertEqual([s["code"] for s in stocks.related_stocks("하이닉스가 투자 확대")], ["000660"])
        self.assertEqual(len(stocks.related_stocks("삼성전자와 SK하이닉스, HBM 투자 확대")), 2)
        self.assertEqual(stocks.related_stocks("삼성전자우, 배당 확대"), [])

    def test_ambiguous_names_and_broker_attribution_are_not_company_matches(self):
        for title in ["FDA, 비만약 실명 위험 경고…릴리·노보 대상", "러셀 브랜드, 징역 선고", "케이티 페리 전남편 소식", "시장 반등 전망-한화"]:
            with self.subTest(title=title):
                self.assertEqual(stocks.related_stocks(title), [])
        self.assertEqual([s["code"] for s in stocks.related_stocks("대상, 영업이익 증가")], ["001680"])

    def test_indirect_links_are_labeled_and_broad_macro_has_no_arbitrary_stocks(self):
        related = stocks.related_stocks("HBM 수요 확대, 반도체 업계 주목")
        self.assertEqual({s["code"] for s in related}, {"005930", "000660"})
        self.assertTrue(all(s["relation"] == "value_chain" and s["sources"] for s in related))
        self.assertEqual(stocks.related_stocks("전쟁 우려 속 환율 상승"), [])

    def test_quote_price_change_sign_timestamps_and_malformed_values(self):
        quote = stocks.parse_quote(QUOTE, "003470")
        self.assertEqual((quote["price"], quote["change_percent"]), (3935, 2.88))
        self.assertEqual(quote["traded_at"], QUOTE["localTradedAt"])
        self.assertEqual(quote["delay_label"], "실시간")
        falling = stocks.parse_quote({**QUOTE, "compareToPreviousPrice": {"code": "5"}}, "003470")
        self.assertEqual(falling["change_percent"], -2.88)
        for values in [{"itemCode": "005930"}, {"closePrice": "NaN"}, {"localTradedAt": "2026-11-11T15:00:00"}, {"compareToPreviousPrice": {"code": "invalid"}}]:
            with self.subTest(values=values):
                self.assertRaises(ValueError, stocks.parse_quote, {**QUOTE, **values}, "003470")

    def test_quote_cache_and_failure_keep_timestamped_previous_price(self):
        valid = stocks.parse_quote(QUOTE, "003470")
        with patch("stocks.collect_quote", return_value=valid) as collect, patch("stocks.time.monotonic", return_value=100):
            stocks.get_quotes(["003470"])
            stocks.get_quotes(["003470"])
            collect.assert_called_once_with("003470")
        with patch("stocks.collect_quote", side_effect=TimeoutError), patch("stocks.time.monotonic", return_value=111):
            stale = stocks.get_quotes(["003470"])["003470"]
            missing = stocks.get_quotes(["005930"])["005930"]
        self.assertEqual((stale["status"], stale["price"], stale["traded_at"]), ("stale", 3935, valid["traded_at"]))
        self.assertEqual(missing["status"], "error")
        self.assertNotIn("price", missing)
        self.assertRaises(ValueError, stocks.get_quotes, ["AAAAAA"])

    def test_us_listings_exclude_etfs_tests_preferreds_and_keep_verified_tsm_adr(self):
        nasdaq = 'Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\nNVDA|NVIDIA Corporation - Common Stock|Q|N|N|100|N|N\nFUND|Some AI ETF|Q|N|N|100|Y|N\nTEST|Testing Common Stock|Q|Y|N|100|N|N\nPREF|Example Preferred Stock|Q|N|N|100|N|N\n'
        result = stocks.parse_us_catalogue(nasdaq, "NASDAQ")
        self.assertEqual(set(result), {"NVDA.O"})
        self.assertEqual(result["NVDA.O"]["country"], "US")
        nyse = 'ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\nTSM|Taiwan Semiconductor Manufacturing Company Ltd.|N|TSM|N|100|N|TSM\nORCL|Oracle Corporation Common Stock|N|ORCL|N|100|N|ORCL\n'
        self.assertEqual(set(stocks.parse_us_catalogue(nyse, "NYSE")), {"TSM", "ORCL"})

    def test_us_quote_keeps_usd_decimal_price_timezone_and_regular_session(self):
        values = {**QUOTE, "reutersCode": "NVDA.O", "closePrice": "168.89", "stockName": "엔비디아",
                  "currencyType": {"code": "USD"}, "localTradedAt": "2026-11-10T16:00:00-05:00"}
        result = stocks.parse_quote(values, "NVDA.O")
        self.assertEqual(result["price"], 168.89)
        self.assertEqual(result["currency"], "USD")
        self.assertEqual(result["session"], "미국 정규장")
        self.assertIn("/worldstock/", result["url"])
        self.assertTrue(result["traded_at"].endswith("-05:00"))
        self.assertRaises(ValueError, stocks.parse_quote, {**values, "currencyType": {"code": "KRW"}}, "NVDA.O")

    def test_partial_catalogue_failure_does_not_remove_successful_domestic_listing(self):
        html = '<table><tr><th>회사명</th><th>시장구분</th><th>종목코드</th><th>업종</th><th>주요제품</th></tr><tr><td>유안타증권</td><td>유가증권</td><td>003470</td><td>금융</td><td>증권</td></tr></table>'
        def read(url, *args):
            if url == stocks.CATALOGUE_URL:
                return html
            raise TimeoutError
        with patch("stocks.CATALOGUE", {}), patch("stocks.CATALOGUE_STATUS", {}), patch("stocks.fetch", side_effect=read):
            self.assertFalse(stocks.refresh_catalogue())
            self.assertIn("003470", stocks.CATALOGUE)
            self.assertEqual(stocks.CATALOGUE_STATUS["status"], "partial")
            self.assertEqual(stocks.CATALOGUE_STATUS["sources"]["NASDAQ"], "error")


if __name__ == "__main__":
    unittest.main()
