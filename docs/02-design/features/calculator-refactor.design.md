# calculator-refactor Design Document

> **Summary**: 임금계산기 공통 유틸 추출, 타입 안전성 강화, facade 분리의 상세 설계
>
> **Project**: laborconsult (노동법 임금계산기)
> **Author**: Claude Code
> **Date**: 2026-03-12
> **Status**: Draft
> **Planning Doc**: [calculator-refactor.plan.md](../../01-plan/features/calculator-refactor.plan.md)

---

## 1. Overview

### 1.1 Design Goals

1. 24개 계산기 모듈의 반복 패턴을 공통 유틸로 추출하여 중복 제거
2. `fixed_allowances: list[dict]`의 매직 스트링 접근을 타입 안전한 데이터클래스로 전환
3. 700줄 facade.py를 역할별 모듈로 분리
4. 기존 32개 테스트 케이스 100% 호환 유지

### 1.2 Design Principles

- **하위 호환성 우선**: 외부 API(`WageCalculator.calculate()`, `from_analysis()`) 시그니처 불변
- **점진적 마이그레이션**: dict 입력을 계속 수용하되 내부에서 dataclass로 변환
- **단방향 의존**: `shared.py` → 계산기 방향만 허용, 역방향 import 금지
- **최소 변경**: 기존 계산 로직과 금액 결과를 변경하지 않음

---

## 2. Architecture

### 2.1 의존성 다이어그램

```
wage_calculator/
│
├── models.py ◄──── 모든 모듈이 의존
│   └── + FixedAllowance (신규)
│
├── utils.py ◄──── 모든 모듈이 의존
│   └── + RoundingPolicy (신규)
│
├── base.py ◄──── 계산기 Result 클래스가 의존
│
├── constants.py ◄──── 계산기가 의존
│
├── calculators/
│   ├── shared.py (신규) ◄──── 계산기 모듈이 의존
│   │   ├── DateRange
│   │   ├── AllowanceClassifier
│   │   └── MultiplierContext
│   │
│   ├── ordinary_wage.py ◄──── 모든 계산기가 의존
│   ├── overtime.py
│   ├── minimum_wage.py
│   ├── severance.py
│   ├── annual_leave.py
│   └── ... (20개)
│
├── legal_hints.py (AllowanceClassifier 사용)
│
└── facade/  (기존 facade.py → 분리)
    ├── __init__.py     (WageCalculator 클래스)
    ├── registry.py     (CALC_TYPES, CALC_TYPE_MAP, _STANDARD_CALCS)
    ├── helpers.py      (_pop_* 함수)
    └── conversion.py   (_provided_info_to_input, _guess_start_date)
```

### 2.2 의존성 규칙

| From | Can Import | Cannot Import |
|------|-----------|---------------|
| `shared.py` | models, utils, constants | 개별 계산기, facade, legal_hints |
| 개별 계산기 | shared, models, utils, constants, ordinary_wage | facade, legal_hints |
| `legal_hints.py` | shared(AllowanceClassifier), models, constants, ordinary_wage | facade, 개별 계산기 |
| `facade/` | 모든 모듈 | (최상위 — 제한 없음) |
| `__init__.py` | facade | (re-export 전용) |

---

## 3. Detailed Interface Design

### 3.1 `calculators/shared.py` — 공통 유틸

#### DateRange

```python
from datetime import date
from ..utils import parse_date

class DateRange:
    """날짜 범위 및 근속 계산 유틸

    현재 중복 위치: severance.py:64-74, annual_leave.py:78-90,
                  dismissal.py, unemployment.py, weekly_holiday.py
    """
    def __init__(self, start_str: str | None, end_str: str | None = None):
        self.start: date | None = parse_date(start_str)
        self.end: date = parse_date(end_str) or date.today()

    @property
    def is_valid(self) -> bool:
        """입사일이 존재하고 start <= end"""
        return self.start is not None and self.start <= self.end

    @property
    def days(self) -> int:
        """근속 일수 (start가 None이면 0)"""
        if self.start is None:
            return 0
        return (self.end - self.start).days

    @property
    def years(self) -> float:
        """근속 연수 (365일 기준)"""
        return self.days / 365

    @property
    def months_approx(self) -> int:
        """근속 개월 수 (30.44일 기준, unemployment.py 호환)"""
        return max(0, int(self.days / 30.44))
```

**적용 대상** (8개 모듈):

| 모듈 | 현재 코드 | 변경 후 |
|------|----------|---------|
| `severance.py:64-74` | `start = parse_date(inp.start_date)` + 수동 계산 | `dr = DateRange(inp.start_date, inp.end_date)` |
| `annual_leave.py:78-90` | 동일 패턴 | `dr = DateRange(inp.start_date, inp.end_date)` |
| `dismissal.py` | 동일 패턴 | `dr = DateRange(...)` |
| `unemployment.py` | `int((end - start).days / 30.44)` | `dr.months_approx` |
| `weekly_holiday.py` | `date.fromisoformat(inp.end_date)` | `dr = DateRange(...)` |
| `average_wage.py` | `parse_date()` + 수동 | `dr = DateRange(...)` |
| `shutdown_allowance.py` | 동일 패턴 | `dr = DateRange(...)` |
| `industrial_accident.py` | 동일 패턴 | `dr = DateRange(...)` |

---

#### AllowanceClassifier

```python
class AllowanceClassifier:
    """수당 이름 기반 자동 분류

    현재 중복 위치:
    - minimum_wage.py:37-42  (_EXCLUDED_PATTERNS, _BONUS_PATTERNS, _WELFARE_PATTERNS)
    - legal_hints.py         (동일 키워드 패턴)
    - ordinary_wage.py:137   (_resolve_is_ordinary 내 condition 처리)
    """

    # 최저임금 비산입 (연장/야간/휴일 등)
    EXCLUDED_KEYWORDS: list[str] = ["연장", "야간", "휴일", "특근"]

    # 정기상여금 (산입범위 적용)
    BONUS_KEYWORDS: list[str] = ["상여금", "상여", "보너스", "격려금", "인센티브"]

    # 복리후생비 (산입범위 적용)
    WELFARE_KEYWORDS: list[str] = [
        "식대", "식비", "급식", "교통비", "교통", "차량", "통근",
        "주거", "숙박", "가족수당", "복리",
    ]

    @classmethod
    def classify_min_wage_type(cls, name: str, explicit_type: str = "") -> str:
        """최저임금 산입유형 결정

        Returns: "standard" | "regular_bonus" | "welfare" | "excluded"

        현재 minimum_wage.py:259-274의 _min_wage_type() 대체
        """
        if explicit_type in ("regular_bonus", "welfare", "excluded", "standard"):
            return explicit_type
        for kw in cls.EXCLUDED_KEYWORDS:
            if kw in name:
                return "excluded"
        for kw in cls.BONUS_KEYWORDS:
            if kw in name:
                return "regular_bonus"
        for kw in cls.WELFARE_KEYWORDS:
            if kw in name:
                return "welfare"
        return "standard"

    @classmethod
    def is_overtime_related(cls, name: str) -> bool:
        """연장/야간/휴일 관련 수당인지 판별 (legal_hints에서 사용)"""
        return any(kw in name for kw in cls.EXCLUDED_KEYWORDS)
```

**적용 대상** (3개 모듈):

| 모듈 | 현재 | 변경 후 |
|------|------|---------|
| `minimum_wage.py:37-42,259-274` | `_EXCLUDED_PATTERNS` + `_min_wage_type()` | `AllowanceClassifier.classify_min_wage_type()` |
| `legal_hints.py:56-60` | `a.get("name")` + 인라인 키워드 매칭 | `AllowanceClassifier.is_overtime_related()` |
| `ordinary_wage.py:137` | `_resolve_is_ordinary()` (condition 로직) | 변경 없음 (condition 로직은 AllowanceClassifier와 독립) |

---

#### MultiplierContext

```python
from ..models import WageInput, BusinessSize
from ..constants import OVERTIME_RATE, NIGHT_PREMIUM_RATE, HOLIDAY_RATE, HOLIDAY_OT_RATE

class MultiplierContext:
    """5인 미만 사업장 배율 처리

    현재 중복 위치:
    - overtime.py:54-60
    - comprehensive.py (동일 분기)
    - flexible_work.py (동일 분기)
    - public_holiday.py
    - dismissal.py (일부 분기)
    """

    def __init__(self, inp: WageInput):
        self.is_small: bool = inp.business_size == BusinessSize.UNDER_5

    @property
    def overtime(self) -> float:
        """연장수당 가산율 (5인 이상: 0.5, 미만: 0.0)"""
        return 0.0 if self.is_small else OVERTIME_RATE

    @property
    def night(self) -> float:
        """야간수당 가산율"""
        return 0.0 if self.is_small else NIGHT_PREMIUM_RATE

    @property
    def holiday(self) -> float:
        """휴일수당 가산율 (8h 이내)"""
        return 0.0 if self.is_small else HOLIDAY_RATE

    @property
    def holiday_ot(self) -> float:
        """휴일수당 가산율 (8h 초과)"""
        return 0.0 if self.is_small else HOLIDAY_OT_RATE

    def small_business_warning(self) -> str | None:
        """5인 미만 경고 메시지 (해당 시에만 반환)"""
        if self.is_small:
            return "5인 미만 사업장: 연장·야간·휴일 가산수당 미적용 (근로기준법 제11조)"
        return None
```

**적용 대상** (5개 모듈):

| 모듈 | 현재 | 변경 후 |
|------|------|---------|
| `overtime.py:54-60` | `is_small = inp.business_size == BusinessSize.UNDER_5` + 4줄 배율 | `mx = MultiplierContext(inp)` |
| `comprehensive.py` | 동일 패턴 | `mx = MultiplierContext(inp)` |
| `flexible_work.py` | 동일 패턴 | `mx = MultiplierContext(inp)` |
| `public_holiday.py` | 동일 패턴 | `mx = MultiplierContext(inp)` |
| `dismissal.py` | 부분 사용 (is_small만) | `mx.is_small` |

---

### 3.2 `models.py` — FixedAllowance 데이터클래스

```python
@dataclass
class FixedAllowance:
    """고정수당 항목 (기존 dict 대체)

    기존: {"name": "직책수당", "amount": 100000, "condition": "없음",
           "is_ordinary": True, "annual": False, "payment_cycle": "매월"}
    """
    name: str = "수당"
    amount: float = 0.0
    condition: str = "없음"            # AllowanceCondition.value 또는 문자열
    is_ordinary: bool | None = None    # None=자동 판정, True/False=명시
    annual: bool = False               # True이면 amount는 연간 총액 (÷12 환산)
    payment_cycle: str = "매월"        # "매월" | "분기" | "반기" | "연"
    min_wage_type: str = ""            # "" | "standard" | "regular_bonus" | "welfare" | "excluded"
    guaranteed_amount: float | None = None  # 최소보장 성과급의 보장분 금액

    @property
    def monthly_amount(self) -> float:
        """월 환산 금액 (payment_cycle 반영)

        현재 minimum_wage.py:246-256의 _monthly_amount() 대체
        """
        if self.annual or self.payment_cycle == "연":
            return self.amount / 12
        elif self.payment_cycle == "분기":
            return self.amount / 3
        elif self.payment_cycle == "반기":
            return self.amount / 6
        return self.amount

    @classmethod
    def from_dict(cls, d: dict) -> "FixedAllowance":
        """dict → FixedAllowance 변환 (하위 호환)

        기존 dict 입력을 그대로 수용하기 위한 팩토리 메서드
        """
        return cls(
            name=d.get("name", "수당"),
            amount=float(d.get("amount", 0)),
            condition=d.get("condition", "없음"),
            is_ordinary=d.get("is_ordinary"),   # None 허용
            annual=d.get("annual", False),
            payment_cycle=d.get("payment_cycle", "매월"),
            min_wage_type=d.get("min_wage_type", ""),
            guaranteed_amount=d.get("guaranteed_amount"),
        )
```

**하위 호환 전략**:

```python
# WageInput.fixed_allowances 타입은 list로 유지 (dict과 FixedAllowance 모두 수용)
# 각 계산기 진입 시 정규화:

def _normalize_allowances(raw: list) -> list[FixedAllowance]:
    """list[dict | FixedAllowance] → list[FixedAllowance]"""
    result = []
    for item in raw:
        if isinstance(item, FixedAllowance):
            result.append(item)
        elif isinstance(item, dict):
            result.append(FixedAllowance.from_dict(item))
        # 그 외 타입은 무시
    return result
```

이 함수를 `shared.py`에 배치하고, 각 계산기에서 `inp.fixed_allowances` 접근 시 호출합니다.

**적용 후 코드 변경 예시** (ordinary_wage.py:88-114):

```python
# Before:
for a in inp.fixed_allowances:
    name = a.get("name", "수당")
    condition = a.get("condition", "없음")
    amount = float(a.get("amount", 0))
    is_annual = a.get("annual", False)

# After:
allowances = _normalize_allowances(inp.fixed_allowances)
for a in allowances:
    name = a.name
    condition = a.condition
    amount = a.amount
    is_annual = a.annual
```

