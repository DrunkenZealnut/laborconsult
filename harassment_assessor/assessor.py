"""
직장 내 괴롭힘 3요소 판정 엔진

근로기준법 제76조의2 기반:
  ① 직장에서의 지위 또는 관계 등의 우위를 이용
  ② 업무상 적정 범위를 넘는 행위
  ③ 신체적·정신적 고통을 주거나 근무환경을 악화시키는 행위
"""

from .models import HarassmentInput
from .result import ElementAssessment, AssessmentResult
from .constants import (
    BEHAVIOR_TYPE_KEYWORDS,
    SUPERIORITY_SCORES,
    ROLE_KEYWORDS,
    MAJORITY_KEYWORDS,
    BEYOND_SCOPE_FACTORS,
    FREQUENCY_MULTIPLIER,
    DURATION_MULTIPLIER,
    IMPACT_KEYWORDS,
    LIKELIHOOD_HIGH,
    LIKELIHOOD_MEDIUM,
    E1_MET, E1_UNCLEAR,
    E2_MET, E2_UNCLEAR,
    E3_MET, E3_UNCLEAR,
    LEGAL_REFERENCES,
    CUSTOMER_HARASSMENT_LEGAL,
    RESPONSE_STEPS,
)


def assess_harassment(inp: HarassmentInput) -> AssessmentResult:
    """
    직장 내 괴롭힘 3요소 판정

    Returns:
        AssessmentResult with 3-element assessment, likelihood, legal basis, response steps
    """
    # 0. 고객 괴롭힘 사전 체크
    if _check_customer_harassment(inp):
        return _build_customer_result(inp)

    # 1. 행위 유형 보강 (description에서 추가 감지)
    all_types = _detect_behavior_types(inp)

    # 2. 3요소 판정
    e1 = _assess_superiority(inp)
    e2 = _assess_beyond_scope(inp, all_types)
    e3 = _assess_harm(inp, all_types)

    # 3. 종합 점수
    overall, likelihood = _calculate_overall(e1, e2, e3)

    # 4. 주의사항
    warnings = _generate_warnings(inp, e1, e2, e3, likelihood)

    return AssessmentResult(
        element_1_superiority=e1,
        element_2_beyond_scope=e2,
        element_3_harm=e3,
        likelihood=likelihood,
        overall_score=overall,
        behavior_types_detected=all_types,
        legal_basis=list(LEGAL_REFERENCES),
        response_steps=list(RESPONSE_STEPS),
        warnings=warnings,
    )


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────


def _check_customer_harassment(inp: HarassmentInput) -> bool:
    """고객 괴롭힘 여부 판별"""
    if inp.relationship_type == "고객":
        return True
    customer_kw = ["고객", "민원인", "손님", "환자", "학부모", "이용자"]
    role = inp.perpetrator_role.lower()
    return any(kw in role for kw in customer_kw)


def _build_customer_result(inp: HarassmentInput) -> AssessmentResult:
    """고객 괴롭힘 결과 생성"""
    warnings = [
        "사업주는 고객 등에 의한 폭언 등으로부터 근로자를 보호할 의무가 있습니다 (산안법 제41조).",
        "업무의 일시적 중단, 전환, 휴식 부여 등 보호조치를 사업주에게 요청할 수 있습니다.",
    ]
    return AssessmentResult(
        is_customer_harassment=True,
        legal_basis=list(CUSTOMER_HARASSMENT_LEGAL),
        warnings=warnings,
    )


def _detect_behavior_types(inp: HarassmentInput) -> list[str]:
    """입력된 behavior_types + description에서 추가 유형 감지"""
    types = set(inp.behavior_types)
    text = f"{inp.behavior_description} {inp.impact}".lower()
    for btype, keywords in BEHAVIOR_TYPE_KEYWORDS.items():
        if btype not in types:
            if any(kw in text for kw in keywords):
                types.add(btype)
    return sorted(types)


def _infer_relationship(inp: HarassmentInput) -> tuple[str, str]:
    """perpetrator_role/victim_role에서 relationship_type 추론. (type, reasoning) 반환."""
    # 명시적 relationship_type이 있으면 그대로
    if inp.relationship_type and inp.relationship_type in SUPERIORITY_SCORES:
        return inp.relationship_type, f"관계유형 '{inp.relationship_type}' 명시"

    combined = f"{inp.perpetrator_role} {inp.victim_role} {inp.behavior_description}"

    # 인원수 우위 키워드
    if any(kw in combined for kw in MAJORITY_KEYWORDS):
        return "다수_소수", f"인원수 우위 감지 ('{inp.perpetrator_role}')"

    # 직위 키워드
    for kw, rtype in ROLE_KEYWORDS.items():
        if kw in inp.perpetrator_role:
            return rtype, f"가해자 '{inp.perpetrator_role}' → {rtype}"

    # 비정규직 관계
    perp = inp.perpetrator_role.lower()
    vict = inp.victim_role.lower()
    if "정규" in perp and ("계약" in vict or "비정규" in vict or "파견" in vict):
        return "정규직_비정규직", f"정규직→비정규직 고용형태 우위"

    # 기본: 동료
    if inp.perpetrator_role:
        return "동료", f"가해자 '{inp.perpetrator_role}' — 우위 관계 불분명"
    return "동료", "관계 정보 부족 — 동료 관계로 가정"


def _assess_superiority(inp: HarassmentInput) -> ElementAssessment:
    """요소1: 지위·관계 우위 평가"""
    rtype, reasoning = _infer_relationship(inp)
    score = SUPERIORITY_SCORES.get(rtype, 0.3)

    if score >= E1_MET:
        status = "해당"
    elif score >= E1_UNCLEAR:
        status = "불분명"
    else:
        status = "미해당"

    return ElementAssessment(
        element_name="① 지위·관계 우위",
        status=status,
        score=score,
        reasoning=reasoning,
    )


def _assess_beyond_scope(inp: HarassmentInput, all_types: list[str]) -> ElementAssessment:
    """요소2: 업무 적정범위 초과 평가"""
    if not all_types:
        return ElementAssessment(
            element_name="② 업무 적정범위 초과",
            status="불분명",
            score=0.2,
            reasoning="구체적 행위 유형이 감지되지 않음",
        )

    # 유형별 최대 점수
    type_score = max(BEYOND_SCOPE_FACTORS.get(t, 0.5) for t in all_types)

    # 빈도·기간 가중
    freq_w = FREQUENCY_MULTIPLIER.get(inp.frequency, 0.5)
    dur_w = DURATION_MULTIPLIER.get(inp.duration, 0.5)
    temporal_w = max(freq_w, dur_w)

    score = min(1.0, type_score * temporal_w)

    if score >= E2_MET:
        status = "해당"
    elif score >= E2_UNCLEAR:
        status = "불분명"
    else:
        status = "미해당"

    # 판정 근거 텍스트
    types_label = {
        "폭행_협박": "폭행·협박", "폭언_모욕": "폭언·모욕",
        "따돌림_무시": "따돌림·무시", "부당업무": "부당한 업무 지시",
        "사적용무": "사적 용무 강요", "감시_통제": "감시·통제",
        "부당인사": "부당 인사",
    }
    type_names = ", ".join(types_label.get(t, t) for t in all_types)
    freq_part = f", 빈도: {inp.frequency}" if inp.frequency else ""
    dur_part = f", 기간: {inp.duration}" if inp.duration else ""
    reasoning = f"행위 유형: {type_names}{freq_part}{dur_part}"

    return ElementAssessment(
        element_name="② 업무 적정범위 초과",
        status=status,
        score=score,
        reasoning=reasoning,
    )


def _assess_harm(inp: HarassmentInput, all_types: list[str]) -> ElementAssessment:
    """요소3: 고통·근무환경 악화 평가"""
    score = 0.0

    # 행위 유형 기본 점수
    if all_types:
        score = 0.5
    if "폭행_협박" in all_types:
        score += 0.3
    if "따돌림_무시" in all_types:
        score += 0.2

    # impact 키워드 가산
    impact_text = f"{inp.impact} {inp.behavior_description}".lower()
    for kw, bonus in IMPACT_KEYWORDS.items():
        if kw in impact_text:
            score += bonus

    # 기간 가산
    dur_w = DURATION_MULTIPLIER.get(inp.duration, 0.0)
    if dur_w >= 0.8:
        score += 0.1

    score = min(1.0, score)

    if score >= E3_MET:
        status = "해당"
    elif score >= E3_UNCLEAR:
        status = "불분명"
    else:
        status = "미해당"

    # 근거
    parts = []
    if all_types:
        parts.append("행위 유형에 의한 고통 추정")
    if inp.impact:
        parts.append(f"피해 결과: {inp.impact}")
    if not parts:
        parts.append("구체적 피해 정보 부족")
    reasoning = ", ".join(parts)

    return ElementAssessment(
        element_name="③ 고통·근무환경 악화",
        status=status,
        score=score,
        reasoning=reasoning,
    )


def _calculate_overall(e1: ElementAssessment, e2: ElementAssessment,
                       e3: ElementAssessment) -> tuple[float, str]:
    """
    종합 점수 산출 및 가능성 수준 결정

    가중치: e1(30%) + e2(35%) + e3(35%)
    """
    overall = (e1.score * 0.30) + (e2.score * 0.35) + (e3.score * 0.35)

    # 예외1: 3요소 모두 "해당"이면 무조건 "높음"
    if e1.status == "해당" and e2.status == "해당" and e3.status == "해당":
        return max(overall, LIKELIHOOD_HIGH), "높음"

    # 예외2: 요소1 "미해당"이면 최대 "보통"
    if e1.status == "미해당":
        if overall >= LIKELIHOOD_MEDIUM:
            return overall, "보통"
        return overall, "낮음"

    if overall >= LIKELIHOOD_HIGH:
        return overall, "높음"
    if overall >= LIKELIHOOD_MEDIUM:
        return overall, "보통"
    return overall, "낮음"


def _generate_warnings(inp: HarassmentInput,
                       e1: ElementAssessment, e2: ElementAssessment,
                       e3: ElementAssessment, likelihood: str) -> list[str]:
    """상황별 주의사항 생성"""
    warnings = []

    # 증거 관련
    if not inp.evidence:
        warnings.append(
            "증거 확보가 중요합니다. 대화 참여자로서의 녹음은 합법이며, "
            "문자·이메일·메신저 캡처, 목격자 진술, 진단서 등을 준비하세요."
        )

    # 1회성
    if inp.frequency == "1회" or inp.duration == "1회성":
        warnings.append(
            "1회 행위도 괴롭힘으로 인정될 수 있으나, "
            "반복·지속적 행위일수록 입증이 용이합니다."
        )

    # 5인 미만
    if inp.business_size == "5인미만":
        warnings.append(
            "직장 내 괴롭힘 금지(제76조의2)는 사업장 규모와 관계없이 모든 사업장에 적용됩니다. "
            "다만, 5인 미만 사업장은 제76조의3 조사·조치 의무 위반 과태료 부과 대상입니다."
        )

    # 회사 미조치
    if inp.company_response in ("미조치", ""):
        if likelihood in ("높음", "보통"):
            warnings.append(
                "사용자가 괴롭힘 신고 후 조사·조치를 하지 않으면 "
                "500만원 이하 과태료 대상입니다 (제116조 제2항)."
            )

    # 불리한 처우
    if "불리한" in inp.company_response or "보복" in inp.company_response:
        warnings.append(
            "괴롭힘 신고를 이유로 해고 등 불리한 처우를 받은 경우, "
            "3년 이하 징역/3천만원 이하 벌금에 해당합니다 (제109조 제2항)."
        )

    # 우위 관계 불분명
    if e1.status == "불분명":
        warnings.append(
            "지위·관계 우위가 불분명합니다. 직급 외에도 정규직/비정규직, "
            "인원수, 연령, 근속연수 등 다양한 우위가 인정될 수 있습니다."
        )

    return warnings
