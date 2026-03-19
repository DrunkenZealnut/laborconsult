# Plan: 상시근로자수 계산모듈 점검 (business-size-calculator-review)

## Executive Summary

| 관점 | 내용 |
|------|------|
| **Problem** | 현재 `business_size.py` 구현에서 일용직(DAILY) 근로자가 매 가동일에 포함되고, 파견·용역·대표자 유형이 WorkerType에 없으며, nodong.kr 기준 10인 threshold 및 규모별 적용법률 안내가 누락되어 있다. |
| **Solution** | nodong.kr/CountLaborCal 계산기를 레퍼런스로 삼아 ① 일용직 처리 로직 보완, ② 누락 WorkerType 3종 추가, ③ 10인 기준 threshold 추가, ④ 규모별 적용법률 안내 기능을 구현한다. |
| **Function UX Effect** | 챗봇에서 "상시근로자수" 질문 시 nodong.kr과 동일한 정확도와 규모별 법률안내를 제공하며, 일용직·파견 등 다양한 고용형태를 정확히 반영한다. |
| **Core Value** | 법적 정확성 100% 달성 — 근로기준법 시행령 제7조의2의 모든 포함/제외 유형을 빠짐없이 반영하고, 규모별 법 적용범위 안내로 실무 활용도를 높인다. |

---

## 1. 배경 및 목적

### 1.1 현재 상태

기존 `business-size-calculator.plan.md`에 따라 `business_size.py` 계산기가 구현 완료됨:
- `calc_business_size()` 함수 (389줄)
- `BusinessSizeResult` 결과 dataclass
- `WorkerType` 8종, `BusinessSize` 4단계 enum
- 테스트 케이스 #33~#36 (4개) 통과
- `facade.py` 연동 완료 (`business_size` target, `CALC_TYPE_MAP["사업장규모"]`)

### 1.2 점검 대상 (nodong.kr/CountLaborCal 비교)

| 항목 | nodong.kr | 현재 구현 | Gap |
|------|-----------|-----------|-----|
| 핵심 공식 | 연인원 ÷ 사업일수 | 연인원 ÷ 가동일수 | ✅ 동일 |
| 산정기간 | 사유발생일 전 1개월 | `_calc_period()` | ✅ 동일 |
| 기본 비가동일 | 토·일 | `DEFAULT_NON_OPERATING_WEEKDAYS = [5, 6]` | ✅ 동일 |
| 5인 미달일수 1/2 판정 | O | `_check_threshold(threshold=5)` | ✅ 동일 |
| **일용직 처리** | 해당 가동일만 포함 | **모든 가동일 포함** (default fallthrough) | ❌ **버그** |
| **파견근로자 제외** | 명시적 제외 | WorkerType에 없음 | ❌ 누락 |
| **외부용역 제외** | 명시적 제외 | WorkerType에 없음 | ❌ 누락 |
| **대표자/비근로자 제외** | 명시적 제외 | WorkerType에 없음 | ❌ 누락 |
| **10인 기준 threshold** | 5인/10인/30인 표시 | 5인만 체크 | ❌ 누락 |
| **규모별 적용법률 안내** | 규모별 노동법 적용표 제공 | 없음 | ❌ 누락 |
| 간편 입력 모드 | 일별 인원수 직접 입력 | 개별 근로자 정보 입력만 | ⚠️ 개선 가능 |

### 1.3 목적

1. **버그 수정**: 일용직(DAILY) 근로자가 매 가동일 포함되는 로직 수정
2. **누락 유형 보완**: 파견·용역·대표자 WorkerType 추가 및 제외 로직 구현
3. **기능 확장**: 10인 기준 threshold 추가, 규모별 적용법률 안내
4. **간편 입력**: 일별 인원수 직접 입력 모드 추가 (선택)

---

## 2. 요구사항

### 2.1 버그 수정 (P0 — Must Fix)

| ID | 요구사항 | 현재 상태 | 수정 내용 |
|----|---------|-----------|-----------|
| BF-01 | 일용직(DAILY) 근로자 가동일 판별 | `_should_include_worker()`에서 DAILY 유형 별도 처리 없이 default fallthrough → 매 가동일 포함됨 | `WorkerEntry`에 `actual_work_dates: list[str]` 필드 추가하거나, 기존 `specific_work_days`(요일) 외에 `actual_work_dates`(특정날짜) 지원 |

### 2.2 누락 유형 추가 (P0 — Must Have)

| ID | 요구사항 | 법적 근거 |
|----|---------|-----------|
| FR-01 | `WorkerType.DISPATCHED` (파견근로자) 추가 → 제외 | 파견법 제2조 — 사용사업주 사업장에서 근로하나 파견사업주 소속 |
| FR-02 | `WorkerType.OUTSOURCED` (외부용역) 추가 → 제외 | 도급업체 소속, 고용관계 없음 |
| FR-03 | `WorkerType.OWNER` (대표자/비근로자) 추가 → 제외 | 근로기준법상 근로자 아님 |

### 2.3 기능 확장 (P1 — Should Have)

| ID | 요구사항 | 설명 |
|----|---------|------|
| FR-04 | `BusinessSize.OVER_10` enum 추가 | 10인 이상 사업장 구분 (취업규칙 작성·신고 의무 등) |
| FR-05 | `_check_threshold()` 다중 threshold | 5인/10인/30인 각각 미달일수 판정 |
| FR-06 | 규모별 적용법률 안내표 생성 | 5인/10인/30인/300인 기준별 적용·미적용 노동법 목록 |
| FR-07 | 간편 입력 모드 (daily_headcount) | `BusinessSizeInput.daily_headcount: dict[str, int]` — 일별 인원수 직접 입력 시 workers 대신 사용 |

### 2.4 테스트 보강 (P1)

