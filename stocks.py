"""Korean/US listed company matching and timestamped public Npay quotes."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
import csv
import io
import json
import math
import re
import threading
import time
from urllib.request import Request, urlopen

import relations

CATALOGUE_URL = "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"
QUOTE_URL = "https://m.stock.naver.com/api/stock/{code}/basic"
US_LISTING_URLS = {"NASDAQ": "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
                   "NYSE": "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"}
CATALOGUE = {}
NAME_MATCHER = None
NAME_CODES = {}
CATALOGUE_STATUS = {"status": "loading", "count": 0, "updated_at": None}
QUOTES = {}
LOCK = threading.Lock()
QUOTE_LOCK = threading.Lock()
QUOTE_TTL = 10
ALIASES = {"000660": ["SK하이닉스", "하이닉스"], "005380": ["현대차"], "005930": ["삼전"],
           "005490": ["포스코홀딩스"], "035420": ["네이버"], "030200": ["KT"]}
for entity in relations.KNOWLEDGE["entities"]:
    if entity["code"]:
        ALIASES.setdefault(entity["code"], []).extend(entity["aliases"])
# shortcut: explicit domestic business links only; expand with sourced entity/event analysis when full-text ingestion is available.
BUSINESS_LINKS = [
    (["반도체", "HBM", "메모리"], ["005930", "000660"]),
    (["방산", "방위산업"], ["012450", "079550", "064350"]),
    (["원전", "원자력"], ["034020", "052690"]),
    (["정유", "유가", "원유"], ["010950", "096770"]),
]


def fetch(url, limit, encoding=None):
    request = Request(url, headers={"User-Agent": "MaekrakPrototype/0.1 (public market data reader)",
                                   "Accept": "application/json, text/html, text/plain, */*"})
    with urlopen(request, timeout=10) as response:
        body = response.read(limit + 1)
        if len(body) > limit:
            raise ValueError("데이터 크기 제한 초과")
        return body.decode(encoding or response.headers.get_content_charset() or "utf-8")


class ListingParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], [], None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.cell = []

    def handle_data(self, text):
        if self.cell is not None:
            self.cell.append(text)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row:
            self.rows.append(self.row)
            self.row = []


def parse_catalogue(html):
    parser = ListingParser()
    parser.feed(html)
    headers = next((row for row in parser.rows if "회사명" in row and "종목코드" in row), None)
    if headers is None or not all(field in headers for field in ("시장구분", "업종", "주요제품")):
        raise ValueError("KRX 목록 형식 변경")
    result = {}
    for row in parser.rows:
        if len(row) != len(headers):
            continue
        values = dict(zip(headers, row))
        code = values["종목코드"].upper()
        if not re.fullmatch(r"[0-9A-Z]{6}", code) or not values["회사명"]:
            continue
        result[code] = {"code": code, "name": values["회사명"], "market": values["시장구분"],
                        "industry": values["업종"], "products": values["주요제품"], "country": "KR", "listing_source": "KRX"}
    if not result:
        raise ValueError("상장 종목 없음")
    return result


def parse_us_catalogue(text, exchange):
    result = {}
    for row in csv.DictReader(io.StringIO(text), delimiter="|"):
        symbol = row.get("Symbol") if exchange == "NASDAQ" else row.get("ACT Symbol")
        name = row.get("Security Name") or ""
        if row.get("ETF") != "N" or row.get("Test Issue") != "N" or not symbol or not re.fullmatch(r"[A-Z][A-Z0-9]{0,5}", symbol):
            continue
        if exchange == "NYSE" and row.get("Exchange") != "N":
            continue
        if re.search(r"warrants?|preferred|units?\b|rights?\b|notes?\b|debentures?|bonds?\b", name, re.I):
            continue
        code = symbol + (".O" if exchange == "NASDAQ" else "")
        if not re.search(r"common|ordinary|depositary|\bADS", name, re.I) and code not in {p["code"] for p in relations.KNOWLEDGE["profiles"]}:
            continue
        company = name.split(" - ")[0]
        company = re.sub(r"\s+(?:Class [A-Z] )?(?:Common Stock|Common Shares|Ordinary Shares).*", "", company, flags=re.I)
        label = next((p["label"] for p in relations.KNOWLEDGE["profiles"] if p["code"] == code), company)
        result[code] = {"code": code, "name": label, "legal_name": company, "market": exchange, "country": "US",
                        "industry": "", "products": "미국 공식 상장 목록 대조 · 사업 정보는 별도 근거 확인", "listing_source": exchange}
    if not result:
        raise ValueError("미국 보통주·ADR 목록 형식 변경 또는 항목 없음")
    return result


def stock_url(code, country="KR"):
    return f"https://stock.naver.com/{'worldstock' if country == 'US' else 'domestic'}/stock/{code}"


def compile_names(catalogue):
    names = {}
    for code, stock in catalogue.items():
        legal = stock.get("legal_name", stock["name"])
        short = re.sub(r",?\s+(?:Corporation|Incorporated|Inc\.?|Corp\.?|Ltd\.?).*$", "", legal, flags=re.I)
        for name in [stock["name"], legal, short, *ALIASES.get(code, [])]:
            names.setdefault(name.lower(), set()).add(code)
    names = {name: next(iter(codes)) for name, codes in names.items() if len(codes) == 1}
    long = "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True) if len(name) > 2)
    short = "|".join(re.escape(name) for name in names if len(name) <= 2)
    boundary = r"[^a-zA-Z0-9가-힣]"
    branches = []
    if long:
        branches.append(f"(?:{long})(?=$|{boundary}|[은는이가의와과도를을에](?=$|{boundary}))")
    if short:
        branches.append(f"(?:{short})(?=$|{boundary})")
    return re.compile(r"(?<![a-zA-Z0-9가-힣])(?:" + "|".join(branches) + ")", re.I) if branches else None, names


def refresh_catalogue():
    global NAME_MATCHER, NAME_CODES
    try:
        with LOCK:
            previous = dict(CATALOGUE)
        readers = {"KRX": lambda: parse_catalogue(fetch(CATALOGUE_URL, 4_000_000, "euc-kr")),
                   **{exchange: (lambda exchange=exchange, url=url: parse_us_catalogue(fetch(url, 4_000_000, "utf-8"), exchange)) for exchange, url in US_LISTING_URLS.items()}}
        catalogue, statuses = {}, {}
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {source: pool.submit(reader) for source, reader in readers.items()}
            for source, future in futures.items():
                try:
                    catalogue.update(future.result())
                    statuses[source] = "ok"
                except Exception:
                    retained = {code: stock for code, stock in previous.items() if stock.get("listing_source", "KRX") == source}
                    catalogue.update(retained)
                    statuses[source] = "stale" if retained else "error"
        if not catalogue:
            raise ValueError("상장 목록 수집 실패")
        matcher, names = compile_names(catalogue)
        with LOCK:
            CATALOGUE.clear()
            CATALOGUE.update(catalogue)
            NAME_MATCHER, NAME_CODES = matcher, names
            complete = all(status == "ok" for status in statuses.values())
            CATALOGUE_STATUS.update(status="ok" if complete else "partial", count=len(catalogue),
                                    markets={country: sum(s["country"] == country for s in catalogue.values()) for country in ("KR", "US")},
                                    sources=statuses, updated_at=datetime.now(timezone.utc).isoformat())
        return complete
    except Exception:
        with LOCK:
            CATALOGUE_STATUS["status"] = "stale" if CATALOGUE else "error"
        return False


def catalogue_collector():
    while True:
        success = refresh_catalogue()
        time.sleep(86400 if success else 300)


def related_stocks(title, as_of=None):
    with LOCK:
        catalogue = dict(CATALOGUE)
        matcher, names = NAME_MATCHER, NAME_CODES
    direct = []
    for match in matcher.finditer(title) if matcher else []:
        name = match.group()
        code = names[name.lower()]
        if re.search(r"[-－—–]\s*" + re.escape(name) + r"\s*$", title):
            continue
        if name == "케이티" and title[match.end():].lstrip().startswith("페리"):
            continue
        if len(name) <= 2 and not (re.search(r"주가|실적|매출|영업|배당|주주|수주|상장|목표가|자사주|매수|매도", title)
                                           or re.match(r"\s*[,，:：]", title[match.end():])):
            continue
        if any(s["code"] == code for s in direct):
            continue
        direct.append({**catalogue[code], "relation": "direct", "reason": f"기사 제목에 ‘{name}’ 직접 언급", "evidence": name})
    inferred, analysis = relations.infer(title, catalogue, direct, as_of)
    if inferred or analysis["ai"]:
        return inferred
    inferred = []
    for keywords, codes in BUSINESS_LINKS:
        word = next((word for word in keywords if word.lower() in title.lower()), None)
        if not word:
            continue
        for code in codes:
            if code not in catalogue or any(s["code"] == code for s in inferred):
                continue
            stock = catalogue[code]
            inferred.append({**stock, "relation": "business", "reason": f"제목의 ‘{word}’ 관련 사업 후보 · KRX 주요제품: {stock['products']}", "evidence": word,
                             "path": f"{word} → 공개된 주요제품 → {stock['name']}", "impact": "영향 미정", "confidence": "조건부 관찰 후보",
                             "sources": relations.source_records(["krx"], (as_of or datetime.now(timezone.utc).isoformat())[:10]),
                             "required_checks": ["업종·제품 연관 후보이며 개별 수주·손익 영향은 미확인"]})
    return inferred[:3]


def parse_quote(data, code):
    us = code[0].isalpha()
    if data.get("reutersCode" if us else "itemCode") != code:
        raise ValueError("시세 종목코드 불일치")
    price = float(str(data["closePrice"]).replace(",", ""))
    change = float(str(data["fluctuationsRatio"]).replace(",", ""))
    direction = data.get("compareToPreviousPrice", {}).get("code")
    if direction in ("4", "5"):
        change = -abs(change)
    elif direction in ("1", "2"):
        change = abs(change)
    elif direction == "3":
        change = 0
    else:
        raise ValueError("등락 방향 정보 없음")
    traded_at = data["localTradedAt"]
    if not math.isfinite(price) or price < 0 or not math.isfinite(change) or datetime.fromisoformat(traded_at).tzinfo is None:
        raise ValueError("유효하지 않은 시세")
    currency = data.get("currencyType", {}).get("code", "USD" if us else "KRW")
    if currency != ("USD" if us else "KRW"):
        raise ValueError("시세 통화 불일치")
    return {"code": code, "name": data["stockName"], "price": price, "change_percent": change, "currency": currency,
            "traded_at": traded_at, "fetched_at": datetime.now(timezone.utc).isoformat(),
            "market_status": data.get("marketStatus"), "delay_label": data.get("delayTimeName") or "지연 여부 미제공",
            "source": "Npay 증권", "session": "미국 정규장" if us else "국내", "url": stock_url(code, "US" if us else "KR"), "status": "ok"}


def collect_quote(code):
    url = f"https://api.stock.naver.com/stock/{code}/basic" if code[0].isalpha() else QUOTE_URL.format(code=code)
    return parse_quote(json.loads(fetch(url, 100_000)), code)


def get_quotes(codes):
    with LOCK:
        if any(code not in CATALOGUE for code in codes):
            raise ValueError("상장 목록에 없는 종목코드")
    # Serialize refreshes to avoid duplicate provider requests when several browser tabs poll at once.
    with QUOTE_LOCK:
        missing = [code for code in codes if code not in QUOTES or time.monotonic() - QUOTES[code][0] >= QUOTE_TTL]
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {code: pool.submit(collect_quote, code) for code in missing}
            for code, future in futures.items():
                try:
                    quote = future.result()
                except Exception:
                    previous = QUOTES.get(code, (0, {}))[1]
                    quote = {**previous, "code": code, "status": "stale" if previous.get("price") is not None else "error",
                             "error": "시세 조회 실패"}
                QUOTES[code] = (time.monotonic(), quote)
        return {code: dict(QUOTES[code][1]) for code in codes}
