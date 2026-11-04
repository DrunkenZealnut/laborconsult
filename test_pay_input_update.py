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
    def test_default_nontaxable_amount_does_not_invent_a_meal_allowance(self):
        from wage_calculator.legal_hints import generate_legal_hints
        hints=generate_legal_hints(WageInput(monthly_wage=3_000_000))
        self.assertFalse(any('식대 20만원만 비과세 적용 중' in h.condition for h in hints))
        self.assertTrue(any('지급 사실' in h.hint for h in hints if h.category=='비과세소득'))

    def test_explicit_average_event_date_is_preserved_without_retirement(self):
        from app.core.analyzer import _build_analysis_result
        from app.core.pipeline import _analysis_to_extract_params, _run_calculator
        raw=dict(requires_calculation=True,calculation_types=['average_wage'],wage_type='월급',
            wage_amount=3_000_000,weekly_work_days=5,daily_work_hours=8,
            average_wage_date='2026-10-01',last_3m_days=92,last_3m_wages=[2_000_000,4_000_000,4_000_000],
            excluded_periods=[dict(start='2026-07-01',end='2026-07-10',paid=1_000_000,reason='사용자귀책휴업')])
        params=_analysis_to_extract_params(_build_analysis_result(raw,'평균임금 사유 발생일 2026년 10월 1일'))
        text=_run_calculator(params,'평균임금 계산')
        self.assertIn('산정기간: 82일',text)
        self.assertIn('9,000,000원',text)
        self.assertIn('115,068원',text)

    def test_annual_bonus_formula_names_the_same_item_in_the_sum(self):
        inp=WageInput(monthly_wage=3_000_000,fixed_allowances=[
            dict(name='정기상여',amount=1_200_000,annual=True)])
        formula=calc_ordinary_wage(inp).formula
        self.assertIn('+ 정기상여 월 환산 100,000원',formula)
        self.assertNotIn('+ 통상임금 포함 수당',formula)

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
        # 고시(제2026-67호)는 최초 2일분 상한만 정한다 — 기사용 1일이면 1일분만 확정, 3·4일째는 미확정(wage-update-followups P4)
        self.assertEqual((r.paid_days,r.employer_pay,r.insurance_benefit),(3,360_000,None))
        self.assertTrue(any('1일분 84,210원은 그 상한 이내로 확정' in w for w in r.warnings),r.warnings)
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
                self.assertIn('정기상여 월 환산 100,000원',text)

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

    def test_analyzer_missing_cycle_is_unknown_only_for_varying_items(self):
        """주기가 갈리는 상여·성과급 계열만 '미확인'(보류)이다. 식대·직책수당 같은 월정 수당은 주기 표현이 없어도(또는 LLM이
        '미확인'을 붙여도) 매월이다 — 수당 하나로 카드 전체가 보류되던 결함(Codex 리뷰 High 1)."""
        from app.core.analyzer import _build_analysis_result
        cycle=lambda a:_build_analysis_result(dict(fixed_allowances=[a]),'').extracted_info['fixed_allowances'][0].get('payment_cycle')
        for name in ('상여','정기상여','명절수당','추석수당','설날수당','생일수당','김장수당','성과급','인센티브','하계휴가비','설날 선물비','추석 귀성여비','연차수당','복지포인트'):
            with self.subTest(name=name):
                self.assertEqual(cycle(dict(name=name,amount=120_000)),'미확인')
                self.assertEqual(cycle(dict(name=name,amount=120_000,payment_cycle='미확인')),'미확인')
        for name in ('수당','식대','직책수당','교통비','가족수당','자격증 수당','통신비'):
            with self.subTest(name=name):
                self.assertEqual(cycle(dict(name=name,amount=120_000)),'매월')
                self.assertEqual(cycle(dict(name=name,amount=120_000,payment_cycle='미확인')),'매월')
        self.assertEqual(cycle(dict(name='식대',amount=600_000,payment_cycle='분기')),'분기')
        self.assertEqual(cycle(dict(name='상여',amount=6_000_000,annual=True)),'연')

    def test_monthly_allowance_without_cycle_does_not_hold_the_chat_card(self):
        """채팅 경로(분석기 → 변환기 → 카드): "월급 250만원 + 식대 20만원"이 최저임금 판정 없이 보류되지 않는다."""
        from app.core.analyzer import _build_analysis_result
        from app.core.pipeline import _analysis_to_extract_params,_run_calculator
        query='월급 250만원에 식대 20만원 받고 주5일 하루 8시간 일합니다. 최저임금 위반인가요?'
        raw=dict(requires_calculation=True,calculation_types=['minimum_wage'],wage_type='월급',wage_amount=2_500_000,
                 weekly_work_days=5,daily_work_hours=8,business_size='5인이상',reference_year=2026,   # 최저임금 연도 고정
                 fixed_allowances=[dict(name='식대',amount=200_000)])
        card=_run_calculator(_analysis_to_extract_params(_build_analysis_result(raw,query)),query) or ''
        self.assertIn('최저임금 충족: ✅ 충족',card)
        self.assertNotIn('계산 보류',card)
        bonus=dict(raw,fixed_allowances=[dict(name='상여금',amount=1_200_000)])
        held=_run_calculator(_analysis_to_extract_params(_build_analysis_result(bonus,query)),query) or ''
        self.assertIn('상여금: 지급 주기를 확인해주세요',held)

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


