"""Q2 transaction tests: partial failures must never remove older chunks."""
import importlib.util
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

class Index:
    def __init__(self):
        self.rows = {"ctx_qa_123_c0": {"id": "ctx_qa_123_c0", "values": [1., 0.],
                                     "metadata": {"url": "https://www.nodong.kr/qna/123", "version": "old"}},
                     "ctx_qa_123_c1": {"id": "ctx_qa_123_c1", "values": [0., 1.],
                                     "metadata": {"url": "https://www.nodong.kr/qna/123"}},
                     "ctx_qa_case_123_c0": {"id": "ctx_qa_case_123_c0", "values": [1., 1.], "metadata": {}}}
        self.fail = False
    def list(self, *, namespace, prefix="", limit=None):
        yield [k for k in self.rows if k.startswith(prefix)]
    def fetch(self, *, ids, namespace):
        return {"vectors": {k:self.rows[k] for k in ids if k in self.rows}}
    def upsert(self, *, vectors, namespace):
        if self.fail:
            raise RuntimeError("interrupted upload")
        self.rows.update({v["id"]: v for v in vectors})
    def delete(self, *, ids, namespace):
        for key in ids:
            self.rows.pop(key, None)

class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("qna_vectors"), "document transaction not implemented")
        import qna_vectors
        self.q = qna_vectors

    def test_partial_failure_preserves_all_previous_chunks(self):
        index = Index()
        index.fail = True
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                self.q.replace_document(index, "qa-eval-test", "123", self.vectors(), Path(tmp))
            self.assertEqual(len(index.rows), 3)
            self.assertTrue((Path(tmp)/"123"/"before.json").exists())
            self.assertFalse((Path(tmp)/"123"/"complete.json").exists())

    def vectors(self):
        return [{"id": "ctx_qa_123_c0", "values": [0.5, 0.5],
                 "metadata": {"url": "https://www.nodong.kr/qna/123", "document_version": "new"}}]

    def test_smaller_document_removes_only_its_own_stale_chunks_and_restores(self):
        index = Index()
        with tempfile.TemporaryDirectory() as tmp:
            self.q.replace_document(index, "qa-eval-test", "123", self.vectors(), Path(tmp))
            self.assertEqual(set(index.rows), {"ctx_qa_123_c0", "ctx_qa_case_123_c0"})
            self.assertEqual(index.rows["ctx_qa_123_c0"]["metadata"]["document_version"], "new")
            self.q.restore_document(index, "qa-eval-test", "123", Path(tmp))
            self.assertEqual(set(index.rows), {"ctx_qa_123_c0", "ctx_qa_123_c1", "ctx_qa_case_123_c0"})
            self.assertEqual(index.rows["ctx_qa_123_c0"]["metadata"]["version"], "old")

    def test_resume_keeps_original_preimage(self):
        index = Index()
        with tempfile.TemporaryDirectory() as tmp:
            self.q.replace_document(index, "qa-eval-test", "123", self.vectors(), Path(tmp))
            self.q.replace_document(index, "qa-eval-test", "123", self.vectors(), Path(tmp))
            self.q.restore_document(index, "qa-eval-test", "123", Path(tmp))
            self.assertEqual(index.rows["ctx_qa_123_c0"]["metadata"]["version"], "old")

    def test_rejects_other_document_ids_and_empty_replacement(self):
        index = Index()
        with tempfile.TemporaryDirectory() as tmp:
            for vectors in [[], [{"id": "ctx_qa_124_c0", "values": [1., 0.], "metadata": {}}]]:
                with self.assertRaises(ValueError):
                    self.q.replace_document(index, "qa-eval-test", "123", vectors, Path(tmp))
            self.assertEqual(len(index.rows), 3)

    def test_restore_refuses_a_later_unrelated_revision(self):
        index=Index()
        with tempfile.TemporaryDirectory() as tmp:
            self.q.replace_document(index,"qa-eval-test","123",self.vectors(),Path(tmp))
            index.rows["ctx_qa_123_c0"]["metadata"]["document_version"]="later-release"
            with self.assertRaises(ValueError):
                self.q.restore_document(index,"qa-eval-test","123",Path(tmp))
            self.assertEqual(index.rows["ctx_qa_123_c0"]["metadata"]["document_version"],"later-release")

    def test_production_namespace_requires_explicit_switch(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                self.q.replace_document(Index(), "qa", "123", self.vectors(), Path(tmp))

    def test_failed_reverification_does_not_leave_completion_marker(self):
        index = Index()
        with tempfile.TemporaryDirectory() as tmp:
            self.q.replace_document(index, "qa-eval-test", "123", self.vectors(), Path(tmp))
            index.fail = True
            with self.assertRaises(RuntimeError):
                self.q.replace_document(index, "qa-eval-test", "123", self.vectors(), Path(tmp))
            self.assertFalse((Path(tmp)/"123"/"complete.json").exists())

    def test_unconfirmed_upsert_never_prunes(self):
        index = Index()
        index.upsert = lambda **kwargs: None
        with tempfile.TemporaryDirectory() as tmp, patch("qna_vectors.time.sleep"):
            with self.assertRaises(RuntimeError):
                self.q.replace_document(index, "qa-eval-test", "123", self.vectors(), Path(tmp))
            self.assertIn("ctx_qa_123_c1", index.rows)

    def test_mixed_source_preimage_is_rejected(self):
        index = Index()
        index.rows["ctx_qa_123_c0"]["metadata"]["url"] = "https://elsewhere.test/123"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                self.q.replace_document(index, "qa-eval-test", "123", self.vectors(), Path(tmp))
            self.assertEqual(len(index.rows), 3)

    def test_id_pagination_uses_supported_maximum(self):
        class Limited:
            def list(self, *, namespace, prefix, limit):
                if limit > 100:
                    raise ValueError("400 maximum limit 100")
                yield ["a"]
                yield ["b"]
        self.assertEqual(self.q.list_ids(Limited(), "qa-eval-before"), ["a", "b"])

    def test_long_ids_are_fetched_within_uri_length_budget(self):
        calls=[]
        class Limited:
            def fetch(self, *, ids, namespace):
                calls.append(ids)
                if sum(len(k)+6 for k in ids)>4000:
                    raise ValueError("414 URI too long")
                return {"vectors":{k:{"id":k,"values":[0.1],"metadata":{}} for k in ids}}
        ids=[f"long-document-{i}-" + "x"*100 for i in range(500)]
        try:
            rows=self.q.fetch_vectors(Limited(),"laborlaw-v2",ids)
        except ValueError:
            self.fail("fetch exceeded URI budget")
        self.assertEqual(set(rows),set(ids))
        self.assertGreater(len(calls),1)

if __name__ == "__main__":
    unittest.main()
