# eitc-calculator Analysis Report

> **Analysis Type**: Gap Analysis (PDCA Check Phase)
>
> **Project**: laborconsult (wage_calculator)
> **Analyst**: gap-detector
> **Date**: 2026-03-07
> **Design Doc**: [eitc-calculator.design.md](../02-design/features/eitc-calculator.design.md)
> **Plan Doc**: [eitc-calculator.plan.md](../01-plan/features/eitc-calculator.plan.md)

---

## 1. Analysis Overview

### 1.1 Analysis Purpose

Verify that the EITC (Earned Income Tax Credit / 근로장려금) calculator implementation matches the design specification across all 7 implementation files: constants, models, calculator module, facade integration, package exports, CLI test cases, and chatbot integration.

### 1.2 Analysis Scope

| Category | Design Document | Implementation Path |
|----------|-----------------|---------------------|
| Constants | design.md Section 2.1 | `wage_calculator/constants.py` |
| Data Model | design.md Section 2.2 | `wage_calculator/models.py` |
| Calculator | design.md Sections 2.3, 3.x | `wage_calculator/calculators/eitc.py` |
| Facade | design.md Sections 4.1-4.6 | `wage_calculator/facade.py` |
| Exports | design.md Section 7 (Step 5) | `wage_calculator/__init__.py` |
| Tests | design.md Section 8 | `wage_calculator_cli.py` |
| Chatbot | design.md Section 5 | `chatbot.py` |

---

## 2. Gap Analysis (Design vs Implementation)

### 2.1 Constants (`constants.py`)

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| `EITC_PARAMS` structure | `dict[int, dict[str, dict]]` | `dict[int, dict[str, dict]]` | Match |
| 2024 entries (single/single_earner/dual_earner) | Specified | Present, values match | Match |
| 2025 entries (single/single_earner/dual_earner) | Specified | Present, values match | Match |
| `get_eitc_params()` helper | Not explicitly designed | Implemented (fallback to latest year) | Added (positive) |
| `EITC_ASSET_UPPER` = 240,000,000 | Specified | 240,000,000 | Match |
| `EITC_ASSET_REDUCTION` = 170,000,000 | Specified | 170,000,000 | Match |
| `EITC_ASSET_REDUCTION_RATE` = 0.50 | Specified | 0.50 | Match |
| `CHILD_CREDIT_MAX_PER_CHILD` | `dict[int, int]` {2024: 1M, 2025: 1M} | Same | Match |
| `CHILD_CREDIT_INCOME_LIMIT` = 40,000,000 | Specified | 40,000,000 | Match |
| `SPOUSE_INCOME_THRESHOLD` = 3,000,000 | Specified | 3,000,000 | Match |

**Constants Score: 100%** (10/10 match + 1 positive addition)

### 2.2 Data Model (`models.py`)

| Field | Design Type | Design Default | Impl Type | Impl Default | Status |
|-------|-------------|----------------|-----------|--------------|--------|
| `household_type` | `str` | `""` | `str` | `""` | Match |
| `annual_total_income` | `float` | `0.0` | `float` | `0.0` | Match |
| `spouse_income` | `float` | `0.0` | `float` | `0.0` | Match |
| `total_assets` | `float` | `0.0` | `float` | `0.0` | Match |
| `num_children_under_18` | `int` | `0` | `int` | `0` | Match |
| `has_elderly_parent` | `bool` | `False` | `bool` | `False` | Match |
| Placement | Before 임금체불 block | After 출산전후휴가, before 임금체불 (line 189) | Match |

**Data Model Score: 100%** (6/6 fields match, placement matches)

### 2.3 EitcResult (`eitc.py`)

| Field | Design | Implementation | Status |
|-------|--------|----------------|--------|
| Inherits `BaseCalculatorResult` | Yes | Yes | Match |
| `household_type: str` | Specified | Present | Match |
| `annual_income: float` | Specified | Present | Match |
| `total_assets: float` | Specified | Present | Match |
| `is_eligible: bool` | Specified | Present | Match |
| `ineligible_reason: str` | Specified | Present | Match |
| `income_zone: str` | Specified | Present | Match |
| `eitc_raw: float` | Specified | Present | Match |
| `asset_reduction: bool` | Specified | Present | Match |
| `eitc_final: float` | Specified | Present | Match |
| `child_credit_per_child: float` | Specified | Present | Match |
| `child_credit_total: float` | Specified | Present | Match |
| `num_children: int` | Specified | Present | Match |
| `total_credit: float` | Specified | Present | Match |

**EitcResult Score: 100%** (14/14 fields match)

### 2.4 Algorithm (`eitc.py` calc_eitc)

| Step | Design | Implementation | Status |
|------|--------|----------------|--------|
| 1. Household type determination | Direct input or `_determine_household_type()` | Same logic | Match |
| 2. Annual income determination | `annual_total_income` > 0 or `monthly_wage * 12` or `annual_wage` | Matches + adds `annual_wage` fallback | Match (enhanced) |
| 3. EITC params lookup | `EITC_PARAMS[year]` with fallback | `get_eitc_params(year)` | Match |
| 4. Income eligibility check | `income >= phase_out_end` -> ineligible | Same | Match |
| 5. Asset eligibility check | `assets >= EITC_ASSET_UPPER` -> ineligible | Same | Match |
| 6a. Increasing zone | `income * (max / inc_end)` | `income * max_amt / inc_end` | Match |
| 6b. Flat zone | `max` | `float(max_amt)` | Match |
| 6c. Decreasing zone | `max - (income - flat_end) * max / (phase_out_end - flat_end)` | Same formula, `max(0.0, amount)` | Match |
| 7. Asset reduction | `> EITC_ASSET_REDUCTION` -> `* (1 - RATE)` | Same with `round()` | Match |
| 8. Child credit calc | `num_children * MAX_PER_CHILD * reduction` | Same logic | Match |
| 8a. Child credit single household exclusion | "단독가구 제외" | `household != "단독"` check | Match |
| 8b. Child credit income limit | `CHILD_CREDIT_INCOME_LIMIT` check | `income < CHILD_CREDIT_INCOME_LIMIT` | Match |
| 9. Total = eitc_final + child_total | Specified | Same | Match |
| `eitc_raw` rounding | Not specified | `round(eitc_raw)` applied | Added (reasonable) |

**Algorithm Score: 100%** (14/14 steps match)

### 2.5 Helper Functions (`eitc.py`)

| Function | Design | Implementation | Status |
|----------|--------|----------------|--------|
| `_determine_household_type(inp)` | 3 conditions: has_spouse, has_children, has_elderly | Same logic, same order | Match |
| `_calc_eitc_amount(income, p)` | Returns `(amount, zone_name)` | Returns `(float, str)` | Match |
| `_zone_range_str(zone, p)` | Not explicitly designed | Implemented for formula display | Added (positive) |
| `_ineligible(reason, ...)` | Not explicitly designed | Implemented for DRY ineligible results | Added (positive) |
| `_HOUSEHOLD_KEY` mapping | Specified ("단독"->"single", etc.) | Same | Match |
| `_HOUSEHOLD_LABEL` mapping | Not explicitly designed | Added for display names | Added (positive) |

**Helper Functions Score: 100%** (3/3 designed match + 3 positive additions)

### 2.6 Facade Integration (`facade.py`)

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| Import `calc_eitc` | Required | `from .calculators.eitc import calc_eitc` (line 27) | Match |
| `CALC_TYPES["eitc"]` | `"근로장려금(EITC) 수급 판정 + 금액"` | Same string (line 53) | Match |
| `CALC_TYPE_MAP["근로장려금"]` | `["eitc"]` | `["eitc"]` (line 73) | Match |
| `CALC_TYPE_MAP["근로장려세제"]` | `["eitc"]` | `["eitc"]` (line 74) | Match |
| `CALC_TYPE_MAP["EITC"]` | `["eitc"]` | `["eitc"]` (line 75) | Match |
| `_pop_eitc` function | Specified | Implemented (lines 207-218) | Match |
| `_pop_eitc` eligible summary keys | 근로장려금/자녀장려금/합계/소득구간/재산감액 | Same keys | Match |
| `_pop_eitc` ineligible truncation | `[:40]` | `[:50]` | Minor diff |
| `_pop_eitc` return 0 | `return 0` (monthly_total 미반영) | `return 0` | Match |
| `_STANDARD_CALCS` entry | After flexible_work, `(eitc, calc_eitc, ..., _pop_eitc, None)` | Same position (line 246) | Match |
| `_auto_detect_targets` EITC condition | `annual_total_income > 0 or household_type` | Same (lines 412-413) | Match |
| `_provided_info_to_input` EITC extension | "가구유형", "연소득", "재산" key handling | NOT implemented | Missing |

**Facade Score: 92%** (11/12 match, 1 missing)

### 2.7 Package Exports (`__init__.py`)

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| `EitcResult` import | Required | `from .calculators.eitc import EitcResult` (line 37) | Match |
| `EitcResult` in `__all__` | Required | Present (line 53) | Match |

**Exports Score: 100%** (2/2 match)

### 2.8 Test Cases (`wage_calculator_cli.py`)

| Design # | Design Name | Impl # | Impl Name | Input Match | Expected | Status |
|----------|-------------|--------|-----------|-------------|----------|--------|
| 33 | 단독_점증 (소득300만, 재산1억) | 37 | EITC 단독 점증 (소득300만, 재산1억) | Match | eitc=1,237,500 zone="점증" | ID shifted |
| 34 | 단독_평탄 (소득600만, 재산1억) | 38 | EITC 단독 평탄 (소득600만, 재산1억) | Match | eitc=1,650,000 zone="평탄" | ID shifted |
| 35 | 단독_소득초과 (소득2,300만) | 39 | EITC 단독 소득초과 (소득2,300만) | Match | ineligible="소득 초과" | ID shifted |
| 36 | 홑벌이_재산감액 (소득1,000만, 재산2억) | 40 | EITC 홑벌이 재산감액 (소득1,000만, 재산2억) | Match | eitc_raw=2,850,000 final=1,425,000 | ID shifted |
| 37 | 맞벌이_점감 (소득2,500만, 재산1.5억) | 41 | EITC 맞벌이 점감 (소득2,500만, 재산1.5억) | Match | zone="점감" | ID shifted |
| 38 | 재산초과 (소득500만, 재산2.5억) | 42 | EITC 재산초과 (소득500만, 재산2.5억) | Match | ineligible="재산 초과" | ID shifted |
| 39 | 자녀장려금 (소득1,200만, 자녀2명) | 43 | EITC 자녀장려금 (소득1,200만, 자녀2명) | Match | eitc+child=4,850,000 | ID shifted |

**Test ID Shift Explanation**: Design specified #33-#39 but business_size test cases (#33-#36) were added before EITC, pushing EITC to #37-#43. All 7 scenarios are present and correct; only IDs differ. This is intentional due to the pre-existing business_size calculator test cases occupying #33-#36.

**Test Cases Score: 100%** (7/7 scenarios match, ID numbering shift is intentional)

### 2.9 Chatbot Integration (`chatbot.py`)

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| Tool schema: `household_type` param | Specified | Present (lines 114-117) | Match |
| Tool schema: `annual_total_income` param | Specified | Present (lines 118-120) | Match |
| Tool schema: `total_assets` param | Specified | Present (lines 121-124) | Match |
| Tool schema: `num_children_under_18` param | Specified | Present (lines 125-128) | Match |
| `calculation_type` includes "근로장려금" | Specified | Present in tool description (line 112) | Match |
| `extract_calc_params` prompt: EITC keyword recognition | Specified | Prompt includes EITC instruction (lines 197-198) | Match |
| `run_calculator` EITC path | Specified | Dedicated EITC branch (lines 217-233) | Match |
| EITC path: WageInput construction | household_type, annual_total_income, total_assets, num_children | All 4 fields + monthly_wage + reference_year | Match (enhanced) |
| EITC path: calls `WageCalculator.calculate(inp, ["eitc"])` | Specified | Same (line 230) | Match |

**Chatbot Score: 100%** (9/9 items match)

### 2.10 Output Format (`eitc.py`)

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| `formulas` format: "가구유형: {label}" | Specified | Present | Match |
| `formulas` format: "연간 총소득: {income}원" | Specified | Present | Match |
| `formulas` format: zone with range | Specified | `_zone_range_str()` provides range | Match |
| `formulas` format: reduction info | Specified | Present with asset reduction details | Match |
| `formulas` format: child credit | Specified | Present when applicable | Match |
| `formulas` format: total line | Specified | Present | Match |
| `breakdown` dict keys | 10 keys specified | All 10 present with same structure | Match |
| Warnings: 연소득 미입력 | Specified | Present | Match |
| Warnings: 재산 미입력 | Specified | Present | Match |
| Warnings: 재산 감액 | Specified | Present | Match |
| Warnings: 단독+자녀 | Specified | Present | Match |
| Warnings: 가구유형 자동 판정 | Specified | Present | Match |
| Warnings: 추정치 안내 | Specified | Present (with 홈택스 URL added) | Match (enhanced) |
| Warnings: 신청 기한 | Specified | Present | Match |
| Warnings: 소득 초과 경계 | Specified | NOT implemented | Missing |
| `legal_basis` entries | 3 entries (조세특례제한법 100조의3, 5, 27) | Same 3 entries (27 added conditionally) | Match |

**Output Format Score: 94%** (15/16 items match, 1 warning missing)

### 2.11 Error Handling (Design Section 9)

| Scenario | Design Behavior | Implementation | Status |
|----------|----------------|----------------|--------|
| household_type 미입력 + 판정 정보 부족 | "단독" 기본 + 경고 | `_determine_household_type` returns "단독" when no info + warning | Match |
| annual_total_income=0 + monthly_wage=0 | ineligible + "소득 정보 없음" | Returns `_ineligible(...)` with "소득 정보 없음" message | Match |
| reference_year에 EITC_PARAMS 없음 | 가장 최근 연도 fallback + 경고 | `get_eitc_params()` fallback + warning when not 2024/2025 | Match |
| total_assets=0 | 재산 요건 미검증 + 경고 | Warning "재산 정보 미입력" added when assets=0 | Match |
| 음수 소득 또는 재산 | 0으로 처리 + 경고 | `max(0.0, ...)` applied | Match (no explicit warning for negative) |

**Error Handling Score: 96%** (4.8/5 -- negative input silently clamps without explicit warning)

---

## 3. Differences Summary

### 3.1 Missing Features (Design O, Implementation X)

| # | Item | Design Location | Description | Impact |
|---|------|-----------------|-------------|--------|
| 1 | `_provided_info_to_input` EITC extension | design.md Section 4.6 | "가구유형", "연소득", "재산" key handling in `_provided_info_to_input()` not added | Low -- EITC is handled via chatbot's dedicated EITC path, not via `from_analysis()` |
| 2 | "소득 초과 경계" warning | design.md Section 6.4 | Warning when income is close to phase_out_end (boundary warning) | Low -- nice-to-have UX enhancement |

### 3.2 Changed Features (Design != Implementation)

| # | Item | Design | Implementation | Impact |
|---|------|--------|----------------|--------|
| 1 | `_pop_eitc` ineligible truncation | `[:40]` | `[:50]` | Negligible -- slightly more reason text visible |
| 2 | Test case IDs | #33-#39 | #37-#43 | None -- business_size tests took #33-#36 first |
| 3 | Negative input handling | "0으로 처리 + 경고" | `max(0.0, ...)` without explicit warning | Negligible -- silently clamps |

### 3.3 Added Features (Design X, Implementation O)

| # | Item | Implementation Location | Description |
|---|------|------------------------|-------------|
| 1 | `get_eitc_params()` helper | `constants.py:182-186` | Centralized EITC params lookup with fallback |
| 2 | `_zone_range_str()` helper | `eitc.py:287-293` | Clean zone range display formatting |
| 3 | `_ineligible()` helper | `eitc.py:296-322` | DRY ineligible result construction |
| 4 | `_HOUSEHOLD_LABEL` dict | `eitc.py:39-43` | Display-friendly household type names |
| 5 | `eitc_raw` rounding | `eitc.py:150` | `round(eitc_raw)` for clean integer display |
| 6 | `annual_wage` fallback | `eitc.py:116-117` | Uses annual_wage when monthly_wage unavailable |
| 7 | 홈택스 URL in warnings | `eitc.py:211, 308` | Added `www.hometax.go.kr` reference |

All additions are improvements that enhance code quality, maintainability, or user experience.

---

## 4. Algorithm Verification (Manual Calculation)

### 4.1 Test Case #37 (단독, 점증구간)

```
Input: 단독, 소득 3,000,000원, 재산 100,000,000원
Design formula: 3,000,000 x (1,650,000 / 4,000,000) = 1,237,500원
Implementation: income * max_amt / inc_end = 3,000,000 * 1,650,000 / 4,000,000 = 1,237,500원
Result: MATCH
```

### 4.2 Test Case #41 (맞벌이, 점감구간)

```
Input: 맞벌이, 소득 25,000,000원, 재산 150,000,000원
Design formula: 3,300,000 - (25,000,000 - 17,000,000) x (3,300,000 / 21,000,000)
              = 3,300,000 - 8,000,000 x 0.15714... = 3,300,000 - 1,257,143 = 2,042,857원
Implementation: max_amt - (income - flat_end) * max_amt / phase_range
              = 3,300,000 - (25,000,000 - 17,000,000) * 3,300,000 / (38,000,000 - 17,000,000)
              = 3,300,000 - 8,000,000 * 3,300,000 / 21,000,000 = 2,042,857원
Result: MATCH
```

### 4.3 Test Case #40 (홑벌이, 재산감액)

```
Input: 홑벌이, 소득 10,000,000원, 재산 200,000,000원
Design: 평탄구간 -> 2,850,000원, 재산 2억 > 1.7억 -> 50% 감액
        eitc_final = 2,850,000 x 0.50 = 1,425,000원
Implementation: Same logic
Result: MATCH
```

### 4.4 Test Case #43 (자녀장려금)

```
Input: 홑벌이, 소득 12,000,000원, 재산 100,000,000원, 자녀 2명
Design: 평탄구간 eitc=2,850,000 + 자녀 2 x 1,000,000 = 4,850,000원
Implementation: eitc_final=2,850,000 + child_total=2 x 1,000,000 = 4,850,000원
Result: MATCH
```

---

## 5. Match Rate Summary

```
+---------------------------------------------+
|  Overall Match Rate: 97%                     |
+---------------------------------------------+
|  Constants:          10/10 (100%)   Match    |
|  Data Model:          6/6  (100%)   Match    |
|  EitcResult:         14/14 (100%)   Match    |
|  Algorithm:          14/14 (100%)   Match    |
|  Helpers:             3/3  (100%)   Match    |
|  Facade:             11/12 ( 92%)   Match    |
|  Exports:             2/2  (100%)   Match    |
|  Tests:               7/7  (100%)   Match    |
|  Chatbot:             9/9  (100%)   Match    |
|  Output Format:      15/16 ( 94%)   Match    |
|  Error Handling:     4.8/5 ( 96%)   Match    |
+---------------------------------------------+
|  Total Items:  96.8/98 = 98.8% -> 97%       |
|  (Rounded conservatively for 2 missing + 3   |
|   minor changes)                              |
+---------------------------------------------+
```

---

## 6. Overall Scores

| Category | Score | Status |
|----------|:-----:|:------:|
| Design Match | 97% | Match >= 90% |
| Architecture Compliance | 100% | Follows existing Facade pattern exactly |
| Convention Compliance | 100% | Python naming, file structure, import order correct |
| Algorithm Correctness | 100% | All manual calculations verified |
| Test Coverage | 100% | All 7 design scenarios present |
| Chatbot Integration | 100% | Dedicated EITC path fully implemented |
| **Overall** | **97%** | Match >= 90% |

---

## 7. Recommended Actions

### 7.1 Optional Improvements (non-blocking)

| Priority | Item | File | Description |
|----------|------|------|-------------|
| Low | Add `_provided_info_to_input` EITC keys | `facade.py:433-486` | Add "가구유형", "연소득", "재산" key handling for `from_analysis()` path |
| Low | Add boundary income warning | `eitc.py` (after zone calculation) | Warn when income is within 10% of `phase_out_end` |
| Negligible | Align truncation length | `facade.py:217` | Change `[:50]` to `[:40]` to match design, or update design to `[:50]` |

### 7.2 Design Document Updates Needed

| Item | Recommendation |
|------|---------------|
| Test case IDs | Update design Section 8 from #33-#39 to #37-#43 (business_size took #33-#36) |
| `_pop_eitc` truncation | Update design Section 4.3 from `[:40]` to `[:50]` to match implementation |
| `get_eitc_params()` helper | Document this addition in design Section 2.1 |
| `annual_wage` fallback | Document in design Section 3.1 Step 2 (income determination) |

---

## 8. Intentional Deviations

| # | Item | Reason | Classification |
|---|------|--------|----------------|
| 1 | Test IDs #37-#43 instead of #33-#39 | business_size calculator tests were added first (#33-#36), pushing EITC IDs forward | Intentional |
| 2 | `_provided_info_to_input` EITC not extended | EITC handled via dedicated chatbot EITC path, not via `from_analysis()` -- design acknowledged this in Section 4.6 ("최소한으로 확장") | Intentional (deferred) |
| 3 | `get_eitc_params()` added | Follows existing `get_insurance_rates()` pattern for year fallback | Positive enhancement |
| 4 | Boundary income warning omitted | Not critical for MVP; can be added in future iteration | Acceptable deferral |

---

## 9. Conclusion

The EITC calculator implementation achieves a **97% match rate** with the design specification. All core requirements are satisfied:

- All 6 WageInput fields added correctly
- All 14 EitcResult fields match design
- The 3-zone (점증/평탄/점감) formula is mathematically verified
- Facade integration is complete (CALC_TYPES, CALC_TYPE_MAP, _pop_eitc, _STANDARD_CALCS, _auto_detect)
- All 7 test scenarios present with correct expected values
- Chatbot integration includes dedicated EITC parameter extraction and execution path
- Output format (breakdown, formulas, warnings, legal_basis) matches design specification

The 2 missing items (`_provided_info_to_input` EITC extension and boundary income warning) are both low-impact and non-blocking. The match rate exceeds the 90% threshold for PDCA completion.

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-03-07 | Initial gap analysis | gap-detector |
