"""
중도입사 일할계산 (근로기준법 제43조)

중도입사 또는 중도퇴직 시 첫/마지막 달 임금:
1. 역일(曆日) 기준: 월급 × 근무일수 / 해당월 총일수  ← 실무 일반
2. 소정근로일 기준: 취업규칙·근로계약에 명시된 경우

기준일 계산 예:
  - 3월 15일 입사, 월급 2,500,000원
  - 3월은 31일 → 근무일 = 31 - 15 + 1 = 17일
  - 일할임금 = 2,500,000 × 17 / 31 = 1,370,968원
"""

import calendar
from dataclasses import dataclass

from ..base import BaseCalculatorResult
from ..utils import parse_date
from datetime import date

from ..models import WageInput
from .ordinary_wage import OrdinaryWageResult


@dataclass
class ProratedResult(BaseCalculatorResult):
    prorated_wage: float = 0.0   # 일할계산 임금 (원)
    method: str = ""             # 계산 방법 ("역일 기준")
    worked_days: int = 0         # 근무 일수 (역일)
    total_days: int = 0          # 해당월 총 일수


def calc_prorated(inp: WageInput, ow: OrdinaryWageResult) -> ProratedResult:
    """중도입사 일할계산 (역일 기준)"""
    warnings = []
    formulas = []
    legal = ["근로기준법 제43조 (임금의 지급)"]

    # 기준 월급: 제공된 monthly_wage 또는 통상임금
    monthly_wage = inp.monthly_wage or ow.monthly_ordinary_wage

    # 입사일 파싱
    join_date = parse_date(inp.join_date)
    if join_date is None:
        return ProratedResult(
            prorated_wage=0,
            method="",
            worked_days=0,
            total_days=0,
            breakdown={"오류": "입사일(join_date)을 입력해주세요"},
            formulas=[],
            warnings=["입사일 미입력"],
            legal_basis=legal,
        )

    # 해당월 총 일수
    total_days = calendar.monthrange(join_date.year, join_date.month)[1]

    # 근무 일수: 직접 지정 우선, 없으면 입사일부터 월말까지 역일 계산
    if inp.first_month_worked_days is not None:
        worked_days = inp.first_month_worked_days
    else:
        worked_days = total_days - join_date.day + 1

    # 역일 기준 일할계산
    prorated = monthly_wage * worked_days / total_days

    formulas.append(
        f"일할계산(역일): {monthly_wage:,.0f}원 × {worked_days}일 / {total_days}일 = {prorated:,.0f}원"
    )
    warnings.append(
        "일할계산 방법(역일/소정근로일)은 취업규칙·근로계약에 따라 다를 수 있습니다"
    )

    breakdown = {
        "입사일": join_date.isoformat(),
        "해당월": f"{join_date.year}년 {join_date.month}월",
        "해당월 총일수": f"{total_days}일",
        "근무 일수(역일)": f"{worked_days}일",
        "월 기준임금": f"{monthly_wage:,.0f}원",
        "일할계산 임금": f"{prorated:,.0f}원",
        "계산식": f"{monthly_wage:,.0f} × {worked_days}/{total_days}",
    }

    return ProratedResult(
        prorated_wage=round(prorated, 0),
        method="역일 기준",
        worked_days=worked_days,
        total_days=total_days,
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )


