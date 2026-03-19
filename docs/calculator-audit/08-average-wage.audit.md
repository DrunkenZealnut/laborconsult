# 평균임금 계산기 감사 시트

## 1. 개요

| 항목 | 내용 |
|------|------|
| 계산기명 | 평균임금 계산기 |
| 코드 파일 | `wage_calculator/calculators/average_wage.py` |
| 함수명 | `calc_average_wage(inp, ow)` |
| 적용 법조문 | 근로기준법 제2조 제1항 제6호 (평균임금 정의), 근로기준법 시행령 제2조 (통상임금 비교) |
| 5인 미만 적용 | 적용 (평균임금은 사업장 규모와 무관) |

## 2. 입력 항목

| 필드명(한글) | 필드명(영문) | 타입 | 기본값 | 필수여부 |
|-------------|-------------|------|--------|---------|
| 임금입력 | `inp: WageInput` | WageInput | - | 필수 |
| 통상임금 결과 | `ow: OrdinaryWageResult` | OrdinaryWageResult | - | 필수 |
| 최근 3개월 임금 | `inp.last_3m_wages` | Optional[list] | None | 선택 |
| 최근 3개월 일수 | `inp.last_3m_days` | Optional[int] | None | 선택 |
| 퇴직일(산정사유발생일) | `inp.end_date` | Optional[str] | None | 선택 |
| 월 기본급 | `inp.monthly_wage` | Optional[float] | None | 선택 |
| 연간 상여금 총액 | `inp.annual_bonus_total` | float | 0.0 | 선택 |
| 미사용 연차수당 | `inp.unused_annual_leave_pay` | float | 0.0 | 선택 |

## 3. 적용 상수

| 상수명 | 값 | 단위 | 법적 근거 | 코드 위치 |
|--------|-----|------|-----------|-----------|
| `AVG_WAGE_PERIOD_DAYS` | 92 | 일 | 근기법 제2조 (3개월 기준 일수) | constants.py:55 |

## 4. 계산 과정 (핵심)

### Step 1: 산정기간 일수 결정

**우선순위** (`average_wage.py:140-157`, `_calc_period_days()`):

1. `last_3m_days` 명시값이 있으면 사용
2. `end_date` 기반 3개월 역산 (calendar 모듈로 정확한 일수 계산)
3. 기본값 `AVG_WAGE_PERIOD_DAYS` = 92일

- 코드: `period_days = _calc_period_days(inp)` (`average_wage.py:57`)
- `_subtract_months()` 함수로 월말 보정 포함 역산 (`average_wage.py:187-196`)

### Step 2: 3개월 임금총액 산출

**입력 형태별 처리** (`average_wage.py:160-184`, `_calc_wage_total()`):

| 입력 형태 | 처리 | 코드 위치 |
|-----------|------|-----------|
| `list[float]` | 각 월 합산: `sum(inp.last_3m_wages)` | `average_wage.py:178` |
| `list[dict]` | 각 월 `base + allowance` 합산 | `average_wage.py:176` |
| None (monthly_wage 있음) | `monthly_wage × 3` 추정 | `average_wage.py:182` |
| None (monthly_wage 없음) | `통상임금(월) × 3` 추정 | `average_wage.py:184` |

### Step 3: 상여금 및 연차수당 가산

**공식** (`average_wage.py:63-64`):

```
상여금_가산액 = 연간_상여금_총액 × 3 ÷ 12
연차수당_가산액 = 미사용_연차수당 × 3 ÷ 12
```

- 법적 근거: 평균임금 산정 시 상여금과 연차수당은 3개월 비례 가산
- 코드: `bonus_addition = inp.annual_bonus_total * 3 / 12`
- 코드: `leave_addition = inp.unused_annual_leave_pay * 3 / 12`

### Step 4: 1일 평균임금 산출

**공식** (`average_wage.py:69-70`):

```
가산_후_총액 = 3개월_임금총액 + 상여금_가산액 + 연차수당_가산액
1일_평균임금 = 가산_후_총액 ÷ 산정기간_일수
```

- 코드: `grand_total = wage_total + bonus_addition + leave_addition`
- 코드: `avg_daily_3m = grand_total / safe_days`
- 0 나눗셈 방지: `safe_days = max(period_days, 1)` (`average_wage.py:69`)

### Step 5: 통상임금 비교 (유리원칙)

**공식** (`average_wage.py:86-105`):

```
if 통상임금_일급 > 3개월_평균임금:
    적용_평균임금 = 통상임금_일급    # 통상임금 기준
else:
    적용_평균임금 = 3개월_평균임금    # 3개월 기준
```

- 법적 근거: 근로기준법 시행령 제2조 (평균임금이 통상임금보다 낮으면 통상임금 적용)
- 통상임금 환산일급: `ow.daily_ordinary_wage` (`average_wage.py:86`)

