"""연차 발생·사용·미사용 평가액. 현재 기간과 첫해 월별 발생분을 분리한다.

과거 출근 자료가 없는 일정은 조건부 참고값이며 실제 누적 채권으로 합산하지 않는다.
"""
import calendar
import math
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..base import BaseCalculatorResult
from ..effective_rules import EffectiveRule, split_effective_periods
from ..legal_rules import resolve_reference_date
from ..models import WageInput, BusinessSize
from ..constants import FULL_TIME_DAILY_HOURS, FULL_TIME_WEEKLY_HOURS
from .ordinary_wage import OrdinaryWageResult

ANNUAL_INPUT_FIELDS = (
    "annual_leave_used", "attendance_rate", "use_fiscal_year", "leave_use_promotion",
    "first_year_leave_used", "first_year_leave_used_hours", "annual_full_attendance_months", "first_year_full_attendance_months",
    "annual_scheduled_days", "annual_attended_days", "annual_deemed_periods",
    "annual_original_weekly_hours", "annual_original_daily_hours", "annual_leave_used_hours",
    "fiscal_year_granted_days", "last_employed_date",
)
LSA_URL = "https://www.law.go.kr/법령/근로기준법/제60조"
HISTORY_URL = "https://opinion.lawmaking.go.kr/nl4li/lsItptEmp/396414"
REDUCED_URL = "https://1350.moel.go.kr/rtmview.do?id=1000320803"
# 제17185호 부칙 제2조: 개정 전에 이미 발생한 휴가는 종전 소멸 규정 유지.
MONTHLY_EXPIRY_RULES = (
    EffectiveRule("monthly-expiry-1year", date(2014, 7, 1), date(2020, 3, 31),
                  {"first_anniversary": False}, (LSA_URL, "법률 제12325호 제60조⑦")),
    EffectiveRule("monthly-expiry-first-year", date(2020, 3, 31), None,
                  {"first_anniversary": True}, (LSA_URL, "법률 제17185호 부칙 제2조")),
)


@dataclass
class AnnualLeaveResult(BaseCalculatorResult):
    accrued_days: float = 0.0
    used_days: float = 0.0
    remaining_days: float = 0.0
    annual_leave_pay: float = 0.0  # 現 잔여분의 입력 시급 평가액. 지급채권 여부는 pay_due
    service_years: float = 0.0
    deducted_days: float = 0.0    # 검증된 개정 전 사건의 호환 필드
    schedule: list = field(default_factory=list)
    is_part_time_ratio: bool = False
    part_time_ratio: float = 1.0
    fiscal_year_gap: float = 0.0  # 자료 없는 누적 비교액을 임의로 만들지 않음
    is_eligible: bool | None = None
    accrued_hours: float = 0.0
    used_hours: float = 0.0
    remaining_hours: float = 0.0
    day_hours: float = 8.0
    effective_attendance_rate: float = 1.0
    assessment_start: str = ""
    assessment_end: str = ""
    pay_due: bool = False
    pay_trigger_date: str = ""
    first_year_accrued_days: float | None = None
    first_year_used_days: float | None = None
    first_year_remaining_days: float | None = None
    first_year_settlement_days: float | None = None
    first_year_accrued_hours: float | None = None
    first_year_used_hours: float | None = None
    first_year_remaining_hours: float | None = None
    accrual_basis: str = "statutory"


def _date(value, label):
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise ValueError(f"{label}을 YYYY-MM-DD 형식의 유효한 날짜로 입력해주세요")


def _number(value, label, lo=0, hi=None, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label}에 유효한 숫자가 필요합니다")
    if value < lo or (hi is not None and value > hi) or (integer and int(value) != value):
        raise ValueError(f"{label}의 범위를 확인해주세요")
    return value


def _safe_date(start, years_add):
    year = start.year + years_add
    last = calendar.monthrange(year, start.month)[1]
    # 민법 제160조: 대응일 없는 달은 말일까지 근로한 뒤 다음날 권리 발생.
    return date(year, start.month, min(start.day, last)) + timedelta(days=int(start.day > last))


def _month(start, months):
    year, month0 = divmod(start.year * 12 + start.month - 1 + months, 12)
    last = calendar.monthrange(year, month0+1)[1]
    return date(year, month0+1, min(start.day, last)) + timedelta(days=int(start.day > last))


def _count_complete_months(start, end):
    months = (end.year-start.year)*12 + end.month-start.month
    return max(0, months - (_month(start, months) > end))


def _years(start, end):
    years = end.year-start.year
    return max(0, years - (_safe_date(start, years) > end))


def _annual_base(years):
    return min(25, 15 + max(0, years-1)//2)


def _monthly_count(inp, limit, rate):
    value = inp.annual_full_attendance_months
    if value is None:
        if rate < 1:
            raise ValueError("출근율만으로 월별 개근 수를 알 수 없습니다. 산정기간 중 개근한 개월 수를 알려주세요")
        return limit
    return _number(value, "월별 개근 수", hi=limit, integer=True)


def _attendance(inp, start, end):
    """일수는 소정근로일 기준. 단축시간은 출근일수에 더하지 않는다."""
    rate = _number(inp.attendance_rate, "출근율(0~1)", hi=1)
    scheduled, attended = inp.annual_scheduled_days, inp.annual_attended_days
    if (scheduled is None) != (attended is None):
        raise ValueError("출근율 산정을 위해 소정근로일수와 출근일수를 함께 알려주세요")
    if scheduled is not None:
        scheduled = _number(scheduled, "소정근로일수", lo=1, hi=(end-start).days+1)
        attended = _number(attended, "출근일수", hi=scheduled)
    periods = inp.annual_deemed_periods
    if not isinstance(periods, list):
        raise ValueError("출근 간주 기간은 사유와 날짜가 있는 목록으로 입력해주세요")
    intervals, credited, reduced = [], 0, False
    for p in periods:
        if not isinstance(p, dict):
            raise ValueError("출근 간주 기간의 사유와 날짜가 필요합니다")
        a, b = _date(p.get("start_date"), "휴직·단축 시작일"), _date(p.get("end_date"), "휴직·단축 종료일")
        if a > b:
            raise ValueError("휴직·단축 시작일과 종료일의 순서를 확인해주세요")
        kind = p.get("kind")
        if kind in ("childcare_reduced", "pregnancy_reduced"):
            if a < date(2024,10,22):
                raise ValueError("2024-10-22 전에 시작한 단축은 종전 기간별 소정근로시간 자료로 별도 산정해야 합니다")
            if b < start or a > end:
                raise ValueError("단축 기간이 현재 연차 산정기간과 겹치지 않습니다")
            reduced = True
            if p.get("scheduled_days") not in (None, 0):
                raise ValueError("단축시간을 결근일수로 환산하지 않습니다. 단축일은 출근일수에 포함해주세요")
        elif kind in ("childcare_leave", "short_childcare_leave", "occupational_injury", "maternity_leave"):
            if kind in ("childcare_leave", "short_childcare_leave"):
                applied = _date(p.get("application_date"), "육아휴직 최초 신청일")
                if applied > a or applied < date(2018,5,29):
                    raise ValueError("2018-05-29 이후 최초 신청한 법정 육아휴직인지 확인해주세요. 종전 휴직은 별도 산정이 필요합니다")
            if kind == "short_childcare_leave" and (a < date(2026,8,20) or (b-a).days+1 not in (7,14)):
                raise ValueError("단기 육아휴직은 2026-08-20 이후의 1주 또는 2주 법정 사용기간인지 확인해주세요")
            if a < start or b > end:
                raise ValueError("연차 산정기간 안에 해당하는 휴직 구간과 그 구간의 소정근로일수를 나눠 입력해주세요")
            if scheduled is None:
                raise ValueError("휴직 출근 간주를 반영하려면 산정기간의 소정근로일수·실제 출근일수·휴직 중 소정근로일수가 필요합니다")
            credited += _number(p.get("scheduled_days"), "휴직 중 소정근로일수", hi=(b-a).days+1)
        else:
            raise ValueError("출근 간주 사유를 확인해주세요. 일반 결근·개인 휴직을 법정 출근 간주로 바꾸지 않습니다")
        overlap_a, overlap_b = max(a, start), min(b, end)
        if any(overlap_a <= y and overlap_b >= x for x,y in intervals):
            raise ValueError("출근 간주 기간이 중복됩니다. 같은 날을 두 번 더하지 않도록 나눠주세요")
        intervals.append((overlap_a, overlap_b))
    if scheduled is not None:
        if attended + credited > scheduled:
            raise ValueError("실제 출근일수와 출근 간주일수의 합이 소정근로일수를 초과합니다")
        rate = (attended+credited)/scheduled
    return rate, reduced


def _hours(inp, reduced):
    daily = _number(inp.schedule.daily_work_hours, "1일 소정근로시간", lo=.01, hi=24)
    weekly = daily * _number(inp.schedule.weekly_work_days, "주 소정근로일수", lo=.01, hi=7)
    if reduced:
        daily = _number(inp.annual_original_daily_hours, "단축 전 1일 소정근로시간", lo=.01, hi=8)
        weekly = _number(inp.annual_original_weekly_hours, "단축 전 주 소정근로시간", lo=.01, hi=40)
    return daily, weekly


def _leave_hours(days, weekly, daily):
    # 시행령 별표2 제4호: 단시간 연차는 시간 단위, 1시간 미만 올림.
    hours = days*daily if weekly >= FULL_TIME_WEEKLY_HOURS else math.ceil(
        round(days*weekly/FULL_TIME_WEEKLY_HOURS*FULL_TIME_DAILY_HOURS, 10))
    return hours, hours/daily


def _first_year_schedule(start, end):
    rows = []
    anniversary = _safe_date(start,1)
    for month in range(1,12):
        grant = _month(start,month)
        if grant > end:
            break
        rule = split_effective_periods(grant,grant+timedelta(days=1),MONTHLY_EXPIRY_RULES)[0].rule
        expiry = anniversary if rule.values["first_anniversary"] else _safe_date(grant,1)
        rows.append(dict(period=f"첫해 {month}개월", kind="monthly", accrual_date=grant.isoformat(),
                         days=1, pay_trigger_date=expiry.isoformat(), expires_on=(expiry-timedelta(days=1)).isoformat(),
                         note="해당 월 개근 시 발생(월별 출근 자료 확인 필요)", conditional=True))
    return rows


def calc_annual_leave(inp: WageInput, ow: OrdinaryWageResult) -> AnnualLeaveResult:
    legal = ["근로기준법 제60조 (연차 유급휴가)"]
    if inp.business_size == BusinessSize.UNDER_5:
        return AnnualLeaveResult(is_eligible=False, breakdown={"법정 연차": "5인 미만 사업장 적용 제외"},
                                 warnings=["별도 약정휴가는 취업규칙·근로계약을 확인해주세요"],
                                 legal_basis=legal+["근로기준법 제11조"])
    try:
        return _calculate(inp,ow,legal)
    except ValueError as exc:
        return AnnualLeaveResult(held_reason=str(exc), warnings=[str(exc)], legal_basis=legal)


def _calculate(inp, ow, legal):
    start = _date(inp.start_date, "입사일")
    end = _date(inp.end_date, "계산 종료일") if inp.end_date else _date(
        resolve_reference_date(inp.reference_date, inp.reference_year), "계산 기준일")
    last = _date(inp.last_employed_date, "마지막 재직일") if inp.last_employed_date else None
    if last and last < start:
        raise ValueError("마지막 재직일이 입사일보다 빠릅니다")
    if last:
        end = min(end,last)
    if end < start:
        raise ValueError("계산 종료일이 입사일보다 빠릅니다")
    if end < date(2014,7,1):
        raise ValueError("2014-07-01 이전 연차는 검증된 법령 판본을 확인한 뒤 별도 산정해야 합니다")
    years = _years(start,end)
    grant = _safe_date(start,years)
    if years and grant < date(2014,7,1):
        raise ValueError("실제 연차 발생일이 2014-07-01 전입니다. 해당 발생일의 법령 판본 확인이 필요합니다")
    if not years and _month(start,1) < date(2014,7,1):
        raise ValueError("첫해 월별 발생분에 2014-07-01 전 기간이 포함됩니다. 당시 판본 확인이 필요합니다")
    assessment_start = _safe_date(start,years-1) if years else start
    assessment_end = grant-timedelta(days=1) if years else end
    if inp.use_fiscal_year:
        if inp.fiscal_year_granted_days is None:
            raise ValueError("회사 회계연도 규정으로 해당 연도에 실제 부여한 연차일수가 필요합니다. 입사일 기준 법정 발생분과 퇴직 시 누적 대조도 필요합니다")
        assessment_start, assessment_end = max(start,date(end.year-1,1,1)), date(end.year,1,1)-timedelta(days=1)
        if assessment_end < assessment_start:
            assessment_start, assessment_end = start,end
    rate, reduced = _attendance(inp,assessment_start,assessment_end)
    daily,weekly = _hours(inp,reduced)
    if weekly < 15:
        return AnnualLeaveResult(is_eligible=False,is_part_time_ratio=True,part_time_ratio=0,
            breakdown={"법정 연차": "4주 평균 주 소정근로시간 15시간 미만: 미발생"},
            warnings=["입력한 소정근로시간이 산정기간에 동일하다는 전제입니다"],
            legal_basis=legal+["근로기준법 제18조 제3항"])
    used = _number(inp.annual_leave_used,"현재 기간 사용 연차")
    first_used = (_number(inp.first_year_leave_used,"첫해 사용 연차")
                  if inp.first_year_leave_used is not None else None)
    first_input_hours = (_number(inp.first_year_leave_used_hours,"첫해 실제 사용 연차시간")
                         if inp.first_year_leave_used_hours is not None else None)
    if first_input_hours is not None:
        first_used = first_input_hours/daily
    first_count = inp.first_year_full_attendance_months
    if first_count is not None:
        _number(first_count,"첫해 개근 수",hi=min(11,_count_complete_months(start,end)),integer=True)
    deducted = 0
    if inp.use_fiscal_year:
        days = _number(inp.fiscal_year_granted_days,"회사 부여 연차",hi=366)
        pay_date = date(end.year+1,1,1)
    elif years == 0:
        days = _monthly_count(inp,min(11,_count_complete_months(start,end)),rate)
        first_count = days
        pay_date = _safe_date(start,1)
    elif rate < .8:
        days = _monthly_count(inp,12,rate)
        # 법제처24-0674: 전년도 개근 월 수에 따른 휴가는 다음 연도에 발생.
        pay_date = _safe_date(start,years+1)
        legal += ["법제처 법령해석 24-0674 (2024-11-04)", "https://opinion.lawmaking.go.kr/nl4li/lsItptEmp/444315"]
    else:
        days = _annual_base(years)
        pay_date = _safe_date(start,years+1)
        if years == 1 and start < date(2017,5,30):
            if first_used is None:
                raise ValueError("개정 전 최초 1년분 계산에는 실제 첫해 사용분이 필요합니다")
            deducted = first_used
            legal += ["개정 전 근로기준법 제60조 제3항 (2017-05-30 전 입사자의 최초 1년분)", HISTORY_URL]
    accrued_hours,accrued_days = _leave_hours(days,weekly,daily)
    monthly_grants = not inp.use_fiscal_year and years == 0
    if monthly_grants:
        accrued_hours = _leave_hours(1,weekly,daily)[0]*days
        accrued_days = accrued_hours/daily
    if inp.use_fiscal_year:
        accrued_days, accrued_hours = days, days*daily
    if deducted:
        if deducted*daily > accrued_hours:
            raise ValueError("개정 전 첫해 사용분이 발생 한도를 초과합니다")
        accrued_hours -= deducted*daily
        accrued_days = accrued_hours/daily
    current_input_hours = inp.annual_leave_used_hours
    if years == 0 and first_input_hours is not None:
        if current_input_hours is not None and current_input_hours != first_input_hours:
            raise ValueError("첫해 실제 사용 연차시간이 두 입력에서 다릅니다")
        current_input_hours = first_input_hours
    if current_input_hours is not None:
        used_hours = _number(current_input_hours,"실제 사용 연차시간")
        used = used_hours/daily
    else:
        if years == 0 and first_used:
            if used and used != first_used:
                raise ValueError("첫해 사용 연차가 두 입력에서 다릅니다. 동일한 첫해 사용분을 확인해주세요")
            used = first_used
        if reduced and used:
            raise ValueError("단축 중 사용 연차는 실제 차감한 시간을 알려주세요. 발생 1일과 사용 1일의 시간이 다를 수 있습니다")
        used_hours = used*daily
    if used_hours > accrued_hours:
        raise ValueError("사용 연차가 현재 기간 발생분보다 많습니다. 이월·선사용 또는 다른 기간의 사용분인지 확인해주세요")
    remaining_hours = accrued_hours-used_hours
    if years == 0:
        first_used = used  # 동일 첫해 장부. 호환 입력 둘을 중복 합산하지 않음
    first_hours = first_count*_leave_hours(1,weekly,daily)[0] if first_count is not None else None
    if years == 0:
        first_used_hours = used_hours
    elif inp.first_year_leave_used_hours is not None:
        first_used_hours = _number(inp.first_year_leave_used_hours,"첫해 실제 사용 연차시간")
        first_used = first_used_hours/daily
    else:
        first_used_hours = first_used*daily if first_used is not None and not reduced else None
    if first_hours is not None and first_used_hours is not None and first_used_hours > first_hours:
        raise ValueError("첫해 사용분이 첫해 발생분을 초과합니다. 이월·선사용 여부를 확인해주세요")
    rows = _first_year_schedule(start,end) if start >= date(2014,7,1) else []
    if years == 0 and not inp.use_fiscal_year:
        expiry_dates = {r["pay_trigger_date"] for r in rows}
        pay_date = _date(next(iter(expiry_dates)),"월별 소멸일") if len(expiry_dates) == 1 else None
    for y in range(1,years+1):
        if _safe_date(start,y) < date(2014,7,1):
            continue
        row_days = _annual_base(y)
        old = (first_used or 0) if y == 1 and start < date(2017,5,30) else 0
        current = y == years and not inp.use_fiscal_year
        if current:
            row_days = days
        row_hours,row_equiv = _leave_hours(row_days,weekly,daily)
        if old:
            row_hours = max(0,row_hours-old*daily)
            row_equiv = row_hours/daily
        if current:
            row_hours,row_equiv = accrued_hours,accrued_days
        rows.append(dict(period=f"{y+1}년차",kind="annual",accrual_date=_safe_date(start,y).isoformat(),
                         days=round(row_equiv,2), hours=row_hours,
                         pay_trigger_date=_safe_date(start,y+1).isoformat(),
                         note=("현재 산정기간 출근자료 반영" if current else "출근율 80% 이상·동일 소정시간 가정의 참고값"),
                         conditional=not current))
    if inp.use_fiscal_year:
        rows.append(dict(period=f"{end.year}년 회사 부여",kind="company",days=accrued_days,
                         hours=accrued_hours,accrual_date="",pay_trigger_date=str(pay_date),
                         conditional=False,note="입력한 회사 실제 부여분. 법정 기준 충족 판정은 별도"))
    warnings = ["사용촉진·사용자 귀책·이월 약정은 별도 확인이 필요합니다",
                "연도별 과거 행은 해당 연도 출근·시간 자료가 없는 경우 조건부 참고값이며 실제 누적 채권이 아닙니다"]
    if years == 0 and rate < 1:
        for row in rows:
            row["days"] = None
            row["note"] = "개근한 월의 날짜가 없어 개별 발생·소멸일 확정 보류"
    if reduced:
        legal += ["근로기준법 제60조 제6항 제4·5호, 법률 제20520호 부칙 제6조",REDUCED_URL]
        warnings.append("단축 전 소정시간이 산정기간의 기준이라는 전제입니다. 단축시간은 결근일수로 환산하지 않습니다")
    if inp.annual_deemed_periods:
        legal.append("근로기준법 제60조 제6항 (출근 간주)")
    if not pay_date:
        warnings.append("단일 정산일로 표시할 수 없습니다. 월별 발생·소멸 일정과 사용 귀속을 확인해주세요")
    if weekly < 40:
        legal.append("근로기준법 시행령 별표 2 제4호 (시간 비례·1시간 미만 올림)")
    pay_due = last is not None and end == last
    if pay_due:
        pay_date = last+timedelta(days=1)
    leave_pay = remaining_hours*ow.hourly_ordinary_wage
    if inp.leave_use_promotion:
        leave_pay = 0
        warnings.append("법정 사용촉진 절차가 적법하게 완료되고 사용 기회가 보장된 경우에 한해 수당 면제 가정")
    if not pay_due:
        warnings.append("현재 잔여분의 입력 통상시급 기준 평가액입니다. 사용기간 만료·퇴직 전 확정 지급채권으로 보지 않습니다")
    if inp.use_fiscal_year:
        warnings.append("회사 부여일수를 사용했습니다. 퇴직 시 입사일 기준과 회사 기준의 누적 발생·사용·기지급 내역을 대조해야 합니다")
    first_remaining_hours = (first_hours-first_used_hours
                             if first_hours is not None and first_used_hours is not None else None)
    first_days = first_hours/daily if first_hours is not None else None
    first_remaining = first_remaining_hours/daily if first_remaining_hours is not None else None
    first_settlement = (first_remaining if first_remaining is not None and
                        start >= date(2020,3,1) and end >= _safe_date(start,1) else None)
    breakdown = {
        "발생 연차": f"{accrued_days:.1f}일 ({accrued_hours:g}시간)",
        "사용 연차": f"{used:.1f}일 ({used_hours:g}시간)",
        "미사용 연차": f"{remaining_hours/daily:.1f}일 ({remaining_hours:g}시간)",
        "일수의 단위": f"발생 기준 1일 = {daily:g}시간",
        "출근율 산정기간": f"{assessment_start} ~ {assessment_end}",
        "법정 출근 간주 반영 출근율": f"{rate*100:.2f}%",
        "연차수당 평가액" if not pay_due else "퇴직 시 현재 기간 미사용수당": f"{leave_pay:,.0f}원",
        "정산 시점": (str(pay_date) if pay_date else "월별 발생·소멸 일정과 사용 귀속 확인 필요") + " (사용촉진·귀책·이월 및 당시 임금 확인 필요)",
    }
    if first_remaining is not None and years:
        breakdown["별도 첫해 장부"] = f"발생 {first_days:g}일({first_hours:g}시간) · 사용 {first_used:g}일({first_used_hours:g}시간) · 잔여 {first_remaining:g}일({first_remaining_hours:g}시간) (현재 기간에서 다시 차감하지 않음)"
    elif years:
        breakdown["별도 첫해 장부"] = "첫해 월별 개근·사용 자료가 부족해 미사용 정산분 확정 보류"
    if inp.use_fiscal_year:
        breakdown["발생 기준"] = "회사 회계연도 규정의 실제 부여일수"
    if deducted:
        breakdown["과거 규정 공제"] = f"첫해 사용 {deducted:g}일 (2017-05-30 전 입사)"
    return AnnualLeaveResult(
        accrued_days=round(accrued_days,2), used_days=round(used,2), remaining_days=round(remaining_hours/daily,2),
        accrued_hours=accrued_hours,used_hours=used_hours,remaining_hours=remaining_hours,day_hours=daily,
        annual_leave_pay=round(leave_pay),service_years=round((end-start).days/365.2425,2),
        deducted_days=deducted,schedule=rows,is_part_time_ratio=weekly<40,
        part_time_ratio=round(accrued_days/days,4) if days else 1,is_eligible=True,
        effective_attendance_rate=rate,assessment_start=str(assessment_start),assessment_end=str(assessment_end),
        pay_due=pay_due,pay_trigger_date=str(pay_date) if pay_date else "",first_year_accrued_days=first_days,
        first_year_used_days=first_used,first_year_remaining_days=first_remaining,first_year_settlement_days=first_settlement,
        first_year_accrued_hours=first_hours,first_year_used_hours=first_used_hours,
        first_year_remaining_hours=first_remaining_hours,accrual_basis="company" if inp.use_fiscal_year else "statutory",
        breakdown=breakdown,formulas=[f"미사용 연차수당: {ow.hourly_ordinary_wage:,.0f}원 × {remaining_hours:g}시간 = {leave_pay:,.0f}원"],
        warnings=warnings,legal_basis=legal)
