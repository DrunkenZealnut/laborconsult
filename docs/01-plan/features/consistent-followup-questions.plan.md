# consistent-followup-questions Planning Document

> **Summary**: 챗봇 추가정보 요청 질문을 LLM 자유형 텍스트 대신 계산기 모듈 필수 필드 기반 코드 판정으로 대체하여 일관성 확보
>
> **Project**: laborconsult
> **Author**: zealnutkim
> **Date**: 2026-03-08
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 챗봇이 사용자에게 추가 정보를 요청할 때 LLM(Claude Haiku)이 `missing_info`를 자유형 텍스트로 생성하여, 동일 질문에도 매번 다른 항목/표현이 나옴. 사용자 경험 저하 및 신뢰도 하락 |
| **Solution** | 15개 계산 유형별 필수 필드(`_REQUIRED_FIELDS`)를 코드에 정의하고, `_compute_missing_info()` 함수가 `extracted_info`와 비교하여 누락 항목을 코드 레벨에서 판정. LLM의 `missing_info`를 완전 대체 |
| **Function/UX Effect** | 동일 질문 → 항상 동일한 추가 질문. 표현도 "임금 (월급 또는 연봉)" 등 표준화된 한국어로 고정. 불필요한 질문 감소 (LLM이 과도하게 요구하던 4~5개 → 필수 1~2개만) |
| **Core Value** | 추가 질문 일관성 → 사용자 신뢰도 향상, 불필요한 대화 왕복 감소, 계산기 모듈과 분석기 간 계약(contract) 명확화 |

---

## 1. Overview

### 1.1 Purpose

챗봇의 추가정보 요청(follow-up) 질문이 동일한 사용자 질문에 대해 매번 달라지는 문제를 해결한다.
현재 LLM이 자유형으로 생성하는 `missing_info`를 계산기 모듈이 실제 필요로 하는 필수 필드 목록으로 대체하여,
**코드 기반의 결정론적(deterministic) 누락 정보 판정**을 구현한다.

### 1.2 Background

**현재 문제 (AS-IS)**:
1. `analyze_intent()` → Claude Haiku가 `missing_info`를 자유형 텍스트 배열로 생성
2. 동일 질문을 3회 입력 시 매번 다른 항목이 나옴:
   - 시도 1: `['퇴사 전 월평균 임금', '고용보험 가입 기간', '퇴사 사유 상세', '현재 구직활동 여부']`
   - 시도 2: `['정확한 입사일자', '고용보험 가입 여부', '퇴사 사유 구체적 내용', '퇴사 후 재취업 여부']`
   - 시도 3: `['퇴사 전 월평균 임금', '고용보험 가입 기간', '퇴사 사유 구체적 내용', '현재 구직활동 여부']`
3. 표현도 매번 달라짐 ("퇴사 전 월평균 임금" vs "퇴사 직전 3개월 월평균 급여" 등)
4. 불필요한 항목 요구 (예: "현재 구직활동 여부"는 실업급여 계산에 불필요)

**부수 문제**:
- 날짜 해석 오류: "2월28일"을 현재 연도(2026)가 아닌 2025로 해석
- `temperature` 미설정으로 LLM 추출 결과 자체도 비결정론적

### 1.3 Related Documents

- 관련 코드: `app/core/pipeline.py`, `app/core/analyzer.py`, `app/core/composer.py`
- 계산기 구조: `wage_calculator/facade.py`, `wage_calculator/models.py`
- 프롬프트: `app/templates/prompts.py`

---

## 2. Scope

### 2.1 In Scope

- [x] 15개 계산 유형별 필수 필드 매핑 테이블 정의 (`_REQUIRED_FIELDS`)
- [x] 코드 기반 누락 정보 판정 함수 (`_compute_missing_info()`)
- [x] `process_question()`에서 LLM `missing_info`를 코드 판정 결과로 교체
- [x] `temperature=0` 설정으로 LLM 추출 일관성 강화
- [x] 날짜 연도 보정 함수 (`_correct_date_year()`)
- [x] 시스템 프롬프트에 현재 날짜 주입 (3개 지점)

### 2.2 Out of Scope

- 다국어 추가 질문 지원 (현재 한국어만)
- 추가 질문 UI 개선 (버튼/선택지 방식 등)
- 계산기 모듈 자체의 필수 필드 변경

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | 동일 질문에 대해 항상 동일한 추가 질문 생성 | High | Done |
| FR-02 | 추가 질문은 계산기가 실제 필요로 하는 필드만 포함 | High | Done |
| FR-03 | 추가 질문 표현을 표준화된 한국어로 고정 | High | Done |
| FR-04 | LLM이 날짜를 잘못 추정해도 코드에서 보정 | High | Done |
| FR-05 | LLM 추출 결과의 일관성 강화 (temperature=0) | Medium | Done |
| FR-06 | 기존 follow-up 흐름과 호환 유지 | High | Done |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| 일관성 | 동일 질문 3회 반복 시 100% 동일 결과 | `test_followup_consistency.py` |
| 성능 | 추가 판정 로직 < 1ms | 코드 내 dict lookup만 사용 |
| 호환성 | 기존 15개 계산기 모두 정상 작동 | `wage_calculator_cli.py` 32개 케이스 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [x] `_REQUIRED_FIELDS` 15개 계산 유형 정의 완료
- [x] `_compute_missing_info()` 함수 구현
- [x] `process_question()`에서 코드 기반 missing_info로 교체
- [x] 3개 샘플 질문 × 3회 반복 = 9회 모두 일관된 결과
- [x] `_correct_date_year()` 단위 테스트 6/6 통과
- [x] 날짜 보정 API 테스트 3/3 통과

