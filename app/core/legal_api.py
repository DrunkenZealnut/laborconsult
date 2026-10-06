"""법제처 국가법령정보 Open API 클라이언트

법제처 DRF API(law.go.kr)를 통해 현행 법령 조문·판례를 실시간 조회한다.
- 조문: 법령명(LM) + `target=eflaw`(시행일 법령) 조회 — 법제처가 **현행 시행판**을
  돌려준다. `target=law`는 시행 예정 개정이 섞인 본문을 현행 헤더로 돌려주므로
  쓰지 않는다(effective-law-and-graph-precedents, 2026-10-04). MST(일련번호) 지정은
  그 판본을 고정 반환하므로 쓰지 않는다(드리프트 이력은 _OFFICIAL_NAME_CACHE 위 주석)
- 조문/판례 조회 → XML 파싱 → 텍스트 추출
- 3단계 캐시: L1(인메모리) → L2(Supabase) → L3(API)
- Circuit breaker: 연속 실패 시 일시 차단으로 타임아웃 누적 방지
- ThreadPoolExecutor 병렬 조회 (최대 5건 동시)
- 모든 실패 시 None 반환 → 기존 RAG 흐름 유지
- `LAW_API_LIVE=off`면 실호출 없이 캐시(L1·L2)만 본다 — 프로덕션(Vercel) IP는 법제처에
  등록돼 있지 않아 실호출이 전부 인증 실패한다. L2는 등록 IP 맥의 예열 작업
  (`warm_law_cache.py`)이 채운다(production-law-api-recovery)
- `<Response>` 루트(자격증명·IP·파라미터 오류)는 `LawApiAuthError`로 올린다 — HTTP 200이라
  raise_for_status로 안 잡히고, '결과 없음'으로 읽으면 장애가 보이지 않는다
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

from app.core import safe_xml

import requests

logger = logging.getLogger(__name__)

# ── API 설정 ──────────────────────────────────────────────────────────────────
LAW_SEARCH_URL = "https://www.law.go.kr/DRF/lawSearch.do"
LAW_SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do"

LAW_SEARCH_TIMEOUT = int(os.getenv("LAW_API_SEARCH_TIMEOUT", "3"))
LAW_SERVICE_TIMEOUT = int(os.getenv("LAW_API_SERVICE_TIMEOUT", "8"))
LAW_CACHE_TTL = int(os.getenv("LAW_API_CACHE_TTL", "86400"))  # 24시간
L2_TIMEOUT = float(os.getenv("LAW_API_L2_TIMEOUT", "5"))      # L2(Supabase) 요청 타임아웃(초)

# 조문 캐시 만료(effective-law D2). 판본은 **시행일(날짜) 경계**에서만 바뀌므로 만료를
# 다음 KST 자정에 맞춘다 — 24h TTL만으로는 새 판본 시행 뒤 최대 하루 동안 옛 판본을 냈다.
# 법제처가 자정 직후 현행판을 늦게 바꿀 수 있어 KST 00~03시 응답은 1시간만 보관한다.
# 판례·헌재·NLRC 캐시는 판본과 무관하므로 이 상한을 받지 않는다.
_KST = timezone(timedelta(hours=9))
_EARLY_HOURS_END = 3
_EARLY_TTL = 3600


# ── 오류 응답·실호출 스위치 ───────────────────────────────────────────────────

class LawApiAuthError(RuntimeError):
    """법제처가 `<Response>` 루트를 돌려줬다 — 자격증명·IP 미등록·파라미터 오류(HTTP 200).

    RuntimeError 하위라 기존의 `except RuntimeError`·`except Exception`은 그대로 잡는다. 이 예외를
    '없음'(None·[]·0건)으로 바꾸지 말 것: 판례·판정문 검색은 인증 오류를 "결과 0건"으로 읽고 서킷에
    성공을 기록했고, 판례 수집은 '미발견'을 진행 기록에 영구 저장했다(production-law-api-recovery D6).
    """


def _raise_if_error_root(root: ET.Element) -> None:
    """`<Response>` 루트면 LawApiAuthError. 법제처 응답을 파싱한 **모든** 곳이 부른다(D6)."""
    if root.tag == "Response":
        detail = (root.findtext(".//result") or root.findtext(".//message")
                  or "").strip()[:80]
        raise LawApiAuthError(f"법제처 API 오류 응답: {detail}")


def _live_allowed() -> bool:
    """법제처 실호출 허용 여부(`LAW_API_LIVE`, 기본 on). **호출 시점에** 읽는다(D5).

    off면 조문은 캐시(L1·L2)만 보고, 판례·판정문 검색은 HTTP 없이 빈 결과를 낸다. 서킷 검사보다 먼저
    판정해 서킷을 건드리지 않는다. 차단된 조회는 미매칭 표지를 남기지 않는다 — 남기면 나중에
    예열된 행이 자정까지 가려진다.
    """
    return os.environ.get("LAW_API_LIVE", "on").strip().lower() != "off"


def law_api_live_mode() -> str:
    """metadata.law_api.live 값("on"/"off")."""
    return "on" if _live_allowed() else "off"


def _set_status(outcome: dict | None, status: str) -> None:
    if outcome is not None:
        outcome["status"] = status


def _failure_status(exc: Exception) -> str:
    return "auth_error" if isinstance(exc, LawApiAuthError) else "error"


# ── 조회 통계(metadata.law_api v2, D7·D7b) ───────────────────────────────────
# 조문과 판례·판정문을 나눠 센다. 옛 대화는 평평한 구조(requested·ok·miss…)다.
ARTICLE_STAT_FIELDS = ("requested", "ok", "ok_cache", "ok_live", "miss", "auth_error",
                       "error", "skipped_unwarmed", "skipped_circuit")
PRECEDENT_STAT_FIELDS = ("requested", "ok", "rejected", "miss", "auth_error", "error", "skipped")
_ARTICLE_FAILURES = ("miss", "auth_error", "error", "skipped_unwarmed", "skipped_circuit")
_PRECEDENT_FAILURES = ("auth_error", "error", "skipped")


def new_law_stats() -> dict:
    return {"articles": dict.fromkeys(ARTICLE_STAT_FIELDS, 0),
            "precedents": dict.fromkeys(PRECEDENT_STAT_FIELDS, 0)}


def merge_law_stats(dst: dict, src: dict) -> dict:
    """src의 조문·판례 집계를 dst에 더한다(제자리 변경 후 dst 반환)."""
    for group in ("articles", "precedents"):
        bucket = dst.setdefault(group, {})
        for field_name, value in (src.get(group) or {}).items():
            bucket[field_name] = bucket.get(field_name, 0) + value
    return dst


def law_stats_requested(stats: dict | None) -> int:
    """조문 + 판례 요청 수. 0이면 metadata.law_api를 기록하지 않는다."""
    return sum((stats or {}).get(g, {}).get("requested", 0) for g in ("articles", "precedents"))


def _record_search(stats: dict | None, status: str | None) -> None:
    """키워드 판례·판정문 검색 1회를 precedents에 센다(결과 있음 ok · 0건 miss)."""
    if stats is None:
        return
    bucket = stats.setdefault("precedents", dict.fromkeys(PRECEDENT_STAT_FIELDS, 0))
    bucket["requested"] = bucket.get("requested", 0) + 1
    key = status if status in ("ok",) + _PRECEDENT_FAILURES else "miss"
    bucket[key] = bucket.get(key, 0) + 1


# ── Circuit Breaker ──────────────────────────────────────────────────────────
_circuit: dict = {"fail_count": 0, "open_until": 0.0, "probing": False}
_CIRCUIT_FAIL_THRESHOLD = 3
_CIRCUIT_COOLDOWN = 30.0


def _circuit_check() -> bool:
    """차단 상태이면 True (호출 금지).

    쿨다운 만료 시 fail_count를 즉시 0으로 초기화하면 그 순간 동시 요청
    전부가 통과해버려(half-open 무의미화) 아직 복구 안 된 서비스에 요청이
    몰릴 수 있다. probing 플래그로 단 1건만 통과시키는 단일 probe 방식으로
    보수화한다(P3).
    """
    if _circuit["fail_count"] < _CIRCUIT_FAIL_THRESHOLD:
        return False
    if time.time() > _circuit["open_until"]:
        if _circuit["probing"]:
            return True  # 이미 다른 요청이 probe 진행 중 — 차단 유지
        _circuit["probing"] = True
        return False  # 이 요청 1건만 probe로 통과
    return True


def _circuit_record_success():
    _circuit["fail_count"] = 0
    _circuit["probing"] = False


def _circuit_record_failure():
    _circuit["fail_count"] += 1
    _circuit["probing"] = False
    if _circuit["fail_count"] >= _CIRCUIT_FAIL_THRESHOLD:
        _circuit["open_until"] = time.time() + _CIRCUIT_COOLDOWN
        logger.warning("법령 API circuit breaker OPEN (%.0fs)", _CIRCUIT_COOLDOWN)


def _circuit_record_neutral():
    """성공도 실패도 아닌 종료(법령명 미매칭 등) — probe만 반납한다.

    미매칭에서 success를 기록하면 폴백 검색이 남긴 failure가 상쇄돼
    검색 엔드포인트 장애에도 회로가 영영 열리지 않고(분석 P1-3),
    아무것도 안 하면 probe로 통과한 요청이 자기 probing 플래그에 갇혀
    후속 요청 전부가 차단된다(기아). 중립 = 카운터 불변 + probe 반납.
    """
    _circuit["probing"] = False


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
    # 예열 대상 법령의 약칭 보강(production-law-api-recovery D3). 실호출을 끄면 비정형 이름을 정식명
    # 해석(검색 API)으로 메울 경로가 없다. '노동조합법'은 LM이 1996년 폐지판으로 해석한다(실측).
    "외국인고용법": "외국인근로자의 고용 등에 관한 법률",
    "산재보험법": "산업재해보상보험법",
    "노동조합법": "노동조합 및 노동관계조정법",
    "근퇴법": "근로자퇴직급여 보장법",
}


# ⚠️ MST(법령일련번호) 사전 매핑을 두지 말 것 (law-version-drift, 2026-08-20).
# MST를 명시해 조회하면 **그 판본의** 조문이 고정 반환된다. 과거의 사전매핑은
# "법 전부개정 시에만 변경"을 전제했지만 실제로는 **일부개정마다 일련번호가
# 바뀐다** — 매핑해 둔 주요 법령일수록 낡은 조문을 답하는 역설이 생겼다
# (실측 2026-08-20: 17개 중 11개가 낡았고, 고용보험법 §70 육아휴직 급여
# 요건의 "30일 또는 7일" 확대가 누락돼 있었다). 조문 조회는 법령명(LM)
# 파라미터로 한다 — 검색(MST 획득) 왕복이 사라져 호출도 2회→1회로 준다.
#
# ⚠️ 단, LM만으로 현행판이 보장되지는 않는다. `target=law&LM=`은 헤더(시행일자·
# 공포번호)는 현행판인데 본문에 **시행 예정 개정**이 섞여 온다(실측 2026-10-04:
# 근로기준법 18개·고용보험법 6개 조문, 제109조②가 10-08 시행분 "삭제"로 옴).
# 그래서 `target=eflaw`(efYd 생략 = 현행 시행판)를 쓴다 — fetch_law_root 참조.

# ── 정식 법령명 해석 캐시 (LM 미매칭 폴백 결과: 입력명 → 정식명 | None) ──────
_OFFICIAL_NAME_CACHE: dict[str, str | None] = {}


# ── L1 조문 캐시 (인메모리, 만료 시각 기반) ──────────────────────────────────
# 값은 (만료 epoch, 텍스트). 조문은 _article_expiry(), 그 밖(판례·NLRC)은 +TTL.
_ARTICLE_CACHE: dict[str, tuple[float, str]] = {}

# 미매칭 negative 표지 — L1 전용(TTL 동일 적용). L2에는 절대 저장하지 않는다.
_MISS_SENTINEL = "__lm_miss__"


def _cache_get(key: str) -> str | None:
    """L1 캐시에서 조문 텍스트 조회. TTL 초과 시 None 반환."""
    entry = _ARTICLE_CACHE.get(key)
    if entry is None:
        return None
    expires_at, text = entry
    if time.time() >= expires_at:
        del _ARTICLE_CACHE[key]
        return None
    return text


def _cache_set(key: str, text: str, expires_at: float | None = None) -> None:
    """L1 캐시에 저장. expires_at(epoch)를 주지 않으면 기존대로 +LAW_CACHE_TTL."""
    if expires_at is None:
        expires_at = time.time() + LAW_CACHE_TTL
    _ARTICLE_CACHE[key] = (expires_at, text)


def _article_expiry(now: float | None = None) -> float:
    """조문 캐시 만료 epoch = min(now + TTL, 다음 KST 자정). KST 00~03시 응답은 +1h 상한.

    판본은 날짜 경계에서만 바뀌므로 자정에 끊으면 새 판본 시행 후 옛 판본을 내지 않는다.
    서버 시계는 UTC여도 된다 — 경계 계산을 KST로 한다(Vercel은 UTC).
    """
    now = time.time() if now is None else now
    kst = datetime.fromtimestamp(now, _KST)
    next_midnight = (kst + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    expiry = min(now + LAW_CACHE_TTL, next_midnight.timestamp())
    if kst.hour < _EARLY_HOURS_END:
        expiry = min(expiry, now + _EARLY_TTL)
    return expiry


# ── L2 Supabase 영속 캐시 ────────────────────────────────────────────────────

_supabase_client = None
_supabase_checked = False
_supabase_lock = threading.Lock()


def _init_supabase():
    """Supabase 클라이언트를 지연 초기화. 미설정 시 None.

    Lock + double-check — 플래그만으로는 병렬 5스레드(fetch_relevant_articles)
    가 동시에 False를 읽고 각자 생성하거나, 생성 완료 전 상태가 공개돼 L2를
    조용히 스킵한다(실측: 콜드 첫 상담에서 5건 중 4건 L2 미저장 — 분석
    P2-1). checked는 생성 시도 완료 후에만 공개한다.
    """
    global _supabase_client, _supabase_checked
    if _supabase_checked:
        return _supabase_client
    with _supabase_lock:
        if _supabase_checked:
            return _supabase_client
        try:
            # 접속 생성은 storage.make_supabase_client 단일 경로 — 여기서
            # create_client 를 직접 부르면 스키마 옵션이 빠져
            # law_article_cache 조회가 public 으로 샌다.
            from app.core.storage import make_supabase_client
            # 답변 경로의 읽기다 — supabase-py 기본 타임아웃(120초)이면 DB 장애 때 답변이 그만큼
            # 멈춘다. 실호출을 끈 프로덕션에서는 L2가 조문의 유일한 경로다.
            _supabase_client = make_supabase_client(postgrest_timeout=L2_TIMEOUT)
        except Exception as e:
            logger.debug("Supabase 초기화 실패: %s", e)
        _supabase_checked = True
    return _supabase_client


class L2ReadError(RuntimeError):
    """L2 조회 자체가 실패했다(행 없음과 다르다) — fetch_article이 `error`로 분류한다(D7)."""


def _is_timeout(exc: Exception) -> bool:
    try:
        import httpx
        return isinstance(exc, httpx.TimeoutException)
    except ImportError:   # pragma: no cover — supabase가 httpx에 의존한다
        return False


def _l2_cache_get(key: str, *, raise_on_error: bool = False) -> str | None:
    """L2(Supabase)에서 캐시 조회. 만료 행은 무시.

    조회 **실패**(행 없음이 아니다)는 1회 재시도한다 — 쉬었던 HTTP/2 연결을 재사용하다 끊기면 동시 요청이
    한꺼번에 응답 없이 실패한다(실측 2026-10-06 topic30 24번: 예열된 세 조문이 0.02초 만에 전부 '미스').
    실호출을 끈 프로덕션에서는 이 조회가 조문의 유일한 경로라, 조용히 None으로 삼키면 조문이 그냥 빠진다.
    타임아웃은 재시도하지 않는다(같은 장애를 다시 기다린다). 최종 실패는 WARNING으로 남기고,
    raise_on_error면 L2ReadError를 올린다(fetch_article이 `miss`가 아니라 `error`로 센다).
    """
    sb = _init_supabase()
    if sb is None:
        return None
    last: Exception | None = None
    for _attempt in range(2):
        try:
            # ⚠️ maybe_single().execute() 는 0행일 때 응답 객체가 아니라 None 을 반환한다.
            #    캐시 미스는 정상 경로인데 그대로 .data 를 읽으면 매번 예외가 나
            #    아래 except 로 떨어진다(동작은 같으나 원인 진단이 흐려진다).
            resp = sb.table("law_article_cache") \
                .select("content") \
                .eq("cache_key", key) \
                .gt("expires_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())) \
                .maybe_single() \
                .execute()
            if resp is not None and resp.data:
                return resp.data["content"]
            return None
        except Exception as e:  # noqa: BLE001 — 연결 끊김·응답 해석 실패 모두 '조회 실패'다
            last = e
            if _is_timeout(e):
                break
    logger.warning("L2 캐시 조회 실패 (%s): %s: %s", key, type(last).__name__, str(last)[:160])
    if raise_on_error:
        raise L2ReadError(f"{type(last).__name__}: {last}") from last
    return None


def _l2_cache_set(key: str, law_name: str, article_no: int | None,
                  content: str, source_type: str = "law",
                  expires_at: float | None = None) -> None:
    """L2(Supabase)에 캐시 저장. 실패 시 무시. expires_at(epoch) 미지정 시 +TTL."""
    sb = _init_supabase()
    if sb is None:
        return
    try:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        # 만료 = L1과 동일한 24h(LAW_CACHE_TTL). 구 7일은 "현행판 보장"과
        # 상충했다 — 캐시 수명 동안은 개정이 반영되지 않으므로, 이 값이 곧
        # 조문 최신성의 최대 지연이다(CodeRabbit #55 Major). MST 드리프트
        # (무기한)와 달리 유계이고, 24h는 개정 공포→시행의 통상 간격 대비
        # 충분히 짧다.
        expires = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(expires_at if expires_at is not None
                        else time.time() + LAW_CACHE_TTL),
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

def _norm_law_name(name: str) -> str:
    """법령명 표기 정규화 — 가운뎃점 이형 흡수 + 공백 정리.

    법제처 정식명은 한글 가운뎃점 ㆍ(U+318D)를 쓰는데 LLM·하드코딩 인용은
    ·(U+00B7)·‧(U+2027)이 섞인다. 코드포인트가 다르면 LM 조회도 부분일치도
    전부 조용히 실패한다 — 실측: 남녀고용평등법 인용이 U+00B7 하나 때문에
    괴롭힘 상담에서 상시 누락됐다(분석 P1-4).
    """
    for dot in ("·", "‧"):
        name = name.replace(dot, "ㆍ")
    return " ".join(name.split())


def _norm_compact(name: str) -> str:
    """정규화 + 공백 제거 — '표기 변형'(띄어쓰기 차이) 동일성 판정용."""
    return _norm_law_name(name).replace(" ", "")


def _law_key(name: str) -> str:
    """법령명 동일성 키 — 공백과 가운뎃점을 **모두** 지운다(캐시 키·예열 대상 판정·중복 제거용).

    LLM은 정식명의 가운뎃점(ㆍ)을 아예 빼고 쓰기도 한다 — 실측(topic30 1번, 의도분석 OpenAI):
    "남녀고용평등과일가정양립지원에관한법률". 점을 남긴 키는 예열 행(정식명)과 갈려 조회가 0건이 된다.
    가운뎃점 유무만 다른 서로 다른 법령은 없다.
    """
    return _norm_compact(name).replace("ㆍ", "")


# 약칭은 공백·가운뎃점을 지운 형태로 찾는다 — "남녀 고용평등법"처럼 띄어 쓴 약칭도 같은 정식명이 된다.
_ALIASES_COMPACT = {_law_key(k): v for k, v in _LAW_NAME_ALIASES.items()}


def _alias_name(name: str) -> str:
    """약칭만 정식명으로 바꾸고, 그 밖은 가운뎃점·공백만 정규화한 원명(예열 대상 색인 없이)."""
    n = _norm_law_name(name or "")
    return _ALIASES_COMPACT.get(_law_key(n), n)


def _official_name_index() -> dict[str, str]:
    try:
        from app.core.law_catalog import official_name_index   # 순환 회피 — 늦은 import
        return official_name_index()
    except Exception:   # 표기 정리용 — 실패해도 조회는 원명으로 진행한다
        logger.warning("법령명 색인 로드 실패", exc_info=True)
        return {}


def canonical_law_name(name: str) -> str:
    """정식 법령명(D3) — 약칭은 정식명으로, 예열 대상 법령은 띄어쓰기·가운뎃점 변형도 정식명으로,
    그 밖은 가운뎃점·공백만 정규화한 원명. LM 조회명과 조문 머리글이 이 값이다."""
    n = _alias_name(name)
    return _official_name_index().get(_law_key(n)) or n


def _resolve_law_name(name: str) -> str:
    """약칭을 정식명칭으로 변환(가운뎃점·공백 정규화 포함). 조회용 — canonical_law_name과 같다."""
    return canonical_law_name(name)


def article_cache_key(law_name: str, article_no: int, sub: int | None = None,
                      paragraph: int | None = None) -> str:
    """조문 캐시 키(v5) — **예열(warm_law_cache)과 조회(fetch_article)가 같이 쓰는 단일 함수**(D3).

    법령명은 약칭을 정식명으로 바꾼 뒤 공백·가운뎃점까지 지운 형태다(_law_key). 공백 정리만으로는 LLM
    표기("근로자퇴직급여보장법"·"남녀고용평등과일가정…")와 정식명 키가 갈리고, 실호출을 끄면 그 차이를
    메울 경로가 없다. 세대 접두사 이력은 fetch_article 참조.
    """
    key = f"v5:{_law_key(_alias_name(law_name))}_{article_no}"
    if sub:
        key += f"의{sub}"
    if paragraph:
        key += f"_{paragraph}"
    return key


def _article_label(law_name: str, article_no: int, sub: int | None = None,
                   paragraph: int | None = None) -> str:
    """로그용 조문 표기 — 조의N·항까지(`근로기준법 제76조의2 제1항`)."""
    return (f"{law_name} 제{article_no}조" + (f"의{sub}" if sub else "")
            + (f" 제{paragraph}항" if paragraph else ""))


# ── 정식 법령명 해석 (LM 미매칭 폴백 전용) ──────────────────────────────────

def _resolve_official_name(law_name: str, api_key: str) -> str | None:
    """법령 검색으로 정식 법령명을 해석한다.

    주요 법령은 별칭 사전(_LAW_NAME_ALIASES)의 정식명이 LM에 바로 매칭돼
    이 함수까지 오지 않는다 — 발동 대상은 의도분석 LLM이 relevant_laws에
    넣은 비정형 이름(미등록 약칭·부정확 표기)뿐이다.
    """
    canonical = _resolve_law_name(law_name)

    if canonical in _OFFICIAL_NAME_CACHE:
        return _OFFICIAL_NAME_CACHE[canonical]

    if not _live_allowed():   # 호출자(fetch_article)가 이미 막지만, 다른 호출 경로를 위해 둔다
        return None

    # 서킷 검사는 호출자(fetch_article)가 이미 통과했다 — 여기서 또 하면
    # probe로 통과한 요청이 자기가 세운 probing 플래그에 막혀 폴백을 못 탄다
    # (실측: probe 요청의 호출 엔드포인트가 LM 하나뿐 — 분석 P2-2).

    try:
        # eflaw 목록은 판본마다 같은 법령을 반복한다 — nw=3(현행)으로 법령당 1행만
        # 받아야 상위 법령의 판본들이 칸을 채워 목표 법령이 밀려나지 않는다.
        resp = _http.get(LAW_SEARCH_URL, params={
            "OC": api_key,
            "target": "eflaw",
            "type": "XML",
            "query": canonical,
            "nw": "3",
            "display": "10",
        }, timeout=LAW_SEARCH_TIMEOUT)
        resp.raise_for_status()

        root = safe_xml.fromstring(resp.content)
        _raise_if_error_root(root)
        for law_el in root.iter("law"):
            name_el = law_el.find("법령명한글")
            if name_el is None:
                name_el = law_el.find("법령명_한글")
            if name_el is None or not name_el.text:
                continue
            text = name_el.text.strip()
            # compact(공백 제거·가운뎃점 통일) 후 양방향 부분일치 — 원형
            # 그대로 비교하면 공백 변형("근로자퇴직급여보장법" vs
            # "근로자퇴직급여 보장법")이 어느 방향으로도 부분문자열이 아니라
            # 폴백의 목적(표기 변형 구제) 자체가 성립하지 않는다(Act 회귀
            # 테스트 B1이 적발). 검색 자체가 fuzzy라 첫 매칭이 최상위다.
            a, b = _norm_compact(canonical), _norm_compact(text)
            if a in b or b in a:
                _OFFICIAL_NAME_CACHE[canonical] = text
                _circuit_record_success()
                return text
        _circuit_record_success()
    except LawApiAuthError:
        raise   # 호출자(fetch_article)가 auth_error로 분류하고 실패를 한 번만 기록한다
    except Exception as e:
        logger.warning("법령명 해석 실패 (%s): %s", law_name, e)
        _circuit_record_failure()

    # 성공한 이름만 캐시한다 — None을 영구 저장하면 일시적 검색 장애가
    # 워밍 인스턴스 수명 내내 그 법령명을 차단한다(CodeRabbit #55).
    # 미매칭 재시도 억제는 호출자의 L1 negative 캐시(_MISS_SENTINEL, TTL
    # 있음)가 담당하므로 여기의 영구 None은 필요 없다.
    return None


# ── 법령 본문 루트 조회 (공용 — 캐시·서킷 없음) ─────────────────────────────

def fetch_law_root(lm: str, api_key: str, *, ef_yd: str | None = None,
                   timeout: float | None = None) -> ET.Element | None:
    """법령 본문 XML 루트(`<법령>`). **조문 조회와 게이트의 단일 출처**다.

    답변 경로(fetch_article)·공식 원문 수집(fetch_official_rules)·그래프 빌드·현행성
    점검(check_law_freshness)이 모두 이 함수를 쓴다 — 조회·게이트가 네 벌로 복제돼
    있던 것을 합쳤다(effective-law D11). 캐시·서킷은 호출자 몫이다.

    - ``target=eflaw``. ``ef_yd``가 없으면 법제처 **현행 시행판**, 있으면 그 판본
      (판본 시행일만 유효 — 임의 날짜는 빈 ``<Law>``가 온다).
    - 요청 LM은 ``_resolve_law_name``으로 정규화한다(약칭·가운뎃점 이형).

    ⚠️ 미매칭도 HTTP 200으로 온다 — 본문이 빈 <Law> 루트다(실측).
    raise_for_status()로는 절대 잡히지 않으므로 루트 태그로 판정해야
    한다. 이 판정이 없으면 폴백이 영영 발동하지 않는다.

    ⚠️ 자격증명·파라미터 오류도 HTTP 200이다 — <Response> 루트에 오류
    문구가 온다(실측: 키 만료 시 "필수입력요소 검증에 실패"). 이를
    미매칭으로 취급하면 API 키 장애가 "법령명 문제"로 영구 오진되고
    회로도 안 열린다 — LawApiAuthError로 올려 failure 경로를 태운다(분석 P1-3).
    프로덕션(Vercel)은 IP 미등록이라 "사용자 정보 검증에 실패"가 이 경로로 온다.

    ⚠️ 법령 루트여도 그대로 믿지 않는다 — LM은 별칭·폐지판까지
    해석한다(실측: '근로자직업훈련촉진법' → '국민 평생 직업능력
    개발법' 반환, '노동조합법' → 1996년 타법폐지판). 반환 법령명이
    요청과 다르거나 폐지면 거부해야 **다른 법의 조문이 요청한 법령명
    헤더를 달고 나가는** 오인용을 막는다(분석 P1-1).
    """
    lm = _resolve_law_name(lm)
    params = {
        "OC": api_key,
        "target": "eflaw",
        "LM": lm,
        "type": "XML",
    }
    if ef_yd:
        params["efYd"] = ef_yd
    resp = _http.get(LAW_SERVICE_URL, params=params,
                     timeout=LAW_SERVICE_TIMEOUT if timeout is None else timeout)
    resp.raise_for_status()
    root = safe_xml.fromstring(resp.content)
    _raise_if_error_root(root)
    if root.tag != "법령":
        return None
    returned = (root.findtext(".//기본정보/법령명_한글")
                or root.findtext(".//기본정보/법령명한글") or "").strip()
    if returned and _norm_compact(returned) != _norm_compact(lm):
        logger.warning("법령명 오해석 거부 (요청 %r → 반환 %r)", lm, returned)
        return None
    status = (root.findtext(".//기본정보/제개정구분") or "").strip()
    if "폐지" in status:
        logger.warning("폐지 법령 거부 (%s: %s)", lm, status)
        return None
    return root


# ── 조문 조회 (3단계 캐시: L1 → L2 → L3) ────────────────────────────────────

def _is_warmed_law(law_name: str) -> bool:
    """예열 대상 법령인가(D7 — off에서 미스를 `miss`와 `skipped_unwarmed`로 가른다)."""
    try:
        from app.core.law_catalog import warm_law_keys   # 순환 회피: law_catalog가 이 모듈을 import
        return _law_key(_alias_name(law_name)) in warm_law_keys()
    except Exception:   # 분류용 — 실패해도 조회를 막지 않는다
        logger.warning("예열 대상 판정 실패 (%s)", law_name, exc_info=True)
        return False


def fetch_article(law_name: str, article_no: int, api_key: str,
                  paragraph: int | None = None,
                  sub: int | None = None,
                  *, outcome: dict | None = None) -> str | None:
    """특정 법률의 조문 텍스트를 3단계 캐시 계층으로 조회.

    법령명(LM) + eflaw로 조회하므로 **현행 시행판**이 온다(fetch_law_root).
    MST(일련번호)를 명시하던 구 방식은 그 판본이 고정 반환돼, 사전매핑이 낡을수록
    옛 조문을 답하는 드리프트가 있었다(law-version-drift). `target=law`는 시행 예정
    개정이 섞여 미래 조문을 답했다(effective-law).

    순서: L1(항) → L2(항) → [항 요청이면] L1(조문) → L2(조문) → [LAW_API_LIVE=on이면] L3.
    항 키가 캐시에 없으면 같은 조문의 전체 키를 본다(D4) — "항이 없으면 조문 전체로 폴백"하는
    기존 의미와 같다. 예열 행은 조문·항 단위로 들어 있지만 LLM이 항 번호를 잘못 낼 수 있다.

    Args:
        sub: "조의N" 번호 (예: 제76조의2 → sub=2)
        outcome: 넘기면 결과 분류를 ``outcome["status"]``에 남긴다(D7) — ``ok_cache``·``ok_live``·
            ``miss``(빈 루트·조문 없음, off면 예열 대상인데 키 없음)·``auth_error``·``error``(L3 예외,
            off면 L2 조회 실패)·``skipped_unwarmed``(off·예열 대상 아님)·``skipped_circuit``. 반환형은 그대로다.
    """
    def _done(status: str, text: str | None = None) -> str | None:
        _set_status(outcome, status)
        return text

    # 세대 접두사 — 캐시된 조문 **형식·출처**가 바뀌면 올린다. 구 키의 낡은 조문이 L2에
    # 남지만(자동 삭제 경로는 없다) 지우는 대신 **안 읽는** 방식이라 마이그레이션이 없고,
    # 롤백 시 구버전 코드가 구 키를 그대로 읽어 안전하다.
    # v2: LM 전환(MST 시절 낡은 판본). v3: 목(目) 포함(2026-10-03 — v2 캐시는 목이 빠져 있다).
    # v4: eflaw 전환(2026-10-04 — v3 캐시에는 target=law의 시행 예정 본문이 들어 있다).
    # v5: 정식명·공백 제거 키(2026-10-06 — 예열 행과 조회 키를 한 함수로 만든다, article_cache_key).
    cache_key = article_cache_key(law_name, article_no, sub, paragraph)
    article_key = article_cache_key(law_name, article_no, sub) if paragraph else None

    # L1: 인메모리 캐시 (미매칭 negative 표지 포함 — 없으면 실패한 법령명이
    # 매 요청 LM 왕복을 반복한다. 구 코드는 _MST_CACHE[...]=None으로 2회째
    # 0회였는데 그 성질이 LM 전환에서 빠졌었다. 분석 P2-3)
    cached = _cache_get(cache_key)
    if cached is not None:
        return _done("miss") if cached == _MISS_SENTINEL else _done("ok_cache", cached)

    # L2: Supabase 영속 캐시. 조회 실패는 '행 없음'과 구분한다 — 실호출을 끈 프로덕션에서 그대로
    # 미스로 세면 예열 누락처럼 보여 원인을 잘못 짚는다.
    l2_failed = False
    try:
        l2_cached = _l2_cache_get(cache_key, raise_on_error=True)
    except L2ReadError:
        l2_cached, l2_failed = None, True
    if l2_cached is not None:
        _cache_set(cache_key, l2_cached, _article_expiry())  # L1에도 저장(자정 상한)
        return _done("ok_cache", l2_cached)

    # 항 → 조문 폴백(D4). 조문 키의 L1이 미매칭 표지면 법령명이 맞지 않는 것이다 — 미스로 보고
    # 항 키로 복사하지 않는다(복사하면 표지가 본문처럼 퍼진다).
    if article_key:
        whole = _cache_get(article_key)
        if whole == _MISS_SENTINEL:
            return _done("miss")
        if whole is None:
            try:
                whole = _l2_cache_get(article_key, raise_on_error=True)
            except L2ReadError:
                whole, l2_failed = None, True
            if whole is not None:
                _cache_set(article_key, whole, _article_expiry())
        if whole is not None:
            _cache_set(cache_key, whole, _article_expiry())
            return _done("ok_cache", whole)

    label = _article_label(law_name, article_no, sub, paragraph)
    # 실호출 스위치는 서킷보다 먼저 본다(D5). 차단은 미매칭 표지를 남기지 않는다.
    if not _live_allowed():
        if l2_failed:
            return _done("error")   # 캐시 조회 장애 — 예열 누락과 구분한다(WARNING은 _l2_cache_get이 남겼다)
        warmed = _is_warmed_law(law_name)
        # 원 입력 → 키를 남긴다 — LLM이 내는 법령명 변형을 실측해 약칭을 보강하는 근거다(D3).
        logger.info("조문 캐시 미스(실호출 꺼짐%s): %s → %s",
                    "" if warmed else ", 예열 대상 아님", label, cache_key)
        return _done("miss" if warmed else "skipped_unwarmed")

    if _circuit_check():
        return _done("skipped_circuit")

    def _fetch_by_lm(lm: str) -> ET.Element | None:
        """조회·게이트는 fetch_law_root 단일 출처(미매칭=None, 오류 응답=예외)."""
        return fetch_law_root(lm, api_key)

    # L3: API 호출 — 성공 경로는 1회(구 방식은 검색+조회 2회)
    try:
        canonical = _resolve_law_name(law_name)
        root = _fetch_by_lm(canonical)
        if root is None:
            # 미매칭 폴백(1회): 표기 변형(띄어쓰기·가운뎃점)을 검색으로 정식명 해석
            # 후 재시도. **표기 키(_law_key) 동일일 때만** — 실질적으로 다른 이름
            # (개명·다른 법)으로의 해석을 허용하면 조문과 헤더(요청명)가
            # 어긋나는 오인용이 되살아난다(P1-1과 같은 결말).
            official = _resolve_official_name(law_name, api_key)
            if (official and official != canonical
                    and _law_key(official) == _law_key(canonical)):
                root = _fetch_by_lm(official)
        if root is None:
            logger.warning("법령 LM 미매칭 (%s): 정식명 해석 실패", label)
            # negative 캐시는 L1에만 — L2에 남기면 오타 하나가 7일간 영속된다.
            for key in filter(None, (cache_key, article_key)):
                _cache_set(key, _MISS_SENTINEL, _article_expiry())
            # 서킷은 중립 — success를 기록하면 폴백 검색의 failure가 상쇄되고
            # (검색 장애에도 회로 영구 미개방), 무기록이면 probe가 갇힌다.
            _circuit_record_neutral()
            return _done("miss")

        article_text = _extract_article(root, article_no, paragraph, sub)
        if article_text:
            expiry = _article_expiry()
            _cache_set(cache_key, article_text, expiry)                  # L1
            _l2_cache_set(cache_key, canonical, article_no, article_text,
                          expires_at=expiry)                             # L2
            _circuit_record_success()
            return _done("ok_live", article_text)

        _circuit_record_success()
        return _done("miss")
    except Exception as e:
        logger.warning("조문 조회 %s (%s): %s",
                       "인증 오류" if isinstance(e, LawApiAuthError) else "실패", label, e)
        _circuit_record_failure()
        return _done(_failure_status(e))


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
            # "조의N" 필터링: 조문가지번호 태그 또는 조문번호 텍스트에서 확인.
            # "0"·"00"은 가지 없음이다 — check_law_freshness._article_key·예열 키와 같은 판정(검증 L8).
            branch_el = jo.find("조문가지번호")
            branch_no = (int(branch_el.text) or None) if branch_el is not None and branch_el.text else None
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
                        if _parse_hang_no(hang_no_el.text) == paragraph:
                            return _format_article_text(jo_no_el.text, hang)
                # 항 미발견 → 조문 전체로 폴백. None을 반환하면 인용이 통째로
                # 사라진다 — 항 하나보다 조문 전체가 낫다(분석 P1-2).
                return _format_full_article(jo)
            else:
                return _format_full_article(jo)
    return None


def _parse_hang_no(text: str) -> int | None:
    """항번호 텍스트 → 정수. 법제처는 ASCII 숫자가 아니라 원문자(①②…)를 쓴다.

    `re.search(r"(\\d+)", "①")`은 절대 매치되지 않아 항 단위 조회가 전량
    None이었다(실측 4법령 — prompts.py가 명시 지시하는 '최저임금법 제6조
    제5항'이 한 번도 조회된 적 없음). 원문자 블록은 셋으로 나뉜다:
    ①~⑳ U+2460~, ㉑~㉟ U+3251~, ㊱~㊿ U+32B1~ (각각 연속).
    """
    for c in text:
        if "①" <= c <= "⑳":
            return ord(c) - 0x2460 + 1
        if "㉑" <= c <= "㉟":
            return ord(c) - 0x3251 + 21
        if "㊱" <= c <= "㊿":
            return ord(c) - 0x32B1 + 36
    m = re.search(r"(\d+)", text)
    return int(m.group(1)) if m else None


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
        _append_ho_mok(hang, parts)

    return "\n".join(parts) if parts else None


def _append_ho_mok(hang_el: ET.Element, parts: list[str]) -> None:
    """호와 그 아래 **목(目)** 을 붙인다.

    목을 빼면 안 된다 — 요건이 목에 있는 조문이 많다. 고용보험법 제40조①5호는 본문이
    "다음 각 목의 어느 하나에 해당할 것"뿐이고 실제 요건(3분의 1 미만·건설일용 14일)은
    가·나목에 있다. 목이 빠진 현행 조문을 받은 LLM은 빈자리를 상담글의 폐기 기준
    ("10일 미만")으로 채워 **현행 조문인 것처럼** 인용했다(지식iN 13·18번, 2026-10-03 실측).
    fetch_official_rules 는 같은 함정을 이미 피하고 있었고 답변 경로만 남아 있었다.
    """
    for ho in hang_el.iter("호"):
        ho_content = ho.find("호내용")
        if ho_content is not None and ho_content.text:
            parts.append(f"  {ho_content.text.strip()}")
        for mok in ho.iter("목"):
            mok_content = mok.find("목내용")
            if mok_content is not None and mok_content.text:
                parts.append(f"    {mok_content.text.strip()}")


def _format_article_text(jo_no_text: str, hang_el: ET.Element) -> str:
    """특정 항을 포맷팅."""
    parts = [jo_no_text.strip()]
    hang_content = hang_el.find("항내용")
    if hang_content is not None and hang_content.text:
        parts.append(hang_content.text.strip())
    _append_ho_mok(hang_el, parts)
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


# ── 참조 정규화 키 (2-1·2-2 중복 제거·제외의 단일 기준, D3·D8) ───────────────

def law_ref_key(ref: str) -> str:
    """참조 문자열의 정규화 키. 조문은 article_cache_key와 같고, 판례는 사건번호, 그 밖은 공백 제거 원문."""
    parsed = parse_law_reference(ref or "")
    if parsed is not None:
        return article_cache_key(parsed["law"], parsed["article"], parsed.get("sub"),
                                 parsed.get("paragraph"))
    prec = parse_precedent_reference(ref or "")
    if prec is not None:
        return f"prec:{prec['year']}{prec['type']}{prec['number']}"
    return "ref:" + "".join((ref or "").split())


def _article_identity(ref: str) -> tuple[str, int, int | None] | None:
    """(정식명 compact, 조, 조의N) — 항을 무시한 조문 동일성. 조문 참조가 아니면 None."""
    parsed = parse_law_reference(ref or "")
    if parsed is None:
        return None
    return (_law_key(_alias_name(parsed["law"])), parsed["article"], parsed.get("sub"))


def select_law_refs(refs, *, exclude_keys=(), drop_refs=(), limit: int | None = None) -> list[str]:
    """정규화 키로 중복을 빼고(순서 보존), exclude_keys와 같은 키·drop_refs와 같은 **조문**(항 무관)을
    뺀 뒤 limit개까지. 2-1·2-2가 같은 조문을 두 번 싣거나 세지 않게 하는 단일 경로다."""
    drop = {i for i in map(_article_identity, drop_refs) if i is not None}
    seen = set(exclude_keys)
    out: list[str] = []
    for ref in refs or ():
        if not ref:
            continue
        key = law_ref_key(ref)
        if key in seen or (drop and _article_identity(ref) in drop):
            continue
        seen.add(key)
        out.append(ref)
        if limit is not None and len(out) >= limit:
            break
    return out


# ── 판례 검색·조회 ───────────────────────────────────────────────────────────

def search_precedent(query: str, api_key: str,
                     max_results: int = 3, *, outcome: dict | None = None) -> list[dict]:
    """판례 검색 → [{id, case_name, date, court}]

    outcome: ``ok``(1건 이상)·``miss``(0건)·``auth_error``·``error``·``skipped``(실호출 꺼짐·서킷).
    """
    if not _live_allowed() or _circuit_check():
        _set_status(outcome, "skipped")
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

        root = safe_xml.fromstring(resp.content)
        # 인증 오류를 '0건'으로 읽고 서킷에 성공을 기록하던 경로다(D6) — 예외로 failure를 태운다.
        _raise_if_error_root(root)
        results = []
        for prec in root.iter("prec"):
            prec_id = _el_text(prec, "판례일련번호")
            if not prec_id:
                continue
            results.append({
                "id": int(prec_id),
                "case_name": _el_text(prec, "사건명") or "",
                "case_no": _el_text(prec, "사건번호") or "",
                "date": _el_text(prec, "선고일자") or "",
                "court": _el_text(prec, "법원명") or "",
            })
        _circuit_record_success()
        _set_status(outcome, "ok" if results else "miss")
        return results
    except Exception as e:
        logger.warning("판례 검색 실패 (%s): %s", query, e)
        _circuit_record_failure()
        _set_status(outcome, _failure_status(e))
        return []


def search_precedent_multi(
    queries: list[str],
    api_key: str,
    max_total: int = 5,
    *,
    stats: dict | None = None,
) -> list[dict]:
    """복수 쿼리로 판례 병렬 검색 → 중복 제거 후 max_total건 반환.

    각 쿼리당 max_results=3으로 검색하고, 판례일련번호 기준 중복 제거.
    stats: 넘기면 쿼리마다 검색 1회를 precedents에 센다(metadata.law_api v2).
    """
    if not queries or not api_key:
        return []

    seen_ids: set[int] = set()
    all_results: list[dict] = []
    statuses: list[str | None] = []

    def _search_one(q: str) -> list[dict]:
        outcome: dict = {}
        try:
            return search_precedent(q, api_key, max_results=3, outcome=outcome)
        finally:
            statuses.append(outcome.get("status"))   # list.append는 스레드 안전하다

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

    for status in statuses:
        _record_search(stats, status)
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
                max_results: int = 3, *, outcome: dict | None = None) -> list[dict]:
    """헌재 결정례 검색 → [{id, case_name, date}]. outcome은 search_precedent와 같다."""
    if not _live_allowed() or _circuit_check():
        _set_status(outcome, "skipped")
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

        root = safe_xml.fromstring(resp.content)
        _raise_if_error_root(root)
        results = []
        for detc in root.iter("Detc"):
            detc_id = _el_text(detc, "헌재결정례일련번호")
            if not detc_id:
                continue
            results.append({
                "id": int(detc_id),
                "case_name": _el_text(detc, "사건명") or "",
                "case_no": _el_text(detc, "사건번호") or "",
                "date": _el_text(detc, "종국일자") or "",
                "court": "헌법재판소",
            })
        _circuit_record_success()
        _set_status(outcome, "ok" if results else "miss")
        return results
    except Exception as e:
        logger.warning("헌재 결정 검색 실패 (%s): %s", query, e)
        _circuit_record_failure()
        _set_status(outcome, _failure_status(e))
        return []


def fetch_detc(detc_id: int, api_key: str, *, outcome: dict | None = None) -> str | None:
    """헌재 결정례에서 판시사항 + 결정요지 추출. 3단계 캐시 적용. outcome은 fetch_precedent와 같다."""
    cache_key = f"detc_{detc_id}"

    cached = _cache_get(cache_key)
    if cached is not None:
        _set_status(outcome, "ok")
        return cached

    l2_cached = _l2_cache_get(cache_key)
    if l2_cached is not None:
        _cache_set(cache_key, l2_cached)
        _set_status(outcome, "ok")
        return l2_cached

    if not _live_allowed() or _circuit_check():   # 캐시 조회 뒤에 게이트(검증 L2)
        _set_status(outcome, "skipped")
        return None

    try:
        resp = _http.get(LAW_SERVICE_URL, params={
            "OC": api_key,
            "target": "detc",
            "ID": str(detc_id),
            "type": "XML",
        }, timeout=LAW_SERVICE_TIMEOUT)
        resp.raise_for_status()

        root = safe_xml.fromstring(resp.content)
        _raise_if_error_root(root)
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
            _set_status(outcome, "ok")
            return text

        _circuit_record_success()
        _set_status(outcome, "miss")
    except Exception as e:
        logger.warning("헌재 결정 조회 실패 (ID=%d): %s", detc_id, e)
        _circuit_record_failure()
        _set_status(outcome, _failure_status(e))

    return None


def fetch_precedent(prec_id: int, api_key: str, *, outcome: dict | None = None) -> str | None:
    """판례 전문에서 판시사항 + 판결요지 추출. 3단계 캐시 적용.

    outcome: ``ok``·``miss``(요지 없음)·``auth_error``·``error``·``skipped``(실호출 꺼짐·서킷).
    """
    cache_key = f"prec_{prec_id}"

    # L1 캐시
    cached = _cache_get(cache_key)
    if cached is not None:
        _set_status(outcome, "ok")
        return cached

    # L2 캐시
    l2_cached = _l2_cache_get(cache_key)
    if l2_cached is not None:
        _cache_set(cache_key, l2_cached)
        _set_status(outcome, "ok")
        return l2_cached

    if not _live_allowed() or _circuit_check():   # 캐시 조회 뒤에 게이트(검증 L2)
        _set_status(outcome, "skipped")
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

        root = safe_xml.fromstring(resp.content)
        _raise_if_error_root(root)
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
            _set_status(outcome, "ok")
            return text

        _circuit_record_success()
        _set_status(outcome, "miss")
    except Exception as e:
        logger.warning("판례 조회 실패 (ID=%d): %s", prec_id, e)
        _circuit_record_failure()
        _set_status(outcome, _failure_status(e))

    return None


# ── 통합 조회 (pipeline.py에서 호출) ──────────────────────────────────────────

# 판례 번호 참조의 검색 폭 — 1페이지만 본다(답변 지연). 수집 스크립트처럼 페이지를 넘기지
# 않으므로 뒤 페이지에 밀린 사건은 None이 된다 — 엉뚱한 판례보다 공백이 낫다.
_PREC_REF_SEARCH_SIZE = 20


def _pick_exact_case(results: list[dict], wanted: str) -> dict | None:
    """검색 결과 중 사건번호가 요청과 **정확일치**(병합 사건 포함)하는 첫 항목.

    법제처 검색은 사건명 기준 fuzzy라 사건번호로 조회해도 무관한 판례를 돌려준다
    (실측: '90누9421' → 6건, 요청 사건 없음). 첫 결과를 그대로 채택하던 답변 경로는
    엉뚱한 판례 본문을 요청 번호의 근거처럼 실었다(effective-law D5).
    """
    from app.core.case_numbers import detail_matches
    for r in results:
        if r.get("case_no") and detail_matches(r["case_no"], wanted):
            return r
    return None


def fetch_relevant_articles(
    relevant_laws: list[str],
    api_key: str | None,
    *,
    stats: dict | None = None,
) -> str | None:
    """relevant_laws 목록을 병렬로 조회하여 통합 텍스트 반환.

    법조문과 판례를 동시에 처리. 부분 실패 허용.
    API 키가 없거나 모든 조회 실패 시 None 반환 → 기존 흐름 유지.

    stats: 넘기면 v2 구조(``{"articles": {...}, "precedents": {...}}``, new_law_stats)에 **누적**한다
        (production-law-api-recovery D7·D7b). 2-1·2-2가 같은 dict를 넘겨 한 대화의 조회를 합친다.
        조문 참조와 판례 번호 참조를 나눠 세고, 정확일치 거부는 ``precedents.rejected``다.
        `target=law` 폴백을 없앤 대신 실패를 **조용하지 않게** 남기는 관측 지점이다(effective-law D12).
    """
    counts = new_law_stats()
    lock = threading.Lock()

    def _count(group: str, *fields: str) -> None:
        with lock:
            for f in ("requested",) + fields:
                counts[group][f] += 1

    def _publish() -> None:
        if stats is not None:
            merge_law_stats(stats, counts)

    if not api_key or not relevant_laws:
        _publish()
        return None

    t0 = time.time()

    # 1. 파싱 (CPU-bound, 즉시)
    tasks: list[tuple[int, str, dict | None]] = []
    for idx, ref in enumerate(relevant_laws[:5]):
        parsed = parse_law_reference(ref)
        tasks.append((idx, ref, parsed))  # parsed=None이면 판례로 시도

    if not tasks:
        _publish()
        return None

    # 2. 병렬 조회
    results: dict[int, str] = {}

    def _fetch_one(idx: int, ref: str, parsed_law: dict | None) -> tuple[int, str | None]:
        """법조문 또는 판례 1건 조회."""
        # 법령 조문
        if parsed_law is not None:
            outcome: dict = {}
            text = fetch_article(
                law_name=parsed_law["law"],
                article_no=parsed_law["article"],
                api_key=api_key,
                paragraph=parsed_law.get("paragraph"),
                sub=parsed_law.get("sub"),
                outcome=outcome,
            )
            status = outcome.get("status")
            if text:
                law_display = _resolve_law_name(parsed_law["law"])
                sub_suffix = f"의{parsed_law['sub']}" if "sub" in parsed_law else ""
                _count("articles", "ok", *([status] if status in ("ok_cache", "ok_live") else []))
                return idx, f"[{law_display} 제{parsed_law['article']}조{sub_suffix}]\n{text}"
            _count("articles", status if status in _ARTICLE_FAILURES else "miss")
            return idx, None

        # 판례/헌재 결정 참조
        parsed_prec = parse_precedent_reference(ref)
        if parsed_prec is not None:
            query = f"{parsed_prec['year']}{parsed_prec['type']}{parsed_prec['number']}"

            # 정확일치 게이트(D5) — 사건번호가 요청과 같은 결과만 채택한다. 헤더에 사건번호를
            # 싣는다: 판례 본문은 자기 번호를 적지 않는 경우가 많아, 사건명만 두면 정당하게
            # 조회한 판례의 인용이 화이트리스트에 오르지 못한다.
            is_detc = parsed_prec["court"] == "헌재"
            searched: dict = {}
            candidates = (search_detc(query, api_key, max_results=_PREC_REF_SEARCH_SIZE, outcome=searched)
                          if is_detc else
                          search_precedent(query, api_key, max_results=_PREC_REF_SEARCH_SIZE, outcome=searched))
            hit = _pick_exact_case(candidates, query)
            if hit is None:
                if candidates:
                    _count("precedents", "rejected")
                    logger.info("판례 정확일치 실패: 요청 %s → 후보 %s", query,
                                [r.get("case_no") for r in candidates[:5]])
                else:
                    status = searched.get("status")
                    _count("precedents", status if status in _PRECEDENT_FAILURES else "miss")
                return idx, None
            detail: dict = {}
            text = (fetch_detc(hit["id"], api_key, outcome=detail) if is_detc
                    else fetch_precedent(hit["id"], api_key, outcome=detail))
            if text:
                case_name = hit["case_name"] or query
                prefix = "헌재 " if is_detc else ""
                _count("precedents", "ok")
                return idx, f"[{prefix}{case_name} {hit['case_no']}]\n{text}"
            status = detail.get("status")
            _count("precedents", status if status in _PRECEDENT_FAILURES else "miss")
            return idx, None

        # 조문도 판례도 아닌 참조(조 번호 없는 법령명 등) — 실어 주지 못한 조문 요청으로 센다
        _count("articles", "miss")
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
                _count("articles" if tasks[futures[fut]][2] is not None else "precedents", "error")
                logger.warning("병렬 조문 조회 실패: %s", e)

    elapsed = time.time() - t0
    a, p = counts["articles"], counts["precedents"]
    logger.info("법령 API 조회 완료: %d/%d건 / %.2fs (live=%s · 조문 캐시 %d·실호출 %d·미스 %d·"
                "인증 %d·오류 %d·건너뜀 %d · 판례 %d/%d 거부 %d)",
                len(results), len(tasks), elapsed, law_api_live_mode(),
                a["ok_cache"], a["ok_live"], a["miss"], a["auth_error"], a["error"],
                a["skipped_unwarmed"] + a["skipped_circuit"], p["ok"], p["requested"], p["rejected"])
    _publish()

    if not results:
        return None

    # 3. 원래 순서대로 정렬하여 반환
    return "\n\n".join(results[k] for k in sorted(results))


def fetch_relevant_precedents(
    query: str,
    api_key: str | None,
    max_results: int = 3,
    *,
    stats: dict | None = None,
) -> tuple[str | None, list[dict]]:
    """키워드로 법제처 API에서 판례를 검색하고 판결요지를 조회.

    stats: 넘기면 검색 1회를 precedents에 센다(metadata.law_api v2).

    Returns:
        (formatted_text, precedent_meta_list)
        - formatted_text: LLM 컨텍스트에 포함할 판례 텍스트 (None이면 실패)
        - precedent_meta_list: [{case_name, date, court, case_number}]
    """
    if not api_key or not query:
        return None, []

    t0 = time.time()

    # 1. 판례 검색
    searched: dict = {}
    prec_results = search_precedent(query, api_key, max_results=max_results, outcome=searched)
    _record_search(stats, searched.get("status"))
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


# ── NLRC 판정문 검색·조회 ─────────────────────────────────────────────────────
# search_precedent/fetch_precedent/fetch_relevant_precedents(위)를 target="nlrc"로
# 그대로 미러링한다(nlrc-decisions-corpus 설계 §2). 사건번호가 부분 마스킹돼
# 있어(예: "2016부해OOO") 인용·캐시 키로 쓸 수 없다 — 캐시 키는 대신 고유한
# 결정문일련번호를 쓰고, 포맷 함수는 사건번호 필드를 아예 노출하지 않는다.

def search_nlrc(query: str, api_key: str, max_results: int = 3,
                *, outcome: dict | None = None) -> list[dict]:
    """NLRC 판정문 검색 → [{id, title, case_no, date}]. 캐시 없음, 매번 라이브.

    outcome은 search_precedent와 같다. 실호출이 꺼져 있으면 HTTP 없이 빈 결과(skipped)다.
    """
    if not _live_allowed() or _circuit_check():
        _set_status(outcome, "skipped")
        return []
    try:
        resp = _http.get(LAW_SEARCH_URL, params={
            "OC": api_key, "target": "nlrc", "type": "XML",
            "query": query, "display": str(max_results),
        }, timeout=LAW_SEARCH_TIMEOUT)
        resp.raise_for_status()
        root = safe_xml.fromstring(resp.content)
        _raise_if_error_root(root)   # 인증 오류를 '0건'으로 읽던 경로(D6)
        results = []
        for el in root.iter("nlrc"):
            decision_id = _el_text(el, "결정문일련번호")
            if not decision_id:
                continue
            results.append({
                "id": int(decision_id),
                "title": _el_text(el, "제목") or "",
                "case_no": _el_text(el, "사건번호") or "",  # 마스킹됨 — 표시 금지
                "date": _el_text(el, "등록일") or "",
            })
        _circuit_record_success()
        _set_status(outcome, "ok" if results else "miss")
        return results
    except Exception as e:
        logger.warning("NLRC 검색 실패 (%s): %s", query, e)
        _circuit_record_failure()
        _set_status(outcome, _failure_status(e))
        return []


def fetch_nlrc_detail(decision_id: int, api_key: str) -> dict | None:
    """결정문 1건 상세 → {category, dept, date, gist, result}. 3단 캐시.

    캐시 키는 결정문일련번호(마스킹되지 않은 고유 숫자) 기반이다 — 사건번호는
    마스킹돼 있어 키로 쓸 수 없다. L1/L2는 str 계약이라 다중 필드를 JSON으로
    직렬화해 저장한다(L2 law_article_cache.content는 TEXT — 스키마 확인됨).
    """
    cache_key = f"nlrc_{decision_id}"

    # json.loads 실패(캐시에 비-JSON 값이 섞이는 이론상 경로)를 캐시 미스로
    # 강등한다 — 여기서 예외가 새면 ThreadPoolExecutor 워커를 거쳐
    # fetch_relevant_nlrc 전체가 죽고, 결국 pipeline.py의 최외곽 try/except가
    # NLRC 블록 전체를 삼킨다. L3 폴백이 있는데 그렇게까지 잃을 이유가 없다.
    cached = _cache_get(cache_key)
    if cached is not None:
        try:
            return json.loads(cached)
        except (json.JSONDecodeError, TypeError):
            logger.warning("NLRC L1 캐시 값이 JSON이 아님 (key=%s) — 미스로 처리", cache_key)

    l2_cached = _l2_cache_get(cache_key)
    if l2_cached is not None:
        try:
            record = json.loads(l2_cached)
        except (json.JSONDecodeError, TypeError):
            logger.warning("NLRC L2 캐시 값이 JSON이 아님 (key=%s) — 미스로 처리", cache_key)
        else:
            _cache_set(cache_key, l2_cached)
            return record

    if not _live_allowed() or _circuit_check():   # 캐시 조회 뒤에 게이트(검증 L2)
        return None

    try:
        resp = _http.get(LAW_SERVICE_URL, params={
            "OC": api_key, "target": "nlrc", "ID": str(decision_id), "type": "XML",
        }, timeout=LAW_SERVICE_TIMEOUT)
        resp.raise_for_status()
        root = safe_xml.fromstring(resp.content)
        _raise_if_error_root(root)

        gist = "\n".join(
            t for t in (
                (root.findtext("판정사항") or "").strip(),
                (root.findtext("판정요지") or "").strip(),
            ) if t
        )
        result = (root.findtext("판정결과") or "").strip()
        if not gist and not result:
            _circuit_record_success()
            return None

        record = {
            "category": (root.findtext("자료구분") or "").strip(),
            "dept": (root.findtext("담당부서") or "").strip(),
            "date": (root.findtext("등록일") or "").strip(),
            "gist": gist,
            "result": result,
        }
        serialized = json.dumps(record, ensure_ascii=False)
        _cache_set(cache_key, serialized)
        _l2_cache_set(cache_key, "", None, serialized, "nlrc")
        _circuit_record_success()
        return record
    except Exception as e:
        logger.warning("NLRC 상세 조회 실패 (ID=%s): %s", decision_id, e)
        _circuit_record_failure()
        return None


def fetch_relevant_nlrc(query: str, api_key: str | None,
                        max_results: int = 3, *, stats: dict | None = None) -> str | None:
    """키워드로 NLRC 판정문을 검색+조회해 포맷된 텍스트로 반환.

    fetch_relevant_precedents()와 같은 오케스트레이션이나 meta_list는 반환하지
    않는다 — pipeline.py의 소비처(_build_sources_payload/_citation_source_hits)가
    nlrc_text를 불투명 텍스트 블록으로만 다뤄 개별 판정 메타가 불필요하다.
    사건번호는 마스킹돼 있어 헤더에 담당부서·자료구분·날짜만 쓴다.
    stats: 넘기면 검색 1회를 precedents에 센다(metadata.law_api v2).
    """
    if not api_key or not query:
        return None
    t0 = time.time()

    searched: dict = {}
    results = search_nlrc(query, api_key, max_results=max_results, outcome=searched)
    _record_search(stats, searched.get("status"))
    if not results:
        return None

    parts: dict[int, str] = {}

    def _fetch_one(idx: int, r: dict) -> tuple[int, str | None]:
        detail = fetch_nlrc_detail(r["id"], api_key)
        if not detail:
            return idx, None
        # "중앙"으로 고정하지 않는다 — dept에 지방노동위(예: 충남지방노동위원회)가
        # 흔히 온다(Plan §1.2 실측). 고정하면 헤더와 바로 뒤 dept 표기가 상충한다.
        header = (f"[노동위원회 판정] {detail['category']} | "
                  f"{detail['dept']} | {detail['date']}")
        body = detail["gist"]
        if detail["result"]:
            body += f"\n판정결과: {detail['result']}"
        return idx, f"{header}\n{body}"

    with ThreadPoolExecutor(max_workers=min(len(results), 5)) as pool:
        futures = {pool.submit(_fetch_one, i, r): i for i, r in enumerate(results)}
        for fut in as_completed(futures):
            idx, text = fut.result()
            if text:
                parts[idx] = text

    elapsed = time.time() - t0
    logger.info("NLRC 라이브 검색 완료: query=%r, %d/%d건 / %.2fs",
                query[:30], len(parts), len(results), elapsed)

    if not parts:
        return None
    return "\n\n---\n\n".join(parts[k] for k in sorted(parts))
