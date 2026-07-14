# calc-db-integration-review Analysis Report

> **Analysis Type**: Gap Analysis (Design vs Implementation)
>
> **Project**: laborconsult (AI 노동상담 챗봇)
> **Analyst**: gap-detector (독립 검증) + 구현 세션 (Gap 조치·재검증)
> **Date**: 2026-07-14
> **Design Doc**: [calc-db-integration-review.design.md](../02-design/features/calc-db-integration-review.design.md)
> **Plan Doc**: [calc-db-integration-review.plan.md](../01-plan/features/calc-db-integration-review.plan.md)

---

## 1. 분석 개요

Design §3~§6의 구현 항목 26개를 gap-detector 에이전트가 **구현 세션과 독립적으로** 코드에서 직접 대조 검증했다(설계 문서의 주장 아닌 코드 확인 기준, 판정 근거 file:line 필수). 판정 기준: ✅ 일치=1점, ⚠️ 타당한 편차·설계 게이트=1점, ⚠️ 부분 구현=0.5점, ❌ 누락=0점.

**1차 판정 94.2% → Gap 2건+부수 1건 즉시 조치·검증 → 최종 100%.**

---

## 2. 항목별 판정 (1차, gap-detector)

| # | 설계 절 | 판정 | 근거 | 비고 |
|---|---------|:---:|------|------|
| 1 | §3.1a 파라미터 6키+2키 전달 | ✅ | `pipeline.py:1003-1010` | occupation/notice/parental/arrear×2/fixed + shutdown/public_holiday |
| 2 | §3.1b `_run_calculator` WageInput 세팅 | ✅ | `pipeline.py:745-773` | 8필드 + 확장 2필드, 값 존재 시만 세팅(R-3) |
| 3 | §3.1c `_WAGELESS_TARGETS`+wage_arrears | ✅ | `pipeline.py:610` | 임금 없는 체불 질문 실행 가능 |
| 4 | §3.2 복수유형 union 라우팅 | ✅ | `pipeline.py:613-640,775-777,985` | 순서 보존 union + 기존 4단계 폴백 유지 |
| 5 | §3.3 오류 문자열 주입 차단 | ✅ | `pipeline.py:812-815` | logger.exception + None |
| 6 | §3.4 배선 테스트 W1~W9 | ✅ | `test_pipeline_wiring.py:31-121` | API 키 불요, 스텁 기반 |
| 7 | §4.1 인덱스명 단일화+로그 | ✅ | `config.py:23-27,63-73` | 하드코딩 잔존 0 (2025 별도 인덱스 예외) |
| 8 | §4.1 RAG 0건 관측성 경고 | ❌→✅ | (조치 후) `rag.py:24-25,176-182` | **1차 미구현** — §4 참조 |
| 9 | §4.2 BM25 gz 배포 코드 | ✅ | `build_bm25_corpus.py:65-74`, `bm25_search.py:29-30,110-113`, `.gitignore:17` | gz 아티팩트 커밋은 §7#9 게이트(키 필요) |
| 10 | §4.3 sources 실데이터+프론트 | ✅ | `pipeline.py:131-161,1406-1407`, `index.html:1049,1076,1101,1115-1122` | replace 이벤트에도 보존되는 구조 |
| 11 | §5.1 인용 목록·검증 동일 원천 | ✅ | `pipeline.py:164-189,1439-1455,1657-1658` | `whitelist_hits` 단일 구성 |
| 12 | §5.2 캐시 유형 스코프+안내 | ✅ | `session.py:97-109`, `pipeline.py:1165-1173,1500-1505` | |
| 13 | §5.3 만원 단위 가드 | ✅ | `pipeline.py:494-515,1207-1208,1229` | 시급·일급 제외, 2곳 호출 |
| 14 | §5.4 enum 10종 확장 세트 | ✅ | `prompts.py:24-27,68-69,222-230`, `pipeline.py:886-899,970-975`, `registry.py:116-117`, `analyzer.py:60-61,78-79,166` | |
| 15 | §5.5 예외 로깅 2곳 | ✅ | `pipeline.py:475-477,1191-1193` | |
| 16 | §5.6 컨텍스트 예산+이중 주입 제거 | ✅ | `pipeline.py:192-196,1445-1484,1138,1603`, `graph.py:230` | |
| 17 | §5.7 타임아웃+maxDuration | ✅ | `analyzer.py:143`, `pipeline.py:214-216,445`, `vercel.json:3` | maxDuration은 preview 검증 대기(R-4) |
| 18 | §5.8 NLRC 번들 로드 | ✅ | `nlrc_cases.py:91-127`, `data/nlrc_cases.json`, `refresh_nlrc_cases.py` | 콜드스타트 네트워크 0회 |
| 19 | D1 변환기 단일화 | ✅ | `facade/__init__.py`, `conversion.py:5-8`, 호출 0 grep | from_analysis/_provided_info_to_input 제거 |
| 20 | D2 chatbot strict 정렬 | ✅ | `chatbot.py:394-399` | |
| 21 | D3 5일 가정 표면화 | ✅ | `pipeline.py:688-690,1212-1213` | |
| 22 | D4 validation_warnings 보존 | ✅ | `schemas.py:33`, `analyzer.py:112,188`, `pipeline.py:1182-1185` | |
| 23 | D5 BM25 멀티쿼리 RRF | ✅ | `bm25_search.py:184-199`, `rag.py:213-214` | |
| 24 | D7 오프라인 단위+CI | ✅ | `test_offline_units.py`(8종), `.github/workflows/tests.yml` | 설계 7종+2종 추가 |
| 25 | D8 수동 스크립트 정합 | ✅ | `search_quality_test.py:2,22-26`, `test_precedent_search.py:5-6,18-24`, `benchmark_pipeline.py:36,538-541` | 픽스처 커밋은 의도적 생략(창작 판례 데이터 부적절) |
| 26 | D9 문서 정합 | ⚠️→✅ | (조치 후) `CLAUDE.md`, `interactive-follow-up.analysis.md:3-7` | **1차: CLAUDE.md:251 잔존 참조** — §4 참조 |

