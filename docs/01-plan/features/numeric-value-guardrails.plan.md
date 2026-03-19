# Plan: 숫자 설정값 LLM 판단 방지 (numeric-value-guardrails)

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | numeric-value-guardrails |
| 작성일 | 2026-03-09 |
| 예상 기간 | 1-2일 |
| 영향 범위 | analyzer.py, pipeline.py, prompts.py |

### Value Delivered

| 관점 | 내용 |
|------|------|
| **Problem** | LLM이 사용자가 명시하지 않은 숫자값(근로시간, 임금액, 기준연도 등)을 추론/환각하여 잘못된 계산 결과 생성 |
| **Solution** | LLM 추출값에 명시적 출처 구분(사용자 원문 vs 추론) + 범위 검증 + 추론값은 missing_info로 전환 |
| **Function UX Effect** | 사용자가 말하지 않은 숫자는 계산에 사용하지 않고 되묻기 → 계산 정확도와 신뢰도 향상 |
| **Core Value** | "숫자는 사용자가 제공한 것만 사용한다" 원칙 확립으로 법률 계산기 신뢰성 보장 |

---

## 1. 현황 분석

### 1.1 문제 정의

현재 파이프라인에서 LLM(Claude)이 숫자가 포함된 설정값을 **직접 판단/추론**하는 곳이 다수 존재한다.
법률 계산기의 결과는 입력 숫자에 민감하므로, LLM이 환각하거나 잘못 추론한 숫자 하나가 전체 계산 결과를 틀리게 만든다.

### 1.2 현재 문제 지점

#### (A) 맥락 추론 허용 — `prompts.py:99`
```
5. 맥락 추론 허용: "하루 10시간 주5일" → daily_work_hours=8, weekly_overtime_hours=10
```
- LLM이 "10시간"에서 소정근로 8h + 연장 2h를 **스스로 계산**
- 사용자가 "소정근로 8시간"이라고 명시하지 않았는데 LLM이 8을 가정
- 실제로는 소정근로가 6시간, 7시간일 수도 있음

#### (B) 기준연도 추론 — `prompts.py:66-68`
```json
"reference_year": {
    "description": "계산 기준 연도. 입사일 또는 문맥에서 추론. 미지정 시 현재 연도."
}
```
- LLM이 문맥에서 연도를 추론 → 최저임금, 보험요율 등 연도별 상수가 달라짐
- 2025 vs 2026 최저임금 차이: 10,030원 vs 10,320원

#### (C) 환각 보호 범위 부족 — `pipeline.py:350-362`
```python
# use_minimum_wage 최우선: LLM이 wage_amount를 환각해도 법정 최저임금 강제 적용
if params.get("use_minimum_wage"):
    amount = MINIMUM_HOURLY_WAGE[ref_year]   # ← 보호됨
else:
    amount = params.get("wage_amount")        # ← LLM값 그대로 사용
```
- `use_minimum_wage` 경우만 보호, 나머지 숫자 필드는 LLM 출력 그대로 사용
- `weekly_overtime_hours`, `daily_work_hours`, `arrear_amount` 등 **검증 없음**

#### (D) 기본값 무조건 적용 — `pipeline.py:364-369`
```python
weekly_days = params.get("weekly_work_days", 5)   # 사용자가 안 말해도 5일
daily_hours = 8.0                                  # 사용자가 안 말해도 8시간
```
- 사용자가 근무일수를 명시하지 않으면 주5일/8시간 **자동 가정**
- 파트타임(주3일, 6시간) 사용자의 경우 완전히 잘못된 계산

---

## 2. 목표

### 2.1 핵심 원칙
> **"숫자는 사용자가 명시적으로 제공한 것만 사용한다. 추론하지 않는다."**

### 2.2 구체적 목표

| # | 목표 | 측정 기준 |
|---|------|----------|
| G1 | LLM이 사용자 원문에 없는 숫자를 추출하지 않음 | 추론된 숫자 → missing_info로 전환 |
| G2 | 사용자 미제공 숫자에 기본값을 자동 적용하지 않음 | 기본값 적용 시 missing_info에 포함 |
| G3 | LLM 추출 숫자에 범위 검증 적용 | 비현실적 값 감지 및 거부 |
| G4 | 기준연도는 현재 연도를 기본값으로 사용 | LLM 추론 제거 |

---

## 3. 변경 범위

### 3.1 파일별 변경 사항

| 파일 | 변경 내용 | 우선순위 |
|------|----------|---------|
| `app/templates/prompts.py` | 분석 규칙 5번 삭제/수정, 숫자 추론 금지 지시 추가 | P0 |
| `app/core/analyzer.py` | 숫자 범위 검증 함수 추가 | P0 |
| `app/core/pipeline.py` | 기본값 자동 적용 제거, missing_info 반환 로직 | P1 |
| `chatbot.py` (pipeline 내 `_run_calculator`) | 동일한 기본값 제거 적용 | P1 |

### 3.2 변경하지 않는 것

| 항목 | 이유 |
|------|------|
| `wage_calculator/constants.py` | 코드 상수는 LLM이 아닌 코드가 사용 → 문제 없음 |
| `wage_calculator/calculators/*` | 계산 로직 자체는 정확 → 입력만 보호하면 됨 |
| `use_minimum_wage` 로직 | 이미 올바르게 작동 중 |
| 날짜 추론/보정 로직 | `_correct_date_year()`는 유효한 보정이므로 유지 |

---

## 4. 구현 전략

### 4.1 Phase 1: 프롬프트 수정 (P0)

`ANALYZER_SYSTEM`의 분석 규칙을 수정:

**현재 (삭제 대상):**
```
5. 맥락 추론 허용: "하루 10시간 주5일" → daily_work_hours=8, weekly_overtime_hours=10
```

**변경:**
```
5. 숫자 추론 금지: 사용자가 명시적으로 말한 숫자만 추출하세요.
   - "하루 10시간 주5일" → daily_work_hours는 추출하지 마세요 (소정근로시간 불명).
     weekly_total_hours=50 추출 가능 (10×5). missing_info에 "1일 소정근로시간" 추가.
   - "월급 250만원" → wage_amount=2500000 (명시적 → OK)
   - "주 3일 근무" → weekly_work_days=3 (명시적 → OK)
   - 사용자가 말하지 않은 숫자를 가정하거나 계산하지 마세요.
```

`reference_year` 설명 수정:
```json
"reference_year": {
    "description": "계산 기준 연도. 사용자가 명시한 경우만 설정. 미설정 시 시스템이 현재 연도 자동 적용."
}
```

### 4.2 Phase 2: 숫자 검증 레이어 (P0)

`analyzer.py`에 `_validate_numeric_params()` 추가:

```python
NUMERIC_RANGES = {
    "wage_amount":           (0, 100_000_000),    # 0 ~ 1억원
    "monthly_wage":          (0, 100_000_000),
    "annual_wage":           (0, 1_200_000_000),   # 0 ~ 12억원
    "daily_work_hours":      (1, 24),
    "weekly_work_days":      (1, 7),
    "weekly_overtime_hours":  (0, 52),             # 법정 한도 고려
    "weekly_night_hours":     (0, 56),             # 8h × 7일
    "weekly_holiday_hours":   (0, 16),             # 8h × 2일
    "notice_days_given":     (0, 365),
    "parental_leave_months": (0, 24),
    "arrear_amount":         (0, 10_000_000_000),  # 0 ~ 100억원
    "reference_year":        (2020, 2030),
}
```

범위 밖 값은 해당 키를 `extracted_info`에서 제거하고 `missing_info`에 추가.

### 4.3 Phase 3: 기본값 자동 적용 제거 (P1)

`pipeline.py`의 `_run_calculator()` 수정:

**현재:**
```python
weekly_days = params.get("weekly_work_days", 5)   # 기본 5일
daily_hours = 8.0                                  # 기본 8시간
```

**변경:**
```python
weekly_days = params.get("weekly_work_days")       # None 허용
daily_hours = params.get("daily_work_hours")       # None 허용
# None이면 WageInput 생성 시 모델 기본값 사용 (models.py에서 관리)
```

`WageInput` / `WorkSchedule` 모델의 기본값은 유지하되, **LLM이 아닌 모델 레벨**에서 관리.
핵심: LLM 레이어에서 "5일이라고 가정"하는 것과, 모델 레이어에서 "미입력 시 기본 5일"은 다른 문제.

---

## 5. 리스크 및 완화

| 리스크 | 영향 | 완화 방안 |
|--------|------|----------|
| missing_info 증가로 사용자 되묻기 빈도 상승 | UX 저하 | 필수 정보만 되묻기, 비필수는 모델 기본값 허용 |
| "하루 10시간" 같은 관용적 표현 처리 불가 | 편의성 저하 | `weekly_total_hours` 필드로 총시간은 추출 허용 |
| 기존 테스트 케이스 영향 | 회귀 | 변경 후 기존 시나리오 재검증 |

---

## 6. 검증 계획

| # | 검증 항목 | 방법 |
|---|----------|------|
| V1 | "하루 10시간 주5일" → daily_work_hours 미추출, missing_info 포함 | 수동 테스트 |
| V2 | "월급 300만원" → wage_amount=3000000 정상 추출 | 수동 테스트 |
| V3 | wage_amount=999999999 → 범위 초과 감지 | 단위 테스트 |
| V4 | reference_year 미제공 → 현재 연도 자동 적용 (코드 레벨) | 단위 테스트 |
| V5 | 기존 32개 CLI 테스트 케이스 통과 | `wage_calculator_cli.py` |

---

## 7. 비변경 사항 (명시적 제외)

- **"만원" → 원 변환** (규칙 7): 유지. 이것은 단위 변환이지 숫자 추론이 아님
- **날짜 보정** (`_correct_date_year`): 유지. 연도 보정은 유효한 규칙
- **`use_minimum_wage` 로직**: 유지. 이미 올바르게 동작
- **계산기 내부 상수 사용**: 변경 불필요. 코드 상수는 LLM 판단이 아님
