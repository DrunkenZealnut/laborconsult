"""
주휴수당 계산기 (근로기준법 제55조)

수요: 169건 (6.5%)

핵심 규칙:
- 발생 조건: 주 소정근로시간 15h 이상 + 소정근로일 개근
- 주휴수당 = 유급주휴시간 × 통상시급
  - 주 소정근로일 ≥ 5일: min(1일 소정근로시간, 8h)
  - 주 소정근로일 < 5일: min(1주 소정근로시간 ÷ 5, 8h)
  ※ 대법원 2025.8.14. 선고 2022다291153 판결
     기존 "주 소정/40×8" 방식은 주 5일 미만 판단 기준;
     주 소정근로일 수를 기준으로 산정하는 것이 타당.

퇴직 마지막 주 주휴수당 (고용부 2021.8.4. 행정해석 변경):
- 기존: 다음 주 계속 근무 전제 시에만 발생
- 변경: 한 주만 근무 후 근로관계 종료되어도 발생 가능
- 조건: 퇴직일이 그 주 주휴일(일요일) 이후여야 발생
  예) 월~금 개근, 토요일 퇴직 → 주휴일(일요일) 전 → 미발생
  예) 월~일요일 근로관계 존속, 월요일 퇴직 → 발생
"""

from dataclasses import dataclass
from datetime import date as _date, timedelta

from ..base import BaseCalculatorResult
from ..constants import WEEKLY_HOLIDAY_MIN_HOURS, WEEKLY_FULL_HOURS
from ..models import WageInput, WageType
from ..utils import WEEKS_PER_MONTH, parse_date
from .ordinary_wage import OrdinaryWageResult

_DAY_KO = ["월", "화", "수", "목", "금", "토", "일"]


@dataclass
class WeeklyHolidayResult(BaseCalculatorResult):
    weekly_holiday_pay: float = 0.0    # 주휴수당 (원/주)
    monthly_holiday_pay: float = 0.0   # 월 주휴수당 (원/월)
    holiday_hours: float = 0.0         # 주휴 인정 시간
    is_eligible: bool = False          # 주휴수당 발생 여부


def calc_weekly_holiday(inp: WageInput, ow: OrdinaryWageResult) -> WeeklyHolidayResult:
    """주휴수당 계산"""
    s = inp.schedule
    hourly = ow.hourly_ordinary_wage
    weekly_scheduled = s.weekly_work_days * s.daily_work_hours
    warnings = []
    formulas = []
    legal = [
        "근로기준법 제55조 (휴일)",
        "근로기준법 시행령 제30조 (주휴일)",
    ]

    # 주 15시간 미만 → 주휴수당 없음
    is_eligible = weekly_scheduled >= WEEKLY_HOLIDAY_MIN_HOURS

    # 개근 여부 확인
    if inp.weekly_attendance_days is not None:
        if inp.weekly_attendance_days < inp.schedule.weekly_work_days:
            is_eligible = False
            warnings.append(
                f"소정근로일 미개근 ({inp.weekly_attendance_days}일 / "
                f"{inp.schedule.weekly_work_days:.0f}일) — 주휴수당 미발생"
            )

    if not is_eligible and weekly_scheduled < WEEKLY_HOLIDAY_MIN_HOURS:
        warnings.append(
            f"주 소정근로시간 {weekly_scheduled}h < {WEEKLY_HOLIDAY_MIN_HOURS}h — "
            f"주휴수당 미발생"
        )
        return WeeklyHolidayResult(
            weekly_holiday_pay=0.0,
            monthly_holiday_pay=0.0,
            holiday_hours=0.0,
            is_eligible=False,
            breakdown={"주휴수당": "발생 조건 미충족 (주 15h 미만)"},
            formulas=[],
            warnings=warnings,
            legal_basis=legal,
        )

    # 주휴 시간 산정 (대법원 2025.8.14. 선고 2022다291153 판결)
    # 주 소정근로일 수를 기준으로 산정
    if s.weekly_work_days >= 5:
        # 주 5일 이상: min(1일 소정근로시간, 8h)
        holiday_hours = min(s.daily_work_hours, 8.0)
        formulas.append(
            f"주 소정근로일 {s.weekly_work_days:.0f}일 ≥ 5일 → 주휴: min({s.daily_work_hours}h, 8h) = {holiday_hours}h"
        )
        legal.append("대법원 2025.8.14. 선고 2022다291153 판결")
    else:
        # 주 5일 미만: min(1주 소정근로시간 ÷ 5, 8h)
        holiday_hours = min(weekly_scheduled / 5.0, 8.0)
        formulas.append(
            f"주 소정근로일 {s.weekly_work_days:.0f}일 < 5일 → 주휴: min({weekly_scheduled}h ÷ 5, 8h) = {holiday_hours:.2f}h"
        )
        legal.append("대법원 2025.8.14. 선고 2022다291153 판결")
        legal.append("근로기준법 제18조 (단시간근로자 근로조건)")

    weekly_pay = hourly * holiday_hours
    monthly_pay = weekly_pay * WEEKS_PER_MONTH

    formulas.append(
        f"주휴수당: {hourly:,.1f}원 × {holiday_hours}h = {weekly_pay:,.0f}원/주"
    )
    formulas.append(
        f"월 주휴수당: {weekly_pay:,.0f}원 × {WEEKS_PER_MONTH:.3f} = {monthly_pay:,.0f}원"
    )

    breakdown = {
        "통상시급": f"{hourly:,.1f}원",
        "주 소정근로일": f"{s.weekly_work_days:.0f}일",
        "주 소정근로시간": f"{weekly_scheduled}h",
        "주휴 인정 시간": f"{holiday_hours}h",
        "주 주휴수당": f"{weekly_pay:,.0f}원",
        "월 주휴수당": f"{monthly_pay:,.0f}원",
    }

    # 시급제/월급제 안내
    if inp.wage_type == WageType.HOURLY:
        warnings.append(
            "시급제: 제시된 시급에 주휴수당이 포함되어 있는지 확인 필요 "
            "(포함 시급 = 기본시급 × (1 + 주휴시간/주소정근로시간))"
        )
    elif inp.wage_type == WageType.MONTHLY:
        breakdown["월급 주휴 포함 여부"] = "월급에 주휴수당 포함 (별도 지급 불필요)"

    # ── 퇴직 마지막 주 주휴수당 발생 여부 (고용부 2021.8.4. 행정해석 변경) ──
    # end_date = 퇴직일 (= 마지막 근무일 다음날)이 입력된 경우에만 판단
    if inp.end_date:
        sep = parse_date(inp.end_date)                 # 퇴직일
        if sep is None:
            return WeeklyHolidayResult(
                weekly_holiday_pay=round(weekly_pay, 0),
                monthly_holiday_pay=round(monthly_pay, 0),
                holiday_hours=holiday_hours,
                is_eligible=True,
                breakdown=breakdown,
                formulas=formulas,
                warnings=warnings,
                legal_basis=legal,
            )
        last_work = sep - timedelta(days=1)            # 마지막 근무일

        # 마지막 근무일이 속한 주의 주휴일(일요일) 산출
        # Python weekday(): 월=0 … 일=6
        week_monday = last_work - timedelta(days=last_work.weekday())
        wh_date = week_monday + timedelta(days=6)      # 해당 주 일요일

        sep_label = f"{sep} ({_DAY_KO[sep.weekday()]}요일)"
        wh_label  = f"{wh_date} (일요일)"

        if sep <= wh_date:
            # 퇴직일이 주휴일 이전 → 미발생
            warnings.append(
                f"퇴직일 {sep_label}이 주휴일 {wh_label} 이전 "
                f"→ 마지막 주 주휴수당 미발생"
            )
            breakdown["마지막 주 주휴수당"] = f"미발생 (퇴직일 {sep_label} < 주휴일 {wh_label})"
        else:
            # 퇴직일이 주휴일 이후 → 발생
            breakdown["마지막 주 주휴수당"] = f"발생 (퇴직일 {sep_label} > 주휴일 {wh_label})"
            formulas.append(
                f"마지막 주: 퇴직일 {sep_label} > 주휴일 {wh_label} → 주휴수당 발생"
            )

        legal.append("고용노동부 행정해석 변경 (2021.8.4.) — 마지막 주 주휴수당 발생 요건")

    return WeeklyHolidayResult(
        weekly_holiday_pay=round(weekly_pay, 0),
        monthly_holiday_pay=round(monthly_pay, 0),
        holiday_hours=holiday_hours,
        is_eligible=True,
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )
