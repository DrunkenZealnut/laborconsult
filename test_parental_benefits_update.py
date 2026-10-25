"""C1+C7: dated payment schedules, qualification and end-to-end input preservation."""
import unittest

from wage_calculator.models import WageInput, WageType
from wage_calculator.calculators.ordinary_wage import calc_ordinary_wage
from wage_calculator.calculators.parental_leave import calc_parental_leave


def benefit(reduced=False, **changes):
    inp = WageInput(wage_type=WageType.MONTHLY, monthly_wage=3_000_000,
                    reference_year=2026, reference_date="2026-10-24")
    fields = dict(childcare_example=True, parental_leave_months=12,
                  childcare_insured_days=180, childcare_child_age=1,
                  reduced_weekly_hours_before=40, reduced_weekly_hours_after=30,
                  reduced_months=1)
    fields.update(changes)
    for k,v in fields.items(): setattr(inp,k,v)
    if reduced:
        from wage_calculator.calculators.reduced_work_benefit import calc_reduced_work_benefit
        return calc_reduced_work_benefit(inp,calc_ordinary_wage(inp))
    return calc_parental_leave(inp,calc_ordinary_wage(inp))


class ParentalBenefitsUpdateTests(unittest.TestCase):
    def test_six_plus_six_applies_without_naming_the_scheme(self):
        """6+6은 요건이 되면 그 금액으로 산정한다(시행령 제95조의3①) — 유형을 지정하지 않아도 같은 자녀·상대 부모 사용 사실이
        있으면 6+6을 검증하고, 검증할 수 없으면 일반형으로 확정하지 않고 보류한다(Codex 리뷰 High 3)."""
        from wage_calculator.models import WorkSchedule

        def calc(**kw):
            inp=WageInput(wage_type=WageType.MONTHLY,monthly_wage=5_000_000,reference_date='2026-10-01',
                          schedule=WorkSchedule(daily_work_hours=8,weekly_work_days=5),parental_leave_start='2026-03-01',
                          parental_leave_months=6,childcare_child_birth_date='2025-12-01',childcare_insured_days=180)
            for k,v in kw.items(): setattr(inp,k,v)
            return calc_parental_leave(inp,calc_ordinary_wage(inp))
        other=dict(parental_same_child=True,parental_other_parent_start='2026-01-01',parental_other_parent_months=6)
        auto,named=calc(**other),calc(parental_scheme='six_plus_six',**other)
        self.assertEqual((auto.scheme,auto.total_benefit),('six_plus_six',20_000_000))   # 250·250·300·350·400·450만
        self.assertEqual(auto.total_benefit,named.total_benefit)
        self.assertEqual((calc().scheme,calc().total_benefit),('general',13_500_000))   # 상대 부모 사실 없음
        held=calc(childcare_child_birth_date=None,**other)
        self.assertIn('6+6 특례(고용보험법 시행령 제95조의3)가 적용될 수 있습니다',held.held_reason)
        self.assertFalse(held.total_benefit)

    def test_identical_single_period_dates_are_redundant_not_conflicting(self):
        fields=dict(childcare_example=False,parental_leave_months=0,
                    parental_leave_start='2026-09-01',parental_leave_end='2026-09-07',
                    parental_leave_periods=[dict(start_date='2026-09-01',end_date='2026-09-07',kind='short')],
                    short_parental_reason_eligible=True,short_parental_used_this_year=False)
        self.assertEqual(benefit(**fields).total_benefit,583_333)
        fields['parental_leave_end']='2026-09-14'
        self.assertTrue(benefit(**fields).held_reason)

    def test_explicit_full_calendar_month_survives_missing_analyzer_dates(self):
        from app.core.pipeline import _run_calculator
        params=dict(needs_calculation=True,calculation_types_kr=['육아기 단축급여'],
                    wage_type='월급',wage_amount=3_000_000,
                    reference_date='2026-10-24',reference_year=2026,
                    reduced_weekly_hours_before=40,reduced_weekly_hours_after=30,reduced_months=1)
        question='2026년 10월 한 달, 만 5세 자녀 양육을 위해 주 40시간에서 주 30시간으로 단축합니다.'
        self.assertIn('625,000',_run_calculator(dict(params),question))
        for q in ['2026년 10월에 단축할 예정인데 시작일은 미정입니다.',
                  '2026년 10월 한 달 근무했고 11월에 단축합니다.',
                  '2026년 10월 한 달은 단축하지 않습니다.',
                  '2026년 10월 한 달 육아휴직하고 11월에는 단축합니다.']:
            with self.subTest(q=q):
                self.assertNotIn('625,000',_run_calculator(dict(params),q))

    def test_prenatal_six_plus_six_checks_both_parents(self):
        fields=dict(monthly_wage=5_000_000,childcare_example=False,parental_leave_start='2024-01-01',
                    parental_leave_months=6,childcare_reason='pregnant_self',childcare_child_birth_date='2024-02-01',
                    parental_scheme='six_plus_six',parental_same_child=True,
                    parental_other_parent_start='2025-09-01',parental_other_parent_months=6)
        self.assertTrue(benefit(**fields).held_reason)
        fields.update(parental_leave_start='2024-03-01',childcare_reason='child',
                      parental_other_parent_start='2024-01-01',parental_other_parent_reason='pregnant_self')
        self.assertFalse(benefit(**fields).held_reason)
        fields['parental_other_parent_reason']='child'
        self.assertTrue(benefit(**fields).held_reason)

    def test_resume_special_checks_resumption_age(self):
        r=benefit(childcare_example=False,parental_leave_start="2026-09-01",parental_leave_months=1,
                  parental_prior_months=3,parental_first_leave_start="2025-03-01",
                  childcare_child_birth_date="2025-01-01",parental_scheme="six_plus_six",
                  parental_same_child=True,parental_other_parent_start="2025-06-01",parental_other_parent_months=6)
        self.assertTrue(r.held_reason)

    def test_special_checks_each_split_start_for_both_parents(self):
        fields=dict(childcare_example=False,parental_leave_months=0,
                    childcare_child_birth_date='2025-01-01',parental_scheme='six_plus_six',
                    parental_same_child=True,parental_other_parent_start='2025-06-01',
                    parental_other_parent_months=6)
        periods=[dict(start_date='2025-03-01',end_date='2025-05-31'),
                 dict(start_date='2026-09-01',end_date='2026-11-30')]
        self.assertTrue(benefit(**fields,parental_leave_periods=periods).held_reason)
        fields.update(parental_other_parent_start=None,parental_other_parent_periods=periods)
        self.assertTrue(benefit(**fields,parental_leave_start='2025-06-01',
                               parental_leave_end='2025-11-30').held_reason)

    def test_continuous_special_can_continue_beyond_age_limit(self):
        r=benefit(monthly_wage=5_000_000,childcare_example=False,
                  parental_leave_start='2026-06-01',parental_leave_months=6,
                  childcare_child_birth_date='2025-01-01',parental_scheme='six_plus_six',
                  parental_same_child=True,parental_other_parent_start='2026-06-01',
                  parental_other_parent_months=6)
        self.assertFalse(r.held_reason,r.held_reason)
        self.assertEqual([row['payment'] for row in r.monthly_schedule],
                         [2_500_000,2_500_000,3_000_000,3_500_000,4_000_000,4_500_000])

    def test_pregnancy_reason_cannot_bypass_postnatal_split_eligibility(self):
        r=benefit(childcare_example=False,parental_leave_months=0,
                  childcare_reason='pregnant_self',childcare_child_birth_date='2024-02-01',
                  parental_leave_periods=[dict(start_date='2024-01-01',end_date='2024-01-31'),
                                          dict(start_date='2026-09-01',end_date='2026-09-30')])
        self.assertTrue(r.held_reason)

    def test_explicit_invalid_fields_and_conflicting_periods_are_held(self):
        for data in [dict(childcare_example="false"),dict(parental_leave_months=1.5),
                     dict(parental_leave_start="2026-01-01",parental_leave_end="2026-01-31",parental_leave_months=2),
                     dict(parental_leave_periods=[dict(start_date="2026-01-01",end_date="2026-01-31")],parental_leave_months=2)]:
            with self.subTest(data=data): self.assertTrue(benefit(**data).held_reason)

    def test_short_leave_requires_born_child_care(self):
        r=benefit(childcare_example=False,childcare_reason="pregnant_self",parental_leave_months=0,
                  parental_leave_periods=[dict(start_date="2026-09-01",end_date="2026-09-07",kind="short")],
                  short_parental_reason_eligible=True,short_parental_used_this_year=False)
        self.assertTrue(r.held_reason)

    def test_parental_parts_reconcile_to_rounded_payment(self):
        for wage in [950_003,1_000_002,1_530_012,2_000_003]:
            r=benefit(monthly_wage=wage,childcare_example=False,parental_leave_start="2024-12-15",parental_leave_months=1)
            for row in r.monthly_schedule:
                self.assertEqual(row['gross'],row['payment']+row['deferred']+row['employer_reduction'])

    def test_unverified_midmonth_partial_does_not_exceed_full_month(self):
        # 17/31 + 13/28 would exceed one month's pay for a 30-day partial month.
        r=benefit(childcare_example=False,parental_leave_start="2026-01-15",
                  parental_leave_end="2026-02-13",parental_leave_months=0)
        self.assertTrue(r.held_reason)

    def test_parental_2026_general_12_months(self):
        r=benefit()
        self.assertEqual(r.total_benefit,23_100_000)
        self.assertEqual(r.total_deferred,0)
        self.assertEqual([x['payment'] for x in r.monthly_schedule],
                         [2_500_000]*3+[2_000_000]*3+[1_600_000]*6)

    def test_parental_crosses_20250101(self):
        r=benefit(childcare_example=False,parental_leave_start="2024-10-01",parental_leave_months=6)
        self.assertEqual([x['month_index'] for x in r.monthly_schedule],list(range(1,7)))
        self.assertEqual([x['payment'] for x in r.monthly_schedule],[1_125_000]*3+[2_000_000]*3)
        self.assertEqual(r.total_deferred,1_125_000)

    def test_old_floor_applies_to_actual_payment(self):
        for wage,gross,paid,deferred in [(500_000,700_000,700_000,0),(1_000_000,800_000,700_000,100_000)]:
            r=benefit(monthly_wage=wage,reference_date="2024-01-01",parental_leave_months=1)
            self.assertEqual((r.monthly_benefit_before_deferred,r.total_benefit,r.total_deferred),(gross,paid,deferred))

    def test_six_plus_six_matches_parent_durations(self):
        r=benefit(monthly_wage=5_000_000,parental_scheme="six_plus_six",
                  parental_other_parent_months=4,parental_same_child=True,
                  childcare_child_birth_date="2025-01-01",parental_other_parent_start="2025-06-01",
                  childcare_example=False,parental_leave_start="2025-03-01",parental_leave_months=6)
        self.assertEqual([x['payment'] for x in r.monthly_schedule],
                         [2_500_000,2_500_000,3_000_000,3_500_000,2_000_000,2_000_000])
        self.assertTrue(benefit(parental_scheme="six_plus_six").held_reason)
        self.assertTrue(benefit(is_second_parent=True).held_reason)

    def test_single_parent_and_extension_are_separate(self):
        r=benefit(parental_scheme="single_parent",parental_single_parent_eligible=True,parental_leave_months=18)
        self.assertEqual(r.total_benefit,34_200_000)
        self.assertEqual(len(r.monthly_schedule),18)
        self.assertTrue(benefit(parental_leave_months=18).held_reason)
        self.assertEqual(len(benefit(parental_leave_months=18,parental_disabled_child_eligible=True).monthly_schedule),18)
        self.assertTrue(benefit(parental_leave_months=19,parental_disabled_child_eligible=True).held_reason)

    def test_missing_and_invalid_dates_do_not_become_today(self):
        self.assertTrue(benefit(childcare_example=False).held_reason)
        self.assertTrue(benefit(childcare_example=False,parental_leave_start="2026-02-30").held_reason)
        self.assertTrue(benefit(parental_leave_months=0).held_reason)
        self.assertTrue(benefit(reference_date="bad").held_reason)

    def test_child_age_or_grade_and_pregnancy(self):
        self.assertTrue(benefit(childcare_child_age=9,childcare_child_grade=3).held_reason)
        self.assertFalse(benefit(childcare_child_age=9,childcare_child_grade=2).held_reason)
        self.assertFalse(benefit(childcare_child_age=None,childcare_reason="pregnant_self").held_reason)
        self.assertTrue(benefit(childcare_reason="pregnant_spouse",reference_date="2026-09-17",childcare_spouse_risk_eligible=True).held_reason)
        self.assertFalse(benefit(childcare_reason="pregnant_spouse",reference_date="2026-09-18",childcare_spouse_risk_eligible=True).held_reason)
        self.assertTrue(benefit(childcare_insured_days=179).held_reason)

    def test_short_parental_7_14_days(self):
        for days in [7,14]:
            r=benefit(childcare_example=False,parental_leave_months=0,
                      parental_leave_periods=[dict(start_date="2026-09-01",end_date=f"2026-09-{days:02d}",kind="short")],
                      short_parental_reason_eligible=True,short_parental_used_this_year=False)
            self.assertFalse(r.held_reason,r.held_reason)
            self.assertEqual(r.total_benefit,round(2_500_000*days/30))
        for start,end,extra in [("2026-08-19","2026-08-25",{}),("2026-09-01","2026-09-08",{}),
                                ("2026-09-01","2026-09-07",{'childcare_insured_days':179}),
                                ("2026-09-01","2026-09-07",{'short_parental_used_this_year':True})]:
            kwargs=dict(childcare_example=False,parental_leave_months=0,
                        parental_leave_periods=[dict(start_date=start,end_date=end,kind="short")],
                        short_parental_reason_eligible=True,short_parental_used_this_year=False)
            kwargs.update(extra);self.assertTrue(benefit(**kwargs).held_reason)

    def test_full_midmonth_and_partial_month(self):
        r=benefit(childcare_example=False,parental_leave_start="2026-01-15",parental_leave_months=1)
        self.assertEqual(r.total_benefit,2_500_000)
        r=benefit(childcare_example=False,parental_leave_start="2026-01-01",parental_leave_end="2026-02-10",parental_leave_months=0)
        self.assertEqual(r.total_benefit,2_500_000+round(2_500_000*10/28))

    def test_split_periods_preserve_month_index_and_reject_overlap(self):
        periods=[dict(start_date="2026-01-01",end_date="2026-03-31"),dict(start_date="2026-07-01",end_date="2026-09-30")]
        r=benefit(childcare_example=False,parental_leave_periods=periods,parental_leave_months=0)
        self.assertEqual([x['payment'] for x in r.monthly_schedule],[2_500_000]*3+[2_000_000]*3)
        self.assertTrue(benefit(childcare_example=False,parental_leave_periods=periods+periods[:1],parental_leave_months=0).held_reason)

    def test_parental_employer_payment_offset(self):
        r=benefit(parental_leave_months=1,childcare_employer_monthly_payment=1_000_000)
        self.assertEqual(r.total_benefit,2_000_000)
        self.assertEqual(r.monthly_schedule[0]['employer_reduction'],500_000)

    def test_reduced_40_to_30_2026(self):
        r=benefit(True)
        self.assertEqual(r.total_benefit,625_000)
        self.assertEqual(r.monthly_schedule[0]['first_part'],625_000)
        self.assertEqual(r.monthly_schedule[0]['remaining_part'],0)

    def test_reduced_over_ten_hours_and_floors(self):
        self.assertEqual(benefit(True,reduced_weekly_hours_after=20).total_benefit,1_025_000)
        self.assertEqual(benefit(True,monthly_wage=400_000).total_benefit,125_000)
        self.assertTrue(benefit(True,reduced_weekly_hours_after=14).held_reason)
        self.assertTrue(benefit(True,reduced_weekly_hours_after=36).held_reason)

    def test_reduced_crosses_20260101(self):
        r=benefit(True,childcare_example=False,reduced_start="2025-12-01",reduced_end="2026-01-31",reduced_months=0)
        self.assertEqual([x['payment'] for x in r.monthly_schedule],[550_000,625_000])
        r=benefit(True,childcare_example=False,reduced_start="2024-06-01",reduced_end="2024-07-31",reduced_months=0)
        self.assertEqual([x['payment'] for x in r.monthly_schedule],[437_500,500_000])

    def test_reduced_partial_and_employer_offset(self):
        r=benefit(True,childcare_example=False,reduced_start="2026-01-01",reduced_end="2026-02-10",reduced_months=0)
        self.assertEqual(r.total_benefit,625_000+round(625_000*10/28))
        r=benefit(True,childcare_employer_monthly_payment=2_500_000,reduced_offset_monthly_ordinary_wage=3_000_000)
        self.assertEqual(r.total_benefit,500_000)

    def test_reduced_duration_uses_only_unused_normal_year(self):
        self.assertEqual(len(benefit(True,reduced_months=36,reduced_unused_parental_months=12).monthly_schedule),36)
        self.assertTrue(benefit(True,reduced_months=37,reduced_unused_parental_months=12).held_reason)
        self.assertTrue(benefit(True,reduced_months=36,reduced_unused_parental_months=18).held_reason)
        self.assertTrue(benefit(True,reduced_months=13).held_reason)
        self.assertFalse(benefit(True,childcare_child_age=13,childcare_child_grade=6).held_reason)

    def test_reduced_standalone_no_parental_months(self):
        from app.core.pipeline import _analysis_to_extract_params,_run_calculator
        from app.models.schemas import AnalysisResult
        from wage_calculator.facade.registry import resolve_calc_type_strict
        from app.core.analyzer import _build_analysis_result
        info=dict(wage_type="월급",wage_amount=3_000_000,reference_date="2026-10-24",reference_year=2026,
                  childcare_example=True,reduced_months=1,reduced_weekly_hours_before=40,reduced_weekly_hours_after=30)
        a=_build_analysis_result(dict(info,requires_calculation=True,calculation_types=['reduced_work_benefit']))
        params=_analysis_to_extract_params(a)
        self.assertEqual(params['reduced_weekly_hours_before'],40)
        text=_run_calculator(params,"통상임금 300만원, 2026년 주 40시간에서 30시간 단축 시 한 달 급여 예시")
        self.assertIn("625,000",text)
        self.assertNotIn("육아휴직 총 수령액",text)
        self.assertNotIn("월 총 예상 수령액",text)
        self.assertEqual(resolve_calc_type_strict("육아기 근로시간 단축급여"),['reduced_work_benefit'])

    def test_benefits_only_card_does_not_present_prior_wage_as_payment(self):
        from wage_calculator.facade import WageCalculator
        inp=WageInput(wage_type=WageType.MONTHLY,monthly_wage=3_000_000,
                      reference_date='2026-10-24',reference_year=2026,
                      childcare_example=True,parental_leave_months=12)
        r=WageCalculator().calculate(inp,['parental_leave'])
        self.assertEqual(r.monthly_total,0)
        self.assertIn('23,100,000',str(r.summary))
        # A separately requested wage calculation still has its own wage total.
        r=WageCalculator().calculate(inp,['parental_leave','insurance'])
        self.assertEqual(r.monthly_total,3_000_000)


if __name__ == '__main__':
    unittest.main()
