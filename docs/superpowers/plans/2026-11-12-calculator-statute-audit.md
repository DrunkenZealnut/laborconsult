# calculator-statute-audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 계산기 모듈을 신규 적재 법령·고시·재결례 대조 결과(Design D1~D12)에 맞춰 고친다 — 실업급여(조기재취업수당 산식·요건·고시, 기준기간, 일용 요건)와 산재(3일 단서, 최고·최저 보상기준, 61세 감액, 통상근로계수, 직업병 안내), 근거 앵커·고시 등록·테스트·공개 흐름도 포함.

**Architecture:** PR-1(`fix/calc-statute-audit-ei`)은 `unemployment.py`·`constants.py`(고시 효력표)·흐름도·등록·앵커·문서, PR-2(`fix/calc-statute-audit-iaci`)는 `industrial_accident.py`·`constants.py`(보상기준 표·통상근로계수)·흐름도·등록·앵커. 두 PR은 main에서 각각 분기하고, 새 테스트 파일 `test_calculator_statute_audit.py` 하나를 둘이 나눠 채운다(PR-2는 PR-1 머지 뒤 재기반하거나 파일 끝에 클래스를 더한다). 근거 문구는 전부 `legal_anchors.CALC_BASIS_ANCHORS` + `fetch_official_rules` 등록 쌍으로 넣는다.

**Tech Stack:** Python 3.11(`./.venv/bin/python`), unittest(API 키 불요), 법제처 Open API(`fetch_official_rules.py --doc`, 등록 IP), GitHub CLI.

**Spec:** `docs/archive/2026-11/calculator-statute-audit/calculator-statute-audit.design.md` (Plan: `…/calculator-statute-audit.plan.md`, 2026-11-12 아카이브 — Task 본문의 경로는 작성 당시 위치)

**규칙(저장소 관례):** 테스트 파일에 클래스를 더할 때 `if __name__ == "__main__"` **앞**에 둔다(CI는 `python3 test_x.py`로 실행). 테스트는 `reference_year=2026`·`reference_date`를 고정한다(오늘 날짜에 묶지 않는다). 커밋 메시지 끝에 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

---

## File Structure

| 파일 | 책임 | PR |
|---|---|---|
| `wage_calculator/constants.py` | 고시 효력표 `EARLY_REEMPLOYMENT_WAGE_CAPS` + `early_reemployment_wage_cap()` / 보상기준 표 `COMPENSATION_LIMITS_DAILY`(→ `MIN_COMPENSATION_DAILY` 파생) + `ORDINARY_WORK_COEFFICIENT` | 1 / 2 |
| `wage_calculator/calculators/unemployment.py` | U1 조기재취업수당 산식·안내(`_early_reemployment_note`), U2 기준기간 문구, U3 일용 요건 안내, 상한 경과조치 안내(`_year_of`) | 1 |
| `wage_calculator/calculators/industrial_accident.py` | `_compensation_limits`·`_continued_three_months`·`_senior_factor`, `_calc_sick_leave(…, age)` 6-튜플, 평균임금 결정 뒤 상한·하한·일용·직업병 분기 | 2 |
| `wage_calculator/legal_anchors.py` | 새 근거 문구의 (doc_id, 구절) | 1·2 |
| `fetch_official_rules.py` | `ARTICLES`·`ANNEXES`·`ADMRULS`·`ADMRUL_LAW_GO_KR_ONLY` 등록 | 1·2 |
| `test_calculator_statute_audit.py` | 신규 — `EarlyReemploymentTests`·`UnemploymentWordingTests`·`FlowchartTests`(PR-1), `SickLeaveTests`·`CompensationLimitTests`·`DailyWorkerTests`·`OccupationalDiseaseTests`(PR-2) | 1·2 |
| `.github/workflows/tests.yml` | 모듈별 회귀 단계에 새 테스트 추가 | 1 |
| `public/calculator_flow/unemployment_benefit_calc.html` + `wage_calculator/calculator_flow/unemployment_benefit_calc.html` | 조기재취업 공식·예시·설명 교정(두 사본 같은 본문) | 1 |
| `public/calculator_flow/industrial_accident_compensation_calc.html` + 패키지 사본 | 3일 단서·보상기준·61세 한 줄 | 2 |
| `public/sw.js` | VERSION v15(PR-1) → v16(PR-2) | 1·2 |
| `CLAUDE.md` | Wage Calculator 절에 새 규칙 bullet | 1·2 |
| `docs/01-plan/...plan.md`, `docs/02-design/...design.md`, `.bkit/state/memory.json` | 문서·상태(§7 변경 사례는 Do에서 채움) | 1 |

---

## PR-1 — 실업급여 + 문서

### Task 1: 작업 트리·브랜치·문서 커밋

**Files:**
- Create worktree: `../laborconsult-csa1` (branch `fix/calc-statute-audit-ei` from `origin/main`)
- Modify: `.bkit/state/memory.json`
- Already written: `docs/01-plan/features/calculator-statute-audit.plan.md`, `docs/02-design/features/calculator-statute-audit.design.md`, `docs/superpowers/plans/2026-11-12-calculator-statute-audit.md`

- [ ] **Step 1: 작업 트리 만들기**

```bash
cd /Users/zealnutkim/DEV/laborconsult && git fetch -q origin && \
git worktree add ../laborconsult-csa1 -b fix/calc-statute-audit-ei origin/main && \
rsync -a output_공식법령/ ../laborconsult-csa1/output_공식법령/ && \
cp docs/01-plan/features/calculator-statute-audit.plan.md ../laborconsult-csa1/docs/01-plan/features/ && \
cp docs/02-design/features/calculator-statute-audit.design.md ../laborconsult-csa1/docs/02-design/features/ && \
cp docs/superpowers/plans/2026-11-12-calculator-statute-audit.md ../laborconsult-csa1/docs/superpowers/plans/
```
Expected: `Preparing worktree (new branch 'fix/calc-statute-audit-ei')`, 3개 문서가 작업 트리에 있다. (메인 작업 트리의 미추적 문서 3개는 머지 뒤 `git checkout`으로 정리한다.)

- [ ] **Step 2: bkit 상태에 기능 등록**

`../laborconsult-csa1/.bkit/state/memory.json`에 키 추가(python으로 안전하게):

```bash
cd /Users/zealnutkim/DEV/laborconsult-csa1 && python3 - <<'EOF'
import json
p='.bkit/state/memory.json'; d=json.load(open(p))
d['calculator-statute-audit']={"phase":"do","planPath":"docs/01-plan/features/calculator-statute-audit.plan.md",
  "designPath":"docs/02-design/features/calculator-statute-audit.design.md","startedAt":"2026-11-12","designAt":"2026-11-12",
  "doAt":"2026-11-12","baseline":"74400ff","source":"Pinecone 신규 적재분(qpack 54·rulings 1,052·official 14) × 계산기 대조",
  "doOrder":["PR-1 실업급여+문서","PR-2 산재"]}
json.dump(d,open(p,'w'),ensure_ascii=False,indent=2); open(p,'a').write('\n')
EOF
git diff --stat .bkit/state/memory.json
```
Expected: 1 file changed.

- [ ] **Step 3: 커밋**

```bash
cd /Users/zealnutkim/DEV/laborconsult-csa1 && git add docs/01-plan/features/calculator-statute-audit.plan.md docs/02-design/features/calculator-statute-audit.design.md docs/superpowers/plans/2026-11-12-calculator-statute-audit.md .bkit/state/memory.json && \
git commit -q -m "docs: calculator-statute-audit Plan·Design·구현 계획 — 신규 적재 법령·재결례 × 계산기 대조(U1~U3·I1~I5), 자료팩 누락 7+19조문 기록

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" && git log --oneline -1
```

---

### Task 2: 고시 효력표 `EARLY_REEMPLOYMENT_WAGE_CAPS`

**Files:**
- Modify: `wage_calculator/constants.py` (`UNEMPLOYMENT_BENEFIT_UPPER` 바로 뒤, 현재 46행 근처)
- Create: `test_calculator_statute_audit.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`test_calculator_statute_audit.py` 생성:

```python
"""calculator-statute-audit — 신규 적재 법령·고시·재결례 대조로 고친 계산기 규칙의 회귀(API 키 불요).

Design: docs/02-design/features/calculator-statute-audit.design.md (D1~D12). 테스트는 2026년·고정 기준일에 묶는다 — 오늘 날짜에
묶으면 해가 바뀔 때 깨진다(calc-card-followups 교훈).
"""
from __future__ import annotations

import copy
import unittest
from pathlib import Path

from wage_calculator.models import WageInput, WageType
from wage_calculator.calculators.ordinary_wage import calc_ordinary_wage

ROOT = Path(__file__).resolve().parent


def _unemp(**changes):
    inp = WageInput(monthly_wage=3_000_000, start_date="2023-01-01", end_date="2026-06-30",
                    reference_year=2026, reference_date="2026-11-12", age=35)
    for key, value in changes.items():
        setattr(inp, key, value)
    from wage_calculator.calculators.unemployment import calc_unemployment
    return calc_unemployment(inp, calc_ordinary_wage(copy.deepcopy(inp)))


