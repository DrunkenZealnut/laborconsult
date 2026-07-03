"""추가질문 메시지 생성 — test_followup_consistency*.py 전용(웹 파이프라인은 미사용)"""


def compose_follow_up(missing_info: list[str], question_summary: str) -> str:
    """missing_info를 기반으로 추가 질문 메시지 생성"""
    lines = [f"**{question_summary}**에 대해 답변드리기 위해 추가 정보가 필요합니다:\n"]
    for i, info in enumerate(missing_info, 1):
        lines.append(f"{i}. {info}")
    lines.append("\n위 정보를 알려주시면 정확한 계산 결과를 제공해 드리겠습니다.")
    return "\n".join(lines)
