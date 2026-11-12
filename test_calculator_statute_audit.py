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


def _accident(**changes):
    inp = WageInput(monthly_wage=6_000_000, start_date="2020-01-01", end_date="2026-06-30",
                    accident_date="2026-03-01", reference_year=2026, reference_date="2026-11-12")
    for key, value in changes.items():
        setattr(inp, key, value)
    from wage_calculator.calculators.industrial_accident import calc_industrial_accident
    return calc_industrial_accident(inp, calc_ordinary_wage(copy.deepcopy(inp)))


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


class CompensationConstantsTests(unittest.TestCase):
    """D6 — 최고·최저 보상기준 표 하나, 최저 열은 파생. 통상근로계수 73/100."""

    def test_limits_table_and_derived_minimum(self):
        from wage_calculator.constants import COMPENSATION_LIMITS_DAILY, MIN_COMPENSATION_DAILY, ORDINARY_WORK_COEFFICIENT
        self.assertEqual(COMPENSATION_LIMITS_DAILY[2026], (268_299, 82_560))
        self.assertEqual(COMPENSATION_LIMITS_DAILY[2025], (None, 80_240))
        self.assertEqual(MIN_COMPENSATION_DAILY, {year: low for year, (_high, low) in COMPENSATION_LIMITS_DAILY.items()})
        self.assertEqual(ORDINARY_WORK_COEFFICIENT, 0.73)


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
        # 93,000 × 70% = 65,100 ≤ 66,048(최저 82,560 × 80%) → 90% = 83,700 > 66,048 → 제54조① 단서 = 66,048
        # → 최저임금액 82,560 미만이라 제54조② 하한으로 올라간다(최저 보상기준이 최저임금액과 같은 해에는 단서 금액이 늘 그 아래다)
        # → 62세는 제54조 기준 계수 82/90
        daily, *_, formulas, warnings, legal = self._sick(93_000, 10, age=62)
        self.assertEqual(daily, round(82_560 * 82 / 90))
        self.assertTrue(any("별표 1" in f for f in formulas))
        self.assertTrue(any("61세 이후" in w for w in warnings))
        self.assertIn("산업재해보상보험법 제55조·별표 1 (고령자의 휴업급여)", legal)

    def test_senior_factor_on_the_minimum_wage_route(self):
        # 60,000 × 70% = 42,000 → 90% = 54,000 ≤ 66,048 → 54,000 < 최저임금액 82,560 → 제54조② → 63세 × 78/90
        daily, *_ = self._sick(60_000, 10, age=63)
        self.assertEqual(daily, round(82_560 * 78 / 90))

    def test_annex_first_item_floor_binds_when_minimum_standard_exceeds_minimum_wage(self):
        # 별표 1 제1호 단서: 제52조 기준 감액 금액이 제3호(최저보상 × 80% × n/90) 금액보다 적으면 제3호. 최저 보상기준이 최저임금액과
        # 같은 해(2024~2026)에는 제52조 경로 금액이 늘 최저임금액 이상이라 닿지 않으므로 표를 바꿔 넣고 확인한다(Act-1 g)
        from unittest import mock
        import wage_calculator.calculators.industrial_accident as ia
        with mock.patch.object(ia, "MIN_COMPENSATION_DAILY", {2026: 120_000}):
            daily, _, _, formulas, _, _ = self._sick(137_500, 10, age=61)    # 70% = 96,250 > 96,000(최저보상 80%) → 제52조 경로
        self.assertEqual(daily, round(96_000 * 86 / 90))                     # 96,250 × 66/70 = 90,750 < 91,733 → 제3호 하한
        self.assertTrue(any("× 66/70 = 90,750원" in f and "하한 91,733원" in f for f in formulas), formulas)   # 등식은 감액 전 값(N1)
        self.assertEqual(self._sick(200_000, 10, age=61)[0], round(140_000 * 66 / 70))   # 하한이 걸리지 않는 경우는 그대로

    def test_card_passes_age_and_days_through(self):
        res = _accident(sick_leave_days=2)
        self.assertEqual(res.sick_leave_total, 0)
        self.assertTrue(any("제52조 단서" in f for f in res.formulas))
        res61 = _accident(sick_leave_days=30, age=61)
        self.assertTrue(any("고령자 감액(만 61세)" in f for f in res61.formulas), res61.formulas)


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


class AccidentFlowchartTests(unittest.TestCase):
    _FLOW = ("public/calculator_flow/industrial_accident_compensation_calc.html",
             "wage_calculator/calculator_flow/industrial_accident_compensation_calc.html")

    def test_copies_match_and_mention_the_new_rules(self):
        import re
        bodies = [(ROOT / p).read_text(encoding="utf-8") for p in self._FLOW]
        svg = [re.sub(r"<script>\n// Mobile: wrap SVGs.*?</script>\n", "", b[b.index("<svg"):], flags=re.S)
               .replace('<script type="module" src="/analytics.js"></script>\n', "") for b in bodies]
        self.assertEqual(svg[0], svg[1])
        for piece in ("3일 이내", "제52조 단서", "최고 보상기준", "268,299", "61세", "장해·유족급여에만", "휴업·상병은 최고만"):
            self.assertIn(piece, bodies[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
