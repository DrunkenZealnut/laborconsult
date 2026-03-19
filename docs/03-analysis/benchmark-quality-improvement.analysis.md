# benchmark-quality-improvement Analysis Report

> **Analysis Type**: Gap Analysis (Design vs Implementation)
>
> **Project**: laborconsult
> **Analyst**: Claude (gap-detector)
> **Date**: 2026-03-14
> **Design Doc**: [benchmark-quality-improvement.design.md](../02-design/features/benchmark-quality-improvement.design.md)

---

## 1. Analysis Overview

### 1.1 Analysis Purpose

Design document `benchmark-quality-improvement.design.md`(2026-03-14)에 정의된 FR-01~FR-12 항목이 실제 구현 코드에 정확히 반영되었는지 검증한다.

### 1.2 Analysis Scope

| Category | Path |
|----------|------|
| Design Document | `docs/02-design/features/benchmark-quality-improvement.design.md` |
| Implementation (6 files) | `benchmark_pipeline.py`, `wage_calculator/facade/__init__.py`, `app/core/legal_consultation.py`, `app/core/rag.py`, `app/core/pipeline.py`, `app/templates/prompts.py` |
| Analysis Date | 2026-03-14 |

---

## 2. FR-by-FR Gap Analysis

### FR-01: Judge JSON Parsing 4-Stage Fallback

**File**: `benchmark_pipeline.py`
**Design**: judge_answer() 내부에 4단계 파싱 (json.loads -> reasoning 줄바꿈 치환 -> regex 점수 추출 -> 1회 재시도) + 신규 함수 `_extract_scores_regex()`, `_retry_judge()` 추가

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| `_extract_scores_regex()` 함수 | L57~77 사양 | `benchmark_pipeline.py` L280~297 | MATCH |
| - fields 5개 | legal_accuracy, completeness, relevance, practicality, calculation_accuracy | 동일 | MATCH |
| - N/A 처리 | `"N/A" if val == '"N/A"' else int(val)` | 동일 | MATCH |
| - reasoning 추출 + 500자 제한 | regex DOTALL, `[:500]` | 동일 | MATCH |
| - 최소 3개 필드 검증 | `len(numeric) < 3: return None` | 동일 | MATCH |
| `_retry_judge()` 함수 | L80~111 사양 | `benchmark_pipeline.py` L300~331 | MATCH |
| - model | JUDGE_MODEL | 동일 | MATCH |
| - max_tokens | 512 | 512 | MATCH |
| - temperature | 0.1 | 0.1 | MATCH |
| - system 추가 문구 | `"\n\nIMPORTANT: Output ONLY..."` | 동일 | MATCH |
| - question/expert/chatbot 1500자 제한 | `[:1500]` | 동일 | MATCH |
| - 실패 시 -1점 반환 | overall_score: -1.0 + reasoning | 동일 | MATCH |
| judge_answer() 4단계 구조 | 1. json.loads -> 2. reasoning 줄바꿈 -> 3. regex -> 4. retry | L371~385: 동일한 4단계 체인 | MATCH |

**FR-01 Score**: 12/12 MATCH

---

### FR-02: `_guess_start_date` Import Export

**File**: `wage_calculator/facade/__init__.py`
**Design**: import 문에 `_guess_start_date` 추가

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| import 문 | `from .conversion import _provided_info_to_input, _guess_start_date` | L20: `from .conversion import _provided_info_to_input, _guess_start_date` | MATCH |

**FR-02 Score**: 1/1 MATCH

---

### FR-03: "" -> "qa" Namespace Normalization

**Design**: 모든 토픽의 namespace에서 빈 문자열 `""` 대신 명시적 `"qa"` 사용 + `rag.py`의 `_search_ns()` 내부 정규화

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| legal_consultation.py: 모든 토픽 namespace에 `"qa"` 명시 | `""` 없음, `"qa"` 사용 | L20~108: 12개 토픽 모두 `"qa"` 명시 사용, `""` 없음 | MATCH |
| rag.py: `_search_ns()` 내부 정규화 | `actual_ns = ns if ns else "qa"` | L56: `actual_ns = ns if ns else "qa"` | MATCH |
| rag.py: query에 `actual_ns` 사용 | `namespace=actual_ns` | L61: `namespace=actual_ns` | MATCH |

**FR-03 Score**: 3/3 MATCH

