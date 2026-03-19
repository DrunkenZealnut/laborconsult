# legal-case-benchmark Planning Document

> **Summary**: output_legal_cases 114건 대상 RAG 챗봇 정확도·응답시간 벤치마크
>
> **Project**: laborconsult (nodong.kr 노동법 Q&A + 임금계산기)
> **Date**: 2026-03-13
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 114건 법원판례/상담사례에 대해 현재 RAG 챗봇이 얼마나 정확하게 답변하는지, 한 건당 응답시간이 얼마인지 정량적 데이터가 없음 |
| **Solution** | 전체 파이프라인(intent 분석→RAG 검색→계산기→LLM 답변) 자동 벤치마크 스크립트 작성, LLM-as-Judge로 정확도 채점 |
| **Function/UX Effect** | 케이스별 정확도 점수(0~5)·응답시간·카테고리별 통계가 JSON+리포트로 산출되어 약점 영역 즉시 파악 가능 |
| **Core Value** | 데이터 기반 품질 개선 — 정확도 낮은 카테고리를 식별해 RAG 데이터·프롬프트·계산기 우선 개선 대상 도출 |

---

## 1. Overview

### 1.1 Purpose

`output_legal_cases/` 114건(서울시 노동상담사례집 기반)에 대해:
1. **정확도 측정**: 챗봇 답변 vs 전문가 답변 비교 → 카테고리별 정확도 산출
2. **응답시간 측정**: 전체 파이프라인 end-to-end 시간 프로파일링

### 1.2 Background

- 현재 `benchmark_legal_cases.py`는 **계산기 모듈만** 벤치마크 (질문→WageInput→계산 결과 vs 전문가 금액)
- 114건 중 계산 가능 29건만 대상 — 나머지 75건(채용취소·해고·괴롭힘·산재 등)은 측정 불가
- 사용자가 원하는 것은 **전체 RAG 파이프라인** 정확도 — 법률 상담 답변 품질 전체
- 기존 추출 데이터: `benchmark_extractions.json` (104건, Claude Haiku로 입력/정답 추출 완료)

### 1.3 현재 상태

| 항목 | 현재 | 목표 |
|------|------|------|
| 벤치마크 대상 | 계산 가능 29건 | 114건 전체 |
| 측정 항목 | 계산 결과 금액 일치 | 답변 품질 (법률 정확성·완전성·관련성) |
| 응답시간 | 미측정 | 케이스별 end-to-end 프로파일링 |
| 리포트 | 없음 | JSON + 카테고리별 통계 + 약점 분석 |

### 1.4 케이스 분포

| 카테고리 | 건수 | 유형 |
|----------|------|------|
| 해당없음 (채용·해고·괴롭힘 등 법률상담) | 32 | 순수 법률 Q&A |
| 퇴직금 | 11 | 계산+법률 |
| 산재보상 | 11 | 법률상담 |
| 연차수당 | 9 | 계산+법률 |
| 주휴수당 | 7 | 계산+법률 |
| 임금체불 | 6 | 계산+법률 |
| 해고예고수당 | 5 | 계산+법률 |
| 연장수당 | 4 | 계산 |
| 기타 (최저임금·통상임금·포괄임금·실업급여·4대보험·육아휴직·출산휴가·휴업수당·평균임금) | 29 | 혼합 |

### 1.5 Related Documents

- 기존 벤치마크: `benchmark_legal_cases.py` (계산기 전용)
- 기존 추출 데이터: `benchmark_extractions.json` (104건)
- RAG 파이프라인: `app/core/pipeline.py`

---

## 2. Scope

### 2.1 In Scope

- [ ] 114건 전체에 대해 full pipeline 실행 (intent 분석→RAG 검색→계산기→LLM 답변)
- [ ] LLM-as-Judge로 답변 정확도 채점 (0~5 스케일)
- [ ] 케이스별 end-to-end 응답시간 측정 + 단계별 프로파일링
- [ ] 카테고리별 통계 리포트 (평균 정확도, 평균 시간, 약점 분석)
- [ ] JSON 결과 파일 출력 (`benchmark_pipeline_results.json`)
- [ ] `--limit`, `--skip-to`, `--dry-run` 옵션

### 2.2 Out of Scope

