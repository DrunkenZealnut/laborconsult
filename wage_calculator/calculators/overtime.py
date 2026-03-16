"""
연장·야간·휴일 수당 계산기 (근로기준법 제56조)
주 52시간 준수 여부 체크 (근로기준법 제52조, 제53조)

수요: 954건 (36.7%) — 가장 많은 임금 관련 질문 유형

핵심 규칙:
- 연장수당: 통상시급 × 연장시간 × 1.5
- 야간수당: 통상시급 × 야간시간 × 0.5 (연장·휴일과 중복 가산)
- 휴일수당: 통상시급 × 휴일시간 × 1.5 (8h 초과분은 × 2.0)
- 5인 미만 사업장: 가산수당 미적용 (× 1.0만 지급)

주 52시간:
- 기본 한도: 소정근로 40h + 연장 12h = 52h/주 (5인 이상)
- 5인 미만: 적용 제외
"""

from dataclasses import dataclass

from ..base import BaseCalculatorResult
from ..utils import WEEKS_PER_MONTH
from ..models import WageInput, BusinessSize
from .ordinary_wage import OrdinaryWageResult
from .shared import MultiplierContext
from ..constants import OVERTIME_RATE, NIGHT_PREMIUM_RATE, HOLIDAY_RATE, HOLIDAY_OT_RATE

# 주 52시간 제한 시행일 (사업장 규모별)
# 5인 이상: 2021.7.1 전면 적용 (기존 50인 이상 2018, 50~299인 2020)
WEEKLY_52H_LIMIT = 52
WEEKLY_SPECIAL_EXTENSION_LIMIT = 60  # 특별연장근로 인가 시 최대 60h (근기법 제53조제4항)


@dataclass
class OvertimeResult(BaseCalculatorResult):
    overtime_pay: float = 0.0          # 연장수당 (원/주)
    night_pay: float = 0.0             # 야간수당 (원/주)
    holiday_pay: float = 0.0           # 휴일수당 (원/주)
    monthly_overtime_pay: float = 0.0  # 월 연장수당 합계


def calc_overtime(inp: WageInput, ow: OrdinaryWageResult) -> OvertimeResult:
    """
    연장·야간·휴일 수당 계산

    Args:
        inp: 임금 입력 데이터
        ow: 통상임금 계산 결과
    """
    s = inp.schedule
    hourly = ow.hourly_ordinary_wage
    warnings = []
    formulas = []
    legal = []

    mc = MultiplierContext(inp)

    overtime_multiplier   = mc.overtime
    night_multiplier      = mc.night
    holiday_multiplier    = mc.holiday
    holiday_ot_multiplier = mc.holiday_ot

    small_warn = mc.small_business_warning()
    if small_warn:
        warnings.append(small_warn)
        legal.append("근로기준법 제11조 (적용범위)")
    else:
        legal.append("근로기준법 제56조 (연장·야간·휴일 근로)")

    # ── 연장수당 ──────────────────────────────────────────────────────────────
    ot_hours = s.weekly_overtime_hours
    overtime_pay = hourly * ot_hours * (1 + overtime_multiplier)
    if ot_hours > 0:
        rate = 1 + overtime_multiplier
        formulas.append(
            f"연장수당: {hourly:,.1f}원 × {ot_hours}h × {rate} = {overtime_pay:,.0f}원/주"
        )

    # ── 야간수당 (22~06시, 연장/휴일과 중복 가산) ────────────────────────────
    night_hours = s.weekly_night_hours
    night_pay = hourly * night_hours * night_multiplier
    if night_hours > 0 and not mc.is_small:
        formulas.append(
            f"야간수당: {hourly:,.1f}원 × {night_hours}h × 0.5 = {night_pay:,.0f}원/주 (중복 가산)"
        )

    # ── 휴일수당 ─────────────────────────────────────────────────────────────
    hol_hours = s.weekly_holiday_hours
    hol_ot_hours = s.weekly_holiday_overtime_hours

    holiday_pay = (
        hourly * hol_hours * (1 + holiday_multiplier)
        + hourly * hol_ot_hours * (1 + holiday_multiplier + holiday_ot_multiplier)
    )

    if hol_hours > 0:
        rate_normal = 1 + holiday_multiplier
        rate_ot = 1 + holiday_multiplier + holiday_ot_multiplier
        formulas.append(
            f"휴일수당: "
            f"{hourly:,.1f}원 × {hol_hours}h × {rate_normal}"
            + (f" + {hourly:,.1f}원 × {hol_ot_hours}h × {rate_ot}" if hol_ot_hours > 0 else "")
            + f" = {holiday_pay:,.0f}원/주"
        )

    # ── 주 → 월 환산 (× 4.345주) ─────────────────────────────────────────────
    monthly = (overtime_pay + night_pay + holiday_pay) * WEEKS_PER_MONTH

    # 주 52시간 초과 경고
    total_weekly = (inp.schedule.weekly_work_days * inp.schedule.daily_work_hours
                    + ot_hours + hol_hours + hol_ot_hours)
    if total_weekly > 52:
        warnings.append(f"주 총 근로시간 {total_weekly}h — 법정 한도 52h 초과 (30인 이상 사업장)")

    breakdown = {
        "통상시급": f"{hourly:,.1f}원",
        "연장수당(주)": f"{overtime_pay:,.0f}원",
        "야간수당(주)": f"{night_pay:,.0f}원",
        "휴일수당(주)": f"{holiday_pay:,.0f}원",
        "월 환산 계수": f"× {WEEKS_PER_MONTH:.3f}주",
        "월 합계": f"{monthly:,.0f}원",
    }

    return OvertimeResult(
        overtime_pay=round(overtime_pay, 0),
        night_pay=round(night_pay, 0),
        holiday_pay=round(holiday_pay, 0),
        monthly_overtime_pay=round(monthly, 0),
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )


@dataclass
class WeeklyHoursComplianceResult:
    total_weekly_hours: float          # 주 총 근로시간
    limit: int                         # 적용 한도 (52h 또는 미적용)
    excess_hours: float                # 초과 시간 (0이면 준수)
    is_compliant: bool                 # 준수 여부
    is_applicable: bool                # 5인 이상 사업장 여부 (5인 미만 미적용)
    penalty_info: str                  # 위반 시 제재 안내
    breakdown: dict
    warnings: list
    legal_basis: list


def check_weekly_hours_compliance(inp: WageInput) -> WeeklyHoursComplianceResult:
    """
    주 52시간 준수 여부 체크

    Args:
        inp: 임금 입력 데이터 (schedule, business_size 사용)

    Returns:
        WeeklyHoursComplianceResult
    """
    warnings = []
    legal = [
        "근로기준법 제52조 (선택적 근로시간제)",
        "근로기준법 제53조 (연장 근로의 제한)",
    ]

    s = inp.schedule
    is_small = inp.business_size == BusinessSize.UNDER_5

    # 주 총 근로시간 계산
    scheduled = s.daily_work_hours * s.weekly_work_days
    overtime  = s.weekly_overtime_hours
    holiday   = s.weekly_holiday_hours + s.weekly_holiday_overtime_hours

    total_weekly = scheduled + overtime + holiday

    if is_small:
        return WeeklyHoursComplianceResult(
            total_weekly_hours=total_weekly,
            limit=0,
            excess_hours=0.0,
            is_compliant=True,
            is_applicable=False,
            penalty_info="5인 미만 사업장: 주 52시간 한도 미적용",
            breakdown={
                "주 총 근로시간": f"{total_weekly:.1f}h",
                "적용 여부": "미적용 (5인 미만 사업장 — 근로기준법 제11조)",
            },
            warnings=["5인 미만 사업장은 주 52시간 제한 미적용 (근로기준법 제11조)"],
            legal_basis=["근로기준법 제11조 (적용범위)"],
        )

    limit = WEEKLY_52H_LIMIT
    excess = max(0.0, total_weekly - limit)
    is_compliant = excess == 0

    if excess > 0:
        warnings.append(
            f"⚠️ 주 {total_weekly:.1f}h — 법정 한도 {limit}h 초과 ({excess:.1f}h 과초과). "
            f"위반 시 2년 이하 징역 또는 2,000만원 이하 벌금 (근로기준법 제110조)"
        )
        legal.append("근로기준법 제110조 (벌칙)")

    penalty = (
        "위반 시: 2년 이하 징역 또는 2,000만원 이하 벌금 (근로기준법 제110조)"
        if excess > 0 else "준수"
    )

    # 특별연장 가능 여부 안내
    if 52 < total_weekly <= 60:
        warnings.append(
            f"특별연장근로 인가 가능 여부 확인 필요 (근로기준법 제53조제4항, 최대 60h/주)"
        )

    breakdown = {
        "소정근로시간": f"{scheduled:.1f}h/주 ({s.daily_work_hours}h × {s.weekly_work_days}일)",
        "연장근로시간": f"{overtime:.1f}h/주",
        "휴일근로시간": f"{holiday:.1f}h/주",
        "주 총 근로시간": f"{total_weekly:.1f}h",
        "법정 한도": f"{limit}h/주 (5인 이상)",
        "초과 시간": f"{excess:.1f}h",
        "준수 여부": "✅ 준수" if is_compliant else f"❌ {excess:.1f}h 초과",
        "위반 시 제재": penalty,
    }

    return WeeklyHoursComplianceResult(
        total_weekly_hours=total_weekly,
        limit=limit,
        excess_hours=round(excess, 1),
        is_compliant=is_compliant,
        is_applicable=True,
        penalty_info=penalty,
        breakdown=breakdown,
        warnings=warnings,
        legal_basis=legal,
    )
