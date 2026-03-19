# income-tax-nontaxable Design Document

> **Summary**: 비과세 근로소득 항목별 구조화 입력 + 법정 한도 자동 적용 + 기존 호환 유지
>
> **Project**: laborconsult (nodong.kr 노동법 Q&A + 임금계산기)
> **Date**: 2026-03-13
> **Status**: Draft
> **Planning Doc**: [income-tax-nontaxable.plan.md](../../01-plan/features/income-tax-nontaxable.plan.md)

---

## 1. Overview

### 1.1 Design Goals

1. `monthly_non_taxable` 단일 값 대신 항목별 구조화 입력 지원
2. 각 비과세 항목의 법정 한도를 연도별로 관리, 초과분 자동 과세 전환
3. 기존 코드 100% 하위 호환 (non_taxable_detail 미사용 시 기존 동작)
4. 생산직 연장근로수당 비과세 적격 조건 자동 검증

### 1.2 Design Principles

- **하위 호환 최우선**: 기존 WageInput → 기존 동작 보장
- **단일 접점 변경**: insurance.py의 `taxable_monthly` 산출 지점 1곳만 수정
- **상수 중심 설계**: 한도는 constants.py에 연도별 dict으로 관리 (코드 변경 없이 갱신)
- **YAGNI**: 현재 필요한 10개 비과세 항목만 구현, 확장은 필드 추가로 가능

---

## 2. Architecture

### 2.1 변경 대상 컴포넌트

```
wage_calculator/
├── constants.py         # [수정] NON_TAXABLE_LIMITS 추가
├── models.py            # [수정] NonTaxableIncome dataclass + WageInput 필드 추가
├── calculators/
│   └── insurance.py     # [수정] calc_nontaxable_total() 추가, _calc_employee() 통합
├── legal_hints.py       # [수정] 비과세 관련 힌트 추가
└── __init__.py          # [수정] NonTaxableIncome export
```

### 2.2 Data Flow

```
WageInput
  ├── non_taxable_detail: NonTaxableIncome  (신규 - 상세)
  └── monthly_non_taxable: float            (기존 - 단일 값)
          │
          ▼
  calc_insurance(inp, ow)
          │
          ├─ non_taxable_detail 있음 → calc_nontaxable_total(nti, year, inp)
          │     ├── 항목별 한도 적용 (NON_TAXABLE_LIMITS[year])
          │     ├── 생산직 OT 적격 검증
          │     ├── warnings 생성 (한도 초과, 부적격 등)
          │     └── formulas 생성 (항목별 비과세 내역)
          │
          └─ non_taxable_detail 없음 → inp.monthly_non_taxable (기존 동작)
          │
          ▼
  taxable_monthly = gross - nontaxable_amount
          │
          ▼
  기존 근로소득세 계산 로직 (변경 없음)
```

### 2.3 Dependencies

| Component | Depends On | Purpose |
|-----------|-----------|---------|
| `calc_nontaxable_total()` | `NON_TAXABLE_LIMITS`, `NonTaxableIncome` | 비과세 합산 |
| `_calc_employee()` | `calc_nontaxable_total()` | 과세소득 산출 |
| `NonTaxableIncome` | 없음 (독립 dataclass) | 입력 구조체 |
| `generate_legal_hints()` | `WageInput.non_taxable_detail` | 비과세 힌트 |

---

## 3. Data Model

### 3.1 NonTaxableIncome (신규, `models.py`)

