#!/usr/bin/env python3
"""LLM 전송 계층(Vercel AI Gateway + OIDC) 오프라인 테스트 — API 키·네트워크 불요 (ai-gateway-oidc-migration).

설계 §7.1 T1~T12. 고정하는 것:
- direct 모드는 바이트 동일 동작(bind가 같은 객체를 돌려준다).
- gateway 모드는 제공자 키를 읽지 않고, 토큰이 없으면 호출 시점에 GatewayAuthError — 제공자 키 우회 분기가 없다.
- 슬러그 변환은 SDK 경계에서만 일어나고 상류(partial.keywords['model']·supports_effort)는 벤더 표기를 유지한다.
- 미해결 모델은 임의 대체 없이 UnsupportedModelError.
- 토큰은 repr·예외 메시지·로그에 나오지 않는다.
- 토큰은 contextvar가 아니라 바인딩된 객체로 스레드풀에 따라간다.
"""
from __future__ import annotations

import contextlib
import io
import logging
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from app.config import AppConfig
from app.core import gateway_auth, llm_transport
from app.core.gateway_auth import GatewayAuthError
from app.core.llm_transport import UnsupportedModelError

TOKEN = "eyJ-test-oidc-token-not-a-real-secret-1234567890"


class _FakeNamespace:
    """SDK 네임스페이스 대역 — 받은 kwargs를 기록한다."""

    def __init__(self, log: list, name: str):
        self._log, self._name = log, name

    def create(self, **kw):
        self._log.append((self._name + ".create", kw))
        return {"ok": True, "kw": kw}

    def stream(self, **kw):
        self._log.append((self._name + ".stream", kw))
        return ("stream-manager", kw)          # 컨텍스트 매니저 대역 — 그대로 반환돼야 한다

    def list(self, **kw):
        self._log.append((self._name + ".list", kw))
        return []


class _FakeChat:
    def __init__(self, log):
        self.completions = _FakeNamespace(log, "chat.completions")


class _FakeSDK:
    """anthropic.Anthropic / openai.OpenAI 대역 — with_options(api_key=…)가 사본을 만들고 api_key를 기억한다."""

    def __init__(self, api_key="placeholder", base_url="https://fake", log=None, options=None):
        self.api_key, self.base_url = api_key, base_url
        self.log = log if log is not None else []
        self.options = options or {}
        self.messages = _FakeNamespace(self.log, "messages")
        self.chat = _FakeChat(self.log)
        self.embeddings = _FakeNamespace(self.log, "embeddings")
        self.models = _FakeNamespace(self.log, "models")

    def with_options(self, **kw):
        opts = dict(self.options, **kw)
        return _FakeSDK(api_key=kw.get("api_key", self.api_key), base_url=self.base_url, log=self.log, options=opts)


def _gw_config(token_env: bool = False, **over) -> AppConfig:
    base = dict(openai_client=_FakeSDK(), pinecone_index=None, claude_client=_FakeSDK(),
                gemini_api_key=None, cohere_api_key=None, transport="gateway")
    base.update(over)
    return AppConfig(**base)


@contextlib.contextmanager
def _env(**kw):
    """값 None은 삭제, 나머지는 설정 — patch.dict는 None을 받지 않는다."""
    with mock.patch.dict(os.environ, {k: v for k, v in kw.items() if v is not None}, clear=False):
        for k, v in kw.items():
            if v is None:
                os.environ.pop(k, None)
        yield


@contextlib.contextmanager
def _no_token():
    tok = gateway_auth._REQUEST_TOKEN.set(None)
    try:
        with _env(VERCEL_OIDC_TOKEN=None, AI_GATEWAY_API_KEY=None):
            yield
    finally:
        gateway_auth._REQUEST_TOKEN.reset(tok)


