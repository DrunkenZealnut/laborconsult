"""wage_calculator 호출 래퍼"""

from wage_calculator.facade import WageCalculator
from wage_calculator.result import WageResult, format_result_json
from wage_calculator.models import WageInput


_calc = WageCalculator()


def run_calculation(wage_input: WageInput, targets: list[str]) -> WageResult:
    """wage_calculator로 계산 실행"""
    if not targets:
        targets = None  # auto-detect
    return _calc.calculate(wage_input, targets=targets)


def result_to_dict(result: WageResult) -> dict:
    """WageResult를 JSON 직렬화 가능한 dict로 변환"""
    return format_result_json(result)
