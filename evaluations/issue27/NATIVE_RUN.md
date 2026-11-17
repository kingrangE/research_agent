# #27 native k6 추가 실행

이 기록은 최초 도구 제출 이후 Task `task_b8ea0f1f15b7`, Dispatch `ctx_6d6a37fe1cba`에서 수행한 실제 HTTP 부하 평가다. Worktree는 `/Users/project/orca/workspaces/research_agent/eval-27`, 브랜치는 `kingrangE/eval-27`, 착수 HEAD는 `90f3dedc24da1221d437d4e94513748208b65662`다. 제품 기준 코드는 `f7b9190c5bba1166cba2166d4361f2cb0712ed86`이며 제품 코드를 변경하지 않았다. 운영 서버·볼륨·인증·다른 Worker는 변경하지 않았다.

## 입력과 환경

공식 [Grafana 설치 안내](https://grafana.com/docs/k6/latest/set-up/install-k6/)의 Homebrew 경로로 `HOMEBREW_NO_AUTO_UPDATE=1 brew install k6`를 실행했다. 설치 종료 코드는 0이고 native k6는 `v2.4.0 (commit/devel, go1.27.4, darwin/arm64)`이다. 유료 자원을 구매하지 않았다. 환경은 macOS 26.3.1 arm64, Apple M2 Pro 12 논리 CPU, 16 GiB RAM, Python 3.13.2다. 대상과 발생기는 서로 다른 로컬 프로세스지만 물리 호스트를 공유하며 다른 작업도 병행된다. 따라서 격리된 서버의 최대 성능이나 운영 10,000명 지원을 뜻하지 않는다.

`serve_load_fixture.py`는 실제 `server.Handler`·`ThreadingHTTPServer`와 실제 archive·시세 캐시·시장·타임라인·상세 코드 경로를 실행한다. 유일 포트는 `127.0.0.1:19227`, DB는 `.data/validation/issue27/native-20261117/target/`이다. 입력은 **합성 기사 1,000건, 합성 상장 코드 10,000개와 기존 사업 지식 등록 16개, 36개 코드의 고정 가격 관측 각 60행(총 2,160행)**이다. 실제 전체 상장 목록이나 운영 사본이 아니다. payload와 가격 관측 시계는 `2026-11-17T05:00:00+00:00`로 고정하고 실제 수집·조회 메타데이터 시계는 실행 시각을 사용한다. 초기 DB 지문은 비공개 `target/inputs.json`에 보존한다.

외부 네트워크 연결은 대상 프로세스의 Python socket audit hook으로 거부하고 `Provider.request`·`Toss.request`는 차단했다. DNS 차단도 재현 코드에 포함한다. 수집기는 시작하지 않으며 시세 수집 함수만 결정적 합성 재생 함수로 대체했다. LLM·임베딩·실제 토스 인증 호출은 0회다. 독립 네트워크 namespace/firewall 격리는 아니다. 별도 합성 쓰기 스레드가 기존 `archive.store`를 5초마다 실행해 한 기사의 정정 버전을 추가한다. 전체 수집·가공 작업자의 운영 적체와 재시도 동작을 재현하지는 않는다. 일부 시장 기준 ETF·미국 캘린더 입력이 없어 시장 API는 미확인/누락 상태도 반환하며 정상 가격으로 채우지 않는다. 차트 API에는 실제 합성 관측 60점이 존재한다.

첫 실행 전 6개 API를 조회하고 100 VU·30초 smoke를 실행했으므로 이후 정규 단계는 warm 프로세스/DB다. OS 캐시는 통제하지 않았다. UTC/KST 기록을 보존하며 NTP offset은 미측정이다. 실제 브라우저 접근은 `The browser access host is unavailable`로 실패했다. 화면 지연과 사용자별 요청 빈도 보정은 미검증이며 HTTP 가상 세션을 렌더링 브라우저라고 부르지 않는다.

## 사전 계획과 실행

100명 정규 측정의 압축 원시 metric은 5,033,684 bytes, 약 166 bytes/요청이었다. 같은 비율만 적용해도 10,000명·2시간에는 약 6.04GB가 필요하므로 현재 1 GiB 출력 보호 한도로는 장기 계측도 완주할 수 없다. 이번 실제 중단 원인은 스레드 한도였고 출력 한도는 발동하지 않았다. 향후 장기 실행에는 저장량/계측 방식을 먼저 산정하고 새 출력 예산을 사전 고정해야 한다.

정상 단계의 계획은 100/1,000/5,000명 각 10분, 10,000명 30분, 별도 2시간이다. 정상 예산은 API별 p95 ≤1초·p99 ≤3초·시도 요청 실패율 ≤0.1%, 복귀 예산 60초다. 같은 호스트를 보호하는 사전 중단 한도는 발생기 RSS 4 GiB, 두 프로세스 합계 RSS 6 GiB, 서버 스레드 384개, 한 회차 압축 원시 출력 1 GiB다. 5초 샘플이므로 샘플 사이 최고점은 미측정이다. 낮은 단계에서 자원 중단이 발생하면 정규 증가는 중단하고 같은 한도를 적용한 10,000 VU 진단 시도와 낮은 부하의 도착률·집중·장애 검사를 분리한다. 짧은 진단은 정규 유지로 세지 않는다.

```sh
python3 scripts/serve_load_fixture.py --root .data/validation/issue27/native-20261117/target --port 19227
python3 scripts/run_native_load.py --output .data/validation/issue27/native-20261117/run --manifest .data/validation/issue27/native-20261117/manifest.json --target-pid OWN_TARGET_PID --sender OWN_TERMINAL --task OWN_TASK --dispatch OWN_DISPATCH
python3 scripts/sample_load_host.py --watch-pid OWN_CONTROLLER_PID --root .data/validation/issue27/native-20261117/target --output .data/validation/issue27/native-20261117/host-telemetry.jsonl
python3 scripts/summarize_native_load.py .data/validation/issue27/native-20261117/run
```

정확한 k6 명령·환경·시작 시각·원시 출력·exit code는 각 회차의 `command.json`, `result.json`, `k6.log`, `metrics.json.gz`에 기록한다. manifest는 최초 프로토콜의 JSON pointer 형식으로 실제 격리 응답의 모드·기사 ID·검색 결과 수·종목 코드·가격·누락 상태·타임라인 종목과 점을 확인한다. 실제 조회한 기사 내용이나 시세 대신 합성 입력을 사용하며 정답 파일은 공개하지 않는다. 2xx 내용 오류를 포함해 실패율 분모는 시도한 요청이고 완료되지 않은 시도도 따로 보고한다. 원시 카운터의 `session_slot`으로 슬롯별 tick 시작/완료·연속 간격·유지 기간을 대조한다. `api_latency`는 native response timing의 HTTP 요청 duration이며 연결 대기/연결 시간은 native 별도 metric을 함께 확인한다. 실제 브라우저의 종단 지연과 동일시하지 않는다. 최종 재현 코드는 대상 시작 시 `target/manifest.json`도 생성한다. 이 파일은 페이지 이동·테마 필터를 추가한 후속 smoke용이며 최초 주요 회차의 manifest는 상위 디렉터리의 원본을 유지한다. 최초 v1을 재생하려면 자동 생성 manifest의 feed 배열을 처음 4개 검색 fixture로 제한한다.

CPU/RSS·스레드·열린 TCP 연결은 `ps`/`lsof`로 5초마다 수집하고 k6 송수신 bytes·dropped iteration·누락 poll을 기록한다. 전체 호스트의 network/disk·VM 통계와 격리 DB의 행 수·크기·읽기 probe 지연은 15초마다 기록하며 이 수치를 대상 프로세스만의 I/O로 해석하지 않는다. 쓰기 지연과 오류는 `writer.jsonl`에 기록한다. DB probe·쓰기 전체 시간은 순수 lock 대기 계측이 아니며 작업 큐 전체 적체는 미검증이다.

## 결과

최초 100 VU·30초 smoke는 실제 HTTP 1,515건, 내용·통신 오류 0건, 누락 poll 0건이며 정규 10분 또는 10,000명 유지 성과로 합산하지 않는다. 아래 정규·진단 회차는 동일 v1 workload SHA와 원래 비공개 manifest를 사용했다. 해당 manifest의 feed 그룹은 검색 4종이며 모든 페이지 이동·테마·생각 시간을 재현한 브라우저 보정 워크로드가 아니다.

| 실제 회차 | 실제 경과/종료 코드 | 시도 / native 완료 / 본문 검사 | 확인 실패 / 미검증 | 판정 |
| --- | --- | --- | --- | --- |
| 100명 정규 10분 | 608.22초 / 0 | 30,300 / 30,300 / 30,300 | 0 / 0 | 이 합성 v1 프로필의 정상 예산 통과 |
| 1,000명 정규 10분 계획 | 10.77초 / 105 | 3,918 / 1,915 / 1,211 | 1,089 / 2,588 | 스레드 안전 한도 중단, 유지 미달 |
| 10,000 VU 30초 진단 | 12.88초 / 105 | 2,364 / 87 / 0 | 0 / 2,364 | 안전 한도 중단, 활성 10,000명 미도달 |
| 1,000명 상당 도착률 60초 smoke | 10.75초 / 105 | 3,850 / 1,849 / 1,122 | 1,038 / 2,610 | 안전 한도 중단, dropped iteration 711 |
| 동기 폴링 100명 60초 smoke | 67.04초 / 99 | 3,038 / 3,038 / 3,038 | 828 / 0 | 실패 27.25%, 누락 poll 45회, 예산 미달 |

native 완료는 연결 실패도 포함한 k6 `http_reqs`의 종료 수이며 성공 건수가 아니다. 묶음 요청이 중단되면 전송이 끝난 요청도 JS 본문 검사를 거치지 않을 수 있다. 확인 실패는 native HTTP/통신 실패와 본문 내용 오류를 합치고 중복을 제외한다. 미검증은 시도에서 확인 실패와 본문 검증 성공을 뺀 수로서 미완료와 내용 미검사 응답을 포함한다. 중단 회차에서 이를 정상 0% 오류로 표현하지 않는다. 1,000명은 실패+미검증 93.85%, 10,000 VU 진단은 100%다. k6 1211 오류는 [공식 오류 코드](https://grafana.com/docs/k6/latest/javascript-api/error-codes/)의 연결 시도 시간 초과이며 v1의 넓은 connection 분류와 별도로 집계했다. 해당 오류는 각각 1,089/0/1,038/828건(위 표의 두 번째부터 다섯 번째 회차)이다.

시도 카운터는 `http.batch` 호출 직전에 제출할 항목을 센다. 강제 중단의 경계에서는 실제 네트워크 전송을 시작하지 못한 항목도 포함할 수 있으며 이를 미검증에서 제외하거나 성공으로 세지 않는다. 전송 완료가 확정된 분모는 native 완료 수다. 정상 100명 회차는 세 분모가 모두 일치하지만 중단 회차는 제출·전송·내용 검사 수를 서로 대체하지 않는다.

100명 정규 단계는 100개 슬롯 각각 120회 반복했고 최소 슬롯 관측 기간은 594.999초, 반복 간격 p50 5.0000초·p95 5.0013초·최대 5.0797초, 누락 poll 0회다. 600초 native 관측 창의 실제 시도 RPS는 50.50, 완료 RPS는 50.488이며 종료 drain을 포함한 native event 창의 완료 처리량은 50.090 RPS다. 정상 구간의 k6 수신은 1,522,986,300 bytes, 송신은 2,759,100 bytes다. 1,000명 중단 회차의 관측 요청 시작 span은 약 375.21 RPS, native event 창의 완료 처리량은 182.95 RPS다. 10,000 VU 진단은 각각 347.41/9.64 RPS이며 이 짧은 비율을 유지 처리량으로 부르지 않는다. 전체 요청 기간을 분모로 하는 중단 회차 RPS는 각 비공개 aggregate에 따로 기록했다.

| API, 100명 정규 10분 | 분모 | p50 ms | p95 ms | p99 ms |
| --- | ---: | ---: | ---: | ---: |
| dashboard | 12,000 | 85.38 | 586.72 | 1,122.55 |
| market | 7,200 | 31.37 | 270.07 | 537.84 |
| feed | 3,000 | 91.06 | 382.23 | 660.41 |
| quotes | 6,000 | 6.72 | 71.32 | 145.44 |
| timeline | 1,800 | 6.80 | 70.20 | 159.36 |
| detail | 300 | 121.23 | 519.44 | 961.84 |

1,000명 회차는 서버 스레드 549개·열린 TCP 540개·RSS 약 181MB·샘플 CPU 763.1%를 관측했고 발생기 RSS 약 504MB였다. 10,000 VU 진단은 서버 스레드 871개·TCP 862개·RSS 약 130MB, 발생기 RSS 약 1.642GB·TCP 864개였다. 5초 간격 사이 최고점은 알 수 없다. 중단은 메모리 한도나 발생기 도구 부재가 아니라 **같은 호스트 보호를 위한 서버 스레드 384개 한도**에 따른 것이다. 단일 물리 호스트에서 서버 한계와 발생기의 영향을 완전히 분리한 최대 성능 판정은 아니다. 발생기 10,000 VU 설정에서 초기화 counter는 9,992개였지만 실제 tick을 시작한 슬롯은 938개, 완료 round는 0개였다. 유휴/초기화 수를 활성 10,000명으로 세지 않는다. 1,000명도 슬롯은 1,000개지만 최소 유지 기간은 0초여서 최고 정규 유지 부하에 포함하지 않는다.

최고 **측정해 10분 유지하고 이 프로필 예산을 통과한 부하**는 100명이다. 100~1,000명 사이의 최대치는 탐색하지 않았다. 1,000명에서 안전 한도를 넘어 5,000명 정규 단계와 10,000명 정상 30분·별도 2시간은 실행하지 않았다. 30초 진단을 해당 기간 대신 제출하지 않는다. 이 로컬 사전 자원 예산에서 10,000명 목표는 미달이며, 실제 운영 규모·두 물리 호스트·브라우저 보정 워크로드의 지원 가능성은 미검증이다.

## 100명에서의 장애·복구와 보존 검사

100명·12분 연속 HTTP 회차는 경과 730.05초, exit 0으로 끝났다. 시도·native 완료·본문 검사 모두 36,360건, 검증 성공 35,058건, 장애를 포함한 실패 1,302건(3.5809%), 미검증 0건, 누락 poll 0회다. 내용 계약 실패 1,165건과 통신 실패 137건을 정상 예산과 분리한다. exit 0은 fault 모드에서 정상 threshold를 적용하지 않은 실행 종료 상태이며 정상 0.1% 오류 예산 통과를 뜻하지 않는다.

429·5xx·timeout·가격 누락은 실제 외부 HTTP 서버 대신 **시세 수집 함수 경계의 합성 예외 재생**이다. 429/5xx는 ValueError, timeout은 2초 지연 후 TimeoutError를 사용했다. 실제 제공처의 HTTP 프로토콜·쿼터·backoff 검증은 미검증이다. DB는 이 사본에 5초 `BEGIN IMMEDIATE` 잠금을 걸었고 짧은 DB I/O 실패는 별도로 주입하지 않았다. 재시작은 이 격리 서버와 그 안의 합성 쓰기 스레드만 대상으로 했다. 독립 운영 data-worker의 큐 복구를 검증한 것은 아니다.

| 장애 | 주입 구간, 회차 시작 기준 | 제거 후 API 복귀 | 범위 |
| --- | --- | ---: | --- |
| 합성 429 | 30~55초 | 7초 | 100명 부하 유지 |
| 합성 5xx | 140~165초 | 9초 | 100명 부하 유지 |
| 합성 timeout | 250~275초 | 8초 | 100명 부하 유지 |
| 일부 가격 누락 | 360~385초 | 10초 | 100명 부하 유지 |
| 복사 DB 쓰기 잠금 | 470~475초 | 0초 | 잠금 해제 이후 창, 대기 시간 0이라는 뜻 아님 |
| 격리 서버 재시작 | 580~582초 | 1초 | old PID 32186 → new PID 42294 |

복귀 시간은 제거 이후 1초 간격으로 찾은 **60초 연속 오류 0건**, API p95/p99 예산 충족, 100개 슬롯 각각 최소 11회 heartbeat를 만족하는 창의 시작 시각이다. 오류 0건 조건은 0.1% 예산보다 보수적인 후처리 확인이며 실제 ready 시각의 밀리초 계측은 아니다. 각 창의 시도는 3,030건이었다. 모든 API 복귀 창은 60초 이내였으나 실제 작업 큐 적체 정상화까지 포함한 전체 복구 판정은 미검증이다. 10,000명 장애·부하 감소 후 복구를 대신하지 않는다.

기사 1,000개의 원본 payload 지문과 합성 정정 355개의 payload 지문을 대조해 소실/지문 불일치 0건을 확인했다. 정정 키는 0~354까지 공백이 없고 합성 쓰기 성공 355건에 대해 DB 누락과 성공 키 중복이 0건이었다. 관측 2,160행은 기준 payload 지문을 유지했다. 합성 쓰기 지연 중앙값은 약 2.11ms, 최대 7.225초이며 82회 보조 DB probe에 오류는 없었다. 쓰기 전체 지연과 DB probe 시간은 순수 lock 대기를 분리한 수치가 아니다.

독립 quote probe는 319회, 4개 코드씩 약 2초 간격으로 실행했고 관측 범위에서 잘못된 코드와 장애 중 새 정상값 위장은 0건이었다. 재시작 중 URLError 1회를 기록했다. probe는 첫 429 구간 이후 시작했으므로 429의 독립 정상값 위장 검사와 전체 코드·상세의 모든 관련 종목 정답 검증은 미검증이다. 실제 quote와 chart는 별개의 합성 fixture stream이며 금융적 일관성/실제 시장 정확도를 평가하지 않는다.

```sh
python3 scripts/run_native_load.py --faults-only --target-root PRIVATE_TARGET_ROOT --output PRIVATE_NEW_FAULT_OUTPUT --manifest PRIVATE_V1_MANIFEST --target-pid OWN_TARGET_PID --sender OWN_TERMINAL --task OWN_TASK --dispatch OWN_DISPATCH
python3 scripts/observe_load_content.py --watch-pid OWN_FAULT_CONTROLLER_PID --directory PRIVATE_NATIVE_RUN_DIRECTORY
python3 scripts/serve_load_fixture.py --root PRIVATE_TARGET_ROOT --verify --baseline PRIVATE_BASELINE_JSON
```

payload 보존 검사는 실제 실행한 `--verify`로 재현했으며 exit 0이다. 원본 DB/전체 corpus나 실제 가격 정답을 읽는 검사가 아니다. baseline은 비공개 `integrity-before.json`의 sample 행 지문을 사용한다. baseline을 생략한 inventory 검사에서는 과거 sample 보존을 통과로 간주하지 않는다.

## 추가 smoke, 재현성, 남은 검증

합성 catalogue와 business/relations/supply 규칙의 지문·개수는 비공개 `knowledge-manifest.json`에 기록했다. 이 추가 지문은 실행 후 착수 커밋과 파일이 동일함을 대조해 재구성한 것으로, 실행 전 별도 계측한 자료라고 주장하지 않는다. DB 초기 지문·고정 workload/manifest·단계 예산은 앞서 기록한 원시 사전 자료를 사용한다.

재시작 후 생성한 후속 manifest는 검색뿐 아니라 전체 목록·다음 cursor 페이지·테마 결과/빈 결과를 포함한다. 이 manifest와 `POPULAR=1`로 100명·60초를 추가 실행했다. 경과 66.57초, exit 0, HTTP 3,030건 모두 내용 검사 성공, 누락 poll 0회였다. feed p50/p95/p99는 81.40/366.22/429.97ms(300건)다. 이 회차는 단기 기능·부하 smoke이며 v1 정규 유지와 동일 프로필의 인기/분산 대조 시험이 아니다. 10,000명 인기 집중·cold cache·장기 유지 결과는 미검증으로 남긴다.

경로별 p50/p95/p99·분모, 각 회차 CPU/RSS/연결의 처음/마지막/최고/분위수, 전송량·연결 시간·실패/미검증과 회차별 exit code는 [비민감 전체 집계](native_aggregates.json)에 있다. 중단 회차의 HTTP duration에는 연결 실패의 0ms와 검사하지 못한 요청의 검열이 있으므로 그 낮은 분위수를 성능 통과로 해석하지 않는다. 연결 시도 시간의 전체 p95는 1,000명 중단에서 약 3.934초, 동기 100명에서 약 3.938초였다. 원시 오류 로그에는 dial i/o timeout과 클라이언트 중단 뒤 BrokenPipe/ConnectionReset이 존재한다. DB만이 원인이라고 단정할 근거는 없다.

실행 중 추가한 평가 도구는 `serve_load_fixture.py`, `run_native_load.py`, `sample_load_host.py`, `observe_load_content.py`, `summarize_native_load.py`와 실제 HTTP/복구·집계 검사 `test_native_load.py`다. 제품 파일은 변경하지 않았다. 첫 대상/제어 스크립트의 실행 소스는 착수 시 기록한 SHA와 일치하는 복원 사본을 비공개로 보존했다. 재시작에는 합성 쓰기 번호 재개·manifest 생성·DNS 차단을 추가한 harness 버전을 사용했으며 그 실행 소스도 따로 보존한다. 실제 `server.py`·데이터 제품 모듈·k6 workload는 주요 회차 사이에 바꾸지 않았다. 따라서 운영 worker의 동일 버전 재시작 검증으로 확대하지 않는다.

Node 계약 검사 6개, Python 계획 검사 2개, 새 Python 검사 5개(실제 HTTP·SQLite·재시작·변조 검출·기존 비표시 DB 보호 포함)는 모두 exit 0이다. Python 5개 도구와 기존 JS 발생기의 구문 검사도 exit 0이다. 네이티브 부하 회차의 105/99 종료는 위 표대로 실패/중단 결과로 보존했으며 검사 통과로 덮지 않았다. 자신이 만든 대상 서버와 부하 발생기는 종료했다. main 병합·push·배포·외부 댓글은 하지 않았다.

필요 후속 검증은 먼저 두 물리 호스트/전체 기록 입력과 브라우저 추적을 준비하고, 100~1,000명 사이 자원 증가와 접속 timeout의 원인을 계측하는 것이다. 수락/동시 처리 한도·캐시·반복 SQLite 초기화/조회 비용은 프로파일링 후보이며 이번 결과만으로 특정 개선의 효과를 주장하지 않는다. 이후 동일 프로필로 정상 5,000/10,000명·30분/2시간·도착률·집중/분산·cache·독립 worker/큐 무결성·실제 외부 오류 경계 검증을 수행해야 한다.

원시 산출물은 `/Users/project/orca/workspaces/research_agent/eval-27/.data/validation/issue27/native-20261117/`의 `environment.json`, `target/inputs.json`, `run/`, `fault-run/`, `extra-probes/`, `host-telemetry.jsonl`, `fault-host-telemetry.jsonl`, `content-probes.jsonl`, `integrity-before.json`, `integrity-after.json`, `integrity-repro-check.json`, 실행 소스 사본과 `checks/`에 보존했다. 이 경로의 DB·합성 가격·fixture 정답·원시 trace는 Git에 추가하지 않았다.
