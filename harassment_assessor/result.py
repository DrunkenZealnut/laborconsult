"""
직장 내 괴롭힘 판정 결과 구조 및 포맷
"""

from dataclasses import dataclass, field

from .constants import DISCLAIMER


@dataclass
class ElementAssessment:
    """3요소 개별 판정 결과"""
    element_name: str = ""
    status: str = ""        # "해당", "미해당", "불분명"
    score: float = 0.0
    reasoning: str = ""


@dataclass
class AssessmentResult:
    """직장 내 괴롭힘 판정 종합 결과"""
    # 3요소 판정
    element_1_superiority: ElementAssessment = field(default_factory=ElementAssessment)
    element_2_beyond_scope: ElementAssessment = field(default_factory=ElementAssessment)
    element_3_harm: ElementAssessment = field(default_factory=ElementAssessment)

    # 종합 판정
    likelihood: str = ""
    overall_score: float = 0.0
    behavior_types_detected: list[str] = field(default_factory=list)

    # 고객 괴롭힘 여부
    is_customer_harassment: bool = False

    # 법적 근거
    legal_basis: list[str] = field(default_factory=list)

    # 대응 절차
    response_steps: list[dict] = field(default_factory=list)

    # 주의사항
    warnings: list[str] = field(default_factory=list)

    # 면책
    disclaimer: str = DISCLAIMER


def format_assessment(result: AssessmentResult) -> str:
    """AssessmentResult를 사람이 읽기 쉬운 텍스트로 변환"""
    lines = []
    lines.append("=" * 50)
    lines.append("⚖️ 직장 내 괴롭힘 판정 결과")
    lines.append("=" * 50)

    # 고객 괴롭힘인 경우
    if result.is_customer_harassment:
        lines.append("")
        lines.append("→ 직장 내 괴롭힘(근기법 제76조의2)에는 해당하지 않습니다.")
        lines.append("  고객에 의한 괴롭힘은 산업안전보건법 제41조가 적용됩니다.")
        lines.append("")
        if result.legal_basis:
            lines.append("── 관련 법 조문 ──")
            for lb in result.legal_basis:
                lines.append(f"  • {lb}")
            lines.append("")
        if result.warnings:
            lines.append("── ⚠️ 주의사항 ──")
            for w in result.warnings:
                lines.append(f"  • {w}")
            lines.append("")
        lines.append(result.disclaimer)
        return "\n".join(lines)

    # 3요소 판정
    _STATUS_ICON = {"해당": "✅", "미해당": "❌", "불분명": "❓"}

    lines.append("")
    for elem in [result.element_1_superiority,
                 result.element_2_beyond_scope,
                 result.element_3_harm]:
        icon = _STATUS_ICON.get(elem.status, "❓")
        lines.append(f"  {icon} {elem.element_name}: {elem.status}")
        lines.append(f"     → {elem.reasoning}")
    lines.append("")

    # 종합 판정
    lines.append(f"  → 직장 내 괴롭힘 해당 가능성: {result.likelihood}")
    if result.behavior_types_detected:
        types_label = {
            "폭행_협박": "폭행·협박", "폭언_모욕": "폭언·모욕",
            "따돌림_무시": "따돌림·무시", "부당업무": "부당한 업무 지시",
            "사적용무": "사적 용무 강요", "감시_통제": "감시·통제",
            "부당인사": "부당 인사",
        }
        types_str = ", ".join(types_label.get(t, t) for t in result.behavior_types_detected)
        lines.append(f"  → 감지된 행위 유형: {types_str}")
    lines.append("")

    # 법적 근거
    if result.legal_basis:
        lines.append("── 관련 법 조문 ──")
        for lb in result.legal_basis:
            lines.append(f"  • {lb}")
        lines.append("")

    # 대응 절차
    if result.response_steps:
        lines.append("── 대응 절차 안내 ──")
        for step in result.response_steps:
            lines.append(f"  {step['step']}단계: {step['title']}")
            lines.append(f"         {step['description']}")
        lines.append("")

    # 주의사항
    if result.warnings:
        lines.append("── ⚠️ 주의사항 ──")
        for w in result.warnings:
            lines.append(f"  • {w}")
        lines.append("")

    lines.append(result.disclaimer)
    return "\n".join(lines)
