-- Q&A 상담 저장 테이블 (Supabase SQL Editor에서 실행)

-- 1. 세션 테이블
CREATE TABLE IF NOT EXISTS qa_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. 대화 테이블 (질문 + 답변)
CREATE TABLE IF NOT EXISTS qa_conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES qa_sessions(id) ON DELETE CASCADE,
    category TEXT NOT NULL DEFAULT '일반상담',
    question_text TEXT NOT NULL,
    answer_text TEXT NOT NULL DEFAULT '',
    calculation_types TEXT[] DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_qa_conversations_session ON qa_conversations(session_id);
CREATE INDEX idx_qa_conversations_category ON qa_conversations(category);
CREATE INDEX idx_qa_conversations_created ON qa_conversations(created_at DESC);

-- 3. 첨부파일 테이블
CREATE TABLE IF NOT EXISTS qa_attachments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES qa_conversations(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    public_url TEXT,
    file_size INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_qa_attachments_conversation ON qa_attachments(conversation_id);

-- 4. RLS (Row Level Security) — anon key로 insert/select 허용
ALTER TABLE qa_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE qa_conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE qa_attachments ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow anon insert sessions" ON qa_sessions FOR INSERT TO anon WITH CHECK (true);
CREATE POLICY "Allow anon select sessions" ON qa_sessions FOR SELECT TO anon USING (true);
CREATE POLICY "Allow anon update sessions" ON qa_sessions FOR UPDATE TO anon USING (true);

CREATE POLICY "Allow anon insert conversations" ON qa_conversations FOR INSERT TO anon WITH CHECK (true);
CREATE POLICY "Allow anon select conversations" ON qa_conversations FOR SELECT TO anon USING (true);

CREATE POLICY "Allow anon insert attachments" ON qa_attachments FOR INSERT TO anon WITH CHECK (true);
CREATE POLICY "Allow anon select attachments" ON qa_attachments FOR SELECT TO anon USING (true);

-- 5. updated_at 자동 갱신 트리거
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tr_qa_sessions_updated
    BEFORE UPDATE ON qa_sessions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- 6. Storage 버킷 (SQL로 생성 — 또는 Supabase 대시보드에서 수동 생성)
INSERT INTO storage.buckets (id, name, public)
VALUES ('chat-attachments', 'chat-attachments', true)
ON CONFLICT (id) DO NOTHING;

-- Storage RLS: anon 업로드/읽기 허용
CREATE POLICY "Allow anon upload" ON storage.objects FOR INSERT TO anon
    WITH CHECK (bucket_id = 'chat-attachments');
CREATE POLICY "Allow anon read" ON storage.objects FOR SELECT TO anon
    USING (bucket_id = 'chat-attachments');
