# rerank Analysis Report

> **Analysis Type**: Gap Analysis (Design vs Implementation)
>
> **Project**: laborconsult
> **Analyst**: gap-detector
> **Date**: 2026-03-16
> **Design Doc**: [rerank.design.md](../02-design/features/rerank.design.md)

---

## 1. Analysis Overview

### 1.1 Analysis Purpose

Verify that the Cohere Rerank implementation matches the design specification across all 5 modified files.

### 1.2 Analysis Scope

- **Design Document**: `docs/02-design/features/rerank.design.md`
- **Implementation Files**: `app/core/rag.py`, `app/core/pipeline.py`, `app/config.py`, `requirements.txt`, `.env.example`
- **Analysis Date**: 2026-03-16

---

## 2. Gap Analysis (Design vs Implementation)

### 2.1 Functional Requirements

| FR | Design Requirement | Implementation | Status |
|----|-------------------|----------------|--------|
| FR-01 | Pinecone 검색 후 Cohere Rerank로 결과 재정렬 | `rerank_results()` in rag.py L139-198 | ✅ MATCH |
| FR-02 | 초기 검색 top_k를 15로 확대 | pipeline.py L854: `search_top_k = 15 if config.cohere_api_key else 5` | ✅ MATCH |
| FR-03 | Rerank 후 상위 5건만 LLM 컨텍스트로 전달 | `RERANK_TOP_N = 5` in rag.py L136 | ✅ MATCH |
| FR-04 | COHERE_API_KEY 미설정 시 rerank 건너뛰기 | rag.py L156 + pipeline.py L860 both check key | ✅ MATCH |
| FR-05 | Rerank 실패 시 cosine score 정렬로 폴백 | rag.py L197: `return hits[:top_n]` in except block | ✅ MATCH |

### 2.2 Module: `app/core/rag.py` — Detailed Item Comparison

| # | Design Item | Design Spec | Implementation | Status | Notes |
|---|-------------|-------------|----------------|--------|-------|
| 1 | RERANK_MODEL constant | `"rerank-v3.5"` | L135: `"rerank-v3.5"` | ✅ MATCH | |
| 2 | RERANK_TOP_N constant | `5` | L136: `5` | ✅ MATCH | |
| 3 | RERANK_TIMEOUT constant | `3.0` | Not implemented | ❌ MISSING | Design specifies 3.0s timeout but no timeout parameter used |
| 4 | Function signature | `rerank_results(query, hits, cohere_api_key, top_n=RERANK_TOP_N)` | L139-144: identical | ✅ MATCH | |
| 5 | Docstring | 4 Args + Returns documented | L145-155: identical | ✅ MATCH | |
| 6 | Guard clause | `if not hits or not cohere_api_key` | L156: identical | ✅ MATCH | |
| 7 | Client class | `cohere.ClientV2` | L162: `cohere.ClientV2` | ✅ MATCH | |
| 8 | cohere import location | Top-level `import cohere` | L160: lazy `import cohere` inside function | ⚠️ CHANGED | Intentional: avoids ImportError when cohere not installed |
| 9 | Document text extraction | title + section + content concatenation | L166-174: identical logic | ✅ MATCH | |
| 10 | "(empty)" fallback | `text.strip() or "(empty)"` | L174: identical | ✅ MATCH | |
| 11 | co.rerank() call | model, query, documents, top_n args | L176-181: identical | ✅ MATCH | |
| 12 | top_n guard | `min(top_n, len(hits))` | L180: identical | ✅ MATCH | |
| 13 | Result reconstruction | `hits[item.index].copy()` + `rerank_score` | L185-188: identical | ✅ MATCH | |
| 14 | rerank_score rounding | `round(item.relevance_score, 4)` | L187: identical | ✅ MATCH | |
| 15 | Success log | `"Rerank 완료: %d건 → %d건 (model=%s)"` | L190-193: identical | ✅ MATCH | |
| 16 | Exception handler | `except Exception as e` → `hits[:top_n]` | L196-198: identical | ✅ MATCH | |
| 17 | Warning log on failure | `"Rerank 실패, cosine 정렬 폴백: %s"` | L197: identical | ✅ MATCH | |

### 2.3 Module: `app/core/pipeline.py` — Integration

| # | Design Item | Design Spec | Implementation | Status |
|---|-------------|-------------|----------------|--------|
| 18 | Import statement | `from app.core.rag import ..., rerank_results` | L30: `from app.core.rag import search_pinecone_multi, format_pinecone_hits, rerank_results` | ✅ MATCH |
| 19 | search_top_k conditional | `15 if config.cohere_api_key else 5` | L854: identical | ✅ MATCH |
| 20 | search_pinecone_multi call | `top_k=search_top_k` | L856: identical | ✅ MATCH |
| 21 | rerank guard condition | `if pinecone_hits and config.cohere_api_key` | L860: identical | ✅ MATCH |
| 22 | rerank_results call | `rerank_results(query, pinecone_hits, config.cohere_api_key)` | L861-862: identical | ✅ MATCH |
| 23 | format_pinecone_hits after rerank | unchanged | L866: identical | ✅ MATCH |
| 24 | Comment: "rerank 시 후보 확대" | present | L853: identical | ✅ MATCH |
| 25 | Comment: "Cohere Rerank (API 키 설정 시)" | present | L859: identical | ✅ MATCH |

### 2.4 Module: `app/config.py` — Configuration

| # | Design Item | Design Spec | Implementation | Status |
|---|-------------|-------------|----------------|--------|
| 26 | cohere_api_key field | `cohere_api_key: str \| None = None` | L30: identical | ✅ MATCH |
| 27 | Field position in dataclass | after odcloud_api_key | L30: after odcloud_api_key (L29) | ✅ MATCH |
| 28 | from_env() reads COHERE_API_KEY | `os.getenv("COHERE_API_KEY")` | L60: `cohere_api_key = os.getenv("COHERE_API_KEY")` | ✅ MATCH |
| 29 | from_env() passes to constructor | `cohere_api_key=cohere_api_key` | L69: identical | ✅ MATCH |

### 2.5 Module: `requirements.txt`

| # | Design Item | Design Spec | Implementation | Status |
|---|-------------|-------------|----------------|--------|
| 30 | cohere package | `cohere>=5.0.0` | L17: `cohere>=5.0.0` | ✅ MATCH |

### 2.6 Module: `.env.example`

| # | Design Item | Design Spec | Implementation | Status |
|---|-------------|-------------|----------------|--------|
| 31 | Comment text | `# Cohere - Rerank 검색 결과 재정렬용 (선택)` | L33: identical | ✅ MATCH |
| 32 | Variable entry | `COHERE_API_KEY=your_cohere_api_key_here` | L34: identical | ✅ MATCH |

---

## 3. Match Rate Summary

```
┌─────────────────────────────────────────────┐
│  Overall Match Rate: 97%                     │
├─────────────────────────────────────────────┤
│  Total Items:          32                    │
│  ✅ MATCH:             30 items (93.8%)      │
│  ⚠️ CHANGED:            1 item  (3.1%)      │
│  ❌ MISSING:            1 item  (3.1%)      │
│  🟡 ADDED:              0 items (0.0%)      │
└─────────────────────────────────────────────┘
```

---

## 4. Differences Found

### ❌ MISSING (Design O, Implementation X)

| # | Item | Design Location | Description | Impact |
|---|------|-----------------|-------------|--------|
| 3 | RERANK_TIMEOUT | design Section 2.1, L33 | Design specifies `RERANK_TIMEOUT = 3.0` constant, but implementation has no timeout parameter. The `co.rerank()` call uses Cohere SDK's default timeout. | Low — SDK default timeout is acceptable; Cohere SDK uses httpx with reasonable defaults (~300s). The 3.0s design value would actually be more restrictive and beneficial for latency control. |

### ⚠️ CHANGED (Design != Implementation)

| # | Item | Design | Implementation | Impact | Intentional? |
|---|------|--------|----------------|--------|--------------|
| 8 | cohere import location | Top-level: `import cohere` at module level | Lazy: `import cohere` inside function body (L160) | None — functional equivalence | Yes — prevents `ImportError` if cohere package is not installed (graceful degradation for environments without cohere) |

---

## 5. Scoring

| Category | Score | Status |
|----------|:-----:|:------:|
| Design Match | 97% | ✅ |
| Architecture Compliance | 100% | ✅ |
| Convention Compliance | 100% | ✅ |
| Error Handling | 100% | ✅ |
| **Overall** | **97%** | ✅ |

---

## 6. Recommended Actions

### 6.1 Optional Improvement (Low Priority)

| Item | File | Recommendation |
|------|------|----------------|
| RERANK_TIMEOUT | `app/core/rag.py` | Consider adding `timeout=RERANK_TIMEOUT` to `cohere.ClientV2()` constructor or `co.rerank()` call for explicit latency control. The design's 3.0s timeout would help prevent slow rerank calls from delaying the entire pipeline response. |

### 6.2 Documentation Update

| Item | Action |
|------|--------|
| Lazy import | Update design document Section 2.1 to reflect lazy import pattern (`import cohere` inside function) with rationale |
| RERANK_TIMEOUT | Either implement the timeout or remove from design document (choose one) |

---

## 7. Conclusion

The rerank feature implementation is an excellent match to the design specification. 30 of 32 items are exact matches. The 1 changed item (lazy import) is an intentional improvement for robustness. The 1 missing item (RERANK_TIMEOUT constant) is low impact since the SDK provides reasonable defaults, though adding it would give better latency control as the design intended.

**Match Rate: 97% -- Design and implementation match well.**

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-16 | Initial analysis | gap-detector |
