-- ─────────────────────────────────────────────────────────────────────────────
-- 보유기간 경과 데이터 자동 파기 (개인정보처리방침 제5항 이행 수단)
--
-- 배경: public/privacy.html 제5항이 "수집일로부터 1년, 경과 시 자동 파기"를 약속한다.
--       코드에는 파기 로직이 없으므로 이 스크립트를 적용해야 방침이 실제로 지켜진다.
--
-- 실행 위치: Supabase 대시보드 → 왼쪽 사이드바 **SQL Editor** → New query
--            (psql 로 접속해도 동일. Database → Connect 의 connection string 사용)
--
-- ⚠️ 이 파일은 데이터를 영구 삭제한다. 반드시 아래 순서로 진행할 것.
--    0) §0 스토리지 파기 큐 생성 (최초 1회)
--    1) §1 함수 생성 (이 시점에는 아무것도 지워지지 않는다)
--    2) §2 미리보기로 삭제 대상 건수를 눈으로 확인
--    3) §3 수동 1회 실행으로 결과 확인 — **반환된 7개 건수가 §2 미리보기와 일치해야 한다.**
--       전부 0이면 RLS 때문에 조용히 실패했을 수 있다(§3 주석 참조)
--    4) §4 pg_cron 등록
--    5) 별도로 `python3 purge_storage_orphans.py` 를 주기 실행 (아래 참조)
--
-- 전제: qa_attachments → qa_conversations → qa_sessions 가 ON DELETE CASCADE 로
--       연결되어 있다(supabase_schema.sql:15,31). 따라서 대화를 지우면 첨부 행도
--       함께 사라진다. 다만 **스토리지 객체는 CASCADE 대상이 아니다.**
--
-- ⚠️⚠️ 왜 SQL 로 파일을 지우지 않는가 (v1.2에서 구조 변경)
--    Supabase 는 `storage.objects` 에 대한 직접 DELETE 를 트리거로 차단한다:
--      ERROR 42501: Direct deletion from storage tables is not allowed.
--                   Use the Storage API instead. (PL/pgSQL function protect_delete())
--    그래서 이 함수는 **파일을 지우지 않고 경로를 `storage_purge_queue` 에 적재**만 한다.
--    실제 삭제는 Storage API 를 쓰는 `purge_storage_orphans.py` 가 큐를 비우며 수행한다.
--    적재는 대화 행이 CASCADE 로 사라지기 **전에** 이루어져야 경로를 잃지 않는다(§1 (1)번).
--
--    ‼️ 스크립트를 돌리지 않으면 DB 행만 지워지고 **파일은 스토리지에 남는다.**
--       개인정보처리방침 제5항을 실제로 이행하려면 두 축이 모두 돌아야 한다.
-- ─────────────────────────────────────────────────────────────────────────────


-- ═══ §0. 스토리지 파기 큐 (최초 1회) ═════════════════════════════════════════

