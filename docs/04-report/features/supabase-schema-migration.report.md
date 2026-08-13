# supabase-schema-migration 완료 보고서

> Plan: `docs/01-plan/features/supabase-schema-migration.plan.md`
> Design: `docs/02-design/features/supabase-schema-migration.design.md`
> Analysis: `docs/03-analysis/supabase-schema-migration.analysis.md`
> 기간: 2026-08-13 (1일)
> Commit: `aa607b4` → `f37a5d7` → PR #49 머지(`a7ff6b0`) → `f83d172`

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | laborconsult를 다른 앱과 공유하던 Supabase `public` 스키마에서 **전용 `laborconsult` 스키마**로 전면 이전 |
| 시작·완료 | 2026-08-13 (당일) |
| Match Rate | **95.1%** (103항목 대조) — 갭 5건 중 **4건 해소** |
| 코드 변경 | 19개 파일(신규 2), **+1,225/−335줄** (문서 제외) |
| 테스트 | 오프라인 **18종 전량 통과**, 신규 회귀 D6~D9 |
| 이전 대상 | 테이블 9종 · RPC 8종 · Storage 버킷 1 |

### Value Delivered

| 관점 | 계획 | 실제 결과 |
|------|------|-----------|
| **Problem** | `public.board_posts`가 **다른 앱의 테이블**(구 단위 권한·승인 사용자·관리자 모델)인데 이름만 같아 우리 코드가 자기 것으로 오인. `purge_expired_data()`가 그 앱의 게시글을 지우도록 작성돼 있었다 | 컬럼 3개(`id`·`category`·`created_at`)가 우연히 겹쳐 "스키마 드리프트"로 보였다. **Plan·Design·구현까지 간 뒤 `pg_policies`를 보고서야** 드러났다. pg_cron 미활성이라 실제 삭제는 없었음을 확인 |
| **Solution** | 전용 스키마로 이전하고 접속을 단일화 | 테이블 9종·RPC 8종·버킷을 `laborconsult`로. `SECURITY DEFINER` 8종의 `search_path`에서 `public` 제거. 접속부 5곳을 `make_supabase_client()` 하나로 |
| **Function/UX Effect** | 상담 저장·게시판·가드·첨부가 그대로 동작 | **게시판 글쓰기가 처음으로 작동한다** — 배포된 채 100% HTTP 500이었다. 프로덕션에서 등록 201 → 노출 → 상세 200 → 삭제 200 전 구간 통과 |
| **Core Value** | "우리 테이블인가"를 이름으로 판단하던 상태에서 **스키마 경계로 보장하는** 상태로 | 사고 메커니즘(`search_path`의 `public`)을 DB 실측 + CI 회귀 **이중 고정**. DB 전체가 저장소 DDL로 재현 가능해졌다 |

---

## 1. 산출물

### 1.1 DDL — 최종 상태 4파일

| 파일 | 변경 | 핵심 |
|------|------|------|
| `supabase_schema.sql` | +270/−? | `CREATE SCHEMA` · 대화 3종 · **`law_article_cache` 흡수** · 테이블 GRANT · Storage 정책 접두사 |
| `supabase_abuse_guard.sql` | 166줄 개편 | 전 객체 스키마 한정 · **`search_path = laborconsult, pg_temp`** |
| `supabase_board_posts.sql` | **신규** 151줄 | 게시판 · UPDATE 단방향 정책 · 컬럼 GRANT |
| `supabase_retention_purge.sql` | 284줄 개편 | `to_regclass` 가드 제거 · cron 스키마 한정 · service_role EXECUTE |

패치 3종(`supabase_fix_*.sql`·`_attachments_private.sql`)은 본문에 흡수하고 이력 표기만 남겼다.

### 1.2 코드

| 파일 | 내용 |
|------|------|
| `app/core/storage.py` | `make_supabase_client()` — 기본 스키마 `laborconsult`(fail-closed), 기동 로그, `public` 경고 |
| `api/index.py` | `_single_row()` 헬퍼 · 접속 단일 경로 |
| `app/config.py` · `app/core/legal_api.py` | 별도 `create_client` 제거 |
| `check_schema.py` | **신규** 189줄 — 테이블 9종·스키마·RPC 대조, 오류 6종 분류 |
| `dedupe_board.py` · `purge_storage_orphans.py` | 접속 단일 경로 |
| `test_offline_units.py` | +180 — D6~D9 |
| `.env.example` · `CLAUDE.md` | 변수명 경고 · 규약 |

---

## 2. 계획 대비 실측

