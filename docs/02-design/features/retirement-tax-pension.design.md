# Design: 퇴직금/퇴직연금/퇴직소득세 계산기

## Executive Summary

| Item | Detail |
|------|--------|
| Feature | 퇴직소득세 계산기 + 퇴직연금(DC/DB) 계산기 + severance.py 개선 |
| Plan Reference | `docs/01-plan/features/retirement-tax-pension.plan.md` |
| New Files | 2개 (`retirement_tax.py`, `retirement_pension.py`) |
| Modified Files | 5개 (`constants.py`, `models.py`, `severance.py`, `facade.py`, `wage_calculator_cli.py`) |

---

## 1. 아키텍처 설계

### 1.1 계산 흐름도

```
                        WageInput
                           │
                    ┌──────┴──────┐
                    ▼             ▼
              calc_ordinary_wage  │
                    │             │
              ┌─────┴─────┐      │
              ▼           ▼      │
         calc_severance   │      │
         (개선: 상여금/    │      │
          연차수당 가산)   │      │
              │           │      │
              ▼           │      │
         calc_retirement_tax     │
         (퇴직소득세)            │
              │                  │
              ▼                  ▼
         IRP 과세이연     calc_retirement_pension
                          (DC/DB형)
```

### 1.2 계산기 간 의존관계

| 계산기 | 입력 의존 | 결과 의존 |
|--------|----------|----------|
| `retirement_tax` | WageInput, OrdinaryWageResult | SeveranceResult (퇴직금액, 근속연수) |
| `retirement_pension` | WageInput, OrdinaryWageResult | SeveranceResult (DB형은 퇴직금 동일) |
| `severance` (개선) | WageInput, OrdinaryWageResult | 없음 (기존과 동일) |

### 1.3 facade.py 통합 흐름

```python
# retirement_tax는 severance 결과를 참조해야 하므로,
# facade에서 severance 실행 후 retirement_tax에 결과 전달

# 기존 _STANDARD_CALCS 패턴과 다름: severance 결과 필요
# → _DEPENDENT_CALCS 패턴 추가 또는 특수 처리

# 방안: retirement_tax는 특수 디스패처로 처리
# (wage_arrears와 유사한 패턴)
```

---

## 2. 상세 설계: constants.py 추가

### 2.1 퇴직소득세 상수

```python
# ── 퇴직소득세 (소득세법 제48조, 시행령 제42조의2) ─────────────────────────

# 근속연수공제 테이블: (상한연수, 연간공제액, 기본누적공제)
# differenceY <= upper: base + (differenceY - prev_upper) * per_year
RETIREMENT_SERVICE_DEDUCTION = [
    # (upper_years, per_year_deduction, base_deduction)
    (5,   1_000_000,          0),  # 1~5년: 연 100만원
    (10,  2_000_000,  5_000_000),  # 6~10년: 500만 + (N-5) x 200만
    (20,  2_500_000, 15_000_000),  # 11~20년: 1500만 + (N-10) x 250만
    (999, 3_000_000, 40_000_000),  # 21년~: 4000만 + (N-20) x 300만
]

# 환산급여별 공제 테이블: (상한금액, 공제율, 기본누적공제)
# hPay <= upper: base + (hPay - prev_upper) * rate
CONVERTED_SALARY_DEDUCTION = [
    # (upper_amount, deduction_rate, base_deduction)
    (  8_000_000, 1.00,           0),  # ~800만: 전액
    ( 70_000_000, 0.60,   8_000_000),  # ~7000만: 800만 + 초과 x 60%
    (100_000_000, 0.55,  45_200_000),  # ~1억: 4520만 + 초과 x 55%
    (300_000_000, 0.45,  61_700_000),  # ~3억: 6170만 + 초과 x 45%
    (float('inf'), 0.35, 151_700_000), # 3억~: 1억5170만 + 초과 x 35%
]

# 퇴직소득세율 = 종합소득세율과 동일 → INCOME_TAX_BRACKETS 재사용

# 지방소득세율
LOCAL_INCOME_TAX_RATE = 0.10  # 퇴직소득세의 10%
```

---

