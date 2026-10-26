"""월별 의무액·확인된 변제충당 명세. 법률상 채권 인정 여부를 추정하지 않는다."""
import re
from collections import defaultdict
from dataclasses import dataclass,field,replace
from decimal import Decimal,ROUND_HALF_UP

from ..base import BaseCalculatorResult
from ..models import WageType
from ..legal_rules import resolve_reference_date
from .pay_inputs import money,strict_date
from .shared import fixed_overtime_monthly,monthly_wage_total,normalize_allowances

CLAIM_INPUT_FIELDS=frozenset({'wage_claim_items','wage_claim_scope_complete','wage_claim_amount_basis',
    'wage_claim_calc_date','wage_claim_payments','wage_claim_adjustments','wage_claim_include_interest'})
CLAIM_DEPENDENCY_FIELDS=frozenset({'weekly_attendance_days'})
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
    due_unconfirmed: float=0.0   # 퇴직일을 몰라 지급기한을 정할 수 없는 미지급액(체불로도 미도래로도 단정하지 않는다)
    overpayment: float=0.0
    calc_date: str=''
    is_estimate: bool=False
    items: list=field(default_factory=list)
    interest_claims: list=field(default_factory=list)
    interest_held_reason: str=''
    statutory_allocations: list=field(default_factory=list)   # 지급기일 뒤 지급의 법정 충당(민법 제479조) 내역


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

def _contract_components(inp):
    # Aggregate sources include these actual contract components even if the caller omits them.
    from .shared import AllowanceClassifier
    result={'regular','weekly_holiday'}
    for allowance in normalize_allowances(inp.fixed_allowances):
        if not allowance.monthly_amount:continue
        if AllowanceClassifier.is_overtime_related(allowance.name):result.update({'overtime','night','holiday'})
        elif '연차' in allowance.name:result.add('annual_leave')
        else:
            ident=re.sub(r'[\s:]+','_',allowance.source_id or allowance.name)[:80]
            result.update({'other:'+ident,'bonus:'+ident})
    if inp.comprehensive_breakdown:
        if any(inp.comprehensive_breakdown.get(k,0) for k in ('overtime_pay','night_pay','holiday_pay')):
            result.update({'overtime','night','holiday'})
    return result


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
        components=_contract_components(inp) if found[0]['id']=='monthly_contract' else set()
        return found[0]['payable_amount'],components,False
    from .shared import ordinary_wage_from_total
    if source in {'ordinary_hours','overtime','night','holiday','weekly_holiday'} and ordinary_wage_from_total(inp):
        raise ValueError('수당이 섞인 월 총액을 통상임금으로 사용하지 않습니다. 기본급·통상임금 구성을 확인해주세요.')
    for attr in ('hourly_wage','daily_wage','monthly_wage','annual_wage','monthly_total_pay'):
        v=getattr(inp,attr)
        if v is not None:money(v,'계산 기초 임금')
    if inp.reference_year!=int(row['month'][:4]):raise ValueError('계산 기준 연도와 귀속월 연도를 일치시켜주세요.')
    wage_attr={WageType.HOURLY:'hourly_wage',WageType.DAILY:'daily_wage',WageType.MONTHLY:'monthly_wage',
               WageType.COMPREHENSIVE:'monthly_wage',WageType.ANNUAL:'annual_wage'}[inp.wage_type]
    base=getattr(inp,wage_attr)
    if base is None or money(base,'계산 기초 임금')<=0:
        raise ValueError('해당 월의 시급·기본급 등 계산 기초 임금액을 확인해주세요.')
    needs_schedule=inp.wage_type!=WageType.HOURLY or bool(inp.fixed_allowances) or source=='weekly_holiday'
    if needs_schedule and (inp.schedule.daily_work_hours<=0 or inp.schedule.weekly_work_days<=0):
        raise ValueError('통상시급·주휴 계산에 필요한 소정근로시간을 확인해주세요.')
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
        # 월급·연봉·포괄임금의 월 임금에는 유급 주휴분이 들어 있다(통상임금 월 기준시간에 주휴시간 포함 — weekly_holiday도
        # '월급에 주휴수당 포함'으로 안내한다). 별도 채권으로 만들면 같은 임금을 두 번 청구한다(Codex 리뷰 High 2: 월급 250만 원에
        # 주휴 383,560원이 따로 확정되고, 월급 행과 함께 넣으면 의무액 2,883,560원)
        if inp.wage_type in (WageType.MONTHLY,WageType.ANNUAL,WageType.COMPREHENSIVE):
            raise ValueError('월급·연봉제의 월 임금에는 유급 주휴분이 들어 있어 주휴수당을 별도 채권으로 만들지 않습니다. '
                             '월급에서 주휴분을 빼기로 약정했다면 그 약정과 금액을 확인해주세요.')
        from .weekly_holiday import calc_weekly_holiday
        weeks=row.get('weeks')
        if isinstance(weeks,bool) or not isinstance(weeks,int) or not 1<=weeks<=6:raise ValueError('동일 조건으로 확정된 주휴 대상 주 수를 확인해주세요.')
        attendance=inp.weekly_attendance_days
        if (isinstance(attendance,bool) or not isinstance(attendance,(int,float))
                or attendance!=inp.schedule.weekly_work_days or not 0<attendance<=7):
            raise ValueError('확정 주휴 대상 주의 개근 일수와 소정근로일수를 확인해주세요. 미개근 주를 전액 채권으로 만들지 않습니다.')
        result=calc_weekly_holiday(replace(inp,end_date=None),ow)
        if result.held_reason:raise ValueError(result.held_reason)
        return _won(result.weekly_holiday_pay*weeks),{'weekly_holiday'},False
    if any(a.annual or a.payment_cycle!='매월' for a in normalize_allowances(inp.fixed_allowances)):
        raise ValueError('연·분기 상여의 월 환산액을 채권으로 만들지 않습니다. 실제 지급월·금액·기일을 입력해주세요.')
    contract=monthly_wage_total(inp,ow,premium=source=='monthly_estimate')
    components=_contract_components(inp)
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
        if result.undetermined or result.shortage_undetermined or result.not_applicable:raise ValueError('최저임금 산입 범위·적용 조건이 미확인되어 의무액을 확정할 수 없습니다.')
        return _won(contract+result.shortage_monthly),components,False
    if inp.schedule.weekly_overtime_hours:components.add('overtime')
    if inp.schedule.weekly_night_hours:components.add('night')
    if inp.schedule.weekly_holiday_hours:components.add('holiday')
    return _won(contract),components,True

