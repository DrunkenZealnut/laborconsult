# Design: RAG Flow 품질 향상

> Feature: `rag-flow-quality-improvement`
> Plan: `docs/01-plan/features/rag-flow-quality-improvement.plan.md`
> Created: 2026-03-18
> Level: Dynamic

---

## 1. Overview

현재 Dense-only 벡터 검색 파이프라인에 3가지 개선을 적용:
1. **Hybrid Search** — BM25 키워드 매칭 + Dense 의미 검색을 RRF로 결합
2. **Adaptive Retrieval** — 질문 복잡도 기반 검색 전략 동적 분기
3. **Self-RAG 검증** — Rerank 후 LLM 관련성 판정으로 무관 문서 필터링

### 1.1 현재 파이프라인 vs 개선 후

```
현재:
  Query → Decompose → Dense Search → Rerank → GraphRAG → LLM

개선 후:
  Query → Decompose → [BM25 + Dense] → RRF Fusion → Rerank
        ↓ (복잡도 분류)
        → Adaptive top_k/max_queries
        → Self-RAG 관련성 필터
        → GraphRAG → LLM
```

---

## 2. Phase 1: Hybrid Search (BM25 + Dense Fusion)

### 2.1 신규 모듈: `app/core/bm25_search.py`

```python
"""BM25 키워드 검색 + Dense 벡터 검색 RRF 결합 모듈"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── BM25 인덱스 ──────────────────────────────────────────────────────────

_bm25_index = None       # rank_bm25.BM25Okapi | None
_bm25_corpus = None      # list[dict] — [{id, text, title, section, source_type}, ...]
_bm25_loaded = False

BM25_CORPUS_PATH = Path(__file__).parent.parent.parent / "data" / "bm25_corpus.json"
BM25_MAX_DOCS = 15000    # Vercel 메모리 제한 내 (256MB)


def _tokenize_ko(text: str) -> list[str]:
    """한국어 형태소 분석 기반 토크나이저.

    Mecab 설치 시 형태소 분석으로 정확한 토큰화.
    미설치 시 정규식 기반 경량 폴백.
    """
    # 1차: Mecab 형태소 분석 (설치되어 있으면 사용)
    try:
        from konlpy.tag import Mecab
        mecab = Mecab()
        # 명사(NNG,NNP) + 동사어간(VV) + 형용사어간(VA) 추출
        pos_tags = mecab.pos(text)
        tokens = [word for word, tag in pos_tags
                  if tag.startswith(('NNG', 'NNP', 'VV', 'VA')) and len(word) >= 2]
        if tokens:
            return tokens
    except (ImportError, Exception):
        pass  # Mecab 미설치 → 폴백

    # 2차: 정규식 기반 경량 토크나이저 (Vercel serverless 호환)
    import re
    text = re.sub(r'[은는이가을를의에서로부터까지도만에게와과](?=\s|$)', '', text)
    tokens = re.sub(r'[^\w\s]', ' ', text).split()
    return [t for t in tokens if len(t) >= 2]


def load_bm25_corpus() -> bool:
    """BM25 코퍼스 로드 (서버 시작 시 1회).

    data/bm25_corpus.json 형식:
    [{"id": "...", "text": "...", "title": "...", "section": "...", "source_type": "..."}, ...]
    """
    global _bm25_index, _bm25_corpus, _bm25_loaded

    if _bm25_loaded:
        return _bm25_index is not None

    _bm25_loaded = True

    if not BM25_CORPUS_PATH.exists():
        logger.info("BM25 corpus not found: %s — BM25 disabled", BM25_CORPUS_PATH)
        return False

    try:
        from rank_bm25 import BM25Okapi

        start = time.monotonic()
        with open(BM25_CORPUS_PATH, "r", encoding="utf-8") as f:
            _bm25_corpus = json.load(f)

        if len(_bm25_corpus) > BM25_MAX_DOCS:
            _bm25_corpus = _bm25_corpus[:BM25_MAX_DOCS]

        tokenized = [_tokenize_ko(doc["text"]) for doc in _bm25_corpus]
        _bm25_index = BM25Okapi(tokenized)

        elapsed = (time.monotonic() - start) * 1000
        logger.info("BM25 loaded: %d docs, %.0fms", len(_bm25_corpus), elapsed)
        return True

    except ImportError:
        logger.warning("rank_bm25 not installed — BM25 disabled")
        return False
    except Exception as e:
        logger.warning("BM25 load failed: %s", e)
        return False


def search_bm25(query: str, top_k: int = 10) -> list[dict]:
    """BM25 키워드 검색.

    Returns:
        [{id, title, section, content, source_type, score(bm25)}, ...]
    """
    if _bm25_index is None or _bm25_corpus is None:
        return []

    tokens = _tokenize_ko(query)
    if not tokens:
        return []

    scores = _bm25_index.get_scores(tokens)

    # 상위 top_k 인덱스 추출
    import numpy as np
    top_indices = np.argsort(scores)[-top_k:][::-1]

    results = []
    for idx in top_indices:
        if scores[idx] <= 0:
            break
        doc = _bm25_corpus[idx]
        results.append({
            "id": doc["id"],
            "title": doc.get("title", ""),
            "section": doc.get("section", ""),
            "content": doc.get("text", ""),
            "source_type": doc.get("source_type", ""),
            "score": float(scores[idx]),
            "search_type": "bm25",
        })

    return results


# ── Reciprocal Rank Fusion (RRF) ─────────────────────────────────────────

RRF_K = 60  # 표준 RRF 상수


def reciprocal_rank_fusion(
    dense_hits: list[dict],
    bm25_hits: list[dict],
    alpha: float = 0.5,
    top_k: int = 15,
) -> list[dict]:
    """Dense + BM25 결과를 RRF로 결합.

    Args:
        dense_hits: Pinecone Dense 검색 결과
        bm25_hits: BM25 키워드 검색 결과
        alpha: Dense 가중치 (0.0=BM25 only, 1.0=Dense only, 0.5=균등)
        top_k: 반환할 최대 건수

    Returns:
        RRF 점수 기준 정렬된 결합 결과
    """
    rrf_scores: dict[str, float] = {}
    hit_map: dict[str, dict] = {}

    # Dense 점수
    for rank, hit in enumerate(dense_hits):
        doc_id = hit["id"]
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + alpha / (RRF_K + rank + 1)
        if doc_id not in hit_map:
            hit_map[doc_id] = hit

    # BM25 점수
    for rank, hit in enumerate(bm25_hits):
        doc_id = hit["id"]
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + (1 - alpha) / (RRF_K + rank + 1)
        if doc_id not in hit_map:
            hit_map[doc_id] = hit

    # RRF 점수 내림차순 정렬
    sorted_ids = sorted(rrf_scores, key=lambda x: rrf_scores[x], reverse=True)

    results = []
    for doc_id in sorted_ids[:top_k]:
        hit = hit_map[doc_id].copy()
        hit["rrf_score"] = round(rrf_scores[doc_id], 6)
        results.append(hit)

    return results
```

### 2.2 BM25 코퍼스 생성 스크립트

`build_bm25_corpus.py` (프로젝트 루트):

```python
"""Pinecone 메타데이터에서 BM25 코퍼스 JSON 생성"""

import json
import os
from pinecone import Pinecone

def build_corpus():
    pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
    index = pc.Index(os.getenv("PINECONE_INDEX_NAME", "semiconductor-lithography"))

    corpus = []
    for ns in ["laborlaw-v2", "counsel", "qa"]:
        # Pinecone list + fetch로 전체 벡터 메타데이터 추출
        for ids in index.list(namespace=ns):
            fetched = index.fetch(ids=ids, namespace=ns)
            for vid, vec in fetched.vectors.items():
                meta = vec.metadata or {}
                corpus.append({
                    "id": vid,
                    "text": meta.get("text", ""),
                    "title": meta.get("title", ""),
                    "section": meta.get("section", ""),
                    "source_type": meta.get("source_type", ""),
                })

    with open("data/bm25_corpus.json", "w", encoding="utf-8") as f:
        json.dump(corpus, f, ensure_ascii=False)

    print(f"BM25 corpus: {len(corpus)} documents saved")

if __name__ == "__main__":
    build_corpus()
```

### 2.3 rag.py 수정: Hybrid Search 통합

