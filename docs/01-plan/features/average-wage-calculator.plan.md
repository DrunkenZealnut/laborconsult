# average-wage-calculator Planning Document

> **Summary**: 평균임금 독립 계산 모듈 신설 — nodong.kr AverageWageCal 참조
>
> **Project**: laborconsult (노동법 임금계산기)
> **Author**: Claude PDCA
> **Date**: 2026-03-08
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 평균임금 계산이 severance.py 내부 private 함수로만 존재하여 독립적으로 산정 불가. 산재·감급·휴업 등 퇴직금 외 용도로 활용 불가 |
| **Solution** | 독립 `average_wage.py` 모듈 신설 + severance.py 리팩터링 + facade/chatbot 매핑 추가 |
| **Function/UX Effect** | "평균임금" 단독 질문에 즉시 응답 가능 + 월별(기본급+기타수당) 세분화 입력 + 통상임금 비교 자동 출력 |
| **Core Value** | 근로기준법 제2조(평균임금) 완전 구현 + nodong.kr 정합성 달성 + 계산기 재사용성 확보 |

---

## 1. Overview

### 1.1 Purpose

평균임금은 퇴직금·산재보상·감급·휴업수당·실업급여 등 노동법 전반에서 사용되는 핵심 지표이다.
현재 시스템에서는 `severance.py` 내부 `_calc_avg_daily_3m()`/`_calc_avg_daily_1y()` private 함수로만 존재하여,
퇴직금 없이 평균임금만 산정하는 것이 불가능하다.

