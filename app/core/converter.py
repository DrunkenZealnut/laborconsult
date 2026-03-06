"""extracted_info → WageInput 변환"""

from datetime import date, timedelta
import re

from wage_calculator.models import (
    WageInput, WageType, BusinessSize, WorkSchedule,
)


WAGE_TYPE_MAP = {
    "시급": WageType.HOURLY,
    "일급": WageType.DAILY,
    "월급": WageType.MONTHLY,
    "연봉": WageType.ANNUAL,
    "포괄임금제": WageType.COMPREHENSIVE,
}

BIZ_SIZE_MAP = {
    "5인미만": BusinessSize.UNDER_5,
    "5인이상": BusinessSize.OVER_5,
    "30인이상": BusinessSize.OVER_30,
    "300인이상": BusinessSize.OVER_300,
}


def convert_to_wage_input(info: dict) -> WageInput:
    """Claude tool_use 추출 결과 → WageInput 변환"""

    wage_type = WAGE_TYPE_MAP.get(info.get("wage_type", ""), WageType.MONTHLY)
    biz_size = BIZ_SIZE_MAP.get(info.get("business_size", ""), BusinessSize.OVER_5)

    schedule = WorkSchedule(
        weekly_work_days=info.get("weekly_work_days", 5),
        daily_work_hours=info.get("daily_work_hours", 8.0),
        weekly_overtime_hours=info.get("weekly_overtime_hours", 0.0),
        weekly_night_hours=info.get("weekly_night_hours", 0.0),
        weekly_holiday_hours=info.get("weekly_holiday_hours", 0.0),
        weekly_holiday_overtime_hours=info.get("weekly_holiday_overtime_hours", 0.0),
    )

    inp = WageInput(
        wage_type=wage_type,
        business_size=biz_size,
        schedule=schedule,
    )

    # 임금 설정
    amount = info.get("wage_amount")
    if amount:
        if wage_type == WageType.HOURLY:
            inp.hourly_wage = amount
        elif wage_type == WageType.DAILY:
            inp.daily_wage = amount
        elif wage_type in (WageType.MONTHLY, WageType.COMPREHENSIVE):
            inp.monthly_wage = amount
        elif wage_type == WageType.ANNUAL:
            inp.annual_wage = amount

    if info.get("monthly_wage") and not inp.monthly_wage:
        inp.monthly_wage = info["monthly_wage"]
    if info.get("annual_wage") and not inp.annual_wage:
        inp.annual_wage = info["annual_wage"]

    # 재직 기간
    if info.get("start_date"):
        inp.start_date = info["start_date"]
    elif info.get("service_period_text"):
        inp.start_date = _guess_start_date(info["service_period_text"])

    if info.get("end_date"):
        inp.dismissal_date = info["end_date"]

    # 고정수당
    for a in info.get("fixed_allowances", []):
        inp.fixed_allowances.append({
            "name": a.get("name", "수당"),
            "amount": a.get("amount", 0),
            "condition": a.get("condition", "없음"),
        })

    # 특수 계산기 입력
    if info.get("notice_days_given") is not None:
        inp.notice_days_given = info["notice_days_given"]
    if info.get("parental_leave_months"):
        inp.parental_leave_months = info["parental_leave_months"]
    if info.get("arrear_amount"):
        inp.arrear_amount = info["arrear_amount"]
    if info.get("arrear_due_date"):
        inp.arrear_due_date = info["arrear_due_date"]

    return inp


def _guess_start_date(text: str) -> str:
    """'3년 6개월' 같은 텍스트에서 추정 입사일 계산"""
    years = 0
    months = 0
    m = re.search(r"(\d+)\s*년", text)
    if m:
        years = int(m.group(1))
    m = re.search(r"(\d+)\s*개월", text)
    if m:
        months = int(m.group(1))

    if years == 0 and months == 0:
        return ""

    total_days = years * 365 + months * 30
    start = date.today() - timedelta(days=total_days)
    return start.isoformat()
