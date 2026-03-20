"""소정근로시간 계산기

주·월·연 소정근로시간 산출 + 시급↔월급 환산.

핵심 공식:
- 주 소정근로시간 = 1일 소정근로시간 × 주 근무일수
- 월 소정근로시간 = (주 소정근로시간 + 유급주휴시간) × 365 / 12 / 7
  → 8h × 5일 + 8h(주휴) = 48h → 48 × 365/12/7 ≈ 208.57 → 약 209시간
- 연 소정근로시간 = 주 소정근로시간 × 52주
"""

from dataclasses import dataclass

from ..base import BaseCalculatorResult
from ..models import WageInput
from .ordinary_wage import OrdinaryWageResult


@dataclass
class WorkingHoursResult(BaseCalculatorResult):
    weekly_hours: float = 0.0          # 주 소정근로시간
    weekly_paid_hours: float = 0.0     # 주 유급시간 (주휴 포함)
    monthly_hours: float = 0.0         # 월 소정근로시간
    annual_hours: float = 0.0          # 연 소정근로시간
    hourly_wage: float = 0.0           # 시급 (환산)
    monthly_wage: float = 0.0          # 월급 (환산)


def calc_working_hours(inp: WageInput, ow: OrdinaryWageResult) -> WorkingHoursResult:
    """소정근로시간 계산 + 시급↔월급 환산"""
    daily = inp.schedule.daily_work_hours
    weekly_days = inp.schedule.weekly_work_days
    warnings = []
    formulas = []
    legal = ["근로기준법 제2조 제1항 제8호 (소정근로시간)"]

    # ── 주 소정근로시간 ──
    weekly_hours = daily * weekly_days

    # ── 유급주휴시간 ──
    if weekly_hours >= 15:
        paid_holiday_hours = daily
        legal.append("근로기준법 제55조 (유급주휴일)")
    else:
        paid_holiday_hours = 0
        warnings.append("주 소정근로시간 15시간 미만: 주휴일 미발생")

    weekly_paid = weekly_hours + paid_holiday_hours

    # ── 월 소정근로시간 ──
    monthly_hours = round(weekly_paid * (365 / 12 / 7), 2)
    formulas.append(
        f"월 소정근로시간 = ({weekly_hours} + {paid_holiday_hours}) × 365/12/7 "
        f"= {monthly_hours:.2f}시간"
    )

    # ── 연 소정근로시간 ──
    annual_hours = round(weekly_hours * 52, 1)

    # ── 시급 ↔ 월급 환산 ──
    hourly = ow.hourly_ordinary_wage
    monthly_from_hourly = round(hourly * monthly_hours) if hourly else 0

    breakdown = {
        "1일 소정근로시간": f"{daily}시간",
        "주 소정근무일수": f"{weekly_days}일",
        "주 소정근로시간": f"{weekly_hours}시간",
        "유급주휴시간": f"{paid_holiday_hours}시간",
        "주 유급시간 합계": f"{weekly_paid}시간",
        "월 소정근로시간": f"{monthly_hours}시간",
        "연 소정근로시간": f"{annual_hours}시간",
    }

    if hourly:
        breakdown["시급"] = f"{hourly:,.0f}원"
        breakdown["월급 환산"] = f"{monthly_from_hourly:,.0f}원 (시급 × 월 소정근로시간)"
        formulas.append(
            f"월급 환산 = {hourly:,.0f} × {monthly_hours} = {monthly_from_hourly:,.0f}원"
        )

    return WorkingHoursResult(
        weekly_hours=weekly_hours,
        weekly_paid_hours=weekly_paid,
        monthly_hours=monthly_hours,
        annual_hours=annual_hours,
        hourly_wage=hourly or 0,
        monthly_wage=monthly_from_hourly,
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )
