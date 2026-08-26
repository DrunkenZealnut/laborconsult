"""Pinecone 벡터 검색 모듈 — 2그룹 병렬 검색

그룹 A: laborlaw-v2 (판례·행정해석·훈령)
그룹 B: counsel + qa (상담사례)
두 그룹을 병렬로 검색하여 응답 속도를 개선한다.
결과가 부족하면 법제처 API(legal_api.py)로 폴백한다.
"""

from __future__ import annotations

import os
import re
import logging
from collections import Counter
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
    source_type: str | frozenset[str] | set[str] | list[str] | None,
    pinecone_index,
) -> list[dict]:
    """네임스페이스 그룹 내 순차 검색 → 결과 병합.

    source_type은 문자열 1개 또는 **복수 집합**을 받는다 — 공공저작물 쿼터
    (`_fetch_public_hits`)가 판례·행정해석·훈령을 한 번에 조회해야 해서다.
    **문자열이 아닌 것은 전부 복수로 본다** — list를 $eq로 보내면 조용히 0건이다.
    """
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
            # list/tuple도 복수로 받는다 — set만 인식하면 `["a","b"]`가
            # `{"$eq": ["a","b"]}`가 되어 **예외 없이 0건**을 반환한다(외부 리뷰 A-12).
            kwargs["filter"] = (
                {"source_type": {"$eq": source_type}}
                if isinstance(source_type, str)
                else {"source_type": {"$in": sorted(source_type)}}
            )

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
                    # text/chunk_text 이중 폴백 — laborlaw-v2에는 적재 시기에 따라
                    # 두 스키마가 섞여 있다. Contextual Retrieval로 올린 구
                    # 판례·행정해석(`ctx_*`)은 **text 없이 chunk_text만** 갖는다
                    # (실측 2026-08-23). `text`만 읽으면 그 벡터는 content가 빈
                    # 채로 흘러가고, format_pinecone_hits가 조용히 버려 **검색은
                    # 되는데 답변 컨텍스트에는 안 실리는** 상태가 된다 — 법률
                    # 근거가 사라지는 경로였다. build_bm25_corpus.py도 같은 폴백을 쓴다.
                    "content": meta.get("text") or meta.get("chunk_text", ""),
                    "source_type": meta.get("source_type", ""),
                    "book_id": meta.get("book_id", ""),   # 해설서 인용 가드(G4) 키
                    "id": m.id,
                })
        except Exception as e:
            logger.warning("Pinecone ns=%s 검색 실패: %s", ns, e)

    return hits


# ── T1: pool 단계 공공저작물 쿼터 (legal-corpus-coverage) ────────────────────
#
# **병목은 rerank 절단이 아니라 pool 구성이다.** 상담글이 코퍼스의 72%이고
# 구어체라 일상 표현 질의와 임베딩 거리가 가까워, 전역 점수 절단에서 법률
# 문서를 pool 진입 단계부터 밀어낸다 — 실측(2026-08-23, 상담 어휘 12주제):
# **8개 주제가 pool에 공공저작물 0건**이었고, 그 상태에서는 rerank 단계에
# 어떤 배분을 넣어도 공공이 2→3건에서 멈췄다(없는 것은 넣을 수 없다).
#
# 여기서 부족분을 채우면 공공 2→15건·법률 근거 도달 2/12→11/12가 된다.
POOL_PUBLIC_SOURCES = frozenset({"precedent", "interpretation", "regulation"})

# search_top_k → pool에 확보할 공공저작물 목표 건수 (등록값은 pool의 20~25%).
#
# ⚠️ **미등록 top_k가 실제로 발생한다.** Self-RAG wider가 `search_top_k * 2`로
# 재검색하므로(`pipeline.py`) 16·30·40이 들어온다. 폴백이 `top_k // 2`였을 때
# COMPLEX wider(40)에서 쿼터가 **20 = 50%**가 되어, pool 절반이 주입 판례로
# 채워지고 상담은 하한(2건)까지 밀려났다. wider는 Self-RAG를 재적용하지 않으므로
# 그 상태가 그대로 답변에 실린다(외부 리뷰 A-3).
#
# 폴백은 등록값과 같은 비율(1/4)에 **상한 6**을 둔다. 상한이 필요한 이유:
# 비율만 두면 top_k가 커질수록 주입분이 선형으로 늘어 "rerank가 걸러낸다"는
# 완화책이 성립하지 않는다(pool의 절반이 주입분이면 rerank가 고를 대안이 없다).
POOL_PUBLIC_QUOTA = {8: 2, 15: 3, 20: 4}
POOL_PUBLIC_QUOTA_CAP = 6

# 상담이 이 수 미만으로 줄지 않는다 — 상담 우위 질문("내 상황과 비슷한 사례")의
# 실용성을 지킨다. 목적이 법률 근거 확보이지 상담 제거가 아니다.
MIN_COUNSEL_IN_POOL = 2


def _pool_public_quota(top_k: int) -> int:
    if top_k in POOL_PUBLIC_QUOTA:
        return POOL_PUBLIC_QUOTA[top_k]
    return min(max(2, top_k // 4), POOL_PUBLIC_QUOTA_CAP)


def _pool_quota_enabled() -> bool:
    """T1 킬스위치 — LEGAL_POOL_QUOTA=off일 때만 끈다.

    TEXTBOOK_PROMOTE·LEGAL_PROMOTE와 같은 재배포-반영 의미론.

    ⚠️ **이 스위치는 같은 사이클 변경의 일부만 되돌린다**(Check 리뷰 A-7).
    끄는 것: 공공 쿼터 1단·2단.
    끄지 못하는 것:
      · `_query_namespaces`의 `text`/`chunk_text` content 폴백 — legacy `ctx_*`
        약 9,088벡터가 컨텍스트 후보로 새로 들어온 상태가 유지된다(rerank 입력
        문서가 달라지므로 **랭킹 자체가 변경 전과 다르다**)
      · 상담 총량 상한(Q4) · `COUNSEL_CITATION_RULES` 접미 · 게시판 제외(Q6)
    즉 `off`는 "쿼터 이전"으로 되돌리지만 "이 사이클 이전"으로는 못 되돌린다.
    전체 롤백이 필요하면 커밋 되돌리기가 유일한 수단이다.
    """
    return os.getenv("LEGAL_POOL_QUOTA", "on").strip().lower() != "off"


def _is_public_source(hit: dict) -> bool:
    return hit.get("source_type") in POOL_PUBLIC_SOURCES


def _fetch_public_hits(query: str, config: "AppConfig", want: int) -> list[dict]:
    """공공저작물 전용 조회 — 쿼터를 채울 후보를 가져온다.

    별도 조회가 필요한 이유: laborlaw-v2 일반 조회에 공공이 몇 건 들어올지는
    운이고, 실측상 12주제 중 8개가 0건이었다. 없는 것은 배분할 수 없다.

    임베딩 1회 + Pinecone 1회를 쓴다. `search_hybrid`가 다중 쿼리를 받아도
    **원문 쿼리 하나로만** 조회한다 — 분해 쿼리마다 부르면 비용이 쿼리 수만큼
    늘고, 쿼터는 pool 전체에 대한 하한이라 한 번이면 충분하다.
    """
    try:
        resp = config.openai_client.with_options(
            timeout=10.0, max_retries=0,
        ).embeddings.create(model=config.embed_model, input=query)
        return _query_namespaces(
            NS_GROUP_LAW, resp.data[0].embedding, want,
            POOL_PUBLIC_SOURCES, config.pinecone_index,
        )
    except Exception as e:
        # 쿼터 조회 실패는 검색 실패가 아니다 — 기존 결과로 진행한다.
        logger.warning("공공저작물 쿼터 조회 실패: %s", e)
        return []


def _apply_public_quota(hits: list[dict], public_hits: list[dict],
                        top_k: int) -> list[dict]:
    """pool의 공공저작물이 쿼터 미만이면 부족분만 상담과 **교체**한다.

    지켜야 할 것 넷(전부 회귀 T26이 고정):
      · **교체이지 증량이 아니다** — pool 크기가 불변이라 Cohere rerank 입력
        건수가 그대로다. 과금·지연 불변이 이 설계의 성립 전제다.
      · **victim은 상담(qa/counsel)만** — 해설서를 밀어내면 저작권 노출은
        줄지만 eval_retrieval의 도달률 75%가 회귀한다(T1-b: 해설서 불변).
      · **상담을 전멸시키지 않는다**(MIN_COUNSEL_IN_POOL).
      · **후보가 없으면 그대로 둔다** — 강제 공백을 만들지 않는다.
    """
    have = sum(1 for h in hits if _is_public_source(h))
    quota = _pool_public_quota(top_k)
    if have >= quota or not public_hits:
        return hits

    merged = list(hits)
    seen = {h["id"] for h in merged}
    added = 0
    for cand in public_hits:
        if have + added >= quota:
            break
        if cand["id"] in seen:
            continue
        victims = [i for i, h in enumerate(merged) if is_counsel_source(h)]
        if len(victims) <= MIN_COUNSEL_IN_POOL:
            break
        merged.pop(victims[-1])       # 점수 최하위 상담부터
        # 주입 표식 — rerank가 이 후보를 top_n 밖으로 밀어냈을 때 2단 보장
        # (_ensure_public_quota)이 되돌릴 대상을 식별하는 근거다. 실측상
        # 1단만으로는 최종 컨텍스트에 반영되지 않았다(pool 3건 → 최종 0건).
        merged.append(dict(cand, quota_injected=True))
        seen.add(cand["id"])
        added += 1

    if added:
        logger.info("공공저작물 pool 쿼터: %d건 주입 (기존 %d → %d/%d)",
                    added, have, have + added, quota)
    return merged


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
        # 국소 타임아웃 — 클라이언트 기본(600s×2회)은 임베딩에 과하다. 의도분석
        # 실패 폴백(2벤더 장애 중)에서도 이 호출이 열리므로, 행(hang) 열화 시
        # 프론트 idle(60s) 안에 실패로 떨어져야 한다(분석 P1-4). with_options는
        # 요청 단위라 답변 LLM 등 다른 OpenAI 경로에 영향이 없다.
        resp = config.openai_client.with_options(
            timeout=10.0, max_retries=0,
        ).embeddings.create(
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
            return _with_public_quota(queries, fused, config, top_k, source_type)
    except Exception as e:
        logger.info("BM25 unavailable, Dense-only: %s", e)

    return _with_public_quota(queries, dense_hits, config, top_k, source_type)


def _with_public_quota(queries: list[str], hits: list[dict], config: "AppConfig",
                       top_k: int, source_type: str | None) -> list[dict]:
    """T1 공공저작물 쿼터 — **파이프라인이 실제로 받는 pool**에 적용한다.

    적용 계층이 중요하다. 처음에 `search_pinecone` 안에 넣었더니 효과가
    시뮬레이션(공공 15건)의 1/3(5건)에 그쳤다 — 그 뒤로 `search_pinecone_multi`의
    재정렬·절단과 RRF 병합·절단이 **두 번 더** 있어 쿼터로 넣은 공공이 다시
    상담 점수에 밀려 잘려나갔기 때문이다(상담이 점수에서 이기는 것이 애초의
    문제다). 여기가 마지막 절단 뒤라 희석되지 않는다.

    `source_type` 지정 조회(특정 소스만 찾는 호출)는 대상이 아니다 — 이미
    원하는 소스로 좁혀져 있어 쿼터가 의미 없고, 넣으면 필터를 깬다.
    """
    if source_type is not None or not _pool_quota_enabled() or not hits:
        return hits
    quota = _pool_public_quota(top_k)
    if sum(1 for h in hits if _is_public_source(h)) >= quota:
        return hits          # 이미 충족 — 조회 비용을 쓰지 않는다
    public_hits = _fetch_public_hits(queries[0], config, quota * 2)
    if not public_hits:
        return hits
    public_hits.sort(key=lambda x: x["score"], reverse=True)
    return _apply_public_quota(hits, public_hits, top_k)


RERANK_MODEL = "rerank-v3.5"
RERANK_TOP_N = 5

# 다양성 승격의 후보 탐색 창 — 전체 랭킹의 top_n ~ FACTOR*top_n 구간에서만
# 해설서를 끌어올린다. 절대 점수 하한을 쓰지 않는 이유: hits의 score는
# Dense(cosine 0.5~0.65)와 BM25(10~30)가 혼재해 스케일이 없고, rerank_score는
# Cohere 성공 경로에만 붙는다. 랭크는 세 exit(성공·무키·예외) 모두에서 동일하게
# 정의되는 유일한 기준이다(설계 §2.3·D-3).
TEXTBOOK_PROMOTE_WINDOW_FACTOR = 2


def _textbook_promote_enabled() -> bool:
    """다양성 승격 킬스위치 — TEXTBOOK_PROMOTE=off일 때만 끈다.

    코드 변경 없는 운영 롤백 수단(ANSWER_PROVIDER와 같은 의미론 — Vercel에서는
    env 변경 후 재배포 시 반영). 알 수 없는 값은 on으로 취급한다.
    """
    return os.getenv("TEXTBOOK_PROMOTE", "on").strip().lower() != "off"


def _legal_promote_enabled() -> bool:
    """법률근거 승격 킬스위치 — LEGAL_PROMOTE=off일 때만 끈다(TEXTBOOK_PROMOTE와
    동일한 재배포-반영 의미론)."""
    return os.getenv("LEGAL_PROMOTE", "on").strip().lower() != "off"


# 법률근거 승격의 대상 — 공공 저작물(저작권법 제7조 비보호) 소스만.
# **textbook을 절대 넣지 말 것** — 해설서 노출 증가는 저작권 재검토 대상이다
# (colloquial-legal-mapping design §6).
#
# POOL_PUBLIC_SOURCES와 **같은 객체**다(별도 frozenset을 만들지 않는다). 두 벌로
# 두면 소스를 추가할 때 한쪽만 갱신돼 I-9 보호(_diversity_class_of)와 T1 쿼터가
# 다른 집합을 보게 되는데, **총량이 불변이라 어떤 메트릭에도 안 잡힌다**
# (CLAUDE.md가 I-9에 대해 남긴 경고와 같은 실패 모드, 외부 리뷰 A-10).
LEGAL_PROMOTE_SOURCES = POOL_PUBLIC_SOURCES


def _is_legal_source(hit: dict) -> bool:
    return hit.get("source_type") in LEGAL_PROMOTE_SOURCES


def _diversity_class_of(hit: dict):
    """hit이 속한 다양성 클래스 판정 술어. 어느 클래스도 아니면 None.

    두 승격(_ensure_source_presence의 두 호출)의 대상 집합과 정확히 같은
    정의여야 한다 — 어긋나면 I-9가 엉뚱한 것을 보호하거나 놓친다.
    """
    if _book_id_of(hit):
        return _book_id_of
    if _is_legal_source(hit):
        return _is_legal_source
    return None


def _pick_swap_victim(selected: list[dict]) -> int | None:
    """아래에서부터, 같은 source_type이 2건 이상인 첫 hit의 인덱스.

    단일 출처(예: precedent 1건)를 지키기 위해서다 — 다양성을 늘리려고 다른
    소수 출처를 지우면 목적이 자기모순이 된다(설계 D-2·I-4).

    승격으로 들어온 항목(promoted 마커)은 후보에서 제외한다(I-7) — 뒤 승격이
    앞 승격분을 잡아먹으면 적용 순서가 결과를 바꾸는 비결정 구조가 된다.
    비승격 원본이 2건 미만이면 None(I-8) — 교체를 허용하면 승격 연쇄가 원본을
    전멸시켜 100% 승격 컨텍스트가 된다.

    다양성 클래스(해설서·법률근거)의 **마지막 1건**은 I-4 폴백에서도 victim이
    되지 않는다(I-9) — 해설서 승격이 유일한 판례를 지우면 법률근거 승격의
    발동 조건이 새로 생겨, rerank 상위 판례가 랭크 창의 하위 판례로 되메워지는
    강등 순환이 생긴다(분석 P1-3). 자연 유입 해설서를 legal 승격이 지우는
    역방향도 같은 규칙이 막는다.
    """
    candidates = [i for i, h in enumerate(selected) if not h.get("promoted")]
    if len(candidates) < 2:
        return None

    def _last_of_class(i: int) -> bool:
        pred = _diversity_class_of(selected[i])
        return pred is not None and sum(1 for h in selected if pred(h)) == 1

    eligible = [i for i in candidates if not _last_of_class(i)]
    if not eligible:
        return None
    counts = Counter(selected[i].get("source_type") for i in candidates)
    for i in reversed(eligible):
        if counts[selected[i].get("source_type")] >= 2:
            return i
    return eligible[-1]


def _ensure_source_presence(
    selected: list[dict],
    ranked: list[dict],
    top_n: int,
    is_target,
    label: str,
) -> list[dict]:
    """selected에 대상 소스가 0건이면 랭크 창의 최상위 후보 1건을 승격(교체).

    해설서·법률근거 두 승격의 공용 몸체 — 불변식 I-1~I-8은 여기 한 곳에만
    구현된다. 다양성 보장이지 저작권 가드가 아니다 — G4/G4-T는 이 결과에
    format_pinecone_hits가 그대로 적용한다(승격 → 가드 순서 불변, I-5).
    교체라 총 건수가 불변이고(I-1), 승격 후보는 말미에 붙인다 — 재랭커 기준
    selected 전원보다 약한 문서이므로 순위를 속이지 않는다.

    Args:
        selected: 현재 상위 목록(앞선 승격이 반영된 상태일 수 있음)
        ranked: 전체 랭킹 — 후보 창(top_n ~ FACTOR*top_n)의 근거
        is_target: 승격 대상 판정 술어
        label: promoted 마커 값("textbook"|"legal") — eval·로그가 이 키로
            발동을 구분 계측한다. 회귀는 test_precedent_ingest.py T23·T24.
    """
    if len(selected) < 2:
        # 교체가 곧 100% 치환이 되는 크기 — 승격하지 않는다(I-6).
        return selected
    if any(is_target(h) for h in selected):
        return selected

    window = ranked[top_n: top_n * TEXTBOOK_PROMOTE_WINDOW_FACTOR]
    candidate = next((h for h in window if is_target(h)), None)
    if candidate is None:
        return selected

    victim_idx = _pick_swap_victim(selected)
    if victim_idx is None:
        return selected
    # promoted 마커는 계측의 구조적 계약이다 — eval 스크립트가 이 키로
    # 발동을 센다(로그 문자열·레벨에 의존하면 문구 수정만으로 계측이 조용히
    # 0이 되고, 그 0은 "승격이 효과 없음"이라는 그럴듯한 오답으로 읽힌다).
    # dict 사본을 만드는 이유: exit-A/C에서 candidate는 호출자 hits의 원본이다.
    promoted = (selected[:victim_idx] + selected[victim_idx + 1:]
                + [dict(candidate, promoted=label)])
    logger.info("%s 다양성 승격: %s (교체: %s, top_n=%d)",
                "해설서" if label == "textbook" else "법률근거",
                candidate.get("id"), selected[victim_idx].get("source_type"), top_n)
    return promoted


def _ensure_public_quota(selected: list[dict], ranked: list[dict],
                         top_n: int) -> list[dict]:
    """최종 top_n에 공공저작물 쿼터를 보장한다 — T1의 **2단**.

    1단(`_apply_public_quota`, pool 단계)만으로는 부족하다는 것이 실측으로
    드러났다: pool에 공공 3건을 넣어도 rerank가 전부 top_n 밖으로 밀어내
    최종 컨텍스트는 0건이었다. 상담글이 구어체 질의와 임베딩·재랭킹 양쪽에서
    가까운 것이 애초의 문제라, pool에 넣는 것만으로는 해결되지 않는다.

    기존 legal 승격(`_ensure_source_presence`)과 다른 점 둘:
      · **여러 건**을 보장한다(승격은 "0건이면 1건").
      · **랭크 창을 쓰지 않는다.** 창(top_n~2·top_n)은 "너무 낮은 것을 끌어올리지
        않는다"는 품질 가드인데, 여기 대상은 `quota_injected` 표식이 붙은 것으로
        한정된다 — 공공 전용 조회에서 상위로 뽑힌 문서라 품질 근거가 이미 있다.
        표식 없는 자연 유입 공공은 대상이 아니다(그건 rerank 판단을 존중한다).

    victim 규칙은 상담 한정 + 하한 유지로 `_apply_public_quota`와 같다.
    """
    quota = _pool_public_quota_for_top_n(top_n)
    have = sum(1 for h in selected if _is_public_source(h))
    if have >= quota:
        return selected

    chosen = {h["id"] for h in selected}
    candidates = [h for h in ranked
                  if h.get("quota_injected") and h["id"] not in chosen]
    if not candidates:
        return selected

    result = list(selected)
    added = 0
    for cand in candidates:
        if have + added >= quota:
            break
        victims = [i for i, h in enumerate(result)
                   if is_counsel_source(h)
                   and not h.get("promoted") and not h.get("quota_injected")]
        # 하한은 1단(`_apply_public_quota`)과 **같은 값**이어야 한다 — `< 2`로
        # 두면 교체 후 상담이 1건까지 줄어 "상담이 2건 미만으로 줄지 않는다"는
        # 불변식이 2단에서만 깨진다(외부 리뷰 A-11).
        if len(victims) <= MIN_COUNSEL_IN_POOL:
            break
        result.pop(victims[-1])
        result.append(dict(cand, promoted="public-quota"))
        added += 1

    if added:
        logger.info("공공저작물 쿼터 보장(2단): %d건 승격 (%d → %d/%d, top_n=%d)",
                    added, have, have + added, quota, top_n)
    return result


def _pool_public_quota_for_top_n(top_n: int) -> int:
    """최종 top_n 기준 공공 목표 건수.

    pool 쿼터(`POOL_PUBLIC_QUOTA`, search_top_k 기준)와 다른 축이다 — pool은
    "후보를 확보"하고 여기는 "컨텍스트에 실린다"를 정한다. top_n이 3~7로 작아
    비율이 아니라 고정값으로 둔다. 상담이 최소 2건 남는 범위(§Q4 상한과 정합).
    """
    return 1 if top_n <= 3 else 2


def _ensure_textbook_presence(ranked: list[dict], top_n: int) -> list[dict]:
    """rerank 결과에 해설서가 0건이면 pool의 최상위 해설서 1건을 승격(교체).

    공용 몸체(_ensure_source_presence)에 위임 — 기존 시그니처는 평가 스크립트
    (eval_retrieval.py)와 T23이 소비하므로 유지한다.
    """
    return _ensure_source_presence(
        ranked[:top_n], ranked, top_n,
        lambda h: bool(_book_id_of(h)), "textbook",
    )


def rerank_results(
    query: str,
    hits: list[dict],
    cohere_api_key: str,
    top_n: int = RERANK_TOP_N,
    ensure_textbook: bool = True,
) -> list[dict]:
    """Cohere Rerank로 검색 결과 재정렬 + 해설서 다양성 승격.

    Args:
        query: 원본 사용자 질문 (rerank 기준)
        hits: Pinecone 검색 결과 리스트
        cohere_api_key: Cohere API 키
        top_n: 반환할 상위 결과 수
        ensure_textbook: 다양성 승격(해설서·법률근거 모두) 적용 여부. False는
            평가 스크립트의 기준선(A/B) 측정 전용 — 파이프라인은 기본값을 쓴다.

    Returns:
        재정렬된 상위 top_n건. 실패 시 원본 hits[:top_n] 반환.
        절단이 일어나는 세 exit(성공·무키·예외) 모두에서 승격이 적용된다 —
        파이프라인의 Cohere 무키 경로는 이 함수를 아예 호출하지 않아 절단이
        없으므로 승격도 필요 없다(설계 §2.1).
    """
    def _finalize(ranked: list[dict]) -> list[dict]:
        # 승격 순서: 해설서(기존) → 법률근거(신규). 두 대상 집합이 배타적이라
        # 앞 승격이 뒤 발동 조건을 바꾸지 않는다. 뒤 승격이 앞 승격분을 victim
        # 삼는 것은 _pick_swap_victim의 I-7이 막는다.
        selected = ranked[:top_n]
        # T1 2단 — 해설서 승격보다 **먼저**. 뒤에 두면 해설서 승격분을 victim
        # 후보에서 제외해야 하는 순서 의존이 생긴다. 여기서는 대상이 상담뿐이라
        # 뒤따르는 승격들의 발동 조건(해설서 0건 / 법률 0건)을 바꾸지 않는다
        # — 공공을 넣으면 legal 승격은 자연히 무발동된다(상위 호환).
        if _pool_quota_enabled():
            selected = _ensure_public_quota(selected, ranked, top_n)
        # ensure_textbook은 **다양성 승격 2종만** 끈다(A/B 측정용). 공공 쿼터까지
        # 끄면 eval_retrieval의 기준선 arm이 두 기능을 동시에 끈 상태를 재게 되어
        # 해설서 승격의 순효과가 나오지 않는다(Check 리뷰 A-13).
        if not ensure_textbook:
            return selected
        if _textbook_promote_enabled():
            selected = _ensure_source_presence(
                selected, ranked, top_n, lambda h: bool(_book_id_of(h)), "textbook")
        if _legal_promote_enabled():
            selected = _ensure_source_presence(
                selected, ranked, top_n, _is_legal_source, "legal")
        return selected

    if not hits or not cohere_api_key:
        return _finalize(hits)  # RRF/cosine 순서가 랭킹을 대행

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

        # 전체 랭킹을 요청한다(top_n이 아니라) — 승격 후보(pool 내 최상위
        # 해설서)의 순위를 알아야 랭크 창을 적용할 수 있다. Cohere 과금은
        # search 단위(쿼리+문서셋)라 top_n을 올려도 비용은 같다(설계 §2.2).
        result = co.rerank(
            model=RERANK_MODEL,
            query=query,
            documents=documents,
            top_n=len(documents),
        )

        # 재정렬된 인덱스로 hits 재구성 (전 문서에 rerank_score 부착)
        ranked = []
        for item in result.results:
            hit = hits[item.index].copy()
            hit["rerank_score"] = round(item.relevance_score, 4)
            ranked.append(hit)

        logger.info(
            "Rerank 완료: %d건 → 상위 %d건 (model=%s)",
            len(hits), min(top_n, len(ranked)), RERANK_MODEL,
        )
        return _finalize(ranked)

    except Exception as e:
        logger.warning("Rerank 실패, cosine 정렬 폴백: %s", e)
        return _finalize(hits)


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
# 역방향(해설서 최소 1건)은 _ensure_textbook_presence(다양성 승격)가 담당한다 —
# 그쪽은 상한이 아니라 교체라 이 상한과 충돌하지 않는다(textbook-retrieval-balance).
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


COUNSEL_SOURCES = frozenset({"qa", "counsel"})


def is_counsel_source(hit_or_meta: dict) -> bool:
    """상담 Q&A·노무사 상담 출처인가 — 가드 Q1~Q4·Q6의 공통 판정.

    hit(검색 결과)과 meta(format_pinecone_hits 출력) 양쪽에 쓴다. 두 dict 모두
    `source_type` 키를 갖는다.
    """
    return hit_or_meta.get("source_type") in COUNSEL_SOURCES


def _cap_counsel_total(hits: list[dict], top_n: int | None = None) -> list[dict]:
    """상담 청크 **총량**을 제한 — 인용 가드 Q4.

    상한은 `max(2, top_n - 1)`이다. 해설서 상한(G4-T=6, 고정)과 달리 top_n에
    연동하는 이유: 상담은 본래 다수 노출이 정상인 소스라 낮은 고정값으로
    자르면 SIMPLE(top_n=3)에서 검색 결과가 사실상 비어버린다. 여기서 막으려는
    것은 "상담이 컨텍스트를 **전부** 채우는 것"이지 상담 자체가 아니다.

    **`top_n`을 반드시 넘길 것.** 생략하면 `len(hits)`를 대용하는데, 그 목록은
    이미 `_cap_by_book`·`_cap_textbook_total`이 버린 뒤이고 COMPLEX에서는
    Self-RAG가 더 줄인 상태다. 그러면 상한이 `len-1`이 되어 **상담이 100%일
    때만 1건 제거**되고 비상담이 하나라도 있으면 발동하지 않는다(외부 리뷰 A-5).
    기본값은 구 호출부(평가 스크립트·테스트) 호환용일 뿐이다.

    **대체 투입은 하지 않는다**(순수 차감). 상한의 목적은 "상담이 컨텍스트를
    전부 채우는 것"을 막는 것이고, 비율 조절은 T1 공공 쿼터의 몫이다.

    _cap_by_book/_cap_textbook_total과 같이 rerank 순위를 보존하는 순수 차감이다.
    """
    n = top_n if top_n is not None else len(hits)
    limit = max(2, n - 1)
    total = 0
    capped: list[dict] = []
    dropped = 0

    for h in hits:
        if not is_counsel_source(h):
            capped.append(h)
            continue
        if total < limit:
            total += 1
            capped.append(h)
        else:
            dropped += 1

    if dropped:
        logger.info("상담 총량 상한(Q4) 적용: %d건 제외 (답변당 최대 %d)",
                    dropped, limit)
    return capped


_CONTEXT_JOINER = "\n\n---\n\n"
_JOINER_LEN = len(_CONTEXT_JOINER)


def format_pinecone_hits(hits: list[dict], top_n: int | None = None,
                         max_chars: int | None = None) -> tuple[str | None, list[dict]]:
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
    #
    # 상담 상한(Q4)은 해설서 상한 **뒤**에 적용한다 — 앞에 두면 상담을 깎아
    # 만든 여유를 해설서가 채운 뒤 다시 깎이는 순서 의존이 생긴다. 두 상한의
    # 대상 집합이 배타적이라(해설서 vs qa/counsel) 이 순서에서는 서로의 결과를
    # 바꾸지 않는다.
    hits = _cap_counsel_total(_cap_textbook_total(_cap_by_book(hits)), top_n)

    parts = []
    meta_list = []
    used_chars = 0
    dropped_budget = 0
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
            entry = f"{header}\n{content}"
            # 길이 예산은 **청크 단위**로 자른다. 호출부가 완성된 문자열을
            # 문자 단위로 자르면(`_cap`) meta_list는 그대로 남아, **본문이
            # 잘려 나간 판례를 인용 화이트리스트가 "인용 가능"으로 제시**하고
            # 환각 검증도 그것을 통과시킨다(외부 리뷰 A-9). 여기서 자르면
            # 텍스트와 meta가 항상 정합한다. 순위 순서라 초과 시점에 중단한다.
            if (max_chars is not None and parts
                    and used_chars + len(entry) + _JOINER_LEN > max_chars):
                dropped_budget += 1
                continue
            used_chars += len(entry) + _JOINER_LEN
            parts.append(entry)
            meta_list.append({
                "title": h["title"],
                "section": h.get("section", ""),
                "source_type": h["source_type"],
                "score": h["score"],
                "chunk_text": content,   # 인용 목록/검증이 본문에서 판례번호를 파싱하도록 동봉(R-1b)
            })

    if dropped_budget:
        logger.info("컨텍스트 길이 예산(%d자) 초과로 %d건 제외 — meta도 함께 제외",
                    max_chars, dropped_budget)

    if not parts:
        return None, []

    formatted = _CONTEXT_JOINER.join(parts)
    return formatted, meta_list
