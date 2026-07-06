# 연차발생일수 + 근로시간산정기 Design Document

> **Summary**: 계산기 #26 연차발생일수 + #27 근로시간산정기 상세 설계. 기존 파사드 패턴 준수, WageInput 확장 최소화
>
> **Project**: laborconsult
> **Author**: Claude
> **Date**: 2026-03-20
> **Status**: Draft
> **Planning Doc**: [annual-leave-accrual-work-hours.plan.md](../../01-plan/features/annual-leave-accrual-work-hours.plan.md)

---

## 1. Overview

### 1.1 Design Goals

1. 기존 `annual_leave.py`의 발생일수 로직(`_calc_accrued_days`)을 **재사용**하되, 수당 계산 없이 발생일수만 반환하는 독립 계산기 생성
2. 교대근무 패턴별 근로시간 자동 산출 → `WorkSchedule` 필드에 결과 세팅 → 기존 연장수당 계산기 연계
3. 신규 파일 2개 + 기존 파일 수정 4개로 최소 변경

### 1.2 Design Principles

- **기존 로직 재사용**: `annual_leave.py`의 `_calc_accrued_days`, `_calc_fiscal_year_leave` 호출
- **파사드 패턴 준수**: `BaseCalculatorResult` 상속, `_STANDARD_CALCS` 등록
- **WageInput 최소 확장**: `ShiftPattern` enum + `unpaid_leave_days` 필드만 추가

---

## 2. Architecture

### 2.1 Component Diagram

```
                    ┌──────────────┐
                    │  WageInput   │
                    │ + shift_pattern
                    │ + unpaid_leave_days
                    └──────┬───────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
┌──────────────────────┐  ┌──────────────────────┐
│ annual_leave_accrual │  │   work_hours_calc    │
│   .py (#26)          │  │     .py (#27)        │
│                      │  │                      │
│ 입력: start_date,    │  │ 입력: shift_pattern, │
│   end_date,          │  │   daily_work_hours,  │
│   attendance_rate,   │  │   shift_start_time   │
│   use_fiscal_year    │  │                      │
│                      │  │ 출력: 월 소정/연장/  │
│ 출력: 연도별 발생    │  │   야간/휴일 시간     │
│   일수 테이블        │  │                      │
│                      │  │ → WorkSchedule 세팅  │
│ 재사용:              │  │   → 연장수당 연계    │
│  _calc_accrued_days  │  │                      │
└──────────────────────┘  └──────────────────────┘
              │                         │
              ▼                         ▼
      [연차수당 계산기]           [연장수당 계산기]
      (기존 annual_leave)        (기존 overtime)
```

### 2.2 Dependencies

| Component | Depends On | Purpose |
|-----------|-----------|---------|
| `annual_leave_accrual.py` | `annual_leave.py::_calc_accrued_days` | 발생일수 로직 재사용 |
| `annual_leave_accrual.py` | `shared.py::DateRange` | 재직기간 계산 |
| `work_hours_calc.py` | `models.py::ShiftPattern` | 교대패턴 enum |
| `work_hours_calc.py` | `constants.py` | 법정 기준시간 |

---

## 3. Data Model

### 3.1 WageInput 확장 (models.py)

```python
class ShiftPattern(Enum):
    """교대근무 패턴"""
    SHIFT_2     = "2교대"       # 주간/야간 12h 교대
    SHIFT_3     = "3교대"       # 3조 8h 교대
    SHIFT_3_2   = "3조2교대"    # 3조 12h 교대 (2일 근무 1일 휴무)
    SHIFT_4_2   = "4조2교대"    # 4조 12h 교대 (2일 근무 2일 휴무)
    ALTERNATE   = "격일근무"     # 24h 근무 24h 휴무 (경비 등)
    CUSTOM      = "직접입력"     # 사용자 지정

# WageInput에 추가할 필드:
shift_pattern: Optional[ShiftPattern] = None   # 교대근무 패턴
shift_start_time: int = 9                       # 근무 시작 시각 (0~23, 기본 09시)
shift_work_hours: float = 12.0                  # 1교대 근무시간 (기본 12h)
shift_break_hours: float = 1.0                  # 교대당 휴게시간
unpaid_leave_days: int = 0                      # 무급휴직 일수 (연차 출근율 반영)
```

### 3.2 Result 데이터클래스

```python
# ── 계산기 A: 연차발생일수 ──

@dataclass
class AnnualLeaveAccrualResult(BaseCalculatorResult):
    total_accrued: float = 0.0       # 현 시점 발생 연차 총일수
    service_years: float = 0.0       # 재직연수
    attendance_rate: float = 1.0     # 출근율
    is_part_time: bool = False       # 단시간근로자 여부
    part_time_ratio: float = 1.0     # 비례계수
    accrual_table: list = field(default_factory=list)
    # accrual_table 각 항목:
    # {"year": 1, "period": "2024.03~2025.03", "days": 15, "basis": "근기법 제60조②"}


# ── 계산기 B: 근로시간산정 ──

@dataclass
class WorkHoursCalcResult(BaseCalculatorResult):
    shift_pattern: str = ""
    monthly_scheduled_hours: float = 0.0    # 월 소정근로시간
    monthly_overtime_hours: float = 0.0     # 월 연장근로시간
    monthly_night_hours: float = 0.0        # 월 야간근로시간 (22~06시)
    monthly_holiday_hours: float = 0.0      # 월 휴일근로시간
    monthly_total_hours: float = 0.0        # 월 총 실근로시간
    weekly_average_hours: float = 0.0       # 주 평균 근로시간
    is_over_52h: bool = False               # 주 52시간 초과 여부
    cycle_description: str = ""             # 교대 주기 설명
```

---

## 4. API (계산기 함수 인터페이스)

### 4.1 연차발생일수

```python
def calc_annual_leave_accrual(inp: WageInput, ow: OrdinaryWageResult) -> AnnualLeaveAccrualResult:
    """
    입사일 기준 연차 발생일수 계산 (수당 미산출)

    핵심 로직: annual_leave.py의 _calc_accrued_days() 재사용
    추가: 무급휴직 기간 출근율 반영, 연도별 누적 테이블
    """
```

**처리 순서:**
1. `DateRange(start_date, end_date)` → 재직기간 산출
2. `unpaid_leave_days` → 출근율 재계산: `(총일수 - 무급휴직) / 총일수`
3. `_calc_accrued_days()` 또는 `_calc_fiscal_year_leave()` 호출
4. 단시간 비례 적용 (`_apply_part_time_ratio`)
5. 연도별 누적 테이블 생성 (`_build_accrual_schedule` 재사용)
6. `AnnualLeaveAccrualResult` 반환 (수당 필드 없음)

### 4.2 근로시간산정기

```python
def calc_work_hours(inp: WageInput, ow: OrdinaryWageResult) -> WorkHoursCalcResult:
    """
    교대근무 패턴별 월 소정/연장/야간/휴일 근로시간 산출

    결과를 inp.schedule에 세팅하여 후속 연장수당 계산기 연계
    """
```

**처리 순서:**
1. `ShiftPattern` → 교대 주기 해석
2. 패턴별 계산:

```python
SHIFT_PATTERNS = {
    "2교대": {
        "cycle_days": 2,        # 2일 주기 (주간→야간)
        "work_days": 2,         # 주기 내 근무일
        "hours_per_shift": 12,
        "night_hours_per_shift": 6,  # 야간조 22~06시 (6h)
        "description": "주간(06~18)·야간(18~06) 교대"
    },
    "3교대": {
        "cycle_days": 3,
        "work_days": 3,
        "hours_per_shift": 8,
        "night_hours_per_shift": 8,  # 야간조 전체 (22~06 해당분)
        "description": "주간·중간·야간 8시간 3교대"
    },
    "3조2교대": {
        "cycle_days": 3,
        "work_days": 2,
        "hours_per_shift": 12,
        "night_hours_per_shift": 6,
        "description": "2일 근무 1일 휴무 (12시간)"
    },
    "4조2교대": {
        "cycle_days": 4,
        "work_days": 2,
        "hours_per_shift": 12,
        "night_hours_per_shift": 6,
        "description": "2일 근무 2일 휴무 (12시간)"
    },
    "격일근무": {
        "cycle_days": 2,
        "work_days": 1,
        "hours_per_shift": 24,
        "night_hours_per_shift": 8,  # 22~06 (8h)
        "description": "24시간 근무 24시간 휴무"
    },
}
```

3. 월 환산:
```python
days_per_month = 365.25 / 12  # 30.4375
cycles_per_month = days_per_month / cycle_days
monthly_total = cycles_per_month * work_days * (hours_per_shift - break_hours)
monthly_scheduled = min(monthly_total, 40 * WEEKS_PER_MONTH)  # 법정 상한
monthly_overtime = max(0, monthly_total - monthly_scheduled)
monthly_night = cycles_per_month * (night_shifts_per_cycle) * night_hours_per_shift
weekly_avg = monthly_total / WEEKS_PER_MONTH
is_over_52 = weekly_avg > 52
```

4. `inp.schedule`에 결과 세팅:
```python
inp.schedule.monthly_scheduled_hours = monthly_scheduled
inp.schedule.weekly_overtime_hours = monthly_overtime / WEEKS_PER_MONTH
inp.schedule.weekly_night_hours = monthly_night / WEEKS_PER_MONTH
inp.schedule.shift_monthly_hours = monthly_total
```

---

## 5. 레지스트리 통합

### 5.1 registry.py 변경

```python
# CALC_TYPES 추가
"annual_leave_accrual": "연차 발생일수 (입사일 기준)",
"work_hours_calc":      "교대근무 근로시간 산정",

# CALC_TYPE_MAP 추가
"연차발생":     ["annual_leave_accrual"],
"연차몇개":     ["annual_leave_accrual"],
"연차일수":     ["annual_leave_accrual"],
"연차개수":     ["annual_leave_accrual"],
"근로시간":     ["work_hours_calc"],
"교대근무시간": ["work_hours_calc"],
"근로시간산정": ["work_hours_calc"],
"근로시간계산": ["work_hours_calc"],
"소정근로시간": ["work_hours_calc"],
"월근로시간":   ["work_hours_calc"],

# _STANDARD_CALCS 추가 (기존 리스트 끝에)
("annual_leave_accrual", calc_annual_leave_accrual, "연차 발생일수", _pop_annual_leave_accrual, None),
("work_hours_calc",      calc_work_hours,           "근로시간 산정", _pop_work_hours,
 lambda inp: inp.shift_pattern is not None),
```

### 5.2 helpers.py 추가

```python
def _pop_annual_leave_accrual(r, result):
    """연차 발생일수 → summary"""
    result.summary["연차 발생일수"] = f"{r.total_accrued:.1f}일"
    result.summary["재직기간"] = f"{r.service_years:.1f}년"
    return 0

def _pop_work_hours(r, result):
    """근로시간 산정 → summary"""
    result.summary["월 소정근로시간"] = f"{r.monthly_scheduled_hours:.1f}시간"
    result.summary["월 연장근로시간"] = f"{r.monthly_overtime_hours:.1f}시간"
    result.summary["월 야간근로시간"] = f"{r.monthly_night_hours:.1f}시간"
    if r.is_over_52h:
        result.summary["주 52시간 초과"] = f"⚠️ 주 평균 {r.weekly_average_hours:.1f}시간"
    return 0
```

### 5.3 conversion.py 매핑 추가

```python
# _provided_info_to_input()에 추가
"교대패턴":     → inp.shift_pattern = ShiftPattern(value)
"무급휴직일수": → inp.unpaid_leave_days = int(value)
"교대시작시간": → inp.shift_start_time = int(value)
"교대근무시간": → inp.shift_work_hours = float(value)
```

---

## 6. Error Handling

| 상황 | 처리 |
|------|------|
| `start_date` 미입력 (연차) | warning + `total_accrued=0` 반환 |
| `shift_pattern` 미입력 (근로시간) | precondition 미충족 → 스킵 |
| 출근율 80% 미만 | warning + 연차 미발생 (0일) |
| `shift_pattern=CUSTOM` + 시간 미입력 | 기본값(12h) 사용 + warning |
| 주 52시간 초과 | `is_over_52h=True` + warning |

---

## 7. Test Cases

### 7.1 연차발생일수 (8건)

| # | 시나리오 | start_date | end_date | 추가 입력 | 기대 total_accrued |
|:-:|---------|-----------|---------|----------|:-----------------:|
| 1 | 6개월 근속 | 2025-09-20 | 2026-03-20 | - | 6일 |
| 2 | 1년 근속 개근 | 2025-03-20 | 2026-03-20 | - | 15일 |
| 3 | 3년 근속 | 2023-03-20 | 2026-03-20 | - | 16일 |
| 4 | 21년 (25일 상한) | 2005-03-20 | 2026-03-20 | - | 25일 |
| 5 | 2년차 차감 | 2024-03-20 | 2026-03-20 | first_year_used=5 | 10일 |
| 6 | 회계연도 7/1 입사 | 2025-07-01 | 2026-03-20 | fiscal_year=True | 비례 |
| 7 | 단시간 주20h | 2025-03-20 | 2026-03-20 | daily=4h, days=5 | 7.5일 |
| 8 | 무급휴직 3개월 | 2025-03-20 | 2026-03-20 | unpaid=90 | 0일 (75%) |

### 7.2 근로시간산정 (6건)

| # | 패턴 | shift_hours | break | 기대 월소정 | 기대 월연장 | 기대 월야간 |
|:-:|------|:----------:|:-----:|:----------:|:----------:|:----------:|
| 1 | 4조2교대 | 12 | 1 | ~173.8h | ~9.5h | ~83.6h |
| 2 | 3조2교대 | 12 | 1 | ~173.8h | ~52.8h | ~83.6h |
| 3 | 2교대 | 12 | 1 | ~173.8h | ~160.1h | ~83.6h |
| 4 | 격일근무 | 24 | 2 | ~173.8h | ~160.1h | ~121.7h |
| 5 | 3교대 | 8 | 0.5 | ~173.8h | ~57.5h | ~76.8h |
| 6 | 커스텀 | 10 | 1 | ~173.8h | 자동계산 | 자동계산 |

---

## 8. Implementation Order

| Phase | Task | Files | 변경량 |
|-------|------|-------|--------|
| 1 | `models.py` — `ShiftPattern` enum + 필드 3개 추가 | `models.py` | +25줄 |
| 2 | `annual_leave_accrual.py` — 발생일수 계산기 | 신규 | ~120줄 |
| 3 | `work_hours_calc.py` — 근로시간산정기 | 신규 | ~180줄 |
| 4 | `registry.py` — CALC_TYPES/MAP/STANDARD 추가 | 수정 | +20줄 |
| 5 | `helpers.py` — _pop 함수 2개 | 수정 | +15줄 |
| 6 | `conversion.py` — 한국어 매핑 추가 | 수정 | +10줄 |
| 7 | `calculators.html` — 사이드바 메뉴 2건 | 수정 | +10줄 |

**총 예상**: 신규 ~300줄 + 기존 수정 ~80줄

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-20 | Initial draft — 2개 계산기 상세 설계 | Claude |
