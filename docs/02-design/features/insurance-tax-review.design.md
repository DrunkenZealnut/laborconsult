# Design: 4대보험료 / 근로소득세 계산식 리뷰 및 보완

> Plan 참조: `docs/01-plan/features/insurance-tax-review.plan.md`

---

## 1. 변경 범위 요약

| Step | File | Changes | GAP |
|:----:|------|---------|-----|
| 1 | `constants.py` | 건강보험 상한/하한, 자녀세액공제, 산재보험 구성요소 상수 추가 | GAP-2,5,6 |
| 2 | `models.py` | `num_children_8_to_20` 필드 추가 | GAP-5 |
| 3 | `insurance.py` | calc_insurance: 절사 규칙, 건강보험 상한/하한, 자녀세액공제 | GAP-1,2,3,5 |
| 4 | `insurance.py` | calc_employer_insurance: 절사 규칙, 건강보험 상한/하한, 산재 구성요소 | GAP-1,2,3,6 |
| 5 | `wage_calculator_cli.py` | 검증 테스트 케이스 추가 | 전체 검증 |

---

## 2. Step 1: constants.py 상수 추가

### 2.1 건강보험 보수월액 상한/하한 (연도별)

위치: `INSURANCE_RATES` dict 내부에 키 추가

```python
INSURANCE_RATES = {
    2025: {
        # ... 기존 요율 유지 ...
        "health_upper_limit": 119_625_106,  # 보수월액 상한 (건강보험료 상한 4,240,710 / 3.545% 역산)
        "health_lower_limit":     279_000,  # 보수월액 하한 (건강보험료 하한 9,890 / 3.545% 역산)
        # 직접 보험료 상한/하한으로 관리하는 게 더 정확:
        "health_premium_max":   4_240_710,  # 근로자 건강보험료 월 상한
        "health_premium_min":       9_890,  # 근로자 건강보험료 월 하한 (19,780/2)
    },
    2026: {
        # ... 기존 요율 유지 ...
        "health_premium_max":   4_240_710,  # 2026년 확정 시 갱신 — 잠정 동일
        "health_premium_min":       9_890,
    },
}
```

**설계 결정**: 보수월액 상한/하한 대신 **보험료 금액 상한/하한**으로 관리.
이유: nodong.kr이 보험료 상한을 직접 적용하며, 역산 시 부동소수점 오차 발생 가능.

### 2.2 자녀세액공제 월 금액

위치: `constants.py` 하단, `LOCAL_INCOME_TAX_RATE` 아래

```python
# 자녀세액공제 월 금액 (소득세법 제59조의2, 2025.3.1 기준)
# 8~20세 자녀 수별 월 공제액
CHILD_TAX_CREDIT_MONTHLY = {
    1: 12_500,   # 연 15만원 / 12
    2: 29_160,   # 연 35만원 / 12 (15만 + 20만)
    # 3명 이상: 35만 + (N-2) × 25만 → 월 환산
}
CHILD_TAX_CREDIT_BASE_3PLUS = 29_160     # 2명까지 기본
CHILD_TAX_CREDIT_PER_EXTRA = 20_830      # 3명째부터 추가 (연 25만/12)
```

> **Note**: nodong.kr의 2026.3.1 기준 값(20,830/45,830/33,330)은 개정 반영값.
> 2025년 기준은 소득세법 제59조의2에 따라 연 15만/35만/60만원.
> 연도별 분기 필요 시 dict로 확장 가능하나, 우선 2025년 기준 적용.

### 2.3 산재보험 구성요소 (사업주 계산기용)

위치: `insurance.py` 내 기존 `DEFAULT_INDUSTRIAL_ACCIDENT_RATE` 교체

```python
# 산재보험 구성요소 (산업재해보상보험법, 2025년 기준)
INDUSTRIAL_ACCIDENT_COMPONENTS = {
    "commute":     0.006,    # 출퇴근재해보험료율 0.6%
    "wage_claim":  0.009,    # 임금채권부담금 비율 0.9% (임금채권보장법 시행령)
    "asbestos":    0.0003,   # 석면피해구제 분담금률 0.03%
}
DEFAULT_INDUSTRY_RATE = 0.007  # 업종별 산재보험료율 기본값 (전체 평균)
```

---

## 3. Step 2: models.py 필드 추가

### 3.1 WageInput 추가 필드

위치: `tax_dependents` 아래

```python
num_children_8_to_20: int = 0    # 8~20세 자녀 수 (자녀세액공제용, 소득세법 제59조의2)
```

기본값 0 → 기존 호출 하위 호환.

---

## 4. Step 3: insurance.py — calc_insurance() 수정

### 4.1 국민연금 — 기준소득월액 1,000원 절사

