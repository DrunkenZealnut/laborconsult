#!/usr/bin/env python3
"""상담 평가 fixture 계약 오프라인 테스트.

실행: ./.venv/bin/python test_consultation_eval.py
"""

from __future__ import annotations

import json
import traceback
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.templates.prompts import ANALYZE_TOOL
from eval_consultation import (
    REQUIRED_CASE_KEYS, EvalCase, aggregate_results, load_cases, score_result,
    validate_cases,
)


FIXTURE = Path(__file__).resolve().parent / "data/eval_consultation_queries.json"
_ANALYZER_PROPERTIES = ANALYZE_TOOL["input_schema"]["properties"]
SUPPORTED_EXPECTED_LABELS = {
    "expected_intent": set(_ANALYZER_PROPERTIES["consultation_type"]["enum"]),
    "expected_topic": set(_ANALYZER_PROPERTIES["consultation_topic"]["enum"]),
    "expected_calculation": set(_ANALYZER_PROPERTIES["calculation_types"]["items"]["enum"]),
}


def test_fixture_has_exactly_60_unique_cases() -> None:
    cases = load_cases(FIXTURE)
    assert len(cases) == 60
    assert len({case.id for case in cases}) == 60


def test_fixture_has_required_fields_and_valid_enums() -> None:
    cases = load_cases(FIXTURE)
    assert validate_cases(cases) == []
    for case in cases:
        assert set(case.__dataclass_fields__) == REQUIRED_CASE_KEYS
        assert case.risk_level in {"low", "medium", "high"}
        assert case.allowed_sources
        for value in (case.id, case.category, case.question):
            assert isinstance(value, str) and value.strip()
        assert isinstance(case.expected_intent, str)
        assert case.expected_topic is None or isinstance(case.expected_topic, str)
        assert case.expected_calculation is None or isinstance(case.expected_calculation, str)
        for field, supported_labels in SUPPORTED_EXPECTED_LABELS.items():
            value = getattr(case, field)
            if value:
                assert value in supported_labels, f"unsupported {field}: {value!r} ({case.id})"
        for values in (case.required_laws, case.allowed_sources,
                       case.required_notices, case.forbidden_claims):
            assert isinstance(values, list)
            assert all(isinstance(value, str) and value.strip() for value in values)
        assert isinstance(case.expected_values, dict)
        assert all(isinstance(key, str) and type(value) in (float, int, str)
                   for key, value in case.expected_values.items())


def test_fixture_category_distribution_matches_design() -> None:
    cases = load_cases(FIXTURE)
    counts: dict[str, int] = {}
    for case in cases:
        counts[case.category] = counts.get(case.category, 0) + 1
    assert counts == {
        "임금·계산": 10,
        "해고·징계·구제절차": 10,
        "근로시간·휴일·연차": 10,
        "퇴직금·퇴직·고용보험": 8,
        "산재·괴롭힘·차별": 8,
        "판례·행정해석·법령 조회": 8,
        "정보 부족·복합·구어체 질문": 6,
    }


def test_fixture_enum_checks_reject_unsupported_labels() -> None:
    cases = load_cases(FIXTURE)
    for field in ("expected_intent", "expected_topic", "expected_calculation"):
        invalid_cases = [replace(cases[0], **{field: "unsupported_label"}), *cases[1:]]
        with patch(f"{__name__}.load_cases", return_value=invalid_cases):
            try:
                test_fixture_has_required_fields_and_valid_enums()
            except AssertionError as error:
                assert f"unsupported {field}:" in str(error)
            else:
                raise AssertionError(f"unsupported label accepted for {field}")


def test_fixture_enum_checks_allow_optional_empty_labels() -> None:
    cases = load_cases(FIXTURE)
    for optional_value in (None, ""):
        optional_case = replace(cases[0], expected_intent="",
                                expected_topic=optional_value,
                                expected_calculation=optional_value)
        with patch(f"{__name__}.load_cases", return_value=[optional_case, *cases[1:]]):
            test_fixture_has_required_fields_and_valid_enums()


def test_fixture_ids_match_design_ranges() -> None:
    cases = load_cases(FIXTURE)
    expected_ids = {
        f"{prefix}-{index:02d}"
        for prefix, count in (("wage", 10), ("dismissal", 10), ("hours", 10),
                              ("retirement", 8), ("risk", 8), ("law", 8), ("missing", 6))
        for index in range(1, count + 1)
    }
    assert {case.id for case in cases} == expected_ids


def test_load_cases_rejects_invalid_root_and_records() -> None:
    valid = json.loads(FIXTURE.read_text(encoding="utf-8"))[0]
    missing_field = dict(valid)
    del missing_field["question"]
    invalid_documents = [
        {}, None, "not a list", [None], ["not a record"], [[]],
        [missing_field], [dict(valid, unexpected=True)],
    ]
    with TemporaryDirectory() as directory:
        path = Path(directory) / "cases.json"
        for document in invalid_documents:
            path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            try:
                load_cases(path)
            except ValueError:
                pass
            else:
                raise AssertionError(f"malformed fixture accepted: {document!r}")


