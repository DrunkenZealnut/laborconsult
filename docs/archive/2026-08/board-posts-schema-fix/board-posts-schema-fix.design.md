# board_posts 스키마 드리프트 복구 Design Document

> **Summary**: 결손 5컬럼을 멱등 DDL로 복구하고, RLS 정책을 **탐지가 아니라 선언**으로 확정한다. `board_recent`·`board_categories`를 오버페치 병합으로 확장하고, 드리프트를 **오프라인(파일↔코드) + 온라인(코드↔DB)** 2층으로 감시한다.
>
> **Project**: laborconsult
> **Author**: Claude
> **Date**: 2026-08-13
> **Status**: Draft
> **Planning Doc**: [board-posts-schema-fix.plan.md](board-posts-schema-fix.plan.md)

---

## 1. Overview

### 1.1 Design Goals

1. **현재 상태를 묻지 말고 목표 상태를 선언한다** — RLS 정책을 anon 키로 조회할 방법이 없고, 0행 테이블에서는 UPDATE/DELETE 프로브가 "차단"과 "0행 일치"를 구분하지 못한다(`board-duplicate-cleanup`이 실측한 바로 그 함정). 탐지를 포기하고 DDL이 정책을 **덮어쓰도록** 한다.
2. **부분 적용에서 재실행해도 안전하게** — 이번 장애가 "DDL을 일부만 실행한 상태"에서 왔다. 같은 상태에서 다시 돌려 온전해져야 한다.
3. **완료 조건은 "실행했다"가 아니라 "실측했다"** — 선행 사이클은 체크리스트를 미체크로 남긴 채 종료됐고 아무도 몰랐다.
4. **컬럼 집합의 단일 출처** — 코드·DDL·점검이 각자 컬럼을 나열하면 다시 갈라진다.

### 1.2 Design Principles

- **조용한 실패를 계측으로 바꾼다** — `except: pass`는 스키마 오류(설정 문제)와 테이블 부재를 구분하지 못한다. 삼키되 **로그는 남긴다**.
- **degrade는 유지한다** — 게시판 목록이 사용자 글 때문에 죽으면 안 된다. 실패 시 AI 대화만이라도 보여준다.
- **DELETE 정책은 주지 않는다** — 프로젝트 규약(CLAUDE.md). soft delete만 쓴다.
- **기존 메커니즘 재사용** — `board_search`가 이미 두 테이블을 병합한다. 새 개념을 만들지 않는다.

---

## 2. Architecture

### 2.1 두 갈래 작업

```
┌────────────────────────────────────────────────────────────────┐
│ ① 스키마 복구 (일회성, 사람이 SQL Editor에서 실행)              │
│    supabase_board_posts.sql                                    │
│      ADD COLUMN ×5 → INDEX ×3 → RLS 정책 ×3 → 컬럼 GRANT       │
│    3컬럼 ──────────────────────────────────────────► 8컬럼      │
└────────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────────┐
│ ② 노출 경로 완성 + 드리프트 감시 (영구)                          │
│    board_recent·board_categories 병합                          │
│    BOARD_POST_COLUMNS 단일 출처 ─┬─ 오프라인: DDL 파일 ↔ 코드   │
│                                  └─ 온라인:  코드 ↔ 실제 DB     │
└────────────────────────────────────────────────────────────────┘
```

### 2.2 컬럼 집합 단일 출처

`app/core/storage.py`에 둔다. 이 모듈은 FastAPI·pipeline·API 키 어디에도 의존하지 않아 **API·운영 스크립트·테스트가 모두 import할 수 있는 유일한 지점**이다 — `PUBLIC_EXCLUDE_KEYS`를 같은 이유로 여기 둔 선례를 따른다(`board-duplicate-cleanup`).

```
app/core/storage.py
  BOARD_POST_COLUMNS         전 8컬럼 — DDL·점검이 참조
  BOARD_POST_PUBLIC_COLUMNS  공개 응답용 5컬럼 — api/index.py의 select가 참조
        │
        ├──► api/index.py        select 문자열 생성 (search·detail·recent)
        ├──► check_schema.py     실제 DB와 대조 (온라인)
        └──► test_offline_units.py  DDL 파일과 대조 (오프라인/CI)
```

`password_hash`·`ip_hash`·`status`는 `BOARD_POST_PUBLIC_COLUMNS`에 **없다** — 공개 응답에 새면 안 되는 컬럼이라 목록 자체를 분리한다.

### 2.3 감시 2층 — 왜 나눠야 하는가

| 층 | 대조 대상 | 실행 위치 | 잡는 것 | 못 잡는 것 |
|----|-----------|-----------|---------|------------|
| **오프라인** | DDL 파일 ↔ `BOARD_POST_COLUMNS` | CI (`test_offline_units.py`) | 코드에 컬럼을 추가하고 DDL을 안 고친 경우 | DDL을 **적용하지 않은** 경우 |
| **온라인** | `BOARD_POST_COLUMNS` ↔ 실제 DB | 수동 (`check_schema.py`) | **이번 장애 유형** — 파일은 맞는데 DB가 다름 | — |

**이번 장애는 오프라인 층으로는 원리적으로 못 잡는다.** DB 접근이 필요한데 CI는 자격증명이 없다. 그래서 온라인 층이 본체이고, 오프라인 층은 "DDL 파일이 코드보다 뒤처지는" 별개 드리프트를 막는 보조다. **CI가 스키마를 검증한다고 오해하지 말 것** — 이 구분을 문서와 스크립트 출력 양쪽에 명시한다.

---

## 3. RLS 정책 확정 — Plan의 미결 항목

### 3.1 현재 상태를 알 수 없다

anon 키로 확인 가능한 사실은 하나뿐이다: `select id`가 성공한다 → **SELECT가 허용돼 있다**(RLS OFF이거나 SELECT 정책 존재). INSERT/UPDATE/DELETE는 판정 불가다:

- 테이블이 **0행**이라 UPDATE/DELETE는 정책이 있든 없든 "0행 영향"으로 끝난다
- PostgREST는 RLS 차단을 **200 OK + 빈 배열**로 반환한다(`board-duplicate-cleanup` §3.1 실측)
- INSERT 프로브는 실제 행을 만든다 — 결손 컬럼 때문에 실패할 가능성이 높지만, `{"category": "x"}`만 넣으면 **성공해 쓰레기 행이 남을 수 있다**

→ **탐지를 포기한다.** DDL이 `DROP POLICY IF EXISTS` + `CREATE POLICY`로 목표 상태를 덮어쓰면 현재 상태를 몰라도 결과가 확정된다.

### 3.2 채택안

```sql
ALTER TABLE board_posts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow anon select posts" ON board_posts;
CREATE POLICY "Allow anon select posts" ON board_posts
    FOR SELECT TO anon USING (true);

DROP POLICY IF EXISTS "Allow anon insert posts" ON board_posts;
CREATE POLICY "Allow anon insert posts" ON board_posts
    FOR INSERT TO anon WITH CHECK (true);

-- soft delete 전용: active → deleted 단방향만 허용
DROP POLICY IF EXISTS "Allow anon soft delete posts" ON board_posts;
CREATE POLICY "Allow anon soft delete posts" ON board_posts
    FOR UPDATE TO anon
    USING (status = 'active')          -- 이미 삭제된 글은 손댈 수 없다
    WITH CHECK (status = 'deleted');   -- 되살리기 불가

-- ⚠️ DELETE 정책 없음 (CLAUDE.md 규약). 하드 삭제는 보존기간 purge(postgres 역할)만 한다.

-- 컬럼 단위 제한 — RLS는 행 단위라 "status만 수정"을 표현할 수 없다.
REVOKE UPDATE ON board_posts FROM anon;
GRANT  UPDATE (status) ON board_posts TO anon;
```

**UPDATE 정책이 이 설계의 핵심이다.** 앱의 유일한 UPDATE는 `api/index.py:927`의 `update({"status": "deleted"})`이고, 위 정책·GRANT는 그것만 통과시킨다. 정책을 `USING (true)`로 열면 **누구든 `question_text`를 고치거나 삭제된 글을 되살릴 수 있다** — bcrypt 검사는 앱 단이라 RLS로는 막지 못한다.

### 3.3 `password_hash` anon SELECT 노출 — 수용

anon SELECT가 전 컬럼에 열리므로 `password_hash`도 읽힌다. 삭제 경로(`:909`)가 이 컬럼을 읽어야 해서 컬럼 REVOKE는 불가능하다.

| 대안 | 평가 |
|------|------|
| 그대로 수용 | **채택.** anon 키는 서버 전용임을 확인(`public/`에 supabase 문자열 0건, 프론트는 `/api/board/*`만 호출). bcrypt rounds=12. `qa_conversations`가 상담 원문 전체에 대해 이미 같은 노출 모델이라 baseline과 일관 |
| `REVOKE SELECT (password_hash)` + 삭제를 `SECURITY DEFINER` RPC로(pgcrypto `crypt()`) | 더 강하지만 **이번 사이클엔 부적절** — 수동 SQL 실패를 고치는 사이클에서 수동 SQL 표면(확장 설치 + RPC)을 늘리는 건 같은 위험을 키운다. §11 후속 |

**재검토 트리거**: anon 키가 클라이언트로 나가게 되거나, `SUPABASE_SERVICE_ROLE_KEY`를 도입하는 시점.

### 3.4 GRANT가 되돌아갈 수 있다

Supabase 기본 설정은 `GRANT ALL ON ALL TABLES IN SCHEMA public TO anon`을 쓴다. 누군가 그 구문을 다시 실행하면 §3.2의 컬럼 GRANT가 **조용히 원복된다.** DDL이 멱등이므로 재실행이 복구 수단이고, `check_schema.py`가 이를 감지할 수 있어야 한다(§7.3).

---

## 4. DDL 설계 — `supabase_board_posts.sql`

### 4.1 멱등 전략

기존 3컬럼과 0행을 보존해야 하므로 `DROP TABLE`은 쓰지 않는다.

```sql
CREATE TABLE IF NOT EXISTS board_posts (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY
);

ALTER TABLE board_posts ADD COLUMN IF NOT EXISTS nickname      TEXT;
ALTER TABLE board_posts ADD COLUMN IF NOT EXISTS password_hash TEXT;
ALTER TABLE board_posts ADD COLUMN IF NOT EXISTS category      TEXT DEFAULT '일반상담';
ALTER TABLE board_posts ADD COLUMN IF NOT EXISTS question_text TEXT;
ALTER TABLE board_posts ADD COLUMN IF NOT EXISTS status        TEXT DEFAULT 'active';
ALTER TABLE board_posts ADD COLUMN IF NOT EXISTS ip_hash       TEXT;
ALTER TABLE board_posts ADD COLUMN IF NOT EXISTS created_at    TIMESTAMPTZ DEFAULT NOW();
```

### 4.2 NOT NULL·CHECK를 나중에 거는 이유

설계 원본은 `nickname TEXT NOT NULL CHECK(...)`처럼 인라인이지만, `ADD COLUMN ... NOT NULL`은 **기존 행이 있으면 실패한다**. 현재 0행이라 지금은 통과하지만, 부분 적용 상태에서 재실행하는 시나리오를 전제하는 이상 분리하는 편이 안전하다.

```sql
DO $$
BEGIN
    -- 제약은 이름으로 멱등 처리 (IF NOT EXISTS 미지원)
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'board_posts_nickname_len') THEN
        ALTER TABLE board_posts ADD CONSTRAINT board_posts_nickname_len
            CHECK (char_length(nickname) BETWEEN 2 AND 10);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'board_posts_question_len') THEN
        ALTER TABLE board_posts ADD CONSTRAINT board_posts_question_len
            CHECK (char_length(question_text) BETWEEN 10 AND 2000);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'board_posts_status_enum') THEN
        ALTER TABLE board_posts ADD CONSTRAINT board_posts_status_enum
            CHECK (status IN ('active', 'deleted'));
    END IF;
END $$;

ALTER TABLE board_posts ALTER COLUMN nickname      SET NOT NULL;
ALTER TABLE board_posts ALTER COLUMN password_hash SET NOT NULL;
ALTER TABLE board_posts ALTER COLUMN question_text SET NOT NULL;
ALTER TABLE board_posts ALTER COLUMN status        SET DEFAULT 'active';
```

`SET NOT NULL`은 이미 NOT NULL이어도 오류가 아니므로 멱등이다.

### 4.3 인덱스

```sql
CREATE INDEX IF NOT EXISTS idx_board_posts_active_created
    ON board_posts(created_at DESC) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_board_posts_category
    ON board_posts(category) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_board_posts_ip_hash
    ON board_posts(ip_hash, created_at DESC);
```

### 4.4 검증 SQL (파일 말미, 실행자가 눈으로 확인)

```sql
-- 컬럼 8개가 나와야 한다
SELECT column_name, data_type, is_nullable, column_default
  FROM information_schema.columns
 WHERE table_name = 'board_posts' ORDER BY ordinal_position;

-- 정책 3개 (select/insert/update). delete는 없어야 정상
SELECT policyname, cmd, qual, with_check FROM pg_policies WHERE tablename = 'board_posts';

-- anon의 UPDATE 권한이 status 컬럼에만 있어야 한다
SELECT grantee, privilege_type, column_name
  FROM information_schema.column_privileges
 WHERE table_name = 'board_posts' AND grantee = 'anon' AND privilege_type = 'UPDATE';
```

---

## 5. `board_recent` 병합 설계

### 5.1 왜 `board_search` 방식을 쓰지 않는가

`board_search`는 조건에 맞는 **전량**을 가져와 메모리에서 자른다(`api/index.py:1062-1065`). `board_recent`는 메인페이지 슬라이드 메뉴가 여는 **가장 빈번한 경로**라 같은 방식이면 매 요청 240+행을 전송한다. 현재는 `.range()`로 DB가 잘라 준다.

### 5.2 오버페치 병합

```
limit = page * per_page          # == offset + per_page

qa:  _fetch_qa_public( select(...) .order(created_at desc).order(id desc)
                       .range(0, limit-1) )          → rows_qa, count_qa
bp:  select(...).eq("status","active")
                .order(created_at desc).order(id desc)
                .range(0, limit-1)                    → rows_bp, count_bp

merged = sort(rows_qa + rows_bp, key=(created_at, id), reverse=True)
items  = merged[offset : offset+per_page]
total  = count_qa + count_bp
```

**정당성**: 전역 정렬에서 [offset, offset+per_page) 구간에 들어갈 항목은 반드시 자기 소스의 상위 `offset+per_page`개 안에 있다. 따라서 각 소스에서 그만큼만 가져오면 충분하다.

**동률 처리**: `created_at`이 같을 때 `id` 내림차순으로 2차 정렬한다. DB 정렬과 Python 정렬이 **같은 키**를 써야 페이지 경계에서 항목이 중복·누락되지 않는다(`dedupe_board.py::pick_representative`가 동률을 `id`로 가른 것과 같은 이유).

### 5.3 알려진 오차 (수용)

`_fetch_qa_public`은 PostgREST 필터가 실패하면 **무필터로 재실행**하고 Python(`_drop_flagged`)에서 거른다. 이 폴백 구간에서는 `count_qa`가 제외분을 포함해 `total`이 과대 계상되고, 오버페치 `limit`개 중 일부가 걸러져 창이 덜 찰 수 있다.

- 정상 경로에서는 DB 필터가 이미 적용돼 오차 0
- 폴백은 드물고, 그 구간에서는 목록 전체가 이미 열화 상태다
- 현행 `board_recent`도 `total_count`를 그대로 쓰므로 **새로 생기는 문제가 아니다**

→ 수용하고 §11에 기록한다.

### 5.4 응답 스키마 변경

`board_recent`의 각 item에 `source`("ai"|"user")를 **추가**한다. `board_search`가 이미 같은 필드를 내보내므로 두 엔드포인트의 스키마가 통일된다. 사용자 글은 `answer_preview: ""`.

`nickname`은 `board_recent`에 **넣지 않는다** — 미리보기는 닉네임을 표시하지 않고, 공개 응답 표면은 좁을수록 좋다.

---

## 6. `board_categories` 합산

```python
counts = {}                                  # qa (기존 로직 그대로)
for row in qa_rows: counts[cat] += 1

try:                                         # bp 추가
    bp = sb.table("board_posts").select("category").eq("status", "active").execute()
    for row in bp.data or []: counts[cat] += 1
except Exception as e:
    logger.warning("board_posts 카테고리 집계 실패: %s", e)   # FR-08 — 삼키되 남긴다
```

`board_posts`는 페이지네이션 없이 전량을 읽는다. 현재 0행이고 사용자 직접 작성이라 증가가 느리다 — `qa_conversations`(248행)를 이미 전량 읽는 기존 로직과 같은 수준이다.

---

## 7. 드리프트 감시

### 7.1 컬럼 상수 (`app/core/storage.py`)

```python
# board_posts 스키마 단일 출처. DDL은 supabase_board_posts.sql,
# 실제 DB와의 대조는 check_schema.py, 파일과의 대조는 test_offline_units.py.
BOARD_POST_COLUMNS = (
    "id", "nickname", "password_hash", "category",
    "question_text", "status", "ip_hash", "created_at",
)

# 공개 응답에 실어도 되는 컬럼. password_hash·ip_hash·status는 의도적으로 제외한다.
BOARD_POST_PUBLIC_COLUMNS = ("id", "nickname", "category", "question_text", "created_at")
```

`api/index.py`의 select 문자열은 `", ".join(BOARD_POST_PUBLIC_COLUMNS)`로 만든다 — 세 곳(search·detail·recent)이 각자 나열하면 다시 갈라진다.

### 7.2 오프라인 대조 (CI, `test_offline_units.py`)

`supabase_board_posts.sql`을 읽어 `BOARD_POST_COLUMNS`의 모든 컬럼명이 등장하는지 확인한다. 정규식 한 줄 수준이고 DB가 필요 없다.

```
D5. test_board_posts_schema_source
    - BOARD_POST_COLUMNS ⊆ DDL 파일 텍스트
    - BOARD_POST_PUBLIC_COLUMNS ⊆ BOARD_POST_COLUMNS
    - password_hash·ip_hash·status ∉ BOARD_POST_PUBLIC_COLUMNS  ← 노출 회귀 차단
```

세 번째 단언이 실질적이다 — 누군가 편의로 `password_hash`를 공개 목록에 넣는 것을 CI가 막는다.

### 7.3 온라인 대조 (`check_schema.py`, 신규)

```
python3 check_schema.py            # 컬럼 존재 여부 대조
python3 check_schema.py --verbose  # 실패한 컬럼의 PostgREST 오류 원문
```

컬럼마다 `select(col).limit(1)`을 던져 42703을 잡는다. 종료코드 0/1로 결과를 알린다.

**출력에 반드시 명시할 것**: "이 점검은 CI에서 돌지 않는다(자격증명 없음). 배포 전 수동 실행 항목이다." — §2.3의 오해를 스크립트 자신이 방어한다.

권한 확인(§3.4의 GRANT 원복)은 anon으로 조회할 수 없으므로 **범위 밖**이다. DDL 파일의 검증 SQL(§4.4)이 그 역할을 한다.

---

## 8. 조용한 실패 제거 (FR-08)

| 위치 | 현재 | 변경 |
|------|------|------|
| `board_search:1059` | `except Exception: pass` | `except Exception as e: logger.warning("board_posts 검색 실패: %s", e)` |
| `board_detail` | `except Exception: pass` | 동일 |
| `board_categories` | (신규) | 동일 |

**동작은 바꾸지 않는다** — 여전히 삼키고 AI 대화만 반환한다. 게시판이 사용자 글 때문에 죽으면 안 된다는 원칙은 유지하되, 흔적을 남긴다.

글쓰기·삭제는 `try/except`가 **없는 채로 둔다.** 500이 나는 게 맞다 — 사용자가 "등록됐다"고 오해하면 안 되고, 이번 장애를 드러낸 것도 그 500이다.

---

## 9. 프론트 (FR-06) — `public/index.html` 미리보기

현재 카드는 `answer_preview`를 펼침 영역에 넣는다. 사용자 글은 답변이 없어 **빈 펼침**이 된다.

`board.html`의 처리(`:776`)와 일관되게:

| 항목 | AI 대화 | 사용자 글 (`source === 'user'`) |
|------|---------|--------------------------------|
| 펼침 내용 | `answer_preview` | `아직 AI 답변이 없습니다` |
| 하단 버튼 | `비슷한 질문하기 →` | `AI에게 물어보기 →` |

`escHtml`을 통과시키는 기존 경로를 그대로 쓴다. `public/sw.js`의 `VERSION`을 올린다 — 안 올리면 낡은 스크립트가 cache-first로 남아 **변경이 조용히 반영되지 않는다**(CLAUDE.md 규약).

---

## 10. 파일별 변경 명세

| 파일 | 변경 | 규모 |
|------|------|------|
| `supabase_board_posts.sql` | **신규** — §4 전체 | ~90줄 |
| `check_schema.py` | **신규** — §7.3 | ~70줄 |
| `app/core/storage.py` | `BOARD_POST_COLUMNS`·`BOARD_POST_PUBLIC_COLUMNS` | ~12줄 |
| `api/index.py` | `board_recent` 병합(§5) · `board_categories` 합산(§6) · select를 상수에서 생성 · `except` 계측(§8) | ~60줄 |
| `public/index.html` | 미리보기 `source` 분기(§9) | ~10줄 |
| `public/sw.js` | `VERSION` 증가 | 1줄 |
| `test_offline_units.py` | D5 (§7.2) | ~25줄 |
| `CLAUDE.md` | 스키마 파일 규약 · 감시 2층의 한계 · 컬럼 상수 단일 출처 | ~10줄 |

