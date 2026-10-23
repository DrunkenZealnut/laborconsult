"""monthly-base-unification 회귀 테스트(오프라인, API 키 불요) — Design §7·§8.1.

월 임금(기준 월액)은 `shared.monthly_wage_total` 하나, 평균임금 일액은 `average_wage.calc_average_wage` 하나로 구한다. 계산기마다
따로 만들던 때 한 카드 안의 월 총액·세전·평균임금이 갈렸고(고정연장수당 20만 원: 월 총 2,702,857원 vs 세전 2,502,857원), 휴업수당은
근로기준법 제2조 제2항 하한 없이 법정 금액 아래로 나왔다(시급 12,000원·휴업 10일 474,783원 → 맞는 값 672,000원).
- U1 재현 f1~f6과 산정 기준일·일용근로자 사례
- U2 고정수당 축 격자(임금 형태 × 수당 × 연장 × 상여 × 이직일 = 288건, 불변식 I1~I9)
- U3 등가 — 월급 X + 통상임금 수당 Y ≡ 월급 X+Y
- U4 총액 경로 — 포괄임금·구성 진술 = 총액 + 총액 밖 고정수당
- U5 휴업수당 하한 경계(평균임금 = 1일 통상임금 ± 1원)
- U6 시급제 근로장려금(f3)
- U7 facade 월 총액 규칙(연장수당 섹션·탄력 연장·공휴일)
- U8 CLI 의도 변경 사례
- U9 구조 — 옛 경로가 없고, 소비처가 두 함수만 부른다
- U10 독립 리뷰 지적(보류 기본급 표기·D4 B·제외기간 추정·총액 안 수당·괄호)
- U11 실업급여 평균임금 줄의 모양·경고
"""
from __future__ import annotations

import ast
import itertools
import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from wage_calculator.calculators.average_wage import calc_average_wage  # noqa: E402
from wage_calculator.calculators.eitc import calc_eitc  # noqa: E402
from wage_calculator.calculators.industrial_accident import calc_industrial_accident  # noqa: E402
from wage_calculator.calculators.insurance import calc_insurance  # noqa: E402
from wage_calculator.calculators.ordinary_wage import calc_ordinary_wage  # noqa: E402
from wage_calculator.calculators.retirement_pension import calc_retirement_pension  # noqa: E402
from wage_calculator.calculators.severance import calc_severance  # noqa: E402
from wage_calculator.calculators.shared import fixed_overtime_monthly  # noqa: E402
from wage_calculator.calculators.shutdown_allowance import calc_shutdown_allowance  # noqa: E402
from wage_calculator.calculators.unemployment import calc_unemployment  # noqa: E402
from wage_calculator.facade import WageCalculator  # noqa: E402
from wage_calculator.models import BusinessSize, WageInput, WageType, WorkSchedule  # noqa: E402

CALC = ROOT / "wage_calculator" / "calculators"
FIVE_DAYS = dict(daily_work_hours=8, weekly_work_days=5)
AVERAGE_WAGE_FAMILY = ["insurance", "severance", "unemployment", "average_wage"]


def wage_input(*, overtime: float = 0, **kw) -> WageInput:
    kw.setdefault("business_size", BusinessSize.OVER_5)
    return WageInput(schedule=WorkSchedule(**FIVE_DAYS, weekly_overtime_hours=overtime), **kw)


def card(inp: WageInput, targets: list[str]):
    """파이프라인 G2처럼 연장분을 더하는 입력이면 연장수당 섹션을 함께 계산한 카드."""
    if inp.schedule.weekly_overtime_hours and "overtime" not in targets:
        targets = targets + ["overtime"]
    return WageCalculator().calculate(replace(inp), targets)


def unemployment(inp: WageInput):
    inp = replace(inp, age=35, insurance_months=30)
    return calc_unemployment(inp, calc_ordinary_wage(inp))


class ReproTest(unittest.TestCase):
    """U1 — Plan §2 재현(시제품 값, Design §2.1)."""

    def test_f1_fixed_overtime_allowance_without_overtime_hours(self):
        inp = wage_input(wage_type=WageType.HOURLY, hourly_wage=12000, start_date="2024-10-01", end_date="2026-10-01",
                         fixed_allowances=[{"name": "고정연장수당", "amount": 200000}])
        ow = calc_ordinary_wage(inp)
        self.assertEqual(card(inp, AVERAGE_WAGE_FAMILY).monthly_total, 2702857)
        self.assertEqual(round(calc_insurance(inp, ow).monthly_gross), 2702857)
        self.assertEqual(calc_average_wage(inp, ow).wage_total, 8108571)

    def test_f1_prime_fixed_overtime_and_computed_overtime_are_counted_once(self):
        """고정연장수당 20만 원과 계산한 연장 391,071원 중 큰 쪽 하나 — 둘 다 더하면 3,093,928원이다(독립 리뷰 M2)."""
        inp = wage_input(wage_type=WageType.HOURLY, hourly_wage=12000, overtime=5,
                         fixed_allowances=[{"name": "고정연장수당", "amount": 200000}])
        self.assertEqual(card(inp, ["insurance"]).monthly_total, 2893928)
        self.assertEqual(round(calc_insurance(inp, calc_ordinary_wage(inp)).monthly_gross), 2893928)

    def test_f2_separate_ordinary_allowance_counts_like_a_merged_salary(self):
        common = dict(start_date="2024-10-01", end_date="2026-10-01", overtime=10)
        split = wage_input(wage_type=WageType.MONTHLY, monthly_wage=2500000,
                           fixed_allowances=[{"name": "직책수당", "amount": 200000}], **common)
        merged = wage_input(wage_type=WageType.MONTHLY, monthly_wage=2700000, **common)
        for inp in (split, merged):
            ow = calc_ordinary_wage(inp)
            self.assertEqual(calc_severance(inp, ow).severance_pay, 6933424)
            self.assertEqual(unemployment(inp).daily_benefit, 68100)

    def test_f4_f5_hourly_shutdown_uses_the_ordinary_wage_floor(self):
        inp = wage_input(wage_type=WageType.HOURLY, hourly_wage=12000, shutdown_days=10, shutdown_start_date="2026-09-01")
        r = calc_shutdown_allowance(inp, calc_ordinary_wage(inp))
        self.assertEqual((r.daily_shutdown_allowance, r.shutdown_allowance), (67200, 672000))
        self.assertIn("근로기준법 제2조 제2항 (평균임금이 통상임금보다 적으면 통상임금)", r.legal_basis)

    def test_f6_shutdown_includes_bonus_three_twelfths(self):
        inp = wage_input(wage_type=WageType.MONTHLY, monthly_wage=3000000, annual_bonus_total=6000000, shutdown_days=10)
        self.assertEqual(calc_shutdown_allowance(inp, calc_ordinary_wage(inp)).shutdown_allowance, 805476)

    def test_shutdown_period_is_counted_back_from_the_shutdown_start(self):
        """휴업 시작일 2026-03-01 → 산정기간 90일(이직일 2026-10-01이면 92일). 상여 3/12를 더한 평균이 통상임금을 넘는 입력이라
        일수가 결과를 가른다."""
        inp = wage_input(wage_type=WageType.MONTHLY, monthly_wage=3000000, annual_bonus_total=6000000, shutdown_days=10,
                         end_date="2026-10-01")
        ow = calc_ordinary_wage(inp)
        self.assertEqual(calc_shutdown_allowance(inp, ow).shutdown_allowance, 805476)
        self.assertEqual(calc_shutdown_allowance(replace(inp, shutdown_start_date="2026-03-01"), ow).shutdown_allowance, 816667)

    def test_accident_average_wage_is_counted_back_from_the_accident_date(self):
        """재해보상의 평균임금 산정 사유 발생일은 사고가 발생한 날이다(근로기준법 시행령 제52조)."""
        inp = wage_input(wage_type=WageType.MONTHLY, monthly_wage=3000000, annual_bonus_total=6000000, sick_leave_days=10,
                         end_date="2026-10-01")
        ow = calc_ordinary_wage(inp)
        self.assertEqual(round(calc_industrial_accident(inp, ow).avg_daily_wage), 115068)
        r = calc_industrial_accident(replace(inp, accident_date="2026-03-01"), ow)
        self.assertEqual(round(r.avg_daily_wage), 116667)
        self.assertIn("근로기준법 시행령 제52조 (재해보상 시의 평균임금 산정 사유 발생일)", r.legal_basis)

    def test_daily_worker_unemployment_skips_the_ordinary_wage_floor(self):
        """실업급여는 하한 전 6호 금액을 받아 고용보험법 제45조 제2항을 스스로 적용한다 — 이직 당시 일용근로자는 단서로 비교하지
        않는다. 하한 후 값을 받으면 그 단서가 무력해진다."""
        common = dict(wage_type=WageType.DAILY, daily_wage=100000, start_date="2023-04-01", end_date="2026-10-01")
        regular, daily = unemployment(wage_input(**common)), unemployment(wage_input(is_daily_worker=True, **common))
        self.assertEqual(regular.base_daily_benefit, 60000)     # 1일 통상임금 100,000원 × 60%
        self.assertEqual(daily.base_daily_benefit, 51009)       # 평균임금 85,016원 × 60%

    def test_f3_hourly_eitc_estimates_income(self):
        inp = wage_input(wage_type=WageType.HOURLY, hourly_wage=12000)
        r = calc_eitc(inp, calc_ordinary_wage(inp))
        self.assertEqual(r.annual_income, 30034284)
        self.assertNotIn("소득 정보 없음", r.ineligible_reason)


