"""판례·행정해석 인용 검증기

RAG 검색 결과에서 판례 번호를 추출하고,
LLM 응답에서 환각된 판례 번호를 감지한다.
"""

from __future__ import annotations

import os
import re
import logging
import time

from app.config import ANSWER_MAX_TOKENS, CITATION_STAGE_BUDGET, GEMINI_MODEL

logger = logging.getLogger(__name__)


# ── 교정 호출 타임아웃 (llm-fallback-hardening FR-07) ─────────────────────────

def _rewrite_timeout(text_len: int) -> float:
    """답변 전문 재생성에 필요한 타임아웃을 입력 길이로 추정.

    고정 5초는 실답변에서 100% 실패한다 — 2026-08-06 실측: claude-haiku-4-5가
    1,960자를 재생성하는 데 7.7초 걸렸다(약 250자/초). 안전계수 1.5를 적용해
    250/1.5 ≈ 165자/초로 잡고 [12, 40]초로 클램프한다.

    교정이 타임아웃되면 환각 판례가 답변에 그대로 남으므로 정확성 항목이다.
    """
    return min(40.0, max(12.0, text_len / 165))


def _remaining(deadline: float | None) -> float:
    """단계 데드라인까지 남은 초. deadline이 None이면 무제한 대신 단계 예산 전체."""
    if deadline is None:
        return CITATION_STAGE_BUDGET
    return deadline - time.monotonic()


def _is_valid_rewrite(text: str | None, original: str) -> bool:
    """교정/퇴고 결과를 채택해도 되는지 판정 — 전 제공자 공통 가드.

    빈 응답·공백만·과도하게 짧아진 결과를 **성공으로 처리하면 안 된다**. 이 결과는
    `replace` 이벤트로 사용자가 이미 받은 완성 답변을 통째로 덮어쓰기 때문에,
    통과시키면 답변이 사라진다. 실패로 판정해 다음 제공자로 넘기는 것이 옳다.

    0.7 하한은 원문 대비 길이 비율 — 교정은 판례 번호만 제거하므로 길이가 크게
    줄면 본문이 유실된 것이다.
    """
    return bool(text) and len(text) > len(original) * 0.7

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

    # 법령 API에서 조회한 판례 (case_name 있는 항목만 — Pinecone 판례는 hits 경로로 파싱됨)
    if legal_precedents:
        api_lines = []
        for prec in legal_precedents:
            case_name = prec.get("case_name", "")
            if not case_name:
                continue
            date = prec.get("date", "")
            api_lines.append(f"  - {case_name} ({date})")
        if api_lines:
            lines.append("\n법령 API 조회 판례:")
            lines.extend(api_lines)

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
    anthropic_client=None,
    gemini_api_key: str | None = None,
    openai_client: object | None = None,
    deadline: float | None = None,
) -> str | None:
    """다른 LLM을 사용해 환각 판례 번호를 제거한 수정 답변을 생성.

    Haiku(1순위) → Gemini(2순위) → OpenAI(3순위) 순서로 시도.

    Args:
        deadline: `time.monotonic()` 기준 단계 데드라인 (FR-07). 벤더 3곳이 각자
            타임아웃을 소진하면 maxDuration(300초)을 위협하므로 단계 전체를 자른다.
            None이면 CITATION_STAGE_BUDGET을 지금부터 적용한다.

    Returns:
        수정된 답변 텍스트. 실패 시 None.
    """
    if not hallucinated:
        return None

    if deadline is None:
        deadline = time.monotonic() + CITATION_STAGE_BUDGET
    per_call = _rewrite_timeout(len(response_text))

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

    # 1순위: Claude Haiku
    if anthropic_client and _remaining(deadline) >= 5:
        try:
            import httpx
            # ⚠️ timeout은 **시도당** 적용된다. max_retries를 지정하지 않으면 SDK 기본
            #    2회 재시도가 살아 있어 한 벤더가 단계 예산(60초)을 통째로 삼킨다
            #    (실측: timeout=0.001에 1.37초 소요 = 3회 시도). 재시도 대신 다음
            #    벤더로 넘기는 것이 설계 원칙 P2와도 일치한다.
            resp = anthropic_client.with_options(
                timeout=httpx.Timeout(min(per_call, _remaining(deadline))),
                max_retries=0,
            ).messages.create(
                model="claude-haiku-4-5-20251001",
                # 답변 전문을 교정해 되돌리므로 답변 생성 한도와 맞춘다.
                # 부족하면 아래 0.7 길이 가드에 걸려 교정이 통째로 폐기된다.
                max_tokens=ANSWER_MAX_TOKENS,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text.strip()
            if _is_valid_rewrite(text, response_text):
                logger.info(
                    "Haiku 판례 교정 완료: %d개 환각 제거", len(hallucinated),
                )
                return text
        except Exception as e:
            logger.warning("Haiku 판례 교정 실패: %s", e)

    # 2순위: Gemini
    if gemini_api_key and _remaining(deadline) >= 5:
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_api_key)
            # 모델명은 app.config 단일 출처 — 하드코딩된 gemini-2.5-pro가 404로
            # 죽어 있어 이 폴백 단계가 통째로 무력했다 (llm-fallback-hardening G7).
            model = genai.GenerativeModel(GEMINI_MODEL)
            resp = model.generate_content(
                prompt,
                request_options={"timeout": min(per_call, _remaining(deadline))},
            )
            text = (resp.text or "").strip()
            if _is_valid_rewrite(text, response_text):
                logger.info(
                    "Gemini 판례 교정 완료: %d개 환각 제거", len(hallucinated),
                )
                return text
        except Exception as e:
            logger.warning("Gemini 판례 교정 실패: %s", e)

    # OpenAI 폴백
    if openai_client and _remaining(deadline) >= 5:
        try:
            resp = openai_client.with_options(
                timeout=min(per_call, _remaining(deadline)), max_retries=0,
            ).chat.completions.create(
                # 답변 생성 모델과 동일 설정을 따라간다 (A/B 교체 시 함께 전환)
                model=os.getenv("OPENAI_CHAT_MODEL", "o3"),
                messages=[
                    {"role": "developer", "content": "당신은 텍스트 교정 도우미입니다."},
                    {"role": "user", "content": prompt},
                ],
                # reasoning 토큰이 이 한도를 함께 소비한다 (pipeline._stream_openai 주석 참고).
                # 답변 전문을 교정해 되돌려야 하므로 넉넉히 잡는다.
                max_completion_tokens=ANSWER_MAX_TOKENS,
            )
            text = (resp.choices[0].message.content or "").strip()
            if _is_valid_rewrite(text, response_text):
                logger.info(
                    "OpenAI 판례 교정 완료: %d개 환각 제거", len(hallucinated),
                )
                return text
        except Exception as e:
            logger.warning("OpenAI 판례 교정 실패: %s", e)

    if _remaining(deadline) < 5:
        logger.warning("인용 교정 단계 예산 소진 — 남은 제공자 생략")
    return None


# ── 마이크로 퇴고: 환각 교정 후 문맥 자연스러움 보정 ─────────────────────────

MICRO_POLISH_MODEL = "claude-haiku-4-5-20251001"
# 타임아웃은 _rewrite_timeout()으로 입력 길이에 비례해 계산한다 — 고정 2초는
# 답변 전문(최대 8192토큰) 재생성에 턱없이 부족해 사실상 항상 실패했다 (FR-07).
MICRO_POLISH_MIN_BUDGET = 15.0  # 잔여 예산이 이보다 적으면 퇴고를 건너뛴다
MICRO_POLISH_THRESHOLD = 3  # 환각 N건 이상 시 발동

_MICRO_POLISH_SYSTEM = (
    "당신은 한국어 문장 교정 도우미입니다. "
    "판례 번호가 제거된 문장의 문맥을 자연스럽게 다듬어주세요.\n\n"
    "절대 규칙:\n"
    "1. 사실 정보(법조문, 금액, 날짜, 기준)를 절대 변경하지 마세요.\n"
    "2. 접속사, 연결어, 지시어만 수정하여 문맥을 매끄럽게 하세요.\n"
    "3. 마크다운 형식을 유지하세요.\n"
    "4. 새로운 판례 번호나 출처를 추가하지 마세요.\n"
    "5. 수정된 전체 텍스트만 출력하세요."
)


def micro_polish(
    corrected_text: str,
    hallucinated_count: int,
    anthropic_client,
    deadline: float | None = None,
) -> str | None:
    """환각 교정 후 문맥 자연스러움 보정.

    환각이 MICRO_POLISH_THRESHOLD건 이상일 때만 발동한다.
    Claude Haiku로 접속사/연결어만 수정하여 문맥을 매끄럽게 보정.

    Args:
        corrected_text: 환각 판례 제거 후 텍스트
        hallucinated_count: 제거된 환각 인용 수
        anthropic_client: Anthropic 클라이언트
        deadline: 인용 교정 단계 데드라인 (FR-07). 퇴고는 정확성이 아니라 품질
            보정이므로 예산 경쟁에서 후순위 — 잔여가 부족하면 건너뛴다.

    Returns:
        퇴고된 텍스트. 실패 또는 불필요 시 None.
    """
    if hallucinated_count < MICRO_POLISH_THRESHOLD:
        return None

    if not anthropic_client:
        return None

    # deadline 미지정 시 예산을 지금부터 새로 부여한다 — correct_hallucinated_citations와
    # 동일한 정규화. 이게 없으면 None이 "단계 예산 전액"으로 해석돼 교정 단계가
    # 이미 쓴 시간을 무시하게 된다.
    if deadline is None:
        deadline = time.monotonic() + CITATION_STAGE_BUDGET
    budget = _remaining(deadline)
    if budget < MICRO_POLISH_MIN_BUDGET:
        logger.info("마이크로 퇴고 생략 — 잔여 예산 %.1f초", budget)
        return None

    try:
        # 재시도 차단 이유는 correct_hallucinated_citations의 Haiku 호출 주석 참고.
        resp = anthropic_client.with_options(
            timeout=min(_rewrite_timeout(len(corrected_text)), budget),
            max_retries=0,
        ).messages.create(
            model=MICRO_POLISH_MODEL,
            # 답변 전문을 다듬어 되돌리므로 답변 생성 한도와 맞춘다.
            max_tokens=ANSWER_MAX_TOKENS,
            temperature=0,
            system=_MICRO_POLISH_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f"{hallucinated_count}개의 판례 번호가 제거되어 "
                    "문맥이 어색할 수 있는 텍스트입니다. "
                    "접속사와 연결어만 수정하여 자연스럽게 다듬어주세요.\n\n"
                    f"{corrected_text}"
                ),
            }],
        )
        polished = resp.content[0].text.strip()
        if _is_valid_rewrite(polished, corrected_text):
            logger.info(
                "마이크로 퇴고 완료: %d건 환각 교정 후 문맥 보정",
                hallucinated_count,
            )
            return polished
        logger.warning("마이크로 퇴고 결과 길이 이상 — 원본 유지")
        return None

    except Exception as e:
        logger.warning("마이크로 퇴고 실패 (정규식 교정 결과 유지): %s", e)
        return None
