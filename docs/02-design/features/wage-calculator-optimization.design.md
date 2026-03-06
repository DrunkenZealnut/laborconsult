# Design: 임금계산기 전체모듈 분석 및 효율화

> Plan 참조: `docs/01-plan/features/wage-calculator-optimization.plan.md`

---

## 1. 신규 파일 설계

### 1.1 `wage_calculator/base.py`

```python
from dataclasses import dataclass, field


@dataclass
class BaseCalculatorResult:
    """모든 계산기 Result의 공통 기반 클래스"""
    breakdown: dict = field(default_factory=dict)
    formulas: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    legal_basis: list = field(default_factory=list)
```

**상속 적용 대상 (18개)**:
OvertimeResult, MinimumWageResult, WeeklyHolidayResult, AnnualLeaveResult,
DismissalResult, ComprehensiveResult, ProratedResult, PublicHolidayResult,
InsuranceResult, EmployerInsuranceResult, SeveranceResult, UnemploymentResult,
CompensatoryLeaveResult, WageArrearsResult, ParentalLeaveResult,
MaternityLeaveResult, FlexibleWorkResult, BusinessSizeResult

**상속하지 않는 클래스**:
- `OrdinaryWageResult` — `formula: str` 단수형 사용, 별도 구조
- `WeeklyHoursComplianceResult` — formulas 필드 없음
- `WageResult` (result.py) — 최종 통합 결과, 다른 구조

### 1.2 `wage_calculator/utils.py`

```python
from datetime import date


def parse_date(s: str) -> date:
    """YYYY-MM-DD 또는 YYYY.MM.DD 문자열 → date 변환"""
    parts = s.strip().replace(".", "-").split("-")
    return date(int(parts[0]), int(parts[1]), int(parts[2]))


# 주 → 월 환산 상수 (365 / 7 / 12 ≈ 4.345)
WEEKS_PER_MONTH = 365 / 7 / 12
```

**마이그레이션 대상**:

| 파일 | 현재 | 변경 |
|------|------|------|
| calculators/annual_leave.py:187 | `_parse_date()` 로컬 정의 | `from ..utils import parse_date` → 로컬 함수 삭제 |
| calculators/severance.py:254 | `_parse_date()` 로컬 정의 | `from ..utils import parse_date` → 로컬 함수 삭제 |
| calculators/prorated.py:98 | `_parse_date()` 로컬 정의 | `from ..utils import parse_date` → 로컬 함수 삭제 |
| calculators/business_size.py:185 | `_parse_date()` 로컬 정의 | `from ..utils import parse_date` → 로컬 함수 삭제 |

---

## 2. facade.py 디스패처 패턴 설계

### 2.1 CalcEntry 정의

```python
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class _CalcEntry:
    """계산기 레지스트리 항목"""
    func: Callable              # calc 함수
    section_name: str           # breakdown 섹션명
    summary_fn: Callable        # result_obj → summary dict 추출
    monthly_amount_fn: Optional[Callable] = None  # result_obj → monthly_total 가산액
    precondition: Optional[Callable] = None       # inp → bool (추가 실행 조건)
    needs_ow: bool = True       # True면 func(inp, ow), False면 특수 호출
```

### 2.2 CALCULATOR_REGISTRY

```python
CALCULATOR_REGISTRY: dict[str, _CalcEntry] = {
    "overtime": _CalcEntry(
        func=calc_overtime,
        section_name="연장·야간·휴일수당",
        summary_fn=lambda r: {"연장/야간/휴일수당(월)": f"{r.monthly_overtime_pay:,.0f}원"},
        monthly_amount_fn=lambda r: r.monthly_overtime_pay,
    ),
    "minimum_wage": _CalcEntry(
        func=calc_minimum_wage,
        section_name="최저임금 검증",
        summary_fn=_minimum_wage_summary,  # 별도 함수 (조건부 키 포함)
    ),
    "weekly_holiday": _CalcEntry(
        func=calc_weekly_holiday,
        section_name="주휴수당",
        summary_fn=lambda r: {"주휴수당(월)": f"{r.monthly_holiday_pay:,.0f}원"},
        monthly_amount_fn=lambda r: r.monthly_holiday_pay,
    ),
    # ... 나머지 14개 동일 패턴
}
```

### 2.3 _run_calculators() 공통 실행 루프