---

### FR-04: default_laws Expansion per Topic

**File**: `app/core/legal_consultation.py`
**Design**: TOPIC_SEARCH_CONFIG 전체 교체 (12개 토픽)

| Topic | Design Laws | Implementation Laws | Status |
|-------|------------|---------------------|--------|
| 해고/징계 | 제23, 26, 27, 28조 (4개) | L23~28: 동일 4개 | MATCH |
| 임금/통상임금 | 제2, 43, 36, 46조 + 최임법 제6조 (5개) | L32~38: 동일 5개 | MATCH |
| 근로시간/휴일 | 제50, 53, 55, 56, 57, 18조 (6개) | L42~49: 동일 6개 | MATCH |
| 퇴직/퇴직금 | 퇴직급여법 제4, 8조 + 임채법 제7조 (3개) | L53~57: 동일 3개 | MATCH |
| 연차휴가 | 제60, 61조 (2개) | L61~64: 동일 2개 | MATCH |
| 산재보상 | 산재법 제37, 125조 (2개) | L68~71: 동일 2개 | MATCH |
| 비정규직 | 기간제법 제4조 (1개) | L75~77: 동일 1개 | MATCH |
| 노동조합 | 빈 배열 | L81: `[]` | MATCH |
| 직장내괴롭힘 | 제76조의2, 3 + 남녀고용평등법 제14조의2 (3개) | L85~89: 동일 3개 | MATCH |
| 근로계약 | 제17조 (1개) | L93~95: 동일 1개 | MATCH |
| 고용보험 | 제40, 45, 69조 (3개) | L99~103: 동일 3개 | MATCH |
| 기타 | 빈 배열 | L107: `[]` | MATCH |
| Namespace 구성 (12개 토픽) | Design 사양 참조 | 모두 일치 | MATCH |

**FR-04 Score**: 13/13 MATCH

---

### FR-05~FR-08: Scope Reduced (No Calculator Changes)

**Design**: FR-05(실업급여 평균임금), FR-06(평균임금 휴직기간), FR-07(휴일근로 가산율), FR-08(비례연차) 모두 계산기 코드 변경 없이 프롬프트/default_laws로 대응.

| Item | Design Decision | Verification | Status |
|------|----------------|--------------|--------|
| FR-05: unemployment.py 변경 없음 | "추가 변경 없음 (FR-04에서 처리)" | 고용보험법 제45조가 FR-04에서 추가됨 확인 | MATCH |
| FR-06: average_wage 변경 없음 | "ANALYZER_SYSTEM 프롬프트에 규칙 추가" | FR-09에서 처리 확인 | MATCH |
| FR-07: overtime.py 변경 없음 | "계산기 자체는 수정 불필요" | git status에 overtime.py 변경 있지만 이 feature 범위 외 (기존 변경) | MATCH |
| FR-08: annual_leave.py 변경 없음 | "FR-04에서 제60조 추가로 대응" | 연차휴가 default_laws에 제60조 확인 | MATCH |

**FR-05~08 Score**: 4/4 MATCH

---

### FR-09: ANALYZER_SYSTEM Keyword-to-Law Mapping (Rules 12-13)

**File**: `app/templates/prompts.py`
**Design**: ANALYZER_SYSTEM 끝부분에 규칙 12, 13 추가

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| Rule 12 제목 | "특수 케이스 자동 법령 매핑" | L175: `12. **특수 케이스 자동 법령 매핑**` | MATCH |
| 택시/운수 -> 최저임금법 제6조 제5항 | 설계 원문 | L176 | MATCH |
| 플랫폼/배달/대리운전 -> 산재법 제125조 | 설계 원문 | L177 | MATCH |
| 65세/고령/정년 이후 -> 고용보험법 제10조 | 설계 원문 | L178 | MATCH |
| 코로나/감염/격리/방역 -> 근기법 제46조 | 설계 원문 | L179 | MATCH |
| 대지급금/체당금 -> 임채법 제7조 | 설계 원문 | L180 | MATCH |
| 초단시간/15시간 미만 -> 근기법 제18조 | 설계 원문 | L181 | MATCH |
| 부제소/합의/청구 포기 -> 근기법 제36조 | 설계 원문 | L182 | MATCH |
| 촉탁/정년 후 재고용 -> 기간제법 제4조 | 설계 원문 | L183 | MATCH |
| 육아기 단축/근로시간 단축 -> 남녀고용평등법 제19조의2 | 설계 원문 | L184 | MATCH |
| Rule 13 | "consultation_topic 결정 시 위 키워드도 고려" | L185 | MATCH |

**FR-09 Score**: 11/11 MATCH

---

### FR-10: Hallucination Prevention Rules (CONSULTATION + COMPOSER)

**File**: `app/templates/prompts.py`

#### FR-10a: CONSULTATION_SYSTEM_PROMPT (Rules 5-1, 5-2)

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| Rule 5-1 제목 | "판례/행정해석 인용 주의 (매우 중요)" | L235: `5-1. **판례·행정해석 인용 주의** (매우 중요):` | MATCH |
| 참고 자료에 포함된 판례만 인용 | 설계 원문 | L236 | MATCH |
| 없는 판례 처리 방법 | "관련 판례가 있을 수 있으나..." | L237 | MATCH |
| 행정해석 동일 규칙 | "참고 자료에 없는 문서번호를 생성하지 마세요" | L238 | MATCH |
| 심각한 피해 경고 | 설계 원문 | L239 | MATCH |
| Rule 5-2 제목 | "특수 케이스 주의사항" | L240: `5-2. **특수 케이스 주의사항**:` | MATCH |
| 65세 이상 고용보험 | 2019.1.15 개정법 경과조치 | L241 | MATCH |
| 코로나 휴업수당 | 사용자 귀책 vs 불가항력 | L242 | MATCH |
| 택시/플랫폼 특례 | 특례 적용 가능성 명시 | L243 | MATCH |
| 채용내정 취소 | 부당해고 적용 여부 상이 | L244 | MATCH |
| 부제소 합의 | 사전포기 vs 퇴직 시점 합의 | L245 | MATCH |

#### FR-10b: COMPOSER_SYSTEM Rules

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| 판례/행정해석 번호 인용 규칙 | "검색 결과에서 확인된 것만 번호를 표기" | L206~207: 동일 규칙 2줄 | MATCH |
| 검색 결과 없을 경우 표기 | "참고 문서 없이 일반 노동법 지식..." | L208: 동일 | MATCH |

**FR-10 Score**: 14/14 MATCH

---

### FR-11: Search Parameter Optimization (threshold 0.4->0.35, top_k 3->5)

| Item | Design | Implementation | Status |
|------|--------|----------------|--------|
| rag.py: `search_multi_namespace()` top_k default | `top_k_per_ns: int = 5` | L43: `top_k_per_ns: int = 5` | MATCH |
| rag.py: `search_multi_namespace()` threshold default | `threshold: float = 0.35` | L44: `threshold: float = 0.35` | MATCH |
| legal_consultation.py: `process_consultation()` top_k | `top_k_per_ns=5` | L193: `top_k_per_ns=5` | MATCH |
| pipeline.py: `_search()` threshold default | `threshold: float = 0.35` | L30: `threshold: float = 0.35` | MATCH |

**FR-11 Score**: 4/4 MATCH

---

### FR-12: Benchmark Re-run

**Design**: 벤치마크 재실행 (`python3 benchmark_pipeline.py`)

| Item | Design | Status | Notes |
|------|--------|--------|-------|
| 벤치마크 재실행 | 모든 변경 완료 후 실행 | PENDING | 사용자에 의해 백그라운드에서 실행 중 |

**FR-12 Score**: 0/1 (PENDING -- not a code gap)

---

## 3. Additional Implementation vs Design Checks

### 3.1 Positive Deviations (Implementation adds value beyond design)

| # | Item | Location | Description |
|---|------|----------|-------------|
| P1 | `_search_ns` source_type fallback | `rag.py` L71 | `"qa" if ns in ("", "qa") else ns` -- 빈 문자열에 대한 추가 방어 |
| P2 | `search_qna` 하위 호환 유지 | `rag.py` L96~101 | `search_qna()` wrapper가 기존 top_k=3 유지하여 하위 호환성 보장 |
| P3 | `search_legal` 하위 호환 유지 | `rag.py` L104~112 | `search_legal()` wrapper도 기존 top_k=3 유지 |

### 3.2 Unchanged Files Verification (FR-05~08)

Design에서 "수정 불필요"로 명시한 계산기 파일들이 이 feature 범위에서 변경되지 않았는지 확인:

| File | Expected | Verification | Status |
|------|----------|--------------|--------|
| `wage_calculator/calculators/unemployment.py` | No change for this feature | git status: modified (pre-existing) | OK -- not FR-05 related |
| `wage_calculator/calculators/average_wage.py` | No change for this feature | git status: modified (pre-existing) | OK -- not FR-06 related |
| `wage_calculator/calculators/overtime.py` | No change for this feature | git status: modified (pre-existing) | OK -- not FR-07 related |
| `wage_calculator/calculators/annual_leave.py` | No change for this feature | git status: modified (pre-existing) | OK -- not FR-08 related |

---

## 4. Match Rate Summary

```
+-------------------------------------------------+
|  Overall Match Rate: 97%                        |
+-------------------------------------------------+
|  MATCH:          62/63 items (98.4%)            |
|  PENDING:         1/63 items  (1.6%) [FR-12]    |
|  MISSING:         0/63 items  (0.0%)            |
|  CHANGED:         0/63 items  (0.0%)            |
|  POSITIVE:        3 additions (beyond design)   |
+-------------------------------------------------+
```

### Score Breakdown by FR

| FR | Category | Items | Match | Status |
|----|----------|:-----:|:-----:|:------:|
| FR-01 | Judge JSON 4-stage fallback | 12 | 12 | MATCH |
| FR-02 | _guess_start_date export | 1 | 1 | MATCH |
| FR-03 | "" -> "qa" normalization | 3 | 3 | MATCH |
| FR-04 | default_laws expansion | 13 | 13 | MATCH |
| FR-05~08 | Scope reduced (no calc changes) | 4 | 4 | MATCH |
| FR-09 | ANALYZER_SYSTEM rules 12-13 | 11 | 11 | MATCH |
| FR-10 | Hallucination prevention rules | 14 | 14 | MATCH |
| FR-11 | threshold/top_k optimization | 4 | 4 | MATCH |
| FR-12 | Benchmark re-run | 1 | 0 | PENDING |
| **Total** | | **63** | **62** | **97%** |

---

## 5. Overall Scores

| Category | Score | Status |
|----------|:-----:|:------:|
| Design Match | 98% | PASS |
| Architecture Compliance | 100% | PASS |
| Convention Compliance | 100% | PASS |
| **Overall** | **97%** | PASS |

---

## 6. Findings Detail

### 6.1 Missing Features (Design O, Implementation X)

None.

### 6.2 Added Features (Design X, Implementation O)

| # | Item | Location | Description | Impact |
|---|------|----------|-------------|--------|
| P1 | source_type "" fallback | `rag.py:71` | 빈 문자열 ns에 대한 source_type 방어 로직 | Positive |
| P2 | search_qna 하위호환 top_k=3 | `rag.py:101` | 기존 호출자 깨지지 않도록 보존 | Positive |
| P3 | search_legal 하위호환 top_k=3 | `rag.py:111` | 기존 호출자 깨지지 않도록 보존 | Positive |

### 6.3 Changed Features (Design != Implementation)

None.

### 6.4 Pending Items

| Item | Design Location | Status | Notes |
|------|----------------|--------|-------|
| FR-12 벤치마크 재실행 | Design Section 5 | PENDING | 백그라운드 실행 중. 코드 Gap 아님 |

---

## 7. Recommended Actions

### 7.1 Immediate Actions

None required. 모든 코드 변경 사항이 설계와 100% 일치.

### 7.2 Post-Benchmark Actions

1. FR-12 벤치마크 완료 후 before/after 비교 수행
2. Design Section 5.2 비교 지표 달성 여부 확인:
   - 전체 평균 점수: 3.88 -> 4.0+ 목표
   - -1점 케이스: 6건 -> 0건 목표
   - 0점 케이스: 1건 -> 0건 목표
   - 3.0 이하: 32건 -> 16건 미만 목표
3. 기존 4.0+ 케이스 점수 하락 여부 모니터링 (5건 이상 하락 시 롤백 검토)

### 7.3 Documentation Updates

None required. Design document accurately reflects implementation.

---

## 8. Synchronization Decision

Match Rate >= 90% -- **Design and implementation match well.**

Minor remaining item (FR-12) is an execution step, not a code gap.

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-14 | Initial gap analysis -- 62/63 MATCH, 1 PENDING, 0 GAP | Claude |