**Vercel 주의**: `check_schema.py`는 런타임에 import되지 않는 운영 스크립트다. `app/core/storage.py`는 이미 추적 중이라 신규 미추적 import는 없다.

---

## 11. 구현 순서

> **DDL을 먼저 적용한다.** 코드가 8컬럼을 전제하므로 순서가 바뀌면 배포 직후 글쓰기가 여전히 500이다.

```
1. supabase_board_posts.sql 작성
2. SQL Editor에서 실행 → §4.4 검증 SQL 3종 눈으로 확인
3. check_schema.py 작성 → 실행해 8/8 통과 확인   ← 완료 조건 (FR-02)
4. 코드 변경 (상수·병합·계측·프론트) + D5
5. 배포 → 종단 검증 (FR-03): 등록 201 → 목록·미리보기 노출 → 상세 → 오답 403 → 정답 삭제 200 → 목록에서 소멸
6. 검증용 글 정리 확인 (soft delete라 status='deleted'로 남는다)
```

**5번을 생략하지 말 것.** 3번은 "컬럼이 있다"만 말하고, NOT NULL·CHECK·RLS 정책이 실제 요청에서 맞물리는지는 종단 실행으로만 확인된다. CHECK 제약(닉네임 2~10자, 질문 10~2000자)이 앱 검증(`api/index.py:851`)과 어긋나면 앱은 통과시키고 DB가 거절해 500이 난다.

---

## 12. Risks (Design 단계 추가분)

| Risk | Impact | Mitigation |
|------|--------|------------|
| **DB CHECK와 앱 검증의 경계가 어긋난다** | High | 둘 다 닉네임 2~10 / 질문 10~2000으로 **같은 값**을 쓴다. 종단 검증에 경계값(닉네임 2자·10자, 질문 10자) 포함 |
| `SET NOT NULL`이 기존 행 때문에 실패 | Medium | 현재 0행이라 무해. 행이 생긴 뒤 재실행하면 실패할 수 있으므로 DDL 주석에 명시 |
| §3.2 UPDATE 정책이 soft delete를 막는다 | High | `USING (status='active') WITH CHECK (status='deleted')`가 앱의 유일한 UPDATE와 정확히 일치. 종단 검증 5번이 이걸 실증한다 |
| 컬럼 GRANT가 Supabase 기본 설정 재실행으로 원복 | Medium | §3.4. 멱등 DDL 재실행이 복구 수단. §4.4 검증 SQL로 확인 |
| 오버페치 병합이 페이지 경계에서 어긋난다 | Medium | DB·Python 정렬 키 통일(§5.2) + 종단 검증에서 1→2페이지 중복·누락 육안 확인 |
| `password_hash`가 anon SELECT로 읽힌다 | Medium | §3.3 수용 — 서버 전용 키 + bcrypt-12. 재검토 트리거 명시 |
| `check_schema.py`가 CI에서 도는 것으로 오해 | Low | 스크립트 출력과 CLAUDE.md 양쪽에 "수동 실행" 명시(§2.3, §7.3) |

---

## 13. 테스트

| ID | 대상 | 내용 |
|----|------|------|
| **D5** | 오프라인 (CI) | §7.2 — DDL 파일 ↔ 상수, 공개 목록에 민감 컬럼 부재 |
| **E1** | 종단 (수동) | 등록 201 → 목록·검색·미리보기·카테고리 노출 → 상세 200 |
| **E2** | 종단 (수동) | 오답 삭제 403 / 정답 삭제 200 → 목록에서 소멸 |
| **E3** | 종단 (수동) | 경계값 — 닉네임 1자/11자 거절, 질문 9자/2001자 거절 (앱과 DB가 같은 지점에서) |
| **E4** | 종단 (수동) | 페이지 1→2 경계에 중복·누락 없음 |
| **R1** | 회귀 | `python3 test_offline_units.py` 전량 통과 |

E1~E4는 DB 상태에 의존해 CI에 넣을 수 없다. Check 단계에서 실행 결과를 기록한다.

---

## 14. Approvals

| Role | Name | Date | Status |
|------|------|------|--------|
| Author | Claude | 2026-08-13 | Draft |
| Reviewer | — | — | Pending |
