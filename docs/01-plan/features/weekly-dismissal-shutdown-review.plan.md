# weekly-dismissal-shutdown-review Plan

> **Feature**: 주휴수당 / 해고예고수당 기존 리뷰 + 휴업수당 신규 구현
> **Author**: Product Manager
> **Created**: 2026-03-08
> **Level**: Dynamic
> **Reference**: https://www.nodong.kr/WeeklyHolidayPay

---

## Executive Summary

| Perspective | Description |
|-------------|-------------|
| **Problem** | 주휴수당·해고예고수당에 일부 엣지케이스 미구현, 휴업수당(근기법 제46조) 계산기 아예 부재 |
| **Solution** | 기존 2개 계산기 보완 + 휴업수당 신규 계산기 추가 (총 3개 대상) |
| **Function UX Effect** | 노동상담 챗봇에서 주휴·해고·휴업 관련 질의 시 정확한 계산 결과 제공 |
| **Core Value** | 근기법 제26조·제46조·제55조 3대 근로자 보호 수당을 하나의 리뷰에서 완성 |

---

## 1. Background & Problem Analysis

### 1.1 현행 구현 상태

| Calculator | File | Lines | Status |
|-----------|------|:-----:|--------|
| 주휴수당 | `weekly_holiday.py` | 159 | 구현됨 (보완 필요) |
| 해고예고수당 | `dismissal.py` | 106 | 구현됨 (보완 필요) |
| 휴업수당 | - | 0 | **미구현** |

### 1.2 주휴수당 (weekly_holiday.py) Gap 분석

**현재 구현 완료 항목**:
- 주 15h 미만 미발생 처리
- 개근 여부 확인 (`weekly_attendance_days`)
- 대법원 2022다291153 판결 반영 (주 5일 기준 분기)
- 퇴직 마지막 주 주휴수당 (2021.8.4. 행정해석)
- 월 환산 (× WEEKS_PER_MONTH)

**nodong.kr 대비 Gap**:
1. **일급제 근로자 역산 없음**: 일급 입력 시 `hourly = daily_wage / daily_work_hours`로 시급 환산 후 주휴 계산하는 흐름은 `ordinary_wage.py`에서 처리하므로 **자체 gap 없음** (확인 완료)
2. **시간급 근로자 월급 포함 여부 안내 부재**: 시급제 근로자의 경우 "주휴수당이 포함된 시급인지" 구분 안내 warning 추가 필요
3. **월급제 주휴 포함 여부 안내**: 월급에 이미 주휴수당이 포함되어 있음을 breakdown에 명시하지 않음

**보완 사항 (P2)**:
- 시급제: "제시된 시급에 주휴수당이 포함되어 있을 수 있습니다" warning
- 월급제: breakdown에 "월급에 주휴수당 포함 여부" 안내 추가
- breakdown에 `주 소정근로일` 표시 추가

### 1.3 해고예고수당 (dismissal.py) Gap 분석

**현재 구현 완료 항목**:
- 30일 예고 부족분 계산
- 수습 3개월 이내 면제
- 일용직 면제

**미구현 사항 (P1)**:
1. **1일 통상임금 계산 오류**: `daily_pay = hourly * 8` 고정 → `hourly * inp.schedule.daily_work_hours` 로 수정 필요. 1일 소정근로시간이 6h인 파트타임은 6h분만 지급해야 함
2. **계속근로기간 3개월 미만 면제 미구현**: 근기법 제26조 단서 2호 "계속 근로한 기간이 3개월 미만인 근로자" 해고예고 의무 면제
3. **계절적 사업 4개월 이내 면제 미구현**: 근기법 제26조 단서 3호
4. **천재지변·귀책사유 면제 미구현**: 근기법 제26조 단서 4호 — boolean 필드 추가하여 처리
5. **해고예고수당 미지급 시 구제절차 안내 부재**: 법적 힌트로 부당해고 구제 신청 안내

### 1.4 휴업수당 (신규) 요구사항

**법적 근거**: 근로기준법 제46조 (휴업수당)

**핵심 규칙**:
- 사용자(사업주)의 귀책사유로 인한 휴업: **평균임금의 70% 이상** 지급
- 평균임금의 70%가 통상임금을 초과하면 → **통상임금 지급**
- 부분 휴업: 근로 제공 시간에 대해서는 정상 임금, 미근로 시간에 대해서는 휴업수당 비례 지급
- 불가항력(천재지변 등) → 휴업수당 미발생
- 5인 미만 사업장에도 적용

**필요 입력 필드** (WageInput 확장):
- `shutdown_days: int` — 총 휴업일수
- `shutdown_hours_per_day: Optional[float]` — 부분 휴업 시 1일 미근로 시간 (None이면 전일 휴업)
- `is_employer_fault: bool` — 사용자 귀책사유 여부 (기본 True)
- `shutdown_start_date: Optional[str]` — 휴업 시작일 (평균임금 산정 기준)

**Result 필드**:
- `shutdown_allowance: float` — 휴업수당 총액
- `daily_shutdown_allowance: float` — 1일 휴업수당
- `avg_wage_70_pct: float` — 평균임금의 70%
- `is_ordinary_wage_applied: bool` — 통상임금 적용 여부 (70%>통상 시)
- `is_partial_shutdown: bool` — 부분 휴업 여부

---

## 2. Requirements

### 2.1 Functional Requirements

| ID | Priority | Requirement | Target |
|----|:--------:|-------------|--------|
| FR-01 | P0 | 휴업수당 계산기 신규 구현 (근기법 제46조) | `shutdown_allowance.py` |
| FR-02 | P1 | 해고예고수당 1일 통상임금 = 시급 × 소정근로시간 (8h 고정 제거) | `dismissal.py` |
| FR-03 | P1 | 해고예고수당 면제사유 3개 추가 (3개월 미만, 계절사업, 천재지변) | `dismissal.py` |
| FR-04 | P2 | 주휴수당 시급제/월급제 안내 warning·breakdown 보강 | `weekly_holiday.py` |
| FR-05 | P1 | WageInput에 휴업 관련 필드 4개 추가 | `models.py` |
| FR-06 | P1 | facade.py에 shutdown_allowance 디스패처 연결 | `facade.py` |
| FR-07 | P2 | CALC_TYPE_MAP에 "휴업수당" 매핑 추가 | `facade.py` |
| FR-08 | P2 | 테스트 케이스 추가 (주휴 2건, 해고 2건, 휴업 3건) | `wage_calculator_cli.py` |

### 2.2 Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| NFR-01 | 기존 85개 테스트 케이스 전수 통과 유지 |
| NFR-02 | constants.py에 SHUTDOWN_RATE = 0.7 상수 추가 |
| NFR-03 | 평균임금 계산은 기존 `calc_average_wage()` 호출로 재사용 |

---

## 3. Implementation Priority

### Phase 1: 휴업수당 신규 구현 (P0)
1. `constants.py`에 `SHUTDOWN_RATE = 0.7` 추가
2. `models.py`에 휴업 관련 필드 4개 추가
3. `wage_calculator/calculators/shutdown_allowance.py` 신규 생성
4. `facade.py`에 `_pop_shutdown_allowance()` + `_STANDARD_CALCS` 등록
5. `CALC_TYPE_MAP`에 "휴업수당" 매핑 추가
6. 테스트 3건 추가

### Phase 2: 해고예고수당 보완 (P1)
1. `daily_pay = hourly * 8` → `hourly * inp.schedule.daily_work_hours` 수정
2. `models.py`에 `tenure_months`, `is_seasonal_worker`, `is_force_majeure` 필드 추가
3. 면제사유 3개 추가 구현
4. 테스트 2건 추가

### Phase 3: 주휴수당 안내 보강 (P2)
1. 시급제 warning: "제시된 시급에 주휴수당 포함 여부 확인 필요"
2. 월급제 breakdown: "월급에 주휴수당 포함 (별도 지급 불필요)"
3. breakdown에 `주 소정근로일` 명시
4. 테스트 2건 추가

---

## 4. Affected Files

| File | Change Type | Description |
|------|:-----------:|-------------|
| `wage_calculator/constants.py` | Modify | `SHUTDOWN_RATE` 상수 추가 |
| `wage_calculator/models.py` | Modify | 휴업·해고 관련 필드 추가 |
| `wage_calculator/calculators/shutdown_allowance.py` | **Create** | 휴업수당 계산기 |
| `wage_calculator/calculators/dismissal.py` | Modify | 1일 통상임금 수정, 면제사유 추가 |
| `wage_calculator/calculators/weekly_holiday.py` | Modify | warning·breakdown 보강 |
| `wage_calculator/facade.py` | Modify | 디스패처 + CALC_TYPE_MAP 등록 |
| `wage_calculator_cli.py` | Modify | 테스트 케이스 7건 추가 |

---

## 5. Risk Assessment

| Risk | Impact | Mitigation |
|------|:------:|------------|
| dismissal.py `daily_pay` 수정이 기존 test #6 결과에 영향 | Medium | test #6은 8h 근무자 → 결과 불변 확인 |
| 휴업수당에 평균임금 필요 → `calc_average_wage()` 의존성 | Low | 기존 average_wage 인프라 재사용 |
| WageInput 필드 추가가 기존 코드에 영향 | Low | 모든 새 필드에 기본값 설정 |

---

## 6. Success Criteria

- [ ] 기존 85개 테스트 전수 통과
- [ ] 휴업수당 테스트 3건 통과 (전일/부분/통상임금 적용)
- [ ] 해고예고수당 테스트 2건 추가 통과 (파트타임/3개월 미만)
- [ ] 주휴수당 테스트 2건 추가 통과 (시급제 안내/월급제 안내)
- [ ] `python3 -c "from wage_calculator import WageCalculator"` 정상
- [ ] PDCA Gap Analysis Match Rate >= 90%

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-08 | Initial plan | product-manager |
