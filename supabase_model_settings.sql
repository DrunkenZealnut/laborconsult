-- 답변 모델 설정 저장소 (admin-model-settings)
--
-- 관리자 화면에서 고른 답변 모델(Claude·OpenAI·Gemini)과 1순위 제공자를 담는 단일 행 문서.
-- 파이프라인은 service-role 로 60초 캐시해 읽고, 읽기 실패 시 코드 기본값으로 동작한다
-- (app/core/model_settings.py). 쓰기는 answer_model_settings_save RPC 한 경로 — CAS + 이력.
--
-- 적용 순서: supabase_legal_rules.sql 다음(7번째). 멱등이라 재실행해도 안전하다.
-- 적용 전: 공유 프로젝트라 이름 충돌부터 확인할 것(CLAUDE.md "소유권을 이름으로 판단하지 말 것").
--   SELECT table_schema, table_name FROM information_schema.tables
--    WHERE table_name LIKE 'answer_model%';

CREATE TABLE IF NOT EXISTS laborconsult.answer_model_settings (
    id          SMALLINT PRIMARY KEY CHECK (id = 1),
    settings    JSONB NOT NULL DEFAULT '{}'::jsonb,
    revision    BIGINT NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by  TEXT
);

INSERT INTO laborconsult.answer_model_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS laborconsult.answer_model_setting_events (
    id          BIGSERIAL PRIMARY KEY,
    revision    BIGINT NOT NULL,
    actor       TEXT,
    before      JSONB NOT NULL,
    after       JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- RLS ON + 정책 무부여 = anon/authenticated 직접 접근 차단. 커스텀 스키마라 기본 권한이
-- 자동 부여되지 않으므로 service_role 읽기 GRANT 를 명시한다(쓰기는 RPC 로만).
ALTER TABLE laborconsult.answer_model_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE laborconsult.answer_model_setting_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON laborconsult.answer_model_settings FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON laborconsult.answer_model_setting_events FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON laborconsult.answer_model_settings, laborconsult.answer_model_setting_events TO service_role;

CREATE OR REPLACE FUNCTION laborconsult.answer_model_settings_save(
    expected_revision BIGINT, new_settings JSONB, event_actor TEXT
)
RETURNS BIGINT
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = laborconsult, pg_temp
AS $$
DECLARE
    current_revision BIGINT;
    old_settings JSONB;
BEGIN
    -- 첫 문장에서 NULL/비객체를 거절한다 — check_schema.py 가 이 성질로 부작용 없이 존재를 확인한다.
    IF new_settings IS NULL OR jsonb_typeof(new_settings) <> 'object' THEN
        RAISE EXCEPTION 'INVALID_MODEL_SETTINGS' USING ERRCODE = '22023';
    END IF;

    SELECT s.revision, s.settings INTO current_revision, old_settings
      FROM laborconsult.answer_model_settings s
     WHERE s.id = 1
       FOR UPDATE;

    IF current_revision IS NULL OR expected_revision IS NULL
       OR expected_revision <> current_revision THEN
        -- 40001(serialization_failure)을 쓰지 말 것. PostgREST가 재시도 대상으로 취급해 응답이
        -- 클라이언트 타임아웃까지 멈춘다(실측 2026-09-30: 30초/40초 ReadTimeout, legal_rules_save도 동일).
        -- PTxyz 는 PostgREST 사용자 정의 상태 — HTTP 409로 즉시 응답된다.
        RAISE EXCEPTION 'MODEL_SETTINGS_REVISION_CONFLICT' USING ERRCODE = 'PT409';
    END IF;

    UPDATE laborconsult.answer_model_settings
       SET settings = new_settings,
           revision = current_revision + 1,
           updated_at = now(),
           updated_by = event_actor
     WHERE id = 1;

    INSERT INTO laborconsult.answer_model_setting_events (revision, actor, before, after)
    VALUES (current_revision + 1, event_actor, old_settings, new_settings);

    RETURN current_revision + 1;
END;
$$;

REVOKE ALL ON FUNCTION laborconsult.answer_model_settings_save(BIGINT, JSONB, TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION laborconsult.answer_model_settings_save(BIGINT, JSONB, TEXT) TO service_role;

-- 검증 (적용 후 실행):
--   SELECT id, revision, settings FROM laborconsult.answer_model_settings;           -- 1행, revision 0
--   SELECT has_table_privilege('anon', 'laborconsult.answer_model_settings', 'SELECT'); -- false
--   SELECT has_function_privilege('service_role',
--          'laborconsult.answer_model_settings_save(bigint, jsonb, text)', 'EXECUTE');   -- true
