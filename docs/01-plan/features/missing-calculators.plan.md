# 누락 계산 기능 추가 Planning Document

> **Summary**: nodong.kr Q&A 19,655건 분석 데이터 기반으로 현재 26개 계산기 모듈에 없는 계산 기능을 식별하고 추가
>
> **Project**: laborconsult
> **Author**: Claude
> **Date**: 2026-03-20
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | Q&A 분석 데이터에서 미매핑 계산 유형 241건(104종) 발견. 특히 "근로시간 계산" 27건, "연차 발생일수" 8건, "시급 환산" 2건 등 실제 수요가 있으나 계산기 미존재. 또한 `ordinary_wage`(통상임금)는 모듈이 존재하나 registry에 미노출 (46건 수요) |
| **Solution** | 3단계 개선: ① ordinary_wage registry 노출 ② 근로시간 계산기 신규 ③ 연차 발생일수 계산기 신규 + CALC_TYPE_MAP 매핑 보강 |
| **Function/UX Effect** | "통상임금 계산해줘" 요청 시 즉시 계산 결과 제공. 근로시간·연차발생 관련 질문에 정확한 수치 답변. 미매핑 241건 → ~50건 미만으로 감소 |
| **Core Value** | Q&A 데이터 기반 수요-공급 정합성 확보. 계산기 커버리지 92% → 97%+ 향상 |

---

## 1. Overview

### 1.1 Purpose

nodong.kr Q&A 19,655건을 `analyze_qna.py`로 분석한 결과, `calculation_type` 필드에서 198종의 계산 유형이 추출되었다. 이 중 현재 26개 계산기 + `CALC_TYPE_MAP`으로 매핑되지 않는 유형이 241건(104종) 존재한다. 본 Plan은 **실제 수요가 높은 미매핑 계산 유형**을 식별하고 계산기를 추가한다.

### 1.2 데이터 분석 결과

#### Q&A 분석 데이터 상위 계산 유형 (해당없음 제외)

| 순위 | 유형 | 건수 | 매핑 상태 |
|:---:|------|:---:|:--------:|
| 1 | 연차수당 | 2,786 | ✅ annual_leave |
| 2 | 퇴직금 | 2,484 | ✅ severance |
| 3 | 실업급여 | 1,384 | ✅ unemployment |
| 4 | 연장수당 | 1,347 | ✅ overtime |
| 5 | 주휴수당 | 1,044 | ✅ weekly_holiday |
| 6 | 최저임금 | 905 | ✅ minimum_wage |
| 7 | 해고예고수당 | 429 | ✅ dismissal |
| 8 | 육아휴직급여 | 167 | ✅ parental_leave |

#### 미매핑 주요 유형 (수요 높은 순)

| 유형 | 건수 | 현재 상태 | 제안 |
|------|:---:|----------|------|
| **기타** | 65 | 미분류 | 키워드 기반 재분류 로직 보강 |
| **임금** (일반) | 30 | 미매핑 | `CALC_TYPE_MAP`에 "임금" → `["minimum_wage", "overtime"]` 추가 |
| **통상임금** | 39+7=46 | 모듈 존재, registry 미노출 | `CALC_TYPES` + `_STANDARD_CALCS`에 ordinary_wage 등록 |
| **근로시간** 계산 | 11+5+5+4+2+2=29 | 모듈 미존재 | 신규 `working_hours` 계산기 |
| **연차 발생일수** | 6+2+2=10 | 기존 annual_leave는 "수당" 전용 | annual_leave 확장 또는 별도 함수 |
| **시급 환산** | 2 | 미매핑 | ordinary_wage로 매핑 가능 |
| **공휴일수당** | 2+1=3 | public_holiday 존재 | `CALC_TYPE_MAP` 매핑 추가 |

---

## 2. Scope

### 2.1 In Scope

- [x] FR-01: `ordinary_wage` registry 노출 — `CALC_TYPES`, `_STANDARD_CALCS` 등록
- [x] FR-02: `CALC_TYPE_MAP` 매핑 보강 — 미매핑 30+ 유형 추가
- [x] FR-03: 근로시간 계산기 (`working_hours`) 신규 모듈
- [x] FR-04: 연차 발생일수 계산 기능 — `annual_leave` 모듈 확장
- [x] FR-05: `resolve_calc_type()` 키워드 폴백 보강

### 2.2 Out of Scope

- 기존 계산기 로직 변경 (결과값 수정 없음)
- 프론트엔드 UI 변경
- 새로운 흐름도(calculator_flow) 추가 (별도 feature)
- "기타" 65건의 수동 재분류

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | **ordinary_wage registry 노출**: `CALC_TYPES`에 `"ordinary_wage": "통상임금 산출"` 추가. `_STANDARD_CALCS`에 디스패처 등록. `CALC_TYPE_MAP`에 `"통상임금" → ["ordinary_wage"]`, `"통상시급" → ["ordinary_wage"]` 매핑 변경 | High | Pending |
| FR-02 | **CALC_TYPE_MAP 매핑 보강**: `"임금" → ["minimum_wage", "overtime"]`, `"공휴일수당" → ["public_holiday"]`, `"시급환산" → ["ordinary_wage"]`, `"임금체불액" → ["wage_arrears"]`, `"중도입사 급여" → ["prorated"]`, `"소정근로시간" → ["weekly_hours_check"]` 등 미매핑 유형 추가 | High | Pending |
| FR-03 | **근로시간 계산기**: 월 소정근로시간·연간 소정근로시간 산출. 입력: 주당 근무일수, 일 근로시간, 주휴 포함 여부. 출력: 월 소정근로시간, 연 소정근로시간, 시급↔월급 환산 | Medium | Pending |
| FR-04 | **연차 발생일수 계산**: 근속기간(입사일~기준일)으로 법정 연차 발생일수 산출. 1년 미만 월 1일, 1~3년 15일, 3년 이후 2년마다 1일 추가 (최대 25일). 기존 `annual_leave` 모듈의 `_annual_leave_days()` 확장 | Medium | Pending |
| FR-05 | **resolve_calc_type 키워드 폴백 보강**: `_keyword_map`에 "근로시간" → `["working_hours"]`, "연차발생" → `["annual_leave"]`, "공휴일" → `["public_holiday"]` 등 추가 | Low | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement |
|----------|----------|-------------|
| Performance | 신규 계산기 실행 < 10ms | 로깅 |
| Compatibility | 기존 102건 배치 테스트 전량 통과 | `calculator_batch_test.py` |
| Reliability | 신규 매핑 추가로 인한 기존 매핑 변경 없음 | 코드 리뷰 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] "통상임금 계산해줘" 질문 시 ordinary_wage 계산 결과 반환
- [ ] "월 소정근로시간 계산" 질문 시 working_hours 계산 결과 반환
- [ ] "3년 근속 연차 며칠?" 질문 시 연차 발생일수 반환
- [ ] 기존 배치 테스트 102건 전량 통과
- [ ] 미매핑 계산 유형 241건 → 80건 미만으로 감소

### 4.2 Quality Criteria

- [ ] 기존 계산기 결과값 변경 0건
- [ ] 신규 코드 변경 파일 ≤ 5개

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| FR-01: ordinary_wage 노출로 기존 계산 흐름 변경 | Medium | Low | ordinary_wage는 이미 모든 계산의 기초. 독립 호출만 추가하며 기존 호출 경로 수정 없음 |
| FR-02: 잘못된 매핑으로 엉뚱한 계산기 호출 | Medium | Medium | 기존 매핑 변경 금지. 신규 키 추가만. 배치 테스트로 검증 |
| FR-03: 근로시간 계산 엣지케이스 (교대제, 격주 등) | Low | Medium | 1차 범위: 표준 근무형태(5일/주). 교대제·격주는 2차 |

---

## 6. Architecture Considerations

### 6.1 변경 대상 모듈

```
wage_calculator/
├── facade/
│   ├── registry.py         ← FR-01, FR-02, FR-05: CALC_TYPES, CALC_TYPE_MAP, _STANDARD_CALCS, resolve_calc_type
│   └── helpers.py          ← FR-01: _pop_ordinary_wage() 추가
├── calculators/
│   ├── ordinary_wage.py    ← FR-01: 이미 존재, calc_ordinary_wage() 독립 반환 로직 추가
│   ├── working_hours.py    ← FR-03: 신규 모듈
│   └── annual_leave.py     ← FR-04: _annual_leave_days() 독립 호출 지원
└── result.py               ← FR-03, FR-04: 결과 포매터 섹션 추가 (필요 시)
```

### 6.2 FR-03 근로시간 계산기 설계 방향

```python
# working_hours.py (신규)
def calc_working_hours(inp: WageInput, result: WageResult) -> None:
    """월·연 소정근로시간 + 시급↔월급 환산"""
    daily = inp.schedule.daily_work_hours    # 예: 8.0
    weekly_days = inp.schedule.weekly_work_days  # 예: 5

    # 주 소정근로시간
    weekly_hours = daily * weekly_days

    # 월 소정근로시간 (= (주 소정 + 주휴 8h) × 365/12/7)
    weekly_with_holiday = weekly_hours + daily  # 주휴 포함
    monthly_hours = weekly_with_holiday * (365 / 12 / 7)  # ≈ 209시간

    # 연 소정근로시간
    annual_hours = weekly_hours * 52

    # 시급 ↔ 월급 환산
    if inp.hourly_wage:
        monthly_wage = inp.hourly_wage * monthly_hours
    elif inp.monthly_wage:
        hourly_wage = inp.monthly_wage / monthly_hours
```

### 6.3 구현 순서

| Phase | Task | 의존성 | 변경량 |
|-------|------|--------|--------|
| 1 | FR-01: ordinary_wage registry 노출 | 없음 | `registry.py` +5줄, `helpers.py` +15줄 |
| 2 | FR-02: CALC_TYPE_MAP 매핑 보강 | 없음 | `registry.py` +15줄 |
| 3 | FR-05: resolve_calc_type 키워드 보강 | FR-02 | `registry.py` +10줄 |
| 4 | FR-03: working_hours 신규 모듈 | 없음 | 신규 ~80줄 + registry +5줄 |
| 5 | FR-04: annual_leave 연차발생일수 | 없음 | `annual_leave.py` +30줄 |

---

## 7. 데이터 기반 우선순위 매트릭스

| 계산 유형 | Q&A 수요 | 구현 난이도 | 기존 모듈 활용 | 우선순위 |
|----------|:--------:|:---------:|:------------:|:-------:|
| 통상임금 (registry 노출) | 46건 | 최소 | ordinary_wage 존재 | **1순위** |
| CALC_TYPE_MAP 보강 | 30+건 | 최소 | 매핑만 추가 | **1순위** |
| 근로시간 계산 | 29건 | 중간 | 신규 모듈 | **2순위** |
| 연차 발생일수 | 10건 | 낮음 | annual_leave 확장 | **3순위** |

---

## 8. Next Steps

1. [ ] Design 문서 작성 (`missing-calculators.design.md`)
2. [ ] FR-01 + FR-02 우선 구현 (매핑만 추가, 리스크 최소)
3. [ ] FR-03 working_hours 신규 모듈 구현
4. [ ] 배치 테스트 검증

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-20 | Initial draft — Q&A 19,655건 분석 기반 5 FRs | Claude |
