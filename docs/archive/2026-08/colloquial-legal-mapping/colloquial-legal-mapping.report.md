# colloquial-legal-mapping 완료 보고서

> Plan: `docs/01-plan/features/colloquial-legal-mapping.plan.md`
> Design: `docs/02-design/features/colloquial-legal-mapping.design.md`
> Analysis: `docs/03-analysis/colloquial-legal-mapping.analysis.md`
> 기간: 2026-08-20 (당일) | PR: [#54](https://github.com/DrunkenZealnut/laborconsult/pull/54) (머지 `95d3c72`, 커밋 4개)

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | 구어체 상담 표현("잘렸다"·"퉁치자")의 법률 개념 매핑을 LLM 단일 의존에서 **3층 구조**로 — 폴백 RAG 활성화 + 정적 사전 + 법률근거 승격 |
| 시작·완료 | 2026-08-20 (당일) |
| Match Rate | 91%(Check) → **98%**(Act 후) — 91% 시점에 경로 리뷰가 P0 1·P1 3 적발, 전 건 해소 |
| 코드 변경 | 12파일, +1,159/−29줄 (커밋 4개 — 본 구현 1 + CodeRabbit 대응 3) |
| 테스트 | 오프라인 스위트 5종 통과, T24 회귀 **24검사** 신규, 사전 단위(양성 24·음성 6·억제 3) |
| 실측 | 폴백 법률 코퍼스 도달 **0% → 50%**, 정상 50% → **67~83%**(반복 4회 밴드), evidence(승격 3종) 신규 기준선 폴백 28%·정상 50%, 해설서 기준선 75.0% **무회귀** |
| 리뷰 | CodeRabbit 3건(Major 2·Minor 1) 전 건 수정·답글, 최종 "No actionable comments" |

### Value Delivered

| 관점 | 계획 | 실제 결과 |
|------|------|-----------|
| **Problem** | 구어→법률용어 변환이 의도분석 LLM 한 곳에 전적으로 의존 — 실패 시 법률 코퍼스 도달 0/8, 정상 경로도 SIMPLE 편중으로 4/8 | 실측으로 진단이 **더 나쁜 쪽으로 정정**됨: 의도분석 실패 시 검색 쿼리가 구어가 아니라 **RAG 블록 자체가 스킵**(`if analysis:`)돼 답변이 검색 근거 0으로 생성되고 있었다 — 법률 상담에서 할루시네이션 위험이 가장 높은 상태 |
| **Solution** | 폴백 전용 정적 사전 + 판례·행정해석 승격(해설서 승격 패턴 재사용) + 프롬프트 예시 확장 | 합성 `AnalysisResult(intent_provider="synthetic")` 주입(원안 "가드 완화"보다 우월 — 무방비 참조 구조적 해소) + 사전 22패턴·**억제자 구조**("기계에 손이 잘렸다"≠해고) + `_ensure_source_presence` 공용화 + 신규 불변식 I-7/I-8/**I-9**(다양성 클래스 마지막 1건 victim 금지 — 유일 판례를 지워 하위 판례로 되메우는 강등 순환 차단) + SIMPLE 강제·임베딩 타임아웃(2벤더 장애 중 무한 대기 방지) |
| **Function & UX Effect** | 법률용어 없는 질문에도 판례·행정해석이 근거에 실림 | 정상 경로 법률 코퍼스 도달 50%→67~83%, LLM 장애 중에도 0%→50%. "의도분석 전멸 대화"가 `metadata.llm.intent_provider="synthetic"`으로 **최초로 계측 가능** |
| **Core Value** | 한국어 맥락 이해가 LLM 가용성에 좌우되지 않는 다층 구조 | 3층이 서로 다른 실패를 담당: LLM 변환(정확도, 18/18) / 정적 사전(가용성 — 오변환>미변환 비대칭 원칙으로 고신뢰만) / 승격(랭킹 편중 — 교체라 저작권 상한 무접촉, `eval_retrieval` 75.0% 무회귀로 실증) |

---

## 1. 산출물

### 1.1 코드

| 파일 | 구분 | 내용 |
|------|------|------|
| `app/core/colloquial_map.py` | **신규** | 구어→법률용어 정적 사전 — 22패턴·계열 7종, (패턴, 용어, 억제자) 3-튜플, NFC 정규화, 항목별 근거 주석 |
| `app/core/pipeline.py` | 수정 | 합성 분석 주입(스코프 게이트·계산 라우팅 **뒤** — 기존 폴백 동작 보존), SIMPLE 강제, `_merge_search_queries(always_fallback)` 원문 병기 |
| `app/core/rag.py` | 수정 | `_ensure_source_presence` 공용화, 법률근거 승격(`LEGAL_PROMOTE_SOURCES`·킬스위치 `LEGAL_PROMOTE`), `_pick_swap_victim` I-7/I-8/I-9, `_diversity_class_of`(승격 대상 집합과 동일 정의 공유), 임베딩 `with_options(timeout=10, max_retries=0)` |
| `app/templates/prompts.py` | 수정 | 변환 예시 7건 추가(상계·공제·통화지급·3.3%·4대보험·갈굼·공상 처리) — 재측정에서 LLM 키워드 실반영 확인 |
| `eval_colloquial.py` | **신규** | 3층 고정 평가(LLM 변환/사전/검색 A/B) — corpus·evidence 이중 지표, 폴백은 SIMPLE 파라미터(프로덕션 정합), `--dict-only` 오프라인 |
| `data/eval_colloquial_queries.json` | **신규** | 고정 fixture 18건(계열 15종, expect_terms 개념 판정) |
| `test_precedent_ingest.py` | +124 | T24 24검사 — 발동·랭크 창·킬스위치 독립성·I-7/8/9·`uses_textbook`·마커 2종 공존 |
| `test_offline_units.py` | +114 | 사전 단위(양성 24·음성 6·억제 3·복합 1) + 배선 검사(폴백 1곳 한정) + merge 원문 병기 |

### 1.2 문서·규범

- `CLAUDE.md`: "다양성 승격 2종"(I-9 포함) + "구어→법률용어 매핑은 다층이다" 불릿 신설
- Design: 반증된 단정(§3.2 "발동 조건 불변") 반례와 함께 정정 기록, 불변식 번호를 선행 사이클 체계로 재정렬
- PDCA 문서 4종 (plan·design·analysis·report)

## 2. 프로세스에서 얻은 것

1. **"Match Rate 90%+여도 경로 리뷰 한 번 더" 관례의 3번째 적중** — gap-detector 91% 시점에 code-analyzer가 P0 1(신규 파일 미추적 → 배포 500)·P1 3(원문 소실·승격 강등 순환·무타임아웃 개방)을 적발. 특히 P1-3은 Design의 단정이 코드로 반증된 사례로, 총량 불변이라 어떤 메트릭에도 잡히지 않는 유형이었다.
2. **측정 도구는 프로덕션 구성과의 정합이 생명** — CodeRabbit 2건이 모두 이 클래스(폴백 파라미터 불일치, 지표에 textbook 혼입). 수정 과정에서 corpus/evidence 분리로 해설서 기여분과 법률근거 승격의 단독 효과가 처음 구분됐다.
3. **준결정 측정은 밴드로 기록** — 정상 경로 도달이 반복 4회에서 12~15/18로 흔들려, 단일 수치 대신 67~83% 밴드 + 측정 횟수를 기준선에 남겼다.

## 3. 잔여 (다음 사이클 후보)

| 항목 | 성격 |
|------|------|
| c15(4대보험)·c16(근로자성) 전 측정 미도달 | 검색 로직이 아니라 **법률 코퍼스의 주제 커버리지 공백** — 행정해석·판례 수집 사이클로 해소 |
| 배포 후 관찰: `구어사전`·`법률근거 다양성 승격` 로그, `intent_provider="synthetic"` 비율 | fail-open이라 오작동이 조용함 — 양성 검증 항목 |
| 폴백 미도달 해고 계열 5건 | 사전 매핑은 정확하나 Q&A 4.9만 건이 pool 독식 — `top_k` 확장은 저작권 재검토 필요(기존 잔여와 동일 계열, 의도적 분리 유지) |
