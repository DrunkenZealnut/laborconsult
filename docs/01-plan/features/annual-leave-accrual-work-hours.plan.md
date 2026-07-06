# 연차발생일수 + 근로시간산정기 Planning Document

> **Summary**: 기존 25개 계산기에 연차 발생일수 계산기(#26)와 교대근무 근로시간 산정기(#27)를 추가하여 nodongok Q&A에서 발견된 핵심 미커버 영역(47건) 해소
>
> **Project**: laborconsult
> **Author**: Claude
> **Date**: 2026-03-20
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 연차 "수당"은 계산 가능하나 입사일 기준 연차 "발생일수" 독립 계산 불가(15건). 교대근무자의 월 소정/연장/야간 근로시간 산정기가 없어 32건의 질문을 처리하지 못함 |
| **Solution** | ① 연차발생일수 계산기: 입사일/회계연도 기준, 무급휴직 제외, 단시간근로자 비례 지원 ② 근로시간산정기: 2교대·3교대·4교대·격일근무 패턴별 월 소정/연장/야간/휴일 시간 자동 산출 |
| **Function/UX Effect** | 챗봇에서 "연차 몇 개 발생하나요?"와 "교대근무 월 근로시간은?" 질문에 정확한 계산 결과 제공. 기존 연차수당·연장수당 계산기의 입력값으로도 활용 |
| **Core Value** | Q&A 미커버 영역 47건 해소 → 계산기 커버리지 25→27종. 연차발생은 연차수당의 전제 계산이므로 정확도 향상. 교대근무 시간 산정은 연장수당·최저임금 검증의 전제 |

---

## 1. Overview

### 1.1 Purpose

nodongok 19,655건 Q&A 분석에서 발견된 상위 미커버 유형 2개를 해결한다:
1. **연차발생일수** (15건) — "입사 2년차 연차 몇 개?", "무급휴직 기간 제외하면?"
2. **근로시간산정** (32건) — "2교대 월 근로시간은?", "3조2교대 연장/야간시간 산출"

### 1.2 Background

- **연차발생일수**: 현재 `annual_leave.py`가 `accrued_days`를 계산하지만, 이는 연차수당 계산의 부산물. 독립적으로 "입사일 기준 연차 발생일수"만 묻는 질문(15건)에 대응 불가. 특히 회계연도 전환, 무급휴직 기간 제외 등 복잡한 케이스 미지원.
- **근로시간산정**: `WorkSchedule` 모델에 `shift_monthly_hours` 필드가 있으나 실제 교대근무 패턴별 자동 계산 로직 없음. 사용자가 직접 시간을 입력해야 하며, "2교대면 월 몇 시간이냐" 질문에 답할 수 없음.

### 1.3 Related Documents

- 기존 연차수당 계산기: `wage_calculator/calculators/annual_leave.py`
- 기존 탄력근무 계산기: `wage_calculator/calculators/flexible_work.py`
- 입력 모델: `wage_calculator/models.py` (WorkSchedule, WorkType)
- 계산기 레지스트리: `wage_calculator/facade/registry.py`
- Q&A 분석 데이터: `analysis_qna_all.jsonl` (19,655건)

---

## 2. Scope

### 2.1 In Scope

**계산기 A: 연차발생일수 (`annual_leave_accrual`)**
- [ ] FR-A1: 입사일 기준 연차 발생일수 계산 (근로기준법 제60조)
- [ ] FR-A2: 1년 미만 근로자 — 월 개근 시 1일 (최대 11일)
- [ ] FR-A3: 1년 이상 근로자 — 15일 + 매 2년마다 1일 추가 (최대 25일)
- [ ] FR-A4: 2년차 차감 — 1년 미만 사용분 15일에서 공제 (제60조③)
- [ ] FR-A5: 회계연도(1.1) 기준 비례 계산 지원
- [ ] FR-A6: 무급휴직/휴업 기간 출근율 반영 (80% 미만 시 미발생)
- [ ] FR-A7: 단시간근로자 비례 연차 (소정근로시간 비례)
- [ ] FR-A8: 연도별 누적 발생/사용 테이블 출력

**계산기 B: 근로시간산정기 (`work_hours_calc`)**
- [ ] FR-B1: 교대근무 패턴 입력 (2교대, 3교대, 3조2교대, 4조2교대, 격일근무)
- [ ] FR-B2: 패턴별 월 소정근로시간 자동 계산
- [ ] FR-B3: 월 연장근로시간 산출 (법정 40h 초과분)
- [ ] FR-B4: 월 야간근로시간 산출 (22:00~06:00)
- [ ] FR-B5: 월 휴일근로시간 산출
- [ ] FR-B6: 주 52시간 준수 여부 판단
- [ ] FR-B7: 감시적/단속적 근로자(승인근로) 시간 산정 특례
- [ ] FR-B8: 결과를 기존 연장수당·최저임금 계산기 입력으로 연계

**공통**
- [ ] FR-C1: `CALC_TYPE_MAP`에 신규 매핑 추가 ("연차발생", "근로시간" 등)
- [ ] FR-C2: `_STANDARD_CALCS` 디스패처에 신규 계산기 등록
- [ ] FR-C3: `facade/conversion.py`에 한국어 → WageInput 변환 추가
- [ ] FR-C4: 흐름도 HTML 2개 신규 생성

### 2.2 Out of Scope

- 기존 `annual_leave.py`(연차수당) 수정 — 발생일수 계산기는 독립 모듈
- 선택적 근로시간제 (별도 feature)
- 간주근로시간제 (별도 feature)
- 휴게시간 자동 판단 (사용자 입력)

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-A1 | **연차발생: 입사일 기준** — `start_date` + `end_date`(또는 오늘) → 근속연수별 발생 연차일수 산출 | High | Pending |
| FR-A2 | **1년 미만** — 입사 후 1개월 개근 시 1일 발생. 출근율 반영. 최대 11일 | High | Pending |
| FR-A3 | **1년 이상** — 15일 기본 + 매 2년 근속마다 1일 가산 (25일 상한) | High | Pending |
| FR-A4 | **2년차 차감** — 1년 미만 사용분을 2년차 15일에서 차감 (제60조③) | High | Pending |
| FR-A5 | **회계연도 기준** — `use_fiscal_year=True` 시 1/1 기준 비례 발생일수 계산 | Medium | Pending |
| FR-A6 | **무급휴직 반영** — 휴직기간을 제외한 출근율 계산. 80% 미만 시 연차 미발생 | Medium | Pending |
| FR-A7 | **단시간근로자** — 소정근로시간 비례 연차 (`주 소정시간 / 40 × 8 × 발생일수`) | Medium | Pending |
| FR-A8 | **누적 테이블** — 연도별 발생/사용/잔여 일수 표 출력 | Low | Pending |
| FR-B1 | **교대패턴 입력** — `shift_pattern` 필드: "2교대", "3교대", "3조2교대", "4조2교대", "격일" | High | Pending |
| FR-B2 | **월 소정근로시간** — 패턴별 기본 계산식 (예: 4조2교대 = 주 평균 42h × 4.345) | High | Pending |
| FR-B3 | **월 연장근로** — 총 실근로 - 법정기준(주 40h × 4.345) = 연장 | High | Pending |
| FR-B4 | **월 야간근로** — 22~06시 해당 시간대 자동 추출 | High | Pending |
| FR-B5 | **월 휴일근로** — 주 소정근로일 외 근무일의 근로시간 | Medium | Pending |
| FR-B6 | **주 52시간 판단** — 소정 40h + 연장 12h 상한 체크 | Medium | Pending |
| FR-B7 | **감시적 근로자** — 고용노동부 승인 시 근로시간/휴게 특례 적용 | Low | Pending |
| FR-B8 | **계산기 연계** — 산출 시간을 `WorkSchedule`에 자동 세팅 → 연장수당 계산 연계 | High | Pending |
| FR-C1 | **CALC_TYPE_MAP 매핑** — "연차발생", "연차몇개", "근로시간", "교대근무시간" 등 추가 | High | Pending |
| FR-C2 | **디스패처 등록** — `_STANDARD_CALCS`에 2개 계산기 추가 | High | Pending |
| FR-C3 | **한국어 변환** — `_provided_info_to_input()`에 교대패턴·무급휴직 필드 매핑 | High | Pending |
| FR-C4 | **흐름도 HTML** — `annual_leave_accrual_flow.html`, `work_hours_calc_flow.html` 신규 | Low | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| Accuracy | 연차발생: 대법원 판례 기준 정확도 100% (제60조 각 항) | 테스트 케이스 10건+ |
| Accuracy | 근로시간: 고용노동부 교대근무 가이드라인 기준 오차 ±0.5h 이내 | 테스트 케이스 8건+ |
| Compatibility | 기존 25개 계산기에 영향 없음 | 기존 102개 배치 테스트 통과 |
| Performance | 계산 응답 < 50ms | 프로파일링 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] 연차발생일수 계산기 — 입사일 입력 시 연도별 발생일수 표 반환
- [ ] 근로시간산정기 — 교대패턴 입력 시 월 소정/연장/야간/휴일 시간 반환
- [ ] 기존 102개 배치 테스트 전량 통과 (회귀 없음)
- [ ] 신규 테스트 케이스 18건+ 통과
- [ ] `CALC_TYPE_MAP` 매핑 완료 → 챗봇에서 자동 인식
- [ ] 흐름도 HTML 2개 + `calculators.html` 메뉴 추가

### 4.2 Quality Criteria

- [ ] 연차 발생일수가 기존 `annual_leave.py`의 `accrued_days`와 동일 결과
- [ ] 교대근무 시간 결과를 연장수당 계산기에 넘겼을 때 정확한 수당 산출

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| 기존 annual_leave.py와 로직 중복 | Low | High | 공통 함수를 `shared.py`로 추출. 발생일수 계산기는 수당 계산 없이 일수만 반환 |
| 교대근무 패턴 무한 변형 | Medium | Medium | 5가지 표준 패턴만 지원. 커스텀은 직접 시간 입력으로 fallback |
| 감시적 근로자 특례 복잡성 | Low | Low | v1에서는 감시적/단속적 근로 플래그만 지원. 상세 규칙은 향후 확장 |

---

## 6. Architecture Considerations

### 6.1 파일 구조

```
wage_calculator/
├── calculators/
│   ├── annual_leave_accrual.py   ← 신규 (#26)
│   └── work_hours_calc.py        ← 신규 (#27)
├── facade/
│   ├── registry.py               ← CALC_TYPES, CALC_TYPE_MAP, _STANDARD_CALCS 추가
│   ├── helpers.py                ← _pop_annual_leave_accrual, _pop_work_hours 추가
│   └── conversion.py             ← 한국어 매핑 추가
├── models.py                     ← ShiftPattern enum, 무급휴직 필드 추가
public/
├── calculator_flow/
│   ├── annual_leave_accrual_flow.html  ← 신규 흐름도
│   └── work_hours_calc_flow.html       ← 신규 흐름도
├── calculators.html               ← 사이드바 메뉴 2건 추가
```

### 6.2 교대근무 패턴 정의

```python
class ShiftPattern(Enum):
    SHIFT_2     = "2교대"      # 주간/야간 교대, 주 평균 ~56h
    SHIFT_3     = "3교대"      # 3조 8시간, 주 평균 ~56h
    SHIFT_3_2   = "3조2교대"   # 12시간 교대, 주 평균 ~42h
    SHIFT_4_2   = "4조2교대"   # 12시간 교대 4조, 주 평균 ~42h
    ALTERNATE   = "격일근무"    # 24시간 격일 (경비 등), 주 평균 ~84h
    CUSTOM      = "직접입력"    # 사용자 지정
```

### 6.3 연차발생 계산 핵심 로직

```python
def calc_annual_leave_accrual(inp) -> AnnualLeaveAccrualResult:
    tenure = DateRange(inp.start_date, inp.end_date or today)
    years = tenure.years

    accrual_table = []
    for year in range(years + 1):
        if year == 0:
            days = min(11, months_with_attendance)  # 월 개근 시 1일
        else:
            base = 15 + max(0, (year - 1) // 2)
            days = min(25, base)
            if year == 1 and first_year_used > 0:
                days -= first_year_used  # 2년차 차감

        if is_part_time:
            days = days * weekly_hours / 40

        accrual_table.append({year, days, used, remaining})

    return AnnualLeaveAccrualResult(accrual_table=accrual_table, ...)
```

### 6.4 의존관계 맵 위치

```
[통상임금] ─────────────► [수당들]
    │
    ├──► [연차발생일수↗] ──► [연차수당]  (발생일수가 수당의 입력)
    │
    └──► [근로시간산정↗] ──► [연장수당]  (시간 산정이 수당의 입력)
                          └► [최저임금]
```

---

## 7. Implementation Order

| Phase | Task | 의존성 | 예상 변경량 |
|-------|------|--------|------------|
| 1 | `models.py` — `ShiftPattern` enum + 무급휴직 필드 추가 | 없음 | +20줄 |
| 2 | `annual_leave_accrual.py` — 연차발생일수 계산기 | Phase 1 | 신규 ~150줄 |
| 3 | `work_hours_calc.py` — 근로시간산정기 | Phase 1 | 신규 ~200줄 |
| 4 | `registry.py` + `helpers.py` + `conversion.py` — 통합 등록 | Phase 2,3 | +60줄 |
| 5 | 테스트 케이스 추가 (`wage_calculator_cli.py` 또는 배치 테스트) | Phase 4 | +100줄 |
| 6 | 흐름도 HTML 2개 + `calculators.html` 메뉴 추가 | Phase 4 | +500줄 |

---

## 8. Test Cases (Preview)

### 연차발생일수

| # | 시나리오 | 입력 | 기대 결과 |
|:-:|---------|------|----------|
| 1 | 1년 미만 (6개월 근무) | 입사 6개월 전 | 발생 6일 |
| 2 | 1년 근속 (개근) | 입사 1년 전 | 15일 |
| 3 | 3년 근속 | 입사 3년 전 | 16일 (15+1) |
| 4 | 21년 근속 (25일 상한) | 입사 21년 전 | 25일 |
| 5 | 2년차 차감 | 1년 미만 5일 사용 | 15-5=10일 |
| 6 | 회계연도 기준 중도입사 | 7/1 입사, 1/1 기준 | 비례 8일 |
| 7 | 단시간 (주 20시간) | part_time, 20h/주 | 15 × 20/40 = 7.5일 |
| 8 | 무급휴직 3개월 (출근율 75%) | 12개월 중 3개월 휴직 | 출근율 75% < 80% → 0일 |

### 근로시간산정

| # | 시나리오 | 입력 | 기대 결과 |
|:-:|---------|------|----------|
| 1 | 4조2교대 (12h 교대) | 4조2교대, 12h | 소정 ~182h, 연장 ~8.6h, 야간 ~91h |
| 2 | 3조2교대 (12h) | 3조2교대 | 소정 ~182h, 연장 ~8.6h |
| 3 | 2교대 (주야 12h) | 2교대 | 소정 ~209h, 연장 ~35h |
| 4 | 격일근무 (24h) | 격일, 24h | 소정 ~182h, 야간 ~91h |
| 5 | 3교대 (8h) | 3교대, 8h | 소정 ~209h, 야간 ~70h |
| 6 | 주 52시간 초과 | 2교대, 60h/주 | 52h 초과 경고 |

---

## 9. Next Steps

1. [ ] Design 문서 작성 (`annual-leave-accrual-work-hours.design.md`)
2. [ ] `models.py` 확장 (ShiftPattern)
3. [ ] 계산기 2개 구현
4. [ ] 레지스트리 통합 + 배치 테스트

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-20 | Initial draft — 20 FRs, nodongok Q&A 데이터 기반 | Claude |