nodong.kr의 평균임금 계산기(https://www.nodong.kr/AverageWageCal)를 참조하여
독립 모듈로 분리하고 facade·chatbot에서 직접 호출 가능하도록 보완한다.

### 1.2 Background

**nodong.kr 평균임금 계산기 주요 기능:**
- 입력: 입사일, 산정사유발생일, 월별 3개월 임금(기본급+기타수당), 연간 상여금, 연차수당, 1일 통상임금
- 공식: `1일 평균임금 = (3개월 임금총액 + 상여금×3/12 + 연차수당×3/12) / 3개월 총일수`
- 비교: 평균임금 < 통상임금이면 통상임금 적용 (근기법 시행령 제2조)
- 활용: 퇴직금(30일분), 산재보상, 감급(1/2 한도), 실업급여(60%), 휴업수당(70%)

**현재 코드 현황:**
| 항목 | 현재 상태 |
|------|-----------|
| 3개월 평균임금 계산 로직 | `severance.py:_calc_avg_daily_3m()` (private) |
| 1년 평균임금 계산 로직 | `severance.py:_calc_avg_daily_1y()` (private) |
| WageInput 관련 필드 | `last_3m_wages`, `last_3m_days`, `annual_bonus_total`, `unused_annual_leave_pay` 이미 존재 |
| facade CALC_TYPES | "평균임금" 항목 없음 |
| CALC_TYPE_MAP | "평균임금" 매핑 없음 |
| 독립 계산기 모듈 | 없음 |

### 1.3 Related Documents

- 참조: https://www.nodong.kr/AverageWageCal (nodong.kr 평균임금 계산기)
- 관련: `docs/01-plan/features/ordinary-wage-review.plan.md` (통상임금 리뷰)
- 법률: 근로기준법 제2조 제1항 (평균임금 정의), 시행령 제2조 (평균임금 < 통상임금 시)

---

## 2. Scope

### 2.1 In Scope

- [x] 독립 `wage_calculator/calculators/average_wage.py` 모듈 신설
- [x] `AverageWageResult` dataclass 정의 (1일 평균임금, 3개월 기준, 통상임금 비교 결과 등)
- [x] 월별 세분화 입력 지원 (기본급 + 기타수당 per month — nodong.kr 방식)
- [x] 산정사유발생일 기반 3개월 기간 자동 계산 (총일수)
- [x] 평균임금 vs 통상임금 비교 + 높은 쪽 자동 적용
- [x] 상여금(×3/12) + 연차수당(×3/12) 가산 처리
- [x] facade.py: CALC_TYPES + CALC_TYPE_MAP + 디스패처 추가
- [x] `severance.py` 리팩터링: 내부 로직을 `average_wage.py` 호출로 전환
- [x] 테스트 케이스 추가 (#60~)

### 2.2 Out of Scope

- 산정사유별 상세 계산 (산재급여·휴업수당 금액 산정은 별도 계산기로)
- 평균임금 산정 제외기간 처리 (수습·쟁의·휴업 기간 제외 — 향후 확장)
- 챗봇 파라미터 매핑 확장 (chatbot.py 수정은 별도 feature)

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | `calc_average_wage(inp, ow)` 독립 함수 — 3개월 평균임금 산출 | High | Pending |
| FR-02 | `AverageWageResult` dataclass: avg_daily_wage, avg_daily_3m, avg_daily_ordinary, used_basis, period_days, wage_total, bonus_addition, leave_addition | High | Pending |
| FR-03 | 산정사유발생일 기반 3개월 총일수 자동 계산 (역산) | High | Pending |
| FR-04 | 평균임금 < 통상임금 시 통상임금 적용 + used_basis 표시 | High | Pending |
| FR-05 | 월별 세분화 입력: `last_3m_wages` 항목을 `[{base: N, allowance: M}, ...]` 형태로 확장 | Medium | Pending |
| FR-06 | facade CALC_TYPES에 `"average_wage": "평균임금"` 추가 | High | Pending |
| FR-07 | facade CALC_TYPE_MAP에 `"평균임금": ["average_wage"]` 추가 | High | Pending |
| FR-08 | severance.py 내부 `_calc_avg_daily_3m()` → `average_wage.py` 호출로 리팩터링 | Medium | Pending |
| FR-09 | 테스트 케이스 3건 이상 (기본 산정 / 통상임금 비교 / 상여금+연차 가산) | High | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| 하위 호환성 | 기존 59개 테스트 100% 통과 | `wage_calculator_cli.py` 전수 실행 |
| 코드 재사용 | severance.py가 average_wage.py를 호출 (중복 제거) | 코드 리뷰 |
| nodong.kr 정합성 | 동일 입력 시 동일 결과 | 수동 비교 검증 |

---

## 4. Gap Analysis: nodong.kr vs 현재 코드

| # | nodong.kr 기능 | 현재 코드 | Gap | 우선순위 |
|---|----------------|-----------|-----|----------|
| 1 | 독립 평균임금 계산 | severance.py 내부 private 함수 | **독립 모듈 필요** | High |
| 2 | 산정사유발생일 입력 | end_date로 대체 사용 중 | **전용 필드 또는 end_date 활용 명시** | Medium |
| 3 | 월별 기본급 + 기타수당 분리 입력 | `last_3m_wages: [total1, total2, total3]` (합계만) | **dict 형태로 확장 가능 (하위호환)** | Medium |
| 4 | 3개월 총일수 자동 계산 | `last_3m_days` 수동 입력 (기본 92일) | **산정사유발생일 기반 자동 계산** | High |
| 5 | 평균임금 vs 통상임금 비교 | severance.py 내부에서만 비교 | **독립 결과에 포함 필요** | High |
| 6 | 상여금×3/12 + 연차수당×3/12 가산 | severance.py에서 처리 중 | **average_wage.py로 이전** | Medium |
| 7 | facade "평균임금" 매핑 | 없음 | **CALC_TYPES + CALC_TYPE_MAP 추가** | High |

---

## 5. Success Criteria

### 5.1 Definition of Done

- [ ] `average_wage.py` 독립 모듈 작동
- [ ] facade에서 `targets=["average_wage"]`로 호출 가능
- [ ] CALC_TYPE_MAP에서 `"평균임금"` → `["average_wage"]` 매핑
- [ ] severance.py가 average_wage.py 재사용 (중복 코드 제거)
- [ ] 기존 59개 + 신규 3건 이상 테스트 전수 통과
- [ ] nodong.kr 동일 입력 대비 결과 일치 확인

### 5.2 Quality Criteria

- [ ] 기존 severance 테스트 (#11~) 결과 변경 없음
- [ ] 통상임금 비교 자동 적용 정상 동작
- [ ] 계산식(formulas) 출력에 상세 내역 포함

---

## 6. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| severance.py 리팩터링 시 기존 결과 변동 | High | Low | 리팩터링 전후 동일 결과 테스트로 검증 |
| `last_3m_wages` 형태 변경 시 하위 호환성 | Medium | Low | 기존 `list[float]` 유지 + `list[dict]` 동시 지원 |
| 3개월 일수 자동 계산 오류 | Medium | Low | calendar 모듈 사용 + 엣지 케이스 테스트 |

---

## 7. Architecture Considerations

### 7.1 모듈 구조

```
wage_calculator/calculators/
├── average_wage.py     # 신규: 독립 평균임금 계산기
├── severance.py        # 수정: average_wage.py 호출로 리팩터링
├── ordinary_wage.py    # 기존 유지 (통상임금)
└── ...
```

### 7.2 의존성 방향

```
facade.py
  ├── average_wage.py  ← 신규 직접 호출
  └── severance.py
        └── average_wage.py  ← 내부 로직 대체
```

### 7.3 데이터 흐름

```
WageInput (last_3m_wages, annual_bonus_total, unused_annual_leave_pay, end_date)
    ↓
calc_average_wage(inp, ow)
    ├─ 3개월 임금총액 계산
    ├─ 상여금×3/12 가산
    ├─ 연차수당×3/12 가산
    ├─ 총액 / 총일수 = 1일 평균임금
    ├─ vs 통상임금 비교
    └─ AverageWageResult 반환
```

---

## 8. Next Steps

1. [ ] Design 문서 작성 (`/pdca design average-wage-calculator`)
2. [ ] 구현 (`/pdca do average-wage-calculator`)
3. [ ] Gap 분석 (`/pdca analyze average-wage-calculator`)

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-08 | Initial draft — nodong.kr 참조 Gap 분석 포함 | Claude PDCA |
