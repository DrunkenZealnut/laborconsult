# production-law-api-recovery — Design rev2

> Plan: `docs/01-plan/features/production-law-api-recovery.plan.md`
> 결정(2026-10-06 사용자 확정, "모두 권고대로"):
> - P0-1은 **조문 캐시 예열(C)을 먼저** 하고, 고정 IP(A)는 비용을 확인한 뒤 결정한다.
> - 예열 대상은 기본안이다.
> - 선행 사이클 PR #101은 머지 완료(`204e59f`)다.
> rev2(2026-10-06): design-validator 72점·조건부 승인. High 3·Medium 8·Low 10을 반영했다(§11).
> - **판본을 명시한 예열**(`ef_yd`=기준판, 만료 상한 3일)
> - **공백까지 제거한 캐시 키**와 약칭 보강
> - **키워드 조문을 2-1로** 옮김
> - **성희롱은 주제 유지 + 괴롭힘 조문 제외**
> - **감시 데이터 상시 기록**(조문·판례 분리)
> - **프로덕션 조건 재현 평가**(`--law-mode prod`)
> - **오프라인 스크립트의 인증 오류 판정**

## 0. 설계 결정

| # | 결정 | 근거 |
|---|---|---|
| D1 | 등록 IP 머신(로컬 맥)이 예열 대상 법령의 **전 조문**을 Supabase `law_article_cache`에 채운다. 스크립트는 `warm_law_cache.py`다. launchd가 매일 KST 00:10과 06:10에 실행하고, 로그인 시에도 한 번 돈다(RunAtLoad). 법령마다 최대 2회 재시도한다 | 프로덕션 실호출은 한 번도 성공하지 않았다(점검 시간대 캐시 저장 0건). 하루 두 번 돌리면 자정 실행이 실패해도 아침에 회복한다(Plan C 요건 "실패 시 재시도") |
| D2 | **판본을 명시해 받는다.** 판본 목록에서 기준판(`reference_version`, 시행일 ≤ 오늘의 최댓값)을 구하고 `fetch_law_root(name, key, ef_yd=기준판)`으로 조회한다. 응답 머리글의 시행일자가 기준판과 다르면 그 법령은 쓰지 않는다. 만료는 `min(다음 시행일 00:00 KST, 지금 + 3일)`이다. 판본 목록 조회가 실패하면 판본을 지정하지 않고 받되, 만료를 다음 KST 자정으로 두고 경고를 남긴다(지금 프로덕션 의미와 같다) | 법제처는 자정 직후 '현행' 포인터를 늦게 바꿀 수 있다(`legal_api.py` 00~03시 1시간 규칙, `check_law_freshness`의 "반영 지연?" 경고). 판본을 고정하면 이 지연과 무관해진다. 상한 3일은 판본 목록에 아직 없는 '공포 즉시 시행' 개정에 대비한 값이다. 맥이 꺼져 있을 때 최악의 지연이 3일로 묶인다 |
| D3 | 캐시 키는 `v5:{_norm_compact(canonical_law_name(name))}_{조}[의{N}][_{항}]`이다. 공백까지 제거한 정식명을 쓴다. 약칭 사전은 공백 제거형으로 조회하고, 예열 대상 법령의 약칭을 보강한다. 키 생성은 `article_cache_key()` 한 함수가 맡고, 예열과 조회가 같이 쓴다. 캐시 미스는 원 입력과 키를 로그로 남긴다 | 공백 정리만으로는 "근로자퇴직급여보장법"(LLM 표기)과 정식명 키가 갈린다. 실호출을 끄면 이 차이를 정식명 해석(실호출)으로 메울 경로도 없다 |
| D4 | 항 단위 키가 캐시에 없으면 실호출 전에 같은 조문의 전체 키를 찾는다. 조문 키의 L1 값이 미매칭 표지(`_MISS_SENTINEL`)면 미스로 보고, 항 키로 복사하지 않는다 | "항이 없으면 조문 전체로 폴백"하는 기존 의미와 같다 |
| D5 | `LAW_API_LIVE`(기본 `on`)는 **호출 시점에 읽는다**. `off`면 법제처 실호출을 하지 않는다. 이 검사는 `_circuit_check()`보다 앞에 둔다. 차단된 조회는 미매칭 표지를 남기지 않는다. 프로덕션은 `off`로 둔다(C 방식인 동안, 배포 시 사용자 확인). 오프라인 테스트는 `on`으로 고정한다 | 실패가 확실한 호출이 요청마다 1~1.4초를 쓰고 서킷을 흔든다. 차단을 미매칭으로 남기면 나중에 예열된 행이 자정까지 가려진다 |
| D6 | **법제처 응답을 받는 모든 곳**이 `<Response>` 루트를 `LawApiAuthError`(RuntimeError 하위)로 올린다. 공용 헬퍼는 `legal_api._raise_if_error_root()`다. 오프라인 스크립트에서는 이 예외를 '없음'으로 바꾸지 않고 실행을 멈춘다 | 판례·판정문 검색은 인증 오류를 "결과 0건"으로 읽고 서킷에 성공을 기록한다. 오프라인 스크립트도 같은 클래스다. 판례 수집은 진행 기록에 '미발견'을 영구 저장하고, 그래프는 캐시를 먼저 지운 뒤 조문 노드를 조용히 뺀다 |
| D7 | 조회 결과를 분류한다. 조문은 `ok_cache`·`ok_live`·`miss`·`auth_error`·`error`·`skipped_unwarmed`·`skipped_circuit`, 판례·판정문은 `ok`·`rejected`·`miss`·`auth_error`·`error`·`skipped`다. off에서 예열 대상 법령의 키가 없으면 `miss`로 센다(예열 누락이나 존재하지 않는 조문). 예열 대상이 아닌 법령이면 `skipped_unwarmed`다 | 지금은 인증 실패·차단·미발견이 모두 `miss` 하나로 섞인다 |
| D7b | `metadata.law_api`를 v2 구조로 바꾼다: `{"live": "on/off", "articles": {...}, "precedents": {...}}`. 조회 요청이 1건이라도 있으면 **항상** 기록한다. 2-1과 2-2는 정규화 키로 중복을 빼, 같은 조문을 한 번만 센다 | 실패한 대화만 기록하면 성공률을 계산할 수 없다(검증 H1) |
| D8 | **키워드 조문은 2-1(조문 조회)에 넣는다.** 의도분석 결과가 없거나 `consultation_type`이 비어도, 계산 질문이어도 돈다. 2-1의 순서는 키워드 조문(최대 3개) → 의도분석 조문이고 합계 최대 5개다. 2-2는 주제 기본 조문 → 의도분석 조문 순서에서 2-1이 이미 조회한 키를 빼고, 최대 5개다 | 2-2는 `consultation_type`이 있어야 돌고 계산 질문이면 건너뛴다(검증 M1). 키워드를 2-1로 옮기면 2-2의 주제 기본 조문 슬롯도 잠식하지 않는다(검증 M4) |
| D9 | 의도분석의 주제 enum은 **바꾸지 않는다**(Plan P0-3과 다름, §11) | 분류가 흔들리고 fixture 기대값이 바뀐다. 조문 선택은 D8이 맡는다 |
| D10 | **성희롱 질문은 2-2를 생략하지 않고 원래 주제를 유지한다.** 대신 2-1·2-2 모두에서 근로기준법 제76조의2·제76조의3을 뺀다. 성희롱 판정은 `harassment_assessor.grounding`의 판정(`is_sexual_harassment`, 기존 `_SEXUAL_RE`) 하나를 쓴다. 키워드 규칙도 이 판정으로 남녀고용평등법 제12·14조를 싣는다 | rev1의 '직장내성희롱' 주제 교체는 실효가 괴롭힘 조문 제거뿐이었다. 그런데 교체하면 "성희롱 + 해고" 질문이 해고 기본 조문까지 잃었다(검증 M3). 판정이 두 벌이면 어긋난다("성적인 농담") |
| D11 | 폴백 감시(`check_llm_fallback.py`)에 법령 조건을 더한다. 아래 '감시 조건' 표 참조 | 장애가 6주 넘게 아무에게도 보이지 않았다(검증 H1·M6) |
| D12 | 예열 상태는 `law_article_cache`의 특수 키 `meta:law_warm_status`에 기록한다. 만료는 `2099-12-31`이고, 감시는 만료 필터 없이 원시 조회한다 | DDL이 필요 없다. 만료 행 정리 경로는 없다(`purge_expired_data`는 이 테이블을 건드리지 않음) |
| D13 | **프로덕션 조건 재현 평가**(`run_eval.py --law-mode prod`)를 둔다. 법제처 DRF 요청이 프로덕션과 같은 `<Response>`(인증 실패)를 받도록 `_http.get`을 바꿔 끼운다. 코드 버전(main·브랜치)과 무관하게 같은 조건이 된다. L2 읽기는 프로덕션처럼 공유 캐시를 쓰고, L3가 실패하므로 L2 쓰기는 없다 | main에는 `LAW_API_LIVE`가 없다. 로컬(등록 IP) 실행은 실호출에 성공해 그 결과를 **프로덕션 L2에 쓴다**. 전후 비교가 깨지고 그날 프로덕션 품질까지 바뀐다(검증 M7, 실제로 프로덕션 적중 26%의 출처가 우리 로컬 실행이었다) |
| D14 | 예열 대상의 단일 출처는 신규 모듈 `app/core/law_catalog.py`다. `BASE_LAWS`(현행성 점검 17종)·`KEYWORD_LAWS`·`keyword_laws(query)`·`warm_law_names()`(기본 + 주제 기본 조문 + 키워드 조문의 법령)를 둔다. 예열 스크립트·`check_law_freshness._watched_laws()`·런타임 분류(D7)가 함께 쓴다 | 대상이 셋으로 갈리면 "점검은 하는데 예열은 안 되는" 사각이 생긴다. `legal_consultation`은 `legal_api`를 import하므로, 순환을 피하려고 분리했다(주제 기본 조문은 함수 안에서 늦게 import) |

**감시 조건(D11)**

| 조건 | 알림 기준 |
|---|---|
| ① 예열 상태 | 마지막 성공 후 36시간 초과, `laws_failed`가 비어 있지 않음, 행 수가 직전 대비 20% 넘게 감소, 상태 행 없음·조회 실패(fail-closed) 중 하나 |
| ② 조문 성공률 | 조문을 요청한 최근 실사용 10건에서 `Σok / Σ(requested − skipped_unwarmed)`가 0.8 미만. 분모 합이 20 미만이면 판정을 보류한다 |
| ③ 인증 오류 | `live=on`인 대화에서 `auth_error > 0`(A 방식 전환 후) |

- 판정은 기존 실행·실패 메일·종료 코드 규약(0 정상·판정불가, 1 알림, 2 감시 실패)을 그대로 쓴다.
- 비율 임계를 쓰는 근거: CLAUDE.md는 대화 단위 비율(하루 0~5건)을 금지하는데, 이 조건은 요청 수 합(대화당 5~10건, 분모 20 이상)으로 판정한다.

## 1. 실측 근거

Plan §1과 rev1 §1(예열 18개 법령, 조문 2,168개, 7,473행, 약 242만 자, 53초)에 더해 다음을 확인했다(2026-10-06).

- **판본 지정 조회:** `fetch_law_root("근로기준법", ef_yd=기준판)`의 머리글 시행일자가 현행 조회와 같고(20261002), 기준판과도 같다.
  - 시행령도 판본 목록이 조회된다. 근로기준법 시행령 57개(기준판 20251023), 고용보험법 시행령 100개(20260918).
  - rev1의 시행령 '다음 시행 None'은 예정 판본이 없다는 뜻이었다.
- **제18조의4(배우자 유산·사산휴가):** 5일 범위, 최초 3일 유급, 유산·사산일부터 20일 이내 청구. 제37조②2의3이 이 조 제4항을 인용한다.
  - rev1 표의 `배우자 (출산|유산)` → 제18조의2 매핑은 틀렸다.
- **약칭 사전 현황:** 10개(근기법·최임법·고보법·산재법·남녀고용평등법·퇴직급여법·기간제법·파견법·임채법·노조법).
  - 외국인고용법·산재보험법·노동조합법·근퇴법은 없다.
- **오프라인 스크립트의 법제처 호출:**

  | 지점 | `<Response>` 판정 |
  |---|---|
  | `fetch_court_precedents._get_xml` | 없음 |
  | `fetch_official_rules.fetch_admrul`(검색·상세) | 없음 |
  | `build_graph.build_articles` | 조회 전에 7일 지난 캐시 파일을 지우고, 실패하면 `[]` |
  | `check_law_freshness.law_versions` | 있음(RuntimeError) |
- **2-1 조건:** `analysis and analysis.relevant_laws and config.law_api_key`(`pipeline.py:1955`). 의도분석이 실패하면 2-1이 돌지 않는다.

## 2. 변경 파일

| 파일 | 변경 |
|---|---|
| `app/core/law_catalog.py` (신규) | `BASE_LAWS`, `KEYWORD_LAWS`, `keyword_laws(query)`, `warm_law_names()` (D14) |
| `app/core/legal_api.py` | `LawApiAuthError`·`_raise_if_error_root`(8곳), `canonical_law_name`·`article_cache_key`(v5, D3), 약칭 보강, `fetch_article(..., outcome=)`·항→조문 폴백(D4), `_live_allowed()`(D5), 판례·판정문 분류, `fetch_relevant_articles`·`fetch_relevant_precedents` 집계 v2(D7), 실패 로그에 조의N·항 |
| `app/core/legal_consultation.py` | `process_consultation(..., exclude_keys=, drop_refs=)`: 2-1 키 제외·성희롱 시 제76조의2·3 제외. 중복 제거를 정규화 키로 |
| `app/core/pipeline.py` | 2-1 조건·순서(D8). 성희롱이면 2-2 실행 + 제외 목록(D10, `_consultation_allowed` 개정). `metadata.law_api` v2 상시 기록(D7b) |
| `harassment_assessor/grounding.py` | `is_sexual_harassment(text)` 공개(기존 `_SEXUAL_RE`) |
| `warm_law_cache.py` (신규) | 예열(D1·D2·D12), `--dry-run`, 종료 코드 0 정상·1 일부 실패·2 인증 오류 |
| `check_law_freshness.py` | `_watched_laws()` → `law_catalog.warm_law_names()`, `law_versions`의 오류를 `LawApiAuthError`로 |
| `check_llm_fallback.py` | 감시 조건 ①②③(D11) |
| `fetch_court_precedents.py`, `fetch_official_rules.py`, `build_graph.py` | `<Response>` 판정과 실행 중단(D6). `build_graph`는 새로 받는 데 성공한 뒤에 캐시를 교체한다 |
| `.env.example` | `LAW_API_LIVE=on` 항목과 설명 |
| `test_law_api_recovery.py` (신규) | §7 R1~R13 |
| 기존 테스트 | §7 '기존 테스트 정정' |
| `.github/workflows/tests.yml` | 신규 테스트 등록 |
| `.github/workflows/llm-fallback-alert.yml` | 감시가 새로 import하는 모듈의 의존성 확인(`requests` 등, 검증 L5) |
| `CLAUDE.md` | 법제처 IP 제한·예열·`LAW_API_LIVE`·키워드 규칙·감시 조건·프로덕션 재현 평가 |
| 저장소 밖 | `~/DEV/laborconsult_eval/kin/run_eval.py`(`--law-mode prod/cache/live`, `context_laws`), `~/Library/LaunchAgents/com.laborconsult.law-cache-warm.plist` |

## 3. P0-1 조문 캐시 예열

### 3.1 대상 (D14)

```python
def warm_law_names() -> list[str]:          # app/core/law_catalog.py — 정식명, 순서 보존·중복 제거
    names = list(BASE_LAWS)                  # 현행성 점검 17종(세법 2종 포함)
    names += 주제 기본 조문의 법령            # legal_consultation.TOPIC_SEARCH_CONFIG(함수 안에서 import)
    names += KEYWORD_LAWS의 법령              # 외국인고용법이 여기서 새로 들어온다
    return dedupe(canonical_law_name(n) for n in names)
```

- 파견법·남녀고용평등법은 이미 `BASE_LAWS`에 있다. 새로 들어오는 것은 외국인고용법뿐이다(rev1 §3.1 정정, 검증 L1).
- 세법 2종(소득세법·조세특례제한법)도 포함한다. 퇴직소득세·근로장려금 계산 질문이 조문을 요청한다. 두 법령이 3,362행으로 전체의 45%다.

### 3.2 행 생성 (D2)

```python
for name in warm_law_names():
    versions = law_versions(name, key)               # check_law_freshness와 같은 함수
    ref = reference_version(versions, today_kst)     # 시행일 ≤ 오늘의 최댓값
    if ref:
        root = fetch_law_root(name, key, ef_yd=ref, timeout=60)     # 판본 고정
        if header_date(root) != ref: fail(name, "판본 불일치"); continue
        nxt = min(v for v in versions if v > today_kst, default=None)
        expires = min(midnight_kst(nxt) if nxt else ∞, now + 3d)
    else:                                            # 목록 실패·없음
        root = fetch_law_root(name, key, timeout=60)
        expires = next_midnight_kst(now); warn(name)
    for jo in 조문단위(조문여부 == "조문"):
        no, sub = 조문번호, 가지번호(없거나 "0"이면 None — _extract_article과 같은 판정, 검증 L8)
        rows += row(article_cache_key(name, no, sub), _extract_article(root, no, None, sub))
        for p in 항번호들(_parse_hang_no):
            rows += row(article_cache_key(name, no, sub, p), _extract_article(root, no, p, sub))
upsert(rows, chunk=500, on_conflict="cache_key")     # 반영 행 수는 len(res.data)로 확인
upsert(meta:law_warm_status = {at, rows, prev_rows, laws_ok, laws_failed, warnings, versions:{법령: ref}, next:{법령: nxt}},
       expires_at="2099-12-31T00:00:00Z")
```

- 텍스트는 프로덕션과 같은 `_extract_article`로 만든다(바이트 동일).
- 열에는 `law_name`=정식명, `article_no`=조, `source_type`=`law_warm`을 넣는다.
- 실패 처리:
  - 인증 오류(`LawApiAuthError`)는 등록 IP가 아니라는 뜻이다. 즉시 중단하고 종료 코드 2를 낸다. 행은 쓰지 않는다.
  - 그 밖의 오류는 법령 단위로 2회 재시도하고, 그래도 실패하면 `laws_failed`에 남긴 뒤 다음 법령으로 넘어간다.
- **00~03시 규칙과의 관계:** 프로덕션 L1은 L2 적중 때도 `_article_expiry()`(다음 자정 이하, 00~03시 1시간)로 저장하므로 지금 규칙을 그대로 따른다. 예열 행만 자정을 넘겨 유효한데, 판본을 `ef_yd`로 고정했기 때문에 '현행' 포인터 지연의 영향을 받지 않는다. CLAUDE.md에 이 예외를 기록한다.

### 3.3 키 (D3)

```python
_ALIASES_COMPACT = {_norm_compact(k): v for k, v in _LAW_NAME_ALIASES.items()}
def canonical_law_name(name):   # 공백 제거형으로 약칭을 찾고, 없으면 정규화한 원명
    n = _norm_law_name(name); return _ALIASES_COMPACT.get(_norm_compact(n), n)
def article_cache_key(name, no, sub=None, paragraph=None):
    k = f"v5:{_norm_compact(canonical_law_name(name))}_{no}"
    return k + (f"의{sub}" if sub else "") + (f"_{paragraph}" if paragraph else "")
```

- **약칭 보강:** 외국인고용법 → 외국인근로자의 고용 등에 관한 법률, 산재보험법 → 산업재해보상보험법, 노동조합법 → 노동조합 및 노동관계조정법, 근퇴법 → 근로자퇴직급여 보장법.
- 기존 10개는 그대로 둔다. `_resolve_law_name`(조회용)도 같은 사전을 쓴다.
- `fetch_article`의 L1·L2 키를 모두 이 함수로 만든다. `v4`는 읽지 않는다.
- 캐시 미스(off)는 `원 입력 → 키`를 info 로그로 남긴다. LLM이 내는 변형을 실측하기 위해서다(검증 H3 '확인 필요').
- 2-1·2-2의 중복 제거도 이 키 기준이다(검증 L3).

### 3.4 항 → 조문 폴백 (D4)

```
L1(항) → L2(항) → [항 키였다면] L1(조문, sentinel이면 미스) → L2(조문) → [LAW_API_LIVE=on이면] L3
```

조문 키로 찾은 결과는 항 키 아래 L1에도 저장한다. L3 결과를 L2에 쓰는 동작은 지금과 같다.

### 3.5 실호출 스위치 (D5)

`_live_allowed()`는 `os.environ.get("LAW_API_LIVE", "on")`을 호출 시점에 읽는다.

| 함수 | off일 때 |
|---|---|
| `fetch_article` | L1·L2만 본다(D7: `ok_cache`/`miss`/`skipped_unwarmed`) |
| `search_precedent`·`search_detc`·`search_nlrc`·`_resolve_official_name` | HTTP 없이 `[]`/None을 돌려주고 `skipped`로 센다 |
| `fetch_precedent`·`fetch_detc`·`fetch_nlrc_detail` | L1·L2 조회 뒤에 게이트를 둔다(검증 L2) |

- 판례·판정문 상세 캐시는 off에서 사실상 쓰이지 않는다. ID를 주는 검색에 캐시가 없기 때문이고, 지금 프로덕션도 0건이다.
- **Vercel의 `LAW_API_KEY`는 지우지 않는다.** 키가 없으면 캐시 조회조차 하지 않는다(`pipeline.py:1955·2121·2142`, `legal_api.py:1011`).

## 4. P0-2 관측·알림

### 4.1 인증 오류 판정 (D6)

| 위치 | 변경 |
|---|---|
| `legal_api.py` `_http.get(` 8곳 | 파싱 직후 `_raise_if_error_root(root)`. 판례·판정문 검색은 이 예외로 failure 경로를 탄다(서킷에 성공을 기록하지 않음) |
| `check_law_freshness.law_versions` | RuntimeError → `LawApiAuthError` |
| `warm_law_cache.py` | `fetch_law_root`·`law_versions`가 올리는 예외로 즉시 중단(종료 코드 2) |
| `fetch_court_precedents._get_xml` | 판정 후 예외를 올린다. 재시도하지 않는다. 진행 기록(`not_found`)에 쓰지 않고 실행을 멈춘다 |
| `fetch_official_rules.fetch_admrul` | 검색·상세 두 곳에서 판정 후 예외를 올린다 |
| `build_graph.build_articles` | `LawApiAuthError`를 `[]`로 바꾸지 않고 빌드를 멈춘다. 만료된 캐시 파일은 새로 받는 데 성공한 뒤에 교체한다 |

### 4.2 결과 분류·기록 (D7·D7b)

```json
"law_api": {
  "live": "off",
  "articles":   {"requested": 7, "ok": 6, "ok_cache": 6, "ok_live": 0, "miss": 1,
                 "auth_error": 0, "error": 0, "skipped_unwarmed": 0, "skipped_circuit": 0},
  "precedents": {"requested": 1, "ok": 0, "rejected": 0, "miss": 0, "auth_error": 0, "error": 0, "skipped": 1}
}
```

- `fetch_article(..., outcome: dict | None = None)`이 상태를 채운다. 반환형은 그대로다.
- `fetch_relevant_articles`는 조문 참조와 판례 번호 참조를 나눠 센다. 정확일치 거부는 `rejected`다.
- `articles.requested + precedents.requested > 0`이면 항상 기록한다. 0이면 기록하지 않는다.
- 옛 대화는 평평한 구조(`requested`·`ok`·`miss`…)다. 감시는 v2만 읽고 옛 구조는 건너뛴다.
- 실패 로그에 조의N·항을 남긴다(`제19조의2 제1항`).

### 4.3 감시 (D11)

§0의 '감시 조건' 표를 그대로 구현한다.
- 상태 행은 `select("content").eq("cache_key", "meta:law_warm_status")`로 만료 필터 없이 읽는다.
- 대화 메타는 기존 실사용 조회를 재사용한다.

## 5. P0-3 근거 조문 선택

### 5.1 `KEYWORD_LAWS` (`law_catalog.py`, 표 순서가 우선순위)

| 규칙 | 조건(요지) | 조문 |
|---|---|---|
| 직장 내 성희롱 | `is_sexual_harassment(query)`(D10, 단일 판정) | 남녀고용평등법 제12조·제14조 |
| 육아휴직 | `육아\s*휴직` | 남녀고용평등법 제19조 |
| 육아기 단축 | `육아기\s*(근로\s*시간\s*)?단축` | 남녀고용평등법 제19조의2 |
| 배우자 출산휴가 | `배우자\s*(의\s*)?출산` | 남녀고용평등법 제18조의2 |
| 배우자 유산·사산 | `배우자\s*(의\s*)?(유산\|사산)` | 남녀고용평등법 **제18조의4** |
| 가족돌봄 | `가족\s*돌봄` | 남녀고용평등법 제22조의2 |
| 임신 중 보호 | `임신.{0,15}(단축\|근로\s*시간\|야간\|연장\|시간\s*외)\|임신기\|출산\s*전후\s*휴가`. 단 `(아내\|배우자\|와이프\|부인\|여자\s*친구).{0,12}(임신\|출산)`이면 제외 | 근로기준법 제74조 |
| 외국인 사업장 변경 | `E-?9\|고용\s*허가\|고용허가제`, 또는 `외국인` + `(사업장\|근무처)\s*변경`이 함께 | 외국인고용법 제25조 |
| 파견 | `불법\s*파견\|파견\s*(근로\|업체\|직원\|회사)\|위장\s*도급\|직접\s*고용\s*의무` | 파견법 제5조·제6조의2 |
| 연소자 | `미성년\|연소자\|18세\s*미만\|고등학생` | 근로기준법 제69조·제70조 |
| 취업규칙 변경 | `취업\s*규칙.{0,20}(변경\|불이익)` | 근로기준법 제94조 |
| 위약예정·의무재직 | `위약금\|의무\s*재직\|손해\s*배상.{0,6}예정\|교육비\s*반환` | 근로기준법 제20조 |
| 경영상 해고 | `경영상.{0,12}(해고\|감원)\|정리\s*해고` | 근로기준법 제24조 |
| 임금명세서 | `(임금\|급여)\s*명세서` | 근로기준법 제48조 |
| 휴업수당 | `휴업\s*수당` | 근로기준법 제46조 |

- `keyword_laws(query)`는 표 순서대로 조문을 모은다. 정규화 키로 중복을 빼고 **최대 3개**만 남긴다.
- rev1에서 바뀐 점:
  - 외국인 규칙은 사업장 변경 문맥을 요구한다. 외국인 퇴직금·최저임금 질문은 제외된다.
  - 임신 규칙은 배우자 임신을 제외한다.
  - 경영상 규칙은 해고·감원을 요구한다. 임금 삭감·휴업 질문은 제외된다.
  - 배우자 유산은 제18조의4로 고쳤다.
  - 쓰지 않는 제13조는 뺐다.

### 5.2 조문 순서 (D8)

```python
refs_21 = dedupe_by_key(keyword_laws(query) + (analysis.relevant_laws if analysis else []))
if sexual: refs_21 = drop(refs_21, 근로기준법 제76조의2, 제76조의3)
refs_21 = refs_21[:5]                                    # 2-1: 키워드가 있으면 analysis가 없어도 돈다
refs_22 = dedupe_by_key(topic_defaults + relevant_laws) - keys(refs_21)
if sexual: refs_22 = drop(refs_22, 근로기준법 제76조의2, 제76조의3)
refs_22 = refs_22[:5]                                    # 2-2
```

- 2-1의 조건은 `(refs_21) and config.law_api_key`가 된다.
- 2-1 컨텍스트(5,000자)와 2-2 컨텍스트(8,000자) 상한은 그대로 둔다.
- 2-1·2-2에 같은 조문이 이중으로 실리던 기존 문제는 키 제외로 사라진다.

### 5.3 성희롱 (D10)

- `_consultation_allowed`: `reason == "sexual"`이어도 생략하지 않는다. claim-authority D14와 `_not_called_info`의 `reason`은 기록용으로 남긴다.
- 성희롱 여부는 `sexual = is_sexual_harassment(query)`다. 판정기 미실행·미호출 경로에서도 같은 함수로 계산한다.
- 주제는 바꾸지 않는다. '직장내괴롭힘' 주제라면 기본 조문 중 제76조의2·3이 빠지고, 남녀고용평등법 제14조의2가 남는다.

## 6. P0-4 평가 (D13)

`run_eval.py --law-mode`:

| 값 | 동작 |
|---|---|
| `prod` | import 직후 `legal_api._http.get`을 감싼다. `law.go.kr/DRF` URL에는 `<Response><result>사용자 정보 검증에 실패하였습니다.</result></Response>`를 돌려주고, 나머지는 원래대로 보낸다. 사전 점검(`fetch_law_root` 실호출)은 건너뛴다 |
| `cache` | 브랜치 전용. `LAW_API_LIVE=off` |
| `live` | 기본값. 지금 동작이다. **프로덕션 L2에 행을 쓴다는 점에 주의** |

- `run.context_laws`에 사용자 메시지에 실린 조문 머리글 목록을 남긴다.
- **완료 조건 3 = 로컬 `prod` 재현 비교**다. 외부 점검 30문항을 쓰고, 질문은 `~/Downloads/…-data.json`에서 읽으며 커밋하지 않는다.
  - '변경 전'은 main 코드 + `prod`다. 프로덕션이 오늘 읽는 v4 캐시를 그대로 읽는다.
  - '변경 후'는 브랜치 코드 + 예열 완료 + `prod`다.
  - 같은 답변 모델로 돌려 유보 표현 수와 1·2·3·6·8번의 `context_laws`를 비교한다.
- **프로덕션에서 다시 돌리지 않는다.** 그 대화는 G-B(비프로덕션 출처 판정)에 걸리지 않아 실사용으로 저장된다. 그러면 공개 게시판에 노출되고(지난 점검에서 3/30건), 감시 표본도 오염된다. 외부 재점검은 사용자가 결정하고, 그때는 이 위험을 알린다.
- 프로덕션 검증은 자연 트래픽의 `metadata.law_api` 3일 관측(완료 조건 1)으로 한다.

## 7. 테스트 (`test_law_api_recovery.py`, 오프라인·CI, `LAW_API_LIVE=on` 고정)

| # | 검사 |
|---|---|
| R1 | `legal_api.py`의 모든 `_http.get(` 호출 함수가 `_raise_if_error_root`를 부른다(AST). `<Response>`를 흉내 내면 `fetch_court_precedents._get_xml`·`fetch_official_rules.fetch_admrul`·`check_law_freshness.law_versions`가 `LawApiAuthError`를 올리고 None이나 []를 내지 않는다 |
| R2 | `<Response>`에서 판례·판정문 검색이 서킷에 성공을 기록하지 않는다. `build_graph.build_articles`는 인증 오류에서 기존 캐시 파일을 지우지 않는다 |
| R3 | `fetch_article` 분류: 빈 루트·조문 없음 → `miss`, 인증 → `auth_error`, 일반 예외 → `error`, 서킷 → `skipped_circuit`, off·예열 대상 키 없음 → `miss`, off·예열 밖 법령 → `skipped_unwarmed`(HTTP 0회, sentinel 미기록), L2 적중 → `ok_cache`. off 검사가 서킷보다 먼저다 |
| R4 | `metadata.law_api` v2: 요청이 있으면 항상 기록되고 조문·판례가 분리된다. 2-1·2-2에 같은 조문이 있으면 한 번만 센다 |
| R5 | `article_cache_key`: 약칭(기존·보강), 공백 변형("근로자퇴직급여보장법"), 가운뎃점 3종이 같은 키다. `v5` 접두 |
| R6 | 항 → 조문 폴백. 조문 키 L1 sentinel은 미스로 처리하고 항 키로 복사하지 않는다 |
| R7 | `warm_law_cache.build_rows`: 고정 XML fixture(조의N·항·전문 장 제목·조문가지번호 "0")로 만든 키·텍스트가 `article_cache_key`·`_extract_article`과 같다 |
| R8 | 만료: `min(다음 시행일 00:00 KST, +3일)`. 목록 실패 → 다음 자정 + 경고. 머리글 불일치 → 쓰지 않음 |
| R9 | `keyword_laws`: 규칙별 양성·반례. 배우자 유산 → 제18조의4, 아내 임신 → 제74조 아님, 외국인 퇴직금 → 제25조 아님, 경영상 임금 삭감 → 제24조 아님, "성적인 농담" → 제12·14조. 최대 3개. 모든 조문이 해석되고 `warm_law_names()`에 들어 있다 |
| R10 | 2-1·2-2 순서·상한·키 제외. 성희롱이면 양쪽 모두 제76조의2·3 없음, 원 주제 기본 조문 유지(성희롱 + 해고 → 해고 기본 조문 유지) |
| R11 | 감시 ①②③: 36시간·`laws_failed`·행 20% 감소·상태 행 없음 → 알림. 성공률 < 0.8(분모 ≥ 20) → 알림, 분모 < 20 → 보류. `live=on`이고 `auth_error` → 알림. 조회 실패 → 종료 코드 2 |
| R12 | `warm_law_names()`가 외국인고용법을 포함하고 `check_law_freshness._watched_laws()`와 같다 |
| R13 | `.env.example`에 `LAW_API_LIVE`가 있다. 신규 `app/core/law_catalog.py`가 git 추적 대상이다(미추적이면 Vercel 500) |

기존 테스트 정정(검증 M8):

| 테스트 | 정정 |
|---|---|
| `test_kin_accuracy.py:384-387` | `fetch_article` 소스의 `v4:` 문자열 요구 → `article_cache_key` 구조 검사로 바꾼다 |
| `test_offline_units.py:241-248` | v4 접두 → v5 |
| `test_effective_law.py` E3 | v4 접두 → v5 |
| `test_effective_law.py` E15 | 기록 조건을 v2 '요청 > 0'으로 바꾼다 |
| `test_effective_law.py` E1 | `target=law` 금지 대상 파일에 `warm_law_cache.py`를 추가한다 |
| `test_llm_fallback_alert.py` | FakeDb에 `law_article_cache` 상태 행 조회를 추가한다 |
| `test_claim_assessor_facts.py` C9b·C15 | 성희롱이면 2-2 생략 → 2-2 실행 + 제76조의2·3 제외 |

## 8. 배포 순서

1. ✅ PR #101 머지.
2. 브랜치 `feat/production-law-api-recovery`에서 구현한다. 오프라인 스위트를 통과시킨다.
3. **변경 전 측정:** main 코드로 `run_eval --law-mode prod`(30문항)를 돌린다.
4. **예열:** `warm_law_cache.py --dry-run` 후 실행해 v5 행을 쓴다. 현재 프로덕션은 v4를 읽으므로 영향이 없다.
5. **변경 후 측정:** 브랜치 코드로 `run_eval --law-mode prod`를 돌려 3과 비교한다(완료 조건 3).
6. **사용자 확인 뒤** Vercel env `LAW_API_LIVE=off`(Production)를 설정한다. `LAW_API_KEY`는 유지한다. 다음 배포부터 적용된다.
7. PR을 머지해 배포한다. 프로덕션은 v5 캐시를 읽고 실호출을 건너뛴다. 감시 변경도 함께 들어간다.
8. launchd 예열 작업을 설치한다.
   - 실행: venv 파이썬 + `warm_law_cache.py`, WorkingDirectory는 저장소, 매일 00:10·06:10과 RunAtLoad.
   - 로그: `~/Library/Logs/laborconsult/law-cache-warm.log`
9. 3일 관측(완료 조건 1, 예열 법령 기준 성공률 95% 이상).

## 9. 위험과 롤백

| 위험 | 대응 |
|---|---|
| 예열 키와 조회 키가 어긋나 효과가 0이다 | 단일 키 함수와 공백 제거 키(R5·R7). 미스 로그로 실측하고, 배포 직후 `ok_cache` 비율을 본다 |
| 옛 판본이 고정된다 | 판본 지정·머리글 검증·상한 3일(R8). 시행일 당일 오전 freshness 점검을 유지한다 |
| 맥이 꺼져 예열이 끊긴다 | 감시 ①(36시간). 만료 상한 3일이 지나면 지금 상태로 되돌아간다(틀린 내용이 아니라 조문 부재) |
| 키워드 규칙 오탐 | 고신뢰 패턴과 반례(R9), 최대 3개, 주제 기본 조문 슬롯과 분리(D8) |
| 캐시 오염(anon 쓰기) | anon 키는 서버 전용이라 위험이 낮다. 다만 만료가 길어져(최장 3일) 오염이 남는 기간이 늘었다. 고정 IP(A) 전환 때 anon 쓰기 축소를 검토한다 |
| `LAW_API_LIVE=off`로 판례·판정문 실시간 조회가 사라진다 | 지금도 프로덕션에서 0건이다. A 방식 전환 때 되살아난다 |
| 롤백 | Vercel env를 지우면(기본 on) 실호출이 다시 실패하는 지금 상태가 된다. PR을 revert하면 구 코드가 v4 키를 읽는데, v4 행은 아무도 쓰지 않으므로 서비스 수준도 지금 상태로 돌아간다. **틀린 내용이 나가지 않는다는 뜻의 안전**이다(검증 L10) |

## 10. 범위 밖

- A 방식(고정 IP)과 그때의 anon 쓰기 축소.
- 판례·판정문 예열(질의가 열려 있음).
- 답변 모델의 유보 성향, 모성보호·성희롱 사실 블록, 30번 정책·면책 고지 중복(Plan §3).
- 의도분석 주제 enum 확장(D9).

## 11. 검증 반영 이력 (design-validator, 2026-10-06, 72점)

| 지적 | 반영 |
|---|---|
| H1 감시 데이터 부재 | D7·D7b·D11 ②, §4.2 v2 구조, R4·R11 |
| H2 판본 경계 | D2, §3.2 판본 지정·머리글 검증·상한 3일, R8 |
| H3 키 정규화 범위 | D3, §3.3 공백 제거 키·약칭 보강·미스 로그, R5 |
| M1 키워드가 2-2 한정 | D8, 2-1로 이동 |
| M2 R10과 D8 모순 | D10, 양쪽 모두 제76조의2·3 제외, R10 재정의 |
| M3 성희롱 판정 두 벌·주제 교체 | D10, 단일 판정·주제 유지 |
| M4 규칙 사실·정밀도 | §5.1(제18조의4, 외국인·임신·경영상 축소, 최대 3, 제13조 삭제), R9 |
| M5 오프라인 호출 | D6, §4.1, R1·R2 |
| M6 예열 실패 미감시 | D11 ①(`laws_failed`·행 감소), 예열 타임아웃 60초 |
| M7 평가·검증 방법 | D13, §6(prod 재현·프로덕션 재실행 금지) |
| M8 깨지는 테스트 | §7 '기존 테스트 정정' |
| L1 파견법 | §3.1 정정 |
| L2 게이트 위치 등 | D5·§3.4·§3.5 |
| L3 정규화 키 기준 중복 제거 | §3.3·§5.2 |
| L4 상태 행 | D12 |
| L5 감시 워크플로 의존성 | §2 |
| L6 Plan 대비 변경 | 아래 표 |
| L7 운영 세부 | §2·§3.5·§8 |
| L8 조문가지번호 "0" | §3.2·R7 |
| L9 비율 임계 근거 | §0 감시 조건 |
| L10 롤백 의미 | §9 |

**Plan 대비 변경**

| Plan | Design | 이유 |
|---|---|---|
| P0-3 주제 enum 확장 | 변경하지 않음(D9) | 분류 흔들림을 피하고, 조문 선택은 D8이 맡는다 |
| P0-3 성희롱 주제로 2-2 | 원 주제 유지 + 괴롭힘 조문 제외(D10) | 주제를 바꾸면 다른 기본 조문을 잃는다 |
| P0-2 인증 오류 알림 | D11 ③으로 반영 | A 방식에서 유효하다(C 방식에서는 실호출이 없음) |
| 완료 조건 3 '프로덕션 재실행' | 로컬 `prod` 재현 비교(D13) | 게시판 노출·감시 표본 오염을 피한다 |
| P0-1 C '실패 시 재시도' | 하루 2회 실행 + 법령별 2회 재시도(D1) | rev1에서 빠져 있었다 |