class T1DirectUnchanged(unittest.TestCase):
    def test_direct_bind_returns_same_object_and_mode_default(self):
        with _env(LLM_TRANSPORT=None):
            self.assertEqual(llm_transport.transport_mode(), "direct")
        with _env(LLM_TRANSPORT="weird"):
            self.assertEqual(llm_transport.transport_mode(), "direct")
        cfg = AppConfig(openai_client=object(), pinecone_index=None, claude_client=object())
        self.assertEqual(cfg.transport, "direct")
        self.assertIs(llm_transport.bind(cfg), cfg)
        self.assertFalse(llm_transport.is_gateway(cfg))

    def test_direct_clients_stay_sdk_objects_with_default_base_url(self):
        """설계 T1 후반 — direct에서는 프록시가 끼지 않고 base_url도 SDK 기본값이다(Check M1)."""
        import anthropic
        import openai
        with _env(ANTHROPIC_BASE_URL=None, OPENAI_BASE_URL=None):
            cfg = AppConfig(openai_client=openai.OpenAI(api_key="not-a-real-key"), pinecone_index=None,
                            claude_client=anthropic.Anthropic(api_key="not-a-real-key"))
        bound = llm_transport.bind(cfg)
        self.assertIs(bound, cfg)
        self.assertNotIsInstance(bound.claude_client, llm_transport._Bound)
        self.assertNotIsInstance(bound.openai_client, llm_transport._Bound)
        self.assertEqual(str(bound.claude_client.base_url).rstrip("/"), "https://api.anthropic.com")
        self.assertEqual(str(bound.openai_client.base_url).rstrip("/"), "https://api.openai.com/v1")

    def test_direct_from_env_still_requires_provider_keys(self):
        with _env(LLM_TRANSPORT="direct", OPENAI_API_KEY=None, ANTHROPIC_API_KEY=None, PINECONE_API_KEY="p"):
            with self.assertRaises(EnvironmentError):
                AppConfig.from_env()


class T2GatewayReadsNoProviderKeys(unittest.TestCase):
    def test_from_env_gateway_ignores_provider_keys(self):
        sentinel_o, sentinel_a, sentinel_c = "SENTINEL-OPENAI", "SENTINEL-ANTHROPIC", "SENTINEL-COHERE"
        with _env(LLM_TRANSPORT="gateway", OPENAI_API_KEY=sentinel_o, ANTHROPIC_API_KEY=sentinel_a,
                  COHERE_API_KEY=sentinel_c, PINECONE_API_KEY="pc-test", GEMINI_API_KEY=None,
                  SUPABASE_URL=None, SUPABASE_KEY=None, VERCEL_OIDC_TOKEN=None, AI_GATEWAY_API_KEY=None), \
             mock.patch("app.config.Pinecone", side_effect=RuntimeError("no network")), \
             mock.patch("app.core.storage.make_supabase_client", return_value=None):
            with contextlib.redirect_stderr(io.StringIO()):
                logging.disable(logging.CRITICAL)
                try:
                    cfg = AppConfig.from_env()
                finally:
                    logging.disable(logging.NOTSET)
        self.assertEqual(cfg.transport, "gateway")
        # 값이 실패 메시지에 찍히지 않게 assertTrue로 비교한다(키·토큰 비출력 규칙)
        self.assertTrue(cfg.cohere_api_key is None, "gateway 모드는 COHERE_API_KEY를 읽지 않는다(토큰 없는 환경이면 None)")
        self.assertTrue(llm_transport._unwrap(cfg.openai_client).api_key != sentinel_o, "OPENAI_API_KEY를 읽었다")
        self.assertTrue(llm_transport._unwrap(cfg.claude_client).api_key != sentinel_a, "ANTHROPIC_API_KEY를 읽었다")
        self.assertIsInstance(cfg.claude_client, llm_transport._Bound, "from_env도 환경 토큰으로 바인딩한다(CLI·평가용)")
        self.assertTrue(str(cfg.openai_client.base_url).startswith(llm_transport.GATEWAY_OPENAI_URL))
        self.assertTrue(str(cfg.claude_client.base_url).startswith(llm_transport.GATEWAY_URL))

    def test_gateway_required_keys_is_pinecone_only(self):
        with _env(LLM_TRANSPORT="gateway", PINECONE_API_KEY=None, OPENAI_API_KEY=None, ANTHROPIC_API_KEY=None):
            with self.assertRaises(EnvironmentError) as ctx:
                AppConfig.from_env()
        self.assertIn("PINECONE_API_KEY", str(ctx.exception))
        self.assertNotIn("OPENAI_API_KEY", str(ctx.exception))


