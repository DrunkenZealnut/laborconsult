"""
연차수당 계산기 (근로기준법 제60조)

수요: 81건 (3.1%)

핵심 규칙:
- 1년 미만: 매월 개근 시 1일 발생 (최대 11일)
- 1년 이상: 15일 기본 + 매 2년마다 1일 추가 (최대 25일)
- 연차수당 = 통상시급 × 8h × 미사용 연차일수
- 5인 미만 사업장: 2021.01.01부터 연차휴가 미적용 (별도 경과 규정)

사용촉진제도 (근로기준법 제61조):
- 사용자가 규정 절차에 따라 사용촉진 조치를 한 경우,
  근로자가 미사용한 연차에 대해 수당 지급 의무 면제
- 절차: ① 만료 6개월 전 서면 통보 → ② 근로자 10일 이내 시기 지정
       → ③ 미지정 시 사용자가 시기 지정(만료 2개월 전까지)
- 1년 미만 발생 연차: 만료 3개월 전 통보 기준 적용
- leave_use_promotion=True이면 수당 지급 의무 없음으로 처리
"""

from dataclasses import dataclass

from ..base import BaseCalculatorResult
from ..utils import parse_date
from datetime import date
from ..models import WageInput, BusinessSize
from .ordinary_wage import OrdinaryWageResult
from ..constants import (
    ANNUAL_LEAVE_BASE_DAYS,
    ANNUAL_LEAVE_MAX_DAYS,
    ANNUAL_LEAVE_ADD_YEARS,
    ANNUAL_LEAVE_ADD_MAX,
    ANNUAL_LEAVE_FIRST_YEAR_MAX,
)


@dataclass
class AnnualLeaveResult(BaseCalculatorResult):
    accrued_days: float = 0.0        # 발생 연차 일수
    used_days: float = 0.0           # 사용 연차 일수
    remaining_days: float = 0.0      # 미사용 연차 일수
    annual_leave_pay: float = 0.0    # 미사용 연차수당 (원)
    service_years: float = 0.0       # 재직 연수


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

    # 연차 발생 계산 (역월 기준 완성 달 수 사용)
    accrued = _calc_accrued_days(service_days, service_years, inp.attendance_rate, start, end)

    # 연차수당
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
    if breakdown_promotion:
        breakdown["사용촉진제도"] = breakdown_promotion

    return AnnualLeaveResult(
        accrued_days=round(accrued, 1),
        used_days=used,
        remaining_days=round(remaining, 1),
        annual_leave_pay=round(leave_pay, 0),
        service_years=round(service_years, 2),
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )


def _calc_accrued_days(
    service_days: int,
    service_years: float,
    attendance_rate: float,
    start: "date | None" = None,
    end: "date | None" = None,
) -> float:
    """연차 발생일수 계산"""
    if service_years < 1:
        # 1년 미만: 매월 개근 시 1일 (최대 11일)
        # 역월(曆月) 기준 완성된 달 수 사용 — service_days//30 보정
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
        accrued = min(ANNUAL_LEAVE_BASE_DAYS + extra_days, ANNUAL_LEAVE_MAX_DAYS)

        # 출근율 80% 미만이면 발생 안 함
        if attendance_rate < 0.8:
            accrued = 0

    return float(accrued)


def _count_complete_months(start: "date", end: "date") -> int:
    """역월(曆月) 기준 완성된 달 수 계산

    예: 2024-01-01 ~ 2024-07-15 → 6개월 완성 (7월은 진행 중)
        2024-01-01 ~ 2024-07-01 → 6개월 완성 (7월 1일 시작 = 완성 아님)
        2024-01-15 ~ 2024-07-15 → 6개월 완성
    """
    months = (end.year - start.year) * 12 + (end.month - start.month)
    # 같은 날짜(일)에 도달했으면 해당 달까지 완성, 아직 못 미쳤으면 1개월 빼기
    if end.day < start.day:
        months -= 1
    return max(0, months)


