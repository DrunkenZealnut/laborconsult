#!/usr/bin/env python3
"""LLM 폴백 경화 오프라인 회귀 테스트 (llm-fallback-hardening FR-11)

API 키 없이 가짜 스트림 함수를 주입해 폴백 판정 규약을 검증한다.
검증 대상은 "실패했을 때 어떻게 되는가"이며, 그 경로는 실제 장애가 나야만
드러나기 때문에 오프라인 재현이 유일한 상시 방어선이다.

실행: python3 test_llm_fallback.py
"""

from __future__ import annotations

import logging
import sys

from app.config import AppConfig
from app.core import pipeline
from app.core.pipeline import AnswerOutcome


# ── 테스트 도우미 ─────────────────────────────────────────────────────────────

def _cfg(gemini: bool = True) -> AppConfig:
    """스트림 함수를 전부 주입하므로 클라이언트는 자리표시자면 충분하다."""
    return AppConfig(
        openai_client=object(), pinecone_index=None, claude_client=object(),
        gemini_api_key="fake-key" if gemini else None, supabase=None,
    )


def _fake(chunks: list[str] | None = None, raise_after: int | None = None):
    """가짜 스트림 함수 생성기.

    chunks: 순서대로 yield할 청크
    raise_after: N개 yield 후 예외 발생 (0이면 즉시 실패)
    """
    def fn(messages, system, config):
        for i, text in enumerate(chunks or []):
            if raise_after is not None and i >= raise_after:
                raise RuntimeError("주입된 스트림 오류")
            yield text
        if raise_after is not None and raise_after <= len(chunks or []):
            raise RuntimeError("주입된 스트림 오류")
    return fn


def _run(providers: list[tuple[str, object]], config=None):
    """_answer_providers를 주입하고 _stream_answer를 소비한다."""
    real = pipeline._answer_providers
    pipeline._answer_providers = lambda cfg: providers
    outcome = AnswerOutcome()
    try:
        events = list(pipeline._stream_answer([], "", config or _cfg(), outcome))
    finally:
        pipeline._answer_providers = real
    return events, outcome


def _text(events) -> str:
    return "".join(t for _, t in events)


# ── T1~T6: _stream_answer 실패 판정 ───────────────────────────────────────────

def test_t1_empty_first_provider_falls_back() -> None:
    """T1 — 1순위가 0청크로 정상 종료하면 성공이 아니라 폴백이어야 한다 (FR-01)."""
    events, outcome = _run([
        ("Claude", _fake([])),
        ("OpenAI", _fake(["정상 답변"])),
    ])
    assert _text(events) == "정상 답변", events
    assert outcome.provider == "OpenAI", outcome
    assert outcome.empty_providers == ["Claude"], outcome
    assert outcome.attempts == ["Claude", "OpenAI"], outcome
    print("  ✅ T1 빈 응답(0청크)을 실패로 승격 → 다음 제공자로 전환")


def test_t2_whitespace_only_not_leaked() -> None:
    """T2 — 공백만 내다 끝난 제공자의 공백이 프론트로 새면 안 된다 (FR-01)."""
    events, outcome = _run([
        ("Claude", _fake(["  ", "\n"])),
        ("OpenAI", _fake(["실제 답변"])),
    ])
    assert _text(events) == "실제 답변", f"공백 오염: {events!r}"
    assert outcome.provider == "OpenAI", outcome
    assert outcome.empty_providers == ["Claude"], outcome
    print("  ✅ T2 공백만 반환한 제공자의 청크가 전송되지 않음")


def test_t3_switch_heartbeat_emitted() -> None:
    """T3 — 첫 청크 전 실패 시 전환 하트비트가 나가야 한다 (FR-03)."""
    events, outcome = _run([
        ("Claude", _fake([], raise_after=0)),
        ("OpenAI", _fake(["폴백 답변"])),
    ])
    heartbeats = [(p, t) for p, t in events if t == ""]
    assert heartbeats == [("OpenAI", "")], f"하트비트 누락/중복: {events!r}"
    assert _text(events) == "폴백 답변", events
    assert not outcome.truncated, outcome
    print("  ✅ T3 전환 구간에 빈 텍스트 하트비트 1회 발행")


def test_t4_truncation_keeps_partial_no_fallback() -> None:
    """T4 — 실질 청크 후 끊기면 폴백하지 않고 절단으로 표시한다 (FR-02)."""
    events, outcome = _run([
        ("Claude", _fake(["안녕하세요", "추가"], raise_after=1)),
        ("OpenAI", _fake(["이 답변은 사용되면 안 됨"])),
    ])
    assert _text(events) == "안녕하세요", events
    assert outcome.truncated is True, outcome
    assert outcome.provider == "Claude", outcome
    assert outcome.attempts == ["Claude"], f"절단 후 폴백이 일어남: {outcome}"
    print("  ✅ T4 절단 시 부분 응답 유지 + truncated 표시 + 폴백 미시도")


def test_t5_all_providers_fail_raises() -> None:
    """T5 — 전 제공자 실패는 RuntimeError로 명시적 실패."""
    try:
        _run([
            ("Claude", _fake([], raise_after=0)),
            ("OpenAI", _fake([], raise_after=0)),
        ])
    except RuntimeError as e:
        assert "모든 AI 서비스" in str(e), e
        print("  ✅ T5 전 제공자 실패 → RuntimeError")
        return
    raise AssertionError("전 제공자 실패인데 예외가 발생하지 않음")


def test_t6_all_providers_empty_raises() -> None:
    """T6 — 전 제공자가 빈 응답이면 조용한 성공이 아니라 실패여야 한다 (FR-01)."""
    outcome = AnswerOutcome()
    real = pipeline._answer_providers
    pipeline._answer_providers = lambda cfg: [
        ("Claude", _fake([])), ("OpenAI", _fake([""]))
    ]
    try:
        list(pipeline._stream_answer([], "", _cfg(), outcome))
    except RuntimeError:
        assert outcome.empty_providers == ["Claude", "OpenAI"], outcome
        print("  ✅ T6 전 제공자 빈 응답 → RuntimeError (조용한 빈 답변 차단)")
        return
    finally:
        pipeline._answer_providers = real
    raise AssertionError("전 제공자 빈 응답인데 빈 답변이 성공 처리됨")


def test_provider_order_and_gemini_gating() -> None:
    """제공자 순서 규약 — Gemini는 키가 있을 때만, ANSWER_PROVIDER가 1순위 지정."""
    import os
    names = [n for n, _ in pipeline._answer_providers(_cfg(gemini=True))]
    assert names == ["Claude", "OpenAI", "Gemini"], names
    names = [n for n, _ in pipeline._answer_providers(_cfg(gemini=False))]
    assert names == ["Claude", "OpenAI"], names

    prev = os.environ.get("ANSWER_PROVIDER")
    os.environ["ANSWER_PROVIDER"] = "openai"
    try:
        names = [n for n, _ in pipeline._answer_providers(_cfg(gemini=True))]
        assert names[0] == "OpenAI", names
    finally:
        if prev is None:
            os.environ.pop("ANSWER_PROVIDER", None)
        else:
            os.environ["ANSWER_PROVIDER"] = prev
    print("  ✅ 제공자 순서: Gemini 키 게이팅 + ANSWER_PROVIDER 1순위 지정")


# ── T7: 절단 대화의 저장·노출 게이팅 ──────────────────────────────────────────

def test_t7_truncated_excluded_from_board() -> None:
    """T7 — 절단 답변은 공개 게시판에서 제외된다 (FR-02)."""
    from api.index import _drop_flagged, _is_public_excluded

    rows = [
        {"id": 1, "metadata": {"has_attachments": False}},
        {"id": 2, "metadata": {"truncated": True}},
        {"id": 3, "metadata": {"guard_flag": "scope_monitor"}},
        {"id": 4, "metadata": None},
    ]
    kept = [r["id"] for r in _drop_flagged(rows)]
    assert kept == [1, 4], kept
    assert _is_public_excluded({"truncated": True})
    assert not _is_public_excluded({"has_attachments": True})
    print("  ✅ T7 truncated·guard_flag 대화가 공개 조회에서 제외")


