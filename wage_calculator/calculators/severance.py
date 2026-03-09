"""
퇴직금 계산기 (근로자퇴직급여보장법 제8조)

수요: 122건 (4.7%)

핵심 규칙:
- 계속근로기간 1년 이상 + 4주 평균 주 15시간 이상 근무 시 발생
- 퇴직금 = 평균임금 × 30일 × (계속근로일수 / 365)
- 평균임금 = 퇴직 전 3개월간 임금 총액 / 3개월 총 일수

■ 대법원 2024.3.12. 선고 2023다302579 반영
  1) 일용직이라도 계속 근무 사실이 인정되면 상용근로자로 보아 퇴직금 지급
     - 월 4~15일 정도 계속 근무 시 퇴직금 요건 충족 가능 (월 25일 이상 불필요)
     - 판단 기준: 근무 중단 없이 계속성이 인정되는지 여부
  2) 평균임금 유리 원칙
     - 퇴직 전 3개월 평균임금이 퇴직 전 1년 평균임금보다 현저히 낮은 경우
       → 1년 평균임금 기준으로 퇴직금 재산정 (근로자에게 유리한 금액 적용)
     - 판결 사례: 3개월 기준 74,355원/일 vs 1년 기준 114,312원/일 → 1년 기준 적용

■ 근로기준법 시행령 제2조
  - 평균임금이 통상임금보다 낮으면 통상임금을 평균임금으로 함
  → 통상임금 vs 평균임금 비교 후 높은 쪽 적용

■ 5인 미만 사업장
  - 퇴직급여 지급 의무 있음 (근퇴법은 사업장 규모 불문 적용)
  - 단, 2010.12.01 이전 입사자 중 4인 이하 사업장은 경과 규정 확인 필요
"""

from dataclasses import dataclass
from datetime import date

from ..base import BaseCalculatorResult
from ..constants import SEVERANCE_MIN_SERVICE_DAYS
from ..models import WageInput, WorkType, BusinessSize
from ..utils import parse_date
from .average_wage import calc_average_wage
from .ordinary_wage import OrdinaryWageResult


@dataclass
class SeveranceResult(BaseCalculatorResult):
    severance_pay: float = 0.0        # 퇴직금 (원)
    avg_daily_wage: float = 0.0       # 적용 평균임금 (원/일)
    avg_daily_3m: float = 0.0         # 3개월 기준 평균임금 (원/일)
    avg_daily_1y: float = 0.0         # 1년 기준 평균임금 (원/일) — 0이면 미산정
    avg_daily_ordinary: float = 0.0   # 통상임금 환산 일급 (원/일)
    used_basis: str = ""              # 적용 기준 ("3개월" / "1년" / "통상임금")
    service_days: int = 0             # 계속근로일수
    service_years: float = 0.0        # 계속근로연수
    is_eligible: bool = False         # 퇴직금 발생 여부


def calc_severance(inp: WageInput, ow: OrdinaryWageResult) -> SeveranceResult:
    """퇴직금 계산 (대법원 2023다302579 반영)"""
    warnings = []
    formulas = []
    legal = [
        "근로자퇴직급여보장법 제8조 (퇴직금 제도의 설정 등)",
        "근로기준법 제2조 (평균임금)",
        "근로기준법 시행령 제2조 (평균임금의 계산에서 제외되는 기간과 임금)",
    ]

    # ── 재직기간 계산 ────────────────────────────────────────────────────────
    start = parse_date(inp.start_date)
    end   = parse_date(inp.end_date) or date.today()

    if start is None:
        return _ineligible(
            "입사일(start_date)을 입력해주세요",
            ow, warnings, formulas, legal,
        )

    service_days = (end - start).days
    service_years = service_days / 365

    # ── 자격 요건 확인 ───────────────────────────────────────────────────────
    # 1) 계속근로 1년 이상
    if service_days < SEVERANCE_MIN_SERVICE_DAYS:
        warnings.append(
            f"계속근로기간 {service_days}일 < 365일 — 퇴직금 미발생"
        )
        return _ineligible(
            f"계속근로 {service_days}일 (1년 미만)",
            ow, warnings, formulas, legal, service_days, service_years,
        )

    # 2) 일용직 판단: 대법원 2023다302579
    if inp.work_type == WorkType.DAILY_WORKER:
        legal.append("대법원 2024.3.12. 선고 2023다302579 판결 (일용직 퇴직금 자격)")
        monthly_days = inp.daily_worker_monthly_days
        if monthly_days is not None:
            if monthly_days < 4:
                warnings.append(
                    f"일용직 월 평균 근무일수 {monthly_days}일 — 계속 근무 인정 어려움 "
                    f"(대법원: 월 4~15일 이상 계속 근무 시 퇴직금 인정)"
                )
            else:
                warnings.append(
                    f"일용직이나 월 평균 {monthly_days}일 계속 근무 — "
                    f"퇴직금 수급 가능성 있음 (대법원 2023다302579)"
                )
        else:
            warnings.append(
                "일용직: 계속 근무 여부에 따라 퇴직금 발생 여부 결정. "
                "월 4~15일 이상 계속 근무 시 상용근로자로 인정 가능 (대법원 2023다302579)"
            )

    # ── 평균임금 산정 (3가지 비교) ───────────────────────────────────────────

    # A. 3개월 평균임금 — average_wage 모듈 재사용
    avg_result = calc_average_wage(inp, ow)
    avg_daily_3m = avg_result.avg_daily_3m

    # B. 1년 평균임금 (대법원 2023다302579)
    avg_daily_1y = _calc_avg_daily_1y(inp, ow)

    # C. 통상임금 환산 일급 (근로기준법 시행령 제2조)
    avg_daily_ordinary = avg_result.avg_daily_ordinary

    # ── 유리한 기준 선택 ─────────────────────────────────────────────────────
    candidates = {"3개월": avg_daily_3m, "통상임금": avg_daily_ordinary}
    used_basis = "3개월"
    avg_daily = avg_daily_3m

    if avg_daily_1y > 0 and avg_daily_1y > avg_daily_3m * 1.05:
        # 1년 평균이 3개월 평균보다 5% 초과 높으면 1년 기준 적용
        candidates["1년"] = avg_daily_1y
        legal.append("대법원 2024.3.12. 선고 2023다302579 판결 (1년 평균임금 적용)")
        warnings.append(
            f"퇴직 전 3개월 평균임금({avg_daily_3m:,.0f}원/일)이 "
            f"1년 평균임금({avg_daily_1y:,.0f}원/일)보다 낮습니다. "
            f"대법원 2023다302579 판결에 따라 1년 기준으로 재산정합니다."
        )

    if avg_daily_ordinary > avg_daily_3m:
        legal.append("근로기준법 시행령 제2조 (평균임금 < 통상임금 시 통상임금 적용)")
        warnings.append(
            f"평균임금({avg_daily_3m:,.0f}원/일)이 통상임금 환산액({avg_daily_ordinary:,.0f}원/일)보다 낮아 "
            f"통상임금 기준 적용"
        )

    # 가장 높은 기준 선택
    best = max(candidates, key=lambda k: candidates[k])
    avg_daily = candidates[best]
    used_basis = best

    formulas.append(f"3개월 평균임금: {avg_daily_3m:,.0f}원/일")
    if avg_daily_1y > 0:
        formulas.append(f"1년 평균임금:   {avg_daily_1y:,.0f}원/일")
    formulas.append(f"통상임금 환산:  {avg_daily_ordinary:,.0f}원/일 ({ow.hourly_ordinary_wage:,.0f}원 × 8h)")
    formulas.append(f"적용 기준:      {used_basis} ({avg_daily:,.0f}원/일)")

    # ── 퇴직금 산정 ──────────────────────────────────────────────────────────
    severance_pay = avg_daily * 30 * (service_days / 365)

    formulas.append(
        f"퇴직금: {avg_daily:,.0f}원 × 30일 × ({service_days}일 ÷ 365) = {severance_pay:,.0f}원"
    )

    breakdown = {
        "입사일":             str(start),
        "퇴직일":             str(end),
        "계속근로일수":       f"{service_days}일 ({service_years:.2f}년)",
        "3개월 평균임금":     f"{avg_daily_3m:,.0f}원/일",
        "1년 평균임금":       f"{avg_daily_1y:,.0f}원/일" if avg_daily_1y > 0 else "미입력 (월급 × 12 추정)",
        "통상임금 환산일급":  f"{avg_daily_ordinary:,.0f}원/일",
        "적용 평균임금":      f"{avg_daily:,.0f}원/일 ({used_basis} 기준)",
        "퇴직금":             f"{severance_pay:,.0f}원",
    }

    # 상여금/연차수당 가산 내역
    if inp.annual_bonus_total > 0:
        bonus_add = inp.annual_bonus_total * 3 / 12
        breakdown["상여금 가산"] = (
            f"{bonus_add:,.0f}원 (연 {inp.annual_bonus_total:,.0f}원 x 3/12)"
        )
        formulas.append(
            f"상여금 가산: {inp.annual_bonus_total:,.0f}원 x 3/12 = {bonus_add:,.0f}원"
        )
    if inp.unused_annual_leave_pay > 0:
        leave_add = inp.unused_annual_leave_pay * 3 / 12
        breakdown["연차수당 가산"] = (
            f"{leave_add:,.0f}원 (연차수당 {inp.unused_annual_leave_pay:,.0f}원 x 3/12)"
        )
        formulas.append(
            f"연차수당 가산: {inp.unused_annual_leave_pay:,.0f}원 x 3/12 = {leave_add:,.0f}원"
        )

    # IRP 의무 안내 (2022.4.14 이후)
    if end >= date(2022, 4, 14):
        warnings.append(
            "2022.4.14 이후 퇴직 시 퇴직금은 IRP(개인형퇴직연금) 계좌로 "
            "세전 금액 전액 지급해야 합니다 (근로자퇴직급여보장법 제9조). "
            "퇴직소득세는 IRP 계좌에서 인출 시 원천징수됩니다."
        )
        legal.append("근로자퇴직급여보장법 제9조 (개인형퇴직연금제도의 설정 등)")

    # 5인 미만 안내
    if inp.business_size == BusinessSize.UNDER_5:
        warnings.append(
            "5인 미만 사업장이라도 퇴직급여 지급 의무 있음 "
            "(근로자퇴직급여보장법은 사업장 규모 불문 적용)"
        )
        legal.append("근로자퇴직급여보장법 제3조 (적용 범위)")

    return SeveranceResult(
        severance_pay=round(severance_pay, 0),
        avg_daily_wage=round(avg_daily, 2),
        avg_daily_3m=round(avg_daily_3m, 2),
        avg_daily_1y=round(avg_daily_1y, 2),
        avg_daily_ordinary=round(avg_daily_ordinary, 2),
        used_basis=used_basis,
        service_days=service_days,
        service_years=round(service_years, 2),
        is_eligible=True,
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )


def _calc_avg_daily_1y(inp: WageInput, ow: OrdinaryWageResult) -> float:
    """퇴직 전 1년 평균임금 계산 (대법원 2023다302579)"""
    period_days = inp.last_1y_days or 365

    if inp.last_1y_wages:
        total = sum(inp.last_1y_wages)
        return total / period_days

    # 1년 데이터 미제공 시 monthly_wage × 12 추정 (명시적 안내)
    if inp.monthly_wage:
        total = inp.monthly_wage * 12
        return total / period_days

    # 통상임금 기반 추정
    return ow.monthly_ordinary_wage * 12 / period_days


def _ineligible(
    reason: str,
    ow: OrdinaryWageResult,
    warnings: list,
    formulas: list,
    legal: list,
    service_days: int = 0,
    service_years: float = 0.0,
) -> SeveranceResult:
    return SeveranceResult(
        severance_pay=0.0,
        avg_daily_wage=0.0,
        avg_daily_3m=0.0,
        avg_daily_1y=0.0,
        avg_daily_ordinary=ow.hourly_ordinary_wage * 8,
        used_basis="-",
        service_days=service_days,
        service_years=service_years,
        is_eligible=False,
        breakdown={"퇴직금": f"미발생 — {reason}"},
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )


