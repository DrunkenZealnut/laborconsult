"""
연차수당 계산기 (근로기준법 제60조)

수요: 81건 (3.1%)

핵심 규칙:
- 1년 미만: 매월 개근 시 1일 발생 (최대 11일)
- 1년 이상: 15일 기본 + 매 2년마다 1일 추가 (최대 25일)
- 2년차 차감: 1년 미만 사용분을 15일에서 공제 (제60조③)
- 연차수당 = 통상시급 × 8h × 미사용 연차일수
- 5인 미만 사업장: 연차휴가 미적용 (근로기준법 제11조)
- 단시간근로자: 비례 연차 (근기법 제18조③)
- 회계기준일(1.1) 기준 계산 지원

사용촉진제도 (근로기준법 제61조):
- 사용자가 규정 절차에 따라 사용촉진 조치를 한 경우,
  근로자가 미사용한 연차에 대해 수당 지급 의무 면제
- 절차: ① 만료 6개월 전 서면 통보 → ② 근로자 10일 이내 시기 지정
       → ③ 미지정 시 사용자가 시기 지정(만료 2개월 전까지)
- 1년 미만 발생 연차: 만료 3개월 전 통보 기준 적용
- leave_use_promotion=True이면 수당 지급 의무 없음으로 처리
"""

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..base import BaseCalculatorResult
from ..utils import parse_date
from ..models import WageInput, BusinessSize
from .ordinary_wage import OrdinaryWageResult
from ..constants import (
    ANNUAL_LEAVE_BASE_DAYS,
    ANNUAL_LEAVE_MAX_DAYS,
    ANNUAL_LEAVE_ADD_YEARS,
    ANNUAL_LEAVE_ADD_MAX,
    ANNUAL_LEAVE_FIRST_YEAR_MAX,
    PART_TIME_MIN_WEEKLY_HOURS,
    FULL_TIME_WEEKLY_HOURS,
    FULL_TIME_DAILY_HOURS,
)


@dataclass
class AnnualLeaveResult(BaseCalculatorResult):
    accrued_days: float = 0.0        # 발생 연차 일수 (현재 기간)
    used_days: float = 0.0           # 사용 연차 일수
    remaining_days: float = 0.0      # 미사용 연차 일수
    annual_leave_pay: float = 0.0    # 미사용 연차수당 (원)
    service_years: float = 0.0       # 재직 연수

    # G1: 2년차 차감
    deducted_days: float = 0.0       # 제60조③ 차감 일수

    # G3: 연도별 발생 스케줄
    schedule: list = field(default_factory=list)

    # G4: 단시간근로자 비례
    is_part_time_ratio: bool = False
    part_time_ratio: float = 1.0

    # G5: 퇴직 시 회계기준일 vs 입사일 차이
    fiscal_year_gap: float = 0.0


def calc_annual_leave(inp: WageInput, ow: OrdinaryWageResult) -> AnnualLeaveResult:
    """연차 발생 및 미사용 연차수당 계산"""
    hourly = ow.hourly_ordinary_wage
    warnings = []
    formulas = []
    legal = ["근로기준법 제60조 (연차 유급휴가)"]

    # 5인 미만 적용 제외
    if inp.business_size == BusinessSize.UNDER_5:
        warnings.append("5인 미만 사업장: 연차휴가 규정 미적용 (근로기준법 제11조)")

    # 재직기간 계산
    start = parse_date(inp.start_date)
    end = parse_date(inp.end_date) or date.today()

    if start is None:
        return AnnualLeaveResult(
            accrued_days=0, used_days=0, remaining_days=0, annual_leave_pay=0,
            service_years=0,
            breakdown={"오류": "입사일(start_date)을 입력해주세요"},
            formulas=[], warnings=["입사일 미입력"], legal_basis=legal,
        )

    service_days = (end - start).days
    service_years = service_days / 365

    # 출근율 확인
    if inp.attendance_rate < 0.8:
        warnings.append(
            f"출근율 {inp.attendance_rate*100:.0f}% < 80% — 연차 비례 적용 또는 미발생"
        )

    # G4: 단시간근로자 판정
    weekly_hours = inp.schedule.daily_work_hours * inp.schedule.weekly_work_days
    pt_accrued, pt_ratio, is_part_time = _apply_part_time_ratio(1.0, inp.schedule)
    if is_part_time and weekly_hours < PART_TIME_MIN_WEEKLY_HOURS:
        legal.append("근로기준법 제18조 제3항 (단시간근로자 연차)")
        warnings.append(
            f"주 소정근로시간 {weekly_hours:.0f}시간 < 15시간 — 연차 미발생"
        )
        return AnnualLeaveResult(
            accrued_days=0, used_days=0, remaining_days=0, annual_leave_pay=0,
            service_years=round(service_years, 2),
            is_part_time_ratio=True, part_time_ratio=0.0,
            breakdown={
                "재직기간": f"{service_days}일 ({service_years:.1f}년)",
                "주 소정근로시간": f"{weekly_hours:.0f}시간 (15시간 미만)",
                "연차": "미발생",
            },
            formulas=[], warnings=warnings, legal_basis=legal,
        )

    # 연차 발생 계산
    deducted_days = 0.0
    if inp.use_fiscal_year:
        # G2: 회계기준일(1.1) 기준
        accrued = _calc_fiscal_year_leave(start, end, inp.attendance_rate)
        legal.append("행정해석: 회계기준일(1.1) 방식 허용 (입사일 기준 이상 보장)")
    else:
        # 입사일 기준 (G1 차감 포함)
        accrued, deducted_days = _calc_accrued_days(
            service_days, service_years, inp.attendance_rate,
            start, end, inp.first_year_leave_used,
        )
        if deducted_days > 0:
            legal.append("근로기준법 제60조 제3항 (최초 1년간 사용 연차 차감)")

    # G4: 단시간 비례 적용
    if is_part_time:
        original_accrued = accrued
        accrued, pt_ratio, _ = _apply_part_time_ratio(accrued, inp.schedule)
        legal.append("근로기준법 제18조 제3항 (단시간근로자 연차)")
        formulas.append(
            f"단시간 비례: {original_accrued:.1f}일 × "
            f"({weekly_hours:.0f}h/40h) × (8h/{inp.schedule.daily_work_hours:.0f}h) "
            f"= {accrued:.1f}일"
        )

    # 연차수당 계산
    used = inp.annual_leave_used
    remaining = max(0.0, accrued - used)
    daily_wage = hourly * 8

    # 사용촉진제도 실시 여부 확인 (근로기준법 제61조)
    promotion_applied = getattr(inp, "leave_use_promotion", False)
    if promotion_applied and remaining > 0:
        legal.append("근로기준법 제61조 (연차 유급휴가의 사용 촉진)")
        warnings.append(
            f"사용촉진제도 실시: 미사용 연차 {remaining:.1f}일에 대해 "
            f"수당 지급 의무 없음 (절차 적법 이행 전제)"
        )
        leave_pay = 0.0
        breakdown_promotion = "면제 — 사용촉진 절차 이행 (근기법 제61조)"
    else:
        leave_pay = daily_wage * remaining
        breakdown_promotion = None
        if not promotion_applied and remaining > 0:
            warnings.append(
                f"사용촉진제도 미실시: 미사용 연차 {remaining:.1f}일 → "
                f"수당 지급 의무 있음"
            )
            legal.append("근로기준법 제61조 (연차 유급휴가의 사용 촉진)")

    formulas.append(
        f"미사용 연차수당: {hourly:,.0f}원 × 8h × {remaining:.1f}일 = {leave_pay:,.0f}원"
        + (" (사용촉진으로 면제)" if promotion_applied and remaining > 0 else "")
    )

    # G5: 퇴직 시 입사일/회계기준일 비교 정산
    fiscal_year_gap = 0.0
    if inp.use_fiscal_year:
        hire_based, _ = _calc_accrued_days(
            service_days, service_years, inp.attendance_rate,
            start, end, inp.first_year_leave_used,
        )
        if is_part_time:
            hire_based, _, _ = _apply_part_time_ratio(hire_based, inp.schedule)
        if hire_based > accrued:
            fiscal_year_gap = hire_based - accrued
            gap_pay = daily_wage * fiscal_year_gap
            warnings.append(
                f"퇴직 시 정산: 입사일 기준({hire_based:.1f}일) > "
                f"회계기준일({accrued:.1f}일) → 차이 {fiscal_year_gap:.1f}일 × "
                f"{daily_wage:,.0f}원 = {gap_pay:,.0f}원 추가 지급 필요"
            )

    # G3 + G6: 연도별 스케줄
    schedule = _build_accrual_schedule(start, end, inp.use_fiscal_year,
                                       inp.first_year_leave_used)

    # 1년 미만일 때 역월 달 수 표시
    months_note = ""
    if service_years < 1 and start and end:
        cm = _count_complete_months(start, end)
        months_note = f" (완성 달 수: {cm}개월)"

    breakdown = {
        "재직기간": f"{service_days}일 ({service_years:.1f}년){months_note}",
        "발생 연차": f"{accrued:.1f}일",
        "사용 연차": f"{used:.1f}일",
        "미사용 연차": f"{remaining:.1f}일",
        "1일 통상임금": f"{daily_wage:,.0f}원",
        "연차수당 합계": f"{leave_pay:,.0f}원",
    }
    if deducted_days > 0:
        breakdown["2년차 차감 (제60조③)"] = (
            f"1년 미만 사용 {inp.first_year_leave_used:.0f}일 차감 → "
            f"부여 {accrued:.1f}일"
        )
    if is_part_time:
        breakdown["단시간 비례"] = f"비례계수 ×{pt_ratio:.2f} (주 {weekly_hours:.0f}시간)"
    if fiscal_year_gap > 0:
        breakdown["퇴직 시 추가 지급"] = f"{fiscal_year_gap:.1f}일분"
    if breakdown_promotion:
        breakdown["사용촉진제도"] = breakdown_promotion
    if schedule:
        sched_lines = []
        for s in schedule:
            sched_lines.append(f"{s['period']}: {s['days']}일 (수당발생: {s['pay_trigger_date']})")
        breakdown["연도별 발생 스케줄"] = " | ".join(sched_lines)

    return AnnualLeaveResult(
        accrued_days=round(accrued, 1),
        used_days=used,
        remaining_days=round(remaining, 1),
        annual_leave_pay=round(leave_pay, 0),
        service_years=round(service_years, 2),
        deducted_days=round(deducted_days, 1),
        schedule=schedule,
        is_part_time_ratio=is_part_time,
        part_time_ratio=round(pt_ratio, 4),
        fiscal_year_gap=round(fiscal_year_gap, 1),
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )


# ── G1: 입사일 기준 연차 발생 (2년차 차감 포함) ──────────────────────────

def _calc_accrued_days(
    service_days: int,
    service_years: float,
    attendance_rate: float,
    start: "date | None" = None,
    end: "date | None" = None,
    first_year_leave_used: float = 0.0,
) -> tuple[float, float]:
    """연차 발생일수 계산

    Returns: (accrued_days, deducted_days)
    """
    deducted = 0.0

    if service_years < 1:
        # 1년 미만: 매월 개근 시 1일 (최대 11일)
        if start and end:
            months_worked = _count_complete_months(start, end)
        else:
            months_worked = service_days // 30
        accrued = min(months_worked, ANNUAL_LEAVE_FIRST_YEAR_MAX)
        if attendance_rate < 1.0:
            accrued = int(accrued * attendance_rate)
    else:
        # 1년 이상: 15일 + 2년마다 1일 추가 (최대 25일)
        extra_years = int(service_years - 1)
        extra_days = min(extra_years // ANNUAL_LEAVE_ADD_YEARS, ANNUAL_LEAVE_ADD_MAX)
        base = min(ANNUAL_LEAVE_BASE_DAYS + extra_days, ANNUAL_LEAVE_MAX_DAYS)

        # G1: 제60조③ — 2년차(extra_years==0)일 때 1년 미만 사용분 차감
        if extra_years == 0 and first_year_leave_used > 0:
            deducted = min(first_year_leave_used, float(ANNUAL_LEAVE_FIRST_YEAR_MAX))
            base = max(0, base - deducted)

        # 출근율 80% 미만이면 발생 안 함
        if attendance_rate < 0.8:
            base = 0
            deducted = 0.0

        accrued = base

    return float(accrued), deducted


# ── G2: 회계기준일(1.1) 기준 연차 ────────────────────────────────────────

def _calc_fiscal_year_leave(start: date, end: date, attendance_rate: float) -> float:
    """회계기준일(1.1~12.31) 기준 연차 계산

    - 입사 첫해: 잔여 월수 비례 (올림)
    - 2년째 이후: 입사년도 기준 근속연수로 산정
    """
    hire_year = start.year
    calc_year = end.year

    if hire_year == calc_year:
        # 입사 첫해: 잔여 월수 비례
        remaining_months = 12 - start.month + (1 if start.day == 1 else 0)
        remaining_months = min(remaining_months, 12)
        accrued = math.ceil(ANNUAL_LEAVE_BASE_DAYS * remaining_months / 12)
    else:
        years_since_hire = calc_year - hire_year
        if years_since_hire <= 1:
            accrued = ANNUAL_LEAVE_BASE_DAYS  # 15일
        else:
            extra = min(
                (years_since_hire - 1) // ANNUAL_LEAVE_ADD_YEARS,
                ANNUAL_LEAVE_ADD_MAX,
            )
            accrued = min(ANNUAL_LEAVE_BASE_DAYS + extra, ANNUAL_LEAVE_MAX_DAYS)

    if attendance_rate < 0.8:
        accrued = 0

    return float(accrued)


# ── G3 + G6: 연도별 연차 발생 스케줄 ─────────────────────────────────────

def _build_accrual_schedule(
    start: date,
    end: date,
    use_fiscal_year: bool = False,
    first_year_leave_used: float = 0.0,
) -> list[dict]:
    """입사일~계산일까지의 연도별 연차 발생 스케줄 생성"""
    schedule = []

    if use_fiscal_year:
        return _build_fiscal_schedule(start, end)

    # 입사일 기준 스케줄
    service_days = (end - start).days
    one_year = date(start.year + 1, start.month, start.day) if _safe_date(start, 1) else start + timedelta(days=365)

    # 1년 미만
    if service_days > 0:
        first_year_end = min(one_year - timedelta(days=1), end)
        months = _count_complete_months(start, first_year_end)
        first_year_days = min(months, ANNUAL_LEAVE_FIRST_YEAR_MAX)
        pay_date = one_year
        schedule.append({
            "period": "1년 미만",
            "accrual_date": f"{start.isoformat()} ~ {first_year_end.isoformat()}",
            "days": first_year_days,
            "pay_trigger_date": pay_date.isoformat(),
            "note": f"매월 개근 시 1일 (최대 {ANNUAL_LEAVE_FIRST_YEAR_MAX}일)",
        })

    # 2년차 이후
    year_num = 2
    current_start = one_year
    while current_start <= end:
        next_start = _safe_date(start, year_num) or (start + timedelta(days=365 * year_num))
        extra_years = year_num - 2  # 2년차=0, 3년차=1, ...
        extra_days = min(extra_years // ANNUAL_LEAVE_ADD_YEARS, ANNUAL_LEAVE_ADD_MAX)
        base = min(ANNUAL_LEAVE_BASE_DAYS + extra_days, ANNUAL_LEAVE_MAX_DAYS)

        # G1: 2년차 차감
        deduction_note = ""
        if year_num == 2 and first_year_leave_used > 0:
            deducted = min(first_year_leave_used, float(ANNUAL_LEAVE_FIRST_YEAR_MAX))
            base = max(0, base - deducted)
            deduction_note = f" (15일 - {first_year_leave_used:.0f}일 차감, 제60조③)"

        schedule.append({
            "period": f"{year_num}년차",
            "accrual_date": current_start.isoformat(),
            "days": base,
            "pay_trigger_date": next_start.isoformat(),
            "note": f"{base}일{deduction_note}",
        })

        current_start = next_start
        year_num += 1

    return schedule


def _build_fiscal_schedule(start: date, end: date) -> list[dict]:
    """회계기준일 기준 스케줄"""
    schedule = []
    hire_year = start.year

    for year in range(hire_year, end.year + 1):
        if year == hire_year:
            remaining_months = 12 - start.month + (1 if start.day == 1 else 0)
            remaining_months = min(remaining_months, 12)
            days = math.ceil(ANNUAL_LEAVE_BASE_DAYS * remaining_months / 12)
            period = f"{year}년 (입사 첫해)"
            note = f"비례 부여: 15 × {remaining_months}/12 = {days}일"
            pay_date = date(year + 1, 1, 1)
        else:
            years_since = year - hire_year
            if years_since <= 1:
                days = ANNUAL_LEAVE_BASE_DAYS
            else:
                extra = min(
                    (years_since - 1) // ANNUAL_LEAVE_ADD_YEARS,
                    ANNUAL_LEAVE_ADD_MAX,
                )
                days = min(ANNUAL_LEAVE_BASE_DAYS + extra, ANNUAL_LEAVE_MAX_DAYS)
            period = f"{year}년 ({years_since + 1}년차)"
            note = f"{days}일"
            pay_date = date(year + 1, 1, 1)

        schedule.append({
            "period": period,
            "accrual_date": f"{year}-01-01",
            "days": days,
            "pay_trigger_date": pay_date.isoformat(),
            "note": note,
        })

    return schedule


# ── G4: 단시간근로자 비례 ─────────────────────────────────────────────────

def _apply_part_time_ratio(accrued: float, schedule) -> tuple[float, float, bool]:
    """단시간근로자 비례 연차 적용

    공식: 통상근로자 연차 × (주소정근로시간/40) × (8h/1일소정근로시간)

    Returns: (adjusted_days, ratio, is_part_time)
    """
    weekly_hours = schedule.daily_work_hours * schedule.weekly_work_days
    daily_hours = schedule.daily_work_hours

    if weekly_hours >= FULL_TIME_WEEKLY_HOURS:
        return accrued, 1.0, False

    if weekly_hours < PART_TIME_MIN_WEEKLY_HOURS:
        return 0.0, 0.0, True

    if daily_hours <= 0:
        return accrued, 1.0, False

    ratio = (weekly_hours / FULL_TIME_WEEKLY_HOURS) * (FULL_TIME_DAILY_HOURS / daily_hours)
    adjusted = round(accrued * ratio, 1)

    return adjusted, round(ratio, 4), True


# ── 유틸리티 ──────────────────────────────────────────────────────────────

def _count_complete_months(start: "date", end: "date") -> int:
    """역월(曆月) 기준 완성된 달 수 계산

    예: 2024-01-01 ~ 2024-07-15 → 6개월 완성 (7월은 진행 중)
        2024-01-01 ~ 2024-07-01 → 6개월 완성 (7월 1일 시작 = 완성 아님)
        2024-01-15 ~ 2024-07-15 → 6개월 완성
    """
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(0, months)


def _safe_date(start: date, years_add: int) -> "date | None":
    """start로부터 years_add년 후 날짜 반환 (2/29 등 예외 처리)"""
    try:
        return date(start.year + years_add, start.month, start.day)
    except ValueError:
        # 2/29 입사 → 2/28로 조정
        return date(start.year + years_add, start.month, start.day - 1)
