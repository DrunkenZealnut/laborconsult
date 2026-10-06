"""
직장 내 괴롭힘 3요소 판정 엔진

근로기준법 제76조의2 기반:
  ① 직장에서의 지위 또는 관계 등의 우위를 이용
  ② 업무상 적정 범위를 넘는 행위
  ③ 신체적·정신적 고통을 주거나 근무환경을 악화시키는 행위
"""

import math
import re

from .models import HarassmentInput, Likelihood
from .result import ElementAssessment, AssessmentResult
from .constants import (
    BEHAVIOR_TYPE_PATTERNS,
    SUPERIORITY_SCORES,
    ROLE_KEYWORDS,
    MAJORITY_RE,
    BEYOND_SCOPE_FACTORS,
    FREQUENCY_MULTIPLIER,
    DURATION_MULTIPLIER,
    IMPACT_PATTERNS,
    HOLD_REQUIRED_FACTS,
    LIKELIHOOD_HIGH,
    LIKELIHOOD_MEDIUM,
    E1_MET, E1_UNCLEAR,
    E2_MET, E2_UNCLEAR,
    E3_MET, E3_UNCLEAR,
    LEGAL_REFERENCES,
    CUSTOMER_HARASSMENT_LEGAL,
    SMALL_WORKPLACE_LEGAL,
    SMALL_WORKPLACE_STEPS,
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

    # 상시 4명 이하는 근로기준법 괴롭힘 규정 미적용 — 법적 근거·대응 절차도 그에 맞춘다.
    # 경고만 바꾸고 이 둘을 그대로 두면 한 결과 안에 "적용되지 않습니다"와 벌칙·과태료가 공존한다.
    legal_basis, steps = _legal_basis_and_steps(inp.business_size)
    return AssessmentResult(
        element_1_superiority=e1,
        element_2_beyond_scope=e2,
        element_3_harm=e3,
        likelihood=likelihood,
        overall_score=overall,
        behavior_types_detected=all_types,
        legal_basis=legal_basis,
        response_steps=steps,
        warnings=warnings,
    )


def _legal_basis_and_steps(business_size: str) -> tuple[list[str], list[dict]]:
    """사업장 규모 3상태에 맞춘 법적 근거·대응 절차(판정·판단 보류 공용).

    상시 4명 이하는 근로기준법 괴롭힘 규정 미적용 — 경고만 바꾸고 근거·절차를 그대로 두면 한 결과 안에
    "적용되지 않습니다"와 벌칙·과태료가 공존한다. 규모 미확정이면 조건은 조문 전체가 아니라 괄호 안의
    **이 용도**에 단다 — 제109조 제1항·제116조 제2항은 괴롭힘 외 다른 조항 위반도 함께 규정한다
    (CodeRabbit PR #98, 법제처 현행판).
    """
    size = _workplace_size_class(business_size)
    if size == "small":
        return list(SMALL_WORKPLACE_LEGAL), list(SMALL_WORKPLACE_STEPS)
    if size == "unknown":
        legal_basis = [ref.replace(" (", " (상시 5명 이상 사업장의 ", 1) for ref in LEGAL_REFERENCES]
        legal_basis.append(SMALL_WORKPLACE_LEGAL[0])   # 적용 조건의 근거(시행령 별표 1)
        steps = [dict(st, description=_IF_COVERED + st["description"]) if st.get("covered_only") else dict(st)
                 for st in RESPONSE_STEPS]
        return legal_basis, steps
    return list(LEGAL_REFERENCES), list(RESPONSE_STEPS)


_HOLD_REASON_TEXT = {
    "no_behavior": "질문에서 구체적인 괴롭힘 행위가 확인되지 않아 판정하지 않았습니다.",
    "no_actor": "행위자와의 관계가 확인되지 않아 판정하지 않았습니다.",
}


def held_assessment(inp: HarassmentInput, reason: str) -> AssessmentResult:
    """판단 보류 — 사안은 서술됐지만 판정에 필요한 사실(행위·행위자)이 질문에서 확인되지 않을 때.

    3요소를 "확인 필요"로 두고 필요한 사실을 안내한다. 법적 근거·대응 절차는 판정과 같은
    사업장 규모 3상태 규칙을 따른다 — 요건 설명과 증거 확보 안내는 보류여도 유효하다.
    """
    pending = ElementAssessment(status="확인 필요", reasoning="질문에서 확인되지 않음")
    legal_basis, steps = _legal_basis_and_steps(inp.business_size)
    warnings = [_HOLD_REASON_TEXT.get(reason, _HOLD_REASON_TEXT["no_behavior"]),
                "판단에 필요한 사실: " + " / ".join(HOLD_REQUIRED_FACTS)]
    return AssessmentResult(
        element_1_superiority=ElementAssessment(element_name="① 지위·관계 우위", **_pending_fields(pending)),
        element_2_beyond_scope=ElementAssessment(element_name="② 업무 적정범위 초과", **_pending_fields(pending)),
        element_3_harm=ElementAssessment(element_name="③ 고통·근무환경 악화", **_pending_fields(pending)),
        likelihood=Likelihood.HOLD.value,
        legal_basis=legal_basis,
        response_steps=steps,
        warnings=warnings,
    )


def _pending_fields(e: ElementAssessment) -> dict:
    return {"status": e.status, "score": 0.0, "reasoning": e.reasoning}


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────


# 규모 미확정일 때 5명 이상 전용 안내(경고·대응 절차) 앞에 붙이는 적용 조건
_IF_COVERED = "상시 5명 이상 사업장이라면, "

_SIZE_RE = re.compile(
    # 범위 "4~5명"·"4명에서 5명"·"4, 5명" — 단위는 한쪽에만 있어도 된다
    r"(?<!\d)(?P<lo>\d+)(?P<u1>인|명)?(?:~|∼|〜|-|–|—|,|에서|또는|혹은)(?P<hi>\d+)(?P<u2>인|명)?"
    # 단일 인원수 + 비교어·근사 표현 "5인 미만"·"약 5명"·"5명 내외"·"10여 명"
    r"|(?<!\d)(?P<pre>약|대략)?(?P<n>\d+)(?P<yeo>여)?(?:인|명)"
    r"(?P<cmp>미만|이하|이상|초과|내외|안팎|정도|가량|쯤|전후|남짓)?"
)


def _size_bounds(m: re.Match) -> tuple[float, float] | None:
    """인원수 표현 하나 → 가능한 상시 근로자 수 구간 [하한, 상한]. 단위 없는 범위는 인원수가 아니다."""
    if m.group("lo"):
        if not (m.group("u1") or m.group("u2")):
            return None
        lo, hi = sorted((int(m.group("lo")), int(m.group("hi"))))
        return lo, hi
    n, cmp_ = int(m.group("n")), m.group("cmp")
    if cmp_ == "미만":
        return 0, n - 1
    if cmp_ == "이하":
        return 0, n
    if cmp_ == "이상":
        return n, math.inf
    if cmp_ == "초과":
        return n + 1, math.inf
    if cmp_ or m.group("pre") or m.group("yeo"):   # 근사 표현 — 앞뒤 1명까지 열어 둔다
        return n - 1, n + 1
    return n, n


def _workplace_size_class(business_size: str) -> str:
    """상시 근로자 수가 5명 기준선의 어느 쪽인지: "small"(4명 이하 확정) / "covered"(5명 이상 확정)
    / "unknown"(미기재·해석 불가·기준선을 걸치는 범위).

    도구 인자는 자유 문자열이라 인원수 표현을 **구간**으로 해석한다(CodeRabbit PR #98):
    - 부분문자열로 보면 "15인 미만"이 "5인미만"을 포함해 소규모로 오분류된다. 반대로 5명 이상으로
      단정해서도 안 된다 — 1~14명에 4명 이하가 들어 있다.
    - 숫자 하나만 집으면 "4~5명"이 5명이 되고 "5명 내외"가 확정 인원이 된다 — 기준선을 걸친다.
    - 여러 표현은 같은 인원에 대한 조건이라 교집합을 취한다. "5인 이상 30인 미만"은 5~29명이고,
      "본사 30명, 지점 3명"처럼 서로 어긋나면 비어서 unknown이다.
    - 천 단위 쉼표를 먼저 지운다 — 남겨 두면 "1,000명"이 "000명", 즉 0명으로 읽힌다.
    """
    text = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", re.sub(r"\s+", "", business_size or ""))
    lo, hi, found = 0, math.inf, False
    for m in _SIZE_RE.finditer(text):
        bounds = _size_bounds(m)
        if bounds is None:
            continue
        lo, hi, found = max(lo, bounds[0]), min(hi, bounds[1]), True
    if not found or lo > hi:
        return "unknown"
    if hi <= 4:
        return "small"
    if lo >= 5:
        return "covered"
    return "unknown"


def _is_small_workplace(business_size: str) -> bool:
    """상시 4명 이하로 **확정되는** 경우만 True — 적용 제외는 확인될 때만 판단한다."""
    return _workplace_size_class(business_size) == "small"


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
    """입력된 behavior_types + description에서 추가 유형 감지.

    근거 검증을 거친 입력(grounded)은 **넘겨받은 유형이 단일 출처**다 — 여기서 다시 찾으면
    불리한 처우 문맥이라 뺀 '전보'가 되살아난다(design-validator H2). 그 외(직접 호출)만 감지한다.
    """
    types = set(inp.behavior_types)
    if inp.grounded:
        return sorted(types)
    text = f"{inp.behavior_description} {inp.impact}"
    types |= {t for t, rx in BEHAVIOR_TYPE_PATTERNS.items() if rx.search(text)}
    return sorted(types)


def _infer_relationship(inp: HarassmentInput) -> tuple[str, str]:
    """perpetrator_role/victim_role에서 relationship_type 추론. (type, reasoning) 반환."""
    # 명시적 relationship_type이 있으면 그대로
    if inp.relationship_type and inp.relationship_type in SUPERIORITY_SCORES:
        return inp.relationship_type, f"관계유형 '{inp.relationship_type}' 명시"

    combined = f"{inp.perpetrator_role} {inp.victim_role} {inp.behavior_description}"

    # 인원수 우위 키워드
    if MAJORITY_RE.search(combined):
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

    # impact 키워드 가산 — grounded 입력은 질문에서 찾은 피해 표현(impact)만 본다
    impact_text = inp.impact if inp.grounded else f"{inp.impact} {inp.behavior_description}"
    for rx, bonus, _label in IMPACT_PATTERNS:
        if rx.search(impact_text):
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

    # "높음"은 3요소가 모두 "해당"일 때만 — 괴롭힘은 세 요건을 모두 갖춰야 성립한다.
    # 종합 점수만으로 "높음"을 내면 요소가 '불분명'이어도 단정이 된다(3차 재평가 9번: ①해당·②불분명·③해당
    # → 0.67 "높음", claim-authority-and-assessor-facts D9).
    if e1.status == "해당" and e2.status == "해당" and e3.status == "해당":
        return max(overall, LIKELIHOOD_HIGH), "높음"
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

    # 5인 미만 — 상시 4명 이하 사업장에는 근로기준법의 직장 내 괴롭힘 규정(제6장의2:
    # 제76조의2·제76조의3)이 **적용되지 않는다**. 적용 규정은 시행령 제7조 별표 1인데 그 표에
    # 제6장의2가 없다(2026-10-04 법제처 eflaw 현행판 별표 1 대조). 구 문구("규모와 관계없이 모든
    # 사업장에 적용 … 5인 미만도 과태료 대상")는 반대였고, 판정 결과가 답변 컨텍스트에 그대로 들어갔다.
    size = _workplace_size_class(inp.business_size)
    small = size == "small"
    if small:
        warnings.append(
            "상시 4명 이하 사업장에는 근로기준법의 직장 내 괴롭힘 규정(제76조의2·제76조의3)과 그 위반 "
            "벌칙·과태료가 적용되지 않습니다(근로기준법 시행령 제7조 별표 1). 괴롭힘 행위는 민사상 "
            "손해배상이나 폭행·모욕 등 형사 절차로 다퉈야 할 수 있습니다."
        )

    elif size == "unknown":
        # 규모 미확정 — 적용 여부가 상시 근로자 수에 달려 있으니 단정하지 않는다(2차 재평가 9번 지적:
        # "5인 미만 사업장에서는 제76조의2·3이 적용되지 않는 범위를 확인하지 않았다").
        warnings.append(
            "상시 근로자 수를 먼저 확인해야 합니다. 상시 4명 이하 사업장에는 근로기준법의 직장 내 "
            "괴롭힘 규정(제76조의2·제76조의3)과 그 위반 벌칙·과태료가 적용되지 않습니다"
            "(근로기준법 시행령 제7조 별표 1)."
        )
    # 벌칙·과태료 경고는 5명 이상 확정이면 단정, 미확정이면 조건부, 4명 이하면 내지 않는다.
    cond = "" if size == "covered" else _IF_COVERED

    # 회사 미조치 (제76조의3 조치 의무 → 제116조 제2항 과태료 — 4명 이하 사업장은 적용 제외)
    if not small and inp.company_response in ("미조치", ""):
        if likelihood in ("높음", "보통"):
            warnings.append(
                f"{cond}사용자가 괴롭힘 신고 후 조사·조치를 하지 않으면 "
                "500만원 이하 과태료 대상입니다 (제116조 제2항)."
            )

    # 불리한 처우 (제76조의3제6항 → 제109조 제1항 — 4명 이하 사업장은 적용 제외)
    if not small and ("불리한" in inp.company_response or "보복" in inp.company_response):
        warnings.append(
            f"{cond}괴롭힘 신고를 이유로 해고 등 불리한 처우를 받은 경우, "
            "3년 이하 징역/3천만원 이하 벌금에 해당합니다 (제109조 제1항)."
        )

    # 우위 관계 불분명
    if e1.status == "불분명":
        warnings.append(
            "지위·관계 우위가 불분명합니다. 직급 외에도 정규직/비정규직, "
            "인원수, 연령, 근속연수 등 다양한 우위가 인정될 수 있습니다."
        )

    return warnings
