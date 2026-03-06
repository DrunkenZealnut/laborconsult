"""
육아휴직급여 계산기 (고용보험법 제70~73조)

핵심 계산식:
  육아휴직급여 = 통상임금 × 80%
    상한: 1,500,000원/월
    하한: 700,000원/월
    사후지급금(25%): 복직 6개월 후 일괄 지급

  아빠 육아휴직 보너스 (같은 자녀, 배우자가 먼저 육아휴직 사용 후 두 번째 사용자 첫 3개월):
    통상임금 100%, 상한 2,500,000원/월

  육아기 근로시간 단축급여:
    = (단축 전 통상임금 - 단축 후 통상임금) 차액 + 단축시간에 대한 보전 급여

※ 2025년 기준. 급여 상·하한액은 연도별 변동 가능.
"""

from dataclasses import dataclass

from ..base import BaseCalculatorResult
from ..models import WageInput
from .ordinary_wage import OrdinaryWageResult

# ── 2025년 기준 상·하한액 ────────────────────────────────────────────────────
# 고용노동부 고시 기준 (매년 변동)
PARENTAL_LEAVE_LIMITS = {
    2024: {"upper": 1_500_000, "lower": 700_000, "bonus_upper": 2_500_000},
    2025: {"upper": 1_500_000, "lower": 700_000, "bonus_upper": 2_500_000},
    2026: {"upper": 1_500_000, "lower": 700_000, "bonus_upper": 2_500_000},
}

# 사후지급금 비율 (매월 지급분 중 일부를 복직 후 지급)
DEFERRED_RATIO = 0.25  # 25%는 복직 6개월 후 일괄 지급


@dataclass
class ParentalLeaveResult(BaseCalculatorResult):
    # 월 급여
    monthly_ordinary_wage: float = 0.0             # 월 통상임금 (계산 기반)
    monthly_benefit_before_deferred: float = 0.0   # 월 지급액 (사후지급금 공제 전)
    monthly_benefit_actual: float = 0.0            # 실제 매월 수령액 (75%)
    monthly_deferred: float = 0.0                  # 사후지급금 (복직 후 지급, 25%)

    # 전체 육아휴직 기간 합계
    total_months: int = 0                          # 육아휴직 기간 (개월)
    total_benefit: float = 0.0                     # 총 급여 합계 (원)
    total_deferred: float = 0.0                    # 총 사후지급금 (원)

    # 아빠 보너스 (해당 시)
    has_bonus: bool = False                        # 아빠 보너스 적용 여부
    bonus_months: int = 0                          # 보너스 적용 개월 (최대 3개월)
    monthly_bonus_benefit: float = 0.0             # 보너스 기간 월 급여

    # 육아기 근로시간 단축급여 (해당 시)
    reduced_work_monthly_benefit: float = 0.0      # 단축급여 (원/월)

    # 상·하한 적용 여부
    upper_limit_applied: bool = False
    lower_limit_applied: bool = False


def calc_parental_leave(inp: WageInput, ow: OrdinaryWageResult) -> ParentalLeaveResult:
    """
    육아휴직급여 계산

    Args:
        inp: 임금 입력 데이터
          - parental_leave_months: 육아휴직 신청 개월 수
          - is_second_parent: 두 번째 육아휴직자 여부 (아빠 보너스)
          - reduced_work_hours_per_day: 육아기 단축 시간/일 (0이면 미사용)
        ow: 통상임금 계산 결과
    """
    warnings = []
    formulas = []
    legal = [
        "고용보험법 제70조 (육아휴직급여)",
        "고용보험법 제71조 (육아휴직급여 지급 기간)",
        "고용보험법 제73조 (육아기 근로시간 단축급여)",
    ]

    year = inp.reference_year
    limits = PARENTAL_LEAVE_LIMITS.get(year, PARENTAL_LEAVE_LIMITS[2025])
    upper  = limits["upper"]
    lower  = limits["lower"]
    bonus_upper = limits["bonus_upper"]

    leave_months = getattr(inp, "parental_leave_months", 0) or 0
    is_second    = getattr(inp, "is_second_parent", False) or False
    reduced_hrs  = getattr(inp, "reduced_work_hours_per_day", 0.0) or 0.0

    if leave_months <= 0:
        leave_months = 1
        warnings.append("육아휴직 개월 수 미입력 — 1개월 기준으로 계산")

    if leave_months > 12:
        warnings.append(f"육아휴직 최대 12개월 초과 입력 ({leave_months}개월) — 12개월로 조정")
        leave_months = 12

    monthly_ow = ow.monthly_ordinary_wage

    # ── 기본 육아휴직급여 (80%) ──────────────────────────────────────────
    raw_benefit = monthly_ow * 0.80
    upper_applied = raw_benefit > upper
    lower_applied = raw_benefit < lower

    monthly_benefit = max(lower, min(raw_benefit, upper))

    if upper_applied:
        formulas.append(
            f"육아휴직급여: {monthly_ow:,.0f}원 × 80% = {raw_benefit:,.0f}원 → 상한 {upper:,}원 적용"
        )
    elif lower_applied:
        formulas.append(
            f"육아휴직급여: {monthly_ow:,.0f}원 × 80% = {raw_benefit:,.0f}원 → 하한 {lower:,}원 적용"
        )
    else:
        formulas.append(
            f"육아휴직급여: {monthly_ow:,.0f}원 × 80% = {monthly_benefit:,.0f}원"
        )

    # ── 사후지급금 계산 (25%) ──────────────────────────────────────────
    monthly_deferred = round(monthly_benefit * DEFERRED_RATIO)
    monthly_actual   = round(monthly_benefit - monthly_deferred)

    formulas.append(
        f"매월 지급: {monthly_benefit:,.0f}원 × 75% = {monthly_actual:,.0f}원"
    )
    formulas.append(
        f"사후지급금: {monthly_benefit:,.0f}원 × 25% = {monthly_deferred:,.0f}원 (복직 6개월 후 일괄)"
    )

    # ── 아빠 보너스 (두 번째 사용자 첫 3개월) ──────────────────────────
    has_bonus = is_second
    bonus_months = 0
    monthly_bonus = 0.0

    if has_bonus:
        bonus_months = min(3, leave_months)
        raw_bonus = monthly_ow * 1.0  # 100%
        monthly_bonus = min(raw_bonus, bonus_upper)
        if raw_bonus > bonus_upper:
            formulas.append(
                f"아빠 보너스(첫 {bonus_months}개월): {monthly_ow:,.0f}원 × 100% = {raw_bonus:,.0f}원 "
                f"→ 상한 {bonus_upper:,}원 적용"
            )
        else:
            formulas.append(
                f"아빠 보너스(첫 {bonus_months}개월): {monthly_ow:,.0f}원 × 100% = {monthly_bonus:,.0f}원"
            )
        warnings.append(
            f"아빠 육아휴직 보너스: 같은 자녀에 대해 배우자 이후 두 번째 육아휴직 사용 시 "
            f"첫 3개월 통상임금 100% (상한 {bonus_upper:,}원/월) 적용"
        )

    # ── 총 급여 계산 ───────────────────────────────────────────────────
    total_benefit = 0.0
    if has_bonus:
        # 보너스 기간: 보너스 급여 (사후지급금 없음 또는 포함)
        # 실제로는 보너스도 사후지급금 25% 공제 적용됨 (동일 구조)
        bonus_actual  = round(monthly_bonus * (1 - DEFERRED_RATIO))
        total_benefit += bonus_actual * bonus_months
        total_benefit += monthly_actual * (leave_months - bonus_months)
    else:
        total_benefit = monthly_actual * leave_months

    total_deferred = monthly_deferred * leave_months
    if has_bonus:
        bonus_deferred = round(monthly_bonus * DEFERRED_RATIO) * bonus_months
        normal_deferred = monthly_deferred * (leave_months - bonus_months)
        total_deferred = bonus_deferred + normal_deferred

    formulas.append(
        f"전체 육아휴직 수령액(매월): {total_benefit:,.0f}원 ({leave_months}개월)"
    )
    formulas.append(
        f"복직 후 사후지급금 합계: {total_deferred:,.0f}원"
    )

    # ── 육아기 근로시간 단축급여 ─────────────────────────────────────────
    reduced_benefit = 0.0
    if reduced_hrs > 0:
        # 단축 시간에 대한 통상임금 대비 보전 (80%)
        # 단축 전 통상임금 - 단축 후 통상임금 = 단축시간 × 통상시급
        # 단축급여 = 차액의 80% + 나머지
        daily_hours_orig = inp.schedule.daily_work_hours
        daily_hours_after = max(0, daily_hours_orig - reduced_hrs)

        # 단축 후 월 통상임금
        if daily_hours_orig > 0:
            reduction_ratio = reduced_hrs / daily_hours_orig
            monthly_ow_after = monthly_ow * (1 - reduction_ratio)
            wage_diff = monthly_ow - monthly_ow_after  # 감소분
            # 고용보험 보전: 감소분 × 80% (상한 별도)
            reduced_benefit = wage_diff * 0.80
            formulas.append(
                f"육아기 단축급여: 단축({reduced_hrs}h/일) → "
                f"임금 감소분 {wage_diff:,.0f}원 × 80% = {reduced_benefit:,.0f}원/월"
            )
        legal.append("고용보험법 제73조의2 (육아기 근로시간 단축급여)")

    warnings.append("육아휴직급여 수급 요건: 육아휴직 시작일 전 피보험기간 180일 이상")
    warnings.append("신청 기한: 육아휴직 종료 후 12개월 이내 (고용보험법 제70조)")
    warnings.append(
        f"사후지급금 {int(DEFERRED_RATIO*100)}%는 복직 후 6개월 이상 근무 후 신청 가능"
    )

    # 보너스 기간 급여 결정
    monthly_bonus_benefit = round(monthly_bonus * (1 - DEFERRED_RATIO)) if has_bonus else 0.0

    breakdown = {
        "월 통상임금": f"{monthly_ow:,.0f}원",
        "육아휴직급여(80%)": f"{monthly_benefit:,.0f}원/월",
        "매월 수령액(75%)": f"{monthly_actual:,.0f}원/월",
        "사후지급금(25%)": f"{monthly_deferred:,.0f}원/월 (복직 후)",
        "육아휴직 기간": f"{leave_months}개월",
        "총 수령액(매월)": f"{total_benefit:,.0f}원",
        "총 사후지급금": f"{total_deferred:,.0f}원",
        "상한액 적용": "✅" if upper_applied else "미적용",
        "하한액 적용": "✅" if lower_applied else "미적용",
    }
    if has_bonus:
        breakdown["아빠 보너스(첫 3개월)"] = f"{monthly_bonus:,.0f}원/월 (100% 상한 {bonus_upper:,}원)"
    if reduced_hrs > 0:
        breakdown["육아기 단축급여"] = f"{reduced_benefit:,.0f}원/월"
    breakdown["기준 연도"] = f"{year}년"

    return ParentalLeaveResult(
        monthly_ordinary_wage=monthly_ow,
        monthly_benefit_before_deferred=round(monthly_benefit),
        monthly_benefit_actual=monthly_actual,
        monthly_deferred=monthly_deferred,
        total_months=leave_months,
        total_benefit=round(total_benefit),
        total_deferred=round(total_deferred),
        has_bonus=has_bonus,
        bonus_months=bonus_months,
        monthly_bonus_benefit=round(monthly_bonus_benefit),
        reduced_work_monthly_benefit=round(reduced_benefit),
        upper_limit_applied=upper_applied,
        lower_limit_applied=lower_applied,
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )
