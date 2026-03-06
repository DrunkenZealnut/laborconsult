"""Pinecone 통합 검색 — laborlaw namespace (Q&A + 법령/판례)

laborlaw namespace 메타데이터 구조:
  - content: 청크 전문 (임베딩 텍스트)
  - content_preview: 미리보기
  - document_title: 문서 제목
  - section_title: 섹션 제목
  - filename: 파일명
  - relative_path: 상대 경로
  - source_collection: 'laborlaw'
  - chunk_index, total_chunks, token_count
"""


def _embed_query(query: str, config) -> list[float]:
    resp = config.openai_client.embeddings.create(
        model=config.embed_model,
        input=[query],
    )
    return resp.data[0].embedding


def _search(query_vec: list[float], config, top_k: int, threshold: float) -> list[dict]:
    """Pinecone laborlaw namespace 검색"""
    results = config.pinecone_index.query(
        vector=query_vec,
        top_k=top_k,
        include_metadata=True,
        namespace=config.namespace,
    )
    hits = []
    for match in results.matches:
        if match.score < threshold:
            continue
        md = match.metadata or {}
        hits.append({
            "score": round(match.score, 4),
            "title": md.get("document_title", ""),
            "section": md.get("section_title", ""),
            "content": md.get("content", md.get("content_preview", "")),
            "filename": md.get("filename", ""),
            "path": md.get("relative_path", ""),
            "chunk_index": md.get("chunk_index", 0),
            "total_chunks": md.get("total_chunks", 0),
        })
    return hits


def search_qna(question: str, calculation_type: str | None, config) -> list[dict]:
    """Q&A 검색: 사용자 질문으로 유사 상담 사례 검색"""
    query_vec = _embed_query(question, config)
    return _search(query_vec, config, top_k=config.rag_top_k, threshold=config.rag_threshold)


def search_legal(laws: list[str], legal_basis: list[str], config) -> list[dict]:
    """법령/판례 검색: 법조문 키워드로 Pinecone 검색"""
    if not laws and not legal_basis:
        return []

    query_parts = list(laws[:5]) + list(legal_basis[:5])
    legal_query = " ".join(query_parts)

    query_vec = _embed_query(legal_query, config)
    return _search(query_vec, config, top_k=config.legal_top_k, threshold=config.rag_threshold)
