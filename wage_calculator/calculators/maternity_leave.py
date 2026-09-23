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
from ..legal_rules import managed, parameter, RuleUnavailable

# ── 연도별 출산전후휴가급여 상한액 (월 기준) ─────────────────────────────────
# 고용노동부 고시「출산전후휴가 급여등 상한액」. 고용보험법 시행령 제101조제1호가 금액을
# **고시로 위임**한다 — 최저임금 × 209h 는 이 표의 옛 관례였을 뿐 고시값이 아니었고,
# 그래서 전 연도가 과소였다(2026년 실측: 2,156,880 vs 고시 2,200,000).
#
# 고시는 기간 총액으로 쓰지만 내부 산식은 **월 상한 ÷ 30 × 일수**다. 2026년 고시로 검증:
#   90일 660만 = 220만×3 ✓ / 120일(다태아) 880만 = 220만×4 ✓ / 100일(미숙아) 7,333,330 ✓
# 그래서 표는 월 상한을 유지한다 — 승인 저장소 키(`maternity.monthly_upper`)의 의미와도 같다.
MATERNITY_LEAVE_UPPER: dict[int, float] = {
    2023: 2_100_000,   # 90일 630만원
    2024: 2_100_000,   # 90일 630만원 (동결)
    2025: 2_100_000,   # 90일 630만원 (동결)
    2026: 2_200_000,   # 90일 660만원 — 고용노동부고시 제2025-124호(시행 2026-01-01)
}

# 고시가 기간 총액을 월 상한에서 환산할 때 쓰는 기준 일수. 연 365일 환산(×12/365)이 아니다 —
# 그렇게 하면 90일 총액이 638만원이 되어 고시 660만원에 217,999원 못 미친다(실측).
MATERNITY_DAYS_PER_MONTH = 30

# ── 배우자 출산휴가 (남녀고용평등법 제18조의2) ───────────────────────────────
# 2025-02-23 개정 시행으로 10일 → **20일**, 고용보험 지원도 5일분 → 20일분 전부로 확대됐다
# (고용노동부 work24 제도안내). 연중 바뀌므로 시행일 구간으로 둔다.
SPOUSE_LEAVE_DAYS_PERIODS: dict[str, int] = {
    "2019-10-01": 10,
    "2025-02-23": 20,
}

# 배우자 출산휴가 급여 상한(전체 기간분). 출산전후휴가와 **일당 기준이 다르다** —
# 2026년 고시 기준 배우자는 1일 84,210원(1,684,210 ÷ 20)이고 출산전후휴가는 73,333원이다.
SPOUSE_LEAVE_UPPER: dict[int, float] = {
    2026: 1_684_210,   # 20일분 — 고용노동부고시 제2025-124호
}


def spouse_leave_days(reference_date: str | None, year: int) -> int:
    """그 시점의 배우자 출산휴가 일수. 날짜가 없으면 그 해 1월 1일 기준으로 읽는다."""
    day = reference_date or f"{int(year):04d}-01-01"
    started = [start for start in SPOUSE_LEAVE_DAYS_PERIODS if start <= day]
    return SPOUSE_LEAVE_DAYS_PERIODS[max(started)] if started else min(
        SPOUSE_LEAVE_DAYS_PERIODS.values())


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
        upper = parameter("maternity.platform_upper", PLATFORM_MATERNITY_UPPER)
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
        # 폴백은 **최신 연도**다(get_minimum_hourly_wage·get_insurance_rates와 같은 규약).
        # 2025 고정이면 표에 없는 미래 연도가 2025년 상한으로 떨어지고, 관리 화면의
        # '현재 적용값'과도 갈린다 — 실측 2027년: 미리보기 2,156,880 vs 계산 2,096,270.
        upper = parameter("maternity.monthly_upper", MATERNITY_LEAVE_UPPER.get(
            year, MATERNITY_LEAVE_UPPER[max(MATERNITY_LEAVE_UPPER)]))

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

    # 최저임금 하한 체크 (노무제공자는 고용보험 상한만 적용, 근기법 최저임금 보장 대상 아님)
    if not is_pw:
        min_hourly = parameter("minimum_hourly_wage", MINIMUM_HOURLY_WAGE.get(year, MINIMUM_HOURLY_WAGE[2025]))
        min_monthly = min_hourly * 209
        if min_monthly > upper:
            # 내장표 경로에서는 대부분 "그 해 상한 고시가 아직 표에 없다"는 데이터 지연이다.
            # 최저임금표만 먼저 갱신되면(2027년이 그랬다) 새 하한이 옛 상한을 넘어 이 조건이
            # 참이 된다. 그때 "승인 상한/하한" 문구를 내면 관리 모드를 쓰지도 않는 운영자에게
            # 없는 설정 문제를 찾게 만든다 — 실제 원인을 그대로 말한다.
            # 관리 모드에서는 상한이 **승인값**이므로 그 설명이 성립하지 않는다.
            if not managed() and year not in MATERNITY_LEAVE_UPPER:
                raise RuleUnavailable(
                    f"{year}년 출산전후휴가급여 상한액 고시가 등록되지 않았습니다"
                    f"(등록된 최신 연도 {max(MATERNITY_LEAVE_UPPER)}년). "
                    "고용노동부 고시를 확인해 상한액을 갱신해야 계산할 수 있습니다"
                )
            raise RuleUnavailable(
                f"출산전후휴가급여 승인 하한({min_monthly:,.0f}원)이 "
                f"승인 상한({upper:,.0f}원)보다 높습니다. 관리자 확인이 필요합니다"
            )
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
    # 고시가 기간 총액을 산정하는 방식과 같아야 한다(월 상한 ÷ 30 × 일수). 연 365일 환산은
    # 90일 총액을 638만원으로 만들어 고시 660만원에 못 미친다.
    daily_benefit = monthly_benefit / MATERNITY_DAYS_PER_MONTH

    total_insurance_benefit = daily_benefit * insurance_days
    total_employer_benefit  = daily_benefit * employer_days
    total_benefit = total_insurance_benefit + total_employer_benefit

    formulas.append(
        f"일 급여: {monthly_benefit:,.0f}원/월 ÷ {MATERNITY_DAYS_PER_MONTH}일 = {daily_benefit:,.0f}원/일"
    )
    formulas.append(
        f"고용보험 지급 총액: {daily_benefit:,.0f}원 × {insurance_days}일 = {total_insurance_benefit:,.0f}원"
    )
    if employer_days > 0:
        formulas.append(
            f"사업주 부담 총액: {daily_benefit:,.0f}원 × {employer_days}일 = {total_employer_benefit:,.0f}원"
        )

    # ── 배우자 출산휴가 ───────────────────────────────────────────────────
    spouse_days = spouse_leave_days(getattr(inp, "reference_date", None), year)
    daily_ordinary = ow.hourly_ordinary_wage * inp.schedule.daily_work_hours
    spouse_pay = daily_ordinary * spouse_days
    spouse_upper = SPOUSE_LEAVE_UPPER.get(year)
    if spouse_upper is not None and spouse_pay > spouse_upper:
        formulas.append(
            f"배우자 출산휴가({spouse_days}일): {daily_ordinary:,.0f}원/일 × {spouse_days}일 "
            f"→ 상한 {spouse_upper:,.0f}원 적용"
        )
        spouse_pay = spouse_upper
    else:
        formulas.append(
            f"배우자 출산휴가({spouse_days}일): {daily_ordinary:,.0f}원/일 × {spouse_days}일 = {spouse_pay:,.0f}원"
        )
        if spouse_upper is None:
            warnings.append(
                f"{year}년 배우자 출산휴가 급여 상한액 고시가 등록되지 않아 상한을 적용하지 않았습니다"
                f"(등록된 최신 연도 {max(SPOUSE_LEAVE_UPPER)}년). 실제 지급액은 상한에 걸릴 수 있습니다"
            )
    legal.append("남녀고용평등법 제18조의2 (배우자 출산휴가)")

    if is_priority:
        # 2025-02-23 개정으로 고용보험 지원이 5일분 → 휴가 전 기간으로 확대됐다.
        warnings.append(
            f"우선지원대상기업: 배우자 출산휴가 {spouse_days}일분 "
            f"({spouse_pay:,.0f}원) 고용보험 지원 대상 (사업주가 이미 지급했으면 차액만 지급)"
        )
    else:
        warnings.append(
            f"우선지원대상기업이 아니면 배우자 출산휴가 {spouse_days}일은 사업주가 전액 유급으로 부담합니다"
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
        f"배우자 출산휴가({spouse_days}일)": f"{spouse_pay:,.0f}원",
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
