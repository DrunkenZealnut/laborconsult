# Admin 상담 답변 품질 조회 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish explicit Live consultation-evaluation runs to Supabase and expose their summaries and case results in the authenticated Admin page.

**Architecture:** The evaluator remains the only Live execution entry point. A `--publish-admin` flag validates and inserts a completed local report into a locked Supabase table; the existing FastAPI admin surface reads that table through JWT-protected endpoints; `public/admin.html` renders the result without direct Supabase access or browser-triggered evaluations.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, Supabase PostgREST client, PostgreSQL SQL migrations, vanilla HTML/CSS/JavaScript, direct-runner Python tests, Node TAP tests.

**Spec:** `docs/superpowers/specs/2026-09-09-admin-consultation-quality-design.md`

## Global Constraints

- `--publish-admin` must require `--live`; offline publishing returns CLI error 2.
- The evaluator must keep `config.supabase = None` while pipeline cases execute, preventing operational conversation persistence.
- The browser must never connect directly to Supabase and must never start a Live evaluation.
- All Admin evaluation endpoints must reuse `require_admin` and return existing 401/404/503 error conventions.
- Saved answers remain capped at 3,000 characters; no full answer is added to the operational database.
- Supabase RLS is enabled with no anon/authenticated table policies; only server-side credentials access the table.
- Existing conversation, attachment, abuse, production pipeline, fixture, and scoring behavior must remain unchanged.
- Preserve unrelated working-tree changes in `.bkit/state/memory.json` and `.claude/`.
- The existing Supabase client defaults to `laborconsult`; evaluation table access must explicitly use `.schema("laborconsult")` without changing that shared default. Focused tests must assert this boundary.

---

### Task 1: Create locked Supabase evaluation-run schema

**Files:**
- Create: `supabase_consultation_eval.sql`
- Create: `test_admin_consultation_quality.py`

**Interfaces:**
- Produces table `laborconsult.consultation_eval_runs` consumed by the CLI publisher and Admin API.
- Produces static SQL assertions reusable by later reviewers without requiring a live Supabase connection.

- [ ] **Step 1: Write the failing SQL contract test**

Add a direct-runner test that reads `supabase_consultation_eval.sql` and asserts the required table, columns, checks, indexes, RLS, and public-role revokes:

```python
def test_consultation_eval_sql_locks_table_and_has_contract() -> None:
    sql = Path("supabase_consultation_eval.sql").read_text(encoding="utf-8").lower()
    for fragment in (
        "create table if not exists laborconsult.consultation_eval_runs",
        "run_id text not null unique",
        "summary jsonb not null",
        "results jsonb not null",
        "enable row level security",
        "revoke all on laborconsult.consultation_eval_runs from anon",
        "revoke all on laborconsult.consultation_eval_runs from authenticated",
        "idx_consultation_eval_runs_created",
    ):
        assert fragment in sql, fragment
    assert "create policy" not in sql
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
./.venv/bin/python test_admin_consultation_quality.py
```

Expected: FAIL because the migration file does not exist.

- [ ] **Step 3: Write the minimal SQL migration**

Create `laborconsult.consultation_eval_runs` with `uuid` primary key, `run_id` uniqueness, `mode` and `status` checks, nonnegative case counts, `jsonb` summary/results/metadata, timestamps, descending created index, mode/status index, RLS enablement, and `REVOKE ALL` from `anon`, `authenticated`, and `PUBLIC`. Do not create policies or SECURITY DEFINER functions; the Python server uses its existing server-side Supabase client.

- [ ] **Step 4: Run the focused test and verify it passes**

Run the same command. Expected: PASS with every SQL fragment asserted.

- [ ] **Step 5: Commit**

```bash
git add supabase_consultation_eval.sql test_admin_consultation_quality.py
git commit -m "feat: add consultation evaluation run schema"
```

### Task 2: Add explicit CLI publication of completed evaluation runs

