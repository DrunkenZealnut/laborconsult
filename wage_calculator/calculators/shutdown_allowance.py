"""
휴업수당 계산기 (근로기준법 제46조)

핵심 규칙:
- 사용자(사업주) 귀책사유 휴업: 평균임금의 70% 이상 지급
- 평균임금 70%가 통상임금 초과 → 통상임금 지급
- 부분 휴업: 미근로 시간에 대해서만 비례 지급
- 불가항력(천재지변 등) → 미발생
- 5인 미만 사업장에도 적용
"""

from dataclasses import dataclass

from ..base import BaseCalculatorResult
from ..constants import SHUTDOWN_RATE
from ..models import WageInput
from .ordinary_wage import OrdinaryWageResult


@dataclass
class ShutdownAllowanceResult(BaseCalculatorResult):
    shutdown_allowance: float = 0.0            # 휴업수당 총액
    daily_shutdown_allowance: float = 0.0      # 1일 휴업수당
    avg_wage_70_pct: float = 0.0               # 평균임금 70%
    daily_ordinary_wage: float = 0.0           # 1일 통상임금
    is_ordinary_wage_applied: bool = False     # 통상임금 적용 여부
    is_partial_shutdown: bool = False          # 부분 휴업 여부
    shutdown_days: int = 0                     # 휴업일수
    partial_ratio: float = 1.0                 # 부분 휴업 비율


def calc_shutdown_allowance(inp: WageInput, ow: OrdinaryWageResult) -> ShutdownAllowanceResult:
    """휴업수당 계산 (근로기준법 제46조)"""
    warnings = []
    formulas = []
    legal = [
        "근로기준법 제46조 (휴업수당)",
    ]

    hourly = ow.hourly_ordinary_wage
    daily_hours = inp.schedule.daily_work_hours
    ordinary_daily = hourly * daily_hours

    # 입력 검증: 휴업일수
    if inp.shutdown_days <= 0:
        return ShutdownAllowanceResult(
            breakdown={"휴업수당": "휴업일수 미입력"},
            formulas=[],
            warnings=["휴업일수가 0일입니다"],
            legal_basis=legal,
        )

    # 불가항력(천재지변 등) → 미발생
    if not inp.is_employer_fault:
        warnings.append("불가항력(천재지변 등) 휴업 — 휴업수당 미발생")
        return ShutdownAllowanceResult(
            shutdown_days=inp.shutdown_days,
            breakdown={
                "휴업수당": "미발생 (불가항력 휴업)",
                "사유": "사용자 귀책사유 아님 (천재지변 등)",
            },
            formulas=["불가항력 휴업 → 근기법 제46조 미적용"],
            warnings=warnings,
            legal_basis=legal,
        )

    # 평균임금 산정 (간이)
    avg_daily_wage = _calc_avg_daily_wage(inp, hourly, daily_hours)

    avg_70 = avg_daily_wage * SHUTDOWN_RATE
    formulas.append(
        f"1일 평균임금: {avg_daily_wage:,.0f}원"
    )
    formulas.append(
        f"평균임금 70%: {avg_daily_wage:,.0f}원 × {SHUTDOWN_RATE} = {avg_70:,.0f}원"
    )
    formulas.append(
        f"1일 통상임금: {hourly:,.0f}원 × {daily_hours}h = {ordinary_daily:,.0f}원"
    )

    # 근기법 제46조 제2항: 70%가 통상임금 초과 시 통상임금 적용
    if avg_70 > ordinary_daily:
        daily_allowance = ordinary_daily
        is_ordinary_applied = True
        formulas.append(
            f"평균임금 70%({avg_70:,.0f}원) > 통상임금({ordinary_daily:,.0f}원) → 통상임금 적용"
        )
        legal.append("근로기준법 제46조 제2항 (통상임금 적용 기준)")
    else:
        daily_allowance = avg_70
        is_ordinary_applied = False
        formulas.append(
            f"평균임금 70%({avg_70:,.0f}원) ≤ 통상임금({ordinary_daily:,.0f}원) → 평균임금 70% 적용"
        )

    # 부분 휴업 처리
    is_partial = False
    partial_ratio = 1.0
    if inp.shutdown_hours_per_day is not None and daily_hours > 0:
        partial_ratio = inp.shutdown_hours_per_day / daily_hours
        if partial_ratio < 1.0:
            is_partial = True
            daily_allowance = daily_allowance * partial_ratio
            formulas.append(
                f"부분 휴업: {inp.shutdown_hours_per_day}h / {daily_hours}h = {partial_ratio:.1%} "
                f"→ 1일 휴업수당 {daily_allowance:,.0f}원"
            )
            warnings.append(
                f"부분 휴업: 1일 {inp.shutdown_hours_per_day}h 미근로 / "
                f"{daily_hours}h 소정근로 ({partial_ratio:.0%})"
            )

    # 총액
    total = daily_allowance * inp.shutdown_days
    formulas.append(
        f"휴업수당 총액: {daily_allowance:,.0f}원 × {inp.shutdown_days}일 = {total:,.0f}원"
    )

    breakdown = {
        "1일 평균임금": f"{avg_daily_wage:,.0f}원",
        "평균임금 70%": f"{avg_70:,.0f}원",
        "1일 통상임금": f"{ordinary_daily:,.0f}원",
        "적용 기준": "통상임금" if is_ordinary_applied else "평균임금 70%",
        "1일 휴업수당": f"{daily_allowance:,.0f}원",
        "휴업일수": f"{inp.shutdown_days}일",
        "휴업수당 총액": f"{total:,.0f}원",
    }
    if is_partial:
        breakdown["부분 휴업"] = (
            f"1일 {inp.shutdown_hours_per_day}h / {daily_hours}h = {partial_ratio:.0%}"
        )

    return ShutdownAllowanceResult(
        shutdown_allowance=round(total, 0),
        daily_shutdown_allowance=round(daily_allowance, 0),
        avg_wage_70_pct=round(avg_70, 0),
        daily_ordinary_wage=round(ordinary_daily, 0),
        is_ordinary_wage_applied=is_ordinary_applied,
        is_partial_shutdown=is_partial,
        shutdown_days=inp.shutdown_days,
        partial_ratio=round(partial_ratio, 4),
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )


def _calc_avg_daily_wage(inp: WageInput, hourly: float, daily_hours: float) -> float:
    """평균임금 간이 산정 (3개월 기준)"""
    if inp.last_3m_wages:
        total_3m = sum(inp.last_3m_wages)
        days_3m = inp.last_3m_days or 92
        return total_3m / days_3m

    # monthly_wage 기반 추정
    if inp.monthly_wage:
        return (inp.monthly_wage * 3) / 92

    # hourly 기반 추정
    monthly_est = hourly * daily_hours * inp.schedule.weekly_work_days * (52 / 12)
    return (monthly_est * 3) / 92
