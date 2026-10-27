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

    # 기본 순서 검증은 환경에 ANSWER_PROVIDER가 없어야 성립한다 — CI나 개발 셸에
    # 값이 남아 있으면 코드 결함 없이 실패하므로 테스트 전체를 격리한다.
    prev = os.environ.pop("ANSWER_PROVIDER", None)
    try:
        names = [n for n, _ in pipeline._answer_providers(_cfg(gemini=True))]
        assert names == ["Claude", "OpenAI", "Gemini"], names
        names = [n for n, _ in pipeline._answer_providers(_cfg(gemini=False))]
        assert names == ["Claude", "OpenAI"], names

        os.environ["ANSWER_PROVIDER"] = "openai"
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
            name = "analyze_labor_question"
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


class _ClaudeRaises:
    """messages.create가 항상 실패하는 Anthropic 클라이언트 대역(장애 모사)."""

    def with_options(self, **kw):
        return self

    @property
    def messages(self):
        return self

    def create(self, **kw):
        raise RuntimeError("Anthropic 장애 모사 (400 usage limit)")


class _Exploding:
    """어떤 속성에 닿아도 실패 — '호출되면 안 되는 제공자' 단언용."""

    def __init__(self, calls: list | None = None):
        self._calls = calls if calls is not None else []

    def __getattr__(self, name):
        self._calls.append(name)
        raise AssertionError(f"호출되면 안 되는 제공자에 접근: {name}")


def _with_primary(primary: str | None):
    """model_settings.resolve()를 고정한다 — 저장소(Supabase) 없이 1순위를 지정."""
    from contextlib import contextmanager
    from app.core import model_settings as ms

    @contextmanager
    def ctx():
        real = ms.resolve
        ms.resolve = lambda settings=None: ms.Resolved(
            models={"claude": ("claude-opus-5-5", "settings"), "openai": ("gpt-6-sol", "settings"),
                    "gemini": ("gemini-3.8-flash", "settings")},
            primary=(primary, "settings"), revision=None, store_available=True)
        try:
            yield
        finally:
            ms.resolve = real
    return ctx()


def _quiet():
    from contextlib import contextmanager

    @contextmanager
    def ctx():
        prev = logging.getLogger().manager.disable
        logging.disable(logging.CRITICAL)
        try:
            yield
        finally:
            logging.disable(prev)
    return ctx()


def test_intent_cross_vendor_fallback() -> None:
    """1순위(Claude) 의도분석 실패 시 2순위(OpenAI)가 실제로 결과를 채우는지 (FR-05).

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
        claude_client = _ClaudeRaises()
        openai_client = fake
        gemini_api_key = None

    with _quiet(), _with_primary("claude"):
        result = analyzer.analyze_intent("퇴직금 얼마인가요?", [], Cfg())

    assert result.requires_calculation is True, result
    assert result.calculation_types == ["severance"], result
    assert result.extracted_info.get("monthly_wage") == 3_000_000, result
    assert result.is_labor_related is True, "스코프 게이트 입력이 유실됨"
    assert result.intent_provider == "OpenAI", result.intent_provider
    # tool 호출이 강제됐는지 + 재시도가 꺼져 있는지 + 설정 모델을 썼는지
    forced = [c for c in fake.calls if c.get("tool_choice")]
    assert forced and forced[0]["tool_choice"]["function"]["name"] == "analyze_labor_question"
    assert forced[0]["model"] == "gpt-6-sol", forced[0]["model"]
    assert any(c.get("max_retries") == 0 for c in fake.calls), "폴백 호출에 재시도가 살아 있음"
    print("  ✅ 교차벤더 폴백: 1순위 실패 → 2순위(설정 모델)가 계산 유형·임금·스코프를 채움")


def test_intent_empty_tool_response_falls_back() -> None:
    """1순위가 tool_use 없이 완료해도 폴백해야 한다 (CodeRabbit #4).

    _stream_answer의 FR-01("빈 응답은 실패다")과 같은 규약이다. 예외 없이 None을
    돌려주면 호출부의 except를 못 타서 2순위 폴백이 통째로 생략됐다.
    """
    from app.core import analyzer

    fake = _FakeOpenAITool({
        "requires_calculation": True,
        "calculation_types": ["annual_leave"],
        "is_labor_related": True,
        "question_summary": "연차 문의",
    })

    class _EmptyResp:
        content = ()          # tool_use 블록 없음 (불변 — RUF012)

    class _EmptyClaude:
        def with_options(self, **kw):
            return self

        @property
        def messages(self):
            return self

        def create(self, **kw):
            return _EmptyResp()

    class Cfg:
        claude_client = _EmptyClaude()
        openai_client = fake
        gemini_api_key = None

    with _quiet(), _with_primary("claude"):
        result = analyzer.analyze_intent("연차 며칠인가요?", [], Cfg())

    assert result.calculation_types == ["annual_leave"], \
        f"빈 tool 응답에서 폴백이 생략됨: {result}"
    assert result.intent_provider == "OpenAI", result.intent_provider
    print("  ✅ 빈 tool 응답(tool_use 없음) → 2순위 폴백 발동")


def test_intent_fallback_disabled_degrades() -> None:
    """INTENT_FALLBACK_ENABLED=false면 폴백 없이 예외를 전파해 레거시로 강등 (FR-05)."""
    from app.core import analyzer

    touched: list = []

    class Cfg:
        claude_client = _ClaudeRaises()
        openai_client = _Exploding(touched)
        gemini_api_key = None

    real_flag = analyzer.INTENT_FALLBACK_ENABLED
    try:
        analyzer.INTENT_FALLBACK_ENABLED = False
        with _quiet(), _with_primary("claude"):
            try:
                analyzer.analyze_intent("퇴직금 얼마인가요?", [], Cfg())
            except RuntimeError:
                pass
            else:
                raise AssertionError("폴백 비활성인데 예외가 전파되지 않음")
    finally:
        analyzer.INTENT_FALLBACK_ENABLED = real_flag
    assert not touched, f"폴백 비활성인데 2순위를 호출함: {touched}"
    print("  ✅ INTENT_FALLBACK_ENABLED=false → 예외 전파(레거시 경로 강등)")


def test_primary_setting_drives_every_stage() -> None:
    """1순위를 바꾸면 답변과 보조 단계가 같은 순서·같은 모델을 쓴다 (unified-model-provider).

    2026-10-11 실측: 1순위를 Gemini로 바꿔도 의도분석·추출·Self-RAG·인용 교정이 Claude에 고정돼
    Anthropic 한도 400에 그대로 묶였다. 순서를 두 곳에서 따로 정하면 그 갈라짐이 다시 생긴다.
    """
    from app.core import analyzer, llm_gateway, self_rag

    fake = _FakeOpenAITool({"requires_calculation": False, "is_labor_related": True,
                            "question_summary": "해고 문의"})

    class Cfg:
        claude_client = _Exploding()
        openai_client = fake
        gemini_api_key = "fake-key"

    with _quiet(), _with_primary("openai"):
        answer_order = [n for n, _ in pipeline._answer_providers(Cfg())]
        chain = llm_gateway.provider_chain(Cfg())
        result = analyzer.analyze_intent("해고됐어요", [], Cfg())
    assert answer_order == ["OpenAI", "Claude", "Gemini"], answer_order
    assert [llm_gateway.PROVIDER_LABEL[p] for p, _ in chain] == answer_order, chain
    assert result.intent_provider == "OpenAI", result.intent_provider

    # Gemini 1순위: 텍스트 단계(Self-RAG)가 Gemini 어댑터로 가고 Claude는 건드리지 않는다
    seen = []
    real = llm_gateway._TEXT["gemini"]
    llm_gateway._TEXT["gemini"] = lambda cfg, model, system, user, mt, to: seen.append(model) or "irrelevant"
    try:
        with _quiet(), _with_primary("gemini"):
            assert self_rag.judge_relevance("질문", "문서", Cfg()) is False
    finally:
        llm_gateway._TEXT["gemini"] = real
    assert seen == ["gemini-3.8-flash"], seen
    print("  ✅ 설정 1순위가 답변·의도분석·Self-RAG 순서와 모델을 함께 결정")


def test_gateway_vendor_quirks() -> None:
    """벤더별 함정 회귀 — 토큰 하한·재작성 거부 시 다음 순위·데드라인·정수 복원·추론 off 재시도."""
    import time
    from app.core import llm_gateway as gw

    # ① 작은 max_tokens도 하한으로 올린다(추론 토큰이 한도를 함께 써 빈 응답이 났다)
    sent = {}

    class _OAI:
        def with_options(self, **kw):
            return self

        @property
        def chat(self):
            return self

        @property
        def completions(self):
            return self

        def create(self, **kw):
            sent.update(kw)

            class _M:
                content = "relevant"

            class _C:
                message = _M()

            class _R:
                choices = [_C()]
            return _R()

    class Cfg:
        claude_client = None
        openai_client = _OAI()
        gemini_api_key = None

    with _quiet(), _with_primary("openai"):
        out, label = gw.text(Cfg(), system=None, user="q", purpose="t", max_tokens=10, timeout=5)
    assert (out, label) == ("relevant", "OpenAI")
    assert sent["max_completion_tokens"] >= 4096, sent
    assert "temperature" not in sent, "temperature는 Claude 5·추론 모델이 거부한다"

    # ② accept 거부 → 다음 순위, ③ 데드라인 소진 → 호출 없음
    calls = []
    real = dict(gw._TEXT)
    gw._TEXT["gemini"] = lambda *a: calls.append("gemini") or "짧음"
    gw._TEXT["openai"] = lambda *a: calls.append("openai") or "충분히 긴 재작성"

    class Cfg2:
        claude_client = None
        openai_client = object()
        gemini_api_key = "k"
    try:
        with _quiet(), _with_primary("gemini"):
            out, label = gw.text(Cfg2(), system=None, user="q", purpose="t", attempts=None,
                                 accept=lambda t: len(t) > 5)
            assert label == "OpenAI" and calls == ["gemini", "openai"], (label, calls)
            calls.clear()
            try:
                gw.text(Cfg2(), system=None, user="q", purpose="t", attempts=None,
                        deadline=time.monotonic() - 1)
            except gw.LLMUnavailable:
                pass
            assert not calls, calls
    finally:
        gw._TEXT.update(real)

    # ④ Gemini 함수 호출의 실수 → 스키마 integer는 정수로
    schema = {"type": "object", "properties": {
        "days": {"type": "integer"}, "wage": {"type": "number"},
        "items": {"type": "array", "items": {"type": "integer"}}}}
    got = gw._coerce({"days": 3.0, "wage": 2500000.0, "items": [1.0, 2.0]}, schema)
    assert got == {"days": 3, "wage": 2500000.0, "items": [1, 2]}, got
    assert isinstance(got["days"], int) and isinstance(got["wage"], float)

    # ⑤ gpt-6-sol: function tool + 추론 400 → reasoning_effort='none'으로 재시도하고 기억
    attempts = []

    class _OAITool(_FakeOpenAITool):
        def create(self, **kw):
            attempts.append(kw.get("reasoning_effort"))
            if kw.get("reasoning_effort") != "none":
                raise RuntimeError("Function tools with reasoning_effort are not supported "
                                   "... set reasoning_effort to 'none'.")
            return super().create(**kw)

    class Cfg3:
        claude_client = None
        openai_client = _OAITool({"question_summary": "x", "is_labor_related": True})
        gemini_api_key = None
    gw._OPENAI_TOOL_NEEDS_NO_REASONING.discard("gpt-6-sol")
    from app.templates.prompts import ANALYZE_TOOL
    with _quiet(), _with_primary("openai"):
        for _ in range(2):
            gw.tool(Cfg3(), system="s", messages=[{"role": "user", "content": "q"}],
                    tools=[ANALYZE_TOOL], choice=ANALYZE_TOOL["name"], purpose="t")
    assert attempts == [None, "none", "none"], attempts
    print("  ✅ 게이트웨이: 토큰 하한·temperature 미전송·거부/데드라인·정수 복원·추론 off 재시도")


def test_llm_meta_intent_vs_primary() -> None:
    """의도분석 폴백 기록은 '1순위가 아닌 제공자'일 때만 — 1순위를 바꾸면 그 제공자가 정상이다."""
    ok = pipeline._llm_meta(AnswerOutcome(provider="Gemini", attempts=["Gemini"]),
                            intent_provider="Gemini")
    assert "intent_provider" not in ok, ok
    fb = pipeline._llm_meta(AnswerOutcome(provider="Gemini", attempts=["Gemini"]),
                            intent_provider="Claude")
    assert fb["intent_provider"] == "Claude", fb
    print("  ✅ _llm_meta: 의도분석 폴백 판정 기준 = 답변 1순위 제공자")


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

def test_notices_survive_citation_correction() -> None:
    """교정 결과가 절단·면책 고지를 떨어뜨려도 복원되는지 (CodeRabbit #8).

    교정은 답변 전문을 외부 LLM에 재생성시키므로 말미 고지가 탈락할 수 있다.
    그대로 replace로 내보내면 사용자가 이미 받은 고지가 사라진다.
    """
    from app.core.pipeline import (
        _ensure_notices, DISCLAIMER, DISCLAIMER_MARK,
        TRUNCATED_MARK, TRUNCATED_NOTICE,
    )

    def _ordered(text: str) -> bool:
        return text.index(TRUNCATED_MARK) < text.index(DISCLAIMER_MARK)

    # ① 두 고지가 모두 탈락한 경우
    restored = _ensure_notices("교정된 본문만 남고 말미 고지가 사라진 상태", truncated=True)
    assert TRUNCATED_MARK in restored, "절단 고지가 복원되지 않음"
    assert DISCLAIMER_MARK in restored, "면책 고지가 복원되지 않음"
    assert _ordered(restored), "복원 순서가 원본(절단 → 면책)과 다름"

    # ② 면책 고지만 살아남은 경우 — 단순 append면 절단이 뒤에 붙어 역순이 된다
    only_disclaimer = _ensure_notices("교정된 본문" + DISCLAIMER, truncated=True)
    assert _ordered(only_disclaimer), f"면책만 남은 입력에서 순서 역전: {only_disclaimer[-80:]!r}"
    assert only_disclaimer.count(DISCLAIMER_MARK) == 1, "면책 고지 중복"

    # ③ 절단 고지만 살아남은 경우
    only_truncated = _ensure_notices("교정된 본문" + TRUNCATED_NOTICE, truncated=True)
    assert _ordered(only_truncated), only_truncated[-80:]
    assert only_truncated.count(TRUNCATED_MARK) == 1, "절단 고지 중복"

    # ④ 멱등 — 여러 번 통과시켜도 같은 결과
    assert _ensure_notices(restored, truncated=True) == restored, "고지가 중복 부착됨"

    # ⑤ 절단이 아니면 절단 고지는 붙이지 않는다
    normal = _ensure_notices("정상 답변", truncated=False)
    assert TRUNCATED_MARK not in normal and DISCLAIMER_MARK in normal, normal

    # ⑥ LLM이 자체 면책 고지를 쓴 경우 우리 고지를 중복 부착하지 않는다
    #    (시스템 프롬프트가 면책 고지 작성을 지시하므로 실제로 흔한 경우다)
    llm_own = _ensure_notices("본문\n\n⚠️ 본 답변은 참고용이며 법적 효력이 없습니다.", truncated=False)
    assert llm_own.count(DISCLAIMER_MARK) == 1, f"면책 고지 중복 부착: {llm_own!r}"
    print("  ✅ 교정 후 고지 정규화(부분 잔존·역순·중복·멱등 전부 처리)")


def test_rewrite_guard_rejects_empty_and_short() -> None:
    """교정 결과 검증이 전 제공자에 균일 적용되는지 (CodeRabbit #6).

    공백만 반환한 제공자를 성공으로 처리하면 replace 이벤트가 완성된 답변을
    통째로 지운다 — 빈 응답은 다음 제공자로 넘겨야 한다.
    """
    from app.core.citation_validator import _is_valid_rewrite

    original = "가" * 1000
    assert not _is_valid_rewrite("", original), "빈 문자열이 통과"
    assert not _is_valid_rewrite(None, original), "None이 통과"
    assert not _is_valid_rewrite("   \n  ".strip(), original), "공백만이 통과"
    assert not _is_valid_rewrite("가" * 500, original), "본문 절반 유실이 통과"
    assert _is_valid_rewrite("가" * 950, original), "정상 교정이 거부됨"
    print("  ✅ 교정 결과 가드: 빈 응답·공백·과도 축소 거부(전 제공자 공통)")


def test_rewrite_timeout_scaling() -> None:
    """FR-07 — 교정 타임아웃이 입력 길이에 비례하고 상하한이 걸리는지."""
    from app.core.citation_validator import _rewrite_timeout

    assert _rewrite_timeout(100) == 15.0, "하한 미적용"
    assert _rewrite_timeout(100_000) == 40.0, "상한 미적용"
    # 실측 기준선: 1,960자 Haiku 7.7초, 1,596자 gemini-3.8-flash 11.1초 → 타임아웃은 그보다 커야 한다
    assert _rewrite_timeout(1960) > 7.7, "실측 소요보다 짧은 타임아웃"
    assert _rewrite_timeout(1596) > 11.1, "Gemini 실측 소요보다 짧은 타임아웃"
    assert _rewrite_timeout(6000) > _rewrite_timeout(2000), "길이 비례 아님"
    print("  ✅ 교정 타임아웃: 길이 비례 + [15, 40]초 클램프")


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
        class Cfg:
            claude_client = Exploding()
            openai_client = Exploding()
            gemini_api_key = "fake"

        result = cv.correct_hallucinated_citations(
            response_text="원본 답변", hallucinated=["대법원 2023다1234"],
            config=Cfg(),
            deadline=time.monotonic() - 1,     # 이미 소진된 예산
        )
    finally:
        logging.disable(prev_level)
    assert result is None, result
    assert not calls, f"예산 소진 후에도 제공자를 호출함: {calls}"
    print("  ✅ 교정 단계 예산 소진 시 전 제공자 생략")


def test_gemini_stream_idle_not_total_deadline() -> None:
    """Gemini 스트림은 '전체 마감'이 아니라 '청크 사이 무응답'으로 끊는다(2026-10-11 생성 중단 18%)."""
    import time as _t
    from app.core import pipeline as pl

    def slow(n, gap):
        def gen():
            for i in range(n):
                _t.sleep(gap)
                yield f"c{i}"
        return gen

    # 총 0.5초 > idle 0.3초여도 청크 간격(0.1초)이 짧으면 끝까지 받는다
    assert list(pl._iter_with_idle_timeout(slow(5, 0.1), 0.3)) == [f"c{i}" for i in range(5)]
    # 간격이 idle을 넘으면 TimeoutError — 받은 청크는 그 전까지 그대로 나간다
    got = []
    try:
        for c in pl._iter_with_idle_timeout(slow(3, 0.4), 0.2):
            got.append(c)
        raise AssertionError("무응답인데 TimeoutError가 나지 않았다")
    except TimeoutError:
        pass
    assert got == [], got
    # SDK 예외는 그대로 올라온다(절단·폴백 판정이 예외 종류를 본다)
    def boom():
        yield "a"
        raise ValueError("sdk")
    got = []
    try:
        for c in pl._iter_with_idle_timeout(boom, 1.0):
            got.append(c)
        raise AssertionError("SDK 예외가 삼켜졌다")
    except ValueError:
        pass
    assert got == ["a"], got
    # 소비자가 시간 초과로 떠나면 생산 스레드도 다음 청크에서 멈춘다(버려진 스트림이 마감까지 쌓이지 않게)
    pulled = []
    def late():
        _t.sleep(0.3)
        for i in range(50):
            pulled.append(i)
            yield f"x{i}"
            _t.sleep(0.01)
    try:
        list(pl._iter_with_idle_timeout(late, 0.1))
        raise AssertionError("무응답인데 TimeoutError가 나지 않았다")
    except TimeoutError:
        pass
    _t.sleep(0.5)
    assert len(pulled) <= 2, f"소비자 종료 후에도 {len(pulled)}청크를 더 끌어왔다"
    # SDK 마감은 답변 길이를 감당해야 한다 — 읽기 한도와 같은 값으로 두면 긴 답변이 전부 잘린다
    assert pl.GEMINI_STREAM_DEADLINE >= 120, pl.GEMINI_STREAM_DEADLINE
    print("  ✅ Gemini 스트림: 전체 마감 아닌 청크 간 무응답으로 판정")


def test_claude_forced_tool_choice_rejected_falls_back_to_auto() -> None:
    """Claude 5.5 세대(opus·sonnet)는 강제 tool_choice(any/tool)를 400으로 거절한다 — auto+지시로 자가치유.

    2026-10-27 실측: rev 13(Claude 1순위)에서 의도분석·파라미터 추출이 매 질문 400
    `tool_choice: type "tool" and "any" are not supported for this model` → OpenAI 폴백. 수정 뒤에는
    ① 그 400이면 auto + 도구 호출 지시 + effort low로 한 번 더 보내고 모델별로 기억한다(다음 호출은 바로 auto)
    ② 다른 400(잔액·한도)과 400이 아닌 예외는 그대로 전파해 다음 제공자로 넘어간다 ③ 강제가 통하는 모델(haiku)은 종전과 같다.
    """
    from app.core import llm_gateway as gw
    from app.templates.prompts import ANALYZE_TOOL

    class _Block:
        type = "tool_use"
        name = ANALYZE_TOOL["name"]
        input = {"question_summary": "x", "is_labor_related": True}

    class _Resp:
        stop_reason = "tool_use"
        content = [_Block()]

    class _Bad(RuntimeError):
        """anthropic.BadRequestError처럼 status_code를 가진 400 대역."""
        status_code = 400

    class _Claude:
        """강제 tool_choice는 400, auto는 성공하는 Anthropic 대역."""

        def __init__(self, reject_forced: bool = True, error: str | None = None, error_cls=None):
            self.calls: list[dict] = []
            self.reject_forced = reject_forced
            self.error = error
            self.error_cls = error_cls or _Bad

        def with_options(self, **kw):
            return self

        @property
        def messages(self):
            return self

        def create(self, **kw):
            self.calls.append(kw)
            if self.error:
                raise self.error_cls(self.error)
            if self.reject_forced and kw["tool_choice"]["type"] in ("any", "tool"):
                raise _Bad('Error code: 400 - {"type": "error", "error": {"type": "invalid_request_error", '
                           '"message": "tool_choice: type \\"tool\\" and \\"any\\" are not supported for this model."}}')
            return _Resp()

    def cfg(client):
        class Cfg:
            claude_client = client
            openai_client = _Exploding()
            gemini_api_key = None
        return Cfg()

    msgs = [{"role": "user", "content": "q"}]
    # ① 거절 → auto 재시도, 기억
    gw._CLAUDE_TOOL_NO_FORCE.discard("claude-opus-5-5")
    fake = _Claude()
    with _quiet(), _with_primary("claude"):
        label, name, inp = gw.tool(cfg(fake), system="s", messages=msgs, tools=[ANALYZE_TOOL],
                                   choice=ANALYZE_TOOL["name"], purpose="t")
        assert (label, name, inp["is_labor_related"]) == ("Claude", ANALYZE_TOOL["name"], True)
        assert [c["tool_choice"]["type"] for c in fake.calls] == ["tool", "auto"], fake.calls
        auto = fake.calls[-1]
        assert auto["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}, auto["tool_choice"]
        assert ANALYZE_TOOL["name"] in auto["system"] and auto["system"].startswith("s"), auto["system"]
        assert auto["output_config"] == {"effort": "low"}, auto.get("output_config")
        assert "output_config" not in fake.calls[0], "강제 경로는 종전과 같아야 한다"
        assert "claude-opus-5-5" in gw._CLAUDE_TOOL_NO_FORCE
        # 두 번째 호출은 실패 호출 없이 바로 auto
        fake2 = _Claude()
        gw.tool(cfg(fake2), system=None, messages=msgs, tools=[ANALYZE_TOOL], choice=None, purpose="t")
        assert [c["tool_choice"]["type"] for c in fake2.calls] == ["auto"], fake2.calls
        assert "목록" in fake2.calls[0]["system"], fake2.calls[0]["system"]   # choice=None → 목록 중 하나
    # ② 다른 400은 전파 — 다음 제공자(여기선 폭발 대역)로 넘어가 LLMUnavailable
    gw._CLAUDE_TOOL_NO_FORCE.discard("claude-opus-5-5")
    broke = _Claude(error="Error code: 400 - credit balance is too low")
    with _quiet(), _with_primary("claude"):
        try:
            gw.tool(cfg(broke), system="s", messages=msgs, tools=[ANALYZE_TOOL], choice=None, purpose="t", attempts=1)
        except gw.LLMUnavailable:
            pass
        else:
            raise AssertionError("잔액 400을 auto 재시도로 삼키면 안 된다")
    assert len(broke.calls) == 1 and "claude-opus-5-5" not in gw._CLAUDE_TOOL_NO_FORCE
    # ②' 같은 문구라도 400이 아니면(5xx 본문·네트워크 오류) auto로 전환하지 않는다(CodeRabbit #142)
    class _Server(RuntimeError):
        status_code = 529
    not400 = _Claude(error='overloaded: tool_choice ... not supported (upstream)', error_cls=_Server)
    with _quiet(), _with_primary("claude"):
        try:
            gw.tool(cfg(not400), system="s", messages=msgs, tools=[ANALYZE_TOOL], choice=None, purpose="t", attempts=1)
        except gw.LLMUnavailable:
            pass
    assert len(not400.calls) == 1 and "claude-opus-5-5" not in gw._CLAUDE_TOOL_NO_FORCE
    assert not gw._is_forced_tool_choice_rejection(RuntimeError("tool_choice: not supported"))   # status_code 없음
    # ③ 강제가 통하면 단일 호출, 지시 접미 없음
    ok = _Claude(reject_forced=False)
    with _quiet(), _with_primary("claude"):
        gw.tool(cfg(ok), system="s", messages=msgs, tools=[ANALYZE_TOOL], choice=ANALYZE_TOOL["name"], purpose="t")
    assert len(ok.calls) == 1 and ok.calls[0]["tool_choice"] == {"type": "tool", "name": ANALYZE_TOOL["name"]}
    assert ok.calls[0]["system"] == "s"
    print("  ✅ Claude 강제 tool_choice 거절(400+문구) → auto+지시 자가치유·기억, 다른 400·비400 전파, 강제 가능 모델 불변")


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
    test_intent_empty_tool_response_falls_back()
    test_intent_fallback_disabled_degrades()
    test_primary_setting_drives_every_stage()
    test_gateway_vendor_quirks()
    test_claude_forced_tool_choice_rejected_falls_back_to_auto()
    test_llm_meta_intent_vs_primary()
    test_intent_both_vendors_fail_keeps_fail_open()
    test_analysis_result_vendor_neutral()
    test_notices_survive_citation_correction()
    test_rewrite_guard_rejects_empty_and_short()
    test_rewrite_timeout_scaling()
    test_citation_stage_budget()
    test_gemini_stream_idle_not_total_deadline()
    print("\n✅ LLM 폴백 경화 테스트 전부 통과")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\n❌ 실패: {e}")
        sys.exit(1)
