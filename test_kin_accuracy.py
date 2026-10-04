"""지식iN 실질문 정확도 회귀 테스트 (kin-answer-accuracy, API 키·네트워크 불요).

출발점: 외부 검증 리포트(2026-10-02, 지식iN 20문항 평균 78.4/100). 오답의 원인은 셋이었다 —
① 코퍼스의 폐기 기준(일용직 '10일 미만', 주휴 '다음 주 근무 예정', 삭제된 근기법 제35조)
② 규칙 공백(조기재취업수당 14일 기준을 7일 대기기간과 혼동) ③ 인용 검증이 존재만 봄.

K1~K12는 Design §7. K6(원문 대조)은 `output_공식법령/`(gitignore)이 없으면 skip — 로컬 관문이다.
"""
from __future__ import annotations

import inspect
import json
import os
import re
import unittest
import unittest.mock
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parent


class KinFixtureTest(unittest.TestCase):
    """K1 — fixture 스키마."""

    def test_k1_fixture_schema(self):
        import eval_consultation as ev
        cases = ev.load_cases(ev.KIN_FIXTURE_PATH)
        self.assertEqual(len(cases), 20)
        self.assertEqual(ev.validate_cases(cases), [])
        self.assertEqual([c.id for c in cases], [f"kin-{i:02d}" for i in range(1, 21)])
        for c in cases:
            self.assertTrue(c.source_ref.startswith("https://kin.naver.com/"), c.id)
            self.assertIsInstance(c.report_score, int, c.id)

    def test_k1_fixture_holds_no_original_question_text(self):
        """저장소가 공개라 지식iN 원문(제3자 글)을 싣지 않는다 — 요약만(Design D5)."""
        raw = (ROOT / "data/eval_kin_queries.json").read_text(encoding="utf-8")
        for marker in ("질문자 추가설명", "용산", "개뼉다구", "지식인에 질문"):
            self.assertNotIn(marker, raw)


class ClaimMatcherTest(unittest.TestCase):
    """K2·K3 — 금지 문구 매처."""

    def test_k2_negated_mention_is_not_a_violation(self):
        from eval_consultation import claim_found
        pat = r"re:10\s*일\s*미만"
        self.assertFalse(claim_found(pat, "'이전 1개월 10일 미만'은 폐지된 구 기준입니다."))
        self.assertTrue(claim_found(pat, "신청일 이전 1개월간 근로일수가 10일 미만이어야 합니다."))
        self.assertFalse(claim_found("다음 주 근무 예정", "다음 주 근무 예정은 요건이 아닙니다."))
        # 표 셀의 명사형 종결 — 실측 kin-01(2차)이 정답인데 검출됐다
        self.assertFalse(claim_found(r"re:다음\s*주.{0,25}(근로|근무).{0,15}(예정).{0,20}(요건)",
                                     "| 다음 주 근무 예정은 요건이 아님 |"))

    def test_k2_negation_in_another_sentence_does_not_cancel(self):
        """다른 문장의 부정어가 단정을 지우면 안 된다(CodeRabbit PR #96)."""
        from eval_consultation import claim_found
        pat = r"re:10\s*일\s*미만"
        self.assertTrue(claim_found(pat, "근로일수가 10일 미만이어야 합니다. 과거 기준은 폐지되었습니다."))
        self.assertTrue(claim_found(pat, "“근로일수가 10일 미만이어야 합니다.” 과거 기준은 폐지되었습니다."))
        self.assertTrue(claim_found(pat, "폐지된 제도도 있습니다.\n일용직은 10일 미만이어야 합니다."))
        self.assertTrue(claim_found(pat, "| 요건 | 10일 미만 | 아닙니다 |"))
        # 같은 문장 안의 부정은 멀리 있어도 존중한다(실측 kin-01 2차 — 과거 해석 인용)
        self.assertFalse(claim_found(
            r"re:다음\s*주.{0,25}(근로|근무).{0,15}(예정).{0,20}(있어야)",
            '과거 행정해석(근로기준정책과-6551, 2015.12.7.)은 대법원 2011다39946 판결을 근거로 '
            '"다음 주 근무가 예정되어 있어야 주휴가 발생한다"고 보았습니다.'))
        # 종전 해석을 소개하며 변경됐다고 쓰는 정답(실측 kin-19 3차)
        self.assertFalse(claim_found(
            r"re:다음\s*주.{0,25}(근로|근무).{0,15}(예정).{0,20}(요건)",
            "다음 주 근무 예정을 요건으로 보던 종전 해석(근로기준정책과-6551, 2015. 12. 7.)은 변경되었습니다."))
        # 같은 문장 안의 부정은 계속 존중한다
        self.assertFalse(claim_found(pat, "'10일 미만'은 2019. 10. 1. 폐지된 구 기준입니다."))

    def test_k2_identifier_claims_ignore_negation(self):
        """판례 인용 문장에는 "아니라"가 흔하다 — 예외를 적용하면 오인용이 통과한다(실측 kin-01)."""
        from eval_consultation import claim_found
        text = "실제 일한 시간이 아니라 계약상 소정근로시간입니다(대법원 2019다293449 참고)."
        self.assertTrue(claim_found("2019다293449", text))

    def test_k2_strict_regex_prefix(self):
        from eval_consultation import claim_found
        text = "3개월 미만이면 해고예고 규정이 적용되지 않습니다(근로기준법 제26조·제35조)."
        self.assertFalse(claim_found(r"re:근로기준법[^.\n]{0,20}?제\s*35\s*조", text))
        self.assertTrue(claim_found(r"re!:근로기준법[^.\n]{0,20}?제\s*35\s*조", text))

    def test_k3_existing_fixture_claims_unchanged(self):
        """기존 60건의 금지 문구는 전부 단정형 리터럴이라, 매처 변경 전후 판정이 같아야 한다."""
        import eval_consultation as ev
        cases = ev.load_cases(ev.FIXTURE_PATH)
        claims = [cl for c in cases for cl in c.forbidden_claims]
        self.assertTrue(claims)
        for cl in claims:
            self.assertFalse(cl.startswith(("re:", "re!:")), cl)
            # 단정형 문장 안에서는 기존(부분문자열) 판정과 같다
            self.assertTrue(ev.claim_found(cl, f"답변: {cl}."), cl)
            self.assertFalse(ev.claim_found(cl, "무관한 답변입니다."), cl)

    def test_k3_invalid_regex_is_a_schema_error(self):
        import eval_consultation as ev
        case = ev.load_cases(ev.KIN_FIXTURE_PATH)[0]
        from dataclasses import replace
        bad = replace(case, forbidden_claims=["re:(unclosed"])
        self.assertIn("invalid forbidden_claims regex: kin-01", ev.validate_cases([bad]))


class RuleFactsTest(unittest.TestCase):
    """K4~K6 — 현행 규칙 블록."""

    def _a(self, **kw):
        return NS(calculation_types=kw.get("types", []), consultation_topic=kw.get("topic"))

    def test_k4_detection(self):
        from app.core.rule_facts import build_rule_facts
        names = lambda q, a=None: [n for n, _ in build_rule_facts(q, a)]  # noqa: E731
        self.assertEqual(names("조기재취업수당 받을 수 있나요?"), ["unemployment"])
        self.assertEqual(names("야근수당 계산", self._a(types=["overtime"])), [])
        self.assertEqual(names("월 경계 주휴수당"), ["weekly_holiday"])
        self.assertEqual(names("3주 근무 후 해고예고 없이 해고됐어요"), ["dismissal_notice"])
        self.assertEqual(names("수습 최저임금 80% 받았어요"), ["probation_wage"])
        self.assertEqual(names("상담", self._a(topic="고용보험")), ["unemployment"])
        self.assertEqual(names("직장 내 괴롭힘 신고 후 불이익"), ["harassment_retaliation"])

    def test_k4_harassment_block_does_not_claim_current_deletion(self):
        """제109조②는 2026-10-08 시행 전까지 존속한다 — 기준일 무관하게 참인 문장만 쓴다."""
        from app.core.rule_facts import build_rule_facts
        text = dict(build_rule_facts("직장 내 괴롭힘 신고 후 해고", None))["harassment_retaliation"]
        self.assertIn("제109조 제1항", text)
        self.assertIn("2026. 10. 8. 시행 시 삭제", text)   # 시제 중립 — 10-08 전후 모두 참
        self.assertNotIn("삭제된 조항", text)

    def test_k4_at_most_max_blocks(self):
        from app.core.rule_facts import MAX_BLOCKS, build_rule_facts
        q = "수습 최저임금 80%에 주휴도 없었고 해고예고 없이 잘려서 실업급여 받을 수 있나요"
        self.assertEqual(len(build_rule_facts(q, None)), MAX_BLOCKS)

    def test_k4_unemployment_block_separates_14_and_7_days(self):
        """12번(54점)의 핵심 오류 — 조기재취업 14일을 대기기간 7일로 적용."""
        from app.core.rule_facts import build_rule_facts
        text = dict(build_rule_facts("조기재취업", None))["unemployment"]
        self.assertIn("14일이 지난 후", text)
        self.assertIn("7일간", text)
        self.assertIn("채용을 약속한 사업주", text)
        self.assertIn("3분의 1 미만", text)

    def test_k5_rule_facts_run_in_managed_mode(self):
        """D1 — 관리 모드에서도 실행돼야 한다(_KNOWLEDGE_MODULES의 rules_enabled 게이트와 분리).

        effective-law D10으로 블록 계산이 화이트리스트 구성 앞으로 옮겨졌다 — 위치가 아니라
        "계산·부착 어디에도 rules_enabled 게이트가 없다"를 고정한다.
        """
        from app.core import pipeline as pl
        src = inspect.getsource(pl.process_question)
        start = src.index("rule_fact_blocks: list[tuple[str, str]] = []")
        call = src.index("build_rule_facts(query, analysis)")
        self.assertLess(start, call)
        self.assertNotIn("rules_enabled", src[start:call])
        attach = src.index("for _rf_name, _rf_block in rule_fact_blocks:")
        line_start = src.rfind("\n", 0, attach)
        self.assertNotIn("rules_enabled", src[line_start:attach])
        # 화이트리스트보다 먼저 계산(D10)
        self.assertLess(call, src.index("whitelist_hits = _citation_source_hits("))

    def test_k6_anchors_exist_in_official_text(self):
        from app.core.rule_facts import RULE_FACTS
        base = ROOT / "output_공식법령"
        if not base.is_dir():
            self.skipTest("output_공식법령/ 없음 — fetch_official_rules.py --doc 로 수집 후 로컬에서 확인")
        norm = lambda t: re.sub(r"\s+", "", t)  # noqa: E731
        for fact in RULE_FACTS:
            self.assertTrue(fact.anchors, fact.name)
            for doc_id, phrase in fact.anchors:
                path = base / f"{doc_id}.md"
                if not path.exists():
                    self.fail(f"{doc_id}.md 없음 — fetch_official_rules.py --doc {doc_id}")
                body = path.read_text(encoding="utf-8").split("## 본문", 1)[-1]
                self.assertIn(norm(phrase), norm(body), f"{fact.name}: {phrase}")

    def test_k6_anchor_docs_are_registered_for_collection(self):
        import fetch_official_rules as fo
        from app.core.rule_facts import RULE_FACTS
        ids = {a[0] for a in fo.ARTICLES}
        for fact in RULE_FACTS:
            for doc_id, _ in fact.anchors:
                self.assertIn(doc_id, ids, doc_id)


class StaleFilterTest(unittest.TestCase):
    """K7~K9 — 폐기 기준 필터."""

    QA_STALE = {"source_type": "qa", "title": "q", "score": 1.0,
                "content": "주휴수당은 다음 주 근로가 예정되어 있지 않다면 지급하지 않아도 됩니다."}
    QA_UPDATED = {"source_type": "qa", "title": "u", "score": 1.0,
                  "content": "과거에는 주휴수당에 다음 주 근로가 예정되어 있어야 한다고 보았으나 "
                             "최근 행정해석(임금근로시간과-1736)에 따르면 그렇지 않습니다."}
    PREC_35 = {"source_type": "precedent", "title": "p", "score": 1.0,
               "content": "근로기준법 제35조 제3호가 근로의 권리를 침해하여"}
    PLAIN = {"source_type": "interpretation", "title": "i", "score": 1.0, "content": "연장근로 가산"}

    def test_k7_counsel_dropped_others_annotated(self):
        from app.core.stale_rules import filter_stale_hits
        hits = [self.QA_STALE, self.PREC_35, self.PLAIN]
        kept, ids = filter_stale_hits(hits)
        self.assertEqual([h["title"] for h in kept], ["p", "i"])
        self.assertTrue(kept[0]["content"].startswith("[구 기준 주의"))
        self.assertEqual(set(ids), {"weekly_next_week", "lsa_35"})
        self.assertNotIn("구 기준", self.PREC_35["content"], "원본 hit을 제자리 수정하면 안 된다")

    def test_k7_counsel_mentioning_current_rule_is_kept(self):
        """변경을 올바르게 설명한 상담글은 구 문구를 인용해도 지우지 않는다(실측 ctx_qa_2253369_c1)."""
        from app.core.stale_rules import filter_stale_hits
        kept, _ = filter_stale_hits([self.QA_UPDATED, self.PLAIN])
        self.assertEqual(len(kept), 2)
        self.assertTrue(kept[0]["content"].startswith("[구 기준 주의"))

    def test_k7_never_drops_everything(self):
        from app.core.stale_rules import filter_stale_hits
        kept, ids = filter_stale_hits([self.QA_STALE])
        self.assertEqual(len(kept), 1)
        self.assertTrue(kept[0]["content"].startswith("[구 기준 주의"))
        self.assertEqual(ids, ["weekly_next_week"])

    def test_k7_kill_switch(self):
        from app.core.stale_rules import filter_stale_hits
        with unittest.mock.patch.dict(os.environ, {"STALE_FILTER": "off"}):
            kept, ids = filter_stale_hits([self.QA_STALE, self.PLAIN])
        self.assertEqual(len(kept), 2)
        self.assertEqual(ids, [])

    def test_k7_change_dates_are_pinned(self):
        """주석의 '이후 변경' 날짜는 시행일이다 — 공포일과 다르면 안내가 틀린다(원문 개정 이력으로 확인)."""
        from app.core.stale_rules import STALE_RULES
        self.assertEqual({r.id: r.changed for r in STALE_RULES}, {
            "daily_10days": "2019-10-01",      # 고용보험법 2019.8.27 개정, 2019.10.1 시행
            "weekly_next_week": "2021-08-04",  # 임금근로시간과-1736
            "lsa_35": "2019-01-15",            # 근로기준법 2019.1.15 개정(제26조 단서로 이관)
        })

    def test_k8_negative_patterns(self):
        from app.core.stale_rules import match_rules
        for text in (
            "교대제 근무표상 다음 주 근무 예정표가 아직 나오지 않았습니다.",
            "계속 근로한 기간이 3개월 미만이면 해고예고 예외입니다(근로기준법 제26조 단서 제1호).",
            "주휴일에 근로를 시켰다면 다음주 소정근로일 중 1일을 쉬게 하여 보상해야 합니다.",
            "연차휴가를 10일 미만으로 사용한 경우",
            "고용보험법 제35조에 따른 피보험자격",
        ):
            self.assertEqual(match_rules(text), [], text)

    def test_k8_positive_patterns(self):
        from app.core.stale_rules import match_rules
        for text, rid in (
            ("일용근로자는 신청일 이전 1개월 동안 근로일수가 10일 미만이어야", "daily_10days"),
            ("주휴수당은 1주 개근하고 다음주에 출근하여야 합니다", "weekly_next_week"),
            ("해고예고 적용 제외(근로기준법 제26조·제35조)", "lsa_35"),
        ):
            self.assertIn(rid, [r.id for r in match_rules(text)], text)

    def test_k7_exclude_set_matches_counsel_sources(self):
        """제외 대상 정의가 둘로 갈리면 안 된다 — rag를 import하면 순환이라 사본을 둔다."""
        from app.core.rag import COUNSEL_SOURCES
        from app.core.stale_rules import _EXCLUDE_SOURCES
        self.assertEqual(_EXCLUDE_SOURCES, COUNSEL_SOURCES)

    def test_k9_filter_runs_before_caps(self):
        from app.core import rag
        src = inspect.getsource(rag.format_pinecone_hits)
        self.assertLess(src.index("filter_stale_hits(hits)"),
                        src.index("_cap_counsel_total(_cap_textbook_total(_cap_by_book(hits))"))

    def test_k9_format_reports_stale_ids(self):
        from app.core.rag import format_pinecone_hits
        out: list[str] = []
        text, meta = format_pinecone_hits([dict(self.QA_STALE, section=""), dict(self.PLAIN, section="")],
                                          stale_out=out)
        self.assertEqual(out, ["weekly_next_week"])
        self.assertEqual([m["title"] for m in meta], ["i"])
        self.assertNotIn("예정되어 있지 않다면", text)


class CitationRelevanceTest(unittest.TestCase):
    """K10·K12 — 인용 관련성."""

    HITS = [
        {"title": "고용보험 가입 시기", "case_no": "2018두63235", "chunk_text": "공무원의 고용보험 가입 신청기간"},
        {"title": "상담 Q&A", "case_no": "", "chunk_text": "대법원 2019다293449 판결에 따르면 주휴"},
    ]

    def test_k10_path_classification(self):
        from app.core.citation_relevance import classify_paths
        paths = classify_paths(["2018두63235", "2019다293449", "2000다1"], self.HITS)
        self.assertEqual(paths["2018두63235"]["path"], "primary")
        self.assertEqual(paths["2019다293449"]["path"], "secondhand")
        self.assertNotIn("2000다1", paths)

    def _config(self, vectors):
        data = [NS(index=i, embedding=v) for i, v in enumerate(vectors)]
        client = unittest.mock.MagicMock()
        client.with_options.return_value.embeddings.create.return_value = NS(data=data)
        return NS(openai_client=client, embed_model="m")

    def test_k10_verdicts(self):
        from app.core.citation_relevance import assess
        with unittest.mock.patch.dict(os.environ, {"CITATION_RELEVANCE_MODE": "monitor",
                                                   "CITATION_RELEVANCE_MIN": "0.5"}):
            v = assess("실업급여 조건", ["2018두63235", "2019다293449"], self.HITS,
                       self._config([[1, 0], [0, 1]]))
        self.assertEqual(v["2018두63235"], {"verdict": "low_relevance", "sim": 0.0})
        self.assertEqual(v["2019다293449"]["verdict"], "secondhand")

    def test_k10_stale_note_not_embedded(self):
        from app.core.citation_relevance import classify_paths
        hit = {"title": "x", "case_no": "2000다1",
               "chunk_text": "[구 기준 주의 — 2019-01-15 이후 변경: 제26조]\n판결 본문"}
        self.assertEqual(classify_paths(["2000다1"], [hit])["2000다1"]["text"], "판결 본문")

    def test_k4_one_failing_block_does_not_drop_others(self):
        from app.core import rule_facts as rf
        bad = rf.RuleFact(name="bad", detect=lambda q, a: 1 / 0, lines=("x",), sources="", as_of="")
        with unittest.mock.patch.object(rf, "RULE_FACTS", (bad,) + rf.RULE_FACTS):
            self.assertEqual([n for n, _ in rf.build_rule_facts("주휴", None)], ["weekly_holiday"])

    def test_k10_fail_open_and_off(self):
        from app.core.citation_relevance import assess
        broken = NS(openai_client=None, embed_model="m")
        self.assertEqual(assess("q", ["2018두63235"], self.HITS, broken), {})
        with unittest.mock.patch.dict(os.environ, {"CITATION_RELEVANCE_MODE": "off"}):
            self.assertEqual(assess("q", ["2018두63235"], self.HITS, self._config([[1], [1]])), {})

    def test_k10_monitor_never_enforces(self):
        from app.core.citation_relevance import enforcement_targets
        v = {"2018두63235": {"verdict": "low_relevance", "sim": 0.1}}
        with unittest.mock.patch.dict(os.environ, {"CITATION_RELEVANCE_MODE": "monitor"}):
            self.assertEqual(enforcement_targets(v), {})
        with unittest.mock.patch.dict(os.environ, {"CITATION_RELEVANCE_MODE": "enforce"}):
            self.assertEqual(enforcement_targets(v), {"low_relevance": ["2018두63235"]})

    def test_k10_whitelist_forwards_case_no(self):
        """메타 사건번호가 화이트리스트로 넘어가야 한다 — 빠지면 T31 메타 경로가 죽는다(2026-10-03 발견)."""
        from app.core.citation_validator import extract_precedents_from_hits
        from app.core.pipeline import _citation_source_hits
        hits = _citation_source_hits(None, [{"title": "판례", "chunk_text": "본문에 번호 없음",
                                             "case_no": "2000다15869", "source_type": "precedent"}],
                                     None, None, None)
        self.assertEqual(hits[0]["case_no"], "2000다15869")
        self.assertIn("2000다15869", extract_precedents_from_hits(hits))

    def test_k12_correction_reason_text(self):
        from app.core import citation_validator as cv
        src = inspect.getsource(cv.correct_hallucinated_citations)
        self.assertIn('reason: str = "hallucinated"', src)
        self.assertIn("확인되지 않은 판례 번호", cv._CORRECTION_TEXT["hallucinated"][1])
        self.assertEqual(set(cv._CORRECTION_TEXT), {"hallucinated", "low_relevance", "secondhand"})


class LawArticleFormatTest(unittest.TestCase):
    """K13 — 법제처 조문 포맷이 목(目)을 담는다(고용보험법 제40조①5호 가·나목)."""

    XML = """<조문단위><조문번호>40</조문번호><조문제목>구직급여의 수급 요건</조문제목>
      <항><항내용>①구직급여는 다음 각 호의 요건을 모두 갖춘 경우에 지급한다.</항내용>
        <호><호내용>5. 다음 각 목의 어느 하나에 해당할 것</호내용>
          <목><목내용>가. 근로일 수의 합이 총 일수의 3분의 1 미만일 것</목내용></목>
          <목><목내용>나. 건설일용근로자로서 14일간 연속하여 근로내역이 없을 것</목내용></목>
        </호></항></조문단위>"""

    def test_k13_full_article_includes_mok(self):
        import xml.etree.ElementTree as ET
        from app.core.legal_api import _format_full_article
        text = _format_full_article(ET.fromstring(self.XML))
        self.assertIn("3분의 1 미만", text)
        self.assertIn("14일간 연속", text)

    def test_k13_paragraph_includes_mok(self):
        import xml.etree.ElementTree as ET
        from app.core.legal_api import _format_article_text
        hang = ET.fromstring(self.XML).find("항")
        self.assertIn("3분의 1 미만", _format_article_text("제40조", hang))

    def test_k13_cache_generation_bumped(self):
        # 목 포함(v3) 이후 eflaw 전환(v4)으로 한 번 더 올라갔다 — 어느 쪽이든 v2 캐시를 읽으면 안 된다.
        from app.core import legal_api
        self.assertIn('cache_key = f"v4:', inspect.getsource(legal_api.fetch_article))


class AnswerRulesTest(unittest.TestCase):
    """K11 — 정확성 규칙이 두 답변 분기 공통으로 붙는다."""

    def test_k11_rules_appended_for_both_branches(self):
        from app.core import pipeline as pl
        src = inspect.getsource(pl.process_question)
        self.assertIn("system_prompt + WAGE_CALC_RULES + ANSWER_ACCURACY_RULES", src)
        # 분기(if consultation…) 안이 아니라 분기 뒤 공통 지점이어야 한다
        branch = src.index("SYSTEM_PROMPT_TEMPLATE.format(")
        rule = src.index("ANSWER_ACCURACY_RULES")
        self.assertGreater(rule, branch)

    def test_k11_rules_content(self):
        from app.templates.prompts import ANSWER_ACCURACY_RULES as R
        for phrase in ("요약·결론·표", "특정 날짜 하나만 권하지", "[구 기준 주의]", "예시"):
            self.assertIn(phrase, R)

    def test_k11_admin_test_call_matches_production_prompt(self):
        from api.model_settings import test_messages
        from app.templates.prompts import ANSWER_ACCURACY_RULES
        system, _ = test_messages()
        self.assertIn(ANSWER_ACCURACY_RULES.strip()[:20], system)


if __name__ == "__main__":
    unittest.main(verbosity=1)
