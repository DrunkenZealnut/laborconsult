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
    def test_monthly_salary_weekly_holiday_is_not_a_separate_claim(self):
        """월급·연봉·포괄임금의 월 임금에는 유급 주휴분이 들어 있다 — 주휴 파생 채권을 만들지 않는다(Codex 리뷰 High 2:
        월급 250만 원에 주휴 383,560원이 따로 확정되고 월급 행과 함께면 의무액 2,883,560원). 시급제는 그대로 계산한다."""
        schedule=WorkSchedule(daily_work_hours=8,weekly_work_days=5)
        weekly=item('wh',amount=None,source='weekly_holiday',weeks=4,basis_confirmed=True,components=['weekly_holiday'])
        common=dict(settlement_month='2026-09',weekly_attendance_days=5,schedule=schedule)
        for wage_type,wage in ((WageType.MONTHLY,dict(monthly_wage=2_500_000)),(WageType.ANNUAL,dict(monthly_wage=None,annual_wage=30_000_000)),
                               (WageType.COMPREHENSIVE,dict(monthly_wage=2_500_000))):
            for items in ([weekly],[item('base',amount=2_500_000,components=['regular']),weekly]):
                with self.subTest(wage_type=wage_type.value,rows=len(items)):
                    r=calculate(items,wage_type=wage_type,**wage,**common)
                    # 포괄임금(명세 없음)은 앞선 가드('수당이 섞인 월 총액을 통상임금으로 쓰지 않음')가 먼저 보류한다 — 결과는 같다
                    self.assertIn('주휴수당을 별도 채권으로 만들지 않습니다' if wage_type!=WageType.COMPREHENSIVE
                                  else '통상임금으로 사용하지 않습니다',r.held_reason)
                    self.assertFalse(r.breakdown.get('월별·항목별 원금 명세'))
        r=calculate([weekly],wage_type=WageType.HOURLY,monthly_wage=None,hourly_wage=12_000,**common)
        self.assertEqual(r.held_reason,'')
        self.assertEqual([x['obligation'] for x in r.breakdown['월별·항목별 원금 명세']],[384_000])

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
        row=item(paid_amount=1000000,paid_date='2026-10-15',paid_interest_amount=0,paid_allocation_confirmed=True)
        inp=WageInput(wage_claim_items=[row],wage_claim_scope_complete=True,wage_claim_amount_basis='gross',
            wage_claim_calc_date='2026-10-24',wage_claim_include_interest=True)
        r=WageCalculator().calculate(inp,['arrears_principal'])
        # 원금 충당 합의가 확인된 지급: 300만원×20%×5일 + 200만원×20%×9일 /365, 원 단위 반올림.
        self.assertEqual(r.summary.get('남은 체불 원금'),'2,000,000원')
        self.assertEqual(r.summary.get('남은 지연이자'),'18,082원')
        self.assertEqual(r.summary.get('남은 원금·이자 합계'),'2,018,082원')
        # 합의가 없으면 지급일까지의 지연이자 8,219원에 먼저 충당된다(민법 제479조) — 원금 우선 값을 함께 싣는다
        row.pop('paid_allocation_confirmed')
        r=WageCalculator().calculate(inp,['arrears_principal'])
        self.assertEqual((r.summary.get('남은 체불 원금'),r.summary.get('남은 원금·이자 합계')),('2,008,219원','2,018,123원'))
        self.assertTrue(any('남은 원금은 2,000,000원(합계 2,018,082원)' in w for w in r.warnings),r.warnings)

    def test_full_principal_paid_late_can_leave_interest(self):
        from wage_calculator.facade import WageCalculator
        row=item(paid_amount=3000000,paid_date='2026-10-15',paid_interest_amount=0,paid_allocation_confirmed=True)
        inp=WageInput(wage_claim_items=[row],
            wage_claim_scope_complete=True,wage_claim_amount_basis='gross',wage_claim_calc_date='2026-10-24')
        r=WageCalculator().calculate(inp,['arrears_principal','wage_arrears'])
        self.assertEqual(r.summary.get('남은 체불 원금'),'0원')
        self.assertEqual(r.summary.get('남은 지연이자'),'8,219원')
        # 합의가 없으면 받은 300만원 중 8,219원은 지연이자에 충당되어 원금 8,219원이 남는다
        row.pop('paid_allocation_confirmed')
        r=WageCalculator().calculate(inp,['arrears_principal','wage_arrears'])
        self.assertEqual((r.summary.get('남은 체불 원금'),r.summary.get('남은 원금·이자 합계')),('8,219원','8,260원'))

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
        r=calculate([item(paid_amount=1000000,paid_date='2026-10-15',paid_interest_amount=0,paid_allocation_confirmed=True)])
        self.assertEqual(r.interest_claims[0]['amount'],3000000)
        self.assertEqual(r.interest_claims[0]['payments'][0]['principal_amount'],1000000)
        self.assertEqual(r.interest_claims[0]['payments'][0]['date'],'2026-10-15')
        self.assertFalse(r.interest_held_reason)
        # 합의가 없으면 C2로 넘기는 이력도 법정 충당(이자 8,219 / 원금 991,781)이다
        r=calculate([item(paid_amount=1000000,paid_date='2026-10-15',paid_interest_amount=0)])
        self.assertEqual({k:r.interest_claims[0]['payments'][0][k] for k in ('principal_amount','interest_amount')},
                         dict(principal_amount=991781,interest_amount=8219))
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

    def test_retirement_deadline_precedes_original_payday(self):
        from wage_calculator.facade import WageCalculator
        inp=WageInput(wage_claim_items=[item(due_date='2026-11-10')],wage_claim_scope_complete=True,
            wage_claim_amount_basis='gross',wage_claim_calc_date='2026-10-24',wage_claim_include_interest=True,
            arrear_retirement_effective_date='2026-10-01',arrear_deadline_holidays=[])
        r=WageCalculator().calculate(inp,['arrears_principal'])
        self.assertEqual(r.summary.get('지급기일 경과 체불 원금'),'3,000,000원')
        self.assertEqual(r.summary.get('남은 원금·이자 합계'),'3,016,438원')
        self.assertIn('2026-10-14',str(r.summary))

    def test_weekly_attendance_survives_both_extractors(self):
        from app.core.analyzer import _build_analysis_result
        from app.core.pipeline import _analysis_to_extract_params,_run_calculator,WAGE_CALC_TOOL
        from app.templates.prompts import ANALYZE_TOOL
        row=item(source='weekly_holiday',amount=None,weeks=4,basis_confirmed=True,components=['weekly_holiday'])
        data=dict(requires_calculation=True,calculation_types=['arrears_principal'],wage_type='시급',wage_amount=15000,
            weekly_work_days=5,daily_work_hours=8,weekly_attendance_days=5,settlement_month='2026-09',
            reference_year=2026,reference_date='2026-10-24',
            wage_claim_items=[row],wage_claim_scope_complete=True,wage_claim_amount_basis='gross',wage_claim_calc_date='2026-10-24')
        for schema in [ANALYZE_TOOL,WAGE_CALC_TOOL]:self.assertIn('weekly_attendance_days',schema['input_schema']['properties'])
        params=_analysis_to_extract_params(_build_analysis_result(data,'주휴 원금'))
        self.assertEqual(params.get('weekly_attendance_days'),5)
        for p in [params,dict(data,needs_calculation=True,calculation_types_kr=['arrears_principal'])]:
            self.assertIn('480,000원',_run_calculator(p,'주5일 하루8시간 시급15000원 주휴 원금'))

    def test_fallback_advertises_actual_claim_dependencies(self):
        from app.core.pipeline import WAGE_CALC_TOOL
        props=WAGE_CALC_TOOL['input_schema']['properties']
        exclusions=props['wage_claim_items']['items']['properties']['exclusions']['items']
        self.assertTrue({'start_date','end_date','reason','eligible'} <= set(exclusions.get('properties',{})))
        for k in ['fixed_allowances','monthly_total_pay','arrear_retirement_effective_date','arrear_deadline_holidays',
                  'is_post_retirement_arrear','debtor_is_merchant','arrear_exclusions','weekly_attendance_days']:
            with self.subTest(k=k):self.assertIn(k,props)

    def test_nonattendance_cannot_create_confirmed_weekly_debt(self):
        for attendance in [4,-1,6,True]:
            with self.subTest(attendance=attendance):
                r=calculate([item(source='weekly_holiday',amount=None,weeks=4,basis_confirmed=True,components=['weekly_holiday'])],
                    wage_type=WageType.HOURLY,hourly_wage=15000,settlement_month='2026-09',weekly_attendance_days=attendance)
                self.assertTrue(r.held_reason)

    def test_derived_claim_requires_wage_and_schedule_for_monthly_allowance(self):
        from app.core.analyzer import _build_analysis_result
        from app.core.pipeline import _analysis_to_extract_params,_run_calculator
        row=item(source='overtime',amount=None,hours=20,basis_confirmed=True,components=['overtime'])
        common=dict(requires_calculation=True,calculation_types=['arrears_principal'],settlement_month='2026-09',
            reference_year=2026,reference_date='2026-10-24',
            wage_claim_items=[row],wage_claim_scope_complete=True,wage_claim_amount_basis='gross',wage_claim_calc_date='2026-10-24')
        for extra in [{},{'wage_type':'시급','wage_amount':15000,'fixed_allowances':[dict(name='직책수당',amount=300000,payment_cycle='매월')]}]:
            with self.subTest(extra=extra):
                card=_run_calculator(_analysis_to_extract_params(_build_analysis_result(common|extra,'연장 체불 원금')),'연장 체불 원금')
                self.assertIn('보류',card)
                self.assertNotIn('미지급 원금 합계:',card)
        # An explicitly supplied hourly rate alone needs no schedule divisor.
        card=_run_calculator(_analysis_to_extract_params(_build_analysis_result(common|dict(wage_type='시급',wage_amount=15000),'연장 체불 원금')),'연장 체불 원금')
        self.assertIn('450,000원',card)

    def test_aggregate_contract_knows_included_fixed_overtime(self):
        allowance=dict(name='고정연장수당',amount=500000,payment_cycle='매월')
        for source in ['minimum_wage','prorated']:
            extra=dict(settlement_month='2026-09',monthly_wage=2000000,fixed_allowances=[allowance])
            row=item(source=source,amount=None,basis_confirmed=True,monthly_hours=209,source_item_id='monthly_contract')
            if source=='prorated':extra.update(proration_employed_at_month_start=True,proration_all_items_proportional=True,proration_method='calendar')
            r=calculate([row,item('ot',amount=450000,components=['overtime'])],**extra)
            with self.subTest(source=source):self.assertTrue(r.held_reason)

    def test_aggregate_monthly_bonus_component_cannot_be_claimed_twice(self):
        row=item(source='minimum_wage',amount=None,basis_confirmed=True,monthly_hours=209)
        r=calculate([row,item('bonus',amount=200000,components=['bonus:monthlybonus'])],settlement_month='2026-09',
            fixed_allowances=[dict(name='정기상여',source_id='monthlybonus',amount=200000,payment_cycle='매월')])
        self.assertTrue(r.held_reason)

    def test_unknown_probation_amount_holds_even_when_both_rates_fail(self):
        row=item(source='minimum_wage',amount=None,basis_confirmed=True,monthly_hours=209)
        r=calculate([row],monthly_wage=1700000,settlement_month='2026-09',is_probation=True)
        self.assertTrue(r.held_reason)
        r=calculate([row],monthly_wage=1700000,settlement_month='2026-09',is_probation=True,contract_months=6)
        self.assertFalse(r.held_reason)  # explicitly ineligible for reduction
        self.assertEqual(r.total_obligation,2156880)

    def test_facade_uses_resolved_size_and_normalized_schedule_for_sources(self):
        from wage_calculator.facade import WageCalculator
        from wage_calculator.models import BusinessSizeInput
        inp=WageInput(wage_type=WageType.HOURLY,hourly_wage=15000,reference_year=2026,settlement_month='2026-09',
            wage_claim_scope_complete=True,wage_claim_amount_basis='gross',wage_claim_calc_date='2026-10-24',
            wage_claim_items=[item(source='overtime',amount=None,hours=20,basis_confirmed=True,components=['overtime'])],
            business_size_input=BusinessSizeInput(event_date='2026-10-01',daily_headcount={'2026-09-01':4}))
        r=WageCalculator().calculate(inp,['business_size','arrears_principal'])
        self.assertEqual(r.summary.get('사업장 규모'),'5인미만')
        self.assertEqual(r.summary.get('지급 의무액 합계'),'300,000원')
        inp=WageInput(monthly_wage=1700000,schedule=WorkSchedule(daily_work_hours=10,weekly_work_days=5),
            settlement_month='2026-09',reference_year=2026,wage_claim_items=[item(source='minimum_wage',amount=None,basis_confirmed=True)],
            wage_claim_scope_complete=True,wage_claim_amount_basis='gross',wage_claim_calc_date='2026-10-24')
        r=WageCalculator().calculate(inp,['arrears_principal'])
        self.assertEqual(r.calculation_status,'not_run')

    def test_unassigned_global_exclusions_hold_interest_only(self):
        from wage_calculator.facade import WageCalculator
        inp=WageInput(wage_claim_items=[item()],wage_claim_scope_complete=True,wage_claim_amount_basis='gross',
            wage_claim_calc_date='2026-10-24',wage_claim_include_interest=True,debtor_is_merchant=False,
            arrear_exclusions=[dict(start_date='2026-10-11',end_date='2026-10-24',reason='insolvency',eligible=True)])
        r=WageCalculator().calculate(inp,['arrears_principal'])
        self.assertEqual(r.summary.get('미지급 원금 합계'),'3,000,000원')
        self.assertNotIn('남은 원금·이자 합계',r.summary)
        self.assertTrue(any(x['target']=='wage_arrears' for x in r.calculation_skipped))
        inp.wage_claim_items[0]['exclusions']=inp.arrear_exclusions;inp.arrear_exclusions=None
        r=WageCalculator().calculate(inp,['arrears_principal'])
        self.assertEqual(r.summary.get('남은 지연이자'),'5,753원')

    def test_explicit_separate_interest_request_is_preserved(self):
        from wage_calculator.facade import WageCalculator
        inp=WageInput(wage_claim_items=[item()],wage_claim_scope_complete=True,wage_claim_amount_basis='gross',
            wage_claim_calc_date='2026-10-24',wage_claim_include_interest=False,arrear_amount=1000000,
            arrear_due_date='2026-08-10',arrear_calc_date='2026-10-24')
        r=WageCalculator().calculate(inp,['arrears_principal','wage_arrears'])
        self.assertEqual(r.summary.get('미지급 원금 합계'),'3,000,000원')
        self.assertEqual(r.summary.get('남은 체불 원금'),'1,000,000원')
        self.assertEqual(r.calculation_status,'complete')
        inp.wage_claim_include_interest=None
        self.assertEqual(WageCalculator().calculate(inp,['arrears_principal','wage_arrears']).calculation_status,'partial')

    def test_extraction_budget_covers_ledger_with_a_bound(self):
        from app.core import llm_gateway as gw
        from unittest.mock import Mock,patch
        from types import SimpleNamespace as NS
        self.assertGreaterEqual(gw.extraction_budget('36개월 체불 원금 정산 '+('지급 내역 '*500)),8192)
        self.assertLessEqual(gw.extraction_budget('체불 '+('월급 '*100000)),32768)
    def test_each_provider_rejects_truncated_valid_tool_arguments(self):
        from app.core import llm_gateway as gw
        from unittest.mock import Mock,patch
        from types import SimpleNamespace as NS
        c=Mock();c.with_options.return_value=c
        c.messages.create.return_value=NS(stop_reason='max_tokens',content=[NS(type='tool_use',name='ledger',input={'wage_claim_scope_complete':True})])
        with self.subTest(provider='claude'),self.assertRaises(ValueError):gw._claude_tool(NS(claude_client=c),'m',None,[],[],None,8192,10)
        c.chat.completions.create.return_value=NS(choices=[NS(finish_reason='length',message=NS(tool_calls=[NS(function=NS(name='ledger',arguments='{"wage_claim_scope_complete":true}'))]))])
        with self.subTest(provider='openai'),self.assertRaises(ValueError):gw._openai_tool(NS(openai_client=c),'m',None,[],[],None,8192,10)
        c.generate_content.return_value=NS(candidates=[NS(finish_reason=2,content=NS(parts=[]))])
        with self.subTest(provider='gemini'),patch.object(gw,'_gemini_model',return_value=c),self.assertRaises(ValueError):
            gw._gemini_tool(NS(),'m',None,[],[],None,8192,10)

    def test_analyzer_and_fallback_request_ledger_sized_budget(self):
        from unittest.mock import patch
        from types import SimpleNamespace as NS
        from app.core.analyzer import analyze_intent
        from app.core.pipeline import _extract_params
        from app.core import llm_gateway as gw
        data=dict(requires_calculation=True,calculation_types=['arrears_principal'],wage_claim_items=[item()])
        with patch.object(gw,'tool',return_value=('OpenAI','analyze_labor_question',data)) as call:
            analyze_intent('36개월 체불 원금 정산',[],NS())
            self.assertGreaterEqual(call.call_args.kwargs['max_tokens'],8192)
        with patch.object(gw,'tool',return_value=('OpenAI','wage_params',dict(needs_calculation=True))) as call:
            _extract_params('36개월 체불 원금 정산',NS())
            self.assertGreaterEqual(call.call_args.kwargs['max_tokens'],8192)

    # ── wage-update-followups PR-3 ──────────────────────────────────────────────────────────────
    C5=dict(wage_claim_scope_complete=True,wage_claim_amount_basis='gross',wage_claim_calc_date='2026-10-24')
    JUL=dict(id='jul',month='2026-07',name='7월 급여',due_date='2026-08-10',components=['regular','weekly_holiday'],
             amount=3_000_000,paid_amount=1_000_000,paid_date='2026-09-10')

    @staticmethod
    def _card(raw,query):
        from app.core.analyzer import _build_analysis_result
        from app.core.pipeline import _analysis_to_extract_params,_run_calculator
        return _run_calculator(_analysis_to_extract_params(_build_analysis_result(raw,query)),query)

    @staticmethod
    def _skipped(r,target):
        return ' '.join(x['reason'] for x in r.calculation_skipped if x['target']==target)

    def test_omitted_interest_relation_with_separate_arrear_is_not_added_as_second_claim(self):
        """A1: 원금 정산과 별도 체불 입력의 관계를 말하지 않으면 '모름'이다 — 같은 채권의 이자를 두 번 더하지 않는다."""
        from wage_calculator.facade import WageCalculator
        self.assertIsNone(WageInput().wage_claim_include_interest)
        raw=dict(requires_calculation=True,calculation_types=['arrears_principal','wage_arrears'],wage_claim_items=[item()],
                 arrear_amount=3_000_000,arrear_due_date='2026-10-10',arrear_calc_date='2026-10-24',**self.C5)
        text=self._card(raw,'9월 급여 300만원 못 받았고 지연이자도 알려주세요')
        self.assertNotIn('3,023,014',text)
        self.assertIn('중복 여부',text)
        r=WageCalculator().calculate(WageInput(wage_claim_items=[item()],arrear_amount=3_000_000,arrear_due_date='2026-10-10',
            arrear_calc_date='2026-10-24',**self.C5),['arrears_principal','wage_arrears'])
        self.assertEqual((r.calculation_status,r.summary.get('미지급 원금 합계')),('partial','3,000,000원'))
        self.assertNotIn('남은 원금·이자 합계',r.summary)

    def test_late_summary_payment_uses_statutory_allocation(self):
        """A2(Q1 b): 지급기일 뒤 일부 지급은 합의가 없으면 그때까지의 지연이자에 먼저 충당된다(민법 제479조) — 원금 우선 값을
        함께 싣는다. 7월분 300만·기일 8/10·9/10에 100만: 법정 2,050,959/2,100,407, 원금 우선 2,000,000/2,099,178."""
        from wage_calculator.facade import WageCalculator
        from wage_calculator.calculators.wage_arrears import calc_wage_arrears
        common=dict(self.C5,wage_claim_include_interest=True,debtor_is_merchant=False)
        calc=lambda row,**kw:WageCalculator().calculate(WageInput(wage_claim_items=[row],**(common|kw)),['arrears_principal'])
        note="그 경우 남은 원금은 2,000,000원(합계 2,099,178원)입니다"
        for extra in ({},{'paid_interest_amount':0}):
            with self.subTest(extra=extra):
                r=calc(dict(self.JUL,**extra))
                self.assertEqual((r.calculation_status,r.summary.get('미지급 원금 합계'),r.summary.get('남은 원금·이자 합계')),
                                 ('complete','2,050,959원','2,100,407원'))
                self.assertTrue(any('민법 제479조' in w and note in w for w in r.warnings),r.warnings)
                self.assertIn('민법 제476조~제479조 (변제충당)',r.legal_basis)
                self.assertTrue(any('지연이자 50,959원에 먼저' in f for f in r.formulas),r.formulas)
        # C2 직접 입력도 같은 결론(충당 확인이 없는 지급 총액 = 원금 + 이자 0)
        c2=calc_wage_arrears(arrear_amount=3_000_000,arrear_due_date='2026-08-10',arrear_calc_date='2026-10-24',
                             debtor_is_merchant=False,payments=[dict(date='2026-09-10',principal_amount=1_000_000,interest_amount=0)])
        self.assertEqual((c2.held_reason,c2.arrear_amount,c2.total_claim),('',2_050_959,2_100_407))
        self.assertTrue(any(note in w for w in c2.warnings),c2.warnings)
        # 충당 합의가 확인되면 입력한 충당 그대로(ww26-20 '합의서로 확인')
        r=calc(dict(self.JUL,paid_interest_amount=0,paid_allocation_confirmed=True))
        self.assertEqual((r.summary.get('미지급 원금 합계'),r.summary.get('남은 원금·이자 합계')),('2,000,000원','2,099,178원'))
        self.assertFalse(any('제479조' in w for w in r.warnings))
        # 지급기일 당일 지급은 충당할 이자가 없어 원금에서 뺀다
        r=calc(dict(self.JUL,paid_date='2026-08-10',paid_interest_amount=0))
        self.assertEqual((r.summary.get('미지급 원금 합계'),r.summary.get('남은 원금·이자 합계')),('2,000,000원','2,082,192원'))
        self.assertFalse(any('제479조' in w for w in r.warnings))
        # 두 추출기 공통 스키마에 합의 플래그가 있다
        from app.templates.prompts import ANALYZE_TOOL
        from app.core.pipeline import WAGE_CALC_TOOL
        for schema in (ANALYZE_TOOL,WAGE_CALC_TOOL):
            props=schema['input_schema']['properties']['wage_claim_items']['items']['properties']
            self.assertIn('paid_allocation_confirmed',props)
            self.assertIn('○월분 급여',props['paid_allocation_confirmed']['description'])
        # 채팅 경로 카드: 합의가 없으면 법정 충당 + 원금 우선 병기, 합의가 명시되면 입력 충당
        raw=dict(requires_calculation=True,calculation_types=['arrears_principal'],wage_claim_include_interest=True,
                 debtor_is_merchant=False,wage_claim_items=[dict(self.JUL)],**self.C5)
        text=self._card(raw,'7월 급여 300만원 중 9월 10일에 100만원만 받았습니다. 남은 돈과 지연이자는?')
        self.assertIn('미지급 원금 합계: 2,050,959원',text)
        self.assertIn('제479조',text)
        self.assertIn('2,000,000원(합계 2,099,178원)',text)
        raw['wage_claim_items']=[dict(self.JUL,paid_interest_amount=0,paid_allocation_confirmed=True)]
        text=self._card(raw,'7월 급여 300만원 중 9월 10일에 100만원을 원금으로 충당하기로 합의하고 받았습니다.')
        self.assertIn('미지급 원금 합계: 2,000,000원',text)

    def test_statutory_allocation_holds_when_interest_rate_is_unknown(self):
        """A2: 지급일까지의 지연이자를 확정할 수 없으면(구 규칙 채권 + 상인 미상 → 연 5%·6%) 그 행을 보류한다."""
        from wage_calculator.facade import WageCalculator
        old=dict(self.JUL,month='2025-08',name='8월 급여',due_date='2025-09-10',paid_date='2025-10-10',paid_interest_amount=0)
        r=WageCalculator().calculate(WageInput(wage_claim_items=[old],**dict(self.C5,wage_claim_calc_date='2025-10-24')),
                                     ['arrears_principal'])
        self.assertEqual(r.calculation_status,'not_run')
        self.assertIn('상인 여부',self._skipped(r,'arrears_principal'))
        self.assertIn('제479조',self._skipped(r,'arrears_principal'))
        # 상인 여부가 확인되면 이율이 하나라 충당한다(민사 5%: 3,000,000×5%×30/365 = 12,329)
        r=WageCalculator().calculate(WageInput(wage_claim_items=[old],debtor_is_merchant=False,
                                               **dict(self.C5,wage_claim_calc_date='2025-10-24')),['arrears_principal'])
        self.assertEqual(r.summary.get('미지급 원금 합계'),'2,012,329원')

    def test_retirement_flag_without_date_settles_principal_and_holds_interest(self):
        """A3: 퇴직 사실만 있고 날짜가 없으면 원래 기일이 지난 원금은 정산하고, 14일 기한·이자만 보류한다."""
        from wage_calculator.facade import WageCalculator
        text=self._card(dict(requires_calculation=True,calculation_types=['arrears_principal'],is_post_retirement_arrear=True,
                             wage_claim_items=[item()],**self.C5),'퇴사했는데 9월 급여 300만원을 못 받았습니다. 미지급 원금은 얼마인가요?')
        self.assertIn('미지급 원금 합계: 3,000,000원',text)
        r=WageCalculator().calculate(WageInput(is_post_retirement_arrear=True,wage_claim_include_interest=True,
            debtor_is_merchant=False,wage_claim_items=[item()],**self.C5),['arrears_principal'])
        self.assertEqual((r.calculation_status,r.summary.get('지급기일 경과 체불 원금')),('partial','3,000,000원'))
        self.assertIn('퇴직 효력일',self._skipped(r,'wage_arrears'))
        r=WageCalculator().calculate(WageInput(is_post_retirement_arrear=True,wage_claim_items=[
            item(),item('oct',month='2026-10',name='10월 급여',due_date='2026-11-10',amount=1_500_000)],**self.C5),['arrears_principal'])
        self.assertEqual(r.summary.get('지급기일 경과 체불 원금'),'3,000,000원')
        self.assertEqual(r.summary.get('기한 미도래·당일 미지급액'),'0원')
        self.assertEqual(r.summary.get('지급기한 미확인 미지급액 (퇴직일 확인 필요)'),'1,500,000원')
        # 원래 기일이 안 지난 행만 있어도 이자를 0원으로 단정하지 않는다
        r=WageCalculator().calculate(WageInput(is_post_retirement_arrear=True,wage_claim_include_interest=True,debtor_is_merchant=False,
            wage_claim_items=[item('oct',month='2026-10',name='10월 급여',due_date='2026-11-10')],**self.C5),['arrears_principal'])
        self.assertNotIn('남은 지연이자',r.summary)
        self.assertIn('퇴직 효력일',self._skipped(r,'wage_arrears'))
        # 퇴직일을 모르면 받은 날이 14일 기한 뒤였는지 알 수 없다 → 법정 충당 여부를 정할 수 없어 보류
        r=WageCalculator().calculate(WageInput(is_post_retirement_arrear=True,wage_claim_items=[
            item(paid_amount=1_000_000,paid_date='2026-10-10',paid_interest_amount=0)],**self.C5),['arrears_principal'])
        self.assertEqual(r.calculation_status,'not_run')
        self.assertIn('퇴직 효력일 또는 마지막 재직일',self._skipped(r,'arrears_principal'))

    def test_severance_row_due_is_fourteen_day_deadline(self):
        """A4(Q4 a): 퇴직금 행의 지급기일은 14일 기한이다 — 입력한 더 이른 기일로 5%·6% 구간을 붙이지 않는다."""
        from wage_calculator.facade import WageCalculator
        from wage_calculator.calculators.wage_arrears import calc_wage_arrears
        sev=dict(id='sev',month='2026-08',name='퇴직금',due_date='2026-09-01',components=['retirement'],amount=10_000_000,paid_amount=0)
        common=dict(self.C5,wage_claim_include_interest=True,arrear_last_employed_date='2026-08-31',is_post_retirement_arrear=True)
        r=WageCalculator().calculate(WageInput(wage_claim_items=[dict(sev)],**common),['arrears_principal'])
        self.assertEqual(r.summary.get('남은 지연이자'),'219,178원')
        self.assertNotIn('민사채무 조건 지연이자',r.summary)
        self.assertTrue(any('퇴직금 지급기한은 2026-09-14' in w and '연 5%(상인은 6%)' in w for w in r.warnings),r.warnings)
        r=WageCalculator().calculate(WageInput(wage_claim_items=[dict(sev)],**dict(common,wage_claim_calc_date='2026-09-05')),['arrears_principal'])
        self.assertEqual((r.summary.get('지급기일 경과 체불 원금'),r.summary.get('기한 미도래·당일 미지급액'),r.summary.get('남은 지연이자')),
                         ('0원','10,000,000원','0원'))
        self.assertTrue(any('아직 퇴직금 지급기한(2026-09-14)이 지나지 않았습니다' in w for w in r.warnings))
        r=WageCalculator().calculate(WageInput(wage_claim_items=[dict(sev)],**dict(common,wage_claim_calc_date='2026-09-15')),['arrears_principal'])
        self.assertEqual(r.summary.get('남은 지연이자'),'5,479원')
        c2=calc_wage_arrears(arrear_amount=10_000_000,arrear_due_date='2026-09-01',claim_kind='retirement_lump_sum',
                             last_employed_date='2026-08-31',arrear_calc_date='2026-10-24',deadline_holidays=[])
        self.assertEqual((c2.interest_amount,c2.due_date),(219_178,'2026-09-14'))
        # 중간정산 가드(퇴직 효력일보다 이른 기일)는 계속 보류
        self.assertTrue(calc_wage_arrears(arrear_amount=10_000_000,arrear_due_date='2026-08-30',claim_kind='retirement_lump_sum',
                                          last_employed_date='2026-08-31',arrear_calc_date='2026-10-24',deadline_holidays=[]).held_reason)
        # 퇴직일이 전혀 없으면 지급기한 미확인 — 이자 보류
        r=WageCalculator().calculate(WageInput(wage_claim_items=[dict(sev)],**dict(self.C5,wage_claim_include_interest=True)),['arrears_principal'])
        self.assertEqual(r.summary.get('지급기한 미확인 미지급액 (퇴직일 확인 필요)'),'10,000,000원')
        self.assertIn('퇴직 효력일',self._skipped(r,'wage_arrears'))

    def test_fixed_overtime_salary_row_and_actual_overtime_counted_once(self):
        """A5: 같은 달 월급에 든 고정연장수당과 실제 연장 근로 임금은 큰 쪽만 — 파생 연장 행에서 고정액을 뺀다."""
        from wage_calculator.facade import WageCalculator
        ot=dict(id='ot',month='2026-09',name='9월 연장수당',due_date='2026-10-10',components=['overtime'],source='overtime',
                hours=20,basis_confirmed=True,paid_amount=0)
        def sal(comps,amount=2_800_000):
            return dict(id='sal',month='2026-09',name='9월 급여',due_date='2026-10-10',components=comps,amount=amount,paid_amount=0)
        base=dict(self.C5,wage_type=WageType.MONTHLY,monthly_wage=2_500_000,schedule=WorkSchedule(daily_work_hours=8,weekly_work_days=5),
                  fixed_allowances=[dict(name='고정연장수당',amount=300_000,payment_cycle='매월')],settlement_month='2026-09',reference_year=2026)
        calc=lambda rows:WageCalculator().calculate(WageInput(wage_claim_items=rows,**base),['arrears_principal'])
        for comps in (['regular','weekly_holiday'],['regular','weekly_holiday','overtime']):
            with self.subTest(comps=comps):
                r=calc([sal(comps),dict(ot)])
                self.assertEqual(r.summary.get('미지급 원금 합계'),'2,859,589원')
                self.assertTrue(any('고정연장수당 300,000원' in f and '추가 의무액 59,589원' in f for f in r.formulas),r.formulas)
        self.assertEqual(calc([sal(['regular','weekly_holiday']),dict(ot,hours=5)]).summary.get('미지급 원금 합계'),'2,800,000원')
        self.assertEqual(calc([sal(['regular','weekly_holiday'],2_500_000),dict(ot)]).calculation_status,'not_run')
        explicit_ot=dict(id='ot2',month='2026-09',name='연장수당',due_date='2026-10-10',components=['overtime'],amount=500_000,paid_amount=0)
        self.assertEqual(calc([sal(['regular','weekly_holiday']),explicit_ot]).calculation_status,'not_run')
        text=self._card(dict(requires_calculation=True,calculation_types=['arrears_principal'],wage_type='월급',wage_amount=2_500_000,
                             weekly_work_days=5,daily_work_hours=8,fixed_allowances=[dict(name='고정연장수당',amount=300_000)],
                             settlement_month='2026-09',reference_year=2026,wage_claim_items=[sal(['regular','weekly_holiday']),dict(ot)],
                             **self.C5),
                        '기본급 250만원에 고정연장수당 30만원 포함 월급 280만원인데 9월 급여를 못 받았고, 9월 연장근로 20시간분도 못 받았습니다. 미지급액은?')
        self.assertIn('2,859,589원',text)
        self.assertNotIn('3,159,589',text)

    def test_gemini_tool_floor_and_ledger_budget_keywords(self):
        """A6: 도구 호출 하한(Gemini 8192)과 원금 장부 예산 표지('정산' 제외, 못 받·밀린 등 포함). 텍스트 단계 하한은 그대로."""
        from unittest.mock import patch
        from types import SimpleNamespace as NS
        from app.core import llm_gateway as gw
        self.assertEqual(gw._MIN_TOOL_TOKENS,{'claude':1024,'openai':4096,'gemini':8192})
        for q in ('9월 급여를 못 받았어요','월급이 두 달째 밀렸어요','36개월 체불 원금 정산'):
            self.assertGreaterEqual(gw.extraction_budget(q),8192,q)
        self.assertGreaterEqual(gw.extraction_budget([{'role':'user','content':'9월 급여를 못 받았어요'}]),8192)
        for q in ('퇴직금 정산 문의','연말정산 환급액 계산'):
            self.assertEqual(gw.extraction_budget(q),1024,q)
        seen={}
        def fake_model(config,model,system,**kw):
            seen.update(kw)
            return NS(generate_content=lambda *a,**k:NS(candidates=[]))
        with patch.object(gw,'_gemini_model',side_effect=fake_model):
            gw._gemini_tool(NS(),'m',None,[],[],None,1024,10)
            self.assertEqual(seen['generation_config']['max_output_tokens'],8192)
            gw._gemini_tool(NS(),'m',None,[],[],None,16384,10)
            self.assertEqual(seen['generation_config']['max_output_tokens'],16384)
        captured={}
        class M:
            def generate_content(self,user,generation_config=None,request_options=None):
                captured.update(generation_config);return NS(candidates=[])
        with patch.object(gw,'_gemini_model',return_value=M()):
            gw._gemini_text(NS(),'m',None,'u',100,10)
        self.assertEqual(captured['max_output_tokens'],2048)

    def test_minimum_wage_basis_only_with_minimum_wage_row(self):
        """A7·A7b: 최저임금법 제6조는 최저임금 행이 있을 때만, 민법 변제충당 조문은 충당 행이 있을 때만 붙인다."""
        from wage_calculator.facade import WageCalculator
        basis='최저임금법 제6조 (최저임금의 효력)';allocation='민법 제476조~제479조 (변제충당)'
        r=WageCalculator().calculate(WageInput(wage_claim_items=[item()],**self.C5),['arrears_principal'])
        self.assertNotIn(basis,r.legal_basis)
        self.assertNotIn(allocation,r.legal_basis)
        r=WageCalculator().calculate(WageInput(monthly_wage=2_000_000,reference_year=2026,settlement_month='2026-09',
            wage_claim_items=[item(amount=None,source='minimum_wage',monthly_hours=209,basis_confirmed=True,paid_amount=1_800_000)],
            **self.C5),['arrears_principal'])
        self.assertIn(basis,r.legal_basis)
        self.assertEqual(r.summary.get('미지급 원금 합계'),'356,880원')
        r=WageCalculator().calculate(WageInput(wage_claim_items=[dict(self.JUL,paid_interest_amount=0,paid_allocation_confirmed=True)],
                                               **self.C5),['arrears_principal'])
        self.assertIn(allocation,r.legal_basis)


if __name__=='__main__':unittest.main()
