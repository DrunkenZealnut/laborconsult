"""Offline contracts for the Admin consultation-quality feature."""

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


def main() -> int:
    tests = [test_consultation_eval_sql_locks_table_and_has_contract]
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
