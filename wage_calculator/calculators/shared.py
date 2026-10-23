"""
계산기 공통 유틸리티

DateRange:           날짜 범위·근속 계산 (8개 모듈 통합)
AllowanceClassifier: 수당 이름 기반 최저임금 산입유형 분류 (3곳 통합)
MultiplierContext:   5인 미만 사업장 가산율 (5곳 통합)
weekly_holiday_hours: 주휴 유급시간 산식 (4곳 + 상담 경로 통합)
_normalize_allowances: dict → FixedAllowance 변환 (하위 호환)
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from datetime import date

from ..models import WageInput, BusinessSize, FixedAllowance, HourSplit, WageType, WorkType
from ..utils import WEEKS_PER_MONTH, fmt_hours, parse_date
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


# ── 주휴 유급시간 ──────────────────────────────────────────────────────────────
# 계산기 전체의 단일 출처 — 통상임금 기준시간(ordinary_wage)·주휴수당(weekly_holiday)·소정근로시간(working_hours)·
# 포괄임금 역산(comprehensive)·시급 없는 상담 경로(pipeline._wageless_weekly_holiday)가 함께 쓴다. 넷이 산식을 따로
# 갖고 있어 주 6일 × 4.1667h(주 25h) 한 카드에 기준시간은 주휴 5h(÷5), 주휴수당은 4.1667h(1일 시간)가 함께 나왔고,
# 포괄임금 역산은 주 5일 미만에도 1일 시간을 그대로 썼다(외부 점검 40번 후속, 2026-10-14).

def holiday_divisor(weekly_work_days: float) -> float:
    """주휴시간을 구할 때 1주 소정근로시간을 나누는 일수 — 1주 소정근로일 수, 5일 미만이면 5일."""
    return max(float(weekly_work_days), 5.0)


def weekly_holiday_hours(weekly_work_days: float, daily_work_hours: float) -> tuple[float, str]:
    """주휴 유급시간과 산식 설명. 1주 소정근로시간 15시간 미만(주휴 미발생) 판정은 호출부가 한다.

    대법원 2025. 8. 14. 선고 2022다291153 판결: 주휴수당의 지급기준이 되는 시간 수는 특별한 사정이 없는 한 1일 평균
    소정근로시간 수(1주간 소정근로시간 수를 1주간 소정근로일 수로 나눈 값)가 원칙이고, 근로자와 사용자가 소정근로시간에
    관하여만 정했다면 1주간 소정근로일이 5일에 미달하는 근로자는 소정근로일 수를 5일로 보아 1주간 소정근로시간 수를
    5일로 나눈다. 8시간 한도는 1일 소정근로시간이 법정근로시간(근로기준법 제50조 제2항) 안의 시간이라서다.
    """
    weekly = weekly_work_days * daily_work_hours
    if weekly_work_days >= 5:
        hours = min(daily_work_hours, 8.0)
        return hours, (f"주 소정근로일 {fmt_hours(weekly_work_days)}일 ≥ 5일 → 주휴: "
                       f"min({fmt_hours(daily_work_hours)}h, 8h) = {fmt_hours(hours)}h")
    hours = min(weekly / holiday_divisor(weekly_work_days), 8.0)
    # '÷ 40h × 8h' 표기는 답변 규칙(WAGE_CALC_RULES)이 쓰는 같은 값의 다른 표기다 — 카드와 답변의 산식 표기를 맞춘다
    return hours, (f"주 소정근로일 {fmt_hours(weekly_work_days)}일 < 5일 → 주휴: min({fmt_hours(weekly)}h ÷ 5, 8h) = "
                   f"{fmt_hours(hours)}h (= {fmt_hours(weekly)}h ÷ 40h × 8h — 1주 소정근로일을 5일로 봄)")


# ── 소정·연장 분리 ─────────────────────────────────────────────────────────────
# 소정근로시간은 1일 8시간·1주 40시간(근로기준법 제50조) 범위에서 정한 시간이다(제2조 제1항 제8호). 예전 카드는 1일 시간 ×
# 근무일수를 그대로 '주 소정근로'라 불러 연장 가산을 빠뜨리고(주 5일 × 10h: 월 260,714원) 주 5일 미만 주휴를 부풀렸다
# (주 4일 × 10h: 8h, 맞는 값 6.4h — calc-card-followups R1·R2). 상시 4명 이하도 같다(근로기준정책과-2668·-5106) — 가산만
# 없다(MultiplierContext). 계산 전에 일정을 한 번 정규화하고 모든 계산기가 그 값을 읽는다(D9) — 계산기 안에서 1일 시간 ×
# 근무일수를 다시 '소정'이라 부르지 말 것. 주휴 함수(weekly_holiday_hours)의 입력도 이렇게 나눈 소정근로시간이다.
LEGAL_DAILY_HOURS = 8.0
LEGAL_WEEKLY_HOURS = 40.0
_SHIFT_TABLE_TYPES = frozenset({WorkType.SHIFT_4_2, WorkType.SHIFT_3_2, WorkType.SHIFT_3, WorkType.SHIFT_2})
_EPS = 1e-9


def split_hours(raw_daily, raw_days, *, daily_cap: float = LEGAL_DAILY_HOURS,
                weekly_cap: float = LEGAL_WEEKLY_HOURS) -> HourSplit:
    """1일 근로시간·주 근무일수를 소정근로와 연장근로로 나눈다(D1).

    1일 소정은 1일 한도까지다. 그 합이 1주 한도를 넘으면 근무일 순서대로 쌓아 1주 한도에 닿은 뒤의 시간이 연장이고,
    소정근로일은 소정 시간이 하루라도 있는 날 수다 — 주 6일 × 8h는 소정 8h × 5일 + 연장 8h(주휴 8h), 주 6일 × 7h는
    소정 40h를 6일에(1일 평균 6.67h) + 연장 2h. 고르게 나누면(40 ÷ 6) 6일째 8시간이 전부 연장인데도 하루 6.67시간
    소정으로 읽힌다. 근무일수가 평균(5.8일 등)이라 그 소정근로일이 근무일수를 넘으면 근무일수로 둔다.
    """
    try:
        daily_in, days_in = float(raw_daily), float(raw_days)
    except (TypeError, ValueError):
        return HourSplit(0.0, 0.0, 0.0, 0.0, mode="skipped", reason="unknown")
    if daily_in <= 0 or days_in <= 0:
        return HourSplit(daily_in, days_in, daily_in, days_in, mode="skipped", reason="unknown")
    capped = min(daily_in, daily_cap)
    if capped * days_in <= weekly_cap + _EPS:
        daily, days = capped, days_in
    else:
        full = math.floor(weekly_cap / capped + _EPS)            # 소정 시간을 꽉 채운 날
        rest = weekly_cap - full * capped
        days = min(full + (1 if rest > _EPS else 0), days_in)
        daily = weekly_cap / days
    excess = daily_in * days_in - daily * days
    if excess <= _EPS:
        return HourSplit(daily_in, days_in, daily_in, days_in)
    return HourSplit(daily_in, days_in, daily, days, excess=excess, mode="applied", overtime=excess)


def reconcile_overtime(stated: float, derived: float) -> float:
    """질문에 따로 적힌 주 연장시간과 1일·1주 한도 초과분을 하나로(D8).

    같은 2시간을 두 필드에 함께 적는 추출이 흔해 더하면 이중 계산이다. 값이 다르면 큰 값을 쓰고, 별개일 가능성은
    연장수당 계산식에 안내한다(calc_overtime)."""
    if stated <= _EPS:
        return derived
    if derived <= _EPS or abs(stated - derived) <= 0.5:
        return stated
    return max(stated, derived)


def _split_skip_reason(inp: WageInput) -> str:
    s = inp.schedule
    if inp.is_platform_worker:
        return "platform"            # 근로시간 규정이 적용되지 않는다
    if s.monthly_scheduled_hours is not None or s.shift_monthly_hours is not None:
        return "direct_hours"        # 기준시간을 직접 정한 입력
    if inp.work_type in _SHIFT_TABLE_TYPES:
        return "shift_table"         # 교대제 표 기준시간(SHIFT_MONTHLY_HOURS)의 성격은 별도 점검 대상
    if getattr(inp, "flexible_work_unit", ""):
        return "flexible"            # 탄력적 근로시간제 계산 입력
    return ""


def apply_hour_split(inp: WageInput) -> HourSplit:
    """inp.schedule을 소정근로 기준으로 정규화하고 결과를 inp.hour_split에 둔다. 이미 나눴으면 그 결과를 돌려준다.

    파이프라인이 먼저(구성 판정 전) 부르고 facade가 다시 부른다 — 두 번째는 아무 일도 하지 않는다."""
    if inp.hour_split is not None:
        return inp.hour_split
    s = inp.schedule
    reason = _split_skip_reason(inp)
    if reason:
        split = HourSplit(s.daily_work_hours, s.weekly_work_days, s.daily_work_hours, s.weekly_work_days,
                          mode="skipped", reason=reason)
    else:
        split = split_hours(s.daily_work_hours, s.weekly_work_days)
        if split.mode == "applied":
            stated = float(s.weekly_overtime_hours or 0.0)
            split = replace(split, stated_overtime=stated, overtime=reconcile_overtime(stated, split.excess))
            s.daily_work_hours, s.weekly_work_days = split.daily, split.days
            s.weekly_overtime_hours = split.overtime
    inp.hour_split = split
    return split


def split_note(split: HourSplit | None) -> str:
    """나눈 결과 설명 — [기준시간]·소정근로시간·시급 없는 주휴 블록이 같은 문장을 쓴다."""
    if split is None or split.mode != "applied":
        return ""
    raw_weekly = split.raw_daily * split.raw_days
    parts = [f"주 근로 {fmt_hours(split.raw_daily)}h×{fmt_hours(split.raw_days)}일 = {fmt_hours(raw_weekly)}h → 소정근로 "
             f"{fmt_hours(split.daily)}h×{fmt_hours(split.days)}일 = {fmt_hours(split.weekly)}h + 연장 {fmt_hours(split.excess)}h"
             "(1일 8시간·주 40시간 초과분 — 근로기준법 제50조, 대법원 2022다291153)"]
    if split.days < split.raw_days - _EPS:
        parts.append(f"주 40시간을 넘는 {fmt_hours(split.raw_days - split.days)}일분은 연장근로일로 보아 소정근로일 "
                     f"{fmt_hours(split.days)}일")
    elif split.daily < min(split.raw_daily, LEGAL_DAILY_HOURS) - _EPS:
        parts.append(f"주 40시간 한도라 1일 평균 소정근로 {fmt_hours(split.daily)}h")
    if split.raw_daily > 12 + _EPS:
        parts.append(f"휴게·수면시간은 근로시간에서 뺍니다(근로기준법 제54조) — {fmt_hours(split.raw_daily)}시간에 휴게가 "
                     "들어 있으면 소정·연장 시간이 달라집니다")
    return ", ".join(parts)


# ── 연장·야간·휴일 근로 임금 ─────────────────────────────────────────────────────
# 연장수당 계산기(calc_overtime)와 기준 월액(monthly_wage_total)이 같은 산식을 쓴다. 예전에는 카드의 '월 총 예상
# 수령액'(통상임금 + 연장수당 3,285,000원)과 퇴직금 평균임금·4대보험 보수(통상임금만 2,502,857원 기준)가 한 카드에서 갈렸다
# (calc-card-followups R15).

@dataclass(frozen=True)
class PremiumWeekly:
    overtime: float = 0.0     # 연장근로 임금(가산 포함)
    night: float = 0.0        # 야간 가산분
    holiday: float = 0.0      # 휴일근로 임금(가산 포함)

    @property
    def total(self) -> float:
        return self.overtime + self.night + self.holiday


def premium_weekly(inp: WageInput, hourly: float) -> PremiumWeekly:
    """주당 연장·야간·휴일 근로 임금(5인 미만은 가산 없이 — MultiplierContext)."""
    s = inp.schedule
    mc = MultiplierContext(inp)
    return PremiumWeekly(
        overtime=hourly * s.weekly_overtime_hours * (1 + mc.overtime),
        night=hourly * s.weekly_night_hours * mc.night,
        holiday=(hourly * s.weekly_holiday_hours * (1 + mc.holiday)
                 + hourly * s.weekly_holiday_overtime_hours * (1 + mc.holiday + mc.holiday_ot)),
    )


def _premium_included(inp: WageInput) -> bool:
    """그 금액에 연장·야간·휴일 근로 임금이 이미 들어 있는가 — 포괄임금제 총액, 또는 파이프라인이 질문의 구성 진술로 정한
    총액(wage_composition_known — 정확 경로는 monthly_total_pay가 따로 있어 여기 오지 않는다)."""
    return inp.wage_type == WageType.COMPREHENSIVE or inp.wage_composition_known


def _adds_premium(inp: WageInput) -> bool:
    """월 임금총액 추정에 연장·야간·휴일 근로 임금을 더하는가 — 이미 들어 있는 총액이면 더하지 않는다. 노무제공자는 근로기준법의
    연장 가산(제56조)을 받는 근로자가 아니라 더하지 않는다(독립 리뷰 M3: 특고 보수월액에 연장분 월 937,500원을 더했다)."""
    return not (_premium_included(inp) or inp.is_platform_worker)


def has_premium_hours(inp: WageInput) -> bool:
    """연장·야간·휴일 근로시간이 하나라도 입력됐는가 — 포괄임금 역산의 근거이자 월 임금총액 추정이 더할 시간이 있는지의 판정."""
    s = inp.schedule
    return any((getattr(s, f, 0) or 0) > 0 for f in (
        "weekly_overtime_hours", "weekly_night_hours", "weekly_holiday_hours", "weekly_holiday_overtime_hours"))


def adds_premium_pay(inp: WageInput) -> bool:
    """기준 월액(monthly_wage_total)이 연장·야간·휴일 근로 임금을 더하는 입력인가 — 더하면 카드의 연장수당 섹션도
    계산해야 '월 총 예상 수령액'이 같은 금액을 쓴다(calc-card-consistency G2). 시간이 아니라 더할 금액으로 본다 — 상시 4명
    이하의 야간근로는 가산이 없어(MultiplierContext) 시간만 보면 0원 섹션과 '월 금액에 들어간다'는 안내가 붙었다(독립 리뷰 L1)."""
    return _adds_premium(inp) and premium_weekly(inp, 1.0).total > 0


def fixed_overtime_monthly(inp: WageInput) -> float:
    """고정수당 중 연장·야간·휴일 근로의 대가(고정연장수당·시간외수당·포괄수당 등)의 월액. 통상임금 계산기가 이름으로 통상임금에서
    빼는 수당과 같은 판정이다(명시적으로 통상임금에 넣은 것·성과조건·연차수당은 제외)."""
    total = 0.0
    for a in normalize_allowances(inp.fixed_allowances):
        if a.is_ordinary is True or a.condition == "성과조건":
            continue
        name = a.name or ""
        if (AllowanceClassifier.is_not_ordinary_by_name(name) and AllowanceClassifier.is_overtime_related(name)
                and not any(kw in AllowanceClassifier._keyword_name(name) for kw in AllowanceClassifier.NON_INCLUDED_KEYWORDS)):
            total += a.amount / 12 if a.annual else a.amount
    return total


def ordinary_wage_from_total(inp: WageInput) -> bool:
    """통상임금 계산 결과가 실제 통상임금이 아니라 수당이 섞인 총액에서 나왔는가 — 포괄임금제 총액(명세 없음), 또는 파이프라인이
    질문의 구성 진술로 정한 총액 경로(보류 카드 — 정확 경로는 기본급과 monthly_total_pay가 따로 있다). 이때는 통상임금과
    비교하는 하한(실업급여 기초일액 — 고용보험법 제45조 제2항)을 쓰지 않는다. 부풀린 값으로 하한이 걸린다."""
    if inp.wage_type == WageType.COMPREHENSIVE:
        return not inp.comprehensive_breakdown
    return inp.wage_composition_known and not inp.monthly_total_pay


def _included_outside_base(inp: WageInput) -> float:
    """포괄임금 명세(comprehensive_breakdown)가 있을 때 총액 중 기본급 밖의 몫(포함된 연장수당·상여 등). 통상임금 계산기는 명세의
    기본급만 통상임금으로 쓰므로 총액을 세려면 이 몫을 되돌린다. 명세가 없으면 통상임금 자리에 이미 총액이 들어 있다."""
    bd = inp.comprehensive_breakdown
    if inp.wage_type != WageType.COMPREHENSIVE or not bd or not inp.monthly_wage:
        return 0.0
    return max(0.0, inp.monthly_wage - float(bd.get("base", inp.monthly_wage)))


def _premium_over_fixed(inp: WageInput, ow) -> tuple[float, float]:
    """(계산한 연장·야간·휴일 근로 임금 월액, 고정연장수당 월액)."""
    return premium_weekly(inp, ow.hourly_ordinary_wage).total * WEEKS_PER_MONTH, fixed_overtime_monthly(inp)


def monthly_wage_total(inp: WageInput, ow, *, premium: bool = True) -> float:
    """월 임금총액(기준 월액)의 단일 출처 — 카드의 월 총액, 보험 세전(근로자·사업주), 평균임금 3개월 총액, 퇴직금 1년 평균,
    DC형 연간임금, 근로장려금 소득이 모두 이 값을 쓴다. 소비처에서 월 금액을 따로 만들지 말 것(monthly-base-unification —
    계산기마다 만들던 때 고정연장수당·직책수당·휴업수당 주휴분이 계산기마다 빠지거나 들어가 한 카드 안에서 금액이 갈렸다).

    기본은 통상임금 월액 + 통상임금에서 뺀 고정수당(연장·야간·휴일·연차수당 — not_ordinary_fixed_total)이고,
    ① 주어진 총액(monthly_total_pay)이 있으면 그 값만 쓴다
    ② 연장 등이 이미 든 총액(포괄임금·구성 진술)이면 명세의 기본급 밖 몫을 더한다 — 연장 등은 더하지 않는다
    ③ 그 밖에는 계산한 연장 등 임금 중 고정연장수당을 넘는 금액을 더한다. 고정연장수당은 계산한 연장 등과 같은 근로의 대가라
       큰 쪽 하나만 센다(독립 리뷰 M2) — 계산한 금액이 0이어도 고정연장수당은 매월 받는 임금이다(f1). 고정연장수당은 기본에 이미
       들어 있다(fixed_overtime_monthly ⊆ not_ordinary_fixed_total — 같은 이름 판정).
    premium=False는 ③을 하지 않는다. facade 월 총액은 연장수당 섹션을 계산한 카드에만 그 금액을 넣는다 — 파이프라인은 더할
    입력이면 연장수당 섹션을 함께 계산한다(adds_premium_pay, calc-card-consistency G2)."""
    if inp.monthly_total_pay:
        return inp.monthly_total_pay
    base = ow.monthly_ordinary_wage + ow.not_ordinary_fixed_total
    if _premium_included(inp):
        return base + _included_outside_base(inp)
    if not premium or not adds_premium_pay(inp):
        return base
    derived, fixed = _premium_over_fixed(inp, ow)
    return base + max(0.0, derived - fixed)


def annual_wage_total(inp: WageInput, ow, *, premium: bool = True) -> float:
    """연 임금총액 = 기준 월액 × 12(DC형 연간임금·근로장려금 소득). 연봉제는 통상임금 월액의 원 단위 반올림을 되돌린다 — 연봉
    2,200만 원이 1,833,333원 × 12 = 21,999,996원이 되어 근로장려금 단독가구 상한(2,200만 원 이상 수급 불가)을 4원 차이로 넘지
    못하고 1원이 나왔다(Check S3). 통상임금 월액은 round(연봉 ÷ 12 + 수당)이라 수당이 원 단위면 이 보정으로 연봉이 그대로 돌아온다."""
    total = monthly_wage_total(inp, ow, premium=premium) * 12
    if inp.wage_type == WageType.ANNUAL and inp.annual_wage and not inp.monthly_total_pay and not _premium_included(inp):
        total += inp.annual_wage - round(inp.annual_wage / 12) * 12
    return total


def monthly_wage_extras(inp: WageInput, ow, *, premium: bool = True) -> str:
    """통상임금 월액 위에 monthly_wage_total이 더한 항목의 표기(' + …' 꼴) — 더한 것이 없거나 총액 경로면 빈 문자열."""
    if inp.monthly_total_pay or _premium_included(inp):
        return ""
    text = ""
    if ow.not_ordinary_fixed_total > 0.5:
        text += f" + 통상임금에서 뺀 고정수당 {ow.not_ordinary_fixed_total:,.0f}원"
    if not premium or not adds_premium_pay(inp):
        return text
    derived, fixed = _premium_over_fixed(inp, ow)
    if derived - fixed <= 0.5:
        return text
    if fixed > 0.5:
        return (text + f" + 연장·야간·휴일 근로 임금 중 고정연장수당을 넘는 금액 월 {derived - fixed:,.0f}원(계산한 금액 "
                f"{derived:,.0f}원 − 고정연장수당 {fixed:,.0f}원, 매주 같은 시간으로 봄)")
    return text + f" + 연장·야간·휴일 근로 임금 월 {derived:,.0f}원(매주 같은 시간으로 봄)"


def monthly_wage_note(inp: WageInput, ow, *, premium: bool = True) -> str:
    """monthly_wage_total의 구성 표기 — 더한 항목만 적는다(더한 것이 없으면 '통상임금').

    연장 등이 든 총액 경로(포괄임금 명세 없음·구성 진술)도 '통상임금'이다 — 통상임금 계산 결과가 곧 그 금액이고, 그것이 월급
    '총액'인지는 파이프라인만 안다(`_label_held_total`이 `held_is_total`일 때만 '월급 총액'으로 바꾼다). 여기서 '월급 총액'이라 적으면
    금액이 질문의 기본급인 보류 카드에서 기본급을 총액이라 부른다(독립 리뷰 M1). 총액 밖 수당인지도 단정하지 않는다 — 진술 속 수당이
    총액 안에 있는지는 파이프라인이 정한다. 포괄임금 명세가 있으면 통상임금 자리에 기본급만 있어 '포괄임금 총액'이라 적는다."""
    if inp.monthly_total_pay:
        return "월 임금총액"
    if _premium_included(inp):
        if _included_outside_base(inp) <= 0.5:
            return "통상임금"
        outside = monthly_wage_total(inp, ow) - inp.monthly_wage   # 명세 경로의 통상임금 계산은 수당을 기본급 위에 더한다
        return "포괄임금 총액" + (f" + 고정수당 {outside:,.0f}원" if outside > 0.5 else "")
    return "통상임금" + monthly_wage_extras(inp, ow, premium=premium)


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
