"""법제처 국가법령정보 Open API 클라이언트

법제처 DRF API(law.go.kr)를 통해 현행 법령 조문·판례를 실시간 조회한다.
- 법령 검색 → MST(일련번호) 획득 (주요 법령은 사전매핑으로 API 생략)
- 조문/판례 조회 → XML 파싱 → 텍스트 추출
- 3단계 캐시: L1(인메모리) → L2(Supabase) → L3(API)
- Circuit breaker: 연속 실패 시 일시 차단으로 타임아웃 누적 방지
- ThreadPoolExecutor 병렬 조회 (최대 5건 동시)
- 모든 실패 시 None 반환 → 기존 RAG 흐름 유지
"""

from __future__ import annotations

import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from xml.etree import ElementTree as ET

import requests

logger = logging.getLogger(__name__)

# ── API 설정 ──────────────────────────────────────────────────────────────────
LAW_SEARCH_URL = "https://www.law.go.kr/DRF/lawSearch.do"
LAW_SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do"

LAW_SEARCH_TIMEOUT = int(os.getenv("LAW_API_SEARCH_TIMEOUT", "3"))
LAW_SERVICE_TIMEOUT = int(os.getenv("LAW_API_SERVICE_TIMEOUT", "8"))
LAW_CACHE_TTL = int(os.getenv("LAW_API_CACHE_TTL", "86400"))  # 24시간


# ── Circuit Breaker ──────────────────────────────────────────────────────────
_circuit: dict = {"fail_count": 0, "open_until": 0.0}
_CIRCUIT_FAIL_THRESHOLD = 3
_CIRCUIT_COOLDOWN = 30.0


def _circuit_check() -> bool:
    """차단 상태이면 True (호출 금지)."""
    if _circuit["fail_count"] < _CIRCUIT_FAIL_THRESHOLD:
        return False
    if time.time() > _circuit["open_until"]:
        _circuit["fail_count"] = 0  # half-open: 1건 시도 허용
        return False
    return True


def _circuit_record_success():
    _circuit["fail_count"] = 0


def _circuit_record_failure():
    _circuit["fail_count"] += 1
    if _circuit["fail_count"] >= _CIRCUIT_FAIL_THRESHOLD:
        _circuit["open_until"] = time.time() + _CIRCUIT_COOLDOWN
        logger.warning("법령 API circuit breaker OPEN (%.0fs)", _CIRCUIT_COOLDOWN)


# ── HTTP 세션 (Keep-Alive, 연결 재사용) ──────────────────────────────────────
_http = requests.Session()
_http.headers.update({"Accept": "application/xml"})


# ── 법령명 약칭 매핑 ─────────────────────────────────────────────────────────
_LAW_NAME_ALIASES: dict[str, str] = {
    "근기법": "근로기준법",
    "최임법": "최저임금법",
    "고보법": "고용보험법",
    "산재법": "산업재해보상보험법",
    "남녀고용평등법": "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률",
    "퇴직급여법": "근로자퇴직급여 보장법",
    "기간제법": "기간제 및 단시간근로자 보호 등에 관한 법률",
    "파견법": "파견근로자 보호 등에 관한 법률",
    "임채법": "임금채권보장법",
    "노조법": "노동조합 및 노동관계조정법",
}


# ── MST 사전 매핑 (주요 노동법 — 법 전부개정 시에만 변경) ────────────────────
_PRELOADED_MST: dict[str, int] = {
    "근로기준법": 265959,
    "근로기준법 시행령": 270551,
    "근로기준법 시행규칙": 269393,
    "최저임금법": 218303,
    "최저임금법 시행령": 206564,
    "고용보험법": 276843,
    "고용보험법 시행령": 281219,
    "산업재해보상보험법": 279733,
    "산업재해보상보험법 시행령": 281227,
    "근로자퇴직급여 보장법": 279829,
    "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률": 276851,
    "소득세법": 276127,
    "조세특례제한법": 268807,
    "기간제 및 단시간근로자 보호 등에 관한 법률": 232201,
    "파견근로자 보호 등에 관한 법률": 223983,
    "임금채권보장법": 259881,
    "노동조합 및 노동관계조정법": 273667,
}

# ── MST 캐시 (사전매핑으로 초기화 + 동적 조회 결과 병합) ────────────────────
_MST_CACHE: dict[str, int | None] = dict(_PRELOADED_MST)


# ── L1 조문 캐시 (인메모리, TTL 기반) ────────────────────────────────────────
_ARTICLE_CACHE: dict[str, tuple[float, str]] = {}


