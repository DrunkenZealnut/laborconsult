-- ─────────────────────────────────────────────────────────────────────────────
-- laborconsult — 보유기간 경과 데이터 자동 파기 (4/4)
--                (개인정보처리방침 제5항 이행 수단)
--
-- 설계: docs/02-design/features/supabase-schema-migration.design.md §4.6
-- 선행: supabase_schema.sql · supabase_abuse_guard.sql · supabase_board_posts.sql
--       (이 함수가 그 테이블들을 참조하므로 반드시 마지막에 적용)
--
-- 배경: public/privacy.html 제5항이 "수집일로부터 1년, 경과 시 자동 파기"를 약속한다.
--       코드에는 파기 로직이 없으므로 이 스크립트를 적용해야 방침이 실제로 지켜진다.
--
-- 실행 위치: Supabase 대시보드 → SQL Editor → New query
--
-- ⚠️ 이 파일은 데이터를 영구 삭제한다. 반드시 아래 순서로 진행할 것.
--    0) §0 스토리지 파기 큐 생성 (최초 1회)
--    1) §1 함수 생성 (이 시점에는 아무것도 지워지지 않는다)
--    2) §2 미리보기로 삭제 대상 건수를 눈으로 확인
--    3) §3 수동 1회 실행 — **반환된 7개 건수가 §2 미리보기와 일치해야 한다.**
--    4) §4 pg_cron 등록
--    5) 별도로 `python3 purge_storage_orphans.py` 를 주기 실행
--
-- ⚠️⚠️ **스키마 한정이 이 파일의 생명이다.**
--    구 버전은 `SET search_path = public, storage` 에 `DELETE FROM board_posts` 를
--    스키마 없이 적었다. 그 결과 이 함수는 **다른 앱의 board_posts 를 지우도록**
--    작성돼 있었다(2026-08-13 발견 — 같은 프로젝트 public 스키마에 구 단위 권한
--    모델을 쓰는 동명 테이블이 있었다. pg_cron 미활성이라 실행된 적은 없었다).
--    SECURITY DEFINER 함수는 정의자 권한으로 돌고 미지정 참조는 search_path 로
--    해석되므로, 이 조합은 남의 데이터를 지우는 가장 조용한 경로다.
--    → search_path 에서 public 을 제거하고 모든 참조를 laborconsult. 로 한정한다.
--
-- ⚠️ 왜 SQL 로 파일을 지우지 않는가
--    Supabase 는 `storage.objects` 직접 DELETE 를 트리거로 차단한다:
--      ERROR 42501: Direct deletion from storage tables is not allowed.
--    그래서 이 함수는 **경로를 큐에 적재만** 하고, 실제 삭제는 Storage API 를 쓰는
--    `purge_storage_orphans.py` 가 수행한다. 적재는 대화 행이 CASCADE 로 사라지기
--    **전에** 이루어져야 경로를 잃지 않는다(§1 (1)번).
--
--    ‼️ 스크립트를 돌리지 않으면 DB 행만 지워지고 **파일은 스토리지에 남는다.**
--       방침 제5항을 실제로 이행하려면 두 축이 모두 돌아야 한다.
-- ─────────────────────────────────────────────────────────────────────────────


-- ═══ §0. 스토리지 파기 큐 (최초 1회) ═════════════════════════════════════════

CREATE TABLE IF NOT EXISTS laborconsult.storage_purge_queue (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    bucket_id   text NOT NULL,
    object_path text NOT NULL,
    queued_at   timestamptz NOT NULL DEFAULT now(),
    deleted_at  timestamptz,              -- NULL 이면 아직 미삭제
    attempts    integer NOT NULL DEFAULT 0,
    last_error  text,
    UNIQUE (bucket_id, object_path)
);

CREATE INDEX IF NOT EXISTS idx_storage_purge_pending
    ON laborconsult.storage_purge_queue (queued_at) WHERE deleted_at IS NULL;

-- 남용 가드 테이블과 동일 관례 — RLS 켜고 정책은 부여하지 않는다.
-- 접근은 아래 SECURITY DEFINER RPC 로만.
ALTER TABLE laborconsult.storage_purge_queue ENABLE ROW LEVEL SECURITY;


-- 큐에서 처리할 항목을 가져온다 (스크립트용)
CREATE OR REPLACE FUNCTION laborconsult.storage_purge_claim(p_limit INT DEFAULT 100)
RETURNS TABLE (id BIGINT, bucket_id TEXT, object_path TEXT)
LANGUAGE sql
SECURITY DEFINER
SET search_path = laborconsult, pg_temp
AS $$
    SELECT q.id, q.bucket_id, q.object_path
    FROM laborconsult.storage_purge_queue q
    WHERE q.deleted_at IS NULL AND q.attempts < 5
    ORDER BY q.queued_at
    LIMIT p_limit;
$$;

-- 처리 결과를 기록한다 (성공이면 tombstone, 실패면 재시도 카운트)
CREATE OR REPLACE FUNCTION laborconsult.storage_purge_mark(
    p_id BIGINT, p_ok BOOLEAN, p_error TEXT DEFAULT NULL
) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = laborconsult, pg_temp
AS $$
BEGIN
    IF p_ok THEN
        UPDATE laborconsult.storage_purge_queue
        SET deleted_at = now(), last_error = NULL
        WHERE id = p_id;
    ELSE
        UPDATE laborconsult.storage_purge_queue
        SET attempts = attempts + 1, last_error = left(coalesce(p_error, ''), 300)
        WHERE id = p_id;
    END IF;
END;
$$;

-- anon/authenticated 에게는 실행 권한을 주지 않는다. purge_storage_orphans.py 는
-- service_role 키로 호출한다(anon 은 storage.objects DELETE 정책이 없어 파일을
-- 못 지운다). 열어 두면 anon 이 큐를 읽거나 상태를 조작할 수 있는 공격 표면이 된다.
REVOKE ALL ON FUNCTION laborconsult.storage_purge_claim(INT)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION laborconsult.storage_purge_mark(BIGINT, BOOLEAN, TEXT)
    FROM PUBLIC, anon, authenticated;


-- ═══ §1. 파기 함수 ═══════════════════════════════════════════════════════════

-- 반환 컬럼이 바뀌면 CREATE OR REPLACE 로 교체되지 않으므로 먼저 DROP 한다.
DROP FUNCTION IF EXISTS laborconsult.purge_expired_data(INT);
DROP FUNCTION IF EXISTS laborconsult.purge_expired_data(INT, INT);

