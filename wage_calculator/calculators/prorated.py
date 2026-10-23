"""Contract-based pay for an explicit settlement month (C6)."""
import calendar
import re
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from ..base import BaseCalculatorResult
from ..models import WageInput, WageType
from .ordinary_wage import OrdinaryWageResult
from .pay_inputs import money, strict_date
from .shared import monthly_wage_total, normalize_allowances

PRORATION_INPUT_FIELDS = {
    'settlement_month','proration_method','join_date','last_employed_date',
    'proration_retirement_effective_date','proration_employed_at_month_start',
    'proration_unpaid_periods','proration_scheduled_dates',
    'proration_all_items_proportional','proration_items','proration_items_complete',
}
SOURCE='https://1350.moel.go.kr/rtmview.do?id=1000059852'

@dataclass
class ProratedResult(BaseCalculatorResult):
    prorated_wage: float = 0.0
    method: str = ''
    worked_days: int = 0
    total_days: int = 0
    settlement_month: str = ''
    included_dates: list = field(default_factory=list)
    excluded_dates: list = field(default_factory=list)
    item_rows: list = field(default_factory=list)

def _dates(start, end):
    return {start+timedelta(days=n) for n in range(max(0,(end-start).days+1))}

def _contract_items(inp, ow):
    if inp.proration_all_items_proportional is True:
        if inp.monthly_total_pay is None and inp.monthly_wage is None:
            raise ValueError('일할 약정의 실제 월 계약 금액을 확인해주세요.')
        for amount in (inp.monthly_total_pay,inp.monthly_wage):
            if amount is not None:money(amount,'월 계약 금액')
        if any(a.annual or a.payment_cycle!='매월' for a in normalize_allowances(inp.fixed_allowances)):
            raise ValueError('연·분기·반기 수당은 월 환산액을 청구하지 않습니다. 이 달 지급 항목과 조건을 확인해주세요.')
        if not inp.monthly_total_pay and any((inp.schedule.weekly_overtime_hours,
                inp.schedule.weekly_night_hours,inp.schedule.weekly_holiday_hours)):
            raise ValueError('실근로수당이 있으면 확정 월 계약 총액 또는 항목별 지급 조건을 확인해주세요.')
        if inp.monthly_total_pay is not None:
            contract=inp.monthly_total_pay
        elif inp.wage_composition_known or inp.wage_type==WageType.COMPREHENSIVE:
            contract=inp.monthly_wage
        else:
            contract=inp.monthly_wage+sum(a.monthly_amount for a in normalize_allowances(inp.fixed_allowances))
        # Ordinary-wage classification must not remove contractually payable items.
        amount=monthly_wage_total(replace(inp,monthly_total_pay=contract),ow,premium=False) if contract else 0
        if inp.proration_items:
            items=inp.proration_items
            # 분석기가 같은 월급을 단일 항목으로 재기록한 경우만 같은 계약으로 취급한다.
            same=(isinstance(items,list) and len(items)==1 and isinstance(items[0],dict)
                  and items[0].get('policy')=='prorate' and items[0].get('payment_cycle')=='매월'
                  and isinstance(items[0].get('id'),str) and bool(items[0]['id'].strip())
                  and isinstance(items[0].get('name'),str) and bool(items[0]['name'].strip())
                  and money(items[0].get('amount'),'계약 지급액')==amount)
            if not same:
                raise ValueError('전체 월액과 항목별 지급 조건이 다릅니다. 정산 대상 금액과 조건을 확인해주세요.')
        elif inp.proration_items is not None and inp.proration_items != []:
            raise ValueError('급여 항목 목록을 확인해주세요.')
        return [dict(id='monthly_contract',name='전체 월 계약 임금',
                     amount=amount,payment_cycle='매월',policy='prorate')]
    items=inp.proration_items
    if inp.proration_items_complete is not True or not isinstance(items,list) or not 1<=len(items)<=50:
        raise ValueError('전체 월액 일할 약정 또는 정산 대상 전체 항목의 지급 조건을 확인해주세요.')
    return items

def _calculate(inp, ow):
    month=inp.settlement_month
    if not isinstance(month,str) or not re.fullmatch(r'\d{4}-\d{2}',month):
        raise ValueError('중도입사·중도퇴사·휴복직 정산 대상월(YYYY-MM)을 확인해주세요.')
    first=strict_date(month+'-01','정산 대상월')
    last=date(first.year,first.month,calendar.monthrange(first.year,first.month)[1])
    all_dates=_dates(first,last)
    method=inp.proration_method
    if method not in ('calendar','scheduled'):
        raise ValueError('약정한 일할계산 방식(달력일수 또는 소정근로일·유급 처리일)을 확인해주세요.')
    hire=None
    for raw in (inp.join_date,inp.start_date):
        if raw is not None:
            parsed=strict_date(raw,'입사일')
            if hire and hire!=parsed:raise ValueError('입사일 입력이 서로 다릅니다.')
            hire=parsed
    if hire is None:
        if inp.proration_employed_at_month_start is not True:
            raise ValueError('실제 입사일 또는 정산월 월초부터 재직했는지 확인해주세요.')
        hire=first
    end=None
    if inp.last_employed_date is not None:end=strict_date(inp.last_employed_date,'마지막 재직일')
    if inp.proration_retirement_effective_date is not None:
        effective=strict_date(inp.proration_retirement_effective_date,'퇴직 효력일')
        if effective<=hire:raise ValueError('퇴직 효력일은 입사일 다음 날 이후여야 합니다.')
        final=effective-timedelta(days=1)
        if end and end!=final:raise ValueError('마지막 재직일과 퇴직 효력일은 하루 차이여야 합니다.')
        end=final
    if inp.end_date is not None and end is None:
        raise ValueError('퇴사 날짜가 마지막 재직일인지 퇴직 효력일인지 확인해주세요.')
    if end and end<hire:raise ValueError('마지막 재직일이 입사일보다 빠릅니다.')
    employed={d for d in all_dates if d>=hire and (end is None or d<=end)}
    unpaid=set()
    periods=inp.proration_unpaid_periods
    if periods is not None:
        if not isinstance(periods,list) or len(periods)>100:raise ValueError('확정 무급 기간 목록을 확인해주세요.')
        for period in periods:
            if not isinstance(period,dict) or period.get('confirmed') is not True:
                raise ValueError('휴직·결근의 무급 처리 여부를 확인해주세요. 주휴일을 자동 공제하지 않습니다.')
            a=strict_date(period.get('start'),'무급 시작일');b=strict_date(period.get('end'),'무급 종료일')
            if b<a:raise ValueError('무급 종료일이 시작일보다 빠릅니다.')
            if not isinstance(period.get('reason'),str) or not period['reason'].strip():
                raise ValueError('확정 무급 기간의 사유를 확인해주세요.')
            unpaid|=_dates(max(a,first),min(b,last))
    denominator=all_dates
    if method=='scheduled':
        supplied=inp.proration_scheduled_dates
        if not isinstance(supplied,list) or not 1<=len(supplied)<=31:
            raise ValueError('해당 월 전체의 소정근로일·유급 처리일 목록을 확인해주세요.')
        denominator={strict_date(d,'소정근로일·유급 처리일') for d in supplied}
        if len(denominator)!=len(supplied) or not denominator<=all_dates:
            raise ValueError('소정근로일·유급 처리일의 중복 또는 다른 월 날짜를 확인해주세요.')
    included=denominator & employed - unpaid
    worked,total=len(included),len(denominator)
    if inp.first_month_worked_days is not None and inp.first_month_worked_days!=worked:
        raise ValueError('기존 근무일수와 실제 재직·무급 날짜가 다릅니다.')
    rows=[];ids=set();formulas=[]
    for raw in _contract_items(inp,ow):
        if not isinstance(raw,dict):raise ValueError('급여 항목별 지급 조건을 확인해주세요.')
        ident=raw.get('id');name=raw.get('name');policy=raw.get('policy')
        if not isinstance(ident,str) or not ident.strip() or ident in ids:
            raise ValueError('급여 항목 식별자가 없거나 중복됩니다.')
        ids.add(ident)
        if not isinstance(name,str) or not name.strip():raise ValueError('급여 항목 이름을 확인해주세요.')
        if policy=='actual':
            basis=money(raw.get('actual_amount'),'확정된 실제 지급액')
            value=basis;formula=f'{name}: 별도 확정 실근로 금액 {basis:,.0f}원'
        elif policy in ('prorate','full'):
            basis=money(raw.get('amount'),'계약 지급액')
            cycle=raw.get('payment_cycle')
            if cycle not in ('매월','분기','반기','연') or policy=='prorate' and cycle!='매월':
                raise ValueError('비례 항목은 실제 월 계약 금액이 필요합니다. 연 상여의 월 환산액은 사용할 수 없습니다.')
            value=Decimal(str(basis))*worked/total if policy=='prorate' else basis
            formula=(f'{name}: {basis:,.0f}원 × {worked}/{total}' if policy=='prorate'
                     else f'{name}: 이 달 전액 지급 약정 {basis:,.0f}원')
        else:raise ValueError('항목별 비례·전액·실제 지급 정책을 확인해주세요.')
        payable=int(Decimal(str(value)).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
        rows.append(dict(id=ident,name=name,policy=policy,contract_amount=basis,
                         payable_amount=payable,settlement_month=month))
        formulas.append(f'{formula} = {payable:,.0f}원')
    amount=sum(row['payable_amount'] for row in rows)
    included_text=[d.isoformat() for d in sorted(included)]
    excluded_text=[d.isoformat() for d in sorted(denominator & employed & unpaid)]
    label='달력일수 약정' if method=='calendar' else '소정근로일·유급 처리일 약정'
    return ProratedResult(prorated_wage=amount,method=label,worked_days=worked,total_days=total,
        settlement_month=month,included_dates=included_text,excluded_dates=excluded_text,item_rows=rows,
        formulas=formulas,breakdown={'정산 대상월':month,'약정 방식':label,'일할 비율':f'{worked}/{total}',
        '포함 날짜':', '.join(included_text) or '없음','확정 무급 제외 날짜':', '.join(excluded_text) or '없음',
        '마지막 재직일':end.isoformat() if end else '재직 중'},
        warnings=['약정한 지급 조건에 따른 세전 월 임금입니다. 주휴일 추가 공제·최저임금·퇴직급여·연차수당·보험료는 별도 확인합니다.'],
        legal_basis=['근로기준법 제43조 (임금 지급)','고용노동부: 일할 방법은 계약·취업규칙 확인',SOURCE])

def calc_prorated(inp: WageInput, ow: OrdinaryWageResult) -> ProratedResult:
    try:return _calculate(inp,ow)
    except (ValueError,OverflowError) as exc:
        return ProratedResult(held_reason=str(exc),warnings=[str(exc)])
