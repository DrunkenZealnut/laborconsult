# effective-law-and-graph-precedents — Design (rev2)

> Plan: `docs/01-plan/features/effective-law-and-graph-precedents.plan.md` · 작성 2026-10-04
> **rev2 (2026-10-04)**: design-validator 지적 20건을 전부 반영했다. 반영 위치는 §11에 표로 정리했다.
> 실측은 전부 2026-10-04 법제처 Open API(등록 IP)에서 했고, 수치와 근거는 §1에 둔다.

## 0. 설계 결정

| # | 결정 | 근거 | Plan 대비 |
|---|---|---|---|
| D1 | 본문 조회를 **`target=eflaw&LM=`(efYd 없음)** 으로 바꾼다. **`target=law` 폴백은 금지한다.** 폴백하면 결함이 다시 들어온다 | efYd를 생략하면 법제처가 현행 시행판을 돌려준다. 6개 법령 전 조문이 `efYd=<현행판>`과 차이 0이었고, 호출도 1회 그대로다(§1.1) | Plan P0-1의 판본 선택 모듈·판본 목록 캐시·`target=law` 폴백을 모두 뺀다. 목록 호출이 없으니 캐시도 필요 없다. "조용하지 않게"라는 요구는 D12가 대신 맡는다 |
| D2 | **조문 캐시(`v4:` 키)만** 만료를 `min(+24h, 다음 KST 자정)`으로 맞춘다. KST 00~03시에 받은 응답은 1시간으로 줄인다 | 판본은 날짜 경계에서만 바뀐다. 기존 24h TTL은 새 판본 시행 뒤 최대 하루 동안 옛 판본을 냈다. 판례·헌재·NLRC 캐시는 판본과 무관하므로 그대로 둔다 | Plan의 "판본 날짜를 캐시 키에" 대신 쓴다 |
| D3 | 기준일 판본은 **전체 판본 목록에서 `max(시행일자 ≤ KST 오늘)`** 로 정의한다. 오프라인 도구에서만 쓴다 | `nw=3`('현행' 표지)은 법제처의 판정이다. 법제처 반영이 늦으면 목록과 본문이 같이 늦어 지연을 잡지 못한다 | Plan P0-1을 오프라인으로 한정한다 |
| D4 | `check_law_freshness`는 **본문을 조문 단위로 대조하고 fail-closed**로 판정한다. 비교에는 프로덕션 포맷 함수를 그대로 쓴다 | `target=law`는 헤더가 현행판과 같고 본문만 시행 예정분이었다. 헤더 대조로는 원리적으로 못 잡는다(08-21 이후 ✅). 감시 도구가 실패를 삼키면 감시 자체가 조용히 죽는다 | 강화 |
| D5 | 답변 경로의 **판례 번호 참조**에 사건번호 정확일치 게이트를 단다(헌재 포함). 정규화 함수는 중립 모듈 `app/core/case_numbers.py`가 단일 출처다 | `fetch_relevant_articles`는 fuzzy 검색의 첫 결과를 그대로 채택한다. 수집 스크립트에는 이 게이트가 있다 | 신규 |
| D6 | 그래프 판례는 **법제처 원문 기록 `data/graph_precedents.json`(커밋)** 에서만 만든다. 큐레이션 명세는 `build_graph.GRAPH_PRECEDENT_SPECS`로 남긴다 | 8건 중 정확한 것은 2건이었다(§1.3). 명세 키를 리터럴로 두면 아카이브의 코드 인용 스캔·교차검증(T27 H4)이 계속 동작한다 | P0-5·P0-6 구체화. 출처는 법제처 일련번호 하나로 좁힌다(코퍼스 벡터 ID 대안 제외 — CI가 커밋된 원문으로 대조해야 하기 때문) |
| D7 | 확인되지 않는 판례는 **삭제**한다 | 오인용보다 공백이 낫다. 코퍼스 검색 경로는 남아 있다 | 동일 |
| D8 | 규칙 블록의 판례 근거는 **별도 필드 `prec_anchors`** 로 두고 `graph_precedents.json`에서 해석한다 | 조문 앵커(`anchors`, `output_공식법령/`, gitignore)와 분리해야 K6 두 테스트가 깨지지 않는다. 판례 앵커는 **CI에서 실검증**된다 | 신규 |
| D9 | 규칙 블록 상한 2 → 3 | 2차 재평가 3·7·18번은 실업급여 + 피보험자격 확인, 17번은 실업급여 + 해고예고가 동시에 필요했다 | P1 |
| D10 | **코드가 만든 사실도 인용 화이트리스트에 넣는다** — 규칙 블록(판례 앵커는 primary hit)과 계산기 결과. 규칙 블록 생성을 화이트리스트 구성 앞으로 옮긴다 | 화이트리스트는 다섯 소스(상담·RAG·법령API·NLRC·그래프)로만 만들어진다(`pipeline.py:2136`). 블록이 제시한 판례나 계산기 법적 근거(`weekly_holiday.py:107` "2022다291153")를 LLM이 인용하면 **환각으로 판정돼 지워질 수 있다** — 지금도 있는 사각이다 | 신규(검증에서 발견) |
| D11 | 조문 조회와 게이트는 **`legal_api.fetch_law_root()` 하나**로 모은다(캐시·서킷 없음). 4곳이 이것을 쓴다 | 지금은 조회와 게이트가 네 벌이다. build_graph에는 `replace(" ", "")` 비교가 남아 있고, fetch_official_rules는 LM 요청값을 정규화하지 않는다. `_fetch_by_lm`은 클로저라 재사용할 수도 없다 | 신규 |
| D12 | 법령 조회의 미매칭·실패·게이트 거부를 **`conv_metadata["law_api"]`** 에 기록한다(있을 때만) | 폴백을 없앤 대신 "조용하지 않게"를 지킨다. 지금은 합계 로그(`legal_api.py:980`)만 남는다 | Plan P0-1의 `version_unverified`를 대체한다 |
| D13 | 공식 원문 헤더에 `effective_date`를 **추가하지 않는다**. 업로더와 지문(fingerprint)도 바꾸지 않는다 | `date`가 이미 `기본정보/시행일자`다(`fetch_official_rules.py:164-168`). 적재된 14건의 본문이 eflaw와 동일하므로 승인 근거 sha256이 유지된다 | Plan P0-3("sha256을 판본에 묶는다")을 뒤집는다 |
| D14 | 코드 인용이 바뀌면 **판례 아카이브 스냅샷을 다시 만든다**(`archive_precedents.py build → verify`) | 아카이브가 `app/`·`build_graph.py`의 사건번호 리터럴을 스캔한다(`archive_precedents.py:444-524`). 바꾸고 재빌드하지 않으면 로컬 verify V8이 실패한다 | 신규 |

**Plan 대비 명시적 제외**: P0-5의 참조조문 근거 `articles` 연결. 커밋된 그래프에 조문 노드가 0개라(`--skip-api` 빌드) 연결할 대상이 없다. 조문 노드를 만드는 사이클에서 다시 다룬다.

## 1. 실측 근거

### 1.1 법제처 본문 조회 — target별 결과 (근로기준법, 2026-10-04)

| 요청 | 루트 | 헤더 시행일자 / 공포번호 | 조문단위 | 제109조② |
|---|---|---|---|---|
| `target=law&LM=` (현재 코드) | 법령 | 20261002 / 21857 | 146 | **삭제 <2026.4.7>** (10-08 시행분) |
| `target=eflaw&LM=` (efYd 없음) | 법령 | 20261002 / 21857 | 145 | 존속 |
| `target=eflaw&LM=&efYd=20261002` | 법령 | 20261002 / 21857 | 145 | 존속 |
| `target=eflaw&MST=290781&efYd=20261002` | 법령 | 동일 | 145 | 존속 |
| `target=eflaw&efYd=20261004` (판본일 아님) | **Law** (빈 루트) | — | 0 | — |
| `target=eflaw&LM=없는법` | **Law** | — | 0 | — |
| `OC=잘못된값` | **Response** | — | — | — |

- `target=law`는 **헤더와 본문이 서로 다른 판본**이다. 109조의 `조문시행일자` 태그까지 20261002로 적혀 있어, 시행 예정분이 섞였다는 신호가 응답 어디에도 없다.
- eflaw의 루트·`기본정보` 필드·오류 응답 형태는 law와 같다. **기존 게이트 4종(빈 Law 루트=미매칭, Response=자격 오류, 반환 법령명 대조, 폐지 거부)이 그대로 적용된다.** 응답 시간도 0.30~0.38초로 같다.
- 판본 목록(`lawSearch target=eflaw`)에 대해 확인한 것:
  - `sort=efdes`는 시행일자 내림차순이고, 근로기준법은 totalCnt 148이다.
  - `nw=3`은 현행판만, `nw=2`는 시행 예정판만 돌려준다.
  - `법령일련번호`(MST)는 **같은 공포본의 여러 시행일 판본이 공유한다**(285279 = 10-08·12-08·2027-01-01). 그래서 판본을 식별하려면 efYd가 반드시 필요하다.

### 1.2 영향 범위 — `target=law` 본문과 현행 시행판의 조문 단위 차이

| 법령 | 현행판 | 시행 예정 판본 | 차이 조문 |
|---|---|---|---|
| 근로기준법 | 20261002 | 6 | **18** (13·54·60·61·101~109 …) |
| 고용보험법 | 20260918 | 3 | **6** (10·18·45·77의3·77의8·113의2) |
| 산업안전보건법 | 20260801 | 3 | 2 |
| 최저임금법·국민건강보험법·남녀고용평등법 | — | 1~4 | 0 |

- 공식 원문 저장본 19건을 eflaw로 다시 받아 대조했다. 18건은 동일하고, 다른 것은 `lsa_act_109`(로컬 전용, 미적재) 하나다. **Pinecone에 적재된 14건은 전부 동일**하다.

### 1.3 그래프 판례표 8건 — 법제처 정확일치 조회

| 사건번호 | 표의 요약 | 법제처 원문 | 처리 |
|---|---|---|---|
| 2023다302838 | 통상임금 고정성 폐지 (year **2023**) | 임금, **2024.12.19 전원합의체**. 참조판례에 "2012다89399 전원합의체 판결(공2014상, 236)**(변경)**" | 유지 · 연도 정정 · 변경 관계 |
| 2012다89399 | 통상임금 전원합의체 | 퇴직금, 2013.12.18 전원합의체. 판시사항 [1] 통상임금 판단 기준 | 유지 + 일부 법리 변경 표시 |
| 2013다25194 | 퇴직금 평균임금 기준 | **근로계약 취소의 소급효**(이력서 허위기재) | 요약 교체 · 개념 `근로계약` |
| 2018다200709 | 연차 사용촉진 적법 요건 | **불리하게 변경된 취업규칙 vs 유리한 근로계약 우선** | 요약 교체 · 개념 `근로계약` |
| 2019다293449 | 주휴수당 산정 기준 | **동산인도** — 법인격 부인의 역적용 | **삭제** |
| 2010다111757 · 2017다261387 · 2020나2016258 | — | 정확일치 없음 / `_미발견.csv` | **삭제** |
| (신규) 2022다291153 | — | 임금, **2025.08.14**. 판결요지 [4] 주 5일 미만 주휴시간 산정 | 추가 · 개념 `주휴수당` |

- 2022다291153의 아카이브 crawl 메타는 선고일이 2025.12.21로 되어 있다(게시일로 보인다). 원문 기록을 단일 출처로 삼는다.

### 1.4 P1 근거 조문 (eflaw 현행판)

| 사실 | 근거 |
|---|---|
| 피보험자격 확인청구는 "언제든지" 가능 | 고용보험법 제17조① |
| 확인 업무는 근로복지공단에 위탁 | 같은 법 시행령 제145조② "…권한을 근로복지공단에 위탁한다" · 2의2 "법 제17조…에 따른 피보험자격의 확인" |
| 수급자격 인정 여부는 직업안정기관(고용센터)이 결정 | 같은 법 제43조② |
| 이직확인서는 요청서를 받은 날부터 10일 이내 발급 | 같은 법 시행규칙 제82조의2② |
| 주 5일 미만·소정근로시간만 정한 경우 주휴시간 = 1주 소정근로시간 ÷ 5 | 대법원 2025.8.14. 선고 2022다291153 판결요지 [4] |
| 단시간근로자 근로조건은 통상근로자 근로시간 비례 | 근로기준법 제18조① |
| 온라인 수급자격 교육 14일 유효 | **법령·행정규칙에서 찾지 못했다**(시행령·시행규칙 전문, admrul 검색 4종) → 고정 블록에 넣지 않는다 |

### 1.5 인용 화이트리스트의 사각 (검증에서 발견, 코드 확인)

- 화이트리스트(`pipeline.py:2136`)는 `consultation_hits, precedent_meta, legal_articles_text, nlrc_text, graph_context` 다섯 가지로만 만든다.
- 규칙 블록(`:2187`)과 계산기 결과(`calc_result`)는 `parts`에만 들어간다.
- 계산기는 법적 근거로 "대법원 2025.8.14. 선고 2022다291153 판결"을 넣는다(`weekly_holiday.py:107`). 이 번호는 그래프·RAG가 우연히 같은 판례를 가져오지 않는 한 **환각 판정 대상**이다.

## 2. 변경 파일

```
app/core/legal_api.py          fetch_law_root() 신설(4곳 공용) · eflaw · 조문 캐시 v4 + 자정 만료
                               · 판례 참조 정확일치 · 조회 통계(stats=) · "항상 현행판" 주석 정정
app/core/case_numbers.py       (신규) normalize_case_no · detail_matches — 단일 출처
fetch_court_precedents.py      case_numbers에서 import + re-export (이름 유지)
fetch_official_rules.py        fetch_law_root 사용 · --doc 재수집(lsa_act_109 + 신규 3조문)
build_graph.py                 fetch_law_root 사용 · MAJOR_PRECEDENTS → GRAPH_PRECEDENT_SPECS
                               · --refresh-precedents [--verify] · 게이트 G1~G5 · 주석 정정
data/graph_precedents.json     (신규·커밋) 판례 원문 기록 5건
data/graph_data.json           재빌드(--skip-api)
app/core/graph.py              판례 줄 렌더링(선고일·판결유형·변경 표시, 요약 200자)
app/core/pipeline.py           규칙 블록 선계산 · 화이트리스트 system/graph hit · law_api 메타
app/core/rule_facts.py         insured_status · unemployment 줄 · 해고예고 감지 · 주휴 줄
                               · prec_anchors · MAX_BLOCKS 3 · 순서 · 주석 정정
app/templates/prompts.py       ANSWER_ACCURACY_RULES 날짜 조언에 기한 확인 구절
check_law_freshness.py         기준판 정의(D3) · 본문 대조 fail-closed · 시행 예정 목록 · dotenv → main()
archive_precedents.py          교차검증 대상 MAJOR_PRECEDENTS → GRAPH_PRECEDENT_SPECS
data/precedent_archive/records/*  스냅샷 재빌드(D14)
test_effective_law.py          (신규·CI) E1~E17
test_precedent_ingest.py       T27 H4 → GRAPH_PRECEDENT_SPECS
test_kin_accuracy.py           K4 이름 · K6(조문 앵커만) · K13 v3→v4 · prec_anchors 검사
test_offline_units.py          캐시 세대 v3 → v4
.github/workflows/tests.yml    test_effective_law.py 등록
CLAUDE.md                      699(MST/LM 전제) · 703(2단계 처방 → D1) · 705(v4, 만료 실제값)
                               · 706(본문 대조) · 그래프 판례 규칙 · 화이트리스트 규칙
```

## 3. 본문 조회 eflaw 전환 (D1·D2·D3·D4·D11)

### 3.1 `legal_api.fetch_law_root` (공용)

```python
def fetch_law_root(lm: str, api_key: str, *, ef_yd: str | None = None,
                   timeout: float = LAW_SERVICE_TIMEOUT) -> ET.Element | None:
    """법령 본문 XML 루트. 캐시·서킷 없음(수집·점검 도구도 공용).
    - 요청 LM은 _resolve_law_name으로 정규화한다(가운뎃점 이형).
    - target=eflaw. ef_yd가 없으면 법제처 현행판이고, 있으면 그 판본이다(판본 시행일만 유효).
    - 빈 <Law> → None(미매칭). <Response> → RuntimeError(자격 오류).
    - 반환 법령명 compact 불일치 → None. 제개정구분 '폐지' → None."""
```

- `fetch_article`의 클로저 `_fetch_by_lm`은 이 함수를 감싸는 얇은 호출로 바꾼다. 서킷·캐시·폴백 로직은 그대로 둔다.
- `_resolve_official_name`(검색)은 `target=eflaw&nw=3&display=10`으로 바꾼다. eflaw 목록은 판본마다 같은 법령을 반복하므로 `display=5`로는 목표 법령이 밀려날 수 있다. `nw=3`이면 법령당 1행이다.
- **캐시**:
  - 조문 키를 `v3:` → `v4:`로 바꾼다(v3에는 시행 예정 본문이 있다). 구 키는 읽지 않으며, 롤백해도 안전하다.
  - `_cache_set(key, text, expires_at=None)`·`_l2_cache_set(…, expires_at=None)` — 시그니처를 하위 호환으로 둔다. 기본값은 기존 TTL이다.
  - 조문 경로만 `_article_expiry(now)`를 넘긴다. 값은 `min(now+LAW_CACHE_TTL, 다음 KST 00:00)`이고, KST 00~03시에 받은 응답이면 `min(…, now+1h)`다.
  - L1 저장 형식은 `(expires_at, text)`로 통일한다. 테스트는 `.clear()`와 2인자 `_cache_set`만 쓴다.
  - 판례·헌재·NLRC 캐시는 바꾸지 않는다.
- eflaw 자체가 장애일 때: 기존과 같이 서킷 → None이다. `target=law` 폴백은 금지한다(D1). 실패는 D12로 기록한다.

### 3.2 `fetch_official_rules`

- `fetch_article_xml`이 `fetch_law_root`를 쓴다. 반환 법령명 비교도 공용 게이트로 통일된다.
- 헤더는 바꾸지 않는다(D13 — `date` = 시행일자). 업로더와 지문도 그대로다.
- 이 사이클의 수집은 `--doc lsa_act_109`(재수집)와 신규 `ei_act_17`·`ei_enf_145`·`ei_rule_82_2`다. 실행 전 `--dry-run`으로 본문 차이를 출력한다.
- **업로더는 이번 사이클에서 돌리지 않는다.** 다음 업로드 때 위 4건 + `lsa_enf_7`(C14) = **5건**이 laborlaw-v2에 같이 올라간다. 공식 원문이 늘어나는 것이라 의도된 변화이고, 기존 관례대로 BM25 재빌드가 뒤따른다.

