"""
nodong.kr 임금계산기 패키지

임금 관련 질문을 포괄하는 통합 계산 엔진입니다.
지원 계산 유형: 통상임금, 연장/야간/휴일수당, 최저임금 검증,
              주휴수당, 연차수당, 해고예고수당, 포괄임금제 역산

사용 예:
    from wage_calculator.facade import WageCalculator
    from wage_calculator.models import WageInput, WageType, WorkType, BusinessSize, WorkSchedule

    inp = WageInput(
        wage_type=WageType.HOURLY,
        hourly_wage=12000,
        business_size=BusinessSize.OVER_5,
        schedule=WorkSchedule(
            weekly_work_days=5,
            weekly_overtime_hours=10,
            weekly_night_hours=2,
        ),
    )
    calc = WageCalculator()
    result = calc.calculate(inp, targets=["overtime", "minimum_wage", "weekly_holiday"])
    print(result.summary)
"""

from .facade import WageCalculator
from .base import BaseCalculatorResult
from .calculators.ordinary_wage import OrdinaryWageResult
from .models import (
    WageInput, WageType, WorkType, BusinessSize, WorkSchedule, AllowanceCondition,
    WorkerType, WorkerEntry, BusinessSizeInput,
)
from .result import WageResult, format_result, format_result_json
from .legal_hints import LegalHint, generate_legal_hints, format_hints
from .calculators.business_size import BusinessSizeResult

__all__ = [
    "WageCalculator",
    "BaseCalculatorResult",
    "OrdinaryWageResult",
    "WageInput",
    "WageType",
    "WorkType",
    "BusinessSize",
    "WorkSchedule",
    "AllowanceCondition",
    "WorkerType",
    "WorkerEntry",
    "BusinessSizeInput",
    "BusinessSizeResult",
    "WageResult",
    "format_result",
    "format_result_json",
    "LegalHint",
    "generate_legal_hints",
    "format_hints",
]
