# production-law-api-recovery — Design

> Plan: `docs/01-plan/features/production-law-api-recovery.plan.md`
> 결정(2026-10-06 사용자 확정, "모두 권고대로"):
> - P0-1은 **조문 캐시 예열(C)을 먼저** 하고, 고정 IP(A)는 비용을 확인한 뒤 결정한다.
> - 예열 대상은 기본안(현행성 점검 대상 + 주제·키워드 규칙이 쓰는 법령)이다.
> - 선행 사이클(claim-authority, PR #101)을 먼저 머지한다.
> 작성 2026-10-06 · 단계: Design

## 0. 설계 결정

| # | 결정 | 근거 |
|---|---|---|
| D1 | 등록 IP 머신(로컬 맥)이 핵심 법령 **전 조문**을 Supabase `law_article_cache`에 미리 채운다. 스크립트는 `warm_law_cache.py`이고, launchd가 매일 KST 00:10에 실행한다 | 프로덕션의 실시간 호출은 한 번도 성공하지 않았다(점검 시간대 캐시 저장 0건). 캐시 적중만 실렸다 |
| D2 | 예열 행의 만료는 **법령별 다음 시행 예정일 00:00 KST**로 한다. 그런 날이 없으면 +7일로 한다 | 맥이 꺼져 있어도 판본 경계까지는 유지되고, 경계에서는 끊겨 옛 판본을 내지 않는다(지금 자정 만료와 같은 안전성) |
| D3 | 캐시 키를 정식 법령명으로 정규화하고 세대를 `v5`로 올린다. 키 생성은 단일 함수 `article_cache_key()`가 맡고, 예열과 조회가 같이 쓴다 | 같은 조문인데 약칭·가운뎃점 이형이 다른 키가 되고 있었다(실측: `남녀고용평등법_19`와 정식명 키) |
| D4 | 항 단위 키가 캐시에 없으면, 실호출 전에 같은 조문의 전체 키를 먼저 찾는다 | "항이 없으면 조문 전체로 폴백"하는 기존 의미와 같다. 예열이 항 키를 빠뜨려도 조문은 실린다 |
| D5 | `LAW_API_LIVE`(기본 `on`)를 둔다. `off`면 법제처 실호출을 전부 건너뛰고 '차단'으로 센다. 프로덕션은 `off`로 둔다(C 방식인 동안) | 실패할 것이 확실한 호출이 요청마다 1~1.4초를 쓰고 서킷을 흔든다. 로컬은 같은 스위치로 프로덕션 조건을 재현한다 |
| D6 | **모든 법제처 호출**이 `<Response>` 루트를 인증·파라미터 오류로 올린다(`LawApiAuthError`). 공용 헬퍼 `_raise_if_error_root()`로 처리한다 | 판례·판정문 검색은 이 판정이 없어 인증 오류를 "결과 0건"으로 읽었고, 서킷에는 오히려 성공을 기록했다 |
| D7 | 조회 결과를 **성공(캐시/실호출)·미발견·오류·인증오류·차단**으로 나눠 집계한다. `fetch_article`은 선택 인자 `outcome`으로 상태를 돌려준다(반환형 불변) | 지금은 인증 실패가 `miss`로 집계돼 error 0으로 보였다 |
| D8 | 키워드 조문 규칙 `KEYWORD_LAWS`를 둔다. 질문에 고신뢰 키워드가 있으면 그 조문을 2-2에서 **가장 먼저** 싣는다. 순서는 키워드 조문 → 주제 기본 조문 → 의도분석 조문이고, 최대 5개다 | 의도분석이 주제를 잘못 고르거나(육아휴직 → 연차휴가) '조의2'를 빠뜨려도(제18조 → 제18조의2) 맞는 조문이 실린다. 분석 결과에 기대지 않는 결정적 경로다 |
| D9 | 의도분석의 주제 enum은 **바꾸지 않는다** | 주제를 늘리면 분류가 흔들리고 기존 fixture 기대값이 바뀐다. 키워드 규칙이 조문 선택을 맡으므로 enum 변경 없이 목표를 달성한다 |
| D10 | `TOPIC_SEARCH_CONFIG`에 '직장내성희롱'을 추가한다(남녀고용평등법 제12·14조). 질문이 성희롱이면 2-2를 **생략하지 않고**, 주제를 '직장내성희롱'으로 바꿔 돌린다 | claim-authority는 괴롭힘 조문이 실리는 것을 막으려고 2-2를 생략했다. 그러나 그러면 성희롱 조문도 함께 빠진다(외부 점검 4번) |
| D11 | 폴백 감시(`check_llm_fallback.py`)에 법령 조건 두 가지를 더한다. ① 예열 상태가 36시간 넘게 갱신되지 않음 ② 최근 실사용 5건의 조문 성공률이 50% 미만 | 장애가 6주 넘게 아무에게도 보이지 않았다. 감시도 fail-closed다 |
| D12 | 예열 상태는 같은 테이블에 특수 키 `meta:law_warm_status`로 기록한다(DDL 없음) | anon 읽기·쓰기가 이미 허용된 테이블이다. 새 테이블은 GRANT·RLS·check_schema 등록이 따라온다 |

## 1. 실측 근거

Plan §1을 참조한다. 추가 실측(2026-10-06):

**프로덕션 캐시 쓰기 0건.** 점검 시간대 로그에서 캐시 조회는 134건, L3 성공 뒤의 저장(POST/PATCH)은 0건이었다.

**예열 규모.** 18개 법령은 현행성 점검 17종에 외국인고용법을 더한 것이다.

| 항목 | 값 |
|---|---|
| 조문 | 2,168개 |
| 저장 행(조문 + 항) | 7,473개 |
| 텍스트 | 약 242만 자 |
| 소요 시간 | 53초 |
| 그중 소득세법·조세특례제한법 | 3,362행·145만 자 |

**시행 예정일.**

| 법령 | 다음 시행일 |
|---|---|
| 근로기준법 | 2026-10-08 |
| 고용보험법·남녀고용평등법 | 2026-11-27 |
| 최저임금법·기간제법·임금채권보장법 | 2026-12-08 |
| 외국인고용법 | 2026-12-10 |
| 소득세법·조세특례제한법 | 2027-01-01 |
| 산재보험법 | 2027-03-30 |

**키워드 규칙에 넣을 조문의 현행판 대조(eflaw).**
- 남녀고용평등법: 제12·13·14·18조의2·19·19조의2·22조의2
- 근로기준법: 제20·24·46·48·69·70·74·94조
- 외국인고용법: 제25조
- 파견법: 제5·6조의2

모두 현행판에 있고 제목이 일치한다.

## 2. 변경 파일

| 파일 | 변경 |
|---|---|
| `app/core/legal_api.py` | `LawApiAuthError`, `_raise_if_error_root()`(모든 DRF 호출), `article_cache_key()`(v5 정규화), `fetch_article(..., outcome=)`, 항 → 조문 L2 폴백, `LAW_API_LIVE` 스위치, `fetch_relevant_articles` 집계 확장, 실패 로그에 조의N·항 |
| `app/core/legal_consultation.py` | `KEYWORD_LAWS`, `keyword_laws(query)`, `TOPIC_SEARCH_CONFIG['직장내성희롱']`, `process_consultation` 순서(키워드 → 주제 → 분석) |
| `app/core/pipeline.py` | 2-2: 성희롱이면 주제를 '직장내성희롱'으로(생략 대신). `metadata.law_api` 기록 조건 확장 |
| `warm_law_cache.py` (신규) | 예열 스크립트: 대상 법령 → 조문·항 행 → 일괄 upsert → 상태 행 |
| `check_law_freshness.py` | `_watched_laws()`가 `KEYWORD_LAWS` 법령도 포함 |
| `check_llm_fallback.py` | 법령 조건(D11) |
| `test_law_api_recovery.py` (신규) | 오프라인 회귀(§7) |
| `test_claim_assessor_facts.py` | C9b·C15의 성희롱 기대값 갱신(생략 → 성희롱 주제로 실행) |
| `.github/workflows/tests.yml` | 신규 테스트 등록 |
| `CLAUDE.md` | 법제처 IP 제한·예열·`LAW_API_LIVE`·키워드 규칙·감시 조건 |
| `~/DEV/laborconsult_eval/kin/run_eval.py` (저장소 밖) | `--law-mode cache\|live` |
| `~/Library/LaunchAgents/com.laborconsult.law-cache-warm.plist` (저장소 밖) | 매일 00:10 KST 실행 + RunAtLoad |

## 3. P0-1 조문 캐시 예열

### 3.1 대상 법령

```
WARM_LAWS = check_law_freshness._watched_laws()   # 기본 17종 + TOPIC_SEARCH_CONFIG + KEYWORD_LAWS 법령
```

- 외국인고용법·파견법은 `KEYWORD_LAWS`를 거쳐 자동으로 들어온다.
- 세법 2종(소득세법·조세특례제한법)도 포함한다. 퇴직소득세·근로장려금 계산 질문이 조문을 요청한다.
- 목록 하나로 현행성 점검과 예열의 대상이 같아진다. 점검은 하는데 예열이 안 되는 사각을 없애려는 것이다.

### 3.2 행 생성 (프로덕션과 같은 함수)

```python
for name in WARM_LAWS:
    root = fetch_law_root(name, key)                       # 현행 시행판(eflaw) — 등록 IP에서만 성공
    expires = next_version_midnight(name, key) or now + 7d # D2 — check_law_freshness.law_versions 재사용
    for jo in 조문단위(조문여부 == "조문"):
        no, sub = 조문번호, 조문가지번호 or None
        rows.append(row(article_cache_key(name, no, sub, None), _extract_article(root, no, None, sub)))
        for 항번호 in jo:                                   # _parse_hang_no(원문자)
            rows.append(row(article_cache_key(name, no, sub, p), _extract_article(root, no, p, sub)))
upsert(rows, chunk=500, on_conflict="cache_key")           # anon 키 — 테이블 정책상 insert/update 허용
upsert(meta:law_warm_status = {at, laws, rows, failed, next_versions})
```

- 텍스트는 `_extract_article`이 만든다. 예열 내용과 프로덕션 실호출 결과가 바이트 단위로 같아야 하기 때문이다.
- `law_name` 열에는 정식명, `article_no` 열에는 조문번호, `source_type`에는 `law_warm`을 넣는다. 사후에 출처를 가르기 위해서다.
- 실패 처리:
  - 법령 하나가 실패해도 나머지는 계속 진행한다. 실패 목록을 상태 행에 남긴다.
  - 인증 오류(`LawApiAuthError`)는 등록 IP가 아니라는 뜻이다. 그때는 즉시 중단하고 종료 코드 2를 낸다.
- `--dry-run`이면 행 수·크기·다음 시행일만 출력하고 쓰지 않는다.

### 3.3 키 정규화 (v5)

```python
def article_cache_key(law_name, article_no, sub=None, paragraph=None) -> str:
    key = f"v5:{_resolve_law_name(law_name)}_{article_no}"   # 약칭 → 정식명, 가운뎃점·공백 정규화
    if sub: key += f"의{sub}"
    if paragraph: key += f"_{paragraph}"
    return key
```

- `fetch_article`의 L1·L2 키를 모두 이 함수로 만든다.
- `v4` 키는 읽지 않는다(세대 원칙: 형식이 바뀌면 올린다). 롤백하면 구 코드가 `v4`를 그대로 읽으므로 안전하다.

### 3.4 항 → 조문 폴백 (D4)

```
L1(항 키) → L2(항 키) → [항 키가 있으면] L1·L2(조문 키) → L3(LAW_API_LIVE=on일 때만)
```

- 조문 키로 찾은 결과는 항 키 아래 L1에도 저장해 다음 조회를 줄인다.
- L3 결과를 L2에 쓰는 동작은 지금과 같다(`_article_expiry`). 등록 IP나 A 방식일 때만 일어난다.

### 3.5 실호출 스위치 (D5)

- `LAW_API_LIVE` 값이 `off`·`0`·`false`이면 `_live_allowed()`가 False다.
- 그때 `fetch_article`·`search_precedent`·`fetch_precedent`·`search_detc`·`fetch_detc`·`search_nlrc`·`fetch_nlrc_detail`·`_resolve_official_name`은 HTTP를 보내지 않는다. 각각 None 또는 []를 돌려주고 상태를 '차단'으로 남긴다.
- 서킷도 건드리지 않는다. 차단은 실패가 아니기 때문이다.
- **프로덕션 설정**은 Vercel env `LAW_API_LIVE=off`다(배포 시 사용자 확인 뒤 설정, 다음 배포부터 적용). A 방식으로 바꾸면 `on`으로 되돌린다.

## 4. P0-2 관측·알림

### 4.1 인증 오류 판정 (D6)

```python
class LawApiAuthError(RuntimeError): ...
def _raise_if_error_root(root):
    if root.tag == "Response":
        raise LawApiAuthError((root.findtext(".//result") or root.findtext(".//message") or "").strip()[:80])
```

- 적용 대상은 `legal_api.py`의 `_http.get(` 8곳과 `check_law_freshness.law_versions`다.
  - `fetch_law_root`의 기존 RuntimeError는 이 예외로 바꾼다.
  - 판례·판정문 검색은 지금 `<Response>`를 0건으로 읽고 서킷에 성공을 기록한다. 이제 failure 경로를 탄다.
- 구조 테스트가 `legal_api.py`의 모든 `_http.get(` 호출 뒤에 이 헬퍼가 있는지 확인한다.

### 4.2 결과 분류 (D7)

| 상태 | 의미 | 집계 키 |
|---|---|---|
| `ok_cache` | L1·L2 적중 | `ok` + `ok_cache` |
| `ok_live` | L3 성공 | `ok` |
| `miss` | 법령·조문 없음(빈 `<Law>`, 오해석 거부, 조문 미발견) | `miss` |
| `auth` | `LawApiAuthError` | `auth_error` + `error` |
| `error` | 그 밖의 예외(네트워크·타임아웃·HTTP) | `error` |
| `skipped` | 서킷 열림 또는 `LAW_API_LIVE=off` | `skipped` |

- `fetch_article(..., outcome: dict | None = None)`이 `outcome["status"]`를 채운다. 반환형(str | None)은 그대로라 다른 호출부는 바뀌지 않는다.
- `fetch_relevant_articles`는 상태별로 센다. 판례 정확일치 거부(`prec_rejected`)는 지금처럼 유지한다.
- `metadata.law_api`는 `miss`·`error`·`auth_error`·`skipped`·`prec_rejected` 중 하나라도 0이 아니면 기록한다. 지금은 `miss`·`error`·`prec_rejected`만 본다.
- 실패 로그에 조의N·항을 남긴다(`제19조의2`, `제74조 제7항`). 지금 로그는 `제%d조`만 찍는다.

### 4.3 감시 조건 (D11, `check_llm_fallback.py`)

- **예열 상태:** `meta:law_warm_status`의 `at`이 36시간보다 오래됐으면 알린다. 상태 행이 없거나 조회에 실패해도 알린다(fail-closed).
- **조문 성공률:** 조문을 요청한 최근 실사용 대화 5건에서 `sum(ok)/sum(requested)`가 0.5 미만이면 알린다. 요청이 없는 대화는 세지 않는다.
- 기존 LLM 폴백 판정과 같은 실행·같은 실패 메일을 쓰고, 메시지에 사유를 나눠 쓴다.
- 종료 코드 규약은 바꾸지 않는다(0 정상·판정불가, 1 알림, 2 감시 실패).

## 5. P0-3 근거 조문 선택

### 5.1 `KEYWORD_LAWS` (D8)

고신뢰 패턴만 쓴다. 오변환(무관한 조문이 근거로 실림)이 미변환보다 비싸다는 colloquial-map 원칙을 따른다.

| 규칙 | 패턴(요지) | 조문 |
|---|---|---|
| 육아휴직 | `육아\s*휴직` | 남녀고용평등법 제19조 |
| 육아기 단축 | `육아기\s*(근로\s*시간\s*)?단축` | 남녀고용평등법 제19조의2 |
| 배우자 출산휴가 | `배우자\s*(출산\|유산)` | 남녀고용평등법 제18조의2 |
| 가족돌봄 | `가족\s*돌봄` | 남녀고용평등법 제22조의2 |
| 임신 중 보호·출산전후휴가 | `임신.{0,15}(단축\|근로\s*시간\|야간\|연장\|시간\s*외)\|임신기\|(?<!배우자\s)출산\s*전후\s*휴가` | 근로기준법 제74조 |
| 직장 내 성희롱 | `성희롱\|성추행\|성적\s*(발언\|농담\|접촉\|요구)` | 남녀고용평등법 제12조·제14조 |
| 외국인 사업장 변경 | `E-?9\|고용\s*허가\|외국인\s*(근로자\|노동자)` | 외국인고용법 제25조 |
| 파견 | `불법\s*파견\|파견\s*(근로\|업체\|직원\|회사)\|위장\s*도급\|직접\s*고용\s*의무` | 파견법 제5조·제6조의2 |
| 연소자 | `미성년\|연소자\|18세\s*미만\|고등학생` | 근로기준법 제69조·제70조 |
| 취업규칙 변경 | `취업\s*규칙.{0,20}(변경\|불이익)` | 근로기준법 제94조 |
| 위약예정·의무재직 | `위약금\|의무\s*재직\|손해\s*배상.{0,6}예정\|교육비\s*반환` | 근로기준법 제20조 |
| 경영상 해고 | `경영상\s*(이유\|해고)\|정리\s*해고` | 근로기준법 제24조 |
| 임금명세서 | `(임금\|급여)\s*명세서` | 근로기준법 제48조 |
| 휴업수당 | `휴업\s*수당` | 근로기준법 제46조 |

- `keyword_laws(query)`는 규칙 순서대로 조문을 모으고 중복을 뺀다. 최대 4개다.
- 반례 테스트가 오탐을 막는다. 예: "출산휴가 급여"는 배우자 규칙에 걸리면 안 되고, "임신 계획"은 제74조에 걸리면 안 된다.
- `check_law_freshness._watched_laws()`가 이 법령들을 읽는다. 그래서 현행성 점검과 예열이 자동으로 따라온다.

### 5.2 2-2 조문 순서

```python
all_laws = dedupe(keyword_laws(query) + topic_config["default_laws"] + relevant_laws)[:5]
```

- 2-1(`analysis.relevant_laws` 직접 조회)은 그대로 둔다. 의도분석이 뽑은 조문은 2-1에서 실린다.

### 5.3 성희롱 2-2 (D10)

- `TOPIC_SEARCH_CONFIG["직장내성희롱"] = {"default_laws": ["…남녀고용평등…법률 제12조", "… 제14조"]}`. 근로기준법 제76조의2·3은 넣지 않는다.
- `_consultation_allowed`: `reason == "sexual"`이어도 생략하지 않는다(claim-authority D14 개정).
- 2-2 주제는 다음 규칙으로 정한다.
  - 성희롱이면(`assessor_info.reason == "sexual"` 또는 성희롱 키워드 규칙에 걸림) → `"직장내성희롱"`
  - 아니면 지금 규칙(분석 주제 → 판정기가 돈 질문이면 `"직장내괴롭힘"`)
- 그래프 `topic:직장내성희롱` 노드가 없어도 그래프 검색은 빈 결과를 낸다(지금 동작, 변경 없음).

## 6. P0-4 평가 환경 일치

- `run_eval.py --law-mode cache`는 import 전에 `LAW_API_LIVE=off`를 설정해 프로덕션 조건을 재현한다. 기본값은 `live`다.
- 컨텍스트 검증용으로 `run`에 `context_laws`를 남긴다. 사용자 메시지에 실린 조문 머리글(`[법령 제N조…]`) 목록이다. 완료 조건 3의 "직접 조문이 실렸는가"를 자동으로 본다.
- 외부 점검 30문항은 `~/Downloads/…-data.json`의 질문을 저장소 밖에서 그대로 읽는다. 원문은 커밋하지 않는다.
- 같은 질문을 `--law-mode cache`로 **변경 전(main)과 변경 후(branch)** 두 번 돌려 유보 표현 수와 `context_laws`를 비교한다.
- 한도 복구 후 자동 평가(E2·E3)의 법령 모드는 이 사이클을 배포한 뒤 결정한다. 프로덕션과 같은 조건을 원하면 `cache`다.

## 7. 테스트 (`test_law_api_recovery.py`, 오프라인·CI)

| # | 검사 |
|---|---|
| R1 | `legal_api.py`의 모든 `_http.get(` 뒤에 `_raise_if_error_root`가 있다(AST 구조 검사) |
| R2 | `<Response>` 응답을 흉내 내면: 판례·판정문 검색이 서킷에 성공을 기록하지 않고 `LawApiAuthError` 경로를 탄다. `fetch_article`의 `outcome`은 `auth`다 |
| R3 | `fetch_article` 상태 분류: 빈 루트 → `miss`, 일반 예외 → `error`, 서킷 열림 → `skipped`, `LAW_API_LIVE=off` → `skipped`이고 HTTP 호출 0회, L2 적중 → `ok_cache` |
| R4 | `fetch_relevant_articles` 집계 키(`ok_cache`·`auth_error`·`skipped`)와 `metadata.law_api` 기록 조건 |
| R5 | `article_cache_key`: 약칭·정식명·가운뎃점 3종(U+318D·U+00B7·U+2027)이 같은 키다. 세대는 `v5` |
| R6 | 항 → 조문 폴백: L2에 조문 키만 있으면 항 조회가 실호출 없이 조문 텍스트를 돌려준다 |
| R7 | `warm_law_cache.build_rows(root, name, expires)`: 고정 XML fixture로 만든 행의 키·텍스트가 `article_cache_key`·`_extract_article`과 같다. 조의N·항·전문(장 제목) 처리를 확인한다 |
| R8 | `next_version_midnight`: 판본 목록에서 오늘 이후 최소 시행일의 KST 자정을 고르고, 없으면 +7일 |
| R9 | `keyword_laws`: 규칙별 양성 문장과 반례 문장, 최대 4개, 중복 제거. 모든 조문이 `parse_law_reference`와 `_resolve_law_name`으로 해석된다 |
| R10 | `process_consultation` 순서(키워드 → 주제 → 분석, 최대 5개). 성희롱 질문은 '직장내성희롱' 주제가 되고 근로기준법 제76조의2가 실리지 않는다 |
| R11 | 감시: 예열 상태 36시간 초과·상태 행 없음 → 알림, 성공률 < 0.5(최근 5건) → 알림, 정상 → ok. 조회 실패 → 종료 코드 2 |
| R12 | `_watched_laws()`가 `KEYWORD_LAWS`의 법령(외국인고용법·파견법)을 포함한다 |

기존 테스트 정정:
- `test_claim_assessor_facts.py` C9b·C15: 성희롱이면 2-2를 생략한다는 기대값을, 성희롱 주제로 실행한다로 바꾼다.
- 법령 캐시 키(v4)를 가정한 테스트가 있으면 v5로 바꾼다.

## 8. 배포 순서

1. **PR #101(claim-authority)을 머지**한다. 선행 조건이다.
2. 이 사이클을 브랜치 `feat/production-law-api-recovery`에서 구현한다. 오프라인 스위트를 통과시킨다.
3. **배포 전에 예열**한다. 로컬에서 `warm_law_cache.py`를 실행해 v5 키를 채운다. 현재 프로덕션은 v4를 읽으므로 영향이 없다.
4. **사용자 확인 뒤** Vercel env `LAW_API_LIVE=off`(Production)를 설정한다. 다음 배포부터 적용된다.
5. PR을 머지해 배포한다. 프로덕션은 v5 캐시를 읽고 실호출을 건너뛴다.
6. launchd 예열 작업을 설치한다(매일 00:10 KST, RunAtLoad).
7. 검증한다.
   - 배포 뒤 실사용 대화의 `metadata.law_api`(ok·skipped)와 런타임 로그
   - 외부 점검 30문항의 `--law-mode cache` 전후 비교
   - 3일 관측(완료 조건 1)

## 9. 위험과 롤백

| 위험 | 대응 |
|---|---|
| 예열 키와 조회 키가 어긋나 효과가 0이다 | 단일 키 함수(R5·R7). 배포 직후 `ok_cache` 비율을 확인한다 |
| 다음 시행일 계산 오류로 옛 판본이 나간다 | `law_versions` 재사용(R8). 시행일 당일 오전 freshness 점검을 유지한다 |
| 맥이 꺼져 예열이 끊긴다 | 상태 감시(36시간). 만료는 다음 시행일 또는 7일이라 그 전까지는 유지된다 |
| 키워드 규칙 오탐으로 무관한 조문이 실린다 | 고신뢰 패턴과 반례 테스트(R9). 규칙당 최대 2개, 합계 최대 4개 |
| `LAW_API_LIVE=off`로 판례·판정문 실시간 조회가 사라진다 | 지금도 프로덕션에서 0건이다(인증 실패). A 방식으로 전환할 때 되살아난다 |
| 롤백 | Vercel env `LAW_API_LIVE`를 제거한다(기본 on). PR을 revert하면 구 코드가 v4 키를 읽는다. 예열 행(v5)은 남아도 무해하다 |

## 10. 범위 밖

- A 방식(고정 IP): 비용·리전 IP 등록 가능 여부를 확인한 뒤 별도로 진행한다.
- 판례·판정문의 캐시 예열: 질의가 열려 있어 예열할 수 없다.
- 답변 모델의 유보 성향, 모성보호·성희롱 사실 블록, 30번 정책·면책 고지 중복은 Plan §3과 같다.
- 의도분석 주제 enum 확장(D9).
