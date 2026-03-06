"""
계산 결과 포맷 및 출력 구조

WageResult: 계산 결과 + 계산식 + 법적 근거를 통합한 최종 결과 객체
"""

from dataclasses import dataclass, field


DISCLAIMER = (
    "⚠️  본 계산 결과는 참고용이며 법적 효력이 없습니다. "
    "실제 지급액은 근로계약서, 취업규칙, 단체협약 등에 따라 다를 수 있습니다. "
    "정확한 판단은 고용노동부(1350) 또는 노무사에게 문의하세요."
)


@dataclass
class WageResult:
    """통합 임금 계산 결과"""
    # 핵심 요약
    ordinary_hourly: float = 0.0          # 통상시급 (원)
    monthly_total: float = 0.0            # 월 총 예상 수령액 (세전, 원)
    monthly_net: float = 0.0             # 월 실수령액 (세후, 원) — insurance 계산 시 채워짐
    minimum_wage_ok: bool = True          # 최저임금 충족 여부

    # 항목별 금액
    summary: dict = field(default_factory=dict)

    # 상세 내역 (항목별 breakdown)
    breakdown: dict = field(default_factory=dict)

    # 계산식 목록
    formulas: list = field(default_factory=list)

    # 법적 근거
    legal_basis: list = field(default_factory=list)

    # 주의사항
    warnings: list = field(default_factory=list)

    # 면책 고지
    disclaimer: str = DISCLAIMER


def format_result(result: "WageResult") -> str:
    """WageResult를 사람이 읽기 쉬운 텍스트로 변환"""
    lines = []

    lines.append("=" * 50)
    lines.append("📊 임금 계산 결과")
    lines.append("=" * 50)

    if result.ordinary_hourly:
        lines.append(f"통상시급: {result.ordinary_hourly:,.0f}원")

    lines.append(f"최저임금 충족: {'✅ 충족' if result.minimum_wage_ok else '❌ 미달'}")
    lines.append("")

    if result.summary:
        lines.append("── 항목별 결과 ──")
        for k, v in result.summary.items():
            lines.append(f"  {k}: {v}")
        lines.append("")

    if result.monthly_total:
        lines.append(f"월 총 예상 수령액(세전): {result.monthly_total:,.0f}원")
    if result.monthly_net:
        lines.append(f"월 실수령액(세후):       {result.monthly_net:,.0f}원")
    if result.monthly_total or result.monthly_net:
        lines.append("")

    if result.formulas:
        lines.append("── 계산식 ──")
        for f in result.formulas:
            lines.append(f"  • {f}")
        lines.append("")

    if result.warnings:
        lines.append("── ⚠️  주의사항 ──")
        for w in result.warnings:
            lines.append(f"  • {w}")
        lines.append("")

    if result.legal_basis:
        lines.append("── 법적 근거 ──")
        for lb in result.legal_basis:
            lines.append(f"  • {lb}")
        lines.append("")

    lines.append(result.disclaimer)

    return "\n".join(lines)


def format_result_json(result: "WageResult") -> dict:
    """WageResult를 JSON 직렬화 가능한 dict로 변환"""
    return {
        "ordinary_hourly": result.ordinary_hourly,
        "monthly_total": result.monthly_total,
        "minimum_wage_ok": result.minimum_wage_ok,
        "summary": result.summary,
        "breakdown": result.breakdown,
        "formulas": result.formulas,
        "legal_basis": result.legal_basis,
        "warnings": result.warnings,
        "disclaimer": result.disclaimer,
    }
