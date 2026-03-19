# average-wage-calculator Design Document

> **Summary**: 평균임금 독립 계산 모듈 신설 — nodong.kr AverageWageCal 참조
>
> **Project**: laborconsult (노동법 임금계산기)
> **Author**: Claude PDCA
> **Date**: 2026-03-08
> **Status**: Draft
> **Plan**: [average-wage-calculator.plan.md](../../01-plan/features/average-wage-calculator.plan.md)

---

## 1. Design Overview

### 1.1 Purpose

`severance.py` 내부 private 함수(`_calc_avg_daily_3m`, `_calc_avg_daily_1y`)에 종속된 평균임금 계산 로직을
독립 모듈 `average_wage.py`로 분리하고, facade에서 직접 호출 가능하도록 한다.

### 1.2 Approach

**최소 변경 원칙:**
1. 신규 `average_wage.py` 모듈 생성 (독립 계산기)
2. `severance.py` 리팩터링: 내부 로직 → `average_wage.py` 호출로 대체
3. `facade.py`: CALC_TYPES/CALC_TYPE_MAP/디스패처 추가
4. 기존 59개 테스트 결과 불변 보장

---

## 2. Data Model

### 2.1 AverageWageResult (신규)

**파일**: `wage_calculator/calculators/average_wage.py`

```python
@dataclass
class AverageWageResult(BaseCalculatorResult):
    avg_daily_wage: float = 0.0        # 적용 1일 평균임금 (원)
    avg_daily_3m: float = 0.0          # 3개월 기준 평균임금 (원/일)
    avg_daily_ordinary: float = 0.0    # 통상임금 환산 일급 (원/일)
    used_basis: str = ""               # 적용 기준 ("3개월" / "통상임금")
    period_days: int = 0               # 산정기간 총 일수
    wage_total: float = 0.0            # 3개월 임금총액
    bonus_addition: float = 0.0        # 상여금 가산액 (연간×3/12)
    leave_addition: float = 0.0        # 연차수당 가산액 (연간×3/12)
    grand_total: float = 0.0           # 임금총액 + 상여금 + 연차수당
```

### 2.2 WageInput 기존 필드 활용 (변경 없음)

| 필드 | 타입 | 용도 |
|------|------|------|
| `last_3m_wages` | `Optional[list]` | 최근 3개월 각 지급액. `list[float]` 또는 `list[dict]` 모두 지원 |
| `last_3m_days` | `Optional[int]` | 3개월 총일수 (None이면 자동 계산) |
| `annual_bonus_total` | `float` | 연간 상여금 |
| `unused_annual_leave_pay` | `float` | 최종 연차수당 |
| `end_date` | `Optional[str]` | 산정사유발생일 (퇴직일 등) |

**`last_3m_wages` 확장 지원 (하위 호환):**
```python
# 기존 형태 (float list) — 그대로 지원
last_3m_wages = [3_000_000, 3_000_000, 3_000_000]

# 신규 형태 (dict list) — nodong.kr 월별 세분화
last_3m_wages = [
    {"base": 2_500_000, "allowance": 500_000},  # 1개월 전
    {"base": 2_500_000, "allowance": 500_000},  # 2개월 전
    {"base": 2_500_000, "allowance": 500_000},  # 3개월 전
]
```

---

## 3. Module Design

### 3.1 average_wage.py (신규 파일)

**위치**: `wage_calculator/calculators/average_wage.py`

```python
"""
평균임금 계산기 (근로기준법 제2조)

평균임금은 퇴직금·산재보상·감급·휴업수당·실업급여 등의 기반이 됩니다.
공식: 1일 평균임금 = (3개월 임금총액 + 상여금×3/12 + 연차수당×3/12) / 3개월 총일수

■ 근로기준법 시행령 제2조
  - 평균임금이 통상임금보다 낮으면 통상임금을 평균임금으로 함
"""
```

**함수 시그니처:**

```python
def calc_average_wage(inp: WageInput, ow: OrdinaryWageResult) -> AverageWageResult:
    """
    평균임금 산정 (독립 호출 가능)

    계산 순서:
    1. 산정기간 일수 결정 (last_3m_days 또는 end_date 기반 자동 계산)
    2. 3개월 임금총액 산출 (last_3m_wages → float/dict 모두 지원)
    3. 상여금·연차수당 가산 (×3/12)
    4. 1일 평균임금 = 총액 / 총일수
    5. 통상임금 비교 → 높은 쪽 적용
    """
```

### 3.2 핵심 로직

#### 3.2.1 산정기간 일수 자동 계산