def test_truncation_notice_and_metadata() -> None:
    """절단 시 사용자 고지가 붙고 metadata.truncated로 저장되는지 (파이프라인 통합)."""
    from app.models.session import Session
    from app.models.schemas import AnalysisResult

    saved = []

    class FakeSB:
        pass

    cfg = _cfg(gemini=False)
    cfg.supabase = FakeSB()

    prev_level = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    real_analyze = pipeline.analyze_intent
    real_providers = pipeline._answer_providers
    real_save = pipeline.save_conversation
    real_session_save = pipeline.save_session_data
    try:
        pipeline.analyze_intent = lambda *a, **kw: AnalysisResult(
            question_summary="테스트", is_labor_related=True)
        pipeline._answer_providers = lambda c: [
            ("Claude", _fake(["주휴수당은 ", "다음과"], raise_after=2)),
        ]
        pipeline.save_conversation = lambda sb, rec: saved.append(rec) or "conv-1"
        pipeline.save_session_data = lambda *a, **kw: None

        events = list(pipeline.process_question(
            "주휴수당 알려줘", Session(id="trunc1"), cfg))
        body = "".join(e.get("text", "") for e in events if e["type"] == "chunk")
        assert "중단되었습니다" in body, f"절단 고지 누락: {body!r}"
        assert "법적 효력" in body, "면책 고지가 사라짐 (D7 위반)"
        assert body.index("중단되었습니다") < body.index("법적 효력"), \
            "절단 고지가 면책 고지보다 뒤에 붙음"

        assert saved, "절단 대화가 저장되지 않음 (저장은 되어야 함)"
        meta = saved[0].metadata or {}
        assert meta.get("truncated") is True, f"metadata.truncated 누락: {meta}"
        assert meta.get("llm", {}).get("truncated") is True, f"계측 누락: {meta}"
        assert meta["llm"]["provider"] == "Claude", meta
    finally:
        pipeline.analyze_intent = real_analyze
        pipeline._answer_providers = real_providers
        pipeline.save_conversation = real_save
        pipeline.save_session_data = real_session_save
        logging.disable(prev_level)
    print("  ✅ 절단 고지 부착(면책 고지 앞) + metadata.truncated 저장")


def test_llm_meta_payload() -> None:
    """FR-10 계측 페이로드 형태."""
    meta = pipeline._llm_meta(
        AnswerOutcome(provider="OpenAI", attempts=["Claude", "OpenAI"],
                      empty_providers=["Claude"]),
        citation_fixed=False,
    )
    assert meta == {
        "provider": "OpenAI", "attempts": ["Claude", "OpenAI"],
        "empty": ["Claude"], "fallback": True, "citation_fixed": False,
    }, meta

    clean = pipeline._llm_meta(AnswerOutcome(provider="Claude", attempts=["Claude"]))
    assert clean == {"provider": "Claude", "attempts": ["Claude"]}, clean
    print("  ✅ _llm_meta: 폴백/빈응답/절단/교정 결과 기록, 정상 시 군더더기 없음")


# ── T8: 교차벤더 도구 스키마 변환 ─────────────────────────────────────────────

def test_t8_tool_schema_conversion() -> None:
    """T8 — Anthropic tool 스펙이 OpenAI function으로 무손실 변환되는지 (FR-05)."""
    from app.core.llm_fallback import anthropic_tool_to_openai, flatten_content
    from app.templates.prompts import ANALYZE_TOOL

    fn = anthropic_tool_to_openai(ANALYZE_TOOL)
    assert fn["type"] == "function"
    assert fn["function"]["name"] == ANALYZE_TOOL["name"]
    # 스키마는 복제가 아니라 동일 객체여야 한다 — 복제하면 필드 추가 시 드리프트
    assert fn["function"]["parameters"] is ANALYZE_TOOL["input_schema"]
    assert "is_labor_related" in fn["function"]["parameters"]["required"], \
        "스코프 게이트 필수 필드가 변환에서 유실됨"

    assert flatten_content("평문") == "평문"
    assert flatten_content([
        {"type": "image", "source": {}},
        {"type": "text", "text": "본문"},
    ]) == "본문"
    print("  ✅ T8 tool 스키마 무수정 변환 + 이미지 블록 탈락")


class _FakeOpenAITool:
    """tool_calls를 반환하는 최소 OpenAI 클라이언트 대역."""

    def __init__(self, arguments: dict):
        import json as _json
        self._args = _json.dumps(arguments)
        self.calls: list[dict] = []

    def with_options(self, **kw):
        self.calls.append(kw)
        return self

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, **kw):
        self.calls.append(kw)
        args = self._args

        class _Fn:
            arguments = args
        class _Call:
            function = _Fn()
        class _Msg:
            tool_calls = [_Call()]
        class _Choice:
            message = _Msg()
        class _Resp:
            choices = [_Choice()]
        return _Resp()


def test_intent_cross_vendor_fallback() -> None:
    """Claude 의도분석 실패 시 OpenAI 폴백이 실제로 결과를 채우는지 (FR-05).

    이 분기는 실장애에서만 실행되므로 테스트가 없으면 죽어 있어도 알 수 없다 —
    이 사이클의 출발점이 정확히 그 상황이었다(3순위 Gemini 404).
    """
    from app.core import analyzer

    fake = _FakeOpenAITool({
        "requires_calculation": True,
        "calculation_types": ["severance"],
        "monthly_wage": 3_000_000,
        "is_labor_related": True,
        "question_summary": "퇴직금 문의",
    })

    class Cfg:
        openai_client = fake
        analyzer_model = "claude-sonnet-5"

    prev_level = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    real = analyzer._analyze_claude
    try:
        def boom(*a, **kw):
            raise RuntimeError("Anthropic 장애 모사 (401)")
        analyzer._analyze_claude = boom
        result = analyzer.analyze_intent("퇴직금 얼마인가요?", [], Cfg())
    finally:
        analyzer._analyze_claude = real
        logging.disable(prev_level)

    assert result.requires_calculation is True, result
    assert result.calculation_types == ["severance"], result
    assert result.extracted_info.get("monthly_wage") == 3_000_000, result
    assert result.is_labor_related is True, "스코프 게이트 입력이 유실됨"
    # tool 호출이 강제됐는지 + 재시도가 꺼져 있는지
    forced = [c for c in fake.calls if c.get("tool_choice")]
    assert forced and forced[0]["tool_choice"]["function"]["name"] == "analyze_labor_question"
    assert any(c.get("max_retries") == 0 for c in fake.calls), "폴백 호출에 재시도가 살아 있음"
    print("  ✅ 교차벤더 폴백: Claude 실패 → OpenAI가 계산 유형·임금·스코프를 채움")


def test_intent_fallback_disabled_degrades() -> None:
    """INTENT_FALLBACK_ENABLED=false면 폴백 없이 예외를 전파해 레거시로 강등 (FR-05)."""
    from app.core import analyzer

    class Cfg:
        openai_client = None
        analyzer_model = "claude-sonnet-5"

    prev_level = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    real_fn, real_flag = analyzer._analyze_claude, analyzer.INTENT_FALLBACK_ENABLED
    try:
        def boom(*a, **kw):
            raise RuntimeError("Anthropic 장애 모사")
        analyzer._analyze_claude = boom
        analyzer.INTENT_FALLBACK_ENABLED = False
        try:
            analyzer.analyze_intent("퇴직금 얼마인가요?", [], Cfg())
        except RuntimeError:
            pass
        else:
            raise AssertionError("폴백 비활성인데 예외가 전파되지 않음")
    finally:
        analyzer._analyze_claude = real_fn
        analyzer.INTENT_FALLBACK_ENABLED = real_flag
        logging.disable(prev_level)
    print("  ✅ INTENT_FALLBACK_ENABLED=false → 예외 전파(레거시 경로 강등)")


def test_intent_both_vendors_fail_keeps_fail_open() -> None:
    """양쪽 벤더 실패 시 파이프라인이 fail-open으로 강등되는지 (FR-06 / P6)."""
    from app.models.session import Session
    from app.core import pipeline

    gate_calls = []

    class Cfg:
        openai_client = None
        claude_client = None
        analyzer_model = "claude-sonnet-5"

    prev_level = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    real_analyze = pipeline.analyze_intent
    real_gate = pipeline.scope_gate_decision
    try:
        def boom(*a, **kw):
            raise RuntimeError("양쪽 벤더 실패 모사")
        pipeline.analyze_intent = boom
        pipeline.scope_gate_decision = lambda *a, **kw: gate_calls.append(a) or "allow"

        from app.core.abuse_guard import GuardContext
        ctx = GuardContext(subject_key="ip:test", injection_mode="off", scope_mode="block")
        events = list(pipeline.process_question(
            "주휴수당 알려줘", Session(id="failopen1"), _cfg(gemini=False), guard_ctx=ctx))
    finally:
        pipeline.analyze_intent = real_analyze
        pipeline.scope_gate_decision = real_gate
        logging.disable(prev_level)

    # analysis is None → 게이트 skip(fail-open). 차단 메시지로 끝나지 않아야 한다.
    assert not gate_calls, "analysis 실패인데 스코프 게이트가 판정을 시도함 (fail-open 위반)"
    assert any(e["type"] in ("chunk", "error") for e in events), events
    print("  ✅ 양쪽 벤더 실패 → 스코프 게이트 skip(fail-open 유지)")


def test_analysis_result_vendor_neutral() -> None:
    """두 벤더가 같은 후처리를 통과하는지 — _build_analysis_result 단일 출처 (FR-05)."""
    from app.core.analyzer import _build_analysis_result

    inp = {
        "requires_calculation": True,
        "calculation_types": ["severance"],
        "monthly_wage": 3_000_000,
        "daily_work_hours": 999,          # 범위 밖 → 제거되어야 함
        "is_labor_related": False,
        "question_summary": "퇴직금",
    }
    result = _build_analysis_result(inp)
    assert result.extracted_info["monthly_wage"] == 3_000_000
    assert "daily_work_hours" not in result.extracted_info, "숫자 범위 검증 미적용"
    assert "1일 소정근로시간" in result.validation_warnings
    assert result.is_labor_related is False, "스코프 판정이 유실됨"

    # 필드 누락 시 fail-open (chatbot-security FR-05 규약)
    assert _build_analysis_result({}).is_labor_related is True
    print("  ✅ 벤더 중립 후처리: 숫자 검증·스코프 판정·fail-open 유지")


# ── 교정 타임아웃 ─────────────────────────────────────────────────────────────

def test_rewrite_timeout_scaling() -> None:
    """FR-07 — 교정 타임아웃이 입력 길이에 비례하고 상하한이 걸리는지."""
    from app.core.citation_validator import _rewrite_timeout

    assert _rewrite_timeout(100) == 12.0, "하한 미적용"
    assert _rewrite_timeout(100_000) == 40.0, "상한 미적용"
    # 실측 기준선: 1,960자 재생성에 7.7초 → 타임아웃은 그보다 커야 한다
    assert _rewrite_timeout(1960) > 7.7, "실측 소요보다 짧은 타임아웃"
    assert _rewrite_timeout(6000) > _rewrite_timeout(2000), "길이 비례 아님"
    print("  ✅ 교정 타임아웃: 길이 비례 + [12, 40]초 클램프")


def test_citation_stage_budget() -> None:
    """FR-07 — 단계 예산이 소진되면 남은 제공자를 호출하지 않는지."""
    import time
    from app.core import citation_validator as cv

    calls = []

    class Exploding:
        def __getattr__(self, name):
            calls.append(name)
            raise AssertionError(f"예산 소진 후 호출 발생: {name}")

    prev_level = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    try:
        result = cv.correct_hallucinated_citations(
            response_text="원본 답변", hallucinated=["2023다1234"],
            anthropic_client=Exploding(), gemini_api_key="fake",
            openai_client=Exploding(),
            deadline=time.monotonic() - 1,     # 이미 소진된 예산
        )
    finally:
        logging.disable(prev_level)
    assert result is None, result
    assert not calls, f"예산 소진 후에도 제공자를 호출함: {calls}"
    print("  ✅ 교정 단계 예산 소진 시 전 제공자 생략")


def main() -> None:
    test_t1_empty_first_provider_falls_back()
    test_t2_whitespace_only_not_leaked()
    test_t3_switch_heartbeat_emitted()
    test_t4_truncation_keeps_partial_no_fallback()
    test_t5_all_providers_fail_raises()
    test_t6_all_providers_empty_raises()
    test_provider_order_and_gemini_gating()
    test_t7_truncated_excluded_from_board()
    test_truncation_notice_and_metadata()
    test_llm_meta_payload()
    test_t8_tool_schema_conversion()
    test_intent_cross_vendor_fallback()
    test_intent_fallback_disabled_degrades()
    test_intent_both_vendors_fail_keeps_fail_open()
    test_analysis_result_vendor_neutral()
    test_rewrite_timeout_scaling()
    test_citation_stage_budget()
    print("\n✅ LLM 폴백 경화 테스트 전부 통과")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\n❌ 실패: {e}")
        sys.exit(1)
