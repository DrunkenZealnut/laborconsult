-- ============================================================================
-- laborconsult — 사용자 직접 작성 질문게시판 (3/4)
--
-- 설계: docs/02-design/features/board-write-security.design.md:138-150 (원형)
--       docs/archive/2026-08/supabase-schema-migration/supabase-schema-migration.design.md §4
-- 선행: supabase_schema.sql (스키마 생성)
--
-- ⚠️ 이 파일이 board_posts 스키마의 단일 출처다. 컬럼을 늘리거나 줄일 때
--    app/core/storage.py::BOARD_POST_COLUMNS 를 반드시 함께 고칠 것 —
--    test_offline_units.py 가 두 소스를 대조해 고정한다.
--
-- ⚠️ **이 테이블은 반드시 laborconsult 스키마에 있어야 한다.** public 스키마에
--    같은 이름의 테이블이 다른 앱 것으로 존재할 수 있다 — 2026-08-13 에 실제로
--    그랬고(구 단위 권한·승인 사용자 모델), 우리 코드가 그것을 자기 것으로
--    오인해 컬럼을 추가하고 정책을 덮어쓸 뻔했다. 스키마 한정이 유일한 방어다.
--
-- 멱등: 부분 적용 상태에서 다시 실행해도 안전하다. 실패하면 그냥 재실행할 것.
-- ============================================================================

-- ── 1. 테이블 · 컬럼 ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS laborconsult.board_posts (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY
);

-- NOT NULL 을 인라인으로 붙이지 않는 이유: ADD COLUMN ... NOT NULL 은 기존 행이
-- 있으면 실패한다. 부분 적용 상태에서의 재실행을 전제하므로 분리한다(아래 3번).
ALTER TABLE laborconsult.board_posts ADD COLUMN IF NOT EXISTS nickname      TEXT;
ALTER TABLE laborconsult.board_posts ADD COLUMN IF NOT EXISTS password_hash TEXT;
ALTER TABLE laborconsult.board_posts ADD COLUMN IF NOT EXISTS category      TEXT DEFAULT '일반상담';
ALTER TABLE laborconsult.board_posts ADD COLUMN IF NOT EXISTS question_text TEXT;
ALTER TABLE laborconsult.board_posts ADD COLUMN IF NOT EXISTS status        TEXT DEFAULT 'active';
ALTER TABLE laborconsult.board_posts ADD COLUMN IF NOT EXISTS ip_hash       TEXT;
ALTER TABLE laborconsult.board_posts ADD COLUMN IF NOT EXISTS created_at    TIMESTAMPTZ DEFAULT NOW();

-- ── 2. 제약 ────────────────────────────────────────────────────────────────
--
-- ⚠️ 경계값은 api/index.py::board_post_write 의 검증(:851, :860)과 **같은 값**이어야
--    한다. 어긋나면 앱이 통과시킨 입력을 DB 가 거절해 사용자에게 500 이 나간다.
--    닉네임 2~10자 / 질문 10~2000자.
--
-- ADD CONSTRAINT 는 IF NOT EXISTS 를 지원하지 않아 이름으로 멱등 처리한다.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'board_posts_nickname_len') THEN
        ALTER TABLE laborconsult.board_posts ADD CONSTRAINT board_posts_nickname_len
            CHECK (char_length(nickname) BETWEEN 2 AND 10);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'board_posts_question_len') THEN
        ALTER TABLE laborconsult.board_posts ADD CONSTRAINT board_posts_question_len
            CHECK (char_length(question_text) BETWEEN 10 AND 2000);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'board_posts_status_enum') THEN
        ALTER TABLE laborconsult.board_posts ADD CONSTRAINT board_posts_status_enum
            CHECK (status IN ('active', 'deleted'));
    END IF;
END $$;

-- ── 3. NOT NULL · 기본값 ───────────────────────────────────────────────────
--
-- ⚠️ 기존 행에 NULL 이 있으면 실패한다. 그 경우 해당 행을 먼저 정리하거나 채운 뒤
--    재실행할 것. SET NOT NULL 은 이미 NOT NULL 이어도 오류가 아니므로 멱등이다.
ALTER TABLE laborconsult.board_posts ALTER COLUMN nickname      SET NOT NULL;
ALTER TABLE laborconsult.board_posts ALTER COLUMN password_hash SET NOT NULL;
ALTER TABLE laborconsult.board_posts ALTER COLUMN question_text SET NOT NULL;
ALTER TABLE laborconsult.board_posts ALTER COLUMN status        SET DEFAULT 'active';
ALTER TABLE laborconsult.board_posts ALTER COLUMN category      SET DEFAULT '일반상담';

