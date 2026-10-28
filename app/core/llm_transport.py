"""LLM 전송 계층 — direct(제공자 직접 호출) | gateway(Vercel AI Gateway, OIDC) (ai-gateway-oidc-migration).

설계: docs/02-design/features/ai-gateway-oidc-migration.design.md §2. 지킬 것:
- 스위치는 ``LLM_TRANSPORT``(기본 ``direct``) 하나다. **Vercel env에만** 두고 로컬 ``.env``에는 넣지 않는다 —
  오프라인 스크립트가 ``AppConfig.from_env()``를 import하면 Gateway 토큰을 요구하게 된다. Vercel env 변경은
  다음 배포부터 적용되므로 설정 뒤 반드시 재배포한다.
- Gateway 모드에서 ``AppConfig.from_env()``는 제공자 키(OPENAI_API_KEY·ANTHROPIC_API_KEY·COHERE_API_KEY)를
  **읽지 않는다**. 인증 실패는 ``GatewayAuthError``로 드러나고, 제공자 키로 가는 분기는 없다.
- 전역 SDK 클라이언트(연결 풀)는 하나다. ``bind()``가 요청마다 ``with_options(api_key=<OIDC>)`` 사본을 씌운다 —
  두 SDK의 ``copy()``는 httpx 클라이언트를 공유하므로(실행본 anthropic 0.120.2·openai 2.53.0 소스 확인) 비용이 없다.
- 모델 ID는 상류(관리자 저장값·``supports_effort``·``_CLAUDE_TOOL_NO_FORCE``·``metadata.llm.model``)에서 **벤더 표기**
  (``claude-opus-5-5``)를 유지하고, SDK 경계의 프록시(``_Bound``)가 호출 직전에만 슬러그(``anthropic/claude-opus-5.5``)로
  바꾼다. 상류에서 바꾸면 ``supports_effort``의 하이픈 정규식이 거짓이 되어 effort가 빠지고 읽기 타임아웃 폴백이 재발한다.
- 슬러그 매핑은 정적 표 → 카탈로그 순이다(정적 표가 현역 모델을 전부 덮어 답변 경로에 네트워크 왕복을 더하지 않는다;
  카탈로그는 관리자가 새로 고른 모델을 위한 것이다). 둘 다 없으면 ``UnsupportedModelError`` — **임의 대체하지 않는다.**
- 재정렬은 Gateway의 Cohere 호환 표면(``/v2/rerank``)만 지원한다. Gemini는 Gateway로 보내지 않는다(``gemini-pro-latest``
  별칭에 대응하는 슬러그가 없다) — 직접 호출로 남고 보고 대상이다.
"""
from __future__ import annotations

import dataclasses
import logging
import os
import threading
import time

from app.core import gateway_auth
from app.core.gateway_auth import GatewayAuthError

logger = logging.getLogger(__name__)

GATEWAY_URL = "https://ai-gateway.vercel.sh"          # Anthropic 호환(/v1/messages)·Cohere 호환(/v2/rerank)
GATEWAY_OPENAI_URL = GATEWAY_URL + "/v1"              # OpenAI 호환(chat.completions·embeddings·models)
MODES = ("direct", "gateway")
_PLACEHOLDER_KEY = "oidc-bound-per-request"           # 실제 요청에는 절대 나가지 않는다(bind가 덮는다)

CATALOG_TTL = 3600.0        # 프로세스 안 캐시(Vercel 인스턴스 수명과 비슷하다)
CATALOG_FAIL_TTL = 60.0     # 실패도 잠깐 기억 — 장애 중 매 호출이 10초를 기다리지 않게
CATALOG_TIMEOUT = 10.0

# 관리자 provider 키 → Gateway 카탈로그의 provider 이름
VENDOR_OF_PROVIDER = {"claude": "anthropic", "openai": "openai", "gemini": "google"}

