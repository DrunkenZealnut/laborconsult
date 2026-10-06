"""chat_guard_check(일일 쿼터·차단) DDL을 실제 PostgreSQL 17에서 검증한다 (chatbot-security FR-03/11).

LEGAL_RULE_SQL_TEST=true python3 -m unittest test_abuse_guard_sql -v
test_legal_rule_sql.py와 같은 격리 방식: 설치된 postgres:17 이미지, 네트워크·포트·볼륨 없음.

지키는 것: 한도에 닿은 뒤의 거절은 카운터를 더 올리지 않는다. 거절된 재시도까지 세면 카운터가 의미 없이
커지고(2026-10-06 실측 51→54), 그날 한도를 올려도 풀리지 않는다.
"""
import json
import os
from pathlib import Path
import unittest
from uuid import uuid4

# 클래스를 이름으로 import하면 unittest가 그 테스트까지 이 모듈에서 다시 수집한다 — 모듈로 참조.
import test_legal_rule_sql as _legal


@unittest.skipUnless(os.getenv("LEGAL_RULE_SQL_TEST") == "true", "opt-in disposable PostgreSQL test")
class AbuseGuardSqlTest(unittest.TestCase):
    sql = classmethod(_legal.SqlTest.sql.__func__)
    _wait_ready = classmethod(_legal.SqlTest._wait_ready.__func__)
    _remove = classmethod(_legal.SqlTest._remove.__func__)

    @classmethod
    def setUpClass(cls):
        import subprocess
        cls.container = "laborconsult-guard-test-" + uuid4().hex[:12]
        subprocess.run(["docker", "run", "--pull=never", "--rm", "-d", "--network=none",
                        "--name", cls.container, "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "postgres:17"],
                       check=True, capture_output=True, timeout=60)
        cls.addClassCleanup(cls._remove)
        cls._wait_ready()
        setup = cls.sql("CREATE SCHEMA laborconsult; CREATE ROLE anon; CREATE ROLE authenticated; "
                        "CREATE ROLE service_role; GRANT USAGE ON SCHEMA laborconsult TO anon, authenticated, service_role;")
        if setup.returncode:
            raise RuntimeError(setup.stderr)
        ddl = Path("supabase_abuse_guard.sql").read_text()
        for attempt in range(2):                     # 멱등성: 두 번 적용해도 성공해야 한다
            result = cls.sql(ddl)
            if result.returncode:
                raise RuntimeError(f"적용 {attempt + 1}회차 실패: {result.stderr}")

    def setUp(self):
        r = self.sql("TRUNCATE laborconsult.chat_quota; TRUNCATE laborconsult.block_list;")
        self.assertEqual(r.returncode, 0, r.stderr)

    def check(self, subject="ip:test", day="2026-10-06", limit=3):
        r = self.sql(f"SET ROLE anon; SELECT laborconsult.chat_guard_check('{subject}', '{day}', {limit});")
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def count(self, subject="ip:test", day="2026-10-06"):
        return self.sql(f"SELECT count FROM laborconsult.chat_quota WHERE subject_key='{subject}' AND day='{day}';"
                        ).stdout.strip()

    def test_allows_up_to_limit_then_rejects(self):
        got = [self.check() for _ in range(3)]
        self.assertTrue(all(g["allowed"] for g in got))
        self.assertEqual([g["count"] for g in got], [1, 2, 3])
        rejected = self.check()
        self.assertEqual((rejected["allowed"], rejected["reason"]), (False, "quota"))

    def test_rejected_retries_do_not_grow_the_counter(self):
        for _ in range(3):
            self.check()
        for _ in range(5):                             # 한도 뒤 재시도
            self.assertFalse(self.check()["allowed"])
        self.assertEqual(self.count(), "3", "거절된 재시도는 세지 않는다")

    def test_raising_the_limit_same_day_lets_the_subject_continue(self):
        for _ in range(3):
            self.check(limit=3)
        for _ in range(4):
            self.check(limit=3)                        # 거절
        self.assertTrue(self.check(limit=5)["allowed"], "카운터가 커지지 않았으므로 한도를 올리면 바로 풀린다")

    def test_next_day_starts_fresh_and_cleans_old_rows(self):
        for _ in range(4):
            self.check(day="2026-10-06")
        nxt = self.check(day="2026-10-07")
        self.assertEqual((nxt["allowed"], nxt["count"]), (True, 1))
        self.assertEqual(self.count(day="2026-10-06"), "", "지난 날짜 행은 정리된다")

    def test_block_list_wins_and_reports_retry_after(self):
        self.sql("INSERT INTO laborconsult.block_list (subject_key, until_ts, reason, strikes) "
                 "VALUES ('ip:test', now() + interval '10 minutes', 'quota', 1);")
        got = self.check()
        self.assertEqual((got["allowed"], got["reason"]), (False, "blocked"))
        self.assertTrue(0 < got["retry_after"] <= 600)
        self.assertEqual(self.count(), "", "차단 중에는 쿼터를 세지 않는다")

    def test_tables_stay_locked_for_anon(self):
        r = self.sql("SET ROLE anon; SELECT * FROM laborconsult.chat_quota;")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("permission denied", r.stderr)


if __name__ == "__main__":
    unittest.main()
