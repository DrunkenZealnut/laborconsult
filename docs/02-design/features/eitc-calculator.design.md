# Design: 근로장려금(EITC) 수급기준 및 금액 계산기

> Plan Reference: `docs/01-plan/features/eitc-calculator.plan.md`

---

## 1. Architecture Overview

기존 wage_calculator 패키지의 Facade 패턴을 그대로 따른다.

```
wage_calculator/
├── constants.py              # [수정] EITC_PARAMS, EITC_ASSET_* 상수 추가
├── models.py                 # [수정] WageInput에 EITC 필드 6개 추가
├── facade.py                 # [수정] CALC_TYPES, CALC_TYPE_MAP, _pop_eitc, _STANDARD_CALCS 추가
├── __init__.py               # [수정] calc_eitc export 추가
└── calculators/
    └── eitc.py               # [신규] calc_eitc() + EitcResult
```

**호출 흐름:**
```
사용자 질문 → chatbot.py extract_calc_params()
  → "근로장려금" 감지 → needs_calculation=true, targets=["eitc"]
  → WageCalculator.calculate(inp, ["eitc"])
    → calc_ordinary_wage(inp)  ← 통상임금은 EITC에서 미사용이지만, 기존 패턴 유지
    → calc_eitc(inp, ow)      ← 핵심 계산
    → _pop_eitc(r, result)    ← summary 세팅
  → format_result(result)
  → Claude 답변 생성
```

**특이사항:** EITC는 통상임금(ow)이 필수는 아니지만, 기존 디스패처 구조(`_STANDARD_CALCS`)가 `(inp, ow)` 시그니처를 요구하므로 이를 따른다. `ow`는 내부에서 사용하지 않아도 무방.

---

## 2. Data Design

### 2.1 constants.py 추가 상수

```python
# ── 근로장려금(EITC) 연도별 기준표 ─────────────────────────────────────────────
# 조세특례제한법 제100조의5, 시행령 제100조의5
# 각 가구유형별: max(최대 장려금), inc_end(점증 종료), flat_end(평탄 종료),
#                phase_out_end(점감 종료 = 소득 상한)
# 금액 단위: 원
EITC_PARAMS: dict[int, dict[str, dict]] = {
    2024: {
        "single":        {"max": 1_650_000, "inc_end":  4_000_000, "flat_end":  9_000_000, "phase_out_end": 22_000_000},
        "single_earner": {"max": 2_850_000, "inc_end":  7_000_000, "flat_end": 14_000_000, "phase_out_end": 32_000_000},
        "dual_earner":   {"max": 3_300_000, "inc_end":  8_000_000, "flat_end": 17_000_000, "phase_out_end": 38_000_000},
    },
    2025: {
        "single":        {"max": 1_650_000, "inc_end":  4_000_000, "flat_end":  9_000_000, "phase_out_end": 22_000_000},
        "single_earner": {"max": 2_850_000, "inc_end":  7_000_000, "flat_end": 14_000_000, "phase_out_end": 32_000_000},
        "dual_earner":   {"max": 3_300_000, "inc_end":  8_000_000, "flat_end": 17_000_000, "phase_out_end": 38_000_000},
    },
    # 2026: 확정 시 추가. 미등록 연도는 가장 최근 연도 fallback.
}

# 재산 요건
EITC_ASSET_UPPER       = 240_000_000   # 2.4억 이상: 수급 불가
EITC_ASSET_REDUCTION   = 170_000_000   # 1.7억 초과 ~ 2.4억 미만: 50% 감액
EITC_ASSET_REDUCTION_RATE = 0.50       # 감액률

# 자녀장려금
CHILD_CREDIT_MAX_PER_CHILD: dict[int, int] = {
    2024: 1_000_000,
    2025: 1_000_000,
}
CHILD_CREDIT_INCOME_LIMIT = 40_000_000  # 자녀장려금 소득 상한 (홑벌이·맞벌이 동일)

# 가구유형 자동 판정 기준
SPOUSE_INCOME_THRESHOLD = 3_000_000     # 배우자 총급여 300만원 기준
```

### 2.2 models.py 추가 필드 (WageInput)

```python
# ── 근로장려금(EITC) 계산용 ──────────────────────────────────────────────────
household_type: str = ""              # "단독" / "홑벌이" / "맞벌이" (빈 문자열이면 자동 판정)
annual_total_income: float = 0.0      # 연간 총소득 (원). 0이면 monthly_wage × 12로 추정
spouse_income: float = 0.0            # 배우자 연간 총급여 (원). 가구유형 자동 판정용
total_assets: float = 0.0             # 가구원 재산 합계 (원)
num_children_under_18: int = 0        # 18세 미만 부양자녀 수
has_elderly_parent: bool = False      # 70세 이상 직계존속 동거 여부
```

**배치 위치:** `# ── 임금체불 지연이자 계산용` 블록 앞 (line ~189).

### 2.3 EitcResult (eitc.py)

```python
@dataclass
class EitcResult(BaseCalculatorResult):
    # 입력 확인
    household_type: str = ""           # 적용된 가구유형 ("단독"/"홑벌이"/"맞벌이")
    annual_income: float = 0.0         # 연간 총소득 (원)
    total_assets: float = 0.0          # 가구 재산 (원)

    # 수급 판정
    is_eligible: bool = False          # 수급 자격 여부
    ineligible_reason: str = ""        # 미수급 사유

    # 근로장려금
    income_zone: str = ""              # "점증" / "평탄" / "점감"
    eitc_raw: float = 0.0             # 근로장려금 (감액 전, 원)
    asset_reduction: bool = False      # 재산 감액 적용 여부
    eitc_final: float = 0.0           # 최종 근로장려금 (감액 후, 원)

    # 자녀장려금
    child_credit_per_child: float = 0.0  # 자녀 1인당 장려금 (원)
    child_credit_total: float = 0.0      # 자녀장려금 합계 (원)
    num_children: int = 0                # 적용 자녀 수

    # 합계
    total_credit: float = 0.0         # 근로장려금 + 자녀장려금 (원)
```

---

## 3. Algorithm Design

### 3.1 calc_eitc(inp, ow) 메인 함수 흐름

```
1. 가구유형 결정
   ├─ household_type 직접 입력 → 사용
   └─ 빈 문자열 → _determine_household_type(inp) 자동 판정

2. 연간 총소득 결정
   ├─ annual_total_income > 0 → 사용
   └─ 0 → monthly_wage × 12 추정 (경고 출력)

3. EITC 기준표 조회
   └─ EITC_PARAMS[year][household_key] (fallback: 최신 연도)

4. 소득 요건 체크
   └─ income >= phase_out_end → _ineligible("소득 초과")

5. 재산 요건 체크
   └─ total_assets >= EITC_ASSET_UPPER → _ineligible("재산 초과")

6. 근로장려금 산출 (_calc_eitc_amount)
   ├─ income <= inc_end          → 점증: income × (max / inc_end)
   ├─ income <= flat_end         → 평탄: max
   └─ income < phase_out_end     → 점감: max - (income - flat_end) × max / (phase_out_end - flat_end)

7. 재산 감액 적용
   └─ total_assets > EITC_ASSET_REDUCTION → eitc × (1 - REDUCTION_RATE)

8. 자녀장려금 산출 (num_children > 0일 때만)
   ├─ 소득 요건 체크 (CHILD_CREDIT_INCOME_LIMIT)
   ├─ 단독가구 제외 (자녀장려금 수급 불가)
   └─ 자녀 수 × CHILD_CREDIT_MAX_PER_CHILD × 재산 감액

9. 결과 조립 + formulas/warnings/legal_basis
```

### 3.2 _determine_household_type(inp) 자동 판정

```python
def _determine_household_type(inp: WageInput) -> str:
    has_spouse = inp.spouse_income > 0 or inp.tax_dependents > 1
    has_children = inp.num_children_under_18 > 0
    has_elderly = inp.has_elderly_parent

    if not has_spouse and not has_children and not has_elderly:
        return "단독"

    if has_spouse and inp.spouse_income >= SPOUSE_INCOME_THRESHOLD:
        return "맞벌이"

    return "홑벌이"  # 배우자 소득 300만 미만, 또는 자녀/직계존속 있음
```

### 3.3 _calc_eitc_amount(income, params) 3구간 산출

```python
def _calc_eitc_amount(income: float, p: dict) -> tuple[float, str]:
    """Returns: (금액, 구간명)"""
    max_amt = p["max"]
    inc_end = p["inc_end"]
    flat_end = p["flat_end"]
    phase_out_end = p["phase_out_end"]

    if income <= inc_end:
        amount = income * (max_amt / inc_end)
        return (amount, "점증")

    if income <= flat_end:
        return (max_amt, "평탄")

    # 점감 구간
    phase_out_range = phase_out_end - flat_end
    amount = max_amt - (income - flat_end) * (max_amt / phase_out_range)
    return (max(0, amount), "점감")
```

### 3.4 household_type ↔ EITC_PARAMS key 매핑

```python
_HOUSEHOLD_KEY = {
    "단독":   "single",
    "홑벌이": "single_earner",
    "맞벌이": "dual_earner",
}
```

---

## 4. Facade Integration

### 4.1 CALC_TYPES 추가

```python
"eitc": "근로장려금(EITC) 수급 판정 + 금액",
```

### 4.2 CALC_TYPE_MAP 추가

```python
"근로장려금":  ["eitc"],
"근로장려세제": ["eitc"],
"EITC":       ["eitc"],
```

### 4.3 _pop_eitc 함수

```python
def _pop_eitc(r, result):
    if r.is_eligible:
        result.summary["근로장려금"] = f"{r.eitc_final:,.0f}원"
        if r.child_credit_total > 0:
            result.summary["자녀장려금"] = f"{r.child_credit_total:,.0f}원"
        result.summary["합계(EITC+자녀)"] = f"{r.total_credit:,.0f}원"
        result.summary["소득구간"] = r.income_zone
        if r.asset_reduction:
            result.summary["재산감액"] = "50% 감액 적용"
    else:
        result.summary["근로장려금"] = f"수급 불가 — {r.ineligible_reason[:40]}"
    return 0  # monthly_total에 미반영 (연간 환급형)
```

### 4.4 _STANDARD_CALCS 등록

```python
("eitc", calc_eitc, "근로장려금(EITC)", _pop_eitc, None),
```

기존 리스트 마지막(`flexible_work` 다음)에 추가.

### 4.5 _auto_detect_targets 추가 조건

```python
# facade.py _auto_detect_targets() 내부
if getattr(inp, "annual_total_income", 0) > 0 or getattr(inp, "household_type", ""):
    targets.append("eitc")
```

### 4.6 _provided_info_to_input 확장

EITC는 chatbot의 `extract_calc_params()`에서 별도 처리하므로, `_provided_info_to_input()`은 최소한으로 확장:

```python
# provided_info에 "가구유형", "연소득", "재산" 키가 있으면 EITC 필드 설정
if "가구유형" in info:
    inp.household_type = info["가구유형"]
if "연소득" in info:
    inp.annual_total_income = _parse_amount(info["연소득"])
if "재산" in info:
    inp.total_assets = _parse_amount(info["재산"])
```

---

## 5. Chatbot Integration

### 5.1 extract_calc_params() 확장

chatbot.py의 `extract_calc_params()`에서 Claude가 "근로장려금" 관련 질문을 인식하도록 프롬프트에 키워드 추가:

```python
# extract_calc_params 프롬프트에 추가
"근로장려금": {
    "needs_calculation": true,
    "calculation_type": "근로장려금",
    "provided_info": {
        "가구유형": "단독/홑벌이/맞벌이",
        "연소득": "연간 총소득 (원)",
        "재산": "가구 재산 합계 (원)",
        "자녀수": "18세 미만 자녀 수"
    }
}
```

