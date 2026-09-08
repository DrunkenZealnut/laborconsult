#!/usr/bin/env python3
"""상담 평가 fixture 로더와 결정론적 답변 지표 (표준 라이브러리만 사용).

질문은 비식별 합성 데이터다. expected_intent는 analyzer의 consultation_type
값이며, 계산·괴롭힘·복합 질문의 빈 문자열은 의도 판정을 요구하지 않는다.
expected_topic=None도 선택 판정이다. expected_calculation은 calculation_types의
단일 enum 값이고 복수 계산 질문에서는 대표 유형을 기록한다. expected_values는
명시된 조건으로 계산 가능한 참고값이며 첫 단계 하네스의 수치 채점 대상은 아니다.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import mean


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
DISCLAIMER_MARKER = "법적 효력"


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


def _coverage(text: str, required: list[str]) -> float:
    if not required:
        return 1.0
    return sum(item in text for item in required) / len(required)


def score_result(case: EvalCase, observed: dict) -> dict:
    """답변 원문의 문자열과 수집 이벤트로 평가하며 숫자 의미는 검증하지 않는다."""
    answer = observed.get("answer", "") or ""
    analysis = observed.get("analysis") or {}
    source_types = {
        hit.get("source_type", "") for hit in observed.get("sources", [])
    }
    forbidden = [item for item in case.forbidden_claims if item in answer]
    intent_match = (
        analysis.get("intent") == case.expected_intent
        if case.expected_intent else None
    )
    topic_match = (
        analysis.get("topic") == case.expected_topic
        if case.expected_topic else None
    )
    calculation_present = (
        observed.get("calc_result") is not None
        if case.expected_calculation else None
    )
    required_law_coverage = _coverage(answer, case.required_laws)
    required_notice_coverage = _coverage(answer, case.required_notices)
    allowed_source_only = source_types.issubset(set(case.allowed_sources))
    disclaimer_present = DISCLAIMER_MARKER in answer
    pipeline_ok = bool(answer.strip()) and not observed.get("pipeline_error")
    automatic_pass = (
        pipeline_ok
        and not forbidden
        and allowed_source_only
        and required_law_coverage >= 1.0
        and required_notice_coverage >= 1.0
        and disclaimer_present
        and intent_match is not False
        and topic_match is not False
        and calculation_present is not False
    )
    return {
        "intent_match": intent_match,
        "topic_match": topic_match,
        "required_law_coverage": required_law_coverage,
        "allowed_source_only": allowed_source_only,
        "required_notice_coverage": required_notice_coverage,
        "forbidden_claims_found": forbidden,
        "disclaimer_present": disclaimer_present,
        "calculation_present": calculation_present,
        "pipeline_ok": pipeline_ok,
        "automatic_pass": automatic_pass,
    }


def aggregate_results(results: list[dict]) -> dict:
    """평점 dict와 선택 timing을 집계하고 실패 실행의 품질 점수는 0으로 센다.

    선택 정확도의 None은 분모에서 제외한다. 비어 있는 실행 목록의 비율은
    0.0이며, 사례가 있지만 해당 라벨이 전부 선택이면 정확도는 None이다.
    지연은 실패 실행도 포함해 측정값만 사용하고, 평균은 정수 반올림,
    p95는 nearest-rank 방식으로 계산한다.
    """
    total = len(results)

    def quality_average(key: str, *, optional: bool = False) -> float | None:
        eligible = [result for result in results
                    if not optional or result.get(key) is not None]
        if not eligible:
            return None if optional and total else 0.0
        return sum(
            result.get(key, 0) if result.get("pipeline_ok") else 0
            for result in eligible
        ) / len(eligible)

    timings = sorted(
        total_ms for result in results
        if (total_ms := (result.get("timing") or {}).get("total_ms")) is not None
    )
    return {
        "total_cases": total,
        "pipeline_success_rate": (
            sum(bool(result.get("pipeline_ok")) for result in results) / total
            if total else 0.0
        ),
        "automatic_pass_rate": quality_average("automatic_pass"),
        "intent_accuracy": quality_average("intent_match", optional=True),
        "topic_accuracy": quality_average("topic_match", optional=True),
        "required_law_coverage": quality_average("required_law_coverage"),
        "required_notice_coverage": quality_average("required_notice_coverage"),
        "disclaimer_rate": quality_average("disclaimer_present"),
        "forbidden_claim_count": sum(
            len(result.get("forbidden_claims_found", [])) for result in results
        ),
        "average_total_ms": round(mean(timings)) if timings else 0,
        "p95_total_ms": int(timings[math.ceil(0.95 * len(timings)) - 1]) if timings else 0,
    }