CREATE TABLE IF NOT EXISTS storage_purge_queue (
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
    ON storage_purge_queue (queued_at) WHERE deleted_at IS NULL;

-- 다른 남용 가드 테이블과 동일 관례 — RLS 켜고 정책은 부여하지 않는다.
-- 접근은 아래 SECURITY DEFINER RPC 로만 (supabase_abuse_guard.sql 관례).
ALTER TABLE storage_purge_queue ENABLE ROW LEVEL SECURITY;


-- 큐에서 처리할 항목을 가져온다 (스크립트용)
CREATE OR REPLACE FUNCTION storage_purge_claim(p_limit INT DEFAULT 100)
RETURNS TABLE (id BIGINT, bucket_id TEXT, object_path TEXT)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT q.id, q.bucket_id, q.object_path
    FROM storage_purge_queue q
    WHERE q.deleted_at IS NULL AND q.attempts < 5
    ORDER BY q.queued_at
    LIMIT p_limit;
$$;

-- 처리 결과를 기록한다 (성공이면 tombstone, 실패면 재시도 카운트)
CREATE OR REPLACE FUNCTION storage_purge_mark(
    p_id BIGINT, p_ok BOOLEAN, p_error TEXT DEFAULT NULL
) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    IF p_ok THEN
        UPDATE storage_purge_queue
        SET deleted_at = now(), last_error = NULL
        WHERE id = p_id;
    ELSE
        UPDATE storage_purge_queue
        SET attempts = attempts + 1, last_error = left(coalesce(p_error, ''), 300)
        WHERE id = p_id;
    END IF;
END;
$$;

-- anon/authenticated 에게는 실행 권한을 주지 않는다. purge_storage_orphans.py는
-- service_role 키로 호출하므로(anon은 storage.objects DELETE 정책이 없어 파일을
-- 못 지운다 — 상단 §0 안내 참조) 이 RPC들에 별도 권한이 필요 없다. service_role은
-- 항상 모든 권한을 가지므로 REVOKE 대상이 아니다. 열어 두면 anon이 큐를 읽거나
-- storage_purge_mark로 상태를 조작할 수 있는 불필요한 공격 표면이 된다.
REVOKE ALL ON FUNCTION storage_purge_claim(INT) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION storage_purge_mark(BIGINT, BOOLEAN, TEXT) FROM PUBLIC, anon, authenticated;


-- ═══ §1. 파기 함수 ═══════════════════════════════════════════════════════════

-- ⚠️ 반환 컬럼이 바뀌었으므로 CREATE OR REPLACE 로는 교체되지 않는다.
--    이전 버전을 적용한 배포는 아래 DROP 두 줄을 먼저 실행할 것.
--    기존 pg_cron 작업(`purge_expired_data(365)`)은 새 시그니처에도 그대로 해소된다.
DROP FUNCTION IF EXISTS purge_expired_data(INT);
DROP FUNCTION IF EXISTS purge_expired_data(INT, INT);

CREATE OR REPLACE FUNCTION purge_expired_data(
    retention_days       INT DEFAULT 365,   -- 상담·첨부·게시글 (개인정보처리방침 제5항)
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
SET search_path = public, storage
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
    --     Supabase 가 storage.objects 직접 DELETE 를 트리거로 막으므로(protect_delete)
    --     여기서는 지우지 않는다. 실제 삭제는 purge_storage_orphans.py 가 Storage API 로 한다.
    --     (2)에서 대화를 지우면 qa_attachments 가 CASCADE 로 사라져 경로를 잃으므로
    --     **반드시 이 단계가 먼저**여야 한다.
    WITH expired AS (
        SELECT a.storage_path
        FROM qa_attachments a
        JOIN qa_conversations c ON c.id = a.conversation_id
        WHERE c.created_at < cutoff
    ), queued AS (
        INSERT INTO storage_purge_queue (bucket_id, object_path)
        SELECT 'chat-attachments', e.storage_path FROM expired e
        ON CONFLICT (bucket_id, object_path) DO NOTHING
        RETURNING 1
    )
    SELECT count(*) INTO n_obj FROM queued;

    -- (2) 만료 대화 삭제 → qa_attachments 행은 CASCADE로 함께 삭제됨
    WITH removed AS (
        DELETE FROM qa_conversations WHERE created_at < cutoff RETURNING 1
    )
    SELECT count(*) INTO n_conv FROM removed;

    -- (3) 남은 대화가 없고 마지막 활동이 만료된 세션 삭제
    WITH removed AS (
        DELETE FROM qa_sessions s
        WHERE s.updated_at < cutoff
          AND NOT EXISTS (SELECT 1 FROM qa_conversations c WHERE c.session_id = s.id)
        RETURNING 1
    )
    SELECT count(*) INTO n_sess FROM removed;

    -- (4) 게시판 글 — board_posts 는 스키마 파일이 없어 수동 생성된 테이블이므로
    --     존재할 때만 처리한다(없어도 이 함수가 실패하지 않도록).
    IF to_regclass('public.board_posts') IS NOT NULL THEN
        EXECUTE format(
            'WITH removed AS (DELETE FROM board_posts WHERE created_at < %L RETURNING 1)
             SELECT count(*) FROM removed', cutoff
        ) INTO n_posts;
    END IF;

    -- (5) 남용 탐지 기록 — abuse_events 는 RPC 어디에도 삭제 경로가 없어
    --     방치하면 영구 누적된다. detail 에 사용자 질문 프리뷰 120자가 들어가므로
    --     (supabase_abuse_guard.sql:117) 보안 로그 보존기간을 넘기면 지운다.
    WITH removed AS (
        DELETE FROM abuse_events WHERE created_at < abuse_cutoff RETURNING 1
    )
    SELECT count(*) INTO n_abuse FROM removed;

    -- (6) 일일 쿼터 — chat_guard_check RPC 는 '같은 subject_key 가 다음 날 다시
    --     요청할 때'만 지운다(supabase_abuse_guard.sql:88). 재방문하지 않는 IP의
    --     행이 영구 잔존하므로 지난 날짜를 일괄 정리한다.
    WITH removed AS (
        DELETE FROM chat_quota WHERE day < today_kst RETURNING 1
    )
    SELECT count(*) INTO n_quota FROM removed;

    -- (7) 만료된 차단 — 동일한 이유(supabase_abuse_guard.sql:79)
    WITH removed AS (
        DELETE FROM block_list WHERE until_ts <= now() RETURNING 1
    )
    SELECT count(*) INTO n_block FROM removed;

    RETURN QUERY SELECT n_obj, n_conv, n_sess, n_posts, n_abuse, n_quota, n_block;
END;
$$;

REVOKE ALL ON FUNCTION purge_expired_data(INT, INT) FROM PUBLIC, anon, authenticated;

COMMENT ON FUNCTION purge_expired_data(INT, INT) IS
    '개인정보처리방침 제5항 이행 — 상담·첨부·게시글 365일 / 남용 탐지 기록 90일 경과분 파기. pg_cron 전용.';


-- ═══ §2. 미리보기 (삭제 없음 — 반드시 먼저 실행) ══════════════════════════════

-- 아래 블록만 따로 실행해 삭제 예정 건수를 확인한다.
/*
WITH cutoff AS (SELECT now() - INTERVAL '365 days' AS t)
SELECT '스토리지 객체(큐 적재 예정)' AS 대상,
       count(*) AS 건수
FROM qa_attachments a
JOIN qa_conversations c ON c.id = a.conversation_id, cutoff
WHERE c.created_at < cutoff.t
UNION ALL
SELECT '대화', count(*) FROM qa_conversations, cutoff WHERE created_at < cutoff.t
UNION ALL
SELECT '세션', count(*) FROM qa_sessions s, cutoff
 WHERE s.updated_at < cutoff.t
   AND NOT EXISTS (SELECT 1 FROM qa_conversations c WHERE c.session_id = s.id)
UNION ALL
SELECT '남용 이벤트(90일 초과)', count(*) FROM abuse_events
 WHERE created_at < now() - INTERVAL '90 days'
UNION ALL
SELECT '지난 일일쿼터', count(*) FROM chat_quota
 WHERE day < to_char(now() AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD')
UNION ALL
SELECT '만료 차단', count(*) FROM block_list WHERE until_ts <= now();
*/


-- ═══ §3. 수동 1회 실행 ═══════════════════════════════════════════════════════

-- 미리보기 건수와 결과가 일치하는지 확인한다.
-- ⚠️ 주석을 유지할 것 — 이 파일 전체를 한 번에 실행해도 삭제가 일어나지 않도록 막아 둔 것이다.
--    아래 한 줄만 따로 복사해 SQL Editor 에서 실행한다.
/*
SELECT * FROM purge_expired_data(365, 90);
*/

-- 반환 예시
--  storage_objects_queued | conversations_deleted | sessions_deleted | board_posts_deleted | abuse_events_deleted | chat_quota_deleted | block_list_deleted
--  -----------------------+-----------------------+------------------+---------------------+----------------------+--------------------+--------------------
--                       3 |                     5 |                2 |                   0 |                   12 |                  8 |                  1
--
-- ⚠️ 첫 컬럼은 '삭제'가 아니라 '큐 적재'다. 파일을 실제로 지우려면 이어서
--    `python3 purge_storage_orphans.py` 를 실행해야 한다.
--
-- ⚠️ 양성 검증 — 7개가 **전부 0인데 §2 미리보기에는 건수가 있었다면** 실패로 볼 것.
--    abuse_events·chat_quota·block_list 는 RLS ON + 정책 0개다. 이 함수의 소유자가
--    테이블 소유자가 아니면 SECURITY DEFINER 라도 RLS 에 막혀 **에러 없이 0건**으로 끝난다
--    (chatbot-security 의 fail-open 과 같은 함정).
--    그 경우 소유자를 맞춘 뒤 재실행할 것:
--      ALTER FUNCTION purge_expired_data(INT, INT) OWNER TO postgres;
--
-- 참고: 데이터가 아직 보유기간을 넘지 않았다면 전부 0이 정상이다. 반드시 §2 와 대조할 것.


-- ═══ §4. pg_cron 등록 (매일 새벽 4시 KST = 19:00 UTC) ════════════════════════

-- Supabase 대시보드 → Database → Extensions 에서 pg_cron 을 먼저 활성화할 것.
/*
CREATE EXTENSION IF NOT EXISTS pg_cron;

SELECT cron.schedule(
    'purge-expired-data',
    '0 19 * * *',
    $cron$ SELECT purge_expired_data(365, 90); $cron$
);

-- 등록 확인
SELECT jobid, jobname, schedule, active FROM cron.job WHERE jobname = 'purge-expired-data';

-- 실행 이력 확인 (며칠 뒤)
SELECT status, return_message, start_time
FROM cron.job_run_details
WHERE jobid = (SELECT jobid FROM cron.job WHERE jobname = 'purge-expired-data')
ORDER BY start_time DESC LIMIT 10;
*/


-- ═══ §5. 스토리지 큐 현황 ════════════════════════════════════════════════════
--
-- ⚠️ "실패포기"(attempts >= 5) 항목은 storage_purge_claim이 더 이상 반환하지
--    않으므로 영원히 재시도되지 않고 조용히 남는다. 이 값이 0보다 크면 개인정보
--    처리방침 제5항의 파기 약속이 그 항목에 한해 지켜지지 않는 상태다. 정기
--    실행(예: purge_storage_orphans.py 실행 직후)마다 이 쿼리를 함께 확인하거나,
--    0보다 클 때 알리는 별도 모니터링을 운영 절차에 둘 것.
/*
SELECT
    count(*) FILTER (WHERE deleted_at IS NULL AND attempts < 5) AS 대기,
    count(*) FILTER (WHERE deleted_at IS NOT NULL)              AS 삭제완료,
    count(*) FILTER (WHERE deleted_at IS NULL AND attempts >= 5) AS 실패포기
FROM storage_purge_queue;

-- 실패 항목 원인 확인
SELECT object_path, attempts, last_error, queued_at
FROM storage_purge_queue
WHERE deleted_at IS NULL AND attempts > 0
ORDER BY queued_at LIMIT 20;
*/


-- ═══ 되돌리기 ════════════════════════════════════════════════════════════════
/*
SELECT cron.unschedule('purge-expired-data');
DROP FUNCTION IF EXISTS purge_expired_data(INT, INT);
DROP FUNCTION IF EXISTS storage_purge_claim(INT);
DROP FUNCTION IF EXISTS storage_purge_mark(BIGINT, BOOLEAN, TEXT);
-- 큐 테이블은 감사 기록이므로 기본적으로 남긴다. 정말 지우려면:
-- DROP TABLE IF EXISTS storage_purge_queue;
*/
