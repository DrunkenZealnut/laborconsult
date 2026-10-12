#!/usr/bin/env python3
"""law-article-coverage 오프라인 회귀(AC1~AC16) — API 키·네트워크 불요.

지식iN 블라인드 재채점(2026-10-06, 프로덕션 20문항 78.4점)의 누락 25건은 대부분 모델이 아니라 근거 조문
공급의 공백이었다. 캐시에 있는 조문을 실을 규칙이 없었고(감봉 제95조·정리해고 제24조 등), 의도분석이 요청한
법령은 예열 밖이었으며, '상시 5명 이상' 적용 조건을 다루는 규칙이 없었다. 설계 중에 삭제된 산재보험법
제125조가 세 경로로 실리고 있던 것과, 휴업수당 계산기가 4명 이하에도 적용된다고 적어 둔 것도 드러났다.
아래 검사는 그 처방이 **조용히** 무너지는 지점을 고정한다.

실행: python3 test_law_article_coverage.py
"""
from __future__ import annotations

import contextlib
import io
import logging
import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "data" / "annex_fixtures"
E = "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률"

_PATCHES: list = []


def setUpModule():
    # 실제 Supabase(L2)·법제처로 나가지 않게 한다.
    from app.core import legal_api
    _PATCHES.append(mock.patch.object(legal_api, "_init_supabase", return_value=None))
    _PATCHES.append(mock.patch.dict(os.environ, {"LAW_API_LIVE": "off"}))
    for p in _PATCHES:
        p.start()
    logging.disable(logging.CRITICAL)


def tearDownModule():
    logging.disable(logging.NOTSET)
    for p in reversed(_PATCHES):
        p.stop()


def _fixture(name: str) -> str:
    """별표 fixture 본문(첫 줄 출처 주석 제외)."""
    return (FIXTURES / name).read_text(encoding="utf-8").split("\n", 1)[1]


class KeywordRulesTest(unittest.TestCase):
    """AC1~AC3 — 새 규칙·구어 확장·2단 선택·예열 대상."""

    POSITIVES = [
        ("징계로 감봉 3개월을 받았는데 한도가 있나요", "근로기준법 제95조"),
        ("장사가 안된다는 이유로 갑자기 해고통보를 받았는데 보상받을 방법이 없나요", "근로기준법 제24조"),  # 재채점 22
        ("직원16명 소기업 경영악화로 직원해고시 절차가 궁금합니다", "근로기준법 제24조"),
        ("매출이 줄어서 다음 달부터 그만 나오래요", "근로기준법 제24조"),
        # '(그만) 나오지 말라'는 휴업 지시와 같은 표현이라 동사로 넣지 않는다(제46조와 갈리지 않는다)
        ("부당해고로 원직복직 대신 금전보상을 받고 싶어요", "근로기준법 제30조"),
        ("3개월미만 부당해고일 경우에는 어떤 보상을 받을 수 있나요?", "근로기준법 제30조"),        # 재채점 23
        ("특별연장근로 인가 없이 야근시키면 불법인가요", "근로기준법 시행규칙 제9조"),           # 재채점 26
        ("최근 몇 주간 주 52시간을 훌쩍 넘는 초과근무를 하고 있어요", "근로기준법 제53조"),
        ("임신 10주차인데 근무시간 단축을 청구하는 절차가 궁금해요", "근로기준법 시행령 제43조의2"),  # 재채점 6
        ("퇴직연금(DC형) 중도인출 요건이 되지 않아요", "근로자퇴직급여 보장법 제22조"),            # 재채점 15
        ("dc형 퇴직연금 부담금은 얼마를 넣어야 하나요", "근로자퇴직급여 보장법 제20조"),
        ("4대보험을 가입한다며 근로 계약서에 체크했는데 알고보니 가입이 안되어 있네요", "고용보험법 제15조"),  # 14
        ("작업지시는 원청 현장관리자에게 무전으로 받고 근로계약서는 도급으로 작성했습니다",
         "파견근로자 보호 등에 관한 법률 제6조의2"),                                            # 재채점 25
        ("육아휴직을 신청했는데 회사가 아무 답이 없어요", f"{E} 시행령 제11조"),                 # 재채점 1
        ("가족돌봄휴직을 회사가 거부할 수 있나요", f"{E} 시행령 제16조의3"),                     # 재채점 3
    ]
    NEGATIVES = [
        ("경영상 어려움으로 임금이 삭감됐어요", "제24조"),            # 기존 R9 반례 — 해고 동사가 없다
        ("장사가 안 돼서 월급이 밀렸어요", "제24조"),                 # 체불
        ("회사사정이 안좋아서 구조조정으로 그만두시는분 연차수당 문의", "제24조"),
        ("경영악화로 인원감축 퇴사했는데 실업급여 받을 수 있나요", "제24조"),
        ("2주간 특별 연장수당이 퇴직금 계산에 포함되나요", "시행규칙 제9조"),
        ("부당해고인가요? 권고사직인가요? 실업급여 받을 수 있나요?", "제30조"),  # 문장을 넘어 '받을 수'
        ("산재 요양 후 복직하면 원직 복직이 아닌 다른 작업을 시킨대요", "제30조"),
        ("원청에서 일하는데 하청업체가 임금을 안 줘요", "파견근로자"),
        ("원청이 하청 작업을 중지시켰어요", "파견근로자"),             # '중지시키다'의 '지시'
        ("원청 안전감독이 하청 현장을 점검했어요", "파견근로자"),       # '감독'은 넣지 않는다
        ("연장수당 계산해 주세요", "제53조"),
        ("4대보험 미가입인데 실업급여 받을 수 있나요", "고용보험법 제15조"),
        ("국민연금 미가입 상태인데 괜찮나요", "고용보험법 제15조"),
        ("아내가 임신 중인데 단축근무 되나요", "시행령 제43조의2"),
        ("퇴직금을 IRP로 받아야 하나요", "근로자퇴직급여 보장법"),
    ]

    def test_ac1_positive_and_negative(self):
        from app.core.law_catalog import keyword_laws
        for q, want in self.POSITIVES:
            refs = keyword_laws(q)
            self.assertTrue(any(r == want or r.endswith(want) for r in refs), f"{q!r} → {refs}")
        for q, unwanted in self.NEGATIVES:
            refs = keyword_laws(q)
            self.assertFalse(any(unwanted in r for r in refs), f"{q!r} → {refs}")

    def test_ac2_two_tier_selection(self):
        from app.core.law_catalog import keyword_laws
        q = "육아휴직 후 육아기 근로시간 단축을 쓰다가 가족돌봄휴가를 쓰려는데 거부당했어요"
        self.assertEqual(keyword_laws(q), [f"{E} 제19조", f"{E} 제19조의2", f"{E} 제22조의2"],
                         "주 조문이 3칸을 채우면 보충 조문(시행령)은 들어가지 않는다 — 1단이면 제22조의2가 빠졌다")
        self.assertEqual(keyword_laws("임신 12주인데 근로시간 단축을 신청하려고 해요"),
                         ["근로기준법 제74조", "근로기준법 시행령 제43조의2"])
        self.assertEqual(keyword_laws("특별연장근로 인가가 필요한가요"),
                         ["근로기준법 제53조", "근로기준법 시행규칙 제9조"])
        self.assertEqual(keyword_laws("주 52시간 초과인데 특별연장근로 인가를 받았대요"),
                         ["근로기준법 제53조", "근로기준법 시행규칙 제9조"], "같은 조문은 한 번만")
        self.assertEqual(keyword_laws("장사가 안된다는 이유로 해고됐어요. 개인사정으로 4대보험 가입을 안 했어요"),
                         ["근로기준법 제24조", "고용보험법 제15조", "고용보험법 제118조"],
                         "과태료 제118조는 보충 — 남는 칸에만")
        self.assertEqual(keyword_laws("육아휴직을 거부당했어요"), [f"{E} 제19조", f"{E} 시행령 제11조"])

    def test_ac3_all_refs_resolve_and_are_warmed(self):
        from app.core.law_catalog import KEYWORD_LAWS, warm_law_keys
        from app.core.legal_api import _law_key, canonical_law_name, parse_law_reference
        for rule in KEYWORD_LAWS:
            for ref in rule.refs + rule.extra:
                parsed = parse_law_reference(ref)
                self.assertIsNotNone(parsed, ref)
                self.assertIn(_law_key(canonical_law_name(parsed["law"])), warm_law_keys(), ref)


class DefaultsAndAliasTest(unittest.TestCase):
    """AC4~AC6 — 주제 기본 조문·약칭·예열 목록."""

    def _consult(self, topic, relevant, *, drop=()):
        from app.config import AppConfig
        from app.core import legal_consultation as lc
        cfg = AppConfig(openai_client=None, pinecone_index=None, claude_client=None)
        cfg.law_api_key = "k"
        with mock.patch.object(lc, "fetch_relevant_articles", return_value=None) as f:
            lc.process_consultation("q", topic, relevant, cfg, drop_refs=drop)
        return f.call_args.args[0] if f.called else []

    def test_ac4_topic_defaults_and_sexual_drop(self):
        from app.core.law_catalog import SEXUAL_HARASSMENT_DROP_REFS
        from app.core.legal_consultation import TOPIC_SEARCH_CONFIG as T
        iaci = T["산재보상"]["default_laws"]
        self.assertNotIn("산업재해보상보험법 제125조", iaci, "2022.6.10 삭제 조문")
        self.assertIn("산업재해보상보험법 제41조", iaci)
        self.assertIn("산업재해보상보험법 제112조", iaci)
        self.assertIn("고용보험법 제70조", T["고용보험"]["default_laws"], "육아휴직 급여는 제70조")
        self.assertNotIn("고용보험법 제69조", T["고용보험"]["default_laws"], "제69조는 준용 조문")
        self.assertIn("근로기준법 제116조", T["직장내괴롭힘"]["default_laws"])
        self.assertIn("근로기준법 제116조", SEXUAL_HARASSMENT_DROP_REFS)
        self.assertEqual(self._consult("직장내괴롭힘", [], drop=SEXUAL_HARASSMENT_DROP_REFS),
                         [f"{E} 제14조의2"], "성희롱이면 괴롭힘 조문(76의2·76의3·116)을 뺀다")

    def test_ac5_alias_suffix_and_new_aliases(self):
        from app.core.legal_api import _alias_name, article_cache_key
        self.assertEqual(_alias_name("근기법 시행령"), "근로기준법 시행령")
        self.assertEqual(_alias_name("남녀고용평등법 시행령"), f"{E} 시행령")
        self.assertEqual(_alias_name("산재법 시행규칙"), "산업재해보상보험법 시행규칙")
        self.assertEqual(_alias_name("성폭력처벌법"), "성폭력범죄의 처벌 등에 관한 특례법")
        self.assertEqual(_alias_name("징수법"), "고용보험 및 산업재해보상보험의 보험료징수 등에 관한 법률")
        self.assertEqual(_alias_name("건강보험법"), "국민건강보험법")
        self.assertEqual(_alias_name("국세징수법"), "국세징수법", "다른 법령은 바꾸지 않는다")
        self.assertEqual(article_cache_key("근기법 시행령", 43, 2), article_cache_key("근로기준법 시행령", 43, 2))

    def test_ac6_intent_warm_laws(self):
        from app.core import legal_api
        from app.core.law_catalog import INTENT_WARM_LAWS, warm_law_names
        names = warm_law_names()
        for law in INTENT_WARM_LAWS:
            self.assertIn(law, names)
        self.assertIn(f"{E} 시행령", names, "보충 조문의 법령도 예열 대상")
        self.assertTrue(legal_api._is_warmed_law("민법"))
        self.assertTrue(legal_api._is_warmed_law("성폭력처벌법"))


class AnnexTest(unittest.TestCase):
    """AC7~AC8 — 별표 '적용 규정' 파서와 주장."""

    def test_ac7_real_annex_listing(self):
        import check_law_freshness as c
        lsa = c.annex_listing(_fixture("lsa_enf_annex1_20251023.txt"))
        A, P = c.ANNEX_ALL, c.ANNEX_PARTIAL
        self.assertEqual(lsa.articles[(23, None)], frozenset({2}))
        self.assertEqual(lsa.articles[(55, None)], frozenset({1}))
        self.assertEqual(lsa.articles[(70, None)], frozenset({2, 3}))
        for n in (26, 35, 38, 42, 49, 74, 76):        # 쪼개진 번호(제 ┃ ┃ │35조부터·제49 ┃ ┃ │조까지)도 읽는다
            self.assertEqual(lsa.articles[(n, None)], A, n)
        self.assertEqual(lsa.articles[(65, None)], P, "임산부·18세 미만으로 한정 → 부분")
        self.assertEqual(lsa.articles[(109, None)], P, "벌칙은 조건부 → 부분")
        for n in (24, 27, 28, 46, 50, 53, 56, 60, 94, 95):
            self.assertNotIn((n, None), lsa.articles, n)
        self.assertFalse(lsa.unparsed)
        fta = c.annex_listing(_fixture("fta_enf_annex1_20210408.txt"))
        self.assertNotIn((4, None), fta.articles, "기간제법 제4조는 4명 이하에 적용되지 않는다")
        self.assertEqual(fta.articles[(16, None)], P, "호 한정 → 부분")
        self.assertEqual(fta.articles[(5, None)], A)

    def test_ac7_parser_edge_cases_fail_closed(self):
        import check_law_freshness as c
        L = c.annex_listing
        self.assertIsNone(c.annex_claim_holds(L("적용법규정 제76조의2부터 제76조의3까지"), "제76조의2", False),
                          "가지번호가 든 범위는 해석하지 않는다")
        self.assertIsNone(c.annex_claim_holds(L("적용법규정 제70조부터 제80조까지"), "제76조의2", False),
                          "일반 범위 안의 가지 조문은 포함 여부를 알 수 없다")
        excluded = L("적용법규정 제50조(제2항은 제외한다)")
        self.assertFalse(c.annex_claim_holds(excluded, "제50조", True), "제외 괄호 → 부분 — '있음' 근거 아님")
        self.assertFalse(c.annex_claim_holds(excluded, "제50조", False), "부분이면 '없음'도 거짓")
        self.assertIsNone(c.annex_claim_holds(L("적용법규정 제50조(제51조는 제외한다)"), "제51조", False),
                          "괄호 안의 조문 언급은 해석하지 않는다(fail-closed)")
        part = L("적용법규정 제50조(임산부에 한정한다)")
        self.assertFalse(c.annex_claim_holds(part, "제50조", True), "부분은 '있음'의 근거가 아니다")
        self.assertFalse(c.annex_claim_holds(part, "제50조", False), "부분이면 '없음'도 거짓")
        merged = L("적용법규정 제23조제2항, 제23조제1항")
        self.assertEqual(merged.articles[(23, None)], frozenset({1, 2}), "같은 조는 합친다")
        self.assertFalse(c.annex_claim_holds(merged, "제23조", False), "항 한정으로라도 있으면 조 단위 '없음'은 거짓")
        header = L("별표 1 … 법 규정(제7조 관련) 구분 적용법규정 제1조")
        self.assertNotIn((7, None), header.articles, "머리말의 '(제7조 관련)'은 목록이 아니다")

    def test_ac8_claims_hold_on_fixtures_and_cover_rule_text(self):
        import check_law_freshness as c
        from app.core.rule_facts import ANNEX_CLAIMS
        from app.templates.prompts import ANSWER_ACCURACY_RULES
        texts = {"근로기준법 시행령": _fixture("lsa_enf_annex1_20251023.txt"),
                 "기간제 및 단시간근로자 보호 등에 관한 법률 시행령": _fixture("fta_enf_annex1_20210408.txt")}
        for claim in ANNEX_CLAIMS:
            self.assertIs(c.annex_claim_holds(c.annex_listing(texts[claim.law]), claim.ref, claim.applies), True,
                          claim)
        # 정확성 규칙 문안의 근로기준법 조문이 모두 주장 목록에 있어야 한다(문안만 고치고 주장을 빠뜨리는 것 방지)
        other_law = re.compile(r"\((?:최저임금법|근로자퇴직급여 보장법|같은 법|기간제법)[^)]*\)")
        lines = {"5명 이상 전용": False, "규모와 무관": True}
        claimed = {(cl.ref, cl.applies) for cl in ANNEX_CLAIMS if cl.group == "answer_rules"}
        for label, applies in lines.items():
            line = next(ln for ln in ANSWER_ACCURACY_RULES.splitlines() if ln.strip().startswith(f"- {label}"))
            refs = {f"제{a}조" + (f"제{p}항" if p else "")
                    for a, p in re.findall(r"제(\d+)조(?: 제(\d+)항)?", other_law.sub("", line))}
            self.assertTrue(refs, label)
            for ref in refs:
                self.assertIn((ref, applies), claimed, f"{label}: {ref}")
        self.assertIn(("제4조", False), {(cl.ref, cl.applies) for cl in ANNEX_CLAIMS
                                         if cl.law.startswith("기간제")})


class RuleTextTest(unittest.TestCase):
    """AC9~AC10 — 5인 조건 문안·심혈관 블록."""

    def test_ac9_size_rule_text_and_anchor_registration(self):
        import fetch_official_rules as fo
        from app.templates.prompts import ANSWER_ACCURACY_RULES, ANSWER_RULE_ANCHORS
        i = ANSWER_ACCURACY_RULES.index("- 상시 근로자 수가 질문에 없는데")
        item = ANSWER_ACCURACY_RULES[i:].strip()
        for part in ("5명 이상 전용", "규모와 무관", "규모가 질문에 있으면", "제11조", "별표 1"):
            self.assertIn(part, item)
        self.assertLessEqual(len(item), 600, "모든 요청에 붙으므로 문안을 짧게 유지한다")
        ids = {a[0] for a in fo.ARTICLES}
        self.assertTrue({d for d, _ in ANSWER_RULE_ANCHORS} <= ids)
        self.assertTrue({"lsa_act_11", "fta_act_3", "fta_enf_2", "mw_act_3", "erb_act_3", "eeo_act_3",
                         "eeo_enf_2", "iaci_act_112"} <= ids)

    def test_ac10_cardio_block(self):
        import fetch_official_rules as fo
        from app.core.rule_facts import RULE_FACTS, build_rule_facts
        names = lambda q, a=None: [n for n, _ in build_rule_facts(q, a)]  # noqa: E731
        q11 = ("산재 질문드립니다 ㅠㅠ 안녕하세요 2022년 7월1일 예비군 훈련도중 뇌출혈 수술을 햿습니다 "
               "그전까지는 17~5시 12시간 주방근무 했는데 가능할까욧")
        self.assertIn("occupational_cardio", names(q11))
        self.assertIn("occupational_cardio", names("출장 중 갑작스런 뇌경색 진단 산재신청 가능할까요"))
        self.assertIn("occupational_cardio", names("남편이 심근경색으로 쓰러졌어요",
                                                   NS(consultation_topic="산재보상", calculation_types=[])))
        for q in ("어머니가 갑작스러운 뇌출혈로 회사를 장기간 못가셔서 실업급여 문의",
                  "대동맥박리 수술 후 회사가 소견서 제출을 요구해요",
                  "할머니 뇌경색으로 장기요양급여 신청하려고요"):
            self.assertNotIn("occupational_cardio", names(q), q)
        fact = next(f for f in RULE_FACTS if f.name == "occupational_cardio")
        self.assertEqual({d for d, _ in fact.anchors}, {"cardio_notice", "iaci_act_112"})
        self.assertIn("cardio_notice", {a[0] for a in fo.ADMRULS})
        self.assertIn("cardio_notice", fo.ADMRUL_LAW_GO_KR_ONLY, "게시판 첨부가 아니라 법제처 통합본으로만 받는다")
        text = dict(build_rule_facts(q11, None))["occupational_cardio"]
        for part in ("60시간", "64시간", "52시간", "30%", "30퍼센트", "24시간", "3년", "5년", "자연경과"):
            self.assertIn(part, text, part)


