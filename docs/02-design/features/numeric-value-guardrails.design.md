# Design: 숫자 설정값 LLM 판단 방지 (numeric-value-guardrails)

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | numeric-value-guardrails |
| Plan 참조 | `docs/01-plan/features/numeric-value-guardrails.plan.md` |
| 작성일 | 2026-03-09 |
| 영향 파일 | 4개 (prompts.py, analyzer.py, pipeline.py, chatbot.py) |

---

## 1. 변경 상세 설계

### 1.1 [P0] prompts.py — ANALYZER_SYSTEM 수정

**파일**: `app/templates/prompts.py`

#### 변경 1: 분석 규칙 5번 교체 (line 99-100)

**Before:**
```
5. 맥락 추론 허용: "하루 10시간 주5일" → daily_work_hours=8, weekly_overtime_hours=10
   (소정근로 8h 초과분 = 연장 2h × 5일 = 10h)
```

**After:**
```
5. 숫자 추론 금지: 사용자가 명시적으로 말한 숫자만 추출하세요.
   - "하루 10시간 주5일" → daily_work_hours와 weekly_overtime_hours를 추출하지 마세요.
     missing_info에 "1일 소정근로시간", "주당 연장근로시간" 추가.
   - "소정근로 8시간, 연장 2시간" → daily_work_hours=8, weekly_overtime_hours=2×근무일수 (명시적 → OK)
   - "월급 250만원" → wage_amount=2500000 (명시적 → OK)
   - "주 3일 근무" → weekly_work_days=3 (명시적 → OK)
   - 사용자가 말하지 않은 숫자를 가정하거나 계산하지 마세요.
```

**설계 근거**:
- "하루 10시간"만으로는 소정근로시간을 알 수 없음 (8h일 수도, 7h일 수도 있음)
- LLM이 "법정 8시간" 가정 → 파트타임/변형근무 사용자에게 오류
- 사용자가 "소정 8시간, 연장 2시간"처럼 명시하면 추출 허용

#### 변경 2: reference_year 설명 수정 (line 66-68)

**Before:**
```json
"reference_year": {
    "type": "integer",
    "description": "계산 기준 연도 (예: 2026). 입사일 또는 문맥에서 추론. 미지정 시 현재 연도.",
}
```

**After:**
```json
"reference_year": {
    "type": "integer",
    "description": "계산 기준 연도 (예: 2026). 사용자가 명시한 경우만 설정하세요. 설정하지 않으면 시스템이 현재 연도를 자동 적용합니다.",
}
```

**설계 근거**:
- LLM이 문맥에서 연도를 추론하면 최저임금/보험요율 등 연도별 상수가 달라짐
- 코드 레벨(`_run_calculator`)에서 이미 `date.today().year` 폴백이 있으므로 LLM 추론 불필요

---

### 1.2 [P0] analyzer.py — 숫자 범위 검증 추가

**파일**: `app/core/analyzer.py`

#### 추가 함수: `_validate_numeric_params()`

```python
# analyzer.py 상단, _correct_date_year() 아래에 추가

NUMERIC_RANGES: dict[str, tuple[float, float]] = {
    "wage_amount":            (1, 100_000_000),
    "monthly_wage":           (1, 100_000_000),
    "annual_wage":            (1, 1_200_000_000),
    "daily_work_hours":       (1, 24),
    "weekly_work_days":       (1, 7),
    "weekly_overtime_hours":  (0, 52),
    "weekly_night_hours":     (0, 56),
    "weekly_holiday_hours":   (0, 16),
    "notice_days_given":      (0, 365),
    "parental_leave_months":  (1, 24),
    "arrear_amount":          (1, 10_000_000_000),
    "reference_year":         (2020, 2030),
}


def _validate_numeric_params(
    extracted: dict,
    missing_info: list[str],
) -> None:
    """LLM이 추출한 숫자 파라미터의 범위를 검증.

    범위 밖 값은 extracted에서 제거하고 missing_info에 사유를 추가한다.
    extracted와 missing_info를 직접 변경(mutate)한다.
    """
    FIELD_LABELS = {
        "wage_amount": "임금액",
        "monthly_wage": "월급",
        "annual_wage": "연봉",
        "daily_work_hours": "1일 소정근로시간",
        "weekly_work_days": "주당 근무일수",
        "weekly_overtime_hours": "주당 연장근로시간",
        "weekly_night_hours": "주당 야간근로시간",
        "weekly_holiday_hours": "주당 휴일근로시간",
        "notice_days_given": "해고예고 일수",
        "parental_leave_months": "육아휴직 개월수",
        "arrear_amount": "체불임금액",
        "reference_year": "기준연도",
    }
    for key, (lo, hi) in NUMERIC_RANGES.items():
        val = extracted.get(key)
        if val is None:
            continue
        try:
            num = float(val)
        except (TypeError, ValueError):
            del extracted[key]
            label = FIELD_LABELS.get(key, key)
            missing_info.append(label)
            continue

        if num < lo or num > hi:
            del extracted[key]
            label = FIELD_LABELS.get(key, key)
            missing_info.append(label)
```

#### 호출 위치: `analyze_intent()` 내 날짜 보정 직후

```python
# 기존: 날짜 보정 (line 88-91)
for date_key in ("start_date", "end_date", "arrear_due_date"):
    if date_key in extracted:
        extracted[date_key] = _correct_date_year(extracted[date_key])

# 추가: 숫자 범위 검증
missing_from_llm = inp.get("missing_info", [])
_validate_numeric_params(extracted, missing_from_llm)

return AnalysisResult(
    requires_calculation=inp.get("requires_calculation", False),
    calculation_types=inp.get("calculation_types", []),
    extracted_info=extracted,
    relevant_laws=inp.get("relevant_laws", []),
    missing_info=missing_from_llm,  # ← 검증 결과가 반영된 리스트
    question_summary=inp.get("question_summary", ""),
)
```

**설계 근거**:
- LLM 환각 방어: `wage_amount=999999999` 같은 비현실적 값 차단
- 검증 실패 시 해당 필드를 `extracted`에서 제거 → 다운스트림에서 `_compute_missing_info()`가 재계산
- `missing_info`에 추가하면 후속 follow-up 질문 로직이 자동으로 되묻기 수행
- mutate 방식을 사용하여 새 dict/list 생성 비용 절약

---

### 1.3 [P1] pipeline.py — `_run_calculator()` 기본값 제거

**파일**: `app/core/pipeline.py`

#### 변경: 기본값 5일/8시간 자동 적용 제거 (line 364-369)

**Before:**
```python
weekly_days = params.get("weekly_work_days", 5)
weekly_total = params.get("weekly_total_hours")
if weekly_total and weekly_days:
    daily_hours = weekly_total / weekly_days
else:
    daily_hours = 8.0
```

**After:**
```python
weekly_days = params.get("weekly_work_days")
weekly_total = params.get("weekly_total_hours")
if weekly_total and weekly_days:
    daily_hours = weekly_total / weekly_days
else:
    daily_hours = params.get("daily_work_hours")

# None → WorkSchedule 모델 기본값 (8.0h, 5일) 사용
# 핵심: LLM이 아닌 모델 레벨에서 기본값 관리
```

```python
schedule = WorkSchedule(
    daily_work_hours=daily_hours if daily_hours is not None else 8.0,
    weekly_work_days=weekly_days if weekly_days is not None else 5.0,
    weekly_overtime_hours=params.get("weekly_overtime_hours") or 0,
    weekly_night_hours=params.get("weekly_night_hours") or 0,
    weekly_holiday_hours=params.get("weekly_holiday_work_hours") or 0,
)
```

**설계 근거**:
- 변경 전: LLM 레이어에서 "5일이라 가정" → 가정의 근거가 불명
- 변경 후: `WorkSchedule` 모델의 기본값(8.0, 5.0) 사용 → 기본값의 출처가 명확
- 실질적 계산 결과는 동일하지만, **LLM이 숫자를 결정하는 것이 아님**을 명확히 함
- `_compute_missing_info()`에서 `daily_work_hours`, `weekly_work_days`가 `extracted_info`에 없으면 이미 되묻기 대상이므로, 여기까지 도달했다면 사용자가 정보를 제공했거나 되묻기를 거친 상태

---

### 1.4 [P1] chatbot.py — `_run_calculator()` 동일 수정

**파일**: `chatbot.py`

#### 변경 위치: line 338-345 (pipeline.py와 동일 패턴)

**Before:**
```python
weekly_days = params.get("weekly_work_days", 5)
# ...
    daily_hours = 8.0
```

**After:**
```python
weekly_days = params.get("weekly_work_days")
# ...
    daily_hours = params.get("daily_work_hours")
```

WorkSchedule 생성도 pipeline.py와 동일하게 수정.

**참고**: `chatbot.py`의 `_run_calculator`는 `pipeline.py`와 중복 코드이나, 이 feature에서는 리팩터링하지 않고 동일 패턴만 적용한다 (scope 제한).

---

## 2. 데이터 흐름

### 2.1 변경 전 흐름

```
사용자: "하루 10시간 주5일 일해요"
    ↓
Analyzer LLM:
    daily_work_hours = 8    ← LLM이 "법정 8시간" 가정
    weekly_overtime_hours = 10  ← LLM이 (10-8)×5 계산
    ↓
pipeline._run_calculator():
    weekly_days = 5          ← 코드 기본값
    daily_hours = 8.0        ← 코드 기본값
    ↓
계산기: 잘못된 입력으로 계산 수행
```

### 2.2 변경 후 흐름

```
사용자: "하루 10시간 주5일 일해요"
    ↓
Analyzer LLM:
    weekly_work_days = 5     ← 명시적 (OK)
    missing_info = ["1일 소정근로시간", "주당 연장근로시간"]  ← 추론 금지
    ↓
_validate_numeric_params(): (범위 검증 통과)
    ↓
_compute_missing_info():
    missing = ["1일 소정근로시간", "주당 연장근로시간"]
    ↓
compose_follow_up():
    "정확한 계산을 위해 추가 정보가 필요합니다:
     - 1일 소정근로시간
     - 주당 연장근로시간"
    ↓
사용자: "소정근로 8시간이에요"
    ↓
Analyzer LLM:
    daily_work_hours = 8     ← 명시적 (OK)
    ↓
merge_with_pending → 계산 실행
```

---

## 3. 구현 순서

| # | 파일 | 작업 | 의존성 |
|---|------|------|--------|
| 1 | `app/templates/prompts.py` | 규칙 5 교체, reference_year 설명 수정 | 없음 |
| 2 | `app/core/analyzer.py` | `_validate_numeric_params()` 추가 + 호출 | 없음 |
| 3 | `app/core/pipeline.py` | `_run_calculator()` 기본값 제거 | 없음 |
| 4 | `chatbot.py` | `_run_calculator()` 기본값 제거 | 없음 |

모든 변경은 독립적이므로 순서 무관하나, 테스트 시 1→2→3→4 순서 권장.

---

## 4. 영향 받지 않는 영역

| 영역 | 이유 |
|------|------|
| `wage_calculator/constants.py` | 코드 상수 — LLM 접근 없음 |
| `wage_calculator/calculators/*` | 계산 로직 — 입력만 보호하면 됨 |
| `wage_calculator/models.py` | `WorkSchedule` 기본값(8.0, 5.0) 유지 |
| `_correct_date_year()` | 날짜 보정 — 유효한 규칙 |
| `use_minimum_wage` 로직 | 이미 올바르게 동작 |
| `_compute_missing_info()` | 코드 기반 필수 필드 판정 — 변경 불필요 |
| `compose_follow_up()` | 되묻기 생성 — 변경 불필요 |
| ANALYZER_SYSTEM 규칙 6 (`"5인 미만"→business_size`) | enum 매핑 — 숫자 추론이 아님 |
| ANALYZER_SYSTEM 규칙 7 (`"만원"→원 변환`) | 단위 변환 — 숫자 추론이 아님 |
| ANALYZER_SYSTEM 규칙 8 (`use_minimum_wage`) | 올바르게 동작 중 |
| ANALYZER_SYSTEM 규칙 9 (날짜 해석) | 날짜 보정은 별도 로직 |

---

## 5. 테스트 시나리오

| # | 입력 | 기대 결과 | 검증 대상 |
|---|------|----------|----------|
| T1 | "하루 10시간 주5일" | `daily_work_hours` 미추출, `missing_info`에 "1일 소정근로시간" | 프롬프트 규칙 5 |
| T2 | "소정근로 8시간, 연장 2시간, 주5일" | `daily_work_hours=8`, `weekly_overtime_hours=10` 추출 | 명시적 값 추출 |
| T3 | "월급 300만원" | `wage_amount=3000000` 정상 추출 | 만원 변환 유지 |
| T4 | LLM이 `wage_amount=999999999` 반환 | 범위 초과 → 제거, `missing_info`에 "임금액" 추가 | 범위 검증 |
| T5 | `reference_year` 미제공 | 코드에서 `date.today().year` 적용 | reference_year 폴백 |
| T6 | `daily_work_hours=30` (비현실적) | 범위 초과(max 24) → 제거 | 범위 검증 |
| T7 | "최저임금으로 주5일 8시간" | `use_minimum_wage=true`, 시스템이 최저임금 적용 | 기존 로직 유지 |
| T8 | 기존 32개 CLI 테스트 | 모두 통과 | 회귀 없음 |
