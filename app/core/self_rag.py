"""Self-RAG: 검색 결과의 질문 관련성을 LLM이 판정하여 무관 문서 필터링

Cohere Rerank 후 추가 관련성 검증 단계로,
COMPLEX 복잡도 질문에서만 활성화된다.

- 관리자 설정 1순위 모델 사용(llm_gateway). 실패한 문서는 관련으로 간주
- 병렬 판정으로 지연 최소화 (ThreadPoolExecutor)
- 실패 시 기존 rerank 결과 그대로 사용 (graceful fallback)
"""

from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.core import llm_gateway

logger = logging.getLogger(__name__)

# 3초는 Haiku 기준이었다. 실측(2026-10-11) gemini-3.8-flash 3.2초·gpt-6-sol 1.2초 — 3초면 Gemini
# 1순위에서 판정이 전부 시간 초과(= 전부 관련)로 필터가 무력해진다.
JUDGE_TIMEOUT = 8.0
# COMPLEX rerank_top_n(7)·wider(10)를 한 번에 판정한다 — 판정 1건이 수 초라 두 차례로 나누면 지연이 배가 된다.
MAX_CONCURRENT = 10

JUDGE_PROMPT = """다음 검색 결과가 사용자 질문에 관련이 있는지 판단하세요.

질문: {query}

검색 결과:
{document}

위 검색 결과가 질문에 직접적으로 관련이 있으면 "relevant", 없으면 "irrelevant"로만 답하세요."""


def judge_relevance(
    query: str,
    document: str,
    config,
) -> bool:
    """단일 문서의 질문 관련성 판정(설정 1순위 모델).

    Returns:
        True = relevant, False = irrelevant
    """
    try:
        answer, _provider = llm_gateway.text(
            config, system=None, purpose="Self-RAG 판정", max_tokens=10,
            timeout=JUDGE_TIMEOUT, attempts=1,
            user=JUDGE_PROMPT.format(query=query, document=document[:1000]),  # 토큰 제한
        )
        # 모델마다 따옴표·마침표·부연을 붙인다("Relevant." 등) — 첫 단어로 판정한다.
        # "irrelevant"는 첫 단어가 달라 걸리지 않는다.
        return re.match(r"[\W_]*relevant\b", answer.strip().lower()) is not None

    except Exception as e:
        logger.debug("Self-RAG judge failed: %s — treating as relevant", e)
        return True  # 실패 시 보수적으로 포함


def filter_by_relevance(
    query: str,
    hits: list[dict],
    config,
    min_hits: int = 2,
) -> tuple[list[dict], bool]:
    """검색 결과를 LLM 관련성 판정으로 필터링.

    Args:
        query: 사용자 질문
        hits: Rerank 후 검색 결과
        config: AppConfig (판정 모델은 설정 1순위)
        min_hits: 최소 보장 건수

    Returns:
        (관련 문서 리스트, needs_wider_search)
        - needs_wider_search: True이면 호출자가 검색 범위를 넓혀야 함
    """
    if len(hits) <= min_hits:
        return hits, False

    start = time.monotonic()

    # 병렬 판정
    filtered = []
    with ThreadPoolExecutor(max_workers=min(MAX_CONCURRENT, len(hits))) as pool:
        futures = {
            pool.submit(
                judge_relevance,
                query,
                f"{hit.get('title', '')} {hit.get('content', '')}",
                config,
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

    # rerank 순서 보존 (as_completed 순서가 비결정적이므로 원본 순위 기준 재정렬)
    filtered.sort(key=lambda h: h.get("rerank_score", h.get("score", 0)), reverse=True)

    elapsed = (time.monotonic() - start) * 1000

    # 결과가 0건이면 검색 범위 확대 트리거
    if len(filtered) == 0:
        logger.warning("Self-RAG: 모든 문서 irrelevant (%.0fms) — wider search 트리거", elapsed)
        return hits[:min_hits], True

    # 최소 보장
    needs_wider = len(filtered) < min_hits
    if needs_wider:
        filtered = hits[:min_hits]

    logger.info("Self-RAG: %d → %d hits (%.0fms)", len(hits), len(filtered), elapsed)
    return filtered, needs_wider
