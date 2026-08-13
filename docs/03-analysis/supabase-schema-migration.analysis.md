# Supabase 전용 스키마 이전 Gap Analysis Report

> **Summary**: 설계 대조 103항목 중 98 일치 — **Match Rate 95.1%**. 갭 5건(MISSING 2·PARTIAL 3). 최대 갭은 **게시판 글쓰기·삭제 종단 미검증(E3)** — 이 사이클이 출발한 바로 그 기능이다. 별도로 Match Rate가 못 잡는 영역을 6항목 실측했다.
>
> **Project**: laborconsult
> **Analyst**: 설계 대조 + 독립 사각지대 점검
> **Date**: 2026-08-13
> **Plan**: [supabase-schema-migration.plan.md](../01-plan/features/supabase-schema-migration.plan.md)
> **Design**: [supabase-schema-migration.design.md](../02-design/features/supabase-schema-migration.design.md)
> **Commit**: `aa607b4` (브랜치 `feat/supabase-schema-migration`, 미머지)

---

## 1. 분석 개요

| 항목 | 내용 |
|------|------|
| 대조 대상 | 설계 §1.1~1.2, §2.1~2.3, §3.2~3.3, §4.1~4.6, §5.1~5.3, §6.1~6.3, §7, §8, §9, §10, §12 |
| 구현 파일 | `supabase_schema.sql`·`_abuse_guard`·`_board_posts`·`_retention_purge`(4) · `app/core/storage.py` · `app/config.py` · `app/core/legal_api.py` · `check_schema.py`(신규) · `dedupe_board.py` · `purge_storage_orphans.py` · `test_offline_units.py` · `.env.example` · `CLAUDE.md` |
| 대조 방식 | 설계 요구 1건 = 항목 1개. 실제 행·실행 결과를 읽어 판정 |
| 보완 검증 | 설계 대조와 **별개로** 사각지대 6항목 실측 (§6) |

## 2. 종합 점수

| 구분 | 수 | 비율 |
|------|---:|-----:|
| **MATCH** | **98** | **95.1%** |
| PARTIAL | 3 | 2.9% |
| MISSING | 2 | 1.9% |
| **총 대조 항목** | **103** | 100% |

**Match Rate = 98 / 103 = 95.1%** → 설계-구현 동기화 양호(≥90%), Act 반복 불요.

| 섹션 | 항목 | MATCH | PARTIAL | MISSING |
|------|----:|------:|--------:|--------:|
| §1.1 Design Goals | 4 | 4 | 0 | 0 |
| §1.2 Design Principles | 3 | 3 | 0 | 0 |
| §2.1 전체 구조 | 2 | 2 | 0 | 0 |
| §2.2 접속 단일화(5곳+위치) | 6 | 6 | 0 | 0 |
| §2.3 파일 통합 처리(9파일) | 9 | 9 | 0 | 0 |
| §3.2 search_path 채택안 | 3 | 3 | 0 | 0 |
| §3.3 검사 방법(D6) | 1 | 1 | 0 | 0 |
| §4.1 파일 구성·순서 | 2 | 2 | 0 | 0 |
| §4.2 스키마 생성·노출 | 3 | 2 | 1 | 0 |
| §4.3 멱등성 결함 수정 | 4 | 4 | 0 | 0 |
| §4.4 law_article_cache RLS | 2 | 2 | 0 | 0 |
| §4.5 Storage 정책 이름 | 2 | 2 | 0 | 0 |
| §4.6 purge 재작성 | 2 | 2 | 0 | 0 |
| §5.1 make_supabase_client | 4 | 4 | 0 | 0 |
| §5.2 기동 계측 | 1 | 1 | 0 | 0 |
| §5.3 .env 변수명 | 4 | 4 | 0 | 0 |
| §6.1 대조 범위 | 2 | 2 | 0 | 0 |
| §6.2 스키마 확인 | 2 | 2 | 0 | 0 |
| §6.3 RPC 존재 확인 | 2 | 2 | 0 | 0 |
| §7 테스트 D5~D9 · E1~E5 | 10 | 7 | 2 | 1 |
| §8 파일별 변경 명세 | 12 | 12 | 0 | 0 |
| §9 구현 순서(8단계) | 8 | 7 | 0 | 1 |
| §10 Risks mitigation | 8 | 8 | 0 | 0 |
| §12 결정 기록 | 7 | 7 | 0 | 0 |
| **합계** | **103** | **98** | **3** | **2** |

---

## 3. 핵심 대조 결과

### 3.1 §2.2 접속 단일화 — 전수 확인

`create_client(` 직접 호출은 **`make_supabase_client()` 내부 1곳뿐**이다.

| 호출부 | 상태 |
|--------|------|
| `app/config.py:126` | ✅ `make_supabase_client()` |
| `app/core/legal_api.py:153` | ✅ 〃 (L2 법령 캐시 — 별도 클라이언트였던 지점) |
| `check_schema.py:163` | ✅ 〃 |
| `dedupe_board.py:421` | ✅ 〃 |
| `purge_storage_orphans.py:70` | ✅ 〃 |

`api/index.py::_get_supabase()`도 `config.supabase`를 반환하므로 같은 경로다. Supabase 접근 표면 전수(`.table()` 36 · `.rpc()` 8 · `.storage.` 3)가 이 하나의 클라이언트를 쓴다.

### 3.2 §3.2 search_path — 실측 확인

DB 실측(`pg_proc.proconfig`):

```
purge_expired_data   true  ["search_path=laborconsult, pg_temp"]
storage_purge_claim  true  ["search_path=laborconsult, pg_temp"]
storage_purge_mark   true  ["search_path=laborconsult, pg_temp"]
```

`public` 부재. 회귀 D7이 DDL 8건 전부를 CI에서 고정한다. `storage.objects`는 search_path 의존 없이 `storage.`로 명시(§3.2 예외 조항 준수).

### 3.3 §4.3 멱등성 — 4항목 전부

| 항목 | 확인 |
|------|------|
| `CREATE INDEX IF NOT EXISTS` | 8/8 |
| `CREATE TABLE IF NOT EXISTS` | 9/9 |
| `DROP POLICY` + `CREATE POLICY` | 15/15 (schema 12 · board_posts 3) |
| `DROP TRIGGER` + `CREATE TRIGGER` | 1/1 |

### 3.4 §4.6 purge 재작성

`to_regclass` 잔존 1건은 **주석**(제거 사실을 설명하는 문구)이고 실행문에는 없다. `DELETE FROM laborconsult.board_posts`(:187), cron 등록도 `laborconsult.purge_expired_data(365, 90)`로 스키마 한정.

### 3.5 §7 D5~D9 — 5종 전부 CI 등록

`test_offline_units.py::main()` 476~480행에 등록. `.github/workflows/tests.yml:37`이 이 스위트를 돌린다. 실행 결과 18종 전량 통과.

---

## 4. 갭 목록

### 🟡 Medium

#### G-1. §7 E3 — 게시판 글쓰기·삭제 종단 미검증 (MISSING)

- **설계**: §7 E3 — "글쓰기 201 → 노출 → 삭제 200"
- **구현**: 수행하지 않았다. `board_posts` 테이블·정책·컬럼 권한은 실측했으나, `POST /api/board/write` → `POST /api/board/{id}/delete` HTTP 경로를 한 번도 통과시키지 않았다.
- **왜 중요한가**: **이 사이클이 출발한 문제가 정확히 그 기능이다.** 게시판 글쓰기는 배포된 채 100% HTTP 500이었고, 그것을 고치려다 이름 충돌을 발견해 여기까지 왔다. 스키마는 맞췄지만 "이제 실제로 글이 써지는가"는 아직 답하지 않았다.
- **미검증 구간**: CAPTCHA(HMAC) → IP rate-limit → 입력 검증 → bcrypt → INSERT → soft delete UPDATE. 특히 **UPDATE 정책(`USING status='active' WITH CHECK status='deleted'`) + 컬럼 GRANT(`status`만)** 조합은 설계의 핵심 통제인데 실동작 확인이 없다.
- **조치**: 후속 — 배포 후 프로덕션에서 1건 등록·삭제. 로컬 `TestClient`로도 가능하나 CAPTCHA 토큰 발급이 선행돼야 한다.

#### G-2. §9 8단계 — Vercel 환경변수·배포·프로덕션 재검증 미완 (MISSING)

- **설계**: §9 7단계 "Vercel 환경변수 갱신 → 배포 → 프로덕션 종단 재검증"
- **구현**: 로컬 `.env`만 갱신. Vercel 대시보드는 미갱신.
- **영향**: **현재 프로덕션은 Supabase 기능이 전부 꺼진 상태다.** `SUPABASE_URL`/`SUPABASE_KEY`가 옛 프로젝트를 가리키거나 미설정이면 상담 저장·게시판·쿼터·첨부가 조용히 비활성이고, 챗봇 답변만 동작한다. 설계 §10이 "누락 시 프로덕션만 조용히 비활성"으로 High 위험으로 잡아둔 항목이다.
- **조치**: 배포 전 필수. 이 사이클의 실질적 완료 조건.

### 🔵 Low

#### G-3. §4.2 — 설계가 테이블 GRANT를 누락했다 (PARTIAL)

