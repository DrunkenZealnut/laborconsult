"""육아 급여 입력·기간 검증. 지급률과 자격 특례는 각 계산기가 결정한다."""
import calendar
import math
from dataclasses import dataclass
from datetime import date, timedelta

from ..effective_rules import split_effective_periods
from ..legal_rules import resolve_reference_date


CHILDCARE_INPUT_FIELDS = frozenset({
    'childcare_example','childcare_child_birth_date','childcare_child_age','childcare_child_grade',
    'childcare_reason','childcare_spouse_risk_eligible','childcare_insured_days',
    'childcare_employer_monthly_payment','parental_leave_months','is_second_parent',
    'parental_leave_start','parental_first_leave_start','parental_first_leave_reason','parental_leave_end','parental_leave_periods','parental_prior_months',
    'parental_prior_days','parental_scheme','parental_same_child','parental_other_parent_months',
    'parental_other_parent_start','parental_other_parent_reason','parental_other_parent_spouse_risk_eligible',
    'parental_other_parent_periods','parental_single_parent_eligible',
    'parental_disabled_child_eligible','short_parental_reason_eligible','short_parental_used_this_year',
    'reduced_work_hours_per_day','reduced_weekly_hours_before','reduced_weekly_hours_after',
    'reduced_start','reduced_end','reduced_periods','reduced_months','reduced_prior_months',
    'reduced_unused_parental_months','reduced_offset_monthly_ordinary_wage',
})


def number(value, label, *, minimum=0, maximum=1e12, integer=False):
    if isinstance(value,bool):
        raise ValueError(f'{label} 숫자를 확인해주세요')
    try: n=float(value)
    except (TypeError,ValueError): raise ValueError(f'{label} 숫자를 확인해주세요') from None
    if not math.isfinite(n) or not minimum <= n <= maximum or (integer and n != int(n)):
        raise ValueError(f'{label} 범위를 확인해주세요')
    return int(n) if integer else n


def day(value, label):
    try:
        if not isinstance(value,str) or len(value)!=10: raise ValueError()
        return date.fromisoformat(value)
    except (ValueError,TypeError): raise ValueError(f'{label} 날짜(YYYY-MM-DD)를 확인해주세요') from None


def month_after(start, count=1):
    """민법상 역월: 대응일 없으면 그 달 말일까지 사용, 종료 제외는 다음 날."""
    y,m=divmod(start.year*12+start.month-1+count,12);m+=1
    last=calendar.monthrange(y,m)[1]
    return date(y,m,start.day) if start.day<=last else date(y,m,last)+timedelta(days=1)


@dataclass(frozen=True)
class BenefitWindow:
    start: date | None
    end: date | None # exclusive
    month_index: int
    fraction: float
    kind: str
    pieces: tuple # (start,end,rule,fraction)
    period: dict


def periods_from_input(inp, reduced=False):
    prefix='reduced' if reduced else 'parental_leave'
    raw=getattr(inp,prefix+'_periods')
    start=getattr(inp, 'reduced_start' if reduced else 'parental_leave_start')
    end=getattr(inp,'reduced_end' if reduced else 'parental_leave_end')
    months=number(getattr(inp,'reduced_months' if reduced else 'parental_leave_months'),
                  '사용 개월 수',maximum=36,integer=True)
    if raw is not None:
        if start or end: raise ValueError('사용 구간 목록과 단일 시작·종료일 중 한 방식을 입력해주세요')
        if not isinstance(raw,list) or not 1<=len(raw)<=40: raise ValueError('실제 사용 구간 목록을 확인해주세요')
    elif start:
        s=day(start,'사용 시작일')
        if end:
            e=day(end,'사용 종료일')+timedelta(days=1)
            if months and month_after(s,months)!=e: raise ValueError('사용 개월 수와 시작·종료일이 서로 다릅니다')
        elif months: e=month_after(s,months)
        else: raise ValueError('사용 종료일 또는 사용 개월 수를 확인해주세요')
        raw=[dict(start_date=start,end_date=(e-timedelta(days=1)).isoformat())]
    elif end: raise ValueError('사용 시작일을 확인해주세요')
    else: return [],months
    out=[]
    for p in raw:
        if not isinstance(p,dict): raise ValueError('사용 구간은 시작일·종료일이 필요합니다')
        s=day(p.get('start_date'),'사용 시작일');e=day(p.get('end_date'),'사용 종료일')+timedelta(days=1)
        if e<=s or (e-s).days>1120: raise ValueError('사용 시작·종료일 순서와 기간을 확인해주세요')
        if p.get('kind','regular') not in ('regular','short'): raise ValueError('휴직 종류를 확인해주세요')
        out.append((s,e,p))
    out.sort(key=lambda x:x[0])
    if any(out[i-1][1]>out[i][0] for i in range(1,len(out))): raise ValueError('사용 구간이 중복됩니다')
    return out,months


def windows(inp,rules,*,reduced=False):
    if not isinstance(inp.childcare_example,bool): raise ValueError('제도 예시 여부를 확인해주세요')
    reference=day(resolve_reference_date(inp.reference_date,inp.reference_year),'조회 기준일')
    periods,months=periods_from_input(inp,reduced)
    prior=number(getattr(inp,'reduced_prior_months' if reduced else 'parental_prior_months'),
                 '기존 사용 개월 수',maximum=36,integer=True)
    if not reduced and number(inp.parental_prior_days,'기존 사용 잔여 일수',maximum=366,integer=True):
        raise ValueError('기존 분할 사용의 잔여 일수가 있습니다. 누적 월차를 확인할 월별 지급 내역이 필요합니다')
    if not periods:
        if inp.childcare_example is not True: raise ValueError('실제 사용 시작·종료일을 확인해주세요. 날짜 없는 제도 예시는 별도로 지정할 수 있습니다')
        if months<=0: raise ValueError('예시의 사용 개월 수를 확인해주세요')
        rule=split_effective_periods(reference,reference+timedelta(days=1),rules)[0].rule
        return [BenefitWindow(None,None,prior+i+1,1.,'regular',((None,None,rule,1.),),{}) for i in range(months)],reference,prior
    result=[];index=prior+1
    for pi,(s,e,p) in enumerate(periods):
        cursor=s;offset=0
        while cursor<e:
            stop=min(month_after(s,offset+1),e)
            full=stop==month_after(s,offset+1)
            if not full and p.get('kind','regular')!='short' and (cursor.year,cursor.month)!=((stop-timedelta(days=1)).year,(stop-timedelta(days=1)).month):
                raise ValueError('월 중 개시 후 두 달에 걸쳐 끝난 일부월은 고용센터의 지급대상월·일할 분모 확인이 필요합니다')
            pieces=[]
            for sl in split_effective_periods(cursor,stop,rules):
                if full:
                    pieces.append((sl.start,sl.end_exclusive,sl.rule,(sl.end_exclusive-sl.start).days/(stop-cursor).days))
                else:
                    # 일부월은 달력상 해당 월의 실제 일수로 나눈다.
                    c=sl.start
                    while c<sl.end_exclusive:
                        b=min(date(c.year,c.month,calendar.monthrange(c.year,c.month)[1])+timedelta(days=1),sl.end_exclusive)
                        pieces.append((c,b,sl.rule,(b-c).days/calendar.monthrange(c.year,c.month)[1]));c=b
            fraction=sum(x[3] for x in pieces)
            result.append(BenefitWindow(cursor,stop,index,fraction,p.get('kind','regular'),tuple(pieces),p))
            cursor=stop;offset+=1;index+=1
            if not full and pi<len(periods)-1:
                raise ValueError('1개월 미만 분할 사용 뒤 재사용하는 경우 누적 월차를 확인할 월별 지급 내역이 필요합니다')
    if months and abs(sum(w.fraction for w in result)-months)>1e-9:
        raise ValueError('사용 개월 수와 실제 사용 구간의 길이가 서로 다릅니다')
    return result,reference,prior


def check_child(inp,start,warnings,*,reduced=False,reason=None):
    reason=inp.childcare_reason if reason is None else reason
    if reason not in ('child','pregnant_self','pregnant_spouse'): raise ValueError('육아휴직 사유를 확인해주세요')
    if reason!='child':
        if reduced: raise ValueError('육아기 단축급여와 임신기 근로시간 단축은 별도 제도입니다')
        if inp.childcare_child_birth_date and start>day(inp.childcare_child_birth_date,'자녀 생년월일'):
            raise ValueError('출생 후 다시 시작한 구간은 자녀 양육 사유로 구분해주세요')
        if reason=='pregnant_spouse' and (start<date(2026,9,18) or inp.childcare_spouse_risk_eligible is not True):
            raise ValueError('임신 중 배우자 돌봄은 2026-09-18 이후 법정 위험 요건 확인이 필요합니다')
        return
    age=inp.childcare_child_age;grade=inp.childcare_child_grade
    if inp.childcare_child_birth_date:
        birth=day(inp.childcare_child_birth_date,'자녀 생년월일')
        if birth>start: raise ValueError('출생 전이면 임신 중 사용 사유를 구분해주세요')
        age=start.year-birth.year-((start.month,start.day)<(birth.month,birth.day))
    if age is not None: age=number(age,'자녀 만 나이',maximum=30,integer=True)
    if grade is not None: grade=number(grade,'초등 학년',minimum=1,maximum=12,integer=True)
    a,g=(12,6) if reduced and start>=date(2025,2,23) else (8,2)
    if (age is not None and age<=a) or (grade is not None and grade<=g): return
    if age is not None and grade is not None: raise ValueError(f'자녀 만 {a}세 이하 또는 초등 {g}학년 이하 요건을 충족하지 않습니다')
    warnings.append(f'자녀 만 {a}세 이하 또는 초등 {g}학년 이하 요건 충족을 전제로 한 조건부 금액입니다')


def common_checks(inp,ws,reference,warnings,*,reduced=False):
    if inp.childcare_insured_days is None:
        warnings.append('급여 수급은 개시일 전 피보험 단위기간 180일 이상 등 요건 확인이 필요합니다')
    elif number(inp.childcare_insured_days,'피보험 단위기간',integer=True)<180:
        raise ValueError('개시일 전 피보험 단위기간 180일 요건을 충족하지 않습니다')
    # 자녀 연령은 매달 재판정하지 않고 각 사용 구간 개시일로 확인한다.
    seen=set()
    for w in ws:
        s=w.period.get('start_date')
        if s not in seen:
            check_child(inp,day(s,'사용 시작일') if s else reference,warnings,
                        reduced=reduced,reason=w.period.get('reason'));seen.add(s)
    if ws[0].start is None:
        warnings.append(f'{reference.isoformat()} 기준 내장 규칙을 고정한 제도 예시이며 실제 사용일·지급 확정액이 아닙니다')
    warnings.append('월 통상임금은 해당 휴직·단축 개시일 기준 입력값입니다. 신청 시기·취업·소득에 따른 지급 제한은 별도 확인이 필요합니다')
    if inp.childcare_employer_monthly_payment is None:
        warnings.append('사업주 지급액 미확인: 금액은 사업주 지급에 따른 감액 전 평가액입니다')


def employer_payment(inp,w):
    value=w.period.get('employer_monthly_payment',inp.childcare_employer_monthly_payment)
    return None if value is None else number(value,'사업주 월 지급액')*w.fraction
