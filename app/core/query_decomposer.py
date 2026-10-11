"""RAG 멀티쿼리 분해 + Adaptive Retrieval 모듈

사용자 질문을 LLM으로 여러 관점의 검색 쿼리로 분해하여
Pinecone 벡터 검색의 recall을 향상시킨다.

Adaptive Retrieval: 질문 복잡도(SIMPLE/MODERATE/COMPLEX)에 따라
검색 전략(top_k, max_queries, graph_hops, self_rag)을 동적으로 조정한다.
"""

from __future__ import annotations

import json
import logging
import time
from enum import Enum

from app.core import llm_gateway

logger = logging.getLogger(__name__)

# 모델은 관리자 설정 1순위(llm_gateway). 3초는 Haiku 기준이었다 — 실측(2026-10-11) gemini-3.8-flash 4.4초,
# gpt-6-sol 2.3초라 3초면 Gemini 1순위에서 매번 시간 초과로 분해가 생략된다.
DECOMPOSE_TIMEOUT = 8.0
MAX_QUERIES = 4
MIN_QUERY_LENGTH = 15     # 이 길이 미만의 질문은 분해 건너뜀


# ── Adaptive Retrieval: 질문 복잡도 분류 ─────────────────────────────────


class QueryComplexity(Enum):
    SIMPLE = "simple"       # 단일 주제, 짧은 질문
    MODERATE = "moderate"   # 중간 복잡도
    COMPLEX = "complex"     # 복합 질문, 다중 법률 참조


COMPLEXITY_PARAMS = {
    QueryComplexity.SIMPLE: {
        "search_top_k": 8,
        "rerank_top_n": 3,
        "max_queries": 1,
        "graph_hops": 1,
        "self_rag": False,
        "force_decompose": False,
    },
    QueryComplexity.MODERATE: {
        "search_top_k": 15,
        "rerank_top_n": 5,
        "max_queries": 3,
        "graph_hops": 2,
        "self_rag": False,
        "force_decompose": False,
    },
    QueryComplexity.COMPLEX: {
        "search_top_k": 20,
        "rerank_top_n": 7,
        "max_queries": 4,
        "graph_hops": 2,
        "self_rag": True,
        "force_decompose": True,
    },
}

# 검색 쿼리 병합의 여유 슬롯 — LLM 분해 쿼리(max_queries) 외에 규칙 기반·
# 폴백 쿼리가 차지할 수 있는 수. pipeline의 _merge_search_queries(max_total=…)와
# eval_retrieval.py의 절단이 공유한다 — 리터럴로 두 곳에 살면 한쪽 조정 시
# 고정 평가셋의 기준선이 프로덕션과 조용히 어긋난다.
QUERY_MERGE_HEADROOM = 2

_COMPLEXITY_MARKERS = ["그리고", "또한", "그런데", "하고", "이랑", "랑", ",", "?"]


def classify_complexity(
    query: str,
    relevant_laws: list[str] | None = None,
    calculation_types: list[str] | None = None,
) -> QueryComplexity:
    """질문 복잡도 분류.

    스코어 기반:
    - 길이 80+: +3, 40+: +2, 25+: +1
    - 법률 참조 수: +min(count, 2)
    - 접속사/쉼표 수: +min(count, 2)
    - 계산 유형 2+: +1

    COMPLEX: score >= 5, MODERATE: score >= 2, SIMPLE: otherwise
    """
    stripped = query.strip()
    length = len(stripped)

    marker_count = sum(1 for m in _COMPLEXITY_MARKERS if m in stripped)
    law_count = len(relevant_laws) if relevant_laws else 0
    calc_count = len(calculation_types) if calculation_types else 0

    score = 0
    if length >= 80:
        score += 3
    elif length >= 40:
        score += 2
    elif length >= 25:
        score += 1

    score += min(law_count, 2)
    score += min(marker_count, 2)

    if calc_count >= 2:
        score += 1

    if score >= 5:
        result = QueryComplexity.COMPLEX
    elif score >= 2:
        result = QueryComplexity.MODERATE
    else:
        result = QueryComplexity.SIMPLE

    logger.debug("Query complexity: %s (score=%d, len=%d, laws=%d, markers=%d)",
                 result.value, score, length, law_count, marker_count)
    return result


# ── 멀티쿼리 분해 ─────────────────────────────────────────────────────────


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
    config,
    *,
    consultation_topic: str | None = None,
    question_summary: str | None = None,
    force: bool = False,
) -> list[str]:
    """사용자 질문을 2~4개 검색 쿼리로 분해.

    Args:
        query: 원본 사용자 질문
        config: AppConfig — 모델은 설정 1순위(실패 시 분해 생략, 다음 순위로 넘기지 않음)
        consultation_topic: 분석된 상담 주제 (있으면 컨텍스트로 활용)
        question_summary: 분석된 질문 요약 (있으면 컨텍스트로 활용)
        force: True이면 _should_decompose() 판단 무시하고 반드시 분해

    Returns:
        분해된 검색 쿼리 리스트 (2~4개).
        분해 불필요/실패 시 빈 리스트 반환.
    """
    if not force and not _should_decompose(query):
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
        # 1순위만 시도한다 — 분해는 recall 보강이라 실패해도 규칙 기반 쿼리로 검색이 돈다.
        raw, _provider = llm_gateway.text(
            config, system=DECOMPOSE_SYSTEM, user=user_msg, purpose="쿼리 분해",
            max_tokens=256, timeout=DECOMPOSE_TIMEOUT, attempts=1,
        )

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
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        logger.warning("쿼리 분해 실패 (%.0fms): %s", elapsed, e)
        return []
