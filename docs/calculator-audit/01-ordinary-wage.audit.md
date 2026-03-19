# 통상임금 계산기 감사 시트

## 1. 개요

| 항목 | 내용 |
|------|------|
| 계산기명 | 통상임금 (Ordinary Wage) |
| 코드 파일 | `wage_calculator/calculators/ordinary_wage.py` |
| 함수명 | `calc_ordinary_wage(inp: WageInput) -> OrdinaryWageResult` |
| 적용 법조문 | 근로기준법 시행령 제6조 (통상임금), 대법원 2013다4174 (정기성+일률성), 대법원 2023다302838 (고정성 요건 폐기) |
| 5인 미만 적용 여부 | 적용 (통상임금 산출 자체는 사업장 규모 무관) |

통상임금은 모든 수당 계산(연장/야간/휴일/퇴직금/연차수당 등)의 기반이 되는 핵심 계산기이다. `WageCalculator.calculate()` 호출 시 항상 최초로 실행된다.

---

## 2. 입력 항목

| 필드명(한글) | 필드명(영문) | 타입 | 기본값 | 필수여부 |
|-------------|-------------|------|--------|---------|
| 임금형태 | `wage_type` | `WageType` enum | `MONTHLY` | 필수 |
| 시급 | `hourly_wage` | `Optional[float]` | `None` | 시급제일 때 필수 |
| 일급 | `daily_wage` | `Optional[float]` | `None` | 일급제일 때 필수 |
| 월급(기본급) | `monthly_wage` | `Optional[float]` | `None` | 월급/포괄임금제일 때 필수 |
| 연봉 | `annual_wage` | `Optional[float]` | `None` | 연봉제일 때 필수 |
| 근무형태 | `work_type` | `WorkType` enum | `REGULAR` | 선택 (교대근무 시 필수) |
| 1일 소정근로시간 | `schedule.daily_work_hours` | `float` | `8.0` | 선택 |
| 주 소정근로일수 | `schedule.weekly_work_days` | `float` | `5.0` | 선택 |
| 월 소정근로시간 | `schedule.monthly_scheduled_hours` | `Optional[float]` | `None` | 선택 (명시 시 최우선) |
| 교대근무 월시간 | `schedule.shift_monthly_hours` | `Optional[float]` | `None` | 선택 (교대근무 직접 지정) |
| 고정수당 목록 | `fixed_allowances` | `list[dict]` | `[]` | 선택 |
| 포괄임금 명세 | `comprehensive_breakdown` | `Optional[dict]` | `None` | 포괄임금제일 때 선택 |

### 고정수당(fixed_allowances) 항목 구조

```python
{
    "name": "직책수당",           # 수당명
    "amount": 100000,            # 금액 (원)
    "condition": "없음",          # AllowanceCondition: 없음/근무일수/재직조건/성과조건/최소보장성과
    "is_ordinary": True,         # 명시적 통상임금 포함/제외 (None이면 자동 판단)
    "annual": False,             # True이면 연간 금액 → /12 월환산
    "guaranteed_amount": 50000,  # 최소보장성과 시 보장 금액
}
```

---

## 3. 적용 상수

| 상수명 | 값 | 단위 | 법적 근거 | 코드 위치 |
|-------|-----|------|----------|----------|
| `MONTHLY_STANDARD_HOURS` | 209.0 | 시간/월 | (주40h + 주휴8h) x 52주 / 12월 | constants.py:43 |
| `WEEKS_PER_MONTH` | 4.345 (365/7/12) | 주/월 | 실무 환산 관행 | utils.py:8 |
| `WEEKLY_HOLIDAY_MIN_HOURS` | 15.0 | 시간/주 | 근기법 제18조 (주 15시간 미만 주휴 미발생) | constants.py:50 |
| `SHIFT_MONTHLY_HOURS["4조2교대"]` | 182.5 | 시간/월 | 12h 격일제 실무 기준 | constants.py:89 |
| `SHIFT_MONTHLY_HOURS["3조2교대"]` | 209.0 | 시간/월 | 8h 교대 표준 기준 | constants.py:90 |
| `SHIFT_MONTHLY_HOURS["3교대"]` | 195.5 | 시간/월 | 24/3=8h 교대 월 평균 | constants.py:91 |
| `SHIFT_MONTHLY_HOURS["2교대"]` | 209.0 | 시간/월 | 스케줄별 별도 산정 | constants.py:92 |

---

## 4. 계산 과정 (핵심)

### Step 1: 월 기준시간(base_hours) 결정

> 함수: `_get_base_hours(inp)` (ordinary_wage.py:168-206)

우선순위에 따라 월 기준시간을 결정한다:

**우선순위 1**: `monthly_scheduled_hours` 명시값 (ordinary_wage.py:181)
```
월기준시간 = schedule.monthly_scheduled_hours
```

**우선순위 2**: `shift_monthly_hours` 교대근무 직접 지정 (ordinary_wage.py:185)
```
월기준시간 = schedule.shift_monthly_hours
```

**우선순위 3**: 교대근무 유형별 조회 (ordinary_wage.py:189-197)
```
월기준시간 = SHIFT_MONTHLY_HOURS[교대유형키]  (없으면 209.0)
```
- 매핑: SHIFT_4_2 → "4조2교대", SHIFT_3_2 → "3조2교대", SHIFT_3 → "3교대", SHIFT_2 → "2교대"

**우선순위 4**: 스케줄 기반 자동 계산 (ordinary_wage.py:199-206)
```
주소정근로시간 = 1일소정근로시간 x 주소정근로일수
주휴시간 = min(주소정근로시간 / 5, 8.0)    # 대법원 2022다291153
         (단, 주소정근로시간 < 15.0이면 주휴시간 = 0)
월기준시간 = (주소정근로시간 + 주휴시간) x WEEKS_PER_MONTH
```
- 법적 근거: 근기법 제18조 (주 15시간 미만 주휴 미발생), 대법원 2022다291153 (주휴시간 산정)

### Step 2: 임금형태별 기본 통상임금(monthly_base) 산출

> ordinary_wage.py:43-82

| 임금형태 | 환산 공식 | 코드 위치 |
|---------|----------|----------|
| `HOURLY` (시급) | 월기본급 = 시급 x 월기준시간 | ordinary_wage.py:44-48 |
| `DAILY` (일급) | 시급 = 일급 / 1일소정근로시간; 월기본급 = 시급 x 월기준시간 | ordinary_wage.py:50-57 |
| `MONTHLY` (월급) | 월기본급 = monthly_wage | ordinary_wage.py:59-62 |
| `ANNUAL` (연봉) | 월기본급 = 연봉 / 12 | ordinary_wage.py:64-68 |
| `COMPREHENSIVE` (포괄임금) | breakdown 있으면 base값, 없으면 총액 사용 | ordinary_wage.py:70-78 |

### Step 3: 고정수당 통상임금 포함분 합산

> ordinary_wage.py:84-113, `_resolve_is_ordinary()` (ordinary_wage.py:135-165)

각 수당에 대해 `_resolve_is_ordinary()` 함수로 통상임금 포함 여부를 판단한다:

| condition 값 | 포함 여부 | 판단 근거 | 코드 위치 |
|-------------|----------|----------|----------|
| `"성과조건"` | 제외 | 성과 달성 여부에 따라 변동 → 일률성 불충족 | ordinary_wage.py:147-150 |
| `"최소보장성과"` | 보장분만 포함 | 대법원 2023다302838 — 최소보장 금액만 산입 | ordinary_wage.py:153-156 |
| `"재직조건"` / `"근무일수"` | 포함 | 대법원 2023다302838 — 고정성 요건 폐기 | ordinary_wage.py:159-162 |
| `"없음"` (기본) | 포함 (is_ordinary 미설정 시) | 정기성+일률성 충족 추정 | ordinary_wage.py:165 |

**최소보장 성과급 처리** (ordinary_wage.py:95-98):
```
실제산입액 = min(max(0, 보장금액), 총액)
```

**연간 지급 수당 월환산** (ordinary_wage.py:101):
```
월환산액 = 연간금액 / 12    (annual=True일 때)
```

**수당 합계 산출** (ordinary_wage.py:104):
```
수당합계 += 월환산액    (통상임금 포함 판정 시)
```

### Step 4: 최종 통상시급 산출

> ordinary_wage.py:115-132

```
월통상임금 = 월기본급 + 수당합계
통상시급 = 월통상임금 / 월기준시간
1일통상임금 = 통상시급 x 1일소정근로시간
```

---

## 5. 출력 항목

| 항목명 | 설명 | 단위 |
|-------|------|------|
| `hourly_ordinary_wage` | 통상시급 (소수점 2자리 반올림) | 원/시간 |
| `daily_ordinary_wage` | 1일 통상임금 (원 단위 반올림) | 원/일 |
| `monthly_ordinary_wage` | 월 통상임금 총액 (원 단위 반올림) | 원/월 |
| `monthly_base_hours` | 적용된 월 기준시간 | 시간 |
| `included_items` | 통상임금 포함 항목 목록 | 문자열 리스트 |
| `excluded_items` | 통상임금 제외 항목 목록 | 문자열 리스트 |
| `formula` | 계산식 설명 문자열 | 문자열 |

---

## 6. 예외 처리 / 엣지 케이스

| 조건 | 처리 | 법적 근거 |
|------|------|----------|
| 교대근무 유형이 SHIFT_MONTHLY_HOURS에 없음 | `MONTHLY_STANDARD_HOURS`(209.0) 사용 | ordinary_wage.py:197 |
| 주 소정근로시간 < 15시간 | 주휴시간 = 0 (주휴 미발생) | 근기법 제18조, ordinary_wage.py:203-204 |
| `wage_type` 미확인 (else 분기) | monthly_base = 0.0, formula = "임금 형태 미확인" | ordinary_wage.py:80-82 |
| 성과조건 수당에 is_ordinary=True 명시 | 무시하고 제외 처리 (경고 메시지 반환) | ordinary_wage.py:148-149 |
| 재직조건/근무일수 수당에 is_ordinary=False 명시 | 무시하고 포함 처리 (대법원 판결 우선) | ordinary_wage.py:160-161 |
| 최소보장성과 수당 | guaranteed_amount와 amount 중 작은 값만 산입 | 대법원 2023다302838, ordinary_wage.py:97 |
| 포괄임금제 + breakdown 미제공 | monthly_wage 총액 전체를 기본급으로 사용 | ordinary_wage.py:76-77 |
| hourly/daily/monthly/annual_wage가 None | 0.0으로 처리 | ordinary_wage.py:45, 51, 60, 65 |
| 일급제에서 daily_work_hours 미입력 | 8.0h 기본값 사용 | ordinary_wage.py:52 |
| 분기/반기/연 수당 월환산 | annual=True → /12 (연 단위만 처리) | ordinary_wage.py:101 |

---

## 7. 계산 예시

### 예시 1: 월급제 + 고정수당 (5인 이상, 주 40시간)

**입력**:
- 임금형태: 월급 (MONTHLY)
- 월 기본급: 3,000,000원
- 근무: 1일 8시간, 주 5일
- 고정수당:
  - 직책수당 200,000원/월 (조건 없음)
  - 분기상여금 900,000원/분기 (재직조건)
  - 성과급 500,000원/월 (성과조건)

**계산 과정**:

Step 1 — 월 기준시간:
```
주소정근로 = 8h x 5일 = 40h
주휴시간 = min(40 / 5, 8) = 8h
월기준시간 = (40 + 8) x 4.345 = 208.6h → 반올림 208.6h
```

Step 2 — 기본 통상임금:
```
월기본급 = 3,000,000원
```

Step 3 — 수당 판단:
```
직책수당: 조건 없음 → 통상임금 포함, 200,000원/월
분기상여금: 재직조건 → 대법원 2023다302838에 따라 포함, 900,000 / 3 = 300,000원/월
성과급: 성과조건 → 통상임금 제외
```

Step 4 — 최종 산출:
```
수당합계 = 200,000 + 300,000 = 500,000원
월통상임금 = 3,000,000 + 500,000 = 3,500,000원
통상시급 = 3,500,000 / 208.6 ≈ 16,779원
1일통상임금 = 16,779 x 8 = 134,233원
```

### 예시 2: 시급제 + 4조2교대

**입력**:
- 임금형태: 시급 (HOURLY)
- 시급: 12,000원
- 근무형태: 4조2교대 (SHIFT_4_2)

**계산 과정**:

Step 1 — 월 기준시간:
```
4조2교대 → SHIFT_MONTHLY_HOURS["4조2교대"] = 182.5h
```

Step 2 — 기본 통상임금:
```
월기본급 = 12,000 x 182.5 = 2,190,000원
```

Step 3 — 수당 없음

Step 4 — 최종 산출:
```
통상시급 = 12,000원 (시급 그대로)
월통상임금 = 2,190,000원
1일통상임금 = 12,000 x 8 = 96,000원
```

---

## 8. 관련 판례

| 판례번호 | 요지 | 코드 반영 위치 |
|---------|------|--------------|
| 대법원 2013다4174 | 통상임금 판단 기준: 정기성 + 일률성 + 고정성 | ordinary_wage.py:5 (docstring) |
| 대법원 2023다302838 (2024.12.19) | 고정성 요건 폐기 — 재직조건/근무일수 조건부 수당도 통상임금 인정 | ordinary_wage.py:6-8, _resolve_is_ordinary():159-162 |
| 대법원 2022다291153 | 주휴시간 산정: min(주소정근로/5, 8) | _get_base_hours():177, ordinary_wage.py:202 |
| 대법원 2023다302838 | 최소보장 성과급의 보장분은 통상임금 포함 | _resolve_is_ordinary():152-156, calc_ordinary_wage():95-98 |
