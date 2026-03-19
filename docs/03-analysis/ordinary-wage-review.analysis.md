# ordinary-wage-review Analysis Report

> **Analysis Type**: Gap Analysis (Design vs Implementation)
>
> **Project**: laborconsult (nodong.kr wage calculator)
> **Analyst**: Claude PDCA (gap-detector)
> **Date**: 2026-03-08
> **Design Doc**: [ordinary-wage-review.design.md](../02-design/features/ordinary-wage-review.design.md)

---

## 1. Analysis Overview

### 1.1 Analysis Purpose

Design document에 명시된 Gap 3건(최소보장 성과급 통상임금 산입, 1일 통상임금 출력, 법률 힌트 보강)의 구현 완전성을 검증한다.

### 1.2 Analysis Scope

- **Design Document**: `docs/02-design/features/ordinary-wage-review.design.md`
- **Implementation Files**:
  - `wage_calculator/models.py` (AllowanceCondition enum)
  - `wage_calculator/calculators/ordinary_wage.py` (core logic)
  - `wage_calculator/facade.py` (breakdown output)
  - `wage_calculator/legal_hints.py` (legal hints)
  - `wage_calculator/__init__.py` (re-exports)
  - `wage_calculator_cli.py` (test cases)
- **Analysis Date**: 2026-03-08

---

## 2. Overall Scores

| Category | Score | Status |
|----------|:-----:|:------:|
| Design Match | 97% | ✅ |
| Architecture Compliance | 100% | ✅ |
| Convention Compliance | 100% | ✅ |
| **Overall** | **97%** | ✅ |

---

## 3. Gap Analysis (Design vs Implementation)

### 3.1 AllowanceCondition Enum

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| GUARANTEED_PERFORMANCE 추가 | `models.py:33-46` 에 명시 | `models.py:47` 정확히 일치 | ✅ Match |
| Enum value | `"최소보장성과"` | `"최소보장성과"` | ✅ Match |
| 기존 enum 불변 | NONE/ATTENDANCE/EMPLOYMENT/PERFORMANCE 유지 | 모두 유지 (L43-46) | ✅ Match |

### 3.2 OrdinaryWageResult 필드

| Field | Design | Implementation | Status |
|-------|--------|----------------|--------|
| `daily_ordinary_wage` 추가 | 2번째 필드 (hourly 다음) | `ordinary_wage.py:21` -- 정확한 위치 | ✅ Match |
| 타입 | `float` | `float` | ✅ Match |
| 주석 | `# 1일 통상임금 (원/일)` | `# 1일 통상임금 (원/일)` | ✅ Match |
| 기존 필드 유지 | 6개 필드 불변 | 6개 필드 그대로 유지 | ✅ Match |

### 3.3 _resolve_is_ordinary() 로직

| Branch | Design | Implementation | Status |
|--------|--------|----------------|--------|
| `"성과조건"` (기존) | `explicit is True` -> False + 경고, 기본 -> False | `ordinary_wage.py:147-150` 일치 | ✅ Match |
| `"최소보장성과"` (신규) | `explicit is False` -> False, else -> True + 판례 참조 | `ordinary_wage.py:152-156` 일치 | ✅ Match |
| `"재직조건"/"근무일수"` (기존) | 기존 로직 유지 | `ordinary_wage.py:158-162` 불변 | ✅ Match |
| 기본(조건 없음) | 기존 로직 유지 | `ordinary_wage.py:164-165` 불변 | ✅ Match |

### 3.4 calc_ordinary_wage() guaranteed_amount 처리

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| 조건 체크 | `condition == "최소보장성과" and is_ordinary` | `ordinary_wage.py:95` 일치 | ✅ Match |
| guaranteed 추출 | `a.get("guaranteed_amount", amount)` | `ordinary_wage.py:96` 일치 | ✅ Match |
| 클램핑(음수 방지) | `max(0, guaranteed_amount)` | `min(max(0, guaranteed), amount)` | ✅ Enhanced |
| 클램핑(초과 방지) | `min(guaranteed_amount, amount)` | 상동 -- 단일 표현으로 통합 | ✅ Enhanced |
| daily_ordinary_wage 산출 | `hourly * daily_work_hours` | `ordinary_wage.py:121-122` 일치 | ✅ Match |
| 반올림 | `round(daily_ordinary, 0)` | `ordinary_wage.py:126` 일치 | ✅ Match |

**Positive**: Design의 에러 처리 Section 5.1에 명시된 `max(0, guaranteed_amount)` + `min(guaranteed_amount, amount)` 두 조건을 `min(max(0, guaranteed), amount)`로 단일 표현 통합. 기능 동일, 코드 간결.

### 3.5 facade.py breakdown 반영

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| `"1일 통상임금"` 키 추가 | `f"{ow.daily_ordinary_wage:,.0f}원"` | `facade.py:302` 정확히 일치 | ✅ Match |
| 기존 키 유지 | 통상시급, 월 통상임금, 기준시간 | `facade.py:301,303-304` 불변 | ✅ Match |

### 3.6 legal_hints.py 힌트 추가

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| 조건 | `condition == "성과조건" and "guaranteed_amount" in a` | `legal_hints.py:78` 일치 | ✅ Match |
| category | `"통상임금"` | `legal_hints.py:81` 일치 | ✅ Match |
| hint 내용 | 최소보장성과 전환 안내 + 대법원 판례 참조 | `legal_hints.py:83-90` 일치 | ✅ Match |
| basis | `ORDINARY_WAGE_2024_RULING` | `legal_hints.py:89` 일치 | ✅ Match |
| priority | `1` (중요) | `legal_hints.py:90` 일치 | ✅ Match |

### 3.7 __init__.py Re-export

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| AllowanceCondition export | 기존 포함 확인만 필요 | `__init__.py:31,48` 이미 포함 | ✅ Match |

### 3.8 Test Cases

| Design ID | Impl ID | Description | Input Match | Expected Match | Status |
|:---------:|:-------:|-------------|:-----------:|:--------------:|--------|
| #33 | #57 | 최소보장 성과급 통상임금 산입 | ✅ | ✅ | ✅ Match |
| #34 | #58 | 1일 통상임금 출력 검증 | ✅ | ✅ | ✅ Match |
| #35 | #59 | 일반 성과조건 제외 유지 | ✅ | ✅ | ✅ Match |

---

## 4. Differences Found

### 4.1 Missing Features (Design O, Implementation X)

**None found.** All 3 design gaps are fully implemented.

### 4.2 Added Features (Design X, Implementation O)

**None found.** Implementation follows minimum-change principle.

### 4.3 Changed Features (Design != Implementation)

| Item | Design | Implementation | Impact |
|------|--------|----------------|:------:|
| Test case IDs | #33, #34, #35 | #57, #58, #59 | None |
| Clamping expression | Two separate calls: `max(0, g)` then `min(g, amount)` | Single: `min(max(0, guaranteed), amount)` | None |

#### Test ID Shift Detail

Design document에서 테스트 번호 #33~#35를 지정했으나, 구현 시점에서 기존 테스트가 #56까지 확장되어 있어 #57~#59로 배정됨.
- #33~#36: business_size (상시근로자 수 산정)
- #37~#43: EITC (근로장려금)
- #44~#51: retirement_tax/pension (퇴직소득세/연금)
- #52~#56: insurance (4대보험 세부 검증)
- **#57~#59: ordinary-wage-review (본 feature)**

이는 설계 문서 작성 시점과 구현 시점 사이에 다른 기능들의 테스트가 추가된 결과이며, 테스트 내용 자체는 설계와 100% 일치한다.

---

## 5. Convention Compliance

### 5.1 Naming Convention

| Category | Convention | Compliance | Violations |
|----------|-----------|:----------:|------------|
| Enum values | 한국어 문자열 | 100% | - |
| 변수명 | snake_case | 100% | - |
| 금액 포맷 | `{:,.0f}원` | 100% | - |
| Docstring | 한국어, 판례 번호 포함 | 100% | - |

### 5.2 Import Order

| File | Status | Notes |
|------|:------:|-------|
| `ordinary_wage.py` | ✅ | stdlib -> internal relative |
| `legal_hints.py` | ✅ | stdlib -> internal relative |
| `facade.py` | ✅ | internal relative only |

### 5.3 Convention Score

```
Convention Compliance: 100%
  Naming:          100%
  Import Order:    100%
  File Structure:  100%
  Code Style:      100%
```

---

## 6. Architecture Compliance

### 6.1 Dependency Direction

| Source | Target | Direction | Status |
|--------|--------|-----------|:------:|
| `ordinary_wage.py` | `models.py`, `constants.py`, `utils.py` | Calculator -> Models/Constants | ✅ |
| `facade.py` | `ordinary_wage.py` | Facade -> Calculator | ✅ |
| `legal_hints.py` | `models.py`, `ordinary_wage.py`, `constants.py` | Hints -> Models/Calculator/Constants | ✅ |
| `__init__.py` | all modules | Package -> Modules | ✅ |

### 6.2 Architecture Score

```
Architecture Compliance: 100%
  Dependency Direction:   100% (no violations)
  Layer Placement:        100% (all files in correct locations)
  Facade Pattern:         100% (single entry point maintained)
```

---

## 7. Backward Compatibility

| Interface | Change Type | Backward Compatible |
|-----------|------------|:-------------------:|
| `AllowanceCondition` enum | New member added | ✅ |
| `OrdinaryWageResult` dataclass | New field added (position 2) | ✅ (keyword-only construction) |
| `_resolve_is_ordinary()` | New branch added | ✅ (existing branches unchanged) |
| `fixed_allowances` dict | New optional key `guaranteed_amount` | ✅ (existing dicts work without it) |
| `facade.py` breakdown | New key `"1일 통상임금"` | ✅ (additive only) |
| Test cases #1~#56 | No changes | ✅ |

---

## 8. Match Rate Summary

```
+---------------------------------------------+
|  Overall Match Rate: 97%                     |
+---------------------------------------------+
|  Total Design Items:     22                  |
|  Exact Match:            20 items (91%)      |
|  Enhanced (better):       2 items  (9%)      |
|  Missing:                 0 items  (0%)      |
|  Changed (functional):    0 items  (0%)      |
+---------------------------------------------+
|  Score Deduction:                            |
|  - Test ID shift (#33-35 -> #57-59): -3%    |
|    (cosmetic, no functional impact)          |
+---------------------------------------------+
```

---

## 9. Recommended Actions

### 9.1 Documentation Update (Low Priority)

| Priority | Item | Description |
|----------|------|-------------|
| Low | Design doc test IDs | Section 6의 테스트 번호 #33~#35를 #57~#59로 업데이트 |
| Low | Design doc total tests | "기존 32개" 표현을 "기존 56개"로 업데이트 (Section 1.1, 6.1) |

### 9.2 No Code Changes Required

구현이 설계와 100% 기능적으로 일치하며, 클램핑 로직은 설계보다 더 간결하게 구현됨. 추가 코드 수정 불필요.

---

## 10. Intentional Deviations

| # | Deviation | Reason | Impact |
|---|-----------|--------|:------:|
| 1 | Test IDs #57-#59 (not #33-#35) | 다른 feature들의 테스트가 #33-#56 사이에 추가됨 | None |
| 2 | Clamping 단일 표현 `min(max(0,g),amount)` | 코드 간결성 향상, 기능 동일 | None |

---

## 11. Conclusion

**Match Rate: 97%** -- 설계와 구현이 매우 높은 수준으로 일치합니다.

- 3건의 설계 Gap(최소보장 성과급, 1일 통상임금, 법률 힌트)이 모두 정확하게 구현됨
- 에러 처리(음수 방지, 초과 클램핑)가 설계대로 적용됨
- 하위 호환성 완전 유지 (기존 56개 테스트 미변경)
- 테스트 ID 번호만 설계와 다르나, 테스트 내용/입력/기대값은 100% 일치

**Post-Analysis Action**: Match Rate >= 90% -- Check phase 완료 가능. `/pdca report ordinary-wage-review` 실행 권장.

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-03-08 | Initial gap analysis -- 97% match rate | Claude PDCA (gap-detector) |