class T3ProxyTranslatesModelAtBoundary(unittest.TestCase):
    def setUp(self):
        self.cfg = _gw_config()
        self.tok = gateway_auth._REQUEST_TOKEN.set(TOKEN)

    def tearDown(self):
        gateway_auth._REQUEST_TOKEN.reset(self.tok)

    def test_messages_create_and_stream(self):
        b = llm_transport.bind(self.cfg)
        self.assertIsNot(b, self.cfg)
        self.assertIs(b.pinecone_index, self.cfg.pinecone_index)
        extra = {"output_config": {"effort": "medium"}, "thinking": {"type": "adaptive", "display": "summarized"},
                 "tools": [{"name": "t"}], "tool_choice": {"type": "auto", "disable_parallel_tool_use": True}}
        client = b.claude_client.with_options(timeout=1.0, max_retries=0)
        res = client.messages.create(model="claude-opus-5-5", max_tokens=10, messages=[], **extra)
        name, kw = b.claude_client._inner.log[-1]
        self.assertEqual(name, "messages.create")
        self.assertEqual(kw["model"], "anthropic/claude-opus-5.5")
        for k, v in extra.items():
            self.assertEqual(kw[k], v, k)
        self.assertTrue(client._inner.api_key == TOKEN, "바인딩 토큰이 api_key로 들어가야 한다")
        self.assertEqual(client._inner.options["timeout"], 1.0)
        self.assertEqual(client._inner.options["max_retries"], 0)
        sm = client.messages.stream(model="claude-sonnet-5", max_tokens=1, messages=[])
        self.assertEqual(sm[0], "stream-manager", "stream은 SDK 객체를 그대로 반환해야 한다")
        self.assertEqual(sm[1]["model"], "anthropic/claude-sonnet-5")

    def test_openai_chat_and_embeddings(self):
        b = llm_transport.bind(self.cfg)
        b.openai_client.with_options(timeout=10.0, max_retries=0).chat.completions.create(
            model="gpt-6-sol", messages=[], max_completion_tokens=4096, stream=True)
        b.openai_client.with_options(timeout=10.0, max_retries=0).embeddings.create(
            model="text-embedding-3-small", input="x")
        names = [n for n, _ in b.openai_client._inner.log]
        self.assertEqual(names, ["chat.completions.create", "embeddings.create"])
        self.assertEqual(b.openai_client._inner.log[0][1]["model"], "openai/gpt-6-sol")
        self.assertEqual(b.openai_client._inner.log[1][1]["model"], "openai/text-embedding-3-small")
        self.assertTrue(all(kw.get("stream") or "input" in kw for _, kw in b.openai_client._inner.log))

    def test_direct_namespace_access_injects_token_once(self):
        b = llm_transport.bind(self.cfg)
        b.openai_client.embeddings.create(model="text-embedding-3-small", input="x")
        self.assertEqual(b.openai_client._inner.log[-1][1]["model"], "openai/text-embedding-3-small")

    def test_rebind_unwraps(self):
        b = llm_transport.bind(llm_transport.bind(self.cfg))
        self.assertIsInstance(b.claude_client._inner, _FakeSDK)

    def test_models_list_is_refused(self):
        b = llm_transport.bind(self.cfg)
        with self.assertRaises(llm_transport.GatewayUnsupportedError):
            b.claude_client.with_options(timeout=1).models


class T4NoTokenFailsAtCallNotAtBind(unittest.TestCase):
    def test_bind_ok_call_raises(self):
        with _no_token():
            b = llm_transport.bind(_gw_config())
            self.assertIsNone(b.cohere_api_key)
            with self.assertRaises(GatewayAuthError):
                b.claude_client.with_options(timeout=1)
            with self.assertRaises(GatewayAuthError):
                b.openai_client.embeddings.create(model="text-embedding-3-small", input="x")
            self.assertEqual(b.claude_client._inner.log, [], "토큰 없이는 SDK에 아무 호출도 가지 않는다")


class T5UnresolvedModelIsError(unittest.TestCase):
    def test_unknown_model_raises_and_no_hyphen_dot_guess(self):
        llm_transport.reset_catalog_cache()
        with mock.patch.object(llm_transport, "_fetch_catalog", side_effect=RuntimeError("offline")):
            with self.assertRaises(UnsupportedModelError):
                llm_transport.to_slug("anthropic", "claude-new-7")
            with mock.patch.dict(llm_transport.STATIC_SLUGS["anthropic"], {}, clear=True):
                with self.assertRaises(UnsupportedModelError):
                    llm_transport.to_slug("anthropic", "claude-opus-5-5")
        llm_transport.reset_catalog_cache()
        self.assertEqual(llm_transport.to_slug("openai", "google/gemini-2.5-pro"), "google/gemini-2.5-pro")

    def test_catalog_fallback_resolves_new_model(self):
        llm_transport.reset_catalog_cache()
        fake = {"slug_by": {("anthropic", "claude-new-7"): "anthropic/claude-new-7"}, "by_vendor": {}, "listing": {}}
        with mock.patch.object(llm_transport, "_fetch_catalog", return_value=fake):
            self.assertEqual(llm_transport.to_slug("anthropic", "claude-new-7"), "anthropic/claude-new-7")
        llm_transport.reset_catalog_cache()


class T6UpstreamKeepsVendorIds(unittest.TestCase):
    def test_answer_providers_keywords_are_vendor_ids(self):
        from app.core import pipeline, llm_gateway
        tok = gateway_auth._REQUEST_TOKEN.set(TOKEN)
        try:
            b = llm_transport.bind(_gw_config())
            with mock.patch("app.core.llm_gateway.provider_chain",
                            return_value=[("claude", "claude-opus-5-5"), ("openai", "gpt-6-sol")]):
                providers = pipeline._answer_providers(b)
            models = [fn.keywords["model"] for _, fn in providers]
            self.assertEqual(models, ["claude-opus-5-5", "gpt-6-sol"])
            self.assertTrue(all("/" not in m for m in models))
            self.assertTrue(llm_gateway.supports_effort(models[0]))
        finally:
            gateway_auth._REQUEST_TOKEN.reset(tok)


class T7MiddlewareCapturesHeader(unittest.TestCase):
    def test_header_visible_in_endpoint_and_absent_header_is_none(self):
        from fastapi.testclient import TestClient
        from api import index as api_index

        seen: list = []

        def probe():
            seen.append(gateway_auth.request_token())
            return {"ok": True}
        from fastapi.routing import APIRoute
        # 정적 서빙 catch-all보다 앞에 둔다 — 뒤에 붙이면 그 라우트가 먼저 잡아 404다
        api_index.app.router.routes.insert(0, APIRoute("/__test_oidc_probe", probe, methods=["GET"]))
        client = TestClient(api_index.app)
        r = client.get("/__test_oidc_probe", headers={gateway_auth.HEADER: TOKEN})
        self.assertEqual(r.status_code, 200)
        r2 = client.get("/__test_oidc_probe")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(seen, [TOKEN, None])
        self.assertIsNone(gateway_auth.request_token(), "요청 밖에서는 토큰이 남지 않는다")
        self.assertEqual(client.get("/api/health").status_code, 200)

    def test_get_config_binds_per_request_without_touching_global(self):
        from api import index as api_index
        g = _gw_config()
        with mock.patch.object(api_index, "_config", g):
            tok = gateway_auth._REQUEST_TOKEN.set(TOKEN)
            try:
                b = api_index.get_config()
            finally:
                gateway_auth._REQUEST_TOKEN.reset(tok)
            self.assertIsInstance(b.claude_client, llm_transport._Bound)
            self.assertIsInstance(g.claude_client, _FakeSDK, "전역은 그대로다")
            self.assertTrue(b.cohere_api_key == TOKEN, "cohere_api_key는 바인딩 토큰이어야 한다")
            self.assertEqual(b.cohere_base_url, llm_transport.GATEWAY_URL)


