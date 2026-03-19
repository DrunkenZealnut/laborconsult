# 맥락 기반 판례 검색(Contextual Precedent Search) Planning Document

> **Summary**: 법원 판례 검색 시 사용자 질문의 정확한 단어가 아닌, 맥락에서 도출된 법적 쟁점·키워드로 검색하여 관련 판례 적중률을 높인다.
>
> **Project**: nodong.kr 노동법 Q&A 챗봇
> **Author**: Claude + zealnutkim
> **Date**: 2026-03-15
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 현재 판례 검색이 `question_summary`(한 줄 요약) 또는 사용자 질문 앞 80자를 그대로 법제처 API에 전달하여, 법적 쟁점과 무관한 일상어가 섞이고 핵심 법률 키워드가 누락되어 관련 판례를 못 찾거나 엉뚱한 판례가 반환된다. |
| **Solution** | Analyzer 단계에서 LLM이 "판례 검색용 키워드"를 별도로 추출하고, 주제별 법적 쟁점 키워드 매핑·다중 쿼리 전략을 적용하여 법제처 판례 API 검색 품질을 높인다. |
| **Function/UX Effect** | 사용자가 "사장이 갑자기 나가라고 하는데 어떻게 해야 하나요" 같은 일상어 질문에도 "부당해고 해고예고수당 근로기준법" 관련 판례가 정확히 검색되어 답변 신뢰도가 향상된다. |
| **Core Value** | 노동법 상담의 핵심 가치인 "법적 근거에 기반한 답변"의 완성도를 높여, 판례 없는 답변 비율을 줄이고 실질적으로 유용한 판례 인용을 제공한다. |

---

## 1. Overview

### 1.1 Purpose

법제처 판례 검색 API의 검색 품질을 개선하여, 사용자의 노동법 질문 맥락에서 실제로 필요한 판례를 정확히 찾아 제공한다.

### 1.2 Background

**현재 문제점:**

1. **쿼리 구성이 단순함**: `pipeline.py:794`에서 `question_summary` 또는 `query[:80]`을 그대로 법제처 API에 전달
   - 예: "월급 250만원 받는데 연장수당 안 줘요" → 이 문장 자체가 판례 검색 쿼리가 됨
   - 법제처 API는 키워드 매칭 기반이므로 "월급", "250만원" 같은 무관한 단어가 노이즈

2. **검색 키워드가 법적 쟁점을 반영하지 않음**:
   - "사장이 갑자기 나가라고 함" → 법적으로는 "부당해고", "해고예고" 쟁점
   - "야근비를 안 줘요" → 법적으로는 "연장근로수당", "통상임금" 쟁점
   - 현재 시스템은 이런 법적 용어 변환을 하지 않음

3. **단일 쿼리 전략**: 한 번의 검색으로 최대 3건만 가져옴
   - 쟁점이 복수일 때(예: 부당해고 + 임금체불) 한쪽 판례만 검색됨

4. **대화 맥락 미반영**: 후속 질문에서 이전 맥락이 판례 검색에 활용되지 않음

**현재 코드 흐름:**
```
사용자 질문 → analyzer (question_summary 추출)
            → pipeline.py:794 (prec_query = question_summary or query[:80])
            → legal_api.py:search_precedent(prec_query) — 그대로 API 전달
            → 법제처 API → 최대 3건 반환
```

### 1.3 Related Documents

- `docs/01-plan/features/search-quality-improvement.plan.md` — 이전 검색 품질 개선
- `docs/01-plan/features/legal-api-integration.plan.md` — 법제처 API 통합
- `app/core/legal_api.py` — 현재 판례 검색 구현
- `app/templates/prompts.py` — Analyzer 시스템 프롬프트

---

## 2. Scope

### 2.1 In Scope

- [ ] Analyzer에서 `precedent_keywords` (판례 검색용 키워드 리스트) 필드 추출
- [ ] 법적 쟁점 키워드 매핑 테이블 (일상어 → 법률 용어)
- [ ] 다중 쿼리 전략 — 키워드 조합별 복수 검색 후 합산·중복 제거
- [ ] 대화 맥락(conversation history) 기반 검색 키워드 보강
- [ ] 기존 `relevant_laws`에서 파생 키워드 활용 (법조문 → 쟁점)
- [ ] 검색 결과 품질 벤치마크 테스트 (before/after)

### 2.2 Out of Scope

- Pinecone RAG 부활 또는 별도 벡터 DB 판례 검색 (현재 법제처 API만 사용)
- 판례 전문 크롤링 및 자체 DB 구축
- 법제처 API 외 다른 판례 검색 API 연동
- 헌재 결정례 검색 개선 (판례 먼저, 추후 확장)

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | Analyzer가 `precedent_keywords` 필드를 추출 (법적 쟁점 키워드 2~5개) | High | Pending |
| FR-02 | 일상어→법률 키워드 매핑 (예: "짤리다"→"해고", "야근"→"연장근로") | High | Pending |
| FR-03 | `relevant_laws`에서 법조문→쟁점 키워드 역매핑 (예: "근기법 제56조"→"연장근로수당") | Medium | Pending |
| FR-04 | 다중 쿼리 검색: 키워드 조합 2~3개로 병렬 검색 후 합산(최대 5건 중복제거) | High | Pending |
| FR-05 | 대화 맥락에서 이전 쟁점 키워드를 후속 질문 판례 검색에 반영 | Medium | Pending |
| FR-06 | `consultation_type`별 기본 판례 검색 키워드 제공 (topic→keyword 매핑) | Medium | Pending |
| FR-07 | 벤치마크 테스트 — 15개 이상 시나리오에서 before/after 판례 적중률 비교 | High | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| Performance | 판례 검색 전체 latency 증가 < 500ms (다중 쿼리 병렬 처리) | 로그 타이밍 비교 |
| Quality | 벤치마크 시나리오 판례 적중률 ≥ 70% (현재 추정 30~40%) | 벤치마크 테스트 |
| Reliability | 키워드 추출 실패 시 기존 로직(question_summary) 폴백 | 에러 로그 모니터링 |
| Token Cost | Analyzer 토큰 사용량 증가 < 20% | API 사용량 비교 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] `precedent_keywords` 필드가 Analyzer tool_use 스키마에 추가됨
- [ ] 다중 쿼리 검색 로직이 `legal_api.py`에 구현됨
- [ ] 일상어→법률 키워드 매핑 테이블이 존재함
- [ ] 기존 pipeline의 판례 검색 호출부가 새 로직을 사용함
- [ ] 폴백 로직이 정상 작동함 (키워드 없을 시 기존 방식)
- [ ] 벤치마크 테스트 15개 이상 시나리오 통과

### 4.2 Quality Criteria

- [ ] 벤치마크 판례 적중률 ≥ 70%
- [ ] 기존 테스트(calculator_batch_test 102건) 영향 없음
- [ ] latency 증가 500ms 이내

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| 법제처 API 쿼리 수 증가로 rate limit 초과 | High | Medium | 다중 쿼리를 2~3개로 제한, 기존 circuit breaker 활용 |
| LLM 키워드 추출 품질이 낮아 오히려 악화 | Medium | Low | 폴백 로직 필수, 벤치마크로 검증 후 배포 |
| Analyzer 토큰 비용 증가 | Low | Medium | 키워드 필드는 간결한 리스트로 제한 (2~5개) |
| 다중 쿼리 병렬 처리 시 API 에러 증가 | Medium | Low | ThreadPoolExecutor 기존 패턴 재사용, 개별 실패 무시 |
| 대화 맥락 반영 시 이전 주제 키워드가 현재 질문에 노이즈 | Medium | Medium | 직전 1턴만 참조, 주제 전환 감지 시 리셋 |

---

## 6. Architecture Considerations

### 6.1 Project Level

이 프로젝트는 FastAPI + Vercel Serverless 구조의 **Dynamic** 레벨이다.

### 6.2 Key Architectural Decisions

| Decision | Options | Selected | Rationale |
|----------|---------|----------|-----------|
| 키워드 추출 방식 | A) LLM 추출 / B) 규칙 기반 / C) 혼합 | C) 혼합 | LLM이 맥락 이해, 규칙 기반이 안정적 폴백 제공 |
| 다중 쿼리 전략 | A) 순차 검색 / B) 병렬 검색 | B) 병렬 | 기존 ThreadPoolExecutor 패턴 활용, latency 최소화 |
| 키워드 매핑 위치 | A) prompts.py / B) 별도 모듈 / C) legal_consultation.py 확장 | B) 별도 모듈 | 관심사 분리, 매핑 테이블 독립 관리 |
| 결과 합산 방식 | A) 단순 합산 / B) 중복제거+재정렬 | B) 중복제거+재정렬 | 같은 판례가 여러 쿼리에서 나올 수 있음 |

### 6.3 변경 대상 파일

```
app/
├── core/
│   ├── legal_api.py          # search_precedent_contextual() 추가
│   ├── pipeline.py           # 판례 검색 호출부 변경 (794줄 부근)
│   └── analyzer.py           # precedent_keywords 스키마 추가
├── models/
│   └── schemas.py            # AnalysisResult에 precedent_keywords 필드
├── templates/
│   └── prompts.py            # ANALYZER_SYSTEM에 키워드 추출 지침 추가
└── core/
    └── precedent_query.py    # [신규] 판례 검색 쿼리 확장 모듈
```

---

## 7. Convention Prerequisites

### 7.1 Existing Project Conventions

- [x] `CLAUDE.md` 코딩 컨벤션 존재
- [x] 법제처 API 패턴 (`legal_api.py`) — circuit breaker, ThreadPoolExecutor
- [x] Analyzer tool_use 스키마 (`analyzer.py`, `prompts.py`)
- [x] 벤치마크 테스트 패턴 (`benchmark_pipeline.py`)

### 7.2 Conventions to Follow

| Category | Rule |
|----------|------|
| **법제처 API 호출** | 기존 circuit breaker, retry, timeout 패턴 준수 |
| **LLM 스키마 변경** | `AnalysisResult` dataclass + Analyzer 프롬프트 동시 수정 |
| **테스트** | `benchmark_pipeline.py` 패턴으로 before/after 비교 |
| **로깅** | `logger.info`로 검색 쿼리·결과 건수 기록 |

### 7.3 Environment Variables

| Variable | Purpose | Scope | To Be Created |
|----------|---------|-------|:-------------:|
| (없음 — 기존 `LAW_API_KEY` 사용) | | | |

---

## 8. Implementation Approach (High-Level)

### Phase 1: Analyzer 키워드 추출 (FR-01, FR-02)

1. `schemas.py`의 `AnalysisResult`에 `precedent_keywords: list[str]` 추가
2. `prompts.py`의 `ANALYZER_SYSTEM`에 키워드 추출 지침 추가:
   - "사용자 질문의 법적 쟁점을 2~5개 법률 키워드로 추출"
   - 예시 제공: "야근비 안 줘요" → `["연장근로수당", "통상임금"]`
3. `analyzer.py`의 tool_use 스키마에 `precedent_keywords` 파라미터 추가

### Phase 2: 쿼리 확장 모듈 (FR-03, FR-06)

1. `app/core/precedent_query.py` 신규 모듈 작성:
   - `expand_precedent_queries(keywords, relevant_laws, consultation_type)` → `list[str]`
   - 일상어→법률 용어 매핑 테이블
   - `relevant_laws`에서 쟁점 키워드 역매핑 (법조문번호 → 쟁점명)
   - `consultation_type`별 기본 키워드 제공

### Phase 3: 다중 쿼리 검색 (FR-04)

1. `legal_api.py`에 `search_precedent_multi(queries, api_key, max_total=5)` 추가:
   - 쿼리 리스트를 병렬로 법제처 API 검색
   - 결과 합산, `판례일련번호` 기준 중복 제거
   - 최대 `max_total`건 반환
2. `pipeline.py` 판례 검색 호출부 변경:
   - `precedent_keywords` 존재 시 → `expand_precedent_queries()` → `search_precedent_multi()`
   - 없으면 → 기존 `question_summary` 폴백

### Phase 4: 대화 맥락 반영 (FR-05)

1. `pipeline.py`에서 이전 턴의 `precedent_keywords`를 세션에 저장
2. 후속 질문 시 이전 키워드를 현재 키워드에 합산 (주제 전환 시 제외)

### Phase 5: 벤치마크 (FR-07)

1. 15개 이상 시나리오 작성 (일상어 질문 → 기대 판례 쟁점)
2. before(현재 로직) / after(새 로직) 판례 적중률 비교
3. latency 비교

---

## 9. Next Steps

1. [ ] Design 문서 작성 (`contextual-precedent-search.design.md`)
2. [ ] 구현 및 벤치마크 테스트
3. [ ] 배포

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-15 | Initial draft | Claude + zealnutkim |
