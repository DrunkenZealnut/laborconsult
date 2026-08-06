---
template: plan
version: 1.2
feature: llm-fallback-hardening
date: 2026-08-06
author: DrunkenZealnut
project: laborconsult
---

# llm-fallback-hardening Planning Document

> **Summary**: LLM 호출 8지점 중 폴백이 존재하는 곳은 답변 생성 1곳뿐이고, 그 폴백조차 "빈 응답·중도 절단·전환 지연"을 성공으로 처리한다. 벤더 장애가 **조용한 품질 붕괴**로 나타나는 경로를 전 계층에서 차단한다.
>
> **Project**: laborconsult
> **Version**: 0.1
> **Author**: DrunkenZealnut
> **Date**: 2026-08-06
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | LLM 호출 8지점 중 6곳이 Anthropic 전용이고, 유일한 폴백 체인(답변 생성)도 ① 0청크 응답을 성공으로 종료하고(빈 답변 노출), ② 스트림 중도 실패를 사용자 고지 없이 삼킨 뒤 면책 고지를 붙여 **완결된 답변처럼** 저장·게시판 노출하며, ③ Claude 무응답 시 최대 ~91초를 침묵해 프론트 60초 idle abort가 먼저 터진다(폴백이 있어도 사용자는 실패를 봄). Anthropic 장애 시엔 계산기 라우팅·스코프 게이트·인용 교정이 동시에 죽어 "숫자 없는 일반론"이 정상 답변처럼 나간다. |
| **Solution** | ① 실패 판정 강화(빈 응답·중도 절단을 실패로 승격, 전환 지연 상한 + 무이벤트 구간 제거), ② 타임아웃·재시도 예산의 단일 출처화(현재 600초 SDK 기본값·무제한 Gemini·8192토큰에 5초/2초 교정 타임아웃 혼재), ③ 의도분석 교차벤더 폴백(OpenAI tool-use)으로 벤더 단일 장애점 해소, ④ provider·폴백·절단 계측 + 오프라인 회귀 테스트로 "조용한 실패"를 관측 가능하게. |
| **Function/UX Effect** | 정상 경로 지연은 무회귀(현행 TTFT ~17.7초 유지). 장애 시 사용자는 빈 답변·잘린 답변 대신 실제 답변(폴백 벤더) 또는 명시적 안내를 받고, Anthropic 장애 중에도 임금 계산 결과가 유지된다. |
| **Core Value** | 노동상담은 금액·기간이 틀리면 실害가 발생하는 도메인이다. 장애가 "오류"가 아니라 "그럴듯한 저품질 답변"으로 새는 경로를 막아, 가용성이 아닌 **답변 신뢰성**을 지킨다. |

---

## 1. Overview

### 1.1 Purpose

`process_question()` 파이프라인은 8개 LLM 호출로 구성되며, Vercel 서버리스(maxDuration 300초) 위에서 SSE로 스트리밍된다. 본 계획은 **LLM 제공자 장애·지연·이상응답**을 장애 모델로 정의하고, 실패가 사용자에게 잘못된 답변으로 전달되지 않도록 폴백 경로를 경화한다.

기존 프로젝트 관례인 *graceful degradation*(Pinecone 실패 → RAG 비활성, BM25 미설치 → Dense-only)은 유지하되, **"조용히 나빠지는 것"과 "조용히 틀리는 것"을 구분**한다. 전자는 허용, 후자는 차단이 본 사이클의 기준선이다.

### 1.2 Background — LLM 호출 인벤토리 실측 (2026-08-06 코드 기준)