## 3. 상세 설계: models.py 추가 필드

### 3.1 WageInput 추가 필드

```python
@dataclass
class WageInput:
    # ... 기존 필드 ...

    # ── 퇴직소득세 계산용 ────────────────────────────────────────────────────
    retirement_pay_amount: float = 0.0         # 퇴직급여 총액 (0이면 severance에서 자동)
    irp_transfer_amount: float = 0.0           # IRP 이체금액 (과세이연)
    retirement_exclude_months: int = 0         # 근속기간 제외월수
    retirement_add_months: int = 0             # 근속기간 가산월수

    # ── 퇴직연금 계산용 ──────────────────────────────────────────────────────
    pension_type: str = ""                     # "DB" / "DC" / ""
    annual_wage_history: Optional[list] = None # DC: 연도별 연간임금총액 [y1, y2, ...]
    dc_return_rate: float = 0.0               # DC: 연간 운용수익률 (0.0 = 0%)

    # ── 퇴직금 평균임금 가산용 ───────────────────────────────────────────────
    annual_bonus_total: float = 0.0            # 연간 상여금 총액
    unused_annual_leave_pay: float = 0.0       # 최종 미사용 연차수당
```

### 3.2 설계 근거

| 필드 | 근거 |
|------|------|
| `retirement_pay_amount` | 퇴직소득세 단독 계산 시 직접 입력. severance와 연동 시 0 유지 |
| `irp_transfer_amount` | nodong.kr 계산기의 "퇴직연금계좌 지급액" 입력 대응 |
| `retirement_exclude_months` | 군복무, 해외파견 등 근속기간 제외 |
| `retirement_add_months` | 산재 요양 등 가산기간 |
| `pension_type` | DB/DC 구분. ""이면 미사용 |
| `annual_wage_history` | DC형 적립금 계산에 필요한 연도별 임금 |
| `dc_return_rate` | DC형 운용수익률. 기본 0% (최소 보장) |
| `annual_bonus_total` | nodong.kr/tj의 "연간 상여금 총액" 입력 대응 |
| `unused_annual_leave_pay` | nodong.kr/tj의 "최종 연차수당" 입력 대응 |

---

## 4. 상세 설계: retirement_tax.py

### 4.1 RetirementTaxResult 클래스

```python
@dataclass
class RetirementTaxResult(BaseCalculatorResult):
    # 입력/기본
    retirement_pay: float = 0.0           # 퇴직급여 총액
    service_years: int = 0                # 근속연수 (정수, 1년 미만 올림)

    # 공제 과정
    service_deduction: float = 0.0        # 근속연수공제액
    converted_salary: float = 0.0         # 환산급여
    converted_deduction: float = 0.0      # 환산급여별 공제액
    tax_base: float = 0.0                 # 과세표준

    # 세액
    converted_tax: float = 0.0            # 환산산출세액
    retirement_income_tax: float = 0.0    # 퇴직소득세
    local_income_tax: float = 0.0         # 지방소득세
    total_tax: float = 0.0               # 총 세액 (소득세 + 지방세)

    # IRP 과세이연
    irp_amount: float = 0.0              # IRP 이체금액
    deferred_tax: float = 0.0            # 이연 퇴직소득세
    deferred_local_tax: float = 0.0      # 이연 지방소득세
    withholding_tax: float = 0.0         # 원천징수 퇴직소득세
    withholding_local_tax: float = 0.0   # 원천징수 지방소득세

    # 실수령액
    net_retirement_pay: float = 0.0       # 실수령 퇴직금 (세후)
```

### 4.2 calc_retirement_tax 함수 시그니처

```python
def calc_retirement_tax(
    inp: WageInput,
    ow: OrdinaryWageResult,
    severance_result: SeveranceResult | None = None,
) -> RetirementTaxResult:
    """
    퇴직소득세 계산 (소득세법 제48조, 시행령 제42조의2)

    Args:
        inp: WageInput (retirement_pay_amount, irp_transfer_amount 등)
        ow: OrdinaryWageResult (미사용, 시그니처 통일)
        severance_result: severance 계산 결과 (있으면 퇴직금/근속연수 자동 연결)

    Returns:
        RetirementTaxResult
    """
```