```python
def _calc_period_days(inp: WageInput) -> int:
    """
    산정사유발생일(end_date) 기반 3개월 역산 일수 계산

    우선순위:
    1. last_3m_days 명시값 사용
    2. end_date가 있으면 calendar로 3개월 역산
    3. 기본값 AVG_WAGE_PERIOD_DAYS (92일)
    """
    if inp.last_3m_days is not None:
        return inp.last_3m_days

    end = parse_date(inp.end_date)
    if end is not None:
        # end_date로부터 3개월 전 날짜 계산
        # 예: 2026-03-08 → 2025-12-08, 일수 = (03-08) - (12-08) = 90일
        month_3_ago = _subtract_months(end, 3)
        return (end - month_3_ago).days

    return AVG_WAGE_PERIOD_DAYS
```

#### 3.2.2 임금총액 산출 (float/dict 하위 호환)

```python
def _calc_wage_total(inp: WageInput, ow: OrdinaryWageResult) -> float:
    """
    3개월 임금총액 산출

    last_3m_wages 형태:
    - list[float]: [3000000, 3000000, 3000000] → sum()
    - list[dict]:  [{"base": 2500000, "allowance": 500000}, ...] → sum(base+allowance)
    - None: monthly_wage × 3 또는 통상임금 × 3 추정
    """
    if inp.last_3m_wages:
        total = 0.0
        for item in inp.last_3m_wages:
            if isinstance(item, dict):
                total += float(item.get("base", 0)) + float(item.get("allowance", 0))
            else:
                total += float(item)
        return total

    if inp.monthly_wage:
        return inp.monthly_wage * 3

    return ow.monthly_ordinary_wage * 3
```

#### 3.2.3 통상임금 비교

```python
# 통상임금 환산 일급 (근기법 시행령 제2조)
avg_daily_ordinary = ow.daily_ordinary_wage  # ordinary_wage_review에서 추가된 필드

# 비교: 평균임금 < 통상임금이면 통상임금 적용
if avg_daily_ordinary > avg_daily_3m:
    used_basis = "통상임금"
    avg_daily_wage = avg_daily_ordinary
else:
    used_basis = "3개월"
    avg_daily_wage = avg_daily_3m
```

### 3.3 _subtract_months 헬퍼

```python
def _subtract_months(d: date, months: int) -> date:
    """날짜에서 N개월 역산 (월말 보정 포함)"""
    import calendar
    month = d.month - months
    year = d.year
    while month <= 0:
        month += 12
        year -= 1
    max_day = calendar.monthrange(year, month)[1]
    day = min(d.day, max_day)
    return date(year, month, day)
```

---

## 4. Integration Design

### 4.1 facade.py 변경

#### 4.1.1 Import 추가

```python
from .calculators.average_wage import calc_average_wage
```

#### 4.1.2 CALC_TYPES 추가

```python
CALC_TYPES = {
    ...
    "average_wage":        "평균임금",          # 신규
}
```

#### 4.1.3 CALC_TYPE_MAP 추가

```python
CALC_TYPE_MAP = {
    ...
    "평균임금":   ["average_wage"],              # 신규
}
```

#### 4.1.4 _pop_average_wage 함수

```python
def _pop_average_wage(r, result):
    result.summary["1일 평균임금"] = f"{r.avg_daily_wage:,.0f}원/일"
    result.summary["적용 기준"] = f"{r.used_basis}"
    result.summary["3개월 임금총액"] = f"{r.grand_total:,.0f}원"
    result.summary["산정기간"] = f"{r.period_days}일"
    return 0
```

#### 4.1.5 _STANDARD_CALCS 추가

```python
_STANDARD_CALCS = [
    ...
    ("average_wage",       calc_average_wage,   "평균임금",             _pop_average_wage,   None),
    ...
]
```

위치: `severance` 항목 바로 앞에 배치 (severance가 average_wage 결과를 참조할 수 있도록)

### 4.2 severance.py 리팩터링

#### 4.2.1 변경 전 (현재)

```python
# severance.py 내부
avg_daily_3m = _calc_avg_daily_3m(inp, ow)    # private 함수
avg_daily_1y = _calc_avg_daily_1y(inp, ow)    # private 함수
avg_daily_ordinary = ow.hourly_ordinary_wage * 8
```

#### 4.2.2 변경 후

```python
from .average_wage import calc_average_wage, _calc_wage_total, _calc_period_days

def calc_severance(inp: WageInput, ow: OrdinaryWageResult) -> SeveranceResult:
    # A. 3개월 평균임금 — average_wage 모듈 재사용
    avg_result = calc_average_wage(inp, ow)
    avg_daily_3m = avg_result.avg_daily_3m
    avg_daily_ordinary = avg_result.avg_daily_ordinary

    # B. 1년 평균임금 — severance 전용 (대법원 2023다302579)
    avg_daily_1y = _calc_avg_daily_1y(inp, ow)   # 이 함수는 severance.py에 유지

    # ... 나머지 로직 동일
```

**핵심 원칙:**
- `_calc_avg_daily_3m()` 삭제 → `calc_average_wage()` 호출로 대체
- `_calc_avg_daily_1y()` 유지 (severance 전용, 대법원 판결 특수 로직)
- `avg_daily_ordinary` → `avg_result.avg_daily_ordinary` 사용
- severance breakdown의 상여금/연차 가산 표시는 `avg_result` 값 활용

### 4.3 __init__.py 추가

```python
from .calculators.average_wage import AverageWageResult

__all__ = [
    ...
    "AverageWageResult",
]
```

---

## 5. Error Handling

### 5.1 입력 부재 시 Fallback

| 상황 | 처리 |
|------|------|
| `last_3m_wages` None + `monthly_wage` None | `ow.monthly_ordinary_wage × 3` 추정 + warning |
| `last_3m_days` None + `end_date` None | `AVG_WAGE_PERIOD_DAYS (92)` 기본값 |
| `last_3m_wages` 빈 리스트 `[]` | `monthly_wage × 3` fallback |
| `last_3m_wages` dict에 `base` 키 없음 | `float(item.get("base", 0))` — 0으로 처리 |
| 산정기간 0일 | `max(period_days, 1)` — 0 나눗셈 방지 |

### 5.2 Warning 메시지

| 조건 | Warning |
|------|---------|
| 임금 데이터 없이 통상임금 추정 사용 | "3개월 임금 데이터 미입력 — 통상임금 기반 추정치입니다" |
| 평균임금 < 통상임금 | "평균임금({X}원/일)이 통상임금({Y}원/일)보다 낮아 통상임금 적용 (근기법 시행령 제2조)" |

---

## 6. Test Plan

### 6.1 신규 테스트 케이스

| # | 설명 | 핵심 검증 |
|---|------|-----------|
| #60 | 기본 평균임금 산정 (3개월 float list) | `last_3m_wages=[3M,3M,3M]`, 92일 기준, avg_daily = 97,826원 |
| #61 | 평균임금 < 통상임금 비교 | 평균임금이 통상임금보다 낮을 때 통상임금 적용 + used_basis="통상임금" |
| #62 | 상여금+연차수당 가산 | `annual_bonus_total=2.4M`, `unused_annual_leave_pay=600K` → 가산 확인 |
| #63 | 산정기간 자동 계산 (end_date 기반) | `end_date="2026-03-08"` → 3개월 역산 일수 자동 산출 |
| #64 | dict 형태 월별 입력 | `last_3m_wages=[{base:2.5M, allowance:500K}, ...]` → 합산 정확 |

### 6.2 기존 테스트 불변 확인

| 범위 | 테스트 | 기대 |
|------|--------|------|
| #1~#59 | 전체 기존 테스트 | 결과 100% 동일 |
| #11 퇴직금 | severance 리팩터링 후 | avg_daily_3m 값 동일 |

---

## 7. Implementation Order

### Step 1: `average_wage.py` 신규 모듈 생성
- `AverageWageResult` dataclass
- `calc_average_wage()` 함수
- `_calc_period_days()`, `_calc_wage_total()`, `_subtract_months()` 헬퍼

### Step 2: `facade.py` 통합
- import 추가
- CALC_TYPES + CALC_TYPE_MAP 추가
- `_pop_average_wage()` 함수
- `_STANDARD_CALCS` 배열에 추가

### Step 3: `severance.py` 리팩터링
- `_calc_avg_daily_3m()` 삭제
- `calc_average_wage()` 호출로 대체
- 기존 결과 동일 검증

### Step 4: `__init__.py` export 추가

### Step 5: `wage_calculator_cli.py` 테스트 추가
- #60~#64 테스트 케이스 추가
- 기존 #1~#59 전수 통과 확인

---

## 8. Dependency Graph

```
average_wage.py
  ├── imports: BaseCalculatorResult, WageInput, OrdinaryWageResult
  ├── imports: parse_date (utils.py)
  ├── imports: AVG_WAGE_PERIOD_DAYS (constants.py)
  └── uses: calendar (stdlib)

severance.py
  ├── imports: calc_average_wage (average_wage.py)  ← 신규 의존성
  └── retains: _calc_avg_daily_1y() (severance 전용)

facade.py
  ├── imports: calc_average_wage (average_wage.py)  ← 신규 의존성
  └── _STANDARD_CALCS: average_wage 항목 추가
```

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-08 | Initial design | Claude PDCA |
