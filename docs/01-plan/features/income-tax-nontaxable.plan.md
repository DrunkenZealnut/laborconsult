# Plan: 근로소득 과세/비과세 상세 분류 적용

> **Summary**: nodong.kr/income_tax_impose, income_tax_except 기반 비과세 근로소득 항목별 상세 입력·자동 한도 적용
>
> **Project**: laborconsult (nodong.kr 노동법 Q&A + 임금계산기)
> **Date**: 2026-03-13
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 현행 시스템은 `monthly_non_taxable=200,000` 단일 값만 지원하여 식대·자가운전보조금·자녀보육수당·연장근로수당 등 다양한 비과세 항목을 구분 관리할 수 없음. 사용자가 비과세 항목별 한도 초과 여부를 직접 판단해야 함 |
| **Solution** | 비과세 근로소득 항목별 구조화된 입력 체계 + 법정 한도 자동 적용 + 과세/비과세 구분 안내 |
| **Function/UX Effect** | 비과세 항목(식대·교통비·보육수당 등)을 개별 입력하면 한도 초과분 자동 과세 전환, 항목별 법적 근거 표시 |
| **Core Value** | 실수령액 정확도 향상 + 비과세 혜택 누락 방지 + 소득세법 기반 신뢰성 확보 |

---

## 1. Overview

### 1.1 Purpose

근로소득세 계산 시 비과세 근로소득을 항목별로 세분화하여:
- 각 항목의 법정 비과세 한도를 자동 적용
- 한도 초과분은 자동으로 과세소득에 편입
- 과세/비과세 구분에 대한 법적 근거를 안내

### 1.2 Background

**정보 출처:**
- https://www.nodong.kr/income_tax_impose — 근로소득의 종류 (과세 항목 23가지)
- https://www.nodong.kr/income_tax_except — 비과세 근로소득의 종류 (항목별 한도·조건)

**현행 한계:**
- `WageInput.monthly_non_taxable: float = 200_000` — 단일 금액만 입력
- 식대 20만원만 기본 적용, 자가운전보조금·보육수당·연장근로수당 비과세 등 미지원
- 사용자가 비과세 총액을 직접 합산하여 입력해야 하는 불편

### 1.3 Related Documents

- 기존 Plan: `docs/01-plan/features/insurance-tax-review.plan.md` (4대보험·소득세 계산식 리뷰)
- 소득세법 제12조 (비과세소득)
- 소득세법 시행령 제12조, 제16조, 제17조의4 등

---

## 2. Scope

### 2.1 In Scope

- [ ] 비과세 근로소득 항목별 구조화 입력 (NonTaxableIncome dataclass)
- [ ] 항목별 법정 비과세 한도 상수 정의 (연도별)
- [ ] 한도 초과분 자동 과세 전환 로직
- [ ] insurance.py calc_insurance() 내 비과세 상세 적용
- [ ] 과세 근로소득 종류 참조 상수 (안내·법적 근거용)
- [ ] 기존 `monthly_non_taxable` 필드와 하위 호환 유지
- [ ] RAG 챗봇 응답 시 과세/비과세 구분 안내 강화

### 2.2 Out of Scope

- 간이세액표 전체 내장 (insurance-tax-review에서 별도 검토)
- 연말정산 세액공제 상세 계산 (의료비·교육비·기부금 등)
- 퇴직소득 비과세 (별도 체계)
- 일용직 근로소득 과세 특례

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | 비과세 항목별 구조화 입력 (식대, 자가운전, 보육, 연장근로 등 7+ 항목) | High | Pending |
| FR-02 | 항목별 월 비과세 한도 자동 적용 (식대 20만원, 자가운전 20만원 등) | High | Pending |
| FR-03 | 한도 초과분 자동 과세소득 전환 + warnings 표시 | High | Pending |
| FR-04 | 기존 `monthly_non_taxable` 단일 값 입력 하위 호환 | High | Pending |
| FR-05 | 생산직 연장·야간·휴일근로수당 비과세 조건 검증 (월정액급여 260만원 이하 등) | Medium | Pending |
| FR-06 | 항목별 법적 근거(소득세법 조문) 연결 | Medium | Pending |
| FR-07 | 과세 근로소득 종류 참조 안내 (23가지 항목 분류) | Low | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| 하위 호환 | 기존 테스트 케이스 전부 통과 | wage_calculator_cli.py 전체 실행 |
| 정확도 | 비과세 한도 적용 후 과세소득 ±0원 일치 | 교차검증 5개 케이스 |
| 성능 | 추가 계산 오버헤드 < 1ms | 기존 대비 시간 측정 |