### 4.3 계산 알고리즘 상세

```python
def calc_retirement_tax(inp, ow, severance_result=None):
    # ── Step 1: 퇴직급여 결정 ──────────────────────────────────────────────
    if severance_result and severance_result.is_eligible:
        retirement_pay = severance_result.severance_pay
        service_days = severance_result.service_days
    else:
        retirement_pay = inp.retirement_pay_amount
        # start_date/end_date에서 근속일수 계산
        start = parse_date(inp.start_date)
        end = parse_date(inp.end_date) or date.today()
        service_days = (end - start).days if start else 0

    if retirement_pay <= 0 or service_days <= 0:
        return _zero_result(...)

    # ── Step 2: 근속연수 계산 ──────────────────────────────────────────────
    # 근속월수에서 제외/가산 반영
    total_months = service_days * 12 / 365
    total_months = total_months - inp.retirement_exclude_months + inp.retirement_add_months
    service_years = max(1, math.ceil(total_months / 12))  # 1년 미만 올림

    # ── Step 3: 근속연수공제 ───────────────────────────────────────────────
    service_deduction = _calc_service_deduction(service_years)
    service_deduction = min(service_deduction, retirement_pay)  # 퇴직급여 초과 불가

    # ── Step 4: 환산급여 ───────────────────────────────────────────────────
    if service_years == 0:
        converted_salary = 0
    else:
        converted_salary = math.floor(
            (retirement_pay - service_deduction) * 12 / service_years
        )

    # ── Step 5: 환산급여별 공제 ────────────────────────────────────────────
    converted_deduction = _calc_converted_deduction(converted_salary)

    # ── Step 6: 과세표준 ──────────────────────────────────────────────────
    tax_base = max(0, converted_salary - converted_deduction)

    # ── Step 7: 환산산출세액 (종합소득세율 적용) ───────────────────────────
    converted_tax = _calc_tax_by_brackets(tax_base)

    # ── Step 8: 최종 퇴직소득세 ────────────────────────────────────────────
    retirement_income_tax = math.floor(converted_tax / 12 * service_years)
    local_income_tax = math.floor(retirement_income_tax * LOCAL_INCOME_TAX_RATE)
    total_tax = retirement_income_tax + local_income_tax

    # ── Step 9: IRP 과세이연 ──────────────────────────────────────────────
    irp_amount = inp.irp_transfer_amount
    if irp_amount > 0 and retirement_pay > 0:
        deferred_tax = math.floor(retirement_income_tax * irp_amount / retirement_pay)
        deferred_local_tax = math.floor(deferred_tax * LOCAL_INCOME_TAX_RATE)
    else:
        deferred_tax = 0
        deferred_local_tax = 0

    # 원천징수액 (10원 미만 절사)
    withholding_tax = math.floor((retirement_income_tax - deferred_tax) / 10) * 10
    withholding_local_tax = math.floor((local_income_tax - deferred_local_tax) / 10) * 10

    # ── 실수령액 ──────────────────────────────────────────────────────────
    net_retirement_pay = retirement_pay - withholding_tax - withholding_local_tax

    return RetirementTaxResult(...)
```

### 4.4 내부 헬퍼 함수

```python
def _calc_service_deduction(years: int) -> float:
    """근속연수공제 계산"""
    prev_upper = 0
    for upper, per_year, base in RETIREMENT_SERVICE_DEDUCTION:
        if years <= upper:
            return base + (years - prev_upper) * per_year
        prev_upper = upper
    return 0  # unreachable

def _calc_converted_deduction(converted_salary: float) -> float:
    """환산급여별 공제 계산"""
    if converted_salary <= 0:
        return 0
    prev_upper = 0
    for upper, rate, base in CONVERTED_SALARY_DEDUCTION:
        if converted_salary <= upper:
            return base + (converted_salary - prev_upper) * rate
        prev_upper = upper
    return 0  # unreachable

def _calc_tax_by_brackets(tax_base: float) -> float:
    """종합소득세율 적용 (INCOME_TAX_BRACKETS 재사용)"""
    if tax_base <= 0:
        return 0
    for upper, rate, deduction in INCOME_TAX_BRACKETS:
        if tax_base <= upper:
            return tax_base * rate - deduction
    return 0  # unreachable
```

