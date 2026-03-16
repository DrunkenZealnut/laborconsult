"""판례·행정해석 인용 검증기

RAG 검색 결과에서 판례 번호를 추출하고,
LLM 응답에서 환각된 판례 번호를 감지한다.
"""

from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

# 대법원/헌재 판례 번호 정규식
# 예: "2023다302838", "대법원 2023다302838", "헌재 2021헌마1234"
_PREC_PATTERN = re.compile(
    r"(?:대법원|대법|헌법재판소|헌재)?\s*"
    r"(\d{4})\s*"
    r"([가-힣]{1,2})\s*"
    r"(\d+)"
)

# 행정해석 문서번호 정규식
# 예: "근로기준정책과-579", "임금근로시간과-1234"
_ADMIN_PATTERN = re.compile(
    r"([가-힣]+과)-(\d+)"
)


def extract_precedents_from_hits(hits: list[dict]) -> dict[str, dict]:
    """RAG 검색 결과에서 판례 번호를 구조화하여 추출.

    Returns:
        {"2023다302838": {"year": 2023, "type": "다", "number": 302838,
                          "source": "title", "title": "..."}, ...}
    """
    precedents: dict[str, dict] = {}

    for i, hit in enumerate(hits):
        title = hit.get("title", "")
        chunk = hit.get("chunk_text", "")

        for text_field, context_source in [
            (title, "title"),
            (chunk, "chunk"),
        ]:
            for match in _PREC_PATTERN.finditer(text_field):
                year = int(match.group(1))
                case_type = match.group(2)
                number = int(match.group(3))

                # 범위 검증 (합리적 범위)
                if not (1950 <= year <= 2030 and number <= 999999):
                    continue

                prec_key = f"{year}{case_type}{number}"
                if prec_key not in precedents:
                    precedents[prec_key] = {
                        "year": year,
                        "type": case_type,
                        "number": number,
                        "source": context_source,
                        "hit_index": i,
                        "title": title[:100],
                    }

    return precedents


def extract_admin_refs_from_hits(hits: list[dict]) -> dict[str, dict]:
    """RAG 검색 결과에서 행정해석 문서번호 추출."""
    admin_refs: dict[str, dict] = {}

    for i, hit in enumerate(hits):
        title = hit.get("title", "")
        chunk = hit.get("chunk_text", "")

        for text_field, context_source in [
            (title, "title"),
            (chunk, "chunk"),
        ]:
            for match in _ADMIN_PATTERN.finditer(text_field):
                ref_key = f"{match.group(1)}-{match.group(2)}"
                if ref_key not in admin_refs:
                    admin_refs[ref_key] = {
                        "department": match.group(1),
                        "number": match.group(2),
                        "source": context_source,
                        "hit_index": i,
                        "title": title[:100],
                    }

    return admin_refs


def build_available_citations_text(
    hits: list[dict],
    legal_precedents: list[dict] | None = None,
) -> str:
    """LLM에 제공할 '인용 가능한 판례 목록' 텍스트 생성.

    이 목록을 시스템 프롬프트와 함께 제공하여
    Claude가 이 목록에 없는 판례 번호를 생성하지 않도록 유도한다.
    """
    precs = extract_precedents_from_hits(hits)
    admin_refs = extract_admin_refs_from_hits(hits)

    lines = ["[인용 가능한 판례·행정해석 목록]"]
    lines.append("아래 목록에 있는 것만 번호를 인용하세요. 목록에 없는 번호는 절대 생성하지 마세요.\n")

    if precs:
        lines.append("판례:")
        for key, info in precs.items():
            lines.append(f"  - {key} (출처: {info['title']})")
    else:
        lines.append("판례: (검색 결과에서 판례를 찾지 못했습니다)")

    # 법령 API에서 조회한 판례
    if legal_precedents:
        lines.append("\n법령 API 조회 판례:")
        for prec in legal_precedents:
            case_name = prec.get("case_name", "")
            date = prec.get("date", "")
            lines.append(f"  - {case_name} ({date})")

    if admin_refs:
        lines.append("\n행정해석:")
        for key, info in admin_refs.items():
            lines.append(f"  - {key} (출처: {info['title']})")
    else:
        lines.append("\n행정해석: (검색 결과에서 행정해석을 찾지 못했습니다)")

    return "\n".join(lines)


def validate_response_citations(
    response_text: str,
    available_precedents: dict[str, dict],
    available_admin_refs: dict[str, dict] | None = None,
) -> dict:
    """생성된 답변에서 인용된 판례·행정해석 번호를 검증.

    Returns:
        {
            "total_cited": int,
            "valid": ["2023다302838", ...],
            "hallucinated": ["2006다49372", ...],
            "warnings": ["..."],
        }
    """
    result = {
        "total_cited": 0,
        "valid": [],
        "hallucinated": [],
        "warnings": [],
    }

    # 판례 번호 검증
    for match in _PREC_PATTERN.finditer(response_text):
        year = int(match.group(1))
        case_type = match.group(2)
        number = int(match.group(3))

        if not (1950 <= year <= 2030 and number <= 999999):
            continue

        prec_key = f"{year}{case_type}{number}"
        result["total_cited"] += 1

        if prec_key in available_precedents:
            result["valid"].append(prec_key)
        else:
            result["hallucinated"].append(prec_key)

    # 행정해석 검증
    if available_admin_refs is not None:
        for match in _ADMIN_PATTERN.finditer(response_text):
            ref_key = f"{match.group(1)}-{match.group(2)}"
            result["total_cited"] += 1

            if ref_key in available_admin_refs:
                result["valid"].append(ref_key)
            else:
                result["hallucinated"].append(ref_key)

    if result["hallucinated"]:
        result["warnings"].append(
            f"⚠️ {len(result['hallucinated'])}개의 판례/행정해석이 "
            f"검색 결과에서 확인되지 않았습니다: {', '.join(result['hallucinated'])}"
        )
        logger.warning(
            "판례 환각 감지: %s (유효: %s)",
            result["hallucinated"], result["valid"],
        )

    return result


def correct_hallucinated_citations(
    response_text: str,
    hallucinated: list[str],
    gemini_api_key: str | None = None,
    openai_client: object | None = None,
) -> str | None:
    """다른 LLM을 사용해 환각 판례 번호를 제거한 수정 답변을 생성.

    Gemini(우선) 또는 OpenAI를 사용하여 원본 답변에서
    환각된 판례 번호를 안전한 표현으로 대체한다.

    Returns:
        수정된 답변 텍스트. 실패 시 None.
    """
    if not hallucinated:
        return None

    hallucinated_str = ", ".join(hallucinated)

    prompt = (
        "아래 노동법 상담 답변에서 판례 번호가 잘못 인용되었습니다.\n"
        f"확인되지 않은 판례 번호: {hallucinated_str}\n\n"
        "규칙:\n"
        "1. 위 판례 번호가 포함된 문장에서 번호만 제거하고, "
        "내용은 유지하되 출처를 다음과 같이 변경하세요:\n"
        '   "관련 판례가 있을 수 있으나 구체적 번호는 '
        'law.go.kr에서 확인이 필요합니다"\n'
        "2. 나머지 답변 내용은 절대 수정하지 마세요.\n"
        "3. 마크다운 형식을 유지하세요.\n"
        "4. 수정된 전체 답변만 출력하세요. 설명이나 부가 텍스트를 추가하지 마세요.\n\n"
        "원본 답변:\n"
        f"{response_text}"
    )

    # Gemini 우선 시도
    if gemini_api_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_api_key)
            model = genai.GenerativeModel("gemini-2.5-pro")
            resp = model.generate_content(prompt)
            if resp.text:
                logger.info(
                    "Gemini 판례 교정 완료: %d개 환각 제거", len(hallucinated),
                )
                return resp.text
        except Exception as e:
            logger.warning("Gemini 판례 교정 실패: %s", e)

    # OpenAI 폴백
    if openai_client:
        try:
            resp = openai_client.chat.completions.create(
                model="o3",
                messages=[
                    {"role": "developer", "content": "당신은 텍스트 교정 도우미입니다."},
                    {"role": "user", "content": prompt},
                ],
                max_completion_tokens=3000,
            )
            text = resp.choices[0].message.content
            if text:
                logger.info(
                    "OpenAI 판례 교정 완료: %d개 환각 제거", len(hallucinated),
                )
                return text
        except Exception as e:
            logger.warning("OpenAI 판례 교정 실패: %s", e)

    return None