class FreshnessChecksTest(unittest.TestCase):
    """AC11 — 생존 점검·고시 앵커·종료 코드(fetch는 mock)."""

    LAW_XML = ("<법령><기본정보><시행일자>20261002</시행일자></기본정보>"
               "<조문단위><조문번호>37</조문번호><조문여부>조문</조문여부><조문제목>업무상의 재해의 인정 기준</조문제목>"
               "<조문내용>제37조(업무상의 재해의 인정 기준)</조문내용></조문단위>"
               "<조문단위><조문번호>125</조문번호><조문여부>조문</조문여부>"
               "<조문내용>제125조 삭제 &lt;2022.6.10&gt;</조문내용></조문단위></법령>")

    def test_ac11_liveness_flags_deleted_and_missing(self):
        import xml.etree.ElementTree as ET
        import check_law_freshness as c
        root = ET.fromstring(self.LAW_XML)
        targets = [("t:1", "산업재해보상보험법 제37조"), ("t:2", "산업재해보상보험법 제125조"),
                   ("t:3", "산업재해보상보험법 제999조")]
        with mock.patch.object(c, "_reference_targets", return_value=targets), \
                mock.patch.object(c, "_next_root", return_value=None):
            fails, warns = c._liveness_checks("k", "20261007", {"산업재해보상보험법": root})
        self.assertTrue(any("제125조" in f and "삭제" in f for f in fails), fails)
        self.assertTrue(any("제999조" in f and "없는" in f for f in fails), fails)
        self.assertFalse(any("제37조" in f for f in fails), fails)

    def test_ac11_notice_anchor_failures_and_exit_code(self):
        import check_law_freshness as c
        import fetch_official_rules as fo
        with mock.patch.object(c, "_next_root", return_value=None), \
                mock.patch.object(fo, "fetch_admrul", return_value={"body": "관련 없는 본문", "effective": "20260223"}), \
                mock.patch.object(fo, "stored_notice", return_value={"date": "20260223"}):
            fails, warns = c._anchor_checks("k", "20261007")
        self.assertTrue(any("cardio_notice" in f for f in fails), fails)
        self.assertFalse(any("미등록 cardio_notice" in w for w in warns), "고시 문서를 미등록으로 보고하지 않는다")
        with mock.patch.object(c, "_next_root", return_value=None), \
                mock.patch.object(fo, "fetch_admrul", side_effect=RuntimeError("timeout")):
            fails, _ = c._anchor_checks("k", "20261007")
        self.assertTrue(any("조회 실패" in f for f in fails), "조회 실패도 실패(fail-closed)")
        with mock.patch.object(c, "_watched_laws", return_value=[]), \
                mock.patch.object(c, "_anchor_checks", return_value=(["x"], [])), \
                mock.patch.object(c, "_annex_checks", return_value=([], [])), \
                mock.patch.object(c, "_liveness_checks", return_value=([], [])), \
                mock.patch.dict(os.environ, {"LAW_API_KEY": "k"}), \
                mock.patch("dotenv.load_dotenv"), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(c.main(["--anchors"]), 1, "앵커 실패는 종료 코드 1")


class WiringTest(unittest.TestCase):
    """AC12~AC16 — 배선·삭제 조문 차단·업로더·휴업수당·괴롭힘 블록."""

    def test_ac12_article_refs_21_uses_two_tier_and_sexual_drop(self):
        from app.core.pipeline import _article_refs_21
        refs = _article_refs_21("임신 12주인데 근로시간 단축 신청 절차가 궁금해요", None, False)
        self.assertEqual(refs[:2], ["근로기준법 제74조", "근로기준법 시행령 제43조의2"])
        refs = _article_refs_21("팀장이 성추행을 해서 신고했어요", NS(relevant_laws=["근로기준법 제116조"]), True)
        self.assertNotIn("근로기준법 제116조", refs)

    def test_ac13_deleted_refs_blocked(self):
        import check_law_freshness as c
        from app.core import legal_api
        refs = c.code_law_refs(str(ROOT))
        self.assertGreater(len(refs), 100, "코드 속 조문 표기를 실제로 뽑아야 한다")
        leaks = [(path, line, ref) for path, line, ref in refs
                 if ref in c.KNOWN_DELETED_REFS and (path, ref) not in c.DELETED_REF_MENTIONS]
        self.assertEqual(leaks, [], "알려진 삭제 조문이 코드에 남아 있다")
        self.assertTrue(legal_api.is_deleted_article("125\n제125조 삭제 <2022.6.10>"))
        self.assertFalse(legal_api.is_deleted_article("2(적용범위)\n제2조(적용범위) ① 법\n② 삭제 <2018.5.28>"),
                         "항 하나만 삭제된 조문은 살아 있다")
        stats = legal_api.new_law_stats()
        with mock.patch.object(legal_api, "fetch_article", return_value="125\n제125조 삭제 <2022.6.10>"):
            out = legal_api.fetch_relevant_articles(["산업재해보상보험법 제125조"], "k", stats=stats)
        self.assertIsNone(out, "삭제 조문은 컨텍스트에 싣지 않는다")
        self.assertEqual((stats["articles"]["requested"], stats["articles"]["deleted"]), (1, 1))

    def test_ac14_uploader_skips_anchor_only_docs(self):
        import pinecone_upload_official_rules as up
        doc = ("# {t}\n\n- doc_id: {d}\n- source_type: law\n- title: {t}\n"
               "- official_url: https://www.law.go.kr/x\n- issuer: x\n- date: 20260101\n- keys: {k}\n\n## 본문\n\n본문")
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "a.md").write_text(doc.format(t="a", d="keyed", k="minimum_hourly_wage"), encoding="utf-8")
            Path(tmp, "b.md").write_text(doc.format(t="b", d="anchor_only", k=""), encoding="utf-8")
            docs, skipped, anchor_only = up.collect_docs(tmp)
        self.assertEqual([d["doc_id"] for d in docs], ["keyed"])
        self.assertEqual(anchor_only, ["anchor_only"])
        self.assertEqual(skipped, [])

    def test_ac15_shutdown_under_5_and_size_assumption_note(self):
        from app.core.pipeline import _SIZE_ASSUMED_NOTE, _analysis_to_extract_params, _run_calculator
        stub = lambda info: NS(requires_calculation=True, calculation_types=["shutdown_allowance"],  # noqa: E731
                               extracted_info=info)
        base = {"wage_type": "시급", "wage_amount": 12000, "shutdown_days": 5, "daily_work_hours": 8,
                "weekly_work_days": 5}
        small = _run_calculator(_analysis_to_extract_params(stub({**base, "business_size": "5인미만"})), "")
        self.assertIn("휴업수당: 미적용 (상시 4명 이하 사업장)", small)
        self.assertNotIn("적용 기준: 평균임금 70%", small)
        self.assertIn("근로기준법 제46조(휴업수당)가 적용되지 않습니다", small)
        unknown = _run_calculator(_analysis_to_extract_params(stub(base)), "")
        self.assertIn(_SIZE_ASSUMED_NOTE, unknown, "규모 미기재 → 5명 이상 가정 고지")
        known = _run_calculator(_analysis_to_extract_params(stub({**base, "business_size": "5인이상"})), "")
        self.assertNotIn(_SIZE_ASSUMED_NOTE, known)
        src = (ROOT / "wage_calculator" / "calculators" / "shutdown_allowance.py").read_text(encoding="utf-8")
        self.assertNotIn("- 5인 미만 사업장에도 적용", src, "핵심 규칙에서 4명 이하 적용 주장을 지웠다")

    def test_ac16_harassment_block_skips_sexual_only(self):
        from app.core.rule_facts import build_rule_facts
        topic = NS(consultation_topic="직장내괴롭힘", calculation_types=[])
        names = lambda q: [n for n, _ in build_rule_facts(q, topic)]  # noqa: E731
        self.assertNotIn("harassment_retaliation", names("회식 자리에서 팀장이 성적인 농담을 해요"),
                         "성희롱만이면 '규모 먼저 확인' 문장을 싣지 않는다")
        self.assertIn("harassment_retaliation", names("팀장의 괴롭힘과 성추행이 계속돼요"))
        self.assertIn("harassment_retaliation", names("상사가 매일 폭언을 해요"))


if __name__ == "__main__":
    unittest.main()
