# board_posts 스키마 드리프트 복구 Planning Document

> **Summary**: `board_posts` 테이블에 코드가 기대하는 8개 컬럼 중 **5개가 없다**(`nickname`·`password_hash`·`question_text`·`status`·`ip_hash`). 게시판 글쓰기·삭제는 배포된 채로 **한 번도 작동한 적이 없고**(HTTP 500), 검색·상세는 `except: pass`가 오류를 삼켜 조용히 0건이 된다. 결손 컬럼을 복구하고, 근본 원인인 "스키마 파일 부재"를 봉인한다.
>
> **Project**: laborconsult
> **Author**: Claude
> **Date**: 2026-08-13
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | `board_posts`에 `id`·`category`·`created_at` **3개만** 존재하고 나머지 5개가 없다(2026-08-13 실측). 글쓰기 INSERT는 결손 컬럼 4개를 쓰는데 `try/except`가 **없어 HTTP 500**, 삭제도 500이다. 즉 게시판 글쓰기는 배포 후 지금까지 **100% 실패**해 왔고, `board_posts` 0행은 "아무도 안 썼다"가 아니라 **"쓸 수 없었다"** 이다. 근본 원인은 이 테이블에 스키마 파일이 없다는 것 — `supabase_retention_purge.sql:173`이 "수동 생성된 테이블"이라 명시하고 있고, `board-write-security` 사이클의 배포 체크리스트에 있던 DDL이 **미체크 상태로 남아 부분만 실행**됐다. |
| **Solution** | ① 멱등 DDL(`supabase_board_posts.sql`)로 결손 5컬럼 + 인덱스 + RLS 정책을 복구하고 저장소를 **단일 출처**로 만든다. ② `board_recent`·`board_categories`가 `board_posts`를 병합 조회하도록 확장해 글쓰기→노출→상세→삭제 전 구간을 성립시킨다. ③ 코드가 select하는 컬럼 집합과 실제 스키마를 대조하는 점검 수단을 두어 드리프트가 조용히 남지 않게 한다. |
| **Function/UX Effect** | 사용자가 `/board`에서 질문을 등록할 수 있게 된다(현재 등록 버튼이 500을 반환). 등록한 글이 `/board` 목록·검색·상세·카테고리 필터와 **메인페이지 슬라이드 메뉴 미리보기**에 모두 나타나고, 비밀번호로 삭제할 수 있다. |
| **Core Value** | "배포됐지만 작동한 적 없는 기능"을 실제로 작동시킨다. 동시에 이 프로젝트에서 세 번째로 반복된 **조용한 실패**(RLS DELETE 무성 차단 → fail-open 가드 → 42703 삼킴) 중 하나를 계측 가능하게 바꾼다. |

---

## 1. Overview

### 1.1 Purpose

공개 질문게시판의 **사용자 직접 작성** 기능(`board_posts`)을 실제로 동작하는 상태로 만든다. AI 상담 대화(`qa_conversations`) 쪽은 정상이므로 범위 밖이다.

### 1.2 Background — 실측 (2026-08-13, Supabase 직접 조회)

**실제 스키마 vs 설계** (`docs/02-design/features/board-write-security.design.md:138-150`)

| 컬럼 | 설계 | 실제 DB | 코드 사용처 |
|------|------|:-------:|-------------|
| `id` | UUID PK | ✅ | 전 경로 |
| `nickname` | TEXT NOT NULL CHECK(2~10) | ❌ **42703** | write INSERT / search select / detail select |
| `password_hash` | TEXT NOT NULL | ❌ **42703** | write INSERT / delete select |
| `category` | TEXT DEFAULT '일반상담' | ✅ | 전 경로 |
| `question_text` | TEXT NOT NULL CHECK(10~2000) | ❌ **42703** | write INSERT / search select·ilike / detail select |
| `status` | TEXT DEFAULT 'active' CHECK | ❌ **42703** | delete update·filter / search filter |
| `ip_hash` | TEXT | ❌ **42703** | write INSERT |
| `created_at` | TIMESTAMPTZ DEFAULT NOW() | ✅ | 전 경로 + 보존기간 purge |

**8개 중 5개 결손.** 인덱스 3종(`idx_board_posts_active_created`·`_category`·`_ip_hash`)의 존재 여부는 anon 권한으로 확인 불가 — Design에서 확정한다.

**경로별 영향** — 결정적 차이는 `try/except` 유무다

| 경로 | 코드 | 결손 컬럼 접촉 | `try/except` | 실제 증상 |
|------|------|----------------|:------------:|-----------|
| 글쓰기 `POST /api/board/write` | `api/index.py:876-888` | INSERT 4개 | **없음** | 🔴 **HTTP 500** — 사용자에게 오류 |
| 삭제 `POST /api/board/{id}/delete` | `:909-914`, `:927` | select 1 + filter 1 + update 1 | **없음** | 🔴 **HTTP 500** |
| 검색 `GET /api/board/search` | `:1039-1041` | select 1 + filter 1 | 있음(`:1059 pass`) | 🟡 조용히 사용자 글 0건 |
| 상세 `GET /api/board/{id}` | `:1114` | select 1 | 있음 | 🟡 조용히 404 |
| 목록 `GET /api/board/recent` | `:933-` | **board_posts 미조회** | — | ⚪ 스키마 무관 (§1.3) |
| 카테고리 `GET /api/board/categories` | `:975-` | **board_posts 미조회** | — | ⚪ 스키마 무관 (§1.3) |
| 보존 purge | `supabase_retention_purge.sql:175-180` | `created_at`만 | `to_regclass` 가드 | ⚪ 작동 (0행이라 무의미) |

글쓰기·삭제가 500이라는 점이 핵심이다. **이 기능은 "쓰면 사라진다"가 아니라 "쓸 수 없다"** — 앞선 사이클(`board-duplicate-cleanup` Plan §7.1)이 이를 "try/except에 삼켜져 사라진다"로 기술한 것은 검색·상세 경로만 본 부분 진단이었다.

### 1.3 별개 결함 — 목록·카테고리가 `board_posts`를 안 읽는다

스키마와 **무관한** 두 번째 갭이다. 소비처를 전수 확인했다:

| 화면 | 호출 API | `board_posts` 포함 |
|------|----------|:------------------:|
| `/board` 페이지 목록 | `board_search` (`public/board.html:651`) | ✅ 포함 |
| `/board` 카테고리 필터 | `board_categories` (`:619`) | ❌ 미포함 |
| 메인페이지 슬라이드 메뉴 미리보기 | `board_recent` (`public/index.html:1819`) | ❌ 미포함 |

즉 스키마만 고치면 **`/board` 본 목록에는 사용자 글이 나타난다**(검색 API가 이미 병합하므로). 남는 구멍은 **메인페이지 미리보기**와 **카테고리 필터의 건수·목록**이다. 후자는 사용자 글이 속한 카테고리가 필터에 아예 뜨지 않거나 건수가 어긋나는 형태로 드러난다.

### 1.4 근본 원인 — 스키마 파일이 없다

```
supabase_schema.sql          qa_sessions · qa_conversations · qa_attachments  ← board_posts 없음
supabase_abuse_guard.sql     abuse_events · block_list · chat_quota
supabase_retention_purge.sql purge_expired_data()
   └ :173-175  "board_posts 는 스키마 파일이 없어 수동 생성된 테이블이므로
                존재할 때만 처리한다(없어도 이 함수가 실패하지 않도록)."
```

DDL은 `docs/04-report/features/board-write-security.report.md:248-260`의 **배포 체크리스트 안에만** 있고, 그 항목은 지금도 `- [ ]` 미체크다. 수동 SQL Editor 실행에 의존했고 일부만 반영된 채 사이클이 종료됐다. 저장소에 단일 출처가 없으니 **누구도 어긋났음을 알 수 없었다.**

### 1.5 Related Documents / Files

- 선행 사이클: `docs/02-design/features/board-write-security.design.md:138-150` (설계 DDL), `docs/04-report/features/board-write-security.report.md:248-260` (미체크 배포 체크리스트)
- 게시판 API: `api/index.py:838-1155`
- 프론트: `public/board.html` (글쓰기·목록·상세·삭제), `public/index.html:1819` (미리보기)
- 보존기간: `supabase_retention_purge.sql:173-180`
- 기존 스키마 파일 관례: `supabase_schema.sql`, `supabase_abuse_guard.sql`

---

## 2. Scope

### 2.1 In Scope

- [ ] FR-01: 멱등 DDL 파일 `supabase_board_posts.sql` 신규 — 결손 5컬럼 + 인덱스 3종 + RLS 정책
- [ ] FR-02: DDL 적용 및 스키마 복구 확인 (SQL Editor — anon은 DDL 불가)
- [ ] FR-03: 글쓰기·삭제 종단 검증 (등록 → 목록 → 상세 → 삭제)
- [ ] FR-04: `board_recent`가 `qa_conversations` ∪ `board_posts`를 병합 조회
- [ ] FR-05: `board_categories`가 양쪽 카테고리를 합산
- [ ] FR-06: 프론트가 답변 없는 사용자 글을 올바르게 렌더 (`answer_preview` 빈 값)
- [ ] FR-07: 스키마 대조 점검 수단 — 코드가 select하는 컬럼 집합 vs 실제 스키마
- [ ] FR-08: `board_search`·`board_detail`의 `except: pass`를 계측 가능하게 교체
- [ ] FR-09: CLAUDE.md에 스키마 파일 규약 기록

### 2.2 Out of Scope

- **사용자 글에 대한 AI 답변 생성** — 현재 `board_posts`에 `answer_text`가 없고 설계에도 없다. 게시판은 "질문 등록"만 하고 답변은 챗봇 경로가 담당하는 것이 현 구조다. 바꾸려면 별도 사이클
- `qa_conversations` 계열 (정상 동작 중)
- 게시판 UI/디자인 변경
- 글 수정 기능 (설계에 없음 — 삭제 후 재등록이 현 모델)
- 관리자 대시보드에서 `board_posts` 관리
- `board_search`의 전량 조회 후 메모리 병합 방식 자체의 성능 개선 (§6.3에서 별건으로 기록)

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | **멱등 DDL 파일**: `supabase_board_posts.sql` — `CREATE TABLE IF NOT EXISTS` + 컬럼별 `ADD COLUMN IF NOT EXISTS`로 **부분 적용 상태에서 재실행해도 안전**하게. 설계 원본(`board-write-security.design.md:138-150`)의 CHECK 제약·기본값을 그대로 복원. 기존 3컬럼은 건드리지 않는다 | High | Pending |
| FR-02 | **DDL 적용**: Supabase SQL Editor에서 실행(anon 키로는 DDL 불가). 적용 후 8컬럼 전부 select 성공을 **실측으로** 확인 — 이번 실패가 "수동 실행을 했다고 믿었으나 안 됐다"에서 왔으므로 양성 확인이 완료 조건이다 | High | Pending |
| FR-03 | **종단 검증**: 실제 글 1건을 등록 → `/board` 목록 노출 → 상세 열람 → 비밀번호 삭제 → 목록에서 사라짐. 각 단계 HTTP 상태 기록. 검증용 글은 삭제로 정리 | High | Pending |
| FR-04 | **`board_recent` 병합**: `qa_conversations`(가드 필터 통과분) + `board_posts`(`status='active'`)를 `created_at` 역순 병합. 페이지네이션은 §6.2 참조 — 현재 `.range()` DB 페이지네이션이라 병합 시 재설계 필요 | High | Pending |
| FR-05 | **`board_categories` 합산**: 양쪽 카테고리 건수를 합산. `/board` 필터의 건수가 실제 목록과 일치해야 한다 | Medium | Pending |
| FR-06 | **프론트 렌더**: `public/index.html`의 미리보기는 `answer_preview`를 펼침 영역에 넣는데 사용자 글은 답변이 없다. 빈 펼침이 되지 않도록 처리(펼침 비활성 또는 안내 문구). `board.html`은 `source`/`nickname`을 이미 다룬다(`:763`) | Medium | Pending |
| FR-07 | **스키마 대조 점검**: 코드가 `board_posts`에서 select/insert하는 컬럼 집합과 실제 스키마를 비교. DB 접근이 필요하므로 CI(오프라인)에서는 스킵하고 `check_env.py` 계열의 운영 점검으로 두는 것이 현실적 — 방식은 Design에서 확정 | High | Pending |
| FR-08 | **조용한 실패 제거**: `board_search:1059`·`board_detail`의 `except Exception: pass`가 스키마 오류(42703)와 "테이블 미생성"을 구분하지 못한다. 전자는 **설정 오류라 조용히 넘기면 안 된다** — 최소한 `logger.warning`으로 계측 | Medium | Pending |
| FR-09 | **CLAUDE.md 규약**: 스키마 파일 없는 수동 테이블 생성 금지, `board_posts` 스키마 파일 위치, 배포 체크리스트의 DDL 항목은 **양성 확인 없이 완료 처리 금지** | Medium | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| Idempotency | DDL을 2회 실행해도 동일 결과, 오류 없음 | SQL Editor 2회 실행 |
| Safety | 기존 3컬럼(`id`·`category`·`created_at`)과 기존 행에 영향 0 | 실행 전후 행 수·컬럼 비교 (현재 0행이라 위험 낮음) |
| Security | anon에 필요한 최소 정책만 — `password_hash`가 anon SELECT로 새지 않을 것 | §5 Risk 참조, Design에서 정책 확정 |
| Correctness | `board_recent` 병합 후에도 `_anonymize()` 전 항목 적용 | 코드 리뷰 + 응답 검사 |
| Correctness | 목록·검색·카테고리 3경로의 건수가 서로 정합 | 종단 검증 시 대조 |
| Fail-safe | 스키마가 다시 어긋나도 **글쓰기는 500이되 목록은 살아 있을 것** (현 구조 유지) | 코드 리뷰 |
| Compatibility | `purge_expired_data()`의 `to_regclass` 가드와 충돌 없음 | SQL 리뷰 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] `supabase_board_posts.sql`이 저장소에 있고, 2회 연속 실행해도 오류 없음
- [ ] 8개 컬럼 전부 `select` 성공 (실측 스크립트 출력)
- [ ] 인덱스 3종 존재 확인
- [ ] `POST /api/board/write` **HTTP 201** + `board_posts` 행 1건 증가
- [ ] 등록한 글이 `/board` 목록·검색 결과·상세·**메인페이지 미리보기**에 노출
- [ ] 카테고리 필터 건수가 실제 목록 건수와 일치
- [ ] 잘못된 비밀번호 삭제 시 403, 올바른 비밀번호 시 200 + 목록에서 사라짐
- [ ] 검증용 글 정리 완료 (soft delete)
- [ ] 스키마 대조 점검이 현재 스키마에 대해 "일치" 보고
- [ ] `python3 test_offline_units.py` 통과 (기존 회귀 불변)

### 4.2 Quality Criteria

- [ ] DDL 적용이 기존 데이터에 영향 0건
- [ ] 병합된 목록에서 사용자 글도 `_anonymize()` 통과
- [ ] `except: pass` 잔존 0건 (게시판 경로)

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| **`password_hash`가 anon SELECT로 노출** | **High** | 조사 필요 | anon 키는 서버 전용이고 프론트에 없음을 확인했다(`public/`에 supabase 문자열 0건). 그래도 정책상 `password_hash`를 anon SELECT에서 제외하는 방법(뷰 또는 컬럼 권한)을 Design에서 검토. 현재 `select id`가 성공하므로 SELECT 정책이 열려 있거나 RLS가 꺼져 있다 — **어느 쪽인지부터 확정할 것** |
| **anon UPDATE 정책이 열려 있으면 누구나 남의 글을 고칠 수 있다** | High | Medium | soft delete가 UPDATE라 정책이 필요한데, 컬럼 단위 제한이 없으면 `question_text`까지 바뀐다. bcrypt 검사는 앱 단이라 RLS로는 못 막는다. RPC(`SECURITY DEFINER`)로 삭제를 감싸는 안을 Design에서 비교 — `abuse_guard`가 같은 패턴을 이미 쓴다 |
| DDL이 또 부분만 적용된다 | High | **Medium** | **이번 실패의 재현이다.** 완료 조건을 "실행했다"가 아니라 **"8컬럼 select 성공을 실측했다"** 로 둔다(FR-02). 멱등 DDL이라 재실행으로 복구 가능 |
| `board_recent` 병합으로 페이지네이션이 어긋난다 | Medium | Medium | §6.2 오버페치 방식 채택. 종단 검증에서 페이지 경계(1→2페이지) 항목 중복·누락을 육안 확인 |
| 병합으로 목록 응답이 느려진다 | Low | Medium | `board_search`가 이미 전량 조회 방식이라 선례가 있으나, `board_recent`는 **첫 화면 경로**라 같은 방식을 쓰면 안 된다. 오버페치는 `per_page`의 2배만 가져온다 |
| 답변 없는 글이 미리보기에서 빈 카드로 보인다 | Low | 확실 | FR-06. 펼침 UI가 답변 전제라 사용자 글은 펼침을 막거나 "답변 대기" 안내 |
| 검증용 글이 공개 게시판에 남는다 | Low | Low | soft delete로 정리. `status='deleted'`는 목록·검색에서 제외된다 |
| 스키마 점검이 CI에서 못 돈다 | Low | 확실 | DB 접근이 필요하므로 오프라인 CI에서는 원리적으로 불가. 운영 점검(`check_env.py` 계열)으로 두고 **CI에서 도는 것처럼 오해하지 않게** 문서에 명시 |

---

## 6. Architecture Considerations

### 6.1 파일 구조

```
supabase_board_posts.sql       ← FR-01: 신규 (기존 supabase_*.sql 관례)
api/index.py                   ← FR-04/05/08: board_recent·board_categories 병합, except 계측
public/index.html              ← FR-06: 미리보기 렌더
check_env.py 또는 신규 스크립트 ← FR-07: 스키마 대조 (방식 Design 확정)
CLAUDE.md                      ← FR-09
```

### 6.2 `board_recent` 병합 — 페이지네이션

