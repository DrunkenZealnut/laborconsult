# 상시근로자 수 감사 시트

## 1. 개요

| 항목 | 내용 |
|------|------|
| 계산기명 | 상시근로자 수 산정 계산기 |
| 코드 파일 | `wage_calculator/calculators/business_size.py` |
| 함수명 | `calc_business_size(bsi: BusinessSizeInput) -> BusinessSizeResult` |
| 적용 법조문 | 근로기준법 제11조(적용 범위), 시행령 제7조의2(상시 사용하는 근로자 수의 산정) |
| 5인 미만 적용 여부 | 해당 없음 (본 계산기가 사업장 규모를 판정하는 도구) |
| 특이사항 | `WageInput` 없이 `BusinessSizeInput`만으로 독립 동작하는 독립 함수 |

## 2. 입력 항목

| 필드명(한글) | 필드명(영문) | 타입 | 기본값 | 필수여부 |
|-------------|-------------|------|--------|---------|
| 법 적용 사유 발생일 | `bsi.event_date` | `str` | `""` | 선택 (미입력 시 오늘) |
| 근로자 목록 | `bsi.workers` | `list[WorkerEntry]` | `[]` | 필수 |
| 비가동일 목록 | `bsi.non_operating_days` | `list[str]` | `None` | 선택 (None이면 토·일 제외) |
| 동거친족만 사업장 | `bsi.is_family_only_business` | `bool` | `False` | 선택 |

**WorkerEntry 세부 필드:**

| 필드명(한글) | 필드명(영문) | 타입 | 기본값 | 필수여부 |
|-------------|-------------|------|--------|---------|
| 근로자 유형 | `worker_type` | `WorkerType` | `REGULAR` | 선택 |
| 근로계약 효력발생일 | `start_date` | `str` | `""` | 필수 |
| 퇴직일 | `end_date` | `str` | `None` | 선택 (None이면 재직중) |
| 휴직/결근 중 | `is_on_leave` | `bool` | `False` | 선택 |
| 휴직대체자 | `is_leave_replacement` | `bool` | `False` | 선택 |
| 특정 출근 요일 | `specific_work_days` | `list[int]` | `None` | 선택 (0=월~6=일) |
| 이름 | `name` | `str` | `""` | 선택 (식별용) |

## 3. 적용 상수

| 상수명 | 값 | 단위 | 법적 근거 | 코드 위치 |
|--------|-----|------|-----------|----------|
| `CALCULATION_PERIOD_MONTHS` | 1 | 개월 | 시행령 제7조의2 | `constants.py:229` |
| `DEFAULT_NON_OPERATING_WEEKDAYS` | [5, 6] (토, 일) | 요일 인덱스 | 실무 관행 | `constants.py:230` |
| 법 적용 기준 미달 판정 | 미달일수 < 가동일수/2 | 비율 | 시행령 제7조의2 제2항 제1호 | `business_size.py:372-377` |

## 4. 계산 과정 (핵심)

### Step 1: 산정기간 결정
- 공식: `산정기간종료 = 사유발생일 - 1일`
- 공식: `산정기간시작 = 사유발생일에서 역월상 1개월 전` (월말 보정 포함)
- 월말 보정: `calendar.monthrange` 사용 — 예: 3월 31일 사유 → 2월은 28/29일까지
- 코드: `business_size.py:188-209` (`_calc_period`)
- 법적 근거: 시행령 제7조의2 "법 적용 사유 발생일 전 1개월간"

### Step 2: 가동일수 집계
- 비가동일 명시 시: 해당 날짜 제외
- 비가동일 미입력 시: 토·일 제외 (기본값)
- 결과: 가동일 목록 + 가동일수
- 코드: `business_size.py:212-231` (`_calc_operating_days`)

### Step 3: 일별 근로자 수 집계
- 각 가동일마다 모든 근로자에 대해 포함/제외 판별 (`_should_include_worker`)
- **포함 기준**:

| 근로자 유형 | 판정 | 사유 | 코드 위치 |
|------------|------|------|----------|
| 통상/기간제/단시간/일용 | 포함 | 고용관계 유지 | `business_size.py:283` |
| 교대근무(SHIFT) | 포함 | 비번일 포함 (사회통념상 상시근무) | `business_size.py:276-277` |
| 외국인(FOREIGN) | 포함 | 국적 불문 | `business_size.py:278-279` |
| 휴직/휴가/결근/징계(`is_on_leave`) | 포함 | 고용관계 유지 | `business_size.py:274-275` |
| 가족(FAMILY) + 비가족 존재 | 포함 | 지휘감독 하 임금 근로 | `business_size.py:280-281` |

- **제외 기준**:

| 근로자 유형 | 판정 | 사유 | 코드 위치 |
|------------|------|------|----------|
| 휴직대체자(`is_leave_replacement`) | 제외 | 중복 산정 방지 | `business_size.py:257-258` |
| 해외현지법인(`OVERSEAS_LOCAL`) | 제외 | 별개 법인격 | `business_size.py:261-262` |
| 동거친족만 사업장 + 가족 + 비가족 없음 | 제외 | 근기법 미적용 | `business_size.py:265-266` |
| 특정요일 출근자 + 해당 요일 아님 | 제외 | `specific_work_days` 체크 | `business_size.py:269-271` |
| `start_date` 미입력 | 제외 | 효력발생일 불명 | `business_size.py:242-243` |
| 근로계약 기간 외 | 제외 | start_date 전 / end_date 후 | `business_size.py:248-253` |

- 코드: `business_size.py:234-283` (`_should_include_worker`), `business_size.py:286-351` (`_count_daily_workers`)

### Step 4: 상시근로자 수 산출
- 공식: `상시근로자수 = round(연인원합계 / 가동일수, 2)`
- 코드: `business_size.py:121`

### Step 5: BusinessSize 판정
- `< 5명` → `UNDER_5` (5인미만)
- `5명 이상 ~ 30명 미만` → `OVER_5` (5인이상)
- `30명 이상 ~ 300명 미만` → `OVER_30` (30인이상)
- `300명 이상` → `OVER_300` (300인이상)
- 코드: `business_size.py:354-362` (`_determine_size`)

### Step 6: 법 적용 기준 미달일수 1/2 판정
- 공식: `미달일수 = count(일별근로자수 < 5인 가동일)`
- 판정: `미달일수 < 가동일수 / 2` → 법 적용 사업장 (`True`)
- 코드: `business_size.py:365-378` (`_check_threshold`)
- 법적 근거: 시행령 제7조의2 제2항 제1호

## 5. 출력 항목

| 항목명 | 설명 | 단위 |
|--------|------|------|
| `regular_worker_count` | 상시근로자 수 | 명 (소수 2자리) |
| `business_size` | 사업장 규모 | `BusinessSize` enum |
| `calculation_period_start` | 산정기간 시작일 | ISO 날짜 |
| `calculation_period_end` | 산정기간 종료일 | ISO 날짜 |
| `operating_days` | 가동일수 | 일 |
| `total_headcount` | 연인원 합계 | 명 |
| `daily_counts` | 일별 근로자 수 | dict[날짜, 인원] |
| `included_workers` | 포함된 근로자 내역 | list[dict] |
| `excluded_workers` | 제외된 근로자 내역 | list[dict] |
| `below_threshold_days` | 5인 미만 일수 | 일 |
| `above_threshold_days` | 5인 이상 일수 | 일 |
| `is_law_applicable` | 법 적용 여부 | bool |

## 6. 예외 처리 / 엣지 케이스

| 조건 | 처리 | 법적 근거 |
|------|------|-----------|
| `event_date` 미입력 | `date.today()` 사용 + 경고 | `business_size.py:57-59` |
| `workers` 빈 리스트 | 0명 → UNDER_5 반환 + 경고 | `business_size.py:64-82` |
| 가동일수 0일 | 산정 불가 반환 + 경고 | `business_size.py:93-112` |
| `start_date` 미입력 근로자 | 제외 + 개별 경고 | `business_size.py:242-243,324-328` |
| 퇴직일 지난 근로자 | 해당 날짜 이후 제외 | `business_size.py:251-253` |
| 동거친족만 사업장 + 가족만 | 전원 제외 → 0명 | `business_size.py:265-266` |
| 동거친족 + 비가족 혼합 | 비가족 1명이라도 있으면 가족도 포함 | `business_size.py:294-298` (`has_non_family` 판별) |
| `specific_work_days` 설정 | 해당 요일에만 포함 | `business_size.py:269-271` |
| 월말 보정 (산정기간) | 2월 등 짧은 월은 `calendar.monthrange`로 자동 보정 | `business_size.py:203-207` |

## 7. 계산 예시

### 예시 1: 통상근로자 7명, 사유발생일 2025-03-15

**입력:** 통상근로자 7명 (전원 재직, 전일 근무), 비가동일 기본(토·일)

| 단계 | 계산 | 결과 |
|------|------|------|
| 산정기간 | 2025-02-15 ~ 2025-03-14 | 28일 |
| 가동일수 | 28일 - 토·일(8일) | 20일 |
| 일별 근로자 수 | 매일 7명 | 7명 × 20일 |
| 연인원 | 7 × 20 | 140명 |
| 상시근로자 수 | 140 / 20 | 7.00명 |
| 판정 | 7.00 ≥ 5 | OVER_5 (5인이상) |
| 미달일수 | 0일 < 10일(가동일 1/2) | 법 적용 |

### 예시 2: 혼합 유형 (통상 3명 + 파트타임 2명(월·수·금) + 휴직대체자 1명)

**입력:** 통상 3명(상시), 파트타임 2명(월·수·금만 출근), 휴직대체자 1명

| 단계 | 계산 | 결과 |
|------|------|------|
| 가동일수 | 20일 (평일) | |
| 월·수·금 일수 | 약 12일 | |
| 통상 연인원 | 3 × 20 | 60명 |
| 파트타임 연인원 | 2 × 12 | 24명 |
| 휴직대체자 | 제외 | 0명 |
| 총 연인원 | 60 + 24 | 84명 |
| 상시근로자 수 | 84 / 20 | 4.20명 |
| 판정 | 4.20 < 5 | UNDER_5 (5인미만) |

## 8. 관련 판례

| 판례번호 | 요지 | 코드 반영 위치 |
|----------|------|---------------|
| 대법원 2020다248475 | 상시근로자 수 산정 시 휴직·결근·징계자도 고용관계 유지 중이면 포함 | `_should_include_worker` 중 `is_on_leave` 처리 (`business_size.py:274-275`) |
| 대법원 2014두6992 | 교대근무자는 비번일에도 사회통념상 상시 근무로 보아 포함 | `WorkerType.SHIFT` 처리 (`business_size.py:276-277`) |
| 대법원 2006다9228 | 동거친족만 사용하는 사업장은 근기법 적용 제외, 단 비가족 근로자 1인이라도 있으면 전원 적용 | `is_family_only_business` + `has_non_family` 판별 (`business_size.py:265-266,294-298`) |
| 근로기준법 시행령 제7조의2 제2항 | 법 적용 기준에 미달하는 일수가 산정기간의 1/2 미만이면 법 적용 사업장으로 봄 | `_check_threshold` (`business_size.py:365-378`) |
