# Plan: GraphRAG 구축 — 노동법 지식 그래프 기반 검색 강화

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | graphrag |
| 작성일 | 2026-03-17 |
| 예상 기간 | 5~7일 |
| 난이도 | High |

### Value Delivered

| 관점 | 내용 |
|------|------|
| **Problem** | 현재 벡터 검색은 단일 홉(cosine similarity)에 의존하여 "근로기준법 제56조에 따른 연장수당인데 고용보험법상 실업급여와의 관계는?"과 같은 법령 간 교차 질문이나, 특정 법조문에 관련된 판례를 구조적으로 찾을 수 없음 |
| **Solution** | NetworkX 기반 in-memory 지식 그래프를 구축하여 법률→조문→판례→개념 간 관계를 명시적 엣지로 연결하고, 기존 Pinecone 벡터 검색에 그래프 순회 결과를 결합하는 하이브리드 검색 |
| **Function UX Effect** | 복합 법률 질문에 대해 관련 법령 체계, 적용 판례, 상위/하위법 관계를 구조적으로 제시하여 "왜 이 법이 적용되는지"까지 설명 가능 |
| **Core Value** | 단순 키워드 매칭을 넘어 노동법 전문가 수준의 법령 체계 이해와 판례 연결 추론을 제공하여 상담 정확도와 신뢰도를 획기적으로 향상 |

---

## 1. 배경 및 현재 상태

### 1.1 현재 RAG 파이프라인

```
사용자 질문 → analyze_intent() → query_decomposer (LLM 분해)
                                    ↓
                              Pinecone 벡터 검색 (2그룹 병렬)
                              ├── laborlaw-v2 namespace
                              └── counsel + qa namespace
                                    ↓
                              Cohere Rerank v3.5
                                    ↓
                              Legal API (법제처 + 판례)
                                    ↓
                              컨텍스트 조립 → LLM 스트리밍 답변
```

### 1.2 현재 한계

| 한계 | 구체적 문제 | 영향 |
|------|------------|------|
| **단일 홉 검색** | "퇴직금 관련 판례"를 검색하면 cosine 유사도 기반으로만 결과 반환. 근로기준법 제34조 → 관련 판례 → 해당 판례가 인용한 다른 조문의 연쇄 탐색 불가 | 복합 질문 답변 품질 저하 |
| **법령 간 관계 부재** | 근로기준법 ↔ 고용보험법 ↔ 산재보험법 간 참조/위임/특례 관계가 암묵적. "실업급여 받으면서 퇴직금도 받을 수 있나요?" 같은 교차 법령 질문에 한쪽만 검색 | 교차 법령 질문 누락 |
| **판례-법조문 연결 미흡** | `precedent_keywords`로 키워드 검색만 수행. 법조문 → 해석 판례 → 변경 판례의 구조적 관계 없음 | 판례 검색 정밀도 부족 |
| **시간축 부재** | 법 개정 이력, 판례 변경(변경판결) 관계가 없어 "현행법 기준" 판단이 LLM 지식에 의존 | 시의성 리스크 |

### 1.3 목표

**기존 벡터 검색을 대체하지 않고, 그래프 순회 결과를 결합하는 하이브리드 방식**:

```
사용자 질문 → analyze_intent()
                 ↓
         ┌───────────────────┐
         │  기존 벡터 검색    │  ← Pinecone + Cohere (유지)
         │  (의미적 유사도)   │
         └───────┬───────────┘
                 │
         ┌───────────────────┐
         │  GraphRAG 검색    │  ← NEW: NetworkX 그래프 순회
         │  (관계 기반 추론)  │
         └───────┬───────────┘
                 │
         ┌───────────────────┐
         │  결과 통합 + 재순위 │  ← 벡터 스코어 + 그래프 관련도 결합
         └───────┬───────────┘
                 ↓
         강화된 컨텍스트 → LLM 답변
```

---

## 2. 지식 그래프 설계

### 2.1 노드 타입

| 노드 타입 | 설명 | 예시 | 소스 |
|-----------|------|------|------|
| `Statute` | 법률 | 근로기준법, 고용보험법 | Legal API (18개 주요 법률) |
| `Article` | 법조문 | 근로기준법 제56조 | Legal API 조문 조회 |
| `Precedent` | 판례 | 대법원 2023다302838 | Pinecone 메타데이터 + Legal API |
| `Concept` | 법적 개념 | 통상임금, 평균임금, 부당해고 | 의도 분석 추출 + 수동 매핑 |
| `Topic` | 상담 주제 | 해고·징계, 임금·통상임금 | consultation_topic enum |
| `Calculator` | 계산기 타입 | overtime, severance | CALC_TYPES |

### 2.2 엣지 타입

| 엣지 타입 | From → To | 설명 | 예시 |
|-----------|-----------|------|------|
| `CONTAINS` | Statute → Article | 법률이 조문을 포함 | 근로기준법 → 제56조 |
| `CITES` | Article → Article | 조문이 다른 조문을 참조 | 제56조 → 제50조(근로시간) |
| `DELEGATES` | Article → Statute | 시행령/시행규칙으로 위임 | 제56조 → 근로기준법 시행령 |
| `INTERPRETS` | Precedent → Article | 판례가 법조문을 해석 | 2023다302838 → 통상임금 |
| `OVERRULES` | Precedent → Precedent | 판례 변경 | 전원합의체 → 기존 판례 |
| `APPLIES_TO` | Article → Concept | 조문이 개념에 적용 | 제56조 → 연장근로수당 |
| `RELATED_TO` | Concept → Concept | 개념 간 관련성 | 통상임금 → 평균임금 |
| `TOPIC_HAS` | Topic → Concept | 주제가 개념을 포함 | 임금·통상임금 → 통상임금 |
| `CALC_FOR` | Calculator → Concept | 계산기가 개념을 계산 | overtime → 연장근로수당 |

### 2.3 그래프 규모 추정

| 항목 | 추정 수량 |
|------|----------|
| Statute 노드 | ~20 (주요 노동법) |
| Article 노드 | ~500 (핵심 조문) |
| Precedent 노드 | ~300 (Pinecone 메타데이터 + Legal API) |
| Concept 노드 | ~100 (법적 개념) |
| Topic 노드 | ~12 (consultation_topic enum) |
| Calculator 노드 | ~25 (CALC_TYPES) |
| **총 노드** | **~960** |
| **총 엣지** | **~3,000~5,000** |

→ NetworkX에서 충분히 처리 가능한 규모 (메모리 < 10MB, 순회 < 50ms)

---

## 3. 그래프 구축 파이프라인

### 3.1 데이터 소스별 추출

| 소스 | 추출 방법 | 생성 노드/엣지 |
|------|-----------|---------------|
| **Legal API (법제처)** | 18개 법률의 조문 목록 API 조회 → 조문 텍스트에서 참조 조문 정규식 추출 | Statute, Article, CONTAINS, CITES |
| **Pinecone 메타데이터** | 기존 벡터의 metadata에서 법조문/판례번호 추출 | Precedent, INTERPRETS |
| **analyze_qna.py 결과** | JSONL 분석 데이터에서 법적 개념, 관련 법률 추출 | Concept, APPLIES_TO |
| **수동 매핑** | consultation_topic → 관련 법률/개념 매핑 테이블 | Topic, TOPIC_HAS |
| **CALC_TYPE_MAP** | 기존 registry.py의 계산기-개념 매핑 | Calculator, CALC_FOR |
| **판례 상호 참조** | 판례 텍스트에서 다른 판례 번호 정규식 추출 | OVERRULES, CITES |

### 3.2 구축 스크립트

