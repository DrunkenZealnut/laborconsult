"""Pinecone 벡터 검색 모듈 — 2그룹 병렬 검색

그룹 A: laborlaw-v2 (판례·행정해석·훈령)
그룹 B: counsel + qa (상담사례)
두 그룹을 병렬로 검색하여 응답 속도를 개선한다.
결과가 부족하면 법제처 API(legal_api.py)로 폴백한다.
"""

from __future__ import annotations

import re
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# 병렬 검색 그룹 정의
NS_GROUP_LAW = ["laborlaw-v2"]          # 그룹 A: 법령·판례
NS_GROUP_COUNSEL = ["counsel", "qa"]    # 그룹 B: 상담사례
NS_GROUPS = [NS_GROUP_LAW, NS_GROUP_COUNSEL]
TOP_K = 5
MIN_SCORE = 0.35  # 이 점수 이하는 무관한 결과로 간주

# 인덱스/네임스페이스 오배선 경고 — 인스턴스당 1회만 (DB-3 관측성)
_zero_hit_warned = False


def _query_namespaces(
    namespaces: list[str],
    vector: list[float],
    top_k: int,
    source_type: str | None,
    pinecone_index,
) -> list[dict]:
    """네임스페이스 그룹 내 순차 검색 → 결과 병합."""
    hits = []
    seen_ids: set[str] = set()

    for ns in namespaces:
        kwargs = {
            "vector": vector,
            "top_k": top_k,
            "namespace": ns,
            "include_metadata": True,
        }
        if source_type:
            kwargs["filter"] = {"source_type": {"$eq": source_type}}

        try:
            result = pinecone_index.query(**kwargs)
            for m in result.matches:
                if m.score < MIN_SCORE or m.id in seen_ids:
                    continue
                seen_ids.add(m.id)
                meta = m.metadata or {}
                hits.append({
                    "score": round(m.score, 4),
                    "title": meta.get("title", ""),
                    "section": meta.get("section", ""),
                    "content": meta.get("text", ""),
                    "source_type": meta.get("source_type", ""),
                    "book_id": meta.get("book_id", ""),   # 해설서 인용 가드(G4) 키
                    "id": m.id,
                })
        except Exception as e:
            logger.warning("Pinecone ns=%s 검색 실패: %s", ns, e)

    return hits


def search_pinecone(
    query: str,
    config: "AppConfig",
    top_k: int = TOP_K,
    source_type: str | None = None,
) -> list[dict]:
    """Pinecone 2그룹 병렬 벡터 검색.

    그룹 A (laborlaw-v2)와 그룹 B (counsel+qa)를 병렬로 검색한 뒤
    결과를 합치고 score 내림차순으로 정렬한다.

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

        # 2그룹 병렬 검색
        all_hits = []

        with ThreadPoolExecutor(max_workers=len(NS_GROUPS)) as pool:
            futures = {
                pool.submit(
                    _query_namespaces, group, vector, top_k, source_type,
                    config.pinecone_index,
                ): group
                for group in NS_GROUPS
            }
            for fut in as_completed(futures):
                group = futures[fut]
                try:
                    all_hits.extend(fut.result())
                except Exception as e:
                    logger.warning("Pinecone 그룹 %s 검색 실패: %s", group, e)

        # 그룹 간 ID 중복 제거
        seen_ids: set[str] = set()
        deduped = []
        for h in all_hits:
            if h["id"] not in seen_ids:
                seen_ids.add(h["id"])
                deduped.append(h)

        # score 내림차순 정렬 후 top_k 반환
        deduped.sort(key=lambda x: x["score"], reverse=True)
        hits = deduped[:top_k]

        all_ns = [ns for g in NS_GROUPS for ns in g]
        logger.info("Pinecone 검색: query=%r, source=%s, %d건 (ns=%s, ≥%.2f)",
                     query[:40], source_type or "all", len(hits),
                     "+".join(all_ns), MIN_SCORE)
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

    # 인덱스/네임스페이스 오배선 조기 감지 (DB-3 관측성) — 인스턴스당 최초 1회만 경고
    global _zero_hit_warned
    if not all_hits and not _zero_hit_warned:
        _zero_hit_warned = True
        from app.config import resolve_index_name
        logger.warning("RAG 검색 결과 0건 — 인덱스/네임스페이스 오배선 가능성 확인 필요 "
                       "(index=%s, ns_groups=%s)", resolve_index_name(), NS_GROUPS)

    logger.info("Pinecone 다중검색: %d개 쿼리 → %d건 (중복제거)",
                len(queries), len(all_hits))
    return all_hits[:top_k * 2]  # 최대 top_k*2건


def search_hybrid(
    queries: list[str],
    config: "AppConfig",
    top_k: int = TOP_K,
    source_type: str | None = None,
    alpha: float = 0.5,
) -> list[dict]:
    """Hybrid Search: Dense (Pinecone) + Sparse (BM25) → RRF 결합.

    BM25 미사용 시 (rank_bm25 미설치 / 코퍼스 미존재) Dense-only 폴백.

    Args:
        queries: 검색 쿼리 리스트
        config: AppConfig
        top_k: 최대 반환 건수
        source_type: 필터 (None이면 전체)
        alpha: Dense 가중치 (0.0=BM25 only, 1.0=Dense only, 0.5=균등)

    Returns:
        RRF 결합된 검색 결과 (또는 Dense-only 폴백)
    """
    # Dense 검색
    dense_hits = search_pinecone_multi(queries, config, top_k=top_k, source_type=source_type)

    # BM25 검색 시도
    try:
        from app.core.bm25_search import (
            search_bm25, reciprocal_rank_fusion, load_bm25_corpus,
            rrf_merge_ranked_lists,
        )

        load_bm25_corpus()
        # 쿼리별 검색 후 순위 병합 — 단일 문자열 결합의 분해 이점 상실 방지 (DB-8)
        per_query = [search_bm25(q, top_k=top_k) for q in queries[:3]]
        bm25_hits = rrf_merge_ranked_lists(per_query, top_k=top_k)

        if bm25_hits:
            fused = reciprocal_rank_fusion(dense_hits, bm25_hits, alpha=alpha, top_k=top_k)
            return fused
    except Exception as e:
        logger.info("BM25 unavailable, Dense-only: %s", e)

    return dense_hits


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


MAX_CHUNKS_PER_BOOK = 3

# 답변 1건에 실리는 해설서 청크의 **총량** 상한(G4-T).
#
# 권당 상한만 두면 구조적 상한이 `MAX_CHUNKS_PER_BOOK × 서적 수`로 서적 등록에
# 따라 커진다. 코퍼스 확장은 저작권 검토를 다시 받지 않으므로, 노출량이 아무도
# 모르게 늘어나는 경로가 된다.
#
# 실제 천장은 `min(rerank_top_n, 3 × 서적수)`라 '권당 3씩 선형 증가'는 아니다 —
# 서적수 1·2·3·4·5에서 SIMPLE 3/3/3/3/3, MODERATE 3/5/5/5/5, COMPLEX 3/6/7/7/7,
# Self-RAG wider 3/6/9/10/10으로 rerank_top_n에 막혀 4권에서 포화한다. 그래서
# 이 상한은 SIMPLE·MODERATE에서는 발동하지 않는다.
#
# ⚠️ 위 표는 **rerank 직후** 기준이고, 이 함수가 실제로 받는 입력은 그 뒤에
# Self-RAG 필터(pipeline.py ③ filter_by_relevance)를 한 번 더 통과한 결과다.
# COMPLEX는 self_rag=True라 입력이 rerank_top_n보다 작아진다 — 실측 7→6·7→5
# (2026-08-18 프리뷰). 그래서 3권 체제 COMPLEX 자연 질의에서는 이 상한이
# 발동하지 않았고(4회 시도 전부 미도달, 최대가 G4의 gaebyeol 4→3), 발동이
# 남는 경로는 Self-RAG를 **재적용하지 않는** wider(pipeline.py:1642,
# rerank_top_n+3=10 → 3권이면 9→6)와 Cohere 미설정 폴백(rerank 자체가 없어
# 수십 건이 그대로 들어온다)이다.
#
# 상한의 실동작 자체는 실코퍼스 벡터로 확인했다(3권×4건=12 → G4가 9 → 이
# 상한이 6). 발동이 드문 것은 상한이 헐거워서가 아니라 앞단이 이미 좁아서이며,
# 서적이 늘거나 rerank_top_n이 오르면 그 여유는 사라진다.
#
# ⚠️ **노출을 실제로 지배하는 값은 query_decomposer.py의 rerank_top_n이다.**
# 그 모듈에는 저작권 표시가 없으므로, 누가 recall을 위해 COMPLEX를 7→20으로
# 올리면 매 답변이 이 상한(6)까지 차오르는데 리뷰 신호가 없다. rerank_top_n을
# 만질 때 이 상수를 함께 볼 것.
#
# 6은 임의 값이 아니라 **2권 체제의 실효 최댓값**이다 — 저작권 검토를 통과한
# 실적이 있는 유일한 수치다(textbook-corpus-embedding 사이클). 서적이 몇 권이
# 되든 이 값은 변하지 않으며, 늘리려면 상수를 고쳐야 하고 그 순간이 검토
# 시점이 된다.
#
# 이 값은 "비해설서 출처가 최소 1건 실린다"를 보장하지 않는다. rerank 결과가
# 전부 해설서면 컨텍스트도 전부 해설서다(SIMPLE은 rerank_top_n=3이라 서적이
# 1권일 때도 그랬다). 그런 보장이 필요하면 별도 설계 항목이다.
MAX_TEXTBOOK_CHUNKS = 6

# 해설서 벡터 ID 규약: textbook_{book_id}_{section:04d}_{chunk}
_TEXTBOOK_ID_RE = re.compile(r"^textbook_([a-z0-9]+)_")


def _book_id_of(hit: dict) -> str:
    """hit의 해설서 식별자. 해설서가 아니면 빈 문자열.

    메타데이터의 book_id를 우선하되, 없으면 벡터 ID에서 되뽑는다 — BM25
    코퍼스는 {id,text,title,section,source_type}만 담고 book_id가 없어서,
    BM25로만 올라온 청크는 메타데이터만 믿으면 가드를 그대로 빠져나간다.
    """
    book = (hit.get("book_id") or "").strip()
    if book:
        return book

    m = _TEXTBOOK_ID_RE.match(hit.get("id") or "")
    if m:
        return m.group(1)

    # source_type만 아는 경우 — 서적 구분은 못 해도 상한은 걸어야 안전하다.
    return "_unknown" if hit.get("source_type") == "textbook" else ""


def _cap_by_book(hits: list[dict], limit: int = MAX_CHUNKS_PER_BOOK) -> list[dict]:
    """동일 해설서(book_id)의 청크를 limit개로 제한 — 인용 가드 G4.

    저작물 본문이 연속 구간째로 LLM 컨텍스트에 실려 재생산되는 것을 막는
    구조적 상한이다. 프롬프트 규칙(G1~G3)은 소프트 가드라 이 함수가 유일한
    확정적 통제다.

    해설서가 아닌 소스(판례·행정해석·상담)는 제한하지 않는다.
    rerank 순위는 보존한다.
    """
    counts: dict[str, int] = {}
    capped: list[dict] = []

    for h in hits:
        book = _book_id_of(h)
        if not book:
            capped.append(h)
            continue
        counts[book] = counts.get(book, 0) + 1
        if counts[book] <= limit:
            capped.append(h)

    # 서적별 폐기량은 저작권 가드의 운영 지표라 총량으로 뭉개지 않는다.
    dropped = {b: n - limit for b, n in counts.items() if n > limit}
    if dropped:
        logger.info("해설서 청크 상한(G4) 적용: %s (권당 최대 %d)", dropped, limit)
    return capped


def _cap_textbook_total(hits: list[dict],
                        limit: int = MAX_TEXTBOOK_CHUNKS) -> list[dict]:
    """해설서 청크 **총량**을 limit개로 제한 — 인용 가드 G4-T.

    _cap_by_book(권당)을 대체하지 않고 덧씌운다. 총량만 두면 한 권이 슬롯을
    독점해 "한 책을 연속 구간째로 재생산"하는 원래 위험이 돌아온다.

    비해설서 hit은 세지도, 버리지도 않는다. rerank 순위를 보존하는 순수
    차감이라는 점도 _cap_by_book과 같다 — 상위부터 채우고 초과분만 버린다.
    """
    total = 0
    capped: list[dict] = []
    dropped: dict[str, int] = {}

    for h in hits:
        book = _book_id_of(h)
        if not book:
            capped.append(h)
            continue
        if total < limit:
            total += 1
            capped.append(h)
        else:
            dropped[book] = dropped.get(book, 0) + 1

    if dropped:
        logger.info("해설서 총량 상한(G4-T) 적용: %s (답변당 최대 %d)",
                    dropped, limit)
    return capped


def format_pinecone_hits(hits: list[dict]) -> tuple[str | None, list[dict]]:
    """Pinecone 검색 결과를 LLM 컨텍스트 텍스트 + 메타 리스트로 변환.

    인용 가드 G4가 여기서 적용되므로 **출력 건수가 입력보다 적을 수 있다** —
    동일 해설서 청크는 최대 3건(G4), 해설서 전체는 최대 6건(G4-T)까지만
    통과한다.

    Returns:
        (formatted_text, meta_list)
        - formatted_text: LLM에 제공할 포매팅된 텍스트 (없으면 None)
        - meta_list: [{title, section, source_type, score}, ...]
    """
    if not hits:
        return None, []

    # 인용 가드 G4 — 이 함수는 파이프라인의 단일 초크포인트라, 여기서 걸러야
    # 호출부가 늘어나도 가드가 새지 않는다. 컨텍스트에서 빠진 청크는
    # meta_list(인용 화이트리스트)에서도 함께 빠진다.
    #
    # 권당(G4) → 총량(G4-T) 순서. **이 순서를 뒤집지 말 것** — 로그 가독성
    # 문제가 아니라 결과가 달라진다. 역순이면 총량 6슬롯을 상위 한 권이 다
    # 채운 뒤 권당 검사가 그것을 3으로 깎아, 뒤 순위의 다른 책이 자리를 잃은
    # 채로 총 3건만 남는다(예: A×6, B×3 → 정순 6건/2권, 역순 3건/1권).
    # 실측 3만 회 비교에서 정순이 역순보다 작은 경우는 0, 큰 경우는 3,197회다.
    hits = _cap_textbook_total(_cap_by_book(hits))

    parts = []
    meta_list = []
    for h in hits:
        source_label = {
            "precedent": "판례",
            "interpretation": "행정해석",
            "regulation": "훈령/예규",
            "counsel": "노무사 상담",
            "qa": "상담 Q&A",
            "textbook": "노동법 해설서",
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
                "chunk_text": content,   # 인용 목록/검증이 본문에서 판례번호를 파싱하도록 동봉(R-1b)
            })

    if not parts:
        return None, []

    formatted = "\n\n---\n\n".join(parts)
    return formatted, meta_list
