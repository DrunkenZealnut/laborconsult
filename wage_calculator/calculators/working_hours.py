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
from ..constants import WEEKLY_HOLIDAY_MIN_HOURS
from ..utils import fmt_hours
from ..models import WageInput
from .ordinary_wage import OrdinaryWageResult
from .shared import split_note, weekly_holiday_hours


@dataclass
class WorkingHoursResult(BaseCalculatorResult):
    weekly_hours: float = 0.0          # 주 소정근로시간
    weekly_paid_hours: float = 0.0     # 주 유급시간 (주휴 포함)
    monthly_hours: float = 0.0         # 월 소정근로시간
    annual_hours: float = 0.0          # 연 소정근로시간
    hourly_wage: float = 0.0           # 시급 (환산)
    monthly_wage: float = 0.0          # 월급 (환산)


def calc_working_hours(inp: WageInput, ow: OrdinaryWageResult) -> WorkingHoursResult:
    """소정근로시간 계산 + 시급↔월급 환산.

    월 소정근로시간은 통상임금 계산기(ordinary_wage._get_base_hours)가 산출한
    ow.monthly_base_hours를 단일 출처로 사용한다. 과거 이 계산기는 주휴시간을
    daily(상한 미적용)로 잡아 통상임금 계산기와 다른 월 소정근로시간을 산출했고,
    두 값이 한 답변에 함께 노출되는 불일치가 있었다. 주휴시간도 같은 함수
    (shared.weekly_holiday_hours, 대법원 2022다291153)로 구한다.
    """
    daily = inp.schedule.daily_work_hours
    weekly_days = inp.schedule.weekly_work_days
    warnings = []
    formulas = []
    legal = ["근로기준법 제2조 제1항 제8호 (소정근로시간)"]

    # ── 주 소정근로시간 ──
    weekly_hours = daily * weekly_days

    # ── 유급주휴시간 (통상임금 기준시간·주휴수당과 같은 함수, 대법원 2022다291153) ──
    if weekly_hours >= WEEKLY_HOLIDAY_MIN_HOURS:
        paid_holiday_hours, _ = weekly_holiday_hours(weekly_days, daily)
        legal.append("근로기준법 제55조 (유급주휴일)")
    else:
        paid_holiday_hours = 0.0
        warnings.append("주 소정근로시간 15시간 미만: 주휴일 미발생")

    weekly_paid = weekly_hours + paid_holiday_hours

    # ── 월 소정근로시간: 통상임금 기준시간을 단일 출처로 사용 (불일치 방지) ──
    # 산출 근거(ow.base_hours_detail)는 facade가 "[기준시간]" 계산식으로 이미 노출하므로
    # 여기서는 결과값만 명시해 중복을 피한다.
    monthly_hours = ow.monthly_base_hours
    formulas.append(f"월 소정근로시간(주휴 포함) = {fmt_hours(monthly_hours)}시간")
    # 1일 8시간·1주 40시간을 넘는 시간은 소정근로가 아니다(근로기준법 제2조 제1항 제8호·제50조) — 따로 밝힌다
    split = getattr(inp, "hour_split", None)
    overtime_hours = split.excess if split is not None and split.mode == "applied" else 0.0
    if overtime_hours:
        formulas.append(f"1주 연장근로 {fmt_hours(overtime_hours)}시간 — 소정근로 아님({split_note(split)})")
        legal.append("근로기준법 제50조 (근로시간)")

    # ── 연 소정근로시간 (주휴 제외, 순수 근로시간) ──
    annual_contractual_hours = round(weekly_hours * 52, 1)

    # ── 통상시급 ↔ 월급 환산 ──
    hourly = ow.hourly_ordinary_wage
    # 통상시급은 소수 둘째 자리로 저장돼 시급 × 시간으로 되돌리면 1원 어긋난다(2,700,001원) — 월 통상임금을 그대로 쓴다
    monthly_from_hourly = round(ow.monthly_ordinary_wage) if hourly else 0

    breakdown = {
        "1일 소정근로시간": f"{fmt_hours(daily)}시간",
        "주 소정근무일수": f"{fmt_hours(weekly_days)}일",
        "주 소정근로시간": f"{fmt_hours(weekly_hours)}시간",
        "유급주휴시간": f"{fmt_hours(paid_holiday_hours)}시간",
        "주 유급시간 합계": f"{fmt_hours(weekly_paid)}시간",
        "월 소정근로시간 (주휴 포함)": f"{fmt_hours(monthly_hours)}시간",
        "연 소정근로시간 (주휴 제외)": f"{annual_contractual_hours}시간",
    }
    if overtime_hours:
        breakdown["주 연장근로시간 (소정근로 아님)"] = f"{fmt_hours(overtime_hours)}시간"

    if hourly:
        breakdown["통상시급"] = f"{hourly:,.0f}원"
        breakdown["통상시급 기준 월급 환산"] = f"{monthly_from_hourly:,.0f}원"
        formulas.append(
            f"월급 환산 = 통상시급 {hourly:,.2f} × {fmt_hours(monthly_hours)}h = {monthly_from_hourly:,.0f}원"
        )

    return WorkingHoursResult(
        weekly_hours=weekly_hours,
        weekly_paid_hours=weekly_paid,
        monthly_hours=monthly_hours,
        annual_hours=annual_contractual_hours,
        hourly_wage=hourly or 0,
        monthly_wage=monthly_from_hourly,
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )
