"""Only internal retrieval records contain source identifiers."""
import importlib.util
import unittest
from types import SimpleNamespace

class TraceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("app.core.retrieval_trace"), "internal trace missing")
        from app.core import retrieval_trace
        self.t = retrieval_trace

    def test_candidates_and_context_are_separate_and_bodies_are_omitted(self):
        a={"id":"ctx_qa_123_c0","source_type":"qa","corpus_origin":"nodong_qna","post_id":"123",
           "posted_at":"2026-03-04","document_version":"v1","score":0.9,"content":"sensitive body","title":"private title"}
        b={"id":"ctx_counsel_1","source_type":"counsel","score":0.8}
        trace=self.t.build_trace([a,b],[a])
        self.assertEqual(len(trace["items"]),2)
        by_id={x["chunk_id"]:x for x in trace["items"]}
        self.assertTrue(by_id[a["id"]]["selected_for_context"])
        self.assertFalse(by_id[b["id"]]["selected_for_context"])
        self.assertEqual(by_id[a["id"]]["corpus_origin"],"nodong_qna")
        self.assertEqual(by_id[b["id"]]["corpus_origin"],"counsel")
        self.assertNotIn("sensitive body",str(trace))
        self.assertNotIn("private title",str(trace))
        self.assertNotIn("actual_influence",str(trace))

    def test_observer_collects_trace_without_database(self):
        calls=[]
        config=SimpleNamespace(retrieval_observer=calls.append,supabase=None)
        self.t.observe(config,[{"id":"x","source_type":"qa","score":0.3}],[])
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0]["items"][0]["corpus_origin"],"unknown")

    def test_observer_failure_does_not_break_answer(self):
        def broken(trace):raise RuntimeError("offline sink unavailable")
        result=self.t.observe(SimpleNamespace(retrieval_observer=broken),[],[])
        self.assertEqual(result["items"],[])

if __name__=="__main__":
    unittest.main()
