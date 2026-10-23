"""월별 의무액·확인된 변제충당 명세. 법률상 채권 인정 여부를 추정하지 않는다."""
import re
from collections import defaultdict
from dataclasses import dataclass,field,replace
from decimal import Decimal,ROUND_HALF_UP

from ..base import BaseCalculatorResult
from ..models import WageType
from ..legal_rules import resolve_reference_date
from .pay_inputs import money,strict_date
from .shared import monthly_wage_total,normalize_allowances

CLAIM_INPUT_FIELDS=frozenset({'wage_claim_items','wage_claim_scope_complete','wage_claim_amount_basis',
    'wage_claim_calc_date','wage_claim_payments','wage_claim_adjustments','wage_claim_include_interest'})
COMPONENTS={'regular','weekly_holiday','overtime','night','holiday','annual_leave','retirement'}
SOURCES={'explicit','ordinary_hours','overtime','night','holiday','weekly_holiday',
         'minimum_wage','prorated','monthly_estimate'}

@dataclass
class WageClaimsResult(BaseCalculatorResult):
    total_obligation: float=0.0
    total_paid: float=0.0
    remaining_principal: float=0.0
    overdue_principal: float=0.0
    not_yet_due: float=0.0
    overpayment: float=0.0
    calc_date: str=''
    is_estimate: bool=False
    items: list=field(default_factory=list)
    interest_claims: list=field(default_factory=list)
    interest_held_reason: str=''


def _hours(value,label):
    n=money(value,label)
    if n>744:raise ValueError(label+'은 한 달의 시간 범위를 넘을 수 없습니다.')
    return n

