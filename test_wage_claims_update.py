"""C5: obligations and allocated payments, before interest."""
import unittest
from dataclasses import replace
from wage_calculator.models import WageInput,WorkSchedule,WageType,BusinessSize
from wage_calculator.calculators.ordinary_wage import calc_ordinary_wage
from wage_calculator.calculators.wage_claims import calc_wage_claims


def item(ident='sep',**changes):
    return dict(id=ident,month='2026-09',name='9월 급여',due_date='2026-10-10',
                components=['regular','weekly_holiday'],amount=3000000,paid_amount=0,**{})|changes

def calculate(items=None,**changes):
    inp=WageInput(**(dict(monthly_wage=3000000,reference_year=2026,
        wage_claim_items=items if items is not None else [item()],wage_claim_scope_complete=True,
        wage_claim_amount_basis='gross',wage_claim_calc_date='2026-10-24')|changes))
    return calc_wage_claims(inp,calc_ordinary_wage(inp))


class WageClaimsUpdateTests(unittest.TestCase):
    def test_analyzer_to_card_and_fallback_keep_gross_claim_ledger(self):
        from app.core.analyzer import _build_analysis_result
        from app.core.pipeline import _analysis_to_extract_params,_run_calculator,WAGE_CALC_TOOL
        from wage_calculator.calculators.wage_claims import CLAIM_INPUT_FIELDS
        data=dict(requires_calculation=True,calculation_types=['arrears_principal'],
            wage_claim_scope_complete=True,wage_claim_amount_basis='gross',wage_claim_calc_date='2026-10-24',
            wage_claim_items=[item(paid_amount=1000000)])
        card=_run_calculator(_analysis_to_extract_params(_build_analysis_result(data,'9월 미지급 원금 계산')),'9월 미지급 원금 계산')
        self.assertIn('2,000,000원',card)
        self.assertIn('3,000,000원',card)
        self.assertNotIn('월 총 예상 수령액',card)
        self.assertNotIn('통상시급:',card)
        for field in CLAIM_INPUT_FIELDS:self.assertIn(field,WAGE_CALC_TOOL['input_schema']['properties'])

    def test_facade_passes_generated_original_claim_to_c2(self):
        from wage_calculator.facade import WageCalculator
        row=item(paid_amount=1000000,paid_date='2026-10-15',paid_interest_amount=0)
        inp=WageInput(wage_claim_items=[row],wage_claim_scope_complete=True,wage_claim_amount_basis='gross',
            wage_claim_calc_date='2026-10-24',wage_claim_include_interest=True)
        r=WageCalculator().calculate(inp,['arrears_principal'])
        # 300만원×20%×5일 + 200만원×20%×9일 /365, 원 단위 반올림.
        self.assertEqual(r.summary.get('남은 체불 원금'),'2,000,000원')
        self.assertEqual(r.summary.get('남은 지연이자'),'18,082원')
        self.assertEqual(r.summary.get('남은 원금·이자 합계'),'2,018,082원')

    def test_full_principal_paid_late_can_leave_interest(self):
        from wage_calculator.facade import WageCalculator
        inp=WageInput(wage_claim_items=[item(paid_amount=3000000,paid_date='2026-10-15',paid_interest_amount=0)],
            wage_claim_scope_complete=True,wage_claim_amount_basis='gross',wage_claim_calc_date='2026-10-24')
        r=WageCalculator().calculate(inp,['arrears_principal','wage_arrears'])
        self.assertEqual(r.summary.get('남은 체불 원금'),'0원')
        self.assertEqual(r.summary.get('남은 지연이자'),'8,219원')

    def test_undated_payment_preserves_principal_and_holds_only_interest(self):
        from wage_calculator.facade import WageCalculator
        inp=WageInput(wage_claim_items=[item(paid_amount=1000000)],wage_claim_scope_complete=True,
            wage_claim_amount_basis='gross',wage_claim_calc_date='2026-10-24')
        r=WageCalculator().calculate(inp,['arrears_principal','wage_arrears'])
        self.assertEqual(r.summary.get('미지급 원금 합계'),'2,000,000원')
        self.assertEqual(r.calculation_status,'partial')
        self.assertNotIn('남은 원금·이자 합계',r.summary)
        self.assertTrue(any(x['target']=='wage_arrears' for x in r.calculation_skipped))

    def test_explicit_claims_do_not_need_unrelated_allowance_cycle_or_schedule(self):
        from wage_calculator.facade import WageCalculator
        inp=WageInput(wage_claim_items=[item()],wage_claim_scope_complete=True,wage_claim_amount_basis='gross',
            wage_claim_calc_date='2026-10-24',fixed_allowances=[dict(name='참고 상여',amount=100000,payment_cycle='미확인')])
        r=WageCalculator().calculate(inp,['arrears_principal'])
        self.assertEqual(r.summary.get('미지급 원금 합계'),'3,000,000원')
        self.assertEqual(r.calculation_status,'complete')

    def test_direct_claim_input_auto_detects_only_the_requested_settlement(self):
        from wage_calculator.facade import WageCalculator
        inp=WageInput(wage_claim_items=[item()],wage_claim_scope_complete=True,wage_claim_amount_basis='gross',
            wage_claim_calc_date='2026-10-24')
        r=WageCalculator().calculate(inp)
        self.assertEqual(r.calculation_executed,['arrears_principal'])
        self.assertEqual(r.summary.get('미지급 원금 합계'),'3,000,000원')

    def test_unknown_total_is_not_used_as_ordinary_wage_for_derived_claim(self):
        r=calculate([item(source='ordinary_hours',amount=None,hours=100,basis_confirmed=True,components=['regular'])],
                    settlement_month='2026-09',wage_composition_known=True)
        self.assertTrue(r.held_reason)
        self.assertFalse(calculate(wage_composition_known=True).held_reason)

    def test_full_payment_is_zero_and_partial_payment_is_difference(self):
        for paid,remaining in [(0,3000000),(1000000,2000000),(3000000,0)]:
            r=calculate([item(paid_amount=paid)])
            self.assertFalse(r.held_reason)
            self.assertEqual(r.remaining_principal,remaining)
            self.assertEqual(r.total_obligation-r.total_paid,remaining)

    def test_multiple_months_and_overpayment_do_not_offset(self):
        r=calculate([item('aug',month='2026-08',due_date='2026-09-10',amount=2000000,paid_amount=2100000),
                     item(amount=2000000,paid_amount=1500000)])
        self.assertEqual((r.remaining_principal,r.overpayment),(500000,100000))
        self.assertEqual(r.total_obligation-r.total_paid+r.overpayment,r.remaining_principal)

    def test_duplicate_components_and_source_ids_hold(self):
        for rows in [[item(),item('other')],[item(),item('sep',components=['overtime'])]]:
            self.assertTrue(calculate(rows).held_reason)

    def test_net_cash_and_missing_paid_amount_are_not_gross_principal(self):
        self.assertTrue(calculate(wage_claim_amount_basis='net').held_reason)
        row=item();row.pop('paid_amount')
        self.assertTrue(calculate([row]).held_reason)
        self.assertTrue(calculate(wage_claim_scope_complete=False).held_reason)

    def test_confirmed_adjustments_correct_obligation_not_payments(self):
        r=calculate(wage_claim_adjustments=[dict(id='fix',item_id='sep',amount=-100000,reason='계약액 오기 정정',confirmed=True)])
        self.assertEqual((r.total_obligation,r.remaining_principal),(2900000,2900000))
        self.assertTrue(calculate(wage_claim_adjustments=[dict(id='x',item_id='sep',amount=-4000000,reason='정정',confirmed=True)]).held_reason)

    def test_allocated_lump_payment_and_exact_reconciliation(self):
        rows=[item('base',components=['regular'],amount=2000000),item('ot',components=['overtime'],amount=500000)]
        for row in rows:row.pop('paid_amount')
        payment=dict(id='p1',date='2026-10-15',amount=1000000,allocation_confirmed=True,
                     allocations=[dict(item_id='base',principal_amount=800000,interest_amount=0),
                                  dict(item_id='ot',principal_amount=200000,interest_amount=0)])
        r=calculate(rows,wage_claim_payments=[payment])
        self.assertEqual(r.remaining_principal,1500000)
        self.assertEqual([x['paid_principal'] for x in r.items],[800000,200000])
        self.assertTrue(calculate(rows,wage_claim_payments=[dict(payment,amount=1100000)]).held_reason)
        self.assertTrue(calculate(rows,wage_claim_payments=[dict(payment,allocation_confirmed=False)]).held_reason)

    def test_summary_payment_and_details_are_counted_once(self):
        p=dict(id='p',date='2026-10-10',amount=1000000,allocation_confirmed=True,
               allocations=[dict(item_id='sep',principal_amount=1000000,interest_amount=0)])
        self.assertEqual(calculate([item(paid_amount=1000000)],wage_claim_payments=[p]).remaining_principal,2000000)
        self.assertTrue(calculate([item(paid_amount=900000)],wage_claim_payments=[p]).held_reason)

    def test_interest_bridge_keeps_original_amount_and_payment_history(self):
        r=calculate([item(paid_amount=1000000,paid_date='2026-10-15',paid_interest_amount=0)])
        self.assertEqual(r.interest_claims[0]['amount'],3000000)
        self.assertEqual(r.interest_claims[0]['payments'][0]['principal_amount'],1000000)
        self.assertEqual(r.interest_claims[0]['payments'][0]['date'],'2026-10-15')
        self.assertFalse(r.interest_held_reason)
        r=calculate([item(paid_amount=1000000)])
        self.assertEqual(r.remaining_principal,2000000)
        self.assertTrue(r.interest_held_reason)

    def test_future_due_amount_is_separate_and_future_payment_rejected(self):
        r=calculate([item(due_date='2026-10-25')])
        self.assertEqual((r.overdue_principal,r.not_yet_due),(0,3000000))
        self.assertEqual(r.interest_claims,[])
        self.assertTrue(calculate([item(paid_amount=1000,paid_date='2026-10-25')]).held_reason)

    def test_invalid_dates_money_ids_and_unconfirmed_corrections_hold(self):
        for row in [item(amount=-1),item(amount=True),item(amount=float('inf')),item(month='2026-13'),
                    item(due_date='2026-02-30'),item(paid_amount=-1),item(components=[]),item(id='')]:
            with self.subTest(row=row):self.assertTrue(calculate([row]).held_reason)
        self.assertTrue(calculate(wage_claim_adjustments=[dict(id='x',item_id='sep',amount=1,reason='정정',confirmed=False)]).held_reason)

    def test_annual_bonus_only_on_explicit_due_item(self):
        r=calculate([item('bonus',name='연 상여',components=['bonus:annual'],amount=1200000,payment_cycle='연')])
        self.assertEqual(r.remaining_principal,1200000)
        self.assertTrue(calculate([item(amount=None,source='monthly_estimate',basis_confirmed=True)],settlement_month='2026-09',
            fixed_allowances=[dict(name='상여',amount=1200000,annual=True)]).held_reason)

    def test_prorated_item_is_reused_without_second_proration(self):
        row=item('oct',month='2026-10',amount=None,source='prorated',source_item_id='monthly_contract',
                 basis_confirmed=True,paid_amount=1000000,paid_date='2026-10-20',paid_interest_amount=0,due_date='2026-10-20')
        r=calculate([row],settlement_month='2026-10',start_date='2024-01-01',last_employed_date='2026-10-16',
                    proration_method='calendar',proration_all_items_proportional=True)
        self.assertEqual((r.total_obligation,r.remaining_principal),(1548387,548387))

    def test_actual_month_overtime_hours_are_not_multiplied_by_monthly_weeks(self):
        inp=WageInput(wage_type=WageType.HOURLY,hourly_wage=15000,business_size=BusinessSize.OVER_5,
            reference_year=2026,settlement_month='2026-09',wage_claim_scope_complete=True,wage_claim_amount_basis='gross',
            wage_claim_calc_date='2026-10-24',wage_claim_items=[item(amount=None,source='overtime',hours=20,
            basis_confirmed=True,components=['overtime'],paid_amount=100000)])
        r=calc_wage_claims(inp,calc_ordinary_wage(inp))
        self.assertEqual((r.total_obligation,r.remaining_principal),(450000,350000))

    def test_minimum_wage_floor_and_unpaid_wages_are_not_added_twice(self):
        inp=WageInput(monthly_wage=2000000,reference_year=2026,settlement_month='2026-09',
            wage_claim_scope_complete=True,wage_claim_amount_basis='gross',wage_claim_calc_date='2026-10-24',
            wage_claim_items=[item(amount=None,source='minimum_wage',monthly_hours=209,basis_confirmed=True,paid_amount=1800000)])
        r=calc_wage_claims(inp,calc_ordinary_wage(inp))
        self.assertEqual((r.total_obligation,r.remaining_principal),(2156880,356880))
        inp.wage_claim_items.append(item('extra',amount=200000,paid_amount=0))
        self.assertTrue(calc_wage_claims(inp,calc_ordinary_wage(inp)).held_reason)

    def test_ordinary_hours_and_confirmed_weeks_reuse_existing_calculators(self):
        inp=WageInput(wage_type=WageType.HOURLY,hourly_wage=15000,reference_year=2026,settlement_month='2026-09',
            weekly_attendance_days=5,wage_claim_scope_complete=True,wage_claim_amount_basis='gross',
            wage_claim_calc_date='2026-10-24',wage_claim_items=[
                item('regular',amount=None,source='ordinary_hours',hours=100,basis_confirmed=True,components=['regular']),
                item('weekly',amount=None,source='weekly_holiday',weeks=4,basis_confirmed=True,components=['weekly_holiday'])])
        r=calc_wage_claims(inp,calc_ordinary_wage(inp))
        self.assertEqual(r.total_obligation,1980000)

    def test_monthly_estimate_is_marked_and_cannot_create_confirmed_interest_claim(self):
        r=calculate([item(amount=None,source='monthly_estimate',basis_confirmed=True)],settlement_month='2026-09')
        self.assertEqual(r.remaining_principal,3000000)
        self.assertTrue(r.is_estimate)
        self.assertTrue(r.interest_held_reason)

if __name__=='__main__':unittest.main()
