# ai-gateway-oidc-migration — 완료 보고서

> **Status**: Complete (단, Gemini 직접 호출 잔존 · 후속 7건 명시 — 그중 F-1 V-9 토큰 만료 실측은 2026-10-30 완료, §9)
>
> **Project**: laborconsult
> **Version**: main `1c4f9cf` (Plan v0.1 · Design v0.3 · Analysis v1.2) · Report v1.3
> **Author**: Claude
> **Completion Date**: 2026-10-28
> **PDCA Cycle**: #1

---

## Executive Summary

### 1.1 Project Overview

| Item | Content |
|------|---------|
| Feature | ai-gateway-oidc-migration: 요청 경로 LLM 호출을 Vercel AI Gateway(OIDC 인증 + Gateway 크레딧)로 전환 |
| Start Date | 2026-10-28 (Plan v0.1 작성) |
| End Date | 2026-10-28 (Act 배포 확인 완료) |
| Duration | 1일 (Plan·Design·Do·Check·Act·Report 전 단계를 2026-10-28 한 날에 완료) |
| 기준 코드 | main `9529cf1` → 완료 시점 main `1c4f9cf` |
| 변경 규모 | 커밋 7개, 19파일, +2,243 / -40 |
| 전송 스위치 | Vercel env `LLM_TRANSPORT` (`gateway` / `direct`, 기본 `direct`) |

### 1.2 Results Summary

```
┌──────────────────────────────────────────────────────────────┐
│  Match Rate (Check → Act):  93.0%  →  99.7%                  │
│  Gateway 전환 (프로덕션):   완료 (transport=gateway 확인)     │
│  Gemini 3순위:              직접 호출 잔존 (Gateway 슬러그 없음)│
│  테스트:  test_llm_transport.py 26/26 · 변이 검사 7/7        │
│  PR:      #145 머지(74aa04d) · #146 머지(1c4f9cf)            │
│  배포:    Preview 2질문 · 롤백 리허설 · Production 3질문 │
│  잔여:    복귀 창 뒤 키 삭제(승인 필요) · V-9 실측 완료(10-30) │
└──────────────────────────────────────────────────────────────┘
```

### 1.3 Value Delivered

| Perspective | Content |
|-------------|---------|
| **Problem** | 프로덕션 LLM 호출이 벤더 4곳의 장기 API 키와 벤더별 선불 잔액에 묶여 있었다. 2026-10-27에 Anthropic 크레딧이 하루 두 번 소진되고 Gemini 선불이 말라 답변이 폴백으로만 이어졌다. |
| **Solution** | Vercel env `LLM_TRANSPORT=gateway`일 때(기본값 `direct`는 기존 직접 호출 그대로) 요청 경로(`api/`·`app/`)의 Claude·OpenAI·임베딩·Cohere 호출을 Vercel AI Gateway로 보낸다. 인증은 요청마다 Vercel이 주는 OIDC 토큰(`x-vercel-oidc-token`)을 `config` 객체에 묶어 쓰고, `LLM_TRANSPORT=gateway`에서는 제공자 키를 읽지 않는다. 슬러그 변환은 SDK 경계 프록시 한 곳에서만 한다. |
| **Function/UX Effect** | 사용자 화면·답변 동작은 바뀌지 않았다. 프로덕션 질문 3건(머지 배포 2건 + Act 배포 확인 1건)이 `metadata.llm.transport=gateway`, 폴백 0으로 완주했다. 임베딩 코사인 0.999999(3문장), Cohere 재정렬 상위 5 순서 동일(점수 차 ≤ 0.0003). 콜드 첫 글자 시간은 43~49초, 웜 26초(표본 적음, 개선 주장 아님). |
| **Core Value** | 장기 키를 요청 경로에서 제거하고 결제를 Gateway 크레딧 하나로 모았다. 인증 실패는 제공자 키로 우회하지 않고 `GatewayAuthError`로 드러나며, 롤백은 env 한 줄 또는 이전 배포 승격으로 즉시 가능하다. |

---

## 2. Related Documents

| Phase | Document | Status |
|-------|----------|--------|
| Plan | [ai-gateway-oidc-migration.plan.md](ai-gateway-oidc-migration.plan.md) | Finalized (v0.1) |
| Design | [ai-gateway-oidc-migration.design.md](ai-gateway-oidc-migration.design.md) | Finalized (v0.3, Check 반영) |
| Check/Act | [ai-gateway-oidc-migration.analysis.md](ai-gateway-oidc-migration.analysis.md) | Complete (v1.2, Act 99.7%) |
| Report | Current document | Complete |

PR · 커밋

| PR | 내용 | 커밋 | 상태 |
|----|------|------|------|
| #145 | 전송 계층 구현(Do) | fdc80d4 · c6bdc85 · 9f6c9c6 → 머지 74aa04d | 머지 |
| #146 | Check 갭 조치(Act) + CodeRabbit 반영 | 8970c61 · 6f75027 → 머지 1c4f9cf | 머지 |

---

## 3. Completed Items

### 3.1 Functional Requirements (Plan 완료 조건 대비)

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| C-1 | `LLM_TRANSPORT=gateway`에서 Claude·OpenAI·임베딩·Cohere가 Gateway로 가고, 제공자 키를 읽는 경로가 없다 | Complete | 요청 경로 우회 0건(Check §7.1 전수). T2·T4가 고정 |
| C-2 | 미설정·`direct`에서 현재 동작과 동일 | Complete | `bind(config) is config`(T1). 기존 스위트 통과 |
| C-3 | 임베딩 표본 코사인 ≥ 0.999, 재정렬 상위 순서 동일 | Complete | 코사인 0.999999 ×3 (1536차원). 재정렬 상위 5 순서 동일, 점수 차 ≤ 0.0003 |
| C-4 | Preview에서 상담·계산·SSE 1회씩 정상, Gateway 기록 | Complete | Preview 2질문 SSE 완주, `transport=gateway` 저장 |
| C-5 | 프로덕션 개인정보 없는 질문 2건 정상 + `transport=gateway` | Complete | 주휴수당·최저임금 2건. 이후 Act 배포 확인 1건 추가 |
| C-6 | 롤백 절차 문서화 + 1회 리허설 | Complete | Preview `direct` 재배포 → `transport=direct` 확인 |
| C-7 | 최종 보고에 잔존 직접 호출·키·삭제 후보·비용·사용자 작업 명시 | Complete | 본 문서 §4.2, §6 |

### 3.2 Non-Functional Requirements

| Item | Target | Achieved | Status |
|------|--------|----------|--------|
| 동작 동일성 (direct) | 기존 스위트 전부 통과 | CI `offline-tests`(전 오프라인 스위트) PR #145·#146 통과 + 로컬 재실행 `test_llm_fallback`·`test_offline_units`·`test_pipeline_wiring`·`test_model_settings` 통과 | Complete |
| 전송 단위 테스트 | 신규 T1~T15 | `test_llm_transport.py` 26/26 (T1~T15 및 하위 단언) | Complete |
| 변이 검사 | 수정 되돌리면 테스트 실패 | Act 5건 + CodeRabbit 2건 = 7/7 | Complete |
| 임베딩 호환 | 코사인 ≥ 0.999 | 0.999999 | Complete |
| 재정렬 호환 | 상위 5 순서 동일 | 동일, 점수 차 ≤ 0.0003 | Complete |
| 지연 (콜드 TTFT) | 기존 대비 악화 없음 | 프로덕션 43.1초(콜드) / 26.1초(웜), Act 배포 확인 49.0초(콜드, 표본 1건). 전후 비교 미측정 | 미측정 (판정 보류) |
| CI | 전부 통과 | offline-tests·GitGuardian·CodeRabbit·Vercel 통과 (PR #146 기준) | Complete |

### 3.3 Deliverables

| Deliverable | Location | Status |
|-------------|----------|--------|
| 전송 계층 (bind·_Bound·슬러그·카탈로그·Cohere) | `app/core/llm_transport.py` | Complete |
| 인증 (헤더 토큰 contextvar·GatewayAuthError) | `app/core/gateway_auth.py` | Complete |
| AppConfig gateway 분기·`.env.vercel.local` 로드 | `app/config.py` | Complete |
| 요청별 바인딩·미들웨어 캡처 | `api/index.py` (`get_config`, `_security_headers`) | Complete |
| 강제 tool_choice 자가치유 + 선등록 | `app/core/llm_gateway.py` | Complete |
| Cohere base_url 전달 | `app/core/rag.py`, `app/core/pipeline.py`, `eval_retrieval.py`, `eval_colloquial.py` | Complete |
| 관리자 모델 목록 (카탈로그 기반, released 정렬) | `app/core/model_settings.py` | Complete |
| 전송 오프라인 테스트 | `test_llm_transport.py` (CI 등록 `.github/workflows/tests.yml`) | Complete |
| 설계·분석·운영 절차 | `docs/archive/2026-10/ai-gateway-oidc-migration/`(Plan·Design·Analysis·Report), `CLAUDE.md`, `.env.example`, `check_env.py` | Complete |

### 3.4 제약 준수 (Plan §1 10개 항목)

| # | 제약 | 준수 여부 | 근거 |
|---|------|-----------|------|
| 1 | 추가 결제·크레딧 구매·자동 충전 설정 금지 | 준수 | 결제·구매·자동 충전 0회. 잔액은 조회만 함 |
| 2 | 키·OIDC 토큰 값을 화면·로그·문서에 출력하지 않음 | 부분 위반 1건 (기록) | 구현 중 `test_llm_transport.py` T2 실패 메시지가 로컬 토큰을 터미널에 한 번 출력했다. 저장소·PR·로그 밖이며, 토큰은 12시간 만료다. 단언을 값 비출력으로 고쳤고 이후 출력 없음(T8 고정). 본 문서에는 값을 쓰지 않았다 |
| 3 | 인증 실패 시 제공자 키 몰래 사용 금지 | 준수 | 제공자 키로 가는 분기 없음(T2·T4, Check §7.1 전수 0건). Gemini는 3순위 직접 호출이 설계상 존속(제약 7 참조) |
| 4 | 지원 안 되는 모델을 임의 대체 금지 | 준수 | 미해결 슬러그는 `UnsupportedModelError`(T5). 하이픈→점 추측 변환 없음 |
| 5 | SDK 버전 제한 사유를 읽고 무조건 올리지 않음 | 준수 | `anthropic<1.0` 유지(1.x의 httpx 전제 충돌). 0.120.2에서 `with_options(api_key=)` 동작 확인(V-2) |
| 6 | 임베딩 모델·차원·Pinecone 데이터 유지 | 준수 | `text-embedding-3-small` 1536 유지, 코사인 0.999999. Pinecone 삭제·재색인 없음 |
| 7 | 미지원 경로는 명시, 전체 완료로 보고 금지 | 준수 | Gemini 직접 호출 잔존을 명시(§4.2). 본 보고는 "전체 전환 완료"로 쓰지 않는다 |
| 8 | 미사용 키는 삭제 후보로만 정리, 제공자 측 키 폐기 금지 | 준수 | 삭제 후보 목록만 작성(§4.3). 복귀 창 7일 동안 Vercel env 키 유지 |
| 9 | 사용자 작업은 코드·검증을 먼저 끝내고 필요한 것만 알림 | 준수 | 잔액 확인·BYOK 확인·Gemini 슬러그 결정 등은 §8.1에 구체적으로 적었다 |
| 10 | 테스트 호출 최소화, 실패 시 복구 수단 준비 | 준수 | 로컬 검증 13회, Preview 2회, 프로덕션 질문 2건(+ Act 확인 1건). 롤백 리허설 수행 |

---

## 4. Incomplete Items

### 4.1 Carried Over to Next Cycle (후속 7건)

| # | Item | Reason | Priority | Estimated Effort |
|---|------|--------|----------|------------------|
| F-1 | ✅ V-9 OIDC 토큰 12시간 만료 실측 (만료 시 SDK 401 노출 확인) — **2026-10-30 완료**(§9 'V-9 실측' 행) | 로컬 1회 — 토큰을 **재pull하지 않고** 12시간 경과 → 만료 토큰으로 호출해 401 노출 확인 → 재pull로 복구 확인 (`vercel env pull`이 토큰을 갱신하므로 순서가 바뀌면 검증이 안 된다, §7). 수명 12.0시간 실측, 만료는 `GatewayAuthError`(토큰 부재 전용)가 아니라 SDK 401로 드러났다 | Medium | 0.5시간 (실측 약 7분) |
| F-2 | 복귀 창(≈2026-11-04) 뒤 Vercel env의 `ANTHROPIC_API_KEY`·`OPENAI_API_KEY`·`COHERE_API_KEY` 삭제 | 사용자 승인 필요 (제공자 측 키는 폐기하지 않음) | Medium | 0.2시간 |
| F-3 | Gateway 예산 상한·태그(`feature:chat`) 도입 | 부가 기능, 범위 밖 | Low | 1시간 |
| F-4 | `check_llm_fallback.py` 사각 보강: "최근 실사용 0건 + health 정상"을 정상으로 보는 문제, 전 제공자 실패는 미저장이라 ✅로 보임 | 기존 감시 사각, Gateway 장애도 같은 경로 | High | 2시간 |
| F-5 | `anthropic` 1.x 대응 (`httpx` 전제 충돌 해소) | SDK 메이저 업그레이드, 범위 밖 | Low | 미정 |
| F-6 | Gemini 슬러그 전환 (`GATEWAY_GEMINI_MODEL`, Design Q1 b) | 사용자가 슬러그를 정해야 함 (U3) | Low | 2시간 |
| F-7 | 콜드 TTFT 다표본 측정 (G-M1 선등록 효과 수치 확인) | 현재 표본 2~3건, 효과 판정 불가 | Medium | 1시간 |

### 4.2 Cancelled/On Hold Items

| Item | Reason | Alternative |
|------|--------|-------------|
| Gemini 3순위 Gateway 전환 (Q1 b) | `gemini-pro-latest` 별칭에 대응하는 Gateway 슬러그 없음. 모델을 바꾸지 않고는 전환 불가(임의 대체 금지) | 직접 호출 유지(잔존 직접 호출). Gemini 선불이 소진돼 현재 실질 비활성이라 손실 없음. 슬러그 결정 시 F-6 |
| V-7 Gemini OpenAI 호환 역할·function calling | Q1 b 미착수에 따라 미실시 | F-6와 함께 |
| 관리자 Gemini 목록 Gateway 전환 | Gemini 직접 호출 유지 | `genai.list_models` 현행 분기 유지 |

### 4.3 잔존 직접 호출 · 필요한 키 · 삭제 후보

| 구분 | 항목 | 상태 |
|------|------|------|
| 잔존 직접 호출 | `pipeline.py::_stream_gemini`, `llm_gateway.py::_gemini_text/_gemini_tool`, `model_settings.py` Gemini 목록 | Gemini는 Google 직접 호출 (`GEMINI_API_KEY` 필요) |
| 필요한 키 (Gateway 모드) | Gateway 경유 경로: `PINECONE_API_KEY`(`AppConfig.from_env()`가 gateway 모드에서 요구하는 유일한 **필수** 키) + 인증 토큰(프로덕션은 요청 헤더, 로컬은 `VERCEL_OIDC_TOKEN` 12시간) · Gemini 직접 호출(Gateway 밖): `GEMINI_API_KEY`(**선택** — 있을 때만 3순위에 들어가고 없으면 Gemini만 빠진다) | 프로덕션은 OIDC 헤더로 인증하므로 `AI_GATEWAY_API_KEY`를 두지 않음 |
| 삭제 후보 (복귀 창 7일 뒤, 사용자 승인) | Vercel env의 `ANTHROPIC_API_KEY`·`OPENAI_API_KEY`·`COHERE_API_KEY` | 복귀 창 동안 유지 필수. 제공자 측 키는 다른 프로젝트·로컬·Actions가 공유하므로 폐기하지 않음 |
| 정리 완료 | Preview 바이패스 비밀 폐기, 브랜치 한정 Preview env 삭제 | 완료 |

---

## 5. Quality Metrics

### 5.1 Final Analysis Results

| Metric | Target | Check (Final) | Act (Final) | Change |
|--------|--------|---------------|-------------|--------|
| Design Match Rate | 90% | 93.0% (✅127 · ⚠️12 · ❌4) | 99.7% (✅142 · ⚠️1 · ❌0) | +6.7%p |
| 대조 항목 | — | 143 (분모 제외: 설계 외 구현 14, N/A 8) | 동일 | — |
| 설계 사각 (Check 발견) | — | Medium 3 · Low 6 | 전부 조치 (Medium 3 + Low 8) | — |
| 요청 경로 제공자 키 우회 | 0건 | 0건 | 0건 | 유지 |
| 오프라인 테스트 | 전부 통과 | test_llm_transport 20/20 | test_llm_transport 26/26 | +6 |
| 변이 검사 | 되돌리면 실패 | — | 7/7 | — |

남은 ⚠️ 1건이었던 O8(V-9 토큰 만료 실측, F-1)은 2026-10-30 로컬 실측으로 해소됐다(§9 'V-9 실측' 행). 분석 문서의 Match Rate 수치는 Act 시점 기록이라 고치지 않는다.

### 5.2 Resolved Issues

| Issue | Resolution | Result |
|-------|------------|--------|
| G-M1: 강제 tool_choice 자가치유가 타임아웃에 기대고 콜드 인스턴스마다 낭비 왕복 1회 | 실측된 5.5 세대 모델(`claude-opus-5-5`·`claude-sonnet-5-5`·`claude-fable-5-1`)을 `_CLAUDE_TOOL_NO_FORCE_KNOWN`에 선등록 | Resolved (회귀 `test_claude_known_no_force_models_skip_forced_attempt`) |
| G-M2: 평가 스크립트가 `cohere_base_url` 없이 재정렬을 불러 OIDC 토큰이 Cohere 자체 호스트로 Bearer 전송 | `eval_retrieval.py`·`eval_colloquial.py`에 `cohere_base_url` 전달, AST 회귀 T13 | Resolved |
| G-M3: 관리자 목록 `created=None`으로 ID 역순 상위 3개가 선택됨 | 카탈로그 `released`를 `created`로 사용, T11 보강 | Resolved |
| BS5: 관리자 목록 토큰을 contextvar에서 재조회 | 바인딩 객체의 `bound_token()` 사용, T14 | Resolved |
| BS6: 카탈로그 네트워크를 잠금 안에서 호출 | 잠금 밖 조회, 실패 시 슬러그 표 유지, T15 | Resolved |
| BS6 2차 효과 (CodeRabbit #146): `/v1/models` 부분 실패가 1시간 캐시됨 | `listing_failed` 표식 + 60초 재조회 (빈 정상 목록은 1시간 유지) | Resolved |
| BS7·BS8: 미사용 함수, check_env 상대경로 | 제거, 저장소 루트 절대경로 | Resolved |
| BS4·BS9 (문서): 400 외 200 편차, 호출 지점·용어 낡음 | 설계 v0.3, docstring 정정 | Resolved |
| V-1 편차: Gateway가 강제 tool_choice를 400이 아닌 200 + 도구 미호출로 반환 | `_claude_tool`이 두 신호를 같은 취급, 회귀 `test_claude_forced_tool_choice_accepted_without_tool_use_falls_back_to_auto` | Resolved (Do 중 발견·조치) |

---

## 6. Lessons Learned & Retrospective

### 6.1 What Went Well (Keep)

- 실측 검증 항목(V-1~V-9, L1~L5)을 Do 첫 작업으로 두어, Gateway 표면의 편차(강제 tool_choice 200 응답)를 프로덕션 전에 찾았다.
- 전송 스위치(`LLM_TRANSPORT`)와 Preview 롤백 리허설 덕분에 프로덕션 전환이 env 한 줄 + 재배포로 끝났고, 복구 경로를 미리 확인했다.
- 요청별 바인딩 객체(`bind`)와 SDK 경계 프록시로 호출부 코드를 거의 건드리지 않았다(`_stream_*`, `llm_gateway` SDK 호출 형태 불변).
- Check 단계에서 설계 사각(G-M1~G-M3)을 찾았고, 그중 두 건(G-M2 토큰 오송신, G-M3 관리자 목록 정렬)은 프로덕션 경로가 아니라 평가·관리 경로라 Check 없이는 놓쳤을 것이다.
- 제약 준수를 Plan에 번호로 고정하고 보고 표에서 항목별로 판정했다.

### 6.2 What Needs Improvement (Problem)

- Gateway 호환 표면은 직접 API와 응답이 다르다(강제 tool_choice 400 → 200 + 미호출). 이것은 문서가 아니라 실측으로만 드러났다. 설계 단계의 "호환" 가정이 불충분했다.
- 테스트 실패 메시지가 토큰을 출력했다(T2). 비밀값을 다루는 단언은 실패 메시지에 값을 넣지 않는 형태로 처음부터 짜야 했다.
- 최초 회귀 테스트(G-M1)는 집합을 손으로 채워 변이를 잡지 못했다. reload로 초기 상태를 단언하도록 고쳤다.
- 설계 v0.1·v0.2의 서술(모듈명 `make_clients`, 상수 `TRANSPORT`, 3지점 호출, `llm_gateway.py` 무변경)이 구현과 어긋났고, v0.3에서 정정해야 했다.
- 기존 폴백 감시는 전 제공자 실패를 저장하지 않아 Gateway 장애를 잡지 못한다(F-4). 전환 검증의 증거가 "저장된 대화"에만 의존했다.

### 6.3 What to Try Next (Try)

- 공급자 호환 표면을 쓰는 전환은 설계 전에 "응답 형태 편차" 실측 항목을 먼저 목록화한다.
- 비밀값을 다루는 테스트는 실패 메시지 검사를 같은 단계에 포함한다(변이 검사로 확인).
- 조치에도 리뷰를 건다. CodeRabbit #146이 BS6 조치의 2차 효과(부분 실패 1시간 캐시)를 찾았다.
- Vercel env 변경은 다음 배포부터 적용되므로, 머지 전에 Production env를 넣고 머지 배포 1회로 전환하는 절차를 유지한다.
- 지연 개선은 표본 수를 정해 두고 측정한다. 단일 표본으로 개선을 주장하지 않는다.

---

## 7. Process Improvement Suggestions

### 7.1 PDCA Process

| Phase | Current | Improvement Suggestion |
|-------|---------|------------------------|
| Plan | 외부 서비스 조사를 공식 문서 기준으로만 함 | 실측 항목(호환 편차)을 Plan 위험 표에 미리 올림 |
| Design | 호출 지점 전수 열거는 잘 됐으나 응답 편차는 미기재 | 외부 API 호환 설계에는 "응답 편차 가설" 칸 추가 |
| Do | 테스트 실패 메시지의 비밀 노출 | 비밀 단언 템플릿 사용 |
| Check | gap-detector Match Rate가 "설계대로인가"만 답함 | 변경 경로 전수 리뷰를 유지(설계 사각 7.2 방식) |

### 7.2 Tools/Environment

| Area | Improvement Suggestion | Expected Benefit |
|------|------------------------|------------------|
| 감시 | `check_llm_fallback.py`에 전 제공자 실패 신호 추가 (F-4) | Gateway 장애 조기 감지 |
| 비용 | Gateway 태그·예산 상한 (F-3) | 기능별 비용 분리, 잔액 소진 전 경고 |
| 측정 | 콜드 TTFT 측정 스크립트 표준화 (F-7) | 지연 변화 판정 가능 |

---

## 8. Next Steps

### 8.1 Immediate (사용자 작업)

- [ ] AI Gateway 잔액 확인 (`GET /v1/credits` 기준 $12.52, 누적 사용 $2.89 — 충전 필요 시 사용자 결정)
- [ ] BYOK 키가 Gateway에 등록돼 있지 않은지 대시보드 확인 (미확인 상태 — 등록돼 있으면 크레딧 대신 그 키로 과금됨)
- [ ] Gemini 3순위 결정: 직접 호출 유지(현재) 또는 `google/<모델>` 슬러그 지정 (F-6)
- [ ] 복귀 창 종료(≈2026-11-04) 뒤 Vercel env 제공자 키 3종 삭제 승인 (F-2)
- [x] 로컬 V-9 (**2026-10-30 완료**, §9 'V-9 실측' 행): 기존 `.env.vercel.local`의 토큰을 **재pull 없이** 12시간 넘게 둔 뒤 `LLM_TRANSPORT=gateway`로 Gateway 호출 1회 → 만료 토큰은 **SDK 401**(`anthropic.AuthenticationError`·`openai.AuthenticationError`·Cohere `UnauthorizedError`)이 그대로 드러나고 제공자 키 폴백·토큰 값 출력이 없는지 확인 → 그 뒤 `vercel env pull .env.vercel.local --environment development`로 갱신해 정상 복구 확인 (F-1). `vercel env pull`은 토큰을 **갱신**하므로 먼저 실행하면 만료 동작을 볼 수 없다. `GatewayAuthError`는 토큰이 **없을 때**만 나는 예외라 만료 경로에서는 나지 않는다(실측 0회) — 이전 판의 "`GatewayAuthError`(SDK 401)" 표기는 두 경우를 합쳐 쓴 것이라 정정

### 8.2 Next PDCA Cycle

| Item | Priority | Expected Start |
|------|----------|----------------|
| F-4 `check_llm_fallback.py` 사각 보강 (전 제공자 실패·health만 정상인 경우) | High | 다음 사이클 |
| F-7 콜드 TTFT 다표본 측정 (G-M1 효과 판정) | Medium | 프로덕션 트래픽 누적 후 |
| F-3 Gateway 예산 상한·태그 | Low | 크레딧 운영 기준 정해진 후 |
| F-5 `anthropic` 1.x 대응 | Low | SDK 전환 계획 수립 시 |

---

## 9. 증거 (Evidence)

| 항목 | 값 |
|------|-----|
| Preview 질문 | 2건 SSE 완주, `transport=gateway` |
| 롤백 리허설 | Preview `direct` 재배포 → `transport=direct` 확인 |
| Production 질문 (머지 배포 후) | 주휴수당·최저임금 2건: SSE 완주, `transport=gateway`, provider Claude, model `claude-opus-5-5`, attempts `['Claude']`, fallback 없음 |
| Production 콜드/웜 TTFT | 43.1초 / 26.1초 (표본 2건, 개선 주장 아님) |
| Act 배포 확인 (배포 1c4f9cf, 2026-10-28 13:36 UTC) | health 200, 연차휴가 1질문 SSE 완주, TTFT 49.0초(콜드)·총 69.2초·2,659자. Supabase: transport=gateway, Claude, `claude-opus-5-5`, fallback·empty·intent_provider·synthetic 모두 없음 |
| 임베딩 동일성 (L1) | 3문장 코사인 0.999999, 1536차원, 모델 에코 `openai/text-embedding-3-small` |
| 재정렬 동일성 (V-5) | 상위 5 순서 동일, 점수 차 ≤ 0.0003 |
| 크레딧 (`GET /v1/credits`) | 설계 검증 시작 $13.97 → 머지 배포 직전 $13.21 → 프로덕션 2질문 후 $12.77 (차액 $0.44) → Act 확인 1질문 후 $12.52, 누적 사용 $2.89 (전환 이후 로컬 검증 13회·Preview 2·프로덕션 3질문 포함) → 2026-10-30 V-9 실측 후 $12.30, 누적 사용 $3.11 (실측 비용 약 $0.22 = 로컬 질문 1건 + 호출 3종) |
| V-9 실측 (2026-10-30 로컬, F-1) | 토큰 수명 **12.0시간** 실측(발급 10-28 17:42:19 KST → 만료 10-29 05:42:19 KST, 호출 시점 나이 37시간). **만료 토큰**: Claude `messages.create`·임베딩·`/v2/rerank`·`/v1/credits` 전부 HTTP 401(`anthropic.AuthenticationError`·`openai.AuthenticationError`·Cohere `UnauthorizedError`), `GatewayAuthError` 0회(토큰 부재 전용). 서버 경로 질문 1건: `/api/health` 200(토큰 불요) → 의도분석 Claude 401 → OpenAI 401 → 레거시 추출, 임베딩 401, 재정렬 401 → 코사인 폴백, 답변 Claude 401 → OpenAI 401 → Gemini 직접 호출(설계 3순위) 429 선불 소진 → 사용자 안내 "모든 AI 서비스에 연결할 수 없습니다", 본문 0자. 제공자 키 미사용(내부 Anthropic·OpenAI 클라이언트 키 ≠ `.env` 키, Cohere 키 자리 = OIDC 토큰), 모델명 설정값 그대로(`claude-opus-5-5`·`gpt-6-sol`), 토큰 값 유출 0건(SSE·로그·예외 메시지). **재pull**(`vercel env pull … --environment development`, 06:43:38 KST, 변경 항목 `VERCEL_OIDC_TOKEN` 1개, 새 만료 18:43:38 KST) 뒤 같은 호출 3종 정상(`anthropic/claude-sonnet-5` 응답·1536차원·재정렬 순서 정상), 같은 질문 54초에 2,625자 완주, 401 0건. 관찰: Gateway 401 본문은 `AI_GATEWAY_API_KEY` 생성을 안내하는데 로컬 OIDC의 처방은 재pull이다(로그 힌트 보강은 Low 후보, 미착수) |
| 폴백 감시 | `check_llm_fallback.py` 로컬 실행(2026-10-28 22:4x KST, 프로덕션 Supabase): **LLM 폴백 ✅ 정상**(최근 실사용 3건 전부 Claude `claude-opus-5-5`, attempts Claude, 저하 없음) · 법령 조회 ✅ 정상(예열 06:10 7,475행 18종 실패 0, 조문 성공률 100%, 분모 50). exit 0. 단 이 감시는 전 제공자 실패를 보지 못한다(F-4) |
| 배포 | 전환 배포 = 머지 커밋 `74aa04d`의 Production 배포(2026-10-28 09:24 UTC) · Act 배포 = `1c4f9cf`의 Production 배포(13:36 UTC, GitHub deployment 7386871227 — 배포 URL은 Vercel 대시보드 Deployments에서 커밋 `1c4f9cf`로 조회) · 롤백 B 대상(이전 프로덕션) = `9529cf1` 배포 |

비용 변화: 전환 전후 청구처 변화(Anthropic·OpenAI·Cohere 3곳 → Gateway 1곳)는 확인됐다. 전후 월 비용 비교는 측정 기간이 짧아 미측정이다.

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-10-28 | 완료 보고서 작성 (Plan v0.1 · Design v0.3 · Analysis v1.2 기준, 1c4f9cf 기준 증거) | Claude |
| 1.1 | 2026-10-28 | 증거 보정 — 크레딧 추이(13.97→13.21→12.77→12.52), 배포 식별(GitHub deployment·URL), 폴백 감시 실측(✅ 정상), 스위트 서술을 CI 기준으로 | Claude |
| 1.2 | 2026-10-29 | PR #147 Codex P2 반영 — V-9(F-1) 절차를 '재pull 없이 만료 → 401 확인 → 재pull 복구' 순서로 정정(`vercel env pull`은 토큰 갱신) | Claude |
| 1.4 | 2026-10-30 | F-1 V-9 토큰 만료 실측 완료 반영 — §8.1 5번 체크, 만료 경로 표기를 `GatewayAuthError`에서 SDK 401로 정정(`GatewayAuthError`는 토큰 부재 전용), §9 'V-9 실측' 행·크레딧 추이($12.30·누적 $3.11) 추가, Status·§1.2 잔여·§4.1 F-1·§5.1 O8 갱신 | Claude |
| 1.3 | 2026-10-29 | PR #147 CodeRabbit Minor 3건 반영 — Solution에 `LLM_TRANSPORT=gateway` 조건 명시, 필요한 키를 Gateway 경유(필수 PINECONE)와 Gemini 직접 호출(선택 GEMINI)로 분리, 축약 배포 URL을 deployment ID로 대체. 2건은 미반영(크레딧 잔액은 Vercel이 USD로 정산하므로 원화 환산 안 함 · 타 사이클 문서 경로는 그 사이클 PR에서 커밋) | Claude |