-- ── 4. 인덱스 ──────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_board_posts_active_created
    ON laborconsult.board_posts(created_at DESC) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_board_posts_category
    ON laborconsult.board_posts(category) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_board_posts_ip_hash
    ON laborconsult.board_posts(ip_hash, created_at DESC);

-- ── 5. RLS 정책 ────────────────────────────────────────────────────────────
--
-- ⚠️ 정책 이름에 큰따옴표를 쓰지 않는다 — SQL Editor 붙여넣기에서 스마트 따옴표
--    (U+201C)로 바뀌면 `syntax error at or near "Allow"` 로 죽는다(실제 발생).
--
-- ⚠️ **이름을 모르는 기존 정책을 일괄 삭제하는 관용구를 쓰지 않는다.** 직전
--    사이클에서 그 방식을 검토했다가, 남의 스키마에 적용하면 그 앱의 인가 모델을
--    통째로 날린다는 것을 실행 직전에 발견했다. 스키마 전용이면 이름 충돌이
--    없으므로 내 이름만 DROP 하면 충분하다.

ALTER TABLE laborconsult.board_posts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS anon_select_posts ON laborconsult.board_posts;
CREATE POLICY anon_select_posts ON laborconsult.board_posts
    FOR SELECT TO anon USING (true);

DROP POLICY IF EXISTS anon_insert_posts ON laborconsult.board_posts;
CREATE POLICY anon_insert_posts ON laborconsult.board_posts
    FOR INSERT TO anon WITH CHECK (true);

-- soft delete 전용 — active → deleted 단방향만 허용한다.
-- USING (true) 로 열면 누구든 question_text 를 고치거나 삭제된 글을 되살릴 수 있다.
-- 비밀번호(bcrypt) 검사는 앱 단이라 RLS 로는 막지 못한다.
DROP POLICY IF EXISTS anon_soft_delete_posts ON laborconsult.board_posts;
CREATE POLICY anon_soft_delete_posts ON laborconsult.board_posts
    FOR UPDATE TO anon
    USING (status = 'active')
    WITH CHECK (status = 'deleted');

-- ⚠️ DELETE 정책은 부여하지 않는다. 하드 삭제는 보존기간 purge
--    (laborconsult.purge_expired_data, postgres 역할)만 수행한다.

-- ── 6. 컬럼 단위 권한 ──────────────────────────────────────────────────────
--
-- RLS 는 행 단위라 "status 컬럼만 수정 허용"을 표현할 수 없다. GRANT 로 막는다.
-- 5번의 UPDATE 정책과 함께 걸려야 앱의 유일한 UPDATE(status='deleted')만 통과한다.
--
-- ⚠️ Supabase 기본 설정의 `GRANT ALL ON ALL TABLES IN SCHEMA ... TO anon` 을
--    누군가 다시 실행하면 이 제한이 **조용히 원복된다.** 이 파일을 재실행하면
--    복구되며, 아래 §검증 ③이 감지 수단이다.
REVOKE UPDATE ON laborconsult.board_posts FROM anon;
GRANT  UPDATE (status) ON laborconsult.board_posts TO anon;

-- SELECT/INSERT 는 정책과 함께 테이블 권한도 있어야 한다.
GRANT SELECT, INSERT ON laborconsult.board_posts TO anon;


-- ═══════════════════════════════════════════════════════════════════════════
-- 검증 — 실행 후 아래 3개를 눈으로 확인할 것
-- ═══════════════════════════════════════════════════════════════════════════

-- ① 컬럼 8개
--    id · nickname · password_hash · category · question_text · status ·
--    ip_hash · created_at
SELECT column_name, data_type, is_nullable, column_default
  FROM information_schema.columns
 WHERE table_schema = 'laborconsult' AND table_name = 'board_posts'
 ORDER BY ordinal_position;

-- ② 정책 3개 (SELECT · INSERT · UPDATE). DELETE 가 나오면 잘못된 상태다.
SELECT policyname, cmd, qual, with_check
  FROM pg_policies
 WHERE schemaname = 'laborconsult' AND tablename = 'board_posts'
 ORDER BY cmd;

-- ③ anon 의 UPDATE 권한이 status 한 컬럼에만 있어야 한다.
--    여러 컬럼이 나오면 6번의 REVOKE/GRANT 가 원복된 상태다.
SELECT grantee, privilege_type, column_name
  FROM information_schema.column_privileges
 WHERE table_schema = 'laborconsult' AND table_name = 'board_posts'
   AND grantee = 'anon' AND privilege_type = 'UPDATE';
