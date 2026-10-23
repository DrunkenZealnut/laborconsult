"""2026-10 계산기 갱신 회귀: 사용자 요청이 실제 계산 결과에 대응해야 한다."""
import unittest

from app.core.pipeline import _run_calculator
from wage_calculator.facade import WageCalculator
from wage_calculator.facade.registry import resolve_calc_type
from wage_calculator.models import WageInput, WageType
from wage_calculator.result import format_result, format_result_json
from app.models.schemas import AnalysisResult
from app.core.pipeline import _analysis_to_extract_params, _calculation_context_heading, _consultation_allowed


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

    def test_retirement_proration_without_supported_inputs(self):
        self.assertHeld(card(["일할계산급여"], "10월 16일 퇴사합니다. 10월 급여 일할계산",
                             start_date="2024-01-01", end_date="2026-10-16"))

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
                self.assertIn("지급기일", text)

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
            wage_type=WageType.MONTHLY, monthly_wage=3100000, join_date="2026-10-16"), ["prorated"])
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