WAGES = {
    "시급": dict(wage_type=WageType.HOURLY, hourly_wage=12000),
    "일급": dict(wage_type=WageType.DAILY, daily_wage=100000),
    "월급": dict(wage_type=WageType.MONTHLY, monthly_wage=2500000),
    "연봉": dict(wage_type=WageType.ANNUAL, annual_wage=36000000),
}
ALLOWANCES = {
    "없음": [],
    "직책수당": [{"name": "직책수당", "amount": 200000}],
    "고정연장수당": [{"name": "고정연장수당", "amount": 200000}],
    "연차수당": [{"name": "연차수당", "amount": 100000}],
    "직책+고정연장": [{"name": "직책수당", "amount": 200000}, {"name": "고정연장수당", "amount": 300000}],
    "연 명절상여(재직)": [{"name": "명절상여금", "amount": 1200000, "annual": True, "condition": "재직조건"}],
}
OVERTIME = (0, 5, 12)
BONUS = (0, 6000000)
END_DATES = ("2026-10-01", "2026-03-01")   # 산정기간 92일·90일


def grid_input(wage, allowance, overtime, bonus, end):
    return wage_input(overtime=overtime, start_date="2023-04-01", end_date=end, fixed_allowances=list(ALLOWANCES[allowance]),
                      annual_bonus_total=bonus, shutdown_start_date=end, shutdown_days=10, pension_type="DC",
                      **WAGES[wage])


class FixedAllowanceGridTest(unittest.TestCase):
    """U2 — 고정수당 축 격자(Design §2.2·§7). main에서 위반 1,264건이던 격자다."""

    @classmethod
    def setUpClass(cls):
        cls.violations, cls.checked, cls.cases = [], dict.fromkeys(
            ("I1", "I2", "I3", "I4", "I5", "I6", "I7", "I8", "I9"), 0), 0
        targets = ["insurance", "severance", "unemployment", "average_wage", "shutdown_allowance", "industrial_accident",
                   "retirement_pension", "eitc"]

        def check(name, ok, *detail):
            cls.checked[name] += 1
            if not ok:
                cls.violations.append((name, *detail))

        for key in itertools.product(WAGES, ALLOWANCES, OVERTIME, BONUS, END_DATES):
            cls.cases += 1
            inp = grid_input(*key)
            ow = calc_ordinary_wage(inp)
            total = card(inp, targets).monthly_total
            avg = calc_average_wage(inp, ow)
            check("I1", abs(total - calc_insurance(inp, ow).monthly_gross) <= 1, key, total)
            check("I2", abs(avg.wage_total - total * 3) <= 3, key, avg.wage_total, total)
            check("I3", calc_severance(inp, ow).avg_daily_wage + 1 >= avg.avg_daily_wage, key)
            un = unemployment(inp)
            if un.is_eligible:
                check("I4", abs(un.avg_daily_wage - round(avg.avg_daily_3m)) <= 1, key, un.avg_daily_wage, avg.avg_daily_3m)
            sh = calc_shutdown_allowance(inp, ow)
            expected = min(0.7 * avg.avg_daily_wage, ow.daily_ordinary_wage)
            check("I5", abs(sh.daily_shutdown_allowance - round(expected)) <= 1
                  and sh.daily_shutdown_allowance + 1 >= 0.7 * ow.daily_ordinary_wage, key, sh.daily_shutdown_allowance)
            check("I6", abs(calc_industrial_accident(replace(inp, sick_leave_days=10), ow).avg_daily_wage - avg.avg_daily_wage) <= 1,
                  key)
            # DC형 연간임금·근로장려금 소득은 연 상여(annual_bonus_total)를 아직 넣지 않는다(이 사이클 전부터 — Design §14 후속).
            # 상여 행에서 '월 총액 × 12'를 단언하면 그 누락을 테스트로 굳히게 되므로 상여 없는 행만 본다(독립 리뷰 L7)
            if not key[3]:
                dc = calc_retirement_pension(inp, ow).annual_contributions
                check("I7", bool(dc) and abs(dc[0]["annual_wage"] - total * 12) <= 12, key, dc[:1], total)
                check("I8", abs(calc_eitc(inp, ow).annual_income - total * 12) <= 12, key)
            check("I9", fixed_overtime_monthly(inp) <= ow.not_ordinary_fixed_total + 0.5, key)

    def test_u2_invariants_hold_across_the_grid(self):
        self.assertEqual(self.cases, 288)
        for name, count in self.checked.items():
            self.assertGreater(count, 0, f"{name}를 검사한 조합이 없다 — 공허한 통과")
        self.assertEqual(self.violations[:5], [])


class EquivalenceTest(unittest.TestCase):
    """U3 — 통상임금에 드는 고정수당 Y를 '월급 X + 수당 Y'로 적으나 '월급 X+Y'로 적으나 같은 금액이다(Plan 등가 불변식)."""

    def test_u3_split_and_merged_salaries_give_the_same_amounts(self):
        for overtime, bonus, end in itertools.product(OVERTIME, BONUS, END_DATES):
            values = []
            for kw in (dict(monthly_wage=2500000, fixed_allowances=[{"name": "직책수당", "amount": 200000}]),
                       dict(monthly_wage=2700000)):
                inp = wage_input(wage_type=WageType.MONTHLY, overtime=overtime, annual_bonus_total=bonus, start_date="2023-04-01",
                                 end_date=end, shutdown_days=10, sick_leave_days=10, **kw)
                ow = calc_ordinary_wage(inp)
                values.append((calc_severance(inp, ow).severance_pay, unemployment(inp).daily_benefit,
                               calc_shutdown_allowance(inp, ow).shutdown_allowance,
                               round(calc_industrial_accident(inp, ow).avg_daily_wage), round(calc_insurance(inp, ow).monthly_gross),
                               card(inp, ["severance", "insurance"]).monthly_total))
            with self.subTest(overtime=overtime, bonus=bonus, end=end):
                self.assertEqual(values[0], values[1])


class TotalPayPathTest(unittest.TestCase):
    """U4 — 연장 등이 이미 든 총액은 '총액 + 총액 밖 고정수당'이고 연장 등을 더하지 않는다(Design D3). main은 명세 있는 포괄임금의
    월 총액·세전을 기본급으로 냈고, 첫 시제품은 총액 밖 식대를 뺐다."""

    def test_u4_comprehensive_and_stated_totals(self):
        paths = {
            "포괄 명세 없음": dict(wage_type=WageType.COMPREHENSIVE, monthly_wage=3000000),
            "포괄 명세 있음": dict(wage_type=WageType.COMPREHENSIVE, monthly_wage=3000000,
                               comprehensive_breakdown={"base": 2200000, "overtime_pay": 800000}),
            "구성 진술 월급": dict(wage_type=WageType.MONTHLY, monthly_wage=3000000, wage_composition_known=True),
        }
        for (label, kw), meal, overtime in itertools.product(paths.items(), (False, True), (0, 10)):
            inp = wage_input(overtime=overtime, end_date="2026-10-01",
                             fixed_allowances=[{"name": "식대", "amount": 200000}] if meal else [], **kw)
            ow = calc_ordinary_wage(inp)
            expected = 3200000 if meal else 3000000
            got = (card(inp, ["insurance", "average_wage"]).monthly_total, calc_insurance(inp, ow).monthly_gross,
                   calc_average_wage(inp, ow).wage_total / 3, calc_eitc(inp, ow).annual_income / 12)
            with self.subTest(label, meal=meal, overtime=overtime):
                for value in got:
                    self.assertAlmostEqual(value, expected, delta=1)


