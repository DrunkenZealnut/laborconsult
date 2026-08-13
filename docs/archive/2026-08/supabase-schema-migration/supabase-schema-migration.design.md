# Supabase 전용 스키마 이전 Design Document

> **Summary**: DDL 9파일(base 4 + 패치 3 + 보조 2)을 **최종 상태 4파일로 통합**하고 전 객체를 `laborconsult` 스키마로 한정한다. 접속 생성을 단일 함수로 모으고, `SECURITY DEFINER`의 `search_path`를 새 스키마로 돌린다 — 이 한 줄이 이번 사고의 메커니즘이었다.
>
> **Project**: laborconsult
> **Author**: Claude
> **Date**: 2026-08-13
> **Status**: Draft
> **Planning Doc**: [supabase-schema-migration.plan.md](supabase-schema-migration.plan.md)

---

## 1. Overview

### 1.1 Design Goals

1. **스키마 밖을 건드릴 수 없게 만든다** — 이름이 겹쳐도 경로가 다르면 사고가 안 난다. DDL·런타임·RPC 모두에서 스키마 미지정 참조를 0으로.
2. **패치 재생이 아니라 최종 상태를 적는다** — 빈 프로젝트라 마이그레이션 이력을 재생할 이유가 없고, 재생하면 또 빠뜨린다(전례 §2.3).
3. **누락이 조용하지 않게 한다** — 지난 프로젝트 전환에서 `session_data`·`law_article_cache`가 빠진 채 프로덕션이 돌았다. 적용 후 **전수 대조**가 완료 조건이다.
4. **접속은 한 곳에서만 만든다** — 스키마 옵션을 호출부마다 붙이면 하나만 빠져도 `public`으로 샌다.

### 1.2 Design Principles

- **선언적 멱등** — 현재 상태를 묻지 않고 목표 상태로 수렴. 단 **자기 스키마 안에서만**(직전 사이클에서 이 원칙을 남의 테이블에 적용해 사고 직전까지 갔다).
- **fail-closed 기본값** — 스키마 미지정 시 `public`이 아니라 `laborconsult`로.
- **graceful degradation 유지** — Supabase 없이도 챗봇은 답한다. 기존 규약 그대로.

---

## 2. Architecture

### 2.1 전체 구조

```
Supabase 프로젝트 exnloiyzmdzbhljwwxrs
├── public 스키마              ← 우리가 쓰지 않는다 (다른 앱이 쓸 수 있음)
├── laborconsult 스키마        ← 전용. 노출 확인됨(PGRST106 대조)
│   ├── qa_sessions · qa_conversations · qa_attachments
│   ├── board_posts
│   ├── law_article_cache
│   ├── chat_quota · block_list · abuse_events      (RLS ON, 정책 무부여)
│   ├── storage_purge_queue
│   └── FUNCTION ×8  (SET search_path = laborconsult, pg_temp)
└── storage 스키마             ← Supabase 소유. 버킷 이름으로 격리
    └── bucket: chat-attachments (비공개)
```

### 2.2 접속 경로 단일화

현재 `create_client()` 호출부가 **5곳**이다. 스키마 옵션을 각자 붙이면 하나만 빠져도 `public`으로 새고 그 실패가 조용하다.

| 호출부 | 현재 | 조치 |
|--------|------|------|
| `app/config.py:125` | `create_client(url, key)` | → `make_supabase_client()` |
| `app/core/legal_api.py:154` | `create_client(url, key)` **별도 생성** | → 〃 (`law_article_cache` L2 캐시가 이 경로다) |
| `check_schema.py:93` | 〃 | → 〃 |
| `dedupe_board.py:420` | 〃 | → 〃 |
| `purge_storage_orphans.py:69` | 〃 | → 〃 |

```
app/core/storage.py
  make_supabase_client(url=None, key=None) -> Client | None
      SyncClientOptions(schema=os.getenv("SUPABASE_SCHEMA", "laborconsult"))
```

