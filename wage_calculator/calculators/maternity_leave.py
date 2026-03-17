"""
출산전후휴가급여 계산기 (고용보험법 제75조, 근로기준법 제74조)

핵심 계산식:
  출산전후휴가: 90일 (다태아 120일)
  급여 기간:
    - 우선지원대상기업(중소기업): 90일 전액 고용보험 지원
    - 대규모 기업: 최초 60일은 사업주 부담, 61일~90일만 고용보험
  급여액:
    - 통상임금 100% (최초 60일, 우선지원은 90일 전체)
    - 상한: 약 2,094,000원/월 (2025년 기준, 매년 고시)
    - 하한: 최저임금액 이상 (근로기준법 보장)

  배우자 출산휴가: 10일 유급 = 통상임금 × 10일분
    (고용보험법 제75조의2, 우선지원대상기업은 5일분 고용보험 지원)
"""

from dataclasses import dataclass

from ..base import BaseCalculatorResult
from ..models import WageInput
from .ordinary_wage import OrdinaryWageResult
from ..constants import MINIMUM_HOURLY_WAGE

# ── 연도별 출산전후휴가급여 상한액 (월 기준) ─────────────────────────────────
# 고용노동부 고시. 근로기준법 제74조, 고용보험법 제75조
# 상한액 = 최저임금 × 통상근로 1개월 시간(209h) × 일정 배수 → 실무 고시값 사용
MATERNITY_LEAVE_UPPER: dict[int, float] = {
    2023: 2_009_080,   # 2023년 최저임금 9,620 × 209h
    2024: 2_060_740,   # 2024년 최저임금 9,860 × 209h
    2025: 2_096_270,   # 2025년 최저임금 10,030 × 209h
    2026: 2_156_880,   # 2026년 최저임금 10,320 × 209h
}


@dataclass
class MaternityLeaveResult(BaseCalculatorResult):
    # 출산전후휴가 급여
    leave_days: int = 0                        # 총 휴가 일수 (90 또는 120)
    monthly_benefit: float = 0.0               # 월 급여액 (상한 적용 후)
    raw_monthly_wage: float = 0.0              # 월 통상임금 (상한 적용 전)

    # 기업 유형별 부담 구조
    is_priority_support: bool = False          # 우선지원대상기업(중소기업) 여부
    insurance_covered_days: int = 0            # 고용보험 지원 일수
    employer_covered_days: int = 0             # 사업주 부담 일수

    # 총 급여
    total_insurance_benefit: float = 0.0       # 고용보험 지급 총액
    total_employer_benefit: float = 0.0        # 사업주 부담 총액

    # 배우자 출산휴가
    spouse_leave_days: int = 0                 # 배우자 출산휴가 일수 (10일)
    spouse_leave_pay: float = 0.0              # 배우자 출산휴가 급여

    upper_limit_applied: bool = False


