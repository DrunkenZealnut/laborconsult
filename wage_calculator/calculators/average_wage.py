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
from datetime import date, timedelta

from ..base import BaseCalculatorResult
from ..models import WageInput, WageType
from ..utils import parse_date
from .shared import monthly_wage_note, monthly_wage_total
from ..constants import AVG_WAGE_PERIOD_DAYS
from .ordinary_wage import OrdinaryWageResult
from .pay_inputs import PayInputError, validate_average_inputs, validated_exclusions, bonus_already_included


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
    try:
        validate_average_inputs(inp)
        return _calculate_average_wage(inp, ow)
    except PayInputError as exc:
        return AverageWageResult(held_reason=str(exc), warnings=[str(exc)])


def _calculate_average_wage(inp: WageInput, ow: OrdinaryWageResult) -> AverageWageResult:
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
        "근로기준법 제2조 제2항 (평균임금이 통상임금보다 적으면 통상임금)",
    ]

    # ── 1. 산정기간 일수 (제외 기간 반영) ──────────────────────────────────────
    full_days = _calc_period_days(inp)
    excluded_days, excluded_wages = _calc_excluded(inp, full_days)
    period_days = max(full_days - excluded_days, 1)

    # ── 2. 3개월 임금총액 (제외 임금 차감) ──────────────────────────────────────
    wage_total, wage_note = _calc_wage_total(inp, ow)
    included_bonus = bonus_already_included(inp, ow)
    if included_bonus > wage_total:
        raise PayInputError("이미 포함된 상여가 3개월 임금총액보다 큽니다.")
    if included_bonus:
        wage_total -= included_bonus
        wage_note = " (동일 연 상여 중복 조정 후)"
        formulas.append(f"동일 연 상여 중복 조정: 3개월 임금에 포함된 {included_bonus:,.0f}원 제외 후 연간 배분액 산입")
    if excluded_days > 0:
        if not inp.last_3m_wages:
            # 추정 총액(기준 월액 × 3)은 제외 기간에도 평소 임금을 받은 것으로 센 값이다 — 그 기간의 몫을 일수 비율로 뺀다. 실제로
            # 받은 금액(paid)을 빼면 평소 임금이 남아 평균임금이 부풀었다(독립 리뷰 M3: 월 300만·제외 30일 97,826 → 145,161원)
            excluded_wages = wage_total * min(excluded_days, full_days) / full_days
        share = "추정 총액의 그 기간 몫, " if not inp.last_3m_wages else ""
        formulas.append(f"산정기간 제외: {excluded_days}일, 제외 임금: {excluded_wages:,.0f}원 ({share}근기법 시행령 제2조)")
    if excluded_wages > wage_total:
        raise PayInputError("제외 기간 지급액이 3개월 임금총액보다 큽니다.")
    wage_total -= excluded_wages
    if excluded_days > 0:
        legal.append("근로기준법 시행령 제2조 제1항 (평균임금 산정 제외 기간)")

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
        legal.append("근로기준법 제2조 제2항 (평균임금이 통상임금보다 적으면 통상임금)")
        warnings.append(
            f"평균임금({avg_daily_3m:,.0f}원/일)이 "
            f"통상임금({avg_daily_ordinary:,.0f}원/일)보다 낮아 통상임금 적용 "
            f"(근로기준법 제2조 제2항)"
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
    - None: 기준 월액(shared.monthly_wage_total) × 3 추정

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

    # 기준 월액 × 3 — 카드의 '월 총 예상 수령액'·보험 세전과 같은 함수다(shared.monthly_wage_total: 주어진 총액 우선, 통상임금에서
    # 뺀 고정수당·연장 등 포함)
    note = monthly_wage_note(inp, ow)
    # 월급제에 통상임금 포함 수당이 없으면 그 통상임금이 곧 월급이다 — 예전 표기('월급 × 3')를 지킨다(Check G-1)
    if (note.startswith("통상임금") and inp.wage_type == WageType.MONTHLY and inp.monthly_wage
            and abs(ow.monthly_ordinary_wage - inp.monthly_wage) < 1):
        note = "월급" + note[len("통상임금"):]
    return monthly_wage_total(inp, ow) * 3, f" ({f'({note})' if ' + ' in note else note} × 3 추정)"


def _calc_excluded(inp: WageInput, period_days: int) -> tuple[int, float]:
    return validated_exclusions(inp, period_days)


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
