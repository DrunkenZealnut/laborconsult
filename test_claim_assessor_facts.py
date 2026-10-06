"""확인청구 기관·괴롭힘 판정기 사실 전제 회귀 테스트 (claim-authority-and-assessor-facts).

오프라인·API 키 불요(CI). 막는 실패는 전부 **조용했다**:
- 피보험자격 확인청구를 고용센터로 안내했다(3차 재평가 7·15번). 올바른 문장은 insured_status 블록에
  이미 있었지만 그 블록은 20문항 중 1개에만 붙었다.
- 괴롭힘 판정기가 질문에 없는 사실(기간·회사 대응·행위 유형·가해자)을 채운 도구 인자로 판정했고,
  "이 결과를 사용하세요" 라벨이 그 판정을 답변까지 밀어 넣었다(3차 9번 "해당 가능성 높음").
- 판정 결과가 있으면 법률상담 경로(2-2)를 통째로 건너뛰어, 잘못 돈 판정이 법령 근거까지 지웠다.

설계: docs/02-design/features/claim-authority-and-assessor-facts.design.md §5 (C1~C16).
Check 단계 보강(C1b·C9b 등): docs/03-analysis/claim-authority-and-assessor-facts.analysis.md §3.
"""
from __future__ import annotations

import json
import os
import re
import unittest
import unittest.mock as mock
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parent
KST = timezone(timedelta(hours=9))


def _fixture_questions() -> dict[str, str]:
    out = {}
    for name in ("eval_consultation_queries.json", "eval_kin_queries.json"):
        for c in json.loads((ROOT / "data" / name).read_text(encoding="utf-8")):
            out[c["id"]] = c["question"]
    return out


def _mode_cases() -> list[tuple[str, str, str, str]]:
    qs = _fixture_questions()
    data = json.loads((ROOT / "data/assessor_grounding_cases.json").read_text(encoding="utf-8"))
    return [(c["id"], qs[c["fixture_ref"]] if "fixture_ref" in c else c["question"], c["mode"], c["reason"])
            for c in data["cases"]]


def _tool_params() -> list[tuple[str, int, dict, str]]:
    qs = _fixture_questions()
    data = json.loads((ROOT / "data/assessor_tool_params.json").read_text(encoding="utf-8"))
    return [(c["fixture_ref"], c["run"], c["params"], qs[c["fixture_ref"]]) for c in data["cases"]]


class GroundingTest(unittest.TestCase):
    """C1~C3·C6·C7 — 판정 입력은 질문 본문에서 도출하고, 모드는 사안 서술로 정한다."""

    def test_c1_values_are_derived_from_the_question(self):
        from harassment_assessor.grounding import derive_input
        qs = _fixture_questions()
        r4 = derive_input(qs["risk-04"])
        self.assertEqual(r4.behavior_types, ["따돌림_무시", "폭언_모욕"])
        self.assertEqual((r4.perpetrator_role, r4.frequency, r4.duration), ("상사", "매일", ""),
                         "질문에 없는 기간은 도출하지 않는다(도구는 6개월을 채웠다)")
        self.assertEqual(r4.company_response, "", '"신고 후 조사 절차"는 회사 대응이 아니다')
        k9 = derive_input(qs["kin-09"])
        self.assertEqual((k9.behavior_types, k9.perpetrator_role, k9.company_response), ([], "", ""),
                         "사유를 쓰라고 한 팀장은 행위자로 지목되지 않았다 · 회사 대응 미조치는 질문에 없다")
        self.assertEqual(k9.evidence, ["녹취"])
        self.assertEqual(derive_input("입사 3년차인데 6개월째 팀장이 업무를 안 줘요").duration, "6개월",
                         "'3년차'는 기간이 아니다")
        size = derive_input("직원 13명인 회사인데 과장이 폭언을 해요")
        self.assertEqual(size.business_size, "직원 13명")
        self.assertEqual(size.relationship_type, "상급자", "13명은 다수 우위가 아니다")
        many = derive_input("동료 3명이 저를 따돌려요")
        self.assertEqual((many.business_size, many.relationship_type), ("", "다수_소수"),
                         "동료 3명은 사업장 규모가 아니고 다수 우위다")
        self.assertTrue(all(derive_input(q).grounded for q in ("아무 질문", qs["risk-03"])))

    def test_c1b_actor_frequency_impact_response_edges(self):
        """Check §3-3·3-4·3-6·3-8 — fixture 밖 표현에서 행위자를 잘못 짚거나 무관한 단어로 '높음'이 났다."""
        from harassment_assessor.assessor import assess_harassment
        from harassment_assessor.grounding import _norm, decide_mode, derive_input
        nl = "팀장님은 친절하세요\n매일 욕을 하는 건 동료예요"
        self.assertEqual(decide_mode(nl).inp.perpetrator_role, "동료", "줄바꿈도 문장 경계다")
        self.assertEqual(derive_input(_norm(nl)).perpetrator_role, "팀장",
                         "축약부터 하면 경계가 사라진다 — 위 단언이 이 차이를 고정한다")
        for q, actor in (("동료가 팀장 앞에서 매일 욕을 해요", "동료"),          # 주격 조사 우선
                         ("과장된 소문 때문에 동료들이 저를 무시해요", "동료"),   # '과장된'은 직위가 아니다
                         ("대표적으로 매일 욕을 들어요", ""), ("이사 온 뒤로 매일 따돌림을 당하고 있어요", ""),
                         ("동기부여가 안 돼요. 매일 욕을 들어요", "")):
            self.assertEqual(derive_input(q).perpetrator_role, actor, q)
        for q in ("팀장이 욕을 했어요. 계속 다녀야 할까요?", "팀장이 욕을 했어요\n계속 다녀야 할까요"):
            inp = derive_input(q)
            self.assertEqual(inp.frequency, "", f"행위 문장 밖의 '계속'은 빈도가 아니다: {q!r}")
            self.assertEqual(assess_harassment(inp).likelihood, "보통")
        pill = derive_input("상사가 매일 욕을 해서 약을 먹고 있어요")
        self.assertEqual(pill.impact, "약을 먹", "라벨('복약')이 아니라 원문을 넘겨야 판정기 가산이 남는다")
        self.assertGreater(assess_harassment(pill).element_3_harm.score,
                           assess_harassment(derive_input("상사가 매일 욕을 해요")).element_3_harm.score)
        self.assertEqual(derive_input("산재 신고 후 해고됐는데 상사가 매일 욕을 해요").company_response, "",
                         "산재 신고 뒤 해고는 '괴롭힘 신고'에 대한 불리한 처우가 아니다")
        self.assertEqual(derive_input("팀장이 매일 욕을 해서 회사에 신고했더니 해고됐어요").company_response,
                         "불리한 처우")

    def test_c2_mode_cases(self):
        from harassment_assessor.grounding import decide_mode
        cases = _mode_cases()
        self.assertGreater(sum(1 for cid, *_ in cases if not cid.startswith(("risk-", "kin-"))), 5,
                           "반례가 실측 5건보다 많아야 한다(M13)")
        for cid, q, mode, reason in cases:
            r = decide_mode(q)
            self.assertEqual((r.mode, r.reason), (mode, reason), cid)

    def test_c3_retaliation_context_removes_the_adverse_measure(self):
        from harassment_assessor.grounding import _RETALIATION_RE, derive_input
        for q in ("괴롭힘 신고 후 불리한 부서로 발령이 났어요", "괴롭힘을 신고했는데 전보 조치가 내려왔습니다",
                  "노동청에 진정했더니 회사가 징계를 하겠대요", _fixture_questions()["risk-05"]):
            self.assertTrue(_RETALIATION_RE.search(q), q)
        self.assertFalse(_RETALIATION_RE.search(_fixture_questions()["risk-04"]), "신고 후 조사 절차는 불리한 처우가 아니다")
        mixed = derive_input("팀장이 매일 욕설을 해서 신고했더니 지방으로 전보됐어요")
        self.assertEqual(mixed.behavior_types, ["폭언_모욕"], "전보는 제76조의3⑥(불리한 처우) 영역이다")

    def test_c6_grounded_input_is_not_rescanned(self):
        from harassment_assessor.assessor import _detect_behavior_types
        from harassment_assessor.models import HarassmentInput
        grounded = HarassmentInput(behavior_types=["폭언_모욕"], behavior_description="신고 후 전보됐다", grounded=True)
        self.assertEqual(_detect_behavior_types(grounded), ["폭언_모욕"], "H2: 뺀 부당인사가 되살아나면 안 된다")
        legacy = HarassmentInput(behavior_description="팀장이 욕을 했어요")
        self.assertIn("폭언_모욕", _detect_behavior_types(legacy), "grounded가 아니면 기존처럼 감지한다")

    def test_c7_dictionary_precision(self):
        from harassment_assessor.constants import BEHAVIOR_TYPE_PATTERNS, IMPACT_PATTERNS, MAJORITY_RE
        verbal = BEHAVIOR_TYPE_PATTERNS["폭언_모욕"]
        for q in ("팀장이 욕해요", "욕했어요", "욕을 들었어요", "매일 갈궈요", "소리를 질러요", "욕설을 합니다"):
            self.assertTrue(verbal.search(q), q)
        for q in ("의욕을 잃었어요", "식욕을 잃었어요", "목욕하고 왔어요", "욕심이 많아요"):
            self.assertFalse(verbal.search(q), q)
        self.assertTrue(verbal.search("팀장이 개새끼라고 해요"), "욕설 직접 인용(Check §3-8)")
        self.assertTrue(BEHAVIOR_TYPE_PATTERNS["따돌림_무시"].search("동료들이 이상한 소문을 퍼뜨려요"))
        unfair = BEHAVIOR_TYPE_PATTERNS["부당업무"]
        for q in ("팀장이 일을 주지 않아요", "팀장이 업무를 안 줘요", "일을 안 줘요"):
            self.assertTrue(unfair.search(q), q)
        self.assertFalse(unfair.search("팀장이 휴일을 안 줘요"), "'휴일'의 '일'은 업무가 아니다")
        impact = lambda t: [label for rx, _b, label in IMPACT_PATTERNS if rx.search(t)]   # noqa: E731
        self.assertEqual(impact("계약직으로 약 8개월 근무"), [], "단독 '약'은 계약·약 8개월에 걸렸다")
        self.assertEqual(impact("약을 먹고 있어요"), ["복약"])
        self.assertFalse(MAJORITY_RE.search("단체협약상 직원 13명"))
        self.assertTrue(MAJORITY_RE.search("동료 3명이 저를 따돌려요"))


