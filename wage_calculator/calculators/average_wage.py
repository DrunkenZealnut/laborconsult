"""
평균임금 계산기 (근로기준법 제2조)

평균임금은 퇴직금·산재보상·감급·휴업수당·실업급여 등의 기반이 됩니다.
공식: 1일 평균임금 = (3개월 임금총액 + 상여금×3/12 + 연차수당×3/12) / 3개월 총일수

■ 근로기준법 시행령 제2조
  - 평균임금이 통상임금보다 낮으면 통상임금을 평균임금으로 함

■ 참조: https://www.nodong.kr/AverageWageCal
"""

import calendar
from dataclasses import dataclass
from datetime import date

from ..base import BaseCalculatorResult
from ..models import WageInput
from ..utils import parse_date
from ..constants import AVG_WAGE_PERIOD_DAYS
from .ordinary_wage import OrdinaryWageResult


@dataclass
class AverageWageResult(BaseCalculatorResult):
    """평균임금 계산 결과"""
    avg_daily_wage: float = 0.0        # 적용 1일 평균임금 (원)
    avg_daily_3m: float = 0.0          # 3개월 기준 평균임금 (원/일)
    avg_daily_ordinary: float = 0.0    # 통상임금 환산 일급 (원/일)
    used_basis: str = ""               # 적용 기준 ("3개월" / "통상임금")
    period_days: int = 0               # 산정기간 총 일수
    wage_total: float = 0.0            # 3개월 임금총액
    bonus_addition: float = 0.0        # 상여금 가산액 (연간×3/12)
    leave_addition: float = 0.0        # 연차수당 가산액 (연간×3/12)
    grand_total: float = 0.0           # 임금총액 + 상여금 + 연차수당


def calc_average_wage(inp: WageInput, ow: OrdinaryWageResult) -> AverageWageResult:
    """
    평균임금 산정 (독립 호출 가능)

    계산 순서:
    1. 산정기간 일수 결정 (last_3m_days 또는 end_date 기반 자동 계산)
    2. 3개월 임금총액 산출 (last_3m_wages → float/dict 모두 지원)
    3. 상여금·연차수당 가산 (×3/12)
    4. 1일 평균임금 = 총액 / 총일수
    5. 통상임금 비교 → 높은 쪽 적용
    """
    warnings = []
    formulas = []
    legal = [
        "근로기준법 제2조 제1항 (평균임금 정의)",
        "근로기준법 시행령 제2조 (평균임금 < 통상임금 시 통상임금 적용)",
    ]

    # ── 1. 산정기간 일수 ───────────────────────────────────────────────────────
    period_days = _calc_period_days(inp)

    # ── 2. 3개월 임금총액 ──────────────────────────────────────────────────────
    wage_total, wage_note = _calc_wage_total(inp, ow)

    # ── 3. 상여금·연차수당 가산 ────────────────────────────────────────────────
    bonus_addition = inp.annual_bonus_total * 3 / 12 if inp.annual_bonus_total > 0 else 0
    leave_addition = inp.unused_annual_leave_pay * 3 / 12 if inp.unused_annual_leave_pay > 0 else 0

    grand_total = wage_total + bonus_addition + leave_addition

    # ── 4. 1일 평균임금 ────────────────────────────────────────────────────────
    safe_days = max(period_days, 1)  # 0 나눗셈 방지
    avg_daily_3m = grand_total / safe_days

    formulas.append(f"3개월 임금총액: {wage_total:,.0f}원{wage_note}")
    if bonus_addition > 0:
        formulas.append(
            f"상여금 가산: {inp.annual_bonus_total:,.0f}원 × 3/12 = {bonus_addition:,.0f}원"
        )
    if leave_addition > 0:
        formulas.append(
            f"연차수당 가산: {inp.unused_annual_leave_pay:,.0f}원 × 3/12 = {leave_addition:,.0f}원"
        )
    formulas.append(
        f"1일 평균임금: {grand_total:,.0f}원 ÷ {period_days}일 = {avg_daily_3m:,.0f}원"
    )

    # ── 5. 통상임금 비교 ───────────────────────────────────────────────────────
    avg_daily_ordinary = ow.daily_ordinary_wage

    if avg_daily_ordinary > avg_daily_3m:
        used_basis = "통상임금"
        avg_daily_wage = avg_daily_ordinary
        legal.append("근로기준법 시행령 제2조 (평균임금 < 통상임금 시 통상임금 적용)")
        warnings.append(
            f"평균임금({avg_daily_3m:,.0f}원/일)이 "
            f"통상임금({avg_daily_ordinary:,.0f}원/일)보다 낮아 통상임금 적용 "
            f"(근기법 시행령 제2조)"
        )
        formulas.append(
            f"통상임금 환산일급: {avg_daily_ordinary:,.0f}원/일 > 평균임금 → 통상임금 적용"
        )
    else:
        used_basis = "3개월"
        avg_daily_wage = avg_daily_3m
        formulas.append(
            f"통상임금 환산일급: {avg_daily_ordinary:,.0f}원/일 ≤ 평균임금 → 3개월 기준 적용"
        )

    # ── 결과 조립 ──────────────────────────────────────────────────────────────
    breakdown = {
        "산정기간": f"{period_days}일",
        "3개월 임금총액": f"{wage_total:,.0f}원",
    }
    if bonus_addition > 0:
        breakdown["상여금 가산"] = f"{bonus_addition:,.0f}원 (연 {inp.annual_bonus_total:,.0f}원 × 3/12)"
    if leave_addition > 0:
        breakdown["연차수당 가산"] = f"{leave_addition:,.0f}원 (연 {inp.unused_annual_leave_pay:,.0f}원 × 3/12)"
    breakdown["가산 후 총액"] = f"{grand_total:,.0f}원"
    breakdown["3개월 평균임금"] = f"{avg_daily_3m:,.0f}원/일"
    breakdown["통상임금 환산일급"] = f"{avg_daily_ordinary:,.0f}원/일"
    breakdown["적용 평균임금"] = f"{avg_daily_wage:,.0f}원/일 ({used_basis} 기준)"

    return AverageWageResult(
        avg_daily_wage=round(avg_daily_wage, 2),
        avg_daily_3m=round(avg_daily_3m, 2),
        avg_daily_ordinary=round(avg_daily_ordinary, 2),
        used_basis=used_basis,
        period_days=period_days,
        wage_total=round(wage_total, 0),
        bonus_addition=round(bonus_addition, 0),
        leave_addition=round(leave_addition, 0),
        grand_total=round(grand_total, 0),
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )


# ── 헬퍼 함수 ─────────────────────────────────────────────────────────────────

def _calc_period_days(inp: WageInput) -> int:
    """
    산정사유발생일(end_date) 기반 3개월 역산 일수 계산

    우선순위:
    1. last_3m_days 명시값
    2. end_date 기반 3개월 역산 (calendar)
    3. 기본값 AVG_WAGE_PERIOD_DAYS (92일)
    """
    if inp.last_3m_days is not None:
        return inp.last_3m_days

    end = parse_date(inp.end_date)
    if end is not None:
        month_3_ago = _subtract_months(end, 3)
        return (end - month_3_ago).days

    return AVG_WAGE_PERIOD_DAYS


def _calc_wage_total(inp: WageInput, ow: OrdinaryWageResult) -> tuple[float, str]:
    """
    3개월 임금총액 산출

    last_3m_wages 형태:
    - list[float]: [3000000, 3000000, 3000000] → sum()
    - list[dict]:  [{"base": 2500000, "allowance": 500000}, ...] → sum(base+allowance)
    - None: monthly_wage × 3 또는 통상임금 × 3 추정

    Returns:
        (total, note) — note는 계산식 부가 설명
    """
    if inp.last_3m_wages and len(inp.last_3m_wages) > 0:
        total = 0.0
        for item in inp.last_3m_wages:
            if isinstance(item, dict):
                total += float(item.get("base", 0)) + float(item.get("allowance", 0))
            else:
                total += float(item)
        return total, ""

    if inp.monthly_wage:
        return inp.monthly_wage * 3, " (월급 × 3 추정)"

    return ow.monthly_ordinary_wage * 3, " (통상임금 × 3 추정)"


def _subtract_months(d: date, months: int) -> date:
    """날짜에서 N개월 역산 (월말 보정 포함)"""
    month = d.month - months
    year = d.year
    while month <= 0:
        month += 12
        year -= 1
    max_day = calendar.monthrange(year, month)[1]
    day = min(d.day, max_day)
    return date(year, month, day)
