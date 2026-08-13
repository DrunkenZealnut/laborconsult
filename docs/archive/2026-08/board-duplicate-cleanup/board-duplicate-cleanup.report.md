# board-duplicate-cleanup 완료 보고서

> Plan: `board-duplicate-cleanup.plan.md`
> Design: `board-duplicate-cleanup.design.md`
> Analysis: `board-duplicate-cleanup.analysis.md`
> 기간: 2026-08-12 ~ 2026-08-13 (2일)
> Commit: `dc98e0d` (PR #47 — 정리 실행 + 가드 도입) → `a0602da` (PR #48 — 갭 6건 해소 + 단일 출처화 + 아카이브) → CodeRabbit 리뷰 반영분

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | 공개 질문게시판 중복 225건 정리 + 합성/테스트 대화의 게시판 유입을 차단하는 4단 가드 |
| 시작·완료 | 2026-08-12 → 2026-08-13 |
| Match Rate | **96.2%** (104항목 대조, MATCH 100) — 갭 6건 **전부 해소** |
| 코드 변경 | 8개 파일(신규 1), **+703/−14줄** (문서 제외) |
| 테스트 | 오프라인 단위 **13종 전량 통과**, 신규 D1~D4 (+136줄) |
| 데이터 | 공개 게시판 463 → **238건** (225건 하드 삭제, 오삭제 0) |

### Value Delivered

| 관점 | 계획 | 실제 결과 |
|------|------|-----------|
| **Problem** | 공개 463건 중 225건(48.6%)이 같은 질문의 반복. 원인은 사용자 오조작이 아니라 `benchmark_pipeline.py`가 `bench_*` 세션으로 프로덕션 Supabase에 그대로 기록하는 구조 — 합성/테스트가 **323건(69.8%)** | 진단이 데이터와 정확히 일치. 완전일치 239 vs 느슨일치 238로 **차이 1건** — 사람이 비슷하게 다시 쓴 게 아니라 같은 문자열의 재실행이었다 |
| **Solution** | ① 일회성 정리 스크립트(dry-run 기본 + 백업 의무) ② `save_conversation()` 초크포인트에 예약 접두사 가드 | 가드를 **판정 3곳(G-A/G-B/G-C) + 집행 1곳(G-D)** 으로 확장. 접두사 단독으로는 HTTP e2e(서버가 hex12 발급)를 못 잡는다는 실측에서 G-B가 추가됐다 |
| **Function/UX Effect** | 게시판 첫 페이지의 질문 반복 소멸, 14개 카테고리 전 영역 유지 | 463 → **238건**, 카테고리 **14종 전부 잔존**, 첨부 고아 0. 현재 공개 240건(= 238 + 배포 후 실사용 2건)이고 중복 그룹은 검증 질문 재요청 1개뿐 |
| **Core Value** | 게시판이 "테스트 로그 덤프"에서 "읽을 만한 상담 사례집"으로 전환 + 재발 경로 봉인 | 배포 후 벤치마크 1회 실행 실측: 전체 245→246 **저장은 정상**, 공개 **238 불변**, 상세 딥링크 **404**. 정리가 일회성으로 끝나는 것이 실측으로 확인됐다 |

---

## 1. 산출물

### 1.1 코드

| 파일 | 구분 | 내용 |
|------|------|------|
| `dedupe_board.py` | **신규** (443줄) | 정규화·그룹핑·대표선정·백업·배치 DELETE·검증·SQL 폴백·고아세션 정리 |
| `app/core/storage.py` | +65 | `PUBLIC_EXCLUDE_KEYS`/`is_public_excluded` **단일 출처**, `SYNTHETIC_SESSION_PREFIXES`, G-C 스탬프 |
| `api/index.py` | +47/−14 | `_is_synthetic_request()`(G-B 진리표), `_fetch_qa_public()`, 제외 계약을 storage에서 import(G-D) |
| `app/core/pipeline.py` | +7 | `guard_ctx is None or guard_ctx.synthetic` → `metadata.synthetic` (G-A) |
| `app/core/abuse_guard.py` | +4 | `GuardContext.synthetic` 필드 |
| `test_offline_units.py` | +136 | D1 정규화 · D2 대표선정 · D3 합성 판정+원본 비변형 · D4 제외 키 계약 |
| `.gitignore` | +4 | `backup_board_dedupe_*.json` · `dedupe_board_*.sql` (둘 다 상담 원문·UUID 포함) |
| `CLAUDE.md` | +11 | 제외 키 4종 계약 · 판정 3중 구조 · RLS DELETE 함정 · CASCADE 지뢰 |

### 1.2 데이터

| 대상 | 결과 |
|------|------|
| `qa_conversations` 공개 | 463 → **238건** (−225) |
| 삭제 방식 | 생성 SQL을 Supabase SQL Editor에서 실행 (RLS 우회, 영구 권한 확대 없음) |
| 백업 | `backup_board_dedupe_20260812_121212.json` 1.2MB / 225건, 쓰기 후 재독 검증 |
| 생성 SQL | `dedupe_board_20260812_121212.sql` — `DELETE ... IN (...)` 5문(50×4+25), `BEGIN;`/`COMMIT;` |
| 카테고리 | **14종 전부 잔존** (임금·수당 40 / 휴가·휴일 35 / 퇴직금 24 …) |
| 첨부 CASCADE | 0건 (사전 실측대로) |
| 고아 세션 | 85개 잔존 — `--purge-sessions` 미사용, 365일 보존기간 purge 대상 |

---

## 2. 계획 대비 실측

| 지표 | 계획 | 실제 | 비고 |
|------|------|------|------|
| 삭제 건수 | 225 | **225** | 정확 일치 |
| 유지 건수 | 238 | **238** | 유지 ID 집합이 설계상 대표 선정 결과와 완전 일치 |
| 카테고리 잔존 | 14 | **14** | |
| 오삭제 | 0 | **0** | 백업 225건 전부가 "동일 질문 그룹의 비최신 항목" |
| 가드 수 | 2 (FR-05/06) | **4** (G-A~G-D) | FR-07 미결 항목이 Design에서 G-B로 확정 |
| 삭제 경로 | PostgREST DELETE | **SQL Editor** | RLS 무성 차단 발견에 따른 설계 보정(§5.8) |
| Match Rate | ≥90% | **96.2%** | 갭 6건 전부 해소 |

---

## 3. 배운 것

### 3.1 RLS는 DELETE를 "권한 오류"가 아니라 "0건 일치"로 처리한다

이번 사이클 최대 발견이다. `qa_conversations`의 anon 정책은 `INSERT`/`SELECT`만 부여돼 있는데,
PostgREST는 DELETE에 **200 OK + 빈 배열**을 반환한다. 첫 `--apply`가 **"225/225 삭제"를 출력하고
실제로는 0건**을 지웠다.

```python
try:
    sb.table("qa_conversations").delete().in_("id", batch).execute()   # ← 예외 없음
    done += len(batch)                                                  # ← 거짓 성공
except Exception: ...                                                   # ← 절대 안 걸림
```

**Supabase 쓰기 스크립트는 예외가 아니라 `len(res.data)` 반영 행 수로 성공을 판정해야 한다.**
`try/except`는 이 실패 모드에 대해 아무 방어력이 없다.

대응으로 `RLSBlocked` 예외 + SQL Editor용 `.sql` 생성 경로를 넣었다. **anon에 DELETE 정책을
부여하는 안은 기각** — 일회성 정리를 위해 상시 삭제 권한을 여는 것은 비대칭이고, 키 유출 시
상담 이력 전체가 삭제 가능해진다.

### 3.2 "음성 결과"를 검증할 땐 그 일이 실제로 일어났는지부터 확인한다

가드 작동 검증(게시판 건수 불변)에서 `benchmark_pipeline.py --limit 3`을 돌렸는데,
`load_existing_results()`의 resume 로직이 기존 116건을 전부 "이미 완료"로 건너뛰어
**파이프라인이 한 번도 실행되지 않았다.** 건수 불변을 "가드가 막았다"로 읽었으면 오판이었다 —
아무것도 저장하지 않았으니 건수가 안 변하는 게 당연했다.

결과 파일을 치운 뒤에야 실제 저장이 일어났고(245→246), 그제야 "저장은 되는데 공개는 안 된다"는
**진짜 음성**을 확인할 수 있었다. 변화 없음을 근거로 삼는 검증은 항상 이 함정을 갖는다.

### 3.3 가드는 여럿이 판정하고 하나가 집행한다 — 그리고 부하는 고르게 지지 않는다

설계 초안은 G-C(예약 접두사)가 `cmp_* 51건, verify_* 등`을 담당한다고 적었으나 **사실이 아니었다.**
`/simplify` 리뷰에서 드러난 실제 구조:

- `cmp_*`는 `compare_llm_models.py`가 `guard_ctx` 없이 파이프라인을 부르는 **G-A 케이스**
- `verify_*`·`eval_*`는 저장소에 사용처 **0건**
- 웹 경로는 `abuse_guard._SESSION_ID_RE`가 `_`를 받지 않아 클라이언트가 `test_foo`를 보내도 폐기하고 hex12를 재발급

즉 예약 접두사 세션 집합 = `guard_ctx is None` 집합이고, **G-C가 단독으로 잡는 케이스는 0건**이다.
부하를 지는 것은 G-A 하나다.

기록으로 남긴 이유는 반대 방향의 오독을 막기 위해서다 — "G-C가 접두사를 다 잡으니 G-A는 중복"이라
판단해 **G-A를 지우면 커버리지가 통째로 사라진다.** 백스톱이 주 방어선처럼 보이는 착시다.

### 3.4 판정 불가는 "합성"이 아니라 "실사용"으로 떨어뜨려야 한다

G-B(`_is_synthetic_request`)는 **양성 검출만** 한다. "프로덕션임을 증명하지 못하면 합성"으로
설계했다면 `VERCEL_ENV`가 누락된 순간 모든 실사용 대화에 `synthetic`이 찍혀 **게시판이 조용히
얼어붙는다.** 에러도 로그도 나지 않으므로 발견까지 몇 주가 걸린다.

진리표 5행 중 결정적인 한 행:

| 상황 | `VERCEL_ENV` | client IP | 판정 |
|------|--------------|-----------|:----:|
| **프로덕션 + env 누락** | 없음 | 공인 | **실사용** ✅ |

fail-open 가드의 실패는 조용하다는 것이 chatbot-security 사이클의 교훈이었고, 여기서도 같은 규칙을
적용해 배포 후 **양성 검증 2단계를 의무화**했다.

### 3.5 "재선언 + 대조 테스트"보다 "단일 출처 + import"가 낫다

초안은 `dedupe_board.py`가 FastAPI를 import하지 않는다는 이유로 `PUBLIC_EXCLUDE_KEYS`를
재선언하고, `api/index.py` 소스를 파싱해 두 집합을 대조하는 테스트(D4)로 드리프트를 막았다.
동작은 했지만 소스 파싱 테스트는 깨지기 쉽다.

`/simplify`에서 `app/core/storage.py`가 **FastAPI·pipeline·API 키 어디에도 의존하지 않아
셋 모두가 import할 수 있는 유일한 지점**임을 확인하고 단일 출처로 옮겼다. D4는 소스 파싱 대신
`SCRIPT_KEYS is PUBLIC_EXCLUDE_KEYS` 동일성 단언으로 바뀌었다 — 대조가 아니라 구조적 보장이다.

같은 원리를 생성 SQL에도 적용했다. 제외 조건을 손으로 나열하면 키가 늘 때 SQL이 조용히 틀린
검증문을 담는데, 이제 `PUBLIC_EXCLUDE_KEYS`에서 생성한다.

### 3.6 `--purge-sessions`는 CASCADE 지뢰다

`qa_conversations.session_id`가 `ON DELETE CASCADE`라 세션을 지우면 그 세션의 **남은 대화까지
사라진다.** 벤치마크 세션 하나가 대화 4건을 갖고 그중 1건만 유지 대상인 상황이 실제로 있었다.

방어로 삭제 직전 세션별 잔여 대화 수를 재조회한다. 세션별 개별 왕복(178세션 × 2~3회)은
`in_()` 배치보다 훨씬 느리지만 의도적이다 — 배치 응답이 페이지 한계에서 잘리면 살아있는 세션이
고아로 오판돼 유지 대상이 증발한다. **틀리는 비용이 데이터 파괴이고 이득이 수십 초면 교환이
성립하지 않는다.**

### 3.7 같은 클래스의 버그는 형제 함수에 그대로 남는다

§3.1의 RLS 발견은 `_delete_batches()`를 고치는 것으로 끝났다고 생각했다. CodeRabbit 리뷰가
`_purge_orphan_sessions()`를 지적하면서 확인해 보니, **같은 파일 안의 형제 함수가 정확히 그
버그를 그대로 갖고 있었다.**

```python
# _delete_batches — 고침
affected = len(res.data or [])
if affected == 0:
    raise RLSBlocked(...)

# _purge_orphan_sessions — 안 고쳐져 있었다
sb.table("qa_sessions").delete().eq("id", sid).execute()
done += 1                                    # ← 예외 없음 = 성공으로 간주
```

`qa_sessions`의 anon 정책도 `INSERT`/`SELECT`/`UPDATE`뿐이라(`supabase_schema.sql:47-49`)
DELETE가 똑같이 조용히 차단된다. 즉 `--purge-sessions`는 **"85건 정리 완료"를 출력하고 0건을
지우는** 상태였다. 이번 사이클에서 이 옵션을 쓰지 않은 덕에 드러나지 않았을 뿐이다.

교훈은 발견 자체가 아니라 **발견을 적용하는 범위**다. "이 실패 모드를 고쳤다"가 아니라
"이 실패 모드가 가능한 지점을 전부 찾았다"여야 했는데, 같은 파일 안조차 훑지 않았다.
`§3.1`의 서술이 "고쳤다"로 끝나 있어 **다 고쳤다는 잘못된 신호**를 준 것도 같은 유형이다
(textbook 사이클의 "주석이 작동한다는 잘못된 신호를 줬다"와 동형).

CodeRabbit은 이 지점을 **TOCTOU 원자성 문제**로 지적했는데, 그 처방(단일 트랜잭션 RPC)은
맞지만 전제가 어긋나 있었다 — anon 키로는 DELETE가 **애초에 일어나지 않으므로** 경합 창을
논하기 전에 무성 실패가 먼저다. 지적된 라인은 옳았고 진단은 절반만 맞았다.

---

## 4. 가드 최종 구성

| 가드 | 위치 | 판정 근거 | 성격 | 담당 |
|------|------|-----------|------|------|
| **G-A** | `pipeline.py` `conv_metadata` 조립부 | `guard_ctx is None` | **광의 규칙 — 주 방어선** | 비웹 호출 전부 (`bench_*` 225, `cmp_*` 51, `test_*` 9, CLI) |
| **G-B** | `api/index.py::_guard_chat_request` | 비프로덕션 요청(`VERCEL_ENV`·loopback) | 양성 검출 | HTTP e2e (hex12 발급분 32건 유형) |
| **G-C** | `storage.py::save_conversation` | `session_id` 예약 접두사 | 백스톱 (단독 검출 0건) | 향후 파이프라인 외 저장 경로 |
| **G-D** | `api/index.py::_PUBLIC_EXCLUDE_KEYS` | `metadata.synthetic` | **집행 — 유일 지점** | 목록·카테고리·검색·상세 4경로 |

집행이 한 곳이라 판정 로직이 늘어도 노출 규칙은 하나로 유지된다. `_PUBLIC_EXCLUDE_KEYS` 한 줄이
PostgREST 필터(`_apply_guard_filter`)와 Python 후처리(`_drop_flagged`) **양쪽에 동시 반영**되는
기존 이중 방어 구조를 그대로 물려받았다.

> ⚠️ **소급 적용 없음** — 가드는 신규 저장분에만 적용된다. 유지된 238건 중 105건이 `bench_*` 세션
> 소속으로 남는다(Plan §7.2의 의도된 수용 — 내용은 정상 노동법 Q&A이고 `session_id`는 공개 응답에
> 포함되지 않는다). "합성 전량 제외(→140건)"로 방침을 바꾸려면 백필 스크립트가 별도로 필요하다.

---

## 5. 검증 결과

### 5.1 오프라인

| 항목 | 결과 |
|------|------|
| `test_offline_units.py` | **13종 전량 통과** (D1~D4 신규) |
| D1 정규화 | NFD/공백/구두점 흡수, 다른 질문은 분리 |
| D2 대표 선정 | 최신 유지 · `created_at` 동률 시 `id` 사전순 결정론적 · 2회 호출 동일 결과 |
| D3 합성 판정 | 접두사 5종 검출 · hex12 오탐 0 · **실제 `save_conversation()` 경유로 원본 metadata 비변형 확인** |
| D4 제외 키 | 4종 계약 + `SCRIPT_KEYS is PUBLIC_EXCLUDE_KEYS` 동일성 + falsy 경계 |
| dedupe 멱등성 | 입력 순서를 뒤집어도 동일 결과 |

### 5.2 배포 후 양성 검증 2단계 (설계 §8 의무)

| 단계 | 방법 | 결과 |
|------|------|------|
| **①** G-B 오탐 0 | 프로덕션 `POST /api/chat`에 실제 질문 전송 | `metadata.synthetic`=**None**, 게시판 노출 ✅, 상세 딥링크 **200** ✅ |
| **②** 가드 작동 | 로컬 `benchmark_pipeline.py --limit 1` | 전체 245→**246**(저장 정상) / 공개 **238 불변** ✅, `bench_1`에 `synthetic:True` ✅, 상세 딥링크 **404** ✅ |

②의 404가 핵심이다. 목록 제외(`_apply_guard_filter`)와 상세 차단(`_is_public_excluded`)은 별개
경로인데, 하나의 상수를 참조하도록 한 설계가 양쪽에 실제로 적용됐다.

### 5.3 현재 상태 실측 (2026-08-13, Supabase 직접 조회)

| 항목 | 값 |
|------|-----|
| `qa_conversations` 전체 | **248** |
| 공개 노출 | **240** (= 정리 후 238 + 배포 후 실사용 2) |
| 제외 | **8** (`textbook` 7 + `synthetic` 1) |
| 고유 질문 | 239 |
| 중복 그룹 | **1** (검증 질문 재요청분 — 정상) |
| 카테고리 | **14종** |

가드 도입 이후 저장된 `bench_1`은 제외 집합에, 실사용 hex12 2건은 공개 집합에 정확히 들어갔다.

### 5.4 Match Rate가 못 잡는 영역 — 독립 실측 7항목

> CLAUDE.md 규약: "Match Rate가 90%를 넘어도 그대로 배포하지 말 것."

설계 대조와 **무관하게** 변경이 닿는 경로를 훑어 전부 통과. 최대 리스크는 **B1**이었다 —
G-D가 유일 집행점이므로 `qa_conversations`를 직접 읽는 경로가 하나라도 가드를 안 거치면 그리로
샌다. 설계 §4.4는 6개 경로를 열거했지만 "그게 전부인가"엔 답하지 않아, 엔드포인트 블록을
전수 파싱해 확인했다(게시판 3경로 가드 통과 / admin 3경로 의도적 미적용).

---

## 6. 갭 처리 현황 — 6건 전부 해소

| # | 갭 | 등급 | 조치 |
|---|-----|------|------|
| G-1 | D3 회귀가 `record.metadata` 비변형을 검증하지 않음 | Medium | ✅ `_StubSB` 주입으로 실제 `save_conversation()` 경유 단언 3종 추가 |
| G-2 | 세션 백업이 파일에 "먼저" 기록되지 않음 | Medium | ✅ 사이드카 파일(`*_sessions.json`) 선기록, 쓰기 실패는 전파해 삭제 차단 |
| G-3 | 백업 JSON에 최상위 `created_at` 부재 | Low | ✅ payload 첫 필드로 추가 |
| G-4 | 복구 절차가 설계 문서 밖에 없음 | Low | ✅ `dedupe_board.py` 모듈 docstring에 FK 순서 명기 |
| G-5 | `_verify()`가 빈 키 행 때문에 오탐 가능 | Low | ✅ 행 수 → **고유 질문(그룹) 수** 비교로 변경, 폐기 행 수 출력 |
| G-6 | 설계 §2.3 G-C 커버리지 오기 | Low | ✅ `/simplify` 리뷰 결과로 정정 주석 추가 |

Check 이후 `/simplify` 패스에서 추가로 정리된 것: `PUBLIC_EXCLUDE_KEYS` 단일 출처화,
`plan_dedupe()` 반환 구조 단순화(리포트가 대표 선정을 재계산하지 않도록), `_fetch_all()` 컬럼
축소(검증 재조회 전송량 −75%), `pipeline.py`의 `getattr` 폴백 제거.

---

## 7. 미결·후속

| # | 항목 | 상태 |
|---|------|------|
| 1 | CLAUDE.md 문구 드리프트 — "`dedupe_board.py`가 재선언" 서술 | ✅ 해소 (PR #48) — 단일 출처 계약으로 교체 |
| 2 | 설계 §5.7 vs §5.8 0행 규칙 모순 | ✅ 해소 (CodeRabbit 리뷰) — §5.7에 정정 주석. 멱등의 근거는 "0행이 무해해서"가 아니라 "0행이 될 id를 보내지 않아서"다 |
| 3 | `_verify()`가 삭제~재조회 사이의 신규 저장을 고려하지 않음 | ✅ 문서화 (CodeRabbit 리뷰) — 오탐 방향임과 유지보수 창 권고를 docstring에 명시. 구조적 해소는 cutoff 스냅샷이 필요해 보류 |
| 4 | 백업 JSON·생성 SQL이 저장소 루트에 평문으로 남아 있었다 (1.2MB / 상담 원문 225건) | ✅ 해소 (2026-08-13) — `~/DEV/laborconsult-backups/`로 이전(디렉터리 700, 파일 600, SHA-256 일치 확인). 복구 절차·파기 기준은 그곳 `README.md`. 파기는 롤백 가능성이 닫힐 때, 상한은 방침상 보유기간 기준 **2027-03-08** |
| 5 | **`board_posts.nickname` 스키마 드리프트** — `api/index.py`가 없는 컬럼을 select해 PostgREST 42703이 `try/except`에 삼켜진다. 현재 0행이라 무증상이나 **사용자 글이 등록되는 순간 게시판에서 통째로 사라진다** | 🔴 별도 사이클 (Plan §7.1 Out of Scope) |
| 6 | `--purge-sessions`의 조회~삭제 TOCTOU — 그 사이 저장된 대화가 CASCADE로 사라지고 **백업 어디에도 없다** | ⏸ 미사용 경로. 유지보수 창 요구를 docstring에 명시. 구조적 해소는 `DELETE ... WHERE NOT EXISTS ... RETURNING` RPC 필요(어차피 RLS 때문에 RPC가 필요하므로 함께 처리) |
| 7 | 잔존 238건 중 105건이 `bench_*` 소속 | 의도적 수용 — 방침 변경 시 백필 필요 |
| 8 | `x-forwarded-for` 무검증 신뢰 — 같은 헤더가 rate limit `subject_key`에도 쓰인다 | 이번 범위 밖. 게시판 영향은 "자기 글이 숨겨질 뿐"이라 Low지만 rate limit 쪽은 별도 검토 가치 |
| 9 | 고아 세션 85개 | 공개 경로가 세션을 읽지 않아 무해, 365일 보존기간 purge 대상. 정리하려면 SQL Editor나 service role 필요(§3.7) |

---

## 변경 이력

| 버전 | 일자 | 내용 |
|------|------|------|
| 1.0 | 2026-08-13 | 완료 보고. Match Rate 96.2%, 중복 225건 정리(463→238), 합성 차단 4단 가드, 갭 6건 전부 해소. RLS DELETE 무성 차단 발견 포함 |
| 1.1 | 2026-08-13 | CodeRabbit 리뷰(PR #48) 반영. **`_purge_orphan_sessions()`가 §3.1의 RLS 무성 차단 버그를 그대로 갖고 있던 것을 발견·수정**(§3.7 신설) — `qa_sessions`도 anon DELETE 정책이 없어 "N건 정리 완료"를 출력하고 0건을 지우는 상태였다. 그밖에 설계 §5.7 문구 정합, `_verify()`·`--purge-sessions`의 한계를 docstring에 명시, 백업 파일 파기 지침 추가 |
