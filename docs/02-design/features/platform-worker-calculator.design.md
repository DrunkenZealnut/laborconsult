# Design: 특수고용직(노무제공자) 사회보험 계산 반영

> Plan Reference: `docs/01-plan/features/platform-worker-calculator.plan.md`

---

## 1. 파일 구조 및 역할

### 1.1 계산기 코드 (9개 파일)

| 파일 | 상태 | 변경 |
|------|------|------|
| `wage_calculator/models.py` | MODIFY | WorkType에 PLATFORM_WORKER, WageInput에 4개 필드 |
| `wage_calculator/constants.py` | MODIFY | 특수고용직 전용 상수 8개 |
| `wage_calculator/calculators/unemployment.py` | MODIFY | 노무제공자 수급요건/상한 분기 (line ~101~256) |
| `wage_calculator/calculators/insurance.py` | MODIFY | 노무제공자 보험료 분기 (line ~101), employer 산재 50% (line ~459) |
| `wage_calculator/calculators/maternity_leave.py` | MODIFY | 노무제공자 출산휴가 요건/상한 분기 (line ~76~135) |
| `wage_calculator/calculators/industrial_accident.py` | MODIFY | 노무제공자 산재보험료 50% 분담 (line ~94) |
| `app/templates/prompts.py` | MODIFY | ANALYZE_TOOL에 is_platform_worker 필드 |
| `app/core/analyzer.py` | MODIFY | info_keys에 is_platform_worker |
| `wage_calculator/facade/conversion.py` | MODIFY | 매핑 로직 |

### 1.2 calculator_flow HTML (5개 파일)

| 파일 | 상태 | 변경 |
|------|------|------|
| `calculator_flow/unemployment_benefit_calc.html` | MODIFY | 노무제공자 탭/분기 추가 |
| `calculator_flow/insurance_income_tax_calc.html` | MODIFY | 노무제공자 보험료 경로 |
| `calculator_flow/employer_insurance_burden_calc.html` | MODIFY | 산재 50% 분담 표시 |
| `calculator_flow/maternity_leave_benefit_flow.html` | MODIFY | 노무제공자 요건/상한 |
| `calculator_flow/industrial_accident_compensation_calc.html` | MODIFY | 보험료 분담 표시 |

---

## 2. 모델 및 상수 설계

### 2.1 models.py — WorkType 추가

```python
class WorkType(Enum):
    REGULAR      = "정규직"
    CONTRACT     = "계약직"
    PART_TIME    = "파트타임"
    DAILY_WORKER = "일용직"
    PLATFORM_WORKER = "특수고용직"   # NEW
    SHIFT_4_2    = "4조2교대"
    ...
```

### 2.2 WageInput — 노무제공자 필드 (4개)

```python
# ── 특수고용직(노무제공자) ──────────────────────────────────────────
is_platform_worker: bool = False
platform_monthly_income: Optional[float] = None   # 월 보수액 (총수입−비과세−경비)
platform_insured_months: int = 0                   # 고용보험 피보험 개월수
platform_income_decreased: bool = False            # 소득 30%↑ 감소 이직 여부
```

**위치**: `is_probation` 블록 아래, `public_holiday_days` 앞에 삽입.

### 2.3 constants.py — 특수고용직 상수 (8개)

```python
# ── 특수고용직(노무제공자) 사회보험 (고용보험법, 산재보험법) ──
PLATFORM_EMP_INSURANCE_RATE   = 0.008    # 고용보험 노무제공자 부담 0.8%
PLATFORM_EMP_INSURANCE_BIZ    = 0.008    # 고용보험 사업주 부담 0.8%
PLATFORM_UNEMPLOYMENT_UPPER   = {2025: 66_000, 2026: 66_000}  # 구직급여 일 상한
PLATFORM_INSURED_REQ_MONTHS   = 12       # 수급요건: 24개월 중 12개월
PLATFORM_INSURED_REQ_WINDOW   = 24       # 수급요건: 기준기간 24개월
PLATFORM_MIN_MONTHLY_INCOME   = 800_000  # 고용보험 가입 최소 월 보수
PLATFORM_MATERNITY_UPPER      = 2_000_000  # 출산휴가 상한 200만원
PLATFORM_INDUSTRIAL_SPLIT     = 0.5      # 산재보험 노무제공자 부담 50%
```

**위치**: 기존 `PROBATION_` 상수 블록 아래.

---

## 3. 계산기별 상세 변경

### 3.1 unemployment.py — 노무제공자 구직급여

**삽입 위치**: `calc_unemployment()` 함수 내, 기존 eligibility 체크 직전 (~line 120)

```python
# ── 노무제공자 분기 ──
is_pw = getattr(inp, "is_platform_worker", False)
if is_pw:
    # 수급요건: 24개월 중 12개월 보험료 납부
    pw_months = getattr(inp, "platform_insured_months", 0)
    if pw_months < PLATFORM_INSURED_REQ_MONTHS:
        is_eligible = False
        ineligible_reason = (
            f"노무제공자 피보험기간 {pw_months}개월 < "
            f"요건 {PLATFORM_INSURED_REQ_MONTHS}개월 "
            f"(이직 전 {PLATFORM_INSURED_REQ_WINDOW}개월 기준)"
        )
    # 소득 30% 감소 이직 → 비자발적 인정
    if getattr(inp, "platform_income_decreased", False):
        is_involuntary = True
        warnings.append("노무제공자 소득 30% 이상 감소로 비자발적 이직 인정")
    # 상한 교체
    upper_limit = float(PLATFORM_UNEMPLOYMENT_UPPER.get(year, 66_000))
    legal.append("고용보험법 제77조의6 (노무제공자 구직급여)")
```

**기존 로직 보존**: `is_pw=False`이면 기존 `MIN_INSURED_DAYS=180` 체크 그대로 실행.

**상한 적용**: 기존 `UNEMPLOYMENT_BENEFIT_UPPER[year]` 대신 `PLATFORM_UNEMPLOYMENT_UPPER[year]` 사용.

**하한/급여일수**: 일반 근로자와 동일 (BENEFIT_DAYS_TABLE 공유).

### 3.2 insurance.py — 노무제공자 보험료

**삽입 위치**: `calc_insurance()` 함수의 분기 시작 (~line 101)

```python
def calc_insurance(inp, ow):
    if inp.is_freelancer and not getattr(inp, "is_platform_worker", False):
        return _calc_freelancer(inp, ow)
    elif getattr(inp, "is_platform_worker", False):
        return _calc_platform_worker(inp, ow)    # NEW
    else:
        return _calc_employee(inp, ow)
```

**새 함수 `_calc_platform_worker()`**:

```python
def _calc_platform_worker(inp, ow):
    """노무제공자 보험료 계산 — 고용보험만 + 3.3% 세금."""
    gross = ow.monthly_ordinary_wage
    year = inp.reference_year

    # 국민연금·건강보험·장기요양: 미가입 (지역가입자 별도)
    national_pension = 0
    health_insurance = 0
    long_term_care = 0

    # 고용보험: 0.8% (월 보수 80만원 이상 시)
    pw_income = getattr(inp, "platform_monthly_income", None) or gross
    if pw_income >= PLATFORM_MIN_MONTHLY_INCOME:
        employment_insurance = int(pw_income * PLATFORM_EMP_INSURANCE_RATE)
    else:
        employment_insurance = 0
        warnings.append(f"월 보수 {pw_income:,.0f}원 < 80만원 → 고용보험 미가입")

    total_insurance = employment_insurance

    # 소득세: 사업소득 3.3% 원천징수
    income_tax = int(gross * 0.03)
    local_income_tax = int(gross * 0.003)
    total_tax = income_tax + local_income_tax

    monthly_net = gross - total_insurance - total_tax
    ...
```

**employer_insurance에 산재 50% 분담**:

```python
def calc_employer_insurance(inp, ow):
    ...
    is_pw = getattr(inp, "is_platform_worker", False)
    if is_pw:
        # 사업주: 고용보험 0.8% + 산재보험 50%
        employer_employment = int(gross * PLATFORM_EMP_INSURANCE_BIZ)
        employer_accident = int(gross * total_accident_rate * (1 - PLATFORM_INDUSTRIAL_SPLIT))
        # 노무제공자 산재 부담분 표시
        worker_accident_share = int(gross * total_accident_rate * PLATFORM_INDUSTRIAL_SPLIT)
        breakdown["노무제공자 산재부담"] = f"{worker_accident_share:,.0f}원 (50%)"
        # 국민연금·건보·장기요양·직업능력개발: 없음
        employer_pension = 0
        employer_health = 0
        employer_ltc = 0
        employer_vocational = 0
    ...
```

### 3.3 maternity_leave.py — 노무제공자 출산휴가

**삽입 위치**: benefit 계산 시작 (~line 88)

```python
is_pw = getattr(inp, "is_platform_worker", False)
if is_pw:
    # 노무제공자: 직전 1년 월 평균 보수 100%, 상한 200만
    pw_income = getattr(inp, "platform_monthly_income", None) or ow.monthly_ordinary_wage
    monthly_benefit = min(pw_income, PLATFORM_MATERNITY_UPPER)
    upper = PLATFORM_MATERNITY_UPPER
    # 수급요건: 피보험 단위기간 3개월 이상
    pw_months = getattr(inp, "platform_insured_months", 0)
    if pw_months < 3:
        is_eligible = False
        warnings.append(f"노무제공자 피보험기간 {pw_months}개월 < 3개월 → 수급 불가")
    # 지급 주체: 전액 고용보험 (사업주 부담 없음)
    insurance_days = leave_days
    employer_days = 0
    legal.append("고용보험법 제77조의3 (노무제공자 출산전후휴가급여)")
else:
    # 기존 일반 근로자 로직 ...
```

### 3.4 industrial_accident.py — 노무제공자 산재보험

**삽입 위치**: 평균임금 산정 후 (~line 106)

급여 산정 자체는 일반 근로자와 동일 (평균임금 기준). 변경은 employer_insurance에서 50% 분담만 처리 (3.2 참조). 단, `breakdown`에 안내 추가:

```python
if getattr(inp, "is_platform_worker", False):
    warnings.append(
        "특수고용직(노무제공자)은 산재보험료를 사업주와 50%씩 분담합니다 "
        "(산재보험법 제126조의2)."
    )
    legal.append("산업재해보상보험법 제126조의2 (특수형태근로종사자의 보험료)")
```

---

## 4. analyzer/conversion 연동

### 4.1 prompts.py — ANALYZE_TOOL 필드 추가

**위치**: `occupation_code` 필드 뒤에 삽입

```python
"is_platform_worker": {
    "type": "boolean",
    "description": (
        "특수고용직(노무제공자/플랫폼 종사자) 여부. "
        "택배기사, 배달기사, 대리운전, 퀵서비스, 보험설계사, 학습지교사, "
        "골프장캐디, 관광안내원, 화물차주, 소프트웨어 프리랜서 등 언급 시 true. "
        "일반 직장인(근로계약 체결)은 false."
    ),
},
```

### 4.2 ANALYZER_SYSTEM — 규칙 추가

기존 10번(수습/직종 판별) 뒤에:

```
11. **특수고용직(노무제공자) 판별**:
   - 택배기사, 배달기사, 대리운전, 퀵서비스, 보험설계사, 학습지교사, 골프장캐디,
     관광안내원, 화물차주, 소프트웨어 프리랜서 → is_platform_worker=true
   - "프리랜서"만 언급되면 is_platform_worker가 아닌 기존 프리랜서 처리
   - 특수고용직은 고용보험(구직급여·출산휴가)만 적용, 국민연금·건강보험 미가입
```

### 4.3 analyzer.py — info_keys 추가

```python
info_keys = {
    ...,
    "is_probation", "contract_months", "occupation_code",
    "is_platform_worker",   # NEW
}
```

### 4.4 conversion.py — 매핑 추가

```python
# 특수고용직(노무제공자) 판별
if info.get("is_platform_worker") is True:
    inp.is_platform_worker = True
    inp.work_type = WorkType.PLATFORM_WORKER
```

---

## 5. calculator_flow HTML 변경

### 5.1 unemployment_benefit_calc.html

**Tab 0 (전체 흐름)** SVG에 노무제공자 분기 노드 추가:
```
수급 자격 확인 → [근로자인가? / 노무제공자인가?]
├── 근로자: 18개월 중 180일, 상한 68,100원
└── 노무제공자: 24개월 중 12개월, 상한 66,000원, 소득감소 이직 인정
```

**Tab 3 (시뮬레이션)**에 "근로 유형" 토글 추가:
- `일반 근로자` / `특수고용직(노무제공자)` 버튼
- 노무제공자 선택 시: 상한 66,000원 적용, 요건 텍스트 변경

### 5.2 insurance_income_tax_calc.html

**Tab 0 (전체 흐름)** SVG에 3-way 분기:
```
[근로자 유형]
├── 일반 근로자: 4대보험 + 간이세액표
├── 특수고용직: 고용보험 0.8%만 + 3.3% 세금
└── 프리랜서(3.3%): 보험 없음 + 3.3% 세금
```

**Tab (시뮬레이션)**에 "특수고용직" 토글 추가:
- 선택 시 국민연금/건보/장기요양 0원 표시, 고용보험 0.8% 적용

### 5.3 employer_insurance_burden_calc.html

산재보험 섹션에 **노무제공자 50% 분담** 안내 추가:
```
산재보험: 사업주 100% (일반) → 사업주 50% + 노무제공자 50% (특수고용직)
```

### 5.4 maternity_leave_benefit_flow.html

**Tab 0 (전체 흐름)**에 분기 추가:
```
[근로 유형]
├── 일반 근로자: 통상임금 기준, 상한 ~216만
└── 노무제공자: 월평균보수 100%, 상한 200만, 피보험 3개월 요건
```

### 5.5 industrial_accident_compensation_calc.html

보험료 부담 설명에 **노무제공자 50% 주석** 추가.

---

## 6. 구현 순서

```
Step 1:  models.py — WorkType.PLATFORM_WORKER + WageInput 4개 필드
Step 2:  constants.py — 특수고용직 상수 8개
Step 3:  unemployment.py — 노무제공자 수급요건/상한 분기
Step 4:  insurance.py — _calc_platform_worker() 신규 + employer 50% 분담
Step 5:  maternity_leave.py — 노무제공자 요건/상한 분기
Step 6:  industrial_accident.py — 보험료 분담 안내
Step 7:  prompts.py — ANALYZE_TOOL + ANALYZER_SYSTEM
Step 8:  analyzer.py — info_keys
Step 9:  conversion.py — 매핑
Step 10: calculator_flow HTML 5개 파일 업데이트
Step 11: 테스트 (노무제공자 시나리오 + 기존 116개 회귀)
```

---

## 7. 테스트 시나리오

| 시나리오 | 입력 | 기대 결과 |
|----------|------|----------|
| 택배기사 실업급여 | is_platform_worker=True, insured_months=15, age=35 | 상한 66,000원, 24개월 중 12개월 요건 충족 |
| 노무제공자 피보험 부족 | insured_months=8 | 수급 불가 (8<12개월) |
| 소득감소 이직 | income_decreased=True | 비자발적 이직 인정 |
| 노무제공자 보험료 | is_platform_worker=True, gross=300만 | 고용보험 24,000원만 (국민연금/건보/장기요양 0) |
| 월 보수 80만 미만 | platform_income=70만 | 고용보험 미가입 경고 |
| 노무제공자 출산휴가 | insured_months=6, 단태 | 상한 200만, 90일, 전액 고용보험 |
| 노무제공자 출산 피보험 부족 | insured_months=2 | 수급 불가 (2<3개월) |
| 노무제공자 산재보상 | is_platform_worker=True, sick_days=30 | 급여 동일 + 보험료 50% 분담 안내 |
| 일반 근로자 (회귀) | is_platform_worker=False | 기존 결과 완전 동일 |
| E2E "배달기사 실업급여" | chatbot query | analyzer가 is_platform_worker=true 추출 → 노무제공자 계산 |
