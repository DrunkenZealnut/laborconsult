"""Offline contracts for the Admin consultation-quality feature."""

from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import patch

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


class FakeSupabaseRunReader:
    """Model read queries and record the schema boundary without a live DB."""

    def __init__(self, rows=(), *, failure=None, missing_response=False):
        self.rows = deepcopy(list(rows))
        self.calls = []
        self.columns = "*"
        self.filters = []
        self.maximum = None
        self.single = False
        self.failure = failure
        self.missing_response = missing_response

    def schema(self, name):
        self.calls.append(("schema", name))
        return self

    def table(self, name):
        self.calls.append(("table", name))
        return self

    def select(self, columns, **kwargs):
        self.calls.append(("select", columns, kwargs))
        self.columns = columns
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def order(self, column, *, desc=False):
        self.calls.append(("order", column, desc))
        self.rows.sort(key=lambda row: row[column], reverse=desc)
        return self

    def limit(self, maximum):
        self.maximum = maximum
        return self

    def maybe_single(self):
        self.single = True
        return self

    def execute(self):
        if self.failure:
            raise self.failure
        if self.missing_response:
            return None
        rows = [row for row in self.rows
                if all(row[column] == value for column, value in self.filters)]
        total = len(rows)
        if self.maximum is not None:
            rows = rows[:self.maximum]
        if self.columns != "*":
            columns = [column.strip() for column in self.columns.split(",")]
            rows = [{column: row[column] for column in columns} for row in rows]
        data = (rows[0] if rows else None) if self.single else rows
        return SimpleNamespace(data=data, count=total)


def _stored_run(**overrides):
    return {
        "id": "a79063c8-81b9-42ba-bda2-27cc612ef4ef",
        "run_id": "eval_20260909T120000Z_abc123",
        "mode": "live", "status": "completed",
        "started_at": "2026-09-09T12:00:00+00:00",
        "finished_at": "2026-09-09T12:01:00+00:00",
        "created_at": "2026-09-09T12:01:01+00:00",
        "fixture_case_count": 60, "evaluated_case_count": 1,
        "summary": {"automatic_pass_rate": 1.0},
        "metadata": {"git_commit": "abc123"},
        "results": [{"case_id": "wage-01", "observed": {"answer": "<b>상담</b>"}}],
        **overrides,
    }


def _assert_http_error(status, call):
    from fastapi import HTTPException
    try:
        call()
    except HTTPException as error:
        assert error.status_code == status, error.status_code
        assert isinstance(error.detail, str) and error.detail
        assert "secret-database-error" not in error.detail
    else:
        raise AssertionError(f"expected HTTP {status}")


def test_admin_evaluation_runs_lists_summaries_in_public_schema() -> None:
    import api.index as api
    row = _stored_run()
    fake = FakeSupabaseRunReader([row])
    with patch.object(api, "_get_supabase", return_value=fake):
        response = api.admin_evaluation_runs(_admin={"role": "admin"})
    expected = {key: value for key, value in row.items() if key not in ("id", "results")}
    assert response == {"runs": [expected], "total": 1}
    assert fake.calls[:2] == [("schema", "public"), ("table", "consultation_eval_runs")]
    assert fake.columns != "*" and "results" not in fake.columns
    assert fake.calls[2][2] == {"count": "exact"}
    assert ("order", "created_at", True) in fake.calls
    assert fake.maximum == 20


def test_admin_evaluation_runs_clamps_limits_and_filters_before_counting() -> None:
    import api.index as api
    rows = [_stored_run(run_id=f"eval_{i}", created_at=f"2026-09-09T12:{i:02}:00Z")
            for i in range(3)]
    rows += [_stored_run(mode="offline"), _stored_run(status="failed")]
    for requested, expected in ((200, 100), (0, 1), (-10, 1), (2, 2)):
        fake = FakeSupabaseRunReader(rows)
        with patch.object(api, "_get_supabase", return_value=fake):
            response = api.admin_evaluation_runs(
                limit=requested, mode="live", status="completed", _admin={"role": "admin"})
        assert fake.maximum == expected
        assert response["total"] == 3
        assert [row["run_id"] for row in response["runs"]] == ["eval_2", "eval_1", "eval_0"][:expected]


def test_admin_evaluation_runs_empty_list() -> None:
    import api.index as api
    with patch.object(api, "_get_supabase", return_value=FakeSupabaseRunReader()):
        assert api.admin_evaluation_runs(_admin={"role": "admin"}) == {"runs": [], "total": 0}


def test_admin_evaluation_run_returns_full_row_in_public_schema() -> None:
    import api.index as api
    for run_id in ("eval_20260909T120000Z_abc123", "eval_A-z_09", "eval_" + "a" * 123):
        row = _stored_run(run_id=run_id)
        fake = FakeSupabaseRunReader([_stored_run(run_id="eval_other"), row])
        with patch.object(api, "_get_supabase", return_value=fake):
            response = api.admin_evaluation_run(run_id, _admin={"role": "admin"})
        assert response == row
        assert fake.calls[:2] == [("schema", "public"), ("table", "consultation_eval_runs")]


def test_admin_evaluation_run_rejects_invalid_ids_before_database_access() -> None:
    import api.index as api
    for run_id in ("", "eval_", "other_123", "eval_한글", "eval_a/b", "eval_a.b",
                   "eval_a\n", "eval_" + "a" * 124):
        with patch.object(api, "_get_supabase", side_effect=AssertionError("DB accessed")):
            _assert_http_error(400, lambda: api.admin_evaluation_run(run_id, _admin={"role": "admin"}))


def test_admin_evaluation_run_missing_rows_are_404() -> None:
    import api.index as api
    for fake in (FakeSupabaseRunReader(), FakeSupabaseRunReader(missing_response=True)):
        with patch.object(api, "_get_supabase", return_value=fake):
            _assert_http_error(404, lambda: api.admin_evaluation_run("eval_missing", _admin={"role": "admin"}))


def test_admin_evaluation_database_errors_are_safe_503() -> None:
    import api.index as api
    for call in (lambda: api.admin_evaluation_runs(_admin={"role": "admin"}),
                 lambda: api.admin_evaluation_run("eval_one", _admin={"role": "admin"})):
        fake = FakeSupabaseRunReader(failure=RuntimeError("secret-database-error"))
        with patch.object(api, "_get_supabase", return_value=fake):
            _assert_http_error(503, call)
        with patch.object(api, "get_config", return_value=SimpleNamespace(supabase=None)):
            _assert_http_error(503, call)


def test_admin_evaluation_routes_enforce_existing_auth_and_serialize_results() -> None:
    import api.index as api
    from fastapi.testclient import TestClient
    row = _stored_run()
    paths = ("/api/admin/evaluation-runs", "/api/admin/evaluation-runs/" + row["run_id"])
    with TestClient(api.app) as client, patch.object(api, "JWT_SECRET", "test-secret-" * 4):
        with patch.object(api, "_get_supabase", side_effect=AssertionError("unauthorized DB access")):
            for path in paths:
                for headers in ({}, {"Authorization": "Bearer invalid"}):
                    response = client.get(path, headers=headers)
                    assert response.status_code == 401, response.text
                    assert set(response.json()) == {"detail"}
                token = api.jwt.encode({"role": "viewer"}, api.JWT_SECRET, algorithm="HS256")
                assert client.get(path, headers={"Authorization": "Bearer " + token}).status_code == 403
        token = api.jwt.encode({"role": "admin"}, api.JWT_SECRET, algorithm="HS256")
        for path in paths:
            with patch.object(api, "_get_supabase", return_value=FakeSupabaseRunReader([row])):
                response = client.get(path, headers={"Authorization": "Bearer " + token})
            assert response.status_code == 200, response.text
            if path == paths[1]:
                assert response.json() == row
            else:
                assert response.json()["total"] == 1
                assert "results" not in response.json()["runs"][0]


def main() -> int:
    tests = [test_consultation_eval_sql_locks_table_and_has_contract,
             test_publish_admin_inserts_one_valid_payload_in_public_schema,
             test_publish_admin_rejects_invalid_reports_before_database_access,
             test_publish_admin_derives_failure_status_and_preserves_bounded_answers,
             test_admin_evaluation_runs_lists_summaries_in_public_schema,
             test_admin_evaluation_runs_clamps_limits_and_filters_before_counting,
             test_admin_evaluation_runs_empty_list,
             test_admin_evaluation_run_returns_full_row_in_public_schema,
             test_admin_evaluation_run_rejects_invalid_ids_before_database_access,
             test_admin_evaluation_run_missing_rows_are_404,
             test_admin_evaluation_database_errors_are_safe_503,
             test_admin_evaluation_routes_enforce_existing_auth_and_serialize_results]
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
