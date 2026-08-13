# 질문게시판 중복 정리 Gap Analysis Report

> **Summary**: 설계 대조 항목 104개 중 100개 일치 — **Match Rate 96.2%**. 갭 6건 중 Medium 2·Low 4. 이 중 **G-1/G-3/G-4/G-5를 분석 직후 수정 완료**했고, 남은 2건(G-2·G-6)은 미사용 경로와 문서 정합이라 후속으로 미룬다. 별도로 Match Rate가 원리적으로 못 잡는 영역을 실측 7항목으로 훑어 전부 통과했다.
>
> **Project**: laborconsult
> **Analyst**: gap-detector + 독립 사각지대 점검
> **Date**: 2026-08-12
> **Plan**: [board-duplicate-cleanup.plan.md](board-duplicate-cleanup.plan.md)
> **Design**: [board-duplicate-cleanup.design.md](board-duplicate-cleanup.design.md)
> **Commit**: dc98e0d (PR #47, main 머지 완료)

---

## 1. 분석 개요

| 항목 | 내용 |
|------|------|
| 대조 대상 | 설계 §3.2, §4.1~4.5, §5.1~5.8, §6.1~6.2, §7, §9, §10 |
| 구현 파일 | `dedupe_board.py`(신규) · `app/core/storage.py` · `app/core/pipeline.py` · `app/core/abuse_guard.py` · `api/index.py` · `test_offline_units.py` · `.gitignore` · `CLAUDE.md` |
| 대조 방식 | 설계 요구 1건 = 항목 1개. 실제 행을 읽어 판정 |
| 보완 검증 | 설계 대조와 **별개로** 사각지대 7항목 실측 (§6) |

## 2. 종합 점수

| 구분 | 수 | 비율 |
|------|---:|-----:|
| **MATCH** | **100** | **96.2%** |
| ├ 그중 의도적 CHANGED (동작 동일) | 3 | 2.9% |
| PARTIAL | 3 | 2.9% |
| MISSING | 1 | 1.0% |
| **총 대조 항목** | **104** | 100% |

**Match Rate = 100 / 104 = 96.2%** → 설계-구현 동기화 양호(≥90%), Act 반복 불요.

| 섹션 | 항목 | MATCH | PARTIAL | MISSING |
|------|----:|------:|--------:|--------:|
| §3.2 FR-07 채택안 (진리표 5행 포함) | 11 | 11 | 0 | 0 |
| §4.1 G-A | 5 | 5 | 0 | 0 |
| §4.2 G-B | 4 | 4 | 0 | 0 |
| §4.3 G-C | 5 | 5 | 0 | 0 |
| §4.4 G-D | 8 | 8 | 0 | 0 |
| §4.5 소급 적용 없음 | 1 | 1 | 0 | 0 |
| §5.1 CLI 계약 | 4 | 4 | 0 | 0 |
| §5.2 실행 흐름 | 12 | 12 | 0 | 0 |
| §5.3 정규화 | 3 | 3 | 0 | 0 |
| §5.4 대표 선정 | 3 | 3 | 0 | 0 |
| §5.5 백업 스키마 | 8 | 6 | 1 | 1 |
| §5.6 CASCADE 방어 | 4 | 3 | 1 | 0 |
| §5.7 배치 파라미터 | 5 | 5 | 0 | 0 |
| §5.8 RLS 대응 | 3 | 3 | 0 | 0 |
| §6.1 metadata 키 계약 | 6 | 6 | 0 | 0 |
| §6.2 스키마 변경 없음 | 1 | 1 | 0 | 0 |
| §7 테스트 D1~D4 | 6 | 5 | 1 | 0 |
| §9 파일별 변경 명세 | 7 | 7 | 0 | 0 |
| §10 구현 체크리스트 | 8 | 8 | 0 | 0 |
| **합계** | **104** | **100** | **3** | **1** |

---

## 3. 핵심 대조 결과

### 3.1 §3.2 FR-07 — 진리표 5행 전부 일치

설계가 Design 단계로 미뤄둔 유일한 미결 항목. `api/index.py:129-147`이 진리표를 정확히 구현했고, **실환경에서도 재현**됐다(§6 ①).

| 상황 | `VERCEL_ENV` | client IP | 코드 경로 | 판정 |
|------|--------------|-----------|-----------|:----:|
| 프로덕션 실사용자 | `production` | 공인 | `:142` False → `:145` False | 실사용 ✅ |
| **프로덕션 + env 누락** | 없음 | 공인 | `:141` falsy → `:145` False | **실사용 ✅ (게시판 안 멈춤)** |
| preview 배포 | `preview` | 공인 | `:142-143` True | 합성 ✅ |
| 로컬 + e2e 테스트 | 없음 | `127.0.0.1` | `:145` True | 합성 ✅ |
| 로컬 수동 테스트 | 없음 | `127.0.0.1` | `:145` True | 합성 ✅ (의도) |

**CHANGED(개선)**: 설계는 `_LOOPBACK` + `any(...)`, 구현은 `_LOOPBACK_PREFIXES` + 튜플 `startswith`. 동작 동일하며 명칭이 `SYNTHETIC_SESSION_PREFIXES`와 일관된다.

### 3.2 §4.1 G-A — `guard_ctx is None ⟺ 비웹 호출` 계약 전수 검증

설계의 핵심 전제를 코드베이스 전수로 확인했다.

| 구분 | 호출부 | G-A 발동 |
|------|--------|:--------:|
| 비웹 | `benchmark_pipeline.py:180` · `compare_llm_models.py:107` · `test_legal_cases_e2e.py:102` · `test_naver_kin.py:86` | ✅ |
| 웹 | `api/index.py:247`(POST /api/chat) · `:286` · `:359`(SSE 2경로) | ❌ (정상) |

계약이 실제로 성립한다. 판정식은 설계와 문자 단위로 일치(`pipeline.py:2102`).

### 3.3 §4.4 G-D — 집행 지점 8개 경로 전수 확인

| 경로 | 적용 | 근거 |
|------|:----:|------|
| `board_recent` | ✅ | `api/index.py:948` + `:956` `_fetch_qa_public` |
| `board_categories` | ✅ | `:988` + `:992` |
| `board_search`(qa) | ✅ | `:1015` + `:1028` |
| `board_detail` | ✅ | `:1107` `_is_public_excluded` → 404 |
| `board_search`(board_posts) | ➖ 미적용이 정상 | metadata 컬럼 부재 |
| `/api/admin/*` 3경로 | ➖ 미적용이 정상 | 관리자는 합성도 봐야 한다 |

`_PUBLIC_EXCLUDE_KEYS` 한 줄 변경(`api/index.py:390`)이 PostgREST 필터(`:402-404`)와 Python 후처리(`:408`) **양쪽에 동시 반영**되는 구조가 의도대로 작동한다.

### 3.4 §5.8 RLS 대응 — 실행으로 실증됨

설계 §5.8은 구현 중 발견된 제약을 사후 반영한 절이다. 저장소 루트의 `dedupe_board_20260812_121212.sql`이 그 산출물이다 — 헤더 `대상 225건`, `DELETE ... IN (...)` **5문(50+50+50+50+25=225)**, `BEGIN;`/`COMMIT;` 래핑, 말미 검증 SELECT 주석. RLS 무성 차단 경로가 실제로 발동해 설계대로 SQL을 생성했다.

---

## 4. 갭 목록 및 조치

### 🟡 Medium

#### G-1. D3 회귀가 `record.metadata` 비변형을 검증하지 않았다 → ✅ **수정 완료**

- **설계**: §7 D3 — "원본 `record.metadata` 딕셔너리가 변형되지 않음"
- **당시 구현**: `test_offline_units.py`의 D3가 `_is_synthetic_session()`의 접두사 검출·hex12 오탐 0·`_` 종료 불변식만 단언
- **코드 자체는 정상**: `storage.py:180` `dict(record.metadata or {})`
- **왜 문제인가**: §10 체크리스트 4번이 코드엔 반영됐으나 **회귀로 고정되지 않았다.** `save_conversation()`이 리팩터되어 `record.metadata["synthetic"] = True`로 되돌아가도 CI가 잡지 못한다. 설계 §4.3이 명시한 실패 모드(호출부 딕셔너리 오염)가 조용히 부활할 수 있다. **"구현은 맞는데 회귀가 없어 되돌아갈 수 있는" 유형은 이 갭이 유일하다.**
- **조치**: `_StubSB`를 주입해 실제 `save_conversation()`을 거치는 단언 3종 추가 — 저장 metadata에 `synthetic` 부착 / 호출부 원본 dict 비변형 / `rec.metadata` 참조 비교체. hex12 미부착 케이스도 실경로로 확인.

#### G-2. 세션 백업이 파일에 "먼저" 기록되지 않는다 → ⏸ **후속**

- **설계**: §5.6-4 — "세션 행을 백업 JSON에 **먼저** 기록"
- **구현**: `dedupe_board.py:226-228`이 세션 행을 메모리에 담고 `:229`에서 즉시 삭제. 파일 반영은 루프 종료 후 `:369-372` 1회. 그 쓰기 실패는 경고만 출력되고 삼켜진다.
- **영향**: `--purge-sessions` 실행 중 중단되면 이미 삭제된 `qa_sessions` 행이 백업에 남지 않아, 복구 시 §5.5의 "sessions 먼저 삽입(FK 선행)" 절차를 밟을 수 없다. **대화 백업은 삭제 전에 확정**되므로(`:337`) 대화 손실 위험은 없다.
- **미룬 이유**: 이번 정리에서 `--purge-sessions`를 **사용하지 않았다**(고아 세션 85개 잔존, 365일 보존기간 purge 대상). 실제로 쓸 때 필요한 보완이다.
- **보완안**: `_purge_orphan_sessions()` 진입 직후 세션 목록을 파일에 선기록한 뒤 삭제로 진입.

### 🔵 Low

#### G-3. 백업 JSON에 최상위 `created_at` 부재 (MISSING) → ✅ **수정 완료**

파일명에 UTC 타임스탬프가 박히고 각 레코드가 자기 `created_at`을 갖지만, 파일이 이름을 잃으면 실행 시점 추적이 끊긴다. payload 첫 필드로 추가.

#### G-4. 복구 절차가 설계 문서 밖 어디에도 없다 (PARTIAL) → ✅ **수정 완료**

`dedupe_board.py` 모듈 docstring에 복구 순서 명기 — "`sessions`를 **먼저**, 그다음 `conversations`. FK 참조 때문에 순서를 뒤집으면 삽입이 실패한다. `sessions`가 비어 있으면 `storage.ensure_session()`으로 세션을 만든 뒤 대화를 넣는다."

#### G-5. `_verify()`가 빈 키 행 때문에 오탐할 수 있다 → ✅ **수정 완료**

- **내용**: `plan_dedupe()`는 `group_by_question()`을 거치므로 질문이 기호뿐인 행(빈 키)을 keep/drop **어디에도 넣지 않는다**(안전한 선택). 반면 `_verify()`의 `rows`는 공개 대상 전량이라 그런 행을 포함해, N건 있으면 삭제 성공 후에도 `len(rows) == expected_keep`이 항상 거짓 → `⚠️ 검증 불일치` 오탐 + `return 1`.
- **실측 영향 0**: 해당 행이 현재 0건이라 이번 실행에서 드러나지 않았다. 오탐 방향이라 데이터는 안전.
- **조치**: 행 수가 아니라 **고유 질문(그룹) 수**를 기대값과 비교하도록 변경하고, 폐기된 빈 키 행 수를 출력에 명시.

#### G-6. 설계 내부 모순 — §5.7 "0행은 무해" vs §5.8 "0행은 RLSBlocked" → ⏸ **문서 갱신 대기**

§5.7 재실행 항목은 "이미 삭제된 id의 DELETE는 0행 영향 → 무해(멱등)"라 적었고, 같은 날 추가된 §5.8은 "0행이면 예외"를 요구한다. 구현은 §5.8을 따른다. **실무상 충돌 없음** — `drop` 목록이 매 실행 새 조회에서 산출되므로 이미 삭제된 id가 배치에 들어가지 않는다. 설계 문구만 정합화하면 된다.

---

## 5. 설계 O / 구현 X · 구현 O / 설계 X

### 5.1 설계에만 있던 것 (전부 §4에서 처리)

| 항목 | 설계 위치 | 상태 |
|------|-----------|------|
| 백업 JSON 최상위 `created_at` | §5.5 | ✅ 수정 |
| D3의 metadata 비변형 회귀 | §7 | ✅ 수정 |
| 복구 절차 코드 문서화 | §5.5 | ✅ 수정 |
| 세션 행의 삭제 **전** 파일 기록 | §5.6-4 | ⏸ 후속 (미사용 경로) |
| 배포 후 양성 검증 2단계 | §8 | ✅ **실행 완료 — §6 참조** |

### 5.2 구현에만 있던 것 (긍정적 추가 10건)

| # | 추가 | 위치 | 가치 |
|---|------|------|------|
| P-1 | `PUBLIC_EXCLUDE_KEYS` 재선언 + `is_public_excluded()` | `dedupe_board.py:35`,`:57-59` | 스크립트가 FastAPI를 import하지 않아도 동일 규칙 적용 |
| **P-2** | **D4가 `api/index.py` 소스를 파싱해 두 소스의 키 집합 대조** | `test_offline_units.py:241-247` | **두 곳 재선언의 유일한 안전장치.** CLAUDE.md의 "양쪽 함께 갱신" 규약을 CI가 강제 |
| P-3 | `group_by_question()`이 빈 키 행 폐기 | `dedupe_board.py:63-68` | 기호뿐인 질문이 한 그룹으로 뭉쳐 대량 삭제되는 사고 방지 |
| P-4 | `_write_backup()`이 파일을 **다시 읽어** 건수 대조 | `:135-142` | 설계 ⑦-2는 "존재 + 레코드 수"만 요구. 디스크 가득참으로 조용히 잘리는 경우까지 방어 |
| P-5 | 백업 payload에 `deleted_count` | `:128` | 복구 시 대조 지표 |
| P-6 | `.gitignore`에 `dedupe_board_*.sql` | `.gitignore:54` | 생성 SQL에도 상담 UUID 225건이 들어간다 |
| P-7 | D3의 "접두사는 `_`로 끝난다" 불변식 단언 | `test_offline_units.py:222-223` | `SYNTHETIC_SESSION_PREFIXES`에 `bench` 같은 항목이 추가되는 것을 차단 |
| P-8 | D4의 falsy 값(`False`/`None`/문자열) 단언 | `:237-238` | 제외 판정의 경계 고정 |
| P-9 | G-C fail-open이 `pass` 대신 `logger.warning` | `storage.py:184-185` | 설계 코드는 `pass`. 조용한 실패를 계측 — CLAUDE.md 계측 규약과 일치 |
| P-10 | dry-run이 중복 그룹 상위 10개를 반복 횟수와 함께 출력 | `dedupe_board.py:251-256` | 육안 검토 품질 |

`plan_dedupe()`/`group_by_question()`/`pick_representative()` 3단 분리는 설계가 함수 경계를 명시하지 않은 부분인데, D1~D2가 Supabase 없이 순수 함수만 테스트할 수 있게 만든 구조적 선택이다.

---

## 6. Match Rate가 못 잡는 영역 — 독립 실측

> CLAUDE.md 규약: "gap-detector의 Match Rate는 '설계대로 만들었는가'만 답한다 — 설계 자체의 공백은 원리적으로 못 잡는다. Match Rate가 90%를 넘어도 그대로 배포하지 말 것."

설계 대조와 **무관하게** 변경이 닿는 경로를 훑었다. 7항목 전부 통과.

| # | 점검 | 결과 |
|---|------|------|
| **B1** | 무가드로 `qa_conversations`를 읽는 공개 경로 | **없음** — 엔드포인트 블록 전수 파싱, 게시판 3경로 가드 통과 / admin 3경로 의도적 미적용 |
| B2 | 게시판 3엔드포인트 건수 정합 | `recent`=`categories`=`search`=**240** |
| B3 | 고아 세션 | 85개(스냅샷 20개) — 공개 경로가 세션을 읽지 않아 무해, 365일 purge 대상 |
| B4 | admin 통계 | 248건 전부 노출 — 설계 §4.4 의도대로 |
| B5 | dedupe 멱등성 | 입력 순서를 뒤집어도 동일 결과 |
| B6 | 잔여 중복 | 1그룹(검증 질문 재요청분)뿐 |
| B7 | 신규 프로덕션 대화 노출 | 게시판 최상단 정상 표시 |

**B1이 이번 사이클의 최대 리스크였다.** G-D는 `_PUBLIC_EXCLUDE_KEYS` 한 곳이 집행하므로, `qa_conversations`를 직접 읽는 경로가 하나라도 가드를 안 거치면 그리로 샌다. 설계는 §4.4에서 6개 경로를 열거했지만 "그게 전부인가"는 답하지 않았다 — 전수 파싱으로 확인했다.

### 6.1 §8 양성 검증 2단계 — 실행 완료

| 단계 | 방법 | 결과 |
|------|------|------|
| **①** G-B 오탐 0 | 프로덕션 `POST /api/chat`에 실제 질문 전송 | `metadata.synthetic`=**None**, 게시판 목록 노출 ✅, 상세 딥링크 HTTP **200** ✅ |
| **②** 가드 작동 | 로컬 `benchmark_pipeline.py --limit 1` | 전체 245→**246**(저장 정상) / 공개 **238 불변** ✅, `bench_1`에 `synthetic:True` ✅, 상세 딥링크 HTTP **404** ✅ |

②의 404 확인이 중요하다. 목록 제외(`_apply_guard_filter`)와 상세 차단(`_is_public_excluded`)은 별개 경로인데, 하나의 상수를 참조하도록 한 설계가 양쪽에 실제로 적용됐다.

**검증 과정에서 드러난 함정**: 첫 시도에서 `--limit 3`을 줬으나 `benchmark_pipeline.py`의 `load_existing_results()` resume 로직이 기존 116건을 전부 "이미 완료"로 건너뛰어 **파이프라인이 한 번도 실행되지 않았다.** 건수 불변을 "가드가 막았다"로 읽었으면 오판이었다. 결과 파일을 치운 뒤에야 실제 저장이 일어났다.

---

## 7. 남은 한계 (의도적 수용)

- **`x-forwarded-for` 무검증 신뢰** — `api/index.py:118`. 설계 §11이 "자기 글이 숨겨질 뿐"이라며 Low로 수용. 다만 같은 헤더가 rate limit `subject_key`(`:162-163`)에도 쓰인다 — **이번 사이클 범위 밖이며 별도 검토 가치가 있다.**
- **`_verify()`가 삭제~재조회 사이의 신규 저장을 고려하지 않는다** — 프로덕션 트래픽 중 `--apply` 실행 시 오탐 가능. 설계 ⑦-4도 같은 한계라 갭으로 잡히지 않았다.
- **잔존 238건 중 105건이 `bench_*` 소속** — Plan §7.2의 의도된 수용. 가드는 신규 저장분에만 적용되므로 "합성 전량 제외(→140건)"로 방침을 바꾸려면 백필이 별도 필요하다.
- **`board_posts.nickname` 스키마 드리프트** — Plan §7.1 Out of Scope. 현재 행 0건이라 무증상이지만 **사용자 글이 등록되는 순간 게시판에서 통째로 사라진다.** 별도 사이클 필요.

---

## 8. 결론

| 판정 | 근거 |
|------|------|
| **Match Rate 96.2%** — Act 반복 불요 | 90% 기준 충족, MISSING 1건도 Low |
| **Medium 갭 2건 중 1건 즉시 해소** | G-1(회귀 부재)은 유일한 "되돌아갈 수 있는" 유형이라 우선 수정 |
| **사각지대 7항목 전부 통과** | 설계가 답하지 않은 "그게 전부인가"를 전수로 확인 |
| **양성 검증 2단계 완료** | fail-open 가드의 조용한 오작동 가능성 배제 |

후속 사이클 이월: **G-2**(`--purge-sessions` 백업 선기록) · **G-6**(설계 §5.7 문구 정합) · 설계 문서 갱신 4건(§3.2 명칭, §5.2 순서, §9 규모).

---

## 9. 관련 문서

- Plan: [board-duplicate-cleanup.plan.md](board-duplicate-cleanup.plan.md)
- Design: [board-duplicate-cleanup.design.md](board-duplicate-cleanup.design.md)
- 선행 사이클: `chatbot-security`(가드 계약·fail-open 규약) · `textbook-corpus-embedding`(G6 공개 제외 선례) · `llm-fallback-hardening`(`truncated` 키)
