"""Effective-date rule snapshots. No network calls or executable rules here."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import math


class RuleUnavailable(ValueError):
    """A managed calculation must stop instead of using an unapproved value."""


# An explicit adapter must consume every key here. Values are never eval'ed.
PARAMETERS = {
    "minimum_hourly_wage": {"label": "최저시급", "unit": "원/시간", "min": 1, "max": 1000000,
                            "topics": ["minimum_wage", "unemployment", "maternity_leave", "industrial_accident"]},
    "maternity.monthly_upper": {"label": "출산전후휴가급여 월 상한", "unit": "원", "min": 1,
                                "max": 100000000, "topics": ["maternity_leave"]},
    "maternity.platform_upper": {"label": "노무제공자 출산급여 월 상한", "unit": "원", "min": 1,
                                 "max": 100000000, "topics": ["maternity_leave"]},
}
for _key, _label in {
    "national_pension": "국민연금 근로자 부담률",
    "health_insurance": "건강보험 근로자 부담률",
    "long_term_care": "건강보험료 대비 장기요양 부담률",
    "employment_insurance": "고용보험 근로자 부담률",
    "pension_income_max": "국민연금 기준소득 상한",
    "pension_income_min": "국민연금 기준소득 하한",
    "health_premium_max": "건강보험료 상한",
    "health_premium_min": "건강보험료 하한",
}.items():
    _rate = _key in {"national_pension", "health_insurance", "long_term_care", "employment_insurance"}
    PARAMETERS["insurance." + _key] = {
        "label": _label, "unit": "비율(0~1)" if _rate else "원", "min": 0,
        "max": 1 if _rate else 1000000000, "topics": ["insurance", "employer_insurance"],
    }


def iso_date(value):
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError("날짜는 YYYY-MM-DD 형식이어야 합니다")
    result = date.fromisoformat(value)
    if result.isoformat() != value:
        raise ValueError("날짜는 YYYY-MM-DD 형식이어야 합니다")
    return result


def iso_date_or_block(value):
    try:
        return iso_date(value)
    except (TypeError, ValueError) as exc:
        raise RuleUnavailable("계산 기준일(reference_date, YYYY-MM-DD)을 확인해주세요") from exc


def kst_today():
    """KST 기준 오늘 'YYYY-MM-DD'. 서버 로컬시간(UTC)은 자정~09시에 전날을 가리킨다.

    abuse_guard.kst_today와 같은 계산이지만, 이 모듈은 app 패키지를 import하지 않는다
    (계산기 패키지 단독 사용 경로를 유지하기 위함).
    """
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    except Exception:
        return datetime.now(timezone(timedelta(hours=9))).date().isoformat()


def resolve_reference_date(reference_date, reference_year=None):
    """명시된 기준일이 우선. 없으면 오늘(KST)로 확정한다.

    '연도만으로 분기 기준을 추정하지 않는다'는 원칙은 **오늘이 속하지 않는 연도**를
    지정한 경우에만 필요하다 — 2025년의 어느 시점인지는 결정할 수 없기 때문이다.
    아무 날짜도 지정하지 않은 질문을 '현재 시점'으로 읽는 데에는 모호성이 없고,
    이를 보류로 처리하면 기준일을 말하지 않는 통상적인 상담 대부분이 수치 없이 끝난다.
    """
    if reference_date is not None:
        iso_date_or_block(reference_date)
        return reference_date
    today = kst_today()
    if reference_year is not None:
        try:
            year = int(reference_year)
        except (TypeError, ValueError) as exc:
            raise RuleUnavailable("계산 기준 연도를 확인해주세요") from exc
        # 법률 기준일은 KST가 권위값이다. UTC 서버의 로컬 연도를 함께 허용하면
        # KST 새해 첫 9시간에 사용자가 명시한 전년을 새해 오늘로 바꾸게 된다.
        if year != int(today[:4]):
            raise RuleUnavailable(
                f"{year}년 기준 계산에는 계산 기준일(YYYY-MM-DD)이 필요합니다 — "
                "연중 변경되는 기준을 연도만으로 정할 수 없습니다")
    return today


def validate_value(key, value):
    spec = PARAMETERS.get(key)
    if spec is None:
        raise ValueError("계산기에 연결되지 않은 기준 키입니다")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("기준 값은 유한한 숫자여야 합니다")
    if not spec["min"] <= value <= spec["max"]:
        raise ValueError("기준 값의 허용 범위를 벗어났습니다")
    if spec["unit"] != "비율(0~1)" and int(value) != value:
        raise ValueError("원 단위 기준 값은 정수여야 합니다")


class RuleSnapshot:
    def __init__(self, records, reference_date):
        self.day = iso_date_or_block(reference_date)
        self.records = deepcopy(records)
        self.used = {}

    def get(self, key):
        matched = [r for r in self.records if r.get("status") == "approved"
                   and r.get("kind") == "parameter" and r.get("key") == key
                   and iso_date(r["effective_from"]) <= self.day
                   and (not r.get("effective_to") or self.day < iso_date(r["effective_to"]))]
        if len(matched) != 1:
            label = PARAMETERS.get(key, {}).get("label", key)
            raise RuleUnavailable(f"{self.day}: 승인된 {label} 기준이 없거나 중복됩니다")
        record = matched[0]
        validate_value(key, record["value"])
        self.used[key] = record
        return record["value"]

    def provenance(self):
        return [{"id": r["id"], "key": k, "value": r["value"],
                 "effective_from": r["effective_from"], "effective_to": r.get("effective_to"),
                 "citation": r["citation"], "evidence_id": r["evidence"]["id"],
                 "evidence_sha256": r["evidence"]["sha256"],
                 "url": r["evidence"].get("official_url") or r["evidence"].get("url", "")}
                for k, r in sorted(self.used.items())]


_snapshot = ContextVar("laborconsult_legal_rule_snapshot", default=None)


@contextmanager
def used_scope():
    """섹션이 보류되면 그 섹션이 읽은 기준을 provenance에서 되돌린다.

    `get()`은 읽는 즉시 `used`에 기록하므로, 8개 중 7개를 읽고 8번째에서 실패한
    보험 계산은 결과가 버려졌는데도 기준 7건을 '적용했다'고 보고하게 된다.
    다른 섹션이 이미 읽은 키는 그대로 둔다(mark 이후 추가분만 제거).
    """
    snapshot = _snapshot.get()
    before = set(snapshot.used) if snapshot is not None else None
    try:
        yield
    except BaseException:
        if snapshot is not None:
            for key in set(snapshot.used) - before:
                snapshot.used.pop(key, None)
        raise


@contextmanager
def rule_scope(snapshot):
    token = _snapshot.set(snapshot)
    try:
        yield
    finally:
        _snapshot.reset(token)


def parameter(key, legacy):
    snapshot = _snapshot.get()
    return snapshot.get(key) if snapshot is not None else legacy


def managed():
    return _snapshot.get() is not None
