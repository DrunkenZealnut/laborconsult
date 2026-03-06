"""
4대보험료 및 근로소득세 계산기

■ 근로자 (4대보험 가입 대상)
  - 국민연금:    기준소득월액 × 4.5%  (상한 617만원, 하한 39만원)
  - 건강보험:    보수월액    × 3.545%
  - 장기요양:    건강보험료  × 12.95%
  - 고용보험:    보수월액    × 0.9%
  - 근로소득세:  간이세액표 기준 (부양가족 수 반영)
  - 지방소득세:  근로소득세 × 10%

■ 3.3% 계약 (사업소득 원천징수)
  - 소득세:      지급액 × 3%
  - 지방소득세:  지급액 × 0.3%
  - 4대보험 없음 (단, 실질 근로자 해당 시 가입 의무 발생)

■ 실질 근로자 판단기준 (대법원 판례)
  7가지 기준 중 다수 해당 시 근로자로 간주:
  ① 업무 내용·방법·시간에 대한 지휘·감독
  ② 특정 사업장에 소속되어 정해진 근무시간·장소 이용
  ③ 비품·원자재·작업 도구 등을 사용자로부터 제공받음
  ④ 다른 사업주에게 중복 제공 불가 (전속성)
  ⑤ 보수가 근로 자체의 대가 (성과와 무관한 고정급)
  ⑥ 세금·4대보험 등 기본적 노무 관계 법령 적용
  ⑦ 지속성·전속성이 있고 경제적 종속관계
"""

from dataclasses import dataclass

from ..base import BaseCalculatorResult
from ..models import WageInput
from .ordinary_wage import OrdinaryWageResult
from ..constants import (
    get_insurance_rates,
    FREELANCER_TAX_RATE,
    INCOME_TAX_BRACKETS,
    EARNED_INCOME_DEDUCTION,
    PERSONAL_DEDUCTION_PER_PERSON,
)

# 실질 근로자 판단 체크리스트 (대법원 2006다49653 등)
WORKER_JUDGMENT_CRITERIA = [
    "① 업무 내용·방법·시간에 대해 사용자로부터 지휘·감독을 받는가?",
    "② 특정 사업장에 소속되어 정해진 근무시간·근무 장소를 사용하는가?",
    "③ 작업 도구·비품·원자재 등을 사용자로부터 제공받는가?",
    "④ 동일 기간 중 다른 사업주에게 노무를 중복 제공하기 어려운가? (전속성)",
    "⑤ 보수가 근로 자체의 대가이고 성과와 무관한 고정급 성격인가?",
    "⑥ 계속적·정기적으로 동일 사업주에게 노무를 제공하는가? (지속성)",
    "⑦ 경제적으로 사용자에게 종속된 관계인가? (독립적 사업 영위 불가)",
]


@dataclass
class InsuranceResult(BaseCalculatorResult):
    # 세전·세후
    monthly_gross: float = 0.0         # 세전 월 급여 (원)
    monthly_net: float = 0.0           # 세후 월 실수령액 (원)

    # 4대보험 (근로자 부담분)
    national_pension: float = 0.0      # 국민연금 (원)
    health_insurance: float = 0.0      # 건강보험 (원)
    long_term_care: float = 0.0        # 장기요양보험 (원)
    employment_insurance: float = 0.0  # 고용보험 (원)
    total_insurance: float = 0.0       # 4대보험 합계 (원)

    # 세금
    income_tax: float = 0.0            # 근로소득세 (원) / 사업소득세 (원)
    local_income_tax: float = 0.0      # 지방소득세 (원)
    total_tax: float = 0.0             # 세금 합계 (원)

    # 총 공제
    total_deduction: float = 0.0       # 4대보험 + 세금 합계 (원)

    # 메타
    is_freelancer: bool = False        # 3.3% 계약 여부


def calc_insurance(inp: WageInput, ow: OrdinaryWageResult) -> InsuranceResult:
    """4대보험료 및 근로소득세 계산"""
    warnings = []
    formulas = []
    legal = []

    # ── 세전 월 급여 산정 ────────────────────────────────────────────────────
    # 통상임금 기준 월 급여 (고정수당 포함)
    gross = ow.monthly_ordinary_wage
    formulas.append(f"세전 월 급여: {gross:,.0f}원 (통상임금 기준)")

    if inp.is_freelancer:
        return _calc_freelancer(inp, gross, warnings, formulas, legal)
    else:
        return _calc_employee(inp, gross, warnings, formulas, legal, inp.reference_year)


def _calc_employee(
    inp: WageInput,
    gross: float,
    warnings: list,
    formulas: list,
    legal: list,
    year: int = 2025,
) -> InsuranceResult:
    """근로자 4대보험 + 근로소득세 계산"""

    rates = get_insurance_rates(year)
    pension_rate    = rates["national_pension"]
    health_rate     = rates["health_insurance"]
    ltc_rate        = rates["long_term_care"]
    emp_rate        = rates["employment_insurance"]
    pension_max     = rates["pension_income_max"]
    pension_min     = rates["pension_income_min"]

    legal.append("국민연금법 제88조 (보험료 부담)")
    legal.append("국민건강보험법 제69조 (보험료)")
    legal.append("고용보험법 제49조 (고용보험료)")
    legal.append("소득세법 제134조 (근로소득 원천징수)")

    # ── 국민연금 ─────────────────────────────────────────────────────────────
    pension_base = max(pension_min, min(gross, pension_max))
    national_pension = round(pension_base * pension_rate)
    if gross > pension_max:
        warnings.append(
            f"국민연금: 기준소득월액 상한({pension_max:,}원) 적용"
        )
    formulas.append(
        f"국민연금: {pension_base:,.0f}원 × {pension_rate*100:.2f}% = {national_pension:,.0f}원 ({year}년 요율)"
    )

    # ── 건강보험 ─────────────────────────────────────────────────────────────
    health_insurance = round(gross * health_rate)
    formulas.append(
        f"건강보험: {gross:,.0f}원 × {health_rate*100:.3f}% = {health_insurance:,.0f}원 ({year}년 요율)"
    )

    # ── 장기요양보험 (건강보험료 기준) ──────────────────────────────────────
    long_term_care = round(health_insurance * ltc_rate)
    formulas.append(
        f"장기요양: {health_insurance:,.0f}원 × {ltc_rate*100:.2f}% = {long_term_care:,.0f}원 ({year}년 요율)"
    )

    # ── 고용보험 ─────────────────────────────────────────────────────────────
    employment_insurance = round(gross * emp_rate)
    formulas.append(
        f"고용보험: {gross:,.0f}원 × {emp_rate*100:.1f}% = {employment_insurance:,.0f}원 ({year}년 요율)"
    )

    total_insurance = national_pension + health_insurance + long_term_care + employment_insurance

    # ── 근로소득세 (간이세액표 근사 계산) ───────────────────────────────────
    # 과세 기준: 월 급여 - 비과세 소득
    taxable_monthly = max(0.0, gross - inp.monthly_non_taxable)
    # 연간 총급여
    annual_gross = taxable_monthly * 12

    # 근로소득공제
    earned_deduction = _calc_earned_income_deduction(annual_gross)
    # 기본공제 (부양가족 × 150만원)
    personal_deduction = inp.tax_dependents * PERSONAL_DEDUCTION_PER_PERSON
    # 표준세액공제 (연 13만원, 간이세액표 단순화)
    standard_tax_credit = 130_000

    taxable_income = max(0.0, annual_gross - earned_deduction - personal_deduction)

    annual_income_tax = _calc_income_tax(taxable_income) - standard_tax_credit
    annual_income_tax = max(0.0, annual_income_tax)

    income_tax = round(annual_income_tax / 12)
    local_income_tax = round(income_tax * 0.1)

    formulas.append(
        f"근로소득세: 연 과세표준 {taxable_income:,.0f}원 → 연 세액 {annual_income_tax:,.0f}원 → 월 {income_tax:,.0f}원"
        f" (부양가족 {inp.tax_dependents}인, 비과세 {inp.monthly_non_taxable:,.0f}원/월)"
    )
    formulas.append(f"지방소득세: {income_tax:,.0f}원 × 10% = {local_income_tax:,.0f}원")

    total_tax = income_tax + local_income_tax
    total_deduction = total_insurance + total_tax
    monthly_net = round(gross - total_deduction)

    breakdown = {
        "세전 월 급여":   f"{gross:,.0f}원",
        f"국민연금 ({pension_rate*100:.2f}%)":  f"{national_pension:,.0f}원",
        f"건강보험 ({health_rate*100:.3f}%)": f"{health_insurance:,.0f}원",
        f"장기요양 (건보×{ltc_rate*100:.2f}%)": f"{long_term_care:,.0f}원",
        f"고용보험 ({emp_rate*100:.1f}%)": f"{employment_insurance:,.0f}원",
        "4대보험 합계":   f"{total_insurance:,.0f}원",
        "근로소득세":     f"{income_tax:,.0f}원",
        "지방소득세":     f"{local_income_tax:,.0f}원",
        "세금 합계":      f"{total_tax:,.0f}원",
        "총 공제액":      f"{total_deduction:,.0f}원",
        "세후 실수령액":  f"{monthly_net:,.0f}원",
        "적용 기준":      f"{year}년 4대보험 요율",
    }

    return InsuranceResult(
        monthly_gross=gross,
        monthly_net=monthly_net,
        national_pension=national_pension,
        health_insurance=health_insurance,
        long_term_care=long_term_care,
        employment_insurance=employment_insurance,
        total_insurance=total_insurance,
        income_tax=income_tax,
        local_income_tax=local_income_tax,
        total_tax=total_tax,
        total_deduction=total_deduction,
        is_freelancer=False,
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )


def _calc_freelancer(
    inp: WageInput,
    gross: float,
    warnings: list,
    formulas: list,
    legal: list,
) -> InsuranceResult:
    """3.3% 사업소득 원천징수 계산 + 실질 근로자 판단 안내"""

    legal.append("소득세법 제127조 (원천징수의무)")
    legal.append("소득세법 제145조 (사업소득 원천징수)")

    income_tax_base = gross * 0.03
    local_tax_base  = gross * 0.003
    income_tax      = round(income_tax_base)
    local_income_tax = round(local_tax_base)
    total_tax       = income_tax + local_income_tax
    monthly_net     = round(gross - total_tax)

    formulas.append(
        f"사업소득세: {gross:,.0f}원 × 3.0% = {income_tax:,.0f}원"
    )
    formulas.append(
        f"지방소득세: {gross:,.0f}원 × 0.3% = {local_income_tax:,.0f}원"
    )
    formulas.append(
        f"원천징수 합계: {total_tax:,.0f}원 (3.3%)"
    )

    # 실질 근로자 판단 안내
    warnings.append(
        "3.3% 계약이라도 실질적으로 근로자에 해당하면 4대보험 가입 의무가 발생합니다. "
        "아래 기준 중 다수 해당 시 근로기준법상 근로자로 판단될 수 있습니다."
    )
    for criterion in WORKER_JUDGMENT_CRITERIA:
        warnings.append(f"  {criterion}")
    warnings.append(
        "※ 실질 근로자로 판단 시: 사용자는 미가입 기간 4대보험료 소급 납부 + "
        "가산금 부과 대상. 근로자는 고용부(1350) 또는 근로복지공단에 신고 가능."
    )

    breakdown = {
        "계약 유형":      "3.3% 사업소득 계약",
        "지급액 (세전)":  f"{gross:,.0f}원",
        "소득세 (3%)":    f"{income_tax:,.0f}원",
        "지방소득세 (0.3%)": f"{local_income_tax:,.0f}원",
        "원천징수 합계":  f"{total_tax:,.0f}원 (3.3%)",
        "실수령액 (세후)": f"{monthly_net:,.0f}원",
        "4대보험":        "미가입 (사업소득 계약) — 실질 근로자 여부 확인 필요",
    }

    return InsuranceResult(
        monthly_gross=gross,
        monthly_net=monthly_net,
        national_pension=0.0,
        health_insurance=0.0,
        long_term_care=0.0,
        employment_insurance=0.0,
        total_insurance=0.0,
        income_tax=income_tax,
        local_income_tax=local_income_tax,
        total_tax=total_tax,
        total_deduction=total_tax,
        is_freelancer=True,
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )


@dataclass
class EmployerInsuranceResult(BaseCalculatorResult):
    """사업주 4대보험 부담금 계산 결과"""
    monthly_gross: float = 0.0                  # 세전 월 급여 (원)

    # 사업주 부담분
    employer_national_pension: float = 0.0      # 국민연금 사업주 부담 (원)
    employer_health_insurance: float = 0.0      # 건강보험 사업주 부담 (원)
    employer_long_term_care: float = 0.0        # 장기요양 사업주 부담 (원)
    employer_employment_insurance: float = 0.0  # 고용보험 사업주 부담 (원)
    employer_vocational_training: float = 0.0   # 직업능력개발부담금 (고용보험) (원)
    employer_industrial_accident: float = 0.0   # 산재보험 (원)
    total_employer_insurance: float = 0.0       # 사업주 4대보험 합계 (원)

    # 총 인건비
    total_labor_cost: float = 0.0               # 세전급여 + 사업주 4대보험


