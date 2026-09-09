#!/usr/bin/env python3
"""상담 평가 fixture 계약 오프라인 테스트.

실행: ./.venv/bin/python test_consultation_eval.py
"""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import traceback
from contextlib import chdir, redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import eval_consultation as harness
from app.templates.prompts import ANALYZE_TOOL
from eval_consultation import (
    REQUIRED_CASE_KEYS, EvalCase, aggregate_results, collect_events, load_cases,
    run_case, score_result, validate_cases,
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
    errors = validate_cases(cases)
    assert errors == [], "\n".join(errors)
    assert harness.SUPPORTED_EXPECTED_LABELS == SUPPORTED_EXPECTED_LABELS
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


def test_collect_events_builds_observed_shape() -> None:
    observed = collect_events(iter([
        {"type": "status", "text": "분석 중"},
        {"type": "sources", "hits": [{"source_type": "law_article"}]},
        {"type": "meta", "calc_result": "계산 결과"},
        {"type": "meta", "assessment_result": "판정 결과"},
        {"type": "chunk", "text": "법적 효력이 "},
        {"type": "ping"},
        {"type": "chunk", "text": "없습니다."},
        {"type": "done"},
        {"type": "chunk", "text": "종료 후 무시"},
    ]), clock=lambda: 10.0)
    assert observed == {
        "analysis": {"intent": None, "topic": None,
                     "calculation_types": [], "missing_info": []},
        "answer": "법적 효력이 없습니다.",
        "sources": [{"source_type": "law_article"}],
        "calc_result": "계산 결과", "assessment_result": "판정 결과",
        "timing": {"total_ms": 0, "ttft_ms": 0}, "pipeline_error": None,
    }


def test_collect_events_measures_first_chunk_and_done_with_injected_clock() -> None:
    current = [0.0]

    def events():
        for timestamp, event in [
            (10.0, {"type": "status"}),
            (10.25, {"type": "ping"}),
            (10.5, {"type": "chunk", "text": "첫 답변"}),
            (11.0, {"type": "chunk", "text": " 계속"}),
            (11.5, {"type": "done"}),
        ]:
            current[0] = timestamp
            yield event

    observed = collect_events(events(), clock=lambda: current[0])
    assert observed["timing"] == {"total_ms": 1500, "ttft_ms": 500}


def test_collect_events_replaces_answer_and_retains_pipeline_error() -> None:
    observed = collect_events([
        {"type": "chunk", "text": "수정 전"},
        {"type": "replace", "text": "수정된 답변"},
        {"type": "chunk", "text": " 법적 효력이 없습니다."},
        {"type": "error", "text": "서비스 오류"},
        {"type": "done"},
    ])
    assert observed["answer"] == "수정된 답변 법적 효력이 없습니다."
    assert observed["pipeline_error"] == "서비스 오류"
    assert score_result(_metric_case(), observed)["pipeline_ok"] is False
    assert collect_events([{"type": "error"}, {"type": "done"}])["pipeline_error"]


def test_collect_events_records_truncation_and_iteration_errors() -> None:
    def broken_events():
        yield {"type": "chunk", "text": "부분 답변"}
        raise RuntimeError("stream failed")

    observed = collect_events(broken_events(), clock=lambda: 10.0)
    assert observed["answer"] == "부분 답변"
    assert "stream failed" in observed["pipeline_error"]
    for events in ([], [{"type": "chunk", "text": "미완성 답변"}]):
        observed = collect_events(events, clock=lambda: 10.0)
        assert observed["pipeline_error"]
        assert observed["timing"] == {"total_ms": 0, "ttft_ms": 0}
    observed = collect_events([{"type": "done"}], clock=lambda: 10.0)
    assert observed["answer"] == ""
    assert observed["pipeline_error"] is None
    assert observed["timing"] == {"total_ms": 0, "ttft_ms": 0}


def test_run_case_captures_effective_analysis_and_restores_analyzer() -> None:
    from app.core import pipeline
    from app.core.storage import _is_synthetic_session
    from app.models.schemas import AnalysisResult

    case, config = _metric_case(), object()
    analysis = AnalysisResult(consultation_type="law", consultation_topic="해고·징계",
                              calculation_types=["연장수당"], missing_info=["LLM 누락"])
    sessions = []
    missing_policy = pipeline._compute_missing_info

    def analyzer(query, history, received_config, *, summary):
        assert (query, history, received_config, summary) == (case.question, [], config, "")
        return analysis

    def process(query, session, received_config):
        assert query == case.question and received_config is config
        assert session.history == [] and session.calc_cache == {}
        sessions.append(session)
        assert pipeline._compute_missing_info is missing_policy
        captured = pipeline.analyze_intent(query, session.recent(), received_config,
                                           summary=session.summary)
        assert captured is analysis
        # The real pipeline also replaces missing_info after analyze_intent returns.
        captured.missing_info = ["실제 정책 누락"]
        yield {"type": "chunk", "text": "법적 효력이 없습니다."}
        yield {"type": "done"}

    with patch.object(pipeline, "analyze_intent", analyzer), \
            patch.object(pipeline, "process_question", process):
        observed = run_case(case, config)
        assert pipeline.analyze_intent is analyzer
        run_case(case, config)
        assert pipeline.analyze_intent is analyzer
    assert sessions[0] is not sessions[1]
    assert all(_is_synthetic_session(session.id) for session in sessions)
    assert observed["analysis"] == {
        "intent": "law", "topic": "해고·징계", "calculation_types": ["연장수당"],
        "missing_info": ["실제 정책 누락"],
    }
    analysis.calculation_types.append("야간수당")
    analysis.missing_info.append("나중 변경")
    assert observed["analysis"]["calculation_types"] == ["연장수당"]
    assert observed["analysis"]["missing_info"] == ["실제 정책 누락"]
    assert observed["pipeline_error"] is None
    assert json.loads(json.dumps(observed, ensure_ascii=False)) == observed


def test_run_case_restores_analyzer_on_failure_and_preserves_partial_output() -> None:
    from app.core import pipeline

    original = pipeline.analyze_intent

    def fail_at_call(*args):
        raise RuntimeError("startup failed")

    def fail_during_iteration(*args):
        yield {"type": "chunk", "text": "부분 답변"}
        raise RuntimeError("stream failed")

    for process, message, answer in (
        (fail_at_call, "startup failed", ""),
        (fail_during_iteration, "stream failed", "부분 답변"),
    ):
        with patch.object(pipeline, "process_question", process):
            observed = run_case(_metric_case(), object())
            assert pipeline.analyze_intent is original
        assert message in observed["pipeline_error"]
        assert observed["answer"] == answer


def test_run_case_restores_analyzer_on_interrupt_and_closes_generator() -> None:
    from app.core import pipeline

    original = pipeline.analyze_intent
    closed = []

    def process(*args):
        try:
            yield {"type": "done"}
        finally:
            closed.append(True)

    with patch.object(pipeline, "process_question", process):
        run_case(_metric_case(), object())
        assert closed == [True]
        assert pipeline.analyze_intent is original

    def interrupted(*args):
        raise KeyboardInterrupt()

    with patch.object(pipeline, "process_question", interrupted):
        try:
            run_case(_metric_case(), object())
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("interrupt swallowed")
        assert pipeline.analyze_intent is original


def test_offline_cli_needs_only_standard_library_and_writes_nothing() -> None:
    script = Path(harness.__file__).resolve()
    with TemporaryDirectory() as directory:
        for args in ([], ["--offline"], ["--offline", "--limit", "2"],
                     ["--offline", "--case", "law-01", "--output", "unused.json"]):
            result = subprocess.run(
                [sys.executable, "-I", "-S", str(script), *args],
                cwd=directory, capture_output=True, text=True, timeout=20,
            )
            assert result.returncode == 0, result.stderr
            assert "fixture: 60건" in result.stdout
            assert "schema: PASS" in result.stdout
            assert "distribution: PASS" in result.stdout
            assert "offline evaluation contract: PASS" in result.stdout
        assert list(Path(directory).iterdir()) == []


def test_cli_rejects_bad_arguments_before_loading_clients() -> None:
    for args in (["--offline", "--limit", "0"], ["--limit", "-1"],
                 ["--limit", "no"], ["--case", "unknown"],
                 ["--live", "--case", "unknown"], ["--live", "--limit", "0"],
                 ["--offline", "--live"], ["--unknown"]):
        with patch.dict(sys.modules, {"app.config": None}), \
                redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            assert harness.main(args) == 2, args
    with redirect_stdout(io.StringIO()):
        assert harness.main(["--help"]) == 0


def test_offline_cli_reports_fixture_errors() -> None:
    cases = load_cases(FIXTURE)
    for broken in ([replace(cases[0], question=""), *cases[1:]], cases[:-1]):
        output, error = io.StringIO(), io.StringIO()
        with patch.object(harness, "load_cases", return_value=broken), \
                redirect_stdout(output), redirect_stderr(error):
            assert harness.main(["--offline", "--limit", "1"]) == 1
        assert "FAIL" in output.getvalue() + error.getvalue()
    for failure in (ValueError("bad JSON"), OSError("missing fixture")):
        with patch.object(harness, "load_cases", side_effect=failure), \
                redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            assert harness.main(["--offline"]) == 1


def _assert_cli_rejects_fixture_values(invalid_values) -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    with TemporaryDirectory() as directory:
        path = Path(directory) / "cases.json"
        for field, value in invalid_values:
            # Corrupt an unselected case to verify the full fixture gate.
            document = [*raw[:-1], dict(raw[-1], **{field: value})]
            path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            for mode in ("--offline", "--live"):
                output, error = io.StringIO(), io.StringIO()
                with patch.object(harness, "FIXTURE_PATH", path), \
                        patch.dict(sys.modules, {"app.config": None}), \
                        redirect_stdout(output), redirect_stderr(error):
                    status = harness.main([mode, "--case", "wage-01", "--limit", "1"])
                assert status == 1, (mode, field, value, output.getvalue())
                assert "schema: FAIL" in error.getvalue(), (field, value, error.getvalue())
                diagnostic_field = "risk level" if field == "risk_level" else field
                assert diagnostic_field in error.getvalue(), (field, value, error.getvalue())
                assert "PASS" not in output.getvalue()
                assert "live configuration" not in error.getvalue()
        assert sorted(p.name for p in Path(directory).iterdir()) == ["cases.json"]


def test_cli_rejects_malformed_fixture_field_types() -> None:
    invalid_values = [
        (field, value)
        for field in ("id", "category", "question")
        for value in (None, 42, [], {}, "", " \t")
    ]
    invalid_values.extend(
        (field, value)
        for field in ("required_laws", "allowed_sources", "required_notices", "forbidden_claims")
        for value in ("근로기준법 제26조", None, {}, [42], [None], [""], [" \t"])
    )
    invalid_values.extend(("expected_values", value) for value in (
        [], None, "amount", {"amount": True}, {"amount": None},
        {"amount": []}, {"amount": {}},
    ))
    invalid_values.extend(("risk_level", value) for value in (None, [], {}, 42, "urgent"))
    invalid_values.append(("allowed_sources", []))
    _assert_cli_rejects_fixture_values(invalid_values)
    case = load_cases(FIXTURE)[0]
    assert validate_cases([replace(case, expected_values={42: 100})])


def test_cli_rejects_unsupported_and_malformed_routing_labels() -> None:
    _assert_cli_rejects_fixture_values([
        (field, value)
        for field in ("expected_intent", "expected_topic", "expected_calculation")
        for value in ("unsupported_label", " ", 42, False, [], {})
    ] + [("expected_intent", None)])


def test_offline_cli_accepts_supported_and_optional_routing_labels() -> None:
    cases = load_cases(FIXTURE)
    for field, labels in SUPPORTED_EXPECTED_LABELS.items():
        # Check every production enum, including labels absent from the fixture.
        for value in [*labels, "", *([None] if field != "expected_intent" else [])]:
            valid = replace(cases[0], **{field: value}, required_laws=[],
                            required_notices=[], forbidden_claims=[],
                            expected_values={"integer": 1, "float": 1.5, "text": "참고값"})
            with patch.object(harness, "load_cases", return_value=[valid, *cases[1:]]), \
                    patch.dict(sys.modules, {"app.config": None}), \
                    redirect_stdout(io.StringIO()) as output:
                assert harness.main(["--offline"]) == 0, (field, value)
            assert "schema: PASS" in output.getvalue()


def _fake_config_module():
    # AppConfig constructs remote clients and loads .env, so replace that boundary.
    config = SimpleNamespace(supabase=object(), openai_client=object())
    calls = []

    def from_env():
        calls.append(config)
        return config

    return SimpleNamespace(AppConfig=SimpleNamespace(from_env=from_env)), config, calls


def test_live_cli_serializes_full_scores_bounded_answer_and_metadata() -> None:
    module, config, config_calls = _fake_config_module()
    seen = []
    observations = []

    def run(case, actual_config):
        assert actual_config is not config
        assert actual_config.supabase is None
        assert actual_config.openai_client is config.openai_client
        seen.append(case.id)
        observed = collect_events([
            {"type": "chunk", "text": "가" * 3100 + " 법적 효력 " +
             " ".join(case.required_laws + case.required_notices)},
            {"type": "done"},
        ])
        observed["analysis"].update(intent=case.expected_intent, topic=case.expected_topic)
        observed["calc_result"] = "계산 결과"
        observed["timing"] = {"total_ms": 100 if len(seen) == 1 else 200, "ttft_ms": 10}
        observations.append(observed)
        return observed

    with TemporaryDirectory() as directory, chdir(directory), \
            patch.dict(sys.modules, {"app.config": module}), \
            patch.object(harness, "run_case", run), redirect_stdout(io.StringIO()):
        assert harness.main(["--live", "--limit", "2"]) == 0
        report = json.loads(Path("eval_consultation_results.json").read_text())
    assert config_calls == [config]
    assert config.supabase is not None
    assert seen == ["wage-01", "wage-02"]
    assert set(report) == {"run_metadata", "summary", "results"}
    metadata = report["run_metadata"]
    assert datetime.fromisoformat(metadata["started_at"]).tzinfo is not None
    assert Path(metadata["fixture_path"]) == FIXTURE
    assert metadata["fixture_case_count"] == 60
    assert metadata["python_version"] == sys.version.split()[0]
    assert len(metadata["git_commit"]) == 40
    assert report["summary"]["total_cases"] == 2
    assert report["summary"]["average_total_ms"] == 150
    assert report["summary"]["automatic_pass_rate"] == 1.0
    for result in report["results"]:
        assert set(result) == {"case_id", "category", "question", "observed", "scores", "pipeline_error"}
        assert len(result["observed"]["answer"]) == 3000
        assert result["scores"]["disclaimer_present"] is True
        assert result["scores"]["automatic_pass"] is True
        assert result["pipeline_error"] is None
    assert all(len(observed["answer"]) > 3000 for observed in observations)


def test_live_cli_case_selects_from_full_fixture_and_custom_output() -> None:
    module, _, _ = _fake_config_module()
    seen = []

    def run(case, config):
        seen.append(case.id)
        return collect_events([{"type": "chunk", "text": "답변"}, {"type": "done"}])

    with TemporaryDirectory() as directory, chdir(directory), \
            patch.dict(sys.modules, {"app.config": module}), \
            patch.object(harness, "run_case", run), redirect_stdout(io.StringIO()):
        assert harness.main(["--live", "--case", "law-01", "--limit", "1",
                             "--output", "custom_results.json"]) == 0
        report = json.loads(Path("custom_results.json").read_text())
        assert not Path("eval_consultation_results.json").exists()
    assert seen == ["law-01"]
    assert report["results"][0]["case_id"] == "law-01"
    assert report["summary"]["automatic_pass_rate"] == 0.0


def test_live_cli_persists_pipeline_failures_and_returns_failure() -> None:
    module, _, _ = _fake_config_module()

    def run(case, config):
        return collect_events([{"type": "error", "text": "service unavailable"},
                               {"type": "done"}])

    with TemporaryDirectory() as directory, chdir(directory), \
            patch.dict(sys.modules, {"app.config": module}), \
            patch.object(harness, "run_case", run), redirect_stdout(io.StringIO()):
        assert harness.main(["--live", "--limit", "2"]) == 1
        report = json.loads(Path("eval_consultation_results.json").read_text())
    assert len(report["results"]) == 2
    assert report["summary"]["pipeline_success_rate"] == 0.0
    assert all(row["pipeline_error"] == "service unavailable" for row in report["results"])


def test_live_cli_reports_configuration_and_output_errors() -> None:
    module, _, _ = _fake_config_module()
    with patch.dict(sys.modules, {"app.config": module}), \
            patch.object(module.AppConfig, "from_env", side_effect=OSError("missing keys")), \
            redirect_stderr(io.StringIO()) as error:
        assert harness.main(["--live", "--limit", "1"]) == 1
        assert "missing keys" in error.getvalue()
    with TemporaryDirectory() as directory, patch.dict(sys.modules, {"app.config": module}), \
            patch.object(harness, "run_case", return_value=collect_events([{"type": "done"}])), \
            redirect_stderr(io.StringIO()) as error, redirect_stdout(io.StringIO()):
        assert harness.main(["--live", "--limit", "1", "--output", directory]) == 1
        assert error.getvalue()



def test_publish_admin_requires_live_before_loading_clients() -> None:
    for args in (["--publish-admin"], ["--offline", "--publish-admin"]):
        with patch.dict(sys.modules, {"app.config": None}), \
                redirect_stderr(io.StringIO()) as error:
            assert harness.main(args) == 2
        assert "--publish-admin requires --live" in error.getvalue()


def test_live_cli_publishes_only_after_local_output_with_isolated_config() -> None:
    from test_admin_consultation_quality import FakeSupabaseInsertRecorder

    module, config, _ = _fake_config_module()
    reports = []
    seen = []
    with TemporaryDirectory() as directory, chdir(directory):
        path = Path("published.json")
        fake = FakeSupabaseInsertRecorder(
            before_execute=lambda: reports.append(json.loads(path.read_text())))
        config.supabase = fake

        def run(case, actual_config):
            assert actual_config is not config and actual_config.supabase is None
            assert config.supabase is fake
            assert fake.calls == []
            seen.append(case.id)
            return collect_events([{"type": "chunk", "text": "가" * 3100}, {"type": "done"}])

        with patch.dict(sys.modules, {"app.config": module}), \
                patch.object(harness, "run_case", run), redirect_stdout(io.StringIO()) as output:
            assert harness.main(["--live", "--limit", "2", "--publish-admin",
                                 "--output", str(path)]) == 0
        assert "admin publish: PASS" in output.getvalue()
        assert reports[0]["run_metadata"]["run_id"] in output.getvalue()
    assert seen == ["wage-01", "wage-02"]
    assert len(fake.inserted) == 1
    row = fake.inserted[0]
    assert row["results"] == reports[0]["results"]
    assert row["summary"] == reports[0]["summary"]
    assert row["mode"] == "live" and row["evaluated_case_count"] == 2
    assert re.fullmatch(r"eval_[A-Za-z0-9_-]{1,123}", row["run_id"])
    assert datetime.fromisoformat(row["finished_at"]) >= datetime.fromisoformat(row["started_at"])
    assert all(len(result["observed"]["answer"]) == 3000 for result in row["results"])


def test_publish_admin_preserves_local_report_on_missing_client_or_insert_failure() -> None:
    from test_admin_consultation_quality import FakeSupabaseInsertRecorder

    class DuplicateRunError(RuntimeError):
        code = "23505"

    for failure in (None, RuntimeError("database unavailable"), DuplicateRunError("duplicate key")):
        module, config, _ = _fake_config_module()
        config.supabase = FakeSupabaseInsertRecorder(failure=failure) if failure else None
        with TemporaryDirectory() as directory, chdir(directory), \
                patch.dict(sys.modules, {"app.config": module}), \
                patch.object(harness, "run_case", return_value=collect_events([
                    {"type": "chunk", "text": "saved answer"}, {"type": "done"}])), \
                redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()) as error:
            assert harness.main(["--live", "--limit", "1", "--publish-admin"]) == 1
            report = json.loads(Path("eval_consultation_results.json").read_text())
            assert report["results"][0]["observed"]["answer"] == "saved answer"
            assert "admin publish: FAIL" in error.getvalue()
            assert "admin publish: PASS" not in output.getvalue()
            if isinstance(failure, DuplicateRunError):
                assert "duplicate" in error.getvalue().lower()
                assert report["run_metadata"]["run_id"] in error.getvalue()
        if failure:
            assert len(config.supabase.inserted) == 1
            assert config.supabase.calls[-1] == ("execute",)


def test_live_cli_does_not_publish_without_flag_or_when_output_fails_or_run_empty() -> None:
    from test_admin_consultation_quality import FakeSupabaseInsertRecorder

    module, config, _ = _fake_config_module()
    fake = config.supabase = FakeSupabaseInsertRecorder()
    with TemporaryDirectory() as directory, chdir(directory), \
            patch.dict(sys.modules, {"app.config": module}), \
            patch.object(harness, "run_case", return_value=collect_events([
                {"type": "chunk", "text": "saved"}, {"type": "done"}])), \
            redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        assert harness.main(["--live", "--limit", "1"]) == 0
        first = json.loads(Path("eval_consultation_results.json").read_text())
        assert harness.main(["--live", "--limit", "1", "--publish-admin", "--output", "."]) == 1
        assert json.loads(Path("eval_consultation_results.json").read_text()) == first
        with patch.object(harness, "load_cases", return_value=[]), \
                patch.object(harness, "EXPECTED_DISTRIBUTION", {}):
            assert harness.main(["--live", "--publish-admin"]) == 1
    assert fake.calls == []


def test_live_cli_records_unexpected_pipeline_exceptions_and_publishes_failed_status() -> None:
    from test_admin_consultation_quality import FakeSupabaseInsertRecorder

    module, config, _ = _fake_config_module()
    config.supabase = FakeSupabaseInsertRecorder()
    with TemporaryDirectory() as directory, chdir(directory), \
            patch.dict(sys.modules, {"app.config": module}), \
            patch.object(harness, "run_case", side_effect=RuntimeError("startup failed")), \
            redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        assert harness.main(["--live", "--limit", "1", "--publish-admin"]) == 1
        report = json.loads(Path("eval_consultation_results.json").read_text())
    assert "startup failed" in report["results"][0]["pipeline_error"]
    assert config.supabase.inserted[0]["status"] == "failed"


def test_live_cli_publish_run_ids_are_unique() -> None:
    from test_admin_consultation_quality import FakeSupabaseInsertRecorder

    module, config, _ = _fake_config_module()
    config.supabase = FakeSupabaseInsertRecorder()
    with TemporaryDirectory() as directory, chdir(directory), \
            patch.dict(sys.modules, {"app.config": module}), \
            patch.object(harness, "run_case", return_value=collect_events([
                {"type": "chunk", "text": "answer"}, {"type": "done"}])), \
            redirect_stdout(io.StringIO()):
        for _ in range(2):
            assert harness.main(["--live", "--limit", "1", "--publish-admin"]) == 0
    assert len({row["run_id"] for row in config.supabase.inserted}) == 2


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
        test_collect_events_builds_observed_shape,
        test_collect_events_measures_first_chunk_and_done_with_injected_clock,
        test_collect_events_replaces_answer_and_retains_pipeline_error,
        test_collect_events_records_truncation_and_iteration_errors,
        test_run_case_captures_effective_analysis_and_restores_analyzer,
        test_run_case_restores_analyzer_on_failure_and_preserves_partial_output,
        test_run_case_restores_analyzer_on_interrupt_and_closes_generator,
        test_offline_cli_needs_only_standard_library_and_writes_nothing,
        test_cli_rejects_bad_arguments_before_loading_clients,
        test_offline_cli_reports_fixture_errors,
        test_cli_rejects_malformed_fixture_field_types,
        test_cli_rejects_unsupported_and_malformed_routing_labels,
        test_offline_cli_accepts_supported_and_optional_routing_labels,
        test_live_cli_serializes_full_scores_bounded_answer_and_metadata,
        test_live_cli_case_selects_from_full_fixture_and_custom_output,
        test_live_cli_persists_pipeline_failures_and_returns_failure,
        test_live_cli_reports_configuration_and_output_errors,
        test_publish_admin_requires_live_before_loading_clients,
        test_live_cli_publishes_only_after_local_output_with_isolated_config,
        test_publish_admin_preserves_local_report_on_missing_client_or_insert_failure,
        test_live_cli_does_not_publish_without_flag_or_when_output_fails_or_run_empty,
        test_live_cli_records_unexpected_pipeline_exceptions_and_publishes_failed_status,
        test_live_cli_publish_run_ids_are_unique,
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
