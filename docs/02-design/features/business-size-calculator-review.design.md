# Design: 상시근로자수 계산모듈 점검 (business-size-calculator-review)

> Plan 참조: `docs/01-plan/features/business-size-calculator-review.plan.md`

---

## 1. 변경 개요

| 구분 | 내용 |
|------|------|
| 대상 | `wage_calculator/` 패키지 — 상시근로자 수 산정 계산기 |
| 유형 | 버그 수정 + 누락 유형 보완 + 기능 확장 |
| 변경 파일 | 5개 (models.py, business_size.py, constants.py, facade.py, wage_calculator_cli.py) |
| 하위호환 | 기존 `== UNDER_5` 비교 패턴 무영향 확인 완료 |

---

## 2. 데이터 모델 변경

### 2.1 WorkerType enum 추가 (`models.py`)

**현재**: 8종 (REGULAR ~ OVERSEAS_LOCAL)
**변경 후**: 11종 (+3)

```python
class WorkerType(Enum):
    # 기존 8종 — 변경 없음
    REGULAR        = "통상"
    CONTRACT       = "기간제"
    PART_TIME      = "단시간"
    DAILY          = "일용"
    SHIFT          = "교대"
    FOREIGN        = "외국인"
    FAMILY         = "가족"
    OVERSEAS_LOCAL = "해외현지법인"
    # ── 신규 3종 (제외 대상) ──
    DISPATCHED     = "파견"       # 파견법 제2조: 파견사업주 소속
    OUTSOURCED     = "용역"       # 도급업체 소속, 고용관계 없음
    OWNER          = "대표자"     # 근로기준법상 근로자 아님
```

**영향 범위**: `WorkerType`은 `business_size.py`의 `_should_include_worker()`와 `_count_daily_workers()`에서만 사용. 다른 계산기에서 WorkerType을 참조하는 곳 없음 → **무영향**.

### 2.2 BusinessSize enum 추가 (`models.py`)

**현재**: 4단계 (UNDER_5, OVER_5, OVER_30, OVER_300)
**변경 후**: 5단계 (+OVER_10)

```python
class BusinessSize(Enum):
    UNDER_5  = "5인미만"
    OVER_5   = "5인이상"
    OVER_10  = "10인이상"     # ← 신규
    OVER_30  = "30인이상"
    OVER_300 = "300인이상"
```

**하위호환 검증 — 기존 코드 전수 조사**:

| 파일 | 비교 패턴 | OVER_10 영향 | 판정 |
|------|-----------|-------------|------|
| `overtime.py:54,164` | `== UNDER_5` → 가산 미적용 | OVER_10은 UNDER_5 아님 | ✅ 무영향 |
| `annual_leave.py:74` | `== UNDER_5` → 연차 미적용 | 동일 | ✅ 무영향 |
| `dismissal.py` | `== UNDER_5` → 해고예고 미적용 | 동일 | ✅ 무영향 |
| `comprehensive.py:165,196,295,331` | `== UNDER_5` | 동일 | ✅ 무영향 |
| `compensatory_leave.py:51` | `== UNDER_5` | 동일 | ✅ 무영향 |
| `flexible_work.py:72` | `== UNDER_5` | 동일 | ✅ 무영향 |
| `severance.py:199` | `== UNDER_5` | 동일 | ✅ 무영향 |
| `public_holiday.py:108-117` | 순차 체크: UNDER_5 → OVER_300 → OVER_30 → else | OVER_10은 else로 진입 → OVER_5와 동일 처리 | ✅ 무영향 |
| `legal_hints.py:166,228` | `== UNDER_5` | 동일 | ✅ 무영향 |
| `facade.py:602-605` | "5인 미만" → UNDER_5, else → OVER_5 | ⚠️ 수정 필요 | 아래 참조 |

**핵심 포인트**: 기존 모든 계산기는 `== UNDER_5` 패턴만 사용하므로, OVER_10 추가 시 기존 로직에 영향 없음. 단, `facade.py`의 `_provided_info_to_input()` 규모 파싱만 확장 필요.

### 2.3 WorkerEntry 필드 추가 (`models.py`)

```python
@dataclass
class WorkerEntry:
    worker_type: WorkerType = WorkerType.REGULAR
    start_date: str = ""
    end_date: Optional[str] = None
    is_on_leave: bool = False
    is_leave_replacement: bool = False
    specific_work_days: Optional[list] = None
    name: str = ""
    # ── 신규 필드 ──
    actual_work_dates: Optional[list] = None  # ["YYYY-MM-DD", ...] 일용직 실제 출근일
```

**설계 근거**: 기존 `specific_work_days`는 "매주 화·목·금" 같은 요일 패턴용이고, `actual_work_dates`는 일용직처럼 특정 날짜에만 근무하는 케이스용. 두 필드는 독립적으로 사용.

### 2.4 BusinessSizeInput 필드 추가 (`models.py`)

```python
@dataclass
class BusinessSizeInput:
    event_date: str = ""
    workers: list = field(default_factory=list)
    non_operating_days: Optional[list] = None
    is_family_only_business: bool = False
    # ── 신규 필드 ──
    daily_headcount: Optional[dict] = None  # {"2025-02-03": 10, ...} 간편 입력
```

**설계 근거**: nodong.kr처럼 일별 인원수만 직접 입력하는 간편 모드 지원. `daily_headcount`가 있으면 `workers` 대신 직접 사용.

---

## 3. business_size.py 변경 상세

### 3.1 BF-01: `_should_include_worker()` 일용직 처리 (버그 수정)

**위치**: `business_size.py:234-283`

**현재 흐름** (line 268 이후):
```
specific_work_days 체크 → is_on_leave → SHIFT → FOREIGN → FAMILY → default: True
```
DAILY 유형이 별도 분기 없이 default `True`로 빠짐 → 매 가동일에 포함됨 (버그)

**수정**: line 268 (`specific_work_days` 체크) 직후, default 도달 전에 DAILY 분기 삽입

```python
    # 5. 특정요일 출근자 → 해당 요일에만 포함
    if worker.specific_work_days is not None:
        if target_date.weekday() not in worker.specific_work_days:
            return False, "특정요일 출근자 — 해당 요일 아님"

    # ── [신규] 5.5. 일용직 → actual_work_dates 기반 판별 ──
    if worker.worker_type == WorkerType.DAILY:
        if worker.actual_work_dates is not None:
            if target_date.isoformat() not in worker.actual_work_dates:
                return False, "일용직 — 해당일 미출근"
            return True, "일용직 — 출근일"
        # actual_work_dates 미입력 시: 기존 동작 유지 (매일 포함)
        # → warnings에서 안내
        return True, "일용직 — 출근일 정보 미입력 (매일 포함 처리)"

    # 6. 나머지 ...
```

**`actual_work_dates` 미입력 시 동작**:
- 기존과 동일하게 매 가동일 포함 (하위호환)
- `warnings`에 "일용직 '{name}': 실제 출근일(actual_work_dates) 미입력으로 매 가동일 포함 처리" 추가
- 기존 테스트 #33~#36에서 DAILY 유형을 사용하지 않으므로 테스트 호환 유지

### 3.2 FR-01~03: `_should_include_worker()` 제외 유형 추가

**위치**: line 256 (`is_leave_replacement` 체크) 직후, line 260 (`OVERSEAS_LOCAL` 체크) 직후에 삽입

```python
    # 2. 휴직대체자 → 제외
    if worker.is_leave_replacement:
        return False, "휴직대체자 (중복 산정 방지)"

    # 3. 해외현지법인 → 제외
    if worker.worker_type == WorkerType.OVERSEAS_LOCAL:
        return False, "해외 현지법인 소속 (별개 법인격)"

    # ── [신규] 3.5. 파견·용역·대표자 → 제외 ──
    if worker.worker_type == WorkerType.DISPATCHED:
        return False, "파견근로자 (파견사업주 소속, 파견법 제2조)"
    if worker.worker_type == WorkerType.OUTSOURCED:
        return False, "외부용역 (도급업체 소속, 고용관계 없음)"
    if worker.worker_type == WorkerType.OWNER:
        return False, "대표자/비근로자 (근로기준법상 근로자 아님)"

    # 4. 동거친족만 사업장 ...
```

**삽입 위치 결정 근거**: 제외 유형은 early return으로 처리하므로, 기존 OVERSEAS_LOCAL 직후에 배치. 동거친족 판별(step 4)이나 specific_work_days 판별(step 5)보다 먼저 평가되어야 함.

### 3.3 `_count_daily_workers()` — `has_non_family` 판별 보완

**위치**: `business_size.py:293-298`

**현재**:
```python
has_non_family = any(
    w.worker_type != WorkerType.FAMILY
    for w in workers
    if not w.is_leave_replacement and w.worker_type != WorkerType.OVERSEAS_LOCAL
)
```

**변경**: 신규 제외 유형도 필터에 추가

```python
_EXCLUDED_TYPES = {WorkerType.OVERSEAS_LOCAL, WorkerType.DISPATCHED,
                   WorkerType.OUTSOURCED, WorkerType.OWNER}

has_non_family = any(
    w.worker_type != WorkerType.FAMILY
    for w in workers
    if not w.is_leave_replacement and w.worker_type not in _EXCLUDED_TYPES
)
```

### 3.4 FR-04: `_determine_size()` — OVER_10 분기 추가

**위치**: `business_size.py:354-362`

**변경**:
```python
def _determine_size(regular_count: float) -> BusinessSize:
    if regular_count < 5:
        return BusinessSize.UNDER_5
    if regular_count < 10:
        return BusinessSize.OVER_5
    if regular_count < 30:
        return BusinessSize.OVER_10     # ← 신규
    if regular_count < 300:
        return BusinessSize.OVER_30
    return BusinessSize.OVER_300
```

### 3.5 FR-05: `_check_threshold()` 다중 threshold 지원

**현재**: 단일 threshold(기본 5) 반환
**변경**: 기존 함수 시그니처 유지 + 다중 threshold 래퍼 추가

```python
# 기존 함수 — 시그니처 변경 없음 (하위호환)
def _check_threshold(
    daily_counts: dict[str, int],
    operating_days: int,
    threshold: int = 5,
) -> tuple[int, int, bool]:
    """... 기존 동작 유지 ..."""

# 신규 함수
def _check_multi_threshold(
    daily_counts: dict[str, int],
    operating_days: int,
) -> dict[int, tuple[int, int, bool]]:
    """5인/10인/30인 기준 각각에 대한 미달일수 1/2 판정"""
    return {
        t: _check_threshold(daily_counts, operating_days, t)
        for t in (5, 10, 30)
    }
```

### 3.6 FR-06: 규모별 적용법률 안내 (`_get_applicable_laws()`)

**신규 함수** (business_size.py 하단에 추가):

```python
def _get_applicable_laws(regular_count: float) -> dict[str, list[str]]:
    """상시근로자 수 기반 적용/미적용 노동법 안내"""
    from ..constants import LABOR_LAW_BY_SIZE

    applicable = []
    not_applicable = []

    for threshold in sorted(LABOR_LAW_BY_SIZE.keys()):
        laws = LABOR_LAW_BY_SIZE[threshold]
        if regular_count >= threshold:
            applicable.extend(laws.get("적용", []))
        else:
            not_applicable.extend(laws.get("적용", []))

    return {"적용": applicable, "미적용": not_applicable}
```

### 3.7 FR-07: `calc_business_size()` — 간편 입력 분기

**위치**: `calc_business_size()` 함수 내 step 3 (`_count_daily_workers` 호출) 직전

```python
    # ── [신규] 간편 입력 모드 분기 ──
    if bsi.daily_headcount is not None:
        # daily_headcount에서 산정기간 내 날짜만 필터
        daily_counts = {}
        for d_str, count in bsi.daily_headcount.items():
            d = _parse_date(d_str)
            if period_start <= d <= period_end and d in operating_dates:
                daily_counts[d.isoformat()] = count

        if not daily_counts:
            warnings.append("간편 입력 데이터 중 산정기간 내 날짜가 없습니다")
            daily_counts = {d.isoformat(): 0 for d in operating_dates}

        included, excluded = [], []
        op_count = len(daily_counts)
    else:
        # 3. 기존 로직: 일별 근로자 수 집계
        daily_counts, included, excluded = _count_daily_workers(
            operating_dates, bsi.workers, bsi.is_family_only_business, warnings,
        )
```

