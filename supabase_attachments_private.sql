-- ─────────────────────────────────────────────────────────────────────────────
-- chat-attachments 버킷 공개 → 비공개 전환
--
-- 배경: supabase_schema.sql 이 버킷을 public = true 로 만들어 왔다. 상담 첨부에는
--       급여명세서·근로계약서·의무기록 등 민감정보가 담기는데, 공개 버킷에서는
--       객체 URL을 아는 사람이 인증 없이 내려받을 수 있다.
--
-- 전환 후 동작:
--   업로드  storage.py::upload_attachment — 변경 없음(anon INSERT 정책 유지)
--   저장    public_url 컬럼에 더 이상 URL을 넣지 않는다(항상 NULL)
--   열람    api/index.py::admin_conversation_detail 이 조회 시점에 발급하는
--           1시간 만료 signed URL이 유일한 경로
--
-- 선행 조건: 아래 코드 변경이 이미 배포되어 있어야 한다.
--   - app/core/storage.py       get_public_url() 호출 제거, public_url = None
--   - public/admin.html         public_url 이 null일 때 "링크 발급 실패" 표시
--   순서를 바꿔 SQL을 먼저 적용해도 관리자 조회는 signed URL로 계속 동작하지만,
--   그 사이 업로드된 첨부는 죽은 public_url 을 갖게 된다.
--
-- ⚠️ 되돌리기는 §4 참조. 실행 전 §1 현황부터 확인할 것.
-- ─────────────────────────────────────────────────────────────────────────────


-- ═══ §1. 현황 확인 (변경 없음) ═══════════════════════════════════════════════

SELECT id, name, public AS 현재_공개여부, created_at
FROM storage.buckets
WHERE id = 'chat-attachments';

SELECT count(*) AS 저장된_첨부_건수,
       count(public_url) AS 공개URL이_박혀있는_건수
FROM qa_attachments;

SELECT policyname, cmd, roles
FROM pg_policies
WHERE schemaname = 'storage' AND tablename = 'objects'
ORDER BY policyname;


-- ═══ §2. 전환 ════════════════════════════════════════════════════════════════

BEGIN;

-- (1) 버킷을 비공개로 — 이 한 줄이 핵심. 이후 공개 URL 경로는 즉시 막힌다.
UPDATE storage.buckets
SET public = false
WHERE id = 'chat-attachments';

-- (2) 이미 저장된 공개 URL 제거 — 전환 후에는 열리지 않는 죽은 링크이고,
--     DB에 남겨 두면 유출 경로를 기록해 두는 셈이 된다.
UPDATE qa_attachments
SET public_url = NULL
WHERE public_url IS NOT NULL;

COMMIT;

-- SELECT 정책("Allow anon read")은 **삭제하지 않는다.**
-- signed URL 발급은 서명하는 역할이 해당 객체를 SELECT할 수 있어야 동작한다.
-- 이 anon 키는 서버(FastAPI)에만 있고 브라우저로 나가지 않으므로(app/config.py:78)
-- 정책을 남겨도 외부에 노출되는 경로가 생기지 않는다. 버킷이 비공개가 된 이상
-- 키 없는 직접 접근은 차단된다.


-- ═══ §3. 검증 ════════════════════════════════════════════════════════════════

-- (1) 버킷이 비공개인가
SELECT id, public FROM storage.buckets WHERE id = 'chat-attachments';
--    기대: public = false

-- (2) 죽은 공개 URL이 남아 있지 않은가
SELECT count(*) AS 남은_공개URL FROM qa_attachments WHERE public_url IS NOT NULL;
--    기대: 0

-- (3) 애플리케이션 검증 — SQL이 아니라 실제 화면에서 확인할 것
--    a. 상담 화면에서 이미지 1개를 첨부해 질문 → 정상 응답
--    b. 관리자 → 해당 대화 상세 → 첨부 링크 클릭 → 파일이 열림(signed URL)
--    c. 그 링크를 복사해 두고 1시간 뒤 다시 열기 → 만료되어 열리지 않음
--    d. qa_attachments.storage_path 로 만든 공개 URL 직접 접근 → 열리지 않음
--       예: https://<project>.supabase.co/storage/v1/object/public/chat-attachments/<path>


-- ═══ §4. 되돌리기 ════════════════════════════════════════════════════════════
-- public_url 은 복구되지 않는다(§2-2에서 지움). 필요하면 storage_path 로 재생성할 것.
/*
UPDATE storage.buckets SET public = true WHERE id = 'chat-attachments';
*/
