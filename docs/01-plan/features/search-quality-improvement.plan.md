# search-quality-improvement Planning Document

> **Summary**: Pinecone 검색 품질 개선 — 네임스페이스 통합, Contextual Retrieval 확대, 하이브리드 검색 전략
>
> **Project**: nodong.kr RAG 챗봇
> **Version**: 1.0
> **Author**: Claude
> **Date**: 2026-03-13
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | laborlaw/laborlaw-v2 간 검색 품질 차이 미미(Avg 0.58 vs 0.57), legal_consultation.py가 참조하는 네임스페이스(precedent, interpretation 등)가 현재 인덱스에 존재하지 않아 법률상담 멀티소스 검색이 완전히 실패함 |
| **Solution** | 1) 네임스페이스 재구축(행정해석·판례·훈령·Q&A를 소스별 분리), 2) 전체 소스에 Contextual Retrieval 적용, 3) rag.py를 멀티네임스페이스 하이브리드 검색으로 업그레이드, 4) 메타데이터 스키마 통일 |
| **Function/UX Effect** | 법률상담 시 판례·행정해석·훈령이 소스별로 정확하게 검색되고, 검색 점수 +10~15% 향상 예상. 사용자에게 출처 유형(판례/행정해석/법조문)별 근거 제시 가능 |
| **Core Value** | 법률 RAG 시스템의 검색 정확도와 신뢰성 향상 — "근거 있는 답변" 품질의 핵심 기반 |

---

## 1. Overview

### 1.1 Purpose

현재 Pinecone 검색 아키텍처의 세 가지 핵심 문제를 해결한다:

1. **깨진 검색 경로**: `legal_consultation.py`가 참조하는 `precedent`, `interpretation`, `regulation`, `legal_cases` 네임스페이스가 현재 `semiconductor-lithography` 인덱스에 존재하지 않아, 법률상담 멀티소스 검색이 빈 결과를 반환
2. **Contextual Retrieval 미확대**: `laborlaw-v2` (9,088벡터, 행정해석+판례)에만 적용. 법령원문·Q&A·훈령 등 나머지 소스는 표준 임베딩만 사용
3. **검색 점수 편차**: Top-1 평균 0.57~0.59로, 법률 도메인 특성상 더 높은 정밀도 필요

### 1.2 Background

**벤치마크 결과 (2026-03-13, 16건 쿼리)**:

| 카테고리 | laborlaw | laborlaw-v2 | 차이 |
|----------|----------|-------------|------|
| 법령 | 0.6054 | 0.5736 | -0.0319 |
| 판례 | 0.5566 | 0.5649 | +0.0083 |
| 행정해석 | 0.5984 | 0.5940 | -0.0044 |
| 복합 | 0.5961 | 0.5631 | -0.0330 |
| **전체** | **0.5891** | **0.5739** | **-0.0152** |

**현재 인덱스 상태** (`semiconductor-lithography`):

| 네임스페이스 | 벡터 수 | 설명 |
|-------------|---------|------|
| `laborlaw` | 6,598 | 표준 임베딩 (Q&A + 법령 + 행정해석 + 판례 등 혼합) |
| `laborlaw-v2` | 9,088 | Contextual Retrieval (행정해석 + 판례만) |
| `__default__` | 11,311 | BEST Q&A (원래 laborconsult-bestqna에서 마이그레이션) |
| 기타(semiconductor 등) | ~11,452 | 노동법 무관 데이터 |

**Critical Issue**: `laborconsult-bestqna` 인덱스는 이미 삭제됨 (404). `legal_consultation.py`의 `TOPIC_SEARCH_CONFIG`가 참조하는 네임스페이스(`precedent`, `interpretation`, `regulation`, `legal_cases`)가 현재 인덱스에 없어 실질적으로 멀티소스 검색 기능이 동작하지 않는 상태.

### 1.3 Related Documents

- 벤치마크 결과: `search_quality_results.json`
- 테스트 스크립트: `search_quality_test.py`
- 기존 업로드: `pinecone_upload_legal.py` (소스별 네임스페이스), `pinecone_upload_contextual.py` (Contextual Retrieval)
- 법률상담 모듈: `app/core/legal_consultation.py`
- RAG 검색: `app/core/rag.py`

---

## 2. Scope

### 2.1 In Scope

- [x] 현재 인덱스/네임스페이스 상태 분석 (완료: search_quality_test.py)
- [ ] 소스별 네임스페이스 재구축 (precedent, interpretation, regulation, legal_cases)
- [ ] 전체 소스에 Contextual Retrieval 적용 확대
- [ ] `rag.py` 멀티네임스페이스 하이브리드 검색 업그레이드
- [ ] 메타데이터 스키마 통일 (laborlaw vs laborlaw-v2 간 불일치 해소)
- [ ] 검색 품질 벤치마크 재실행 및 비교

### 2.2 Out of Scope

- 임베딩 모델 변경 (text-embedding-3-small → large 등)
- Pinecone 인덱스 분리 (현재 semiconductor-lithography 공유 유지)
- Reranker 도입 (Cohere rerank 등 — 향후 별도 feature)
- 벡터 DB 마이그레이션 (Pinecone → Qdrant/Weaviate 등)

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | 소스별 네임스페이스 재구축: precedent, interpretation, regulation, qa를 Contextual Retrieval로 재업로드 | High | Pending |
| FR-02 | `legal_consultation.py`가 새 네임스페이스에서 정상 검색되도록 수정 | High | Pending |
| FR-03 | `rag.py`를 멀티네임스페이스 병렬 검색으로 업그레이드 (legal_consultation.py 패턴 재활용) | High | Pending |
| FR-04 | 메타데이터 스키마 통일 — 모든 네임스페이스에서 동일한 필드명 사용 | Medium | Pending |
| FR-05 | 기존 `laborlaw`, `laborlaw-v2` 네임스페이스 정리 (새 네임스페이스로 마이그레이션 후 삭제) | Medium | Pending |
| FR-06 | 검색 품질 벤치마크 스크립트 업데이트 — 새 네임스페이스 대응 | Medium | Pending |
| FR-07 | `.env` 및 `config.py` 업데이트 — namespace 설정 유연화 | Low | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| Performance | 멀티네임스페이스 검색 총 응답시간 < 1.5초 (현재 단일 NS ~0.5초) | search_quality_test.py 응답시간 측정 |
| Quality | Top-1 평균 점수 ≥ 0.65 (현재 0.59) | 16건 벤치마크 쿼리 재실행 |
| Reliability | 검색 실패 시 graceful degradation (빈 NS → 다른 NS fallback) | 에러 시나리오 테스트 |
| Cost | Contextual Retrieval 업로드 비용 < $10 (Claude Haiku 맥락 생성) | API 비용 추산 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] 소스별 4개 네임스페이스(precedent, interpretation, regulation, qa)에 Contextual Retrieval 적용 완료
- [ ] `legal_consultation.py`의 `search_multi_namespace()` 정상 동작 확인
- [ ] `rag.py`가 멀티네임스페이스 검색 지원
- [ ] 메타데이터 스키마 통일 (source_type, title, section, chunk_text, url, date, category)
- [ ] 벤치마크 Top-1 평균 ≥ 0.65
- [ ] 기존 chatbot 기능 regression 없음

### 4.2 Quality Criteria

- [ ] 16건 벤치마크 쿼리 전체 유효 결과 반환 (score ≥ 0.3)
- [ ] `legal_consultation.py` 12개 주제 전체 검색 성공
- [ ] 업로드 스크립트 resume/reset 기능 정상 동작

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Contextual Retrieval 확대 후에도 검색 품질 향상 미미 | Medium | Medium | 벤치마크 목표치를 현실적으로 설정 (0.65), 개선 안 되면 Reranker 도입 별도 계획 |
| 대량 재업로드 시 API 비용 초과 | Low | Low | `--dry-run`으로 사전 추산, 소스별 단계적 업로드 |
| 기존 `laborlaw` NS 삭제 시 chatbot 장애 | High | Medium | 새 NS 완성 전까지 기존 NS 유지, 코드 먼저 변경 후 NS 전환 |
| 네임스페이스 수 증가로 검색 레이턴시 증가 | Medium | Medium | 주제별 검색 대상 NS를 2-3개로 제한 (현재 legal_consultation.py 패턴 유지) |

---

## 6. Architecture Considerations

### 6.1 Project Level Selection

| Level | Characteristics | Recommended For | Selected |
|-------|-----------------|-----------------|:--------:|
| **Starter** | Simple structure | Static sites | ☐ |
| **Dynamic** | Feature-based modules, BaaS integration | Web apps with backend | ☑ |
| **Enterprise** | Strict layer separation | High-traffic systems | ☐ |

### 6.2 Key Architectural Decisions

| Decision | Options | Selected | Rationale |
|----------|---------|----------|-----------|
| 네임스페이스 전략 | A) 소스별 분리 / B) 단일 통합 / C) 소스+CTX 이중 | A) 소스별 분리 | `legal_consultation.py` 주제별 검색에 최적 |
| Contextual Retrieval | A) 전체 적용 / B) 판례+행정해석만 / C) 미적용 | A) 전체 적용 | 판례에서 v2 우세 확인, 전체 확대 시 효과 극대화 |
| 메타데이터 스키마 | A) laborlaw 기존 / B) laborlaw-v2 기존 / C) 통합 신규 | C) 통합 신규 | 두 스키마의 장점을 합친 표준 스키마 정의 |
| 업로드 스크립트 | A) pinecone_upload_legal.py 수정 / B) contextual.py 수정 / C) 신규 통합 | B) contextual.py 확장 | 이미 Contextual Retrieval 로직 보유 |
| 검색 모듈 | A) rag.py 단독 / B) legal_consultation.py 단독 / C) rag.py에 멀티NS 통합 | C) rag.py 통합 | 코드 중복 제거, 단일 검색 진입점 |

### 6.3 Target Namespace Architecture

```
semiconductor-lithography 인덱스
├── precedent (판례) — Contextual Retrieval
├── interpretation (행정해석) — Contextual Retrieval
├── regulation (훈령/예규/고시) — Contextual Retrieval
├── qa (Q&A 상담사례 + BEST Q&A) — Contextual Retrieval
├── semiconductor / semiconductor-v2 (반도체 — 별도 도메인)
├── kosha / safeguide / field-training (산업안전 — 별도 도메인)
└── (laborlaw, laborlaw-v2 — 마이그레이션 후 삭제)
```

### 6.4 통합 메타데이터 스키마

```python
{
    "source_type": str,       # "precedent" | "interpretation" | "regulation" | "qa"
    "title": str,             # 문서 제목 (최대 200자)
    "category": str,          # 분류 (최대 50자)
    "section": str,           # 섹션명 (최대 100자)
    "chunk_text": str,        # 원본 청크 텍스트 (최대 900자)
    "url": str,               # 원문 URL
    "date": str,              # 작성일
    "chunk_index": int,       # 청크 인덱스
    "contextualized": bool,   # Contextual Retrieval 적용 여부
}
```

---

## 7. Convention Prerequisites

### 7.1 Existing Project Conventions

- [x] `CLAUDE.md` has coding conventions section
- [x] `.env` environment variables defined
- [x] Pinecone upload scripts follow consistent pattern

### 7.2 Conventions to Define/Verify

| Category | Current State | To Define | Priority |
|----------|---------------|-----------|:--------:|
| **메타데이터 필드명** | 불일치 (document_title vs title) | 통합 스키마 (§6.4) | High |
| **청크 ID 패턴** | `{source}_{id}_chunk_{n}` vs `ctx_{source}_{id}_c{n}` | `{source}_{id}_c{n}` 통일 | Medium |
| **Embed text 포맷** | 표준: `제목:\n분류:\n섹션:\n\n본문` / CTX: `[맥락]\n제목:\n분류:\n섹션:\n\n본문` | CTX 포맷으로 통일 | High |

### 7.3 Environment Variables Needed

| Variable | Purpose | Scope | To Be Created |
|----------|---------|-------|:-------------:|
| `PINECONE_INDEX_NAME` | 인덱스명 | Server | 기존 (semiconductor-lithography) |
| `PINECONE_NAMESPACE` | (삭제 예정 — 멀티NS로 전환) | Server | 삭제 |
| ~~`PINECONE_HOST`~~ | (Pinecone SDK가 자동 해석) | - | 삭제 가능 |

---

## 8. Implementation Strategy

### 8.1 Phase 1: 업로드 스크립트 통합 (pinecone_upload_contextual.py 확장)

1. `SOURCES` 목록에 훈령/예규(`regulation`), Q&A(`qa`) 추가
2. 소스별 네임스페이스 분리 지원 (`--namespace` 또는 소스 config에서 자동 결정)
3. 메타데이터 스키마를 §6.4 표준으로 통일
4. `--dry-run`으로 벡터 수/비용 사전 추산

### 8.2 Phase 2: 네임스페이스 재업로드

1. `precedent` NS에 판례 Contextual Retrieval 업로드
2. `interpretation` NS에 행정해석 Contextual Retrieval 업로드
3. `regulation` NS에 훈령/예규 Contextual Retrieval 업로드
4. `qa` NS에 Q&A 데이터 Contextual Retrieval 업로드

### 8.3 Phase 3: 검색 모듈 업그레이드

1. `rag.py`에 멀티네임스페이스 검색 통합 (legal_consultation.py 패턴)
2. `config.py`에서 단일 `namespace` 설정 제거, 주제별 NS 매핑 사용
3. `legal_consultation.py`가 새 NS에서 정상 동작 확인

### 8.4 Phase 4: 벤치마크 및 정리

1. 검색 품질 벤치마크 재실행 → 목표 Top-1 ≥ 0.65 확인
2. 기존 `laborlaw`, `laborlaw-v2` 네임스페이스 삭제
3. `.env`에서 `PINECONE_NAMESPACE` 제거

---

## 9. Next Steps

1. [ ] Write design document (`search-quality-improvement.design.md`)
2. [ ] Team review and approval
3. [ ] Start implementation

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-13 | Initial draft — 벤치마크 결과 기반 계획 수립 | Claude |
