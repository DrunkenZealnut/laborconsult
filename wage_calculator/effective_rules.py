"""내장 법률 규칙의 시행일 구간. 개별 제도의 적용례·자격은 계산기가 판단한다."""
from dataclasses import dataclass
from datetime import date
from typing import Mapping, Sequence


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
