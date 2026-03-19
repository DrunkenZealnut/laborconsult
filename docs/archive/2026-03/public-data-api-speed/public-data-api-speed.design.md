# Design: 법령/판례 등 공공데이터 API 연결 속도 개선

> Plan 참조: `docs/01-plan/features/public-data-api-speed.plan.md`

---

## 1. 현재 코드 분석

### 1.1 현재 아키텍처 (`app/core/legal_api.py`, 274줄)

```
모듈 전역 상태:
  _MST_CACHE: dict[str, int | None]         # 법령명 → MST 번호
  _ARTICLE_CACHE: dict[str, tuple[float, str]]  # 캐시키 → (timestamp, text)

호출 흐름:
  fetch_relevant_articles(relevant_laws, api_key)
    ↓ for ref in relevant_laws[:5]  ← 순차 루프
    ↓   parse_law_reference(ref)
    ↓   fetch_article(law_name, article_no, api_key, paragraph)
    ↓     _cache_get(key)          ← L1 인메모리 캐시 확인
    ↓     _lookup_mst(law_name)    ← MST 캐시 미스 시 API 호출
    ↓       requests.get(LAW_SEARCH_URL, timeout=5)
    ↓     requests.get(LAW_SERVICE_URL, timeout=5)
    ↓     _extract_article(root, article_no)
    ↓     _cache_set(key, text)    ← L1 저장
    ↓   articles.append(...)
    ↓ return "\n\n".join(articles)
```

### 1.2 병목 지점 정밀 분석

| # | 위치 (줄) | 병목 | 최악 지연 | 발생 빈도 |
|---|----------|------|----------|----------|
| B1 | L255 `for ref in relevant_laws[:5]` | 순차 루프 | 5건 × 10초 = 50초 | 매 호출 |
| B2 | L83 `requests.get(LAW_SEARCH_URL)` | MST 검색 API (매번 새 연결) | 5초/건 | L1 미스 시 |
| B3 | L128 `requests.get(LAW_SERVICE_URL)` | 조문 API (매번 새 연결) | 5초/건 | L1 미스 시 |
| B4 | L42 `_MST_CACHE = {}` | 프로세스 종료 시 소멸 | 콜드스타트당 전체 재조회 | 높음 (Vercel) |
| B5 | L46 `_ARTICLE_CACHE = {}` | 프로세스 종료 시 소멸 | 콜드스타트당 전체 재조회 | 높음 (Vercel) |
| B6 | L227 `parse_law_reference` | "대법원 YYYY다NNNNN" → None | 판례 질문 무응답 | 중 |

### 1.3 기존 API 인터페이스 (변경 없음)

```python
# pipeline.py (L789)에서 호출하는 공개 인터페이스 — 시그니처 유지
def fetch_relevant_articles(
    relevant_laws: list[str],
    api_key: str | None,
) -> str | None:
```

---

## 2. 설계 명세

### 2.1 Phase A: 병렬화 + MST 사전매핑 + 연결 풀 (P0)

#### DS-A1: MST 사전 매핑 테이블

**변경 파일**: `app/core/legal_api.py`
**변경 위치**: L42 `_MST_CACHE` 주변

```python
# ── MST 사전 매핑 (주요 노동법 — 법 전부개정 시에만 변경) ────────────────
_PRELOADED_MST: dict[str, int] = {
    "근로기준법": 270551,
    "최저임금법": 270545,
    "고용보험법": 270463,
    "산업재해보상보험법": 270346,
    "근로자퇴직급여 보장법": 270488,
    "남녀고용평등과 일·가정 양립 지원에 관한 법률": 270730,
    "소득세법": 270521,
    "조세특례제한법": 270478,
    "근로기준법 시행령": 270552,
    "최저임금법 시행령": 270546,
}

# ── MST 캐시 (동적 조회 결과 + 사전매핑 병합) ────────────────────────────
_MST_CACHE: dict[str, int | None] = dict(_PRELOADED_MST)  # 사전매핑으로 초기화
```

**_lookup_mst 수정**: 사전매핑 히트 시 API 호출 생략 (기존 캐시 체크 로직과 동일하게 동작, 변경 최소)

#### DS-A2: requests.Session 연결 풀링

**변경 파일**: `app/core/legal_api.py`
**변경 위치**: L18 `import requests` 하단

```python
# ── HTTP 세션 (Keep-Alive, 연결 재사용) ──────────────────────────────────
_http = requests.Session()
_http.headers.update({"Accept": "application/xml"})
```

**수정 대상**:
- L83 `requests.get(LAW_SEARCH_URL, ...)` → `_http.get(LAW_SEARCH_URL, ...)`
- L128 `requests.get(LAW_SERVICE_URL, ...)` → `_http.get(LAW_SERVICE_URL, ...)`

#### DS-A3: fetch_relevant_articles 병렬화

**변경 파일**: `app/core/legal_api.py`
**변경 위치**: L243 `fetch_relevant_articles` 함수 전체 교체

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def fetch_relevant_articles(
    relevant_laws: list[str],
    api_key: str | None,
) -> str | None:
    """relevant_laws 목록을 병렬로 조회하여 통합 텍스트 반환."""
    if not api_key or not relevant_laws:
        return None

    # 1. 파싱 (CPU-bound, 즉시)
    tasks: list[tuple[int, dict]] = []
    for idx, ref in enumerate(relevant_laws[:5]):
        parsed = parse_law_reference(ref)
        if parsed is not None:
            tasks.append((idx, parsed))

    if not tasks:
        return None

    # 2. 병렬 조문 조회
    results: dict[int, str] = {}

    def _fetch_one(idx: int, parsed: dict) -> tuple[int, str | None]:
        text = fetch_article(
            law_name=parsed["law"],
            article_no=parsed["article"],
            api_key=api_key,
            paragraph=parsed.get("paragraph"),
        )
        if text:
            law_display = _resolve_law_name(parsed["law"])
            return idx, f"[{law_display} 제{parsed['article']}조]\n{text}"
        return idx, None

    with ThreadPoolExecutor(max_workers=min(len(tasks), 5)) as pool:
        futures = {pool.submit(_fetch_one, idx, p): idx for idx, p in tasks}
        for fut in as_completed(futures):
            try:
                idx, article_text = fut.result()
                if article_text:
                    results[idx] = article_text
            except Exception as e:
                logger.warning("병렬 조문 조회 실패: %s", e)

    if not results:
        return None

    # 3. 원래 순서대로 정렬하여 반환
    return "\n\n".join(results[k] for k in sorted(results))
```

**핵심 설계 결정**:
- `ThreadPoolExecutor` 사용 (pipeline.py가 동기 코드이므로 asyncio 불필요)
- `max_workers=min(len(tasks), 5)` — 불필요한 스레드 생성 방지
- `as_completed` — 가장 빠른 응답부터 수집
- 개별 스레드 예외는 해당 건만 스킵 (부분 실패 허용)
- `results[idx]` + `sorted(results)` — 원래 법조문 순서 유지

### 2.2 Phase B: Supabase 영속 캐시 (P1)

#### DS-B1: Supabase 캐시 테이블

**실행 위치**: Supabase Dashboard SQL Editor

```sql
CREATE TABLE IF NOT EXISTS law_article_cache (
    cache_key   TEXT PRIMARY KEY,
    law_name    TEXT NOT NULL,
    article_no  INTEGER,
    content     TEXT NOT NULL,
    source_type TEXT DEFAULT 'law',  -- 'law' | 'prec' | 'expc'
    fetched_at  TIMESTAMPTZ DEFAULT NOW(),
    expires_at  TIMESTAMPTZ DEFAULT NOW() + INTERVAL '7 days'
);

-- 만료 행 자동 삭제용 인덱스
CREATE INDEX IF NOT EXISTS idx_cache_expires ON law_article_cache(expires_at);
```

#### DS-B2: 3단계 캐시 계층

**변경 파일**: `app/core/legal_api.py`
**새 함수 추가**:

```python
# ── Supabase 캐시 (L2) ─────────────────────────────────────────────────

