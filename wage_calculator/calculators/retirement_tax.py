"""
퇴직소득세 계산기 (소득세법 제48조, 시행령 제42조의2)

nodong.kr/retire_pay_tax (cal_v2026_1.js) 로직 기반 구현

계산 흐름:
  퇴직급여 → 근속연수공제 → 환산급여 → 환산급여별공제
  → 과세표준 → 세율적용 → 환산산출세액
  → 최종 퇴직소득세 = floor(환산산출세액 / 12 x 근속연수)
  → 지방소득세 = floor(퇴직소득세 x 10%)
  → IRP 과세이연 (선택)
"""

import math
from dataclasses import dataclass
from datetime import date

from ..base import BaseCalculatorResult
from ..models import WageInput
from .ordinary_wage import OrdinaryWageResult
from .severance import SeveranceResult
from .shared import DateRange
from ..constants import (
    RETIREMENT_SERVICE_DEDUCTION,
    CONVERTED_SALARY_DEDUCTION,
    INCOME_TAX_BRACKETS,
    LOCAL_INCOME_TAX_RATE,
)


@dataclass
class RetirementTaxResult(BaseCalculatorResult):
    # 입력/기본
    retirement_pay: float = 0.0           # 퇴직급여 총액
    service_years: int = 0                # 근속연수 (정수, 1년 미만 올림)

    # 공제 과정
    service_deduction: float = 0.0        # 근속연수공제액
    converted_salary: float = 0.0         # 환산급여
    converted_deduction: float = 0.0      # 환산급여별 공제액
    tax_base: float = 0.0                 # 과세표준

    # 세액
    converted_tax: float = 0.0            # 환산산출세액
    retirement_income_tax: float = 0.0    # 퇴직소득세
    local_income_tax: float = 0.0         # 지방소득세
    total_tax: float = 0.0               # 총 세액 (소득세 + 지방세)

    # IRP 과세이연
    irp_amount: float = 0.0              # IRP 이체금액
    deferred_tax: float = 0.0            # 이연 퇴직소득세
    deferred_local_tax: float = 0.0      # 이연 지방소득세
    withholding_tax: float = 0.0         # 원천징수 퇴직소득세
    withholding_local_tax: float = 0.0   # 원천징수 지방소득세

    # 실수령액
    net_retirement_pay: float = 0.0       # 실수령 퇴직금 (세후)


