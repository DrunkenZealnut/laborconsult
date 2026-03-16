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
from ..models import WageInput, NonTaxableIncome
from .ordinary_wage import OrdinaryWageResult
from ..constants import (
    get_insurance_rates,
    FREELANCER_TAX_RATE,
    INCOME_TAX_BRACKETS,
    EARNED_INCOME_DEDUCTION,
    PERSONAL_DEDUCTION_PER_PERSON,
    INDUSTRIAL_ACCIDENT_COMPONENTS,
    DEFAULT_INDUSTRY_RATE,
    SPECIAL_DEDUCTION_PARAMS,
    HIGH_INCOME_TAX_BRACKETS,
    EARNED_INCOME_TAX_CREDIT_THRESHOLD,
    EARNED_INCOME_TAX_CREDIT_LOW_RATE,
    EARNED_INCOME_TAX_CREDIT_HIGH_BASE,
    EARNED_INCOME_TAX_CREDIT_HIGH_RATE,
    EARNED_INCOME_TAX_CREDIT_LIMITS,
    get_child_tax_credit_monthly,
    get_nontaxable_limits,
    NON_TAXABLE_INCOME_LEGAL_BASIS,
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
    health_premium_max = rates.get("health_premium_max", float("inf"))
    health_premium_min = rates.get("health_premium_min", 0)

    legal.append("국민연금법 제88조 (보험료 부담)")
    legal.append("국민건강보험법 제69조 (보험료)")
    legal.append("고용보험법 제49조 (고용보험료)")
    legal.append("소득세법 제134조 (근로소득 원천징수)")

    # ── 국민연금 ─────────────────────────────────────────────────────────────
    pension_base = max(pension_min, min(gross, pension_max))
    pension_base = (pension_base // 1000) * 1000  # 기준소득월액 1,000원 미만 절사
    national_pension = int(pension_base * pension_rate)  # 원 미만 절사
    if gross > pension_max:
        warnings.append(
            f"국민연금: 기준소득월액 상한({pension_max:,}원) 적용"
        )
    formulas.append(
        f"국민연금: {pension_base:,.0f}원(1천원절사) × {pension_rate*100:.2f}% = {national_pension:,.0f}원 ({year}년)"
    )

    # ── 건강보험 ─────────────────────────────────────────────────────────────
    health_insurance = int(gross * health_rate)  # 원 미만 절사
    health_insurance = max(health_premium_min, min(health_insurance, health_premium_max))
    if health_insurance >= health_premium_max:
        warnings.append(
            f"건강보험: 보험료 상한({health_premium_max:,}원) 적용"
        )
    formulas.append(
        f"건강보험: {gross:,.0f}원 × {health_rate*100:.3f}% = {health_insurance:,.0f}원 ({year}년)"
    )

    # ── 장기요양보험 (건강보험료 기준) ──────────────────────────────────────
    long_term_care = int(health_insurance * ltc_rate)  # 원 미만 절사
    formulas.append(
        f"장기요양: {health_insurance:,.0f}원 × {ltc_rate*100:.2f}% = {long_term_care:,.0f}원 ({year}년)"
    )

    # ── 고용보험 ─────────────────────────────────────────────────────────────
    employment_insurance = int(gross * emp_rate)  # 원 미만 절사
    formulas.append(
        f"고용보험: {gross:,.0f}원 × {emp_rate*100:.1f}% = {employment_insurance:,.0f}원 ({year}년)"
    )

    total_insurance = national_pension + health_insurance + long_term_care + employment_insurance

    # ── 비과세 근로소득 산정 ──────────────────────────────────────────────────
    if inp.non_taxable_detail is not None:
        nontax_amount, nontax_warns, nontax_formulas, nontax_legal = (
            calc_nontaxable_total(inp.non_taxable_detail, year, inp)
        )
        warnings.extend(nontax_warns)
        formulas.extend(nontax_formulas)
        legal.extend(nontax_legal)
    else:
        nontax_amount = inp.monthly_non_taxable

    # ── 근로소득세 (2026 간이세액표 산출식, 소득세법 시행령 별표 2 <개정 2026. 2. 27.>) ──
    taxable_monthly = max(0.0, gross - nontax_amount)

    if taxable_monthly > 10_000_000:
        # 월급여액 10,000천원 초과: 고소득 간이세액표 산출식
        # ① 10,000천원 기준세액 산출 (산출식 ①~⑨ 적용)
        base_annual = 10_000_000 * 12
        earned_ded = _stepped_deduction(base_annual)
        personal_ded = inp.tax_dependents * PERSONAL_DEDUCTION_PER_PERSON
        pension_annual = national_pension * 12
        special_ded = _calc_special_deduction(base_annual, inp.tax_dependents)
        taxable_income = max(0.0, base_annual - earned_ded - personal_ded
                             - pension_annual - special_ded)
        assessed_tax = _calc_income_tax(taxable_income)
        earned_credit = _calc_earned_income_tax_credit(assessed_tax, base_annual)
        annual_tax_at_10m = max(0.0, assessed_tax - earned_credit)
        base_tax = (int(annual_tax_at_10m / 12) // 10) * 10

        # ② 초과분 가산세액
        surcharge = _calc_high_income_surcharge(taxable_monthly)
        income_tax = base_tax + surcharge

        formulas.append(
            f"근로소득세(간이세액표 고소득): 10,000천원 기준세액 {base_tax:,.0f}원"
            f" + 초과분 가산세액 {surcharge:,.0f}원 = 월 {income_tax:,.0f}원"
            f" (부양가족 {inp.tax_dependents}인, 비과세 {nontax_amount:,.0f}원/월)"
        )
    else:
        annual_gross = taxable_monthly * 12
        # ① 근로소득공제
        earned_deduction = _stepped_deduction(annual_gross)
        # ② 인적공제 (공제대상가족 × 150만원)
        personal_deduction = inp.tax_dependents * PERSONAL_DEDUCTION_PER_PERSON
        # ③ 연금보험료공제 (국민연금 연간 납부액)
        pension_annual = national_pension * 12
        # ④ 특별소득공제 및 특별세액공제
        special_deduction = _calc_special_deduction(annual_gross, inp.tax_dependents)
        # ⑤ 과세표준
        taxable_income = max(0.0, annual_gross - earned_deduction - personal_deduction
                             - pension_annual - special_deduction)
        # ⑥ 산출세액
        assessed_tax = _calc_income_tax(taxable_income)
        # ⑦ 근로소득세액공제
        earned_tax_credit = _calc_earned_income_tax_credit(assessed_tax, annual_gross)
        # ⑧ 연간 결정세액
        annual_income_tax = max(0.0, assessed_tax - earned_tax_credit)
        # ⑨ 월 근로소득세 (10원 미만 절사)
        income_tax = (int(annual_income_tax / 12) // 10) * 10

        formulas.append(
            f"근로소득세(간이세액표): 연 과세표준 {taxable_income:,.0f}원"
            f" → 산출세액 {assessed_tax:,.0f}원 - 세액공제 {earned_tax_credit:,.0f}원"
            f" → 월 {income_tax:,.0f}원"
            f" (부양가족 {inp.tax_dependents}인, 비과세 {nontax_amount:,.0f}원/월)"
        )

    # ⑩ 자녀세액공제 (간이세액표와 별도 공제, 소득세법 제59조의2)
    child_credit = get_child_tax_credit_monthly(inp.num_children_8_to_20, year)
    if child_credit > 0:
        income_tax = max(0, income_tax - child_credit)
        formulas.append(
            f"자녀세액공제: {inp.num_children_8_to_20}명 → 월 {child_credit:,.0f}원 공제 ({year}년)"
        )

    local_income_tax = int(income_tax * 0.1)  # 원 미만 절사
    formulas.append(f"지방소득세: {income_tax:,.0f}원 × 10% = {local_income_tax:,.0f}원")

    total_tax = income_tax + local_income_tax
    total_deduction = total_insurance + total_tax
    monthly_net = gross - total_deduction

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

    # 산재보험 업종 요율
    industry_rate = getattr(inp, "industry_accident_rate", DEFAULT_INDUSTRY_RATE)
    if not industry_rate:
        industry_rate = DEFAULT_INDUSTRY_RATE

    # ── 국민연금 (사업주 = 근로자와 동일) ──────────────────────────────
    pension_rate = rates["national_pension"]
    pension_base = max(rates["pension_income_min"], min(gross, rates["pension_income_max"]))
    pension_base = (pension_base // 1000) * 1000  # 기준소득월액 1,000원 미만 절사
    employer_pension = int(pension_base * pension_rate)  # 원 미만 절사
    formulas.append(
        f"국민연금(사업주): {pension_base:,.0f}원(1천원절사) × {pension_rate*100:.2f}% = {employer_pension:,.0f}원"
    )

    # ── 건강보험 (사업주 = 근로자와 동일) ──────────────────────────────
    health_rate = rates["health_insurance"]
    health_premium_max = rates.get("health_premium_max", float("inf"))
    health_premium_min = rates.get("health_premium_min", 0)
    employer_health = int(gross * health_rate)  # 원 미만 절사
    employer_health = max(health_premium_min, min(employer_health, health_premium_max))
    formulas.append(
        f"건강보험(사업주): {gross:,.0f}원 × {health_rate*100:.3f}% = {employer_health:,.0f}원"
    )

    # ── 장기요양 (건강보험료 기준) ──────────────────────────────────────
    ltc_rate = rates["long_term_care"]
    employer_ltc = int(employer_health * ltc_rate)  # 원 미만 절사
    formulas.append(
        f"장기요양(사업주): {employer_health:,.0f}원 × {ltc_rate*100:.2f}% = {employer_ltc:,.0f}원"
    )

    # ── 고용보험 실업급여 (사업주 = 근로자와 동일) ─────────────────────
    emp_rate = rates["employment_insurance"]
    employer_employment = int(gross * emp_rate)  # 원 미만 절사
    formulas.append(
        f"고용보험 실업급여(사업주): {gross:,.0f}원 × {emp_rate*100:.1f}% = {employer_employment:,.0f}원"
    )

    # ── 직업능력개발부담금 (사업주만 부담, 규모별 차등) ──────────────────
    voc_rate = VOCATIONAL_TRAINING_RATES[size_cat]
    employer_vocational = int(gross * voc_rate)  # 원 미만 절사
    size_label = {"under_150": "150인 미만", "150_999": "150~999인", "over_1000": "1000인 이상"}.get(size_cat, size_cat)
    formulas.append(
        f"직업능력개발({size_label}): {gross:,.0f}원 × {voc_rate*100:.2f}% = {employer_vocational:,.0f}원"
    )

    # ── 산재보험 (전액 사업주 부담, 구성요소별) ──────────────────────────
    commute_rate = INDUSTRIAL_ACCIDENT_COMPONENTS["commute"]
    wage_claim_rate = INDUSTRIAL_ACCIDENT_COMPONENTS["wage_claim"]
    asbestos_rate = INDUSTRIAL_ACCIDENT_COMPONENTS["asbestos"]
    total_accident_rate = industry_rate + commute_rate + wage_claim_rate + asbestos_rate
    employer_accident = int(gross * total_accident_rate)  # 원 미만 절사
    formulas.append(
        f"산재보험: 업종({industry_rate*100:.2f}%) + 출퇴근({commute_rate*100:.1f}%) "
        f"+ 임금채권({wage_claim_rate*100:.1f}%) + 석면({asbestos_rate*100:.2f}%) "
        f"= {total_accident_rate*100:.2f}% → {employer_accident:,.0f}원"
    )
    if industry_rate == DEFAULT_INDUSTRY_RATE:
        warnings.append(
            f"산재보험 업종요율: 전체 평균 {DEFAULT_INDUSTRY_RATE*100:.1f}% 적용. "
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
        f"산재보험({total_accident_rate*100:.2f}%)": f"{employer_accident:,.0f}원",
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


def calc_nontaxable_total(
    nti: NonTaxableIncome,
    year: int,
    inp: WageInput,
) -> tuple[float, list[str], list[str], list[str]]:
    """비과세 근로소득 항목별 한도 적용 후 월 합산

    Args:
        nti: 비과세 항목별 입력
        year: 기준 연도
        inp: WageInput (생산직 적격 판단용 monthly_wage 참조)

    Returns:
        (월 비과세 합계, warnings, formulas, legal_basis)
    """
    limits = get_nontaxable_limits(year)
    total = 0.0
    warnings: list[str] = []
    formulas: list[str] = []
    legal: list[str] = []

    def _apply_cap(value: float, cap: float, label: str, legal_key: str) -> float:
        """항목별 한도 적용 공통 로직"""
        nonlocal total
        if value <= 0:
            return 0.0
        applied = min(value, cap)
        total += applied
        formulas.append(f"{label} 비과세: {applied:,.0f}원 (한도 {cap:,.0f}원/월)")
        legal.append(NON_TAXABLE_INCOME_LEGAL_BASIS[legal_key])
        if value > cap:
            excess = value - cap
            warnings.append(
                f"{label}: {value:,.0f}원 중 {cap:,.0f}원만 비과세, "
                f"초과분 {excess:,.0f}원은 과세소득 편입"
            )
        return applied

    def _apply_unlimited(value: float, label: str, legal_key: str) -> float:
        """한도 없는 비과세 항목 처리"""
        nonlocal total
        if value <= 0:
            return 0.0
        total += value
        formulas.append(f"{label} 비과세: {value:,.0f}원 (한도 없음)")
        legal.append(NON_TAXABLE_INCOME_LEGAL_BASIS[legal_key])
        return value

    # ── 식대 ──────────────────────────────────────────────
    _apply_cap(nti.meal_allowance, limits["meal"], "식대", "meal")

    # ── 자가운전보조금 ────────────────────────────────────
    _apply_cap(nti.car_subsidy, limits["car"], "자가운전보조금", "car")

    # ── 자녀보육수당 ──────────────────────────────────────
    if nti.childcare_allowance > 0:
        if nti.num_childcare_children <= 0:
            warnings.append("보육수당: 6세 이하 자녀 수(num_childcare_children) 미입력 — 비과세 미적용")
        else:
            cap = limits["childcare"] * nti.num_childcare_children
            applied = min(nti.childcare_allowance, cap)
            total += applied
            formulas.append(
                f"자녀보육수당 비과세: {applied:,.0f}원 "
                f"(6세 이하 {nti.num_childcare_children}명, 한도 {cap:,.0f}원/월)"
            )
            legal.append(NON_TAXABLE_INCOME_LEGAL_BASIS["childcare"])
            if nti.childcare_allowance > cap:
                warnings.append(
                    f"보육수당: {nti.childcare_allowance:,.0f}원 중 {cap:,.0f}원만 비과세"
                )

    # ── 생산직 연장근로수당 비과세 ─────────────────────────
    if nti.overtime_nontax > 0:
        eligible, reason = _check_overtime_nontax_eligible(nti, limits, inp)
        if eligible:
            monthly_cap = limits["overtime_annual"] / 12
            applied = min(nti.overtime_nontax, monthly_cap)
            total += applied
            formulas.append(
                f"연장근로수당 비과세: {applied:,.0f}원/월 "
                f"(연 한도 {limits['overtime_annual']:,.0f}원)"
            )
            legal.append(NON_TAXABLE_INCOME_LEGAL_BASIS["overtime"])
            if nti.overtime_nontax > monthly_cap:
                warnings.append(
                    f"연장근로수당: 월 {nti.overtime_nontax:,.0f}원 중 "
                    f"{monthly_cap:,.0f}원만 비과세 (연 {limits['overtime_annual']:,.0f}원 한도)"
                )
        else:
            warnings.append(f"연장근로수당 비과세 부적격: {reason}")

    # ── 국외근로소득 ──────────────────────────────────────
    if nti.overseas_pay > 0:
        cap_key = "overseas_construction" if nti.is_overseas_construction else "overseas"
        cap = limits[cap_key]
        label = "해외건설현장" if nti.is_overseas_construction else "국외근로"
        _apply_cap(nti.overseas_pay, cap, label, "overseas")

    # ── 연구보조비 ────────────────────────────────────────
    _apply_cap(nti.research_subsidy, limits["research"], "연구보조비", "research")

    # ── 취재수당 ──────────────────────────────────────────
    _apply_cap(nti.reporting_subsidy, limits["reporting"], "취재수당", "reporting")

    # ── 벽지수당 ──────────────────────────────────────────
    _apply_cap(nti.remote_area_subsidy, limits["remote_area"], "벽지수당", "remote_area")

    # ── 직무발명보상금 (연간 → 월 환산) ───────────────────
    if nti.invention_reward_annual > 0:
        cap = limits["invention_annual"]
        applied_annual = min(nti.invention_reward_annual, cap)
        applied_monthly = applied_annual / 12
        total += applied_monthly
        formulas.append(
            f"직무발명보상금 비과세: 연 {applied_annual:,.0f}원 "
            f"→ 월 {applied_monthly:,.0f}원 (한도 연 {cap:,.0f}원)"
        )
        legal.append(NON_TAXABLE_INCOME_LEGAL_BASIS["invention"])
        if nti.invention_reward_annual > cap:
            warnings.append(
                f"직무발명보상금: 연 {nti.invention_reward_annual:,.0f}원 중 "
                f"{cap:,.0f}원만 비과세"
            )

    # ── §2 단체보장성보험료 (연간 → 월 환산) ─────────────────
    if nti.group_insurance_annual > 0:
        cap = limits["group_insurance_annual"]
        applied_annual = min(nti.group_insurance_annual, cap)
        applied_monthly = applied_annual / 12
        total += applied_monthly
        formulas.append(
            f"단체보장성보험료 비과세: 연 {applied_annual:,.0f}원 "
            f"→ 월 {applied_monthly:,.0f}원 (한도 연 {cap:,.0f}원)"
        )
        legal.append(NON_TAXABLE_INCOME_LEGAL_BASIS["group_insurance"])
        if nti.group_insurance_annual > cap:
            warnings.append(
                f"단체보장성보험료: 연 {nti.group_insurance_annual:,.0f}원 중 "
                f"{cap:,.0f}원만 비과세"
            )

    # ── §2 경조금 (무한도, 사회통념상 범위) ───────────────────
    _apply_unlimited(nti.congratulatory_pay, "경조금", "congratulatory")

    # ── §3 승선수당 ──────────────────────────────────────────
    _apply_cap(nti.boarding_allowance, limits["boarding"], "승선수당", "boarding")

    # ── §3 지방이전 이주수당 ─────────────────────────────────
    _apply_cap(nti.relocation_subsidy, limits["relocation"], "지방이전 이주수당", "relocation")

    # ── §3 일직·숙직료 ──────────────────────────────────────
    if nti.overnight_duty_pay > 0:
        _apply_cap(nti.overnight_duty_pay, limits["overnight_duty"], "일직·숙직료", "overnight_duty")
        warnings.append("일직·숙직료: 실비변상 범위는 사내 규정 기준이며, 사회통념상 타당한 범위 내 비과세")

    # ── §7 근로자 학자금 (무한도) ─────────────────────────────
    _apply_unlimited(nti.tuition_support, "근로자 학자금", "tuition")

    # ── §7 사택 제공 이익 (무한도) ────────────────────────────
    _apply_unlimited(nti.company_housing, "사택 제공 이익", "company_housing")

    # ── 출산지원금 (한도 없음) ─────────────────────────────
    _apply_unlimited(nti.childbirth_support, "출산지원금", "childbirth")

    # ── 기타 비과세 (사용자 직접 입력, 한도 없음) ──────────
    if nti.other_nontaxable > 0:
        total += nti.other_nontaxable
        formulas.append(f"기타 비과세: {nti.other_nontaxable:,.0f}원 (사용자 입력)")

    formulas.append(f"비과세 근로소득 합계: {total:,.0f}원/월")

    return total, warnings, formulas, legal


def _check_overtime_nontax_eligible(
    nti: NonTaxableIncome,
    limits: dict,
    inp: WageInput,
) -> tuple[bool, str]:
    """생산직 연장근로수당 비과세 적격 여부 (소득세법 제12조제3호나목)

    조건:
      1. 생산직 및 관련직 종사자 (자기 선언)
      2. 월정액급여 한도 이하
      3. 전년도 총급여 한도 이하
    """
    if not nti.is_production_worker:
        return False, "생산직 종사자가 아닌 것으로 입력됨 (is_production_worker=False)"

    monthly_limit = limits["overtime_monthly_salary"]
    monthly_wage = inp.monthly_wage or 0
    if monthly_wage > monthly_limit:
        return False, f"월정액급여 {monthly_wage:,.0f}원 > 한도 {monthly_limit:,.0f}원"

    annual_limit = limits["overtime_prev_year_salary"]
    if nti.prev_year_total_salary > 0 and nti.prev_year_total_salary > annual_limit:
        return False, (
            f"전년도 총급여 {nti.prev_year_total_salary:,.0f}원 > "
            f"한도 {annual_limit:,.0f}원"
        )

    return True, ""


def _calc_high_income_surcharge(monthly_salary: float) -> int:
    """월급여액 10,000천원 초과분 가산세액 (소득세법 시행령 별표 2 <개정 2026. 2. 27.>)

    10,000천원 초과 구간별:
    - 10,000~14,000천원: 초과분 × 98% × 35% + 25,000원
    - 14,000~28,000천원: 1,397,000 + 초과분 × 98% × 38%
    - 28,000~30,000천원: 6,610,600 + 초과분 × 98% × 40%
    - 30,000~45,000천원: 7,394,600 + 초과분 × 40%
    - 45,000~87,000천원: 13,394,600 + 초과분 × 42%
    - 87,000천원 초과:   31,034,600 + 초과분 × 45%
    """
    for upper, base_add, threshold, rate, apply_98 in HIGH_INCOME_TAX_BRACKETS:
        if monthly_salary <= upper:
            excess = monthly_salary - threshold
            if apply_98:
                return int(base_add + excess * 0.98 * rate)
            else:
                return int(base_add + excess * rate)
    return 0


def _calc_special_deduction(annual_gross: float, num_dependents: int) -> float:
    """특별소득공제 및 특별세액공제 계산 (간이세액표 산출식, 소득세법 시행령 별표 2 <개정 2026. 2. 27.>)

    - 공제대상가족수(1/2/3+)와 총급여 구간별 산출식
    - 3인 이상·4500만~7000만: 4,000만원 초과분 × 4% 추가 공제
    - 1.2억 초과: 특별소득공제 0원
    """
    if annual_gross <= 0:
        return 0.0

    dep_key = min(num_dependents, 3)
    if dep_key < 1:
        dep_key = 1

    brackets = SPECIAL_DEDUCTION_PARAMS.get(dep_key, SPECIAL_DEDUCTION_PARAMS[1])

    deduction = 0.0
    for upper, base, rate, excess_rate, add_base, add_rate in brackets:
        if annual_gross <= upper:
            deduction = base + annual_gross * rate
            if excess_rate > 0:
                deduction -= max(0, annual_gross - 30_000_000) * excess_rate
            if add_base > 0 and add_rate > 0:
                deduction += max(0, annual_gross - add_base) * add_rate
            break
    # 1.2억 초과: 특별소득공제 없음 (brackets에 매칭 안 됨 → deduction = 0)

    return max(0.0, deduction)


def _calc_earned_income_tax_credit(assessed_tax: float, annual_gross: float) -> float:
    """근로소득세액공제 계산 (소득세법 제59조)

    - 산출세액 130만원 이하: 산출세액 × 55%
    - 산출세액 130만원 초과: 71.5만원 + 초과분 × 30%
    - 한도: 총급여 3,300만 이하 74만, 7,000만 이하 66만, 초과 50만
    """
    if assessed_tax <= 0:
        return 0.0

    # 세액공제 계산
    if assessed_tax <= EARNED_INCOME_TAX_CREDIT_THRESHOLD:
        credit = assessed_tax * EARNED_INCOME_TAX_CREDIT_LOW_RATE
    else:
        excess = assessed_tax - EARNED_INCOME_TAX_CREDIT_THRESHOLD
        credit = EARNED_INCOME_TAX_CREDIT_HIGH_BASE + excess * EARNED_INCOME_TAX_CREDIT_HIGH_RATE

    # 한도 적용
    for upper, limit in EARNED_INCOME_TAX_CREDIT_LIMITS:
        if annual_gross <= upper:
            credit = min(credit, limit)
            break

    return credit


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
    """근로소득공제 단계별 계산 (소득세법 제47조)"""
    steps = [
        (5_000_000,    0.70),   # ~500만: 70%
        (15_000_000,   0.40),   # 500~1,500만: 40%
        (45_000_000,   0.15),   # 1,500~4,500만: 15%
        (100_000_000,  0.05),   # 4,500~1억: 5%
        (float("inf"), 0.02),   # 1억 초과: 2%
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
