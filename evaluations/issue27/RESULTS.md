# #27 실행 결과: 10,000명 목표 미검증

2026-11-17 KST에 Task `task_620216ae4c21`, Dispatch `ctx_9513085d3f9c`를 독립 Worktree `/Users/project/orca/workspaces/research_agent/eval-27`, 브랜치 `kingrangE/eval-27`에서 수행했다. 실제 시작 HEAD는 `f7b9190c5bba1166cba2166d4361f2cb0712ed86`으로 Coordinator의 지정값과 일치한다. 이슈 본문의 과거 기준 `e5d97c7`로 되돌리지 않았다. 변경 커밋은 이 브랜치의 이 보고서를 포함한 커밋으로 확인할 수 있다. main 병합, push, 배포, 이슈 종료, 외부 댓글은 하지 않았다.

이번 결과는 버전 고정 발생기·사전 계획·계약 검사와 미실행 조건의 제출이다. 10,000명 정상/장기/요청 집중/장애 평가의 실행 완료나 지원 가능 판정은 아니다. 독립 발생기·대상 자원, 기록된 전체 입력 사본, 브라우저 추적, k6 실행 파일이 제공되지 않아 HTTP 부하는 실행하지 않았다. 운영 컨테이너·원본 Linux 볼륨·공유 인증에는 접근하거나 변경하지 않았다. LLM·임베딩·토스 호출은 모두 0회다.

## 변경 경계

`scripts/load_active_sessions.js`에 k6의 고정 세션과 별도 도착률 시험을 추가했다. 60/25/15 혼합, 분산/동기 폴링, 인기/분산 fixture, 시도/실패/미실행 기대 분모, 경로별 지연, 2xx 내용 대조와 통신 오류 분류를 제공한다. 세션별 tick 시작·완료를 숫자 슬롯으로 기록하고 지연 때문에 생략한 round를 드러낸다. 정상/fault/recovery 회차를 분리할 수 있으며 실제 장애 주입은 구현하지 않았다. 결과 요약만으로 10,000명 통과를 선언하지 않는다.

`scripts/plan_active_sessions.py`는 환경·시계·지문·초기 예산·단계별 예상 요청 수를 네트워크 없이 기록한다. `tests/test_active_sessions.mjs`와 `tests/test_active_sessions_plan.py`는 실제 발생기 코드의 계약/분모를 검사한다. JS 검사는 native k6 대신 transport/metric shim을 사용하며 HTTP나 브라우저를 실행하지 않는다. `evaluations/issue27/PROTOCOL.md`는 실행 자원 산정, 비공개 fixture 형식, 재현 명령, 계측, 장애·복구·무결성 판정을 기록한다. 제품 API·UI·공유 모듈 변경은 없다.

## 환경과 사전 예산

환경은 macOS 26.3.1 arm64, Apple M2 Pro 논리 CPU 12개, RAM 17,179,869,184 bytes(16 GiB), Python 3.13.2, Node v23.10.0이다. 같은 호스트에서 다른 평가 Worker가 병행하므로 격리 성능 환경이 아니다. native k6는 없다. 실행 모드는 plan-only-no-http이며 대상 서버/작업자 수·캐시·DB·전체 상장 목록·가격/기사 수·관계 규칙 지문은 미확보다. 코드와 UI 지문은 비공개 preflight에 기록했다. 시각은 UTC 기록/KST 실행, 스케줄 설명은 k6 executor와 Date.now 기반이며 NTP offset은 미측정이다.

정상 예산은 API별 p95 ≤1초, p99 ≤3초, 시도한 요청 중 실패율 ≤0.1%다. 장애 제거 후 복귀 예산은 60초, 기사/정정 소실·잘못된 종목·정상값 위장은 0건이다. 이 예산은 계획 출력에 고정했다. 전용 호스트 최소 2대와 소수 브라우저가 필요하며 전체 정상 단계만 최소 3시간이다. CPU/RAM·네트워크·원시 출력 저장량과 비용은 부하를 실행하지 않아 미산정이다. 구매·운영 부하 권한은 사용하지 않았다.

소스 기반 임시 혼합의 예상값은 10,000명에서 5,050 RPS, 30분 9,090,000 HTTP 요청, 별도 2시간 36,360,000 요청이다. 100/1,000/5,000명 각 10분의 예상 요청은 각각 30,300/303,000/1,515,000건이다. 실제 UI의 가시성·캐시·모달·클릭·생각 시간에 따른 빈도는 브라우저 추적으로 보정하지 못했으므로 실제 사용자 빈도로 확정하지 않는다.

## 검사 결과와 실측 분모

| 실행 명령 | 종료 코드 | 결과 |
| --- | ---: | --- |
| `node --test tests/test_active_sessions.mjs` | 0 | 6개 계약 검사 통과, 합성 transport/metric 사용 |
| `python3 -m unittest discover -s tests -p test_active_sessions_plan.py` | 0 | 2개 분모/유효성 검사 통과 |
| `node --check scripts/load_active_sessions.js` | 0 | 구문 검사 통과, k6 runtime 검증 아님 |
| `python3 -m py_compile scripts/plan_active_sessions.py` | 0 | 구문 검사 통과 |
| `git diff --check` | 0 | 공백 오류 없음 |
| `command -v k6` | 1 | 실행 파일 없음, native 실행 미검증 |
| `TZ=Asia/Seoul python3 scripts/plan_active_sessions.py --output .data/validation/issue27/preflight-final.json` | 0 | 계획·환경·예산 기록, HTTP 요청 없음 |

계약 검사는 10,000개 숫자 슬롯의 30초 혼합을 열거해 151,500개의 **계획 항목**과 5,050 예상 RPS를 확인했다. 이 항목은 활성 접속·시도 요청·실측 RPS에 합산하지 않는다. JSON 오류, 잘못된 symbol/상태, 누락 필드, timeout/연결/5xx, 지연된 poll의 누락 집계, 잘못된 격리 선언의 거부를 검사했다. native k6 scheduler/메트릭과의 호환성은 미검증이다.

실측 HTTP 시도 0건, 완료 0건이며 실제 활성 세션 수·최고 10분 유지 부하·도달/완료 RPS·경로별 p50/p95/p99·오류율은 모두 미산정이다. 오류율 분모 0을 0% 성공으로 표현하지 않는다. 실행을 예약하지 않았으므로 미실행 기대 요청 수 역시 미산정이며 계획 수 전체를 실제 dropped request라고 부르지 않는다. CPU/RSS 추이·네트워크·디스크·스레드/연결·DB lock 대기·작업 적체와 복귀 시간은 미측정이다. 원시 HTTP·시세·브라우저 trace는 생성하지 않았다.

| 판정 항목 | 판정 | 근거/제약 |
| --- | --- | --- |
| 요청 혼합·분모·오류 계약 | 로컬 검사 통과 | native runtime·실제 대상 성능과 별개 |
| 10,000명 정상 30분/장기 2시간 | 미검증 | 전용 자원·입력·발생기 실행 파일 없음 |
| 기대 도착률·동기 집중·인기 종목·캐시 비교 | 미검증 | 시나리오 제공, 실행하지 않음 |
| 장애·60초 복구·기사/정정/작업 무결성 | 미검증 | 격리 DB·작업자·오류 재생 환경 없음 |
| 발생기/서버/DB/외부 지연 원인 분리 | 미검증 | 해당 계측이 없음 |
| 실제 브라우저 빈도·화면 지연 | 미검증 | 브라우저 추적/교차 측정 없음 |

필요 후속 검증의 우선순위는 전용 발생기/대상 확보와 native k6 소규모 호환성 확인, 외부 egress 차단 및 입력 사본·내용 정답 고정, 브라우저 요청 빈도 보정, 낮은 단계부터 자원·출력량 확인, 10,000명 정상/장기·도착률·집중·캐시 비교, 마지막으로 격리 장애·복구·무결성 검증이다. 병목을 실측하지 않았으므로 서버·DB 개선안을 성능 원인으로 단정하지 않는다. 현 상태로 이슈의 전체 성능 평가 완료나 10,000명 지원을 승인할 근거는 없다.

비공개 원시 산출물은 `/Users/project/orca/workspaces/research_agent/eval-27/.data/validation/issue27/preflight-start.json`, `preflight-final.json`, `checks/commands.json`, `checks/1.log`부터 `checks/6.log`에 있다. 시작 기록과 최종 계획의 발생기 지문은 작업 중 변경으로 다를 수 있으며 최종 계획이 제출 코드의 지문이다. `.data/`는 Git에서 제외했다. 이 보고서에는 비민감 집계만 포함한다.
