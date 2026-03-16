"""
실업급여(구직급여) 계산기

■ 고용보험법 제45조~제62조
■ 수급 3대 요건
  ① 비자발적 이직 (또는 자발적이라도 법정 예외 사유)
  ② 이직일 이전 18개월간 피보험단위기간 합계 180일 이상
  ③ 적극적 재취업 활동 (4주마다 인정신청)

■ 구직급여 일액 (고용보험법 제46조)
  기준 일액 = 이직 전 평균임금 × 60%
  상한액    = 연도별 변동 (고용보험법 시행령 제68조)
  하한액    = 최저임금 × 80% × 소정근로시간(8h)
  → 기준 일액이 상·하한 범위를 벗어나면 상한 또는 하한 적용

■ 소정급여일수 (고용보험법 제50조)
  피보험기간·나이(50세 기준)·장애인 여부에 따라 120~270일

■ 조기재취업수당 (고용보험법 제64조)
  소정급여일수 절반 이상 남기고 취업 → 남은 급여의 50%
  (단, 12개월 이상 고용 유지 후 신청)
"""

from dataclasses import dataclass

from ..base import BaseCalculatorResult
from ..constants import MINIMUM_HOURLY_WAGE, UNEMPLOYMENT_BENEFIT_UPPER
from ..models import WageInput
from .ordinary_wage import OrdinaryWageResult
from .shared import DateRange


# ── 상수 ─────────────────────────────────────────────────────────────────────
BENEFIT_RATE         = 0.60     # 평균임금 대비 지급률
LOWER_LIMIT_RATE     = 0.80     # 최저임금 × 80%
LOWER_LIMIT_HOURS    = 8        # 하한 산정 기준 소정근로시간
MIN_INSURED_DAYS     = 180      # 수급 최소 피보험단위기간 (일)
MAX_BENEFIT_MONTHS   = 12       # 수급기간 만료 (이직일 다음날부터 12개월)

# 소정급여일수 테이블
# (피보험기간 하한 개월, 50세 미만 일반, 50세 이상 또는 장애인)
BENEFIT_DAYS_TABLE = [
    (120, 240, 270),   # 10년 이상
    ( 60, 210, 240),   # 5~10년
    ( 36, 180, 210),   # 3~5년
    ( 12, 150, 180),   # 1~3년
    (  0, 120, 120),   # 1년 미만
]

# 자발적 이직 예외 인정 사유 (고용보험법 시행규칙 제101조 별표2)
VOLUNTARY_EXCEPTIONS = [
    "임금체불",
    "최저임금미달",
    "직장내괴롭힘",
    "통근불가",          # 왕복 3시간 이상
    "간호",              # 부모·배우자·자녀·손자녀 간호
    "임신출산육아",
    "사업장이전",        # 통근 불가능 거리로 이전
    "건강악화",
    "채용조건상이",      # 실제 근로조건이 명시 조건과 현저히 다른 경우
    "사업축소",
    "권고사직",
]


@dataclass
class UnemploymentResult(BaseCalculatorResult):
    """실업급여(구직급여) 계산 결과"""
    avg_daily_wage: float = 0.0           # 이직 전 평균임금 일액
    base_daily_benefit: float = 0.0       # 기준 일액 (평균임금 × 60%)
    daily_benefit: float = 0.0            # 실 지급 일액 (상·하한 적용 후)
    upper_limit: float = 0.0              # 상한액
    lower_limit: float = 0.0              # 하한액
    benefit_days: int = 0                 # 소정급여일수
    total_benefit: float = 0.0            # 총 구직급여 (일액 × 소정급여일수)
    early_reemployment_bonus: float = 0.0 # 조기재취업수당 (절반 남겼을 때)
    is_eligible: bool = False             # 수급 자격 여부
    ineligible_reason: str = ""           # 수급 불가 사유


