"""
출산전후휴가급여 계산기 (고용보험법 제75조, 근로기준법 제74조)

핵심 계산식:
  출산전후휴가: 90일 (미숙아 100일 · 다태아 120일, 둘 다면 긴 쪽)
  급여 기간:
    - 우선지원대상기업(중소기업): 90일 전액 고용보험 지원
    - 대규모 기업: 최초 60일은 사업주 부담, 61일~90일만 고용보험
  급여액:
    - 통상임금 100% (최초 60일, 우선지원은 90일 전체)
    - 상한: 고용노동부 고시(2026년 월 220만원 = 90일 660만원). 기간 총액은 월 상한 ÷ 30 × 일수
    - 하한: 최저임금액 이상 (근로기준법 보장)

  배우자 출산휴가(남녀고용평등법 제18조의2): 2025-02-23부터 20일 유급(종전 10일).
    **유급 의무는 사업주**에게 있고, 우선지원대상기업이면 그중 일부를 고용보험이 급여로
    지원한다(종전 5일분 → 현재 전 기간, 고시 상한 적용, 차액은 사업주 부담).
    고시 상한은 **보험 급여**의 상한이지 유급액의 상한이 아니다.
"""

import math

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

# 미숙아 출산전후휴가 100일 시행일(근로기준법 제74조제1항). 배우자 20일과 같은 날 시행됐다.
# 상한은 따로 두지 않는다 — 고시 총액이 `월 상한 ÷ 30 × 일수`라 일수만 바뀌면 따라온다.
# 고시는 총액을 10원 미만 절사해 적으므로(미숙아 100일 7,333,330원 = 220만 × 100/30 절사)
# 상한이 걸릴 때만 총액을 같은 단위로 맞춘다. 90·120일은 나누어떨어져 값이 변하지 않는다.
PREMATURE_LEAVE_FROM = "2025-02-23"

# ── 배우자 출산휴가 (남녀고용평등법 제18조의2, 고용보험법 제75조의2) ─────────
# **유급 일수와 고용보험 지원 일수는 다른 값이고 함께 바뀐다.** 2025-02-23 개정 시행으로
# 유급 10일 → 20일, 지원 5일분 → 전 기간으로 확대됐다(고용노동부 work24 제도안내).
# 연중 시행이라 시행일 구간으로 둔다 — (유급 일수, 고용보험 지원 일수).
SPOUSE_LEAVE_PERIODS: dict[str, tuple[int, int]] = {
    "2019-10-01": (10, 5),
    "2025-02-23": (20, 20),
}

# 배우자 출산휴가 **급여**(고용보험 지원분) 상한. 유급액 전체의 상한이 아니다 —
# 통상임금이 상한을 넘으면 **차액은 사업주가 부담**한다(work24 제도안내). 또 출산전후휴가와
# 일당 기준이 다르다: 2026년 기준 배우자 1일 84,210원 vs 출산전후휴가 73,333원.
# 2025-02-23 이전(5일분 체제)의 상한은 **1차 출처로 확인하지 못해** 등록하지 않았다.
# 2차 출처들은 401,910원(5일분, 고용노동부고시 제2023-84호·제2024-105호)을 말하지만
# 금액이 HWP 첨부에만 있고 law.go.kr 의 그 고시 페이지는 폐지돼 열리지 않는다
# (2026-01 부터 「출산전후휴가 급여등 상한액 고시」로 통합). 원문을 확인하면 추가할 것 —
# 그때까지는 상한 미적용 + 경고가 추정값을 넣는 것보다 낫다.
# ── 난임치료휴가 · 배우자 유산·사산휴가 ─────────────────────────────────────
# 같은 고시(「출산전후휴가 급여등 상한액」)가 함께 정하므로 여기서 같이 계산한다.
#   난임치료휴가(남녀고용평등법 제18조의3): 연 6일 중 **최초 2일 유급**,
#     2026-11-27 부터 유급 4일로 확대.
#   배우자 유산·사산휴가(2026-09-18 시행): 5일 중 **최초 3일 유급**.
# 둘 다 유급분을 우선지원대상기업 근로자에 한해 고용보험이 지원한다.
INFERTILITY_LEAVE_PERIODS: dict[str, tuple[int, int]] = {      # (연간 일수, 유급 일수)
    "2025-02-23": (6, 2),
    "2026-11-27": (6, 4),
}
SPOUSE_MISCARRIAGE_PERIODS: dict[str, tuple[int, int]] = {     # (휴가 일수, 유급 일수)
    "2026-09-18": (5, 3),
}

