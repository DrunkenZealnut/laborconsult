# missing-calculators — Gap Analysis Report

> **Feature**: missing-calculators (누락 계산 기능 추가)
> **Date**: 2026-03-20
> **Design**: `docs/02-design/features/missing-calculators.design.md`
> **Match Rate**: **97%**

---

## Overall Scores

| Category | Score | Status |
|----------|:-----:|:------:|
| FR-01: ordinary_wage Registry | 100% | PASS |
| FR-02: CALC_TYPE_MAP 22 Keys | 100% | PASS |
| FR-03: working_hours Module | 93% | PASS |
| FR-04: annual_leave Output | 100% functional | PASS |
| FR-05: Keyword Fallback | 100% | PASS |
| **Overall** | **97%** | **PASS** |

분석 항목 57건: **53 MATCH, 4 CHANGED (의도적), 2 POSITIVE, 0 MISSING**

---

## FR-01: ordinary_wage Registry (11항목 — 100%)

CALC_TYPES, _STANDARD_CALCS, CALC_TYPE_MAP, 래퍼 함수, _pop_ordinary_wage 모두 설계대로 구현. 1건 의도적 변경: `_calc_ordinary_wage_standalone` (private 네이밍).

## FR-02: CALC_TYPE_MAP 22개 키 (22항목 — 100%)

22개 신규 매핑 키 전량 일치. 기존 매핑 변경 0건.

## FR-03: working_hours 모듈 (15항목 — 93%)

WorkingHoursResult 6필드, calc_working_hours() 시그니처, 공식 `(weekly+holiday)×365/12/7` 모두 일치. 1건 의도적 변경: `MONTHLY_STANDARD_HOURS` 미임포트 (동적 계산이 비표준 스케줄도 처리하므로).

## FR-04: annual_leave 출력 (4항목 — 100% functional)

`"법정 연차 발생일수"` 키 추가 확인. 2건 의도적 변경: 기존 코드베이스의 짧은 키 네이밍 컨벤션 유지 (`"미사용 연차"`, `"연차수당"`).

## FR-05: 키워드 폴백 (5항목 — 100%)

5개 신규 키워드 그룹 전량 일치.

---

## 의도적 변경 4건

| # | 설계 | 구현 | 사유 |
|:-:|------|------|------|
| C1 | `calc_ordinary_wage_standalone` | `_calc_ordinary_wage_standalone` | Python private 컨벤션 |
| C2 | `import MONTHLY_STANDARD_HOURS` | 미임포트 | 동적 공식이 모든 스케줄 처리 |
| C3 | `"미사용 연차일수"` | `"미사용 연차"` | 기존 코드베이스 컨벤션 |
| C4 | `"미사용 연차수당"` | `"연차수당"` | 기존 코드베이스 컨벤션 |

## 테스트 검증

기존 116건 CLI 테스트 전량 통과. 모든 변경은 추가 전용 — 기존 계산기 로직 수정 0건.

---

## 결론

- **Match Rate: 97%** — Report 단계 진행 가능
- 0건 MISSING, 4건 의도적 개선, 2건 긍정적 편차
- 버그/회귀: 0건
