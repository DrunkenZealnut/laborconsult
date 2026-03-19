# Design: 연차수당 계산기 기능 보완 (annual-leave-review)

## 1. 설계 개요

Plan 문서의 6개 갭(G1~G6) 보완을 위한 상세 설계서.

| 항목 | 내용 |
|------|------|
| Plan 참조 | `docs/01-plan/features/annual-leave-review.plan.md` |
| 대상 모듈 | `wage_calculator/calculators/annual_leave.py` (주) |
| 연관 모듈 | `models.py`, `constants.py`, `facade.py`, `wage_calculator_cli.py` |
| 설계 원칙 | 기존 인터페이스 호환 유지, 하위 호환성 보장 |

---

## 2. 데이터 모델 변경

### 2.1 WageInput 필드 변경

`models.py`의 연차 계산 섹션 (현재 L144~L148):

```python
# ── 연차 계산용 ──────────────────────────────────────────────────────────
annual_leave_used: float = 0.0         # 사용한 연차 일수
attendance_rate: float = 1.0           # 출근율 (0.0~1.0, 기본 100%)
use_fiscal_year: bool = False          # 회계연도(1/1) 기준 여부  ← 기존 (미사용)
leave_use_promotion: bool = False      # 사용촉진제도 실시 여부 (근기법 제61조)
first_year_leave_used: float = 0.0     # ← 신규: 1년 미만 기간 중 사용한 연차 (제60조③ 차감용)
```

**변경 사항**:
- `use_fiscal_year`: 이미 존재하나 로직 미구현 → G2에서 활용
- `first_year_leave_used`: **신규 추가** → G1(2년차 차감) 계산에 사용
  - 기본값 `0.0` (하위 호환)
  - 2년차 부여일수 = `15 - first_year_leave_used`

### 2.2 AnnualLeaveResult 필드 확장

```python
@dataclass
class AnnualLeaveResult(BaseCalculatorResult):
    accrued_days: float = 0.0           # 발생 연차 일수 (현재 기간)
    used_days: float = 0.0              # 사용 연차 일수
    remaining_days: float = 0.0         # 미사용 연차 일수
    annual_leave_pay: float = 0.0       # 미사용 연차수당 (원)
    service_years: float = 0.0          # 재직 연수

    # ── 신규 필드 ────────────────────────────────────────────
    schedule: list = field(default_factory=list)  # G3: 연도별 발생 스케줄
    deducted_days: float = 0.0          # G1: 제60조③ 차감 일수
    is_part_time_ratio: bool = False    # G4: 단시간근로자 비례 적용 여부
    part_time_ratio: float = 1.0        # G4: 비례 계수
    fiscal_year_gap: float = 0.0        # G5: 회계기준일 vs 입사일 차이
```

### 2.3 constants.py 추가 상수

```python
# ── 단시간근로자 연차 ────────────────────────────────────────────────────
PART_TIME_MIN_WEEKLY_HOURS = 15.0      # 주 15시간 미만 → 연차 미발생
FULL_TIME_WEEKLY_HOURS = 40.0          # 통상근로자 기준 주 소정근로시간
FULL_TIME_DAILY_HOURS = 8.0            # 통상근로자 기준 1일 소정근로시간
```

---

## 3. 알고리즘 상세 설계

### 3.1 [G1] 2년차 연차 차감 (근기법 제60조 제3항)

**영향 범위**: `_calc_accrued_days()` 함수

**현재 로직 문제**:
```python
# 현재: service_years >= 1일 때 무조건 15일 기본 부여
extra_years = int(service_years - 1)
extra_days = min(extra_years // 2, 10)
accrued = min(15 + extra_days, 25)
```

