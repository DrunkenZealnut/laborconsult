import importlib.util
import os
import unittest
from unittest.mock import patch
from types import SimpleNamespace

class QualityStoreTests(unittest.TestCase):
    def test_no_storage_or_tokens_for_synthetic_or_disabled(self):
        self.assertIsNotNone(importlib.util.find_spec('app.core.qa_quality_store'))
        from app.core.qa_quality_store import record_quality
        with patch.dict(os.environ,{'QA_QUALITY_ENABLED':'false'}):
            self.assertIsNone(record_quality(None,'id','sid',{},'model',synthetic=False))
        with patch.dict(os.environ,{'QA_QUALITY_ENABLED':'true'}):
            self.assertIsNone(record_quality(None,'id','sid',{},'model',synthetic=True))

    def test_private_client_requires_server_role_key(self):
        from app.core import qa_quality_store as store
        self.assertTrue(hasattr(store,"quality_client"),"private service client missing")
        with patch.dict(os.environ,{"SUPABASE_SERVICE_ROLE_KEY":"","SUPABASE_KEY":"public-key"}):
            self.assertIsNone(store.quality_client())
        with patch.dict(os.environ,{"SUPABASE_SERVICE_ROLE_KEY":"server-role"}), patch("app.core.storage.make_supabase_client",return_value="private-client") as factory:
            self.assertEqual(store.quality_client(),"private-client")
            self.assertEqual(factory.call_args.kwargs["key"],"server-role")

    def test_private_trace_and_signed_versions(self):
        self.assertIsNotNone(importlib.util.find_spec('app.core.qa_quality_store'))
        from app.core.qa_quality_store import record_quality
        from app.core.answer_feedback import verify_token
        events=[]
        class Store:
            def schema(self,name):events.append(name);return self
            def table(self,name):events.append(name);return self
            def insert(self,row):events.append(row);return self
            def execute(self):return SimpleNamespace(data=[{'ok':True}])
        secret='a'*32
        with patch.dict(os.environ,{'QA_QUALITY_ENABLED':'true','ADMIN_JWT_SECRET':secret}):
            event=record_quality(Store(),'11111111-1111-1111-1111-111111111111','sid',
                {'trace_id':'22222222-2222-2222-2222-222222222222','items':[],'unidentified_selected':0},'fixed-model',synthetic=False)
        self.assertEqual(event['type'],'feedback')
        claims=verify_token(secret,event['token'],'sid')
        self.assertEqual(claims['versions']['answer_model'],'fixed-model')
        self.assertEqual(events[:2],['laborconsult','qa_retrieval_traces'])
        self.assertNotIn('items',event)

if __name__=='__main__': unittest.main()
