"""사후 상담 사례 대조 (legal-corpus-coverage T3).

**왜 사후인가.** 상담 Q&A는 제3자 게시물이라 답변의 *근거*로 쓰면 저작권
노출이자 품질 위험이다(작성자마다 결론이 다를 수 있다). 그렇다고 버리면
"내 상황과 비슷한 사례"라는 실사용 가치가 사라진다. 그래서 위치를 옮긴다 —
답변은 법령·판례로 짓고, 상담은 **생성된 답변과 결론이 같을 때만** 참고
사례로 덧붙인다.

**다르면 제시하지 않는다**(2026-08-20 사용자 확정). 노동상담에서 상충하는
정보는 사용자를 혼란시키고, 우리 답변은 법령·판례 근거라 신뢰도가 더 높다.
다만 **기록은 남긴다** — "우리 답과 실무 상담이 갈리는 주제"는 품질 모니터링·
코퍼스 공백 탐지의 신호다.

**대조 수단은 임베딩 유사도다**(LLM 호출 0회). 답변 스트리밍이 끝난 뒤 실행하는
단계라 체감 지연이 아니고, 임베딩 1회(배치)로 끝난다.
"""

from __future__ import annotations

import logging
import math
import os

logger = logging.getLogger(__name__)

# 답변과 상담 사례가 "같은 결론"이라고 볼 유사도 하한.
#
# **절대값이 낮은 것이 정상이다.** 답변은 법률 문어체이고 상담 청크는 질문+답변
# 구어체라 같은 쟁점이라도 코사인이 0.5를 잘 넘지 않는다. 문서 간 유사도(0.8+)를
# 기대하고 임계를 잡으면 **아무것도 표시되지 않는다**(설계 초안의 0.75가 그랬다).
#
# 실측(2026-08-23). **실제 LLM 답변 기준**이 운영 실태다 — 손으로 쓴 짧은
# 문어체 답변으로 재면 값이 0.1~0.2 낮게 나와 임계를 과하게 낮추게 된다:
#   실제 답변(2,123자) ↔ 같은 쟁점 상담   0.483 ~ 0.629
#   실제 답변          ↔ 다른 쟁점 상담   0.238 ~ 0.429   ← 대조군(해고·산재)
#
# 0.45는 대조군 최고(0.429)와 같은 쟁점 최저(0.483) **사이**에 놓인다.
# **마진이 0.05로 좁다** — 임계값 하나로 완벽히 갈리지 않으므로, 애매하면
# **표시하지 않는 쪽**으로 기운다: 사용자 지시가 "다르면 제시하지 않는다"이고,
# 오표시(상충 정보 노출)가 미표시(사례 없음)보다 비싸다.
# 운영에서 `metadata.case_match`의 max_similarity 분포를 관찰해 재조정할 것.
SIMILARITY_THRESHOLD = float(os.getenv("CASE_MATCH_THRESHOLD", "0.45"))

# 답변 임베딩에 넣을 최대 길이 — 임베딩 모델의 실질 상한과 비용을 함께 고려한다.
# 답변 앞부분(핵심 답변·결론)이 대조에 가장 유효하다.
_MAX_ANSWER_CHARS = 2000

# 표시할 사례 수. 여러 건을 늘어놓으면 "근거"처럼 보여 T3의 취지가 흐려진다.
MAX_CASES = 2


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def match_counsel_cases(answer: str, precedent_meta: list[dict] | None,
                        config) -> dict:
    """생성된 답변과 컨텍스트에 실린 상담 사례를 대조한다.

    Args:
        answer: 완성된 답변 본문(인용 교정 후)
        precedent_meta: format_pinecone_hits가 낸 meta 목록
        config: AppConfig (openai_client, embed_model)

    Returns:
        {"cases": [...], "divergent": bool, "checked": int, "max_similarity": float}
        - cases: 임계 이상인 사례(표시 대상). 없으면 빈 목록
        - divergent: 대조는 했으나 임계 이상이 하나도 없음 = 결론이 갈림
    """
    empty = {"cases": [], "divergent": False, "checked": 0, "max_similarity": 0.0}
    if not answer or not precedent_meta:
        return empty

    from app.core.rag import is_counsel_source

    counsel = [m for m in precedent_meta
               if is_counsel_source(m) and (m.get("chunk_text") or "").strip()]
    if not counsel:
        return empty

    try:
        # 답변 1개 + 상담 N개를 **한 번의 배치 호출**로 임베딩한다.
        texts = [answer[:_MAX_ANSWER_CHARS]] + [
            (m.get("chunk_text") or "")[:_MAX_ANSWER_CHARS] for m in counsel]
        resp = config.openai_client.with_options(
            timeout=10.0, max_retries=0,
        ).embeddings.create(model=config.embed_model, input=texts)
        vecs = [d.embedding for d in sorted(resp.data, key=lambda x: x.index)]
    except Exception as e:
        # 대조 실패가 답변을 막지 않는다 — 사례를 못 붙일 뿐이다.
        logger.warning("상담 사례 대조 실패: %s", e)
        return empty

    if len(vecs) != len(counsel) + 1:
        logger.warning("상담 사례 대조: 임베딩 수 불일치 %d != %d",
                       len(vecs), len(counsel) + 1)
        return empty

    answer_vec = vecs[0]
    scored = [(_cosine(answer_vec, v), m) for v, m in zip(vecs[1:], counsel)]
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[0][0] if scored else 0.0

    # 제목은 **비식별화 후** 내보낸다 — nodong.kr 상담 제목은 사용자가 쓴
    # 문장이라 회사명·이름이 들어갈 수 있는데, 여기서는 그 제목이 "유사 사례"라는
    # 편집적 추천으로 승격돼 나간다(외부 리뷰 A-8). `_build_sources_payload`와
    # 같은 길이 상한도 함께 건다. anonymize는 FastAPI·API 키 비의존 경량 모듈이다.
    from app.anonymize import anonymize

    cases = [{
        "title": anonymize(m.get("title", ""))[:120],
        "section": anonymize(m.get("section", ""))[:60],
        "source_type": m.get("source_type", ""),
        "similarity": round(sim, 3),
    } for sim, m in scored if sim >= SIMILARITY_THRESHOLD][:MAX_CASES]

    # 대조 대상이 있었는데 하나도 임계를 못 넘었다 = 결론이 갈린다.
    divergent = bool(scored) and not cases
    if divergent:
        logger.info("상담 사례 결론 상이 — 미표시(최대 유사도 %.3f, 임계 %.2f)",
                    top, SIMILARITY_THRESHOLD)
    return {"cases": cases, "divergent": divergent,
            "checked": len(scored), "max_similarity": round(top, 3)}