**Files:**
- Modify: `eval_consultation.py:312-412`
- Modify: `test_consultation_eval.py`
- Modify: `test_admin_consultation_quality.py`

**Interfaces:**
- Consumes the existing report root shape: `run_metadata`, `summary`, and `results`.
- Produces `publish_admin_run(report: dict, supabase) -> str`.
- Adds `--publish-admin` to `main(argv)` and emits `admin publish: PASS` on success.

- [ ] **Step 1: Write failing publication and option tests**

Add tests that prove the flag contract before any Supabase call:

```python
def test_publish_admin_requires_live() -> None:
    assert harness.main(["--offline", "--publish-admin"]) == 2

def test_publish_admin_inserts_one_valid_payload() -> None:
    fake = FakeSupabaseInsertRecorder()
    report = {
        "run_metadata": {
            "run_id": "eval_20260909T120000Z_abc123",
            "mode": "live",
            "started_at": "2026-09-09T12:00:00+00:00",
            "finished_at": "2026-09-09T12:01:00+00:00",
            "fixture_case_count": 1,
            "evaluated_case_count": 1,
        },
        "summary": {"automatic_pass_rate": 1.0},
        "results": [{"case_id": "wage-01", "observed": {"answer": "bounded"}}],
    }
    assert harness.publish_admin_run(report, fake) == report["run_metadata"]["run_id"]
    assert len(fake.inserted) == 1
    row = fake.inserted[0]
    assert row["run_id"] == report["run_metadata"]["run_id"]
    assert row["summary"] == report["summary"]
    assert len(row["results"]) == len(report["results"])

def test_publish_admin_preserves_local_report_when_insert_fails(tmp_path: Path) -> None:
    # invoke main with a fake Supabase client whose insert raises RuntimeError
    # and assert the output JSON remains readable and main returns 1.
```

The fake client must record the actual insert payload and raise on `.execute()`; it must not only assert that a mock method was called.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
./.venv/bin/python test_consultation_eval.py
./.venv/bin/python test_admin_consultation_quality.py
```

Expected: the new imports/options or publisher are missing, so the new tests fail.

- [ ] **Step 3: Implement the publication boundary**

Add standard-library helpers for a URL-safe `run_id`, report validation, and `publish_admin_run`. Require `run_metadata`, `summary`, and `results`; map `started_at`, `finished_at`, `fixture_case_count`, `evaluated_case_count`, `mode`, and `metadata` into one row; preserve the existing bounded `observed.answer`. Call exactly one `supabase.schema("laborconsult").table("consultation_eval_runs").insert(row).execute()` and return the run ID. Add an offline assertion that the publisher uses the explicit laborconsult-schema boundary.

Add `--publish-admin` to the parser. Reject it unless `args.live` is true before loading `AppConfig`. In Live mode, keep the original Supabase client only as a publisher client, copy the config for `run_case`, set the copy’s `supabase` to `None`, write the local JSON first, then publish. Return 1 for configuration, output, pipeline, or publication failures and retain the local output file. Do not publish when the selected run is empty.

- [ ] **Step 4: Run focused tests and verify they pass**

```bash
./.venv/bin/python test_consultation_eval.py
./.venv/bin/python test_admin_consultation_quality.py
./.venv/bin/python -I -S eval_consultation.py --offline
```

Expected: all direct tests pass; the isolated offline command never imports application clients and still prints the four existing PASS lines.

- [ ] **Step 5: Commit**

```bash
git add eval_consultation.py test_consultation_eval.py test_admin_consultation_quality.py
git commit -m "feat: publish consultation evaluation runs"
```

### Task 3: Add authenticated Admin evaluation-run API

**Files:**
- Modify: `api/index.py` after `admin_stats` and before conversation routes
- Modify: `test_admin_consultation_quality.py`

**Interfaces:**
- Consumes `laborconsult.consultation_eval_runs` through the existing `_get_supabase()` client.
- Produces `GET /api/admin/evaluation-runs` and `GET /api/admin/evaluation-runs/{run_id}`.
- Reuses `require_admin`, `_get_supabase`, and existing JSON error conventions.

- [ ] **Step 1: Write failing API contract tests**

Call the route functions with a fake Supabase client and explicit `_admin={"role": "admin"}`. Assert the list query excludes `results`, clamps `limit`, applies mode/status filters, orders by `created_at` descending, and returns the exact list envelope. Assert detail returns `results`, rejects invalid run IDs, returns 404 for no row, and translates DB errors to 503.

```python
def test_admin_evaluation_runs_requires_existing_route_contract() -> None:
    response = api.admin_evaluation_runs(limit=200, _admin={"role": "admin"})
    assert response["total"] == 1
    assert "results" not in response["runs"][0]

