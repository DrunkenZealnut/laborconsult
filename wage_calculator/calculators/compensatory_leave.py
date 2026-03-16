"""
보상휴가 환산 계산기 (근로기준법 제57조)

핵심 개념:
- 연장·야간·휴일 근로에 대해 임금 대신 휴가를 부여하는 제도
- 노사 서면합의 필요
- 보상휴가 시간 = 연장시간 × 1.5 + 야간시간 × 0.5 + 휴일(8h이내) × 1.5 + 휴일(8h초과) × 2.0
- 미사용 보상휴가 수당 = 보상휴가 시간 × 통상시급 (사용 기한 내 미사용 시)
"""

from dataclasses import dataclass

from ..base import BaseCalculatorResult
from ..utils import WEEKS_PER_MONTH
from ..models import WageInput, BusinessSize
from .ordinary_wage import OrdinaryWageResult
from .shared import MultiplierContext
from ..constants import OVERTIME_RATE, NIGHT_PREMIUM_RATE, HOLIDAY_RATE, HOLIDAY_OT_RATE


@dataclass
class CompensatoryLeaveResult(BaseCalculatorResult):
    # 보상휴가 시간 (실제 부여 가능한 시간)
    compensatory_hours: float = 0.0        # 총 보상휴가 시간
    overtime_comp_hours: float = 0.0       # 연장근로 분 보상휴가 시간
    night_comp_hours: float = 0.0          # 야간근로 분 보상휴가 시간
    holiday_comp_hours: float = 0.0        # 휴일근로 분 보상휴가 시간 (8h이내)
    holiday_ot_comp_hours: float = 0.0     # 휴일근로 분 보상휴가 시간 (8h초과)

    # 미사용 보상휴가 수당
    unused_leave_pay: float = 0.0          # 미사용 보상휴가 수당 (원/주)
    monthly_unused_pay: float = 0.0        # 월 환산 (원/월)

    # 원래 수당 (비교용)
    original_overtime_pay: float = 0.0     # 현금 지급 시 수당 합계 (원/주)


def calc_compensatory_leave(inp: WageInput, ow: OrdinaryWageResult) -> CompensatoryLeaveResult:
    """
    보상휴가 환산 계산

    Args:
        inp: 임금 입력 데이터
        ow: 통상임금 계산 결과
    """
    s = inp.schedule
    hourly = ow.hourly_ordinary_wage
    warnings = []
    formulas = []
    legal = ["근로기준법 제57조 (보상휴가제)"]

    mc = MultiplierContext(inp)

    small_warn = mc.small_business_warning()
    if small_warn:
        warnings.append(
            "5인 미만 사업장: 가산수당 미적용으로 보상휴가 가산분도 미적용 "
            "(연장근로 1.0배, 야간근로 0배, 휴일근로 1.0배만 적용)"
        )

    # ── 배율 설정 (5인 미만은 가산 없음) ───────────────────────────────────
    ot_rate      = mc.overtime
    night_rate   = mc.night
    hol_rate     = mc.holiday
    hol_ot_rate  = mc.holiday_ot

    # ── 보상휴가 시간 계산 ────────────────────────────────────────────────
    ot_hours         = s.weekly_overtime_hours
    night_hours      = s.weekly_night_hours
    hol_hours        = s.weekly_holiday_hours
    hol_ot_hours     = s.weekly_holiday_overtime_hours

    # 연장근로: 실제 시간 + 가산 (1.5배 → 1시간 연장 = 1.5시간 보상휴가)
    overtime_comp    = ot_hours * (1 + ot_rate)
    # 야간근로: 가산분만 보상 (중복 적용분, 0.5배 → 1시간 야간 = 0.5시간 보상)
    night_comp       = night_hours * night_rate
    # 휴일근로(8h이내): 1.5배
    holiday_comp     = hol_hours * (1 + hol_rate)
    # 휴일근로(8h초과): 2.0배
    holiday_ot_comp  = hol_ot_hours * (1 + hol_rate + hol_ot_rate)

    total_comp = overtime_comp + night_comp + holiday_comp + holiday_ot_comp

    if ot_hours > 0:
        rate = 1 + ot_rate
        formulas.append(
            f"연장근로 보상휴가: {ot_hours}h × {rate} = {overtime_comp:.2f}h"
        )
    if night_hours > 0 and not mc.is_small:
        formulas.append(
            f"야간근로 보상휴가(가산분): {night_hours}h × {night_rate} = {night_comp:.2f}h"
        )
    if hol_hours > 0:
        rate = 1 + hol_rate
        formulas.append(
            f"휴일근로 보상휴가(8h이내): {hol_hours}h × {rate} = {holiday_comp:.2f}h"
        )
    if hol_ot_hours > 0:
        rate = 1 + hol_rate + hol_ot_rate
        formulas.append(
            f"휴일근로 보상휴가(8h초과): {hol_ot_hours}h × {rate} = {holiday_ot_comp:.2f}h"
        )

    formulas.append(f"총 보상휴가: {total_comp:.2f}h/주")

    # ── 미사용 보상휴가 수당 ─────────────────────────────────────────────
    unused_leave_pay = hourly * total_comp
    formulas.append(
        f"미사용 보상휴가 수당(주): {hourly:,.1f}원 × {total_comp:.2f}h = {unused_leave_pay:,.0f}원"
    )

    # ── 월 환산 ─────────────────────────────────────────────────────────
    monthly_unused = unused_leave_pay * WEEKS_PER_MONTH
    formulas.append(f"월 환산: {unused_leave_pay:,.0f}원 × {WEEKS_PER_MONTH:.3f}주 = {monthly_unused:,.0f}원")

    # ── 현금 수당과 비교 (참고용) ────────────────────────────────────────
    original_pay = hourly * (
        ot_hours * (1 + ot_rate)
        + night_hours * night_rate
        + hol_hours * (1 + hol_rate)
        + hol_ot_hours * (1 + hol_rate + hol_ot_rate)
    )
    # 현금 지급과 보상휴가는 동일 금액: 보상휴가 시간 × 통상시급 = 현금 수당 합계

    warnings.append("보상휴가제 도입 시 노사 서면합의 필수 (근로기준법 제57조)")
    warnings.append(
        "보상휴가 사용 기한(일반적으로 1년 이내) 내 미사용 시 미사용 수당 현금 지급 의무"
    )

    breakdown = {
        "통상시급": f"{hourly:,.1f}원",
        "연장근로 보상휴가": f"{overtime_comp:.2f}h/주",
        "야간근로 보상휴가(가산)": f"{night_comp:.2f}h/주",
        "휴일근로 보상휴가(8h이내)": f"{holiday_comp:.2f}h/주",
        "휴일근로 보상휴가(8h초과)": f"{holiday_ot_comp:.2f}h/주",
        "총 보상휴가(주)": f"{total_comp:.2f}h",
        "총 보상휴가(월 환산)": f"{total_comp * WEEKS_PER_MONTH:.2f}h",
        "미사용 보상휴가 수당(주)": f"{unused_leave_pay:,.0f}원",
        "미사용 보상휴가 수당(월)": f"{monthly_unused:,.0f}원",
        "비고": "현금 수당 = 미사용 보상휴가 수당 (동일 금액)",
    }

    return CompensatoryLeaveResult(
        compensatory_hours=round(total_comp, 2),
        overtime_comp_hours=round(overtime_comp, 2),
        night_comp_hours=round(night_comp, 2),
        holiday_comp_hours=round(holiday_comp, 2),
        holiday_ot_comp_hours=round(holiday_ot_comp, 2),
        unused_leave_pay=round(unused_leave_pay, 0),
        monthly_unused_pay=round(monthly_unused, 0),
        original_overtime_pay=round(original_pay, 0),
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )
