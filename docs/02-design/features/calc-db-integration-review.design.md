# 계산기 모듈·데이터베이스 호출 과정 점검 Design (calc-db-integration-review)

> **Summary**: Plan에서 확정한 28건(P1 5·P2 10·P3 10·TEST 3)을 4개 웨이브로 구현하기 위한 코드 수준 설계. 계산기 파라미터 배선 복구, 복수 계산유형 라우팅, BM25 코퍼스 배포, sources 이벤트 실데이터화, 인용 화이트리스트 확장, 타임아웃/컨텍스트 예산 도입을 다룬다.
>
> **Project**: laborconsult
> **Author**: DrunkenZealnut
> **Date**: 2026-07-14
> **Status**: Draft
> **Planning Doc**: [calc-db-integration-review.plan.md](../../01-plan/features/calc-db-integration-review.plan.md)

---

## 1. 설계 개요

### 1.1 설계 목표

1. **배선 무결성**: analyzer가 추출한 파라미터는 반드시 소비처(계산기 필드)까지 도달하거나, 도달 못 하는 이유가 로그에 남는다.
2. **출처 투명성**: 검색된 근거(판례·법령·판정사례)가 LLM 컨텍스트·인용 검증·UI 세 곳에 **동일한 원천**으로 공급된다.
3. **폴백 보존**: 모든 신규 경로는 실패 시 기존 동작으로 수렴한다(CLAUDE.md graceful degradation 규약).
4. **오프라인 검증 가능성**: 핵심 배선·정규식·결합 로직은 API 키 없이 테스트 가능해야 한다.

### 1.2 설계 원칙

- 웨이브별 독립 PR — 각 PR은 골든(`test_wage_golden.py`)·CLI 116케이스 무회귀를 조건으로 머지.
- 기존 이벤트/스키마 하위호환 — SSE 이벤트 타입 추가 없음(기존 `sources`를 실데이터화), params dict 기존 키 유지.
- 아키텍처 고정 — Vercel serverless + Supabase + Pinecone. 신규 인프라 없음.
- 값이 있을 때만 세팅 — 신규 배선 필드는 존재 시에만 `WageInput`에 대입해 자동감지(`_auto_detect_targets`) 부작용을 값 존재 케이스로 한정(R-3).

### 1.3 전후 데이터 흐름 (계산기 경로)

```
[현재]  analyze_intent ─ extracted_info(23필드) ─▶ _analysis_to_extract_params(17필드로 축소)
        ─▶ _run_calculator(WageInput에 9필드만 세팅) ─▶ calculate(targets=유형[0]만)

[개선]  analyze_intent ─ extracted_info(23필드) ─▶ _analysis_to_extract_params(23필드 유지
        + calculation_types_kr 리스트) ─▶ _run_calculator(수습·체불·육아휴직·해고예고·
        고정수당·직종 배선) ─▶ calculate(targets=전체 유형 union)
        실패 시: 오류 문자열 주입 대신 None + logger.exception
```

### 1.4 전후 데이터 흐름 (검색/출처 경로)

```
[현재]  search_hybrid(BM25 코퍼스 없음→Dense-only) → rerank → precedent_meta
        ├▶ LLM 컨텍스트 + 인용목록(precedent_meta만)
        ├▶ 인용 검증 화이트리스트(consultation+precedent_meta만) — 법령API/NLRC/graph 사각
        └▶ sources 이벤트: 항상 []

[개선]  search_hybrid(BM25 gz 코퍼스 로드→RRF) → rerank → precedent_meta
        ├▶ LLM 컨텍스트(소스별 예산 캡) + 인용목록(전 소스)
        ├▶ 인용 검증 화이트리스트(전 소스: +법령API/NLRC/graph)
        └▶ sources 이벤트: 정규화 hits ≤5건 → 프론트 답변 하단 출처 표시
```

---

## 2. 확정된 설계 결정 (Plan §8.2 대응)

| 결정 | 확정안 | 근거 |
|------|--------|------|
| BM25 코퍼스 배포 | **gzip 커밋** (`data/bm25_corpus.json.gz`, 실측 ≤10MB 전제). 초과 시 부록 A(Supabase Storage 로더)로 전환 | 콜드스타트 추가 네트워크 0회, 빌드 단계 불필요. 과거 75MB 위생 문제는 raw json — gz는 한국어 JSON 기준 1/4~1/5 수준 |
| sources 스키마 | `{"type":"sources","hits":[{title,section,source_type,score,origin}]}` 상한 5건, `chunk_text` 미포함 | 본문 전송은 대역폭·불필요(제목/출처만 UI 표시). origin ∈ rag/consultation/legal_api |
| 컨텍스트 예산 | 소스별 캡: precedent 8,000자·consultation 8,000·법조문 5,000·NLRC 4,000·첨부 6,000 (graph는 기존 2,000 유지). 계산결과·인용목록·누락안내·연락처·질문은 비절삭 | 절삭 불가 항목(정확성 직결)과 절삭 가능 항목(검색 자료) 분리. 총량은 로그로 관측 후 조정 |
| 타임아웃 | `analyze_intent` 12s, `_extract_params` 10s, 스트리밍 connect 5s/read 30s (mid-stream 실패 시 부분 응답 유지 규약 불변). `vercel.json` builds config에 `maxDuration: 300` — preview 검증 필수(R-4) | 보조 호출(3~5s)과 위계 유지. read 30s는 무토큰 정지 감지용 |
| 변환기 수렴 | **웹 인라인 변환기 정식화**: `_run_calculator`가 유일 변환기. `from_analysis()`/`conversion.py::_provided_info_to_input()` 삭제(호출 0 확인). `_parse_contract_months`/`_infer_occupation_code`/`_guess_start_date` 유틸은 존치 | 한국어 라벨 스키마의 소비 경로(analyze_qna 배치→계산)가 이미 사문화. 이중 유지보수 제거 |

**구현 범위에서 제외 (제품 결정 대기, Plan §4 말미)**: CALC-8(수치 카드 UI), CALC-10(pending 복원 vs 폐기 — 단 스테일 문서 주석은 Wave D 포함), DB-9(breaker 공유 스토어).

---

## 3. Wave A — 계산 정확성 (CALC-1·2·3 + TEST-1)

### 3.1 CALC-1: 파라미터 배선 복구

**(a) `pipeline.py::_analysis_to_extract_params`** — params dict에 6개 키 추가 (`:818-837` 블록):

```python
"notice_days_given":     info.get("notice_days_given"),
"parental_leave_months": info.get("parental_leave_months"),
"arrear_amount":         info.get("arrear_amount"),
"arrear_due_date":       info.get("arrear_due_date"),
"fixed_allowances":      info.get("fixed_allowances"),
"occupation_code":       info.get("occupation_code"),
```

(`is_probation`/`contract_months`는 기존 전달됨 — `_run_calculator` 세팅만 누락 상태)

**(b) `pipeline.py::_run_calculator`** — `WageInput` 세팅 블록 추가 (`:604-635` 영역, platform_worker 처리 뒤):

```python
# 수습·계약기간·직종 (최저임금 감액 판정: minimum_wage.py:73-76 소비)
if params.get("is_probation"):
    inp.is_probation = True
if params.get("contract_months") is not None:
    inp.contract_months = int(params["contract_months"])
if params.get("occupation_code"):
    inp.occupation_code = str(params["occupation_code"]).strip()
# 해고예고 / 육아휴직 / 임금체불
if params.get("notice_days_given") is not None:
    inp.notice_days_given = int(params["notice_days_given"])
if params.get("parental_leave_months"):
    inp.parental_leave_months = int(params["parental_leave_months"])
if params.get("arrear_amount"):
    inp.arrear_amount = float(params["arrear_amount"])
if params.get("arrear_due_date"):
    inp.arrear_due_date = str(params["arrear_due_date"])
# 고정수당 — facade가 dict 항목을 그대로 지원 (facade/__init__.py:136)
if params.get("fixed_allowances"):
    inp.fixed_allowances = [
        a for a in params["fixed_allowances"]
        if isinstance(a, dict) and a.get("amount")
    ]
```

**(c) `_WAGELESS_TARGETS`에 `wage_arrears` 추가** (`pipeline.py:509`):

설계 중 확인된 2차 결함 — 체불 지연이자는 임금 정보가 불필요한 독립 계산(`calc_wage_arrears`, `facade/__init__.py:103-113`)인데, 임금 없는 체불 질문은 `has_wage=False` → wageless 필터(`:642-648`)가 `wage_arrears`를 제외해 배선을 복구해도 실행이 막힌다.

```python
_WAGELESS_TARGETS = {"working_hours", "weekly_hours_check", "wage_arrears"}
```

0원 통상임금 노이즈는 기존 방어(`:667-670` formulas 필터 + `result.py` 최저임금 라인 숨김)가 그대로 적용된다.

### 3.2 CALC-2: 복수 계산유형 라우팅

**(a) `_analysis_to_extract_params`**: `REVERSE_CALC_MAP` 변환을 전체 유형에 적용, 신규 키로 전달. 기존 `calculation_type`(첫 라벨)은 캐시 키·카테고리 분류(`:1499`) 하위호환을 위해 유지:

```python
labels = [REVERSE_CALC_MAP[ct] for ct in analysis.calculation_types
          if ct in REVERSE_CALC_MAP]
params["calculation_type"] = labels[0] if labels else "임금계산"
params["calculation_types_kr"] = labels          # 신규: 전체 라벨 리스트
```

**(b) `_resolve_targets` 시그니처 확장** (`pipeline.py:512`): 첫 인자를 `calc_types: list[str]`로. 1단계 strict 매칭을 라벨별로 수행해 **순서 보존 union**:

```python
merged: list[str] = []
for label in calc_types:
    for t in (resolve_calc_type_strict(label) or []):
        if t not in merged:
            merged.append(t)
if merged:
    return merged
# 이하 2~4단계(키워드 추론/최저임금 검증/미실행)는 기존과 동일
```

**(c) `_run_calculator`**: `calc_type = params.get("calculation_type","")` 대신:

```python
calc_types = params.get("calculation_types_kr") or (
    [params["calculation_type"]] if params.get("calculation_type") else [])
targets = _resolve_targets(calc_types, query, has_wage)
```

**효과**: `_compute_missing_info`(전체 유형 기준)와 실행 대상이 구조적으로 일치. `severance+annual_leave` → `["severance","minimum_wage","annual_leave"]`.

### 3.3 CALC-3: 오류 문자열 주입 차단

`pipeline.py:672-673`:

```python
except Exception:
    logger.exception("계산기 실행 실패 — 계산 없이 상담 경로로 진행 (targets=%s)", targets)
    return None
```

- `calc_result=None`이면 meta 이벤트(`:1023-1027`)·프롬프트 주입(`:1267-1268`) 모두 자연 차단(기존 truthy 가드).
- `calculator_batch_test.py`의 "계산기 오류" 문자열은 자체 except에서 생성 — 영향 없음(grep 확인). `chatbot.py:314,401`은 개발용 CLI라 유지(Wave D에서 라우팅만 정렬).

### 3.4 TEST-1: 오프라인 배선 테스트 — 신규 `test_pipeline_wiring.py`

- 스타일: `test_wage_golden.py`와 동일(stdlib assert, pytest 불요, **API 키·네트워크 불요** — `AppConfig` 생성 없이 순수 함수만 호출).
- analysis 스텁: `types.SimpleNamespace(requires_calculation=True, calculation_types=[...], extracted_info={...})` — `_analysis_to_extract_params`는 이 두 필드만 소비.

| # | 케이스 | 입력 요지 | 단언 |
|---|--------|-----------|------|
| W1 | 체불 배선 | `wage_arrears`, arrear_amount=10_000_000, arrear_due_date=6개월 전 | params에 arrear_* 존재 → calc_result에 "임금체불 지연이자" 섹션 |
| W2 | 체불+임금無 | W1에서 임금 필드 제거 | wageless 경로로도 실행됨(None 아님) |
| W3 | 육아휴직 배선 | `parental_leave`, months=12, monthly_wage=3_000_000 | "육아휴직" 섹션 존재 |
| W4 | 수습 감액 | `minimum_wage`, 시급, is_probation=True, contract_months=12 | 감액(90%) 반영 수치 |
| W5 | 수습+단순노무 | W4 + occupation_code="9" | 감액 미적용(단순노무 예외) |
| W6 | 복수 유형 | `["severance","annual_leave"]` + 월급/입사일 | 두 섹션 모두 존재 |
| W7 | 오류 차단 | calculate가 예외를 던지는 입력(monkeypatch) | `_run_calculator` 반환 None (오류 문자열 아님) |
| W8 | 고정수당 | fixed_allowances=[{name,amount,condition}] | 통상임금 반영 확인 |
| W9 | 기존 회귀 | 최저임금·주휴 기본 케이스 | 기존 결과 형식 불변 |

---

## 4. Wave B — 검색 인프라·출처 투명성 (DB-3 → DB-1 → DB-2)

### 4.1 DB-3: Pinecone 인덱스명 단일화

**단일 출처 상수** — `app/config.py` 모듈 레벨:

```python
# 인덱스명 단일 출처. 값 교체는 프로덕션 env 확인(R-1) 후 별도 커밋으로.
DEFAULT_PINECONE_INDEX = "semiconductor-lithography"
def resolve_index_name() -> str:
    return os.getenv("PINECONE_INDEX_NAME", DEFAULT_PINECONE_INDEX)
```

- 교체 대상(8곳): `app/config.py:55`, `build_bm25_corpus.py:30`, `pinecone_upload_contextual.py:47`, `pinecone_upload_legal.py:388`, `pinecone_upload_counsel.py:203`, `upload_new_precedents.py:335`, `test_precedent_search.py:13`, `chatbot.py:35` — 전부 `from app.config import resolve_index_name`으로 통일. **이 리팩터 자체는 값 불변**(업로드 스크립트 3곳은 기본값이 `laborconsult-bestqna`→공용 기본값으로 바뀌므로 커밋 메시지에 명시; 실행 시 env 설정이 전제).
- **값 확정 절차(R-1)**: ① Vercel 대시보드/`vercel env ls`에서 `PINECONE_INDEX_NAME` 실값 확인 ② 실값 있으면 `DEFAULT_PINECONE_INDEX`를 그 값으로 교체 ③ 미설정이면 Pinecone 콘솔에서 `laborlaw-v2/counsel/qa` 네임스페이스 보유 인덱스를 확인해 교체. 확인 전에는 기본값 유지(동작 불변).
- **관측성**: `config.from_env` 성공 시 `logger.info("Pinecone index=%s", index_name)` 추가. `rag.py::search_pinecone_multi`가 쿼리 존재+결과 0건이면 모듈 플래그로 **최초 1회** `logger.warning("RAG 0건 — 인덱스/네임스페이스 확인: %s", ...)`.

### 4.2 DB-1: BM25 코퍼스 배포 (gzip 커밋)

**(a) `build_bm25_corpus.py`**: 출력 gzip화 + 크기 리포트:

