-- Apply after supabase_schema.sql, using a database owner connection.
-- No law values are seeded. Only the server service-role can access this registry.
BEGIN;

CREATE TABLE IF NOT EXISTS laborconsult.legal_rule_registry (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    revision BIGINT NOT NULL DEFAULT 0 CHECK (revision >= 0),
    document JSONB NOT NULL DEFAULT jsonb_build_object('records', jsonb_build_array(), 'scans', jsonb_build_array()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (jsonb_typeof(document->'records') = 'array'),
    CHECK (jsonb_typeof(document->'scans') = 'array')
);
INSERT INTO laborconsult.legal_rule_registry(id) VALUES (1) ON CONFLICT DO NOTHING;

-- payload 에는 **바뀐 레코드만** 담는다. 초판은 변경마다 registry 전량을 복사해
-- 이력 크기가 revision 수 × 문서 크기로 늘었다(registry 의 8MB 문제를 이력에서 반복).
-- 근거 원문은 evidence_id + sha256 으로 고정되므로 이력에 복제하지 않는다.
CREATE TABLE IF NOT EXISTS laborconsult.legal_rule_events (
    revision BIGINT PRIMARY KEY,
    actor TEXT NOT NULL,
    action JSONB NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- 초판(document 전량)에서 넘어오는 경로. 이름만 바꿔 기존 행은 보존한다.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'laborconsult' AND table_name = 'legal_rule_events'
                 AND column_name = 'document') THEN
        ALTER TABLE laborconsult.legal_rule_events RENAME COLUMN document TO payload;
    END IF;
END $$;
ALTER TABLE laborconsult.legal_rule_events ALTER COLUMN payload SET DEFAULT '{}'::jsonb;

ALTER TABLE laborconsult.legal_rule_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE laborconsult.legal_rule_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON laborconsult.legal_rule_registry FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON laborconsult.legal_rule_events FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON laborconsult.legal_rule_registry, laborconsult.legal_rule_events TO service_role;

-- 인자가 늘면 CREATE OR REPLACE 는 **덮어쓰지 않고 오버로드를 만든다** — 초판 4인자
-- 함수가 남아 있으면 그쪽 호출이 계속 전량을 이력에 쓴다. 먼저 지운다.
DROP FUNCTION IF EXISTS laborconsult.legal_rules_save(BIGINT, JSONB, TEXT, JSONB);

CREATE OR REPLACE FUNCTION laborconsult.legal_rules_save(
    expected_revision BIGINT, new_document JSONB, event_actor TEXT, event_action JSONB,
    event_payload JSONB DEFAULT '{}'::jsonb
) RETURNS BIGINT
LANGUAGE plpgsql SECURITY DEFINER
-- pg_temp 를 **명시적으로 마지막에** 둔다. 목록에서 빠지면 PostgreSQL 이 관계 이름을
-- 찾을 때 pg_temp 를 가장 먼저 뒤지므로, CREATE TEMP 권한이 있는 사용자가 동명 임시
-- 테이블로 SECURITY DEFINER 함수를 속일 수 있다(pg_catalog 는 생략해도 암묵적 최우선).
SET search_path = laborconsult, pg_temp
AS $$
DECLARE current_revision BIGINT;
BEGIN
    IF new_document IS NULL OR
       jsonb_typeof(new_document->'records') IS DISTINCT FROM 'array' OR
       jsonb_typeof(new_document->'scans') IS DISTINCT FROM 'array' OR
       octet_length(new_document::text) > 8000000 OR
       length(trim(coalesce(event_actor, ''))) = 0 OR
       jsonb_typeof(event_action) IS DISTINCT FROM 'object' OR
       jsonb_typeof(coalesce(event_payload, '{}'::jsonb)) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'INVALID_LEGAL_RULE_DOCUMENT' USING ERRCODE = '22023';
    END IF;
    SELECT revision INTO current_revision FROM laborconsult.legal_rule_registry WHERE id = 1 FOR UPDATE;
    IF current_revision IS NULL OR expected_revision IS NULL OR expected_revision <> current_revision THEN
        RAISE EXCEPTION 'LEGAL_RULE_REVISION_CONFLICT' USING ERRCODE = '40001';
    END IF;
    UPDATE laborconsult.legal_rule_registry
       SET revision = current_revision + 1, document = new_document, updated_at = now() WHERE id = 1;
    INSERT INTO laborconsult.legal_rule_events(revision, actor, action, payload)
        VALUES (current_revision + 1, event_actor, event_action,
                coalesce(event_payload, '{}'::jsonb));
    RETURN current_revision + 1;
END;
$$;

REVOKE ALL ON FUNCTION laborconsult.legal_rules_save(BIGINT, JSONB, TEXT, JSONB, JSONB)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION laborconsult.legal_rules_save(BIGINT, JSONB, TEXT, JSONB, JSONB) TO service_role;
COMMIT;
