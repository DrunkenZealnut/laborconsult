"""answer_model_settings DDL을 실제 PostgreSQL 17에서 검증한다 (admin-model-settings).

LEGAL_RULE_SQL_TEST=true python3 -m unittest test_model_settings_sql -v
test_legal_rule_sql.py와 같은 격리 방식: 설치된 postgres:17 이미지, 네트워크·포트·볼륨 없음.
"""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import unittest
from uuid import uuid4

# 클래스를 이름으로 import하면 unittest가 그 테스트까지 이 모듈에서 다시 수집한다 — 모듈로 참조.
import test_legal_rule_sql as _legal


@unittest.skipUnless(os.getenv("LEGAL_RULE_SQL_TEST") == "true", "opt-in disposable PostgreSQL test")
class ModelSettingsSqlTest(unittest.TestCase):
    sql = classmethod(_legal.SqlTest.sql.__func__)
    _wait_ready = classmethod(_legal.SqlTest._wait_ready.__func__)
    _remove = classmethod(_legal.SqlTest._remove.__func__)

    @classmethod
    def setUpClass(cls):
        import subprocess
        cls.container = "laborconsult-model-test-" + uuid4().hex[:12]
        subprocess.run(["docker", "run", "--pull=never", "--rm", "-d", "--network=none",
                        "--name", cls.container, "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "postgres:17"],
                       check=True, capture_output=True, timeout=60)
        cls.addClassCleanup(cls._remove)
        cls._wait_ready()
        setup = cls.sql("CREATE SCHEMA laborconsult; CREATE ROLE anon; CREATE ROLE authenticated; "
                        "CREATE ROLE service_role; GRANT USAGE ON SCHEMA laborconsult TO anon, authenticated, service_role;")
        if setup.returncode:
            raise RuntimeError(setup.stderr)
        ddl = Path("supabase_model_settings.sql").read_text()
        for attempt in range(2):                     # 멱등성: 두 번 적용해도 성공해야 한다
            result = cls.sql(ddl)
            if result.returncode:
                raise RuntimeError(f"적용 {attempt + 1}회차 실패: {result.stderr}")

    def setUp(self):
        r = self.sql("TRUNCATE laborconsult.answer_model_setting_events; "
                     "UPDATE laborconsult.answer_model_settings SET revision=0, settings='{}'::jsonb;")
        self.assertEqual(r.returncode, 0, r.stderr)

    @staticmethod
    def save(revision=0, doc='{"primary":"claude"}'):
        return (f"SET ROLE service_role; SELECT laborconsult.answer_model_settings_save("
                f"{revision}, '{doc}'::jsonb, 'test-actor');")

    def test_single_row_seeded_idempotently(self):
        self.assertEqual(self.sql("SELECT count(*) FROM laborconsult.answer_model_settings;").stdout.strip(), "1")

    def test_cas_and_history_are_atomic(self):
        r = self.sql(self.save())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip().splitlines()[-1], "1")
        dup = self.sql(self.save())
        self.assertNotEqual(dup.returncode, 0)
        self.assertIn("MODEL_SETTINGS_REVISION_CONFLICT", dup.stderr)
        state = self.sql("SELECT revision, settings->>'primary' FROM laborconsult.answer_model_settings; "
                         "SELECT count(*), max(before::text), max(after->>'primary') FROM laborconsult.answer_model_setting_events;")
        self.assertEqual(state.stdout.strip().splitlines(), ["1|claude", "1|{}|claude"])

    def test_concurrent_writers_cannot_both_commit(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(self.sql, [self.save(), self.save()]))
        self.assertEqual(sum(r.returncode == 0 for r in results), 1)

    def test_null_or_non_object_rejected_before_any_write(self):
        for doc in ("NULL", "'[]'::jsonb"):
            r = self.sql(f"SET ROLE service_role; SELECT laborconsult.answer_model_settings_save(0, {doc}, 'x');")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("INVALID_MODEL_SETTINGS", r.stderr)
        self.assertEqual(self.sql("SELECT revision FROM laborconsult.answer_model_settings;").stdout.strip(), "0")

    def test_public_roles_denied_and_service_role_cannot_bypass_rpc(self):
        for role in ("anon", "authenticated"):
            for q in ("SELECT * FROM laborconsult.answer_model_settings;",
                      "SELECT * FROM laborconsult.answer_model_setting_events;",
                      self.save().split(";", 1)[1]):
                r = self.sql(f"SET ROLE {role}; {q}")
                self.assertNotEqual(r.returncode, 0, r.stdout)
                self.assertIn("permission denied", r.stderr)
        self.assertEqual(self.sql("SET ROLE service_role; SELECT settings FROM laborconsult.answer_model_settings;").returncode, 0)
        for q in ("UPDATE laborconsult.answer_model_settings SET revision=9;",
                  "DELETE FROM laborconsult.answer_model_setting_events;"):
            self.assertNotEqual(self.sql("SET ROLE service_role; " + q).returncode, 0)


if __name__ == "__main__":
    unittest.main()