`storage.py`에 두는 이유는 `PUBLIC_EXCLUDE_KEYS`·`BOARD_POST_COLUMNS`와 같다 — FastAPI·pipeline·API 키에 의존하지 않아 앱·운영 스크립트가 모두 import할 수 있는 유일한 지점이다.

### 2.3 왜 통합인가 — 패치 재생의 실패 전례

`supabase_fix_missing_schema.sql` 머리말이 증거다:

> "API 키 재설정(**Supabase 프로젝트 전환**) 후 누락된 스키마 보수
> 증상: 매 채팅마다 `Could not find the 'session_data' column of 'qa_sessions'` (PGRST204) → 후속 질문 맥락이 요청 간 유실 / `law_article_cache` 404"

**이미 한 번 프로젝트를 옮기다 테이블·컬럼을 빠뜨렸고, 프로덕션에서 조용히 깨진 채 돌았다.** 원인은 base 파일만 적용하고 이후 패치를 놓친 것이다. 같은 실수를 반복하지 않으려면 **패치를 본문에 녹여 최종 상태 하나로** 만들어야 한다.

| 파일 | 처리 |
|------|------|
| `supabase_schema.sql` | 통합 대상 (base) |
| `supabase_abuse_guard.sql` | 통합 대상 (base) |
| `supabase_retention_purge.sql` | 통합 대상 (base) |
| `supabase_board_posts.sql` | 통합 대상 (직전 사이클 산출물) |
| `supabase_fix_missing_schema.sql` | **본문에 흡수** — `session_data`·`updated_at`·`law_article_cache` |
| `supabase_fix_session_id.sql` | **본문에 흡수** — `session_id TEXT` (base에 이미 반영됨, 확인만) |
| `supabase_attachments_private.sql` | **본문에 흡수** — 버킷 `public=false` (base에 이미 반영됨, 확인만) |
| `supabase_abuse_guard_verify.sql` | 보조 유지 (검증용) |
| `supabase_abuse_guard_rollback.sql` | 보조 유지 (롤백용) |

흡수된 3파일은 **삭제하지 않고** 머리말에 "신규 환경에는 불필요 — 본문에 흡수됨"을 적어 이력으로 남긴다.

---

## 3. `search_path` — 이번 사고의 메커니즘

### 3.1 문제

`supabase_abuse_guard.sql`의 함수 4개가 전부:

```sql
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
```

`SECURITY DEFINER` 함수는 정의자 권한으로 실행되고, 본문의 **스키마 미지정 참조는 `search_path` 순서로 해석**된다. `public`이 앞에 있으면 함수가 남의 테이블을 읽고 쓴다. `purge_expired_data()`의 `DELETE FROM board_posts`가 다른 앱의 게시글을 지우려던 것이 정확히 이 경로였다.

### 3.2 채택안

```sql
LANGUAGE plpgsql SECURITY DEFINER SET search_path = laborconsult, pg_temp AS $$
```

`public`을 **목록에서 제거한다.** 남겨 두면 우리 스키마에 없는 이름이 조용히 `public`으로 흘러간다 — fail-closed가 아니다.

`pg_temp`를 마지막에 두는 것은 Postgres 권장 사항(임시 테이블을 통한 함수 하이재킹 방지)이라 유지한다.

**예외**: `purge_expired_data()`는 `storage.objects`를 참조하므로 `SET search_path = laborconsult, storage, pg_temp`가 필요하다. 다만 storage 객체는 **항상 `storage.` 로 명시**하고 search_path에 의존하지 않는 편이 안전하다 — 명시를 택한다.

### 3.3 검사 방법

DDL에 스키마 미지정 객체 참조가 남지 않았는지 오프라인 테스트로 고정한다(§7 D6). 정규식으로 `FROM|JOIN|UPDATE|DELETE FROM|INSERT INTO` 뒤의 식별자가 `laborconsult.`·`storage.`·CTE 이름·`pg_*` 중 하나인지 본다.