---

## 5. 상세 설계: retirement_pension.py

### 5.1 RetirementPensionResult 클래스

```python
@dataclass
class RetirementPensionResult(BaseCalculatorResult):
    pension_type: str = ""                # "DB" / "DC"
    total_pension: float = 0.0            # 총 퇴직연금 수령액
    total_contribution: float = 0.0       # 총 적립금 (DC)
    investment_return: float = 0.0        # 운용수익 (DC)
    service_years: float = 0.0            # 근속연수
    annual_contributions: list = field(default_factory=list)  # DC: 연도별 적립내역
```

### 5.2 calc_retirement_pension 함수

```python
def calc_retirement_pension(
    inp: WageInput,
    ow: OrdinaryWageResult,
    severance_result: SeveranceResult | None = None,
) -> RetirementPensionResult:
    """
    퇴직연금 계산
    - DB형: 퇴직금과 동일 (근퇴법 제15조)
    - DC형: 연간임금총액 1/12 적립 합계 + 운용수익 (근퇴법 제17조)
    """
```

### 5.3 DC형 계산 로직

```python
def _calc_dc_pension(inp, ow, severance_result):
    """DC형: 매년 연간임금총액/12 적립"""
    contributions = []

    if inp.annual_wage_history:
        # 연도별 실제 임금 제공
        for i, annual_wage in enumerate(inp.annual_wage_history, 1):
            contribution = annual_wage / 12
            contributions.append({
                "year": i,
                "annual_wage": annual_wage,
                "contribution": contribution,
            })
    else:
        # monthly_wage x 12 기준 추정
        annual_wage = (inp.monthly_wage or ow.monthly_ordinary_wage) * 12
        start = parse_date(inp.start_date)
        end = parse_date(inp.end_date) or date.today()
        years = max(1, round((end - start).days / 365)) if start else 1
        for i in range(1, years + 1):
            contribution = annual_wage / 12
            contributions.append({
                "year": i,
                "annual_wage": annual_wage,
                "contribution": contribution,
            })

    total_contribution = sum(c["contribution"] for c in contributions)

    # 운용수익 (복리 계산)
    if inp.dc_return_rate > 0:
        accumulated = 0.0
        for c in contributions:
            accumulated = (accumulated + c["contribution"]) * (1 + inp.dc_return_rate)
        investment_return = accumulated - total_contribution
        total_pension = accumulated
    else:
        investment_return = 0.0
        total_pension = total_contribution

    return total_pension, total_contribution, investment_return, contributions
```

### 5.4 DB형 계산 로직

```python
def _calc_db_pension(inp, ow, severance_result):
    """DB형: 퇴직금과 동일 공식"""
    if severance_result and severance_result.is_eligible:
        return severance_result.severance_pay
    # severance 없으면 직접 계산
    avg_daily = ow.hourly_ordinary_wage * 8  # 통상임금 기준 최소
    start = parse_date(inp.start_date)
    end = parse_date(inp.end_date) or date.today()
    service_days = (end - start).days if start else 0
    return avg_daily * 30 * (service_days / 365) if service_days > 0 else 0
```

---

## 6. 상세 설계: severance.py 개선

### 6.1 _calc_avg_daily_3m 수정

현재 코드 (`severance.py:194-207`):
```python
def _calc_avg_daily_3m(inp: WageInput, ow: OrdinaryWageResult) -> float:
    period_days = inp.last_3m_days or AVG_WAGE_PERIOD_DAYS
    if inp.last_3m_wages:
        total = sum(inp.last_3m_wages)
    elif inp.monthly_wage:
        total = inp.monthly_wage * 3
    else:
        total = ow.monthly_ordinary_wage * 3
    return total / period_days
```

수정 후:
```python
def _calc_avg_daily_3m(inp: WageInput, ow: OrdinaryWageResult) -> float:
    period_days = inp.last_3m_days or AVG_WAGE_PERIOD_DAYS

    # A. 퇴직 전 3개월 임금총액
    if inp.last_3m_wages:
        wage_total = sum(inp.last_3m_wages)
    elif inp.monthly_wage:
        wage_total = inp.monthly_wage * 3
    else:
        wage_total = ow.monthly_ordinary_wage * 3

    # B. 상여금 가산 (연간상여금 x 3/12)
    bonus_addition = inp.annual_bonus_total * 3 / 12 if inp.annual_bonus_total > 0 else 0

    # C. 연차수당 가산 (연차수당 x 3/12)
    leave_addition = inp.unused_annual_leave_pay * 3 / 12 if inp.unused_annual_leave_pay > 0 else 0

    total = wage_total + bonus_addition + leave_addition
    return total / period_days
```

### 6.2 IRP 의무지급 안내 추가

`calc_severance()` 함수 말미, 퇴직금 산정 후:

```python
# IRP 의무 안내 (2022.4.14 이후)
if end >= date(2022, 4, 14):
    warnings.append(
        "2022.4.14 이후 퇴직 시 퇴직금은 IRP(개인형퇴직연금) 계좌로 "
        "세전 금액 전액 지급해야 합니다 (근로자퇴직급여보장법 제9조). "
        "퇴직소득세는 IRP 계좌에서 인출 시 원천징수됩니다."
    )
    legal.append("근로자퇴직급여보장법 제9조 (개인형퇴직연금제도의 설정 등)")
```

### 6.3 breakdown에 상여금/연차수당 가산 내역 추가

```python
if inp.annual_bonus_total > 0:
    breakdown["상여금 가산"] = f"{bonus_addition:,.0f}원 (연 {inp.annual_bonus_total:,.0f}원 × 3/12)"
if inp.unused_annual_leave_pay > 0:
    breakdown["연차수당 가산"] = f"{leave_addition:,.0f}원 (연차수당 {inp.unused_annual_leave_pay:,.0f}원 × 3/12)"
```

---

## 7. 상세 설계: facade.py 통합

### 7.1 import 추가

```python
from .calculators.retirement_tax import calc_retirement_tax
from .calculators.retirement_pension import calc_retirement_pension
```

### 7.2 CALC_TYPES 추가

```python
CALC_TYPES = {
    # ... 기존 ...
    "retirement_tax":     "퇴직소득세",
    "retirement_pension": "퇴직연금(DB/DC)",
}
```

### 7.3 CALC_TYPE_MAP 추가

```python
CALC_TYPE_MAP = {
    # ... 기존 ...
    "퇴직소득세":   ["severance", "retirement_tax"],
    "퇴직연금":     ["retirement_pension"],
    "퇴직":        ["severance", "retirement_tax"],
}
```

### 7.4 populate 함수

```python
def _pop_retirement_tax(r, result):
    result.summary["퇴직소득세"] = f"{r.retirement_income_tax:,.0f}원"
    result.summary["지방소득세"] = f"{r.local_income_tax:,.0f}원"
    result.summary["총 세액"] = f"{r.total_tax:,.0f}원"
    result.summary["실수령 퇴직금"] = f"{r.net_retirement_pay:,.0f}원"
    if r.irp_amount > 0:
        result.summary["IRP 이연세액"] = f"{r.deferred_tax + r.deferred_local_tax:,.0f}원"
    return 0

def _pop_retirement_pension(r, result):
    result.summary["퇴직연금 유형"] = r.pension_type
    result.summary["퇴직연금 수령액"] = f"{r.total_pension:,.0f}원"
    if r.pension_type == "DC":
        result.summary["총 적립금"] = f"{r.total_contribution:,.0f}원"
        result.summary["운용수익"] = f"{r.investment_return:,.0f}원"
    return 0
```

### 7.5 디스패처 처리 (retirement_tax 특수 처리)

retirement_tax는 severance 결과에 의존하므로, `_STANDARD_CALCS`에 넣지 않고 특수 처리:

