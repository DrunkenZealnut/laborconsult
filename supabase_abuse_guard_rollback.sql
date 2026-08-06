-- ============================================================================
-- 챗봇 남용 가드 — 되돌리기 (chatbot-security §8.6)
--
-- ⚠️ 먼저 이것부터: 스키마를 지우지 않고도 가드를 멈출 수 있다.
--    Vercel 환경변수에서 아래 둘을 off로 바꾸면 즉시 무력화된다(재배포 불요).
--        ABUSE_GUARD_MODE=off
--        SCOPE_GATE_MODE=off
--    쿼터까지 끄려면 DAILY_CHAT_QUOTA를 아주 큰 값(예: 100000)으로 설정.
--
--    아래 스크립트는 스키마 자체를 제거하며 **남용 이벤트 기록이 모두 사라진다**.
--    되돌릴 수 없으므로, 관측 데이터가 필요하면 먼저 백업할 것:
--        SELECT * FROM abuse_events ORDER BY created_at DESC;
--
-- 앱은 스키마가 없어도 fail-open으로 정상 동작한다(쿼터·차단만 생략).
-- qa_conversations.metadata.guard_flag는 잔류해도 무해하다.
-- ============================================================================

DROP FUNCTION IF EXISTS chat_guard_check(text, text, int);
DROP FUNCTION IF EXISTS record_abuse_event(text, text, text, text, text, int, int, int);
DROP FUNCTION IF EXISTS abuse_summary(int, int);
DROP FUNCTION IF EXISTS abuse_unblock(text);

DROP TABLE IF EXISTS chat_quota;
DROP TABLE IF EXISTS block_list;
DROP TABLE IF EXISTS abuse_events;

-- 확인: 0 / 0 이면 제거 완료
SELECT
    (SELECT count(*) FROM pg_tables
      WHERE schemaname = 'public'
        AND tablename IN ('chat_quota', 'block_list', 'abuse_events')) AS tables_left,
    (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
      WHERE n.nspname = 'public'
        AND p.proname IN ('chat_guard_check', 'record_abuse_event',
                          'abuse_summary', 'abuse_unblock')) AS functions_left;
