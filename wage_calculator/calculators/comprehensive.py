"""
포괄임금제 역산 계산기

포괄임금제: 기본급에 연장·야간·휴일수당 등을 포함하여 지급하는 계약 형태.
가산율을 반영한 총계수시간으로 기본시급을 역산하여 최저임금 충족 여부와
수당별 적정액을 검증합니다.

■ 역산 공식 (대법원 2020다300299 반영)
  기본시급 = 포괄임금 총액 ÷ 총계수시간
  총계수시간 = 기본시간 + 연장×1.5 + 야간×0.5 + 휴일8h이내×1.5 + 휴일8h초과×2.0

■ 5인 미만 사업장 (근기법 제56조 적용 제외)
  가산수당 미적용: 연장×1.0, 야간×0.0, 휴일×1.0, 휴일OT×1.0

■ 포괄임금제 유효 요건 (판례)
  - 근로시간 산정이 객관적으로 곤란할 것 (대법원 2008다6052)
  - 교대제·일급·시급 근로자에게는 적용 불가 (대법원 2014도8873)
  - 당사자 간 명확한 합의 필요 (대법원 2008다57852)

핵심 처리:
1. breakdown 있는 경우: 항목별 분리 → 역산 검증 + 수당별 적정액 비교
2. breakdown 없는 경우: 총액에서 역산 → 기본시급·수당 분리
"""

from dataclasses import dataclass, field

from ..base import BaseCalculatorResult
from ..models import WageInput, WageType, WorkType
from .ordinary_wage import OrdinaryWageResult
from .shared import MultiplierContext
from ..constants import MINIMUM_HOURLY_WAGE

# 주 → 월 환산 계수
WEEKS_PER_MONTH = 365 / 7 / 12  # ≈ 4.345


@dataclass
class ComprehensiveResult(BaseCalculatorResult):
    base_wage: float = 0.0                                    # 역산 기본급 (월)
    effective_hourly: float = 0.0                             # 역산 통상시급
    included_allowances: dict = field(default_factory=dict)   # 포함 수당 내역
    is_minimum_wage_ok: bool = False                          # 최저임금 충족 여부
    legal_minimum: float = 0.0                                # 법정 최저임금
    shortage: float = 0.0                                     # 월 부족분
    # 신규 필드
    total_coefficient_hours: float = 0.0                      # 총계수시간 (월)
    allowance_comparison: dict = field(default_factory=dict)  # 수당별 적정액 vs 포함액
    is_valid_comprehensive: bool = True                       # 포괄임금제 유효성
    validity_issues: list = field(default_factory=list)       # 유효성 문제 목록


