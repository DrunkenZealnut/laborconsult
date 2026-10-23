"""Offline experiment options, scoped to QA and sparse corpus selection."""
import unittest
import importlib.util
from types import SimpleNamespace
from unittest.mock import patch
from app.core import bm25_search

class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("app.core.qna_experiment"), "experiment routing missing")
        from app.core import qna_experiment
        self.q = qna_experiment

    def test_only_qa_namespace_is_remapped_and_filter_is_combined(self):
        seen = []
        index = SimpleNamespace(query=lambda **kw: seen.append(kw) or SimpleNamespace(matches=[]))
        wrapped = self.q.EvaluationIndex(index, "qa-eval-before", enabled=False)
        wrapped.query(namespace="qa", vector=[0.1], top_k=5, filter={"source_type":{"$eq":"qa"}})
        wrapped.query(namespace="counsel", vector=[0.1], top_k=5)
        self.assertEqual(seen[0]["namespace"], "qa-eval-before")
        self.assertIn("$and", seen[0]["filter"])
        self.assertIn("nodong_qna", str(seen[0]["filter"]))
        self.assertEqual(seen[1]["namespace"], "counsel")
        self.assertNotIn("filter", seen[1])

    def test_other_sources_can_be_pinned_to_the_same_frozen_namespaces(self):
        seen=[]
        wrapped=self.q.EvaluationIndex(SimpleNamespace(query=lambda **kw: seen.append(kw)),"qa-eval-after",frozen_namespaces={"counsel":"qa-eval-fixed-counsel","laborlaw-v2":"qa-eval-fixed-law"})
        wrapped.query(namespace="counsel",vector=[0.1],top_k=5)
        wrapped.query(namespace="laborlaw-v2",vector=[0.1],top_k=5)
        self.assertEqual([r["namespace"] for r in seen],["qa-eval-fixed-counsel","qa-eval-fixed-law"])

    def test_sparse_exclusion_keeps_other_qa_sources(self):
        docs = [{"id":"a","text":"연차","source_type":"qa","corpus_origin":"nodong_qna"},
                {"id":"b","text":"연차","source_type":"qa","corpus_origin":"legal_cases"}]
        with patch.dict("os.environ", {"QNA_EVAL_MODE":"without"}):
            selected = [d for d in docs if self.q.include_sparse_document(d)]
        self.assertEqual([d["id"] for d in selected], ["b"])

    def test_explicit_missing_sparse_file_cannot_fall_back(self):
        with patch.dict("os.environ", {"QNA_EVAL_BM25_PATH":"/missing/snapshot.jsonl.gz"}):
            paths = self.q.corpus_paths([bm25_search.BM25_CORPUS_PATHS[0]])
        self.assertEqual([str(p) for p in paths], ["/missing/snapshot.jsonl.gz"])

    def test_invalid_experiment_namespace_is_rejected(self):
        with self.assertRaises(ValueError):
            self.q.EvaluationIndex(SimpleNamespace(), "laborlaw-v2", enabled=True)

if __name__ == "__main__":
    unittest.main()
