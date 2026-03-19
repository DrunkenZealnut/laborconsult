# rerank Planning Document

> **Summary**: Cohere Rerank로 Pinecone 벡터 검색 결과 정밀도(precision) 향상
>
> **Project**: laborconsult (노동OK 노동법 Q&A 챗봇)
> **Author**: Claude
> **Date**: 2026-03-16
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 벡터 검색(bi-encoder)은 recall은 좋으나 precision이 부족 — 관련성 낮은 결과가 LLM 컨텍스트에 혼입 |
| **Solution** | Pinecone에서 후보를 넓게 가져온 후 Cohere Rerank(cross-encoder)로 재정렬하여 상위 N건만 사용 |
| **Function/UX Effect** | 더 관련성 높은 판례·행정해석만 LLM에 전달 → 답변 정확도·신뢰도 향상 |
| **Core Value** | multi-query(recall) + rerank(precision)의 조합으로 RAG 검색 품질 양축 완성 |

---

## 1. Overview

### 1.1 Purpose

Pinecone 벡터 검색 결과를 Cohere Rerank API(cross-encoder)로 재정렬하여 검색 정밀도를 향상시킨다.

**Bi-encoder vs Cross-encoder:**
- **Bi-encoder** (현재 Pinecone): 쿼리와 문서를 각각 임베딩 → cosine 유사도. 빠르지만 의미적 정밀도 한계.
- **Cross-encoder** (Rerank): 쿼리-문서 쌍을 함께 분석 → relevance score. 느리지만 정밀도 높음.

### 1.2 Background

multi-query 기능으로 recall을 개선했으나, 여러 쿼리 결과가 병합되면서:
- 각 쿼리별 cosine score가 직접 비교 불가 (다른 임베딩 공간에서 산출)
- 관련성 낮은 결과가 높은 cosine score로 혼입 가능
- LLM 컨텍스트에 노이즈가 섞이면 답변 품질 저하

Rerank는 통일된 기준으로 모든 후보를 재평가하여 이 문제를 해결한다.

### 1.3 Related Documents

- 선행 기능: `docs/archive/2026-03/multi-query/` (multi-query, 97% 완료)
- 수정 대상: `app/core/rag.py`

---

## 2. Scope

### 2.1 In Scope

- [x] `cohere` 패키지 추가 + `COHERE_API_KEY` 환경변수
- [x] `app/core/rag.py`에 rerank 함수 추가
- [x] `search_pinecone_multi()` 후 rerank 단계 통합
- [x] Pinecone 초기 검색 top_k 확대 (5 → 15)
- [x] Rerank 미설정(API 키 없음) 시 기존 동작 유지 (graceful degradation)

### 2.2 Out of Scope

- Pinecone 인덱스 구조 변경
- Cohere Embed (임베딩 교체) — 기존 OpenAI 임베딩 유지
- 법제처 API 폴백 경로의 rerank 적용
- UI 변경

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | Pinecone 검색 후 Cohere Rerank로 결과 재정렬 | High | Pending |
| FR-02 | 초기 검색 top_k를 15로 확대하여 rerank 후보 풀 확보 | High | Pending |
| FR-03 | Rerank 후 상위 5건만 LLM 컨텍스트로 전달 | High | Pending |
| FR-04 | `COHERE_API_KEY` 미설정 시 rerank 건너뛰기 (기존 동작 유지) | High | Pending |
| FR-05 | Rerank 실패(타임아웃, API 에러) 시 cosine score 정렬로 폴백 | High | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| 지연시간 | Rerank 추가 지연 ≤ 500ms | 로그 타이밍 |
| 비용 | ~$0.002/검색 (rerank-v3.5, 15문서) | API 사용량 |
| 정밀도 | 관련성 높은 문서 상위 비율 향상 | 수동 평가 |
| 안정성 | API 키 없거나 실패 시 기존 동작 유지 | 로그 확인 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] `cohere` 패키지 requirements.txt에 추가
- [ ] `rag.py`에 rerank 함수 구현
- [ ] `COHERE_API_KEY` 없을 때 정상 동작 확인
- [ ] Rerank 실패 시 폴백 정상 동작 확인
- [ ] 복합 질문 3건 이상에서 결과 품질 향상 확인

### 4.2 Quality Criteria

- [ ] 기존 테스트 통과 (API 키 없는 환경 포함)
- [ ] 응답 지연 증가 500ms 이내
- [ ] 기존 답변 품질 저하 없음

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Cohere API 장애/지연 | Medium | Low | 타임아웃 3초 + cosine 정렬 폴백 |
| API 키 미설정 환경 (CI/CD, 신규 개발자) | Medium | Medium | 키 없으면 rerank 건너뛰기, 기존 동작 100% 유지 |
| 비용 증가 | Low | Low | rerank-v3.5 기준 1,000검색당 ~$2, 일 1,000건 시 $2/일 |
| 한국어 rerank 품질 | Medium | Low | Cohere rerank-v3.5는 다국어 지원, 한국어 포함 |

---

## 6. Architecture Considerations

### 6.1 데이터 흐름 (변경 후)

```
사용자 질문
    │
    ├─ decompose_query() → 2~4개 쿼리 (multi-query)
    ├─ build_precedent_queries() → 규칙 기반 쿼리
    └─ _merge_search_queries() → 병합
            │
            ▼
    search_pinecone_multi(top_k=15)  ← 확대 (기존 5)
            │
            ▼ 최대 30건 후보 (15 × 2)
            │
    rerank_results(query, hits)  ← 신규
            │ Cohere rerank-v3.5
            ▼
    상위 5건 (relevance_score 정렬)
            │
            ▼
    format_pinecone_hits() → LLM 컨텍스트
```

### 6.2 Key Architectural Decisions

| Decision | Options | Selected | Rationale |
|----------|---------|----------|-----------|
| Rerank 모델 | rerank-v3.5 / rerank-english-v3.0 | rerank-v3.5 | 다국어(한국어) 지원, 최신 모델 |
| Rerank 위치 | rag.py 내부 / pipeline.py | rag.py 내부 | 검색 모듈의 책임, pipeline 변경 최소화 |
| 초기 top_k | 10 / 15 / 20 | 15 | 후보 다양성과 비용의 균형 |
| Rerank top_n | 3 / 5 / 10 | 5 | 기존 LLM 컨텍스트 크기 유지 |
| API 키 없을 때 | 에러 / 건너뛰기 | 건너뛰기 | 기존 동작 100% 보장 |

### 6.3 수정 파일

```
app/core/rag.py           ← 주 수정: rerank 함수 추가, top_k 조정
app/config.py             ← 수정: cohere_client 추가
requirements.txt          ← 수정: cohere 패키지 추가
.env.example              ← 수정: COHERE_API_KEY 추가
```

---

## 7. Convention Prerequisites

### 7.1 Existing Project Conventions

- [x] 에러 처리: try/except + logger.warning + 폴백 (rag.py 기존 패턴)
- [x] 선택적 기능: API 키 없으면 건너뛰기 (법제처 API와 동일 패턴)
- [x] 로깅: `logging.getLogger(__name__)` 패턴

### 7.2 Environment Variables

| Variable | Purpose | Required |
|----------|---------|:--------:|
| `COHERE_API_KEY` | Rerank API 호출 | 선택 |

---

## 8. Next Steps

1. [ ] Design 문서 작성 (`rerank.design.md`)
2. [ ] `cohere` 패키지 추가, `AppConfig`에 client 추가
3. [ ] `rag.py`에 rerank 함수 구현
4. [ ] 수동 테스트 + 품질 비교

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-16 | Initial draft | Claude |