def _won(n):return int(Decimal(str(n)).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
def _text(value,label):
    if not isinstance(value,str) or not value.strip() or len(value)>150:raise ValueError(label+'을 확인해주세요.')
    return value.strip()
def _month(raw):
    if not isinstance(raw,str) or not re.fullmatch(r'\d{4}-\d{2}',raw):raise ValueError('귀속월 YYYY-MM을 확인해주세요.')
    strict_date(raw+'-01','귀속월');return raw

def claims_are_independent(inp):
    """금액이 명시된 원금 명세는 평소 임금의 지급주기와 무관하다."""
    return (isinstance(inp.wage_claim_items,list) and bool(inp.wage_claim_items)
            and all(isinstance(x,dict) and x.get('source','explicit')=='explicit' for x in inp.wage_claim_items))

def _amount(row,inp,ow):
    source=row.get('source','explicit')
    if source not in SOURCES:raise ValueError('지급 의무액의 산출 출처를 확인해주세요.')
    if source=='explicit':return _won(money(row.get('amount'),'지급 의무액')),set(),False
    if row.get('amount') is not None:raise ValueError('확정 의무액과 별도 산출 출처를 중복 입력하지 마세요.')
    if row.get('basis_confirmed') is not True:raise ValueError('해당 월의 실제 계산 기초·지급 조건을 확인해주세요.')
    if inp.settlement_month!=row['month']:raise ValueError('산출 출처의 정산 대상월과 채권 귀속월이 다릅니다.')
    if source=='prorated':
        from .prorated import calc_prorated
        result=calc_prorated(inp,ow)
        if result.held_reason:raise ValueError(result.held_reason)
        found=[x for x in result.item_rows if x['id']==row.get('source_item_id')]
        if len(found)!=1:raise ValueError('일할 명세의 원본 항목 ID를 확인해주세요.')
        components={'regular','weekly_holiday'} if found[0]['id']=='monthly_contract' else set()
        return found[0]['payable_amount'],components,False
    from .shared import ordinary_wage_from_total
    if source in {'ordinary_hours','overtime','night','holiday','weekly_holiday'} and ordinary_wage_from_total(inp):
        raise ValueError('수당이 섞인 월 총액을 통상임금으로 사용하지 않습니다. 기본급·통상임금 구성을 확인해주세요.')
    for attr in ('hourly_wage','daily_wage','monthly_wage','annual_wage','monthly_total_pay'):
        v=getattr(inp,attr)
        if v is not None:money(v,'계산 기초 임금')
    if inp.reference_year!=int(row['month'][:4]):raise ValueError('계산 기준 연도와 귀속월 연도를 일치시켜주세요.')
    if inp.wage_type!=WageType.HOURLY and (inp.schedule.daily_work_hours<=0 or inp.schedule.weekly_work_days<=0):
        raise ValueError('통상시급 계산에 필요한 소정근로시간을 확인해주세요.')
    if source=='ordinary_hours':
        h=_hours(row.get('hours'),'확정 실제 시간')
        return _won(ow.hourly_ordinary_wage*h),{'regular'},False
    if source in ('overtime','night','holiday'):
        from .overtime import calc_overtime
        h=_hours(row.get('hours'),'확정 실제 시간')
        extra=_hours(row.get('holiday_overtime_hours',0),'휴일 8시간 초과 시간')
        if source!='holiday' and extra:raise ValueError('휴일 초과 시간은 휴일수당 항목에서 구분해주세요.')
        schedule=replace(inp.schedule,weekly_overtime_hours=0,weekly_night_hours=0,weekly_holiday_hours=0,
                         weekly_holiday_overtime_hours=0)
        setattr(schedule,{'overtime':'weekly_overtime_hours','night':'weekly_night_hours','holiday':'weekly_holiday_hours'}[source],h)
        if source=='holiday':schedule.weekly_holiday_overtime_hours=extra
        result=calc_overtime(replace(inp,schedule=schedule,hour_split=None),ow)
        return _won(getattr(result,source+'_pay')),{source},False
    if source=='weekly_holiday':
        from .weekly_holiday import calc_weekly_holiday
        weeks=row.get('weeks')
        if isinstance(weeks,bool) or not isinstance(weeks,int) or not 1<=weeks<=6:raise ValueError('동일 조건으로 확정된 주휴 대상 주 수를 확인해주세요.')
        if inp.weekly_attendance_days is None:raise ValueError('주휴 대상 주의 개근 여부를 확인해주세요.')
        result=calc_weekly_holiday(replace(inp,end_date=None),ow)
        if result.held_reason:raise ValueError(result.held_reason)
        return _won(result.weekly_holiday_pay*weeks),{'weekly_holiday'},False
    if any(a.annual or a.payment_cycle!='매월' for a in normalize_allowances(inp.fixed_allowances)):
        raise ValueError('연·분기 상여의 월 환산액을 채권으로 만들지 않습니다. 실제 지급월·금액·기일을 입력해주세요.')
    contract=monthly_wage_total(inp,ow,premium=source=='monthly_estimate')
    components={'regular','weekly_holiday'}
    if source=='minimum_wage':
        from .minimum_wage import calc_minimum_wage
        if inp.wage_type!=WageType.MONTHLY or any((inp.schedule.weekly_overtime_hours,inp.schedule.weekly_night_hours,inp.schedule.weekly_holiday_hours)):
            raise ValueError('최저임금 월 의무액은 연장 등을 분리한 월급 계약·완전한 월의 조건을 확인해주세요.')
        minimum_basis=ow
        if row.get('monthly_hours') is not None:
            hours=_hours(row['monthly_hours'],'확인된 월 유급시간')
            if hours<=0:raise ValueError('월 유급시간은 0보다 커야 합니다.')
            minimum_basis=replace(ow,monthly_base_hours=hours)
        result=calc_minimum_wage(inp,minimum_basis)
        if result.undetermined or result.not_applicable:raise ValueError('최저임금 산입 범위·적용 조건이 미확인되어 의무액을 확정할 수 없습니다.')
        return _won(contract+result.shortage_monthly),components,False
    if inp.schedule.weekly_overtime_hours:components.add('overtime')
    if inp.schedule.weekly_night_hours:components.add('night')
    if inp.schedule.weekly_holiday_hours:components.add('holiday')
    return _won(contract),components,True

def _calculate(inp,ow):
    if inp.is_platform_worker:raise ValueError('임금 채권을 정산하려면 근로자성을 확인해주세요.')
    if inp.wage_claim_scope_complete is not True:raise ValueError('요청 정산 범위의 전체 항목과 지급 내역을 확인해주세요.')
    if inp.wage_claim_amount_basis!='gross':raise ValueError('의무액과 지급액을 같은 세전 기준으로 확인해주세요. 통장 세후 입금액을 바로 차감하지 않습니다.')
    asof=strict_date(inp.wage_claim_calc_date or resolve_reference_date(inp.reference_date,inp.reference_year),'잔액 기준일')
    raw=inp.wage_claim_items
    if not isinstance(raw,list) or not 1<=len(raw)<=100:raise ValueError('월별 지급 의무액·기지급액·지급기일의 항목 명세가 필요합니다.')
    r=WageClaimsResult(calc_date=asof.isoformat(),legal_basis=['근로기준법 제43조 (임금 지급)',
        '민법 제476조~제479조 (변제충당)','최저임금법 제6조 (최저임금의 효력)'])
    prepared={};covered=set();derived=set()
    for row in raw:
        if not isinstance(row,dict):raise ValueError('급여 항목 명세를 확인해주세요.')
        ident=_text(row.get('id'),'항목 ID');name=_text(row.get('name'),'항목 이름');month=_month(row.get('month'))
        if ident in prepared:raise ValueError('급여 항목 ID가 중복됩니다.')
        due=strict_date(row.get('due_date'),'지급기일')
        components=row.get('components')
        if not isinstance(components,list) or not components or len(components)>50:raise ValueError('항목 간 포함·중복 관계를 확인해주세요.')
        for c in components:
            if not isinstance(c,str) or not (c in COMPONENTS or re.fullmatch(r'(?:bonus|other):[^\s:]{1,80}',c)):
                raise ValueError('임금 요소의 식별자를 확인해주세요.')
        if len(set(components))!=len(components):raise ValueError('같은 항목의 임금 요소가 중복됩니다.')
        amount,automatic,estimate=_amount(row,inp,ow)
        elements=set(components)|automatic
        scope={(month,c) for c in elements}
        if scope&covered:raise ValueError('같은 월의 임금 요소가 중복됩니다. 포함된 수당·최저임금 차액을 다시 청구하지 않도록 항목 관계를 확인해주세요.')
        covered|=scope
        source=row.get('source','explicit')
        if source!='explicit':
            key=(month,source,row.get('source_item_id') if source=='prorated' else None)
            if key in derived:raise ValueError('동일한 계산 결과를 두 항목에 중복 사용했습니다.')
            derived.add(key)
        r.is_estimate |= estimate
        prepared[ident]=dict(id=ident,name=name,month=month,due_date=due.isoformat(),components=sorted(elements),
            source=source,original_obligation=amount,adjustment=0,obligation=amount,raw=row,payments=[])
    adjustments=inp.wage_claim_adjustments or []
    if not isinstance(adjustments,list) or len(adjustments)>100:raise ValueError('의무액 정정 목록을 확인해주세요.')
    ids=set()
    for adj in adjustments:
        if not isinstance(adj,dict) or adj.get('confirmed') is not True:raise ValueError('의무액 정정의 사유·금액이 확인되어야 합니다.')
        aid=_text(adj.get('id'),'정정 ID');_text(adj.get('reason'),'정정 사유')
        if aid in ids or adj.get('item_id') not in prepared:raise ValueError('정정 ID 중복 또는 정정 대상 항목을 확인해주세요.')
        ids.add(aid);v=adj.get('amount')
        if isinstance(v,bool) or not isinstance(v,(float,int)):raise ValueError('정정액을 확인해주세요.')
        delta=_won(money(abs(v),'정정액'))*(-1 if v<0 else 1)
        prepared[adj['item_id']]['adjustment']+=delta
    payments=inp.wage_claim_payments or []
    if not isinstance(payments,list) or len(payments)>500:raise ValueError('기지급 목록을 확인해주세요.')
    ids=set();allocated=set()
    for payment in payments:
        if not isinstance(payment,dict) or payment.get('allocation_confirmed') is not True:
            raise ValueError('지급액의 항목별 원금·이자·비용 충당 내역을 확인해주세요. 임의 배분하지 않습니다.')
        pid=_text(payment.get('id'),'지급 ID')
        if pid in ids:raise ValueError('지급 ID가 중복됩니다.')
        ids.add(pid);d=strict_date(payment.get('date'),'실제 지급일')
        if d>asof:raise ValueError('기준일 이후 지급은 실제 잔액에 반영하지 않습니다.')
        total=_won(money(payment.get('amount'),'실제 지급 총액'))
        parts=payment.get('allocations')
        if not isinstance(parts,list) or not 1<=len(parts)<=100:raise ValueError('지급액의 항목별 배분 내역을 확인해주세요.')
        summed=0;seen=set()
        for part in parts:
            if not isinstance(part,dict) or part.get('item_id') not in prepared:raise ValueError('지급액이 귀속되는 항목을 확인해주세요.')
            ident=part['item_id']
            if ident in seen:raise ValueError('한 지급 내역의 동일 항목 배분이 중복됩니다.')
            seen.add(ident);allocated.add(ident)
            principal=_won(money(part.get('principal_amount'),'원금 충당액'))
            interest=None if part.get('interest_amount') is None else _won(money(part['interest_amount'],'이자 충당액'))
            cost=_won(money(part.get('cost_amount',0),'비용 충당액'))
            summed+=principal+(interest or 0)+cost
            prepared[ident]['payments'].append(dict(date=d.isoformat(),principal_amount=principal,
                interest_amount=interest,allocation_confirmed=True))
        if summed!=total:raise ValueError('지급 총액과 항목별 원금·이자·비용 배분 합계가 다릅니다.')
    interest_holds=[]
    for ident,x in prepared.items():
        row=x.pop('raw');x['obligation']+=x['adjustment']
        if x['obligation']<0:raise ValueError('정정 후 지급 의무액이 음수입니다.')
        summary=None if row.get('paid_amount') is None else _won(money(row['paid_amount'],'기지급 원금'))
        if ident in allocated:
            paid=sum(p['principal_amount'] for p in x['payments'])
            if summary is not None and summary!=paid:raise ValueError('기지급 원금 요약과 실제 배분 내역이 다릅니다.')
        else:
            if summary is None:raise ValueError('항목별 기지급 원금 또는 미지급 0원 확인이 필요합니다.')
            paid=summary
            paid_date=row.get('paid_date')
            interest=None if row.get('paid_interest_amount') is None else _won(money(row['paid_interest_amount'],'지급 이자'))
            if paid_date is not None:
                d=strict_date(paid_date,'실제 지급일')
                if d>asof:raise ValueError('기준일 이후 지급은 실제 잔액에 반영하지 않습니다.')
                if paid or interest:x['payments'].append(dict(date=d.isoformat(),principal_amount=paid,interest_amount=interest,allocation_confirmed=True))
            elif paid or interest:interest_holds.append('실제 지급일이 없어 이자 기간을 계산할 수 없습니다.')
        x.update(paid_principal=paid,remaining=max(0,x['obligation']-paid),overpayment=max(0,paid-x['obligation']),
                 overdue=strict_date(x['due_date'],'지급기일')<asof)
        r.items.append(x)
        r.total_obligation+=x['obligation'];r.total_paid+=paid;r.remaining_principal+=x['remaining'];r.overpayment+=x['overpayment']
        if x['overdue']:r.overdue_principal+=x['remaining']
        else:r.not_yet_due+=x['remaining']
        # 초과 지급은 별도 표시하고, 해당 채권의 소멸액까지만 C2에 전달한다.
        left=x['obligation'];history=[]
        for p in sorted(x['payments'],key=lambda p:p['date']):
            amount=min(left,p['principal_amount']);left-=amount
            if amount or p['interest_amount']:
                history.append(dict(p,principal_amount=amount))
            elif p['interest_amount'] is None:interest_holds.append('초과 지급 중 이자 충당액을 확인해주세요.')
        if x['obligation'] and x['overdue']:
            kind='retirement_lump_sum' if 'retirement' in x['components'] else 'regular_wage'
            r.interest_claims.append(dict(id=ident,amount=x['obligation'],due_date=x['due_date'],claim_kind=kind,payments=history,
                                         exclusions=row.get('exclusions')))
        r.formulas.append(f"{x['month']} {x['name']}: 의무액 {x['obligation']:,.0f}원 − 기지급 원금 {paid:,.0f}원 = 미지급 {x['remaining']:,.0f}원"+
                          (f" (초과 지급 {x['overpayment']:,.0f}원 별도)" if x['overpayment'] else ''))
    if r.is_estimate:interest_holds.append('월 평균 추정 의무액은 확정 채권이 아닙니다. 실제 월별 의무액을 확인해야 이자를 계산할 수 있습니다.')
    r.interest_held_reason=' '.join(dict.fromkeys(interest_holds))
    r.breakdown={'월별·항목별 원금 명세':r.items,'잔액 기준일':r.calc_date}
    r.warnings=['명시한 정산 범위의 세전 금액입니다. 목록에 없는 퇴직급여·연차수당·공제를 자동 합산하지 않습니다.',
                '초과 지급은 다른 항목의 체불과 자동 상계하지 않습니다. 지급 의무와 변제충당이 확인된 사실을 전제로 합니다.']
    if r.is_estimate:r.warnings.append('월 평균 조건으로 산출한 추정 원금이 포함되어 있습니다. 실제 월별 채권으로 확정하지 마세요.')
    if r.not_yet_due:r.warnings.append('지급기일 당일 또는 아직 기일이 지나지 않은 금액은 체불 원금·이자 청구 합계와 구분합니다.')
    return r

def calc_wage_claims(inp,ow):
    try:return _calculate(inp,ow)
    except (ValueError,TypeError,OverflowError) as exc:return WageClaimsResult(held_reason=str(exc))


def calc_claim_interest(inp,claims_result):
    """C2에 원금 산정 결과의 원래 채권과 변제 이력을 전달한다."""
    from .wage_arrears import calc_wage_arrears,WageArrearsResult
    if claims_result is None:return WageArrearsResult(held_reason='원금 명세가 보류되어 연결할 이자 채권을 확정할 수 없습니다.')
    if claims_result.interest_held_reason:return WageArrearsResult(held_reason=claims_result.interest_held_reason)
    if inp.arrear_amount or inp.arrear_due_date or inp.arrear_claims or inp.arrear_payments:
        return WageArrearsResult(held_reason='산정한 임금 채권과 별도 확정 체불 입력이 함께 있습니다. 같은 채권의 중복 여부를 확인해주세요.')
    if inp.arrear_calc_date and inp.arrear_calc_date!=claims_result.calc_date:
        return WageArrearsResult(held_reason='원금 잔액 기준일과 이자 기준일이 다릅니다.')
    if not claims_result.interest_claims:
        return WageArrearsResult(arrear_amount=0,interest_amount=0,remaining_interest=0,total_claim=0,
            calc_date=claims_result.calc_date,warnings=['기준일에 지급기일이 지난 양수 채권이 없어 지연이자 청구액은 0원입니다.'])
    return calc_wage_arrears(claims=claims_result.interest_claims,arrear_calc_date=claims_result.calc_date,
        is_post_retirement_arrear=inp.is_post_retirement_arrear,
        retirement_effective_date=inp.arrear_retirement_effective_date or inp.proration_retirement_effective_date,
        last_employed_date=inp.arrear_last_employed_date or inp.last_employed_date,
        debtor_is_merchant=inp.debtor_is_merchant,deadline_holidays=inp.arrear_deadline_holidays,
        is_employee=not inp.is_platform_worker)