def _fixed_overtime_offsets(inp,ow,raw):
    """같은 달 월급 행에 든 고정연장수당 {귀속월: 월액}. 그 달의 파생 연장·야간·휴일 행에서 이 금액을 뺀다(A5).

    고정연장수당과 실제 연장·야간·휴일 근로 임금은 같은 근로의 대가라 큰 쪽만 센다 — facade의 월 총액과 같은 규칙이다.
    월급에 든 금액은 ① 고정연장수당(fixed_allowances) ② 파이프라인 구성 진술 경로의 '총액 − 통상임금 월액·비통상 고정수당'
    (고정연장수당 항목을 지우고 monthly_total_pay로 옮긴 경우)이다. 월급 행이 그 금액을 포함하는지 알 수 없으면(계약 총액과
    다르고 overtime 요소도 없음) 보류한다. 같은 달 연장 금액을 직접 적은 행은 _calculate가 보류한다."""
    premium={'overtime','night','holiday'}
    # 파생 연장·야간·휴일 행, 또는 연장 금액을 직접 적은 행(월급 행이 아닌 explicit 행)이 있는 달
    months={x.get('month') for x in raw if isinstance(x,dict) and (
        x.get('source') in premium or (x.get('source','explicit')=='explicit' and isinstance(x.get('components'),list)
                                      and 'regular' not in x['components'] and premium&set(x['components'])))}
    if not months:return {}
    fixed=fixed_overtime_monthly(inp)
    if inp.wage_composition_known and inp.monthly_total_pay:
        fixed+=max(0.0,inp.monthly_total_pay-(ow.monthly_ordinary_wage+ow.not_ordinary_fixed_total))
    fixed=_won(fixed)
    if fixed<=0:return {}
    contract=_won(inp.monthly_total_pay or monthly_wage_total(inp,ow,premium=False))
    out={}
    for x in raw:
        if not (isinstance(x,dict) and x.get('source','explicit')=='explicit' and x.get('month') in months
                and isinstance(x.get('components'),list) and 'regular' in x['components']):
            continue
        if 'overtime' in x['components'] or _won(money(x.get('amount'),'지급 의무액'))==contract:
            out[x['month']]=fixed
        else:
            raise ValueError(f'같은 달 월급 행에 고정연장수당 월 {fixed:,.0f}원이 들어 있는지 확인해주세요. 고정연장수당과 실제 '
                             '연장·야간·휴일 근로 임금은 같은 근로의 대가라 큰 쪽만 청구합니다.')
    return out