def test_validate_cases_reports_contract_errors() -> None:
    case = load_cases(FIXTURE)[0]
    invalid = replace(case, question=" \n\t", risk_level="urgent", allowed_sources=[])
    assert validate_cases([case, invalid]) == [
        f"duplicate id: {case.id}",
        f"empty question: {case.id}",
        f"invalid risk level: {case.id}",
        f"missing allowed_sources: {case.id}",
    ]


def _metric_case(**changes) -> EvalCase:
    return replace(EvalCase(
        id="x", category="법령", question="질문", expected_intent="law",
        expected_topic="해고·징계", required_laws=["근로기준법 제26조"],
        allowed_sources=["law_article"], expected_calculation=None,
        expected_values={}, required_notices=["1350"],
        forbidden_claims=["무조건 해고할 수 있습니다"], risk_level="high",
    ), **changes)


def _passing_observed(**changes) -> dict:
    return {
        "analysis": {"intent": "law", "topic": "해고·징계"},
        "answer": "근로기준법 제26조 안내. 1350 상담. 법적 효력이 없습니다.",
        "sources": [{"source_type": "law_article", "title": "근로기준법"}],
        "calc_result": None, "assessment_result": None,
        "timing": {"total_ms": 100, "ttft_ms": 2}, "pipeline_error": None,
        **changes,
    }


def test_score_result_detects_missing_law_notice_and_forbidden_claim() -> None:
    result = score_result(_metric_case(), _passing_observed(
        answer="근로기준법 제23조에 따르면 무조건 해고할 수 있습니다.",
    ))
    assert result["required_law_coverage"] == 0.0
    assert result["required_notice_coverage"] == 0.0
    assert result["forbidden_claims_found"] == ["무조건 해고할 수 있습니다"]
    assert result["automatic_pass"] is False


def test_score_result_passes_complete_answer_and_rejects_each_missing_requirement() -> None:
    case = _metric_case()
    result = score_result(case, _passing_observed())
    assert result == {
        "intent_match": True, "topic_match": True,
        "required_law_coverage": 1.0, "allowed_source_only": True,
        "required_notice_coverage": 1.0, "forbidden_claims_found": [],
        "disclaimer_present": True, "calculation_present": None,
        "pipeline_ok": True, "automatic_pass": True,
    }
    failing_changes = [
        {"analysis": {"intent": "other", "topic": "해고·징계"}},
        {"analysis": {"intent": "law", "topic": "other"}},
        {"answer": "1350 상담. 법적 효력이 없습니다."},
        {"answer": "근로기준법 제26조. 법적 효력이 없습니다."},
        {"answer": "근로기준법 제26조. 1350 상담."},
        {"answer": _passing_observed()["answer"] + " 무조건 해고할 수 있습니다"},
        {"sources": [{"source_type": "law_article"}, {"source_type": "blog"}]},
        {"sources": [{"title": "unknown source"}]},
    ]
    for changes in failing_changes:
        assert score_result(case, _passing_observed(**changes))["automatic_pass"] is False


def test_score_result_optional_labels_and_empty_requirements() -> None:
    for optional in (None, ""):
        case = _metric_case(expected_intent=optional, expected_topic=optional,
                            expected_calculation=optional, required_laws=[],
                            required_notices=[])
        result = score_result(case, {"answer": "법적 효력이 없습니다."})
        assert result["intent_match"] is None
        assert result["topic_match"] is None
        assert result["calculation_present"] is None
        assert result["required_law_coverage"] == 1.0
        assert result["required_notice_coverage"] == 1.0
        assert result["allowed_source_only"] is True
        assert result["automatic_pass"] is True


def test_score_result_partial_coverage_uses_answer_only() -> None:
    case = _metric_case(required_laws=["근로기준법 제26조", "근로기준법 제23조"],
                        required_notices=["1350", "노동위원회"])
    result = score_result(case, _passing_observed(
        sources=[{"source_type": "law_article", "title": "근로기준법 제23조 노동위원회"}],
        calc_result="근로기준법 제23조 노동위원회",
    ))
    assert result["required_law_coverage"] == 0.5
    assert result["required_notice_coverage"] == 0.5
    assert result["automatic_pass"] is False


def test_score_result_requires_calculation_event_without_numeric_validation() -> None:
    case = _metric_case(expected_calculation="연장수당", expected_values={"amount": 999})
    for calc_result, present in ((None, False), ("", True), ("계산 결과: 100원", True)):
        result = score_result(case, _passing_observed(calc_result=calc_result))
        assert result["calculation_present"] is present
        assert result["automatic_pass"] is present


