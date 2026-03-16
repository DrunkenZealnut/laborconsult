"""RAG 멀티쿼리 분해 모듈

사용자 질문을 LLM으로 여러 관점의 검색 쿼리로 분해하여
Pinecone 벡터 검색의 recall을 향상시킨다.
"""

from __future__ import annotations

import json
import logging
import time

import anthropic

logger = logging.getLogger(__name__)

DECOMPOSE_MODEL = "claude-haiku-4-5-20251001"
DECOMPOSE_TIMEOUT = 3.0   # 초 (Haiku 500ms 목표, 여유 포함)
MAX_QUERIES = 4
MIN_QUERY_LENGTH = 15     # 이 길이 미만의 질문은 분해 건너뜀


DECOMPOSE_SYSTEM = """당신은 한국 노동법 전문 검색 어시스턴트입니다.
사용자의 노동법 관련 질문을 벡터 검색에 최적화된 2~4개의 검색 쿼리로 분해하세요.

규칙:
1. 각 쿼리는 질문의 서로 다른 관점이나 하위 주제를 커버해야 합니다.
2. 법률 용어와 일상 용어를 혼합하여 다양한 문서를 검색할 수 있게 하세요.
3. 관련 법조문명이 있으면 쿼리에 포함하세요 (예: "근로기준법 제60조 연차휴가").
4. 각 쿼리는 20~60자 범위로 작성하세요.
5. 원본 질문의 핵심 의도를 반드시 하나 이상의 쿼리에 포함하세요.

JSON 배열로만 응답하세요. 설명 없이 쿼리 문자열 배열만 반환합니다."""


DECOMPOSE_USER_TEMPLATE = """다음 노동법 질문을 2~4개 검색 쿼리로 분해하세요:

질문: {query}
{context_line}
JSON 배열로 응답:"""


def _should_decompose(query: str) -> bool:
    """분해가 필요한 질문인지 판단.

    단순 질문(짧은 키워드, 단일 주제)은 분해 없이 원본 사용이 효율적.
    """
    stripped = query.strip()
    if len(stripped) < MIN_QUERY_LENGTH:
        return False
    # 복합 질문 신호: 접속사, 쉼표, 물음표 2개 이상, "~하고", "~랑" 등
    complexity_markers = ["그리고", "또한", "그런데", "하고", "이랑", "랑", ",", "?"]
    marker_count = sum(1 for m in complexity_markers if m in stripped)
    # 길이가 충분히 길거나 복합 신호가 있으면 분해
    return len(stripped) >= 40 or marker_count >= 1


def decompose_query(
    query: str,
    client: anthropic.Anthropic,
    *,
    consultation_topic: str | None = None,
    question_summary: str | None = None,
) -> list[str]:
    """사용자 질문을 2~4개 검색 쿼리로 분해.

    Args:
        query: 원본 사용자 질문
        client: Anthropic 클라이언트
        consultation_topic: 분석된 상담 주제 (있으면 컨텍스트로 활용)
        question_summary: 분석된 질문 요약 (있으면 컨텍스트로 활용)

    Returns:
        분해된 검색 쿼리 리스트 (2~4개).
        분해 불필요/실패 시 빈 리스트 반환.
    """
    if not _should_decompose(query):
        logger.debug("쿼리 분해 건너뜀 (단순 질문): %r", query[:40])
        return []

    # 컨텍스트 라인 구성
    context_parts = []
    if consultation_topic:
        context_parts.append(f"주제: {consultation_topic}")
    if question_summary and question_summary != query[:len(question_summary)]:
        context_parts.append(f"요약: {question_summary}")
    context_line = "\n".join(context_parts)
    if context_line:
        context_line = f"\n{context_line}\n"

    user_msg = DECOMPOSE_USER_TEMPLATE.format(
        query=query,
        context_line=context_line,
    )

    start = time.monotonic()
    try:
        resp = client.messages.create(
            model=DECOMPOSE_MODEL,
            max_tokens=256,
            temperature=0.3,
            system=DECOMPOSE_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            timeout=DECOMPOSE_TIMEOUT,
        )
        raw = resp.content[0].text.strip()

        # JSON 파싱 — 응답이 ```json ... ``` 감싸져 있을 수 있음
        text = raw
        if text.startswith("```"):
            # 코드블록 제거
            lines = text.split("\n")
            text = "\n".join(
                l for l in lines
                if not l.strip().startswith("```")
            ).strip()

        queries = json.loads(text)
        if not isinstance(queries, list):
            raise ValueError(f"배열이 아닌 응답: {type(queries)}")

        # 문자열만 필터링, 빈 문자열 제거, 최대 개수 제한
        queries = [q.strip() for q in queries if isinstance(q, str) and q.strip()]
        queries = queries[:MAX_QUERIES]

        elapsed = (time.monotonic() - start) * 1000
        logger.info(
            "쿼리 분해 완료: %d개 쿼리, %.0fms — %r → %s",
            len(queries), elapsed, query[:40], queries,
        )
        return queries

    except json.JSONDecodeError as e:
        elapsed = (time.monotonic() - start) * 1000
        logger.warning("쿼리 분해 JSON 파싱 실패 (%.0fms): %s", elapsed, e)
        return []
    except anthropic.APITimeoutError:
        elapsed = (time.monotonic() - start) * 1000
        logger.warning("쿼리 분해 타임아웃 (%.0fms)", elapsed)
        return []
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        logger.warning("쿼리 분해 실패 (%.0fms): %s", elapsed, e)
        return []
