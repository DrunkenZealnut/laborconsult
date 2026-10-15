"""외부 점검 50문항 후속 회귀 테스트 (audit-50-legal-accuracy, API 키·네트워크 불요).

출발점: 2026-10-11 외부 점검(프로덕션 50문항, 평균 90.48). 오답 대부분은 LLM이 아니라 근거 전달 계층에서
났다 — 정답 지침이 있는데 질문 어휘가 패턴에 없어 안 붙었고(B), 붙은 지침이 틀리기 쉬운 지점을 말하지
않았고(A), 쟁점 그룹이 아예 없었고(C), 결정적 계산 카드가 산입 제외 수당이 섞인 총액으로 '충족'을 냈다(E).

T1~T6은 Design §8. 질문 원문·점검자 서술은 저장소에 없다 — fixture의 사실관계 요약과 우리 앱 원답변 문장,
자체 작성 정답 문장만 쓴다. Check(2026-10-12) 독립 리뷰가 찾은 반례 — 패턴 과대 매칭 10건, 예산 밀어내기, 월급 구성
가드의 기본급 오추출·포함 진술 오판·포괄임금 역산 재판정, 콜아웃 속 범위 문구 — 를 각 검사에 더했다.
"""
from __future__ import annotations

import json
import math
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "data/eval_audit50_queries.json"
# 이번 사이클에서 지침을 바꾸거나 새로 쓴 그룹 — anchors가 비어 있으면 안 된다(Design §4, C4로 질병 퇴사 추가)
ANCHORED_GROUPS = {
    "labor_civil_damage_and_response", "dismissal_scope", "ei_short_work_recognition",
    "contract_terms_discrepancy", "wage_due_vs_final_settlement", "premium_pay_conditions",
    "ei_health_resignation",
}


def _groups():
    from app.core.consultation_evidence import evidence_groups
    evidence_groups.cache_clear()
    return {g["id"]: g for g in evidence_groups()}


def _select(query):
    from app.core.consultation_evidence import select_evidence
    return select_evidence(query, as_of="2026-10-11")


class DetectorTest(unittest.TestCase):
    """T1 — 감지 규칙은 오류 문장에서 검출되고 정답 문장에서는 검출되지 않는다."""

    def test_t1_fixture_schema_and_detector_examples(self):
        import eval_consultation as ev
        cases = ev.load_cases(FIXTURE)
        self.assertEqual(len(cases), 14)
        self.assertEqual(ev.validate_cases(cases), [])
        checked = 0
        for case in cases:
            examples = case.detector_examples or {}
            if not examples:
                continue
            checked += 1

            def violations(text, case=case):
                return ([c for c in case.forbidden_claims if ev.claim_found(c, text)]
                        + ev.required_if_missing(case.required_if, text))
            for text in examples["positive"]:
                self.assertTrue(violations(text), f"{case.id} 감지 누락: {text[:60]}")
            for text in examples["negative"]:
                self.assertEqual(violations(text), [], f"{case.id} 정답 오검출: {text[:60]}")
        self.assertEqual(checked, 13)   # #36은 결정적 테스트(T5)로 검증한다

    def test_t1_gaps_stay_inside_one_sentence(self):
        """앞 문장에서 시작한 왼쪽 일치가 그 문장의 부정어에 지워지면 검출이 0이 된다(Design §7.3)."""
        import eval_consultation as ev
        claim = next(c for c in ev.load_cases(FIXTURE) if c.id == "a50-32").forbidden_claims[0]
        text = ("결근일을 차감하면서 고정 연차수당은 지급한 것으로 보이며 이는 공제 문제가 아니라 정산 문제입니다. "
                "결근한 달에는 연차휴가가 발생하지 않으므로 이러한 방식은 법적 체계에 맞지 않습니다.")
        self.assertTrue(ev.claim_found(claim, text))


class RequiredIfTest(unittest.TestCase):
    """T6 — required_if: 부정된 조건은 불성립, 인용 블록 안의 범위 문구는 불인정."""

    RULES = [{"when": r"re:제\s*19\s*조", "require": [r"re!:처음부터.{0,10}달랐"]}]

    def test_t6_condition_without_scope_is_flagged(self):
        import eval_consultation as ev
        self.assertEqual(ev.required_if_missing(self.RULES, "제19조에 따라 즉시 해제할 수 있습니다."),
                         [self.RULES[0]["when"]])

    def test_t6_negated_condition_is_not_a_condition(self):
        import eval_consultation as ev
        self.assertEqual(ev.required_if_missing(self.RULES, "이 사안에는 제19조가 적용되지 않습니다."), [])

    def test_t6_scope_inside_quote_block_does_not_count(self):
        import eval_consultation as ev
        quoted = "> 제19조 처음부터 조건이 달랐던 경우\n제19조에 따라 즉시 해제할 수 있습니다."
        self.assertTrue(ev.required_if_missing(self.RULES, quoted))
        body = quoted + "\n처음부터 조건이 달랐는지 확인하세요."
        self.assertEqual(ev.required_if_missing(self.RULES, body), [])

    def test_t6_callout_scope_counts_as_body(self):
        """답변 프롬프트는 적용 예외를 콜아웃(> ⚠️ **주의사항**)에 쓰라고 한다 — 그 문구를 버리면 정답이 위반이 된다."""
        import eval_consultation as ev
        answer = ("근로계약서와 실제가 다르면 제19조를 검토할 수 있습니다.\n\n"
                  "> ⚠️ **주의사항**: 제19조는 처음부터 조건이 달랐던 경우에 적용됩니다.")
        self.assertEqual(ev.required_if_missing(self.RULES, answer), [])

    def test_t6_condition_only_inside_a_quote_is_not_a_condition(self):
        """조문 인용 속 번호가 조건을 세우면 '해당하지 않는다'고 쓴 답이 위반이 된다."""
        import eval_consultation as ev
        answer = ("> 근로기준법 제19조 ① 명시된 근로조건이 사실과 다를 경우 …\n\n"
                  "이 사안은 임금 체불 문제라 해당 조문 사안이 아닙니다.")
        self.assertEqual(ev.required_if_missing(self.RULES, answer), [])

    def test_t6_violation_is_counted_with_forbidden_claims(self):
        import eval_consultation as ev
        case = next(c for c in ev.load_cases(FIXTURE) if c.id == "a50-03")
        result = ev.score_result(case, {"answer": "근로조건 위반이므로 즉시 해제할 수 있습니다.", "sources": []})
        self.assertTrue(any(item.startswith("required_if:") for item in result["forbidden_claims_found"]))
        self.assertFalse(result["automatic_pass"])


class CatalogAnchorTest(unittest.TestCase):
    """T2 — 지침의 법률 사실은 같은 그룹 source 원문에 있다(공백 무시 부분문자열)."""

    def test_t2_anchors_quote_their_own_group_sources(self):
        norm = lambda s: re.sub(r"\s+", "", s)  # noqa: E731
        groups = _groups()
        for gid in ANCHORED_GROUPS:
            self.assertTrue(groups[gid].get("anchors"), f"{gid} anchors 없음")
        for gid, group in groups.items():
            # 런타임은 anchors를 읽지 않아 형식 오류가 조용하다 — 철자가 틀린 키는 검증을 통째로 건너뛴다
            self.assertNotIn("anchor", group, f"{gid}: 'anchors' 오기")
            sources = {s["id"]: s for s in group.get("sources", [])}
            for anchor in group.get("anchors", []) or []:
                self.assertEqual(set(anchor), {"source", "quote"}, gid)
                # 빈 구절은 어떤 원문에도 부분문자열이라 대조가 무의미하다
                self.assertGreaterEqual(len(norm(anchor["quote"])), 4, f"{gid}: 앵커 구절이 비었거나 너무 짧음")
                self.assertIn(anchor["source"], sources, f"{gid}: 다른 그룹의 source를 앵커로 씀")
                self.assertIn(norm(anchor["quote"]), norm(sources[anchor["source"]]["content"]),
                              f"{gid}: 원문에 없는 구절 {anchor['quote'][:40]}")

    def test_t2_anchored_sources_survive_selection_checks(self):
        """앵커가 가리키는 source가 런타임 검증(_source_hit)에서 탈락하면 지침이 근거 없이 남는다."""
        from app.core.consultation_evidence import _source_hit
        for gid in ANCHORED_GROUPS:
            for source in _groups()[gid]["sources"]:
                self.assertIsNotNone(_source_hit(source, "2026-10-11"), f"{gid}: {source['id']} 탈락")


class ConclusionFirstTest(unittest.TestCase):
    """T9 — 틀리기 쉬운 지점의 금지는 지침·규칙 블록 맨 앞 '결론:'에 둔다(C49·C52).

    같은 금지가 본문 중간에 있을 때 재실측 오답이 났고(지침 세 쟁점 4/18, 주휴 블록 3/12) 맨 앞으로 옮긴 지침은
    0/18이 됐다(Act-5). 효과가 문구보다 위치에 달려 있어, 순서를 바꾸는 편집이 조용히 효과를 지우지 않게 고정한다.
    """

    def test_t9_conclusion_leads_the_guidance(self):
        groups = _groups()
        for gid in ("contract_terms_discrepancy", "wage_due_vs_final_settlement", "ei_health_resignation"):
            self.assertTrue(groups[gid]["guidance"].startswith("결론:"), gid)

    def test_t9_conclusion_leads_the_weekly_holiday_block(self):
        from app.core.rule_facts import build_rule_facts
        block = dict(build_rule_facts("주휴수당", None))["weekly_holiday"]
        first = block.splitlines()[1]  # 0번 줄은 공통 머리말
        self.assertTrue(first.startswith("- 결론:"), first[:40])
        # 오답 3회가 모두 요건 목록 칸이었다 — 금지가 본문만이 아니라 목록·표까지 덮어야 한다
        for phrase in ("소정근로시간", "실제 근로시간", "충족", "요건 목록·표"):
            self.assertIn(phrase, first)


class CatalogMatchTest(unittest.TestCase):
    """T3 — 패턴 양성·음성. 음성은 1차 시안에서 실제로 과대 매칭됐던 표현이다(Design §2.3)."""

    POSITIVE = {
        "dismissal_scope": ["알바 근로계약서까지 썼는데 일을 배우는 동안 자르셨어요. 돈을 안 준대요.",
                            "입사 이틀 만에 내일부터 나오지 말라는 말을 들었습니다.",
                            "사장님이 저를 자를 수 있나요?",
                            # '오늘'이 사건 시점이면 해고 질문이다 — 기간어는 지시 바로 앞에 붙을 때만 뺀다
                            "오늘 출근했더니 사장이 갑자기 내일부터 나오지 말래요.",
                            # 사물 명사가 흔한 낱말의 일부이거나 일터 이름이다 — 명사만 보던 Act-4 첫 판이 지웠다(리뷰 M1)
                            "회사에 임신 사실을 알렸더니 저를 잘랐어요.",
                            "회사에서 구조조정 대상자라며 저를 잘랐어요.",
                            "사장이 계속 나무라더니 결국 저를 잘랐어요.",
                            "알바하던 피자집에서 잘렸어요.",
                            "빵집에서 알바하다 잘렸어요.",
                            "회사가 일손이 남는다고 저를 잘랐어요.",
                            "회사에서 줄을 잘못 서서 잘렸어요.",
                            "회사에서 머리 염색했다고 잘렸어요.",
                            "손을 다쳐서 회사에서 잘렸어요.",
                            "회사(재단법인)에서 잘렸어요.",
                            "회사가 일손을 잘랐어요. 저도 그중 한 명이에요.",
                            "사장이 제 머리를 이유로 잘랐어요."],
        "ei_health_resignation": ["우울증과 공황장애로 응급실에 다녀온 뒤 일을 그만두었습니다. 실업급여를 받을 수 있나요?"],
        "ei_short_work_recognition": [
            "실업급여를 신청하려는데 11월에 단기 알바를 해달라고 부탁받아 8일 일할 예정입니다.",
            "실업급여 수급 기간에 쿠팡 파트너스 링크 공유로 수수료를 받으면 중단되나요?",
            "실업급여 받는 중인데 알바를 하게 되면 어떻게 되나요?"],
        "contract_terms_discrepancy": [
            "근로계약서와 다른 근로시간인데 10시에 출근하라고 합니다. 아르바이트입니다.",
            "임금지연 관련 당일퇴사 문의입니다. 급여를 나눠 주고 마지막 달 월급을 안 줍니다.",
            "근로기준법 제19조에 따라 근로조건이 다르면 즉시 퇴사할 수 있나요? 알바입니다.",
            "면접 때 들은 것과 다르게 주말에도 일을 시켜요. 회사를 그만두고 싶어요."],
        "wage_due_vs_final_settlement": ["교육을 받다가 그만두었는데 노동청에 신고하면 못 받은 돈을 받을 수 있나요?",
                                         "퇴사하고 14일이 지났는데 월급을 못 받았어요.",
                                         # 해고 어미(잘랐·자르셨 등)가 퇴사 요건을 채운다 — 설계 시점의 `잘(?:렸|린)|자르`와 다르다(C24)
                                         "알바 사장님이 갑자기 잘랐는데 마지막 달 월급을 못 받았어요. 노동청에 신고하면 받을 수 있나요?"],
        "premium_pay_conditions": ["알바 마지막 주에 대타로 일요일에도 일하게 됐는데 주휴수당은 받을 수 있나요?",
                                   "주휴일인 일요일에 8시간을 더 일했는데 휴일근로수당을 받을 수 있나요?"],
    }
    NEGATIVE = {
        "ei_short_work_recognition": [
            # 과거 생활비 서술 — 수급 중 근로가 아니다
            "우울증으로 그만두고 알바하면서 모아둔 돈으로 버티고 있습니다. 실업급여 상담을 받았습니다.",
            # 이미 시작한 근로('하게 됐는데')는 예정된 근로가 아니다 — 수급 자격 질문이다
            "편의점 알바를 하게 됐는데 3개월 만에 사장이 그만두래요. 실업급여 받을 수 있나요?"],
        # 계약서 위조 질문 속 수당 언급 — 가산 청구가 아니다
        "premium_pay_conditions": ["퇴사 후 진정하니 계약서에 다른 필체로 연장근로수당 내용이 적혀 있었습니다. 고소 가능할까요?"],
        # 해고 아닌 '자르다'·'나오지 마'(Check 실측 과대 매칭)
        "dismissal_scope": ["미용실에서 머리를 자르는 일을 배우고 있는데 시급이 최저임금보다 낮습니다.",
                            "가게에서 칼로 재료를 자를 수 있는 사람이 저밖에 없어서 연장근무를 했는데 수당을 받을 수 있나요?",
                            "회사에서 원단을 잘라서 포장하는 일을 하는데 주휴수당이 나오나요?",
                            "사장님이 오늘은 나오지 말래요. 휴업수당을 받을 수 있나요?",
                            "알바하다가 손가락이 잘렸어요. 산재 신청이 되나요?",
                            # 목록 밖 사물(Design §13.5 R3 → Act-4)
                            "가게에서 박스를 잘라서 포장하는 일을 하는데 주휴수당이 나오나요?",
                            "식당 알바인데 사장님이 양파를 잘라 놓으라고 하셨어요. 시급이 최저임금보다 낮아요.",
                            "회사에서 테이프를 자르는 일만 하는데 연장수당을 받을 수 있나요?",
                            "가게에서 빵을 잘라서 진열하는 일인데 주휴수당이 나오나요?",
                            "치킨집 알바인데 사장님이 통닭을 잘라서 포장하래요. 시급이 최저임금보다 낮아요.",
                            "점장님이 빵을 반으로 잘라서 진열하래요. 시급이 최저임금보다 낮아요.",
                            "가게 사장님이 양파를 얇게 잘라서 담으래요. 주휴수당이 나오나요?",
                            "사장이 제 월급 잘랐어요. 신고할 수 있나요?",
                            # 돈·시간을 자르는 것은 임금·근로시간 삭감이다
                            "사장이 제 월급을 잘랐어요. 신고할 수 있나요?",
                            "회사에서 근무시간을 잘라서 월급이 줄었어요. 휴업수당을 받을 수 있나요?"],
        # 다른 법률의 제19조, '다 좋은데', '처음에 말씀드린 것처럼 다른'
        "contract_terms_discrepancy": [
            "남녀고용평등법 제19조에 따라 육아휴직을 쓰려는데 회사가 거부합니다. 급여는 어떻게 되나요?",
            "제19조의2에 따라 육아기 근로시간 단축을 신청했는데 회사가 월급을 깎았어요.",
            "근로조건이 다 좋은데 회사가 멀어서 고민입니다. 퇴사하면 실업급여를 받을 수 있나요?",
            "처음에 말씀드린 것처럼 다른 회사로 옮기려는데 퇴사하면 월급은 언제 받나요?"],
        # 날짜 속 14일
        "wage_due_vs_final_settlement": ["3월 14일에 퇴사했는데 퇴직금은 언제 받을 수 있나요?"],
    }

    def test_t3_positive(self):
        for gid, queries in self.POSITIVE.items():
            for query in queries:
                self.assertIn(gid, _select(query).groups, f"{gid} 미발동: {query[:40]}")

    def test_t3_negative(self):
        for gid, queries in self.NEGATIVE.items():
            for query in queries:
                self.assertNotIn(gid, _select(query).groups, f"{gid} 과대 매칭: {query[:40]}")

    def test_t3_fixture_questions_reach_their_groups(self):
        """요약 질문도 원문과 같은 그룹에 닿아야 오프라인 fixture가 B 수정을 검증한다(Design §7.2)."""
        expected = {"a50-03": {"contract_terms_discrepancy"}, "a50-04": {"dismissal_scope"},
                    "a50-14": {"ei_health_resignation"}, "a50-18": {"ei_short_work_recognition"},
                    "a50-23": {"ei_short_work_recognition"}, "a50-30": {"labor_civil_damage_and_response"},
                    "a50-31": {"contract_terms_discrepancy"}, "a50-32": {"premium_pay_conditions"},
                    "a50-34": {"wage_due_vs_final_settlement"},
                    "a50-37": {"labor_civil_damage_and_response", "wage_due_vs_final_settlement"},
                    "a50-49": {"premium_pay_conditions"}}
        cases = {c["id"]: c for c in json.loads(FIXTURE.read_text(encoding="utf-8"))}
        for case_id, gids in expected.items():
            self.assertLessEqual(gids, set(_select(cases[case_id]["question"]).groups), case_id)


class CatalogBudgetTest(unittest.TestCase):
    """T4 — 다쟁점 질문에서도 그룹이 생략되지 않는다(합계 상한 초과 시 통째로 생략)."""

    def test_t4_largest_combination_is_not_omitted(self):
        query = ("알바에서 당일 해고를 당했는데 27분 수당을 안 준다고 합니다. 노동청에 신고하면 실수한 것에 대한 "
                 "손해배상으로 역고소당할까 걱정됩니다. 임금체불로 신고 가능한가요?")
        sel = _select(query)
        self.assertEqual(set(sel.groups), {"labor_civil_damage_and_response", "dismissal_scope",
                                           "wage_due_vs_final_settlement"})
        self.assertEqual(sel.omitted, [])

    def test_t4_every_three_group_combination_fits(self):
        """그룹 3개의 모든 조합이 생략 없이 들어간다. 실측 질문의 최대 조합만 고정하면, 커진 지침이 다른 조합에서
        기존 그룹을 밀어내도 모른다(Check 실측: 손해배상+재직자 대지급금+해고 → 해고 지침 생략)."""
        import itertools
        from app.core.consultation_evidence import select_evidence
        forced = [dict(g, patterns=["."], all_patterns=[], exclude_patterns=[]) for g in _groups().values()]
        for combo in itertools.combinations(forced, 3):
            sel = select_evidence("x", as_of="2026-10-11", groups=combo)
            self.assertEqual(sel.omitted, [], [g["id"] for g in combo])

    def test_t4_table_padding_is_not_delivered(self):
        """별표 원문 사본의 정렬 공백은 전달하지 않는다 — 보관본은 그대로다(앵커는 공백 무시 대조)."""
        group = _groups()["premium_pay_conditions"]
        annex = next(s for s in group["sources"] if s["id"] == "lsa_enf_annex1")
        self.assertIn("    ", annex["content"])
        text = _select("주휴일인 일요일에 8시간을 더 일했는데 휴일근로수당을 받을 수 있나요?").text
        self.assertNotIn("  ", text)
        self.assertIn("제54조, 제55조제1항, 제63조", text)


class WageCompositionTest(unittest.TestCase):
    """T5 — 월급 총액에 비산입 수당이 포함됐다고 밝힌 질문에서 카드가 '✅ 충족'을 내지 않는다(Design §5)."""

    Q36 = ("카페에서 주 5일 월급제로 일합니다. 세전 월급은 270만 원이고, 기본급 2,096,270원에 연장·야간·휴일근로수당과 "
           "연차수당이 포함되어 있습니다. 2026년 최저임금 위반인가요? 주 40시간, 5인 미만 사업장입니다.")
    PARAMS = {"needs_calculation": True, "wage_type": "월급", "wage_amount": 2700000, "business_size": "5인미만",
              "weekly_total_hours": 40, "weekly_work_days": 5, "reference_year": 2026,
              "calculation_types_kr": ["최저임금"]}

    def test_t5_statement_parsing(self):
        from app.core.pipeline import _stated_wage_composition
        self.assertEqual(_stated_wage_composition(self.Q36), (True, 2096270))
        # 연장수당을 따로 묻는 질문은 포함 진술이 아니다
        self.assertEqual(_stated_wage_composition("이번 주 주휴수당과 연장근로수당을 각각 계산해 주세요."), (False, None))
        self.assertEqual(_stated_wage_composition("월급 250만원인데 연차수당이 포함돼 있다고 합니다.")[0], True)

    def test_t5_base_pay_is_compared_with_minimum_wage(self):
        from app.core.pipeline import _run_calculator
        out = _run_calculator(dict(self.PARAMS), self.Q36)
        self.assertNotIn("✅ 충족", out)
        self.assertIn("최저임금 충족: ❌ 미달", out)
        self.assertIn("기본급 2,096,270원으로", out)

    def test_t5_base_already_extracted_is_judged_not_held(self):
        """의도분석이 기본급을 임금으로 뽑았으면 그대로 판정한다 — 보류하면 맞는 '❌ 미달'이 지워진다."""
        from app.core.pipeline import _run_calculator
        out = _run_calculator(dict(self.PARAMS, wage_amount=2096270), self.Q36)
        self.assertIn("최저임금 충족: ❌ 미달", out)
        self.assertNotIn("판정 보류", out)
        # 카드의 월 총액은 사용자가 말한 270만 원이다 — 질문의 총액(만원 표기)을 읽는다(Act-3). 예전에는 못 읽어 기본급이
        # 총액처럼 보이지 않게 줄을 숨겼다(조치 후 재실측 2회 모두 이 경로)
        self.assertIn("월 총 예상 수령액(세전): 2,700,000원", out)

    def test_t5_extracted_base_with_total_pay_targets_uses_the_stated_total(self):
        """기본급이 임금으로 뽑혔어도 질문에 총액이 적혀 있으면 퇴직금은 그 총액으로 낸 평균임금 기준이다(Act-3 R7). 총액을
        못 읽으면 평균임금이 수당 없이 계산됐다는 사실을 알린다."""
        from app.core.pipeline import _run_calculator
        params = dict(self.PARAMS, wage_amount=2096270, calculation_types_kr=["최저임금", "퇴직금"],
                      start_date="2025-03-01", end_date="2026-10-01")
        out = _run_calculator(params, self.Q36)
        self.assertIn("최저임금 충족: ❌ 미달", out)
        self.assertIn("  퇴직금: 4,189,905원", out)
        self.assertIn("수당을 포함한 월급 2,700,000원 기준입니다", out)
        self.assertNotIn("실제보다 적게", out)
        no_total = self.Q36.replace("세전 월급은 270만 원이고, ", "")
        out = _run_calculator(params, no_total)
        self.assertIn("최저임금 충족: ❌ 미달", out)
        self.assertIn("실제보다 적게 나왔을 수 있습니다", out)
        self.assertNotIn("월 총 예상 수령액", out)

    def test_t5_stated_base_with_total_basis_targets_is_judged(self):
        """4대보험처럼 총액이 맞는 기준인 계산이 함께 와도 기본급으로 판정한다 — 보수월액은 총액으로 따로 계산한다
        (`monthly_total_pay`, Act-3 R7). 예전에는 이 조합이 판정 보류였다."""
        from app.core.pipeline import _run_calculator
        out = _run_calculator(dict(self.PARAMS, calculation_types_kr=["최저임금", "4대보험"]), self.Q36)
        self.assertIn("최저임금 충족: ❌ 미달", out)
        self.assertIn("세전 월 급여: 2,700,000원 (월 임금총액 기준)", out)
        self.assertNotIn("판정 보류", out)

    def test_t5_stated_base_with_average_wage_targets_is_judged(self):
        """기본급이 적혀 있으면 퇴직금을 함께 물어도 기본급으로 판정한다 — 퇴직금 때문에 보류로 가면 Act-2가 퇴직금 금액도
        빼서 맞는 '미달'과 금액이 모두 사라졌다(Act-2 코드 리뷰 M1). 의도분석이 기본급을 뽑은 C8 경로와 같은 카드다."""
        from app.core.pipeline import _run_calculator
        params = dict(self.PARAMS, calculation_types_kr=["최저임금", "퇴직금"],
                      start_date="2025-03-01", end_date="2026-10-01")
        for amount in (2700000, 2096270):
            with self.subTest(amount=amount):
                out = _run_calculator(dict(params, wage_amount=amount), self.Q36)
                self.assertIn("최저임금 충족: ❌ 미달", out)
                self.assertIn("부족분(월): 56,187원", out)
                # 평균임금은 총액(270만 원 × 3 ÷ 92 = 88,043원/일), 통상임금 하한은 기본급(80,394원/일) — Act-3 R7.
                # Act-2에서는 평균임금도 기본급 기준이라 3,825,873원(과소 안내)이었다
                self.assertIn("  퇴직금: 4,189,905원", out)
                self.assertNotIn("실제보다 적게", out)
                self.assertNotIn("금액 보류:", out)

    def test_t5_without_statement_nothing_changes(self):
        from app.core.pipeline import _run_calculator
        out = _run_calculator(dict(self.PARAMS), "월급 270만 원, 주 40시간인데 최저임금 위반인가요?")
        self.assertIn("최저임금 충족: ✅ 충족", out)

    def test_t5_card_total_is_the_stated_total(self):
        """기본급으로 계산해도 카드의 '월 총 예상 수령액'은 사용자가 말한 총액이다."""
        from app.core.pipeline import _run_calculator
        self.assertIn("월 총 예상 수령액(세전): 2,700,000원", _run_calculator(dict(self.PARAMS), self.Q36))

    def test_t5_rounded_base_from_analysis_is_judged(self):
        """의도분석이 기본급을 천 원 단위로 반올림해 뽑아도 같은 기본급으로 본다."""
        from app.core.pipeline import _run_calculator
        out = _run_calculator(dict(self.PARAMS, wage_amount=2096000), self.Q36)
        self.assertIn("최저임금 충족: ❌ 미달", out)
        # 반올림 금액을 월급으로 쓰면 '월급 2,096,000원에 … 포함'이라는 없는 진술이 된다 — 질문의 총액을 쓴다
        self.assertIn("월급 2,700,000원에", out)
        self.assertIn("기본급 2,096,270원으로", out)
        self.assertNotIn("월급 2,096,000원에", out)
        # 안내가 말하는 기본급으로 실제 계산도 해야 한다 — 반올림된 값으로 계산하면 안내(2,096,270원)와 어긋난다(Act-1 C22)
        self.assertIn("실질시급: 2,096,270원 ÷ 208.5714h", out)
        self.assertIn("월 56,187원", out)
        self.assertNotIn("2,096,000", out)
        # 질문에 총액이 없어도 천 원 단위 반올림은 같은 기본급으로 본다(C8)
        out = _run_calculator(dict(self.PARAMS, wage_amount=2096000), self.Q36.replace("세전 월급은 270만 원이고, ", ""))
        self.assertIn("최저임금 충족: ❌ 미달", out)
        self.assertIn("기본급 2,096,270원 기준으로", out)

    def test_t5_priced_other_pay_is_counted_in_minimum_wage(self):
        """총액에 산입 대상 수당(식대·직책수당)이 섞여 있으면 기본급만으로 계산하면 없는 '미달'과 '노동청 신고 가능'이
        나왔다(Check 실측). 금액이 모두 적혀 있으면 고정수당으로 넣어 산입해 판정한다(Act-3 R8 — 2,300,000원 ÷ 208.5714h =
        11,027원). 금액이 없거나 성격이 갈리는 수당·별도 지급·금액이 둘이면 여전히 보류한다."""
        from app.core.pipeline import _run_calculator
        params = dict(self.PARAMS, wage_amount=2600000, business_size="5인이상")
        q = ("월급 2,600,000원(기본급 2,000,000원, 식대 200,000원, 직책수당 100,000원, 고정연장수당 300,000원 포함)입니다. "
             "최저임금 위반인가요? 주 40시간입니다.")
        out = _run_calculator(dict(params), q)
        self.assertIn("최저임금 충족: ✅ 충족", out)
        self.assertIn("통상시급: 11,027원", out)
        self.assertIn("기본급 2,000,000원과 식대 200,000원·직책수당 100,000원으로", out)
        self.assertNotIn("❌ 미달", out)
        held = {
            "금액 없음": "월급 2,600,000원(기본급 2,000,000원, 식대와 고정연장수당 포함)입니다. 최저임금 위반인가요?",
            "상여금": ("월급 2,600,000원(기본급 2,000,000원, 식대 200,000원, 상여금 100,000원, 고정연장수당 300,000원 포함)"
                    "입니다. 최저임금 위반인가요?"),
            "별도 지급": "월급 2,600,000원(기본급 2,000,000원, 고정연장수당 포함)이고 식대 200,000원은 별도입니다. 최저임금 위반인가요?",
            "금액 둘": ("월급 2,600,000원(기본급 2,000,000원, 식대 200,000원, 고정연장수당 포함)입니다. 식대 150,000원이 맞는지 "
                     "모르겠어요. 최저임금 위반인가요?"),
            # 기본급 + 수당이 총액보다 크면 진술이 어긋난다
            "합계 초과": "월급 2,100,000원(기본급 2,000,000원, 식대 200,000원, 연장수당 포함)입니다. 최저임금 위반인가요?",
        }
        for name, query in held.items():
            with self.subTest(name):
                out = _run_calculator(dict(params), query)
                self.assertIn("최저임금 충족: ⏸ 판정 보류", out)
                self.assertNotIn("❌ 미달", out)

    def test_t5_base_pay_mentions_that_are_not_the_base(self):
        """인상액·작년 값·서로 다른 두 금액은 기본급으로 쓰지 않는다. 총액의 절반도 안 되는 값(시급)도 쓰지 않는다."""
        from app.core.pipeline import _run_calculator, _stated_wage_composition
        cases = {
            "월급 270만 원(연장·야간수당 포함)인데 올해 기본급이 50,000원 올랐습니다.": None,
            "작년 기본급은 1,900,000원이었고 올해 기본급은 2,200,000원입니다. 월급 2,700,000원에 연장수당이 포함되어 있습니다.": 2200000,
            "기본급 2,000,000원이라고 했다가 기본급 2,100,000원이라고 합니다. 연장수당이 포함되어 있습니다.": None,
        }
        for query, base in cases.items():
            self.assertEqual(_stated_wage_composition(query)[1], base, query[:30])
        out = _run_calculator(dict(self.PARAMS, wage_amount=2700000),
                              "월급 2,700,000원에 연장수당이 포함돼 있고 기본급 10,320원 기준으로 계산한다고 합니다.")
        self.assertIn("최저임금 충족: ⏸ 판정 보류", out)

    def test_t5_statements_that_are_not_inclusion(self):
        """부정·의문·계산 지시·다른 항목의 '포함'은 포함 진술이 아니다 — 진술을 뒤집어 맞는 '미달'을 보류로 바꿨다."""
        from app.core.pipeline import _run_calculator, _stated_wage_composition
        for query in ("월급 200만원이고 연장수당은 포함되어 있지 않습니다.",
                      "월급 200만원(연장수당 별도, 포함 안 됨)입니다.",
                      "월급 200만원(식대 포함)이고 연장수당은 따로 받습니다.",
                      "월급 200만원에 연장수당은 없고 식대가 포함되어 있습니다.",
                      "월급 200만원에 연장수당을 포함해서 계산해 주세요.",
                      "월급 200만원인데 연차수당도 포함되나요?",
                      "월급 200만원에 유급휴일수당이 포함되어 있습니다."):
            self.assertFalse(_stated_wage_composition(query)[0], query)
        out = _run_calculator(dict(self.PARAMS, wage_amount=2000000, business_size="5인이상"),
                              "월급 200만원(연장수당 별도, 포함 안 됨), 주 40시간입니다. 최저임금 위반인가요?")
        self.assertIn("최저임금 충족: ❌ 미달", out)

    def test_t5_comprehensive_reverse_calculation_does_not_refill_a_held_verdict(self):
        """보류해도 포괄임금 역산이 같은 총액으로 '충족'을 다시 채웠다(Check 실측). 비산입 수당은 시급을 부풀리기만
        하므로 '미달'은 그대로 둔다."""
        from app.core.pipeline import _run_calculator
        query = "포괄임금제로 월 {}원 받습니다. 연장·야간수당이 포함되어 있습니다. 주 40시간입니다."
        params = dict(self.PARAMS, wage_type="포괄임금제", calculation_types_kr=["포괄임금제"], business_size="5인이상")
        held = _run_calculator(dict(params, wage_amount=2700000), query.format("2,700,000"))
        self.assertIn("포괄임금 역산 시급", held)
        self.assertNotIn("충족: ✅", held)
        self.assertIn("최저임금 충족: ⏸ 판정 보류", held)
        short = _run_calculator(dict(params, wage_amount=2000000), query.format("2,000,000"))
        self.assertIn("최저임금 충족: ❌ 미달", short)
        self.assertIn("총액으로 계산해도 최저임금에 미달", short)

    def test_t5_stated_total_pay_parsing(self):
        """질문의 월급 총액 — 만원 표기를 읽고, 기본급보다 큰 값이 하나로 정해질 때만 쓴다(Act-3 R7)."""
        from app.core.pipeline import _stated_total_pay
        cases = {
            ("세전 월급은 270만 원이고, 기본급 2,096,270원에 연장수당이 포함되어 있습니다.", 2096270): 2700000,
            ("월급 2,600,000원(기본급 2,000,000원, 식대 200,000원 포함)", 2000000): 2600000,
            ("급여는 300만원이고 기본급은 200만원입니다.", 2000000): 3000000,
            ("작년 월급은 250만 원이었고 올해 월급은 270만 원입니다.", 2000000): 2700000,     # 과거 값은 뺀다
            ("월급이 20만원 올랐습니다.", 100000): None,                                    # 변동분
            ("식대 월 20만원이 따로 나옵니다.", 100000): None,                               # 키워드 없는 '월 N원'
            ("실업급여 150만원을 받을 수 있나요?", 1000000): None,                            # 합성어
            ("월급 270만 원이라고 했다가 월급 280만 원이라고 합니다.", 2000000): None,          # 값이 둘
            ("월급 200만 원에 연장수당이 포함되어 있습니다.", 2000000): None,                  # 기본급보다 크지 않다
            # Act-3 리뷰 M1 — 세전 월급 총액이 아닌 금액
            ("세후 월급은 240만 원입니다.", 2000000): None,
            ("실수령 월급 230만원 정도예요.", 2000000): None,
            ("월급 270만원(세후)입니다.", 2000000): None,
            ("연 급여 3,240만 원입니다.", 2000000): None,
            ("2026년 최저 월급이 2,156,880원이라던데요.", 2000000): None,
            ("월급이 250만 원에서 270만 원으로 올랐어요.", 2000000): None,
            ("전 직장 월급은 300만원이었어요.", 2000000): None,
            ("육아휴직 급여 300만원을 받았어요.", 2000000): None,
            ("산재 휴업급여 300만원을 받았어요.", 2000000): None,                          # 합성어(문맥 목록 밖)
            ("세전 월급 270만원이고 세후 월급은 240만원", 2000000): 2700000,
            ("월급(세전) 270만원", 2000000): 2700000,
            ("급여 총액 270만원", 2000000): 2700000,
        }
        for (text, base), expected in cases.items():
            with self.subTest(text[:20]):
                self.assertEqual(_stated_total_pay(text, base), expected)

    def test_t5_stated_other_pay_parsing(self):
        """금액이 적힌 고정수당만 계산에 넣고, 하나라도 판단할 수 없으면 기본급 판정을 미룬다(Act-3 R8)."""
        from app.core.pipeline import _stated_other_pay
        cases = {
            "기본급 2,000,000원, 식대 200,000원, 직책수당 100,000원, 고정연장수당 300,000원 포함": ({"식대": 200000, "직책수당": 100000}, False),
            "식대 20만 원과 고정연장수당이 포함되어 있습니다": ({"식대": 200000}, False),
            "연장수당과 연차수당이 포함되어 있습니다": ({}, False),
            "식대와 고정연장수당이 포함되어 있습니다": ({}, True),          # 금액 없음
            "상여금 100,000원, 연장수당 포함": ({}, True),                  # 성격이 갈리는 수당
            "가족수당 50,000원, 연장수당 포함": ({}, True),
            "주휴수당 300,000원, 연장수당 포함": ({"주휴수당": 300000}, False),   # 목록 밖 이름도 금액이 있으면 넣는다(리뷰 H1)
            "연장수당 포함이고 식대 200,000원은 별도입니다": ({}, True),      # 총액 밖
            "식대 200,000원 포함인데 식대 150,000원이라는 말도 있어요": ({}, True),  # 금액이 둘
            # Act-3 리뷰 H1·H2 — 목록 밖 이름, 이름 전체, 변동, 유급휴일
            "팀장수당 200,000원, 연장수당 포함": ({"팀장수당": 200000}, False),
            "연장수당과 팀장수당이 포함되어 있습니다": ({}, True),
            "중식비 100,000원, 석식비 100,000원, 연장수당 포함": ({"중식비": 100000, "석식비": 100000}, False),
            "위험수당 100,000원, 특수위험수당 100,000원, 연장수당 포함": ({"위험수당": 100000, "특수위험수당": 100000}, False),
            "직책수당이 10만원에서 20만원으로 올랐고 연장수당 포함": ({}, True),
            "유급휴일수당 361,200원, 연장수당 포함": ({}, True),            # 주휴일이 아니면 비산입 — 이름만으로 못 가른다
            "식대 20만, 연장수당 포함": ({"식대": 200000}, False),         # '원' 생략
            "기본급 2,000,000원에 연장수당 포함입니다. 식대 20만원도 받아요.": ({"식대": 200000}, False),  # 다른 문장의 금액
            "기본급 2,000,000원에 연장수당 포함입니다. 주휴수당도 받을 수 있나요?": ({}, False),  # 질문 문장
            # Act-4 — 금액이 이름 앞('의·짜리'로 이어질 때만)
            "기본급 2,000,000원에 200,000원의 식대와 연장수당이 포함되어 있습니다": ({"식대": 200000}, False),
            "기본급 2,000,000원 식대 포함, 연장수당 포함": ({}, True),       # 앞 금액은 기본급 것이다
        }
        for text, expected in cases.items():
            with self.subTest(text[:20]):
                self.assertEqual(_stated_other_pay(text), expected)

    def test_t5_amount_extraction_does_not_change_the_dual_basis_card(self):
        """기본급·총액을 질문에서 읽으면 의도분석이 총액·기본급·천 원 반올림·만 원 반올림 중 무엇을 뽑았든 같은 카드다 —
        통상임금·최저임금은 기본급, 평균임금·4대보험 보수는 총액(Act-3 R7). Act-2까지는 기본급을 뽑으면 퇴직금이
        과소(기본급 기준)였고 총액을 뽑고 4대보험을 물으면 판정 보류였다."""
        from app.core.pipeline import _run_calculator
        params = dict(self.PARAMS, calculation_types_kr=["최저임금", "퇴직금", "4대보험"],
                      start_date="2025-03-01", end_date="2026-10-01")
        outs = [_run_calculator(dict(params, wage_amount=amount), self.Q36)
                for amount in (2700000, 2096270, 2096000, 2090000)]
        self.assertEqual(len(set(outs)), 1)
        out = outs[0]
        for line in ("통상시급: 10,051원", "최저임금 충족: ❌ 미달", "부족분(월): 56,187원", "  퇴직금: 4,189,905원",
                     "세전 월 급여: 2,700,000원 (월 임금총액 기준)", "월 총 예상 수령액(세전): 2,700,000원",
                     "3개월 평균임금: 88,043원/일", "1년 평균임금:   88,767원/일", "적용 기준:      3개월 (88,043원/일)"):
            self.assertIn(line, out)

    def test_t5_analyzer_overtime_allowance_is_not_ordinary_wage(self):
        """의도분석이 고정연장수당을 고정수당으로 뽑아도 통상임금·최저임금 산입에 넣지 않는다 — 조건 '없음' 고정수당은 통상임금으로
        자동 판정되어 총액의 비산입 나머지가 통상시급을 부풀렸다(Act-3)."""
        from app.core.pipeline import _run_calculator
        out = _run_calculator(dict(self.PARAMS, fixed_allowances=[{"name": "고정연장수당", "amount": 603730, "condition": "없음"}]),
                              self.Q36)
        self.assertIn("통상시급: 10,051원", out)
        self.assertIn("최저임금 충족: ❌ 미달", out)

    def test_t5_monthly_total_pay_feeds_every_total_basis_calculator(self):
        """`monthly_total_pay`(월 임금총액)를 주면 총액 기준 계산(4대보험·사업주 부담·실업급여·근로장려금·일할계산·DC형 퇴직연금·
        평균임금 3개월 총액·산재 평균임금 추정)은 '월급 = 총액'일 때와 같고, 통상임금 기준 계산(연장·주휴·연차·해고예고)은
        '월급 = 기본급'일 때와 같다 — 한 입력 안에서 두 기준이 갈린다(Act-3 R7)."""
        import copy
        from wage_calculator.calculators.ordinary_wage import calc_ordinary_wage
        from wage_calculator.facade.registry import _STANDARD_CALCS
        from wage_calculator.models import BusinessSize, WageInput, WageType, WorkSchedule
        from wage_calculator.result import WageResult
        common = dict(wage_type=WageType.MONTHLY, business_size=BusinessSize.OVER_5, reference_year=2026,
                      schedule=WorkSchedule(daily_work_hours=8, weekly_work_days=5, weekly_overtime_hours=5),
                      start_date="2023-03-01", end_date="2026-10-01", join_date="2026-09-10", pension_type="DC")
        dual = WageInput(monthly_wage=2096270, monthly_total_pay=2700000, **copy.deepcopy(common))
        # '월급 = 총액'은 임금 구성이 정해진 입력이다 — 구성을 모르면 월급이 소정근로의 대가라 보고 연장수당을 따로 더한다
        # (calc-card-followups D4·F6). 그 경로는 test_calc_card_followups가 본다
        total_only = WageInput(monthly_wage=2700000, wage_composition_known=True, **copy.deepcopy(common))
        base_only = WageInput(monthly_wage=2096270, **copy.deepcopy(common))
        calcs = {key: (func, populate) for key, func, _, populate, _ in _STANDARD_CALCS}

        def summary(key, inp):
            func, populate = calcs[key]
            inp = copy.deepcopy(inp)
            result = WageResult()
            populate(func(inp, calc_ordinary_wage(inp)), result)
            return result.summary
        for key in ("insurance", "employer_insurance", "unemployment", "eitc", "prorated"):
            with self.subTest(total_basis=key):
                self.assertEqual(summary(key, dual), summary(key, total_only))
        # 2026년은 구직급여 하한액(66,048원)이 상한액보다 커서 일액이 임금과 무관하다 — 평균임금 추정식으로 본다
        from wage_calculator.calculators.unemployment import calc_unemployment
        unemployment = calc_unemployment(copy.deepcopy(dual), calc_ordinary_wage(copy.deepcopy(dual)))
        self.assertTrue(any("(2,700,000원 × 3) ÷ 92일" in f for f in unemployment.formulas), unemployment.formulas)
        for key in ("overtime", "weekly_holiday", "annual_leave", "dismissal"):
            with self.subTest(ordinary_basis=key):
                self.assertEqual(summary(key, dual), summary(key, base_only))
        self.assertEqual(summary("average_wage", dual)["3개월 임금총액"], summary("average_wage", total_only)["3개월 임금총액"])
        from wage_calculator.calculators.retirement_pension import calc_retirement_pension
        pension = lambda inp: calc_retirement_pension(copy.deepcopy(inp), calc_ordinary_wage(copy.deepcopy(inp)), None)
        self.assertEqual(pension(dual).total_pension, pension(total_only).total_pension)
        from wage_calculator.calculators.industrial_accident import calc_industrial_accident
        accident = calc_industrial_accident(copy.deepcopy(dual), calc_ordinary_wage(copy.deepcopy(dual)))
        self.assertIn("평균임금(추정): 2,700,000원 ÷ 30일 = 90,000원/일", accident.formulas)
        # 근로장려금은 소득이 한도를 넘으면 두 기준 모두 0원이라 요약만으로는 못 가른다 — 소득 추정 안내로 본다
        from wage_calculator.calculators.eitc import calc_eitc
        eitc = calc_eitc(copy.deepcopy(dual), calc_ordinary_wage(copy.deepcopy(dual)))
        self.assertTrue(any("월 임금총액 2,700,000원 x 12 = 32,400,000원" in w for w in eitc.warnings), eitc.warnings)

    def test_t5_exact_path_review_regressions(self):
        """Act-3 델타 리뷰 재현 — 목록 밖 산입 수당을 버려 없는 '미달'(H1), 의도분석 고정수당을 검증 없이 산입해 없는 '충족'
        (H3), 세후 금액·합산 금액을 총액으로 단정(M1·M2)."""
        from app.core.pipeline import _run_calculator
        base = dict(self.PARAMS, business_size="5인이상", calculation_types_kr=["최저임금"])
        team = "월급 2,700,000원(기본급 2,096,270원, 팀장수당 200,000원, 연장·야간수당 포함)입니다. 최저임금 위반인가요?"
        out = _run_calculator(dict(base), team)
        self.assertIn("최저임금 충족: ✅ 충족", out)                 # 2,296,270원 ÷ 208.5714h = 11,010원
        self.assertIn("기본급 2,096,270원과 팀장수당 200,000원으로", out)
        held = {
            "금액 없는 목록 밖 수당": "월급 2,700,000원(기본급 2,096,270원, 연장수당과 팀장수당 포함)입니다. 최저임금 위반인가요?",
            "유급휴일수당": "월급 2,700,000원(기본급 1,795,680원, 유급휴일수당 361,200원, 연장·야간수당 포함)입니다. 최저임금 위반인가요?",
        }
        for name, query in held.items():
            with self.subTest(name):
                self.assertIn("최저임금 충족: ⏸ 판정 보류", _run_calculator(dict(base), query))
        # H3 — 의도분석 고정수당은 정확 경로에서 쓰지 않는다(질문에 없는 식대, 다른 이름의 같은 수당, 비산입 이름)
        meal = "월급 2,700,000원(기본급 1,950,000원, 중식비 200,000원, 연장수당 포함)입니다. 최저임금 위반인가요?"
        for name, allowances in {"질문에 없는 식대": [{"name": "식대", "amount": 200000, "condition": "없음"}],
                                 "같은 수당 다른 이름": [{"name": "식대보조", "amount": 200000, "condition": "없음"}],
                                 "비산입 이름": [{"name": "시간외근로수당", "amount": 550000, "condition": "없음"}]}.items():
            with self.subTest(name):
                out = _run_calculator(dict(base, fixed_allowances=allowances), meal)
                self.assertIn("최저임금 충족: ❌ 미달", out)          # (1,950,000 + 200,000) ÷ 208.5714h = 10,308원 < 10,320원
                self.assertIn("실질시급: 2,150,000원 ÷ 208.5714h", out)
        # M1 — 세후 금액은 총액이 아니다 / M2 — 질문에 없는 의도분석 금액은 총액이 아니다
        net = "세후 월급은 240만 원이고, 기본급 2,096,270원에 연장·야간수당이 포함되어 있습니다. 퇴직금은 얼마인가요?"
        params = dict(self.PARAMS, calculation_types_kr=["최저임금", "퇴직금"], start_date="2025-03-01", end_date="2026-10-01")
        for amount in (2700000, 2100000):
            with self.subTest(net_pay=amount):
                out = _run_calculator(dict(params, wage_amount=amount), net)
                self.assertNotIn("2,400,000", out)
                self.assertNotIn(f"월급 {amount:,}원", out)
                self.assertIn("실제보다 적게 나왔을 수 있습니다", out)
        # 질문의 총액과 의도분석 금액이 어긋나면 총액을 모르는 것으로 둔다
        conflict = ("세전 월급은 270만 원이고, 기본급 2,096,270원에 연장·야간수당이 포함되어 있습니다. 지난달은 2,600,000원을 "
                    "받았어요. 퇴직금은 얼마인가요?")
        out = _run_calculator(dict(params, wage_amount=2600000), conflict)
        self.assertIn("실제보다 적게 나왔을 수 있습니다", out)
        self.assertNotIn("월급 2,700,000원", out)
        # 키워드 없는 '월 N원'도 의도분석 금액과 같으면 총액으로 쓴다
        bare = "월 270만원 받는데 기본급 2,096,270원에 연장·야간수당이 포함되어 있습니다. 퇴직금은 얼마인가요?"
        out = _run_calculator(dict(params, wage_amount=2700000), bare)
        self.assertIn("  퇴직금: 4,189,905원", out)

    def test_t5_severance_and_accident_summaries_do_not_overwrite_each_other(self):
        """퇴직금과 산재를 함께 물으면 요약의 '적용 평균임금' 키가 겹쳐 퇴직금 옆에 산재 값이 찍혔다(Act-3 리뷰 L2)."""
        from wage_calculator import WageCalculator, WageInput, WageType
        r = WageCalculator().calculate(WageInput(wage_type=WageType.MONTHLY, monthly_wage=2096270, monthly_total_pay=2700000,
                                                 reference_year=2026, start_date="2023-03-01", end_date="2026-10-01"),
                                       ["severance", "industrial_accident"])
        self.assertEqual(r.summary["적용 평균임금"], "88,043원/일 (3개월 기준)")
        self.assertEqual(r.summary["산재 적용 평균임금"], "90,000원/일")

    def test_t5_composition_without_the_word_included(self):
        """'포함'이라는 말 없이 기본급과 비산입 수당 금액을 나열해도 구성 진술이다 — 총액으로 '✅ 충족'을 냈다(Design §13.5
        R2 → Act-4). 별도 지급이면 아니다. 만원 단위 기본급도 읽고 근사값일 수 있다고 밝힌다."""
        from app.core.pipeline import _run_calculator, _stated_wage_composition
        listed = "월급 2,700,000원(기본급 2,096,270원, 고정연장수당 603,730원)입니다. 최저임금 위반인가요?"
        self.assertEqual(_stated_wage_composition(listed), (True, 2096270))
        self.assertEqual(_stated_wage_composition("기본급 200만원이고 연장수당 30만원은 별도로 받아요."), (False, 2000000))
        # 기본급 금액이 없으면 나열이 아니다 — 월급과 연장수당을 따로 말하는 질문일 수 있다
        self.assertEqual(_stated_wage_composition("이번 달 연장수당 300,000원을 받았는데 맞게 받은 건가요?"), (False, None))
        base = dict(self.PARAMS, business_size="5인이상")
        out = _run_calculator(dict(base), listed)
        self.assertIn("최저임금 충족: ❌ 미달", out)
        self.assertIn("통상시급: 10,051원", out)
        man = "월급 270만 원이고 기본급 209만원에 연장수당이 포함되어 있습니다. 최저임금 위반인가요?"
        out = _run_calculator(dict(base), man)
        self.assertIn("최저임금 충족: ❌ 미달", out)
        self.assertIn("기본급 2,090,000원으로", out)
        self.assertIn("기본급은 질문의 만 원 단위 금액으로 계산했습니다", out)

    def test_t5_comprehensive_wage_without_overtime_hours_is_held(self):
        """포괄임금제는 연장수당 등이 포함된 총액이다 — 약정 연장시간을 모르면 역산이 연장 0시간으로 나눠 '충족'을 냈다(R2 →
        Act-4). 총액으로도 미달이면 미달 그대로다(리뷰 H5). 연장시간이 있으면 최저임금 검증(총액 ÷ 소정근로시간)이 아니라
        역산(대법원 2020다300299 방식)으로 판정한다 — 의도분석 라벨이 '최저임금'뿐이면 역산이 빠져 '충족'이었다(리뷰 H4).
        '포괄임금제가 아니'·'아닌'이면 해당 없음(리뷰 L5)."""
        from app.core.pipeline import _run_calculator
        comp = dict(self.PARAMS, wage_type="포괄임금제", business_size="5인이상", calculation_types_kr=["최저임금"])
        out = _run_calculator(dict(comp), "포괄임금제로 월 270만원 받습니다. 주 40시간입니다. 최저임금 위반인가요?")
        self.assertIn("최저임금 충족: ⏸ 판정 보류", out)
        self.assertIn("약정 연장시간을 모르면", out)
        self.assertIn(f"{self.HELD_HOURLY}: 12,945원", out)
        for line in ("실질시급", "총액 기준 시급:", "≥ 10,320원"):       # 보류한 '충족'의 계산식·요약도 싣지 않는다
            self.assertNotIn(line, out)
        low = _run_calculator(dict(comp, wage_amount=2000000), "포괄임금제로 월 200만원 받는데 최저임금 위반인가요?")
        self.assertIn("최저임금 충족: ❌ 미달", low)              # 2,000,000 ÷ 208.5714h = 9,589원 — 연장시간과 무관하게 미달
        self.assertIn("포괄임금제 총액에는 연장·야간·휴일수당 등이 포함돼 있는데, 그 총액으로 계산해도 최저임금에 미달합니다", low)
        self.assertNotIn("약정 연장시간을 모르면", low)
        for labels in (["최저임금"], ["최저임금", "포괄임금제"], ["포괄임금제"], ["연차수당", "포괄임금제"]):
            with self.subTest(labels=labels):
                out = _run_calculator(dict(comp, weekly_overtime_hours=10, calculation_types_kr=labels),
                                      "포괄임금제로 월 270만원 받습니다. 주 50시간입니다. 위반인가요?")
                self.assertIn("최저임금 충족: ❌ 미달", out)
                self.assertIn("역산 기본시급: 2,700,000원 ÷ 273.75h = 9,863원", out)
                self.assertIn(f"{self.HELD_HOURLY}: 12,945원", out)    # 총액 ÷ 소정근로시간은 통상시급이 아니다
                self.assertNotIn("실질시급: 2,700,000원", out)
                self.assertNotIn("약정 연장시간을 모르면", out)
        # 기본급이 적혀 있으면 연장시간이 있어도 정확 경로(기본급 기준)다 — 역산은 총액이 기본급 + 법정 가산과 같다고 가정한다
        out = _run_calculator(dict(comp, weekly_overtime_hours=10),
                              "포괄임금제로 월 270만원(기본급 209만 6,270원) 받고 주 10시간 연장합니다. 최저임금 위반인가요?")
        self.assertIn("기본급 2,096,270원으로", out)
        self.assertIn("최저임금 충족: ❌ 미달", out)
        # 기본급이 있어도 산입 여부가 갈리는 항목이 있으면 보류지만, 연장시간을 아는데 '모르면'이라고 쓰지 않고, 포괄임금제라고만
        # 했는데 '포함돼 있다고 하셔서'라고 쓰지 않는다
        out = _run_calculator(dict(comp, weekly_overtime_hours=10),
                              "포괄임금제로 월 270만원(기본급 200만원, 상여금 포함) 받고 주 10시간 연장합니다. 위반인가요?")
        self.assertIn("최저임금 충족: ❌ 미달", out)                # 역산 9,863원 — 총액으로도 미달
        self.assertIn("포괄임금제 총액에는 연장·야간·휴일수당 등이 포함돼 있는데, 그 총액으로 계산해도 최저임금에 미달합니다", out)
        held = _run_calculator(dict(comp, wage_amount=3200000, weekly_overtime_hours=10),
                               "포괄임금제로 월 320만원(기본급 200만원, 상여금 포함) 받고 주 10시간 연장합니다. 위반인가요?")
        self.assertIn("최저임금 충족: ⏸ 판정 보류", held)
        self.assertIn("포괄임금제 총액에는 연장·야간·휴일수당 등이 포함돼 있어 최저임금 충족 여부는 판정하지 않았습니다", held)
        for text in (out, held):
            self.assertNotIn("약정 연장시간을 모르면", text)
            self.assertNotIn("포함돼 있다고 하셔서", text)
        enough = _run_calculator(dict(comp, wage_amount=3200000, weekly_overtime_hours=10),
                                 "포괄임금제로 월 320만원 받습니다. 주 50시간입니다. 위반인가요?")
        self.assertIn("최저임금 충족: ✅ 충족", enough)            # 3,200,000 ÷ 273.75h = 11,689원 — 역산 '충족'은 믿는다
        for query in ("포괄임금제가 아니고 월급 270만원입니다. 주 40시간입니다. 최저임금 위반인가요?",
                      "포괄임금제가 아닌 월급제로 270만원 받습니다. 주 40시간입니다. 최저임금 위반인가요?"):
            with self.subTest(query=query):
                self.assertNotIn("약정 연장시간을 모르면", _run_calculator(dict(comp), query))

    def test_t5_act4_review_parser_regressions(self):
        """Act-4 델타 리뷰 재현 — 만원 뒤 잔액을 버린 기본급(H2), 기간 단위를 무시한 이름 앞 금액(H3), 과거 시점·따로 지급
        나열(M3), '포함' 진술의 좁은 수당 이름(M4), 다른 기본급 언급에 붙은 근사 안내(L4)."""
        from app.core.pipeline import (_run_calculator, _stated_base_pay, _stated_other_pay, _stated_wage_composition,
                                       _base_rounding_unit)
        # H2 — 잔액까지 읽고, 못 읽거나 어림이면 쓰지 않는다
        for text, expected in {"기본급 209만 6천원에 연장수당이 포함": 2096000, "기본급 209만6,270원에 연장수당이 포함": 2096270,
                               "기본급 209만 6270원에 연장수당이 포함": 2096270, "기본급 209.6만원에 연장수당이 포함": 2096000,
                               "기본급 200만원대에 연장수당이 포함": None, "기본급 200만원 정도에 연장수당이 포함": None,
                               "기본급 209만 6백원에 연장수당이 포함": None}.items():
            with self.subTest(text):
                self.assertEqual(_stated_base_pay(text), expected)
        self.assertEqual(_base_rounding_unit("기본급 209만 6천원"), "천 원")
        self.assertEqual(_base_rounding_unit("기본급 209만6,270원"), None)        # 원 단위까지 적었다
        self.assertEqual(_base_rounding_unit("기본급 209만원, 계약서상 기본급 2,090,000원"), None)   # 같은 금액을 원 단위로도 적었다
        base = dict(self.PARAMS, wage_amount=2500000, reference_year=2025, business_size="5인이상")
        out = _run_calculator(dict(base), "월급 250만원(기본급 209만 6천원)에 연장수당이 포함돼 있어요. 최저임금 위반인가요?")
        self.assertIn("최저임금 충족: ✅ 충족", out)        # 2,096,000 ÷ 208.5714h = 10,049원 ≥ 10,030원(2025)
        self.assertIn("천 원 단위 금액으로 계산했습니다", out)
        # L4 — 근사 안내는 판정에 쓴 기본급이 만·천 원 표기일 때만
        out = _run_calculator(dict(self.PARAMS, business_size="5인이상"),
                              "작년 기본급은 190만원이었고 지금은 월급 2,700,000원(기본급 2,096,270원)에 연장수당이 포함돼 있어요.")
        self.assertIn("기본급 2,096,270원으로", out)
        self.assertNotIn("단위 금액으로 계산했습니다", out)
        # H3 — 금액 앞이 기간·다른 임금이면 이름 앞 금액이 아니다
        for text in ("기본급 200만원, 하루 8,000원짜리 식대와 연장수당이 포함돼 있어요.",
                     "기본급 190만원에 연 120만원의 식대와 연장수당이 포함되어 있습니다.",
                     "월급 250만원에 시급 10,320원의 주휴수당과 연장수당이 포함돼 있어요.",
                     "기본급 200만원에 주 5만원짜리 교통비와 연장수당 포함",
                     "기본급 2,000,000원의 식대 포함, 연장수당 포함"):
            with self.subTest(text):
                self.assertEqual(_stated_other_pay(text), ({}, True))
        self.assertEqual(_stated_other_pay("기본급 200만원에 월 200,000원짜리 식대와 연장수당이 포함"), ({"식대": 200000}, False))
        self.assertEqual(_stated_other_pay("기본급 200만원에 식대 19만 5천원과 연장수당이 포함"), ({}, True))   # 못 읽은 잔액
        from app.core.pipeline import _stated_total_pay
        self.assertIsNone(_stated_total_pay("월급 270만 5천원이고 기본급 2,096,270원입니다", 2096270))   # 총액도 마찬가지
        self.assertEqual(_stated_total_pay("월급 270만원이고 기본급 2,096,270원입니다", 2096270), 2700000)
        # M3 — 과거 시점 기본급·따로 받는 수당은 지금 월급의 구성이 아니다
        for text in ("작년에는 기본급 200만원에 연장수당 30만원이었는데, 올해는 월급 250만원이에요.",
                     "기본급 200만원, 연장수당 30만원은 매달 따로 나와요.",
                     "기본급 200만원인데 연장수당 30만원을 못 받았어요.",
                     "기본급 200만원이고 연장수당 30만원을 따로 받아요."):
            with self.subTest(text):
                self.assertFalse(_stated_wage_composition(text)[0])
        # M4 — '포함' 진술의 수당 이름은 항목 탐지와 같은 넓은 이름이다
        for name in ("시간외수당", "잔업수당", "고정OT", "포괄수당", "심야수당"):
            with self.subTest(name):
                self.assertEqual(_stated_wage_composition(f"월급 270만원에 {name}이 포함돼 있습니다."), (True, None))

    def test_t5_act4_rereview_regressions(self):
        """Act-4 재검토 재현 — 총액 위에 다시 더한 고정연장수당(M-A), 정상 금액까지 버린 꼬리 검사(M-B), 연장시간 미상 보류에
        실린 '역산 기본시급'(M-C), 총액을 '기본급 월액'·'실질시급'이라 부른 미달 카드(M-D), 판정 문장(H4a), 포함 진술 +
        연장시간(Low), '아닌가요?'(L5), 오리엔테이션 '오티'(M4), 다른 항목의 '없'(M3)."""
        from app.core.pipeline import _run_calculator, _stated_base_pay, _stated_total_pay, _stated_wage_composition
        base = dict(self.PARAMS, business_size="5인이상")
        fa = [{"name": "고정연장수당", "amount": 600000, "condition": "없음"}]
        # M-A — 금액이 총액이면 의도분석이 뽑은 연장수당은 그 일부다. '중' 표현도 구성 진술이다
        for query in ("월급 270만원에 고정연장수당 60만원이 포함되어 있습니다. 최저임금 위반인가요?",
                      "월급 270만원 중 60만원이 고정연장수당이에요. 최저임금 위반인가요?"):
            with self.subTest(query):
                out = _run_calculator(dict(base, fixed_allowances=fa), query)
                self.assertIn("월 총 예상 수령액(세전): 2,700,000원", out)
                self.assertIn("최저임금 충족: ⏸ 판정 보류", out)
        comp = dict(base, wage_type="포괄임금제", weekly_overtime_hours=10, fixed_allowances=fa)
        self.assertIn("월 총 예상 수령액(세전): 2,700,000원",
                      _run_calculator(comp, "포괄임금제로 월 270만원(고정연장수당 60만원 포함), 주 10시간 연장합니다. 위반인가요?"))
        self.assertFalse(_stated_wage_composition("월급 270만원 중 연장수당은 따로 받아요.")[0])
        # M-B — '원'으로 끝난 금액 뒤의 숫자·'초과근무'·'이상한'은 어림이 아니다
        for text, expected in {"기본급 2,096,270원 2026년 기준이고 연장수당 포함": 2096270,
                               "기본급 200만원 초과근무수당 30만원 포함": 2000000,
                               "기본급 200만원 이상하게 계산돼요": 2000000,
                               "기본급 200만 대에 연장수당 포함": None,
                               "기본급 209만 9천9백원에 연장수당 포함": None}.items():
            with self.subTest(text):
                self.assertEqual(_stated_base_pay(text), expected)
        self.assertEqual(_stated_total_pay("월급 250만원 5인 미만 카페, 기본급 200만원", 2000000), 2500000)
        out = _run_calculator(dict(base, wage_amount=2300000), "기본급 200만원 초과근무수당 30만원 포함, 월급 230만원입니다. 위반인가요?")
        self.assertIn("최저임금 충족: ❌ 미달", out)
        # M-C — 연장시간 미상 보류에는 역산을 싣지 않는다
        out = _run_calculator(dict(base, wage_type="포괄임금제", calculation_types_kr=["최저임금", "포괄임금제"]),
                              "포괄임금제로 월 270만원 받습니다. 주 40시간입니다. 최저임금 위반인가요?")
        self.assertIn("최저임금 충족: ⏸ 판정 보류", out)
        self.assertNotIn("역산", out)
        # M-D — 총액으로도 미달이라 남긴 최저임금 줄은 총액을 기본급·실질시급이라 부르지 않는다
        out = _run_calculator(dict(base, wage_amount=2000000), "월급 200만원에 연장수당이 포함되어 있습니다. 최저임금 위반인가요?")
        self.assertIn("최저임금 충족: ❌ 미달", out)
        self.assertIn("월급 총액(수당 포함, 기본급 아님): 2,000,000원", out)
        self.assertIn("최저임금 미달: 총액 기준 시급 9,589원", out)
        for stale in ("기본급 월액:", "실질시급"):
            self.assertNotIn(stale, out)
        # H4(a) — 최저임금을 묻지 않았으면 '역산으로 판정했습니다'라고 말하지 않는다
        out = _run_calculator(dict(base, wage_type="포괄임금제", weekly_overtime_hours=10, calculation_types_kr=["연차수당"],
                                   start_date="2025-03-01", end_date="2026-10-01"),
                              "포괄임금제로 월 270만원 받고 주 10시간 연장합니다. 연차수당은 얼마인가요?")
        self.assertNotIn("역산(대법원 2020다300299 방식)으로 판정했습니다", out)
        # 포함 진술 + 연장시간 — 진술 유무로 판정이 갈리지 않는다(역산은 연장시간을 반영한다)
        q = "포괄임금제로 월 320만원 받습니다. 연장·야간수당이 포함되어 있고 주 10시간 연장합니다. 위반인가요?"
        self.assertIn("최저임금 충족: ✅ 충족", _run_calculator(dict(base, wage_type="포괄임금제", wage_amount=3200000,
                                                                 weekly_overtime_hours=10), q))
        # L5 — '포괄임금제 아닌가요?'는 의문이다
        out = _run_calculator(dict(base, wage_type="포괄임금제", wage_amount=2500000),
                              "회사가 포괄임금제 아닌가요? 월 250만원, 주 40시간입니다. 최저임금 위반인가요?")
        self.assertIn("약정 연장시간을 모르면", out)
        # M4 — 오리엔테이션 '오티'는 시간외근로수당이 아니다 / M3 — 다른 항목의 '없'
        self.assertFalse(_stated_wage_composition("입사 첫 주에 오티 포함 3일 교육을 받았고 월급은 250만원입니다.")[0])
        self.assertEqual(_stated_wage_composition("기본급 200만원에 연장수당 30만원이라 식대가 없어요."), (True, 2000000))

    HELD_HOURLY = "월급 총액 기준 시급(포함 수당 때문에 통상시급 아님)"

    # 그 이름을 부정하는 표기("…통상시급 아님", "…통상임금 아님", "통상시급이 아닙니다")·금액 보류 안내와 법적 근거 줄은
    # 이름을 붙이는 것이 아니다
    DENIALS = ("통상시급 아님", "통상임금 아님", "통상시급이 아닙니다", "금액 보류:")

    def _stale_names(self, out):
        """카드에서 아직 총액 기반 값을 '통상시급'·'통상임금'이라 부르는 줄."""
        return [line.strip() for line in out.splitlines()
                if re.search(r"통상(?:시급|임금)", line)
                and not any(d in line for d in self.DENIALS)
                and not line.strip().startswith("• 근로기준법 (통상임금)")]

    def test_t5_held_card_never_names_the_total_an_ordinary_hourly_wage(self):
        """보류 카드의 첫 줄이 '통상시급: 12,945원'(총액 270만 원 ÷ 208.5714h)이었다(Plan P0-5 둘째 항목). 통상임금은
        연장·야간·휴일수당을 포함하지 않는다. 카드는 LLM에 '이 수치를 사용하세요'로 주입되므로 이름이 틀리면 표시와
        근거가 둘 다 틀린다."""
        from app.core.pipeline import _run_calculator
        # 성격이 갈리는 수당(상여금)이 섞이면 기본급으로 판정하지 않고 보류한다(금액이 모두 적힌 식대·직책수당이면 Act-3 정확 경로)
        other_pay = ("월급 2,600,000원(기본급 2,000,000원, 식대 200,000원, 상여금 100,000원, 고정연장수당 300,000원 포함)입니다. "
                     "최저임금 위반인가요? 주 40시간입니다.")
        no_base = "월급 270만 원에 연장·야간·휴일근로수당과 연차수당이 포함되어 있습니다. 최저임금 위반인가요? 주 40시간입니다."
        comp = "포괄임금제로 월 {}원 받습니다. 연장·야간수당이 포함되어 있습니다. 주 40시간입니다."
        comp_params = dict(self.PARAMS, wage_type="포괄임금제", calculation_types_kr=["포괄임금제"], business_size="5인이상")
        cases = {
            # 기본급이 없으면 보류다(4대보험은 총액 기준으로 그대로 계산되고 이름만 바뀐다)
            "기본급 미기재 + 4대보험": (dict(self.PARAMS, calculation_types_kr=["최저임금", "4대보험"]), no_base, "12,945"),
            "성격이 갈리는 수당 동반": (dict(self.PARAMS, wage_amount=2600000, business_size="5인이상"), other_pay, "12,466"),
            "포괄임금 보류": (dict(comp_params, wage_amount=2700000), comp.format("2,700,000"), "12,945"),
            # '미달'은 판정을 두는 경로지만 시급 이름은 같다 — 9,589원은 총액 ÷ 시간이다. 안내 문구는 교체되지만 이름표
            # 설명 문장은 같이 붙는다(Act-1 재확인 N2: 빠져 있었고 테스트가 그 부재를 정상으로 고정했다)
            "포괄임금 미달": (dict(comp_params, wage_amount=2000000), comp.format("2,000,000"), "9,589"),
        }
        for name, (params, query, won) in cases.items():
            with self.subTest(name):
                out = _run_calculator(params, query)
                self.assertIn(f"{self.HELD_HOURLY}: {won}원", out)
                self.assertNotIn("통상시급: ", out)
                # 통상임금 계산을 요청하지 않아도 계산식에는 항상 '[통상임금] 월 기본급: 총액'이 실린다
                # (Act-1 코드 리뷰: 이 재현이 고정돼 있지 않았다)
                self.assertNotIn("[통상임금]", out)
                self.assertNotIn("월 기본급:", out)
                # 경고가 사라진 이름을 가리키면("위 통상시급은") 한 카드 안에서 이름이 어긋난다
                self.assertNotIn("위 통상시급", out)
                self.assertIn("위 시급은 그 수당이 섞인 월급 총액", out)
                # 이 시급으로 계산하는 금액(연장수당·퇴직금의 통상임금 하한 등)은 함께 보류하므로(Act-2 C27) 카드에 총액을
                # '통상'이라 부르는 줄이 남지 않는다. Act-1에서는 퇴직금 계산기의 줄이 잔여로 남아 있었다
                self.assertEqual(self._stale_names(out), [])

    HOLD_Q = "월급 270만 원에 연장·야간·휴일수당과 연차수당이 포함되어 있습니다. 주 40시간, 주 5일 근무합니다."
    DATES = {"start_date": "2023-03-01", "end_date": "2026-10-01"}

    def test_t5_held_card_holds_amounts_computed_from_the_ordinary_wage(self):
        """보류 카드의 '통상임금'은 연장·야간·휴일·연차수당이 섞인 총액이라 그것으로 낸 금액이 모두 부풀려진다 — 연장수당
        843,634원이 총액 위에 더해져 월 총액 3,543,634원이 됐고, 퇴직금·평균임금·산재는 '평균임금 < 통상임금' 하한이 부풀린
        통상임금으로 걸렸다(Design §13.5 R1·R6). 금액만 보류하고 무엇을 뺐는지 계열별 이유와 함께 밝힌다(Act-2 C27·C29).
        일수·시간처럼 시급과 무관한 결과는 남는다(코드 리뷰 M2)."""
        from app.core.pipeline import _run_calculator
        base = dict(self.PARAMS, business_size="5인이상")
        comp_params = dict(base, wage_type="포괄임금제", wage_amount=2000000, calculation_types_kr=["포괄임금제"])
        comp_q = "포괄임금제로 월 2,000,000원 받습니다. 연장·야간수당이 포함되어 있습니다. 주 40시간입니다."
        ot, wh = "연장/야간/휴일 수당", "주휴수당"
        # (params, query, 통상시급 계열 보류, 평균임금 계열 보류, 없어야 할 금액 줄, 남아야 할 줄)
        cases = {
            "연장수당": (dict(base, calculation_types_kr=["연장수당"], weekly_overtime_hours=10), self.HOLD_Q,
                     [ot], [], ["연장/야간/휴일수당(월)", "연장수당: "], []),
            "주휴수당": (dict(base, calculation_types_kr=["주휴수당"]), self.HOLD_Q, [wh], [], ["주휴수당(월)", "주휴수당: "],
                     ["주휴: min(8h, 8h) = 8h"]),
            "연차수당": (dict(base, calculation_types_kr=["연차수당"], **self.DATES), self.HOLD_Q,
                     ["연차수당"], [], ["  연차수당: ", "미사용 연차수당:"],
                     ["  법정 연차 발생일수: 16.0일", "  미사용 연차: 16.0일", "사용촉진제도 미실시"]),
            "해고예고수당": (dict(base, calculation_types_kr=["해고예고수당"], **self.DATES), self.HOLD_Q,
                       ["해고예고수당"], [], ["  해고예고수당: "], []),
            # 퇴직소득세·퇴직연금은 퇴직금 결과로 계산한다 — 함께 보류한다
            "퇴직소득세": (dict(base, calculation_types_kr=["퇴직소득세"], **self.DATES), self.HOLD_Q,
                      [], ["퇴직금", "퇴직소득세"], ["  퇴직금: ", "  퇴직소득세: ", "적용 평균임금", "평균임금 < 통상임금"],
                      ["  계속근로: 1310일 (3.59년)", "근속연수: 4년"]),
            "퇴직연금": (dict(base, calculation_types_kr=["퇴직연금"], **self.DATES), self.HOLD_Q,
                     [], ["퇴직금", "퇴직연금(DB/DC)"], ["  퇴직금: ", "퇴직연금 수령액"], []),
            "평균임금": (dict(base, calculation_types_kr=["평균임금"], **self.DATES), self.HOLD_Q,
                     [], ["평균임금"], ["1일 평균임금", "적용 기준: 통상임금"], ["  산정기간: 92일"]),
            "산재": (dict(base, calculation_types_kr=["산재"], **self.DATES), self.HOLD_Q,
                   [], ["평균임금", "산재보상금(휴업·장해·유족·장례비)"], ["적용 평균임금", "1일 평균임금"], []),
            "휴업수당": (dict(base, calculation_types_kr=["휴업수당"], shutdown_days=10, **self.DATES), self.HOLD_Q,
                     [], ["휴업수당(근기법 제46조)"], ["  휴업수당: ", "적용 기준"], []),
            "육아휴직": (dict(base, calculation_types_kr=["육아휴직"], parental_leave_months=12, **self.DATES), self.HOLD_Q,
                     ["육아휴직급여"], [], ["육아휴직 월 수령액"], []),
            "출산휴가(다태아)": (dict(base, calculation_types_kr=["출산휴가"], is_multiple_birth=True, **self.DATES),
                            self.HOLD_Q, ["출산전후휴가급여"], [], ["출산전후휴가 월 급여", "배우자 출산휴가 유급액"],
                            ["다태아 출산전후휴가: 120일"]),
            "유급 공휴일": (dict(base, calculation_types_kr=["유급공휴일"], public_holiday_days=2), self.HOLD_Q,
                       ["유급 공휴일"], [], ["유급공휴일 수당"], []),
            "보상휴가": (dict(base, calculation_types_kr=["보상휴가"], weekly_overtime_hours=5), self.HOLD_Q,
                     [ot, "보상휴가 환산"], [], ["연장/야간/휴일수당(월)", "미사용 보상휴가 수당"], ["  보상휴가(주): 7.50h"]),
            # 포괄임금제 총액 + 연장시간은 '포함' 진술이 있어도 보류가 아니라 역산으로 판정한다(Act-4 재검토) — 통상임금으로 낸
            # 금액은 그 경로에서도 보류하고 보류 목록을 안내에 싣는다(코드 리뷰 L5)
            "포괄임금 미달 + 연장": (dict(comp_params, weekly_overtime_hours=10, calculation_types_kr=["포괄임금제", "연장수당"]),
                                   comp_q, [ot], [], ["연장/야간/휴일수당(월)"],
                                   ["최저임금은 연장 가산을 반영한 역산(대법원 2020다300299 방식)으로 판정했습니다",
                                    "포괄임금 역산 시급 7,306원 < 최저임금 10,320원"]),
        }
        for name, (params, query, hourly, average, gone, kept) in cases.items():
            with self.subTest(name):
                out = _run_calculator(params, query)
                for line in gone:
                    self.assertNotIn(line, out)
                for line in kept:
                    self.assertIn(line, out)
                self.assertIn("금액 보류:", out)
                if hourly:
                    self.assertIn(f"통상임금(시급·일급·월액)으로 계산하는 항목({', '.join(hourly)})", out)
                else:
                    self.assertNotIn("통상임금(시급·일급·월액)으로 계산하는 항목", out)
                if average:
                    self.assertIn(f"평균임금으로 계산하는 항목({', '.join(average)})", out)
                else:
                    self.assertNotIn("평균임금으로 계산하는 항목", out)
                self.assertIn("추정하지 마세요", out)
                # 금액이 총액 위에 더해지지 않는다 — 카드의 월 총액은 사용자가 말한 총액이다
                won = "2,000,000" if "포괄" in name else "2,700,000"
                self.assertIn(f"월 총 예상 수령액(세전): {won}원", out)
                self.assertEqual(self._stale_names(out), [])

    def test_t5_held_card_passes_only_eligibility_zeros(self):
        """자격 판정으로 0인 결과(퇴직금 미발생·주휴 미발생)는 통상임금과 무관하다 — 보류하면 '(보류: 퇴직금)'이 없는 퇴직금이
        있는 것처럼 읽혔다(코드 리뷰 M2). 입력이 없어 0인 결과(연장시간·입사일 미기재)는 보류한다 — 통과시키면 사용자가
        '포함돼 있다'고 한 수당에 '0원'이 붙었다(재검토 N1). 퇴직연금(DB형)은 퇴직금을 따른다(재검토 N2)."""
        from app.core.pipeline import _run_calculator
        base = dict(self.PARAMS, business_size="5인이상")
        short = {"start_date": "2026-03-01", "end_date": "2026-10-01"}
        part_q = "월급 600,000원에 연장·야간·휴일수당과 연차수당이 포함되어 있습니다. 주 12시간, 주 3일 근무합니다."
        passed = {
            "퇴직금 미발생": (dict(base, calculation_types_kr=["퇴직금"], **short), self.HOLD_Q,
                         ["퇴직금 미발생", "  퇴직금: 0원"]),
            "퇴직연금도 퇴직금을 따른다": (dict(base, calculation_types_kr=["퇴직연금"], **short), self.HOLD_Q,
                                  ["퇴직금 미발생", "퇴직연금 수령액: 0원", "DB형 퇴직연금도 0원"]),
            "주휴 미발생": (dict(base, wage_amount=600000, weekly_total_hours=12, weekly_work_days=3,
                            calculation_types_kr=["주휴수당"]), part_q, ["주휴수당(월): 0원", "주휴수당 미발생"]),
        }
        for name, (params, query, kept) in passed.items():
            with self.subTest(name):
                out = _run_calculator(params, query)
                for line in kept:
                    self.assertIn(line, out)
                self.assertNotIn("금액 보류:", out)
        held = {
            "연장시간 미기재": (dict(base, calculation_types_kr=["연장수당"]), "연장/야간/휴일 수당",
                           "연장/야간/휴일수당(월): 0원"),
            "입사일 미기재": (dict(base, calculation_types_kr=["연차수당"]), "연차수당", "  연차수당: 0원"),
        }
        for name, (params, label, zero_line) in held.items():
            with self.subTest(name):
                out = _run_calculator(params, self.HOLD_Q)
                self.assertNotIn(zero_line, out)
                self.assertIn(f"통상임금(시급·일급·월액)으로 계산하는 항목({label})", out)

    def test_t5_held_formulas_drop_zero_lines_with_inflated_figures(self):
        """금액 보류 섹션은 결론이 0원인 계산식도 뺀다 — '과세표준: 2,865,414 - 2,865,414 = 0원'은 부풀린 퇴직금으로 낸
        중간값이다(재검토 N4)."""
        from app.core.pipeline import _run_calculator
        query = "월급 1,200,000원에 연장·야간·휴일수당과 연차수당이 포함되어 있습니다. 주 40시간, 주 5일 근무합니다."
        out = _run_calculator(dict(self.PARAMS, wage_amount=1200000, business_size="5인이상",
                                   calculation_types_kr=["퇴직소득세"], **self.DATES), query)
        self.assertIn("평균임금으로 계산하는 항목(퇴직금, 퇴직소득세)", out)
        self.assertNotIn("과세표준", out)
        self.assertIn("근속연수: 4년", out)

    def test_t5_db_pension_is_zero_when_severance_is_not_due(self):
        """DB형 퇴직연금은 '퇴직금과 동일'이 계산의 전제다 — 퇴직금 미발생인데 통상시급으로 따로 추정해 계속근로 7개월에
        1,821,300원을 냈다(보류 경로 밖의 일반 카드에서도, 재검토 N2)."""
        from wage_calculator import WageCalculator, WageInput, WageType
        from wage_calculator.models import BusinessSize
        from wage_calculator.result import format_result
        inp = WageInput(wage_type=WageType.MONTHLY, monthly_wage=2700000, business_size=BusinessSize.OVER_5,
                        reference_year=2026, start_date="2026-03-01", end_date="2026-10-01")
        out = format_result(WageCalculator().calculate(inp, ["severance", "retirement_pension"]))
        self.assertIn("퇴직연금 수령액: 0원", out)
        self.assertIn("퇴직금 미발생", out)

    def test_t5_amount_held_sections_do_not_report_applied_rule_versions(self):
        """관리 모드에서 금액을 보류한 섹션이 읽은 승인 기준은 적용 버전으로 보고하지 않는다 — 금액이 없는 카드 머리에
        '기준 버전: maternity.monthly_upper'가 붙었다(재검토 N3). 보류하지 않으면 그대로 보고한다."""
        import copy
        import test_legal_rule_updates as rules
        from app.core.legal_updates import LegalUpdateService
        from wage_calculator import WageCalculator, WageInput, WageType
        from wage_calculator.models import BusinessSize
        store = rules.MemoryStore()
        service = LegalUpdateService(store, rules.Evidence())
        for change in ({}, {"topic": "maternity_leave", "key": "maternity.monthly_upper", "value": 3_000_000}):
            record = service.create(rules.proposal(**change), store.revision, "admin-test")
            service.transition(record["id"], "approve", store.revision, "admin-test", "원문·시행일·값 대조 확인")
        inp = WageInput(wage_type=WageType.MONTHLY, monthly_wage=2_700_000, reference_year=2031,
                        reference_date="2031-06-01", business_size=BusinessSize.OVER_5,
                        start_date="2029-03-01", end_date="2031-06-01")
        calc = WageCalculator(rule_store=store)
        plain = calc.calculate(copy.deepcopy(inp), ["maternity_leave"])
        self.assertIn("maternity.monthly_upper", [version["key"] for version in plain.legal_rule_versions])
        held = calc.calculate(copy.deepcopy(inp), ["maternity_leave"], amount_hold=("maternity_leave",))
        self.assertEqual(held.amount_held, ["maternity_leave"])
        self.assertEqual(held.legal_rule_versions, [])
        self.assertEqual(held.legal_rule_status, "managed_no_parameters")

    def test_t5_held_card_keeps_amounts_whose_basis_is_the_total(self):
        """4대보험 보수월액·실업급여 평균임금은 수당을 포함한 총액이 맞는 기준이다 — 보류하지 않는다. 4대보험 계산식의
        '(통상임금 기준)'은 그 총액을 통상임금이라 부르므로 이름만 바꾼다(Act-2 C28)."""
        from app.core.pipeline import _run_calculator
        out = _run_calculator(dict(self.PARAMS, business_size="5인이상", calculation_types_kr=["4대보험", "실업급여"],
                                   **self.DATES), self.HOLD_Q)
        self.assertIn("세전 월 급여: 2,700,000원 (월급 총액 기준)", out)
        self.assertNotIn("(통상임금 기준)", out)
        self.assertIn("평균임금 일액(추정): (2,700,000원 × 3) ÷ 92일", out)
        self.assertIn("구직급여 일액", out)
        self.assertNotIn("금액 보류:", out)
        self.assertEqual(self._stale_names(out), [])

    def test_t5_held_targets_note(self):
        """평균임금 계열은 '통상임금으로 계산하는 항목'이 아니다 — 평균임금은 총액이 맞고 하한을 확인할 수 없을 뿐이다. 한
        문장으로 묶으면 LLM이 "퇴직금은 통상임금 기준"으로 옮긴다(코드 리뷰 M3)."""
        from app.core.pipeline import _held_targets_note, _calculation_context_heading
        self.assertEqual(_held_targets_note([]), "")
        note = _held_targets_note(["overtime", "severance", "retirement_tax"])
        self.assertIn("금액 보류: 통상임금(시급·일급·월액)으로 계산하는 항목(연장/야간/휴일 수당)은 수당이 섞인 총액으로는", note)
        self.assertIn("평균임금으로 계산하는 항목(퇴직금, 퇴직소득세)은 평균임금 자체는 수당을 포함한 총액이 맞지만", note)
        # 휴업수당은 하한이 아니라 통상임금 상한 비교다(재검토 N5)
        self.assertIn("휴업수당의 통상임금 상한", note)
        self.assertIn("추정하지 마세요", note)
        self.assertNotIn("통상임금으로 계산하는", note)
        # 금액을 보류한 카드에는 LLM 컨텍스트 머리말도 추정 금지를 덧붙인다(코드 리뷰 L4)
        self.assertIn("금액을 보류한 항목은 추정하지 마세요", _calculation_context_heading("📊 임금 계산 결과" + note))
        self.assertEqual(_calculation_context_heading("📊 임금 계산 결과"), "임금계산기 결과 — 이 수치를 사용하세요")

    # 통상임금을 읽지만 보류 경로에서 그대로 계산하는 계산기와 그 이유. 보류 대상(`_ORDINARY_BASED_TARGETS`)에도 여기에도 없는
    # 계산기가 통상임금을 읽기 시작하면 보류 카드에 부풀린 금액이 다시 실린다.
    KEPT_ORDINARY_READERS = {
        "comprehensive": "월급 총액(inp.monthly_wage)으로 역산하는 계산이다 — 판정은 따로 내린다",
        "prorated": "월급 총액으로 일할계산한다(통상임금은 월급이 없을 때만 읽는다)",
        "insurance": "보수월액은 수당을 포함한 총액이 맞다 — 계산식의 이름만 바꾼다(사업주 부담분도 같은 모듈)",
        "unemployment": ("월급이 있으면 평균임금을 월급 총액으로 추정한다(통상시급은 월급이 없을 때만 읽는다). 기초일액의 통상임금 "
                         "비교(고용보험법 제45조 제2항)는 총액 경로에서 하지 않는다(shared.ordinary_wage_from_total)"),
        "eitc": ("소득은 월급(총액)으로 추정한다 — 통상시급은 연장 등 근로 임금을 더할 때만 읽고, 구성이 정해진 총액(보류 경로)에는 "
                 "더하지 않는다(shared.monthly_pay_estimate, calc-card-followups F6)"),
        "working_hours": "시간을 계산한다 — 계산식의 시급 단어만 바꾼다",
    }

    def test_t5_every_calculator_reading_the_ordinary_wage_is_classified(self):
        """보류 대상은 '통상임금(통상시급·1일·월 통상임금)을 읽는 계산기'를 전수 점검해 정했다(Design §13.5 R1 선행 조건).
        새 계산기나 수정된 계산기가 통상임금을 읽으면 어느 쪽인지 정해야 이 테스트가 통과한다."""
        from app.core.pipeline import _ORDINARY_BASED_TARGETS
        readers = set()
        for path in (ROOT / "wage_calculator" / "calculators").glob("*.py"):
            if path.stem in ("ordinary_wage", "shared", "__init__"):
                continue
            if re.search(r"\bow\.(?:hourly|daily|monthly)_ordinary_wage\b", path.read_text(encoding="utf-8")):
                readers.add(path.stem)
        self.assertEqual(readers - _ORDINARY_BASED_TARGETS - set(self.KEPT_ORDINARY_READERS), set())
        # 분류표가 실제 계산기를 가리키는지도 본다 — 이름이 바뀌면 분류가 조용히 비고, 겹치면 어느 쪽인지 모호하다
        self.assertLessEqual(set(self.KEPT_ORDINARY_READERS), readers)
        self.assertEqual(_ORDINARY_BASED_TARGETS & set(self.KEPT_ORDINARY_READERS), set())
        from wage_calculator.facade.registry import CALC_TYPES
        self.assertLessEqual(_ORDINARY_BASED_TARGETS, set(CALC_TYPES))

    def test_t5_kept_calculators_do_not_read_the_hourly_or_daily_ordinary_wage(self):
        """유지 목록의 계산기는 월급이 있으면 통상시급·1일 통상임금을 쓰지 않아야 한다. 파일 단위 분류 검사는 유지 계산기에
        통상임금 하한(예: 구직급여)이 새로 들어와도 잡지 못한다(코드 리뷰 L5). 시급·일급만 두 배로 바꿔 요약이 그대로인지
        본다 — 월 통상임금은 4대보험이 보수(= 월급 총액)로 쓰므로 그대로 둔다."""
        import copy
        import dataclasses
        from wage_calculator.calculators.ordinary_wage import calc_ordinary_wage
        from wage_calculator.facade.registry import _STANDARD_CALCS
        from wage_calculator.models import BusinessSize, WageInput, WageType, WorkSchedule
        from wage_calculator.result import WageResult
        # 보류 카드의 조건 — 월급이 수당이 섞인 총액으로 정해진 경로다(wage_composition_known). 그 밖의 경로에서는 실업급여가 1일
        # 통상임금과 기초일액을 비교한다(고용보험법 제45조 제2항, calc-card-followups F5)
        inp = WageInput(wage_type=WageType.MONTHLY, monthly_wage=2700000, business_size=BusinessSize.OVER_5,
                        schedule=WorkSchedule(daily_work_hours=8, weekly_work_days=5), wage_composition_known=True,
                        reference_year=2026, start_date="2023-03-01", end_date="2026-10-01")
        ow = calc_ordinary_wage(inp)
        bumped = dataclasses.replace(ow, hourly_ordinary_wage=ow.hourly_ordinary_wage * 2,
                                     daily_ordinary_wage=ow.daily_ordinary_wage * 2)
        calcs = {key: (func, populate) for key, func, _, populate, _ in _STANDARD_CALCS}
        # 소정근로시간 계산기는 카드의 시급을 되풀이해 보여 줄 뿐이다(시간 계산은 시급과 무관)
        echoes = {"시급", "월급 환산"}
        for key in ("insurance", "employer_insurance", "unemployment", "eitc", "comprehensive", "prorated",
                    "working_hours"):
            func, populate = calcs[key]

            def summary(wage):
                result = WageResult()
                populate(func(copy.deepcopy(inp), wage), result)
                return {k: v for k, v in result.summary.items() if k not in echoes}
            with self.subTest(key):
                self.assertEqual(summary(ow), summary(bumped))

    def test_t5_base_amount_with_priced_pay_is_computed_exactly(self):
        """의도분석이 기본급을 뽑고 식대가 금액과 함께 적혀 있으면 통상임금 = 기본급 + 식대, 최저임금 산입도 그 합이다 — Act-2
        까지는 보류하고 기본급만으로 연장수당을 계산해 과소였다(Design §13.5 R8 → Act-3). 총액(260만 원)은 질문에서 읽는다."""
        from app.core.pipeline import _run_calculator
        query = "월급 260만 원(기본급 2,000,000원, 식대 200,000원, 고정연장수당 포함)입니다. 연장수당은 얼마인가요? 주 40시간입니다."
        out = _run_calculator(dict(self.PARAMS, wage_amount=2000000, business_size="5인이상",
                                   calculation_types_kr=["최저임금", "연장수당"], weekly_overtime_hours=10), query)
        self.assertIn("통상시급: 10,548원", out)
        self.assertIn("최저임금 충족: ✅ 충족", out)
        self.assertIn("연장/야간/휴일수당(월): 687,500원", out)
        self.assertIn("기본급 2,000,000원과 식대 200,000원으로", out)
        self.assertNotIn("판정 보류", out)

    def test_t5_hold_with_the_base_as_amount_keeps_computing(self):
        """보류해도 계산 금액이 질문의 기본급이면(수당 금액 미기재) 그 시급은 총액 ÷ 시간이 아니다 — 금액을 보류하는 것은
        총액일 때뿐이다(Act-2 경계)."""
        from app.core.pipeline import _run_calculator
        query = "월급 260만 원(기본급 2,000,000원, 식대와 고정연장수당 포함)입니다. 연장수당은 얼마인가요? 주 40시간입니다."
        out = _run_calculator(dict(self.PARAMS, wage_amount=2000000, business_size="5인이상",
                                   calculation_types_kr=["최저임금", "연장수당"], weekly_overtime_hours=10), query)
        self.assertIn("최저임금 충족: ⏸ 판정 보류", out)
        self.assertIn("통상시급: 9,589원", out)
        self.assertIn("연장/야간/휴일수당(월)", out)
        self.assertNotIn("금액 보류:", out)

    def test_t5_held_card_keeps_ordinary_names_when_the_amount_is_not_a_total(self):
        """의도분석이 질문의 기본급(만 원 단위 반올림 포함)을 임금으로 뽑았으면 그 값은 총액이 아니다 — '월급 총액(… 기본급
        아님)' 이름표가 사용자 진술(기본급 2,000,000원)을 뒤집었다(Act-1 코드 리뷰 재현). 판정은 여전히 보류다."""
        from app.core.pipeline import _run_calculator
        # 식대 금액이 없어 기본급으로 판정하지 않는다(보류). 금액이 있으면 Act-3 정확 경로다
        other_pay = ("월급 260만 원(기본급 2,000,000원, 식대와 고정연장수당 포함)입니다. "
                     "최저임금 위반인가요? 주 40시간입니다.")
        # 질문에 총액이 없고 금액이 기본급보다 작다(반올림) → 의도분석 금액과 기본급이 어긋나 보류. 총액이 적혀 있으면
        # 금액과 무관하게 정확 경로다(`test_t5_amount_extraction_does_not_change_the_dual_basis_card`)
        no_total = self.Q36.replace("세전 월급은 270만 원이고, ", "")
        cases = {
            "기본급보다 작은 금액": (dict(self.PARAMS, wage_amount=2090000), no_total, "10,021", "2,090,000"),
            "기본급과 같은 금액": (dict(self.PARAMS, wage_amount=2000000, business_size="5인이상"), other_pay, "9,589", "2,000,000"),
            # 허용폭(C8과 같은 1,000원) 안이면 기본급으로 본다
            "기본급 + 500원": (dict(self.PARAMS, wage_amount=2000500, business_size="5인이상"), other_pay, "9,591", "2,000,500"),
        }
        for name, (params, query, won, amount) in cases.items():
            with self.subTest(name):
                out = _run_calculator(params, query)
                self.assertIn("최저임금 충족: ⏸ 판정 보류", out)
                self.assertIn(f"통상시급: {won}원", out)
                self.assertIn(f"[통상임금] 월 기본급: {amount}원", out)
                self.assertNotIn("월급 총액", out)
                self.assertNotIn("위 시급은", out)

    def test_t5_held_formula_relabel_only_touches_leading_labels(self):
        """계산식 치환은 통상임금 계산기의 머리말만 바꾼다. 줄 중간의 같은 글자는 다른 계산기의 설명일 수 있다."""
        from app.core.pipeline import _relabel_held_formula
        total = "월급 총액(수당 포함, 기본급·통상임금 아님):"
        self.assertEqual(_relabel_held_formula("[통상임금] 월 기본급: 2,700,000원"), f"[시급 환산] {total} 2,700,000원")
        self.assertEqual(_relabel_held_formula("월 기본급: 2,700,000원"), f"{total} 2,700,000원")
        self.assertEqual(_relabel_held_formula("[통상임금] 포괄임금 총액(기본급 구분 없음): 2,700,000원"),
                         "[시급 환산] 포괄임금 총액(기본급 구분 없음): 2,700,000원")
        self.assertEqual(_relabel_held_formula("참고: 월 기본급: 1원"), "참고: 월 기본급: 1원")
        self.assertEqual(_relabel_held_formula("퇴직금: 통상임금 환산 103,547원/일"), "퇴직금: 통상임금 환산 103,547원/일")

    def test_t5_held_card_renames_the_hourly_word_in_other_calculators_lines(self):
        """소정근로시간 계산기는 '월급 환산 = 통상시급 × 시간' 식을 만든다 — 보류 카드에서 그 시급은 총액 ÷ 시간이라, 첫 줄은
        '통상시급 아님'인데 계산식은 '통상시급'이면 한 카드 안에서 이름이 충돌한다(Act-1 코드 리뷰 중-2·재확인 N1이 독립적으로
        지적)."""
        from app.core.pipeline import _run_calculator
        query = "월급 270만 원에 연장수당이 포함돼 있습니다. 주 40시간인데 월 소정근로시간과 최저임금 위반 여부를 알려주세요."
        out = _run_calculator(dict(self.PARAMS, calculation_types_kr=["소정근로시간", "최저임금"]), query)
        self.assertIn("월급 환산 = 총액 기준 시급 12,945.21 × 208.5714h = 2,700,000원", out)
        self.assertEqual(self._stale_names(out), [])
        self.assertNotIn("통상시급 12,945", out)

    def test_t5_hourly_word_rename_keeps_denials(self):
        from app.core.pipeline import _rename_held_hourly
        self.assertEqual(_rename_held_hourly("월급 환산 = 통상시급 12,945 × 208.5714h"), "월급 환산 = 총액 기준 시급 12,945 × 208.5714h")
        self.assertEqual(_rename_held_hourly("평균임금을 통상시급으로 추정했습니다."), "평균임금을 총액 기준 시급으로 추정했습니다.")
        # 이름을 부정하는 표기는 그대로다
        for kept in ("월급 총액 기준 시급(포함 수당 때문에 통상시급 아님)", "위 시급은 통상시급이 아니며 …"):
            self.assertEqual(_rename_held_hourly(kept), kept)

    def test_t5_held_card_renames_every_total_based_line_when_ordinary_wage_is_requested(self):
        """통상임금 계산이 함께 오면 summary와 계산식에도 같은 총액이 '통상시급'·'월 통상임금'·'월 기본급'으로 실린다.
        첫 줄만 바꾸면 한 카드 안에서 이름이 갈려 LLM이 총액을 기본급·통상임금으로 읽는다."""
        from app.core.pipeline import _run_calculator
        query = ("월급 2,600,000원(기본급 2,000,000원, 식대 200,000원, 상여금 100,000원, 고정연장수당 300,000원 포함)입니다. "
                 "최저임금 위반인가요? 통상임금도 알려주세요. 주 40시간입니다.")
        out = _run_calculator(dict(self.PARAMS, wage_amount=2600000, business_size="5인이상",
                                   calculation_types_kr=["최저임금", "통상임금"]), query)
        self.assertIn("최저임금 충족: ⏸ 판정 보류", out)
        for stale in ("통상시급: ", "월 통상임금:", "월 기본급:", "[통상임금]"):
            self.assertNotIn(stale, out, stale)
        self.assertIn(f"  {self.HELD_HOURLY}: 12,466원", out)                      # 항목별 결과 줄
        self.assertIn("  월급 총액(포함 수당 때문에 통상임금 아님): 2,600,000원", out)
        self.assertIn("[시급 환산] 월급 총액(수당 포함, 기본급·통상임금 아님): 2,600,000원", out)

    def test_t5_cards_with_a_real_base_pay_keep_the_ordinary_hourly_label(self):
        """기본급 경로·C8 경로·미진술 경로의 시급은 실제 기본급(또는 사용자가 말한 월급) ÷ 시간이다 — 이름을 바꾸지 않는다."""
        from app.core.pipeline import _run_calculator
        plain = "월급 270만 원, 주 40시간인데 최저임금 위반인가요?"
        cases = {"기본급 경로": (dict(self.PARAMS), self.Q36, "통상시급: 10,051원"),
                 "C8 경로": (dict(self.PARAMS, wage_amount=2096270), self.Q36, "통상시급: 10,051원"),
                 "미진술": (dict(self.PARAMS), plain, "통상시급: 12,945원")}
        for name, (params, query, line) in cases.items():
            with self.subTest(name):
                out = _run_calculator(params, query)
                self.assertIn(line, out)
                self.assertNotIn("월급 총액 기준 시급", out)
                self.assertIn("[통상임금] 월 기본급:", out)

    def test_t5_hourly_label_defaults_to_the_ordinary_hourly_wage(self):
        """라벨은 기본값이 '통상시급'이고 기본값일 때는 출력이 달라지지 않는다(JSON에도 키를 더하지 않는다)."""
        from wage_calculator.result import WageResult, format_result, format_result_json
        result = WageResult(ordinary_hourly=15000, minimum_wage_ok=True)
        self.assertEqual(result.hourly_label, "통상시급")
        self.assertIn("통상시급: 15,000원", format_result(result))
        self.assertNotIn("hourly_label", format_result_json(result))
        result.hourly_label = "월급 총액 기준 시급"
        self.assertIn("월급 총액 기준 시급: 15,000원", format_result(result))
        self.assertEqual(format_result_json(result)["hourly_label"], "월급 총액 기준 시급")



class CalculatorFactTest(unittest.TestCase):
    """T7 — 계산기의 법적 근거 표기와 금액 절사(Act-3, 공식 원문 대조 2026-10-12: 근로기준법 2026-10-08 시행판)."""

    def test_t7_average_wage_floor_cites_the_act_not_the_decree(self):
        """'평균임금이 통상임금보다 적으면 통상임금'은 근로기준법 제2조 제2항이다 — 계산기가 시행령 제2조(평균임금 계산에서
        제외되는 기간과 임금)로 적어 그 표기가 카드의 법적 근거로 LLM에 들어갔다."""
        from wage_calculator import WageCalculator, WageInput, WageType
        from wage_calculator.result import format_result
        inp = WageInput(wage_type=WageType.MONTHLY, monthly_wage=2700000, reference_year=2026,
                        start_date="2023-03-01", end_date="2026-10-01")
        out = format_result(WageCalculator().calculate(inp, ["average_wage", "severance"]))
        self.assertIn("근로기준법 제2조 제2항 (평균임금이 통상임금보다 적으면 통상임금)", out)
        self.assertNotIn("시행령 제2조 (평균임금 <", out)
        # 경고문의 괄호 근거와 흐름도 '유리한 원칙' 탭도 같은 조문이다(Act-3 리뷰 L1). 시행령 제2조는 제외기간 설명에만 남는다
        self.assertIn("통상임금 적용 (근로기준법 제2조 제2항)", out)
        for html in ("wage_calculator/calculator_flow/average_wage_calculation_flow.html",
                     "public/calculator_flow/average_wage_calculation_flow.html"):
            with self.subTest(html):
                text = (ROOT / html).read_text(encoding="utf-8")
                self.assertIn(">근로기준법 제2조 제2항·대법원 2023다302579 | 근로자 보호를 위해 가장 유리한 기준을 적용<", text)
                self.assertNotIn(">시행령 제2조 | 근로자 보호를 위해", text)

    def test_t7_shutdown_allowance_cap_cites_the_proviso(self):
        """휴업수당의 통상임금 상한은 근로기준법 제46조 제1항 단서다(제2항은 노동위원회 승인 시 기준 미달 지급). 흐름도
        두 사본도 같은 표기여야 한다."""
        from wage_calculator import WageCalculator, WageInput, WageType
        from wage_calculator.models import BusinessSize
        from wage_calculator.result import format_result
        inp = WageInput(wage_type=WageType.MONTHLY, monthly_wage=1500000, monthly_total_pay=3000000,
                        business_size=BusinessSize.OVER_5, reference_year=2026, shutdown_days=10,
                        start_date="2023-03-01", end_date="2026-10-01")
        out = format_result(WageCalculator().calculate(inp, ["shutdown_allowance"]))
        self.assertIn("통상임금 적용", out)                      # 평균임금 70%(22,826원 × 10) > 통상임금 → 상한
        self.assertIn("근로기준법 제46조 제1항 단서", out)
        self.assertNotIn("제46조 제2항", out)
        for html in ("wage_calculator/calculator_flow/shutdown_allowance_calc.html",
                     "public/calculator_flow/shutdown_allowance_calc.html"):
            with self.subTest(html):
                text = (ROOT / html).read_text(encoding="utf-8")
                self.assertIn("제46조 제1항 단서", text)
                self.assertNotIn("제46조 제2항", text)

    def test_t7_insurance_premium_truncation_is_not_cut_by_float_error(self):
        """원 미만 절사 전에 부동소수 오차를 걷어낸다 — 2,700,000 × 0.9%가 24,299.999…가 되어 고용보험료가 24,299원이었다."""
        from wage_calculator import WageCalculator, WageInput, WageType
        from wage_calculator.calculators.insurance import _floor_won
        from wage_calculator.result import format_result
        self.assertEqual(_floor_won(2700000 * 0.009), 24300)
        self.assertEqual(_floor_won(24299.6), 24299)                 # 절사 자체는 그대로
        out = format_result(WageCalculator().calculate(
            WageInput(wage_type=WageType.MONTHLY, monthly_wage=2700000, reference_year=2026), ["insurance"]))
        self.assertIn("고용보험: 2,700,000원 × 0.9% = 24,300원", out)


    def test_t7_annual_leave_and_overtime_pay_are_not_ordinary_wage_or_minimum_wage(self):
        """연차 유급휴가 미사용수당은 최저임금 비산입이다(최저임금법 시행규칙 제2조 제1항 제2호, 공식 원문 대조 2026-10-12) —
        분류기가 '연차수당'을 전액산입으로 셌다. 연장·야간·휴일근로·연차수당은 통상임금도 아니다(시행령 제6조 제1항 '소정근로'
        의 대가 — 제56조 가산임금·제60조 제5항 휴가임금은 통상임금으로 계산한다). 조건 '없음'이면 통상임금으로 자동 판정돼 통상시급이
        부풀었다(audit-50 Act-4). '유급휴일수당'은 주휴분일 수 있어 이름만으로 빼지 않는다."""
        from wage_calculator import WageCalculator, WageInput, WageType
        from wage_calculator.calculators.shared import AllowanceClassifier as C
        for name in ("연차수당", "미사용 연차수당", "시간외근로수당", "잔업수당", "포괄수당"):
            with self.subTest(name):
                self.assertEqual(C.classify_min_wage_type(name), "excluded")
                self.assertTrue(C.is_not_ordinary_by_name(name))
        self.assertFalse(C.is_overtime_related("연차수당"))           # 연장근로 판정에는 넣지 않는다
        for name in ("유급휴일수당", "주휴수당", "휴일수당", "직책수당"):
            with self.subTest(ordinary=name):
                self.assertFalse(C.is_not_ordinary_by_name(name))
        self.assertTrue(C.is_not_ordinary_by_name("휴일 근무수당"))
        inp = WageInput(wage_type=WageType.MONTHLY, monthly_wage=2000000, reference_year=2026, fixed_allowances=[
            {"name": "연차수당", "amount": 200000, "condition": "없음"},
            {"name": "고정연장수당", "amount": 300000, "condition": "재직조건"},
            {"name": "직책수당", "amount": 100000, "condition": "없음"}])
        r = WageCalculator().calculate(inp, ["ordinary_wage", "minimum_wage"])
        self.assertEqual(r.ordinary_hourly, round(2100000 / (48 * 365 / 7 / 12), 2))
        formula = next(f for f in r.formulas if f.startswith("[통상임금]"))
        self.assertIn("= 2,100,000원 (통상임금 제외: 연차수당 200,000원, 고정연장수당 300,000원 — 소정근로의 대가가 아닌", formula)
        self.assertEqual(r.breakdown["최저임금 검증"]["  연차수당"], "200,000원/월  [비산입(연차수당)]")
        self.assertEqual(r.breakdown["최저임금 검증"]["산입 월 임금 합계"], "2,100,000원")
        # 명시적으로 통상임금이라고 한 값은 존중한다
        explicit = WageInput(wage_type=WageType.MONTHLY, monthly_wage=2000000, reference_year=2026, fixed_allowances=[
            {"name": "야간근무수당", "amount": 100000, "condition": "없음", "is_ordinary": True}])
        self.assertIn("통상임금 포함 수당 100,000원", WageCalculator().calculate(explicit, ["ordinary_wage"]).formulas[1])

    def test_t7_analyzer_overtime_allowance_outside_the_exact_path_is_not_ordinary_wage(self):
        """구성 진술이 없는 질문에서도 의도분석이 뽑은 고정연장수당은 통상임금에 넣지 않는다 — Act-3은 정확 경로에서만 막았다."""
        from app.core.pipeline import _run_calculator
        params = {"needs_calculation": True, "wage_type": "월급", "wage_amount": 2500000, "weekly_work_days": 5,
                  "daily_work_hours": 8, "weekly_overtime_hours": 5, "reference_year": 2026, "business_size": "5인이상",
                  "calculation_types_kr": ["연장수당"],
                  "fixed_allowances": [{"name": "고정연장수당", "amount": 300000, "condition": "없음"}]}
        out = _run_calculator(params, "월급 250만원 받고 고정연장수당 30만원은 따로 나옵니다. 주 5시간 연장근로하면 수당이 얼마인가요?")
        self.assertIn("통상시급: 11,986원", out)                       # 2,500,000 ÷ 208.5714h — 2,800,000이면 13,425원
        self.assertIn("통상임금 제외: 고정연장수당 300,000원", out)


    def test_t7_hourly_wage_equal_to_the_minimum_is_never_short(self):
        """시급이 최저임금과 같으면 어떤 근무형태든 '충족'이다 — 월 기준시간을 반올림하지 않게 되자 (시급 × h) ÷ h가 부동소수
        오차로 10,319.999…가 되어 '미달, 부족분 0원'이 났다(Act-4 리뷰 H1: 2025년 주 6일 × 8시간, 2026년 7일 × 6.5시간 등)."""
        from wage_calculator import WageCalculator, WageInput, WageType
        from wage_calculator.constants import MINIMUM_HOURLY_WAGE
        from wage_calculator.models import WorkSchedule
        short = []
        for year in (2025, 2026, 2027):
            for days in range(1, 8):
                for half in range(2, 25):
                    inp = WageInput(wage_type=WageType.HOURLY, hourly_wage=MINIMUM_HOURLY_WAGE[year], reference_year=year,
                                    schedule=WorkSchedule(daily_work_hours=half / 2, weekly_work_days=days))
                    if WageCalculator().calculate(inp, ["minimum_wage"]).minimum_wage_ok is not True:
                        short.append((year, days, half / 2))
        self.assertEqual(short, [])

    def test_t7_monthly_wage_between_the_statutory_hours_and_the_notice_hours_is_flagged(self):
        """고시의 월 환산액은 주 40시간 근무자를 209시간 기준으로 적는다(고시 본문). 계산은 시행령 산식(208.5714시간)이라 그 사이
        월급은 카드가 '충족'이어도 고시 환산액에 못 미친다 — 판정만 내면 사실 블록과 한 답변 안에서 갈렸다(Act-4 리뷰 M5)."""
        from wage_calculator import WageCalculator, WageInput, WageType
        for wage, flagged in ((2153000, True), (2156880, False), (2152000, False)):
            with self.subTest(wage=wage):
                r = WageCalculator().calculate(WageInput(wage_type=WageType.MONTHLY, monthly_wage=wage, reference_year=2026),
                                               ["minimum_wage"])
                self.assertIs(r.minimum_wage_ok, wage >= 2152458)
                self.assertEqual(any("고시의 월 환산액 2,156,880원" in w for w in r.warnings), flagged)
        hourly = WageCalculator().calculate(WageInput(wage_type=WageType.HOURLY, hourly_wage=10320, reference_year=2026),
                                            ["minimum_wage"])
        self.assertFalse(any("고시의 월 환산액" in w for w in hourly.warnings))
        # 수습 감액(90%)이면 고시 환산액과 비교하지 않는다 — 고시 금액은 감액 전 금액이다
        probation = WageCalculator().calculate(WageInput(wage_type=WageType.MONTHLY, monthly_wage=1940000, reference_year=2026,
                                                         is_probation=True, probation_months=3), ["minimum_wage"])
        self.assertIs(probation.minimum_wage_ok, True)          # 1,940,000 ÷ 208.5714h = 9,301원 ≥ 9,288원
        self.assertFalse(any("고시의 월 환산액" in w for w in probation.warnings))
        # 사실 블록도 같은 사정을 밝힌다(카드 판정과 209시간 환산액이 한 답변 안에서 갈리지 않게)
        from app.core.pipeline import _build_minwage_facts
        analysis = type("A", (), {"calculation_types": ["minimum_wage"], "relevant_laws": [], "extracted_info": {},
                                  "consultation_topic": "minimum_wage", "question_type": "wage"})()
        facts = _build_minwage_facts("최저임금 월급은 얼마인가요?", analysis)
        self.assertIn("월급 환산액은 고시의 표기(주 40시간 근무, 월 209시간 기준)입니다", facts)
        found = re.search(r"(\d{4})년 기준 월 ([\d,]+)원 이상 ([\d,]+)원 미만이면 카드는 '충족'이어도 고시 환산액보다 적습니다", facts)
        self.assertIsNotNone(found)
        from wage_calculator.constants import MINIMUM_HOURLY_WAGE
        hourly = MINIMUM_HOURLY_WAGE[int(found.group(1))]
        self.assertEqual(int(found.group(2).replace(",", "")), math.ceil(hourly * 48 * 365 / 7 / 12))   # 첫 충족 금액
        self.assertEqual(int(found.group(3).replace(",", "")), hourly * 209)

    def test_t7_name_exclusions_keep_the_monthly_total_and_label_the_rows(self):
        """이름으로 통상임금에서 뺀 고정수당도 매월 받는 돈이라 '월 총 예상 수령액'에 남는다(Act-4 리뷰 L8). 최저임금 행은
        초과수당·연차수당·주휴일 외 유급휴일 임금을 구분해 적는다(L7). 초과·OT·심야·주말근무수당도 비산입·통상임금 제외이고,
        '계약연장'·'근속연차'는 다른 뜻이다(M2). 교대제 고정수당은 통상임금에서 이름만으로 빼지 않는다."""
        from wage_calculator import WageCalculator, WageInput, WageType
        from wage_calculator.calculators.shared import AllowanceClassifier as C
        for name in ("초과근무수당", "고정 OT 수당", "고정ot수당", "오티수당", "심야수당", "주말근무수당", "주말 근무수당",
                     "주말 출근수당", "시간 외 수당"):
            with self.subTest(name):
                self.assertEqual(C.classify_min_wage_type(name), "excluded")
                self.assertTrue(C.is_not_ordinary_by_name(name))
        for name in ("계약연장수당", "정년연장수당", "근속연차수당", "연차별 수당", "교대수당", "IoT 자격수당", "PILOT수당",
                     "목표초과달성수당"):
            with self.subTest(standard=name):
                self.assertEqual(C.classify_min_wage_type(name), "standard")
                self.assertFalse(C.is_not_ordinary_by_name(name))
        self.assertFalse(C.is_not_ordinary_by_name("야간교대수당"))
        self.assertEqual(C.classify_min_wage_type("야간교대수당"), "excluded")
        inp = WageInput(wage_type=WageType.MONTHLY, monthly_wage=2000000, reference_year=2026, fixed_allowances=[
            {"name": "고정연장수당", "amount": 300000, "condition": "없음"},
            {"name": "연차수당", "amount": 100000, "condition": "없음"},
            {"name": "유급휴일수당", "amount": 50000, "condition": "없음"}])
        r = WageCalculator().calculate(inp, ["minimum_wage"])
        self.assertEqual(r.monthly_total, 2450000)          # 통상임금 2,050,000(유급휴일수당 포함) + 제외 수당 400,000
        rows = r.breakdown["최저임금 검증"]
        self.assertEqual(rows["  고정연장수당"], "300,000원/월  [비산입(초과수당)]")
        self.assertEqual(rows["  연차수당"], "100,000원/월  [비산입(연차수당)]")
        self.assertEqual(rows["  유급휴일수당"], "50,000원/월  [비산입(주휴일 외 유급휴일 임금 — 주휴수당이면 산입)]")


class MonthlyHoursTest(unittest.TestCase):
    """T8 — 월 환산 시간은 반올림하지 않는다(최저임금법 시행령 제5조①3호: 1주 기준시간 × 1년 평균 주 수 ÷ 12). 외부 점검 #45가
    83.4286h를 83.4h로 먼저 반올림해 낸 860,688원(맞는 값 860,983원)을 지적했다 — audit-50 Act-4."""

    def test_t8_part_time_monthly_amount_is_not_rounded_in_between(self):
        from app.core.pipeline import _run_calculator
        params = {"needs_calculation": True, "wage_type": "시급", "wage_amount": 10320, "weekly_work_days": 2,
                  "daily_work_hours": 8, "weekly_total_hours": 16, "reference_year": 2026, "business_size": "5인이상",
                  "calculation_types_kr": ["주휴수당", "최저임금"]}
        out = _run_calculator(params, "주말 2일 8시간씩 16시간 일하고 시급 10,320원입니다. 주휴수당 계산이 맞나요?")
        self.assertIn("월 환산: (16h+3.2h)×365÷7÷12 = 83.4286h", out)
        self.assertIn("시급 10,320원 × 83.4286h = 860,983원", out)
        self.assertIn("월 주휴수당: 33,024원 × (365÷7÷12) = 143,497원", out)    # 표시값으로 다시 계산해도 같다
        self.assertNotIn("860,688", out)
        self.assertNotIn("4.345 =", out)

    def test_t8_full_time_monthly_hours_and_comprehensive_coefficients(self):
        from wage_calculator import WageCalculator, WageInput, WageType
        from wage_calculator.models import BusinessSize, WorkSchedule
        from wage_calculator.result import format_result
        out = format_result(WageCalculator().calculate(
            WageInput(wage_type=WageType.MONTHLY, monthly_wage=2096270, reference_year=2026), ["minimum_wage"]))
        self.assertIn("실질시급: 2,096,270원 ÷ 208.5714h = 10,050.61원", out)
        comp = format_result(WageCalculator().calculate(
            WageInput(wage_type=WageType.COMPREHENSIVE, monthly_wage=2000000, reference_year=2026, business_size=BusinessSize.OVER_5,
                      schedule=WorkSchedule(daily_work_hours=8, weekly_work_days=5, weekly_overtime_hours=10)),
            ["comprehensive"]))
        # 역산 시급은 반올림하지 않은 계수시간으로 나눈다(273.75h — 반올림하면 273.8h)
        self.assertIn("역산 기본시급: 2,000,000원 ÷ 273.75h = 7,306원", comp)

    def test_t8_displayed_figures_recompute_to_the_card_amounts(self):
        """계산식의 표시값으로 다시 계산하면 카드 금액이 나와야 한다 — 주휴시간을 소수 첫째 자리로(3.25h → 3.2h), 주휴수당 주액을
        원 단위로(95,890원) 줄여 적어 다시 계산한 값이 어긋났다(Act-4 리뷰 L1·L2)."""
        import re as _re
        from wage_calculator import WageCalculator, WageInput, WageType
        from wage_calculator.models import WorkSchedule
        from wage_calculator.utils import WEEKS_PER_MONTH
        r = WageCalculator().calculate(WageInput(wage_type=WageType.HOURLY, hourly_wage=10320, reference_year=2026,
                                                 schedule=WorkSchedule(daily_work_hours=3.25, weekly_work_days=5)),
                                       ["weekly_holiday"])
        self.assertIn("월 환산: (16.25h+3.25h)×365÷7÷12 = 84.7321h", r.formulas[0])
        r = WageCalculator().calculate(WageInput(wage_type=WageType.MONTHLY, monthly_wage=2000000, reference_year=2026,
                                                 schedule=WorkSchedule(daily_work_hours=7, weekly_work_days=3)),
                                       ["weekly_holiday"])
        line = next(f for f in r.formulas if f.startswith("월 주휴수당:"))
        weekly, monthly = _re.match(r"월 주휴수당: ([\d,.]+)원 × \(365÷7÷12\) = ([\d,]+)원", line).groups()
        self.assertEqual(round(float(weekly.replace(",", "")) * WEEKS_PER_MONTH), int(monthly.replace(",", "")))

    def test_t8_hours_display(self):
        from wage_calculator.utils import fmt_hours
        self.assertEqual(fmt_hours(209.0), "209")
        self.assertEqual(fmt_hours(48 * 365 / 7 / 12), "208.5714")
        self.assertEqual(fmt_hours(19.2 * 365 / 7 / 12), "83.4286")
        self.assertEqual(fmt_hours(273.75), "273.75")


class ScheduleHoursTest(unittest.TestCase):
    """T10 — 외부 점검 40번 후속(계산 카드). 질문은 '주 6일, 시급 12,000원, 9월 28일~30일 3일 동안 25시간'뿐인데 카드가
    소정근로시간을 지어냈다 — Act-6 18회 중 10회는 기본값 1일 8시간으로 '8h×6일 = 48h'(주휴수당 월 417,143원·월 총액
    2,920,000원), 8회는 의도분석이 실근로 합계 25시간을 주 소정근로시간으로 옮겨 '4.1667h×6일 = 25h'였고, 그 카드에는
    기준시간 주휴 5h(통상임금 계산기 ÷5)와 주휴수당 4.1667h(주휴수당 계산기)가 함께 실렸다. 주휴시간 산식이 계산기 네 곳에
    따로 있었다(포괄임금 역산은 주 5일 미만에도 1일 시간)."""

    Q40 = ("주 6일, 시급 12,000원으로 일합니다. 9월 28일~30일 3일 동안 25시간 일했는데, 앞 주에 주휴수당이 나갔다고 "
           "3일치는 주휴가 나올 수 없다고 합니다. 10월 1일부터도 계속 출근하고 있습니다. 맞는 건가요?")
    P40 = {"needs_calculation": True, "calculation_types_kr": ["주휴수당"], "wage_type": "시급", "wage_amount": 12000,
           "weekly_work_days": 6, "reference_year": 2026}
    ASSUMED = ("8h×6일", "48h", "4.1667h×6일", "417,143", "2,920,000", "217,262", "1,564,286", "50,000원/주",
               "월 총 예상 수령액", "주휴수당(월)")

    def test_t10_one_holiday_formula_across_calculators(self):
        """통상임금 기준시간·주휴수당·소정근로시간·포괄임금 역산이 같은 주휴시간을 쓴다."""
        from wage_calculator import WageInput, WageType
        from wage_calculator.calculators.comprehensive import _calc_coefficient_hours
        from wage_calculator.calculators.ordinary_wage import calc_ordinary_wage
        from wage_calculator.calculators.shared import weekly_holiday_hours
        from wage_calculator.calculators.weekly_holiday import calc_weekly_holiday
        from wage_calculator.calculators.working_hours import calc_working_hours
        from wage_calculator.models import BusinessSize, WorkSchedule
        from wage_calculator.utils import WEEKS_PER_MONTH
        checked = 0
        for days in (1, 2, 3, 4, 5, 5.5, 6, 7):
            for quarter in range(2, 49):
                daily = quarter / 4
                weekly = days * daily
                if weekly < 15:
                    continue
                inp = WageInput(wage_type=WageType.HOURLY, hourly_wage=12000, business_size=BusinessSize.OVER_5,
                                schedule=WorkSchedule(daily_work_hours=daily, weekly_work_days=days))
                hours = weekly_holiday_hours(days, daily)[0]
                ow = calc_ordinary_wage(inp)
                case = (days, daily)
                self.assertAlmostEqual(ow.monthly_base_hours, (weekly + hours) * WEEKS_PER_MONTH, places=6, msg=case)
                self.assertAlmostEqual(calc_weekly_holiday(inp, ow).holiday_hours, hours, places=9, msg=case)
                self.assertAlmostEqual(calc_working_hours(inp, ow).weekly_paid_hours, weekly + hours, places=9, msg=case)
                self.assertAlmostEqual(_calc_coefficient_hours(inp)[1]["기본시간"], (weekly + hours) * WEEKS_PER_MONTH,
                                       places=6, msg=case)
                checked += 1
        self.assertGreater(checked, 200)
        # 포괄임금 흐름도(브라우저 계산)도 같은 산식 — 예전에는 '÷5'만 써서 계산기(1일 시간)와도 달랐다
        for html in ("public/calculator_flow/comprehensive_wage_reverse_calc.html",
                     "wage_calculator/calculator_flow/comprehensive_wage_reverse_calc.html"):
            src = (ROOT / html).read_text(encoding="utf-8")
            self.assertIn("Math.min(weekly / Math.max(days, 5), 8)", src, html)
            self.assertNotIn("Math.min(weekly / 5, 8)", src, html)

    def test_t10_holiday_hours_follow_the_supreme_court_rule(self):
        """대법원 2022다291153: 1일 평균 소정근로시간(1주 소정 ÷ 1주 소정근로일 수)이 원칙, 5일 미만은 5일로 보아 나눈다."""
        from wage_calculator.calculators.shared import weekly_holiday_hours
        for (days, daily), hours in {(6, 25 / 6): 25 / 6, (6, 6): 6, (6, 40 / 6): 40 / 6, (6, 8): 8, (5, 8): 8,
                                     (5, 3.25): 3.25, (3, 6): 3.6, (2, 8): 3.2, (4, 10): 8, (7, 4): 4, (5, 9): 8, (6, 10): 8}.items():
            self.assertAlmostEqual(weekly_holiday_hours(days, daily)[0], hours, places=9, msg=(days, daily))
        self.assertEqual(weekly_holiday_hours(6, 25 / 6)[1], "주 소정근로일 6일 ≥ 5일 → 주휴: min(4.1667h, 8h) = 4.1667h")
        self.assertEqual(weekly_holiday_hours(3, 6)[1], "주 소정근로일 3일 < 5일 → 주휴: min(18h ÷ 5, 8h) = 3.6h (= 18h ÷ 40h × 8h — 1주 소정근로일을 5일로 봄)")

    def test_t10_card_for_question_40_assumes_no_hours(self):
        from app.core.pipeline import _calculation_context_heading, _run_calculator
        for name, extra in {"근무일수만": {}, "실근로 합계를 주 소정으로": {"weekly_total_hours": 25},
                            "실근로 합계를 1일로 나눔": {"daily_work_hours": 25 / 3}}.items():
            with self.subTest(name):
                params = dict(self.P40, **extra)
                out = _run_calculator(params, self.Q40)
                for text in self.ASSUMED:
                    self.assertNotIn(text, out)
                for text in ("최저임금 충족: ✅ 충족", "주휴수당 = 시급 12,000원 × 주휴시간",
                             "주휴시간 = 1주 소정근로시간 ÷ 1주 소정근로일 6일(1일 평균 소정근로시간, 8시간 한도)",
                             "4주 평균 1주 소정근로시간 15시간 이상", "근로기준법 시행령 별표 2 제2호나목",
                             "금액 보류: 질문에 1일·1주 소정근로시간이 없어 다음은 계산하지 않았습니다 — 주휴시간·주휴수당.",
                             "[기준시간] 소정근로시간 미확인", "실질시급: 시급 12,000원"):
                    self.assertIn(text, out)
                self.assertIn("추정하지 마세요", _calculation_context_heading(out))
                self.assertEqual(bool(extra), "질문의 25시간은 그 기간에 실제로 일한 시간이라 소정근로시간으로 쓰지 않았습니다" in out)
                self.assertNotIn("8.3333", out)
                self.assertEqual(params.get("schedule_hours_rejected"), extra or None)

    def test_t10_card_via_analysis_conversion_drops_derived_weekly_total(self):
        """의도분석 → params 변환(_analysis_to_extract_params)은 주 합계가 없으면 1일 × 근무일수로 채운다. 1일(25 ÷ 3)을 버려도 그
        곱(50)이 남아 카드가 '8.3333h×6일 = 50h'로 계산했다(CodeRabbit PR #114). 의도분석이 반올림한 1일(8.3)은 곱의 오차가 커진다."""
        from types import SimpleNamespace
        from app.core.pipeline import _analysis_to_extract_params, _run_calculator
        cases = {"1일 = 25 ÷ 3": ({"daily_work_hours": 25 / 3}, ("8.3333", "50h")),
                 "반올림 8.33": ({"daily_work_hours": 8.33}, ("8.33h", "49.98h")),
                 "반올림 8.3": ({"daily_work_hours": 8.3}, ("8.3h", "49.8h")),
                 "주 합계를 바로 50으로": ({"weekly_total_hours": 50}, ("8.3333", "50h")),
                 "주 합계를 바로 49.8로": ({"weekly_total_hours": 49.8}, ("8.3h", "49.8h"))}
        for name, (extra, derived) in cases.items():
            with self.subTest(name):
                info = dict({k: v for k, v in self.P40.items() if k not in ("needs_calculation", "calculation_types_kr")},
                            **extra)
                params = _analysis_to_extract_params(SimpleNamespace(
                    extracted_info=info, requires_calculation=True, calculation_types=["weekly_holiday"]))
                out = _run_calculator(params, self.Q40)
                for text in self.ASSUMED + derived:
                    self.assertNotIn(text, out)
                for text in ("[기준시간] 소정근로시간 미확인",
                             "질문의 25시간은 그 기간에 실제로 일한 시간이라 소정근로시간으로 쓰지 않았습니다"):
                    self.assertIn(text, out)
                self.assertEqual(set(params["schedule_hours_rejected"]), {"weekly_total_hours", *extra})

    def test_t10_span_totals_are_not_scheduled_hours(self):
        """기간 표지('N일 동안'·'28일~30일'·'이번 주'·'어제'·'N일 근무했다')와 같은 절의 시간은 소정근로시간 근거가 아니다."""
        from app.core.pipeline import _ground_schedule_hours as ground
        rejected = {
            "9월 28일~30일 3일 동안 25시간 일했는데 주휴수당이 안 나온대요": (25, None, 6),
            "3일 동안 25시간 일했어요": (None, 25 / 3, None),
            "28일부터 30일까지 총 25시간 일했습니다": (25, None, None),
            "이번 주에 30시간 일했어요. 주휴수당 받나요?": (30, None, None),
            "지난주 42시간 근무했는데 연장수당 나오나요?": (42, None, 5),
            "어제 10시간 일했어요": (None, 10, None),
            "2주 동안 50시간 일했어요": (50, None, None),
            "하루 6시간씩 3일 근무했다": (18, 6, 3),         # CLAUDE.md 함정 ③ — 실제 근무
            "9/28~30 25시간 일했어요": (25, None, 6),        # 날짜 범위 표기 셋
            "9월 28~30일 25시간 일했어요": (25, None, 6),
            "9/28부터 9/30까지 25시간 일했는데요": (25, None, 6),
            "11시간씩 6일 근무했어요": (66, 11, 6),          # 1일 소정근로시간은 8시간을 넘지 못한다 — 실근무 서술
            # 독립 리뷰 M3 — 월을 넘는 범위, 계획어가 앞에 있는 실근로, 고유어 일수, 'h' 단위, 점 표기
            "9월 28일부터 10월 1일까지 30시간 일했어요": (30, None, 6),
            "스케줄이 바뀌어서 이번 주 3일 동안 25시간 일했어요": (25, None, 6),
            "1주일 동안 25시간 일했어요": (25, None, 6),
            "사흘 동안 25시간 일했어요": (25, None, 6),
            "3일 동안 25h 일했어요": (25, None, 6),
            "9.28~9.30 25시간 일했어요": (25, None, 6),
        }
        for query, (weekly, daily, days) in rejected.items():
            with self.subTest(query):
                self.assertEqual(ground(query, weekly, daily, days),
                                 (None, None, {k: v for k, v in (("weekly_total_hours", weekly),
                                                                 ("daily_work_hours", daily)) if v is not None}))
        kept = {
            "주 25시간 일해요": (25, None, 6),
            "하루 8시간씩 주 6일 근무합니다": (48, 8, 6),
            "주 6일, 하루 8시간 근무인데 이번 주 3일 동안 25시간 일했어요": (48, 8, 6),
            "주 3일 하루 6시간씩 근무했어요": (18, 6, 3),
            "주 3일 동안 하루 4시간 30분 일해요": (13.5, 4.5, 3),
            "평일 9시부터 18시까지 주 5일 근무": (40, 8, 5),     # 'N시간' 표현이 없으면 대조하지 않는다
            "주 25시간 일하는데 이번 주는 30시간 일했어요": (25, None, None),
            "그 주휴수당은 하루 8시간 기준인가요? 3일 동안 쉬었어요": (None, 8, 5),
            "이번주에 15시간을 스케줄에 넣어뒀는데 주휴 받을 수 있나요": (15, None, None),   # 근무표의 계획 시간
            "이번 주 근무표에 20시간 배정됐어요": (20, None, None),
            "주휴시간을 3.2시간으로 산정하셨습니다. 하루 8시간 주 2일입니다": (16, 8, 2),     # 소수점에서 절을 끊지 않는다
            "주 3~4일 하루 5시간씩 일해요": (None, 5, None),
            "하루 4.5시간씩 주 4일 일해요": (18, 4.5, 4),
            # 독립 리뷰 H1 — 출퇴근 시각에서 구한 1일 8시간, 기간 동안의 1주 근무 형태, 평일·주말 합계
            "9시부터 18시까지(점심 1시간), 주 5일 근무합니다. 지난주 연장근로 10시간 했는데 수당은?": (40, 8, 5),
            "1년 6개월 동안 주 15시간씩 일했는데 퇴직금 받나요?": (15, None, None),
            "4주 동안 평균 주 16시간 일했어요": (16, None, None),
            "이번 주에 주 20시간으로 계약했어요": (20, None, None),
            "평일 4시간, 주말 8시간 일하는데 지난주 28시간 일했어요": (36, None, 7),
            "3개월 동안 하루 4시간씩 주 5일 일했어요": (20, 4, 5),
            "근로계약서상 하루 8시간인데 지난주 52시간 일했어요": (40, 8, 5),
            # 기간 합계와 같은 값이어도 기간 밖의 시간(그 × 근무일수 포함)이 뒷받침하면 쓴다
            "주 25시간 계약인데 이번 주 3일 동안도 25시간 일했어요": (25, None, 6),
            "하루 5시간씩 주 5일 일하는데 이번 주 3일 동안 25시간 일했어요": (25, 5, 5),
            "이번 주는 계약상 30시간이에요": (30, None, None),       # 계획어가 시간 앞에 있다
        }
        for query, (weekly, daily, days) in kept.items():
            with self.subTest(query):
                self.assertEqual(ground(query, weekly, daily, days), (weekly, daily, {}))
        # 값마다 따로 본다 — 의도분석이 기간 합계(30)를 주 소정으로 골랐으면 그것만 버리고 질문의 1일 시간은 남긴다
        self.assertEqual(ground("주 25시간 일하는데 이번 주는 30시간 일했어요", 30, None, None),
                         (None, None, {"weekly_total_hours": 30}))
        # 소수점 절 분리 결함 — '3.2시간'이 '3' | '2시간'으로 갈려 '2시간'이 '4주간' 절의 기간 합계로 잡혔다
        from app.core.pipeline import _hours_mentions
        self.assertEqual(_hours_mentions("주휴시간을 3.2시간으로 산정하셨습니다 이에 따라 4주간 총 12.8시간입니다"),
                         [(3.2, True, ()), (12.8, True, ())])
        self.assertEqual(_hours_mentions("하루 4시간 30분, 주 3일 2시간 반"), [(4.5, False, ()), (2.5, False, ())])
        # 기간 일수 — 의도분석이 합계를 그 일수로 나눈 1일 시간(25 ÷ 3)도 기간 합계에서 나온 값이다
        self.assertEqual(_hours_mentions("9월 28일~30일 3일 동안 25시간 일했는데"), [(25.0, True, (3, 3))])
        self.assertEqual(ground("주 6일, 하루 8시간 근무인데 이번 주 3일 동안 25시간 일했어요", 25, 8, 6),
                         (None, 8, {"weekly_total_hours": 25}))
        # 주 합계는 근무일수로 나눈 1일 값으로도 대조한다 — 기간 1일 평균 × 근무일수(25 ÷ 3 × 6 = 50), 반올림한 1일을 곱한 값(8.3 × 6
        # = 49.8, 50에서 0.2 떨어진다)도 기간 합계에서 나온 값이다(CodeRabbit PR #114)
        span40 = "9월 28일~30일 3일 동안 25시간 일했는데 주휴수당이 안 나온대요"
        for weekly in (50, 49.98, 49.8):
            self.assertEqual(ground(span40, weekly, None, 6), (None, None, {"weekly_total_hours": weekly}), weekly)
        self.assertEqual(ground(span40, 50, 25 / 3, 6), (None, None, {"weekly_total_hours": 50, "daily_work_hours": 25 / 3}))
        self.assertEqual(ground(span40, 49.8, 8.3, 6), (None, None, {"weekly_total_hours": 49.8, "daily_work_hours": 8.3}))
        # 기간 밖 1일 시간(8시간 20분)이 뒷받침하면 같은 값이어도 쓴다 — 근거 쪽도 근무일수로 나눈 1일 값으로 본다
        q820 = "주 6일 하루 8시간 20분 근무인데 9월 28일~30일 3일 동안 25시간 일했어요"
        self.assertEqual(ground(q820, 50, 25 / 3, 6), (50, 25 / 3, {}))
        self.assertEqual(ground(q820, 49.8, 8.3, 6), (49.8, 8.3, {}))
        # 1일을 버려도 그 곱이 아닌 주 합계(질문의 계약 48시간)는 남긴다
        self.assertEqual(ground("주 48시간 계약인데 9월 28일~30일 3일 동안 25시간 일했어요", 48, 25 / 3, 6),
                         (48, None, {"daily_work_hours": 25 / 3}))
        # 앞 턴 캐시에서 채운 값은 이번 질문의 기간 표현으로 버리지 않는다(그 턴에서 대조했다) — 1일 × 근무일수도 같다
        self.assertEqual(ground("이번 주 3일 동안 25시간 일했는데 주휴수당 나오나요?", 40, 8, 5, trusted=("daily_work_hours",)),
                         (40, 8, {}))
        self.assertEqual(ground("이번 주 3일 동안 25시간 일했는데 주휴수당 나오나요?", 25, 8, 5, trusted=("daily_work_hours",)),
                         (None, 8, {"weekly_total_hours": 25}))
        # 캐시 값이 기간 합계에서 나온 값(25 ÷ 5일)과 우연히 같아도 버리지 않는다 — 캐시 값과 그 × 근무일수가 근거다
        self.assertEqual(ground("이번 주 5일 동안 25시간 일했어요", 25, 5, 5, trusted=("daily_work_hours",)), (25, 5, {}))
        self.assertEqual(ground("이번 주 5일 동안 25시간 일했어요", 25, 5, 5),
                         (None, None, {"weekly_total_hours": 25, "daily_work_hours": 5}))

    def test_t10_rejected_hours_leave_the_cache_and_are_asked_for(self):
        """버린 값은 계산 캐시(extracted_info)에서 빠진다 — 남으면 다음 턴 프리필이 대조 없이 그 값을 다시 채운다."""
        from types import SimpleNamespace
        from app.core.pipeline import _note_rejected_hours, _run_calculator
        params = dict(self.P40, weekly_total_hours=25)
        analysis = SimpleNamespace(extracted_info={"wage_amount": 12000, "weekly_work_days": 6, "weekly_total_hours": 25},
                                   missing_info=[])
        _run_calculator(params, self.Q40)
        _note_rejected_hours(analysis, params)
        self.assertEqual(analysis.extracted_info, {"wage_amount": 12000, "weekly_work_days": 6})
        self.assertEqual(analysis.missing_info, ["1일 소정근로시간 또는 주 소정근로시간"])
        _note_rejected_hours(analysis, params)      # 두 번 불러도 안내는 하나
        self.assertEqual(analysis.missing_info, ["1일 소정근로시간 또는 주 소정근로시간"])
        untouched = SimpleNamespace(extracted_info={"daily_work_hours": 8}, missing_info=[])
        _note_rejected_hours(untouched, {"weekly_work_days": 5})
        self.assertEqual((untouched.extracted_info, untouched.missing_info), ({"daily_work_hours": 8}, []))

    def test_t10_unknown_hours_scope(self):
        """시급·일급과 주 5일이 아닌 근무일수는 시간을 가정하지 않는다. 월급제 기본값(주 40시간)은 그대로다."""
        from app.core.pipeline import _run_calculator
        hourly = {"needs_calculation": True, "wage_type": "시급", "reference_year": 2026, "business_size": "5인이상"}
        monthly = dict(hourly, wage_type="월급", wage_amount=2500000, calculation_types_kr=["최저임금"])
        q = "임금 계산해 주세요"
        # 시급만: 판정은 남고 주휴는 산식만, 5일 미만은 5일로 본다
        out = _run_calculator(dict(hourly, wage_amount=12000, calculation_types_kr=["주휴수당"]), q)
        self.assertIn("1주 소정근로시간 ÷ 1주 소정근로일 수(5일 미만은 5일로 봄, 8시간 한도)", out)
        self.assertIn("최저임금 충족: ✅ 충족", out)
        self.assertNotIn("208.5714", out)
        out = _run_calculator(dict(hourly, wage_amount=12000, weekly_work_days=3, calculation_types_kr=["주휴수당"]), q)
        self.assertIn("1주 소정근로시간 ÷ 5(1주 소정근로일 3일 — 5일 미만은 5일로 봄, 8시간 한도)", out)
        self.assertNotIn("별표 2", out)
        # 미달도 시급으로 판정하고 월 부족액(가정한 시간 × 부족분)은 싣지 않는다
        out = _run_calculator(dict(hourly, wage_amount=9000, calculation_types_kr=["최저임금"]), q)
        self.assertIn("최저임금 충족: ❌ 미달", out)
        self.assertIn("(부족분 1,320원/h)", out)
        self.assertNotIn("부족분(월)", out)
        self.assertNotIn(", 월 ", out)
        # 시간에 따라 달라지는 계산은 보류 목록에 이름을 남긴다. 시급제 연장수당(시급 × 가산율 × 질문의 시간)은 남는다(리뷰 M2)
        out = _run_calculator(dict(hourly, wage_amount=12000, calculation_types_kr=["퇴직금", "연장수당"], weekly_work_days=6,
                                   weekly_overtime_hours=5, start_date="2023-01-01", end_date="2026-01-01"), q)
        self.assertIn("다음은 계산하지 않았습니다 — 퇴직금.", out)
        self.assertNotIn("퇴직금: ", out)
        self.assertIn("연장수당: 12,000.0원 × 5h × 1.5 = 90,000원/주", out)
        # 52시간 경고는 가정한 1일 시간 × 6일 + 연장시간이 아니라 질문의 시간만 본다(가정이면 40 + 13 = 53시간 '초과')
        out = _run_calculator(dict(hourly, wage_amount=12000, calculation_types_kr=["연장수당"], weekly_work_days=6,
                                   weekly_overtime_hours=13), q)
        self.assertIn("연장수당: 12,000.0원 × 13h × 1.5 = 234,000원/주", out)
        self.assertNotIn("52h 초과", out)
        # 고정수당이 있는 시급·일급은 최저임금 판정도 시간에 달린다
        out = _run_calculator(dict(hourly, wage_amount=12000, calculation_types_kr=["최저임금"],
                                   fixed_allowances=[{"name": "식대", "amount": 200000, "condition": "없음"}]), q)
        self.assertIn("다음은 계산하지 않았습니다 — 최저임금 검증.", out)
        self.assertNotIn("최저임금 충족:", out)
        out = _run_calculator(dict(hourly, wage_type="일급", wage_amount=100000, calculation_types_kr=["최저임금"]), q)
        self.assertIn("다음은 계산하지 않았습니다 — 최저임금 검증.", out)
        # 임금체불 지연이자는 시간과 무관하다
        out = _run_calculator(dict(hourly, wage_amount=12000, calculation_types_kr=["임금체불"],
                                   arrear_amount=1000000, arrear_due_date="2026-01-10"), q)
        self.assertIn("임금체불 지연이자", out)
        # 월급: 근무일수가 없거나 주 5일 이상이면 주 40시간 관행(주 6일은 1일 40 ÷ 6시간 — 예전 기본값은 48시간이었다), 그 사실을
        # [기준시간]에 밝힌다. 주 5일 미만(단시간)은 관행이 없어 보류
        for extra, hours in (({}, "208.5714h"), ({"weekly_work_days": 5}, "208.5714h"), ({"weekly_work_days": 6}, "202.7778h")):
            out = _run_calculator(dict(monthly, **extra), q)
            self.assertIn(f"= {hours} — 소정근로시간을 질문에서 확인하지 못해 주 40시간으로 계산", out)
            self.assertNotIn("소정근로시간 미확인", out)
            self.assertNotIn("48h", out)
        out = _run_calculator(dict(monthly, weekly_work_days=3), q)
        self.assertIn("다음은 계산하지 않았습니다 — 최저임금 검증.", out)
        self.assertNotIn("통상시급:", out)
        # 시간과 무관한 계산(임금체불)이 남아도 월급·일급의 통상시급(가정한 시간으로 나눈 값)은 싣지 않는다(리뷰 L1)
        for extra in ({"weekly_work_days": 3}, {"wage_type": "일급", "wage_amount": 90000}):
            out = _run_calculator(dict(monthly, calculation_types_kr=["임금체불", "최저임금"], arrear_amount=1000000,
                                       arrear_due_date="2026-01-10", **extra), q)
            self.assertIn("임금체불 지연이자", out)
            self.assertNotIn("통상시급:", out)
            self.assertNotIn("11,250", out)
            self.assertIn("[기준시간] 소정근로시간 미확인 — 월 환산·통상시급은 계산하지 않음", out)
            self.assertNotIn("시급제 최저임금은", out)
        # 시간을 밝힌 카드에는 기본값 표시가 없다
        out = _run_calculator(dict(monthly, weekly_work_days=5, daily_work_hours=8), q)
        self.assertNotIn("질문에서 확인하지 못해", out)
        # 소정근로시간이 있으면 예전 카드 그대로다
        out = _run_calculator(dict(hourly, wage_amount=12000, weekly_work_days=6, daily_work_hours=4,
                                   calculation_types_kr=["주휴수당"]), q)
        self.assertNotIn("소정근로시간 미확인", out)
        self.assertIn("주휴수당: 12,000원 × 4h = 48,000원/주", out)

    def test_t10_review_regressions(self):
        """독립 리뷰 M1·H3·M4·M2 — 버린 뒤 월급 기본값으로 돌아가 '52시간 준수'를 내지 않고, 임금 없는 경로도 근무일수만으로 시간을
        가정하지 않으며, 주 6일 단시간 월급제는 주휴 기준(판례 원칙 vs 시행령 별표 2)에 따라 판정이 갈리면 보류한다."""
        from app.core.pipeline import _run_calculator
        # M1 — 주 60시간 실근로를 주 소정근로시간으로 옮긴 값을 버리면 월급제도 시간을 모른다(예전: '주 총 근로시간 40.0h, 준수')
        out = _run_calculator({"needs_calculation": True, "calculation_types_kr": ["주52시간"], "wage_type": "월급",
                               "wage_amount": 3000000, "weekly_total_hours": 60, "business_size": "5인이상"},
                              "월급 300만원 받는데 지난주 60시간 일했어요. 52시간 위반인가요?")
        self.assertIn("질문의 60시간은 그 기간에 실제로 일한 시간이라", out)
        self.assertIn("주 52시간 준수 여부 체크", out)
        self.assertNotIn("✅ 준수", out)
        self.assertNotIn("40.0h", out)
        # H3 — 임금 없이 근무일수만 있으면 소정근로시간 산정을 하지 않는다(예전: 8h × 6일 → 243.3333시간)
        out = _run_calculator({"needs_calculation": True, "calculation_types_kr": ["근로시간산정"], "weekly_work_days": 6},
                              "주 6일 근무하는데 월 소정근로시간이 몇 시간인가요?")
        self.assertIn("다음은 계산하지 않았습니다 — 소정근로시간 산출.", out)
        self.assertNotIn("243.3333", out)
        out = _run_calculator({"needs_calculation": True, "calculation_types_kr": ["근로시간산정"]}, "월 소정근로시간이 몇 시간인가요?")
        self.assertIn("= 208.5714h — 소정근로시간을 질문에서 확인하지 못해 주 40시간으로 계산", out)
        # M4 — 월 190만 원, 주 6일 × 6시간: 1일 평균(6h) 182.5h 충족 / 통상 근로자 주 5일(7.2h) 187.71h 미달 → 보류
        monthly = {"needs_calculation": True, "calculation_types_kr": ["최저임금"], "wage_type": "월급",
                   "weekly_work_days": 6, "daily_work_hours": 6, "reference_year": 2026}
        out = _run_calculator(dict(monthly, wage_amount=1900000), "월급 190만원, 주 6일 하루 6시간")
        self.assertIn("최저임금 충족: ⏸ 판정 보류", out)
        self.assertIn("실질시급: 10,411원 또는 10,122원", out)
        self.assertIn("근로기준법 시행령 별표 2 제2호나목) 10,122원이라 최저임금(10,320원) 충족 여부가 갈립니다", out)
        self.assertNotIn("✅ 충족", out)
        self.assertNotIn("❌ 미달", out)
        out = _run_calculator(dict(monthly, wage_amount=2500000), "월급 250만원, 주 6일 하루 6시간")   # 둘 다 충족이면 판정
        self.assertIn("최저임금 충족: ✅ 충족", out)
        self.assertNotIn("갈립니다", out)
        out = _run_calculator(dict(monthly, wage_type="시급", wage_amount=10320), "시급 10,320원, 주 6일 하루 6시간")  # 시급제는 같다
        self.assertIn("최저임금 충족: ✅ 충족", out)
        # 주 6일 × 7시간 = 42시간은 단시간근로자가 아니라 별표 2 대안이 없다. 대신 주 40시간을 넘는 2시간이 연장근로라
        # (calc-card-followups D1) 소정 기준시간은 202.78h이고, 월급에 그 연장분이 포함됐는지에 따라 10,948원 충족 / 역산 10,287원
        # 미달로 갈려 보류한다(D4)
        out = _run_calculator(dict(monthly, daily_work_hours=7, wage_amount=2220000), "월급 222만원, 주 6일 하루 7시간")
        self.assertIn("최저임금 충족: ⏸ 판정 보류", out)
        self.assertIn("실질시급: 10,948원 또는 10,287원", out)
        self.assertNotIn("시행령 별표 2 제2호나목", out)
        # M2 — 특수고용직은 시간을 몰라도 법률 힌트(산재 특례 등)가 남는다
        out = _run_calculator({"needs_calculation": True, "calculation_types_kr": ["최저임금"], "wage_type": "시급",
                               "wage_amount": 12000, "is_platform_worker": True, "weekly_work_days": 6},
                              "배달 라이더인데 시급 12,000원으로 주 6일 일해요")
        self.assertIn("특수고용직(노무제공자) 산재 적용", out)
        self.assertIn("다음은 계산하지 않았습니다 — 4대보험·소득세", out)

    def test_t10_managed_minimum_wage_marker_and_blocked_result(self):
        """관리 모드 '최저시급' 질문은 시급 자리가 표지값(1)이라 금액을 적지 않는다. 안내가 앞에 붙어도 요청 단위 '계산 보류'는
        LLM 머리말에서 보류로 읽힌다(예전 판정은 문자열 맨 앞만 봤다)."""
        from unittest import mock
        from app.core.pipeline import _calculation_context_heading, _run_calculator
        params = {"needs_calculation": True, "calculation_types_kr": ["주휴수당"], "wage_type": "시급",
                  "use_minimum_wage": True, "weekly_work_days": 3, "reference_year": 2026}
        with mock.patch("app.core.legal_rule_store.rules_enabled", return_value=True), \
                mock.patch("app.core.legal_rule_store.configured_store", return_value=None):
            out = _run_calculator(params, "최저시급 받고 주 3일 일해요. 주휴수당 나오나요?")
        self.assertIn("주휴수당 = 시간급 통상임금 × 주휴시간", out)
        self.assertNotIn("시급 1원", out)
        self.assertIn("\n계산 보류", out)
        self.assertIn("금액 추정 금지", _calculation_context_heading(out))
        self.assertIn("금액 추정 금지", _calculation_context_heading("계산 보류: 승인 기준 없음"))
        self.assertEqual(_calculation_context_heading("📊 임금 계산 결과\n보류된 계산 (승인 기준 없음 — 아래 결과에 포함되지 않음):"),
                         "임금계산기 결과 — 이 수치를 사용하세요")

    def test_t10_part_timer_working_more_than_five_days_gets_the_annex_alternative(self):
        """주 5일을 넘게 일하는 단시간근로자 — 원칙(÷ 소정근로일 수)으로 계산하되 통상 근로자 기준(시행령 별표 2)을 함께 밝힌다."""
        from wage_calculator import WageCalculator, WageInput, WageType
        from wage_calculator.models import WorkSchedule

        def warnings(days, daily):
            inp = WageInput(wage_type=WageType.HOURLY, hourly_wage=12000,
                            schedule=WorkSchedule(daily_work_hours=daily, weekly_work_days=days))
            return " ".join(WageCalculator().calculate(inp, ["weekly_holiday"]).warnings)

        self.assertIn("근로기준법 시행령 별표 2 제2호나목·제4호라목) — 통상 근로자가 주 5일 근무하면 주휴 4.8h(24h ÷ 5)입니다.",
                      warnings(6, 4))
        for days, daily in ((5, 4), (6, 8), (4, 6)):
            self.assertNotIn("별표 2", warnings(days, daily), (days, daily))


if __name__ == "__main__":
    unittest.main(verbosity=1)