| # | 호출부 | 모델 / 한도 | 타임아웃 | 재시도 | 폴백 | 실패 시 실제 영향 |
|---|--------|-------------|----------|:------:|------|-------------------|
| L1 | `pipeline._stream_claude` (답변 1순위) | `claude-sonnet-5` / 8192 | connect 5s, read 30s | SDK 기본 2 | → OpenAI → Gemini | (체인 정상 시 무영향) |
| L2 | `pipeline._stream_openai` (답변 2순위) | `o3`(env) / 8192 | **미지정 → SDK 기본 600s** | SDK 기본 2 | → Gemini | 300s maxDuration·60s 프론트 idle 초과 |
| L3 | `pipeline._stream_gemini` (답변 3순위) | `gemini-2.5-pro` | **없음(무제한)** | 없음 | 없음 | 무한 대기 가능 |
| L4 | `analyzer.analyze_intent` (의도분석) | `claude-sonnet-5` / 1024 | 12s | SDK 기본 2 (실효 ~36s) | **없음** → L5(동일 벤더) | 계산기 미실행 + 스코프 게이트 무력화 |
| L5 | `pipeline._extract_params` (레거시 추출) | `claude-sonnet-5` / 512 | 10s | SDK 기본 2 | **없음** | 계산기 미실행 |
| L6 | `query_decomposer` / `self_rag` | `claude-haiku-4-5` | 3s | SDK 기본 2 | 규칙 기반 축소 ✅ | 검색 품질 저하(허용 범위) |
| L7 | `citation_validator.correct_hallucinated_citations` | Haiku(5s) → Gemini(**무제한**) → o3(**미지정**) / 각 8192 | 혼재 | SDK 기본 2 | 3단 폴백 ✅ | 환각 판례가 답변에 잔존 |
| L8 | `citation_validator.micro_polish` | `claude-haiku-4-5` / 8192 | **2s** | SDK 기본 2 | 없음 | 문맥 어색(허용 범위) |

**벤더 집중도**: 8곳 중 **6곳(L1·L4·L5·L6·L7 1순위·L8)이 Anthropic 전용**. 교차벤더 폴백이 존재하는 것은 답변 생성(L1)과 인용 교정(L7)뿐이다.

**검증 근거**
- SDK 기본값 실측(`.venv`): `anthropic 0.120.2` / `openai 2.53.0` 모두 `DEFAULT_MAX_RETRIES=2`, `DEFAULT_TIMEOUT=Timeout(connect=5.0, read=600, …)`
- 프론트 idle abort: `public/index.html:1621` `SEND_TIMEOUT_MS = 60000` (이벤트 수신 시마다 리셋)
- 플랫폼 상한: `vercel.json` `maxDuration: 300`
- 모델 A/B 실측: `compare_llm_models_report.md` — o3 vs gpt-5.6-luna 품질 4.05 vs 4.00(동률), TTFT 17.7초(지연 대부분이 intent+RAG 단계)

### 1.3 Related Documents

- `docs/01-plan/features/chatbot-security.plan.md` + `docs/02-design/features/chatbot-security.design.md` — **fail-open은 조용하다**는 교훈과 `guard_ctx` 규약. 본 계획의 계측·양성검증 원칙은 여기서 승계
- `docs/01-plan/features/calc-db-integration-review.plan.md` — DB-6(임계경로 타임아웃) 도입 이력. L4·L5 타임아웃이 그 산물
- 커밋 `8ec409c` (2026-08-06) — Sonnet 5 전환 + reasoning 토큰 한도 8192 통일. 본 계획은 그 **후속 미해결 항목**(교정 타임아웃 부정합)을 포함
- `compare_llm_models.py` / `compare_llm_models_report.md` — `ANSWER_PROVIDER` 강제 + 블라인드 채점 하네스(폴백 벤더 품질 검증에 재사용)
- `CLAUDE.md` — Graceful degradation 관례, "새 기능 추가 시 반드시 폴백 경로 구현"

### 1.4 확인된 갭

| # | 갭 | 근거 | 영향 | 대응 |
|---|-----|------|------|:----:|
| **G1** | **빈 응답을 성공으로 처리**: `_stream_answer`의 for 루프가 0청크로 정상 종료하면 `return`(성공)한다. 예외가 없으므로 **폴백이 발동하지 않고 빈 답변이 그대로 나간다**. 2026-08-06 실측된 o3 `finish_reason=length` + 본문 0자 사례가 정확히 이 경로 | `pipeline.py:355-361` | **높음** | FR-01 |
| **G2** | **중도 절단이 완결 답변으로 위장**: `started=True` 이후 예외 → `logger.warning` + `return`. 사용자 고지 없음. 이후 6-0에서 `_DISCLAIMER`가 붙고 Supabase 저장·게시판 노출까지 진행되어, 문장 중간에서 끊긴 답변이 **완결된 상담 답변으로 보존**된다 | `pipeline.py:362-366`, `1805-1813`, `1852+` | **높음** | FR-02 |
| **G3** | **폴백 전환이 프론트 인내심보다 느림**: Claude 무응답 시 read 30s × SDK 재시도 3회 ≈ **91초+백오프** 동안 SSE 이벤트가 하나도 나가지 않는다. 프론트는 60초 무활동에서 abort → **폴백이 도달하기 전에 사용자는 실패를 본다** | `pipeline.py:286`, `public/index.html:1621` | **높음** | FR-03 |
| **G4** | **의도분석 벤더 단일 장애점**: L4 실패 시 폴백은 L5인데 **같은 Anthropic 클라이언트**다. Anthropic 장애 = 계산기 미실행 + `analysis is None`으로 스코프 게이트 skip(fail-open). 답변만 OpenAI로 나가므로 사용자에겐 "정상이지만 숫자 없는 일반론"으로 보인다 | `pipeline.py:1309-1317`, `1361` | **높음** | FR-05, FR-06 |
| **G5** | **교정 타임아웃 ↔ 토큰 한도 부정합**: L7 Haiku 5초·L8 2초인데 둘 다 `max_tokens=8192`로 **답변 전문을 재생성**한다. 실측 타임아웃 확인됨. 교정 실패 = 환각 판례가 사용자에게 그대로 남음(정확성 리스크) | `citation_validator.py:250`, `305` | 중간 | FR-07 |
| **G6** | **타임아웃 미지정 구간**: L2는 SDK 기본 600초, L3·L7 Gemini/OpenAI 경로는 사실상 무제한. Vercel 300초·프론트 60초와 정합하지 않아 **플랫폼이 먼저 함수를 죽이는** 경로가 존재 | `pipeline.py:304,330`, `citation_validator.py:267,279` | 중간 | FR-04 |
| **G7** | ~~3순위 Gemini의 실체 불명~~ → **설계 단계에서 확정: 이미 죽어 있음.** `gemini-2.5-pro`가 404 `"no longer available to new users"`를 반환한다(2026-08-06 실측). 답변 3순위(L3)와 인용 교정 2순위(L7b) **양쪽 모두 사망** — 실제 폴백은 문서·코드의 약속과 달리 **2단**이었다. G8(계측 부재)이 이 사실을 가리고 있었다 | `config.py:21`, `pipeline.py:346`, `citation_validator.py:266` | **높음(승격)** | FR-08 |
| **G8** | **폴백 관측 부재**: `used_provider`는 지역 변수로만 존재 — Supabase 저장·SSE 노출·집계 어디에도 없다. 폴백률·빈응답률·교정 실패율을 **아무도 모른다**. `chatbot-security`가 겪은 "fail-open은 조용하다" 함정의 재현 | `pipeline.py:1767-1780` | 중간 | FR-10 |
| **G9** | **문서 드리프트**: `CLAUDE.md`는 "Claude Sonnet 4.6 (primary)"라 적었으나 실제는 `claude-sonnet-5`. 운영 스위치 `ANSWER_PROVIDER`·`OPENAI_CHAT_MODEL`은 `.env.example` 미기재 — 장애 시 **즉시 롤백 수단을 운영자가 모른다** | `config.py:16,20`, `.env.example` | 낮음 | FR-13 |

---

## 2. Scope

### 2.1 In Scope

- [ ] 답변 생성 폴백 체인(`_stream_answer`) 실패 판정·전환 지연·사용자 고지 경화 (G1·G2·G3)
- [ ] 전 LLM 호출(L1~L8)의 타임아웃·재시도 예산 명시화 및 단일 출처 관리 (G6)
- [ ] 의도분석(L4) 교차벤더 폴백 — OpenAI tool-use로 동일 스키마 재시도 (G4)
- [ ] 인용 교정(L7)·마이크로 퇴고(L8) 타임아웃과 토큰 한도 정합 (G5)
- [ ] 3순위 제공자(Gemini) 실체 확정 및 타임아웃 부여 (G7)
- [ ] provider·폴백·절단 계측(`qa_conversations.metadata`) + 오프라인 회귀 테스트 신설 (G8)
- [ ] 운영 문서 정합: `.env.example` 스위치 문서화, `CLAUDE.md` 모델명 정정 (G9)

### 2.2 Out of Scope

- LLM 제공자 추가 도입(Vercel AI Gateway, 사내 프록시 등) — 현행 3벤더 체제 유지
- 답변 품질 자체의 개선(프롬프트·RAG 튜닝) — 별도 사이클(`benchmark-quality-improvement`)
- 임베딩(`text-embedding-3-small`)·Cohere rerank의 폴백 — 이미 graceful degradation 존재, 본 사이클은 생성계 LLM에 한정
- 세션·대화 저장 계층의 내구성(Supabase 장애) — `calc-db-integration-review`에서 처리됨
- 비용 최적화·모델 교체 판단 — `compare_llm_models.py` 결과상 전환 근거 없음(별건)
- 프론트 재시도 UI(자동 재전송 버튼 등) — 본 사이클은 서버 측 정직성 확보까지

---

## 3. Requirements

### 3.1 장애 모델

| ID | 장애 시나리오 | 현재 결과 | 사용자 체감 | 우선순위 |
|----|--------------|-----------|-------------|:--------:|
| F1 | 제공자가 200 OK + 본문 0자 반환(reasoning 토큰 소진 등) | 성공 처리, 폴백 미발동 | 빈 답변 | P0 |
| F2 | 첫 청크 이후 연결 끊김 | 부분 응답 유지 + 면책 고지 부착 + 저장 | **잘린 답변을 완결로 오인** | P0 |
| F3 | 1순위가 무응답(타임아웃 반복) | ~91초 침묵 후 폴백 시도 | 프론트가 먼저 abort → 실패 | P0 |
| F4 | Anthropic 전면 장애 | 답변만 OpenAI, 계산·게이트·교정 전멸 | 숫자 없는 일반론(정상처럼 보임) | P1 |
| F5 | 교정 호출 타임아웃 | 교정 폐기, 원문 유지 | 환각 판례 잔존 | P1 |
| F6 | 3순위 미설정/무한대기 | 300초 함수 강제 종료 | 응답 없음 | P1 |
| F7 | 폴백이 실제로 동작하는지 아무도 모름 | 지표 없음 | (운영 리스크) | P2 |

### 3.2 Functional Requirements

**P0 — 조용한 실패 제거**

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | **빈 응답을 실패로 승격**: `_stream_answer`가 어떤 제공자에서 0청크(또는 공백만) 수신 후 정상 종료하면 성공으로 처리하지 않고 다음 제공자로 전환한다. 전 제공자가 빈 응답이면 기존 `RuntimeError` 경로로 합류(사용자에게 명시적 오류). 판정 기준은 **`strip()` 후 0자**로 한정해 "짧지만 정상인 답변"의 오탐을 배제 (G1/F1) | High | Pending |
| FR-02 | **중도 절단의 정직한 처리**: 스트림 도중 실패 시 ① SSE로 절단 고지 이벤트 발행(사용자가 재질문 가능하도록), ② 절단 답변에는 면책 고지 자동 부착을 생략하거나 절단 표식과 함께 부착, ③ Supabase 저장 시 `metadata.truncated=true` 기록 + **게시판 공개 제외**(기존 `_exclude_guard_flagged` 관례 재사용). 부분 응답 유지(재시도 없음) 규약 자체는 변경하지 않음 (G2/F2) | High | Pending |
| FR-03 | **전환 지연 상한 + 무이벤트 구간 제거**: 답변 생성 호출의 재시도를 명시 지정(임계경로 `max_retries` 축소)하고 **첫 청크 대기 상한**을 별도로 둬 상한 초과 시 즉시 다음 제공자로 전환. 전환 중에는 `status`/`ping` 이벤트를 발행해 프론트 60초 idle 타이머를 리셋한다. 목표: 무이벤트 최대 구간 ≤ 15초, 1→2순위 전환 완료 ≤ 25초 (G3/F3) | High | Pending |
| FR-04 | **타임아웃·재시도 예산 단일 출처화**: L1~L8 전 호출에 명시 타임아웃 부여(현재 미지정 = SDK 600초인 L2, 무제한인 L3·L7 Gemini/OpenAI 포함). 값은 `app/config.py` 등 한 곳에 상수화하고, **최악 경로 누적이 Vercel 300초 이내**임을 예산표로 증명 (G6/F6) | High | Pending |

**P1 — 벤더 단일 장애점 해소**

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-05 | **의도분석 교차벤더 폴백**: `analyze_intent` 실패 시 OpenAI function calling으로 **동일 스키마**(`ANALYZE_TOOL` 단일 출처 재사용) 재시도 → 동일한 `AnalysisResult` 반환. 양쪽 모두 실패할 때만 현행 레거시 경로(L5)로 강등. 스키마는 이중 관리하지 않고 어댑터만 분리 (G4/F4) | High | Pending |
| FR-06 | **스코프 게이트 생존 확인**: FR-05로 `is_labor_related`가 확보되므로 Anthropic 장애 중에도 게이트가 동작함을 검증. 양쪽 실패 시 fail-open 유지(`chatbot-security` FR-05 규약 불변) — 가드가 상담을 막지 않는다는 원칙은 그대로 (G4) | High | Pending |
| FR-07 | **교정 경로 타임아웃 정합**: L7 Haiku(5초)·L8(2초)를 `max_tokens=8192` 전문 재생성 실측 소요에 맞춰 재산정한다. 고정값 상향 또는 입력 길이 비례 동적 타임아웃 중 설계에서 선택. **답변 한도와 교정 한도는 묶여 있으므로**(한쪽만 낮추면 `len(text) > len(response_text) * 0.7` 가드에 걸려 교정이 통째로 폐기) 함께 조정 (G5/F5) | High | Pending |
| FR-08 | **죽은 3순위 복구**(설계 단계에서 **High로 승격**): `gemini-2.5-pro` 404 확인 → 동작 검증된 `gemini-pro-latest`로 교체하고, 답변(L3)·인용 교정(L7b) 양쪽의 모델명을 상수로 통일. `request_options` 타임아웃 부여로 **무제한 대기 제거**. 레거시 SDK는 신모델에서 정상 동작하므로 유지(마이그레이션은 후속 과제) (G7/F6) | **High** | Pending |
| FR-09 | **폴백 고지 문구 점검**: 현행 "이미지 미지원" 고지는 유지하고, FR-01/FR-02가 추가하는 신규 고지와 톤·중복을 정리(사용자에게 벤더명 노출 여부 포함) | Low | Pending |

**P2 — 관측·검증**

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-10 | **폴백 계측**: `used_provider`, 폴백 발생 여부, 빈 응답·절단 여부, 인용 교정 성공/실패를 `qa_conversations.metadata`에 기록(**스키마 변경 없음**)하고 구조화 로그로 남긴다. 관리자 대시보드 노출은 선택 (G8/F7) | Medium | Pending |
| FR-11 | **오프라인 회귀 테스트 신설**: `test_llm_fallback.py` — fake 클라이언트로 (빈 응답 / 첫 청크 전 실패 / 중도 절단 / 타임아웃 / 전 제공자 실패) 5개 시나리오를 API 키 없이 검증. `.github/workflows/tests.yml`에 등록(기존 오프라인 스위트 관례 준수) | Medium | Pending |
| FR-12 | **장애 주입 양성 검증 절차**: 배포 후 무효 키·강제 예외로 실제 폴백 경로가 발동하는지 1회 실측하는 체크리스트 작성. `chatbot-security`의 "fail-open은 조용하므로 배포 후 양성 검증 필수" 교훈 승계 | Medium | Pending |
| FR-13 | **운영 문서 정합**: `.env.example`에 `ANSWER_PROVIDER`·`OPENAI_CHAT_MODEL`·`GEMINI_API_KEY` 용도와 롤백 절차 기재, `CLAUDE.md`의 "Claude Sonnet 4.6" → 실제 모델명 정정 (G9) | Low | Pending |

