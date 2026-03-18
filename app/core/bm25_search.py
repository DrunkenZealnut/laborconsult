"""BM25 키워드 검색 + Dense 벡터 검색 RRF 결합 모듈

Pinecone Dense 검색에 BM25 키워드 매칭을 결합하여
정확한 법조문 번호/용어 검색 시 recall을 향상시킨다.

- Mecab 형태소 분석기 설치 시 정확한 토큰화 사용
- 미설치 시 정규식 기반 경량 토크나이저 폴백
- Vercel serverless: 글로벌 변수로 cold start 시 1회만 로드
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# ── BM25 인덱스 (글로벌 캐시) ────────────────────────────────────────────

_bm25_index = None       # rank_bm25.BM25Okapi | None
_bm25_corpus = None      # list[dict] — [{id, text, title, section, source_type}, ...]
_bm25_loaded = False

BM25_CORPUS_PATH = Path(__file__).parent.parent.parent / "data" / "bm25_corpus.json"
BM25_MAX_DOCS = 15000    # Vercel 메모리 제한 내 (256MB)


# ── 한국어 토크나이저 ────────────────────────────────────────────────────

_mecab = None
_mecab_checked = False


def _get_mecab():
    """Mecab 인스턴스 lazy loading (1회만 시도)."""
    global _mecab, _mecab_checked
    if _mecab_checked:
        return _mecab
    _mecab_checked = True
    try:
        from konlpy.tag import Mecab
        _mecab = Mecab()
        logger.info("Mecab 형태소 분석기 로드 완료")
    except (ImportError, Exception) as e:
        logger.info("Mecab 미사용 (정규식 폴백): %s", e)
        _mecab = None
    return _mecab


def _tokenize_ko(text: str) -> list[str]:
    """한국어 토크나이저 — Mecab 우선, 미설치 시 정규식 폴백.

    Mecab 사용 시: 명사(NNG,NNP) + 동사어간(VV) + 형용사어간(VA) 추출
    폴백 시: 조사 제거 + 공백 분리
    """
    mecab = _get_mecab()

    if mecab is not None:
        try:
            pos_tags = mecab.pos(text)
            tokens = [
                word for word, tag in pos_tags
                if tag.startswith(("NNG", "NNP", "VV", "VA")) and len(word) >= 2
            ]
            if tokens:
                return tokens
        except Exception:
            pass  # Mecab 실패 → 폴백

    # 정규식 기반 경량 토크나이저 (2글자 조사 우선 매칭)
    text = re.sub(r"(?:에서|부터|까지|에게)(?=\s|$)", "", text)
    text = re.sub(r"[은는이가을를의로도만와과](?=\s|$)", "", text)
    tokens = re.sub(r"[^\w\s]", " ", text).split()
    return [t for t in tokens if len(t) >= 2]


# ── BM25 코퍼스 로드 ─────────────────────────────────────────────────────

def load_bm25_corpus() -> bool:
    """BM25 코퍼스 로드 (서버 시작 시 1회).

    data/bm25_corpus.json 형식:
    [{"id": "...", "text": "...", "title": "...", "section": "...", "source_type": "..."}, ...]

    Returns:
        True if loaded successfully, False otherwise
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

        tokenized = [_tokenize_ko(doc.get("text", "")) for doc in _bm25_corpus]
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


# ── BM25 검색 ────────────────────────────────────────────────────────────

def search_bm25(query: str, top_k: int = 10) -> list[dict]:
    """BM25 키워드 검색.

    Args:
        query: 검색 쿼리 텍스트
        top_k: 최대 반환 건수

    Returns:
        [{id, title, section, content, source_type, score, search_type}, ...]
    """
    if _bm25_index is None or _bm25_corpus is None:
        return []

    tokens = _tokenize_ko(query)
    if not tokens:
        return []

    scores = _bm25_index.get_scores(tokens)

    # 상위 top_k 인덱스 추출 (numpy 없이 순수 Python)
    indexed_scores = [(i, s) for i, s in enumerate(scores) if s > 0]
    indexed_scores.sort(key=lambda x: x[1], reverse=True)
    top_indices = indexed_scores[:top_k]

    results = []
    for idx, score in top_indices:
        doc = _bm25_corpus[idx]
        results.append({
            "id": doc["id"],
            "title": doc.get("title", ""),
            "section": doc.get("section", ""),
            "content": doc.get("text", ""),
            "source_type": doc.get("source_type", ""),
            "score": round(float(score), 4),
            "search_type": "bm25",
        })

    logger.info("BM25 검색: query=%r, %d건", query[:40], len(results))
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

    logger.info(
        "RRF fusion: Dense %d + BM25 %d → %d (alpha=%.1f)",
        len(dense_hits), len(bm25_hits), len(results), alpha,
    )
    return results
