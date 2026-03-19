# 통상임금 계산 모듈 리뷰 Planning Document

> **Summary**: nodong.kr 공식 통상임금 계산기 대비 현재 모듈의 입력/로직/출력 완성도 검증 및 개선
>
> **Project**: laborconsult (노동OK BEST Q&A 크롤러 & 임금계산기)
> **Author**: Claude PDCA
> **Date**: 2026-03-08
> **Status**: Draft

---

## Executive Summary

| 항목 | 내용 |
|------|------|
| **Feature** | 통상임금 계산 모듈 리뷰 (ordinary-wage-review) |
| **기간** | 2026-03-08 ~ |
| **근거** | https://www.nodong.kr/common_wage_cal |

### Value Delivered (4-Perspective)

| Perspective | Description |
|-------------|-------------|
| **Problem** | 현재 통상임금 모듈이 nodong.kr 공식 계산기의 수당 세분류(9종), 상여금 조건부 산입 로직, 휴일근로 8h 초과 구분 입력 등을 충분히 반영하지 못할 수 있음 |
| **Solution** | nodong.kr 계산기 입력/로직/출력 항목을 기준으로 Gap 분석 후, 누락 기능 보강 및 계산 정확도 검증 |
| **Function UX Effect** | 사용자가 제공하는 수당·상여금 정보를 더 정밀하게 반영하여 통상시급 산출 정확도 향상 |
| **Core Value** | 대법원 2023다302838 판결 반영 + nodong.kr 실무 기준 정합성 확보 → 챗봇 신뢰도 향상 |

---

## 1. Overview

### 1.1 Purpose

nodong.kr 공식 통상임금 계산기(https://www.nodong.kr/common_wage_cal)를 참조 기준으로 삼아, 현재 `wage_calculator/calculators/ordinary_wage.py` 모듈의 **입력 완성도, 계산 로직 정확성, 출력 항목 충분성**을 검증하고 개선 포인트를 도출한다.

### 1.2 Background

- 통상임금은 연장·야간·휴일수당, 퇴직금, 연차수당 등 **모든 수당 계산의 기반**
- 대법원 2023다302838 (2024.12.19) 판결로 고정성 요건 폐기 → 재직조건·근무일수 조건부 수당도 통상임금 인정
- nodong.kr 계산기는 **9종 정기수당 + 3종 상여금 조건 분류**를 지원하며, 이를 현재 코드의 `fixed_allowances` 구조와 비교 필요
- 현재 코드는 `_resolve_is_ordinary()`에서 조건 판단하나, nodong.kr처럼 **수당 유형별 세분류 UI**가 반영되지 않을 수 있음

### 1.3 Related Documents

- 참조: https://www.nodong.kr/common_wage_cal (nodong.kr 공식 통상임금 계산기)
- 코드: `wage_calculator/calculators/ordinary_wage.py`
- 모델: `wage_calculator/models.py` (WageInput, AllowanceCondition)
- 상수: `wage_calculator/constants.py` (MONTHLY_STANDARD_HOURS, SHIFT_MONTHLY_HOURS)
- 퍼사드: `wage_calculator/facade.py` (WageCalculator.calculate)
- 판례: 대법원 2023다302838, 대법원 2013다4174, 대법원 2022다291153

---

## 2. Scope

### 2.1 In Scope (Gap 분석 대상)

- [ ] **입력 필드 비교**: nodong.kr 입력 항목 vs 현재 WageInput 필드 매핑
- [ ] **수당 분류 체계**: 9종 정기수당 세분류 반영 여부 검증
- [ ] **상여금 조건부 산입 로직**: 정기상여금 / 재직조건 / 최소보장 성과급 3종 분류
- [ ] **휴일근로 8h 초과 구분**: 현재 `weekly_holiday_hours` + `weekly_holiday_overtime_hours` 구조 적합성
- [ ] **월 기준시간 산출**: 주휴시간 포함 자동계산 로직 정확성 (특히 단시간 근로자)
- [ ] **출력 항목**: 시간당 통상임금, 1일 통상임금, 각종 수당 산정값 출력 완성도
- [ ] **최저임금 비교 연계**: 통상임금 ↔ 최저임금 크로스 검증
- [ ] **테스트 케이스**: nodong.kr 예제 기반 검증 케이스 추가

### 2.2 Out of Scope

- 다른 계산기 모듈 (overtime, severance 등) 자체 로직 리뷰
- UI/프론트엔드 구현 (계산기는 백엔드 Python 모듈)
- Pinecone RAG 파이프라인 변경
- chatbot.py 대화 흐름 변경

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | nodong.kr 9종 정기수당 분류(업무·직책·자격·근속·위험·교대·기술·식대·교통 수당)를 `fixed_allowances` 구조에서 표현 가능한지 검증 | High | Pending |
| FR-02 | 상여금 3종 조건 분류(정기상여금 / 재직·근무일수 조건 / 최소보장 성과급) → `AllowanceCondition` enum + `_resolve_is_ordinary()` 매핑 완성도 | High | Pending |
| FR-03 | 연간 상여금 입력 → 월 환산(/12) 처리가 `annual=True` 플래그로 정상 동작하는지 검증 | High | Pending |
| FR-04 | 휴일근로 입력의 8h 이내/초과 구분이 `WorkSchedule.weekly_holiday_hours` + `weekly_holiday_overtime_hours`로 정확히 반영되는지 검증 | Medium | Pending |
| FR-05 | 1주 근무시간 선택입력(직접입력 vs 자동계산)에 대응하는 `monthly_scheduled_hours` 직접 지정 경로 검증 | Medium | Pending |
| FR-06 | 단시간 근로자(주 15h 미만) 주휴시간 0 처리 정확성 | Medium | Pending |
| FR-07 | 교대근무 유형별 월 소정근로시간 조회값 검증 (4조2교대 182.5h, 3교대 195.5h 등) | Medium | Pending |
| FR-08 | 출력: 시간당 통상임금 + 1일 통상임금 + 포함/제외 항목 목록 완성도 | Medium | Pending |
| FR-09 | 최저임금 비교 시 통상임금 산입범위(`MIN_WAGE_INCLUSION_RATES`) 적용 정확성 | Low | Pending |
| FR-10 | "최소지급분이 보장되는 성과급" → 통상임금 포함 처리 로직 (현재 `_resolve_is_ordinary`에 미반영 가능) | High | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| 정확성 | nodong.kr 계산기와 동일 입력 시 통상시급 오차 ±1원 이내 | 수동 크로스체크 5개 케이스 |
| 호환성 | 기존 32개 테스트 케이스 전수 통과 유지 | `wage_calculator_cli.py` 전체 실행 |
| 확장성 | 새 수당 유형 추가 시 `fixed_allowances` dict 구조만으로 처리 가능 | 코드 리뷰 |
| 법률 정합성 | 대법원 2023다302838 판결 반영 완전성 | 판결문 기반 체크리스트 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] nodong.kr 입력 필드 ↔ WageInput 필드 매핑표 완성
- [ ] Gap 항목별 수정 코드 구현 (또는 "현재 코드 적합" 판정)
- [ ] nodong.kr 기준 테스트 케이스 최소 3개 추가
- [ ] 기존 32개 테스트 케이스 회귀 통과
- [ ] `_resolve_is_ordinary()` 로직 완전성 검증 완료