def calc_retirement_tax(
    inp: WageInput,
    ow: OrdinaryWageResult,
    severance_result: SeveranceResult | None = None,
) -> RetirementTaxResult:
    """퇴직소득세 계산 (소득세법 제48조, 시행령 제42조의2)"""
    warnings = []
    formulas = []
    legal = [
        "소득세법 제22조 (퇴직소득)",
        "소득세법 제48조 (퇴직소득공제)",
        "소득세법 제55조 (세율)",
        "소득세법 시행령 제42조의2 (환산급여 및 환산급여별 공제)",
    ]

    # ── Step 1: 퇴직급여 및 근속일수 결정 ──────────────────────────────────
    if severance_result and severance_result.is_eligible:
        retirement_pay = severance_result.severance_pay
        service_days = severance_result.service_days
    else:
        retirement_pay = inp.retirement_pay_amount
        dr = DateRange(inp.start_date, inp.end_date)
        service_days = dr.days

    if retirement_pay <= 0 or service_days <= 0:
        return _zero_result(retirement_pay, warnings, formulas, legal)

    # ── Step 2: 근속연수 계산 (제외/가산월 반영) ───────────────────────────
    total_months = service_days * 12 / 365
    total_months = total_months - inp.retirement_exclude_months + inp.retirement_add_months
    service_years = max(1, math.ceil(total_months / 12))

    formulas.append(f"근속연수: {service_years}년 (재직일수 {service_days}일)")

    # ── Step 3: 근속연수공제 ───────────────────────────────────────────────
    service_deduction = _calc_service_deduction(service_years)
    service_deduction = min(service_deduction, retirement_pay)

    formulas.append(f"근속연수공제: {service_deduction:,.0f}원")

    # ── Step 4: 환산급여 ───────────────────────────────────────────────────
    converted_salary = math.floor(
        (retirement_pay - service_deduction) * 12 / service_years
    )
    converted_salary = max(0, converted_salary)

    formulas.append(
        f"환산급여: ({retirement_pay:,.0f} - {service_deduction:,.0f}) "
        f"x 12 / {service_years} = {converted_salary:,.0f}원"
    )

    # ── Step 5: 환산급여별 공제 ────────────────────────────────────────────
    converted_deduction = _calc_converted_deduction(converted_salary)

    formulas.append(f"환산급여별 공제: {converted_deduction:,.0f}원")

    # ── Step 6: 과세표준 ──────────────────────────────────────────────────
    tax_base = max(0, converted_salary - converted_deduction)

    formulas.append(
        f"과세표준: {converted_salary:,.0f} - {converted_deduction:,.0f} "
        f"= {tax_base:,.0f}원"
    )

    # ── Step 7: 환산산출세액 ──────────────────────────────────────────────
    converted_tax = _calc_tax_by_brackets(tax_base)

    formulas.append(f"환산산출세액: {converted_tax:,.0f}원")

    # ── Step 8: 최종 퇴직소득세 ────────────────────────────────────────────
    retirement_income_tax = math.floor(converted_tax / 12 * service_years)
    local_income_tax = math.floor(retirement_income_tax * LOCAL_INCOME_TAX_RATE)
    total_tax = retirement_income_tax + local_income_tax

    formulas.append(
        f"퇴직소득세: floor({converted_tax:,.0f} / 12 x {service_years}) "
        f"= {retirement_income_tax:,.0f}원"
    )
    formulas.append(f"지방소득세: {local_income_tax:,.0f}원 (소득세 x 10%)")

    # ── Step 9: IRP 과세이연 ──────────────────────────────────────────────
    irp_amount = min(inp.irp_transfer_amount, retirement_pay)
    if irp_amount > 0 and retirement_pay > 0:
        deferred_tax = math.floor(
            retirement_income_tax * irp_amount / retirement_pay
        )
        deferred_local_tax = math.floor(deferred_tax * LOCAL_INCOME_TAX_RATE)
        legal.append("근로자퇴직급여보장법 제9조 (IRP 과세이연)")
        formulas.append(
            f"IRP 이연세액: {deferred_tax:,.0f}원 "
            f"(퇴직소득세 x {irp_amount:,.0f} / {retirement_pay:,.0f})"
        )
    else:
        deferred_tax = 0
        deferred_local_tax = 0

    # 원천징수액 (10원 미만 절사)
    withholding_tax = math.floor(
        (retirement_income_tax - deferred_tax) / 10
    ) * 10
    withholding_local_tax = math.floor(
        (local_income_tax - deferred_local_tax) / 10
    ) * 10

    # ── 실수령액 ──────────────────────────────────────────────────────────
    net_retirement_pay = retirement_pay - withholding_tax - withholding_local_tax

    formulas.append(
        f"실수령 퇴직금: {retirement_pay:,.0f} - {withholding_tax:,.0f} "
        f"- {withholding_local_tax:,.0f} = {net_retirement_pay:,.0f}원"
    )

    breakdown = {
        "퇴직급여": f"{retirement_pay:,.0f}원",
        "근속연수": f"{service_years}년",
        "근속연수공제": f"{service_deduction:,.0f}원",
        "환산급여": f"{converted_salary:,.0f}원",
        "환산급여별 공제": f"{converted_deduction:,.0f}원",
        "과세표준": f"{tax_base:,.0f}원",
        "환산산출세액": f"{converted_tax:,.0f}원",
        "퇴직소득세": f"{retirement_income_tax:,.0f}원",
        "지방소득세": f"{local_income_tax:,.0f}원",
        "총 세액": f"{total_tax:,.0f}원",
    }

    if irp_amount > 0:
        breakdown["IRP 이체금액"] = f"{irp_amount:,.0f}원"
        breakdown["이연 퇴직소득세"] = f"{deferred_tax:,.0f}원"
        breakdown["이연 지방소득세"] = f"{deferred_local_tax:,.0f}원"
        breakdown["원천징수 소득세"] = f"{withholding_tax:,.0f}원"
        breakdown["원천징수 지방소득세"] = f"{withholding_local_tax:,.0f}원"

    breakdown["실수령 퇴직금"] = f"{net_retirement_pay:,.0f}원"

    return RetirementTaxResult(
        retirement_pay=retirement_pay,
        service_years=service_years,
        service_deduction=service_deduction,
        converted_salary=converted_salary,
        converted_deduction=converted_deduction,
        tax_base=tax_base,
        converted_tax=converted_tax,
        retirement_income_tax=retirement_income_tax,
        local_income_tax=local_income_tax,
        total_tax=total_tax,
        irp_amount=irp_amount,
        deferred_tax=deferred_tax,
        deferred_local_tax=deferred_local_tax,
        withholding_tax=withholding_tax,
        withholding_local_tax=withholding_local_tax,
        net_retirement_pay=net_retirement_pay,
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )


# ── 내부 헬퍼 ────────────────────────────────────────────────────────────


def _calc_service_deduction(years: int) -> float:
    """근속연수공제 계산"""
    prev_upper = 0
    for upper, per_year, base in RETIREMENT_SERVICE_DEDUCTION:
        if years <= upper:
            return base + (years - prev_upper) * per_year
        prev_upper = upper
    return 0


def _calc_converted_deduction(converted_salary: float) -> float:
    """환산급여별 공제 계산"""
    if converted_salary <= 0:
        return 0
    prev_upper = 0
    for upper, rate, base in CONVERTED_SALARY_DEDUCTION:
        if converted_salary <= upper:
            return base + (converted_salary - prev_upper) * rate
        prev_upper = upper
    return 0


def _calc_tax_by_brackets(tax_base: float) -> float:
    """종합소득세율 적용 (INCOME_TAX_BRACKETS 재사용)"""
    if tax_base <= 0:
        return 0
    for upper, rate, deduction in INCOME_TAX_BRACKETS:
        if tax_base <= upper:
            return tax_base * rate - deduction
    return 0


def _zero_result(
    retirement_pay: float,
    warnings: list,
    formulas: list,
    legal: list,
) -> RetirementTaxResult:
    if retirement_pay <= 0:
        warnings.append("퇴직급여가 0원 이하입니다")
    else:
        warnings.append("근속기간을 확인할 수 없습니다 (입사일/퇴직일 필요)")
    return RetirementTaxResult(
        retirement_pay=retirement_pay,
        net_retirement_pay=retirement_pay,
        breakdown={"퇴직소득세": "계산 불가"},
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )
