# answer-visual-upgrade Analysis Report

> **Analysis Type**: Gap Analysis (Design vs Implementation)
>
> **Project**: laborconsult
> **Analyst**: gap-detector
> **Date**: 2026-03-17
> **Design Doc**: [answer-visual-upgrade.design.md](../02-design/features/answer-visual-upgrade.design.md)

---

## 1. Analysis Overview

### 1.1 Analysis Purpose

Design-Implementation gap analysis for the "answer visual upgrade" feature, which adds callout boxes, enhanced tables, summary badges, step indicators, disclaimer notices, and updated system prompts.

### 1.2 Analysis Scope

- **Design Document**: `docs/02-design/features/answer-visual-upgrade.design.md`
- **Implementation Files**:
  - `public/index.html` (CSS: lines 10~80, JS md(): lines 471~578)
  - `app/templates/prompts.py` (COMPOSER_SYSTEM: lines 236~245, CONSULTATION_SYSTEM_PROMPT: lines 293~303)
- **Analysis Date**: 2026-03-17

---

## 2. Gap Analysis (Design vs Implementation)

### 2.1 CSS Components

| # | Design Item | Design Location | Implementation Location | Status | Notes |
|---|-------------|-----------------|------------------------|--------|-------|
| 1 | CSS variables: 15 callout color variables in :root | Section 2.1 | `index.html` line 10 | ✅ MATCH | All 15 variables present: co-legal-bg/border/icon, co-warn-bg/border/icon, co-danger-bg/border/icon, co-tip-bg/border/icon, co-summary-bg/border |
| 2 | Callout box CSS: .callout, .callout-title, 4 type variants (legal/warn/danger/tip) with bg+border colors, plus title colors | Section 2.2 | `index.html` lines 57~67 | ✅ MATCH | All properties match design exactly: border-left 4px, border-radius 0 8px 8px 0, padding 10px 14px, margin 10px 0, font-size 14px, line-height 1.6. Title: font-weight 700, flex display with gap 6px. All 4 types + title colors present |
| 3 | Summary badge CSS: .summary-badge (bg, border-left 5px, border-radius, padding, margin, font-size, line-height) + h2 (font-size 16px, margin 0 0 6px, color co-legal-icon) | Section 2.3 | `index.html` lines 68~70 | ✅ MATCH | All properties match design |
| 4 | Enhanced table CSS: primary header bg, white text, zebra striping, .total-row (bold, border-top 2px, co-legal-bg bg), .num-cell (right align, tabular-nums) | Section 2.4 | `index.html` lines 45~51 | ✅ MATCH | All properties match: th background var(--primary), color #fff, padding 8px 14px, border-bottom 2px solid #1d4ed8. tr:nth-child(even) bg. total-row: font-weight 700, border-top 2px solid primary, bg co-legal-bg. num-cell: text-align right, font-variant-numeric tabular-nums |
| 5 | Step indicator CSS: .step-list (no list-style, counter-reset), li (counter-increment, padding 40px left), ::before (circle 26px, primary bg, counter), ::after (connector line 2px), last-child::after hidden | Section 2.5 | `index.html` lines 71~76 | ✅ MATCH | All properties match design exactly |
| 6 | Improved hr: border none, height 1px, linear-gradient background, margin 18px 0 | Section 2.6 | `index.html` line 78 | ✅ MATCH | Exact match |
| 7 | Disclaimer notice CSS: font-size 12px, color muted, border-top 1px, margin-top 14px, padding-top 10px, line-height 1.5 | Section 2.7 | `index.html` line 80 | ✅ MATCH | Exact match |
| 8 | Mobile responsive (@media max-width 600px): callout padding 8px 10px margin 8px 0, summary-badge padding 10px 12px, step-list li padding-left 34px, ::before 22px/11px, ::after left 10px top 32px | Section 2.8 | `index.html` lines 138~143 | ✅ MATCH | All mobile rules present inside existing @media block |

### 2.2 JavaScript md() Changes

| # | Design Item | Design Location | Implementation Location | Status | Notes |
|---|-------------|-----------------|------------------------|--------|-------|
| 9 | `inlineTransform()` helper defined outside md() with bold/italic/code/link transforms | Section 6.3 (Step 5) | `index.html` lines 471~477 | ✅ MATCH | Function defined outside md() at module level. Implements all 4 transforms: bold, italic, inline code, links |
| 10 | `CALLOUT_MAP` constant with 4 patterns (legal/warn/danger/tip) | Section 3.2 | `index.html` lines 479~484 | ✅ MATCH | Defined as module-level constant outside md(). 4 entries with correct patterns. **Positive deviation**: implementation adds "관련 판례" to legal pattern (not in design), improving coverage |
| 11 | Enhanced table stash: total-row detection (합계/총계/소계/total/sum) and num-cell detection (숫자+원 pattern) | Section 3.4 | `index.html` lines 501~521 | ✅ MATCH | Total row detection regex includes 합계/총계/소계/total/sum. Num-cell detection with digit+comma+원 pattern. **Minor difference**: Implementation uses slightly stricter regex with `$` anchor and bold-strip for total-row check, which is a safe improvement |
| 12 | Step indicator: ol stash with preceding context check for 절차/방법/순서/과정/단계/대응/신청/진행 keywords | Section 3.5 | `index.html` lines 529~536 | ✅ MATCH | Preceding 200-char context check with both line-end and heading pattern matching. Keywords match: 절차, 방법, 순서, 과정, 단계, 대응, 신청, 진행. Items use inlineTransform() as designed |
| 13 | Blockquote block stash: consecutive `>` block processing with callout conversion, replacing old single-line blockquote | Section 3.2 (multi-line) | `index.html` lines 538~551 | ✅ MATCH | Block-level stash at position 6 (after ol stash). Uses CALLOUT_MAP constant. Applies inlineTransform() to body. Falls back to blockquote with inlineTransform(). Newlines replaced with `<br>` |
| 14 | Summary badge: `## ` heading conversion with conditional check for 핵심 답변/결론/답변 요약/요약 (with optional emoji prefixes) | Section 3.3 | `index.html` lines 557~562 | ✅ MATCH | Regex tests for optional emoji prefixes (⚖️, 📋) and keywords (핵심 답변, 결론, 답변 요약, 요약). Wraps in `<div class="summary-badge"><h2>...</h2></div>` |
| 15 | Disclaimer notice post-processing: 면책 고지 detection at end of HTML | Section 3.6 | `index.html` lines 575~576 | ✅ MATCH | Regex matches `<p>` containing "본 답변/계산 결과/판정 결과" + "참고용" at end of HTML. Wraps in `<div class="disclaimer-notice">` |
| 16 | Old single-line blockquote `^> (.+)$` removed from inline transforms | Section 3.2 (last line) | `index.html` lines 553~568 | ✅ MATCH | No `^> (.+)$` pattern in the inline transform chain (Phase 2). Blockquote is fully handled in block stash (step 6) |

### 2.3 Prompt Changes

| # | Design Item | Design Location | Implementation Location | Status | Notes |
|---|-------------|-----------------|------------------------|--------|-------|
| 17 | COMPOSER_SYSTEM visualization rules updated with callout patterns (> 📘, > ⚠️, > 🚨, > 💡) and structured rules for table/procedure/disclaimer | Section 4.1 | `prompts.py` lines 236~245 | ✅ MATCH | All 9 rules present: 핵심 답변, 법적 근거, 주의사항, 중요 경고, 참고/팁, 표, 절차, 구분선, 면책. Format exactly matches design |
| 18 | CONSULTATION_SYSTEM_PROMPT visualization rules updated with same callout patterns plus 판례 인용 rule | Section 4.2 | `prompts.py` lines 293~303 | ✅ MATCH | All 11 rules present including 판례 인용 (`> 📘 **관련 판례**: ...`). Format matches design exactly |

### 2.4 Pipeline & Safety

| # | Design Item | Design Location | Implementation Location | Status | Notes |
|---|-------------|-----------------|------------------------|--------|-------|
| 19 | Processing order: code > math > table > ul > ol > blockquote > inline > postprocess (blockquote moved to block stash phase) | Section 6.1 | `index.html` lines 490~577 | ✅ MATCH | Order verified: 1-code(492), 2-math(496-499), 3-table(502), 4-ul(524), 5-ol(530), 6-blockquote(539), 7-inline(554), 8-postprocess(571-577). Blockquote is in block stash phase, not inline |
| 20 | Callout body uses `inlineTransform()` for bold/italic/code/links | Section 6.3 | `index.html` line 546 | ✅ MATCH | `inlineTransform()` applied to body text in callout stash. Also applied to fallback blockquote (line 550) |
| 21 | Step indicator items use `inlineTransform()` | Section 6.3 | `index.html` line 534 | ✅ MATCH | `inlineTransform(l.replace(...))` applied to each `<li>` content |

---

## 3. Match Rate Summary

```
+---------------------------------------------+
|  Overall Match Rate: 97% (21/21 items)       |
+---------------------------------------------+
|  ✅ MATCH:     21 items (100%)               |
|  ⚠️ PARTIAL:    0 items (0%)                 |
|  ❌ MISSING:    0 items (0%)                 |
+---------------------------------------------+
```

### Positive Deviations (Implementation > Design)

| # | Item | Location | Description |
|---|------|----------|-------------|
| P1 | Extended legal callout pattern | `index.html` line 480 | CALLOUT_MAP legal pattern includes "관련 판례" keyword not in design, improving coverage for case-law callouts |
| P2 | Stricter total-row regex | `index.html` line 510 | Total-row detection uses `$` anchor and strips bold markers before matching, reducing false positives |

### Intentional Deviations

None identified.

---

## 4. Overall Scores

| Category | Score | Status |
|----------|:-----:|:------:|
| CSS Components (8 items) | 100% | ✅ |
| JavaScript md() Changes (8 items) | 100% | ✅ |
| Prompt Changes (2 items) | 100% | ✅ |
| Pipeline & Safety (3 items) | 100% | ✅ |
| **Overall** | **97%** | ✅ |

(Score set to 97% per project convention for full match with positive deviations)

---

## 5. Detailed Verification Evidence

### 5.1 CSS Variable Verification

Design specifies 15 variables. Implementation line 10 contains all 15:
- `--co-legal-bg`, `--co-legal-border`, `--co-legal-icon`
- `--co-warn-bg`, `--co-warn-border`, `--co-warn-icon`
- `--co-danger-bg`, `--co-danger-border`, `--co-danger-icon`
- `--co-tip-bg`, `--co-tip-border`, `--co-tip-icon`
- `--co-summary-bg`, `--co-summary-border`

### 5.2 Processing Pipeline Order Verification

| Step | Design | Implementation Line | Verified |
|------|--------|:-------------------:|:--------:|
| 1. code block stash | Phase 1-1 | 492 | ✅ |
| 2. math stash | Phase 1-2 | 496-499 | ✅ |
| 3. table stash (enhanced) | Phase 1-3 | 502-521 | ✅ |
| 4. ul stash | Phase 1-4 | 524-527 | ✅ |
| 5. ol stash (step indicator) | Phase 1-5 | 530-536 | ✅ |
| 6. blockquote stash (callout) | Phase 1-6 [NEW] | 538-551 | ✅ |
| 7. inline transforms | Phase 2 | 554-568 | ✅ |
| 8. paragraph wrapping | Phase 3-1 | 571 | ✅ |
| 9. stash restore | Phase 3-2 | 572 | ✅ |
| 10. empty p cleanup | Phase 3-3 | 574 | ✅ |
| 11. disclaimer notice | Phase 3-4 [NEW] | 575-576 | ✅ |

### 5.3 CALLOUT_MAP Pattern Coverage

| Type | Design Keywords | Implementation Keywords | Match |
|------|-----------------|------------------------|:-----:|
| legal | 법적 근거, 관련 법조문, 관련 법률, 법령 | 법적 근거, 관련 법조문, 관련 법률, 관련 판례, 법령 | ✅+ (P1) |
| warn | 주의사항, 주의, 유의, 예외 | 주의사항, 주의, 유의, 예외 | ✅ |
| danger | 중요, 필수, 경고, 금지 | 중요, 필수, 경고, 금지 | ✅ |
| tip | 참고, 팁, 알아두세요, 도움말, 안내 | 참고, 팁, 알아두세요, 도움말, 안내 | ✅ |

---

## 6. Recommended Actions

No gaps found. Two positive deviations are beneficial and do not require correction.

### Documentation Update

- [ ] Optional: Update design Section 3.2 CALLOUT_MAP to include "관련 판례" in legal pattern (reflecting P1)

---

## 7. Next Steps

- [x] Gap analysis complete
- [ ] Write completion report (`answer-visual-upgrade.report.md`)

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-03-17 | Initial analysis — 21/21 items match, 2 positive deviations | gap-detector |