### 4.2 Quality Criteria

- [x] 코드 기반 missing_info 3회 일관성: 100%
- [x] 날짜 보정 정확도: 100% (6/6 단위 + 3/3 API)
- [x] 기존 기능 영향 없음 (graceful fallback 유지)

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| 새 계산기 추가 시 `_REQUIRED_FIELDS` 누락 | Medium | Medium | 계산기 추가 시 필수 필드 등록 절차 문서화 |
| LLM이 `extracted_info`에 필드를 추출하지 않아 코드 판정이 달라짐 | Medium | Low | `temperature=0` + 프롬프트 강화로 추출 안정화 |
| 사용자가 정보를 제공했는데 불필요한 추가 질문 발생 | Low | Low | 필수 필드를 최소한으로 설정 (예: unemployment는 임금만) |

---

## 6. Architecture Considerations

### 6.1 데이터 흐름 (TO-BE)

```
사용자 질문
  ↓
analyze_intent() [temperature=0, 날짜 주입]
  ↓
AnalysisResult (extracted_info, calculation_types)
  ↓
_compute_missing_info()  ← LLM missing_info 대체
  ├── _REQUIRED_FIELDS[calc_type] 조회
  ├── extracted_info와 비교
  └── 누락 필드 목록 반환 (고정 한국어 표현)
  ↓
missing 있음 → compose_follow_up() → 추가 질문
missing 없음 → 바로 계산 실행
```

### 6.2 핵심 설계 결정

| Decision | Options | Selected | Rationale |
|----------|---------|----------|-----------|
| 누락 판정 방식 | LLM 자유형 / 코드 기반 | 코드 기반 | 결정론적, 일관성 100% |
| 필수 필드 정의 | 하드코딩 / DB / 설정 파일 | 하드코딩 (dict) | 계산기가 15개로 고정, 변경 빈도 낮음 |
| 대체 필드 처리 | OR 그룹 (set) | set 기반 any() | "월급 또는 연봉 또는 시급" 중 하나만 있으면 충족 |
| 날짜 보정 | 프롬프트만 / 코드 보정 | 코드 보정 | LLM 프롬프트만으로는 불안정 |

### 6.3 변경 대상 파일

| 파일 | 변경 유형 | 내용 |
|------|----------|------|
| `app/core/pipeline.py` | 수정 | `_REQUIRED_FIELDS` + `_compute_missing_info()` 추가, `process_question()`에서 사용 |
| `app/core/analyzer.py` | 수정 | `_correct_date_year()` 추가, `temperature=0`, 날짜 보정 적용 |
| `app/templates/prompts.py` | 수정 | `ANALYZER_SYSTEM`에 `{today}` 플레이스홀더 + 날짜 해석 규칙 |
| `app/core/pipeline.py` | 수정 | `SYSTEM_PROMPT_TEMPLATE`로 변경, `_extract_params`에 날짜 주입 |
| `chatbot.py` | 수정 | `SYSTEM_PROMPT_TEMPLATE`로 변경, 날짜 주입 |

---

## 7. 계산 유형별 필수 필드 매핑

| 계산 유형 | 필수 필드 (OR 그룹) | 추가 질문 표현 |
|----------|-------------------|---------------|
| overtime | 임금 + 1일근로시간 + 연장근로시간 | "임금 (시급/월급/연봉)", "1일 소정근로시간", "주당 연장근로시간" |
| minimum_wage | 임금 + 1일근로시간 | "현재 받는 임금 (시급/월급/연봉)", "1일 소정근로시간" |
| weekly_holiday | 임금 + 근무일수 + 1일근로시간 | "임금 (시급/월급/연봉)", "주당 근무일수", "1일 소정근로시간" |
| severance | 임금 + 근무기간 | "임금 (월급 또는 연봉)", "입사일 또는 근무기간" |
| annual_leave | 임금 + 근무기간 | "임금 (월급 또는 연봉)", "입사일 또는 근무기간" |
| dismissal | 임금 + 근무기간 | "임금 (월급 또는 연봉)", "입사일 또는 근무기간" |
| unemployment | 임금 | "퇴직 전 월 평균 임금" |
| insurance | 임금 | "임금 (월급 또는 연봉)" |
| parental_leave | 임금 + 휴직개월수 | "임금 (월급 또는 연봉)", "육아휴직 예정 개월수" |
| maternity_leave | 임금 | "임금 (월급 또는 연봉)" |
| wage_arrears | 체불액 + 체불발생일 | "체불 임금액", "체불 발생일 (원래 급여일)" |
| compensatory_leave | 임금 + 연장근로시간 | "임금 (시급/월급)", "주당 연장근로시간" |
| flexible_work | 임금 | "임금 (시급/월급)" |
| comprehensive | 월급총액 + 1일근로시간 + 연장근로시간 | "포괄임금제 월급 총액", "1일 소정근로시간", "월 고정 연장근로시간" |
| eitc | 소득 | "연간 총 소득 (또는 월급)" |

---

## 8. Next Steps

1. [x] Design 문서 작성 (`consistent-followup-questions.design.md`)
2. [x] 구현 완료 및 테스트 통과
3. [ ] Gap 분석 (`/pdca analyze consistent-followup-questions`)
4. [ ] 완료 보고서 (`/pdca report consistent-followup-questions`)

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-08 | Initial draft | zealnutkim |
