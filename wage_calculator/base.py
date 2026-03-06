"""
계산기 Result 공통 기반 클래스
"""

from dataclasses import dataclass, field


@dataclass
class BaseCalculatorResult:
    """모든 계산기 Result의 공통 기반 클래스"""
    breakdown: dict = field(default_factory=dict)
    formulas: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    legal_basis: list = field(default_factory=list)
