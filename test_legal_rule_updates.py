"""Offline behavioral tests; all numeric/date fixtures are synthetic, not legal authority."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.core.legal_updates import LegalUpdateService, Conflict, EvidenceError, RuleError
from wage_calculator.legal_rules import (PARAMETERS, RuleSnapshot, rule_scope, parameter,
                                         RuleUnavailable)


class MemoryStore:
    def __init__(self):
        self.revision = 0
        self.document = {"records": [], "scans": []}
        self.events = []

    def load(self):
        return self.revision, deepcopy(self.document)

    def save(self, revision, document, actor, action, payload):
        if revision != self.revision:
            raise Conflict("다른 관리자가 변경했습니다")
        self.revision += 1
        self.document = deepcopy(document)
        self.events.append({"revision": self.revision, "actor": actor,
                            "action": action, "payload": deepcopy(payload)})
        return self.revision


class Evidence:
    def __init__(self):
        self.documents = {"fixture-law": {
            "id": "fixture-law", "namespace": "laborlaw-v2",
            "source_type": "regulation", "title": "테스트 전용 고시",
            "url": "https://www.moel.go.kr/test-fixture", "date": "2030-12-01",
            "text": "테스트 전용: 2031년 1월 1일부터 시간급 12,345원. 실제 법률값 아님.",
        }}

    def fetch(self, vector_id):
        if vector_id not in self.documents:
            raise EvidenceError("문서 없음")
        return deepcopy(self.documents[vector_id])

    def search(self, query):
        return [self.fetch("fixture-law")]


def proposal(**changes):
    return dict({
        "topic": "minimum_wage", "kind": "parameter", "key": "minimum_hourly_wage",
        "value": 12345, "effective_from": "2031-01-01", "effective_to": "2032-01-01",
        "evidence_id": "fixture-law", "quote": "2031년 1월 1일부터 시간급 12,345원",
        "citation": "테스트 전용 고시", "note": "테스트 fixture; 법적 근거 아님",
    }, **changes)


class LegalUpdatesTest(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.evidence = Evidence()
        self.service = LegalUpdateService(self.store, self.evidence)

    def add(self, **changes):
        return self.service.create(proposal(**changes), self.store.revision, "admin-test")

    def approve(self, record):
        return self.service.transition(record["id"], "approve", self.store.revision,
                                       "admin-test", "원문·시행일·값 대조 확인")

    def snapshot(self, day="2031-06-01"):
        return RuleSnapshot(self.store.document["records"], day)

    def test_pending_has_no_effect_and_approval_changes_only_covered_date(self):
        record = self.add()
        with self.assertRaises(RuleUnavailable):
            self.snapshot().get("minimum_hourly_wage")
        self.approve(record)
        self.assertEqual(self.snapshot().get("minimum_hourly_wage"), 12345)
        for day in ("2030-12-31", "2032-01-01"):
            with self.assertRaises(RuleUnavailable):
                self.snapshot(day).get("minimum_hourly_wage")
        self.assertEqual(self.snapshot("2031-01-01").get("minimum_hourly_wage"), 12345)

    def test_source_is_server_fetched_and_quote_must_exist(self):
        with self.assertRaises(RuleError):
            self.add(quote="원문에 없는 문장")
        record = self.add()
        self.assertEqual(record["evidence"]["text"], self.evidence.fetch("fixture-law")["text"])
        self.assertTrue(record["evidence"]["sha256"])

    def test_unofficial_source_and_textbook_cannot_be_approved(self):
        for field, value in (("url", "https://nodong.kr/example"),
                             ("url", "https://www.moel.go.kr.attacker.test/x"),
                             ("source_type", "textbook"), ("namespace", "qa")):
            self.setUp()
            self.evidence.documents["fixture-law"][field] = value
            try:
                record = self.add()
                self.approve(record)
            except RuleError:
                pass
            else:
                self.fail((field, value))

    def test_approval_refetches_and_rejects_changed_or_missing_evidence(self):
        record = self.add()
        self.evidence.documents["fixture-law"]["text"] += " 정정"
        with self.assertRaises(EvidenceError):
            self.approve(record)
        del self.evidence.documents["fixture-law"]
        with self.assertRaises(EvidenceError):
            self.approve(record)
        self.assertEqual(self.store.document["records"][0]["status"], "pending")

    def test_overlap_rejected_but_adjacent_quarter_allowed(self):
        first = self.add(effective_to="2031-07-01")
        self.approve(first)
        conflict = self.add(effective_from="2031-06-30")
        with self.assertRaises(RuleError):
            self.approve(conflict)
        second = self.add(effective_from="2031-07-01", value=12346)
        self.approve(second)
        self.assertEqual(self.snapshot("2031-06-30").get("minimum_hourly_wage"), 12345)
        self.assertEqual(self.snapshot("2031-07-01").get("minimum_hourly_wage"), 12346)

    def test_invalid_dates_values_keys_and_unknown_fields_are_rejected(self):
        for change in ({"value": float("nan")}, {"value": True}, {"value": -1},
                       {"key": "python_eval"}, {"effective_from": "2031-02-29"},
                       {"effective_to": "2030-01-01"}, {"topic": "unknown"},
                       {"status": "approved"}, {"evidence": {"fake": "data"}}):
            with self.subTest(change=change), self.assertRaises(RuleError):
                self.add(**change)

    def test_revision_conflict_prevents_lost_update(self):
        record = self.add()
        with self.assertRaises(Conflict):
            self.service.transition(record["id"], "approve", 0, "admin-other", "검토 확인")
        self.assertEqual(self.store.revision, 1)

    def test_only_pending_can_edit_and_revocation_does_not_fallback(self):
        record = self.add()
        record = self.service.edit(record["id"], proposal(value=12346), self.store.revision, "admin-test")
        self.approve(record)
        with self.assertRaises(RuleError):
            self.service.edit(record["id"], proposal(), self.store.revision, "admin-test")
        self.service.transition(record["id"], "revoke", self.store.revision, "admin-test", "승인 취소")
        with self.assertRaises(RuleUnavailable):
            self.snapshot().get("minimum_hourly_wage")
        self.assertEqual(len(self.store.events), 4)

    def test_legal_review_cannot_execute_as_parameter(self):
        record = self.add(kind="legal_review", key="", value=None)
        with self.assertRaises(RuleError):
            self.approve(record)
        self.service.transition(record["id"], "reviewed", self.store.revision,
                                "admin-test", "코드 수정과 회귀검증 필요: AUD-01")
        with self.assertRaises(RuleUnavailable):
            self.snapshot().get("minimum_hourly_wage")

    def test_scan_is_idempotent_pending_only_and_records_empty_failure(self):
        self.service.scan("minimum_wage", "worker")
        self.service.scan("minimum_wage", "worker")
        self.assertEqual(len(self.store.document["records"]), 1)
        self.assertEqual(self.store.document["records"][0]["status"], "pending")
        with patch.object(self.evidence, "search", return_value=[]):
            self.service.scan("minimum_wage", "worker")
        self.assertEqual(self.store.document["scans"][-1]["status"], "empty")
        with patch.object(self.evidence, "search", side_effect=RuntimeError("secret")):
            result = self.service.scan("minimum_wage", "worker")
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("secret", str(result))

    def test_scan_keeps_valid_hits_when_one_evidence_document_is_malformed(self):
        """한 검색 결과의 스키마 오류가 같은 응답의 정상 근거까지 버리면 안 된다."""
        valid = self.evidence.fetch("fixture-law")
        malformed = dict(valid, id="broken", text="", chunk_text="")
        with patch.object(self.evidence, "search", return_value=[valid, malformed]):
            result = self.service.scan("minimum_wage", "worker")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["hit_count"], 1)
        self.assertEqual(result["new_count"], 1)
        self.assertEqual(len(self.store.document["records"]), 1)

    def test_request_scope_resets_on_exception_and_has_provenance(self):
        record = self.add()
        self.approve(record)
        snapshot = self.snapshot()
        self.assertEqual(parameter("minimum_hourly_wage", 7), 7)
        try:
            with rule_scope(snapshot):
                self.assertEqual(parameter("minimum_hourly_wage", 7), 12345)
                raise RuntimeError("test")
        except RuntimeError:
            pass
        self.assertEqual(parameter("minimum_hourly_wage", 7), 7)
        self.assertEqual(snapshot.provenance()[0]["id"], record["id"])

    def test_facade_uses_approved_value_and_emits_provenance(self):
        from wage_calculator import WageCalculator, WageInput, WageType
        record = self.add()
        self.approve(record)
        inp = WageInput(wage_type=WageType.HOURLY, hourly_wage=12000,
                        reference_year=2031, reference_date="2031-06-01")
        result = WageCalculator(rule_store=self.store).calculate(inp, ["minimum_wage"])
        self.assertFalse(result.minimum_wage_ok)
        self.assertEqual(result.legal_rule_versions[0]["value"], 12345)
        self.assertEqual(result.legal_rule_status, "managed_parameters")

    def test_missing_approval_date_or_store_blocks_without_amounts(self):
        from wage_calculator import WageCalculator, WageInput, WageType
        from wage_calculator.result import format_result, format_result_json
        # 오늘(무지정)·승인 밖 날짜·형식 오류 모두 금액 없이 보류된다.
        # 무지정은 '날짜를 못 정해서'가 아니라 '오늘에 승인된 기준이 없어서' 보류다.
        for day in (None, "2031-06-01", "not-a-date"):
            inp = WageInput(wage_type=WageType.HOURLY, hourly_wage=12000, reference_date=day)
            result = WageCalculator(rule_store=self.store).calculate(inp, ["minimum_wage"])
            self.assertEqual(result.legal_rule_status, "blocked")
            self.assertEqual(result.monthly_total, 0)
            self.assertIn("계산 보류", format_result(result))
            self.assertIsNone(format_result_json(result)["minimum_wage_ok"])
        valid = WageInput(wage_type=WageType.HOURLY, hourly_wage=12000,
                          reference_date="2031-06-01")
        with patch.object(self.store, "load", side_effect=RuntimeError("private")) as load:
            result = WageCalculator(rule_store=self.store).calculate(valid, ["minimum_wage"])
        load.assert_called_once_with()
        self.assertEqual(result.legal_rule_status, "blocked")
        self.assertNotIn("private", format_result(result))

    def test_unspecified_date_resolves_to_today_but_other_year_still_needs_a_date(self):
        """R2: 기준일 무지정은 오늘. '연도만으로 추정 금지'는 오늘이 속하지 않는 연도에만 적용."""
        from wage_calculator import WageCalculator, WageInput, WageType
        from wage_calculator.legal_rules import kst_today, resolve_reference_date
        today = kst_today()
        this_year = int(today[:4])

        self.assertEqual(resolve_reference_date(None), today)
        self.assertEqual(resolve_reference_date(None, this_year), today)
        self.assertEqual(resolve_reference_date("2031-06-01", 2031), "2031-06-01")
        with self.assertRaises(RuleUnavailable):
            resolve_reference_date(None, this_year - 3)

        # KST 새해 첫 9시간에 UTC 서버가 전년이어도, 전년 지정값을 오늘로 바꾸면 안 된다.
        with patch("wage_calculator.legal_rules.kst_today", return_value="2027-01-01"):
            with self.assertRaises(RuleUnavailable):
                resolve_reference_date(None, 2026)

        # 오늘 구간에 승인된 기준이 있으면 날짜를 말하지 않아도 계산이 나온다.
        self.approve(self.add(effective_from=today, effective_to=None))
        inp = WageInput(wage_type=WageType.MONTHLY, use_minimum_wage=True)
        result = WageCalculator(rule_store=self.store).calculate(inp, ["minimum_wage"])
        self.assertEqual(result.legal_rule_status, "managed_parameters")
        self.assertEqual(result.legal_reference_date, today)
        self.assertEqual(result.ordinary_hourly, 12345)

        # 같은 승인 상태라도 다른 연도를 지목하면 기준일을 요구한다(추정 금지 원칙 유지).
        past = WageInput(wage_type=WageType.MONTHLY, use_minimum_wage=True,
                         reference_year=this_year - 3)
        blocked = WageCalculator(rule_store=self.store).calculate(past, ["minimum_wage"])
        self.assertEqual(blocked.legal_rule_status, "blocked")
        self.assertIn("계산 기준일", blocked.warnings[0])

    def _insurance_store(self, skip=None):
        """보험 8개 기준을 승인하되 skip 한 건만 빠뜨린다."""
        from wage_calculator.constants import INSURANCE_RATES
        for key, value in INSURANCE_RATES[2026].items():
            if key == skip:
                continue
            self.approve(self.add(topic="insurance", key="insurance." + key, value=value))
        return self.store

    def test_one_missing_rule_blocks_only_its_own_section(self):
        """R3: 승인 누락은 그 섹션만 뺀다 — 같은 요청의 다른 계산까지 버리지 않는다."""
        from wage_calculator import WageCalculator, WageInput, WageType
        from wage_calculator.result import format_result, format_result_json
        self._insurance_store(skip="health_premium_min")
        inp = WageInput(wage_type=WageType.MONTHLY, monthly_wage=3_000_000,
                        reference_year=2031, reference_date="2031-06-01")

        r = WageCalculator(rule_store=self.store).calculate(inp, ["overtime", "insurance"])
        self.assertNotEqual(r.legal_rule_status, "blocked")
        self.assertEqual([b["target"] for b in r.legal_rule_blocked], ["insurance"])
        self.assertEqual(r.legal_rule_attempted, 2)
        self.assertIn("연장·야간·휴일수당", r.breakdown)      # 무관한 계산은 살아남는다
        self.assertNotIn("4대보험·소득세", r.breakdown)
        text = format_result(r)
        self.assertIn("보류된 계산", text)
        self.assertIn("4대보험·소득세", text)
        self.assertEqual(format_result_json(r)["legal_rule_blocked"], r.legal_rule_blocked)

        # 보류된 섹션이 읽은 기준 7건은 '적용된 버전'으로 남으면 안 된다.
        self.assertEqual(r.legal_rule_versions, [])

    def test_all_sections_blocked_still_reports_request_level_hold(self):
        """부분 결과가 하나도 없으면 통상임금 껍데기가 아니라 '계산 보류'다."""
        from wage_calculator import WageCalculator, WageInput, WageType
        from wage_calculator.result import format_result
        self._insurance_store(skip="health_premium_min")
        inp = WageInput(wage_type=WageType.MONTHLY, monthly_wage=3_000_000,
                        reference_year=2031, reference_date="2031-06-01")
        r = WageCalculator(rule_store=self.store).calculate(inp, ["insurance"])
        self.assertEqual(r.legal_rule_status, "blocked")
        self.assertEqual(r.monthly_total, 0)
        self.assertIn("계산 보류", format_result(r))

    def test_blocked_minimum_wage_does_not_leave_a_false_verdict(self):
        """최저임금 기준이 없으면 기본값 True 가 '충족'으로 새면 안 된다."""
        from wage_calculator import WageCalculator, WageInput, WageType
        from wage_calculator.result import format_result
        self._insurance_store()          # 보험만 승인, 최저시급은 미승인
        inp = WageInput(wage_type=WageType.MONTHLY, monthly_wage=3_000_000,
                        reference_year=2031, reference_date="2031-06-01")
        r = WageCalculator(rule_store=self.store).calculate(inp, ["minimum_wage", "insurance"])
        self.assertIn("minimum_wage", [b["target"] for b in r.legal_rule_blocked])
        self.assertIsNone(r.minimum_wage_ok)
        self.assertIn("판정 보류", format_result(r))
        self.assertNotIn("최저임금 충족: ✅", format_result(r))
        self.assertIn("4대보험·소득세", r.breakdown)          # 보험은 정상 산출

    def test_blocked_comprehensive_does_not_leave_a_false_minimum_wage_verdict(self):
        """포괄임금 역산이 최저시급 누락으로 빠지면 기본 True 판정도 함께 버린다."""
        from wage_calculator import WageCalculator, WageInput, WageType
        from wage_calculator.result import format_result
        inp = WageInput(wage_type=WageType.COMPREHENSIVE, monthly_wage=3_000_000,
                        reference_year=2031, reference_date="2031-06-01")
        result = WageCalculator(rule_store=self.store).calculate(
            inp, ["overtime", "comprehensive"])
        self.assertEqual([b["target"] for b in result.legal_rule_blocked], ["comprehensive"])
        self.assertIsNone(result.minimum_wage_ok)
        self.assertIn("판정 보류", format_result(result))
        self.assertNotIn("최저임금 충족: ✅", format_result(result))

    def test_unperformed_minimum_wage_check_has_no_success_default(self):
        """최저임금 검사를 실행하지 않은 결과를 충족으로 표시하지 않는다."""
        from wage_calculator.result import WageResult, format_result
        result = WageResult(ordinary_hourly=15000)
        self.assertIsNone(result.minimum_wage_ok)
        self.assertIn("최저임금 충족: ⏸ 판정 보류", format_result(result))
        self.assertNotIn("최저임금 충족: ✅", format_result(result))

    def test_maternity_conflicting_approved_floor_and_cap_blocks_section(self):
        """승인 하한이 승인 상한보다 높으면 어느 금액도 법정값으로 선택하지 않는다."""
        from wage_calculator import WageCalculator, WageInput, WageType
        self.approve(self.add(value=20000))
        self.approve(self.add(
            topic="maternity_leave", key="maternity.monthly_upper", value=2_000_000,
        ))
        inp = WageInput(wage_type=WageType.MONTHLY, monthly_wage=3_000_000,
                        reference_year=2031, reference_date="2031-06-01")
        result = WageCalculator(rule_store=self.store).calculate(inp, ["maternity_leave"])
        self.assertEqual(result.legal_rule_status, "blocked")
        self.assertEqual(result.monthly_total, 0)
        self.assertIn("상한", result.warnings[0])
        self.assertIn("하한", result.warnings[0])

    def test_status_says_managed_only_when_an_approved_value_was_actually_used(self):
        """R4: provenance가 비면 managed로 부르지 않는다 — 내장표 수치가 법적 검증으로 오독된다."""
        from wage_calculator import WageCalculator, WageInput, WageType
        from wage_calculator.result import format_result, format_result_json
        self.approve(self.add())
        inp = WageInput(wage_type=WageType.MONTHLY, monthly_wage=3_000_000,
                        reference_year=2031, reference_date="2031-06-01")

        # 연장수당은 11개 관리 키를 하나도 읽지 않는다 → 상태·표시가 달라야 한다.
        unused = WageCalculator(rule_store=self.store).calculate(inp, ["overtime"])
        self.assertEqual(unused.legal_rule_status, "managed_no_parameters")
        self.assertEqual(unused.legal_rule_versions, [])
        self.assertEqual(unused.legal_reference_date, "2031-06-01")
        self.assertGreater(unused.ordinary_hourly, 0)          # 계산 자체는 정상
        text = format_result(unused)
        self.assertNotIn("수치 기준 적용일", text)
        self.assertIn("승인 수치 기준 없음", text)

        # 최저임금은 읽는다 → 적용일·버전 표기가 붙는다.
        used = WageCalculator(rule_store=self.store).calculate(inp, ["minimum_wage"])
        self.assertEqual(used.legal_rule_status, "managed_parameters")
        self.assertEqual([v["key"] for v in used.legal_rule_versions], ["minimum_hourly_wage"])
        self.assertIn("수치 기준 적용일", format_result(used))
        self.assertEqual(format_result_json(used)["legal_rule_status"], "managed_parameters")

    def test_comprehensive_and_minimum_wage_share_one_approved_minimum(self):
        """R1: 두 계산기가 같은 최저시급 출처를 써야 한 응답 안에서 모순되지 않는다."""
        from wage_calculator import WageCalculator, WageInput, WageType
        self.approve(self.add(value=99999))
        inp = WageInput(wage_type=WageType.COMPREHENSIVE, monthly_wage=3_000_000,
                        reference_year=2031, reference_date="2031-06-01")
        result = WageCalculator(rule_store=self.store).calculate(inp, ["comprehensive", "minimum_wage"])
        self.assertEqual(result.legal_rule_status, "managed_parameters")
        section = result.breakdown["포괄임금제 역산"]
        self.assertEqual(section["2031년 최저임금"], "99,999원")
        self.assertEqual(section["최저임금 충족"], "❌")
        self.assertFalse(result.minimum_wage_ok)

    def test_managed_minimum_wage_input_and_original_input_preserved(self):
        from wage_calculator import WageCalculator, WageInput, WageType
        self.approve(self.add())
        inp = WageInput(wage_type=WageType.MONTHLY, reference_year=2031,
                        reference_date="2031-06-01", use_minimum_wage=True)
        result = WageCalculator(rule_store=self.store).calculate(inp, ["minimum_wage"])
        self.assertEqual(result.ordinary_hourly, 12345)
        self.assertIsNone(inp.hourly_wage)
        self.assertEqual(inp.wage_type, WageType.MONTHLY)

    def test_official_rule_pipeline_produces_approvable_metadata(self):
        """R11: 수집→적재 산출물이 승인 게이트를 통과하는 모양인지 (네트워크 없이)."""
        from app.core.legal_updates import official_evidence, evidence_snapshot
        import pinecone_upload_official_rules as up

        doc = {"doc_id": "mw_notice", "source_type": "regulation",
               "title": "2026년 적용 최저임금 고시 (고용노동부)",
               "official_url": "https://www.law.go.kr/%ED%96%89%EC%A0%95%EA%B7%9C%EC%B9%99/x",
               "issuer": "고용노동부", "date": "20260101",
               "keys": ["minimum_hourly_wage"],
               "body": "모든산업 10,320원"}
        vectors = up.build_vectors(doc)
        self.assertEqual([v["id"] for v in vectors], ["official_mw_notice_0"])
        # PineconeEvidence._document() 가 붙이는 것과 같은 모양으로 만든다.
        meta = dict(vectors[0]["metadata"], namespace="laborlaw-v2", id=vectors[0]["id"])
        snap = evidence_snapshot(meta)
        official_evidence(snap)                      # 통과하지 못하면 예외
        # 공식 전용 검색이 이 표식으로 문서를 찾는다 — 빠지면 신규 문서가
        # 수만 벡터에 묻혀 자동 검색이 후보를 못 만든다.
        self.assertIs(meta["official"], True)
        # text/chunk_text 이중 폴백: 적재 시기가 다른 스키마가 섞여 있어 한쪽만
        # 쓰면 검색은 되는데 답변 컨텍스트에서 조용히 사라진다.
        self.assertEqual(meta["text"], meta["chunk_text"])

    def test_article_collection_uses_official_effective_date_not_collection_date(self):
        """같은 조문을 다른 날 수집해도 수집일 때문에 새 근거로 오인하면 안 된다."""
        import fetch_official_rules as fetcher
        xml = """<법령><기본정보><법령명_한글>최저임금법</법령명_한글>
        <시행일자>20260101</시행일자></기본정보><조문단위><조문여부>조문</조문여부>
        <조문번호>5</조문번호><조문가지번호>0</조문가지번호>
        <조문내용>제5조<br /> 최저임금액</조문내용></조문단위></법령>"""
        response = SimpleNamespace(text=xml, raise_for_status=lambda: None)
        with patch.object(fetcher.requests, "get", return_value=response):
            article = fetcher.fetch_article_xml("fixture-key", "최저임금법", 5, None)
        self.assertEqual(article["body"], "제5조 최저임금액")
        self.assertEqual(article["date"], "20260101")

    def test_official_rule_docs_without_https_source_are_not_uploaded(self):
        """http·헤더 누락 문서는 올려도 승인 불가다 — 파싱 단계에서 거른다."""
        import os
        import tempfile
        import pinecone_upload_official_rules as up

        body = "## 본문\n\n제1조 본문"
        cases = {
            "http만 있음": "- doc_id: x\n- source_type: law\n- title: T\n"
                          "- official_url: http://www.law.go.kr/a\n",
            "official_url 없음": "- doc_id: x\n- source_type: law\n- title: T\n",
            "본문 없음": "- doc_id: x\n- source_type: law\n- title: T\n"
                       "- official_url: https://www.law.go.kr/a\n",
            "잘못된 문서 ID": "- doc_id: Bad-ID\n- source_type: law\n- title: T\n"
                            "- official_url: https://www.law.go.kr/a\n",
        }
        with tempfile.TemporaryDirectory() as tmp:
            for label, head in cases.items():
                path = os.path.join(tmp, "d.md")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(head + ("" if label == "본문 없음" else "\n" + body))
                with self.subTest(label=label):
                    self.assertIsNone(up.parse_doc(path))

    def test_insurance_parameter_keys_match_the_rate_table_exactly(self):
        """R9: get_insurance_rates()가 legacy dict의 **모든** 키를 parameter()로 조회한다.

        요율 항목을 늘리면서 PARAMETERS를 안 늘리면 관리 모드에서 보험 계산이 영구
        보류된다 — 예외도 로그도 없는 조용한 실패라 이 단언이 유일한 탐지 수단이다.
        """
        from wage_calculator.constants import INSURANCE_RATES
        from wage_calculator.legal_rules import PARAMETERS
        registered = {k.split(".", 1)[1] for k in PARAMETERS if k.startswith("insurance.")}
        for year, rates in INSURANCE_RATES.items():
            with self.subTest(year=year):
                self.assertEqual(set(rates), registered)

    def test_history_keeps_the_changed_record_without_copying_the_source_text(self):
        """R8: 이력에 registry 전량·근거 원문을 복제하면 revision 수만큼 배로 늘어난다."""
        record = self.add()
        payload = self.store.events[-1]["payload"]
        self.assertEqual([r["id"] for r in payload["records"]], [record["id"]])
        entry = payload["records"][0]
        self.assertEqual(entry["evidence"]["sha256"], record["evidence"]["sha256"])
        self.assertNotIn("text", entry["evidence"])     # 원문은 id+sha256으로 되짚는다
        self.assertNotIn("records", entry)              # 문서 전량이 섞여 들어오지 않는다
        self.approve(record)
        self.assertEqual(self.store.events[-1]["payload"]["records"][0]["status"], "approved")

        # 검색은 이번 실행에서 **새로 만든** 후보만 담는다(기존 후보 재복제 금지).
        self.service.scan("minimum_wage", "worker")
        self.assertEqual(len(self.store.events[-1]["payload"]["records"]), 1)
        self.service.scan("minimum_wage", "worker")
        self.assertEqual(self.store.events[-1]["payload"]["records"], [])

    def test_insurance_parameters_do_not_mutate_static_table(self):
        from wage_calculator.constants import get_insurance_rates, INSURANCE_RATES
        baseline = deepcopy(INSURANCE_RATES)
        for key, value in INSURANCE_RATES[2026].items():
            record = self.add(topic="insurance", key="insurance." + key,
                              value=0.05 if key == "national_pension" else value)
            self.approve(record)
        with rule_scope(self.snapshot()):
            self.assertEqual(get_insurance_rates(2031)["national_pension"], 0.05)
        self.assertEqual(INSURANCE_RATES, baseline)

    def test_pipeline_preserves_reference_date_and_blocks_missing_date(self):
        import app.core.pipeline as pipeline
        from wage_calculator import WageCalculator
        self.approve(self.add())
        analysis = SimpleNamespace(requires_calculation=True, calculation_types=["minimum_wage"],
            extracted_info={"use_minimum_wage": True, "reference_year": 2031,
                            "reference_date": "2031-06-01"})
        params = pipeline._analysis_to_extract_params(analysis)
        with patch.dict("os.environ", {"LEGAL_RULES_ENABLED": "true"}), patch.object(
            pipeline, "WageCalculator", return_value=WageCalculator(rule_store=self.store)
        ):
            result = pipeline._run_calculator(params)
            self.assertIn("12,345", result)
            params.pop("reference_date")
            self.assertIn("계산 보류", pipeline._run_calculator(params))

    def test_pipeline_labels_dated_hold_as_non_numeric_guidance(self):
        """기준일이 삽입된 보류 문구도 사용 가능한 계산 결과로 오인하지 않는다."""
        import app.core.pipeline as pipeline
        heading = pipeline._calculation_context_heading(
            "계산 보류 (기준일 2031-06-01): 승인 기준이 없습니다")
        self.assertIn("금액 추정 금지", heading)
        self.assertNotIn("이 수치를 사용하세요", heading)

    def test_admin_listing_omits_source_text_and_detail_returns_it(self):
        """R7: 후보마다 최대 5만자 원문을 목록에 실으면 응답 한도를 넘겨 화면이 멈춘다."""
        from api.legal_updates import listing
        record = self.add()
        _, document = self.store.load()
        listed = listing(document)["records"][0]
        self.assertNotIn("text", listed["evidence"])
        self.assertEqual(listed["evidence"]["text_length"], len(record["evidence"]["text"]))
        self.assertEqual(listed["evidence"]["sha256"], record["evidence"]["sha256"])
        self.assertEqual(listed["id"], record["id"])
        # 상세 조회는 저장된 원문을 그대로 돌려준다(Pinecone 현재본이 아니라 승인 근거).
        self.assertEqual(self.service._find(document, record["id"])["evidence"]["text"],
                         record["evidence"]["text"])

    def test_analyzer_passes_explicit_reference_date_to_calculation(self):
        from app.core.analyzer import _build_analysis_result
        result = _build_analysis_result({"requires_calculation": True, "reference_date": "2031-06-01"})
        self.assertEqual(result.extracted_info.get("reference_date"), "2031-06-01")

    def test_batch_continues_after_failure_and_never_approves(self):
        from sync_legal_rules import scan_topics, scan_exit_code
        with patch.object(self.service, "scan", side_effect=[RuntimeError("private"),
                           {"topic": "annual_leave", "status": "completed", "new_count": 1}]):
            results = scan_topics(self.service, ["minimum_wage", "annual_leave"])
        self.assertEqual([r["status"] for r in results], ["failed", "completed"])
        self.assertNotIn("private", str(results))
        self.assertEqual(scan_exit_code([{"status": "completed"}]), 0)
        self.assertEqual(scan_exit_code([{"status": "partial"}]), 1)
        self.assertEqual(scan_exit_code([{"status": "failed"}]), 1)

    def test_llm_fact_blocks_use_approved_values_not_hardcoded_amounts(self):
        import app.core.pipeline as pipeline
        self.approve(self.add())
        analysis = SimpleNamespace(extracted_info={"reference_date": "2031-06-01"}, calculation_types=[])
        with patch.dict("os.environ", {"LEGAL_RULES_ENABLED": "true"}), patch(
            "app.core.legal_rule_store.configured_store", return_value=self.store
        ):
            block = pipeline._build_minwage_facts("최저임금", analysis)
            self.assertIn("12,345", block)
            self.assertNotIn("10,320", block)
            analysis.extracted_info = {}
            block = pipeline._build_minwage_facts("최저임금", analysis)
            self.assertIn("확인 필요", block)
            self.assertNotIn("10,320", block)

    def test_parallel_request_snapshots_are_isolated(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        self.approve(self.add(effective_to="2031-07-01"))
        self.approve(self.add(effective_from="2031-07-01", value=12346))
        barrier = Barrier(2)

        def calculate(day):
            with rule_scope(self.snapshot(day)):
                barrier.wait(timeout=3)
                return parameter("minimum_hourly_wage", 0)

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(calculate, ["2031-06-30", "2031-07-01"])), [12345, 12346])
        self.assertEqual(parameter("minimum_hourly_wage", 7), 7)

    def test_optional_note_stays_valid_through_approval(self):
        payload = proposal()
        payload.pop("note")
        record = self.service.create(payload, 0, "admin-test")
        self.approve(record)
        self.assertEqual(self.snapshot().get("minimum_hourly_wage"), 12345)

    def test_rejected_record_cannot_be_approved_and_new_version_can_restore(self):
        record = self.add()
        self.service.transition(record["id"], "reject", self.store.revision, "admin-test", "근거 재검토 필요")
        with self.assertRaises(RuleError):
            self.approve(record)
        self.approve(self.add())
        self.assertEqual(self.snapshot().get("minimum_hourly_wage"), 12345)

    def test_builtin_parameter_covers_every_connected_key(self):
        """어느 키 하나라도 None 이면 그 입력란만 현재값 없이 남아, 오입력 경고가 조용히 꺼진다."""
        from wage_calculator.constants import builtin_parameter
        for key in PARAMETERS:
            self.assertIsInstance(builtin_parameter(key, 2026), (int, float), key)
        self.assertIsNone(builtin_parameter("not.a.key", 2026))

    def test_admin_preview_and_calculator_read_the_same_builtin_value(self):
        """관리 화면의 '현재 적용값'이 계산기와 갈리면 대조 장치가 거짓말을 한다.

        연금 기준소득월액은 **연중 7월**에 바뀌므로 연도만으로 읽으면 하반기 내내
        어긋난다(2026-07-01 기준 6,370,000 vs 6,590,000).
        """
        from wage_calculator.calculators.maternity_leave import MATERNITY_LEAVE_UPPER
        from wage_calculator.constants import (MINIMUM_HOURLY_WAGE, PLATFORM_MATERNITY_UPPER,
                                               builtin_parameter, get_insurance_rates,
                                               get_minimum_hourly_wage)
        # 계산기가 실제로 읽는 값. 11개 키 **전부**를 본다 — insurance.* 만 검사하면
        # 미래 연도에서 갈리는 maternity 폴백을 놓친다(실측 2027년 불일치).
        def calculator_value(key, year):
            if key == "minimum_hourly_wage":
                return get_minimum_hourly_wage(year)
            if key == "maternity.platform_upper":
                return PLATFORM_MATERNITY_UPPER
            if key == "maternity.monthly_upper":
                return MATERNITY_LEAVE_UPPER.get(year, MATERNITY_LEAVE_UPPER[max(MATERNITY_LEAVE_UPPER)])
            return None

        for year, day in ((2026, "2026-03-01"), (2026, "2026-07-01"), (2026, "2026-12-31"),
                          (2027, "2027-05-01"), (2031, "2031-01-01")):
            rates = get_insurance_rates(year, day)      # rule_scope 없음 → 내장표 경로
            for key in PARAMETERS:
                expected = (rates[key[10:]] if key.startswith("insurance.")
                            else calculator_value(key, year))
                with self.subTest(day=day, key=key):
                    self.assertEqual(builtin_parameter(key, year, day), expected)


if __name__ == "__main__":
    unittest.main()
