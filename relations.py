"""Evidence-backed event → business role → listed company candidates."""

from datetime import datetime, timezone
import json
from pathlib import Path
import re

KNOWLEDGE = json.loads((Path(__file__).parent / "data" / "relations.json").read_text())
SOURCES = KNOWLEDGE["sources"]
EVENTS = [
    ("policy", "정책·생태계 육성", r"유니콘|육성|키운다|지원책|정부.*지원|소버린|국가대표"),
    ("capacity", "설비·컴퓨팅 용량 투자", r"증설|설비|데이터센터.*(?:투자|건설)|컴퓨팅.*(?:용량|계약)|(?:GPU|TPU|가속기).*투자|기가와트|\bGW\b|CAPEX"),
    ("equity", "지분 투자·자금 조달", r"투자유치|투자 유치|출자|펀딩|자금.*조달|지분|funding|financing"),
    ("contract", "계약·공급·협력", r"계약|공급|수주|발주|협력|파트너|제휴|MOU|partnership"),
    ("product", "제품·서비스 상용화", r"출시|공개|상용화|도입|제품|서비스|(?<![a-z])API(?![a-z])"),
    ("efficiency", "효율·가격·경쟁 변화", r"효율|저비용|비용.*절감|가격.*인하|추론.*(?:개선|비용)|대체|경쟁"),
    ("restriction", "규제·제재·공급 제약", r"규제|제재|수출.*통제|관세|봉쇄|금지"),
    ("earnings", "실적·수요 변화", r"실적|매출|영업익|수요|주문|가이던스|목표가"),
]
ROLE_NAMES = {"llm": "기반모델", "cloud": "클라우드", "enterprise_ai": "기업 AI·서비스 통합",
              "accelerator": "AI 가속기", "network": "네트워크", "memory": "AI 메모리", "foundry": "파운드리", "packaging": "첨단 패키징"}
RELATION_NAMES = {"parent": "상장 모회사", "investment_partner": "투자·사업 관계", "supplier_partner": "공급·컴퓨팅 관계",
                  "distribution_partner": "유통·통합 관계", "capacity_plan": "협력 계획", "technology_partner": "기술 협력"}


def contains(text, word):
    pattern = re.escape(word)
    if re.search(r"[a-z]", word, re.I):
        pattern = r"(?<![a-z])" + pattern + r"(?![a-z])"
    return bool(re.search(pattern, text, re.I))


def source_records(ids, as_of):
    result = []
    for source_id in ids:
        source = SOURCES[source_id]
        if source["published_on"] and source["published_on"] > as_of:
            continue
        result.append({"id": source_id, **source, "checked_on": KNOWLEDGE["reviewed_on"]})
    return result


def context(title):
    boundary = r"[^a-zA-Z0-9가-힣]"
    def entity_matches(entity):
        if entity["id"] == "amazon" and re.search(r"아마존\s*(?:강|열대우림|삼림|산림|우림)|Amazon\s+(?:river|rainforest)", title, re.I):
            return False
        for alias in entity["aliases"]:
            if alias in ("제미나이", "Gemini", "알파벳", "Alphabet", "클로드", "Claude") and not re.search(r"AI|인공지능|LLM|모델|클라우드|챗봇|API|코딩|출시|버전|실적|투자", title, re.I):
                continue
            if re.search(r"(?<![a-zA-Z0-9가-힣])" + re.escape(alias) + f"(?=$|{boundary}|[은는이가의와과도를을에](?=$|{boundary}))", title, re.I):
                return True
        return False
    entities = [e for e in KNOWLEDGE["entities"] if entity_matches(e)]
    ai = any(contains(title, word) for word in ("AI", "인공지능", "LLM", "생성형", "파운데이션", "기반모델", "기반 모델", "HBM", "GPU", "TPU"))
    ai = ai or any(e["id"] in ("openai", "anthropic", "naver_cloud") for e in entities)
    events = [{"id": key, "name": name} for key, name, pattern in EVENTS if re.search(pattern, title, re.I)]
    if re.search(r"투자|\binvest(?:ment|s|ed|ing)?\b", title, re.I) and not any(e["id"] in ("capacity", "equity") for e in events):
        if any(e["id"] in ("openai", "anthropic") for e in entities) and re.search(r"에.{0,25}투자|지분", title):
            events.append({"id": "equity", "name": "지분 투자·자금 조달"})
        else:
            events.append({"id": "investment", "name": "투자 발표 · 유형 미확인"})
    prospective = bool(re.search(r"검토|예정|계획|추진|논의|MOU|의향|목표|전망|가능성", title, re.I))
    disputed = bool(re.search(r"부인|사실무근|무산|취소|철회|루머|오보", title))
    return {"entities": [{"id":e["id"], "name":e["name"], "code":e["code"],
                          "listing_note": None if e["code"] else "직접 거래 종목 미확인 · 관계 기업을 별도 표시"} for e in entities], "events": events, "ai": ai,
            "event_state": "부인·취소 등 재확인 필요" if disputed else "계획·전망 포함" if prospective else "제목의 주장 · 원문 확인 필요",
            "disputed": disputed, "knowledge_version": KNOWLEDGE["version"], "basis": "기사 제목 + 공개 사업 근거"}


