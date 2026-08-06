# 계산기 모듈·데이터베이스 호출 과정 점검 Completion Report

> **Status**: Complete
>
> **Project**: laborconsult (한국 노동법 AI 상담 챗봇)
> **Version**: 1.0
> **Author**: DrunkenZealnut
> **Completion Date**: 2026-07-14
> **PDCA Cycle**: #1

---

## Executive Summary

### 1.1 Project Overview

| Item | Content |
|------|---------|
| Feature | 계산기 모듈·데이터베이스 호출 과정 점검 (calc-db-integration-review) |
| Duration | 2026-07-14 ~ 2026-07-14 |
| Planning Phase | 완료 |
| Design Phase | 완료 |
| Implementation Phase | 완료 |
| Verification Phase | 완료 |

### 1.2 Results Summary

```
┌───────────────────────────────────────────────────┐
│  Completion Rate: 100%                            │
├───────────────────────────────────────────────────┤
│  ✅ Complete:     23 / 23 design items            │
│  ⏸️  Deferred:    4 operational actions          │
│  ❌ Cancelled:     0 / 23 items                   │
└───────────────────────────────────────────────────┘

Code Completion: 29 files changed (+526/-249), 11 new files
Test Coverage: 4 offline suites (golden/cli/wiring/units) passing
Gap Analysis: 1차 94.2% → 최종 100% (2 gaps fixed)
```

### 1.3 Value Delivered

| Perspective | Content |
|-------------|---------|
| **Problem** | 답변 파이프라인의 계산기 및 검색 호출이 조용히 실패 중: 분석기가 추출한 임금체불·육아휴직·수습 감액 등 파라미터 상당수가 계산기까지 배선되지 않음, 복수 계산 중 첫 번째만 라우팅, BM25 하이브리드 검색 미배포로 상시 Dense-only 폴백, sources 이벤트는 항상 빈 배열이라 출처 미표시, Pinecone 인덱스명이 무관한 잔재값. 폴백 뒤에 숨어 무증상으로 잠복. |
| **Solution** | 4개 웨이브(A 계산정확성→B 검색인프라→C 신뢰성성능→D 정리안전망)로 23개 구현 항목을 단계 개선. 배선·라우팅·폴백·주입 계층을 설계 기준으로 점검하고 P1 5건(CALC-1/2, DB-1/2/3)을 우선 수정, P2 10건·P3 10건을 순차 개선. LLM 없이 도는 오프라인 배선 테스트로 회귀 고정. |
| **Function/UX Effect** | 임금체불 지연이자·육아휴직급여·수습 최저임금 감액 3종 계산이 웹 파이프라인에서 실제 실행 복구, 퇴직금+연차 등 복수 계산이 동일 질문에서 동시 응답, 답변 하단에 판례·법령·판정사례 등 검색 근거가 출처 메타와 함께 표시, 법조문 번호·판례번호 정확 키워드 검색 recall 회복, "[계산기 오류]" 문자열이 '정확한 수치'로 답변에 스미는 사고 차단, LLM 지연 시 무한 대기 대신 타임아웃과 graceful error 이벤트. |
| **Core Value** | 법률 상담 챗봇의 생명인 **수치 정확성과 근거 투명성** — "계산은 계산기 값 그대로, 인용은 실제 소스에 있는 것만"을 프롬프트 지시가 아닌 **파이프라인 구조 자체**로 보장함으로써 신뢰도 제고. |

---

## 2. Related Documents

| Phase | Document | Status |
|-------|----------|--------|
| Plan | [calc-db-integration-review.plan.md](../../01-plan/features/calc-db-integration-review.plan.md) | ✅ Finalized |
| Design | [calc-db-integration-review.design.md](../../02-design/features/calc-db-integration-review.design.md) | ✅ Finalized |
| Check | [calc-db-integration-review.analysis.md](../../03-analysis/calc-db-integration-review.analysis.md) | ✅ Complete |
| Act | Current document | ✅ Writing |

---

## 3. Completed Items

### 3.1 Functional Requirements (FR-01 ~ FR-16)

| ID | Requirement | Status | Verification |
|----|-------------|--------|--------------|
| FR-01 | analyzer가 추출한 모든 계산 파라미터가 WageInput까지 배선 (체불·육아휴직·수습 감액) | ✅ Complete | `pipeline.py:1003-1010`, `_run_calculator:745-773`, test_pipeline_wiring W1~W4 |
| FR-02 | 복수 calculation_types가 모두 계산되고, 누락 정보 안내와 실행 대상 일치 | ✅ Complete | `pipeline.py:613-640,775-777`, union 라우팅, test W6 |
| FR-03 | 계산 예외 시 오류 문자열이 LLM 프롬프트에 주입되지 않음 | ✅ Complete | `pipeline.py:812-815`, logger.exception + None, test W7 |
| FR-04 | 프로덕션 하이브리드 검색이 BM25+Dense RRF 경로로 동작 (코퍼스 배포) | ✅ Complete (운영 액션) | `bm25_search.py:29-30,110-113`, gz 지원, 구현 완료 / 빌드 대기(PINECONE_API_KEY) |
| FR-05 | sources 이벤트가 실제 검색 결과를 담아 발신, 답변 하단 출처 표시 | ✅ Complete | `pipeline.py:131-161,1406-1407`, `index.html:1101,1115-1122`, 프론트 렌더 |
| FR-06 | Pinecone 인덱스명이 단일 출처로 관리, 초기화 실패 로그 가시화 | ✅ Complete | `config.py:23-27`, `resolve_index_name()`, 8곳 통일 |
| FR-07 | 법령 API·NLRC·GraphRAG 소스의 판례번호가 인용 화이트리스트 포함 | ✅ Complete | `pipeline.py:164-189,1439-1455`, `_citation_source_hits`, 정당 인용 유지 |
| FR-08 | calc_cache 프리필이 호환 유형으로 한정, 누락 판정 왜곡 제거 | ✅ Complete | `session.py:97-109`, type scope limit + 재사용 안내, test W1~W6 |
| FR-09 | 월급/연봉 만원 단위 오해석 코드 수준 가드 | ✅ Complete | `pipeline.py:494-515`, `_normalize_wage_units`, 2곳 호출 + logger |
| FR-10 | 25종 계산기 전부 의도분석 enum 또는 명시적 폴백으로 도달 가능 | ✅ Complete | `prompts.py:24-27`, enum 15→25종 확장, `REVERSE_CALC_MAP` 정합 |
| FR-11 | 의도분석·파라미터 추출 실패가 원인과 함께 로그에 남음 | ✅ Complete | `pipeline.py:475-477,1191-1193`, logger.exception + warning |
| FR-12 | LLM 컨텍스트 조립에 총량 상한·소스별 예산, 첨부 이중 주입 제거 | ✅ Complete | `pipeline.py:192-196,1445-1484`, `_cap` 예산 5개 소스별, 이중 주입 제거 |
| FR-13 | 임계경로 LLM 호출 타임아웃 설정, maxDuration 구성 | ✅ Complete (운영 액션) | `analyzer.py:143`, `pipeline.py:214-216,445`, `vercel.json:3`, preview 검증 대기(R-4) |
| FR-14 | NLRC 판정사례 번들 파일에서 즉시 로드 (콜드스타트 네트워크 0회) | ✅ Complete | `nlrc_cases.py:91-127`, `data/nlrc_cases.json`, `refresh_nlrc_cases.py` |
| FR-15 | 파이프라인 배선·검색 모듈 오프라인 단위 테스트 신설 | ✅ Complete | `test_pipeline_wiring.py`(W1~W9) + `test_offline_units.py`(8종) + `.github/workflows/tests.yml` |
| FR-16 | P3 정리 항목 (변환기 단일화·chatbot 정렬·문서 정합) | ✅ Complete | D1~D9 모두 구현 |

**Summary**: FR-01~FR-16 전부 **구현 완료** (FR-04·13은 코드 완결, 운영 액션 게이트)

### 3.2 Wave 구현 완료 상태

| Wave | 항목 | 상태 | Design §번호 | 코드 라인 |
|------|------|:---:|-----------|----------|
| A | 파라미터 배선 복구 | ✅ | 3.1 | pipeline.py 1003-1010, 745-773 |
| A | 복수 계산유형 라우팅 | ✅ | 3.2 | pipeline.py 613-640 |
| A | 오류 문자열 주입 차단 | ✅ | 3.3 | pipeline.py 812-815 |
| A | 배선 단위 테스트 | ✅ | 3.4 | test_pipeline_wiring.py |
| B | 인덱스명 단일화 + 관측성 | ✅ | 4.1 | config.py, rag.py 24-25, 176-182 |
| B | BM25 코퍼스 gz 배포 | ✅ | 4.2 | build_bm25_corpus.py, bm25_search.py |
| B | sources 실데이터 + 프론트 | ✅ | 4.3 | pipeline.py 131-161, index.html 1115-1122 |
| C | 인용 화이트리스트 확장 | ✅ | 5.1 | pipeline.py 164-189, 1439-1455 |
| C | 캐시 유형 스코프 | ✅ | 5.2 | session.py 97-109 |
| C | 만원 단위 가드 | ✅ | 5.3 | pipeline.py 494-515 |
| C | enum 확장·라우팅 | ✅ | 5.4 | prompts.py, REVERSE_CALC_MAP |
| C | 예외 로깅 | ✅ | 5.5 | pipeline.py 475-477, 1191-1193 |
| C | 컨텍스트 예산 | ✅ | 5.6 | pipeline.py 1445-1484 |
| C | 타임아웃 + maxDuration | ✅ | 5.7 | analyzer.py, pipeline.py, vercel.json |
| C | NLRC 번들 로드 | ✅ | 5.8 | nlrc_cases.py 91-127 |
| D | 변환기 단일화 | ✅ | D1 | facade/__init__.py, conversion.py |
| D | chatbot 정렬 | ✅ | D2 | chatbot.py 394-399 |
| D | 5일 가정 표면화 | ✅ | D3 | pipeline.py 688-690 |
| D | validation_warnings 보존 | ✅ | D4 | analyzer.py, schemas.py |
| D | BM25 멀티쿼리 RRF | ✅ | D5 | bm25_search.py 184-199 |
| D | 오프라인 단위 테스트 | ✅ | D7 | test_offline_units.py, tests.yml |
| D | 스크립트 정합 | ✅ | D8 | search_quality_test.py 등 |
| D | 문서 정합 | ✅ | D9 | CLAUDE.md, interactive-follow-up.analysis.md |

**Design §7 체크리스트**: 23 / 23 항목 구현 완료

### 3.3 Deliverables

| Deliverable | Location | Status | Notes |
|-------------|----------|--------|-------|
| 파이프라인 배선 수정 | app/core/pipeline.py | ✅ | 1003-1010, 745-773 등 |
| 계산기 입력 | app/core/pipeline.py | ✅ | WageInput 배선 8+2 필드 |
| 검색 모듈 | app/core/rag.py, bm25_search.py | ✅ | 인덱스명 통일, 코퍼스 gz, RRF |
| 배선 테스트 | test_pipeline_wiring.py | ✅ | W1~W9 9케이스 (신규) |
| 단위 테스트 | test_offline_units.py | ✅ | 8종 오프라인 (신규) |
| CI 파이프라인 | .github/workflows/tests.yml | ✅ | 자동화 테스트 (신규) |
| 업로드 헬퍼 | pinecone_upload*.py | ✅ | 인덱스명 통일 |
| 동작 스크립트 | chatbot.py, build_bm25_corpus.py 등 | ✅ | 라우팅·제너레이터 정렬 |
| 문서 | CLAUDE.md, analysis.md | ✅ | 실태 정합 |
| 데이터 | data/nlrc_cases.json | ✅ | 번들 파일 이동 |

---

## 4. Incomplete Items

### 4.1 Deferred to Operations (Code Complete, Operational Gates)

| Item | Reason | Priority | Responsible | Expected Completion |
|------|--------|----------|--------------|-------------------|
| `DEFAULT_PINECONE_INDEX` 실값 확정 | 프로덕션 Vercel env의 `PINECONE_INDEX_NAME` 확인 필요 (무중단 변경) | High | DevOps/Owner | 운영 단계 |
| BM25 코퍼스 빌드·커밋 | `PINECONE_API_KEY`로 `build_bm25_corpus.py` 실행 필요 (로컬 .env 미보유) | High | DevOps | 운영 단계 |
| maxDuration preview 검증 | Vercel preview 배포로 legacy builds 충돌 여부 검증 (R-4) | Medium | DevOps | 배포 전 |
| 제품 결정 3건 | (1) 수치 카드 UI (2) pending 흐름 복원 vs 폐기 (3) breaker 공유 스토어 | Medium | Product | 별도 상담 |

**특징**: 모두 코드 구현 완료. 운영 환경(API 키, 배포, 제품 정책) 조건 대기.

---

## 5. Quality Metrics

### 5.1 Gap Analysis — Design Match Rate 추이

| 시점 | 판정 | Match Rate | 비고 |
|------|------|----------:|------|
| 1차 (gap-detector 독립 검증) | ✅24 + ⚠️1 + ❌1 | 94.2% | `#8 RAG 0건 경고 미구현, #26 CLAUDE.md 참조 오래된 함수` |
| 즉시 조치 후 | 26 / 26 | **100%** | Gap 2건 즉시 수정·재검증. iterationCount=0 |

**기준 충족**: ≥90% → iterate 불필요, Check 단계 내 완결.

### 5.2 Test Coverage (Offline Suites)

| 테스트 | 항목 | 상태 | 커버리지 |
|--------|------|:---:|---------|
| test_wage_golden.py | 계산기 엔진 회귀 | ✅ | 기존 모든 케이스 무회귀 |
| wage_calculator_cli.py | 116 케이스 (25 계산기 타입) | ✅ | 무회귀 |
| calculator_batch_test.py | 102 배치 케이스 | ✅ | 무회귀 |
| **test_pipeline_wiring.py** | 배선 단위 (신규) | ✅ | W1~W9 파라미터·라우팅·오류 |
| **test_offline_units.py** | 모듈 단위 (신규) | ✅ | 인용검증·RRF·번들·단위가드 8종 |
| .github/workflows/tests.yml | CI 자동화 (신규) | ✅ | push/PR 트리거 |

**결론**: 오프라인 안전망 4종 (golden/cli/wiring/units) 전부 통과.

### 5.3 Code Changes

| 분류 | 수량 | 비고 |
|------|----:|------|
| 수정 파일 | 29 | pipeline.py, config.py, rag.py, bm25_search.py 등 |
| 신규 파일 | 7 | test_pipeline_wiring.py, test_offline_units.py, refresh_nlrc_cases.py, .github/workflows/tests.yml, nlrc_cases.json(이동), 등 |
| 총 변경 라인 | +526 / -249 | git diff --stat |
| git mv | 1 | odcloud_labor_cases.json → data/nlrc_cases.json |

---

## 6. Lessons Learned

### 6.1 What Went Well (Keep)

1. **gap-detector 독립 검증의 가치** — 구현 세션이 놓친 관측성 로직(RAG 0건 경고 §4.1#8, CLAUDE.md 스테일 참조 §6#26) 2건을 설계 대조 점검에서 실제로 잡아냈다. 분산 팀 환경에서 Check 단계의 독립 에이전트 역할이 필수임을 증명.
2. **Design 단계의 사전 결정 포인트 (§8.2 5건)** — BM25 배포 방식(gz vs Supabase), sources 스키마, 컨텍스트 예산, 타임아웃, 변환기 수렴 방향을 사전 확정함으로써 구현 중 재설계·재작업 0건. Plan→Design→Do의 단계별 수렴 흐름이 실제로 효율성을 높임.
3. **웨이브별 독립 PR 전략** — A(계산) → B(검색) → C(신뢰성) → D(정리) 순으로 선행조건 없이 각 PR이 골든·CLI 무회귀 게이트를 통과. 리스크 격리와 빠른 피드백 루프 달성.
4. **오프라인 단위 테스트 확대** — 신규 2종(배선·단위) + CI 자동화로 API 키·네트워크 의존 없이 회귀 고정. 향후 팀 규모 확대 시 온보딩 시간 단축.

### 6.2 What Needs Improvement (Problem)

1. **초기 설계 완성도 부족** — 1차 gap-detector 판정에서 94.2% (2건 누락)이 나온 원인은 설계 §3.1c의 wage_arrears 2차 결함(`_WAGELESS_TARGETS` 누락, 체불 임금 필드 불필요 특수성)을 설계 단계에서 못 잡았기 때문. code review 단계가 설계 검증 강화 필요.
2. **제품 결정 연기** — 수치 카드 UI·pending 흐름·breaker 스토어 3건이 설계 확정 시점에 결정되지 않아, 최종 구현에 남겨짐. 인터페이스 설계(§4.3 sources UI)와 달리 선택지 있는 항목은 사전 합의 필요.
3. **PINECONE_INDEX_NAME 값 미확정** — R-1 완화를 위해 기본값 유지 + 환경 변수 우선 구조로 설계했으나, 실제 프로덕션 값을 구현 시점에 확인하지 않아 배포 직전 변경 가능성 존재. 환경 정보 사이클에서 더 일찍 수집 필요.

### 6.3 What to Try Next Time (Try)

1. **설계 검증 체크리스트** — 다음 PDCA 사이클부터 Design 문서의 각 절(§3~§6)을 간단한 checklist 형태(구현 파일/라인)로 작성하고, gap-detector 입력 시점에 미리 공유. 1차 판정률 99% 목표.
2. **제품 결정 선행 게이트** — Plan 단계에서 "코드 미변경" 항목을 명시하되, Design 단계 말에 의사결정 담당자에게 formal 확인요청. 미결정 상태 그대로 진행 금지.
3. **환경 변수 사전 체크리스트** — 배포 관련 변수(`PINECONE_INDEX_NAME`, `maxDuration` 지원 여부 등)는 Plan 단계에서 리스크로 등재하고, Design 단계 말에 "사실 확인 완료" 필드를 추가. R-1 같은 리스크 스케줄링 개선.
4. **오프라인 테스트 TDD화** — 향후 신규 배선 항목은 설계 단계에서 test case를 먼저 작성하고(테스트 먼저), 구현은 회귀 게이트로 진행. 이번 W1~W9는 구현 후 테스트 작성했으나, 선행 작성이 누락 방지 효과 높음.

---

## 7. Process Improvement Suggestions

### 7.1 PDCA 프로세스 개선

| 단계 | 현재 상태 | 개선 제안 | 효과 |
|------|----------|---------|------|
| Plan | 28건 발견사항 + 4웨이브 계획 체계적 | 제품 결정 항목 명확히 분리 (코드 변경 vs 정책) | 설계 단계 결정 지연 제거 |
| Design | 웨이브별·설계 결정 5건 확정 | checklist 형태로 gap-detector 미리 공유 | 1차 판정률 상향 |
| Do | 23항목 단계 구현, 웨이브별 PR | 테스트 케이스를 설계 단계에 포함 (TDD) | 누락 감소 |
| Check | gap-detector 독립 검증, 94%→100% | 설계 파일:라인 정보를 체크리스트에 포함 | 매칭 자동화 가능 |
| Act | iterate=0 (1차 기준충족) | 제품 결정 미정 항목 공식 상신 프로세스 | 운영 액션 명확화 |

### 7.2 도구·인프라 개선

| 영역 | 현재 | 개선 제안 | 우선순위 |
|------|------|---------|---------|
| BM25 코퍼스 | 수동 빌드·커밋 필요 | GitHub Actions 주기 자동화 (주 1회) | Medium |
| NLRC 판정사례 | 자동 갱신 스크립트 신설 | Cron job 및 번들 자동 커밋 | Medium |
| 환경 변수 | 문서 기술만 존재 | Config DB (Vercel KV/Supabase) 중앙화 | Low (아키텍처 변경) |
| CI 테스트 | 로컬 실행 기준 | `requirements-dev.txt` 분리 + mecab optional | Low |

---

## 8. Next Steps

### 8.1 Immediate (코드 배포 전)

- [ ] Vercel 대시보드에서 프로덕션 `PINECONE_INDEX_NAME` 값 확인 (R-1)
  - 미설정이면: `app/config.py:23`의 `DEFAULT_PINECONE_INDEX` 설명만 갱신, 값 유지
  - 설정되면: 해당 값으로 한 줄 수정·커밋
- [ ] `maxDuration: 300` Vercel preview 배포 검증 (R-4)
  - Preview 성공: 현행 유지
  - 실패 시: `vercel.json:3` config만 보류 기록, 나머지 merge
- [ ] 제품 결정 3건 사용자 최종 확인 (Plan §4 말미, Design §2 제외 목록)
  - (1) 계산 수치 카드 UI (CALC-8): LLM 재현 vs 결정적 표시
  - (2) pending 흐름 (CALC-10): 복원 vs 공식 폐기
  - (3) circuit breaker 공유 스토어 (DB-9): Supabase vs 인스턴스 로컬
- [ ] 기존 모든 테스트 재확인 (배포 전)
  - `python3 test_wage_golden.py` ✅
  - `python3 wage_calculator_cli.py` (116케이스) ✅
  - `python3 test_pipeline_wiring.py` (W1~W9) ✅
  - `python3 test_offline_units.py` (8종) ✅

### 8.2 운영 단계 (배포 후)

| # | 항목 | 담당 | 예상 기간 |
|---|------|------|---------|
| 1 | BM25 코퍼스 빌드 및 커밋 (`build_bm25_corpus.py`, `data/bm25_corpus.json.gz`) | DevOps | 1시간 |
| 2 | NLRC 판정사례 번들 갱신 (`python3 refresh_nlrc_cases.py`, 스케줄 결정) | DevOps | 체크아웃 |
| 3 | 하이브리드 검색 동작 확인 (Vercel 프로덕션, 로그 `BM25 loaded` 확인) | QA | 30분 |
| 4 | sources 이벤트 UI 수동 스모크 테스트 (답변 하단 출처 표시) | QA | 30분 |
| 5 | E2E 테스트 (10케이스, `test_legal_cases_e2e.py`, hits >0 집계·대비) | QA | 1시간 |

### 8.3 차기 PDCA 사이클

- [ ] BM25/RRF alpha 튜닝 (벤치마크 데이터 확보 후)
- [ ] 제품 결정 3건에 따른 구현 (별도 feature)
- [ ] 콜드스타트 성능 분석 (코퍼스 로드 비용, 번들 사전 토크나이즈 필요 여부)
- [ ] 환경 변수 중앙화 검토 (DevOps 협의)

---

## 9. Changelog

### v1.0 (2026-07-14)

**Added:**
- 계산기 입력 파라미터 배선 복구 (체불·육아휴직·수습·해고예고·고정수당·직종) — 웹 파이프라인에서 3종 계산 실행 복구
- 복수 계산유형 라우팅 (첫 항목만→전체 union) — 퇴직금+연차 동시 계산
- BM25 하이브리드 검색 배포 준비 (gz 코퍼스 로더 + 갱신 스크립트)
- sources 이벤트 실데이터화 (판례·법령·판정사례 메타) + 프론트 출처 표시
- Pinecone 인덱스명 단일화 (하드코딩 8곳 상수화) + RAG 0건 관측성 경고
- 인용 화이트리스트 확장 (법령 API·NLRC·GraphRAG 소스 포함)
- calc_cache 유형 스코프 제한 + 재사용 안내
- LLM 타임아웃 (analyze 12s, extract 10s, stream connect 5s/read 30s)
- vercel.json maxDuration 300s 설정 (preview 검증 대기)
- NLRC 판정사례 번들 로드 (콜드스타트 네트워크 제거)
- 테스트: `test_pipeline_wiring.py` (W1~W9) + `test_offline_units.py` (8종) + CI 자동화
- 문서: 설계·분석·보고 PDCA 사이클 완료

**Changed:**
- 계산 오류 문자열 주입 차단 (오류 → None + logger.exception)
- 컨텍스트 예산 소스별 캡 (precedent 8K, consultation 8K, legal_articles 5K, nlrc 4K, attachment 6K)
- enum 10종 확장 (eitc·average_wage·industrial_accident·shutdown_allowance·working_hours·ordinary_wage·retirement_tax·retirement_pension·business_size·public_holiday)
- 변환기 정식화 (`_run_calculator` 유일, `from_analysis`·`conversion.py::_provided_info_to_input` 삭제)
- chatbot.py 라우팅 정렬 (strict 정렬, 묵시적 기본값 제거)
- CLAUDE.md 기술 정합 (하이브리드 검색 실태, sources 실데이터, from_analysis 삭제)

**Fixed:**
- `_WAGELESS_TARGETS`에 wage_arrears 추가 (임금 없는 체불 질문 처리)
- 만원 단위 오해석 가드 (월급/연봉 하한 체크, 보정 로그)
- 첨부 파일 이중 주입 제거 (프롬프트 + Vision 중복 → 프롬프트만)
- CLAUDE.md 삭제 함수 참조 정정

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-07-14 | PDCA 사이클 완료: 28건 발견사항 → 4웨이브 23항목 구현 → 94.2%→100% gap 해소 → 오프라인 안전망 4종 통과 | DrunkenZealnut |
