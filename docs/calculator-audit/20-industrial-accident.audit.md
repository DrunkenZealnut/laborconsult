# 산재보상금 감사 시트

## 1. 개요

| 항목 | 내용 |
|------|------|
| 계산기명 | 산재보상금 계산기 |
| 코드 파일 | `wage_calculator/calculators/industrial_accident.py` |
| 함수명 | `calc_industrial_accident(inp: WageInput, ow: OrdinaryWageResult) -> IndustrialAccidentResult` |
| 적용 법조문 | 산업재해보상보험법 제36조(종류), 제52조(휴업급여), 제54조(최저보상), 제57조(장해급여), 제62조(유족급여), 제66조(상병보상연금), 제71조(장례비) |
| 5인 미만 적용 여부 | 적용 (산재보험 당연적용 사업장, 규모 무관) |

## 2. 입력 항목

| 필드명(한글) | 필드명(영문) | 타입 | 기본값 | 필수여부 |
|-------------|-------------|------|--------|---------|
| 월급여 | `monthly_wage` | `float` | `None` | 선택 (평균임금 추정용) |
| 요양(휴업) 일수 | `sick_leave_days` | `int` | `0` | 휴업급여 계산 시 필수 |
| 중증요양상태 등급 | `severe_illness_grade` | `int` | `0` | 상병보상연금 시 필수 (1~3) |
| 장해등급 | `disability_grade` | `int` | `0` | 장해급여 시 필수 (1~14) |
| 장해급여 연금 선택 | `disability_pension` | `bool` | `True` | 선택 |
| 유족 수 | `num_survivors` | `int` | `0` | 유족급여 시 필수 |
| 유족급여 연금 선택 | `survivor_pension` | `bool` | `True` | 선택 |
| 사망 여부 | `is_deceased` | `bool` | `False` | 유족/장례비 시 필수 |
| 기준 연도 | `reference_year` | `int` | 현재 연도 | 선택 |
| 통상임금 환산일급 | `ow.daily_ordinary_wage` | `float` | - | 필수 (OrdinaryWageResult에서 수령) |

## 3. 적용 상수

| 상수명 | 값 | 단위 | 법적 근거 | 코드 위치 |
|--------|-----|------|-----------|----------|
| `SICK_LEAVE_RATE` | 0.70 (70%) | 비율 | 산재보험법 제52조 | `constants.py:316` |
| `SICK_LEAVE_LOW_RATE` | 0.90 (90%) | 비율 | 산재보험법 제54조 | `constants.py:317` |
| `MIN_COMP_THRESHOLD` | 0.80 (80%) | 비율 | 산재보험법 제54조 | `constants.py:318` |
| `MIN_COMPENSATION_DAILY[2025]` | 80,240 | 원/일 | 고용노동부 고시 | `constants.py:323` |
| `MIN_COMPENSATION_DAILY[2026]` | 82,560 | 원/일 | 고용노동부 고시 | `constants.py:324` |
| `DISABILITY_GRADE_TABLE` | 1~14급별 (연금일수, 일시금일수, 지급형태) | 일 | 산재보험법 제57조 | `constants.py:275-290` |
| `SEVERE_ILLNESS_DAYS` | {1:329, 2:291, 3:257} | 일/년 | 산재보험법 제66조 | `constants.py:293-297` |
| `SURVIVOR_BASE_RATIO` | 0.47 (47%) | 비율 | 산재보험법 제62조 | `constants.py:300` |
| `SURVIVOR_ADD_RATIO` | 0.05 (5%/인) | 비율 | 산재보험법 제62조 | `constants.py:301` |
| `SURVIVOR_MAX_RATIO` | 0.67 (67%) | 비율 | 산재보험법 제62조 | `constants.py:302` |
| `SURVIVOR_LUMP_SUM_DAYS` | 1,300 | 일 | 산재보험법 제62조 | `constants.py:303` |
| `FUNERAL_DAYS` | 120 | 일 | 산재보험법 제71조 | `constants.py:306` |
| `FUNERAL_LIMITS[2025]` | (18,554,400, 13,414,000) | 원 (최고, 최저) | 고용노동부 고시 | `constants.py:311` |
| `MINIMUM_HOURLY_WAGE[2025]` | 10,030 | 원/시간 | 최저임금위원회 | `constants.py:19` |

## 4. 계산 과정 (핵심)

### Step 1: 평균임금 결정
- 기본: 통상임금 환산일급 (`ow.daily_ordinary_wage`)
- `monthly_wage` 제공 시: `추정평균임금 = 월급여 ÷ 30`
- 두 값 중 큰 쪽 적용: `평균임금 = max(통상임금환산일급, 추정평균임금)`
- 코드: `industrial_accident.py:95-106`

### Step 2: 휴업급여 계산 (산재보험법 제52조, 제54조)
- 조건: `sick_leave_days > 0`
- **최저보상기준 적용 4단계** (`_calc_sick_leave` 함수):
  1. `기본 = 평균임금 × 70%`
  2. `기본 ≤ 최저보상기준 × 80%` 이면:
     - `보정값 = 평균임금 × 90%`
     - `보정값 > 최저보상기준 × 80%` → 최저보상기준 × 80% 적용
     - `보정값 ≤ 최저보상기준 × 80%` → 90% 적용
  3. 최종값 < 최저임금 일급(시급×8h) → 최저임금 일급 적용
- 총액: `휴업급여총액 = 일휴업급여 × 요양일수`
- 코드: `industrial_accident.py:204-252`

### Step 3: 상병보상연금 계산 (산재보험법 제66조)
- 조건: `severe_illness_grade` 1~3
- 공식: `연간액 = 평균임금 × 등급별일수`
  - 1급: 329일, 2급: 291일, 3급: 257일
- 코드: `industrial_accident.py:255-269`
- 주의: 상병보상연금 수급 시 휴업급여 미지급 (제66조 제2항, `industrial_accident.py:136-140`)

### Step 4: 장해급여 계산 (산재보험법 제57조)
- 등급 유효 범위: 1~14급
- **지급 형태 결정**:
  - 1~3급: 연금만 (`pension_only`)
  - 4~7급: 연금/일시금 선택 (`choice`)
  - 8~14급: 일시금만 (`lump_sum`)
- 공식: `장해급여 = 평균임금 × 적용일수`
- 코드: `industrial_accident.py:272-327` (`_calc_disability`)

### Step 5: 유족급여 계산 (산재보험법 제62조)
- 조건: `is_deceased == True` and `num_survivors > 0`
- **연금**: `지급비율 = min(0.47 + 0.05 × 유족수, 0.67)`
  - `연간유족연금 = 평균임금 × 365일 × 지급비율`
- **일시금**: `유족일시금 = 평균임금 × 1,300일`
- 코드: `industrial_accident.py:330-356` (`_calc_survivor`)

### Step 6: 장례비 계산 (산재보험법 제71조)
- 조건: `is_deceased == True`
- 공식: `장례비 = 평균임금 × 120일`
- 최고/최저 한도 적용: `FUNERAL_LIMITS[연도]`
- 코드: `industrial_accident.py:359-381` (`_calc_funeral`)

### Step 7: 보상금 합산
- `총보상금 = 휴업급여 + 상병보상연금 + 장해급여 + 유족급여 + 장례비`
- 코드: `industrial_accident.py:108-175`

## 5. 출력 항목

| 항목명 | 설명 | 단위 |
|--------|------|------|
| `avg_daily_wage` | 적용 1일 평균임금 | 원 |
| `sick_leave_daily` | 1일 휴업급여 | 원 |
| `sick_leave_total` | 휴업급여 총액 | 원 |
| `sick_leave_days` | 요양일수 | 일 |
| `min_comp_applied` | 최저보상기준 적용 여부 | bool |
| `illness_pension_daily` | 상병보상연금 1일분 | 원 |
| `illness_pension_annual` | 상병보상연금 연간액 | 원 |
| `illness_grade` | 중증요양상태 등급 | 정수 |
| `disability_amount` | 장해급여 금액 | 원 |
| `disability_grade` | 장해등급 | 정수 |
| `disability_type` | 지급형태 ("연금"/"일시금") | 문자열 |
| `disability_days` | 적용 보상일수 | 일 |
| `survivor_amount` | 유족급여 금액 | 원 |
| `survivor_type` | 지급형태 ("연금"/"일시금") | 문자열 |
| `survivor_ratio` | 유족연금 지급비율 | 비율 |
| `funeral_amount` | 장례비 | 원 |
| `total_compensation` | 전체 보상금 합산 | 원 |

