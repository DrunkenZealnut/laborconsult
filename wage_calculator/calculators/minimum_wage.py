"""
최저임금 검증 계산기 (최저임금법 제6조)

수요: 741건 (28.5%) — 두 번째로 많은 임금 관련 질문 유형

산입범위 규칙 (최저임금법 제6조제4항, 2019년 개정):
┌──────────────────────┬────────────────────────────────────────────────────┐
│ 항목                  │ 처리 방법                                           │
├──────────────────────┼────────────────────────────────────────────────────┤
│ 기본급               │ 전액 산입                                            │
│ 일반 고정수당         │ 전액 산입 (min_wage_type="standard" 또는 미설정)     │
│ 정기상여금            │ 법정 최저 월액의 N% 초과분만 산입 (2024+: 전액)      │
│ 복리후생비            │ 법정 최저 월액의 M% 초과분만 산입 (2024+: 전액)      │
│ 연장/야간/휴일수당     │ 비산입 (min_wage_type="excluded")                   │
└──────────────────────┴────────────────────────────────────────────────────┘

fixed_allowances 항목에 min_wage_type 키로 명시 가능:
  "standard"      → 전액 산입 (기본값)
  "regular_bonus" → 정기상여금 산입범위 적용
  "welfare"       → 복리후생비 산입범위 적용
  "excluded"      → 비산입 (연장/야간/휴일 등)
미설정 시 수당 이름으로 자동 추론.
"""

from dataclasses import dataclass

from ..base import BaseCalculatorResult
from ..models import WageInput, WageType
from .ordinary_wage import OrdinaryWageResult
from .shared import normalize_allowances, AllowanceClassifier
from ..constants import (
    MINIMUM_HOURLY_WAGE,
    PROBATION_MIN_WAGE_RATE,
    get_min_wage_inclusion_rates,
)


@dataclass
class MinimumWageResult(BaseCalculatorResult):
    is_compliant: bool = False         # 최저임금 충족 여부
    effective_hourly: float = 0.0      # 실질 시급 (원)
    legal_minimum: float = 0.0         # 법정 최저임금 (원)
    shortage_monthly: float = 0.0      # 부족분 월액 (충족 시 0)
    reference_year: int = 0            # 기준 연도
    monthly_hours_used: float = 0.0    # 적용된 월 근로시간


