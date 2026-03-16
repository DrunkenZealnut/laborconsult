# rerank Completion Report

> **Feature**: rerank — Cohere Rerank로 RAG 검색 정밀도 향상
> **Date**: 2026-03-16
> **Status**: Completed

---

## Executive Summary

| Item | Detail |
|------|--------|
| **Feature** | rerank |
| **Started** | 2026-03-16 |
| **Completed** | 2026-03-16 |
| **Duration** | 1 session |

| Metric | Value |
|--------|-------|
| **Match Rate** | 97% |
| **Checked Items** | 32 |
| **Changed Files** | 5 (rag.py, pipeline.py, config.py, requirements.txt, .env.example) |
| **Lines Added** | ~80 |

### Value Delivered

| Perspective | Content |
|-------------|---------|
| **Problem** | cosine 유사도 기반 정렬은 복합 질문에서 관련성 낮은 문서가 상위에 혼입 |
| **Solution** | Pinecone top_k=15 후보 확보 → Cohere rerank-v3.5(cross-encoder)로 재정렬 → 상위 5건 |
| **Function/UX Effect** | 5개 복합 질문 테스트에서 **25건 중 22건(88%) 순위 변동** — "5인 미만 사업장", "직장내 괴롭힘 퇴사 실업급여" 등 정확히 일치하는 문서가 1위로 상승 |
| **Core Value** | 추가 지연 ~400ms, 비용 ~$2/일로 검색 정밀도 대폭 향상. API 키 없으면 기존 동작 100% 유지 |

---

## 1. PDCA Cycle Summary

| Phase | Status | Output |
|-------|:------:|--------|
| Plan | ✅ | `docs/01-plan/features/rerank.plan.md` |
| Design | ✅ | `docs/02-design/features/rerank.design.md` |
| Do | ✅ | 5개 파일 수정/추가 |
| Check | ✅ 97% | `docs/03-analysis/rerank.analysis.md` |
| Act | N/A | 97% ≥ 90%, iterate 불필요 |
| Report | ✅ | 본 문서 |

---

## 2. Implementation Summary

### 2.1 Modified Files

| File | Change | Lines |
|------|--------|:-----:|
| `app/core/rag.py` | `rerank_results()` 함수 추가 | +65 |
| `app/core/pipeline.py` | import + top_k 분기 + rerank 호출 | +8 |
| `app/config.py` | `cohere_api_key` 필드 + from_env() | +3 |
| `requirements.txt` | `cohere>=5.0.0` | +1 |
| `.env.example` | `COHERE_API_KEY` 안내 | +3 |

### 2.2 Key Design Decisions

| 항목 | 결정 | 근거 |
|------|------|------|
| Rerank 모델 | `rerank-v3.5` | 다국어(한국어) 지원, 최신 |
| Lazy import | `import cohere` 함수 내부 | 미설치 환경 ImportError 방지 |
| top_k 분기 | 15 (rerank 시) / 5 (기존) | API 키 유무에 따라 자동 |
| 폴백 | 실패 시 cosine 정렬 유지 | 파이프라인 안정성 보장 |

---

## 3. Benchmark Results (5건 복합 질문 비교)

### 3.1 순위 변동 요약

| 질문 | 공통 | 신규진입 | 탈락 | Rerank 핵심 효과 |
|------|:----:|:--------:|:----:|------------------|
| 정리해고+퇴직금+실업급여 | 2 | 3 | 3 | "실업급여 산정" 문서 진입 |
| 연차 미사용+사용촉진 | 0 | **5** | 5 | "연차촉진" 직접 관련 문서만 선택 |
| 야간+휴일수당 5인미만 | 0 | **5** | 5 | "5인 미만 사업장" 1위 (re=0.90) |
| 계약직 정규직전환 | 1 | 4 | 4 | "2년 이상 정규직 전환" 진입 |
| 직장괴롭힘+실업급여 | 0 | **5** | 5 | 정확 일치 문서 1위 (re=0.95) |
| **합계** | 3 | **22** | 22 | — |

### 3.2 성능

| 항목 | WITHOUT Rerank | WITH Rerank | 차이 |
|------|:--------------:|:-----------:|:----:|
| 평균 소요시간 | ~1,800ms | ~2,200ms | +400ms |
| 검색 후보 수 | ~10건 | ~30건 → 5건 | 후보 3배 확대 |
| 호출당 비용 | $0 | ~$0.002 | — |

### 3.3 대표 사례: 질문 5

```
질문: "직장 내 괴롭힘으로 퇴사하면 실업급여 받을 수 있나요?"

WITHOUT (cosine):
  1. [Q&A] 실업급여                              cos=0.6522
  2. [Q&A] 실업급여중 부정수급에 대한 기준이...      cos=0.6577

WITH (rerank):
  1. [Q&A] 직장내 폭언으로 퇴사 시 실업급여...       re=0.9513  ← 정확 매칭
  2. [Q&A] 직장내 괴롭힘으로 인한 자발적 퇴사...     re=0.9322
  3. [Q&A] 직장내 괴롭힘으로 퇴사 후 실업급여 신청... re=0.9043
```

---

## 4. Quality Metrics

| Category | Score |
|----------|:-----:|
| Design Match | 97% |
| Architecture Compliance | 100% |
| FR 충족 | 5/5 (100%) |
| MISSING | 1건 (RERANK_TIMEOUT — Low, SDK 기본값 사용) |
| CHANGED | 1건 (lazy import — 의도적 개선) |

---

## 5. Cost Analysis

| Item | Value |
|------|-------|
| Rerank 입력 | ~15건 × 200자 = ~3,000자/호출 |
| 호출 비용 | ~$0.002/검색 |
| 일 1,000건 기준 | ~$2/일 |
| 추가 지연 | ~400ms |
| Graceful degradation | API 키 없으면 비용 $0, 기존 동작 유지 |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-03-16 | Completion report with benchmark | Claude |