### 3.3 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| 성능(무회귀) | 정상 경로 TTFT p50 회귀 없음 (기준선 ~17.7초) | `compare_llm_models.py` 하네스 재사용 |
| 전환 지연 | 1→2순위 전환 완료 ≤ 25초, 무이벤트 최대 구간 ≤ 25초<br>*(초안의 15초는 설계 §3.4에서 25초로 확정 — 답변 벤더 1회분 read 타임아웃과 같으며 프론트 idle 60초 대비 마진 35초)* | 장애 주입 실측(FR-12) |
| 플랫폼 정합 | 최악 폴백 경로 누적 < 300초(Vercel), 무이벤트 구간 < 60초(프론트 idle) | 타임아웃 예산표 + 실측 |
| 정확성 | 절단·빈 응답 답변이 게시판·저장에 완결 답변으로 노출되는 사례 0건 | `test_llm_fallback.py` + 저장 경로 검증 |
| 계산 가용성 | Anthropic 장애 모사 시에도 계산기 라우팅 성공 | `test_pipeline_wiring.py`(CALC-1/2/3) 확장 |
| 테스트 | 신규 스위트는 **API 키 불요**로 CI에서 실행 | `.github/workflows/tests.yml` |
| 운영성 | 재배포 없이 1순위 제공자·모델 교체 가능(기존 env 스위치 유지) | `.env.example` 문서화 |
| 호환성 | `guard_ctx=None` 호출부(CLI·`benchmark_pipeline.py`·E2E) 무변경 동작 | 기존 테스트 통과 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] P0(FR-01~04) 전체 + P1(FR-05~08) 구현
- [ ] `test_llm_fallback.py` 신설·통과 — 5개 장애 시나리오 전부 재현, CI 등록
- [ ] 기존 오프라인 스위트 회귀 없음: `test_wage_golden.py` / `test_pipeline_wiring.py` / `test_offline_units.py` / `test_abuse_guard.py`
- [ ] 타임아웃 예산표 작성 — L1~L8 값 + 최악 경로 누적 < 300초 근거
- [ ] Anthropic 장애 모사 시 계산기 라우팅 성공을 테스트로 증명(FR-05)
- [ ] `.env.example`·`CLAUDE.md` 갱신(FR-13)
- [ ] 배포 후 장애 주입 양성 검증 체크리스트 작성(FR-12)

### 4.2 Quality Criteria

- [ ] 어떤 경화 로직도 **정상 경로를 막지 않는다** — 판정 실패 시 기존 동작 유지(프로젝트 graceful degradation 관례)
- [ ] 빈 응답 판정이 짧은 정상 답변을 오탐하지 않음(`strip()` 후 0자 기준)
- [ ] 절단 고지가 사용자에게 과도한 불안을 주지 않는 문구(기존 오류 문구 톤과 일관)
- [ ] 신규 상수가 코드 여러 곳에 흩어지지 않고 단일 출처 유지

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| 재시도 축소로 일시적 429/5xx에 취약해짐 | Medium | Medium | 재시도를 0이 아닌 1회로 두고, **재시도보다 벤더 전환을 빠르게** 하는 방향으로 설계. 429는 즉시 전환 대상으로 분류 |
| 첫 청크 타임아웃이 정상 장문 답변을 끊음 | High | Low | "첫 청크 대기"와 "스트림 중 무진행"을 **분리된 타임아웃**으로 설계. 후자는 현행 30초 유지 |
| OpenAI 의도분석의 추출 품질이 Claude보다 낮음 | Medium | Medium | 폴백 전용(정상 경로 미변경). `test_pipeline_wiring.py` 골든 케이스로 회귀 확인, 품질 미달 시 FR-05를 "degraded 모드 + 사용자 고지"로 축소 |
| tool 스키마 이중 관리로 드리프트 발생 | Medium | Medium | `ANALYZE_TOOL` 단일 출처 유지 + 벤더별 어댑터만 분리. 스키마 동등성 테스트 추가 |
| 절단 고지 추가가 기존 프론트 렌더러와 충돌 | Low | Medium | 신규 SSE 타입 대신 **기존 `status`/`replace` 이벤트 재사용** 우선 검토 |
| 교정 타임아웃 상향이 전체 응답 지연을 늘림 | Medium | Medium | 교정은 환각 감지 시에만 발동(상시 아님). 예산표에서 최악 경로에 포함해 300초 내 검증 |
| Gemini 경로가 실제로 한 번도 검증된 적 없을 가능성 | Medium | Medium | FR-08에서 실체 확인 우선. 미설정이면 "있는 척하는 3순위"를 제거하는 편이 정직 |
| `metadata` 필드 추가가 게시판 조회에 영향 | Medium | Low | `qa_conversations`만 대상(이미 `metadata` 사용 중). **`board_posts`에는 절대 미적용**(metadata 컬럼 부재 — PostgREST 400이 삼켜져 게시글 소실) |