# 두 휴가의 급여 상한은 **1일 단위**로 고시된다(제2026-67호: 난임 1일분 84,210원,
# 배우자 유산·사산 1일분 84,210원). 배우자 *출산*휴가(20일분 1,684,210원 → 1일 84,210.5)와
# 값이 미세하게 달라 그쪽 표에서 유도하지 않고 따로 둔다.
DAILY_LEAVE_UPPER_PERIODS: dict[str, float] = {
    "2026-01-01": 84_210,
}

SPOUSE_LEAVE_UPPER_PERIODS: dict[str, float] = {
    "2025-02-23": 1_607_650,   # 20일분 — 2025년 고시
    "2026-01-01": 1_684_210,   # 20일분 — 고용노동부고시 제2025-124호
}


def _won(value: float) -> str:
    """금액 표시. 통상임금은 원 미만이 남으므로 그때만 소수 2자리까지 보인다 —
    정수로 반올림해 보여 주면 화면의 산식이 서로 곱해지지 않는다
    (실측: 95,877 × 20 = 1,917,540 ≠ 표시된 합계 1,917,546)."""
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"


def _effective(periods: dict, reference_date: str | None, year: int):
    """시행일 구간표에서 그 시점의 값. 날짜가 없으면 그 해 1월 1일 기준. 이전이면 None."""
    day = reference_date or f"{int(year):04d}-01-01"
    started = [start for start in periods if start <= day]
    return periods[max(started)] if started else None


def spouse_leave_days(reference_date: str | None, year: int) -> tuple[int, int]:
    """그 시점의 (배우자 출산휴가 유급 일수, 고용보험 지원 일수)."""
    return _effective(SPOUSE_LEAVE_PERIODS, reference_date, year) or SPOUSE_LEAVE_PERIODS[
        min(SPOUSE_LEAVE_PERIODS)]


@dataclass
class MaternityLeaveResult(BaseCalculatorResult):
    # 출산전후휴가 급여
    leave_days: int = 0                        # 총 휴가 일수 (90 / 미숙아 100 / 다태아 120)
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
    spouse_leave_days: int = 0                 # 배우자 출산휴가 유급 일수 (10일 또는 20일)
    spouse_leave_pay: float = 0.0              # 배우자 출산휴가 유급액(사업주 지급 의무 총액)
    spouse_insurance_benefit: float = 0.0      # 그중 고용보험이 지원하는 급여(상한 적용)
    spouse_insurance_days: int = 0             # 고용보험 지원 일수

    # 난임치료휴가 · 배우자 유산·사산휴가 (같은 고시가 상한을 정한다)
    infertility_paid_days: int = 0             # 난임치료휴가 유급 일수
    infertility_pay: float = 0.0               # 그 유급액(상한 적용)
    spouse_miscarriage_paid_days: int = 0      # 배우자 유산·사산휴가 유급 일수
    spouse_miscarriage_pay: float = 0.0        # 그 유급액(상한 적용)

    upper_limit_applied: bool = False


def calc_maternity_leave(inp: WageInput, ow: OrdinaryWageResult) -> MaternityLeaveResult:
    """
    출산전후휴가급여 계산

    Args:
        inp: 임금 입력 데이터
          - is_priority_support_company: 우선지원대상기업 여부 (기본 True)
          - is_multiple_birth: 다태아 여부 (기본 False)
          - is_premature_birth: 미숙아 여부 (기본 False, 2025-02-23~ 100일)
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
    is_premature = getattr(inp, "is_premature_birth", False)
    reference_date = getattr(inp, "reference_date", None)

    # ── 휴가 일수 결정 ────────────────────────────────────────────────────
    # 미숙아 100일은 2025-02-23 시행이라 그 이전 출산에는 적용되지 않는다(근기법 제74조①).
    # 다태아 120일과 겹치면 더 긴 쪽이 남는다. 상한은 별도 표가 필요 없다 —
    # 고시의 기간 총액이 `월 상한 ÷ 30 × 일수`라 일수만 바뀌면 그대로 따라온다
    # (2026년 미숙아 100일 고시 7,333,330원 ≒ 2,200,000 × 100/30).
    premature_applies = is_premature and (reference_date or f"{int(year):04d}-01-01") >= PREMATURE_LEAVE_FROM
    leave_days = 120 if is_multiple else (100 if premature_applies else 90)
    if is_multiple:
        formulas.append(f"다태아 출산전후휴가: {leave_days}일")
        legal.append("근로기준법 제74조제1항 (다태아 120일)")
    elif premature_applies:
        formulas.append(f"미숙아 출산전후휴가: {leave_days}일")
        legal.append("근로기준법 제74조제1항 (미숙아 100일, 2025-02-23 시행)")
    else:
        formulas.append(f"출산전후휴가: {leave_days}일")
        if is_premature:
            warnings.append(
                "미숙아 출산전후휴가 100일은 2025-02-23 시행이라 그 이전 출산에는 적용되지 "
                "않습니다. 출산일이 그 이후라면 계산 기준일을 함께 알려주세요"
            )

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
    if upper_applied:
        # 고시는 기간 총액을 **10원 미만 절사**해 적는다(미숙아 100일 7,333,330원 =
        # 220만 × 100/30 의 절사값). 월 상한만 곱하면 3원이 남아 고시 상한을 넘는다.
        # 90·120일은 30으로 나누어떨어져 절사해도 값이 같다.
        cap_total = math.floor(upper * leave_days / MATERNITY_DAYS_PER_MONTH / 10) * 10
        overflow = total_insurance_benefit + total_employer_benefit - cap_total
        if overflow > 0:
            total_insurance_benefit -= overflow if insurance_days else 0
            total_employer_benefit -= overflow if not insurance_days else 0
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
    # **유급액과 보험 급여를 분리한다.** 고시 상한은 고용보험이 지급하는 급여의 상한이고
    # (우선지원대상기업 근로자만 대상), 유급 의무 자체는 사업주에게 남아 차액을 부담한다.
    # 상한을 유급액에 그대로 걸면 대규모기업 근로자의 법정 유급액이 줄어든 것처럼 보인다.
    spouse_days, spouse_insurance_days = spouse_leave_days(reference_date, year)
    daily_ordinary = ow.hourly_ordinary_wage * inp.schedule.daily_work_hours
    spouse_pay = daily_ordinary * spouse_days
    formulas.append(
        f"배우자 출산휴가({spouse_days}일, 유급): "
        f"{_won(daily_ordinary)}원/일 × {spouse_days}일 = {spouse_pay:,.0f}원"
    )
    legal.append("남녀고용평등법 제18조의2 (배우자 출산휴가)")

    spouse_insurance = 0.0
    if is_priority:
        spouse_upper = _effective(SPOUSE_LEAVE_UPPER_PERIODS, reference_date, year)
        spouse_insurance = daily_ordinary * spouse_insurance_days
        if spouse_upper is not None and spouse_insurance > spouse_upper:
            formulas.append(
                f"배우자 출산휴가급여(고용보험, {spouse_insurance_days}일분): "
                f"{spouse_insurance:,.0f}원 → 상한 {spouse_upper:,.0f}원 적용"
            )
            spouse_insurance = spouse_upper
        else:
            formulas.append(
                f"배우자 출산휴가급여(고용보험, {spouse_insurance_days}일분): {spouse_insurance:,.0f}원"
            )
            if spouse_upper is None:
                warnings.append(
                    "해당 시점의 배우자 출산휴가 급여 상한액 고시가 등록되지 않아 상한을 적용하지 "
                    "않았습니다. 실제 지급액은 상한에 걸릴 수 있습니다"
                )
        legal.append("고용보험법 제75조의2 (배우자 출산휴가 급여)")
        warnings.append(
            f"우선지원대상기업: 배우자 출산휴가 {spouse_insurance_days}일분"
            f"({spouse_insurance:,.0f}원)이 고용보험 지원 대상입니다. "
            f"유급액 {spouse_pay:,.0f}원과의 차액 {spouse_pay - spouse_insurance:,.0f}원은 사업주가 부담합니다"
        )
    else:
        warnings.append(
            f"우선지원대상기업이 아니면 배우자 출산휴가 {spouse_days}일 유급액 "
            f"{spouse_pay:,.0f}원 전액을 사업주가 부담합니다(고용보험 지원 없음)"
        )

    # ── 난임치료휴가 · 배우자 유산·사산휴가 ───────────────────────────────
    daily_upper = _effective(DAILY_LEAVE_UPPER_PERIODS, reference_date, year)

    def _daily_leave(periods, label, law):
        """유급 일수 × 1일 통상임금, 고시 1일 상한 적용. 시행 전이면 (0, 0)."""
        found = _effective(periods, reference_date, year)
        if not found:
            return 0, 0.0
        total_days, paid_days = found
        per_day = min(daily_ordinary, daily_upper) if daily_upper else daily_ordinary
        pay = per_day * paid_days
        legal.append(law)
        formulas.append(
            f"{label}: 총 {total_days}일 중 유급 {paid_days}일 × "
            f"{_won(per_day)}원 = {pay:,.0f}원"
            + ("" if daily_upper and daily_ordinary <= daily_upper else " (1일 상한 적용)"))
        return paid_days, pay

    infertility_days, infertility_pay = _daily_leave(
        INFERTILITY_LEAVE_PERIODS, "난임치료휴가", "남녀고용평등법 제18조의3 (난임치료휴가)")
    miscarriage_days, miscarriage_pay = _daily_leave(
        SPOUSE_MISCARRIAGE_PERIODS, "배우자 유산·사산휴가",
        "남녀고용평등법 제18조의4 (배우자 유산·사산휴가)")
    if infertility_days and is_priority:
        warnings.append(
            f"우선지원대상기업: 난임치료휴가 유급 {infertility_days}일분"
            f"({infertility_pay:,.0f}원)이 고용보험 지원 대상입니다")
    if miscarriage_days and is_priority:
        warnings.append(
            f"우선지원대상기업: 배우자 유산·사산휴가 유급 {miscarriage_days}일분"
            f"({miscarriage_pay:,.0f}원)이 고용보험 지원 대상입니다")

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
        f"배우자 출산휴가({spouse_days}일 유급)": f"{spouse_pay:,.0f}원",
        "└ 고용보험 지원분": (f"{spouse_insurance:,.0f}원 ({spouse_insurance_days}일분)"
                              if is_priority else "없음 (우선지원대상기업 아님)"),
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
        spouse_insurance_benefit=round(spouse_insurance),
        spouse_insurance_days=spouse_insurance_days if is_priority else 0,
        infertility_paid_days=infertility_days,
        infertility_pay=round(infertility_pay),
        spouse_miscarriage_paid_days=miscarriage_days,
        spouse_miscarriage_pay=round(miscarriage_pay),
        upper_limit_applied=upper_applied,
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )
