# llm-fallback-alert-blindspot Planning Document

> **Summary**: 전 제공자 실패·답변 중 예외처럼 **저장되지 않아 폴백 감시가 보지 못하는 실패**를 답변 없는 실패 행으로 기록하고, `check_llm_fallback.py`가 그 행을 읽어 다음 cron 주기(≤ 6시간) 안에 알리게 한다. ai-gateway-oidc-migration 후속 **F-4(High)**.
>
> **Project**: laborconsult · **Author**: Claude(Fable 5.1) + 사용자 · **Date**: 2026-10-30 · **Status**: Approved(§8 확정) → Design
> **Parent**: `docs/archive/2026-10/llm-fallback-alert/`(PR #89, 2026-10-02) · `docs/archive/2026-10/ai-gateway-oidc-migration/ai-gateway-oidc-migration.report.md` §4.1 F-4

---

## Executive Summary

| Perspective | Content |
|---|---|
| **Problem** | 폴백 감시는 **저장된 대화만** 읽는다. 전 제공자가 실패하면 파이프라인이 오류 이벤트만 내고 대화를 저장하지 않아(`pipeline.py` `except RuntimeError` 분기), 전면 장애 중에도 '✅ 정상' 또는 '판정 불가'가 나온다. 실측 2026-10-14: gpt-6-luna 첫 응답 >20초 + Claude 한도 + Gemini 크레딧 소진으로 **전 제공자 실패 상태였는데** 마지막 저장 대화가 10-11이라 ✅였다. Gateway 전환(10-28) 뒤에는 토큰(401)·크레딧 소진(402) 장애가 정확히 같은 경로다. "실사용이 0건"과 "전부 실패"를 구분할 수 없다. |
| **Solution** | **실패도 기록한다.** 전 제공자 실패와 답변 중 예외에서 `qa_conversations`에 답변 없는 실패 행(`metadata.llm.failed=True`, 오류는 예외 클래스명·HTTP 상태만 — 메시지 원문·토큰 없음)을 남기고 공개 게시판에서 제외한다. 감시는 `failed`를 저하 사유에 더하고, **최근 W시간 안의 실패 행 1건으로도 알린다**(3건 연속을 기다리지 않음). 요약에 '마지막 실사용 답변 경과'를 표시한다. 새 테이블·DDL·Secret 없음(기존 anon INSERT 정책·metadata 컬럼 재사용). |
| **Function/UX Effect** | 전면 장애가 **다음 cron(≤ 6시간)에 메일로 드러난다**(10-14 사례면 10-14 당일). 사용자 화면·답변 경로는 불변 — 기록은 fail-open이고 오류 안내는 그대로 나간다. 재현은 로컬 만료 OIDC 토큰(V-9 절차)으로 **비용 $0**. |
| **Core Value** | 이 코드베이스의 감시 원칙 "실패가 조용히 사라지지 않게"의 마지막 사각(저장 전 실패)을 닫는다. Gateway 크레딧 소진·토큰 장애가 **답변 0건으로 숨는** 경로를 끊는다. |

---

## 1. Overview

### 1.1 Purpose

`check_llm_fallback.py`(6시간 cron)가 **저장 전에 끝나는 실패**를 보게 한다. 지금은 `qa_conversations.metadata.llm`만 읽으므로, 1순위가 실패하고 2순위가 성공한 경우(폴백)는 보이지만 **전부 실패한 경우는 보이지 않는다** — 더 나쁜 장애가 덜 보인다.

### 1.2 Background — 실측 근거

| 날짜 | 사실 | 출처 |
|---|---|---|
| 2026-10-14 | rev 11(gpt-6-luna 1순위) 상태에서 첫 응답 >20초 + Claude 한도 + Gemini 선불 소진 = 전 제공자 실패. 감시는 마지막 실사용 10-11 17:22 기준 **✅ 정상**. | memory `project-llm-fallback-alert` |
| 2026-10-11 → 10-27 | 실사용 저장 0건(트래픽 없음, 10-26 확인). → "마지막 실사용 경과 시간" 단독 알림은 **오탐**이 된다. | memory `project-codex-wage-update-review` |
| 2026-10-28 | Gateway 전환. 토큰 부재·만료·크레딧 소진은 전 표면(Claude·OpenAI·임베딩·Cohere) 동시 실패 → 전 제공자 실패 경로. 보고서 F-4 High로 기록. | ai-gateway report §4.1·§8.1 |
| 2026-10-30 | V-9 실측: 만료 토큰으로 서버 경로 1질문 → 의도분석 Claude 401→OpenAI 401→레거시, 임베딩·공공쿼터 401, 재정렬 401→코사인, 답변 Claude 401→OpenAI 401→Gemini 직접 429 → `error` 이벤트 "모든 AI 서비스에 연결할 수 없습니다" → **저장 0건**. 이 경로의 **무비용 재현 수단**이 확보됐다. | ai-gateway report v1.4 §9 'V-9 실측' |

**현재 실패 경로와 기록 여부**

| # | 경로 | 코드 지점 | 지금 저장 | 감시가 봄 | 이번 대상 |
|---|---|---|---|---|---|
| (a) | 1순위 실패 → 폴백 성공 | `_stream_answer` 전환 | O(`llm.fallback`) | O | — (기존) |
| (b) | **전 제공자 실패·전부 빈 응답** | `pipeline.py` `process_question`의 `except RuntimeError` → `error`+`done` | **X** | **X** | **O** |
| (c) | **답변 중 예상 밖 예외** | `api/index.py` SSE 두 경로의 `except Exception`("답변 생성 실패") | **X** | **X** | **O** |
| (d) | 초기화 실패(`get_config`·세션 복원) | `api/index.py` "SSE 초기화 실패" → `_sse_error` | X | X | △ Supabase 핸들이 없을 수 있어 **기록 불가** — 한계로 명시 |
| (e) | 가드 거절·인젝션/스코프 block·유출 감지 | `_guard_chat_request`·`scan_injection`·`scan_leak` | 의도적 미저장(`abuse_events`에 기록) | 해당 없음 | — |
| (f) | 트래픽 0 | — | — | '판정 불가' | 알림 아님. 요약에 경과만 |

### 1.3 Related Documents

- 선행 사이클: `docs/archive/2026-10/llm-fallback-alert/llm-fallback-alert.plan.md`·`.design.md`(판정 규칙 R1 "최근 실사용 3건 연속 저하", fail-closed, 본문 비조회)
- 계측 설계: `docs/archive/2026-08/llm-fallback-hardening/`(`metadata.llm` 페이로드, `AnswerOutcome`)
- F-4 정의: `docs/archive/2026-10/ai-gateway-oidc-migration/ai-gateway-oidc-migration.report.md` §4.1·§8.2
- 운영 규칙: `CLAUDE.md` "폴백 결과는 `qa_conversations.metadata.llm`에 기록한다 … 계측만으로는 부족했다" 절
- 코드: `check_llm_fallback.py`, `.github/workflows/llm-fallback-alert.yml`, `app/core/pipeline.py`(`_stream_answer`·`_llm_meta`·저장 구간), `app/core/storage.py`(`save_conversation`·`PUBLIC_EXCLUDE_KEYS`), `api/index.py`(SSE 경로)

---

## 2. Scope

### 2.1 In Scope

- [ ] **실패 행 기록 헬퍼** 1개(`storage.py` 또는 `pipeline.py`) — (b)·(c) 두 경로가 **같은 헬퍼**를 쓴다. `save_conversation`을 그대로 재사용해 `ConversationRecord(answer_text="")`로 저장(세션 보장·synthetic 백스톱 G-C 포함).
- [ ] **metadata 계약** — `metadata.failed=True`(게시판 제외 키), `metadata.llm = {failed: True, attempts, empty, error_class, status?, transport, stage: "answer"|"pipeline"}`. 기존 `_llm_meta` 확장 또는 자매 함수. **예외 메시지 원문은 저장하지 않는다**(토큰·키·URL이 섞일 수 있다 — Gateway 401 본문은 안내 URL을 포함한다).
- [ ] `PUBLIC_EXCLUDE_KEYS`에 `failed` 추가(`storage.py` 단일 출처 → 게시판 PostgREST 필터·Python 후처리·`dedupe_board.py` 검증 SQL이 자동 반영).
- [ ] **감시 규칙** — `degraded()`에 `failed`; 신규 R2 "최근 실사용 중 `created_at ≥ now − W`인 `failed` 행 ≥ 1 → alert"(W는 설계 결정, 후보 12시간 = cron 2주기); 기존 R1(3건 연속) 유지. 요약 표에 실패 행 표시(provider '—', 사유 `failed:<error_class>`).
- [ ] **요약 보강** — "마지막 실사용 답변: {KST} ({N}시간 전)"·"최근 24시간 실패 행 {n}건" 줄(알림 아님).
- [ ] 알림 문구: `error_class`/`status`가 401·402·`AuthenticationError`·credit 류면 "Gateway 토큰·크레딧 잔액(`/v1/credits`) 확인" 힌트.
- [ ] 테스트(전부 오프라인, CI `tests.yml`): `test_llm_fallback.py`(전 제공자 실패 시 헬퍼 호출·`error`→`done` 순서 유지·기록 실패에도 이벤트 불변·메시지 원문 미저장), `test_llm_fallback_alert.py`(R2·W 경계·합성 실패 행 제외·10-14 사례 재구성·render 비출력), `test_offline_units.py`(`PUBLIC_EXCLUDE_KEYS` 계약), `api` 경로 테스트(예외 → 헬퍼).
- [ ] 문서: `CLAUDE.md` 폴백 감시 절(사각 해소·실패 행 계약·R2), `check_llm_fallback.py` docstring, 워크플로 주석, 보관 보고서 F-4 완료 표기(이번 사이클 Report에서).

### 2.2 Out of Scope

- **능동 카나리(주기 합성 질문)** — Gateway 크레딧을 쓴다(실측 질문 1건 ≈ $0.2 → 6시간 주기면 월 ≈ $24, 잔액 $12.30). 사용자 제약 "추가 결제·크레딧 구매 금지"와 충돌 → **사용자 승인 뒤 별도 사이클**.
- 요청 수 대비 저장 수 비교(`chat_quota` 합계) — anon 조회 RPC 신설(DDL)이 필요하고 가드가 fail-open이라 누락이 생긴다. 보류.
- 초기화 실패 (d) 기록 — Supabase 핸들 자체가 없을 수 있다. 한계로 보고서에 명시.
- 메일·슬랙 발송 코드, 알림 억제(dedupe), 비율 판정 — 선행 사이클과 같은 이유로 제외.
- `/api/health`에 실패 카운터 — Fluid Compute 인스턴스별 메모리라 신호가 되지 못한다.
- Vercel 런타임 로그 API 조회 — 토큰 Secret 신설·보존기간 짧음. 보류.
- 관리자 화면 신규 메뉴 — 실패 행은 기존 대화 목록에 '답변 없음'으로 보이는 것으로 충분(설계에서 표시만 결정).

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | (b) 전 제공자 실패: `process_question`의 `except RuntimeError` 분기에서 실패 행을 기록한다 — `question_text`·`category`·`session_id`는 정상 저장과 같게, `answer_text=""`, `metadata.failed=True`, `metadata.llm={failed, attempts(outcome), empty, error_class, status?, transport, stage:"answer"}` | High | Pending |
| FR-02 | (c) 답변 중 예외: `api/index.py` SSE GET·POST 경로의 `except Exception`에서 같은 헬퍼로 기록한다(`stage:"pipeline"`, `attempts`는 없을 수 있음). 동기 `POST /api/chat`의 미처리 예외(현재 500) 적용 여부는 설계에서 정한다 | High | Pending |
| FR-03 | 기록은 **fail-open**: 기록 실패(DB 장애·예외)가 사용자 오류 안내(`error`·`done`)를 막거나 바꾸지 않는다. 순서는 `error` → (ping) → 기록 → `done` 또는 설계가 정한 동등 순서 — 사용자 안내 지연은 Supabase INSERT 1회 이내 | High | Pending |
| FR-04 | **비밀·본문 비저장·비출력**: metadata에 예외 메시지 원문·토큰·키·URL을 넣지 않는다(클래스명·HTTP 상태만). 감시 스크립트는 `question_text`를 조회하지 않는 현 계약 유지 | High | Pending |
| FR-05 | `failed`를 `PUBLIC_EXCLUDE_KEYS`에 추가 — 공개 게시판 필터·후처리·`dedupe_board` 검증 SQL 모두 자동 반영. `True`일 때만 기록(명시적 False 금지) | High | Pending |
| FR-06 | synthetic 규약 유지: `guard_ctx is None`·`guard_ctx.synthetic`(G-A/G-B)·예약 접두사(G-C)는 실패 행에도 그대로 적용 → 로컬 재현·벤치가 감시 표본·게시판을 오염시키지 않는다 | High | Pending |
| FR-07 | 감시 R2: 실사용(비합성) 행 중 `llm.failed`이고 `created_at ≥ now − W`인 행이 1건 이상이면 alert(exit 1). R1(최근 3건 연속 저하 — `failed`도 저하)은 유지. W 기본값·근거는 설계에서(후보 12h) | High | Pending |
| FR-08 | 요약(Job Summary)에 "마지막 실사용 답변 시각·경과", "최근 24시간 실패 행 수"를 표시한다. **알림 사유가 아니다**(트래픽 0은 장애가 아니다 — 10-11~10-27 실측) | Medium | Pending |
| FR-09 | alert 문구: 실패 행의 `error_class`/`status`에 따라 점검 힌트를 낸다 — 401/`AuthenticationError`→OIDC 토큰·Vercel env, 402/credit→Gateway 크레딧 잔액, 그 외→Vercel 런타임 로그의 "답변 생성 실패, 다음 제공자로 전환" 원문 | Medium | Pending |
| FR-10 | 문서 갱신: `CLAUDE.md` 폴백 감시 절, `check_llm_fallback.py` docstring, `llm-fallback-alert.yml` 주석, memory `project-llm-fallback-alert` 사각 해소 | Medium | Pending |
| FR-11 | (선택) 킬스위치 `FAILURE_RECORD=off` — 기록만 끄고 오류 안내는 불변. 필요성은 설계에서 판단(기록이 fail-open이라 없어도 되는지) | Low | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement |
|---|---|---|
| 성능 | 실패 경로에만 Supabase INSERT 1회 추가(정상 경로 불변). 프론트 idle 60초 대비 ≤ 수 초 | 로컬 재현의 `error`→`done` 간격 측정 |
| 저장소 | DDL 0건, 새 테이블·컬럼·RPC·Secret 없음. 실패 행은 `qa_conversations` 보존기간(365일, `purge_expired_data`)을 그대로 따른다 | `git diff -- '*.sql'` 비어 있음 |
| 보안·개인정보 | 질문 원문 저장은 정상 대화와 같은 범위(방침 제5항 보존 대상) — **방침 변경 불요**를 설계에서 확인. 토큰·키·예외 메시지 원문 0건 | 단위 테스트 + 로컬 재현 행 육안 |
| 감시 원칙 | 감시 자신은 fail-closed(조회 실패 exit 2) 유지. 판정은 "Claude가 아님"이 아니라 fallback·failed | 기존 테스트 A5·A8 유지 |
| 테스트 | 전부 오프라인(API 키 불요), CI 편입. 변이 검사: 기록 호출 제거·`failed` 키 누락·W 경계 조정 각각이 테스트를 깨뜨린다 | 변이 N/N |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] 로컬 재현(만료 OIDC 토큰, `LLM_TRANSPORT=gateway uvicorn`, V-9 절차 — **재pull 전**에 실행): 질문 1건 → SSE `error`·`done` 그대로 + Supabase에 `llm.failed=True`·`synthetic=True`·`answer_text=""` 행 1건, metadata에 토큰·키·메시지 원문 없음. 비용 $0(전 호출 401).
- [ ] `check_llm_fallback.py` 오프라인: 실패 행 1건(최근 W 안) fixture → exit 1; W 밖이면 R1만; 합성 실패 행은 제외; **10-14 사례 재구성**(마지막 실사용 10-11 + 10-14 전면 실패 행) → 10-14 실행에서 alert.
- [ ] 기존 테스트 전부 통과: `test_llm_fallback.py`·`test_llm_fallback_alert.py`·`test_offline_units.py`·`test_abuse_guard.py`·`test_pipeline_wiring.py`·`test_llm_transport.py`.
- [ ] 공개 게시판 API(`/api/board/recent`·`search`·`{id}`)에 실패 행 미노출 — 필터·후처리 양쪽 회귀.
- [ ] PR: Codex·CodeRabbit 리뷰 반영 → 머지 → 배포 → `workflow_dispatch` 1회 수동 실행 exit 0, 요약에 '마지막 실사용 경과' 줄 확인.
- [ ] 변이 검사 통과, CLAUDE.md·docstring·memory 갱신.

### 4.2 Quality Criteria

- [ ] Gap 분석(`/pdca analyze`) ≥ 90% + 변경이 닿는 경로(SSE 두 경로·동기 경로·게시판 3경로·감시)를 설계와 무관하게 한 번 더 훑는 리뷰(CLAUDE.md "Match Rate 90%를 넘어도 그대로 배포하지 말 것").
- [ ] 정상 경로(답변 성공) 코드 diff 0 — 실패 분기와 감시만 바뀐다.

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| 실패 행이 관리자 통계·대화 목록을 오염 | Medium | High | 게시판은 `failed` 키로 제외. 관리자 목록은 '답변 없음'으로 보이는 것을 허용(디버깅 가치). `admin_stats` 총계 포함 여부는 설계에서 결정(기본: 포함하되 표시) |
| Supabase 장애가 원인인 전면 실패는 기록 불가 | Medium | Low | 그 경우 감시 조회도 실패해 exit 2로 드러난다. "LLM 전부 실패 + DB 정상"(10-14·Gateway 401/402 유형)은 기록된다 |
| 일시적 단일 실패(네트워크 blip)로 메일 발송 | Low | Medium | W = cron 2주기면 최대 2통. 선행 사이클과 같은 결정(장애 지속 중 반복 메일 수용). 전 제공자 실패는 단 1건도 점검할 가치가 있다 |
| 기록 중 지연으로 `done` 지연·프론트 idle | Low | Low | 기록 앞에 `ping`, 기록은 try/except, 타임아웃은 기존 저장과 동일 |
| 예외 메시지에 토큰·키 혼입 | High | Low | FR-04: 클래스명·상태만 저장. 단위 테스트가 메시지 원문 부재를 단언. 사용자 제약 "토큰을 화면·로그·문서에 출력하지 않는다"의 연장 |
| (c) 경로에서 `attempts` 비어 있음 → `is_real`은 `llm` truthy면 포함, `degraded`에 `failed` 있어 판정 가능 | Low | Medium | `_llm_meta`와 분리된 실패 전용 페이로드로 키 존재를 보장 |
| 벤치·로컬 재현의 합성 실패 행 누적 | Low | Medium | synthetic 제외(감시·게시판) + 365일 purge |
| 동기 `/api/chat`의 예외가 500으로 남음 | Low | Low | 설계에서 헬퍼 적용 여부 결정(프런트는 SSE만 쓴다) |

---

## 6. Alternatives Considered

| 안 | 내용 | 판정 | 이유 |
|---|---|---|---|
| **A1 (채택)** | `qa_conversations`에 실패 행(`answer_text=""`, `metadata.failed`) | ✅ | 감시가 이미 읽는 표·같은 anon INSERT 정책·DDL 0. `judge()` 변경 최소. 게시판 제외는 기존 단일 출처 키로 |
| A2 | `abuse_events` RPC(`record_abuse_event`)에 `llm_failure` 이벤트 | ✗ | 남용 기록과 의미 혼동, 관리자 남용 화면에 노출, `detail`에 질문 프리뷰가 섞이는 표 |
| A3 | `law_article_cache`의 `meta:` 행(예열 상태 행 패턴) | ✗ | 캐시 표 오용·단일 행 읽기-수정-쓰기 경합·만료 purge와 충돌 |
| A4 | 신규 `ops_events` 테이블 + DDL | ✗(보류) | SQL Editor 수동 적용·커스텀 스키마 GRANT 함정(2026-08-13 반복 사고)·감시용 anon SELECT 정책 필요 — 하루 0~5건 기록에 과함 |
| B | `chat_quota` 요청 합계 vs 저장 수 비교 | ✗(보류) | anon 조회 RPC 신설(DDL), 가드 fail-open이라 요청 누락, 거절 요청 미집계 |
| C | "마지막 실사용 경과 N시간" 알림 | ✗ → 표시만 | 10-11~10-27 트래픽 0 실측 — 오탐. FR-08로 요약에만 |
| D | 주기 카나리 질문 | ✗(승인 필요) | 월 ≈ $24 크레딧·결제 제약. 사용자 결정 뒤 별도 |
| E | `/api/health` 실패 카운터 | ✗ | 인스턴스별 메모리, 콜드 스타트마다 0 |