def test_score_result_failed_or_empty_answers_cannot_pass() -> None:
    observations = [{}, _passing_observed(pipeline_error="pipeline failed")]
    observations.extend(_passing_observed(answer=answer) for answer in (None, "", " \n\t"))
    for observed in observations:
        result = score_result(_metric_case(), observed)
        assert result["pipeline_ok"] is False
        assert result["automatic_pass"] is False


def test_aggregate_results_excludes_optional_none_from_denominator() -> None:
    summary = aggregate_results([
        {"pipeline_ok": True, "intent_match": True, "topic_match": None,
         "required_law_coverage": 1.0, "required_notice_coverage": 1.0,
         "forbidden_claims_found": [], "disclaimer_present": True,
         "automatic_pass": True, "timing": {"total_ms": 100}},
        {"pipeline_ok": False, "intent_match": False, "topic_match": False,
         "required_law_coverage": 0.0, "required_notice_coverage": 0.0,
         "forbidden_claims_found": ["x"], "disclaimer_present": False,
         "automatic_pass": False, "timing": {"total_ms": 200}},
    ])
    assert summary == {
        "total_cases": 2, "pipeline_success_rate": 0.5,
        "automatic_pass_rate": 0.5, "intent_accuracy": 0.5,
        "topic_accuracy": 0.0, "required_law_coverage": 0.5,
        "required_notice_coverage": 0.5, "disclaimer_rate": 0.5,
        "forbidden_claim_count": 1, "average_total_ms": 150, "p95_total_ms": 200,
    }


def test_aggregate_results_failed_runs_cannot_inflate_quality() -> None:
    metrics = score_result(_metric_case(), _passing_observed())
    failed = {**metrics, "pipeline_ok": False, "forbidden_claims_found": ["x", "y"]}
    summary = aggregate_results([metrics, failed])
    for key in ("pipeline_success_rate", "automatic_pass_rate", "intent_accuracy",
                "topic_accuracy", "required_law_coverage", "required_notice_coverage",
                "disclaimer_rate"):
        assert summary[key] == 0.5, key
    assert summary["forbidden_claim_count"] == 2
    assert summary["average_total_ms"] == 0
    assert summary["p95_total_ms"] == 0


def test_aggregate_results_empty_and_all_optional() -> None:
    assert aggregate_results([]) == {
        "total_cases": 0, "pipeline_success_rate": 0.0,
        "automatic_pass_rate": 0.0, "intent_accuracy": 0.0,
        "topic_accuracy": 0.0, "required_law_coverage": 0.0,
        "required_notice_coverage": 0.0, "disclaimer_rate": 0.0,
        "forbidden_claim_count": 0, "average_total_ms": 0, "p95_total_ms": 0,
    }
    result = score_result(_metric_case(expected_intent="", expected_topic=None),
                          _passing_observed())
    summary = aggregate_results([result])
    assert summary["intent_accuracy"] is None
    assert summary["topic_accuracy"] is None


def test_aggregate_results_latency_uses_nearest_rank_and_measured_runs() -> None:
    results = [{"timing": {"total_ms": value}} for value in range(20, 0, -1)]
    results.extend([{}, {"timing": {"total_ms": None}}])
    summary = aggregate_results(results)
    assert summary["average_total_ms"] == 10  # integer milliseconds, round to nearest
    assert summary["p95_total_ms"] == 19
    summary = aggregate_results([{"timing": {"total_ms": 0}}, {"timing": {"total_ms": 100}}])
    assert summary["average_total_ms"] == 50
    assert summary["p95_total_ms"] == 100


def main() -> int:
    tests = [
        test_fixture_has_exactly_60_unique_cases,
        test_fixture_has_required_fields_and_valid_enums,
        test_fixture_enum_checks_reject_unsupported_labels,
        test_fixture_enum_checks_allow_optional_empty_labels,
        test_fixture_category_distribution_matches_design,
        test_fixture_ids_match_design_ranges,
        test_load_cases_rejects_invalid_root_and_records,
        test_validate_cases_reports_contract_errors,
        test_score_result_detects_missing_law_notice_and_forbidden_claim,
        test_score_result_passes_complete_answer_and_rejects_each_missing_requirement,
        test_score_result_optional_labels_and_empty_requirements,
        test_score_result_partial_coverage_uses_answer_only,
        test_score_result_requires_calculation_event_without_numeric_validation,
        test_score_result_failed_or_empty_answers_cannot_pass,
        test_aggregate_results_excludes_optional_none_from_denominator,
        test_aggregate_results_failed_runs_cannot_inflate_quality,
        test_aggregate_results_empty_and_all_optional,
        test_aggregate_results_latency_uses_nearest_rank_and_measured_runs,
    ]
    try:
        for test in tests:
            test()
            print(f"  ✅ {test.__name__}")
    except Exception:
        traceback.print_exc()
        return 1
    print("\n✅ 상담 평가 fixture·지표 테스트 전부 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
