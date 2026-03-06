# Design: 5인미만 사업장 판단 계산기 (business-size-calculator)

> Plan 참조: `docs/01-plan/features/business-size-calculator.plan.md`

---

## 1. 설계 개요

### 1.1 설계 방향

`calc_wage_arrears()`처럼 **독립 함수 패턴**을 채택한다. 상시근로자 수 산정은 WageInput 의존 없이 자체 입력(`BusinessSizeInput`)으로 동작하되, facade 연동 시 결과를 `inp.business_size`에 반영할 수 있도록 한다.

### 1.2 변경 파일 목록

| 파일 | 변경 유형 | 내용 |
|------|----------|------|
| `wage_calculator/calculators/business_size.py` | **신규** | 핵심 계산 로직 |
| `wage_calculator/models.py` | 수정 | `WorkerEntry`, `BusinessSizeInput` dataclass 추가 |
| `wage_calculator/facade.py` | 수정 | `CALC_TYPES`, `CALC_TYPE_MAP` 추가, `calculate()` 연동 |
| `wage_calculator/calculators/__init__.py` | 수정 | export 추가 |
| `wage_calculator/__init__.py` | 수정 | public API export 추가 |
| `wage_calculator/constants.py` | 수정 | 상시근로자 수 관련 상수 추가 |
| `wage_calculator_cli.py` | 수정 | 테스트 케이스 #33~#36 추가 |

---

## 2. 데이터 모델 상세 설계

### 2.1 models.py 추가 사항

```python
# ── 상시근로자 수 산정용 ────────────────────────────────────────────

class WorkerType(Enum):
    """근로자 유형 — 상시근로자 수 산정 시 포함/제외 판별"""
    REGULAR       = "통상"        # 통상근로자 → 포함
    CONTRACT      = "기간제"      # 기간제 → 포함
    PART_TIME     = "단시간"      # 단시간 → 포함
    DAILY         = "일용"        # 일용직 → 포함 (해당 가동일만)
    SHIFT         = "교대"        # 교대근무 → 포함 (비번일 포함)
    FOREIGN       = "외국인"      # 외국인 → 포함
    FAMILY        = "가족"        # 가족근로자 → 조건부 포함
    OVERSEAS_LOCAL = "해외현지법인"  # 해외 현지법인 소속 → 제외


@dataclass
class WorkerEntry:
    """개별 근로자 정보"""
    worker_type: WorkerType = WorkerType.REGULAR
    start_date: str = ""              # 근로계약 효력발생일 "YYYY-MM-DD"
    end_date: str | None = None       # 퇴직일 (None이면 재직중)
    is_on_leave: bool = False         # 휴직/휴가/결근/징계 중 여부 (포함 대상)
    is_leave_replacement: bool = False  # 휴직대체자 여부 (제외 대상)
    specific_work_days: list[int] | None = None  # 특정 요일만 출근 (0=월~6=일, None이면 상시)
    name: str = ""                    # 식별용 (선택)


@dataclass
class BusinessSizeInput:
    """상시근로자 수 산정 입력"""
    event_date: str = ""              # 법 적용 사유 발생일 "YYYY-MM-DD"
    workers: list[WorkerEntry] = field(default_factory=list)
    non_operating_days: list[str] | None = None  # 비가동일 "YYYY-MM-DD" 목록 (None이면 토·일)
    is_family_only_business: bool = False  # 동거친족만 사용하는 사업장
```

**설계 결정:**
- `WorkerType` enum을 별도 도입하여 포함/제외 판별을 타입 기반으로 명확히 구분
- `is_on_leave`는 휴직·휴가·결근·징계를 통합 (모두 "고용관계 유지 → 포함" 동일 로직)
- `is_leave_replacement`는 별도 플래그로 분리 (제외 대상이므로 명시적)
- `specific_work_days`는 `None`(상시) vs `[0,2,4]`(월·수·금) 구분

### 2.2 WageInput 연동 필드

```python
# WageInput에 추가 (선택적)
class WageInput:
    ...
    # ── 상시근로자 수 산정용 (선택) ────────────────────────────────────
    business_size_input: BusinessSizeInput | None = None  # 제공 시 business_size 자동 산정
```

---

## 3. 계산기 상세 설계

### 3.1 파일: `wage_calculator/calculators/business_size.py`

#### 3.1.1 결과 dataclass

```python
@dataclass
class BusinessSizeResult:
    """상시근로자 수 산정 결과"""
    regular_worker_count: float        # 산정된 상시근로자 수 (소수점 2자리)
    business_size: BusinessSize        # 판정된 사업장 규모
    calculation_period_start: str      # 산정기간 시작일
    calculation_period_end: str        # 산정기간 종료일
    operating_days: int                # 가동일수
    total_headcount: int               # 연인원 합계
    daily_counts: dict[str, int]       # 일별 근로자 수 {"2026-02-05": 7, ...}
    included_workers: list[dict]       # 포함된 근로자 내역
    excluded_workers: list[dict]       # 제외된 근로자 내역
    below_threshold_days: int          # 5인 미만인 날의 수
    above_threshold_days: int          # 5인 이상인 날의 수
    is_law_applicable: bool            # 법 적용 여부 (미달일수 < 산정기간/2)
    breakdown: dict
    formulas: list[str]
    legal_basis: list[str]
    warnings: list[str]
```

#### 3.1.2 핵심 함수 시그니처

```python
def calc_business_size(bsi: BusinessSizeInput) -> BusinessSizeResult:
    """
    상시근로자 수 산정 (근로기준법 시행령 제7조의2)

    독립 함수: WageInput 없이 BusinessSizeInput만으로 동작.

    산정 절차:
      1. _calc_period()          → 산정기간(1개월) 결정
      2. _calc_operating_days()  → 가동일수 집계
      3. _count_daily_workers()  → 일별 근로자 수 집계 (포함/제외 판별)
      4. _calc_regular_count()   → 연인원 ÷ 가동일수
      5. _determine_size()       → BusinessSize 결정
      6. _check_threshold()      → 미달일수 1/2 판정
    """
```

#### 3.1.3 내부 함수 설계

```python
def _calc_period(event_date: date) -> tuple[date, date]:
    """
    산정기간 결정: event_date 전 역일상 1개월

    예: event_date = 2026-03-06
      → period_start = 2026-02-06
      → period_end   = 2026-03-05 (event_date 전일)

    월말 보정: 시작일의 해당 월 일수가 부족하면 말일로 조정
      예: event_date = 2026-03-31 → start = 2026-02-28
    """
    pass


def _calc_operating_days(
    period_start: date,
    period_end: date,
    non_operating_days: list[date] | None,
) -> tuple[list[date], int]:
    """
    가동일수 집계

    Args:
        period_start, period_end: 산정기간
        non_operating_days: 비가동일 목록 (None이면 토·일을 비가동일로 처리)

    Returns:
        (가동일 날짜 리스트, 가동일수)

    규칙:
        - 비가동일이 명시되면 해당 날만 제외
        - None이면 토·일 제외 (기본)
        - 비가동일에 실근무 시에는 별도 처리하지 않음 (v1 범위 외)
    """
    pass


def _should_include_worker(
    worker: WorkerEntry,
    target_date: date,
    is_family_only: bool,
    has_non_family_worker: bool,
) -> tuple[bool, str]:
    """
    특정 날짜에 해당 근로자를 연인원에 포함할지 판별

    Returns:
        (포함 여부, 사유)

    판별 순서:
        1. 근로계약 효력기간 확인 (start_date ~ end_date)
        2. 휴직대체자 → 제외
        3. 해외현지법인 → 제외
        4. 동거친족만 사업장 + 가족근로자 → 제외 (단, 비가족 1명이라도 있으면 포함)
        5. 특정요일 출근자 → target_date 요일이 specific_work_days에 포함된 경우만 포함
        6. 교대근무·휴직자·결근자 등 → 포함 (고용관계 유지 / 사회통념상 상시)
    """
    pass


def _count_daily_workers(
    operating_dates: list[date],
    workers: list[WorkerEntry],
    is_family_only: bool,
) -> tuple[dict[str, int], list[dict], list[dict]]:
    """
    일별 근로자 수 집계

    Returns:
        (daily_counts, included_workers, excluded_workers)

    daily_counts: {"2026-02-06": 7, "2026-02-07": 8, ...}
    included_workers: [{"name": "...", "worker_type": "통상", "days_counted": 22, "reason": "고용관계 유지"}, ...]
    excluded_workers: [{"name": "...", "worker_type": "기간제", "reason": "휴직대체자"}, ...]
    """
    pass


def _determine_size(regular_count: float) -> BusinessSize:
    """
    상시근로자 수 → BusinessSize enum 결정

    규칙:
        < 5   → UNDER_5
        < 30  → OVER_5
        < 300 → OVER_30
        ≥ 300 → OVER_300
    """
    pass


def _check_threshold(
    daily_counts: dict[str, int],
    operating_days: int,
    threshold: int = 5,
) -> tuple[int, int, bool]:
    """
    법 적용 기준 미달일수 1/2 판정 (시행령 §7의2②1호)

    Args:
        daily_counts: 일별 근로자 수
        operating_days: 가동일수
        threshold: 판정 기준 인원 (기본 5인)

    Returns:
        (미달일수, 충족일수, 법 적용 여부)

    규칙:
        미달일수 < (산정기간 가동일수 / 2) → 법 적용 (True)
        미달일수 ≥ (산정기간 가동일수 / 2) → 법 미적용 (False)
    """
    pass
```

---

## 4. facade.py 연동 설계

### 4.1 CALC_TYPES 추가

```python
CALC_TYPES = {
    ...
    "business_size":       "상시근로자 수 판정",
}
```

### 4.2 CALC_TYPE_MAP 추가

```python
CALC_TYPE_MAP = {
    ...
    "사업장규모": ["business_size"],
}
```

### 4.3 calculate() 내 실행 블록

```python
if "business_size" in targets and inp.business_size_input is not None:
    bs = calc_business_size(inp.business_size_input)
    # 산정된 규모로 WageInput 갱신 (후속 계산기에 반영)
    inp.business_size = bs.business_size
    result.summary["상시근로자 수"] = f"{bs.regular_worker_count:.1f}명"
    result.summary["사업장 규모"] = bs.business_size.value
    result.summary["법 적용 여부"] = "적용" if bs.is_law_applicable else "미적용"
    result.breakdown["상시근로자 수 판정"] = bs.breakdown
    result.formulas.extend(bs.formulas)
    all_warnings.extend(bs.warnings)
    all_legal.extend(bs.legal_basis)
```

**실행 순서**: `business_size` 계산은 **통상임금 계산 직후, 다른 모든 계산기 직전에** 실행한다. 이유: 후속 계산기(overtime, annual_leave 등)가 갱신된 `inp.business_size`를 참조해야 하므로.

### 4.4 _auto_detect_targets() 연동

```python
def _auto_detect_targets(self, inp: WageInput) -> list[str]:
    targets = ["minimum_wage"]

    # 상시근로자 수 산정 입력이 있으면 자동 추가
    if inp.business_size_input is not None:
        targets.insert(0, "business_size")  # 맨 앞에 삽입 (최우선 실행)

    ...
```

---

## 5. constants.py 추가 상수

```python
# ── 상시근로자 수 산정 (근로기준법 시행령 제7조의2) ───────────────────
REGULAR_WORKER_THRESHOLDS = {
    5: BusinessSize.UNDER_5,     # 5인 미만
    30: BusinessSize.OVER_5,     # 5인 이상 30인 미만
    300: BusinessSize.OVER_30,   # 30인 이상 300인 미만
}
# ≥ 300 → OVER_300

CALCULATION_PERIOD_MONTHS = 1    # 산정기간 1개월
DEFAULT_NON_OPERATING_WEEKDAYS = [5, 6]  # 토(5), 일(6) — 기본 비가동일
```

