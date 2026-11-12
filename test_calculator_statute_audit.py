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
