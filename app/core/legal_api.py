"""법제처 국가법령정보 Open API 클라이언트

법제처 DRF API(law.go.kr)를 통해 현행 법령 조문을 실시간 조회한다.
- 법령 검색 → MST(일련번호) 획득
- 조문 조회 → XML 파싱 → 텍스트 추출
- 인메모리 2단계 캐시 (MST + 조문)
- 모든 실패 시 None 반환 → 기존 RAG 흐름 유지
"""

from __future__ import annotations

import logging
import os
import re
import time
from xml.etree import ElementTree as ET

import requests

logger = logging.getLogger(__name__)

# ── API 설정 ──────────────────────────────────────────────────────────────────
LAW_SEARCH_URL = "http://www.law.go.kr/DRF/lawSearch.do"
LAW_SERVICE_URL = "http://www.law.go.kr/DRF/lawService.do"

LAW_API_TIMEOUT = int(os.getenv("LAW_API_TIMEOUT", "5"))
LAW_CACHE_TTL = int(os.getenv("LAW_API_CACHE_TTL", "86400"))  # 24시간


# ── 법령명 약칭 매핑 ─────────────────────────────────────────────────────────
_LAW_NAME_ALIASES: dict[str, str] = {
    "근기법": "근로기준법",
    "최임법": "최저임금법",
    "고보법": "고용보험법",
    "산재법": "산업재해보상보험법",
    "남녀고용평등법": "남녀고용평등과 일·가정 양립 지원에 관한 법률",
    "퇴직급여법": "근로자퇴직급여 보장법",
}


# ── MST 캐시 (법령일련번호) ──────────────────────────────────────────────────
_MST_CACHE: dict[str, int | None] = {}


# ── 조문 캐시 ─────────────────────────────────────────────────────────────────
_ARTICLE_CACHE: dict[str, tuple[float, str]] = {}


def _cache_get(key: str) -> str | None:
    """캐시에서 조문 텍스트 조회. TTL 초과 시 None 반환."""
    entry = _ARTICLE_CACHE.get(key)
    if entry is None:
        return None
    ts, text = entry
    if time.time() - ts > LAW_CACHE_TTL:
        del _ARTICLE_CACHE[key]
        return None
    return text


def _cache_set(key: str, text: str) -> None:
    """조문 텍스트를 캐시에 저장."""
    _ARTICLE_CACHE[key] = (time.time(), text)


# ── 법령명 정규화 ─────────────────────────────────────────────────────────────

def _resolve_law_name(name: str) -> str:
    """약칭을 정식명칭으로 변환."""
    return _LAW_NAME_ALIASES.get(name, name)


# ── 법령 MST 조회 ─────────────────────────────────────────────────────────────

def _lookup_mst(law_name: str, api_key: str) -> int | None:
    """법령명으로 MST(일련번호)를 조회. 결과를 _MST_CACHE에 저장."""
    canonical = _resolve_law_name(law_name)

    if canonical in _MST_CACHE:
        return _MST_CACHE[canonical]

    try:
        resp = requests.get(LAW_SEARCH_URL, params={
            "OC": api_key,
            "target": "law",
            "type": "XML",
            "query": canonical,
            "display": "5",
        }, timeout=LAW_API_TIMEOUT)
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        for law_el in root.iter("law"):
            name_el = law_el.find("법령명한글")
            if name_el is None:
                name_el = law_el.find("법령명_한글")
            if name_el is not None and name_el.text and canonical in name_el.text:
                mst_el = law_el.find("법령일련번호")
                if mst_el is not None and mst_el.text:
                    mst = int(mst_el.text)
                    _MST_CACHE[canonical] = mst
                    return mst
    except Exception as e:
        logger.warning("법령 MST 조회 실패 (%s): %s", law_name, e)

    _MST_CACHE[canonical] = None
    return None


# ── 조문 조회 ─────────────────────────────────────────────────────────────────

def fetch_article(law_name: str, article_no: int, api_key: str,
                  paragraph: int | None = None) -> str | None:
    """특정 법률의 조문 텍스트를 조회."""
    cache_key = f"{law_name}_{article_no}"
    if paragraph:
        cache_key += f"_{paragraph}"

    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    mst = _lookup_mst(law_name, api_key)
    if mst is None:
        return None

    try:
        resp = requests.get(LAW_SERVICE_URL, params={
            "OC": api_key,
            "target": "law",
            "MST": str(mst),
            "type": "XML",
        }, timeout=LAW_API_TIMEOUT)
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        article_text = _extract_article(root, article_no, paragraph)
        if article_text:
            _cache_set(cache_key, article_text)
            return article_text

    except Exception as e:
        logger.warning("조문 조회 실패 (%s 제%d조): %s", law_name, article_no, e)

    return None


def _extract_article(root: ET.Element, article_no: int,
                     paragraph: int | None = None) -> str | None:
    """XML 응답에서 특정 조문 텍스트를 추출."""
    for jo in root.iter("조문단위"):
        jo_no_el = jo.find("조문번호")
        if jo_no_el is None or not jo_no_el.text:
            continue
        match = re.search(r"(\d+)", jo_no_el.text)
        if match and int(match.group(1)) == article_no:
            if paragraph is not None:
                for hang in jo.iter("항"):
                    hang_no_el = hang.find("항번호")
                    if hang_no_el is not None and hang_no_el.text:
                        h_match = re.search(r"(\d+)", hang_no_el.text)
                        if h_match and int(h_match.group(1)) == paragraph:
                            return _format_article_text(jo_no_el.text, hang)
                return None
            else:
                return _format_full_article(jo)
    return None


def _format_full_article(jo_el: ET.Element) -> str | None:
    """조문 전체를 읽기 좋은 텍스트로 포맷팅."""
    parts: list[str] = []

    title_el = jo_el.find("조문제목")
    jo_no_el = jo_el.find("조문번호")
    if jo_no_el is not None and jo_no_el.text:
        header = jo_no_el.text.strip()
        if title_el is not None and title_el.text:
            header += f"({title_el.text.strip()})"
        parts.append(header)

    content_el = jo_el.find("조문내용")
    if content_el is not None and content_el.text:
        parts.append(content_el.text.strip())

    for hang in jo_el.iter("항"):
        hang_content = hang.find("항내용")
        if hang_content is not None and hang_content.text:
            parts.append(hang_content.text.strip())
        for ho in hang.iter("호"):
            ho_content = ho.find("호내용")
            if ho_content is not None and ho_content.text:
                parts.append(f"  {ho_content.text.strip()}")

    return "\n".join(parts) if parts else None


def _format_article_text(jo_no_text: str, hang_el: ET.Element) -> str:
    """특정 항을 포맷팅."""
    parts = [jo_no_text.strip()]
    hang_content = hang_el.find("항내용")
    if hang_content is not None and hang_content.text:
        parts.append(hang_content.text.strip())
    for ho in hang_el.iter("호"):
        ho_content = ho.find("호내용")
        if ho_content is not None and ho_content.text:
            parts.append(f"  {ho_content.text.strip()}")
    return "\n".join(parts)


# ── 법조문 참조 파싱 ──────────────────────────────────────────────────────────

_ARTICLE_PATTERN = re.compile(
    r"([\w·]+(?:법|령|규칙))\s*제?(\d+)조(?:의(\d+))?(?:\s*제?(\d+)항)?"
)


def parse_law_reference(ref: str) -> dict | None:
    """법조문 참조 문자열을 파싱.

    Examples:
        "근로기준법 제56조"      → {"law": "근로기준법", "article": 56}
        "최저임금법 제6조 제2항"  → {"law": "최저임금법", "article": 6, "paragraph": 2}
        "근로기준법 제51조의2"    → {"law": "근로기준법", "article": 51, "sub": 2}
        "대법원 2023다302838"     → None (판례는 Phase 2)
    """
    m = _ARTICLE_PATTERN.search(ref)
    if not m:
        return None
    result: dict = {
        "law": m.group(1),
        "article": int(m.group(2)),
    }
    if m.group(3):
        result["sub"] = int(m.group(3))
    if m.group(4):
        result["paragraph"] = int(m.group(4))
    return result


# ── 통합 조회 (pipeline.py에서 호출) ──────────────────────────────────────────

def fetch_relevant_articles(
    relevant_laws: list[str],
    api_key: str | None,
) -> str | None:
    """relevant_laws 목록에서 법조문을 조회하여 통합 텍스트 반환.

    API 키가 없거나 모든 조회 실패 시 None 반환 → 기존 흐름 유지.
    """
    if not api_key or not relevant_laws:
        return None

    articles: list[str] = []
    for ref in relevant_laws[:5]:  # 최대 5개 법조문만 조회
        parsed = parse_law_reference(ref)
        if parsed is None:
            continue

        text = fetch_article(
            law_name=parsed["law"],
            article_no=parsed["article"],
            api_key=api_key,
            paragraph=parsed.get("paragraph"),
        )
        if text:
            law_display = _resolve_law_name(parsed["law"])
            articles.append(f"[{law_display} 제{parsed['article']}조]\n{text}")

    if not articles:
        return None

    return "\n\n".join(articles)
