# Supabase 전용 스키마 이전 Planning Document

> **Summary**: laborconsult가 다른 앱과 Supabase `public` 스키마를 공유하다 `board_posts` 이름 충돌로 남의 테이블을 자기 것으로 오인했다. 새 프로젝트의 **`laborconsult` 전용 스키마**로 전면 이전하고, 테이블 7종·RPC 4종·purge 함수·Storage 버킷을 저장소 관리 DDL로 재구축한다. 부수적으로 저장소에 스키마 파일이 없던 문제(`board_posts`)도 함께 해소된다.
>
> **Project**: laborconsult
> **Author**: Claude
> **Date**: 2026-08-13
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | laborconsult가 남의 Supabase 프로젝트 `public` 스키마에 얹혀 있었다. `board_posts`가 **다른 앱의 테이블**(구 단위 권한·승인 사용자·관리자 모델)인데 이름만 같아 우리 코드가 자기 것으로 오인했고, `purge_expired_data()`는 그 앱의 게시글을 365일 기준으로 **삭제하도록 작성돼 있었다.** 이름 충돌은 `public` 스키마를 공유하는 한 언제든 재발한다. |
| **Solution** | 새 Supabase 프로젝트(`exnloiyzmdzbhljwwxrs`)의 **`laborconsult` 전용 스키마**로 이전한다(실측: 스키마 노출 확인, 테이블 0개). 테이블 7종·RPC·purge를 **저장소 관리 DDL 3파일**로 재구축하고, 클라이언트를 `SyncClientOptions(schema=...)`로 고정한다. 이름 충돌은 스키마 경계가 구조적으로 차단한다. |
| **Function/UX Effect** | 사용자 체감 기능은 그대로다 — 상담 저장·세션 복원·게시판·남용 가드·첨부. 다만 **현재 `SUPABASE_URL`/`SUPABASE_KEY`가 `.env`에 없어 Supabase 기능 전체가 꺼져 있다**(대화 미저장·게시판 빈 목록·쿼터 미작동). 이 사이클이 그것을 되살린다. |
| **Core Value** | "우리 테이블인가"를 이름으로 판단하던 상태에서 **스키마 경계로 보장하는** 상태로 바꾼다. 동시에 DB 전체가 저장소 DDL로 재현 가능해져, 이번처럼 "수동 생성 후 아무도 모르는 드리프트"가 생길 여지를 없앤다. |

---

## 1. Overview

### 1.1 Purpose

laborconsult의 모든 Supabase 자산을 새 프로젝트의 `laborconsult` 스키마로 이전하고, 그 스키마 전체를 저장소가 관리하는 멱등 DDL로 확립한다.

### 1.2 Background — 무엇이 잘못됐나 (2026-08-13 실측)

**이름 충돌 발견 경위.** `board_posts` 스키마 드리프트를 고치려다 정책을 조회한 결과:

```
policyname          cmd     roles            qual
board_posts_select  SELECT  {authenticated}  is_approved_user() AND (is_admin() OR district_id = get_user_district_id() ...)
board_posts_update  UPDATE  {authenticated}  is_approved_user() AND (is_admin() OR author_id = auth.uid())
board_posts_delete  DELETE  {authenticated}  is_admin()
board_posts_insert  INSERT  {authenticated}  ...
```

`is_admin()`·`district_id`·`author_id`·`auth.uid()` — laborconsult에 없는 함수·컬럼·인증 모델이다. **다른 애플리케이션의 테이블이었다.**

**이미 존재하던 위험**(내가 손대기 전부터):

| # | 내용 | 심각도 |
|---|------|:------:|
| 1 | `purge_expired_data()`의 `DELETE FROM board_posts WHERE created_at < cutoff` — pg_cron 매일 실행용. **다른 앱의 게시글을 지운다** | 🔴 |
| 2 | `board_search`·`board_detail`이 그 테이블을 조회 — 42703으로 실패해 `except: pass`에 삼켜짐 | 🟡 |
| 3 | `board_post_write` INSERT가 그 테이블 대상 — HTTP 500 | 🟡 |

