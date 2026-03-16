"""
계산기 공통 유틸리티

DateRange:           날짜 범위·근속 계산 (8개 모듈 통합)
AllowanceClassifier: 수당 이름 기반 최저임금 산입유형 분류 (3곳 통합)
MultiplierContext:   5인 미만 사업장 가산율 (5곳 통합)
_normalize_allowances: dict → FixedAllowance 변환 (하위 호환)
"""

from __future__ import annotations

from datetime import date

from ..models import WageInput, BusinessSize, FixedAllowance
from ..utils import parse_date
from ..constants import OVERTIME_RATE, NIGHT_PREMIUM_RATE, HOLIDAY_RATE, HOLIDAY_OT_RATE


# ── DateRange ──────────────────────────────────────────────────────────────────

class DateRange:
    """날짜 범위 및 근속 계산

    기존 중복: severance.py, annual_leave.py, dismissal.py, unemployment.py,
              weekly_holiday.py, average_wage.py, shutdown_allowance.py, industrial_accident.py
    """

    def __init__(self, start_str: str | None, end_str: str | None = None):
        self.start: date | None = parse_date(start_str)
        self.end: date = parse_date(end_str) or date.today()

    @property
    def is_valid(self) -> bool:
        """입사일이 존재하고 start <= end"""
        return self.start is not None and self.start <= self.end

    @property
    def days(self) -> int:
        """근속 일수 (start가 None이면 0)"""
        if self.start is None:
            return 0
        return (self.end - self.start).days

    @property
    def years(self) -> float:
        """근속 연수 (365일 기준)"""
        return self.days / 365 if self.days > 0 else 0.0

    @property
    def months_approx(self) -> int:
        """근속 개월 수 (30.44일 기준, unemployment.py 호환)"""
        return max(0, int(self.days / 30.44))


# ── AllowanceClassifier ───────────────────────────────────────────────────────

class AllowanceClassifier:
    """수당 이름 기반 자동 분류

    기존 중복:
    - minimum_wage.py:37-42  (_EXCLUDED_PATTERNS, _BONUS_PATTERNS, _WELFARE_PATTERNS)
    - minimum_wage.py:259-274 (_min_wage_type)
    - legal_hints.py (인라인 키워드 매칭)
    """

    # 최저임금 비산입 (연장/야간/휴일 등)
    EXCLUDED_KEYWORDS: list[str] = ["연장", "야간", "휴일", "특근"]

    # 정기상여금 (산입범위 적용)
    BONUS_KEYWORDS: list[str] = ["상여금", "상여", "보너스", "격려금", "인센티브"]

    # 복리후생비 (산입범위 적용)
    WELFARE_KEYWORDS: list[str] = [
        "식대", "식비", "급식", "교통비", "교통", "차량", "통근",
        "주거", "숙박", "가족수당", "복리",
    ]

    @classmethod
    def classify_min_wage_type(cls, name: str, explicit_type: str = "") -> str:
        """최저임금 산입유형 결정

        Returns: "standard" | "regular_bonus" | "welfare" | "excluded"
        """
        if explicit_type in ("regular_bonus", "welfare", "excluded", "standard"):
            return explicit_type
        for kw in cls.EXCLUDED_KEYWORDS:
            if kw in name:
                return "excluded"
        for kw in cls.BONUS_KEYWORDS:
            if kw in name:
                return "regular_bonus"
        for kw in cls.WELFARE_KEYWORDS:
            if kw in name:
                return "welfare"
        return "standard"

    @classmethod
    def is_overtime_related(cls, name: str) -> bool:
        """연장/야간/휴일 관련 수당인지 판별"""
        return any(kw in name for kw in cls.EXCLUDED_KEYWORDS)


# ── MultiplierContext ──────────────────────────────────────────────────────────

class MultiplierContext:
    """5인 미만 사업장 가산율 관리

    기존 중복: overtime.py:54-60, comprehensive.py, flexible_work.py,
              public_holiday.py, dismissal.py
    """

    def __init__(self, inp: WageInput):
        self.is_small: bool = inp.business_size == BusinessSize.UNDER_5

    @property
    def overtime(self) -> float:
        """연장수당 가산율 (5인 이상: 0.5, 미만: 0.0)"""
        return 0.0 if self.is_small else OVERTIME_RATE

    @property
    def night(self) -> float:
        """야간수당 가산율"""
        return 0.0 if self.is_small else NIGHT_PREMIUM_RATE

    @property
    def holiday(self) -> float:
        """휴일수당 가산율 (8h 이내)"""
        return 0.0 if self.is_small else HOLIDAY_RATE

    @property
    def holiday_ot(self) -> float:
        """휴일수당 가산율 (8h 초과)"""
        return 0.0 if self.is_small else HOLIDAY_OT_RATE

    def small_business_warning(self) -> str | None:
        """5인 미만 경고 메시지 (해당 시에만 반환)"""
        if self.is_small:
            return "5인 미만 사업장: 연장·야간·휴일 가산수당 미적용 (근로기준법 제11조)"
        return None


# ── Allowance Normalization ────────────────────────────────────────────────────

def normalize_allowances(raw: list) -> list[FixedAllowance]:
    """list[dict | FixedAllowance] → list[FixedAllowance] (하위 호환)"""
    result = []
    for item in raw:
        if isinstance(item, FixedAllowance):
            result.append(item)
        elif isinstance(item, dict):
            result.append(FixedAllowance.from_dict(item))
    return result