```
build_graph.py
├── 법률/조문 그래프 구축 (Legal API 조회)
├── 판례-법조문 연결 (Pinecone 메타데이터 + 정규식)
├── 개념 노드 생성 (analysis_qna.jsonl + 수동 매핑)
├── 주제/계산기 노드 연결
├── 그래프 직렬화 (JSON → graph_data.json)
└── 통계 출력
```

### 3.3 직렬화 및 로드

- **빌드 시**: `build_graph.py` → `data/graph_data.json` (node-link format)
- **런타임**: `app/core/graph.py`에서 앱 시작 시 JSON 로드 → NetworkX 그래프 복원
- **Vercel**: cold start 시 JSON 파싱 (~100ms for <10MB)
- **업데이트**: Legal API 데이터 변경 시 `build_graph.py` 재실행 → JSON 커밋

---

## 4. GraphRAG 검색 엔진

### 4.1 그래프 검색 흐름

```
1. analyze_intent() 결과에서 엔티티 추출
   ├── relevant_laws → Article 노드 매칭
   ├── precedent_keywords → Concept 노드 매칭
   └── consultation_topic → Topic 노드 매칭

2. 시드 노드에서 멀티홉 순회 (최대 2~3홉)
   ├── 1홉: 직접 연결된 노드 (법조문→판례, 법률→조문)
   ├── 2홉: 간접 연결 (법조문→판례→관련 법조문)
   └── 3홉: 확장 탐색 (필요 시, 교차 법령)

3. 그래프 결과를 텍스트 컨텍스트로 변환
   ├── 관련 법조문 요약
   ├── 관련 판례 목록 (그래프 경로 설명 포함)
   └── 법령 간 관계 설명 ("제56조는 제50조의 근로시간 규정에 기반합니다")
```

### 4.2 하이브리드 스코어링

```
최종 스코어 = α × cosine_score + β × graph_relevance + γ × rerank_score

α = 0.4 (벡터 유사도)
β = 0.3 (그래프 관련도: 시드 노드로부터의 거리 역수)
γ = 0.3 (Cohere rerank)
```

그래프 관련도 = `1 / (1 + shortest_path_length)` (시드 노드에서 가까울수록 높음)

### 4.3 컨텍스트 강화

기존 파이프라인의 `parts` 리스트에 그래프 기반 컨텍스트를 추가:

```python
# 기존 parts (벡터 검색 결과, 법률 API 결과, 계산 결과 등)
parts = [...]

# GraphRAG 강화
if graph_context:
    parts.insert(1, "=== 법령 관계 분석 ===\n" + graph_context)
```

---

## 5. 변경 대상 파일

| 파일 | 상태 | 변경 내용 |
|------|------|-----------|
| `build_graph.py` | **NEW** | 그래프 구축 스크립트 (Legal API + Pinecone + 매핑) |
| `data/graph_data.json` | **NEW** | 직렬화된 그래프 데이터 |
| `app/core/graph.py` | **NEW** | GraphRAG 검색 엔진 (로드, 순회, 스코어링) |
| `app/core/pipeline.py` | MODIFY | 그래프 검색 통합 (process_question 내) |
| `app/core/rag.py` | MODIFY | 하이브리드 스코어링 결합 |
| `requirements.txt` | MODIFY | `networkx` 추가 |

---

## 6. 구현 순서

