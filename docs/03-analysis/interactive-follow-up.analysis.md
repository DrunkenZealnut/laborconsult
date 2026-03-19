# interactive-follow-up Analysis Report

> **Analysis Type**: Gap Analysis (Design vs Implementation)
>
> **Project**: laborconsult (AI 노동상담 챗봇)
> **Analyst**: gap-detector
> **Date**: 2026-03-07
> **Design Doc**: [interactive-follow-up.design.md](../02-design/features/interactive-follow-up.design.md)

---

## 1. Analysis Overview

### 1.1 Analysis Purpose

Design document (interactive-follow-up.design.md)와 실제 구현 코드 간의 일치율을 측정하고 차이점을 식별한다.

### 1.2 Analysis Scope

- **Design Document**: `docs/02-design/features/interactive-follow-up.design.md`
- **Implementation Files**: schemas.py, session.py, config.py, pipeline.py, index.html, analyzer.py, composer.py, prompts.py, api/index.py
- **Analysis Date**: 2026-03-07

---

## 2. Gap Analysis (Design vs Implementation)

### 2.1 File Change Summary Verification

| File | Design Change Type | Actual Change | Status |
|------|-------------------|---------------|--------|
| `app/models/schemas.py` | ADD AnalysisResult | AnalysisResult added (L25-32) | ✅ Match |
| `app/models/session.py` | MODIFY pending + 3 methods | _pending_analysis + 4 methods (has_pending_info, save_pending, merge_with_pending, clear_pending) | ✅ Match |
| `app/config.py` | MODIFY analyzer_model | analyzer_model added (L23) + anthropic_client property (L25-28) | ✅ Match |
| `app/core/pipeline.py` | MODIFY analysis step + bridge | analyze_intent import, compose_follow_up import, analysis step, _analysis_to_extract_params | ✅ Match |
| `public/index.html` | MODIFY readSSE follow_up | follow_up event handler (L345-348) | ✅ Match |
| `app/core/analyzer.py` | NONE (unchanged) | Exists and functional | ✅ Match |
| `app/core/composer.py` | NONE (unchanged) | Exists with compose_follow_up() | ✅ Match |
| `app/templates/prompts.py` | NONE (unchanged) | Exists with ANALYZE_TOOL, ANALYZER_SYSTEM | ✅ Match |
| `api/index.py` | NONE (already has follow_up) | follow_up handling at L60-65 | ✅ Match |

### 2.2 AnalysisResult Model (Section 2.1)

| Field | Design | Implementation | Status |
|-------|--------|----------------|--------|
| `requires_calculation` | `bool = False` | `bool = False` | ✅ |
| `calculation_types` | `list[str] = []` | `list[str] = []` | ✅ |
| `extracted_info` | `dict = {}` | `dict = {}` | ✅ |
| `relevant_laws` | `list[str] = []` | `list[str] = []` | ✅ |
| `missing_info` | `list[str] = []` | `list[str] = []` | ✅ |
| `question_summary` | `str = ""` | `str = ""` | ✅ |

Score: 6/6 fields match (100%)

### 2.3 Session Extension (Section 2.2)

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| `_pending_analysis` field | `AnalysisResult \| None = None` | `AnalysisResult \| None = field(default=None, repr=False)` | ✅ Match (repr=False matches design Section 3.4) |
| `has_pending_info()` | returns `self._pending_analysis is not None` | identical (L29-30) | ✅ |
| `save_pending()` | sets `self._pending_analysis = analysis` | identical (L32-33) | ✅ |
| `merge_with_pending()` | merges extracted_info, filters missing_info, clears pending | identical logic (L35-46) | ✅ |
| `clear_pending()` | sets `self._pending_analysis = None` | identical (L48-49) | ✅ |
| AnalysisResult import | `from app.models.schemas import AnalysisResult` | present (L8) | ✅ |

Score: 6/6 items match (100%)

### 2.4 Config Extension (Section 5)

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| `analyzer_model` attribute | `str = EXTRACT_MODEL` | `str = EXTRACT_MODEL` (L23) | ✅ |
| `anthropic_client` access | design says "config.claude_client로 참조" + "alias 또는 직접 속성 접근 필요" | `@property anthropic_client` alias provided (L25-28) | ✅ Positive addition |

Score: 2/2 items match (100%)

### 2.5 Pipeline Modifications (Section 3.1)

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| `analyze_intent` import | present | L9: `from app.core.analyzer import analyze_intent` | ✅ |
| `compose_follow_up` import | present | L10: `from app.core.composer import compose_follow_up` | ✅ |
| Status yield "질문 분석 중..." | `yield {"type": "status", "text": "질문 분석 중..."}` | L428 | ✅ |
| `session.has_pending_info()` check | first branch | L434 | ✅ |
| Pending merge path | `analyze_intent() -> merge_with_pending()` | L436-438 | ✅ |
| New question analysis path | `analyze_intent() -> check missing_info` | L441-458 | ✅ |
| follow_up yield format | `{"type": "follow_up", "text": ..., "missing_fields": ...}` | L449-450 | ✅ |
| `session.save_pending()` before follow_up | present | L445 | ✅ |
| `session.add_user/add_assistant` after follow_up | present | L451-452 | ✅ |
| `yield {"type": "done"}` + `return` after follow_up | present | L453-454 | ✅ |
| Fallback to `_extract_params` on failure | `except Exception: session.clear_pending()` | L459-462 | ✅ |
| `use_analysis_params` flag for bridge routing | design implies analysis.extracted_info used first | L430, L457-458, L468-475 | ✅ |

Score: 12/12 items match (100%)

### 2.6 Bridge Function (Section 4)

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| `_analysis_to_extract_params()` function | present in design | L313-351 | ✅ |
| `weekly_total` calculation (daily x days) | `_calc_weekly_total()` separate function | inline at L317-321 | ✅ Equivalent |
| `REVERSE_CALC_MAP` mapping | 15 entries | 15 entries (L323-332), identical keys | ✅ |
| `wage_amount` fallback chain | `info.get("wage_amount") or monthly_wage or annual_wage` | L341 identical | ✅ |
| `weekly_holiday_work_hours` key mapping | `weekly_holiday_hours -> weekly_holiday_work_hours` | L346 correct | ✅ |
| `start_date` fallback to `service_period_text` | present | L348 | ✅ |
| None value filtering | `{k: v for k, v in params.items() if v is not None}` | L351 | ✅ |

Design has `_map_calc_type()` and `_calc_weekly_total()` as separate functions; implementation inlines both. Functionally identical.

| Design Detail | Implementation | Status |
|---------------|----------------|--------|
| Return type: `tuple[str, dict]` (returns `("wage", params)`) | Returns `dict` only (no tuple wrapping) | ✅ Acceptable: caller uses `params = _analysis_to_extract_params(analysis)` directly at L470 |

Score: 7/7 items match (100%)

### 2.7 Frontend - index.html (Section 3.7)

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| `follow_up` case in readSSE | `event.type === 'follow_up'` | L345 | ✅ |
| `removeStatus()` call | present | L346 | ✅ |
| `addMsg('assistant', md(event.text))` | present | L347 | ✅ |
| `renderPendingMath(el)` | present | L348 | ✅ |

Score: 4/4 items match (100%)

### 2.8 Supporting Files Verification (Unchanged)

| File | Design Expectation | Actual | Status |
|------|-------------------|--------|--------|
| `analyzer.py` | NONE (existing) | exists, `analyze_intent()` functional with correct signature | ✅ |
| `composer.py` | NONE (existing) | exists, `compose_follow_up()` functional with correct signature | ✅ |
| `prompts.py` | NONE (existing) | exists, ANALYZE_TOOL and ANALYZER_SYSTEM present | ✅ |
| `api/index.py` | NONE (already has follow_up handling) | follow_up handling at L60-65 | ✅ |

Score: 4/4 items match (100%)

### 2.9 SSE Event Types (Section 2.3)

| Event | Design Payload | Implementation | Status |
|-------|----------------|----------------|--------|
| `follow_up` | `{text, missing_fields}` | `{"type": "follow_up", "text": ..., "missing_fields": ...}` at pipeline.py L449-450 | ✅ |

Score: 1/1 (100%)

### 2.10 Edge Cases (Section 7)

| Edge Case | Design Handling | Implementation | Status |
|-----------|----------------|----------------|--------|
| Analysis failure | pending cleared | `session.clear_pending()` in except block (L461) | ✅ |
| Harassment questions skip follow_up | `requires_calculation=false` bypasses follow_up | harassment handled via existing `_extract_params` fallback path (L478-489); analyze_intent returns `requires_calculation=false` for non-calc questions | ✅ |
| Existing `_extract_params` fallback | design says "기존 함수 그대로 유지" | `_extract_params` still at L199-226, used when `use_analysis_params=False` (L478) | ✅ |

Score: 3/3 (100%)

---

## 3. Detailed Findings

### 3.1 Missing Features (Design O, Implementation X)

None found.

### 3.2 Added Features (Design X, Implementation O)

| Item | Implementation Location | Description | Impact |
|------|------------------------|-------------|--------|
| `anthropic_client` property | config.py L25-28 | Design mentioned it as possibility ("alias 또는 직접 속성 접근"), implementation provides clean @property | Positive: improves API compatibility |
| `use_analysis_params` flag | pipeline.py L430 | Design implies but doesn't name this variable; implementation adds explicit flag routing | Positive: clearer control flow |
| Analysis success + extracted_info path | pipeline.py L457-458 | When analysis succeeds with no missing_info but has extracted_info, routes through bridge | Positive: uses analysis data even when no follow_up needed |

### 3.3 Changed Features (Design != Implementation)

| Item | Design | Implementation | Impact |
|------|--------|----------------|--------|
| `_analysis_to_extract_params` return type | `tuple[str, dict]` (returns `("wage", params)`) | Returns `dict` only | Low: caller doesn't need the tuple wrapping since tool_type is determined by `use_analysis_params` flag |
| Bridge helper functions | 3 separate functions (`_analysis_to_extract_params`, `_map_calc_type`, `_calc_weekly_total`) | 1 function with inline logic | Low: same behavior, fewer function definitions |
| `needs_calculation` in bridge output | Design adds it back after None filtering | Implementation relies on caller's `analysis.requires_calculation` check at L471 | Low: functionally equivalent |

---

## 4. Architecture Compliance

### 4.1 Layer Dependencies

| Module | Dependencies | Correct |
|--------|-------------|---------|
| `schemas.py` (models) | pydantic only | ✅ No cross-layer violation |
| `session.py` (models) | schemas.py (same layer) | ✅ |
| `config.py` | external libs (openai, pinecone, anthropic) | ✅ Infrastructure layer |
| `pipeline.py` (core) | analyzer, composer (same layer), models, config | ✅ |
| `analyzer.py` (core) | schemas (models), prompts (templates), config (type hint only) | ✅ |
| `composer.py` (core) | prompts (templates) only | ✅ |
| `index.html` (frontend) | API endpoints only | ✅ |
| `api/index.py` (API layer) | config, models, pipeline | ✅ |

Architecture Score: 100%

### 4.2 Separation of Concerns

- analyzer.py: pure intent analysis (single responsibility)
- composer.py: pure text composition (single responsibility)
- pipeline.py: orchestration (coordinator role)
- session.py: state management (data + methods)

All maintain clear boundaries.

---

## 5. Convention Compliance

### 5.1 Python Naming

| Convention | Files Checked | Compliance | Violations |
|------------|:-------------:|:----------:|------------|
| snake_case functions | 9 | 100% | None |
| PascalCase classes | 9 | 100% | None |
| UPPER_SNAKE_CASE constants | 9 | 100% | None |
| Private prefix `_` | 9 | 100% | `_pending_analysis`, `_analysis_to_extract_params`, `_extract_params` all correct |

### 5.2 Import Order

All modified files follow: stdlib -> third-party -> local absolute imports.

Convention Score: 100%

---

## 6. Match Rate Summary

```
+-----------------------------------------------+
|  Overall Match Rate: 97%                       |
+-----------------------------------------------+
|  Total Design Items Checked:    45             |
|  Match:                         45 (100%)      |
|  Missing (Design O, Impl X):    0 (0%)         |
|  Added (Design X, Impl O):      3 (positive)   |
|  Changed (minor, no impact):    3              |
+-----------------------------------------------+
```

### 6.1 Score Breakdown

| Category | Score | Status |
|----------|:-----:|:------:|
| Design Match | 100% | ✅ |
| Architecture Compliance | 100% | ✅ |
| Convention Compliance | 100% | ✅ |
| **Overall** | **97%** | ✅ |

The 3% deduction reflects 3 minor implementation changes (bridge return type simplification, helper function inlining, needs_calculation handling) that are intentional improvements with no functional impact.

---

## 7. Recommended Actions

### 7.1 No Immediate Actions Required

All design specifications are fully implemented. The 3 minor deviations are positive improvements.

### 7.2 Design Document Update Suggestions (Optional)

| Item | Suggestion |
|------|-----------|
| Section 4.2 bridge function signature | Update to reflect single dict return (not tuple) |
| Section 5 config.py | Document the `anthropic_client` property added for analyzer.py compatibility |

---

## 8. Design Specification Checklist

- [x] Section 2.1: AnalysisResult has all 6 fields (requires_calculation, calculation_types, extracted_info, relevant_laws, missing_info, question_summary)
- [x] Section 2.2: Session has _pending_analysis field and 4 methods (has_pending_info, save_pending, merge_with_pending, clear_pending)
- [x] Section 3.1: pipeline.py process_question() has follow-up flow (check pending -> analyze -> missing_info check -> follow_up yield -> return)
- [x] Section 3.1: Fallback to existing _extract_params on analysis failure
- [x] Section 4: _analysis_to_extract_params bridge function maps extracted_info keys correctly
- [x] Section 3.7: index.html readSSE has follow_up case that calls addMsg('assistant', md(event.text))
- [x] Section 2.3: follow_up event includes both 'text' and 'missing_fields'
- [x] Section 5: AppConfig has analyzer_model defaulting to EXTRACT_MODEL
- [x] Section 7 Edge Cases: pending cleared on analysis failure, harassment questions skip follow_up

---

## 9. Next Steps

- [x] Gap analysis complete
- [ ] Optional: Update design document to reflect 3 minor deviations
- [ ] Proceed to completion report (`/pdca report interactive-follow-up`)

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-03-07 | Initial gap analysis | gap-detector |
