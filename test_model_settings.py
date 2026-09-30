"""답변 모델 설정 오프라인 테스트 (admin-model-settings, API 키·네트워크 불요).

M-1 기본값 경로 무회귀 · M-2 우선순위 · M-3 캐시 · M-4 fail-open · M-5 목록 필터(최신 3개)
M-6 토큰 · M-7 저장 검증 · M-8 모델 기록 · M-9 테스트 호출 판정
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.core import model_settings as ms


def _cfg(gemini=True):
    from types import SimpleNamespace
    return SimpleNamespace(gemini_api_key="k" if gemini else None,
                           openai_client=object(), claude_client=object())


class _EnvClean:
    KEYS = ("OPENAI_CHAT_MODEL", "GEMINI_MODEL", "ANSWER_PROVIDER")

    def setUp(self):
        self._saved = {k: os.environ.pop(k, None) for k in self.KEYS}
        ms.invalidate()

    def tearDown(self):
        for k, v in self._saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)
        ms.invalidate()


class ResolveTest(_EnvClean, unittest.TestCase):
    def test_m1_empty_settings_match_code_defaults(self):
        from app import config
        r = ms.resolve({})
        self.assertEqual(r.models["claude"], (config.CLAUDE_MODEL, "default"))
        self.assertEqual(r.models["openai"], (config.OPENAI_CHAT_MODEL_DEFAULT, "default"))
        self.assertEqual(r.models["gemini"], (config.GEMINI_MODEL_DEFAULT, "default"))
        self.assertEqual(r.primary, (None, "default"))

    def test_m1_answer_providers_default_order_and_models(self):
        from app.core import pipeline
        with patch.object(ms, "_fetch", return_value=({}, 0, True)):
            providers = pipeline._answer_providers(_cfg())
        self.assertEqual([n for n, _ in providers], ["Claude", "OpenAI", "Gemini"])
        from app import config
        self.assertEqual(providers[0][1].keywords["model"], config.CLAUDE_MODEL)
        self.assertEqual(providers[1][1].keywords["model"], config.OPENAI_CHAT_MODEL_DEFAULT)

    def test_m2_precedence_settings_over_env_over_default(self):
        os.environ["OPENAI_CHAT_MODEL"] = "gpt-env"
        os.environ["GEMINI_MODEL"] = "gemini-env"
        os.environ["ANSWER_PROVIDER"] = "openai"
        r = ms.resolve({"models": {"gemini": {"model": "gemini-set"}}})
        self.assertEqual(r.models["openai"], ("gpt-env", "env"))
        self.assertEqual(r.models["gemini"], ("gemini-set", "settings"))
        self.assertEqual(r.primary, ("openai", "env"))
        r = ms.resolve({"primary": "gemini"})
        self.assertEqual(r.primary, ("gemini", "settings"))

    def test_m2_claude_ignores_env(self):
        os.environ["CLAUDE_MODEL"] = "claude-stale"
        try:
            self.assertEqual(ms.resolve({}).models["claude"][1], "default")
        finally:
            os.environ.pop("CLAUDE_MODEL", None)

    def test_m2_invalid_stored_values_fall_back(self):
        r = ms.resolve({"primary": "bogus", "models": {"claude": {"model": "bad id!"}}})
        self.assertEqual(r.models["claude"][1], "default")
        self.assertEqual(r.primary, (None, "default"))

    def test_m2_unknown_env_primary_is_not_reported_as_env(self):
        os.environ["ANSWER_PROVIDER"] = "mistral"
        self.assertEqual(ms.resolve({}).primary, (None, "default"))

    def test_m2_primary_reorders_providers(self):
        from app.core import pipeline
        with patch.object(ms, "_fetch", return_value=({"primary": "gemini"}, 1, True)):
            names = [n for n, _ in pipeline._answer_providers(_cfg())]
        self.assertEqual(names, ["Gemini", "Claude", "OpenAI"])


class CacheTest(_EnvClean, unittest.TestCase):
    def test_m3_ttl_and_invalidate(self):
        with patch.object(ms, "_fetch", return_value=({}, 0, True)) as f, \
                patch.object(ms.time, "monotonic", side_effect=[0, 0, 10, 70, 70, 71, 71]):
            ms.load()          # miss → 1
            ms.load()          # 10s → hit
            ms.load()          # 70s → miss → 2
            self.assertEqual(f.call_count, 2)
            ms.invalidate()
            ms.load()          # invalidated → 3
            self.assertEqual(f.call_count, 3)

    def test_r1_fetch_started_before_invalidate_does_not_repopulate_cache(self):
        """저장 직전에 시작된 조회가 invalidate() 뒤에 끝나도 옛 값을 캐시하지 않는다(R-1)."""
        def slow_fetch():
            ms.invalidate()                      # 조회 도중 다른 요청이 저장·무효화
            return {"primary": "openai"}, 1, True
        with patch.object(ms, "_fetch", side_effect=slow_fetch):
            ms.load()
        self.assertIsNone(ms._cache, "무효화 이전 세대의 결과가 캐시에 들어갔다")

    def test_m4_failure_is_default_and_cached(self):
        calls = {"n": 0}

        class Boom:
            def table(self, *_):
                calls["n"] += 1
                raise RuntimeError("db down")
        with patch.object(ms, "_read_client", return_value=Boom()):
            r1 = ms.resolve()
            r2 = ms.resolve()
        self.assertFalse(r1.store_available)
        self.assertEqual(r1.models["claude"][1], "default")
        self.assertEqual(r2.models, r1.models)
        self.assertEqual(calls["n"], 1, "실패도 캐시해야 DB 장애 중 매 요청이 2초씩 기다리지 않는다")

    def test_m4_missing_key_is_default(self):
        with patch.object(ms, "_read_client", return_value=None):
            r = ms.resolve()
        self.assertFalse(r.store_available)
        self.assertEqual(r.primary, (None, "default"))


class ListTest(unittest.TestCase):
    def test_m5_openai_filters_dedupes_and_cuts_to_three(self):
        raw = [{"id": i, "label": i, "created": c} for i, c in [
            ("text-embedding-3-small", 900), ("gpt-4o-mini-tts", 899), ("gpt-5.1-codex", 898),
            ("gpt-live-1", 897), ("gpt-9", 800), ("gpt-9-2026-09-01", 801),
            ("gpt-8", 700), ("gpt-7", 600), ("gpt-6", 500)]]
        out = [m["id"] for m in ms.select_latest("openai", raw, current="gpt-6")]
        self.assertEqual(out, ["gpt-9", "gpt-8", "gpt-7", "gpt-6"])   # 3개 + 현재값

    def test_m5_current_not_duplicated_when_in_top3(self):
        raw = [{"id": f"m{i}", "label": None, "created": i} for i in range(5)]
        out = ms.select_latest("claude", raw, current="m4")
        self.assertEqual([m["id"] for m in out], ["m4", "m3", "m2"])
        self.assertTrue(out[0]["current"])

    def test_m5_snapshot_kept_when_no_alias(self):
        raw = [{"id": "claude-haiku-4-5-20251001", "label": None, "created": 1}]
        self.assertEqual(ms.select_latest("claude", raw, None)[0]["id"], "claude-haiku-4-5-20251001")

    def test_m5_gemini_aliases_plus_version_ranked(self):
        names = ["models/gemini-flash-latest", "models/gemini-pro-latest", "models/antigravity-preview-latest",
                 "models/gemini-3.6-flash", "models/gemini-3.8-flash", "models/gemini-3.8-flash-preview",
                 "models/gemini-3.7-flash", "models/gemini-2.5-pro", "models/gemini-3-pro-image",
                 "models/gemini-2.5-pro-preview-tts"]
        raw = [{"id": n, "label": None, "created": None} for n in names]
        out = [m["id"] for m in ms.select_latest("gemini", raw, current="gemini-pro-latest")]
        self.assertEqual(out[:2], ["gemini-flash-latest", "gemini-pro-latest"])
        self.assertEqual(out[2:], ["gemini-3.8-flash", "gemini-3.8-flash-preview", "gemini-3.7-flash"])
        self.assertNotIn("antigravity-preview-latest", out)


class TokenAndSaveTest(unittest.TestCase):
    S = "secret"

    def test_m6_token(self):
        t = ms.issue_token(self.S, "claude", "m1", now=1000)
        self.assertTrue(ms.verify_token(self.S, t, "claude", "m1", now=1001))
        self.assertFalse(ms.verify_token(self.S, t, "claude", "m2", now=1001))
        self.assertFalse(ms.verify_token(self.S, t, "openai", "m1", now=1001))
        self.assertFalse(ms.verify_token(self.S, t, "claude", "m1", now=1000 + ms.TOKEN_TTL + 1))
        self.assertFalse(ms.verify_token("other", t, "claude", "m1", now=1001))
        self.assertFalse(ms.verify_token(self.S, t[:-1] + "0", "claude", "m1", now=1001))
        self.assertFalse(ms.verify_token(self.S, None, "claude", "m1"))

    def test_m7_changed_model_requires_token(self):
        with self.assertRaises(ms.SettingsError):
            ms.build_document({}, {"models": {"claude": {"model": "m1"}}}, self.S)
        tok = ms.issue_token(self.S, "claude", "m1")
        doc = ms.build_document({}, {"models": {"claude": {"model": "m1", "token": tok}}}, self.S)
        self.assertEqual(doc["models"]["claude"]["model"], "m1")

    def test_m7_unchanged_model_and_primary_only_need_no_token(self):
        cur = {"models": {"claude": {"model": "m1", "tested_at": "t"}}}
        doc = ms.build_document(cur, {"primary": "openai", "models": {"claude": {"model": "m1"}}}, self.S)
        self.assertEqual(doc, {"models": {"claude": {"model": "m1", "tested_at": "t"}}, "primary": "openai"})

    def test_m7_rejects_bad_shapes(self):
        for bad in ({"primary": "x"}, {"models": {"mistral": {"model": "a"}}},
                    {"models": {"claude": {"model": "bad id!"}}}, {"models": []}):
            with self.assertRaises(ms.SettingsError, msg=bad):
                ms.build_document({}, bad, self.S)


class SaveFailureTest(unittest.TestCase):
    def test_r2_non_conflict_rpc_error_becomes_runtime_error(self):
        class Db:
            def rpc(self, *_a, **_k):
                raise ConnectionError("db down")
        with patch.dict(os.environ, {"SUPABASE_SERVICE_ROLE_KEY": "k"}), \
                patch("app.core.storage.make_supabase_client", return_value=Db()):
            with self.assertRaises(RuntimeError):
                ms.save(0, {})

    def test_r2_conflict_is_revision_conflict(self):
        class Db:
            def rpc(self, *_a, **_k):
                raise Exception("{'code': 'PT409', 'message': 'MODEL_SETTINGS_REVISION_CONFLICT'}")
        with patch.dict(os.environ, {"SUPABASE_SERVICE_ROLE_KEY": "k"}), \
                patch("app.core.storage.make_supabase_client", return_value=Db()):
            with self.assertRaises(ms.RevisionConflict):
                ms.save(0, {})


class PipelineAndTestCallTest(unittest.TestCase):
    def test_m8_outcome_records_model_from_partial(self):
        from functools import partial
        from app.core import pipeline

        def fake(messages, system, config, model=None):
            yield f"answer by {model}"
        outcome = pipeline.AnswerOutcome()
        real = pipeline._answer_providers
        pipeline._answer_providers = lambda cfg: [("Claude", partial(fake, model="claude-x"))]
        try:
            list(pipeline._stream_answer([], "", _cfg(), outcome))
        finally:
            pipeline._answer_providers = real
        self.assertEqual(outcome.model, "claude-x")
        self.assertEqual(pipeline._llm_meta(outcome)["model"], "claude-x")

    def test_m8_plain_function_leaves_model_none(self):
        from app.core import pipeline

        def fake(messages, system, config):
            yield "x"
        outcome = pipeline.AnswerOutcome()
        real = pipeline._answer_providers
        pipeline._answer_providers = lambda cfg: [("Claude", fake)]
        try:
            list(pipeline._stream_answer([], "", _cfg(), outcome))
        finally:
            pipeline._answer_providers = real
        self.assertIsNone(outcome.model)
        self.assertNotIn("model", pipeline._llm_meta(outcome))

    def test_m9_test_call_verdicts(self):
        from api.model_settings import run_test_call

        def blank(messages, system, config, model=None):
            yield "  "
            yield "\n"

        def good(messages, system, config, model=None):
            yield "정"
            raise AssertionError("첫 실질 텍스트에서 소비를 멈춰야 한다")

        def boom(messages, system, config, model=None):
            raise RuntimeError("404 model not found")
            yield  # pragma: no cover

        self.assertFalse(run_test_call(blank, None, "m")[0])
        ok, sample, _ = run_test_call(good, None, "m")
        self.assertTrue(ok)
        self.assertEqual(sample, "정")
        ok, detail, _ = run_test_call(boom, None, "m")
        self.assertFalse(ok)
        self.assertIn("404", detail)


if __name__ == "__main__":
    unittest.main(verbosity=1)
