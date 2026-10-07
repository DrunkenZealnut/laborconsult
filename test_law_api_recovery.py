#!/usr/bin/env python3
"""production-law-api-recovery 오프라인 회귀(R1~R13) — API 키·네트워크 불요.

프로덕션(Vercel) IP는 법제처에 등록돼 있지 않아 실호출이 전부 인증 실패한다(점검 시간대 조문 성공
49/185, 전부 L2 캐시 적중). 이 사이클은 등록 IP 맥의 예열(warm_law_cache.py)로 L2를 채우고 프로덕션은
`LAW_API_LIVE=off`로 캐시만 읽는다. 아래 검사는 그 전제가 **조용히** 깨지는 지점을 고정한다 —
예열 키와 조회 키의 불일치, 인증 오류를 '없음'으로 읽는 경로, 감시 공백, 엉뚱한 근거 조문.

실행: python3 test_law_api_recovery.py
"""
from __future__ import annotations

import ast
import json
import logging
import os
import subprocess
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

import requests

ROOT = Path(__file__).resolve().parent
KST = timezone(timedelta(hours=9))

ERR_XML = "<Response><result>사용자 정보 검증에 실패하였습니다.</result></Response>"
MISS_XML = "<Law></Law>"
SEARCH_MISS = "<LawSearch></LawSearch>"
LAW_XML = (
    "<법령><기본정보><법령명_한글>근로기준법</법령명_한글><시행일자>20261002</시행일자>"
    "<제개정구분>일부개정</제개정구분></기본정보>"
    # 장 제목(조문여부=전문)은 뒤따르는 조문과 같은 조문번호를 갖는다
    "<조문단위><조문번호>60</조문번호><조문여부>전문</조문여부><조문내용>제4장 근로시간과 휴식</조문내용></조문단위>"
    "<조문단위><조문번호>60</조문번호><조문여부>조문</조문여부><조문제목>연차 유급휴가</조문제목>"
    "<조문내용>제60조(연차 유급휴가)</조문내용>"
    "<항><항번호>①</항번호><항내용>① 1년간 80퍼센트 이상 출근한 근로자에게 15일</항내용></항>"
    "<항><항번호>②</항번호><항내용>② 1년 미만 근로자에게 1개월 개근 시 1일</항내용></항></조문단위>"
    "<조문단위><조문번호>76</조문번호><조문가지번호>2</조문가지번호><조문여부>조문</조문여부>"
    "<조문내용>제76조의2(직장 내 괴롭힘의 금지)</조문내용></조문단위>"
    # 조문가지번호 "0"은 가지 없음이다(검증 L8)
    "<조문단위><조문번호>5</조문번호><조문가지번호>0</조문가지번호><조문여부>조문</조문여부>"
    "<조문내용>제5조(근로조건의 준수)</조문내용></조문단위>"
    "</법령>"
)


def _resp(content: str | bytes):
    r = mock.Mock()
    r.content = content.encode() if isinstance(content, str) else content
    r.text = r.content.decode()
    r.raise_for_status = mock.Mock()
    return r


def _live(on: bool):
    return mock.patch.dict(os.environ, {"LAW_API_LIVE": "on" if on else "off"})


def _reset():
    from app.core import legal_api
    legal_api._ARTICLE_CACHE.clear()
    legal_api._OFFICIAL_NAME_CACHE.clear()
    legal_api._circuit.update({"fail_count": 0, "open_until": 0.0, "probing": False})


_PATCHES: list = []


def setUpModule():
    # 실제 Supabase(L2)로 나가지 않게 한다 — fetch_court_precedents는 import 시 로컬 .env를 읽는다.
    from app.core import legal_api
    _PATCHES.append(mock.patch.object(legal_api, "_init_supabase", return_value=None))
    _PATCHES.append(mock.patch.dict(os.environ, {"LAW_API_LIVE": "on"}))
    for p in _PATCHES:
        p.start()
    logging.disable(logging.CRITICAL)


def tearDownModule():
    logging.disable(logging.NOTSET)
    for p in reversed(_PATCHES):
        p.stop()


class ErrorRootTest(unittest.TestCase):
    """R1 — 법제처 응답을 받는 모든 곳이 `<Response>`를 LawApiAuthError로 올린다(D6)."""

    def test_r1_every_http_site_checks_error_root(self):
        tree = ast.parse((ROOT / "app/core/legal_api.py").read_text(encoding="utf-8"))
        sites = {}
        for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
            calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call)]
            gets = [c for c in calls if isinstance(c.func, ast.Attribute) and c.func.attr == "get"
                    and isinstance(c.func.value, ast.Name) and c.func.value.id == "_http"]
            if gets:
                sites[fn.name] = any(isinstance(c.func, ast.Name) and c.func.id == "_raise_if_error_root"
                                     for c in calls)
        self.assertGreaterEqual(len(sites), 8, sites)
        self.assertEqual([n for n, ok in sites.items() if not ok], [], "판정 없는 HTTP 지점")

    def test_r1_auth_error_is_a_runtime_error(self):
        from app.core import legal_api
        self.assertTrue(issubclass(legal_api.LawApiAuthError, RuntimeError), "기존 except RuntimeError 호환")
        with mock.patch.object(legal_api._http, "get", return_value=_resp(ERR_XML)):
            with self.assertRaises(legal_api.LawApiAuthError):
                legal_api.fetch_law_root("근로기준법", "k")

    def test_r1_offline_scripts_raise_instead_of_none(self):
        from app.core.legal_api import LawApiAuthError
        import fetch_court_precedents as fc
        with mock.patch.object(fc._session, "get", return_value=_resp(ERR_XML)) as g:
            with self.assertRaises(LawApiAuthError):
                fc._get_xml(fc.LAW_SEARCH_URL, {"q": 1})
        self.assertEqual(g.call_count, 1, "인증 오류는 재시도하지 않는다")
        with mock.patch.object(fc._session, "get", return_value=_resp(ERR_XML)):
            with self.assertRaises(LawApiAuthError):
                fc.search_case("2016다255941", "prec", "k")   # '미발견'(None)이 아니다

        import fetch_official_rules as fo
        with mock.patch.object(fo.requests, "get", return_value=_resp(ERR_XML)):
            with self.assertRaises(LawApiAuthError):
                fo.fetch_admrul("k", "최저임금 고시", "최저임금 고시", "고용노동부")

        import check_law_freshness as c
        from app.core import legal_api
        with mock.patch.object(legal_api._http, "get", return_value=_resp(ERR_XML)):
            with self.assertRaises(LawApiAuthError):
                c.law_versions("근로기준법", "k")

    def test_r1_precedent_collector_does_not_record_not_found_on_auth_error(self):
        src = (ROOT / "fetch_court_precedents.py").read_text(encoding="utf-8")
        handler = src[src.index("except LawApiAuthError as e:\n        # 이 사건은 기록하지 않는다"):]
        handler = handler[:handler.index("sys.exit(2)")]
        self.assertNotIn('progress["not_found"]', handler)


class SearchFailureTest(unittest.TestCase):
    """R2 — 인증 오류가 '0건'·서킷 성공이 되지 않는다. 그래프 빌드는 캐시를 지우지 않는다."""

    def setUp(self):
        _reset()

    def test_r2_searches_record_failure_not_success(self):
        from app.core import legal_api
        for fn in (legal_api.search_precedent, legal_api.search_detc, legal_api.search_nlrc):
            _reset()
            legal_api._circuit["fail_count"] = 1
            outcome: dict = {}
            with mock.patch.object(legal_api._http, "get", return_value=_resp(ERR_XML)):
                self.assertEqual(fn("2023다302838", "k", outcome=outcome), [])
            self.assertEqual(outcome["status"], "auth_error", fn.__name__)
            self.assertEqual(legal_api._circuit["fail_count"], 2, f"{fn.__name__}: 서킷에 성공을 기록하면 0이 된다")

    def test_r2_detail_fetch_auth_error(self):
        from app.core import legal_api
        for fn in (legal_api.fetch_precedent, legal_api.fetch_detc):
            _reset()
            outcome: dict = {}
            with mock.patch.object(legal_api._http, "get", return_value=_resp(ERR_XML)):
                self.assertIsNone(fn(1, "k", outcome=outcome))
            self.assertEqual(outcome["status"], "auth_error")
        _reset()
        with mock.patch.object(legal_api._http, "get", return_value=_resp(ERR_XML)):
            self.assertIsNone(legal_api.fetch_nlrc_detail(1, "k"))
        self.assertEqual(legal_api._circuit["fail_count"], 1)

    def _graph(self, name="근로기준법"):
        import networkx as nx
        G = nx.DiGraph()
        G.add_node(f"statute:{name}", type="statute", name=name)
        return G

    def _expired_cache(self, tmp: Path, name="근로기준법") -> Path:
        f = tmp / f"{name}.eflaw.json"
        f.write_text(json.dumps([{"number": 60, "title": "연차 유급휴가", "text": "옛 본문"}]), encoding="utf-8")
        old = time.time() - 8 * 86400
        os.utime(f, (old, old))
        return f

    def test_r2_graph_build_keeps_cache_on_auth_error(self):
        import build_graph
        from app.core import legal_api
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(build_graph, "CACHE_DIR", Path(d)), \
             mock.patch.dict(os.environ, {"LAW_API_KEY": "k"}), \
             mock.patch.object(legal_api, "fetch_law_root", side_effect=legal_api.LawApiAuthError("x")), \
             mock.patch.object(build_graph.time, "sleep"):
            f = self._expired_cache(Path(d))
            with self.assertRaises(legal_api.LawApiAuthError):
                build_graph.build_articles(self._graph())
            self.assertTrue(f.exists(), "만료 캐시를 먼저 지우면 인증 오류에서 조문 노드가 사라진다")

    def test_r2_graph_build_uses_stale_cache_on_other_failure(self):
        import build_graph
        from app.core import legal_api
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(build_graph, "CACHE_DIR", Path(d)), \
             mock.patch.dict(os.environ, {"LAW_API_KEY": "k"}), \
             mock.patch.object(legal_api, "fetch_law_root", side_effect=requests.ConnectionError("down")), \
             mock.patch.object(build_graph.time, "sleep"):
            f = self._expired_cache(Path(d))
            G = self._graph()
            build_graph.build_articles(G)
            self.assertTrue(f.exists())
            self.assertIn("article:근로기준법:60", G.nodes, "일시 장애에서 조문 노드를 조용히 빼지 않는다")


class FetchArticleOutcomeTest(unittest.TestCase):
    """R3 — fetch_article 결과 분류(D7). 실호출 스위치는 서킷보다 먼저다(D5)."""

    def setUp(self):
        _reset()

    def _fetch(self, *args, **kw):
        from app.core import legal_api
        outcome: dict = {}
        text = legal_api.fetch_article(*args, outcome=outcome, **kw)
        return text, outcome.get("status")

    def test_r3_live_cache_and_failures(self):
        from app.core import legal_api
        with mock.patch.object(legal_api._http, "get", return_value=_resp(LAW_XML)) as g:
            text, status = self._fetch("근로기준법", 60, "k")
            self.assertIn("연차 유급휴가", text)
            self.assertEqual(status, "ok_live")
            self.assertEqual(self._fetch("근로기준법", 60, "k")[1], "ok_cache", "L1 적중")
            self.assertEqual(g.call_count, 1)
            self.assertEqual(self._fetch("근로기준법", 999, "k"), (None, "miss"), "조문 없음")
        _reset()
        with mock.patch.object(legal_api._http, "get", side_effect=[_resp(MISS_XML), _resp(SEARCH_MISS)]):
            self.assertEqual(self._fetch("근로기준법", 60, "k"), (None, "miss"), "빈 루트")
        _reset()
        with mock.patch.object(legal_api._http, "get", return_value=_resp(ERR_XML)):
            self.assertEqual(self._fetch("근로기준법", 60, "k"), (None, "auth_error"))
        self.assertEqual(legal_api._circuit["fail_count"], 1)
        _reset()
        with mock.patch.object(legal_api._http, "get", side_effect=requests.ConnectionError("down")):
            self.assertEqual(self._fetch("근로기준법", 60, "k"), (None, "error"))
        _reset()
        legal_api._circuit.update({"fail_count": 3, "open_until": time.time() + 30})
        with mock.patch.object(legal_api._http, "get") as g:
            self.assertEqual(self._fetch("근로기준법", 60, "k"), (None, "skipped_circuit"))
            g.assert_not_called()

    def test_r3_l2_hit_is_ok_cache(self):
        from app.core import legal_api
        key = legal_api.article_cache_key("근로기준법", 60)
        with mock.patch.object(legal_api, "_l2_cache_get", side_effect=lambda k, **_: "L2 본문" if k == key else None), \
             mock.patch.object(legal_api._http, "get") as g:
            self.assertEqual(self._fetch("근기법", 60, "k"), ("L2 본문", "ok_cache"), "약칭도 같은 키")
            g.assert_not_called()

    def test_r3b_l2_read_failure_is_retried_then_error_not_miss(self):
        """쉬었던 HTTP/2 연결이 끊기면 L2 조회가 응답 없이 실패한다(실측 topic30 24번) — 1회 재시도하고,
        그래도 실패하면 '예열 누락(miss)'이 아니라 `error`다."""
        from app.core import legal_api

        class Flaky:
            def __init__(self, fails):
                self.fails, self.calls = fails, 0

            def table(self, *_):
                return self

            def select(self, *_):
                return self

            def eq(self, *_):
                return self

            def gt(self, *_):
                return self

            def maybe_single(self):
                return self

            def execute(self):
                self.calls += 1
                if self.calls <= self.fails:
                    raise ConnectionError("Server disconnected")
                return NS(data={"content": "제60조 본문"})
        for fails, want in ((1, ("제60조 본문", "ok_cache")), (2, (None, "error"))):
            _reset()
            db = Flaky(fails)
            with _live(False), mock.patch.object(legal_api, "_init_supabase", return_value=db):
                self.assertEqual(self._fetch("근로기준법", 60, "k"), want, f"실패 {fails}회")
            self.assertEqual(db.calls, 2, "재시도는 1회")
        self.assertNotIn(legal_api.article_cache_key("근로기준법", 60), legal_api._ARTICLE_CACHE)

    def test_r3b_l2_client_has_short_timeout(self):
        from app.core import legal_api
        src = (ROOT / "app/core/legal_api.py").read_text(encoding="utf-8")   # _init_supabase는 모듈 대역 중
        body = src[src.index("def _init_supabase"):src.index("class L2ReadError")]
        self.assertIn("make_supabase_client(postgrest_timeout=L2_TIMEOUT)", body)
        self.assertLessEqual(legal_api.L2_TIMEOUT, 10, "답변 경로의 읽기 — 기본 120초면 DB 장애 때 답변이 멈춘다")

    def test_r3_live_off_reads_cache_only(self):
        from app.core import legal_api
        with _live(False), mock.patch.object(legal_api._http, "get") as g:
            self.assertEqual(self._fetch("근로기준법", 60, "k"), (None, "miss"), "예열 대상인데 키가 없다")
            self.assertEqual(self._fetch("선원법", 3, "k"), (None, "skipped_unwarmed"), "예열 대상이 아니다")
            g.assert_not_called()
        self.assertNotIn(legal_api.article_cache_key("근로기준법", 60), legal_api._ARTICLE_CACHE,
                         "차단은 미매칭 표지를 남기지 않는다 — 나중에 예열된 행이 자정까지 가려진다")

    def test_r3_live_switch_is_checked_before_circuit(self):
        from app.core import legal_api
        legal_api._circuit.update({"fail_count": 3, "open_until": time.time() - 1})   # 다음 요청이 probe
        with _live(False):
            self.assertEqual(self._fetch("근로기준법", 60, "k")[1], "miss")
        self.assertFalse(legal_api._circuit["probing"], "off 판정이 서킷 probe를 소비하면 안 된다")

    def test_r3_live_switch_is_read_at_call_time(self):
        from app.core import legal_api
        with _live(False):
            self.assertEqual(legal_api.law_api_live_mode(), "off")
        with _live(True):
            self.assertEqual(legal_api.law_api_live_mode(), "on")


class MetadataV2Test(unittest.TestCase):
    """R4 — metadata.law_api v2: 요청이 있으면 항상 기록, 조문·판례 분리, 같은 조문은 한 번만 센다."""

    def _run_pipeline(self, analysis, *, law_api_key="k", l2=None, query="연차 며칠인가요"):
        from app.config import AppConfig
        from app.core import legal_api, pipeline
        from app.models.session import Session
        saved = []
        cfg = AppConfig(openai_client=object(), pinecone_index=None, claude_client=object(),
                        gemini_api_key=None, supabase=object())
        cfg.law_api_key = law_api_key

        def _fake(messages, system, config):
            yield "답변 본문입니다."
        l2 = l2 or {}
        with mock.patch.object(pipeline, "analyze_intent", return_value=analysis), \
             mock.patch.object(pipeline, "_answer_providers", lambda c: [("Claude", _fake)]), \
             mock.patch.object(pipeline, "save_conversation", lambda sb, rec: saved.append(rec) or "c1"), \
             mock.patch.object(pipeline, "save_session_data", lambda *a, **k: None), \
             mock.patch.object(legal_api, "_l2_cache_get", side_effect=lambda k, **_: l2.get(k)), \
             mock.patch.object(legal_api._http, "get", side_effect=AssertionError("실호출 금지")):
            list(pipeline.process_question(query, Session(id="lawapi1"), cfg))
        self.assertTrue(saved, "대화가 저장되지 않음")
        return saved[0].metadata or {}

    def test_r4_recorded_always_and_deduped_across_21_22(self):
        from app.core import legal_api
        from app.models.schemas import AnalysisResult
        _reset()
        analysis = AnalysisResult(question_summary="연차", relevant_laws=["근로기준법 제60조"],
                                  consultation_type="procedure_guide", consultation_topic="연차휴가")
        l2 = {legal_api.article_cache_key("근로기준법", 60): "제60조 본문",
              legal_api.article_cache_key("근로기준법", 61): "제61조 본문"}
        with _live(False):
            meta = self._run_pipeline(analysis, l2=l2)
        law = meta.get("law_api")
        self.assertIsNotNone(law, "성공한 대화도 기록한다(성공률 분모)")
        self.assertEqual(law["live"], "off")
        a = law["articles"]
        self.assertEqual((a["requested"], a["ok"], a["ok_cache"]), (2, 2, 2),
                         "제60조는 2-1에서만, 2-2는 기본 조문 중 제61조만 — 같은 조문을 두 번 세지 않는다")
        p = law["precedents"]
        self.assertEqual(p["requested"], p["skipped"], "off면 판례·판정문 검색은 전부 건너뛴다")

    def test_r4_not_recorded_without_requests(self):
        from app.models.schemas import AnalysisResult
        _reset()
        meta = self._run_pipeline(AnalysisResult(question_summary="연차", consultation_topic="연차휴가",
                                                 consultation_type="procedure_guide"), law_api_key=None)
        self.assertNotIn("law_api", meta)


class CacheKeyTest(unittest.TestCase):
    """R5 — 약칭·공백 변형·가운뎃점 3종이 같은 v5 키(D3)."""

    def test_r5_equivalent_names_share_a_key(self):
        from app.core.legal_api import article_cache_key as k
        self.assertTrue(k("근로기준법", 60).startswith("v5:"))
        groups = [
            ["근로기준법", "근기법", "근로 기준법"],
            ["근로자퇴직급여 보장법", "근로자퇴직급여보장법", "퇴직급여법", "근퇴법"],
            ["외국인근로자의 고용 등에 관한 법률", "외국인고용법"],
            ["산업재해보상보험법", "산재법", "산재보험법"],
            ["노동조합 및 노동관계조정법", "노조법", "노동조합법"],
            ["남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률", "남녀고용평등과 일·가정 양립 지원에 관한 법률",
             "남녀고용평등과 일‧가정 양립 지원에 관한 법률", "남녀고용평등법", "남녀 고용평등법",
             # 의도분석 LLM은 가운뎃점을 아예 빼고 쓰기도 한다(topic30 1번 실측)
             "남녀고용평등과일가정양립지원에관한법률"],
        ]
        for names in groups:
            self.assertEqual({k(n, 19, 2, 1) for n in names}, {k(names[0], 19, 2, 1)}, names)
        self.assertNotEqual(k("근로기준법", 60, None, 2), k("근로기준법", 602))
        self.assertEqual(k("근로기준법", 76, 2), "v5:근로기준법_76의2")

    def test_r5_variants_of_warmed_laws_resolve_to_official_name(self):
        from app.core.legal_api import canonical_law_name
        self.assertEqual(canonical_law_name("남녀고용평등과일가정양립지원에관한법률"),
                         "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률", "조문 머리글·LM 조회명은 정식명")
        self.assertEqual(canonical_law_name("근로자퇴직급여보장법"), "근로자퇴직급여 보장법")
        self.assertEqual(canonical_law_name("선원 법"), "선원 법", "예열 밖 법령은 정규화한 원명")

    def test_r5_ref_key_dedupes_variants(self):
        from app.core.legal_api import law_ref_key, select_law_refs
        self.assertEqual(law_ref_key("근기법 제60조"), law_ref_key("근로기준법 제60조"))
        self.assertEqual(law_ref_key("대법원 2023다302838"), law_ref_key("2023다302838"))
        self.assertEqual(select_law_refs(["근로기준법 제60조", "근기법 제60조", "근로기준법 제61조"]),
                         ["근로기준법 제60조", "근로기준법 제61조"])


class ParagraphFallbackTest(unittest.TestCase):
    """R6 — 항 키가 없으면 같은 조문 키(D4). 조문 키의 미매칭 표지는 항 키로 복사하지 않는다."""

    def setUp(self):
        _reset()

    def test_r6_paragraph_falls_back_to_article_key(self):
        from app.core import legal_api
        whole = legal_api.article_cache_key("근로기준법", 60)
        para = legal_api.article_cache_key("근로기준법", 60, None, 9)
        with _live(False), \
             mock.patch.object(legal_api, "_l2_cache_get", side_effect=lambda k, **_: "조문 전체" if k == whole else None):
            outcome: dict = {}
            self.assertEqual(legal_api.fetch_article("근로기준법", 60, "k", paragraph=9, outcome=outcome), "조문 전체")
        self.assertEqual(outcome["status"], "ok_cache")
        self.assertEqual(legal_api._ARTICLE_CACHE[para][1], "조문 전체", "항 키 아래 L1에도 저장")

    def test_r6_article_sentinel_is_a_miss_and_not_copied(self):
        from app.core import legal_api
        whole = legal_api.article_cache_key("근로기준법", 60)
        para = legal_api.article_cache_key("근로기준법", 60, None, 1)
        legal_api._cache_set(whole, legal_api._MISS_SENTINEL)
        with mock.patch.object(legal_api._http, "get") as g:
            outcome: dict = {}
            self.assertIsNone(legal_api.fetch_article("근로기준법", 60, "k", paragraph=1, outcome=outcome))
            g.assert_not_called()
        self.assertEqual(outcome["status"], "miss")
        self.assertNotIn(para, legal_api._ARTICLE_CACHE)


class WarmRowsTest(unittest.TestCase):
    """R7 — 예열 행의 키·텍스트가 프로덕션 조회 함수와 같다(바이트 동일)."""

    def test_r7_rows_match_runtime_key_and_text(self):
        import xml.etree.ElementTree as ET
        import warm_law_cache as w
        from app.core.legal_api import _extract_article, article_cache_key
        root = ET.fromstring(LAW_XML)
        rows = w.build_rows(root, "근기법", "2026-10-08T00:00:00Z", "2026-10-06T00:00:00Z")
        by_key = {r["cache_key"]: r for r in rows}
        expected = {
            article_cache_key("근로기준법", 60): (60, None, None),
            article_cache_key("근로기준법", 60, None, 1): (60, None, 1),
            article_cache_key("근로기준법", 60, None, 2): (60, None, 2),
            article_cache_key("근로기준법", 76, 2): (76, 2, None),
            article_cache_key("근로기준법", 5): (5, None, None),
        }
        self.assertEqual(set(by_key), set(expected), "조의N·항·가지번호 0·장 제목 처리")
        for key, (no, sub, para) in expected.items():
            self.assertEqual(by_key[key]["content"], _extract_article(root, no, para, sub), key)
            self.assertEqual(by_key[key]["law_name"], "근로기준법", "정식명")
            self.assertEqual(by_key[key]["source_type"], "law_warm")
            self.assertEqual(by_key[key]["expires_at"], "2026-10-08T00:00:00Z")
        self.assertIn("근로조건의 준수", by_key[article_cache_key("근로기준법", 5)]["content"],
                      "가지번호 '0'을 가지로 읽으면 제5조가 사라진다")
        self.assertNotIn("제4장", by_key[article_cache_key("근로기준법", 60)]["content"])


class WarmExpiryTest(unittest.TestCase):
    """R8 — 만료 min(다음 시행일 00:00 KST, +3일), 목록 실패 → 다음 자정 + 경고, 머리글 불일치 → 쓰지 않음."""

    NOW = datetime(2026, 10, 6, 12, 0, tzinfo=KST)

    def test_r8_expiry(self):
        import warm_law_cache as w
        exp, nxt = w.expiry_for([{"date": "20261008"}, {"date": "20261002"}], "20261006", self.NOW)
        self.assertEqual((exp, nxt), (datetime(2026, 10, 8, tzinfo=KST), "20261008"))
        exp, nxt = w.expiry_for([{"date": "20270101"}, {"date": "20261002"}], "20261006", self.NOW)
        self.assertEqual((exp, nxt), (self.NOW + timedelta(days=3), "20270101"), "상한 3일")
        exp, nxt = w.expiry_for([{"date": "20261002"}], "20261006", self.NOW)
        self.assertEqual((exp, nxt), (self.NOW + timedelta(days=3), None))

    def test_r8_version_list_failure_expires_at_next_midnight(self):
        import xml.etree.ElementTree as ET
        import check_law_freshness as c
        import warm_law_cache as w
        with mock.patch.object(c, "law_versions", side_effect=requests.ConnectionError("down")), \
             mock.patch.object(w, "fetch_law_root", return_value=ET.fromstring(LAW_XML)) as f:
            r = w.warm_one("근로기준법", "k", "20261006", self.NOW)
        self.assertNotIn("ef_yd", f.call_args.kwargs, "판본을 모르면 지정하지 않는다")
        self.assertEqual(r["expires"], w._iso(datetime(2026, 10, 7, tzinfo=KST)))
        self.assertIn("판본 목록 조회 실패", r["warning"])

    def test_r8_pinned_version_and_header_check(self):
        import xml.etree.ElementTree as ET
        import check_law_freshness as c
        import warm_law_cache as w
        versions = [{"date": "20261008"}, {"date": "20261002"}]
        with mock.patch.object(c, "law_versions", return_value=versions), \
             mock.patch.object(w, "fetch_law_root", return_value=ET.fromstring(LAW_XML)) as f:
            r = w.warm_one("근로기준법", "k", "20261006", self.NOW)
        self.assertEqual(f.call_args.kwargs["ef_yd"], "20261002", "기준판을 명시한다")
        self.assertEqual((r["ref"], r["next"]), ("20261002", "20261008"))
        stale = LAW_XML.replace("<시행일자>20261002</시행일자>", "<시행일자>20250101</시행일자>")
        with mock.patch.object(c, "law_versions", return_value=versions), \
             mock.patch.object(w, "fetch_law_root", return_value=ET.fromstring(stale)):
            with self.assertRaises(w.WarmError):
                w.warm_one("근로기준법", "k", "20261006", self.NOW)

    def _main(self, warm_one, db):
        import warm_law_cache as w
        with mock.patch("dotenv.load_dotenv"), mock.patch.dict(os.environ, {"LAW_API_KEY": "k"}), \
             mock.patch.object(w, "warm_law_names", return_value=["근로기준법", "고용보험법"]), \
             mock.patch.object(w, "warm_one", side_effect=warm_one), \
             mock.patch.object(w.time, "sleep"), \
             mock.patch("app.core.storage.make_supabase_client", return_value=db) as mk, \
             mock.patch("builtins.print"):
            return w.main([]), mk

    def test_r8_auth_error_exits_2_without_writes(self):
        from app.core.legal_api import LawApiAuthError
        db = mock.Mock()
        code, mk = self._main(LawApiAuthError("검증 실패"), db)
        self.assertEqual(code, 2)
        mk.assert_not_called()

    def test_r8_partial_failure_is_recorded_in_status(self):
        import warm_law_cache as w

        class Db:
            def __init__(self):
                self.upserts = []

            def table(self, *_):
                return self

            def upsert(self, payload, **_):
                self.upserts.append(payload)
                self._data = payload if isinstance(payload, list) else [payload]
                return self

            def select(self, *_):
                self._data = []
                return self

            def eq(self, *_):
                return self

            def execute(self):
                return NS(data=self._data)

        rows = [{"cache_key": "v5:근로기준법_60", "content": "x"}]
        ok = {"rows": rows, "ref": "20261002", "next": "20261008", "expires": "2026-10-08T00:00:00Z",
              "warning": None}

        def warm_one(name, *_):
            if name == "고용보험법":
                raise w.WarmError("판본 불일치")
            return ok
        db = Db()
        code, _ = self._main(warm_one, db)
        self.assertEqual(code, 1)
        status = json.loads(db.upserts[-1]["content"])
        self.assertEqual(status["rows"], 1)
        self.assertIn("고용보험법", status["laws_failed"], "감시 ①이 실패 법령을 본다")
        self.assertEqual(db.upserts[-1]["expires_at"], "2099-12-31T00:00:00Z")


class KeywordLawsTest(unittest.TestCase):
    """R9 — 키워드 조문 규칙의 양성·반례(고신뢰 패턴만, 최대 3개)."""

    CASES = [
        ("육아휴직을 쓰고 싶은데 회사가 거부해요", "제19조"),
        ("육아기 근로시간 단축 신청했어요", "제19조의2"),
        ("현재 육아 근로단축 근무를 하고 있어요", "제19조의2"),
        ("가정돌봄휴가를 쓰려고 하는데 거부당했어요", "제22조의2"),
        ("배우자 출산휴가는 며칠인가요", "제18조의2"),
        ("아내가 출산했는데 휴가가 있나요", "제18조의2"),
        ("배우자 유산휴가 있나요", "제18조의4"),
        ("가족돌봄휴가 쓸 수 있나요", "제22조의2"),
        ("임신 12주인데 근로시간 단축 신청 가능한가요", "근로기준법 제74조"),
        ("임신 초기 유산 위험으로 근무시간 단축 요청 가능한가요", "근로기준법 제74조"),
        ("출산전후휴가 90일 쓰는데 회사가 싫어해요", "근로기준법 제74조"),
        ("E-9 비자인데 사업장 변경하고 싶어요", "제25조"),
        ("외국인 근로자인데 사업장을 바꾸고 싶어요", "제25조"),
        ("E-9비자로 3년 근무하면 회사 변경이 몇 번 가능한가요", "제25조"),
        ("불법파견이면 직접고용 의무가 있나요", "제6조의2"),
        ("고등학생 알바인데 밤 10시 넘어서 일해요", "근로기준법 제70조"),
        ("취업규칙 불이익 변경에 동의 안 했어요", "근로기준법 제94조"),
        ("교육비 반환 약정이 있어요", "근로기준법 제20조"),
        ("경영상 이유로 해고 통보를 받았어요", "근로기준법 제24조"),
        ("임금명세서를 안 줘요", "근로기준법 제48조"),
        ("휴업수당은 얼마인가요", "근로기준법 제46조"),
        ("회식 자리에서 팀장이 성적인 농담을 해요", "제14조"),
        # law-article-coverage — 나머지 양성·반례는 test_law_article_coverage.py AC1
        ("징계로 감봉 3개월을 받았어요", "근로기준법 제95조"),
        ("장사가 안된다는 이유로 갑자기 해고통보를 받았어요", "근로기준법 제24조"),
        ("특별연장근로 인가 없이 야근시켜요", "근로기준법 시행규칙 제9조"),
    ]
    NEGATIVES = [
        ("아내가 임신 중인데 단축근무 되나요", "제74조"),
        ("외국인 근로자 퇴직금 계산", "제25조"),
        ("E-9 근로자인데 출국만기보험이랑 퇴직금 차이가 뭔가요", "제25조"),   # CodeRabbit PR #102
        ("고용허가제 외국인 근로자 최저임금 적용되나요", "제25조"),
        ("경영상 어려움으로 임금이 삭감됐어요", "제24조"),
        ("연차휴가 며칠인가요", "법률 제"),
        ("주휴수당 계산해주세요", "제"),
    ]

    def test_r9_positive_and_negative(self):
        from app.core.law_catalog import keyword_laws
        for q, want in self.CASES:
            refs = keyword_laws(q)
            self.assertTrue(any(r.endswith(want) or want in r for r in refs), f"{q!r} → {refs}")
        for q, unwanted in self.NEGATIVES:
            refs = keyword_laws(q)
            self.assertFalse(any(unwanted in r for r in refs), f"{q!r} → {refs}")
        self.assertIn("남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률 제18조의4", keyword_laws("배우자 사산"),
                      "배우자 유산·사산휴가는 제18조의2가 아니라 제18조의4")

    def test_r9_limit_and_all_refs_warmed(self):
        from app.core.legal_api import _law_key, canonical_law_name, parse_law_reference
        from app.core.law_catalog import KEYWORD_LAWS, keyword_laws, warm_law_keys
        many = "육아휴직 · 배우자 출산휴가 · 가족돌봄휴가 · 임금명세서 · 휴업수당"
        self.assertEqual(len(keyword_laws(many)), 3)
        for rule in KEYWORD_LAWS:
            for ref in rule.refs + rule.extra:          # 보충 조문도 예열 대상이어야 한다(law-article-coverage D1)
                parsed = parse_law_reference(ref)
                self.assertIsNotNone(parsed, ref)
                self.assertIn(_law_key(canonical_law_name(parsed["law"])), warm_law_keys(),
                              f"{ref}: 예열 대상이 아니면 프로덕션(실호출 꺼짐)에서 조회되지 않는다")


class RefSelectionTest(unittest.TestCase):
    """R10 — 2-1·2-2 순서·상한·키 제외. 성희롱이면 양쪽 모두 제76조의2·3 없음, 원 주제 기본 조문 유지."""

    def _consult(self, topic, relevant, *, exclude=(), drop=()):
        from app.core import legal_consultation as lc
        from app.config import AppConfig
        cfg = AppConfig(openai_client=None, pinecone_index=None, claude_client=None)
        cfg.law_api_key = "k"
        with mock.patch.object(lc, "fetch_relevant_articles", return_value=None) as f:
            lc.process_consultation("q", topic, relevant, cfg, exclude_keys=exclude, drop_refs=drop)
        return f.call_args.args[0] if f.called else []

    def test_r10_order_cap_and_exclusion(self):
        from app.core.legal_api import law_ref_key
        from app.core.pipeline import _article_refs_21
        refs = _article_refs_21("육아휴직 거부당했어요", NS(relevant_laws=[
            "근로기준법 제60조", "근기법 제60조", "고용보험법 제70조", "고용보험법 제73조",
            "고용보험법 제74조", "고용보험법 제75조"]), False)
        self.assertEqual(refs[0], "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률 제19조", "키워드가 먼저")
        self.assertEqual(len(refs), 5)
        self.assertEqual(sum(r.endswith("제60조") for r in refs), 1, "정규화 키로 중복 제거")
        self.assertEqual(_article_refs_21("육아휴직", None, False)[:1],
                         ["남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률 제19조"], "의도분석이 없어도 돈다")
        got = self._consult("근로시간·휴일", ["근로기준법 제50조"],
                            exclude={law_ref_key("근로기준법 제50조")})
        self.assertEqual(got[0], "근로기준법 제53조", "주제 기본 조문이 먼저, 2-1 키는 뺀다")
        self.assertEqual(len(got), 5, "2-2 상한 5")

    def test_r10_sexual_harassment_drops_76_keeps_topic_defaults(self):
        from app.core.law_catalog import SEXUAL_HARASSMENT_DROP_REFS as drop
        from app.core.pipeline import _article_refs_21, _is_sexual_query
        q = "팀장이 성추행을 해서 신고했더니 해고됐어요"
        self.assertTrue(_is_sexual_query(q))
        refs21 = _article_refs_21(q, NS(relevant_laws=["근로기준법 제76조의2", "근로기준법 제23조"]), True)
        self.assertFalse(any("제76조의" in r for r in refs21), refs21)
        self.assertIn("남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률 제12조", refs21)
        fired = self._consult("해고·징계", ["근로기준법 제76조의3 제2항"], drop=drop)
        self.assertIn("근로기준법 제23조", fired, "성희롱 + 해고 → 해고 기본 조문 유지")
        self.assertFalse(any("제76조의" in r for r in fired), fired)
        harassment = self._consult("직장내괴롭힘", [], drop=drop)
        self.assertEqual(harassment, ["남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률 제14조의2"])

    def test_r10_pipeline_wiring(self):
        import inspect
        from app.core import pipeline
        src = inspect.getsource(pipeline.process_question)
        self.assertIn("article_refs_21 = _article_refs_21(query, analysis, sexual)", src)
        self.assertIn("if article_refs_21 and config.law_api_key:", src)
        self.assertIn("exclude_keys={law_ref_key(r) for r in article_refs_21}", src)
        self.assertIn("drop_refs=SEXUAL_HARASSMENT_DROP_REFS if sexual else ()", src)
        self.assertNotIn('info.get("reason") == "sexual"', inspect.getsource(pipeline._consultation_allowed))


class MonitorTest(unittest.TestCase):
    """R11 — 폴백 감시의 법령 조건 ①②③(D11)."""

    NOW = datetime(2026, 10, 7, 3, 0, tzinfo=timezone.utc)

    def _status(self, **kw):
        s = {"at": "2026-10-06T15:10:00Z", "rows": 7473, "prev_rows": 7473, "laws_ok": ["근로기준법"],
             "laws_failed": {}}
        s.update(kw)
        return s

    @staticmethod
    def _row(i, requested=3, ok=3, unwarmed=0, live="off", auth=0, synthetic=False, deleted=0):
        meta = {"law_api": {"live": live,
                            "articles": {"requested": requested, "ok": ok, "skipped_unwarmed": unwarmed,
                                         "auth_error": auth, "deleted": deleted},
                            "precedents": {"requested": 1, "skipped": 1}}}
        if synthetic:
            meta["synthetic"] = True
        return {"id": i, "created_at": f"2026-10-06T{i:02d}:00:00Z", "metadata": meta}

    def test_r11_warm_status(self):
        import check_llm_fallback as c
        self.assertEqual(c.judge_law([], self._status(), self.NOW).status, "ok")
        for status in (None, self._status(at="2026-10-05T10:00:00Z"),
                       self._status(laws_failed={"소득세법": "Timeout"}),
                       self._status(rows=5000, prev_rows=7473)):
            self.assertEqual(c.judge_law([], status, self.NOW).status, "alert", status)
        self.assertEqual(c.judge_law([], self._status(rows=7000, prev_rows=7473), self.NOW).status, "ok",
                         "감소 20% 이하는 정상")

    def test_r11_ok_rate(self):
        import check_llm_fallback as c
        low = [self._row(i, requested=3, ok=2) for i in range(10)]
        v = c.judge_law(low, self._status(), self.NOW)
        self.assertEqual(v.status, "alert")
        self.assertAlmostEqual(v.ok_rate, 20 / 30)
        few = [self._row(i, requested=3, ok=0) for i in range(5)]       # 분모 15 < 20 → 보류
        self.assertEqual(c.judge_law(few, self._status(), self.NOW).status, "ok")
        unwarmed = [self._row(i, requested=3, ok=2, unwarmed=1) for i in range(10)]
        self.assertEqual(c.judge_law(unwarmed, self._status(), self.NOW).status, "ok", "예열 밖 법령은 분모에서 뺀다")
        deleted = [self._row(i, requested=3, ok=2, deleted=1) for i in range(10)]
        self.assertEqual(c.judge_law(deleted, self._status(), self.NOW).status, "ok",
                         "삭제된 조문 요청(law-article-coverage D5)도 없는 조문 요청과 같이 분모에서 뺀다")
        noisy = low + [self._row(20 + i, ok=0, synthetic=True) for i in range(10)]
        noisy += [{"id": 99, "created_at": "2026-10-06T23:00:00Z",
                   "metadata": {"law_api": {"requested": 9, "ok": 0, "miss": 9}}}]   # 옛 평평한 구조
        self.assertAlmostEqual(c.judge_law(noisy, self._status(), self.NOW).ok_rate, 20 / 30,
                               msg="합성·옛 구조는 건너뛴다")

    def test_r11_auth_error_when_live(self):
        import check_llm_fallback as c
        rows = [self._row(i) for i in range(10)]
        self.assertEqual(c.judge_law(rows + [self._row(11, live="on", auth=1)], self._status(), self.NOW).status,
                         "alert")
        self.assertEqual(c.judge_law(rows + [self._row(11, live="off", auth=1)], self._status(), self.NOW).status,
                         "ok")

    def test_r11_status_query_failure_exits_2(self):
        import check_llm_fallback as c

        class Db:
            def table(self, name):
                self.name = name
                return self

            def select(self, *_):
                return self

            def order(self, *_a, **_k):
                return self

            def range(self, *_):
                self.data = []
                return self

            def eq(self, *_):
                raise RuntimeError("permission denied")

            def execute(self):
                return self
        with mock.patch("app.core.storage.make_supabase_client", return_value=Db()), \
             mock.patch("sys.argv", ["check_llm_fallback.py"]), mock.patch("builtins.print"):
            self.assertEqual(c.main(), 2)

    def test_r11_fetch_counts_distinct_rows_across_pages(self):
        """페이지 경계 행이 다음 페이지에 다시 와도(새 행 저장) 같은 행을 두 번 세지 않는다(CodeRabbit PR #102)."""
        import check_llm_fallback as c
        rows = [self._row(i) for i in range(12)]   # 조문 요청 행 12개, 최신순 정렬은 아래 페이지가 맡는다
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        pages = [rows[0:3], rows[2:5], rows[5:8], rows[8:11], rows[11:12]]   # 경계 행이 겹친다

        class Db:
            def __init__(self):
                self.calls = 0

            def table(self, *_):
                return self

            def select(self, *_):
                return self

            def order(self, *_a, **_k):
                return self

            def range(self, a, b):
                self.data = pages[self.calls] if self.calls < len(pages) else []
                self.calls += 1
                return self

            def execute(self):
                return self
        db = Db()
        with mock.patch.object(c, "PAGE_SIZE", 3):
            got = c.fetch_recent_law(db, window=6)
        distinct = {r["id"] for r in got}
        self.assertGreaterEqual(len(distinct), 6, "중복을 빼고도 window개를 모을 때까지 읽는다")
        self.assertEqual(db.calls, 3, "중복을 두 번 세면 2페이지(행 6개, 실제 5개)에서 멈춘다 — 경계가 겹치면 더 읽어야 한다")

    def test_r11_monitor_does_not_import_requests_stack(self):
        src = (ROOT / "check_llm_fallback.py").read_text(encoding="utf-8")
        self.assertNotIn("legal_api", src.split('"""', 2)[2], "Actions는 supabase만 설치한다")


class CatalogTest(unittest.TestCase):
    """R12 — 예열 대상 = 현행성 점검 대상, 외국인고용법 포함."""

    def test_r12_warm_names_equal_watched(self):
        import check_law_freshness as c
        from app.core.legal_api import _law_key
        from app.core.law_catalog import BASE_LAWS, warm_law_names
        names = warm_law_names()
        self.assertEqual(names, c._watched_laws())
        self.assertIn("외국인근로자의 고용 등에 관한 법률", names)
        self.assertTrue(set(BASE_LAWS) <= set(names))
        self.assertEqual(len({_law_key(n) for n in names}), len(names), "표기 차이 중복 없음")


class RepoTest(unittest.TestCase):
    """R13 — 설정 예시와 신규 모듈의 git 추적(미추적이면 Vercel 500)."""

    def test_r13_env_example(self):
        self.assertIn("LAW_API_LIVE=", (ROOT / ".env.example").read_text(encoding="utf-8"))

    def test_r13_new_modules_tracked(self):
        try:
            out = subprocess.run(["git", "ls-files", "--error-unmatch", "app/core/law_catalog.py",
                                  "warm_law_cache.py"], cwd=ROOT, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            self.skipTest("git 없음")
        self.assertEqual(out.returncode, 0, f"git 추적 대상이 아니다 — 커밋에서 빠지면 Vercel import 오류: {out.stderr}")


if __name__ == "__main__":
    unittest.main(verbosity=1)