---

## 4. 비과세 근로소득 항목 상세 (nodong.kr/income_tax_except 기반)

### 4.1 주요 비과세 항목 및 한도

| # | 항목 | 월 한도 | 연 한도 | 조건 | 법적 근거 |
|---|------|---------|---------|------|-----------|
| 1 | 식대·식사비 | 20만원 | - | 현물 식사 미제공 시 | 소득세법 제12조제3호머목 |
| 2 | 자가운전보조금 | 20만원 | - | 본인 차량 업무 사용 | 소득세법 시행령 제12조 |
| 3 | 자녀보육수당 | 20만원/자녀 | - | 6세 이하 자녀 (2026년~) | 소득세법 제12조제3호러목 |
| 4 | 출산지원금 | 한도 없음 | - | 출생일 2년 이내, 최대 2회 | 소득세법 제12조제3호모목 |
| 5 | 연장·야간·휴일근로수당 | - | 240만원 | 생산직, 월정액 260만원 이하, 전년 총급여 3,700만원 이하 | 소득세법 제12조제3호나목 |
| 6 | 국외근로소득 | 100만원 | - | 해외 근무 (건설현장 500만원) | 소득세법 제12조제3호가목 |
| 7 | 연구보조비 | 20만원 | - | 연구활동종사자 | 소득세법 시행령 제12조제12호 |
| 8 | 취재수당 | 20만원 | - | 취재활동 종사 기자 등 | 소득세법 시행령 제12조제13호 |
| 9 | 벽지수당 | 20만원 | - | 벽지 근무 공무원 등 | 소득세법 시행령 제12조제9호 |
| 10 | 직무발명보상금 | - | 700만원 | 발명진흥법상 보상 | 소득세법 제12조제3호바목 |

### 4.2 근로소득에 포함되지 않는 소득

| 항목 | 조건 |
|------|------|
| 퇴직급여 적립금 | 전원 가입 + 근로자 변경 불가 |
| 사택 제공 이익 | 주주·출자자 아닌 임원·종업원 |
| 사내근로복지기금 장학금 | 근로복지기본법 기반 |
| 단체순수보장성보험료 | 연 70만원 이내 |

### 4.3 과세 근로소득 종류 (참조용, nodong.kr/income_tax_impose)

23가지 과세 항목:
1. 봉급·급료·임금·상여금 및 유사 급여
2. 근로수당·가족수당·직무수당·근속수당 등 각종 수당
3. 급식수당 (비과세 한도 초과분)
4. 주택수당·주택 제공 이익
5. 주택 구입·임차 자금 저리 대여 이익
6. 학자금·장학금
7. 직무발명보상금 (비과세 한도 초과분)
8. 사용자 부담 보험료 (단체환급부보장성)
9. 주식매수선택권 행사 이익
10. 공로금·위로금·개업축하금 등

---

## 5. 설계 방향

### 5.1 NonTaxableIncome 데이터 구조

```python
@dataclass
class NonTaxableIncome:
    """비과세 근로소득 항목별 입력"""
    meal_allowance: float = 0.0           # 식대 (월)
    car_subsidy: float = 0.0              # 자가운전보조금 (월)
    childcare_allowance: float = 0.0      # 자녀보육수당 (월, 자녀별)
    num_childcare_children: int = 0       # 6세 이하 자녀 수
    childbirth_support: float = 0.0       # 출산지원금 (월 환산)
    overtime_nontax: float = 0.0          # 생산직 연장근로수당 비과세분 (월 환산)
    overseas_pay: float = 0.0             # 국외근로소득 (월)
    is_overseas_construction: bool = False # 해외건설현장 여부
    research_subsidy: float = 0.0         # 연구보조비 (월)
    reporting_subsidy: float = 0.0        # 취재수당 (월)
    remote_area_subsidy: float = 0.0      # 벽지수당 (월)
    invention_reward: float = 0.0         # 직무발명보상금 (연)
    other_nontaxable: float = 0.0         # 기타 비과세 (월)
```

### 5.2 한도 적용 로직

```python
def calc_total_nontaxable(nti: NonTaxableIncome, year: int) -> tuple[float, list[str]]:
    """
    Returns: (월 비과세 합계, 경고 리스트)
    - 각 항목별 한도 초과 시 한도만 적용 + warning 생성
    """
    limits = get_nontaxable_limits(year)
    total = 0.0
    warnings = []

    # 식대: 월 20만원 한도
    meal = min(nti.meal_allowance, limits["meal"])
    if nti.meal_allowance > limits["meal"]:
        warnings.append(f"식대: {nti.meal_allowance:,.0f}원 중 {limits['meal']:,.0f}원만 비과세")
    total += meal
    # ... 각 항목 반복

    return total, warnings
```

