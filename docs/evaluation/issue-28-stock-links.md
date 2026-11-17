# #28 독립 기사 종목 연결 평가 명세와 실행 기록

이 문서는 평가 도구의 재현 절차와 자료 확보 전 상태를 기록한다. 실제 한국어 전문의 독립 최종 정답은 확보되지 않았으므로 종목 연결 정밀도 95%, 재현율 80%, 출처·재현 정보 100%, 도전 사례 치명 오류 0건은 모두 **미검증**이다. 기존 영문 사건 구절 정답과 UI 회귀 검사를 한국어 기사 정답으로 전용하지 않았다. 투자 성과나 상승 확률을 측정하지 않는다.

## 작업 경계와 기준

이슈는 https://github.com/kingrangE/research_agent/issues/28 이고 Task는 `task_dbc7ce9431e9`, Dispatch는 `ctx_eee9e9f949fd`다. Worktree는 `/Users/project/orca/workspaces/research_agent/eval-28`, 브랜치는 `kingrangE/eval-28`이며 실제 착수 HEAD는 `f7b9190c5bba1166cba2166d4361f2cb0712ed86`으로 coordinator의 지정값과 일치한다. 이슈 본문의 과거 로컬 기준 `e5d97c7`과는 다르며 현재 코드가 원격과 같다고 가정하지 않는다. 변경 경계는 새 평가 스크립트 `evaluate_stock_links.py`, 합성 단위 검사 `tests/test_stock_link_evaluation.py`, 이 문서다. 운영 공용 코드, 규칙, UI, DB, 컨테이너와 인증은 변경하지 않는다.

실행 환경은 Apple M2 Pro, 물리/논리 CPU 12/12, 메모리 17,179,869,184바이트, macOS Darwin 25.3.0 arm64, Python 3.13.2, Node v23.10.0이다. 로컬 날짜는 2026-11-17, 기준 시간대는 Asia/Seoul이고 스크립트는 실행 직전 UTC 시각과 실제 프로세스 시간대를 기록한다. 시스템 시계 동기화는 독립 확인하지 않았다. 단일 Python 프로세스의 오프라인 모드로 서버·추가 작업자·포트·운영 DB·Docker 프로젝트는 사용하지 않았다. 같은 호스트의 다른 4개 worker와 자원을 공유하므로 격리 성능 측정이 아니다. 새 Python 프로세스로 실행하며 OS 파일 캐시는 통제하지 않았다. 네트워크·LLM·임베딩·시세 호출 예산은 각각 0회다. 부트스트랩은 seed 28, 1,000회로 미리 고정한다. 실제 최종 평가 입력·정답·상장 목록의 수와 지문은 자료 미확보로 미산정이고, 대체 값을 만들지 않았다. 서버·규칙 파일과 UI 파일의 SHA-256, 런타임과 실제 HEAD는 비공개 `environment.json`에 기록한다.

## 자료 확보 전에 고정할 표본 계획

아래는 이번에 제시하는 후속 평가 계획이며 이미 추출·검수된 자료라는 뜻이 아니다. 개발 종료일, 후속 기간 시작/종료일과 추출 시각은 자료 담당자가 실제 후속 기간을 정한 뒤 manifest에 고정해야 한다. 평가 결과를 열기 전에 원문 버전, 상장 목록, 공개 관계 자료, 분할과 아래 층별 수를 봉인한다. 현 시점에서는 날짜를 임의로 정하거나 과거 자료를 독립 후속 자료라고 표현하지 않는다.

최소 100개의 독립 사건 요건을 충족하도록 우선 서로 다른 사건 120건을 기사 120건으로 추출한다. 정상 운영 빈도 표본 80건과 의도적 도전 40건을 구분한다. 각 집단에서 KR/US × AI·소프트웨어/반도체/데이터센터/전력 인프라의 8칸에 정상 10건, 도전 5건을 고정한다. 이 균등 층화 점수는 실제 운영 빈도로 가중한 전체 시장 점수가 아니다. 정상 표본은 각 칸의 기간 내 적격 기사 목록에서 미리 정한 난수 seed와 추출 순서로 뽑고, 모집단 수와 포함 확률을 별도 보존한다. 대표성 판단은 최종 자료 담당자가 해야 한다.

추출 단계의 예상 주 연결 성격은 direct 40건, documented 25건, theme 25건, none 30건으로 고정한다. 이는 예측이나 정답을 보고 사후 재배분하는 기준이 아니다. 실제 검수 후 각 유형이 바뀌면 예상 층과 최종 정답 층의 차이를 보고하고 표본을 유리하게 교체하지 않는다. 도전 사례는 동명이인, 계열사, 우선주, 비상장, 증권사 인용, 정정, 취소, 미래 근거, 명시적 부정, 관련 종목 없음의 10개 태그에 각각 4건을 배정한다. 정상 80건의 `challenge_tag`는 `none`이다. 동일 사건 재전송·정정·취소는 같은 `event_id` 계열로 묶으며 개발/최종과 정상/도전 사이에 흩어 놓지 않는다. 이 분할은 사람이 검토하며 문장 유사도만으로 독립성을 확정하지 않는다.

