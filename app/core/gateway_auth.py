"""Vercel OIDC 토큰 — AI Gateway 인증의 단일 출처 (ai-gateway-oidc-migration).

규칙 — 전부 설계서 §3의 결정이다:
- Vercel 함수 런타임은 토큰을 **요청마다** ``x-vercel-oidc-token`` 헤더로 넣어 준다. ``api/index.py``의
  미들웨어가 ``capture()``로 contextvar에 두고, ``llm_transport.bind()``가 **요청 스레드에서 한 번** 읽어
  config 객체에 고정한다. ThreadPoolExecutor·threading.Thread는 contextvar를 상속하지 않으므로, 스레드로는
  contextvar가 아니라 그 객체가 따라간다(Self-RAG 병렬·Gemini idle 감시).
- 로컬은 ``vercel env pull .env.vercel.local``이 쓴 ``VERCEL_OIDC_TOKEN``(12시간)이고, CI 등 Vercel 밖은
  ``AI_GATEWAY_API_KEY``(선택). 프로덕션 Vercel env에는 ``AI_GATEWAY_API_KEY``를 두지 않는다 — 장기 키를
  없애는 것이 전환의 목적이다.
- 토큰이 없으면 ``GatewayAuthError``. 제공자 키(ANTHROPIC_API_KEY 등)로 가는 분기는 **존재하지 않는다**.
- 토큰 값은 어떤 로그·예외 메시지·repr·metadata에도 넣지 않는다(길이도 적지 않는다).
"""
from __future__ import annotations

import os
from contextvars import ContextVar, Token

HEADER = "x-vercel-oidc-token"

_REQUEST_TOKEN: ContextVar[str | None] = ContextVar("vercel_oidc_token", default=None)


class GatewayAuthError(RuntimeError):
    """Gateway 모드인데 쓸 수 있는 OIDC 토큰이 없다. 메시지에 토큰·키 값을 넣지 말 것."""


def capture(headers) -> Token:
    """요청 헤더에서 토큰을 contextvar에 둔다. 헤더가 없으면 None을 set한다(이전 값이 남지 않게)."""
    value = None
    if headers is not None:
        try:
            value = headers.get(HEADER)
        except Exception:  # noqa: BLE001 — 헤더 객체가 매핑이 아니어도 요청을 막지 않는다
            value = None
    return _REQUEST_TOKEN.set(value or None)


def release(token: Token) -> None:
    try:
        _REQUEST_TOKEN.reset(token)
    except ValueError:
        # 다른 컨텍스트에서 reset을 시도한 경우 — 요청별 컨텍스트가 버려지므로 누출은 없다
        pass


def request_token() -> str | None:
    """이 요청의 헤더 토큰만(환경변수 폴백 없음) — 테스트·진단용."""
    return _REQUEST_TOKEN.get()


def current_token() -> str | None:
    """우선순위: 요청 헤더 → VERCEL_OIDC_TOKEN(로컬) → AI_GATEWAY_API_KEY(CI 등). 없으면 None."""
    return (_REQUEST_TOKEN.get()
            or (os.environ.get("VERCEL_OIDC_TOKEN") or "").strip()
            or (os.environ.get("AI_GATEWAY_API_KEY") or "").strip()
            or None)


def require_token() -> str:
    token = current_token()
    if not token:
        raise GatewayAuthError(
            "LLM_TRANSPORT=gateway인데 OIDC 토큰이 없다 — Vercel 함수에서는 x-vercel-oidc-token 헤더, "
            "로컬에서는 `vercel env pull .env.vercel.local`(VERCEL_OIDC_TOKEN, 12시간)이 필요하다. "
            "제공자 키로 우회하지 않는다.")
    return token
