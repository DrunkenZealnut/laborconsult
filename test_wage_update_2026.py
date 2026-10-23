"""2026-10 계산기 갱신 회귀: 사용자 요청이 실제 계산 결과에 대응해야 한다."""
import unittest
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
        self.assertTrue(annual(annual_deemed_periods=[p]).held_reason)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