## 6. 예외 처리 / 엣지 케이스

| 조건 | 처리 | 법적 근거 |
|------|------|-----------|
| `monthly_wage` 미입력 | 통상임금 환산일급만 사용 | `industrial_accident.py:105-106` |
| `disability_grade < 1` 또는 `> 14` | 장해급여 0원 반환 | `industrial_accident.py:280-281` |
| 1~3급에서 `disability_pension=False` | 경고: "연금만 가능" | 산재보험법 제57조 (`industrial_accident.py:295-298`) |
| 상병보상연금 + 휴업급여 동시 입력 | 경고: "중복 불가" (양쪽 모두 계산은 수행) | 산재보험법 제66조 제2항 (`industrial_accident.py:136-140`) |
| `num_survivors <= 0` | 유족급여 0원 | `industrial_accident.py:334-335` |
| `is_deceased == False` | 유족급여·장례비 미계산 | `industrial_accident.py:158,169` |
| 장례비 > 최고액 | 최고액 적용 | 고용노동부 고시 |
| 장례비 < 최저액 | 최저액 적용 | 고용노동부 고시 |
| 연도별 상수 미등록 | 가장 최근 연도 키 fallback | `industrial_accident.py:220,364-366` |
| `severe_illness_grade` 범위 외 (1~3 아닌 값) | 0일 반환 → 상병보상연금 0원 | `industrial_accident.py:260-261` |

## 7. 계산 예시

### 예시 1: 휴업급여 (평균임금 100,000원/일, 90일 요양, 2025년)

**입력:** 평균임금 = 100,000원/일, 요양일수 = 90일

| 단계 | 계산 | 결과 |
|------|------|------|
| 기본 휴업급여 | 100,000 × 70% | 70,000원/일 |
| 최저보상기준 80% | 80,240 × 80% | 64,192원 |
| 비교 | 70,000 > 64,192 | 기본율(70%) 적용 |
| 최저임금 일급 | 10,030 × 8 = 80,240 | 70,000 < 80,240이지만 70% 적용 우선 |
| 휴업급여 총액 | 70,000 × 90 | 6,300,000원 |

### 예시 2: 장해급여 + 유족급여 + 장례비 (사망사고, 2025년)

**입력:** 평균임금 = 120,000원/일, 장해등급 5급(일시금), 사망, 유족 3명(연금)

| 단계 | 계산 | 결과 |
|------|------|------|
| 장해급여(5급 일시금) | 120,000 × 869일 | 104,280,000원 |
| 유족연금 비율 | min(47% + 5%×3, 67%) | 62% |
| 유족연금 연간 | 120,000 × 365 × 62% | 27,156,000원/년 |
| 장례비 | 120,000 × 120일 = 14,400,000 | 범위 내(13,414,000~18,554,400) → 14,400,000원 |
| 총 보상금 | 104,280,000 + 27,156,000 + 14,400,000 | 145,836,000원 |

## 8. 관련 판례

| 판례번호 | 요지 | 코드 반영 위치 |
|----------|------|---------------|
| 대법원 2016두49223 | 산재보상 평균임금은 통상임금과 실지급액 중 유리한 쪽 적용 | `industrial_accident.py:96-99` (max 비교) |
| 대법원 2018두42440 | 장해등급 1~3급은 연금만 가능하며 일시금 선택 불가 | `DISABILITY_GRADE_TABLE` 1~3급 `pension_only` (`constants.py:276-278`) |
| 대법원 2015두3867 | 상병보상연금 수급 기간에는 휴업급여가 지급되지 않음 | `industrial_accident.py:136-140` (경고 처리) |
| 산재보험법 제54조 | 휴업급여 최저보상기준: 평균임금 70%가 기준 이하 시 90% 또는 기준의 80% 적용 | `_calc_sick_leave` 4단계 로직 (`industrial_accident.py:204-252`) |
