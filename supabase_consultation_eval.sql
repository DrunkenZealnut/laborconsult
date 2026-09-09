-- Apply in Supabase SQL Editor before publishing consultation evaluations.
-- Access is reserved for the server-side service-role client.

CREATE TABLE IF NOT EXISTS laborconsult.consultation_eval_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id TEXT NOT NULL UNIQUE,
    mode TEXT NOT NULL CHECK (mode IN ('live', 'offline')),
    status TEXT NOT NULL CHECK (status IN ('completed', 'partial', 'failed', 'unexecuted')),
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    fixture_case_count INTEGER NOT NULL CHECK (fixture_case_count >= 0),
    evaluated_case_count INTEGER NOT NULL CHECK (evaluated_case_count >= 0),
    summary JSONB NOT NULL,
    results JSONB NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_consultation_eval_runs_created
    ON laborconsult.consultation_eval_runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_consultation_eval_runs_mode_status
    ON laborconsult.consultation_eval_runs(mode, status);

ALTER TABLE laborconsult.consultation_eval_runs ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON laborconsult.consultation_eval_runs FROM anon;
REVOKE ALL ON laborconsult.consultation_eval_runs FROM authenticated;
REVOKE ALL ON laborconsult.consultation_eval_runs FROM PUBLIC;
