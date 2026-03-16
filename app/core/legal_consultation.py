"""법률상담 전용 모듈 — 법제처 API 법조문 조회 + 컨텍스트 조립

계산이 필요 없는 법률상담 질문(해고, 퇴직금, 근로시간 등)에 대해
법제처 API로 현행 법조문을 조회하여 LLM 컨텍스트를 구성한다.
"""

from __future__ import annotations

import logging

from app.config import AppConfig
from app.core.legal_api import fetch_relevant_articles

logger = logging.getLogger(__name__)

# ── 주제별 기본 법조문 설정 ──────────────────────────────────────────────────

TOPIC_SEARCH_CONFIG: dict[str, dict] = {
    "해고·징계": {
        "default_laws": [
            "근로기준법 제23조",    # 해고 등의 제한
            "근로기준법 제26조",    # 해고의 예고
            "근로기준법 제27조",    # 해고사유 등의 서면통지
            "근로기준법 제28조",    # 부당해고등의 구제신청
        ],
    },
    "임금·통상임금": {
        "default_laws": [
            "근로기준법 제2조",     # 정의 (평균임금, 통상임금)
            "근로기준법 제43조",    # 임금 지급
            "근로기준법 제36조",    # 금품 청산
            "근로기준법 제46조",    # 휴업수당
            "최저임금법 제6조",     # 최저임금의 적용 (제5항 택시 특례 포함)
        ],
    },
    "근로시간·휴일": {
        "default_laws": [
            "근로기준법 제50조",    # 근로시간
            "근로기준법 제53조",    # 연장 근로의 제한
            "근로기준법 제55조",    # 휴일
            "근로기준법 제56조",    # 연장·야간 및 휴일 근로
            "근로기준법 제57조",    # 보상 휴가제
            "근로기준법 제18조",    # 단시간근로자의 근로조건
        ],
    },
    "퇴직·퇴직금": {
        "default_laws": [
            "근로자퇴직급여 보장법 제4조",  # 퇴직급여제도의 설정
            "근로자퇴직급여 보장법 제8조",  # 퇴직금제도의 설정 등
            "임금채권보장법 제7조",          # 간이대지급금
        ],
    },
    "연차휴가": {
        "default_laws": [
            "근로기준법 제60조",    # 연차 유급휴가
            "근로기준법 제61조",    # 연차 유급휴가의 사용 촉진
        ],
    },
    "산재보상": {
        "default_laws": [
            "산업재해보상보험법 제37조",    # 업무상의 재해의 인정 기준
            "산업재해보상보험법 제125조",   # 특수형태근로종사자에 대한 특례
        ],
    },
    "비정규직": {
        "default_laws": [
            "기간제 및 단시간근로자 보호 등에 관한 법률 제4조",  # 기간제근로자의 사용
        ],
    },
    "노동조합": {
        "default_laws": [],
    },
    "직장내괴롭힘": {
        "default_laws": [
            "근로기준법 제76조의2",  # 직장 내 괴롭힘의 금지
            "근로기준법 제76조의3",  # 직장 내 괴롭힘 발생 시 조치
            "남녀고용평등과 일·가정 양립 지원에 관한 법률 제14조의2",  # 고객 등에 의한 성희롱 방지
        ],
    },
    "근로계약": {
        "default_laws": [
            "근로기준법 제17조",    # 근로조건의 명시
        ],
    },
    "고용보험": {
        "default_laws": [
            "고용보험법 제40조",    # 구직급여의 수급 요건
            "고용보험법 제45조",    # 이직 전 평균임금 일액의 산정
            "고용보험법 제69조",    # 육아휴직 급여
        ],
    },
    "기타": {
        "default_laws": [],
    },
}


# ── 컨텍스트 조립 ─────────────────────────────────────────────────────────────

def build_consultation_context(
    legal_articles_text: str | None = None,
) -> str:
    """법조문을 LLM 컨텍스트로 구성."""
    if not legal_articles_text:
        return ""
    return f"현행 법조문 (법제처 국가법령정보센터 조회):\n\n{legal_articles_text}"


# ── 통합 조회 함수 (pipeline.py에서 호출) ─────────────────────────────────────

def process_consultation(
    query: str,
    consultation_topic: str | None,
    relevant_laws: list[str],
    config: AppConfig,
) -> tuple[str, list[dict]]:
    """법률상담 전용 처리 — 법제처 API 법조문 조회.

    Returns:
        (context_text, source_hits) — LLM 컨텍스트 + 빈 목록 (하위 호환)
    """
    topic_config = TOPIC_SEARCH_CONFIG.get(
        consultation_topic or "기타",
        TOPIC_SEARCH_CONFIG["기타"],
    )

    # 1. 법조문 목록: LLM 추출 + 주제별 기본값 병합
    all_laws = list(relevant_laws or [])
    for law in topic_config["default_laws"]:
        if law not in all_laws:
            all_laws.append(law)

    # 2. 법조문 API 조회 (법제처 국가법령정보센터)
    legal_articles_text = None
    if all_laws and config.law_api_key:
        try:
            legal_articles_text = fetch_relevant_articles(all_laws, config.law_api_key)
        except Exception as e:
            logger.warning("법령 API 조회 실패: %s", e)

    # 3. 컨텍스트 조립
    context = build_consultation_context(legal_articles_text)

    return context, []