# ── 사업장 규모별 직업능력개발부담금(고용안정·직능개발) 요율 ──────────────────
# 고용보험법 시행령 제12조 (2025년 기준)
VOCATIONAL_TRAINING_RATES: dict[str, float] = {
    "under_150":   0.0025,   # 150인 미만: 0.25%
    "150_999":     0.0045,   # 150~999인: 0.45%
    "over_1000":   0.0085,   # 1000인 이상: 0.85%
}

# 산재보험 평균 요율 (전체 사업종 평균, 2025년 기준)
# 실제는 업종별로 상이 (0.7%~30%). 기본값 평균 0.7% 사용
DEFAULT_INDUSTRIAL_ACCIDENT_RATE = 0.007


def calc_employer_insurance(inp: WageInput, ow: OrdinaryWageResult) -> EmployerInsuranceResult:
    """
    사업주 4대보험 부담금 계산

    Args:
        inp: 임금 입력 데이터
          - company_size_category: "under_150", "150_999", "over_1000"
          - industry_accident_rate: 산재보험 업종별 요율 (기본 0.007)
        ow: 통상임금 계산 결과
    """
    warnings = []
    formulas = []
    legal = [
        "국민연금법 제88조 (보험료 부담)",
        "국민건강보험법 제76조 (직장가입자 보험료 부담)",
        "고용보험법 제49조, 제13조 (사업주 부담)",
        "산업재해보상보험법 제13조 (보험료 전액 사업주 부담)",
    ]

    year = inp.reference_year
    rates = get_insurance_rates(year)
    gross = ow.monthly_ordinary_wage

    # 사업장 규모 카테고리
    size_cat = getattr(inp, "company_size_category", "under_150") or "under_150"
    if size_cat not in VOCATIONAL_TRAINING_RATES:
        size_cat = "under_150"
        warnings.append("사업장 규모 카테고리 미설정 — '150인 미만' 기준 적용")

    # 산재보험 요율
    accident_rate = getattr(inp, "industry_accident_rate", DEFAULT_INDUSTRIAL_ACCIDENT_RATE)
    if not accident_rate:
        accident_rate = DEFAULT_INDUSTRIAL_ACCIDENT_RATE

    # ── 국민연금 (사업주 = 근로자와 동일 4.5%) ──────────────────────────
    pension_rate = rates["national_pension"]
    pension_base = max(rates["pension_income_min"], min(gross, rates["pension_income_max"]))
    employer_pension = round(pension_base * pension_rate)
    formulas.append(
        f"국민연금(사업주): {pension_base:,.0f}원 × {pension_rate*100:.2f}% = {employer_pension:,.0f}원"
    )

    # ── 건강보험 (사업주 = 근로자와 동일 3.545%) ──────────────────────────
    health_rate = rates["health_insurance"]
    employer_health = round(gross * health_rate)
    formulas.append(
        f"건강보험(사업주): {gross:,.0f}원 × {health_rate*100:.3f}% = {employer_health:,.0f}원"
    )

    # ── 장기요양 (건강보험료 × 12.95%) ──────────────────────────────────
    ltc_rate = rates["long_term_care"]
    employer_ltc = round(employer_health * ltc_rate)
    formulas.append(
        f"장기요양(사업주): {employer_health:,.0f}원 × {ltc_rate*100:.2f}% = {employer_ltc:,.0f}원"
    )

    # ── 고용보험 실업급여 (사업주 = 근로자와 동일 0.9%) ───────────────────
    emp_rate = rates["employment_insurance"]
    employer_employment = round(gross * emp_rate)
    formulas.append(
        f"고용보험 실업급여(사업주): {gross:,.0f}원 × {emp_rate*100:.1f}% = {employer_employment:,.0f}원"
    )

    # ── 직업능력개발부담금 (사업주만 부담, 규모별 차등) ──────────────────
    voc_rate = VOCATIONAL_TRAINING_RATES[size_cat]
    employer_vocational = round(gross * voc_rate)
    size_label = {"under_150": "150인 미만", "150_999": "150~999인", "over_1000": "1000인 이상"}.get(size_cat, size_cat)
    formulas.append(
        f"직업능력개발({size_label}): {gross:,.0f}원 × {voc_rate*100:.2f}% = {employer_vocational:,.0f}원"
    )

    # ── 산재보험 (전액 사업주 부담) ──────────────────────────────────────
    employer_accident = round(gross * accident_rate)
    formulas.append(
        f"산재보험(업종요율 {accident_rate*100:.2f}%): {gross:,.0f}원 × {accident_rate*100:.2f}% = {employer_accident:,.0f}원"
    )
    if accident_rate == DEFAULT_INDUSTRIAL_ACCIDENT_RATE:
        warnings.append(
            f"산재보험 요율: 전체 업종 평균 {DEFAULT_INDUSTRIAL_ACCIDENT_RATE*100:.1f}% 적용. "
            "실제 요율은 업종별 상이 (근로복지공단 확인 필요)"
        )

    # ── 합계 ─────────────────────────────────────────────────────────────
    total_employer = (
        employer_pension + employer_health + employer_ltc
        + employer_employment + employer_vocational + employer_accident
    )
    total_labor_cost = gross + total_employer

    formulas.append(
        f"사업주 4대보험 합계: {total_employer:,.0f}원 (세전급여 대비 {total_employer/gross*100:.1f}%)"
    )
    formulas.append(
        f"총 인건비(세전급여 + 사업주 보험): {gross:,.0f}원 + {total_employer:,.0f}원 = {total_labor_cost:,.0f}원"
    )

    breakdown = {
        "세전 월 급여": f"{gross:,.0f}원",
        f"국민연금({pension_rate*100:.2f}%)": f"{employer_pension:,.0f}원",
        f"건강보험({health_rate*100:.3f}%)": f"{employer_health:,.0f}원",
        f"장기요양(건보×{ltc_rate*100:.2f}%)": f"{employer_ltc:,.0f}원",
        f"고용보험 실업급여({emp_rate*100:.1f}%)": f"{employer_employment:,.0f}원",
        f"직업능력개발({voc_rate*100:.2f}%, {size_label})": f"{employer_vocational:,.0f}원",
        f"산재보험({accident_rate*100:.2f}%)": f"{employer_accident:,.0f}원",
        "사업주 4대보험 합계": f"{total_employer:,.0f}원",
        "총 인건비(사업주 관점)": f"{total_labor_cost:,.0f}원",
        "적용 기준": f"{year}년 요율 / {size_label}",
    }

    return EmployerInsuranceResult(
        monthly_gross=gross,
        employer_national_pension=employer_pension,
        employer_health_insurance=employer_health,
        employer_long_term_care=employer_ltc,
        employer_employment_insurance=employer_employment,
        employer_vocational_training=employer_vocational,
        employer_industrial_accident=employer_accident,
        total_employer_insurance=total_employer,
        total_labor_cost=total_labor_cost,
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )


def _calc_earned_income_deduction(annual_gross: float) -> float:
    """근로소득공제 계산 (연간 총급여 기준)"""
    from ..constants import EARNED_INCOME_DEDUCTION
    prev_limit = 0.0
    deduction = 0.0
    for limit, base_deduction, marginal_rate in EARNED_INCOME_DEDUCTION:
        if annual_gross <= prev_limit:
            break
        if annual_gross <= limit:
            excess = annual_gross - prev_limit
            deduction = base_deduction + (excess * marginal_rate if marginal_rate else 0)
            # 첫 구간은 그냥 율 적용
            if prev_limit == 0:
                deduction = annual_gross * marginal_rate if marginal_rate else annual_gross * 0.70
            break
        prev_limit = limit

    # 총급여 구간별 단계 공제 계산 (누진식)
    # 재계산: 단계형 공제
    deduction = _stepped_deduction(annual_gross)
    return min(deduction, 20_000_000)  # 공제 한도 2,000만원


def _stepped_deduction(annual_gross: float) -> float:
    """근로소득공제 단계별 계산"""
    steps = [
        (5_000_000,   0.70),
        (10_000_000,  0.40),
        (30_000_000,  0.15),
        (55_000_000,  0.05),
        (float("inf"), 0.02),
    ]
    deduction = 0.0
    prev = 0.0
    for limit, rate in steps:
        if annual_gross <= prev:
            break
        taxable_in_bracket = min(annual_gross, limit) - prev
        deduction += taxable_in_bracket * rate
        prev = limit
    return deduction


def _calc_income_tax(taxable_income: float) -> float:
    """근로소득세 계산 (누진세율표 적용)"""
    from ..constants import INCOME_TAX_BRACKETS
    for upper, rate, deduction in INCOME_TAX_BRACKETS:
        if taxable_income <= upper:
            return max(0.0, taxable_income * rate - deduction)
    return 0.0
