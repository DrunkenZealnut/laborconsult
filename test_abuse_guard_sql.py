"""chat_guard_check(일일 쿼터·차단) DDL을 실제 PostgreSQL 17에서 검증한다 (chatbot-security FR-03/11).

LEGAL_RULE_SQL_TEST=true python3 -m unittest test_abuse_guard_sql -v
test_legal_rule_sql.py와 같은 격리 방식: 설치된 postgres:17 이미지, 네트워크·포트·볼륨 없음.

지키는 것: 한도에 닿은 뒤의 거절은 카운터를 더 올리지 않는다(한도 직전의 동시 요청 포함). 거절된 재시도까지
세면 카운터가 의미 없이 커지고(2026-10-06 실측 51→54), 그날 한도를 올려도 풀리지 않는다.
"""
import json
import os
from pathlib import Path
import subprocess
import time
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

    def wait_for(self, query, expected, budget=15.0):
        deadline = time.monotonic() + budget
        while True:
            got = self.sql(query).stdout.strip()
            if got == expected:
                return
            if time.monotonic() > deadline:
                self.fail(f"대기 실패: {query} → {got!r} (기대 {expected!r})")
            time.sleep(0.1)

    def test_concurrent_requests_at_the_limit_do_not_overshoot(self):
        """한도 직전에 동시에 들어온 두 요청 — 늦은 쪽은 거절되고 카운터는 한도에 머문다(CodeRabbit #103).

        앞 요청이 증가만 하고 커밋하기 전에 뒤 요청을 보내 사전 검사를 같은 값(2)으로 통과시킨 뒤 앞 요청을
        커밋한다. 사전 검사만 있던 함수는 뒤 요청을 거절하면서도 그 증가분(4)을 저장했다.
        """
        for _ in range(2):
            self.check()                               # count = 2, 한도 3
        psql = ["docker", "exec", "-i", self.container, "psql", "-h", "127.0.0.1", "-U", "postgres",
                "-v", "ON_ERROR_STOP=1", "-At"]
        call = "SELECT laborconsult.chat_guard_check('ip:test', '2026-10-06', 3);\n"
        pipes = dict(stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        first = subprocess.Popen(psql, **pipes)
        second = None
        try:
            first.stdin.write("BEGIN; SET ROLE anon; " + call)
            first.stdin.flush()
            self.wait_for("SELECT count(*) FROM pg_stat_activity WHERE state = 'idle in transaction';", "1")
            second = subprocess.Popen(psql, **pipes)
            second.stdin.write("SET ROLE anon; " + call)
            second.stdin.flush()
            self.wait_for("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock';", "1")
            # stdin은 communicate가 닫게 둔다 — 직접 닫으면 3.11의 communicate가 닫힌 파일을 flush하다 죽는다
            out1, err1 = first.communicate("COMMIT;\n", timeout=20)
            out2, err2 = second.communicate(timeout=20)
        finally:
            for proc in (first, second):
                if proc is not None and proc.poll() is None:
                    proc.kill()
            # 도중에 실패하면 컨테이너 안의 psql이 트랜잭션을 연 채 남아 다음 테스트의 TRUNCATE를 막는다
            self.sql("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                     "WHERE backend_type = 'client backend' AND pid <> pg_backend_pid();")
        self.assertEqual((first.returncode, second.returncode), (0, 0), err1 + err2)
        got1, got2 = ([json.loads(line) for line in out.splitlines() if line.startswith("{")][-1]
                      for out in (out1, out2))
        self.assertEqual((got1["allowed"], got1["count"]), (True, 3))
        self.assertEqual((got2["allowed"], got2["reason"], got2["count"]), (False, "quota", 3))
        self.assertEqual(self.count(), "3", "동시 요청의 거절도 카운터를 올리지 않는다")

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
