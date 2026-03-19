# Plan: 실업급여 계산 모듈 리뷰

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | unemployment-calculator-review |
| 작성일 | 2026-03-08 |
| 참조 | https://www.nodong.kr/UnemploymentPay_cal |
| 예상 소요 | 수정 범위 소규모 (2~3 파일) |

### Value Delivered

| 관점 | 내용 |
|------|------|
| Problem | 구직급여 상한액이 66,000원(2019년)으로 고정되어 있어 2025~2026년 실제 기준과 불일치. 평균임금 산정 시 상여금/연차수당 미반영 |
| Solution | 연도별 상한액 테이블 도입, 평균임금에 상여금/연차수당 반영 로직 추가 |
| Function UX Effect | 사용자가 실업급여 계산 시 실제 고용보험법 기준과 일치하는 정확한 금액 확인 가능 |
| Core Value | 법적 정확성 확보 — nodong.kr 공식 계산기와 동일한 결과 산출 |

---

## 1. 현황 분석

### 1.1 현재 구현 (`wage_calculator/calculators/unemployment.py`)

| 항목 | 현재 구현 | 비고 |
|------|----------|------|
| 상한액 | 66,000원 고정 (`BENEFIT_UPPER_LIMIT`) | 2019년 이후 고정으로 하드코딩 |
| 하한액 | 최저임금 × 80% × 8h (동적) | 정상 작동 |
| 평균임금 산정 | `last_3m_wages` 또는 `monthly_wage × 3 / 92` | 상여금/연차수당 미포함 |
| 소정급여일수 | 5단계 테이블 (피보험기간 × 나이/장애) | nodong.kr과 일치 |
| 조기재취업수당 | 남은 급여의 50% | 정상 |
| 수급자격 판단 | 피보험기간 180일 + 비자발적 이직 | 정상 |

### 1.2 nodong.kr 기준과 비교

| 항목 | nodong.kr (2026년) | 현재 코드 | 차이 |
|------|-------------------|----------|------|
| 상한액 | **68,100원/일** | 66,000원/일 | **-2,100원 오류** |
| 하한액 | 66,048원/일 | 66,048원/일 | 일치 |
| 평균임금 | 3개월 임금 + 상여금/12×3 + 연차수당/12×3 | 3개월 임금만 | **누락** |
| 1일 통상임금 | 별도 입력 가능 | 미지원 | 참고 사항 |

---

## 2. 발견된 문제점

### 2.1 [Critical] 상한액 고정값 오류

**현재**: `BENEFIT_UPPER_LIMIT = 66_000` (2019년 이후 고정)

**실제 변경 이력**:
| 연도 | 상한액(원/일) | 근거 |
|------|-------------|------|
| 2019~2023 | 66,000 | 고용보험법 시행령 제68조 |
| 2024 | 66,000 | 동결 |
| 2025 | 66,000 | 동결 (최저임금 인상에도 불구) |
| 2026 | **68,100** | 인상 (고용노동부 고시) |

- 2026년 기준 코드의 상한 66,000 < 하한 66,048 → **역전 발생** → 코드가 `upper = lower` 처리하지만, 실제로는 상한이 68,100원으로 인상되어 역전 없음
- 테스트 케이스 #18도 상한 66,000 기준으로 작성됨 → 수정 필요

### 2.2 [Major] 평균임금에 상여금/연차수당 미반영

nodong.kr은 평균임금 산정 시:
```
평균임금 = (최종 3개월 임금총액 + 연간상여금총액/12×3 + 최종연차수당/12×3) ÷ 최종 3개월 일수
```

현재 코드는 `last_3m_wages` 합계 또는 `monthly_wage × 3` 만 사용하여 상여금·연차수당 가산 누락.

`WageInput`에 이미 `annual_bonus_total`과 `unused_annual_leave_pay` 필드가 존재하므로 활용 가능.

### 2.3 [Minor] 연도별 상한액 테이블 부재

상한액이 하드코딩(66,000)이라 향후 법 개정 시 코드 수정 필요. `constants.py`에 연도별 테이블로 관리하는 것이 유지보수에 유리.

---

## 3. 개선 계획

### 3.1 상한액을 연도별 테이블로 변경

**파일**: `wage_calculator/constants.py`

```python
# 구직급여 상한액 (원/일, 고용보험법 시행령 제68조)
UNEMPLOYMENT_BENEFIT_UPPER: dict[int, int] = {
    2019: 66_000,
    2020: 66_000,
    2021: 66_000,
    2022: 66_000,
    2023: 66_000,
    2024: 66_000,
    2025: 66_000,
    2026: 68_100,
}
```

**파일**: `wage_calculator/calculators/unemployment.py`
- `BENEFIT_UPPER_LIMIT` 상수 제거
- `constants.py`의 연도별 테이블에서 동적 조회

### 3.2 평균임금 산정에 상여금/연차수당 반영

**파일**: `wage_calculator/calculators/unemployment.py` — `calc_unemployment()` 함수

평균임금 산정 구간(3단계)에서 `inp.annual_bonus_total`과 `inp.unused_annual_leave_pay`가 있으면 가산:

```python
# 상여금/연차수당 3개월 비례분 가산
bonus_3m = (inp.annual_bonus_total / 12) * 3 if inp.annual_bonus_total else 0
leave_pay_3m = (inp.unused_annual_leave_pay / 12) * 3 if inp.unused_annual_leave_pay else 0
total_3m = sum(inp.last_3m_wages) + bonus_3m + leave_pay_3m
```

### 3.3 테스트 케이스 업데이트

**파일**: `wage_calculator_cli.py`

- 테스트 #18: `reference_year=2026`으로 변경하고 상한액 68,100 반영
- 신규 테스트: 상여금 포함 평균임금 산정 케이스 추가

---

## 4. 수정 대상 파일

| 파일 | 변경 내용 | 영향도 |
|------|----------|--------|
| `wage_calculator/constants.py` | `UNEMPLOYMENT_BENEFIT_UPPER` 연도별 테이블 추가 | Low |
| `wage_calculator/calculators/unemployment.py` | 상한액 동적 조회 + 평균임금 상여금/연차수당 반영 | Medium |
| `wage_calculator_cli.py` | 테스트 케이스 #17~#20 검증 및 신규 추가 | Low |

---

## 5. 범위 외 (Out of Scope)

- 일용직/예술인/특수고용직 실업급여 (별도 계산 체계, 현재 미지원)
- 실업인정 신청 절차 시뮬레이션
- 자발적 이직 예외 사유 자동 판정 로직 고도화
- 수급기간 만료일 계산 (이직일 기준 12개월)

---

## 6. 검증 기준

| 검증 항목 | 기대 결과 |
|----------|----------|
| 2026년 상한액 | 68,100원/일 적용, 역전 경고 미발생 |
| 2025년 상한액 | 66,000원/일 (기존과 동일) |
| 상여금 포함 평균임금 | nodong.kr과 동일한 산식 적용 |
| 기존 테스트 #17~#20 | 모두 통과 (2025년 기준 결과 불변) |
| 신규 테스트 | 상여금/연차수당 포함 케이스 통과 |