## 5. 출력 항목

| 항목명 | 설명 | 단위 |
|--------|------|------|
| `avg_daily_wage` | 적용 1일 평균임금 (최종값) | 원/일 |
| `avg_daily_3m` | 3개월 기준 평균임금 | 원/일 |
| `avg_daily_ordinary` | 통상임금 환산 일급 | 원/일 |
| `used_basis` | 적용 기준 ("3개월" 또는 "통상임금") | 문자열 |
| `period_days` | 산정기간 총 일수 | 일 |
| `wage_total` | 3개월 임금총액 | 원 |
| `bonus_addition` | 상여금 가산액 | 원 |
| `leave_addition` | 연차수당 가산액 | 원 |
| `grand_total` | 가산 후 총액 | 원 |
| `breakdown` | 계산 내역 상세 | dict |
| `formulas` | 적용 공식 목록 | list |
| `warnings` | 주의사항 목록 | list |
| `legal_basis` | 법적 근거 목록 | list |

## 6. 예외 처리 / 엣지 케이스

| 조건 | 처리 | 법적 근거 |
|------|------|-----------|
| 산정기간 일수 0일 | `max(period_days, 1)`로 0 나눗셈 방지 (`average_wage.py:69`) | 방어 코드 |
| `last_3m_wages` 미입력 + `monthly_wage` 있음 | `monthly_wage × 3` 추정 (`average_wage.py:182`) | 간이 산정 |
| `last_3m_wages` 미입력 + `monthly_wage` 없음 | `통상임금(월) × 3` 추정 (`average_wage.py:184`) | 간이 산정 |
| `last_3m_wages`가 dict 리스트 | `base + allowance` 합산 (`average_wage.py:176`) | 항목별 입력 지원 |
| 평균임금 < 통상임금 | 통상임금을 평균임금으로 적용 (`average_wage.py:88-96`) | 근기법 시행령 제2조 |
| `end_date` 월말 보정 | `_subtract_months()`에서 `min(d.day, max_day)` 처리 (`average_wage.py:195`) | 2월 등 짧은 달 처리 |
| 상여금/연차수당 0원 | 가산하지 않음 (`average_wage.py:63-64`) | - |

## 7. 계산 예시

### 예시 1: 3개월 임금 직접 입력 (상여금 연 400만원, 연차수당 50만원)

입력:
- `last_3m_wages` = [3,000,000, 3,200,000, 3,100,000]
- `last_3m_days` = 91일
- `annual_bonus_total` = 4,000,000원
- `unused_annual_leave_pay` = 500,000원
- 통상임금 일급 = 95,694원 (시급 11,962원 × 8시간)

**Step 1**: 산정기간 = 91일 (명시값)

**Step 2**: 3개월 임금총액 = 3,000,000 + 3,200,000 + 3,100,000 = 9,300,000원

**Step 3**:
- 상여금 가산 = 4,000,000 × 3/12 = 1,000,000원
- 연차수당 가산 = 500,000 × 3/12 = 125,000원

**Step 4**:
- 가산 후 총액 = 9,300,000 + 1,000,000 + 125,000 = 10,425,000원
- 1일 평균임금 = 10,425,000 ÷ 91 = 114,560원

**Step 5**:
- 통상임금 일급 95,694원 < 평균임금 114,560원
- 적용 기준: "3개월" (평균임금이 높으므로)
- 적용 평균임금 = 114,560원/일

### 예시 2: 월급만 입력 (통상임금이 더 높은 경우)

입력:
- `monthly_wage` = 2,500,000원
- `last_3m_wages` = None
- 통상임금 일급 = 100,000원 (수당 포함)

**Step 1**: 산정기간 = 92일 (기본값)

**Step 2**: 3개월 임금총액 = 2,500,000 × 3 = 7,500,000원 (추정)

**Step 3**: 상여금/연차수당 없음

**Step 4**:
- 1일 평균임금 = 7,500,000 ÷ 92 = 81,522원

**Step 5**:
- 통상임금 일급 100,000원 > 평균임금 81,522원
- 적용 기준: "통상임금"
- 적용 평균임금 = 100,000원/일

## 8. 관련 판례

| 판례번호 | 요지 | 코드 반영 위치 |
|---------|------|--------------|
| (근기법 시행령 제2조) | 평균임금이 통상임금보다 낮으면 통상임금을 평균임금으로 적용 (유리원칙) | `average_wage.py:86-105` |

> 참고: 본 계산기는 퇴직금(`severance.py`)에서 별도로 호출하는 1년 기준 평균임금 산정과는 별개의 독립 계산기입니다. 퇴직금에서는 `last_1y_wages`/`last_1y_days` 필드를 활용한 1년 기준 산정도 지원합니다.
