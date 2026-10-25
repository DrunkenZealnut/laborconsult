import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from qna_ingestion import document
from qna_corpus import EMBED_DIM

class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('qna_update'),'update workflow missing')
        import qna_update
        self.q=qna_update

    def crawl(self,path):
        (path/'records').mkdir(parents=True)
        old={}
        for pid,status,change in [('1','answered','unchanged'),('2','unanswered','unchanged'),('3','answered','new')]:
            doc=document(pid,'제목','2026-03-04','질문 내용',['답변 내용'] if status=='answered' else [],category='일반',fetched_at='2026-10-24T00:00:00+09:00')
            doc['change']=change
            (path/'records'/f'{pid}.json').write_text(json.dumps(doc))
            if change!='new':old[pid]=doc
        (path/'baseline-manifest.json').write_text(json.dumps(old))
        (path/'report.json').write_text(json.dumps({'complete':True,'failed':0,'date_unknown':[]}))
        (path/'state.json').write_text(json.dumps({'posts':{pid:{'status':'ok'} for pid in ['1','2','3']}}))

    def test_unchanged_unanswered_is_selected_for_legacy_ui_cleanup(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);self.crawl(root/'crawl')
            report=self.q.prepare(root/'crawl',root/'candidate')
            self.assertEqual(set(report['documents']),{'2','3'})
            self.assertGreater(report['embedding_tokens'],0)
            self.assertEqual(report['contextualization_tokens'],0)

    def test_next_collection_manifest_keeps_current_answers_and_unvisited_legacy(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);self.crawl(root/"crawl")
            baseline=self.q.read(root/"crawl/baseline-manifest.json")
            baseline["9"]={**baseline["1"],"post_id":"9"}
            self.q.save(root/"crawl/baseline-manifest.json",baseline)
            self.assertTrue(hasattr(self.q,"merge_manifest"),"next-run manifest missing")
            self.q.merge_manifest(root/"crawl",root/"current.json")
            merged=self.q.read(root/"current.json")
            self.assertEqual(set(merged),{"1","2","3","9"})
            self.assertEqual(merged["3"]["status"],"answered")

    def test_explicit_quarantine_keeps_failed_source_out_of_candidate(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);self.crawl(root/"crawl")
            report={"complete":False,"failed_ids":["2"],"failed_pages":[],"unvisited_ids":[],"date_unknown":[]}
            self.q.save(root/"crawl/report.json",report)
            state=self.q.read(root/"crawl/state.json");state["posts"]["2"]={"status":"failed"}
            self.q.save(root/"crawl/state.json",state)
            result=self.q.prepare(root/"crawl",root/"candidate",quarantine_ids=["2"])
            self.assertEqual(set(result["documents"]),{"3"})
            self.assertEqual(result["quarantined_ids"],["2"])
            self.assertFalse(result["collection_report"]["complete"])
            with self.assertRaises(ValueError):self.q.prepare(root/"crawl",root/"other",quarantine_ids=["9"])

    def test_incomplete_collection_cannot_be_materialized(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);self.crawl(root/'crawl')
            (root/'crawl'/'report.json').write_text(json.dumps({'complete':False}))
            with self.assertRaises(ValueError):self.q.prepare(root/'crawl',root/'candidate')

    def test_parallel_embedding_still_validates_and_completes_each_document(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);self.crawl(root/"crawl");self.q.prepare(root/"crawl",root/"candidate")
            result=self.q.embed(root/"candidate",lambda texts:[[0.1]*EMBED_DIM for _ in texts],workers=2)
            self.assertEqual(result["documents"],2)
            self.assertEqual(len(self.q.replacements(root/"candidate")),2)

    def test_embedding_resume_and_partial_provider_error(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);self.crawl(root/'crawl');self.q.prepare(root/'crawl',root/'candidate')
            calls=[]
            def embed(texts):calls.append(texts);return [[0.1]*EMBED_DIM for _ in texts]
            self.q.embed(root/'candidate',embed)
            first=len(calls)
            self.q.embed(root/'candidate',lambda _: self.fail('completed embeddings should be reused'))
            self.assertGreater(first,0)
            (root/'candidate'/'vectors'/'3.json.gz').unlink()
            with self.assertRaises(ValueError):self.q.embed(root/'candidate',lambda _: [])
            self.assertFalse((root/'candidate'/'embedding-complete.json').exists())

    def test_undeployed_answer_survives_next_collection_until_verified_deployment(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);self.crawl(root/'crawl')
            self.q.merge_manifest(root/'crawl',root/'collected.json')
            collected=self.q.read(root/'collected.json')
            self.q.save(root/'crawl/baseline-manifest.json',collected)
            doc=self.q.read(root/'crawl/records/3.json');doc['change']='unchanged'
            self.q.save(root/'crawl/records/3.json',doc)
            candidate=root/'candidate';manifest=self.q.prepare(root/'crawl',candidate)
            self.assertIn('3',manifest['documents'],'postponed new answer was lost')
            self.q.embed(candidate,lambda texts:[[.1]*EMBED_DIM for _ in texts])
            ledger=root/'production';ledger.mkdir()
            done={'status':'complete','namespace':'qa','candidate_version':manifest['candidate_version'],'documents':len(manifest['documents'])}
            self.q.save(ledger/'apply-complete.json',done)
            for pid in manifest['documents']:
                prepared=self.q.read(candidate/'prepared'/f'{pid}.json')
                self.q.save(ledger/pid/'complete.json',{'status':'complete','namespace':'qa','post_id':pid,'chunk_ids':[r['chunk_id'] for r in prepared['chunks']]})
            self.q.mark_deployed(root/'collected.json',candidate,ledger,root/'deployed.json')
            checkpoint=self.q.read(root/'deployed.json')
            self.assertEqual(checkpoint['3']['deployed_content_hash'],doc['content_hash'])
            self.q.save(root/'crawl/baseline-manifest.json',checkpoint)
            self.assertEqual(self.q.prepare(root/'crawl',root/'next')['documents'],{},
                             'verified unchanged unanswered cleanup must not remain pending forever')
            self.q.save(ledger/'apply-complete.json',{**done,'namespace':'qa-eval-test'})
            with self.assertRaises(ValueError):self.q.mark_deployed(root/'collected.json',candidate,ledger,root/'bad.json')
            self.assertFalse((root/'bad.json').exists())

if __name__=='__main__':unittest.main()