def calc_maternity_leave(inp: WageInput, ow: OrdinaryWageResult) -> MaternityLeaveResult:
    """
    출산전후휴가급여 계산

    Args:
        inp: 임금 입력 데이터
          - is_priority_support_company: 우선지원대상기업 여부 (기본 True)
          - is_multiple_birth: 다태아 여부 (기본 False)
        ow: 통상임금 계산 결과
    """
    warnings = []
    formulas = []
    legal = [
        "근로기준법 제74조 (출산전후휴가)",
        "고용보험법 제75조 (출산전후휴가급여)",
    ]

    year = inp.reference_year
    is_priority = getattr(inp, "is_priority_support_company", True)
    is_multiple  = getattr(inp, "is_multiple_birth", False)

    # ── 휴가 일수 결정 ────────────────────────────────────────────────────
    leave_days = 120 if is_multiple else 90
    if is_multiple:
        formulas.append(f"다태아 출산전후휴가: {leave_days}일")
        legal.append("근로기준법 제74조제1항 (다태아 120일)")
    else:
        formulas.append(f"출산전후휴가: {leave_days}일")

    # ── 상한액 조회 ─────────────────────────────────────────────────────
    is_pw = getattr(inp, "is_platform_worker", False)
    if is_pw:
        from ..constants import PLATFORM_MATERNITY_UPPER, PLATFORM_INSURED_REQ_MONTHS
        upper = PLATFORM_MATERNITY_UPPER
        legal.append("고용보험법 제77조의3 (노무제공자 출산전후휴가급여)")
        # 노무제공자 수급요건: 피보험 3개월 이상
        pw_months = getattr(inp, "platform_insured_months", 0)
        if pw_months < 3:
            warnings.append(
                f"노무제공자 출산전후휴가급여 수급요건 미충족: "
                f"피보험기간 {pw_months}개월 < 3개월. "
                "출산일 전 피보험 단위기간 3개월 이상 필요합니다."
            )
    else:
        upper = MATERNITY_LEAVE_UPPER.get(year, MATERNITY_LEAVE_UPPER[2025])

    # ── 월 급여 계산 ─────────────────────────────────────────────────────
    if is_pw:
        pw_income = getattr(inp, "platform_monthly_income", None) or ow.monthly_ordinary_wage
        monthly_ow = pw_income  # 직전 1년 월 평균 보수 100%
    else:
        monthly_ow = ow.monthly_ordinary_wage
    upper_applied = monthly_ow > upper
    monthly_benefit = min(monthly_ow, upper)

    if upper_applied:
        formulas.append(
            f"출산전후휴가급여: 통상임금 {monthly_ow:,.0f}원 → 상한 {upper:,.0f}원 적용"
        )
    else:
        formulas.append(
            f"출산전후휴가급여: 통상임금 {monthly_ow:,.0f}원 (100%) = {monthly_benefit:,.0f}원/월"
        )

    # 최저임금 하한 체크
    min_hourly = MINIMUM_HOURLY_WAGE.get(year, MINIMUM_HOURLY_WAGE[2025])
    min_monthly = min_hourly * 209
    if monthly_benefit < min_monthly:
        monthly_benefit = min_monthly
        warnings.append(
            f"출산전후휴가급여가 최저임금 월액({min_monthly:,.0f}원) 미만 → 최저임금 보장"
        )

    # ── 기업 유형별 부담 구조 ─────────────────────────────────────────────
    if is_priority:
        # 우선지원대상기업: 전 기간(90일) 고용보험 지원
        insurance_days = leave_days
        employer_days  = 0
        formulas.append(
            f"우선지원대상기업: {leave_days}일 전액 고용보험 지원"
        )
        legal.append("고용보험법 제75조제1항 (우선지원대상기업 전액 지원)")
    else:
        # 대규모 기업: 최초 60일 사업주 부담, 이후만 고용보험
        employer_days  = min(60, leave_days)
        insurance_days = max(0, leave_days - 60)
        formulas.append(
            f"대규모 기업: 최초 {employer_days}일 사업주 부담, "
            f"이후 {insurance_days}일 고용보험 지원"
        )
        legal.append("고용보험법 제75조제2항 (대규모 기업)")
        warnings.append(
            "대규모 기업(우선지원대상기업 제외): 최초 60일은 사업주가 통상임금 100% 지급, "
            "61일~90일만 고용보험에서 지급 (상한 적용)"
        )

    # ── 일 환산 급여 (월 급여 → 일 급여) ────────────────────────────────
    daily_benefit = monthly_benefit * 12 / 365  # 연간 → 일 환산

    total_insurance_benefit = daily_benefit * insurance_days
    total_employer_benefit  = daily_benefit * employer_days
    total_benefit = total_insurance_benefit + total_employer_benefit

    formulas.append(
        f"일 급여: {monthly_benefit:,.0f}원/월 × 12 ÷ 365 = {daily_benefit:,.0f}원/일"
    )
    formulas.append(
        f"고용보험 지급 총액: {daily_benefit:,.0f}원 × {insurance_days}일 = {total_insurance_benefit:,.0f}원"
    )
    if employer_days > 0:
        formulas.append(
            f"사업주 부담 총액: {daily_benefit:,.0f}원 × {employer_days}일 = {total_employer_benefit:,.0f}원"
        )

    # ── 배우자 출산휴가 (10일) ────────────────────────────────────────────
    spouse_days = 10
    daily_ordinary = ow.hourly_ordinary_wage * inp.schedule.daily_work_hours
    spouse_pay = daily_ordinary * spouse_days

    formulas.append(
        f"배우자 출산휴가(10일): {daily_ordinary:,.0f}원/일 × {spouse_days}일 = {spouse_pay:,.0f}원"
    )
    legal.append("남녀고용평등법 제18조의2 (배우자 출산휴가)")

    if is_priority:
        spouse_insurance_days = 5
        warnings.append(
            f"우선지원대상기업: 배우자 출산휴가 {spouse_insurance_days}일분 "
            f"({daily_ordinary * spouse_insurance_days:,.0f}원) 고용보험 지원 가능"
        )

    warnings.append("수급 요건: 출산 전 피보험기간 180일 이상 (고용보험법 제75조)")
    warnings.append(f"신청 기한: 출산전후휴가 종료 후 12개월 이내")

    breakdown = {
        "월 통상임금": f"{monthly_ow:,.0f}원",
        "월 급여(상한 적용)": f"{monthly_benefit:,.0f}원",
        "총 휴가 일수": f"{leave_days}일 {'(다태아)' if is_multiple else ''}",
        "기업 유형": "우선지원대상기업(중소기업)" if is_priority else "대규모 기업",
        "고용보험 지원 일수": f"{insurance_days}일",
        "사업주 부담 일수": f"{employer_days}일",
        "고용보험 지급 총액": f"{total_insurance_benefit:,.0f}원",
        "사업주 부담 총액": f"{total_employer_benefit:,.0f}원",
        "배우자 출산휴가(10일)": f"{spouse_pay:,.0f}원",
        "상한액": f"{upper:,.0f}원/월 ({year}년 기준)",
        "상한 적용": "✅" if upper_applied else "미적용",
    }

    return MaternityLeaveResult(
        leave_days=leave_days,
        monthly_benefit=round(monthly_benefit),
        raw_monthly_wage=monthly_ow,
        is_priority_support=is_priority,
        insurance_covered_days=insurance_days,
        employer_covered_days=employer_days,
        total_insurance_benefit=round(total_insurance_benefit),
        total_employer_benefit=round(total_employer_benefit),
        spouse_leave_days=spouse_days,
        spouse_leave_pay=round(spouse_pay),
        upper_limit_applied=upper_applied,
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )
