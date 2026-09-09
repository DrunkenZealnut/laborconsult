#!/usr/bin/env python3
"""상담 평가 fixture·지표·파이프라인 수집기 (live 실행만 외부 의존성 로드).

질문은 비식별 합성 데이터다. expected_intent는 analyzer의 consultation_type
값이며, 계산·괴롭힘·복합 질문의 빈 문자열은 의도 판정을 요구하지 않는다.
expected_topic=None도 선택 판정이다. expected_calculation은 calculation_types의
단일 enum 값이고 복수 계산 질문에서는 대표 유형을 기록한다. expected_values는
명시된 조건으로 계산 가능한 참고값이며 첫 단계 하네스의 수치 채점 대상은 아니다.
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import re
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterable
from copy import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from uuid import uuid4


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
# Keep offline validation standard-library-only. Tests check these labels against
# the production analyzer schema, including labels not yet used by the fixture.
SUPPORTED_EXPECTED_LABELS = {
    "expected_intent": frozenset({
        "law_interpretation", "precedent_search", "procedure_guide",
        "rights_check", "system_explanation",
    }),
    "expected_topic": frozenset({
        "해고·징계", "임금·통상임금", "근로시간·휴일", "퇴직·퇴직금", "연차휴가",
        "산재보상", "비정규직", "노동조합", "직장내괴롭힘", "근로계약", "고용보험", "기타",
    }),
    "expected_calculation": frozenset({
        "overtime", "minimum_wage", "weekly_holiday", "annual_leave", "dismissal",
        "severance", "unemployment", "insurance", "comprehensive", "parental_leave",
        "maternity_leave", "prorated", "wage_arrears", "flexible_work",
        "compensatory_leave", "eitc", "average_wage", "shutdown_allowance",
        "working_hours", "public_holiday", "ordinary_wage", "retirement_tax",
        "retirement_pension",
    }),
}
DISCLAIMER_MARKER = "법적 효력"
FIXTURE_PATH = Path(__file__).resolve().parent / "data/eval_consultation_queries.json"
EXPECTED_DISTRIBUTION = {
    "임금·계산": 10,
    "해고·징계·구제절차": 10,
    "근로시간·휴일·연차": 10,
    "퇴직금·퇴직·고용보험": 8,
    "산재·괴롭힘·차별": 8,
    "판례·행정해석·법령 조회": 8,
    "정보 부족·복합·구어체 질문": 6,
}


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
        if isinstance(case.id, str) and case.id.strip():
            if case.id in seen:
                errors.append(f"duplicate id: {case.id}")
            seen.add(case.id)
        for field in ("id", "category", "question"):
            value = getattr(case, field)
            if not isinstance(value, str):
                errors.append(f"invalid {field}: {case.id}")
            elif not value.strip():
                errors.append(f"empty {field}: {case.id}")
        if not isinstance(case.risk_level, str) or case.risk_level not in VALID_RISK_LEVELS:
            errors.append(f"invalid risk level: {case.id}")
        if not case.allowed_sources:
            errors.append(f"missing allowed_sources: {case.id}")
        for field in ("required_laws", "allowed_sources", "required_notices", "forbidden_claims"):
            values = getattr(case, field)
            if not isinstance(values, list) or not all(
                isinstance(value, str) and value.strip() for value in values
            ):
                errors.append(f"invalid {field}: {case.id}; expected a list of nonempty strings")
        if not isinstance(case.expected_values, dict) or not all(
            isinstance(key, str) and type(value) in (float, int, str)
            for key, value in case.expected_values.items()
        ):
            errors.append(f"invalid expected_values: {case.id}")
        for field, supported_labels in SUPPORTED_EXPECTED_LABELS.items():
            value = getattr(case, field)
            if value is None and field != "expected_intent":
                continue
            if not isinstance(value, str) or (value != "" and value not in supported_labels):
                errors.append(f"unsupported {field}: {value!r} ({case.id})")
    return errors


def _analysis_snapshot(analysis) -> dict:
    return {
        "intent": getattr(analysis, "consultation_type", None),
        "topic": getattr(analysis, "consultation_topic", None),
        "calculation_types": list(getattr(analysis, "calculation_types", []) or []),
        "missing_info": list(getattr(analysis, "missing_info", []) or []),
    }


def collect_events(events: Iterable[dict], *, clock: Callable[[], float] = time.perf_counter) -> dict:
    """첫 이벤트부터 done까지 수집한다. clock은 단조 증가하는 초 단위 함수다.

    TTFT는 첫 chunk까지의 시간이며 chunk가 없으면 0이다. replace는 표시된
    본문 전체를 교체한다. done 없는 종료와 실행 예외도 부분 답변을 보존해
    실패 레코드로 반환한다. 이벤트 iterable의 자원 정리는 호출자가 담당한다.
    """
    observed = {
        "analysis": _analysis_snapshot(None),
        "answer": "", "sources": [], "calc_result": None,
        "assessment_result": None,
        "timing": {"total_ms": 0, "ttft_ms": 0}, "pipeline_error": None,
    }
    started = first_chunk = ended = None
    chunks = []
    done = False
    try:
        for event in events:
            ended = clock()
            if started is None:
                started = ended
            event_type = event.get("type")
            if event_type == "chunk":
                if first_chunk is None:
                    first_chunk = ended
                chunks.append(event.get("text", ""))
            elif event_type == "replace":
                chunks = [event.get("text", "")]
            elif event_type == "sources":
                observed["sources"] = list(event.get("hits", []))
            elif event_type == "meta":
                for key in ("calc_result", "assessment_result"):
                    if key in event:
                        observed[key] = event[key]
            elif event_type == "error":
                observed["pipeline_error"] = event.get("text") or "pipeline error"
            elif event_type == "done":
                done = True
                break
    except Exception as error:
        observed["pipeline_error"] = f"{type(error).__name__}: {error}"
    if not done:
        ended = clock()
        if not observed["pipeline_error"]:
            observed["pipeline_error"] = "pipeline ended without done event"
    observed["answer"] = "".join(chunks)
    if started is not None:
        observed["timing"]["total_ms"] = round((ended - started) * 1000)
        if first_chunk is not None:
            observed["timing"]["ttft_ms"] = round((first_chunk - started) * 1000)
    return observed


def run_case(case: EvalCase, config) -> dict:
    """독립 세션에서 라이브 평가 1건을 실행한다 (같은 프로세스에서 순차 호출).

    analyze_intent 참조를 잠시 교체하므로 서비스 요청과 동시 실행하지 않는다.
    analyzer가 반환한 객체를 보관해 파이프라인의 실제 누락정보 정책 적용 후
    snapshot을 만든다. 외부 모듈은 이 함수에서만 import하여 오프라인 사용은
    API 클라이언트와 설정 로딩 없이 가능하다.
    """
    from app.core import pipeline
    from app.models.session import Session

    original = pipeline.analyze_intent
    analysis = None

    def capture_analysis(*args, **kwargs):
        nonlocal analysis
        analysis = original(*args, **kwargs)
        return analysis

    def case_events():
        # Defer invocation so errors before the first yield also become records.
        yield from pipeline.process_question(case.question, Session(id=f"eval_{case.id}"), config)

    events = case_events()
    pipeline.analyze_intent = capture_analysis
    try:
        observed = collect_events(events)
        observed["analysis"] = _analysis_snapshot(analysis)
        return observed
    finally:
        try:
            events.close()
        finally:
            pipeline.analyze_intent = original


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


def _git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parent,
            check=True, capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _new_run_id() -> str:
    return f"eval_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid4().hex}"


def _admin_run_row(report: dict) -> dict:
    """Validate a finished Live report before accessing the evaluation table."""
    if not isinstance(report, dict):
        raise ValueError("report must be an object")
    metadata, summary, results = (report.get(key) for key in ("run_metadata", "summary", "results"))
    if not isinstance(metadata, dict) or not isinstance(summary, dict):
        raise ValueError("run_metadata and summary must be objects")
    if not isinstance(results, list) or not results:
        raise ValueError("results must be a nonempty list")
    run_id = metadata.get("run_id")
    if not isinstance(run_id, str) or not re.fullmatch(r"eval_[A-Za-z0-9_-]{1,123}", run_id):
        raise ValueError("invalid evaluation run_id")
    if metadata.get("mode") != "live":
        raise ValueError("admin publication requires a Live report")
    timestamps = []
    for key in ("started_at", "finished_at"):
        value = metadata.get(key)
        if not isinstance(value, str):
            raise ValueError(f"{key} must be an ISO timestamp")
        timestamp = datetime.fromisoformat(value)
        if timestamp.tzinfo is None:
            raise ValueError(f"{key} must include a timezone")
        timestamps.append(timestamp)
    if timestamps[1] < timestamps[0]:
        raise ValueError("finished_at precedes started_at")
    for key in ("fixture_case_count", "evaluated_case_count"):
        value = metadata.get(key)
        if type(value) is not int or value < 0:
            raise ValueError(f"{key} must be a nonnegative integer")
    if not len(results) == metadata["evaluated_case_count"] <= metadata["fixture_case_count"]:
        raise ValueError("case counts do not match results")
    failures = 0
    for result in results:
        if not isinstance(result, dict) or not isinstance(result.get("case_id"), str) or not result["case_id"]:
            raise ValueError("each result must have a case_id")
        observed = result.get("observed")
        if not isinstance(observed, dict) or not isinstance(observed.get("answer"), str):
            raise ValueError("each result must have an observed answer string")
        if len(observed["answer"]) > 3000:
            raise ValueError("observed answer exceeds 3000 characters")
        scores = result.get("scores", {})
        if not isinstance(scores, dict):
            raise ValueError("result scores must be an object")
        failures += bool(result.get("pipeline_error") or observed.get("pipeline_error")
                         or scores.get("pipeline_ok") is False)
    row = {
        **{key: metadata[key] for key in (
            "run_id", "mode", "started_at", "finished_at",
            "fixture_case_count", "evaluated_case_count",
        )},
        "status": "failed" if failures == len(results) else "partial" if failures else "completed",
        "summary": summary, "results": results, "metadata": metadata,
    }
    try:
        json.dumps(row, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError("report must contain JSON-compatible values") from error
    return row


def publish_admin_run(report: dict, supabase) -> str:
    """Insert exactly one validated report using the evaluation-only schema."""
    row = _admin_run_row(report)
    if supabase is None:
        raise ValueError("Supabase is not configured for admin publication")
    try:
        supabase.schema("public").table("consultation_eval_runs").insert(row).execute()
    except Exception as error:
        if getattr(error, "code", None) == "23505":
            raise ValueError(f"duplicate evaluation run_id: {row['run_id']}") from error
        raise
    return row["run_id"]


def main(argv: list[str] | None = None) -> int:
    """기본값은 fixture 검증만 수행한다. live는 순차 실행 후 로컬 JSON을 쓴다.

    CLI 오류는 2, fixture·설정·저장·파이프라인 실행 오류는 1이다. 품질 지표
    미달 자체는 실행 실패가 아니므로 0이며, 결과의 automatic_pass로 확인한다.
    --case를 먼저 선택한 뒤 --limit을 적용한다. offline은 결과 파일을 쓰지 않는다.
    """
    parser = argparse.ArgumentParser(description="상담 평가 fixture 검증 및 라이브 평가")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="외부 호출 없이 fixture 검증 (기본값)")
    mode.add_argument("--live", action="store_true", help="실제 파이프라인을 순차 실행")
    parser.add_argument("--publish-admin", action="store_true", help="Live 결과를 관리자 평가 테이블에 저장")
    parser.add_argument("--limit", type=int, help="앞에서부터 실행할 사례 수 (양수)")
    parser.add_argument("--case", metavar="ID", help="지정 ID 하나만 선택")
    parser.add_argument("--output", type=Path, default=Path("eval_consultation_results.json"),
                        help="라이브 결과 JSON 경로 (기본: %(default)s)")
    try:
        args = parser.parse_args(argv)
        if args.publish_admin and not args.live:
            parser.error("--publish-admin requires --live")
        if args.limit is not None and args.limit <= 0:
            parser.error("--limit must be positive")
    except SystemExit as error:
        return int(error.code)

    try:
        cases = load_cases(FIXTURE_PATH)
        errors = validate_cases(cases)
        distribution_ok = (
            all(isinstance(case.category, str) for case in cases)
            and Counter(case.category for case in cases) == EXPECTED_DISTRIBUTION
        )
    except (OSError, ValueError, TypeError, AttributeError) as error:
        print(f"fixture: FAIL: {error}", file=sys.stderr)
        return 1
    if errors or not distribution_ok:
        for error in errors:
            print(f"schema: FAIL: {error}", file=sys.stderr)
        if not distribution_ok:
            print("distribution: FAIL", file=sys.stderr)
        return 1

    selected = cases
    if args.case is not None:
        selected = [case for case in cases if case.id == args.case]
        if not selected:
            print(f"unknown case ID: {args.case}", file=sys.stderr)
            return 2
    if args.limit is not None:
        selected = selected[:args.limit]

    if not args.live:
        print(f"fixture: {len(cases)}건")
        print("schema: PASS")
        print("distribution: PASS")
        print("offline evaluation contract: PASS")
        return 0

    if not selected:
        print("live evaluation: FAIL: no selected cases", file=sys.stderr)
        return 1

    metadata = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "fixture_path": str(FIXTURE_PATH),
        "fixture_case_count": len(cases),
        "python_version": platform.python_version(),
        "git_commit": _git_commit(),
    }
    try:
        from app.config import AppConfig

        original_config = AppConfig.from_env()
        publisher_client = original_config.supabase if args.publish_admin else None
        config = copy(original_config)
        # process_question persists answers when supabase is set. Evaluation
        # records are published only through the explicit evaluation boundary.
        config.supabase = None
    except Exception as error:
        print(f"live configuration: FAIL: {error}", file=sys.stderr)
        return 1

    results = []
    for case in selected:
        try:
            observed = run_case(case, config)
        except Exception as error:
            observed = collect_events([
                {"type": "error", "text": f"{type(error).__name__}: {error}"},
                {"type": "done"},
            ])
        scores = score_result(case, observed)
        results.append({
            "case_id": case.id,
            "category": case.category,
            "question": case.question,
            "observed": {**observed, "answer": observed["answer"][:3000]},
            "scores": scores,
            "pipeline_error": observed["pipeline_error"],
        })
    summary = aggregate_results([
        {**result["scores"], "timing": result["observed"]["timing"]}
        for result in results
    ])
    report = {"run_metadata": metadata, "summary": summary, "results": results}
    if args.publish_admin:
        metadata.update(run_id=_new_run_id(), mode="live",
                        finished_at=datetime.now(timezone.utc).isoformat(),
                        evaluated_case_count=len(results))
    try:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    except (OSError, TypeError, ValueError) as error:
        print(f"output: FAIL: {error}", file=sys.stderr)
        return 1
    print(f"live evaluation: {len(results)}건")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"output: {args.output}")
    if args.publish_admin:
        try:
            run_id = publish_admin_run(report, publisher_client)
        except Exception as error:
            print(f"admin publish: FAIL: {error}; local report: {args.output}", file=sys.stderr)
            return 1
        print(f"admin publish: PASS: {run_id}")
    return 0 if all(result["scores"]["pipeline_ok"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