CREATE OR REPLACE FUNCTION laborconsult.purge_expired_data(
    retention_days       INT DEFAULT 365,   -- 상담·첨부·게시글 (방침 제5항)
    abuse_retention_days INT DEFAULT 90     -- 남용 탐지 기록 (보안 로그, 더 짧게)
)
RETURNS TABLE (
    storage_objects_queued  BIGINT,   -- 파일 삭제는 purge_storage_orphans.py 가 수행
    conversations_deleted   BIGINT,
    sessions_deleted        BIGINT,
    board_posts_deleted     BIGINT,
    abuse_events_deleted    BIGINT,
    chat_quota_deleted      BIGINT,
    block_list_deleted      BIGINT
)
LANGUAGE plpgsql
SECURITY DEFINER
-- ⚠️ public 을 넣지 않는다. 넣으면 미지정 참조가 다른 앱의 동명 테이블로 간다.
--    storage 도 넣지 않고 아래에서 `storage.` 로 명시한다 — search_path 의존은
--    같은 사고의 씨앗이다.
SET search_path = laborconsult, pg_temp
AS $$
DECLARE
    cutoff       TIMESTAMPTZ := now() - make_interval(days => retention_days);
    abuse_cutoff TIMESTAMPTZ := now() - make_interval(days => abuse_retention_days);
    -- chat_quota.day 는 앱이 KST 기준으로 계산해 넣는 'YYYY-MM-DD' 텍스트다.
    -- 같은 기준으로 비교해야 하루 밀리지 않는다.
    today_kst    TEXT := to_char(now() AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD');
    n_obj    BIGINT := 0;
    n_conv   BIGINT := 0;
    n_sess   BIGINT := 0;
    n_posts  BIGINT := 0;
    n_abuse  BIGINT := 0;
    n_quota  BIGINT := 0;
    n_block  BIGINT := 0;
BEGIN
    -- (1) 만료 대화에 딸린 스토리지 경로를 **큐에 적재**한다.
    --     (2)에서 대화를 지우면 qa_attachments 가 CASCADE 로 사라져 경로를 잃으므로
    --     **반드시 이 단계가 먼저**여야 한다.
    WITH expired AS (
        SELECT a.storage_path
        FROM laborconsult.qa_attachments a
        JOIN laborconsult.qa_conversations c ON c.id = a.conversation_id
        WHERE c.created_at < cutoff
    ), queued AS (
        INSERT INTO laborconsult.storage_purge_queue (bucket_id, object_path)
        SELECT 'chat-attachments', e.storage_path FROM expired e
        ON CONFLICT (bucket_id, object_path) DO NOTHING
        RETURNING 1
    )
    SELECT count(*) INTO n_obj FROM queued;

    -- (2) 만료 대화 삭제 → qa_attachments 행은 CASCADE 로 함께 삭제됨
    WITH removed AS (
        DELETE FROM laborconsult.qa_conversations WHERE created_at < cutoff RETURNING 1
    )
    SELECT count(*) INTO n_conv FROM removed;

    -- (3) 남은 대화가 없고 마지막 활동이 만료된 세션 삭제
    WITH removed AS (
        DELETE FROM laborconsult.qa_sessions s
        WHERE s.updated_at < cutoff
          AND NOT EXISTS (
              SELECT 1 FROM laborconsult.qa_conversations c WHERE c.session_id = s.id)
        RETURNING 1
    )
    SELECT count(*) INTO n_sess FROM removed;

    -- (4) 게시판 글.
    --     ⚠️ 구 버전의 `to_regclass('public.board_posts')` 가드를 **제거했다.**
    --        그 가드는 "스키마 파일이 없어 수동 생성된 테이블이라 없을 수도 있다"는
    --        전제에서 나왔는데, 이제 supabase_board_posts.sql 이 존재를 보장한다.
    --        없으면 조용히 0건을 반환하는 것보다 **실패하는 편이 옳다** —
    --        방침 이행이 안 되고 있다는 사실이 드러나야 한다.
    WITH removed AS (
        DELETE FROM laborconsult.board_posts WHERE created_at < cutoff RETURNING 1
    )
    SELECT count(*) INTO n_posts FROM removed;

    -- (5) 남용 탐지 기록 — detail 에 사용자 질문 프리뷰 120자가 들어가므로
    --     보안 로그 보존기간을 넘기면 지운다.
    WITH removed AS (
        DELETE FROM laborconsult.abuse_events WHERE created_at < abuse_cutoff RETURNING 1
    )
    SELECT count(*) INTO n_abuse FROM removed;

    -- (6) 일일 쿼터 — chat_guard_check 는 '같은 subject_key 가 다음 날 다시 요청할
    --     때'만 지운다. 재방문하지 않는 IP 의 행이 영구 잔존하므로 일괄 정리한다.
    WITH removed AS (
        DELETE FROM laborconsult.chat_quota WHERE day < today_kst RETURNING 1
    )
    SELECT count(*) INTO n_quota FROM removed;

    -- (7) 만료된 차단 — 동일한 이유
    WITH removed AS (
        DELETE FROM laborconsult.block_list WHERE until_ts <= now() RETURNING 1
    )
    SELECT count(*) INTO n_block FROM removed;

    RETURN QUERY SELECT n_obj, n_conv, n_sess, n_posts, n_abuse, n_quota, n_block;
END;
$$;

REVOKE ALL ON FUNCTION laborconsult.purge_expired_data(INT, INT)
    FROM PUBLIC, anon, authenticated;

COMMENT ON FUNCTION laborconsult.purge_expired_data(INT, INT) IS
    '개인정보처리방침 제5항 이행 — 상담·첨부·게시글 365일 / 남용 탐지 기록 90일 경과분 파기. pg_cron 전용.';


-- ═══ §2. 미리보기 — 지우기 전에 건수부터 확인 ════════════════════════════════

SELECT
    (SELECT count(*) FROM laborconsult.qa_conversations
      WHERE created_at < now() - interval '365 days')                AS 대화,
    (SELECT count(*) FROM laborconsult.board_posts
      WHERE created_at < now() - interval '365 days')                AS 게시글,
    (SELECT count(*) FROM laborconsult.abuse_events
      WHERE created_at < now() - interval '90 days')                 AS 남용기록,
    (SELECT count(*) FROM laborconsult.chat_quota
      WHERE day < to_char(now() AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD')) AS 쿼터,
    (SELECT count(*) FROM laborconsult.block_list
      WHERE until_ts <= now())                                       AS 만료차단;


-- ═══ §3. 수동 1회 실행 ═══════════════════════════════════════════════════════
--
-- ⚠️ 반환된 7개 건수를 §2 미리보기와 대조할 것. 미리보기에는 건수가 있는데
--    전부 0이면 조용히 실패한 것이다(권한·스키마 문제).
/*
SELECT * FROM laborconsult.purge_expired_data(365, 90);
*/


-- ═══ §4. pg_cron 등록 (매일 새벽 4시 KST = 19:00 UTC) ════════════════════════
--
-- Supabase 대시보드 → Database → Extensions 에서 pg_cron 을 먼저 활성화할 것.
--
-- ⚠️ **함수를 스키마 한정으로 부를 것.** cron 작업은 자체 search_path 로 돌기
--    때문에 `SELECT purge_expired_data(...)` 로 적으면 찾지 못하거나, 더 나쁘게는
--    public 의 동명 함수를 부른다.
/*
CREATE EXTENSION IF NOT EXISTS pg_cron;

SELECT cron.schedule(
    'laborconsult-purge-expired-data',
    '0 19 * * *',
    $cron$ SELECT laborconsult.purge_expired_data(365, 90); $cron$
);

-- 등록 확인
SELECT jobid, jobname, schedule, active FROM cron.job
 WHERE jobname = 'laborconsult-purge-expired-data';

-- 실행 이력 확인 (며칠 뒤)
SELECT status, return_message, start_time
FROM cron.job_run_details
WHERE jobid = (SELECT jobid FROM cron.job WHERE jobname = 'laborconsult-purge-expired-data')
ORDER BY start_time DESC LIMIT 10;
*/


-- ═══ §5. 스토리지 큐 현황 ════════════════════════════════════════════════════
--
-- ⚠️ "실패포기"(attempts >= 5) 항목은 storage_purge_claim 이 더 이상 반환하지
--    않으므로 영원히 재시도되지 않고 조용히 남는다. 이 값이 0보다 크면 방침
--    제5항의 파기 약속이 그 항목에 한해 지켜지지 않는 상태다.
/*
SELECT
    count(*) FILTER (WHERE deleted_at IS NULL AND attempts < 5) AS 대기,
    count(*) FILTER (WHERE deleted_at IS NULL AND attempts >= 5) AS 실패포기,
    count(*) FILTER (WHERE deleted_at IS NOT NULL)               AS 삭제완료
FROM laborconsult.storage_purge_queue;
*/


-- ═══ §6. 검증 ════════════════════════════════════════════════════════════════

-- 함수 4개가 laborconsult 스키마에 있고, search_path 에 public 이 없어야 한다.
SELECT p.proname, p.prosecdef AS security_definer, p.proconfig
  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname = 'laborconsult'
   AND p.proname IN ('purge_expired_data', 'storage_purge_claim', 'storage_purge_mark')
 ORDER BY p.proname;
