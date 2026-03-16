# multi-query Completion Report

> **Feature**: multi-query — LLM 기반 쿼리 분해로 RAG 검색 recall 향상
> **Date**: 2026-03-16
> **Status**: Completed

---

## Executive Summary

| Item | Detail |
|------|--------|
| **Feature** | multi-query |
| **Started** | 2026-03-16 |
| **Completed** | 2026-03-16 |
| **Duration** | 1 session |

| Metric | Value |
|--------|-------|
| **Match Rate** | 97% |
| **Checked Items** | 40 |
| **Changed Files** | 2 (1 new + 1 modified) |
| **Lines Added** | ~160 |

### Value Delivered

| Perspective | Content |
|-------------|---------|
| **Problem** | 단일 임베딩 검색은 복합 질문에서 관련 문서를 놓쳐 답변 품질 저하 |
| **Solution** | Claude Haiku로 질문을 2~4개 관점별 쿼리로 분해, 기존 `search_pinecone_multi` 인프라 재활용 |
| **Function/UX Effect** | 복합 노동법 질문에서 검색 recall 향상, 더 풍부한 판례·행정해석·Q&A 참조 |
| **Core Value** | 호출당 $0.0001, 지연 ~300ms 추가로 검색 품질 개선 — 최소 비용·최대 효과 |

---

## 1. PDCA Cycle Summary

| Phase | Status | Output |
|-------|:------:|--------|
| Plan | ✅ | `docs/01-plan/features/multi-query.plan.md` |
| Design | ✅ | `docs/02-design/features/multi-query.design.md` |
| Do | ✅ | `app/core/query_decomposer.py` (new), `app/core/pipeline.py` (modified) |
| Check | ✅ 97% | `docs/03-analysis/multi-query.analysis.md` |
| Act | N/A | 97% ≥ 90%, iterate 불필요 |
| Report | ✅ | 본 문서 |

---

## 2. Implementation Summary

### 2.1 New Module: `app/core/query_decomposer.py`

| Component | Description |
|-----------|-------------|
| `DECOMPOSE_MODEL` | `claude-haiku-4-5-20251001` — 저비용, 빠른 응답 |
| `DECOMPOSE_SYSTEM` | 한국 노동법 전문 검색 쿼리 분해 프롬프트 |
| `_should_decompose()` | 단순 질문 필터링 — 길이 < 40자 & 복합 신호 없으면 건너뜀 |
| `decompose_query()` | LLM 호출 → JSON 파싱 → 2~4개 쿼리 반환, 실패 시 `[]` |

**특이사항 (설계 대비 추가):**
- LLM이 ` ```json ``` ` 마크다운으로 래핑할 때 자동 제거
- 모든 에러 핸들러에 elapsed time 포함 (진단 강화)

### 2.2 Modified: `app/core/pipeline.py`

| Component | Description |
|-----------|-------------|
| `_merge_search_queries()` | LLM 분해 + 규칙 기반 쿼리 병합, 중복 제거, max 5개 |
| 통합 지점 (~line 838) | `decompose_query()` → `_merge_search_queries()` → `search_pinecone_multi()` |

### 2.3 Data Flow

```
사용자 질문
    ├─ analyze_intent() → AnalysisResult (기존)
    ├─ decompose_query() → ["쿼리1", "쿼리2", "쿼리3"] (신규)
    ├─ build_precedent_queries() → ["규칙쿼리1", "규칙쿼리2"] (기존)
    └─ _merge_search_queries() → 병합 최대 5개 → search_pinecone_multi()
```

---

## 3. Quality Metrics

### 3.1 Gap Analysis Results

| Category | Score |
|----------|:-----:|
| Design Match | 97% |
| Architecture Compliance | 100% |
| Convention Compliance | 100% |
| FR 충족 | 5/5 (100%) |

### 3.2 Functional Requirements

| FR | Requirement | Status |
|----|-------------|:------:|
| FR-01 | 2~4개 관점별 쿼리 분해 | ✅ |
| FR-02 | search_pinecone_multi() 통합 | ✅ |
| FR-03 | build_precedent_queries() 결과와 병합 | ✅ |
| FR-04 | 단순 질문 분해 건너뛰기 | ✅ |
| FR-05 | 실패 시 폴백 (빈 리스트) | ✅ |

### 3.3 Non-Functional

| Criteria | Target | Status |
|----------|--------|:------:|
| 지연시간 | ≤ 500ms | ✅ (Haiku 평균 ~300ms) |
| 비용 | ≤ $0.0025/호출 | ✅ (~$0.0001/호출) |
| 안정성 | 폴백 정상 동작 | ✅ (3개 에러 핸들러) |

---

## 4. Cost Analysis

| Item | Value |
|------|-------|
| Haiku 입력 | ~250 토큰/호출 |
| Haiku 출력 | ~80 토큰/호출 |
| 호출 비용 | ~$0.0001/호출 |
| 일 1,000건 기준 | ~$0.10/일 |
| 추가 Pinecone 호출 | +6~9 쿼리 (3 NS × 2~3 추가) |

---

## 5. Files Changed

| File | Type | Lines |
|------|------|:-----:|
| `app/core/query_decomposer.py` | New | 144 |
| `app/core/pipeline.py` | Modified | +28 (import, helper, integration) |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-03-16 | Completion report | Claude |