---

### 3.3 `utils.py` — RoundingPolicy

```python
from enum import Enum

class RoundingPolicy(Enum):
    """반올림 정책

    현재 상태:
    - overtime.py: round(x, 0)
    - insurance.py: int(x)  (절삭)
    - minimum_wage.py: round(x, 0)
    - severance.py: round(x, 2) (평균임금), round(x, 0) (퇴직금)
    """
    WON = "won"              # 원 단위 반올림: round(x, 0) — 수당/퇴직금
    TRUNCATE = "truncate"    # 원 미만 절삭: int(x) — 보험료/세금
    DECIMAL_2 = "decimal_2"  # 소수점 2자리: round(x, 2) — 시급/일급

def apply_rounding(value: float, policy: RoundingPolicy) -> float:
    """정책에 따른 반올림 적용"""
    if policy == RoundingPolicy.WON:
        return round(value, 0)
    elif policy == RoundingPolicy.TRUNCATE:
        return float(int(value))
    elif policy == RoundingPolicy.DECIMAL_2:
        return round(value, 2)
    return value
```

**적용 원칙**:
- 수당/급여/퇴직금 → `RoundingPolicy.WON`
- 4대보험/소득세 → `RoundingPolicy.TRUNCATE`
- 시급/일급/비율 → `RoundingPolicy.DECIMAL_2`

> **참고**: 이번 리팩토링에서는 RoundingPolicy를 추가하되, 기존 결과값 변경을 방지하기 위해 각 계산기의 현재 반올림 방식을 그대로 매핑합니다. 정책 통일은 별도 후속 작업으로 진행합니다.

---

### 3.4 `facade/` — facade.py 분리

현재 `facade.py` (700줄)를 4개 파일로 분리:

#### `facade/__init__.py` (~200줄)

```python
"""WageCalculator 통합 퍼사드"""

from .registry import CALC_TYPES, CALC_TYPE_MAP, _STANDARD_CALCS
from .conversion import _provided_info_to_input, _guess_start_date
from .helpers import (
    _pop_overtime, _pop_minimum_wage, _pop_weekly_holiday,
    _pop_annual_leave, _pop_dismissal, _pop_comprehensive,
    _pop_prorated, _pop_public_holiday, _pop_insurance,
    _pop_employer_insurance, _pop_severance, _pop_unemployment,
    _pop_compensatory, _pop_wage_arrears, _pop_parental,
    _pop_maternity, _pop_flexible, _pop_business_size,
    _pop_eitc, _pop_retirement_tax, _pop_retirement_pension,
    _pop_average_wage, _pop_shutdown, _pop_industrial_accident,
)
# ... calculator imports는 registry.py에서 관리

class WageCalculator:
    """기존 API 완전 보존"""
    def calculate(self, inp, targets=None): ...
    def from_analysis(self, calculation_type, provided_info): ...
    @staticmethod
    def resolve_calc_type(calculation_type): ...
    @staticmethod
    def supported_types(): ...
```

#### `facade/registry.py` (~120줄)

```python
"""계산기 레지스트리 — CALC_TYPES, CALC_TYPE_MAP, _STANDARD_CALCS"""

# 모든 calc_* import를 여기서 관리
from ..calculators.overtime import calc_overtime, check_weekly_hours_compliance
from ..calculators.minimum_wage import calc_minimum_wage
# ... 나머지 import

CALC_TYPES = { ... }      # 현재 facade.py:37-64
CALC_TYPE_MAP = { ... }   # 현재 facade.py:67-100+
_STANDARD_CALCS = [ ... ] # 현재 facade.py의 (key, func, section, populate, precondition) 튜플 리스트
```

#### `facade/helpers.py` (~250줄)

```python
"""summary 딕셔너리 생성 헬퍼 (_pop_* 함수들)"""

def _pop_overtime(result, summary): ...
def _pop_minimum_wage(result, summary): ...
# ... 23개 _pop_* 함수
```

#### `facade/conversion.py` (~130줄)

```python
"""분석 결과 → WageInput 변환"""

from ..models import WageInput, WageType, BusinessSize, WorkSchedule

def _provided_info_to_input(provided_info: dict) -> WageInput: ...
def _guess_start_date(provided_info: dict) -> str | None: ...
```

**import 경로 호환성**:

```python
# 기존 코드 (변경 없이 작동해야 함):
from wage_calculator.facade import WageCalculator
from wage_calculator import WageCalculator

# facade가 패키지로 변경되면:
# wage_calculator/facade/__init__.py에서 WageCalculator export
# wage_calculator/__init__.py: from .facade import WageCalculator (유지)
```

---

## 4. Migration Plan (상세)

### Phase A — Foundation (기존 코드 변경 없음, 추가만)

| Step | File | Action | Risk |
|------|------|--------|------|
| A1 | `calculators/shared.py` | 신규 생성 (DateRange, AllowanceClassifier, MultiplierContext, _normalize_allowances) | None — 기존 코드 미사용 |
| A2 | `utils.py` | RoundingPolicy enum + apply_rounding() 추가 | None — 기존 함수 유지 |
| A3 | `models.py` | FixedAllowance dataclass + from_dict() 추가 | None — WageInput.fixed_allowances 타입 변경 없음 |
| A4 | 테스트 | `python3 wage_calculator_cli.py` 실행 → 32/32 PASS 확인 | None |

### Phase B — Core Migration (5개 핵심 모듈)

| Step | File | Change | Verification |
|------|------|--------|-------------|
| B1 | `ordinary_wage.py` | `.get()` → `FixedAllowance` 속성 접근 (`_normalize_allowances` 사용) | 테스트 #1-#32 전체 |
| B2 | `minimum_wage.py` | `_EXCLUDED_PATTERNS` → `AllowanceClassifier`, `_monthly_amount` → `a.monthly_amount`, `_min_wage_type` → `AllowanceClassifier.classify_min_wage_type` | 테스트 #2(최저임금) |
| B3 | `overtime.py` | 배율 4줄 → `MultiplierContext(inp)` | 테스트 #1(연장수당) |
| B4 | `severance.py` | `parse_date`+수동계산 → `DateRange(inp.start_date, inp.end_date)` | 테스트 #10(퇴직금) |
| B5 | `annual_leave.py` | 동일 DateRange 적용 | 테스트 #4(연차) |

### Phase C — Broad Migration (나머지 모듈)

| Step | Files | Change |
|------|-------|--------|
| C1 | `dismissal.py`, `unemployment.py`, `weekly_holiday.py` | DateRange 적용 |
| C2 | `comprehensive.py`, `flexible_work.py`, `public_holiday.py` | MultiplierContext 적용 |
| C3 | `legal_hints.py` | AllowanceClassifier.is_overtime_related() 적용 |
| C4 | `average_wage.py`, `shutdown_allowance.py`, `industrial_accident.py` | DateRange 적용 |
| C5 | `insurance.py`, `parental_leave.py`, `maternity_leave.py` | _normalize_allowances 적용 (해당 시) |
| C6 | 테스트 | 32/32 PASS 확인 |

### Phase D — Facade Split

| Step | Action | Verification |
|------|--------|-------------|
| D1 | `facade.py` → `facade/` 디렉토리 생성 | - |
| D2 | `facade/registry.py` 분리 (CALC_TYPES, CALC_TYPE_MAP, _STANDARD_CALCS) | import 테스트 |
| D3 | `facade/helpers.py` 분리 (_pop_* 함수) | import 테스트 |
| D4 | `facade/conversion.py` 분리 (_provided_info_to_input) | import 테스트 |
| D5 | `facade/__init__.py` 작성 (WageCalculator 클래스) | - |
| D6 | `wage_calculator/__init__.py` import 경로 확인 | `from wage_calculator.facade import WageCalculator` 작동 확인 |
| D7 | 기존 `facade.py` 삭제 | 32/32 PASS 확인 |

---

## 5. Test Plan

### 5.1 회귀 테스트

| 검증 | 방법 | 기준 |
|------|------|------|
| 전체 계산기 | `python3 wage_calculator_cli.py` | 32/32 PASS |
| 금액 일치 | 각 테스트 케이스 결과값 비교 | 원 단위 동일 |
| import 호환 | `from wage_calculator.facade import WageCalculator` | 에러 없음 |
| `from_analysis` | chatbot.py 시뮬레이션 | 동일 결과 |

### 5.2 리팩토링 검증 (Phase 완료 시)

| 검증 | 방법 | 목표 |
|------|------|------|
| 중복 제거 | `grep -r "parse_date(inp.start_date)" wage_calculator/` | 0건 (DateRange 사용) |
| 매직 스트링 | `grep -r 'a.get("condition"' wage_calculator/` | 0건 (FixedAllowance 사용) |
| 배율 중복 | `grep -r "BusinessSize.UNDER_5" wage_calculator/calculators/` | shared.py만 |
| 코드줄 감소 | `find wage_calculator -name "*.py" -exec wc -l {} +` | 20%+ 감소 |

### 5.3 Edge Case 확인

- [ ] `fixed_allowances`에 dict과 FixedAllowance 혼재 입력
- [ ] `FixedAllowance.from_dict({})` — 빈 dict
- [ ] `DateRange(None, None)` — 입사일 미입력
- [ ] `DateRange("2024-01-01", "2023-01-01")` — start > end
- [ ] `MultiplierContext` with `BusinessSize.OVER_10` (5인 이상 경로)

---

## 6. Convention Reference

### 6.1 Python Naming (기존 유지)

| Target | Rule | Example |
|--------|------|---------|
| 클래스 | PascalCase | `DateRange`, `FixedAllowance` |
| 함수 | snake_case | `calc_overtime`, `_normalize_allowances` |
| 상수 | UPPER_SNAKE_CASE | `OVERTIME_RATE`, `WEEKS_PER_MONTH` |
| 모듈 내 private | `_` prefix | `_resolve_is_ordinary()` |
| 공개 유틸 (shared.py) | prefix 없음 | `AllowanceClassifier.classify_min_wage_type()` |

### 6.2 Import Order

```python
# 1. stdlib
from dataclasses import dataclass
from datetime import date
from enum import Enum

# 2. 패키지 내 상위 모듈
from ..models import WageInput, BusinessSize
from ..utils import parse_date, WEEKS_PER_MONTH
from ..constants import OVERTIME_RATE

# 3. 같은 디렉토리
from .shared import DateRange, MultiplierContext, AllowanceClassifier
from .ordinary_wage import OrdinaryWageResult
```

---

## 7. File Change Summary

### 신규 파일

| File | Lines (예상) | Contents |
|------|-------------|----------|
| `calculators/shared.py` | ~120 | DateRange, AllowanceClassifier, MultiplierContext, _normalize_allowances |
| `facade/__init__.py` | ~200 | WageCalculator 클래스 |
| `facade/registry.py` | ~120 | CALC_TYPES, CALC_TYPE_MAP, _STANDARD_CALCS |
| `facade/helpers.py` | ~250 | _pop_* 함수 23개 |
| `facade/conversion.py` | ~130 | _provided_info_to_input, _guess_start_date |

### 수정 파일

| File | Change |
|------|--------|
| `models.py` | +FixedAllowance 데이터클래스 (~30줄) |
| `utils.py` | +RoundingPolicy enum + apply_rounding (~20줄) |
| `ordinary_wage.py` | `.get()` → FixedAllowance 속성 |
| `minimum_wage.py` | _EXCLUDED_PATTERNS 제거, AllowanceClassifier 사용 |
| `overtime.py` | 배율 4줄 → MultiplierContext |
| `severance.py` | parse_date 패턴 → DateRange |
| `annual_leave.py` | parse_date 패턴 → DateRange |
| + 15개 추가 계산기 | 유사 패턴 적용 |
| `legal_hints.py` | 키워드 매칭 → AllowanceClassifier |
| `__init__.py` | facade import 경로 변경 |

### 삭제 파일

| File | Reason |
|------|--------|
| `facade.py` | → `facade/` 패키지로 분리 (Phase D) |

---

## 8. Implementation Order

```
Phase A (Foundation)     Phase B (Core)           Phase C (Broad)         Phase D (Split)
─────────────────────    ────────────────────     ────────────────────    ────────────────────
A1: shared.py 생성       B1: ordinary_wage.py     C1: 날짜 3개 모듈       D1: facade/ 디렉토리
A2: utils.py 확장        B2: minimum_wage.py      C2: 배율 3개 모듈       D2: registry.py
A3: models.py 확장       B3: overtime.py          C3: legal_hints.py      D3: helpers.py
A4: 테스트 확인          B4: severance.py         C4: 나머지 날짜 모듈     D4: conversion.py
                         B5: annual_leave.py      C5: 보험/휴직 모듈       D5: __init__.py
                         테스트 확인              C6: 테스트 확인          D6: import 확인
                                                                          D7: facade.py 삭제
```

각 Phase 완료 시 반드시 `python3 wage_calculator_cli.py` → 32/32 PASS 확인

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-12 | Initial draft | Claude Code |