---

## 6. 구현 순서

```
Step 1: models.py — WorkerType, WorkerEntry, BusinessSizeInput 추가
Step 2: constants.py — 상시근로자 수 관련 상수 추가
Step 3: calculators/business_size.py — 핵심 계산 로직 구현
         _calc_period → _calc_operating_days → _should_include_worker
         → _count_daily_workers → _determine_size → _check_threshold
         → calc_business_size (통합)
Step 4: calculators/__init__.py — export 추가
Step 5: __init__.py — public API export 추가
Step 6: models.py — WageInput에 business_size_input 필드 추가
Step 7: facade.py — CALC_TYPES, CALC_TYPE_MAP, calculate(), _auto_detect_targets() 수정
Step 8: wage_calculator_cli.py — 테스트 케이스 #33~#36 추가
```

---

## 7. 테스트 케이스 설계

### 7.1 케이스 #33: 기본 5인 이상 사업장

```python
{
    "id": 33,
    "desc": "상시근로자 수 판정 — 10명 사업장 (기본)",
    "input": BusinessSizeInput(
        event_date="2026-03-06",
        workers=[
            WorkerEntry(worker_type=WorkerType.REGULAR, start_date="2025-01-01")
            for _ in range(10)
        ],
    ),
    "expected": {
        "regular_worker_count": 10.0,
        "business_size": BusinessSize.OVER_5,
        "is_law_applicable": True,
    },
}
```

### 7.2 케이스 #34: 5인 미만 — 휴직대체자 제외

```python
{
    "id": 34,
    "desc": "상시근로자 수 판정 — 4명 (3명 + 휴직자1명, 대체자1명 제외)",
    "input": BusinessSizeInput(
        event_date="2026-03-06",
        workers=[
            WorkerEntry(worker_type=WorkerType.REGULAR, start_date="2025-01-01"),
            WorkerEntry(worker_type=WorkerType.REGULAR, start_date="2025-01-01"),
            WorkerEntry(worker_type=WorkerType.REGULAR, start_date="2025-01-01"),
            WorkerEntry(worker_type=WorkerType.REGULAR, start_date="2025-01-01", is_on_leave=True),
            WorkerEntry(worker_type=WorkerType.CONTRACT, start_date="2025-06-01", is_leave_replacement=True),
        ],
    ),
    "expected": {
        "regular_worker_count": 4.0,  # 3명 + 휴직자1명 포함, 대체자1명 제외
        "business_size": BusinessSize.UNDER_5,
    },
}
```

### 7.3 케이스 #35: 경계 — 미달일수 1/2 판정

```python
{
    "id": 35,
    "desc": "상시근로자 수 판정 — 미달일수 1/2 경계 (평균 5명이지만 미달일 다수)",
    "input": BusinessSizeInput(
        event_date="2026-03-06",
        workers=[
            # 상시 3명
            WorkerEntry(worker_type=WorkerType.REGULAR, start_date="2025-01-01"),
            WorkerEntry(worker_type=WorkerType.REGULAR, start_date="2025-01-01"),
            WorkerEntry(worker_type=WorkerType.REGULAR, start_date="2025-01-01"),
            # 산정기간 후반에만 근무하는 2명 (중도입사)
            WorkerEntry(worker_type=WorkerType.REGULAR, start_date="2026-02-20"),
            WorkerEntry(worker_type=WorkerType.REGULAR, start_date="2026-02-20"),
        ],
    ),
    "expected": {
        "business_size": BusinessSize.UNDER_5,  # or OVER_5 — 미달일수 비율에 따라
        # 구체적 expected는 가동일수 대비 미달일수로 결정
    },
}
```

### 7.4 케이스 #36: 특정요일 + 교대근무 혼합

```python
{
    "id": 36,
    "desc": "상시근로자 수 판정 — 특정요일 출근자 + 교대근무 혼합",
    "input": BusinessSizeInput(
        event_date="2026-03-06",
        workers=[
            WorkerEntry(worker_type=WorkerType.REGULAR, start_date="2025-01-01"),
            WorkerEntry(worker_type=WorkerType.REGULAR, start_date="2025-01-01"),
            WorkerEntry(worker_type=WorkerType.SHIFT, start_date="2025-01-01"),  # 교대: 비번일도 포함
            WorkerEntry(worker_type=WorkerType.DAILY, start_date="2025-01-01",
                        specific_work_days=[0, 2, 4]),  # 월·수·금만 출근
            WorkerEntry(worker_type=WorkerType.FOREIGN, start_date="2025-06-01"),
        ],
    ),
    "expected": {
        "business_size": BusinessSize.OVER_5,  # 상시 5명 이상
        # 교대근무자 비번일 포함, 특정요일 출근자는 해당일만 산입
    },
}
```

---

## 8. 에러 처리 및 경계 조건

### 8.1 입력 검증

| 조건 | 처리 |
|------|------|
| `event_date` 빈 문자열 | warnings에 "사유 발생일 미입력" 추가, 오늘 날짜 사용 |
| `workers` 빈 리스트 | regular_worker_count = 0, UNDER_5 반환 |
| `start_date` 누락 | 해당 근로자 제외 + warnings |
| `start_date > event_date` | 산정기간에 포함되지 않으므로 자동 제외 |
| 가동일수 = 0 | ZeroDivisionError 방지: regular_worker_count = 0 |

### 8.2 월말 보정

```
event_date = 2026-03-31
→ period_start = 2026-02-28 (2월은 28일까지)
→ period_end   = 2026-03-30

event_date = 2026-01-31
→ period_start = 2025-12-31
→ period_end   = 2026-01-30
```

`dateutil.relativedelta` 대신 표준 라이브러리만 사용 (의존성 최소화):
```python
from datetime import date, timedelta
# period_end = event_date - timedelta(days=1)
# period_start = (event_date.month 기준 1개월 전 계산, 월말 보정 포함)
```

### 8.3 동거친족 판별

```python
# is_family_only_business=True 일 때:
#   1. 모든 workers 중 FAMILY가 아닌 근로자가 1명이라도 있으면
#      → is_family_only = False로 재판정 (가족근로자도 포함)
#   2. 모두 FAMILY이면 → 전원 제외 (근기법 미적용)
has_non_family = any(w.worker_type != WorkerType.FAMILY for w in workers)
```

---

## 9. 출력 포맷 예시

### 9.1 breakdown 구조

```python
{
    "산정기간": "2026-02-06 ~ 2026-03-05 (28일)",
    "가동일수": "20일 (토·일 제외)",
    "연인원 합계": "160명",
    "상시근로자 수": "160 ÷ 20 = 8.0명",
    "판정 결과": "5인 이상 사업장 (OVER_5)",
    "5인 미만 일수": "0일 / 20일 (0.0%)",
    "법 적용 여부": "적용 (미달일수 < 산정기간의 1/2)",
    "포함 근로자": "8명 (통상 5, 기간제 1, 교대 1, 외국인 1)",
    "제외 근로자": "1명 (휴직대체자 1)",
}
```

### 9.2 formulas 예시

```python
[
    "[상시근로자 수] 연인원(160명) ÷ 가동일수(20일) = 8.0명",
    "[판정] 8.0명 ≥ 5인 → 5인 이상 사업장",
    "[법 적용] 5인 미만 일수(0일) < 가동일수의 1/2(10일) → 근로기준법 적용",
]
```

---

## 10. 의존성

- 외부 라이브러리 추가 없음 (표준 라이브러리 `datetime` 만 사용)
- `dateutil` 사용하지 않음 — 월 단위 역산은 직접 구현
- 기존 `BusinessSize` enum 변경 없음
