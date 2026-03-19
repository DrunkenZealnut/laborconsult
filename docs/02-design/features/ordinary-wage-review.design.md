# 통상임금 계산 모듈 리뷰 Design Document

> **Summary**: nodong.kr 대비 Gap 3건(최소보장 성과급, 1일 통상임금 출력, 법률 힌트 보강)의 상세 설계
>
> **Project**: laborconsult (노동OK 임금계산기)
> **Author**: Claude PDCA
> **Date**: 2026-03-08
> **Status**: Draft
> **Planning Doc**: [ordinary-wage-review.plan.md](../../01-plan/features/ordinary-wage-review.plan.md)

---

## 1. Overview

### 1.1 Design Goals

1. **최소보장 성과급 통상임금 산입**: `AllowanceCondition` enum에 `GUARANTEED_PERFORMANCE` 추가, `_resolve_is_ordinary()` 분기 로직 구현
2. **1일 통상임금 출력**: `OrdinaryWageResult`에 `daily_ordinary_wage` 필드 추가, 다운스트림(facade, result) 반영
3. **법률 힌트 보강**: 최소보장 성과급 관련 검토 포인트를 `legal_hints.py`에 추가
4. **하위 호환성**: 기존 32개 테스트 케이스 및 API 인터페이스 변경 없음 보장

### 1.2 Design Principles

- **최소 변경 원칙**: Gap 해소에 필요한 코드만 변경, 불필요한 리팩토링 금지
- **하위 호환**: 기존 `AllowanceCondition.PERFORMANCE`("성과조건") 동작 유지
- **법률 정합성**: 대법원 2023다302838 판결 기준 통상임금 판단 로직 완전성 확보

---

## 2. Architecture

### 2.1 변경 대상 컴포넌트

```
wage_calculator/
├── models.py                          # [변경] AllowanceCondition enum 추가
├── calculators/
│   └── ordinary_wage.py               # [변경] _resolve_is_ordinary() + OrdinaryWageResult
├── legal_hints.py                     # [변경] 최소보장 성과급 힌트 추가
├── facade.py                          # [변경] breakdown에 daily_ordinary_wage 반영
└── __init__.py                        # [확인] AllowanceCondition 재export (기존 포함)

wage_calculator_cli.py                 # [변경] 테스트 케이스 #33~#35 추가
```

### 2.2 Data Flow (변경 경로)

```
WageInput.fixed_allowances[*].condition = "최소보장성과"
  │
  ▼
_resolve_is_ordinary(allowance)
  │ condition == "최소보장성과" → guaranteed_amount 확인
  │   ├─ guaranteed_amount > 0 → (True, "최소보장분 통상임금 포함")
  │   └─ guaranteed_amount == 0 → (False, "보장액 미설정 → 성과조건 제외")
  ▼
calc_ordinary_wage(inp) → OrdinaryWageResult
  │ + daily_ordinary_wage = hourly × daily_work_hours
  ▼
WageCalculator.calculate() → WageResult
  │ breakdown["통상임금"]["1일 통상임금"] 추가
  ▼
format_result() / chatbot.py 출력
```

### 2.3 Dependencies (영향 분석)

| 변경 파일 | 영향받는 파일 | 영향 내용 |
|-----------|-------------|-----------|
| `models.py` (AllowanceCondition) | `ordinary_wage.py`, `legal_hints.py` | 새 enum값 참조 |
| `ordinary_wage.py` (OrdinaryWageResult) | `facade.py`, `legal_hints.py`, `__init__.py` | 새 필드 추가 |
| `ordinary_wage.py` (_resolve_is_ordinary) | 없음 (내부 함수) | 분기 추가만 |
| `legal_hints.py` | 없음 | 힌트 추가만 |

---

## 3. Data Model 변경

### 3.1 AllowanceCondition Enum 추가

**파일**: `wage_calculator/models.py:33-46`

```python
class AllowanceCondition(Enum):
    NONE        = "없음"         # 조건 없음 — 통상임금 해당
    ATTENDANCE  = "근무일수"      # 소정근로일수 이내 조건 — 통상임금 인정
    EMPLOYMENT  = "재직조건"      # 재직자만 지급 — 통상임금 인정
    PERFORMANCE = "성과조건"      # 성과·목표 달성 조건 — 통상임금 제외
    GUARANTEED_PERFORMANCE = "최소보장성과"  # [신규] 최소지급분 보장 성과급 — 보장분만 통상임금 포함
```

