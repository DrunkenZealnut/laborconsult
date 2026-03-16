"""
퇴직연금 계산기 (근로자퇴직급여보장법 제15조, 제17조)

- DB형(확정급여형): 퇴직금과 동일 공식 (평균임금 x 30 x 재직연수)
- DC형(확정기여형): 매년 연간임금총액 1/12 이상 적립 + 운용수익
"""

from dataclasses import dataclass, field
from datetime import date

from ..base import BaseCalculatorResult
from ..models import WageInput
from .ordinary_wage import OrdinaryWageResult
from .severance import SeveranceResult
from .shared import DateRange


@dataclass
class RetirementPensionResult(BaseCalculatorResult):
    pension_type: str = ""                # "DB" / "DC"
    total_pension: float = 0.0            # 총 퇴직연금 수령액
    total_contribution: float = 0.0       # 총 적립금 (DC)
    investment_return: float = 0.0        # 운용수익 (DC)
    service_years: float = 0.0            # 근속연수
    annual_contributions: list = field(default_factory=list)  # DC: 연도별 적립내역


def calc_retirement_pension(
    inp: WageInput,
    ow: OrdinaryWageResult,
    severance_result: SeveranceResult | None = None,
) -> RetirementPensionResult:
    """퇴직연금 계산 (DB/DC)"""
    warnings = []
    formulas = []
    legal = []

    pension_type = inp.pension_type.upper() if inp.pension_type else "DB"

    if pension_type == "DC":
        return _calc_dc(inp, ow, warnings, formulas, legal)
    else:
        return _calc_db(inp, ow, severance_result, warnings, formulas, legal)


def _calc_db(
    inp: WageInput,
    ow: OrdinaryWageResult,
    severance_result: SeveranceResult | None,
    warnings: list,
    formulas: list,
    legal: list,
) -> RetirementPensionResult:
    """DB형: 퇴직금과 동일 공식"""
    legal.append("근로자퇴직급여보장법 제15조 (확정급여형퇴직연금제도의 급여 수준)")

    if severance_result and severance_result.is_eligible:
        total_pension = severance_result.severance_pay
        service_years = severance_result.service_years
        formulas.append(
            f"DB형 퇴직연금 = 퇴직금과 동일: {total_pension:,.0f}원"
        )
    else:
        avg_daily = ow.hourly_ordinary_wage * 8
        dr = DateRange(inp.start_date, inp.end_date)
        service_days = dr.days
        service_years = round(dr.years, 2)

        if service_days > 0:
            total_pension = avg_daily * 30 * (service_days / 365)
            formulas.append(
                f"DB형: {avg_daily:,.0f}원 x 30일 x ({service_days}일 / 365) "
                f"= {total_pension:,.0f}원"
            )
        else:
            total_pension = 0
            warnings.append("재직기간을 확인할 수 없습니다 (입사일/퇴직일 필요)")

    warnings.append(
        "DB형(확정급여형): 퇴직금과 동일한 급여 수준 보장. "
        "적립금 운용은 회사 책임 (운용수익/손실 근로자 영향 없음)"
    )

    breakdown = {
        "퇴직연금 유형": "확정급여형(DB)",
        "수령액": f"{total_pension:,.0f}원",
        "근속연수": f"{service_years:.2f}년",
    }

    return RetirementPensionResult(
        pension_type="DB",
        total_pension=round(total_pension, 0),
        service_years=service_years,
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )


def _calc_dc(
    inp: WageInput,
    ow: OrdinaryWageResult,
    warnings: list,
    formulas: list,
    legal: list,
) -> RetirementPensionResult:
    """DC형: 매년 연간임금총액/12 적립"""
    legal.append("근로자퇴직급여보장법 제17조 (확정기여형퇴직연금제도의 부담금 납입)")

    contributions = []

    if inp.annual_wage_history:
        for i, annual_wage in enumerate(inp.annual_wage_history, 1):
            contribution = annual_wage / 12
            contributions.append({
                "year": i,
                "annual_wage": annual_wage,
                "contribution": round(contribution, 0),
            })
    else:
        annual_wage = (inp.monthly_wage or ow.monthly_ordinary_wage) * 12
        dr2 = DateRange(inp.start_date, inp.end_date)
        years = max(1, round(dr2.years)) if dr2.is_valid else 1
        for i in range(1, years + 1):
            contribution = annual_wage / 12
            contributions.append({
                "year": i,
                "annual_wage": annual_wage,
                "contribution": round(contribution, 0),
            })

    total_contribution = sum(c["contribution"] for c in contributions)
    service_years = len(contributions)

    # 운용수익 (복리)
    if inp.dc_return_rate > 0:
        accumulated = 0.0
        for c in contributions:
            accumulated = (accumulated + c["contribution"]) * (1 + inp.dc_return_rate)
        investment_return = round(accumulated - total_contribution, 0)
        total_pension = round(accumulated, 0)
        formulas.append(
            f"DC형 적립금: {total_contribution:,.0f}원 "
            f"+ 운용수익(연 {inp.dc_return_rate*100:.1f}%): {investment_return:,.0f}원 "
            f"= {total_pension:,.0f}원"
        )
    else:
        investment_return = 0
        total_pension = total_contribution
        formulas.append(
            f"DC형 적립금: 연간임금총액/12 x {service_years}년 = {total_contribution:,.0f}원"
        )

    warnings.append(
        "DC형(확정기여형): 매년 연간임금총액의 1/12 이상 적립. "
        "운용수익은 근로자 책임 (수익률에 따라 수령액 변동)"
    )
    if inp.dc_return_rate == 0:
        warnings.append(
            "운용수익률 0%로 계산 (최소 보장 기준). "
            "실제 수령액은 운용 실적에 따라 달라집니다."
        )

    breakdown = {
        "퇴직연금 유형": "확정기여형(DC)",
        "총 적립금": f"{total_contribution:,.0f}원",
        "운용수익": f"{investment_return:,.0f}원",
        "총 수령액": f"{total_pension:,.0f}원",
        "적립 기간": f"{service_years}년",
    }

    for c in contributions:
        breakdown[f"{c['year']}년차 적립"] = (
            f"연임금 {c['annual_wage']:,.0f}원 / 12 = {c['contribution']:,.0f}원"
        )

    return RetirementPensionResult(
        pension_type="DC",
        total_pension=total_pension,
        total_contribution=total_contribution,
        investment_return=investment_return,
        service_years=service_years,
        annual_contributions=contributions,
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )
