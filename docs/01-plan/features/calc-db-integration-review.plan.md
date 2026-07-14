# 계산기 모듈·데이터베이스 호출 과정 점검 Plan (calc-db-integration-review)

> **Summary**: 사용자 질문 → 답변 생성 파이프라인에서 **계산기 모듈 호출 경로**(의도분석→라우팅→파라미터 변환→계산→결과 주입)와 **데이터베이스/외부지식 호출 경로**(RAG·법제처 법령 API·판례·NLRC 판정사례·GraphRAG)를 코드 수준으로 정밀 감사하여 28건의 결함·공백(P1 5건)을 확정하고, 4개 웨이브(계산 정확성→검색 인프라→신뢰성/성능→정리·안전망)로 개선을 계획한다.
>
> **Project**: laborconsult
> **Author**: DrunkenZealnut
> **Date**: 2026-07-14
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 답변 파이프라인의 모듈 호출이 **조용히 실패**하고 있다 — analyzer가 추출한 계산 파라미터 상당수(체불임금·육아휴직·수습감액 등)가 계산기까지 배선되지 않아 해당 계산이 사실상 미작동, 복수 계산 요청은 첫 유형만 계산, BM25 하이브리드 검색은 코퍼스 미배포로 상시 Dense-only, `sources` 이벤트는 항상 빈 배열이라 출처 표시가 사장, Pinecone 기본 인덱스명은 무관한 잔재값. 전부 폴백 뒤에 숨어 무증상으로 잠복 |
| **Solution** | 2-트랙 사전 감사(계산기 경로 13건 + DB/검색 경로 11건 + 테스트·관측성 공백 3건 + 문서 스테일 1건)로 발견사항을 파일:라인 근거와 함께 확정하고, 4개 웨이브 — **A** 계산 정확성(P1 배선·라우팅) → **B** 검색 인프라(인덱스명·BM25·출처 표시) → **C** 신뢰성/성능(인용 검증 사각지대·캐시 오염·타임아웃·컨텍스트 캡) → **D** 정리·회귀 안전망 — 로 단계 개선. LLM 없이 도는 오프라인 배선 테스트로 회귀 고정 |
| **Function/UX Effect** | 미작동 계산 3종(임금체불 지연이자·육아휴직급여·수습 최저임금 감액) 복구, 퇴직금+연차 등 복수 계산 동시 응답, 답변 하단에 판례·법령 실제 출처 표시, 법조문 번호·판례번호 키워드 검색 recall 회복, "[계산기 오류]" 문자열이 '정확한 수치'로 둔갑해 답변에 스미는 사고 차단, LLM 지연 시 무한 대기 대신 우아한 실패 |
| **Core Value** | 법률 상담 챗봇의 생명인 **수치 정확성과 근거 투명성** — "계산은 계산기 값 그대로, 인용은 실제 소스에 있는 것만"을 프롬프트 지시가 아닌 **파이프라인 구조**로 보장 |

---

## 1. 개요

### 1.1 목적

`process_question()`(app/core/pipeline.py)이 답변을 만들 때 의존하는 두 축 — ① 임금계산기 모듈 호출, ② 지식소스(Pinecone RAG·법제처 법령 API·판례·NLRC 판정사례·GraphRAG·지식모듈) 호출 — 의 **호출 과정 자체**를 점검하고, 유실·사문화·오류전파 결함을 우선순위에 따라 수정한다. 계산기 내부 산식이나 코퍼스 콘텐츠 품질이 아니라 **배선(wiring)·라우팅·폴백·주입** 계층이 대상이다.

### 1.2 배경

- 2026-07-04 "2026년 최저임금" 환각 사건 후속으로 `module-routing-upgrade`(커밋 68dcf01)가 라우팅 명시화(`_resolve_targets` 4단계)·부분 실행·지식 모듈 등록제를 도입했고, 이후 프로덕션 검증에서 라우팅 구제 실패(8c7f33b)·계산기 간 불일치(1c55952)가 추가 수정됨. **그러나 라우팅 이후 단계(파라미터 배선·결과 주입)와 검색 인프라는 동일 수준의 점검을 받지 않았다.**
- `project-comprehensive-improvement`(Wave 0~5, PR #11~#16 머지)에서 **보류된 항목**이 이번 범위에 직접 걸린다: sources SSE 이벤트(Wave 3 보류), BM25 배포(Wave 3 보류), vercel.json maxDuration(Wave 4 보류), session pending 배선 결정(제품 결정 보류).
- 본 Plan 작성 전에 2개 탐색 에이전트로 사전 감사를 수행했다(§1.3). 발견사항은 전부 파일:라인 근거가 확인된 것만 수록했다(추측 배제).

### 1.3 사전 감사 방법

| 트랙 | 대상 | 방식 |
|------|------|------|
| 계산기 호출 경로 | `analyzer.py` → `pipeline.py`(분기·변환·`_run_calculator`) → `wage_calculator/facade/*` → 프롬프트 주입·SSE·프론트 표시 | 코드 정독 + 호출처 grep(죽은 경로 확인) + 테스트 4종 커버리지 대조 |
| DB/검색 호출 경로 | `rag.py`·`bm25_search.py`·`query_decomposer.py`·`self_rag.py`·`graph.py`·`legal_api.py`·`nlrc_cases.py`·`conflict_resolver.py`·`citation_validator.py` + `pipeline.py` 통합 지점 | 코드 정독 + 데이터 파일 실존 확인(`git ls-files`) + 아카이브/plan 문서 보류항목 대조 |

### 1.4 관련 문서

- `docs/02-design/features/module-routing-upgrade.design.md` — 직전 라우팅 개선 설계(plan/analysis/report 없이 design만 존재)
- `docs/01-plan/features/project-comprehensive-improvement.plan.md` — Wave 0~5 종합 개선(보류분 승계 원천)
- `docs/archive/2026-03/rag-flow-quality-improvement/` — BM25/RRF 도입 이력·미실행 벤치마크
- `docs/01-plan/features/search-quality-improvement.plan.md` — 네임스페이스 재구축 등 미완 체크리스트
- `docs/03-analysis/interactive-follow-up.analysis.md` — 현 코드와 불일치(스테일) 확인됨 → Wave D에서 정합화

---

## 2. 범위

### 2.1 In Scope

- [ ] 계산기 호출 경로: 의도분석 파라미터 추출 → `_analysis_to_extract_params` → `_run_calculator` → `WageInput` 배선 → targets 라우팅 → `calc_result` 프롬프트 주입/SSE 전달
- [ ] DB/검색 호출 경로: 복잡도 분류 → 멀티쿼리 → 하이브리드 검색(BM25+Dense) → rerank/Self-RAG → 법제처 API → NLRC 판정사례 → GraphRAG → 충돌 주석 → 인용 검증
- [ ] 위 경로의 폴백·예외 처리·관측성(로그)·타임아웃·캐시 정합성
- [ ] 인덱스/네임스페이스/코퍼스 등 검색 인프라 구성값 정리
- [ ] 회귀 안전망: LLM 없이 도는 오프라인 배선 단위 테스트 신설
- [ ] Wave 3/4 보류분 수용: sources 이벤트 실데이터 발신, BM25 코퍼스 배포, maxDuration 설정

### 2.2 Out of Scope

- 개별 계산기 내부 산식 변경(별도 감사 완료: `docs/calculator-audit/`, 골든 테스트 존재)
- 크롤러·메타데이터 생성·Pinecone 업로드 파이프라인(코퍼스 소스 추가/재청킹 포함)
- 프롬프트 전면 개편, LLM 모델 교체
- UI 리디자인(§5의 sources 최소 표시·수치 카드 제외)
- 괴롭힘 평가기(`harassment_assessor`) 내부 로직
- Supabase 스키마 변경

---

## 3. 사전 감사 발견사항 (심각도별 마스터 목록)

ID 규칙: `CALC-*` 계산기 호출 경로, `DB-*` 데이터베이스/검색 호출 경로, `TEST-*` 테스트·관측성.

### 3.1 🔴 P1 — 높음 (기능 사문화·정확성 직결)

| # | 발견 | 근거 위치 |
|---|------|-----------|
| CALC-1 | **계산기 입력 파라미터 배선 누락** — analyzer가 추출하는 `arrear_amount`/`arrear_due_date`·`parental_leave_months`·`notice_days_given`·`fixed_allowances`·`occupation_code`가 `_analysis_to_extract_params`에서 드롭되고, `is_probation`/`contract_months`는 전달돼도 `_run_calculator`가 `WageInput`에 세팅하지 않음. 소비처는 실존(`minimum_wage.py:73-76` 수습 감액, `parental_leave.py:88`, `facade/__init__.py:103` 체불 skip 조건) → **임금체불 지연이자·육아휴직급여 계산은 웹 파이프라인에서 사실상 실행 불가, 수습 감액 미적용** | `analyzer.py:147-158`, `pipeline.py:818-837`, `pipeline.py:604-635` |
| CALC-2 | **복수 계산유형 중 첫 번째만 라우팅** — `calculation_types[0]`만 변환·계산. 예: 퇴직금+연차수당 질문 시 연차 유실. 반면 `_compute_missing_info`는 전체 유형 기준으로 판정 → "부족 정보 없음"이라 안내하고도 계산은 안 되는 안내-실행 불일치 | `pipeline.py:815-816` vs `pipeline.py:780` |
| DB-1 | **BM25 코퍼스 미배포 → 하이브리드 검색 상시 무력화** — `data/bm25_corpus.json`이 리포·빌드 어디에도 없음(`data/`엔 `graph_data.json`뿐, Vercel 빌드에 생성 단계 없음). `load_bm25_corpus()`가 False 반환 → 항상 Dense-only. 법조문 번호·판례번호 정확 키워드 recall 저하. rag-flow 아카이브 리포트도 "빌드 스크립트 실행 필요" 명시 | `bm25_search.py:98-99`, `rag.py:208-218`, `vercel.json` |
| DB-2 | **`sources` SSE 이벤트 항상 빈 배열** — 유일한 emit이 하드코딩 `hits: []`. 실제 검색 결과(`pinecone_hits`/`precedent_meta`/`consultation_hits`)는 미포함, 프론트 핸들러도 no-op(`.sources` CSS 미사용 잔재). **법률 챗봇인데 답변 근거 출처를 UI에 표시하지 못함** (Wave 3 보류분) | `pipeline.py:1215`, `public/index.html:1074`, `:210-212` |
| DB-3 | **Pinecone 인덱스명 기본값이 무관한 잔재값 + 리포 전반 3종 혼재** — env 미설정 시 `semiconductor-lithography`에 연결, 초기화 실패도 조용히 삼켜져 무증상 RAG 전멸 가능. 업로드 스크립트는 `laborconsult-bestqna`, 조회·테스트는 제각각 → 업로드-조회 대상 불일치 위험 | `app/config.py:55-63`, `pinecone_upload_legal.py:388`, `chatbot.py:35`, `search_quality_test.py:20` |

### 3.2 🟡 P2 — 중간 (신뢰성·정합성·성능)

| # | 발견 | 근거 위치 |
|---|------|-----------|
| CALC-3 | **계산기 오류 문자열을 '정확한 수치'로 LLM에 주입** — 예외 시 `"[계산기 오류: {e}]"`가 `calc_result`로 살아남아 "정확한 계산 — 이 수치를 사용하세요" 헤더로 프롬프트에 주입됨. 차단·폴백 없음 | `pipeline.py:672-673` → `:1267-1268` |
| CALC-4 | **calc_cache 교차오염** — 이전 질문의 `extracted_info` 전체가 calc_type별로 저장되고 `get_cached_info()`가 flat 병합 → 새 질문의 빈 필드에 무차별 프리필. 누락 판정(`_compute_missing_info`)보다 먼저 실행돼 판정까지 왜곡 | `session.py:89-103`, `pipeline.py:989-995` |
| CALC-5 | **만원/원 단위 코드 가드 부재** — "250만원"→2,500,000 변환을 LLM 지시(rule#7)에만 의존. `NUMERIC_RANGES` 하한이 1이라 만원 누락값(250)도 통과. 시급 최저임금 보정(`pipeline.py:565-571`)만 존재, 월급/연봉 가드 없음 | `prompts.py:192`, `analyzer.py:47-49` |
| CALC-6 | **ANALYZE_TOOL calculation_types enum 협소** — `eitc`·`industrial_accident`·`average_wage`·`public_holiday`·`working_hours`·`shutdown_allowance` 등이 enum에 없어 주 분석경로에서 분류 불가. `REVERSE_CALC_MAP`에 매핑이 있어도 도달 불가 → 키워드 폴백(`infer_calc_types`)에만 의존 | `prompts.py:17-23`, `pipeline.py:804-813` |
| CALC-7 | **분석·추출 실패의 조용한 삼킴** — 의도분석 전체가 bare `except Exception:`으로 무로그 폴백, `_extract_params`도 `except: pass`. "계산기 미실행" 원인 관측 불가(직전 라우팅 개선에서 로그를 넣은 취지와 상반) | `pipeline.py:1006-1009`, `:400-401` |
| CALC-8 | **계산 수치가 UI에 결정적으로 표시되지 않음** — 프론트가 `meta`(calc_result) 이벤트를 무시, 수치는 LLM 재현에만 의존. LLM이 수치를 바꾸면 사용자는 정답을 볼 수 없음 | `public/index.html:1074-1075`, `pipeline.py:1267` |
| DB-4 | **인용 검증 화이트리스트 사각지대 — 정당한 인용을 환각으로 오판·삭제** — 화이트리스트가 `consultation_hits + precedent_meta`만 포함. 법령 API 텍스트·NLRC·GraphRAG에 실린 판례번호를 LLM이 정당히 인용해도 `hallucinated`로 분류돼 번호가 제거됨 | `pipeline.py:1446-1454`, `citation_validator.py:164-178`, `:227-234` |
| DB-5 | **LLM 컨텍스트 총량 상한 부재 + 첨부 이중 주입** — `parts[]` 조립에 전역 캡 없음(graph만 2000자 캡). COMPLEX(top_k 20)+다중 소스+첨부 전문 결합 시 비대화. 첨부는 텍스트 프롬프트와 Vision 블록에 중복 주입 가능 | `pipeline.py:1245-1394`, `:1284`, `:1408` |
| DB-6 | **임계경로 LLM 타임아웃 부재** — 항상 실행되는 `analyze_intent`·`_extract_params`·`_stream_claude`에 타임아웃 없음(보조 호출은 3s/3s/5s/2s 존재). `vercel.json`에 `maxDuration` 미설정(Wave 4 보류분) → 지연 시 graceful 실패 없이 행(hang) | `analyzer.py:132`, `pipeline.py:142`, `:370`, `vercel.json` |
| DB-7 | **NLRC 판정사례를 콜드스타트마다 네트워크 전량 재조회** — 인메모리 캐시(24h TTL)는 서버리스 인스턴스별로 재구축 필요. 커밋된 `odcloud_labor_cases.json`(126KB)은 **코드 어디서도 미참조**(죽은 데이터) — 번들 로드로 콜드스타트 네트워크를 제거할 수 있는데 미사용 | `nlrc_cases.py:27-30`, `:60-88` |

### 3.3 🟢 P3 — 낮음 (정리·드리프트)

| # | 발견 | 근거 위치 |
|---|------|-----------|
| CALC-9 | 변환기 이원화 — 정식 진입점 `from_analysis()`/`_provided_info_to_input()`은 호출처 0건(죽은 API), 웹은 별도 인라인 변환기 사용. 지원 필드도 서로 달라 드리프트 위험. `facade/__init__.py:231-232` 주석("출산휴가는 from_analysis 경로로 처리")은 실제 미작동 | `facade/__init__.py:156-172`, `conversion.py:10-103` |
| CALC-10 | follow-up pending 흐름 죽은 코드 — `save_pending()` 호출처가 프로덕션에 없어 `merge_with_pending` 분기 도달 불가. 복원 vs 공식 폐기의 **제품 결정 필요**(종합개선 보류분) + `interactive-follow-up.analysis.md`가 "구현됨"으로 기술된 스테일 문서 | `session.py:36-82`, `pipeline.py:973-980`, `:12-13` |
| CALC-11 | chatbot.py 레거시 오라우팅 — 미매핑 계산유형을 조용히 `minimum_wage`로 폴백(웹은 제거한 묵시적 기본값). 두 진입점 라우팅 드리프트 | `chatbot.py:394` |
| CALC-12 | `weekly_total_hours`만 있을 때 주 5일 강제 가정 — 실제 근무일수(예: 3일)와 무관하게 5일 환산 → 주휴·연차 왜곡 소지 | `pipeline.py:577-582` |
| CALC-13 | `NUMERIC_RANGES` 검증이 추가한 missing_info 라벨이 `_compute_missing_info` 교체로 유실 가능(`_REQUIRED_FIELDS` 미정의 유형은 판정 공백) | `analyzer.py:96-102`, `pipeline.py:996-1000` |
| DB-8 | BM25가 멀티쿼리를 단일 문자열로 결합 검색(분해 이점 상실), RRF alpha=0.5 고정·미튜닝 | `rag.py:209` |
| DB-9 | legal_api circuit breaker 상태가 인스턴스 로컬(서버리스 다중 인스턴스 간 비공유) | `legal_api.py:35` |
| DB-10 | BM25 코퍼스 로드(최대 15,000 doc 토크나이즈)가 첫 요청 경로에서 동기 수행(코퍼스 배포 시 콜드스타트 가산) | `rag.py:208`, `bm25_search.py:109-116` |

### 3.4 ⚙️ 테스트·관측성 공백

| # | 발견 | 근거 위치 |
|---|------|-----------|
| TEST-1 | **파이프라인 배선 테스트 0건** — 골든/배치 테스트는 `WageCalculator.calculate()` 엔진을 직접 호출해 analyzer→변환→`_run_calculator` 경로를 전부 우회. CALC-1/2 같은 배선 결함을 잡을 수 있는 테스트가 없음 | `test_wage_golden.py:36-104`, `calculator_batch_test.py:443-455` |
| TEST-2 | **검색 모듈 단위테스트 전무 + 기존 스크립트 전부 라이브 키 의존** — `rag`/`bm25`/`self_rag`/`graph`/`conflict_resolver`/`citation_validator`/`legal_api`/`nlrc_cases` 직접 단위테스트 없음. 검색 테스트 4종은 assert 없는 수동 스크립트, CI 잡 부재(pages.yml은 정적 배포만) | grep 확인, `.github/workflows/pages.yml` |
| TEST-3 | **기존 벤치마크 실행 불가·대상 불일치** — `benchmark_pipeline.py`는 `output_legal_cases/` 부재로 0건 처리, `search_quality_test.py`·`test_precedent_search.py`는 프로덕션과 다른 인덱스/네임스페이스를 조회. `test_legal_cases_e2e.py`는 정답 판례(`known_refs`) 대조 없이 건수만 집계 | `benchmark_pipeline.py:36`, `search_quality_test.py:20-22`, `test_precedent_search.py:13,44` |

---

## 4. 개선 계획 (웨이브별)

> 웨이브 순서 원칙: 정답이 틀리는 것(A) → 근거가 빈약한 것(B) → 신뢰성·성능(C) → 정리·안전망(D). 각 웨이브는 독립 PR로 머지 가능해야 하며, 매 웨이브마다 골든·CLI 116케이스 무회귀 확인.

### Wave A — 계산 정확성 (P1: CALC-1, CALC-2, CALC-3 + TEST-1)

1. `_analysis_to_extract_params`·`_run_calculator`에 누락 필드 배선(체불·육아휴직·수습·직종·고정수당·해고예고) — 죽은 `conversion.py`를 참조 구현으로 활용하되 단일 변환기로 수렴(CALC-9와 연계, 최종 수렴은 Wave D)
2. `calculation_types` 전체를 targets로 변환(첫 번째만이 아니라 union) + `_compute_missing_info` 판정과 실행 대상 일치화
3. 계산 예외 시 `calc_result` 주입 차단(오류는 로그 + status 이벤트로만) — "정확한 수치" 헤더에 오류문이 실리는 경로 제거
4. **오프라인 배선 단위 테스트 신설**: 고정 analysis dict → params → `WageInput` 필드 → targets를 LLM 없이 검증(체불/육아휴직/수습/복수유형 케이스 포함)

### Wave B — 검색 인프라·출처 투명성 (P1: DB-3 → DB-1 → DB-2)

1. **인덱스명 단일화(선행)**: 기본값 `semiconductor-lithography` 제거, 단일 상수(또는 필수 env)로 통일 + 초기화 실패를 로그로 가시화. *프로덕션 Vercel env 실값 확인 후 변경(리스크 R-1)*
2. **BM25 코퍼스 배포**: `build_bm25_corpus.py` 실행 → 크기 측정 → 배포 방식 결정(§8.2 결정 포인트) → `search_hybrid`가 실제 RRF 경로를 타는지 확인. 코퍼스 갱신 절차 문서화(신규 업로드 시 재빌드)
3. **sources 이벤트 실데이터 발신 + 프론트 최소 표시**: `pinecone_hits`/`precedent_meta`/`consultation_hits`를 정규화한 hits 배열로 emit, 프론트는 답변 하단 접이식 출처 목록 렌더(기존 `.sources` CSS 활용)

### Wave C — 신뢰성·성능 (P2: DB-4, CALC-4~7, DB-5~7)

1. 인용 화이트리스트에 법령 API·NLRC·GraphRAG 소스의 판례번호 편입(DB-4) — 정당 인용 삭제 방지
2. calc_cache 프리필을 동일/호환 calc_type으로 한정 + 누락 판정 이후로 이동(CALC-4)
3. 만원 단위 휴리스틱 가드(월급 하한 sanity check, 예: 월급 < 10,000이면 만원 단위로 해석 후 재검증)(CALC-5)
4. `calculation_types` enum을 25종 타깃과 정합화(CALC-6) + 분석 실패 로깅(CALC-7)
5. 컨텍스트 조립 총량 캡 + 소스별 예산(우선순위: 계산결과 > 인용목록 > 판례 > 법조문 > 상담사례) + 첨부 이중 주입 제거(DB-5)
6. `analyze_intent`/`_extract_params`/스트림 first-token 타임아웃 + `vercel.json` `maxDuration` 설정(DB-6, Wave 4 보류분 수용 — legacy builds/functions 동시사용 이슈 재검증 포함)
7. NLRC 번들 파일(`odcloud_labor_cases.json`) 우선 로드 + 네트워크는 백그라운드 갱신으로 강등(DB-7)

### Wave D — 정리·드리프트 해소·안전망 (P3 + TEST-2/3)

1. 변환기 단일화 마무리: `from_analysis`/`conversion.py`를 웹 경로와 수렴하거나 공식 폐기(CALC-9), chatbot.py 라우팅을 strict 버전으로 정렬(CALC-11)
2. `weekly_total`→근무일수 가정 개선(가능하면 질문에서 일수 추출, 불가 시 5일 가정을 답변에 명시)(CALC-12), missing_info 병합 규칙 정리(CALC-13)
3. BM25 쿼리별 검색+RRF(DB-8), 코퍼스 lazy-load 최적화(DB-10) — *코퍼스 배포(Wave B) 후에만 의미 있음*
4. 검색·인용 모듈 오프라인 단위 테스트(fixture 기반: RRF 결합, 화이트리스트 매칭, 환각 검출 정규식)(TEST-2) + 기존 테스트 스크립트의 인덱스/NS를 프로덕션 정합화(TEST-3)
5. 스테일 문서 정리: `interactive-follow-up.analysis.md`에 미배선 사실 주석, CLAUDE.md의 SSE 이벤트·하이브리드 검색 기술을 실태와 일치화

### 제품 결정 대기 (코드 변경 없음 — 사용자 판단 필요)

| 항목 | 선택지 | 관련 |
|------|--------|------|
| 계산 수치 카드 UI | `meta.calc_result`를 프론트에서 결정적 카드로 표시 vs 현행(LLM 재현 의존) 유지 | CALC-8 |
| follow-up pending 흐름 | 복원(설계 필요) vs 공식 폐기(session.py 잔존 코드 제거) | CALC-10 |
| circuit breaker 공유 스토어 | Supabase 기반 공유 vs 인스턴스 로컬 유지(현행) | DB-9 |

---

## 5. 요구사항

### 5.1 기능 요구사항

| ID | 요구사항 | 근거 | 우선순위 | 상태 |
|----|----------|------|----------|------|
| FR-01 | analyzer가 추출한 모든 계산 파라미터가 `WageInput`까지 배선되어 해당 계산기가 실제 실행된다(체불·육아휴직·수습 감액 포함) | CALC-1 | High | Pending |
| FR-02 | 복수 `calculation_types`가 모두 계산되고, 누락 정보 안내와 실행 대상이 일치한다 | CALC-2 | High | Pending |
| FR-03 | 계산 예외 시 오류 문자열이 LLM 프롬프트에 '정확한 수치'로 주입되지 않는다 | CALC-3 | High | Pending |
| FR-04 | 프로덕션 하이브리드 검색이 BM25+Dense RRF 경로로 실제 동작한다(코퍼스 배포 + 갱신 절차 문서화) | DB-1 | High | Pending |
| FR-05 | `sources` 이벤트가 실제 검색 결과를 담아 발신되고 답변 하단에 출처가 표시된다 | DB-2 | High | Pending |
| FR-06 | Pinecone 인덱스명이 코드베이스 전체에서 단일 출처로 관리되고, 초기화 실패가 로그로 가시화된다 | DB-3 | High | Pending |
| FR-07 | 법령 API·NLRC·GraphRAG 소스의 판례번호가 인용 화이트리스트에 포함되어 정당한 인용이 삭제되지 않는다 | DB-4 | Medium | Pending |
| FR-08 | calc_cache 프리필이 호환 계산유형으로 한정되고 누락 판정을 왜곡하지 않는다 | CALC-4 | Medium | Pending |
| FR-09 | 월급/연봉 만원 단위 오해석에 대한 코드 수준 가드가 존재한다 | CALC-5 | Medium | Pending |
| FR-10 | 25종 계산기 전부가 의도분석 enum 또는 명시적 폴백으로 도달 가능하다 | CALC-6 | Medium | Pending |
| FR-11 | 의도분석·파라미터 추출 실패가 원인과 함께 로그에 남는다 | CALC-7 | Medium | Pending |
| FR-12 | LLM 컨텍스트 조립에 총량 상한과 소스별 예산이 있고 첨부 이중 주입이 없다 | DB-5 | Medium | Pending |
| FR-13 | 임계경로 LLM 호출에 타임아웃이 있고 `maxDuration`이 설정되며, 초과 시 사용자에게 graceful 오류 이벤트가 간다 | DB-6 | Medium | Pending |
| FR-14 | NLRC 판정사례가 번들 파일에서 즉시 로드된다(콜드스타트 네트워크 의존 제거) | DB-7 | Medium | Pending |
| FR-15 | 파이프라인 배선·검색 모듈의 오프라인 단위 테스트가 존재하고 API 키 없이 통과한다 | TEST-1/2 | High | Pending |
| FR-16 | P3 정리 항목(변환기 단일화·chatbot 정렬·문서 정합) 처리 | CALC-9~13, DB-8~10, TEST-3 | Low | Pending |

### 5.2 비기능 요구사항

| 분류 | 기준 | 측정 방법 |
|------|------|-----------|
| 정확성 | 계산기 결과 수치와 최종 답변 수치 일치(오류문 주입 0건) | 오프라인 배선 테스트 + `test_legal_cases_e2e.py` 확장 |
| 성능 | 첫 토큰 지연 회귀 없음(개선 전후 비교), NLRC 콜드스타트 네트워크 0회 | `benchmark_pipeline.py` 타이밍 수집(케이스 fixture 보강 후) |
| 가용성 | 모든 신규 경로에 폴백 존재(BM25 실패→Dense, sources 실패→미발신, 번들 실패→네트워크) — CLAUDE.md graceful degradation 규약 | 폴백 강제 주입 테스트 |
| 관측성 | 라우팅 결정·계산 실패·검색 폴백이 로그로 추적 가능 | 로그 필드 검수 |
| 비용 | 질문당 LLM 호출 수 증가 없음(현행: 분석 1 + [추출 1] + [분해 1] + [Self-RAG ≤5] + 답변 1 + [교정 ≤2]) | 코드 리뷰 + 벤치마크 카운터 |

---

## 6. 성공 기준

### 6.1 Definition of Done

- [ ] P1 5건(CALC-1/2, DB-1/2/3) 전부 수정 + 각 항목 회귀 테스트 존재
- [ ] P2 10건 중 CALC-3~7·DB-4~7 수정(CALC-8은 제품 결정에 따름)
- [ ] 오프라인 배선 테스트 신설·통과(API 키 없이 실행 가능)
- [ ] 기존 안전망 무회귀: `test_wage_golden.py`, `wage_calculator_cli.py` 116케이스, `calculator_batch_test.py` 102케이스
- [ ] sources 이벤트 실데이터 발신을 로컬 uvicorn에서 확인(SSE 이벤트 캡처)
- [ ] 제품 결정 3건(수치 카드·pending·breaker 스토어)을 사용자에게 상신, 결정 반영 또는 보류 기록
- [ ] Gap 분석(Match Rate) ≥ 90%

### 6.2 품질 기준

- [ ] 모든 신규 코드에 폴백 경로(CLAUDE.md 규약) — 신규 실패 모드가 전체 파이프라인을 죽이지 않음
- [ ] Vercel 배포 필수 파일(`app/core/*.py` 신규 모듈) git 추적 확인
- [ ] 인덱스명 변경은 프로덕션 env 확인 후 적용(무중단)
- [ ] 웨이브별 독립 PR + CLI/골든 테스트 결과 첨부

---

## 7. 리스크와 완화

| ID | 리스크 | 영향 | 가능성 | 완화 |
|----|--------|------|--------|------|
| R-1 | 인덱스명 기본값 교체가 프로덕션 env 실값과 어긋나 검색 전멸 | High | Medium | 변경 전 Vercel env의 `PINECONE_INDEX_NAME` 실값 확인, 미설정이면 현행 인덱스명을 상수로 고정 후 단계 전환, 초기화 실패 로그 선배치 |
| R-2 | BM25 코퍼스가 대용량이면 리포 비대(과거 75MB 코퍼스 위생 문제 재발) | Medium | Medium | 빌드 후 크기 실측 → 임계(예: 5MB) 초과 시 커밋 대신 빌드 단계/외부 스토리지 채택(§8.2), `.gitignore` 선반영 |
| R-3 | CALC-1 배선 확장이 targets 자동감지(`targets=None`) 동작을 바꿔 기존 답변 회귀 | Medium | Medium | 골든·배치 테스트 선실행 기준선 확보, 신규 필드는 명시 target 요청 시에만 활성화하는 보수적 배선부터 |
| R-4 | `maxDuration` 설정이 legacy `builds`+`functions` 동시 사용 배포 실패 유발(Wave 4 보류 사유) | High | Medium | 별도 브랜치에서 Vercel preview 배포로 선검증, 실패 시 `vercel.ts` 마이그레이션 검토 |
| R-5 | sources UI 추가가 단일 파일(`index.html` ~1,470줄) 회귀 유발 | Medium | Low | 접이식 목록 최소 구현, 기존 `readSSE` 이벤트 스위치에 케이스 추가만, 수동 스모크 체크리스트 |
| R-6 | 타임아웃 도입이 정상 느린 응답(o3 폴백 등)을 조기 절단 | Medium | Low | 스트리밍은 first-token 기준, 폴백 체인 전체 예산과 분리 설정, 타임아웃 시 `error` 이벤트로 안내 |
| R-7 | 인용 화이트리스트 확장이 실제 환각 억제력을 약화 | Medium | Low | 소스 텍스트에서 정규식으로 추출된 번호만 편입(자유 편입 금지), e2e 환각 카운터로 전후 비교 |

---

## 8. 아키텍처·컨벤션 전제

### 8.1 아키텍처 고정 (변경 금지)

- **Vercel serverless(FastAPI) + Supabase + Pinecone + 3-LLM 폴백 체인** 유지 — 2026-07-02 결정. 로컬 파일저장/Docker 방향 금지, 첨부는 Supabase Storage.
- 프로젝트 레벨: Dynamic(기존 프로젝트, 신규 폴더 구조 도입 없음). 본 feature는 기존 `app/core/`·`wage_calculator/`·`public/` 내 수정으로 한정.

### 8.2 설계 단계 결정 포인트 (design 문서에서 확정)

| 결정 | 선택지 | 기본 권고 |
|------|--------|-----------|
| BM25 코퍼스 배포 방식 | ① 리포 커밋(소용량일 때) ② Vercel 빌드 단계 생성 ③ Supabase Storage에서 콜드스타트 로드 | 크기 실측 후 결정, 소용량이면 ① |
| sources 이벤트 스키마 | hits 필드 구성(title/source_type/case_number/score/url) 및 상한 개수 | 상위 5건, CLAUDE.md SSE 목록 갱신 동반 |
| 컨텍스트 예산 배분 | 총량 캡 값과 소스별 우선순위 | 계산결과 > 인용가능목록 > 판례 > 법조문 > 상담사례 순 유지 |
| 타임아웃 값 | analyze/extract/first-token 각각 | 보조 호출(3~5s) 대비 여유값, 실측 p95 기반 |
| 변환기 수렴 방향 | 인라인 변환기를 정식화 vs `conversion.py`로 역수렴 | 웹 경로(인라인)를 정식화하고 `conversion.py` 폐기 |

### 8.3 컨벤션 준수 사항 (CLAUDE.md)

- Graceful degradation 필수: 신규 기능 실패가 파이프라인을 중단시키지 않을 것(BM25→Dense, 번들→네트워크, sources→미발신)
- `app/core/*.py` 신규/수정 모듈은 반드시 git 추적(untracked 시 Vercel 500)
- SSE 이벤트 타입 추가·변경 시 CLAUDE.md 목록과 `public/index.html::readSSE()` 동기화
- 금액 표시 `{:,.0f}`, 법령 인용 형식("근로기준법 제N조", "대법원 YYYY다NNNN") 유지
- `from __future__ import annotations` (app/core 전 모듈)

### 8.4 환경 변수

| 변수 | 용도 | 조치 |
|------|------|------|
| `PINECONE_INDEX_NAME` | 인덱스 단일화 후 명시 설정 권장 | 프로덕션 실값 확인(R-1) 후 기본값 정리 |
| `COHERE_API_KEY` | rerank 활성(top_k adaptive 분기에 영향) | 현행 유지(옵션) |
| 신규 변수 | 없음(원칙) — 타임아웃 등은 상수로 | — |

---

## 9. Next Steps

1. [ ] `/pdca design calc-db-integration-review` — 웨이브별 구현 수준 설계(§8.2 결정 포인트 확정 포함)
2. [ ] 프로덕션 Vercel env `PINECONE_INDEX_NAME` 실값 확인(R-1 선행 조건)
3. [ ] 제품 결정 3건(수치 카드 UI·pending 흐름·breaker 스토어) 사용자 확인
4. [ ] Wave A부터 구현 착수(`/pdca do`)

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-07-14 | 최초 작성 — 2-트랙 사전 감사(계산기 13건·DB/검색 11건·테스트 3건·문서 1건) 기반 | DrunkenZealnut |
