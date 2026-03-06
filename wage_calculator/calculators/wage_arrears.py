"""
임금체불 지연이자 계산기

법적 근거:
- 근로기준법 제37조: 퇴직 후 14일 초과 미지급 → 연 20% 지연이자
- 상법 제54조: 재직 중 미지급 → 연 6% 지연이자
- 근로기준법 제49조: 임금채권 소멸시효 3년

계산식:
  지연이자 = 미지급 원금 × 이자율 × (지연일수 / 365)
  총 청구액 = 원금 + 지연이자
"""

from dataclasses import dataclass

from ..base import BaseCalculatorResult
from typing import Optional
from datetime import date, datetime


@dataclass
class WageArrearsResult(BaseCalculatorResult):
    # 원금 및 이자
    arrear_amount: float = 0.0         # 미지급 임금 원금 (원)
    interest_rate: float = 0.0         # 적용 이자율 (연, 소수)
    delay_days: int = 0                # 지연일수
    interest_amount: float = 0.0       # 지연이자 (원)
    total_claim: float = 0.0           # 총 청구액 = 원금 + 이자 (원)

    # 소멸시효
    due_date: str = ""                 # 원래 지급예정일
    calc_date: str = ""                # 이자 계산 기준일
    statute_of_limitations_date: str = ""  # 소멸시효 만료일 (지급예정일로부터 3년)
    is_expired: bool = False           # 소멸시효 만료 여부

    # 적용 근거
    is_post_retirement: bool = False   # True → 연 20% / False → 연 6%


def calc_wage_arrears(
    arrear_amount: float,
    arrear_due_date: str,
    is_post_retirement_arrear: bool = False,
    arrear_calc_date: Optional[str] = None,
) -> WageArrearsResult:
    """
    임금체불 지연이자 계산

    Args:
        arrear_amount: 미지급 임금 원금 (원)
        arrear_due_date: 원래 지급예정일 "YYYY-MM-DD"
        is_post_retirement_arrear: True이면 퇴직 후 14일 초과 → 연 20% 적용
                                   False이면 재직 중 미지급 → 연 6% 적용
        arrear_calc_date: 이자 계산 기준일 (None이면 오늘)

    Returns:
        WageArrearsResult
    """
    warnings = []
    formulas = []
    legal = []

    # ── 날짜 파싱 ────────────────────────────────────────────────────────
    try:
        due = datetime.strptime(arrear_due_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        due = date.today()
        warnings.append(f"지급예정일 파싱 실패 — 오늘({due}) 기준 적용")

    if arrear_calc_date:
        try:
            calc = datetime.strptime(arrear_calc_date, "%Y-%m-%d").date()
        except ValueError:
            calc = date.today()
            warnings.append(f"계산기준일 파싱 실패 — 오늘({calc}) 기준 적용")
    else:
        calc = date.today()

    # ── 소멸시효 (3년) ────────────────────────────────────────────────────
    from datetime import timedelta
    sol_date = date(due.year + 3, due.month, due.day)
    try:
        sol_date = due.replace(year=due.year + 3)
    except ValueError:
        # 2월 29일 등 윤년 처리
        sol_date = due + timedelta(days=365 * 3)

    is_expired = calc > sol_date

    if is_expired:
        warnings.append(
            f"⚠️ 소멸시효 만료: 지급예정일({due})로부터 3년이 경과하였습니다 ({sol_date}). "
            "법원에 시효중단 조치 없이는 임금채권 행사 불가할 수 있습니다."
        )

    # ── 퇴직 후 14일 초과 체크 안내 ─────────────────────────────────────
    if is_post_retirement_arrear:
        # 퇴직 후 14일 기준: 퇴직일로부터 14일 초과 시 연 20%
        # 여기서는 is_post_retirement_arrear=True이면 이미 14일 초과로 가정
        interest_rate = 0.20
        rate_basis = "연 20% (근로기준법 제37조 — 퇴직 후 14일 초과 미지급)"
        legal.append("근로기준법 제37조 (금품 청산)")
    else:
        interest_rate = 0.06
        rate_basis = "연 6% (상법 제54조 — 재직 중 미지급 또는 14일 이내)"
        legal.append("상법 제54조 (상사법정이율)")

    legal.append("근로기준법 제49조 (임금채권 소멸시효 3년)")

    # ── 지연일수 계산 ─────────────────────────────────────────────────────
    delay_days = max(0, (calc - due).days)

    # ── 지연이자 계산 ─────────────────────────────────────────────────────
    interest_amount = arrear_amount * interest_rate * (delay_days / 365)
    total_claim = arrear_amount + interest_amount

    formulas.append(
        f"지연이자 = {arrear_amount:,.0f}원 × {interest_rate*100:.0f}% × ({delay_days}일 ÷ 365)"
        f" = {interest_amount:,.0f}원"
    )
    formulas.append(f"총 청구액 = {arrear_amount:,.0f}원 + {interest_amount:,.0f}원 = {total_claim:,.0f}원")

    # ── 추가 안내 ─────────────────────────────────────────────────────────
    if not is_post_retirement_arrear:
        warnings.append(
            "재직 중 임금체불: 연 6% (상법 제54조) 적용. "
            "퇴직 후 14일 초과 시 자동으로 연 20%로 전환됩니다."
        )
    else:
        warnings.append(
            "퇴직일로부터 14일 이내 미지급은 연 6% 적용 대상입니다. "
            "14일 초과분부터 연 20%가 적용됩니다."
        )

    warnings.append(
        f"임금채권 소멸시효: 지급예정일({due})로부터 3년 = {sol_date}"
    )
    warnings.append(
        "지연이자 청구 방법: 고용노동부 임금체불 진정(1350) 또는 법원 민사소송"
    )

    breakdown = {
        "미지급 원금": f"{arrear_amount:,.0f}원",
        "지급예정일": str(due),
        "계산기준일": str(calc),
        "지연일수": f"{delay_days}일",
        "적용 이자율": f"{interest_rate*100:.0f}%/년 ({rate_basis})",
        "지연이자": f"{interest_amount:,.0f}원",
        "총 청구액": f"{total_claim:,.0f}원",
        "소멸시효 만료일": f"{sol_date} ({'만료됨' if is_expired else '미만료'})",
    }

    return WageArrearsResult(
        arrear_amount=round(arrear_amount, 0),
        interest_rate=interest_rate,
        delay_days=delay_days,
        interest_amount=round(interest_amount, 0),
        total_claim=round(total_claim, 0),
        due_date=str(due),
        calc_date=str(calc),
        statute_of_limitations_date=str(sol_date),
        is_expired=is_expired,
        is_post_retirement=is_post_retirement_arrear,
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )
