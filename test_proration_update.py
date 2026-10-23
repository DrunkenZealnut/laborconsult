"""C6: contract-based settlement month and item ledger."""
import unittest
from wage_calculator.models import WageInput
from wage_calculator.calculators.ordinary_wage import calc_ordinary_wage
from wage_calculator.calculators.prorated import calc_prorated


def prorate(**changes):
    inp=WageInput(monthly_wage=3_000_000,start_date='2024-01-01')
    fields=dict(settlement_month='2026-10',proration_method='calendar',
                last_employed_date='2026-10-16',proration_all_items_proportional=True)
    fields.update(changes)
    for k,v in fields.items():setattr(inp,k,v)
    return calc_prorated(inp,calc_ordinary_wage(inp))


class ProrationUpdateTests(unittest.TestCase):
    def test_facade_validates_original_negative_contract_but_keeps_independent_items(self):
        from wage_calculator.facade import WageCalculator
        inp=WageInput(monthly_wage=-3000000,settlement_month='2026-10',proration_method='calendar',
            proration_employed_at_month_start=True,last_employed_date='2026-10-16',
            proration_all_items_proportional=True)
        r=WageCalculator().calculate(inp,['prorated'])
        self.assertEqual(r.calculation_status,'not_run')
        inp.proration_all_items_proportional=False;inp.proration_items_complete=True
        inp.proration_items=[dict(id='base',name='기본급',amount=3100000,payment_cycle='매월',policy='prorate')]
        self.assertEqual(WageCalculator().calculate(inp,['prorated']).summary.get('일할계산 임금'),'1,600,000원')

    def test_whole_contract_cannot_bypass_unknown_allowance_with_empty_item_flag(self):
        from wage_calculator.facade import WageCalculator
        for items in (None,[]):
            inp=WageInput(monthly_wage=3000000,settlement_month='2026-10',proration_method='calendar',
                proration_employed_at_month_start=True,last_employed_date='2026-10-16',
                proration_all_items_proportional=True,proration_items_complete=True,proration_items=items,
                fixed_allowances=[dict(name='미확인 수당',amount=500000,payment_cycle='미확인')])
            self.assertEqual(WageCalculator().calculate(inp,['prorated']).calculation_status,'not_run')

    def test_partial_schedule_does_not_block_calendar_settlement(self):
        from app.core.pipeline import _run_calculator
        p=dict(needs_calculation=True,calculation_types_kr=['일할계산급여'],wage_type='월급',wage_amount=3000000,
            weekly_work_days=3,settlement_month='2026-10',proration_method='calendar',
            proration_employed_at_month_start=True,last_employed_date='2026-10-16',proration_all_items_proportional=True)
        text=_run_calculator(p,'10월 월급을 역일수로 일할계산')
        self.assertIn('1,548,387원',text)
        self.assertNotIn('계산 보류',text)

    def test_settlement_only_never_synthesizes_another_monthly_premium(self):
        from app.core.pipeline import _run_calculator
        p=dict(needs_calculation=True,calculation_types_kr=['일할계산급여'],wage_type='월급',wage_amount=2800000,
            weekly_work_days=5,daily_work_hours=8,weekly_overtime_hours=5,business_size='5인이상',
            settlement_month='2026-10',proration_method='calendar',proration_employed_at_month_start=True,
            last_employed_date='2026-10-16',proration_items_complete=True,
            proration_items=[dict(id='base',name='기본급',amount=2800000,payment_cycle='매월',policy='prorate'),
                dict(id='ot',name='실제 연장수당',actual_amount=150000,policy='actual')])
        for hours in (8,9):
            p['daily_work_hours']=hours
            text=_run_calculator(dict(p),'명시된 급여 항목만으로 10월 일할계산')
            self.assertIn('1,595,161원',text)
            self.assertNotIn('연장/야간/휴일수당(월)',text)
            self.assertNotIn('통상시급:',text)
        p['daily_work_hours']=8;p['calculation_types_kr']=['일할계산급여','연장수당']
        self.assertIn('연장/야간/휴일수당(월)',_run_calculator(p,'일할 임금과 연장수당 비교'))

    def test_fallback_extraction_can_express_same_settlement_contract(self):
        from app.core.pipeline import WAGE_CALC_TOOL,_run_calculator
        from app.templates.prompts import ANALYZE_TOOL
        from wage_calculator.calculators.prorated import PRORATION_INPUT_FIELDS
        props=WAGE_CALC_TOOL['input_schema']['properties']
        for name in PRORATION_INPUT_FIELDS:
            self.assertEqual(props.get(name),ANALYZE_TOOL['input_schema']['properties'][name],name)
        p=dict(needs_calculation=True,calculation_type='일할계산급여',wage_type='월급',wage_amount=3000000,
            settlement_month='2026-10',proration_method='calendar',proration_employed_at_month_start=True,
            last_employed_date='2026-10-16',proration_all_items_proportional=True)
        self.assertIn('1,548,387원',_run_calculator(p,'10월 월급 역일수 일할계산'))

    def test_identical_whole_contract_and_single_item_are_not_double_counted(self):
        item=dict(id='salary',name='월급 전액',amount=3000000,payment_cycle='매월',policy='prorate')
        for items in ([],[item]):
            self.assertEqual(prorate(proration_items=items,proration_items_complete=True).prorated_wage,1548387)
        for bad in (dict(item,amount=2900000),dict(item,policy='full'),dict(item,payment_cycle='연')):
            self.assertTrue(prorate(proration_items=[bad],proration_items_complete=True).held_reason)
        self.assertTrue(prorate(proration_items=[item,item],proration_items_complete=True).held_reason)

    def test_public_javascript_matches_python_dates_and_gross_amounts(self):
        import json,re,subprocess
        from pathlib import Path
        html=Path('public/calculator_flow/mid_month_proration_calc.html').read_text()
        self.assertEqual(html,Path('wage_calculator/calculator_flow/mid_month_proration_calc.html').read_text())
        match=re.search(r'<script id="proration-engine">(.*?)</script>',html,re.S)
        self.assertIsNotNone(match,'public page needs the settlement-month calculator')
        cases=[{},dict(last_employed_date=None,proration_retirement_effective_date='2026-10-16'),
            dict(monthly_wage=2900000,settlement_month='2024-02',start_date='2024-02-15',last_employed_date='2024-02-20'),
            dict(monthly_wage=3000000,settlement_month='2026-04',last_employed_date='2026-04-15'),
            dict(monthly_wage=3100000,last_employed_date=None,proration_unpaid_periods=[
                dict(start='2026-10-10',end='2026-10-14',reason='무급휴직',confirmed=True)]),
            dict(proration_method='scheduled',proration_scheduled_dates=[f'2026-10-{i:02}' for i in range(1,11)],last_employed_date='2026-10-05'),
            dict(proration_method=None),dict(last_employed_date='2026-02-30'),dict(monthly_wage=-1),
            dict(proration_all_items_proportional=False)]
        params=[dict(monthly_wage=3000000,start_date='2024-01-01',settlement_month='2026-10',
            proration_method='calendar',last_employed_date='2026-10-16',proration_all_items_proportional=True,**{})|c for c in cases]
        js=match.group(1)+'\nprocess.stdout.write(JSON.stringify('+json.dumps(params)+'.map(calculateProration)));'
        rows=json.loads(subprocess.check_output(['node','-e',js],text=True))
        for case,row in zip(cases,rows):
            expected=prorate(**case)
            with self.subTest(case=case):
                self.assertEqual(bool(row.get('held_reason')),bool(expected.held_reason))
                if not expected.held_reason:
                    self.assertEqual(row['prorated_wage'],expected.prorated_wage)
                    self.assertEqual(row['included_dates'],expected.included_dates)
                    self.assertEqual(row['excluded_dates'],expected.excluded_dates)
                    self.assertEqual((row['worked_days'],row['total_days']),(expected.worked_days,expected.total_days))

    def test_contract_pay_does_not_depend_on_ordinary_wage_classification(self):
        r=prorate(fixed_allowances=[dict(name='월 계약수당',amount=100000,is_ordinary=False)])
        self.assertEqual(r.prorated_wage,1600000)

    def test_item_only_request_needs_no_invented_base_wage_or_schedule(self):
        from app.core.pipeline import _run_calculator
        text=_run_calculator(dict(needs_calculation=True,calculation_types_kr=['일할계산급여'],
            settlement_month='2026-10',proration_method='calendar',proration_employed_at_month_start=True,
            last_employed_date='2026-10-16',proration_items_complete=True,
            proration_items=[dict(id='base',name='기본급',amount=3100000,payment_cycle='매월',policy='prorate')]),
            '명시된 급여 항목만으로 10월 일할계산')
        self.assertIsNotNone(text)
        self.assertIn('1,600,000원',text)
        self.assertNotIn('통상시급:',text)
        self.assertNotIn('월 총 예상 수령액',text)

    def test_complete_settlement_items_ignore_unrelated_unknown_cycle(self):
        from wage_calculator.facade import WageCalculator
        inp=WageInput(monthly_wage=3100000,start_date='2024-01-01',settlement_month='2026-10',
            proration_method='calendar',last_employed_date='2026-10-16',proration_items_complete=True,
            proration_items=[dict(id='base',name='기본급',amount=3100000,payment_cycle='매월',policy='prorate')],
            fixed_allowances=[dict(name='별도 참고 금액',amount=100000,payment_cycle='미확인')])
        r=WageCalculator().calculate(inp,['prorated'])
        self.assertEqual(r.summary.get('일할계산 임금'),'1,600,000원')
        self.assertEqual(r.calculation_status,'complete')

    def test_last_employed_and_effective_dates_are_distinct(self):
        r=prorate()
        self.assertEqual((r.prorated_wage,r.worked_days,r.total_days),(1548387,16,31))
        r=prorate(last_employed_date=None,proration_retirement_effective_date='2026-10-16')
        self.assertEqual((r.prorated_wage,r.worked_days),(1451613,15))
        self.assertTrue(prorate(proration_retirement_effective_date='2026-10-16').held_reason)

    def test_month_is_not_taken_from_hire_date(self):
        r=prorate(settlement_month='2026-09',last_employed_date='2026-10-16')
        self.assertEqual((r.prorated_wage,r.worked_days,r.total_days),(3000000,30,30))

    def test_leap_february_and_same_month_hire_exit(self):
        r=prorate(monthly_wage=2_900_000,start_date='2024-02-15',
                  settlement_month='2024-02',last_employed_date='2024-02-20')
        self.assertEqual((r.prorated_wage,r.worked_days,r.total_days),(600000,6,29))

    def test_unpaid_intervals_are_clipped_and_not_double_counted(self):
        periods=[dict(start='2026-09-30',end='2026-10-03',reason='무급휴직',confirmed=True),
                 dict(start='2026-10-02',end='2026-10-05',reason='무급휴직',confirmed=True)]
        r=prorate(monthly_wage=3_100_000,last_employed_date=None,proration_unpaid_periods=periods)
        self.assertEqual((r.prorated_wage,r.worked_days),(2600000,26))
        self.assertEqual(r.excluded_dates,[f'2026-10-{n:02}' for n in range(1,6)])

    def test_scheduled_denominator_includes_explicit_paid_days(self):
        dates=[f'2026-10-{n:02}' for n in [1,2,3,4,5,6,7,8,9,10]]
        r=prorate(proration_method='scheduled',proration_scheduled_dates=dates,last_employed_date='2026-10-05')
        self.assertEqual((r.prorated_wage,r.worked_days,r.total_days),(1500000,5,10))
        self.assertTrue(prorate(proration_method='scheduled').held_reason)
        self.assertTrue(prorate(proration_method='scheduled',proration_scheduled_dates=dates+dates[:1]).held_reason)

    def test_item_prorate_full_and_actual_amounts_sum_once(self):
        rows=[dict(id='base',name='기본급',amount=2_800_000,payment_cycle='매월',policy='prorate'),
              dict(id='meal',name='식대',amount=200_000,payment_cycle='매월',policy='full'),
              dict(id='ot',name='실근로수당',actual_amount=150_000,policy='actual')]
        r=prorate(proration_all_items_proportional=False,proration_items_complete=True,proration_items=rows)
        self.assertEqual(r.prorated_wage,1795161)
        self.assertEqual(sum(x['payable_amount'] for x in r.item_rows),r.prorated_wage)
        self.assertEqual(len(r.item_rows),3)

    def test_annual_equivalent_is_not_an_automatic_monthly_claim(self):
        self.assertTrue(prorate(fixed_allowances=[dict(name='상여',amount=1200000,annual=True)]).held_reason)
        r=prorate(proration_all_items_proportional=False,proration_items_complete=True,
                  proration_items=[dict(id='bonus',name='이번 달 지급 확정 연상여',amount=1200000,
                                        payment_cycle='연',policy='full')])
        self.assertEqual(r.prorated_wage,1200000)

    def test_missing_contract_and_invalid_inputs_hold(self):
        for data in [dict(proration_method=None),dict(settlement_month=None),
                     dict(proration_all_items_proportional=None),dict(settlement_month='2026-13'),
                     dict(last_employed_date='2026-02-30'),dict(start_date='2027-01-01'),
                     dict(proration_unpaid_periods=[dict(start='2026-10-01',end='2026-10-02',confirmed=False)]),
                     dict(proration_items=[dict(id='a',name='기본급',amount=True,policy='prorate',payment_cycle='매월')],
                          proration_items_complete=True,proration_all_items_proportional=False)]:
            with self.subTest(data=data):self.assertTrue(prorate(**data).held_reason)

    def test_no_employment_in_month_is_zero_without_division_error(self):
        r=prorate(settlement_month='2024-01',start_date='2024-02-01',last_employed_date=None)
        self.assertEqual((r.prorated_wage,r.worked_days),(0,0))
        self.assertFalse(r.held_reason)

    def test_analyzer_to_card_preserves_contract_and_does_not_show_full_salary(self):
        from app.core.analyzer import _build_analysis_result
        from app.core.pipeline import _analysis_to_extract_params,_run_calculator
        data=dict(requires_calculation=True,calculation_types=['prorated'],wage_type='월급',wage_amount=3000000,
                  weekly_work_days=5,daily_work_hours=8,start_date='2024-01-01',settlement_month='2026-10',
                  last_employed_date='2026-10-16',proration_method='calendar',proration_all_items_proportional=True)
        text=_run_calculator(_analysis_to_extract_params(_build_analysis_result(data,'2026년 10월 정산')),'10월 급여 일할계산')
        self.assertIn('1,548,387원',text)
        self.assertNotIn('월 총 예상 수령액',text)
        self.assertIn('16/31',text)
        self.assertIn('2026-10-16',text)

if __name__=='__main__':
    unittest.main()
