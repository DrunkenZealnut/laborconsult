# llm-fallback-alert-blindspot — 완료 보고서

> **Status**: Complete (코드·테스트·문서) — PR·배포·양성 검증은 머지 뒤
>
> **Project**: laborconsult
> **Version**: main `a78921a` 기준 브랜치 `fix/fallback-alert-blindspot`(미커밋) · Plan v0.2 · Design v0.2 · Analysis(Check 95.1% → Act 99.0%) · Report v1.0
> **Author**: Claude
> **Completion Date**: 2026-11-03
> **PDCA Cycle**: #1 (ai-gateway-oidc-migration 후속 F-4)

---

## Executive Summary

### 1.1 Project Overview

| Item | Content |
|------|---------|
| Feature | llm-fallback-alert-blindspot: 저장 전에 끝나는 LLM 실패(전 제공자 실패, 답변 중 예외)를 답변 없는 실패 행으로 기록하고, 폴백 감시가 그 행을 읽어 알리게 한다 |
| Start Date | 2026-10-30 (Plan v0.1 작성, U1~U4 확정) |
| End Date | 2026-11-03 (Report 작성). Act 반영은 2026-11-02 |
| Duration | 2026-10-30 ~ 2026-11-03 (Plan·Design·Do·Check 10-30, Act 11-02, Report 11-03) |
| 변경 규모 | 코드·테스트·운영 문서 10개 파일 +767 / -59 (미커밋) + `.bkit/state/memory.json` · 보관 보고서 F-4 진행 표기 2파일 +7 / -6. 미추적 문서 3종(Plan·Design·Analysis)과 이 보고서 |
| 기록 방식 | `pipeline.record_failed_conversation()` 단일 헬퍼. 호출부 3곳(파이프라인, SSE 두 경로, 동기 경로)은 서로 배타라 요청당 최대 1행 |

### 1.2 Results Summary

```
┌──────────────────────────────────────────────────────────────┐
│  Match Rate (Check → Act):  95.1%  →  99.0%  (101/102)       │
│  실패 행 기록:              전 제공자 실패 + 답변 중 예외      │
│  로컬 재현:                 만료 토큰, 실패 행 1건 확인, 비용 $0│
│  테스트:  T-F1~F8 · alert 27 OK · 변이 검사 7/7               │
│  PR·배포:                   미실시 (커밋은 사용자 요청 시에만)  │
│  잔여:    ⚠️ 1건(#67 T-F6 수식 비교) · 후속 Low 5건 · 운영 사항 │
└──────────────────────────────────────────────────────────────┘
```

### 1.3 Value Delivered

| Perspective | Content |
|-------------|---------|
| **Problem** | 감시는 저장된 대화만 읽었다. 전 제공자가 실패하면 대화가 저장되지 않아 전면 장애가 "✅ 정상" 또는 "판정 불가"로 보였다. 2026-10-14 사례를 B4 테스트로 재구성하면 기존 판정은 `insufficient`(알림 없음)이고 신규 판정은 `alert`다. |
| **Solution** | 전 제공자 실패와 답변 중 예외마다 실패 행을 남긴다(`answer_text=""`, `metadata.failed=True`, 예외 클래스명과 HTTP 상태만 저장). 감시에 "최근 12시간 안의 실사용 실패 행 1건이면 알림" 규칙(R2)을 더하고, 요약에 마지막 실사용 경과와 24시간 실패 수를 표시한다. 새 테이블·DDL·Secret은 없다. |
| **Function/UX Effect** | 사용자 화면과 정상 답변 경로는 바뀌지 않는다. 로컬 재현(만료 토큰, 비용 $0)에서 SSE는 `error → ping → done`을 내고, DB에는 실패 행 1건이 생겼다(제공자 실패 3건: Claude 401, OpenAI 401, Gemini 429). 프로덕션에서 전면 장애가 cron 주기(최대 6시간) 안에 드러나는지는 머지·배포 뒤 확인이 필요하다. |
| **Core Value** | 감시 원칙 "실패가 조용히 사라지지 않게 한다"의 마지막 사각인 저장 전 실패를 닫았다. Gateway 크레딧 소진이나 토큰 장애가 답변 0건 상태로 숨는 경로를 끊는다. |

---

## 2. Related Documents