**fixed_allowances 사용 예시**:
```python
{
    "name": "성과급",
    "amount": 3000000,           # 연간 성과급 총액 (최대)
    "annual": True,
    "condition": "최소보장성과",
    "guaranteed_amount": 1200000  # [신규] 연간 최소보장분 (이것만 통상임금 산입)
}
```

**설계 결정**: `guaranteed_amount` 키를 `fixed_allowances` dict에 선택적으로 추가
- `guaranteed_amount` 존재 + `condition == "최소보장성과"` → 보장분만 통상임금 포함
- `guaranteed_amount` 미존재 → `amount` 전액을 보장분으로 간주
- WageInput dataclass 변경 불필요 (fixed_allowances는 `list[dict]`)

### 3.2 OrdinaryWageResult 필드 추가

**파일**: `wage_calculator/calculators/ordinary_wage.py:17-25`

```python
@dataclass
class OrdinaryWageResult:
    """통상임금 계산 결과"""
    hourly_ordinary_wage: float          # 통상시급 (원/시간)
    daily_ordinary_wage: float           # [신규] 1일 통상임금 (원/일)
    monthly_ordinary_wage: float         # 월 통상임금 총액 (원)
    monthly_base_hours: float            # 적용된 월 기준시간
    included_items: list                 # 통상임금 포함 항목 목록
    excluded_items: list                 # 통상임금 제외 항목 목록
    formula: str                         # 계산식 설명
```

**계산식**: `daily_ordinary_wage = hourly_ordinary_wage × daily_work_hours`

---

## 4. 로직 상세 설계

### 4.1 `_resolve_is_ordinary()` 변경

**파일**: `wage_calculator/calculators/ordinary_wage.py:123-148`

**현재 로직**:
```
condition == "성과조건" → (False, "") 일괄 제외
```

**변경 후 로직**:
```
condition == "성과조건" → (False, "") 일괄 제외  # 기존 유지
condition == "최소보장성과" →
  ├─ explicit is False → (False, "명시적 제외 설정")
  └─ else → (True, "최소보장분 통상임금 포함 (대법원 2023다302838)")
```

**상세 코드 설계**:

```python
def _resolve_is_ordinary(allowance: dict) -> tuple[bool, str]:
    condition = allowance.get("condition", "없음")
    explicit = allowance.get("is_ordinary")
    name = allowance.get("name", "수당")

    # 성과조건: 통상임금 제외 (기존 유지)
    if condition == "성과조건":
        if explicit is True:
            return False, "성과조건부로 통상임금 제외 처리 (명시 설정 무시)"
        return False, ""

    # [신규] 최소보장 성과급: 보장분만 통상임금 포함
    if condition == "최소보장성과":
        if explicit is False:
            return False, "명시적 제외 설정"
        return True, "최소보장분 통상임금 포함 (대법원 2023다302838)"

    # 재직조건·근무일수 조건: 기존 로직 유지
    if condition in ["재직조건", "근무일수"]:
        if explicit is False:
            return True, f"재직/근무일수 조건부이나 대법원 2023다302838에 따라 통상임금 포함"
        return True, ""

    # 조건 없음: 기존 로직 유지
    return (explicit if explicit is not None else True), ""
```

### 4.2 `calc_ordinary_wage()` 수당 금액 처리

**최소보장 성과급의 금액 처리 포인트**: `allowance_total` 합산 시 `guaranteed_amount` 우선 적용

**현재 코드** (ordinary_wage.py:86-104):
```python
for a in inp.fixed_allowances:
    amount = float(a.get("amount", 0))
    is_annual = a.get("annual", False)
    is_ordinary, note = _resolve_is_ordinary(a)
    monthly_amount = amount / 12 if is_annual else amount
    ...
```

**변경 후** (최소보장 성과급인 경우 보장분만 산입):
```python
for a in inp.fixed_allowances:
    condition = a.get("condition", "없음")
    amount = float(a.get("amount", 0))
    is_annual = a.get("annual", False)
    is_ordinary, note = _resolve_is_ordinary(a)

    # 최소보장 성과급: guaranteed_amount가 있으면 그 금액만 산입
    if condition == "최소보장성과" and is_ordinary:
        guaranteed = float(a.get("guaranteed_amount", amount))
        effective_amount = guaranteed
    else:
        effective_amount = amount

    monthly_amount = effective_amount / 12 if is_annual else effective_amount
    ...
```

### 4.3 `daily_ordinary_wage` 산출

**위치**: `calc_ordinary_wage()` 반환부 (ordinary_wage.py:111-120)

```python
hourly_ordinary = monthly_ordinary / base_hours
daily_work_hours = inp.schedule.daily_work_hours or 8.0
daily_ordinary = hourly_ordinary * daily_work_hours

return OrdinaryWageResult(
    hourly_ordinary_wage=round(hourly_ordinary, 2),
    daily_ordinary_wage=round(daily_ordinary, 0),    # [신규]
    monthly_ordinary_wage=round(monthly_ordinary, 0),
    monthly_base_hours=base_hours,
    included_items=included_items,
    excluded_items=excluded_items,
    formula=formula,
)
```

### 4.4 facade.py breakdown 반영

**위치**: `WageCalculator.calculate()` (facade.py:296-304)

```python
result.breakdown["통상임금"] = {
    "통상시급": f"{ow.hourly_ordinary_wage:,.0f}원",
    "1일 통상임금": f"{ow.daily_ordinary_wage:,.0f}원",     # [신규]
    "월 통상임금": f"{ow.monthly_ordinary_wage:,.0f}원",
    "기준시간": f"{ow.monthly_base_hours}h",
}
```

### 4.5 legal_hints.py 보강

**위치**: `_hints_ordinary_wage()` (legal_hints.py:53-105)

**추가 힌트**: 최소보장 성과급이 `condition="성과조건"`으로 입력된 경우 → 최소보장분 존재 여부 안내

```python
# 성과조건인데 guaranteed_amount 키가 있는 경우 → 최소보장성과 전환 안내
if condition == "성과조건" and "guaranteed_amount" in a:
    hints.append(LegalHint(
        category="통상임금",
        condition=f"'{name}': 성과조건이나 최소보장분 {a['guaranteed_amount']:,.0f}원 존재",
        hint=(
            f"'{name}'에 최소지급보장분이 설정되어 있습니다. "
            f"최소지급분이 보장되는 성과급은 통상임금에 해당할 수 있습니다 "
            f"(대법원 2023다302838). condition을 '최소보장성과'로 변경하면 "
            f"보장분만 통상임금에 산입됩니다."
        ),
        basis=ORDINARY_WAGE_2024_RULING,
        priority=1,
    ))
```

---

## 5. 에러 처리

### 5.1 예외 상황

| 상황 | 처리 방법 | 파일 |
|------|-----------|------|
| `guaranteed_amount` 음수 | `max(0, guaranteed_amount)` 처리 | `ordinary_wage.py` |
| `guaranteed_amount > amount` | `min(guaranteed_amount, amount)` 클램핑 | `ordinary_wage.py` |
| `daily_work_hours = 0` | `daily_work_hours or 8.0` 기본값 | `ordinary_wage.py` |
| 기존 코드에서 `OrdinaryWageResult` 생성 시 `daily_ordinary_wage` 누락 | 기존 코드는 `calc_ordinary_wage()` 내부에서만 생성 → 영향 없음 | - |

### 5.2 하위 호환성 보장

| 인터페이스 | 변경 | 호환성 |
|-----------|------|:------:|
| `AllowanceCondition` enum | 새 멤버 추가 | **O** (기존 값 불변) |
| `OrdinaryWageResult` dataclass | 새 필드 추가 (위치 변경) | **주의** |
| `_resolve_is_ordinary()` | 새 분기 추가 | **O** (기존 분기 불변) |
| `fixed_allowances` dict | 새 키 `guaranteed_amount` 선택적 | **O** (기존 dict 호환) |

**주의점**: `OrdinaryWageResult`의 필드 순서 변경 → positional 생성하는 외부 코드가 있으면 깨질 수 있음. 현재 코드베이스에서는 `calc_ordinary_wage()` 내부에서만 keyword argument로 생성하므로 안전.

---

## 6. Test Plan

### 6.1 테스트 범위

| Type | Target | Method |
|------|--------|--------|
| 회귀 테스트 | 기존 #1~#32 케이스 | `wage_calculator_cli.py` 전체 실행 |
| 신규 유닛 | 최소보장 성과급 산입 | #33 케이스 추가 |
| 신규 유닛 | 1일 통상임금 출력 검증 | #34 케이스 추가 |
| 신규 유닛 | 보장액 없는 성과급 제외 | #35 케이스 추가 |

### 6.2 Test Case #33: 최소보장 성과급 통상임금 산입

```python
# 월급 250만원 + 성과급(연 360만원, 최소보장 120만원)
WageInput(
    wage_type=WageType.MONTHLY,
    monthly_wage=2_500_000,
    fixed_allowances=[
        {
            "name": "성과급",
            "amount": 3_600_000,
            "annual": True,
            "condition": "최소보장성과",
            "guaranteed_amount": 1_200_000,
        }
    ],
)
# 기대: 월 통상임금 = 2,500,000 + (1,200,000 / 12) = 2,600,000
# 통상시급 = 2,600,000 / 209 ≈ 12,440원
```

### 6.3 Test Case #34: 1일 통상임금 출력 검증

```python
# 시급 10,030원, 8시간 근무
WageInput(
    wage_type=WageType.HOURLY,
    hourly_wage=10_030,
)
# 기대: hourly = 10,030, daily = 80,240, monthly = 2,096,270
```

### 6.4 Test Case #35: 일반 성과조건 제외 유지

```python
# 월급 300만원 + 순수 성과급(조건="성과조건")
WageInput(
    wage_type=WageType.MONTHLY,
    monthly_wage=3_000_000,
    fixed_allowances=[
        {
            "name": "인센티브",
            "amount": 5_000_000,
            "annual": True,
            "condition": "성과조건",
        }
    ],
)
# 기대: 월 통상임금 = 3,000,000 (성과급 제외)
# 통상시급 = 3,000,000 / 209 ≈ 14,354원
```

---

## 7. Coding Convention Reference

### 7.1 프로젝트 컨벤션 적용

| Item | Convention |
|------|-----------|
| Enum 값 | 한국어 문자열 (`"최소보장성과"`) — 기존 패턴 준수 |
| 금액 포맷 | `{:,.0f}원` — 소수점 없음 |
| Docstring | 한국어, 판례 번호 포함 |
| 테스트 번호 | #33부터 연번 |
| 변수명 | 영문 snake_case (guaranteed_amount) |

### 7.2 Import 순서

```python
# 1. 표준 라이브러리
from dataclasses import dataclass

# 2. 패키지 내부 (상대 import)
from ..models import WageInput, WageType, WorkType
from ..constants import MONTHLY_STANDARD_HOURS, SHIFT_MONTHLY_HOURS, WEEKLY_HOLIDAY_MIN_HOURS
from ..utils import WEEKS_PER_MONTH
```

---

## 8. Implementation Order

### 8.1 구현 순서 (의존성 기반)

```
1. models.py              AllowanceCondition.GUARANTEED_PERFORMANCE 추가
   │
2. ordinary_wage.py       _resolve_is_ordinary() 분기 추가
   │                      + calc_ordinary_wage() guaranteed_amount 처리
   │                      + OrdinaryWageResult.daily_ordinary_wage 추가
   │
3. facade.py              breakdown["통상임금"]에 "1일 통상임금" 추가
   │
4. legal_hints.py         최소보장 성과급 관련 힌트 추가
   │
5. wage_calculator_cli.py 테스트 케이스 #33~#35 추가
   │
6. 회귀 테스트            기존 #1~#32 전체 실행
```

### 8.2 파일별 변경 요약

| 순서 | 파일 | 변경 유형 | 변경 라인(예상) |
|:----:|------|-----------|:--------------:|
| 1 | `models.py` | Enum 추가 | +2줄 |
| 2 | `ordinary_wage.py` | 함수 수정 + 필드 추가 | +15줄 |
| 3 | `facade.py` | breakdown dict 키 추가 | +1줄 |
| 4 | `legal_hints.py` | 힌트 분기 추가 | +15줄 |
| 5 | `wage_calculator_cli.py` | 테스트 케이스 추가 | +60줄 |
| | **합계** | | **~93줄** |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-08 | Initial design — Gap 3건 상세 설계 | Claude PDCA |
