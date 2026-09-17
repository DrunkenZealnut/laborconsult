# Report: 노동위원회 판정문 라이브 조회 전환 (nlrc-decisions-corpus)

> **Feature**: 중앙노동위원회 판정문을 번들(360건 제목)+odcloud 우회 검색에서 법제처 API 라이브 조회(44,430건)로 전환
> **PDCA Cycle**: Plan → Design → Do → Check(96%) → Act → Report
> **Period**: 2026-09-14(발견·조사) ~ 2026-09-16(Check·Act)
> **Match Rate**: 96%(82항목 중 78 MATCH·2 PARTIAL·2 FAIL) — Gap 4건 전량 Act로 해소
> **Status**: 구현·검증 완료, 커밋 2건(`b64b805`·`880b9f6`) 푸시 완료. PR 미생성

---

## Executive Summary

### 1.1 프로젝트 개요

| 항목 | 내용 |
|------|------|
| Feature | nlrc-decisions-corpus |
| 시작일 | 2026-09-14 |
| 종료일 | 2026-09-16 |
| 소요 | 3세션일(발견·Plan 확정 1일 + Design·Do 1일 + Check·Act 1일) |

### 1.2 결과 요약

```
┌─────────────────────────────────────────────┐
│  Match Rate: 96% (78/82)                     │
├─────────────────────────────────────────────┤
│  ✅ 완료:     78 / 82 항목                    │
│  ⚠️ 부분:      2 / 82 항목                    │
│  ❌ 초기 미달:  2 / 82 항목 → Act로 전량 해소  │
└─────────────────────────────────────────────┘
```

Plan의 착수 조건(D1~D5) 전항목 충족 후 착수. Check에서 발견된 Gap 4건(High 1·
Low 3)과 Match Rate 밖 추가 결함 2건 모두 같은 세션에서 해소·재검증했다.

### 1.3 Value Delivered

| 관점 | 내용 |
|------|------|
| **Problem** | 노동위원회 판정문 44,430건 중 **360건 제목만** 로컬 번들로 쓰고 있었고, 본문 보강조차 노동위 판정 대신 **제목을 법원판례 API에 재검색해 엉뚱한(그러나 주제는 비슷한) 판례를 빌려오는 우회**였다(`nlrc_cases.py::_search_related_precedent`). 노동위 자체의 판정사항·판정요지는 파이프라인 어디서도 쓰인 적이 없었다. |
| **Solution** | `legal_api.py`의 기존 법원판례 라이브 조회 패턴(`search_precedent`/`fetch_precedent`/`fetch_relevant_precedents` — circuit breaker + L1/L2/L3 캐시)을 `target="nlrc"`로 그대로 미러링해 3개 함수를 신설했다. 사건번호가 부분 마스킹(`2016부해OOO`)돼 있어 인용·캐시 키로 못 쓰는 제약을 캐시 키는 `결정문일련번호`(고유 숫자)로, 인용 표시는 담당부서·자료구분·날짜로 우회했다. RAG 적재는 하지 않는다 — 본문이 평균 560자라 전량 적재해도 BM25 메모리 상한(여유 79MB)을 위협하는 반면, 라이브 조회는 색인 없이 전체가 항상 최신 상태다. 구 번들·odcloud 경로(`nlrc_cases.py`·`refresh_nlrc_cases.py`·`data/nlrc_cases.json`·`ODCLOUD_API_KEY`)는 소비자 전수 확인 후 완전 폐기했다. |
| **Function/UX Effect** | 사용자 인터페이스 변화 없음. 답변에 실리는 노동위 판정 텍스트가 "제목만" 또는 "무관한 법원판례 대리 표시"에서 **노동위 자체 판정사항·판정요지**로 바뀌었다(실 API 확인: 부당해고·부당노동행위·차별시정 3개 질의 전부 정상 응답, 마스킹된 사건번호 미노출). 캐시 히트 시 응답 0.0000초(1차 0.388초 대비) — "필요할 때만 신속하게"라는 이 사이클의 원래 목표가 실측으로 성립했다. |
| **Core Value** | 이미 계약된 API 키(`LAW_API_KEY`)로 접근 가능하던 44,000배 큰 데이터를 별도 인프라(색인·캐시 시스템 신규 구축) 없이 기존 코드 패턴 재사용만으로 끌어왔다. 동시에 이 사이클은 **자기 검증의 한계**를 두 번 드러냈다 — Design 시점에 "하류 소비처 셋 다 무변경"이라 단정했다가 gap-detector가 넷째 소비처(LLM 프롬프트 라벨)를 찾아냈고, 별도로 헌법상 저작권 판단(D2)은 구조적 유비로 확정하되 확인 못 한 한계를 정직하게 기록해뒀다 — 확신과 실제 검증 범위를 구분해 남기는 것이 이 프로젝트의 일관된 태도임을 재확인했다. |

---

## 2. 관련 문서

| 단계 | 문서 | 상태 |
|------|------|------|
| Plan | [nlrc-decisions-corpus.plan.md](../01-plan/features/nlrc-decisions-corpus.plan.md) | ✅ 확정(D1~D5 전항목 해소) |
| Design | [nlrc-decisions-corpus.design.md](../02-design/features/nlrc-decisions-corpus.design.md) | ✅ 확정(§11에 Check 결과 직접 반영) |
| Check | 별도 Analysis 문서 없음 — gap-detector 결과를 Design §11에 직접 기록 | — |
| Report | 본 문서 | ✅ 작성 완료 |

> Check를 별도 `03-analysis` 문서로 분리하지 않은 이유: gap-detector의 대조
> 대상이 Design 문서 자체였고, 발견된 Gap 전부가 Design의 특정 절을 직접
> 수정하는 형태로 해소돼 Design과 분리된 별도 기록이 실익이 적었다(선행
> 사이클 `yeoncha-corpus-cycle`이 Check를 Report에 접은 것과 같은 판단, 이번엔
> Design에 접었다).

---

## 3. Plan 요약

**발단**: `korean-law-mcp` 도입 조사 중 법제처 `nlrc` target(44,430건)이 미사용임을 발견. 별도 조사로 `korean-law-mcp` 자체는 도입 비권장으로 결론(같은 `law.go.kr` API 래퍼, 미수집 1,186건 회수 불가).

**핵심 방향 전환**(2026-09-15): 최초 조사 시점엔 "court_precedents처럼 RAG 적재"를 가정했으나, 실측 3건 프로브(부당해고·부당노동행위·차별시정)로 두 전제가 무너져 **API 라이브 연동**으로 전환했다:

| 실측 | 값 | 함의 |
|---|---|---|
| 사건번호 마스킹 | `2016부해OOO` 등 3건 전부 확인 | `case_no` 기반 원장·인용 설계가 원리적으로 성립 불가 |
| 본문 크기 | 470·486·728자(전부 700자 미만) | 전량 적재해도 예상 청크 ≈ 4.5만 개 — BM25 메모리 상한 직접 위협 |

**D2(저작권) 내부 판단**(2026-09-15): 노동위 판정을 저작권법 제7조 제3호 "행정심판절차 그 밖에 이와 유사한 절차에 의한 의결·결정"에 해당하는 것으로 봤다 — 법원 판결문·헌재결정·훈령예규에 이미 써온 것과 같은 판단 기준. WebSearch 5회·WebFetch 2회로 확인을 시도했으나 노동위원회를 특정해 확인해주는 판례·유권해석은 찾지 못했다는 **한계를 정직하게 병기**했다(구조적 유비이지 확정 선례가 아님).

---

## 4. Design 요약

**핵심 결정**: 새 함수는 신규 모듈이 아니라 `legal_api.py`에 추가(기존 인프라 공유), `nlrc_cases.py`는 대체가 아니라 **명시적 삭제**(소비자 전수 확인 후), 파이프라인 변경은 게이트+호출부 1곳뿐(하류 소비처가 텍스트 블록만 원해 자동으로 맞물릴 것으로 판단 — **이 판단이 Check에서 부분적으로 틀렸음이 드러남**, §6 참고).

**리스크 사전 확인**: L1/L2 캐시가 `str` 전용 계약인데 다중 필드를 담아야 해 JSON 직렬화가 필요했다 — Do 착수 전 `supabase_schema.sql`의 `content TEXT` 컬럼을 직접 확인해 리스크를 해소하고 넘어갔다.

---

## 5. Do 요약

| 산출물 | 내용 |
|---|---|
| 신설 | `legal_api.py`에 `search_nlrc`/`fetch_nlrc_detail`/`fetch_relevant_nlrc` 3함수(`import json` 추가 포함) |
| 교체 | `pipeline.py` "2-1c" 블록 — 게이트 `odcloud_api_key`→`law_api_key`, 호출부 `search_nlrc_with_details`→`fetch_relevant_nlrc` |
| 삭제 | `nlrc_cases.py`·`refresh_nlrc_cases.py`·`data/nlrc_cases.json`·`AppConfig.odcloud_api_key` |
| 문서 정리 | `.env.example`·`CLAUDE.md` 3곳·`archive_precedents.py` MANIFEST 주석·`wage_calculator/pipeline-visualization.html`(Design에 없었으나 grep으로 발견해 반영) |
| 테스트 | `test_legal_api_nlrc`·`test_legal_api_nlrc_cache_key`·`test_pipeline_nlrc_gate` 3종 신설, `test_nlrc_bundle` 삭제 |

**검증**: CI 6종 통과 + 실 API 라이브 스모크(3질의, 마스킹 미노출 코드 단언) + 캐시 히트 확인(0.388초→0.0000초).

---

## 6. Check 결과 및 Act

gap-detector Match Rate **96%**(82항목 중 78 MATCH). 설계에는 있는데 구현에 없는 항목 **0건** — Plan·Design의 모든 산출물·비범위·실행순서가 코드로 확인됐다. Gap 4건 전량 Act로 해소:

| ID | 심각도 | 현상 | 조치 |
|---|---|---|---|
| **GAP-1** | **High** | `pipeline.py:1925`의 LLM 프롬프트 라벨이 데이터 출처 교체 후에도 `"공공데이터포털 조회"`를 그대로 주장. Design §3.2가 하류 소비처를 **셋**(`_build_sources_payload`·`_citation_source_hits`·프런트 라벨)으로 단정했으나 실제론 **다섯**이었다 | `(법제처 국가법령정보센터 조회)`로 교체 + Design §3.2에 누락 소비처 2곳 기록 |
| GAP-2 | Low | 판례 아카이브 MANIFEST가 삭제된 `data/nlrc_cases.json`과 사라진 설계 절("§5.3")을 계속 가리킴. 생성 소스는 이미 고쳐져 있었으나 산출물이 재생성 전이었다 | `archive_precedents.py build` 재실행, `verify` V0~V8 전체 재통과 |
| GAP-3 | Low | GAP-1과 동일 원인의 문서 버전 — `wage_calculator/pipeline-visualization.html`의 **두 번째** 노드(Do 때 누락)가 구 라벨 유지 | 동일 라벨로 교체 |
| GAP-4 | Low | Design §5가 "실답변 샘플로 판단"하겠다며 유보한 프롬프트 지시 결정이 명시적으로 닫히지 않음 | 근거와 함께 "불요"로 확정 기록 |

**Match Rate가 못 잡은 것(설계·구현 일치이나 개선) 2건**도 같은 세션에서 발견·수정:

1. 헤더가 `[중앙노동위원회 판정]`으로 고정돼 있어 **지방노동위 사건**(실측 다수, Plan §1.2가 이미 "지방노동위까지 포함"이라 명시했던 사실을 Design 때 놓침)에서 바로 뒤 담당부서 표기와 상충. `[노동위원회 판정]`으로 수정 후 **실 API로 재확인**.
2. `fetch_nlrc_detail`의 L1/L2 캐시 읽기(`json.loads`)가 `try` 블록 **밖**에 있어 비-JSON 값이 섞이면 예외가 새어 NLRC 블록 전체가 조용히 사라질 수 있는 경로(fail-open이라 크래시는 안 나지만 원인 진단이 흐려짐). `try`로 좁혀 캐시 미스로 강등.
3. **테스트 하나가 실제 함수를 호출하지 않고 있었다.** `test_legal_api_nlrc`가 픽스처 XML을 `ET`로 직접 파싱만 해 필드명을 검증했을 뿐 `search_nlrc`/`fetch_nlrc_detail` 자체는 한 번도 부르지 않았다 — 이 사이클 초반(T30-d/e, 별건인 crawl-precedent-production-ns) 겪었던 것과 **같은 클래스의 함정**(소스 검사·독립 픽스처 검증은 실제 호출의 대체가 되지 못함). `_http.get`을 페이크로 바꿔 실제 함수를 호출하도록 승격하고, 이 세션에서 이미 라이브로 캐싱해둔 실제 ID(15255)와의 우연한 캐시 히트를 피하려 합성 ID를 썼다.

전부 재검증 완료 — CI 6종 재통과, `archive_precedents.py verify` 재통과, 헤더 수정 실 API 재확인, 신규 테스트(페이크 HTTP 버전) 단독 재실행 통과.

---

## 7. 산출물 및 커밋

```
b64b805 feat: NLRC 판정문을 법제처 API 라이브 조회로 연동 — 번들+odcloud 폐기
880b9f6 fix: nlrc-decisions-corpus Check 반영 — 출처 라벨·헤더·캐시 예외 4건
```

두 커밋 모두 `origin/feat/crawl-precedent-production-ns`에 푸시됨. PR 미생성(요청 시 생성).

---

## 8. 품질 지표

| 항목 | 결과 |
|---|---|
| CI 6종(`test_offline_units`·`test_wage_golden`·`test_pipeline_wiring`·`test_abuse_guard`·`test_llm_fallback`·`test_precedent_ingest`) | ✅ 전량 통과(Do·Act 양쪽에서 재확인) |
| `archive_precedents.py verify`(V0~V8) | ✅ 통과 |
| 실 API 라이브 스모크 | ✅ 3질의(부당해고·부당노동행위·차별시정), 마스킹 미노출 확인 |
| 캐시 동작 | ✅ 1차 0.388초 → 2차 0.0000초(값 동일) |
| gap-detector Match Rate | 96%(1차) → Gap 4건 + 추가 2건 해소 후 재검증 완료 |

---

## 9. 교훈 및 회고

### 9.1 잘된 것 (Keep)

- **기존 패턴 미러링이 실제로 리스크를 줄였다.** `legal_api.py`의 court precedent 경로(circuit breaker·3단 캐시·ThreadPoolExecutor)를 그대로 복제해, 신규 인프라 없이 44,430건 규모를 다뤘다. 새로 설계했다면 캐시 계층·서킷브레이커를 처음부터 만들어야 했을 것이다.
- **구현 전 재검토로 스스로 잘못된 권고를 정정했다**(GAP-3, 별건 crawl-precedent-production-ns 사이클이지만 같은 세션·같은 방법론). 가장 가까운 형제 코드를 실제로 열어보고 원 계획을 뒤집는 습관이 이번에도 유효했다.
- **저작권 판단의 한계를 숨기지 않고 기록했다**(Plan §5.1). "구조적 유비이지 확정 선례가 아니다"를 명시해, 다음에 이 판단을 재검토할 사람이 무엇이 검증됐고 무엇이 안 됐는지 바로 알 수 있게 했다.

### 9.2 개선 필요 (Problem)

- **"하류 소비처 불변"을 주장할 때 알고 있는 소비처만 나열하고 다 세었다고 착각했다.** GAP-1이 그 결과다 — `grep -n "nlrc_text"`을 전수로 돌렸다면 Design 단계에서 바로 잡혔을 실수를, Check(gap-detector)가 대신 잡았다.
- **Design이 작성한 테스트 코드를 그대로 구현에 옮기면서, 그 테스트 자체의 약점(실제 함수 미호출)을 이 세션 초반에 이미 배운 교훈에도 불구하고 반복했다.** 교훈을 "알고 있다"는 것과 "매 순간 적용한다"는 것 사이에 거리가 있었다.
- **헤더 문구(`중앙노동위원회`)를 Plan 자신이 이미 명시한 사실(지방노동위 포함)과 대조하지 않고 그대로 코드에 옮겼다.** Design 코드 작성이 Plan 재독 없이 진행된 결과다.

### 9.3 다음에 시도할 것 (Try)

- **"소비처 불변" 같은 광범위한 불변 주장을 할 때는 `grep -n`의 전체 출력 개수를 문서에 직접 적어 근거로 남긴다** — "셋"이라고 쓰는 대신 "grep 결과 5곳, 그중 3곳만 검토"처럼 세는 과정 자체를 기록하면 누락이 스스로 드러난다.
- **Design 코드를 작성할 때 Plan의 실측 데이터(이 경우 "지방노동위까지 포함")를 다시 펼쳐 대조하는 단계를 명시적으로 넣는다.**
- **"이전에 배운 함정"을 코드 작성 체크리스트 항목으로 명문화한다** — 알고 있는 것과 적용하는 것 사이의 거리를 줄이는 유일한 방법은 그때그때 상기시키는 절차뿐이었다.

---

## 10. 다음 단계

### 10.1 즉시

- [ ] PDCA 아카이브(`docs/archive/2026-09/nlrc-decisions-corpus/`)
- [ ] PR 생성 여부 결정(요청 대기)

### 10.2 다음 PDCA 사이클 후보

| 항목 | 우선순위 | 비고 |
|---|---|---|
| 프로덕션 관찰 — NLRC 라이브 조회 발동 빈도·캐시 히트율 | 관찰 | 별도 사이클 불요, 로그 누적 후 판단 |
| `search_nlrc()`의 `display`(max_results) 확장 여부 | Low | 현재 3건 유지, 근거 있는 수요 발생 시 재검토 |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-09-16 | 완료 보고서 작성 | Claude Sonnet 5 (PDCA) |