### 4.2 Quality Criteria

- [ ] 통상시급 계산 오차 ±1원 이내 (nodong.kr 대비)
- [ ] 기존 코드 regression 없음
- [ ] AllowanceCondition enum이 nodong.kr 분류 체계를 100% 커버

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| nodong.kr 계산기 내부 로직이 비공개 → 역산 불가능한 경우 | Medium | Medium | BEST Q&A 14개 참고자료 + 노동부 행정해석 17건 + 대법원 판례로 로직 추론 |
| "최소보장 성과급" 판단 기준이 모호 | High | Medium | AllowanceCondition에 `GUARANTEED_PERFORMANCE` 유형 추가 검토 |
| 기존 테스트 케이스가 수당 세분류를 커버하지 않음 | Medium | High | nodong.kr 예제 기반 테스트 케이스 신규 작성 |
| 교대근무 월 소정근로시간이 사업장마다 상이 | Low | Medium | `shift_monthly_hours` 직접 지정 경로가 이미 존재 → 문서화 보강 |

---

## 6. Gap 분석 매트릭스 (nodong.kr vs 현재 코드)

### 6.1 입력 필드 비교

| nodong.kr 입력 | 현재 WageInput 필드 | 매핑 상태 | Gap |
|---------------|---------------------|-----------|-----|
| 1주 근무시간 (선택/직접입력) | `schedule.daily_work_hours × weekly_work_days` 또는 `monthly_scheduled_hours` | **O** | 직접입력 경로 존재 |
| 1일 근무시간 (1~24h) | `schedule.daily_work_hours` (default 8.0) | **O** | |
| 1주 근무일 (1~7일) | `schedule.weekly_work_days` (default 5.0) | **O** | |
| 기본급(월) | `monthly_wage` | **O** | |
| 월 통상수당 | `fixed_allowances[*].amount` | **O** | 합산으로 입력 가능 |
| 연간 상여금 | `fixed_allowances[*].amount + annual=True` | **O** | /12 환산 처리됨 |
| 야간/연장/휴일 근로시간 | `schedule.weekly_night/overtime/holiday_hours` | **O** | |
| 휴일근로 8h 이내/초과 구분 | `weekly_holiday_hours` + `weekly_holiday_overtime_hours` | **O** | 분리됨 |
| 입사일/퇴직일 | `start_date` / `end_date` | **O** | |
| 9종 정기수당 세분류 | `fixed_allowances[*].name` (자유 텍스트) | **△** | 구조적 분류 없음 (이름만) |
| 정기상여금 | `fixed_allowances` + `condition="없음"` | **O** | |
| 재직/근무일수 조건 상여금 | `AllowanceCondition.EMPLOYMENT/ATTENDANCE` | **O** | 2023다302838 반영 |
| 최소보장 성과급 | **미반영** | **X** | `PERFORMANCE` → 일괄 제외 처리 중 |
| 미사용 연차휴가 수 | `annual_leave_used` (역산 필요) | **△** | 미사용 수 직접 입력 불가 |