- **설계**: §4.2는 `CREATE SCHEMA` + `GRANT USAGE ON SCHEMA`만 적었다.
- **실제**: 그것만으로는 **전부 `permission denied`** 였다(적용 검증에서 실측). 커스텀 스키마에는 Supabase의 default privileges가 적용되지 않아 테이블마다 `GRANT SELECT, INSERT …`가 필요하다.
- **구현**: §5-1 절을 신설해 4테이블에 GRANT 부여 + 검증 SQL ④ 추가.
- **판정 근거**: 구현이 옳고 설계가 불완전했다. **설계대로만 적용했다면 배포가 깨졌을 것**이므로 단순 "긍정적 추가"가 아니라 설계 결함으로 계상한다.
- **교훈**: RLS 정책(어느 **행**)과 GRANT(**접근 자체**)는 다른 계층인데, `public` 스키마에서는 Supabase가 GRANT를 자동으로 채워 그 구분이 보이지 않았다. 스키마를 옮기니 드러났다.

#### G-4. §7 E4 — 쿼터 검증이 HTTP 경로가 아니다 (PARTIAL)

- **설계**: "DAILY_CHAT_QUOTA=3에서 4번째 요청 429"
- **구현**: `chat_guard_check` RPC를 직접 4회 호출해 4번째 `{'reason': 'quota', 'allowed': False}` 확인.
- **검증된 것**: RPC가 `laborconsult` 스키마의 `chat_quota`·`block_list`를 정확히 읽고 쓴다 — 이 사이클이 바꾼 계층은 완전히 확인됐다.
- **미검증**: `_guard_chat_request()` → `check_guard()` → RPC 배선. 다만 이 배선은 이번 사이클에서 **변경되지 않았고**(chatbot-security 사이클 산출물) 클라이언트만 교체됐다.
- **조치**: 후속 — 프로덕션 검증 시 함께.

#### G-5. §7 E2 — 게시판 상세(정상 글) 미확인 (PARTIAL)

- **설계**: "게시판 4경로" (목록·카테고리·검색·상세)
- **구현**: 목록·카테고리·검색 3경로 200 확인. 상세는 **404 차단만** 확인(합성 대화 딥링크).
- **원인**: 새 DB라 공개 대화가 0건이라 정상 상세를 열 대상이 없다.
- **조치**: G-1·G-2 해소 시 자동으로 함께 검증된다.

---

## 5. 설계 O / 구현 X · 구현 O / 설계 X

### 5.1 설계에만 있던 것

| 항목 | 설계 위치 | 상태 |
|------|-----------|------|
| E3 글쓰기·삭제 종단 | §7 | ⏸ 후속 (G-1) |
| Vercel 갱신·배포·프로덕션 검증 | §9-7 | ⏸ 후속 (G-2) |
| E4 HTTP 경로 쿼터 | §7 | 🔶 RPC 직접으로 대체 (G-4) |
| E2 정상 상세 | §7 | 🔶 데이터 부재 (G-5) |

### 5.2 구현에만 있던 것 (긍정적 추가 8건)

| # | 추가 | 위치 | 가치 |
|---|------|------|------|
| **P-1** | **테이블 GRANT 4종 + 검증 SQL ④** | `supabase_schema.sql:168-171`,`226-` | **없으면 전부 permission denied.** 설계 누락 보완(G-3) |
| P-2 | `check_schema.py::_classify()` — 오류를 원인별 6종으로 분류 | `:64-79` | `permission denied`(GRANT 누락)와 `42703`(컬럼 결손)은 조치가 다르다. 뭉뚱그리면 이번 발견을 못 했다 |
| P-3 | 잠긴 테이블 4종을 **차단됨이 정상**으로 판정 | `:110-127` | 설계 §6.1은 "직접 조회 불가라 RPC로 대신"이라 했으나, 차단 자체를 양성 신호로 쓰는 편이 이중 방어를 직접 검증한다 |
| P-4 | `storage_purge_queue`를 잠긴 목록에 포함 | `:53` | 설계 §6.1 표에는 없었다 |
| P-5 | 각 DDL 말미 검증 SQL (`pg_policies`·`column_privileges`·`proconfig`) | 4파일 | anon으로 확인 불가한 계층을 사람이 눈으로 보게 |
| P-6 | `ON CONFLICT (id) DO UPDATE SET public = false` | `supabase_schema.sql:196` | 버킷이 공개로 만들어져 있어도 비공개로 수렴 (기존은 `DO NOTHING`) |
| P-7 | 흡수된 패치 3파일에 이력 표기 | `supabase_fix_*.sql` | 삭제하지 않고 "신규 환경에 불필요" 명시 |
| P-8 | `.env.example`에 `NEXT_PUBLIC_*` 경고 | `:44-48` | 이번에 실제로 겪은 함정 |

---

## 6. Match Rate가 못 잡는 영역 — 독립 실측

> CLAUDE.md 규약: "Match Rate가 90%를 넘어도 그대로 배포하지 말 것."

| # | 점검 | 결과 |
|---|------|------|
| **B1** | 코드에 `public` 스키마 직접 참조 | **0건** — grep 전수 |
| B2 | Supabase 접근 표면이 전부 단일 클라이언트 경유 | ✅ `.table()` 36 · `.rpc()` 8 · `.storage.` 3 전부 |
| B3 | Storage가 스키마 경계 밖인 영향 | 무해 — 버킷 이름(`chat-attachments`)으로 격리, 정책도 `bucket_id` 스코프 |
| B4 | CI가 D6~D9를 실제로 돌리는가 | ✅ `.github/workflows/tests.yml:37` |
| **B5** | `SUPABASE_SERVICE_ROLE_KEY` | **미설정** — `purge_storage_orphans.py`가 동작 불가(§7.1) |
| **B6** | 옛 프로젝트의 laborconsult 데이터 | **248건 잔존** — 실제 상담 원문 포함(§7.2) |

B1이 이번 사이클의 최대 리스크였다. 스키마 경계는 코드가 `public`을 명시적으로 부르지 않을 때만 성립하는데, 설계는 "접속 옵션으로 고정한다"만 답하고 "본문에 `public.` 참조가 없는가"는 답하지 않았다 — 전수 확인했다.

---

## 7. 남은 한계

### 7.1 개인정보 파기의 절반이 비어 있다 (B5)

`purge_expired_data()`는 파일 경로를 큐에 적재만 하고, 실제 삭제는 `purge_storage_orphans.py`가 Storage API로 한다. 그런데 **`SUPABASE_SERVICE_ROLE_KEY`가 미설정**이라 그 스크립트가 동작하지 않는다(anon은 `storage.objects` DELETE 정책이 없다).

새 프로젝트라 아직 파기 대상이 없어 무증상이지만, 개인정보처리방침 제5항 이행은 **두 축이 모두 돌아야** 성립한다. 이번 사이클 범위 밖(Plan §2.2 Out of Scope)이나 운영 항목으로 남는다.

### 7.2 옛 프로젝트에 상담 원문 248건이 남아 있다 (B6)

사용자가 "테스트용"으로 확인해 이관하지 않았고, **삭제하지도 않았다.** 옛 프로젝트에 그대로 있어 필요하면 회수할 수 있는 상태다. 다만 실제 상담 질문·답변이 포함돼 있고 그 프로젝트에는 laborconsult의 보존기간 purge가 더 이상 등록되지 않을 것이므로, **보관/삭제 방침을 별도로 정해야 한다.**

아울러 그 프로젝트의 `purge_expired_data()` 함수에는 여전히 `DELETE FROM board_posts` 절이 남아 있다(스키마 미지정). pg_cron 미활성이라 자동 위험은 없지만 수동 실행 시 다른 앱의 게시글을 지운다.

### 7.3 이번 사이클이 고치지 않은 것

- `board_posts`에 `answer_text`가 없어 사용자 글에는 답변이 붙지 않는다 — 제품 결정 필요(직전 사이클 Plan §7.2)
- `board_search`의 전량 조회 후 메모리 슬라이스 — 현재 규모에선 무증상

---

## 8. 결론

| 판정 | 근거 |
|------|------|
| **Match Rate 95.1%** — Act 반복 불요 | 90% 기준 충족 |
| **사고 메커니즘은 봉인 확인** | `search_path`에 `public` 부재를 DB 실측 + CI 회귀(D7) 이중 고정 |
| **배포는 아직 하면 안 된다** | G-2(Vercel 미갱신) 미해소 시 프로덕션이 조용히 비활성 |
| **G-1이 실질 미완** | 이 사이클이 출발한 기능(게시판 글쓰기)의 종단 검증이 없다 |

후속 이월: **G-2 → G-1 → G-5·G-4** 순. G-2 없이는 나머지를 프로덕션에서 확인할 수 없다.

---

## 9. 관련 문서

- Plan: [supabase-schema-migration.plan.md](../01-plan/features/supabase-schema-migration.plan.md)
- Design: [supabase-schema-migration.design.md](../02-design/features/supabase-schema-migration.design.md)
- 대체된 사이클: [board-posts-schema-fix.plan.md](../01-plan/features/board-posts-schema-fix.plan.md) — 전제 무효(타 앱 테이블), 산출물은 이번에 승계
- 선행 사이클: `chatbot-security`(RPC·fail-open 규약) · `board-duplicate-cleanup`(RLS 무성 차단 실측)
