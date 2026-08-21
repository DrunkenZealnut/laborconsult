"""법제처 국가법령정보 Open API 클라이언트

법제처 DRF API(law.go.kr)를 통해 현행 법령 조문·판례를 실시간 조회한다.
- 조문: 법령명(LM) 직접 조회 — 항상 현행판. MST(일련번호) 지정은 그 판본을
  고정 반환하므로 쓰지 않는다(드리프트 이력은 _OFFICIAL_NAME_CACHE 위 주석)
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
import threading
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
}


# ⚠️ MST(법령일련번호) 사전 매핑을 두지 말 것 (law-version-drift, 2026-08-20).
# MST를 명시해 조회하면 **그 판본의** 조문이 고정 반환된다. 과거의 사전매핑은
# "법 전부개정 시에만 변경"을 전제했지만 실제로는 **일부개정마다 일련번호가
# 바뀐다** — 매핑해 둔 주요 법령일수록 낡은 조문을 답하는 역설이 생겼다
# (실측 2026-08-20: 17개 중 11개가 낡았고, 고용보험법 §70 육아휴직 급여
# 요건의 "30일 또는 7일" 확대가 누락돼 있었다). 조문 조회는 법령명(LM)
# 파라미터로 한다 — 법제처가 항상 현행판을 반환해 드리프트가 원리적으로
# 불가능하고, 검색(MST 획득) 왕복이 사라져 호출도 2회→1회로 준다.

# ── 정식 법령명 해석 캐시 (LM 미매칭 폴백 결과: 입력명 → 정식명 | None) ──────
_OFFICIAL_NAME_CACHE: dict[str, str | None] = {}


# ── L1 조문 캐시 (인메모리, TTL 기반) ────────────────────────────────────────
_ARTICLE_CACHE: dict[str, tuple[float, str]] = {}

# 미매칭 negative 표지 — L1 전용(TTL 동일 적용). L2에는 절대 저장하지 않는다.
_MISS_SENTINEL = "__lm_miss__"


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
            _supabase_client = make_supabase_client()
        except Exception as e:
            logger.debug("Supabase 초기화 실패: %s", e)
        _supabase_checked = True
    return _supabase_client


def _l2_cache_get(key: str) -> str | None:
    """L2(Supabase)에서 캐시 조회. 만료 행은 무시."""
    sb = _init_supabase()
    if sb is None:
        return None
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
        # 만료 = L1과 동일한 24h(LAW_CACHE_TTL). 구 7일은 "현행판 보장"과
        # 상충했다 — 캐시 수명 동안은 개정이 반영되지 않으므로, 이 값이 곧
        # 조문 최신성의 최대 지연이다(CodeRabbit #55 Major). MST 드리프트
        # (무기한)와 달리 유계이고, 24h는 개정 공포→시행의 통상 간격 대비
        # 충분히 짧다.
        expires = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(time.time() + LAW_CACHE_TTL),
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


def _resolve_law_name(name: str) -> str:
    """약칭을 정식명칭으로 변환(가운뎃점·공백 정규화 포함)."""
    name = _norm_law_name(name)
    return _LAW_NAME_ALIASES.get(name, name)


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

    # 서킷 검사는 호출자(fetch_article)가 이미 통과했다 — 여기서 또 하면
    # probe로 통과한 요청이 자기가 세운 probing 플래그에 막혀 폴백을 못 탄다
    # (실측: probe 요청의 호출 엔드포인트가 LM 하나뿐 — 분석 P2-2).

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
    except Exception as e:
        logger.warning("법령명 해석 실패 (%s): %s", law_name, e)
        _circuit_record_failure()

    # 성공한 이름만 캐시한다 — None을 영구 저장하면 일시적 검색 장애가
    # 워밍 인스턴스 수명 내내 그 법령명을 차단한다(CodeRabbit #55).
    # 미매칭 재시도 억제는 호출자의 L1 negative 캐시(_MISS_SENTINEL, TTL
    # 있음)가 담당하므로 여기의 영구 None은 필요 없다.
    return None


# ── 조문 조회 (3단계 캐시: L1 → L2 → L3) ────────────────────────────────────

def fetch_article(law_name: str, article_no: int, api_key: str,
                  paragraph: int | None = None,
                  sub: int | None = None) -> str | None:
    """특정 법률의 조문 텍스트를 3단계 캐시 계층으로 조회.

    법령명(LM)으로 조회하므로 항상 **현행판**이 온다 — MST(일련번호)를
    명시하던 구 방식은 그 판본이 고정 반환돼, 사전매핑이 낡을수록 옛 조문을
    답하는 드리프트가 있었다(law-version-drift).

    Args:
        sub: "조의N" 번호 (예: 제76조의2 → sub=2)
    """
    # v2: 접두사 — LM 전환 시점의 캐시 세대 구분. 구 키(MST 시절)의 낡은
    # 조문이 L2에 남지만(만료 7일 — 자동 삭제 경로는 없다) 지우는 대신
    # **안 읽는** 방식이라 마이그레이션이 없고, 롤백 시 구버전 코드가 구 키를
    # 그대로 읽어 안전하다.
    cache_key = f"v2:{law_name}_{article_no}"
    if sub:
        cache_key += f"의{sub}"
    if paragraph:
        cache_key += f"_{paragraph}"

    # L1: 인메모리 캐시 (미매칭 negative 표지 포함 — 없으면 실패한 법령명이
    # 매 요청 LM 왕복을 반복한다. 구 코드는 _MST_CACHE[...]=None으로 2회째
    # 0회였는데 그 성질이 LM 전환에서 빠졌었다. 분석 P2-3)
    cached = _cache_get(cache_key)
    if cached is not None:
        return None if cached == _MISS_SENTINEL else cached

    # L2: Supabase 영속 캐시
    l2_cached = _l2_cache_get(cache_key)
    if l2_cached is not None:
        _cache_set(cache_key, l2_cached)  # L1에도 저장
        return l2_cached

    if _circuit_check():
        return None

    def _fetch_by_lm(lm: str) -> ET.Element | None:
        """LM(법령명) 조회. 매칭 실패를 None으로 정규화한다.

        ⚠️ 미매칭도 HTTP 200으로 온다 — 본문이 빈 <Law> 루트다(실측).
        raise_for_status()로는 절대 잡히지 않으므로 루트 태그로 판정해야
        한다. 이 판정이 없으면 폴백이 영영 발동하지 않는다.

        ⚠️ 자격증명·파라미터 오류도 HTTP 200이다 — <Response> 루트에 오류
        문구가 온다(실측: 키 만료 시 "필수입력요소 검증에 실패"). 이를
        미매칭으로 취급하면 API 키 장애가 "법령명 문제"로 영구 오진되고
        회로도 안 열린다 — 예외로 올려 failure 경로를 태운다(분석 P1-3).

        ⚠️ 법령 루트여도 그대로 믿지 않는다 — LM은 별칭·폐지판까지
        해석한다(실측: '근로자직업훈련촉진법' → '국민 평생 직업능력
        개발법' 반환, '노동조합법' → 1996년 타법폐지판). 반환 법령명이
        요청과 다르거나 폐지면 거부해야 **다른 법의 조문이 요청한 법령명
        헤더를 달고 나가는** 오인용을 막는다(분석 P1-1).
        """
        resp = _http.get(LAW_SERVICE_URL, params={
            "OC": api_key,
            "target": "law",
            "LM": lm,
            "type": "XML",
        }, timeout=LAW_SERVICE_TIMEOUT)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        if root.tag == "Response":
            detail = (root.findtext(".//result") or root.findtext(".//message")
                      or "").strip()[:80]
            raise RuntimeError(f"법제처 API 오류 응답: {detail}")
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

    # L3: API 호출 — 성공 경로는 1회(구 방식은 검색+조회 2회)
    try:
        canonical = _resolve_law_name(law_name)
        root = _fetch_by_lm(canonical)
        if root is None:
            # 미매칭 폴백(1회): 표기 변형(띄어쓰기 등)을 검색으로 정식명 해석
            # 후 재시도. **compact 동일일 때만** — 실질적으로 다른 이름
            # (개명·다른 법)으로의 해석을 허용하면 조문과 헤더(요청명)가
            # 어긋나는 오인용이 되살아난다(P1-1과 같은 결말).
            official = _resolve_official_name(law_name, api_key)
            if (official and official != canonical
                    and _norm_compact(official) == _norm_compact(canonical)):
                root = _fetch_by_lm(official)
        if root is None:
            logger.warning("법령 LM 미매칭 (%s): 정식명 해석 실패", law_name)
            # negative 캐시는 L1에만 — L2에 남기면 오타 하나가 7일간 영속된다.
            _cache_set(cache_key, _MISS_SENTINEL)
            # 서킷은 중립 — success를 기록하면 폴백 검색의 failure가 상쇄되고
            # (검색 장애에도 회로 영구 미개방), 무기록이면 probe가 갇힌다.
            _circuit_record_neutral()
            return None

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