| Phase | Document | Status |
|-------|----------|--------|
| Plan | [llm-fallback-alert-blindspot.plan.md](../../01-plan/features/llm-fallback-alert-blindspot.plan.md) | Approved (v0.2, U1~U4 확정) |
| Design | [llm-fallback-alert-blindspot.design.md](../../02-design/features/llm-fallback-alert-blindspot.design.md) | v0.2 (Check M-1·M-2 반영) |
| Check/Act | [llm-fallback-alert-blindspot.analysis.md](../../03-analysis/llm-fallback-alert-blindspot.analysis.md) | Complete (Check 95.1% → Act 99.0%) |
| Report | Current document | Complete |
| Parent | [ai-gateway-oidc-migration.report.md](../../archive/2026-10/ai-gateway-oidc-migration/ai-gateway-oidc-migration.report.md) §4.1 F-4 | v1.5(2026-11-03) '구현 완료·머지 대기' 진행 표기 완료 · '완료' 확정은 머지·배포 뒤 |

PR·커밋

| PR | 내용 | 상태 |
|----|------|------|
| 없음 | 브랜치 `fix/fallback-alert-blindspot`, main `a78921a`에서 분기. 전부 미커밋 | 커밋·PR은 사용자 요청 시 진행 |

---

## 3. Completed Items

### 3.1 Functional Requirements (Plan 완료 조건 대비)

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| FR-01 | (b) 전 제공자 실패 시 실패 행 기록 | Complete | `pipeline.py` `process_question`의 `except RuntimeError` 분기가 `record_failed_conversation(stage="answer")`를 부른다. T-F1·T-F2 |
| FR-02 | (c) 답변 중 예외 시 실패 행 기록 | Complete | `api/index.py` SSE GET·POST의 `except Exception`, 동기 `POST /api/chat`의 except. `stage="pipeline"`. T-F7 |
| FR-03 | 기록은 fail-open, 안내 먼저 | Complete | 파이프라인: `error → ping → 기록 → done`. SSE 두 경로: `error → 기록 → done`(Check M-1 조치 후). 기록 실패는 WARNING으로 끝난다. T-F1~F3, T-F7 |
| FR-04 | 비밀·본문 비저장·비출력 | Complete | 예외 메시지 원문 미저장, 클래스명과 HTTP 상태만 저장. `FAILURE_META_KEYS` 9키 화이트리스트. T-F1이 키 화이트리스트와 메시지 원문(`SECRET` 문자열) 부재를, T-F4가 stage=pipeline 페이로드와 상태 추출 세 모양을 단언 |
| FR-05 | `failed`를 게시판 제외 키에 추가 | Complete | `storage.py` `PUBLIC_EXCLUDE_KEYS`에 `failed` 추가(6종). `test_offline_units.py`가 키와 `True`일 때만 기록을 단언. 필터(`_apply_guard_filter`)·후처리(`_drop_flagged`)는 같은 튜플을 읽어 자동 반영되고 기존 회귀(`test_abuse_guard.py` 게시판 필터 폴백, `test_llm_fallback.py` T7)가 그 구조를 고정한다. `failed` 행을 직접 넣은 엔드포인트 회귀는 없음(4.1 D-d) |
| FR-06 | synthetic 규약 유지 | Complete | 실패 행에도 G-A·G-B·G-C를 그대로 적용. T-F5 |
| FR-07 | 감시 R2: 최근 12시간 실사용 실패 행 1건 이상이면 알림 | Complete | `check_llm_fallback.py` `judge()`. R1은 유지. B1·B2·B3·B4·B5·B5b |
| FR-08 | 요약에 마지막 실사용 경과·24시간 실패 수 표시 | Complete | 알림 사유가 아니다. B6·B8·B9 |
| FR-09 | 상태 코드별 점검 힌트 | Complete | 402 힌트 단언 추가(Check L-4 조치). B11·B12 |
| FR-10 | 문서 갱신 | Complete | `CLAUDE.md` 폴백 감시 절과 제외 키 6종, `check_llm_fallback.py` docstring, 워크플로 주석 갱신. memory 본문·인덱스 줄 갱신(11-03). L-8 문서 정합 4건 반영 — CLAUDE.md 실패 페이로드 키에 `provider(None)` 추가, docstring 첫 줄 R2, docstring '지킬 것 셋' → '다섯'(CLAUDE.md와 일치), memory 인덱스 |
| FR-11 | 킬스위치 `FAILURE_RECORD=off` | N/A | 설계 결정 D-5로 도입하지 않음. 기록이 fail-open이고 되돌리기는 PR revert로 충분하다 |

