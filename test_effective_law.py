"""기준일 판본 조회 + 그래프 판례 재구축 회귀 테스트 (effective-law-and-graph-precedents).

오프라인·API 키 불요(CI). 막는 실패는 전부 **조용했다**:
- `target=law&LM=`이 시행 예정 개정이 섞인 본문을 현행 헤더로 돌려줬다(근로기준법 18조문·
  고용보험법 6조문, 2026-10-04 실측). 헤더만 보던 현행성 검증은 ✅를 냈다.
- 손으로 쓴 그래프 판례표 8건 중 2건만 맞았다. 그래프 컨텍스트가 인용 화이트리스트에
  들어가 오인용(2019다293449 = 동산인도를 "주휴수당 판례"로)이 검증을 통과했다.
- 규칙 블록·계산기가 제시한 판례가 화이트리스트 밖이라 정당한 인용이 지워질 수 있었다.

설계: docs/02-design/features/effective-law-and-graph-precedents.design.md §8 (E1~E17),
§13 C12~C14(E18·E19), gap 분석 후속(E20).
"""
from __future__ import annotations

import ast
import inspect
import json
import re
import unittest
import unittest.mock as mock
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parent
KST = timezone(timedelta(hours=9))


def _resp(xml: str):
    return NS(content=xml.encode(), raise_for_status=lambda: None)


def _law_target_uses(path: str) -> list[int]:
    """코드(주석·docstring 제외)에서 target=law 사용 줄. dict·키워드 인자·URL 문자열 모두."""
    src = (ROOT / path).read_text(encoding="utf-8")
    tree = ast.parse(src)
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                docs.add(id(body[0].value))
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if (isinstance(k, ast.Constant) and k.value == "target"
                        and isinstance(v, ast.Constant) and v.value == "law"):
                    hits.append(node.lineno)
        elif isinstance(node, ast.keyword):
            if node.arg == "target" and isinstance(node.value, ast.Constant) and node.value.value == "law":
                hits.append(node.value.lineno)
        elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
              and id(node) not in docs and re.search(r"target=law\b", node.value)):
            hits.append(node.lineno)
    return sorted(hits)


class EflawSwitchTest(unittest.TestCase):
    """E1·E4·E12 — 조회 경로."""

    def test_e1_no_target_law_in_lookup_files(self):
        for path in ("app/core/legal_api.py", "fetch_official_rules.py",
                     "build_graph.py", "check_law_freshness.py"):
            self.assertEqual(_law_target_uses(path), [], f"{path}: target=law 금지(시행 예정분 혼입)")

    def test_e1_detector_catches_variants(self):
        """탐지기 자체 검증 — dict·키워드·URL 형태를 잡고 주석·docstring은 무시한다."""
        import tempfile, os
        code = ('"""docstring target=law"""\n# target=law 주석\n'
                'a = {"target": "law"}\nf(target="law")\nu = "https://x/?target=law&LM=1"\n')
        with tempfile.NamedTemporaryFile("w", suffix=".py", dir=ROOT, delete=False,
                                         encoding="utf-8") as fh:
            fh.write(code)
        try:
            self.assertEqual(_law_target_uses(os.path.basename(fh.name)), [3, 4, 5])
        finally:
            os.unlink(fh.name)

    def _root(self, xml, **kw):
        from app.core import legal_api
        with mock.patch.object(legal_api._http, "get", return_value=_resp(xml)) as g:
            out = legal_api.fetch_law_root("남녀고용평등과 일·가정 양립 지원에 관한 법률", "k", **kw)
        return out, g

    def test_e4_gates_and_params(self):
        ok = ("<법령><기본정보><법령명_한글>남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률</법령명_한글>"
              "<제개정구분>일부개정</제개정구분></기본정보></법령>")
        root, g = self._root(ok)
        self.assertIsNotNone(root)
        params = g.call_args.kwargs["params"]
        self.assertEqual(params["target"], "eflaw")
        self.assertEqual(params["LM"], "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률", "가운뎃점 이형 정규화")
        self.assertNotIn("efYd", params)
        _, g = self._root(ok, ef_yd="20261002")
        self.assertEqual(g.call_args.kwargs["params"]["efYd"], "20261002")
        self.assertIsNone(self._root("<Law>일치하는 법령이 없습니다</Law>")[0])
        self.assertIsNone(self._root(ok.replace("남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률", "다른 법"))[0])
        self.assertIsNone(self._root(ok.replace("일부개정", "타법폐지"))[0])
        with self.assertRaises(RuntimeError):
            self._root("<Response><result>사용자 정보 검증에 실패</result></Response>")

    def test_e12_collectors_use_shared_lookup(self):
        import fetch_official_rules as fo
        import build_graph
        self.assertIn("fetch_law_root(", inspect.getsource(fo.fetch_article_xml))
        self.assertIn("fetch_law_root(", inspect.getsource(build_graph._fetch_articles_from_api))


class CacheExpiryTest(unittest.TestCase):
    """E2·E3·E17 — 조문 캐시만 자정 만료."""

    def _ts(self, *args):
        return datetime(*args, tzinfo=KST).timestamp()

    def test_e2_article_expiry(self):
        from app.core.legal_api import _article_expiry
        self.assertEqual(_article_expiry(self._ts(2026, 10, 4, 23, 59)), self._ts(2026, 10, 5, 0, 0))
        self.assertEqual(_article_expiry(self._ts(2026, 10, 5, 1, 30)), self._ts(2026, 10, 5, 2, 30))
        self.assertEqual(_article_expiry(self._ts(2026, 10, 4, 12, 0)), self._ts(2026, 10, 5, 0, 0))
        # UTC 서버 시각으로 들어와도 경계는 KST다 (UTC 15:30 = KST 00:30 → +1h)
        utc = datetime(2026, 10, 4, 15, 30, tzinfo=timezone.utc).timestamp()
        self.assertEqual(_article_expiry(utc), utc + 3600)

    def test_e3_article_cache_v4_with_midnight_expiry(self):
        from app.core import legal_api
        xml = ("<법령><기본정보><법령명_한글>고용보험법</법령명_한글><제개정구분>일부개정</제개정구분>"
               "</기본정보><조문단위><조문번호>17</조문번호><조문여부>조문</조문여부>"
               "<조문내용>제17조(피보험자격의 확인)</조문내용></조문단위></법령>")
        legal_api._ARTICLE_CACHE.clear()
        legal_api._circuit.update({"fail_count": 0, "open_until": 0.0, "probing": False})
        legal_api._cache_set("v3:고용보험법_17", "target=law 시절 본문")   # 구 세대는 읽지 않는다
        with mock.patch.object(legal_api, "_l2_cache_get", return_value=None), \
             mock.patch.object(legal_api, "_l2_cache_set") as l2s, \
             mock.patch.object(legal_api._http, "get", return_value=_resp(xml)) as g:
            text = legal_api.fetch_article("고용보험법", 17, "k")
        self.assertIn("제17조", text)
        self.assertNotIn("target=law 시절", text)
        self.assertEqual(g.call_count, 1, "v3 키가 있어도 API로 다시 받는다")
        key = l2s.call_args.args[0]
        self.assertTrue(key.startswith("v4:"), key)
        expires = l2s.call_args.kwargs["expires_at"]
        self.assertLessEqual(abs(expires - legal_api._article_expiry()), 5)
        self.assertEqual(legal_api._ARTICLE_CACHE[key][0], expires)
        legal_api._ARTICLE_CACHE.clear()

    def test_e17_other_caches_keep_ttl(self):
        from app.core import legal_api
        noon = self._ts(2026, 10, 4, 23, 50)
        with mock.patch.object(legal_api.time, "time", return_value=noon):
            legal_api._cache_set("prec_1", "판례")
        self.assertEqual(legal_api._ARTICLE_CACHE.pop("prec_1")[0], noon + legal_api.LAW_CACHE_TTL)
        # 자정 상한은 조문 경로만 쓴다 — 판례·헌재·NLRC 함수는 _article_expiry를 부르지 않는다
        for fn in (legal_api.fetch_precedent, legal_api.fetch_detc, legal_api.fetch_nlrc_detail):
            self.assertNotIn("_article_expiry", inspect.getsource(fn))


class PrecedentRefGateTest(unittest.TestCase):
    """E5·E14·E15 — 답변 경로의 판례 번호 참조."""

    def test_e14_single_source(self):
        import fetch_court_precedents as fc
        from app.core import case_numbers
        self.assertIs(fc.normalize_case_no, case_numbers.normalize_case_no)
        self.assertIs(fc.detail_matches, case_numbers.detail_matches)

    def _run(self, refs, search_results, *, detc=False):
        from app.core import legal_api
        stats = {}
        fetch = mock.Mock(return_value="판시사항 본문")
        target_search = "search_detc" if detc else "search_precedent"
        target_fetch = "fetch_detc" if detc else "fetch_precedent"
        with mock.patch.object(legal_api, target_search, return_value=search_results), \
             mock.patch.object(legal_api, target_fetch, fetch):
            text = legal_api.fetch_relevant_articles(refs, "k", stats=stats)
        return text, fetch, stats

    def test_e5_exact_match_only(self):
        fuzzy = {"id": 1, "case_name": "동산인도", "case_no": "2019다2934"}
        exact = {"id": 2, "case_name": "임금", "case_no": "2022다291153"}
        text, fetch, stats = self._run(["대법원 2022다291153"], [fuzzy, exact])
        fetch.assert_called_once_with(2, "k")
        self.assertIn("[임금 2022다291153]", text, "헤더에 사건번호")
        self.assertEqual(stats["ok"], 1)
        text, fetch, stats = self._run(["대법원 2022다291153"], [fuzzy])
        self.assertIsNone(text)
        fetch.assert_not_called()
        self.assertEqual(stats["prec_rejected"], 1)

    def test_e5_merged_case_and_detc(self):
        merged = {"id": 3, "case_name": "손해배상", "case_no": "2000다51919, 51926"}
        text, fetch, _ = self._run(["대법원 2000다51926"], [merged])
        fetch.assert_called_once_with(3, "k")
        detc = {"id": 9, "case_name": "근로기준법 제35조 위헌소원", "case_no": "2015헌바327"}
        text, fetch, _ = self._run(["헌재 2015헌바327"], [dict(detc, case_no="2014헌바3"), detc], detc=True)
        fetch.assert_called_once_with(9, "k")
        self.assertIn("2015헌바327", text)

    def test_e15_stats_and_metadata_condition(self):
        from app.core import legal_api
        stats = {}
        with mock.patch.object(legal_api, "fetch_article", side_effect=["조문", None]):
            legal_api.fetch_relevant_articles(["근로기준법 제26조", "근로기준법 제999조"], "k", stats=stats)
        self.assertEqual((stats["requested"], stats["ok"], stats["miss"]), (2, 1, 1))
        from app.core import pipeline
        src = inspect.getsource(pipeline.process_question)
        self.assertIn('conv_metadata["law_api"] = dict(law_api_stats)', src)
        self.assertIn('any(law_api_stats.get(k) for k in ("miss", "error", "prec_rejected"))', src)


class FreshnessCheckTest(unittest.TestCase):
    """E6 — 본문 대조 fail-closed."""

    XML = ("<법령><기본정보><법령명_한글>근로기준법</법령명_한글><시행일자>{date}</시행일자></기본정보>"
           "{body}</법령>")
    ART = "<조문단위><조문번호>{no}</조문번호><조문여부>조문</조문여부><조문내용>{text}</조문내용></조문단위>"

    def _root(self, date, arts):
        import xml.etree.ElementTree as ET
        body = "".join(self.ART.format(no=n, text=t) for n, t in arts)
        return ET.fromstring(self.XML.format(date=date, body=body))

    def test_e6_diff_and_reference(self):
        import check_law_freshness as c
        a = c._article_texts(self._root("20261002", [("1", "a"), ("2", "b")]))
        b = c._article_texts(self._root("20261002", [("1", "a"), ("2", "B"), ("3", "c")]))
        self.assertEqual(c._diff_articles(a, b), ["2", "3"], "한쪽에만 있는 조문도 차이")
        self.assertEqual(c.reference_version([{"date": "20261008"}, {"date": "20261002"},
                                              {"date": "20250101"}], "20261004"), "20261002")
        self.assertIsNone(c.reference_version([{"date": "20270101"}], "20261004"))

    def _check(self, versions, prod, base):
        import check_law_freshness as c
        def fake_root(name, key, *, ef_yd=None, timeout=None):
            r = base if ef_yd else prod
            if isinstance(r, Exception):
                raise r
            return r
        with mock.patch.object(c, "law_versions", return_value=versions), \
             mock.patch.object(c, "fetch_law_root", side_effect=fake_root):
            return c.check_law("근로기준법", "k", "20261004")

    def test_e6_fail_closed(self):
        v = [{"date": "20261002", "kind": "타법개정"}, {"date": "20261008", "kind": "일부개정"}]
        same = self._root("20261002", [("1", "a")])
        self.assertTrue(self._check(v, same, same)["ok"])
        r = self._check(v, self._root("20261002", [("1", "a"), ("2", "미래")]), same)
        self.assertFalse(r["ok"]); self.assertEqual(r["diff"], ["2"])
        self.assertFalse(self._check(v, same, None)["ok"], "빈 루트(판본일 아님)는 실패")
        self.assertFalse(self._check(v, RuntimeError("down"), same)["ok"], "예외는 실패")
        self.assertFalse(self._check([], same, same)["ok"], "판본 목록 미일치는 실패")
        self.assertEqual(self._check(v, same, same)["upcoming"], [("20261008", "일부개정")])


class GraphPrecedentTest(unittest.TestCase):
    """E7·E8·E9·E16 — 그래프 판례는 법제처 원문 기록에서만."""

    def setUp(self):
        import build_graph
        self.bg = build_graph
        self.records = build_graph.load_precedent_records()

    def test_e7_gates_pass_on_committed_records(self):
        nodes = self.bg.precedent_nodes()
        self.assertEqual(set(nodes), set(self.bg.GRAPH_PRECEDENT_SPECS))
        for no, node in nodes.items():
            items = self.bg.holding_items(self.records[no]["issue"])
            self.assertIn(node["summary"], items, f"{no}: 요약은 판시사항 항목 그대로(G2)")
        self.assertEqual(nodes["2012다89399"]["superseded_by"], ["2023다302838"])

    def test_e7_gates_reject(self):
        bg, recs = self.bg, json.loads(json.dumps(self.records))
        spec = {"2013다25194": {"concepts": ["근로계약"]}}
        with self.assertRaises(bg.PrecedentGateError):           # G1
            bg.precedent_nodes(spec, {})
        with self.assertRaises(bg.PrecedentGateError):           # G3
            bg.precedent_nodes({"2013다25194": {"concepts": ["주휴수당"]}}, recs)
        with self.assertRaises(bg.PrecedentGateError):           # G4
            bg.precedent_nodes({"2012다89399": {"concepts": ["통상임금"], "supersedes": ["2013다25194"]}}, recs)
        bad = dict(recs); bad["2013다25194"] = dict(recs["2013다25194"], source_url="http://example.com/x")
        with self.assertRaises(bg.PrecedentGateError):           # G5
            bg.precedent_nodes(spec, bad)

    def test_e7_supersede_marker_is_bound_to_the_case(self):
        """참조판례에 여러 건이 있어도 '(변경)'은 그 번호의 항목 안에서만 인정한다."""
        refs = "대법원 2010. 1. 1. 선고 2009다1 판결, 대법원 2013. 12. 18. 선고 2012다89399 전원합의체 판결(공2014상, 236)(변경)"
        self.assertTrue(self.bg._supersede_evidence(refs, "2012다89399"))
        self.assertFalse(self.bg._supersede_evidence(refs, "2009다1"))

    def test_e8_removed_and_corrected(self):
        graph = json.loads((ROOT / "data/graph_data.json").read_text(encoding="utf-8"))
        nums = {n.get("case_number") for n in graph["nodes"] if n.get("type") == "precedent"}
        for gone in ("2019다293449", "2010다111757", "2017다261387", "2020나2016258"):
            self.assertNotIn(gone, nums)
            self.assertNotIn(gone, self.bg.GRAPH_PRECEDENT_SPECS)
        self.assertEqual(self.records["2023다302838"]["date"], "2024.12.19")

    def test_e9_rendering(self):
        from app.core.graph import format_precedent_line
        node = self.bg.precedent_nodes()["2012다89399"]
        line = format_precedent_line(node)
        self.assertIn("2013.12.18 선고", line)
        self.assertIn("전원합의체 판결", line)
        self.assertIn("일부 법리는 대법원 2023다302838 판결로 변경됨", line)
        long = format_precedent_line(dict(node, summary="가" * 500, superseded_by=[]))
        self.assertLessEqual(long.count("가"), 200)

    def test_e16_committed_graph_matches_rebuild(self):
        graph = json.loads((ROOT / "data/graph_data.json").read_text(encoding="utf-8"))
        committed = {n["case_number"]: {k: v for k, v in n.items() if k not in ("id", "type")}
                     for n in graph["nodes"] if n.get("type") == "precedent"}
        rebuilt = {k: {a: b for a, b in v.items() if a != "concepts"}
                   for k, v in self.bg.precedent_nodes().items()}
        self.assertEqual(committed, rebuilt, "graph_data.json 재빌드 누락(python3 build_graph.py --skip-api)")