현재는 `.range(offset, offset+per_page-1)`로 **DB가 페이지를 자른다.** 두 테이블을 병합하면 이 방식이 성립하지 않는다.

| 안 | 방식 | 평가 |
|----|------|------|
| A. 전량 조회 후 메모리 병합 | `board_search`가 쓰는 방식 | 코드 일관성은 있으나 **첫 화면마다 240+행 전송**. `board_recent`는 가장 빈번한 경로라 부적절 |
| **B. 오버페치 병합** | 각 테이블에서 `offset+per_page`만큼 가져와 병합·정렬·슬라이스, `total`은 각 `count="exact"` 합 | **권장.** 전송량이 페이지 크기에 비례. 표준 기법 |

동률 처리: `created_at`이 같으면 `id` 사전순으로 결정론적 정렬 — 페이지 경계에서 항목이 중복·누락되지 않게 한다(`dedupe_board.py::pick_representative`와 같은 이유).

### 6.3 별건 기록 — `board_search`의 전량 조회

`board_search`는 매 요청마다 조건에 맞는 **전량**을 가져와 메모리에서 자른다(`api/index.py:1062-1065`). 현재 240행이라 무증상이지만 코퍼스가 커지면 드러난다. 이번 범위 밖으로 두되, `board_recent`를 같은 방식으로 만들지 **않는** 근거로 기록한다.

### 6.4 조용한 실패 — 이 프로젝트 세 번째

| 사이클 | 실패 모드 | 증상 |
|--------|-----------|------|
| `chatbot-security` | fail-open 가드 | 가드가 죽어도 상담은 계속 — 무증상 |
| `board-duplicate-cleanup` | RLS DELETE 무성 차단 | "225/225 삭제" 출력 + 실제 0건 |
| **이번** | 42703을 `except: pass`가 삼킴 | 사용자 글이 검색에서 조용히 0건 |

셋 다 **예외도 로그도 남기지 않는다.** FR-08은 이 계보에 대한 대응이다 — CLAUDE.md의 "계측이 없으면 경로가 통째로 죽어도 아무도 모른다"와 같은 규약이다.

### 6.5 DDL은 사람이 실행해야 한다

anon 키로는 DDL이 불가능하고, 이는 `board-duplicate-cleanup`에서 확인한 DELETE 차단과 같은 계열이다. 실행 경로는 Supabase SQL Editor(`postgres` 역할). **따라서 "적용했다"를 자동 검증할 방법이 없고, 이번 드리프트가 정확히 그 틈에서 생겼다** — FR-02의 실측 확인이 이 사이클의 실질적 안전장치다.

---

## 7. Follow-up / Notes

### 7.1 `board-write-security` 사이클의 미완 상태

그 사이클은 Report까지 작성됐지만 배포 체크리스트가 미체크로 남았다. **문서상 완료와 실제 배포 사이에 간극이 있었고 아무도 몰랐다.** 이번 FR-09는 그 재발을 막는 규약이다 — DDL이 필요한 사이클은 "적용 실측"을 Definition of Done에 넣어야 한다.

### 7.2 사용자 글에 답변이 붙지 않는 구조

`board_posts`에 `answer_text`가 없어 등록된 질문은 답변 없이 남는다. 게시판이 "AI 상담 사례집 + 사용자 질문 게시판"의 혼합인데 후자에 응답 경로가 없다. 이번 범위 밖이지만 **제품 결정이 필요한 지점**이다 — 답변을 붙일지, 챗봇으로 유도할지.

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
| 수정 범위 | **스키마 복구 + 목록/카테고리 통합** | 스키마만, 스키마+조용한실패제거 |
| 재발 방지 | **스키마 파일 + 기동 시 점검** | 스키마 파일만, 복구만(별도 사이클) |
| DDL 방식 | **멱등**(`IF NOT EXISTS`) — 부분 적용 상태에서 재실행 안전 | 전체 재생성(`DROP`+`CREATE`, 데이터 손실 위험) |
| `board_recent` 페이지네이션 | **오버페치 병합** (§6.2 안 B) | 전량 조회 후 메모리 병합(`board_search` 방식) |

※ 사전 조사에서 두 가지가 초기 가정과 달랐음을 기록한다 — ① 결손은 `nickname` 1개가 아니라 **5개**이고, ② `/board` 본 목록은 `board_search`를 쓰므로 스키마만 고쳐도 사용자 글이 나타난다(구멍은 메인페이지 미리보기와 카테고리 필터). 선행 사이클 문서의 "목록·상세에서 전부 사라진다"는 검색·상세 경로만 본 부분 진단이었다.
