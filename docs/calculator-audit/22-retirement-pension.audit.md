# 퇴직연금 감사 시트

## 1. 개요

| 항목 | 내용 |
|------|------|
| 계산기명 | 퇴직연금 계산기 |
| 코드 파일 | `wage_calculator/calculators/retirement_pension.py` |
| 함수명 | `calc_retirement_pension(inp: WageInput, ow: OrdinaryWageResult, severance_result: SeveranceResult | None) -> RetirementPensionResult` |
| 적용 법조문 | 근로자퇴직급여보장법 제15조(DB형 급여 수준), 제17조(DC형 부담금 납입) |
| 5인 미만 적용 여부 | 적용 (퇴직급여 제도는 1인 이상 사업장 적용, 규모 무관) |

## 2. 입력 항목

| 필드명(한글) | 필드명(영문) | 타입 | 기본값 | 필수여부 |
|-------------|-------------|------|--------|---------|
| 연금 유형 | `pension_type` | `str` | `""` | 선택 ("DB"/"DC", 빈 문자열이면 DB) |
| 입사일 | `start_date` | `str` | `None` | DB형 필수 (SeveranceResult 없을 때) |
| 퇴직일 | `end_date` | `str` | `None` | 선택 (None이면 오늘) |
| 월급여 | `monthly_wage` | `float` | `None` | DC형 필수 (연봉이력 없을 때) |
| 연도별 연간임금총액 | `annual_wage_history` | `list[float]` | `None` | DC형 선택 |
| DC 운용수익률 | `dc_return_rate` | `float` | `0.0` | DC형 선택 |
| 퇴직금 계산 결과 | `severance_result` | `SeveranceResult` | `None` | DB형 선택 (있으면 우선) |
| 시간당 통상임금 | `ow.hourly_ordinary_wage` | `float` | - | DB형 필수 (SeveranceResult 없을 때) |
| 월 통상임금 | `ow.monthly_ordinary_wage` | `float` | - | DC형 필수 (월급여 없을 때) |

## 3. 적용 상수

| 상수명 | 값 | 단위 | 법적 근거 | 코드 위치 |
|--------|-----|------|-----------|----------|
| DB형 계산기준 | 일평균임금 × 30일 × (재직일수/365) | 원 | 퇴직급여보장법 제15조 | `retirement_pension.py:71` |
| DC형 적립기준 | 연간임금총액 / 12 | 원/년 | 퇴직급여보장법 제17조 | `retirement_pension.py:116-117` |
| 일 평균임금 환산 | 시간급 × 8시간 | 원/일 | 실무 관행 | `retirement_pension.py:64` |
| 운용수익 | 복리 계산: `(누적 + 적립) × (1 + 수익률)` | 원 | DC형 실무 | `retirement_pension.py:141-143` |

## 4. 계산 과정 (핵심)

### DB형 (확정급여형)

#### Step 1: 연금유형 판정
- `pension_type` 대문자 변환, 빈 문자열이면 "DB"
- 코드: `retirement_pension.py:38`

#### Step 2-A: SeveranceResult 연동 (우선)
- 조건: SeveranceResult 제공 + 수급 자격 있음
- `총수령액 = 퇴직금` (퇴직금과 동일)
- 코드: `retirement_pension.py:57-61`
- 법적 근거: 퇴직급여보장법 제15조

#### Step 2-B: 자체 계산 (SeveranceResult 없을 때)
- 공식: `일평균임금 = 시간급 × 8`
- 공식: `재직일수 = (퇴직일 - 입사일).days`
- 공식: `근속연수 = round(재직일수 / 365, 2)`
- 공식: `DB형수령액 = 일평균임금 × 30 × (재직일수 / 365)`
- 코드: `retirement_pension.py:64-75`

### DC형 (확정기여형)

#### Step 3: 연간 적립금 산출
- **연봉이력 있을 때**: 각 연도 `적립금 = 연간임금총액 / 12`
- **연봉이력 없을 때**: `연간임금 = (월급여 or 월통상임금) × 12`, 재직연수만큼 반복
- 재직연수: `max(1, round((퇴직일 - 입사일).days / 365))`
- 코드: `retirement_pension.py:114-133`
- 법적 근거: 퇴직급여보장법 제17조

#### Step 4: 운용수익 계산 (DC형, 복리)
- 수익률 > 0이면 복리 적용:
  - `누적 = (누적 + 당해적립금) × (1 + 수익률)`
  - `운용수익 = 누적 - 총적립금`
  - `총수령액 = 누적`