```python
@dataclass
class NonTaxableIncome:
    """비과세 근로소득 항목별 입력 (소득세법 제12조)

    각 필드는 월 지급액 기준. 법정 한도 초과분은 자동 과세 전환.
    """
    # ── 주요 비과세 (고빈도) ──────────────────────────────────
    meal_allowance: float = 0.0            # 식대·식사비 (월)
    car_subsidy: float = 0.0               # 자가운전보조금 (월)
    childcare_allowance: float = 0.0       # 자녀보육수당 (월, 자녀 1인당)
    num_childcare_children: int = 0        # 6세 이하 자녀 수

    # ── 연장근로 비과세 (생산직) ──────────────────────────────
    overtime_nontax: float = 0.0           # 연장·야간·휴일근로수당 비과세분 (월)
    is_production_worker: bool = False     # 생산직 종사자 자기 선언
    prev_year_total_salary: float = 0.0   # 전년도 총급여 (적격 판단용)

    # ── 기타 비과세 ──────────────────────────────────────────
    overseas_pay: float = 0.0              # 국외근로소득 (월)
    is_overseas_construction: bool = False  # 해외건설현장 (한도 500만→100만)
    research_subsidy: float = 0.0          # 연구보조비 (월)
    reporting_subsidy: float = 0.0         # 취재수당 (월)
    remote_area_subsidy: float = 0.0       # 벽지수당 (월)
    invention_reward_annual: float = 0.0   # 직무발명보상금 (연간 총액)
    childbirth_support: float = 0.0        # 출산지원금 (월 환산, 한도 없음)
    other_nontaxable: float = 0.0          # 기타 비과세 (월, 사용자 직접 입력)

    @classmethod
    def from_dict(cls, d: dict) -> "NonTaxableIncome":
        """dict → NonTaxableIncome 변환 (chatbot 연동용)"""
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
```

### 3.2 WageInput 필드 추가 (`models.py`)

```python
# 기존 필드 유지
monthly_non_taxable: float = 200_000  # 기존 단일 비과세 (하위 호환)

# 신규 필드 추가
non_taxable_detail: Optional[NonTaxableIncome] = None  # 항목별 상세 (None=기존 방식)
```

---

## 4. 상수 정의 (`constants.py`)

### 4.1 NON_TAXABLE_LIMITS

```python
# ── 비과세 근로소득 한도 (소득세법 제12조, 시행령 제12조) ─────────────────
NON_TAXABLE_LIMITS: dict[int, dict] = {
    2025: {
        "meal":            200_000,   # 식대 월 20만원
        "car":             200_000,   # 자가운전보조금 월 20만원
        "childcare":       200_000,   # 보육수당 자녀 1인당 월 20만원 (6세 이하)
        "overtime_annual": 2_400_000, # 생산직 연장근로 연 240만원
        "overtime_monthly_salary": 2_100_000,  # 생산직 적격: 월정액 210만원 이하
        "overtime_prev_year_salary": 30_000_000,  # 생산직 적격: 전년 총급여 3,000만원 이하
        "overseas":        1_000_000, # 국외근로 월 100만원
        "overseas_construction": 5_000_000, # 해외건설 월 500만원
        "research":        200_000,   # 연구보조비 월 20만원
        "reporting":       200_000,   # 취재수당 월 20만원
        "remote_area":     200_000,   # 벽지수당 월 20만원
        "invention_annual": 7_000_000, # 직무발명 연 700만원
    },
    2026: {
        "meal":            200_000,
        "car":             200_000,
        "childcare":       200_000,
        "overtime_annual": 2_400_000,
        "overtime_monthly_salary": 2_600_000,  # 2026년~ 260만원
        "overtime_prev_year_salary": 37_000_000,  # 2026년~ 3,700만원
        "overseas":        1_000_000,
        "overseas_construction": 5_000_000,
        "research":        200_000,
        "reporting":       200_000,
        "remote_area":     200_000,
        "invention_annual": 7_000_000,
    },
}


def get_nontaxable_limits(year: int) -> dict:
    """연도별 비과세 한도 반환 (미등록 연도: 최근 연도 fallback)"""
    if year in NON_TAXABLE_LIMITS:
        return NON_TAXABLE_LIMITS[year]
    return NON_TAXABLE_LIMITS[max(NON_TAXABLE_LIMITS.keys())]
```

### 4.2 과세 근로소득 종류 (참조 상수, FR-07)

```python
# ── 과세 근로소득 종류 (소득세법 제20조, 참조·안내용) ──────────────────
TAXABLE_INCOME_TYPES: list[str] = [
    "봉급·급료·임금·상여금 및 유사 급여",
    "근로수당·가족수당·직무수당·근속수당 등",
    "급식수당 (비과세 한도 초과분)",
    "주택수당·주택 제공 이익",
    "주택 구입·임차 자금 저리 대여 이익",
    "학자금·장학금",
    "직무발명보상금 (비과세 한도 초과분)",
    "사용자 부담 보험료 (단체환급부보장성)",
    "주식매수선택권 행사 이익",
    "공로금·위로금·개업축하금 등",
]

# ── 비과세 근로소득 종류 (소득세법 제12조, 참조·안내용) ──────────────────
NON_TAXABLE_INCOME_LEGAL_BASIS: dict[str, str] = {
    "meal":       "소득세법 제12조제3호머목 (식대·식사비)",
    "car":        "소득세법 시행령 제12조 (자가운전보조금)",
    "childcare":  "소득세법 제12조제3호러목 (자녀보육수당)",
    "overtime":   "소득세법 제12조제3호나목 (생산직 연장·야간·휴일근로수당)",
    "overseas":   "소득세법 제12조제3호가목 (국외근로소득)",
    "research":   "소득세법 시행령 제12조제12호 (연구보조비)",
    "reporting":  "소득세법 시행령 제12조제13호 (취재수당)",
    "remote_area":"소득세법 시행령 제12조제9호 (벽지수당)",
    "invention":  "소득세법 제12조제3호바목 (직무발명보상금)",
    "childbirth": "소득세법 제12조제3호모목 (출산지원금)",
}
```

---

## 5. 핵심 함수 설계 (`insurance.py`)

### 5.1 calc_nontaxable_total()