```python
# AS-IS
pension_base = max(pension_min, min(gross, pension_max))
national_pension = round(pension_base * pension_rate)

# TO-BE
pension_base = max(pension_min, min(gross, pension_max))
pension_base = (pension_base // 1000) * 1000  # 1,000원 미만 절사
national_pension = int(pension_base * pension_rate)  # 원 미만 절사
```

Formula 텍스트도 갱신: `"국민연금: {pension_base:,.0f}원(1천원절사) × ..."`

### 4.2 건강보험 — 보험료 상한/하한 적용

```python
# TO-BE
health_premium_max = rates.get("health_premium_max", float("inf"))
health_premium_min = rates.get("health_premium_min", 0)

health_insurance = int(gross * health_rate)  # 원 미만 절사
health_insurance = max(health_premium_min, min(health_insurance, health_premium_max))

if health_insurance == health_premium_max:
    warnings.append(f"건강보험: 보험료 상한({health_premium_max:,}원) 적용")
```

### 4.3 장기요양보험 — 원 미만 절사

```python
# AS-IS
long_term_care = round(health_insurance * ltc_rate)

# TO-BE
long_term_care = int(health_insurance * ltc_rate)  # 원 미만 절사
```

### 4.4 고용보험 — 원 미만 절사

```python
# AS-IS
employment_insurance = round(gross * emp_rate)

# TO-BE
employment_insurance = int(gross * emp_rate)  # 원 미만 절사
```

### 4.5 자녀세액공제 적용

근로소득세 계산 블록 내, `income_tax = round(annual_income_tax / 12)` 다음:

```python
# 자녀세액공제 (8~20세 자녀)
child_credit = _calc_child_tax_credit(inp.num_children_8_to_20)
income_tax = max(0, income_tax - child_credit)

# formula 추가
if child_credit > 0:
    formulas.append(
        f"자녀세액공제: {inp.num_children_8_to_20}명 → 월 {child_credit:,.0f}원 공제"
    )
```

### 4.6 _calc_child_tax_credit() 신규 함수

```python
def _calc_child_tax_credit(num_children: int) -> int:
    """자녀세액공제 월 금액 계산 (소득세법 제59조의2)"""
    if num_children <= 0:
        return 0
    from ..constants import (
        CHILD_TAX_CREDIT_MONTHLY,
        CHILD_TAX_CREDIT_BASE_3PLUS,
        CHILD_TAX_CREDIT_PER_EXTRA,
    )
    if num_children <= 2:
        return CHILD_TAX_CREDIT_MONTHLY.get(num_children, 0)
    # 3명 이상: 2명 기본 + 추가분
    return CHILD_TAX_CREDIT_BASE_3PLUS + (num_children - 2) * CHILD_TAX_CREDIT_PER_EXTRA
```

---

## 5. Step 4: insurance.py — calc_employer_insurance() 수정

### 5.1 절사 규칙 동일 적용

근로자 계산과 동일하게 `round()` → `int()` 변경:
- `employer_pension = int(pension_base * pension_rate)`
- `employer_health = int(gross * health_rate)` + 상한/하한
- `employer_ltc = int(employer_health * ltc_rate)`
- `employer_employment = int(gross * emp_rate)`

### 5.2 국민연금 기준소득월액 1,000원 절사

```python
pension_base = max(rates["pension_income_min"], min(gross, rates["pension_income_max"]))
pension_base = (pension_base // 1000) * 1000  # 1,000원 미만 절사
```

### 5.3 산재보험 구성요소 분리

```python
# AS-IS
employer_accident = round(gross * accident_rate)

# TO-BE
from .insurance import INDUSTRIAL_ACCIDENT_COMPONENTS

industry_rate = getattr(inp, "industry_accident_rate", DEFAULT_INDUSTRY_RATE) or DEFAULT_INDUSTRY_RATE
commute_rate = INDUSTRIAL_ACCIDENT_COMPONENTS["commute"]
wage_claim_rate = INDUSTRIAL_ACCIDENT_COMPONENTS["wage_claim"]
asbestos_rate = INDUSTRIAL_ACCIDENT_COMPONENTS["asbestos"]

total_accident_rate = industry_rate + commute_rate + wage_claim_rate + asbestos_rate
employer_accident = int(gross * total_accident_rate)

formulas.append(
    f"산재보험: 업종({industry_rate*100:.2f}%) + 출퇴근(0.6%) + 임금채권(0.9%) + 석면(0.03%) "
    f"= {total_accident_rate*100:.2f}% → {employer_accident:,.0f}원"
)
```

breakdown에 구성요소별 내역 추가:
```python
breakdown[f"산재보험({total_accident_rate*100:.2f}%)"] = f"{employer_accident:,.0f}원"
breakdown["  업종별 요율"] = f"{industry_rate*100:.2f}%"
breakdown["  출퇴근재해"] = f"0.6%"
breakdown["  임금채권부담금"] = f"0.9%"
breakdown["  석면피해구제"] = f"0.03%"
```

