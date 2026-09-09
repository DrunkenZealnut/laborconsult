"""Offline contracts for the Admin consultation-quality feature."""

from copy import deepcopy
import json
from types import SimpleNamespace

import eval_consultation as harness

from pathlib import Path
import re
import traceback


def test_consultation_eval_sql_locks_table_and_has_contract() -> None:
    """Catch missing run fields, constraints, indexes, or public-role locks."""
    sql = Path(__file__).with_name("supabase_consultation_eval.sql").read_text(
        encoding="utf-8"
    )
    # Ignore comments and formatting so only executable SQL satisfies the contract.
    sql = re.sub(r"/\*.*?\*/|--[^\n]*", "", sql, flags=re.DOTALL)
    sql = " ".join(sql.lower().split())
    for fragment in (
        "create table if not exists public.consultation_eval_runs",
        "id uuid primary key default gen_random_uuid()",
        "run_id text not null unique",
        "mode text not null check (mode in ('live', 'offline'))",
        "status text not null check (status in ('completed', 'partial', 'failed', 'unexecuted'))",
        "started_at timestamptz not null",
        "finished_at timestamptz,",
        "fixture_case_count integer not null check (fixture_case_count >= 0)",
        "evaluated_case_count integer not null check (evaluated_case_count >= 0)",
        "summary jsonb not null",
        "results jsonb not null",
        "metadata jsonb not null default '{}'::jsonb",
        "created_at timestamptz not null default now()",
        "create index if not exists idx_consultation_eval_runs_created "
        "on public.consultation_eval_runs(created_at desc)",
        "create index if not exists idx_consultation_eval_runs_mode_status "
        "on public.consultation_eval_runs(mode, status)",
        "alter table public.consultation_eval_runs enable row level security",
        "revoke all on public.consultation_eval_runs from anon",
        "revoke all on public.consultation_eval_runs from authenticated",
        "revoke all on public.consultation_eval_runs from public",
    ):
        assert fragment in sql, fragment
    assert "create policy" not in sql
    assert "security definer" not in sql



class FakeSupabaseInsertRecorder:
    """Record the DB boundary, without allowing operational-schema writes."""

    def __init__(self, *, failure=None, before_execute=None):
        self.inserted = []
        self.calls = []
        self.failure = failure
        self.before_execute = before_execute

    def schema(self, name):
        self.calls.append(("schema", name))
        assert name == "public"
        return self

    def table(self, name):
        self.calls.append(("table", name))
        assert self.calls[-2] == ("schema", "public")
        assert name == "consultation_eval_runs"
        return self

    def insert(self, row):
        self.calls.append(("insert",))
        self.inserted.append(json.loads(json.dumps(row, allow_nan=False)))
        return self

    def execute(self):
        self.calls.append(("execute",))
        if self.before_execute:
            self.before_execute()
        if self.failure:
            raise self.failure
        return SimpleNamespace(data=self.inserted)


def _completed_report():
    return {
        "run_metadata": {
            "run_id": "eval_20260909T120000Z_abc123", "mode": "live",
            "started_at": "2026-09-09T12:00:00+00:00",
            "finished_at": "2026-09-09T12:01:00+00:00",
            "fixture_case_count": 60, "evaluated_case_count": 1,
            "git_commit": "abc123", "fixture_path": "fixture.json",
        },
        "summary": {"automatic_pass_rate": 1.0},
        "results": [{"case_id": "wage-01", "observed": {"answer": "bounded"}}],
    }


def test_publish_admin_inserts_one_valid_payload_in_public_schema() -> None:
    report = _completed_report()
    original = deepcopy(report)
    fake = FakeSupabaseInsertRecorder()
    assert harness.publish_admin_run(report, fake) == "eval_20260909T120000Z_abc123"
    assert fake.calls == [("schema", "public"), ("table", "consultation_eval_runs"),
                          ("insert",), ("execute",)]
    assert fake.inserted == [{
        "run_id": "eval_20260909T120000Z_abc123", "mode": "live", "status": "completed",
        "started_at": "2026-09-09T12:00:00+00:00",
        "finished_at": "2026-09-09T12:01:00+00:00",
        "fixture_case_count": 60, "evaluated_case_count": 1,
        "summary": {"automatic_pass_rate": 1.0},
        "results": [{"case_id": "wage-01", "observed": {"answer": "bounded"}}],
        "metadata": original["run_metadata"],
    }]
    assert report == original


def test_publish_admin_rejects_invalid_reports_before_database_access() -> None:
    invalid = [None, [], {}, {**_completed_report(), "summary": []},
               {**_completed_report(), "results": {}},
               {**_completed_report(), "run_metadata": []}]
    for key, value in (
        ("run_id", "eval_bad/route"), ("run_id", "eval_한글"),
        ("run_id", "eval_" + "a" * 130), ("run_id", 42),
        ("mode", "offline"), ("started_at", "yesterday"),
        ("started_at", "2026-09-09T12:00:00"), ("finished_at", None),
        ("finished_at", "2026-09-09T11:00:00+00:00"),
        ("fixture_case_count", -1), ("fixture_case_count", True),
        ("fixture_case_count", 0), ("evaluated_case_count", 2),
        ("evaluated_case_count", 1.0),
    ):
        report = _completed_report()
        report["run_metadata"][key] = value
        invalid.append(report)
    for key in _completed_report()["run_metadata"]:
        if key in ("git_commit", "fixture_path"):
            continue
        report = _completed_report()
        del report["run_metadata"][key]
        invalid.append(report)
    for result in (None, {}, {"case_id": "wage-01", "observed": []},
                   {"case_id": "wage-01", "observed": {"answer": 1}},
                   {"case_id": "wage-01", "observed": {"answer": "x" * 3001}}):
        report = _completed_report()
        report["results"] = [result]
        invalid.append(report)
    report = _completed_report()
    report["results"] = []
    report["run_metadata"]["evaluated_case_count"] = 0
    invalid.append(report)
    report = _completed_report()
    report["summary"]["automatic_pass_rate"] = float("nan")
    invalid.append(report)
    for report in invalid:
        fake = FakeSupabaseInsertRecorder()
        try:
            harness.publish_admin_run(report, fake)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid report: {report!r}")
        assert fake.calls == []


def test_publish_admin_derives_failure_status_and_preserves_bounded_answers() -> None:
    for errors, status in (([None], "completed"), (["error"], "failed"),
                           ([None, "error"], "partial")):
        report = _completed_report()
        report["results"] = [
            {"case_id": f"wage-{i}", "pipeline_error": error,
             "observed": {"answer": "가" * 3000, "pipeline_error": error}}
            for i, error in enumerate(errors)
        ]
        report["run_metadata"]["evaluated_case_count"] = len(errors)
        fake = FakeSupabaseInsertRecorder()
        harness.publish_admin_run(report, fake)
        assert fake.inserted[0]["status"] == status
        assert fake.inserted[0]["results"] == report["results"]


def main() -> int:
    tests = [test_consultation_eval_sql_locks_table_and_has_contract,
             test_publish_admin_inserts_one_valid_payload_in_public_schema,
             test_publish_admin_rejects_invalid_reports_before_database_access,
             test_publish_admin_derives_failure_status_and_preserves_bounded_answers]
    try:
        for test in tests:
            test()
            print(f"PASS: {test.__name__}")
    except Exception:
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
