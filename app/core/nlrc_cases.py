"""중앙노동위원회 주요판정사례 검색 + 법제처 판례 보강

공공데이터포털(odcloud) API에서 360건 판정사례를 캐싱하고,
사용자 질문 키워드와 매칭되는 사례를 찾은 뒤,
법제처 API(law.go.kr)로 관련 판례를 웹검색하여 본문을 보강한다.

흐름:
  1. 최초 호출 시 odcloud API에서 전체 사례 로드 → 메모리 캐시
  2. 질문 키워드 / precedent_keywords로 사례 제목 검색
  3. 매칭된 사례의 핵심 키워드를 법제처 API에 검색
  4. 판정사례 제목 + 법제처 판례 본문을 결합하여 반환
"""

from __future__ import annotations

import os
import re
import json
import time
import logging
import urllib.request
from threading import Lock

logger = logging.getLogger(__name__)

# ── 캐시 ──────────────────────────────────────────────────────────────────────
_cases_cache: list[dict] = []
_cache_lock = Lock()
_cache_loaded_at: float = 0
_CACHE_TTL = 86400  # 24시간

ODCLOUD_ENDPOINT = (
    "https://api.odcloud.kr/api/15143186/v1/"
    "uddi:7e647f42-6407-4759-bd18-d546c62d34b7"
)

# ── 주제별 키워드 매핑 (판정사례 자료구분 → 검색 키워드) ─────────────────────
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "징계해고": ["징계", "해고", "징계해고", "징계처분"],
    "통상해고": ["해고", "통상해고", "근로계약 종료"],
    "기간만료": ["기간제", "계약만료", "갱신기대권", "기간만료"],
    "부당노동행위": ["부당노동행위", "노동조합", "지배개입", "불이익"],
    "공정대표": ["공정대표의무", "교섭대표", "차별"],
    "기타징계": ["징계", "감봉", "정직", "견책"],
    "경영상해고": ["경영상 해고", "정리해고", "구조조정"],
    "기타구제이익": ["구제이익", "구제신청"],
    "교섭단위분리": ["교섭단위", "분리", "교섭창구"],
    "교섭요구공고": ["교섭요구", "교섭대표", "공동교섭"],
    "당사자적격": ["당사자적격", "근로자성", "사용자"],
    "사직": ["사직", "권고사직", "자진퇴사"],
    "차별시정": ["차별시정", "차별", "비정규직", "기간제"],
    "교섭대표결정": ["교섭대표", "과반수", "단일화"],
    "전보": ["전보", "전보처분", "인사이동", "배치전환"],
    "직권면직": ["직권면직", "수습", "시용", "본채용"],
    "대기발령": ["대기발령", "직위해제"],
    "정직": ["정직", "징계"],
}


def _fetch_all_cases(api_key: str) -> list[dict]:
    """odcloud API에서 전체 판정사례를 가져온다."""
    all_items = []
    page = 1
    per_page = 100

    while True:
        url = (
            f"{ODCLOUD_ENDPOINT}"
            f"?page={page}&perPage={per_page}&serviceKey={api_key}"
        )
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "laborconsult/1.0",
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            items = data.get("data", [])
            all_items.extend(items)
            if len(items) < per_page:
                break
            page += 1
            time.sleep(0.1)
        except Exception as e:
            logger.warning("odcloud API 호출 실패 (page=%d): %s", page, e)
            break

    logger.info("NLRC 판정사례 %d건 로드 완료", len(all_items))
    return all_items


def _get_cases(api_key: str) -> list[dict]:
    """캐시된 판정사례 반환 (TTL 초과 시 재로드)."""
    global _cases_cache, _cache_loaded_at

    now = time.time()
    if _cases_cache and (now - _cache_loaded_at) < _CACHE_TTL:
        return _cases_cache

    with _cache_lock:
        # 더블체크
        if _cases_cache and (time.time() - _cache_loaded_at) < _CACHE_TTL:
            return _cases_cache

        _cases_cache = _fetch_all_cases(api_key)
        _cache_loaded_at = time.time()
        return _cases_cache


def search_nlrc_cases(
    keywords: list[str],
    api_key: str,
    max_results: int = 5,
) -> list[dict]:
    """키워드로 NLRC 판정사례 검색.

    Args:
        keywords: 검색 키워드 리스트 (예: ["부당해고", "징계"])
        api_key: odcloud API 키
        max_results: 최대 반환 건수

    Returns:
        [{제목, 자료구분, 위원회명, 작성일자, score}, ...] score 내림차순
    """
    if not api_key:
        return []

    cases = _get_cases(api_key)
    if not cases:
        return []

    # 키워드 매칭 점수 계산
    scored = []
    for case in cases:
        title = case.get("제목", "")
        category = case.get("자료구분", "")
        score = 0

        # 직접 키워드 매칭
        for kw in keywords:
            if kw in title:
                score += 3
            # 자료구분의 연관 키워드 매칭
            cat_kws = _CATEGORY_KEYWORDS.get(category, [])
            if kw in cat_kws:
                score += 1

        if score > 0:
            scored.append({
                "제목": title,
                "자료구분": category,
                "위원회명": case.get("위원회명", ""),
                "작성일자": case.get("작성일자", ""),
                "score": score,
            })

    # score 내림차순, 동점이면 최신순
    scored.sort(key=lambda x: (-x["score"], x["작성일자"]), reverse=False)
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:max_results]


def search_nlrc_with_details(
    keywords: list[str],
    odcloud_api_key: str,
    law_api_key: str | None = None,
    max_results: int = 3,
) -> str | None:
    """NLRC 판정사례 검색 + 법제처 API로 관련 판례 본문 보강.

    Args:
        keywords: 검색 키워드
        odcloud_api_key: 공공데이터포털 API 키
        law_api_key: 법제처 API 키 (본문 보강용, 없으면 제목만)
        max_results: 최대 반환 건수

    Returns:
        포매팅된 텍스트 (없으면 None)
    """
    cases = search_nlrc_cases(keywords, odcloud_api_key, max_results=max_results)
    if not cases:
        return None

    parts = []

    for case in cases:
        title = case["제목"]
        header = (
            f"[중앙노동위원회 판정] {title}\n"
            f"  자료구분: {case['자료구분']} | "
            f"위원회: {case['위원회명']} | "
            f"작성일: {case['작성일자']}"
        )

        # 법제처 API로 관련 판례 검색하여 본문 보강
        detail_text = ""
        if law_api_key:
            detail_text = _search_related_precedent(title, law_api_key)

        if detail_text:
            parts.append(f"{header}\n  관련 판례:\n{detail_text}")
        else:
            parts.append(header)

    if not parts:
        return None

    return "\n\n".join(parts)


def _search_related_precedent(title: str, law_api_key: str) -> str:
    """판정사례 제목에서 핵심 키워드를 추출하여 법제처 판례 검색."""
    # 제목에서 검색 쿼리 생성 (핵심 키워드 추출)
    # "~라고 판정한 사례" 등 공통 접미사 제거
    query = re.sub(r"(라고|이라고|다고)\s*(판정|판단|결정)한\s*사례\s*$", "", title)
    query = query.strip()
    if len(query) > 40:
        query = query[:40]

    try:
        from app.core.legal_api import search_precedent

        results = search_precedent(query, law_api_key, max_results=2)
        if not results:
            return ""

        lines = []
        for r in results[:2]:
            case_name = r.get("사건명", "")
            case_no = r.get("사건번호", "")
            court = r.get("법원명", "")
            date = r.get("선고일자", "")
            if case_name:
                lines.append(
                    f"    - {case_name} ({case_no}, {court} {date})"
                )
        return "\n".join(lines)

    except Exception as e:
        logger.debug("NLRC 관련 판례 검색 실패 (무시): %s", e)
        return ""