class ShutdownFloorBoundaryTest(unittest.TestCase):
    """U5 — 휴업수당은 1일 통상임금 미만의 평균임금을 쓰지 않는다(Plan 완료 조건 3, 근로기준법 제2조 제2항·제46조)."""

    def test_u5_one_won_either_side_of_the_ordinary_wage(self):
        inp = wage_input(wage_type=WageType.HOURLY, hourly_wage=12000, shutdown_days=10, last_3m_days=92)
        ow = calc_ordinary_wage(inp)
        self.assertEqual(ow.daily_ordinary_wage, 96000)
        below = calc_shutdown_allowance(replace(inp, last_3m_wages=[95999 * 92 / 3] * 3), ow)
        above = calc_shutdown_allowance(replace(inp, last_3m_wages=[96001 * 92 / 3] * 3), ow)
        self.assertEqual(below.daily_shutdown_allowance, 67200)      # 통상임금 96,000원 × 70%
        self.assertEqual(above.daily_shutdown_allowance, 67201)      # 3개월 평균 96,001원 × 70%


class EitcHourlyTest(unittest.TestCase):
    """U6 — 시급제도 기준 월액 × 12로 소득을 추정해 판정한다(f3)."""

    def test_u6_hourly_income_is_the_monthly_total_times_twelve(self):
        inp = wage_input(wage_type=WageType.HOURLY, hourly_wage=12000, overtime=5)
        r = calc_eitc(inp, calc_ordinary_wage(inp))
        self.assertAlmostEqual(r.annual_income, card(inp, ["eitc"]).monthly_total * 12, delta=12)   # 카드 월 총액은 원 단위 반올림
        self.assertTrue(any("x 12" in w for w in r.warnings), r.warnings)


def cli_cases():
    import wage_calculator_cli
    return {c["id"]: c for c in wage_calculator_cli.TEST_CASES}


class FacadeTotalTest(unittest.TestCase):
    """U7·U8 — facade 월 총액(Design D6)과 CLI 의도 변경(Design §6.1)."""

    @classmethod
    def setUpClass(cls):
        cls.cases = cli_cases()

    def run_case(self, case_id):
        case = self.cases[case_id]
        return WageCalculator().calculate(replace(case["input"]), case["targets"])

    def test_u7_overtime_is_added_only_when_the_overtime_section_is_computed(self):
        """보상휴가 질문(#24)은 연장 대가를 휴가로 받는다 — 연장수당 섹션이 없으니 월 총액에 연장분이 없다."""
        self.assertEqual(self.run_case(24).monthly_total, 3000000)
        inp = wage_input(wage_type=WageType.MONTHLY, monthly_wage=3000000, overtime=10)
        self.assertEqual(WageCalculator().calculate(replace(inp), ["insurance"]).monthly_total, 3000000)
        self.assertGreater(WageCalculator().calculate(replace(inp), ["insurance", "overtime"]).monthly_total, 3000000)

    def test_u7_flexible_work_overtime_is_added(self):
        self.assertEqual(self.run_case(29).monthly_total, 3031250)
        self.assertEqual(self.run_case(30).monthly_total, 3288462)

    def test_u8_intended_changes(self):
        """포괄임금 명세 총액(#3·#67·#69), 공휴일 ÷ 12 제거(#10), 휴업수당 하한(#86·#87)."""
        for case_id in (3, 10, 67, 69):
            with self.subTest(case_id):
                self.assertEqual(self.run_case(case_id).monthly_total, 3000000)
        self.assertEqual(self.run_case(86).summary["휴업수당"], "2,416,428원")
        self.assertEqual(self.run_case(87).summary["휴업수당"], "671,230원")


def pipeline_card(params: dict, query: str) -> str:
    from test_calc_card_consistency import card as _card
    base = {"wage_type": "월급", "weekly_work_days": 5, "daily_work_hours": 8, "business_size": "5인이상",
            "start_date": "2023-04-01", "end_date": "2026-10-01"}
    return _card(dict(base, **params), query)


