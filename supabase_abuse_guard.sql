-- ============================================================================
-- 챗봇 남용 가드 스키마 (chatbot-security)
-- 설계: docs/02-design/features/chatbot-security.design.md §3.1
--
-- 실행: Supabase 대시보드 → SQL Editor에 붙여넣고 Run
--   전체를 한 번에 실행해도 되고, "Failed to fetch"가 나면 STEP 1~4를
--   하나씩 나눠 실행해도 결과는 같다(각 STEP은 독립적으로 재실행 가능).
--
-- 관련 파일
--   supabase_abuse_guard_verify.sql    배포 후 양성 검증 (필수)
--   supabase_abuse_guard_rollback.sql  되돌리기
--
-- ⚠️ 권한 설계 (중요)
--   SUPABASE_KEY는 anon 키이고 기존 테이블(qa_*)은 RLS + anon 정책으로 운영된다.
--   신규 테이블에 anon 정책을 부여하면 클라이언트가 block_list를 직접 삭제해
--   차단을 자가 해제하거나, abuse_events(IP 해시·질의 프리뷰)를 열람할 수 있다.
--   따라서 테이블은 RLS ENABLE + 정책 무부여(직접 접근 전면 차단)로 잠그고,
--   접근은 SECURITY DEFINER 함수로만 허용한다.
--
--   잔존 위험(수용): anon 키가 유출되면 abuse_summary/abuse_unblock을 직접
--   호출할 수 있다. 이는 기존 qa_* 테이블이 이미 anon SELECT를 허용하는 것과
--   동일 수준의 노출이며, 근본 해소는 service_role 키 도입(별도 사이클)이 필요하다.
-- ============================================================================


-- ════════════════════════════════════════════════════════════════════════════
-- STEP 1/4 — 테이블
-- ════════════════════════════════════════════════════════════════════════════

-- FR-03: 일일 쿼터 카운터 (Vercel 인스턴스 무관 총량 방어)
CREATE TABLE IF NOT EXISTS chat_quota (
    subject_key text NOT NULL,          -- 'ip:<sha256(ip)[:16]>'
    day         text NOT NULL,          -- 'YYYY-MM-DD' — KST 기준, 앱에서 계산해 전달
    count       integer NOT NULL DEFAULT 0,
    PRIMARY KEY (subject_key, day)
);

-- FR-11: 임시 자동 차단
CREATE TABLE IF NOT EXISTS block_list (
    subject_key text PRIMARY KEY,
    until_ts    timestamptz NOT NULL,
    reason      text,
    strikes     integer NOT NULL DEFAULT 0
);

