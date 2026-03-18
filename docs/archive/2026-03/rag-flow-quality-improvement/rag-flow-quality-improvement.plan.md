# RAG Flow 품질 향상 Plan

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | RAG Flow 품질 향상 |
| 시작일 | 2026-03-18 |
| 예상 기간 | 4일 |
| Level | Dynamic |

### Value Delivered

| 관점 | 내용 |
|------|------|
| **Problem** | Contextual Retrieval 적용 완료 상태이나, Dense-only 검색으로 정확한 법조문 번호/용어 검색 시 누락 발생. 질문 복잡도와 무관한 정적 검색 전략. 검색 결과의 관련성 사전 검증 부재 |
| **Solution** | SafeFactory 참조 아키텍처 기반으로 Hybrid Search (BM25+Dense), Adaptive Retrieval, Self-RAG 검증 3단계를 추가하여 검색 정밀도와 재현율을 동시에 향상 |
| **Function UX Effect** | 답변의 법적 근거가 더 정확하고 풍부해지며, 환각 판례 인용이 감소하고, 복잡한 복합 질문에 대한 응답 품질이 크게 개선됨 |
| **Core Value** | 노동법 상담 신뢰도 향상 — 정확한 판례·법조문 인용으로 법률 전문가 수준의 답변 품질 달성 |

---

## 1. 현황 분석

### 1.1 현재 RAG 파이프라인 구조

```
사용자 질문
  ↓
[1] Intent Analysis (Claude tool_use)
  → 질문 유형, 관련 법률, 키워드 추출
  ↓
[2] Query Decomposition (Claude Haiku)
  → 복합 질문 → 2~4개 관점별 검색 쿼리 분해
  ↓
[3] Multi-Query Merge
  → LLM 분해 + 규칙 기반 쿼리 병합 (최대 5개)
  ↓
[4] Pinecone Vector Search (2그룹 병렬)
  → 그룹 A: laborlaw-v2 (판례·행정해석·훈령)
  → 그룹 B: counsel + qa (상담사례)
  → OpenAI text-embedding-3-small (1536 dim)
  ↓
[5] Cohere Rerank (rerank-v3.5)
  → top 15 → top 5 재정렬
  ↓
[6] GraphRAG (NetworkX BFS 2-hop)
  → 법조문-개념-판례 관계 그래프 순회
  ↓
[7] Legal API Fallback
  → Pinecone 결과 부족 시 법제처 API 폴백
  → NLRC 중앙노동위 판정사례 검색
  ↓
[8] Context Assembly + LLM Streaming
  → Claude → OpenAI → Gemini 폴백 체인
  ↓
[9] Citation Validation
  → 환각 판례 감지 + 교정 (replace 이벤트)
```

### 1.2 이미 적용된 기법

| 기법 | 구현 상태 | 파일 |
|------|----------|------|
| **Contextual Retrieval** | ✅ 완료 | `pinecone_upload_contextual.py` — Claude Haiku로 각 청크에 문서 맥락 prefix 생성 후 임베딩 |
| **Multi-Query Decomposition** | ✅ 완료 | `query_decomposer.py` — 복합 질문 → 2~4개 쿼리 분해 |
| **Cohere Rerank** | ✅ 완료 | `rag.py` — rerank-v3.5로 top 15 → top 5 재정렬 |
| **GraphRAG** | ✅ 완료 | `graph.py` — NetworkX BFS 2-hop 법령 관계 그래프 |
| **Citation Validation** | ✅ 완료 | `citation_validator.py` — 환각 판례 감지 + LLM 교정 |

### 1.3 남은 문제점