```python
def calc_nontaxable_total(
    nti: NonTaxableIncome,
    year: int,
    inp: WageInput,
) -> tuple[float, list[str], list[str], list[str]]:
    """비과세 근로소득 항목별 한도 적용 후 월 합산

    Args:
        nti: 비과세 항목별 입력
        year: 기준 연도
        inp: WageInput (생산직 적격 판단용 monthly_wage 참조)

    Returns:
        (월 비과세 합계, warnings, formulas, legal_basis)
    """
    limits = get_nontaxable_limits(year)
    total = 0.0
    warnings = []
    formulas = []
    legal = []

    # ── 식대 ──────────────────────────────────────────────
    if nti.meal_allowance > 0:
        cap = limits["meal"]
        applied = min(nti.meal_allowance, cap)
        total += applied
        formulas.append(f"식대 비과세: {applied:,.0f}원 (한도 {cap:,.0f}원/월)")
        legal.append(NON_TAXABLE_INCOME_LEGAL_BASIS["meal"])
        if nti.meal_allowance > cap:
            excess = nti.meal_allowance - cap
            warnings.append(
                f"식대: {nti.meal_allowance:,.0f}원 중 {cap:,.0f}원만 비과세, "
                f"초과분 {excess:,.0f}원은 과세소득 편입"
            )

    # ── 자가운전보조금 ────────────────────────────────────
    if nti.car_subsidy > 0:
        cap = limits["car"]
        applied = min(nti.car_subsidy, cap)
        total += applied
        formulas.append(f"자가운전보조금 비과세: {applied:,.0f}원 (한도 {cap:,.0f}원/월)")
        legal.append(NON_TAXABLE_INCOME_LEGAL_BASIS["car"])
        if nti.car_subsidy > cap:
            excess = nti.car_subsidy - cap
            warnings.append(
                f"자가운전보조금: {nti.car_subsidy:,.0f}원 중 {cap:,.0f}원만 비과세, "
                f"초과분 {excess:,.0f}원은 과세소득 편입"
            )

    # ── 자녀보육수당 ──────────────────────────────────────
    if nti.childcare_allowance > 0 and nti.num_childcare_children > 0:
        cap = limits["childcare"] * nti.num_childcare_children
        applied = min(nti.childcare_allowance, cap)
        total += applied
        formulas.append(
            f"자녀보육수당 비과세: {applied:,.0f}원 "
            f"(6세 이하 {nti.num_childcare_children}명, 한도 {cap:,.0f}원/월)"
        )
        legal.append(NON_TAXABLE_INCOME_LEGAL_BASIS["childcare"])
        if nti.childcare_allowance > cap:
            warnings.append(
                f"보육수당: {nti.childcare_allowance:,.0f}원 중 {cap:,.0f}원만 비과세"
            )

    # ── 생산직 연장근로수당 비과세 ─────────────────────────
    if nti.overtime_nontax > 0:
        eligible, reason = _check_overtime_nontax_eligible(nti, limits, inp)
        if eligible:
            monthly_cap = limits["overtime_annual"] / 12
            applied = min(nti.overtime_nontax, monthly_cap)
            total += applied
            formulas.append(
                f"연장근로수당 비과세: {applied:,.0f}원/월 "
                f"(연 한도 {limits['overtime_annual']:,.0f}원)"
            )
            legal.append(NON_TAXABLE_INCOME_LEGAL_BASIS["overtime"])
            if nti.overtime_nontax > monthly_cap:
                warnings.append(
                    f"연장근로수당: 월 {nti.overtime_nontax:,.0f}원 중 "
                    f"{monthly_cap:,.0f}원만 비과세 (연 {limits['overtime_annual']:,.0f}원 한도)"
                )
        else:
            warnings.append(f"연장근로수당 비과세 부적격: {reason}")

    # ── 국외근로소득 ──────────────────────────────────────
    if nti.overseas_pay > 0:
        cap_key = "overseas_construction" if nti.is_overseas_construction else "overseas"
        cap = limits[cap_key]
        applied = min(nti.overseas_pay, cap)
        total += applied
        label = "해외건설현장" if nti.is_overseas_construction else "국외근로"
        formulas.append(f"{label} 비과세: {applied:,.0f}원 (한도 {cap:,.0f}원/월)")
        legal.append(NON_TAXABLE_INCOME_LEGAL_BASIS["overseas"])
        if nti.overseas_pay > cap:
            warnings.append(f"{label}: 초과분 {nti.overseas_pay - cap:,.0f}원 과세")

    # ── 연구보조비 ────────────────────────────────────────
    if nti.research_subsidy > 0:
        cap = limits["research"]
        applied = min(nti.research_subsidy, cap)
        total += applied
        formulas.append(f"연구보조비 비과세: {applied:,.0f}원 (한도 {cap:,.0f}원/월)")
        legal.append(NON_TAXABLE_INCOME_LEGAL_BASIS["research"])
        if nti.research_subsidy > cap:
            warnings.append(f"연구보조비: 초과분 {nti.research_subsidy - cap:,.0f}원 과세")

    # ── 취재수당 ──────────────────────────────────────────
    if nti.reporting_subsidy > 0:
        cap = limits["reporting"]
        applied = min(nti.reporting_subsidy, cap)
        total += applied
        formulas.append(f"취재수당 비과세: {applied:,.0f}원 (한도 {cap:,.0f}원/월)")
        legal.append(NON_TAXABLE_INCOME_LEGAL_BASIS["reporting"])
        if nti.reporting_subsidy > cap:
            warnings.append(f"취재수당: 초과분 {nti.reporting_subsidy - cap:,.0f}원 과세")

    # ── 벽지수당 ──────────────────────────────────────────
    if nti.remote_area_subsidy > 0:
        cap = limits["remote_area"]
        applied = min(nti.remote_area_subsidy, cap)
        total += applied
        formulas.append(f"벽지수당 비과세: {applied:,.0f}원 (한도 {cap:,.0f}원/월)")
        legal.append(NON_TAXABLE_INCOME_LEGAL_BASIS["remote_area"])
        if nti.remote_area_subsidy > cap:
            warnings.append(f"벽지수당: 초과분 {nti.remote_area_subsidy - cap:,.0f}원 과세")

    # ── 직무발명보상금 (연간 → 월 환산) ───────────────────
    if nti.invention_reward_annual > 0:
        cap = limits["invention_annual"]
        applied_annual = min(nti.invention_reward_annual, cap)
        applied_monthly = applied_annual / 12
        total += applied_monthly
        formulas.append(
            f"직무발명보상금 비과세: 연 {applied_annual:,.0f}원 "
            f"→ 월 {applied_monthly:,.0f}원 (한도 연 {cap:,.0f}원)"
        )
        legal.append(NON_TAXABLE_INCOME_LEGAL_BASIS["invention"])
        if nti.invention_reward_annual > cap:
            warnings.append(
                f"직무발명보상금: 연 {nti.invention_reward_annual:,.0f}원 중 "
                f"{cap:,.0f}원만 비과세"
            )

    # ── 출산지원금 (한도 없음) ─────────────────────────────
    if nti.childbirth_support > 0:
        total += nti.childbirth_support
        formulas.append(f"출산지원금 비과세: {nti.childbirth_support:,.0f}원 (한도 없음)")
        legal.append(NON_TAXABLE_INCOME_LEGAL_BASIS["childbirth"])

    # ── 기타 비과세 (사용자 직접 입력, 한도 없음) ──────────
    if nti.other_nontaxable > 0:
        total += nti.other_nontaxable
        formulas.append(f"기타 비과세: {nti.other_nontaxable:,.0f}원 (사용자 입력)")

    formulas.append(f"비과세 근로소득 합계: {total:,.0f}원/월")

    return total, warnings, formulas, legal
```

### 5.2 _check_overtime_nontax_eligible()

```python
def _check_overtime_nontax_eligible(
    nti: NonTaxableIncome,
    limits: dict,
    inp: WageInput,
) -> tuple[bool, str]:
    """생산직 연장근로수당 비과세 적격 여부 (소득세법 제12조제3호나목)

    조건:
      1. 생산직 및 관련직 종사자 (자기 선언)
      2. 월정액급여 260만원 이하 (2026년~, 2025년까지 210만원)
      3. 전년도 총급여 3,700만원 이하 (2026년~, 2025년까지 3,000만원)
    """
    if not nti.is_production_worker:
        return False, "생산직 종사자가 아닌 것으로 입력됨"

    monthly_limit = limits["overtime_monthly_salary"]
    monthly_wage = inp.monthly_wage or 0
    if monthly_wage > monthly_limit:
        return False, f"월정액급여 {monthly_wage:,.0f}원 > 한도 {monthly_limit:,.0f}원"

    annual_limit = limits["overtime_prev_year_salary"]
    if nti.prev_year_total_salary > 0 and nti.prev_year_total_salary > annual_limit:
        return False, (
            f"전년도 총급여 {nti.prev_year_total_salary:,.0f}원 > "
            f"한도 {annual_limit:,.0f}원"
        )

    return True, ""
```

### 5.3 _calc_employee() 통합 지점

```python
# insurance.py _calc_employee() 내 (line ~168 부근)
# AS-IS:
taxable_monthly = max(0.0, gross - inp.monthly_non_taxable)

# TO-BE:
if inp.non_taxable_detail is not None:
    nontax_amount, nontax_warns, nontax_formulas, nontax_legal = (
        calc_nontaxable_total(inp.non_taxable_detail, year, inp)
    )
    warnings.extend(nontax_warns)
    formulas.extend(nontax_formulas)
    legal.extend(nontax_legal)
else:
    nontax_amount = inp.monthly_non_taxable

taxable_monthly = max(0.0, gross - nontax_amount)
```

---

## 6. legal_hints.py 추가 힌트

```python
def _hints_nontaxable(inp: WageInput) -> list[LegalHint]:
    """비과세 근로소득 관련 법률 힌트"""
    hints = []

    # 비과세 상세 미사용 + 기본 20만원 사용 시 안내
    if inp.non_taxable_detail is None and inp.monthly_non_taxable == 200_000:
        hints.append(LegalHint(
            category="비과세소득",
            condition="식대 20만원만 비과세 적용 중",
            hint="자가운전보조금, 자녀보육수당, 연구보조비 등 추가 비과세 항목이 있으면 "
                 "non_taxable_detail로 상세 입력 시 실수령액이 증가할 수 있습니다.",
            basis="소득세법 제12조 (비과세소득)",
            priority=2,
        ))

    # 생산직 연장근로수당 비과세 가능성 안내
    if (inp.non_taxable_detail is None
            and (inp.monthly_wage or 0) <= 2_600_000
            and inp.schedule.weekly_overtime_hours > 0):
        hints.append(LegalHint(
            category="비과세소득",
            condition=f"월급 {(inp.monthly_wage or 0):,.0f}원 + 연장근로 있음",
            hint="생산직 종사자인 경우 연장·야간·휴일근로수당 연 240만원까지 비과세 가능. "
                 "non_taxable_detail.is_production_worker=True로 설정하세요.",
            basis="소득세법 제12조제3호나목",
            priority=2,
        ))

    return hints
```

