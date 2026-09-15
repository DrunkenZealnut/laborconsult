# nlrc-decisions-corpus Design

> **Plan**: `docs/01-plan/features/nlrc-decisions-corpus.plan.md`
> **Period**: 2026-09-15
> **Status**: Do 완료(§9 1~7 완료, CI 전량 통과 + 실 API 라이브 스모크 확인). 8(커밋+PR)만 남음

---

## 0. Plan 대비 이번 Design에서 확정한 것

Plan §3.2가 제시한 함수 시그니처를 실제 XML 필드·캐시 키·에러 처리까지 구체화했다.
Plan에 없던 결정 셋:

| 결정 | 내용 | 근거 |
|---|---|---|
| 배치 위치 | `legal_api.py`에 추가(신규 모듈 아님) | `search_precedent`류와 `_http`·`_circuit_check`·`_cache_get`·`_l2_cache_get` 인프라를 그대로 공유해야 "미러링"이 성립한다 |
| `nlrc_cases.py` | **삭제**(번들·odcloud·카테고리 키워드 매핑 포함) | `pipeline.py` 1개 호출부 외 소비자 없음(§4.1 실측). 대체가 아니라 상위 경로라 병행 이유가 없다 |
| 파이프라인 변경 폭 | **1줄 함수 교체**만, 트리거·변수명·하류 소비 전부 불변 | `_build_sources_payload`/`_citation_source_hits`가 `nlrc_text`를 이미 텍스트 블록으로만 다뤄(§3.3) 개별 판정 단위 메타가 불필요하다 |
| 반환 타입 | `fetch_relevant_nlrc() -> str \| None` (meta_list 없음) | `fetch_relevant_precedents()`의 `(text, meta_list)`와 다르다 — meta_list의 유일한 소비처가 없어 만들면 죽은 필드가 된다 |

---

## 1. 범위

### 1.1 산출물

| # | 파일 | 변경 |
|---|---|---|
| 1 | `app/core/legal_api.py` | `search_nlrc()`·`fetch_nlrc_detail()`·`fetch_relevant_nlrc()` 신규(§2) |
| 2 | `app/core/pipeline.py` | "2-1c" 블록 1곳 교체(§3) |
| 3 | `app/core/nlrc_cases.py` | **삭제**(§4) |
| 4 | `refresh_nlrc_cases.py` | **삭제**(§4) |
| 5 | `data/nlrc_cases.json` | **삭제**(§4) |
| 6 | `app/config.py` | `odcloud_api_key` 필드 삭제(§4) |
| 7 | `.env.example`, `CLAUDE.md` | `ODCLOUD_API_KEY` 관련 서술 제거(§4) |
| 8 | `test_offline_units.py` | `test_nlrc_bundle()` 삭제, `test_legal_api_nlrc()` 신규(§6) |

### 1.2 비범위

- **Pinecone·BM25 변경 없음** — 색인·임베딩·업로드 스크립트를 전혀 건드리지 않는다(Plan §3.1의 기각 사유가 그대로 이유다)
- **원장(ledger) 없음** — `vector_ledger.py` 미사용. 저장하는 벡터가 없다
- **`archive_precedents.py`의 NLRC 제외 규칙 불변** — `:922` *"NLRC 제외 — data/nlrc_cases.json에 사건번호·본문 필드 없음(설계 §5.3)"* 은 그 판례 아카이브(문서 번들·인벤토리)가 다루는 대상이 Pinecone 적재분이기 때문이다. 이 사이클은 아무것도 적재하지 않으므로 그 제외 규칙은 **이 변경과 무관하게 계속 옳다** — 갱신 불요
- **인용 화이트리스트 확장 없음** — 마스킹된 사건번호는 애초에 `\d+` 기반 사건번호 정규식에 매치되지 않는다(§5)

---

## 2. `legal_api.py` 신규 함수

### 2.1 XML 스키마 실측 (2026-09-15, 3건 라이브 프로브)

```
검색(lawSearch.do, target=nlrc, section=evtNm):
  <nlrc id="1"><결정문일련번호>15255</결정문일련번호>
    <제목><![CDATA[○ ○ ○ 부당해고 구제신청]]></제목>
    <사건번호>2016부해OOO</사건번호><등록일>2016.05.09</등록일></nlrc>

상세(lawService.do, target=nlrc, ID=결정문일련번호):
  <NlrcService><결정문일련번호>15255</결정문일련번호>
    <기관명>노동위원회</기관명><사건번호>2016부해OOO</사건번호>
    <자료구분>부당해고</자료구분><담당부서>충남지방노동위원회</담당부서>
    <등록일>2016.5.9.</등록일><제목><![CDATA[...]]></제목>
    <내용></내용>  ← 3건 모두 공백, 사용 안 함
    <판정사항><![CDATA[...]]></판정사항>
    <판정요지><![CDATA[...]]></판정요지>
    <판정결과><![CDATA[각하]]></판정결과></NlrcService>
```

실측 3건 본문 합계(판정사항+판정요지+판정결과): 470·486·728자 — 전부 700자 미만.
사건번호는 3건 전부 마지막 구간이 `OOO`로 마스킹됨(`2016부해OOO`·`2023부노OOO`·
`2023차별OOO`) — **인용·중복판정 키로 쓰지 않는다**(§5).

### 2.2 `search_nlrc()`

```python
def search_nlrc(query: str, api_key: str, max_results: int = 3) -> list[dict]:
    """NLRC 판정문 검색 → [{id, title, case_no, category, dept, date}]

    search_precedent()와 동일 계약 — 캐시 없음(질의별 히트율이 낮아 무의미),
    매번 라이브. LAW_SEARCH_TIMEOUT(3s) 적용. target만 다르다.
    """
    if _circuit_check():
        return []
    try:
        resp = _http.get(LAW_SEARCH_URL, params={
            "OC": api_key, "target": "nlrc", "type": "XML",
            "query": query, "display": str(max_results),
        }, timeout=LAW_SEARCH_TIMEOUT)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        results = []
        for el in root.iter("nlrc"):
            decision_id = _el_text(el, "결정문일련번호")
            if not decision_id:
                continue
            results.append({
                "id": int(decision_id),
                "title": _el_text(el, "제목") or "",
                "case_no": _el_text(el, "사건번호") or "",  # 표시 금지, §5
                "date": _el_text(el, "등록일") or "",
            })
        _circuit_record_success()
        return results
    except Exception as e:
        logger.warning("NLRC 검색 실패 (%s): %s", query, e)
        _circuit_record_failure()
        return []
```

`search_precedent()`와 글자 그대로 같은 구조다 — 필드명과 `target`만 다르다.
`case_no`는 검색 결과 dict에 담되(디버깅·로깅용) **포맷 함수에서 노출하지 않는다.**

### 2.3 `fetch_nlrc_detail()` — 캐시 키가 핵심

```python
def fetch_nlrc_detail(decision_id: int, api_key: str) -> dict | None:
    """결정문 1건 상세 → {category, dept, date, gist, result}. 3단 캐시.

    캐시 키가 `결정문일련번호`(마스킹 안 된 숫자)인 것이 이 설계의 핵심이다
    — fetch_precedent()의 prec_id와 같은 역할이고, 마스킹된 사건번호로는
    성립하지 않는 것(원장 키 등)이 이 숫자 하나로 전부 우회된다(Plan §3.1).
    """
    cache_key = f"nlrc_{decision_id}"

    cached = _cache_get(cache_key)
    if cached is not None:
        return json.loads(cached)  # L1은 str 저장 계약 — 아래 참고

    l2_cached = _l2_cache_get(cache_key)
    if l2_cached is not None:
        _cache_set(cache_key, l2_cached)
        return json.loads(l2_cached)

    if _circuit_check():
        return None

    try:
        resp = _http.get(LAW_SERVICE_URL, params={
            "OC": api_key, "target": "nlrc", "ID": str(decision_id), "type": "XML",
        }, timeout=LAW_SERVICE_TIMEOUT)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)

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
```

⚠️ **`_cache_get`/`_cache_set`은 현재 `str`만 주고받는 계약이다**(확인됨 —
`_cache_get(key) -> str | None`, `_cache_set(key, text) -> None`,
`_l2_cache_set(key, law_name, article_no, content, source_type="law")`,
`fetch_precedent`가 그렇게 쓴다). 상세는 필드가 여럿(category·dept·date·gist·
result)이라 문자열 하나로는 부족해 `json.dumps`/`loads`로 감쌌다 — 이 계약
확장이 네 함수의 시그니처 자체를 바꾸진 않는다(값이 문자열인 건 동일, 그
문자열이 JSON일 뿐). `_l2_cache_set`은 `(key, "", None, serialized, "nlrc")`로
호출(`fetch_precedent`의 `(cache_key, "", None, text, "prec")` 패턴과 동형).
L2(Supabase) 컬럼 타입이 text라면 문제없다 — **Do 단계에서 L2 캐시 테이블
스키마를 확인할 것**(마이그레이션이 필요하면 이 설계가 그 작업을 포함하도록
갱신). **`legal_api.py`에 `json` import가 없다**(확인됨, 2026-09-15) — Do
1단계에 `import json` 추가를 포함시킬 것.

### 2.4 `fetch_relevant_nlrc()` — 파이프라인 진입점

```python
def fetch_relevant_nlrc(query: str, api_key: str | None,
                        max_results: int = 3) -> str | None:
    """키워드로 NLRC 판정문을 검색+조회해 포맷된 텍스트로 반환.

    fetch_relevant_precedents()와 같은 얕은 오케스트레이션이나 반환형이
    다르다 — meta_list를 안 만든다(§0). 인용 표시는 §5 참고.
    """
    if not api_key or not query:
        return None
    t0 = time.time()

    results = search_nlrc(query, api_key, max_results=max_results)
    if not results:
        return None

    parts: dict[int, str] = {}

    def _fetch_one(idx: int, r: dict) -> tuple[int, str | None]:
        detail = fetch_nlrc_detail(r["id"], api_key)
        if not detail:
            return idx, None
        header = (f"[중앙노동위원회 판정] {detail['category']} | "
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
```

---

## 3. 파이프라인 교체

`pipeline.py:1814`("2-1c") 원본:

```python
nlrc_text = None
if analysis and config.odcloud_api_key:
    try:
        nlrc_keywords = getattr(analysis, "precedent_keywords", None) or []
        topic = getattr(analysis, "consultation_topic", None)
        if topic:
            nlrc_keywords = list(nlrc_keywords) + [topic.replace("·", " ")]
        if nlrc_keywords:
            nlrc_text = search_nlrc_with_details(
                nlrc_keywords, odcloud_api_key=config.odcloud_api_key,
                law_api_key=config.law_api_key, max_results=3,
            )
            if nlrc_text:
                logger.info("NLRC 판정사례 검색 완료")
    except Exception as e:
        logger.warning("NLRC 판정사례 검색 실패 (무시): %s", e)
```

변경 후 — **게이트와 호출부만** 바뀐다:

```python
nlrc_text = None
if analysis and config.law_api_key:                        # ← odcloud_api_key
    try:                                                    #    → law_api_key
        nlrc_keywords = getattr(analysis, "precedent_keywords", None) or []
        topic = getattr(analysis, "consultation_topic", None)
        if topic:
            nlrc_keywords = list(nlrc_keywords) + [topic.replace("·", " ")]
        if nlrc_keywords:
            nlrc_query = " ".join(nlrc_keywords[:3])         # ← 키워드 리스트를
            nlrc_text = fetch_relevant_nlrc(                 #   질의 문자열로
                nlrc_query, config.law_api_key, max_results=3)
            if nlrc_text:
                logger.info("NLRC 판정사례 검색 완료")
    except Exception as e:
        logger.warning("NLRC 판정사례 검색 실패 (무시): %s", e)
```

`search_nlrc()`가 court precedent의 `search_precedent()`와 같이 **단일 질의
문자열**을 받는 계약이라(구 `search_nlrc_cases()`는 키워드 리스트를 받아 내부
매칭했다), 리스트→문자열 결합이 유일한 실질 변경이다. `nlrc_keywords[:3]` 상한은
`build_precedent_queries()`가 이미 쓰는 절제(과다 키워드가 fuzzy 검색을 더
흐린다) 관례를 따른다.

