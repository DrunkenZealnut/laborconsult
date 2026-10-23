"""내장 법률 규칙의 시행일 구간. 개별 제도의 적용례·자격은 계산기가 판단한다."""
from dataclasses import dataclass
from datetime import date
from typing import Mapping, Sequence


# 내장 규칙: 관리자 승인 11개 키와 별도이며 지급 대상 기간에 적용한다.
_EI = "https://www.law.go.kr/법령/고용보험법시행령"


@dataclass(frozen=True)
class EffectiveRule:
    rule_id: str
    effective_from: date
    effective_to: date | None
    values: Mapping
    sources: tuple[str, ...]


@dataclass(frozen=True)
class RuleSlice:
    start: date
    end_exclusive: date
    rule: EffectiveRule


PARENTAL_RULES = (
    EffectiveRule("parental-2024", date(2024,1,1), date(2025,1,1),
                  {"general_caps": (1_500_000,)*3, "general_rates": (.8,)*3,
                   "six_caps": (2_000_000,2_500_000,3_000_000,3_500_000,4_000_000,4_500_000),
                   "single_cap": 2_500_000, "lower": 700_000, "deferred": .25},
                  (_EI, "제95조·95조의3; 제34048호")),
    EffectiveRule("parental-2025", date(2025,1,1), None,
                  {"general_caps": (2_500_000,2_000_000,1_600_000), "general_rates": (1.,1.,.8),
                   "six_caps": (2_500_000,2_500_000,3_000_000,3_500_000,4_000_000,4_500_000),
                   "single_cap": 3_000_000, "lower": 700_000, "deferred": 0.},
                  (_EI, "제35100호 부칙 제3·4·7조")),
)
REDUCED_RULES = tuple(
    EffectiveRule(name, start, end, {"first_hours": hours, "first_cap": first,
                                   "remaining_cap": rest, "lower": 500_000},
                  (_EI, source))
    for name,start,end,hours,first,rest,source in (
        ("reduced-2024a",date(2024,1,1),date(2024,7,1),5,2_000_000,1_500_000,"제104조의2; 제34048호"),
        ("reduced-2024b",date(2024,7,1),date(2025,1,1),10,2_000_000,1_500_000,"제34601호 부칙 제3조"),
        ("reduced-2025",date(2025,1,1),date(2026,1,1),10,2_200_000,1_500_000,"제35100호 부칙 제5조"),
        ("reduced-2026",date(2026,1,1),None,10,2_500_000,1_600_000,"제35934호 부칙 제3조"),
    )
)


def split_effective_periods(start: date, end_exclusive: date,
                            rules: Sequence[EffectiveRule]) -> list[RuleSlice]:
    """[start, end_exclusive) 완전 분할. 빈 기간·역전·규칙 공백/중복은 오류."""
    if not isinstance(start, date) or not isinstance(end_exclusive, date) or start >= end_exclusive:
        raise ValueError("유효한 시작일과 종료일(제외)이 필요합니다")
    ordered = sorted(rules, key=lambda r: r.effective_from)
    for i, rule in enumerate(ordered):
        if rule.effective_to is not None and rule.effective_to <= rule.effective_from:
            raise ValueError("규칙의 시행 기간이 비어 있거나 역전됐습니다")
        if i and (ordered[i-1].effective_to is None or ordered[i-1].effective_to > rule.effective_from):
            raise ValueError("규칙 시행 기간이 중복됩니다")
    result, cursor = [], start
    for rule in ordered:
        a, b = max(start, rule.effective_from), min(end_exclusive, rule.effective_to or end_exclusive)
        if a >= b:
            continue
        if a != cursor:
            raise ValueError("해당 기간의 검증된 규칙이 없습니다")
        result.append(RuleSlice(a, b, rule))
        cursor = b
    if cursor != end_exclusive:
        raise ValueError("해당 기간의 검증된 규칙이 없습니다")
    return result