```python
out_path = Path("data/bm25_corpus.json.gz")
with gzip.open(out_path, "wt", encoding="utf-8") as f:
    json.dump(corpus, f, ensure_ascii=False, separators=(",", ":"))
print(f"BM25 corpus: {len(corpus)} docs, {out_path.stat().st_size/1e6:.1f}MB (gz)")
```

**(b) `app/core/bm25_search.py::load_bm25_corpus`**: 경로 후보 `[data/bm25_corpus.json.gz, data/bm25_corpus.json]` 순회, `.gz`는 `gzip.open(path, "rt", encoding="utf-8")`. 로드 시간 로그 기존 유지(콜드스타트 실측 → DB-10 후속 판단 근거).

**(c) `.gitignore`**: `data/bm25_corpus.json`(raw) ignore 추가 — `.gz`만 추적.

**(d) 운영 절차** (CLAUDE.md Commands에 추가): 코퍼스 업로드(`pinecone_upload*`) 후 `python3 build_bm25_corpus.py` 재실행 → `.gz` 커밋. 자동화(GitHub Actions weekly)는 후속 과제로 기록만.

**(e) 크기 게이트**: 실측 gz > 10MB이면 커밋 중단 → 부록 A(Supabase Storage) 전환. `.gitignore`에 `.gz`도 추가하고 로더에 Storage 다운로드 경로 활성화.

**검증**: 로컬 `uvicorn` 기동 → 질의 1회 → 로그 `BM25 loaded: N docs` + `Pinecone 다중검색` 병행 확인, `search_hybrid` 반환 hits에 RRF 결합 흔적(양쪽 search_type 혼재) 확인.

### 4.3 DB-2: sources 이벤트 실데이터화 + 프론트 표시

**(a) 백엔드** — `pipeline.py`에 정규화 헬퍼 신설, `:1215` 교체:

```python
def _build_sources_payload(precedent_meta, consultation_hits, max_items=5) -> list[dict]:
    out, seen = [], set()
    for origin, hits in (("consultation", consultation_hits or []),
                         ("rag", precedent_meta or [])):
        for h in hits:
            title = h.get("title") or h.get("case_name") or ""
            key = (title, h.get("section", ""))
            if not title or key in seen:
                continue
            seen.add(key)
            out.append({
                "title": title[:120],
                "section": h.get("section", "")[:80],
                "source_type": h.get("source_type", "precedent"),
                "score": round(float(h.get("rerank_score") or h.get("score") or 0), 3),
                "origin": origin,
            })
    return out[:max_items]
```

호출 위치는 현행 `:1215` 지점 유지(consultation 경로 완료 후) — `yield {"type": "sources", "hits": _build_sources_payload(precedent_meta, consultation_hits)}`. 법제처 API 폴백 판례는 `precedent_meta`에 이미 합류하므로 별도 처리 불요.

> 구현 시 확인: `consultation_hits`(`legal_consultation.py::process_consultation` 반환)의 필드가 `title/section/source_type/score` 규격인지 — 다르면 위 헬퍼에서 흡수(이미 `.get` 기반 방어).

**(b) 프론트** — `public/index.html::readSSE` `:1074` 분기 분리:

```js
} else if (event.type === 'sources') {
  pendingSources = event.hits || [];          // 스트림 시작 전 도착 → 보관
} else if (event.type === 'meta') {
  // handled in answer (현행 유지 — CALC-8 결정 대기)
}
```

답변 완료(`done`) 시 현재 assistant 말풍선 요소에 기존 `.sources` CSS(`:210-212`) 재활용:

```js
function appendSources(msgEl, hits) {
  if (!hits.length) return;
  const labels = {precedent:'판례', interpretation:'행정해석', regulation:'훈령·예규',
                  counsel:'노무사 상담', qa:'상담 Q&A'};
  const div = document.createElement('div');
  div.className = 'sources';
  div.textContent = '근거 자료: ' + hits.map(h =>
    `[${labels[h.source_type] || h.source_type}] ${h.title}`).join(' · ');
  msgEl.appendChild(div);
}
```

- `replace` 이벤트로 본문이 교체돼도 `.sources`는 말풍선 하단에 별도 노드로 append하므로 보존되도록 `replace` 처리부에서 본문 노드만 교체(구현 시 현행 replace 로직 확인).
- 개인정보: hits는 코퍼스 문서 제목·출처 메타만 포함(사용자 입력 미포함) — `_anonymize()` 불요. 단 `counsel/qa` 제목은 크롤링 공개 데이터임을 전제.

---

## 5. Wave C — 신뢰성·성능 (DB-4, CALC-4~7, DB-5~7)

### 5.1 DB-4: 인용 화이트리스트 사각지대 해소

공통 수집 헬퍼 신설(파이프라인 내):

