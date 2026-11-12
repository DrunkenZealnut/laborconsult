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


if __name__ == "__main__":
    unittest.main(verbosity=2)
