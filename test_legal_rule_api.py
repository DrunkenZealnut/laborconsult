"""HTTP auth, mutation and real adapter boundaries; no external services."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from api.legal_updates import build_legal_router
from app.core.legal_updates import LegalUpdateService, Conflict, EvidenceError
from app.core.legal_rule_store import PineconeEvidence, SupabaseRuleStore
from test_legal_rule_updates import MemoryStore, Evidence, proposal


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.store, self.evidence = MemoryStore(), Evidence()
        self.store.events = []
        self.service = LegalUpdateService(self.store, self.evidence)

        def auth(authorization: str = Header(None)):
            if authorization != "Bearer test-token":
                raise HTTPException(401, "인증 필요")
            return {"role": "admin", "jti": "test-session"}

        app = FastAPI()
        app.include_router(build_legal_router(auth, lambda: self.service))
        self.client = TestClient(app)
        self.headers = {"Authorization": "Bearer test-token"}

    def test_all_endpoints_require_auth_before_store_or_evidence_access(self):
        for method, path, body in (
            ("GET", "", None), ("GET", "/events", None), ("GET", "/evidence?id=fixture-law", None),
            ("GET", "/documents", None),
            ("POST", "/scan", {"topic": "minimum_wage"}),
            ("POST", "/candidates", {"revision": 0, "payload": proposal()}),
            ("PUT", "/candidates/unknown", {"revision": 0, "payload": proposal()}),
            ("POST", "/candidates/unknown/approve", {"revision": 0, "note": "검토 완료"}),
        ):
            response = self.client.request(method, "/api/admin/legal-rules" + path, json=body)
            self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(self.store.revision, 0)

    def test_lifecycle_and_revision_conflict_over_http(self):
        response = self.client.post("/api/admin/legal-rules/candidates", headers=self.headers,
                                    json={"revision": 0, "payload": proposal()})
        self.assertEqual(response.status_code, 200, response.text)
        record_id = response.json()["record"]["id"]
        path = f"/api/admin/legal-rules/candidates/{record_id}/approve"
        stale = self.client.post(path, headers=self.headers, json={"revision": 0, "note": "원문 대조 완료"})
        self.assertEqual(stale.status_code, 409)
        approved = self.client.post(path, headers=self.headers, json={"revision": 1, "note": "원문 대조 완료"})
        self.assertEqual(approved.status_code, 200, approved.text)
        result = self.client.get("/api/admin/legal-rules", headers=self.headers).json()
        self.assertEqual(result["revision"], 2)
        self.assertEqual(result["records"][0]["status"], "approved")
        self.assertTrue(result["parameters"])
        self.assertEqual(len(result["topics"]), 28)
        # 입력란 옆 '현재 적용값'의 출처. 승인 직후 그 키만 승인값으로 바뀌어야 한다.
        current = result["current"]["values"]["minimum_hourly_wage"]
        self.assertEqual(current["approved"], None, "오늘은 2031년 구간 밖이다")
        self.assertIsNotNone(current["builtin"])
        self.assertEqual(result["current"]["total"], len(result["parameters"]))

    def test_official_document_catalog_replaces_hand_typed_vector_ids(self):
        response = self.client.get("/api/admin/legal-rules/documents", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        documents = response.json()["documents"]
        self.assertEqual(documents[0]["id"], "fixture-law")
        self.assertEqual(documents[0]["rule_keys"], ["minimum_hourly_wage"])

    def test_document_catalog_failure_degrades_to_manual_entry_instead_of_breaking(self):
        """목록을 못 받아도 문서 ID 직접 입력으로 계속 쓸 수 있어야 한다 —
        여기서 422를 올리면 개선하려던 화면이 오히려 멈춘다."""
        self.evidence.catalog = Mock(side_effect=EvidenceError("Pinecone 연결 실패"))
        response = self.client.get("/api/admin/legal-rules/documents", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["documents"], [])
        self.assertIn("직접 입력", response.json()["detail"])

    def test_invalid_body_and_private_failure_are_not_exposed(self):
        for body in ({"revision": True, "payload": proposal()},
                     {"revision": 0, "payload": proposal(), "approved": True}):
            response = self.client.post("/api/admin/legal-rules/candidates", headers=self.headers, json=body)
            self.assertEqual(response.status_code, 422)
        self.store.load = Mock(side_effect=RuntimeError("private-key"))
        response = self.client.get("/api/admin/legal-rules", headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private-key", response.text)

    def test_event_history_endpoint_returns_saved_actor_and_action(self):
        self.store.events = Mock(return_value=[{"revision": 2, "actor": "admin-session:test-session",
                                               "action": {"type": "approve"}}])
        response = self.client.get("/api/admin/legal-rules/events", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["events"][0]["action"]["type"], "approve")

    def test_real_app_registers_authenticated_routes_and_static_script(self):
        from api.index import app
        client = TestClient(app)
        self.assertEqual(client.get("/api/admin/legal-rules").status_code, 401)
        asset = client.get("/admin_legal_rules.js")
        self.assertEqual(asset.status_code, 200)
        self.assertIn("function mount", asset.text)


class AdapterTest(unittest.TestCase):
    def test_pinecone_fetch_and_search_are_namespace_and_type_scoped(self):
        index, openai = Mock(), Mock()
        index.fetch.return_value = {"vectors": {"id1": {"metadata": {
            "source_type": "law", "text": "법조문 테스트", "namespace": "qa", "url": "https://law.go.kr/x"}}}}
        index.query.return_value = {"matches": [{"id": "id1", "metadata": {"text": "원문"}}]}
        openai.with_options.return_value.embeddings.create.return_value = SimpleNamespace(data=[SimpleNamespace(embedding=[0.1])])
        adapter = PineconeEvidence(index, openai)
        doc = adapter.fetch("id1")
        self.assertEqual(doc["namespace"], "laborlaw-v2")
        index.fetch.assert_called_once_with(ids=["id1"], namespace="laborlaw-v2", timeout=15)
        adapter.search("최저임금")
        args = index.query.call_args.kwargs
        self.assertEqual(args["namespace"], "laborlaw-v2")
        self.assertNotIn("textbook", args["filter"]["source_type"]["$in"])
        # 공식 원문 전용 조회가 **따로** 돌아야 한다. 일반 검색 한 번으로는 신규
        # 공식 문서 17벡터가 수만 벡터에 묻혀 top_k 8 에 못 들고, 자동 검색이
        # 승인 가능한 후보를 한 건도 만들지 못한다(실측 2026-09-18: 24건 전부 거절).
        filters = [c.kwargs["filter"] for c in index.query.call_args_list]
        self.assertEqual(len(filters), 2, "공식 전용 조회가 빠졌다")
        self.assertTrue(any(f.get("official") is True for f in filters))
        self.assertTrue(all("source_type" in f for f in filters))
        index.fetch.return_value = {"vectors": {}}
        with self.assertRaises(EvidenceError):
            adapter.fetch("missing")

    def test_official_pass_failure_does_not_lose_general_results(self):
        """공식 전용 조회가 실패해도 일반 결과를 살리되 부분 실패를 숨기지 않는다."""
        index, openai = Mock(), Mock()
        openai.with_options.return_value.embeddings.create.return_value = SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.1])])
        index.query.side_effect = [
            {"matches": [{"id": "a", "metadata": {"text": "일반"}}]},
            RuntimeError("공식 조회 장애"),
        ]
        docs = PineconeEvidence(index, openai).search("최저임금")
        self.assertEqual([d["id"] for d in docs], ["a"])
        self.assertTrue(docs.partial)

        service = LegalUpdateService(MemoryStore(), Mock(search=Mock(return_value=docs)))
        scan = service.scan("minimum_wage", "test")
        self.assertEqual(scan["status"], "partial")

    def test_official_hits_come_first_and_duplicates_collapse(self):
        index, openai = Mock(), Mock()
        openai.with_options.return_value.embeddings.create.return_value = SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.1])])
        index.query.side_effect = [
            {"matches": [{"id": "gen", "metadata": {"text": "일반"}},
                         {"id": "off", "metadata": {"text": "공식"}}]},
            {"matches": [{"id": "off", "metadata": {"text": "공식"}}]},
        ]
        docs = PineconeEvidence(index, openai).search("최저임금")
        self.assertEqual([d["id"] for d in docs], ["off", "gen"])

    def test_catalog_prefix_matches_the_uploader_id_scheme(self):
        """접두사가 어긋나면 목록이 **빈 채로** 돌아온다 — 예외도 로그도 없는 실패다.
        업로더는 `official`, 조회는 `official_`(구분자 포함)이라 동등 비교가 아니다."""
        import re
        with open("pinecone_upload_official_rules.py", encoding="utf-8") as f:
            uploader = re.search(r'ID_PREFIX = "([^"]+)"', f.read()).group(1)
        self.assertEqual(PineconeEvidence._OFFICIAL_PREFIX, uploader + "_")

    def test_catalog_pages_the_listing_chunks_the_fetch_and_reports_truncation(self):
        index = Mock()
        index.list_paginated.side_effect = [
            SimpleNamespace(vectors=[SimpleNamespace(id="official_a_0")],
                            pagination=SimpleNamespace(next="t1")),
            SimpleNamespace(vectors=[{"id": "official_b_0"}], pagination={"next": "t2"}),
            SimpleNamespace(vectors=[], pagination=SimpleNamespace(next="t3")),  # 빈 페이지 → 종료
        ]
        index.fetch.return_value = SimpleNamespace(vectors={
            "official_a_0": SimpleNamespace(metadata={
                "source_type": "regulation", "title": "고시", "official_url": "https://www.law.go.kr/a",
                "text": "본문", "rule_keys": ["minimum_hourly_wage"]}),
            "official_b_0": SimpleNamespace(metadata={
                "source_type": "law", "title": "조문", "official_url": "https://www.law.go.kr/b",
                "chunk_text": "본문2"}),
        })
        docs = PineconeEvidence(index, Mock()).catalog()
        self.assertEqual([d["id"] for d in docs], ["official_a_0", "official_b_0"])
        self.assertEqual(docs[0]["rule_keys"], ["minimum_hourly_wage"])
        self.assertEqual(docs[1]["rule_keys"], [])          # 힌트 없는 문서도 남는다
        self.assertEqual(docs[1]["text"], "본문2")           # text/chunk_text 이중 폴백
        self.assertFalse(docs.truncated)
        # 나열 호출에 타임아웃이 없으면 서버리스 실행시간 한도까지 매달린다.
        self.assertEqual(index.list_paginated.call_args.kwargs["timeout"], 15)
        # 상한에 걸려 잘린 사실은 호출부가 알아야 한다(빈 목록과 구분 불가능하면 안 된다).
        index.list_paginated.side_effect = [
            SimpleNamespace(vectors=[SimpleNamespace(id="official_a_0")],
                            pagination=SimpleNamespace(next="t1")),
        ]
        self.assertTrue(PineconeEvidence(index, Mock()).catalog(cap=1).truncated)

    def test_supabase_cas_arguments_and_conflict_conversion(self):
        client = Mock()
        store = SupabaseRuleStore(client)
        client.schema.assert_called_once_with("laborconsult")
        client.schema.return_value.rpc.return_value.execute.return_value.data = 1
        self.assertEqual(store.save(0, {"records": [], "scans": []}, "actor",
                                    {"type": "test"}, {"records": []}), 1)
        args = client.schema.return_value.rpc.call_args.args
        self.assertEqual(args[0], "legal_rules_save")
        self.assertEqual(args[1]["expected_revision"], 0)
        # 이력에는 registry 전량이 아니라 바뀐 레코드만 간다(R8).
        self.assertEqual(args[1]["event_payload"], {"records": []})
        client.schema.return_value.rpc.return_value.execute.side_effect = RuntimeError("LEGAL_RULE_REVISION_CONFLICT")
        with self.assertRaises(Conflict):
            store.save(0, {}, "actor", {}, {})


if __name__ == "__main__":
    unittest.main()
