# Plan: Supabase Q&A 저장 (카테고리 분류 + 첨부파일)

## Executive Summary

| Item | Detail |
|------|--------|
| Feature | supabase-qa-storage |
| Created | 2026-03-08 |
| Status | Plan |

### Value Delivered

| Perspective | Description |
|------------|-------------|
| Problem | 모든 상담 데이터가 인메모리 세션에만 존재하여 서버 재시작 시 소실되고, 상담 유형별 분석·통계 불가 |
| Solution | Supabase에 질문(텍스트+첨부파일)과 답변을 카테고리별로 영구 저장하는 파이프라인 구축 |
| Function UX Effect | 사용자 상담 이력이 영구 보존되며, 관리자가 카테고리별 상담 통계·트렌드를 확인할 수 있음 |
| Core Value | 데이터 영속성 확보 + 상담 분석 기반 마련 — 서비스 품질 개선을 위한 데이터 자산화 |

---

## 1. Problem Statement

### 현재 상태 (AS-IS)

- `app/models/session.py`에서 `_sessions: dict[str, Session]`으로 인메모리 관리
- Vercel Serverless 환경에서는 요청마다 cold start 가능 → 세션 데이터 유실
- 상담 내역(질문, 답변, 첨부파일)을 어디에도 영구 저장하지 않음
- 상담 유형별 통계(임금, 해고, 퇴직금 등)를 추출할 수 없음
- 첨부파일(이미지, PDF, TXT)의 내용은 답변 생성에만 사용되고 폐기

### 목표 상태 (TO-BE)

- 모든 질문과 답변을 Supabase PostgreSQL에 영구 저장
- 질문을 카테고리(임금/퇴직/해고/산재/육아/일반상담 등)로 자동 분류
- 첨부파일은 Supabase Storage에 업로드, DB에는 URL 참조 저장
- 세션 기반 대화 이력 조회 가능 (향후 사용자 인증 연동 대비)

### 근거

- `analyze_qna.py` 분석 결과에서 10,000건 Q&A의 카테고리 분포 파악 완료
- 기존 `_extract_params()`의 `calculation_type` 필드가 카테고리 분류에 활용 가능
- `app/core/file_parser.py`에 첨부파일 파싱 인프라 이미 구현됨

---

## 2. Scope

### In-Scope

1. **Supabase 클라이언트 설정** (`app/config.py`): `SUPABASE_URL`, `SUPABASE_KEY` 환경변수 + 클라이언트 초기화
2. **DB 테이블 스키마**: `sessions`, `conversations` (질문+답변+카테고리+메타), `attachments` 테이블
3. **저장 모듈** (`app/core/storage.py`): Supabase CRUD 래퍼 함수
4. **파이프라인 통합** (`app/core/pipeline.py`): `process_question()` 완료 후 비동기 저장
5. **첨부파일 업로드** (`app/core/storage.py`): base64 → Supabase Storage 업로드 + public URL
6. **카테고리 자동 분류**: 기존 `analyze_intent()` → `calculation_type` 매핑 활용
7. **의존성 추가** (`requirements.txt`): `supabase` 패키지

### Out-of-Scope

- 사용자 인증/회원가입 (향후 별도 feature)
- 관리자 대시보드 UI (DB에 데이터만 저장, 대시보드는 별도)
- 대화 이력 조회 API 엔드포인트 (저장만 우선 구현)
- 기존 인메모리 세션 완전 대체 (병행 운영 — 인메모리는 대화 흐름용, Supabase는 영구 저장용)
- 개인정보 마스킹/암호화 (별도 보안 feature)

---

## 3. Technical Analysis

### 3.1 현재 아키텍처 흐름

```
사용자 → POST /api/chat/stream → process_question() → Claude 스트리밍 답변
                                      ↓
                              analyze_intent()
                                      ↓
                          calculation_type 추출
                          (overtime, severance, dismissal 등)
                                      ↓
                              답변 생성 + SSE 전송
                                      ↓
                              (데이터 폐기 — 저장 없음)
```

### 3.2 목표 아키텍처 흐름

```
사용자 → POST /api/chat/stream → process_question() → Claude 스트리밍 답변
                                      ↓
                              analyze_intent()
                                      ↓
                          calculation_type → 카테고리 매핑
                                      ↓
                              답변 생성 + SSE 전송
                                      ↓
                              Supabase 저장 (비동기)
                              ├── conversations 테이블 (질문+답변+카테고리)
                              ├── attachments 테이블 (파일 메타데이터)
                              └── Supabase Storage (파일 바이너리)
```

### 3.3 카테고리 매핑 전략

기존 `_extract_params()`의 `calculation_type` 필드와 `CALC_TYPE_MAP` (facade.py)을 활용:

| calculation_type | 카테고리 |
|-----------------|---------|
| overtime, comprehensive, ordinary_wage | 임금·수당 |
| severance | 퇴직금 |
| dismissal | 해고 |
| unemployment | 실업급여 |
| annual_leave, weekly_holiday, public_holiday | 휴가·휴일 |
| insurance, employer_insurance | 4대보험 |
| industrial_accident | 산업재해 |
| parental_leave, maternity_leave | 육아·출산 |
| wage_arrears | 임금체불 |
| harassment | 직장내 괴롭힘 |
| (없음/기타) | 일반상담 |

### 3.4 Supabase 테이블 스키마 (초안)

**sessions**
| Column | Type | Note |
|--------|------|------|
| id | UUID (PK) | 세션 ID |
| created_at | timestamptz | 자동 생성 |
| updated_at | timestamptz | 마지막 활동 시간 |

**conversations**
| Column | Type | Note |
|--------|------|------|
| id | UUID (PK) | 대화 ID |
| session_id | UUID (FK → sessions) | 세션 참조 |
| category | text | 카테고리 (임금·수당, 퇴직금, ...) |
| question_text | text | 사용자 질문 원문 |
| answer_text | text | Claude 답변 전문 |
| calculation_types | text[] | 사용된 계산기 목록 |
| metadata | jsonb | 분석 결과, 파라미터 등 |
| created_at | timestamptz | 자동 생성 |

**attachments**
| Column | Type | Note |
|--------|------|------|
| id | UUID (PK) | 첨부파일 ID |
| conversation_id | UUID (FK → conversations) | 대화 참조 |
| filename | text | 원본 파일명 |
| content_type | text | MIME 타입 |
| storage_path | text | Supabase Storage 경로 |
| public_url | text | 공개 접근 URL |
| file_size | integer | 파일 크기 (bytes) |
| created_at | timestamptz | 자동 생성 |

### 3.5 첨부파일 저장 전략

- `file_parser.py`에서 이미 base64 디코딩 처리
- Supabase Storage 버킷: `chat-attachments` (public 또는 private)
- 경로 패턴: `{session_id}/{conversation_id}/{filename}`
- 업로드 후 public URL을 `attachments.public_url`에 저장
- 파일 크기 제한은 기존 `file_parser.py` 제한 유지 (이미지 3MB, PDF 3MB, TXT 1MB)

---

## 4. 수정 대상 파일

| File | Change | Impact |
|------|--------|--------|
| `requirements.txt` | `supabase` 패키지 추가 | Low |
| `app/config.py` | Supabase 클라이언트 초기화 + 환경변수 | Low |
| `app/core/storage.py` | **신규** — Supabase CRUD 래퍼 (save_conversation, upload_attachment) | Medium |
| `app/core/pipeline.py` | `process_question()` 완료 후 저장 호출 추가 | Medium |
| `api/index.py` | 스트리밍 완료 후 저장 트리거 | Low |
| `vercel.json` | SUPABASE_URL, SUPABASE_KEY 환경변수 참조 (Vercel 설정) | Low |
| `.env.example` | Supabase 환경변수 템플릿 추가 | Low |

---

## 5. 구현 순서

```
Step 1: requirements.txt — supabase 패키지 추가
Step 2: app/config.py — SUPABASE_URL, SUPABASE_KEY 환경변수 + 클라이언트 초기화
Step 3: Supabase 테이블/Storage 생성 (SQL 마이그레이션 스크립트)
Step 4: app/core/storage.py — save_session, save_conversation, upload_attachment 구현
Step 5: app/core/pipeline.py — process_question() 내 저장 로직 통합
Step 6: api/index.py — 스트리밍 완료 후 저장 트리거
Step 7: .env.example 업데이트
Step 8: 통합 테스트 — 질문→답변→Supabase 저장 확인
```

---

## 6. 리스크 및 고려사항

| Risk | Mitigation |
|------|------------|
| Vercel Serverless에서 Supabase 연결 지연 | 저장을 fire-and-forget 패턴으로 처리, 답변 전송에 영향 없도록 |
| 대용량 첨부파일 업로드 시간 | 파일 업로드는 답변 완료 후 비동기 처리 |
| Supabase 장애 시 답변 불가? | 저장 실패해도 답변은 정상 전송 (저장은 부가 기능) |
| 개인정보 포함 데이터 | 향후 마스킹/암호화 feature로 대응 (현재 Scope 외) |
| Supabase 무료 플랜 Storage 제한 (1GB) | 파일 크기 제한 유지 + 모니터링 |

---

## 7. 검증 기준

| 검증 항목 | 기대 결과 |
|----------|----------|
| 텍스트 질문 저장 | 질문+답변이 conversations 테이블에 저장됨 |
| 카테고리 자동 분류 | calculation_type에 따라 올바른 카테고리 할당 |
| 첨부파일 저장 | 파일이 Storage에 업로드되고 attachments에 URL 저장 |
| 세션 연속성 | 동일 session_id의 대화가 같은 세션으로 그룹화 |
| 저장 실패 시 | 답변은 정상 전송, 에러 로깅만 수행 |
| 기존 기능 무영향 | 모든 기존 테스트 케이스 통과, chatbot.py 정상 작동 |
