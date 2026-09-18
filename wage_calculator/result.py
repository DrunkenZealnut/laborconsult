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
    minimum_wage_ok: bool | None = None   # None: 미실행 또는 계산 보류
    # legacy(내장표) / managed_parameters(승인 기준 소비함) /
    # managed_no_parameters(관리 모드지만 이 계산엔 해당 기준 없음) / blocked(보류)
    legal_rule_status: str = "legacy"
    legal_rule_versions: list = field(default_factory=list)
    # 승인 기준이 없어 **그 섹션만** 빠진 계산 [{target, section, reason}, ...]
    legal_rule_blocked: list = field(default_factory=list)
    legal_rule_attempted: int = 0   # 시도한 섹션 수 (전부 보류면 요청 단위 보류로 승격)
    legal_reference_date: str | None = None

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
    if result.legal_rule_status == "blocked":
        # 기준일을 함께 밝힌다 — 저장소 장애 사유에는 날짜가 안 들어가 어느 시점 기준이
        # 없다는 것인지 알 수 없고, 관리자가 등록할 구간을 특정하지 못한다.
        day = f" (기준일 {result.legal_reference_date})" if result.legal_reference_date else ""
        return ("계산 보류" + day + ": " + " / ".join(result.warnings)
                + "\n승인된 기준 확인 전에는 금액을 추정 계산하지 마세요.")
    lines = []

    lines.append("=" * 50)
    if result.legal_rule_status == "managed_parameters":
        lines.append(f"수치 기준 적용일: {result.legal_reference_date} (산식의 법률 검토는 별도)")
        for version in result.legal_rule_versions:
            lines.append(f"기준 버전: {version['key']} / {version['id']} / {version['citation']}")
    elif result.legal_rule_status == "managed_no_parameters":
        # 적용일만 적으면 내장표 수치까지 승인 기준으로 읽힌다. 출처를 분명히 한다.
        lines.append(f"기준일 {result.legal_reference_date}: 이 계산에 적용된 승인 수치 기준 없음 "
                     "— 아래 금액은 내장 기준표·산식에 따른 값입니다")
    if result.legal_rule_blocked:
        # 빠진 섹션을 밝히지 않으면 '물어본 것 중 일부가 없다'는 사실이 조용히 사라진다.
        lines.append("보류된 계산 (승인 기준 없음 — 아래 결과에 포함되지 않음):")
        for item in result.legal_rule_blocked:
            lines.append(f"  · {item['section']}: {item['reason']}")
        lines.append("보류 항목의 금액·요율은 추정하지 마세요.")
    lines.append("📊 임금 계산 결과")
    lines.append("=" * 50)

    # 임금 미제공(통상시급 0원) 부분 실행 시 최저임금 판정도 무의미 — 함께 숨김
    if result.ordinary_hourly:
        lines.append(f"통상시급: {result.ordinary_hourly:,.0f}원")
        # None 은 '판정 보류'다. falsy 라고 '미달'로 찍으면 없는 위반을 만들어낸다.
        verdict = ("⏸ 판정 보류" if result.minimum_wage_ok is None
                   else "✅ 충족" if result.minimum_wage_ok else "❌ 미달")
        lines.append(f"최저임금 충족: {verdict}")
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
        "legal_rule_status": result.legal_rule_status,
        "legal_rule_versions": result.legal_rule_versions,
        "legal_rule_blocked": result.legal_rule_blocked,
        "legal_reference_date": result.legal_reference_date,
        "summary": result.summary,
        "breakdown": result.breakdown,
        "formulas": result.formulas,
        "legal_basis": result.legal_basis,
        "warnings": result.warnings,
        "disclaimer": result.disclaimer,
    }