**변경 로직**:
```python
def _calc_accrued_days(service_days, service_years, attendance_rate,
                       start=None, end=None,
                       first_year_leave_used=0.0) -> float:
    if service_years < 1:
        # 1년 미만: 기존과 동일 (월 1일, 최대 11일)
        ...
    else:
        # 1년 이상 기본 부여
        extra_years = int(service_years - 1)
        extra_days = min(extra_years // ANNUAL_LEAVE_ADD_YEARS, ANNUAL_LEAVE_ADD_MAX)
        base = min(ANNUAL_LEAVE_BASE_DAYS + extra_days, ANNUAL_LEAVE_MAX_DAYS)

        # ★ 제60조③ 차감: 재직 1~2년 사이이고 first_year_leave_used > 0이면 차감
        if extra_years == 0 and first_year_leave_used > 0:
            deduction = min(first_year_leave_used, ANNUAL_LEAVE_FIRST_YEAR_MAX)
            base = max(0, base - deduction)

        if attendance_rate < 0.8:
            base = 0
        accrued = base

    return float(accrued)
```

**핵심 규칙**:
- `extra_years == 0` → 재직 1~2년 (2년차)
- 차감 상한: `first_year_leave_used`는 최대 11일 (ANNUAL_LEAVE_FIRST_YEAR_MAX)
- 3년차 이후(`extra_years >= 1`)에는 차감 미적용

### 3.2 [G2] 회계기준일(1.1) 기준 계산

**영향 범위**: `calc_annual_leave()` 메인 함수에 분기 추가

**설계**:
```python
if inp.use_fiscal_year:
    accrued = _calc_fiscal_year_leave(start, end, inp.attendance_rate)
else:
    accrued = _calc_accrued_days(...)
```

**`_calc_fiscal_year_leave(start, end, attendance_rate)` 함수**:

```python
def _calc_fiscal_year_leave(start: date, end: date, attendance_rate: float) -> float:
    """회계기준일(1.1~12.31) 기준 연차 계산

    규칙:
    - 입사 첫해: 입사월~12월 잔여 기간에 대한 비례 부여
      예: 7월 입사 → (6개월/12) × 15 = 7.5 → 올림 8일
    - 2년째(다음해 1.1~): 15일 전체 부여
    - 3년째(+2년)부터: 매 2년마다 1일 추가 (최대 25일)
    """
    # end가 속한 회계연도(1.1~12.31) 기준 계산
    fiscal_start = date(end.year, 1, 1)

    # 입사 첫해 여부 판단
    hire_year = start.year
    calc_year = end.year

    if hire_year == calc_year:
        # 입사 첫해: 잔여 월수 비례
        remaining_months = 12 - start.month + (1 if start.day == 1 else 0)
        accrued = math.ceil(ANNUAL_LEAVE_BASE_DAYS * remaining_months / 12)
    else:
        # 입사년도 기준 근속연수 계산
        years_since_hire = calc_year - hire_year
        if years_since_hire <= 1:
            accrued = ANNUAL_LEAVE_BASE_DAYS  # 15일
        else:
            extra = min((years_since_hire - 1) // ANNUAL_LEAVE_ADD_YEARS, ANNUAL_LEAVE_ADD_MAX)
            accrued = min(ANNUAL_LEAVE_BASE_DAYS + extra, ANNUAL_LEAVE_MAX_DAYS)

    if attendance_rate < 0.8:
        accrued = 0

    return float(accrued)
```

**비례 계산 단수처리**: `math.ceil()` (올림) — 근로자 유리 원칙

### 3.3 [G3] 연도별 연차 발생 스케줄 표

**영향 범위**: 신규 함수 `_build_accrual_schedule()`

**설계**:
```python
def _build_accrual_schedule(start: date, end: date,
                            use_fiscal_year: bool = False,
                            first_year_leave_used: float = 0.0) -> list[dict]:
    """입사일~계산일까지의 연도별 연차 발생 스케줄 생성

    Returns:
        [
            {
                "period": "1년 미만",
                "accrual_date": "2024-01-01 ~ 2024-12-31",
                "days": 11,
                "pay_trigger_date": "2025-01-01",
                "note": "매월 개근 시 1일 (최대 11일)"
            },
            {
                "period": "2년차",
                "accrual_date": "2025-01-01",
                "days": 10,
                "pay_trigger_date": "2026-01-01",
                "note": "15일 - 1년 미만 사용 5일 = 10일 (제60조③)"
            },
            ...
        ]
    """
```