### 5.2 run_calculator() 내 EITC 경로

`run_calculator()`에서 `calculation_type == "근로장려금"` → WageInput 구성 → `WageCalculator.calculate(inp, ["eitc"])`.

**소득 추정 로직:**
- 사용자가 "월급 200만원, 미혼"이라고 하면:
  - `monthly_wage = 2_000_000`
  - `annual_total_income = 2_000_000 × 12 = 24_000_000`
  - `household_type = "단독"` (미혼 → 자동 판정)

---

## 6. Output Format

### 6.1 formulas 예시 (단독, 소득 600만, 재산 1억)

```
[근로장려금] 가구유형: 단독가구
[근로장려금] 연간 총소득: 6,000,000원 (평탄구간: 4,000,000 ~ 9,000,000원)
[근로장려금] 근로장려금: 1,650,000원 (최대액)
[근로장려금] 재산 100,000,000원 < 1.7억 → 감액 미적용
[근로장려금] 최종 근로장려금: 1,650,000원
```

### 6.2 formulas 예시 (홑벌이, 소득 1,000만, 재산 2억, 자녀 1명)

```
[근로장려금] 가구유형: 홑벌이가구
[근로장려금] 연간 총소득: 10,000,000원 (평탄구간: 7,000,000 ~ 14,000,000원)
[근로장려금] 근로장려금: 2,850,000원 (최대액)
[근로장려금] 재산 200,000,000원 > 1.7억 → 50% 감액 적용
[근로장려금] 근로장려금 감액 후: 1,425,000원
[자녀장려금] 부양자녀 1명 × 1,000,000원 × 50%(재산감액) = 500,000원
[합계] 근로장려금 1,425,000원 + 자녀장려금 500,000원 = 1,925,000원
```

### 6.3 breakdown dict 구조

```python
{
    "가구유형": "홑벌이가구",
    "연간 총소득": "10,000,000원",
    "가구 재산": "200,000,000원",
    "소득구간": "평탄 (7,000,000 ~ 14,000,000원)",
    "근로장려금(감액 전)": "2,850,000원",
    "재산 감액": "50% 적용 (재산 1.7억 초과)",
    "근로장려금(최종)": "1,425,000원",
    "자녀장려금": "500,000원 (1명 × 1,000,000원 × 50%)",
    "합계": "1,925,000원",
    "기준 연도": "2025년",
    "신청 안내": "정기 5월 / 반기 3월·9월",
}
```

### 6.4 warnings 출력 목록

| 조건 | warning 메시지 |
|------|---------------|
| 연소득 미입력 → 월급 추정 | "연간 총소득 미입력 — 월급 {X}원 × 12 = {Y}원으로 추정" |
| 재산 미입력 | "재산 정보 미입력 — 재산 요건 미검증 (실제 수급 시 재산 2.4억 미만 필요)" |
| 재산 감액 | "재산 {X}원 > 1.7억 → 근로장려금·자녀장려금 50% 감액" |
| 소득 초과 경계 | "총소득이 상한({X}원)에 근접합니다 — 다른 소득(이자·배당 등) 합산 시 초과 가능" |
| 단독가구 + 자녀 | "단독가구는 자녀장려금 수급 대상이 아닙니다" |
| 가구유형 자동 판정 | "배우자 소득·부양자녀 정보로 '{X}가구'로 판정" |
| 공통 | "근로장려금은 추정치입니다. 정확한 금액은 국세청 홈택스에서 확인하세요" |
| 공통 | "신청 기한: 정기 5월 (전년도 소득 기준), 반기 상반기 9월·하반기 3월" |

### 6.5 legal_basis

```python
[
    "조세특례제한법 제100조의3 (근로장려금 수급 요건)",
    "조세특례제한법 제100조의5 (근로장려금 산정)",
    "조세특례제한법 제100조의27 (자녀장려금)",  # 자녀장려금 계산 시
]
```

---

## 7. Implementation Order (구체화)

| Step | File | Action | LoC |
|------|------|--------|-----|
| 1 | `wage_calculator/constants.py` | EITC_PARAMS, EITC_ASSET_*, CHILD_CREDIT_* 상수 추가 | ~30 |
| 2 | `wage_calculator/models.py` | WageInput에 6개 필드 추가 | ~10 |
| 3 | `wage_calculator/calculators/eitc.py` | EitcResult + calc_eitc() + 헬퍼 함수 3개 | ~180 |
| 4 | `wage_calculator/facade.py` | import, CALC_TYPES, CALC_TYPE_MAP, _pop_eitc, _STANDARD_CALCS, _auto_detect, _provided_info_to_input | ~30 |
| 5 | `wage_calculator/__init__.py` | export 추가 | ~2 |
| 6 | `wage_calculator_cli.py` | 테스트 케이스 #33~#39 (7개) | ~80 |
| 7 | `chatbot.py` | extract_calc_params 프롬프트 + run_calculator EITC 경로 | ~15 |

**총 예상 LoC:** ~350줄 (신규 180 + 수정 170)

---

## 8. Test Specification

### 8.1 단위 테스트 (wage_calculator_cli.py)

| # | Name | Input | Expected |
|---|------|-------|----------|
| 33 | 단독_점증 | 단독, 소득 300만, 재산 1억 | eligible, eitc=1,237,500원, zone="점증" |
| 34 | 단독_평탄 | 단독, 소득 600만, 재산 1억 | eligible, eitc=1,650,000원, zone="평탄" |
| 35 | 단독_소득초과 | 단독, 소득 2,300만, 재산 1억 | ineligible, reason="소득 초과" |
| 36 | 홑벌이_재산감액 | 홑벌이, 소득 1,000만, 재산 2억 | eligible, eitc_raw=2,850,000, eitc_final=1,425,000, asset_reduction=True |
| 37 | 맞벌이_점감 | 맞벌이, 소득 2,500만, 재산 1.5억 | eligible, zone="점감", eitc=~1,057,143원 |
| 38 | 재산초과 | 홑벌이, 소득 500만, 재산 2.5억 | ineligible, reason="재산 초과" |
| 39 | 자녀장려금 | 홑벌이, 소득 1,200만, 재산 1억, 자녀 2명 | eitc=2,850,000 + child=2,000,000, total=4,850,000 |

### 8.2 검증 산식 (수기)

**#33:** 3,000,000 × (1,650,000 / 4,000,000) = 1,237,500원

**#37:** 점감 = 3,300,000 - (25,000,000 - 17,000,000) × (3,300,000 / 21,000,000)
       = 3,300,000 - 8,000,000 × 0.15714... = 3,300,000 - 1,257,143 = 2,042,857원

**#36:** 2,850,000 × 50% = 1,425,000원

---

## 9. Error Handling

| Scenario | Behavior |
|----------|----------|
| household_type 미입력 + 판정 정보 부족 | "단독"으로 기본 처리 + 경고 |
| annual_total_income 미입력 + monthly_wage도 없음 | ineligible + "소득 정보 없음" |
| reference_year에 EITC_PARAMS 없음 | 가장 최근 연도 fallback + 경고 |
| total_assets 미입력 (0원) | 재산 요건 미검증 + 경고 (감액 미적용) |
| 음수 소득 또는 재산 | 0으로 처리 + 경고 |

---

## 10. File Change Summary

| File | Type | Changes |
|------|------|---------|
| `wage_calculator/constants.py` | MODIFY | +30 lines (EITC 상수 블록) |
| `wage_calculator/models.py` | MODIFY | +10 lines (WageInput 필드 6개) |
| `wage_calculator/calculators/eitc.py` | CREATE | ~180 lines |
| `wage_calculator/facade.py` | MODIFY | +30 lines (6곳 수정) |
| `wage_calculator/__init__.py` | MODIFY | +2 lines |
| `wage_calculator_cli.py` | MODIFY | +80 lines (7 test cases) |
| `chatbot.py` | MODIFY | +15 lines |
| **Total** | | **~350 lines** |