| # | 문제 | 영향 | 심각도 |
|---|------|------|--------|
| P1 | **Dense-only 검색**: BM25 등 키워드 매칭 없이 임베딩 유사도만 사용 | 정확한 법조문 번호/용어 검색 시 누락 ("근로기준법 제60조" 등 exact match 약함) | High |
| P2 | **정적 top_k**: 질문 복잡도와 무관하게 동일한 검색량 (top_k=5~15) | 단순 질문에 과도한 검색, 복잡 질문에 부족한 검색 | Medium |
| P3 | **검색 결과 신뢰도 검증 없음**: 검색 결과의 질문 관련성을 LLM이 사전 판단하지 않음 | 무관한 문서가 컨텍스트에 포함되어 답변 품질 저하 | Medium |
| P4 | **GraphRAG 불안정**: graph_data.json 미존재 시 완전 비활성화, 노드 커버리지 제한적 | 법률 관계 정보 보강 불완전 | Low |

### 1.4 SafeFactory 참조 아키텍처에서 차용할 패턴

1. **Hybrid Search**: Dense + Sparse(BM25) 결합으로 키워드 매칭과 의미 검색 동시 수행
2. **질문 분류 고도화**: 질문 복잡도 기반 검색 전략 분기 (단순/복합/멀티홉)
3. **Multi-stage Ranking**: 초벌 검색 → Cohere 재정렬(✅) → LLM 관련성 판정
4. **Self-RAG / Faithfulness Check**: 검색 결과의 관련성·충분성을 LLM이 사전 판단

---

## 2. 개선 계획

### Phase 1: Hybrid Search (BM25 + Dense) — 우선순위 1

**목표**: 키워드 매칭(BM25)과 의미 검색(Dense)을 결합하여 recall 향상

**현재**: OpenAI 임베딩 기반 Dense search만 사용
**개선**: Pinecone Sparse-Dense Hybrid Search 또는 로컬 BM25 + Dense fusion

**구현 옵션 비교**:

| 옵션 | 장점 | 단점 | 선택 |
|------|------|------|------|
| A. Pinecone Hybrid (sparse_values) | 단일 API, 관리 용이 | Pinecone Serverless에서 sparse 지원 제한 | - |
| B. 로컬 BM25 + Dense fusion | 완전 통제 가능, 무료 | 메모리 사용, BM25 인덱스 관리 | **추천** |
| C. Elasticsearch + Pinecone | 강력한 BM25 | 인프라 복잡도 증가 | - |

**구현 계획 (옵션 B)**:
- `app/core/bm25_search.py` 신규: rank_bm25 기반 로컬 키워드 검색
- Pinecone 메타데이터에서 text 추출하여 BM25 코퍼스 구축 (서버 시작 시 1회)
- Reciprocal Rank Fusion (RRF)으로 Dense + BM25 결과 병합
- Vercel serverless 환경 고려: BM25 인덱스를 JSON으로 직렬화하여 cold start 시 로드

**예상 효과**: 법조문 번호, 정확한 법률 용어 검색 시 recall 20-30% 향상

### Phase 2: Adaptive Retrieval (질문 복잡도 기반 전략 분기) — 우선순위 2

**목표**: 질문 복잡도에 따라 검색 전략을 동적으로 조정

**현재**: 모든 질문에 동일한 검색 파이프라인 적용
**개선**: 3단계 복잡도 분류에 따른 전략 분기

```python
class QueryComplexity(Enum):
    SIMPLE = "simple"       # "최저시급이 얼마인가요?" → top_k=3, no decomposition
    MODERATE = "moderate"   # "퇴직금 계산 방법" → top_k=5, 1-2 decomposed queries
    COMPLEX = "complex"     # "5인 미만 사업장에서 1년 2개월 근무 후 해고 시..." → top_k=10, 3-4 queries, GraphRAG
```

**구현 범위**:
- `app/core/query_decomposer.py`: 기존 `_should_decompose()` 확장 → 복잡도 등급 반환
- `app/core/pipeline.py`: 복잡도별 `search_top_k`, `max_queries`, `graph_hops` 동적 조정
- Intent analysis 결과에서 복잡도 추정 (질문 길이, 키워드 수, 법률 참조 수)

**예상 효과**: 단순 질문 응답 속도 30% 향상, 복잡 질문 답변 품질 20% 향상

### Phase 3: Self-RAG 검증 (검색 결과 관련성 판정) — 우선순위 2

