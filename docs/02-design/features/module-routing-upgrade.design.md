# Design: 모듈 라우팅·부분실행·지식모듈 업그레이드

> Feature: `module-routing-upgrade`
> Created: 2026-07-05
> Level: Dynamic
> 배경: 2026-07-04 "2026년 최저임금" 환각 사건 — 조회성 질문이 어떤 모듈에도 배치되지
> 않아 LLM 학습 지식(과거 값)으로 답변. 라우팅 공백이 근본 원인.

---

## 1. Overview

"질문 분석 → 계산기 배치 → 산출물 통합" 구조는 유지하되, 세 지점을 보강한다:

1. **라우팅 명시화** — 묵시적 `minimum_wage` 폴백 제거, 단계별 로그로 오배치 관측 가능화
2. **부분 실행** — 임금 정보가 없어도 임금 불필요 계산기(근로시간 계열)는 실행
3. **지식 모듈 등록제** — "계산은 아니지만 검증된 사실 주입"을 등록형 패턴으로 일반화

모듈별 LLM 호출 + 통합 LLM(풀 에이전트) 방식은 채택하지 않음 — 모듈 산출이
결정적(deterministic)이라 단일 composer LLM으로 충분하고, Vercel serverless에서
지연·비용만 증가.

## 2. 라우팅 — `pipeline._resolve_targets()`

기존: `CALC_TYPE_MAP.get(calc_type, ["minimum_wage"])` (pipeline)
— 미매칭 라벨이 **조용히** 최저임금 검증기로 배치, registry의 키워드 폴백도 미사용.

개선: 4단계 명시 라우팅, 각 단계 `logger.info`:

| 단계 | 방법 | 결과 |
|------|------|------|
| ① | `resolve_calc_type_strict()` (registry 신규) — 정확 매칭→구분자 분리→키워드 | 매칭 시 반환 |
| ② | `infer_calc_types(query)` (storage.py 기존 재활용) + `CALC_TYPES` 필터 | 추론 성공 시 반환 |
| ③ | 임금 정보 존재 시 `["minimum_wage"]` | 기존 동작 보존 (로그 명시) |
| ④ | 미확정 | `None` → 계산기 미실행, 상담 경로 |

`resolve_calc_type()`은 strict 래퍼로 유지 — 벤치마크·chatbot.py 기존 동작 무변경.

## 3. 부분 실행 — `_WAGELESS_TARGETS`

기존: `wage_amount` 없으면 `return None` (전부 아니면 전무).

개선: `{"working_hours", "weekly_hours_check"}`는 schedule만으로 실행.
- 0원 오검증 방지 2중 장치:
  - `result.py::format_result` — 통상시급 0원이면 "최저임금 충족" 판정 라인 숨김
  - `pipeline` — 임금 미제공 시 `[통상임금]` 계산식 제거
- 화이트리스트 확장 조건: WageInput 임금 필드 없이 의미 있는 산출 가능 +
  facade 가드(`business_size_input`, `arrear_amount` 등) 통과 확인 후 추가

## 4. 지식 모듈 — `_KNOWLEDGE_MODULES`

빌더 시그니처: `(query, analysis) -> str | None` (None = 미트리거)

| 모듈 | 트리거 | 데이터 출처 |
|------|--------|------------|
| 최저임금 | 키워드 + calculation_types | `MINIMUM_HOURLY_WAGE` (최근 3개년) |
| 4대보험요율 | 키워드 | `INSURANCE_RATES` (해당 연도) |

- 실패 시 `logger.warning` 후 무시 (graceful degradation 컨벤션 준수)
- 신규 모듈(연차 발생 기준, 비과세 한도 등)은 리스트 등록만으로 주입

## 5. 검증

- 로컬(pure-stdlib): registry strict/호환성, wageless 계산 실행 출력, 지식모듈 수치 정확성
- 배포 후: 임금 없는 근로시간 질문("주 45시간 근무면 52시간 위반인가요?") →
  `weekly_hours_check` 부분 실행 + 오판정 라인 부재 확인
