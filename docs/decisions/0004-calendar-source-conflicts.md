# 공급자 캘린더와 거래소 공표가 상충할 때

결정일: 2026-11-16. 검수 가격 수집 중 발견한 #5·#10·#11의 거래일 정합성 문제다.

## 실제 증상과 재현

- 일부 미국 휴장일에 일봉이 없는데 공급자 캘린더는 정규장 개장으로 저장됐다. 실제 2020-12-25 직접 조회도 정규장 시간을 반환했다. 거래정지나 가격 수집 실패로 단정할 수 없는 공급자 일정 상충이다.
- 별도로, 다른 날짜 응답의 이전·다음 영업일 정보가 이미 직접 조회한 날짜의 휴장 상태를 덮어쓸 수 있었다.
- `python3 -m unittest tests.test_market_history.HistoryTest.test_neighbor_calendar_cannot_overwrite_direct_holiday -q`는 수정 전 실패했다. 실제 반응 계산 경로의 `test_real_calendar_consumer_uses_exchange_holiday_without_rewriting_vendor`도 대응일을 12월 28일 대신 25일로 골라 실패했다.

## 선택한 처리와 대안

- 직접 조회한 날짜는 주변 날짜의 응답으로 덮어쓰지 않는다. 다만 직접 조회 자체도 잘못된 사례가 있어 이 우선순위만으로 해결됐다고 보지 않는다.
- 원문 응답과 원시 캘린더를 보존하고 공통 조회 경로에서 검토한 거래소 공표 예외를 적용한다. 휴장·조기 폐장 날짜와 출처를 별도 자료로 관리한다. 원본 일정, 보정 일정, 상충 여부와 근거 링크를 함께 남긴다.
- 가격이 없는 평일을 자동 휴장 처리하거나 모든 평일을 개장으로 가정하는 대안은 거래정지·누락과 휴장을 혼동하므로 배제했다. 휴일 계산식을 직접 만드는 대신 공식 표의 날짜를 사용한다. 현 범위는 작은 공개 일정 자료로 처리할 수 있어 대형 거래 캘린더 의존성을 추가하지 않았다.
- 명시된 예외 외 날짜는 공급자 값을 유지한다. 이 자료가 모든 국가·선물·옵션·장외 세션·돌발 휴장을 검증한 것은 아니다. 조기 폐장일에 개장 세션 자체가 없으면 시각을 만들지 않고 미확인 상태를 남긴다.

## 재현·롤백 경계

- 일봉 반응, 테마 통계, 커버리지, 검수 가격 대조가 동일한 캘린더 조회를 사용한다. 현지 시간대의 13시 폐장은 DST를 포함해 변환한다.
- 공표 자료의 버전·지문을 계산 입력에 포함한다. 기존 계산을 덮어쓰지 않고 이전 일정 기준이라는 표시를 붙인다. 이전 고정 입력의 재실행도 유지한다.
- 현재 웹 공표 자료의 모든 과거 개정본은 확보하지 못했다. 당시 가용 일정·시세라고 주장하지 않으며 사후 가격 관측으로 제공한다. 상충이 발견되면 기존 커버리지·모형·통계를 다시 검증해야 한다.

## 공식 근거

- [NYSE 2019–2021 일정](https://ir.theice.com/press/news-details/2018/NYSE-Group-Announces-2019-2020-and-2021-Holiday-and-Early-Closings-Calendar/default.aspx)
- [NYSE 2022–2024 일정](https://ir.theice.com/press/news-details/2021/NYSE-Group-Announces-2022-2023-and-2024-Holiday-and-Early-Closings-Calendar/default.aspx)
- [NYSE 2024–2026 일정](https://ir.theice.com/press/news-details/2023/NYSE-Group-Announces-2024-2025-and-2026-Holiday-and-Early-Closings-Calendar/default.aspx)
- [2025-01-09 추가 휴장](https://ir.theice.com/press/news-details/2024/The-New-York-Stock-Exchange-Will-Close-Markets-on-January-9-to-Honor-the-Passing-of-Former-President-Jimmy-Carter-on-National-Day-of-Mourning/default.aspx)
- [Nasdaq 2020 연말 휴장·조기 폐장](https://www.nasdaqtrader.com/TraderNews.aspx?id=ETA2020-85)
