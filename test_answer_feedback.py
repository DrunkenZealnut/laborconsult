"""Signed feedback is tied to a stored answer and the same session."""
import importlib.util
import unittest
from types import SimpleNamespace

class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("app.core.answer_feedback"), "feedback module missing")
        from app.core import answer_feedback
        self.f = answer_feedback

    def token(self):
        return self.f.issue_token("test-secret-12345678901234567890","11111111-1111-1111-1111-111111111111","session-a",
                                  {"answer_model":"fixed-model","corpus_version":"v1"},now=100)

    def test_token_rejects_other_session_tampering_and_expiry(self):
        secret="test-secret-12345678901234567890"
        token=self.token()
        claims=self.f.verify_token(secret,token,"session-a",now=101)
        self.assertEqual(claims["versions"]["corpus_version"],"v1")
        for value,sid,now in [(token,"session-b",101),(token+"x","session-a",101),(token,"session-a",99999999)]:
            with self.assertRaises(ValueError):
                self.f.verify_token(secret,value,sid,now=now)

    def test_negative_vote_needs_enum_reason_and_boolean_vote(self):
        self.f.validate_submission("vote",False,"missing_answer")
        self.f.validate_submission("exposure",None,None)
        for args in [("vote",False,None),("vote",1,None),("vote",True,"private text"),("exposure",True,None)]:
            with self.assertRaises(ValueError):
                self.f.validate_submission(*args)

    def test_store_uses_fixed_schema_and_server_token_versions(self):
        events=[]
        class Store:
            def schema(self,name):events.append(("schema",name));return self
            def rpc(self,name,params):events.append(("rpc",name,params));return self
            def execute(self):return SimpleNamespace(data={"saved":True})
        result=self.f.submit(Store(),"test-secret-12345678901234567890",self.token(),"session-a",
                             "vote",False,"unclear",now=101)
        self.assertTrue(result["saved"])
        self.assertEqual(events[0],("schema","laborconsult"))
        payload=events[1][2]
        self.assertEqual(payload["p_versions"]["corpus_version"],"v1")
        self.assertNotIn("question",str(payload))
        self.assertNotIn("answer_text",str(payload))

if __name__=="__main__":
    unittest.main()