```python
# facade.py calculate() 내부, 표준 계산기 루프 이후:

# ── 특수 계산기: 퇴직소득세 (severance 결과 참조) ───────────────────────
if "retirement_tax" in targets:
    # severance 결과 찾기
    sev_result = None
    for key, func, section, populate, precondition in _STANDARD_CALCS:
        if key == "severance":
            # 이미 실행되었으면 결과 참조
            break
    # severance가 targets에 없었으면 실행
    if "severance" not in targets:
        sev_result = calc_severance(inp, ow)
    else:
        sev_result = _severance_cache  # 캐시에서 참조

    rt = calc_retirement_tax(inp, ow, sev_result)
    _pop_retirement_tax(rt, result)
    _merge(result, "퇴직소득세", rt, all_w, all_l)

# ── 특수 계산기: 퇴직연금 ──────────────────────────────────────────────
if "retirement_pension" in targets and inp.pension_type:
    rp = calc_retirement_pension(inp, ow, sev_result)
    _pop_retirement_pension(rp, result)
    _merge(result, "퇴직연금", rp, all_w, all_l)
```

**캐시 방안**: severance 결과를 변수에 저장하여 retirement_tax에서 참조.

```python
# 실제 구현: _STANDARD_CALCS 루프에서 severance 결과 캐시
_severance_cache = None
for key, func, section, populate, precondition in _STANDARD_CALCS:
    if key not in targets:
        continue
    if precondition and not precondition(inp):
        continue
    r = func(inp, ow)
    if key == "severance":
        _severance_cache = r  # 캐시
    monthly_total += populate(r, result)
    _merge(result, section, r, all_w, all_l)
```

### 7.6 _auto_detect_targets 추가

```python
def _auto_detect_targets(self, inp):
    targets = [...]  # 기존

    # 퇴직소득세: severance가 있고 retirement_pay_amount 또는 irp_transfer_amount 있으면
    if "severance" in targets or inp.retirement_pay_amount > 0:
        targets.append("retirement_tax")

    # 퇴직연금: pension_type이 있으면
    if inp.pension_type:
        targets.append("retirement_pension")

    return targets
```

---

## 8. 테스트 설계: wage_calculator_cli.py

### 8.1 테스트 케이스 #33: 단기 근속 퇴직소득세

```python
{
    "case": 33,
    "title": "퇴직소득세 — 3년 근속",
    "input": WageInput(
        monthly_wage=3_000_000,
        start_date="2023-03-07",
        end_date="2026-03-07",
        retirement_pay_amount=0,  # severance 자동 연동
    ),
    "targets": ["severance", "retirement_tax"],
    "expect": {
        "근속연수공제": 3_000_000,  # 3년 x 100만
        "퇴직소득세 > 0": True,    # 세액 발생
    },
}
```

### 8.2 테스트 케이스 #34: 10년 근속 퇴직소득세

```python
{
    "case": 34,
    "title": "퇴직소득세 — 10년 근속",
    "input": WageInput(
        monthly_wage=3_000_000,
        start_date="2016-03-07",
        end_date="2026-03-07",
    ),
    "targets": ["severance", "retirement_tax"],
    "expect": {
        "근속연수공제": 15_000_000,  # 500만 + 5 x 200만
    },
}
```

### 8.3 테스트 케이스 #35: IRP 과세이연

```python
{
    "case": 35,
    "title": "퇴직소득세 — IRP 과세이연",
    "input": WageInput(
        retirement_pay_amount=50_000_000,
        irp_transfer_amount=30_000_000,
        start_date="2016-03-07",
        end_date="2026-03-07",
    ),
    "targets": ["retirement_tax"],
    "expect": {
        "이연비율": 0.6,  # 3000만/5000만 = 60%
    },
}
```

### 8.4 테스트 케이스 #36: 장기근속 고액

```python
{
    "case": 36,
    "title": "퇴직소득세 — 25년 근속 1억원",
    "input": WageInput(
        retirement_pay_amount=100_000_000,
        start_date="2001-03-07",
        end_date="2026-03-07",
    ),
    "targets": ["retirement_tax"],
    "expect": {
        "근속연수공제": 55_000_000,  # 4000만 + 5 x 300만
    },
}
```

### 8.5 테스트 케이스 #37: DB형 퇴직연금

```python
{
    "case": 37,
    "title": "퇴직연금 DB형 — 퇴직금 동일",
    "input": WageInput(
        monthly_wage=3_000_000,
        start_date="2016-03-07",
        end_date="2026-03-07",
        pension_type="DB",
    ),
    "targets": ["severance", "retirement_pension"],
    "expect": {
        "DB형 == 퇴직금": True,
    },
}
```

### 8.6 테스트 케이스 #38: DC형 퇴직연금

```python
{
    "case": 38,
    "title": "퇴직연금 DC형 — 5년 적립",
    "input": WageInput(
        pension_type="DC",
        annual_wage_history=[36_000_000] * 5,  # 연 3600만 x 5년
    ),
    "targets": ["retirement_pension"],
    "expect": {
        "총적립금": 15_000_000,  # 3600만/12 x 5
    },
}
```

### 8.7 테스트 케이스 #39: 상여금 가산

```python
{
    "case": 39,
    "title": "퇴직금 — 상여금 가산 반영",
    "input": WageInput(
        monthly_wage=3_000_000,
        annual_bonus_total=6_000_000,  # 연 600만 상여금
        start_date="2023-03-07",
        end_date="2026-03-07",
    ),
    "targets": ["severance"],
    "expect": {
        "상여금가산포함": True,
        # 3개월 임금 = 900만 + 상여금가산(600만x3/12=150만) = 1050만
        # 평균임금 = 1050만 / 92 ≈ 114,130원/일
    },
}
```

### 8.8 테스트 케이스 #40: 연차수당 가산

```python
{
    "case": 40,
    "title": "퇴직금 — 연차수당 가산 반영",
    "input": WageInput(
        monthly_wage=3_000_000,
        unused_annual_leave_pay=1_000_000,  # 연차수당 100만
        start_date="2023-03-07",
        end_date="2026-03-07",
    ),
    "targets": ["severance"],
    "expect": {
        "연차수당가산포함": True,
        # 3개월 임금 = 900만 + 연차수당가산(100만x3/12=25만) = 925만
    },
}
```

---

## 9. 구현 순서

| 순서 | 파일 | 작업 | 예상 LOC |
|------|------|------|---------|
| 1 | `constants.py` | 퇴직소득세 테이블 상수 추가 | +25 |
| 2 | `models.py` | WageInput 필드 8개 추가 | +20 |
| 3 | `calculators/retirement_tax.py` | 퇴직소득세 계산기 신규 | ~150 |
| 4 | `calculators/severance.py` | 상여금/연차수당 가산 + IRP 안내 | ~30 변경 |
| 5 | `calculators/retirement_pension.py` | DC/DB 퇴직연금 계산기 신규 | ~120 |
| 6 | `facade.py` | 디스패처 등록, 캐시, auto_detect | ~50 변경 |
| 7 | `wage_calculator_cli.py` | 테스트 케이스 #33~#40 | ~120 |
| 8 | 검증 | nodong.kr 계산 결과와 교차 검증 | - |

**총 예상**: 신규 ~270 LOC + 수정 ~100 LOC = ~370 LOC

---

## 10. 엣지 케이스 및 주의사항

| 엣지 케이스 | 처리 방법 |
|------------|----------|
| 근속연수 0년 (1년 미만) | `service_years = max(1, ceil(...))` → 최소 1년 |
| 퇴직급여 < 근속연수공제 | `service_deduction = min(deduction, pay)` → 퇴직급여 한도 |
| 환산급여 음수 | `converted_salary = max(0, ...)` |
| 과세표준 0 | 세액 0 반환 |
| IRP 금액 > 퇴직급여 | `irp = min(irp, retirement_pay)` |
| DC형 연도별 임금 미제공 | `monthly_wage x 12` 균등 추정 |
| 2024년 이전 퇴직 | warning 추가 (구법 미지원 안내) |
| `math.floor` 절사 | nodong.kr JS와 동일하게 원 단위 이하 절사 |
| 10원 미만 절사 (원천징수) | `floor(amount / 10) * 10` |