**스케줄 생성 로직**:
1. **1년 미만 기간**: 입사일~(입사 후 1년-1일), 매월 1일, 최대 11일
2. **2년차**: 입사 후 1년~2년, 제60조③ 차감 적용
3. **3년차 이후**: 매 2년마다 +1일, 최대 25일
4. **수당 발생일**: 각 기간 종료 다음날

**회계기준일 모드일 때**:
- 기간을 1.1~12.31 단위로 분할
- 입사 첫해는 비례 부여

### 3.4 [G4] 단시간근로자 비례 연차

**영향 범위**: `calc_annual_leave()` 메인 함수

**비례 공식** (노동부 행정해석, 근기법 제18조 제3항):
```
비례 연차 = 통상근로자 연차일수
          × (단시간 주소정근로시간 / 40)
          × (통상 1일 소정근로시간 / 단시간 1일 소정근로시간)
```

**설계**:
```python
def _apply_part_time_ratio(accrued: float, schedule: WorkSchedule) -> tuple[float, float, bool]:
    """단시간근로자 비례 연차 적용

    Returns: (adjusted_days, ratio, is_part_time)
    """
    weekly_hours = schedule.daily_work_hours * schedule.weekly_work_days
    daily_hours = schedule.daily_work_hours

    if weekly_hours >= FULL_TIME_WEEKLY_HOURS:
        return accrued, 1.0, False  # 통상근로자

    if weekly_hours < PART_TIME_MIN_WEEKLY_HOURS:
        return 0.0, 0.0, True  # 주 15시간 미만 → 미발생

    # 비례 계산
    ratio = (weekly_hours / FULL_TIME_WEEKLY_HOURS) * (FULL_TIME_DAILY_HOURS / daily_hours)
    adjusted = round(accrued * ratio, 1)

    return adjusted, ratio, True
```

**적용 시점**: `_calc_accrued_days()` 결과를 받아서 비례 적용 → 최종 `accrued_days`

**단수처리**: `round(x, 1)` — 소수점 첫째 자리

### 3.5 [G5] 퇴직 시 입사일/회계일 비교 정산

**영향 범위**: `calc_annual_leave()` 메인 함수 하단

**설계**:
```python
# use_fiscal_year=True인 경우에만 비교
if inp.use_fiscal_year:
    hire_based = _calc_accrued_days(service_days, service_years, inp.attendance_rate,
                                     start, end, inp.first_year_leave_used)
    fiscal_based = accrued  # 위에서 이미 계산된 회계기준일 연차

    if hire_based > fiscal_based:
        gap = hire_based - fiscal_based
        gap_pay = daily_wage * gap
        warnings.append(
            f"퇴직 시 정산: 입사일 기준({hire_based:.1f}일) > "
            f"회계기준일({fiscal_based:.1f}일) → 차이 {gap:.1f}일 × {daily_wage:,.0f}원 = "
            f"{gap_pay:,.0f}원 추가 지급 필요"
        )
```

### 3.6 [G6] 수당 발생일 계산

스케줄 표(G3)의 `pay_trigger_date` 필드로 구현.

**규칙**:
- 1년 미만 연차: 입사 후 1년 다음날 (사용기간 만료)
- N년차 연차: 입사일 기준 — 해당 연도 종료 다음날
- 회계기준일: 다음해 1월 1일

---

## 4. 함수 구조

### 4.1 변경 후 함수 목록

```
calc_annual_leave(inp, ow)           # 메인 — G1~G6 통합
├── _calc_accrued_days(...)          # 수정 — G1 차감 파라미터 추가
├── _calc_fiscal_year_leave(...)     # 신규 — G2 회계기준일
├── _build_accrual_schedule(...)     # 신규 — G3 스케줄 표
├── _apply_part_time_ratio(...)      # 신규 — G4 단시간 비례
├── _count_complete_months(...)      # 기존 유지
└── (비교 정산 로직)                 # G5 — calc_annual_leave 내 인라인
```

### 4.2 calc_annual_leave 플로우