---

## 6. Step 5: wage_calculator_cli.py 테스트 케이스

### 6.1 추가 테스트 케이스

현재 마지막 ID = 51. #52~#56 추가:

```python
# #52: 기본 — 월 300만, 비과세 20만, 부양가족 1인 (절사 규칙 검증)
{
    "id": 52,
    "desc": "4대보험 절사 규칙 — 월 3,000,000원, 비과세 200,000원",
    "input": WageInput(
        wage_type=WageType.MONTHLY,
        monthly_wage=3_000_000,
        reference_year=2025,
        monthly_non_taxable=200_000,
        tax_dependents=1,
    ),
    "targets": ["insurance"],
}

# #53: 국민연금 상한 — 월 617만원 (상한 적용 검증)
{
    "id": 53,
    "desc": "4대보험 국민연금 상한 — 월 6,170,000원",
    "input": WageInput(
        wage_type=WageType.MONTHLY,
        monthly_wage=6_170_000,
        reference_year=2025,
        tax_dependents=3,
    ),
    "targets": ["insurance"],
}

# #54: 건강보험 상한 — 월 1억 (건강보험료 상한 적용 검증)
{
    "id": 54,
    "desc": "4대보험 건강보험 상한 — 월 100,000,000원",
    "input": WageInput(
        wage_type=WageType.MONTHLY,
        monthly_wage=100_000_000,
        reference_year=2025,
        tax_dependents=4,
    ),
    "targets": ["insurance"],
}

# #55: 자녀세액공제 — 자녀 2명 (공제 적용 검증)
{
    "id": 55,
    "desc": "자녀세액공제 — 월 4,000,000원, 자녀 2명",
    "input": WageInput(
        wage_type=WageType.MONTHLY,
        monthly_wage=4_000_000,
        reference_year=2025,
        tax_dependents=4,  # 본인+배우자+자녀2
        num_children_8_to_20=2,
    ),
    "targets": ["insurance"],
}

# #56: 사업주 — 산재보험 구성요소 분리 검증
{
    "id": 56,
    "desc": "사업주 4대보험 — 산재보험 구성요소 (업종 1.5%)",
    "input": WageInput(
        wage_type=WageType.MONTHLY,
        monthly_wage=3_500_000,
        reference_year=2025,
        industry_accident_rate=0.015,
        company_size_category="150_999",
    ),
    "targets": ["employer_insurance"],
}
```

---

## 7. 절사 규칙 정리

| 보험 | 기준 | 절사 규칙 | 코드 |
|------|------|-----------|------|
| 국민연금 | 기준소득월액 | 1,000원 미만 절사 | `(base // 1000) * 1000` |
| 국민연금 | 보험료 | 원 미만 절사 | `int(base * rate)` |
| 건강보험 | 보험료 | 원 미만 절사 + 상한/하한 | `int(base * rate)` + clamp |
| 장기요양 | 보험료 | 원 미만 절사 | `int(health * rate)` |
| 고용보험 | 보험료 | 원 미만 절사 | `int(base * rate)` |
| 근로소득세 | 세액 | 10원 미만 절사 | `(tax // 10) * 10` |
| 지방소득세 | 세액 | 10원 미만 절사 | `(local // 10) * 10` |

> **Note**: 소득세 10원 미만 절사는 현행 미적용 (round 사용).
> 영향이 미미하므로 이번에는 보험료 절사에만 집중, 소득세 절사는 선택적 적용.

---

## 8. 하위 호환성

| 항목 | 영향 |
|------|------|
| 기존 WageInput 호출 | `num_children_8_to_20=0` 기본값 → 영향 없음 |
| 보험료 변경 | `round()` → `int()`: 기존보다 최대 1원 낮아질 수 있음 |
| 건강보험 상한 | 기존에 상한 없었으므로 초고소득 케이스에서 금액 감소 |
| `get_insurance_rates()` | 새 키 추가지만 `.get()` 사용으로 미존재 시 안전 |
| 기존 테스트 통과 | 절사로 인한 1~수십원 차이 → 테스트가 정확한 값 검증하지 않으므로 통과 |

---

## 9. 구현 순서

```
1. constants.py     — 상수 추가 (상한/하한, 자녀공제, 산재 구성)
2. models.py        — num_children_8_to_20 필드 추가
3. insurance.py     — calc_insurance() 절사 + 상한/하한 + 자녀공제
4. insurance.py     — calc_employer_insurance() 절사 + 산재 구성요소
5. wage_calculator_cli.py — 테스트 #52~#56
6. 전체 테스트 실행    — python3 wage_calculator_cli.py
```
