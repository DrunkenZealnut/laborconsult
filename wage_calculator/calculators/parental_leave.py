"""육아휴직급여: 지급 대상 기간의 규칙과 누적 월차를 별도로 보존한다."""
from dataclasses import dataclass, field
from datetime import date

from ..base import BaseCalculatorResult
from ..effective_rules import PARENTAL_RULES
from ..legal_rules import RuleUnavailable
from ..models import WageInput
from .ordinary_wage import OrdinaryWageResult
from .childcare_shared import (windows, common_checks, number, day, month_after,
                              employer_payment)


@dataclass
class ParentalLeaveResult(BaseCalculatorResult):
    monthly_ordinary_wage: float = 0.0
    monthly_benefit_before_deferred: float = 0.0 # 첫 지급 월의 호환 값
    monthly_benefit_actual: float = 0.0
    monthly_deferred: float = 0.0
    total_months: float = 0.0
    total_benefit: float = 0.0
    total_deferred: float = 0.0
    has_bonus: bool = False
    bonus_months: int = 0
    monthly_bonus_benefit: float = 0.0
    reduced_work_monthly_benefit: float = 0.0
    upper_limit_applied: bool = False
    lower_limit_applied: bool = False
    monthly_schedule: list = field(default_factory=list)
    scheme: str = 'general'


def _other_parent(inp):
    months=inp.parental_other_parent_months
    start=inp.parental_other_parent_start
    if inp.parental_other_parent_periods is not None:
        from dataclasses import replace
        other=replace(inp,parental_leave_periods=inp.parental_other_parent_periods,
                      parental_leave_start=None,parental_leave_end=None,parental_leave_months=0,
                      parental_prior_months=0,parental_prior_days=0)
        ws,_,_=windows(other,PARENTAL_RULES)
        if any(w.fraction!=1 for w in ws):
            raise ValueError('상대 부모의 1개월 미만 사용분은 6+6 대응 지급 내역을 확인해주세요')
        actual=len(ws)
        if months is not None and months!=actual: raise ValueError('상대 부모 사용 개월 수와 구간이 다릅니다')
        if start and start!=ws[0].start.isoformat(): raise ValueError('상대 부모 개시일과 사용 구간이 다릅니다')
        months=actual;start=ws[0].start.isoformat()
    return (None if months is None else number(months,'상대 부모 사용 개월 수',maximum=18,integer=True)),start


def _scheme(inp,ws,reference):
    scheme=inp.parental_scheme
    if scheme not in ('general','single_parent','six_plus_six'): raise ValueError('육아휴직급여 유형을 확인해주세요')
    if inp.is_second_parent and scheme=='general':
        raise ValueError('두 번째 사용자라는 사실만으로 특례를 판정할 수 없습니다. 같은 자녀·양쪽 개시일과 사용 기간을 확인해주세요')
    other,start=_other_parent(inp)
    if inp.parental_single_parent_eligible is True and scheme=='general': scheme='single_parent'
    if scheme=='single_parent' and inp.parental_single_parent_eligible is not True:
        raise ValueError('한부모가족지원법상 한부모 자격을 확인해주세요')
    matched=0
    if scheme=='six_plus_six':
        if inp.parental_same_child is not True or other is None or other<=0 or not start:
            raise ValueError('6+6은 같은 자녀에 대한 양쪽 부모의 개시일·사용 기간 확인이 필요합니다')
        first=ws[0].start
        if first is None: raise ValueError('6+6은 양쪽 부모의 실제 개시일이 필요합니다')
        if inp.parental_prior_months and not inp.parental_first_leave_start:
            raise ValueError('6+6 재사용은 같은 자녀에 대한 본인 최초 개시일을 확인해주세요')
        if inp.parental_first_leave_start:
            initial=day(inp.parental_first_leave_start,'최초 육아휴직 개시일')
            if initial>first: raise ValueError('최초 개시일이 재사용 개시일보다 늦습니다')
            first=initial
        second=day(start,'상대 부모 개시일')
        if inp.childcare_reason=='child':
            if not inp.childcare_child_birth_date: raise ValueError('6+6 자녀 생년월일을 확인해주세요')
            birth=day(inp.childcare_child_birth_date,'자녀 생년월일')
            if any(d<birth or d>month_after(birth,18) for d in (first,second)):
                raise ValueError('6+6은 부모 각각의 개시일에 자녀가 생후 18개월 이내여야 합니다')
        elif inp.childcare_reason=='pregnant_spouse' and first<date(2026,9,18):
            raise ValueError('임신 중 배우자 돌봄 특례 시행일을 확인해주세요')
        matched=min(6,other)
    return scheme,matched,other