| 지표 | 계획 | 실제 | 비고 |
|------|------|------|------|
| 이전 테이블 | 7 | **9** | `law_article_cache`·`storage_purge_queue`를 조사 중 추가 발견 |
| RPC | 4 | **8** | `storage_purge_*` 3종 + 트리거 함수 |
| DDL 파일 | 4 | **4** | 패치 3종 흡수 |
| 접속 생성부 | 4곳 예상 | **5곳** | `legal_api.py`가 L2 캐시용으로 별도 생성 중이었다 |
| Match Rate | ≥90% | **95.1%** | 갭 5건 중 4건 해소 |
| 오프라인 테스트 | — | 14 → **18** | D6~D9 |

---

## 3. 배운 것

### 3.1 소유권을 이름으로 판단하면 안 된다 — 세 번 연속 틀렸다

| # | 단정 | 실제 | 원인 |
|---|------|------|------|
| 1 | "`board_posts` 0행" | RLS가 anon에게 행을 가린 것 | `count`를 읽지 않고 `len(data)`로 판단 |
| 2 | "0행 = 쓸 수 없었다" | 남의 테이블이라 우리 글이 있을 리 없었다 | 1번 위에 쌓은 추론 |
| 3 | "우리 테이블의 드리프트" | **다른 앱의 테이블** | 소유권을 이름으로만 판단 |

셋 다 **확인 가능한 것을 확인하지 않고** 넘어갔다. 특히 3번은 `pg_policies` 한 번이면 즉시 드러났다.

결정적으로, 내 조사 방식 자체가 답을 제한했다 — **내가 기대하는 컬럼만 프로브했기 때문에 "일치 아니면 결손" 둘 중 하나로만 답이 나올 수 있었다.** "이건 다른 것이다"라는 답은 구조적으로 나올 수 없었다. 롤백 후 드러난 실제 컬럼(`district_id`·`title`·`content`·`is_pinned`·`author_id`)이 그 사실을 보여준다.

### 3.2 `search_path`가 사고의 실제 메커니즘이었다

```sql
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
```

`SECURITY DEFINER`는 정의자 권한으로 실행되고 **미지정 참조는 `search_path` 순서로 해석**된다. `purge_expired_data()`의 `DELETE FROM board_posts`가 남의 게시글을 지우려던 경로가 정확히 이것이다.

`public`을 목록에서 **빼는** 것이 핵심이다 — 남겨 두면 우리 스키마에 없는 이름이 조용히 흘러간다. `storage.objects`처럼 다른 스키마 객체는 `search_path` 의존 없이 항상 명시한다.

### 3.3 커스텀 스키마에는 자동 권한이 없다 — 같은 클래스로 두 번 걸렸다

| 회차 | 대상 | 증상 |
|------|------|------|
| 1 | **테이블** | RLS 정책만 만들고 GRANT 누락 → `qa_*`·`law_article_cache` 전부 `permission denied` |
| 2 | **함수** | `REVOKE ALL … FROM PUBLIC`이 service_role의 유일한 경로까지 지움 → `42501` |

`public` 스키마에서는 Supabase의 default privileges가 자동으로 채워 줘서 이 계층이 **보이지 않았다.** 두 번 걸린 뒤에야 CLAUDE.md를 "무엇을 빠뜨렸나"가 아니라 **"이 스키마엔 자동 부여가 없다"** 는 원리로 고쳐 적었다.

부수적으로 알게 된 것: `service_role`은 **BYPASSRLS일 뿐 superuser가 아니다.** 같은 이유로 자기가 소유하지 않은 함수에 GRANT를 줄 수 없어, 한 번 회수하면 SQL Editor로만 복구된다.

### 3.4 종단 검증이 유일하게 잡을 수 있는 결함이 있다

Gap 분석에서 G-1(게시판 글쓰기·삭제 종단)을 미검증으로 남겼다가 실행했더니 **상세만 HTTP 500**이었다.

```
postgrest-py 의 .maybe_single().execute() 는 0행일 때
응답 객체가 아니라 None 을 반환 → .data → AttributeError → 500
```

`board_detail`은 `qa_conversations`를 먼저 조회하는데 게시글 id로는 항상 0행이라, **사용자 글 상세는 한 번도 열린 적이 없었다.** 이 사이클이 만든 버그가 아니라 `board_posts`에 행이 생기기 전까지 도달 불가였던 기존 결함이다.

정적 분석·스키마 대조·단위 테스트 어느 것도 이걸 잡을 수 없었다. **"이 기능이 실제로 되는가"는 실행으로만 답할 수 있다.** 같은 함정이 5곳에 있어 `_single_row()`로 전수 봉인했다.

### 3.5 "빈 응답"은 성공과 실패를 구분하지 못한다

프로덕션 검증에서 `{"items":[],"total":0}`을 받았는데, 이것만으로는 **"연결 정상 + 데이터 0건"과 "Supabase 미연결 폴백"이 구분되지 않는다.** graceful degradation이 둘을 같은 모양으로 만든다.

이 프로젝트에서 반복된 조용한 실패와 같은 형태다 — RLS DELETE 무성 차단(200 OK + 빈 배열), fail-open 가드, 42703 삼킴. 결국 **실제 쓰기 1건**으로만 양성 신호를 얻을 수 있었다.

신규 코드 반영 자체는 부작용 없이 판별했다 — `maybe_single` 수정으로 없는 id 상세가 500→404가 되는 것을 discriminator로 썼다.

---

## 4. 검증 결과

### 4.1 스키마 (`check_schema.py`)

```
프로젝트 : exnloiyzmdzbhljwwxrs
스키마   : laborconsult
[공개 테이블] qa_sessions(4) · qa_conversations(8) · qa_attachments(8) ·
              law_article_cache(7) · board_posts(8)          전부 ✓
[잠긴 테이블] chat_quota · block_list · abuse_events ·
              storage_purge_queue                    전부 차단됨 ✓
[RPC]        abuse_unblock · abuse_summary                     ✓
✅ 스키마 일치
```

### 4.2 DB 실측 — 사고 메커니즘 봉인

```
purge_expired_data   security_definer=true  ["search_path=laborconsult, pg_temp"]
storage_purge_claim  security_definer=true  ["search_path=laborconsult, pg_temp"]
storage_purge_mark   security_definer=true  ["search_path=laborconsult, pg_temp"]
```

### 4.3 종단 검증

| 항목 | 프리뷰 | 프로덕션 |
|------|:------:|:--------:|
| CAPTCHA 200 → 등록 201 | ✅ | ✅ |
| `search`·`recent` 병합 노출 (`source=user`) | ✅ | ✅ |
| 카테고리 합산 | ✅ | ✅ |
| 상세 200 (닉네임·`answer` 빈 값) | ✅ | ✅ |
| 삭제 오답 403 → 정답 200 | ✅ | ✅ |
| 목록 소멸 + 상세 404 | ✅ | ✅ |

⑤가 설계의 핵심 통제다 — RLS UPDATE 정책(`USING status='active'` × `WITH CHECK status='deleted'`) + 컬럼 GRANT(`status`만)가 실제로 맞물린다. bcrypt 검증은 앱 단이라 RLS로 막을 수 없으므로, 이 조합이 내용 변조·되살리기를 차단하는 유일한 구조적 통제다.

검증글은 모두 soft delete로 정리했다.

### 4.4 기타

| 항목 | 결과 |
|------|------|
| 상담 저장 경로 | `ensure_session`·`save_conversation`·**세션 스냅샷 왕복** ✅ |
| 쿼터 RPC | `chat_guard_check` 4회 → 4번째 quota 차단 ✅ |
| 첨부 | 업로드 + 1시간 signed URL + `public_url` NULL 유지 ✅ |
| 첨부 파기 큐 | `purge_storage_orphans.py --dry-run` 큐 조회 성공 ✅ |
| 오프라인 테스트 | **18종 전량 통과** (D6~D9 신규) |

### 4.5 옛 프로젝트 원상복구

| 항목 | 결과 |
|------|------|
| 추가했던 컬럼 5종 제거 | ✅ `after_columns`에서 확인 |
| 그 앱의 정책 4개 | ✅ `{authenticated}` 원형 유지 |
| pg_cron | 미활성 — **그 앱 데이터 삭제 이력 없음** |

---

## 5. 미결·후속

| # | 항목 | 상태 |
|---|------|------|
| 1 | **pg_cron 미등록** — 등록해야 보유기간 파기가 자동 실행된다(`supabase_retention_purge.sql` §4). 지금 등록해도 삭제 대상 0건이라 무해 | ⏳ 운영 |
| 2 | **옛 프로젝트에 상담 원문 248건 잔존** — 이관·삭제 모두 하지 않았다. 그 프로젝트의 `purge_expired_data()`에는 여전히 스키마 미지정 `DELETE FROM board_posts`가 남아 있다(cron 미활성이라 자동 위험 없음, 수동 실행 시 다른 앱 게시글 삭제) | 🔴 방침 결정 필요 |
| 3 | G-4 쿼터 HTTP 배선(`_guard_chat_request` → `check_guard` → RPC) | ⏸ 이번 사이클에서 변경되지 않은 구간. RPC 실동작은 확인됨 |
| 4 | `board_posts`에 `answer_text`가 없어 사용자 글에 답변이 붙지 않는다 | ⏸ 제품 결정 |
| 5 | `board_search`의 전량 조회 후 메모리 슬라이스 | 보류 — 현 규모에선 무증상 |

---

## 변경 이력

| 버전 | 일자 | 내용 |
|------|------|------|
| 1.0 | 2026-08-13 | 완료 보고. Match Rate 95.1%, `laborconsult` 전용 스키마 이전(테이블 9·RPC 8·버킷 1), 접속 단일화, 회귀 D6~D9. 검증 중 `maybe_single()` 결함 5곳·커스텀 스키마 권한 누락 2건 발견·수정 |
