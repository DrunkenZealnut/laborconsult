"""Self-RAG: 검색 결과의 질문 관련성을 LLM이 판정하여 무관 문서 필터링

Cohere Rerank 후 추가 관련성 검증 단계로,
COMPLEX 복잡도 질문에서만 활성화된다.

- Claude Haiku 사용 (저비용, 빠른 응답)
- 병렬 판정으로 지연 최소화 (ThreadPoolExecutor)
- 실패 시 기존 rerank 결과 그대로 사용 (graceful fallback)
"""

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
        answer = resp.content[0].text.strip().lower().rstrip(".")
        return answer == "relevant"

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
