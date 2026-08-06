# llm-fallback-hardening Gap Analysis Report

> **Feature**: LLM 폴백 경화 (빈 응답·절단·전환 지연·교차벤더)
> **Date**: 2026-08-06
> **Design**: [llm-fallback-hardening.design.md](../02-design/features/llm-fallback-hardening.design.md) (v0.1)
> **Plan**: [llm-fallback-hardening.plan.md](../01-plan/features/llm-fallback-hardening.plan.md) (v0.2)
> **Match Rate**: 91% → **99%** (Act-1 반영, §12 참조)
> **분석 방식**: gap-detector 에이전트 대조 + 주요 발견 실측 재검증

---

## 1. Summary

| Category | 항목 | 구현됨 | 부분구현 | 미구현 |
|----------|:----:|:------:|:--------:|:------:|
| P0 조용한 실패 제거 (FR-01~04) | 4 | 3 | 1 | 0 |
| P1 벤더 단일 장애점 (FR-05~08) | 4 | 2 | 2 | 0 |
| FR-09 고지 문구 | 1 | 1 | 0 | 0 |
| P2 관측·검증 (FR-10~13) | 4 | 3 | 1 | 0 |
| 결정 D1~D10 | 10 | 9 | 1 | 0 |
| 설계 원칙 P1·P4·P6 | 3 | 3 | 0 | 0 |
| 테스트 T1~T8 | 8 | 8 | 0 | 0 |

### Match Rate 산출 근거

FR 우선순위를 가중치로 사용(P0=3, P1=2, FR-09=1, P2=1), 배점은 구현됨 1.0 / 부분구현 0.5~0.75.

| FR | 가중 | 판정 | 배점 | 소계 |
|----|:----:|:----:|:----:|-----:|
| FR-01 | 3 | 구현됨 | 1.00 | 3.00 |
| FR-02 | 3 | 구현됨 | 1.00 | 3.00 |
| FR-03 | 3 | 구현됨 | 1.00 | 3.00 |
| FR-04 | 3 | 부분구현 | 0.75 | 2.25 |
| FR-05 | 2 | 구현됨 | 1.00 | 2.00 |
| FR-06 | 2 | 부분구현 | 0.75 | 1.50 |
| FR-07 | 2 | 부분구현 | 0.75 | 1.50 |
| FR-08 | 2 | 구현됨 | 1.00 | 2.00 |
| FR-09 | 1 | 구현됨 | 1.00 | 1.00 |
| FR-10 | 1 | 구현됨 | 1.00 | 1.00 |
| FR-11 | 1 | 구현됨 | 1.00 | 1.00 |
| FR-12 | 1 | 부분구현 | 0.50 | 0.50 |
| FR-13 | 1 | 구현됨 | 1.00 | 1.00 |
| **합계** | **25** | | | **22.75** |

**22.75 / 25 = 91.0%**

---

## 2. FR별 판정

| ID | 요구사항 요약 | 판정 | 근거 (파일:줄) |
|----|---------------|:----:|----------------|
| FR-01 | 빈 응답(실질 0자)을 실패로 승격 → 다음 제공자 전환, 전부 빈 응답이면 RuntimeError | **구현됨** | `app/core/pipeline.py:419` `chars = 0`(started 불리언 폐기), `:432` `chars += len(text.strip())`, `:444-450` 0자 종료 시 `empty_providers` 기록 후 계속, `:452-453` `RuntimeError`. 판정이 `strip()` 후 0자로 한정돼 짧은 정상 답변 오탐 없음 |
| FR-02 | 절단 시 ① SSE 고지 ② 면책 고지 유지 ③ `metadata.truncated` + 게시판 제외 | **구현됨** | `pipeline.py:434-439` 절단 표시 + 폴백 미시도, `:1913-1922` 절단 고지를 면책 고지 앞에 전송, `:2013-2016` `conv_metadata["truncated"]`, `api/index.py:357` `_PUBLIC_EXCLUDE_KEYS`, `:369-370` PostgREST 필터, `:374-380` Python 후처리, `:1074` 상세 조회 차단 |
| FR-03 | 재시도 축소 + 전환 하트비트로 무이벤트 구간 제거 | **구현됨** | `pipeline.py:306-311`(Claude c5/r20, retries 0), `:332-337`(OpenAI 동일), `:414-417` 2순위부터 `yield (name, "")`, `:1883-1886` 호출부가 `ping`으로 변환. **검증**: `public/index.html:1295` `onActivity()`가 파싱 이전 `reader.read()` 직후 호출되므로 이벤트 타입과 무관하게 idle 타이머(`:1621` 60초)가 리셋된다 |
| FR-04 | L1~L8 전 호출 명시 타임아웃 + `app/config.py` 단일 출처 | **부분구현** | 상수 단일 출처 `app/config.py:28-56` ✅, 타임아웃 8지점 전부 부여 ✅. **그러나 `max_retries`가 4곳 미배선** — `query_decomposer.py:194`, `self_rag.py:46`, `citation_validator.py:277`, `:398`. `config.py:46` 주석은 `CRITICAL_MAX_RETRIES`가 "decomposer/self_rag 공통"이라 선언하나 두 모듈은 import조차 하지 않는다 → **GAP-1·GAP-2** |
| FR-05 | 의도분석 OpenAI 교차벤더 폴백, `ANALYZE_TOOL` 단일 출처 | **구현됨** | `app/core/llm_fallback.py` 신설(`:40-54` 스키마 무수정 변환, `:57-94` tool 강제 호출, `:80` `max_retries=0`), `analyzer.py:139-171` `_build_analysis_result` 벤더 중립화, `:229-246` 폴백 분기. 스키마는 복제가 아닌 동일 객체 참조(`test_llm_fallback.py:266`의 `is` 비교로 고정) |
| FR-06 | 스코프 게이트 생존 + 양쪽 실패 시 fail-open 유지 | **부분구현** | 규약 보존 ✅ — `pipeline.py:1420` 조건 무변경, `:1422` `getattr(..., True)`, `analyzer.py:170` 누락 시 True. **설계 §4.3이 명시한 검증(Claude 예외 주입 → `calculation_types` 충전 + 게이트 호출)이 자동 테스트에 없다** → GAP-3 |
| FR-07 | 교정 타임아웃 동적화 + 단계 예산 상한 + 교정 전 ping | **부분구현** | `citation_validator.py:21-30` `_rewrite_timeout`, `:33-37` `_remaining`, `:274/296/316` 벤더별 잔여 게이트, `:350` `MICRO_POLISH_MIN_BUDGET`, `pipeline.py:1950` ping ✅. **단계 예산 60초가 보증되지 않음** — 재시도로 단일 벤더가 예산을 초과 가능 → GAP-1 |
| FR-08 | 죽은 3순위 복구 + 모델 상수 통일 + 타임아웃 | **구현됨** | `config.py:21-25` `gemini-pro-latest` + 404 경위 주석, `pipeline.py:357` 상수 사용, `:365-368` `request_options` 타임아웃, `citation_validator.py:302` 하드코딩 제거 |
| FR-09 | 폴백 고지 문구 점검 | **구현됨** | `pipeline.py:1889-1895` 이미지 미지원 고지 유지, `:1916-1920` 절단 고지가 기존 오류 문구 톤과 일관 |
| FR-10 | provider·폴백·빈응답·절단·교정 결과 계측 + 구조화 로그 | **구현됨** | `pipeline.py:456-472` `_llm_meta`, `:2017` metadata 부착, `:2018-2022` 구조화 로그. 대시보드 노출은 설계상 "선택" |
| FR-11 | `test_llm_fallback.py` 신설(API 키 불요) + CI 등록 | **구현됨** | 14개 테스트, 클라이언트는 `object()` 자리표시자라 키 불요, `.github/workflows/tests.yml:42-43` 등록 |
| FR-12 | 장애 주입 양성 검증 절차 | **부분구현** | 체크리스트 V1~V4 설계 §5.3 존재 ✅ + **V1·V2·V3 로컬 실행 완료**(§6 참조). **V4(프로덕션 계측 양성 확인) 미실행 + 실행 결과 문서 산출물 없음** → GAP-4 |
| FR-13 | `.env.example` 문서화 + `CLAUDE.md` 정정 | **구현됨** | `.env.example:20-39` 7개 변수 + 롤백 절차, `CLAUDE.md:87,101,297-304,52` |

---

## 3. 설계 결정 D1~D10 준수

| # | 결정 | 준수 | 근거 |
|---|------|:----:|------|
| D1 | Gemini 존치 + `gemini-pro-latest` 교체 | ✅ | `config.py:25`, `pipeline.py:383-384` |
| D2 | `google-generativeai` 유지 | ✅ | `requirements.txt:14` 무변경 |
| D3 | 답변 경로 `max_retries=0` + 벤더 전환 | ✅ | `config.py:38`, `pipeline.py:311,337` |
| D4 | **2-튜플 규약 보존** | ✅ | `pipeline.py:392-395` `outcome`은 선택 인자, `:417,430,433` 전부 2-튜플. `test_abuse_guard.py:547` 스텁 무변경 통과 |
| D5 | 의도분석 폴백 모델 `gpt-4.1` | ✅ | `config.py:51` |
| D6 | 교정 타임아웃 동적 + 단계 예산 | ⚠️ | 동적화·게이트 구현, **예산 상한이 재시도로 초과 가능**(GAP-1) |
| D7 | **절단 답변의 면책 고지 유지** | ✅ | `pipeline.py:1924-1932` 절단 여부와 무관하게 부착. `test_llm_fallback.py:220-222`가 존재 + 순서를 회귀 고정 |
| D8 | 절단 답변도 인용 교정 수행 | ✅ | `pipeline.py:1934-1972` 교정 블록이 절단 분기 밖 |
| D9 | **계측은 metadata 재사용, 스키마 변경 0** | ✅ | `pipeline.py:2010-2017` 기존 dict에 `llm` 키만. 마이그레이션 SQL 없음 |
| D10 | **`board_posts`에 metadata 필터 미적용** | ✅ | `api/index.py:1011-1033,1085-1094` board_posts는 필터 미경유. `test_abuse_guard.py:650-652` 정규식 회귀 가드 |

> D10은 사용자 게시글 전멸을 유발하는 심각 회귀 시나리오다 — 코드·테스트 양쪽에서 회귀 없음 확인.

---

## 4. 타임아웃 예산표 대조 (설계 §3.4 vs 코드)

| ID | 호출 | 설계값 | 실제 코드값 | 일치 |
|----|------|--------|-------------|:----:|
| L1 | Claude 답변 | c5 / r20 × 1 (25s) | connect 5.0 / read 20.0 / retries 0 | ✅ |
| L2 | OpenAI 답변 | c5 / r20 × 1 (25s) | 동일 상수 | ✅ |
| L3 | Gemini 답변 | 25s × 1 | `ANSWER_READ_TIMEOUT + CONNECT_TIMEOUT` = 25.0 | ✅ |
| L4 | `analyze_intent` | 12s × 1 | 12.0 / retries 0 | ✅ |
| L4b | OpenAI 폴백 분석 | 10s × 1 | 10.0 / retries 0 | ✅ |
| L5 | `_extract_params` | 10s × 1 | 10.0 / retries 0 | ✅ |
| L6 | decomposer / self_rag | 3s × **1** (3s) | 3.0s × **3**(SDK 기본 재시도) = **최대 ~9s** | ❌ |
| L7 | 인용 교정 3벤더 | 동적 + **단계 예산 60s** | 동적 ✅ / 게이트 ✅ / **Haiku 재시도 3회로 단일 벤더 최대 ~122s** | ⚠️ |
| L8 | `micro_polish` | 동적 + 잔여 ≥15s | 동적 ✅ / **재시도 3회** | ⚠️ |

**누적 검증**

| 구간 | 설계 | 실제(최악) |
|------|-----:|-----------:|
| 이해 (L4+L4b+L5) | 32s | 32s |
| 검색 (L6 포함) | ~30s | ~30s (+L6 재시도 여유, 병렬이라 체감 제한적) |
| 답변 (L1+L2+L3) | 75s | 75s |
| 교정 (L7+L8) | 80s | **최대 ~120s** |
| 저장 | ~20s | ~20s |
| **합계** | **≈237s** | **≈277s** |

300초 미만은 유지되나 마진이 63초 → **23초로 축소**됐다. 무이벤트 최대 구간 25초는 설계대로(프론트 60초 대비 안전).

---

## 5. 설계 원칙 P1·P4·P6 검증

| 원칙 | 검증 | 결과 |
|------|------|:----:|
| **P1 정상 경로 무회귀** | 첫 청크가 실질 텍스트면 `pending` 경로를 타지 않고(`pipeline.py:423-427`) 즉시 yield. 첫 청크가 공백인 경우만 1청크 지연 후 함께 방출(유실 없음). 폴백 미발생 시 하트비트도 없음(`:414` `if idx:`). **실측**: 정상 경로 `provider=Claude attempts=['Claude']`, TTFT 20.4초, 계산 결과 동일 | ✅ |
| **P4 호출 규약 보존** | `_stream_answer`가 여전히 `(str, str)`만 yield. `outcome`은 4번째 선택 인자 → `test_abuse_guard.py:547` 스텁 무변경 통과 | ✅ |
| **P6 fail-open 불변** | `pipeline.py:1420` 조건 무변경, `:1422` 기본 True, `analyzer.py:170` 누락 시 True. `INTENT_FALLBACK_ENABLED=false` → `analyzer.py:232` raise → `pipeline.py:1412-1415`가 흡수 → `analysis=None` 유지 → 게이트 skip + 레거시 경로 진입 | ✅ |

---

## 6. 정밀 검증 — 의심 항목 (전건 실측)

| # | 의심 | 판정 | 상세 |
|---|------|------|------|
| 1 | `pending` 버퍼에 버려지는 청크가 있는가 | **의도된 폐기** | 공백만 내고 정상 종료 시 `pending`은 flush되지 않고 폐기된다. 설계 §3.1 "폴백 답변 앞 빈 줄 오염 제거" + T2가 명시적으로 요구한 동작(`test_llm_fallback.py:78-87`이 고정). 폐기 대상은 선행 공백뿐이라 정보 손실 없음 |
| 2 | 절단 후 `outcome` 참조가 `UnboundLocalError`/None 유발 가능한가 | **불가능** | `outcome`이 `try` 밖(`pipeline.py:1871`)에서 무조건 선바인딩. 중간 이탈 경로 2곳(`:1898-1901` RuntimeError, `:1905-1911` 유출)은 둘 다 `return`. `citation_fixed`도 `:1942`에서 선바인딩 |
| 3 | `citation_validator → app.config` 순환 import | **없음** | `app/config.py:1-11`은 stdlib + 외부 SDK만 import, `app.core.*` 의존 0 → 단방향 |
| 4 | `analyzer → llm_fallback` 순환 | **없음** | `llm_fallback.py:13-14`가 `json`·`logging`만 import. 설계 §4.2의 순환 회피 의도대로 최하위 모듈 |
| 5 | `_remaining(None)`이 예산을 새로 부여하는 것이 의도인가 | **호출부 안전, 계약은 느슨** | `correct_hallucinated_citations`는 `:252-253`에서 선정규화하나 `micro_polish`는 하지 않아 `deadline=None`이면 60초를 새로 부여. 유일한 호출부가 항상 deadline을 넘겨 현재는 무해 → GAP-5 |
| 6 | `INTENT_FALLBACK_ENABLED=false`의 raise를 호출부가 강등하는가 | **정상 강등** | `analyzer.py:232` raise → `pipeline.py:1412-1415` 흡수 → `:1463` `analysis is None`으로 `_extract_params` 진입. **다만 자동 테스트 미커버**(GAP-3) |

### 6-1. 장애 주입 실행 결과 (FR-12 V1~V3)

| # | 주입 | 결과 |
|---|------|------|
| **V1** | `ANTHROPIC_API_KEY` 무효화 | 의도분석 401 → **OpenAI 폴백 성공**(`gpt-4.1`) → **계산기 실행**(퇴직금 10,922,155원). 답변은 OpenAI. `llm_outcome provider=OpenAI attempts=['Claude','OpenAI']` 기록 |
| **V2** | `ANSWER_PROVIDER=gemini` | `provider=Gemini`, 79자 정상 수신(8.5초) — 죽어 있던 3순위 복구 확인 |
| **V3** | `ANSWER_READ_TIMEOUT=0.1` | 3벤더 전부 타임아웃 → 하트비트 2회 발행 → `RuntimeError` 명시적 실패 |
| **V4** | 프로덕션 계측 양성 확인 | **미실행** (배포 후 수행 필요) |

> V1은 FR-05의 핵심 가치를 실증한다 — 기존 코드였다면 의도분석 실패 시 레거시 경로도 Claude라 계산 없는 일반론이 나갔을 상황에서 퇴직금 금액이 유지됐다.

---

## 7. 테스트 시나리오 T1~T8

| # | 설계 시나리오 | 테스트 함수 | 위치 | 존재 |
|---|--------------|-------------|------|:----:|
| T1 | 1순위 0청크 → 폴백, `empty_providers` 기록 | `test_t1_empty_first_provider_falls_back` | `test_llm_fallback.py:65` | ✅ |
| T2 | 공백만 → 청크 오염 0 | `test_t2_whitespace_only_not_leaked` | `:78` | ✅ |
| T3 | 첫 청크 전 예외 → 하트비트 1회 | `test_t3_switch_heartbeat_emitted` | `:90` | ✅ |
| T4 | 실질 청크 후 예외 → 절단, 폴백 미시도 | `test_t4_truncation_keeps_partial_no_fallback` | `:103` | ✅ |
| T5 | 전 제공자 실패 → RuntimeError | `test_t5_all_providers_fail_raises` | `:116` | ✅ |
| T6 | 전 제공자 빈 응답 → RuntimeError | `test_t6_all_providers_empty_raises` | `:130` | ✅ |
| T7 | 절단 대화 게시판 제외 | `test_t7_truncated_excluded_from_board` | `:171` | ✅ |
| T8 | tool 스키마 변환 | `test_t8_tool_schema_conversion` | `:257` | ✅ |

T1~T8 8종 전부 존재. 설계 §5.2가 요구한 "T4의 저장 게이팅을 `process_question` 통합 실행으로 검증"도 `:188-235`에 별도 구현.

---

## 8. 발견된 갭