---

## 6. Architecture Considerations

### 6.1 Project Level Selection

| Level | Characteristics | Selected |
|-------|-----------------|:--------:|
| Starter | 정적 구조 | ☐ |
| **Dynamic** | 기존 FastAPI + `app/core` 모듈 계층에 통합 | ☑ |
| Enterprise | 별도 게이트웨이/서비스 메시 | ☐ |

### 6.2 Key Architectural Decisions

| Decision | Options | 권고 | Rationale |
|----------|---------|------|-----------|
| 실패 판정 위치 | `_stream_answer` 내부 / 호출부(`process_question`) | **`_stream_answer` 내부** | 폴백 판정이 한 곳에 모여야 3벤더 전부에 균일 적용. 호출부는 절단 고지·저장 정책만 담당 |
| 교차벤더 의도분석 배치 | `analyzer.py` 내 provider 분기 / 신규 어댑터 모듈 | **얇은 어댑터 분리** | `analyzer.py`는 스키마·검증 로직 유지, 벤더 차이(tool_use vs function calling)만 어댑터가 흡수 |
| 타임아웃 상수 위치 | 각 모듈 상수 / `app/config.py` 집중 | **`app/config.py` 집중** | 예산표와 코드가 어긋나지 않게 단일 출처. 기존 `CLAUDE_MODEL` 등 상수 관례와 동일 |
| 절단·폴백 고지 전달 | 신규 SSE 타입 / 기존 `status`·`replace` 재사용 | **기존 이벤트 재사용 우선** | 프론트 `readSSE()` 변경 최소화. 신규 타입은 미인식 시 조용히 무시되는 위험 |
| 계측 저장소 | 신규 테이블 / `qa_conversations.metadata` | **`metadata` 재사용** | 스키마 마이그레이션 0. `guard_flag` 선례 존재 |
| 재시도 정책 | SDK 기본(2) 유지 / 명시 축소 | **임계경로만 명시 축소** | 재시도는 동일 벤더 반복 — 장애 시엔 전환이 더 빠르고 안전 |

### 6.3 변경 대상 파일 (예상)

```
수정: app/core/pipeline.py           (_stream_answer 실패 판정·전환 예산·고지,
                                      _stream_openai/_stream_gemini 타임아웃, 저장 시 계측)
      app/core/analyzer.py           (교차벤더 폴백 진입점)
      app/core/citation_validator.py (L7·L8 타임아웃 정합, Gemini/OpenAI 상한)
      app/config.py                  (LLM 타임아웃·재시도 단일 출처 상수)
      .env.example                   (ANSWER_PROVIDER·OPENAI_CHAT_MODEL 문서화)
      CLAUDE.md                      (모델명 정정 + 폴백 규약 기재)
      .github/workflows/tests.yml    (신규 스위트 등록)
신설: test_llm_fallback.py           (오프라인 폴백 회귀 — API 키 불요)
      app/core/llm_fallback.py (선택) (교차벤더 어댑터 — 설계에서 확정)
```

