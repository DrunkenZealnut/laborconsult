# 유급공휴일 감사 시트

## 1. 개요

| 항목 | 내용 |
|------|------|
| 계산기명 | 유급공휴일 수당 |
| 코드 파일 | `wage_calculator/calculators/public_holiday.py` |
| 함수명 | `calc_public_holiday(inp, ow, holiday_days)` |
| 적용 법조문 | 근로기준법 제55조 제2항 (관공서 공휴일의 유급휴일 보장) |
| 5인 미만 적용 여부 | 미적용 (5인 미만 사업장 제외) |

## 2. 입력 항목

| 필드명(한글) | 필드명(영문) | 타입 | 기본값 | 필수여부 |
|-------------|-------------|------|--------|---------|
| 비근무 유급공휴일 일수 | `inp.public_holiday_days` | `int` | `0` | 선택 (0이면 기본 1일) |
| 사업장 규모 | `inp.business_size` | `BusinessSize` | `OVER_5` | 필수 |
| 기준 연도 | `inp.reference_year` | `int` | 현재 연도 | 필수 |
| 1일 소정근로시간 | `inp.schedule.daily_work_hours` | `float` | `8.0` | 선택 |
| 통상시급 | `ow.hourly_ordinary_wage` | `float` | - | `calc_ordinary_wage()` 결과 |
| (함수 인자) 공휴일 일수 | `holiday_days` | `int \| None` | `None` | 선택 (제공 시 `inp.public_holiday_days` 무시) |

## 3. 적용 상수

| 상수명 | 값 | 단위 | 법적 근거 | 코드 위치 |
|--------|---|------|-----------|----------|
| `PUBLIC_HOLIDAY_APPLY_DATE["300인이상"]` | `2020-01-01` | 날짜 | 근로기준법 부칙 (2018.3.20 개정) | `public_holiday.py:23` |
| `PUBLIC_HOLIDAY_APPLY_DATE["30인이상"]` | `2021-01-01` | 날짜 | 근로기준법 부칙 (2018.3.20 개정) | `public_holiday.py:24` |
| `PUBLIC_HOLIDAY_APPLY_DATE["5인이상"]` | `2022-01-01` | 날짜 | 근로기준법 부칙 (2018.3.20 개정) | `public_holiday.py:25` |

## 4. 계산 과정 (핵심)

### Step 1: 공휴일 일수 결정
```
비근무공휴일일수 = holiday_days (함수 인자) 또는 inp.public_holiday_days
if 비근무공휴일일수 <= 0:
    비근무공휴일일수 = 1  (기본 1일)
```
- 함수 인자 `holiday_days`가 우선 적용
- 코드 참조: `public_holiday.py:52-54`

### Step 2: 적용 대상 여부 판단
```
기준일 = date(inp.reference_year, 1, 1)
적용여부 = _check_eligibility(inp.business_size, 기준일)
```
- `_check_eligibility()` 내부 로직 (코드 참조: `public_holiday.py:108-117`):
  - `UNDER_5` (5인 미만): 항상 `False` (미적용)
  - `OVER_300` (300인 이상): 기준일 >= 2020-01-01이면 적용
  - `OVER_30` (30인 이상): 기준일 >= 2021-01-01이면 적용
  - `OVER_5` (5인 이상): 기준일 >= 2022-01-01이면 적용
- 법적 근거: 근로기준법 제55조 제2항, 부칙 (단계별 시행)

### Step 3: 미적용 시 조기 반환
```
if not 적용여부:
    -> total_holiday_pay=0, eligible=False 반환
```
- 사유: "5인 미만 사업장" 또는 "해당 규모 적용 시작일 이전"
- 코드 참조: `public_holiday.py:63-79`

### Step 4: 공휴일 1일 수당 산출
```
공휴일1일수당 = 통상시급 x 1일소정근로시간
```
- 코드 참조: `public_holiday.py:81`
- 법적 근거: 근로기준법 제55조 제2항 (유급으로 보장 = 통상시급 x 소정근로시간)

