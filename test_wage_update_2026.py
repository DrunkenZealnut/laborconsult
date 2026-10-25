"""2026-10 계산기 갱신 회귀: 사용자 요청이 실제 계산 결과에 대응해야 한다."""
import unittest
from datetime import date
from unittest import mock
from test_parental_benefits_update import ParentalBenefitsUpdateTests
from test_arrears_interest_update import ArrearsInterestUpdateTests
from test_pay_input_update import PayInputUpdateTests
from test_proration_update import ProrationUpdateTests
from test_wage_claims_update import WageClaimsUpdateTests

from app.core.pipeline import _run_calculator
from wage_calculator.facade import WageCalculator
from wage_calculator.facade.registry import resolve_calc_type
from wage_calculator.models import WageInput, WageType
from wage_calculator.result import format_result, format_result_json
from app.models.schemas import AnalysisResult
from app.core.pipeline import _analysis_to_extract_params, _calculation_context_heading, _consultation_allowed
from wage_calculator.models import BusinessSize, WorkSchedule
from wage_calculator.calculators.annual_leave import calc_annual_leave
from wage_calculator.calculators.ordinary_wage import calc_ordinary_wage


def annual(**kwargs):
    data = dict(wage_type=WageType.HOURLY, hourly_wage=10000,
                business_size=BusinessSize.OVER_5, reference_year=2026,
                reference_date="2026-10-23", start_date="2025-01-01", end_date="2026-07-01")
    data.update(kwargs)
    inp = WageInput(**data)
    return calc_annual_leave(inp, calc_ordinary_wage(inp))


def annual_card(**kwargs):
    """facade를 거친 연차 카드 — 답변은 summary만 본다(breakdown은 카드에 나오지 않는다)."""
    data = dict(wage_type=WageType.HOURLY, hourly_wage=10000,
                business_size=BusinessSize.OVER_5, reference_year=2026,
                reference_date="2026-10-23", start_date="2025-01-01", end_date="2026-07-01")
    data.update(kwargs)
    return WageCalculator().calculate(WageInput(**data), ["annual_leave"])


class _Today(date):
    """분석기 연도 보정의 '오늘'을 2026-10-26으로 고정한다."""
    @classmethod
    def today(cls):
        return cls(2026, 10, 26)


# 연차 후속(wage-update-followups PR-4) 공용 입력
_FULL_ORIGINAL = dict(schedule=WorkSchedule(daily_work_hours=5, weekly_work_days=5),
                      annual_original_weekly_hours=40, annual_original_daily_hours=8)
_REDUCED = dict(kind="childcare_reduced", end_date="2025-12-31")
_FACTS_2018 = dict(start_date="2017-01-01", end_date="2019-01-01", annual_scheduled_days=250, annual_attended_days=150)
_FACTS_2025 = dict(annual_scheduled_days=250, annual_attended_days=150, annual_full_attendance_months=6)
_LEAVE_2025 = dict(kind="childcare_leave", start_date="2025-07-01", end_date="2025-12-31", scheduled_days=100)


class AnnualLeaveUpdateTests(unittest.TestCase):
    def test_effective_rule_slices_are_half_open_and_reject_gaps(self):
        from datetime import date as D
        from wage_calculator.effective_rules import EffectiveRule, split_effective_periods
        rules = [EffectiveRule("old", D(2024, 1, 1), D(2025, 1, 1), {}, ("source",)),
                 EffectiveRule("new", D(2025, 1, 1), None, {}, ("source",))]
        slices = split_effective_periods(D(2024, 12, 31), D(2025, 1, 2), rules)
        self.assertEqual([(s.start, s.end_exclusive, s.rule.rule_id) for s in slices],
                         [(D(2024,12,31),D(2025,1,1),"old"), (D(2025,1,1),D(2025,1,2),"new")])
        for start,end,rs in ((D(2025,1,1),D(2025,1,1),rules),
                             (D(2025,1,2),D(2025,1,1),rules),
                             (D(2023,1,1),D(2025,1,2),rules),
                             (D(2024,1,1),D(2025,1,2),rules+rules[:1])):
            with self.assertRaises(ValueError):
                split_effective_periods(start,end,rs)

    def test_annual_first_year_used_not_deducted(self):
        r = annual(first_year_leave_used=5)
        self.assertEqual((r.accrued_days, r.deducted_days), (15, 0))
        self.assertEqual(r.schedule[-1]["days"], 15)
        text = str((r.breakdown, r.legal_basis, r.schedule))
        self.assertNotIn("제60조 제3항", text)
        self.assertNotIn("2년차 차감", text)

    def test_historical_deduction_retained_only_before_hire_cutoff(self):
        for hire, deduction in (("2017-05-29", 5), ("2017-05-30", 0)):
            r = annual(start_date=hire, end_date="2018-07-01", first_year_leave_used=5)
            self.assertEqual((r.accrued_days, r.deducted_days), (15-deduction, deduction))

    def test_under_five_and_under_fifteen_do_not_accrue(self):
        for data in (dict(business_size=BusinessSize.UNDER_5),
                     dict(schedule=WorkSchedule(daily_work_hours=2.8, weekly_work_days=5))):
            r = annual(**data)
            self.assertEqual((r.accrued_days, r.annual_leave_pay), (0, 0))
            self.assertFalse(r.is_eligible)
        self.assertEqual(annual(schedule=WorkSchedule(daily_work_hours=3, weekly_work_days=5)).accrued_hours, 45)

    def test_exact_year_contract_and_anniversary(self):
        r = annual(start_date="2025-01-01", end_date="2026-01-01", last_employed_date="2025-12-31")
        self.assertEqual(r.accrued_days, 11)
        self.assertEqual(len([s for s in r.schedule if s["kind"] == "annual"]), 0)
        self.assertEqual(annual(end_date="2026-01-01").accrued_days, 15)
        # A leap day must not turn day 365 into a completed calendar year.
        self.assertEqual(annual(start_date="2024-01-01", end_date="2024-12-31").accrued_days, 11)
        self.assertEqual(annual(start_date="2023-01-01", end_date="2026-01-01").accrued_days, 16)

    def test_low_attendance_requires_actual_completed_months(self):
        r = annual(attendance_rate=.79, annual_full_attendance_months=7)
        self.assertEqual(r.accrued_days, 7)
        self.assertEqual(r.schedule[-1]["days"], 7)
        self.assertEqual(annual(attendance_rate=.8).accrued_days, 15)
        self.assertTrue(annual(attendance_rate=.79).held_reason)
        self.assertEqual(annual(end_date="2025-07-01", attendance_rate=.9,
                                annual_full_attendance_months=4).accrued_days, 4)

    def test_annual_deemed_attendance_periods(self):
        facts = dict(annual_scheduled_days=250, annual_attended_days=150,
                     annual_full_attendance_months=6)
        p = dict(kind="childcare_leave", start_date="2025-07-01", end_date="2025-12-31",
                 scheduled_days=100, application_date="2025-06-01")
        self.assertEqual(annual(**facts, annual_deemed_periods=[p]).accrued_days, 15)
        self.assertEqual(annual(**facts).accrued_days, 6)
        self.assertTrue(annual(**facts, annual_deemed_periods=[p, p]).held_reason)

    def test_deemed_period_requires_count_in_assessment_period(self):
        p = dict(kind="childcare_leave", start_date="2024-07-01", end_date="2025-06-30",
                 scheduled_days=100, application_date="2024-06-01")
        r = annual(annual_scheduled_days=250, annual_attended_days=150, annual_deemed_periods=[p])
        self.assertTrue(r.held_reason)
        self.assertIn("산정기간", r.held_reason)

    def test_reduced_hours_after_amendment_keep_accrual_hours(self):
        p = dict(kind="childcare_reduced", start_date="2025-01-01", end_date="2025-12-31")
        r = annual(schedule=WorkSchedule(daily_work_hours=5, weekly_work_days=5),
                   annual_deemed_periods=[p], annual_original_weekly_hours=40,
                   annual_original_daily_hours=8, annual_leave_used_hours=5)
        self.assertEqual((r.accrued_days, r.accrued_hours, r.remaining_hours), (15, 120, 115))
        self.assertEqual(r.annual_leave_pay, 1150000)
        # Starting before the amendment does not switch automatically during use.
        p["start_date"] = "2024-10-21"
        held = annual(schedule=WorkSchedule(daily_work_hours=5, weekly_work_days=5), annual_deemed_periods=[p],
                      annual_original_weekly_hours=40, annual_original_daily_hours=8)
        self.assertIn("2024-10-22", held.held_reason)   # 원래 시간을 넣어도 다른 사유가 아니라 시행일 경계로 보류된다

    def test_short_childcare_deemed_attendance_effective_boundary(self):
        for start, end, held in (("2026-08-19", "2026-08-25", True),
                                 ("2026-08-20", "2026-08-26", False)):
            r = annual(start_date="2025-10-01", end_date="2026-10-01",
                       annual_scheduled_days=250, annual_attended_days=195,
                       annual_deemed_periods=[dict(kind="short_childcare_leave",
                           start_date=start, end_date=end, scheduled_days=5,
                           application_date="2026-08-01")])
            self.assertEqual(bool(r.held_reason), held)
            if not held:
                self.assertEqual(r.accrued_days, 15)

    def test_first_year_usage_and_current_usage_are_separate(self):
        r = annual(first_year_leave_used=5, first_year_full_attendance_months=11, annual_leave_used=2)
        self.assertEqual((r.accrued_days, r.used_days, r.remaining_days), (15, 2, 13))
        self.assertEqual((r.first_year_accrued_days, r.first_year_remaining_days), (11, 6))
        self.assertEqual(r.first_year_settlement_days, 6)
        self.assertFalse(r.pay_due)
        self.assertIn("평가액", str(r.breakdown))

    def test_part_time_rounds_up_hours_not_days(self):
        r = annual(schedule=WorkSchedule(daily_work_hours=3.1, weekly_work_days=3),
                   annual_original_weekly_hours=None)
        self.assertEqual(r.accrued_hours, 0)  # 9.3h/week, excluded
        r = annual(schedule=WorkSchedule(daily_work_hours=5.1, weekly_work_days=3))
        self.assertEqual(r.accrued_hours, 46)  # ceil(15 * 15.3/40 * 8), not rounded days × 5.1
        self.assertEqual(r.annual_leave_pay, 460000)

    def test_calendar_anniversary_for_february_29_and_month_end(self):
        self.assertEqual(annual(start_date="2024-02-29", end_date="2025-02-28").accrued_days, 11)
        self.assertEqual(annual(start_date="2024-02-29", end_date="2025-03-01").accrued_days, 15)
        self.assertEqual(annual(start_date="2025-01-31", end_date="2025-02-28").accrued_days, 0)
        self.assertEqual(annual(start_date="2025-01-31", end_date="2025-03-01").accrued_days, 1)

    def test_part_time_monthly_grants_and_actual_fiscal_days(self):
        r = annual(end_date="2025-07-01", schedule=WorkSchedule(daily_work_hours=5.1,weekly_work_days=3))
        self.assertEqual(r.accrued_hours, 24)  # monthly ceil(3.06) × six separate grants
        fiscal = annual(use_fiscal_year=True, fiscal_year_granted_days=10,
                        schedule=WorkSchedule(daily_work_hours=5.1,weekly_work_days=3))
        self.assertEqual(fiscal.accrued_hours, 51)  # actual company grant already expressed in employee days

    def test_old_monthly_expiry_and_low_attendance_annual_grant_date(self):
        r = annual(start_date="2019-10-01", end_date="2020-10-01")
        monthly = [s for s in r.schedule if s["kind"]=="monthly"]
        self.assertEqual(monthly[0]["pay_trigger_date"], "2020-11-01")
        self.assertEqual(monthly[5]["pay_trigger_date"], "2020-10-01")
        low = annual(attendance_rate=.7, annual_full_attendance_months=6)
        self.assertEqual(low.pay_trigger_date, "2027-01-01")
        self.assertEqual(low.schedule[-1]["accrual_date"], "2026-01-01")
        self.assertFalse(low.schedule[-1]["conditional"])

    def test_first_year_part_time_ledger_uses_employee_hours(self):
        schedule = WorkSchedule(daily_work_hours=8,weekly_work_days=3)
        r = annual(schedule=schedule,first_year_full_attendance_months=11,first_year_leave_used=2)
        self.assertEqual((r.first_year_accrued_hours,r.first_year_used_hours,r.first_year_remaining_hours),(55,16,39))
        self.assertEqual(r.first_year_settlement_days,39/8)
        at_first_end = annual(end_date="2025-12-31",schedule=schedule,annual_leave_used=2)
        self.assertEqual(r.first_year_remaining_hours,at_first_end.remaining_hours)
        self.assertEqual(at_first_end.first_year_used_days,2)

    def test_low_attendance_part_time_is_one_annual_grant(self):
        r = annual(attendance_rate=.7, annual_full_attendance_months=7,
                   schedule=WorkSchedule(daily_work_hours=8,weekly_work_days=3))
        self.assertEqual(r.accrued_hours,34)  # annual ceil(7×24/40×8)

    def test_company_grant_is_not_labelled_statutory(self):
        r = WageCalculator().calculate(WageInput(wage_type=WageType.HOURLY,hourly_wage=10000,
            start_date="2025-01-01",end_date="2026-07-01",use_fiscal_year=True,fiscal_year_granted_days=10),["annual_leave"])
        self.assertNotIn("법정 연차 발생일수",r.summary)
        self.assertEqual(r.summary["회사 부여 연차일수"],"10일")

    def test_historical_part_time_deducts_actual_used_hours(self):
        r = annual(start_date="2017-01-01",end_date="2018-01-01",first_year_leave_used=2,
                   schedule=WorkSchedule(daily_work_hours=8,weekly_work_days=3))
        self.assertEqual((r.accrued_hours,r.accrued_days),(56,7))

    def test_unsupported_historical_grant_is_held_even_if_query_is_later(self):
        self.assertTrue(annual(start_date="2012-10-01",end_date="2014-07-01",
                               first_year_leave_used=5).held_reason)

    def test_unknown_first_year_usage_does_not_mean_zero(self):
        r = annual(first_year_full_attendance_months=11)
        self.assertEqual(r.first_year_accrued_days,11)
        self.assertIsNone(r.first_year_remaining_days)
        self.assertIsNone(r.first_year_settlement_days)

    def test_historical_first_year_does_not_collapse_expiry_to_anniversary(self):
        r = annual(start_date="2019-10-01",end_date="2020-02-01",first_year_leave_used=0)
        self.assertEqual(r.pay_trigger_date,"")
        self.assertIn("월별",r.breakdown["정산 시점"])
        self.assertNotIn("2020-10-01",r.breakdown["정산 시점"])

    def test_historical_low_attendance_schedule_matches_current_grant(self):
        r = annual(start_date="2017-01-01",end_date="2018-01-01",attendance_rate=.7,
                   annual_full_attendance_months=6,first_year_leave_used=5)
        self.assertEqual((r.accrued_days,r.schedule[-1]["days"],r.schedule[-1]["hours"]),(6,6,48))

    def test_reduced_first_year_usage_alias_requires_actual_hours(self):
        data = dict(end_date="2025-07-01",schedule=WorkSchedule(daily_work_hours=5,weekly_work_days=5),
                    annual_original_weekly_hours=40,annual_original_daily_hours=8,
                    annual_deemed_periods=[dict(kind="childcare_reduced",start_date="2025-01-01",end_date="2025-07-01")])
        self.assertTrue(annual(**data,first_year_leave_used=1).held_reason)
        r = annual(**data,first_year_leave_used=1,annual_leave_used_hours=5)
        self.assertEqual((r.used_hours,r.remaining_hours),(5,43))
        same = annual(**data,first_year_leave_used_hours=5)
        self.assertEqual((same.used_hours,same.remaining_hours),(5,43))

    def test_first_year_reduced_usage_requires_its_own_hours(self):
        data = dict(schedule=WorkSchedule(daily_work_hours=5,weekly_work_days=5),
                    annual_original_weekly_hours=40,annual_original_daily_hours=8,
                    annual_deemed_periods=[dict(kind="childcare_reduced",start_date="2025-01-01",end_date="2025-12-31")],
                    first_year_full_attendance_months=11,first_year_leave_used=1)
        self.assertIsNone(annual(**data).first_year_settlement_days)
        r = annual(**data,first_year_leave_used_hours=5)
        self.assertEqual((r.first_year_accrued_hours,r.first_year_remaining_hours),(88,83))

    def test_schema_covers_all_annual_fields(self):
        from app.templates.prompts import ANALYZE_TOOL
        from wage_calculator.calculators.annual_leave import ANNUAL_INPUT_FIELDS
        self.assertTrue(set(ANNUAL_INPUT_FIELDS) <= set(ANALYZE_TOOL["input_schema"]["properties"]))

    def test_invalid_dates_and_counts_are_held(self):
        for data in (dict(end_date="2026-02-30"), dict(annual_leave_used=-1),
                     dict(attendance_rate=1.1), dict(annual_full_attendance_months=13, attendance_rate=.7),
                     dict(annual_scheduled_days=250, annual_attended_days=251)):
            with self.subTest(data=data):
                self.assertTrue(annual(**data).held_reason)

    def test_fiscal_policy_missing_not_invented(self):
        self.assertTrue(annual(use_fiscal_year=True).held_reason)
        r = annual(use_fiscal_year=True, fiscal_year_granted_days=16, annual_leave_used=5)
        self.assertEqual((r.accrued_days, r.remaining_days), (16, 11))
        self.assertIn("회사", str(r.breakdown))

    def test_pipeline_preserves_annual_facts_and_holds_missing_months(self):
        from app.core.analyzer import _build_analysis_result
        raw = dict(requires_calculation=True, calculation_types=["annual_leave"],
                   wage_type="시급", wage_amount=10000, business_size="5인이상",
                   daily_work_hours=8, weekly_work_days=5, start_date="2025-01-01",
                   end_date="2026-07-01", reference_date="2026-10-23",
                   attendance_rate=.7, annual_full_attendance_months=6, annual_leave_used=2)
        params = _analysis_to_extract_params(_build_analysis_result(raw, "2025년 입사"))
        text = _run_calculator(params, "연차 계산")
        self.assertIn("6.0일", text)
        self.assertIn("4.0일", text)
        raw.pop("annual_full_attendance_months")
        held = _run_calculator(_analysis_to_extract_params(_build_analysis_result(raw, "2025년 입사")), "연차 계산")
        self.assertIn("계산 보류", held)
        self.assertNotIn("월 총 예상 수령액", held)

    # ── wage-update-followups PR-4: L1 적용 제외 사유·첫해 장부·정산 시점을 카드 요약으로 ─────────────────────
    def test_l1_exclusion_reason_is_on_the_card(self):
        for data, expected in ((dict(business_size=BusinessSize.UNDER_5), "0.0일 (5인 미만 사업장 적용 제외)"),
                               (dict(schedule=WorkSchedule(daily_work_hours=2.8, weekly_work_days=5)),
                                "0.0일 (4주 평균 주 소정근로시간 15시간 미만: 미발생)")):
            with self.subTest(expected=expected):
                summary = annual_card(**data).summary
                self.assertEqual(summary["법정 연차 발생일수"], expected)
                self.assertNotIn("단시간 비례", summary)        # '×0.00'은 비례가 아니라 미발생이다
        self.assertIn("주 14시간", annual_card(schedule=WorkSchedule(daily_work_hours=2.8, weekly_work_days=5)).summary["시간 전제"])

    def test_l1_first_year_ledger_held_state_is_on_the_card(self):
        summary = annual_card(first_year_leave_used=5).summary
        self.assertEqual(summary["별도 첫해 장부"],
                         "월별 발생 최대 11일(각 월 개근 시) · 사용 5일 — 월별 개근 수 확인 전 미사용 정산분 확정 보류"
                         "(현재 기간에서 다시 차감하지 않음)")
        self.assertNotIn("별도 첫해 미사용분", summary)   # 개근 수를 모르면 기본 출근율로 11일을 확정하지 않는다

    def test_l1_day_366_retiree_card_shows_first_year_leave(self):
        result = annual_card(end_date="2026-01-01", last_employed_date="2026-01-01")
        self.assertEqual(result.summary["법정 연차 발생일수"], "15.0일")
        self.assertIn("최대 11일", result.summary["별도 첫해 장부"])
        self.assertIn("사용 미확인", result.summary["별도 첫해 장부"])
        self.assertEqual(result.summary["정산 시점"], "2026-01-02 (퇴직 — 마지막 재직일 다음날)")
        self.assertIn("별도 첫해 장부: 월별 발생 최대 11일", format_result(result))
        known = annual_card(end_date="2026-01-01", last_employed_date="2026-01-01",
                            first_year_full_attendance_months=11, first_year_leave_used=0).summary
        self.assertEqual(known["별도 첫해 미사용분"], "11일 (당해 발생분·수당에 합산하지 않음)")
        self.assertNotIn("별도 첫해 장부", known)

    def test_l1_first_year_ledger_not_added_to_later_years_without_facts(self):
        self.assertNotIn("별도 첫해 장부", annual_card(start_date="2023-01-01").summary)
        self.assertIn("별도 첫해 장부", annual_card(start_date="2023-01-01", first_year_leave_used=3).summary)

    def test_l1_settlement_point_is_on_the_card(self):
        self.assertEqual(annual_card().summary["정산 시점"], "2027-01-01 (사용기간 만료 다음날 · 그 전에 퇴직하면 퇴직 시)")
        self.assertEqual(annual_card(end_date=None, last_employed_date="2025-12-31").summary["정산 시점"],
                         "2026-01-01 (퇴직 — 마지막 재직일 다음날)")

    # ── L2 퇴직이 end_date로만 올 때: 조건부 문구(A안) ─────────────────────────────────────────
    def test_l2_end_date_only_is_conditional_not_pre_retirement(self):
        result = annual_card(end_date="2025-12-31")
        self.assertEqual((result.summary["법정 연차 발생일수"], result.summary["연차수당"]), ("11.0일", "880,000원"))
        status = result.summary["연차수당 정산 상태"]
        self.assertIn("마지막 재직일 미확인", status)
        self.assertIn("퇴직했다면 퇴직 시 정산 대상", status)
        self.assertFalse(any("퇴직 전 확정 지급채권으로 보지 않습니다" in w for w in result.warnings))
        self.assertIn("퇴직 시 현재 기간 잔여분",
                      annual_card(end_date=None, last_employed_date="2025-12-31").summary["연차수당 정산 상태"])
        self.assertIn("퇴직 전 확정 지급액 아님", annual_card(end_date=None).summary["연차수당 정산 상태"])

    def test_l2_end_date_on_anniversary_flags_the_day_366_boundary(self):
        flagged = annual(end_date="2026-01-01")
        self.assertTrue(flagged.anniversary_boundary)
        self.assertEqual(flagged.accrued_days, 15)
        self.assertTrue(any("1년 미만 월별 발생분(최대 11일)만" in w for w in flagged.warnings))
        self.assertIn("발생일 경계", annual_card(end_date="2026-01-01").summary)
        for data in (dict(end_date="2026-01-01", last_employed_date="2026-01-01"),
                     dict(end_date="2025-12-31"), dict(end_date="2026-01-02")):
            with self.subTest(data=data):
                self.assertFalse(annual(**data).anniversary_boundary)

    def test_l2_chat_path_retirement_by_end_date_is_conditional(self):
        from app.core.analyzer import _build_analysis_result
        raw = dict(requires_calculation=True, calculation_types=["annual_leave"], wage_type="시급", wage_amount=10000,
                   business_size="5인이상", daily_work_hours=8, weekly_work_days=5, reference_date="2026-10-26",
                   start_date="2025-01-01", end_date="2025-12-31", annual_leave_used=0)
        query = "2025년 1월 1일 입사해서 2025년 12월 31일 퇴사했습니다. 연차를 하나도 안 썼는데 연차수당 얼마인가요?"
        text = _run_calculator(_analysis_to_extract_params(_build_analysis_result(raw, query)), query)
        self.assertIn("퇴직했다면 퇴직 시 정산 대상", text)
        self.assertNotIn("퇴직 전 확정 지급채권으로 보지 않습니다", text)

    # ── L3 육아휴직 출근 간주: 개시일 기준(고용노동부 2018.5 설명자료) ──────────────────────────────────
    def test_l3_childcare_leave_without_application_date_counts(self):
        r = annual(**_FACTS_2025, annual_deemed_periods=[dict(_LEAVE_2025)])
        self.assertEqual((r.held_reason, r.accrued_days), ("", 15))      # 출근율 (150+100)/250
        self.assertIn("근로기준법 제60조제6항제3호", r.deemed_basis_note)
        self.assertIn("개정 근로기준법 설명자료, 2018.5", r.deemed_basis_note)
        self.assertNotIn("부칙", r.deemed_basis_note)     # 2025년 휴직은 해석이 갈리지 않는다 — 조건 문구를 붙이지 않는다
        self.assertTrue(any("2018-05-29 이후 개시한 육아휴직" in line for line in r.legal_basis))
        card = annual_card(**_FACTS_2025, annual_deemed_periods=[dict(_LEAVE_2025)]).summary
        self.assertIn("2025-07-01~2025-12-31", card["출근 간주 기준"])
        short = annual(start_date="2025-10-01", end_date="2026-10-01", annual_scheduled_days=250, annual_attended_days=195,
                       annual_deemed_periods=[dict(kind="short_childcare_leave", start_date="2026-08-20",
                                                   end_date="2026-08-26", scheduled_days=5)])
        self.assertEqual((short.held_reason, short.accrued_days), ("", 15))   # 단기 육아휴직도 신청일을 요구하지 않는다

    def test_l3_split_use_first_applied_before_amendment_counts_with_condition(self):
        r = annual(**_FACTS_2025, annual_deemed_periods=[dict(_LEAVE_2025, application_date="2017-03-01")])
        self.assertEqual((r.held_reason, r.accrued_days), ("", 15))
        self.assertIn("부칙 <제15108호> 제2조", r.deemed_basis_note)
        self.assertIn("최초 신청일 2017-03-01", r.deemed_basis_note)
        card = annual_card(**_FACTS_2025, annual_deemed_periods=[dict(_LEAVE_2025, application_date="2017-03-01")])
        self.assertIn("부칙", card.summary["출근 간주 기준"])
        later = annual(**_FACTS_2025, annual_deemed_periods=[dict(_LEAVE_2025, application_date="2025-06-01")])
        self.assertNotIn("부칙", later.deemed_basis_note)

    def test_l3_start_date_boundary_and_inconsistent_application(self):
        facts = dict(start_date="2017-05-01", end_date="2019-05-01", annual_scheduled_days=250, annual_attended_days=150)
        leave = dict(kind="childcare_leave", end_date="2018-11-30", scheduled_days=100)
        self.assertIn("2018-05-29 전에 시작",
                      annual(**facts, annual_deemed_periods=[dict(leave, start_date="2018-05-28")]).held_reason)
        r = annual(**facts, annual_deemed_periods=[dict(leave, start_date="2018-05-29")])
        self.assertEqual(r.accrued_days, 15)
        self.assertIn("최초 신청일 미기재", r.deemed_basis_note)    # 2018년 개시·신청일 미기재 — 경계 사례라 조건을 붙인다
        self.assertIn("신청일이 휴직 시작일보다 늦습니다",
                      annual(**_FACTS_2025, annual_deemed_periods=[dict(_LEAVE_2025, application_date="2025-08-01")]).held_reason)

    # ── L4 산정기간 소정근로시간 전제와 '×1.00' 정리 ──────────────────────────────────────────
    def test_l4_hours_premise_is_on_one_year_or_more_cards(self):
        premise = annual_card(schedule=WorkSchedule(daily_work_hours=5, weekly_work_days=5)).summary["시간 전제"]
        self.assertIn("2025-01-01~2025-12-31", premise)
        self.assertIn("주 25시간·1일 5시간", premise)
        self.assertEqual(annual(schedule=WorkSchedule(daily_work_hours=5, weekly_work_days=5)).accrued_hours, 75)  # 값은 그대로
        self.assertNotIn("시간 전제", annual_card(start_date="2026-01-01").summary)   # 1년 미만: 현재 기간이 곧 산정기간
        reduced = annual_card(annual_deemed_periods=[dict(_REDUCED, start_date="2025-01-01")], **_FULL_ORIGINAL).summary
        self.assertIn("단축 전 소정근로시간(주 40시간·1일 8시간)", reduced["시간 전제"])

    def test_l4_part_time_ratio_is_shown_in_hours_not_times_one(self):
        card = annual_card(schedule=WorkSchedule(daily_work_hours=5, weekly_work_days=5)).summary
        self.assertEqual((card["연차수당"], card["단시간 비례"]),
                         ("750,000원", "주 25시간 ÷ 40시간 — 발생 75시간(1일 5시간 기준 15일)"))
        self.assertNotIn("×", card["단시간 비례"])

    # ── L6·L6b 주 소정근로시간 부동소수 오차 ─────────────────────────────────────────────────
    def test_l6_weekly_fifteen_hours_split_over_fractional_days_accrues(self):
        for days in (5.5, 6.5):
            with self.subTest(days=days):
                r = annual(schedule=WorkSchedule(daily_work_hours=15 / days, weekly_work_days=days))
                self.assertTrue(r.is_eligible)
                self.assertEqual(r.accrued_hours, 45)
        self.assertFalse(annual(schedule=WorkSchedule(daily_work_hours=14.99 / 5, weekly_work_days=5)).is_eligible)
        # L6b: 같은 카드의 주휴도 같은 헬퍼 — 연차는 발생하는데 주휴는 '15h 미만 0원'인 카드가 나오지 않는다
        card = WageCalculator().calculate(WageInput(
            wage_type=WageType.HOURLY, hourly_wage=10000, business_size=BusinessSize.OVER_5, reference_year=2026,
            reference_date="2026-10-23", start_date="2025-01-01", end_date="2026-07-01",
            schedule=WorkSchedule(daily_work_hours=15 / 5.5, weekly_work_days=5.5)), ["annual_leave", "weekly_holiday"])
        self.assertEqual(card.summary["주휴수당(월)"], "118,506원")
        from wage_calculator.utils import WEEKS_PER_MONTH
        monthly = calc_ordinary_wage(WageInput(wage_type=WageType.MONTHLY, monthly_wage=1_000_000,
                                               schedule=WorkSchedule(daily_work_hours=15 / 5.5, weekly_work_days=5.5)))
        # 월 기준시간에도 주휴 시간(1일 평균 15/5.5h)이 들어간다 — 14.999h로 읽으면 주휴 없이 65.18h가 된다
        self.assertAlmostEqual(monthly.monthly_base_hours, (15 + 15 / 5.5) * WEEKS_PER_MONTH, places=6)

    # ── L7 연도 보정에 last_employed_date ─────────────────────────────────────────────────
    def test_l7_last_employed_date_year_is_corrected_with_other_dates(self):
        from app.core.analyzer import _build_analysis_result
        raw = dict(requires_calculation=True, calculation_types=["annual_leave"], wage_type="시급", wage_amount=10000,
                   business_size="5인이상", daily_work_hours=8, weekly_work_days=5, reference_date="2026-10-26",
                   start_date="2024-03-01", end_date="2024-09-30", last_employed_date="2024-09-30")
        query = "3월 1일 입사해서 9월 30일까지 일하고 그만뒀어요. 연차수당은요?"
        with mock.patch("app.core.analyzer.date", _Today):
            analysis = _build_analysis_result(raw, query)
        info = analysis.extracted_info
        self.assertEqual((info["start_date"], info["last_employed_date"]), ("2026-03-01", "2026-09-30"))
        text = _run_calculator(_analysis_to_extract_params(analysis), query)
        self.assertNotIn("계산 보류", text)
        self.assertIn("법정 연차 발생일수: 6.0일", text)
        self.assertIn("480,000원", text)
        self.assertIn("정산 시점: 2026-10-01 (퇴직", text)
        with mock.patch("app.core.analyzer.date", _Today):     # 연도 단서가 있으면 그대로 둔다
            kept = _build_analysis_result(raw, "2024년 3월 1일 입사, 2024년 9월 30일까지 근무").extracted_info
        self.assertEqual(kept["last_employed_date"], "2024-09-30")

    def test_l7_extract_params_path_corrects_last_employed_date(self):
        from app.core import pipeline
        params = {"needs_calculation": True, "start_date": "2024-03-01", "last_employed_date": "2024-09-30"}
        with mock.patch("app.core.analyzer.date", _Today), \
             mock.patch.object(pipeline.llm_gateway, "tool", return_value=("p", "wage_params", dict(params))):
            kind, out = pipeline._extract_params("3월 1일 입사, 9월 30일까지 근무", object())
        self.assertEqual((kind, out["start_date"], out["last_employed_date"]), ("wage", "2026-03-01", "2026-09-30"))

    # ── L5 리뷰 제안 단언 8개(M3는 L3 결정에 맞춰 개시일 경계로 바꿈) ────────────────────────────
    def test_l5_m1_even_year_increment(self):
        self.assertEqual((annual(start_date="2024-01-01", end_date="2026-01-01").accrued_days,
                          annual(start_date="2022-01-01", end_date="2026-01-01").accrued_days), (15, 16))

    def test_l5_m2_forty_hours_over_six_days_is_full_time(self):
        r = annual(schedule=WorkSchedule(daily_work_hours=40 / 6, weekly_work_days=6))
        self.assertEqual((round(r.accrued_hours, 6), r.accrued_days), (100, 15))

    def test_l5_m3_childcare_start_boundary(self):
        # 리뷰 원안('2018-06-01 시작·2018-05-28 신청 → 보류')은 개시일 기준(L3 a)에서 기대가 뒤집힌다 — 반영하고 조건을 남긴다
        leave = dict(kind="childcare_leave", end_date="2018-12-31", scheduled_days=100, application_date="2018-05-28")
        r = annual(**_FACTS_2018, annual_deemed_periods=[dict(leave, start_date="2018-06-01")])
        self.assertFalse(r.held_reason)
        self.assertIn("최초 신청일 2018-05-28", r.deemed_basis_note)
        facts = dict(start_date="2017-05-01", end_date="2019-05-01", annual_scheduled_days=250, annual_attended_days=150)
        self.assertTrue(annual(**facts, annual_deemed_periods=[dict(leave, start_date="2018-05-28", end_date="2018-11-30",
                                                                    application_date=None)]).held_reason)

    def test_l5_m4_pre_amendment_deduction_only_for_second_year(self):
        r = annual(start_date="2016-03-01", end_date="2018-07-01", first_year_leave_used=5)
        self.assertEqual((r.accrued_days, r.deducted_days), (15, 0))

    def test_l5_m5_short_childcare_leave_must_be_one_or_two_weeks(self):
        self.assertTrue(annual(start_date="2025-10-01", end_date="2026-10-01", annual_scheduled_days=250,
                               annual_attended_days=195, annual_deemed_periods=[dict(kind="short_childcare_leave",
                               start_date="2026-08-20", end_date="2026-08-29", scheduled_days=8,
                               application_date="2026-08-01")]).held_reason)

    def test_l5_m6_pre_amendment_label(self):
        summary = annual_card(start_date="2017-05-29", end_date="2018-07-01", first_year_leave_used=5).summary
        self.assertEqual(summary["개정 전 사건의 첫해 공제"], "5.0일 (2017-05-30 전 입사)")

    def test_l5_m7_reduced_hours_start_boundary_with_original_hours(self):
        held = annual(annual_deemed_periods=[dict(_REDUCED, start_date="2024-10-21")], **_FULL_ORIGINAL)
        self.assertIn("2024-10-22", held.held_reason)
        self.assertEqual(annual(annual_deemed_periods=[dict(_REDUCED, start_date="2024-10-22")], **_FULL_ORIGINAL).accrued_hours, 120)

    def test_l5_m8_low_attendance_monthly_cap_is_twelve(self):
        self.assertEqual(annual(end_date="2026-01-02", attendance_rate=.7, annual_full_attendance_months=12).accrued_days, 12)


def card(labels, query="", **extra):
    return _run_calculator({
        "needs_calculation": True, "wage_type": "월급", "wage_amount": 3000000,
        "reference_year": 2026, "reference_date": "2026-10-23",
        "daily_work_hours": 8, "weekly_work_days": 5,
        "calculation_types_kr": labels, **extra,
    }, query) or ""


class UnexecutedCardTests(unittest.TestCase):
    def assertHeld(self, text):
        self.assertIn("계산 보류", text)
        self.assertNotIn("월 총 예상 수령액", text)
        self.assertNotIn("월 실수령액", text)
        self.assertNotIn("통상시급:", text)

    def test_prorated_unexecuted_hides_monthly_total(self):
        text = card(["일할계산급여"], "10월 16일 퇴사합니다. 10월 급여 일할계산",
                    start_date="2024-01-01", end_date="2026-10-16")
        self.assertHeld(text)
        self.assertNotIn("입사일(join_date)이 없습니다", text)
        self.assertIn("중도퇴사", text)

    def test_direct_skipped_result_has_no_amounts_in_text_or_json(self):
        result = WageCalculator().calculate(
            WageInput(wage_type=WageType.MONTHLY, monthly_wage=3000000), ["prorated"])
        self.assertHeld(format_result(result))
        payload = format_result_json(result)
        self.assertEqual(payload["monthly_total"], 0)
        self.assertEqual(payload["ordinary_hourly"], 0)
        self.assertEqual(payload["summary"], {})
        self.assertEqual(payload["calculation_skipped"][0]["target"], "prorated")

    def test_auxiliary_overtime_does_not_make_skipped_request_successful(self):
        self.assertHeld(card(["일할계산급여"], "일할계산 급여", daily_work_hours=10,
                             premium_paid_separately=True))

    def test_mixed_request_preserves_completed_insurance(self):
        text = card(["일할계산급여", "4대보험"])
        self.assertIn("계산 보류", text)
        self.assertIn("일할계산", text)
        self.assertIn("세전 월 급여", text)
        self.assertIn("월 실수령액", text)

    def test_arrears_requires_principal_and_due_date(self):
        for extra in ({}, {"arrear_amount": 3000000}, {"arrear_due_date": "2026-09-25"}):
            with self.subTest(extra=extra):
                text = card(["임금체불"], **extra)
                self.assertHeld(text)
                self.assertIn("지급기일" if extra.get("arrear_amount") else "원금", text)

    def test_year_end_settlement_is_not_monthly_insurance(self):
        for labels in (["연말정산"], ["4대보험"], []):
            with self.subTest(labels=labels):
                text = card(labels, "월급 300만원입니다. 연말정산 환급액 계산해 주세요.")
                self.assertHeld(text)
                self.assertIn("연말정산", text)

    def test_year_end_notice_preserves_separately_requested_insurance(self):
        text = card(["연말정산", "4대보험"], "연말정산 환급액과 월급의 4대보험 공제액")
        self.assertIn("연말정산", text)
        self.assertIn("계산 보류", text)
        self.assertIn("세전 월 급여", text)

    def test_selective_settlement_is_not_ordinary_working_hours(self):
        for labels in (["선택적 근로시간제"], ["근로시간"]):
            with self.subTest(labels=labels):
                self.assertHeld(card(labels, "선택적 근로시간제 정산기간의 초과근로 계산"))

    def test_unknown_target_does_not_fall_back_to_monthly_wage(self):
        result = WageCalculator().calculate(
            WageInput(wage_type=WageType.MONTHLY, monthly_wage=3000000), ["unsupported"])
        self.assertHeld(format_result(result))

    def test_unsupported_legacy_dispatch_has_no_full_month_salary(self):
        result = WageCalculator().calculate(WageInput(wage_type=WageType.MONTHLY, monthly_wage=3000000),
                                            resolve_calc_type("연말정산"))
        self.assertHeld(format_result(result))

    def test_supported_proration_still_executes(self):
        result = WageCalculator().calculate(WageInput(
            wage_type=WageType.MONTHLY, monthly_wage=3100000, join_date="2026-10-16",
            settlement_month="2026-10",proration_method="calendar",proration_all_items_proportional=True), ["prorated"])
        self.assertIn("1,600,000", format_result(result))
        self.assertNotIn("계산 보류", format_result(result))

    def test_regular_working_hours_is_preserved(self):
        self.assertIn("월 소정근로시간", card(["근로시간"], "주5일 8시간 소정근로시간 계산"))

    def test_analysis_prorated_does_not_fall_back_to_full_month_salary(self):
        analysis = AnalysisResult(requires_calculation=True, calculation_types=["prorated"],
                                  extracted_info={"monthly_wage": 3000000, "wage_type": "월급",
                                                  "start_date": "2024-01-01", "end_date": "2026-10-16"})
        self.assertHeld(_run_calculator(_analysis_to_extract_params(analysis), "10월 16일 퇴사 급여 일할계산"))

    def test_legacy_ordinary_alias_keeps_hourly_wage(self):
        result = WageCalculator().calculate(WageInput(wage_type=WageType.HOURLY, hourly_wage=10000), ["ordinary"])
        self.assertEqual(result.ordinary_hourly, 10000)
        self.assertNotIn("계산 보류", format_result(result))

    def test_invalid_join_date_is_held_instead_of_zero_calculation(self):
        result = WageCalculator().calculate(WageInput(wage_type=WageType.MONTHLY,
                                                      monthly_wage=3000000, join_date="invalid"), ["prorated"])
        self.assertHeld(format_result(result))

    def test_compound_label_preserves_separate_insurance(self):
        text = card(["연말정산/4대보험"], "연말정산과 4대보험을 계산해주세요")
        self.assertIn("계산 보류", text)
        self.assertIn("세전 월 급여", text)

    def test_missing_input_heading_does_not_request_rule_approval(self):
        heading = _calculation_context_heading(card(["일할계산급여"]))
        self.assertNotIn("승인 정보", heading)
        self.assertIn("완료된 항목", heading)

    def test_zero_entitlement_is_a_valid_result(self):
        result = WageCalculator().calculate(WageInput(wage_type=WageType.MONTHLY,
            monthly_wage=3000000, start_date="2026-09-01", end_date="2026-10-16"), ["severance"])
        text = format_result(result)
        self.assertNotIn("계산 보류", text)
        self.assertIn("퇴직금: 0원", text)

    def test_skipped_calculation_still_allows_legal_consultation(self):
        analysis = AnalysisResult(consultation_type="labor_law", consultation_topic="임금")
        self.assertTrue(_consultation_allowed(analysis, card(["일할계산급여"]), None, {}))

    def test_retirement_label_and_unrecognized_label_do_not_default_to_minimum(self):
        for label in ("중도퇴사 급여", "대지급금", "알수없는계산"):
            with self.subTest(label=label):
                self.assertHeld(card([label], f"월급 300만원입니다. {label} 계산해주세요"))

    def test_empty_analysis_label_cannot_complete_unsupported_only_request(self):
        analysis = AnalysisResult(requires_calculation=True, calculation_types=[],
                                  extracted_info={"wage_type": "월급", "monthly_wage": 3000000})
        self.assertHeld(_run_calculator(_analysis_to_extract_params(analysis), "연말정산 환급액만 계산해주세요"))

    def test_insurance_payment_history_is_not_a_separate_calculation_request(self):
        self.assertHeld(card(["4대보험"], "국민연금과 건강보험을 매달 냈습니다. 연말정산 환급액만 계산해주세요"))

    def test_negated_selective_regime_preserves_overtime(self):
        text = card(["연장수당"], "선택적 근로시간제가 아닙니다. 일반 근로자의 연장수당을 계산해주세요",
                    weekly_overtime_hours=5, premium_paid_separately=True)
        self.assertNotIn("계산 보류", text)
        self.assertIn("연장/야간/휴일수당(월)", text)

    def test_separately_requested_regular_hours_are_preserved(self):
        text = card(["선택적 근로시간제", "근로시간"],
                    "선택적 근로시간제 정산과 별도로 일반 근로자의 주5일 하루8시간 소정근로시간도 계산해주세요")
        self.assertIn("계산 보류", text)
        self.assertIn("월 소정근로시간", text)

    def test_compound_supported_labels_preserve_both_outcomes(self):
        for labels in (["일할계산급여/4대보험"], ["4대보험/일할계산급여"], ["연말정산·4대보험"]):
            with self.subTest(labels=labels):
                text = card(labels)
                self.assertIn("계산 보류", text)
                self.assertIn("세전 월 급여", text)

    def test_platform_filter_does_not_replace_requested_proration_with_insurance(self):
        self.assertHeld(card(["일할계산급여"], is_platform_worker=True))

    def test_platform_auto_insurance_does_not_complete_missing_arrears(self):
        self.assertHeld(card(["임금체불"], is_platform_worker=True))

    def test_unknown_request_keeps_independent_known_request(self):
        text = card(["대지급금", "4대보험"])
        self.assertIn("대지급금", text)
        self.assertIn("계산 보류", text)
        self.assertIn("세전 월 급여", text)

    def test_explicit_unsupported_analyzer_type_preserves_valid_mixed_request(self):
        analysis = AnalysisResult(requires_calculation=True,
            calculation_types=["year_end_settlement", "insurance"],
            extracted_info={"wage_type": "월급", "monthly_wage": 3000000})
        text = _run_calculator(_analysis_to_extract_params(analysis))
        self.assertIn("계산 보류", text)
        self.assertIn("연말정산", text)
        self.assertIn("세전 월 급여", text)

    def test_monthly_net_is_preserved_alongside_year_end_settlement(self):
        text = card(["연말정산", "4대보험"], "연말정산 환급액과 매월 실수령액을 각각 계산해주세요")
        self.assertIn("계산 보류", text)
        self.assertIn("월 실수령액", text)

    def test_short_selective_regime_names_are_held(self):
        for query in ("선택근로 정산기간의 초과근로를 계산해주세요", "선택적 근로 정산기간의 초과수당을 계산해주세요"):
            for labels in (["근로시간"], ["연장수당"]):
                with self.subTest(query=query, labels=labels):
                    self.assertHeld(card(labels, query))


_CHAT_BASE = dict(requires_calculation=True, question_summary="q", is_labor_related=True, wage_type="월급",
                  weekly_work_days=5, daily_work_hours=8, reference_year=2026)


def _chat(query, **raw):
    """프로덕션 변환기: analyzer._build_analysis_result → _analysis_to_extract_params → _run_calculator."""
    from app.core.analyzer import _build_analysis_result
    from app.core import pipeline as P
    analysis = _build_analysis_result(dict(_CHAT_BASE, **raw), query)
    return P._run_calculator(P._analysis_to_extract_params(analysis), query) or "", analysis


class CardGuardFollowupTests(unittest.TestCase):
    """빈 계산 유형 폴백·지나가는 연말정산·조건부 예시 지시(wage-update-followups G1·G2·G6)."""
    HELD_TYPE = "요청한 계산 유형을 확인할 수 없습니다"
    YEAR_END = "연말정산 환급·추가납부액 계산은 아직 지원하지 않습니다"

    def test_empty_types_fall_back_only_for_explicit_calculation_requests(self):  # G1
        cases = [
            ("월급 200만원 주5일 하루 8시간인데 최저임금 위반인가요?", dict(wage_amount=2_000_000), "최저임금 충족: ❌ 미달"),
            ("월급 300만원, 2023년 1월 2일 입사해 2026년 10월 1일 퇴사합니다. 퇴직금 얼마인가요?",
             dict(wage_amount=3_000_000, start_date="2023-01-02", end_date="2026-10-01"), "퇴직금: 12,938,057원"),
            ("월급 300만원이면 4대보험 공제액은요?", dict(wage_amount=3_000_000), "세전 월 급여: 3,000,000원"),
            ("시급 12,000원, 주5일 하루 4시간 일해요. 주휴수당 얼마인가요?",
             dict(wage_type="시급", wage_amount=12_000, daily_work_hours=4), "주휴수당(월): 208,571원"),
        ]
        for query, raw, expected in cases:
            with self.subTest(query=query):
                text, _ = _chat(query, calculation_types=[], **raw)
                self.assertIn(expected, text)
                self.assertNotIn(self.HELD_TYPE, text)

    def test_empty_types_keep_notice_and_consultation_for_other_topics(self):  # G1 (R1)
        cases = [
            ("해고당했는데 월급 300만원 기준으로 뭘 받을 수 있나요?", dict(wage_amount=3_000_000)),
            ("부당해고를 당했어요. 월급 300만원, 2023년 1월 2일 입사, 2026년 10월 1일 해고. 퇴직금은 얼마인가요?",
             dict(wage_amount=3_000_000, start_date="2023-01-02", end_date="2026-10-01")),
            ("퇴직금 중간정산이 가능한가요? 월급은 300만원입니다.", dict(wage_amount=3_000_000)),
            ("시급 12,000원, 주5일 하루 4시간인데 이번 주 하루 결근하면 주휴수당 나오나요?",
             dict(wage_type="시급", wage_amount=12_000, daily_work_hours=4)),
        ]
        for query, raw in cases:
            with self.subTest(query=query):
                text, analysis = _chat(query, calculation_types=[], consultation_type="labor_law", **raw)
                self.assertIn(self.HELD_TYPE, text)
                self.assertNotIn("해고예고수당", text)
                self.assertNotIn("📊 임금 계산 결과", text)
                self.assertTrue(_consultation_allowed(analysis, text, None, {}))

    def test_passing_year_end_mention_keeps_requested_insurance(self):  # G2
        for query in ("연말정산은 회사가 알아서 해준다는데, 월급 300만원이면 매달 떼는 4대보험은요?",
                      "연말정산 시즌이라 궁금한데 월급 300만원이면 세후 실수령액이 얼마인가요?",
                      # 지난 일의 서술 — Live 고정 사례 ww26-39 그대로, 결과어가 붙어 있어도 과거형이면 요청이 아니다
                      "월급 300만원(세전, 비과세 수당 없음)을 받는 직장인입니다. 작년 연말정산 때는 환급을 조금 받았어요. "
                      "부양가족은 본인 1명이고, 2026년 10월 기준으로 매달 4대보험을 떼고 나면 실수령액이 얼마인지 계산해주세요.",
                      "연말정산 결과 추가납부가 나왔는데 월급 300만원이면 4대보험은요?"):
            with self.subTest(query=query):
                text, _ = _chat(query, calculation_types=["insurance"], wage_amount=3_000_000)
                self.assertIn("세전 월 급여: 3,000,000원", text)
                self.assertNotIn(self.YEAR_END, text)

    def test_year_end_as_calculation_target_stays_unsupported(self):  # G2 반례
        for query in ("연말정산 환급 얼마나 받을까요? 월급 300만원이에요.",
                      "월급 300만원입니다. 연말정산 환급액 계산해 주세요.",
                      # 결과어와 요청어가 떨어진 같은 절(Codex #137)
                      "월급 300만원입니다. 연말정산 때 받을 수 있는 환급액은 얼마인가요?",
                      "연말정산 환급 받으면 실수령액이 얼마나 늘어요? 월급 300만원이에요."):
            with self.subTest(query=query):
                text, _ = _chat(query, calculation_types=["insurance"], wage_amount=3_000_000)
                self.assertIn(self.YEAR_END, text)
                self.assertNotIn("세전 월 급여", text)
                self.assertNotIn("월 실수령액", text)

    def test_year_end_request_keeps_monthly_net_wording_variants(self):  # G2 실수령 앞말
        text, _ = _chat("연말정산 환급액도 궁금하고 월급 실수령액도 얼마인지 알려주세요. 월급 300만원.",
                        calculation_types=["insurance"], wage_amount=3_000_000)
        self.assertIn(self.YEAR_END, text)
        self.assertIn("세후 실수령액: 2,662,477원", text)

    def test_conditional_example_instruction_survives_unsupported_notice(self):  # G6
        from app.core import pipeline as P
        params = {"needs_calculation": True, "reference_year": 2026, "wage_type": "시급", "wage_amount": 10320,
                  "weekly_work_days": 3, "calculation_types_kr": ["주휴수당", "연말정산"]}
        text = P._run_calculator(params, "시급 10,320원이고 주 3일 하루 6시간씩 일해요. 연말정산이랑 주휴수당 계산해 주세요.")
        self.assertIn(P._CONDITIONAL_EXAMPLE_MARK, text)
        heading = P._calculation_context_heading(text)
        self.assertIn("완료된 항목만", heading)
        self.assertIn("'조건부 예시'는 그 조건을 함께 밝혀서만", heading)


class CalcBasisAnchorTests(unittest.TestCase):
    """계산기 근거 문구의 원문 앵커(wage_calculator/legal_anchors.py, wage-update-followups D-A)."""

    def test_anchor_docs_are_registered_for_collection(self):
        import fetch_official_rules as fo
        from wage_calculator.legal_anchors import CALC_BASIS_ANCHORS
        ids = {a[0] for a in fo.ARTICLES} | {a[0] for a in fo.ADMRULS}
        self.assertTrue(CALC_BASIS_ANCHORS)
        for doc_id, phrase in CALC_BASIS_ANCHORS:
            self.assertIn(doc_id, ids, doc_id)
            self.assertTrue(phrase.strip(), doc_id)

    def test_anchors_exist_in_official_text(self):
        import re
        from pathlib import Path
        from wage_calculator.legal_anchors import CALC_BASIS_ANCHORS
        base = Path(__file__).resolve().parent / "output_공식법령"
        if not base.is_dir():
            self.skipTest("output_공식법령/ 없음 — fetch_official_rules.py --doc 로 수집 후 로컬에서 확인")
        norm = lambda t: re.sub(r"[\s·ㆍ‧]", "", t)  # noqa: E731
        for doc_id, phrase in CALC_BASIS_ANCHORS:
            path = base / f"{doc_id}.md"
            if not path.exists():
                self.fail(f"{doc_id}.md 없음 — fetch_official_rules.py --doc {doc_id}")
            body = path.read_text(encoding="utf-8").split("## 본문", 1)[-1]
            self.assertIn(norm(phrase), norm(body), f"{doc_id}: {phrase}")

    def test_freshness_check_walks_calc_basis_anchors(self):
        import inspect
        import check_law_freshness
        src = inspect.getsource(check_law_freshness._anchor_warnings)
        self.assertIn('("calc_basis", CALC_BASIS_ANCHORS)', src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