**목표**: 검색된 문서의 질문 관련성을 LLM이 사전 판정하여 무관한 문서를 필터링

**현재**: Cohere rerank score 기반 정렬만 수행, 관련성 0.5 미만도 포함될 수 있음
**개선**: Rerank 후 LLM(Haiku)으로 각 문서의 관련성을 binary 판정

```python
# Self-RAG 관련성 판정
for hit in reranked_hits:
    relevance = llm_judge_relevance(query, hit["content"])  # "relevant" / "irrelevant"
    if relevance == "relevant":
        filtered_hits.append(hit)
```

**구현 범위**:
- `app/core/rag.py`: `filter_by_relevance()` 함수 추가
- Claude Haiku 사용 (저비용, 빠른 응답)
- 병렬 판정으로 지연 최소화 (ThreadPoolExecutor)
- 판정 결과 캐싱 (query+doc_id 기반, 세션 내)

**주의사항**:
- 비용: Haiku 호출 추가 (hit당 ~100 토큰, 5건 기준 ~500 토큰)
- 지연: 500ms 추가 예상 → timeout 3초 설정, 타임아웃 시 기존 rerank 결과 사용

**예상 효과**: 무관한 문서 컨텍스트 유입 70% 감소, 답변 정확도 향상

---

## 3. 구현 우선순위 및 일정

| Phase | 항목 | 우선순위 | 예상 소요 | 의존성 |
|-------|------|----------|-----------|--------|
| 1 | Hybrid Search (BM25+Dense) | P1 | 1.5일 | 없음 |
| 2 | Adaptive Retrieval | P2 | 1일 | Phase 1과 병렬 가능 |
| 3 | Self-RAG 검증 | P2 | 1일 | Phase 1 완료 후 |
| - | 통합 테스트 + 벤치마크 | - | 0.5일 | 전체 완료 후 |

### 3.1 성공 기준

| 지표 | 현재 추정 | 목표 | 측정 방법 |
|------|----------|------|-----------|
| 검색 정밀도 (Precision@5) | ~65% | ≥80% | 벤치마크 질문 30개 기준 |
| 환각 판례 발생률 | ~15% | ≤5% | citation_validator 로그 분석 |
| 응답 지연 (P95) | ~8초 | ≤10초 | API 응답 시간 모니터링 |
| 답변 품질 (인간 평가) | - | 기존 대비 20%↑ | 5점 척도 블라인드 평가 |

### 3.2 리스크

| 리스크 | 영향 | 대응 |
|--------|------|------|
| BM25 인덱스 메모리 과다 (Vercel 제한) | 배포 실패 | JSON 직렬화 + 지연 로딩, 256MB 이내 유지 |
| Self-RAG LLM 비용 증가 | 운영비 증가 | Haiku 사용, 캐싱, 복잡 질문에만 적용 |
| BM25+Dense fusion 가중치 튜닝 | 검색 품질 불안정 | 벤치마크 30개 질문으로 최적 alpha 값 탐색 |

---

## 4. 제외 사항 (YAGNI)

- **Fine-tuned embedding model**: 현재 데이터 규모(~10K 문서)에서는 범용 모델로 충분
- **Vector DB 교체 (Weaviate, Qdrant 등)**: Pinecone Serverless 현재 성능 충분
- **Cross-encoder reranking 모델 자체 호스팅**: Cohere API로 충분, 인프라 복잡도 방지
- **실시간 사용자 피드백 루프**: 현재 사용자 규모에서는 과도

---

## 5. 참조

- SafeFactory RAG Pipeline 아키텍처 (`/Users/zealnutkim/Downloads/safefactory-rag-pipeline.png`)
- [Anthropic Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval) — 청크 품질 향상 기법
- 현재 파이프라인: `app/core/pipeline.py`, `app/core/rag.py`, `app/core/query_decomposer.py`, `app/core/graph.py`
- 현재 벤치마크: `benchmark_pipeline.py`, `search_quality_test.py`