### 6.2 핵심 Gap 상세

#### Gap 1: "최소보장 성과급" 통상임금 산입 미지원 (FR-10)

**현재 코드** (`_resolve_is_ordinary`):
```python
if condition == "성과조건":
    return False, ""   # 일괄 제외
```

**nodong.kr 분류**:
- 회사 실적 의존 성과급 → 통상임금 **제외**
- 개인 평가 기준 성과급 (보장액 없음) → 통상임금 **제외**
- **최소지급분이 보장되는 성과급** → 통상임금 **포함**

**대응방안**: `AllowanceCondition`에 `GUARANTEED_PERFORMANCE = "최소보장성과"` 추가하고, `_resolve_is_ordinary()`에서 통상임금 포함 처리

#### Gap 2: 9종 정기수당 구조적 분류 부재

**현재**: `fixed_allowances`는 `name`(자유 텍스트) + `amount` + `condition` + `is_ordinary` 구조
**nodong.kr**: 업무·직책·자격·근속·위험·교대·기술·식대·교통 9종 분류

**판단**: 현재 구조로도 기능적으로 **충분** — `name` 필드에 수당명을 기재하면 동일 효과. 구조적 강제가 불필요한 이유는 통상임금 판단 기준이 `condition`(지급조건)이지 수당 유형이 아니기 때문.

→ **현재 코드 적합 판정** (변경 불필요)

#### Gap 3: 1일 통상임금 출력 누락 (FR-08)

**현재 OrdinaryWageResult**:
- `hourly_ordinary_wage` (시간당 통상임금) ✅
- `monthly_ordinary_wage` (월 통상임금) ✅
- **`daily_ordinary_wage` (1일 통상임금) 없음** ❌

**nodong.kr**: 시간당 + 1일 통상임금 모두 출력

**대응방안**: `OrdinaryWageResult`에 `daily_ordinary_wage` 필드 추가 (`hourly × daily_work_hours`)

---

## 7. Architecture Considerations

### 7.1 Project Level

| Level | Selected |
|-------|:--------:|
| **Dynamic** | **O** |

Python 백엔드 모듈, facade 패턴 기반의 기존 아키텍처를 유지.

### 7.2 Key Architectural Decisions

| Decision | Current | Change Needed | Rationale |
|----------|---------|:-------------:|-----------|
| 수당 데이터 구조 | `list[dict]` (fixed_allowances) | No | 자유 텍스트 `name` + `condition` enum으로 충분 |
| 통상임금 판단 | `_resolve_is_ordinary()` | **Yes** | "최소보장성과" 조건 추가 필요 |
| AllowanceCondition enum | 4종 (NONE/ATTENDANCE/EMPLOYMENT/PERFORMANCE) | **Yes** | `GUARANTEED_PERFORMANCE` 추가 |
| OrdinaryWageResult | hourly + monthly | **Yes** | `daily_ordinary_wage` 추가 |
| 테스트 체계 | CLI 32 cases | **Expand** | nodong.kr 기준 케이스 추가 |

---

## 8. Convention Prerequisites

### 8.1 Existing Project Conventions

- [x] `CLAUDE.md` has coding conventions section
- [x] 금액 단위: 원 (Won), 소수점 없이 표시 `{:,.0f}`
- [x] 한국어 변수명 `facade.py::_provided_info_to_input()` 에서 사용
- [x] 법률 참조: "근로기준법 제N조" 또는 "대법원 YYYY다NNNN" 형식
- [x] 테스트: `wage_calculator_cli.py` 번호제 (#1~#32)

### 8.2 환경변수

| Variable | Purpose | Status |
|----------|---------|:------:|
| `OPENAI_API_KEY` | 임베딩 (chatbot 연동 시) | 기존 |
| `ANTHROPIC_API_KEY` | Claude 응답 (chatbot 연동 시) | 기존 |

---

## 9. Implementation Priorities (Design Phase 입력)

| 순서 | 작업 | 예상 영향 | 우선순위 |
|:----:|------|-----------|:--------:|
| 1 | `AllowanceCondition.GUARANTEED_PERFORMANCE` enum 추가 | 모델 변경 | High |
| 2 | `_resolve_is_ordinary()` 최소보장 성과급 로직 추가 | 핵심 로직 | High |
| 3 | `OrdinaryWageResult.daily_ordinary_wage` 필드 추가 | 출력 보강 | Medium |
| 4 | nodong.kr 기준 테스트 케이스 3~5개 추가 | 검증 | Medium |
| 5 | 기존 32개 케이스 회귀 테스트 | 안정성 | High |

---

## 10. Next Steps

1. [ ] Design 문서 작성 (`ordinary-wage-review.design.md`)
2. [ ] Gap 1 (최소보장 성과급) 상세 설계
3. [ ] 테스트 케이스 설계 (nodong.kr 예제 기반)
4. [ ] 구현 및 Gap 분석

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-08 | Initial draft — nodong.kr vs 현재 코드 Gap 분석 | Claude PDCA |
