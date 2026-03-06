"""
법률 판단 힌트 시스템

임금 계산 중 발견된 사실관계에 기반하여
법적으로 검토해볼 만한 포인트를 제시합니다.

⚠️ 이 시스템은 법적 판단이 아닌 '검토 포인트' 제시입니다.
실제 법적 판단은 노무사(1350) 또는 변호사에게 문의하세요.
"""

from dataclasses import dataclass, field

from .models import WageInput, BusinessSize, WageType
from .calculators.ordinary_wage import OrdinaryWageResult
from .constants import MINIMUM_HOURLY_WAGE, ORDINARY_WAGE_2024_RULING


@dataclass
class LegalHint:
    """법률 검토 포인트"""
    category: str   # 검토 영역: "통상임금", "최저임금", "연장수당" 등
    condition: str  # 검출된 상황 설명
    hint: str       # 검토 포인트 내용
    basis: str      # 관련 법령·판례
    priority: int   # 1=중요(즉시 확인), 2=참고


def generate_legal_hints(
    inp: WageInput,
    ow: OrdinaryWageResult | None = None,
    minimum_wage_ok: bool = True,
) -> list[LegalHint]:
    """
    입력 정보 기반 법률 판단 힌트 생성

    Returns:
        LegalHint 목록 (priority 오름차순 정렬)
    """
    hints: list[LegalHint] = []

    hints.extend(_hints_ordinary_wage(inp))
    hints.extend(_hints_minimum_wage(inp, minimum_wage_ok))
    hints.extend(_hints_overtime(inp))
    hints.extend(_hints_comprehensive(inp))
    hints.extend(_hints_small_business(inp))

    # 중요도 순 정렬 (1 먼저)
    return sorted(hints, key=lambda h: h.priority)


# ── 통상임금 관련 힌트 ────────────────────────────────────────────────────────

def _hints_ordinary_wage(inp: WageInput) -> list[LegalHint]:
    hints = []

    for a in inp.fixed_allowances:
        name = a.get("name", "수당")
        condition = a.get("condition", "없음")
        is_ordinary = a.get("is_ordinary")        # None = 미설정
        payment_cycle = a.get("payment_cycle", "매월")

        # 재직조건/근무일수 → 명시적으로 is_ordinary=False 처리된 경우
        if condition in ["재직조건", "근무일수"] and is_ordinary is False:
            hints.append(LegalHint(
                category="통상임금",
                condition=f"'{name}': {condition} 조건부 지급 → 통상임금 제외 처리",
                hint=(
                    f"대법원 2023다302838 (2024.12.19) 판결에 따라, "
                    f"소정근로일수 이내 조건이거나 재직조건만으로는 통상임금성을 "
                    f"부정할 수 없습니다. '{name}'이 정기적·일률적으로 지급된다면 "
                    f"통상임금 해당 가능성이 높습니다. 계산기는 자동으로 포함 처리합니다."
                ),
                basis=ORDINARY_WAGE_2024_RULING,
                priority=1,
            ))

        # 성과조건부인데 통상임금으로 입력된 경우
        if condition == "성과조건" and is_ordinary is True:
            hints.append(LegalHint(
                category="통상임금",
                condition=f"'{name}': 성과조건부 지급 → 통상임금 포함 처리",
                hint=(
                    f"'{name}'은 성과 달성에 따라 지급 여부가 결정되므로 "
                    f"통상임금에서 제외될 가능성이 있습니다. "
                    f"계산기는 성과조건부를 자동으로 제외 처리합니다."
                ),
                basis="대법원 2013다4174 (통상임금 판단 기준)",
                priority=1,
            ))

        # 격월·분기 지급 상여금 — 2023 판결로 통상임금 허용됨 (참고)
        if payment_cycle in ["격월", "분기", "연"] and is_ordinary is not False:
            hints.append(LegalHint(
                category="통상임금",
                condition=f"'{name}': {payment_cycle} 지급",
                hint=(
                    f"대법원 2023다302838 판결로 지급 주기가 격월·분기·연 단위여도 "
                    f"정기적·일률적으로 지급되면 통상임금으로 인정됩니다. "
                    f"단, 지급 기준·금액의 일률성을 별도 확인하세요."
                ),
                basis=ORDINARY_WAGE_2024_RULING,
                priority=2,
            ))

    return hints


# ── 최저임금 관련 힌트 ───────────────────────────────────────────────────────

def _hints_minimum_wage(inp: WageInput, minimum_wage_ok: bool) -> list[LegalHint]:
    hints = []

    if not minimum_wage_ok:
        year = inp.reference_year
        mw = MINIMUM_HOURLY_WAGE.get(year, 0)
        hints.append(LegalHint(
            category="최저임금",
            condition=f"최저임금 미달 ({year}년 기준 {mw:,}원/시간)",
            hint=(
                f"현재 임금이 {year}년 최저임금({mw:,}원/시간)에 미달합니다. "
                f"최저임금법 제6조에 따라 최저임금 이상을 지급해야 하며, "
                f"위반 시 3년 이하 징역 또는 2천만원 이하 벌금 대상입니다 (최저임금법 제28조)."
            ),
            basis="최저임금법 제6조, 제28조",
            priority=1,
        ))

    if inp.is_probation:
        hints.append(LegalHint(
            category="최저임금",
            condition="수습기간 최저임금 90% 특례 적용 중",
            hint=(
                "수습 사용 후 3개월 이내이면 최저임금의 90%를 적용할 수 있습니다. "
                "단, 고용노동부 고시 단순노무직은 특례 미적용."
            ),
            basis="최저임금법 제5조 제2항",
            priority=2,
        ))

    return hints


# ── 연장수당 관련 힌트 ───────────────────────────────────────────────────────

def _hints_overtime(inp: WageInput) -> list[LegalHint]:
    hints = []
    s = inp.schedule

    # 5인 미만 + 연장근로 → 가산수당 미적용 안내
    if inp.business_size == BusinessSize.UNDER_5 and s.weekly_overtime_hours > 0:
        hints.append(LegalHint(
            category="연장수당",
            condition="5인 미만 사업장 연장근로 발생",
            hint=(
                "5인 미만 사업장은 연장·야간·휴일 가산수당(50%)이 미적용됩니다. "
                "단, 소정근로시간 외 근로에 대한 기본 임금은 반드시 지급해야 합니다. "
                "취업규칙·근로계약에 가산수당을 명시한 경우 지급 의무 발생."
            ),
            basis="근로기준법 제11조, 제56조",
            priority=2,
        ))

    # 포괄임금제에서 실제 연장 > 포함 연장인 경우
    if inp.wage_type == WageType.COMPREHENSIVE and inp.comprehensive_breakdown:
        included_ot_h = inp.comprehensive_breakdown.get("included_overtime_hours", 0)
        actual_ot_monthly = s.weekly_overtime_hours * (365 / 7 / 12)
        if included_ot_h > 0 and actual_ot_monthly > included_ot_h:
            hints.append(LegalHint(
                category="연장수당",
                condition=(
                    f"포괄임금 포함 연장 {included_ot_h:.0f}h/월 "
                    f"< 실제 연장 {actual_ot_monthly:.1f}h/월"
                ),
                hint=(
                    f"포괄임금에 포함된 연장근로시간({included_ot_h:.0f}h/월)보다 실제 "
                    f"연장근로({actual_ot_monthly:.1f}h/월)가 초과하는 경우, "
                    f"초과분에 대한 추가 수당을 청구할 수 있습니다."
                ),
                basis="근로기준법 제56조, 대법원 2016다243078",
                priority=1,
            ))

    return hints


# ── 포괄임금제 관련 힌트 ─────────────────────────────────────────────────────

def _hints_comprehensive(inp: WageInput) -> list[LegalHint]:
    hints = []

    if inp.wage_type == WageType.COMPREHENSIVE:
        hints.append(LegalHint(
            category="포괄임금제",
            condition="포괄임금제 근로계약",
            hint=(
                "포괄임금제는 근로시간 산정이 어려운 경우에만 허용됩니다(대법원 2021다201143). "
                "사무직·일반 근로자의 포괄임금제는 무효일 수 있습니다. "
                "실제 연장근로가 포함 금액을 초과하면 추가 수당 청구 가능."
            ),
            basis="대법원 2016다243078, 2021다201143",
            priority=2,
        ))

    return hints


# ── 5인 미만 사업장 관련 힌트 ────────────────────────────────────────────────

def _hints_small_business(inp: WageInput) -> list[LegalHint]:
    hints = []

    if inp.business_size == BusinessSize.UNDER_5:
        # 연차·공휴일 미적용 안내 (start_date가 있으면 연차 관련)
        if inp.start_date:
            hints.append(LegalHint(
                category="연차휴가",
                condition="5인 미만 사업장 — 연차휴가 규정 미적용",
                hint=(
                    "5인 미만 사업장은 근로기준법 제60조(연차 유급휴가)가 적용되지 않습니다. "
                    "단, 취업규칙·근로계약에 연차를 명시한 경우 약정 연차로 인정됩니다."
                ),
                basis="근로기준법 제11조, 제60조",
                priority=2,
            ))

    return hints


# ── 포맷 출력 ─────────────────────────────────────────────────────────────────

def format_hints(hints: list[LegalHint]) -> str:
    """힌트 목록을 읽기 쉬운 텍스트로 변환"""
    if not hints:
        return ""

    lines = ["── 법률 검토 포인트 (참고용, 법적 판단 아님) ──"]
    for i, h in enumerate(hints, 1):
        mark = "🔴" if h.priority == 1 else "🟡"
        lines.append(f"\n{mark} [{h.category}] #{i}")
        lines.append(f"   상황: {h.condition}")
        lines.append(f"   검토: {h.hint}")
        lines.append(f"   근거: {h.basis}")

    lines.append(
        "\n⚠️ 위 내용은 참고용이며 법적 판단이 아닙니다. "
        "정확한 판단은 고용노동부(1350) 또는 노무사에게 문의하세요."
    )
    return "\n".join(lines)
