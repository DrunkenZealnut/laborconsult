"""Intent Analyzer — Claude tool_use로 노동상담 질문 분석"""

import json
from app.models.schemas import AnalysisResult
from app.templates.prompts import ANALYZE_TOOL, ANALYZER_SYSTEM


def analyze_intent(
    question: str,
    history: list[dict],
    config: "AppConfig",
) -> AnalysisResult:
    """사용자 질문을 분석하여 계산 유형, 추출 정보, 누락 정보를 반환"""

    messages = []
    # 최근 대화 컨텍스트 (최대 4턴)
    for turn in history[-8:]:
        messages.append(turn)
    messages.append({"role": "user", "content": question})

    response = config.anthropic_client.messages.create(
        model=config.analyzer_model,
        max_tokens=1024,
        system=ANALYZER_SYSTEM,
        tools=[ANALYZE_TOOL],
        tool_choice={"type": "tool", "name": "analyze_labor_question"},
        messages=messages,
    )

    # tool_use 블록에서 분석 결과 추출
    for block in response.content:
        if block.type == "tool_use":
            inp = block.input
            # extracted_info 구성: 계산기 입력용 필드만 분리
            info_keys = {
                "wage_type", "wage_amount", "business_size",
                "weekly_work_days", "daily_work_hours",
                "weekly_overtime_hours", "weekly_night_hours", "weekly_holiday_hours",
                "start_date", "end_date", "service_period_text",
                "fixed_allowances", "monthly_wage", "annual_wage",
                "notice_days_given", "parental_leave_months",
                "arrear_amount", "arrear_due_date",
            }
            extracted = {k: v for k, v in inp.items() if k in info_keys and v is not None}

            return AnalysisResult(
                requires_calculation=inp.get("requires_calculation", False),
                calculation_types=inp.get("calculation_types", []),
                extracted_info=extracted,
                relevant_laws=inp.get("relevant_laws", []),
                missing_info=inp.get("missing_info", []),
                question_summary=inp.get("question_summary", ""),
            )

    return AnalysisResult(question_summary=question)