| # | 갭 | 심각도 | 위치 | 수정 제안 |
|---|-----|:------:|------|-----------|
| **GAP-1** | **인용 교정 경로의 재시도가 단계 예산을 무력화**. `messages.create(..., timeout=...)`에 `max_retries` 미지정 → SDK 기본 2회 재시도. 타임아웃은 **시도당** 적용되므로 Haiku 한 벤더가 최대 3×40초 + 백오프 ≈ 122초를 소비할 수 있다. 잔여 예산 검사는 벤더 호출 *사이*에만 있어 진행 중 초과를 막지 못한다. 설계 D6/FR-07의 "단계 예산 60s"가 보증되지 않는다.<br>**실측 확인**: `timeout=0.001`로 호출 시 현행 방식은 **1.37초** 소요(3회 시도), `with_options(max_retries=0)`은 **0.00초**. `create()`는 `max_retries` 인자를 받지 않아 반드시 `with_options()`를 써야 한다 | **High** | `citation_validator.py:277-285`, `:398-414` | 두 호출을 `anthropic_client.with_options(timeout=..., max_retries=0).messages.create(...)`로 교체. 재시도 대신 다음 벤더로 넘기는 것이 설계 원칙 P2와도 일치 |
| **GAP-2** | **L6 재시도 미배선 + 주석 드리프트**. `query_decomposer`·`self_rag`가 `CRITICAL_MAX_RETRIES`를 import하지 않아 SDK 기본 2회 재시도가 남는다(예산표 3s → 실제 최대 ~9s). `config.py:46` 주석은 "decomposer/self_rag 공통"이라 선언해 코드보다 앞서간다 — 본 사이클이 G9로 지적한 문서 드리프트의 재발 | **Medium** | `query_decomposer.py:194-200`, `self_rag.py:46-57`, `config.py:46` | 두 호출부에 `with_options(max_retries=CRITICAL_MAX_RETRIES)` 배선, 또는 배선하지 않을 것이면 `config.py:46` 주석에서 두 모듈 제거 |
| **GAP-3** | **FR-05/FR-06 폴백 분기가 자동 테스트에서 미검증**. `analyzer.py:231-246`(Claude 예외 → `call_openai_tool`)과 `INTENT_FALLBACK_ENABLED=false` 강등 경로를 실행하는 테스트가 없다. T8은 스키마 변환만, `test_analysis_result_vendor_neutral`은 후처리만 검증한다. V1 수동 실행으로 동작은 확인됐으나 **상시 회귀 방어선이 없다**. 이 사이클의 출발점이 "폴백이 죽어 있는데 아무도 몰랐다"였음을 감안하면 같은 함정의 재생산 | **High** | `test_llm_fallback.py`(부재) | `_analyze_claude`를 raise로 monkeypatch + `openai_client`를 tool_calls 반환 가짜 객체로 주입해 ① `calculation_types` 충전 ② `is_labor_related` 전달 ③ `INTENT_FALLBACK_ENABLED=false`에서 예외 전파 → 레거시 강등, 3케이스 추가 |
| **GAP-4** | FR-12 V4(프로덕션 계측 양성 확인) 미실행 + 실행 결과 문서 산출물 없음. V1~V3은 로컬 실행 완료(§6-1)이나 기록이 분석 문서에만 있다. V4는 Plan 오픈 항목인 "프로덕션 `GEMINI_API_KEY` 실값 미확인"을 판별하는 유일한 수단 | **Medium** | 산출물 없음 | 배포 후 V4 실행(`select metadata->'llm'->>'provider' ...`) 후 결과를 완료 보고서에 기록 |
| **GAP-5** | `micro_polish(deadline=None)`이 단계 예산과 무관하게 60초를 새로 부여. 현 호출부는 항상 deadline을 넘기므로 무해하나 GAP-1과 겹치면 최대치가 열린다 | **Low** | `citation_validator.py:33-37`, `:392` | `deadline = deadline or (time.monotonic() + CITATION_STAGE_BUDGET)` 선정규화 |
| **GAP-6** | `flatten_content` 2벌 존재 — `pipeline._flatten_content`(이미지 탈락 안내 주입)와 `llm_fallback.flatten_content`(조용히 탈락). 의도적 분기로 보이나 코드에 근거가 없어 후속 수정자가 합칠 위험 | **Low** | `pipeline.py:257`, `llm_fallback.py:19` | `llm_fallback.flatten_content` docstring에 분기 이유 한 줄 추가 |
| **GAP-7** | `chatbot.py::generate_answer`는 폴백 없는 단일 Claude 스트림 그대로 — 빈 응답·절단·타임아웃 무방비. 설계 범위 밖(웹 파이프라인 한정)이나 CLI 사용자는 G1~G3에 노출 | **Low (범위 밖)** | `chatbot.py:464-486` | 후속 과제. CLI가 `process_question`을 재사용하도록 통합하는 편이 근본적 |
| **GAP-8** | Plan §3.3 NFR "무이벤트 최대 구간 ≤ 15초" vs 설계·구현 25초. 설계 §3.4가 근거와 함께 완화했으나 Plan 문서는 15초로 남아 드리프트 | **Low** | `plan.md` NFR 표 vs `design.md` §3.4 | Plan NFR에 "설계에서 25초로 확정(프론트 60초 대비 마진 35초)" 각주 추가 |

---

## 9. 범위 초과 구현 (설계에 없는 추가 — 전부 긍정적)

| # | 항목 | 위치 |
|---|------|------|
| P1 | `INTENT_FALLBACK_MAX_TOKENS` 상수화 (단일 출처 원칙 확장) | `config.py:52` |
| P2 | `_llm_meta` 시그니처를 `citation_fixed: bool`로 단순화 (dict 왕복 제거, `None`이면 키 생략) | `pipeline.py:456,470-471` |
| P3 | 구조화 로그에 `citation_fixed` 추가(설계 4필드 → 5필드) | `pipeline.py:2018-2022` |
| P4 | `_is_public_excluded` 헬퍼 추출 — 상세 조회와 목록 후처리가 판정을 공유 | `api/index.py:374-375` |
| P5 | T1~T8 외 추가 테스트 6종(제공자 순서·`_llm_meta` 형태·벤더 중립 후처리·절단 통합·타임아웃 스케일링·예산 소진) | `test_llm_fallback.py` |
| P6 | `guard_flag` 유실 방지 회귀 가드 신설 | `test_abuse_guard.py:631-636` |
| P7 | `.env.example`에 롤백 시나리오별 그룹핑 + 각 값의 실패 모드 서술 | `.env.example:20-39` |
| P8 | `CLAUDE.md` 폴백 규약 5항(설계 3항 요구) + 순환 import 회피 근거 기록 | `CLAUDE.md:297-304` |
| P9 | `config.py` 예산표 동기화 의무를 두 상한(300초·60초)과 함께 명시 | `config.py:32-35` |