class ReviewFindingsTest(unittest.TestCase):
    """U10 — 독립 리뷰가 파이프라인 경로에서 찾은 것(Do §14). U1~U9는 계산기를 직접 불러 이 경로를 보지 않았다."""

    def test_m1_held_base_pay_is_not_called_the_total(self):
        """금액이 질문의 기본급인 보류 카드(held_is_total=False)에 '월급 총액'을 붙이지 않는다 — 총액 이름표는 파이프라인이
        총액일 때만 붙인다(`_label_held_total`)."""
        out = pipeline_card(dict(wage_amount=2090000, calculation_types_kr=["4대보험", "실업급여"]),
                            "기본급 2,096,270원에 연장·야간수당이 포함되어 있습니다. 4대보험과 실업급여는 얼마인가요?")
        self.assertIn("세전 월 급여: 2,090,000원 (통상임금 기준)", out)
        self.assertNotIn("월급 총액", out)
        total = pipeline_card(dict(wage_amount=2700000, calculation_types_kr=["4대보험"]),
                              "월급 270만원에 연장·야간수당이 포함되어 있습니다. 4대보험은 얼마인가요?")
        self.assertIn("세전 월 급여: 2,700,000원 (월급 총액 기준)", total)

    def test_m2_d4_alternative_keeps_the_allowances_outside_the_composition(self):
        """'A원 또는 B원'의 차이는 구성(연장 등 포함 여부)만이어야 한다 — B에도 통상임금에서 뺀 연차수당이 들어간다."""
        out = pipeline_card(dict(wage_amount=2500000, weekly_overtime_hours=10, calculation_types_kr=["4대보험"],
                                 fixed_allowances=[{"name": "연차수당", "amount": 100000}]),
                            "월급 250만원에 연차수당 10만원을 받고 매주 연장근로 10시간을 합니다. 4대보험은 얼마인가요?")
        self.assertIn("세전 월 급여: 3,381,250원(연장수당 별도) 또는 2,600,000원(월급에 포함)", out)

    def test_m3_excluded_period_does_not_inflate_the_estimate(self):
        """추정 총액에서 제외 기간의 몫은 일수 비율로 뺀다(받은 금액만 빼면 평소 임금이 남는다). 산정기간 밖 제외 기간은 세지 않는다."""
        inp = wage_input(wage_type=WageType.MONTHLY, monthly_wage=3000000, start_date="2023-04-01", end_date="2026-10-01",
                         excluded_periods=[{"start": "2026-08-01", "end": "2026-08-30", "paid": 0}])
        self.assertEqual(unemployment(inp).avg_daily_wage, 97826)
        moved = replace(inp, annual_bonus_total=6000000, shutdown_days=10, shutdown_start_date="2026-03-01")
        ow = calc_ordinary_wage(moved)
        self.assertEqual(calc_shutdown_allowance(moved, ow).shutdown_allowance,
                         calc_shutdown_allowance(replace(moved, excluded_periods=[]), ow).shutdown_allowance)

    def test_m4_allowance_stated_inside_the_total_is_not_added_again(self):
        out = pipeline_card(dict(wage_amount=2700000, calculation_types_kr=["4대보험", "실업급여"],
                                 fixed_allowances=[{"name": "식대", "amount": 200000}]),
                            "월급 270만 원에 식대 20만 원과 연장수당이 모두 포함돼 있습니다. 4대보험과 실업급여는 얼마인가요?")
        self.assertIn("세전 월 급여: 2,700,000원 (월급 총액 기준)", out)
        self.assertIn("(2,700,000원 × 3) ÷ 92일", out)
        from app.core.pipeline import _stated_included_items
        self.assertEqual(_stated_included_items("월급 270만 원(연장수당 포함), 식대 20만 원 받습니다."), set())
        self.assertEqual(_stated_included_items("연장수당은 포함돼 있고 식대 20만 원은 포함되지 않아요."), set())

    def test_l1_formula_parenthesizes_the_monthly_sum(self):
        """'통상임금 월 A원 + 고정수당 B원 × 3'은 B만 세 배로 읽힌다 — 합계를 괄호로 묶는다."""
        out = pipeline_card(dict(wage_type="시급", wage_amount=12000, calculation_types_kr=["실업급여", "평균임금"],
                                 fixed_allowances=[{"name": "고정연장수당", "amount": 200000}]),
                            "시급 12,000원, 주 5일 8시간, 고정연장수당 20만 원을 받다가 2026년 10월 1일 퇴사했어요. 실업급여는?")
        self.assertIn("((통상임금 월 2,502,857원 + 통상임금에서 뺀 고정수당 200,000원) × 3) ÷ 92일 = 88,136.6원", out)
        self.assertIn("8,108,571원 ((통상임금 + 통상임금에서 뺀 고정수당 200,000원) × 3 추정)", out)


