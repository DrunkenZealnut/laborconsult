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

if __name__=='__main__':unittest.main()
