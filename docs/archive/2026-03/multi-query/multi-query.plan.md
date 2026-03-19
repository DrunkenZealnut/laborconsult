# multi-query Planning Document

> **Summary**: LLM 기반 쿼리 분해로 Pinecone RAG 검색 품질 향상
>
> **Project**: laborconsult (노동OK 노동법 Q&A 챗봇)
> **Author**: Claude
> **Date**: 2026-03-16
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 사용자 질문을 단일 임베딩으로 검색하면 복합 질문·모호한 표현에서 관련 문서를 놓침 |
| **Solution** | LLM이 사용자 질문을 2~4개 관점별 쿼리로 분해 → 병렬 벡터 검색 → 중복 제거 병합 |
| **Function/UX Effect** | 검색 재현율(recall) 향상으로 더 풍부하고 정확한 답변 제공, 특히 복합 질문에서 누락 감소 |
| **Core Value** | 기존 `search_pinecone_multi` 인프라 활용으로 최소 비용의 검색 품질 개선 |

---

## 1. Overview

### 1.1 Purpose

사용자의 복합적·모호한 노동법 질문을 LLM이 여러 검색 관점으로 분해하여, Pinecone 벡터 검색의 recall을 향상시킨다.

**예시:**
- 입력: "5년 근무 후 정리해고 당하면 퇴직금이랑 실업급여 얼마나 받을 수 있나요?"
- 분해 쿼리:
  1. "정리해고 요건 근로기준법 제24조"
  2. "퇴직금 산정 방법 5년 근속"
  3. "실업급여 수급 요건 구직급여 금액"

### 1.2 Background

현재 RAG 검색 흐름:
1. `pipeline.py` → `build_precedent_queries()` (규칙 기반 키워드 조합) → `search_pinecone_multi()`
2. 폴백: `question_summary` 또는 `query[:80]` 단일 쿼리

**한계점:**
- `build_precedent_queries()`는 `precedent_keywords` + `relevant_laws` 역매핑 기반으로, LLM이 추출하지 못한 관점은 누락
- 단일 임베딩은 복합 질문의 모든 측면을 포착하지 못함
- 규칙 기반 확장은 노동법 도메인 어휘의 다양한 표현(동의어, 구어체)을 커버하지 못함

### 1.3 Related Documents

- 기존 구현: `app/core/rag.py` (search_pinecone_multi), `app/core/precedent_query.py`
- 참고: `docs/01-plan/features/search-quality-improvement.plan.md` (이전 검색 품질 개선)

---

## 2. Scope

### 2.1 In Scope

- [x] LLM 기반 쿼리 분해 모듈 (`app/core/query_decomposer.py`)
- [x] `pipeline.py` 통합 — 법률상담 경로에서 multi-query 적용
- [x] 기존 `search_pinecone_multi()` 재활용 (새 검색 인프라 불필요)
- [x] 비용/지연 제어 — 저비용 모델(Haiku) 사용, 캐싱 고려

### 2.2 Out of Scope

- Pinecone 인덱스 구조 변경 (현행 유지)
- 임금계산 경로의 쿼리 분해 (계산기 경로는 이미 구조화된 입력 사용)
- HyDE(Hypothetical Document Embedding) 등 고급 검색 기법
- 사용자 대면 UI 변경

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | 사용자 질문을 2~4개 관점별 검색 쿼리로 분해 | High | Pending |
| FR-02 | 분해된 쿼리를 `search_pinecone_multi()`에 전달하여 병렬 검색 | High | Pending |
| FR-03 | 기존 `build_precedent_queries()` 결과와 LLM 분해 결과를 병합 | Medium | Pending |
| FR-04 | 단순 질문(키워드 1~2개)은 분해 건너뛰기 (불필요한 API 호출 방지) | Medium | Pending |
| FR-05 | 분해 실패 시 원본 쿼리로 폴백 | High | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| 지연시간 | 쿼리 분해 ≤ 500ms (Haiku 기준) | 로그 타이밍 |
| 비용 | 호출당 입력 ~200토큰 + 출력 ~100토큰 (Haiku $0.0025 이하) | API 사용량 모니터링 |
| 검색품질 | 복합 질문에서 recall ≥ 20% 향상 (벤치마크 대비) | benchmark 스크립트 비교 |
| 안정성 | 분해 실패율 < 1%, 폴백 정상 작동 | 로그 모니터링 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] `query_decomposer.py` 모듈 구현 완료
- [ ] `pipeline.py`에서 법률상담 경로 통합 완료
- [ ] 복합 질문 5건 이상에서 recall 향상 확인
- [ ] 폴백 경로 정상 동작 확인
- [ ] 기존 E2E 테스트(`test_e2e.py`) 통과

### 4.2 Quality Criteria

- [ ] 응답 지연 증가 500ms 이내
- [ ] 단순 질문에서 불필요한 분해 미발생
- [ ] 기존 답변 품질 저하 없음

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| LLM 호출 지연으로 전체 응답 느려짐 | Medium | Medium | Haiku 사용 + 500ms 타임아웃 + 비동기 처리 |
| 분해 쿼리가 원본보다 품질 낮음 | Medium | Low | 원본 쿼리 항상 포함 + 결과 score 기반 정렬 |
| API 비용 증가 | Low | Low | Haiku 사용 시 호출당 $0.002 미만, 일 1000건 기준 $2 |
| 분해 결과 파싱 실패 | Low | Medium | JSON 파싱 + 폴백으로 원본 쿼리 사용 |

---

## 6. Architecture Considerations

### 6.1 Project Level

Python FastAPI 기반 서버리스 (Vercel). 기존 아키텍처 유지, 모듈 추가만.

### 6.2 Key Architectural Decisions

| Decision | Options | Selected | Rationale |
|----------|---------|----------|-----------|
| 분해 모델 | Claude Haiku / GPT-4o-mini / 규칙 기반 | Claude Haiku | 이미 Anthropic SDK 사용 중, 저비용, 한국어 품질 |
| 분해 위치 | pipeline.py 내 인라인 / 별도 모듈 | 별도 모듈 | 테스트·재사용성·관심사 분리 |
| 기존 확장과의 관계 | 대체 / 병합 | 병합 | `build_precedent_queries()` 결과 + LLM 분해 결과 합산 |
| 쿼리 수 제한 | 2~4개 / 무제한 | 2~4개 (max 4) | 비용·지연 제어, Pinecone 호출 수 제한 |

### 6.3 모듈 구조

```
app/core/
├── query_decomposer.py   ← 신규: LLM 쿼리 분해
├── rag.py                  (기존: search_pinecone_multi 재활용)
├── precedent_query.py      (기존: 규칙 기반 확장, 유지)
└── pipeline.py             (수정: 분해 쿼리 통합)
```

### 6.4 데이터 흐름

```
사용자 질문
    │
    ├─→ analyze_intent() → analysis (기존)
    │
    ├─→ query_decomposer.decompose_query()  ← 신규
    │       │
    │       └─→ Claude Haiku: "이 질문을 2~4개 검색 쿼리로 분해하세요"
    │              → ["쿼리1", "쿼리2", "쿼리3"]
    │
    ├─→ build_precedent_queries() (기존 규칙 기반)
    │       → ["규칙쿼리1", "규칙쿼리2"]
    │
    └─→ 병합 + 중복 제거 → search_pinecone_multi()
            → 검색 결과 (score 정렬, 중복 제거)
```

---

## 7. Convention Prerequisites

### 7.1 Existing Project Conventions

- [x] `CLAUDE.md` — 프로젝트 구조·명명 규칙 정의됨
- [x] 한국어 변수명 사용 (`facade/conversion.py`)
- [x] 로깅: `logging.getLogger(__name__)` 패턴
- [x] 에러 처리: try/except + logger.warning + 폴백

### 7.2 Environment Variables

| Variable | Purpose | Status |
|----------|---------|--------|
| `ANTHROPIC_API_KEY` | Claude Haiku 호출 | 기존 사용 중 |

신규 환경변수 불필요.

---

## 8. Next Steps

1. [ ] Design 문서 작성 (`multi-query.design.md`)
2. [ ] `query_decomposer.py` 구현
3. [ ] `pipeline.py` 통합
4. [ ] 벤치마크 비교 테스트

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-16 | Initial draft | Claude |
