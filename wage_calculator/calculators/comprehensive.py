"""
포괄임금제 역산 계산기

포괄임금제: 기본급에 연장·야간·휴일수당 등을 포함하여 지급하는 계약 형태.
실질 시급을 역산하여 최저임금 충족 여부를 확인합니다.

핵심 처리:
1. breakdown 있는 경우: 항목별 분리 → 통상임금 역산
2. breakdown 없는 경우: 총액에서 역산, 포함 수당 추정 표시
"""

from dataclasses import dataclass, field

from ..base import BaseCalculatorResult
from ..models import WageInput, WageType
from .ordinary_wage import OrdinaryWageResult
from ..constants import MINIMUM_HOURLY_WAGE


@dataclass
class ComprehensiveResult(BaseCalculatorResult):
    base_wage: float = 0.0                               # 기본급 (통상임금 기반)
    effective_hourly: float = 0.0                         # 역산 통상시급
    included_allowances: dict = field(default_factory=dict)  # 포함된 수당 내역
    is_minimum_wage_ok: bool = False                      # 최저임금 충족 여부
    legal_minimum: float = 0.0                            # 법정 최저임금
    shortage: float = 0.0                                 # 부족분 (충족 시 0)


def calc_comprehensive(inp: WageInput, ow: OrdinaryWageResult) -> ComprehensiveResult:
    """포괄임금제 역산 및 적법성 검토"""
    hourly = ow.hourly_ordinary_wage
    monthly_hours = ow.monthly_base_hours
    warnings = []
    formulas = []
    legal = [
        "근로기준법 제56조 (연장·야간·휴일 근로)",
        "대법원 2012다89399 (포괄임금제 적법성)",
    ]

    year = inp.reference_year
    if year not in MINIMUM_HOURLY_WAGE:
        year = max(MINIMUM_HOURLY_WAGE.keys())
    legal_minimum = MINIMUM_HOURLY_WAGE[year]

    # 포함 수당 내역
    s = inp.schedule
    included_allowances = {}

    if inp.comprehensive_breakdown:
        bd = inp.comprehensive_breakdown
        base = float(bd.get("base", 0))
        ot_pay = float(bd.get("overtime_pay", 0))
        night_pay = float(bd.get("night_pay", 0))
        holiday_pay = float(bd.get("holiday_pay", 0))
        other_pay = float(bd.get("other", 0))

        total_given = base + ot_pay + night_pay + holiday_pay + other_pay

        included_allowances = {
            "기본급": f"{base:,.0f}원",
        }
        if ot_pay > 0:
            included_allowances["연장수당(포함)"] = f"{ot_pay:,.0f}원"
        if night_pay > 0:
            included_allowances["야간수당(포함)"] = f"{night_pay:,.0f}원"
        if holiday_pay > 0:
            included_allowances["휴일수당(포함)"] = f"{holiday_pay:,.0f}원"
        if other_pay > 0:
            included_allowances["기타 포함 수당"] = f"{other_pay:,.0f}원"

        # 통상시급 역산: 기본급 기준
        effective_hourly = base / monthly_hours
        formulas.append(
            f"통상시급(역산): 기본급 {base:,.0f}원 ÷ {monthly_hours}h = {effective_hourly:,.0f}원"
        )

        # 적정 수당 계산 비교
        expected_ot = hourly * s.weekly_overtime_hours * 1.5 * (365 / 7 / 12)
        if ot_pay > 0 and s.weekly_overtime_hours > 0:
            if ot_pay < expected_ot * 0.95:  # 5% 오차 허용
                warnings.append(
                    f"연장수당 과소 포함 의심: 포함 {ot_pay:,.0f}원 < 산정 {expected_ot:,.0f}원"
                )

    else:
        # breakdown 없음: 총액에서 역산
        total_given = inp.monthly_wage or (ow.monthly_ordinary_wage)
        effective_hourly = total_given / monthly_hours
        formulas.append(
            f"시급 역산: {total_given:,.0f}원 ÷ {monthly_hours}h = {effective_hourly:,.0f}원"
        )
        included_allowances["포괄임금 총액"] = f"{total_given:,.0f}원"
        warnings.append(
            "포괄임금 항목별 명세 없음 — 기본급/수당 구분이 불명확합니다. "
            "근로계약서에 항목 명시를 권장합니다."
        )

    # 최저임금 충족 여부
    is_ok = effective_hourly >= legal_minimum
    shortage = max(0.0, legal_minimum - effective_hourly) * monthly_hours

    if not is_ok:
        warnings.append(
            f"포괄임금 역산 시급 {effective_hourly:,.0f}원 < "
            f"최저임금 {legal_minimum:,}원 — 최저임금법 위반"
        )

    # 포괄임금제 자체의 적법성 경고
    if s.weekly_overtime_hours == 0 and s.weekly_night_hours == 0:
        warnings.append(
            "연장/야간 근로가 없는 경우 포괄임금제 명목으로 수당 미지급은 위법입니다."
        )

    breakdown = {
        "역산 통상시급": f"{effective_hourly:,.0f}원",
        f"{year}년 최저임금": f"{legal_minimum:,}원",
        "최저임금 충족": "✅" if is_ok else "❌",
        "월 부족분": f"{shortage:,.0f}원" if shortage > 0 else "-",
        "월 기준시간": f"{monthly_hours}h",
        **included_allowances,
    }

    base_wage = float(inp.comprehensive_breakdown.get("base", inp.monthly_wage or 0)) \
        if inp.comprehensive_breakdown else (inp.monthly_wage or 0)

    return ComprehensiveResult(
        base_wage=base_wage,
        effective_hourly=round(effective_hourly, 0),
        included_allowances=included_allowances,
        is_minimum_wage_ok=is_ok,
        legal_minimum=legal_minimum,
        shortage=round(shortage, 0),
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )
