---
template: analysis
version: 1.2
feature: chatbot-security
date: 2026-07-31
author: DrunkenZealnut
project: laborconsult
---

# chatbot-security Gap Analysis

> **판정**: Match Rate **93% → 98%** (갭 수정 후). Critical 0건, Major 2건·Minor 2건 **수정 완료**, 의도적 이탈 2건은 설계에 반영 예정
>
> **기준 문서**: [chatbot-security.design.md](../02-design/features/chatbot-security.design.md) v0.2
> **분석 도구**: bkit gap-detector (설계 명세 67개 항목 × 코드 1:1 대조)
> **분석일**: 2026-07-31

---

## 1. 요약

| 산출 단위 | 최초 | 수정 후 | 비고 |
|---|:---:|:---:|---|
| FR 구현 (FR-01~13) | 12/13 = **92%** | 13/13 = **100%** | FR-09·FR-10 부분 → 완전 |
| 설계 명세 (§3·§5·§6·§8) | 62.5/67 = **93%** | 65.5/67 = **98%** | 의도적 이탈 2건(G-5·G-6)만 잔존 |
| 테스트 커버리지 (§8.1) | 9.5/11 = **86%** | 11/11 = **100%** | 3그룹 보강 + 신규 3그룹 |
| **종합** | **93%** | **98%** ✅ | 90% 기준 통과 |

Critical 0건. Major 2건은 **실제 결함**이었고 이 사이클에서 수정했다.

---

## 2. 발견된 갭과 조치

### 🟠 Major (2건 — 수정 완료)

#### G-1. 길이 위반이 남용 이벤트로 기록되지 않아 자동 차단에 구멍

| 항목 | 내용 |
|---|---|
| **설계 요구** | FR-10 `event_type = injection\|scope\|quota\|ratelimit\|length\|block\|leak`, §3.1 RPC 2가 `injection\|quota\|length`를 자동 차단 카운트 대상으로 정의 |
| **실제 상태** | `record_violation` 호출이 4곳(quota·injection·scope·leak)뿐. 길이 위반은 `GuardRejection(400)`만 던지고 이벤트 미기록 → `abuse_events`에 `length` 행이 영원히 없어 SQL의 `event_type IN (...)` 중 `length` 분기가 죽은 코드. 대량 길이 공격 시 `/api/admin/abuse`가 무증상 |
| **위치** | `api/index.py:137-151` (수정 전) |
| **조치** | Supabase 핸들 확보를 1단계 앞으로 옮기고, 길이 위반 시 `record_violation(..., "length", ..., "block")` 호출 추가 |

**설계에서 의도적으로 이탈한 부분**: `ratelimit` 이벤트는 **기록하지 않기로 결정**했다. 이미 인메모리로 차단된 요청마다 DB INSERT를 하면 요청 폭주가 그대로 DB 쓰기 증폭이 되어 방어 수단이 공격 벡터가 된다. 자동 차단 카운트 대상도 아니므로(RPC는 `injection|quota|length`만 집계) `logging.info`로 충분하다. 코드 주석에 이 판단을 명시했다.

#### G-2. 게시판 필터 폴백이 실제 예외를 잡지 못해 500 발생 가능

| 항목 | 내용 |
|---|---|
| **설계 요구** | §3.2·§6.1 "필터 구문 실패 시 전체 조회 후 Python 후처리 폴백 — 빈 목록·500 회피" |
| **실제 상태** | `_exclude_guard_flagged()`의 try/except가 감싼 것은 **쿼리 빌드**뿐이었다. `.is_(...)`는 파라미터 문자열을 붙일 뿐 예외를 던지지 않고, 실제 거부는 `.execute()`의 PostgREST 400으로 나타난다. 호출부 3곳(`board_recent`·`board_categories`·`board_search`)에 try/except가 없어 **그대로 500** — 설계가 의도한 폴백 경로에 도달조차 못 함 |
| **위치** | `api/index.py:344-358`, `:882-891`, `:921-926`, `:948-955` (수정 전) |
| **조치** | 빌드가 아니라 **실행까지** 감싸는 `_fetch_qa_public(build)` 헬퍼로 교체. `build(apply_filter: bool)` 콜백을 받아 필터 적용 실행 → 실패 시 무필터 재실행 + `_drop_flagged()` Python 후처리. 3곳 모두 이 헬퍼 경유로 전환하고, `board_recent`의 `result.count`는 헬퍼 반환값으로 대체 |

이 결함은 `metadata` 컬럼이 없는 환경이나 PostgREST 버전 차이에서 **게시판 전체가 500**이 되는 시나리오였다. 스텁으로 400을 강제해 폴백이 실제 작동하는지 검증하는 테스트(`test_board_filter_execute_fallback`)를 추가했다.

### 🔵 Minor (2건 수정 / 2건 설계 반영 예정 / 1건 문서)

| # | 항목 | 상태 | 조치 |
|---|---|:---:|---|
| G-3 | `validate_message`에 fail-open try/except 없음 (§6.1 계약 미이행) | ✅ 수정 | 본문을 try/except로 감싸 예외 시 `(True, message[:limit], None, None)` 반환 |
| G-4 | `session_id` 정규식이 `re.match` + `$` → 후행 개행 허용(`"abcdefgh\n"` 통과) | ✅ 수정 | `fullmatch()`로 변경 + 회귀 테스트 2건(개행 거부·레거시 `uuid4().hex[:12]` 통과) |
| G-5 | DDL RPC 2의 카운트 쿼리에 `AND mode = 'block'` 추가 (설계 SQL 본문에 없음) | 📝 설계 반영 | **구현이 정답** — §5.10 산문("monitor는 차단 판정 제외")과 일치. 설계 v0.3에서 SQL 본문 정정 |
| G-6 | `unicodedata.normalize("NFC")` 적용 (설계 §5.1에 미규정) | 📝 설계 반영 | 무해·바람직한 추가. 설계 v0.3 §5.1에 NFC 명기 |
| G-7 | `ALLOWED_ORIGINS` 실값 설정이 `.env.example`에만 있고 `CLAUDE.md` 배포 절에 미기재 | 📝 문서 | 이미 `CLAUDE.md` Abuse Guard 운영 문단 + 설계 §8.4 배포 체크리스트에 존재 — 중복 기재 불요로 판단 |

### 테스트 커버리지 보강 (3그룹 → 6그룹)

| 그룹 | 최초 | 조치 |
|---|:---:|---|
| 저장 게이팅 | 소스 문자열 토큰 존재만 확인 | **동작 검증**으로 교체 — 스텁 config로 `process_question`을 소진해 monitor 대화에 `guard_flag`가 붙고 정상 대화에는 안 붙는지 확인 (`test_guard_flag_storage_gating`) |
| 차단 경로 | 수동 확인만 | **자동화** — 인젝션 block 시 이벤트가 `["chunk","done"]`뿐이고 세션 이력이 비며, LLM 클라이언트 접근이 0회임을 Exploding 스텁으로 검출 (`test_block_paths_skip_llm_and_storage`) |
| KST day 폴백 | 포맷만 검증 | `zoneinfo` import 실패를 몽키패치로 강제해 고정 오프셋 폴백이 같은 날짜를 내는지 확인 |
| 게시판 필터 폴백 | 없음 | 신규 — `execute()` 400 강제 → 무필터 재조회 + Python 후처리 동작 확인 |
| session_id 경계 | 8·64자만 | 후행 개행 거부 + 레거시 형식 통과(회귀 방지) 추가 |

---

## 3. 검증 통과 항목

gap-detector가 코드 대조로 확인한 일치 항목:

- **§5.0 진입 헬퍼**: 시그니처·반환 3-튜플·`GuardRejection`·핸들러 3종 `request: Request` 추가. `_guard_chat_request`가 `get_or_create_session`·첨부 파싱보다 **먼저** 호출됨
- **§5.2~5.4**: 채팅 전용 버킷 분리, RPC 파라미터명 정확, `ZoneInfo` → 고정 오프셋 폴백, 카테고리당 1회 가산, 억제자 윈도우 25자, 첨부 포함 `combined_query` 검사, `detail` 120자 상한
- **§5.5~5.9**: 스코프 게이트가 `analyze_intent` 직후 배치·`analysis=None`이면 미적용, `INJECTION_RESISTANCE`가 `.format()` **이후** 결합·중괄호 0개·두 프롬프트 모두 적용, 첨부 래핑 2곳, `scan_leak`이 면책 고지·인용 검증 **이전** 위치, `LEAK_MIN_HITS=2`
- **§3.1 DDL**: 테이블 3종 컬럼·인덱스 2개·RPC 4개 시그니처·`SECURITY DEFINER`·`SET search_path`·RLS ENABLE + **정책 무부여**·REVOKE/GRANT 전부 일치
- **§3.2 게시판**: qa 4곳 적용 + `board_detail` metadata select 후 404, **`board_posts` 미적용**, admin 조회 무필터
- **§3.3 패턴 사전**: 6개 카테고리 패턴 문자열·가중치(3/3/3/3/2/3)·suppress 플래그·`_BENIGN_ACTOR`·`_SUPPRESS_WINDOW=25` **완전 일치**
- **§3.6 유출 시그니처**: 5개 정확 일치. 설계에서 제외하기로 한 3종("답변 원칙:", "[인용 가능한 판례·행정해석 목록]", "analyze_labor_question") **미포함** 확인. 시그니처 4·5는 실제 시스템 프롬프트(`pipeline.py:1142,1153`)에 실재
- **§6.1 fail-open**: `scan_injection`·`scan_leak`·`check_guard`·`record_violation`·`validate_message`(G-3 수정 후) 전부 try/except

---

## 4. 회귀 위험: 낮음

| 항목 | 평가 |
|---|---|
| `process_question` 호출처 | 전수 6곳 확인 — 웹 3곳만 `guard_ctx` 전달, `benchmark_pipeline.py:180`·`test_naver_kin.py:86`·`test_legal_cases_e2e.py:102`는 기본값 `None`으로 가드 전면 비활성. `chatbot.py`는 파이프라인 미사용 |
| `ANALYZE_TOOL["required"].append(...)` | `required`를 읽는 코드는 tool 전달부와 테스트뿐. `tool_choice`로 강제 호출 중이라 기존 필드 추출 무영향. `AnalysisResult` 기본값 True로 누락 시에도 fail-open |
| `session_id` 형식 검증 도입 | 기존 발급 형식 `uuid4().hex[:12]`(12자 hex)가 정규식을 통과 — 프론트 저장분 무효화 없음(회귀 테스트로 고정) |
| 게시판 응답 스키마 | `_fetch_qa_public` 전환 후에도 반환 키(`items`/`total`/`total_pages`/`has_more`) 동일 |

### 실행 검증 (수정 후)

```
test_wage_golden.py      ✅ 전부 통과
test_pipeline_wiring.py  ✅ 전부 통과
test_offline_units.py    ✅ 전부 통과
test_abuse_guard.py      ✅ 전체 통과 (20개 그룹)
test_answer_renderer.js  ✅ pass 8 / fail 0
엔드포인트 스모크        health 200 / 길이초과 400 / 빈 메시지 400 /
                         GET 스트림 SSE error / admin 무인증 401 / board 503(Supabase 미설정)
```

---

## 5. 잔존 항목 (배포 전 필수)

코드는 완결됐으나 **아직 배포 가능한 상태가 아니다**:

1. **Supabase DDL 실행** — `supabase_abuse_guard.sql`을 SQL Editor에서 실행. 미실행 시 쿼터·차단·이벤트가 전부 fail-open으로 조용히 통과한다
2. **쿼터 양성 검증** — fail-open은 소리 없이 실패하므로 "차단이 안 나온다"는 확인은 무의미. `DAILY_CHAT_QUOTA=3`으로 4번째 요청이 실제 429인지 확인 (SQL 파일 §4에 절차)
3. **Vercel env 설정** + `ALLOWED_ORIGINS` 실값
4. **monitor 1주 관측** — 두 가드 모두 기본 `monitor`라 현재는 기록만 하고 차단하지 않음. `/api/admin/abuse`로 오탐 확인 후 §8.3 기준(경계 셋 오판 0, 오프토픽 정탐 ≥16/20) 충족 시 `block` 전환

## 6. 후속 (선택)

- 설계 v0.3에 G-5·G-6 의도적 이탈 2건 반영 → 문서-코드 100% 정합화
- `ratelimit` 이벤트 미기록 결정을 설계 FR-10에 명시
- GET 스트림 `message`의 URL 로그 노출(설계 §5.12) — 프론트 POST 전환은 별도 사이클

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-07-31 | 갭 분석 최초 — 93% 판정, Major 2·Minor 5 도출 후 Major 2건·Minor 2건 수정 및 테스트 6그룹 보강으로 98% 달성 | DrunkenZealnut |