### 3.3 `build_graph._fetch_articles_from_api`

- `fetch_law_root`를 쓴다. 커밋된 그래프는 조문 노드가 0개라 실효는 없다. 그래도 복제된 게이트(`replace(" ", "")`)를 없앤다.

### 3.4 `check_law_freshness` (D3·D4)

1. **기준판**: `lawSearch target=eflaw&query=<법령>&sort=efdes&display=100`에서, compact 법령명이 일치하는 항목 중 `max(시행일자 ≤ KST 오늘)`을 고른다.
2. **본문 대조**: 프로덕션 경로 `fetch_law_root(lm)`(efYd 없음)와 `fetch_law_root(lm, ef_yd=기준판)`의 조문을 **`legal_api._format_full_article`로 각각 포맷**해 조문 키 단위로 비교한다. 프로덕션 포맷 경로까지 함께 검증하기 위해서다.
3. **fail-closed**:
   - 한쪽에만 있는 조문도 차이로 센다.
   - 목록 미일치, 빈 루트, 미매칭, 예외는 모두 exit 1이다.
   - 차이가 0일 때만 통과다.
4. **지연 경고**: 프로덕션 응답 헤더의 `시행일자` ≠ 기준판이면 "법제처 반영 지연"으로 경고한다. 처음 17종을 실측할 때 단계 시행 법령(소득세법·조특법)에서 오탐이 나면 공포일자+공포번호를 함께 본다.
5. **시행 예정 목록**(`nw=2`)을 법령별로 출력한다.
6. `load_dotenv`를 모듈 최상단에서 `main()` 안으로 옮긴다. 테스트가 import할 때 환경변수가 덮어써지지 않게 하기 위해서다.

**실행 시점**: 등록 IP에서만 동작하므로 Actions로 돌릴 수 없다. 수동 실행 항목으로 둔다.
- 배포 전(`check_schema.py`와 같은 급)
- ⑤가 출력한 **시행 예정일 당일 오전**

CLAUDE.md에 이 두 시점을 적는다.

### 3.5 규칙 블록 앵커 — 다음 판본 경고

- `check_law_freshness --anchors`: 각 **조문** 앵커 문서의 법령에 시행 예정판이 있으면, `ef_yd=<가장 가까운 예정일>` 본문에서도 앵커를 대조한다. 실패하면 "YYYY-MM-DD부터 거짓"이라고 경고한다(실패 코드는 아님).
- 판례 앵커(`prec_anchors`)는 판본 개념이 없으므로 대상이 아니다.

## 4. 판례 참조 정확일치 (D5·D12)

- **`app/core/case_numbers.py`(신규, 표준 라이브러리만)**: `normalize_case_no`·`detail_matches`를 `fetch_court_precedents`에서 옮긴다.
  - `fetch_court_precedents`는 `from app.core.case_numbers import normalize_case_no, detail_matches`로 같은 이름을 노출한다. T1~T3·T12와 `archive_precedents.py:45`는 그대로 동작한다.
  - 동일성 테스트(`fetch.normalize_case_no is case_numbers.normalize_case_no`)로 사본 재발을 막는다.
  - legal_api는 `fetch_court_precedents`를 import하지 않는다. 그 모듈은 import 시 `load_dotenv(override=True)`를 실행한다.
- `search_precedent`·`search_detc` 결과에 `case_no`(`<사건번호>`)를 추가한다. 기존 호출부는 쓰지 않는 키라 하위 호환이다.
- `fetch_relevant_articles._fetch_one`의 판례·헌재 분기:
  - `max_results=20`(1페이지)에서 `detail_matches(r["case_no"], 요청)`이 참인 첫 항목만 채택한다. 없으면 None이다.
  - 헤더는 `[{사건명} {사건번호}]`다. 지금은 사건명만 있어서, 판례 본문에 자기 번호가 없으면 화이트리스트에 오르지 않는다.
- **통계(D12)**: `fetch_relevant_articles(relevant_laws, api_key, *, stats=None)`. `stats`에 `{requested, ok, miss, error, prec_rejected}`를 채운다.
  - pipeline은 `miss + error + prec_rejected > 0`일 때만 `conv_metadata["law_api"] = stats`를 기록한다.
  - 게이트 거부는 `logger.info("판례 정확일치 실패: 요청 %s → 후보 %s")`로 남긴다.

## 5. 그래프 판례 재구축 (D6·D7)

### 5.1 원문 기록 `data/graph_precedents.json`

```json
{
  "2023다302838": {
    "case_no": "2023다302838", "court": "대법원", "date": "2024.12.19",
    "judgment_type": "전원합의체 판결", "case_name": "임금", "serial_id": 600539,
    "source_url": "https://www.law.go.kr/DRF/lawService.do?OC=&target=prec&ID=600539&type=HTML",
    "issue": "<판시사항>", "summary": "<판결요지>", "ref_cases": "<참조판례>",
    "fetched_at": "2026-10-04"
  }
}
```

- `build_graph.py --refresh-precedents`(LAW_API_KEY 필요)로 받는다.
  - `fetch_court_precedents`는 함수 안에서 import한다(dotenv 부작용을 스크립트 실행 경로로 한정하기 위해서다).
  - 조회 순서: `search_case`(정확일치 + 페이지 순회) → `fetch_detail` → `normalize_record` → `detail_matches` 재확인(수집 스크립트 :518과 같다).
- `--refresh-precedents --verify`는 원격을 다시 받아 커밋본과 비교하고, 손으로 고친 흔적이나 원문 변경을 찾는다. 수동 점검 항목이다.
- 전문(`full_text`)은 저장하지 않는다. 5건 합계는 약 20KB이고, 법원 판결문은 저작권법 제7조 비보호다.

### 5.2 큐레이션 명세 — `build_graph.GRAPH_PRECEDENT_SPECS`

```python
GRAPH_PRECEDENT_SPECS = {          # 키는 리터럴 — 아카이브 코드 인용 스캔이 읽는다
    "2023다302838": {"concepts": ["통상임금"], "supersedes": ["2012다89399"]},
    "2012다89399":  {"concepts": ["통상임금"]},
    "2022다291153": {"concepts": ["주휴수당"]},
    "2018다200709": {"concepts": ["근로계약"]},
    "2013다25194":  {"concepts": ["근로계약"]},
}
```

- `MAJOR_PRECEDENTS`는 삭제한다. 대신 `archive_precedents.py:512-522`의 교차검증과 `test_precedent_ingest.py:1946-1954`(T27 H4)를 `GRAPH_PRECEDENT_SPECS`로 바꾼다.
- `except ImportError` 범위는 넓히지 않는다. 넓히면 교차검증이 조용히 꺼진다.

### 5.3 빌드 게이트 (하나라도 실패하면 빌드 중단)

| # | 규칙 |
|---|---|
| G1 | 명세의 모든 사건이 기록에 있고, `detail_matches(기록.case_no, 키)`가 참이다(병합 사건 허용) |
| G2 | 노드 `summary`는 판시사항 **항목 하나를 그대로** 쓴다(`[n]` 접두 제거, 공백 정규화). 대상은 연결 개념의 키워드(개념명·aliases)를 포함하는 첫 항목이다 |
| G3 | 각 `concepts`의 키워드가 판시사항 또는 판결요지에 있다 |
| G4 | `supersedes`: `ref_cases`에서 해당 사건번호부터 다음 `선고`(또는 끝)까지의 구간에 `(변경)`이 있다. 번호와 표지를 묶어서 본다 — 참조판례에는 여러 건이 들어 있기 때문이다 |
| G5 | `source_url` 호스트가 `law.go.kr`이고 `serial_id`가 있다 |

- 노드 속성은 `case_number, court, date, judgment_type, summary, superseded_by`다. 손입력하던 `year`는 없앤다(읽는 곳도 없다).
- 재빌드는 `python3 build_graph.py --skip-api`로 한다. E16이 `graph_data.json`의 판례 노드가 기록과 명세로 재현되는지 대조한다(재빌드 누락 탐지).

### 5.4 렌더링 (`graph.build_graph_context`)

```
[관련 판례 (그래프 탐색)]
- 대법원 2023다302838 (2024.12.19 선고, 전원합의체 판결): <판시사항 항목 ≤200자>
- 대법원 2012다89399 (2013.12.18 선고, 전원합의체 판결): <…> — 일부 법리는 대법원 2023다302838 판결로 변경됨
```

- 요약 상한을 100자에서 200자로 올린다.

## 6. 인용 화이트리스트 확장 (D10)

- `_citation_source_hits(consultation_hits, precedent_meta, legal_articles_text, nlrc_text, graph_context, *, extra_hits=None, system_texts=None)` — 키워드 전용 인자를 덧붙인다. 기존 5-위치인자 호출(`test_offline_units.py:417`, `len==3`)은 그대로 통과한다.
- **extra_hits**(primary, `case_no` 보유):
  - 그래프 판례 중 **최종 `graph_context` 문자열에 실제로 나타난 번호만**(2000자 절단 이후) 넣는다. `{"title": "대법원 …", "case_no", "chunk_text": summary, "source_type": "precedent"}` 형식이다.
  - 감지된 규칙 블록의 `prec_anchors` 판례도 넣는다(chunk_text = 기록의 앵커 판시 구절).
- **system_texts**(텍스트 블록): 감지된 규칙 블록 전문과 `calc_result`다.
  - 계산기 법적 근거는 손으로 쓴 것이지만 `meta` 카드로 사용자에게 이미 그대로 표시된다. 답변 본문에서 그것을 지우면 카드와 본문이 어긋난다. 이 번호들은 아카이브 인벤토리(`cited_code`)가 추적한다.
- 순서를 바꾼다: `build_rule_facts(query, analysis)`를 화이트리스트 구성(`:2136`) **앞**에서 한 번 계산해 보관하고, `parts`에 붙이는 위치는 지금과 같게 둔다.
- `graph_results`는 try 밖에서 `[]`로 초기화한다.

## 7. P1 규칙 블록

| 블록 | 변경 | 앵커 |
|---|---|---|
| `insured_status` (신규) | 감지: 미가입·미신고·3.3%·확인청구·피보험자격·"가입 안". 문구: 실제 근로자였으면 미신고 기간도 **언제든지** 피보험자격 확인청구를 할 수 있다. 확인 업무는 **근로복지공단**에 위탁돼 있고, 수급자격 인정은 **고용센터(직업안정기관)** 가 결정한다 | `ei_act_17` "언제든지 고용노동부장관에게 피보험자격의 취득 또는 상실에 관한 확인을 청구할 수 있다" · `ei_enf_145` "권한을 근로복지공단에 위탁한다" · "법 제17조" · "피보험자격의 확인" · `ei_act_43` "수급자격의 인정 여부를 결정" |
| `unemployment` | 줄 추가: 이직확인서는 근로자가 발급요청서를 내면 사업주가 **10일 이내** 발급한다 | `ei_rule_82_2` "제출받은 날부터 10일 이내에" |
| `dismissal_notice` | 감지 = 기존 OR (`해고` AND 단기 근속 단서 `\d+\s*(일\|주\|개월)` · 수습 · 입사) | 변경 없음 |
| `weekly_holiday` | 줄 추가: 주 5일 미만이고 소정근로시간만 정했다면 1주 소정근로시간 ÷ 5(대법원 2025. 8. 14. 선고 2022다291153). 같은 업무 통상근로자가 있으면 그 근로시간 비례(제18조①)가 출발점이다 | `prec_anchors`: `2022다291153` "1주간 소정근로시간 수를 5일로 나누는 방법으로 산정하는 것이 타당하다" · `anchors`: `lsa_act_18` "같은 종류의 업무에 종사하는 통상 근로자의 근로시간을 기준으로 산정한 비율" |
| (전역) | `MAX_BLOCKS` 2→3. 순서: unemployment → insured_status → harassment_retaliation → dismissal_notice → weekly_holiday → probation_wage | `rule_facts.py:26` 주석, K4 테스트 이름 갱신 |

- **감지 정밀도 확인(Do 단계)**: 기존 60건 + 지식iN 20건 fixture 질문에 감지기를 돌려 블록별 발동 목록을 표로 남긴다. 무관 발동이 보이면 단서를 좁힌다.
- **온라인 교육 14일**: 공식 근거가 없어(§1.4) 고정 블록에 넣지 않는다. 대신 `ANSWER_ACCURACY_RULES`의 날짜 조언 줄에 "교육 이수·서류 제출의 **유효기간·처리기한**은 고용센터·고용24 안내로 확인하도록 함께 쓴다"를 붙인다. 숫자는 적지 않는다.

## 8. 테스트 (`test_effective_law.py`, 오프라인·CI)

| ID | 검사 |
|---|---|
| E1 | 4개 파일(legal_api·fetch_official_rules·build_graph·check_law_freshness)에 `target\s*[:=]\s*["']law["']`·`target=law\b`가 **코드 줄**에 없다(주석·docstring 제외). 4곳을 1단계에서 함께 바꾸므로 처음부터 등록한다 |
| E2 | `_article_expiry` — 23:59 KST → 00:00 만료, 01:30 KST → +1h, 일반 시각 → `min(+TTL, 자정)`. UTC 서버 기준으로도 맞다 |
| E3 | 조문 캐시 `v4:` 저장, `v3:` 불독. `test_offline_units.py:243`·`test_kin_accuracy.py` K13 갱신 |
| E4 | `fetch_law_root` 모의: 빈 Law → None, Response → RuntimeError, 법령명 불일치 → None, 폐지 → None. 요청 LM의 U+00B7 정규화 |
| E5 | 판례·헌재 정확일치: fuzzy 첫 결과 거부, 2번째 정확일치 채택, 병합 사건 일치, 없으면 None + `prec_rejected` 증가. 헤더에 사건번호 |
| E6 | `_diff_articles` — 차이 조문, **한쪽에만 있는 조문**, 빈 루트·예외 시 fail(exit 1) |
| E7 | 그래프 게이트 G1~G5를 커밋된 `graph_precedents.json`으로 실검증(skip 없음) |
| E8 | 회귀: 삭제 4건이 그래프·명세에 없다. 2023다302838 `date`=2024.12.19 |
| E9 | 렌더링: 선고일·판결유형·변경 표시, 요약 200자 이하 |
| E10 | 그래프 판례 개별 hit: 렌더된 번호만 포함되고, `classify_paths`가 primary로 판정 |
| E11 | 규칙 블록: insured_status 감지, MAX_BLOCKS 3, 해고 단서 감지(+ 비발동 사례), 순서, `prec_anchors`가 기록에서 해석됨(CI 실검증) |
| E12 | `fetch_official_rules.fetch_article_xml`이 `fetch_law_root`를 경유한다(구조 검사) |
| E13 | **화이트리스트**: 그래프 없이 규칙 블록만 있는 컨텍스트에서 2022다291153 인용이 valid. `calc_result`의 판례도 valid |
| E14 | `fetch_court_precedents.normalize_case_no is case_numbers.normalize_case_no` (detail_matches 동일) |
| E15 | `fetch_relevant_articles(stats=)` 집계와 pipeline `law_api` 메타 기록 조건(실패 0이면 미기록) |
| E16 | 재빌드 동등성: 명세 + 기록 → 판례 노드 집합·속성이 `graph_data.json`과 같다 |
| E17 | 판례·NLRC 캐시는 자정 상한을 받지 않는다(기존 TTL) |

**기존 테스트 갱신**:
- T27 H4 → `GRAPH_PRECEDENT_SPECS`
- K4 이름 → `test_k4_at_most_max_blocks`
- K6 두 테스트는 `anchors`(조문)만 보도록 하고, `prec_anchors`는 E11이 담당한다
- K13 `v3:` → `v4:`
- `test_offline_units.py` E(캐시 세대)

`tests.yml`에 `python3 test_effective_law.py`를 등록한다.

## 9. 구현 순서

1. `fetch_law_root` 신설과 **4개 파일 target 전환을 함께** 한다. 조문 캐시 v4·자정 만료, E1~E4·E12·E17, K13·test_offline_units 갱신도 이 단계다
2. `check_law_freshness` 재작성(D3·D4) + E6 → **17종 + 실입력 실행, 차이 0 확인**. 헤더 경고 오탐 여부를 기록한다
3. `case_numbers` 이동 + 정확일치 게이트 + stats + E5·E14·E15
4. `fetch_official_rules --doc`(dry-run 대조 → 재수집 1 + 신규 3)
5. `graph_precedents.json` 수집 → 명세·게이트·렌더링 → `--skip-api` 재빌드. T27 H4·아카이브 교차검증 갱신, E7~E9·E16
6. pipeline 화이트리스트(규칙 블록 선계산·extra_hits·system_texts) + law_api 메타 + E10·E13
7. 규칙 블록 P1 + prompts + 감지 정밀도 표 + E11·K4·K6 → K6(로컬)와 prec_anchors(CI) 앵커 전량 확인
8. `archive_precedents.py build` → `verify` → records 커밋(D14)
9. CLAUDE.md(699·703·705·706 + 신규 규칙)와 코드 주석 정정
10. 지식iN 20건 Live 재측정(2019다293449·2013다25194 오인용 0, 기존 지표 비회귀)

## 10. 위험과 롤백

| 위험 | 탐지 | 대응·롤백 |
|---|---|---|
| eflaw 기본값이 어떤 법령에서 현행이 아님 | `check_law_freshness` 본문 대조(fail-closed) | `fetch_law_root`의 target 한 줄과 캐시 세대 |
| 법제처 자정 반영 지연 | freshness 지연 경고(수동: 배포 전·시행 예정일 오전) | 00~03시 응답은 1시간 TTL이라 지연 피해가 최대 1시간이다 |
| eflaw 장애 | 서킷 + `law_api` 메타 | 폴백 없음(D1) — 조문 없이 답변한다(기존과 같음) |
| 정확일치 게이트로 판례 조회 None 증가 | `law_api.prec_rejected` | 게이트 유지(오인용보다 안전) |
| 그래프 판례 축소(8→5)로 일부 주제 판례 연결 소실 | 노드 수 | 검증된 판례만 명세에 추가하는 경로가 생겼다 |
| 규칙 블록 3개로 컨텍스트 증가 | 블록 문자 수(최대 약 1,800자) | `MAX_BLOCKS` 상수 |
| 계산기의 손입력 판례 인용이 화이트리스트로 승격 | 아카이브 인벤토리 `cited_code`(실인용 코드 공백 10건) | 카드 표시와 일치시키는 쪽이 낫다. 인용 실재 검증은 범위 밖(§12) |

## 11. 검증 반영 이력 (design-validator, 2026-10-04)

| V# | 심각도 | 지적 | 반영 |
|---|---|---|---|
| 1 | High | `MAJOR_PRECEDENTS` 삭제 시 T27 H4·archive 교차검증 붕괴 | §5.2 `GRAPH_PRECEDENT_SPECS` 유지·교체, §2 두 파일 추가 |
| 2 | High | `prec:` 앵커가 K6 두 테스트를 깨뜨림 | D8 별도 필드 `prec_anchors`, K6은 조문 전용, E11 |
| 3 | High | 규칙 블록·계산기 판례가 화이트리스트 밖 → 환각 판정 | D10·§6, 규칙 블록 선계산, E13 |
| 4 | Medium | K13의 `v3:` 단언 누락 | E3·§2 |
| 5 | Medium | `detail_matches` 사본 생성 위험 | D5 중립 모듈 `case_numbers.py` + re-export + 동일성 E14 |
| 6 | Medium | 기준판 정의 불일치(nw=3 vs 기준일), 헤더 대조 오탐 | D3, §3.4①④(실측 후 공포번호 병행 결정) |
| 7 | Medium | `_diff_articles` 실패 조건 미정의 | §3.4③ fail-closed, E6 |
| 8 | Medium | 지연 탐지가 수동뿐 | §3.4 실행 시점 명시 + D2 00~03시 1h TTL |
| 9 | Medium | 아카이브 코드 인용 스냅샷 노후 → V8 실패 | D14, 9단계 중 8 |
| 10 | Medium | 조회·게이트 네 벌 | D11 `fetch_law_root`, E12 |
| 11 | Medium | Plan 폴백·관측 요구 무단 삭제 | D1 폴백 금지 명시 + D12 `law_api` 메타 |
| 12 | Low | `effective_date` 중복·업로드 범위 불명 | D13 필드 미추가, §3.2 업로드 범위 명시 |
| 13 | Low | 변경 목록 누락(prompts·CLAUDE.md 다수 줄·주석) | §2 전량 추가 |
| 14 | Low | 자정 만료가 판례·NLRC 캐시까지 적용 | D2 조문 키 한정, 시그니처 하위호환, E17 |
| 15 | Low | eflaw 검색 `display=5` 밀림 | §3.1 `nw=3&display=10` |
| 16 | Low | refresh의 `detail_matches`·G4 결속·수동 편집·재빌드 누락 | §5.1 재확인·`--verify`, G1·G4 수정, E16 |
| 17 | Low | `_citation_source_hits` 시그니처·렌더 집합 일치 | §6 키워드 전용 인자, 렌더된 번호만 |
| 18 | Low | E1 순서·패턴·dotenv 부작용 | E1 정규식·1단계 동시 전환, §3.4⑥ dotenv 이동, §5.1 지연 import |
| 19 | Low | "해고" 과감지·순서·앵커가 핵심 주장 미검증 | §7 단서 조건·순서 변경·앵커 보강·감지 정밀도 표 |
| 20 | Low | 헌재 테스트·헤더 번호·거부 로그 부재 | §4 헤더·통계·로그, E5 헌재 |

## 12. 범위 밖

- 2023다302838·2022다291153의 laborlaw-v2 코퍼스 적재(BM25 재빌드 동반)
- 코드에 손으로 쓴 판례 인용의 실재 검증 — 아카이브 인벤토리 기준 실인용 코드 공백은 10건이다
- 행정해석 번호 검증, 시행 예정 조문의 사용자 안내

## 13. 구현 중 변경·실측 (Do, 2026-10-04)

| # | 내용 | 이유·근거 |
|---|---|---|
| C1 | `check_law_freshness` 17종 실측: **전부 ✅**, 헤더 시행일자 = 기준판(소득세법·조특법 포함) | eflaw 경로에서는 구 주석의 '단계시행 오탐'이 재현되지 않는다. 그래서 공포번호 병행 대조는 넣지 않았다(§3.4④) |
| C2 | **음성 대조**: 프로덕션 조회만 `target=law`로 되돌리면 근로기준법 18·고용보험법 6 조문 차이로 **실패**한다 | 검증 도구가 실제로 결함을 잡는지 확인한 것이다(같은 수치가 §1.2 실측과 일치) |
| C3 | 커밋된 `graph_data.json`의 statute 노드 12개에 MST 시절 `mst` 속성이 남아 있었고, 재빌드로 사라졌다 | law-version-drift 이후 한 번도 재빌드되지 않았다. 읽는 곳은 없다(grep 0). E16이 이후 재빌드 누락을 잡는다 |
| C4 | `build_graph` 조문 파일 캐시 이름에 `.eflaw` 접미사 | target=law 시절 파일이 남아 있으면 7일 동안 재사용된다 — 캐시 세대와 같은 원리 |
| C5 | `holding_items`가 `[n]`과 ` / ` 두 구분 형식을 받는다 | 2023다302838 판시사항은 ` / `로 구분된다(실측) |
| C6 | `fetch_official_rules --dry-run`이 저장본 대조(동일/다름/신규)를 출력한다(`stored_body`) | §3.2의 "재수집 전 본문 차이 출력". 실측: lsa_act_109만 다름, 나머지 동일 |
| C7 | 통계의 `miss`는 미매칭과 조회 실패를 함께 센다 | `fetch_article`이 내부에서 예외를 삼키고 None을 돌려준다. `error`는 스레드 단계의 예외만 센다. 구분이 필요해지면 `fetch_article` 반환값을 바꿔야 한다 |
| C8 | L2 적중 → L1 복사에도 `_article_expiry()`를 쓴다 | L2 행의 만료를 읽지 않으므로 KST 00~03시 구간에서 최대 1시간 넘길 수 있다. 수용한다 |
| C9 | 기존 테스트 갱신: drift guard(`"LM"` 요구를 legal_api로 옮기고 build_graph는 `fetch_law_root` 요구), K5(위치가 아니라 `rules_enabled` 부재로), K4 이름, K13 v4, `test_legal_rule_updates` mock 경로(`legal_api._http`) | D10·D11로 생긴 구조 변화 |
| C10 | 감지 정밀도(fixture 80문항, 분석 없이 키워드만): unemployment 17 · insured_status 1(kin-03) · harassment 4 · dismissal 5(dismissal-01·04·06, law-05, kin-17) · weekly 9 · probation 2. 3블록 초과 0건 | 무관 발동이 없다. kin-15(퇴직금 질문에서 LLM이 확인청구를 자발적으로 언급)는 insured_status가 감지하지 못한다 — 키워드로 잡을 수 없는 유형이라 남긴다 |
| C11 | 판례 아카이브 `build → verify` 전체 통과(V0~V8). code_citations·inventory 갱신 | D14 |
| C12 | **판정기(`harassment_assessor`)가 불리한 처우 벌칙을 "제109조 제2항"으로 손으로 적고 있었다**(constants 2곳, assessor 1곳) → 제1항으로 정정 | 3차 Live에서 9번 답변이 "판정기 결과에는 '제109조 제2항'으로 표시되어 있으나 현행 기준상 제1항"이라고 썼다. 판정 결과가 답변 컨텍스트에 그대로 들어가 1·2·3차 재평가 모두에서 같은 오조문이 나온 출처다. 회귀는 E18 |
| C13 | 판정기의 5인 미만 경고 정정 — "괴롭힘 금지는 규모와 관계없이 모든 사업장 적용·5인 미만도 과태료 대상"을 **"상시 4명 이하 사업장에는 제76조의2·제76조의3과 그 벌칙·과태료가 적용되지 않는다"** 로 바꿨다. 미조치 과태료·불리한 처우 벌칙 경고도 4명 이하에서는 내지 않는다 | 법제처 eflaw 현행 시행령 별표 1(제7조, 4명 이하 적용 규정)에 **제6장의2가 없다**(실측). 2차 재평가 9번 지적과 같은 내용이다 |
| C14 | `harassment_retaliation` 블록에 4명 이하 미적용 문장을 넣고 앵커 `lsa_enf_7`(시행령 제7조)를 달았다. 부재 주장은 `ANNEX_ABSENCE_CLAIMS` + `check_law_freshness --anchors`의 별표 부재 점검이 맡는다(현행판 위반=실패, 다음 판본 위반=경고) | "별표에 없다"는 구절 앵커로 검증할 수 없는 부재 주장이다. 법이 4명 이하 사업장에 괴롭힘 규정을 적용하도록 바뀌면 이 점검이 잡는다. E19 |
| C15 | 평가 매처 부정어에 `종전`·`변경되었`·`바뀌었` 추가 | 3차 Live kin-19의 정답("다음 주 근무 예정을 요건으로 보던 **종전** 해석은 **변경되었습니다**")이 오검출됐다. 10-02 원답변 12/12 검출은 유지 |
| C16 | **지식iN 20건 3차 Live**(이 브랜치): 자동 통과 **17/20**(기준선 12 → 15·14 → 17). **2019다293449·2010다111757 오인용 0**. 남은 것: 9번(판정기 문구 — C12 후 단건 재측정 통과), 11번(2018두63235 — 범위 밖, monitor), 19번(매처 오검출 — C15) | Plan 완료 조건 4 |
| C17 | `check_law_freshness`의 시행 예정 목록은 `nw=2` 호출이 아니라 efdes 판본 목록에서 `시행일자 > 오늘`로 뽑는다 | 결과는 같다. 법제처 '현행/시행예정' 표지를 믿지 않는다는 D3과도 맞는다(gap X1) |
| C18 | G4 구간은 "다음 `선고`까지"가 아니라 "다음 사건번호 전까지"로 자른다. 노드에 `supersedes` 속성도 둔다(`superseded_by`의 역방향) | 법제처 참조판례 형식에서 결과가 같고, 정규식이 더 단순하다(gap X2) |
| C19 | 해고예고 감지의 단기 근속 단서: `\d+(주\|개월\|달)` + (만에·정도·동안·근무·일하·다니·째·밖에·만), `\d+일` + (만에·동안·근무·일하·밖에·째), 수습·며칠·이틀·사흘·입사 직후 | 날짜("7월 27일")의 '일'이 단서로 잡히지 않게 하기 위해서다(E11 비발동 사례) |
| C20 | Plan 완료 조건 4: 3차 Live에서 **2013다25194도 0**이다(기준선·1차는 15·16번, 2차는 15번에 있었다) | gap P4 |

### 13.1 gap 분석 후속 (Check, 2026-10-04 — Match Rate 98.2%)

| gap # | 심각도 | 조치 |
|---|---|---|
| 위험 1 | Medium | 4명 이하 판정 결과의 **법적 근거·대응 절차**도 바꿨다(`SMALL_WORKPLACE_LEGAL`·`SMALL_WORKPLACE_STEPS`). E18이 결과 **전체**(`format_assessment`)를 본다 |
| 위험 2 | Medium | 109② 문장을 시제 중립으로 바꿨다("2026. 10. 8. 시행 시 삭제"). 10-08 이후에도 참이고 손볼 필요가 없다 |
| 위험 3 | Medium | 법률상담 경로(`process_consultation`)에도 `law_api_stats`를 넘기고 pipeline에서 합산한다(E20) |
| 위험 4 | Medium(배포) | 커밋 시 untracked 파일 0건 확인(`app/core/case_numbers.py`·`data/graph_precedents.json`·테스트·문서) |
| 위험 5 | Low-Med | `_is_small_workplace` — "5인 미만"·"4명 이하" 등 띄어쓰기 변형 흡수(E18) |
| 위험 7 | Low | insured_status의 `3.3` 부분문자열 → 원천징수 표현 정규식(`3.3%`·`3.3프로`) (E20) |
| 위험 8 | Low | `_fetch_one`의 지역변수 `results` → `candidates` |
| 위험 9 | Low | `_anchor_warnings`·`_annex_checks` 예외 처리 + 판본 본문이 없을 때 "거짓" 대신 "확인 불가" |
| 위험 10 | Low | `_article_key`가 `조문가지번호="0"`을 가지 없음으로 처리(E20) |
| 위험 11 | Low | `PRECEDENT_RECORDS_PATH`를 `Path(__file__)` 기준으로 바꾸고 미사용 import를 정리 |
| 위험 6·12 | Low | 수용한다. enforce 금지(CLAUDE.md)로 계산기 판례의 secondhand 분류는 영향이 없다. 렌더 판정은 설계 정의대로다 |
| P1 | Low | 수용한다. `ei_enf_145`의 두 앵커는 항(②) 결속을 보장하지 않는다 — 구절 앵커의 원리적 한계이고, 구간 결속 앵커는 범위 밖이다 |
| P2·P3 | Low | E3에 `v3:` 불독 단언, E17에 `fetch_nlrc_detail` 추가 |
| 문서 갭 | — | CLAUDE.md(:135 조문 수, 부정어 창, 판정기 서술, law_api 범위), 설계 §3.2(5건), §13 C17~C20 반영 |