## 비공개 입력 형식

입력은 UTF-8 JSON이다. 전체 기사·정답·개별 예측·검수 자료는 저장소 밖 접근 제한 디렉터리에 둔다. 파일 내용 지문은 `fingerprint()`의 정렬된 JSON 표현이고 원본 파일 바이트 지문도 실행 결과에 별도로 기록한다. 주어진 SHA 문자열은 그 자체로 실제 원문 보관, 인간 신원 또는 독립성을 인증하지 않는다. 자료 담당자는 연결된 비공개 보관본을 열어 일치 여부를 확인해야 한다. 도구는 원문이나 공개 사이트를 다운로드하지 않는다.

`articles.json`은 기사 객체 배열이다. 각 객체에 `id`, `event_id`, `sample` (`normal`/`challenge`), `market` (`KR`/`US`), `theme`, `primary_type` (`direct`/`documented`/`theme`/`none`), `challenge_tag`, `title`, `body`, 오프셋이 있는 `published_at`, `source_url`, `source_archive_sha256`을 넣는다. 보관된 전문과 제목의 버전 일치는 사람이 확인한다. 시장·테마는 추출 기준의 주 층이고 다중 시장 연결은 종목 코드로 별도 검수한다. 코드는 선행 0을 보존하는 문자열이다.

`catalogue.json`은 코드 → 기존 `stocks.py` 목록 객체 사전이다. 각 항목은 적어도 `code`, `name`, `country`, `market`, `products`를 포함하며 필요하면 `legal_name`을 넣는다. 기사 당시 거래 가능한 개별 보통주·ADR·우선주 여부와 법인·브랜드의 차이를 검수한다. 현재 KRX/미국 파서가 일부 우선주 등을 제외하는 점을 평가자 목록으로 조용히 숨기지 않는다. 전체 당시 상장 목록과 공개 관계 자료 중 사람이 검토한 평가 가능 증권을 후보 범위로 고정한다. 목록 범위 밖 기업은 무조건 누락으로 세지 않고 범위 밖임을 보고한다.

`manifest.json`에는 `rules` (현재 `rule_hashes()`의 파일별 지문), `articles_sha256`, `catalogue_sha256`, `candidate_codes` (목록의 정렬된 모든 코드), `listing_archive_sha256`, `relation_archives_sha256`, `development_event_ids`, `development_end`, `final_start`, `final_end`, 오프셋이 있는 `frozen_at`, `strata_counts` (`sample|market|theme` → 건수), `primary_type_counts`, `challenge_tag_counts`, `independent_final`을 넣는다. 개발/최종 기간 역전, 개발 사건 유입, 정상/도전 사건 교차, 중복 기사 ID, 입력·규칙 지문 및 고정 층별 수 불일치를 거부한다. 상장·관계 보관본의 실제 보관과 시점별 적격 여부는 사람 검수 항목이다. UI 검수 완료 후 원문 링크·연결 유형·부정/미래 상태를 실제 화면과 대조한 기록의 `ui_review_sha256`을 추가한다. UI 검수 지문만으로 실제 화면 검수를 대체하지 않는다.

`gold.json`은 기사 ID → 검수 객체 사전이며 보류 기사도 빠짐없이 넣는다. 객체에는 `status` (`reviewed`/`undecidable`/`hold`), `complete` (후보 범위 안의 완전한 정답인지), `links`, `negative_codes`, `critical_codes`, `reviews`를 넣는다. `links`는 `code`, `type` (`direct`/`documented`/`theme`), 기사 제목/전문에서 그대로 찾을 수 있는 `quote`, 오프셋이 있는 `known_at`, `source_url`, `source_archive_sha256` 배열이다. 연결 없음은 검수 완료·완전 정답·빈 links로 표현한다. 불완전 정답에서는 명시적으로 부정 검수한 `negative_codes`만 오연결로 판정하고 나머지 예측은 unknown으로 별도 집계한다. 그런 사례의 재현율은 미산정이고 최종 통과 자격도 없다. 유형은 기업 이름 식별·공개 관계·테마 참여의 구분이며 법적 직접 당사자나 수혜 예측을 같은 정답으로 취급하지 않는다.