_supabase_client = None  # 지연 초기화

def _init_supabase():
    """Supabase 클라이언트를 지연 초기화. 미설정 시 None."""
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if url and key:
        from supabase import create_client
        _supabase_client = create_client(url, key)
    return _supabase_client


def _l2_cache_get(key: str) -> str | None:
    """Supabase에서 캐시 조회. 만료 행은 무시."""
    sb = _init_supabase()
    if sb is None:
        return None
    try:
        resp = sb.table("law_article_cache") \
            .select("content") \
            .eq("cache_key", key) \
            .gt("expires_at", "now()") \
            .maybe_single() \
            .execute()
        if resp.data:
            return resp.data["content"]
    except Exception as e:
        logger.debug("L2 캐시 조회 실패 (%s): %s", key, e)
    return None


def _l2_cache_set(key: str, law_name: str, article_no: int | None,
                  content: str, source_type: str = "law") -> None:
    """Supabase에 캐시 저장. 실패 시 무시."""
    sb = _init_supabase()
    if sb is None:
        return
    try:
        sb.table("law_article_cache").upsert({
            "cache_key": key,
            "law_name": law_name,
            "article_no": article_no,
            "content": content,
            "source_type": source_type,
            "fetched_at": "now()",
            "expires_at": f"now() + interval '7 days'",
        }).execute()
    except Exception as e:
        logger.debug("L2 캐시 저장 실패 (%s): %s", key, e)
```

#### DS-B3: fetch_article 캐시 계층 통합

**변경 위치**: `fetch_article()` 함수 (L112-145)

```python
def fetch_article(law_name: str, article_no: int, api_key: str,
                  paragraph: int | None = None) -> str | None:
    """3단계 캐시 계층으로 조문 텍스트 조회.

    L1 (인메모리) → L2 (Supabase) → L3 (law.go.kr API)
    """
    cache_key = f"{law_name}_{article_no}"
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
        }, timeout=LAW_API_TIMEOUT)
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        article_text = _extract_article(root, article_no, paragraph)
        if article_text:
            _cache_set(cache_key, article_text)           # L1 저장
            _l2_cache_set(cache_key, law_name, article_no,
                          article_text, "law")             # L2 저장
            return article_text

    except Exception as e:
        logger.warning("조문 조회 실패 (%s 제%d조): %s", law_name, article_no, e)

    return None
```

### 2.3 Phase C: 판례·해석례 API (P2)

#### DS-C1: 판례 참조 패턴 파싱

**변경 위치**: L213 `_ARTICLE_PATTERN` 하단에 추가

```python
_PREC_PATTERN = re.compile(
    r"(?:대법원|헌법재판소|헌재)\s*(\d{4})\s*([가-힣]+)\s*(\d+)"
)

def parse_precedent_reference(ref: str) -> dict | None:
    """판례 참조 문자열 파싱.

    Examples:
        "대법원 2023다302838" → {"year": 2023, "type": "다", "number": 302838}
        "헌재 2021헌마1234"  → {"year": 2021, "type": "헌마", "number": 1234}
    """
    m = _PREC_PATTERN.search(ref)
    if not m:
        return None
    return {
        "year": int(m.group(1)),
        "type": m.group(2),
        "number": int(m.group(3)),
    }
```

#### DS-C2: 판례 검색·조회 함수

**변경 파일**: `app/core/legal_api.py` 하단 추가

```python
def search_precedent(query: str, api_key: str,
                     max_results: int = 3) -> list[dict]:
    """판례 검색 → [{id, case_name, date, summary}]"""
    try:
        resp = _http.get(LAW_SEARCH_URL, params={
            "OC": api_key,
            "target": "prec",
            "type": "XML",
            "query": query,
            "display": str(max_results),
        }, timeout=LAW_API_TIMEOUT)
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
        return results
    except Exception as e:
        logger.warning("판례 검색 실패 (%s): %s", query, e)
        return []


def fetch_precedent(prec_id: int, api_key: str) -> str | None:
    """판례 전문에서 판시사항 + 판결요지 추출."""
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

    try:
        resp = _http.get(LAW_SERVICE_URL, params={
            "OC": api_key,
            "target": "prec",
            "ID": str(prec_id),
            "type": "XML",
        }, timeout=LAW_API_TIMEOUT)
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        parts = []
        for field in ["판시사항", "판결요지"]:
            el = root.find(f".//{field}")
            if el is not None and el.text:
                parts.append(f"[{field}]\n{el.text.strip()}")

        if parts:
            text = "\n\n".join(parts)
            _cache_set(cache_key, text)
            _l2_cache_set(cache_key, "", None, text, "prec")
            return text

    except Exception as e:
        logger.warning("판례 조회 실패 (ID=%d): %s", prec_id, e)

    return None


def _el_text(parent: ET.Element, tag: str) -> str | None:
    """XML 엘리먼트에서 텍스트 추출 헬퍼."""
    el = parent.find(tag)
    return el.text.strip() if el is not None and el.text else None
```

#### DS-C3: fetch_relevant_articles 확장 (판례 지원)

**변경 위치**: `fetch_relevant_articles()` 내부 `_fetch_one` 함수 확장

```python
def _fetch_one(idx: int, ref: str, parsed_law: dict | None) -> tuple[int, str | None]:
    """법조문 또는 판례 1건 조회."""
    # 법령 조문
    if parsed_law is not None:
        text = fetch_article(
            law_name=parsed_law["law"],
            article_no=parsed_law["article"],
            api_key=api_key,
            paragraph=parsed_law.get("paragraph"),
        )
        if text:
            law_display = _resolve_law_name(parsed_law["law"])
            return idx, f"[{law_display} 제{parsed_law['article']}조]\n{text}"
        return idx, None

    # 판례 참조
    parsed_prec = parse_precedent_reference(ref)
    if parsed_prec is not None:
        query = f"{parsed_prec['year']}{parsed_prec['type']}{parsed_prec['number']}"
        results = search_precedent(query, api_key, max_results=1)
        if results:
            text = fetch_precedent(results[0]["id"], api_key)
            if text:
                return idx, f"[{results[0]['case_name']}]\n{text}"
    return idx, None
```

#### DS-C4: parse_law_reference 확장

**변경 위치**: `fetch_relevant_articles()` 의 파싱 단계

```python
# 1. 파싱 단계 확장
tasks: list[tuple[int, str, dict | None]] = []  # (idx, raw_ref, parsed_law_or_None)
for idx, ref in enumerate(relevant_laws[:5]):
    parsed = parse_law_reference(ref)
    tasks.append((idx, ref, parsed))  # parsed=None이면 판례로 시도
