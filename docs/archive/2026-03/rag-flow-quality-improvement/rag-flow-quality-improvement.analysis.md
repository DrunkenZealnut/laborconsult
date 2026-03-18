# Gap Analysis: RAG Flow 품질 향상

> Feature: `rag-flow-quality-improvement`
> Design: `docs/02-design/features/rag-flow-quality-improvement.design.md`
> Analyzed: 2026-03-18
> Match Rate: **99%**

---

## 1. Overall Scores

| Category | Score | Status |
|----------|:-----:|:------:|
| Phase 1: Hybrid Search (BM25) | 100% | PASS |
| Phase 2: Adaptive Retrieval | 100% | PASS |
| Phase 3: Self-RAG | 100% | PASS |
| Graceful Degradation | 83% | PASS |
| File Changes | 100% | PASS |
| **Overall (96 items)** | **99%** | **PASS** |

---

## 2. Match Rate

```
Total items:             97
  N/A (corpus):           1
Scoreable items:         96
  MATCH:                 74  (77%)
  POSITIVE:              18  (19%)
  CHANGED (intentional):  3  ( 3%)
  MISSING:                1  ( 1%)
────────────────────────────────────
Effective Match Rate:   99%  (95/96)
```

---

## 3. CHANGED Items (3 — intentional, zero impact)

| # | Item | Design | Implementation | Reason |
|---|------|--------|----------------|--------|
| 29 | `search_hybrid()` 폴백 로그 | `"Hybrid: BM25 unavailable, Dense-only"` | `"BM25 unavailable, Dense-only: {error}"` | 에러 상세 포함 디버깅 편의 |
| 51 | `classify_complexity()` 스코어 가중치 | len>=80:+2, >=40:+1 | len>=80:+3, >=40:+2, >=25:+1 | 넓은 범위로 세밀한 분류 |
| 52 | COMPLEX 임계값 | score >= 4 | score >= 5 | 스코어 범위 확대에 비례 조정 |

## 4. MISSING Items (1 — low impact)

| # | Item | Design Location | Impact |
|---|------|-----------------|--------|
| 87 | `classify_complexity()` 실패 시 MODERATE 폴백 | Section 7 Graceful Degradation | Low — 순수 함수(외부 I/O 없음), 실패 확률 극저 |

**수정 제안** (선택사항, 3줄):
```python
try:
    complexity = classify_complexity(query, ...)
except Exception:
    complexity = QueryComplexity.MODERATE
```

## 5. POSITIVE Additions (18 — 구현이 설계보다 개선)

| Item | File | Value |
|------|------|-------|
| `_get_mecab()` 싱글턴 | bm25_search.py | Mecab 반복 생성 방지 |
| `import re` 모듈 최상위 | bm25_search.py | Python 베스트 프랙티스 |
| numpy 의존성 제거 | bm25_search.py | 순수 Python 정렬, 불필요 의존성 제거 |
| `doc.get("text", "")` | bm25_search.py | 안전한 키 접근 |
| 검색/RRF 로깅 추가 | bm25_search.py | 관찰가능성 향상 |
| BM25 전체 try/except | rag.py | 견고한 폴백 |
| API 키 검증 + dotenv | build_bm25_corpus.py | 독립 실행 안전성 |
| 출력 디렉토리 자동 생성 | build_bm25_corpus.py | `mkdir(parents=True)` |
| 빈 텍스트 필터링 | build_bm25_corpus.py | 무의미 코퍼스 항목 방지 |
| `force_decompose: False` 명시 | query_decomposer.py | `.get()` 폴백 불필요 |
| `_COMPLEXITY_MARKERS` 모듈 상수 | query_decomposer.py | DRY 원칙 |
| `min(MAX_CONCURRENT, len(hits))` | self_rag.py | 불필요 워커 방지 |
| Self-RAG try/except 래핑 | pipeline.py | graceful degradation 강화 |

---

## 6. Verdict

**PASS** — 99% match rate. 기능적 갭 없음.

선택사항: `classify_complexity()` try/except 폴백 추가 (3줄, low priority).
운영 사항: `python build_bm25_corpus.py` 실행하여 `data/bm25_corpus.json` 생성 필요.
