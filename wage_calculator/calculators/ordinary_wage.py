"""
통상임금 계산 엔진

통상임금은 모든 수당(연장·야간·휴일·퇴직금·연차수당 등)의 기반이 됩니다.
판단 기준: 정기성 + 일률성 (대법원 2013다4174)
※ 고정성 요건은 대법원 2023다302838 (2024.12.19) 판결로 폐기됨
  → 재직조건·소정근로일수 이내 조건부 수당도 통상임금 인정 가능
  → AllowanceCondition.EMPLOYMENT / ATTENDANCE 조건부 수당을 자동 포함 처리
"""

from dataclasses import dataclass
from ..models import WageInput, WageType, WorkType
from ..constants import MONTHLY_STANDARD_HOURS, SHIFT_MONTHLY_HOURS, WEEKLY_HOLIDAY_MIN_HOURS
from ..utils import WEEKS_PER_MONTH
from .shared import normalize_allowances


@dataclass
class OrdinaryWageResult:
    """통상임금 계산 결과"""
    hourly_ordinary_wage: float          # 통상시급 (원/시간)
    daily_ordinary_wage: float           # 1일 통상임금 (원/일)
    monthly_ordinary_wage: float         # 월 통상임금 총액 (원)
    monthly_base_hours: float            # 적용된 월 기준시간
    base_hours_detail: str               # 월 기준시간 산출 근거
    included_items: list                 # 통상임금 포함 항목 목록
    excluded_items: list                 # 통상임금 제외 항목 목록
    formula: str                         # 계산식 설명


def calc_ordinary_wage(inp: WageInput) -> OrdinaryWageResult:
    """
    임금 형태별 통상시급 산출

    계산 순서:
    1. 기준 월 근로시간 결정 (교대근무 여부 확인)
    2. 임금 형태 → 기본 통상임금 환산
    3. 고정수당(fixed_allowances) 중 통상임금 포함분 합산
    4. 월 통상임금 / 기준시간 = 통상시급
    """
    base_hours, base_hours_detail = _get_base_hours(inp)
    included_items = []
    excluded_items = []

    # ── Step 1: 기본 통상임금 산출 ───────────────────────────────────────────
    if inp.wage_type == WageType.HOURLY:
        hourly = inp.hourly_wage or 0.0
        monthly_base = hourly * base_hours
        formula = f"시급 {hourly:,.0f}원 × {base_hours}h = {monthly_base:,.0f}원"
        included_items.append(f"기본 시급: {hourly:,.0f}원")

    elif inp.wage_type == WageType.DAILY:
        daily = inp.daily_wage or 0.0
        daily_hours = inp.schedule.daily_work_hours or 8.0
        hourly = daily / daily_hours
        monthly_base = hourly * base_hours
        formula = (f"일급 {daily:,.0f}원 ÷ {daily_hours}h = 시급 {hourly:,.0f}원"
                   f" × {base_hours}h = {monthly_base:,.0f}원")
        included_items.append(f"기본 일급: {daily:,.0f}원")

    elif inp.wage_type == WageType.MONTHLY:
        monthly_base = inp.monthly_wage or 0.0
        formula = f"월 기본급: {monthly_base:,.0f}원"
        included_items.append(f"월 기본급: {monthly_base:,.0f}원")

    elif inp.wage_type == WageType.ANNUAL:
        annual = inp.annual_wage or 0.0
        monthly_base = annual / 12
        formula = f"연봉 {annual:,.0f}원 ÷ 12 = {monthly_base:,.0f}원"
        included_items.append(f"연봉 월 환산: {monthly_base:,.0f}원")

    elif inp.wage_type == WageType.COMPREHENSIVE:
        # 포괄임금제: breakdown이 있으면 base만 사용, 없으면 총액 사용
        if inp.comprehensive_breakdown:
            monthly_base = inp.comprehensive_breakdown.get("base", inp.monthly_wage or 0.0)
            formula = f"포괄임금 중 기본급: {monthly_base:,.0f}원"
        else:
            monthly_base = inp.monthly_wage or 0.0
            formula = f"포괄임금 총액(기본급 구분 없음): {monthly_base:,.0f}원"
        included_items.append(f"포괄임금 기본급: {monthly_base:,.0f}원")

    else:
        monthly_base = 0.0
        formula = "임금 형태 미확인"

    # ── Step 2: 고정수당 중 통상임금 포함분 합산 ─────────────────────────────
    # 대법원 2023다302838: 재직조건·근무일수 조건부도 통상임금 포함 가능
    allowance_total = 0.0
    allowances = normalize_allowances(inp.fixed_allowances)
    for a in allowances:
        is_ordinary, note = _resolve_is_ordinary_fa(a)

        # 최소보장 성과급: guaranteed_amount가 있으면 그 금액만 산입
        if a.condition == "최소보장성과" and is_ordinary:
            guaranteed = a.guaranteed_amount if a.guaranteed_amount is not None else a.amount
            effective_amount = min(max(0, guaranteed), a.amount)
        else:
            effective_amount = a.amount

        monthly_amount = effective_amount / 12 if a.annual else effective_amount

        if is_ordinary:
            allowance_total += monthly_amount
            label = f"{a.name}: {monthly_amount:,.0f}원/월"
            if note:
                label += f" ({note})"
            included_items.append(label)
        else:
            label = f"{a.name}: {monthly_amount:,.0f}원/월 (통상임금 제외)"
            if note:
                label += f" — {note}"
            excluded_items.append(label)

    monthly_ordinary = monthly_base + allowance_total

    if allowance_total > 0:
        formula += f" + 통상임금 포함 수당 {allowance_total:,.0f}원 = {monthly_ordinary:,.0f}원"

    hourly_ordinary = monthly_ordinary / base_hours
    daily_work_hours = inp.schedule.daily_work_hours or 8.0
    daily_ordinary = hourly_ordinary * daily_work_hours

    return OrdinaryWageResult(
        hourly_ordinary_wage=round(hourly_ordinary, 2),
        daily_ordinary_wage=round(daily_ordinary, 0),
        monthly_ordinary_wage=round(monthly_ordinary, 0),
        monthly_base_hours=base_hours,
        base_hours_detail=base_hours_detail,
        included_items=included_items,
        excluded_items=excluded_items,
        formula=formula,
    )


def _resolve_is_ordinary_fa(allowance) -> tuple[bool, str]:
    """
    수당의 통상임금 포함 여부 결정 (대법원 2023다302838 반영)
    FixedAllowance 속성 접근 방식 사용

    Returns:
        (is_ordinary, note) — note는 판결 적용 시 설명 문자열
    """
    condition = allowance.condition
    explicit = allowance.is_ordinary
    name = allowance.name

    # 성과조건: 통상임금 제외 (명시적으로 포함 설정해도 경고)
    if condition == "성과조건":
        if explicit is True:
            return False, "성과조건부로 통상임금 제외 처리 (명시 설정 무시)"
        return False, ""

    # 최소보장 성과급: 보장분만 통상임금 포함 (대법원 2023다302838)
    if condition == "최소보장성과":
        if explicit is False:
            return False, "명시적 제외 설정"
        return True, "최소보장분 통상임금 포함 (대법원 2023다302838)"

    # 재직조건·근무일수 조건: 2023다302838 판결로 통상임금 인정
    if condition in ["재직조건", "근무일수"]:
        if explicit is False:
            return True, f"재직/근무일수 조건부이나 대법원 2023다302838에 따라 통상임금 포함"
        return True, ""

    # 조건 없음(기본): 명시적 설정 우선, 없으면 True
    return (explicit if explicit is not None else True), ""


def _get_base_hours(inp: WageInput) -> tuple[float, str]:
    """
    월 기준시간 결정 (주휴시간 포함)

    우선순위:
    1. monthly_scheduled_hours 명시값
    2. shift_monthly_hours (교대근무 직접 지정)
    3. 교대근무 유형별 조회
    4. 스케줄 기반 자동 계산: (주 소정근로 + 주휴시간) × WEEKS_PER_MONTH
       - 주휴시간 = min(주 소정근로 / 5, 8) (대법원 2022다291153)
       - 주 15시간 미만이면 주휴 0

    Returns:
        (월 기준시간, 계산 근거 문자열)
    """
    # 1) 명시적 월 소정근로시간
    if inp.schedule.monthly_scheduled_hours is not None:
        h = inp.schedule.monthly_scheduled_hours
        return h, f"월 소정근로시간(직접 입력): {h}h"

    # 2) 교대근무: shift_monthly_hours 직접 지정
    if inp.schedule.shift_monthly_hours is not None:
        h = inp.schedule.shift_monthly_hours
        return h, f"교대근무 월 소정근로시간(직접 입력): {h}h"

    # 3) 교대근무 유형에서 조회
    shift_key_map = {
        WorkType.SHIFT_4_2: "4조2교대",
        WorkType.SHIFT_3_2: "3조2교대",
        WorkType.SHIFT_3:   "3교대",
        WorkType.SHIFT_2:   "2교대",
    }
    if inp.work_type in shift_key_map:
        key = shift_key_map[inp.work_type]
        h = SHIFT_MONTHLY_HOURS.get(key, MONTHLY_STANDARD_HOURS)
        return h, f"{key} 월 소정근로시간: {h}h"

    # 4) 일반: 스케줄 기반 자동 계산
    s = inp.schedule
    weekly_work_hours = s.daily_work_hours * s.weekly_work_days
    if weekly_work_hours >= WEEKLY_HOLIDAY_MIN_HOURS:
        weekly_holiday_hours = min(weekly_work_hours / 5, 8.0)
        holiday_detail = f"min({weekly_work_hours}h÷5, 8h) = {weekly_holiday_hours:.1f}h"
    else:
        weekly_holiday_hours = 0.0
        holiday_detail = f"0h (주 {weekly_work_hours}h < {WEEKLY_HOLIDAY_MIN_HOURS}h)"
    total_weekly = weekly_work_hours + weekly_holiday_hours
    monthly_hours = round(total_weekly * WEEKS_PER_MONTH, 1)

    detail = (
        f"주 소정근로: {s.daily_work_hours}h×{s.weekly_work_days:.0f}일 = {weekly_work_hours}h, "
        f"주휴시간: {holiday_detail}, "
        f"월 환산: ({weekly_work_hours}h+{weekly_holiday_hours:.1f}h)×{WEEKS_PER_MONTH:.3f} = {monthly_hours}h"
    )
    return monthly_hours, detail