def calc_comprehensive(inp: WageInput, ow: OrdinaryWageResult) -> ComprehensiveResult:
    """포괄임금제 역산 및 적법성 검토"""
    warnings = []
    formulas = []
    legal = [
        "근로기준법 제56조 (연장·야간·휴일 근로)",
        "대법원 2024.12.26. 선고 2020다300299 (포괄임금 최저임금 판단 계산방법)",
        "대법원 2023.11.30. 선고 2019다29778 (연차수당 포함 시 법정 미달분 무효)",
        "대법원 2016.9.8. 선고 2014도8873 (근로시간 산정 곤란 요건)",
        "대법원 2010.5.13. 선고 2008다6052 (근로시간 계산 어렵지 않으면 포괄임금 불허)",
        "대법원 2009.12.10. 선고 2008다57852 (포괄임금제 성립 판단방법)",
        "대법원 1998.3.24. 선고 96다24699 (연차수당 포괄 포함 가능 여부)",
        "근로기준정책과-818 (2022.3.8, 포괄임금제 임금명세서 작성방법)",
    ]

    # ── 최저임금 기준 ──────────────────────────────────────────────────────────
    year = inp.reference_year
    if year not in MINIMUM_HOURLY_WAGE:
        year = max(MINIMUM_HOURLY_WAGE.keys())
    legal_minimum = MINIMUM_HOURLY_WAGE[year]

    # ── 1. 유효성 판단 ─────────────────────────────────────────────────────────
    is_valid, validity_issues = _check_validity(inp)
    if not is_valid:
        for issue in validity_issues:
            warnings.append(issue)

    # ── 2. 총계수시간 산출 ─────────────────────────────────────────────────────
    total_coeff, coeff_detail = _calc_coefficient_hours(inp)
    formulas.append(f"총계수시간(월): {total_coeff:.1f}h")
    for k, v in coeff_detail.items():
        if v > 0:
            formulas.append(f"  {k}: {v:.1f}h")

    # ── 3. 역산 대상 총액 산출 ─────────────────────────────────────────────────
    bd = inp.comprehensive_breakdown
    included_allowances = {}
    allowance_comparison = {}

    if bd:
        # 경로 2: 기본급 + 수당 구분
        base = float(bd.get("base", 0))
        ot_pay = float(bd.get("overtime_pay", 0))
        night_pay = float(bd.get("night_pay", 0))
        holiday_pay = float(bd.get("holiday_pay", 0))
        holiday_ot_pay = float(bd.get("holiday_ot_pay", 0))
        duty_allowance = float(bd.get("duty_allowance", 0))
        welfare = float(bd.get("welfare", 0))
        monthly_bonus = float(bd.get("monthly_bonus", 0))
        annual_bonus = float(bd.get("annual_bonus", 0))
        other_pay = float(bd.get("other", 0))

        # 연간 상여금 월 환산
        annual_bonus_monthly = annual_bonus / 12 if annual_bonus > 0 else 0

        total_given = (base + ot_pay + night_pay + holiday_pay + holiday_ot_pay
                       + duty_allowance + welfare + monthly_bonus + annual_bonus_monthly
                       + other_pay)

        # 포함 수당 내역
        included_allowances["기본급"] = f"{base:,.0f}원"
        if ot_pay > 0:
            included_allowances["연장수당(포함)"] = f"{ot_pay:,.0f}원"
        if night_pay > 0:
            included_allowances["야간수당(포함)"] = f"{night_pay:,.0f}원"
        if holiday_pay > 0:
            included_allowances["휴일수당(포함)"] = f"{holiday_pay:,.0f}원"
        if holiday_ot_pay > 0:
            included_allowances["휴일8h초과수당(포함)"] = f"{holiday_ot_pay:,.0f}원"
        if duty_allowance > 0:
            included_allowances["직무수당"] = f"{duty_allowance:,.0f}원"
        if welfare > 0:
            included_allowances["복리후생비"] = f"{welfare:,.0f}원"
        if monthly_bonus > 0:
            included_allowances["매월 상여금"] = f"{monthly_bonus:,.0f}원"
        if annual_bonus > 0:
            included_allowances["연간 상여금(월환산)"] = f"{annual_bonus_monthly:,.0f}원 (연 {annual_bonus:,.0f}원÷12)"
        if other_pay > 0:
            included_allowances["기타 포함 수당"] = f"{other_pay:,.0f}원"

        # 역산 기본시급: 총액 ÷ 총계수시간
        effective_hourly = total_given / max(total_coeff, 1)
        formulas.append(
            f"역산 기본시급: {total_given:,.0f}원 ÷ {total_coeff:.1f}h = {effective_hourly:,.0f}원"
        )

        # 수당별 적정액 비교
        allowance_comparison = _calc_allowance_comparison(
            effective_hourly, inp, bd,
        )
        for name, comp in allowance_comparison.items():
            if comp["판정"] == "부족":
                warnings.append(
                    f"{name} 부족: 적정 {comp['적정액']:,.0f}원 > "
                    f"포함 {comp['포함액']:,.0f}원 (차액 {abs(comp['차액']):,.0f}원)"
                )

        base_wage = total_given  # 역산 기준 총액

    else:
        # 경로 1: 정액급여 → 총계수시간으로 역산
        total_given = inp.monthly_wage or ow.monthly_ordinary_wage
        effective_hourly = total_given / max(total_coeff, 1)
        formulas.append(
            f"역산 기본시급: {total_given:,.0f}원 ÷ {total_coeff:.1f}h = {effective_hourly:,.0f}원"
        )
        included_allowances["포괄임금 총액"] = f"{total_given:,.0f}원"
        warnings.append(
            "포괄임금 항목별 명세 없음 — 기본급/수당 구분이 불명확합니다. "
            "근로계약서에 항목 명시를 권장합니다."
        )

        # 역산으로 추정되는 수당 내역
        s = inp.schedule
        mc = MultiplierContext(inp)
        base_hours = coeff_detail["기본시간"]
        est_base = effective_hourly * base_hours
        included_allowances["추정 기본급"] = f"{est_base:,.0f}원"

        if s.weekly_overtime_hours > 0:
            ot_rate = 1.0 + mc.overtime
            est_ot = effective_hourly * s.weekly_overtime_hours * ot_rate * WEEKS_PER_MONTH
            included_allowances["추정 연장수당"] = f"{est_ot:,.0f}원"
        if s.weekly_night_hours > 0 and not mc.is_small:
            est_night = effective_hourly * s.weekly_night_hours * mc.night * WEEKS_PER_MONTH
            included_allowances["추정 야간수당"] = f"{est_night:,.0f}원"
        if s.weekly_holiday_hours > 0:
            hol_rate = 1.0 + mc.holiday
            est_hol = effective_hourly * s.weekly_holiday_hours * hol_rate * WEEKS_PER_MONTH
            included_allowances["추정 휴일수당"] = f"{est_hol:,.0f}원"

        base_wage = total_given

    # ── 4. 최저임금 충족 여부 ──────────────────────────────────────────────────
    is_ok = effective_hourly >= legal_minimum
    shortage = max(0.0, legal_minimum - effective_hourly) * total_coeff

    if not is_ok:
        warnings.append(
            f"포괄임금 역산 시급 {effective_hourly:,.0f}원 < "
            f"최저임금 {legal_minimum:,}원 — 최저임금법 위반 "
            f"(대법원 2020다300299)"
        )

    # ── 5인 미만 안내 ──────────────────────────────────────────────────────────
    mc_warn = MultiplierContext(inp)
    if mc_warn.is_small:
        warnings.append(
            "5인 미만 사업장: 연장·야간·휴일 가산수당(×0.5) 미적용 "
            "(근기법 제56조 적용 제외)"
        )

    # ── breakdown 조립 ─────────────────────────────────────────────────────────
    breakdown = {
        "역산 통상시급": f"{effective_hourly:,.0f}원",
        "총계수시간(월)": f"{total_coeff:.1f}h",
        f"{year}년 최저임금": f"{legal_minimum:,}원",
        "최저임금 충족": "✅" if is_ok else "❌",
        "월 부족분": f"{shortage:,.0f}원" if shortage > 0 else "-",
    }

    if not is_valid:
        breakdown["포괄임금 유효성"] = "⚠️ 유효성 문제 있음"

    # 계수시간 상세
    coeff_strs = {}
    for k, v in coeff_detail.items():
        if v > 0:
            coeff_strs[k] = f"{v:.1f}h"
    if coeff_strs:
        breakdown["계수시간 상세"] = coeff_strs

    # 수당별 비교표
    if allowance_comparison:
        comp_strs = {}
        for name, comp in allowance_comparison.items():
            comp_strs[name] = (
                f"적정 {comp['적정액']:,.0f}원 / "
                f"포함 {comp['포함액']:,.0f}원 / "
                f"{comp['판정']}"
            )
        breakdown["수당별 비교"] = comp_strs

    breakdown.update(included_allowances)

    return ComprehensiveResult(
        base_wage=round(base_wage, 0),
        effective_hourly=round(effective_hourly, 0),
        included_allowances=included_allowances,
        is_minimum_wage_ok=is_ok,
        legal_minimum=legal_minimum,
        shortage=round(shortage, 0),
        total_coefficient_hours=round(total_coeff, 1),
        allowance_comparison=allowance_comparison,
        is_valid_comprehensive=is_valid,
        validity_issues=validity_issues,
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )


# ── 헬퍼 함수 ─────────────────────────────────────────────────────────────────


def _check_validity(inp: WageInput) -> tuple[bool, list]:
    """포괄임금제 유효성 검사 (판례 기반)"""
    issues = []

    # 1. 교대제 근로자 → 적용 불가 (근로시간 산정 곤란하지 않음)
    shift_types = (
        WorkType.SHIFT_4_2, WorkType.SHIFT_3_2,
        WorkType.SHIFT_3, WorkType.SHIFT_2, WorkType.ROTATING,
    )
    if inp.work_type in shift_types:
        issues.append(
            "교대제 근로자에게는 포괄임금제를 적용할 수 없습니다 — "
            "근로시간 산정이 객관적으로 어렵지 않음 "
            "(대법원 2014도8873, 2008다6052)"
        )

    # 2. 시급제·일급제 → 적용 불가
    if inp.wage_type in (WageType.HOURLY, WageType.DAILY):
        issues.append(
            "시급제·일급제 근로자에게는 포괄임금제를 적용할 수 없습니다 "
            "(대법원 2014도8873)"
        )

    # 3. 연장·야간·휴일 근로가 전혀 없는 경우
    s = inp.schedule
    if (s.weekly_overtime_hours == 0 and s.weekly_night_hours == 0
            and s.weekly_holiday_hours == 0
            and s.weekly_holiday_overtime_hours == 0):
        issues.append(
            "연장·야간·휴일 근로가 없는 경우 포괄임금제 명목의 "
            "수당 미지급은 위법입니다 (대법원 2008다6052)"
        )

    return len(issues) == 0, issues