class UnemploymentFormulaTest(unittest.TestCase):
    """U11 — 실업급여 평균임금 줄은 숫자의 출처만 바뀌고 모양·경고는 그대로다(Design §4). 산식 줄이 계산과 어긋나면 LLM이 그 줄을 옮긴다."""

    def formulas(self, **kw):
        r = unemployment(wage_input(start_date="2023-04-01", **kw))
        return r, " / ".join(r.formulas)

    def test_u11_estimate_divides_by_the_period_days(self):
        r, text = self.formulas(wage_type=WageType.MONTHLY, monthly_wage=3000000, end_date="2026-03-01")
        self.assertIn("평균임금 일액(추정): (3,000,000원 × 3) ÷ 90일 = 100,000.0원", text)
        self.assertTrue(any(w.startswith("평균임금은 이직 전 3개월 실지급 임금으로 산정합니다") for w in r.warnings), r.warnings)

    def test_u11_hourly_estimate_keeps_its_warning(self):
        r, _ = self.formulas(wage_type=WageType.HOURLY, hourly_wage=12000, end_date="2026-10-01")
        self.assertTrue(any(w.startswith("평균임금을 통상임금 월액(시급 × 월 기준시간)으로 추정했습니다") for w in r.warnings))

    def test_u11_actual_wages_and_excluded_periods(self):
        _, text = self.formulas(wage_type=WageType.MONTHLY, monthly_wage=3000000, end_date="2026-10-01",
                                last_3m_wages=[3000000, 3000000, 2000000], annual_bonus_total=6000000)
        self.assertIn("평균임금 일액: (8,000,000원 + 상여금 1,500,000원 + 연차수당 0원) ÷ 92일 = 103,260.9원", text)
        _, text = self.formulas(wage_type=WageType.MONTHLY, monthly_wage=3000000, end_date="2026-10-01",
                                excluded_periods=[{"start": "2026-08-01", "end": "2026-08-30", "paid": 0}])
        self.assertIn("산정기간 제외: 30일, 제외 임금: 2,934,783원 (추정 총액의 그 기간 몫, 근기법 시행령 제2조)", text)
        self.assertIn("(3개월 임금총액 6,065,217원(제외 임금 차감 후)) ÷ 62일 = 97,826.1원", text)

    def test_u11_daily_held_notice_puts_unemployment_with_pay_estimates(self):
        """일급 보류 카드에서 실업급여는 '통상임금으로 계산하는 항목'이 아니다 — 평균임금을 월 금액 × 3으로 추정한다."""
        from app.core.pipeline import _held_targets_note
        note = _held_targets_note(["unemployment"])
        self.assertIn("월 보수·소득으로 계산하는 항목", note)
        self.assertNotIn("통상임금(시급·일급·월액)으로 계산하는 항목", note)


def calls(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call):
            func = node.func
            names.add(func.id if isinstance(func, ast.Name) else getattr(func, "attr", ""))
    return names


class StructureTest(unittest.TestCase):
    """U9 — 소비처가 월 금액·평균임금을 직접 만들지 않는다. 동작 검사(U2)가 못 보는 '같은 값을 다른 식으로 만드는' 경로를 막는다."""

    def test_u9_old_paths_are_gone(self):
        from wage_calculator.calculators import shared, shutdown_allowance
        for name in ("monthly_pay_estimate", "premium_monthly_with_fixed", "premium_monthly_note"):
            self.assertFalse(hasattr(shared, name), name)
        self.assertFalse(hasattr(shutdown_allowance, "_calc_avg_daily_wage"))
        tree = ast.parse((CALC / "industrial_accident.py").read_text(encoding="utf-8"))
        divide_by_30 = [n for n in ast.walk(tree) if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div)
                        and isinstance(n.right, ast.Constant) and n.right.value == 30]
        self.assertEqual(divide_by_30, [])   # 산재 평균임금의 옛 '월 금액 ÷ 30'

    def test_u9_consumers_call_the_single_sources(self):
        for module in ("insurance", "average_wage", "severance", "eitc", "retirement_pension", "unemployment"):
            with self.subTest(module):
                self.assertIn("monthly_wage_total", calls(CALC / f"{module}.py"))
        for module in ("severance", "unemployment", "shutdown_allowance", "industrial_accident"):
            with self.subTest(module):
                self.assertIn("calc_average_wage", calls(CALC / f"{module}.py"))
        self.assertIn("monthly_wage_total", calls(ROOT / "wage_calculator" / "facade" / "__init__.py"))


if __name__ == "__main__":
    unittest.main()