### 3.2 Non-Functional Requirements

| Item | Target | Achieved | Status |
|------|--------|----------|--------|
| 성능 | 실패 경로에만 추가 저장. 정상 경로 불변 | 실패 경로에 저장 3왕복 추가(세션 조회·갱신, 행 삽입). 안내를 먼저 보내 사용자 대기는 늘지 않음. 로컬 재현의 `error`→`done` 간격은 미측정 | 부분 (간격 측정 미실시) |
| 저장소 | DDL 0건, 새 테이블·컬럼·RPC·Secret 없음 | `.sql` 변경 0건, 신규 Secret 0건 | Complete |
| 보안·개인정보 | 토큰·키·메시지 원문 0건. 질문 원문은 정상 대화와 같은 범위 | 로컬 재현 행에서 토큰 패턴과 URL이 0건. 방침 제5항 범위 안이라 방침 변경 불요(U2) | Complete |
| 감시 원칙 | 감시는 fail-closed, 판정은 fallback·failed 기준 | 조회 실패 시 exit 2 유지. 제공자 이름으로 판정하지 않음 | Complete |
| 테스트 | 전부 오프라인, CI 편입. 변이 검사 | 오프라인 전부 통과. 변이 검사 7/7 | Complete |

### 3.3 Deliverables

| Deliverable | Location | Status |
|-------------|----------|--------|
| 실패 행 헬퍼, 상태 코드 추출, 실패 전용 페이로드 | `app/core/pipeline.py` (`record_failed_conversation`, `_failure_llm_meta`, `_status_of`, `FAILURE_META_KEYS`) | Complete |
| 카테고리·synthetic 판정 추출(성공 경로와 공유) | `app/core/pipeline.py` (`_category_for`, `_synthetic_flag`) | Complete |
| 전 제공자 실패 분기 배선 | `app/core/pipeline.py` (`process_question`) | Complete |
| 답변 중 예외 배선 (SSE 두 경로, 동기 경로) | `api/index.py` | Complete |
| 게시판 제외 키 6종 | `app/core/storage.py` (`PUBLIC_EXCLUDE_KEYS`) | Complete |
| 감시 R2, W 구간 조회, 요약, 힌트, `--fail-window` | `check_llm_fallback.py` | Complete |
| 관리자 상세 표지(stage별 문구) | `public/admin.html` | Complete |
| 오프라인 테스트 | `test_llm_fallback.py`, `test_llm_fallback_alert.py`, `test_offline_units.py` | Complete |
| 설계·분석·계획 문서 | `docs/01-plan/`, `docs/02-design/`, `docs/03-analysis/` (미추적) | Complete |
| 운영 문서 | `CLAUDE.md`, `.github/workflows/llm-fallback-alert.yml` 주석 | Complete |
| 보관 보고서 F-4 진행 표기 | `docs/archive/2026-10/ai-gateway-oidc-migration/ai-gateway-oidc-migration.report.md`(v1.5 — Status·§4.1·§8.2·§9), `docs/archive/2026-10/_INDEX.md` | Complete ('완료' 확정 표기는 머지 뒤) |

### 3.4 제약 준수

| # | 제약 | 준수 여부 | 근거 |
|---|------|-----------|------|
| 1 | 추가 결제·크레딧 구매 금지 | 준수 | 로컬 재현은 전 호출이 401이라 비용 $0. 카나리(U4)는 범위 밖 |
| 2 | 토큰·키·예외 메시지 원문 비출력 | 준수 | 재현 결과는 키 이름·불리언·상태 코드만 확인. 신규 저장 필드는 클래스명과 상태 코드만 |
| 3 | 제공자 키로 우회하는 경로 신설 금지 | 준수 | 신규 경로 없음. 실패 기록은 기존 저장 함수만 사용 |
| 4 | 모델 임의 대체 금지 | 준수 | 모델 설정 미변경 |
| 5 | SDK 버전 불변 | 준수 | 의존성 파일 변경 없음 |
| 6 | 임베딩·Pinecone 불변 | 준수 | 검색 경로 미변경 |
| 7 | DDL·Secret 신설 금지 | 준수 | `.sql` 변경 0건 |
| 8 | 정상 경로 동작 불변 | 부분 준수 | 카테고리·synthetic 판정을 함수로 추출(동작 동일)하고 `failures.append` 2줄을 추가했다. Plan의 "정상 경로 코드 diff 0"을 문자 그대로는 충족하지 않으나 기존 테스트가 동작 동일을 확인한다 |