---

## 7. Convention Prerequisites

### 7.1 Existing Project Conventions

- [x] Graceful degradation 관례 — "새 기능 추가 시 반드시 폴백 경로 구현"(`CLAUDE.md`)
- [x] 오프라인 테스트 관례 — API 키 없이 CI 실행(`test_wage_golden.py` 외 3종)
- [x] `app/core/*.py`는 **반드시 git 커밋** — 미추적 파일은 Vercel import 500 유발
- [x] `from __future__ import annotations` 사용 관례
- [x] `guard_ctx=None`이면 가드 전체 비활성 — CLI·벤치마크 호출부 무변경 원칙

### 7.2 Environment Variables Needed

| Variable | Purpose | Default | To Be Created |
|----------|---------|---------|:-------------:|
| `ANSWER_PROVIDER` | 답변 1순위 제공자 고정(장애 시 무배포 롤백) | (빈값 = Claude) | 기존·**문서화 필요** |
| `OPENAI_CHAT_MODEL` | 답변/교정 OpenAI 모델 | `o3` | 기존·**문서화 필요** |
| `GEMINI_API_KEY` | 3순위 제공자 활성 | (미설정) | 기존·**실체 확인 필요** |
| `LLM_FIRST_CHUNK_TIMEOUT` | 첫 청크 대기 상한(폴백 전환 트리거) | 설계에서 확정 | ☐ |
| `LLM_MAX_RETRIES` | 임계경로 재시도 횟수 | 설계에서 확정 | ☐ |
| `INTENT_FALLBACK_ENABLED` | 의도분석 교차벤더 폴백 on/off(즉시 완화용) | `true` | ☐ |
| `CITATION_FIX_TIMEOUT` | 인용 교정 호출 상한 | 설계에서 확정 | ☐ |

---

## 8. Next Steps

1. [x] **선행 확인 완료**: `GEMINI_API_KEY`는 유효하나 **모델(`gemini-2.5-pro`)이 404로 사망** — FR-08은 "확인"이 아니라 "복구"로 확정(설계 §1.3·§4.1)
2. [x] **타임아웃 예산표 확정**: 설계 §3.4 — 최악 누적 ≈ 237초 < 300초, 무이벤트 최대 25초 < 60초
3. [x] 설계 문서 작성 완료: [llm-fallback-hardening.design.md](../../02-design/features/llm-fallback-hardening.design.md)
4. [ ] 구현(Do) — 설계 §7 Wave 0(긴급 Gemini 복구) → A → B → C 순
5. [ ] 갭 분석(`/pdca analyze`) → 장애 주입 양성 검증(FR-12) → 보고서

**오픈 항목**
- ~~프로덕션 Vercel 환경변수 `GEMINI_API_KEY` 미확인~~ → **2026-08-06 해소**: 로컬·Vercel 양쪽 갱신 완료(운영자 확인). 로컬에서 `gemini-pro-latest` 3순위 폴백 실동작 검증됨(`provider=Gemini`, 9.1초). 다만 **404의 원인은 키가 아니라 은퇴한 모델명**이었으므로, 실질 해결은 `GEMINI_MODEL` 교체(FR-08) 쪽이다
- 답변 스트림의 wall-clock 데드라인(서버가 200 + 하트비트만 보내는 병리 케이스)은 설계 §3.3에서 **범위 제외** — 서버리스 스레드 누수 위험이 이득보다 큼

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-08-06 | Initial draft — LLM 호출 8지점 실측 인벤토리, 갭 G1~G9 도출, 장애 모델 F1~F7, FR 13종 정의. 범위 결정: 전 계층 + 의도분석 교차벤더 폴백 | DrunkenZealnut |
| 0.2 | 2026-08-06 | 설계 단계 실측 반영 — G7을 "실체 불명"에서 "**이미 404로 사망**"으로 확정하고 FR-08을 High 승격. Next Steps 1~3 완료 처리, 오픈 항목 2건 기재 | DrunkenZealnut |
