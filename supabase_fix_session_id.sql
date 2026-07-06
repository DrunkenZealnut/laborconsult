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