### 3.8 `calc_business_size()` — 결과에 다중 threshold + 적용법률 추가

**위치**: formulas 생성 후, breakdown 구성 시

```python
    # [신규] 다중 threshold 판정
    multi_threshold = _check_multi_threshold(daily_counts, op_count)

    # [신규] 규모별 적용법률
    laws = _get_applicable_laws(regular_count)

    # breakdown에 추가
    breakdown["규모별 기준 판정"] = {
        f"{t}인 기준": {
            "미달일수": f"{below_t}일",
            "충족일수": f"{above_t}일",
            "법 적용": "적용" if applicable_t else "미적용",
        }
        for t, (below_t, above_t, applicable_t) in multi_threshold.items()
    }
    breakdown["적용 노동법"] = laws["적용"]
    breakdown["미적용 노동법"] = laws["미적용"]
```

### 3.9 BusinessSizeResult 필드 추가

```python
@dataclass
class BusinessSizeResult(BaseCalculatorResult):
    # 기존 필드 유지
    regular_worker_count: float = 0.0
    business_size: BusinessSize = BusinessSize.UNDER_5
    # ...
    is_law_applicable: bool = False
    # ── 신규 필드 ──
    multi_threshold: dict = field(default_factory=dict)  # {5: (below, above, bool), 10: ..., 30: ...}
    applicable_laws: list = field(default_factory=list)
    not_applicable_laws: list = field(default_factory=list)
```

---

## 4. constants.py 변경

### 4.1 LABOR_LAW_BY_SIZE 추가

**위치**: `DEFAULT_NON_OPERATING_WEEKDAYS` 이후 (line 230 부근)

```python
# ── 규모별 적용 노동법 안내 (근로기준법 시행령 별표) ──────────────────────
LABOR_LAW_BY_SIZE = {
    5: {
        "적용": [
            "해고예고 (제26조)",
            "부당해고 구제신청 (제28조)",
            "연장·야간·휴일 가산수당 50% (제56조)",
            "연차 유급휴가 (제60조)",
            "생리휴가 (제73조)",
            "퇴직급여 (퇴직급여보장법 제4조)",
        ],
    },
    10: {
        "적용": [
            "취업규칙 작성·신고 의무 (제93조)",
            "취업규칙 불이익변경 동의 (제94조)",
        ],
    },
    30: {
        "적용": [
            "노사협의회 설치 (근로자참여법 제4조)",
            "장애인 고용의무 (장애인고용법 제28조)",
        ],
    },
    300: {
        "적용": [
            "고용영향평가 (고용정책기본법 제13조의2)",
            "공정채용법 적용 (채용절차법 제4조의3)",
        ],
    },
}
```

---

## 5. facade.py 변경

### 5.1 `_provided_info_to_input()` — 규모 파싱 확장

**위치**: `facade.py:600-605`

**현재**:
```python
size_str = info.get("사업장규모", "") or ""
if "5인 미만" in size_str or "5인미만" in size_str:
    biz_size = BusinessSize.UNDER_5
else:
    biz_size = BusinessSize.OVER_5
```

**변경**:
```python
size_str = info.get("사업장규모", "") or ""
if "5인 미만" in size_str or "5인미만" in size_str:
    biz_size = BusinessSize.UNDER_5
elif "300인" in size_str:
    biz_size = BusinessSize.OVER_300
elif "30인" in size_str:
    biz_size = BusinessSize.OVER_30
elif "10인" in size_str:
    biz_size = BusinessSize.OVER_10
else:
    biz_size = BusinessSize.OVER_5
```

**주의**: "300인" 체크를 "30인"보다 먼저 해야 "300인이상"이 "30인"에 매칭되지 않음.

---

## 6. wage_calculator_cli.py 테스트 추가

### 6.1 TC-01: 일용직 실제 출근일 테스트 (#37)

```python
{
    "id": 37,
    "desc": "상시근로자 수 — 일용직 actual_work_dates (3명 중 2명만 특정 날짜 근무)",
    "input": BusinessSizeInput(
        event_date="2025-03-01",
        workers=[
            # 통상 5명 (매일 포함)
            WorkerEntry(name=f"직원{i+1}", worker_type=WorkerType.REGULAR, start_date="2024-01-02")
            for i in range(5)
        ] + [
            # 일용직A: 5일만 근무
            WorkerEntry(
                name="일용A", worker_type=WorkerType.DAILY, start_date="2024-01-02",
                actual_work_dates=["2025-02-03", "2025-02-04", "2025-02-05", "2025-02-06", "2025-02-07"],
            ),
            # 일용직B: 10일 근무
            WorkerEntry(
                name="일용B", worker_type=WorkerType.DAILY, start_date="2024-01-02",
                actual_work_dates=[f"2025-02-{d:02d}" for d in range(3, 15) if date(2025, 2, d).weekday() < 5],
            ),
        ],
    ),
    "targets": ["business_size"],
    # 검증: 연인원 = 5×가동일 + 5 + 10 → 상시근로자 수 ≈ 5.7명 (OVER_5)
    # 일용직이 매일 포함되지 않음을 확인
}
```

### 6.2 TC-02: 파견·용역·대표자 제외 테스트 (#38)

```python
{
    "id": 38,
    "desc": "상시근로자 수 — 파견·용역·대표자 제외 (10명 중 3명 제외 → 상시 7명)",
    "input": BusinessSizeInput(
        event_date="2025-03-01",
        workers=[
            WorkerEntry(name=f"직원{i+1}", worker_type=WorkerType.REGULAR, start_date="2024-01-02")
            for i in range(7)
        ] + [
            WorkerEntry(name="파견F", worker_type=WorkerType.DISPATCHED, start_date="2024-01-02"),
            WorkerEntry(name="용역G", worker_type=WorkerType.OUTSOURCED, start_date="2024-01-02"),
            WorkerEntry(name="대표자H", worker_type=WorkerType.OWNER, start_date="2024-01-02"),
        ],
    ),
    "targets": ["business_size"],
    # 검증: 상시 7.0명, OVER_5, 파견·용역·대표자 제외 목록에 3명
}
```

### 6.3 TC-03: 10인 경계값 테스트 (#39)

```python
{
    "id": 39,
    "desc": "상시근로자 수 — 10인 경계값 (9명 → OVER_5, 취업규칙 의무 없음)",
    "input": BusinessSizeInput(
        event_date="2025-03-01",
        workers=[
            WorkerEntry(name=f"직원{i+1}", worker_type=WorkerType.REGULAR, start_date="2024-01-02")
            for i in range(9)
        ],
    ),
    "targets": ["business_size"],
    # 검증: 상시 9.0명, BusinessSize.OVER_5 (not OVER_10), 취업규칙 의무 없음
}
```

### 6.4 TC-04: 간편 입력 모드 테스트 (#40)

```python
{
    "id": 40,
    "desc": "상시근로자 수 — 간편 입력 (daily_headcount 직접 지정)",
    "input": BusinessSizeInput(
        event_date="2025-03-01",
        daily_headcount={
            # 2025-02-01(토)~2025-02-28(금), 가동일=평일 20일
            f"2025-02-{d:02d}": 8
            for d in range(1, 29)
            if date(2025, 2, d).weekday() < 5  # 평일만
        },
    ),
    "targets": ["business_size"],
    # 검증: 연인원=8×20=160, 상시=8.0명, OVER_5
}
```

---

## 7. 구현 순서 (의존성 기반)

