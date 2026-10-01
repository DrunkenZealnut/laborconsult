# anthropic-sdk-v1 Planning Document

> **Summary**: Anthropic Python SDK 1.x 비호환 3종(스트림·타임아웃 타입·temperature)을 0.x/1.x 양립 코드로 바꾸고, SDK 계약 테스트로 고정한 뒤 `<1.0` 상한을 푼다.
>
> **Project**: laborconsult
> **Author**: Claude (with DrunkenZealnut)
> **Date**: 2026-09-29
> **Status**: Cancelled (2026-09-29) — SDK 업그레이드 불요, `anthropic<1.0` 상한 유지로 종결

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 2026-09-27 재빌드가 상한 없는 `anthropic>=0.20.0`을 1.8.0으로 해석해 Claude 답변이 전량 OpenAI로 폴백됐고 쿼리 분해도 꺼졌다. 폴백이 흡수해 **오류 없이 품질만** 떨어졌고, SDK 계약을 검사하는 테스트가 없어 CI도 통과했다. 현재는 `<1.0` 상한으로 봉합한 상태다. |
| **Solution** | 비호환 3종을 **두 버전 모두에서 동작하는 형태**로 교체(스트림은 이벤트 순회, 타임아웃은 `anthropic.Timeout`, temperature 제거)하고, 설치된 SDK의 시그니처·스트림 형태를 검사하는 계약 테스트를 CI에 넣은 뒤 상한을 푼다. |
| **Function/UX Effect** | 사용자 체감 변화 없음(1순위 Claude 답변·쿼리 분해·Self-RAG·인용 교정 유지). 다음 SDK 메이저 업이 오면 **배포 전 CI에서** 실패한다. |
| **Core Value** | "폴백이 장애를 삼킨다"는 이 코드베이스의 반복 패턴(모델 폐기 404, reasoning 빈 응답)을 의존성 축에서도 막는다. |

---

## 1. Overview

### 1.1 Purpose

SDK 1.x에서 깨지는 호출부를 버전 양립 코드로 바꾸고, 같은 클래스의 회귀가 **조용히** 프로덕션에 나가지 못하게 한다.

### 1.2 Background — 실측 (2026-09-29, 격리 venv에 anthropic 1.8.0 설치 후 검사)

| # | 1.x 변경 | 영향 호출부 | 증상 |
|---|---|---|---|
| B1 | 전송 계층 `httpx` → `httpx2`. `timeout`은 `float \| httpx2.Timeout`만 수용 | `pipeline.py::_stream_claude`(398), `citation_validator.py`(303) | Claude 답변 전량 실패 → OpenAI 폴백(프로덕션 실측), 인용 교정 Claude 경로 실패 |
| B2 | `Messages.create/stream` 시그니처에서 `temperature` **삭제** | `query_decomposer.py:209`(0.3), `self_rag.py:55`(0), `citation_validator.py:310·439`(0), `pinecone_upload_contextual.py:342`(0) | 쿼리 분해 실패(프로덕션 실측), Self-RAG·인용 교정·마이크로 폴리시 실패 → 각자 폴백 |
| B3 | `MessageStream.text_stream` **삭제** — 스트림 순회 시 `TextEvent(type="text", text)`가 나온다 | `pipeline.py:411`, `chatbot.py:485` | B1을 고쳐도 답변 스트리밍이 AttributeError로 다시 폴백 |

**양립 가능성 확인**: `anthropic.Timeout`(0.120.2=httpx 기반, 1.8.0=httpx2 기반)과 `anthropic.lib.streaming.TextEvent(type, text, snapshot)`는 **양쪽 버전에 모두 있다.** 그래서 코드를 먼저 바꾸고 상한을 나중에 푸는 무중단 순서가 가능하다.

**유지되는 표면**(1.8.0 확인): `Anthropic(api_key, timeout, max_retries)`, `with_options(timeout, max_retries)`, `messages.create/stream`의 `model·max_tokens·messages·system·tools·tool_choice`, `TextBlock.text`, `ToolUseBlock.input`, `APITimeoutError`(⊂ `APIConnectionError`).

**temperature 영향 판단**: 답변·의도분석(Sonnet 5)은 이미 미지정이다(모델이 400으로 거부). 남은 곳은 전부 Haiku 4.5의 판정·교정 호출이다. 모델은 아직 temperature를 받으므로 `extra_body`로 우회 전달이 가능하다. 다만 이는 SDK가 의도적으로 뺀 파라미터를 되살리는 것이라, 다음 모델 교체 때 400으로 다시 조용히 폴백될 위험을 심는다.

### 1.3 Related Documents

- `docs/02-design/features/llm-fallback-hardening.design.md` — 폴백·타임아웃 예산표(§3.4)
- CLAUDE.md "LLM provider fallback 규약", "모델명은 별칭으로"

---

## 2. Scope

### 2.1 In Scope

- [ ] B1: Anthropic 호출의 `httpx.Timeout` → `anthropic.Timeout` (OpenAI 호출의 `httpx.Timeout`은 그대로 — 별개 SDK)
- [ ] B2: `temperature` 인자 제거 5곳 (결정 D1)
- [ ] B3: `stream.text_stream` → 이벤트 순회 `event.type == "text"` (pipeline·chatbot)
- [ ] 계약 테스트 T-SDK: 설치된 SDK에 대해 ① 우리가 넘기는 kwargs 전부가 `Messages.create/stream` 시그니처에 존재 ② `anthropic.Timeout` 수용 ③ 가짜 이벤트 스트림으로 `_stream_claude`가 텍스트를 내는지
- [ ] CI: 오프라인 테스트를 **anthropic 최신 메이저**로도 1회 더 실행하는 job(결정 D2)
- [ ] `requirements.txt` 상한 해제 → 재배포 → 프로덕션 `llm_outcome provider=Claude` 확인

### 2.2 Out of Scope

- openai 3.x / pinecone 10.x — 같은 재빌드에서 메이저 업됐지만 현재 정상 동작(프로덕션 로그 확인). 상한 여부는 별도 판단
- 요구사항 전면 lock 파일(`uv.lock` 등) 도입 — 아래 D2 대안으로만 기록
- 모델 교체, 프롬프트 변경

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-01 | SDK 0.x·1.x **양쪽**에서 Claude 답변 스트리밍이 1순위로 성공 | High |
| FR-02 | 쿼리 분해·Self-RAG·인용 교정·마이크로 폴리시의 Claude 경로가 양쪽에서 동작 | High |
| FR-03 | 타임아웃 예산(connect/read/write/pool)이 변경 전과 동일 | High |
| FR-04 | 계약 테스트가 B1~B3 각각을 **변경 전 코드에서 실패**, 변경 후 통과 | High |
| FR-05 | `chatbot.py`·`pinecone_upload_contextual.py` 오프라인 스크립트도 양립 | Medium |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement |
|----------|----------|-------------|
| 무중단 | 상한 해제 전 배포가 0.x에서 무회귀 | 기존 오프라인 테스트 전량 + 프로덕션 1건 |
| 관측 | 폴백 발생이 로그에 남음(기존 `llm_outcome`) | 전환 후 1주 `attempts=['Claude']` 비율 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] 0.120.x·1.8.x 각각에서 오프라인 테스트 전량 + T-SDK 통과
- [ ] T-SDK가 현행 main 코드 + 1.8.0 조합에서 **실패함을 먼저 확인**(테스트가 실제로 잡는지)
- [ ] 상한 해제 배포 후 프로덕션 질문 1건: `llm_outcome provider=Claude attempts=['Claude']`, `쿼리 분해 완료` 로그
- [ ] CLAUDE.md 폴백 규약 절에 "SDK 계약 테스트" 한 줄

### 4.2 Quality Criteria

- 인용 교정·Self-RAG 결과가 temperature 제거로 흔들리지 않는지: `eval_retrieval.py` 도달률 기준선 대비 −2%p 이내

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| temperature 제거로 Haiku 판정(Self-RAG yes/no, 인용 교정)이 비결정적이 됨 | Medium | Medium | 판정은 단답·저엔트로피 출력이라 영향이 작을 것으로 본다. 4.2 평가로 확인하고, 회귀 시 D1-b(extra_body)로 전환 |
| 0.x 이벤트 순회가 1.x와 미묘하게 다름(예: 텍스트 외 이벤트) | High | Low | 두 버전 모두 `TextEvent` 클래스 확인. `type == "text"` 필터만 쓰고 나머지 이벤트는 무시 |
| 1.x의 다른 비호환(예외 계층·재시도 동작) 미발견 | Medium | Medium | CI 최신 메이저 job이 오프라인 테스트 전체를 1.x로 돌린다. 예외 계층은 `APITimeoutError ⊂ APIConnectionError` 유지 확인됨 |
| 상한 해제 후 또 다른 메이저(2.x)가 조용히 설치 | High | Low | 상한을 **없애지 않고 `<2.0`으로 한 칸 올린다** + CI 최신 job이 조기 경보 |

---

## 6. Architecture Considerations

### 6.1 Project Level Selection

Dynamic (기존 유지 — Vercel + Supabase 고정)

### 6.2 Key Architectural Decisions

| Decision | Options | 권장 | Rationale |
|----------|---------|------|-----------|
| **D1** temperature | a) 제거 / b) `extra_body={"temperature": 0}` 우회 | **a** | SDK가 의도적으로 뺀 파라미터. b는 다음 모델에서 400 → 조용한 폴백을 재현한다(Sonnet 5가 이미 그렇게 거부 중). 4.2 평가가 회귀를 보이면 b로 |
| **D2** 재발 방지 | a) CI 최신 메이저 job + 한 칸 상한 / b) 전체 lock 파일 / c) 상한만 | **a** | b는 모든 의존성의 보안 패치를 막고 Vercel Python 빌드와의 정합 검증이 별도로 필요하다. c는 오늘의 사고를 반복한다(상한을 올리는 순간 무검증) |
| **D3** 타임아웃 타입 | a) `anthropic.Timeout` / b) float 단일값 | **a** | connect/read 분리 예산(llm-fallback-hardening §3.4)을 유지해야 한다. float는 connect 대기도 read 한도까지 늘린다 |
| **D4** 전환 순서 | a) 양립 코드 → 배포 → 상한 해제 → 배포 / b) 한 번에 | **a** | 각 단계가 독립 롤백 가능. 1단계만으로 0.x에서 무회귀를 먼저 확인 |

### 6.3 변경 파일 (예상)

```
app/core/pipeline.py          B1·B3 (_stream_claude)
app/core/citation_validator.py B1·B2 (2곳)
app/core/query_decomposer.py  B2
app/core/self_rag.py          B2
chatbot.py                    B3
pinecone_upload_contextual.py B2
test_llm_fallback.py          T-SDK (또는 신규 test_anthropic_sdk_contract.py)
.github/workflows/tests.yml   최신 메이저 job
requirements.txt              상한 <2.0 (2단계)
```

---

## 7. Convention Prerequisites

### 7.1 Existing Project Conventions

- [x] 폴백 규약: 빈 응답=실패, 재시도보다 전환, `max_retries=0` (CLAUDE.md)
- [x] 모든 `app/core/*.py`는 `from __future__ import annotations`
- [x] 오프라인 테스트는 API 키 불요 — T-SDK도 네트워크 없이(가짜 스트림·시그니처 검사)

### 7.2 Conventions to Define

| Category | Rule |
|----------|------|
| SDK 타입 | Anthropic 호출에 `httpx.*`를 직접 쓰지 않는다 — SDK가 재수출하는 `anthropic.Timeout`만 |
| 의존성 | 메이저 업이 잦은 LLM SDK는 "한 칸 상한 + CI 최신 job" 쌍으로만 관리 |

### 7.3 Environment Variables Needed

없음

### 7.4 Pipeline Integration

해당 없음(9-phase 파이프라인 미사용 프로젝트)

---

## 8. Next Steps

1. [ ] D1·D2 결정 확인
2. [ ] `/pdca design anthropic-sdk-v1`
3. [ ] 구현 → gap 분석