---

## 3. Match Rate

| 시점 | 계산 | Match Rate |
|------|------|-----------:|
| 1차 (gap-detector 독립 판정) | ✅24×1 + ⚠️1×0.5 + ❌1×0 = 24.5 / 26 | **94.2%** |
| Gap 조치 후 (최종) | 26 / 26 | **100%** |

기준(≥90%) 충족 — iterate 불필요, Check 단계 내 즉시 조치로 종결. iterationCount=0.

---

## 4. Gap 및 조치 내역

| Gap | 내용 | 조치 | 검증 |
|-----|------|------|------|
| #8 (❌) | `search_pinecone_multi` 결과 0건 시 인덱스/네임스페이스 오배선 경고 부재 — R-1(인덱스명 오배선) 조기 감지 장치 누락 | `rag.py`에 모듈 플래그 `_zero_hit_warned` + 0건 시 인스턴스당 1회 `logger.warning`(index명·NS 그룹 노출) 구현 | 단위 재현: 빈 결과 강제 → 경고 1회 발화·재호출 시 미발화 확인, 오프라인 스위트 3종 재통과 |
| #26 (⚠️) | `CLAUDE.md:251`이 삭제된 `_provided_info_to_input()`의 한국어 변수명 규약을 여전히 서술 | 영문 키 규약(`_run_calculator` 기준)으로 교체 | grep 잔존 참조 0건 |
| 부수 | `build_bm25_corpus.py` docstring이 raw json 출력으로 표기(실제는 gz) | docstring 정정 | py_compile 통과 |

---

## 5. 구현이 설계를 초과한 부분 (gap-detector 확인)

- **인덱스 리팩터 8→10곳**: 설계 목록 외 `pinecone_upload.py`·`cleanup_remaining.py`도 `resolve_index_name()` 통일
- **오프라인 테스트 +2종**: `test_session_cache_scope`·`test_analysis_schema` (CALC-4·D4 직접 커버)
- **REVERSE_CALC_MAP insurance 오매핑 교정**: `"임금계산"`(overtime+minwage+weekly_holiday로 오라우팅) → `"4대보험"`(insurance) — 4대보험 질문이 실제 보험 계산기로 라우팅
- **ANALYZER_SYSTEM**: 신규 10유형 전체 라벨별 안내(설계는 2줄 최소안)

---

## 6. 잔여 운영 액션 (코드 완결 — Check 범위 밖)

| # | 항목 | 필요한 것 | 관련 |
|---|------|-----------|------|
| 1 | `DEFAULT_PINECONE_INDEX` 실값 확정 | 프로덕션 Vercel env `PINECONE_INDEX_NAME` 확인 → `app/config.py:23` 한 줄 교체 | R-1, 설계 §7#7 |
| 2 | BM25 코퍼스 빌드·커밋 | `PINECONE_API_KEY`로 `python3 build_bm25_corpus.py` → `data/bm25_corpus.json.gz` 커밋. 미커밋 시 현행처럼 Dense-only 폴백(동작 저하 없음, 개선 미발현) | DB-1, 설계 §7#9 |
| 3 | `maxDuration` preview 검증 | Vercel preview 배포 — legacy builds 미지원 시 `vercel.json:3`의 config만 되돌림 | R-4 |
| 4 | 제품 결정 3건 | 수치 카드 UI(CALC-8) / pending 복원 vs 폐기(CALC-10) / breaker 공유 스토어(DB-9) | Plan §4 |

---

## 7. 결론

Design 대비 구현 일치율 **100%** (1차 독립 판정 94.2% → Gap 3건 조치·검증). 오프라인 안전망 4종(골든·CLI 116케이스·배선 W1~W9·단위 8종) 전부 통과. 다음 단계: `/pdca report calc-db-integration-review`.