- Pinecone 데이터 수정/보강 (결과 분석 후 별도 작업)
- 프롬프트 튜닝 (벤치마크 결과를 보고 별도 결정)
- 스트리밍 UI 테스트 (API 응답 기준 측정)
- Supabase 저장 (벤치마크는 로컬 실행)

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | 114건 각 케이스의 질문을 `process_question()` 파이프라인에 전달하여 답변 생성 | High | Pending |
| FR-02 | 전문가 답변(case .md 파일의 `## 답변` 섹션)을 정답으로 추출 | High | Pending |
| FR-03 | LLM-as-Judge: 챗봇 답변 vs 전문가 답변 비교 → 5항목 채점 (법률 정확성, 완전성, 관련성, 실용성, 계산 정확성) | High | Pending |
| FR-04 | 케이스별 end-to-end 시간 + 단계별 시간 측정 (분석/검색/계산/LLM) | High | Pending |
| FR-05 | 결과를 JSON으로 저장 (`benchmark_pipeline_results.json`) | High | Pending |
| FR-06 | 카테고리별 집계 통계 출력 (평균 점수, 평균 시간, min/max) | Medium | Pending |
| FR-07 | `--limit N` (N건만), `--skip-to N` (N번부터), `--category X` 옵션 | Medium | Pending |
| FR-08 | 중간 결과 저장 — 오류/중단 시 이어서 실행 가능 | Medium | Pending |
| FR-09 | 비용 예측 출력 (실행 전 Anthropic API 토큰 예상 비용) | Low | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| Performance | 114건 전체 실행 < 60분 | wall clock |
| Reliability | API rate limit/error 자동 재시도 (최대 3회) | 에러 카운트 |
| Cost | 전체 실행 $10 이내 (Claude Haiku judge + Sonnet pipeline) | 토큰 카운트 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] 114건 전체 실행 완료, 결과 JSON 생성
- [ ] 카테고리별 평균 정확도 점수 산출
- [ ] 케이스별 응답시간 프로파일 데이터 수집
- [ ] 약점 카테고리 식별 (정확도 3.0 미만인 카테고리)

### 4.2 Quality Criteria

- [ ] 모든 케이스에서 답변 생성 성공 (timeout/error 제외)
- [ ] Judge 채점 일관성 확인 (동일 케이스 재실행 시 ±0.5 이내)
- [ ] 시간 측정 정밀도 100ms 이내

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| API 비용 초과 ($10+) | Medium | Medium | `--limit 10` dry-run 후 비용 확인, Haiku judge 사용 |
| Rate limiting (Anthropic/OpenAI) | High | High | 케이스 간 1~2초 딜레이, exponential backoff |
| LLM Judge 편향 (자기 답변 과대평가) | Medium | Low | 전문가 답변만 기준, 구체적 채점 루브릭 제공 |
| 일부 케이스 파이프라인 오류 | Low | Medium | try/except로 개별 케이스 실패 격리, 결과에 error 기록 |
| Pinecone 검색 결과 부족 (일부 토픽 미색인) | Medium | Medium | 검색 결과 hit 수와 score도 함께 기록 |

---

## 6. Technical Design Preview

### 6.1 벤치마크 스크립트 구조

```
benchmark_pipeline.py
├── parse_case_file(path) → {question, expert_answer, metadata}
├── run_pipeline(question, config) → {answer, timing, search_hits, calc_result}
├── judge_answer(chatbot_answer, expert_answer, question) → {scores, reasoning}
├── aggregate_results(results) → {category_stats, overall_stats}
└── main() → JSON output + console summary
```

### 6.2 채점 루브릭 (LLM-as-Judge)

| 항목 | 0점 | 3점 | 5점 |
|------|-----|-----|-----|
| 법률 정확성 | 잘못된 법률 인용 | 대체로 맞지만 세부 오류 | 정확한 법률·판례 인용 |
| 완전성 | 핵심 내용 누락 | 주요 포인트 포함 | 전문가 답변 수준 포함 |
| 관련성 | 질문과 무관한 답변 | 대체로 관련 | 질문에 정확히 대응 |
| 실용성 | 추상적 답변만 | 일부 구체적 조언 | 구체적 절차·기관 안내 |
| 계산 정확성 | 계산 오류 | 근사치 (±10%) | 정확한 계산 (±1%) |

### 6.3 시간 프로파일링

```
{
  "case_id": 16,
  "timing": {
    "total_ms": 8523,
    "intent_analysis_ms": 1200,
    "rag_search_ms": 350,
    "calculator_ms": 45,
    "legal_api_ms": 1800,
    "llm_generation_ms": 5128
  }
}
```

### 6.4 비용 예측

| 단계 | 모델 | 예상 토큰/건 | 114건 합계 | 예상 비용 |
|------|------|-------------|-----------|----------|
| Intent 분석 | Haiku 4.5 | ~2K in + 0.5K out | ~285K | ~$0.28 |
| RAG 임베딩 | text-embedding-3-small | ~0.5K | ~57K | ~$0.001 |
| LLM 답변 | Sonnet 4.6 | ~4K in + 1.5K out | ~627K | ~$5.64 |
| Judge 채점 | Haiku 4.5 | ~3K in + 0.5K out | ~399K | ~$0.40 |
| **합계** | | | | **~$6.32** |

---

## 7. Implementation Order

1. [ ] `benchmark_pipeline.py` 기본 구조 작성 (parse + pipeline 호출 + timing)
2. [ ] LLM-as-Judge 채점 함수 구현 (Haiku 4.5, 5항목 루브릭)
3. [ ] 카테고리별 집계·통계 함수 구현
4. [ ] CLI 옵션 (`--limit`, `--skip-to`, `--category`, `--dry-run`)
5. [ ] 10건 pilot run → 비용·시간 검증
6. [ ] 114건 전체 실행 → 결과 분석

---

## 8. Next Steps

1. [ ] Write design document (`legal-case-benchmark.design.md`)
2. [ ] 10건 pilot run으로 비용·시간·Judge 품질 검증
3. [ ] 전체 실행 후 약점 카테고리 기반 개선 작업 식별

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-13 | Initial draft | Claude |