---

## 4. Incomplete Items

### 4.1 Definition of Done 미완 항목

| # | Item | Reason | Priority |
|---|------|--------|----------|
| D-a | PR 생성, Codex·CodeRabbit 리뷰 반영, 머지 | 커밋은 사용자 요청 시에만 진행 | High |
| D-b | Vercel 배포 | PR 머지 뒤 | High |
| D-c | `workflow_dispatch` 1회 수동 실행 exit 0, 요약에 "마지막 실사용 답변" 줄 확인 | 배포 뒤 | High |
| D-d | 공개 게시판 API(`/api/board/recent`·`search`·`{id}`) 실패 행 미노출 회귀 | 현재는 키 단언과 구조 보장(`_apply_guard_filter`·`_drop_flagged`·상세 조회)만 있다. 엔드포인트 단위 테스트는 없다 | Medium |
| D-e | 보관 보고서 F-4 '완료' 확정 표기 | 11-03 v1.5로 '구현 완료·머지 대기' 진행 표기까지 했다. 확정은 머지·배포·`workflow_dispatch` 뒤 | Low |
| D-f | 로컬 재현의 `error`→`done` 간격 측정 | 미측정 | Low |

### 4.2 Cancelled/On Hold Items

| Item | Reason | Alternative |
|------|--------|-------------|
| 킬스위치 `FAILURE_RECORD` (FR-11) | D-5: 기록은 실패 경로에서만 돌고 fail-open이라 사용자 영향이 없다. 환경변수는 재배포 반영 의미론을 늘린다 | PR revert |
| 초기화 실패 기록 (Plan (d)) | 초기화 실패 시 Supabase 핸들이 없을 수 있다 | 한계로 명시. 감시 조회도 같은 원인이면 exit 2로 드러난다 |
| 능동 카나리 질문 (U4) | 6시간 주기 시 월 약 $24 크레딧 소비. 결제 제약과 충돌 | 사용자 승인 뒤 별도 사이클 |
| 요청 수 대비 저장 수 비교 (B) | anon 조회 RPC 신설(DDL)이 필요하고 가드가 fail-open이라 누락이 생긴다 | 보류 |
| `/api/health` 실패 카운터 (E) | 인스턴스별 메모리라 콜드 스타트마다 0 | 보류 |
| 관리자 목록 표지 | `admin_conversations` 별칭 투영의 실측이 없어 목록이 멈출 위험 | 상세 화면 표지만 적용. 후속 후보 |
| 동기 `POST /api/chat`의 응답 변경(500 → 안내 본문) | 프런트는 SSE만 쓴다. 현행 동작 불변 원칙 | 실패 행만 기록하고 원 예외를 다시 올린다(500 유지) |

### 4.3 한계와 위험 (Check 단계 R-1~R-3 포함)

| ID | 내용 | 대응 |
|----|------|------|
| R-1 | 프로세스가 죽는 장애(배포 손상으로 import 실패, maxDuration 초과, OOM)는 except에 도달하지 않아 실패 행이 0건이다. R1·R2가 모두 침묵한다 | 후속 후보: 워크플로에서 `/api/health`를 1회 호출(LLM 미사용, 비용 $0) |
| R-2 | 결정적 코드 결함(특정 질문이나 첨부 모양)은 재시도마다 행을 쌓아 12시간 동안 cron마다 메일이 나간다 | stage별 제목으로 완화(M-2 조치). 운영 절차에 stage=pipeline 대응(수정·revert)을 명시하는 작업은 미반영 |
| R-3 | 의도분석 단계 예외 등 게이트 판정 전 예외는 질문 원문이 실린 실패 행으로 저장된다. 게시판에는 실리지 않지만 관리자 화면에는 보인다. U2 범위를 약간 넘는다 | 수용 여부 결정이 필요하다(사용자 결정) |
| Plan §5 | 기록 자체가 Supabase 장애에 걸리면 행이 남지 않는다 | 감시 조회도 실패해 exit 2로 드러난다. 설계상 수용 |
| L-3 | 힌트 'other'가 INFO 줄("실패 행 저장")을 안내하지만 루트 로거가 WARNING이라 그 줄은 출력되지 않을 가능성이 높다 | 후속 Low: 안내 대상을 WARNING·ERROR 줄로 변경 |
| 관리자 표지 | 상세 화면 표지는 적용됐으나 목록 표지는 보류 | 후속 후보 |
| 감시 문구 | 전부 failed인 표본에서도 R1 문구("3건 연속 폴백")가 나올 수 있다(L-5, 미반영) | 후속 Low |

