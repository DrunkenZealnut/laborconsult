# weekly-dismissal-shutdown-review Design Document

> **Feature**: 주휴수당 / 해고예고수당 기존 리뷰 + 휴업수당 신규 구현
> **Plan Reference**: [weekly-dismissal-shutdown-review.plan.md](../../01-plan/features/weekly-dismissal-shutdown-review.plan.md)
> **Author**: Architect
> **Created**: 2026-03-08
> **Level**: Dynamic

---

## 1. Architecture Overview

기존 wage_calculator facade 패턴 위에 3개 계산기를 보완/추가한다.

```
WageCalculator.calculate(inp, targets)
  └─ calc_ordinary_wage(inp)            # 기반
  └─ _STANDARD_CALCS dispatcher
       ├─ calc_weekly_holiday(inp, ow)   # P2 보완: warning/breakdown
       ├─ calc_dismissal(inp, ow)        # P1 보완: daily_pay 수정 + 면제사유
       └─ calc_shutdown_allowance(inp, ow)  # P0 신규
```

### 1.1 Dependency Flow

```
shutdown_allowance.py
  ├── imports: OrdinaryWageResult (통상시급)
  ├── imports: calc_average_wage (평균임금)
  ├── imports: SHUTDOWN_RATE from constants
  └── logic: max(avg_wage × 70%, ordinary_daily) → 하한 비교
```

---

## 2. Phase 1: 휴업수당 신규 구현 (P0)

### 2.1 constants.py 추가

```python
# ── 휴업수당 (근로기준법 제46조) ─────────────────────────────────────────────
SHUTDOWN_RATE = 0.70   # 평균임금의 70%
```

**위치**: `DISMISSAL_NOTICE_DAYS = 30` 다음 줄 (해고예고 섹션 아래)

### 2.2 models.py 필드 추가

WageInput 데이터클래스의 `# ── 산재보상금 계산용` 섹션 **앞에** 추가:

```python
    # ── 휴업수당 계산용 (근기법 제46조) ──────────────────────────────────────────
    shutdown_days: int = 0                         # 총 휴업일수
    shutdown_hours_per_day: Optional[float] = None # 부분 휴업: 1일 미근로 시간 (None=전일 휴업)
    is_employer_fault: bool = True                 # 사용자 귀책사유 (False=불가항력→미발생)
    shutdown_start_date: Optional[str] = None      # 휴업 시작일 (평균임금 산정 기준)
```

해고예고 섹션에 면제사유용 필드 추가:

```python
    # ── 해고예고 계산용 ──────────────────────────────────────────────────────
    notice_days_given: int = 0             # 실제 해고예고일수
    dismissal_date: Optional[str] = None   # 해고 통보일
    tenure_months: Optional[int] = None    # 계속근로기간 (개월, None=미입력)
    is_seasonal_worker: bool = False       # 계절적 사업 4개월 이내 근로자
    is_force_majeure: bool = False         # 천재지변·근로자 귀책사유 해당
```

### 2.3 shutdown_allowance.py 신규 생성

**파일**: `wage_calculator/calculators/shutdown_allowance.py`

```python
"""
휴업수당 계산기 (근로기준법 제46조)

핵심 규칙:
- 사용자(사업주) 귀책사유 휴업: 평균임금의 70% 이상 지급
- 평균임금 70%가 통상임금 초과 → 통상임금 지급
- 부분 휴업: 미근로 시간에 대해서만 비례 지급
- 불가항력(천재지변 등) → 미발생
- 5인 미만 사업장에도 적용
"""

from dataclasses import dataclass

from ..base import BaseCalculatorResult
from ..constants import SHUTDOWN_RATE
from ..models import WageInput
from .ordinary_wage import OrdinaryWageResult
```

#### 2.3.1 ShutdownAllowanceResult

```python
@dataclass
class ShutdownAllowanceResult(BaseCalculatorResult):
    shutdown_allowance: float = 0.0            # 휴업수당 총액
    daily_shutdown_allowance: float = 0.0      # 1일 휴업수당
    avg_wage_70_pct: float = 0.0               # 평균임금 70%
    daily_ordinary_wage: float = 0.0           # 1일 통상임금
    is_ordinary_wage_applied: bool = False     # 통상임금 적용 여부
    is_partial_shutdown: bool = False          # 부분 휴업 여부
    shutdown_days: int = 0                     # 휴업일수
    partial_ratio: float = 1.0                 # 부분 휴업 비율 (미근로/소정)
```

#### 2.3.2 calc_shutdown_allowance() 핵심 로직

```python
def calc_shutdown_allowance(inp: WageInput, ow: OrdinaryWageResult) -> ShutdownAllowanceResult:
```

**입력 검증**:
1. `inp.shutdown_days <= 0` → 0원 반환 + warning
2. `inp.is_employer_fault == False` → 0원 반환 + "불가항력 휴업 — 휴업수당 미발생"

**평균임금 산정**:
- `inp.last_3m_wages` 제공 시: `sum(last_3m_wages) / (last_3m_days or 92)`
- 미제공 시: `(inp.monthly_wage or hourly × daily_hours × WEEKS_PER_MONTH × daily_work_days/weekly_work_days) × 3 / 92`
- 기존 `calc_average_wage()` 호출 **하지 않음** — 직접 평균임금 산정 (average_wage.py는 WageInput 전체를 받는 calculator인데 shutdown은 독자적으로 3개월 평균만 필요)

**핵심 계산**:
```python
avg_daily_wage = total_3m_wages / total_3m_days
avg_70 = avg_daily_wage * SHUTDOWN_RATE         # 평균임금 70%
ordinary_daily = ow.hourly_ordinary_wage * inp.schedule.daily_work_hours

# 근기법 제46조 제2항: 70%가 통상임금 초과 시 통상임금 적용
if avg_70 > ordinary_daily:
    daily_allowance = ordinary_daily
    is_ordinary_applied = True
else:
    daily_allowance = avg_70
    is_ordinary_applied = False
```

**부분 휴업 처리**:
```python
if inp.shutdown_hours_per_day is not None:
    daily_hours = inp.schedule.daily_work_hours
    partial_ratio = inp.shutdown_hours_per_day / daily_hours
    daily_allowance = daily_allowance * partial_ratio
    is_partial = True
```

**총액**: `shutdown_allowance = daily_allowance × shutdown_days`

**breakdown 필드**:
```python
breakdown = {
    "1일 평균임금": f"{avg_daily_wage:,.0f}원",
    "평균임금 70%": f"{avg_70:,.0f}원",
    "1일 통상임금": f"{ordinary_daily:,.0f}원",
    "적용 기준": "통상임금" if is_ordinary_applied else "평균임금 70%",
    "1일 휴업수당": f"{daily_allowance:,.0f}원",
    "휴업일수": f"{shutdown_days}일",
    "휴업수당 총액": f"{total:,.0f}원",
}
# 부분 휴업 시 추가:
#   "부분 휴업": f"1일 {shutdown_hours_per_day}h / {daily_hours}h = {partial_ratio:.1%}"
```

**legal_basis**:
```python
legal = [
    "근로기준법 제46조 (휴업수당)",
    "근로기준법 제46조 제2항 (통상임금 적용 기준)",
]
```

### 2.4 facade.py 연결

#### 2.4.1 import 추가

`from .calculators.severance import calc_severance` 뒤에 (알파벳순):

```python
from .calculators.shutdown_allowance import calc_shutdown_allowance
```

#### 2.4.2 _pop_shutdown_allowance 함수

`_pop_severance` 다음에:

```python
def _pop_shutdown_allowance(r, result):
    """result.summary에 휴업수당 총액·적용기준·일수 추가. 반환: 0."""
    result.summary["휴업수당"] = f"{r.shutdown_allowance:,.0f}원"
    result.summary["적용 기준"] = "통상임금" if r.is_ordinary_wage_applied else "평균임금 70%"
    if r.is_partial_shutdown:
        result.summary["부분 휴업"] = f"비율 {r.partial_ratio:.0%}"
    return 0
```

#### 2.4.3 _STANDARD_CALCS 등록