class EarlyReemploymentWageCapTests(unittest.TestCase):
    """D2 — 지급제외 임금액 고시는 효력 기간을 가진 표다."""

    def test_cap_table_has_the_2026_71_notice(self):
        from wage_calculator.constants import EARLY_REEMPLOYMENT_WAGE_CAPS
        self.assertIn(("2026-11-01", "2029-10-31", 3_000_000, "고용노동부고시 제2026-71호"), EARLY_REEMPLOYMENT_WAGE_CAPS)

    def test_cap_lookup_respects_effective_period(self):
        from wage_calculator.constants import early_reemployment_wage_cap
        self.assertEqual(early_reemployment_wage_cap("2026-11-01")[:2], (3_000_000, "고용노동부고시 제2026-71호"))
        self.assertEqual(early_reemployment_wage_cap("2029-10-31")[:2], (3_000_000, "고용노동부고시 제2026-71호"))
        self.assertIsNone(early_reemployment_wage_cap("2026-10-31"))
        self.assertIsNone(early_reemployment_wage_cap("2029-11-01"))
        self.assertIsNone(early_reemployment_wage_cap(None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/zealnutkim/DEV/laborconsult-csa1 && /Users/zealnutkim/DEV/laborconsult/.venv/bin/python test_calculator_statute_audit.py 2>&1 | tail -4`
Expected: `FAILED (errors=2)` — `ImportError: cannot import name 'EARLY_REEMPLOYMENT_WAGE_CAPS'`.

- [ ] **Step 3: 구현**

`wage_calculator/constants.py`의 `UNEMPLOYMENT_BENEFIT_UPPER` dict 닫는 `}` 바로 뒤에 추가:

```python

# ── 조기재취업 수당 지급제외 임금액(고용보험법 시행령 제84조①1호 라목이 위임한 고시) ────────────────────────────
# (시행일, 효력 종료일(포함), 월 임금액, 고시 번호). 효력 기간을 표에 두는 이유는 난임 1일 상한표(DAILY_LEAVE_CAPS)와
# 같다 — 기한 없는 상수는 효력이 끝난 고시를 조용히 계속 적용한다. 새 고시가 나오면 행을 더한다(calculator-statute-audit D2).
EARLY_REEMPLOYMENT_WAGE_CAPS: tuple[tuple[str, str, int, str], ...] = (
    ("2026-11-01", "2029-10-31", 3_000_000, "고용노동부고시 제2026-71호"),
)


def early_reemployment_wage_cap(reference_date: str | None) -> tuple[int, str, str, str] | None:
    """기준일(YYYY-MM-DD)에 효력이 있는 (월 임금액, 고시 번호, 시행일, 종료일). 없으면 None — 고시 시행 전·효력 종료 뒤."""
    if not reference_date:
        return None
    for start, end, amount, notice in EARLY_REEMPLOYMENT_WAGE_CAPS:
        if start <= str(reference_date)[:10] <= end:
            return amount, notice, start, end
    return None
```

- [ ] **Step 4: 통과 확인**

Run: `cd /Users/zealnutkim/DEV/laborconsult-csa1 && /Users/zealnutkim/DEV/laborconsult/.venv/bin/python test_calculator_statute_audit.py 2>&1 | tail -3`
Expected: `OK` (2 tests).

- [ ] **Step 5: 커밋**

```bash
cd /Users/zealnutkim/DEV/laborconsult-csa1 && git add wage_calculator/constants.py test_calculator_statute_audit.py && \
git commit -q -m "feat(calc): 조기재취업 수당 지급제외 임금액 고시 효력표(제2026-71호, 월 300만원, 2026-11-01~2029-10-31)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: U1 — 조기재취업수당 산식·라벨·요건 안내

**Files:**
- Modify: `wage_calculator/calculators/unemployment.py` (모듈 docstring 19~21행, import 26~33행, 7절 323~330행, breakdown 358행, 파일 끝에 헬퍼)
- Test: `test_calculator_statute_audit.py`

- [ ] **Step 1: 실패하는 테스트 추가** (`if __name__` 앞에)

```python
class EarlyReemploymentTests(unittest.TestCase):
    """D1·D2 — 금액은 구직급여일액 × 미지급일수 × 1/2, 카드 값은 절반 남긴 시점 기준 하한, 요건·고시는 안내."""

    def test_formula_names_the_unpaid_days_rule_and_drops_the_max_label(self):
        res = _unemp()
        line = next(f for f in res.formulas if f.startswith("조기재취업수당"))
        self.assertIn("미지급일수", line)
        self.assertIn("× 1/2", line)
        self.assertIn("시행령 제85조", line)
        self.assertNotIn("최대", line)
        self.assertNotIn("최대", res.breakdown["조기재취업수당"])
        self.assertIn("절반", res.breakdown["조기재취업수당"])

    def test_floor_amount_is_unchanged_from_previous_card(self):
        res = _unemp()
        self.assertEqual(res.early_reemployment_bonus, round(res.daily_benefit * (res.benefit_days // 2) * 0.5, 0))

    def test_requirements_note_lists_statutory_conditions(self):
        res = _unemp()
        note = next(w for w in res.warnings if w.startswith("조기재취업수당 요건"))
        for piece in ("14일", "2분의 1", "12개월", "65세", "6개월", "최후 이직 사업주", "2년", "청구는 재취업 12개월 뒤"):
            self.assertIn(piece, note)
        self.assertIn("고용보험법 시행령 제84조 (지급기준)·제85조 (금액)·제86조 (청구)", res.legal_basis)

    def test_wage_cap_notice_appears_only_inside_its_effective_period(self):
        inside = next(w for w in _unemp(reference_date="2026-11-12").warnings if w.startswith("조기재취업수당 요건"))
        self.assertIn("월 3,000,000원", inside)
        self.assertIn("제2026-71호", inside)
        before = next(w for w in _unemp(reference_date="2026-10-01").warnings if w.startswith("조기재취업수당 요건"))
        self.assertNotIn("3,000,000", before)
        self.assertIn("고용노동부장관이 고시하는 임금액", before)
        after = next(w for w in _unemp(reference_date="2029-11-01").warnings if w.startswith("조기재취업수당 요건"))
        self.assertNotIn("3,000,000", after)
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/zealnutkim/DEV/laborconsult-csa1 && /Users/zealnutkim/DEV/laborconsult/.venv/bin/python test_calculator_statute_audit.py EarlyReemploymentTests 2>&1 | tail -4`
Expected: `FAILED (failures=3, errors=1)` — 산식에 "미지급일수" 없음, "최대" 포함, 요건 경고 없음(StopIteration).

- [ ] **Step 3: 구현**

(a) 모듈 docstring의 조기재취업 세 줄을 바꾼다:

```python
■ 조기재취업수당 (고용보험법 제64조, 시행령 제84조~제86조)
  금액 = 구직급여일액 × 미지급일수 × 1/2 (시행령 제85조①). 소정급여일수를 2분의 1 이상 남기고 재취업한 경우가 발생 요건이라
  그 경계(절반 남김)의 금액이 하한이다. 요건·제외(14일 경과·12개월 고용·전 사업주·고시 임금 이상 등)는 안내만 한다.
```

(b) import에 두 줄 추가:

```python
from ..constants import (
    MINIMUM_HOURLY_WAGE,
    UNEMPLOYMENT_BENEFIT_UPPER,
    PLATFORM_UNEMPLOYMENT_UPPER,
    PLATFORM_INSURED_REQ_MONTHS,
    PLATFORM_INSURED_REQ_WINDOW,
    early_reemployment_wage_cap,
)
from ..legal_rules import kst_today
```

(c) 7절 교체 — 기존

```python
    # ── 7. 조기재취업수당 ─────────────────────────────────────────────────────
    # 소정급여일수 절반 이상 남기고 취업 시, 남은 급여의 50%
    half_days    = benefit_days // 2
    early_bonus  = daily_benefit * half_days * 0.50
    formulas.append(
        f"조기재취업수당(최대): {daily_benefit:,.0f}원 × {half_days}일(절반) × 50% = {early_bonus:,.0f}원"
    )
    legal.append("고용보험법 제64조 (조기재취업수당)")
```
을

```python
    # ── 7. 조기재취업수당 — 구직급여일액 × 미지급일수 × 1/2 (고용보험법 제64조③·시행령 제85조①) ──────────────────
    # 재취업일은 입력에 없다. 발생 요건의 경계(재취업 전날 기준 소정급여일수의 2분의 1을 남김)에서의 금액이 **하한**이고, 더
    # 일찍 재취업하면 미지급일수가 늘어 커진다. 예전 카드는 이 하한을 '(최대)'라 불렀다(calculator-statute-audit U1).
    half_days    = benefit_days // 2
    early_bonus  = daily_benefit * half_days * 0.50
    formulas.append(
        f"조기재취업수당(절반 남긴 시점 기준): {daily_benefit:,.0f}원 × 미지급일수 {half_days}일 × 1/2 = {early_bonus:,.0f}원 "
        "— 미지급일수가 많을수록 커집니다(고용보험법 시행령 제85조 제1항)"
    )
    warnings.append(_early_reemployment_note(getattr(inp, "reference_date", None)))
    legal.append("고용보험법 제64조 (조기재취업 수당)")
    legal.append("고용보험법 시행령 제84조 (지급기준)·제85조 (금액)·제86조 (청구)")
```
으로.

(d) breakdown의 `"조기재취업수당":` 줄을

```python
        "조기재취업수당":  f"{early_bonus:,.0f}원  (소정급여일수의 절반을 남기고 재취업한 경우의 금액 — 요건·제외는 안내 참조)",
```
으로.

(e) 파일 끝(마지막 함수 뒤)에 헬퍼 추가:

```python


def _early_reemployment_note(reference_date: str | None) -> str:
    """조기재취업수당 요건·제외·청구 시기 — 판정하지 않고 안내만(시행령 제84조·제86조, 법 제64조②). 고시 임금액은 기준일에
    효력이 있는 행이 있을 때만 금액으로 적는다(calculator-statute-audit D2)."""
    cap = early_reemployment_wage_cap(reference_date or kst_today())
    wage_clause = (f"월 {cap[0]:,.0f}원 이상 임금({cap[1]}, {cap[2]}~{cap[3]} 재취업분)" if cap
                   else "고용노동부장관이 고시하는 임금액 이상")
    return (
        "조기재취업수당 요건: 실업 신고일부터 14일이 지난 후 재취업하고, 재취업 전날 기준 소정급여일수를 2분의 1 이상 남겼으며, "
        "12개월 이상 계속 고용(이직일 당시 65세 이상은 6개월 이상 고용 인정)이어야 합니다. 최후 이직 사업주·관련 사업주 재고용, "
        f"신고 전 채용 약속, 공무원 채용, 병역 특례 근무, {wage_clause}은 제외됩니다. 재취업 전 2년 안에 수당을 받았으면 "
        "지급되지 않고, 청구는 재취업 12개월 뒤(65세 이상은 즉시)입니다(고용보험법 시행령 제84조·제86조)."
    )
```

- [ ] **Step 4: 통과 확인**

Run: `cd /Users/zealnutkim/DEV/laborconsult-csa1 && /Users/zealnutkim/DEV/laborconsult/.venv/bin/python test_calculator_statute_audit.py 2>&1 | tail -3`
Expected: `OK` (6 tests).

- [ ] **Step 5: 기존 회귀**

Run: `cd /Users/zealnutkim/DEV/laborconsult-csa1 && for t in test_wage_golden.py test_pipeline_wiring.py test_audit50.py test_calc_card_consistency.py; do /Users/zealnutkim/DEV/laborconsult/.venv/bin/python $t > /tmp/csa_$t.log 2>&1; echo "$t exit=$?"; done`
Expected: 전부 `exit=0`.

- [ ] **Step 6: 커밋**

```bash
cd /Users/zealnutkim/DEV/laborconsult-csa1 && git add wage_calculator/calculators/unemployment.py test_calculator_statute_audit.py && \
git commit -q -m "fix(calc): 조기재취업수당은 구직급여일액 × 미지급일수 × 1/2 — '(최대)' 라벨 제거, 절반 남긴 시점 기준 하한으로 표기, 요건·제외·청구 시기·고시 임금 안내(U1)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: U2·U3 — 기준기간 문구, 일용근로자 요건 안내, 상한 경과조치 안내

**Files:**
- Modify: `wage_calculator/calculators/unemployment.py` (153~159행 `else:` 분기, 259~262행 상한 결정 뒤)
- Test: `test_calculator_statute_audit.py`

- [ ] **Step 1: 실패하는 테스트 추가**

```python
class UnemploymentWordingTests(unittest.TestCase):
    """D3 — 기준기간 18개월(초단시간 24개월), 일용근로자 수급요건 안내, 상한 경과조치 안내."""

    def test_reference_period_text_has_no_daily_worker_one_year(self):
        res = _unemp(insurance_months=3)
        self.assertFalse(res.is_eligible)
        self.assertNotIn("1년", res.ineligible_reason)
        self.assertIn("18개월", res.ineligible_reason)
        self.assertIn("24개월", res.ineligible_reason)
        self.assertIn("제40조", res.ineligible_reason)

    def test_daily_worker_gets_the_one_third_rule_note(self):
        res = _unemp(is_daily_worker=True)
        note = next(w for w in res.warnings if w.startswith("일용근로자 추가 요건"))
        for piece in ("3분의 1", "14일간", "제40조 제1항 제5호", "제49조 제1항 단서"):
            self.assertIn(piece, note)
        self.assertIn("고용보험법 제40조 제1항 제5호 (일용근로자 수급요건)", res.legal_basis)
        self.assertFalse(any(w.startswith("일용근로자 추가 요건") for w in _unemp().warnings))

    def test_upper_limit_note_when_separation_year_differs(self):
        res = _unemp(end_date="2025-12-15", reference_year=2026)
        note = next(w for w in res.warnings if w.startswith("구직급여 상한액은 이직일 기준"))
        self.assertIn("66,000원", note)
        self.assertIn("부칙", note)
        self.assertEqual(res.upper_limit, 68_100)   # 계산 값은 기준연도 그대로
        self.assertFalse(any(w.startswith("구직급여 상한액은 이직일 기준") for w in _unemp(end_date="2026-06-30").warnings))
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/zealnutkim/DEV/laborconsult-csa1 && /Users/zealnutkim/DEV/laborconsult/.venv/bin/python test_calculator_statute_audit.py UnemploymentWordingTests 2>&1 | tail -4`
Expected: `FAILED (failures=1, errors=2)`.

- [ ] **Step 3: 구현**

(a) `else:` 분기(일반 근로자) 교체 — 기존

```python
    else:
        # ① 피보험단위기간 부족 (일반 근로자)
        if insured_days_approx < MIN_INSURED_DAYS:
            reason = (
                f"피보험단위기간 약 {insured_days_approx}일 — 최소 {MIN_INSURED_DAYS}일 필요. "
                "이직일 이전 18개월 이내(초단시간근로자는 24개월, 일용직은 1년)에 "
                "피보험단위기간 합계가 180일 이상이어야 합니다."
            )
            return _ineligible(reason, warnings, legal)
```
을

```python
    else:
        # ① 피보험단위기간 부족 (일반 근로자) — 기준기간은 18개월, 초단시간근로자(주 15시간 미만·주 2일 이하)는 24개월
        # (고용보험법 제40조②). 일용근로자에 별도 기준기간은 없다 — 예전 문구의 '일용직은 1년'은 법에 없는 값이었다(U2)
        if insured_days_approx < MIN_INSURED_DAYS:
            reason = (
                f"피보험단위기간 약 {insured_days_approx}일 — 최소 {MIN_INSURED_DAYS}일 필요. "
                "이직일 이전 18개월 이내(초단시간근로자는 24개월)에 피보험단위기간 합계가 180일 이상이어야 합니다"
                "(고용보험법 제40조 제1항·제2항)."
            )
            return _ineligible(reason, warnings, legal)
        # 일용근로자 추가 요건(제40조①5호) — 근로일수 입력이 없어 판정하지 않고 안내만 한다(U3). 건설일용은 대기기간이 없다(제49조① 단서)
        if getattr(inp, "is_daily_worker", False):
            warnings.append(
                "일용근로자 추가 요건(고용보험법 제40조 제1항 제5호): 수급자격 인정신청일이 속한 달의 직전 달 초일부터 신청일까지 "
                "근로일수 합이 같은 기간 총일수의 3분의 1 미만이어야 합니다(건설일용근로자는 신청일 이전 14일간 연속 근로내역이 "
                "없으면 됩니다). 건설일용근로자는 대기기간 없이 신고일부터 지급합니다(제49조 제1항 단서)."
            )
            legal.append("고용보험법 제40조 제1항 제5호 (일용근로자 수급요건)")
```
으로.

(b) 상한 결정 뒤(`upper = float(UNEMPLOYMENT_BENEFIT_UPPER.get(...))` 블록 바로 다음, 하한 계산 앞)에 추가:

```python
        # 상한액은 이직일 기준 — 2026년 인상(68,100원)은 2026-01-01 이후 이직자에게 적용되고 그 전 이직자는 종전 규정
        # (고용보험법 시행령 부칙 <제35934호> 제4조). 계산은 기준연도 의미론을 유지하고 어긋남만 알린다
        end_year = _year_of(getattr(inp, "end_date", None))
        if end_year and end_year < year and UNEMPLOYMENT_BENEFIT_UPPER.get(end_year) not in (None, upper):
            warnings.append(
                f"구직급여 상한액은 이직일 기준으로 적용됩니다 — 이직일 {inp.end_date}의 상한은 "
                f"{UNEMPLOYMENT_BENEFIT_UPPER[end_year]:,.0f}원입니다(고용보험법 시행령 부칙 <제35934호> 제4조). "
                f"이 카드는 {year}년 상한 {upper:,.0f}원으로 계산했습니다."
            )
```

(c) 파일 끝 헬퍼 추가(`_early_reemployment_note` 앞이나 뒤):

```python


def _year_of(text) -> int | None:
    """'YYYY-MM-DD' 문자열의 연도. 형식이 아니면 None."""
    s = str(text or "")
    return int(s[:4]) if len(s) >= 4 and s[:4].isdigit() else None
```

- [ ] **Step 4: 통과 확인**

Run: `cd /Users/zealnutkim/DEV/laborconsult-csa1 && /Users/zealnutkim/DEV/laborconsult/.venv/bin/python test_calculator_statute_audit.py 2>&1 | tail -3`
Expected: `OK` (9 tests).

- [ ] **Step 5: 커밋**

```bash
cd /Users/zealnutkim/DEV/laborconsult-csa1 && git add wage_calculator/calculators/unemployment.py test_calculator_statute_audit.py && \
git commit -q -m "fix(calc): 실업급여 기준기간 문구에서 법에 없는 '일용직 1년' 제거(18개월·초단시간 24개월), 일용근로자 수급요건(3분의 1·건설일용 14일) 안내, 상한 경과조치 안내(U2·U3)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: 등록·앵커·원문 수집 (PR-1)

**Files:**
- Modify: `fetch_official_rules.py` (`ARTICLES` 끝 `lsa_act_60` 뒤, `ADMRULS` 끝 `cardio_notice` 뒤, `ADMRUL_LAW_GO_KR_ONLY`)
- Modify: `wage_calculator/legal_anchors.py`
- Test: `test_wage_update_2026.py::CalcBasisAnchorTests` (기존), `test_kin_accuracy.py`, `test_claim_assessor_facts.py`

- [ ] **Step 1: 앵커 추가(테스트가 먼저 실패하도록)**

`wage_calculator/legal_anchors.py`의 `CALC_BASIS_ANCHORS` 튜플 끝(`("ei_enf_95", "해당 금액이 160만원을 넘는 경우에는 160만원으로"),` 뒤)에:

```python
    # 조기재취업수당 — 금액·요건·제외·청구 시기(unemployment.py, calculator-statute-audit U1)
    ("ei_act_64", "미지급일수의 비율에 따라 대통령령으로 정하는 기준에 따라 산정한 금액"),
    ("ei_enf_85", "구직급여일액에 미지급일수의 2분의 1을 곱한 금액"),
    ("ei_enf_84", "14일이 지난 후 재취업한 수급자격자가 재취업한 날의 전날을 기준으로"),
    ("ei_enf_84", "소정급여일수를 2분의 1 이상 남기고 재취업한 경우"),
    ("ei_enf_84", "12개월 이상 계속하여 고용된 경우이거나 이직일 당시 65세 이상인 사람"),
    ("ei_enf_84", "고용노동부장관이 정하여 고시하는 임금액 이상을 받는 경우"),
    ("ei_enf_84", "2년을 말한다"),
    ("ei_enf_86", "시작한 날부터 12개월 이후에 제출해야 한다"),
    ("ei_early_reemp_wage", "월 3,000,000원"),
    # 실업급여 기준기간·일용근로자 수급요건(U2·U3)
    ("ei_act_40", "기준기간은 이직일 이전 18개월로 하되"),
    ("ei_act_40", "근로일 수의 합이 같은 기간 동안의 총 일수의 3분의 1 미만일 것"),
    ("ei_act_40", "수급자격 인정신청일 이전 14일간 연속하여 근로내역이 없을 것"),
    ("ei_act_49", "최종 이직 당시 건설일용근로자였던 사람에 대해서는 제42조에 따른 실업의 신고일부터 계산하여 구직급여를 지급한다"),
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/zealnutkim/DEV/laborconsult-csa1 && /Users/zealnutkim/DEV/laborconsult/.venv/bin/python test_wage_update_2026.py CalcBasisAnchorTests 2>&1 | grep -E "AssertionError|FAIL|OK" | head -5`
Expected: `FAIL: test_anchor_docs_are_registered_for_collection` — `'ei_enf_85' not found in {...}`.

- [ ] **Step 3: 등록**

`fetch_official_rules.py` `ARTICLES`의 `("lsa_act_60", ...)` 줄 뒤에:

```python
    # 조기재취업수당의 금액·청구(unemployment.py — calculator-statute-audit U1). 제40·64조·시행령 제84조·제49조는 unemployment
    # 규칙 블록 앵커로 이미 등록돼 있다. 앵커 전용(keys 없음)
    ("ei_enf_85",     "고용보험법 시행령",               85,  None, []),
    ("ei_enf_86",     "고용보험법 시행령",               86,  None, []),
```

`ADMRULS`의 `("cardio_notice", ...)` 항목 뒤에:

```python
    # 조기재취업 수당 지급제외 임금액(시행령 제84조①1호 라목 위임, 고용노동부고시 제2026-71호, 2026-11-01~2029-10-31) —
    # unemployment 카드 안내 문구의 앵커(calculator-statute-audit D2). 앵커 전용(keys 없음), 법제처 통합본으로만 받는다
    ("ei_early_reemp_wage", "조기재취업 수당 지급제외",
     "조기재취업 수당 지급제외 대상에 해당하는 임금액 고시", "고용노동부", []),
```

`ADMRUL_LAW_GO_KR_ONLY = {"cardio_notice"}` → `ADMRUL_LAW_GO_KR_ONLY = {"cardio_notice", "ei_early_reemp_wage"}`.

- [ ] **Step 4: 원문 수집(등록 IP)**

Run: `cd /Users/zealnutkim/DEV/laborconsult-csa1 && /Users/zealnutkim/DEV/laborconsult/.venv/bin/python fetch_official_rules.py --doc ei_enf_85 --doc ei_enf_86 --doc ei_early_reemp_wage 2>&1 | tail -8 && ls -la output_공식법령/ei_enf_85.md output_공식법령/ei_enf_86.md output_공식법령/ei_early_reemp_wage.md`
Expected: 3개 파일 생성. 인증 오류(`<Response>`)면 등록 회선인지 확인하고 중단(exit 2).

- [ ] **Step 5: 앵커 원문 존재 확인**

Run: `cd /Users/zealnutkim/DEV/laborconsult-csa1 && for t in test_wage_update_2026.py test_kin_accuracy.py test_claim_assessor_facts.py; do /Users/zealnutkim/DEV/laborconsult/.venv/bin/python $t > /tmp/csa_$t.log 2>&1; echo "$t exit=$? $(tail -1 /tmp/csa_$t.log)"; done`
Expected: 셋 다 `exit=0 OK`. 실패 시 메시지의 구절을 저장본에서 `grep`해 원문 표기(공백·가운뎃점·따옴표)에 맞춰 앵커 구절을 고친다 — 원문은 고치지 않는다.

- [ ] **Step 6: 메인 작업 트리의 원문 사본 동기화 + 커밋**

```bash
rsync -a /Users/zealnutkim/DEV/laborconsult-csa1/output_공식법령/ /Users/zealnutkim/DEV/laborconsult/output_공식법령/ && \
cd /Users/zealnutkim/DEV/laborconsult-csa1 && git add fetch_official_rules.py wage_calculator/legal_anchors.py && \
git commit -q -m "feat(anchors): 조기재취업수당·기준기간·일용 수급요건 근거 앵커 13개 + 시행령 제85·86조·지급제외 임금액 고시 등록(앵커 전용)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: 공개 흐름도 교정 + 서비스워커 버전

**Files:**
- Modify: `public/calculator_flow/unemployment_benefit_calc.html`, `wage_calculator/calculator_flow/unemployment_benefit_calc.html` (같은 본문 3곳)
- Modify: `public/sw.js:12`
- Test: `test_calculator_statute_audit.py`

- [ ] **Step 1: 실패하는 테스트 추가**

```python
class FlowchartTests(unittest.TestCase):
    """D11 — 공개 흐름도 두 사본의 본문이 같고, 조기재취업 공식이 미지급일수 × 1/2다."""

    _FLOW = ("public/calculator_flow/unemployment_benefit_calc.html",
             "wage_calculator/calculator_flow/unemployment_benefit_calc.html")

    @staticmethod
    def _svg_body(path: Path) -> str:
        text = path.read_text(encoding="utf-8")
        return text[text.index("<svg"):]   # head 메타데이터·단독 진입 링크는 공개 사본에만 있다

    def test_two_copies_share_the_same_svg_body(self):
        a, b = (self._svg_body(ROOT / p) for p in self._FLOW)
        self.assertEqual(a, b)

    def test_early_reemployment_formula_is_half_of_unpaid_days(self):
        body = self._svg_body(ROOT / self._FLOW[0])
        self.assertNotIn("÷ 2) × 50%", body)
        self.assertNotIn("2,553,750", body)
        self.assertIn("미지급(잔여)일수 × 1/2", body)
        self.assertIn("68,100 × 150일 × 1/2 = 5,107,500원", body)
        self.assertIn("14일", body)          # 요건 설명 줄
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/zealnutkim/DEV/laborconsult-csa1 && /Users/zealnutkim/DEV/laborconsult/.venv/bin/python test_calculator_statute_audit.py FlowchartTests 2>&1 | tail -4`
Expected: `FAILED (failures=1)` — `test_early_reemployment_formula...`(두 사본 동일 테스트는 통과).

- [ ] **Step 3: 두 사본 같은 치환**

```bash
cd /Users/zealnutkim/DEV/laborconsult-csa1 && for f in public/calculator_flow/unemployment_benefit_calc.html wage_calculator/calculator_flow/unemployment_benefit_calc.html; do
python3 - "$f" <<'EOF'
import sys, pathlib
p = pathlib.Path(sys.argv[1]); s = p.read_text(encoding="utf-8")
pairs = [
 ("소정급여일수의 절반 이상 남기고 재취업하면 잔여분의 50% 지급",
  "신고일부터 14일이 지난 뒤 소정급여일수를 1/2 이상 남기고 재취업해 12개월 이상 고용되면 미지급일수의 1/2 지급 — 전 사업주 재고용·월 300만원 이상 임금(2026-11-01~) 등은 제외"),
 ("= 1일 수급액 × (잔여일수 ÷ 2) × 50%", "= 1일 수급액 × 미지급(잔여)일수 × 1/2"),
 ("조기수당: 68,100 × (150÷2) × 50% = 2,553,750원 (추가로 받음)", "조기수당: 68,100 × 150일 × 1/2 = 5,107,500원 (추가로 받음)"),
]
for old, new in pairs:
    assert s.count(old) == 1, (p, old[:30], s.count(old))
    s = s.replace(old, new)
p.write_text(s, encoding="utf-8"); print("ok", p)
EOF
done
sed -i '' "s/^const VERSION = 'v14-2026-11-12';/const VERSION = 'v15-2026-11-12';/" public/sw.js && grep -n "^const VERSION" public/sw.js
```
Expected: `ok` 2회, `const VERSION = 'v15-2026-11-12';`.

- [ ] **Step 4: 통과 확인**

Run: `cd /Users/zealnutkim/DEV/laborconsult-csa1 && /Users/zealnutkim/DEV/laborconsult/.venv/bin/python test_calculator_statute_audit.py 2>&1 | tail -3 && node --test test_public_fetch.js 2>&1 | grep -E "^# (pass|fail)"`
Expected: `OK` (11 tests), `# pass 9 / # fail 0`.

- [ ] **Step 5: 커밋**

```bash
cd /Users/zealnutkim/DEV/laborconsult-csa1 && git add public/calculator_flow/unemployment_benefit_calc.html wage_calculator/calculator_flow/unemployment_benefit_calc.html public/sw.js test_calculator_statute_audit.py && \
git commit -q -m "fix(flow): 실업급여 흐름도의 조기재취업 공식·예시를 미지급일수 × 1/2로(÷2×50% 절반 값 교정), 요건 설명 추가, sw v15

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: CI 등록·CLAUDE.md·CLI diff·PR-1

**Files:**
- Modify: `.github/workflows/tests.yml` (모듈별 회귀 단계 149~151행)
- Modify: `CLAUDE.md` (Wage Calculator 절, `**출산·가족휴가 급여의 지급 기간 근거는 ...**` bullet 앞)
- Modify: `docs/02-design/features/calculator-statute-audit.design.md` §7

- [ ] **Step 1: tests.yml**

`python3 test_wage_claims_update.py` 줄 뒤에 같은 들여쓰기로:

```yaml
          python3 test_calculator_statute_audit.py
```

- [ ] **Step 2: CLAUDE.md bullet 추가**

`- **출산·가족휴가 급여의 지급 기간 근거는 `maternity_leave.EI_LEAVE_BASIS` 단일 출처다**` bullet 바로 앞에:

```markdown
- **조기재취업수당은 구직급여일액 × 미지급일수 × 1/2이고 카드 값은 '절반 남긴 시점 기준' 하한이다**(고용보험법 시행령
  제85조①, calculator-statute-audit U1). 재취업일이 입력에 없어 발생 요건의 경계(소정급여일수 1/2 잔여)에서의 금액만 확정할 수
  있다 — 예전 카드는 그 하한을 '(최대)'라 불렀고 공개 흐름도는 '÷2 × 50%'로 절반 값을 예시했다. 요건(신고일 +14일 경과·12개월
  고용·65세 6개월·전 사업주 재고용 제외·고시 임금 이상 제외·2년 내 수령 이력)은 `_early_reemployment_note`가 안내만 하고
  판정하지 않는다. **고시 임금액은 효력 기간을 가진 표(`EARLY_REEMPLOYMENT_WAGE_CAPS`)로 둔다** — 제2026-71호(월 300만원)는
  2026-11-01~2029-10-31에만 적고, 밖이면 "고용노동부장관이 고시하는 임금액"으로 쓴다(기한 없는 상수는 끝난 고시를 조용히
  계속 적용한다). 실업급여 기준기간은 18개월(초단시간 24개월)이고 일용근로자 특례는 **없다**(제40조②) — '일용직은 1년'은 법에 없는
  값이었다. 일용근로자(`is_daily_worker`)에는 제40조①5호(근로일수 3분의 1 미만·건설일용 14일 연속 무근로)를 안내만 한다.
  회귀는 `test_calculator_statute_audit.py`.
```

- [ ] **Step 3: CLI diff 기록**

```bash
cd /Users/zealnutkim/DEV/laborconsult && ./.venv/bin/python wage_calculator_cli.py > /tmp/cli_main.txt 2>&1
cd /Users/zealnutkim/DEV/laborconsult-csa1 && /Users/zealnutkim/DEV/laborconsult/.venv/bin/python wage_calculator_cli.py > /tmp/cli_pr1.txt 2>&1
diff /tmp/cli_main.txt /tmp/cli_pr1.txt | grep -E "^[<>]" | grep -vE "조기재취업|상한액은 이직일|일용근로자 추가 요건|제84조|제64조|18개월 이내" | head
```
Expected: 마지막 명령 출력이 **비어 있다**(바뀐 줄이 전부 이번 변경의 문구). 비어 있지 않으면 그 줄의 사례를 Design §7에 이유와 함께 적거나 결함으로 고친다. Design §7에 "PR-1: 금액 변화 0건, 문구 변화 — 조기재취업 산식·안내(실업급여 사례 8건), 상한 경과조치 안내(이직일 2025 사례 N건)"를 기록한다.

- [ ] **Step 4: 전수 테스트**

```bash
cd /Users/zealnutkim/DEV/laborconsult-csa1 && PY=/Users/zealnutkim/DEV/laborconsult/.venv/bin/python; for t in test_wage_golden.py test_pipeline_wiring.py test_offline_units.py test_wage_update_2026.py test_calc_card_followups.py test_calc_card_consistency.py test_monthly_base_unification.py test_audit50.py test_unemployment_separation.py test_kin_accuracy.py test_claim_assessor_facts.py test_law_article_coverage.py test_effective_law.py test_calculator_statute_audit.py; do $PY $t > /tmp/csa_$t.log 2>&1; echo "$t exit=$?"; done; $PY -m unittest test_legal_rule_updates test_legal_rule_api 2>&1 | tail -1
```
Expected: 전부 `exit=0`, `OK`.

- [ ] **Step 5: 커밋·push·PR**

```bash
cd /Users/zealnutkim/DEV/laborconsult-csa1 && git add .github/workflows/tests.yml CLAUDE.md docs/02-design/features/calculator-statute-audit.design.md && \
git commit -q -m "docs: calculator-statute-audit 규칙(CLAUDE.md)·CI 등록·CLI 변경 사례 기록

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" && git push -u origin fix/calc-statute-audit-ei && \
gh pr create --base main --title "fix: 실업급여 계산기 — 조기재취업수당 산식·요건·고시, 기준기간 문구, 일용 수급요건 안내 (calculator-statute-audit PR-1)" --body-file - <<'EOF'
## 요약
Pinecone 신규 적재분(공식 자료팩 54·재결례 1,052·고시 14) × 계산기 대조 감사(Plan·Design 포함)의 PR-1 — 실업급여.

- **U1** 조기재취업수당: `(최대)` → 구직급여일액 × 미지급일수 × 1/2의 **하한**(절반 남긴 시점). 요건·제외(14일 경과·12개월 고용·65세 6개월·전 사업주·고시 임금 월 300만원(제2026-71호, 효력표)·2년 제한·청구 시기) 안내. 공개 흐름도의 `÷2 × 50%`(절반 값) 교정.
- **U2** 기준기간 문구의 법에 없는 '일용직 1년' 제거(18개월·초단시간 24개월, 제40조②).
- **U3** 일용근로자 수급요건(제40조①5호 3분의 1·건설일용 14일·대기기간 없음) 안내.
- 상한 경과조치(시행령 부칙 제35934호 제4조) 안내.
- 앵커 13·등록(시행령 제85·86조, 지급제외 임금액 고시) — `check_law_freshness --anchors` 순회 대상.

## 검증
- `test_calculator_statute_audit.py`(신규, CI 등록) + 기존 골든·배선·카드·앵커 테스트 통과.
- CLI 116사례: 금액 변화 0, 문구 변화만(Design §7).

## 데이터 발견(코드 범위 밖, Plan §2.4)
자료팩이 산식 이미지 조문 7건(시행령 제104조의2·제104조의15 포함)을 보류했고 스냅숏 이후 신설 19건이 없다 — 후속 `source-pack-refresh`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```
Expected: PR URL 출력. 이후 `gh pr checks <n> --watch`로 CI 확인 → 사용자 확인 뒤 `gh pr merge <n> --merge`.

---

## PR-2 — 산재

### Task 8: 작업 트리 + 보상기준 표·통상근로계수 상수

**Files:**
- Create worktree: `../laborconsult-csa2` (branch `fix/calc-statute-audit-iaci` from `origin/main` — PR-1 머지 뒤면 그 main)
- Modify: `wage_calculator/constants.py` (`MIN_COMPENSATION_DAILY` 블록 교체, 현재 591~607행 근처)
- Test: `test_calculator_statute_audit.py` (PR-1이 머지되지 않았으면 같은 내용의 파일을 새로 만든다 — 클래스 이름이 겹치지 않는다)

- [ ] **Step 1: 작업 트리**

```bash
cd /Users/zealnutkim/DEV/laborconsult && git fetch -q origin && git worktree add ../laborconsult-csa2 -b fix/calc-statute-audit-iaci origin/main && rsync -a output_공식법령/ ../laborconsult-csa2/output_공식법령/
```

- [ ] **Step 2: 실패하는 테스트 추가** (`test_calculator_statute_audit.py`, `if __name__` 앞. 파일이 없으면 Task 2의 머리말·import·`_unemp`까지 포함해 만든다)

```python
def _accident(**changes):
    inp = WageInput(monthly_wage=6_000_000, start_date="2020-01-01", end_date="2026-06-30",
                    accident_date="2026-03-01", reference_year=2026, reference_date="2026-11-12")
    for key, value in changes.items():
        setattr(inp, key, value)
    from wage_calculator.calculators.industrial_accident import calc_industrial_accident
    return calc_industrial_accident(inp, calc_ordinary_wage(copy.deepcopy(inp)))


class CompensationConstantsTests(unittest.TestCase):
    """D6 — 최고·최저 보상기준 표 하나, 최저 열은 파생. 통상근로계수 73/100."""

    def test_limits_table_and_derived_minimum(self):
        from wage_calculator.constants import COMPENSATION_LIMITS_DAILY, MIN_COMPENSATION_DAILY, ORDINARY_WORK_COEFFICIENT
        self.assertEqual(COMPENSATION_LIMITS_DAILY[2026], (268_299, 82_560))
        self.assertEqual(COMPENSATION_LIMITS_DAILY[2025], (None, 80_240))
        self.assertEqual(MIN_COMPENSATION_DAILY, {year: low for year, (_high, low) in COMPENSATION_LIMITS_DAILY.items()})
        self.assertEqual(ORDINARY_WORK_COEFFICIENT, 0.73)
```

- [ ] **Step 3: 실패 확인**

Run: `cd /Users/zealnutkim/DEV/laborconsult-csa2 && /Users/zealnutkim/DEV/laborconsult/.venv/bin/python test_calculator_statute_audit.py CompensationConstantsTests 2>&1 | tail -3`
Expected: `ImportError: cannot import name 'COMPENSATION_LIMITS_DAILY'`.

- [ ] **Step 4: 구현** — `constants.py`의

```python
# 연도별 1일 최저보상기준금액 (고용노동부 고시)
MIN_COMPENSATION_DAILY: dict[int, float] = {
    2024: 78_880,
    2025: 80_240,
    2026: 82_560,
}
```
을

```python
# ── 산재 최고·최저 보상기준 금액(산재보험법 제36조⑦·시행령 제26조, 고용노동부 고시, 1일) ──────────────────────
# {연도: (최고, 최저)}. 평균임금이 최고를 넘으면 최고, 최저에 못 미치면 최저가 평균임금이 된다 — 장례비는 제외, 휴업급여·
# 상병보상연금에는 최저를 적용하지 않는다(제36조⑦ 단서). 최저가 최저임금액(시급×8)보다 적으면 최저임금액이 최저가 된다
# (제36조⑦ 후단) — 2026년은 82,560 = 10,320×8로 같다. 최고를 모르는 연도는 None — 그 해는 최고 상한을 걸지 않고 경고한다
# (없는 값을 다른 해 값으로 폴백하지 않는다). 2026: 고용노동부고시 제2025-84호(2026-01-01~12-31). 2024·2025 최고는 미수집
# (calculator-statute-audit D6).
COMPENSATION_LIMITS_DAILY: dict[int, tuple[float | None, float]] = {
    2024: (None, 78_880),
    2025: (None, 80_240),
    2026: (268_299, 82_560),
}
# 파생 — 휴업급여 저소득 보정(제54조)이 읽는 최저 열. 같은 숫자를 두 곳에 적지 않는다(직접 편집하지 말 것)
MIN_COMPENSATION_DAILY: dict[int, float] = {year: low for year, (_high, low) in COMPENSATION_LIMITS_DAILY.items()}

# 일용근로자 평균임금 = 일당 × 통상근로계수(산재보험법 제36조⑤·시행령 제23조·제24조①1호, 고용노동부고시 제2025-90호)
ORDINARY_WORK_COEFFICIENT = 0.73
```
으로.

- [ ] **Step 5: 통과 확인 + 커밋**

```bash
cd /Users/zealnutkim/DEV/laborconsult-csa2 && /Users/zealnutkim/DEV/laborconsult/.venv/bin/python test_calculator_statute_audit.py CompensationConstantsTests 2>&1 | tail -1 && \
git add wage_calculator/constants.py test_calculator_statute_audit.py && git commit -q -m "feat(calc): 산재 최고·최저 보상기준 표(2026 고시 제2025-84호 268,299/82,560)와 통상근로계수 73/100 상수

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```
Expected: `OK`.

---

### Task 9: I1·I3 — 휴업급여 3일 단서와 61세 이후 감액

**Files:**
- Modify: `wage_calculator/calculators/industrial_accident.py` (`_calc_sick_leave` 254~301행, 호출부 164~173행, import)
- Test: `test_calculator_statute_audit.py`

- [ ] **Step 1: 실패하는 테스트 추가**

```python
class SickLeaveTests(unittest.TestCase):
    """D4 3일 단서 · D7 61세 이후 별표 1 계수(산정 경로별)."""

    def _sick(self, avg, days, age=0, year=2026):
        from wage_calculator.calculators.industrial_accident import _calc_sick_leave
        return _calc_sick_leave(avg, days, year, age=age)

    def test_three_days_or_less_pays_nothing_and_points_to_employer(self):
        daily, total, _, formulas, _, legal = self._sick(200_000, 3)
        self.assertEqual((daily, total), (0.0, 0.0))
        self.assertTrue(any("제52조 단서" in f and "제79조" in f for f in formulas), formulas)
        self.assertIn("근로기준법 제78조·제79조 (사용자의 요양보상·휴업보상)", legal)
        daily4, *_ = self._sick(200_000, 4)
        self.assertEqual(daily4, 140_000)

    def test_senior_factor_on_the_70_percent_route(self):
        self.assertEqual(self._sick(200_000, 10, age=61)[0], round(140_000 * 66 / 70))
        self.assertEqual(self._sick(200_000, 10, age=65)[0], round(140_000 * 50 / 70))
        self.assertEqual(self._sick(200_000, 10, age=70)[0], round(140_000 * 50 / 70))
        self.assertEqual(self._sick(200_000, 10, age=60)[0], 140_000)
        self.assertEqual(self._sick(200_000, 10, age=0)[0], 140_000)

    def test_senior_factor_on_the_minimum_standard_route(self):
        # 93,000 × 70% = 65,100 ≤ 66,048(최저 82,560 × 80%) → 90% = 83,700 > 66,048 → 제54조① 단서 = 66,048 → 62세 × 82/90
        daily, *_ , formulas, warnings, legal = self._sick(93_000, 10, age=62)
        self.assertEqual(daily, round(66_048 * 82 / 90))
        self.assertTrue(any("별표 1" in f for f in formulas))
        self.assertTrue(any("61세 이후" in w for w in warnings))
        self.assertIn("산업재해보상보험법 제55조·별표 1 (고령자의 휴업급여)", legal)

    def test_senior_factor_on_the_minimum_wage_route(self):
        # 60,000 × 70% = 42,000 → 90% = 54,000 ≤ 66,048 → 54,000 < 최저임금액 82,560 → 제54조② → 63세 × 78/90
        daily, *_ = self._sick(60_000, 10, age=63)
        self.assertEqual(daily, round(82_560 * 78 / 90))

    def test_card_passes_age_and_days_through(self):
        res = _accident(sick_leave_days=2)
        self.assertEqual(res.sick_leave_total, 0)
        self.assertTrue(any("제52조 단서" in f for f in res.formulas))
        res61 = _accident(sick_leave_days=30, age=61)
        self.assertTrue(any("고령자 감액(만 61세)" in f for f in res61.formulas), res61.formulas)
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/zealnutkim/DEV/laborconsult-csa2 && /Users/zealnutkim/DEV/laborconsult/.venv/bin/python test_calculator_statute_audit.py SickLeaveTests 2>&1 | tail -3`
Expected: `FAILED (errors=5)` — `_calc_sick_leave() got an unexpected keyword argument 'age'`.

- [ ] **Step 3: 구현**

(a) `_calc_sick_leave` 전체 교체:

```python
# 61세 이후 휴업급여 계수(산재보험법 제55조·별표 1) — {연령: (제52조 기준 n/70, 제54조 기준 n/90)}, 65세 이후는 (50, 70)
_SENIOR_FACTORS: dict[int, tuple[int, int]] = {61: (66, 86), 62: (62, 82), 63: (58, 78), 64: (54, 74)}
_SENIOR_FACTOR_65 = (50, 70)


def _senior_factor(age: int) -> tuple[int, int] | None:
    """만 나이가 61세 이상이면 별표 1 계수 (n70, n90). 모르거나(0) 60세 이하면 None."""
    if not age or age < 61:
        return None
    return _SENIOR_FACTORS.get(age, _SENIOR_FACTOR_65)


def _calc_sick_leave(
    avg_daily: float, days: int, year: int, age: int = 0
) -> tuple[float, float, bool, list[str], list[str], list[str]]:
    """
    휴업급여 계산 (산재보험법 제52조·제54조·제55조)

    Returns: (1일 지급액, 총액, 최저보상기준 적용 여부, formulas, warnings, legal)

    1단계: 요양 3일 이내면 미지급(제52조 단서) — 사용자의 요양보상·휴업보상(근로기준법 제78조·제79조)
    2단계: avg_daily × 70% (제52조)
    3단계: 결과 ≤ 최저보상기준 × 80% → avg_daily × 90% (제54조① 본문); 90%가 최저보상기준 × 80%보다 많으면 최저보상기준 × 80% (제54조① 단서)
    4단계: 위 금액 < 최저임금액(시급 × 8) → 최저임금액 (제54조②)
    5단계: 61세 이후면 별표 1 계수 — 제52조 기준은 n/70, 제54조 기준은 n/90(단서 기준은 최저보상 × 80% × n/90).
          제52조 기준 금액이 제3호(단서 기준) 금액보다 적으면 제3호 금액(별표 1 제1호 단서)
    avg_daily는 호출부가 최고 보상기준으로 자른 값이다(제36조⑦ — 최저 보상기준은 휴업급여에 적용하지 않는다).
    """
    formulas: list[str] = []
    warnings: list[str] = []
    legal: list[str] = []
    if days <= 3:
        formulas.append(
            f"휴업급여: 취업하지 못한 기간 {days}일 ≤ 3일 → 산재 휴업급여 미지급(산재보험법 제52조 단서). "
            "이 기간은 사업주가 요양보상·휴업보상(평균임금의 60%)을 합니다(근로기준법 제78조·제79조)"
        )
        legal.append("근로기준법 제78조·제79조 (사용자의 요양보상·휴업보상)")
        return 0.0, 0.0, False, formulas, warnings, legal

    min_comp_applied = False
    base = avg_daily * SICK_LEAVE_RATE  # 70%
    min_comp = MIN_COMPENSATION_DAILY.get(year, MIN_COMPENSATION_DAILY[max(MIN_COMPENSATION_DAILY.keys())])
    min_comp_80 = min_comp * MIN_COMP_THRESHOLD
    min_wage_daily = get_minimum_hourly_wage(year) * 8

    daily = base
    route = "base70"                       # 제52조
    formulas.append(f"기본 휴업급여: {avg_daily:,.0f}원 × 70% = {base:,.0f}원")

    if base <= min_comp_80:
        daily_90 = avg_daily * SICK_LEAVE_LOW_RATE
        if daily_90 > min_comp_80:
            daily = min_comp_80
            route = "low_min80"            # 제54조① 단서
            formulas.append(f"90%({daily_90:,.0f}원) > 최저보상기준 80%({min_comp_80:,.0f}원) → 최저보상기준 80% 적용")
        else:
            daily = daily_90
            route = "low90"                # 제54조① 본문
            formulas.append(f"90%({daily_90:,.0f}원) ≤ 최저보상기준 80%({min_comp_80:,.0f}원) → 90% 적용")
        min_comp_applied = True

    if daily < min_wage_daily:
        daily = min_wage_daily
        route = "min_wage"                 # 제54조②
        formulas.append(f"최저임금 일급({min_wage_daily:,.0f}원) 하한 적용")
        min_comp_applied = True

    factor = _senior_factor(age)
    if factor:
        n70, n90 = factor
        if route == "base70":
            reduced = daily * n70 / 70
            floor3 = min_comp_80 * n90 / 90          # 별표 1 제1호 단서 — 제3호 금액보다 적으면 제3호
            daily, label = max(reduced, floor3), f"{n70}/70"
        else:
            daily, label = daily * n90 / 90, f"{n90}/90"
        formulas.append(f"고령자 감액(만 {age}세): 1일 휴업급여 × {label} = {daily:,.0f}원 (산재보험법 제55조·별표 1)")
        warnings.append(
            f"61세 이후 휴업급여는 별표 1에 따라 감액됩니다(만 {age}세 계수 {label}). 각 연령에 도달하는 날부터 계수가 바뀌며, "
            "61세 이후 취업 중 재해 등 제55조 단서 사유는 일정 기간 감액하지 않습니다."
        )
        legal.append("산업재해보상보험법 제55조·별표 1 (고령자의 휴업급여)")

    daily = round(daily)
    total = daily * days
    formulas.append(f"휴업급여 총액: {daily:,.0f}원 × {days}일 = {total:,.0f}원")
    return daily, total, min_comp_applied, formulas, warnings, legal
```

(b) import 블록을

```python
from ..constants import (
    MINIMUM_HOURLY_WAGE,
    DISABILITY_GRADE_TABLE,
    SEVERE_ILLNESS_DAYS,
    SURVIVOR_BASE_RATIO,
    SURVIVOR_ADD_RATIO,
    SURVIVOR_MAX_RATIO,
    SURVIVOR_LUMP_SUM_DAYS,
    FUNERAL_DAYS,
    FUNERAL_LIMITS,
    SICK_LEAVE_RATE,
    SICK_LEAVE_LOW_RATE,
    MIN_COMP_THRESHOLD,
    MIN_COMPENSATION_DAILY,
    COMPENSATION_LIMITS_DAILY,
    ORDINARY_WORK_COEFFICIENT,
    get_minimum_hourly_wage,
)
```
으로 바꾸고, 기존 `_calc_sick_leave` 안의 `from ..constants import get_minimum_hourly_wage` 지역 import는 지운다(위 교체본에 없다).

(c) 호출부(2. 휴업급여) 교체:

```python
    # ── 2. 휴업급여 ───────────────────────────────────────────────────────
    sl_daily, sl_total, sl_min = 0.0, 0.0, False
    if inp.sick_leave_days > 0:
        sl_daily, sl_total, sl_min, sl_f, sl_w, sl_l = _calc_sick_leave(
            avg_capped, inp.sick_leave_days, year, age=getattr(inp, "age", 0) or 0
        )
        total_compensation += sl_total
        formulas.extend(sl_f)
        warnings.extend(sl_w)
        legal.extend(l for l in sl_l if l not in legal)
        breakdown["휴업급여"] = (
            f"{sl_daily:,.0f}원/일 × {inp.sick_leave_days}일 = {sl_total:,.0f}원"
            if sl_total else f"0원 (요양 {inp.sick_leave_days}일 ≤ 3일 — 제52조 단서)"
        )
```
`avg_capped`는 Task 10에서 정의한다 — Task 10 전까지는 이 줄을 `avg_daily`로 두고 Task 10에서 바꾼다. (한 커밋으로 묶으려면 Task 10까지 한 뒤 테스트를 돈다.)

- [ ] **Step 4: 통과 확인** (Task 10까지 적용한 뒤 실행해도 된다 — 단독으로 확인하려면 호출부의 `avg_capped`를 잠시 `avg_daily`로)

Run: `cd /Users/zealnutkim/DEV/laborconsult-csa2 && /Users/zealnutkim/DEV/laborconsult/.venv/bin/python test_calculator_statute_audit.py SickLeaveTests 2>&1 | tail -3`
Expected: `OK` (5 tests).

- [ ] **Step 5: 커밋**

```bash
cd /Users/zealnutkim/DEV/laborconsult-csa2 && git add wage_calculator/calculators/industrial_accident.py test_calculator_statute_audit.py && \
git commit -q -m "fix(calc): 산재 휴업급여 — 요양 3일 이내 미지급(제52조 단서, 사업주 보상 안내)·61세 이후 별표 1 계수를 산정 경로별로(제55조)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: I2 — 최고·최저 보상기준을 급여별로 적용

**Files:**
- Modify: `wage_calculator/calculators/industrial_accident.py` (평균임금 결정 뒤 ~157행, 급여 호출부 164~210행, 헬퍼)
- Test: `test_calculator_statute_audit.py`

- [ ] **Step 1: 실패하는 테스트 추가**

```python
class CompensationLimitTests(unittest.TestCase):
    """D5 — 최고는 장례비 외 전 급여, 최저는 장해·유족만(제36조⑦)."""

    def test_high_wage_is_capped_for_disability_and_sick_leave_but_not_funeral(self):
        res = _accident(monthly_wage=12_000_000, sick_leave_days=30, disability_grade=7, disability_pension=False,
                        is_deceased=True, num_survivors=0)
        self.assertGreater(res.avg_daily_wage, 268_299)
        self.assertEqual(res.disability_amount, round(268_299 * 616, 0))
        self.assertEqual(res.sick_leave_daily, round(268_299 * 0.7))
        self.assertEqual(res.funeral_amount, 19_279_760)        # 120일분이 최고액을 넘어 장례비 자체 최고액
        self.assertTrue(any("최고 보상기준 금액 적용" in f for f in res.formulas), res.formulas)
        self.assertIn("산업재해보상보험법 제36조 제7항 (최고·최저 보상기준 금액)", res.legal_basis)

    def test_low_wage_is_floored_for_disability_only(self):
        res = _accident(monthly_wage=1_500_000, sick_leave_days=30, disability_grade=14, disability_pension=False)
        self.assertLess(res.avg_daily_wage, 82_560)
        self.assertEqual(res.disability_amount, round(82_560 * 55, 0))
        self.assertEqual(res.sick_leave_daily, 82_560)           # 최저임금액 하한(제54조②) — 최저 보상기준이 아니다
        self.assertTrue(any("최저 보상기준 금액 적용" in f and "장해·유족" in f for f in res.formulas), res.formulas)

    def test_unknown_high_limit_year_warns_instead_of_capping(self):
        res = _accident(monthly_wage=12_000_000, disability_grade=7, disability_pension=False,
                        reference_year=2025, reference_date="2025-06-01", accident_date="2025-03-01")
        self.assertEqual(res.disability_amount, round(res.avg_daily_wage * 616, 0))
        self.assertTrue(any("최고 보상기준 금액을 확인하지 못했습니다" in w for w in res.warnings), res.warnings)

    def test_middle_wage_applies_no_limit(self):
        res = _accident(monthly_wage=4_000_000, disability_grade=10, disability_pension=False, sick_leave_days=20)
        self.assertFalse(any("보상기준 금액 적용" in f for f in res.formulas))
        self.assertEqual(res.disability_amount, round(res.avg_daily_wage * 297, 0))
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/zealnutkim/DEV/laborconsult-csa2 && /Users/zealnutkim/DEV/laborconsult/.venv/bin/python test_calculator_statute_audit.py CompensationLimitTests 2>&1 | tail -3`
Expected: `FAILED (failures=3)`(또는 Task 9 호출부의 `avg_capped` NameError).

- [ ] **Step 3: 구현**

(a) 헬퍼(`_calc_sick_leave` 앞):

```python
def _compensation_limits(year: int) -> tuple[float | None, float]:
    """(최고, 최저) 보상기준 금액. 최저는 최저임금액(시급 × 8)과 비교해 큰 쪽(제36조⑦ 후단). 표에 없는 해는 (None, 최저임금액)."""
    high, low = COMPENSATION_LIMITS_DAILY.get(year, (None, 0.0))
    return high, max(float(low), get_minimum_hourly_wage(year) * 8)
```

(b) 평균임금 결정 블록 끝(`if inp.accident_date: legal.append(...)` 뒤, `total_compensation = 0.0` 앞)에:

```python
    # ── 1-2. 최고·최저 보상기준(제36조⑦) — 장례비 외 급여의 평균임금 상한, 장해·유족급여의 하한 ────────────────────
    # 휴업급여·상병보상연금에는 최저를 적용하지 않는다(단서). 장례비는 자체 최고·최저(제71조②)가 있어 제외다.
    comp_high, comp_low = _compensation_limits(year)
    avg_capped = avg_daily
    if comp_high is not None and avg_daily > comp_high:
        avg_capped = comp_high
        formulas.append(
            f"최고 보상기준 금액 적용: 평균임금 {avg_daily:,.0f}원 > {comp_high:,.0f}원 → 휴업·장해·유족·상병보상연금은 "
            f"{comp_high:,.0f}원으로 산정(산재보험법 제36조 제7항, 장례비 제외)"
        )
        legal.append("산업재해보상보험법 제36조 제7항 (최고·최저 보상기준 금액)")
    elif comp_high is None and avg_daily > comp_low * 3.6:
        # 최고/최저 = 1.8배 ÷ 1/2 = 3.6배(제36조⑦) — 최저만 아는 해에 최고를 넘었을 가능성이 큰 구간만 알린다
        warnings.append(
            f"{year}년 최고 보상기준 금액을 확인하지 못했습니다 — 평균임금이 전체 근로자 임금 평균액의 1.8배를 넘으면 그 금액으로 "
            "제한됩니다(산재보험법 제36조 제7항). 이 카드는 상한 없이 계산했습니다."
        )
    avg_floor = avg_capped
    if avg_capped < comp_low:
        avg_floor = comp_low
        formulas.append(
            f"최저 보상기준 금액 적용: 평균임금 {avg_daily:,.0f}원 < {comp_low:,.0f}원 → 장해·유족급여는 {comp_low:,.0f}원으로 "
            "산정(산재보험법 제36조 제7항 — 휴업급여·상병보상연금에는 적용하지 않음)"
        )
        if "산업재해보상보험법 제36조 제7항 (최고·최저 보상기준 금액)" not in legal:
            legal.append("산업재해보상보험법 제36조 제7항 (최고·최저 보상기준 금액)")
```

(c) `breakdown: dict = {"적용 평균임금": f"{avg_daily:,.0f}원/일"}` 를

```python
    breakdown: dict = {"적용 평균임금": f"{avg_daily:,.0f}원/일"
                       + (f" (휴업·상병 {avg_capped:,.0f}원, 장해·유족 {avg_floor:,.0f}원 — 보상기준 적용)"
                          if (avg_capped, avg_floor) != (avg_daily, avg_daily) else "")}
```
으로.

(d) 호출부 인자 — 상병보상연금 `_calc_illness_pension(avg_capped, ...)`, 장해 `_calc_disability(avg_floor, ...)`, 유족 `_calc_survivor(avg_floor, ...)`, 장례비 `_calc_funeral(avg_daily, year)`(그대로), 휴업급여는 Task 9의 `avg_capped`.

- [ ] **Step 4: 통과 확인**

Run: `cd /Users/zealnutkim/DEV/laborconsult-csa2 && /Users/zealnutkim/DEV/laborconsult/.venv/bin/python test_calculator_statute_audit.py 2>&1 | tail -3`
Expected: `OK`.

- [ ] **Step 5: 커밋**

```bash
cd /Users/zealnutkim/DEV/laborconsult-csa2 && git add wage_calculator/calculators/industrial_accident.py test_calculator_statute_audit.py && \
git commit -q -m "fix(calc): 산재 최고·최저 보상기준(제36조⑦)을 평균임금 단계에서 급여별 적용 — 장해·유족 최고·최저, 휴업·상병 최고만, 장례비 제외

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: I4·I5 — 일용근로자 통상근로계수, 직업병 특례 안내

**Files:**
- Modify: `wage_calculator/calculators/industrial_accident.py` (평균임금 결정 블록 뒤·1-2 앞, 재해 유형 안내 뒤)
- Test: `test_calculator_statute_audit.py`

- [ ] **Step 1: 실패하는 테스트 추가**

```python
class DailyWorkerAndDiseaseTests(unittest.TestCase):
    """D8 일당 × 통상근로계수(3개월 미만일 때만) · D9 직업병 특례 안내."""

    def test_daily_worker_average_wage_uses_the_coefficient(self):
        res = _accident(wage_type=WageType.DAILY, monthly_wage=None, daily_wage=150_000, is_daily_worker=True,
                        start_date="2026-01-15", accident_date="2026-03-01", end_date="2026-03-01",
                        disability_grade=14, disability_pension=False)
        self.assertEqual(res.avg_daily_wage, 109_500)
        self.assertTrue(any("통상근로계수 73/100" in f for f in res.formulas), res.formulas)
        self.assertTrue(any("3개월 이상 계속" in w for w in res.warnings))
        self.assertIn("산업재해보상보험법 제36조 제5항·시행령 제23조·제24조 (일용근로자 평균임금 — 통상근로계수)", res.legal_basis)

    def test_daily_worker_with_three_months_of_service_keeps_ordinary_average(self):
        res = _accident(wage_type=WageType.DAILY, monthly_wage=None, daily_wage=150_000, is_daily_worker=True,
                        start_date="2025-10-01", accident_date="2026-03-01", end_date="2026-03-01",
                        disability_grade=14, disability_pension=False)
        self.assertFalse(any("통상근로계수 73/100 =" in f for f in res.formulas))
        self.assertTrue(any("단서 가목" in w for w in res.warnings), res.warnings)

    def test_daily_worker_without_daily_wage_is_only_told(self):
        res = _accident(is_daily_worker=True, disability_grade=14, disability_pension=False)
        self.assertTrue(any("일당을 알면" in w for w in res.warnings), res.warnings)

    def test_occupational_disease_gets_the_special_average_note(self):
        res = _accident(injury_type="질병", sick_leave_days=30)
        self.assertTrue(any("제36조 제6항" in w and "시행령 제25조" in w for w in res.warnings), res.warnings)
        self.assertIn("산업재해보상보험법 제36조 제6항·시행령 제25조 (직업병 평균임금 산정 특례)", res.legal_basis)
        self.assertFalse(any("제36조 제6항" in w for w in _accident(injury_type="사고", sick_leave_days=30).warnings))
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/zealnutkim/DEV/laborconsult-csa2 && /Users/zealnutkim/DEV/laborconsult/.venv/bin/python test_calculator_statute_audit.py DailyWorkerAndDiseaseTests 2>&1 | tail -3`
Expected: `FAILED (failures=4)`(일당 입력 사례는 `avg.held_reason`로 빈 결과가 올 수도 있다 — 그러면 `assertEqual(res.avg_daily_wage, 109_500)`이 실패한다. 아래 구현이 `held_reason` 분기 앞에서 일용 경로를 처리하는 이유다).

- [ ] **Step 3: 구현**

(a) 헬퍼(`_compensation_limits` 옆):

```python
def _continued_three_months(inp: WageInput) -> bool:
    """입사일과 재해일(없으면 퇴직일)이 있고 그 사이가 3개월 이상이면 True — 시행령 제23조①1호 단서 가목(일용으로 보지 않음)."""
    end = inp.accident_date or inp.end_date
    if not inp.start_date or not end:
        return False
    from .shared import DateRange
    return DateRange(inp.start_date, end).months_approx >= 3
```

(b) 평균임금 결정 블록을 다음으로 교체(기존 `avg = calc_average_wage(...)`부터 `legal.append("근로기준법 시행령 제52조 ...")`까지):

```python
    # ── 1. 평균임금 결정 ──────────────────────────────────────────────────
    # 산재보험의 평균임금은 근로기준법의 평균임금이다(산재보험법 제5조 제2호) — 평균임금 계산기 하나로 구한다(monthly-base-unification).
    # 분모는 3개월 총일수(근로기준법 제2조 제1항 제6호), 평균임금이 통상임금보다 적으면 통상임금(제2조 제2항). 산정 사유 발생일은
    # 사고가 발생한 날이다(근로기준법 시행령 제52조). 예전에는 '월 금액 ÷ 30'과 1일 통상임금 중 큰 쪽이었다
    is_daily = bool(getattr(inp, "is_daily_worker", False))
    daily_wage = getattr(inp, "daily_wage", None)
    use_coefficient = is_daily and bool(daily_wage) and not _continued_three_months(inp)
    if use_coefficient:
        # 1-1. 일용근로자: 일당 × 통상근로계수(제36조⑤, 시행령 제23조·제24조①1호, 고용노동부고시 제2025-90호 73/100 —
        #      calculator-statute-audit D8). 3개월 이상 계속 근로면 일용으로 보지 않아 일반 평균임금(제23조①1호 단서 가목)
        avg_daily = float(daily_wage) * ORDINARY_WORK_COEFFICIENT
        formulas.append(f"평균임금(일용근로자): 일당 {float(daily_wage):,.0f}원 × 통상근로계수 73/100 = {avg_daily:,.0f}원 "
                        "(산재보험법 제36조 제5항, 시행령 제23조·제24조, 고용노동부고시 제2025-90호)")
        warnings.append("근로관계가 3개월 이상 계속되거나 근로 형태가 상용근로자와 비슷하면 일용근로자로 보지 않고 일반 평균임금으로 "
                        "산정합니다(시행령 제23조 제1항 제1호 단서). 1개월 이상 근로한 일용근로자는 실제 임금·근로일수로 적용 "
                        "제외를 신청할 수 있습니다(제24조 제2항).")
        legal.append("산업재해보상보험법 제36조 제5항·시행령 제23조·제24조 (일용근로자 평균임금 — 통상근로계수)")
    else:
        avg = calc_average_wage(replace(inp, end_date=inp.accident_date or inp.end_date), ow)
        if avg.held_reason:
            return IndustrialAccidentResult(held_reason=avg.held_reason, warnings=avg.warnings)
        avg_daily = avg.avg_daily_wage
        if avg.used_basis == "통상임금":
            formulas.append(f"평균임금: {avg_daily:,.0f}원/일 (3개월 평균임금 {avg.avg_daily_3m:,.0f}원 < 1일 통상임금 "
                            f"{avg.avg_daily_ordinary:,.0f}원 → 통상임금, 근로기준법 제2조 제2항)")
            legal.append("근로기준법 제2조 제2항 (평균임금이 통상임금보다 적으면 통상임금)")
        else:
            formulas.append(f"평균임금: {avg_daily:,.0f}원/일 (3개월 기준)")
        if is_daily and not daily_wage:
            warnings.append("일용근로자의 산재 평균임금은 일당 × 통상근로계수(73/100)로 산정합니다(시행령 제24조 제1항 제1호) — "
                            "일당을 알면 그 기준으로 계산합니다. 이 카드는 일반 평균임금입니다.")
        elif is_daily:
            warnings.append("근로관계가 3개월 이상 계속돼 일용근로자 특례(통상근로계수)를 적용하지 않고 일반 평균임금으로 산정했습니다"
                            "(시행령 제23조 제1항 제1호 단서 가목).")
    if inp.accident_date:
        legal.append("근로기준법 시행령 제52조 (재해보상 시의 평균임금 산정 사유 발생일)")
```

(c) 재해 유형 안내 블록 끝(`if injury_type == "뇌심혈관": ...` 뒤)에:

```python
    if injury_type in ("질병", "뇌심혈관"):
        # 직업병 평균임금 특례(제36조⑥·시행령 제25조) — 진폐는 고시 금액, 그 밖은 비슷한 근로자의 월평균 임금총액. 공단이 적용하고
        # 계산기는 재현할 수 없어 안내만 한다(calculator-statute-audit D9)
        warnings.append("직업병(진폐 등)은 공단이 평균임금 산정 특례를 적용할 수 있습니다 — 진폐는 매년 고시하는 금액, 그 밖의 직업병은 "
                        "성별·직종·업종·규모가 비슷한 근로자의 월평균 임금총액 기준(산재보험법 제36조 제6항, 시행령 제25조). "
                        "이 카드는 일반 평균임금으로 계산했습니다.")
        legal.append("산업재해보상보험법 제36조 제6항·시행령 제25조 (직업병 평균임금 산정 특례)")
```

- [ ] **Step 4: 통과 확인 + 기존 회귀**

```bash
cd /Users/zealnutkim/DEV/laborconsult-csa2 && PY=/Users/zealnutkim/DEV/laborconsult/.venv/bin/python; $PY test_calculator_statute_audit.py 2>&1 | tail -1; for t in test_wage_golden.py test_pipeline_wiring.py test_audit50.py test_monthly_base_unification.py test_calc_card_consistency.py; do $PY $t > /tmp/csa2_$t.log 2>&1; echo "$t exit=$?"; done
```
Expected: `OK`, 전부 `exit=0`. `test_audit50.py`의 산재 '월급 = 총액' 대조(`KEPT_ORDINARY_READERS`)가 실패하면 그 테스트의 입력이 보상기준에 걸린 것인지 확인한다 — 걸렸다면 테스트 입력이 아니라 기대값 쪽 변화가 정당한지 Design §7에 적는다.

- [ ] **Step 5: 커밋**

```bash
cd /Users/zealnutkim/DEV/laborconsult-csa2 && git add wage_calculator/calculators/industrial_accident.py test_calculator_statute_audit.py && \
git commit -q -m "fix(calc): 산재 일용근로자 평균임금 = 일당 × 통상근로계수 73/100(3개월 미만일 때만, 시행령 제23조·제24조)·직업병 평균임금 특례 안내(제36조⑥)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 12: 등록·앵커·원문 수집 (PR-2)

**Files:**
- Modify: `fetch_official_rules.py` (`ARTICLES`·`ANNEXES`·`ADMRULS`·`ADMRUL_LAW_GO_KR_ONLY`)
- Modify: `wage_calculator/legal_anchors.py`

- [ ] **Step 1: 앵커 추가** (`CALC_BASIS_ANCHORS` 끝)

```python
    # 산재 — 3일 단서·사용자 보상(industrial_accident.py, calculator-statute-audit I1)
    ("iaci_act_52", "취업하지 못한 기간이 3일 이내이면 지급하지 아니한다"),
    ("lsa_act_79", "평균임금의 100분의 60의 휴업보상"),
    # 최고·최저 보상기준(I2)
    ("iaci_act_36", "보험급여(장례비는 제외한다)를 산정할 때"),
    ("iaci_act_36", "상용근로자 5명 이상 사업체의 전체 근로자의 임금 평균액의 1.8배"),
    ("iaci_act_36", "시간급 최저임금액에 8을 곱한 금액"),
    ("iaci_act_36", "휴업급여 및 상병보상연금을 산정할 때에는 최저 보상기준 금액을 적용하지 아니한다"),
    ("iaci_comp_limits", "최고 보상기준 금액은 1일 268,299원으로 하고, 최저 보상기준 금액은 1일 82,560원으로 한다"),
    ("iaci_funeral_limits", "장례비 최고금액은 19,279,760원으로 하고, 장례비 최저금액은 13,943,000원으로 한다"),
    # 61세 이후 감액(I3)
    ("iaci_act_55", "61세가 되면 그 이후의 휴업급여는 별표 1에 따라"),
    ("iaci_annex1", "1일당 휴업급여 지급액 × 66/70"),
    ("iaci_annex1", "최저 보상기준 금액 × 80/100 × 86/90"),
    # 일용근로자 통상근로계수(I4)
    ("iaci_enf_23", "근로관계가 3개월 이상 계속되는 경우"),
    ("iaci_enf_24", "고용노동부장관이 고시하는 근로계수"),
    ("iaci_enf_24", "산정 방법의 적용 제외를 신청할 수 있다"),
    ("iaci_ordinary_coeff", "통상근로계수는 73/100으로 한다"),
    # 직업병 특례(I5)
    ("iaci_act_36", "진폐 등 대통령령으로 정하는 직업병으로 보험급여를 받게 되는 근로자에게"),
    ("iaci_enf_25", "성별ㆍ직종 및 소속한 사업의 업종ㆍ규모가 비슷한 근로자의 월평균 임금총액"),
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/zealnutkim/DEV/laborconsult-csa2 && /Users/zealnutkim/DEV/laborconsult/.venv/bin/python test_wage_update_2026.py CalcBasisAnchorTests 2>&1 | grep -E "not found|OK|FAIL" | head -3`
Expected: `'iaci_act_52' not found`.

- [ ] **Step 3: 등록**

`ARTICLES` 끝(PR-1의 `ei_enf_86` 뒤, 없으면 `lsa_act_60` 뒤)에:

```python
    # 산재 계산기 근거(industrial_accident.py — calculator-statute-audit I1~I5): 3일 단서·사용자 휴업보상·최고·최저 보상기준·
    # 고령자 휴업급여·일용근로자 통상근로계수·직업병 특례. 앵커 전용(keys 없음)
    ("iaci_act_36",   "산업재해보상보험법",              36,  None, []),
    ("iaci_act_52",   "산업재해보상보험법",              52,  None, []),
    ("iaci_act_54",   "산업재해보상보험법",              54,  None, []),
    ("iaci_act_55",   "산업재해보상보험법",              55,  None, []),
    ("iaci_enf_23",   "산업재해보상보험법 시행령",        23,  None, []),
    ("iaci_enf_24",   "산업재해보상보험법 시행령",        24,  None, []),
    ("iaci_enf_25",   "산업재해보상보험법 시행령",        25,  None, []),
    ("lsa_act_79",    "근로기준법",                     79,  None, []),
```

`ANNEXES`에(`ei_rule_annex1_2` 뒤, 닫는 `]` 앞 — 현재 `"별표1의2"),]`로 붙어 있으니 줄을 나눈다):

```python
    # 고령자의 휴업급여 지급기준(산재보험법 제55조 위임) — 61세 이후 계수표의 앵커(calculator-statute-audit I3)
    ("iaci_annex1",      "산업재해보상보험법",   "고령자의 휴업급여 지급기준",                       "별표1"),
```

`ADMRULS` 끝에:

```python
    # 산재 급여 산정 고시 3건(2026-01-01~12-31, 고용노동부고시 제2025-84·85·90호) — 보상기준 표·장례비 표·통상근로계수의 출처
    # (calculator-statute-audit D6·D8). 앵커 전용(keys 없음), 법제처 통합본으로만 받는다
    ("iaci_comp_limits",    "최고·최저 보상기준 금액", "최고·최저 보상기준 금액", "고용노동부", []),
    ("iaci_funeral_limits", "장례비 최고·최저 금액",   "장례비 최고·최저 금액",   "고용노동부", []),
    ("iaci_ordinary_coeff", "통상근로계수",           "통상근로계수",           "고용노동부", []),
```

`ADMRUL_LAW_GO_KR_ONLY`에 세 doc_id 추가.

- [ ] **Step 4: 수집·대조**

```bash
cd /Users/zealnutkim/DEV/laborconsult-csa2 && PY=/Users/zealnutkim/DEV/laborconsult/.venv/bin/python; $PY fetch_official_rules.py --doc iaci_act_36 --doc iaci_act_52 --doc iaci_act_54 --doc iaci_act_55 --doc iaci_enf_23 --doc iaci_enf_24 --doc iaci_enf_25 --doc lsa_act_79 --doc iaci_annex1 --doc iaci_comp_limits --doc iaci_funeral_limits --doc iaci_ordinary_coeff 2>&1 | tail -14; ls output_공식법령/ | grep -cE "^iaci_|^lsa_act_79"; for t in test_wage_update_2026.py test_kin_accuracy.py test_claim_assessor_facts.py; do $PY $t > /tmp/csa2_$t.log 2>&1; echo "$t exit=$? $(tail -1 /tmp/csa2_$t.log)"; done
```
Expected: 파일 12개(iaci_* 11 + lsa_act_79) 생성, 세 테스트 `OK`. `--doc`이 별표(`iaci_annex1`)를 받지 못하면 `fetch_official_rules.py` main의 ANNEXES 처리 분기를 확인한다(unemployment-separation-grounds가 `--doc ei_rule_annex2`로 받았으므로 같은 경로가 있다).

- [ ] **Step 5: 메인 원문 사본 동기화 + 커밋**

```bash
rsync -a /Users/zealnutkim/DEV/laborconsult-csa2/output_공식법령/ /Users/zealnutkim/DEV/laborconsult/output_공식법령/ && \
cd /Users/zealnutkim/DEV/laborconsult-csa2 && git add fetch_official_rules.py wage_calculator/legal_anchors.py && \
git commit -q -m "feat(anchors): 산재 계산기 근거 앵커 17개 + 산재법 제36·52·54·55조·시행령 제23~25조·근기법 제79조·별표 1·고시 3건 등록(앵커 전용)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 13: 산재 흐름도·서비스워커·CLAUDE.md·CLI diff·PR-2

**Files:**
- Modify: `public/calculator_flow/industrial_accident_compensation_calc.html`, `wage_calculator/calculator_flow/industrial_accident_compensation_calc.html`
- Modify: `public/sw.js`, `CLAUDE.md`, `docs/02-design/features/calculator-statute-audit.design.md` §7
- Test: `test_calculator_statute_audit.py`

- [ ] **Step 1: 실패하는 테스트 추가**

```python
class AccidentFlowchartTests(unittest.TestCase):
    _FLOW = ("public/calculator_flow/industrial_accident_compensation_calc.html",
             "wage_calculator/calculator_flow/industrial_accident_compensation_calc.html")

    def test_copies_match_and_mention_the_new_rules(self):
        bodies = [(ROOT / p).read_text(encoding="utf-8") for p in self._FLOW]
        svg = [b[b.index("<svg"):] for b in bodies]
        self.assertEqual(svg[0], svg[1])
        for piece in ("3일 이내", "제52조 단서", "최고 보상기준", "268,299", "61세"):
            self.assertIn(piece, bodies[0])
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/zealnutkim/DEV/laborconsult-csa2 && /Users/zealnutkim/DEV/laborconsult/.venv/bin/python test_calculator_statute_audit.py AccidentFlowchartTests 2>&1 | tail -3`
Expected: `FAILED (failures=1)`.

- [ ] **Step 3: 두 사본 같은 치환 + sw.js**

```bash
cd /Users/zealnutkim/DEV/laborconsult-csa2 && for f in public/calculator_flow/industrial_accident_compensation_calc.html wage_calculator/calculator_flow/industrial_accident_compensation_calc.html; do
python3 - "$f" <<'EOF'
import sys, pathlib
p = pathlib.Path(sys.argv[1]); s = p.read_text(encoding="utf-8")
pairs = [
 ('<text class="ts" x="185" y="394" text-anchor="middle" dominant-baseline="central">저임금자: 최대 90%까지 상향</text>',
  '<text class="ts" x="185" y="394" text-anchor="middle" dominant-baseline="central">저임금자 90% 상향 · 3일 이내 요양은 미지급(제52조 단서)</text>'),
 ('<p style="font-size:13px;color:var(--color-text-secondary);margin:0">산업재해보상보험법 제52조</p>',
  '<p style="font-size:13px;color:var(--color-text-secondary);margin:0">산업재해보상보험법 제52조·제54조·제55조 — 요양 3일 이내는 미지급(제52조 단서), 평균임금은 최고 보상기준(2026년 268,299원/일, 제36조⑦)까지, 61세부터 별표 1 계수로 감액</p>'),
]
for old, new in pairs:
    assert s.count(old) == 1, (p, old[:40], s.count(old))
    s = s.replace(old, new)
p.write_text(s, encoding="utf-8"); print("ok", p)
EOF
done
sed -i '' "s/^const VERSION = 'v15-2026-11-12';/const VERSION = 'v16-2026-11-12';/" public/sw.js && grep -n "^const VERSION" public/sw.js
```
Expected: `ok` 2회, `v16-2026-11-12`(PR-1이 아직 머지 전이면 main의 `v14-...`에서 `v15-...`로 올리고, PR-1 머지 뒤 재기반 때 v16으로 다시 맞춘다).

- [ ] **Step 4: CLAUDE.md bullet** (PR-1 bullet 뒤, 없으면 `**출산·가족휴가 급여의 지급 기간 근거는 ...**` 앞)

```markdown
- **산재 급여의 평균임금은 최고·최저 보상기준(제36조⑦)을 거친다**(calculator-statute-audit I2). 표는 `COMPENSATION_LIMITS_DAILY`
  `{연도: (최고, 최저)}` 하나고 `MIN_COMPENSATION_DAILY`는 그 최저 열의 파생이다 — 직접 편집하지 말 것. 최고는 장례비 외 전 급여,
  최저는 장해·유족급여에만(휴업급여·상병보상연금은 단서로 제외, 장례비는 제71조② 자체 최고·최저). 최고를 모르는 해(2024·2025)는
  **폴백하지 않고** 평균임금이 최저의 3.6배(=1.8배 ÷ 1/2)를 넘을 때만 경고한다. 휴업급여는 요양 **3일 이내 미지급**(제52조 단서 —
  근로기준법 제78·79조 사용자 보상 안내)이고, 61세 이후는 별표 1 계수를 **산정 경로별**로 곱한다(제52조 기준 n/70, 제54조 기준
  n/90, 단서 기준은 최저보상×80%×n/90 — `_calc_sick_leave(…, age)`가 6-튜플(daily, total, min_comp, formulas, warnings, legal)을
  돌려준다). 일용근로자(`is_daily_worker`)는 일당 × 통상근로계수 0.73(시행령 제24조①1호, 고시 제2025-90호)이되 **3개월 이상 계속
  근로가 확인되면 적용하지 않는다**(제23조①1호 단서 가목, `_continued_three_months`). 직업병(`injury_type` 질병·뇌심혈관)은
  평균임금 특례(제36조⑥·시행령 제25조)를 안내만 한다. 재결례 934건에서 다투어진 규칙들이다 — 재결은 산식 근거가 아니라 **빠진 법정
  규칙을 찾는 지표**로만 쓴다. 회귀는 `test_calculator_statute_audit.py`.
```

- [ ] **Step 5: CLI diff 기록**

```bash
cd /Users/zealnutkim/DEV/laborconsult && git pull -q --ff-only origin main && ./.venv/bin/python wage_calculator_cli.py > /tmp/cli_main2.txt 2>&1
cd /Users/zealnutkim/DEV/laborconsult-csa2 && /Users/zealnutkim/DEV/laborconsult/.venv/bin/python wage_calculator_cli.py > /tmp/cli_pr2.txt 2>&1
diff /tmp/cli_main2.txt /tmp/cli_pr2.txt | grep -E "^[<>]" | head -60
```
Expected: 산재 사례(#71~#78)에서만 차이 — 각 차이가 (최고·최저 적용 / 3일 단서 / 61세 / 일용) 중 하나인지 확인하고 Design §7 표에 "사례 번호 — 입력(평균임금·요양일수·나이) — 바뀐 값 — 규칙"으로 적는다. 그 밖의 사례가 바뀌면 결함으로 고친다.

- [ ] **Step 6: 전수 테스트 + 커밋 + PR**

```bash
cd /Users/zealnutkim/DEV/laborconsult-csa2 && PY=/Users/zealnutkim/DEV/laborconsult/.venv/bin/python; for t in test_wage_golden.py test_pipeline_wiring.py test_offline_units.py test_wage_update_2026.py test_calc_card_followups.py test_calc_card_consistency.py test_monthly_base_unification.py test_audit50.py test_kin_accuracy.py test_claim_assessor_facts.py test_law_article_coverage.py test_effective_law.py test_calculator_statute_audit.py; do $PY $t > /tmp/csa2_$t.log 2>&1; echo "$t exit=$?"; done; node --test test_public_fetch.js 2>&1 | grep -E "^# (pass|fail)"
git add public/calculator_flow/industrial_accident_compensation_calc.html wage_calculator/calculator_flow/industrial_accident_compensation_calc.html public/sw.js CLAUDE.md docs/02-design/features/calculator-statute-audit.design.md test_calculator_statute_audit.py && \
git commit -q -m "docs(calc): 산재 흐름도에 3일 단서·보상기준·61세 감액, CLAUDE.md 규칙, CLI 변경 사례 기록, sw v16

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" && git push -u origin fix/calc-statute-audit-iaci && \
gh pr create --base main --title "fix: 산재보상 계산기 — 3일 단서·최고·최저 보상기준·61세 감액·일용 통상근로계수·직업병 특례 안내 (calculator-statute-audit PR-2)" --body-file - <<'EOF'
## 요약
calculator-statute-audit PR-2 — 산재보상 계산기. 재결례 934건에서 다투어진 법정 규칙 5개를 계산·안내로 넣고 2026 고시 3건을 출처 등록.

- **I1** 요양 3일 이내 휴업급여 미지급(제52조 단서) + 사용자 요양·휴업보상 안내(근기법 제78·79조)
- **I2** 최고·최저 보상기준(제36조⑦) — 장해·유족 최고·최저, 휴업·상병 최고만, 장례비 제외. 표 `COMPENSATION_LIMITS_DAILY`(2026: 268,299/82,560, 고시 제2025-84호). 최고 미확인 연도는 폴백 없이 경고
- **I3** 61세 이후 휴업급여 별표 1 계수를 산정 경로별로(제55조)
- **I4** 일용근로자 평균임금 = 일당 × 통상근로계수 73/100(시행령 제23·24조, 고시 제2025-90호) — 3개월 이상 계속 근로면 미적용
- **I5** 직업병 평균임금 특례(제36조⑥·시행령 제25조) 안내
- 앵커 17·등록(산재법 제36·52·54·55조, 시행령 제23~25조, 근기법 제79조, 별표 1, 고시 3건)

## 검증
- `test_calculator_statute_audit.py` 확장 + 기존 골든·배선·카드·앵커 테스트 통과
- CLI 116사례: 바뀐 사례와 규칙 대응을 Design §7에 기록

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```
Expected: 전부 `exit=0`, PR URL. CI 확인 → 사용자 확인 → 머지(PR-1 머지 뒤면 `git rebase origin/main` 후 충돌은 `constants.py`·`legal_anchors.py`·`fetch_official_rules.py`·테스트·CLAUDE.md의 **추가 줄 양쪽 보존**).

---

## 마무리(머지 뒤)

- [ ] 메인 작업 트리 정리: `cd /Users/zealnutkim/DEV/laborconsult && git pull --ff-only origin main && git checkout -- docs 2>/dev/null; git status --short` (미추적 문서 3개는 머지된 main에 들어 있으므로 중복 사본 삭제), `git worktree remove ../laborconsult-csa1 ../laborconsult-csa2`.
- [ ] `python3 check_law_freshness.py --anchors` (등록 IP) — 새 앵커 실패 0.
- [ ] 메모리 `project-calculator-statute-audit.md` 작성(PR 번호·머지 해시·CLI 변경 사례·후속 `source-pack-refresh`).
- [ ] `/pdca analyze calculator-statute-audit`(gap-detector)로 Design 대조 → 90% 이상이면 보고서.
