"""
해고예고수당 계산기 (근로기준법 제26조)

수요: 69건 (2.7%)

핵심 규칙:
- 30일 전 예고 없이 해고 시: 30일분 통상임금 지급
- 예고일수가 30일 미만 시: (30 - 예고일수)일분 지급
- 예외: 수습 3개월 이내, 일용직 1개월 이내, 천재지변·고의 귀책 등
"""

from dataclasses import dataclass

from ..base import BaseCalculatorResult
from ..models import WageInput, WorkType
from .ordinary_wage import OrdinaryWageResult
from ..constants import DISMISSAL_NOTICE_DAYS


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
    daily_pay = hourly * 8    # 1일 통상임금 (8시간)
    warnings = []
    formulas = []
    legal = ["근로기준법 제26조 (해고의 예고)"]

    notice_given = max(0, inp.notice_days_given)

    # 면제 사유 확인
    is_exempt = False
    exempt_reason = ""

    if inp.work_type == WorkType.DAILY_WORKER:
        warnings.append("일용직 근로자: 계속 근로 1개월 미만 시 해고예고 의무 면제")
        legal.append("근로기준법 제26조 단서 (일용직 1개월 미만)")
        is_exempt = True
        exempt_reason = "일용직 1개월 미만 — 면제 여부는 실제 계속근로기간 확인 필요"

    if inp.is_probation and inp.probation_months <= 3:
        warnings.append("수습기간 3개월 이내: 해고예고 의무 면제")
        legal.append("근로기준법 제26조 단서 (수습 3개월 이내)")
        is_exempt = True
        exempt_reason = f"수습기간 {inp.probation_months}개월 이내 — 면제"

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
        "1일 통상임금": f"{daily_pay:,.0f}원 ({hourly:,.0f}원 × 8h)",
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