class T8TokenNeverLeaks(unittest.TestCase):
    def test_repr_error_and_logs(self):
        tok = gateway_auth._REQUEST_TOKEN.set(TOKEN)
        try:
            b = llm_transport.bind(_gw_config())
            self.assertNotIn(TOKEN, repr(b.claude_client))
            self.assertNotIn(TOKEN, repr(b.claude_client.with_options(timeout=1).messages))
            self.assertNotIn(TOKEN, repr(b))
        finally:
            gateway_auth._REQUEST_TOKEN.reset(tok)
        with _no_token():
            try:
                llm_transport.bind(_gw_config()).claude_client.with_options(timeout=1)
            except GatewayAuthError as e:
                self.assertNotIn(TOKEN, str(e))
        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        logging.getLogger("app.core.llm_transport").addHandler(handler)
        try:
            llm_transport.reset_catalog_cache()
            with mock.patch.object(llm_transport, "_fetch_catalog", side_effect=RuntimeError(TOKEN)):
                llm_transport.catalog(TOKEN)
        finally:
            logging.getLogger("app.core.llm_transport").removeHandler(handler)
            llm_transport.reset_catalog_cache()
        self.assertNotIn(TOKEN, buf.getvalue())


class T9CohereRoutesThroughGateway(unittest.TestCase):
    def test_rerank_gateway_vs_direct(self):
        from app.core import rag
        calls: list = []

        class _Res:
            def __init__(self, n):
                class _R:  # noqa: D401
                    def __init__(self, i):
                        self.index, self.relevance_score = i, 1.0 - i / 100
                self.results = [_R(i) for i in range(n)]

        class _Co:
            def __init__(self, **kw):
                calls.append(("init", kw))

            def rerank(self, **kw):
                calls.append(("rerank", kw))
                return _Res(len(kw["documents"]))

        hits = [{"id": f"h{i}", "content": f"c{i}", "score": 0.5} for i in range(3)]
        with mock.patch.dict("sys.modules", {"cohere": mock.MagicMock(ClientV2=_Co)}):
            rag.rerank_results("q", hits, TOKEN, top_n=2, cohere_base_url=llm_transport.GATEWAY_URL)
            rag.rerank_results("q", hits, "direct-key", top_n=2)
        self.assertEqual(calls[0], ("init", {"api_key": TOKEN, "base_url": llm_transport.GATEWAY_URL}))
        self.assertEqual(calls[1][1]["model"], "cohere/rerank-v3.5")
        self.assertEqual(calls[2], ("init", {"api_key": "direct-key"}))
        self.assertEqual(calls[3][1]["model"], rag.RERANK_MODEL)


