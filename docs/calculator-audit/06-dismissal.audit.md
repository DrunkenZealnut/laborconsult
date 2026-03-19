# 해고예고수당 계산기 감사 시트

## 1. 개요

| 항목 | 내용 |
|------|------|
| 계산기명 | 해고예고수당 계산기 |
| 코드 파일 | `wage_calculator/calculators/dismissal.py` |
| 함수명 | `calc_dismissal(inp, ow)` |
| 적용 법조문 | 근로기준법 제26조 (해고의 예고) |
| 5인 미만 적용 | 적용 (근기법 제26조는 5인 미만 사업장에도 적용) |

## 2. 입력 항목

| 필드명(한글) | 필드명(영문) | 타입 | 기본값 | 필수여부 |
|-------------|-------------|------|--------|---------|
| 임금입력 | `inp: WageInput` | WageInput | - | 필수 |
| 통상임금 결과 | `ow: OrdinaryWageResult` | OrdinaryWageResult | - | 필수 |
| 실제 예고일수 | `inp.notice_days_given` | int | 0 | 필수 |
| 1일 소정근로시간 | `inp.schedule.daily_work_hours` | float | 8.0 | 필수 |
| 계속근로기간 | `inp.tenure_months` | Optional[int] | None | 선택 |
| 계절적 사업 여부 | `inp.is_seasonal_worker` | bool | False | 선택 |
| 천재지변/귀책 여부 | `inp.is_force_majeure` | bool | False | 선택 |
| 근무형태 | `inp.work_type` | WorkType | REGULAR | 선택 |
| 수습기간 여부 | `inp.is_probation` | bool | False | 선택 |
| 수습기간(개월) | `inp.probation_months` | int | 3 | 선택 |

## 3. 적용 상수

| 상수명 | 값 | 단위 | 법적 근거 | 코드 위치 |
|--------|-----|------|-----------|-----------|
| `DISMISSAL_NOTICE_DAYS` | 30 | 일 | 근기법 제26조 (30일 전 예고) | constants.py:58 |

## 4. 계산 과정 (핵심)

### Step 1: 1일 통상임금 산출

**공식** (`dismissal.py:31-33`):

```
1일_통상임금 = 통상시급 × 1일_소정근로시간
```

- 코드: `daily_pay = hourly * daily_hours`
- 통상시급은 `OrdinaryWageResult.hourly_ordinary_wage`에서 제공

### Step 2: 면제 사유 확인

5가지 면제 사유를 순차적으로 확인 (`dismissal.py:41-75`):

| 순서 | 면제 사유 | 조건 | 법적 근거 | 코드 위치 |
|------|----------|------|-----------|-----------|
| 1 | 계속근로기간 3개월 미만 | `tenure_months < 3` | 근기법 제26조 단서 2호 | `dismissal.py:45-49` |
| 2 | 계절적 사업 4개월 이내 | `is_seasonal_worker == True` | 근기법 제26조 단서 3호 | `dismissal.py:52-56` |
| 3 | 천재지변/근로자 귀책 | `is_force_majeure == True` | 근기법 제26조 단서 4호 | `dismissal.py:58-63` |
| 4 | 일용직 1개월 미만 | `work_type == DAILY_WORKER` | 근기법 제26조 단서 | `dismissal.py:65-69` |
| 5 | 수습기간 3개월 이내 | `is_probation and probation_months <= 3` | 근기법 제26조 단서 | `dismissal.py:71-75` |

면제 사유에 해당하면 수당 0원으로 즉시 반환 (`dismissal.py:77-93`).

### Step 3: 수당 지급 일수 계산

**공식** (`dismissal.py:96`):

```
수당_지급일수 = max(0, 30 - 실제_예고일수)
```

- 코드: `payable_days = max(0, DISMISSAL_NOTICE_DAYS - notice_given)`

### Step 4: 해고예고수당 산출

**공식** (`dismissal.py:97`):

```
해고예고수당 = 1일_통상임금 × 수당_지급일수
```

- 코드: `dismissal_pay = daily_pay * payable_days`
- 예고일수가 30일 이상이면 수당 0원

## 5. 출력 항목

| 항목명 | 설명 | 단위 |
|--------|------|------|
| `dismissal_pay` | 해고예고수당 | 원 |
| `notice_days_required` | 필요 예고일수 (30일) | 일 |
| `notice_days_given` | 실제 예고일수 | 일 |
| `payable_days` | 수당 지급 일수 | 일 |
| `is_exempt` | 면제 여부 | bool |
| `breakdown` | 계산 내역 상세 | dict |
| `formulas` | 적용 공식 목록 | list |
| `warnings` | 주의사항 목록 | list |
| `legal_basis` | 법적 근거 목록 | list |

## 6. 예외 처리 / 엣지 케이스

| 조건 | 처리 | 법적 근거 |
|------|------|-----------|
| 계속근로기간 3개월 미만 | 면제, 수당 0원 반환 (`dismissal.py:45-49`) | 근기법 제26조 단서 2호 |
| 계절적 사업 4개월 이내 | 면제, 수당 0원 반환 (`dismissal.py:52-56`) | 근기법 제26조 단서 3호 |
| 천재지변/근로자 귀책사유 | 면제, 수당 0원 반환 (`dismissal.py:58-63`) | 근기법 제26조 단서 4호 |
| 일용직 근로자 | 면제 처리 (계속근로 1개월 미만 시) (`dismissal.py:65-69`) | 근기법 제26조 단서 |
| 수습기간 3개월 이내 | 면제, 수당 0원 반환 (`dismissal.py:71-75`) | 근기법 제26조 단서 |
| 예고일수 30일 이상 | 수당 0원 (정상 예고) (`dismissal.py:107`) | 근기법 제26조 |
| 예고일수 음수 입력 | `max(0, notice_days_given)`으로 0 처리 (`dismissal.py:38`) | 방어 코드 |

## 7. 계산 예시

### 예시 1: 예고 없는 즉시 해고 (월급 300만원, 1일 8시간)

**Step 1**: 1일 통상임금
- 통상시급 = 3,000,000 ÷ 209 = 14,354원
- 1일 통상임금 = 14,354원 × 8시간 = 114,833원

**Step 2**: 면제 사유 없음

**Step 3**: 수당 지급일수 = max(0, 30 - 0) = 30일

**Step 4**: 해고예고수당 = 114,833원 × 30일 = 3,444,990원

### 예시 2: 10일 전 예고 후 해고 (월급 250만원, 1일 8시간)

**Step 1**: 1일 통상임금
- 통상시급 = 2,500,000 ÷ 209 = 11,962원
- 1일 통상임금 = 11,962원 × 8시간 = 95,694원

**Step 2**: 면제 사유 없음

**Step 3**: 수당 지급일수 = max(0, 30 - 10) = 20일

**Step 4**: 해고예고수당 = 95,694원 × 20일 = 1,913,880원

### 예시 3: 수습 2개월 차 해고 (면제 사례)

**Step 2**: `is_probation=True`, `probation_months=2` (3개월 이내)
- 면제 사유 해당
- 해고예고수당 = 0원

## 8. 관련 판례

| 판례번호 | 요지 | 코드 반영 위치 |
|---------|------|--------------|
| (법조문 기반) | 근기법 제26조 단서 각 호에 따른 면제 사유를 순차적으로 확인 | `dismissal.py:41-75` |

> 참고: 해고예고수당 계산기는 판례보다 근로기준법 제26조의 법조문 자체에 충실하게 구현되어 있으며, 면제 사유 5가지를 조문 단서 각 호에 따라 확인합니다.
