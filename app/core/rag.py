"""Pinecone 벡터 검색 모듈 — 멀티 네임스페이스 (laborlaw-v2 + counsel)

판례·행정해석·노무사 상담을 Pinecone에서 먼저 검색하고,
결과가 부족하면 법제처 API(legal_api.py)로 폴백한다.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

NAMESPACES = ["laborlaw-v2", "counsel", "qa"]
TOP_K = 5
MIN_SCORE = 0.35  # 이 점수 이하는 무관한 결과로 간주


def search_pinecone(
    query: str,
    config: "AppConfig",
    top_k: int = TOP_K,
    source_type: str | None = None,
) -> list[dict]:
    """Pinecone 멀티 네임스페이스 벡터 검색.

    Args:
        query: 검색 쿼리 텍스트
        config: AppConfig (openai_client, pinecone_index)
        top_k: 최대 반환 건수
        source_type: 필터 ("precedent", "interpretation", "counsel" 등). None이면 전체.

    Returns:
        [{score, title, section, content, source_type, id}, ...]
    """
    try:
        # 쿼리 임베딩 (1회만)
        resp = config.openai_client.embeddings.create(
            model=config.embed_model,
            input=query,
        )
        vector = resp.data[0].embedding

        # 멀티 네임스페이스 검색
        all_hits = []
        seen_ids: set[str] = set()

        for ns in NAMESPACES:
            kwargs = {
                "vector": vector,
                "top_k": top_k,
                "namespace": ns,
                "include_metadata": True,
            }
            if source_type:
                kwargs["filter"] = {"source_type": {"$eq": source_type}}

            try:
                result = config.pinecone_index.query(**kwargs)
                for m in result.matches:
                    if m.score < MIN_SCORE or m.id in seen_ids:
                        continue
                    seen_ids.add(m.id)
                    meta = m.metadata or {}
                    all_hits.append({
                        "score": round(m.score, 4),
                        "title": meta.get("title", ""),
                        "section": meta.get("section", ""),
                        "content": meta.get("text", ""),
                        "source_type": meta.get("source_type", ""),
                        "id": m.id,
                    })
            except Exception as e:
                logger.warning("Pinecone ns=%s 검색 실패: %s", ns, e)

        # score 내림차순 정렬 후 top_k 반환
        all_hits.sort(key=lambda x: x["score"], reverse=True)
        hits = all_hits[:top_k]

        logger.info("Pinecone 검색: query=%r, source=%s, %d건 (ns=%s, ≥%.2f)",
                     query[:40], source_type or "all", len(hits),
                     "+".join(NAMESPACES), MIN_SCORE)
        return hits

    except Exception as e:
        logger.warning("Pinecone 검색 실패: %s", e)
        return []


def search_pinecone_multi(
    queries: list[str],
    config: "AppConfig",
    top_k: int = TOP_K,
    source_type: str | None = None,
) -> list[dict]:
    """복수 쿼리로 Pinecone 병렬 검색 → 중복 제거.

    Args:
        queries: 검색 쿼리 리스트
        config: AppConfig
        top_k: 쿼리당 최대 건수
        source_type: 필터 (None이면 전체)

    Returns:
        중복 제거된 결과 리스트 (score 내림차순)
    """
    if not queries:
        return []

    seen_ids: set[str] = set()
    all_hits: list[dict] = []

    def _search_one(q: str) -> list[dict]:
        return search_pinecone(q, config, top_k=top_k, source_type=source_type)

    with ThreadPoolExecutor(max_workers=min(len(queries), 3)) as pool:
        futures = {pool.submit(_search_one, q): q for q in queries}
        for fut in as_completed(futures):
            try:
                hits = fut.result()
                for h in hits:
                    if h["id"] not in seen_ids:
                        seen_ids.add(h["id"])
                        all_hits.append(h)
            except Exception as e:
                logger.warning("Pinecone 다중검색 개별 실패: %s", e)

    # score 내림차순 정렬
    all_hits.sort(key=lambda x: x["score"], reverse=True)
    logger.info("Pinecone 다중검색: %d개 쿼리 → %d건 (중복제거)",
                len(queries), len(all_hits))
    return all_hits[:top_k * 2]  # 최대 top_k*2건


RERANK_MODEL = "rerank-v3.5"
RERANK_TOP_N = 5


def rerank_results(
    query: str,
    hits: list[dict],
    cohere_api_key: str,
    top_n: int = RERANK_TOP_N,
) -> list[dict]:
    """Cohere Rerank로 검색 결과 재정렬.

    Args:
        query: 원본 사용자 질문 (rerank 기준)
        hits: Pinecone 검색 결과 리스트
        cohere_api_key: Cohere API 키
        top_n: 반환할 상위 결과 수

    Returns:
        재정렬된 상위 top_n건. 실패 시 원본 hits[:top_n] 반환.
    """
    if not hits or not cohere_api_key:
        return hits[:top_n]

    try:
        import cohere

        co = cohere.ClientV2(api_key=cohere_api_key)

        # Rerank용 문서 텍스트 추출
        documents = []
        for h in hits:
            text = ""
            if h.get("title"):
                text += h["title"] + " "
            if h.get("section"):
                text += h["section"] + " "
            if h.get("content"):
                text += h["content"]
            documents.append(text.strip() or "(empty)")

        result = co.rerank(
            model=RERANK_MODEL,
            query=query,
            documents=documents,
            top_n=min(top_n, len(hits)),
        )

        # 재정렬된 인덱스로 hits 재구성
        reranked = []
        for item in result.results:
            hit = hits[item.index].copy()
            hit["rerank_score"] = round(item.relevance_score, 4)
            reranked.append(hit)

        logger.info(
            "Rerank 완료: %d건 → %d건 (model=%s)",
            len(hits), len(reranked), RERANK_MODEL,
        )
        return reranked

    except Exception as e:
        logger.warning("Rerank 실패, cosine 정렬 폴백: %s", e)
        return hits[:top_n]


def format_pinecone_hits(hits: list[dict]) -> tuple[str | None, list[dict]]:
    """Pinecone 검색 결과를 LLM 컨텍스트 텍스트 + 메타 리스트로 변환.

    Returns:
        (formatted_text, meta_list)
        - formatted_text: LLM에 제공할 포매팅된 텍스트 (없으면 None)
        - meta_list: [{title, section, source_type, score}, ...]
    """
    if not hits:
        return None, []

    parts = []
    meta_list = []
    for h in hits:
        source_label = {
            "precedent": "판례",
            "interpretation": "행정해석",
            "regulation": "훈령/예규",
            "counsel": "노무사 상담",
            "qa": "상담 Q&A",
        }.get(h["source_type"], h["source_type"])

        header = f"[{source_label}] {h['title']}"
        if h.get("section"):
            header += f" — {h['section']}"

        content = h.get("content", "")
        if content:
            parts.append(f"{header}\n{content}")
            meta_list.append({
                "title": h["title"],
                "section": h.get("section", ""),
                "source_type": h["source_type"],
                "score": h["score"],
            })

    if not parts:
        return None, []

    formatted = "\n\n---\n\n".join(parts)
    return formatted, meta_list
