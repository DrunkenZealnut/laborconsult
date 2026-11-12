"""
주휴수당 계산기 (근로기준법 제55조)

수요: 169건 (6.5%)

핵심 규칙:
- 발생 조건: 주 소정근로시간 15h 이상 + 소정근로일 개근
- 주휴수당 = 유급주휴시간 × 통상시급
  - 주 소정근로일 ≥ 5일: min(1일 소정근로시간, 8h)
  - 주 소정근로일 < 5일: min(1주 소정근로시간 ÷ 5, 8h)
  ※ 대법원 2025.8.14. 선고 2022다291153 판결 — 1일 평균 소정근로시간(1주 소정근로시간 ÷ 1주 소정근로일 수)이
     원칙이고, 소정근로시간만 정했으면 1주 소정근로일이 5일에 미달하는 근로자는 5일로 보아 나눈다.
     산식은 shared.weekly_holiday_hours 단일 출처(통상임금 기준시간·소정근로시간·포괄임금 역산과 같은 값).

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
from ..utils import WEEKS_PER_MONTH, WEEKS_PER_MONTH_LABEL, fmt_hours, fmt_won, parse_date
from .ordinary_wage import OrdinaryWageResult
from .shared import weekly_holiday_hours  # noqa: F401 — 상담 경로(pipeline)가 이 모듈에서 가져간다
from .shared import scheduled_weekly_hours

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
    # 같은 카드의 연차와 같은 헬퍼 — 15h ÷ 5.5일 × 5.5일이 15h 미만으로 남으면 연차는 발생, 주휴는 0h가 된다(L6b)
    weekly_scheduled = scheduled_weekly_hours(s.daily_work_hours, s.weekly_work_days)
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
    holiday_hours, formula = weekly_holiday_hours(s.weekly_work_days, s.daily_work_hours)
    formulas.append(formula)
    legal.append("대법원 2025.8.14. 선고 2022다291153 판결")
    if s.weekly_work_days < 5:
        legal.append("근로기준법 제18조 (단시간근로자 근로조건)")
    # 주 5일을 넘게 일하는 단시간근로자는 같은 업무의 통상 근로자가 있으면 시행령 별표 2로 1일 소정근로시간을 정한다 — 통상
    # 근로자의 소정근로일 수로 나누므로 통상 근로자가 주 5일이면 위 원칙(÷ 1주 소정근로일 수)보다 길다. 계산기는 통상 근로자의
    # 근무 형태를 모르니 원칙으로 계산하고 다른 경우를 밝힌다(주 6일 × 4.1667h: 4.1667h vs 5h).
    if s.weekly_work_days > 5 and weekly_scheduled < WEEKLY_FULL_HOURS:
        warnings.append(
            "같은 사업장에 같은 업무의 통상 근로자가 있는 단시간근로자라면 1일 소정근로시간은 4주 동안의 소정근로시간을 그 기간 "
            "통상 근로자의 총 소정근로일 수로 나눈 시간이고 유급휴일 임금도 그 시간으로 계산합니다(근로기준법 시행령 별표 2 "
            f"제2호나목·제4호라목) — 통상 근로자가 주 5일 근무하면 주휴 {fmt_hours(weekly_scheduled / 5)}h"
            f"({fmt_hours(weekly_scheduled)}h ÷ 5)입니다."
        )
        legal.append("근로기준법 시행령 별표 2 (단시간근로자의 근로조건 결정기준)")

    weekly_pay = hourly * holiday_hours
    monthly_pay = weekly_pay * WEEKS_PER_MONTH

    formulas.append(
        f"주휴수당: {fmt_won(hourly)}원 × {fmt_hours(holiday_hours)}h = {fmt_won(weekly_pay)}원/주"
    )
    formulas.append(
        f"월 주휴수당: {fmt_won(weekly_pay)}원 × ({WEEKS_PER_MONTH_LABEL}) = {monthly_pay:,.0f}원"
    )

    breakdown = {
        "통상시급": f"{hourly:,.1f}원",
        "주 소정근로일": f"{fmt_hours(s.weekly_work_days)}일",
        "주 소정근로시간": f"{fmt_hours(weekly_scheduled)}h",
        "주휴 인정 시간": f"{fmt_hours(holiday_hours)}h",
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
