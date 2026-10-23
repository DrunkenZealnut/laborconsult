"""확정 체불 원금의 채권별 단리. 지급사유·변제·제외 기간을 구분한다."""
import calendar
import math
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..base import BaseCalculatorResult
from ..effective_rules import ARREARS_RULES
from ..legal_rules import resolve_reference_date

ARREARS_INPUT_FIELDS = frozenset({
    'arrear_amount','arrear_due_date','arrear_calc_date','is_post_retirement_arrear',
    'arrear_claim_kind','arrear_retirement_effective_date','arrear_last_employed_date',
    'debtor_is_merchant','arrear_payments','arrear_exclusions','arrear_claims','arrear_deadline_holidays',
})
EXCLUSION_REASONS = frozenset({'natural_disaster','insolvency','statutory_funding_constraint',
                               'reasonable_legal_dispute','equivalent'})
DAY = timedelta(days=1)


@dataclass
class WageArrearsResult(BaseCalculatorResult):
    arrear_amount: float = 0.0  # 계산일의 남은 원금
    original_principal: float = 0.0
    principal_paid: float = 0.0
    interest_rate: float | None = None
    delay_days: int = 0
    interest_amount: float | None = None
    interest_paid: float | None = 0.0
    remaining_interest: float | None = None
    total_claim: float | None = None
    due_date: str = ''
    calc_date: str = ''
    statute_of_limitations_date: str = ''  # 단순 3년 도달일, 권리 소멸 확정 아님
    is_expired: bool = False              # 단순 도달 여부만 유지하는 호환 필드
    is_post_retirement: bool = False
    interest_schedule: list = field(default_factory=list)
    conditional_scenarios: list = field(default_factory=list)
    claims: list = field(default_factory=list)


def _date(value, label):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):
        raise ValueError(f'{label} 날짜(YYYY-MM-DD)를 확인해주세요')
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f'{label} 날짜(YYYY-MM-DD)를 확인해주세요') from None


def _money(value, label, *, positive=False):
    if isinstance(value,bool):
        raise ValueError(f'{label} 숫자를 확인해주세요')
    try:
        n=float(value)
    except (ValueError,TypeError):
        raise ValueError(f'{label} 숫자를 확인해주세요') from None
    if not math.isfinite(n) or not (0 < n <= 1e12 if positive else 0 <= n <= 1e12):
        raise ValueError(f'{label} 범위를 확인해주세요')
    return n


def _rule(cause):
    for rule in ARREARS_RULES:
        if rule.effective_from<=cause and (rule.effective_to is None or cause<rule.effective_to):
            return rule
    raise ValueError('2005-07-01 전 지급사유는 당시 적용 규칙 확인이 필요합니다')


def _three_year_date(start):
    return date(start.year+3,start.month,min(start.day,calendar.monthrange(start.year+3,start.month)[1]))


def _retirement(effective, last_day, retired, holidays, warnings):
    if not isinstance(retired,bool):
        raise ValueError('퇴직 여부를 확인해주세요')
    e=_date(effective,'퇴직 효력일') if effective is not None else None
    if last_day is not None:
        from_last=_date(last_day,'마지막 재직일')+DAY
        if e and e!=from_last:
            raise ValueError('마지막 재직일 다음 날과 퇴직 효력일이 서로 다릅니다')
        e=from_last
    if retired and e is None:
        raise ValueError('퇴직 여부만으로 14일 경과를 가정하지 않습니다. 퇴직 효력일 또는 마지막 재직일을 확인해주세요')
    if e is None:
        return None,None
    if holidays is not None and (not isinstance(holidays,list) or len(holidays)>366):
        raise ValueError('기간 말일 조정에 사용할 법정 공휴일 목록을 확인해주세요')
    days={_date(x,'법정 공휴일') for x in holidays or []}
    deadline=e+timedelta(days=13)  # 오전 0시 효력 발생: 민법 제157조 단서
    while deadline.weekday()>=5 or deadline in days:
        deadline+=DAY
    if holidays is None:
        warnings.append('퇴직 지급기한은 토·일요일만 조정한 조건부 날짜입니다. 말일의 법정·대체공휴일 여부를 확인해주세요')
    return e,deadline


def _prepare_claim(raw, fallback_id, calc, retirement, retirement_deadline, default_kind):
    if not isinstance(raw,dict):
        raise ValueError('채권별 원금·지급기일 자료를 확인해주세요')
    cid=raw.get('id',fallback_id)
    if not isinstance(cid,str) or not cid.strip() or len(cid)>100:
        raise ValueError('채권 ID를 확인해주세요')
    kind=raw.get('claim_kind',default_kind)
    if kind not in ('regular_wage','retirement_lump_sum'):
        raise ValueError('정기지급 임금과 퇴직급여 일시금을 구분해주세요. 판결·약정·DC 부담금 이율은 별도 검토가 필요합니다')
    if kind=='retirement_lump_sum' and retirement is None:
        raise ValueError('퇴직급여 일시금은 퇴직 효력일 또는 마지막 재직일이 필요합니다')
    amount=_money(raw.get('amount'),'채권 원금',positive=True)
    due=(_date(raw['due_date'],'원래 지급기일') if raw.get('due_date') not in (None,'')
         else retirement_deadline if kind=='retirement_lump_sum' else None)
    if due is None:
        raise ValueError('정기지급 임금의 원래 지급기일을 확인해주세요')
    if kind=='retirement_lump_sum' and due<retirement:
        raise ValueError('퇴직급여 일시금의 지급기일이 퇴직 효력일보다 빠릅니다. 중간정산은 별도 확인이 필요합니다')
    rule=_rule(due+DAY)
    special=due+DAY if kind=='regular_wage' and rule.values['regular_rate'] is not None else None
    if retirement_deadline:
        special=min(special,retirement_deadline+DAY) if special else retirement_deadline+DAY
    start=min(due+DAY,special) if special else due+DAY
    payments=[] if raw.get('payments') is None else raw['payments']
    exclusions=[] if raw.get('exclusions') is None else raw['exclusions']
    if not isinstance(payments,list) or len(payments)>500:
        raise ValueError('채권별 원금 변제 목록을 확인해주세요')
    if not isinstance(exclusions,list) or len(exclusions)>100:
        raise ValueError('채권별 지연이자 적용 제외 구간을 확인해주세요')
    by_day={};interest_paid=0.0;interest_paid_known=True
    for p in payments:
        if not isinstance(p,dict) or p.get('allocation_confirmed') is not True:
            raise ValueError('부분 지급의 채권별 원금 충당액이 확인되어야 합니다. 비용·이자·원본의 변제충당 내역을 확인해주세요')
        d=_date(p.get('date'),'원금 변제일')
        if d>calc:
            raise ValueError('계산일 이후 변제는 실제 원금 잔액에 반영할 수 없습니다')
        principal_part=_money(p.get('principal_amount'),'원금 충당액')
        interest_part=None if p.get('interest_amount') is None else _money(p['interest_amount'],'지급 이자 충당액')
        if principal_part==0 and not interest_part:
            raise ValueError('지급한 원금 또는 이자 충당액을 확인해주세요')
        by_day[d]=by_day.get(d,0)+principal_part
        if interest_part is None:
            interest_paid_known=False
        else:
            interest_paid+=interest_part
    if sum(by_day.values())>amount:
        raise ValueError('확정된 원금 변제액이 해당 채권 원금을 초과합니다')
    excluded=[]
    for x in exclusions:
        if not isinstance(x,dict) or x.get('eligible') is not True or x.get('reason') not in EXCLUSION_REASONS:
            raise ValueError('제37조·시행령 제18조 적용 제외의 법정 사유와 해당 여부를 확인해주세요')
        a=_date(x.get('start_date'),'제외 시작일');b=_date(x.get('end_date'),'제외 종료일')
        if b<a:
            raise ValueError('적용 제외 시작·종료일 순서를 확인해주세요')
        excluded.append((a,b,x['reason']))
    sol=_three_year_date(retirement if kind=='retirement_lump_sum' else due)
    return dict(id=cid,kind=kind,amount=amount,due=due,start=start,special=special,rule=rule,
                payments=by_day,interest_paid=interest_paid,interest_paid_known=interest_paid_known,
                exclusions=excluded,sol=sol)


def _calculate(claim, calc, merchant):
    start=claim['start'];stop=calc+DAY
    if start>=stop:
        return []
    boundaries={start,stop}
    if claim['special'] and start<claim['special']<stop:
        boundaries.add(claim['special'])
    for d in claim['payments']:
        if start<d+DAY<stop:
            boundaries.add(d+DAY)
    for a,b,_ in claim['exclusions']:
        boundaries.update(d for d in (a,b+DAY) if start<d<stop)
    points=sorted(boundaries);rows=[]
    for a,b in zip(points,points[1:]):
        principal=claim['amount']-sum(v for d,v in claim['payments'].items() if d<a)
        if principal<=0:
            continue
        reasons=sorted({reason for x,y,reason in claim['exclusions'] if x<=a<=y})
        statutory=claim['special'] is not None and a>=claim['special'] and not reasons
        values=claim['rule'].values
        statutory_rate=values['regular_rate'] if claim['kind']=='regular_wage' and values['regular_rate'] is not None else values['retirement_rate']
        rate=statutory_rate if statutory else values['commercial_rate' if merchant else 'civil_rate']
        days=(b-a).days
        rows.append(dict(claim_id=claim['id'],start_date=a.isoformat(),end_date=(b-DAY).isoformat(),
                         principal=principal,days=days,rate=rate,interest=principal*rate*days/365,
                         basis='근로기준법 제37조' if statutory else '상법 제54조' if merchant else '민법 제379·397조',
                         rule_id=claim['rule'].rule_id,excluded_reasons=reasons))
    return rows


def calc_wage_arrears(arrear_amount=0, arrear_due_date='', is_post_retirement_arrear=False,
                     arrear_calc_date=None, *, claim_kind='regular_wage',
                     retirement_effective_date=None, last_employed_date=None,
                     debtor_is_merchant=None, payments=None, exclusions=None, claims=None,
                     deadline_holidays=None, reference_date=None, reference_year=None, is_employee=True):
    r=WageArrearsResult(legal_basis=['근로기준법 제37조·제49조',
        '근로기준법 시행령 제17조·제18조','상법 제54조','민법 제379조·제397조·제479조',
        '내장 시행일 규칙: 법률 제20520호 부칙 제2조 (관리자 승인 키와 별도)'])
    try:
        if is_employee is not True:
            raise ValueError('근로기준법상 근로자 여부를 확인해야 합니다. 비근로자 용역대금에 임금 지연이자 20%를 적용하지 않습니다')
        if debtor_is_merchant is not None and not isinstance(debtor_is_merchant,bool):
            raise ValueError('채무자의 상인 여부는 확인된 사실 또는 미확인으로 구분해주세요')
        calc=_date(arrear_calc_date if arrear_calc_date is not None else
                   resolve_reference_date(reference_date,reference_year),'계산 기준일')
        retirement,deadline=_retirement(retirement_effective_date,last_employed_date,
                                        is_post_retirement_arrear,deadline_holidays,r.warnings)
        if claims is None:
            raw=[dict(id='1',amount=arrear_amount,due_date=arrear_due_date,claim_kind=claim_kind,
                      payments=payments,exclusions=exclusions)]
        else:
            if not isinstance(claims,list) or not 1<=len(claims)<=100:
                raise ValueError('1~100건의 채권 목록을 확인해주세요')
            if arrear_amount or arrear_due_date or payments or exclusions:
                raise ValueError('단일 채권과 채권 목록을 중복 입력하지 마세요')
            raw=claims
        prepared=[_prepare_claim(x,str(i+1),calc,retirement,deadline,claim_kind) for i,x in enumerate(raw)]
        if len({x['id'] for x in prepared})!=len(prepared):
            raise ValueError('채권 ID가 중복됩니다')
        scenarios=[]
        for merchant in ([False,True] if debtor_is_merchant is None else [debtor_is_merchant]):
            rows=[]
            for c in prepared:
                claim_rows=_calculate(c,calc,merchant)
                if c['interest_paid']>round(sum(row['interest'] for row in claim_rows)):
                    raise ValueError(f"채권 {c['id']}의 지급 이자가 해당 조건의 누적 발생 이자를 초과합니다. 이율·변제충당 내역을 확인해주세요")
                rows.extend(claim_rows)
            total=round(sum(x['interest'] for x in rows))
            scenarios.append(dict(debtor_is_merchant=merchant,interest_amount=total,interest_schedule=rows))
        r.original_principal=sum(x['amount'] for x in prepared)
        r.principal_paid=sum(sum(x['payments'].values()) for x in prepared)
        r.arrear_amount=r.original_principal-r.principal_paid
        r.interest_paid=sum(x['interest_paid'] for x in prepared) if all(x['interest_paid_known'] for x in prepared) else None
        for scenario in scenarios:
            accrued=sum(row['interest'] for row in scenario['interest_schedule'])
            if r.interest_paid is not None and r.interest_paid>scenario['interest_amount']:
                raise ValueError('지급 이자가 해당 조건의 누적 발생 이자를 초과합니다. 이율·변제충당·다른 채권 포함 여부를 확인해주세요')
            remaining=None if r.interest_paid is None else max(0,round(accrued-r.interest_paid))
            scenario.update(remaining_interest=remaining,
                            total_claim=None if remaining is None else round(r.arrear_amount+remaining))
        if len(scenarios)==2 and scenarios[0]['interest_schedule']!=scenarios[1]['interest_schedule']:
            r.conditional_scenarios=scenarios
            r.warnings.append('채무자의 상인 여부 미확인: 민사 5%와 상사 6%의 조건별 결과입니다. 어느 하나를 확정 금액으로 선택하지 마세요')
        else:
            chosen=scenarios[0];r.interest_schedule=chosen['interest_schedule']
            r.interest_amount=chosen['interest_amount'];r.total_claim=chosen['total_claim']
            r.remaining_interest=chosen['remaining_interest']
            rates={x['rate'] for x in r.interest_schedule}
            r.interest_rate=next(iter(rates)) if len(rates)==1 else None
        r.delay_days=sum(x['days'] for x in scenarios[0]['interest_schedule'])
        r.calc_date=calc.isoformat();r.is_post_retirement=retirement is not None
        for c in prepared:
            r.claims.append(dict(id=c['id'],claim_kind=c['kind'],original_principal=c['amount'],
                principal_paid=sum(c['payments'].values()),remaining_principal=c['amount']-sum(c['payments'].values()),
                interest_paid=c['interest_paid'] if c['interest_paid_known'] else None,
                due_date=c['due'].isoformat(),statute_review_date=c['sol'].isoformat(),three_year_date_passed=calc>c['sol']))
            if c['kind']=='regular_wage' and c['rule'].values['regular_rate'] is None:
                r.warnings.append(f"채권 {c['id']}: 지급기일 다음 날 {(c['due']+DAY).isoformat()}의 지급사유는 법률 제20520호 부칙 제2조상 개정 적용 대상이 아닙니다. 2025-10-23을 지났다는 이유로 재직 중 이율을 20%로 바꾸지 않습니다. 퇴직 지급기한 경과분은 별도 구간으로 판단했습니다")
        if len(prepared)==1:
            r.due_date=prepared[0]['due'].isoformat()
            r.statute_of_limitations_date=prepared[0]['sol'].isoformat()
            r.is_expired=calc>prepared[0]['sol']
        r.breakdown={'채권별 원금':r.claims,'남은 원금':f'{r.arrear_amount:,.0f}원','계산기준일':r.calc_date}
        if r.conditional_scenarios:
            r.breakdown['상인 여부에 따른 조건별 결과']=r.conditional_scenarios
        else:
            r.breakdown.update({'기간별 이자':r.interest_schedule,'누적 지연이자':f'{r.interest_amount:,.0f}원'})
            if r.total_claim is not None:
                r.breakdown.update({'이미 지급한 이자':f'{r.interest_paid:,.0f}원',
                                    '남은 이자':f'{r.remaining_interest:,.0f}원',
                                    '남은 원금과 이자 합계':f'{r.total_claim:,.0f}원'})
        if r.interest_paid is None:
            r.warnings.append('부분 지급 중 이자에 충당한 금액이 미확인되어 남은 이자·청구 합계는 보류합니다. 누적 발생 이자를 미지급 이자로 단정하지 마세요. 지급 이자가 없다고 확인되면 0원을 입력해주세요')
        for scenario in scenarios if r.conditional_scenarios else scenarios[:1]:
            prefix=('상사채무 조건' if scenario['debtor_is_merchant'] else '민사채무 조건') if r.conditional_scenarios else ''
            for row in scenario['interest_schedule']:
                r.formulas.append(f'{prefix} 채권 {row["claim_id"]} {row["start_date"]}~{row["end_date"]}: '
                    f'{row["principal"]:,.0f}원 × {row["rate"]:.0%} × {row["days"]}일 ÷ 365 = {row["interest"]:,.2f}원')
        r.warnings.append('원금·이자 변제충당과 적용 제외의 법적 자격이 확인된 사실을 전제로 한 단리 추정입니다. 이자는 지급한 날까지 계산합니다')
        if all(not c['exclusions'] for c in prepared):
            r.warnings.append('입력된 법정 제외 기간이 없어 제37조·시행령 제18조 적용 제외 사유가 없다는 조건으로 계산했습니다')
        r.warnings.append('채권별 단순 3년 도달일은 시효 검토용입니다. 중단·정지·승인·재판상 청구·공휴일 등을 반영하지 않아 권리 소멸을 확정하지 않습니다')
        if any(x['three_year_date_passed'] for x in r.claims):
            r.warnings.append('단순 3년 도달일이 지난 채권이 있습니다. 시효 중단·정지 등 실제 이력을 확인해주세요')
        r.warnings.append('지연이자 청구는 민사절차로 검토합니다. 임금체불 진정과 이자 지급 의무 위반의 형사처벌은 구분됩니다')
        return r
    except (ValueError,TypeError,OverflowError) as exc:
        return WageArrearsResult(held_reason=str(exc),legal_basis=r.legal_basis)
