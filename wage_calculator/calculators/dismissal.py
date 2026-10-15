"""
해고예고수당 계산기 (근로기준법 제26조)

수요: 69건 (2.7%)

핵심 규칙:
- 30일 전 예고 없이 해고 시: 30일분 통상임금 지급
- 예고일수가 30일 미만 시: (30 - 예고일수)일분 지급
- 예외(현행 제26조 단서): 1. 계속 근로한 기간 3개월 미만 2. 천재·사변 등으로 사업 계속 불가
  3. 근로자가 고의로 막대한 지장·손해(고용노동부령 사유). 수습·일용직·계절적 사업을 따로 면제하는 규정은 없다
"""

from dataclasses import dataclass

from ..base import BaseCalculatorResult
from ..legal_rules import kst_today
from ..models import WageInput, WorkType
from .ordinary_wage import OrdinaryWageResult
from ..constants import DISMISSAL_NOTICE_DAYS
from ..utils import fmt_hours, parse_date


@dataclass
class DismissalResult(BaseCalculatorResult):
    dismissal_pay: float = 0.0       # 해고예고수당 (원)
    notice_days_required: int = 0    # 필요 예고일수
    notice_days_given: int = 0       # 실제 예고일수
    payable_days: int = 0            # 수당 지급 일수
    is_exempt: bool = False          # 해고예고 의무 면제 여부


def calc_dismissal(inp: WageInput, ow: OrdinaryWageResult) -> DismissalResult:
    """해고예고수당 계산"""
    hourly = ow.hourly_ordinary_wage
    daily_hours = inp.schedule.daily_work_hours
    daily_pay = hourly * daily_hours  # 1일 통상임금 (소정근로시간)
    warnings = []
    formulas = []
    legal = ["근로기준법 제26조 (해고의 예고)"]

    notice_given = max(0, inp.notice_days_given)

    # 면제 사유 확인
    is_exempt = False
    exempt_reason = ""

    # 예외는 현행 제26조 단서 세 호뿐이다(calc-card-followups F7). 예전 카드는 조문에 없는 '수습 3개월 이내'·'일용직 1개월
    # 미만'·'계절적 사업 4개월 이내'를 면제로 보아, 수습 입사 5개월째 해고에 0원을, 정규직 입사 2개월째 해고에 30일분을 냈다
    # (R16·R17 — 둘 다 반대). 계속근로기간은 입사일부터 해고(퇴직)일까지로 따진다
    under_three = _tenure_under_three_months(inp)
    if under_three:
        warnings.append("계속 근로한 기간이 3개월 미만이라 해고예고 의무가 없습니다(근로기준법 제26조 단서 제1호).")
        legal.append("근로기준법 제26조 단서 제1호 (계속 근로 3개월 미만)")
        is_exempt = True
        exempt_reason = "계속 근로 3개월 미만 — 면제(제26조 단서 제1호)"
    elif under_three is None:
        warnings.append("입사일을 몰라 계속근로기간을 확인하지 못했습니다 — 계속 근로한 기간이 3개월 미만이면 해고예고 의무가 "
                        "없습니다(근로기준법 제26조 단서 제1호).")

    # 천재·사변 등(제2호), 근로자의 고의로 막대한 지장·손해(제3호, 고용노동부령 사유)
    if inp.is_force_majeure:
        warnings.append("천재·사변 등으로 사업을 계속할 수 없거나, 근로자가 고의로 사업에 막대한 지장·재산상 손해를 끼친 경우"
                        "(고용노동부령으로 정하는 사유)라 해고예고 의무가 없습니다.")
        legal.append("근로기준법 제26조 단서 제2호·제3호")
        is_exempt = True
        exempt_reason = "천재·사변 또는 근로자의 고의에 의한 손해(고용노동부령 사유) — 면제"

    # 예전 카드가 면제로 보던 사정 — 답변이 그 옛 면제를 되살리지 않게 적어 둔다
    kind = ("수습" if inp.is_probation else "계절적 사업" if inp.is_seasonal_worker
            else "일용직" if inp.work_type == WorkType.DAILY_WORKER else None)
    if kind and not is_exempt:
        warnings.append(f"{kind}이라는 사정만으로는 해고예고 의무가 면제되지 않습니다 — 근로기준법 제26조 단서의 예외는 계속 근로한 "
                        "기간 3개월 미만(제1호), 천재·사변 등으로 사업을 계속할 수 없는 경우(제2호), 근로자가 고의로 막대한 지장·"
                        "손해를 끼친 경우(제3호) 세 가지입니다.")

    if is_exempt:
        breakdown = {
            "해고예고 의무": "면제",
            "사유": exempt_reason,
            "수당": "해당없음",
        }
        return DismissalResult(
            dismissal_pay=0.0,
            notice_days_required=DISMISSAL_NOTICE_DAYS,
            notice_days_given=notice_given,
            payable_days=0,
            is_exempt=True,
            breakdown=breakdown,
            formulas=[],
            warnings=warnings,
            legal_basis=legal,
        )

    # 수당 지급 일수
    payable_days = max(0, DISMISSAL_NOTICE_DAYS - notice_given)
    dismissal_pay = daily_pay * payable_days

    if payable_days > 0:
        formulas.append(
            f"해고예고수당: {daily_pay:,.0f}원/일 × {payable_days}일 = {dismissal_pay:,.0f}원"
        )
        formulas.append(
            f"(30일 - 실제 예고 {notice_given}일 = {payable_days}일분)"
        )
    else:
        formulas.append(f"예고일수 {notice_given}일 ≥ 30일 → 해고예고수당 없음")

    breakdown = {
        "1일 통상임금": f"{daily_pay:,.0f}원 ({hourly:,.0f}원 × {fmt_hours(daily_hours)}h)",
        "필요 예고일수": f"{DISMISSAL_NOTICE_DAYS}일",
        "실제 예고일수": f"{notice_given}일",
        "수당 지급일수": f"{payable_days}일",
        "해고예고수당": f"{dismissal_pay:,.0f}원",
    }

    return DismissalResult(
        dismissal_pay=round(dismissal_pay, 0),
        notice_days_required=DISMISSAL_NOTICE_DAYS,
        notice_days_given=notice_given,
        payable_days=payable_days,
        is_exempt=False,
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )


def _add_months(d, months: int):
    """기산일에서 N개월이 차는 경계(그날부터는 N개월 이상) — 그달에 같은 날이 없으면 다음 달 1일이다. 민법 제160조 제3항은 최종의 월에
    해당일이 없으면 그 월의 말일로 기간이 만료한다고 하므로 1월 31일 입사는 4월 30일까지 일해야 3개월이고 5월 1일이 경계다(2차 리뷰
    L1 — 예전에는 4월 30일을 경계로 잡아 하루 일찍 '3개월 이상'으로 봤다)."""
    import calendar
    from datetime import timedelta
    month_index = d.month - 1 + months
    year, month = d.year + month_index // 12, month_index % 12 + 1
    last = calendar.monthrange(year, month)[1]
    if d.day > last:
        return d.replace(year=year, month=month, day=last) + timedelta(days=1)
    return d.replace(year=year, month=month)


def _tenure_under_three_months(inp: WageInput) -> bool | None:
    """계속 근로한 기간이 3개월 미만인가(근로기준법 제26조 단서 제1호). 입사일을 모르면 None. 종료일은 퇴직금의 계속근로기간과 같이
    마지막 근무일 다음 날로 본다(입사일 ~ 종료일 전날)."""
    if inp.tenure_months is not None:
        return inp.tenure_months < 3
    start = parse_date(inp.start_date) if inp.start_date else None
    if not start:
        return None
    end_text = inp.end_date or inp.dismissal_date or inp.reference_date
    end = parse_date(end_text) if end_text else None
    # kst_today()는 'YYYY-MM-DD' 문자열이다 — 그대로 비교하면 TypeError로 카드 전체가 사라졌다(2차 리뷰 H1, 종료일 없는 질문)
    return (end or parse_date(kst_today())) < _add_months(start, 3)