def calc_unemployment(inp: WageInput, ow: OrdinaryWageResult) -> UnemploymentResult:
    """
    실업급여(구직급여) 계산

    필요 입력:
      - monthly_wage 또는 last_3m_wages + last_3m_days  (평균임금 산정)
      - insurance_months 또는 start_date + end_date      (피보험기간)
      - age                                              (소정급여일수)
      - is_involuntary_quit                              (수급 자격)
      - voluntary_quit_reason                            (자발 이직 예외 사유)
      - is_disabled                                      (소정급여일수 확대)
    """
    warnings: list[str] = []
    formulas: list[str] = []
    legal = [
        "고용보험법 제45조 (구직급여의 수급 자격)",
        "고용보험법 제46조 (구직급여 일액)",
        "고용보험법 제50조 (소정급여일수)",
    ]

    year          = inp.reference_year
    age           = getattr(inp, "age", 0)
    is_disabled   = getattr(inp, "is_disabled", False)
    is_involuntary = getattr(inp, "is_involuntary_quit", True)
    quit_reason    = (getattr(inp, "voluntary_quit_reason", "") or "").strip()

    # ── 1. 피보험기간 산정 ────────────────────────────────────────────────────
    insurance_months = getattr(inp, "insurance_months", None)
    if insurance_months is None and inp.start_date:
        dr = DateRange(inp.start_date, inp.end_date)
        insurance_months = dr.months_approx

    if insurance_months is None:
        insurance_months = 0

    insured_days_approx = insurance_months * 30

    # ── 2. 수급 자격 판단 ────────────────────────────────────────────────────

    # ① 피보험단위기간 부족
    if insured_days_approx < MIN_INSURED_DAYS:
        reason = (
            f"피보험단위기간 약 {insured_days_approx}일 — 최소 {MIN_INSURED_DAYS}일 필요. "
            "이직일 이전 18개월 이내(초단시간근로자는 24개월, 일용직은 1년)에 "
            "피보험단위기간 합계가 180일 이상이어야 합니다."
        )
        return _ineligible(reason, warnings, legal)

    # ② 자발적 이직 여부
    if not is_involuntary:
        if quit_reason:
            # 예외 사유 있으면 경고 후 계산 진행
            warnings.append(
                f"⚠ 자발적 이직 — 예외 사유 '{quit_reason}' 해당 시 수급 가능. "
                "고용보험법 시행규칙 제101조 별표2 해당 여부를 고용센터에서 최종 확인 필요."
            )
            legal.append("고용보험법 시행규칙 제101조 별표2 (자발적 이직 예외 인정 사유)")
        else:
            reason = (
                "자발적 이직은 구직급여 수급 불가 (고용보험법 제58조). "
                "권고사직·계약만료·부당해고·임금체불·직장내괴롭힘 등 비자발적 사유이거나 "
                "법정 예외 사유(임신·출산·육아, 통근 불가, 건강 악화 등)에 해당해야 합니다. "
                "이직 확인서의 이직 사유를 정확히 기재해야 합니다."
            )
            return _ineligible(reason, warnings, legal)

    # ── 3. 평균임금 일액 산정 ─────────────────────────────────────────────────
    # 3-0. 다중 사업장 평균임금 (고용보험법 제45조 제1항 단서)
    multi = getattr(inp, "multi_employer_wages", None)
    if multi and len(multi) >= 2:
        total_wages = sum(
            float(e.get("monthly_wage", 0)) * float(e.get("months", 1))
            for e in multi
        )
        period_days_multi = 92  # 3개월 기준
        avg_daily = total_wages / period_days_multi
        formulas.append(
            f"다중 사업장 평균임금: "
            + " + ".join(
                f"{e.get('employer', '?')} {float(e.get('monthly_wage', 0)):,.0f}원×{e.get('months', 1)}개월"
                for e in multi
            )
            + f" = {total_wages:,.0f}원 ÷ {period_days_multi}일 = {avg_daily:,.0f}원"
        )
        legal.append("고용보험법 제45조 제1항 단서 (최종이직 전 3개월 내 2회 이상 피보험자격 취득)")
    else:
        # 상여금/연차수당 3개월 비례분 가산 (nodong.kr 기준)
        avg_daily = None  # 아래에서 계산

    # 단일 사업장 (기존 로직)
    bonus_3m = (inp.annual_bonus_total / 12) * 3 if inp.annual_bonus_total else 0
    leave_pay_3m = (inp.unused_annual_leave_pay / 12) * 3 if inp.unused_annual_leave_pay else 0
    extra_3m = bonus_3m + leave_pay_3m

    if avg_daily is not None:
        pass  # 다중 사업장에서 이미 계산됨
    elif inp.last_3m_wages and inp.last_3m_days:
        base_3m   = sum(inp.last_3m_wages)
        total_3m  = base_3m + extra_3m
        avg_daily = total_3m / inp.last_3m_days
        formulas.append(
            f"평균임금 일액: ({base_3m:,.0f}원"
            + (f" + 상여금 {bonus_3m:,.0f}원 + 연차수당 {leave_pay_3m:,.0f}원" if extra_3m else "")
            + f") ÷ {inp.last_3m_days}일 = {avg_daily:,.1f}원"
        )
    elif inp.monthly_wage:
        base_3m   = inp.monthly_wage * 3
        total_3m  = base_3m + extra_3m
        avg_daily = total_3m / 92
        formulas.append(
            f"평균임금 일액(추정): ({inp.monthly_wage:,.0f}원 × 3"
            + (f" + 상여금 {bonus_3m:,.0f}원 + 연차수당 {leave_pay_3m:,.0f}원" if extra_3m else "")
            + f") ÷ 92일 = {avg_daily:,.1f}원"
        )
        if not extra_3m:
            warnings.append(
                "평균임금은 이직 전 3개월 실지급 임금으로 산정합니다. "
                "상여금·성과금 등 변동 급여가 있으면 급여명세서로 재확인하세요."
            )
    else:
        avg_daily = ow.hourly_ordinary_wage * 8
        formulas.append(
            f"평균임금 일액(통상시급 기준): {ow.hourly_ordinary_wage:,.1f}원 × 8h = {avg_daily:,.1f}원"
        )
        warnings.append("평균임금을 통상시급으로 추정했습니다. 정확한 계산은 이직 전 3개월 임금으로 확인하세요.")

    # ── 4. 구직급여 일액 산정 ─────────────────────────────────────────────────
    base_daily = avg_daily * BENEFIT_RATE

    upper = float(UNEMPLOYMENT_BENEFIT_UPPER.get(
        year, UNEMPLOYMENT_BENEFIT_UPPER[max(UNEMPLOYMENT_BENEFIT_UPPER)]
    ))

    # 하한액: 최저임금 × 80% × 8h
    min_wage = MINIMUM_HOURLY_WAGE.get(year, MINIMUM_HOURLY_WAGE[max(MINIMUM_HOURLY_WAGE)])
    lower    = min_wage * LOWER_LIMIT_RATE * LOWER_LIMIT_HOURS

    # 2026년 이후 하한 > 상한이 될 수 있음 → 경고
    if lower > upper:
        warnings.append(
            f"{year}년 하한액({lower:,.0f}원) > 상한액({upper:,.0f}원) — "
            "정부가 상한액을 아직 인상하지 않은 경우입니다. "
            "고용노동부 공지를 확인하세요. 현재는 하한액으로 계산합니다."
        )
        upper = lower   # 사실상 하한이 상한을 초과하면 하한으로 통일

    limit_applied = ""
    if base_daily >= upper:
        daily_benefit = upper
        limit_applied = "상한액 적용"
        warnings.append(
            f"평균임금 일액({avg_daily:,.0f}원/일)이 높아 상한액 {upper:,.0f}원이 적용됩니다."
        )
    elif base_daily <= lower:
        daily_benefit = lower
        limit_applied = "하한액 적용"
        warnings.append(
            f"평균임금 일액({avg_daily:,.0f}원/일)이 낮아 하한액 {lower:,.0f}원이 적용됩니다."
        )
    else:
        daily_benefit = base_daily

    formulas.append(
        f"구직급여 일액: {avg_daily:,.0f}원 × {BENEFIT_RATE:.0%} = {base_daily:,.0f}원"
        + (f" → {limit_applied}: {daily_benefit:,.0f}원" if limit_applied else f" = {daily_benefit:,.0f}원")
    )

    # ── 5. 소정급여일수 산정 ──────────────────────────────────────────────────
    is_senior    = (age >= 50) or is_disabled
    benefit_days = _get_benefit_days(insurance_months, is_senior)

    age_label = "50세 이상 또는 장애인" if is_senior else "50세 미만 일반"
    age_detail = f" (만 {age}세)" if age else ""
    formulas.append(
        f"소정급여일수: 피보험기간 {insurance_months}개월 [{age_label}{age_detail}] → {benefit_days}일"
    )

    # ── 6. 총 구직급여 ────────────────────────────────────────────────────────
    total = daily_benefit * benefit_days
    formulas.append(
        f"총 구직급여: {daily_benefit:,.0f}원/일 × {benefit_days}일 = {total:,.0f}원"
    )

    # ── 7. 조기재취업수당 ─────────────────────────────────────────────────────
    # 소정급여일수 절반 이상 남기고 취업 시, 남은 급여의 50%
    half_days    = benefit_days // 2
    early_bonus  = daily_benefit * half_days * 0.50
    formulas.append(
        f"조기재취업수당(최대): {daily_benefit:,.0f}원 × {half_days}일(절반) × 50% = {early_bonus:,.0f}원"
    )
    legal.append("고용보험법 제64조 (조기재취업수당)")

    # ── 8. 안내 사항 ─────────────────────────────────────────────────────────
    warnings.append(
        f"수급기간 만료: 이직일 다음날부터 {MAX_BENEFIT_MONTHS}개월. "
        "소정급여일수가 남아 있어도 만료일 경과 시 소멸합니다."
    )
    warnings.append(
        "신청: 이직 다음날부터 고용센터 방문 또는 워크넷(www.work.go.kr) 온라인 신청. "
        "수급자격 인정 후 4주마다 실업 인정 신청 필요."
    )
    if age > 0 and age >= 60:
        warnings.append(
            "만 60세 이상은 사업주 동의 없으면 고용보험 임의 가입입니다. "
            "피보험자 여부를 먼저 확인하세요."
        )

    breakdown = {
        "피보험기간":      f"{insurance_months}개월 (약 {insured_days_approx}일)",
        "연령 구분":       f"{age_label}{age_detail}",
        "평균임금 일액":   f"{avg_daily:,.0f}원",
        "구직급여 기준 일액": f"{base_daily:,.0f}원 (× {BENEFIT_RATE:.0%})",
        "상한액":          f"{upper:,.0f}원/일",
        "하한액":          f"{lower:,.0f}원/일  (최저임금 {min_wage:,}원 × 80% × 8h)",
        "실 지급 일액":    f"{daily_benefit:,.0f}원" + (f"  [{limit_applied}]" if limit_applied else ""),
        "소정급여일수":    f"{benefit_days}일",
        "총 구직급여":     f"{total:,.0f}원",
        "조기재취업수당":  f"{early_bonus:,.0f}원  (절반 이상 남기고 취업 후 12개월 고용 유지 시)",
        "수급기간 만료":   "이직일 다음날부터 12개월",
    }

    return UnemploymentResult(
        avg_daily_wage=round(avg_daily, 0),
        base_daily_benefit=round(base_daily, 0),
        daily_benefit=round(daily_benefit, 0),
        upper_limit=round(upper, 0),
        lower_limit=round(lower, 0),
        benefit_days=benefit_days,
        total_benefit=round(total, 0),
        early_reemployment_bonus=round(early_bonus, 0),
        is_eligible=True,
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _ineligible(reason: str, warnings: list, legal: list) -> UnemploymentResult:
    """수급 자격 없음 결과 생성"""
    warnings.insert(0, f"❌ 수급 자격 없음 — {reason}")
    return UnemploymentResult(
        is_eligible=False,
        ineligible_reason=reason,
        warnings=warnings,
        legal_basis=legal,
        breakdown={
            "수급 자격": "❌ 미충족",
            "사유":       reason,
        },
    )


def _get_benefit_days(insurance_months: int, is_senior: bool) -> int:
    """피보험기간·나이에 따른 소정급여일수 반환"""
    for min_months, days_young, days_senior in BENEFIT_DAYS_TABLE:
        if insurance_months >= min_months:
            return days_senior if is_senior else days_young
    return 120   # 안전 기본값