def calc_minimum_wage(inp: WageInput, ow: OrdinaryWageResult) -> MinimumWageResult:
    """
    최저임금 충족 여부 및 부족분 계산 (산입범위 정확 반영)

    Args:
        inp: 임금 입력 데이터
        ow:  통상임금 계산 결과 (월 기준시간 참조용)
    """
    year = inp.reference_year
    warnings: list = []
    formulas: list = []
    legal:    list = ["최저임금법 제6조 (최저임금의 효력)"]

    # ── 기준 연도 최저임금 ────────────────────────────────────────────────────
    if year not in MINIMUM_HOURLY_WAGE:
        year = max(MINIMUM_HOURLY_WAGE.keys())
        warnings.append(f"{inp.reference_year}년 최저임금 미확정 — {year}년 기준 적용")
    legal_minimum = float(MINIMUM_HOURLY_WAGE[year])

    # ── 수습기간 특례 ─────────────────────────────────────────────────────────
    if inp.is_probation:
        adjusted = legal_minimum * PROBATION_MIN_WAGE_RATE
        warnings.append(
            f"수습기간 ({inp.probation_months}개월) 최저임금 특례 적용: "
            f"{legal_minimum:,.0f}원 × 90% = {adjusted:,.0f}원"
        )
        formulas.append(
            f"수습 최저임금: {legal_minimum:,.0f}원 × 0.9 = {adjusted:,.0f}원"
        )
        legal.append("최저임금법 제5조제2항 (수습 사용 중인 근로자)")
        legal_minimum = adjusted

    monthly_hours = ow.monthly_base_hours

    # ── 산입범위 제외율 조회 ──────────────────────────────────────────────────
    bonus_excl_rate, welfare_excl_rate = get_min_wage_inclusion_rates(year)

    # 법정 최저임금 월액 (제외기준 계산용 — 최저임금법 시행령 제5조의2)
    legal_monthly_ref = legal_minimum * 209.0

    # ── 1. 기본급 월액 ────────────────────────────────────────────────────────
    base_monthly = _get_base_monthly(inp, monthly_hours)

    # ── 2. 고정수당 분류 ──────────────────────────────────────────────────────
    std_included   = 0.0
    bonus_total    = 0.0
    welfare_total  = 0.0
    allowance_rows: list[tuple[str, float, str]] = []   # (name, monthly, label)

    for a in normalize_allowances(inp.fixed_allowances):
        monthly_amt = _monthly_amount_fa(a)
        mwt         = AllowanceClassifier.classify_min_wage_type(a.name, a.min_wage_type)
        name        = a.name

        if mwt == "excluded":
            allowance_rows.append((name, monthly_amt, "비산입(초과수당)"))
        elif mwt == "regular_bonus":
            bonus_total += monthly_amt
            allowance_rows.append((name, monthly_amt, "정기상여금"))
        elif mwt == "welfare":
            welfare_total += monthly_amt
            allowance_rows.append((name, monthly_amt, "복리후생비"))
        else:
            std_included += monthly_amt
            allowance_rows.append((name, monthly_amt, "전액산입"))

    # ── 3. 정기상여금 산입 계산 ───────────────────────────────────────────────
    bonus_excl_threshold = legal_monthly_ref * bonus_excl_rate
    bonus_included       = max(0.0, bonus_total - bonus_excl_threshold)

    # ── 4. 복리후생비 산입 계산 ───────────────────────────────────────────────
    welfare_excl_threshold = legal_monthly_ref * welfare_excl_rate
    welfare_included       = max(0.0, welfare_total - welfare_excl_threshold)

    # ── 5. 총 산입 월 임금 및 실질 시급 ──────────────────────────────────────
    included_monthly = base_monthly + std_included + bonus_included + welfare_included
    effective_hourly = included_monthly / monthly_hours

    is_compliant    = effective_hourly >= legal_minimum
    shortage_hourly = max(0.0, legal_minimum - effective_hourly)
    shortage_monthly = shortage_hourly * monthly_hours

    # ── formulas ──────────────────────────────────────────────────────────────
    formulas.append(f"기본급 월액: {base_monthly:,.0f}원")
    if std_included:
        formulas.append(f"전액산입 수당 합계: {std_included:,.0f}원")

    if bonus_total:
        if bonus_excl_rate > 0:
            legal.append("최저임금법 제6조제4항 제1호 (정기상여금 산입범위)")
            formulas.append(
                f"정기상여금 산입: {bonus_total:,.0f}원 − 제외기준 {bonus_excl_threshold:,.0f}원 "
                f"(법정 최저월액 {legal_monthly_ref:,.0f}원 × {bonus_excl_rate:.0%}) "
                f"= {bonus_included:,.0f}원"
            )
        else:
            formulas.append(f"정기상여금 전액산입 ({year}년~): {bonus_total:,.0f}원")

    if welfare_total:
        if welfare_excl_rate > 0:
            legal.append("최저임금법 제6조제4항 제2호 (복리후생비 산입범위)")
            formulas.append(
                f"복리후생비 산입: {welfare_total:,.0f}원 − 제외기준 {welfare_excl_threshold:,.0f}원 "
                f"(법정 최저월액 × {welfare_excl_rate:.0%}) "
                f"= {welfare_included:,.0f}원"
            )
        else:
            formulas.append(f"복리후생비 전액산입 ({year}년~): {welfare_total:,.0f}원")

    formulas.append(
        f"실질시급: {included_monthly:,.0f}원 ÷ {monthly_hours}h = {effective_hourly:,.2f}원"
    )
    formulas.append(f"{year}년 최저임금: {legal_minimum:,.0f}원/h")

    if not is_compliant:
        warnings.append(
            f"최저임금 미달: 실질시급 {effective_hourly:,.0f}원 < {legal_minimum:,.0f}원 "
            f"(부족분 {shortage_hourly:,.0f}원/h, 월 {shortage_monthly:,.0f}원)"
        )
        legal.append("최저임금법 제6조제1항 위반 가능성 — 노동청 신고 가능")
    else:
        formulas.append(
            f"충족: {effective_hourly:,.0f}원 ≥ {legal_minimum:,.0f}원 "
            f"(초과 {effective_hourly - legal_minimum:,.0f}원/h)"
        )

    # ── breakdown ─────────────────────────────────────────────────────────────
    breakdown: dict = {
        f"{year}년 법정 최저시급": f"{legal_minimum:,.0f}원",
        "실질 시급":              f"{effective_hourly:,.0f}원",
        "충족 여부":              "✅ 충족" if is_compliant else "❌ 미달",
        "월 근로시간":            f"{monthly_hours}h",
        "기본급 월액":            f"{base_monthly:,.0f}원",
    }
    if std_included:
        breakdown["전액산입 수당"] = f"{std_included:,.0f}원"
    if bonus_total:
        breakdown["정기상여금 (월 환산)"] = f"{bonus_total:,.0f}원"
        if bonus_excl_rate > 0:
            breakdown["  ├ 제외 기준액"] = (
                f"{bonus_excl_threshold:,.0f}원 ({bonus_excl_rate:.0%})"
            )
        breakdown["  └ 실제 산입액"] = f"{bonus_included:,.0f}원"
    if welfare_total:
        breakdown["복리후생비 (월 환산)"] = f"{welfare_total:,.0f}원"
        if welfare_excl_rate > 0:
            breakdown["  ├ 제외 기준액 "] = (
                f"{welfare_excl_threshold:,.0f}원 ({welfare_excl_rate:.0%})"
            )
        breakdown["  └ 실제 산입액 "] = f"{welfare_included:,.0f}원"
    breakdown["산입 월 임금 합계"] = f"{included_monthly:,.0f}원"
    breakdown["부족분(월)"] = f"{shortage_monthly:,.0f}원" if shortage_monthly > 0 else "-"

    if allowance_rows:
        breakdown["── 수당 산입 내역 ──"] = ""
        for name, amt, label in allowance_rows:
            breakdown[f"  {name}"] = f"{amt:,.0f}원/월  [{label}]"

    return MinimumWageResult(
        is_compliant=is_compliant,
        effective_hourly=round(effective_hourly, 0),
        legal_minimum=round(legal_minimum, 0),
        shortage_monthly=round(shortage_monthly, 0),
        reference_year=year,
        monthly_hours_used=monthly_hours,
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=list(dict.fromkeys(legal)),
    )


# ── 헬퍼 함수 ─────────────────────────────────────────────────────────────────

def _get_base_monthly(inp: WageInput, monthly_hours: float) -> float:
    """기본급만 월 환산 (fixed_allowances 미포함)"""
    if inp.wage_type == WageType.HOURLY:
        return (inp.hourly_wage or 0.0) * monthly_hours
    elif inp.wage_type == WageType.DAILY:
        daily = inp.daily_wage or 0.0
        dh    = inp.schedule.daily_work_hours or 8.0
        return (daily / dh) * monthly_hours
    elif inp.wage_type in (WageType.MONTHLY, WageType.COMPREHENSIVE):
        if inp.wage_type == WageType.COMPREHENSIVE and inp.comprehensive_breakdown:
            return float(inp.comprehensive_breakdown.get("base", inp.monthly_wage or 0.0))
        return inp.monthly_wage or 0.0
    elif inp.wage_type == WageType.ANNUAL:
        return (inp.annual_wage or 0.0) / 12
    return 0.0


def _monthly_amount_fa(a) -> float:
    """수당 월 환산 금액 — FixedAllowance 속성 접근"""
    amount = a.amount
    cycle = a.payment_cycle
    if a.annual or cycle == "연":
        return amount / 12
    elif cycle == "분기":
        return amount / 3
    elif cycle == "반기":
        return amount / 6
    return amount
