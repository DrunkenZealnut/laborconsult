"""Candidate materialization and sparse snapshot safety."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from qna_ingestion import document

class CorpusTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("qna_corpus"), "candidate materialization missing")
        import qna_corpus
        self.q = qna_corpus

    def test_context_metadata_is_private_redacted_and_versioned(self):
        doc = document("123", "연차 질문", "2026-03-04", "연락처 010-1234-5678 입니다.", ["답변입니다."])
        chunks, texts = self.q.prepare_document(doc)
        self.assertEqual(len(chunks), len(texts))
        self.assertTrue(all("010-1234-5678" not in t for t in texts))
        vectors = self.q.make_vectors(doc, chunks, [[0.1]*1536 for _ in chunks])
        self.assertEqual(vectors[0]["metadata"]["corpus_origin"], "nodong_qna")
        self.assertEqual(vectors[0]["metadata"]["document_version"], doc["content_hash"])
        self.assertEqual(vectors[0]["metadata"]["posted_at"], "2026-03-04")

    def test_short_embedding_response_cannot_silently_omit_chunks(self):
        doc = document("123", "질문", "2026-03-04", "질문", ["답변"])
        chunks, texts = self.q.prepare_document(doc)
        with self.assertRaises(ValueError):
            self.q.make_vectors(doc, chunks, [[0.1]*1536])

    def test_unanswered_document_has_no_login_chunk(self):
        doc = document("123", "질문", "2026-03-04", "실제 질문", [])
        chunks, _ = self.q.prepare_document(doc)
        self.assertEqual(len(chunks), 1)
        v = self.q.make_vectors(doc, chunks, [[0.1]*1536])
        self.assertEqual(v[0]["metadata"]["answer_status"], "unanswered")
        self.assertEqual(v[0]["metadata"]["section"], "질문")

    def test_legacy_origin_requires_canonical_url(self):
        row = {"id":"ctx_qa_123_c0", "values":[0.1], "metadata":{"source_type":"qa","url":"https://www.nodong.kr/qna/123","text":"본문"}}
        enriched = self.q.enrich_baseline(row, "qa")
        self.assertEqual(enriched["metadata"]["post_id"], "123")
        self.assertEqual(enriched["values"], [0.1])
        other = {**row, "metadata":{"source_type":"qa","url":"https://example.org/123","text":"다른 자료"}}
        self.assertNotIn("corpus_origin", self.q.enrich_baseline(other,"qa")["metadata"])

    def test_legacy_chunks_do_not_claim_different_document_versions(self):
        versions = []
        for i in range(2):
            row = {"id":f"ctx_qa_123_c{i}", "values":[0.1], "metadata":{
                "source_type":"qa", "url":"https://www.nodong.kr/qna/123", "text":f"청크 {i}"}}
            versions.append(self.q.enrich_baseline(row, "qa")["metadata"]["document_version"])
        self.assertEqual(versions[0], versions[1])

if __name__ == "__main__":
    unittest.main()