```python
def _run_calculators(
    targets: list[str],
    inp: WageInput,
    ow: OrdinaryWageResult,
    result: WageResult,
    monthly_total: float,
    all_warnings: list,
    all_legal: list,
) -> float:
    """레지스트리 기반 계산기 실행 루프"""
    for key in targets:
        entry = CALCULATOR_REGISTRY.get(key)
        if entry is None:
            continue
        # 사전 조건 확인
        if entry.precondition and not entry.precondition(inp):
            continue
        # 계산 실행
        calc_result = entry.func(inp, ow) if entry.needs_ow else None
        # summary 병합
        result.summary.update(entry.summary_fn(calc_result))
        # 공통 결과 병합
        result.breakdown[entry.section_name] = calc_result.breakdown
        result.formulas.extend(calc_result.formulas)
        all_warnings.extend(calc_result.warnings)
        all_legal.extend(calc_result.legal_basis)
        # monthly_total 가산
        if entry.monthly_amount_fn:
            monthly_total += entry.monthly_amount_fn(calc_result)
    return monthly_total
```

### 2.4 특수 계산기 처리 (디스패처 제외)

아래 5개는 호출 패턴이 달라서 CALCULATOR_REGISTRY에 넣지 않고 별도 처리:

| 계산기 | 이유 |
|--------|------|
| `business_size` | `calc_business_size(inp.business_size_input)` — 독립 입력 + `inp.business_size` 변경 부수효과 |
| `wage_arrears` | `calc_wage_arrears(amount, date, ...)` — 스칼라 인자, inp/ow 불필요 |
| `weekly_hours_check` | `check_weekly_hours_compliance(inp)` — ow 불필요 + formulas 없음 |
| `legal_hints` | `generate_legal_hints(inp, ow, result.minimum_wage_ok)` — 3번째 인자가 result 의존 |
| `insurance` (result 특수) | `result.monthly_net = ins.monthly_net` — WageResult 필드 직접 설정 |

→ 이 5개는 `calculate()` 내에서 기존처럼 개별 블록으로 유지 (단, 공통 부분은 헬퍼 호출)

### 2.5 리팩토링 후 calculate() 구조

```python
def calculate(self, inp, targets=None):
    if targets is None:
        targets = self._auto_detect_targets(inp)
    ow = calc_ordinary_wage(inp)
    result = WageResult(ordinary_hourly=ow.hourly_ordinary_wage)
    # ... 통상임금 breakdown 설정 (기존과 동일, 5줄)

    monthly_total = ow.monthly_ordinary_wage
    all_warnings, all_legal = [], ["근로기준법 (통상임금)"]

    # 1. business_size (최우선, 별도 처리)
    _handle_business_size(targets, inp, result, all_warnings, all_legal)

    # 2. 레지스트리 기반 표준 계산기 (13개)
    monthly_total = _run_calculators(
        targets, inp, ow, result, monthly_total, all_warnings, all_legal)

    # 3. insurance (result.monthly_net 직접 설정)
    _handle_insurance(targets, inp, ow, result, all_warnings, all_legal)

    # 4. wage_arrears (독립 함수)
    _handle_wage_arrears(targets, inp, result, all_warnings, all_legal)

    # 5. weekly_hours_check (ow 불필요)
    _handle_weekly_hours_check(targets, inp, result, all_warnings, all_legal)

    # 6. legal_hints (마지막)
    _handle_legal_hints(targets, inp, ow, result, all_warnings)

    result.monthly_total = round(monthly_total, 0)
    result.warnings = list(dict.fromkeys(all_warnings))
    result.legal_basis = list(dict.fromkeys(all_legal))
    return result
```

**예상 라인 수**: `calculate()` 본체 ~40줄 + `_run_calculators()` ~20줄 + 특수 핸들러 5개 × ~10줄 = ~110줄 (현재 243줄 → 55% 감소)

---

## 3. BaseCalculatorResult 상속 적용 상세

### 3.1 변경 패턴 (18개 계산기 공통)

**변경 전** (예: overtime.py):
```python
@dataclass
class OvertimeResult:
    overtime_pay: float
    night_pay: float
    holiday_pay: float
    monthly_overtime_pay: float
    breakdown: dict
    formulas: list
    warnings: list
    legal_basis: list
```

**변경 후**:
```python
from ..base import BaseCalculatorResult

@dataclass
class OvertimeResult(BaseCalculatorResult):
    overtime_pay: float = 0.0
    night_pay: float = 0.0
    holiday_pay: float = 0.0
    monthly_overtime_pay: float = 0.0
```

### 3.2 주의사항

- `dataclass` 상속 시 부모에 default 있는 필드 뒤에 자식의 non-default 필드를 둘 수 없음
- → **해결**: 자식 도메인 필드에도 default 값 추가 (`= 0.0`, `= ""`, `= False` 등)
- `UnemploymentResult`, `ParentalLeaveResult` 등은 이미 default 사용 중이므로 문제 없음

### 3.3 계산기별 도메인 필드 (삭제되지 않는 필드)

