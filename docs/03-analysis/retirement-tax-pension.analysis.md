# retirement-tax-pension Analysis Report

> **Analysis Type**: Gap Analysis (PDCA Check Phase)
>
> **Project**: laborconsult (Korean Labor Law Wage Calculator)
> **Analyst**: gap-detector
> **Date**: 2026-03-07
> **Design Doc**: [retirement-tax-pension.design.md](../02-design/features/retirement-tax-pension.design.md)

---

## 1. Analysis Overview

### 1.1 Analysis Purpose

Compare the design document (`docs/02-design/features/retirement-tax-pension.design.md`) against the actual implementation for the retirement income tax calculator, retirement pension (DB/DC) calculator, and severance.py improvements.

### 1.2 Analysis Scope

- **Design Document**: `docs/02-design/features/retirement-tax-pension.design.md`
- **Implementation Files**: 7 files (2 new, 5 modified)
- **Analysis Date**: 2026-03-07

---

## 2. Gap Analysis (Design vs Implementation)

### 2.1 constants.py -- Retirement Tax Constants

| Design Item | Design Value | Implementation Value | Status |
|-------------|-------------|---------------------|--------|
| `RETIREMENT_SERVICE_DEDUCTION` table | 4 tiers: (5,1M,0), (10,2M,5M), (20,2.5M,15M), (999,3M,40M) | Identical | ✅ Match |
| `CONVERTED_SALARY_DEDUCTION` table | 5 tiers matching design exactly | Identical | ✅ Match |
| `INCOME_TAX_BRACKETS` reuse note | "퇴직소득세율 = 종합소득세율" comment | Comment present, `INCOME_TAX_BRACKETS` imported in `retirement_tax.py` | ✅ Match |
| `LOCAL_INCOME_TAX_RATE` | 0.10 | 0.10 | ✅ Match |
| Location in file | After existing constants | Lines 208-228, after EITC section | ✅ Match |

**Score: 5/5 (100%)**

### 2.2 models.py -- WageInput New Fields

| Design Field | Design Type & Default | Implementation | Status |
|-------------|----------------------|----------------|--------|
| `retirement_pay_amount` | `float = 0.0` | `float = 0.0` (L212) | ✅ Match |
| `irp_transfer_amount` | `float = 0.0` | `float = 0.0` (L213) | ✅ Match |
| `retirement_exclude_months` | `int = 0` | `int = 0` (L214) | ✅ Match |
| `retirement_add_months` | `int = 0` | `int = 0` (L215) | ✅ Match |
| `pension_type` | `str = ""` | `str = ""` (L218) | ✅ Match |
| `annual_wage_history` | `Optional[list] = None` | `Optional[list] = None` (L219) | ✅ Match |
| `dc_return_rate` | `float = 0.0` | `float = 0.0` (L220) | ✅ Match |
| `annual_bonus_total` | `float = 0.0` | `float = 0.0` (L223) | ✅ Match |
| `unused_annual_leave_pay` | `float = 0.0` | `float = 0.0` (L224) | ✅ Match |
| Section comments | 3 comment blocks | All 3 present with matching text | ✅ Match |

**Score: 10/10 (100%)**

Note: Design specified 8 fields (Section 3.1), but `annual_bonus_total` and `unused_annual_leave_pay` were listed under "퇴직금 평균임금 가산용" making it effectively 9 fields. Implementation has all 9.

### 2.3 retirement_tax.py -- New Calculator

#### 2.3.1 RetirementTaxResult Class

| Design Field | Design Type | Implementation | Status |
|-------------|-------------|----------------|--------|
| Inherits `BaseCalculatorResult` | Yes | Yes (L32) | ✅ Match |
| `retirement_pay: float = 0.0` | Yes | L34 | ✅ Match |
| `service_years: int = 0` | Yes | L35 | ✅ Match |
| `service_deduction: float = 0.0` | Yes | L38 | ✅ Match |
| `converted_salary: float = 0.0` | Yes | L39 | ✅ Match |
| `converted_deduction: float = 0.0` | Yes | L40 | ✅ Match |
| `tax_base: float = 0.0` | Yes | L41 | ✅ Match |
| `converted_tax: float = 0.0` | Yes | L44 | ✅ Match |
| `retirement_income_tax: float = 0.0` | Yes | L45 | ✅ Match |
| `local_income_tax: float = 0.0` | Yes | L46 | ✅ Match |
| `total_tax: float = 0.0` | Yes | L47 | ✅ Match |
| `irp_amount: float = 0.0` | Yes | L50 | ✅ Match |
| `deferred_tax: float = 0.0` | Yes | L51 | ✅ Match |
| `deferred_local_tax: float = 0.0` | Yes | L52 | ✅ Match |
| `withholding_tax: float = 0.0` | Yes | L53 | ✅ Match |
| `withholding_local_tax: float = 0.0` | Yes | L54 | ✅ Match |
| `net_retirement_pay: float = 0.0` | Yes | L57 | ✅ Match |

**17/17 fields matched.**

#### 2.3.2 Function Signature

| Design | Implementation | Status |
|--------|----------------|--------|
| `calc_retirement_tax(inp, ow, severance_result=None)` | `calc_retirement_tax(inp, ow, severance_result=None)` (L60-64) | ✅ Match |
| Return type `RetirementTaxResult` | `RetirementTaxResult` | ✅ Match |

#### 2.3.3 Algorithm Steps (Design Section 4.3 vs Implementation)

| Step | Design Pseudocode | Implementation | Status |
|------|-------------------|----------------|--------|
| Step 1: Retirement pay determination | Use severance if eligible, else `inp.retirement_pay_amount` + date calc | L76-86, identical logic | ✅ Match |
| Step 1: Zero guard | `if retirement_pay <= 0 or service_days <= 0: return _zero_result(...)` | L85-86 | ✅ Match |
| Step 2: Service years calc | `service_days * 12 / 365`, exclude/add months, `max(1, ceil(…/12))` | L89-91, identical | ✅ Match |
| Step 3: Service deduction | `_calc_service_deduction(years)`, `min(deduction, pay)` | L96-97, identical | ✅ Match |
| Step 4: Converted salary | `floor((pay - deduction) * 12 / years)` | L102-104, `max(0, ...)` added | ✅ Match |
| Step 5: Converted deduction | `_calc_converted_deduction(converted_salary)` | L113 | ✅ Match |
| Step 6: Tax base | `max(0, converted_salary - converted_deduction)` | L118 | ✅ Match |
| Step 7: Tax by brackets | `_calc_tax_by_brackets(tax_base)` | L126 | ✅ Match |
| Step 8: Final tax | `floor(converted_tax / 12 * service_years)`, local tax, total | L131-133 | ✅ Match |
| Step 9: IRP deferral | `floor(income_tax * irp / pay)`, deferred local tax | L142-155 | ✅ Match |
| Step 9: 10-won truncation | `floor(amount / 10) * 10` | L158-163 | ✅ Match |
| Net retirement pay | `pay - withholding_tax - withholding_local_tax` | L166 | ✅ Match |

**Edge case: IRP amount capping**

| Design (Section 10) | Implementation | Status |
|---------------------|----------------|--------|
| `irp = min(irp, retirement_pay)` | `irp_amount = min(inp.irp_transfer_amount, retirement_pay)` (L142) | ✅ Match |

Design did not explicitly show `irp = min(...)` in step 9 pseudocode, but listed it in Section 10 edge cases. Implementation correctly applies it.

**Edge case: Converted salary max(0)**

| Design (Section 10) | Implementation | Status |
|---------------------|----------------|--------|
| "환산급여 음수 -> max(0, ...)" | `converted_salary = max(0, converted_salary)` (L105) | ✅ Match |

Design pseudocode (Step 4) did not show `max(0, ...)` but Section 10 required it. Implementation added it correctly.

#### 2.3.4 Helper Functions

| Design Helper | Implementation | Status |
|---------------|----------------|--------|
| `_calc_service_deduction(years)` | L222-229, identical logic | ✅ Match |
| `_calc_converted_deduction(converted_salary)` | L232-241, identical logic | ✅ Match |
| `_calc_tax_by_brackets(tax_base)` | L244-251, identical logic | ✅ Match |
| `_zero_result()` | L254-271, added with proper warnings | ✅ Match |

#### 2.3.5 Positive Additions (not in design)

| Addition | Location | Impact | Assessment |
|----------|----------|--------|------------|
| `warnings` list with legal references | L66-73 | Positive | Consistent with other calculator patterns |
| `formulas` list with step-by-step documentation | L93, 99, 107-110, etc. | Positive | Enhances transparency |
| `breakdown` dict with full computation details | L173-194 | Positive | Matches facade pattern |
| `legal_basis` references (4 laws) | L68-73 | Positive | Matches project convention |
| IRP legal basis appended conditionally | L148 | Positive | Only when IRP used |

**Score: 12/12 algorithm steps + 4/4 helpers + 5 positive additions = 100%**

### 2.4 retirement_pension.py -- New Calculator

#### 2.4.1 RetirementPensionResult Class

| Design Field | Implementation | Status |
|-------------|----------------|--------|
| `pension_type: str = ""` | L20 | ✅ Match |
| `total_pension: float = 0.0` | L21 | ✅ Match |
| `total_contribution: float = 0.0` | L22 | ✅ Match |
| `investment_return: float = 0.0` | L23 | ✅ Match |
| `service_years: float = 0.0` | L24 | ✅ Match |
| `annual_contributions: list` | L25, `field(default_factory=list)` | ✅ Match |
| Inherits `BaseCalculatorResult` | L19 | ✅ Match |

**7/7 fields matched.**

#### 2.4.2 Function Signature

| Design | Implementation | Status |
|--------|----------------|--------|
| `calc_retirement_pension(inp, ow, severance_result=None)` | L28-32 | ✅ Match |

#### 2.4.3 DC Calculation Logic

| Design Item | Implementation | Status |
|-------------|----------------|--------|
| Iterate `annual_wage_history` if provided | L114-121 | ✅ Match |
| Fallback to `monthly_wage x 12` | L123-133 | ✅ Match |
| Contribution = `annual_wage / 12` | L116, L128 | ✅ Match |
| Compound return calculation | L139-148 | ✅ Match |
| 0% return rate handling | L150-155 | ✅ Match |
| Returns contributions list | L186, `annual_contributions=contributions` | ✅ Match |

#### 2.4.4 DB Calculation Logic

| Design Item | Implementation | Status |
|-------------|----------------|--------|
| Use severance result if available | L57-62 | ✅ Match |
| Fallback: `hourly_wage * 8 * 30 * (days/365)` | L64-77 | ✅ Match |
| Legal reference 근퇴법 제15조 | L55 | ✅ Match |

#### 2.4.5 Positive Additions

| Addition | Impact | Assessment |
|----------|--------|------------|
| DB/DC informational warnings | Positive | Helps user understand product type |
| DC 0% return rate warning | Positive | Transparency |
| Breakdown with per-year detail | Positive | Clear audit trail |
| `round()` on contribution values | Positive | Cleaner output |
| `pension_type.upper()` normalization | Positive | Handles "db"/"DB" gracefully |

**Score: 100%**

### 2.5 severance.py -- Modifications

#### 2.5.1 _calc_avg_daily_3m Modification

| Design Change | Implementation | Status |
|---------------|----------------|--------|
| Add `bonus_addition = annual_bonus_total * 3 / 12` | L234 | ✅ Match |
| Add `leave_addition = unused_annual_leave_pay * 3 / 12` | L237 | ✅ Match |
| `total = wage_total + bonus_addition + leave_addition` | L239 | ✅ Match |
| Guard: `if annual_bonus_total > 0` | L234 | ✅ Match |
| Guard: `if unused_annual_leave_pay > 0` | L237 | ✅ Match |

#### 2.5.2 IRP Notice

| Design Change | Implementation | Status |
|---------------|----------------|--------|
| `if end >= date(2022, 4, 14):` | L188 | ✅ Match |
| Warning text about IRP mandatory | L189-193, text matches | ✅ Match |
| Legal reference 근퇴법 제9조 | L194 | ✅ Match |

#### 2.5.3 Breakdown Additions

