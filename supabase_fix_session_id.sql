-- ⚠️ [2026-08-13] 이 파일은 **신규 환경에 불필요**하다. 내용이 최종 상태 DDL 본문에
--    흡수됐다(supabase_schema.sql). 패치를 따로 두면 프로젝트를 옮길 때 base 만
--    적용하고 놓치게 되며, 실제로 그렇게 해서 session_data·law_article_cache 가
--    빠진 채 프로덕션이 돌았다. 이력 참조용으로만 남긴다.
--    현재 적용 순서: supabase_schema.sql → _abuse_guard → _board_posts → _retention_purge

-- session_id 타입을 UUID → TEXT로 변경 (기존 앱의 12자 hex ID와 호환)
-- 전체를 단일 트랜잭션으로 실행 — 중간 실패 시 전량 롤백되어 부분 마이그레이션 방지.

BEGIN;

-- 1. FK 제약 조건 삭제
ALTER TABLE qa_conversations DROP CONSTRAINT IF EXISTS qa_conversations_session_id_fkey;

-- 2. qa_sessions.id를 TEXT로 변경
ALTER TABLE qa_sessions ALTER COLUMN id TYPE TEXT USING id::TEXT;

-- 3. qa_conversations.session_id를 TEXT로 변경
ALTER TABLE qa_conversations ALTER COLUMN session_id TYPE TEXT USING session_id::TEXT;

-- 4. FK 제약 조건 재생성
ALTER TABLE qa_conversations
    ADD CONSTRAINT qa_conversations_session_id_fkey
    FOREIGN KEY (session_id) REFERENCES qa_sessions(id) ON DELETE CASCADE;

COMMIT;
