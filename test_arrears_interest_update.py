"""C2: dated claim interest, statutory transition and principal allocations."""
import unittest
import json
from pathlib import Path
import shutil
import subprocess
from wage_calculator.calculators.wage_arrears import calc_wage_arrears


def interest(**changes):
    args=dict(arrear_amount=3_000_000,arrear_due_date='2026-01-01',
              arrear_calc_date='2026-01-31')
    args.update(changes)
    return calc_wage_arrears(**args)


class ArrearsInterestUpdateTests(unittest.TestCase):
    def test_paid_interest_is_separate_from_accrual_and_missing_allocation_holds_total(self):
        payment=dict(date='2026-01-15',principal_amount=1_000_000,allocation_confirmed=True)
        unknown=interest(payments=[payment])
        self.assertEqual(unknown.interest_amount,40548)
        self.assertIsNone(unknown.total_claim)
        paid=interest(payments=[dict(payment,interest_amount=23014)])
        self.assertEqual((paid.interest_amount,paid.interest_paid,paid.remaining_interest,paid.total_claim),
                         (40548,23014,17534,2017534))
        overpaid=interest(arrear_amount=0,arrear_due_date='',claims=[
            dict(id='a',amount=3_000_000,due_date='2026-01-31',payments=[dict(
                date='2026-01-31',principal_amount=0,interest_amount=1000,allocation_confirmed=True)]),
            dict(id='b',amount=3_000_000,due_date='2026-01-01')])
        self.assertTrue(overpaid.held_reason)

    def test_interest_payment_unknown_preserves_card_and_independent_insurance(self):
        from app.core.pipeline import _run_calculator
        text=_run_calculator(dict(needs_calculation=True,calculation_types_kr=['임금체불','4대보험'],
             wage_type='월급',wage_amount=3_000_000,weekly_work_days=5,daily_work_hours=8,
             arrear_amount=3_000_000,arrear_due_date='2026-01-01',arrear_calc_date='2026-01-31',
             arrear_payments=[dict(date='2026-01-15',principal_amount=1_000_000,allocation_confirmed=True)]),
             '지연이자와 4대보험 계산')
        self.assertIn('40,548',text)
        self.assertIn('청구 합계: 보류',text)
        self.assertNotIn('2,040,548',text)
        self.assertIn('세후 실수령액',text)

    def test_freelance_fee_is_not_statutory_wage_interest(self):
        from app.core.pipeline import _run_calculator
        from wage_calculator.facade import WageCalculator
        from wage_calculator.models import WageInput
        text=_run_calculator(dict(needs_calculation=True,calculation_types_kr=['임금체불'],
             is_platform_worker=True,arrear_amount=3_000_000,arrear_due_date='2026-01-01',
             arrear_calc_date='2026-01-31',debtor_is_merchant=True),'근로자가 아닌 프리랜서 용역비 지연이자')
        self.assertNotIn('49,315',text)
        self.assertIn('근로자',text)
        direct=WageCalculator().calculate(WageInput(is_platform_worker=True,arrear_amount=3_000_000,
             arrear_due_date='2026-01-01',arrear_calc_date='2026-01-31'),['wage_arrears'])
        self.assertNotIn('wage_arrears',direct.calculation_executed)

    def test_auto_detection_accepts_claim_list_and_retirement_dates(self):
        from wage_calculator.facade import WageCalculator
        from wage_calculator.models import WageInput
        for inp in [WageInput(arrear_claims=[dict(id='a',amount=3_000_000,due_date='2026-01-01')],
                              arrear_calc_date='2026-01-31'),
                    WageInput(arrear_amount=3_000_000,arrear_claim_kind='retirement_lump_sum',
                              arrear_retirement_effective_date='2024-06-01',arrear_deadline_holidays=[],
                              arrear_calc_date='2024-06-15')]:
            with self.subTest(inp=inp):
                self.assertIn('wage_arrears',WageCalculator().calculate(inp).calculation_executed)

    def test_interest_only_composed_wage_does_not_restore_monthly_total(self):
        from app.core.pipeline import _run_calculator
        params=dict(needs_calculation=True,calculation_types_kr=['임금체불'],wage_type='월급',
                    wage_amount=3_000_000,arrear_amount=3_000_000,arrear_due_date='2026-01-01',
                    arrear_calc_date='2026-01-31',weekly_work_days=5,daily_work_hours=8)
        query='월급 총액 300만원에 연장수당이 포함되어 있고 기본급은 250만원입니다. 확정 체불 원금의 지연이자만 계산해주세요.'
        text=_run_calculator(params,query)
        self.assertIn('49,315',text)
        self.assertNotIn('월 총 예상 수령액',text)

    @unittest.skipIf(shutil.which('node') is None,'node 없음')
    def test_public_calculator_matches_dated_examples(self):
        page=Path(__file__).parent/'public/calculator_flow/wage_arrears_interest_calc.html'
        self.assertEqual(page.read_bytes(),(Path(__file__).parent/'wage_calculator/calculator_flow'/page.name).read_bytes())
        script=r'''
const fs=require('node:fs'),vm=require('node:vm');
const code=[...fs.readFileSync(process.argv[1],'utf8').matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m=>m[1]).find(s=>s.includes('function calculateInterest'));
const context=vm.createContext({});vm.runInContext(code,context);
const base={amount:3000000,kind:'regular_wage',due:'2026-01-01',end:'2026-01-31',retirement:'',merchant:null,holidays:[]};
const cases=[{}, {due:'2025-10-21',end:'2025-10-31'}, {due:'2025-10-22',end:'2025-10-31'},
 {retirement:'2026-01-15'}, {kind:'retirement_lump_sum',due:'2024-06-14',retirement:'2024-06-01',end:'2024-06-15'},
 {due:'2024-02-29',end:'2024-03-01',merchant:false}, {end:'2026-01-01'}];
console.log(JSON.stringify(cases.map(c=>context.calculateInterest({...base,...c}).scenarios.map(s=>s.interest))));
'''
        run=subprocess.run(['node','-e',script,str(page)],capture_output=True,text=True,timeout=30,check=True)
        self.assertEqual(json.loads(run.stdout),[[49315],[4110,4932],[14795],[49315],[1644],[411],[0]])

    def test_malformed_optional_inputs_do_not_become_missing(self):
        for fields in [dict(arrear_due_date='2026-W01-1'), dict(arrear_calc_date='2026-W01-1'),
                       dict(payments=False), dict(exclusions={}),
                       dict(retirement_effective_date=0), dict(last_employed_date=False),
                       dict(claim_kind='retirement_lump_sum', retirement_effective_date='2026-01-01',
                            arrear_due_date=0)]:
            with self.subTest(fields=fields):
                self.assertTrue(interest(**fields).held_reason)

    def test_retirement_deadline_weekend_and_declared_holiday(self):
        r=interest(arrear_due_date='', claim_kind='retirement_lump_sum',
                   retirement_effective_date='2026-01-04', deadline_holidays=['2026-01-19'],
                   arrear_calc_date='2026-01-21')
        self.assertEqual(r.due_date,'2026-01-20')
        self.assertEqual((r.delay_days,r.interest_amount),(1,1644))

    def test_arrears_fields_survive_analysis_and_wageless_pipeline(self):
        from app.core.analyzer import _build_analysis_result
        from app.core.pipeline import _analysis_to_extract_params,_run_calculator
        raw=dict(requires_calculation=True,calculation_types=['wage_arrears'],
                 arrear_amount=3_000_000,arrear_due_date='2026-01-01',arrear_calc_date='2026-01-31',
                 arrear_claim_kind='regular_wage',debtor_is_merchant=True,
                 arrear_retirement_effective_date='2026-01-15',arrear_deadline_holidays=[])
        a=_build_analysis_result(raw,'2026년 1월 1일 급여일, 1월 31일까지 이자')
        params=_analysis_to_extract_params(a)
        self.assertEqual(params['arrear_calc_date'],'2026-01-31')
        text=_run_calculator(params,'확정 체불 원금의 지연이자')
        self.assertIn('49,315',text)
        self.assertNotIn('월 총 예상 수령액',text)

    def test_conditional_interest_is_not_formatted_as_a_single_amount(self):
        from app.core.pipeline import _run_calculator
        text=_run_calculator(dict(needs_calculation=True,calculation_types_kr=['임금체불'],
             arrear_amount=3_000_000,arrear_due_date='2025-10-21',arrear_calc_date='2025-10-31'),
             '상인 여부 미확인, 지연이자만 계산')
        self.assertIn('4,110',text);self.assertIn('4,932',text)
        self.assertIn('조건',text)

    def test_claim_list_executes_without_legacy_amount(self):
        from app.core.pipeline import _run_calculator
        text=_run_calculator(dict(needs_calculation=True,calculation_types_kr=['임금체불'],
             arrear_calc_date='2026-01-31',arrear_claims=[
                 dict(id='a',amount=3_000_000,due_date='2026-01-01')]),'확정 채권별 지연이자')
        self.assertIn('49,315',text)

    def test_arrears_2026_30_days(self):
        r=interest()
        self.assertEqual((r.delay_days,r.interest_amount,r.total_claim),(30,49_315,3_049_315))
        self.assertEqual(r.interest_rate,.20)

    def test_regular_payday_transition_is_cause_based(self):
        new=interest(arrear_due_date='2025-10-22',arrear_calc_date='2025-10-31')
        old=interest(arrear_due_date='2025-10-21',arrear_calc_date='2025-10-31',debtor_is_merchant=True)
        self.assertEqual((new.delay_days,new.interest_amount),(9,14_795))
        self.assertEqual((old.delay_days,old.interest_amount),(10,4_932))
        self.assertEqual({row['rate'] for row in old.interest_schedule},{.06})

    def test_arrears_retirement_does_not_reset_start(self):
        r=interest(retirement_effective_date='2026-01-15',deadline_holidays=[])
        self.assertEqual(r.interest_amount,49_315)
        self.assertEqual(sum(x['days'] for x in r.interest_schedule),30)

    def test_retirement_lump_sum_fourteen_day_boundary(self):
        fields=dict(arrear_due_date='2024-06-14',claim_kind='retirement_lump_sum',
                    retirement_effective_date='2024-06-01',deadline_holidays=[])
        self.assertEqual(interest(**fields,arrear_calc_date='2024-06-14').interest_amount,0)
        r=interest(**fields,arrear_calc_date='2024-06-15')
        self.assertEqual(r.interest_amount,1_644)
        self.assertEqual(r.interest_schedule[0]['start_date'],'2024-06-15')

    def test_retirement_boolean_never_replaces_dates(self):
        self.assertTrue(interest(is_post_retirement_arrear=True).held_reason)
        self.assertTrue(interest(claim_kind='retirement_lump_sum').held_reason)
        self.assertTrue(interest(retirement_effective_date='2026-01-15',
                                 last_employed_date='2026-01-15').held_reason)

    def test_unknown_merchant_produces_two_conditional_amounts(self):
        r=interest(arrear_due_date='2025-10-21',arrear_calc_date='2025-10-31')
        self.assertIsNone(r.interest_amount)
        self.assertEqual([x['interest_amount'] for x in r.conditional_scenarios],[4_110,4_932])
        self.assertFalse(r.held_reason)

    def test_partial_principal_payment_reduces_next_day_balance(self):
        r=interest(payments=[dict(date='2026-01-15',principal_amount=1_000_000,interest_amount=0,allocation_confirmed=True)])
        self.assertEqual((r.arrear_amount,r.interest_amount,r.total_claim),(2_000_000,40_548,2_040_548))
        self.assertEqual([(x['principal'],x['days']) for x in r.interest_schedule],[(3_000_000,14),(2_000_000,16)])
        self.assertTrue(interest(payments=[dict(date='2026-01-15',principal_amount=1_000_000)]).held_reason)
        self.assertTrue(interest(payments=[dict(date='2026-01-15',principal_amount=4_000_000,allocation_confirmed=True)]).held_reason)

    def test_multiple_claims_keep_their_due_dates(self):
        r=interest(arrear_amount=0,arrear_due_date='',claims=[
            dict(id='a',amount=3_000_000,due_date='2026-01-01',claim_kind='regular_wage'),
            dict(id='b',amount=2_000_000,due_date='2026-01-15',claim_kind='regular_wage')])
        self.assertEqual(r.interest_amount,66_849)
        self.assertEqual({x['claim_id'] for x in r.interest_schedule},{'a','b'})

    def test_exclusion_only_changes_its_own_dates(self):
        r=interest(debtor_is_merchant=True,exclusions=[
            dict(start_date='2026-01-11',end_date='2026-01-20',reason='reasonable_legal_dispute',eligible=True)])
        self.assertEqual(r.interest_amount,37_808)
        self.assertEqual([(x['rate'],x['days']) for x in r.interest_schedule],[(.2,9),(.06,10),(.2,11)])
        self.assertTrue(interest(exclusions=[dict(start_date='2026-01-11',end_date='2026-01-20',
                                                  reason='reasonable_legal_dispute')]).held_reason)

    def test_leap_day_and_invalid_dates(self):
        r=interest(arrear_due_date='2024-02-29',arrear_calc_date='2024-03-01',debtor_is_merchant=False)
        self.assertEqual(r.statute_of_limitations_date,'2027-02-28')
        self.assertEqual(r.interest_amount,411)
        for fields in [dict(arrear_due_date='2026-02-30'),dict(arrear_calc_date='bad'),
                       dict(arrear_amount=float('nan')),dict(arrear_amount=-1),dict(debtor_is_merchant='false')]:
            with self.subTest(fields=fields):self.assertTrue(interest(**fields).held_reason)

    def test_no_delay_and_full_payment_are_zero_interest_or_zero_balance(self):
        self.assertEqual(interest(arrear_calc_date='2026-01-01').interest_amount,0)
        r=interest(payments=[dict(date='2026-01-15',principal_amount=3_000_000,interest_amount=0,allocation_confirmed=True)])
        self.assertEqual((r.arrear_amount,r.interest_amount,r.total_claim),(0,23_014,23_014))


if __name__=='__main__':
    unittest.main()
