"""판례 검색 쿼리 확장 모듈

Analyzer가 추출한 precedent_keywords + relevant_laws + consultation_topic을
조합하여 법제처 판례 API에 보낼 검색 쿼리 리스트를 생성한다.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ── 법조문 → 쟁점 키워드 역매핑 ─────────────────────────────────────────────
LAW_TO_ISSUE: dict[str, list[str]] = {
    "근로기준법 제23조": ["부당해고", "해고 제한"],
    "근로기준법 제26조": ["해고예고", "해고예고수당"],
    "근로기준법 제27조": ["해고 서면통지"],
    "근로기준법 제28조": ["부당해고 구제신청"],
    "근로기준법 제36조": ["금품 청산", "임금 체불"],
    "근로기준법 제43조": ["임금 지급", "임금 체불"],
    "근로기준법 제46조": ["휴업수당"],
    "근로기준법 제50조": ["근로시간", "법정근로시간"],
    "근로기준법 제51조": ["탄력적 근로시간제"],
    "근로기준법 제53조": ["연장근로 제한"],
    "근로기준법 제55조": ["휴일", "주휴일"],
    "근로기준법 제56조": ["연장근로수당", "야간근로수당", "휴일근로수당", "가산임금"],
    "근로기준법 제57조": ["보상휴가"],
    "근로기준법 제60조": ["연차 유급휴가", "연차수당"],
    "근로기준법 제61조": ["연차 사용 촉진"],
    "근로기준법 제2조": ["통상임금", "평균임금"],
    "근로기준법 제18조": ["단시간근로자", "초단시간근로"],
    "근로기준법 제76조의2": ["직장 내 괴롭힘"],
    "근로기준법 제76조의3": ["직장 내 괴롭힘 조치"],
    "최저임금법 제6조": ["최저임금", "최저임금 산입범위"],
    "근로자퇴직급여 보장법 제4조": ["퇴직급여", "퇴직연금"],
    "근로자퇴직급여 보장법 제8조": ["퇴직금", "퇴직금 산정"],
    "고용보험법 제40조": ["실업급여", "구직급여"],
    "고용보험법 제45조": ["구직급여 산정"],
    "고용보험법 제69조": ["육아휴직급여"],
    "고용보험법 제10조": ["고용보험 적용 제외", "65세 이상"],
    "산업재해보상보험법 제37조": ["업무상 재해", "산재"],
    "산업재해보상보험법 제125조": ["특수형태근로종사자"],
    "임금채권보장법 제7조": ["대지급금", "체당금"],
    "기간제법 제4조": ["기간제 근로자", "무기계약 전환"],
    "남녀고용평등법 제19조의2": ["육아기 근로시간 단축"],
}

# ── 주제별 기본 판례 검색 키워드 ──────────────────────────────────────────────
TOPIC_DEFAULT_KEYWORDS: dict[str, list[str]] = {
    "해고·징계": ["부당해고", "해고 제한", "해고예고"],
    "임금·통상임금": ["통상임금", "평균임금", "임금 체불"],
    "근로시간·휴일": ["연장근로", "야간근로", "휴일근로", "가산임금"],
    "퇴직·퇴직금": ["퇴직금 산정", "평균임금", "퇴직금 중간정산"],
    "연차휴가": ["연차 유급휴가", "연차수당", "사용 촉진"],
    "산재보상": ["업무상 재해", "산재 인정", "출퇴근 재해"],
    "비정규직": ["기간제 근로자", "차별 시정", "무기계약"],
    "직장내괴롭힘": ["직장 내 괴롭힘", "사용자 조치 의무"],
    "근로계약": ["근로조건 명시", "근로계약 위반"],
    "고용보험": ["실업급여", "구직급여", "수급 자격"],
    "기타": [],
}


def build_precedent_queries(
    precedent_keywords: list[str],
    relevant_laws: list[str] | None = None,
    consultation_topic: str | None = None,
    max_queries: int = 3,
) -> list[str]:
    """판례 검색용 쿼리 리스트 생성 (최대 max_queries개).

    전략:
    1. precedent_keywords를 핵심 쿼리로 합침
    2. relevant_laws에서 쟁점 키워드를 추출하여 보조 쿼리 생성
    3. consultation_topic 기본 키워드로 보충 쿼리 생성
    중복 쿼리 제거 후 max_queries개 반환.
    """
    queries: list[str] = []
    seen_terms: set[str] = set()

    # 1. 핵심 쿼리: precedent_keywords 합침
    if precedent_keywords:
        core_query = " ".join(precedent_keywords[:4])
        queries.append(core_query)
        seen_terms.update(precedent_keywords)

    # 2. 법조문 역매핑 쿼리
    if relevant_laws:
        law_issues: list[str] = []
        for law_ref in relevant_laws:
            for law_key, issues in LAW_TO_ISSUE.items():
                if law_key in law_ref:
                    for issue in issues:
                        if issue not in seen_terms:
                            law_issues.append(issue)
                            seen_terms.add(issue)
        if law_issues and len(queries) < max_queries:
            queries.append(" ".join(law_issues[:4]))

    # 3. 주제 기본 키워드 보충
    if consultation_topic and len(queries) < max_queries:
        topic_kws = TOPIC_DEFAULT_KEYWORDS.get(consultation_topic, [])
        unseen = [kw for kw in topic_kws if kw not in seen_terms]
        if unseen:
            queries.append(" ".join(unseen[:3]))

    logger.info("판례 쿼리 확장: keywords=%s → queries=%s",
                precedent_keywords, queries)

    return queries[:max_queries]