`("severance", ...)` 항목 뒤에:

```python
("shutdown_allowance", calc_shutdown_allowance, "휴업수당", _pop_shutdown_allowance,
 lambda inp: inp.shutdown_days > 0),
```

#### 2.4.4 CALC_TYPE_MAP 추가

```python
"휴업수당":   ["shutdown_allowance"],
```

#### 2.4.5 TARGET_LABEL_MAP 추가

```python
"shutdown_allowance": "휴업수당(근기법 제46조)",
```

#### 2.4.6 _auto_detect_targets 추가

```python
if inp.shutdown_days > 0:
    targets.append("shutdown_allowance")
```

---

## 3. Phase 2: 해고예고수당 보완 (P1)

### 3.1 dismissal.py 수정

#### 3.1.1 1일 통상임금 수정 (L32)

**Before**:
```python
daily_pay = hourly * 8    # 1일 통상임금 (8시간)
```

**After**:
```python
daily_hours = inp.schedule.daily_work_hours
daily_pay = hourly * daily_hours  # 1일 통상임금 (소정근로시간)
```

**breakdown** 수정 (L88):
```python
"1일 통상임금": f"{daily_pay:,.0f}원 ({hourly:,.0f}원 × {daily_hours}h)",
```

#### 3.1.2 면제사유 추가 (L42~53 사이)

기존 일용직·수습 면제 체크 **앞에** 추가:

```python
    # 계속근로기간 3개월 미만 (근기법 제26조 단서 2호)
    if inp.tenure_months is not None and inp.tenure_months < 3:
        warnings.append(f"계속근로기간 {inp.tenure_months}개월 (<3개월): 해고예고 의무 면제")
        legal.append("근로기준법 제26조 단서 2호 (3개월 미만)")
        is_exempt = True
        exempt_reason = f"계속근로기간 {inp.tenure_months}개월 미만 — 면제"

    # 계절적 사업 4개월 이내 (근기법 제26조 단서 3호)
    if inp.is_seasonal_worker:
        warnings.append("계절적 사업 4개월 이내 근로자: 해고예고 의무 면제")
        legal.append("근로기준법 제26조 단서 3호 (계절적 사업)")
        is_exempt = True
        exempt_reason = "계절적 사업 4개월 이내 — 면제"

    # 천재지변·근로자 귀책사유 (근기법 제26조 단서 4호)
    if inp.is_force_majeure:
        warnings.append("천재지변 또는 근로자 귀책사유: 해고예고 의무 면제")
        legal.append("근로기준법 제26조 단서 4호 (천재지변·귀책사유)")
        is_exempt = True
        exempt_reason = "천재지변/근로자 귀책 — 면제"
```

**면제 검증 순서** (우선순위):
1. 3개월 미만 근속
2. 계절적 사업
3. 천재지변·귀책
4. 일용직 (기존)
5. 수습 3개월 이내 (기존)

### 3.2 models.py 추가 필드

(2.2절에 통합, 해고예고 섹션에 3개 필드 추가)

---

## 4. Phase 3: 주휴수당 안내 보강 (P2)

### 4.1 weekly_holiday.py 수정

#### 4.1.1 시급제 warning 추가

`calc_weekly_holiday()` 함수 말미, `return` 직전에:

```python
    # 시급제 안내
    if inp.wage_type == WageType.HOURLY:
        warnings.append(
            "시급제: 제시된 시급에 주휴수당이 포함되어 있는지 확인 필요 "
            "(포함 시급 = 기본시급 × (1 + 주휴시간/주소정근로시간))"
        )
```

#### 4.1.2 월급제 breakdown 추가

`breakdown` 딕셔너리에:

```python
    if inp.wage_type == WageType.MONTHLY:
        breakdown["월급 주휴 포함 여부"] = "월급에 주휴수당 포함 (별도 지급 불필요)"
```

#### 4.1.3 주 소정근로일 breakdown 추가

```python
    breakdown["주 소정근로일"] = f"{s.weekly_work_days:.0f}일"
```

#### 4.1.4 import 추가

