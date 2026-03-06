# Plan: 5인미만 사업장 판단 계산기 (business-size-calculator)

## Executive Summary

| 관점 | 내용 |
|------|------|
| **Problem** | 현재 `BusinessSize`는 사용자가 직접 선택하는 enum 값이며, 실제 상시근로자 수를 법적 기준(근로기준법 제11조, 시행령 제7조의2)으로 산정하는 로직이 없다. 잘못된 규모 판단은 가산수당·연차·퇴직금 등 모든 후속 계산에 오류를 전파한다. |
| **Solution** | 근로자 연인원 ÷ 가동일수 공식 기반의 `calc_business_size()` 계산기를 구현하고, 포함/제외 근로자 유형 판별 로직과 법 적용 기준 미달일수 1/2 판정을 자동화한다. |
| **Function UX Effect** | 사용자가 근로자 명단·기간만 입력하면 자동으로 사업장 규모를 판정하여, 기존 19개 계산기의 `business_size` 필드에 정확한 값을 공급한다. |
| **Core Value** | 법적 근거에 기반한 정확한 사업장 규모 판정으로, 5인미만 여부에 따라 달라지는 근로기준법 적용 범위(가산수당, 연차, 해고예고 등)의 정확성을 보장한다. |

---

## 1. 배경 및 목적

### 1.1 현재 상태
- `BusinessSize` enum은 `UNDER_5`, `OVER_5`, `OVER_30`, `OVER_300` 4단계로 구분
- 사용자가 직접 선택하며, 실제 상시근로자 수 산정 로직 없음
- 기존 계산기 7개 이상(overtime, annual_leave, severance, public_holiday, compensatory_leave, flexible_work, legal_hints)이 `business_size` 값에 의존

### 1.2 문제
- 사용자가 상시근로자 수 개념을 모르거나 잘못 판단하는 경우 빈번
- 휴직자·교대근무 비번일·결근자 등의 포함/제외 기준이 복잡
- 법 적용 기준 미달일수 1/2 규칙을 모르는 사용자 다수

### 1.3 목적
근로기준법 시행령 제7조의2에 따른 상시근로자 수 산정 계산기를 구현하여:
1. 정확한 사업장 규모를 자동 판정
2. 기존 계산기에 올바른 `BusinessSize` 값 공급
3. 포함/제외 근로자 유형별 안내 제공

---

## 2. 요구사항

### 2.1 핵심 기능 (Must Have)

| ID | 요구사항 | 우선순위 |
|----|---------|---------|
| FR-01 | 상시근로자 수 산정: 연인원 ÷ 가동일수 공식 | P0 |
| FR-02 | 포함 근로자 유형 판별 (12개 유형) | P0 |
| FR-03 | 제외 근로자 유형 판별 (4개 유형) | P0 |
| FR-04 | 법 적용 기준 미달일수 1/2 판정 | P0 |
| FR-05 | BusinessSize enum 자동 결정 (UNDER_5 / OVER_5 / OVER_30 / OVER_300) | P0 |
| FR-06 | 산정 결과 breakdown (일별 근로자 수, 가동일, 포함/제외 내역) | P1 |
| FR-07 | WageInput 연동: 산정된 BusinessSize를 기존 계산기에 전달 | P1 |

### 2.2 입력 데이터 구조

```python
@dataclass
class WorkerEntry:
    """개별 근로자 정보"""
    worker_type: str          # "통상", "기간제", "단시간", "일용", "교대", "외국인" 등
    start_date: str           # 근로계약 효력발생일 "YYYY-MM-DD"
    end_date: str | None      # 퇴직일 (None이면 재직중)
    is_on_leave: bool         # 휴직 중 여부
    is_leave_replacement: bool  # 휴직대체자 여부
    specific_work_days: list[int] | None  # 특정 요일만 출근 (0=월~6=일, None이면 매일)

@dataclass
class BusinessSizeInput:
    """상시근로자 수 산정 입력"""
    event_date: str           # 법 적용 사유 발생일 "YYYY-MM-DD"
    workers: list[WorkerEntry]  # 근로자 명단
    non_operating_days: list[str] | None  # 비가동일 목록 (None이면 토·일 자동)
    is_family_only_business: bool = False  # 동거친족만 사용하는 사업장 여부
```

### 2.3 출력 데이터 구조

```python
@dataclass
class BusinessSizeResult:
    """상시근로자 수 산정 결과"""
    regular_worker_count: float       # 산정된 상시근로자 수
    business_size: BusinessSize       # 판정된 사업장 규모
    calculation_period: tuple[str, str]  # 산정기간 (시작일, 종료일)
    operating_days: int               # 가동일수
    total_headcount: int              # 연인원 합계
    daily_counts: dict[str, int]      # 일별 근로자 수
    included_workers: list[dict]      # 포함된 근로자 내역
    excluded_workers: list[dict]      # 제외된 근로자 내역
    below_threshold_days: int         # 기준 미달 일수
    is_law_applicable: bool           # 법 적용 여부 (미달일수 < 산정기간/2)
    breakdown: dict                   # 상세 내역
    formulas: list[str]              # 계산식
    legal_basis: list[str]           # 법적 근거
    warnings: list[str]             # 주의사항
```