def test_admin_evaluation_run_returns_case_results() -> None:
    response = api.admin_evaluation_run("eval_20260909T120000Z_abc123", _admin={"role": "admin"})
    assert response["results"][0]["case_id"] == "wage-01"
```

- [ ] **Step 2: Run the focused test and verify it fails**

```bash
./.venv/bin/python test_admin_consultation_quality.py
```

Expected: `AttributeError` or route-not-found failure for the new functions.

- [ ] **Step 3: Implement the two read-only routes**

Add a private `_validate_eval_run_id` that permits only `eval_` plus ASCII letters, digits, `_`, and `-`, with a bounded length. Query only the summary/list columns for the list endpoint and clamp `limit` to 1–100. Query the full row for detail after validating the path ID. Use `supabase.schema("laborconsult").table("consultation_eval_runs")` for both routes and add an offline assertion for that boundary. Convert missing rows to `HTTPException(404, ...)`, Supabase exceptions to `HTTPException(503, ...)`, and never expose raw exception strings. All route signatures include `_admin=Depends(require_admin)`.

- [ ] **Step 4: Run API tests and existing Admin auth checks**

```bash
./.venv/bin/python test_admin_consultation_quality.py
./.venv/bin/python test_e2e.py --help
```

Expected: route contract tests pass; the existing E2E runner remains importable and its unauthenticated Admin endpoint test is unchanged.

- [ ] **Step 5: Commit**

```bash
git add api/index.py test_admin_consultation_quality.py
git commit -m "feat: add admin consultation evaluation API"
```

### Task 4: Add the Admin `답변 품질` view

**Files:**
- Modify: `public/admin.html`
- Create: `test_admin_quality.js`

**Interfaces:**
- Consumes the two `/api/admin/evaluation-runs` endpoints and the existing `adminFetch` token helper.
- Produces view IDs `quality-view`, `quality-status`, `quality-stat-cards`, `quality-run-list`, and `quality-detail`.
- Produces pure render helpers `renderEvaluationSummary`, `renderEvaluationRuns`, `renderEvaluationDetail`, and `formatEvaluationMetric` for direct JavaScript tests.

- [ ] **Step 1: Write failing JavaScript render tests**

Extract the named pure functions from `public/admin.html` into a Node VM test, then assert empty/live-unexecuted and completed states:

```javascript
test('미실행 평가 결과는 0이 아니라 측정 없음으로 표시한다', () => {
  const html = renderEvaluationSummary({ mode: 'live', status: 'unexecuted', summary: {} });
  assert.match(html, /측정 없음/);
  assert.doesNotMatch(html, /(?:>|:)0(?:<|$)/);
});

