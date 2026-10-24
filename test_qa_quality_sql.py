"""Real PostgreSQL permission, ownership and denominator checks."""
import os
from pathlib import Path
import unittest
from test_legal_rule_sql import SqlTest as _Harness

@unittest.skipUnless(os.getenv('LEGAL_RULE_SQL_TEST') == 'true', 'opt-in disposable PostgreSQL test')
class QualitySqlTests(unittest.TestCase):
    _setup_base = staticmethod(_Harness.setUpClass.__func__)
    sql = classmethod(_Harness.sql.__func__)
    _wait_ready = classmethod(_Harness._wait_ready.__func__)
    _remove = classmethod(_Harness._remove.__func__)

    @classmethod
    def setUpClass(cls):
        path=Path("supabase_qa_quality.sql")
        if not path.exists(): raise AssertionError("quality migration missing")
        cls._setup_base(cls)
        result=cls.sql("CREATE TABLE laborconsult.qa_conversations (id uuid PRIMARY KEY, session_id text NOT NULL);")
        if result.returncode: raise RuntimeError(result.stderr)
        path=Path('supabase_qa_quality.sql')
        if not path.exists(): raise AssertionError('quality migration missing')
        result=cls.sql(path.read_text())
        if result.returncode: raise RuntimeError(result.stderr)

    def setUp(self):
        result=self.sql("TRUNCATE laborconsult.qa_conversations CASCADE; INSERT INTO laborconsult.qa_conversations VALUES ('11111111-1111-1111-1111-111111111111','session-a');")
        self.assertEqual(result.returncode,0,result.stderr)

    def record(self,kind='exposure',vote='NULL',reason='NULL',sid='session-a'):
        return ("SET ROLE service_role; SELECT laborconsult.qa_feedback_record("
                f"'11111111-1111-1111-1111-111111111111','{sid}','{kind}',{vote},{reason},'{{\"corpus_version\":\"v1\"}}');")

    def test_owner_validation_and_public_permissions(self):
        bad=self.sql(self.record(sid='wrong'))
        self.assertNotEqual(bad.returncode,0)
        self.assertIn('FEEDBACK_OWNER',bad.stderr)
        for role in ['anon','authenticated']:
            for query in ['SELECT * FROM laborconsult.answer_feedback;', 'SELECT * FROM laborconsult.qa_retrieval_traces;', self.record().split(';',1)[1]]:
                result=self.sql(f'SET ROLE {role}; '+query)
                self.assertNotEqual(result.returncode,0,result.stdout)
                self.assertIn('permission denied',result.stderr)

    def test_exposure_idempotency_vote_and_denominators(self):
        for _ in range(2): self.assertEqual(self.sql(self.record()).returncode,0)
        vote=self.sql(self.record('vote','false',"'missing_answer'"))
        self.assertEqual(vote.returncode,0,vote.stderr)
        duplicate=self.sql(self.record('vote','false',"'missing_answer'"))
        self.assertEqual(duplicate.returncode,0,duplicate.stderr)
        state=self.sql("SELECT count(*),count(exposed_at),count(voted_at),count(*) FILTER(WHERE positive) FROM laborconsult.answer_feedback;")
        self.assertEqual(state.stdout.strip(),'1|1|1|0')
        changed=self.sql(self.record('vote','true'))
        self.assertNotEqual(changed.returncode,0)
        self.assertIn('FEEDBACK_RATE',changed.stderr)
        self.sql("UPDATE laborconsult.answer_feedback SET voted_at=now()-interval '1 minute';")
        self.assertEqual(self.sql(self.record('vote','true')).returncode,0)
        summary=self.sql("SET ROLE service_role; SELECT laborconsult.qa_quality_summary(30)->'feedback'->>'votes';")
        self.assertEqual(summary.returncode,0,summary.stderr)
        self.assertEqual(summary.stdout.strip().splitlines()[-1],'1')

    def test_unexposed_vote_and_invalid_reason_rejected(self):
        missing=self.sql(self.record('vote','true'))
        self.assertNotEqual(missing.returncode,0)
        self.assertIn('FEEDBACK_NOT_EXPOSED',missing.stderr)
        self.sql(self.record())
        bad=self.sql(self.record('vote','false',"'private arbitrary text'"))
        self.assertNotEqual(bad.returncode,0)
        self.assertEqual(self.sql('SELECT count(voted_at) FROM laborconsult.answer_feedback;').stdout.strip(),'0')

    def test_repeat_migration_and_no_public_objects(self):
        self.sql(self.record())
        result=self.sql(Path('supabase_qa_quality.sql').read_text())
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.sql('SELECT count(*) FROM laborconsult.answer_feedback;').stdout.strip(),'1')
        self.assertEqual(self.sql("SELECT count(*) FROM information_schema.tables WHERE table_schema='public';").stdout.strip(),'0')

# Do not discover the imported harness tests twice.
del _Harness
if __name__=='__main__': unittest.main()
