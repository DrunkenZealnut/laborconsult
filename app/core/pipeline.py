"""파이프라인 오케스트레이터 — 전체 흐름 제어"""

from app.core.analyzer import analyze_intent
from app.core.converter import convert_to_wage_input
from app.core.calculator import run_calculation, result_to_dict
from app.core.rag import search_qna, search_legal
from app.core.composer import compose_answer, compose_follow_up


def process_question(question: str, session, config):
    """
    전체 파이프라인 실행 (generator: SSE 스트리밍용)

    ① 의도 분석 → ② 계산 → ③ Q&A 검색 → ④ 법령 검색 → ⑤ 답변 생성
    """
    # ① 의도 분석
    analysis = analyze_intent(question, session.history, config)

    # 추가 질문 필요 시
    if analysis.missing_info and analysis.requires_calculation and not session.has_pending_info():
        session.save_pending(analysis)
        text = compose_follow_up(analysis.missing_info, analysis.question_summary)
        yield {"type": "follow_up", "text": text}
        return

    # pending 정보 병합
    if session.has_pending_info():
        analysis = session.merge_with_pending(analysis, question)

    # ② 계산 실행
    calc_result = None
    calc_dict = None
    if analysis.requires_calculation and analysis.extracted_info:
        try:
            wage_input = convert_to_wage_input(analysis.extracted_info)
            calc_result = run_calculation(wage_input, analysis.calculation_types)
            calc_dict = result_to_dict(calc_result)
        except Exception as e:
            calc_result = None
            calc_dict = {"error": str(e)}

    # ③ Q&A RAG 검색
    rag_hits = search_qna(question, analysis.calculation_types[0] if analysis.calculation_types else None, config)

    # ④ 법령/판례 RAG 검색
    legal_basis = calc_result.legal_basis if calc_result else []
    legal_hits = search_legal(analysis.relevant_laws, legal_basis, config)

    # 메타데이터 전송
    yield {
        "type": "meta",
        "calc_result": calc_dict,
        "sources_count": len(rag_hits) + len(legal_hits),
    }

    # ⑤ 통합 답변 생성 (스트리밍)
    full_text = ""
    for chunk in compose_answer(question, analysis, calc_result, rag_hits, legal_hits, config):
        full_text += chunk
        yield {"type": "chunk", "text": chunk}

    yield {"type": "done"}

    # 세션 히스토리 업데이트
    session.add_turn(question, full_text)
