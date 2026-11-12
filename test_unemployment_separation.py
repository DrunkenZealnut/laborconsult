#!/usr/bin/env python3
"""실업급여 이직사유 근거 보강 회귀 — unemployment-separation-grounds U1~U12 (오프라인, API 키 불요, CI).

감지(강·약 단서·초점어) · 동반 블록(MAX_BLOCKS 칸을 쓰지 않음) · 수량 결속·요건 앵커 · CI 별표 fixture 대조 ·
별표 선택(annex_unit) · 2-1 배선·예열 · 현행성 점검(fetch mock) · 폐기 기준 상호 제약 · 판정 단일 출처 · 수집 스크립트.
"""
from __future__ import annotations

import ast
import json
import os
import re
import tempfile
import unicodedata
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "data" / "annex_fixtures"
XML_FIXTURE = FIXTURES / "ei_rule_annexes_20260918.xml"
ANNEX_FIXTURES = {"ei_rule_annex2": FIXTURES / "ei_rule_annex2_20260918.txt",
                  "ei_rule_annex1_2": FIXTURES / "ei_rule_annex1_2_20260918.txt",
                  # 산재법 별표 1(고령자 휴업급여 계수) — 산재 계산기 앵커(calculator-statute-audit I3). XML fixture는 고용보험법 시행규칙 것이라
                  # U5의 제목 유일성 검사는 그 법령의 별표에만 돈다
                  "iaci_annex1": FIXTURES / "iaci_annex1_20260701.txt"}
norm = lambda t: re.sub(r"\s+", "", t or "")  # noqa: E731

# 설계 §8.1 S+(합성 양성 13) — 측정 하네스 synthetic.json과 같은 문장
POSITIVE = (
    "식당에서 1년 넘게 일했는데 3개월째 월급이 절반만 들어오고 지난달에는 아예 못 받았어요. 이번 달 말에 그만두려고 하는데 실업급여를 받을 수 있을까요?",
    "편의점에서 일하는데 시급이 최저임금보다 낮게 몇 달째 계산돼서 나왔어요. 이 이유로 그만두면 실업급여 대상이 되나요?",
    "석 달 동안 거의 매주 60시간씩 일했어요. 연장근로 제한을 넘긴 것 같은데 몸이 버티질 못해서 퇴사하면 실업급여 받을 수 있나요?",
    "회사가 경기도 외곽으로 이전하면서 출퇴근에 왕복 3시간 반이 걸리게 됐어요. 그만두면 실업급여 받을 수 있나요?",
    "어머니가 수술을 받으셔서 두 달 정도 제가 직접 간병해야 하는데 회사가 휴직을 안 해준대요. 퇴사하면 실업급여를 받을 수 있나요?",
    "허리 디스크가 심해져서 지금 하는 물류 일을 계속하기 어렵고, 회사는 다른 업무로 바꿔줄 수 없다고 해요. 퇴사하면 실업급여 받을 수 있나요?",
    "7살 아이를 돌봐줄 사람이 없어 육아휴직을 신청했는데 회사가 거절했어요. 결국 그만두게 되면 실업급여 대상인가요?",
    "회사 경영이 어려워져서 인원을 줄인다며 권고사직을 받았어요. 실업급여 받을 수 있나요?",
    "1년 계약직으로 일했는데 계약 기간이 끝나고 회사가 재계약을 하지 않겠다고 해요. 실업급여 받을 수 있나요?",
    "팀장의 폭언과 괴롭힘이 계속돼서 결국 회사를 그만뒀어요. 이런 경우에도 실업급여를 받을 수 있나요?",
    "회사 사정이 안 좋다고 사장님이 다음 달부터 나오지 말래요. 그만두면 실업급여 돼요?",
    "남편이 지방으로 발령이 나서 함께 이사 가야 하는데, 지금 직장은 너무 멀어져서 퇴사해야 해요. 실업급여 받을 수 있나요?",
    "임신 중인데 몸이 힘들어 휴직을 요청했지만 회사가 허락하지 않았어요. 퇴사하면 실업급여 대상이 되나요?",
)
# 강단서 양성 — 2-1 키워드 규칙(제58조)까지 받는 문항(설계 §1.3: 양성 13 중 8 — 실측, 2026-11-06). 약단서만 있는 간병·질병·임신은 블록만.
STRONG_POSITIVE = tuple(POSITIVE[i] for i in (0, 1, 3, 6, 7, 8, 9, 10))
WEAK_ONLY_POSITIVE = tuple(POSITIVE[i] for i in (2, 4, 5, 11, 12))
# 설계 §1.3 검증 지적 오탐 예문 12건 — rev1은 6건 이상 발동, rev2는 0
NEGATIVE = (
    "육아휴직 급여 수급자격이 되는지 알고 싶어요. 입사 6개월째인데요",
    "출산전후휴가 급여 신청은 어디서 하고 서류는 무엇이 필요한가요",
    "실업급여 받는 중에 아파서 실업인정일에 못 갔어요. 어떻게 하죠",
    "이번 달 급여가 안 들어와요. 사장님은 다음 주에 준다고만 해요",
    "실업급여 부정수급을 자진신고하려고 합니다. 절차가 어떻게 되나요",
    "간호조무사인데 실업급여 금액이 얼마나 되나요",
    "실업급여 하루 금액이 얼마인가요. 월급은 300만원이었어요",
    "실업급여 받으면서 알바 해도 되나요",
    "조기재취업수당은 언제 신청하나요",
    "실업인정일에 꼭 고용센터에 방문해야 하나요",
    "고용보험 가입 기간이 180일이 안 되면 실업급여 못 받나요",
    "기계에 손가락이 잘렸어요. 산재 처리하고 실업급여도 받을 수 있나요",
)
KIN = {
    "kin-03": ("한 달에 한 번 일용 알바 계약서를 쓰고 3.3%를 떼고 주급으로 받고 있으며 고용보험 등 4대보험은 미가입입니다. "
               "이전 계약직 기간에도 미가입이었습니다. 실업급여를 받을 수 있나요?", False),
    "kin-10": ("2차 실업인정 기간 28일 사이에 추석·개천절·대체공휴일이 있습니다. 구직급여가 28일치 그대로 나오나요, "
               "공휴일을 빼고 나오나요?", False),
    "kin-11": ("2년 넘게 다닌 회사를 퇴직한 뒤 한 달짜리 계약직으로 주말(토·일) 하루 8시간씩 일하게 됐습니다. 이 계약이 끝난 뒤 "
               "실업급여를 받을 수 있나요?", True),
    "kin-12": ("공사가 끝나 9월 22일 퇴사했고 10월 7일 고용센터에서 실업급여를 신청할 예정입니다. 그 뒤 10월 12일에 취업이 되면 "
               "조기재취업수당을 받을 수 있나요?", False),
}
# U2 — 문장 속 수량은 모두 이 표에 있고, 결속어와 40자 안에 함께 나온다(블록 문장 **과** 같은 호의 앵커 양쪽)
QUANTITY_BINDING = (("1년", "이내"), ("2개월", "이상"), ("70퍼센트", "휴업"), ("3시간", "왕복"), ("30일", "간호"),
                    ("8세", "자녀"), ("2학년", "초등학교"))
QUANTITY_RE = re.compile(r"\d+\s*(?:년|개월|주|일|시간|퍼센트|%|세|학년|회|명)")


def _sep():
    from app.core.rule_facts import RULE_FACTS
    return next(f for f in RULE_FACTS if f.name == "separation_grounds")


def _names(q, a=None):
    from app.core.rule_facts import build_rule_facts
    return [n for n, _ in build_rule_facts(q, a)]


def _bound(text: str, qty: str, bind: str, window: int = 40) -> bool:
    return any(abs(m.start() - b.start()) <= window
               for m in re.finditer(re.escape(qty), text) for b in re.finditer(re.escape(bind), text))


class DetectionTest(unittest.TestCase):
    """U1·U1b — 감지."""

    def test_u1_positive_negative_and_kin(self):
        from app.core.separation_signals import is_separation_question
        for q in POSITIVE:
            self.assertTrue(is_separation_question(q), q)
            self.assertTrue(is_separation_question(unicodedata.normalize("NFD", q)), f"NFD: {q}")
        for q in NEGATIVE:
            self.assertFalse(is_separation_question(q), q)
        for cid, (q, expected) in KIN.items():
            self.assertEqual(is_separation_question(q), expected, cid)
        # n-amount(금액만)는 발동하지 않고, n-transfer·n-misconduct는 이직 질문이라 발동한다(적중 판정은 측정이 한다)
        self.assertFalse(is_separation_question("월급이 300만원이었는데 실업급여 하루 금액은 얼마나 나오나요?"))
        self.assertTrue(is_separation_question("지금보다 연봉이 높은 회사로 옮기려고 사직서를 냈어요. 새 회사 입사 전까지 실업급여를 받을 수 있나요?"))
        self.assertTrue(is_separation_question("회사 공금을 횡령했다는 이유로 해고됐어요. 실업급여는 받을 수 있나요?"))
        self.assertFalse(is_separation_question(""), "빈 입력")
        self.assertFalse(is_separation_question(None))

    def test_u1b_question_summary_is_a_secondary_signal(self):
        from app.core.separation_signals import is_separation_question
        follow_up = "그럼 저는 받을 수 있는 건가요?"
        self.assertFalse(is_separation_question(follow_up))
        a = NS(question_summary="자진퇴사 뒤 실업급여 수급자격 문의", consultation_topic=None, calculation_types=[])
        self.assertIn("separation_grounds", _names(follow_up, a), "요약에만 단서가 있는 후속 턴")
        self.assertNotIn("separation_grounds", _names(follow_up, NS(question_summary="연차 일수 문의",
                                                                        consultation_topic=None, calculation_types=[])))


class BlockTextTest(unittest.TestCase):
    """U2·U2b·U7 — 문안의 수량·요건·길이·순서."""

    def test_u2_quantities_are_anchored_with_binding_words(self):
        fact = _sep()
        text = " ".join(fact.lines)
        table = {q for q, _ in QUANTITY_BINDING}
        found = {norm(m) for m in QUANTITY_RE.findall(text)}
        self.assertEqual(found, table, f"표 밖의 수량 또는 빠진 수량: {found ^ table}")
        annex = " ".join(p for d, p in fact.anchors if d == "ei_rule_annex2")
        for qty, bind in QUANTITY_BINDING:
            self.assertTrue(_bound(text, qty, bind), f"문장: {qty}↔{bind}")
            self.assertTrue(_bound(annex, qty, bind), f"앵커: {qty}↔{bind}")

    def test_u2b_requirement_anchors_are_in_the_sentences(self):
        text = " ".join(_sep().lines)
        for phrase in ("계속 다닐 수 없게 된", "객관적으로 인정", "휴가나 휴직이 허용되지 않아"):
            self.assertIn(phrase, text, phrase)
        self.assertIn("확정하지 않는다", text, "D9 — 수급을 확정하지 않는다")
        self.assertNotRegex(text, r"4명\s*이하|5명\s*이상|5인", "3의2호와 사업장 규모의 관계는 원문 미확정(L10)")

    def test_u7_length_order_companion(self):
        from app.core.rule_facts import RULE_FACTS
        fact = _sep()
        block = fact.build("권고사직 당했는데 실업급여 받을 수 있나요", None)
        self.assertIsNotNone(block)
        self.assertLessEqual(len(block), 2100, len(block))
        names = [f.name for f in RULE_FACTS]
        self.assertEqual(names.index("separation_grounds"), names.index("unemployment") + 1)
        self.assertEqual(fact.companion_of, "unemployment")
        self.assertEqual(len([f for f in RULE_FACTS if f.companion_of]), 1, "동반 블록은 이 하나다")


class CompanionTest(unittest.TestCase):
    """U7b — 동반 블록이 기존 블록을 밀어내지 않는다."""

    def test_u7b_companion_does_not_consume_a_slot(self):
        self.assertEqual(_names("3주 일하고 해고됐는데 4대보험도 미가입이에요. 실업급여 받을 수 있나요"),
                         ["unemployment", "separation_grounds", "insured_status", "dismissal_notice"])
        self.assertEqual(_names("상사 괴롭힘으로 퇴사했는데 고용보험 미가입이에요. 실업급여 받을 수 있나요"),
                         ["unemployment", "separation_grounds", "insured_status", "harassment_retaliation"])
        kin_139 = "수습 최저임금 80%에 주휴도 없었고 해고예고 없이 잘려서 실업급여 받을 수 있나요"
        names = _names(kin_139)
        self.assertEqual(len(names), 4)
        self.assertEqual(names[:2], ["unemployment", "separation_grounds"])
        self.assertEqual(len([n for n in names if n != "separation_grounds"]), 3, "일반 블록은 MAX_BLOCKS까지")

    def test_u7b_without_unemployment_it_uses_a_slot(self):
        # '실업수당'은 실업 문맥이지만 unemployment 블록의 감지어가 아니다 → 동반이 아니라 일반 블록으로 한 칸을 쓴다
        q = "3주 일하고 해고됐고 4대보험 미가입, 상사 괴롭힘도 있었어요. 실업수당 받을 수 있나요"
        self.assertEqual(_names(q), ["separation_grounds", "insured_status", "harassment_retaliation"])


class AnchorFixtureTest(unittest.TestCase):
    """U3·U3b·U4 — 별표 앵커 CI 대조와 등록."""

    def test_u3_annex_anchors_are_in_committed_fixtures(self):
        fact = _sep()
        for doc_id, path in ANNEX_FIXTURES.items():
            if not path.exists():
                self.fail(f"{path.name} 없음 — fetch_official_rules.py --doc {doc_id} 로 받은 output_공식법령/{doc_id}.md 본문을 "
                          "첫 줄 출처 주석과 함께 복사한다(가운뎃점·공백 원문 그대로)")
            body = path.read_text(encoding="utf-8").split("\n", 1)[1]   # 첫 줄은 출처 주석
            # 별표 fixture는 이직사유 블록 앵커와 계산기 근거 앵커(산재법 별표 1 — calculator-statute-audit I3) 둘을 CI에서 대조한다
            from wage_calculator.legal_anchors import CALC_BASIS_ANCHORS
            phrases = [p for d, p in list(fact.anchors) + list(CALC_BASIS_ANCHORS) if d == doc_id]
            self.assertTrue(phrases, doc_id)
            for phrase in phrases:
                self.assertIn(norm(phrase), norm(body), f"{doc_id}: {phrase}")   # 공백만 무시 — 가운뎃점(·/ㆍ)은 구분

    def test_u3b_fixture_matches_stored_official_text(self):
        import fetch_official_rules as fo
        checked = 0
        for doc_id, path in ANNEX_FIXTURES.items():
            stored = fo.stored_body(doc_id) if (ROOT / fo.OUT_DIR).is_dir() else None
            if stored is None or not path.exists():
                continue
            self.assertEqual(norm(path.read_text(encoding="utf-8").split("\n", 1)[1]), norm(stored),
                             f"{doc_id}: fixture가 저장본과 다르다 — 재수집 뒤 fixture를 갱신할 것")
            checked += 1
        if not checked:
            self.skipTest("output_공식법령/ 별표 저장본 없음 — 로컬 관문")

    def test_u4_anchor_docs_are_registered(self):
        import fetch_official_rules as fo
        ids = {a[0] for a in fo.ARTICLES} | {a[0] for a in fo.ADMRULS} | {a[0] for a in fo.ANNEXES}
        for doc_id, _ in _sep().anchors:
            self.assertIn(doc_id, ids, doc_id)
            self.assertRegex(doc_id, r"^[a-z0-9_]+$", "doc_id는 ASCII 소문자·숫자·밑줄")
        self.assertEqual({a[0] for a in fo.ANNEXES}, set(ANNEX_FIXTURES))
        self.assertEqual(len({d for d, _ in _sep().anchors}), 4)
        self.assertEqual(len(_sep().anchors), 45)


class AnnexUnitTest(unittest.TestCase):
    """U5 — 별표 선택(실제 응답 스키마 fixture)."""

    def test_u5_annex_unit_selects_exactly_one_table(self):
        from app.core.legal_api import annex_unit
        root = ET.parse(XML_FIXTURE).getroot()
        unit = annex_unit(root, "근로자의 수급자격이 제한되지 아니하는 정당한 이직 사유")
        self.assertEqual((unit.findtext("별표번호"), unit.findtext("별표가지번호")), ("0002", "00"))
        self.assertEqual(annex_unit(root, "사업에 막대한 지장을 초래하거나 재산상 손해를 끼친 경우").findtext("별표가지번호"), "02")
        with self.assertRaises(ValueError):
            annex_unit(root, "정당한 이직 사유")          # 별표 2·2의2·2의3 — 서식은 세지 않는다(그래서 3개)
        self.assertIsNone(annex_unit(root, "이직확인서"), "서식은 별표가 아니다")
        self.assertIsNone(annex_unit(root, "없는 제목"))
        self.assertIsNone(annex_unit(None, "x"))
        # 등록된 제목 둘은 fixture에서 유일하다 — 설계 D2
        import fetch_official_rules as fo
        for _, law, title_part, _ in fo.ANNEXES:
            if law != "고용보험법 시행규칙":
                continue                                   # fixture XML은 고용보험법 시행규칙 별표 목록이다
            self.assertIsNotNone(annex_unit(root, title_part), title_part)


class CatalogWiringTest(unittest.TestCase):
    """U6·U6b·U10 — 2-1 키워드 규칙·예열·판정 단일 출처."""

    def test_u6_article_58_for_strong_cues_only(self):
        from app.core.law_catalog import keyword_laws, warm_law_keys, warm_law_names
        from app.core.legal_api import _law_key
        for q in STRONG_POSITIVE:
            self.assertIn("고용보험법 제58조", keyword_laws(q), q)
        for q in WEAK_ONLY_POSITIVE + NEGATIVE:
            self.assertNotIn("고용보험법 제58조", keyword_laws(q), q)
        for q in POSITIVE + NEGATIVE:
            self.assertFalse(any("시행규칙 제101조" in r for r in keyword_laws(q)), q)
        self.assertIn("고용보험법 시행규칙", warm_law_names())
        self.assertIn(_law_key("고용보험법"), warm_law_keys())

    def test_u6b_keyword_limit_boundary_with_sexual_harassment(self):
        from app.core.law_catalog import keyword_laws
        refs = keyword_laws("회식에서 성추행을 당해 자진퇴사했는데 실업급여 받을 수 있나요")
        self.assertEqual(len(refs), 3)
        self.assertEqual(refs[-1], "고용보험법 제58조")
        self.assertTrue(all("남녀고용평등" in r for r in refs[:2]))

    def test_u10_single_source_of_judgement(self):
        import app.core.law_catalog as lc
        import app.core.rule_facts as rf
        import app.core.separation_signals as ss
        self.assertIs(lc.has_strong_separation_cue, ss.has_strong_separation_cue)
        self.assertIs(lc.is_unemployment_context, ss.is_unemployment_context)
        self.assertIs(rf.is_separation_question, ss.is_separation_question)
        rule = next(r for r in lc.KEYWORD_LAWS if r.name == "이직사유·수급자격 제한")
        self.assertEqual(rule.refs, ("고용보험법 제58조",))
        for q in POSITIVE + NEGATIVE:
            self.assertEqual(rule.match(" ".join(q.split())),
                             ss.is_unemployment_context(q) and ss.has_strong_separation_cue(q), q)


class FreshnessTest(unittest.TestCase):
    """U8 — `_anchor_checks`의 현행판·다음 판본·저장본 칸(fetch mock)."""

    LAW = ("<법령><기본정보><법령명_한글>고용보험법</법령명_한글><시행일자>20260101</시행일자></기본정보>"
           "<조문단위><조문번호>58</조문번호><조문여부>조문</조문여부><조문내용>제58조(이직 사유에 따른 수급자격의 제한)</조문내용>"
           "<항><항내용>① 현행 구절 ALPHA</항내용></항></조문단위></법령>")
    RULE = ("<법령><기본정보><법령명_한글>고용보험법 시행규칙</법령명_한글><시행일자>20260918</시행일자></기본정보>"
            "<별표단위><별표구분>별표</별표구분><별표제목>근로자의 수급자격이 제한되지 아니하는 정당한 이직 사유</별표제목>"
            "<별표내용>별표 본문 BETA</별표내용></별표단위>"
            "<별표단위><별표구분>별표</별표구분><별표제목>사업에 막대한 지장을 초래하거나 재산상 손해를 끼친 경우</별표제목>"
            "<별표내용>별표 본문 GAMMA</별표내용></별표단위></법령>")

    def _run(self, fact, roots, stored=None, nxt=None):
        import check_law_freshness as c
        import fetch_official_rules as fo
        import app.core.rule_facts as rf
        import app.templates.prompts as pr
        import wage_calculator.legal_anchors as la
        stored = stored or {}
        with mock.patch.object(rf, "RULE_FACTS", (fact,)), mock.patch.object(pr, "ANSWER_RULE_ANCHORS", ()), \
                mock.patch.object(la, "CALC_BASIS_ANCHORS", ()), \
                mock.patch.object(c, "fetch_law_root", side_effect=lambda law, key, **kw: roots[law]), \
                mock.patch.object(c, "_next_root", side_effect=lambda law, key, today, cache: (nxt or {}).get(law)), \
                mock.patch.object(fo, "stored_body", side_effect=lambda d: stored.get(d)):
            return c._anchor_checks("k", "20261105")

    def _fact(self, anchors):
        from app.core.rule_facts import RuleFact
        return RuleFact(name="t", detect=lambda q, a: True, lines=("x",), sources="s", as_of="d", anchors=tuple(anchors))

    def test_u8_current_version_cells(self):
        law, rule = ET.fromstring(self.LAW), ET.fromstring(self.RULE)
        roots = {"고용보험법": law, "고용보험법 시행규칙": rule}
        ok = self._fact([("ei_act_58", "현행 구절 ALPHA"), ("ei_rule_annex2", "본문 BETA"), ("ei_rule_annex1_2", "GAMMA")])
        fails, warns = self._run(ok, roots, stored={"ei_act_58": "제58조(이직 사유에 따른 수급자격의 제한)\n① 현행 구절 ALPHA", "ei_rule_annex2": "별표 본문 BETA",
                                                    "ei_rule_annex1_2": "별표 본문 GAMMA"})
        self.assertEqual(fails, [], fails)
        self.assertEqual(warns, [], warns)
        # 현행 조문 거짓 → 실패 · 현행 별표 구절 없음 → 실패
        fails, _ = self._run(self._fact([("ei_act_58", "없는 구절"), ("ei_rule_annex2", "없는 구절")]), roots)
        self.assertTrue(any("ei_act_58" not in f and "제58조" in f and "앵커 구절 없음" in f for f in fails), fails)
        self.assertTrue(any("ei_rule_annex2" in f and "앵커 구절 없음" in f for f in fails), fails)
        # 별표 0개 → 실패 · 2개 이상 → 실패 · 조회 예외 → 실패
        none_root = ET.fromstring("<법령/>")
        fails, _ = self._run(self._fact([("ei_rule_annex2", "x")]), {"고용보험법 시행규칙": none_root})
        self.assertTrue(any("별표 없음" in f for f in fails), fails)
        dup = ET.fromstring(self.RULE.replace("사업에 막대한 지장을 초래하거나 재산상 손해를 끼친 경우",
                                             "근로자의 수급자격이 제한되지 아니하는 정당한 이직 사유(2)"))
        fails, _ = self._run(self._fact([("ei_rule_annex2", "x")]), {"고용보험법 시행규칙": dup})
        self.assertTrue(any("제목 중복" in f for f in fails), fails)

        class Boom(dict):
            def __getitem__(self, k):
                raise RuntimeError("down")
        fails, _ = self._run(self._fact([("ei_act_58", "x"), ("ei_rule_annex2", "y")]), Boom())
        self.assertTrue(any("현행판 조회 실패" in f for f in fails), fails)
        self.assertTrue(any("현행 별표 조회 실패" in f for f in fails), fails)

    def test_u8c_fetch_failure_is_remembered_per_law(self):
        """L-8(PR #153 리뷰) — 현행판 조회가 예외로 실패하면 같은 법령의 다음 조문·별표 앵커도 '조회 실패(원인)'로 보고한다.
        예전에는 캐시에 None을 넣어 뒤 앵커가 '현행판에 조문 없음·별표 없음'으로 잘못 나갔다. 빈 응답(None 루트)도 '없음'과 구분한다."""
        class Down(dict):
            def __getitem__(self, k):
                raise RuntimeError("down")
        fact = self._fact([("ei_rule_101", "x"), ("ei_rule_annex2", "y"), ("ei_rule_annex1_2", "z")])
        fails, _ = self._run(fact, Down())
        self.assertFalse(any("조문 없음" in f or "별표 없음" in f for f in fails), fails)
        self.assertEqual(sum("조회 실패" in f and "RuntimeError" in f for f in fails), 3, fails)
        # 빈 응답(None 루트)은 '미매칭'으로 — 조문·별표 모두
        fails, _ = self._run(fact, {"고용보험법 시행규칙": None})
        self.assertFalse(any("조문 없음" in f or "별표 없음" in f for f in fails), fails)
        self.assertEqual(sum("현행판 미매칭" in f for f in fails), 3, fails)

    def test_u8_next_version_and_stored_cells_are_warnings(self):
        law, rule = ET.fromstring(self.LAW), ET.fromstring(self.RULE)
        roots = {"고용보험법": law, "고용보험법 시행규칙": rule}
        fact = self._fact([("ei_act_58", "현행 구절 ALPHA"), ("ei_rule_annex2", "본문 BETA")])
        nxt_law = ET.fromstring(self.LAW.replace("ALPHA", "OMEGA"))
        nxt_rule = ET.fromstring(self.RULE.replace("BETA", "DELTA"))
        fails, warns = self._run(fact, roots, stored={"ei_act_58": "옛 저장본", "ei_rule_annex2": "옛 별표 저장본"},
                                 nxt={"고용보험법": ("20270101", nxt_law), "고용보험법 시행규칙": ("20270101", nxt_rule)})
        self.assertEqual(fails, [], fails)
        self.assertTrue(any("제58조 앵커가 20270101부터 거짓" in w for w in warns), warns)
        self.assertTrue(any("별표(ei_rule_annex2) 앵커가 20270101부터 거짓" in w for w in warns), warns)
        self.assertTrue(any(w.startswith("ei_act_58: 저장본이 현행 본문과 다름") for w in warns), warns)
        self.assertTrue(any(w.startswith("ei_rule_annex2: 저장본이 현행 별표와 다름") for w in warns), warns)
        # 저장본 없음(별표) → 경고 · 다음 판본에 별표가 없으면 경고
        _, warns = self._run(self._fact([("ei_rule_annex2", "본문 BETA")]), roots,
                             nxt={"고용보험법 시행규칙": ("20270101", ET.fromstring("<법령/>"))})
        self.assertTrue(any("저장본 없음" in w for w in warns), warns)
        self.assertTrue(any("판본 별표 확인 불가" in w for w in warns), warns)


class StaleRuleConstraintTest(unittest.TestCase):
    """U9 — 별표 2 10호('8세 이하 또는 초등학교 2학년 이하')는 현행이다. 모성보호 폐기 기준이 이를 지우면 안 된다."""

    def test_u9_annex2_item10_quote_survives_stale_filter(self):
        from app.core.stale_rules import filter_stale_hits
        hit = {"source_type": "qa", "title": "q", "score": 1.0,
               "content": "별표 2 10호에 따라 8세 이하 또는 초등학교 2학년 이하의 자녀 육아로 휴직이 허용되지 않아 퇴사하면 "
                          "정당한 이직 사유에 해당할 수 있습니다. 만 8세 이하 자녀라고 표기한 상담도 같은 뜻입니다."}
        kept, _ = filter_stale_hits([hit])
        self.assertEqual(kept, [hit])


class CollectorTest(unittest.TestCase):
    """U11 — `fetch_official_rules.main`의 별표 단계(fetch mock)."""

    def _main(self, argv, annex_side_effect, tmp):
        import fetch_official_rules as fo
        env = {**os.environ, "LAW_API_KEY": "k"}
        with mock.patch.dict(os.environ, env), mock.patch.object(fo, "OUT_DIR", tmp), \
                mock.patch("dotenv.load_dotenv", return_value=True), \
                mock.patch.object(fo, "fetch_annex", side_effect=annex_side_effect) as fa, \
                mock.patch.object(fo, "fetch_article_xml") as fx, mock.patch.object(fo, "fetch_admrul") as fd:
            rc = fo.main(argv)
        return rc, fa, fx, fd

    def test_u11_doc_fetches_only_the_annex_and_stores_the_body_verbatim(self):
        import fetch_official_rules as fo
        raw = "■ 고용보험법 시행규칙 [별표 2]\n   1. 다음 각 목의    어느 하나에\n      해당하는 경     \n  우"
        with tempfile.TemporaryDirectory() as tmp:
            rc, fa, fx, fd = self._main(["--doc", "ei_rule_annex2", "--skip-url-check"],
                                        lambda key, law, title: {"body": raw, "date": "20260918", "annex_date": "20240701"}, tmp)
            self.assertEqual(rc, 0)
            self.assertEqual(fa.call_count, 1)
            fx.assert_not_called()
            fd.assert_not_called()
            text = Path(tmp, "ei_rule_annex2.md").read_text(encoding="utf-8")
            self.assertEqual(text.split("## 본문", 1)[1].strip(), raw.strip(), "별표내용 원문 그대로(D1)")
            self.assertIn("- keys: ", text)
            self.assertIn(fo.annex_url("고용보험법 시행규칙", "별표2"), text)
            self.assertIn("- source_type: law", text)

    def test_u11_duplicate_title_and_missing_annex_are_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, *_ = self._main(["--doc", "ei_rule_annex2", "--skip-url-check"],
                                lambda *a: (_ for _ in ()).throw(ValueError("둘")), tmp)
            self.assertEqual(rc, 1)
            self.assertFalse(Path(tmp, "ei_rule_annex2.md").exists())
            rc, *_ = self._main(["--doc", "ei_rule_annex1_2", "--skip-url-check"], lambda *a: None, tmp)
            self.assertEqual(rc, 1)


class ImportBoundaryTest(unittest.TestCase):
    """U12 — fail-open 경계: law_catalog는 rule_facts를 import하지 않고, separation_signals는 의존성이 없다."""

    @staticmethod
    def _imports(path: Path) -> set[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        out = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                out |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                out.add(node.module)
        return out

    def test_u12_import_boundary(self):
        catalog = self._imports(ROOT / "app" / "core" / "law_catalog.py")
        self.assertFalse(any("rule_facts" in m for m in catalog), catalog)
        signals = self._imports(ROOT / "app" / "core" / "separation_signals.py")
        self.assertEqual(signals, {"__future__", "re", "unicodedata", "app.core.colloquial_map"}, signals)
        colloquial = self._imports(ROOT / "app" / "core" / "colloquial_map.py")
        self.assertEqual(colloquial, {"__future__", "re", "unicodedata"}, colloquial)


if __name__ == "__main__":
    unittest.main()