def infer(title, catalogue, direct, as_of=None):
    as_of = (as_of or datetime.now(timezone.utc).isoformat())[:10]
    analysis = context(title)
    candidates = []
    ids = {e["id"] for e in analysis["entities"]}
    event_ids = {e["id"] for e in analysis["events"]}
    corporate_event = bool(event_ids)
    eligible = analysis["ai"] and corporate_event
    common_checks = ["원문에서 사건과 확정 여부 확인", "해당 사업의 매출·이익 기여와 실행 일정 확인"]

    def add(code, relation, reason, path, mechanism, evidence, checks, role=None, kind=None):
        if code not in catalogue:
            return
        record = {**catalogue[code], "relation": relation, "reason": reason, "path": path,
                  "mechanism": mechanism, "sources": evidence, "required_checks": checks,
                  "impact": "영향 미정", "materiality": "기사 사건의 매출·이익 영향 미산정", "role": role,
                  "connection_kind": kind, "knowledge_as_of": as_of,
                  "confidence": "직접 언급" if relation == "direct" else "공개 관계 확인 · 사건 영향 미확인" if relation == "documented" else "조건부 관찰 후보"}
        for candidate in candidates:
            if candidate["code"] == code:
                known = {s["id"] for s in candidate["sources"]}
                candidate["sources"].extend(s for s in evidence if s["id"] not in known)
                if path != candidate["path"]:
                    candidate.setdefault("other_paths", []).append(path)
                return
        candidates.append(record)

    for stock in direct:
        source = source_records(["krx" if stock.get("country", "KR") == "KR" else "nasdaq"], as_of)
        add(stock["code"], "direct", stock["reason"], f"기사 직접 언급 → {stock['name']}",
            "기사에 이름이 등장한 사실이며 수혜나 주가 방향 판정은 아님", source, common_checks)

    # Explicit entity identities can resolve unlisted brands to their listed issuer, but never mint a ticker for a private entity.
    for entity in analysis["entities"]:
        if entity["code"]:
            code = entity["code"]
            add(code, "direct", f"기사의 ‘{entity['name']}’를 상장 종목과 대조", f"{entity['name']} → 상장 종목",
                "기업·브랜드 명칭 대조. 해당 기사에서 이익이 증가한다는 의미는 아님",
                source_records(["nasdaq"], as_of), common_checks)

    if eligible or "naver_cloud" in ids:
        relationships = sorted(KNOWLEDGE["relationships"], key=lambda r: r["kind"] in ("capacity_plan", "technology_partner"))
        for relationship in relationships:
            if relationship["entity"] not in ids:
                continue
            if not eligible and relationship["kind"] != "parent":
                continue
            if any(SOURCES[s]["published_on"] and SOURCES[s]["published_on"] > as_of for s in relationship["sources"]):
                continue
            evidence = source_records(relationship["sources"], as_of)
            if not evidence:
                continue
            add(relationship["code"], "documented", relationship["path"], relationship["path"], relationship["mechanism"],
                evidence, [relationship["condition"], *common_checks], kind=RELATION_NAMES[relationship["kind"]])

    if eligible:
        if "policy" in event_ids:
            roles = {"llm", "cloud", "enterprise_ai"}
        elif re.search(r"HBM|메모리", title, re.I):
            roles = {"memory", "packaging"}
        elif re.search(r"LLM|파운데이션|기반.?모델|에이전트|기업용|소프트웨어", title, re.I) or ids & {"openai", "anthropic"}:
            roles = {"llm", "cloud", "enterprise_ai", "accelerator", "memory"}
        else:
            roles = {"accelerator", "memory", "foundry", "packaging", "cloud"}
        # Diversify across roles and markets, rather than filling every slot with the first names in one sector.
        profiles = [p for p in KNOWLEDGE["profiles"] if p["code"] in catalogue and set(p["roles"]) & roles]
        selected = []
        deferred = []
        groups = set()
        for profile in profiles:
            country = catalogue.get(profile["code"], {}).get("country", "KR")
            role = next((role for role in profile["roles"] if role in roles and (country, role) not in groups), None)
            if role:
                selected.append((profile, role))
                groups.add((country, role))
            else:
                deferred.append((profile, next(role for role in profile["roles"] if role in roles)))
        for profile, role in selected + deferred:
            evidence = source_records(profile["sources"], as_of)
            if not evidence:
                continue
            label = ROLE_NAMES[role]
            if "policy" in event_ids:
                path = f"AI 생태계·정책 → {label} 사업 → {profile['label']}"
                mechanism = "AI 생태계 사업 참여를 근거로 살펴볼 후보. 이 정책의 지원 대상·수주 여부는 확인되지 않음"
                checks = ["정책 수혜 자격·선정 기업·예산 집행 확인", "비상장 지원 대상과 상장 사업자 구분"]
            elif "equity" in event_ids:
                path = f"AI 기업 투자·자금 조달 → 사업 확대 가능성 → {label}"
                mechanism = "투자금이 해당 제품·서비스 구매로 이어질 경우의 간접 노출. 투자 발표만으로 발주는 확정되지 않음"
                checks = ["지분 투자와 설비·구매 계약을 구분", "자금 사용처·고객·확정 발주와 매출 인식 시점 확인"]
            else:
                path = f"AI 사건 → {label} 가치사슬 → {profile['label']}"
                mechanism = "공개된 해당 사업 참여를 근거로 연결한 가치사슬 후보. 개별 사건의 거래 상대방은 미확인"
                checks = ["사건이 실제 제품·고객·수요와 연결되는지 확인", "효율 개선·규제·경쟁 변화는 영향 방향이 혼재할 수 있음"]
            add(profile["code"], "theme" if "policy" in event_ids else "value_chain", profile["activity"], path, mechanism,
                evidence, [*checks, *common_checks], role=label)

    if analysis["disputed"]:
        for candidate in candidates:
            candidate["required_checks"].insert(0, "기사에 부인·취소 등이 포함됨. 과거 사업 관계가 신규 거래의 성립을 입증하지 않음")
    # Keep all directly mentioned issuers, then a bounded diversified set of inferred candidates.
    selected = [c for c in candidates if c["relation"] == "direct"]
    remaining = sorted((c for c in candidates if c["relation"] != "direct"),
                       key=lambda c: (c["relation"] != "documented", -len(c.get("other_paths", []))))
    profiles = {p["code"]: p for p in KNOWLEDGE["profiles"]}
    for tier in ("documented", "value_chain", "theme"):
        group_candidates = [c for c in remaining if c["relation"] == tier]
        groups = set()
        for candidate in group_candidates:
            role = candidate["role"] or profiles.get(candidate["code"], {}).get("roles", [candidate["connection_kind"]])[0]
            group = (candidate.get("country", "KR"), role)
            if group not in groups and len(selected) < 8:
                selected.append(candidate)
                groups.add(group)
        for candidate in group_candidates:
            if len(selected) >= 8:
                break
            if candidate not in selected:
                selected.append(candidate)
    candidates = selected
    analysis["entities"] = [{"name": e["name"], "code": e["code"], "listing_note": None if e["code"] else "직접 거래 종목 미확인 · 관계 기업을 별도 표시"} for e in analysis["entities"]]
    analysis["checks"] = (["투자금 유입은 GPU·HBM 발주와 다릅니다."] if "equity" in event_ids else []) + (["AI 육성 정책의 지원 대상과 계약 수혜자는 원문 확인이 필요합니다."] if "policy" in event_ids else [])
    return candidates, analysis