`search_pinecone_multi()` 호출 후 BM25 결과와 RRF 결합:

```python
# app/core/rag.py에 추가할 함수

def search_hybrid(
    queries: list[str],
    config: "AppConfig",
    top_k: int = 15,
    source_type: str | None = None,
    alpha: float = 0.5,
) -> list[dict]:
    """Hybrid Search: Dense (Pinecone) + Sparse (BM25) → RRF 결합.

    BM25 미사용 시 (코퍼스 미로드) Dense-only 폴백.
    """
    from app.core.bm25_search import search_bm25, reciprocal_rank_fusion, load_bm25_corpus

    # Dense 검색
    dense_hits = search_pinecone_multi(queries, config, top_k=top_k, source_type=source_type)

    # BM25 검색 (코퍼스 로드 시도)
    load_bm25_corpus()
    combined_query = " ".join(queries)
    bm25_hits = search_bm25(combined_query, top_k=top_k)

    if not bm25_hits:
        # BM25 미사용 — Dense-only 폴백
        logger.info("Hybrid: BM25 unavailable, Dense-only")
        return dense_hits

    # RRF 결합
    fused = reciprocal_rank_fusion(dense_hits, bm25_hits, alpha=alpha, top_k=top_k)
    logger.info("Hybrid: Dense %d + BM25 %d → RRF %d (alpha=%.1f)",
                len(dense_hits), len(bm25_hits), len(fused), alpha)
    return fused
```

### 2.4 pipeline.py 수정

```python
# 기존 (pipeline.py L888-892):
search_top_k = 15 if config.cohere_api_key else 5
pinecone_hits = search_pinecone_multi(
    pinecone_search_queries, config, top_k=search_top_k,
)

# 변경 후:
from app.core.rag import search_hybrid
search_top_k = 15 if config.cohere_api_key else 5
pinecone_hits = search_hybrid(
    pinecone_search_queries, config, top_k=search_top_k,
)
```

### 2.5 의존성 추가

```
# requirements.txt에 추가
rank-bm25>=0.2.2
numpy>=1.24.0  # (이미 존재할 가능성 높음)
```

---

## 3. Phase 2: Adaptive Retrieval

### 3.1 query_decomposer.py 수정

```python
# app/core/query_decomposer.py에 추가

from enum import Enum


class QueryComplexity(Enum):
    SIMPLE = "simple"       # 단일 주제, 짧은 질문
    MODERATE = "moderate"   # 중간 복잡도
    COMPLEX = "complex"     # 복합 질문, 다중 법률 참조


# 복잡도별 검색 파라미터
COMPLEXITY_PARAMS = {
    QueryComplexity.SIMPLE: {
        "search_top_k": 8,    # rerank 전 후보 (BM25+Dense 합산)
        "rerank_top_n": 3,    # rerank 후 최종
        "max_queries": 1,     # 쿼리 분해 없음 (원본만)
        "graph_hops": 1,      # GraphRAG 1-hop
        "self_rag": False,    # Self-RAG 비활성
    },
    QueryComplexity.MODERATE: {
        "search_top_k": 15,
        "rerank_top_n": 5,
        "max_queries": 3,
        "graph_hops": 2,
        "self_rag": False,
    },
    QueryComplexity.COMPLEX: {
        "search_top_k": 20,
        "rerank_top_n": 7,
        "max_queries": 4,        # 기존 decompose_query() 최대 활용
        "graph_hops": 2,
        "self_rag": True,        # Self-RAG 활성
        "force_decompose": True, # 길이 무관하게 반드시 쿼리 분해
    },
}


def classify_complexity(
    query: str,
    relevant_laws: list[str] | None = None,
    calculation_types: list[str] | None = None,
) -> QueryComplexity:
    """질문 복잡도 분류.

    기준:
    - SIMPLE: 길이 < 30자, 법률 참조 0~1개, 접속사 없음
    - MODERATE: 길이 30~80자, 법률 참조 1~2개, 접속사 0~1개
    - COMPLEX: 길이 > 80자 또는 법률 참조 3개+ 또는 접속사 2개+
    """
    stripped = query.strip()
    length = len(stripped)

    complexity_markers = ["그리고", "또한", "그런데", "하고", "이랑", "랑", ",", "?"]
    marker_count = sum(1 for m in complexity_markers if m in stripped)

    law_count = len(relevant_laws) if relevant_laws else 0
    calc_count = len(calculation_types) if calculation_types else 0

    # 스코어 기반 분류
    score = 0
    if length >= 80:
        score += 2
    elif length >= 40:
        score += 1

    score += min(law_count, 2)
    score += min(marker_count, 2)

    if calc_count >= 2:
        score += 1

    if score >= 4:
        return QueryComplexity.COMPLEX
    elif score >= 2:
        return QueryComplexity.MODERATE
    else:
        return QueryComplexity.SIMPLE
```

### 3.2 pipeline.py 수정: Adaptive 적용

```python
# pipeline.py RAG 검색 섹션 (L860 부근) 수정

from app.core.query_decomposer import classify_complexity, COMPLEXITY_PARAMS

# 복잡도 분류 (intent analysis 결과 활용)
complexity = classify_complexity(
    query,
    relevant_laws=getattr(analysis, "relevant_laws", None),
    calculation_types=analysis.calculation_types if analysis.requires_calculation else None,
)
params = COMPLEXITY_PARAMS[complexity]
logger.info("Query complexity: %s → %s", complexity.value, params)

# Adaptive: max_queries 제한
if params["max_queries"] <= 1:
    # SIMPLE: 분해 건너뜀
    decomposed = []
elif params.get("force_decompose"):
    # COMPLEX: 기존 _should_decompose() 무시, 반드시 분해
    decomposed = decompose_query(query, config.claude_client, ...,
                                  force=True)  # force 파라미터 추가
else:
    decomposed = decompose_query(query, config.claude_client, ...)

# Adaptive: search_top_k
pinecone_hits = search_hybrid(
    pinecone_search_queries, config, top_k=params["search_top_k"],
)

# Adaptive: rerank_top_n
if pinecone_hits and config.cohere_api_key:
    pinecone_hits = rerank_results(
        query, pinecone_hits, config.cohere_api_key,
        top_n=params["rerank_top_n"],
    )
```

---

## 4. Phase 3: Self-RAG 관련성 검증

### 4.1 신규 모듈: `app/core/self_rag.py`

```python
"""Self-RAG: 검색 결과의 질문 관련성을 LLM이 판정하여 무관 문서 필터링"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic

logger = logging.getLogger(__name__)

JUDGE_MODEL = "claude-haiku-4-5-20251001"
JUDGE_TIMEOUT = 3.0      # 초
MAX_CONCURRENT = 5        # 병렬 판정 최대 수

JUDGE_PROMPT = """다음 검색 결과가 사용자 질문에 관련이 있는지 판단하세요.

질문: {query}

검색 결과:
{document}

위 검색 결과가 질문에 직접적으로 관련이 있으면 "relevant", 없으면 "irrelevant"로만 답하세요."""


def judge_relevance(
    query: str,
    document: str,
    client: anthropic.Anthropic,
) -> bool:
    """단일 문서의 질문 관련성 판정.

    Returns:
        True = relevant, False = irrelevant
    """
    try:
        resp = client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=10,
            temperature=0,
            messages=[{
                "role": "user",
                "content": JUDGE_PROMPT.format(
                    query=query,
                    document=document[:1000],  # 토큰 제한
                ),
            }],
            timeout=JUDGE_TIMEOUT,
        )
        answer = resp.content[0].text.strip().lower()
        return "relevant" in answer

    except Exception as e:
        logger.debug("Self-RAG judge failed: %s — treating as relevant", e)
        return True  # 실패 시 보수적으로 포함


def filter_by_relevance(
    query: str,
    hits: list[dict],
    client: anthropic.Anthropic,
    min_hits: int = 2,
) -> tuple[list[dict], bool]:
    """검색 결과를 LLM 관련성 판정으로 필터링.

    Args:
        query: 사용자 질문
        hits: Rerank 후 검색 결과
        client: Anthropic 클라이언트
        min_hits: 최소 보장 건수 (너무 많이 필터링되면 상위 N건 유지)

    Returns:
        (관련 문서 리스트, needs_wider_search)
        - needs_wider_search: True이면 호출자가 검색 범위를 넓혀야 함
    """
    if len(hits) <= min_hits:
        return hits, False

    start = time.monotonic()

    # 병렬 판정
    filtered = []
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as pool:
        futures = {
            pool.submit(
                judge_relevance,
                query,
                f"{hit.get('title', '')} {hit.get('content', '')}",
                client,
            ): hit
            for hit in hits
        }
        for fut in as_completed(futures):
            hit = futures[fut]
            try:
                if fut.result():
                    filtered.append(hit)
            except Exception:
                filtered.append(hit)  # 실패 시 포함

    elapsed = (time.monotonic() - start) * 1000

    # 결과가 0건이면 검색 범위 확대 트리거 반환
    if len(filtered) == 0:
        logger.warning("Self-RAG: 모든 문서 irrelevant (%.0fms) — wider search 트리거", elapsed)
        return hits[:min_hits], True  # 기존 상위 N건 + 확대 요청

    # 최소 보장
    needs_wider = len(filtered) < min_hits
    if needs_wider:
        filtered = hits[:min_hits]

    logger.info("Self-RAG: %d → %d hits (%.0fms)", len(hits), len(filtered), elapsed)
    return filtered, needs_wider
```

### 4.2 pipeline.py 수정: Self-RAG 적용

```python
# Rerank 후, COMPLEX 질문에만 Self-RAG 적용
# 필터링 결과 0건이면 검색 범위를 넓혀 재검색

if params.get("self_rag") and pinecone_hits and len(pinecone_hits) > 2:
    from app.core.self_rag import filter_by_relevance
    pinecone_hits, needs_wider = filter_by_relevance(
        query, pinecone_hits, config.claude_client,
    )

    # 검색 범위 확대 트리거: top_k를 2배로 늘려 재검색
    if needs_wider:
        logger.info("Self-RAG wider search: top_k %d → %d", params["search_top_k"], params["search_top_k"] * 2)
        wider_hits = search_hybrid(
            pinecone_search_queries, config,
            top_k=params["search_top_k"] * 2,
        )
        if wider_hits and config.cohere_api_key:
            wider_hits = rerank_results(
                query, wider_hits, config.cohere_api_key,
                top_n=params["rerank_top_n"] + 3,
            )
        if wider_hits:
            pinecone_hits = wider_hits  # 확대 결과로 교체 (Self-RAG 재필터링 안 함)
```

---

## 5. File Changes

| File | Action | Description |
|------|--------|-------------|
| `app/core/bm25_search.py` | **Create** | BM25 검색 + RRF fusion 모듈 |
| `app/core/self_rag.py` | **Create** | Self-RAG 관련성 판정 모듈 |
| `app/core/rag.py` | **Modify** | `search_hybrid()` 함수 추가 |
| `app/core/query_decomposer.py` | **Modify** | `QueryComplexity`, `classify_complexity()`, `COMPLEXITY_PARAMS` 추가 |
| `app/core/pipeline.py` | **Modify** | Hybrid Search, Adaptive Retrieval, Self-RAG 통합 |
| `build_bm25_corpus.py` | **Create** | BM25 코퍼스 JSON 생성 스크립트 |
| `data/bm25_corpus.json` | **Create** | BM25 검색용 코퍼스 데이터 (빌드 시 생성) |
| `requirements.txt` | **Modify** | `rank-bm25>=0.2.2` 추가 |

---

## 6. Implementation Order

```
Phase 1 (P1): Hybrid Search — 1.5일
  ├─ 1.1 build_bm25_corpus.py 작성 + data/bm25_corpus.json 생성
  ├─ 1.2 app/core/bm25_search.py 작성 (_tokenize_ko, load_bm25_corpus, search_bm25, reciprocal_rank_fusion)
  ├─ 1.3 app/core/rag.py에 search_hybrid() 추가
  ├─ 1.4 app/core/pipeline.py: search_pinecone_multi → search_hybrid 교체
  ├─ 1.5 requirements.txt에 rank-bm25 추가
  └─ 1.6 단위 테스트: BM25 검색 + RRF 결합 검증

Phase 2 (P2): Adaptive Retrieval — 1일
  ├─ 2.1 app/core/query_decomposer.py: QueryComplexity, classify_complexity(), COMPLEXITY_PARAMS 추가
  ├─ 2.2 app/core/pipeline.py: 복잡도 분류 + 파라미터 동적 적용
  └─ 2.3 단위 테스트: 복잡도 분류 검증 (3단계 × 5개 예시)

Phase 3 (P3): Self-RAG — 1일
  ├─ 3.1 app/core/self_rag.py 작성 (judge_relevance, filter_by_relevance)
  ├─ 3.2 app/core/pipeline.py: COMPLEX 질문에 Self-RAG 적용
  └─ 3.3 단위 테스트: 관련성 판정 검증

통합 테스트 — 0.5일
  ├─ 벤치마크 30개 질문 실행 (benchmark_pipeline.py)
  └─ Precision@5, 환각율, 응답 지연 측정
```

---

## 7. Graceful Degradation

모든 신규 기능은 실패 시 기존 로직으로 폴백:

| 기능 | 실패 조건 | 폴백 |
|------|----------|------|
| BM25 | `rank_bm25` 미설치 / 코퍼스 미존재 | Dense-only 검색 (기존) |
| BM25 | 검색 결과 0건 | Dense-only 결과 사용 |
| Adaptive | classify_complexity 실패 | MODERATE 파라미터 사용 |
| Self-RAG | Haiku API 타임아웃/실패 | Rerank 결과 그대로 사용 |
| Self-RAG | 필터링 후 min_hits 미달 | 상위 min_hits건 유지 |

---

## 8. Testing Checklist

### 8.1 기능 테스트
- [ ] BM25 코퍼스 생성 (build_bm25_corpus.py)
- [ ] BM25 검색: "근로기준법 제60조" → 정확한 문서 반환
- [ ] RRF 결합: Dense + BM25 결과 병합 검증
- [ ] search_hybrid(): BM25 미사용 시 Dense-only 폴백
- [ ] classify_complexity(): SIMPLE/MODERATE/COMPLEX 분류 정확도
- [ ] Adaptive top_k: SIMPLE(8) / MODERATE(15) / COMPLEX(20)
- [ ] Self-RAG: 무관 문서 필터링 동작
- [ ] Self-RAG: min_hits 보장 (최소 2건)
- [ ] Self-RAG: 타임아웃 시 기존 결과 유지

### 8.2 회귀 테스트
- [ ] 기존 채팅 SSE 스트리밍 정상
- [ ] 기존 임금계산기 정상
- [ ] 기존 괴롭힘 평가 정상
- [ ] BM25 미설치 환경에서 정상 동작 (Vercel)

### 8.3 벤치마크
- [ ] Precision@5 ≥ 80% (30개 질문)
- [ ] 환각 판례 ≤ 5%
- [ ] 응답 지연 P95 ≤ 10초

---

## 9. Configuration

### 9.1 환경 변수 (신규 없음)

기존 환경 변수만 사용. BM25는 로컬 파일 기반.

### 9.2 튜닝 파라미터

| 파라미터 | 위치 | 기본값 | 설명 |
|----------|------|--------|------|
| `RRF_K` | `bm25_search.py` | 60 | RRF 상수 (클수록 순위 평탄화) |
| `alpha` | `search_hybrid()` | 0.5 | Dense 가중치 (0~1) |
| `COMPLEXITY_PARAMS` | `query_decomposer.py` | 위 표 참조 | 복잡도별 검색 파라미터 |
| `JUDGE_TIMEOUT` | `self_rag.py` | 3.0초 | Self-RAG LLM 판정 타임아웃 |
| `MAX_CONCURRENT` | `self_rag.py` | 5 | Self-RAG 병렬 판정 수 |
| `min_hits` | `filter_by_relevance()` | 2 | Self-RAG 최소 보장 건수 |