`reviews`에는 두 독립 검수자의 `reviewer`, `human: true`, `prediction_blind: true`, `reviewed_at`, 원시 판정 기록의 `record_sha256`, 코드·유형·근거·부정·완전성까지 포함한 판정의 `decision_sha256`을 보존한다. 판정이 다르면 제삼자 또는 합의 검수의 `adjudication.record_sha256`과 합의 정답의 `adjudication.decision_sha256`을 남긴다. 판정 지문은 `decision_fingerprint()`가 선택하는 `status`, `complete`, `links`, `negative_codes`, `critical_codes`의 정렬된 JSON 지문으로 정의한다. 두 일치 판정 또는 합의 판정이 최종 정답 지문과 맞아야 해결 기사로 센다. 일치도는 정확한 기사별 판정 지문 일치/유효 독립 검수 기사 수다. 집합형 정답에 단순 Cohen kappa를 적용하지 않는다. `critical_codes`는 코드 → 오류 태그 배열로 `wrong_security`, `future_evidence`, `denial_promoted`를 받는다. 이는 현재 예측을 본 뒤 정답을 바꾸는 항목이 아니라 증권 구별·근거 시점·부인 승격에 대한 판정이다. 공개 근거의 날짜가 기사일 이후인 경우는 도구도 치명 오류로 잡지만 같은 날 시각 차이는 날짜만으로 확인할 수 없어 사람이 원문 시각을 확인해야 한다.

## 실행과 집계

```sh
python3 -m unittest discover -s tests -p test_stock_link_evaluation.py -v
python3 evaluate_stock_links.py --audit --output /private/tmp/research-agent-eval28-audit-UNIQUE
python3 evaluate_stock_links.py --manifest /PRIVATE/manifest.json --articles /PRIVATE/articles.json --catalogue /PRIVATE/catalogue.json --output /PRIVATE/predictions-UNIQUE
python3 evaluate_stock_links.py --manifest /PRIVATE/manifest.json --articles /PRIVATE/articles.json --catalogue /PRIVATE/catalogue.json --gold /PRIVATE/gold.json --output /PRIVATE/scored-UNIQUE
```

출력 디렉터리는 저장소 밖의 새 경로여야 하고 기존 경로 덮어쓰기는 거부한다. 디렉터리는 권한 0700으로 생성한다. 원문과 정답은 출력에 복제하지 않지만 예측, 기사 ID·URL, 오연결·누락 코드와 치명 오류 추적은 민감 자료로 취급한다. `environment.json`, `predictions.json`, `results.json`을 보관한다. 정답 파일은 예측을 생성·저장한 뒤에만 연다. 예측만 생성하는 첫 실행으로 검수자에게 예측을 노출하지 않는 흐름을 마련할 수 있다. 결과를 보고 규칙을 바꾸면 해당 자료는 개발 자료가 되므로 새로운 후속 최종 자료가 필요하다.

기준선은 기존 직접 이름 대조 `direct_mentions`, 현재 방식은 실제 화면의 `server.classify`를 그대로 호출한다. 기본은 자료 모드의 제목 기반 후보 경로이며 전문을 제목 문자열에 이어 붙이지 않는다. 이미 보관된 분석이 있는 운용 모드를 평가할 때만 기사 객체의 선택적 `reading`에 당시 `article_title`과 `entity_mentions`를 그대로 보존한다. 정답 검수자가 정답에서 entity_mentions를 만들어 넣으면 누출이다. 신규 LLM 호출은 하지 않으며 입력에 reading이 없으면 본문 기업 추출 경로는 미지원으로 보고한다. 전문 기반 독립 정답을 두어 제목 경로의 누락도 그대로 측정한다. 기준선은 순수 이름 대조라 현재 방식의 근거 시점 필터까지 같은 것은 아니며 이 차이를 보고한다. 본문 언급 `body`는 direct로, 현재 방식의 `value_chain`/`business`는 집계에서 theme으로 묶되 원시 관계 유형과 원문 출처는 예측 파일에 보존한다. 기본 뉴스 칩은 유형을 표시하지 않고 상세 카드가 여섯 원시 유형을 표시하므로 실제 UI 검수는 기사 상세에서 수행해야 한다. 실제 화면의 최초 3건과 전체 표시도 확인하며 평가의 top8은 반환 순서의 앞 8건이다. 직접 연결이 8건을 넘을 수 있으므로 전체와 top8은 동일하다고 가정하지 않는다.

전체 micro 기사-코드 정밀도·재현율·F1과 기사별 macro 및 시장·테마·표본·유형별 macro를 보고한다. 각 비율에는 분자·분모가 있고 기사/독립 사건 수, unknown·보류·예측 없음·정답 음성·정답 음성 오탐률, 기사별 오연결·누락 코드, top8 정밀도·정답 회수율, 정답 유형→예측 유형 혼동을 남긴다. 유형별 지표는 코드와 유형을 함께 맞혀야 하므로 코드 micro보다 엄격하다. 자료의 시장 층은 기사 추출 시장이고 종목 코드별 시장 전체를 뜻하지 않는다. 출처 지표는 반환된 URL/공개일 존재와 기사일 이전 여부의 메타데이터 확인 비율이며 실제 링크 접속·보관본 내용 일치는 별도 사람이 검증해야 한다.