class T10TokenTravelsWithObjectIntoThreads(unittest.TestCase):
    def test_threadpool_without_contextvar(self):
        tok = gateway_auth._REQUEST_TOKEN.set(TOKEN)
        try:
            b = llm_transport.bind(_gw_config())
        finally:
            gateway_auth._REQUEST_TOKEN.reset(tok)

        def work():
            assert gateway_auth.request_token() is None, "스레드는 contextvar를 상속하지 않는다(재현 조건)"
            with _env(VERCEL_OIDC_TOKEN=None, AI_GATEWAY_API_KEY=None):
                b.openai_client.with_options(timeout=5).embeddings.create(model="text-embedding-3-small", input="x")
            return b.openai_client._inner.log[-1][1]["model"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(pool.submit(work).result(), "openai/text-embedding-3-small")


class T11AdminListUsesCatalog(unittest.TestCase):
    def test_fetch_raw_models_gateway(self):
        from app.core import model_settings as ms
        # /v1/models 실측 형태: created는 전 모델 동일 상수, released가 출시일(Check G-M3)
        fake = {"slug_by": {}, "listing": {
                    "anthropic/claude-opus-5.5": {"type": "language", "name": "Claude Opus 5.5",
                                                  "released": 1790035200, "created": 1755815280},
                    "anthropic/claude-sonnet-5.5": {"type": "language", "name": "Claude Sonnet 5.5",
                                                    "released": 1790553600, "created": 1755815280},
                    "anthropic/claude-sonnet-4.6": {"type": "language", "name": "Claude Sonnet 4.6",
                                                    "released": 1771286400, "created": 1755815280},
                    "anthropic/claude-x-embed": {"type": "embedding", "name": "emb"}},
                "by_vendor": {"anthropic": [("claude-opus-5-5", "anthropic/claude-opus-5.5"),
                                            ("claude-sonnet-5-5", "anthropic/claude-sonnet-5.5"),
                                            ("claude-sonnet-4-6", "anthropic/claude-sonnet-4.6"),
                                            ("claude-x-embed", "anthropic/claude-x-embed")]}}
        llm_transport.reset_catalog_cache()
        cfg = _gw_config()
        with mock.patch.object(llm_transport, "_fetch_catalog", return_value=fake):
            rows = ms.fetch_raw_models("claude", cfg)
        llm_transport.reset_catalog_cache()
        ids = [r["id"] for r in rows]
        self.assertIn("claude-opus-5-5", ids)
        self.assertNotIn("claude-x-embed", ids, "임베딩 타입은 텍스트 목록에서 뺀다")
        self.assertIn("claude-sonnet-5", ids, "정적 표의 모델도 포함된다")
        self.assertEqual(cfg.claude_client.log, [], "벤더 models.list를 부르지 않는다")
        self.assertTrue(all("/" not in i for i in ids), "관리자 목록은 벤더 ID다")
        by = {r["id"]: r for r in rows}
        self.assertEqual(by["claude-opus-5-5"]["created"], 1790035200,
                         "created는 /v1/models의 released(출시일)다 — 전 모델 동일 상수인 created가 아니다")
        latest = [m["id"] for m in ms.select_latest("claude", rows, None)]
        self.assertEqual(latest[:3], ["claude-sonnet-5-5", "claude-opus-5-5", "claude-sonnet-4-6"],
                         "출시일 역순 3개 — 날짜가 없으면 ID 역순으로 떨어져 sonnet 계열만 남는다(Check G-M3)")


class T13RerankCallSitesPassBaseUrl(unittest.TestCase):
    """config의 cohere_api_key를 넘기는 rerank_results 호출부는 cohere_base_url도 넘겨야 한다(Check G-M2).

    gateway 모드에서 config.cohere_api_key는 OIDC 토큰이다 — base_url 없이 부르면 그 토큰이 Cohere 자체 호스트로
    Bearer 송신된다(401 뒤 코사인 폴백이라 조용하다). from_env()가 환경 토큰으로 바인딩하므로 평가 스크립트도 해당된다
    (eval_retrieval·eval_colloquial이 그랬다).
    """

    def test_every_config_keyed_call_passes_cohere_base_url(self):
        import ast
        import pathlib
        root = pathlib.Path(__file__).resolve().parent
        files = [p for p in list(root.glob("*.py")) + list((root / "app").rglob("*.py")) + list((root / "api").rglob("*.py"))
                 if not p.name.startswith("test_")]
        offenders, checked = [], []
        for path in files:
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
                if name != "rerank_results":
                    continue
                values = list(node.args) + [k.value for k in node.keywords]
                if not any(isinstance(v, ast.Attribute) and v.attr == "cohere_api_key" for v in values):
                    continue
                checked.append(f"{path.relative_to(root)}:{node.lineno}")
                if not any(k.arg == "cohere_base_url" for k in node.keywords):
                    offenders.append(checked[-1])
        self.assertTrue(any(c.startswith("app/core/pipeline.py") for c in checked), checked)
        self.assertTrue(any(c.startswith("eval_retrieval.py") for c in checked), checked)
        self.assertTrue(any(c.startswith("eval_colloquial.py") for c in checked), checked)
        self.assertEqual(offenders, [], "cohere_api_key만 넘기고 cohere_base_url을 빠뜨린 호출")


class T14AdminListTokenComesFromBoundConfig(unittest.TestCase):
    def test_fetch_raw_models_uses_bound_token_not_contextvar(self):
        """관리자 목록 토큰은 바인딩 객체에서 — contextvar를 다시 읽지 않는다(규칙 ①, Check BS5)."""
        from app.core import model_settings as ms
        tok = gateway_auth._REQUEST_TOKEN.set(TOKEN)
        try:
            cfg = llm_transport.bind(_gw_config())
        finally:
            gateway_auth._REQUEST_TOKEN.reset(tok)
        self.assertTrue(llm_transport.bound_token(cfg) == TOKEN, "bound_token은 바인딩된 토큰을 돌려준다")
        other = gateway_auth._REQUEST_TOKEN.set("a-different-request-token")
        try:
            with mock.patch.object(llm_transport, "catalog_models", return_value=[]) as cm:
                ms.fetch_raw_models("claude", cfg)
        finally:
            gateway_auth._REQUEST_TOKEN.reset(other)
        self.assertTrue(cm.call_args.args[1] == TOKEN, "토큰은 바인딩 객체에서 와야 한다 — contextvar의 다른 값이 아니다")
        plain = AppConfig(openai_client=object(), pinecone_index=None, claude_client=object())
        self.assertIsNone(llm_transport.bound_token(plain))


class T15CatalogFetchOutsideLockAndListingOptional(unittest.TestCase):
    def test_fetch_runs_without_holding_lock(self):
        """네트워크 조회 중 잠금을 쥐면 정적 표에 없는 모델을 해석하는 답변 경로가 뒤에 줄을 선다(Check BS6)."""
        seen = []

        def fake_fetch(token):
            seen.append(llm_transport._catalog_lock.locked())
            return {"slug_by": {}, "by_vendor": {}, "listing": {}}

        llm_transport.reset_catalog_cache()
        with mock.patch.object(llm_transport, "_fetch_catalog", side_effect=fake_fetch):
            llm_transport.catalog(None)
        llm_transport.reset_catalog_cache()
        self.assertEqual(seen, [False])

    def test_models_listing_failure_keeps_slug_table(self):
        """/v1/models가 죽어도 카탈로그 슬러그 표는 살린다 — type·출시일만 빠진다(Check BS6)."""
        import httpx

        class _R:
            def __init__(self, payload):
                self._p = payload

            def raise_for_status(self):
                pass

            def json(self):
                return self._p

        def fake_get(url, **kw):
            if url.endswith("/v1/models/catalog"):
                return _R({"models": [{"slug": "anthropic/claude-new-9",
                                       "providers": [{"provider": "anthropic", "providerModelId": "claude-new-9"}]}]})
            raise ConnectionError("models listing down")

        with mock.patch.object(httpx, "get", side_effect=fake_get), \
                self.assertLogs("app.core.llm_transport", level="WARNING") as logs:
            cat = llm_transport._fetch_catalog(None)
        self.assertEqual(cat["slug_by"].get(("anthropic", "claude-new-9")), "anthropic/claude-new-9")
        self.assertEqual(cat["listing"], {})
        self.assertTrue(any("/v1/models" in m for m in logs.output))


class T12GeminiStaysDirect(unittest.TestCase):
    def test_gemini_in_chain_only_with_key_and_untouched_by_bind(self):
        from app.core import llm_gateway
        tok = gateway_auth._REQUEST_TOKEN.set(TOKEN)
        try:
            with_key = llm_transport.bind(_gw_config(gemini_api_key="g"))
            without = llm_transport.bind(_gw_config(gemini_api_key=None))
        finally:
            gateway_auth._REQUEST_TOKEN.reset(tok)
        self.assertEqual(with_key.gemini_api_key, "g", "bind는 Gemini 키를 건드리지 않는다(직접 호출 잔존)")
        self.assertTrue(llm_gateway._available(with_key, "gemini"))
        self.assertFalse(llm_gateway._available(without, "gemini"))
        self.assertTrue(llm_gateway._available(without, "claude"))
        self.assertTrue(llm_gateway._available(without, "openai"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