def _cache_get(key: str) -> str | None:
    """L1 캐시에서 조문 텍스트 조회. TTL 초과 시 None 반환."""
    entry = _ARTICLE_CACHE.get(key)
    if entry is None:
        return None
    ts, text = entry
    if time.time() - ts > LAW_CACHE_TTL:
        del _ARTICLE_CACHE[key]
        return None
    return text


def _cache_set(key: str, text: str) -> None:
    """L1 캐시에 조문 텍스트 저장."""
    _ARTICLE_CACHE[key] = (time.time(), text)


# ── L2 Supabase 영속 캐시 ────────────────────────────────────────────────────

_supabase_client = None
_supabase_checked = False


def _init_supabase():
    """Supabase 클라이언트를 지연 초기화. 미설정 시 None."""
    global _supabase_client, _supabase_checked
    if _supabase_checked:
        return _supabase_client
    _supabase_checked = True
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if url and key:
        try:
            from supabase import create_client
            _supabase_client = create_client(url, key)
        except Exception as e:
            logger.debug("Supabase 초기화 실패: %s", e)
    return _supabase_client


def _l2_cache_get(key: str) -> str | None:
    """L2(Supabase)에서 캐시 조회. 만료 행은 무시."""
    sb = _init_supabase()
    if sb is None:
        return None
    try:
        resp = sb.table("law_article_cache") \
            .select("content") \
            .eq("cache_key", key) \
            .gt("expires_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())) \
            .maybe_single() \
            .execute()
        if resp.data:
            return resp.data["content"]
    except Exception as e:
        logger.debug("L2 캐시 조회 실패 (%s): %s", key, e)
    return None


def _l2_cache_set(key: str, law_name: str, article_no: int | None,
                  content: str, source_type: str = "law") -> None:
    """L2(Supabase)에 캐시 저장. 실패 시 무시."""
    sb = _init_supabase()
    if sb is None:
        return
    try:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        expires = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(time.time() + 7 * 86400),  # 7일
        )
        sb.table("law_article_cache").upsert({
            "cache_key": key,
            "law_name": law_name,
            "article_no": article_no,
            "content": content,
            "source_type": source_type,
            "fetched_at": now,
            "expires_at": expires,
        }).execute()
    except Exception as e:
        logger.debug("L2 캐시 저장 실패 (%s): %s", key, e)


# ── 법령명 정규화 ─────────────────────────────────────────────────────────────

def _resolve_law_name(name: str) -> str:
    """약칭을 정식명칭으로 변환."""
    return _LAW_NAME_ALIASES.get(name, name)


# ── 법령 MST 조회 ─────────────────────────────────────────────────────────────

def _lookup_mst(law_name: str, api_key: str) -> int | None:
    """법령명으로 MST(일련번호)를 조회. 사전매핑 히트 시 API 미호출."""
    canonical = _resolve_law_name(law_name)

    if canonical in _MST_CACHE:
        return _MST_CACHE[canonical]

    if _circuit_check():
        return None

    try:
        resp = _http.get(LAW_SEARCH_URL, params={
            "OC": api_key,
            "target": "law",
            "type": "XML",
            "query": canonical,
            "display": "5",
        }, timeout=LAW_SEARCH_TIMEOUT)
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
                    _circuit_record_success()
                    return mst
        _circuit_record_success()
    except Exception as e:
        logger.warning("법령 MST 조회 실패 (%s): %s", law_name, e)
        _circuit_record_failure()

    _MST_CACHE[canonical] = None
    return None


# ── 조문 조회 (3단계 캐시: L1 → L2 → L3) ────────────────────────────────────