95% 구간은 독립 사건 계열 전체를 묶어 동일 사건 기사와 종목 쌍의 상관을 보존하는 percentile bootstrap이다. 전체·시장·테마·유형·정상/도전에 각각 산정하고 사건 2개 미만은 구간 미산정이다. 점 추정·작은 집단의 구간과 유효 재표집 수를 함께 읽으며 100% 관측이나 좁은 구간이 새로운 오류가 없음을 보장하지 않는다. 모든 기사 보류로 높은 정밀도를 주장할 수 없고 예측 0건 정밀도는 null이다. 독립 사건 100개·두 사람 맹검/불일치 해결·완전 검수·독립 최종 자료 선언·UI 검수 기록 중 하나라도 없으면 목표를 통과 처리하지 않는다. 도구가 검사하는 메타데이터 조건과 실제 사람이 입증해야 하는 독립성·아카이브·UI 검수는 구별한다.

## 실제 실행 결과와 남은 검증

합성 단위 검사 12개는 종료 코드 0으로 통과했다. 정상 기사 품질 분모로 합성 자료를 세지 않는다. 실제 평가 감사 실행의 입력 기사는 0건, 독립 사건 0건, 사람 검수 0건이다. 따라서 정밀도 분자/분모 0/0, 재현율 0/0, F1, 95% 구간, 시장·테마·관계별 품질, 치명 오류율은 모두 미산정이다. p50/p95/p99도 실제 기사 처리 표본 0개로 미산정이며 단위 검사 실행 시간을 서비스 지연이나 투자자 탐색 시간으로 표현하지 않는다. 연결 없음·보류·오탐 비율 역시 실제 자료가 없어 미산정이다. 독립 후속 기간·상장 스냅샷·공개 관계 보관본과 두 사람의 검수가 제공되지 않은 것이 차단 요인이다.

운영 서버 부하, 브라우저 실제 화면 대조, 독립 검수자 일치도, 실제 오연결·누락·치명 사례 분석은 실행하지 않았다. 코드에서 상세의 직접/사업/테마 구분과 출처 링크 렌더링을 확인했지만 실제 화면 검증으로 보고하지 않는다. 후속 실행자는 고정 표본 120건과 비공개 보관본·정답·검수 로그를 준비하고 현재 규칙으로 예측을 봉인한 후 실제 화면과 근거를 대조해야 한다. 이번 제출은 재현 가능한 도구와 정직한 자료 미확보 보고이며 이슈의 최종 품질 기준 충족이나 자동 이슈 종료를 뜻하지 않는다.


## 전달용 실행 증거

최종 실행에서 `python3 -m unittest discover -s tests -p test_stock_link_evaluation.py -v`는 12개, `test_relations.py`는 16개, `test_stocks.py`는 15개, `test_server.py`는 17개로 합계 60개 검사가 통과했고 각 종료 코드는 0이다. `python3 -m py_compile evaluate_stock_links.py`와 `git diff --check`도 종료 코드 0이다. 합성 1건을 사용한 전체 CLI 점검은 최초 공개일 null 처리 오류로 종료 코드 1이었으며 `/private/tmp/research-agent-eval28-task-dbc7ce9431e9-smoke/cli.log`에 실패를 보존했다. 공개일 미확인을 미검증으로 처리하는 회귀 검사를 추가한 뒤 같은 입력의 새 출력 경로 실행이 종료 코드 0으로 통과했다. 기존 출력 디렉터리 재사용은 의도대로 종료 코드 2로 거부됐다. 합성 1건의 품질 수치는 실제 기사 평가 집계에 포함하지 않으며 최종 품질 인증도 false임을 별도로 확인했다.

최종 감사 명령은 `python3 evaluate_stock_links.py --audit --output /private/tmp/research-agent-eval28-task-dbc7ce9431e9-release-audit`이고 종료 코드 0, 상태 unverified다. 환경·규칙 지문과 실제 자료 0건 결과의 비공개 산출물은 해당 경로의 `environment.json`, `results.json`이다. 합성 CLI 입력·출력·오류·수정 후 결과·검사 로그·실행 명령과 종료 코드 목록은 `/private/tmp/research-agent-eval28-task-dbc7ce9431e9-smoke/` 및 `verification.json`에 있다. 원시 자료는 저장소에 추가하지 않는다. 이 경로는 호스트 임시 공간이라 장기 보존을 보장하지 않으며 실제 최종 평가 때는 접근 제한 검증 저장소로 보관해야 한다. 이전 감사 경로는 중간 도구 상태의 기록이고 최종 전달 기준은 release-audit다.
