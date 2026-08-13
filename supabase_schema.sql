-- ============================================================================
-- laborconsult — 기본 스키마 (1/4)
--
-- 설계: docs/02-design/features/supabase-schema-migration.design.md §4
-- 실행: Supabase SQL Editor. **파일 단위로 나눠 실행할 것** — 한 번에 붙여넣으면
--       구문 오류 하나로 전량 롤백되고 어디서 막혔는지도 보이지 않는다.
--
-- 적용 순서
--   1) supabase_schema.sql          ← 이 파일. 스키마를 만들므로 반드시 첫 번째
--   2) supabase_abuse_guard.sql
--   3) supabase_board_posts.sql
--   4) supabase_retention_purge.sql
--
-- 적용 후 완료 조건은 "실행했다"가 아니라 **`python3 check_schema.py` 전수 통과**다.
-- 2026-08-13 이전 프로젝트 전환에서 base 파일만 적용하고 후속 패치를 놓쳐
-- `qa_sessions.session_data`·`law_article_cache`가 빠진 채 프로덕션이 돌았다
-- (증상: 매 채팅 PGRST204 → 후속 질문 맥락 유실, 법령 L2 캐시 404). 그래서 이
-- 파일은 패치를 본문에 흡수한 **최종 상태**다.
--
-- ⚠️ PostgREST 노출은 DDL로 못 한다. Supabase 대시보드 → Settings → API →
--    Exposed schemas 에 `laborconsult` 가 있어야 한다(현 환경은 설정 완료).
--
-- ⚠️ 모든 객체를 `laborconsult.` 로 한정한다. 스키마를 생략하면 search_path 에
--    따라 `public` 의 동명 객체를 건드릴 수 있다 — 2026-08-13 board_posts 사고가
--    정확히 그 경로였다(다른 앱의 테이블을 우리 것으로 오인).
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS laborconsult;
GRANT USAGE ON SCHEMA laborconsult TO anon, authenticated, service_role;