---

## 3. 계산 로직 설계

### 3.1 핵심 공식

```
상시근로자 수 = 산정기간(1개월) 연인원 ÷ 산정기간 가동일수
```

### 3.2 산정 절차

```
1. 산정기간 결정: event_date 전 역일상 1개월
2. 가동일수 집계: 산정기간 내 실가동일 (비가동일 제외, 단 비가동일 실근무 시 포함)
3. 일별 근로자 수 집계:
   a. 각 근로자의 근로계약 효력발생일~종료일 확인
   b. 포함 유형: 통상, 기간제, 단시간, 휴직자, 결근자, 교대(비번일 포함), 외국인 등
   c. 제외 유형: 휴직대체자, 해외현지법인 소속, 동거친족만 사업장의 친족
   d. 특정요일 출근자: 해당 가동일에만 산입
4. 연인원 합산
5. 상시근로자 수 = 연인원 ÷ 가동일수
6. BusinessSize 결정: <5 → UNDER_5, <30 → OVER_5, <300 → OVER_30, ≥300 → OVER_300
7. 법 적용 기준 미달일수 판정: 일별 근로자 수 < 5인 날이 산정기간의 1/2 미만이면 법 적용
```

### 3.3 포함/제외 규칙 매트릭스

| 유형 | 포함 | 조건 |
|------|------|------|
| 통상/기간제/단시간 | O | 고용관계 유지 |
| 휴직자/휴가/결근/징계 | O | 고용관계 유지 |
| 교대근무 비번일 | O | 사회통념상 상시근무 |
| 외국인 근로자 | O | 국적 불문 |
| 가족 근로자 | O | 지휘감독 하 임금 근로 시 |
| 휴직대체자 | X | 중복 산정 방지 |
| 해외 현지법인 소속 | X | 별개 법인격 |
| 동거친족만 사업장 친족 | X | 다른 근로자 1명이라도 있으면 포함 |
| 특정요일 출근자 | 조건부 | 해당 가동일에만 산입 |

---

## 4. 기존 시스템 연동

### 4.1 파일 구조

```
wage_calculator/
├── calculators/
│   └── business_size.py     # 신규: 상시근로자 수 산정 계산기
├── models.py                # WorkerEntry, BusinessSizeInput 추가
├── facade.py                # CALC_TYPES에 "business_size" 추가, calculate() 연동
└── constants.py             # 상시근로자 수 관련 상수 추가
```

### 4.2 facade.py 연동

- `CALC_TYPES`에 `"business_size": "상시근로자 수 판정"` 추가
- `CALC_TYPE_MAP`에 `"사업장규모": ["business_size"]` 추가
- `WageCalculator.calculate()`에서 `business_size` target 시 산정 후 `inp.business_size` 자동 갱신

### 4.3 CLI 테스트

- `wage_calculator_cli.py`에 테스트 케이스 추가 (#33~#36 예상)
  - 케이스 33: 기본 5인 이상 사업장 (직원 10명, 가동일 22일)
  - 케이스 34: 5인 미만 사업장 (직원 3명 + 휴직대체자 1명 제외)
  - 케이스 35: 경계 케이스 — 미달일수 1/2 판정
  - 케이스 36: 특정요일 출근자 + 교대근무 혼합

---

## 5. 기술적 고려사항

### 5.1 설계 원칙
- 기존 `BusinessSize` enum 변경 없이 하위호환 유지
- 독립 실행 가능 (WageInput 없이도 BusinessSizeInput만으로 산정)
- 결과는 기존 `WageResult`와 동일한 breakdown/formulas/warnings 패턴

### 5.2 제약사항
- 파견근로자·도급업체 근로자 판정은 v1에서 제외 (별도 복잡한 판례 필요)
- 복수 사업장 분리 판단은 사용자 입력에 의존 (자동 판별 불가)

### 5.3 법적 근거
- 근로기준법 제11조 (적용 범위)
- 근로기준법 시행령 제7조의2 (상시 사용하는 근로자 수의 산정)

---

## 6. 성공 기준

| 기준 | 목표 |
|------|------|
| 핵심 공식 정확성 | 연인원 ÷ 가동일수 산정 정확 |
| 포함/제외 규칙 | 12개 포함 + 4개 제외 유형 모두 반영 |
| 미달일수 판정 | 1/2 규칙 정확 적용 |
| 기존 계산기 연동 | business_size 판정 결과로 기존 7개+ 계산기 정상 동작 |
| 테스트 통과 | 신규 케이스 #33~#36 전체 통과 |
| 하위호환 | 기존 WageInput.business_size 직접 입력 방식 유지 |