### 3.1 트리거 조건 변경의 의미

`config.odcloud_api_key` → `config.law_api_key`. **`LAW_API_KEY`는 이미 판례·
법령 조문 검색의 필수 키**이므로 이 경로가 별도 키 없이도 나머지 법제처 연동과
같은 가용성을 갖는다 — 오히려 지금까지는 `ODCLOUD_API_KEY`가 없으면 NLRC 전체가
꺼지는 **불필요한 추가 장애점**이었다.

### 3.2 하류 소비처 불변 확인

`_build_sources_payload()`·`_citation_source_hits()`(둘 다 `pipeline.py`)는
`nlrc_text: str | None`을 **불투명 텍스트 블록**으로만 다룬다(`("nlrc", "nlrc_case",
"중앙노동위원회 판정사례", nlrc_text)`) — 개별 판정 단위 구조를 보지 않는다.
프런트 `public/index.html:1385`의 `nlrc_case: '판정사례'` 라벨도 이 블록 단위
그대로다. **셋 다 수정 불요** — 변수명·타입이 그대로라 자동으로 맞물린다.

---

## 4. 폐기 범위

### 4.1 소비자 전수 확인 — `nlrc_cases.py`

```
refresh_nlrc_cases.py   → 삭제 대상 자신(번들 갱신 스크립트, 번들이 없어지면 무의미)
test_offline_units.py   → test_nlrc_bundle() 삭제(§6)
app/core/pipeline.py    → §3의 교체로 소비 종료
```

이 셋 외 소비자 없음(전수 grep, 2026-09-15). `search_nlrc_cases()`·
`_CATEGORY_KEYWORDS`·`_search_related_precedent()`·`_load_bundle()`·
`_fetch_all_cases()` 전부 이 세 소비자 경로 안에서만 쓰였다 — 부분 재사용 없이
파일째 삭제한다.

### 4.2 연쇄 폐기

| 대상 | 처리 | 확인 |
|---|---|---|
| `data/nlrc_cases.json` | 삭제 | `_load_bundle()`의 유일한 독자가 사라짐 |
| `app/config.py::odcloud_api_key` | 필드 삭제 | `check_env.py`에 없음(애초에 필수 검증 대상 아니었다), 다른 소비자 없음(§4.1) |
| `.env.example`의 `ODCLOUD_API_KEY=...` | 삭제 | |
| `CLAUDE.md` — Commands "NLRC 판정사례 번들 갱신" 블록 | 삭제 | `refresh_nlrc_cases.py` 명령 자체가 없어짐 |
| `CLAUDE.md` — `ODCLOUD_API_KEY` 환경변수 설명 | 삭제 | |
| `CLAUDE.md` — Pipeline Flow §4 "`nlrc_cases.py` (판정사례 360건 — 번들 우선 로드…)" | `legal_api.py` 라이브 조회로 서술 교체 | |

**`archive_precedents.py:922`의 NLRC 제외 주석은 건드리지 않는다**(§1.2) — 그
설명("설계 §5.3")이 가리키는 옛 문서가 사라지므로 주석 자체는 자기완결적으로
다시 쓰되("Pinecone에 적재하지 않는 라이브 조회 경로라 아카이브 대상이 아님"),
**판정 로직(제외)은 그대로 유지**한다.

---

## 5. 인용 표시 — 마스킹 대응

LLM 컨텍스트에 들어가는 헤더는 `사건번호`를 쓰지 않는다:

```
[중앙노동위원회 판정] 부당해고 | 충남지방노동위원회 | 2016.5.9.
법인등기부등본 상 분사무소이자...(판정사항)
...(판정요지)
판정결과: 각하
```

시스템 프롬프트에 "노동위 판정은 사건번호로 지목하지 말고 담당부서·자료구분·
날짜로 설명할 것"이라는 지시를 추가할지는 Do 단계에서 실답변 샘플로 판단한다
— LLM이 `판정사항` 텍스트 안에 등장하는 사건 설명을 스스로 사건번호처럼
인용하려 들 가능성은 낮지만(원문 자체에 마스킹 안 된 번호가 없으므로 지어낼
근거가 없다), 프롬프트 레벨 명시가 더 안전하면 추가한다.

인용 화이트리스트(`citation_validator`)는 **아무 것도 새로 할 필요가 없다** —
`case_no` 필드를 포맷 함수가 애초에 안 쓰므로 마스킹된 번호가 컨텍스트에 노출될
경로 자체가 없고, 정규식 기반 인용 추출도 `OOO`엔 매치되지 않는다(수비적으로도
안전).

---

## 6. 회귀 테스트

`test_offline_units.py`에 네트워크 없이 XML 파싱 계약을 고정한다 — 이 프로젝트에
`legal_api.py`의 판례 검색 경로(`search_precedent`/`fetch_precedent`) 자체가
지금까지 오프라인 회귀가 **없었다**(전수 grep 확인). 새 경로는 만들되 기존 경로
소급 보강은 이 사이클 범위 밖이다.

픽스처는 **2026-09-15 실제 프로브로 받은 XML 그대로** 쓴다(추측 데이터 아님):

```python
def test_legal_api_nlrc() -> None:
    from app.core import legal_api as L

    search_xml = (
        '<?xml version="1.0" encoding="UTF-8"?><Nlrc>'
        '<nlrc id="1"><결정문일련번호>15255</결정문일련번호>'
        '<제목><![CDATA[○ ○ ○ 부당해고 구제신청]]></제목>'
        '<사건번호>2016부해OOO</사건번호><등록일>2016.05.09</등록일></nlrc></Nlrc>'
    )
    detail_xml = (
        '<?xml version="1.0" encoding="UTF-8"?><NlrcService>'
        '<결정문일련번호>15255</결정문일련번호><기관명>노동위원회</기관명>'
        '<사건번호>2016부해OOO</사건번호><자료구분>부당해고</자료구분>'
        '<담당부서>충남지방노동위원회</담당부서><등록일>2016.5.9.</등록일>'
        '<제목><![CDATA[○ ○ ○ 부당해고 구제신청]]></제목><내용></내용>'
        '<판정사항><![CDATA[법인등기부등본 상 분사무소...]]></판정사항>'
        '<판정요지><![CDATA[○ ○ ○는 법인등기부등본이나...]]></판정요지>'
        '<판정결과><![CDATA[각하]]></판정결과></NlrcService>'
    )
    root = ET.fromstring(search_xml)
    el = next(root.iter("nlrc"))
    assert L._el_text(el, "결정문일련번호") == "15255"
    assert L._el_text(el, "사건번호") == "2016부해OOO"  # 마스킹 — 표시 금지 확인용

    droot = ET.fromstring(detail_xml)
    assert (droot.findtext("판정사항") or "").strip().startswith("법인등기부등본")
    assert (droot.findtext("판정결과") or "").strip() == "각하"
    print("  ✅ NLRC XML 파싱: 검색·상세 필드 추출 확인")


def test_legal_api_nlrc_cache_key() -> None:
    from app.core import legal_api as L
    import inspect

    src = inspect.getsource(L.fetch_nlrc_detail)
    assert 'f"nlrc_{decision_id}"' in src, "캐시 키가 결정문일련번호 기반이 아님"
    assert '["사건번호"]' not in src and "case_no" not in src.split("def ")[1], (
        "fetch_nlrc_detail이 마스킹된 사건번호를 반환값에 담고 있음(§5 위반)")
    print("  ✅ NLRC 캐시 키: 마스킹 안 된 결정문일련번호 기반")


def test_pipeline_nlrc_gate() -> None:
    """odcloud_api_key가 아니라 law_api_key로 게이트하는지(§3.1)."""
    import inspect
    from app.core import pipeline as P

    src = inspect.getsource(P)
    assert "config.odcloud_api_key" not in src, "구 odcloud 게이트가 남아있음"
    assert "fetch_relevant_nlrc" in src, "신규 함수가 배선되지 않음"
    print("  ✅ 파이프라인: NLRC 게이트가 law_api_key로 교체됨")
```

`_el_text`는 `search_precedent()`가 이미 쓰는 헬퍼(존재 확인만, 새로 안 만든다).
`fetch_relevant_nlrc()` 자체(네트워크·ThreadPoolExecutor 포함)는 오프라인
테스트 대상이 아니다 — `fetch_relevant_precedents()`도 지금까지 그렇다.

---

## 7. 저작권 가드 (Plan §5.1 기술적 완화 구체화)

| 완화책 | 구현 위치 |
|---|---|
| 짧은 발췌만 | `fetch_nlrc_detail()`이 `판정사항`+`판정요지`만 조합 — 실측 최대 728자, `내용` 필드(전문이 있다면 그쪽일 가능성) 미사용 |
| 장기 보관 없음 | `LAW_CACHE_TTL`(24h, 기존 상수 재사용) — 별도 TTL 신설 안 함 |
| 출처 항상 명시 | `fetch_relevant_nlrc()`의 헤더 포맷이 담당부서·자료구분·날짜를 매번 포함(§2.4) — 조건부 아님 |
| 저장소 미보관 | Pinecone·BM25·원장·아카이브 전부 미접촉(§1.2) — 캐시(L1 인메모리 프로세스 수명, L2 Supabase 24h TTL)만 |

---

## 8. 리스크

| 리스크 | 대응 |
|---|---|
| `_cache_get`/`_l2_cache_get`가 `str` 아닌 값을 만난 적 없음 — JSON 직렬화가 기존 캐시 계약을 깨는지 | Do 단계에서 L2 Supabase 캐시 테이블 컬럼 타입 확인 필수(§2.3) |
| `search_nlrc()`가 court precedent와 달리 `display` 파라미터의 최대값·페이지네이션 한계를 안 검증함 | `max_results=3`(기존 `search_nlrc_with_details` 기본값과 동일) 유지, 확장은 별도 판단 |
| 삭제 대상(`nlrc_cases.py` 등)이 §4.1 전수 확인 이후 새로 생긴 소비자가 있을 수 있음 | Do 착수 직전 재확인(`grep` 1회, 비용 거의 0) |

---

## 9. 실행 순서 (Do)

1. ✅ `legal_api.py`에 `import json` 추가 + §2의 세 함수 추가
2. ✅ `pipeline.py` §3 교체(게이트·호출부)
3. ✅ `test_offline_units.py`에 §6 테스트 추가, `test_nlrc_bundle()` 제거
4. ✅ CI 전량 통과 확인(6종)
5. ✅ `nlrc_cases.py`·`refresh_nlrc_cases.py`·`data/nlrc_cases.json` 삭제(`git rm`)
6. ✅ `app/config.py`·`.env.example`·`CLAUDE.md`·`archive_precedents.py` 주석·
   `wage_calculator/pipeline-visualization.html`(§4.2에 없었으나 grep으로 발견,
   추가 반영)에서 `ODCLOUD_API_KEY`/`nlrc_cases` 서술 제거
7. ✅ 실 API 키로 라이브 스모크(부당해고·부당노동행위·차별시정 각 1질의, 실제
   프로덕션 데이터) — 마스킹된 사건번호 미노출 코드 검증 통과. 캐시 히트도
   확인(1차 0.388초 → 2차 0.0000초, 값 동일)
8. ⬜ 커밋 + PR — 사용자 확인 대기

---

## 10. Plan 대비 변경

| 항목 | Plan | Design | 사유 |
|---|---|---|---|
| 함수 위치 | 명시 안 됨 | `legal_api.py`(신규 모듈 아님) | §0 |
| `nlrc_cases.py` 처리 | 암시적 "교체" | **명시적 삭제** + 전수 소비자 확인 | §4.1 |
| 반환 타입 | 언급 없음 | `str \| None`(meta_list 없음) | §0 — 소비처가 텍스트 블록만 원함 |
| L1/L2 캐시 값 타입 | 언급 없음 | JSON 직렬화 필요(다중 필드) — L2 스키마 확인이 리스크로 승격 | §2.3, §8 |
| `archive_precedents.py` 영향 | 언급 없음 | **무영향 확인**, 단 주석 자기완결화 | §4.2 |
