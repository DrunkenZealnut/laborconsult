"""정보 충돌 해결 모듈 — 소스 유형별 우선순위 규칙

병렬 검색 결과(법제처 법령, Pinecone 판례, NLRC 판정사례, GraphRAG)에서
동일한 법 조항에 대해 상충 정보가 있을 때, 법적 우선순위에 따라 해결한다.

원칙:
  현행 법령 > 대법원 판례 > 하급심 판례 > 행정해석 > 판정사례 > 상담사례

주의:
  - '충돌'은 동일 법 조항에 대해 서로 다른 기준을 제시하는 경우
  - 보완 관계의 정보는 충돌이 아님 (예: 법조문 + 적용 사례)
  - 충돌 감지는 법 조항 참조 패턴 기반 (정규식 매칭)
"""

from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

# 법 조항 참조 패턴 (예: "근로기준법 제56조", "최저임금법 제6조의2")
_LAW_REF_PATTERN = re.compile(
    r"((?:근로기준법|최저임금법|산업재해보상보험법|남녀고용평등법|"
    r"근로자퇴직급여보장법|고용보험법|산업안전보건법|"
    r"파견근로자보호법|기간제법|외국인고용법)"
    r"(?:\s*시행령|\s*시행규칙)?"
    r"\s*제\d+조(?:의\d+)?)"
)


def _extract_law_refs(text: str) -> set[str]:
    """텍스트에서 법 조항 참조 추출."""
    return set(_LAW_REF_PATTERN.findall(text))


def annotate_source_priority(
    precedent_text: str | None,
    legal_articles_text: str | None,
    nlrc_text: str | None,
) -> str | None:
    """충돌 가능성이 있는 컨텍스트에 우선순위 주석을 부착.

    동일 법 조항을 참조하는 소스가 여러 개인 경우,
    LLM에 우선순위 안내 메모를 전달한다.

    Returns:
        conflict_note: LLM에 전달할 충돌 안내 메모. 충돌 없으면 None.
    """
    if not legal_articles_text:
        return None
    if not precedent_text and not nlrc_text:
        return None

    legal_refs = _extract_law_refs(legal_articles_text)
    if not legal_refs:
        return None

    prec_refs = _extract_law_refs(precedent_text or "")
    nlrc_refs = _extract_law_refs(nlrc_text or "")

    # 교집합 = 동일 조항을 다루는 소스들
    overlap = legal_refs & (prec_refs | nlrc_refs)
    if not overlap:
        return None

    note_lines = [
        "[정보 우선순위 안내]",
        f"다음 법 조항에 대해 복수의 출처가 있습니다: {', '.join(sorted(overlap))}",
        "",
        "적용 우선순위 (반드시 준수):",
        "1. 현행 법조문 (법제처 국가법령정보센터 조회) — 최우선 적용",
        "2. 대법원 판례 — 법조문 해석 기준",
        "3. 행정해석·판정사례 — 참고 자료",
        "",
        "⚠️ 판례나 행정해석이 현행 법조문과 다른 기준을 제시하는 경우, "
        "법령 개정으로 인한 차이일 수 있으므로 현행 법조문을 우선 적용하고 "
        "'과거 판례/해석에서는 다른 기준이 적용되었으나 현행법 기준으로 안내드립니다'로 설명하세요.",
    ]

    logger.info("정보 충돌 감지: %d개 조항 — %s", len(overlap), overlap)
    return "\n".join(note_lines)