---

## 4. DDL 설계

### 4.1 파일 구성과 적용 순서

```
1. supabase_schema.sql          CREATE SCHEMA + 대화 3종 + law_article_cache + 트리거 + Storage
2. supabase_abuse_guard.sql     남용 3종 + RPC 4종 + GRANT 회수
3. supabase_board_posts.sql     게시판 1종
4. supabase_retention_purge.sql storage_purge_queue + RPC 3종 + pg_cron
```

순서가 있는 이유: 1이 스키마를 만들고, 4가 1~3의 테이블을 참조한다. **각 파일 머리말에 순번과 선행 조건을 명시**한다.

### 4.2 스키마 생성과 노출

```sql
CREATE SCHEMA IF NOT EXISTS laborconsult;
GRANT USAGE ON SCHEMA laborconsult TO anon, authenticated, service_role;
```

PostgREST 노출은 **대시보드 설정**(Settings → API → Exposed schemas)이라 DDL로 못 한다. 이미 노출돼 있음을 실측했으므로(§Plan 1.3) 파일 머리말에 "이미 설정됨, 새 환경에서는 먼저 추가할 것"으로 기록한다.

### 4.3 멱등성 결함 수정

현행 base 파일은 **재실행하면 실패한다**. 통합하며 함께 고친다.

| 현행 | 문제 | 수정 |
|------|------|------|
| `CREATE INDEX idx_...` | 두 번째 실행에서 `already exists` | `CREATE INDEX IF NOT EXISTS` |
| `CREATE POLICY "..."` | 〃 | `DROP POLICY IF EXISTS` + `CREATE POLICY` |
| `CREATE TRIGGER tr_...` | 〃 | `DROP TRIGGER IF EXISTS` + `CREATE TRIGGER` |
| 정책 이름에 큰따옴표·공백 | 복사 시 스마트 따옴표로 깨짐(2026-08-13 실제 발생) | 인용부호 없는 식별자 |

**정책은 `DROP` 후 `CREATE`가 필수다.** 이름이 다른 기존 정책까지 지우는 §직전 사이클의 "전체 삭제" 방식은 **쓰지 않는다** — 우리 스키마 전용이라 이름 충돌이 없고, 전체 삭제는 남의 것까지 지울 수 있는 위험한 관용구다.

### 4.4 `law_article_cache`의 RLS 결정

`supabase_fix_missing_schema.sql`은 RLS를 켜고 "anon 키면 캐시가 동작하지 않으니 안 되면 DISABLE" 이라는 주석을 남겼다. **미결 상태로 방치된 것이다.**

| 안 | 평가 |
|----|------|
| RLS OFF | 캐시는 동작하지만 스키마 안에 RLS 없는 테이블이 하나 생긴다. 일관성 훼손 |
| **RLS ON + anon `SELECT`/`INSERT`/`UPDATE` 정책** | **채택.** 다른 테이블과 같은 모델. 캐시는 공개 법령 조문이라 민감정보가 없다 |

`DELETE` 정책은 주지 않는다(프로젝트 규약). 만료 행 정리는 `purge_expired_data()`가 맡는다.

### 4.5 Storage 정책 이름

`storage.objects`는 우리 스키마 밖이라 **정책 이름이 프로젝트 전역**이다. 현행 `"Allow anon upload"`·`"Allow anon read"`는 다른 앱과 충돌할 수 있다.

```sql
DROP POLICY IF EXISTS laborconsult_attachments_insert ON storage.objects;
CREATE POLICY laborconsult_attachments_insert ON storage.objects
    FOR INSERT TO anon WITH CHECK (bucket_id = 'chat-attachments');
```

버킷 이름도 `bucket_id = 'chat-attachments'`로 스코프가 걸려 있어 다른 버킷에는 영향이 없다.

### 4.6 `purge_expired_data()` 재작성

```sql
-- 이전 (사고 원인)
IF to_regclass('public.board_posts') IS NOT NULL THEN
    EXECUTE format('... DELETE FROM board_posts WHERE created_at < %L ...', cutoff)

-- 이후
DELETE FROM laborconsult.board_posts WHERE created_at < cutoff
```

`to_regclass` 가드도 제거한다. 그 가드는 "스키마 파일이 없어 수동 생성된 테이블이라 있을 수도 없을 수도 있다"는 전제에서 나왔는데, 이제 같은 DDL이 테이블을 보장하므로 **없으면 실패하는 게 맞다**(조용한 무동작보다 낫다).

---

## 5. 접속 코드 설계

### 5.1 `make_supabase_client()`

```python
# app/core/storage.py
SUPABASE_SCHEMA_DEFAULT = "laborconsult"

def make_supabase_client(url=None, key=None):
    """laborconsult 스키마로 고정된 Supabase 클라이언트. 미설정 시 None.

    ⚠️ 기본 스키마는 public이 아니라 laborconsult다. public으로 떨어지면
       다른 앱의 동명 테이블을 건드릴 수 있다(2026-08-13 board_posts 사고).
    """
    url = url or os.getenv("SUPABASE_URL")
    key = key or os.getenv("SUPABASE_KEY")
    if not (url and key):
        return None
    schema = os.getenv("SUPABASE_SCHEMA") or SUPABASE_SCHEMA_DEFAULT
    return create_client(url, key, options=SyncClientOptions(schema=schema))
```

`SUPABASE_SCHEMA`를 환경변수로 여는 이유는 스테이징 분리 여지 때문이다. **`public`은 값으로 허용하되 경고 로그를 남긴다** — 실수로 넣었을 때 조용하지 않게.

### 5.2 기동 시 계측

`app/config.py`가 클라이언트를 만든 뒤 스키마를 로그에 남긴다.

```
INFO Supabase 연결: schema=laborconsult host=exnloiyzmdzbhljwwxrs
```

없으면 "어느 스키마에 붙었는지"를 사후에 확인할 방법이 없다. 이번 사고에서 그게 없어 오래 걸렸다.

### 5.3 `.env` 변수명

| 변수 | 값 | 비고 |
|------|-----|------|
| `SUPABASE_URL` | `https://exnloiyzmdzbhljwwxrs.supabase.co` | 앱이 읽는 이름 |
| `SUPABASE_KEY` | `sb_publishable_…` | 신규 키 체계, `anon` 역할로 매핑 |
| `SUPABASE_SCHEMA` | (미설정 = `laborconsult`) | 선택 |

`NEXT_PUBLIC_*`는 Next.js 관례라 FastAPI인 이 프로젝트가 읽지 않는다. **제거한다** — 남겨 두면 "설정했는데 왜 안 되나"가 반복된다. `.env.example`에도 같은 이름으로 기록한다.

**Vercel 환경변수도 같이 갱신해야 한다.** 누락 시 로컬만 되고 프로덕션은 조용히 비활성이다.

---

## 6. `check_schema.py` 확장

### 6.1 대조 범위

| 테이블 | 컬럼 출처 |
|--------|-----------|
| `qa_sessions`·`qa_conversations`·`qa_attachments` | 신규 상수 |
| `board_posts` | `BOARD_POST_COLUMNS` (기존) |
| `law_article_cache` | 신규 상수 |
| `chat_quota`·`block_list`·`abuse_events` | **직접 조회 불가** — RLS ON + 정책 무부여가 정상. RPC 존재 여부로 대신 확인 |
| `storage_purge_queue` | 〃 |

### 6.2 스키마 자체를 확인해야 하는 이유

컬럼만 보면 **잘못된 스키마에 우연히 같은 이름의 테이블이 있을 때 "정상"을 보고한다.** 이번 사고가 정확히 그 형태였다 — `id`·`category`·`created_at` 3개가 맞아떨어져 우리 테이블로 보였다.

```
=== Supabase 스키마 대조 ===
접속 스키마: laborconsult          ← 기대값과 다르면 즉시 실패
프로젝트   : exnloiyzmdzbhljwwxrs
```

### 6.3 RPC 존재 확인

`sb.rpc(name, {})`를 잘못된 인자로 호출하면 함수가 **있으면** 인자 오류(`PGRST202`/`42883` 구분), **없으면** 다른 코드가 온다. 이 차이로 존재를 판정한다. 부수효과가 없는 방식이어야 하므로 `chat_guard_check` 같은 쓰기 함수는 **빈 인자로만** 호출한다.

---

## 7. 테스트

| ID | 층 | 내용 |
|----|----|----|
| **D6** | 오프라인(CI) | DDL 4파일에 **스키마 미지정 객체 참조 0건** — `laborconsult.`·`storage.`·CTE·`pg_*` 외의 참조 탐지 |
| **D7** | 오프라인(CI) | 모든 `SECURITY DEFINER` 함수의 `search_path`에 `public`이 없을 것 |
| **D8** | 오프라인(CI) | DDL에 큰따옴표 인용 식별자 0건 (스마트 따옴표 사고 재발 차단) |
| **D9** | 오프라인(CI) | 코드가 `.table()`로 접근하는 이름 ⊆ DDL 정의 테이블 (누락 탐지) |
| **D5** | 오프라인(CI) | 기존 — `BOARD_POST_COLUMNS` ↔ DDL |
| **E1~E5** | 종단(수동) | 상담 저장 / 게시판 4경로 / 글쓰기·삭제 / 쿼터 429 / 첨부+signed URL |

**D9가 이번 설계의 핵심 회귀다.** 지난 프로젝트 전환에서 `law_article_cache`가 빠진 것을 CI가 잡을 수 있었던 유일한 지점이다.

D6~D9는 전부 **파일 텍스트 검사**라 DB 없이 돈다. 실제 DB 대조는 `check_schema.py`(수동)의 몫이고, 이 경계를 스크립트 출력에 명시한다.

---

## 8. 파일별 변경 명세

| 파일 | 변경 | 규모 |
|------|------|------|
| `supabase_schema.sql` | 스키마 한정 + 패치 흡수 + 멱등화 | ~140줄 (현 85) |
| `supabase_abuse_guard.sql` | 스키마 한정 + `search_path` 교체 | ~230줄 |
| `supabase_board_posts.sql` | 스키마 한정 + 전체삭제 관용구 제거 | ~150줄 |
| `supabase_retention_purge.sql` | 스키마 한정 + `board_posts` 절 재작성 | ~320줄 |
| `supabase_fix_*.sql` ×3 | 머리말에 "본문 흡수됨" 표기 | ~6줄 |
| `app/core/storage.py` | `make_supabase_client()` + 컬럼 상수 4종 | ~60줄 |
| `app/config.py` | 접속을 단일 함수로 + 기동 로그 | ~10줄 |
| `app/core/legal_api.py` | 별도 `create_client` 제거 | ~5줄 |
| `check_schema.py` | 테이블 9종 + 스키마 확인 + RPC | ~90줄 |
| `dedupe_board.py`·`purge_storage_orphans.py` | 접속 단일 함수 사용 | ~10줄 |
| `test_offline_units.py` | D6~D9 | ~90줄 |
| `.env.example`·`CLAUDE.md` | 변수명·규약 | ~20줄 |

**Vercel 주의**: `app/core/storage.py`·`app/config.py`는 런타임 import 대상이다. 미추적 파일이 생기지 않게 커밋 확인 필수(CLAUDE.md 규약).

---

## 9. 구현·적용 순서

```
0. [선행] 옛 프로젝트 원상복구 (Plan FR-01)          ← 남의 데이터
     - cron.job 확인 → purge 중지 또는 board_posts 절 제거
     - 추가한 컬럼 5종·제약 3종 제거
1. DDL 4파일 재작성 + D6~D9 작성 → CI 통과 확인
2. .env 정리 (SUPABASE_URL·SUPABASE_KEY)
3. SQL Editor 적용 (1→2→3→4 순서, 각 파일 단위로 나눠 실행)
4. check_schema.py 확장 → 전 테이블·스키마·RPC 실측    ← 완료 조건
5. 접속 코드 단일화 (config·legal_api·스크립트 3종)
6. 로컬 종단 검증 E1~E5
7. Vercel 환경변수 갱신 → 배포 → 프로덕션 종단 재검증
8. CLAUDE.md 규약 기록
```

**3번은 파일 단위로 나눠 실행한다.** 한 번에 붙여넣으면 구문 오류 하나로 전량 롤백되고, 어디서 막혔는지도 안 보인다(2026-08-13 실제로 겪음).

**4번이 완료 조건이다.** "적용했다"가 아니라 "전수 대조가 통과했다" — 지난 전환에서 이걸 안 해서 `session_data`·`law_article_cache` 누락이 프로덕션까지 갔다.

---

## 10. Risks (Design 단계 추가분)

| Risk | Impact | Mitigation |
|------|--------|------------|
| **`search_path`에서 `public`을 빼면 기존 함수가 못 찾는 객체가 생긴다** | High | 함수 본문의 모든 참조를 스키마 한정으로 바꾸는 것이 전제. D6/D7이 CI에서 고정 |
| `pg_cron`이 `laborconsult.purge_expired_data()`를 못 찾는다 | Medium | cron 등록 시 스키마 한정 호출로 적는다: `SELECT laborconsult.purge_expired_data(365, 90)` |
| Storage 정책 이름이 다른 앱과 충돌 | Medium | §4.5 접두사. `DROP POLICY IF EXISTS`로 멱등 |
| `sb_publishable_` 키가 `anon` 역할이 아니다 | High | RLS 정책이 `TO anon`이라 다르면 전부 막힌다. **E1(상담 저장)이 첫 관문** — 실패 시 즉시 드러난다 |
| 통합 과정에서 객체를 빠뜨린다 | **High** | D9(코드 ↔ DDL 대조) + `check_schema.py` 전수. **지난 전환의 실패가 정확히 이것** |
| `law_article_cache` RLS 정책이 캐시를 막는다 | Low | §4.4에서 정책 부여. 실패 시 로그에 "L2 캐시 저장 실패"가 남는다 |
| 옛 프로젝트 데이터가 필요해진다 | Low | 이관하지 않을 뿐 **삭제하지 않는다**. 옛 프로젝트에 그대로 있다 |
| Vercel 환경변수 누락 | High | 9번 7단계. 프로덕션에서 E1 재검증이 유일한 확인 |

---

## 11. Approvals

| Role | Name | Date | Status |
|------|------|------|--------|
| Author | Claude | 2026-08-13 | Draft |
| Reviewer | — | — | Pending |

---

## 12. 결정 기록 (2026-08-13)

| 항목 | 결정 | 근거 |
|------|------|------|
| DDL 구성 | **최종 상태 4파일로 통합** | 패치 재생이 지난 전환에서 실패했다(§2.3) |
| `search_path` | **`laborconsult, pg_temp` — `public` 제거** | 남기면 없는 이름이 조용히 남의 스키마로 |
| storage 참조 | **항상 `storage.` 명시** | search_path 의존은 같은 사고의 씨앗 |
| 정책 삭제 방식 | **내 이름만 `DROP IF EXISTS`** | 전체 삭제 관용구는 남의 스키마에서 파괴적 |
| `law_article_cache` | **RLS ON + anon 3정책** | 미결로 방치된 주석을 닫는다 |
| 기본 스키마 | **`laborconsult`** (`public` 폴백 없음) | fail-closed |
| 옛 데이터 | **이관 없음, 삭제도 없음** | 사용자 확인(테스트용), 되돌릴 여지는 남긴다 |