```
1. 입력 검증 (start_date 필수)
2. 재직기간 계산
3. 단시간근로자 판정 (G4)
4. 연차 발생 계산:
   ├── use_fiscal_year=True → _calc_fiscal_year_leave() (G2)
   └── use_fiscal_year=False → _calc_accrued_days() (G1 차감 포함)
5. 단시간 비례 적용 (G4)
6. 미사용 연차수당 계산
7. 사용촉진제도 체크
8. 연도별 스케줄 생성 (G3 + G6)
9. 퇴직 시 비교 정산 (G5, use_fiscal_year=True만)
10. 결과 조립
```

---

## 5. facade.py 변경

### 5.1 _pop_annual_leave 확장

```python
def _pop_annual_leave(r, result):
    result.summary["연차수당"] = f"{r.annual_leave_pay:,.0f}원"
    result.summary["미사용 연차"] = f"{r.remaining_days:.1f}일"
    if r.deducted_days > 0:
        result.summary["2년차 차감"] = f"{r.deducted_days:.1f}일 (제60조③)"
    if r.is_part_time_ratio:
        result.summary["단시간 비례"] = f"×{r.part_time_ratio:.2f}"
    if r.fiscal_year_gap > 0:
        result.summary["퇴직 시 추가 지급"] = f"{r.fiscal_year_gap:.1f}일"
    return r.annual_leave_pay if not getattr(r, '_promotion_applied', False) else 0
```

### 5.2 CALC_TYPE_MAP 변경 없음

기존 `"연차수당": ["annual_leave"]` 매핑 유지.

---

## 6. 테스트 케이스 설계

### 6.1 기존 테스트 영향 분석

| 기존 # | 설명 | 영향 | 이유 |
|:------:|------|:----:|------|
| #5 | 3년 근속, 5일 사용 | ✅ 무영향 | `extra_years=2`, 차감 해당 없음 |
| #14 | 역월 기준 1월 입사 7월 | ✅ 무영향 | 1년 미만, 차감 무관 |

### 6.2 신규 테스트 케이스

```python
# ── G1: 2년차 차감 ─────────────────────────────────────────
# #79: 2년차, 1년 미만에 5일 사용 → 부여 15-5=10일
{
    "id": 79,
    "desc": "연차 2년차 차감 — 1년 미만 5일 사용 (근기법 제60조③)",
    "input": WageInput(
        wage_type=WageType.MONTHLY,
        monthly_wage=3_000_000,
        business_size=BusinessSize.OVER_5,
        reference_year=2025,
        start_date="2024-01-01",
        end_date="2025-06-01",
        first_year_leave_used=5.0,
        annual_leave_used=0,
    ),
    "targets": ["annual_leave"],
}

# #80: 2년차, 1년 미만 미사용(0일) → 부여 15일 + 미사용 11일 수당
{
    "id": 80,
    "desc": "연차 2년차 미차감 — 1년 미만 미사용 시 15일 전체 부여",
    "input": WageInput(
        wage_type=WageType.MONTHLY,
        monthly_wage=3_000_000,
        business_size=BusinessSize.OVER_5,
        reference_year=2025,
        start_date="2024-01-01",
        end_date="2025-06-01",
        first_year_leave_used=0.0,
        annual_leave_used=0,
    ),
    "targets": ["annual_leave"],
}

# ── G4: 단시간근로자 비례 ────────────────────────────────────
# #81: 주 20시간 (일 4시간×5일), 3년 근속 → 비례 연차
{
    "id": 81,
    "desc": "연차 단시간근로자 비례 — 주 20시간, 3년 근속",
    "input": WageInput(
        wage_type=WageType.HOURLY,
        hourly_wage=10_030,
        business_size=BusinessSize.OVER_5,
        reference_year=2025,
        start_date="2022-01-01",
        end_date="2025-01-01",
        schedule=WorkSchedule(daily_work_hours=4, weekly_work_days=5),
    ),
    "targets": ["annual_leave"],
}

# #82: 주 12시간 (주 15시간 미만) → 연차 미발생
{
    "id": 82,
    "desc": "연차 단시간 주 12시간 — 15시간 미만 미발생",
    "input": WageInput(
        wage_type=WageType.HOURLY,
        hourly_wage=10_030,
        business_size=BusinessSize.OVER_5,
        reference_year=2025,
        start_date="2023-01-01",
        end_date="2025-01-01",
        schedule=WorkSchedule(daily_work_hours=4, weekly_work_days=3),
    ),
    "targets": ["annual_leave"],
}

# ── G2: 회계기준일 모드 ──────────────────────────────────────
# #83: 회계기준일, 7월 입사 → 첫해 비례 8일
{
    "id": 83,
    "desc": "연차 회계기준일 — 7월 입사 첫해 비례 부여",
    "input": WageInput(
        wage_type=WageType.MONTHLY,
        monthly_wage=3_000_000,
        business_size=BusinessSize.OVER_5,
        reference_year=2025,
        start_date="2025-07-01",
        end_date="2025-12-31",
        use_fiscal_year=True,
    ),
    "targets": ["annual_leave"],
}

# #84: 회계기준일, 3년 근속 → 15일 부여
{
    "id": 84,
    "desc": "연차 회계기준일 — 3년 근속 15일",
    "input": WageInput(
        wage_type=WageType.MONTHLY,
        monthly_wage=3_500_000,
        business_size=BusinessSize.OVER_5,
        reference_year=2025,
        start_date="2022-03-15",
        end_date="2025-06-01",
        use_fiscal_year=True,
        annual_leave_used=5,
    ),
    "targets": ["annual_leave"],
}

# ── G3+G6: 스케줄 표 (기존 테스트에서 확인) ─────────────────
# 스케줄은 breakdown 에 포함되어 모든 테스트에서 검증

# ── G5: 퇴직 시 비교 정산 ────────────────────────────────────
# #85: 회계기준일 < 입사일 기준 → 차액 표시
{
    "id": 85,
    "desc": "연차 퇴직 시 회계기준일 vs 입사일 비교 정산",
    "input": WageInput(
        wage_type=WageType.MONTHLY,
        monthly_wage=3_000_000,
        business_size=BusinessSize.OVER_5,
        reference_year=2025,
        start_date="2024-07-01",
        end_date="2025-06-30",
        use_fiscal_year=True,
        annual_leave_used=0,
    ),
    "targets": ["annual_leave"],
}
```

---

## 7. 구현 순서

| 단계 | 작업 | 파일 | 의존성 |
|:----:|------|------|--------|
| 1 | `models.py`: `first_year_leave_used` 필드 추가 | models.py | 없음 |
| 2 | `constants.py`: 단시간 상수 추가 | constants.py | 없음 |
| 3 | `annual_leave.py`: G1 차감 로직 | annual_leave.py | 단계 1 |
| 4 | `annual_leave.py`: G4 단시간 비례 | annual_leave.py | 단계 2 |
| 5 | `annual_leave.py`: G2 회계기준일 | annual_leave.py | 없음 |
| 6 | `annual_leave.py`: G3 스케줄 + G6 수당발생일 | annual_leave.py | 단계 3,5 |
| 7 | `annual_leave.py`: G5 비교 정산 | annual_leave.py | 단계 5 |
| 8 | `annual_leave.py`: AnnualLeaveResult 확장 | annual_leave.py | 전체 |
| 9 | `facade.py`: `_pop_annual_leave` 확장 | facade.py | 단계 8 |
| 10 | `wage_calculator_cli.py`: 테스트 추가 | cli.py | 전체 |

---

## 8. 제약사항 및 주의사항

| 항목 | 설명 |
|------|------|
| 하위 호환 | `first_year_leave_used=0.0` 기본값 → 기존 코드 영향 없음 |
| `use_fiscal_year` | 기존 필드 활용, 새 필드 추가 불필요 |
| 비례 계산 올림 | 회계기준일 비례: `math.ceil()`, 단시간: `round(x, 1)` |
| 스케줄 표 크기 | 최대 25년분 (일반적으로 3~10행) → 성능 무관 |
| 기존 테스트 #5, #14 | `first_year_leave_used=0.0`이고 3년 이상 → 차감 미적용, 결과값 변동 없음 |
| 단시간 판정 기준 | `schedule.daily_work_hours × weekly_work_days` < 40 → 비례 적용 |