### 4.4 Analysis Low 잔여 항목

| ID | 현상 | 상태 |
|----|------|------|
| L-2 | 마지막 행의 `created_at`을 해석할 수 없으면 '창을 덮음'으로 본다 | 설계에 명시해 수용. 요약에 "R2 창 미확인" 줄은 없음 |
| L-5 | 전부 failed인 표본에서 R1 문구가 "연속 폴백"으로 나온다 | 미반영 |
| L-6 | T-F6은 수식을 재구현해 비교한다(분석 #67, 잔존 ⚠️ 1건). T-F7은 강화됨 | T-F6은 성공 경로 행과 직접 비교로 바꿀 후보 |
| L-8 | 문서 정합 4건(CLAUDE.md의 llm 키 열거에 `provider` 누락, docstring 첫 줄, "지킬 것" 개수, memory 인덱스 줄) | 반영 완료 — 첫 줄·인덱스는 Act(11-02), `provider` 키·'지킬 것 다섯'은 Report 단계(11-03) |
| L-9 | `--fail-window`에 0 이하를 주면 R2가 조용히 꺼진다 | 후속 Low: 0보다 큰지 검증 |
| L-10 | 기존 결함: `fetch` 중복 집계가 페이지 경계 중복을 센다. R1 판정이 두 곳에 중복돼 있다 | 후속 Low |

---

## 5. Quality Metrics

### 5.1 Final Analysis Results

| Metric | Target | Check (Final) | Act (Final) | Change |
|--------|--------|---------------|-------------|--------|
| Design Match Rate | 90% | 95.1% (97/102) | 99.0% (101/102) | +3.9%p |
| 대조 항목 | — | 102 (➕ 설계 밖 구현과 N/A — 목록 표지·FR-11 — 는 분모 제외) | 동일 | — |
| 설계 사각 | — | Medium 2 · Low 10 | Medium 2 전부 + Low 4 조치 (M-1·M-2·L-1·L-4) | Low 잔여는 4.4 |
| 잔존 ⚠️ | — | 5건 | 1건 (#67, T-F6 수식 비교) | — |
| 변이 검사 | 되돌리면 실패 | 6/6 (Do) | 7/7 (Do 6 + Act 1) | — |

Match Rate 99.0%는 설계 정정 9건과 Check 조치 반영 뒤 재계산한 값이다. Check 시점 95.1%는 설계 대비 구현 차이를 보여 주는 기록으로 남긴다.

### 5.2 Test Results (2026-11-03 재실행, 전부 rc=0)

| 테스트 | 결과 |
|--------|------|
| `test_llm_fallback.py` (T-F1~F8) | 통과 |
| `test_llm_fallback_alert.py` | 27 tests OK (Check 시 25건, Act에서 B11·B12 추가 등) |
| `test_offline_units.py` | 통과 |
| `test_abuse_guard.py` | 통과 |
| `test_pipeline_wiring.py` | 통과 |
| `test_llm_transport.py` | 26 OK |
| `test_law_api_recovery.py` | 42 OK |

### 5.3 Resolved Issues (Check 조치)

| Issue | Resolution | Result |
|-------|------------|--------|
| M-1: SSE 경로가 안내보다 기록을 먼저 해 DB 대기 동안 사용자가 안내를 못 받는다 (PostgREST 3왕복, 기본 타임아웃 120초) | 두 SSE 경로를 `error → 기록 → done`으로 바꿨다(`gen = _sse_error_events(...)` 분할). 동기 경로에 "답변 생성 실패(동기)" ERROR 로그 추가 | Resolved. T-F7이 AST로 문장 순서를 고정. 순서를 되돌리면 T-F7 실패를 확인 |
| M-2: stage=pipeline 실패를 "전 제공자 실패"로 표기 | 감시 제목과 `::error::`를 stage별로 나눴다(`_stage_counts`, `_failure_label`). 힌트에 pipeline 항목 추가. 관리자 표지도 stage별 문구 | Resolved. B12 |
| L-1: `_status_of`가 폴백 except 안에서 예외를 던질 수 있다 | 본문을 `try/except Exception → None`으로 감쌌다 | Resolved. T-F4에 속성 접근 예외 케이스 추가 |
| L-4: 402·NoProvider 힌트 단언이 항상 참인 no-op이었다 | no-op 단언 제거, B11 추가 (402·GatewayAuthError·NoProvider·중복 1회·빈 failures 폴백) | Resolved |
| L-7: 출력 형식이 설계와 다름 | 설계를 구현에 맞춰 정정 | Resolved |
| 설계 정정 9건 (분석 §5) | 제외 키 6종(counsel 포함), B5b·B5 행 수, 목록 표지 보류, §4.3 자기모순 해소, 해석 불가 시각 처리, 예외 메시지 적용 범위 한정 | Resolved (Design v0.2) |

---

## 6. Lessons Learned & Retrospective

### 6.1 What Went Well (Keep)

- 로컬 재현을 만료 OIDC 토큰으로 했다. 전 호출이 401이라 비용 없이 실제 전 제공자 실패 경로를 밟았다.
- 기록을 `record_failed_conversation()` 하나로 모았다. 성공 경로와 실패 경로가 카테고리·synthetic 판정을 같은 함수로 공유해 관리자 분포가 어긋나지 않는다.
- Check가 설계 자체의 모순을 찾았다. §4.3은 "안내 먼저"와 "INSERT 1회"를 함께 주장했는데, 기본 타임아웃 120초를 코드로 확인한 뒤 순서를 `error → 기록 → done`으로 확정했다.
- 변이 검사를 단계마다 돌려 테스트 공백을 찾았다. T-F7은 호출 위치를 옮겨도 통과하는 약한 단언이었고 Act에서 AST로 강화했다.

### 6.2 What Needs Improvement (Problem)

- 설계 문서의 숫자(제외 키 "4종·5종", 테스트 행 수)가 구현과 여러 번 어긋났다. 구현 전에 세지 않고 적었다.
- 로컬 검증 중 INFO 로그가 보이지 않았다. 루트 로거가 WARNING이라 INFO가 숨었다. 로그 대신 Supabase 조회로 행을 확인해야 했다.
- 힌트 단언 한 개(402)가 항상 참이었다. 픽스처에 해당 상태가 없었기 때문이다.
- 이번 변경으로 기존 결함(R1 중복 집계, L-10)의 노출 범위가 넓어졌다.

### 6.3 What to Try Next (Try)

- 로그 기반 검증 전에 로깅 레벨을 먼저 확인한다.
- 변이 검사 항목에 "조건이 항상 참인 단언" 확인을 포함한다. 픽스처에 해당 분기가 있는지 함께 본다.
- 설계 문서의 개수·키 목록은 구현 후 grep으로 대조한다.
- 실패 경로를 바꾸는 사이클은 Check 전에 "사용자가 받는 안내 순서"를 표로 먼저 확인한다.

---

## 7. Process Improvement Suggestions

### 7.1 PDCA Process

| Phase | Current | Improvement Suggestion |
|-------|---------|------------------------|
| Plan | 실패 경로를 표(a)~(f)로 분류해 대상을 고정했다 | 같은 표를 설계 단계에서 코드 지점과 함께 갱신 |
| Design | "안내 먼저"와 "INSERT 1회"를 함께 적어 모순이 생겼다 | 지연 상한은 전제(타임아웃·왕복 수)를 적고 계산 |
| Do | 로그 가시성을 가정하고 검증했다 | 검증 수단을 로그가 아닌 저장소 조회로 우선 |
| Check | gap-detector가 설계 대비만 판정해 경로 리뷰를 따로 했다 | 변경 경로 전수 리뷰를 Check 항목에 고정 (R-1~R-3이 그 결과) |

### 7.2 Tools/Environment

| Area | Improvement Suggestion | Expected Benefit |
|------|------------------------|------------------|
| 감시 | `/api/health` 사전 호출로 프로세스 사망 사각 보완 (R-1) | 배포 손상·타임아웃 조기 감지 |
| 감시 | 제목 문구를 전부 failed 표본에 맞게 조정 (L-5) | 메일 문구 정확도 |
| 관리 | 별도 집계 "최근 30일 실패 N건" (U3 후속) | 장기 추세 확인 |
| 비용 | 카나리 질문 (U4) | 승인 뒤 주기 감시 가능 |

---

## 8. Next Steps

### 8.1 Immediate (사용자 작업)

- [ ] 커밋과 PR 생성을 요청할지 결정 (커밋은 사용자 요청 시에만 진행)
- [ ] R-3 수용 여부 결정: 게이트 판정 전 예외의 질문 원문 저장
- [ ] 머지·배포 뒤 `workflow_dispatch` 1회 실행, exit 0과 요약 줄 확인
- [ ] 머지·배포 뒤 보관 보고서 F-4 '완료' 확정 표기(v1.5 진행 표기는 완료)
- [ ] 카나리(U4) 도입은 결제 승인 뒤 별도 사이클로 결정

### 8.2 Next PDCA Cycle

| Item | Priority | Expected Start |
|------|----------|----------------|
| 게시판 API 실패 행 미노출 엔드포인트 회귀 (D-d) | Medium | 머지 전 또는 직후 |
| R-1 프로세스 사망 사각: `/api/health` 사전 호출 | Medium | 다음 사이클 |
| R-2 운영 절차에 stage=pipeline 대응 명시 | Low | 다음 사이클 |
| L-2·L-3·L-5·L-9·L-10 Low 잔여 정리 | Low | 다음 사이클 |
| 관리자 목록 표지 (별칭 투영 실측 후) | Low | 실측 뒤 |
| 별도 집계 "최근 30일 실패 N건" | Low | 실사용 누적 뒤 |

---

## 9. 증거 (Evidence)

| 항목 | 값 |
|------|-----|
| 로컬 재현 (2026-10-30 22:02 KST, 만료 OIDC 토큰, `LLM_TRANSPORT=gateway`, 비용 $0) | SSE `error → ping → done`. DB 실패 행 1건: `answer_text` 0자, `metadata.failed=True`, `synthetic=True`, `llm.stage="answer"`, 제공자 실패 3건(Claude 401, OpenAI 401, Gemini 429), `transport="gateway"`. 페이로드에 토큰 패턴과 URL 0건 |
| 감시 로컬 실행 (2026-10-30, 변경된 감시 코드, 프로덕션 Supabase 조회) | exit 0. "마지막 실사용 답변: 10-28 22:39 KST (47.4시간 전) · 최근 24시간 실패 0건". 합성 실패 행은 R2에서 제외 확인 |
| 로그 확인 | "실패 행 저장" INFO 줄은 로그에 보이지 않았다(루트 로거 WARNING). 행은 Supabase 조회로 확인 |
| 테스트 (2026-11-03, rc=0) | 5.2 표 참조 |
| 변이 검사 | Do 6건(기록 호출 제거, `failed` 키 누락, 창 조건 제거, `degraded` failed 분기 제거, `_status_of` code 분기 제거, SSE GET 호출 제거) + Act 1건(SSE GET 순서 되돌림 → T-F7 실패). 7/7 |
| DDL·Secret | `.sql` 변경 0건, 신규 Secret 0건 |
| 변경 규모 | 코드·테스트·운영 문서 10개 파일 +767 / -59 (미커밋) + `.bkit/state/memory.json` · 보관 보고서 F-4 진행 표기 2파일 +7 / -6. 미추적 문서 3종(Plan·Design·Analysis)과 이 보고서. 정상 경로 변경은 함수 추출과 `failures.append` 2줄 |
| 비용 | 로컬 재현 $0. 카나리 없음 |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-11-03 | 완료 보고서 작성. Plan v0.2·Design v0.2·Analysis(95.1% → 99.0%) 기준, 브랜치 `fix/fallback-alert-blindspot` 미커밋 상태 기준 | Claude |