---

## 10. 설계에 있으나 미구현

| 항목 | 설계 위치 | 상태 |
|------|-----------|------|
| L6 재시도 축소 | §3.4 예산표 | 미구현 (GAP-2) |
| 교정 단계 예산 60초의 실질 보증 | §4.4, D6 | 부분 (GAP-1) |
| FR-06 생존 검증 테스트 | §4.3 | 미구현 (GAP-3) |
| FR-12 V4 실행·결과 기록 | §5.3, §7 Wave C | 부분 (GAP-4) |
| 관리자 대시보드 계측 노출 | §5.1 | 미구현 — **설계가 "선택"으로 명시**, 정상 |
| 답변 스트림 wall-clock 데드라인 | §3.3 | 미구현 — **설계가 범위 제외로 명시**, 정상 |

---

## 11. 결론 및 권고

### 결론

**Match Rate 91% — 설계와 구현이 잘 정합한다.** P0의 핵심(빈 응답=실패 승격, 절단의 정직한 처리, 전환 하트비트)은 코드·테스트·문서 3중으로 완결됐고, 회귀 위험 4대 항목(D4 2-튜플, D7 면책 고지, D9 스키마 무변경, D10 `board_posts` 필터)은 전부 회귀 없음을 확인했다. 순환 import 우려 2건도 실제로는 존재하지 않는다.

미달 항목은 두 갈래로 모인다.

1. **재시도가 예산을 뚫는다** (GAP-1·GAP-2) — 설계 원칙 P2("재시도보다 전환")를 답변 경로에는 적용했으나 교정 경로와 L6에는 적용하지 않았다. 그 결과 "단계 예산 60초"라는 설계의 명시적 보증이 코드에서 성립하지 않는다. 실측으로 확인된 결함이다.
2. **폴백 코드가 자동 검증되지 않는다** (GAP-3) — FR-05가 만든 교차벤더 경로는 V1 수동 실행으로만 확인됐고 상시 회귀 방어선이 없다. 이 사이클의 출발점이 "폴백이 404로 죽어 있는데 계측이 없어 몰랐다"였음을 감안하면, 검증 없는 폴백 추가는 같은 함정의 재생산이다.

### 권고 (우선순위 순)

| 순위 | 조치 | 근거 |
|:----:|------|------|
| 1 | `citation_validator.py:277`·`:398`에 `with_options(max_retries=0)` 배선 | GAP-1. 2줄 수정으로 설계 §4.4의 예산 보증이 성립. **배포 전 필수** |
| 2 | `analyze_intent` 폴백 분기 테스트 3케이스 추가 | GAP-3. 검증 없는 폴백은 없는 폴백과 같다 |
| 3 | `query_decomposer`/`self_rag` 재시도 배선 또는 `config.py:46` 주석 정정 | GAP-2. 코드·주석 중 하나는 반드시 고쳐야 드리프트가 닫힌다 |
| 4 | 배포 후 V4 실행·기록 | GAP-4. 프로덕션 `GEMINI_API_KEY` 오픈 항목이 여기서만 판별된다 |
| 5 | `micro_polish` deadline 선정규화 / `flatten_content` 분기 근거 주석 / Plan NFR 각주 | GAP-5·6·8. 저비용 위생 조치 |
| 6 | `app/core/llm_fallback.py`·`test_llm_fallback.py` git 추적 | `CLAUDE.md` 규약 — 미추적 시 Vercel import 500 |

**후속 사이클 후보**: `chatbot.py::generate_answer`를 `process_question` 경로로 통합해 CLI에도 동일 폴백 규약 적용(GAP-7).

### PDCA 다음 단계

Match Rate 91% ≥ 90%로 `[Check]` 기준은 통과했다. 다만 **GAP-1·GAP-3은 배포 전 처리 권고**이므로 `/pdca iterate llm-fallback-hardening`으로 두 건을 정리한 뒤 `/pdca report`를 진행하는 편이 안전하다.

---

## 12. Act-1 반영 결과 (2026-08-06)

### 12-1. 처리 내역