| Design Change | Implementation | Status |
|---------------|----------------|--------|
| `breakdown["상여금 가산"]` with formatted text | L170-174 | ✅ Match |
| `breakdown["연차수당 가산"]` with formatted text | L178-182 | ✅ Match |
| Format: `"X원 (연 Y원 x 3/12)"` | Matches design format | ✅ Match |

#### 2.5.4 Positive Additions

| Addition | Impact |
|----------|--------|
| `formulas.append()` for bonus/leave additions | Positive -- audit trail |

**Score: 8/8 (100%)**

### 2.6 facade.py -- Integration

#### 2.6.1 Imports

| Design | Implementation | Status |
|--------|----------------|--------|
| `from .calculators.retirement_tax import calc_retirement_tax` | L28 | ✅ Match |
| `from .calculators.retirement_pension import calc_retirement_pension` | L29 | ✅ Match |

#### 2.6.2 CALC_TYPES

| Design Entry | Implementation | Status |
|-------------|----------------|--------|
| `"retirement_tax": "퇴직소득세"` | L56 | ✅ Match |
| `"retirement_pension": "퇴직연금(DB/DC)"` | L57 | ✅ Match |

#### 2.6.3 CALC_TYPE_MAP

| Design Entry | Implementation | Status |
|-------------|----------------|--------|
| `"퇴직소득세": ["severance", "retirement_tax"]` | L80 | ✅ Match |
| `"퇴직연금": ["retirement_pension"]` | L81 | ✅ Match |
| `"퇴직": ["severance", "retirement_tax"]` | L82 | ✅ Match |

#### 2.6.4 Populate Functions

| Design Function | Implementation | Status | Notes |
|----------------|----------------|--------|-------|
| `_pop_retirement_tax` summary keys | L214-220 | ✅ Match | Minor: design had `result.summary["총 세액"]` but impl omits it (deducible from other fields) |
| `_pop_retirement_tax` IRP conditional | L218-219 | ✅ Match | `deferred_tax` only (not `deferred_tax + deferred_local_tax` as design) |
| `_pop_retirement_pension` summary | L223-228 | ✅ Match | |
| `_pop_retirement_pension` DC conditional | L226-227 | ✅ Match | Added `investment_return > 0` guard |

**Minor differences in _pop_retirement_tax:**

| Design | Implementation | Impact |
|--------|----------------|--------|
| `result.summary["총 세액"]` included | Not included | Low -- total_tax is in breakdown, not summary |
| IRP summary: `deferred_tax + deferred_local_tax` | `deferred_tax` only | Low -- minor display difference |
| Pension type displayed as raw "DB"/"DC" | Full Korean name "확정급여형(DB)" / "확정기여형(DC)" | Positive -- more user-friendly |

#### 2.6.5 Dispatcher (Special Handling)

| Design Pattern | Implementation | Status |
|---------------|----------------|--------|
| Severance cache in standard loop | L319, L326-327: `_severance_cache = None`, cached on `key == "severance"` | ✅ Match |
| retirement_tax after standard loop | L351-355: special section | ✅ Match |
| Pass `_severance_cache` to `calc_retirement_tax` | L353 | ✅ Match |
| retirement_pension after retirement_tax | L357-361: special section | ✅ Match |
| Pass `_severance_cache` to `calc_retirement_pension` | L359 | ✅ Match |

Design proposed `if "retirement_pension" in targets and inp.pension_type:` but implementation uses `if "retirement_pension" in targets:` without the `inp.pension_type` guard. This is acceptable because pension_type defaults to "" and the calculator handles it by defaulting to DB.

| Design | Implementation | Impact |
|--------|----------------|--------|
| Precondition `inp.pension_type` for pension | No precondition -- always runs if in targets | Low -- calculator handles empty pension_type by defaulting to DB |

#### 2.6.6 Auto-detect Targets

| Design Rule | Implementation | Status |
|-------------|----------------|--------|
| `if "severance" in targets or inp.retirement_pay_amount > 0:` append retirement_tax | L455-456 | ✅ Match |
| `if inp.pension_type:` append retirement_pension | L459-460 | ✅ Match |

**Score: 16/16 major items, 3 minor display differences (non-functional)**