def fetch_article(law_name: str, article_no: int, api_key: str,
                  paragraph: int | None = None,
                  sub: int | None = None) -> str | None:
    """특정 법률의 조문 텍스트를 3단계 캐시 계층으로 조회.

    Args:
        sub: "조의N" 번호 (예: 제76조의2 → sub=2)
    """
    cache_key = f"{law_name}_{article_no}"
    if sub:
        cache_key += f"의{sub}"
    if paragraph:
        cache_key += f"_{paragraph}"

    # L1: 인메모리 캐시
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # L2: Supabase 영속 캐시
    l2_cached = _l2_cache_get(cache_key)
    if l2_cached is not None:
        _cache_set(cache_key, l2_cached)  # L1에도 저장
        return l2_cached

    if _circuit_check():
        return None

    # L3: API 호출
    mst = _lookup_mst(law_name, api_key)
    if mst is None:
        return None

    try:
        resp = _http.get(LAW_SERVICE_URL, params={
            "OC": api_key,
            "target": "law",
            "MST": str(mst),
            "type": "XML",
        }, timeout=LAW_SERVICE_TIMEOUT)
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        article_text = _extract_article(root, article_no, paragraph, sub)
        if article_text:
            _cache_set(cache_key, article_text)                          # L1
            _l2_cache_set(cache_key, law_name, article_no, article_text) # L2
            _circuit_record_success()
            return article_text

        _circuit_record_success()
    except Exception as e:
        logger.warning("조문 조회 실패 (%s 제%d조): %s", law_name, article_no, e)
        _circuit_record_failure()

    return None


def _extract_article(root: ET.Element, article_no: int,
                     paragraph: int | None = None,
                     sub: int | None = None) -> str | None:
    """XML 응답에서 특정 조문 텍스트를 추출.

    Args:
        sub: "조의N" 번호. 예: 제76조의2 → article_no=76, sub=2.
             None이면 "조의N" 조문을 건너뛴다 (제76조만 매칭).
    """
    for jo in root.iter("조문단위"):
        jo_no_el = jo.find("조문번호")
        if jo_no_el is None or not jo_no_el.text:
            continue
        match = re.search(r"(\d+)", jo_no_el.text)
        if match and int(match.group(1)) == article_no:
            # "조의N" 필터링: 조문가지번호 태그 또는 조문번호 텍스트에서 확인
            branch_el = jo.find("조문가지번호")
            branch_no = int(branch_el.text) if branch_el is not None and branch_el.text else None
            jo_text = jo_no_el.text or ""

            if sub is not None:
                # sub 지정: 조문가지번호 우선, 없으면 텍스트 "의N" 매칭
                if branch_no is not None:
                    if branch_no != sub:
                        continue
                elif f"의{sub}" not in jo_text:
                    continue
            else:
                # sub 미지정: 조의N 조문 건너뛰기
                if branch_no is not None:
                    continue
                elif re.search(r"의\d", jo_text):
                    continue

            # "전문" 항목(장/절 제목) 건너뛰기
            jo_type = jo.find("조문여부")
            if jo_type is not None and jo_type.text == "전문":
                continue

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


# ── XML 텍스트 추출 헬퍼 ─────────────────────────────────────────────────────

def _el_text(parent: ET.Element, tag: str) -> str | None:
    """XML 엘리먼트에서 텍스트 추출."""
    el = parent.find(tag)
    return el.text.strip() if el is not None and el.text else None


# ── 법조문 참조 파싱 ──────────────────────────────────────────────────────────

_ARTICLE_PATTERN = re.compile(
    r"([\w·ㆍ][\w·ㆍ\s]*?(?:법률|법|령|규칙))\s*제?(\d+)조(?:의(\d+))?(?:\s*제?(\d+)항)?"
)


def parse_law_reference(ref: str) -> dict | None:
    """법조문 참조 문자열을 파싱.

    Examples:
        "근로기준법 제56조"      → {"law": "근로기준법", "article": 56}
        "최저임금법 제6조 제2항"  → {"law": "최저임금법", "article": 6, "paragraph": 2}
        "근로기준법 제51조의2"    → {"law": "근로기준법", "article": 51, "sub": 2}
        "기간제 및 단시간근로자 보호 등에 관한 법률 제4조"
            → {"law": "기간제 및 단시간근로자 보호 등에 관한 법률", "article": 4}
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


# ── 판례 참조 파싱 ───────────────────────────────────────────────────────────

_PREC_PATTERN = re.compile(
    r"(?:(대법원|대법|헌법재판소|헌재)\s*)?(\d{4})\s*([가-힣]+)\s*(\d+)"
)

_DETC_TYPES = {"헌가", "헌나", "헌다", "헌라", "헌마", "헌바", "헌사", "헌아"}


def parse_precedent_reference(ref: str) -> dict | None:
    """판례 참조 문자열 파싱. court 필드로 대법원/헌재를 구분.

    Examples:
        "대법원 2023다302838" → {"court": "대법원", ..., "type": "다", ...}
        "헌재 2021헌마1234"  → {"court": "헌재", ..., "type": "헌마", ...}
        "2017헌바127"        → {"court": "헌재", ..., "type": "헌바", ...}
    """
    m = _PREC_PATTERN.search(ref)
    if not m:
        return None
    court_prefix = m.group(1) or ""
    case_type = m.group(3)

    # court 결정: 명시적 접두어 우선, 없으면 사건 유형으로 판별
    if court_prefix in ("헌법재판소", "헌재"):
        court = "헌재"
    elif court_prefix in ("대법원", "대법"):
        court = "대법원"
    elif case_type in _DETC_TYPES:
        court = "헌재"
    else:
        court = "대법원"

    return {
        "court": court,
        "year": int(m.group(2)),
        "type": case_type,
        "number": int(m.group(4)),
    }


# ── 판례 검색·조회 ───────────────────────────────────────────────────────────

def search_precedent(query: str, api_key: str,
                     max_results: int = 3) -> list[dict]:
    """판례 검색 → [{id, case_name, date, court}]"""
    if _circuit_check():
        return []

    try:
        resp = _http.get(LAW_SEARCH_URL, params={
            "OC": api_key,
            "target": "prec",
            "type": "XML",
            "query": query,
            "display": str(max_results),
        }, timeout=LAW_SEARCH_TIMEOUT)
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        results = []
        for prec in root.iter("prec"):
            prec_id = _el_text(prec, "판례일련번호")
            if not prec_id:
                continue
            results.append({
                "id": int(prec_id),
                "case_name": _el_text(prec, "사건명") or "",
                "date": _el_text(prec, "선고일자") or "",
                "court": _el_text(prec, "법원명") or "",
            })
        _circuit_record_success()
        return results
    except Exception as e:
        logger.warning("판례 검색 실패 (%s): %s", query, e)
        _circuit_record_failure()
        return []


def search_precedent_multi(
    queries: list[str],
    api_key: str,
    max_total: int = 5,
) -> list[dict]:
    """복수 쿼리로 판례 병렬 검색 → 중복 제거 후 max_total건 반환.

    각 쿼리당 max_results=3으로 검색하고, 판례일련번호 기준 중복 제거.
    """
    if not queries or not api_key:
        return []

    seen_ids: set[int] = set()
    all_results: list[dict] = []

    def _search_one(q: str) -> list[dict]:
        return search_precedent(q, api_key, max_results=3)

    with ThreadPoolExecutor(max_workers=min(len(queries), 3)) as pool:
        futures = {pool.submit(_search_one, q): q for q in queries}
        for fut in as_completed(futures):
            try:
                results = fut.result()
                for r in results:
                    if r["id"] not in seen_ids:
                        seen_ids.add(r["id"])
                        all_results.append(r)
            except Exception as e:
                logger.warning("판례 다중검색 개별 실패 (%s): %s",
                               futures[fut], e)

    logger.info("판례 다중검색 완료: %d개 쿼리 → %d건 (중복제거)",
                len(queries), len(all_results))
    return all_results[:max_total]


def fetch_precedent_details(
    prec_results: list[dict],
    api_key: str,
) -> tuple[str | None, list[dict]]:
    """검색된 판례 리스트의 판결요지를 병렬 조회하여 포매팅.

    Returns:
        (formatted_text, precedent_meta_list)
    """
    if not prec_results:
        return None, []

    t0 = time.time()
    texts: dict[int, str] = {}
    meta_list: list[dict] = []

    def _fetch_one(idx: int, prec: dict) -> tuple[int, str | None]:
        text = fetch_precedent(prec["id"], api_key)
        if text:
            header = f"[{prec['court']} {prec['case_name']}] (선고일: {prec['date']})"
            return idx, f"{header}\n{text}"
        return idx, None

    with ThreadPoolExecutor(max_workers=min(len(prec_results), 5)) as pool:
        futures = {
            pool.submit(_fetch_one, i, p): i
            for i, p in enumerate(prec_results)
        }
        for fut in as_completed(futures):
            try:
                idx, prec_text = fut.result()
                if prec_text:
                    texts[idx] = prec_text
                    p = prec_results[idx]
                    meta_list.append({
                        "case_name": p["case_name"],
                        "date": p["date"],
                        "court": p["court"],
                    })
            except Exception as e:
                logger.warning("판례 상세 조회 실패: %s", e)

    elapsed = time.time() - t0
    logger.info("판례 상세 조회 완료: %d/%d건 / %.2fs",
                len(texts), len(prec_results), elapsed)

    if not texts:
        return None, []

    formatted = "\n\n---\n\n".join(texts[k] for k in sorted(texts))
    return formatted, meta_list


def search_detc(query: str, api_key: str,
                max_results: int = 3) -> list[dict]:
    """헌재 결정례 검색 → [{id, case_name, date}]"""
    if _circuit_check():
        return []

    try:
        resp = _http.get(LAW_SEARCH_URL, params={
            "OC": api_key,
            "target": "detc",
            "type": "XML",
            "query": query,
            "display": str(max_results),
        }, timeout=LAW_SEARCH_TIMEOUT)
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        results = []
        for detc in root.iter("Detc"):
            detc_id = _el_text(detc, "헌재결정례일련번호")
            if not detc_id:
                continue
            results.append({
                "id": int(detc_id),
                "case_name": _el_text(detc, "사건명") or "",
                "date": _el_text(detc, "종국일자") or "",
                "court": "헌법재판소",
            })
        _circuit_record_success()
        return results
    except Exception as e:
        logger.warning("헌재 결정 검색 실패 (%s): %s", query, e)
        _circuit_record_failure()
        return []


def fetch_detc(detc_id: int, api_key: str) -> str | None:
    """헌재 결정례에서 판시사항 + 결정요지 추출. 3단계 캐시 적용."""
    cache_key = f"detc_{detc_id}"

    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    l2_cached = _l2_cache_get(cache_key)
    if l2_cached is not None:
        _cache_set(cache_key, l2_cached)
        return l2_cached

    if _circuit_check():
        return None

    try:
        resp = _http.get(LAW_SERVICE_URL, params={
            "OC": api_key,
            "target": "detc",
            "ID": str(detc_id),
            "type": "XML",
        }, timeout=LAW_SERVICE_TIMEOUT)
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        parts = []
        for field in ["판시사항", "결정요지"]:
            el = root.find(f".//{field}")
            if el is not None and el.text:
                parts.append(f"[{field}]\n{el.text.strip()}")

        if parts:
            text = "\n\n".join(parts)
            _cache_set(cache_key, text)
            _l2_cache_set(cache_key, "", None, text, "detc")
            _circuit_record_success()
            return text

        _circuit_record_success()
    except Exception as e:
        logger.warning("헌재 결정 조회 실패 (ID=%d): %s", detc_id, e)
        _circuit_record_failure()

    return None


def fetch_precedent(prec_id: int, api_key: str) -> str | None:
    """판례 전문에서 판시사항 + 판결요지 추출. 3단계 캐시 적용."""
    cache_key = f"prec_{prec_id}"

    # L1 캐시
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # L2 캐시
    l2_cached = _l2_cache_get(cache_key)
    if l2_cached is not None:
        _cache_set(cache_key, l2_cached)
        return l2_cached

    if _circuit_check():
        return None

    # L3 API
    try:
        resp = _http.get(LAW_SERVICE_URL, params={
            "OC": api_key,
            "target": "prec",
            "ID": str(prec_id),
            "type": "XML",
        }, timeout=LAW_SERVICE_TIMEOUT)
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        parts = []
        for field in ["판시사항", "판결요지"]:
            el = root.find(f".//{field}")
            if el is not None and el.text:
                parts.append(f"[{field}]\n{el.text.strip()}")

        if parts:
            text = "\n\n".join(parts)
            _cache_set(cache_key, text)                       # L1
            _l2_cache_set(cache_key, "", None, text, "prec")  # L2
            _circuit_record_success()
            return text

        _circuit_record_success()
    except Exception as e:
        logger.warning("판례 조회 실패 (ID=%d): %s", prec_id, e)
        _circuit_record_failure()

    return None


# ── 통합 조회 (pipeline.py에서 호출) ──────────────────────────────────────────

def fetch_relevant_articles(
    relevant_laws: list[str],
    api_key: str | None,
) -> str | None:
    """relevant_laws 목록을 병렬로 조회하여 통합 텍스트 반환.

    법조문과 판례를 동시에 처리. 부분 실패 허용.
    API 키가 없거나 모든 조회 실패 시 None 반환 → 기존 흐름 유지.
    """
    if not api_key or not relevant_laws:
        return None

    t0 = time.time()

    # 1. 파싱 (CPU-bound, 즉시)
    tasks: list[tuple[int, str, dict | None]] = []
    for idx, ref in enumerate(relevant_laws[:5]):
        parsed = parse_law_reference(ref)
        tasks.append((idx, ref, parsed))  # parsed=None이면 판례로 시도

    if not tasks:
        return None

    # 2. 병렬 조회
    results: dict[int, str] = {}

    def _fetch_one(idx: int, ref: str, parsed_law: dict | None) -> tuple[int, str | None]:
        """법조문 또는 판례 1건 조회."""
        # 법령 조문
        if parsed_law is not None:
            text = fetch_article(
                law_name=parsed_law["law"],
                article_no=parsed_law["article"],
                api_key=api_key,
                paragraph=parsed_law.get("paragraph"),
                sub=parsed_law.get("sub"),
            )
            if text:
                law_display = _resolve_law_name(parsed_law["law"])
                sub_suffix = f"의{parsed_law['sub']}" if "sub" in parsed_law else ""
                return idx, f"[{law_display} 제{parsed_law['article']}조{sub_suffix}]\n{text}"
            return idx, None

        # 판례/헌재 결정 참조
        parsed_prec = parse_precedent_reference(ref)
        if parsed_prec is not None:
            query = f"{parsed_prec['year']}{parsed_prec['type']}{parsed_prec['number']}"

            if parsed_prec["court"] == "헌재":
                detc_results = search_detc(query, api_key, max_results=1)
                if detc_results:
                    text = fetch_detc(detc_results[0]["id"], api_key)
                    if text:
                        case_name = detc_results[0]["case_name"] or query
                        return idx, f"[헌재 {case_name}]\n{text}"
            else:
                prec_results = search_precedent(query, api_key, max_results=1)
                if prec_results:
                    text = fetch_precedent(prec_results[0]["id"], api_key)
                    if text:
                        case_name = prec_results[0]["case_name"] or query
                        return idx, f"[{case_name}]\n{text}"

        return idx, None

    with ThreadPoolExecutor(max_workers=min(len(tasks), 5)) as pool:
        futures = {
            pool.submit(_fetch_one, idx, ref, parsed): idx
            for idx, ref, parsed in tasks
        }
        for fut in as_completed(futures):
            try:
                idx, article_text = fut.result()
                if article_text:
                    results[idx] = article_text
            except Exception as e:
                logger.warning("병렬 조문 조회 실패: %s", e)

    elapsed = time.time() - t0
    logger.info("법령 API 조회 완료: %d/%d건 / %.2fs",
                len(results), len(tasks), elapsed)

    if not results:
        return None

    # 3. 원래 순서대로 정렬하여 반환
    return "\n\n".join(results[k] for k in sorted(results))


def fetch_relevant_precedents(
    query: str,
    api_key: str | None,
    max_results: int = 3,
) -> tuple[str | None, list[dict]]:
    """키워드로 법제처 API에서 판례를 검색하고 판결요지를 조회.

    Returns:
        (formatted_text, precedent_meta_list)
        - formatted_text: LLM 컨텍스트에 포함할 판례 텍스트 (None이면 실패)
        - precedent_meta_list: [{case_name, date, court, case_number}]
    """
    if not api_key or not query:
        return None, []

    t0 = time.time()

    # 1. 판례 검색
    prec_results = search_precedent(query, api_key, max_results=max_results)
    if not prec_results:
        logger.info("판례 키워드 검색 결과 없음: %s", query[:50])
        return None, []

    # 2. 판결요지 병렬 조회
    texts: dict[int, str] = {}
    meta_list: list[dict] = []

    def _fetch_one(idx: int, prec: dict) -> tuple[int, str | None]:
        text = fetch_precedent(prec["id"], api_key)
        if text:
            header = f"[{prec['court']} {prec['case_name']}] (선고일: {prec['date']})"
            return idx, f"{header}\n{text}"
        return idx, None

    with ThreadPoolExecutor(max_workers=min(len(prec_results), 5)) as pool:
        futures = {
            pool.submit(_fetch_one, i, p): i
            for i, p in enumerate(prec_results)
        }
        for fut in as_completed(futures):
            try:
                idx, prec_text = fut.result()
                if prec_text:
                    texts[idx] = prec_text
                    p = prec_results[idx]
                    meta_list.append({
                        "case_name": p["case_name"],
                        "date": p["date"],
                        "court": p["court"],
                    })
            except Exception as e:
                logger.warning("판례 조회 실패: %s", e)

    elapsed = time.time() - t0
    logger.info("판례 키워드 검색 완료: query=%r, %d/%d건 / %.2fs",
                query[:30], len(texts), len(prec_results), elapsed)

    if not texts:
        return None, []

    formatted = "\n\n---\n\n".join(texts[k] for k in sorted(texts))
    return formatted, meta_list