---

## 7. __init__.py Export 추가

```python
# wage_calculator/__init__.py
from .models import (
    ...,
    NonTaxableIncome,  # 추가
)

__all__ = [
    ...,
    "NonTaxableIncome",  # 추가
]
```

---

## 8. Test Plan

### 8.1 테스트 케이스

| ID | 설명 | 입력 | 기대 결과 |
|----|------|------|-----------|
| NT-01 | 식대만 (기존 호환 검증) | `NonTaxableIncome(meal_allowance=200_000)` | 비과세 20만원, 기존 `monthly_non_taxable=200_000`과 동일 세금 |
| NT-02 | 식대+자가운전 | `meal=200_000, car=200_000` | 비과세 40만원, 과세소득 20만원 감소 |
| NT-03 | 식대 한도 초과 | `meal=300_000` | 비과세 20만원 + warning "초과분 10만원 과세" |
| NT-04 | 생산직 OT 적격 | `overtime_nontax=300_000, is_production_worker=True`, 월급 200만원 | 비과세 20만원/월 (연240만한도) |
| NT-05 | 생산직 OT 부적격 (월급 초과) | `overtime_nontax=300_000, is_production_worker=True`, 월급 300만원 | 비과세 0원 + warning "부적격" |
| NT-06 | non_taxable_detail=None 하위 호환 | 기존 WageInput(monthly_non_taxable=200_000) | 기존 결과와 100% 동일 |
| NT-07 | 국외근로 (건설현장) | `overseas_pay=4_000_000, is_overseas_construction=True` | 비과세 400만원 (한도 500만) |
| NT-08 | 복합 항목 (식대+차량+보육) | `meal=200_000, car=150_000, childcare=200_000, num_childcare_children=1` | 비과세 55만원 |

### 8.2 기존 테스트 회귀

- `wage_calculator_cli.py` 전체 테스트 케이스 (#1~#32+) 통과 확인
- 모두 `non_taxable_detail=None` → 기존 로직 경유 → 결과 변경 없음

---

## 9. Implementation Order

### 9.1 순서

1. [ ] `constants.py` — `NON_TAXABLE_LIMITS`, `get_nontaxable_limits()`, `NON_TAXABLE_INCOME_LEGAL_BASIS`, `TAXABLE_INCOME_TYPES` 추가
2. [ ] `models.py` — `NonTaxableIncome` dataclass + `WageInput.non_taxable_detail` 필드 추가
3. [ ] `insurance.py` — `calc_nontaxable_total()`, `_check_overtime_nontax_eligible()` 추가 + `_calc_employee()` 통합
4. [ ] `__init__.py` — `NonTaxableIncome` export
5. [ ] `legal_hints.py` — `_hints_nontaxable()` 추가 + `generate_legal_hints()` 연결
6. [ ] `wage_calculator_cli.py` — NT-01 ~ NT-08 테스트 케이스 추가
7. [ ] 기존 테스트 전체 통과 확인

### 9.2 변경 규모 예상

| File | Added Lines | Modified Lines |
|------|------------|----------------|
| constants.py | ~50 | 0 |
| models.py | ~25 | 2 |
| insurance.py | ~120 | 5 |
| __init__.py | 2 | 1 |
| legal_hints.py | ~25 | 2 |
| wage_calculator_cli.py | ~60 | 0 |
| **Total** | **~282** | **~10** |

---

## 10. Error Handling

| 상황 | 처리 방식 |
|------|-----------|
| `non_taxable_detail=None` | 기존 `monthly_non_taxable` 사용 (기본 동작) |
| 비과세 항목 음수 입력 | `max(0, value)` 처리 + warning |
| `num_childcare_children=0`이지만 `childcare_allowance>0` | warning "6세 이하 자녀 수 미입력" |
| 생산직 적격 조건 미충족 | `overtime_nontax` 전액 과세 + 사유 warning |
| 비과세 합계 > gross | `taxable_monthly = max(0, gross - nontax)` (음수 방지) |
| `from_dict()` 알 수 없는 키 | 무시 (dict comprehension 필터) |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-13 | Initial draft | Claude |
