#!/usr/bin/env python3
"""상담 평가 fixture 로더와 계약 검증 도구 (표준 라이브러리만 사용).

질문은 비식별 합성 데이터다. expected_intent는 analyzer의 consultation_type
값이며, 계산·괴롭힘·복합 질문의 빈 문자열은 의도 판정을 요구하지 않는다.
expected_topic=None도 선택 판정이다. expected_calculation은 calculation_types의
단일 enum 값이고 복수 계산 질문에서는 대표 유형을 기록한다. expected_values는
명시된 조건으로 계산 가능한 참고값이며 첫 단계 하네스의 수치 채점 대상은 아니다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


REQUIRED_CASE_KEYS = frozenset({
    "id",
    "category",
    "question",
    "expected_intent",
    "expected_topic",
    "required_laws",
    "allowed_sources",
    "expected_calculation",
    "expected_values",
    "required_notices",
    "forbidden_claims",
    "risk_level",
})
VALID_RISK_LEVELS = frozenset({"low", "medium", "high"})


@dataclass(frozen=True)
class EvalCase:
    id: str
    category: str
    question: str
    expected_intent: str
    expected_topic: str | None
    required_laws: list[str]
    allowed_sources: list[str]
    expected_calculation: str | None
    expected_values: dict[str, float | int | str]
    required_notices: list[str]
    forbidden_claims: list[str]
    risk_level: str


def load_cases(path: Path) -> list[EvalCase]:
    """JSON fixture를 읽어 필드 집합이 고정된 평가 사례로 변환한다."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("evaluation fixture root must be a list")

    cases = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or set(item) != REQUIRED_CASE_KEYS:
            raise ValueError(f"case {index} has invalid field set")
        cases.append(EvalCase(**item))
    return cases


def validate_cases(cases: list[EvalCase]) -> list[str]:
    """평가 사례의 결정론적으로 확인 가능한 계약 오류를 반환한다."""
    errors = []
    seen = set()
    for case in cases:
        if case.id in seen:
            errors.append(f"duplicate id: {case.id}")
        seen.add(case.id)
        if not case.question.strip():
            errors.append(f"empty question: {case.id}")
        if case.risk_level not in VALID_RISK_LEVELS:
            errors.append(f"invalid risk level: {case.id}")
        if not case.allowed_sources:
            errors.append(f"missing allowed_sources: {case.id}")
    return errors
