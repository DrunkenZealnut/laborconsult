"""육아기 근로시간 단축급여. 사업주 지급 임금과 별도의 고용보험 급여."""
from dataclasses import dataclass, field
from datetime import date

from ..base import BaseCalculatorResult
from ..effective_rules import REDUCED_RULES
from ..legal_rules import RuleUnavailable
from .childcare_shared import windows,common_checks,number,employer_payment


@dataclass
class ReducedWorkBenefitResult(BaseCalculatorResult):
    monthly_ordinary_wage: float = 0.
    monthly_benefit: float = 0. # 첫 지급 월의 호환 값
    total_benefit: float = 0.
    weekly_hours_before: float = 0.
    weekly_hours_after: float = 0.
    monthly_schedule: list = field(default_factory=list)


def calc_reduced_work_benefit(inp,ow):
    r=ReducedWorkBenefitResult(legal_basis=['고용보험법 제73조의2·제74조',
        '고용보험법 시행령 제104조의2·제104조의4', '남녀고용평등법 제19조의2',
        '내장 시행일 규칙: 제34601호 부칙 제3조·제35100호 부칙 제5조·제35934호 부칙 제3조'])
    try:
        before=number(inp.reduced_weekly_hours_before,'단축 전 주 소정근로시간',minimum=15,maximum=40)
        after=number(inp.reduced_weekly_hours_after,'단축 후 주 소정근로시간',minimum=15,maximum=35)
        if before<=after: raise ValueError('단축 후 주 소정근로시간은 단축 전보다 적어야 합니다')
        wage=number(ow.monthly_ordinary_wage,'단축 개시일 월 통상임금',minimum=1)
        ws,reference,prior=windows(inp,REDUCED_RULES,reduced=True)
        common_checks(inp,ws,reference,r.warnings,reduced=True)
        unused=inp.reduced_unused_parental_months
        if unused is not None: unused=number(unused,'기본 12개월 중 미사용 육아휴직 개월 수',maximum=12)
        if ws[0].start and sum((w.end-w.start).days for w in ws)<30:
            raise ValueError('육아기 단축급여는 단축 30일 이상 부여 요건을 확인해주세요')
        for w in ws:
            if w.kind!='regular': raise ValueError('단기 육아휴직과 육아기 단축은 별도 제도입니다')
            if w.month_index>12:
                if unused is None: raise ValueError('12개월 초과 단축은 기본 12개월 중 미사용 육아휴직 기간을 확인해주세요')
                multiplier=2 if (w.start or reference)>=date(2025,2,23) else 1
                if w.month_index-1+w.fraction>12+multiplier*unused:
                    raise ValueError('미사용 육아휴직을 반영한 육아기 단축 최대 기간을 초과합니다')
            first=remaining=0.;parts=[]
            for a,b,rule,fraction in w.pieces:
                v=rule.values;hours=before-after
                first_base=max(v['lower'],min(wage,v['first_cap']))
                remaining_base=max(v['lower'],min(wage*.8,v['remaining_cap']))
                f=first_base*min(hours,v['first_hours'])/before
                rest=remaining_base*max(0,hours-v['first_hours'])/before
                first+=f*fraction;remaining+=rest*fraction
                parts.append(dict(rule_id=rule.rule_id,start_date=a.isoformat() if a else None,
                                  end_date=b.isoformat() if b else None,end_exclusive=True,
                                  fraction=fraction,first_hours=v['first_hours'],first_base=first_base,
                                  remaining_base=remaining_base,first_monthly=f,remaining_monthly=rest))
            gross=first+remaining;paid=gross;reduction=0.
            employer=employer_payment(inp,w)
            if employer is not None and employer>0:
                limit=w.period.get('offset_monthly_ordinary_wage',inp.reduced_offset_monthly_ordinary_wage)
                if limit is None:
                    raise ValueError('사업주 지급액 감액을 위해 단축 직전월 또는 인상 후의 해당 기간 월 통상임금을 확인해주세요')
                limit=number(limit,'단축급여 감액 기준 월 통상임금',minimum=1)
                reduction=min(gross,max(0,gross+employer-limit*w.fraction));paid-=reduction
            row=dict(month_index=w.month_index,start_date=w.start.isoformat() if w.start else None,
                     end_date=w.end.isoformat() if w.end else None,end_exclusive=True,fraction=w.fraction,
                     first_part=first,remaining_part=remaining,gross=round(gross),payment=round(paid),
                     employer_payment=employer,employer_reduction=round(reduction),rules=parts)
            r.monthly_schedule.append(row)
            r.formulas.append(f'{w.month_index}개월 차: 최초 구간 {first:,.0f}원 + 나머지 {remaining:,.0f}원 − 사업주 지급 조정 {reduction:,.0f}원 = {paid:,.0f}원')
        r.monthly_ordinary_wage=wage;r.weekly_hours_before=before;r.weekly_hours_after=after
        r.total_benefit=sum(x['payment'] for x in r.monthly_schedule)
        r.monthly_benefit=r.monthly_schedule[0]['payment']
        r.breakdown={'단축 전후 주 소정근로시간':f'{before:g} → {after:g}시간',
                     '고용보험 단축급여 합계':f'{r.total_benefit:,.0f}원','월별 지급 내역':r.monthly_schedule}
        return r
    except (ValueError,TypeError,RuleUnavailable) as exc:
        return ReducedWorkBenefitResult(held_reason=str(exc),legal_basis=r.legal_basis)