기존 imports에:
```python
from ..models import WageInput, WageType  # WageType 추가
```

현재: `from ..models import WageInput` → `from ..models import WageInput, WageType`

---

## 5. Implementation Order (8 Steps)

| Step | File | Action | Dependencies |
|:----:|------|--------|:------------:|
| 1 | `constants.py` | `SHUTDOWN_RATE = 0.70` 추가 | - |
| 2 | `models.py` | 휴업 4필드 + 해고 3필드 추가 | - |
| 3 | `calculators/shutdown_allowance.py` | 신규 생성 | Step 1, 2 |
| 4 | `facade.py` | import + `_pop_shutdown_allowance` + `_STANDARD_CALCS` + `CALC_TYPE_MAP` + `_auto_detect_targets` | Step 3 |
| 5 | `calculators/dismissal.py` | `daily_pay` 수정 + 면제사유 추가 | Step 2 |
| 6 | `calculators/weekly_holiday.py` | warning + breakdown 보강 | - |
| 7 | `wage_calculator_cli.py` | 테스트 7건 추가 | Step 3~6 |
| 8 | 전체 테스트 실행 | `python3 wage_calculator_cli.py` — 기존 85 + 신규 7 = 92건 통과 | Step 7 |

---

## 6. Test Cases

### 6.1 휴업수당 테스트 (3건)

**TC-86: 전일 휴업 (월급 300만원)**
```python
{
    "id": 86,
    "desc": "휴업수당 — 전일 휴업 30일 (사용자 귀책)",
    "input": WageInput(
        wage_type=WageType.MONTHLY,
        monthly_wage=3000000,
        business_size=BusinessSize.OVER_5,
        reference_year=2025,
        shutdown_days=30,
        is_employer_fault=True,
    ),
    "targets": ["shutdown_allowance"],
}
# 예상: 평균임금 = 3,000,000 × 3 / 92 ≈ 97,826원/일
#        70% ≈ 68,478원
#        통상임금 = 3,000,000 / 209 ≈ 14,354원/시 × 8h = 114,833원
#        68,478 < 114,833 → 평균임금 70% 적용
#        총액 ≈ 68,478 × 30 = 2,054,348원
```

**TC-87: 부분 휴업 (1일 4h 미근로)**
```python
{
    "id": 87,
    "desc": "휴업수당 — 부분 휴업 (1일 8h 중 4h 미근로, 20일)",
    "input": WageInput(
        wage_type=WageType.MONTHLY,
        monthly_wage=2500000,
        business_size=BusinessSize.OVER_5,
        reference_year=2025,
        shutdown_days=20,
        shutdown_hours_per_day=4.0,
        is_employer_fault=True,
    ),
    "targets": ["shutdown_allowance"],
}
# 예상: 평균임금 70% × (4h/8h) = 50% 적용
```

**TC-88: 불가항력 휴업 (미발생)**
```python
{
    "id": 88,
    "desc": "휴업수당 — 불가항력 (천재지변, 미발생)",
    "input": WageInput(
        wage_type=WageType.MONTHLY,
        monthly_wage=3000000,
        business_size=BusinessSize.OVER_5,
        reference_year=2025,
        shutdown_days=10,
        is_employer_fault=False,
    ),
    "targets": ["shutdown_allowance"],
}
# 예상: 0원 (불가항력)
```

### 6.2 해고예고수당 테스트 (2건)

**TC-89: 파트타임 해고예고 (6h 근무)**
```python
{
    "id": 89,
    "desc": "해고예고수당 — 파트타임 6h 근무자 (기존 8h 고정 오류 수정 검증)",
    "input": WageInput(
        wage_type=WageType.HOURLY,
        hourly_wage=10030,
        business_size=BusinessSize.OVER_5,
        reference_year=2025,
        notice_days_given=0,
        schedule=WorkSchedule(
            daily_work_hours=6,
            weekly_work_days=5,
        ),
    ),
    "targets": ["dismissal"],
}
# 예상: daily_pay = 10,030 × 6h = 60,180원
#        해고예고수당 = 60,180 × 30 = 1,805,400원
# (기존 8h 기준이면 80,240 × 30 = 2,407,200 — 오류)
```

**TC-90: 3개월 미만 근속 면제**
```python
{
    "id": 90,
    "desc": "해고예고수당 — 3개월 미만 근속 면제",
    "input": WageInput(
        wage_type=WageType.MONTHLY,
        monthly_wage=2500000,
        business_size=BusinessSize.OVER_5,
        reference_year=2025,
        notice_days_given=0,
        tenure_months=2,
    ),
    "targets": ["dismissal"],
}
# 예상: 면제 (is_exempt=True, dismissal_pay=0)
```

### 6.3 주휴수당 테스트 (2건)

**TC-91: 시급제 주휴 안내**
```python
{
    "id": 91,
    "desc": "주휴수당 — 시급제 주휴 포함 여부 안내 warning 확인",
    "input": WageInput(
        wage_type=WageType.HOURLY,
        hourly_wage=10030,
        business_size=BusinessSize.OVER_5,
        reference_year=2025,
        schedule=WorkSchedule(
            daily_work_hours=8,
            weekly_work_days=5,
        ),
    ),
    "targets": ["weekly_holiday"],
}
# 검증: warnings에 "시급제: 제시된 시급에 주휴수당이 포함" 포함
```

**TC-92: 월급제 주휴 안내**
```python
{
    "id": 92,
    "desc": "주휴수당 — 월급제 주휴 포함 안내 breakdown 확인",
    "input": WageInput(
        wage_type=WageType.MONTHLY,
        monthly_wage=3000000,
        business_size=BusinessSize.OVER_5,
        reference_year=2025,
    ),
    "targets": ["weekly_holiday"],
}
# 검증: breakdown에 "월급 주휴 포함 여부" 키 존재
#        breakdown에 "주 소정근로일" 키 존재
```

---

## 7. Verification Criteria

| # | Criterion | Expected |
|---|-----------|----------|
| 1 | `python3 wage_calculator_cli.py` | 92 tests pass (기존 85 + 신규 7) |
| 2 | `python3 -c "from wage_calculator import WageCalculator"` | No error |
| 3 | TC-86 전일 휴업: `shutdown_allowance > 0` | True |
| 4 | TC-87 부분 휴업: `is_partial_shutdown` | True |
| 5 | TC-88 불가항력: `shutdown_allowance == 0` | True |
| 6 | TC-89 파트타임 해고: `dismissal_pay == 10030 × 6 × 30` | 1,805,400원 |
| 7 | TC-90 3개월 미만: `is_exempt == True` | True |
| 8 | TC-91 시급 warning: "시급제" in warnings | True |
| 9 | TC-92 월급 breakdown: "월급 주휴 포함" in breakdown | True |
| 10 | shutdown_allowance.py imports: PEP 8 (stdlib → blank → local) | Yes |
| 11 | facade.py imports: 알파벳순 + shutdown_allowance 추가 | Yes |
| 12 | facade.py `_pop_shutdown_allowance` docstring 존재 | Yes |

---

## 8. File Change Summary

| # | File | Change | Lines |
|---|------|--------|:-----:|
| 1 | `wage_calculator/constants.py` | `SHUTDOWN_RATE = 0.70` 추가 | +2 |
| 2 | `wage_calculator/models.py` | 휴업 4필드 + 해고 3필드 추가 | +10 |
| 3 | `wage_calculator/calculators/shutdown_allowance.py` | **신규** | ~130 |
| 4 | `wage_calculator/calculators/dismissal.py` | daily_pay 수정 + 면제사유 3건 추가 | +30 |
| 5 | `wage_calculator/calculators/weekly_holiday.py` | warning + breakdown 3건 추가 | +12 |
| 6 | `wage_calculator/facade.py` | import + _pop + _STANDARD_CALCS + CALC_TYPE_MAP + auto_detect | +15 |
| 7 | `wage_calculator_cli.py` | 테스트 7건 추가 | ~120 |

**총 변경량**: 신규 1파일(~130줄) + 기존 6파일(~190줄 수정) = ~320줄

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-08 | Initial design | architect |
