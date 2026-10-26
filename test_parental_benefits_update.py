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
        # 자녀가 생후 18개월을 넘은 뒤 시작한 휴직이면 6+6은 확정적으로 해당하지 않는다 — 일반형을 그대로 낸다(PR #134 Codex 리뷰)
        older=calc(childcare_child_birth_date='2021-12-01',**other)
        self.assertEqual((older.held_reason,older.scheme,older.total_benefit),('','general',13_500_000))
        # 상대 부모 구간이 불완전하면 예외가 아니라 보류다(PR #134 Codex 재리뷰: KeyError 'start_date')
        broken=calc(parental_same_child=True,parental_other_parent_periods=[{'end_date':'2026-06-30'}])
        self.assertTrue(broken.held_reason)
        self.assertFalse(broken.total_benefit)

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


def _chat(tool_input, query):
    """프로덕션 변환기: analyzer._build_analysis_result → _analysis_to_extract_params → _run_calculator."""
    from app.core.analyzer import _build_analysis_result
    from app.core.pipeline import _analysis_to_extract_params, _run_calculator
    analysis = _build_analysis_result(dict(tool_input, requires_calculation=True, is_labor_related=True), query)
    return _run_calculator(_analysis_to_extract_params(analysis), query)


class MaternityFamilyFollowupTests(unittest.TestCase):
    """출산·난임 근거와 상한(wage-update-followups PR-2a: P3·P3b·P4·P6·P6b)."""

    def maternity(self, **kw):
        from wage_calculator.models import WorkSchedule
        from wage_calculator.calculators.maternity_leave import calc_maternity_leave
        inp = WageInput(wage_type=WageType.MONTHLY, monthly_wage=5_000_000, reference_year=2026,
                        reference_date="2026-05-01", schedule=WorkSchedule(daily_work_hours=8, weekly_work_days=5))
        for k, v in kw.items(): setattr(inp, k, v)
        return calc_maternity_leave(inp, calc_ordinary_wage(inp))

    def test_large_company_multiple_birth_uses_75_45_days_without_subtype(self):
        """P3: 유형 미지정(CLI·라이브러리) 다태아 대규모도 사업주 75일·보험 45일(제74조④, 제76조①1호 단서)."""
        r = self.maternity(is_priority_support_company=False, is_multiple_birth=True)
        self.assertEqual((r.employer_covered_days, r.insurance_covered_days, r.total_insurance_benefit),
                         (75, 45, 3_300_000))
        self.assertTrue(any("최초 75일" in w and "76일~120일 중 최대 45일" in w for w in r.warnings), r.warnings)
        r = self.maternity(is_priority_support_company=False, is_premature_birth=True)
        self.assertEqual((r.employer_covered_days, r.insurance_covered_days), (60, 40))
        self.assertTrue(any("61일~100일 중 최대 40일" in w for w in r.warnings), r.warnings)

    def test_auto_path_large_company_employer_pay_uses_ordinary_wage(self):
        """P3b: 사업주 유급분은 통상임금 기준 — 보험 상한 일액(4,400,000)이 아니라 유형 지정 경로와 같은 값."""
        self.assertEqual(self.maternity(is_priority_support_company=False).total_employer_benefit, 10_000_000)
        self.assertEqual(self.maternity(is_priority_support_company=False, is_multiple_birth=True)
                         .total_employer_benefit, 12_500_000)
        explicit = self.maternity(is_priority_support_company=False, maternity_leave_type="maternity",
                                  family_leave_days=90, family_leave_used_days=0,
                                  family_leave_start_date="2026-05-01", family_leave_end_date="2026-07-29",
                                  family_leave_insured_days=400, family_leave_eligible=True)
        self.assertFalse(explicit.held_reason, explicit.held_reason)
        self.assertEqual(explicit.total_employer_benefit, 10_000_000)

    def test_premature_multiple_large_company_holds_insurance_total(self):
        """P3: 미숙아이면서 다태아인 대규모는 보험 한도(40일·45일)를 법문이 정하지 않는다 — 보험 총액만 보류."""
        from wage_calculator.facade import WageCalculator
        r = self.maternity(is_priority_support_company=False, is_multiple_birth=True, is_premature_birth=True)
        self.assertIsNone(r.total_insurance_benefit)
        self.assertEqual(r.total_employer_benefit, 12_500_000)
        self.assertTrue(any("법문이 정하지 않아" in w for w in r.warnings), r.warnings)
        from wage_calculator.models import WorkSchedule
        inp = WageInput(wage_type=WageType.MONTHLY, monthly_wage=5_000_000, reference_year=2026,
                        reference_date="2026-05-01", schedule=WorkSchedule(daily_work_hours=8, weekly_work_days=5),
                        is_priority_support_company=False, is_multiple_birth=True, is_premature_birth=True)
        summary = WageCalculator().calculate(inp, ["maternity_leave"]).summary
        self.assertIn("미확정", summary["고용보험 지급 총액"])

    def test_legal_basis_cites_article_76_items_not_article_75_paragraphs(self):
        """P3: 제75조에는 항이 없고 제75조의2는 수급권 대위다 — 지급 기간 근거는 제76조①각 호."""
        from wage_calculator.calculators.family_leave import calc_family_leave
        texts = []
        for kw in (dict(is_priority_support_company=True), dict(is_priority_support_company=False),
                   dict(is_priority_support_company=True, reference_date="2026-10-01")):
            texts += self.maternity(**kw).legal_basis
        inp = WageInput(wage_type=WageType.MONTHLY, monthly_wage=3_000_000, maternity_leave_type="infertility",
                        family_leave_start_date="2026-10-01", family_leave_end_date="2026-10-02", family_leave_days=2,
                        family_leave_used_days=0, family_leave_insured_days=400, family_leave_eligible=True,
                        is_priority_support_company=True)
        texts += calc_family_leave(inp, calc_ordinary_wage(inp)).legal_basis
        joined = " / ".join(texts)
        for wrong in ("제75조제1항", "제75조제2항", "제75조의2", "급여등 규정"):
            self.assertNotIn(wrong, joined)
        for item in ("제76조제1항제1호", "제76조제1항제1호 단서", "제76조제1항제2호", "제76조제1항제3호",
                     "제76조제1항제4호"):
            self.assertIn(item, joined)

    def infertility(self, start, end, days, used=0):
        return _chat(dict(calculation_types=["maternity_leave"], wage_type="월급", wage_amount=5_000_000,
                          weekly_work_days=5, daily_work_hours=8, maternity_leave_type="infertility",
                          family_leave_days=days, family_leave_used_days=used, family_leave_start_date=start,
                          family_leave_end_date=end, family_leave_insured_days=400, family_leave_eligible=True,
                          is_priority_support_company=True),
                     f"난임치료휴가 {start}~{end} {days}일. 월급 500만원, 우선지원대상기업")

    def test_infertility_days_3_and_4_are_unconfirmed_after_20261127(self):
        """P4(Q3 a): 고시는 최초 2일분 상한만 정한다 — 1·2일째는 확정, 3·4일째는 미확정. 사업주 유급액은 확정."""
        out = self.infertility("2026-12-01", "2026-12-04", 4)
        self.assertIn("난임치료휴가 사업주 유급액: 767,123원", out)
        self.assertIn("2일분 168,420원은 그 상한 이내로 확정", out)
        self.assertIn("나머지 2일분은 상한 고시가 정해지지 않아", out)
        self.assertNotIn("336,840", out)
        self.assertNotIn("사업주 잔여 부담", out)
        self.assertNotIn("whatsnew.mofe.go.kr", out)
        self.assertIn("168,420원", self.infertility("2026-10-05", "2026-10-06", 2))   # 2일 유급 시기는 그대로

    def test_daily_cap_expires_with_the_notice(self):
        """P4: 고시 제2026-67호는 2026-12-31까지 효력 — 그 뒤 1일 상한은 미등록(외삽 금지)."""
        from wage_calculator.models import WorkSchedule
        from wage_calculator.calculators.maternity_leave import calc_maternity_leave, daily_leave_cap
        self.assertEqual(daily_leave_cap("infertility", "2026-12-31"), (84_210, 2))
        self.assertEqual(daily_leave_cap("spouse_miscarriage", "2026-12-31"), (84_210, 3))
        self.assertEqual(daily_leave_cap("infertility", "2027-01-01"), (None, 0))
        inp = WageInput(wage_type=WageType.HOURLY, hourly_wage=15_000, reference_year=2026, reference_date="2026-12-01",
                        schedule=WorkSchedule(daily_work_hours=8, weekly_work_days=5), is_priority_support_company=True)
        r = calc_maternity_leave(inp, calc_ordinary_wage(inp))
        self.assertEqual((r.infertility_paid_days, r.infertility_pay, r.infertility_insurance_benefit), (4, 480_000, None))
        self.assertEqual(r.spouse_miscarriage_insurance_benefit, 252_630)

    def test_infertility_paid_days_switch_at_20261127_and_count_prior_use(self):
        """P4: 11-26 사용은 유급 2일, 11-27부터 4일. 시행 전 사용분도 4일에 센다(부칙 <제21700호> 제2조)."""
        from wage_calculator.calculators.family_leave import calc_family_leave

        def run(start, end, days, used):
            inp = WageInput(wage_type=WageType.HOURLY, hourly_wage=15_000, maternity_leave_type="infertility",
                            family_leave_start_date=start, family_leave_end_date=end, family_leave_days=days,
                            family_leave_used_days=used, family_leave_insured_days=400, family_leave_eligible=True,
                            is_priority_support_company=True)
            return calc_family_leave(inp, calc_ordinary_wage(inp))

        r = run("2026-11-24", "2026-11-26", 3, 0)
        self.assertEqual((r.paid_days, r.employer_pay, r.insurance_benefit), (2, 240_000, 168_420))
        r = run("2026-11-27", "2026-11-30", 4, 0)
        self.assertEqual((r.paid_days, r.employer_pay, r.insurance_benefit), (4, 480_000, None))
        r = run("2026-11-27", "2026-11-28", 2, 2)     # 시행 전 2일 사용 → 남은 유급 2일, 상한 확정분 0일
        self.assertEqual((r.paid_days, r.employer_pay, r.insurance_benefit), (2, 240_000, None))
        self.assertTrue(any("이번 사용분은 나머지 2일분" in w for w in r.warnings), r.warnings)
        r = run("2026-11-27", "2026-11-27", 1, 3)     # 잔여 상한이 음수가 되지 않는다(확정 0일)
        self.assertEqual((r.paid_days, r.employer_pay, r.insurance_benefit), (1, 120_000, None))
        self.assertTrue(any("이번 사용분은 나머지 1일분" in w for w in r.warnings), r.warnings)
        self.assertTrue(run("2026-11-26", "2026-11-27", 2, 0).held_reason)   # 시행일을 걸치면 구간별 확인

    def test_public_pages_drop_old_maternity_and_parental_texts(self):
        """P6·P6b: 공개 화면의 옛 육아휴직 상한과 대규모 다태아 60/60일 분배를 남기지 않는다."""
        import json, subprocess
        from pathlib import Path
        root = Path(__file__).resolve().parent
        menu = (root / "public/calculators.html").read_text(encoding="utf-8")
        self.assertNotIn("상한 150만원", menu)
        self.assertIn("1~3개월 100%(상한 250만)", menu)
        self.assertIn("미숙아 100", menu)
        flow = root / "public/calculator_flow/maternity_leave_benefit_flow.html"
        html = flow.read_text(encoding="utf-8")
        self.assertEqual(flow.read_bytes(), (root / "wage_calculator/calculator_flow" / flow.name).read_bytes())
        self.assertIn("babyType==='single'?60:75", html)
        self.assertIn(">처음 75일<", html)
        self.assertIn(">나머지 45일<", html)
        # 화면 계산식을 그대로 돌려 대규모 다태아(월 500만)의 분배를 계산기와 대조한다
        script = next(b.split("</script>")[0] for b in html.split("<script>") if "function calc(" in b)
        js = ("var els={};var document={getElementById:function(i){return els[i]||(els[i]={value:'500',"
              "style:{},textContent:'',innerHTML:''});}};" + script
              + ";setType('multi');setSize('large');calc();"
                "console.log(JSON.stringify({d:els.detail.innerHTML,t:els.totalPay.textContent}));")
        try:
            out = json.loads(subprocess.check_output(["node", "-e", js], text=True))
        except FileNotFoundError:
            self.skipTest("node 없음")
        self.assertIn("처음 75일 (사업주: 통상임금 전액)", out["d"])
        self.assertIn("12,500,000원", out["d"])
        self.assertIn("나머지 45일 (고용보험)", out["d"])
        self.assertIn("3,300,000원", out["d"])
        self.assertEqual(out["t"], "15,800,000원")


PARENTAL_2025 = dict(calculation_types=["parental_leave"], wage_type="월급", wage_amount=3_000_000,
                     childcare_example=False, parental_leave_start="2025-03-01", parental_leave_end="2025-05-31",
                     childcare_child_age=1, childcare_insured_days=400)
Q_PARENTAL = "2025년 3월 1일부터 5월 31일까지 만 1세 아이 육아휴직을 썼습니다. 월급 300만원인데 육아휴직급여가 얼마였나요?"
REDUCED_2025 = dict(calculation_types=["reduced_work_benefit"], wage_type="월급", wage_amount=3_000_000,
                    childcare_example=False, reduced_start="2025-03-01", reduced_end="2025-05-31",
                    reduced_weekly_hours_before=40, reduced_weekly_hours_after=30, childcare_child_age=5,
                    childcare_insured_days=400)
Q_REDUCED = "2025년 3월 1일부터 5월 31일까지 만 5세 아이 때문에 주 40시간에서 30시간으로 단축했습니다. 단축급여 얼마였나요?"


class ChildcareReferenceDateTests(unittest.TestCase):
    """P1: 실제 사용 구간이 있으면 첫 개시일이 기준일이다(wage-update-followups PR-2b)."""

    def test_actual_periods_do_not_need_reference_date_for_past_year(self):
        """연도만 지목돼도 실제 구간이 있으면 보류하지 않는다 — 지급액은 구간별 시행 규칙으로 정해진다."""
        out = _chat(dict(PARENTAL_2025, reference_year=2025), Q_PARENTAL)
        self.assertIn("육아휴직 총 수령액: 7,500,000원", out)
        self.assertNotIn("계산 기준일(YYYY-MM-DD)이 필요합니다", out)
        out = _chat(dict(REDUCED_2025, reference_year=2025), Q_REDUCED)
        self.assertIn("고용보험 단축급여 합계: 1,650,000원", out)
        self.assertNotIn("계산 기준일(YYYY-MM-DD)이 필요합니다", out)

    def test_after_new_year_last_year_leave_is_still_calculated(self):
        """기한(2027-01-01): 새해에 '작년 휴직'을 물어도 보류되지 않는다."""
        from unittest.mock import patch
        with patch("wage_calculator.legal_rules.kst_today", return_value="2027-01-05"):
            out = _chat(dict(PARENTAL_2025, reference_year=2026, parental_leave_start="2026-03-01",
                             parental_leave_end="2026-05-31"),
                        "2026년 3월 1일부터 5월 31일까지 만 1세 육아휴직. 월급 300만원")
        self.assertIn("육아휴직 총 수령액: 7,500,000원", out)

    def test_dateless_example_still_needs_date_for_other_year(self):
        """가드: '연도만으로 추정 금지'는 날짜 없는 제도 예시에 그대로 남는다."""
        r = benefit(reference_date=None, reference_year=2025, parental_leave_months=3)
        self.assertIn("계산 기준일", r.held_reason)

    def test_mixed_request_keeps_other_calculations_reference_year(self):
        """R3: 같은 요청의 최저임금은 여전히 2025년 기준(10,030원)으로 판정하고, 육아휴직은 첫 개시일로 계산한다."""
        out = _chat(dict(PARENTAL_2025, calculation_types=["parental_leave", "minimum_wage"], reference_year=2025),
                    Q_PARENTAL + " 최저임금 위반인지도 알려주세요")
        self.assertIn("2025년 최저임금: 10,030원/h", out)
        self.assertIn("육아휴직 총 수령액: 7,500,000원", out)


class Rule2024AmountTests(unittest.TestCase):
    """P5: 2024 판본 금액 단언(코드 무변경). 기존 테스트로는 2024 상한·특례월 사후지급 변이가 살아남았다."""

    def calc(self, **changes):
        inp = WageInput(wage_type=WageType.MONTHLY, monthly_wage=5_000_000, reference_year=2026,
                        reference_date="2026-10-24")
        fields = dict(childcare_example=False, childcare_insured_days=180, childcare_child_age=1)
        fields.update(changes)
        for k, v in fields.items(): setattr(inp, k, v)
        return calc_parental_leave(inp, calc_ordinary_wage(inp))

    def test_2024_six_plus_six_caps_and_full_monthly_payment(self):
        """2024 판본 시행령 제95조의3①1호 상한 200~450만, 특례월은 사후지급 없이 매월 전액."""
        r = self.calc(parental_leave_start="2024-03-01", parental_leave_months=6, childcare_reason="child",
                      childcare_child_birth_date="2024-02-01", parental_scheme="six_plus_six", parental_same_child=True,
                      parental_other_parent_start="2024-01-01", parental_other_parent_months=6,
                      parental_other_parent_reason="pregnant_self")
        self.assertFalse(r.held_reason, r.held_reason)
        self.assertEqual([x["payment"] for x in r.monthly_schedule],
                         [2_000_000, 2_500_000, 3_000_000, 3_500_000, 4_000_000, 4_500_000])
        self.assertEqual(r.total_deferred, 0)

    def test_2024_single_parent_cap_and_full_monthly_payment(self):
        """2024 판본 한부모 첫 3개월 상한 250만·전액 지급, 4개월째는 일반형 80%·150만·사후지급 25%."""
        r = self.calc(parental_leave_start="2024-03-01", parental_leave_months=4, parental_scheme="single_parent",
                      parental_single_parent_eligible=True)
        self.assertFalse(r.held_reason, r.held_reason)
        self.assertEqual([x["payment"] for x in r.monthly_schedule], [2_500_000] * 3 + [1_125_000])
        self.assertEqual(r.total_deferred, 375_000)


class AutoSixPlusSixBoundaryTests(unittest.TestCase):
    """P7: 자동 6+6의 경계 — 나이로 불충족이 확정되면 일반형, 같은 자녀 미입력이면 6+6 가능성 안내."""

    OTHER = dict(parental_other_parent_start="2026-01-01", parental_other_parent_months=6)

    def calc(self, **kw):
        from wage_calculator.models import WorkSchedule
        inp = WageInput(wage_type=WageType.MONTHLY, monthly_wage=5_000_000, reference_date="2026-10-01",
                        schedule=WorkSchedule(daily_work_hours=8, weekly_work_days=5), parental_leave_start="2026-03-01",
                        parental_leave_months=6, childcare_child_birth_date="2025-12-01", childcare_insured_days=180)
        for k, v in kw.items(): setattr(inp, k, v)
        return calc_parental_leave(inp, calc_ordinary_wage(inp))

    def test_unknown_same_child_with_other_parent_facts_warns(self):
        r = self.calc(**self.OTHER)
        self.assertEqual((r.scheme, r.total_benefit), ("general", 13_500_000))
        self.assertTrue(any("6+6 특례" in w and "적용될 수 있어" in w for w in r.warnings), r.warnings)
        r = self.calc(parental_same_child=False, **self.OTHER)
        self.assertFalse(any("6+6" in w for w in r.warnings), r.warnings)

    def test_child_age_beyond_18_months_disproves_six_plus_six_without_birth_date(self):
        r = self.calc(parental_same_child=True, childcare_child_birth_date=None, childcare_child_age=5, **self.OTHER)
        self.assertEqual((r.held_reason, r.scheme, r.total_benefit), ("", "general", 13_500_000))
        self.assertTrue(any("개시일 현재 기준" in w and "6+6 특례" in w for w in r.warnings), r.warnings)
        r = self.calc(parental_same_child=True, childcare_child_birth_date=None, childcare_child_grade=2,
                      **self.OTHER)
        self.assertEqual((r.held_reason, r.scheme), ("", "general"))
        r = self.calc(parental_same_child=True, childcare_child_birth_date=None, childcare_child_age=1, **self.OTHER)
        self.assertIn("자녀 생년월일", r.held_reason)          # 만 1세는 12~23개월 — 갈리지 않으니 묻는다


if __name__ == '__main__':
    unittest.main()