def _principal_first(inp,r,alternatives,note):
    """법정 충당 카드에 함께 싣는 원금 우선 값 문구 — 남은 원금과, 이자를 계산할 수 있으면 원금·이자 합계."""
    remaining=r.remaining_principal
    for x in r.items:
        if x['id'] in alternatives:
            remaining+=max(0,x['obligation']-alternatives[x['id']][0])-x['remaining']
    # 법정 충당은 요약 지급(행마다 지급 1건)에만 적용되므로, 그 행의 이자 채권 이력을 입력한 배분 1건으로 바꾼다
    dated={a['id']:a['date'] for a in r.statutory_allocations}
    claims=[c if c['id'] not in alternatives else dict(c,payments=[
        dict(date=dated[c['id']],principal_amount=alternatives[c['id']][0],interest_amount=alternatives[c['id']][1],
             allocation_confirmed=True)] if any(alternatives[c['id']]) else []) for c in r.interest_claims]
    total=None
    if not r.interest_held_reason:
        alt=calc_claim_interest(inp,replace(r,interest_claims=claims))
        total=None if alt.held_reason else alt.total_claim
    return note(remaining,total)


def _calculate(inp,ow):
    if inp.is_platform_worker:raise ValueError('임금 채권을 정산하려면 근로자성을 확인해주세요.')
    if inp.wage_claim_scope_complete is not True:raise ValueError('요청 정산 범위의 전체 항목과 지급 내역을 확인해주세요.')
    if inp.wage_claim_amount_basis!='gross':raise ValueError('의무액과 지급액을 같은 세전 기준으로 확인해주세요. 통장 세후 입금액을 바로 차감하지 않습니다.')
    asof=strict_date(inp.wage_claim_calc_date or resolve_reference_date(inp.reference_date,inp.reference_year),'잔액 기준일')
    raw=inp.wage_claim_items
    if not isinstance(raw,list) or not 1<=len(raw)<=100:raise ValueError('월별 지급 의무액·기지급액·지급기일의 항목 명세가 필요합니다.')
    # 근거 조문은 해당하는 행이 있을 때만 붙인다 — 약정 임금 미지급만 정산한 카드에 최저임금법 제6조(미달분을 임금 채권으로
    # 만드는 근거)나 변제충당 조문을 붙이면 오인용이 된다(wage-update-followups A7·A7b)
    r=WageClaimsResult(calc_date=asof.isoformat(),legal_basis=['근로기준법 제43조 (임금 지급)'])
    from .wage_arrears import _retirement,_prepare_claim,_statutory_allocation,principal_first_note
    effective_raw=inp.arrear_retirement_effective_date or inp.proration_retirement_effective_date
    last_raw=inp.arrear_last_employed_date or inp.last_employed_date
    # 퇴직 여부만 있고 날짜가 없으면 14일 기한을 정할 수 없다 — 원래 기일이 지난 원금은 정산하고 기한·이자만 보류한다(A3)
    retirement_unknown=inp.is_post_retirement_arrear is True and effective_raw is None and last_raw is None
    retirement=retirement_deadline=None
    if not retirement_unknown:
        retirement,retirement_deadline=_retirement(effective_raw,last_raw,inp.is_post_retirement_arrear,
                                                   inp.arrear_deadline_holidays,r.warnings)
    if inp.debtor_is_merchant is not None and not isinstance(inp.debtor_is_merchant,bool):
        raise ValueError('채무자의 상인 여부는 확인된 사실 또는 미확인으로 구분해주세요.')
    merchants=[False,True] if inp.debtor_is_merchant is None else [inp.debtor_is_merchant]
    prepared={};covered=set();derived=set()
    fixed_left=_fixed_overtime_offsets(inp,ow,raw)
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
        # 퇴직금 행의 지급기일은 퇴직 후 14일 기한이다 — 20%의 기산일은 조문이 고정하고 입력한 기일과 무관하다(A4,
        # 근로기준법 제36조·제37조제1항제1호, 근로자퇴직급여 보장법 제9조)
        severance='retirement' in components
        effective_due=(retirement_deadline if severance and retirement_deadline else
                       min(due,retirement_deadline) if retirement_deadline else due)
        if severance and retirement_deadline:
            r.warnings.append(f"{month} {name}: 퇴직금 지급기한은 {retirement_deadline.isoformat()}입니다(근로기준법 제36조, "
                              "근로자퇴직급여 보장법 제9조). 연 20% 지연이자는 그 다음 날부터 붙습니다(근로기준법 제37조 제1항 제1호)."
                              +(f" 입력한 지급일({due.isoformat()})은 법정 기한보다 빨라 기한을 기준으로 계산했습니다. 회사 규정이나 계약에 "
                                "그보다 이른 지급일이 정해져 있었다면, 그 다음 날부터 기한까지 연 5%(상인은 6%) 지연손해금을 따로 "
                                "청구할 여지가 있습니다." if due<retirement_deadline else "")
                              +(f" 아직 퇴직금 지급기한({retirement_deadline.isoformat()})이 지나지 않았습니다."
                                if asof<=retirement_deadline else ""))
        # 지급기한 미확인: 퇴직일을 몰라 14일 기한이 원래 기일보다 빠를 수 있는 행(원래 기일이 아직 안 지남)과 퇴직금 행
        due_unconfirmed=((retirement_unknown and (due>=asof or severance))
                         or (severance and retirement_deadline is None))
        amount,automatic,estimate=_amount(row,inp,ow)
        elements=set(components)|automatic
        if month in fixed_left:
            if row.get('source','explicit')=='explicit' and 'regular' in components:
                elements=elements-{'overtime','night','holiday'}   # 고정연장수당은 아래 파생 행에서 큰 쪽으로 센다
            elif row.get('source') in ('overtime','night','holiday'):
                before=fixed_left[month];offset=min(amount,before);fixed_left[month]-=offset
                r.formulas.append(f"{month} {name}: 계산한 금액 {amount:,.0f}원 − 같은 달 월급에 든 고정연장수당 {before:,.0f}원 "
                                  f"→ 추가 의무액 {amount-offset:,.0f}원 (같은 근로의 대가라 큰 쪽만 청구)")
                amount-=offset
            elif elements&{'overtime','night','holiday'}:
                raise ValueError('같은 달 월급에 고정연장수당이 들어 있어 연장·야간·휴일 임금을 별도 금액으로 다시 청구하지 않습니다. '
                                 '항목 관계를 확인해주세요.')
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
            source=source,effective_due_date=effective_due.isoformat(),due_unconfirmed=due_unconfirmed,
            original_obligation=amount,adjustment=0,obligation=amount,raw=row,payments=[])
    if any(x['source']=='minimum_wage' for x in prepared.values()):
        r.legal_basis.append('최저임금법 제6조 (최저임금의 효력)')
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
    interest_holds=[];timing_unknown=[];alternatives={};agreed=False
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
                total=paid+(interest or 0)
                # 충당 합의가 확인되지 않은 지급기일 뒤 지급은 그때까지 생긴 지연이자에 먼저 충당된다(민법 제479조 — 합의가
                # 없으면 법정 순서, 일방 지정 무효). 회사가 '○월분 급여'로 줬다는 사실만으로 원금 충당으로 보지 않는다(A2)
                agreed|=bool(total) and row.get('paid_allocation_confirmed') is True
                if total and row.get('paid_allocation_confirmed') is not True and x['obligation']>0:
                    if retirement_unknown or x['due_unconfirmed']:
                        timing_unknown.append(f"{x['month']} {x['name']}")
                    elif d>strict_date(x['effective_due_date'],'적용 지급기일'):
                        kind='retirement_lump_sum' if 'retirement' in x['components'] else 'regular_wage'
                        claim=_prepare_claim(dict(id=ident,amount=x['obligation'],claim_kind=kind,payments=[],
                                                  due_date=x['effective_due_date'] if kind=='retirement_lump_sum' else x['due_date'],
                                                  exclusions=row.get('exclusions')),ident,d,retirement,retirement_deadline,kind)
                        split=_statutory_allocation(claim,dict(date=d,amount=total),merchants)
                        if split is None:
                            raise ValueError(f"{x['month']} {x['name']}: 지급기일 뒤에 받은 금액은 그때까지 생긴 지연이자에 먼저 충당되는데"
                                             "(민법 제479조), 채무자의 상인 여부가 확인되지 않아 그 지연이자(연 5%·6%)를 정할 수 없습니다. "
                                             "남은 원금을 확정하지 않습니다. 회사가 상인인지(상행위로 생긴 채무인지)나 원금·이자 충당 합의를 "
                                             "알려주세요.")
                        alternatives[ident]=(min(paid,x['obligation']),interest or 0)
                        interest,paid=split
                        r.statutory_allocations.append(dict(id=ident,month=x['month'],name=x['name'],date=d.isoformat(),
                                                            total=total,interest=interest,principal=paid))
                        r.formulas.append(f"{x['month']} {x['name']}: {d.isoformat()} 지급 {total:,.0f}원 → 그때까지 생긴 지연이자 "
                                          f"{interest:,.0f}원에 먼저, 나머지 {paid:,.0f}원을 원금에 충당 (민법 제479조)")
                if paid or interest:x['payments'].append(dict(date=d.isoformat(),principal_amount=paid,interest_amount=interest,allocation_confirmed=True))
            elif paid or interest:interest_holds.append('실제 지급일이 없어 이자 기간을 계산할 수 없습니다.')
        x.update(paid_principal=paid,remaining=max(0,x['obligation']-paid),overpayment=max(0,paid-x['obligation']),
                 overdue=not x['due_unconfirmed'] and strict_date(x['effective_due_date'],'적용 지급기일')<asof)
        r.items.append(x)
        r.total_obligation+=x['obligation'];r.total_paid+=paid;r.remaining_principal+=x['remaining'];r.overpayment+=x['overpayment']
        if x['overdue']:r.overdue_principal+=x['remaining']
        elif x['due_unconfirmed']:r.due_unconfirmed+=x['remaining']
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
            # 퇴직금 행은 C5가 정한 14일 기한을 넘긴다(C2가 같은 대체 안내를 다시 내지 않는다)
            r.interest_claims.append(dict(id=ident,amount=x['obligation'],claim_kind=kind,payments=history,
                                         due_date=x['effective_due_date'] if kind=='retirement_lump_sum' else x['due_date'],
                                         exclusions=row.get('exclusions')))
        r.formulas.append(f"{x['month']} {x['name']}: 의무액 {x['obligation']:,.0f}원 − 기지급 원금 {paid:,.0f}원 = 미지급 {x['remaining']:,.0f}원"+
                          (f" (초과 지급 {x['overpayment']:,.0f}원 별도)" if x['overpayment'] else ''))
    if timing_unknown:
        raise ValueError(', '.join(dict.fromkeys(timing_unknown))+': 퇴직일이 없어 받은 날이 퇴직 후 14일 지급기한 뒤인지 알 수 '
                         '없습니다. 기한 뒤에 받은 금액은 그때까지 생긴 지연이자에 먼저 충당되므로(민법 제479조) 남은 원금을 확정하지 '
                         '않습니다. 퇴직 효력일 또는 마지막 재직일을 알려주세요.')
    if r.is_estimate:interest_holds.append('월 평균 추정 의무액은 확정 채권이 아닙니다. 실제 월별 의무액을 확인해야 이자를 계산할 수 있습니다.')
    if retirement_unknown or r.due_unconfirmed:
        interest_holds.append('퇴직 효력일 또는 마지막 재직일이 없어 퇴직 후 14일 지급기한과 지연이자를 정할 수 없습니다.')
    r.interest_held_reason=' '.join(dict.fromkeys(interest_holds))
    if r.statutory_allocations or allocated or agreed:
        r.legal_basis.append('민법 제476조~제479조 (변제충당)')
    if r.statutory_allocations:
        r.warnings.append(_principal_first(inp,r,alternatives,principal_first_note))
    r.breakdown={'월별·항목별 원금 명세':r.items,'잔액 기준일':r.calc_date}
    r.warnings+=['명시한 정산 범위의 세전 금액입니다. 목록에 없는 퇴직급여·연차수당·공제를 자동 합산하지 않습니다.',
                '초과 지급은 다른 항목의 체불과 자동 상계하지 않습니다. 지급 의무와 변제충당이 확인된 사실을 전제로 합니다.']
    if r.is_estimate:r.warnings.append('월 평균 조건으로 산출한 추정 원금이 포함되어 있습니다. 실제 월별 채권으로 확정하지 마세요.')
    if retirement_unknown:r.warnings.append('퇴직일을 몰라 원래 지급기일이 지난 항목만 체불 원금으로 확정했습니다. 퇴직 후 14일 기한이 '
        '더 빠를 수 있어 그 밖의 항목은 지급기한 미확인으로 따로 표시합니다.')
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
    if inp.arrear_exclusions:
        return WageArrearsResult(held_reason='공통 이자 제외 기간의 채권별 적용 범위를 확인해주세요. 각 항목의 exclusions에 귀속을 명시해야 합니다.')
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
