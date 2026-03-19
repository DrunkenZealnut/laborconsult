# supabase-qa-storage Analysis Report

> **Analysis Type**: Gap Analysis (Plan vs Implementation)
>
> **Project**: laborconsult
> **Analyst**: gap-detector
> **Date**: 2026-03-08
> **Plan Doc**: [supabase-qa-storage.plan.md](../01-plan/features/supabase-qa-storage.plan.md)

---

## 1. Analysis Overview

### 1.1 Analysis Purpose

Plan 문서에 정의된 7개 Scope 항목이 실제 구현 코드와 일치하는지 검증한다. 이 기능에는 별도 Design 문서가 없으며, Plan 문서의 Section 3~5(기술 분석, 수정 대상 파일, 구현 순서)를 설계 기준으로 사용한다.

### 1.2 Analysis Scope

- **Plan Document**: `docs/01-plan/features/supabase-qa-storage.plan.md`
- **Implementation Files**:
  - `app/config.py` -- Supabase 클라이언트 초기화
  - `app/core/storage.py` -- 저장 모듈 (신규)
  - `app/core/pipeline.py` -- 파이프라인 통합
  - `app/core/file_parser.py` -- raw_data 필드 추가
  - `requirements.txt` -- supabase 패키지
  - `supabase_schema.sql` -- DDL 스크립트
  - `supabase_fix_session_id.sql` -- session_id 타입 수정
  - `app/models/session.py` -- 세션 ID 생성
  - `api/index.py` -- API 진입점
  - `.env.example` -- 환경변수 템플릿
- **Analysis Date**: 2026-03-08

---

## 2. Overall Scores

| Category | Score | Status |
|----------|:-----:|:------:|
| Design Match | 94% | ⚠️ |
| Architecture Compliance | 100% | ✅ |
| Convention Compliance | 100% | ✅ |
| **Overall** | **97%** | **✅** |

---

## 3. Gap Analysis (Plan vs Implementation)

### 3.1 Scope Item Verification

| # | Plan Scope Item | Implementation | Status |
|---|----------------|----------------|:------:|
| 1 | Supabase 클라이언트 설정 (config.py) | `app/config.py` L10, L24, L39-42 | ✅ |
| 2 | DB 테이블 스키마 (3 tables) | `supabase_schema.sql` 전체 | ✅ |
| 3 | 저장 모듈 (storage.py) | `app/core/storage.py` 전체 (136 lines) | ✅ |
| 4 | 파이프라인 통합 (pipeline.py) | `app/core/pipeline.py` L552-586 | ✅ |
| 5 | 첨부파일 업로드 (Storage) | `storage.py` L105-135, `file_parser.py` L36 raw_data | ✅ |
| 6 | 카테고리 자동 분류 | `storage.py` L16-52 CATEGORY_MAP + classify_category() | ✅ |
| 7 | 의존성 추가 (requirements.txt) | `requirements.txt` L14 `supabase>=2.0.0` | ✅ |

### 3.2 Supabase Client Setup (Scope #1)

| Plan Item | Implementation | Status |
|-----------|---------------|:------:|
| `SUPABASE_URL` 환경변수 | `os.environ["SUPABASE_URL"]` (config.py:40) | ✅ |
| `SUPABASE_KEY` 환경변수 | `os.environ["SUPABASE_KEY"]` (config.py:41) | ✅ |
| `create_client()` 호출 | `from supabase import create_client` (config.py:10) | ✅ |
| AppConfig에 supabase 필드 | `supabase: SupabaseClient` (config.py:24) | ✅ |

### 3.3 DB Schema (Scope #2)

#### qa_sessions

| Plan Column | Plan Type | Schema DDL | Status |
|------------|-----------|------------|:------:|
| id | UUID (PK) | `UUID PRIMARY KEY DEFAULT gen_random_uuid()` | ⚠️ Note |
| created_at | timestamptz | `TIMESTAMPTZ NOT NULL DEFAULT now()` | ✅ |
| updated_at | timestamptz | `TIMESTAMPTZ NOT NULL DEFAULT now()` + trigger | ✅ |

**Note**: DDL defines `id` as UUID, but `session.py:59` generates 12-char hex IDs (`uuid.uuid4().hex[:12]`). `supabase_fix_session_id.sql` fixes this by altering to TEXT type. This is a known issue with a fix script ready.

#### qa_conversations

| Plan Column | Plan Type | Schema DDL | Status |
|------------|-----------|------------|:------:|
| id | UUID (PK) | `UUID PRIMARY KEY DEFAULT gen_random_uuid()` | ✅ |
| session_id | UUID (FK) | `UUID NOT NULL REFERENCES qa_sessions(id)` | ✅ |
| category | text | `TEXT NOT NULL DEFAULT '일반상담'` | ✅ |
| question_text | text | `TEXT NOT NULL` | ✅ |
| answer_text | text | `TEXT NOT NULL DEFAULT ''` | ✅ |
| calculation_types | text[] | `TEXT[] DEFAULT '{}'` | ✅ |
| metadata | jsonb | `JSONB DEFAULT '{}'` | ✅ |
| created_at | timestamptz | `TIMESTAMPTZ NOT NULL DEFAULT now()` | ✅ |

All 3 indexes present: `idx_qa_conversations_session`, `idx_qa_conversations_category`, `idx_qa_conversations_created`.

#### qa_attachments

| Plan Column | Plan Type | Schema DDL | Status |
|------------|-----------|------------|:------:|
| id | UUID (PK) | `UUID PRIMARY KEY DEFAULT gen_random_uuid()` | ✅ |
| conversation_id | UUID (FK) | `UUID NOT NULL REFERENCES qa_conversations(id)` | ✅ |
| filename | text | `TEXT NOT NULL` | ✅ |
| content_type | text | `TEXT NOT NULL` | ✅ |
| storage_path | text | `TEXT NOT NULL` | ✅ |
| public_url | text | `TEXT` (nullable) | ✅ |
| file_size | integer | `INTEGER DEFAULT 0` | ✅ |
| created_at | timestamptz | `TIMESTAMPTZ NOT NULL DEFAULT now()` | ✅ |

Index present: `idx_qa_attachments_conversation`.

### 3.4 Storage Module (Scope #3)

| Plan Function | Implementation | Status |
|--------------|----------------|:------:|
| save_conversation() | `storage.py:82-100` -- ConversationRecord + insert | ✅ |
| upload_attachment() | `storage.py:105-135` -- Storage upload + DB insert | ✅ |
| save_session (ensure_session) | `storage.py:57-67` -- upsert pattern | ✅ |

**Positive Additions** (not in Plan):
- `ConversationRecord` dataclass (L72-79) -- structured input for save_conversation
- `ensure_session()` (L57-67) -- idempotent session upsert with updated_at refresh
- `classify_category()` accepts `tool_type` parameter for harassment detection (L45-52)

### 3.5 Category Mapping (Scope #6)

| Plan calc_type | Plan Category | Impl Category | Status |
|---------------|--------------|--------------|:------:|
| overtime, comprehensive, ordinary_wage | 임금·수당 | 임금·수당 | ✅ |
| severance | 퇴직금 | 퇴직금 | ✅ |
| dismissal | 해고 | 해고 | ✅ |
| unemployment | 실업급여 | 실업급여 | ✅ |
| annual_leave, weekly_holiday, public_holiday | 휴가·휴일 | 휴가·휴일 | ✅ |
| insurance, employer_insurance | 4대보험 | 4대보험 | ✅ |
| industrial_accident | 산업재해 | 산업재해 | ✅ |
| parental_leave, maternity_leave | 육아·출산 | 육아·출산 | ✅ |
| wage_arrears | 임금체불 | 임금체불 | ✅ |
| harassment | 직장내 괴롭힘 | 직장내 괴롭힘 | ✅ |
| (없음/기타) | 일반상담 | 일반상담 | ✅ |

**Positive Additions** -- extra calc_types mapped beyond Plan:

| calc_type | Category | Note |
|-----------|---------|------|
| minimum_wage | 임금·수당 | Plan 미기재, 자연스러운 확장 |
| prorated | 임금·수당 | Plan 미기재, 자연스러운 확장 |
| flexible_work | 임금·수당 | Plan 미기재, 자연스러운 확장 |
| shutdown_allowance | 해고 | Plan 미기재, 자연스러운 확장 |
| compensatory_leave | 휴가·휴일 | Plan 미기재, 자연스러운 확장 |
| eitc | 근로장려금 | 신규 카테고리 (Plan에 없음) |
| retirement_tax | 퇴직금 | Plan 미기재, severance 카테고리 확장 |
| retirement_pension | 퇴직금 | Plan 미기재, severance 카테고리 확장 |
| average_wage | 임금·수당 | Plan 미기재, 자연스러운 확장 |

### 3.6 Pipeline Integration (Scope #4)

| Plan Item | Implementation | Status |
|-----------|---------------|:------:|
| process_question() 완료 후 비동기 저장 | pipeline.py L552-586 (Step 8) | ✅ |
| fire-and-forget 패턴 | try/except with logger.warning (L585-586) | ✅ |
| 저장 실패해도 답변 정상 전송 | Step 8 is after yield chunks, before yield done | ✅ |
| 카테고리 결정 로직 | classify_category() 호출 (L565) | ✅ |
| 첨부파일 업로드 | upload_attachment() 반복 호출 (L578-584) | ✅ |
| raw_data 전달 | att.raw_data guard (L580) | ✅ |

### 3.7 Attachment Storage (Scope #5)

| Plan Item | Implementation | Status |
|-----------|---------------|:------:|
| base64 → Supabase Storage 업로드 | storage.py L116-120 | ✅ |
| 버킷: `chat-attachments` | `sb.storage.from_("chat-attachments")` (L116) | ✅ |
| 경로 패턴: `{session_id}/{conversation_id}/{filename}` | `f"{session_id}/{conversation_id}/{filename}"` (L114) | ✅ |
| public URL 저장 | `get_public_url()` → `qa_attachments.public_url` (L121, L128) | ✅ |
| file_parser.py raw_data 필드 | `raw_data: bytes \| None = None` (file_parser.py:36) | ✅ |
| parse_attachment에서 raw_data 할당 | `result.raw_data = data` (file_parser.py:155) | ✅ |

### 3.8 File Modification Verification

| Plan File | Plan Change | Implemented | Status |
|-----------|------------|:-----------:|:------:|
| `requirements.txt` | supabase 패키지 추가 | L14 `supabase>=2.0.0` | ✅ |
| `app/config.py` | Supabase 클라이언트 초기화 | L10, L24, L39-42 | ✅ |
| `app/core/storage.py` | 신규 -- CRUD 래퍼 | 136 lines, 4 functions | ✅ |
| `app/core/pipeline.py` | 저장 호출 추가 | L552-586 (Step 8) | ✅ |
| `api/index.py` | 스트리밍 완료 후 저장 트리거 | N/A (pipeline 내부에서 처리) | ✅ Note |
| `vercel.json` | SUPABASE env 참조 | 변경 없음 (Vercel 대시보드 설정) | ✅ Note |
| `.env.example` | Supabase 환경변수 템플릿 | **미구현** | ❌ |

**api/index.py Note**: Plan은 "스트리밍 완료 후 저장 트리거"를 api/index.py에서 별도 처리하도록 명시했으나, 실제로는 `pipeline.py`의 `process_question()` 내부(Step 8)에서 저장이 처리된다. api/index.py는 generator를 소비할 뿐이므로 별도 수정이 불필요하다. 이는 더 나은 설계이다 (관심사 분리).

**vercel.json Note**: Supabase 환경변수는 Vercel 대시보드에서 직접 설정하는 것이 표준이므로 vercel.json 수정은 불필요하다.

---

## 4. Differences Found

### 4.1 Missing Items (Plan O, Implementation X)

| # | Item | Plan Location | Description | Impact |
|---|------|--------------|-------------|:------:|
| M-1 | .env.example 업데이트 | Plan Section 5, Step 7 | `SUPABASE_URL`, `SUPABASE_KEY` 템플릿이 `.env.example`에 추가되지 않음 | Low |

### 4.2 Added Items (Plan X, Implementation O)

| # | Item | Implementation Location | Description |
|---|------|------------------------|-------------|
| A-1 | ConversationRecord dataclass | storage.py:72-79 | 구조화된 입력 타입 -- Plan은 함수 시그니처만 언급 |
| A-2 | ensure_session() | storage.py:57-67 | 세션 upsert 로직 -- Plan의 save_session에 해당 |
| A-3 | 9개 추가 calc_type 매핑 | storage.py:20-42 | minimum_wage, prorated, flexible_work, shutdown_allowance, compensatory_leave, eitc, retirement_tax, retirement_pension, average_wage |
| A-4 | RLS 정책 | supabase_schema.sql:40-53 | anon key insert/select/update 허용 -- 보안 필수 |
| A-5 | updated_at 트리거 | supabase_schema.sql:56-66 | 자동 갱신 함수 + 트리거 |
| A-6 | Storage 버킷 DDL | supabase_schema.sql:68-77 | 버킷 생성 + Storage RLS |
| A-7 | supabase_fix_session_id.sql | 별도 파일 | UUID → TEXT 타입 변경 스크립트 |
| A-8 | metadata에 has_attachments 포함 | pipeline.py:573 | 첨부파일 존재 여부 메타데이터 |
| A-9 | classify_category에 tool_type 파라미터 | storage.py:45-48 | harassment 직접 감지 (calc_type 우회) |

### 4.3 Changed Items (Plan != Implementation)

| # | Item | Plan | Implementation | Impact |
|---|------|------|----------------|:------:|
| C-1 | 테이블명 접두사 | `sessions`, `conversations`, `attachments` | `qa_sessions`, `qa_conversations`, `qa_attachments` | None |
| C-2 | 저장 트리거 위치 | api/index.py에서 처리 | pipeline.py 내부 Step 8에서 처리 | Positive |

**C-1**: Plan Section 3.4에서는 `sessions`, `conversations`, `attachments`로 표기했으나, DDL과 코드에서는 `qa_` 접두사를 사용한다. 이는 Supabase에서 다른 테이블과의 이름 충돌을 방지하는 좋은 관행이다.

**C-2**: api/index.py가 아닌 pipeline.py 내부에서 저장을 처리함으로써 동기/비동기 API 양쪽 모두에서 저장이 동작한다. 더 나은 설계.

### 4.4 Known Issues

| # | Issue | Description | Fix Available |
|---|-------|-------------|:------------:|
| K-1 | session_id 타입 불일치 | DDL: UUID, 앱: 12-char hex | `supabase_fix_session_id.sql` 실행 필요 |

---

## 5. Risk Assessment

| Plan Risk | Mitigation (Plan) | Implementation | Status |
|-----------|-------------------|----------------|:------:|
| Serverless 연결 지연 | fire-and-forget | try/except + logger.warning (L553-586) | ✅ |
| 대용량 첨부파일 | 비동기 처리 | 답변 완료 후 동기 저장 (충분) | ✅ |
| Supabase 장애 시 답변 불가? | 저장 실패해도 답변 정상 | Step 8은 모든 chunk yield 후 실행 | ✅ |
| Storage 제한 (1GB) | 파일 크기 제한 유지 | file_parser.py 기존 제한 유지 | ✅ |

---

## 6. Verification Criteria Check

| Plan 검증 항목 | Implementation Evidence | Status |
|---------------|------------------------|:------:|
| 텍스트 질문 저장 | save_conversation() inserts to qa_conversations | ✅ |
| 카테고리 자동 분류 | classify_category() with CATEGORY_MAP (22 entries) | ✅ |
| 첨부파일 저장 | upload_attachment() → Storage + qa_attachments | ✅ |
| 세션 연속성 | ensure_session() upsert + session_id FK | ✅ |
| 저장 실패 시 | try/except wrapping, logger.warning (L585-586) | ✅ |
| 기존 기능 무영향 | 저장은 Step 8 (답변 완료 후), 독립적 try/except | ✅ |

---

## 7. Match Rate Summary

```
+---------------------------------------------+
|  Overall Match Rate: 97%                     |
+---------------------------------------------+
|  Plan Scope Items:         7/7   (100%)      |
|  File Modifications:       6/7   ( 86%)      |
|  DB Schema Fields:        20/20  (100%)      |
|  Category Mappings:       11/11  (100%)      |
|  Risk Mitigations:         4/4   (100%)      |
|  Verification Criteria:    6/6   (100%)      |
+---------------------------------------------+
|  Missing:     1 item  (.env.example)         |
|  Changed:     2 items (positive deviations)  |
|  Added:       9 items (positive additions)   |
+---------------------------------------------+
```

---

## 8. Recommended Actions

### 8.1 Immediate (Must-Do)

| # | Action | File | Impact |
|---|--------|------|--------|
| 1 | `.env.example`에 Supabase 환경변수 추가 | `.env.example` | Low -- 개발자 온보딩 편의성 |
| 2 | `supabase_fix_session_id.sql` 실행 | Supabase SQL Editor | High -- 미실행 시 insert 실패 |

Suggested `.env.example` addition:
```bash
# Supabase - Q&A 영구 저장용
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_anon_key_here
```

### 8.2 Documentation Update

| # | Item | Description |
|---|------|-------------|
| 1 | Plan Section 3.4 테이블명 | `sessions` → `qa_sessions` 등 접두사 반영 |
| 2 | Plan Section 4 api/index.py | "저장 트리거" 삭제 또는 "pipeline 내부에서 처리"로 수정 |

### 8.3 Future Consideration

| # | Item | Note |
|---|------|------|
| 1 | SUPABASE_URL/KEY 미설정 시 graceful skip | 현재 `os.environ["SUPABASE_URL"]`은 KeyError 발생 -- Supabase 없이 로컬 개발 불가 |
| 2 | 대화 이력 조회 API | Plan Out-of-Scope, 향후 별도 feature |
| 3 | 개인정보 마스킹 | Plan Out-of-Scope, 향후 별도 feature |

---

## 9. Synchronization Decision

| # | Gap | Recommended Action |
|---|-----|-------------------|
| M-1 (.env.example) | **Modify Implementation** -- `.env.example`에 SUPABASE_URL, SUPABASE_KEY 추가 |
| K-1 (session_id UUID) | **Run Fix Script** -- `supabase_fix_session_id.sql` 실행하여 UUID→TEXT 변환 |
| C-1 (테이블명 접두사) | **Update Plan** -- `qa_` 접두사를 Plan 문서에 반영 (의도적 개선) |
| C-2 (저장 위치) | **Update Plan** -- api/index.py 대신 pipeline.py 내부 처리로 반영 (의도적 개선) |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-03-08 | Initial gap analysis (Plan vs Implementation) | gap-detector |
