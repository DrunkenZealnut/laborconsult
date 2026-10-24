import importlib.util
import os
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app.core.answer_feedback import issue_token

class QualityApiTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('api.qa_quality'), 'quality router missing')
        from api.qa_quality import build_router
        self.events=[]
        owner=self
        class Store:
            def schema(self,name): owner.events.append(name);return self
            def rpc(self,name,params): owner.events.append((name,params));return self
            def execute(self): return SimpleNamespace(data={'saved':True})
        def admin(): raise HTTPException(401,'auth required')
        app=FastAPI()
        app.include_router(build_router(admin,lambda:SimpleNamespace(supabase=Store()),'secret',lambda req:0))
        self.client=TestClient(app)
        self.token=issue_token('secret','11111111-1111-1111-1111-111111111111','s',{'corpus_version':'v1'})

    def test_disabled_and_owner_guard(self):
        body={'token':self.token,'session_id':'wrong','kind':'exposure'}
        with patch.dict(os.environ,{'QA_QUALITY_ENABLED':'false'}):
            self.assertEqual(self.client.post('/api/answer-feedback',json=body).status_code,503)
        with patch.dict(os.environ,{'QA_QUALITY_ENABLED':'true'}):
            self.assertEqual(self.client.post('/api/answer-feedback',json=body).status_code,400)
        self.assertEqual(self.events,[])
        self.assertEqual(self.client.get('/api/admin/qa-quality').status_code,401)

    def test_strict_shape_and_success(self):
        body={'token':self.token,'session_id':'s','kind':'exposure'}
        with patch.dict(os.environ,{'QA_QUALITY_ENABLED':'true'}):
            self.assertEqual(self.client.post('/api/answer-feedback',json={**body,'positive':1}).status_code,422)
            self.assertEqual(self.client.post('/api/answer-feedback',json={**body,'versions':{}}).status_code,422)
            r=self.client.post('/api/answer-feedback',json=body)
            self.assertEqual(r.status_code,200,r.text)
            self.assertTrue(r.json()['saved'])
        self.assertEqual(self.events[0],'laborconsult')

    def test_complete_app_quality_route_precedes_static_fallback(self):
        import api.index as main
        client=TestClient(main.app)
        self.assertEqual(client.get('/api/admin/qa-quality').status_code,401)
        def allowed_admin():return {'admin':True}
        main.app.dependency_overrides[main.require_admin]=allowed_admin
        self.addCleanup(main.app.dependency_overrides.pop,main.require_admin)
        with patch.object(main,'quality_client',return_value=None):
            response=client.get('/api/admin/qa-quality')
        self.assertEqual(response.status_code,503)
        self.assertEqual(response.json()['detail'],'집계를 불러올 수 없습니다.')

if __name__=='__main__':unittest.main()