-- FR-10: 남용 이벤트 (원문 쿼리 전문 저장 금지 — detail은 카테고리·점수·프리뷰만)
CREATE TABLE IF NOT EXISTS abuse_events (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at  timestamptz NOT NULL DEFAULT now(),
    event_type  text NOT NULL,          -- injection|scope|quota|length|leak
    subject_key text NOT NULL,
    session_id  text,
    detail      text,                   -- 전체 120자 이하
    mode        text                    -- monitor|block
);
CREATE INDEX IF NOT EXISTS idx_abuse_events_subject ON abuse_events (subject_key, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_abuse_events_created ON abuse_events (created_at DESC);

-- RLS 활성화 + 정책 미부여 → anon 직접 접근 불가 (RPC만 우회)
ALTER TABLE chat_quota   ENABLE ROW LEVEL SECURITY;
ALTER TABLE block_list   ENABLE ROW LEVEL SECURITY;
ALTER TABLE abuse_events ENABLE ROW LEVEL SECURITY;


-- ════════════════════════════════════════════════════════════════════════════
-- STEP 2/4 — 요청 경로 RPC (쿼터·차단 검사)
-- ════════════════════════════════════════════════════════════════════════════

-- FR-03/11: 차단 조회 + 쿼터 원자 증가를 1왕복으로 처리
CREATE OR REPLACE FUNCTION chat_guard_check(
    p_subject_key text, p_day text, p_daily_limit int
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    v_until timestamptz;
    v_count int;
BEGIN
    -- 만료된 차단 정리 후 활성 차단 조회
    DELETE FROM block_list WHERE subject_key = p_subject_key AND until_ts <= now();
    SELECT until_ts INTO v_until FROM block_list WHERE subject_key = p_subject_key;
    IF v_until IS NOT NULL THEN
        RETURN jsonb_build_object(
            'allowed', false, 'reason', 'blocked',
            'retry_after', GREATEST(0, EXTRACT(EPOCH FROM (v_until - now()))::int));
    END IF;

    -- 지난 날짜 행 정리(자기 키만) + 원자 증가
    DELETE FROM chat_quota WHERE subject_key = p_subject_key AND day < p_day;
    INSERT INTO chat_quota (subject_key, day, count) VALUES (p_subject_key, p_day, 1)
        ON CONFLICT (subject_key, day) DO UPDATE SET count = chat_quota.count + 1
        RETURNING count INTO v_count;

    IF v_count > p_daily_limit THEN
        RETURN jsonb_build_object('allowed', false, 'reason', 'quota', 'count', v_count);
    END IF;
    RETURN jsonb_build_object('allowed', true, 'count', v_count);
END $$;


-- ════════════════════════════════════════════════════════════════════════════
-- STEP 3/4 — 이벤트 기록·관리자 RPC
-- ════════════════════════════════════════════════════════════════════════════

-- FR-10/11: 이벤트 기록 + 자동 차단 판정 (위반 시에만 호출)
-- 윈도우 카운트와 strikes 원자 증가는 PostgREST로 표현 불가해 DB에 위임.
-- monitor 모드 이벤트는 기록만 되고 차단 판정에서 제외된다(관측 기간 보호).
CREATE OR REPLACE FUNCTION record_abuse_event(
    p_subject_key text, p_event_type text, p_session_id text, p_detail text, p_mode text,
    p_window_secs int, p_threshold int, p_block_minutes int
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    v_recent int;
    v_blocked boolean := false;
BEGIN
    INSERT INTO abuse_events (event_type, subject_key, session_id, detail, mode)
    VALUES (p_event_type, p_subject_key, p_session_id, left(p_detail, 120), p_mode);

    IF p_event_type IN ('injection', 'quota', 'length') AND p_mode = 'block' THEN
        SELECT count(*) INTO v_recent FROM abuse_events
        WHERE subject_key = p_subject_key
          AND created_at > now() - make_interval(secs => p_window_secs)
          AND event_type IN ('injection', 'quota', 'length')
          AND mode = 'block';
        IF v_recent >= p_threshold THEN
            INSERT INTO block_list (subject_key, until_ts, reason, strikes)
            VALUES (p_subject_key, now() + make_interval(mins => p_block_minutes),
                    p_event_type, 1)
            ON CONFLICT (subject_key) DO UPDATE
                SET until_ts = now() + make_interval(mins => p_block_minutes),
                    reason   = EXCLUDED.reason,
                    strikes  = block_list.strikes + 1;
            v_blocked := true;
        END IF;
    END IF;

    RETURN jsonb_build_object('recorded', true, 'blocked', v_blocked);
END $$;


-- FR-12: 관리자 현황 (admin JWT 검증은 앱 계층 require_admin이 수행)
CREATE OR REPLACE FUNCTION abuse_summary(p_days int DEFAULT 7, p_limit int DEFAULT 100)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
    RETURN jsonb_build_object(
        'counts', (SELECT coalesce(jsonb_object_agg(event_type, n), '{}'::jsonb) FROM (
            SELECT event_type, count(*) n FROM abuse_events
            WHERE created_at > now() - make_interval(days => p_days)
            GROUP BY event_type) t),
        'events', (SELECT coalesce(jsonb_agg(e), '[]'::jsonb) FROM (
            SELECT created_at, event_type, subject_key, session_id, detail, mode
            FROM abuse_events ORDER BY created_at DESC LIMIT p_limit) e),
        'blocked', (SELECT coalesce(jsonb_agg(b), '[]'::jsonb) FROM (
            SELECT subject_key, until_ts, reason, strikes FROM block_list
            WHERE until_ts > now() ORDER BY until_ts DESC) b));
END $$;


-- FR-12: 수동 차단 해제 (오탐 대응)
CREATE OR REPLACE FUNCTION abuse_unblock(p_subject_key text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
    DELETE FROM block_list WHERE subject_key = p_subject_key;
    RETURN jsonb_build_object('ok', true);
END $$;


-- ════════════════════════════════════════════════════════════════════════════
-- STEP 4/4 — 권한 (테이블은 잠그고 RPC만 개방)
-- ════════════════════════════════════════════════════════════════════════════

-- 테이블 권한 회수 — RLS와 별개 계층이라 둘 다 잠가야 이중 방어가 된다.
-- Supabase는 public 스키마에 default privileges를 걸어 새 테이블에 권한을
-- 자동 부여한다. RLS만 켜두면 행은 0건이 나오지만 쿼리 자체는 성공하므로,
-- RLS가 꺼지는 순간 전체가 노출된다. GRANT 자체를 회수해 둔다.
--
-- ⚠️ PUBLIC 회수가 핵심 — 권한 경로가 둘이다.
--    ① 역할에 직접 부여    → REVOKE ... FROM anon
--    ② PUBLIC에 부여        → REVOKE ... FROM PUBLIC
--    ②를 빠뜨리면 anon에서 회수해도 PUBLIC 경로로 여전히 읽힌다.
--    (ACL에 '=r/postgres'처럼 '=' 앞에 역할명이 없는 항목이 PUBLIC 부여분)
REVOKE ALL ON chat_quota, block_list, abuse_events FROM PUBLIC;

DO $$
DECLARE
    v_role text;
BEGIN
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
            EXECUTE format(
                'REVOKE ALL ON chat_quota, block_list, abuse_events FROM %I', v_role);
        END IF;
    END LOOP;
END $$;

REVOKE ALL ON FUNCTION chat_guard_check(text, text, int) FROM PUBLIC;
REVOKE ALL ON FUNCTION record_abuse_event(text, text, text, text, text, int, int, int) FROM PUBLIC;
REVOKE ALL ON FUNCTION abuse_summary(int, int) FROM PUBLIC;
REVOKE ALL ON FUNCTION abuse_unblock(text) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION chat_guard_check(text, text, int) TO anon;
GRANT EXECUTE ON FUNCTION record_abuse_event(text, text, text, text, text, int, int, int) TO anon;
GRANT EXECUTE ON FUNCTION abuse_summary(int, int) TO anon;
GRANT EXECUTE ON FUNCTION abuse_unblock(text) TO anon;


-- ════════════════════════════════════════════════════════════════════════════
-- 설치 확인 — 세 값이 모두 ✅ 여야 정상
-- ════════════════════════════════════════════════════════════════════════════

SELECT
    CASE WHEN (SELECT count(*) FROM pg_tables
                WHERE schemaname = 'public'
                  AND tablename IN ('chat_quota', 'block_list', 'abuse_events')) = 3
         THEN '✅ 3개' ELSE '❌ 누락' END AS "테이블",
    CASE WHEN (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'public'
                  AND p.proname IN ('chat_guard_check', 'record_abuse_event',
                                    'abuse_summary', 'abuse_unblock')) = 4
         THEN '✅ 4개' ELSE '❌ 누락' END AS "함수",
    CASE WHEN NOT EXISTS (
             SELECT 1 FROM pg_roles
              WHERE rolname = 'anon'
                AND has_table_privilege('anon', 'abuse_events', 'SELECT'))
         THEN '✅ 회수됨'
         ELSE '❌ anon이 테이블을 읽을 수 있음 — STEP 4 확인 필요' END AS "테이블 권한";