def _validate_periods(inp,ws,reference,prior,other):
    extended=(inp.parental_single_parent_eligible is True or inp.parental_disabled_child_eligible is True or
              (inp.parental_same_child is True and other is not None and other>=3 and prior+sum(w.fraction for w in ws)>=3))
    seen_short=set();normal_days=0
    for w in ws:
        start=w.start or reference
        if w.month_index>12 and (not extended or start<date(2025,2,23)):
            raise ValueError('12개월 초과는 2025-02-23 이후 부모 각각 3개월 사용·법정 한부모·장애아동 부모 중 연장 자격 확인이 필요합니다')
        if w.month_index>18: raise ValueError('육아휴직 총 사용 기간은 연장 대상도 18개월 이내입니다')
        if w.kind=='short':
            if inp.childcare_reason!='child': raise ValueError('단기 육아휴직은 출생한 자녀의 법정 돌봄 사유를 확인해주세요')
            days=(w.end-w.start).days
            if start<date(2026,8,20) or days not in (7,14):
                raise ValueError('단기 육아휴직은 2026-08-20 이후 연 1회 7일 또는 14일입니다')
            if inp.short_parental_reason_eligible is not True or inp.short_parental_used_this_year is not False:
                raise ValueError('단기 육아휴직의 법정 사유와 해당 연도 기사용 여부를 확인해주세요')
            if inp.childcare_insured_days is None: raise ValueError('단기 급여는 피보험 단위기간 180일 확인이 필요합니다')
            if start.year in seen_short: raise ValueError('단기 육아휴직은 연 1회입니다')
            seen_short.add(start.year)
        elif w.start: normal_days+=(w.end-w.start).days
    if ws[0].start and normal_days and normal_days+sum((w.end-w.start).days for w in ws if w.kind=='short')<30:
        raise ValueError('일반 육아휴직급여는 합산 30일 이상 부여 요건을 확인해주세요')


