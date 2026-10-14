"""
계산기 공통 유틸리티

DateRange:           날짜 범위·근속 계산 (8개 모듈 통합)
AllowanceClassifier: 수당 이름 기반 최저임금 산입유형 분류 (3곳 통합)
MultiplierContext:   5인 미만 사업장 가산율 (5곳 통합)
_normalize_allowances: dict → FixedAllowance 변환 (하위 호환)
"""

from __future__ import annotations

import re
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

    # 최저임금 비산입 — 연장·휴일근로 임금과 연장·야간·휴일 가산임금(최저임금법 시행규칙 제2조①1호). 시간외·잔업·포괄·초과·
    # OT·심야·주말근무수당도 같은 임금의 다른 이름이다(의도분석 고정수당 이름 — audit-50 Act-3 리뷰 H3b·Act-4 리뷰 M2).
    # 대조는 공백을 없애고 대문자로 바꾼 이름(`_keyword_name`)에 한다
    EXCLUDED_KEYWORDS: list[str] = ["연장", "야간", "심야", "휴일", "특근", "시간외", "잔업", "포괄", "초과근무", "초과근로",
                                    "초과수당", "초과시간", "OT", "오티", "주말근무", "주말근로", "주말출근"]
    # 최저임금 비산입이지만 연장근로와 무관 — 연차 유급휴가의 미사용수당(시행규칙 제2조①2호, 공식 원문 대조 2026-10-12)
    NON_INCLUDED_KEYWORDS: list[str] = ["연차"]
    # 같은 글자가 다른 뜻인 이름 — '계약연장·정년연장·기간연장수당'·'근속연차수당'·'연차별'(근속 연수)은 연장근로·연차휴가와
    # 무관하고, 영문 낱말 속 'OT'('IoT'·'PILOT')는 시간외근로가 아니다(Act-4 리뷰 M2·재검토). 대조 전에 지운다
    _NOT_PREMIUM_RE = re.compile(r"계약연장|정년연장|기간연장|근속연차|연차별|[A-Z]+OT[A-Z]*|[A-Z]*OT[A-Z]+")
    # 교대제 고정수당('야간교대수당'·'야간조수당')은 통상임금으로 다퉈지는 소정근로의 대가일 수 있어 통상임금에서는 이름만으로
    # 빼지 않는다. 최저임금 산입은 그대로 비산입(야간)이다 — 어느 쪽도 없는 '충족'을 만들지 않는 방향이다
    _SHIFT_RE = re.compile(r"야간교대|야간조")

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
        key = cls._keyword_name(name)
        for kw in cls.EXCLUDED_KEYWORDS + cls.NON_INCLUDED_KEYWORDS:
            if kw in key:
                return "excluded"
        for kw in cls.BONUS_KEYWORDS:
            if kw in name:
                return "regular_bonus"
        for kw in cls.WELFARE_KEYWORDS:
            if kw in name:
                return "welfare"
        return "standard"

    @classmethod
    def _keyword_name(cls, name: str) -> str:
        """키워드 대조용 이름 — 공백을 없애고 대문자로 바꾼 뒤 같은 글자가 다른 뜻인 부분('계약연장' 등)을 지운다."""
        return cls._NOT_PREMIUM_RE.sub("", re.sub(r"\s+", "", name or "").upper())

    @classmethod
    def is_not_ordinary_by_name(cls, name: str) -> bool:
        """이름만으로 통상임금이 아닌 수당인가(연장·야간·휴일근로·연차수당 등).

        연장·야간·휴일근로 가산임금('통상임금의 100분의 50', 근로기준법 제56조)과 연차휴가 임금('통상임금 또는 평균임금',
        제60조 제5항)은 소정근로의 대가(시행령 제6조 제1항)가 아니고, 넣으면 통상임금이 자기 자신으로 커진다. '휴일'은 근로일
        때만이다 — '유급휴일수당'은 기본급과 함께 월 통상임금을 이루는 주휴분일 수 있다(audit-50 Act-4).
        """
        key = cls._SHIFT_RE.sub("", cls._keyword_name(name))
        if any(kw in key for kw in cls.NON_INCLUDED_KEYWORDS):
            return True
        if any(kw in key for kw in cls.EXCLUDED_KEYWORDS if kw != "휴일"):
            return True
        return bool(re.search(r"휴일(?:근로|근무|출근|특근)", key))

    @classmethod
    def is_overtime_related(cls, name: str) -> bool:
        """연장/야간/휴일 관련 수당인지 판별"""
        key = cls._keyword_name(name)
        return any(kw in key for kw in cls.EXCLUDED_KEYWORDS)

    @classmethod
    def excluded_kind(cls, name: str) -> str:
        """최저임금 비산입 행의 표기 — 연차수당·주휴일 외 유급휴일 임금은 초과수당이 아니다(시행규칙 제2조 제1항 2·3호)."""
        key = cls._keyword_name(name)
        if any(kw in key for kw in cls.NON_INCLUDED_KEYWORDS):
            return "연차수당"
        if "휴일" in key and not re.search(r"휴일(?:근로|근무|출근|특근)", key) and not any(
                kw in key for kw in cls.EXCLUDED_KEYWORDS if kw != "휴일"):
            return "주휴일 외 유급휴일 임금 — 주휴수당이면 산입"
        return "초과수당" if cls.is_overtime_related(name) else "명시 지정"


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
