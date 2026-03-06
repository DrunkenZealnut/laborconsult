"""
유급 공휴일 계산 (근로기준법 제55조 제2항)

법정공휴일을 유급으로 보장하는 규정 (단계별 적용):
  - 300인 이상: 2020.01.01부터
  - 30인 이상:  2021.01.01부터
  - 5인 이상:   2022.01.01부터
  - 5인 미만:   미적용 (취업규칙·단체협약에 따름)

비근무 공휴일 수당 = 통상시급 × 1일 소정근로시간
"""

from dataclasses import dataclass

from ..base import BaseCalculatorResult
from datetime import date as date_cls

from ..models import WageInput, BusinessSize
from .ordinary_wage import OrdinaryWageResult


# 규모별 유급 공휴일 적용 시작일 (근로기준법 부칙)
PUBLIC_HOLIDAY_APPLY_DATE: dict[str, date_cls] = {
    "300인이상": date_cls(2020, 1, 1),
    "30인이상":  date_cls(2021, 1, 1),
    "5인이상":   date_cls(2022, 1, 1),
}


@dataclass
class PublicHolidayResult(BaseCalculatorResult):
    holiday_pay_per_day: float = 0.0  # 공휴일 1일 수당 (원)
    holiday_days: int = 0             # 비근무 공휴일 일수
    total_holiday_pay: float = 0.0    # 총 공휴일 수당 (원)
    eligible: bool = False            # 유급공휴일 적용 대상 여부


def calc_public_holiday(
    inp: WageInput,
    ow: OrdinaryWageResult,
    holiday_days: int | None = None,
) -> PublicHolidayResult:
    """
    유급 공휴일 수당 계산

    Args:
        holiday_days: 비근무 유급 공휴일 일수 (None이면 inp.public_holiday_days 사용)
    """
    warnings = []
    formulas = []
    legal = ["근로기준법 제55조 제2항 (관공서 공휴일의 유급휴일 보장)"]

    n_days = holiday_days if holiday_days is not None else inp.public_holiday_days
    if n_days <= 0:
        n_days = 1  # 기본 1일

    hourly = ow.hourly_ordinary_wage
    daily_hours = inp.schedule.daily_work_hours or 8.0

    # 적용 대상 여부
    ref_date = date_cls(inp.reference_year, 1, 1)
    eligible = _check_eligibility(inp.business_size, ref_date)

    if not eligible:
        reason = (
            "5인 미만 사업장 — 유급공휴일 미적용"
            if inp.business_size == BusinessSize.UNDER_5
            else f"{inp.reference_year}년 기준 해당 규모 적용 시작일 이전"
        )
        warnings.append(f"유급공휴일 미적용: {reason}")
        return PublicHolidayResult(
            holiday_pay_per_day=0,
            holiday_days=n_days,
            total_holiday_pay=0,
            eligible=False,
            breakdown={"적용여부": f"미적용 ({reason})"},
            formulas=[],
            warnings=warnings,
            legal_basis=legal,
        )

    pay_per_day = hourly * daily_hours
    total_pay = pay_per_day * n_days

    formulas.append(
        f"공휴일 수당: {hourly:,.0f}원 × {daily_hours}h × {n_days}일 = {total_pay:,.0f}원"
    )

    breakdown = {
        "통상시급": f"{hourly:,.0f}원",
        "1일 소정근로시간": f"{daily_hours}h",
        "공휴일 1일 수당": f"{pay_per_day:,.0f}원",
        "비근무 공휴일 일수": f"{n_days}일",
        "총 공휴일 수당": f"{total_pay:,.0f}원",
    }

    return PublicHolidayResult(
        holiday_pay_per_day=round(pay_per_day, 0),
        holiday_days=n_days,
        total_holiday_pay=round(total_pay, 0),
        eligible=True,
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )


def _check_eligibility(business_size: BusinessSize, reference_date: date_cls) -> bool:
    """유급공휴일 적용 대상 여부 판단"""
    if business_size == BusinessSize.UNDER_5:
        return False
    if business_size == BusinessSize.OVER_300:
        return reference_date >= PUBLIC_HOLIDAY_APPLY_DATE["300인이상"]
    if business_size == BusinessSize.OVER_30:
        return reference_date >= PUBLIC_HOLIDAY_APPLY_DATE["30인이상"]
    # OVER_5
    return reference_date >= PUBLIC_HOLIDAY_APPLY_DATE["5인이상"]
