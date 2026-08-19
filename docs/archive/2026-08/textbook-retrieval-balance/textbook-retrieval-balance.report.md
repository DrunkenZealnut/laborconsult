# textbook-retrieval-balance 완료 보고서

> Plan: `docs/01-plan/features/textbook-retrieval-balance.plan.md`
> Design: `docs/02-design/features/textbook-retrieval-balance.design.md`
> Analysis: `docs/03-analysis/textbook-retrieval-balance.analysis.md`
> 기간: 2026-08-19 (1일) | PR: [#52](https://github.com/DrunkenZealnut/laborconsult/pull/52) (머지 `2754b42`)

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | 해설서가 검색(pool)에는 잡히는데 rerank 절단으로 답변 근거에서 사장되는 문제를 **출처 다양성 승격**으로 해소 + 개별노동법실무 part4·Part5 적재 |
| 시작·완료 | 2026-08-19 (당일) |
| Match Rate | **97.8%** (23항목 대조, 불일치 0 · 부분 1 즉시 처리) |
| 코드 변경 | 14파일, +1,242/−22줄 (커밋 3개) |
| 테스트 | 오프라인 스위트 6종 통과, T23 회귀 **18검사** 신규 |
| 실측 | 도달률 **50.0% → 75.0%** (1 pass A/B, 고정 평가셋 24질의), 총 건수·노출 상한 불변 |
| 벡터 | `gaebyeol` 1,700 → **3,125** (실무테마 36~60, +1,425) |

### Value Delivered

| 관점 | 계획 | 실제 결과 |
|------|------|-----------|
| **Problem** | 해설서 4,993청크를 적재했지만 10질의 중 7건이 답변 근거 0건. 그중 3건은 hybrid pool에 **있었는데 Cohere rerank 절단에서 탈락** — 이미 확보한 근거가 사장됨. `decompose_query`(LLM) 비결정성 때문에 개선 효과를 측정할 방법 자체도 없었다 | 실측으로 병목을 2갈래로 분리(랭킹 탈락 3 / 검색 미도달 4) — **랭킹 탈락만** 이번 범위로 확정, 검색 미도달은 외부 전송량이 늘어 저작권 검토가 달라지므로 명시적 제외 |
| **Solution** | rerank 결과에 해설서 0건 + pool에 존재 시, 전체 랭킹 `2×top_n` 이내의 최상위 해설서 1건을 최하위 중복-출처와 **교체**. 선결로 고정 평가셋 구축 | `_ensure_textbook_presence` — 절단 지점 3곳(성공·무키·예외) 공통 적용, Cohere를 전체 랭킹 요청으로 전환(과금 불변). 고정 평가셋 24질의 + 1 pass A/B 하네스. 킬스위치 `TEXTBOOK_PROMOTE=off` |
| **Function & UX Effect** | 해설서 수록 주제 질문에서 출처 카드에 「노동법 해설서」 최소 1건 노출, 총 건수·지연 불변 | 도달률 50.0→**75.0%**(+4 = 발동 4건과 정합), 출처 분포 qa 86→83으로 완화. **프로덕션 실측**: "재택근무 근로시간 산정" 질의 출처에 textbook 2건 확인(2026-08-19, 완료 조건 7) |
| **Core Value** | 검색이 이미 확보한 근거를 랭킹 편중으로 버리지 않는다 — 코퍼스 투자를 노출 상한을 건드리지 않고 회수 | **저작권 경계 3중 고정**: 교체≠추가(총 116건 불변), 승격→가드 순서 구조 불변(I-5), G4/G4-T 수치·동작 무변경 — 코드·테스트(T23)·문서(CLAUDE.md)에서 각각 검증 |

---

## 1. 산출물

### 1.1 코드

| 파일 | 구분 | 내용 |
|------|------|------|
| `app/core/rag.py` | +97 | `_ensure_textbook_presence`(승격)·`_pick_swap_victim`(단일 출처 보호)·`_textbook_promote_enabled`(킬스위치)·`rerank_results` 3-exit 공통 `_finalize` + 전체 랭킹 요청 + `promoted` 마커 |
| `app/core/query_decomposer.py` | +6 | `QUERY_MERGE_HEADROOM` — pipeline·eval의 `+2` 리터럴 단일화 |
| `app/core/pipeline.py` | +3/−2 | 상수 참조 전환(동작 불변) |
| `eval_retrieval.py` | **신규** 236줄 | 고정 평가셋 하네스 — `--freeze`(분해 고정)·1 pass A/B(같은 pool에서 기준선·승격 파생)·지표 4종 |
| `data/eval_retrieval_queries.json` | **신규** | 24질의(new 10/old 6/wage 4/weak 4) + freeze된 분해 쿼리. LLM 산출물 스냅샷 — 손 교정 금지 명문화 |
| `test_precedent_ingest.py` | +99 | T23 18검사 — 불변식 I-1~I-6·무키 경로·가드 통과·킬스위치·마커 |
| `pinecone_upload_textbook.py` | +17/−4 | `gaebyeol` extra_parts에 part4·Part5, title 범위 1~35→**1~60** |

### 1.2 코퍼스·문서

- `laborlaw-v2`: gaebyeol 3,125벡터 (기존 1,700의 완전 상위집합 — 고아 0건, 조각별 게이트 전부 상한 내)
- `data/bm25_corpus.json.gz` 재빌드 (67,732문서)
- `CLAUDE.md` 다양성 승격 불릿 + G4-T 상호참조, `.env.example` 킬스위치, PDCA 문서 4종

## 2. 측정 (고정 평가셋 24질의, 1 pass A/B)

| 지표 | 기준선 | 승격 ON | 판정 |
|------|---:|---:|------|
| 도달률 (pool에 해설서 有 → 최종 도달) | 50.0% (8/16) | **75.0% (12/16)** | 목표 달성 |
| 승격 발동 | 0 | 4건 (16.7%) — 차이 +4와 정확히 일치 | 같은 pool 비교라 잡음 0 |
| 최종 컨텍스트 총 건수 | 116 | 116 | **불변** (교체≠추가) |
| G4/G4-T 차감 | 0 | 0 | 가드 동작 동일 |
| 잔여 미도달 4건 | — | 랭크 창 밖 후보 | 무관 해설서를 안 끌어올리는 설계 의도 |

## 3. 품질 활동 이력

| 단계 | 결과 |
|------|------|
| gap-detector (23항목) | 97.8% — 불일치 0, Low 2건 즉시 처리 |
| /simplify (4관점 병렬) | 발견 15 → **적용 10 · 스킵 4**(사유 기록). 핵심: 로그 의존 계측 → `promoted` 구조적 마커, 2회 실행 → 1 pass A/B(API 절반+잡음 제거), `QUERY_MERGE_HEADROOM` 단일화 |
| CodeRabbit (PR #52) | Actionable 5건 → 수용 4 · 의도적 스킵 1(fixture 분해 쿼리는 프로덕션 LLM 산출물 스냅샷 — 교정 시 이상적 쿼리 측정 + 기준선 무효, 사유를 fixture note에 명문화) |
| 프로덕션 실측 | 배포 `2754b42` success → 실질의 출처에 `source_type: textbook` 2건(자연 도달) 확인 |

## 4. 배운 것

- **계측은 반환값의 구조적 계약으로**: 승격 로그(INFO)가 로거 기본 레벨(WARNING)에 걸러져 발동 4건이 0으로 집계된 것을 실측 — "0"은 오류로 보이지 않고 "효과 없음"이라는 그럴듯한 오답으로 읽힌다. `promoted` 마커로 전환하고 T23-a4/a5로 봉인
- **A/B는 분기점 이후만 파생**: 분기가 결정적 인프로세스 단계면 실행을 2번 돌 이유가 없다 — 같은 pool 파생은 비용 절반에 비교 잡음이 원리적으로 0
- **평가 fixture는 프로덕션 산출물의 스냅샷**: LLM 분해 쿼리의 법령 번호 오류를 "교정"하면 프로덕션이 만들지 않는 이상적 쿼리로 측정하게 된다 — 리뷰 지적이 사실이어도 수용하지 않는 것이 맞는 경우

## 5. 남긴 것 (의도적 범위 밖)

| 항목 | 성격 |
|------|------|
| 검색 미도달 4건 (SIMPLE `top_k` 상향·소스별 쿼터) | 외부 전송량 증가 → 저작권 검토 재수행 필요. 별도 사이클 |
| 프로덕션 승격 발동 빈도 관찰 (`다양성 승격` 로그) | 운영 항목 — G6 게시판 제외 증가의 근사치 |
| gaebyeol part6~ 추가 시 title 범위 게이트 | 게이트 신호(본문 테마 번호)가 OCR 오독·상호참조로 오염 실측 — 신호 정확도 실측 후 도입 |