_CHAT_BASE = dict(requires_calculation=True, question_summary="q", is_labor_related=True, wage_type="월급",
                  weekly_work_days=5, daily_work_hours=8, reference_year=2026)


def _chat(query, **raw):
    """프로덕션 변환기: analyzer._build_analysis_result → _analysis_to_extract_params → _run_calculator."""
    from app.core.analyzer import _build_analysis_result
    from app.core import pipeline as P
    analysis = _build_analysis_result(dict(_CHAT_BASE, **raw), query)
    return P._run_calculator(P._analysis_to_extract_params(analysis), query) or "", analysis


class AnalyzerTotalAndBonusTests(unittest.TestCase):
    """분석기 총액의 근거 대조·상여 중복 조정·휴업수당 기산일(wage-update-followups G3·G4·G7)."""
    Q_OT = "월급 300만원, 주5일 하루 8시간에 매주 10시간 연장근로를 하고 연장수당은 따로 받습니다. 4대보험 공제액 알려주세요."

    def test_analyzer_total_equal_to_wage_does_not_replace_monthly_base(self):  # G3
        text, _ = _chat(self.Q_OT, calculation_types=["insurance"], wage_amount=3_000_000,
                        weekly_overtime_hours=10, monthly_total_pay=3_000_000)
        self.assertIn("세전 월 급여: 3,937,500원", text)
        self.assertIn("월 실수령액(세후):       3,387,472원", text)

    def test_analyzer_total_missing_or_net_in_question_is_dropped(self):  # G3
        text, _ = _chat("월급 270만원에 연장수당이 포함되어 있습니다. 2020년 1월 1일 입사, 2026년 10월 1일 퇴사. 퇴직금은?",
                        calculation_types=["severance"], wage_amount=2_700_000, start_date="2020-01-01",
                        end_date="2026-10-01", monthly_total_pay=2_900_000)
        self.assertIn("월 총 예상 수령액(세전): 2,700,000원", text)
        self.assertNotIn("2,900,000", text)
        text, _ = _chat("월급 300만원이고 세후로는 270만원 정도 받아요. 매주 10시간 연장근로를 하고 연장수당은 따로 받습니다. "
                        "4대보험 공제액 알려주세요.", calculation_types=["insurance"], wage_amount=3_000_000,
                        weekly_overtime_hours=10, monthly_total_pay=2_700_000)
        self.assertIn("세전 월 급여: 3,937,500원", text)

    def test_stated_gross_total_is_kept(self):  # G3 비회귀(과잉 제거 방지)
        text, _ = _chat("월급 300만원이고 연장수당 합치면 매달 350만원 정도 받아요. 4대보험 공제액 알려주세요.",
                        calculation_types=["insurance"], wage_amount=3_000_000, monthly_total_pay=3_500_000)
        self.assertIn("세전 월 급여: 3,500,000원", text)
        text, _ = _chat("기본급 250만원에 식대 20만원, 월 270만원 받습니다. 4대보험 공제액 알려주세요.",
                        calculation_types=["insurance"], wage_amount=2_500_000, monthly_total_pay=2_700_000)
        self.assertIn("세전 월 급여: 2,700,000원", text)
        text, _ = _chat("기본급 300만원, 정기상여 포함 월 환산 총액 310만원", calculation_types=["average_wage"],
                        wage_amount=3_000_000, monthly_total_pay=3_100_000, annual_bonus_total=1_200_000,
                        monthly_total_bonus_included=100_000,
                        fixed_allowances=[dict(name="정기상여", amount=1_200_000, annual=True, source_id="b1")])
        self.assertIn("3개월 임금총액: 9,300,000원", text)

    def test_follow_up_keeps_only_totals_grounded_in_an_earlier_turn(self):  # G3 후속 질문(Codex #137)
        """앞 턴에서 질문과 대조한 월 총액은 금액을 다시 적지 않은 후속 질문에서도 세전 기준으로 남고, 앞 턴에서 버린 총액(세후)은
        캐시에 남지 않아 후속 질문에서 되살아나지 않는다."""
        from unittest import mock
        from app.config import AppConfig
        from app.core import pipeline as P
        from app.core.analyzer import _build_analysis_result
        from app.models.session import Session

        def answer(messages, system, config):
            yield "답변"

        def cards(*turns):
            session = Session(id="g3-followup-offline")
            config = AppConfig(openai_client=object(), pinecone_index=None, claude_client=object(), supabase=None)
            config.law_api_key = None
            out = []
            for query, raw in turns:
                analysis = _build_analysis_result(dict(_CHAT_BASE, calculation_types=["insurance"], **raw), query)
                with mock.patch.object(P, "analyze_intent", return_value=analysis), \
                     mock.patch.object(P, "_answer_providers", lambda c: [("OpenAI", answer)]), \
                     mock.patch.object(P, "process_consultation", return_value=("", [])):
                    events = list(P.process_question(query, session, config))
                out.append(next((e["calc_result"] for e in events if e.get("type") == "meta"), ""))
            return out

        follow_up = ("부양가족이 2명이면 다시 계산해 주세요.", {})
        first, second = cards(("월급 300만원이고 연장수당 합치면 매달 세전 350만원 받아요. 4대보험 공제액 알려주세요.",
                               dict(wage_amount=3_000_000, monthly_total_pay=3_500_000)), follow_up)
        self.assertIn("세전 월 급여: 3,500,000원", first)
        self.assertIn("세전 월 급여: 3,500,000원", second)
        first, second = cards(("월급 300만원이고 세후로는 270만원 정도 받아요. 4대보험 공제액 알려주세요.",
                               dict(wage_amount=3_000_000, monthly_total_pay=2_700_000)), follow_up)
        self.assertIn("세전 월 급여: 3,000,000원", first)
        self.assertIn("세전 월 급여: 3,000,000원", second)

    def test_bonus_dedup_subtracts_only_the_bonus_not_premium_raised_by_it(self):  # G4
        from wage_calculator.calculators.pay_inputs import bonus_already_included
        from wage_calculator.models import BusinessSize, WageType, WorkSchedule
        fa = [{"name": "정기상여", "amount": 6_000_000, "annual": True, "condition": "재직조건", "source_id": "b1"}]
        inp = WageInput(wage_type=WageType.MONTHLY, monthly_wage=2_500_000, business_size=BusinessSize.OVER_5,
                        start_date="2020-01-01", end_date="2026-10-01",
                        schedule=WorkSchedule(daily_work_hours=8, weekly_work_days=5, weekly_overtime_hours=12),
                        fixed_allowances=fa, annual_bonus_total=6_000_000, annual_bonus_allowance_ids=["b1"])
        self.assertEqual(bonus_already_included(inp, calc_ordinary_wage(inp)), 1_500_000)
        text, _ = _chat("월급 250만원, 정기상여 연 600만원(재직조건), 주5일 하루8시간에 매주 12시간 연장근로하고 연장수당은 따로 "
                        "받습니다. 2020년 1월 1일 입사 2026년 10월 1일 퇴사. 퇴직금은?",
                        calculation_types=["severance"], wage_amount=2_500_000, weekly_overtime_hours=12,
                        start_date="2020-01-01", end_date="2026-10-01", annual_bonus_total=6_000_000,
                        fixed_allowances=fa, annual_bonus_allowance_ids=["b1"])
        self.assertIn("퇴직금: 27,252,271원", text)

    def test_shutdown_average_wage_is_dated_at_shutdown_start(self):  # G7
        from wage_calculator.models import BusinessSize, WageType, WorkSchedule
        from wage_calculator.result import format_result
        s = WageInput(wage_type=WageType.MONTHLY, monthly_wage=2_500_000, business_size=BusinessSize.OVER_5,
                      start_date="2020-01-01",
                      schedule=WorkSchedule(daily_work_hours=8, weekly_work_days=5, weekly_overtime_hours=12),
                      shutdown_start_date="2026-03-01", shutdown_days=10, average_wage_date="2026-10-01")
        with_date = format_result(WageCalculator().calculate(s, ["shutdown_allowance"]))
        without = format_result(WageCalculator().calculate(replace(s, average_wage_date=None), ["shutdown_allowance"]))
        self.assertIn("휴업수당: 802,083원", with_date)
        self.assertIn("휴업수당: 802,083원", without)
        self.assertIn("휴업 시작일(2026-03-01)을 산정 사유 발생일로", with_date)
        self.assertNotIn("휴업 시작일 미확인", with_date)
        no_start = format_result(WageCalculator().calculate(replace(s, shutdown_start_date=None, average_wage_date=None,
                                                                    end_date="2026-03-01"), ["shutdown_allowance"]))
        self.assertIn("휴업 시작일 미확인", no_start)


if __name__=='__main__':
    unittest.main()
