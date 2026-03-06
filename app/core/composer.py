"""통합 답변 생성 — Claude 스트리밍"""

from app.templates.prompts import COMPOSER_SYSTEM


def compose_answer(question, analysis, calc_result, rag_hits, legal_hits, config):
    """계산 결과 + Q&A RAG + 법령/판례 RAG를 통합하여 스트리밍 답변 생성 (generator)"""

    context_parts = []

    if calc_result:
        context_parts.append(_format_calc_context(calc_result))
    if legal_hits:
        context_parts.append(_format_legal_context(legal_hits))
    if rag_hits:
        context_parts.append(_format_rag_context(rag_hits))

    user_message = (
        f"질문: {question}\n\n"
        f"질문 분석: {analysis.question_summary}\n\n"
        + "\n\n---\n\n".join(context_parts)
    )

    with config.anthropic_client.messages.stream(
        model=config.answer_model,
        max_tokens=3000,
        system=COMPOSER_SYSTEM,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        for text in stream.text_stream:
            yield text


def compose_follow_up(missing_info: list[str], question_summary: str) -> str:
    """missing_info를 기반으로 추가 질문 메시지 생성"""
    lines = [f"**{question_summary}**에 대해 답변드리기 위해 추가 정보가 필요합니다:\n"]
    for i, info in enumerate(missing_info, 1):
        lines.append(f"{i}. {info}")
    lines.append("\n위 정보를 알려주시면 정확한 계산 결과를 제공해 드리겠습니다.")
    return "\n".join(lines)


def _format_calc_context(result) -> str:
    lines = ["[계산 결과]"]
    for key, val in result.summary.items():
        lines.append(f"  {key}: {val}")
    if result.ordinary_hourly:
        lines.append(f"\n  통상시급: {result.ordinary_hourly:,.0f}원")
    if result.monthly_total:
        lines.append(f"  월 총액(세전): {result.monthly_total:,.0f}원")
    if result.monthly_net and result.monthly_net > 0:
        lines.append(f"  월 실수령액: {result.monthly_net:,.0f}원")
    if result.formulas:
        lines.append("\n[계산식]")
        for f in result.formulas[:10]:
            lines.append(f"  {f}")
    if result.warnings:
        lines.append("\n[주의사항]")
        for w in result.warnings[:5]:
            lines.append(f"  - {w}")
    if result.legal_basis:
        lines.append("\n[계산기 법적 근거]")
        for lb in result.legal_basis[:5]:
            lines.append(f"  - {lb}")
    return "\n".join(lines)


def _format_legal_context(hits: list[dict]) -> str:
    lines = ["[관련 법령/판례 검색 결과]"]
    for i, h in enumerate(hits[:5], 1):
        lines.append(f"\n  [{i}] {h['title']}")
        if h.get("section"):
            lines.append(f"  섹션: {h['section']}")
        lines.append(f"  유사도: {h['score']}")
        lines.append(f"  {h['content'][:600]}")
    return "\n".join(lines)


def _format_rag_context(hits: list[dict]) -> str:
    lines = ["[유사 상담 사례]"]
    for i, h in enumerate(hits[:5], 1):
        lines.append(f"\n  [{i}] {h['title']}")
        if h.get("section"):
            lines.append(f"  섹션: {h['section']}")
        lines.append(f"  유사도: {h['score']}")
        lines.append(f"  {h['content'][:500]}")
    return "\n".join(lines)