```
Phase 1: 그래프 스키마 + 핵심 구축 (2일)
├── NetworkX 그래프 모델 정의 (노드/엣지 타입, 속성)
├── Legal API에서 법률/조문 그래프 자동 구축
├── 조문 간 참조 관계 정규식 추출 (CITES)
├── 개념/주제/계산기 노드 수동 매핑 테이블
└── JSON 직렬화/역직렬화

Phase 2: 판례-법조문 연결 (1일)
├── Pinecone 메타데이터에서 판례번호 추출
├── 판례 → 해석 법조문 연결 (INTERPRETS)
├── 판례 간 상호 참조 추출 (OVERRULES)
└── 그래프 통계 및 검증

Phase 3: 검색 엔진 구현 (1.5일)
├── 시드 노드 매칭 (analyze_intent 결과 → 그래프 노드)
├── 멀티홉 순회 (BFS/DFS, 깊이 제한)
├── 그래프 관련도 스코어링
└── 컨텍스트 텍스트 생성

Phase 4: 파이프라인 통합 (1일)
├── pipeline.py에 그래프 검색 호출 추가
├── 하이브리드 스코어링 (벡터 + 그래프 + rerank)
├── 컨텍스트 조립에 그래프 결과 삽입
└── 시스템 프롬프트에 관계 설명 활용 안내

Phase 5: 테스트 및 최적화 (0.5~1일)
├── 단일법 질문 vs 교차법 질문 비교 테스트
├── 그래프 로드 시간 측정 (Vercel cold start)
├── 멀티홉 깊이별 품질/성능 트레이드오프
└── 엣지 케이스 (그래프에 없는 법률, 미매칭 노드)
```

---

## 7. 비기능 요구사항

### 7.1 성능
- 그래프 JSON 로드: < 200ms (Vercel cold start)
- 그래프 순회 (2홉): < 50ms
- 총 검색 시간 증가: < 300ms (기존 대비)
- 그래프 데이터 크기: < 10MB (JSON)

### 7.2 안정성
- 그래프 로드 실패 시 기존 벡터 검색만으로 fallback
- 매칭되는 시드 노드가 없으면 그래프 검색 스킵
- Vercel serverless 환경에서 global 변수로 그래프 캐시 (cold start 최소화)

### 7.3 확장성
- 그래프 노드/엣지 추가가 JSON 파일 수정만으로 가능
- 새로운 법률 추가 시 `build_graph.py` 재실행으로 자동 반영
- 추후 Neo4j 등 전용 DB 전환이 가능한 추상화 레이어

---

## 8. 리스크 및 완화

| 리스크 | 영향 | 완화 방안 |
|--------|------|-----------|
| Legal API 조문 조회 대량 호출 (구축 시) | Medium | 구축은 오프라인, 캐시 활용, 속도 제한 준수 |
| 조문 간 참조 정규식 추출 정밀도 | High | "제N조", "동법 제N조", "같은 법" 등 다양한 패턴 커버 + 수동 보정 |
| Vercel cold start 시 JSON 로드 지연 | Medium | 그래프 크기 10MB 이하 유지, lazy loading, global 캐시 |
| 그래프에 없는 엔티티 질문 | Low | graceful fallback (기존 벡터 검색만 사용) |
| 판례 간 OVERRULES 관계 자동 추출 어려움 | High | 초기에는 주요 전원합의체 판결만 수동 매핑, 점진적 확대 |

---

## 9. 성공 지표

| 지표 | 현재 | 목표 |
|------|------|------|
| 교차 법령 질문 관련 법률 포함률 | ~50% (키워드 의존) | ≥ 85% |
| 판례-법조문 연결 정확도 | 0% (구조적 연결 없음) | ≥ 80% |
| 그래프 노드 커버리지 (주요 노동법) | 0 | ≥ 18개 법률, 500+ 조문 |
| 그래프 로드 + 순회 총 시간 | N/A | < 300ms |
| 기존 단일법 질문 품질 유지 | 기준 | 동등 이상 |

---

## 10. 제외 범위 (YAGNI)

- Neo4j 등 외부 그래프 DB (현 규모에서는 NetworkX로 충분)
- 자동 그래프 학습 / GNN (수동 + 규칙 기반으로 시작)
- 법률 개정 이력 자동 추적 (별도 feature로)
- 그래프 시각화 UI (관리자용으로 추후 고려)
- 전체 법령 DB 구축 (주요 18개 노동법 + 관련 판례만)
