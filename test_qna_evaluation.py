import importlib.util
import unittest
from unittest.mock import patch
from types import SimpleNamespace

class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('qna_evaluation'),'frozen evaluation harness missing')
        import qna_evaluation
        self.q=qna_evaluation
        self.frozen={'law_cache':{'law:key':'frozen article'},'model_settings':{'primary':'openai','models':{}},
                     'model_revision':12,'legal_rule_revision':3,'legal_rule_document':{'records':[]},'environment':{}}

    def test_snapshot_reads_and_db_write_attempts_are_blocked(self):
        from app.core import legal_api,model_settings,legal_rule_store,storage
        config=SimpleNamespace(supabase=object())
        with self.q.frozen_runtime(self.frozen,config) as audit:
            self.assertIsNone(config.supabase)
            self.assertEqual(legal_api._l2_cache_get('law:key'),'frozen article')
            self.assertIsNone(legal_api._l2_cache_get('missing'))
            self.assertEqual(model_settings.load()[1],12)
            self.assertEqual(legal_rule_store.configured_store().load()[0],3)
            with self.assertRaises(RuntimeError):legal_api._l2_cache_set('x','law',1,'text')
            with self.assertRaises(RuntimeError):storage.make_supabase_client()
            self.assertEqual(len(audit['blocked_writes']),2)

    def test_numeric_mentions_are_unit_aware_and_never_labeled_semantic_accuracy(self):
        result=self.q.numeric_mentions({'pay':2500000,'days':15},'급여는 250만원, 연차는 15일입니다.')
        self.assertTrue(result['pay']);self.assertTrue(result['days'])
        self.assertFalse(self.q.numeric_mentions({'pay':2500000},'급여는 250원입니다.')['pay'])

if __name__=='__main__':unittest.main()
