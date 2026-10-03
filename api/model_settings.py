"""관리자 — 답변 모델 설정 (admin-model-settings).

저장 게이트는 **서버가 강제한다**: 화면에서 버튼을 막는 것은 편의일 뿐이고, PUT은
테스트 호출 통과 시 발급한 서명 토큰이 없으면 변경된 모델을 거절한다.
테스트 호출은 별도 코드가 아니라 **답변 경로의 스트리밍 함수 그대로**다 — 테스트용
호출을 따로 두면 실제 호출 방식과 어긋난다(9-27 SDK 1.x 사고가 타임아웃 인자 하나로 났다).
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.core import model_settings as ms

logger = logging.getLogger(__name__)

# 테스트 호출은 **실제 답변과 같은 크기**로 보낸다. 짧은 프롬프트로는 claude-opus-5-5가 1~2초에
# 통과했지만, 실제 답변(시스템 프롬프트 + 참고 자료 3~4천 자)에서는 첫 토큰까지 20초를 넘겨
# 타임아웃 → 전 답변이 o3로 폴백됐다(2026-10-02 실측). 첫 실질 텍스트가 오면 바로 멈추므로
# 비용은 입력 토큰 수천 개뿐이다.
TEST_CONTEXT_CHARS = 4000       # 프로덕션 로그 'LLM 컨텍스트 3170~3974자'
SLOW_RATIO = 0.5                # 첫 응답이 답변 대기 한도의 절반을 넘으면 경고
_TEST_PARAGRAPH = (
    "근로기준법 제55조 제1항은 사용자가 근로자에게 1주에 평균 1회 이상의 유급휴일을 보장하도록 정한다. "
    "같은 법 시행령 제30조는 1주 동안의 소정근로일을 개근한 자에게 주휴일을 주도록 하고, 제18조 제3항은 "
    "4주 동안을 평균하여 1주 동안의 소정근로시간이 15시간 미만인 근로자에게는 이를 적용하지 않는다. "
    "단시간근로자의 근로조건은 통상근로자의 근로시간을 기준으로 산정한 비율에 따라 결정한다. ")


def test_messages() -> tuple[str, str]:
    """(system, user) — 답변 경로와 같은 조립 순서·비슷한 크기."""
    from datetime import date
    from app.templates.prompts import (ANSWER_ACCURACY_RULES, CONSULTATION_SYSTEM_PROMPT,
                                       INJECTION_RESISTANCE, WAGE_CALC_RULES)
    system = (CONSULTATION_SYSTEM_PROMPT.format(today=date.today().isoformat())
              + INJECTION_RESISTANCE + WAGE_CALC_RULES + ANSWER_ACCURACY_RULES)
    context = (_TEST_PARAGRAPH * (TEST_CONTEXT_CHARS // len(_TEST_PARAGRAPH) + 1))[:TEST_CONTEXT_CHARS]
    # 질문도 실제 상담처럼 추론이 필요한 것으로 둔다 — "한 문장으로 답하라"는 추론을 거의 유발하지 않아
    # 첫 응답 시간을 과소 측정한다(실측: opus-5-5 테스트 4.6초 vs 실제 질문 24.7초).
    user = (f"참고 자료:\n\n{context}\n\n---\n\n질문: 주 3일, 하루 6시간 일하는 아르바이트입니다. "
            "이번 주는 월~수만 일했는데 주휴수당을 받을 수 있나요? 요건과 계산 방법을 법적 근거와 함께 알려주세요.")
    return system, user
TEST_RATE = (10, 60.0)          # 10회 / 60초 (인스턴스별 베스트에포트)


class TestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(max_length=20)
    model: str = Field(max_length=100)


class SaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: StrictInt = Field(ge=0)
    primary: str | None = Field(default=None, max_length=20)
    models: dict = Field(default_factory=dict)


class ResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: StrictInt = Field(ge=0)


def run_test_call(stream_fn, config, model: str, system: str | None = None,
                  user: str | None = None) -> tuple[bool, str, int]:
    """(ok, sample 또는 오류 요약, 첫 응답까지 ms). 실질 텍스트 1자 이상이면 통과 —
    _stream_answer의 '빈 응답은 실패' 규약과 같은 기준이다. 첫 실질 텍스트에서 멈추므로
    측정값은 곧 **첫 응답 시간(TTFT)**이고, 답변 대기 한도를 넘으면 스트림 자체가 타임아웃으로
    실패한다 — 프로덕션과 같은 판정이다."""
    if system is None or user is None:
        system, user = test_messages()
    start = time.monotonic()
    got = ""
    try:
        for chunk in stream_fn([{"role": "user", "content": user}], system, config,
                               model=model):
            got += chunk
            if got.strip():
                break
    except Exception as e:  # noqa: BLE001 — 벤더 오류를 그대로 요약해 돌려준다
        return False, f"{type(e).__name__}: {str(e)[:200]}", int((time.monotonic() - start) * 1000)
    latency = int((time.monotonic() - start) * 1000)
    if not got.strip():
        return False, "빈 응답(실질 0자) — 답변 경로에서 폴백되는 모델입니다", latency
    return True, got.strip()[:40], latency


def build_model_router(require_admin, config_factory, secret: str, stream_fns: dict):
    """stream_fns: {"claude": pipeline._stream_claude, ...} — 순환 import를 피하려 주입받는다."""
    router = APIRouter(prefix="/api/admin/model-settings", tags=["model-settings"])
    calls: deque = deque()
    lock = threading.Lock()

    def check_provider(provider: str, config) -> None:
        if provider not in ms.PROVIDERS:
            raise HTTPException(400, f"알 수 없는 제공자: {provider}")
        if provider == "gemini" and not config.gemini_api_key:
            raise HTTPException(400, "Gemini API 키가 설정되지 않았습니다")

    @router.get("")
    def state(admin=Depends(require_admin)):
        settings, revision, ok = ms.load(force=True)
        resolved = ms.resolve(settings)
        config = config_factory()
        stored = settings.get("models") if isinstance(settings.get("models"), dict) else {}  # R-6
        providers = {}
        for p in ms.PROVIDERS:
            model, source = resolved.models[p]
            entry = stored.get(p) if isinstance(stored.get(p), dict) else {}
            providers[p] = {"model": model, "source": source,
                            "available": p != "gemini" or bool(config.gemini_api_key),
                            "tested_at": entry.get("tested_at")}
        return {"revision": revision, "store_available": ok,
                "primary": {"value": resolved.primary[0], "source": resolved.primary[1]},
                "providers": providers, "events": ms.recent_events() if ok else []}

    @router.get("/models")
    def models(provider: str = Query(max_length=20), admin=Depends(require_admin)):
        config = config_factory()
        check_provider(provider, config)
        try:
            raw = ms.fetch_raw_models(provider, config)
        except ms.SettingsError as e:
            raise HTTPException(400, str(e)) from e
        except Exception as e:  # noqa: BLE001
            logger.warning("%s 모델 목록 조회 실패: %s", provider, e)
            raise HTTPException(502, "모델 목록을 불러오지 못했습니다") from e
        current = ms.resolve().models[provider][0]
        return {"provider": provider, "models": ms.select_latest(provider, raw, current)}

    @router.post("/test")
    def test(req: TestRequest, admin=Depends(require_admin)):
        config = config_factory()
        check_provider(req.provider, config)
        if not ms.MODEL_ID_RE.match(req.model):
            raise HTTPException(400, "모델 ID 형식이 올바르지 않습니다")
        now = time.monotonic()
        with lock:
            while calls and now - calls[0] > TEST_RATE[1]:
                calls.popleft()
            if len(calls) >= TEST_RATE[0]:
                raise HTTPException(429, "테스트 호출이 너무 잦습니다. 잠시 후 다시 시도하세요")
            calls.append(now)
        # 목록 소속 확인(FR-09) — 호출 전에 막아 비용이 들지 않는다. 오타·낡은 이름 차단.
        try:
            raw = ms.fetch_raw_models(req.provider, config)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, "모델 목록을 불러오지 못해 검증할 수 없습니다") from e
        known = {m["id"].removeprefix("models/") for m in raw}
        if req.model not in known:
            raise HTTPException(422, f"{req.model}: 제공자 목록에 없는 모델입니다")
        ok, detail, latency = run_test_call(stream_fns[req.provider], config, req.model)
        logger.info("답변 모델 테스트 provider=%s model=%s ok=%s ttft=%dms", req.provider, req.model, ok, latency)
        if not ok:
            raise HTTPException(422, f"테스트 호출 실패 — {detail}")
        from app.config import ANSWER_READ_TIMEOUT
        limit_ms = int(ANSWER_READ_TIMEOUT * 1000)
        warning = None
        if latency >= limit_ms * SLOW_RATIO:
            warning = (f"첫 응답까지 {latency / 1000:.1f}초 — 답변 대기 한도 {ANSWER_READ_TIMEOUT:g}초의 "
                       f"{latency * 100 // limit_ms}%입니다. 긴 질문에서는 한도를 넘겨 다음 제공자로 "
                       "폴백될 수 있습니다.")
        return {"ok": True, "latency_ms": latency, "limit_ms": limit_ms, "warning": warning,
                "sample": detail, "token": ms.issue_token(secret, req.provider, req.model)}

    @router.put("")
    def save(req: SaveRequest, admin=Depends(require_admin)):
        settings, _revision, ok = ms.load(force=True)
        if not ok:
            raise HTTPException(503, "설정 저장소에 연결할 수 없습니다")
        if req.primary == "gemini" and not config_factory().gemini_api_key:
            # 키가 없으면 _answer_providers가 Gemini를 목록에 넣지 않아 저장해도 무효과다(R-5).
            raise HTTPException(400, "Gemini API 키가 없어 1순위로 지정할 수 없습니다")
        try:
            doc = ms.build_document(settings, {"primary": req.primary, "models": req.models}, secret)
            revision = ms.save(req.revision, doc, actor=_actor(admin))
        except ms.SettingsError as e:
            raise HTTPException(422, str(e)) from e
        except ms.RevisionConflict as e:
            raise HTTPException(409, "다른 곳에서 먼저 변경됐습니다. 새로고침 후 다시 시도하세요") from e
        except RuntimeError as e:
            raise HTTPException(503, str(e)) from e
        return {"revision": revision}

    @router.post("/reset")
    def reset(req: ResetRequest, admin=Depends(require_admin)):
        if not ms.load(force=True)[2]:
            raise HTTPException(503, "설정 저장소에 연결할 수 없습니다")
        try:
            revision = ms.save(req.revision, {}, actor=_actor(admin))
        except ms.RevisionConflict as e:
            raise HTTPException(409, "다른 곳에서 먼저 변경됐습니다. 새로고침 후 다시 시도하세요") from e
        except RuntimeError as e:
            raise HTTPException(503, str(e)) from e
        return {"revision": revision}

    return router


def _actor(admin) -> str:
    return "admin-session:" + str((admin or {}).get("jti") or "shared")[:100]