| 갭 | 심각도 | 조치 | 검증 |
|----|:------:|------|------|
| **GAP-1** | High | `citation_validator.py` Haiku 교정·`micro_polish` 두 호출을 `with_options(timeout=..., max_retries=0)`로 교체. `create()`가 `max_retries`를 받지 않아 `with_options()`가 유일한 경로 | **실측**: 무효 키 + 클라이언트 기본 `max_retries=2` 환경에서 `correct_hallucinated_citations` 소요 **0.33초**(재시도 시 1.4초+). 단계 예산 60초 보증 성립 |
| **GAP-2** | Medium | `query_decomposer.py`·`self_rag.py`가 `CRITICAL_MAX_RETRIES`를 import해 `with_options`로 배선. `config.py:46` 주석과 코드 일치 | 순환 import 없음 확인. 정상 경로에서 쿼리 분해 1,541ms로 정상 동작 |
| **GAP-3** | High | 폴백 분기 테스트 3종 신설 — ① Claude 예외 주입 → OpenAI가 `calculation_types`·`monthly_wage`·`is_labor_related` 충전 + tool 강제·`max_retries=0` 확인 ② `INTENT_FALLBACK_ENABLED=false` → 예외 전파 ③ 양쪽 실패 → 스코프 게이트 skip(fail-open) | `test_llm_fallback.py` 14 → **17건 전부 통과** |
| **GAP-5** | Low | `micro_polish`에 `deadline` 선정규화 추가 (`correct_hallucinated_citations`와 동일) | 테스트 통과 |
| **GAP-6** | Low | `llm_fallback.flatten_content` docstring에 `pipeline._flatten_content`와의 의도적 분기 이유 명시("합치지 말 것") | — |
| **GAP-8** | Low | Plan NFR에 "무이벤트 ≤ 25초(설계 §3.4 확정)" 각주 추가 — 문서 드리프트 해소 | — |

### 12-2. 미처리 (사유 명시)

| 갭 | 사유 |
|----|------|
| **GAP-4** (Low로 하향) | V4(프로덕션 계측 양성 확인)는 **배포 후에만 가능**. V1~V3은 로컬 실행·기록 완료(§6-1). 배포 후 `select metadata->'llm'->>'provider' from qa_conversations ...` 실행이 남는다.<br>**2026-08-06 갱신**: Plan 오픈 항목이던 "프로덕션 `GEMINI_API_KEY` 미확인"은 운영자가 로컬·Vercel 양쪽을 갱신해 **해소**됐다. 따라서 V4에 남은 목적은 "계측이 프로덕션에서 실제로 기록되는지" 하나뿐이며, V2(3순위 실체 판별)는 로컬 실동작 검증(`provider=Gemini`, 9.1초)으로 대체됐다 |
| **GAP-7** (Low) | `chatbot.py` CLI 경로는 **설계 범위 밖**(웹 파이프라인 한정). 후속 사이클에서 `process_question` 통합으로 처리 권고 |

### 12-3. Act-1 후 Match Rate

| FR | 가중 | 이전 | 이후 | 소계 |
|----|:----:|:----:|:----:|-----:|
| FR-01·02·03 | 각 3 | 1.00 | 1.00 | 9.00 |
| FR-04 | 3 | 0.75 | **1.00** | 3.00 |
| FR-05 | 2 | 1.00 | 1.00 | 2.00 |
| FR-06 | 2 | 0.75 | **1.00** | 2.00 |
| FR-07 | 2 | 0.75 | **1.00** | 2.00 |
| FR-08 | 2 | 1.00 | 1.00 | 2.00 |
| FR-09·10·11·13 | 각 1 | 1.00 | 1.00 | 4.00 |
| FR-12 | 1 | 0.50 | **0.75** | 0.75 |
| **합계** | **25** | 22.75 | | **24.75** |

**24.75 / 25 = 99.0%** — 잔여 0.25는 배포 의존 항목(GAP-4 V4)이며 코드 결함이 아니다.

### 12-4. 회귀 확인

| 스위트 | 결과 |
|--------|------|
| `test_wage_golden.py` | ✅ |
| `test_pipeline_wiring.py` | ✅ |
| `test_offline_units.py` | ✅ |
| `test_abuse_guard.py` | ✅ (20개 그룹) |
| `test_llm_fallback.py` | ✅ (17건) |
| `test_answer_renderer.js` | ✅ (8 pass / 0 fail) |
| 실파이프라인 정상 경로 | ✅ `provider=Claude attempts=['Claude']`, 계산 결과 유지 |