| 계산기 | 유지되는 도메인 필드 |
|--------|---------------------|
| OvertimeResult | overtime_pay, night_pay, holiday_pay, monthly_overtime_pay |
| MinimumWageResult | is_compliant, effective_hourly, legal_minimum, shortage_monthly, reference_year, monthly_hours_used |
| WeeklyHolidayResult | weekly_holiday_pay, monthly_holiday_pay, holiday_hours, is_eligible |
| AnnualLeaveResult | accrued_days, used_days, remaining_days, annual_leave_pay, service_years |
| DismissalResult | dismissal_pay, notice_days_required, notice_days_given, payable_days, is_exempt |
| ComprehensiveResult | base_wage, effective_hourly, included_allowances, is_minimum_wage_ok, legal_minimum, shortage |
| ProratedResult | prorated_wage, method, worked_days, total_days |
| PublicHolidayResult | holiday_pay_per_day, holiday_days, total_holiday_pay, eligible |
| InsuranceResult | monthly_gross, monthly_net, national_pension, health_insurance, long_term_care, employment_insurance, total_insurance, income_tax, local_income_tax, total_tax, total_deduction, is_freelancer |
| SeveranceResult | severance_pay, avg_daily_wage, avg_daily_3m, avg_daily_1y, avg_daily_ordinary, used_basis, service_days, service_years, is_eligible |
| UnemploymentResult | avg_daily_wage, base_daily_benefit, daily_benefit, upper_limit, lower_limit, benefit_days, total_benefit, early_reemployment_bonus, is_eligible, ineligible_reason |
| CompensatoryLeaveResult | compensatory_hours, overtime_comp_hours, night_comp_hours, holiday_comp_hours, holiday_ot_comp_hours, unused_leave_pay, monthly_unused_pay, original_overtime_pay |
| WageArrearsResult | arrear_amount, interest_rate, delay_days, interest_amount, total_claim, due_date, calc_date, statute_of_limitations_date, is_expired, is_post_retirement |
| ParentalLeaveResult | monthly_ordinary_wage, monthly_benefit_before_deferred, monthly_benefit_actual, monthly_deferred, total_months, total_benefit, total_deferred, has_bonus, bonus_months, monthly_bonus_benefit, reduced_work_monthly_benefit, upper_limit_applied, lower_limit_applied |
| MaternityLeaveResult | leave_days, monthly_benefit, raw_monthly_wage, is_priority_support, insurance_covered_days, employer_covered_days, total_insurance_benefit, total_employer_benefit, spouse_leave_days, spouse_leave_pay, upper_limit_applied |
| FlexibleWorkResult | unit_period, unit_weeks, total_actual_hours, legal_hours, overtime_hours, overtime_pay_per_period, monthly_overtime_pay, weeks_exceeding_limit, extra_premium_pay |
| BusinessSizeResult | regular_worker_count, business_size, calculation_period_start, calculation_period_end, operating_days, total_headcount, daily_counts, included_workers, excluded_workers, below_threshold_days, above_threshold_days, is_law_applicable |

---

## 4. WEEKS_PER_MONTH 상수 적용

### 4.1 constants.py 추가

```python
# 주 → 월 환산 (365일 / 7일 / 12개월 ≈ 4.345)
WEEKS_PER_MONTH = 365 / 7 / 12
```

### 4.2 적용 대상

각 파일에서 `52 / 12` 또는 `4.345` 사용 부분을 `WEEKS_PER_MONTH` 로 교체:

| 파일 | 현재 표현 | 변경 |
|------|----------|------|
| calculators/overtime.py | `weekly * 52 / 12` | `weekly * WEEKS_PER_MONTH` |
| calculators/weekly_holiday.py | `weekly * 52 / 12` | `weekly * WEEKS_PER_MONTH` |
| calculators/compensatory_leave.py | `weekly * 52 / 12` | `weekly * WEEKS_PER_MONTH` |

> 참고: `52 / 12 = 4.333...` vs `365 / 7 / 12 = 4.345...` — 미세한 차이.
> 기존 코드가 `52 / 12`를 사용한다면 값을 바꾸지 않고 상수명만 적용.
> → `WEEKS_PER_MONTH = 52 / 12` 로 기존 값 유지하여 계산 결과 변경 방지.

---

## 5. 파일 이동 설계

### 5.1 ordinary_wage.py 이동

```
wage_calculator/ordinary_wage.py
  → wage_calculator/calculators/ordinary_wage.py
```

**import 변경 대상**:

| 파일 | 현재 | 변경 |
|------|------|------|
| facade.py:9 | `from .ordinary_wage import calc_ordinary_wage` | `from .calculators.ordinary_wage import calc_ordinary_wage` |
| legal_hints.py | `from .ordinary_wage import ...` (사용 시) | `from .calculators.ordinary_wage import ...` |
| __init__.py | 필요 시 re-export | 기존 경로 유지 (하위 호환) |

### 5.2 shift_work.py 병합

```
wage_calculator/shift_work.py 내용
  → wage_calculator/calculators/ordinary_wage.py 하단에 병합
```

**shift_work.py 함수 4개**:
- `get_shift_monthly_hours()` → ordinary_wage.py에서 사용
- `calc_4_2_shift_hours()` → 유틸리티
- `calc_3_2_shift_hours()` → 유틸리티
- `describe_shift()` → 유틸리티

**이동 후**: shift_work.py 삭제, `__init__.py`에서 re-export 유지

### 5.3 하위 호환 보장

```python
# wage_calculator/__init__.py에 추가 (기존 import 경로 유지)
from .calculators.ordinary_wage import calc_ordinary_wage, OrdinaryWageResult
# shift_work 함수들도 calculators.ordinary_wage에서 re-export
```

---

## 6. 변경하지 않는 것 (명시적)

| 항목 | 이유 |
|------|------|
| `WageInput` 53필드 구조 | chatbot.py `from_analysis()` 연동 → 별도 PDCA |
| `OrdinaryWageResult` 구조 | `formula: str` 단수형, BaseCalculatorResult와 불일치 |
| `WageResult` (result.py) | 최종 통합 결과 구조, 계산기 Result와 별개 |
| 법적 근거 상수화 (FR-04) | Plan에서 선택 사항으로 지정, 본 PDCA에서는 제외 |
| `legal_hints.py` 로직 | 경고 중복은 인지하되 구조 변경은 별도 |
| 각 계산기의 계산 로직 | 순수 리팩토링 — 계산 결과 변경 없음 |

---

## 7. 구현 순서 (8단계)

| Step | 작업 | 파일 | 검증 |
|------|------|------|------|
| **1** | `base.py` 생성 — BaseCalculatorResult 정의 | 신규: `wage_calculator/base.py` | import 확인 |
| **2** | `utils.py` 생성 — parse_date, WEEKS_PER_MONTH | 신규: `wage_calculator/utils.py` | import 확인 |
| **3** | 18개 계산기 Result → BaseCalculatorResult 상속 적용 | `calculators/*.py` (18파일) | `python3 wage_calculator_cli.py` 36건 통과 |
| **4** | _parse_date() 4곳 → utils.parse_date() 교체 | annual_leave, severance, prorated, business_size | `python3 wage_calculator_cli.py` 36건 통과 |
| **5** | WEEKS_PER_MONTH 상수 적용 (constants.py + 계산기) | constants.py + overtime, weekly_holiday, compensatory_leave | `python3 wage_calculator_cli.py` 36건 통과 |
| **6** | facade.py 디스패처 패턴 적용 | facade.py | `python3 wage_calculator_cli.py` 36건 통과 |
| **7** | ordinary_wage.py / shift_work.py 이동 + 병합 | calculators/ordinary_wage.py, facade.py, __init__.py | `python3 wage_calculator_cli.py` 36건 통과 |
| **8** | __init__.py, calculators/__init__.py 정리 + 최종 테스트 | __init__.py, calculators/__init__.py | 36건 통과 + `wc -l` 코드 감소 확인 |

**핵심 원칙**: 매 Step 완료 후 `python3 wage_calculator_cli.py` 실행하여 36건 전체 통과 확인. 실패 시 즉시 롤백.

---

## 8. 예상 결과

### 8.1 코드 라인 변화

| 항목 | 현재 | 예상 | 변화 |
|------|------|------|------|
| base.py | 0 | 12 | +12 |
| utils.py | 0 | 15 | +15 |
| facade.py | 496 | ~280 | -216 |
| 18개 계산기 (보일러플레이트) | 각 4줄 × 18 = 72 | 0 | -72 |
| _parse_date() × 4곳 | 각 3줄 × 4 = 12 | 0 | -12 |
| shift_work.py | 64 | 0 (병합) | -64 |
| ordinary_wage.py (이동) | 167 | 167+64 = 231 | 0 (이동만) |
| **합계** | 6,097 | ~5,748 | **~349줄 감소 (~5.7%)** |

> facade.py의 감소가 가장 큼 (216줄). 실제로는 summary_fn 람다 등이 추가되므로 순감소는 200줄 내외.

### 8.2 유지보수 개선 효과

| 시나리오 | Before | After |
|----------|--------|-------|
| 신규 계산기 추가 | 계산기 파일 + facade에 10줄 복붙 + __init__.py 2곳 | 계산기 파일 + REGISTRY 1줄 + __init__.py |
| parse_date 버그 수정 | 4곳 수정 | 1곳 수정 |
| Result에 공통 필드 추가 | 18곳 수정 | base.py 1곳 수정 |
| 법적 근거 문자열 변경 | N곳 검색·수정 | (본 PDCA 범위 외) |