- 수익률 = 0이면: `총수령액 = 총적립금`
- 코드: `retirement_pension.py:139-155`

## 5. 출력 항목

| 항목명 | 설명 | 단위 |
|--------|------|------|
| `pension_type` | 연금 유형 ("DB"/"DC") | 문자열 |
| `total_pension` | 총 퇴직연금 수령액 | 원 |
| `total_contribution` | 총 적립금 (DC형) | 원 |
| `investment_return` | 운용수익 (DC형) | 원 |
| `service_years` | 근속연수 | 년 |
| `annual_contributions` | 연도별 적립 내역 (DC형) | list[dict] |

## 6. 예외 처리 / 엣지 케이스

| 조건 | 처리 | 법적 근거 |
|------|------|-----------|
| `pension_type` 빈 문자열 | "DB"로 기본 설정 | `retirement_pension.py:38` |
| DB형 + SeveranceResult 없음 + `start_date` 없음 | `service_days = 0` → 수령액 0 + 경고 | `retirement_pension.py:67,77-78` |
| DB형 + `end_date` 미입력 | `date.today()` 사용 | `retirement_pension.py:66` |
| DC형 + `annual_wage_history` 없음 + `monthly_wage` 없음 | `ow.monthly_ordinary_wage × 12` 사용 | `retirement_pension.py:123` |
| DC형 + `start_date` 없음 | 재직연수 `max(1, ...)` → 최소 1년 | `retirement_pension.py:126` |
| DC형 + `dc_return_rate = 0` | 운용수익 0원, 총수령액 = 총적립금 + 경고 | `retirement_pension.py:150-155,161-165` |
| DB형 운용손실 | 회사 책임 (근로자 영향 없음) 안내 | `retirement_pension.py:80-83` |
| DC형 운용손실 | 근로자 책임 안내 | `retirement_pension.py:157-160` |
| DB형 `service_years` 소수점 | `round(service_days / 365, 2)` 소수 2자리 | `retirement_pension.py:68` |

## 7. 계산 예시

### 예시 1: DB형 (시간급 20,000원, 근속 15년)

**입력:** 시간급 = 20,000원, 재직일수 = 5,475일 (15년), DB형

| 단계 | 계산 | 결과 |
|------|------|------|
| 일평균임금 | 20,000 × 8 | 160,000원/일 |
| 근속연수 | round(5,475 / 365, 2) | 15.00년 |
| DB형 수령액 | 160,000 × 30 × (5,475 / 365) | 72,000,000원 |

### 예시 2: DC형 (연도별 연봉이력 3년, 수익률 3%)

**입력:** 연도별 연간임금 = [36,000,000, 38,000,000, 40,000,000], `dc_return_rate = 0.03`

| 단계 | 계산 | 결과 |
|------|------|------|
| 1년차 적립 | 36,000,000 / 12 | 3,000,000원 |
| 1년차 누적 | (0 + 3,000,000) × 1.03 | 3,090,000원 |
| 2년차 적립 | 38,000,000 / 12 | 3,166,667원 |
| 2년차 누적 | (3,090,000 + 3,166,667) × 1.03 | 6,444,367원 |
| 3년차 적립 | 40,000,000 / 12 | 3,333,333원 |
| 3년차 누적 | (6,444,367 + 3,333,333) × 1.03 | 10,081,031원 |
| 총 적립금 | 3,000,000 + 3,166,667 + 3,333,333 | 9,500,000원 |
| 운용수익 | 10,081,031 - 9,500,000 | 581,031원 |
| 총 수령액 | | 10,081,031원 |

## 8. 관련 판례

| 판례번호 | 요지 | 코드 반영 위치 |
|----------|------|---------------|
| 대법원 2019다288827 | DB형 퇴직연금은 퇴직금과 동일한 수준 이상 보장해야 함 | `_calc_db` 함수 전체 (퇴직금 공식 동일 적용) |
| 대법원 2018다271643 | DC형 퇴직연금 적립금은 연간임금총액의 1/12 이상이어야 함 | `retirement_pension.py:116-117` (연간임금/12 계산) |
| 근로자퇴직급여보장법 제15조 | DB형 급여수준: 가입자 퇴직일 기준 계속근로기간 1년에 대해 30일분 이상의 평균임금 | `_calc_db` 공식 (일평균임금 × 30 × 근속연수) |
| 근로자퇴직급여보장법 제17조 | DC형 사업주 부담금: 매년 연간임금총액의 1/12 이상 의무 적립 | `_calc_dc` 적립금 계산 로직 |
