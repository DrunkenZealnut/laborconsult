"""
근로장려금(EITC) 및 자녀장려금 계산기

조세특례제한법 제100조의2~12, 제100조의27

핵심 계산식:
  가구유형별(단독/홑벌이/맞벌이) 점증-평탄-점감 3구간 산식
    - 점증: 소득 x (최대액 / 점증종료소득)
    - 평탄: 최대액
    - 점감: 최대액 - (소득 - 평탄종료) x 최대액 / (점감종료 - 평탄종료)

  재산 감액: 가구 재산 1.7억 초과 ~ 2.4억 미만 -> 50% 감액

  자녀장려금: 18세 미만 부양자녀 x 최대 100만원 (소득 4,000만원 미만)
"""

from dataclasses import dataclass

from ..base import BaseCalculatorResult
from ..models import WageInput
from .ordinary_wage import OrdinaryWageResult
from ..constants import (
    get_eitc_params,
    EITC_ASSET_UPPER,
    EITC_ASSET_REDUCTION,
    EITC_ASSET_REDUCTION_RATE,
    CHILD_CREDIT_MAX_PER_CHILD,
    CHILD_CREDIT_INCOME_LIMIT,
    SPOUSE_INCOME_THRESHOLD,
)

# 가구유형 한글 -> EITC_PARAMS 키
_HOUSEHOLD_KEY = {
    "단독":   "single",
    "홑벌이": "single_earner",
    "맞벌이": "dual_earner",
}

_HOUSEHOLD_LABEL = {
    "단독":   "단독가구",
    "홑벌이": "홑벌이가구",
    "맞벌이": "맞벌이가구",
}


@dataclass
class EitcResult(BaseCalculatorResult):
    """근로장려금(EITC) + 자녀장려금 계산 결과"""
    # 입력 확인
    household_type: str = ""
    annual_income: float = 0.0
    total_assets: float = 0.0

    # 수급 판정
    is_eligible: bool = False
    ineligible_reason: str = ""

    # 근로장려금
    income_zone: str = ""
    eitc_raw: float = 0.0
    asset_reduction: bool = False
    eitc_final: float = 0.0

    # 자녀장려금
    child_credit_per_child: float = 0.0
    child_credit_total: float = 0.0
    num_children: int = 0

    # 합계
    total_credit: float = 0.0


def calc_eitc(inp: WageInput, ow: OrdinaryWageResult) -> EitcResult:
    """
    근로장려금(EITC) + 자녀장려금 계산

    Args:
        inp: 임금 입력 데이터
          - household_type: "단독"/"홑벌이"/"맞벌이" (빈 문자열이면 자동 판정)
          - annual_total_income: 연간 총소득 (원). 0이면 monthly_wage*12 추정
          - total_assets: 가구원 재산 합계 (원)
          - num_children_under_18: 18세 미만 부양자녀 수
        ow: 통상임금 계산 결과 (EITC에서는 직접 사용하지 않음)
    """
    warnings: list[str] = []
    formulas: list[str] = []
    legal = [
        "조세특례제한법 제100조의3 (근로장려금 수급 요건)",
        "조세특례제한법 제100조의5 (근로장려금 산정)",
    ]

    year = inp.reference_year

    # ── 1. 가구유형 결정 ──────────────────────────────────────────────────
    household = inp.household_type.strip() if inp.household_type else ""
    if not household or household not in _HOUSEHOLD_KEY:
        household = _determine_household_type(inp)
        warnings.append(
            f"가구유형 자동 판정: '{_HOUSEHOLD_LABEL.get(household, household)}' "
            f"(배우자 소득·부양자녀·직계존속 정보 기반)"
        )

    household_key = _HOUSEHOLD_KEY[household]
    label = _HOUSEHOLD_LABEL.get(household, household)
    formulas.append(f"가구유형: {label}")

    # ── 2. 연간 총소득 결정 ───────────────────────────────────────────────
    income = max(0.0, inp.annual_total_income)
    if income == 0:
        if inp.monthly_wage:
            income = inp.monthly_wage * 12
            warnings.append(
                f"연간 총소득 미입력 — 월급 {inp.monthly_wage:,.0f}원 x 12 = "
                f"{income:,.0f}원으로 추정합니다."
            )
        elif inp.annual_wage:
            income = inp.annual_wage
        else:
            return _ineligible(
                "소득 정보 없음 — 연간 총소득 또는 월급 정보가 필요합니다.",
                household, income, inp.total_assets, warnings, legal,
            )

    formulas.append(f"연간 총소득: {income:,.0f}원")

    # ── 3. EITC 기준표 조회 ───────────────────────────────────────────────
    params_all = get_eitc_params(year)
    if year not in {2024, 2025}:
        warnings.append(f"{year}년 EITC 기준이 미확정 — 가장 최근 기준으로 계산합니다.")
    p = params_all[household_key]

    # ── 4. 소득 요건 체크 ─────────────────────────────────────────────────
    if income >= p["phase_out_end"]:
        return _ineligible(
            f"총소득 {income:,.0f}원 >= 상한 {p['phase_out_end']:,.0f}원 "
            f"({label} 기준) — 소득 초과",
            household, income, inp.total_assets, warnings, legal,
        )

    # ── 5. 재산 요건 체크 ─────────────────────────────────────────────────
    assets = max(0.0, inp.total_assets)
    if assets >= EITC_ASSET_UPPER:
        return _ineligible(
            f"가구 재산 {assets:,.0f}원 >= {EITC_ASSET_UPPER:,.0f}원 — 재산 초과",
            household, income, assets, warnings, legal,
        )

    # ── 6. 근로장려금 산출 ────────────────────────────────────────────────
    eitc_raw, zone = _calc_eitc_amount(income, p)
    eitc_raw = round(eitc_raw)

    zone_range = _zone_range_str(zone, p)
    formulas.append(f"소득구간: {zone} ({zone_range})")
    formulas.append(f"근로장려금(감액 전): {eitc_raw:,.0f}원")

    # ── 7. 재산 감액 ─────────────────────────────────────────────────────
    asset_reduced = False
    eitc_final = eitc_raw
    if assets > EITC_ASSET_REDUCTION:
        asset_reduced = True
        eitc_final = round(eitc_raw * (1 - EITC_ASSET_REDUCTION_RATE))
        formulas.append(
            f"재산 {assets:,.0f}원 > {EITC_ASSET_REDUCTION:,.0f}원 → "
            f"{int(EITC_ASSET_REDUCTION_RATE * 100)}% 감액: {eitc_final:,.0f}원"
        )
        warnings.append(
            f"재산 {assets:,.0f}원이 1.7억 초과 — 근로장려금·자녀장려금 50% 감액 적용"
        )
    elif assets > 0:
        formulas.append(
            f"재산 {assets:,.0f}원 <= {EITC_ASSET_REDUCTION:,.0f}원 → 감액 미적용"
        )
    else:
        warnings.append(
            "재산 정보 미입력 — 재산 요건 미검증. "
            "실제 수급 시 가구원 재산 합계 2.4억 미만이어야 합니다."
        )

    # ── 8. 자녀장려금 ────────────────────────────────────────────────────
    num_children = max(0, inp.num_children_under_18)
    child_per = 0.0
    child_total = 0.0

    if num_children > 0 and household != "단독":
        if income < CHILD_CREDIT_INCOME_LIMIT:
            child_max = CHILD_CREDIT_MAX_PER_CHILD.get(
                year, CHILD_CREDIT_MAX_PER_CHILD[max(CHILD_CREDIT_MAX_PER_CHILD)]
            )
            child_per = child_max
            if asset_reduced:
                child_per = round(child_max * (1 - EITC_ASSET_REDUCTION_RATE))
            child_total = child_per * num_children
            formulas.append(
                f"자녀장려금: {num_children}명 x {child_per:,.0f}원 = {child_total:,.0f}원"
            )
            legal.append("조세특례제한법 제100조의27 (자녀장려금)")
        else:
            warnings.append(
                f"자녀장려금: 총소득 {income:,.0f}원 >= "
                f"{CHILD_CREDIT_INCOME_LIMIT:,.0f}원 — 소득 초과로 수급 불가"
            )
    elif num_children > 0 and household == "단독":
        warnings.append("단독가구는 자녀장려금 수급 대상이 아닙니다.")

    # ── 9. 합계 ──────────────────────────────────────────────────────────
    total = eitc_final + child_total
    formulas.append(f"합계: 근로장려금 {eitc_final:,.0f}원 + 자녀장려금 {child_total:,.0f}원 = {total:,.0f}원")

    # 공통 안내
    warnings.append(
        "근로장려금은 추정치입니다. 정확한 금액은 국세청 홈택스(www.hometax.go.kr)에서 확인하세요."
    )
    warnings.append(
        "신청 기한: 정기 5월 (전년도 소득 기준), 반기 상반기 9월 / 하반기 3월"
    )

    breakdown = {
        "가구유형": label,
        "연간 총소득": f"{income:,.0f}원",
        "가구 재산": f"{assets:,.0f}원" if assets > 0 else "미입력",
        "소득구간": f"{zone} ({zone_range})",
        "근로장려금(감액 전)": f"{eitc_raw:,.0f}원",
        "재산 감액": f"{int(EITC_ASSET_REDUCTION_RATE * 100)}% 적용" if asset_reduced else "미적용",
        "근로장려금(최종)": f"{eitc_final:,.0f}원",
    }
    if child_total > 0:
        breakdown["자녀장려금"] = f"{child_total:,.0f}원 ({num_children}명 x {child_per:,.0f}원)"
    breakdown["합계"] = f"{total:,.0f}원"
    breakdown["기준 연도"] = f"{year}년"
    breakdown["신청 안내"] = "정기 5월 / 반기 3월·9월"

    return EitcResult(
        household_type=household,
        annual_income=income,
        total_assets=assets,
        is_eligible=True,
        income_zone=zone,
        eitc_raw=eitc_raw,
        asset_reduction=asset_reduced,
        eitc_final=eitc_final,
        child_credit_per_child=child_per,
        child_credit_total=child_total,
        num_children=num_children,
        total_credit=total,
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────


def _determine_household_type(inp: WageInput) -> str:
    """배우자 소득·부양자녀·직계존속 정보로 가구유형 자동 판정"""
    has_children = inp.num_children_under_18 > 0
    has_elderly = inp.has_elderly_parent
    has_spouse = inp.spouse_income > 0 or inp.tax_dependents > 1

    if not has_spouse and not has_children and not has_elderly:
        return "단독"
    if has_spouse and inp.spouse_income >= SPOUSE_INCOME_THRESHOLD:
        return "맞벌이"
    return "홑벌이"


def _calc_eitc_amount(income: float, p: dict) -> tuple[float, str]:
    """3구간(점증/평탄/점감) 근로장려금 산출. Returns (금액, 구간명)"""
    max_amt = p["max"]
    inc_end = p["inc_end"]
    flat_end = p["flat_end"]
    phase_out_end = p["phase_out_end"]

    if income <= inc_end:
        return (income * max_amt / inc_end, "점증")

    if income <= flat_end:
        return (float(max_amt), "평탄")

    # 점감
    phase_range = phase_out_end - flat_end
    amount = max_amt - (income - flat_end) * max_amt / phase_range
    return (max(0.0, amount), "점감")


def _zone_range_str(zone: str, p: dict) -> str:
    """구간별 소득 범위 문자열"""
    if zone == "점증":
        return f"0 ~ {p['inc_end']:,.0f}원"
    if zone == "평탄":
        return f"{p['inc_end']:,.0f} ~ {p['flat_end']:,.0f}원"
    return f"{p['flat_end']:,.0f} ~ {p['phase_out_end']:,.0f}원"


def _ineligible(
    reason: str,
    household: str,
    income: float,
    assets: float,
    warnings: list,
    legal: list,
) -> EitcResult:
    """수급 불가 결과 생성"""
    warnings.insert(0, f"수급 불가 — {reason}")
    warnings.append(
        "근로장려금 수급 요건을 충족하지 못합니다. "
        "상세 기준은 국세청 홈택스(www.hometax.go.kr)에서 확인하세요."
    )
    return EitcResult(
        household_type=household,
        annual_income=income,
        total_assets=assets,
        is_eligible=False,
        ineligible_reason=reason,
        breakdown={
            "수급 자격": "미충족",
            "사유": reason,
        },
        warnings=warnings,
        legal_basis=legal,
    )