```
Step 1: models.py
  ├── WorkerType: +DISPATCHED, +OUTSOURCED, +OWNER
  ├── BusinessSize: +OVER_10
  ├── WorkerEntry: +actual_work_dates
  └── BusinessSizeInput: +daily_headcount
       ↓ (enum/dataclass 정의 완료)

Step 2: constants.py
  └── +LABOR_LAW_BY_SIZE dict
       ↓ (상수 정의 완료)

Step 3: business_size.py (핵심)
  ├── BusinessSizeResult: +multi_threshold, +applicable_laws, +not_applicable_laws
  ├── _should_include_worker(): +DAILY 분기, +DISPATCHED/OUTSOURCED/OWNER 제외
  ├── _count_daily_workers(): _EXCLUDED_TYPES 필터 보완
  ├── _determine_size(): +OVER_10 분기
  ├── +_check_multi_threshold() 함수
  ├── +_get_applicable_laws() 함수
  └── calc_business_size(): 간편 입력 분기 + 다중 threshold + 적용법률 결과
       ↓ (계산 로직 완료)

Step 4: facade.py
  └── _provided_info_to_input(): 규모 파싱 확장 (300인→30인→10인→5인 순)
       ↓ (연동 완료)

Step 5: wage_calculator_cli.py
  └── 테스트 케이스 #37~#40 추가
       ↓ (검증)

Step 6: 전체 테스트
  ├── 기존 #1~#36 하위호환 확인
  └── 신규 #37~#40 통과 확인
```

---

## 8. 변경 파일별 diff 예상 크기

| 파일 | 추가 | 수정 | 삭제 | 예상 줄 수 |
|------|------|------|------|-----------|
| `models.py` | +4 fields, +3 enum, +1 enum | 0 | 0 | +15줄 |
| `constants.py` | +LABOR_LAW_BY_SIZE | 0 | 0 | +25줄 |
| `business_size.py` | +3 함수, BF-01, FR-01~03 | _determine_size, calc_business_size | 0 | +80줄 |
| `facade.py` | 규모 파싱 분기 | 1 블록 | 0 | +8줄 |
| `wage_calculator_cli.py` | #37~#40 | 0 | 0 | +60줄 |
| **합계** | | | | **~188줄** |

---

## 9. 검증 체크리스트

### 9.1 기능 검증

- [ ] BF-01: DAILY + `actual_work_dates` 지정 시 해당일만 포함
- [ ] BF-01: DAILY + `actual_work_dates=None` 시 매일 포함 (하위호환) + warning
- [ ] FR-01: DISPATCHED → 제외, excluded_workers에 표시
- [ ] FR-02: OUTSOURCED → 제외, excluded_workers에 표시
- [ ] FR-03: OWNER → 제외, excluded_workers에 표시
- [ ] FR-04: 상시 10~29명 → OVER_10 (기존은 OVER_5였음)
- [ ] FR-05: breakdown에 5인/10인/30인 각 threshold 결과 포함
- [ ] FR-06: breakdown에 적용/미적용 법률 목록 포함
- [ ] FR-07: daily_headcount 입력 시 workers 무시하고 직접 계산

### 9.2 하위호환 검증

- [ ] 기존 테스트 #1~#32 (WageInput 기반) 전체 통과
- [ ] 기존 테스트 #33~#36 (BusinessSizeInput 기반) 전체 통과
- [ ] EITC 테스트 #37+ (기존 번호 충돌 시 재번호 매김)
- [ ] `facade.py` from_analysis() 정상 동작

### 9.3 엣지 케이스

- [ ] 빈 workers + daily_headcount=None → 기존 동작 (0명, UNDER_5)
- [ ] daily_headcount 전체가 산정기간 밖 → warning + 0명
- [ ] 모든 근로자가 제외 유형 → 0명, UNDER_5
- [ ] actual_work_dates에 중복 날짜 → 1회만 카운트 (isoformat 비교)

---

## 10. 리스크 및 완화 전략

| 리스크 | 영향 | 완화 |
|--------|------|------|
| OVER_10 추가로 기존 `== OVER_5` 비교하는 코드 | 현재 코드에 `== OVER_5` 비교 없음 (전수 확인) | ✅ 이미 검증됨 |
| 기존 테스트 #37이 EITC 케이스와 충돌 | 테스트 ID 충돌 | 기존 EITC #37을 #41로 이동하거나, business_size 테스트를 #37~#40에 삽입 후 EITC를 #41~로 이동 |
| daily_headcount 날짜가 비가동일 포함 | 실가동일 외 날짜 입력 시 오계산 | operating_dates 교집합 필터로 해결 |
| _provided_info_to_input() "10인" 문자열이 "300인이상" 안에 포함 | 잘못된 파싱 | "300인" → "30인" → "10인" 순서로 체크 |
