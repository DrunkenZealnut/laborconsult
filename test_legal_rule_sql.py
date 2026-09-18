"""Opt-in real PostgreSQL transaction/permission tests in an isolated disposable container.

LEGAL_RULE_SQL_TEST=true python -m unittest test_legal_rule_sql -v
Uses the already-installed postgres:17 image; no network, host ports, or persistent volumes.
"""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import time
import unittest
from uuid import uuid4


@unittest.skipUnless(os.getenv("LEGAL_RULE_SQL_TEST") == "true", "opt-in disposable PostgreSQL test")
class SqlTest(unittest.TestCase):
    @classmethod
    def sql(cls, sql, timeout=20):
        return subprocess.run(["docker", "exec", "-i", cls.container, "psql", "-h", "127.0.0.1", "-U", "postgres",
                               "-v", "ON_ERROR_STOP=1", "-At"], input=sql, text=True, capture_output=True,
                              timeout=timeout)

    @classmethod
    def _wait_ready(cls, budget=60.0):
        """기동 대기. **예외도 '아직'으로 센다.**

        느린 것은 postgres 가 아니라 docker 다 — 컨테이너를 연달아 만들고 지우면
        데몬이 잠깐 먹통이 돼 `docker exec` 가 그대로 멈춘다(실측: 20초 타임아웃).
        그건 returncode 가 아니라 TimeoutExpired 라, 반환값만 보는 루프는 재시도
        없이 그 자리에서 죽고 setUpClass 실패로 전체 테스트가 한꺼번에 에러난다.
        준비되면 즉시 빠져나오므로 예산을 늘려도 정상 경로는 느려지지 않는다.
        """
        deadline = time.monotonic() + budget
        while time.monotonic() < deadline:
            try:
                if cls.sql("SELECT 1", timeout=5).returncode == 0:
                    return
            except subprocess.TimeoutExpired:
                pass
            time.sleep(0.5)
        raise RuntimeError(f"postgres:17 컨테이너가 {budget:.0f}초 안에 준비되지 않았습니다")

    @classmethod
    def _remove(cls):
        # 정리 실패로 테스트를 깨뜨리지 않는다 — `--rm` 이 붙어 있어 데몬이 회복되면
        # 스스로 사라진다. (`docker stop -t 1` 은 이미 죽은 컨테이너에서 멈춘다.)
        try:
            subprocess.run(["docker", "rm", "-f", cls.container], capture_output=True, timeout=30)
        except subprocess.TimeoutExpired:
            pass

    @classmethod
    def setUpClass(cls):
        cls.container = "laborconsult-rule-test-" + uuid4().hex[:12]
        subprocess.run(["docker", "run", "--pull=never", "--rm", "-d", "--network=none",
                        "--name", cls.container, "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "postgres:17"],
                       check=True, capture_output=True, timeout=60)
        cls.addClassCleanup(cls._remove)
        cls._wait_ready()
        setup = cls.sql("CREATE SCHEMA laborconsult; CREATE ROLE anon; CREATE ROLE authenticated; "
                        "CREATE ROLE service_role; GRANT USAGE ON SCHEMA laborconsult TO anon, authenticated, service_role;")
        if setup.returncode:
            raise RuntimeError(setup.stderr)
        result = cls.sql(Path("supabase_legal_rules.sql").read_text())
        if result.returncode:
            raise RuntimeError(result.stderr)

    def setUp(self):
        result = self.sql("TRUNCATE laborconsult.legal_rule_events; UPDATE laborconsult.legal_rule_registry "
                          "SET revision=0, document=jsonb_build_object('records',jsonb_build_array(),'scans',jsonb_build_array());")
        self.assertEqual(result.returncode, 0, result.stderr)

    @staticmethod
    def save(revision=0):
        return (f"SET ROLE service_role; SELECT laborconsult.legal_rules_save({revision}, "
                "'{\"records\":[],\"scans\":[]}', 'test-actor', '{\"type\":\"test\"}', "
                "'{\"records\":[]}');")

    def test_cas_and_event_are_atomic(self):
        result = self.sql(self.save())
        self.assertEqual(result.returncode, 0, result.stderr)
        duplicate = self.sql(self.save())
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertIn("LEGAL_RULE_REVISION_CONFLICT", duplicate.stderr)
        state = self.sql("SELECT revision FROM laborconsult.legal_rule_registry; SELECT count(*) FROM laborconsult.legal_rule_events;")
        self.assertEqual(state.stdout.strip().splitlines(), ["1", "1"])

    def test_concurrent_writers_cannot_both_commit_same_revision(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(self.sql, [self.save(), self.save()]))
        self.assertEqual(sum(r.returncode == 0 for r in results), 1)
        self.assertEqual(self.sql("SELECT count(*) FROM laborconsult.legal_rule_events;").stdout.strip(), "1")

    def test_public_roles_and_direct_event_tampering_are_denied(self):
        for role in ("anon", "authenticated"):
            for query in ("SELECT * FROM laborconsult.legal_rule_registry;",
                          "SELECT * FROM laborconsult.legal_rule_events;",
                          self.save().split(';', 1)[1]):
                result = self.sql(f"SET ROLE {role}; {query}")
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("permission denied", result.stderr)
        self.assertEqual(self.sql(self.save()).returncode, 0)
        for query in ("DELETE FROM laborconsult.legal_rule_events;",
                      "UPDATE laborconsult.legal_rule_registry SET revision=10;"):
            result = self.sql("SET ROLE service_role; " + query)
            self.assertNotEqual(result.returncode, 0)

    def test_v1_history_column_and_function_overload_are_migrated_not_duplicated(self):
        """초판(document 전량 + 4인자 함수)에서 올라오는 경로.

        CREATE OR REPLACE 는 인자가 다르면 덮어쓰지 않고 오버로드를 만든다 — 4인자
        함수가 남으면 그 호출이 계속 registry 전량을 이력에 쓴다.
        """
        legacy = self.sql(
            "DROP TABLE laborconsult.legal_rule_events;"
            "CREATE TABLE laborconsult.legal_rule_events (revision BIGINT PRIMARY KEY,"
            " actor TEXT NOT NULL, action JSONB NOT NULL, document JSONB NOT NULL,"
            " created_at TIMESTAMPTZ NOT NULL DEFAULT now());"
            "INSERT INTO laborconsult.legal_rule_events(revision, actor, action, document)"
            " VALUES (1, 'v1-actor', '{\"type\":\"v1\"}', '{\"records\":[]}');"
            "CREATE FUNCTION laborconsult.legal_rules_save(BIGINT, JSONB, TEXT, JSONB)"
            " RETURNS BIGINT LANGUAGE sql AS $f$ SELECT 0::bigint $f$;")
        self.assertEqual(legacy.returncode, 0, legacy.stderr)
        applied = self.sql(Path("supabase_legal_rules.sql").read_text())
        self.assertEqual(applied.returncode, 0, applied.stderr)
        state = self.sql(
            "SELECT count(*) FROM laborconsult.legal_rule_events WHERE actor = 'v1-actor';"
            "SELECT string_agg(column_name, ',' ORDER BY column_name)"
            " FROM information_schema.columns WHERE table_schema = 'laborconsult'"
            "   AND table_name = 'legal_rule_events' AND column_name IN ('document', 'payload');"
            "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace"
            " WHERE n.nspname = 'laborconsult' AND p.proname = 'legal_rules_save';")
        self.assertEqual(state.stdout.strip().splitlines(), ["1", "payload", "1"], state.stderr)

    def test_migration_is_repeatable_without_erasing_history(self):
        self.assertEqual(self.sql(self.save()).returncode, 0)
        result = self.sql(Path("supabase_legal_rules.sql").read_text())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.sql("SELECT count(*) FROM laborconsult.legal_rule_events;").stdout.strip(), "1")


if __name__ == "__main__":
    unittest.main()