**이번 작업 중 발생시킨 것**(전부 되돌릴 수 있는 범위):

| # | 내용 | 상태 |
|---|------|------|
| 4 | 그 테이블에 컬럼 5종 추가(`nickname`·`password_hash`·`question_text`·`status`·`ip_hash`) | 롤백 SQL 제공, 미실행 |
| 5 | CHECK 제약 3종 추가 시도 | 트랜잭션 롤백 추정, 확인 필요 |
| 6 | **정책 4개 전체 삭제 후 `TO anon USING(true)` 대체** — 그 앱의 인가 붕괴 + 익명 공개 | 🔴 **미실행. 정책 상세를 확인해 직전에 중단** |

6번은 실행됐다면 사고였다. "현재 상태를 묻지 말고 목표 상태를 선언한다"는 설계 원칙이 **남의 테이블에 적용되면 파괴적**이라는 것을 놓쳤다.

### 1.3 새 환경 실측

| 항목 | 값 |
|------|-----|
| 프로젝트 | `https://exnloiyzmdzbhljwwxrs.supabase.co` |
| `.env` 변수명 | `NEXT_PUBLIC_SUPABASE_URL` · `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` |
| **앱이 읽는 변수명** | `SUPABASE_URL` · `SUPABASE_KEY` (`app/config.py:123-124`) → **불일치, 현재 미설정** |
| 키 형식 | `sb_publishable_…` (Supabase 신규 체계, 기존 anon JWT 대체) |
| `laborconsult` 스키마 | **노출됨** — 대조 실험으로 확정(아래) |
| `laborconsult` 테이블 | **0개** |
| `public` 스키마 | laborconsult 테이블 7종 전부 없음 |

**스키마 노출 판정 근거** — PostgREST 오류 코드 대조:

| `Accept-Profile` | 응답 | 의미 |
|------------------|------|------|
| `laborconsult` | `PGRST205` 테이블 없음 | 스키마는 유효, 테이블만 없음 |
| `definitely_not_exposed_xyz` | `PGRST106` Invalid schema | 미노출 시 나오는 코드 |
| `storage` | `PGRST106` Invalid schema | 〃 |

`supabase-py 2.31`에서 `SyncClientOptions(schema="laborconsult")`로 라우팅되는 것도 실측 확인했다.

### 1.4 현재 서비스 상태

`SUPABASE_URL`/`SUPABASE_KEY` 미설정 → `app/config.py`가 `supabase=None`으로 폴백한다. **상담 저장·세션 복원·게시판·남용 쿼터·첨부가 전부 비활성**이다. 챗봇 답변 자체는 정상(Pinecone·LLM은 무관).

### 1.5 이전 대상 자산

| 자산 | 정의 위치 | 비고 |
|------|-----------|------|
| `qa_sessions`·`qa_conversations`·`qa_attachments` | `supabase_schema.sql` | RLS 정책 7종 포함 |
| `abuse_events`·`block_list`·`chat_quota` | `supabase_abuse_guard.sql` | RLS 활성 + **정책 무부여**, 접근은 RPC만 |
| RPC 4종 (`chat_guard_check` 등) | `supabase_abuse_guard.sql` | `SECURITY DEFINER` |
| `board_posts` | `supabase_board_posts.sql` | 이번 사이클 신규 작성분 재사용 |
| `purge_expired_data()` + `storage_purge_queue` | `supabase_retention_purge.sql` | pg_cron 등록 포함 |
| Storage 버킷 `chat-attachments` | `supabase_schema.sql` 말미 | 새 프로젝트에 재생성 필요 |

### 1.6 Related Documents / Files

- 직전 사이클(전제 무효화됨): `docs/01-plan/features/board-posts-schema-fix.plan.md`, `.design.md`
- 스키마 파일 3종: `supabase_schema.sql`, `supabase_abuse_guard.sql`, `supabase_retention_purge.sql`, `supabase_board_posts.sql`
- 접속부: `app/config.py:118-130`
- 운영 스크립트: `check_schema.py`, `dedupe_board.py`, `purge_storage_orphans.py`, `refresh_nlrc_cases.py`

---

## 2. Scope

### 2.1 In Scope

- [ ] FR-01: 옛 프로젝트 원상복구 — 추가한 컬럼·제약 제거, purge의 `board_posts` 절 제거
- [ ] FR-02: `.env` 변수명 정리 (`SUPABASE_URL`/`SUPABASE_KEY`) + `.env.example` 갱신
- [ ] FR-03: 스키마 지정 접속 (`SyncClientOptions(schema=...)`, 기본값 `laborconsult`)
- [ ] FR-04: 스키마 한정 DDL 재작성 — 기존 4파일을 `laborconsult` 스키마로
- [ ] FR-05: RPC 4종을 `laborconsult` 스키마에 재생성 + 호출부 검증
- [ ] FR-06: Storage 버킷 `chat-attachments` 재생성 (비공개 + 정책)
- [ ] FR-07: `purge_expired_data()` 재작성 — `board_posts`를 **자기 스키마 것으로만** 한정
- [ ] FR-08: `check_schema.py` 확장 — 테이블 7종 전체 대조 + 스키마 이름 검증
- [ ] FR-09: 종단 검증 — 상담 저장·게시판·가드 쿼터·첨부 전 경로
- [ ] FR-10: CLAUDE.md·`.env.example` 규약 갱신

### 2.2 Out of Scope

