"""Offline corpus assembly must preserve non-Q&A rows and reject partial snapshots."""
import gzip
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from test_qna_vectors import Index

class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("qna_snapshot"), "snapshot assembler missing")
        import qna_snapshot
        self.q = qna_snapshot

    def snapshot(self, path):
        for ns, ids in {"qa":["ctx_qa_123_c0","ctx_qa_123_c1","ctx_qa_case_1_c0"],"counsel":["c1"],"laborlaw-v2":["law1"]}.items():
            folder = path/ns;folder.mkdir(parents=True)
            rows={key:{"id":key,"values":[0.1],"metadata":{"text":key,"title":key,"source_type":"qa" if ns=="qa" else ns,
                "url":"https://www.nodong.kr/qna/123" if key.startswith("ctx_qa_123_") else ""}} for key in ids}
            (folder/"ids.json").write_text(json.dumps(ids))
            (folder/"complete.json").write_text(json.dumps({"count":len(ids)}))
            with gzip.open(folder/"0000000.json.gz","wt") as f:json.dump(rows,f)

    def test_replacement_keeps_other_sources_and_removes_only_old_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);self.snapshot(path/"snapshot")
            new={"id":"ctx_qa_123_c0","values":[0.2],"metadata":{"text":"new answer","title":"new","source_type":"qa","corpus_origin":"nodong_qna","post_id":"123","document_version":"new"}}
            out=path/"out.jsonl.gz"
            report=self.q.build_sparse(path/"snapshot", {"123":[new]}, out)
            with gzip.open(out,"rt") as f:rows=[json.loads(line) for line in f]
            self.assertEqual({r["id"] for r in rows}, {"ctx_qa_123_c0","ctx_qa_case_1_c0","c1","law1"})
            self.assertEqual(report["count"],4)
            self.assertEqual(next(r for r in rows if r["id"]=="ctx_qa_123_c0")["document_version"],"new")

    def test_incomplete_snapshot_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);self.snapshot(path/"snapshot")
            (path/"snapshot/counsel/complete.json").unlink()
            out=path/"out.jsonl.gz";out.write_bytes(b"previous")
            with self.assertRaises(ValueError):
                self.q.build_sparse(path/"snapshot", {}, out)
            self.assertEqual(out.read_bytes(),b"previous")

    def test_missing_shard_is_detected_before_output_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);self.snapshot(path/"snapshot")
            (path/"snapshot/qa/0000000.json.gz").unlink()
            with self.assertRaises(ValueError):
                self.q.build_sparse(path/"snapshot", {}, path/"out.jsonl.gz")
            self.assertFalse((path/"out.jsonl.gz").exists())

    def test_clone_refuses_populated_namespace_without_its_own_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);self.snapshot(path/"snapshot")
            self.assertTrue(hasattr(self.q, "clone_qa"), "candidate clone missing")
            with self.assertRaises(ValueError):
                self.q.clone_qa(path/"snapshot", Index(), "qa-eval-before", path/"ledger")

    def test_owned_clone_resume_skips_already_verified_identical_vectors(self):
        index=Index();index.rows={}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);self.snapshot(path/"snapshot")
            self.q.clone_qa(path/"snapshot",index,"qa-eval-before",path/"ledger")
            index.upsert=lambda **kw: self.fail("identical clone must not be uploaded again")
            self.q.clone_qa(path/"snapshot",index,"qa-eval-before",path/"ledger")

    def test_clone_freezes_other_sources_without_relabeling_them_as_qna(self):
        index=Index();index.rows={}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);self.snapshot(path/"snapshot")
            self.q.clone_qa(path/"snapshot", index, "qa-eval-fixed-law", path/"ledger", source_namespace="laborlaw-v2")
            self.assertEqual(set(index.rows),{"law1"})
            self.assertEqual(index.rows["law1"]["metadata"]["namespace"],"laborlaw-v2")

    def test_clone_preserves_values_and_adds_matching_document_versions(self):
        index=Index();index.rows={}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);self.snapshot(path/"snapshot")
            self.assertTrue(hasattr(self.q, "clone_qa"), "candidate clone missing")
            self.q.clone_qa(path/"snapshot", index, "qa-eval-before", path/"ledger")
            self.assertEqual(len(index.rows),3)
            self.assertEqual(index.rows["ctx_qa_123_c0"]["values"],[0.1])
            self.assertEqual(index.rows["ctx_qa_123_c0"]["metadata"]["document_version"],
                             index.rows["ctx_qa_123_c1"]["metadata"]["document_version"])
            self.assertNotIn("corpus_origin",index.rows["ctx_qa_case_1_c0"]["metadata"])

if __name__=="__main__":
    unittest.main()