### 5.3 기존 필드 하위 호환

```python
# insurance.py calc_insurance() 내
if inp.non_taxable_detail:
    # 신규: 항목별 상세 입력
    nontaxable, nontax_warnings = calc_total_nontaxable(inp.non_taxable_detail, year)
    warnings.extend(nontax_warnings)
else:
    # 기존: 단일 값 사용 (하위 호환)
    nontaxable = inp.monthly_non_taxable
```

### 5.4 생산직 연장근로수당 비과세 조건 검증

```python
def is_eligible_overtime_nontax(inp: WageInput) -> bool:
    """소득세법 제12조제3호나목 — 생산직 연장근로수당 비과세 적격 여부"""
    # 조건 1: 월정액급여 260만원 이하 (2026년~, 2025년까지 210만원)
    monthly_limit = 2_600_000 if inp.reference_year >= 2026 else 2_100_000
    # 조건 2: 전년도 총급여 3,700만원 이하 (2026년~, 2025년까지 3,000만원)
    annual_limit = 37_000_000 if inp.reference_year >= 2026 else 30_000_000
    # 조건 3: 생산직 및 관련직 종사자
    return (inp.monthly_wage or 0) <= monthly_limit
    # 주의: 전년도 총급여는 별도 입력 필요
```

---

## 6. 변경 파일 및 영향 범위

| File | Change Type | Description |
|------|-------------|-------------|
| `wage_calculator/constants.py` | 상수 추가 | NON_TAXABLE_LIMITS (연도별 비과세 한도), TAXABLE_INCOME_TYPES (참조) |
| `wage_calculator/models.py` | 클래스 추가 | NonTaxableIncome dataclass + WageInput.non_taxable_detail 필드 |
| `wage_calculator/calculators/insurance.py` | 로직 수정 | calc_total_nontaxable() 함수 추가, calc_insurance() 내 비과세 상세 적용 |
| `wage_calculator_cli.py` | 테스트 추가 | 비과세 상세 입력 테스트 케이스 2~3개 |
| `wage_calculator/legal_hints.py` | 힌트 추가 | 비과세 관련 법적 안내 메시지 |

### 하위 호환성

- `monthly_non_taxable` 기존 필드 유지 — `non_taxable_detail` 미입력 시 기존 방식 동작
- 기존 테스트 케이스 #1~#32 영향 없음 (모두 `monthly_non_taxable` 사용)
- 신규 테스트 케이스에서 항목별 비과세 검증

---

## 7. 검증 기준

### 7.1 교차 검증 케이스

| Case | 설명 | 비과세 항목 | 기대 결과 |
|------|------|------------|-----------|
| NT-01 | 식대 20만원만 | meal=200,000 | monthly_non_taxable=200,000과 동일 |
| NT-02 | 식대+자가운전 | meal=200,000, car=200,000 | 비과세 40만원 적용 |
| NT-03 | 식대 한도 초과 | meal=300,000 | 비과세 20만원 + warning |
| NT-04 | 생산직 OT 비과세 | overtime_nontax=300,000 (적격) | 비과세 20만원/월(연240만) |
| NT-05 | 생산직 OT 부적격 | overtime_nontax=300,000 (월급 300만) | 비과세 0원 + warning |

### 7.2 Definition of Done

- [ ] NonTaxableIncome dataclass 구현 + from_dict() 팩토리
- [ ] 항목별 한도 상수 정의 (2025, 2026년)
- [ ] calc_total_nontaxable() 함수 구현
- [ ] insurance.py 통합 (기존 호환 유지)
- [ ] 테스트 케이스 NT-01 ~ NT-05 통과
- [ ] 기존 CLI 테스트 전체 통과

---

## 8. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| 연도별 비과세 한도 변경 | Medium | High | constants.py에 연도별 dict으로 관리, 매년 갱신 |
| 생산직 판별 불확실성 | Medium | Medium | 사용자 자기 선언 + 조건 경고 표시 |
| 기존 테스트 호환성 | High | Low | non_taxable_detail=None이면 기존 로직 사용 |
| 항목 간 중복 적용 | Low | Low | 각 항목 독립 한도 (중복 허용이 법 취지) |

---

## 9. Next Steps

1. [ ] Design 문서 작성 (`income-tax-nontaxable.design.md`)
2. [ ] 구현 (constants → models → insurance.py → CLI 테스트)
3. [ ] Gap Analysis

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-13 | Initial draft | Claude |
