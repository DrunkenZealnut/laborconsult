"""C4b: preserve pay periods and actual average-wage facts."""
import unittest
from dataclasses import replace
from wage_calculator.models import WageInput, FixedAllowance
from wage_calculator.calculators.ordinary_wage import calc_ordinary_wage
from wage_calculator.calculators.average_wage import calc_average_wage
from wage_calculator.facade import WageCalculator


def average(**changes):
    inp = WageInput(monthly_wage=3_000_000, end_date='2026-10-01')
    for key, value in changes.items():
        setattr(inp, key, value)
    return calc_average_wage(inp, calc_ordinary_wage(inp))


class PayInputUpdateTests(unittest.TestCase):
    def test_unknown_cycle_alternative_preserves_independent_interest(self):
        from app.core.pipeline import _run_calculator
        text=_run_calculator(dict(needs_calculation=True,calculation_types_kr=['평균임금','임금체불 지연이자'],
            wage_type='월급',wage_amount=3_000_000,weekly_work_days=5,daily_work_hours=8,
            weekly_overtime_hours=5,fixed_allowances=[dict(name='상여',amount=1_200_000,payment_cycle='미확인')],
            arrear_amount=3_000_000,arrear_due_date='2026-01-01',arrear_calc_date='2026-01-31'))
        self.assertIsNotNone(text)
        self.assertIn('49,315',text)
        self.assertIn('지급 주기',text)

    def test_db_pension_resolves_average_dependency_and_held_severance(self):
        from wage_calculator.calculators.severance import calc_severance
        from wage_calculator.calculators.retirement_pension import calc_retirement_pension
        inp=WageInput(monthly_wage=3_000_000,start_date='2020-01-01',end_date='2026-10-01',
                      last_3m_days=0,pension_type='DB')
        for targets in [['retirement_pension'],['average_wage','retirement_pension']]:
            self.assertNotIn('retirement_pension',WageCalculator().calculate(inp,targets).calculation_executed)
        ow=calc_ordinary_wage(inp)
        self.assertTrue(calc_retirement_pension(inp,ow,calc_severance(inp,ow)).held_reason)

    def test_family_only_composition_does_not_restore_monthly_receipt(self):
        from app.core.pipeline import _run_calculator
        text=_run_calculator(dict(needs_calculation=True,calculation_types_kr=['난임치료휴가'],
            wage_type='월급',wage_amount=3_000_000,weekly_work_days=5,daily_work_hours=8,
            family_leave_days=2,family_leave_used_days=0,family_leave_eligible=True,
            family_leave_start_date='2026-10-01',family_leave_end_date='2026-10-02',
            family_leave_insured_days=180,is_priority_support_company=True),
            '월급 300만원에 기본급 250만원과 고정연장수당 50만원이 포함됩니다. 주 5일 하루 8시간 근무. 난임치료휴가 2일 급여 계산')
        self.assertIn('191,781',text)
        self.assertNotIn('월 총 예상 수령액',text)

    def test_explicit_maternity_does_not_ignore_usage_or_insurance(self):
        from wage_calculator.calculators.maternity_leave import calc_maternity_leave
        base=dict(monthly_wage=3_000_000,maternity_leave_type='maternity',family_leave_days=30,
            family_leave_used_days=0,family_leave_start_date='2026-10-01',family_leave_end_date='2026-10-30',
            family_leave_insured_days=100,family_leave_eligible=True,is_priority_support_company=True)
        inp=WageInput(**base)
        self.assertTrue(calc_maternity_leave(inp,calc_ordinary_wage(inp)).held_reason)
        inp=replace(inp,family_leave_days=90,family_leave_end_date='2026-12-29',family_leave_insured_days=180,
                    is_priority_support_company=None)
        self.assertTrue(calc_maternity_leave(inp,calc_ordinary_wage(inp)).held_reason)

    def test_full_maternity_employer_wage_is_not_capped_at_insurance(self):
        from wage_calculator.calculators.maternity_leave import calc_maternity_leave
        inp=WageInput(monthly_wage=3_000_000,maternity_leave_type='maternity',reference_year=2026,
            reference_date='2026-01-01',family_leave_days=90,family_leave_used_days=0,
            family_leave_start_date='2026-01-01',family_leave_end_date='2026-03-31',
            family_leave_insured_days=180,family_leave_eligible=True,is_priority_support_company=False)
        r=calc_maternity_leave(inp,calc_ordinary_wage(inp))
        self.assertFalse(r.held_reason)
        self.assertEqual((r.total_insurance_benefit,r.total_employer_benefit),(2_200_000,6_000_000))
        r=calc_maternity_leave(replace(inp,is_priority_support_company=True),calc_ordinary_wage(inp))
        self.assertEqual((r.total_insurance_benefit,r.total_employer_benefit),(6_600_000,1_600_000))

    def test_total_inclusive_bonus_survives_analyzer_and_pipeline(self):
        from app.core.analyzer import _build_analysis_result
        from app.core.pipeline import _analysis_to_extract_params,_run_calculator
        raw=dict(requires_calculation=True,calculation_types=['average_wage'],wage_type='월급',wage_amount=3_000_000,
            monthly_total_pay=3_100_000,weekly_work_days=5,daily_work_hours=8,annual_bonus_total=1_200_000,
            monthly_total_bonus_included=100_000,fixed_allowances=[dict(name='정기상여',amount=1_200_000,
            annual=True,source_id='b1')],annual_bonus_allowance_ids=['b1'])
        params=_analysis_to_extract_params(_build_analysis_result(raw,'기본급 300만원, 정기상여 포함 월 환산 총액 310만원'))
        self.assertEqual(params.get('monthly_total_pay'),3_100_000)
        text=_run_calculator(params,'평균임금 추정')
        self.assertIn('9,300,000원',text)
        self.assertNotIn('9,600,000원',text)

    def test_calculation_evidence_identifies_annual_allowance_and_dated_family_rule(self):
        from wage_calculator.result import format_result
        inp=WageInput(monthly_wage=3_000_000,fixed_allowances=[dict(name='정기상여',amount=1_200_000,annual=True)])
        text=format_result(WageCalculator().calculate(inp,['ordinary_wage']))
        self.assertIn('정기상여: 연간 총액 1,200,000원',text)
        inp=WageInput(monthly_wage=3_000_000,maternity_leave_type='infertility',family_leave_days=3,
            family_leave_used_days=1,family_leave_start_date='2026-11-27',family_leave_end_date='2026-12-01',
            family_leave_eligible=True,family_leave_insured_days=180)
        text=format_result(WageCalculator().calculate(inp,['maternity_leave']))
        self.assertIn('2026-11-27 시행',text)
        self.assertIn('최초 4일 유급',text)

    def test_family_leave_only_returns_requested_type(self):
        from app.core.pipeline import _run_calculator
        base=dict(needs_calculation=True,wage_type='시급',wage_amount=15_000,
                  weekly_work_days=5,daily_work_hours=8,reference_year=2026,
                  family_leave_used_days=0,family_leave_days=2,is_priority_support_company=True,
                  family_leave_insured_days=180,family_leave_eligible=True,
                  family_leave_start_date='2026-10-01',family_leave_end_date='2026-10-02')
        for label, kind in [('난임치료휴가','infertility'),('배우자 유산·사산휴가','spouse_miscarriage'),
                            ('배우자 출산휴가','spouse_birth')]:
            with self.subTest(label=label):
                text=_run_calculator(dict(base,calculation_types_kr=[label],maternity_leave_type=kind),label+' 급여 계산')
                self.assertIn('240,000원',text)
                self.assertIn(label,text)
                self.assertNotIn('출산전후휴가 월 급여',text)
                self.assertNotIn('90일',text)
                self.assertNotIn('월 총 예상 수령액',text)

    def test_family_paid_days_and_insurance_conditions(self):
        from wage_calculator.calculators.maternity_leave import calc_maternity_leave
        inp=WageInput(hourly_wage=15_000)
        from wage_calculator.models import WageType
        inp.wage_type=WageType.HOURLY
        fields=dict(maternity_leave_type='infertility',family_leave_days=3,family_leave_used_days=1,
                    family_leave_start_date='2026-10-01',family_leave_end_date='2026-10-05',
                    family_leave_eligible=True,family_leave_insured_days=180)
        for k,v in fields.items():setattr(inp,k,v)
        r=calc_maternity_leave(inp,calc_ordinary_wage(inp))
        self.assertEqual((getattr(r,'paid_days',None),getattr(r,'employer_pay',None)),(1,120_000))
        self.assertEqual(r.insurance_benefit,84_210)
        inp.family_leave_start_date='2026-11-27';inp.family_leave_end_date='2026-12-01'
        r=calc_maternity_leave(inp,calc_ordinary_wage(inp))
        self.assertEqual((r.paid_days,r.employer_pay,r.insurance_benefit),(3,360_000,252_630))
        inp.family_leave_insured_days=None
        r=calc_maternity_leave(inp,calc_ordinary_wage(inp))
        self.assertEqual(r.employer_pay,360_000)
        self.assertIsNone(r.insurance_benefit)

    def test_family_leave_boundaries_and_missing_facts_hold(self):
        from wage_calculator.calculators.maternity_leave import calc_maternity_leave
        for fields in [dict(family_leave_days=None),dict(family_leave_used_days=None),
                       dict(family_leave_start_date='2026-09-17'),dict(family_leave_days=6),
                       dict(family_leave_eligible=None),dict(family_leave_days=True)]:
            inp=WageInput(monthly_wage=3_000_000)
            for k,v in dict(maternity_leave_type='spouse_miscarriage',family_leave_days=3,
                            family_leave_used_days=0,family_leave_eligible=True,
                            family_leave_start_date='2026-09-18',family_leave_end_date='2026-09-23').items():
                setattr(inp,k,v)
            for k,v in fields.items():setattr(inp,k,v)
            with self.subTest(fields=fields):
                self.assertTrue(calc_maternity_leave(inp,calc_ordinary_wage(inp)).held_reason)

    def test_family_labels_preserve_compound_and_own_miscarriage_is_held(self):
        from wage_calculator.facade.registry import split_calc_labels,resolve_calc_type_strict
        self.assertEqual(split_calc_labels('배우자 유산·사산휴가/4대보험'),['배우자 유산·사산휴가','4대보험'])
        self.assertEqual(resolve_calc_type_strict('난임치료휴가'),['maternity_leave'])
        self.assertEqual(resolve_calc_type_strict('유산·사산휴가'),[])

    def test_regular_maternity_request_does_not_publish_other_leaves(self):
        from app.core.pipeline import _run_calculator
        text=_run_calculator(dict(needs_calculation=True,calculation_types_kr=['출산휴가'],
            wage_type='월급',wage_amount=3_000_000,weekly_work_days=5,daily_work_hours=8,
            reference_year=2026,maternity_leave_type='maternity',family_leave_days=90,family_leave_used_days=0,
            family_leave_start_date='2026-01-01',family_leave_end_date='2026-03-31',
            family_leave_insured_days=180,family_leave_eligible=True,is_priority_support_company=True),'출산전후휴가 급여')
        self.assertIn('출산전후휴가 월 급여',text)
        self.assertNotIn('배우자 출산휴가',text)
        self.assertNotIn('난임치료휴가',text)

    def test_unknown_cycle_does_not_drop_independent_interest(self):
        inp=WageInput(monthly_wage=3_000_000,fixed_allowances=[dict(name='상여',amount=1_200_000,payment_cycle='미확인')],
                      arrear_amount=3_000_000,arrear_due_date='2026-01-01',arrear_calc_date='2026-01-31')
        r=WageCalculator().calculate(inp,['ordinary_wage','wage_arrears'])
        self.assertEqual(r.calculation_executed,['wage_arrears'])
        self.assertIn('49,315원',r.summary.values())

    def test_compound_family_request_does_not_select_just_one(self):
        from app.core.pipeline import _run_calculator
        text=_run_calculator(dict(needs_calculation=True,calculation_types_kr=['난임치료휴가','배우자 출산휴가'],
            wage_type='월급',wage_amount=3_000_000,weekly_work_days=5,daily_work_hours=8,
            maternity_leave_type='infertility',family_leave_days=2,family_leave_used_days=0,
            family_leave_eligible=True,family_leave_start_date='2026-10-01',family_leave_end_date='2026-10-02'),
            '난임치료휴가와 배우자 출산휴가 급여 각각 계산')
        self.assertIn('계산 보류',text)
        self.assertNotIn('사업주 유급액:',text)

    def test_annual_allowance_cycle_survives_pipeline(self):
        from app.core.analyzer import _build_analysis_result
        from app.core.pipeline import _analysis_to_extract_params, _run_calculator
        for cycle, amount in [('연', 1_200_000), ('분기', 300_000), ('반기', 600_000)]:
            with self.subTest(cycle=cycle):
                query='월 기본급 300만원, 매주 5일 하루 8시간. 정기상여의 통상임금 월 환산액 계산'
                raw=dict(requires_calculation=True, calculation_types=['ordinary_wage'],
                         wage_type='월급', wage_amount=3_000_000, weekly_work_days=5, daily_work_hours=8,
                         fixed_allowances=[dict(name='정기상여', amount=amount, payment_cycle=cycle,
                                                source_id='bonus1', condition='없음')])
                text=_run_calculator(_analysis_to_extract_params(_build_analysis_result(raw,query)),query)
                self.assertIn('3,100,000',text)
                self.assertIn('통상임금 포함 수당 100,000원',text)

    def test_annual_flag_is_total_even_when_paid_quarterly(self):
        inp=WageInput(monthly_wage=3_000_000, fixed_allowances=[dict(
            name='상여', amount=1_200_000, annual=True, payment_cycle='분기')])
        self.assertEqual(calc_ordinary_wage(inp).monthly_ordinary_wage,3_100_000)

    def test_unknown_cycle_never_becomes_monthly_money(self):
        for cycle in ['미확인','',None,'일회성']:
            with self.subTest(cycle=cycle):
                inp=WageInput(monthly_wage=3_000_000, fixed_allowances=[dict(
                    name='상여',amount=1_200_000,payment_cycle=cycle)])
                r=WageCalculator().calculate(inp,['ordinary_wage','insurance'])
                self.assertFalse(r.calculation_executed)
                self.assertTrue(r.calculation_skipped)
                self.assertEqual(r.calculation_status,'not_run')
                self.assertNotIn('월 총 예상 수령액',r.summary)

    def test_nonmonthly_equivalent_is_not_labeled_monthly_receipt(self):
        from wage_calculator.result import format_result
        r=WageCalculator().calculate(WageInput(monthly_wage=3_000_000,
            fixed_allowances=[dict(name='정기상여',amount=1_200_000,annual=True)]),['ordinary_wage'])
        text=format_result(r)
        self.assertIn('월 환산 임금',text)
        self.assertNotIn('월 총 예상 수령액',text)

    def test_analyzer_missing_cycle_is_unknown(self):
        from app.core.analyzer import _build_analysis_result
        r=_build_analysis_result(dict(fixed_allowances=[dict(name='수당',amount=120_000)]),'수당 12만원')
        self.assertEqual(r.extracted_info['fixed_allowances'][0].get('payment_cycle'),'미확인')

    def test_average_wage_explicit_inputs_survive_pipeline(self):
        from app.core.analyzer import _build_analysis_result
        from app.core.pipeline import _analysis_to_extract_params, _run_calculator
        raw=dict(requires_calculation=True,calculation_types=['average_wage'],
                 wage_type='월급',wage_amount=3_000_000,weekly_work_days=5,daily_work_hours=8,
                 end_date='2026-10-01',last_3m_days=92,last_3m_wages=[2_000_000,4_000_000,4_000_000],
                 excluded_periods=[dict(start='2026-07-01',end='2026-07-10',reason='사용자귀책휴업',paid=1_000_000)])
        params=_analysis_to_extract_params(_build_analysis_result(raw,'2026년 평균임금'))
        for key in ('last_3m_days','last_3m_wages','excluded_periods'):
            self.assertEqual(params.get(key),raw[key])
        text=_run_calculator(params,'평균임금 계산')
        self.assertIn('82일',text)
        self.assertIn('9,000,000원',text)
        self.assertNotIn('× 3 추정',text)

    def test_actual_bonus_included_is_replaced_by_annual_share(self):
        r=average(last_3m_wages=[3_000_000,3_000_000,4_200_000],annual_bonus_total=1_200_000,
                  last_3m_bonus_included=1_200_000)
        self.assertFalse(r.held_reason)
        self.assertEqual((r.wage_total,r.bonus_addition,r.grand_total),(9_000_000,300_000,9_300_000))

    def test_same_bonus_source_deduplicates_estimate(self):
        r=average(fixed_allowances=[dict(name='정기상여',amount=1_200_000,annual=True,source_id='b1')],
                  annual_bonus_total=1_200_000,annual_bonus_allowance_ids=['b1'])
        self.assertFalse(r.held_reason)
        self.assertEqual((r.wage_total,r.grand_total),(9_000_000,9_300_000))

    def test_equal_amount_distinct_bonus_is_not_deduplicated(self):
        r=average(fixed_allowances=[dict(name='별도상여',amount=1_200_000,annual=True,source_id='other')],
                  annual_bonus_total=1_200_000,annual_bonus_allowance_ids=[])
        self.assertFalse(r.held_reason)
        self.assertEqual(r.grand_total,9_600_000)

    def test_total_pay_bonus_inclusion_is_explicit(self):
        for included, expected in [(100_000,9_300_000),(0,9_600_000)]:
            r=average(monthly_total_pay=3_100_000,annual_bonus_total=1_200_000,
                      monthly_total_bonus_included=included)
            self.assertFalse(r.held_reason)
            self.assertEqual(r.grand_total,expected)
        self.assertTrue(average(monthly_total_pay=3_100_000,annual_bonus_total=1_200_000).held_reason)

    def test_unknown_bonus_overlap_holds_average_only(self):
        inp=WageInput(monthly_wage=3_000_000,annual_bonus_total=1_200_000,
                      last_3m_wages=[3_000_000]*3)
        r=WageCalculator().calculate(inp,['average_wage','insurance'])
        self.assertNotIn('average_wage',r.calculation_executed)
        self.assertIn('insurance',r.calculation_executed)
        self.assertTrue(any('상여' in item['reason'] for item in r.calculation_skipped))

    def test_invalid_actual_inputs_hold_instead_of_estimate(self):
        for fields in [dict(last_3m_wages=[]),dict(last_3m_wages=[-1]),dict(last_3m_wages=[float('nan')]),
                       dict(last_3m_wages=[True]),dict(last_3m_wages=[{'typo':3_000_000}]),
                       dict(last_3m_days=0),dict(last_3m_days=True),dict(last_3m_days=93),
                       dict(annual_bonus_total=-1),dict(annual_bonus_total=float('inf'))]:
            with self.subTest(fields=fields):
                self.assertTrue(average(**fields).held_reason)

    def test_exclusion_requires_legal_reason_and_paid_actual_amount(self):
        p=dict(start='2026-07-01',end='2026-07-10',reason='사용자귀책휴업',paid=0)
        for bad in [dict(p,reason='개인결근'),dict(p,start='bad'),dict(p,end='2026-06-30'),
                    {k:v for k,v in p.items() if k!='paid'},dict(p,paid=-1)]:
            with self.subTest(period=bad):
                self.assertTrue(average(last_3m_wages=[3_000_000]*3,excluded_periods=[bad]).held_reason)

    def test_identical_exclusion_once_and_ambiguous_overlap_held(self):
        p=dict(start='2026-07-01',end='2026-07-10',reason='사용자귀책휴업',paid=1_000_000)
        r=average(last_3m_wages=[3_000_000]*3,excluded_periods=[p,p.copy()])
        self.assertEqual((r.period_days,r.wage_total),(82,8_000_000))
        self.assertTrue(average(last_3m_wages=[3_000_000]*3,
             excluded_periods=[p,dict(p,start='2026-07-05',end='2026-07-15')]).held_reason)

    def test_all_excluded_and_bonus_with_exclusion_hold(self):
        p=dict(start='2026-07-01',end='2026-09-30',reason='육아휴직',paid=0)
        self.assertTrue(average(excluded_periods=[p]).held_reason)
        self.assertTrue(average(annual_bonus_total=1_200_000,
                               excluded_periods=[dict(p,end='2026-07-10')]).held_reason)

    def test_average_hold_propagates_to_consumers(self):
        inp=WageInput(monthly_wage=3_000_000,start_date='2020-01-01',end_date='2026-10-01',
                      last_3m_days=0,shutdown_days=10)
        for target in ['severance','shutdown_allowance','industrial_accident','unemployment']:
            with self.subTest(target=target):
                r=WageCalculator().calculate(inp,[target])
                self.assertNotIn(target,r.calculation_executed)
                self.assertTrue(r.calculation_skipped)


if __name__=='__main__':
    unittest.main()
