# 챗봇 남용 가드 — 인젝션·오프토픽·비용 남용 차단 Completion Report

> **Summary**: 완전 무방비였던 채팅 3경로에 2단 가드(엔드포인트 공통 검사 + 파이프라인 내 인젝션/스코프 게이트)를 삽입해 악의적 접근과 노동법 외 용도 사용을 LLM 호출 전 또는 의도분석 1회 비용으로 차단. 설계 대비 98% 일치도로 구현, Supabase 배포·PR 머지까지 완료.
>
> **Project**: laborconsult
> **Feature**: chatbot-security
> **Date**: 2026-07-31
> **Match Rate**: 98% (65.5/67 items, Critical 0건, 의도적 이탈 2건)
> **Status**: Completed — main 머지 완료(PR #28), Supabase 스키마 배포·검증 완료, monitor 모드 관측 대기

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 채팅 3경로(`/api/chat`, GET/POST `/api/chat/stream`)는 비로그인 공개인데 rate limit·길이 제한·인젝션 방어·주제 게이트가 전무했다. 시스템 프롬프트가 "참고 자료가 없어도 일반 지식으로 답변"을 지시해 오프토픽 질문에도 파이프라인 전체(의도분석 Sonnet → RAG → 답변 LLM)가 완주했고, 모든 대화가 공개 게시판에 자동 전시되어 탈옥 답변이 다른 사용자에게 노출될 위험이 있었다. |
| **Solution** | 2단 가드 구조로 악성 요청을 저비용 지점에서 차단: ① 엔드포인트(`_guard_chat_request`)에서 입력 검증·rate limit·Supabase 쿼터/차단을 세션 생성·첨부 파싱보다 먼저 수행 ② 파이프라인(`process_question`) 내에서 정규식 인젝션 스캔(LLM 호출 0회로 차단)과 `analyze_intent` 편승 스코프 게이트(추가 LLM 호출 없이 오프토픽 차단)를 수행. 노동상담 언어와 공격 언어가 어휘를 공유하는 문제는 "제3자 주어 서술" 억제자로 해소해 실측 오탐 0건을 달성했다. |
| **Function/UX Effect** | 정상 노동상담은 오탐 없이 그대로 통과(공격 38케이스 차단율 100%, 정상 35케이스 오차단 0건, 스캔 오버헤드 0.06ms). 차단 응답은 기존 SSE 이벤트(`chunk`/`done`/`replace`/`error`)만 재사용해 프론트엔드 수정이 전혀 없었다. 두 가드 모두 monitor 모드로 배포되어 즉시 차단 없이 1주간 관측 후 전환한다. |
| **Core Value** | 무료 공개 노동상담 서비스의 비용 지속성(Denial of Wallet 방어)과 목적 부합성(노동법 상담 전용 유지)을 동시에 확보했다. Supabase 배포 과정에서 RLS·GRANT 권한 설계의 실전 함정(PUBLIC 경로 누락)을 실제 검증으로 발견·수정해, 문서로만 존재하던 보안 설계가 실제로 작동함을 확인했다. |

---

## PDCA Cycle Summary

### Plan (Planning Phase)

**Document**: `docs/01-plan/features/chatbot-security.plan.md`

SafeFactory 프로젝트의 동일 사이클(plan v0.2 / design v0.1)을 준거 문서로 삼되, laborconsult 코드 실측으로 완전히 재작성했다. 두 프로젝트의 구조 차이 7건(§1.4)을 먼저 정리한 것이 이후 설계 전체의 기반이 됐다:

- **저장소**: SafeFactory는 Flask+SQLite(단일 서버)였으나 laborconsult는 Vercel 서버리스(인스턴스 비영속) → SQLite 불가, Supabase로 치환
- **스코프 게이트**: SafeFactory는 기존 관련성 문턱(abstention gate)이 있어 "감싸는" 설계였으나, laborconsult는 관련성 게이트 자체가 없어 **신설**이 필요 — 이것이 사용자 요구("노동법 질문 이외 용도 차단")의 핵심
- **오염 대상**: SafeFactory는 시맨틱 캐시(TTL 1시간)였으나 laborconsult는 **공개 게시판 영구 전시**(`qa_conversations` 자동 저장 → `/api/board/*`) — 더 높은 우선순위로 재설계

**위협 모델**: OWASP LLM Top 10 매핑 T1~T9 (Denial of Wallet, Prompt Injection, System Prompt Leakage, Unbounded Consumption 등)

**요구사항**: FR-01~FR-13 (P0 4건, P1 5건, P2 4건)

### Design (Design Phase)

**Document**: `docs/02-design/features/chatbot-security.design.md` (v0.2)

**v0.1 → v0.2 개정 배경**: design-validator 에이전트 검증에서 Critical 3건이 발견되어 즉시 반영했다.

| Critical | 문제 | 해결 |
|----------|------|------|
| C-1 | Supabase RLS/GRANT 설계 부재 — `SUPABASE_KEY`가 anon 키인데 신규 테이블에 정책이 없으면 쿼터·차단이 fail-open으로 조용히 무력화되거나, 정책을 잘못 열면 클라이언트가 차단을 자가 해제 가능 | 테이블은 RLS ENABLE + 정책 무부여로 잠그고, 접근은 `SECURITY DEFINER` RPC 4개로만 |
| C-2 | 초안 인젝션 정규식이 정상 노동상담을 오차단("회사가 기존 지침을 무시하고..." 등) | 억제자(`_BENIGN_ACTOR`) 패턴 도입 — 매치 앞 25자에 회사·상사 등 제3자 주어가 있으면 해당 카테고리 무효화. 실측 스크립트로 확정: 공격 38건 차단율 100%, 정상 35건 오차단 0건, 스캔 0.06ms |
| C-3 | 게시판 오염 필터가 `board_detail`에서 metadata를 select하지 않아 무력화, `board_posts`에 적용하면 metadata 컬럼 부재로 사용자 글이 전멸 | 필터를 `qa_conversations` 한정으로 명시, `board_detail` select에 metadata 추가 |

**핵심 아키텍처 결정**:
1. 2단 배치: 엔드포인트(길이·rate limit·쿼터) → 파이프라인(인젝션·스코프·유출) — 저비용→고비용 순
2. 스코프 판정은 `ANALYZE_TOOL`에 `is_labor_related` 필드 편승 — 매 질문 이미 실행되는 의도분석에 얹어 **추가 LLM 호출 0회**
3. 전 계층 fail-open — 가드 예외·Supabase 장애가 상담 서비스를 막지 않음(CLAUDE.md graceful degradation 관례)
4. 거절 응답은 신규 SSE 이벤트 없이 기존 `chunk`/`done`/`replace`/`error`만 재사용

### Do (Implementation)

**Scope**: 신규 8개 파일 + 수정 9개 파일, 약 3,681줄 변경

| File | Type | Details |
|------|:----:|---------|
| `app/core/abuse_guard.py` | 신규(390줄) | `validate_message`·`scan_injection`·`scope_gate_decision`·`scan_leak`·`check_guard`·`record_violation`·`GuardContext`·`GuardRejection` — 전부 fail-open |
| `api/index.py` | 수정(+234줄) | `_guard_chat_request` 공통 헬퍼(3경로 배선, 세션 생성·첨부 파싱보다 먼저 호출), 게시판 필터 4곳, admin 남용 현황 API 2종 |
| `app/core/pipeline.py` | 수정(+103줄) | `guard_ctx` 인자, 인젝션 스캔 훅(의도분석 이전), 스코프 게이트(의도분석 직후), 첨부 경계 래핑, 유출 감지(면책 고지 이전), 저장 게이팅 |
| `app/core/analyzer.py` | 수정 | `AnalysisResult.is_labor_related` 반환 배선 |
| `app/models/schemas.py` | 수정 | `is_labor_related: bool = True`(fail-open 기본값), 메시지 하드캡 20,000자 |
| `app/templates/prompts.py` | 수정(+41줄) | `ANALYZE_TOOL`에 스코프 필드, `INJECTION_RESISTANCE` 접미(format 이후 결합) |
| `supabase_abuse_guard.sql` | 신규(227줄) | 테이블 3종(`chat_quota`/`block_list`/`abuse_events`) + RPC 4종, RLS+GRANT 권한 |
| `supabase_abuse_guard_verify.sql` | 신규(161줄) | 배포 후 양성 검증 — 9항목 단일 표 출력 |
| `supabase_abuse_guard_rollback.sql` | 신규(35줄) | 되돌리기 스크립트 |
| `test_abuse_guard.py` | 신규(735줄) | 오프라인 테스트 20그룹 |
| `.github/workflows/tests.yml` | 수정 | 남용 가드 테스트 CI 등록 |
| `.env.example`, `CLAUDE.md` | 수정 | env 10종 문서화, Abuse Guard 운영 관례 |

**핵심 구현 결정 — 인젝션 패턴 실측 확정**:

초안 정규식은 오탐이 있어(§Design C-2), 별도 스크립트로 가중치·억제자 설계를 실측 검증한 뒤 최종본을 확정했다. 이 확정본을 코드에 그대로 이식했다.

```
공격 38케이스 → 차단율 100%
정상 노동상담 35케이스 → 오차단 0건
scan_injection() 오버헤드 → 0.06ms (250자 입력, 2000회 평균)
```

**동작 실증**: 가짜 LLM 클라이언트(모든 속성 접근이 예외를 던지는 스텁)를 주입해 차단 경로를 직접 실행했다.

- 인젝션 block 시 이벤트가 `['chunk', 'done']` 뿐 — LLM 클라이언트 접근 0회
- 오프토픽 block 시 이벤트가 `['status', 'chunk', 'done']` — 의도분석 1회 후 RAG·답변 LLM 생략
- 두 경우 모두 세션 이력에 미기록(인젝션 문자열의 후속 턴 재주입 차단)
- `guard_ctx=None`(CLI·벤치마크·E2E 테스트 호출부)은 가드 전면 비활성 — 기존 동작 무변경

### Check (Gap Analysis)

**Document**: `docs/03-analysis/chatbot-security.analysis.md`

**gap-detector 에이전트**가 설계 명세 67개 항목을 코드와 1:1 대조해 최초 Match Rate **93%**를 산출했다. Critical 0건이었으나 Major 2건은 실제 결함으로 판정되어 즉시 수정했다.

| Major | 문제 | 영향 | 수정 |
|-------|------|------|------|
| G-1 | 길이 위반이 `abuse_events`에 기록되지 않음 | DDL의 자동 차단 카운트(`event_type IN ('injection','quota','length')`)에서 `length` 분기가 죽은 코드 — 대량 길이 공격이 무증상 | Supabase 핸들 확보를 앞당기고 `record_violation("length", ...)` 추가 |
| G-2 | 게시판 필터 폴백이 쿼리 **빌드**만 감싸고 **실행**(`.execute()`의 PostgREST 400)은 못 잡음 | 설계가 의도한 "빈 목록·500 회피" 폴백에 도달하지 못해 필터 실패 시 게시판 전체가 500 | 실행까지 감싸는 `_fetch_qa_public(build)` 헬퍼로 교체, 3곳 전환 |

Minor 5건 중 2건(`validate_message` fail-open 누락, `session_id` 정규식이 후행 개행 허용)도 함께 수정했고, 나머지 2건은 **의도적 설계 이탈**로 판정해 구현을 정답으로 유지했다(`ratelimit` 이벤트 DB 미기록 — 인메모리로 이미 차단된 요청마다 INSERT하면 요청 폭주가 DB 쓰기 증폭이 되는 역효과 방지).

수정 후 테스트를 17그룹 → 20그룹으로 보강하며 "소스 문자열 존재 확인"에서 "실제 동작 검증"으로 전환했다(예: 저장 게이팅은 스텁 config로 `process_question`을 실제 소진해 `guard_flag` 부착 여부를 확인).

**Match Rate 93% → 98%** (수정 후, 90% 기준 통과)

### Act (Completion)

**Iteration Count**: 1 (Check에서 발견된 Major 2·Minor 2를 즉시 수정, 90% 기준을 넘겨 별도 iterate 사이클 불요)

**Quality Metrics**:

| 지표 | 목표 | 달성 |
|------|:---:|:---:|
| Match Rate | ≥90% | 98% |
| Critical 이슈 | 0 | 0 |
| 인젝션 차단율 | ≥90% | 100% (38/38) |
| 인젝션 오탐 | 0 | 0 (0/35) |
| 스캔 오버헤드 | <5ms | 0.06ms |
| 오프라인 테스트 그룹 | — | 20 (17 → 20 보강) |
| 기존 스위트 회귀 | 0건 | 0건 (계산 골든·배선·오프라인 단위·렌더러 전부 통과) |
| CI 통과 | 필수 | offline-tests·Vercel·GitGuardian 전부 pass |

---

## Results

### Completed Items

- ✅ **FR-01** 입력 검증: 길이 2,000자·제어문자·`session_id` 형식(불일치 시 신규 발급)
- ✅ **FR-02** rate limit: IP당 5회/60초, 채팅 전용 버킷 분리
- ✅ **FR-03** 일일 쿼터: Supabase RPC 1왕복, IP당 50회/일
- ✅ **FR-04** 인젝션 가드: 정규식+가중치, 의도분석 이전 배치로 차단 시 LLM 호출 0회
- ✅ **FR-05** 노동법 스코프 게이트: `analyze_intent` 편승, 추가 LLM 호출 0회로 오프토픽 차단
- ✅ **FR-06** 시스템 프롬프트 인젝션 저항 접미(format 이후 결합)
- ✅ **FR-07** 첨부 문서 경계 래핑(간접 인젝션 완화)
- ✅ **FR-08** 유출 감지(시그니처 2개 이상 동시 적중 시에만 판정 — 우연 일치 방지)
- ✅ **FR-09** 저장·게시판 오염 방지(차단 미저장, monitor flag 게시판 제외)
- ✅ **FR-10** 남용 이벤트 로깅(Supabase `abuse_events`, PII 최소화)
- ✅ **FR-11** 자동 임시 차단(윈도우 내 위반 누적, `SECURITY DEFINER` RPC)
- ✅ **FR-12** 관리자 남용 현황 API(`GET/POST /api/admin/abuse*`)
- ✅ **FR-13** 운영 하드닝 문서화(`ALLOWED_ORIGINS` 실값 권고)
- ✅ **기존 기능 영향 없음**: `guard_ctx=None` 호출처(벤치마크·E2E 테스트) 전수 확인, 기존 오프라인 스위트 3종 + 렌더러 무회귀
- ✅ **Supabase 배포·검증 완료**: 테이블 3·RPC 4·권한 이중 회수(역할+PUBLIC) 실제 적용 및 9항목 양성 검증 전부 통과
- ✅ **PR 머지 완료**: PR #28 → main (`72c301e`), CI 전체 통과

### Implementation Notes

**설계 대비 구현 이탈 2건 (의도적, 구현이 정답)**:
1. RPC의 자동 차단 카운트 쿼리에 `AND mode = 'block'` 추가 — monitor 모드는 관측 목적이라 차단 판정에서 제외(§5.10 산문 의도와 일치, 최초 SQL 본문에는 누락)
2. `validate_message`에 `unicodedata.normalize("NFC", ...)` 적용 — 설계 미기재이나 유니코드 정규화는 기존 프로젝트 관례(`filetree.py`)와 일치, 무해한 개선

**환경변수** (전부 선택, 미설정 시 안전한 기본값):
```
MAX_MESSAGE_LENGTH=2000        CHAT_RATE_LIMIT=5          CHAT_RATE_WINDOW=60
DAILY_CHAT_QUOTA=50            ABUSE_GUARD_MODE=monitor   SCOPE_GATE_MODE=monitor
INJECTION_BLOCK_THRESHOLD=3    ABUSE_BLOCK_WINDOW=300     ABUSE_BLOCK_THRESHOLD=10
ABUSE_BLOCK_MINUTES=30
```

---

## Testing Summary

**오프라인 테스트** (`test_abuse_guard.py`, API 키·네트워크 불요, CI 등록): **20개 그룹 전부 통과**

| 그룹 | 검증 방식 |
|------|-----------|
| 입력 검증 | 길이·제어문자·빈입력·session_id 형식(개행 거부·레거시 호환 포함) |
| 인젝션 차단율 | 공격 38케이스 → 100% |
| 인젝션 오탐 | 정상 35케이스 → 0건 |
| 억제자 | 제3자 주어 서술 무효화 + 윈도우 경계 |
| 성능 | scan_injection 0.06ms |
| 스코프 게이트 | 전 분기 + fail-open(판정 실패→allow) |
| 유출 감지 | 2개 이상 적중 시에만 판정, 정상·인용 답변 오탐 0 |
| 쿼터·차단 RPC | 통과·차단·쿼터 분기 + fail-open 3종 |
| 자동 차단 | RPC 인자·detail 상한·fail-open |
| 채팅 rate limit | 5회/60초 경계 + 버킷 분리 |
| 엔드포인트 가드 | 통과·400·429 변환 |
| 파이프라인 배선 | guard_ctx·인젝션·스코프·유출·저장 게이팅 |
| **차단 경로 동작** | LLM 호출 0회(Exploding 스텁) + 세션 이력 미기록 + guard_ctx=None 무영향 |
| **저장 게이팅 동작** | monitor 대화만 guard_flag 부착 저장(스텁으로 실제 소진) |
| 스코프 스키마 | tool·required·AnalysisResult·analyzer 배선 |
| 프롬프트 접미 | 중괄호 없음 + format 이후 결합 |
| 게시판 필터 | qa 4곳(metadata select 포함) + board_posts 미적용 |
| **게시판 필터 폴백** | execute() 400 → 무필터 재조회 + Python 후처리(500 회피) |

**회귀 검증**: `test_wage_golden.py` / `test_pipeline_wiring.py` / `test_offline_units.py` / `test_answer_renderer.js`(pass 8/fail 0) 전부 무회귀

**엔드포인트 스모크** (FastAPI TestClient): health 200, 길이초과 400, 빈 메시지 400, GET 스트림 SSE error, admin 무인증 401, board 503(Supabase 미설정 시)

**Supabase 배포 검증** (`supabase_abuse_guard_verify.sql`, 9항목):

| # | 항목 | 결과 |
|---|------|:---:|
| 1 | 쿼터 — 상한 3에서 4번째 요청 거부 | ✅ |
| 2 | 자동 차단 — 위반 3회 누적 시 발동 | ✅ |
| 3 | 차단 적용 — 차단된 키의 다음 요청 거부 | ✅ |
| 4 | monitor 모드 — 위반 3회에도 차단 없음 | ✅ |
| 5 | 수동 해제 — 해제 후 재요청 허용 | ✅ |
| 6 | 관리자 현황 — `abuse_summary` 응답 형식 | ✅ |
| 7 | 권한 — anon의 `abuse_events` 직접 조회 거부 | ✅ (수정 후) |
| 8 | 권한 — anon의 RPC 호출 허용 | ✅ |
| 9 | 검증 흔적 정리 | ✅ |

---

## Lessons Learned

### What Went Well

1. **설계 검증 에이전트의 실질적 기여**: design-validator가 v0.1 단계에서 발견한 Critical 3건(RLS 권한 부재·인젝션 오탐·게시판 필터 무력화)이 실제 코드에도 나타났을 결함이었다. 구현 전 설계 단계에서 걸러진 것이 이후 사이클 전체의 안정성을 높였다.
2. **실측 우선 설계**: 인젝션 패턴을 "그럴듯한 정규식"이 아니라 스크립트로 공격 38·정상 35케이스를 실제로 돌려 확정했다. 억제자 도입 전후 오탐이 4건에서 0건으로 줄어드는 과정을 수치로 확인하고 코드에 그대로 이식했다.
3. **gap-detector가 실전 결함을 발견**: Major 2건(G-1 길이 이벤트 미기록, G-2 게시판 필터 실행 시점 예외 미포착) 모두 "설계는 맞게 썼지만 구현이 설계의 의도를 놓친" 유형으로, 코드 대조 없이는 발견하기 어려운 결함이었다.
4. **fail-open 원칙의 배포 단계 재확인**: fail-open은 "조용한 실패"라는 특성상 배포 후 검증 없이는 무력화 여부를 알 수 없다. 이 원칙을 설계 문서에만 남기지 않고 `supabase_abuse_guard_verify.sql`이라는 실행 가능한 검증 스크립트로 구현해 실제로 문제(PUBLIC 권한 누락)를 잡아냈다.
5. **동작 검증으로의 전환**: Check 단계에서 "소스에 토큰이 있는지"를 확인하던 테스트 3그룹을 "실제로 그 동작이 일어나는지"로 교체한 것이 이후 배포 검증 스크립트 설계에도 동일하게 적용됐다.

### Areas for Improvement

1. **Supabase 권한 검증 환경의 재현 정확도**: 로컬 Docker Postgres 검증 환경에 처음엔 `anon` 역할 자체가 없었고, 두 번째 시도에선 `anon`/`authenticated`에만 권한을 걸어 PUBLIC 경로 누락을 놓쳤다. 실제 배포 환경(Supabase의 `ALTER DEFAULT PRIVILEGES`)을 처음부터 정확히 재현했다면 사용자가 두 번 재실행하는 수고를 줄일 수 있었다.
2. **디자인 문서와 SQL 본문의 미세한 불일치**: `record_abuse_event` RPC의 카운트 쿼리에 `mode='block'` 조건을 추가한 것이 설계 §5.10 산문과는 일치하지만 SQL 코드 블록에는 반영되지 않은 상태로 남아 있었다(G-5, gap-detector가 발견). 설계 문서의 산문 설명과 코드 블록은 항상 동기화해야 한다.
3. **`ratelimit` 이벤트 미기록 결정이 설계에 사후 반영됨**: 이 판단(DB 쓰기 증폭 방지)은 구현 단계에서 내려졌으나 Plan의 FR-10 정의에는 아직 반영되지 않았다. 설계 문서의 다음 개정(v0.3)에서 명시가 필요하다.
4. **GET 스트림의 URL 로그 노출**: `GET /api/chat/stream?message=...`은 질문 원문이 쿼리스트링으로 전달되어 Vercel 액세스 로그·리퍼러에 남을 수 있다(FR-13, 범위 외로 문서화만 완료). 프론트를 POST 우선으로 전환하는 별도 사이클이 필요하다.

### To Apply Next Time

1. **권한 검증 스크립트를 설계 단계에서 함께 작성**: `_verify.sql` 같은 실행 가능한 검증 스크립트를 Design 단계에서 초안 작성해 두면, Do 단계에서 배포 전 자체 검증이 가능해 사용자가 프로덕션에서 직접 함정을 밟는 상황을 줄일 수 있다.
2. **DDL과 산문 설명의 정합성 자동 확인**: gap-detector가 설계 문서와 코드를 대조하듯, SQL 파일과 설계 문서의 SQL 코드 블록도 diff 대조 대상에 포함하면 G-5 같은 이탈을 Check 단계에서 조기 포착할 수 있다.
3. **Supabase 권한 테스트를 CI에 편입 검토**: 현재는 배포 후 수동으로 `_verify.sql`을 실행해야 한다. Docker Postgres 기반 CI 잡으로 DDL의 권한 회수 여부를 자동 검증하면 이번처럼 실전에서 함정을 밟는 일을 원천 차단할 수 있다(단, 실제 Supabase 환경의 `ALTER DEFAULT PRIVILEGES` 재현이 전제).

---

## Deployment Checklist

### Pre-Deployment — 완료됨

- [x] `supabase_abuse_guard.sql` 실행 (테이블 3·함수 4·권한 회수 확인)
- [x] `supabase_abuse_guard_verify.sql`로 양성 검증 (9/9 통과)
- [x] 코드 커밋·PR 생성·CI 통과·main 머지 (PR #28 → `72c301e`)

### Post-Deployment — 진행 필요

- [ ] Vercel 환경변수에 `ALLOWED_ORIGINS` 실값 설정 (현재 `*` — 타 사이트 임베드로 무료 프록시화 가능)
- [ ] **monitor 모드 1주 관측**: `GET /api/admin/abuse`로 `injection`·`scope` 이벤트를 점검, 정상 노동상담이 오탐되지 않는지 확인
- [ ] 관측 기준 충족 시 `ABUSE_GUARD_MODE=block`·`SCOPE_GATE_MODE=block` 전환 (Vercel env 변경만으로 가능, 재배포 불요)
- [ ] 즉시 롤백 필요 시 `ABUSE_GUARD_MODE=off`·`SCOPE_GATE_MODE=off`로 되돌림 (재배포 불요)

### Monitoring

- [ ] `/api/admin/abuse?days=7`로 이벤트 유형별 집계·최근 목록·활성 차단 목록 주기 점검
- [ ] `chat_quota` 테이블 증가 추이로 DAILY_CHAT_QUOTA=50이 실제 트래픽에 적정한지 확인
- [ ] 게시판(`/api/board/*`)에서 `guard_flag` 대화가 정상적으로 비노출되는지 확인

---

## Next Steps

### 즉시

1. **Vercel `ALLOWED_ORIGINS` 실값 설정** — 현재 `*`로 CORS 완전 개방

### 1주일 내

2. **monitor 모드 관측** — 인젝션·스코프 게이트 오탐 여부를 `/api/admin/abuse`로 확인
3. **관측 결과에 따라 block 전환** — 경계 셋 오판 0·오프토픽 정탐 ≥16/20(설계 §8.3 기준) 충족 시

### 1개월 이후

4. **GET 스트림 → POST 전환 검토** — 질문 원문의 URL 로그 노출 제거(FR-13 잔여 항목)
5. **admin.html에 남용 현황 위젯 추가** — 현재는 API만 존재, UI는 후속 과제
6. **service_role 키 도입 검토** — anon 키 유출 시 `abuse_summary`/`abuse_unblock` RPC가 여전히 호출 가능한 잔존 위험 해소(설계 §3.1에 문서화된 트레이드오프)

---

## Document References

| Document | Path | Purpose |
|----------|------|---------|
| Plan | `docs/01-plan/features/chatbot-security.plan.md` | 위협 모델·현황 실측·FR-01~13 정의 |
| Design | `docs/02-design/features/chatbot-security.design.md` (v0.2) | 2단 가드 아키텍처·인젝션 패턴 실측·Supabase 스키마 |
| Analysis | `docs/03-analysis/chatbot-security.analysis.md` | 설계-구현 갭 분석, 93%→98% |
| Implementation | `app/core/abuse_guard.py`, `api/index.py`, `app/core/pipeline.py` 외 | 소스 코드 |
| Deployment | `supabase_abuse_guard.sql`, `_verify.sql`, `_rollback.sql` | Supabase 스키마·검증·롤백 |
| PR | [github.com/DrunkenZealnut/laborconsult/pull/28](https://github.com/DrunkenZealnut/laborconsult/pull/28) | 머지 커밋 `72c301e` |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-07-31 | 완료 보고서 최초 작성 — Match Rate 98%, PR #28 머지 완료, Supabase 배포·양성 검증 완료. monitor 모드 관측 대기 상태로 종료 | Claude |