```

---

## 3. 변경 파일 상세

### 3.1 파일별 변경 범위

| # | 파일 | Phase | 변경 유형 | 변경 줄 수 (예상) |
|---|------|-------|----------|----------------|
| 1 | `app/core/legal_api.py` | A | MST 사전매핑 추가 | +15줄 |
| 2 | `app/core/legal_api.py` | A | `requests.Session` 도입 | +3줄, ~2줄 수정 |
| 3 | `app/core/legal_api.py` | A | `fetch_relevant_articles` 병렬화 | +35줄 (기존 ~20줄 교체) |
| 4 | `app/core/legal_api.py` | B | L2 캐시 함수 3개 | +55줄 |
| 5 | `app/core/legal_api.py` | B | `fetch_article` 캐시 계층 적용 | ~10줄 수정 |
| 6 | `app/core/legal_api.py` | C | 판례 패턴 파싱 + 검색/조회 | +80줄 |
| 7 | `app/core/legal_api.py` | C | `fetch_relevant_articles` 판례 확장 | ~15줄 수정 |
| 8 | `app/config.py` | B | (변경 없음 — Supabase 이미 연동) | 0줄 |
| 9 | `app/core/pipeline.py` | — | (변경 없음 — 인터페이스 유지) | 0줄 |
| 10 | `.env.example` | B | `LAW_CACHE_SUPABASE=true` 주석 추가 | +2줄 |

**총 예상**: 순수 추가 ~190줄, 수정 ~30줄. `legal_api.py`만 변경.

### 3.2 변경하지 않는 것

| 대상 | 이유 |
|------|------|
| `app/core/pipeline.py` | `fetch_relevant_articles()` 시그니처 유지 → 호출부 변경 불필요 |
| `app/config.py` | Supabase 클라이언트는 `legal_api.py`에서 독립 초기화 (config 의존성 추가 안 함) |
| `wage_calculator/` | 계산기와 완전 독립 |
| `chatbot.py` | CLI 전용, 파이프라인만 사용 |

---

## 4. 구현 순서

```
Phase A — 병렬화 + MST 사전매핑 (P0)
┌─────────────────────────────────────────────────────────────────────┐
│ Step 1: _PRELOADED_MST 딕셔너리 추가 + _MST_CACHE 초기화 병합      │
│ Step 2: _http = requests.Session() 도입 + get 호출 2곳 교체         │
│ Step 3: fetch_relevant_articles() ThreadPoolExecutor 병렬화 교체    │
│ Step 4: 로컬 테스트 — 순차 vs 병렬 시간 비교                        │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
Phase B — Supabase 영속 캐시 (P1)
┌─────────────────────────────────────────────────────────────────────┐
│ Step 5: Supabase SQL — law_article_cache 테이블 + 인덱스 생성       │
│ Step 6: _init_supabase(), _l2_cache_get(), _l2_cache_set() 추가     │
│ Step 7: fetch_article() 내부에 L2 캐시 계층 삽입                     │
│ Step 8: .env.example 업데이트                                       │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
Phase C — 판례·해석례 (P2)
┌─────────────────────────────────────────────────────────────────────┐
│ Step 9: _PREC_PATTERN + parse_precedent_reference() 추가            │
│ Step 10: search_precedent() + fetch_precedent() + _el_text() 추가   │
│ Step 11: fetch_relevant_articles() 판례 분기 추가                    │
│ Step 12: 통합 테스트 — 법조문 + 판례 혼합 질문                       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 5. 인터페이스 계약

### 5.1 공개 API (변경 없음)

```python
# pipeline.py에서 호출하는 유일한 공개 함수 — 시그니처 불변
def fetch_relevant_articles(
    relevant_laws: list[str],
    api_key: str | None,
) -> str | None:
    """법조문+판례를 병렬 조회하여 통합 텍스트 반환.

    반환 형식:
        "[근로기준법 제56조]\n조문 텍스트...\n\n[대법원 2023다302838]\n판결요지..."
        또는 None (전부 실패/미설정)
    """
```

### 5.2 신규 공개 함수 (Phase C)

```python
# 판례 검색 — 향후 직접 호출 가능
def search_precedent(query: str, api_key: str, max_results: int = 3) -> list[dict]
def fetch_precedent(prec_id: int, api_key: str) -> str | None
```

### 5.3 내부 함수 변경

| 함수 | 변경 내용 |
|------|----------|
| `_lookup_mst` | `_MST_CACHE` 초기값이 `_PRELOADED_MST`로 채워짐 → 주요 법령은 API 미호출 |
| `fetch_article` | L1 → L2 → L3 3단계 캐시 탐색 |
| `_cache_get/_cache_set` | 변경 없음 (L1 캐시 역할 유지) |

---

## 6. 에러 처리 설계

| 시나리오 | 처리 방식 | 사용자 영향 |
|---------|----------|-----------|
| 개별 스레드 API 실패 | 해당 건만 `None`, 다른 건 정상 반환 | 일부 법조문 누락, 나머지 표시 |
| Supabase 연결 실패 | L2 스킵, L1+L3로 동작 | 콜드스타트 시 약간 느림 |
| 모든 API 타임아웃 | `None` 반환 → pipeline.py 기존 RAG만 사용 | 법조문 없이 답변 (현재와 동일) |
| API 키 미설정 | 즉시 `None` 반환 | 현재와 동일 |
| 판례 검색 결과 없음 | 해당 건 `None` | 법조문만 표시 |
| ThreadPool 예외 | `try/except` per future | 로그 후 해당 건 스킵 |

---

## 7. 성능 목표 및 측정

### 7.1 목표 지표

| 시나리오 | 현재 (예상) | 목표 | 측정 방법 |
|---------|-----------|------|----------|
| 콜드스타트 + 3건 (L2 미스) | 10~25초 | <5초 | `time.time()` 래핑 로그 |
| 콜드스타트 + 3건 (L2 히트) | 10~25초 | <500ms | Supabase 조회 시간 로그 |
| 웜스타트 + 3건 (L1 히트) | ~0ms | ~0ms | 변경 없음 |
| 단일 조문 (전부 미스) | 2~10초 | <3초 | API 응답 시간 로그 |

### 7.2 측정 로깅

```python
# fetch_relevant_articles 내부에 성능 로그 추가
import time

def fetch_relevant_articles(...):
    t0 = time.time()
    # ... 병렬 조회 로직 ...
    elapsed = time.time() - t0
    logger.info("법령 API 조회 완료: %d건 / %.2fs (캐시 히트: %d건)",
                len(results), elapsed, cache_hits)
```

---

## 8. 테스트 시나리오

| # | 테스트 | 입력 | 기대 결과 |
|---|-------|------|----------|
| T1 | MST 사전매핑 히트 | `_lookup_mst("근로기준법", key)` | API 미호출, 즉시 270551 반환 |
| T2 | MST 사전매핑 미스 | `_lookup_mst("국민연금법", key)` | API 호출 후 캐시 저장 |
| T3 | 병렬 조회 3건 | `fetch_relevant_articles(["근기법 제56조", "근기법 제60조", "최임법 제6조"], key)` | 3건 모두 반환, 소요시간 <5s |
| T4 | 부분 실패 | 1건 타임아웃 + 2건 성공 | 2건만 포함된 텍스트 반환 |
| T5 | L2 캐시 히트 | 콜드스타트 후 이전 조회 건 | Supabase에서 즉시 조회 |
| T6 | L2 미설정 | Supabase 환경변수 없음 | L1+L3로 정상 동작 |
| T7 | 판례 검색 | `"대법원 2023다302838"` in relevant_laws | 판결요지 텍스트 포함 |
| T8 | 혼합 조회 | 법조문 2건 + 판례 1건 | 3건 모두 병렬 조회 후 순서대로 반환 |
| T9 | Session 재사용 | 연속 2회 호출 | 2번째 호출 시 TCP 재연결 없음 |
| T10 | 전부 실패 | API 키 잘못됨 | `None` 반환, pipeline.py RAG만 동작 |

---

## 9. 의존성

### 9.1 Python 패키지

| 패키지 | 버전 | 용도 | 상태 |
|--------|------|------|------|
| `requests` | 기존 | HTTP 클라이언트 + Session | 이미 설치 |
| `concurrent.futures` | stdlib | 스레드 풀 | 추가 설치 불필요 |
| `supabase` | 기존 | L2 캐시 | 이미 설치 (optional) |

**추가 설치 패키지: 없음**

### 9.2 외부 서비스

| 서비스 | 용도 | 설정 |
|--------|------|------|
| law.go.kr DRF API | 법령·판례 조회 | `LAW_API_KEY` (기존) |
| Supabase | L2 영속 캐시 | `SUPABASE_URL`, `SUPABASE_KEY` (기존) |

---

## 10. 롤백 전략

| Phase | 롤백 방법 | 영향 |
|-------|----------|------|
| A (병렬화) | `ThreadPoolExecutor` 제거, 순차 루프 복원 | 기존 속도로 복귀 |
| B (L2 캐시) | `_l2_cache_get/set` 호출 제거 | L1+L3로 동작 (현재와 동일) |
| C (판례) | 판례 관련 함수/분기 제거 | "대법원..." → None (현재와 동일) |

각 Phase가 독립적이라 부분 롤백 가능. `pipeline.py`는 변경하지 않으므로 `legal_api.py`만 되돌리면 됨.
