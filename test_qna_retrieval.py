"""Provenance must survive both retrieval paths without entering public metadata."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from app.core import rag, bm25_search
from app.core.pipeline import _build_sources_payload

META = {"title": "상담", "section": "답변", "source_type": "qa", "text": "답변 본문",
        "corpus_origin": "nodong_qna", "post_id": "123", "posted_at": "2026-03-04",
        "document_version": "version-1", "url": "https://www.nodong.kr/qna/123",
        "fetched_at": "2026-10-24T07:00:00+09:00"}

class ProvenanceTests(unittest.TestCase):
    def test_dense_to_context_preserves_version_and_date(self):
        index = SimpleNamespace(query=lambda **kw: SimpleNamespace(matches=[
            SimpleNamespace(id="ctx_qa_123_c0", score=0.9, metadata=META)]))
        hits = rag._query_namespaces(["qa"], [0.1], 5, None, index)
        self.assertEqual(hits[0].get("document_version"), "version-1")
        context, meta = rag.format_pinecone_hits(hits)
        self.assertEqual(meta[0].get("post_id"), "123")
        self.assertIn("2026-03-04", context)

    def test_bm25_retains_same_provenance(self):
        doc = bm25_search._slim({"id": "ctx_qa_123_c0", **META})
        with patch.object(bm25_search, "_bm25_corpus", [doc]), patch.object(
            bm25_search, "_bm25_index", SimpleNamespace(get_scores=lambda t: [1.0])):
            hit = bm25_search.search_bm25("답변")[0]
        self.assertEqual(hit.get("document_version"), "version-1")
        self.assertEqual(hit.get("posted_at"), "2026-03-04")

    def test_public_sources_do_not_expose_nodong_url_or_internal_identifiers(self):
        hits = _build_sources_payload([META], [])
        self.assertEqual(len(hits), 1)
        for field in ["post_id", "document_version", "corpus_origin", "url", "fetched_at"]:
            self.assertNotIn(field, hits[0])

    def test_unanswered_post_cannot_be_presented_as_advice(self):
        source={**META, "answer_status":"unanswered"}
        index=SimpleNamespace(query=lambda **kw: SimpleNamespace(matches=[
            SimpleNamespace(id="ctx_qa_123_c0", score=0.9, metadata=source)]))
        hits=rag._query_namespaces(["qa"],[0.1],5,None,index)
        context,meta=rag.format_pinecone_hits(hits)
        self.assertIn("답변 없는 질문",context)
        self.assertEqual(meta[0].get("answer_status"),"unanswered")

    def test_missing_provenance_does_not_invent_dates(self):
        context, meta = rag.format_pinecone_hits([{"id":"legacy", "title":"상담", "section":"답변",
            "source_type":"qa", "content":"내용", "score":0.8}])
        self.assertIn("시점 불명", context)
        self.assertFalse(meta[0].get("posted_at"))

if __name__ == "__main__":
    unittest.main()
