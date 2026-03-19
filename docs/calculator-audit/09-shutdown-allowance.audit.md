# 휴업수당 계산기 감사 시트

## 1. 개요

| 항목 | 내용 |
|------|------|
| 계산기명 | 휴업수당 계산기 |
| 코드 파일 | `wage_calculator/calculators/shutdown_allowance.py` |
| 함수명 | `calc_shutdown_allowance(inp, ow)` |
| 적용 법조문 | 근로기준법 제46조 (휴업수당) |
| 5인 미만 적용 | 적용 (근기법 제46조는 5인 미만 사업장에도 적용) |

## 2. 입력 항목

| 필드명(한글) | 필드명(영문) | 타입 | 기본값 | 필수여부 |
|-------------|-------------|------|--------|---------|
| 임금입력 | `inp: WageInput` | WageInput | - | 필수 |
| 통상임금 결과 | `ow: OrdinaryWageResult` | OrdinaryWageResult | - | 필수 |
| 총 휴업일수 | `inp.shutdown_days` | int | 0 | 필수 |
| 사용자 귀책사유 여부 | `inp.is_employer_fault` | bool | True | 필수 |
| 1일 소정근로시간 | `inp.schedule.daily_work_hours` | float | 8.0 | 필수 |
| 부분 휴업 시간 | `inp.shutdown_hours_per_day` | Optional[float] | None | 선택 |
| 최근 3개월 임금 | `inp.last_3m_wages` | Optional[list] | None | 선택 |
| 최근 3개월 일수 | `inp.last_3m_days` | Optional[int] | None | 선택 |
| 월 기본급 | `inp.monthly_wage` | Optional[float] | None | 선택 |

## 3. 적용 상수

| 상수명 | 값 | 단위 | 법적 근거 | 코드 위치 |
|--------|-----|------|-----------|-----------|
| `SHUTDOWN_RATE` | 0.70 | 비율 | 근기법 제46조 (평균임금의 70% 이상) | constants.py:61 |

## 4. 계산 과정 (핵심)

### Step 1: 입력 검증

- 휴업일수 <= 0 이면 즉시 반환 (`shutdown_allowance.py:45-51`)
- 불가항력(천재지변 등) 휴업이면 미발생으로 즉시 반환 (`shutdown_allowance.py:53-65`)
- 코드: `if not inp.is_employer_fault:` — 사용자 귀책사유가 아니면 미발생

### Step 2: 1일 통상임금 산출

**공식** (`shutdown_allowance.py:40-42`):

```
1일_통상임금 = 통상시급 × 1일_소정근로시간
```

- 코드: `ordinary_daily = hourly * daily_hours`

### Step 3: 1일 평균임금 산정 (간이)

**우선순위** (`shutdown_allowance.py:149-162`, `_calc_avg_daily_wage()`):

1. `last_3m_wages` 있으면: `sum(last_3m_wages) ÷ (last_3m_days or 92)`
2. `monthly_wage` 있으면: `(monthly_wage × 3) ÷ 92`
3. 통상시급 기반 추정: `(시급 × 일근로시간 × 주근무일 × 52/12 × 3) ÷ 92`

### Step 4: 평균임금 70% vs 통상임금 비교

**공식** (`shutdown_allowance.py:70-94`):

```
평균임금_70퍼 = 1일_평균임금 × 0.70

if 평균임금_70퍼 > 1일_통상임금:
    1일_휴업수당 = 1일_통상임금        # 통상임금 적용 (제46조 제2항)
else:
    1일_휴업수당 = 평균임금_70퍼       # 평균임금 70% 적용
```

- 법적 근거: 근기법 제46조 제2항 — 평균임금 70%가 통상임금을 초과하면 통상임금을 지급하면 됨

### Step 5: 부분 휴업 처리

**조건**: `shutdown_hours_per_day`가 입력되고, `daily_hours > 0`일 때 (`shutdown_allowance.py:97-111`)

**공식**:

```
부분_휴업_비율 = 1일_미근로시간 ÷ 1일_소정근로시간
1일_휴업수당 = 1일_휴업수당(전일) × 부분_휴업_비율
```

- 코드: `partial_ratio = inp.shutdown_hours_per_day / daily_hours`
- `partial_ratio < 1.0`일 때만 부분 휴업 적용

### Step 6: 총액 산출

**공식** (`shutdown_allowance.py:114`):

```
휴업수당_총액 = 1일_휴업수당 × 휴업일수
```

- 코드: `total = daily_allowance * inp.shutdown_days`

## 5. 출력 항목

| 항목명 | 설명 | 단위 |
|--------|------|------|
| `shutdown_allowance` | 휴업수당 총액 | 원 |
| `daily_shutdown_allowance` | 1일 휴업수당 | 원 |
| `avg_wage_70_pct` | 평균임금 70% | 원 |
| `daily_ordinary_wage` | 1일 통상임금 | 원 |
| `is_ordinary_wage_applied` | 통상임금 적용 여부 | bool |
| `is_partial_shutdown` | 부분 휴업 여부 | bool |
| `shutdown_days` | 휴업일수 | 일 |
| `partial_ratio` | 부분 휴업 비율 | float |
| `breakdown` | 계산 내역 상세 | dict |
| `formulas` | 적용 공식 목록 | list |
| `warnings` | 주의사항 목록 | list |
| `legal_basis` | 법적 근거 목록 | list |

## 6. 예외 처리 / 엣지 케이스

| 조건 | 처리 | 법적 근거 |
|------|------|-----------|
| 휴업일수 <= 0 | 즉시 반환 (미입력 안내) (`shutdown_allowance.py:45-51`) | 방어 코드 |
| 불가항력(천재지변 등) 휴업 | 미발생 반환 (`shutdown_allowance.py:53-65`) | 근기법 제46조 (사용자 귀책사유 한정) |
| 평균임금 70% > 통상임금 | 통상임금 적용 (`shutdown_allowance.py:82-88`) | 근기법 제46조 제2항 |
| 부분 휴업 (미근로시간 < 소정시간) | 비례 적용 (`shutdown_allowance.py:99-111`) | 근기법 제46조 |
| `last_3m_wages` 미입력 | `monthly_wage × 3 ÷ 92` 또는 시급 기반 추정 (`shutdown_allowance.py:157-162`) | 간이 산정 |
| `last_3m_days` 미입력 | 기본 92일 사용 (`shutdown_allowance.py:153`) | 3개월 기준 |

## 7. 계산 예시

### 예시 1: 전일 휴업 20일 (월급 300만원, 평균임금 70% < 통상임금)

입력:
- `monthly_wage` = 3,000,000원
- `shutdown_days` = 20일
- `is_employer_fault` = True
- 통상시급 = 14,354원, 1일 8시간

**Step 2**: 1일 통상임금 = 14,354원 × 8 = 114,833원

**Step 3**: 1일 평균임금 = (3,000,000 × 3) ÷ 92 = 97,826원

**Step 4**:
- 평균임금 70% = 97,826원 × 0.70 = 68,478원
- 68,478원 < 114,833원 (통상임금)
- 적용: 평균임금 70% = 68,478원

**Step 6**: 휴업수당 총액 = 68,478원 × 20일 = 1,369,560원

### 예시 2: 부분 휴업 (4시간 미근로 / 8시간 소정, 15일)

입력:
- `monthly_wage` = 2,500,000원
- `shutdown_days` = 15일
- `shutdown_hours_per_day` = 4.0
- `is_employer_fault` = True
- 통상시급 = 11,962원, 1일 8시간

**Step 2**: 1일 통상임금 = 11,962원 × 8 = 95,694원

**Step 3**: 1일 평균임금 = (2,500,000 × 3) ÷ 92 = 81,522원

**Step 4**:
- 평균임금 70% = 81,522원 × 0.70 = 57,065원
- 57,065원 < 95,694원
- 적용: 평균임금 70% = 57,065원

**Step 5**: 부분 휴업 적용
- 비율 = 4시간 ÷ 8시간 = 50%
- 1일 휴업수당 = 57,065원 × 0.50 = 28,533원

**Step 6**: 휴업수당 총액 = 28,533원 × 15일 = 427,995원

## 8. 관련 판례

| 판례번호 | 요지 | 코드 반영 위치 |
|---------|------|--------------|
| (법조문 기반) | 근기법 제46조 제1항: 사용자 귀책사유 휴업 시 평균임금의 70% 이상 지급 | `shutdown_allowance.py:70` |
| (법조문 기반) | 근기법 제46조 제2항: 평균임금 70%가 통상임금 초과 시 통상임금 지급 | `shutdown_allowance.py:82-88` |

> 참고: 본 계산기의 평균임금 산정은 간이 방식(`_calc_avg_daily_wage`)을 사용합니다. 정밀한 평균임금 산정이 필요한 경우 별도의 `average_wage.py`(평균임금 계산기)를 먼저 실행한 후 그 결과를 활용하는 것이 권장됩니다.
