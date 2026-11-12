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


class FlowchartTests(unittest.TestCase):
    """D11 — 공개 흐름도 두 사본의 본문이 같고, 조기재취업 공식이 미지급일수 × 1/2다."""

    _FLOW = ("public/calculator_flow/unemployment_benefit_calc.html",
             "wage_calculator/calculator_flow/unemployment_benefit_calc.html")

    @staticmethod
    def _svg_body(path: Path) -> str:
        """첫 <svg>부터 끝까지 — head 메타데이터·단독 진입 링크·모바일 스크롤 스크립트·analytics는 공개 사본에만 있다."""
        import re
        text = path.read_text(encoding="utf-8")[path.read_text(encoding="utf-8").index("<svg"):]
        text = re.sub(r"<script>\n// Mobile: wrap SVGs.*?</script>\n", "", text, flags=re.S)
        return text.replace('<script type="module" src="/analytics.js"></script>\n', "")

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