- **옛 프로젝트 데이터 이관** — 사용자가 "어차피 테스트용"으로 확인. 옛 프로젝트에 그대로 남아 있어 필요해지면 나중에 옮길 수 있다(§5 Risk)
- 다른 앱(구 단위 게시판)의 코드·스키마 수정 — 우리가 건드린 것만 되돌린다
- Pinecone·BM25 코퍼스 (별개 저장소, 무관)
- 게시판 기능 자체의 설계 변경 — `board-posts-schema-fix`의 FR-04~06(목록 병합 등)은 이미 구현돼 있고 그대로 살린다
- `SUPABASE_SERVICE_ROLE_KEY` 도입

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | **옛 프로젝트 원상복구**: 추가한 컬럼 5종·CHECK 3종 제거(그 앱 소유인 `id`·`category`·`created_at`은 **절대 건드리지 않는다**). 실행 전 `SELECT *`로 원래 컬럼 온전성 확인. 아울러 `purge_expired_data()`에서 `board_posts` 절을 제거하거나 pg_cron을 중지해 **다른 앱 데이터 삭제 위험을 끊는다** | **High** | Pending |
| FR-02 | **`.env` 정리**: `SUPABASE_URL`·`SUPABASE_KEY`를 새 프로젝트 값으로 설정. `NEXT_PUBLIC_*`는 Next.js 관례라 이 프로젝트(FastAPI)와 무관 — 혼선을 막기 위해 제거하거나 주석 처리. `.env.example`도 갱신 | High | Pending |
| FR-03 | **스키마 지정 접속**: `app/config.py`가 `SyncClientOptions(schema=os.getenv("SUPABASE_SCHEMA", "laborconsult"))`로 클라이언트를 만든다. 운영 스크립트(`check_schema.py`·`dedupe_board.py`·`purge_storage_orphans.py`)도 같은 경로를 쓰도록 **접속 생성을 한 곳으로 모은다** | High | Pending |
| FR-04 | **DDL 스키마 한정**: 기존 4파일의 모든 객체를 `laborconsult.` 로 한정. `CREATE SCHEMA IF NOT EXISTS laborconsult` 포함. 멱등 유지. **다른 스키마의 동명 객체를 건드릴 수 없는 형태**여야 한다 | High | Pending |
| FR-05 | **RPC 재생성**: `chat_guard_check`·`abuse_summary`·`abuse_unblock`(+ `purge_expired_data`)을 `laborconsult` 스키마에 생성. `SECURITY DEFINER` + `SET search_path`가 새 스키마를 가리키는지 확인. `sb.rpc()` 호출이 노출 스키마 기준으로 해석되는지 실측 | High | Pending |
| FR-06 | **Storage 버킷**: `chat-attachments` 재생성(비공개). 업로드 정책 + 1시간 signed URL 경로가 동작하는지 확인. `storage` 스키마는 우리 스키마 밖이라 별도 처리 | Medium | Pending |
| FR-07 | **purge 재작성**: `laborconsult.board_posts`만 대상으로 한정. `to_regclass('public.board_posts')` 같은 스키마 미지정 참조를 전부 제거 — 이번 사고의 직접 원인이다 | High | Pending |
| FR-08 | **`check_schema.py` 확장**: 테이블 7종 컬럼 집합 대조 + **접속 스키마가 `laborconsult`인지** 확인. 잘못된 스키마에 붙은 채 "정상"을 보고하면 이번 사고가 반복된다 | High | Pending |
| FR-09 | **종단 검증**: ① 챗봇 질문 1건 → `qa_conversations` 저장 확인 ② 게시판 목록·검색·상세 ③ 게시판 글쓰기 201 → 노출 → 삭제 ④ 남용 쿼터(`DAILY_CHAT_QUOTA=3`으로 4번째 429) ⑤ 첨부 업로드 + signed URL | High | Pending |
| FR-10 | **규약 기록**: CLAUDE.md에 스키마 경계·접속 단일 경로·"스키마 미지정 참조 금지"를 기록. `.env.example` 갱신 | Medium | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| Isolation | 어떤 DDL·런타임 쿼리도 `laborconsult` 밖 객체를 수정하지 않을 것 | DDL 전수 검토 (스키마 미지정 참조 0건) |
| Idempotency | DDL 4파일 2회 연속 실행 시 동일 결과 | SQL Editor 2회 실행 |
| Safety | 옛 프로젝트에서 그 앱 소유 컬럼·정책·행 변경 0건 | 실행 전후 `SELECT *` 대조 |
| Fail-safe | Supabase 미설정·연결 실패 시 기존 graceful degradation 유지 | 코드 리뷰 + `.env` 제거 상태 기동 |
| Correctness | RLS 정책이 옛 프로젝트와 동일 (anon INSERT/SELECT, DELETE 무부여) | `pg_policies` 조회 |
| Observability | 접속 스키마가 기동 로그에 남을 것 | 로그 확인 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] 옛 프로젝트: 추가 컬럼 5종·제약 3종 제거, 그 앱 정책 4개 원형 유지 확인
- [ ] 옛 프로젝트: `purge_expired_data()`가 그 앱의 `board_posts`를 더 이상 지우지 않음 (또는 cron 중지)
- [ ] `python3 check_schema.py` → 테이블 7종 전 컬럼 일치 + 스키마 `laborconsult` 확인
- [ ] `python3 check_env.py` 통과
- [ ] 챗봇 질문 1건이 `laborconsult.qa_conversations`에 저장됨
- [ ] 게시판 목록·검색·상세·카테고리 정상 (사용자 글 + AI 대화 병합)
- [ ] 게시판 글쓰기 201 → 목록·미리보기 노출 → 상세 → 삭제 200
- [ ] `DAILY_CHAT_QUOTA=3`에서 4번째 요청 429 (RPC 실동작)
- [ ] 첨부 업로드 + 1시간 signed URL 열람
- [ ] `python3 test_offline_units.py` 통과
- [ ] DDL 4파일 재실행 시 오류 0

### 4.2 Quality Criteria

- [ ] DDL에 스키마 미지정 객체 참조 0건
- [ ] 접속 생성 지점이 코드베이스에 **1개** (스크립트 포함)
- [ ] 다른 앱 데이터 변경 0건

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| **롤백 SQL이 그 앱 소유 컬럼을 지운다** | **High** | Low | 삭제 대상 5종은 2026-08-13 첫 조사에서 전부 42703(부재)로 확인된 것뿐. `id`·`category`·`created_at`은 목록에서 제외. 실행 전 `SELECT *` 육안 확인 |
| **pg_cron이 그 앱 게시글을 계속 지운다** | **High** | 조사 필요 | FR-01 최우선. `SELECT * FROM cron.job`으로 등록 여부부터 확인 |
| 옛 프로젝트 데이터 248건 손실 | Medium | — | 사용자가 "테스트용"으로 확인. **옛 프로젝트에 그대로 남아 있어** 필요 시 이관 가능. 이번엔 이관하지 않는다 |
| `sb.rpc()`가 커스텀 스키마를 못 찾는다 | High | Medium | FR-05에서 **실측 우선**. 안 되면 RPC만 `public`에 두고 내부에서 `laborconsult.*`를 참조하는 절충 |
| Storage는 `laborconsult` 스키마 밖이다 | Medium | 확실 | `storage.objects`는 Supabase 소유 스키마. 버킷 이름으로 격리되며, 이번 프로젝트가 전용이라 충돌 없음 |
| `sb_publishable_` 키의 RLS 거동이 anon JWT와 다르다 | Medium | Low | 신규 키 체계는 `anon` 역할로 매핑된다. FR-09 쿼터 검증이 실증 |
| 코드가 스키마를 안 지정한 채 배포된다 | High | Medium | 기본값을 `laborconsult`로 두어 **미지정 시에도 올바른 스키마**. `public` 폴백 금지 |
| Vercel 환경변수 미갱신 | High | 확실 | 배포 전 Vercel 대시보드에서 `SUPABASE_URL`·`SUPABASE_KEY`(+`SUPABASE_SCHEMA`) 갱신. 누락 시 프로덕션만 조용히 비활성 |
| 이전 중 프로덕션이 대화를 저장하지 못한다 | Medium | 확실 | 이미 그 상태다(§1.4). 이전 완료가 곧 복구 |

---

## 6. Architecture Considerations

### 6.1 스키마 경계가 해결하는 것

```
[이전]  public 스키마 (공유)
          ├── qa_conversations      ← 우리
          ├── board_posts           ← 남의 것 (이름만 같음) ⚠️
          └── ...
        "우리 것인가"를 이름으로 판단 → 오인 가능

[이후]  laborconsult 스키마 (전용)
          ├── qa_conversations
          ├── board_posts           ← 우리 것임이 경로로 보장
          └── ...
        스키마 경계가 구조적으로 차단
```

`public.board_posts`와 `laborconsult.board_posts`는 **공존할 수 있다.** 우리 코드는 후자만 본다.

### 6.2 접속 생성을 한 곳으로

현재 `create_client()` 호출부가 `app/config.py`·운영 스크립트 3종에 흩어져 있다. 스키마 옵션을 각자 붙이면 하나만 빠져도 `public`으로 새고, 그 실패가 **조용하다**(테이블이 없으면 PGRST205, 있으면 남의 것을 건드림).

→ `app/core/storage.py`(FastAPI·API 키 비의존 지점)에 `make_supabase_client()`를 두고 전부 그것을 쓴다. `PUBLIC_EXCLUDE_KEYS`·`BOARD_POST_COLUMNS`와 같은 자리다.

### 6.3 DDL 파일 구성

기존 4파일 구조를 유지하되 전부 스키마 한정한다. 파일을 합치지 않는 이유는 적용 단위와 변경 이력이 다르기 때문이다.

```
supabase_schema.sql          CREATE SCHEMA + 대화 3종 + RLS + Storage 버킷
supabase_abuse_guard.sql     남용 3종 + RPC 4종
supabase_board_posts.sql     게시판 1종 (이번 사이클 작성분 재사용)
supabase_retention_purge.sql purge 함수 + 큐 + pg_cron
```

**적용 순서가 있다** — `supabase_schema.sql`이 스키마를 만들므로 첫 번째다. 순서를 파일 머리 주석에 명시한다.

### 6.4 스키마 미지정 참조 금지

이번 사고의 직접 원인이 `to_regclass('public.board_posts')`였다. `SECURITY DEFINER` 함수는 `SET search_path`를 갖는데, 그 값이 `public`이면 함수 본문의 미지정 참조가 전부 남의 스키마로 간다.

→ DDL 검토 시 **스키마 미지정 객체 참조를 0건으로** 만든다. 오프라인 테스트로 고정 가능하다(정규식으로 `FROM board_posts` 같은 패턴 탐지).