class WhitelistTest(unittest.TestCase):
    """E10·E13 — 인용 화이트리스트."""

    def test_e10_rendered_precedents_only(self):
        from app.core.citation_relevance import classify_paths
        from app.core.graph import rendered_precedents
        results = [{"data": {"type": "precedent", "case_number": "2023다302838", "court": "대법원",
                             "summary": "통상임금"}},
                   {"data": {"type": "precedent", "case_number": "2012다89399", "court": "대법원",
                             "summary": "통상임금"}}]
        shown = rendered_precedents("- 대법원 2023다302838 (…): 통상임금", results)
        self.assertEqual([d["case_number"] for d in shown], ["2023다302838"], "절단돼 안 보인 판례는 제외")
        hits = [{"title": "대법원 2023다302838", "case_no": "2023다302838", "chunk_text": "통상임금"}]
        self.assertEqual(classify_paths(["2023다302838"], hits)["2023다302838"]["path"], "primary")

    def test_e13_rule_block_and_calculator_citations_are_whitelisted(self):
        from app.core.citation_validator import extract_precedents_from_hits, validate_response_citations
        from app.core.pipeline import _citation_source_hits
        from app.core.rule_facts import build_rule_facts, prec_anchor_hits
        blocks = build_rule_facts("주 3일 6시간 알바 주휴수당", None)
        names = [n for n, _ in blocks]
        self.assertIn("weekly_holiday", names)
        answer = "주휴시간은 1주 소정근로시간을 5로 나눕니다(대법원 2022다291153 판결)."
        bare = _citation_source_hits(None, [], None, None, None)
        self.assertIn("2022다291153", validate_response_citations(answer, extract_precedents_from_hits(bare))["hallucinated"])
        hits = _citation_source_hits(None, [], None, None, None,
                                     extra_hits=prec_anchor_hits(names),
                                     system_texts=[("현행 규칙 블록", b) for _, b in blocks])
        check = validate_response_citations(answer, extract_precedents_from_hits(hits))
        self.assertEqual(check["hallucinated"], [])
        calc = "── 법적 근거 ──\n  • 대법원 2025.8.14. 선고 2022다291153 판결"
        hits = _citation_source_hits(None, [], None, None, None, system_texts=[("임금계산기 결과", calc)])
        self.assertEqual(validate_response_citations(answer, extract_precedents_from_hits(hits))["hallucinated"], [])
        self.assertEqual(len(_citation_source_hits(None, [{"title": "t", "chunk_text": "c"}],
                                                   "법조문", None, "그래프")), 3, "기존 5-위치인자 호출 불변")


class RuleBlockTest(unittest.TestCase):
    """E11 — P1 규칙 블록."""

    def names(self, q, a=None):
        from app.core.rule_facts import build_rule_facts
        return [n for n, _ in build_rule_facts(q, a)]

    def test_e11_detection_and_order(self):
        from app.core.rule_facts import MAX_BLOCKS, RULE_FACTS
        self.assertEqual(MAX_BLOCKS, 3)
        self.assertEqual([f.name for f in RULE_FACTS],
                         ["unemployment", "insured_status", "harassment_retaliation",
                          "dismissal_notice", "weekly_holiday", "probation_wage"])
        self.assertEqual(self.names("알바인데 3.3% 떼고 고용보험 미가입이면 실업급여 못 받나요"),
                         ["unemployment", "insured_status"])
        self.assertIn("dismissal_notice", self.names("3주 정도 근무했는데 해고됐어요"))
        self.assertIn("dismissal_notice", self.names("수습 중 해고"))
        self.assertNotIn("dismissal_notice", self.names("7월 27일에 해고 통보를 받았습니다. 부당해고 구제신청 절차는?"))
        self.assertIn("dismissal_notice", self.names("부당해고 구제신청", NS(consultation_topic="해고·징계",
                                                                   calculation_types=[])))

    def test_e11_insured_status_text(self):
        from app.core.rule_facts import build_rule_facts
        text = dict(build_rule_facts("고용보험 미가입 확인청구", None))["insured_status"]
        self.assertIn("언제든지", text)
        self.assertIn("근로복지공단", text)
        self.assertIn("고용센터", text)

    def test_e11_prec_anchors_resolve_in_committed_records(self):
        from app.core.rule_facts import RULE_FACTS, precedent_records
        recs = precedent_records()
        norm = lambda t: re.sub(r"\s+", "", t)  # noqa: E731
        n = 0
        for fact in RULE_FACTS:
            for case_no, phrase in fact.prec_anchors:
                rec = recs.get(case_no)
                self.assertIsNotNone(rec, f"{fact.name}: 원문 기록 없음 {case_no}")
                self.assertIn(norm(phrase), norm(rec["issue"] + rec["summary"]), f"{fact.name}: {phrase}")
                n += 1
        self.assertGreaterEqual(n, 1)

    def test_e11_answer_rule_mentions_deadline_check(self):
        from app.templates.prompts import ANSWER_ACCURACY_RULES
        self.assertIn("유효기간과 처리기한", ANSWER_ACCURACY_RULES)


class HandWrittenLegalFactsTest(unittest.TestCase):
    """E18·E19 — 코드에 손으로 쓴 법률 사실(판정기 문구·별표 부재 주장)."""

    def test_e18_harassment_assessor_cites_current_articles(self):
        """판정 결과는 답변 컨텍스트에 그대로 들어간다 — 손으로 쓴 '제109조 제2항'이 지식iN
        재평가 9번(1·2·3차 모두) 오인용의 출처였다. 불리한 처우 벌칙은 제109조 제1항이다."""
        from harassment_assessor import constants
        from harassment_assessor.assessor import assess_harassment
        from harassment_assessor.models import HarassmentInput
        texts = [ln for ln in (ROOT / "harassment_assessor/constants.py").read_text(encoding="utf-8").splitlines()
                 + (ROOT / "harassment_assessor/assessor.py").read_text(encoding="utf-8").splitlines()
                 if not ln.lstrip().startswith("#")]
        self.assertFalse([ln for ln in texts if "제109조 제2항" in ln and '"' in ln], "벌칙 근거는 제1항")
        self.assertTrue(any("제109조 제1항" in r for r in constants.LEGAL_REFERENCES))

        base = dict(perpetrator_role="팀장", victim_role="팀원", behavior_types=["폭언_모욕"],
                    frequency="주 1회 이상", duration="3개월 이상", company_response="불리한 처우")
        big = assess_harassment(HarassmentInput(business_size="5인이상", **base))
        self.assertTrue(any("제109조 제1항" in w for w in big.warnings))
        small = assess_harassment(HarassmentInput(business_size="5인미만", **base))
        joined = " ".join(small.warnings)
        self.assertIn("적용되지 않습니다", joined, "4명 이하 사업장에는 제76조의2·3 미적용(시행령 별표 1)")
        self.assertNotIn("제109조", joined)
        self.assertNotIn("규모와 관계없이", joined)
        # 결과 **전체**(법적 근거·대응 절차 포함)에 모순이 없어야 한다 — 경고만 고치고
        # legal_basis·response_steps를 그대로 두면 "적용되지 않습니다"와 벌칙·과태료가 공존한다.
        from harassment_assessor.result import format_assessment
        whole = format_assessment(small)
        # '과태료' 단어 자체는 "적용되지 않습니다" 문장에 정당하게 나온다 — 금액·조문 번호로 본다
        for wrong in ("제109조", "제116조", "500만원", "3천만원", "노동청 진정", "제76조의3 제2항"):
            self.assertNotIn(wrong, whole, f"4명 이하 판정 결과에 '{wrong}'")
        self.assertIn("별표 1", whole)
        # 도구 인자는 자유 문자열 — 띄어쓰기 변형도 같은 분기
        spaced = assess_harassment(HarassmentInput(business_size="5인 미만", **base))
        self.assertEqual(spaced.legal_basis, small.legal_basis)

    def test_e19_annex_absence_check(self):
        import xml.etree.ElementTree as ET
        import check_law_freshness as c
        from app.core.rule_facts import ANNEX_ABSENCE_CLAIMS, RULE_FACTS
        xml = ("<법령><별표><별표단위><별표제목>상시 4명 이하의 근로자를 사용하는 사업 또는 사업장에 "
               "적용하는 법 규정</별표제목><별표내용>제6장 안전과 보건 제76조</별표내용></별표단위></별표></법령>")
        self.assertTrue(c._annex_absence(ET.fromstring(xml), "4명 이하", "제6장의2"))
        self.assertFalse(c._annex_absence(ET.fromstring(xml.replace("제76조", "제6장의2 직장 내 괴롭힘")),
                                          "4명 이하", "제6장의2"))
        self.assertIsNone(c._annex_absence(ET.fromstring("<법령/>"), "4명 이하", "제6장의2"))
        names = {f.name for f in RULE_FACTS}
        for block, *_ in ANNEX_ABSENCE_CLAIMS:
            self.assertIn(block, names)


class GapFollowupTest(unittest.TestCase):
    """E20 — gap 분석 후속(위험 3·7·10)."""

    def test_e20_insured_status_withholding_pattern(self):
        from app.core.rule_facts import build_rule_facts
        names = lambda q: [n for n, _ in build_rule_facts(q, None)]  # noqa: E731
        self.assertIn("insured_status", names("알바비에서 3.3% 떼고 받아요"))
        self.assertIn("insured_status", names("3.3프로 공제"))
        self.assertNotIn("insured_status", names("주 23.3시간 근무, 13.3% 인상"))

    def test_e20_consultation_path_stats_merged(self):
        import inspect as _inspect
        from app.core import legal_consultation, pipeline
        self.assertIn("stats=law_api_stats", _inspect.getsource(legal_consultation.process_consultation))
        src = _inspect.getsource(pipeline.process_question)
        self.assertIn("law_api_stats=consultation_law_stats", src)
        self.assertIn("law_api_stats[_k] = law_api_stats.get(_k, 0) + _v", src)

    def test_e20_article_key_zero_branch(self):
        import xml.etree.ElementTree as ET
        import check_law_freshness as c
        jo = ET.fromstring("<조문단위><조문번호>5</조문번호><조문가지번호>0</조문가지번호></조문단위>")
        self.assertEqual(c._article_key(jo), "5")
        jo2 = ET.fromstring("<조문단위><조문번호>76</조문번호><조문가지번호>2</조문가지번호></조문단위>")
        self.assertEqual(c._article_key(jo2), "76의2")


if __name__ == "__main__":
    unittest.main(verbosity=1)