| ID | 요구사항 | 설명 |
|----|---------|------|
| TC-01 | 일용직 처리 테스트 (#37) | 일용직 3명 중 2명만 특정 날짜 근무 → 정확한 연인원 |
| TC-02 | 파견·용역·대표자 제외 테스트 (#38) | 10명 중 3명 제외 → 상시 7명 |
| TC-03 | 10인 경계값 테스트 (#39) | 상시 9.5명 → 10인 미만, 취업규칙 의무 없음 |
| TC-04 | 간편 입력 모드 테스트 (#40) | daily_headcount 직접 입력으로 동일 결과 검증 |

---

## 3. 수정 대상 파일

### 3.1 파일별 변경 내역

| 파일 | 변경 유형 | 내용 |
|------|-----------|------|
| `wage_calculator/models.py` | 수정 | ① `WorkerType`에 DISPATCHED/OUTSOURCED/OWNER 추가 ② `BusinessSize`에 OVER_10 추가 ③ `WorkerEntry`에 `actual_work_dates` 필드 추가 ④ `BusinessSizeInput`에 `daily_headcount` 필드 추가 |
| `wage_calculator/calculators/business_size.py` | 수정 | ① `_should_include_worker()`에 DAILY/DISPATCHED/OUTSOURCED/OWNER 처리 추가 ② `_determine_size()`에 OVER_10 분기 추가 ③ `_check_threshold()`에 다중 threshold 지원 ④ `calc_business_size()`에 daily_headcount 간편 입력 분기 추가 ⑤ 규모별 적용법률 안내 함수 신규 |
| `wage_calculator/constants.py` | 수정 | 규모별 적용법률 매핑 상수 추가 |
| `wage_calculator_cli.py` | 수정 | 테스트 케이스 #37~#40 추가 |
| `wage_calculator/facade.py` | 수정 (최소) | BusinessSize.OVER_10 관련 summary 출력 보완 |

### 3.2 변경 영향도

```
models.py (WorkerType/BusinessSize enum 변경)
  ↓ 영향받는 파일
  ├── business_size.py — 직접 사용 (핵심 변경 대상)
  ├── facade.py — _provided_info_to_input() 사업장규모 파싱
  ├── overtime.py — business_size 기반 가산수당 판정
  ├── annual_leave.py — 5인 미만 제외 로직
  ├── dismissal.py — 5인 미만 해고예고 적용
  ├── public_holiday.py — 5인 이상 공휴일 유급 적용
  └── legal_hints.py — 규모별 힌트 생성
```

**하위호환 보장**: 기존 UNDER_5/OVER_5/OVER_30/OVER_300은 그대로 유지. OVER_10은 추가 enum이므로 기존 코드에 영향 없음. 기존 `business_size == BusinessSize.OVER_5` 비교 로직에서 OVER_10이 걸리지 않도록 조건 순서 확인 필요.

---

## 4. 상세 수정 설계

### 4.1 BF-01: 일용직 근로자 처리

**현재 문제** (`business_size.py:273`):
```python
# DAILY 유형에 대한 분기 없이 default로 빠짐
return True, "고용관계 유지"  # 매 가동일에 포함됨 → 잘못된 결과
```

**수정 방안**:
```python
# WorkerEntry에 actual_work_dates 추가
actual_work_dates: Optional[list] = None  # ["YYYY-MM-DD", ...] 실제 출근일

# _should_include_worker()에 DAILY 분기 추가
if worker.worker_type == WorkerType.DAILY:
    if worker.actual_work_dates is not None:
        if target_date.isoformat() not in worker.actual_work_dates:
            return False, "일용직 — 해당일 미출근"
    return True, "일용직 — 출근일"
```

### 4.2 FR-01~03: 누락 WorkerType 추가

```python
class WorkerType(Enum):
    # 기존 8종 유지
    REGULAR        = "통상"
    CONTRACT       = "기간제"
    PART_TIME      = "단시간"
    DAILY          = "일용"
    SHIFT          = "교대"
    FOREIGN        = "외국인"
    FAMILY         = "가족"
    OVERSEAS_LOCAL = "해외현지법인"
    # 신규 3종
    DISPATCHED     = "파견"         # → 제외
    OUTSOURCED     = "용역"         # → 제외
    OWNER          = "대표자"       # → 제외 (비근로자)
```

`_should_include_worker()` 제외 로직:
```python
if worker.worker_type == WorkerType.DISPATCHED:
    return False, "파견근로자 (파견사업주 소속)"
if worker.worker_type == WorkerType.OUTSOURCED:
    return False, "외부용역 (도급업체 소속, 고용관계 없음)"
if worker.worker_type == WorkerType.OWNER:
    return False, "대표자/비근로자 (근로기준법상 근로자 아님)"
```

### 4.3 FR-04~05: 10인 기준 및 다중 threshold

```python
class BusinessSize(Enum):
    UNDER_5  = "5인미만"
    OVER_5   = "5인이상"
    OVER_10  = "10인이상"    # 신규
    OVER_30  = "30인이상"
    OVER_300 = "300인이상"

def _determine_size(regular_count: float) -> BusinessSize:
    if regular_count < 5:
        return BusinessSize.UNDER_5
    if regular_count < 10:
        return BusinessSize.OVER_5
    if regular_count < 30:
        return BusinessSize.OVER_10
    if regular_count < 300:
        return BusinessSize.OVER_30
    return BusinessSize.OVER_300
```

다중 threshold 결과:
```python
threshold_results = {
    5:  _check_threshold(daily_counts, op_count, 5),
    10: _check_threshold(daily_counts, op_count, 10),
    30: _check_threshold(daily_counts, op_count, 30),
}
```

### 4.4 FR-06: 규모별 적용법률 안내

`constants.py`에 추가:
```python
LABOR_LAW_BY_SIZE = {
    5: {
        "적용": ["해고예고(제26조)", "부당해고구제(제28조)", "연장·야간·휴일 가산수당(제56조)",
                 "연차유급휴가(제60조)", "생리휴가(제73조)", "퇴직급여(퇴직급여법)"],
        "미적용_under": ["가산수당 미적용", "연차유급휴가 미적용", "부당해고구제 미적용"],
    },
    10: {
        "적용": ["취업규칙 작성·신고(제93조)", "취업규칙 불이익변경 시 동의(제94조)"],
    },
    30: {
        "적용": ["근로자위원회 설치(근참법 제4조)", "장애인 고용의무(장애인고용법 제28조)"],
    },
    300: {
        "적용": ["고용영향평가(고용정책기본법)", "공정채용법 적용"],
    },
}
```

### 4.5 FR-07: 간편 입력 모드

```python
@dataclass
class BusinessSizeInput:
    event_date: str = ""
    workers: list = field(default_factory=list)
    daily_headcount: Optional[dict] = None   # {"2025-02-03": 10, "2025-02-04": 8, ...}
    non_operating_days: Optional[list] = None
    is_family_only_business: bool = False
```

`calc_business_size()` 분기:
```python
if bsi.daily_headcount is not None:
    # 간편 모드: daily_headcount 직접 사용
    daily_counts = {d: c for d, c in bsi.daily_headcount.items()
                    if period_start <= _parse_date(d) <= period_end}
    # workers 기반 포함/제외 분석 건너뜀
else:
    # 기존 로직: workers 기반 일별 집계
    daily_counts, included, excluded = _count_daily_workers(...)
```

---

## 5. 하위호환 영향 분석

### 5.1 BusinessSize.OVER_10 추가 시 기존 코드 영향

| 파일 | 사용 패턴 | 영향 |
|------|-----------|------|
| `overtime.py` | `business_size == UNDER_5` → 가산 미적용 | ✅ 무영향 (OVER_10은 5인 이상) |
| `annual_leave.py` | `business_size == UNDER_5` → 연차 미적용 | ✅ 무영향 |
| `dismissal.py` | `business_size == UNDER_5` → 해고예고 미적용 | ✅ 무영향 |
| `public_holiday.py` | `business_size in (UNDER_5,)` → 공휴일 미적용 | ✅ 무영향 |
| `legal_hints.py` | 규모별 힌트 생성 | ⚠️ OVER_10 힌트 추가 필요 |
| `facade.py` | `_provided_info_to_input()` 규모 파싱 | ⚠️ "10인 이상" 파싱 추가 필요 |

### 5.2 WorkerType 추가 시 기존 코드 영향

`WorkerType`은 `business_size.py`와 `models.py`에서만 사용 → **다른 계산기에 영향 없음**.

---

## 6. 구현 순서

```
Phase 1 (P0 — 버그 수정 + 누락 유형)
  1. models.py: WorkerType 3종 추가 + WorkerEntry.actual_work_dates 추가
  2. business_size.py: _should_include_worker() DAILY/DISPATCHED/OUTSOURCED/OWNER 처리
  3. wage_calculator_cli.py: TC-01, TC-02 추가 및 검증

Phase 2 (P1 — 기능 확장)
  4. models.py: BusinessSize.OVER_10 추가 + BusinessSizeInput.daily_headcount 추가
  5. business_size.py: _determine_size() OVER_10 분기 + 다중 threshold + 간편 입력
  6. constants.py: LABOR_LAW_BY_SIZE 규모별 적용법률 상수
  7. business_size.py: 규모별 적용법률 안내 함수 + breakdown에 포함
  8. facade.py: OVER_10 파싱 + summary 보완
  9. legal_hints.py: OVER_10 관련 힌트 추가 (해당시)
  10. wage_calculator_cli.py: TC-03, TC-04 추가 및 전체 테스트

Phase 3 (검증)
  11. 기존 테스트 #33~#36 재확인 (하위호환)
  12. 전체 #1~#40 테스트 통과 확인
```

---

## 7. 성공 기준

| 기준 | 목표 |
|------|------|
| BF-01 일용직 처리 | 일용직 근로자가 실제 출근일에만 연인원에 포함 |
| FR-01~03 누락 유형 | 파견·용역·대표자 3종 WorkerType 추가 및 제외 동작 |
| FR-04~05 10인 기준 | BusinessSize.OVER_10 판정 + 다중 threshold 결과 |
| FR-06 적용법률 안내 | 5인/10인/30인/300인별 적용·미적용 법률 목록 출력 |
| FR-07 간편 입력 | daily_headcount 입력 시 nodong.kr과 동일 결과 |
| 하위호환 | 기존 테스트 #1~#36 전체 통과 |
| 신규 테스트 | #37~#40 전체 통과 |

---

## 8. 법적 근거

- 근로기준법 제11조 (적용 범위)
- 근로기준법 시행령 제7조의2 (상시 사용하는 근로자 수의 산정)
- 근로기준법 제26조 (해고예고), 제28조 (부당해고구제), 제56조 (가산수당), 제60조 (연차)
- 근로기준법 제93조 (취업규칙 작성·신고 — 10인 이상)
- 근로자참여 및 협력증진에 관한 법률 제4조 (근로자위원회 — 30인 이상)
- 파견근로자보호 등에 관한 법률 제2조 (파견근로자 정의)
- 참조: https://www.nodong.kr/CountLaborCal
