-- ============================================================================
-- 챗봇 남용 가드 — 배포 후 양성 검증 (chatbot-security §8.4)
--
-- 실행: supabase_abuse_guard.sql 적용 후 SQL Editor에 전체를 붙여넣고 Run
--       결과가 표 하나로 나온다. "결과" 열이 전부 ✅ 여야 정상.
--
-- ⚠️ 왜 필요한가
--   앱의 가드는 전 계층 fail-open이다. 스키마가 없거나 권한이 틀려도
--   경고 로그만 남기고 조용히 통과한다. 따라서 "차단이 안 나온다"는 확인만으로는
--   가드가 살아 있는지 알 수 없고, 아래처럼 **실제로 차단이 나오는지**를 봐야 한다.
--
-- 검증용 키('ip:selftest*')만 사용하며 실제 트래픽 데이터를 건드리지 않는다.
-- 마지막에 검증 흔적을 스스로 정리한다.
-- ============================================================================

DROP TABLE IF EXISTS _guard_verify;
CREATE TEMP TABLE _guard_verify (
    seq      serial,
    item     text,
    expected text,
    actual   text,
    pass     text
);

DO $$
DECLARE
    r          jsonb;
    n          int;
    anon_read  boolean := false;   -- anon이 테이블을 읽을 수 있었는가(위험 신호)
    anon_rpc   boolean := false;   -- anon이 RPC를 호출할 수 있었는가(정상 신호)
    anon_err   text := '';
BEGIN
    -- ── 1. 쿼터: 상한 3에서 4번째 요청이 거부되어야 한다 ────────────────────
    PERFORM chat_guard_check('ip:selftest1', '2099-01-01', 3);
    PERFORM chat_guard_check('ip:selftest1', '2099-01-01', 3);
    PERFORM chat_guard_check('ip:selftest1', '2099-01-01', 3);
    r := chat_guard_check('ip:selftest1', '2099-01-01', 3);
    INSERT INTO _guard_verify(item, expected, actual, pass) VALUES (
        '1. 쿼터 — 상한 3에서 4번째 요청',
        'allowed=false, reason=quota',
        r::text,
        CASE WHEN (r->>'allowed') = 'false' AND (r->>'reason') = 'quota'
             THEN '✅ 정상' ELSE '❌ 실패 — 쿼터가 작동하지 않음' END);

    -- ── 2. 자동 차단: block 모드 위반 3회 누적 시 차단 발동 ─────────────────
    PERFORM record_abuse_event('ip:selftest2','injection','s','test','block',300,3,30);
    PERFORM record_abuse_event('ip:selftest2','injection','s','test','block',300,3,30);
    r := record_abuse_event('ip:selftest2','injection','s','test','block',300,3,30);
    INSERT INTO _guard_verify(item, expected, actual, pass) VALUES (
        '2. 자동 차단 — 위반 3회 누적',
        'blocked=true',
        r::text,
        CASE WHEN (r->>'blocked') = 'true'
             THEN '✅ 정상' ELSE '❌ 실패 — 자동 차단이 발동하지 않음' END);

    -- ── 3. 차단된 키는 이후 요청이 거부되어야 한다 ──────────────────────────
    r := chat_guard_check('ip:selftest2', '2099-01-01', 50);
    INSERT INTO _guard_verify(item, expected, actual, pass) VALUES (
        '3. 차단 적용 — 차단된 키의 다음 요청',
        'allowed=false, reason=blocked, retry_after>0',
        r::text,
        CASE WHEN (r->>'allowed') = 'false' AND (r->>'reason') = 'blocked'
                  AND (r->>'retry_after')::int > 0
             THEN '✅ 정상' ELSE '❌ 실패 — 차단이 적용되지 않음' END);

    -- ── 4. monitor 모드는 차단을 발동시키지 않아야 한다(관측 기간 보호) ─────
    PERFORM record_abuse_event('ip:selftest3','injection','s','test','monitor',300,3,30);
    PERFORM record_abuse_event('ip:selftest3','injection','s','test','monitor',300,3,30);
    r := record_abuse_event('ip:selftest3','injection','s','test','monitor',300,3,30);
    INSERT INTO _guard_verify(item, expected, actual, pass) VALUES (
        '4. monitor 모드 — 위반 3회에도 차단 없음',
        'blocked=false',
        r::text,
        CASE WHEN (r->>'blocked') = 'false'
             THEN '✅ 정상' ELSE '❌ 실패 — monitor인데 차단이 발동함' END);

    -- ── 5. 수동 해제 ────────────────────────────────────────────────────────
    PERFORM abuse_unblock('ip:selftest2');
    r := chat_guard_check('ip:selftest2', '2099-01-01', 50);
    INSERT INTO _guard_verify(item, expected, actual, pass) VALUES (
        '5. 수동 해제 — 해제 후 재요청',
        'allowed=true',
        r::text,
        CASE WHEN (r->>'allowed') = 'true'
             THEN '✅ 정상' ELSE '❌ 실패 — 해제가 반영되지 않음' END);

    -- ── 6. 관리자 현황 조회 ─────────────────────────────────────────────────
    r := abuse_summary(7, 5);
    INSERT INTO _guard_verify(item, expected, actual, pass) VALUES (
        '6. 관리자 현황 — abuse_summary',
        'counts/events/blocked 키 존재',
        left(r::text, 80) || '...',
        CASE WHEN r ? 'counts' AND r ? 'events' AND r ? 'blocked'
             THEN '✅ 정상' ELSE '❌ 실패 — 응답 형식 불일치' END);

    -- ── 7. 권한 격리: anon은 테이블 직접 접근 불가, RPC만 가능 ──────────────
    BEGIN
        SET LOCAL ROLE anon;
        BEGIN
            SELECT count(*) INTO n FROM abuse_events;
            anon_read := true;                      -- 읽혔다면 위험
        EXCEPTION WHEN OTHERS THEN
            anon_err := SQLERRM;                    -- 막혔다면 정상
        END;
        BEGIN
            PERFORM chat_guard_check('ip:selftest4', '2099-01-01', 50);
            anon_rpc := true;
        EXCEPTION WHEN OTHERS THEN
            anon_rpc := false;
        END;
        RESET ROLE;
    EXCEPTION WHEN OTHERS THEN
        RESET ROLE;                                 -- anon 역할이 없는 환경 등
        anon_err := 'role 전환 불가: ' || SQLERRM;
    END;

    INSERT INTO _guard_verify(item, expected, actual, pass) VALUES (
        '7. 권한 — anon의 abuse_events 직접 조회',
        '거부(permission denied)',
        CASE WHEN anon_read THEN '쿼리 성공(' || n || '건 반환)'
             ELSE coalesce(anon_err, '거부됨') END,
        CASE WHEN anon_read AND n > 0
             THEN '❌ 위험 — anon이 남용 로그를 열람함(RLS 미작동)'
             WHEN anon_read
             THEN '⚠️ 보완 필요 — RLS로 행은 막히나 SELECT 권한이 남아 방어선이 1겹 (STEP 4 재실행)'
             ELSE '✅ 정상' END);

    INSERT INTO _guard_verify(item, expected, actual, pass) VALUES (
        '8. 권한 — anon의 RPC 호출',
        '허용',
        CASE WHEN anon_rpc THEN '호출 성공' ELSE '호출 실패' END,
        CASE WHEN anon_rpc THEN '✅ 정상'
             ELSE '❌ 실패 — GRANT EXECUTE 누락, 쿼터가 프로덕션에서 작동 안 함' END);

    -- ── 8. 검증 흔적 정리 ───────────────────────────────────────────────────
    DELETE FROM chat_quota   WHERE subject_key LIKE 'ip:selftest%';
    DELETE FROM block_list   WHERE subject_key LIKE 'ip:selftest%';
    DELETE FROM abuse_events WHERE subject_key LIKE 'ip:selftest%';

    SELECT (SELECT count(*) FROM chat_quota   WHERE subject_key LIKE 'ip:selftest%')
         + (SELECT count(*) FROM block_list   WHERE subject_key LIKE 'ip:selftest%')
         + (SELECT count(*) FROM abuse_events WHERE subject_key LIKE 'ip:selftest%')
      INTO n;
    INSERT INTO _guard_verify(item, expected, actual, pass) VALUES (
        '9. 검증 흔적 정리',
        '0건 잔류',
        n || '건',
        CASE WHEN n = 0 THEN '✅ 정상' ELSE '❌ 실패 — 검증 데이터가 남음' END);
END $$;


-- ════════════════════════════════════════════════════════════════════════════
-- 결과 — "결과" 열이 전부 ✅ 여야 배포 가능
-- ════════════════════════════════════════════════════════════════════════════
SELECT
    item     AS "검증 항목",
    pass     AS "결과",
    expected AS "기대값",
    actual   AS "실제 반환"
FROM _guard_verify
ORDER BY seq;
