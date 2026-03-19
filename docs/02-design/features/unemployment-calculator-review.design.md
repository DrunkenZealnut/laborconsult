# Design: 실업급여 계산 모듈 리뷰

> Plan 참조: `docs/01-plan/features/unemployment-calculator-review.plan.md`

---

## 1. 변경 사항 요약

| # | 변경 | 파일 | 심각도 |
|---|------|------|--------|
| D-1 | 연도별 구직급여 상한액 테이블 추가 | `constants.py` | Critical |
| D-2 | 상한액 동적 조회로 전환 | `unemployment.py` | Critical |
| D-3 | 평균임금에 상여금/연차수당 가산 | `unemployment.py` | Major |
| D-4 | 테스트 케이스 갱신 및 추가 | `wage_calculator_cli.py` | Low |

---

## 2. 상세 설계

### D-1. `constants.py` — 연도별 구직급여 상한액 테이블

기존 `MINIMUM_HOURLY_WAGE`, `INSURANCE_RATES`와 동일한 패턴으로 연도별 dict 추가.

**추가 위치**: `MINIMUM_HOURLY_WAGE` 블록 직후 (line 21 이후)

```python
# ── 구직급여 상한액 (원/일, 고용보험법 시행령 제68조) ──────────────────────
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

**헬퍼 함수 불필요** — `MINIMUM_HOURLY_WAGE`와 동일하게 `.get(year, fallback)` 패턴으로 `unemployment.py`에서 직접 조회.

---

### D-2. `unemployment.py` — 상한액 동적 조회

#### 2a. import 변경

```python
# Before
from ..constants import MINIMUM_HOURLY_WAGE

# After
from ..constants import MINIMUM_HOURLY_WAGE, UNEMPLOYMENT_BENEFIT_UPPER
```

#### 2b. 모듈 상수 제거

```python
# 삭제
BENEFIT_UPPER_LIMIT  = 66_000   # 구직급여 상한 (2019년 이후, 원/일)
```

#### 2c. `calc_unemployment()` 내 상한액 조회 변경 (line 175)

```python
# Before
upper = float(BENEFIT_UPPER_LIMIT)

# After
upper = float(UNEMPLOYMENT_BENEFIT_UPPER.get(
    year, UNEMPLOYMENT_BENEFIT_UPPER[max(UNEMPLOYMENT_BENEFIT_UPPER)]
))
```

`max()` fallback: 등록되지 않은 미래 연도는 가장 최근 연도 값 사용 (기존 `MINIMUM_HOURLY_WAGE` 패턴과 동일).

#### 2d. 역전 경고 로직 유지

기존 `if lower > upper:` 블록은 그대로 유지. 2026년 기준 upper=68,100 > lower=66,048이므로 역전 미발생. 향후 최저임금이 추가 인상되어 하한이 상한을 초과하는 시점에 대비한 안전장치.

---

### D-3. `unemployment.py` — 평균임금에 상여금/연차수당 가산

#### 3a. 대상 구간

`calc_unemployment()` 내 "3. 평균임금 일액 산정" 블록 (line 149~170) 의 두 가지 경로 모두에 적용:

1. **`last_3m_wages` 제공 시** (line 150~155)
2. **`monthly_wage` 기반 추정 시** (line 156~164)

#### 3b. 상여금/연차수당 3개월 비례분 계산 공통 함수

별도 함수 추출 불필요 (인라인 처리). `WageInput`의 기존 필드 활용:
- `inp.annual_bonus_total` — 연간 상여금 총액
- `inp.unused_annual_leave_pay` — 최종 연차수당

```python
# 공통 가산분 (3개월 비례)
bonus_3m    = (inp.annual_bonus_total / 12) * 3 if inp.annual_bonus_total else 0
leave_pay_3m = (inp.unused_annual_leave_pay / 12) * 3 if inp.unused_annual_leave_pay else 0
extra_3m    = bonus_3m + leave_pay_3m
```

#### 3c. 경로별 적용

**경로 1: `last_3m_wages` 제공 시**

```python
if inp.last_3m_wages and inp.last_3m_days:
    base_3m   = sum(inp.last_3m_wages)
    total_3m  = base_3m + extra_3m
    avg_daily = total_3m / inp.last_3m_days
    formulas.append(
        f"평균임금 일액: ({base_3m:,.0f}원"
        + (f" + 상여금 {bonus_3m:,.0f}원 + 연차수당 {leave_pay_3m:,.0f}원" if extra_3m else "")
        + f") ÷ {inp.last_3m_days}일 = {avg_daily:,.1f}원"
    )
```

**경로 2: `monthly_wage` 추정 시**

```python
elif inp.monthly_wage:
    base_3m   = inp.monthly_wage * 3
    total_3m  = base_3m + extra_3m
    avg_daily = total_3m / 92
    formulas.append(
        f"평균임금 일액(추정): ({inp.monthly_wage:,.0f}원 × 3"
        + (f" + 상여금 {bonus_3m:,.0f}원 + 연차수당 {leave_pay_3m:,.0f}원" if extra_3m else "")
        + f") ÷ 92일 = {avg_daily:,.1f}원"
    )
```

**경로 3: 통상시급 fallback** — 변경 없음 (상여금/연차 정보 없는 최소 입력이므로)

#### 3d. 가산분 존재 시 안내 추가

```python
if extra_3m:
    formulas.append(
        f"  └ 상여금 3개월분: {inp.annual_bonus_total:,.0f}원/12×3 = {bonus_3m:,.0f}원"
        + f", 연차수당 3개월분: {inp.unused_annual_leave_pay:,.0f}원/12×3 = {leave_pay_3m:,.0f}원"
    )
```

---

### D-4. 테스트 케이스 갱신

#### 기존 테스트 영향 분석

| # | 설명 | reference_year | 영향 | 조치 |
|---|------|---------------|------|------|
| 17 | 3년 35세 월300만 하한 | 2025 | 무영향 (하한 적용 케이스) | 유지 |
| 18 | 11년 55세 월600만 상한 | 2025 | 무영향 (2025 상한 = 66,000 동일) | 유지 |
| 19 | 자발적이직 임금체불 | 2025 | 무영향 | 유지 |
| 20 | 피보험기간 부족 | 2025 | 무영향 | 유지 |

**기존 4개 테스트는 모두 `reference_year=2025`이므로 결과 불변.**

#### 신규 테스트 케이스 2건

**테스트 A: 2026년 상한액 적용 확인**

```python
{
    "id": 33,
    "desc": "실업급여 — 2026년 상한액 68,100원 적용 (10년 52세 월500만)",
    # 평균임금 일액: 5,000,000×3÷92 ≈ 163,043원 → 60% = 97,826원
    # 상한액(2026): 68,100원 → 상한 적용
    # 소정급여일수: 120개월 × 50세이상 → 270일
    # 총 구직급여: 68,100 × 270 = 18,387,000원
    "input": WageInput(
        wage_type=WageType.MONTHLY,
        monthly_wage=5_000_000,
        business_size=BusinessSize.OVER_5,
        reference_year=2026,
        insurance_months=120,
        age=52,
        is_involuntary_quit=True,
    ),
    "targets": ["unemployment"],
}
```

**테스트 B: 상여금/연차수당 포함 평균임금 산정**

```python
{
    "id": 34,
    "desc": "실업급여 — 상여금 600만원 + 연차수당 포함 평균임금 (5년 40세 월250만)",
    # base_3m: 2,500,000×3 = 7,500,000원
    # 상여금 3개월분: 6,000,000÷12×3 = 1,500,000원
    # 연차수당 3개월분: 600,000÷12×3 = 150,000원
    # total_3m: 7,500,000 + 1,500,000 + 150,000 = 9,150,000원
    # 평균임금 일액: 9,150,000÷92 ≈ 99,457원 → 60% = 59,674원
    # 하한액(2025): 64,192원 → 하한 적용
    # 소정급여일수: 60개월 × 50세미만 → 210일
    # 총 구직급여: 64,192 × 210 = 13,480,320원
    "input": WageInput(
        wage_type=WageType.MONTHLY,
        monthly_wage=2_500_000,
        business_size=BusinessSize.OVER_5,
        reference_year=2025,
        insurance_months=60,
        age=40,
        is_involuntary_quit=True,
        annual_bonus_total=6_000_000,
        unused_annual_leave_pay=600_000,
    ),
    "targets": ["unemployment"],
}
```

---

## 3. 구현 순서

```
Step 1: constants.py — UNEMPLOYMENT_BENEFIT_UPPER 테이블 추가
Step 2: unemployment.py — import 변경 + BENEFIT_UPPER_LIMIT 제거 + 동적 조회
Step 3: unemployment.py — 평균임금 상여금/연차수당 가산 로직
Step 4: wage_calculator_cli.py — 신규 테스트 #33, #34 추가
Step 5: python3 wage_calculator_cli.py 전체 실행 → 전 케이스 통과 확인
```

---

## 4. 변경하지 않는 것

| 항목 | 이유 |
|------|------|
| `UnemploymentResult` dataclass | 필드 변경 없음 — 기존 구조로 충분 |
| `_get_benefit_days()` | 소정급여일수 테이블은 nodong.kr과 일치 |
| `_ineligible()` | 수급 불가 로직 변경 없음 |
| `WageInput` 모델 | `annual_bonus_total`, `unused_annual_leave_pay` 이미 존재 |
| 조기재취업수당 로직 | 변경 사항 없음 |
| `facade.py` | unemployment 관련 라우팅 변경 없음 |

---

## 5. 검증 매트릭스

| 검증 항목 | 입력 조건 | 기대 결과 |
|----------|----------|----------|
| 2026 상한액 | `reference_year=2026`, 고임금 | `upper_limit=68,100`, 역전 경고 없음 |
| 2025 상한액 | `reference_year=2025`, 고임금 | `upper_limit=66,000` (기존 동일) |
| 미래 연도 fallback | `reference_year=2027` | 가장 최근 등록 연도(2026) 값 사용 |
| 상여금 포함 | `annual_bonus_total=6_000_000` | 평균임금 일액 증가, formula에 내역 표시 |
| 상여금 미제공 | `annual_bonus_total=0` | 기존과 동일 (가산분 0) |
| 기존 테스트 #17~#20 | 변경 없음 | 모두 통과 |