def calc_parental_leave(inp: WageInput, ow: OrdinaryWageResult) -> ParentalLeaveResult:
    r=ParentalLeaveResult(legal_basis=['고용보험법 제70조·제71조',
        '고용보험법 시행령 제95조·제95조의3·제98조',
        '남녀고용평등법 제19조·제19조의4',
        '내장 시행일 규칙: 제35100호 부칙 제3·4·7조 (관리자 승인 키와 별도)'])
    try:
        wage=number(ow.monthly_ordinary_wage,'개시일 기준 월 통상임금',minimum=1)
        ws,reference,prior=windows(inp,PARENTAL_RULES)
        common_checks(inp,ws,reference,r.warnings)
        scheme,matched,other=_scheme(inp,ws,reference)
        _validate_periods(inp,ws,reference,prior,other)
        r.scheme=scheme;r.monthly_ordinary_wage=wage
        for w in ws:
            gross=paid=deferred=0.;parts=[]
            for a,b,rule,fraction in w.pieces:
                v=rule.values;i=w.month_index
                tier=0 if i<=3 else (1 if i<=6 else 2)
                rate=v['general_rates'][tier];cap=v['general_caps'][tier]
                special=(scheme=='six_plus_six' and i<=matched) or (scheme=='single_parent' and i<=3)
                if scheme=='six_plus_six' and i<=matched: rate=1.;cap=v['six_caps'][i-1]
                if scheme=='single_parent' and i<=3: rate=1.;cap=v['single_cap']
                raw=wage*rate;monthly=max(v['lower'],min(raw,cap))
                current=monthly if special else max(v['lower'],monthly*(1-v['deferred']))
                gross+=monthly*fraction;paid+=current*fraction;deferred+=(monthly-current)*fraction
                r.upper_limit_applied |= raw>cap;r.lower_limit_applied |= raw<v['lower']
                parts.append(dict(start_date=a.isoformat() if a else None,
                                  end_date=b.isoformat() if b else None,end_exclusive=True,
                                  rule_id=rule.rule_id,rate=rate,cap=cap,lower=v['lower'],fraction=fraction,
                                  monthly_gross=monthly,monthly_actual=current))
            employer=employer_payment(inp,w);reduction=0.
            if employer is not None and employer>0:
                if any(p['rule_id']=='parental-2024' for p in parts) and employer:
                    raise ValueError('2024년 사업주 지급액이 있는 경우 종전 감액·사후지급 내역을 확인해주세요')
                if w.fraction!=1 and (w.start or reference)<date(2026,7,1):
                    raise ValueError('2026-07-01 전 일부월 사업주 지급액 감액은 당시 지급 내역을 확인해주세요')
                reduction=min(paid,max(0,paid+employer-wage*w.fraction));paid-=reduction
            row=dict(month_index=w.month_index,start_date=w.start.isoformat() if w.start else None,
                     end_date=(w.end.isoformat() if w.end else None),end_exclusive=True,
                     fraction=w.fraction,kind=w.kind,gross=round(gross),payment=round(gross)-round(deferred)-round(reduction),
                     deferred=round(deferred),employer_payment=employer,employer_reduction=round(reduction),rules=parts)
            r.monthly_schedule.append(row)
            r.formulas.append(f'{w.month_index}개월 차: {row["gross"]:,}원 − 사후지급 {row["deferred"]:,}원 − 사업주 지급 조정 {row["employer_reduction"]:,}원 = {row["payment"]:,}원')
        r.total_benefit=sum(x['payment'] for x in r.monthly_schedule)
        r.total_deferred=sum(x['deferred'] for x in r.monthly_schedule)
        first=r.monthly_schedule[0]
        r.monthly_benefit_before_deferred=first['gross'];r.monthly_benefit_actual=first['payment'];r.monthly_deferred=first['deferred']
        r.total_months=sum(w.fraction for w in ws);r.has_bonus=scheme=='six_plus_six'
        r.bonus_months=sum(w.month_index<=matched for w in ws)
        r.monthly_bonus_benefit=first['payment'] if r.has_bonus else 0
        r.breakdown={'급여 유형':{'general':'일반형','single_parent':'법정 한부모','six_plus_six':'6+6 부모 함께'}[scheme],
                     '월차별 지급 내역':r.monthly_schedule,'육아휴직 급여 합계':f'{r.total_benefit:,.0f}원',
                     '사후지급 합계':f'{r.total_deferred:,.0f}원'}
        if r.total_deferred:
            r.warnings.append('2024년 대상 기간의 사후지급분은 복직 후 6개월 계속 근무 또는 법정 예외 요건을 따릅니다')
        if inp.reduced_weekly_hours_before is not None or inp.reduced_work_hours_per_day:
            from .reduced_work_benefit import calc_reduced_work_benefit
            reduced=calc_reduced_work_benefit(inp,ow)
            if reduced.held_reason: r.warnings.append('별도 단축급여: '+reduced.held_reason)
            else: r.reduced_work_monthly_benefit=reduced.monthly_benefit
        return r
    except (ValueError,TypeError,RuleUnavailable) as exc:
        return ParentalLeaveResult(held_reason=str(exc),legal_basis=r.legal_basis)