-- ── 1. 세션 ────────────────────────────────────────────────────────────────
-- id 는 앱의 12자 hex 세션 ID 와 호환되어야 하므로 UUID 가 아니라 TEXT 다.
-- session_data 는 세션 스냅샷(app/core/storage.py::save_session_data).
CREATE TABLE IF NOT EXISTS laborconsult.qa_sessions (
    id           TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    session_data JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- ── 2. 대화 ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS laborconsult.qa_conversations (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id        TEXT NOT NULL
                        REFERENCES laborconsult.qa_sessions(id) ON DELETE CASCADE,
    category          TEXT NOT NULL DEFAULT '일반상담',
    question_text     TEXT NOT NULL,
    answer_text       TEXT NOT NULL DEFAULT '',
    calculation_types TEXT[] DEFAULT '{}',
    metadata          JSONB DEFAULT '{}',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_qa_conversations_session
    ON laborconsult.qa_conversations(session_id);
CREATE INDEX IF NOT EXISTS idx_qa_conversations_category
    ON laborconsult.qa_conversations(category);
CREATE INDEX IF NOT EXISTS idx_qa_conversations_created
    ON laborconsult.qa_conversations(created_at DESC);


-- ── 3. 첨부파일 ────────────────────────────────────────────────────────────
-- public_url 은 버킷이 비공개라 **항상 NULL** 이다. 열람은 관리자 조회 시점에
-- 발급하는 1시간 만료 signed URL 이 유일한 경로다(개인정보처리방침 제7항).
CREATE TABLE IF NOT EXISTS laborconsult.qa_attachments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL
                      REFERENCES laborconsult.qa_conversations(id) ON DELETE CASCADE,
    filename        TEXT NOT NULL,
    content_type    TEXT NOT NULL,
    storage_path    TEXT NOT NULL,
    public_url      TEXT,
    file_size       INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_qa_attachments_conversation
    ON laborconsult.qa_attachments(conversation_id);


-- ── 4. 법령 조문 L2 캐시 ───────────────────────────────────────────────────
-- app/core/legal_api.py::_l2_cache_get() / _l2_cache_set() 가 사용.
-- 이 테이블이 없으면 법제처 조회가 매번 API 를 때린다(404 로그만 남고 무증상).
CREATE TABLE IF NOT EXISTS laborconsult.law_article_cache (
    cache_key   TEXT PRIMARY KEY,
    law_name    TEXT,
    article_no  INTEGER,
    content     TEXT,
    source_type TEXT DEFAULT 'law',
    fetched_at  TIMESTAMPTZ,
    expires_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_law_article_cache_expires
    ON laborconsult.law_article_cache (expires_at);


-- ── 5. RLS ─────────────────────────────────────────────────────────────────
-- anon 키는 서버(FastAPI)에만 있고 브라우저로 나가지 않는다(public/ 에 supabase
-- 문자열 0건). 그래도 최소 권한을 유지한다.
--
-- ⚠️ DELETE 정책은 어느 테이블에도 부여하지 않는다. 하드 삭제는 보존기간 purge
--    (postgres 역할)만 수행한다. anon 에 DELETE 를 열면 키 유출 시 상담 이력
--    전체가 삭제 가능해진다.
--
-- ⚠️ 정책 이름에 큰따옴표를 쓰지 않는다 — SQL Editor 붙여넣기 과정에서 스마트
--    따옴표(U+201C)로 바뀌면 `syntax error at or near ...` 로 죽는다(실제 발생).

ALTER TABLE laborconsult.qa_sessions       ENABLE ROW LEVEL SECURITY;
ALTER TABLE laborconsult.qa_conversations  ENABLE ROW LEVEL SECURITY;
ALTER TABLE laborconsult.qa_attachments    ENABLE ROW LEVEL SECURITY;
ALTER TABLE laborconsult.law_article_cache ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS anon_insert_sessions ON laborconsult.qa_sessions;
CREATE POLICY anon_insert_sessions ON laborconsult.qa_sessions
    FOR INSERT TO anon WITH CHECK (true);
DROP POLICY IF EXISTS anon_select_sessions ON laborconsult.qa_sessions;
CREATE POLICY anon_select_sessions ON laborconsult.qa_sessions
    FOR SELECT TO anon USING (true);
DROP POLICY IF EXISTS anon_update_sessions ON laborconsult.qa_sessions;
CREATE POLICY anon_update_sessions ON laborconsult.qa_sessions
    FOR UPDATE TO anon USING (true);

DROP POLICY IF EXISTS anon_insert_conversations ON laborconsult.qa_conversations;
CREATE POLICY anon_insert_conversations ON laborconsult.qa_conversations
    FOR INSERT TO anon WITH CHECK (true);
DROP POLICY IF EXISTS anon_select_conversations ON laborconsult.qa_conversations;
CREATE POLICY anon_select_conversations ON laborconsult.qa_conversations
    FOR SELECT TO anon USING (true);

DROP POLICY IF EXISTS anon_insert_attachments ON laborconsult.qa_attachments;
CREATE POLICY anon_insert_attachments ON laborconsult.qa_attachments
    FOR INSERT TO anon WITH CHECK (true);
DROP POLICY IF EXISTS anon_select_attachments ON laborconsult.qa_attachments;
CREATE POLICY anon_select_attachments ON laborconsult.qa_attachments
    FOR SELECT TO anon USING (true);

-- 법령 캐시는 공개 조문이라 민감정보가 없다. UPDATE 까지 열어야 갱신이 된다.
-- (구 supabase_fix_missing_schema.sql 은 RLS 만 켜고 정책을 안 줘서 "L2 캐시
--  저장 실패" 로그가 나면 DISABLE 하라는 미결 주석을 남겼다 — 여기서 닫는다.)
DROP POLICY IF EXISTS anon_select_law_cache ON laborconsult.law_article_cache;
CREATE POLICY anon_select_law_cache ON laborconsult.law_article_cache
    FOR SELECT TO anon USING (true);
DROP POLICY IF EXISTS anon_insert_law_cache ON laborconsult.law_article_cache;
CREATE POLICY anon_insert_law_cache ON laborconsult.law_article_cache
    FOR INSERT TO anon WITH CHECK (true);
DROP POLICY IF EXISTS anon_update_law_cache ON laborconsult.law_article_cache;
CREATE POLICY anon_update_law_cache ON laborconsult.law_article_cache
    FOR UPDATE TO anon USING (true);


-- ── 5-1. 테이블 권한 ───────────────────────────────────────────────────────
--
-- ⚠️ **커스텀 스키마에는 Supabase 기본 권한이 자동 부여되지 않는다.**
--    public 스키마는 default privileges 가 새 테이블에 anon/authenticated 권한을
--    자동으로 주지만, laborconsult 처럼 직접 만든 스키마는 그 대상이 아니다.
--    GRANT USAGE ON SCHEMA 만으로는 부족하다 — 2026-08-13 적용 검증에서 qa_* 와
--    law_article_cache 가 전부 `permission denied` 로 나왔다.
--
--    RLS 정책은 "어느 **행**을 볼 수 있나"이고 GRANT 는 "테이블에 접근할 수 있나"다.
--    계층이 달라 둘 다 있어야 동작한다. 정책만 만들고 GRANT 를 빠뜨리면
--    정책이 무의미해진다(접근 자체가 막히므로).
--
--    DELETE 는 어디에도 주지 않는다 — 하드 삭제는 purge(postgres 역할) 전용.

GRANT SELECT, INSERT, UPDATE ON laborconsult.qa_sessions       TO anon;
GRANT SELECT, INSERT         ON laborconsult.qa_conversations  TO anon;
GRANT SELECT, INSERT         ON laborconsult.qa_attachments    TO anon;
GRANT SELECT, INSERT, UPDATE ON laborconsult.law_article_cache TO anon;


-- ── 6. updated_at 자동 갱신 ────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION laborconsult.update_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = laborconsult, pg_temp
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS tr_qa_sessions_updated ON laborconsult.qa_sessions;
CREATE TRIGGER tr_qa_sessions_updated
    BEFORE UPDATE ON laborconsult.qa_sessions
    FOR EACH ROW EXECUTE FUNCTION laborconsult.update_updated_at();


-- ── 7. Storage 버킷 ────────────────────────────────────────────────────────
-- storage 스키마는 Supabase 소유라 laborconsult 스키마 밖이다. 버킷 이름으로만
-- 격리되므로 정책 이름에 접두사를 붙여 다른 앱과 충돌하지 않게 한다.
--
-- public = false: 상담 첨부에는 급여명세서·근로계약서 등 개인정보가 담긴다.
-- 영구 공개 URL 을 만들지 않고 1시간 만료 signed URL 로만 연다.
INSERT INTO storage.buckets (id, name, public)
VALUES ('chat-attachments', 'chat-attachments', false)
ON CONFLICT (id) DO UPDATE SET public = false;

DROP POLICY IF EXISTS laborconsult_attachments_insert ON storage.objects;
CREATE POLICY laborconsult_attachments_insert ON storage.objects
    FOR INSERT TO anon WITH CHECK (bucket_id = 'chat-attachments');

-- SELECT 정책은 signed URL 발급에 필요하다. 버킷이 비공개라 정책이 있어도
-- 키 없이 객체에 직접 접근할 수는 없다.
DROP POLICY IF EXISTS laborconsult_attachments_select ON storage.objects;
CREATE POLICY laborconsult_attachments_select ON storage.objects
    FOR SELECT TO anon USING (bucket_id = 'chat-attachments');


-- ═══════════════════════════════════════════════════════════════════════════
-- 검증 — 실행 후 눈으로 확인할 것
-- ═══════════════════════════════════════════════════════════════════════════

-- ① 테이블 4개 (qa_sessions · qa_conversations · qa_attachments · law_article_cache)
SELECT tablename FROM pg_tables WHERE schemaname = 'laborconsult' ORDER BY tablename;

-- ② 정책 12개, 전부 anon. DELETE 가 나오면 잘못된 상태다.
SELECT tablename, policyname, cmd, roles
  FROM pg_policies WHERE schemaname = 'laborconsult' ORDER BY tablename, cmd;

-- ③ 버킷이 비공개인지
SELECT id, public FROM storage.buckets WHERE id = 'chat-attachments';

-- ④ anon 테이블 권한 — 4개 테이블 전부 나와야 한다. 비어 있으면 5-1 이 안 걸린 것이고,
--    그 상태에서는 RLS 정책이 있어도 `permission denied` 로 전부 막힌다.
SELECT table_name, string_agg(DISTINCT privilege_type, ', ' ORDER BY privilege_type) AS privs
  FROM information_schema.role_table_grants
 WHERE table_schema = 'laborconsult' AND grantee = 'anon'
 GROUP BY table_name ORDER BY table_name;
