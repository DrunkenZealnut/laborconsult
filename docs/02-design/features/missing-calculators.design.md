# 누락 계산 기능 추가 Design Document

> **Summary**: Q&A 분석 기반 누락 계산기 5개 FR의 상세 설계
>
> **Project**: laborconsult
> **Author**: Claude
> **Date**: 2026-03-20
> **Status**: Draft
> **Plan Reference**: `docs/01-plan/features/missing-calculators.plan.md`

---

## 1. FR-01: ordinary_wage Registry 노출 (구현 순서 1번)

### 1.1 변경 파일

| 파일 | 변경 유형 |
|------|----------|
| `wage_calculator/facade/registry.py` | 수정 — CALC_TYPES, _STANDARD_CALCS, CALC_TYPE_MAP |
| `wage_calculator/facade/helpers.py` | 수정 — `_pop_ordinary_wage()` 추가 |

### 1.2 상세 설계

#### 1.2.1 registry.py — CALC_TYPES에 추가

```python
# 기존 CALC_TYPES 딕셔너리 내에 추가
"ordinary_wage":       "통상임금 산출",
```

#### 1.2.2 registry.py — CALC_TYPE_MAP 매핑 변경

```python
# 기존: "통상임금": ["minimum_wage"]
# 변경:
"통상임금":    ["ordinary_wage"],
"통상시급":    ["ordinary_wage"],
```

#### 1.2.3 registry.py — _STANDARD_CALCS에 디스패처 등록

`_STANDARD_CALCS` 리스트의 **맨 앞**에 추가한다. ordinary_wage는 다른 모든 계산기의 기반이므로 이미 내부에서 먼저 실행되지만, 독립 호출 시에도 결과를 반환해야 한다.

```python
# _STANDARD_CALCS 맨 앞에 추가 (기존 항목 이전)
("ordinary_wage",  calc_ordinary_wage_standalone, "통상임금", _pop_ordinary_wage, None),
```

**주의**: 기존 `calc_ordinary_wage()`는 `OrdinaryWageResult`를 반환하는데, `_STANDARD_CALCS`의 함수는 `(inp, ow) -> BaseCalculatorResult` 시그니처가 필요하다. 래퍼 함수를 만든다.

#### 1.2.4 registry.py — 래퍼 함수

```python
from ..calculators.ordinary_wage import calc_ordinary_wage as _calc_ow_raw, OrdinaryWageResult
from ..base import BaseCalculatorResult

def calc_ordinary_wage_standalone(inp, ow: OrdinaryWageResult) -> BaseCalculatorResult:
    """통상임금을 독립 계산기로 노출하는 래퍼.

    ow는 이미 facade에서 계산된 OrdinaryWageResult이므로
    이를 BaseCalculatorResult 형태로 변환만 한다.
    """
    breakdown = {
        "통상시급": f"{ow.hourly_ordinary_wage:,.0f}원",
        "1일 통상임금": f"{ow.daily_ordinary_wage:,.0f}원",
        "월 통상임금": f"{ow.monthly_ordinary_wage:,.0f}원",
        "월 기준시간": f"{ow.monthly_base_hours}시간 ({ow.base_hours_detail})",
    }
    if ow.included_items:
        breakdown["포함 항목"] = ", ".join(ow.included_items)
    if ow.excluded_items:
        breakdown["제외 항목"] = ", ".join(ow.excluded_items)

    return BaseCalculatorResult(
        breakdown=breakdown,
        formulas=[ow.formula],
        warnings=[],
        legal_basis=["대법원 2013다4174 (정기성·일률성)", "대법원 2023다302838 (고정성 요건 폐기)"],
    )
```

#### 1.2.5 helpers.py — _pop_ordinary_wage()

```python
def _pop_ordinary_wage(r, result):
    """result.summary에 통상시급·월 통상임금 추가. 반환: 0 (monthly_total에 미반영)."""
    result.summary["통상시급"] = f"{r.breakdown.get('통상시급', '계산 불가')}"
    result.summary["월 통상임금"] = f"{r.breakdown.get('월 통상임금', '계산 불가')}"
    return 0
```

---

## 2. FR-02: CALC_TYPE_MAP 매핑 보강 (구현 순서 1번 동시)

### 2.1 변경 파일

| 파일 | 변경 유형 |
|------|----------|
| `wage_calculator/facade/registry.py` | 수정 — CALC_TYPE_MAP에 신규 키 추가 |

### 2.2 추가할 매핑

Q&A 분석에서 미매핑으로 발견된 유형들. **기존 매핑은 변경하지 않고 추가만 한다.**

```python
# CALC_TYPE_MAP에 추가할 키들
"임금":           ["minimum_wage", "overtime"],
"임금 계산":       ["minimum_wage", "overtime"],
"임금계산 검증":    ["minimum_wage"],
"공휴일수당":       ["public_holiday"],
"시급환산":         ["ordinary_wage"],
"임금체불액":       ["wage_arrears"],
"미지급 임금 계산":  ["wage_arrears"],
"부당임금삭감액":    ["wage_arrears"],
"중도입사 급여":     ["prorated"],
"일할계산급여":      ["prorated"],
"소정근로시간":      ["working_hours"],
"근로시간":          ["working_hours"],
"근로시간 계산":     ["working_hours"],
"근로시간계산":      ["working_hours"],
"근로시간 산정":     ["working_hours"],
"근로시간산정":      ["working_hours"],
"근로시간산출":      ["working_hours"],
"월근로시간":        ["working_hours"],
"연차발생":          ["annual_leave"],
"연차 발생일수 계산": ["annual_leave"],
"연말정산":          ["insurance"],
"휴일근무수당":      ["overtime", "minimum_wage"],
```

---

## 3. FR-05: resolve_calc_type 키워드 폴백 보강 (구현 순서 2번)

### 3.1 변경 파일

| 파일 | 변경 유형 |
|------|----------|
| `wage_calculator/facade/registry.py` | 수정 — `_keyword_map` 리스트에 항목 추가 |

### 3.2 추가할 키워드

```python
# _keyword_map에 추가 (기존 항목 뒤에)
(["근로시간", "소정근로", "월근로"],  ["working_hours"]),
(["통상임금", "통상시급"],           ["ordinary_wage"]),
(["공휴일"],                        ["public_holiday"]),
(["일할", "중도입사"],               ["prorated"]),
(["연차발생", "발생일수"],            ["annual_leave"]),
```

---

## 4. FR-03: 근로시간 계산기 (구현 순서 3번)

### 4.1 변경 파일

| 파일 | 변경 유형 |
|------|----------|
| `wage_calculator/calculators/working_hours.py` | **신규** — 소정근로시간 계산 모듈 |
| `wage_calculator/facade/registry.py` | 수정 — import, CALC_TYPES, _STANDARD_CALCS |
| `wage_calculator/facade/helpers.py` | 수정 — `_pop_working_hours()` |

### 4.2 working_hours.py 상세 설계

```python
"""소정근로시간 계산기

주·월·연 소정근로시간 산출 + 시급↔월급 환산.

Q&A 수요: 29건 (근로시간, 근로시간계산, 소정근로시간, 월근로시간 등)

핵심 공식:
- 주 소정근로시간 = 1일 소정근로시간 × 주 근무일수
- 월 소정근로시간 = (주 소정근로시간 + 유급주휴시간) × 365 / 12 / 7
  → 8h × 5일 + 8h(주휴) = 48h → 48 × 365/12/7 ≈ 208.57 → 약 209시간
- 연 소정근로시간 = 주 소정근로시간 × 52주
"""

from dataclasses import dataclass

from ..base import BaseCalculatorResult
from ..models import WageInput
from ..constants import MONTHLY_STANDARD_HOURS
from .ordinary_wage import OrdinaryWageResult


@dataclass
class WorkingHoursResult(BaseCalculatorResult):
    weekly_hours: float = 0.0          # 주 소정근로시간
    weekly_paid_hours: float = 0.0     # 주 유급시간 (주휴 포함)
    monthly_hours: float = 0.0         # 월 소정근로시간
    annual_hours: float = 0.0          # 연 소정근로시간
    hourly_wage: float = 0.0           # 시급 (환산)
    monthly_wage: float = 0.0          # 월급 (환산)


def calc_working_hours(inp: WageInput, ow: OrdinaryWageResult) -> WorkingHoursResult:
    """소정근로시간 계산 + 시급↔월급 환산"""
    daily = inp.schedule.daily_work_hours      # 기본 8.0
    weekly_days = inp.schedule.weekly_work_days  # 기본 5.0
    warnings = []
    formulas = []
    legal = ["근로기준법 제2조 제1항 제8호 (소정근로시간)"]

    # ── 주 소정근로시간 ──
    weekly_hours = daily * weekly_days

    # ── 유급주휴시간 ──
    # 주 15시간 이상 근무 시 주휴일 1일 부여 (근기법 제55조)
    if weekly_hours >= 15:
        paid_holiday_hours = daily  # 주휴시간 = 1일 소정근로시간
        legal.append("근로기준법 제55조 (유급주휴일)")
    else:
        paid_holiday_hours = 0
        warnings.append("주 소정근로시간 15시간 미만: 주휴일 미발생")

    weekly_paid = weekly_hours + paid_holiday_hours

    # ── 월 소정근로시간 ──
    # (주 소정 + 주휴) × 365/12/7
    monthly_hours = round(weekly_paid * (365 / 12 / 7), 2)
    formulas.append(
        f"월 소정근로시간 = ({weekly_hours} + {paid_holiday_hours}) × 365/12/7 "
        f"= {monthly_hours:.2f}시간"
    )

    # ── 연 소정근로시간 ──
    annual_hours = round(weekly_hours * 52, 1)

    # ── 시급 ↔ 월급 환산 ──
    hourly = ow.hourly_ordinary_wage
    monthly_from_hourly = round(hourly * monthly_hours) if hourly else 0

    breakdown = {
        "1일 소정근로시간": f"{daily}시간",
        "주 소정근무일수": f"{weekly_days}일",
        "주 소정근로시간": f"{weekly_hours}시간",
        "유급주휴시간": f"{paid_holiday_hours}시간",
        "주 유급시간 합계": f"{weekly_paid}시간",
        "월 소정근로시간": f"{monthly_hours}시간",
        "연 소정근로시간": f"{annual_hours}시간",
    }

    if hourly:
        breakdown["시급"] = f"{hourly:,.0f}원"
        breakdown["월급 환산"] = f"{monthly_from_hourly:,.0f}원 (시급 × 월 소정근로시간)"
        formulas.append(f"월급 환산 = {hourly:,.0f} × {monthly_hours} = {monthly_from_hourly:,.0f}원")

    return WorkingHoursResult(
        weekly_hours=weekly_hours,
        weekly_paid_hours=weekly_paid,
        monthly_hours=monthly_hours,
        annual_hours=annual_hours,
        hourly_wage=hourly or 0,
        monthly_wage=monthly_from_hourly,
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )
```

### 4.3 helpers.py — _pop_working_hours()

```python
def _pop_working_hours(r, result):
    """result.summary에 월 소정근로시간·시급·월급 환산 추가. 반환: 0."""
    result.summary["월 소정근로시간"] = f"{r.monthly_hours}시간"
    if r.hourly_wage:
        result.summary["시급"] = f"{r.hourly_wage:,.0f}원"
    if r.monthly_wage:
        result.summary["월급 환산"] = f"{r.monthly_wage:,.0f}원"
    return 0
```

### 4.4 registry.py — 등록

```python
# import 추가
from ..calculators.working_hours import calc_working_hours

# CALC_TYPES에 추가
"working_hours":       "소정근로시간 산출",

# _STANDARD_CALCS에 추가 (weekly_hours_check 근처)
("working_hours",  calc_working_hours,  "소정근로시간",  _pop_working_hours, None),
```

---

## 5. FR-04: 연차 발생일수 계산 기능 (구현 순서 4번)

### 5.1 변경 파일

| 파일 | 변경 유형 |
|------|----------|
| `wage_calculator/calculators/annual_leave.py` | 수정 — `calc_annual_leave` 내 연차발생일수 전용 출력 보강 |

### 5.2 설계 방향

기존 `calc_annual_leave()`는 이미 `_calc_accrued_days()`로 법정 연차 발생일수를 산출한다. 별도 모듈을 만들지 않고, **기존 annual_leave 계산기에서 "연차발생"이 타겟일 때 발생일수 중심으로 출력을 구성**한다.

변경 사항:
- `AnnualLeaveResult`에 이미 `accrued_days`, `schedule` 필드가 있어 별도 추가 불필요
- `CALC_TYPE_MAP`에 `"연차발생" → ["annual_leave"]` 추가 (FR-02에서 처리)
- `_pop_annual_leave()`에서 `accrued_days`도 summary에 추가

```python
# helpers.py — _pop_annual_leave 수정
def _pop_annual_leave(r, result):
    """result.summary에 연차 발생일수·미사용 연차수당 추가."""
    result.summary["법정 연차 발생일수"] = f"{r.accrued_days}일"  # ← 추가
    result.summary["미사용 연차일수"] = f"{r.remaining_days}일"
    result.summary["미사용 연차수당"] = f"{r.annual_leave_pay:,.0f}원"
    return 0
```

---

## 6. 구현 순서 및 의존성

```
Phase 1: FR-01 + FR-02 (registry 노출 + 매핑 보강) — 동시 구현
    ↓
Phase 2: FR-05 (키워드 폴백 보강)
    ↓
Phase 3: FR-03 (working_hours 신규 모듈)
    ↓
Phase 4: FR-04 (annual_leave 출력 보강)
    ↓
Phase 5: 배치 테스트 검증 (calculator_batch_test.py 102건)
```

---

## 7. 변경 영향도 요약

| 파일 | 변경 유형 | 예상 줄 수 | FR |
|------|----------|:----------:|-----|
| `wage_calculator/facade/registry.py` | 수정 | +50줄 | FR-01, FR-02, FR-03, FR-05 |
| `wage_calculator/facade/helpers.py` | 수정 | +20줄 | FR-01, FR-03, FR-04 |
| `wage_calculator/calculators/working_hours.py` | **신규** | ~90줄 | FR-03 |

**총계**: 수정 2개 + 신규 1개. ~160줄.

---

## 8. 테스트 체크리스트

| 시나리오 | 기대 결과 |
|---------|----------|
| "통상임금 계산해줘, 월급 300만원" | ordinary_wage 계산: 통상시급, 월 통상임금 표시 |
| "주 5일 8시간 근무, 월 소정근로시간?" | working_hours: 209시간 |
| "주 3일 6시간 근무, 시급 1만원 월급?" | working_hours: 주 18시간 + 주휴 6h = 24h × 365/12/7 ≈ 104.3h → 월급 약 104만원 |
| "3년 근속 연차 며칠?" | annual_leave: 발생 15일 |
| "7년 근속 연차?" | annual_leave: 발생 17일 (15 + 2) |
| 기존 배치 테스트 102건 | 전량 통과 (결과값 변경 0건) |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-20 | Initial design — 5 FRs detailed | Claude |
