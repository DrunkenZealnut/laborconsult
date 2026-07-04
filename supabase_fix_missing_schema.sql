-- API 키 재설정(Supabase 프로젝트 전환) 후 누락된 스키마 보수
-- 실행: Supabase Dashboard → SQL Editor에 전체 붙여넣고 Run
--
-- 증상 (Vercel 런타임 로그):
--   1) 매 채팅마다 "세션 데이터 저장 실패: Could not find the 'session_data'
--      column of 'qa_sessions'" (PGRST204) → 후속 질문 맥락이 요청 간 유실
--   2) law_article_cache 조회가 404 (테이블 자체 없음) → 법령 조문 L2 캐시 불능

-- ── 1) qa_sessions.session_data — 세션 스냅샷 저장 컬럼 ──────────────────────
-- app/core/storage.py::save_session_data() / restore_session_data() 가 사용
ALTER TABLE qa_sessions ADD COLUMN IF NOT EXISTS session_data JSONB;
ALTER TABLE qa_sessions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

-- ── 2) law_article_cache — 법령 조문 L2 캐시 테이블 ──────────────────────────
-- app/core/legal_api.py::_l2_cache_get() / _l2_cache_set() 가 사용
CREATE TABLE IF NOT EXISTS law_article_cache (
    cache_key   TEXT PRIMARY KEY,
    law_name    TEXT,
    article_no  INTEGER,
    content     TEXT,
    source_type TEXT DEFAULT 'law',
    fetched_at  TIMESTAMPTZ,
    expires_at  TIMESTAMPTZ
);

-- 만료 행 조회 성능용 인덱스 (expires_at > now() 필터)
CREATE INDEX IF NOT EXISTS idx_law_article_cache_expires
    ON law_article_cache (expires_at);

-- RLS: SUPABASE_KEY가 service_role 키라면 RLS를 켜도 서버 접근에 영향 없음(권장).
-- anon 키를 쓰고 있다면 아래 ENABLE 이후 캐시가 동작하지 않으므로,
-- 로그에 "L2 캐시 저장 실패"가 계속 보이면 DISABLE로 전환하세요.
ALTER TABLE law_article_cache ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE law_article_cache DISABLE ROW LEVEL SECURITY;  -- anon 키 사용 시 대안
