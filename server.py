"""맥락 prototype: public-feed collection and an explainable reading queue."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

import stocks
import relations
import intelligence
import archive
from analysis_store import epoch

ROOT = Path(__file__).resolve().parent
INTERVAL = 30
SOURCES = [
    {"id": "finance", "name": "한국경제 · 증권", "url": "https://www.hankyung.com/feed/finance", "category": "증권"},
    {"id": "economy", "name": "한국경제 · 경제", "url": "https://www.hankyung.com/feed/economy", "category": "경제"},
    {"id": "international", "name": "한국경제 · 국제", "url": "https://www.hankyung.com/feed/international", "category": "국제"},
]
THEMES = [
    {"id": "macro", "name": "환율·금리", "keywords": ["환율", "달러", "금리", "연준", "인플레이션", "인플레", "물가", "국채", "통화", "Fed", "CPI"], "question": "환율과 금리 변화가 기업의 비용·실적 전망에 어떤 영향을 주는지 확인해 보세요.", "links": ["수출 기업", "수입 원가", "외국인 수급"]},
    {"id": "geopolitics", "name": "국제 정세", "keywords": ["전쟁", "중동", "이란", "러시아", "우크라", "관세", "제재", "분쟁", "미중", "트럼프", "수출 규제"], "question": "정책·분쟁의 실제 변화와 에너지·공급망 관련 자료를 함께 확인해 보세요.", "links": ["공급망", "에너지", "수출입 정책"]},
    {"id": "semiconductor", "name": "반도체·AI", "keywords": ["반도체", "삼성전자", "하이닉스", "엔비디아", "HBM", "인공지능", "데이터센터", "AI", "젠슨"], "question": "수요·투자 계획이 실제 주문과 실적으로 이어지는지 구분해서 읽어 보세요.", "links": ["설비 투자", "메모리 수요", "전력 인프라"]},
    {"id": "energy", "name": "에너지·원자재", "keywords": ["유가", "원유", "석유", "천연가스", "정유", "전력", "원전", "발전", "에너지", "금값"], "question": "원자재 가격 변화와 비용을 부담하거나 수혜를 보는 산업을 함께 살펴보세요.", "links": ["운송 비용", "정유·화학", "전력 공급"]},
    {"id": "earnings", "name": "기업·실적", "keywords": ["실적", "영업익", "순이익", "매출", "수주", "목표가", "목표주가", "배당", "자사주", "흑자", "적자"], "question": "실적의 일회성 요인과 지속 가능한 변화를 나누고 원문 수치를 확인해 보세요.", "links": ["이익 전망", "주주 환원", "증권사 관점"]},
    {"id": "themes", "name": "종목·테마", "keywords": ["바이오", "모더나", "백신", "로봇", "배터리", "방산", "조선", "테마", "급등", "상한가", "주도주", "ETF"], "question": "단기적인 관심 증가인지 사업의 변화인지 관련 자료를 비교해 보세요.", "links": ["관련 종목", "거래 관심", "사업 변화"]},
]
STATE = {"articles": [], "sources": [], "updated_at": None, "collecting": True}
LOCK = threading.Lock()


def iso_now():
    return datetime.now(timezone.utc).isoformat()


def safe_url(value):
    try:
        parsed = urlsplit(value)
        parsed.port
        return value if parsed.scheme in ('https','http') and parsed.hostname and not (parsed.username or parsed.password) else None
    except (ValueError,TypeError):
        return None


def parse_feed(body, source):
    root = ET.fromstring(body)
    articles = []
    for item in root.findall(".//item"):
        title = " ".join((item.findtext("title") or "").split())
        url = safe_url((item.findtext("link") or "").strip())
        if not title or not url:
            continue
        try:
            published = parsedate_to_datetime(item.findtext("pubDate") or "")
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            published = published.isoformat()
        except (TypeError, ValueError, OverflowError):
            published = None
        articles.append({"id": sha256(url.encode()).hexdigest()[:16], "title": title, "url": url,
                         "source": source["name"], "source_id": source["id"], "category": source["category"],
                         "kind": "news", "feed_xml": ET.tostring(item, encoding="unicode"), "published_at": published, "collected_at": iso_now(), "copies": 1})
    if not articles:
        raise ValueError("읽을 수 있는 기사 항목이 없습니다")
    return articles


def collect_source(source):
    request = Request(source["url"], headers={"User-Agent": "MaekrakPrototype/0.1 (public RSS reader)", "Accept": "application/rss+xml, application/xml, text/xml"})
    with urlopen(request, timeout=15) as response:
        body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise ValueError("피드 크기 제한 초과")
        return parse_feed(body, source)


def deduplicate(articles):
    result = {}
    for article in sorted(articles,key=lambda a: epoch(a.get('published_at')),reverse=True):
        if article['url'] in result:
            result[article['url']]['copies'] += 1
        else:
            result[article['url']] = dict(article)
    return list(result.values())


def classify(article, now=None, reading=None):
    now = now or datetime.now(timezone.utc)
    matches = []
    for theme in THEMES:
        words = [word for word in theme["keywords"] if (re.search(r"(?<![a-z])ai(?![a-z])", article["title"], re.I) if word == "AI" else word.lower() in (re.sub(r"[0-9][0-9,.]*(?:조|억|만|천)?\s*달러", "", article["title"]) if word == "달러" else article["title"]).lower())]
        if words:
            matches.append({"id": theme["id"], "name": theme["name"], "words": words})
    age = None
    if article.get("published_at"):
        age = max(0, (now - datetime.fromisoformat(article["published_at"])).total_seconds() / 3600)
    freshness = 0 if age is None else max(0, 50 - 25 * age if age <= 1 else 25 - (age - 1))
    score = round(freshness, 1)
    if matches:
        primary = next(t for t in THEMES if t["id"] == matches[0]["id"])
        reason = f"제목의 ‘{'·'.join(matches[0]['words'][:2])}’ 키워드로 {primary['name']} 주제로 분류했습니다. 주제는 점수에 반영하지 않습니다."
        question = primary["question"]
    else:
        reason = "시장 관련 피드에서 수집한 새 자료입니다. 제목에서 주요 관찰 키워드는 확인되지 않았습니다."
        question = "원문에서 투자와 직접 관련된 사실이 있는지 확인해 보세요."
    related = stocks.related_stocks(article['title'],article.get('published_at'))
    if reading and reading.get('article_title') == article['title']:
        body_stocks = stocks.body_related_stocks(reading.get('entity_mentions',[]),article.get('url'),article.get('published_at'))
        direct = [stock for stock in related if stock['relation']=='direct']
        codes = {stock['code'] for stock in direct}
        direct.extend(stock for stock in body_stocks if stock['code'] not in codes)
        codes = {stock['code'] for stock in direct}
        related = direct + [stock for stock in related if stock['code'] not in codes][:max(0,8-len(direct))]
    return {**article, "themes": matches, "score": score, "reason": reason, "question": question,
            "score_parts": {"freshness": score}, "related_stocks": related,
            "stock_analysis": relations.context(article["title"])}


def snapshot():
    with LOCK:
        state = {**STATE, "articles": [dict(a) for a in STATE["articles"]], "sources": [dict(s) for s in STATE["sources"]]}
    analysis = intelligence.snapshot()
    readings = {a['id']:a for event in analysis.get('events',[]) for a in event['articles']}
    articles = [classify({k:v for k,v in a.items() if k != 'feed_xml'},reading=readings.get(a['id'])) for a in deduplicate(state['articles'])]
    articles.sort(key=lambda a: (a["score"], epoch(a.get("published_at"))), reverse=True)
    themes = [{**{k: t[k] for k in ("id", "name", "question", "links")},
               "count": sum(any(m["id"] == t["id"] for m in a["themes"]) for a in articles)} for t in THEMES]
    with stocks.LOCK:
        stock_status = dict(stocks.CATALOGUE_STATUS)
    return {**state, "articles": articles, "themes": themes, "raw_count": len(state["articles"]), "interval": INTERVAL,
            "stock_status": stock_status, "quote_interval": stocks.QUOTE_TTL, "intelligence": analysis, "archive": archive.summary(),
            "method": "기본 추천은 주식 적합성을 검토한 사건의 모델 순위. 전체 자료의 최신성 점수는 별도 유지. 국내·미국 종목 연결과 공개 근거를 제공하며 실적·가격 반영 정도는 추가 확인 필요."}




def analysis_articles():
    with LOCK:
        articles = [dict(a) for a in STATE['articles']]
    return sorted(deduplicate(articles), key=lambda a: epoch(a.get('published_at')), reverse=True)


def refresh():
    with LOCK:
        old_articles = list(STATE["articles"])
        old_sources = {s["id"]: s for s in STATE["sources"]}
        STATE["collecting"] = True
    collected, statuses, fresh = [], [], []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {s["id"]: pool.submit(collect_source, s) for s in SOURCES}
        for source in SOURCES:
            previous = old_sources.get(source["id"], {})
            try:
                articles = futures[source["id"]].result()
                collected.extend(articles)
                fresh.extend(articles)
                statuses.append({**source, "status": "ok", "count": len(articles), "last_success": iso_now(), "error": None})
            except Exception as error:
                # Keep the last successful data, and expose failure rather than pretending it is current.
                retained = [a for a in old_articles if a["source_id"] == source["id"]]
                collected.extend(retained)
                statuses.append({**source, "status": "stale" if retained else "error", "count": len(retained),
                                 "last_success": previous.get("last_success"), "error": f"수집 실패 ({type(error).__name__})"})
    archive_error = None
    try:
        if fresh:
            archive.store(fresh)
    except Exception as error:
        archive_error = f'누적 보관 실패 ({type(error).__name__})'
    with LOCK:
        STATE.update(archive_error=archive_error, articles=collected, sources=statuses, updated_at=iso_now(), collecting=False)


def collector():
    while True:
        started = time.monotonic()
        refresh()
        time.sleep(max(0, INTERVAL - (time.monotonic() - started)))


def demo_snapshot():
    now = datetime.now(timezone.utc)
    examples = json.loads((ROOT / "web" / "demo.json").read_text())
    articles = []
    for index, example in enumerate(examples):
        article = {**example, "id": f"demo-{index}", "url": None, "published_at": (now - timedelta(minutes=example["minutes_ago"])).isoformat(),
                   "collected_at": now.isoformat(), "copies": example.get("copies", 1), "source_id": "scenario"}
        articles.append(classify(article, now))
    articles.sort(key=lambda a: a["score"], reverse=True)
    themes = [{**{k: t[k] for k in ("id", "name", "question", "links")},
               "count": sum(any(m["id"] == t["id"] for m in a["themes"]) for a in articles)} for t in THEMES]
    return {"articles": articles, "themes": themes, "raw_count": sum(a["copies"] for a in articles),
            "sources": [{"id": "scenario", "name": "가상 시나리오", "status": "demo", "count": len(articles), "last_success": None}],
            "updated_at": now.isoformat(), "collecting": False, "interval": INTERVAL,
            "stock_status": dict(stocks.CATALOGUE_STATUS)}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/dashboard":
            self.respond(json.dumps(snapshot(), ensure_ascii=False).encode(), "application/json; charset=utf-8")
            return
        if path == "/api/demo":
            self.respond(json.dumps(demo_snapshot(), ensure_ascii=False).encode(), "application/json; charset=utf-8")
            return
        if path == "/api/quotes":
            codes = list(dict.fromkeys(parse_qs(urlsplit(self.path).query).get("codes", [""])[0].split(",")))
            if not 1 <= len(codes) <= 20 or any(not re.fullmatch(r"(?:[0-9][0-9A-Z]{5}|[A-Z][A-Z0-9]{0,5}(?:\.O)?)", code) for code in codes):
                self.respond(b'{"error":"Invalid stock codes"}', "application/json", 400)
                return
            try:
                quotes = stocks.get_quotes(codes)
            except ValueError:
                self.respond(b'{"error":"Unknown stock codes"}', "application/json", 400)
                return
            self.respond(json.dumps({"quotes": quotes}, ensure_ascii=False).encode(), "application/json; charset=utf-8")
            return
        files = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                 "/styles.css": ("styles.css", "text/css; charset=utf-8"), "/demo.json": ("demo.json", "application/json; charset=utf-8"),
                 "/favicon.svg": ("favicon.svg", "image/svg+xml")}
        if path not in files:
            self.send_error(404)
            return
        filename, content_type = files[path]
        self.respond((ROOT / "web" / filename).read_bytes(), content_type)

    def respond(self, body, content_type, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="맥락 투자 정보 대시보드 시제품")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument('--analysis', action='store_true', help='Ollama 본문 분석·사건 묶기·시장 맥락순 활성화')
    args = parser.parse_args()
    if args.analysis:
        os.environ['LLM_ENABLED'] = '1'
    restored = archive.restore()
    if restored:
        restored_sources = [{**s,'status':'stale','count':sum(a['source_id']==s['id'] for a in restored),
            'last_success':max((a['collected_at'] for a in restored if a['source_id']==s['id']),default=None),
            'error':'재시작 후 이전 수집 자료 · 새 피드 확인 중'} for s in SOURCES]
        STATE.update(articles=restored,sources=restored_sources)
    threading.Thread(target=archive.body_collector, daemon=True).start()
    threading.Thread(target=collector, daemon=True).start()
    threading.Thread(target=stocks.catalogue_collector, daemon=True).start()
    threading.Thread(target=intelligence.collector, args=(analysis_articles,), daemon=True).start()
    print(f"맥락 prototype: http://127.0.0.1:{args.port} ({INTERVAL}초 간격 수집)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
