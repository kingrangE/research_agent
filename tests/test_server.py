import copy
from pathlib import Path
import tempfile
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

import server


class DashboardTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        patcher = patch('archive.PATH',Path(temp.name)/'news.sqlite3')
        patcher.start()
        self.addCleanup(patcher.stop)

    def article(self, title="환율 상승과 반도체 실적", **values):
        return {"id": "test", "title": title, "url": "https://example.com/1", "source": "테스트", "source_id": "finance",
                "kind": "news", "category": "증권", "published_at": "2026-11-11T00:00:00+00:00", "copies": 1, **values}

    def test_feed_skips_unsafe_links_and_preserves_missing_date(self):
        xml = b'<rss><channel><item><title>Safe &amp; sound</title><link>https://example.com/a</link><pubDate>not-a-date</pubDate></item><item><title>Bad</title><link>javascript:alert(1)</link></item></channel></rss>'
        articles = server.parse_feed(xml, server.SOURCES[0])
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["title"], "Safe & sound")
        self.assertIsNone(articles[0]["published_at"])
        self.assertRaises(ValueError, server.parse_feed, b"<rss/>", server.SOURCES[0])

    def test_duplicates_do_not_multiply_attention_or_modify_input(self):
        first = self.article()
        second = self.article(url="https://example.com/2")
        result = server.deduplicate([first, second, self.article()])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["copies"], 3)
        self.assertEqual(first["copies"], 1)

    def test_multitheme_classification_and_age_score(self):
        now = datetime(2026, 11, 11, 0, 0, tzinfo=timezone.utc)
        recent = server.classify(self.article(), now)
        old = server.classify(self.article(published_at="2026-11-08T00:00:00+00:00"), now)
        self.assertEqual({t["id"] for t in recent["themes"]}, {"macro", "semiconductor", "earnings"})
        self.assertGreater(recent["score"], old["score"])
        unknown = server.classify(self.article(published_at=None), now)
        self.assertEqual(unknown["score_parts"]["freshness"], 0)
        self.assertFalse(server.classify(self.article(title="Retail market update"), now)["themes"])
        amount = server.classify(self.article(title="TSMC, AI 기업에 10억달러 투자"), now)
        self.assertNotIn("macro", {t["id"] for t in amount["themes"]})
        currency = server.classify(self.article(title="달러 강세에 환율 상승"), now)
        self.assertIn("macro", {t["id"] for t in currency["themes"]})

    def test_freshness_curve_and_boundaries(self):
        now = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
        for minutes, expected in [(-10, 50), (0, 50), (30, 37.5), (59, 25.4),
                                  (60, 25), (61, 25), (90, 24.5), (120, 24),
                                  (1560, 0), (1620, 0)]:
            with self.subTest(minutes=minutes):
                article = self.article(published_at=(now - timedelta(minutes=minutes)).isoformat())
                result = server.classify(article, now)
                self.assertEqual(result["score_parts"]["freshness"], expected)
                self.assertEqual(result["score"], expected)
        self.assertEqual(server.classify(self.article(published_at=None), now)["score"], 0)

    def test_topics_and_material_types_do_not_change_score(self):
        now = datetime(2026, 11, 11, 0, 0, tzinfo=timezone.utc)
        generic = server.classify(self.article(title="일반 기사"), now)
        themed = server.classify(self.article(title="중동 전쟁 유가 환율 반도체 실적 급등"), now)
        self.assertEqual(generic["score"], themed["score"])
        self.assertNotIn("relevance", themed["score_parts"])
        report = server.classify(self.article(kind="report"), now)
        self.assertEqual(report["score"], generic["score"])
        self.assertEqual(report["score_parts"], {"freshness": 50})

    def test_polling_interval_accounts_for_collection_duration(self):
        with patch("server.refresh") as refresh, patch("server.time.monotonic", side_effect=[100, 105]), \
             patch("server.time.sleep", side_effect=InterruptedError) as sleep:
            with self.assertRaises(InterruptedError):
                server.collector()
        refresh.assert_called_once()
        sleep.assert_called_once_with(25)

    def test_collection_failure_retains_last_success_and_exposes_status(self):
        previous = copy.deepcopy(server.STATE)
        self.addCleanup(lambda: server.STATE.update(previous))
        server.STATE.update(articles=[self.article()], sources=[{"id": "finance", "last_success": "2026-11-10T00:00:00Z"}])
        with patch("server.collect_source", side_effect=TimeoutError):
            server.refresh()
        self.assertEqual(len(server.STATE["articles"]), 1)
        status = server.STATE["sources"][0]
        self.assertEqual(status["status"], "stale")
        self.assertEqual(status["last_success"], "2026-11-10T00:00:00Z")
        self.assertFalse(server.STATE["collecting"])
        self.assertEqual(server.STATE["sources"][1]["status"], "error")

    def test_demo_is_separate_and_cannot_link_to_fabricated_news(self):
        demo = server.demo_snapshot()
        self.assertEqual(len(demo["articles"]), 13)
        self.assertGreater(demo["raw_count"], len(demo["articles"]))
        self.assertTrue(all(a["title"].startswith("[가상]") and a["url"] is None for a in demo["articles"]))
        self.assertTrue(any(a["kind"] == "report" for a in demo["articles"]))

    def test_feed_does_not_sample_only_the_first_sixty_articles(self):
        xml='<rss><channel>'+''.join(f'<item><title>자료 {i}</title><link>https://example.com/{i}</link><description>원문 설명 {i}</description></item>' for i in range(75))+'</channel></rss>'
        rows=server.parse_feed(xml.encode(),server.SOURCES[0])
        self.assertEqual(len(rows),75)
        self.assertIn('원문 설명 74',rows[-1]['feed_xml'])

    def test_archive_failure_does_not_discard_fresh_feed_data(self):
        previous=copy.deepcopy(server.STATE)
        self.addCleanup(lambda:server.STATE.update(previous))
        with patch('server.collect_source',side_effect=lambda source:[self.article(source_id=source['id'])]),patch('server.archive.store',side_effect=OSError):
            server.refresh()
        self.assertEqual(len(server.STATE['articles']),3)
        self.assertTrue(all(s['status']=='ok' for s in server.STATE['sources']))
        self.assertIn('보관 실패',server.STATE['archive_error'])


if __name__ == "__main__":
    unittest.main()