---

## 7. Convention Prerequisites

- 기존 규약 적용: 저장 단일 초크포인트 `save_conversation`, 제외 키 단일 출처 `storage.PUBLIC_EXCLUDE_KEYS`(재선언 금지), synthetic 3중 판정(G-A/G-B/G-C), 감시 fail-closed·본문 비조회, `from __future__ import annotations`, 폴백 경로 fail-open.
- 새 환경변수: 없음(FR-11 킬스위치는 선택). 새 Secret: 없음(`SUPABASE_URL`·`SUPABASE_KEY` anon 기존).
- DDL: 없음. `check_schema.py`·`_DDL_FILES` 불변.
- 재현 환경: `.env.vercel.local`의 OIDC 토큰은 2026-10-30 18:43 KST 만료 → 그 뒤 재pull **없이** 로컬 서버를 띄우면 (b) 경로가 재현된다(그 전에 필요하면 만료 토큰 파일을 임시로 넣는다 — 값은 어디에도 출력하지 않는다).

---

## 8. Decisions for User — **확정 2026-10-30(사용자 "a로 확정")**

| ID | 질문 | 결정 | 근거 |
|---|---|---|---|
| U1 | R2의 W(최근 실패 행 알림 창) | **12시간** | cron 2주기 — 실행 하나가 지연·취소돼도 다음 실행이 같은 실패를 보고, 단일 blip의 메일은 최대 2통. 6h는 놓치면 영영 못 보고, 24h는 하루 내내 메일 |
| U2 | 실패 행에 질문 원문 저장 | **정상 대화와 동일 저장** | 방침 제5항 "상담 대화(질문·답변) 1년" 범위 안 — 변경 불요. (c) 예외 경로는 질문 모양(첨부·길이)이 원인일 수 있어 원문 없이는 재현 불가. 답변 본문은 빈 문자열, 예외 메시지·토큰·키는 미저장(FR-04) |
| U3 | 관리자 통계 총계에 실패 행 포함 | **포함 + 상세 화면 '답변 실패' 표지**(`metadata.failed`) | 통계는 지금도 합성 행을 포함한 "저장된 행 수"다. 실패도 상담 요청이고, 숨기지 않는 것이 이 사이클의 방향. 네 집계 쿼리 무변경, 별도 집계(최근 30일 실패 N건)는 후속 후보 |
| U4 | 카나리 질문 도입 | **이번 범위 밖** | 월 ≈ $24 크레딧(잔액 $12.30) — 결제 승인 뒤 별도 사이클 |

---

## 9. Next Steps

1. [x] U1~U3 확정(2026-10-30) → `/pdca design llm-fallback-alert-blindspot`
2. [ ] Do 순서(제안): ① 실패 행 헬퍼 + 페이로드(`storage`/`pipeline`) ② `process_question` `except RuntimeError` 배선 ③ `api/index.py` 두 SSE 경로 배선 ④ `PUBLIC_EXCLUDE_KEYS` ⑤ `check_llm_fallback.py` R2·요약·힌트 ⑥ 테스트 4종 ⑦ 로컬 재현(만료 토큰) ⑧ 문서
3. [ ] PR(브랜치 `fix/fallback-alert-blindspot`) → Codex·CodeRabbit → 머지 → 배포 → `workflow_dispatch` 1회
4. [ ] Report에 보관 보고서 F-4 완료 표기, memory 갱신

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-10-30 | 초안 — 실패 경로 분류(a)~(f), A1 채택·대안 7종, FR-01~11, 사용자 결정 U1~U4 | Claude |
| 0.2 | 2026-10-30 | §8 확정 — U1 12h · U2 동일 저장 · U3 포함+표지 · U4 범위 밖 | 사용자·Claude |