test('사례 상세는 답변과 오류를 HTML로 실행하지 않는다', () => {
  const html = renderEvaluationDetail({
    question: '<script>alert(1)</script>', answer: '<b>x</b>', pipeline_error: 'bad',
  });
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);
});
```

- [ ] **Step 2: Run the focused JS test and verify it fails**

```bash
node test_admin_quality.js
```

Expected: the named render helpers are absent.

- [ ] **Step 3: Add the view markup, styles, and render/fetch flow**

Add a third nav button and hidden view. `showView('quality')` calls `loadEvaluationRuns()`, which uses `adminFetch` and displays loading, empty, API error, or run-list states. Selecting a run calls the detail endpoint. Render all server strings through `escapeHtml`; never pass question, answer, error, metadata, or source values directly into an HTML template. Use `formatEvaluationMetric` to return `측정 없음` for `null`/`undefined`, percentages for rates, and millisecond formatting for timing.

Display the latest summary cards and a run list with mode/status badges. Detail rows must show case ID/category, automatic pass, optional score fields, error, question, bounded answer, sources, analysis, calculation, and timing. Keep the existing dashboard, conversation, login, logout, Markdown, and attachment behavior unchanged.

- [ ] **Step 4: Run UI tests and existing Admin page checks**

```bash
node test_admin_quality.js
node test_answer_renderer.js
node test_answer_glance.js
```

Expected: new render tests and existing 8+16 TAP tests pass.

- [ ] **Step 5: Commit**

```bash
git add public/admin.html test_admin_quality.js
git commit -m "feat: show consultation quality in admin"
```

### Task 5: Document rollout and run integrated verification

**Files:**
- Modify: `CLAUDE.md` in the Admin/API and operational evaluation sections
- Modify: `test_e2e.py` with unauthenticated evaluation endpoint checks
- Modify: `test_admin_consultation_quality.py` if integrated assertions need a shared helper

**Interfaces:**
- Documents `supabase_consultation_eval.sql`, the required server-side Supabase credentials, the smoke publish command, and the full 60-case publish command.
- Extends E2E coverage without requiring a live evaluation or a live database in the default test run.

- [ ] **Step 1: Write failing E2E/auth contract tests**

Add to `test_e2e.py`:

```python
def test_admin_evaluation_runs_unauthorized(base_url: str) -> bool:
    r = requests.get(f"{base_url}/api/admin/evaluation-runs", timeout=10)
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"
    return True
```

Register it next to `test_admin_stats_unauthorized`. Add static documentation assertions in the direct test only if the repository’s current docs test pattern requires them; otherwise verify the commands manually during this task.

- [ ] **Step 2: Run the focused E2E contract test and verify it fails before the route exists**

```bash
uvicorn api.index:app --host 127.0.0.1 --port 5555
./.venv/bin/python test_e2e.py --base-url http://127.0.0.1:5555 --quick
```

Expected before Task 3: the new unauthenticated evaluation endpoint check receives 404. Stop the local server after the red run; do not call a remote deployment from the default test command.

- [ ] **Step 3: Document deployment and operator commands**

Document the SQL apply order and these commands:

```bash
./.venv/bin/python eval_consultation.py --live --case wage-01 --limit 1 --publish-admin --output /tmp/consultation-smoke.json
./.venv/bin/python eval_consultation.py --live --publish-admin --output eval_consultation_results.json
```

State that Admin only displays published results, Live execution is not started by the browser, and the first production run must verify the local JSON before publication.

- [ ] **Step 4: Run the complete offline verification set**

```bash
./.venv/bin/python test_admin_consultation_quality.py
./.venv/bin/python test_consultation_eval.py
./.venv/bin/python -I -S eval_consultation.py --offline
./.venv/bin/python test_wage_golden.py
./.venv/bin/python test_pipeline_wiring.py
./.venv/bin/python test_offline_units.py
./.venv/bin/python test_llm_fallback.py
node test_admin_quality.js
node test_answer_renderer.js
node test_answer_glance.js
git diff --check
```

Do not run a Live evaluation or apply the Supabase migration automatically; those are operator actions in the rollout section.

- [ ] **Step 5: Commit documentation and E2E coverage**

```bash
git add CLAUDE.md test_e2e.py
git commit -m "docs: document admin consultation quality rollout"
```