### 6.5 `check_schema.py`가 스키마도 확인해야 하는 이유

컬럼만 대조하면, 잘못된 스키마에 우연히 같은 이름의 테이블이 있을 때 "정상"을 보고한다. **이번 사고가 정확히 그 형태였다** — 컬럼 3개가 맞아떨어져 우리 테이블로 보였다.

→ 접속 스키마를 출력하고, 기대값과 다르면 실패로 처리한다.

---

## 7. Follow-up / Notes

### 7.1 직전 사이클(`board-posts-schema-fix`)의 처리

Plan·Design의 진단("우리 테이블의 스키마 드리프트")은 **틀렸다.** 다만 그 사이클에서 만든 산출물 중 다음은 유효하며 이번에 그대로 쓴다:

| 산출물 | 상태 |
|--------|------|
| `supabase_board_posts.sql` | ✅ 스키마 한정만 추가하면 유효 |
| `check_schema.py` | ✅ 확장해서 사용 (FR-08) |
| `BOARD_POST_COLUMNS` 단일 출처 | ✅ 유효 |
| `board_recent` 병합·`board_categories` 합산 | ✅ 유효 (테이블만 바뀜) |
| `except: pass` → 계측 | ✅ **이번 사고를 드러낸 것이 이 로그였다** |
| D5 회귀 | ✅ 유효 |
| Plan/Design 문서 | ❌ 전제 무효 — 이 사이클 문서가 대체하고, 교훈은 여기 §1.2에 승계 |

### 7.2 배운 것 — 검증이 없으면 진단이 소설이 된다

세 번 연속 같은 형태로 틀렸다.

| # | 단정 | 실제 | 원인 |
|---|------|------|------|
| 1 | "`board_posts` 0행" | RLS가 anon에게 행을 가린 것 | `count`를 읽지 않고 `len(data)`로 판단 |
| 2 | "0행 = 쓸 수 없었다" | 남의 테이블이라 우리 글이 있을 리 없었다 | 1번 위에 쌓은 추론 |
| 3 | "우리 테이블의 드리프트" | 다른 앱의 테이블 | 소유권을 **이름으로만** 판단 |

셋 다 **확인 가능한 것을 확인하지 않고** 넘어갔다. 특히 3번은 `pg_policies` 한 번이면 즉시 드러났는데 Plan·Design·구현까지 간 뒤에야 봤다. 새 스토어에 손대기 전에 **소유권과 실제 내용을 먼저 확인**하는 것을 규약으로 남긴다(FR-10).

### 7.3 실행 순서 권고

```
1. FR-01  옛 프로젝트 원상복구 + cron 위험 제거   ← 최우선(남의 데이터)
2. FR-02  .env 정리
3. FR-04  DDL 스키마 한정 재작성
4.        SQL Editor 적용 (순서: schema → abuse_guard → board_posts → retention)
5. FR-03  접속 코드 + FR-08 점검 확장
6. FR-09  종단 검증
7. FR-10  규약 기록
```

1번이 먼저인 이유는 **남의 데이터가 걸린 유일한 항목**이기 때문이다. 우리 서비스 복구는 그다음이다.

---

## 8. Approvals

| Role | Name | Date | Status |
|------|------|------|--------|
| Author | Claude | 2026-08-13 | Draft |
| Reviewer | — | — | Pending |

---

## 9. 결정 기록 (2026-08-13)

| 항목 | 결정 | 대안 |
|------|------|------|
| 격리 방식 | **전용 스키마 `laborconsult`** | 테이블 이름 접두사(`lc_*`), 별도 프로젝트만 |
| 옛 데이터 | **이관하지 않음** (사용자 확인: 테스트용) | 248건 이관 |
| 스키마 지정 | **접속 옵션 + 기본값 `laborconsult`** | 테이블마다 스키마 한정, `public` 폴백 |
| 게시판 테이블 | **`laborconsult.board_posts`** — 남의 것과 공존 | 이름 변경(`user_posts` 등) |
| 접속 생성 | **`storage.py` 단일 함수** | 호출부마다 옵션 지정 |