# 정적 슬러그 표 — 2026-10-28 `GET /v1/models` 실측. 버전은 점 표기(anthropic/claude-opus-5.5).
STATIC_SLUGS: dict[str, dict[str, str]] = {
    "anthropic": {
        "claude-opus-5-5": "anthropic/claude-opus-5.5",
        "claude-sonnet-5-5": "anthropic/claude-sonnet-5.5",
        "claude-sonnet-5": "anthropic/claude-sonnet-5",
        "claude-haiku-5-5": "anthropic/claude-haiku-5.5",
        "claude-opus-5": "anthropic/claude-opus-5",
    },
    "openai": {
        "gpt-6-sol": "openai/gpt-6-sol",
        "o3": "openai/o3",
        "text-embedding-3-small": "openai/text-embedding-3-small",
    },
    "cohere": {
        "rerank-v3.5": "cohere/rerank-v3.5",
    },
}


class UnsupportedModelError(RuntimeError):
    """Gateway 슬러그를 찾지 못한 모델 — 다른 모델로 바꾸지 않고 실패시킨다."""


class GatewayUnsupportedError(RuntimeError):
    """Gateway 모드에서 쓸 수 없는 SDK 표면(벤더 models.list 등)."""


def transport_mode() -> str:
    value = (os.getenv("LLM_TRANSPORT") or "direct").strip().lower()
    return value if value in MODES else "direct"


def is_gateway(config) -> bool:
    return getattr(config, "transport", "direct") == "gateway"


def make_gateway_clients():
    """Gateway용 전역 클라이언트 — 자리표시 키 + Gateway base_url. 제공자 키는 읽지 않는다."""
    import anthropic
    from openai import OpenAI
    openai_client = OpenAI(api_key=_PLACEHOLDER_KEY, base_url=GATEWAY_OPENAI_URL)
    claude_client = anthropic.Anthropic(api_key=_PLACEHOLDER_KEY, base_url=GATEWAY_URL)
    return openai_client, claude_client


# ── 슬러그 매핑 ──────────────────────────────────────────────────────────────

def to_slug(vendor: str, model: str, token: str | None = None) -> str:
    """벤더 모델 ID → Gateway 슬러그. '/'가 이미 있으면 슬러그로 보고 그대로 둔다."""
    if not model:
        raise UnsupportedModelError(f"{vendor}: 모델이 비었다")
    if "/" in model:
        return model
    slug = STATIC_SLUGS.get(vendor, {}).get(model)
    if slug:
        return slug
    slug = catalog(token).get("slug_by", {}).get((vendor, model))
    if slug:
        return slug
    raise UnsupportedModelError(
        f"Gateway 슬러그를 찾지 못했다: {vendor}/{model} — 정적 표·카탈로그 모두 없음. 임의 대체하지 않는다")


# ── 카탈로그(관리자 목록·미수록 모델 폴백) ──────────────────────────────────────

_catalog_lock = threading.Lock()
_catalog: dict = {}
_catalog_at = 0.0
_catalog_failed_at = 0.0


def _fetch_catalog(token: str | None) -> dict:
    import httpx
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    r = httpx.get(GATEWAY_URL + "/v1/models/catalog", headers=headers, timeout=CATALOG_TIMEOUT)
    r.raise_for_status()
    models = (r.json() or {}).get("models") or []
    # /v1/models는 type(언어·임베딩·재정렬)·name·released(출시일 epoch)를 준다 — 실패해도 슬러그 표는 살린다(Check BS6).
    # 그때는 type 필터와 출시일 정렬이 빠질 뿐이고, "카탈로그 전체 실패 → 정적 표"로 떨어지는 것보다 낫다.
    listing: dict = {}
    try:
        r2 = httpx.get(GATEWAY_OPENAI_URL + "/models", headers=headers, timeout=CATALOG_TIMEOUT)
        r2.raise_for_status()
        listing = {e.get("id"): e for e in ((r2.json() or {}).get("data") or []) if e.get("id")}
    except Exception as exc:  # noqa: BLE001 — 토큰 값은 메시지에 없다
        logger.warning("Gateway /v1/models 조회 실패 — type·출시일 없이 카탈로그만 쓴다: %s", type(exc).__name__)
    slug_by: dict[tuple[str, str], str] = {}
    by_vendor: dict[str, list[tuple[str, str]]] = {}
    for entry in models:
        slug = entry.get("slug")
        if not slug:
            continue
        for p in entry.get("providers") or []:
            vendor, pm = p.get("provider"), p.get("providerModelId")
            if vendor and pm:
                slug_by.setdefault((vendor, pm), slug)
                by_vendor.setdefault(vendor, []).append((pm, slug))
    return {"slug_by": slug_by, "by_vendor": by_vendor, "listing": listing}


def catalog(token: str | None = None) -> dict:
    """카탈로그(캐시). 실패하면 빈 dict — 호출부는 정적 표로 동작한다.

    네트워크는 **잠금 밖**에서 탄다(Check BS6) — 잠금을 쥔 채 최대 20초를 기다리면, 정적 표에 없는 모델을 해석하는
    답변 경로의 다른 스레드까지 그 뒤에 줄을 선다. 동시 미스는 두 번 받아올 수 있지만 결과는 같다.
    """
    global _catalog, _catalog_at, _catalog_failed_at
    now = time.monotonic()
    with _catalog_lock:
        if _catalog and now - _catalog_at < CATALOG_TTL:
            return _catalog
        if now - _catalog_failed_at < CATALOG_FAIL_TTL:
            return _catalog
    try:
        fetched = _fetch_catalog(token)
    except Exception as exc:  # noqa: BLE001 — 토큰·키 값은 메시지에 없다(SDK 밖 요청)
        with _catalog_lock:
            _catalog_failed_at = time.monotonic()
        logger.warning("Gateway 카탈로그 조회 실패 — 정적 슬러그 표로 동작: %s", type(exc).__name__)
        return _catalog
    with _catalog_lock:
        _catalog, _catalog_at = fetched, time.monotonic()
        return _catalog


def reset_catalog_cache() -> None:
    global _catalog, _catalog_at, _catalog_failed_at
    with _catalog_lock:
        _catalog, _catalog_at, _catalog_failed_at = {}, 0.0, 0.0


def catalog_models(provider: str, token: str | None = None) -> list[dict]:
    """관리자 목록용 — Gateway 카탈로그에서 해당 벤더의 **텍스트 모델**을 벤더 ID(providerModelId)로 돌려준다.

    형식은 model_settings.fetch_raw_models와 같다: [{"id", "label", "created"}]. created는 ``/v1/models``의 ``released``
    (출시일 epoch)다 — 같은 응답의 ``created``는 전 모델이 같은 상수(1755815280)라 쓰지 않는다(2026-10-28 실측). 날짜가
    없으면(None) select_latest가 ID 역순으로 떨어져 Claude 목록이 sonnet 계열만 남는다(Check G-M3). 카탈로그가 비면
    정적 표만 돌려준다 — 그래도 저장값은 전부 해석 가능하다.
    """
    vendor = VENDOR_OF_PROVIDER.get(provider, provider)
    cat = catalog(token)
    out: list[dict] = []
    seen: set[str] = set()
    listing = cat.get("listing", {})
    for pm, slug in cat.get("by_vendor", {}).get(vendor, []):
        meta = listing.get(slug) or {}
        if listing and meta.get("type") not in (None, "language"):
            continue
        if pm in seen:
            continue
        seen.add(pm)
        out.append({"id": pm, "label": meta.get("name") or slug, "created": meta.get("released")})
    for pm, slug in STATIC_SLUGS.get(vendor, {}).items():
        if pm not in seen and (not listing or (listing.get(slug) or {}).get("type") in (None, "language")):
            seen.add(pm)
            out.append({"id": pm, "label": slug, "created": (listing.get(slug) or {}).get("released")})
    return out


# ── SDK 경계 프록시 ─────────────────────────────────────────────────────────────

class _Methods:
    """네임스페이스(messages·chat.completions·embeddings)의 허용 메서드만 노출하고 model=만 슬러그로 바꾼다."""
    __slots__ = ("_target", "_vendor", "_token", "_names")

    def __init__(self, target, vendor: str, token: str | None, names: tuple[str, ...]):
        self._target, self._vendor, self._token, self._names = target, vendor, token, names

    def __getattr__(self, name: str):
        if name not in self._names:
            raise AttributeError(f"GatewayBound {self._vendor}: '{name}'은 전송 계층이 지원하지 않는 호출이다")
        fn = getattr(self._target, name)
        vendor, token = self._vendor, self._token

        def call(*args, **kw):
            if "model" in kw:
                kw["model"] = to_slug(vendor, kw["model"], token)
            return fn(*args, **kw)
        return call

    def __repr__(self) -> str:
        return f"<GatewayBound {self._vendor} {'/'.join(self._names)}>"


class _Chat:
    __slots__ = ("completions",)

    def __init__(self, completions: _Methods):
        self.completions = completions


class _Bound:
    """요청별 토큰이 묶인 SDK 클라이언트 사본. 호출부가 쓰는 표면만 지원한다 — 그 외 접근은 AttributeError.

    현행 호출부는 전부 ``client.with_options(...)``를 먼저 거친다(2026-10-28 전수 조사, 예외 0건). 거치지 않고
    ``messages`` 등에 바로 접근하면 여기서 ``with_options()``를 한 번 끼워 토큰을 넣는다.
    """
    __slots__ = ("_inner", "_vendor", "_token", "_authed")

    def __init__(self, inner, vendor: str, token: str | None, authed: bool = False):
        self._inner, self._vendor, self._token, self._authed = inner, vendor, token, authed

    def __repr__(self) -> str:                      # 토큰·키는 절대 포함하지 않는다
        return f"<GatewayBound {self._vendor} authed={self._authed}>"

    @property
    def base_url(self):
        return getattr(self._inner, "base_url", None)

    def with_options(self, **kw):
        if not self._token:
            raise GatewayAuthError(
                "LLM_TRANSPORT=gateway인데 OIDC 토큰이 없다 — Vercel 함수에서는 x-vercel-oidc-token 헤더, "
                "로컬에서는 `vercel env pull .env.vercel.local`(VERCEL_OIDC_TOKEN, 12시간)이 필요하다. "
                "제공자 키로 우회하지 않는다.")
        kw.pop("api_key", None)
        return _Bound(self._inner.with_options(api_key=self._token, **kw), self._vendor, self._token, authed=True)

    def _authed_inner(self):
        return self._inner if self._authed else self.with_options()._inner

    @property
    def messages(self) -> _Methods:
        return _Methods(self._authed_inner().messages, self._vendor, self._token, ("create", "stream"))

    @property
    def chat(self) -> _Chat:
        return _Chat(_Methods(self._authed_inner().chat.completions, self._vendor, self._token, ("create",)))

    @property
    def embeddings(self) -> _Methods:
        return _Methods(self._authed_inner().embeddings, self._vendor, self._token, ("create",))

    @property
    def models(self):
        raise GatewayUnsupportedError(
            "Gateway 모드에서는 벤더 models.list를 부르지 않는다 — llm_transport.catalog_models()를 쓸 것")


def _unwrap(client):
    return client._inner if isinstance(client, _Bound) else client


def bound_token(config) -> str | None:
    """바인딩된 config에 고정된 토큰(없으면 None). 요청 밖·스레드에서 contextvar를 다시 읽는 대신 이것을 쓴다(규칙 ①)."""
    client = getattr(config, "claude_client", None)
    return client._token if isinstance(client, _Bound) else None


def bind(config):
    """요청별 바인딩. direct면 그대로(동작 바이트 동일), gateway면 토큰을 객체에 고정한 사본."""
    if not is_gateway(config):
        return config
    token = gateway_auth.current_token()
    return dataclasses.replace(
        config,
        claude_client=_Bound(_unwrap(config.claude_client), "anthropic", token),
        openai_client=_Bound(_unwrap(config.openai_client), "openai", token),
        cohere_api_key=token,
        cohere_base_url=GATEWAY_URL,
    )


# ── Cohere(재정렬) ──────────────────────────────────────────────────────────────

def rerank_client(api_key: str, base_url: str | None = None):
    """direct: ClientV2(api_key) · gateway: ClientV2(api_key=<OIDC>, base_url=Gateway) → /v2/rerank."""
    import cohere
    if base_url:
        return cohere.ClientV2(api_key=api_key, base_url=base_url)
    return cohere.ClientV2(api_key=api_key)


def rerank_model(base_url: str | None, model: str) -> str:
    return to_slug("cohere", model) if base_url else model