### Step 5: 총 공휴일 수당 산출
```
총공휴일수당 = 공휴일1일수당 x 비근무공휴일일수
```
- 코드 참조: `public_holiday.py:82`

### Step 6: 결과 반올림
```
공휴일1일수당 = round(공휴일1일수당, 0)
총공휴일수당 = round(총공휴일수당, 0)
```
- 코드 참조: `public_holiday.py:97-98`

## 5. 출력 항목

| 항목명 | 설명 | 단위 |
|--------|------|------|
| `holiday_pay_per_day` | 공휴일 1일 수당 | 원 |
| `holiday_days` | 비근무 공휴일 일수 | 일 |
| `total_holiday_pay` | 총 공휴일 수당 | 원 |
| `eligible` | 유급공휴일 적용 대상 여부 | bool |
| `breakdown` | 상세 내역 (통상시급, 1일 소정근로시간, 1일 수당, 일수, 총 수당) | dict |
| `formulas` | 계산식 문자열 목록 | list |
| `warnings` | 경고 메시지 목록 | list |
| `legal_basis` | 법적 근거 목록 | list |

## 6. 예외 처리 / 엣지 케이스

| 조건 | 처리 | 법적 근거 |
|------|------|-----------|
| 5인 미만 사업장 | `eligible=False`, 수당 0원 반환. "유급공휴일 미적용" 경고 | 근기법 제55조 제2항 적용 제외 |
| 기준연도가 규모별 시행일 이전 | `eligible=False`, 수당 0원 반환. "적용 시작일 이전" 경고 | 근기법 부칙 |
| `public_holiday_days` = 0 | 기본 1일로 처리 | - |
| `daily_work_hours` 미지정 | 기본 8.0시간 적용 (`WorkSchedule` 기본값) | - |
| 함수 인자 `holiday_days` 제공 | `inp.public_holiday_days` 무시, 인자값 사용 | - |

## 7. 계산 예시

### 예시 1: 5인 이상 사업장, 공휴일 3일, 시급 15,000원

**입력:**
- 사업장 규모: `OVER_5`
- 기준 연도: 2025
- 통상시급: 15,000원
- 1일 소정근로시간: 8시간
- 비근무 공휴일 일수: 3일

**계산:**
1. 적용 대상 판단: OVER_5, 2025-01-01 >= 2022-01-01 -> 적용
2. 공휴일 1일 수당: 15,000 x 8 = 120,000원
3. 총 공휴일 수당: 120,000 x 3 = 360,000원

**결과:**
- `holiday_pay_per_day` = 120,000원
- `total_holiday_pay` = 360,000원
- `eligible` = True

### 예시 2: 5인 미만 사업장

**입력:**
- 사업장 규모: `UNDER_5`
- 기준 연도: 2025
- 비근무 공휴일 일수: 2일

**계산:**
1. 적용 대상 판단: UNDER_5 -> 미적용

**결과:**
- `holiday_pay_per_day` = 0원
- `total_holiday_pay` = 0원
- `eligible` = False
- 경고: "유급공휴일 미적용: 5인 미만 사업장"

## 8. 관련 판례

| 판례번호 | 요지 | 코드반영위치 |
|----------|------|-------------|
| 대법원 2021다303586 | 관공서 공휴일에 관한 규정에 따른 공휴일이 유급휴일로 보장되며, 대체공휴일도 포함 | `public_holiday.py:50` (법적 근거 기재) |
| 행정해석 근로기준정책과-3666 | 5인 이상 사업장은 관공서 공휴일(대체공휴일 포함)에 근무하지 않아도 유급으로 처리해야 함. 근무 시 휴일근로 가산수당 지급 | `public_holiday.py:81` (통상시급 x 소정근로시간 기준) |
| 행정해석 근로기준정책과-1472 | 단계적 시행: 300인 이상(2020), 30인 이상(2021), 5인 이상(2022) | `public_holiday.py:22-26` (`PUBLIC_HOLIDAY_APPLY_DATE` 딕셔너리) |