def _calc_coefficient_hours(inp: WageInput) -> tuple[float, dict]:
    """총계수시간 산출 — 가산율 반영 (5인 미만 시 가산 없음)"""
    s = inp.schedule
    mc = MultiplierContext(inp)
    wpm = WEEKS_PER_MONTH

    # 기본시간 = (소정근로 + 주휴) × 주→월 환산
    weekly_paid = s.daily_work_hours * s.weekly_work_days
    weekly_holiday_paid = s.daily_work_hours if weekly_paid >= 15 else 0
    base_hours = (weekly_paid + weekly_holiday_paid) * wpm

    # 가산율 결정 (MultiplierContext: 가산분만 반환, 기본 1.0은 여기서 추가)
    ot_mult = 1.0 + mc.overtime
    night_mult = mc.night
    hol_mult = 1.0 + mc.holiday
    hol_ot_mult = 1.0 + mc.holiday + mc.holiday_ot

    ot_coeff = s.weekly_overtime_hours * ot_mult * wpm
    night_coeff = s.weekly_night_hours * night_mult * wpm
    hol_coeff = s.weekly_holiday_hours * hol_mult * wpm
    hol_ot_coeff = s.weekly_holiday_overtime_hours * hol_ot_mult * wpm

    total = base_hours + ot_coeff + night_coeff + hol_coeff + hol_ot_coeff

    detail = {
        "기본시간": round(base_hours, 1),
        "연장계수": round(ot_coeff, 1),
        "야간계수": round(night_coeff, 1),
        "휴일계수": round(hol_coeff, 1),
        "휴일OT계수": round(hol_ot_coeff, 1),
    }
    return round(total, 1), detail


def _calc_allowance_comparison(
    hourly: float, inp: WageInput, bd: dict,
) -> dict:
    """수당별 적정액 vs 포함액 비교"""
    s = inp.schedule
    mc = MultiplierContext(inp)
    wpm = WEEKS_PER_MONTH

    items = [
        ("연장수당", s.weekly_overtime_hours,
         1.0 + mc.overtime,
         float(bd.get("overtime_pay", 0))),
        ("야간수당", s.weekly_night_hours,
         mc.night,
         float(bd.get("night_pay", 0))),
        ("휴일수당(8h이내)", s.weekly_holiday_hours,
         1.0 + mc.holiday,
         float(bd.get("holiday_pay", 0))),
        ("휴일수당(8h초과)", s.weekly_holiday_overtime_hours,
         1.0 + mc.holiday + mc.holiday_ot,
         float(bd.get("holiday_ot_pay", 0))),
    ]

    comparison = {}
    for name, hours, rate, included in items:
        if hours <= 0 and included <= 0:
            continue
        proper = hourly * hours * rate * wpm
        diff = included - proper
        # 100원 이하 오차 허용
        verdict = "적정" if diff >= -100 else "부족"
        comparison[name] = {
            "적정액": round(proper),
            "포함액": round(included),
            "차액": round(diff),
            "판정": verdict,
        }

    return comparison