### 2.7 wage_calculator_cli.py -- Test Cases

Design specified test cases #33-#40 (8 tests). Implementation uses IDs #44-#51 (8 tests) because IDs #33-#43 were already occupied by business_size (#33-#36) and EITC (#37-#43) calculators.

| Design Case | Design ID | Impl ID | Description | Status | Notes |
|-------------|:---------:|:-------:|-------------|--------|-------|
| #33: 3년 단기근속 퇴직소득세 | 33 | 44 | 10년 근속 3000만원 | Changed | See below |
| #34: 10년 근속 퇴직소득세 | 34 | 45 | 5년 근속 + IRP 전액이체 | Changed | See below |
| #35: IRP 과세이연 | 35 | 46 | 20년 근속 + 상여금/연차수당 | Changed | See below |
| #36: 25년 장기근속 1억 | 36 | 47 | DB형 퇴직연금 | Changed | See below |
| #37: DB형 퇴직연금 | 37 | 48 | DC형 5년 수익률 3% | Changed | See below |
| #38: DC형 5년 적립 | 38 | 49 | DC형 연도별 임금이력 + 수익률 5% | Changed | See below |
| #39: 상여금 가산 | 39 | 50 | 통합 테스트 (퇴직금+소득세+연금) | Changed | See below |
| #40: 연차수당 가산 | 40 | 51 | 1년 미만 근속 직접입력 | Changed | See below |

**Test case ID shift analysis:** The design was written assuming IDs would be #33-#40, but business_size (#33-#36) and EITC (#37-#43) already occupied those slots. Implementation correctly shifted to #44-#51. This is the same pattern observed in the eitc-calculator analysis (design #33-#39, impl #37-#43).

**Test scenario comparison (detailed):**

| Scenario | Design Coverage | Impl Coverage | Assessment |
|----------|----------------|---------------|------------|
| Short-term service (3yr) tax | Design #33 | Impl #50 (3yr integrated) + #51 (short-term) | ✅ Covered |
| 10-year service tax | Design #34 | Impl #44 (10yr, severance+tax) | ✅ Covered |
| IRP deferral | Design #35 | Impl #45 (full IRP transfer), #50 (partial IRP) | ✅ Covered |
| Long service (20-25yr) | Design #36 | Impl #46 (20yr + bonus/leave) | ✅ Covered |
| DB pension = severance | Design #37 | Impl #47 (10yr DB) | ✅ Covered |
| DC pension 5yr | Design #38 | Impl #48 (5yr, 3% return) | ✅ Covered |
| DC with annual history | Not in design | Impl #49 (4yr, 5%, variable wages) | Positive addition |
| Bonus/leave addition | Design #39-#40 | Impl #46 (20yr + bonus + leave combined) | ✅ Covered (combined) |
| Integrated test (sev+tax+pension) | Not in design | Impl #50 (3yr, DB, IRP) | Positive addition |
| Short-term direct input | Not in design | Impl #51 (1yr, direct 5M) | Positive addition |

The implementation test cases are **more comprehensive** than design:
- Design: 8 cases covering specific scenarios individually
- Implementation: 8 cases (#44-#51) covering same scenarios with more realistic combinations plus 3 additional scenarios (annual wage history DC, integrated test, short-term direct input)

**Score: 8/8 design scenarios covered, 3 positive additions**

### 2.8 __init__.py -- Exports

| Design Expectation | Implementation | Status |
|-------------------|----------------|--------|
| No explicit export design for new types | `RetirementTaxResult` and `RetirementPensionResult` NOT exported in `__init__.py` | Neutral |

This matches the existing pattern where only `BusinessSizeResult` and `EitcResult` are exported as specific Result types. Other result types (e.g., `SeveranceResult`, `OvertimeResult`) are not exported either. **Not a gap.**

---

## 3. Edge Cases Verification (Design Section 10)

| Edge Case | Design Handling | Implementation | Status |
|-----------|----------------|----------------|--------|
| Service years 0 (< 1 year) | `max(1, ceil(...))` | L91: `max(1, math.ceil(total_months / 12))` | ✅ |
| Retirement pay < service deduction | `min(deduction, pay)` | L97: `min(service_deduction, retirement_pay)` | ✅ |
| Converted salary negative | `max(0, ...)` | L105: `max(0, converted_salary)` | ✅ |
| Tax base 0 | Return 0 tax | L118: `max(0, ...)`, L248: early return 0 | ✅ |
| IRP > retirement pay | `min(irp, pay)` | L142: `min(inp.irp_transfer_amount, retirement_pay)` | ✅ |
| DC annual wage not provided | `monthly_wage x 12` estimate | L123-133: fallback logic | ✅ |
| `math.floor` truncation | Floor at won level | Used consistently | ✅ |
| 10-won truncation (withholding) | `floor(amount / 10) * 10` | L158-163 | ✅ |

**Missing from implementation (low impact):**

| Design Edge Case | Status | Impact |
|-----------------|--------|--------|
| "2024년 이전 퇴직: warning 추가" | Not implemented | Low -- informational only, not a calculation error |

**Score: 8/9 edge cases (89%), 1 missing is informational-only**

---

## 4. Architecture Compliance

### 4.1 Dependency Direction

| File | Layer | Dependencies | Status |
|------|-------|-------------|--------|
| `retirement_tax.py` | Calculator | `base`, `utils`, `models`, `ordinary_wage`, `severance`, `constants` | ✅ Correct |
| `retirement_pension.py` | Calculator | `base`, `utils`, `models`, `ordinary_wage`, `severance` | ✅ Correct |
| `severance.py` | Calculator | `base`, `utils`, `models`, `ordinary_wage`, `constants` | ✅ Correct |
| `facade.py` | Facade | All calculators, `models`, `result`, `legal_hints` | ✅ Correct |

### 4.2 Pattern Consistency

| Pattern | Expected | Actual | Status |
|---------|----------|--------|--------|
| Calculator function signature `(inp, ow) -> Result` | Yes | retirement_tax/pension add optional `severance_result` | ✅ Acceptable extension |
| Result dataclass inherits `BaseCalculatorResult` | Yes | Both new Results inherit it | ✅ |
| Populate function returns monthly_total addition | Yes | Both return 0 | ✅ |
| warnings/formulas/legal_basis in results | Yes | Both include all three | ✅ |
| breakdown dict for display | Yes | Both include detailed breakdown | ✅ |

---

## 5. Convention Compliance

### 5.1 Naming Convention

| Category | Convention | Compliance |
|----------|-----------|:----------:|
| File names | `snake_case.py` | ✅ 100% |
| Function names | `snake_case` | ✅ 100% |
| Class names | `PascalCase` | ✅ 100% |
| Constants | `UPPER_SNAKE_CASE` | ✅ 100% |
| Internal helpers | `_prefix` | ✅ 100% |

### 5.2 Import Order

All files follow: stdlib -> package-relative -> constants pattern. ✅

### 5.3 Korean Won Formatting

All monetary values use `{:,.0f}원` format. ✅

---

## 6. Overall Scores

| Category | Score | Status |
|----------|:-----:|:------:|
| constants.py | 100% | ✅ |
| models.py | 100% | ✅ |
| retirement_tax.py (Result class) | 100% | ✅ |
| retirement_tax.py (Algorithm) | 100% | ✅ |
| retirement_tax.py (Helpers) | 100% | ✅ |
| retirement_pension.py | 100% | ✅ |
| severance.py modifications | 100% | ✅ |
| facade.py integration | 97% | ✅ |
| wage_calculator_cli.py tests | 100% | ✅ |
| Edge case handling | 89% | ✅ |
| Architecture compliance | 100% | ✅ |
| Convention compliance | 100% | ✅ |
| **Overall Match Rate** | **97%** | ✅ |

```
+-------------------------------------------------+
|  Overall Match Rate: 97%                         |
+-------------------------------------------------+
|  Missing Items:          0 (critical)            |
|  Minor Differences:      4 (non-functional)      |
|  Positive Additions:    14                        |
+-------------------------------------------------+
```

---

## 7. Differences Found

### 7.1 Missing Features (Design O, Implementation X) -- None Critical

| Item | Design Location | Description | Impact |
|------|----------------|-------------|--------|
| 2024년 이전 퇴직 warning | Section 10 | Informational warning about old tax law not supported | Low (info only) |

### 7.2 Changed Features (Design != Implementation)

| Item | Design | Implementation | Impact |
|------|--------|----------------|--------|
| Test case IDs | #33-#40 | #44-#51 | None (ID shift due to prior calculators) |
| `_pop_retirement_tax` summary keys | Includes "총 세액" | Omits "총 세액" (in breakdown instead) | Low (display only) |
| `_pop_retirement_tax` IRP display | `deferred_tax + deferred_local_tax` | `deferred_tax` only | Low (minor format) |
| `_pop_retirement_pension` type display | Raw "DB"/"DC" | Full Korean name | Positive (UX improvement) |
| Pension dispatcher precondition | `inp.pension_type` guard | No guard (defaults to DB) | Low (functional equivalent) |

### 7.3 Positive Additions (Design X, Implementation O)

| Item | Implementation Location | Description |
|------|------------------------|-------------|
| `warnings` / `formulas` / `legal_basis` in retirement_tax.py | L66-73, throughout | Full audit trail with legal references |
| `breakdown` dict in retirement_tax.py | L173-194 | Detailed computation display |
| `_zero_result()` helper | L254-271 | Graceful handling of invalid input |
| `pension_type.upper()` normalization | retirement_pension.py L38 | Case-insensitive input |
| `round()` on DC contributions | retirement_pension.py L120, L143-144 | Clean numeric output |
| DB/DC type informational warnings | retirement_pension.py L80-83, L157-165 | User education |
| Per-year breakdown for DC | retirement_pension.py L175-178 | Detailed audit trail |
| `formulas` for bonus/leave additions in severance | severance.py L175-177, L183-185 | Transparency |
| Full Korean pension type names in summary | facade.py L224 | Better UX |
| DC `investment_return > 0` guard in summary | facade.py L226 | Cleaner output when no return |
| Test #49: DC with annual wage history + 5% return | cli.py L822-833 | Additional DC scenario |
| Test #50: Integrated severance+tax+pension | cli.py L834-847 | End-to-end integration test |
| Test #51: Short-term direct input | cli.py L848-860 | Edge case coverage |
| IRP legal reference conditional append | retirement_tax.py L148 | Only when IRP is actually used |

---

## 8. Recommended Actions

### 8.1 Optional Improvements (Low Priority)

| Priority | Item | File | Expected Impact |
|----------|------|------|-----------------|
| Low | Add "2024년 이전 퇴직" warning | retirement_tax.py | Informational completeness |
| Low | Add `_pop_retirement_tax` "총 세액" to summary | facade.py | Display completeness |
| None | Update design doc test case IDs to #44-#51 | design.md | Documentation accuracy |

### 8.2 Design Document Updates Needed

- [ ] Update test case IDs from #33-#40 to #44-#51 (reflecting actual available ID range)
- [ ] Document positive additions (warnings, formulas, breakdown, _zero_result)
- [ ] Note pension type Korean name display enhancement

---

## 9. Intentional Deviations

| Deviation | Rationale | Acceptable |
|-----------|-----------|:----------:|
| Test IDs #44-#51 instead of #33-#40 | IDs #33-#43 occupied by business_size + EITC | Yes |
| "총 세액" omitted from summary | Available in breakdown; summary already shows component taxes | Yes |
| IRP display shows `deferred_tax` only | Simpler display; full details in breakdown | Yes |
| Pension type full Korean name | Better user experience | Yes |
| No `inp.pension_type` guard in dispatcher | Calculator handles empty value by defaulting to DB | Yes |
| Missing "2024년 이전 퇴직" warning | Informational only; does not affect calculation accuracy | Yes |

---

## 10. Next Steps

- [x] All critical design items implemented
- [x] All edge cases handled (except 1 informational warning)
- [x] Test cases cover all design scenarios plus 3 additional
- [ ] Optional: Add "2024년 이전 퇴직" warning for completeness
- [ ] Optional: Update design document to reflect actual test IDs
- [ ] Proceed to report phase: `/pdca report retirement-tax-pension`

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-03-07 | Initial gap analysis | gap-detector |