```python
def _citation_source_hits(consultation_hits, precedent_meta,
                          legal_articles_text, nlrc_text, graph_context) -> list[dict]:
    hits = list(consultation_hits or [])
    for m in (precedent_meta or []):
        hits.append({"title": m.get("case_name", m.get("title", "")),
                     "chunk_text": m.get("chunk_text", "")})
    for label, text in (("법제처 법령 조문", legal_articles_text),
                        ("NLRC 판정사례", nlrc_text),
                        ("법령 지식그래프", graph_context)):
        if text:
            hits.append({"title": label, "chunk_text": text})
    return hits
```

- **적용 2곳(동일 원천 원칙)**: ① 인용 가능 목록 생성 `:1250-1262`의 `build_available_citations_text(...)` 입력 ② 검증 화이트리스트 `:1446-1454`. 조립 시점(`:1245`)에 `nlrc_text`(`:1176-1195`)·`graph_context`(`:1217-1229`)가 이미 확보되어 있어 순서 문제 없음.
- 텍스트 블록을 hits로 넣으면 `extract_precedents_from_hits`가 `chunk_text`에서 `_PREC_PATTERN` 정규식으로 번호만 추출 — **자유 편입이 아니라 소스에 실재하는 번호만** 화이트리스트에 오름(R-7 완화 구조 내장).
- 전후 비교: `test_legal_cases_e2e.py`의 환각/replace 카운터로 측정(§8).

### 5.2 CALC-4: calc_cache 교차오염 축소

- `session.py::get_cached_info(calc_types: list[str] | None = None)`: 지정 시 **해당 calc_type 키의 캐시만** 병합(교집합 없으면 빈 dict). 기본 None=전체(하위호환).
- `pipeline.py:989`: `cached = session.get_cached_info(analysis.calculation_types or None)`; `analysis.calculation_types`가 비면(비계산 질문) 프리필 자체를 스킵.
- 프리필 발생 시 `prefilled_keys` 수집 → `logger.info` + 컨텍스트에 안내 블록 추가(누락 안내 `:1300` 앞):

```
[이전 대화에서 재사용한 정보] 월급, 주당 근무일수
→ 새 사업장/조건 질문이라면 값이 다를 수 있음을 답변에서 짚어주세요.
```

- 프리필 → 누락 판정 순서는 현행 유지(후속질문에서 재질문 방지가 목적이므로 재사용 값은 '충족'으로 간주하는 게 맞음 — 오염 축소는 유형 스코프 제한으로 달성).

### 5.3 CALC-5: 만원/원 단위 가드

`pipeline.py`에 `_normalize_wage_units(params)` 신설, `_ensure_minimum_wage_flag` 직후 호출:

```python
_UNIT_FLOORS = {  # wage_type: (하한, 배율) — 하한 미만이면 만원 단위 누락으로 판단
    "월급": (100_000, 10_000), "포괄임금제": (100_000, 10_000),
    "연봉": (1_200_000, 10_000),
}
def _normalize_wage_units(params: dict) -> None:
    wt = params.get("wage_type", "")
    amt = params.get("wage_amount")
    rule = _UNIT_FLOORS.get(wt)
    if rule and amt and 10 <= amt < rule[0]:
        params["wage_amount"] = amt * rule[1]
        params["unit_corrected"] = True
        logger.warning("임금 단위 보정: %s %s → %s", wt, amt, params["wage_amount"])
```

- 시급·일급은 제외(정상 저액 존재, 시급은 최저임금 가드 `:565-571` 별도). 보정 발생 시 `analysis.missing_info`에 `"임금액 단위(만원으로 해석함) 확인"` append → 기존 안내 블록(`:1300-1309`)이 답변 말미에 자동 노출.
- `NUMERIC_RANGES` 하한은 변경하지 않음(wage_amount가 시급/일급과 공용이라 오탐 위험).

### 5.4 CALC-6: calculation_types enum 확장

**(a) `prompts.py` ANALYZE_TOOL enum**(현 15종)에 10종 추가:

```
"eitc", "average_wage", "industrial_accident", "shutdown_allowance",
"working_hours", "public_holiday", "ordinary_wage",
"retirement_tax", "retirement_pension", "business_size"
```

**(b) `pipeline.py` REVERSE_CALC_MAP** 추가 매핑 (모두 기존 `CALC_TYPE_MAP` 키로 연결):

| enum | 라벨 | CALC_TYPE_MAP |
|------|------|---------------|
| eitc | 근로장려금 | 기존 |
| average_wage | 평균임금 | 기존 |
| industrial_accident | 산재보상 | 기존 |
| shutdown_allowance | 휴업수당 | 기존 |
| working_hours | 근로시간산정 | 기존 |
| ordinary_wage | 통상임금 | 기존 |
| retirement_tax | 퇴직소득세 | 기존 |
| retirement_pension | 퇴직연금 | 기존 |
| business_size | 사업장규모 | 기존 |
| public_holiday | 유급공휴일 | **신규 키** `"유급공휴일": ["public_holiday"]` |

**(c) `ANALYZER_SYSTEM` 프롬프트**에 신규 유형 안내 2줄(근로장려금·산재·평균임금·휴업수당·소정근로시간 질문 시 해당 enum 사용).

**(d) `_REQUIRED_FIELDS` 보강**(CALC-13 연계 최소분): `average_wage`·`shutdown_allowance`·`public_holiday`·`working_hours` 항목 추가(각 필수 필드·한국어 설명) — 없으면 누락 판정 공백으로 안내 문구가 비게 됨.

### 5.5 CALC-7: 조용한 예외 삼킴 제거

- `pipeline.py:1006-1009`: `except Exception as e:` → `logger.exception("의도분석 실패 — 레거시 추출 경로로 폴백: %s", e)` (동작 불변, 로그만).
- `pipeline.py:400-401`(`_extract_params`): `except Exception: pass` → `logger.warning("파라미터 추출 실패(무시): %s", e)`.

### 5.6 DB-5: 컨텍스트 예산 + 첨부 이중 주입 제거

**(a) 절삭 유틸**:

```python
def _cap(text: str | None, limit: int) -> str | None:
    if text and len(text) > limit:
        return text[:limit] + "\n...(자료 일부 생략)"
    return text
```

조립부(`:1245-1284`)에서 적용: `precedent_text=_cap(...,8000)`, `consultation_context=_cap(...,8000)`, `legal_articles_text=_cap(...,5000)`, `nlrc_text=_cap(...,4000)`, `attachment_text=_cap(...,6000)`. 비절삭: `calc_result`·인용목록·지식모듈·누락안내·연락처·질문. `user_message` 총길이는 `logger.info("컨텍스트 %d자", len(user_message))`로 관측만(값 조정은 데이터 확보 후).

**(b) 첨부 이중 주입**: `:1283-1284`를 `vision_block` 없는 첨부의 추출 텍스트만 포함하도록 수정:

```python
non_vision_text = "\n\n".join(
    f"[첨부: {att.filename}]\n{att.extracted_text}"
    for att in (attachments or [])
    if att.extracted_text and not att.vision_block)
if non_vision_text:
    parts.append(f"첨부된 문서 내용:\n\n{_cap(non_vision_text, 6000)}")
```

`combined_query`(분석용, `:953-964`)는 현행 유지(의도분석에는 전체 텍스트 필요; 단 `_cap(..., 4000)` 적용). 구현 시 `ParsedAttachment`의 `vision_block`/`extracted_text` 동시 존재 케이스(이미지 OCR) 실태 확인.

### 5.7 DB-6: 임계경로 타임아웃 + maxDuration

- `analyzer.py:132`: `config.anthropic_client.with_options(timeout=12.0).messages.create(...)`
- `pipeline.py::_extract_params`(`:370` 영역): 동일 패턴 `timeout=10.0`
- `pipeline.py::_stream_claude`(`:142`):

```python
import httpx
_STREAM_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0)
with config.claude_client.with_options(timeout=_STREAM_TIMEOUT).messages.stream(...)
```

  read 30s = 토큰 간 무진행 감지. 첫 청크 전 실패 → `_stream_answer` 폴백 체인(OpenAI→Gemini), mid-stream 실패 → 부분 응답 유지(기존 규약, CLAUDE.md 명시 유지).
- `vercel.json`: `{"src": "api/index.py", "use": "@vercel/python", "config": {"maxDuration": 300}}` — **preview 배포로 검증 후 머지**(R-4: legacy builds에서 미지원/충돌 시 이 항목만 분리·보류 재기록).

### 5.8 DB-7: NLRC 판정사례 번들 로드

- `git mv odcloud_labor_cases.json data/nlrc_cases.json` (구조: 사례 dict 배열 — `구분/순번/위원회명/자료구분/작성일자/제목/조회수`, 검색 로직이 쓰는 키와 일치 확인됨).
- `nlrc_cases.py::_get_cases`: 캐시 미스 시 **번들 우선**:

```python
_BUNDLE_PATH = Path(__file__).resolve().parents[2] / "data" / "nlrc_cases.json"
# 캐시 유효 → 반환
# 번들 존재 → json.load → _cases_cache 세팅 후 반환 (네트워크 0회)
# 번들 없음/파싱 실패 → 기존 _fetch_all_cases(api_key) 폴백
```

- 갱신 스크립트 신규 `refresh_nlrc_cases.py`(루트): `_fetch_all_cases` 재사용해 `data/nlrc_cases.json` 재작성 → 수동 주기 실행·커밋(CLAUDE.md Commands 추가). 24h TTL은 번들 경로에서는 의미 없어짐 — 번들 로드 시 TTL 무시(프로세스 생존 동안 유지).
- `pipeline.py:1178`의 `config.odcloud_api_key` 게이트는 유지(키 없는 배포에서 동작 변화 없음 — 번들의 목적은 지연 제거).

---

## 6. Wave D — 정리·드리프트·안전망 (P3 + TEST-2/3)

| # | 항목 | 설계 요지 | 파일 |
|---|------|-----------|------|
| D1 | CALC-9 변환기 단일화 | `from_analysis()` 삭제, `conversion.py`는 `_parse_contract_months`/`_infer_occupation_code`/`_guess_start_date` 유틸만 남기고 `_provided_info_to_input` 삭제. `facade/__init__.py:231` 주석의 "from_analysis 명시 경로" 문구 수정. CLAUDE.md의 `from_analysis` 서술 제거 | `facade/__init__.py`, `facade/conversion.py`, `CLAUDE.md` |
| D2 | CALC-11 chatbot 정렬 | `chatbot.py:394` → `resolve_calc_type_strict` + None 시 "계산 유형 미확정 — 계산기 미실행" 출력(묵시적 minimum_wage 제거). CLI 오류 문자열 표시는 유지 | `chatbot.py` |
| D3 | CALC-12 5일 가정 표면화 | `:579-582`에서 가정 발생 시 `params["assumed_weekly_days"]=True` → `missing_info`에 "주 근무일수(5일로 가정함)" append | `pipeline.py` |
| D4 | CALC-13 검증 라벨 보존 | `_validate_numeric_params`가 제거한 라벨을 `AnalysisResult.validation_warnings`(신규 필드, 기본 `[]`)로 분리 반환 → pipeline에서 `missing_info = code_missing + validation_warnings`(중복 제거) | `analyzer.py`, `pipeline.py` |
| D5 | DB-8 BM25 멀티쿼리 | `search_hybrid`: 쿼리별 `search_bm25` (상위 3쿼리) → 쿼리 간 RRF 병합 → Dense와 최종 RRF. alpha 튜닝은 벤치마크 확보 후 별도(보류 기록) | `rag.py`, `bm25_search.py` |
| D6 | DB-10 코퍼스 로드 비용 | Wave B 배포 후 콜드스타트 로그 실측 → 2s 초과 시에만 사전 토크나이즈 코퍼스(tokens 필드 포함 gz) 후속 — 이번 구현 없음(관측 항목) | — |
| D7 | TEST-2 오프라인 단위 테스트 | 신규 `test_offline_units.py`: ① `citation_validator` extract/validate/available-text(환각·화이트리스트 픽스처) ② `reciprocal_rank_fusion` 순수 로직 ③ `_merge_search_queries` ④ `conflict_resolver.annotate_source_priority` ⑤ NLRC 번들 로더(픽스처 JSON) ⑥ `_normalize_wage_units` ⑦ `_build_sources_payload`. CI: `.github/workflows/tests.yml` — push/PR 시 `pip install -r requirements.txt` 후 `python3 test_wage_golden.py && python3 test_pipeline_wiring.py && python3 test_offline_units.py` | 신규 2파일 |
| D8 | TEST-3 기존 스크립트 정합 | `search_quality_test.py`·`test_precedent_search.py`: 인덱스/NS를 `app.config` 상수·`rag.py` NS 상수 import로 교체 + docstring에 "라이브 키 필요(수동 도구)" 명시. `benchmark_pipeline.py`: `CASE_DIR` 부재 시 안내 후 종료 + `test_sample/legal_cases/` 소형 픽스처 3건 커밋으로 스모크 가능화 | 각 파일 |
| D9 | 문서 정합 | CLAUDE.md: Hybrid Search 실태(gz 코퍼스·갱신 절차)·sources 이벤트 실데이터·from_analysis 제거 반영. `interactive-follow-up.analysis.md` 헤더에 "pending 흐름 미배선(제품 결정 대기)" 스테일 노트 | 문서 2건 |

---

## 7. 구현 순서 (Do 단계 체크리스트)

> 각 웨이브 완료 시: `python3 test_wage_golden.py` + `python3 wage_calculator_cli.py`(116케이스) + 신규 테스트 통과 → 독립 PR.

**Wave A** (선행조건 없음)
1. [ ] `_WAGELESS_TARGETS` + `wage_arrears` (3.1c)
2. [ ] `_analysis_to_extract_params` 6키 추가 (3.1a) + `calculation_types_kr` (3.2a)
3. [ ] `_run_calculator` WageInput 배선 (3.1b) + 복수 유형 resolve (3.2b,c)
4. [ ] 오류 문자열 → None + logger.exception (3.3)
5. [ ] `test_pipeline_wiring.py` W1~W9 (3.4)

**Wave B** (4.1 → 4.2 → 4.3 순서 권장; 4.2는 Pinecone 키 필요)
6. [ ] 인덱스명 상수화 8곳 — 값 불변 리팩터 (4.1)
7. [ ] **[사용자 확인]** 프로덕션 `PINECONE_INDEX_NAME` 실값 → `DEFAULT_PINECONE_INDEX` 확정 커밋
8. [ ] `build_bm25_corpus.py` gz 출력 + 로더 gz 지원 + `.gitignore` (4.2) → 실측 크기 게이트
9. [ ] 코퍼스 빌드 실행·커밋 + 로컬 RRF 동작 확인
10. [ ] `_build_sources_payload` + `:1215` 교체 (4.3a)
11. [ ] 프론트 sources 렌더 + replace 보존 확인 (4.3b)

**Wave C**
12. [ ] `_citation_source_hits` + 목록/검증 2곳 적용 (5.1)
13. [ ] `get_cached_info(calc_types)` 스코프 + 재사용 안내 블록 (5.2)
14. [ ] `_normalize_wage_units` (5.3)
15. [ ] enum 10종 + REVERSE/CALC_TYPE_MAP + `_REQUIRED_FIELDS` 보강 (5.4)
16. [ ] 예외 로깅 2곳 (5.5)
17. [ ] `_cap` 예산 + 첨부 이중 주입 제거 (5.6)
18. [ ] 타임아웃 3곳 (5.7) / [ ] `maxDuration` preview 검증 후 머지 (5.7, 실패 시 보류 기록)
19. [ ] NLRC 번들 이동·로더·갱신 스크립트 (5.8)

**Wave D**
20. [ ] D1~D5 코드 정리 / 21. [ ] D7 `test_offline_units.py` + CI / 22. [ ] D8 스크립트 정합 + 픽스처 / 23. [ ] D9 문서 정합

---

## 8. 테스트·검증 전략

| 구분 | 도구 | 실행 조건 | 커버 |
|------|------|-----------|------|
| 배선 단위(신규) | `test_pipeline_wiring.py` | 오프라인 | CALC-1/2/3, W1~W9 |
| 모듈 단위(신규) | `test_offline_units.py` | 오프라인 | 인용검증·RRF·쿼리병합·충돌주석·번들로더·단위가드·sources payload |
| 계산 회귀(기존) | `test_wage_golden.py`, `wage_calculator_cli.py`, `calculator_batch_test.py` | 오프라인 | 계산 엔진 무회귀 |
| E2E(기존, 수동) | `test_legal_cases_e2e.py` 10케이스 | 라이브 키 | 환각/replace 카운트 전후 비교(DB-4 효과), sources 이벤트 수신 확인(케이스별 `hits>0` 집계 추가) |
| 배포 검증 | Vercel preview | 배포 | maxDuration 적용, BM25 로드 로그, sources UI 수동 스모크 |
| CI(신규) | GitHub Actions | push/PR | 오프라인 3종 스위트 |

구현 시 확인 항목(설계에서 미확정): ① `consultation_hits` 필드 규격 ② `ParsedAttachment.vision_block`과 `extracted_text` 동시 존재 실태 ③ `requirements.txt`의 CI 설치 가능성(mecab 등 optional 의존은 코드가 이미 폴백 처리) ④ `@vercel/python` builds config의 `maxDuration` 지원 여부(preview로 판정).

---

## 9. 리스크 대응 매핑 (Plan §7)

| 리스크 | 본 설계의 대응 |
|--------|----------------|
| R-1 인덱스명 | 4.1 — 값 불변 상수화(선행) → 실값 확인 후 별도 커밋. 0건 경고 로그로 오배선 조기 감지 |
| R-2 코퍼스 크기 | 4.2e — gz 실측 10MB 게이트, 초과 시 부록 A 전환. raw json은 ignore |
| R-3 배선 회귀 | 1.2 원칙(값 존재 시만 세팅) + W9 회귀 케이스 + 골든/CLI 선실행 |
| R-4 maxDuration | 5.7 — preview 검증 게이트, 실패 시 항목 분리 보류 |
| R-5 프론트 회귀 | 4.3b — readSSE 분기 추가 최소 수정, replace 보존 명시 확인, 수동 스모크 |
| R-6 타임아웃 오절단 | 5.7 — read 30s(토큰 간), 폴백 체인 유지, 부분 응답 규약 불변 |
| R-7 화이트리스트 확장 | 5.1 — 정규식 실재 번호만 편입되는 구조 + e2e 환각 카운터 전후 비교 |

---

## 10. Definition of Done 매핑 (Plan §6.1)

| Plan DoD | 설계 근거 절 |
|----------|--------------|
| P1 5건 수정 + 회귀 테스트 | §3(CALC-1/2), §4(DB-1/2/3), 테스트 §3.4·§8 |
| P2 수정(CALC-3~7, DB-4~7) | §3.3, §5 |
| 오프라인 테스트 신설 | §3.4, §6 D7 |
| 기존 안전망 무회귀 | §7 웨이브별 게이트 |
| sources 로컬 확인 | §4.3 검증 + §8 E2E hits 집계 |
| 제품 결정 3건 상신 | §2 제외 목록 — Do 완료 보고 시 재상신 |
| Gap ≥ 90% | 본 설계 절 번호를 analyze 단계 대조 기준으로 사용 |

---

## 부록 A — BM25 코퍼스 Supabase Storage 로더 (크기 게이트 초과 시에만)

- 업로드: `build_bm25_corpus.py`가 gz를 Supabase Storage 버킷 `corpora/`에 업로드(서비스 키 필요).
- 로더: `load_bm25_corpus()` 후보 경로에 `/tmp/bm25_corpus.json.gz` 추가 — 부재 시 Storage에서 1회 다운로드(콜드스타트 +다운로드 시간, 실패 시 Dense-only 폴백 유지).
- 이 경로를 택하면 CLAUDE.md에 환경변수(`SUPABASE_URL/KEY`) 의존을 명시.

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-07-14 | 최초 작성 — Wave A~D 구현 수준 설계, Plan §8.2 결정 5건 확정, 2차 결함(wage_arrears wageless 누락) 반영 | DrunkenZealnut |
