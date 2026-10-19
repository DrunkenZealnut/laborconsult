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
from ..utils import WEEKS_PER_MONTH, WEEKS_PER_MONTH_LABEL, fmt_hours
from ..models import WageInput, BusinessSize
from .ordinary_wage import OrdinaryWageResult
from .shared import MultiplierContext, premium_weekly
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

    # 금액은 평균임금·보수월액 추정(monthly_pay_estimate)과 같은 산식이다 — 한 카드에서 월 총액과 평균임금이 갈리지 않게
    pw = premium_weekly(inp, hourly)

    # ── 연장수당 ──────────────────────────────────────────────────────────────
    ot_hours = s.weekly_overtime_hours
    overtime_pay = pw.overtime
    if ot_hours > 0:
        rate = 1 + overtime_multiplier
        formulas.append(
            f"연장수당: {hourly:,.1f}원 × {fmt_hours(ot_hours)}h × {rate} = {overtime_pay:,.0f}원/주"
            + _derived_overtime_label(inp)
        )
        conflict = _overtime_conflict_note(inp)
        if conflict:
            warnings.append(conflict)

    # ── 야간수당 (22~06시, 연장/휴일과 중복 가산) ────────────────────────────
    night_hours = s.weekly_night_hours
    night_pay = pw.night
    if night_hours > 0 and not mc.is_small:
        formulas.append(
            f"야간수당: {hourly:,.1f}원 × {night_hours}h × 0.5 = {night_pay:,.0f}원/주 (중복 가산)"
        )

    # ── 휴일수당 ─────────────────────────────────────────────────────────────
    hol_hours = s.weekly_holiday_hours
    hol_ot_hours = s.weekly_holiday_overtime_hours

    holiday_pay = pw.holiday

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

    # 주 52시간 초과 경고 — 상시 4명 이하는 연장 근로의 제한(제53조)이 적용되지 않는다(근로기준법 제11조, 주 52시간 체크와 같은
    # 판정). 한도는 5명 이상 전체에 적용된다(30명 미만 특별연장은 2022년 말 종료 — 예전 표기 '30인 이상 사업장'은 낡았다)
    total_weekly = (inp.schedule.weekly_work_days * inp.schedule.daily_work_hours
                    + ot_hours + hol_hours + hol_ot_hours)
    if total_weekly > 52 and inp.business_size != BusinessSize.UNDER_5:
        warnings.append(f"주 총 근로시간 {total_weekly}h — 법정 한도 52h 초과 (상시 5명 이상 사업장, 근로기준법 제53조)")

    breakdown = {
        "통상시급": f"{hourly:,.1f}원",
        "연장수당(주)": f"{overtime_pay:,.0f}원",
        "야간수당(주)": f"{night_pay:,.0f}원",
        "휴일수당(주)": f"{holiday_pay:,.0f}원",
        "월 환산 계수": f"× ({WEEKS_PER_MONTH_LABEL})주",
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


def _derived_overtime_label(inp: WageInput) -> str:
    """연장시간이 1일 8시간·1주 40시간 초과분에서 나왔으면 그 출처를 붙인다(calc-card-followups F1)."""
    split = getattr(inp, "hour_split", None)
    if split is None or split.mode != "applied" or split.excess <= 0:
        return ""
    source = f"1일 8시간·주 40시간 초과분 {fmt_hours(split.excess)}h"
    if split.stated_overtime > 0:
        source += f", 질문의 연장 {fmt_hours(split.stated_overtime)}h"
    return f" ({source})"


def _overtime_conflict_note(inp: WageInput) -> str | None:
    """질문의 연장시간과 1일 초과분이 다르면 큰 값으로 계산했다는 사실과 별개일 때의 합계(D8)."""
    split = getattr(inp, "hour_split", None)
    if split is None or split.mode != "applied" or split.stated_overtime <= 0:
        return None
    if abs(split.stated_overtime - split.excess) <= 0.5:
        return None
    return (f"질문의 연장 {fmt_hours(split.stated_overtime)}시간과 하루 8시간·주 40시간을 넘는 {fmt_hours(split.excess)}시간이 "
            f"같은 시간인지 알 수 없어 큰 값({fmt_hours(split.overtime)}시간)으로 계산했습니다 — 둘이 별개라면 주 "
            f"{fmt_hours(split.stated_overtime + split.excess)}시간입니다.")


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
        "소정근로시간": f"{scheduled:.1f}h/주 ({fmt_hours(s.daily_work_hours)}h × {fmt_hours(s.weekly_work_days)}일)",
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