class AssessorOutputTest(unittest.TestCase):
    """C4·C5 — '높음'은 세 요소가 모두 해당일 때만, 판단 보류는 단정하지 않는다."""

    def test_c4_high_requires_all_three_elements(self):
        from harassment_assessor.assessor import assess_harassment
        from harassment_assessor.models import HarassmentInput
        # 3차 9번 경로: ① 해당(1.0) · ② 불분명(부당인사 0.7×0.5) · ③ 해당(0.5+사직 0.2) → 종합 0.67
        kin09_like = assess_harassment(HarassmentInput(perpetrator_role="팀장", behavior_types=["부당인사"],
                                                       impact="사직"))
        self.assertGreaterEqual(kin09_like.overall_score, 0.65)
        self.assertEqual(kin09_like.element_2_beyond_scope.status, "불분명")
        self.assertEqual(kin09_like.likelihood, "보통", "요소가 불분명이면 종합 점수만으로 '높음'을 내지 않는다")
        full = assess_harassment(HarassmentInput(perpetrator_role="상사", behavior_types=["폭언_모욕", "따돌림_무시"],
                                                 frequency="매일"))
        self.assertEqual(full.likelihood, "높음")

    def test_c5_held_output_does_not_assert(self):
        from harassment_assessor.assessor import held_assessment
        from harassment_assessor.constants import HOLD_REQUIRED_FACTS
        from harassment_assessor.models import HarassmentInput
        from harassment_assessor.result import format_assessment
        for reason, first in (("no_behavior", "구체적인 괴롭힘 행위"), ("no_actor", "행위자와의 관계")):
            text = format_assessment(held_assessment(HarassmentInput(grounded=True), reason))
            self.assertIn("판단 보류", text.splitlines()[1])
            self.assertIn(first, text)
            self.assertTrue(all(f in text for f in HOLD_REQUIRED_FACTS))
            self.assertNotRegex(text, r"해당 가능성:\s*(높음|보통|낮음)")
            self.assertNotIn("판정 결과", text.splitlines()[1])


class PipelineWiringTest(unittest.TestCase):
    """C8~C10·C13~C15 — 판정기 배선·라벨·킬스위치·2-2 조건."""

    SRC = (ROOT / "app/core/pipeline.py").read_text(encoding="utf-8")

    def test_c8_labels_and_prompt_no_longer_say_use_as_is(self):
        self.assertIn("_run_assessor(params, query)", self.SRC)
        # 계산기 수치를 그대로 쓰라는 지시(정당)는 남는다 — 판정기 결과에 대한 지시만 금지한다
        for banned in ("이 결과를 사용하세요", "종합 가능성을 그대로 사용하세요"):
            self.assertNotIn(banned, self.SRC, banned)
        self.assertIn("질문에 나온 사실만으로 판정", self.SRC)
        self.assertIn("판단 보류 — 해당 여부를 단정하지 말고", self.SRC)
        self.assertIn("판정기 결과는 질문에 나온 사실만으로 낸 것입니다", self.SRC)
        self.assertIn("if _consultation_allowed(analysis, calc_result, assessment_result, assessor_info):", self.SRC)
        self.assertNotRegex(self.SRC, r"if [^\n]*not assessment_result[^\n]*consultation_type",
                            "판정 결과만으로 2-2를 건너뛰던 옛 조건")
        # 판단 보류 지시는 두 답변 분기 공통 접미(Check §3-5) — 분기 뒤, 보류일 때만
        from app.templates.prompts import HELD_ASSESSMENT_RULES
        self.assertIn("단정하지 말고", HELD_ASSESSMENT_RULES)
        held = self.SRC.index("system_prompt = system_prompt + HELD_ASSESSMENT_RULES")
        self.assertGreater(held, self.SRC.index("system_prompt = system_prompt + INJECTION_RESISTANCE"))
        self.assertIn('if (assessor_info or {}).get("mode") == "held":', self.SRC[held - 200: held])

    def test_c9_metadata_records_field_names_only(self):
        from app.core.pipeline import _run_assessor
        for ref, run, params, q in _tool_params():
            if not (params or {}).get("is_harassment_question"):
                continue
            _text, info = _run_assessor(params, q)
            blob = json.dumps(info, ensure_ascii=False)
            for value in (params.get("duration"), params.get("company_response"), params.get("behavior_description")):
                if value:
                    self.assertNotIn(value, blob, f"{ref}#{run}: 값이 아니라 필드명만 남긴다")
            if ref == "risk-04":
                self.assertIn("duration", info.get("dropped", []), "도구가 지어낸 기간은 버린 필드로 기록된다")

    def test_c9b_not_called_is_recorded_with_sexual_reason(self):
        """Check §3-1 — 도구가 괴롭힘을 고르지 않아도 성희롱이면 2-2를 생략해야 한다."""
        from app.core.pipeline import _consultation_allowed, _not_called_info
        self.assertEqual(_not_called_info("wage", "팀장이 매일 욕해요"), {"mode": "not_called", "tool": "wage"})
        sexual = _not_called_info("none", "팀장이 회식 자리에서 성적인 농담을 해요")
        self.assertEqual(sexual, {"mode": "not_called", "tool": "none", "reason": "sexual"})
        self.assertFalse(_consultation_allowed(NS(consultation_type="procedure_guide"), None, None, sexual))
        self.assertIn("assessor_info = _not_called_info(tool_type, query)", self.SRC)
        self.assertIn('conv_metadata["assessor"] = assessor_info', self.SRC)

    def test_c10_kill_switch_restores_tool_param_path(self):
        from app.core import pipeline
        from harassment_assessor import HarassmentInput, assess_harassment, format_assessment
        with mock.patch.dict(os.environ, {"ASSESSOR_GROUNDING": "off"}):
            for ref, run, params, q in _tool_params():
                if not (params or {}).get("is_harassment_question"):
                    continue
                text, info = pipeline._run_assessor(params, q)
                fields = {k: params.get(k, d) for k, d in (
                    ("perpetrator_role", ""), ("victim_role", ""), ("relationship_type", ""),
                    ("behavior_description", ""), ("behavior_types", []), ("frequency", ""), ("duration", ""),
                    ("witnesses", False), ("evidence", []), ("impact", ""), ("company_response", ""),
                    ("business_size", ""))}
                self.assertEqual(info, {"mode": "off"})
                self.assertEqual(text, format_assessment(assess_harassment(HarassmentInput(**fields))), f"{ref}#{run}")

    def test_c13_mode_uses_question_body_not_attachments(self):
        self.assertIn("_run_assessor(params, query)", self.SRC)
        self.assertNotIn("_run_assessor(params, combined_query)", self.SRC)

    def test_c14_errors_are_absorbed_as_skipped(self):
        from app.core import pipeline
        with mock.patch.object(pipeline, "ground", side_effect=RuntimeError("boom")):
            text, info = pipeline._run_assessor({"is_harassment_question": True}, "팀장이 매일 욕해요")
        self.assertIsNone(text, "오류문을 판정 결과로 주입하지 않는다")
        self.assertEqual(info, {"mode": "skipped", "reason": "error"})
        text, info = pipeline._run_assessor(
            {"is_harassment_question": True, "evidence": "녹음, 문자", "behavior_types": "폭언_모욕"},
            "팀장이 매일 욕해요. 녹음이 있어요")
        self.assertIsNotNone(text, "문자열로 온 list 인자도 처리한다")
        self.assertEqual(info["mode"], "assessed")
        # 관측용 dropped 계산이 판정을 버리면 안 된다(Check §3-7)
        odd = {"is_harassment_question": True, "behavior_types": [{"x": 1}, 3], "evidence": True, "frequency": 2}
        text, info = pipeline._run_assessor(odd, "팀장이 매일 욕해요")
        self.assertIsNotNone(text)
        self.assertEqual(info["mode"], "assessed")
        from harassment_assessor import ground
        self.assertEqual(ground(["x"], "팀장이 매일 욕해요").dropped, ["(unparsed)"], "dropped 예외는 ground 안에서 흡수")
        with mock.patch.dict(os.environ, {"ASSESSOR_GROUNDING": "off"}):
            text, _ = pipeline._run_assessor({"is_harassment_question": True, "behavior_types": "폭언_모욕"},
                                              "팀장이 매일 욕해요")
        self.assertIn("감지된 행위 유형: 폭언·모욕", text, "킬스위치 경로도 문자열 list 인자를 글자 단위로 쪼개지 않는다")
        self.assertNotIn("_, 모", text)

    def test_c15_consultation_path_condition(self):
        from app.core.pipeline import _consultation_allowed
        a = NS(consultation_type="procedure_guide")
        none = NS(consultation_type=None)
        self.assertFalse(_consultation_allowed(a, None, "판정", {"mode": "assessed"}), "판정이면 생략")
        self.assertFalse(_consultation_allowed(a, None, "판정", {"mode": "off"}), "킬스위치 off는 이전처럼 생략")
        self.assertTrue(_consultation_allowed(none, None, "보류", {"mode": "held", "reason": "no_behavior"}),
                        "판단 보류는 consultation_type이 비어도 돌린다")
        self.assertTrue(_consultation_allowed(none, None, None, {"mode": "skipped", "reason": "no_case"}))
        self.assertTrue(_consultation_allowed(none, None, None, {"mode": "not_called", "tool": "wage"}),
                        "미호출도 판정기가 돌지 않은 경우다 — consultation_type이 비어도 돌린다(Check §3-2)")
        self.assertFalse(_consultation_allowed(a, None, None, {"mode": "not_called", "tool": "none",
                                                                "reason": "sexual"}))
        self.assertFalse(_consultation_allowed(a, None, None, {"mode": "skipped", "reason": "sexual"}),
                         "성희롱은 괴롭힘 기본 조문이 실리므로 생략")
        self.assertFalse(_consultation_allowed(a, "계산", None, None), "계산 결과가 있으면 생략(기존)")
        self.assertTrue(_consultation_allowed(a, None, None, None), "판정기와 무관한 상담 질문(기존)")
        self.assertFalse(_consultation_allowed(none, None, None, None))


class ClaimAuthorityFactsTest(unittest.TestCase):
    """C11·C12·C16 — 확인청구 기관 문장과 원문 앵커."""

    def test_c11_rule_blocks_carry_the_role_split_and_section_50(self):
        import fetch_official_rules as fo
        from app.core.rule_facts import RULE_FACTS
        facts = {f.name: f for f in RULE_FACTS}
        unemp = facts["unemployment"]
        self.assertTrue(any("근로복지공단에 확인을 청구" in ln and "언제든지" in ln for ln in unemp.lines))
        for doc in ("ei_act_58", "ei_act_43", "ei_act_17", "ei_enf_145"):
            self.assertIn(doc, {d for d, _ in unemp.anchors}, doc)
        insured = facts["insured_status"]
        self.assertTrue(any("제50조 제5항" in ln and "확인청구의 기한이 아니다" in ln for ln in insured.lines))
        self.assertEqual(sum(1 for d, _ in insured.anchors if d == "ei_act_50"), 2)
        ids = {a[0] for a in fo.ARTICLES}
        self.assertTrue({"ei_act_50", "ei_act_58"} <= ids)

    def test_c12_answer_rule_anchors(self):
        import fetch_official_rules as fo
        from app.templates.prompts import ANSWER_ACCURACY_RULES, ANSWER_RULE_ANCHORS
        self.assertIn("근로복지공단", ANSWER_ACCURACY_RULES)
        self.assertIn("제50조 제5항", ANSWER_ACCURACY_RULES)
        ids = {a[0] for a in fo.ARTICLES}
        self.assertTrue({d for d, _ in ANSWER_RULE_ANCHORS} <= ids)
        base = ROOT / "output_공식법령"
        if not base.is_dir():
            self.skipTest("output_공식법령/ 없음 — 원문 대조는 로컬 관문")
        from app.core.rule_facts import RULE_FACTS
        norm = lambda t: re.sub(r"\s+", "", t)   # noqa: E731
        today = datetime.now(KST).strftime("%Y%m%d")
        anchors = list(ANSWER_RULE_ANCHORS) + [a for f in RULE_FACTS for a in f.anchors]
        for doc_id, phrase in anchors:
            text = (base / f"{doc_id}.md").read_text(encoding="utf-8")
            self.assertIn(norm(phrase), norm(text.split("## 본문", 1)[-1]), f"{doc_id}: {phrase[:30]}")
            date = re.search(r"^- date:\s*(\S+)", text, re.M)
            if date:   # 저장본 판본이 시행 예정분이면 안 된다(D16 — 4건이 20280101 헤더였다)
                self.assertLessEqual(date.group(1).replace("-", ""), today, doc_id)

    def test_c17_kin15_matcher_flags_only_wrong_filing_agency(self):
        """kin-15 금지 문구는 고용센터를 확인청구 **접수처**로 지정한 문장만 잡는다(CodeRabbit PR #101).

        구 패턴(고용센터 뒤 30자 안에 확인청구)은 역할을 올바르게 나눈 정답 문장까지 잡았다.
        """
        from eval_consultation import claim_found
        kin15 = [c for c in json.loads((ROOT / "data/eval_kin_queries.json").read_text(encoding="utf-8"))
                 if c["id"] == "kin-15"][0]
        pattern = next(p for p in kin15["forbidden_claims"] if "고용센터" in p)
        for wrong in ("고용센터에 피보험자격 확인청구를 하면 최대 3년까지 소급 가입이 인정됩니다.",
                      "고용센터에 **피보험자격 확인청구**를 하면 소급 가입이 인정될 수 있습니다.",   # 3차 원답변 형태
                      "관할 고용센터에서 피보험자격 확인을 청구하세요.",
                      "고용센터를 통해 피보험자격 확인청구를 진행할 수 있습니다."):
            self.assertTrue(claim_found(pattern, wrong), wrong)
        for right in ("고용센터는 수급자격을 판단하고 피보험자격 확인청구는 근로복지공단에서 처리합니다.",
                      "이직사유 판단과 수급자격 인정은 고용센터가 하고, 피보험자격 확인청구는 근로복지공단에 합니다.",
                      "고용센터에 문의하면 피보험자격 확인청구 방법을 안내받을 수 있지만 청구는 근로복지공단에 합니다.",
                      "비자발적 이직이므로 **고용센터에 실업급여**를 신청하고, 확인청구는 **근로복지공단**에 합니다."):
            self.assertFalse(claim_found(pattern, right), right)
        # '3년'은 확인청구 **기한**으로 내세운 문맥만 잡는다 — 피보험기간 소급 범위 설명은 정답이다(제50조⑤)
        three = next(p for p in kin15["forbidden_claims"] if "3년" in p)
        for wrong in ("피보험자격 확인청구는 최대 3년까지만 할 수 있습니다.",
                      "3년 이내에 피보험자격 확인청구를 해야 합니다.",
                      "3년이 지나면 확인청구를 할 수 없습니다.",
                      "확인청구 기한은 최대 3년입니다.",
                      "확인청구는 근로 종료 후 3년 이내에만 가능합니다.",
                      "피보험자격 확인청구는 3년 안에 해야 합니다.",          # CodeRabbit PR #101
                      "확인청구는 3년 이내 청구해야 합니다."):
            self.assertTrue(claim_found(three, wrong), wrong)
        for right in ("신고되지 않은 기간의 피보험기간은 최대 3년까지 소급해 인정될 수 있습니다.",
                      "확인청구는 언제든지 할 수 있고, '3년'은 피보험기간을 계산하는 범위입니다.",
                      "퇴직금과 임금채권의 소멸시효는 3년입니다.",
                      "퇴직금은 3년 이내에 청구해야 합니다.",
                      "확인청구는 기한이 없지만, 피보험기간 소급은 최대 3년까지입니다.",
                      "피보험자격 확인은 언제든지 청구할 수 있고 피보험기간은 3년 안에서 소급 인정됩니다."):
            self.assertFalse(claim_found(three, right), right)

    def test_c16_freshness_anchor_check_includes_answer_rules(self):
        src = (ROOT / "check_law_freshness.py").read_text(encoding="utf-8")
        self.assertIn("ANSWER_RULE_ANCHORS", src)
        self.assertIn('("answer_rules", ANSWER_RULE_ANCHORS)', src)


if __name__ == "__main__":
    unittest.main(verbosity=1)
