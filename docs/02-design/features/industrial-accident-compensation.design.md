# Design: 산재보상금 계산기 (industrial-accident-compensation)

## 참조
- Plan: `docs/01-plan/features/industrial-accident-compensation.plan.md`
- 참조: https://www.nodong.kr/IndustrialAccidentCompensationCal

---

## 1. 데이터 모델

### 1.1 WageInput 신규 필드 (models.py)

```python
    # ── 산재보상금 계산용 ─────────────────────────────────────────────────────
    accident_date: Optional[str] = None          # 산재 발생일 "YYYY-MM-DD"
    disability_grade: int = 0                    # 장해등급 (1~14, 0=해당없음)
    disability_pension: bool = True              # 장해급여 연금 선택 (True=연금, False=일시금)
    severe_illness_grade: int = 0                # 중증요양상태 등급 (1~3, 0=해당없음)
    num_survivors: int = 0                       # 유족수 (1~4+, 0=해당없음)
    survivor_pension: bool = True                # 유족급여 연금 선택 (True=연금, False=일시금)
    sick_leave_days: int = 0                     # 요양(휴업) 일수
    is_deceased: bool = False                    # 사망 여부
```

### 1.2 IndustrialAccidentResult (industrial_accident.py)

```python
@dataclass
class IndustrialAccidentResult(BaseCalculatorResult):
    """산재보상금 계산 결과"""
    avg_daily_wage: float = 0.0              # 적용 1일 평균임금

    # 휴업급여
    sick_leave_daily: float = 0.0            # 1일 휴업급여
    sick_leave_total: float = 0.0            # 휴업급여 총액
    sick_leave_days: int = 0                 # 요양일수
    min_comp_applied: bool = False           # 최저보상기준 적용 여부

    # 상병보상연금
    illness_pension_daily: float = 0.0       # 상병보상연금 1일분
    illness_pension_annual: float = 0.0      # 상병보상연금 연간액
    illness_grade: int = 0                   # 중증요양상태 등급

    # 장해급여
    disability_amount: float = 0.0           # 장해급여 금액
    disability_grade: int = 0                # 장해등급
    disability_type: str = ""                # "연금" / "일시금"
    disability_days: int = 0                 # 적용 보상일수

    # 유족급여
    survivor_amount: float = 0.0             # 유족급여 금액
    survivor_type: str = ""                  # "연금" / "일시금"
    survivor_ratio: float = 0.0              # 유족연금 지급비율

    # 장례비
    funeral_amount: float = 0.0              # 장례비

    # 합산
    total_compensation: float = 0.0          # 전체 보상금 합산
```

---

## 2. 상수 설계 (constants.py)

### 2.1 장해등급별 보상일수

```python
# ── 산재보상 장해등급별 보상일수 (산업재해보상보험법 제57조) ──────────────────
# (연금일수, 일시금일수, 지급형태)
# 지급형태: "pension_only"=연금만, "choice"=선택, "lump_sum"=일시금만
DISABILITY_GRADE_TABLE: dict[int, tuple[int, int, str]] = {
    1:  (329, 1474, "pension_only"),
    2:  (291, 1309, "pension_only"),
    3:  (257, 1155, "pension_only"),
    4:  (224, 1012, "choice"),
    5:  (193,  869, "choice"),
    6:  (164,  737, "choice"),
    7:  (138,  616, "choice"),
    8:  (  0,  495, "lump_sum"),
    9:  (  0,  385, "lump_sum"),
    10: (  0,  297, "lump_sum"),
    11: (  0,  220, "lump_sum"),
    12: (  0,  154, "lump_sum"),
    13: (  0,   99, "lump_sum"),
    14: (  0,   55, "lump_sum"),
}
```

### 2.2 상병보상연금 등급별 연금일수

```python
# ── 상병보상연금 등급별 일수 (산업재해보상보험법 제66조) ─────────────────────
SEVERE_ILLNESS_DAYS: dict[int, int] = {
    1: 329,
    2: 291,
    3: 257,
}
```

### 2.3 유족보상연금 지급비율

```python
# ── 유족보상연금 지급비율 (산업재해보상보험법 제62조) ────────────────────────
SURVIVOR_BASE_RATIO = 0.47       # 기본금액: 평균임금 365일분의 47%
SURVIVOR_ADD_RATIO  = 0.05       # 가산: 유족 1명당 5%
SURVIVOR_MAX_RATIO  = 0.67       # 최대 67% (4명 이상)
SURVIVOR_LUMP_SUM_DAYS = 1300    # 유족일시금: 1,300일분
```

### 2.4 장례비 연도별 최고/최저액

```python
# ── 장례비 (산업재해보상보험법 제71조) ──────────────────────────────────────
FUNERAL_DAYS = 120  # 평균임금 120일분

# 연도별 장례비 최고·최저액 (고용노동부 고시)
FUNERAL_LIMITS: dict[int, tuple[float, float]] = {
    # year: (최고액, 최저액)
    2024: (17_756_400, 12_843_000),
    2025: (18_554_400, 13_414_000),
    2026: (19_279_760, 13_943_000),
}
```

### 2.5 휴업급여 최저보상기준

```python
# ── 휴업급여 최저보상기준 (산업재해보상보험법 제54조) ────────────────────────
# 연도별 1일 최저보상기준금액 (고용노동부 고시)
MIN_COMPENSATION_DAILY: dict[int, float] = {
    2024: 78_880,
    2025: 80_240,
    2026: 82_560,
}
SICK_LEAVE_RATE = 0.70           # 휴업급여 기본율: 평균임금 70%
SICK_LEAVE_LOW_RATE = 0.90       # 저소득 보정율: 평균임금 90%
MIN_COMP_THRESHOLD = 0.80        # 최저보상기준 80%
```

---

## 3. 핵심 로직 설계

### 3.1 휴업급여 계산 (G1)

```python
def _calc_sick_leave(avg_daily: float, days: int, year: int) -> tuple[float, float, bool, list]:
    """
    휴업급여 계산 (산재보험법 제52조, 제54조)

    Returns: (1일 휴업급여, 총액, 최저보상기준 적용 여부, formulas)
    """
    formulas = []
    min_comp_applied = False

    base = avg_daily * SICK_LEAVE_RATE  # 70%
    min_comp = MIN_COMPENSATION_DAILY.get(year, MIN_COMPENSATION_DAILY[2026])
    min_comp_80 = min_comp * MIN_COMP_THRESHOLD  # 최저보상기준 × 80%

    # 최저임금 (시급 × 8시간)
    from .constants import MINIMUM_HOURLY_WAGE
    min_wage_daily = MINIMUM_HOURLY_WAGE.get(year, MINIMUM_HOURLY_WAGE[2026]) * 8

    daily = base
    formulas.append(f"기본 휴업급여: {avg_daily:,.0f}원 × 70% = {base:,.0f}원")

    if base <= min_comp_80:
        # 저소득: 90% 적용
        daily_90 = avg_daily * SICK_LEAVE_LOW_RATE
        if daily_90 > min_comp_80:
            daily = min_comp_80
            formulas.append(f"90%({daily_90:,.0f}원) > 최저보상기준 80%({min_comp_80:,.0f}원) → 최저보상기준 80% 적용")
        else:
            daily = daily_90
            formulas.append(f"90%({daily_90:,.0f}원) ≤ 최저보상기준 80%({min_comp_80:,.0f}원) → 90% 적용")
        min_comp_applied = True

    # 최저임금 하한
    if daily < min_wage_daily:
        daily = min_wage_daily
        formulas.append(f"최저임금 일급({min_wage_daily:,.0f}원) 적용")
        min_comp_applied = True

    total = daily * days
    formulas.append(f"휴업급여 총액: {daily:,.0f}원 × {days}일 = {total:,.0f}원")

    return daily, total, min_comp_applied, formulas
```

### 3.2 상병보상연금 계산 (G2)

```python
def _calc_illness_pension(avg_daily: float, grade: int) -> tuple[float, float, list]:
    """
    상병보상연금 계산 (산재보험법 제66조)

    Returns: (1일분, 연간액, formulas)
    """
    days = SEVERE_ILLNESS_DAYS.get(grade, 0)
    if days == 0:
        return 0, 0, []

    daily = avg_daily  # 100% 기준
    annual = daily * days
    formulas = [
        f"상병보상연금 (중증요양상태 제{grade}급): "
        f"{avg_daily:,.0f}원 × {days}일 = {annual:,.0f}원/년",
    ]
    return daily, annual, formulas
```

### 3.3 장해급여 계산 (G3, G4)

```python
def _calc_disability(avg_daily: float, grade: int, prefer_pension: bool) -> tuple[float, str, int, list]:
    """
    장해급여 계산 (산재보험법 제57조)

    Returns: (금액, 지급형태, 적용일수, formulas)
    """
    if grade < 1 or grade > 14:
        return 0, "", 0, []

    pension_days, lump_days, pay_type = DISABILITY_GRADE_TABLE[grade]
    formulas = []
    warnings = []

    if pay_type == "pension_only":
        # 1~3급: 연금만 가능
        days = pension_days
        dtype = "연금"
        amount = avg_daily * days
        formulas.append(
            f"장해급여 (제{grade}급, 연금): "
            f"{avg_daily:,.0f}원 × {days}일 = {amount:,.0f}원/년"
        )
        if not prefer_pension:
            warnings.append(f"제{grade}급은 연금만 가능합니다 (일시금 선택 불가)")

    elif pay_type == "lump_sum":
        # 8~14급: 일시금만
        days = lump_days
        dtype = "일시금"
        amount = avg_daily * days
        formulas.append(
            f"장해급여 (제{grade}급, 일시금): "
            f"{avg_daily:,.0f}원 × {days}일 = {amount:,.0f}원"
        )

    else:  # "choice" — 4~7급
        if prefer_pension:
            days = pension_days
            dtype = "연금"
            amount = avg_daily * days
            formulas.append(
                f"장해급여 (제{grade}급, 연금 선택): "
                f"{avg_daily:,.0f}원 × {days}일 = {amount:,.0f}원/년"
            )
        else:
            days = lump_days
            dtype = "일시금"
            amount = avg_daily * days
            formulas.append(
                f"장해급여 (제{grade}급, 일시금 선택): "
                f"{avg_daily:,.0f}원 × {days}일 = {amount:,.0f}원"
            )

    return amount, dtype, days, formulas
```

### 3.4 유족급여 계산 (G5, G6)

```python
def _calc_survivor(avg_daily: float, num: int, prefer_pension: bool) -> tuple[float, str, float, list]:
    """
    유족급여 계산 (산재보험법 제62조)

    Returns: (금액, 지급형태, 지급비율, formulas)
    """
    if num <= 0:
        return 0, "", 0, []

    formulas = []

    if prefer_pension:
        ratio = min(SURVIVOR_BASE_RATIO + SURVIVOR_ADD_RATIO * num, SURVIVOR_MAX_RATIO)
        amount = avg_daily * 365 * ratio
        formulas.append(
            f"유족보상연금: {avg_daily:,.0f}원 × 365일 × {ratio*100:.0f}% "
            f"(47% + {num}명×5%) = {amount:,.0f}원/년"
        )
        return amount, "연금", ratio, formulas
    else:
        amount = avg_daily * SURVIVOR_LUMP_SUM_DAYS
        formulas.append(
            f"유족보상일시금: {avg_daily:,.0f}원 × {SURVIVOR_LUMP_SUM_DAYS}일 = {amount:,.0f}원"
        )
        return amount, "일시금", 0, formulas
```

### 3.5 장례비 계산 (G7)

```python
def _calc_funeral(avg_daily: float, year: int) -> tuple[float, list]:
    """
    장례비 계산 (산재보험법 제71조)

    Returns: (장례비 금액, formulas)
    """
    raw = avg_daily * FUNERAL_DAYS
    max_amt, min_amt = FUNERAL_LIMITS.get(year, FUNERAL_LIMITS[2026])

    if raw > max_amt:
        amount = max_amt
        note = f"최고액 적용 ({max_amt:,.0f}원)"
    elif raw < min_amt:
        amount = min_amt
        note = f"최저액 적용 ({min_amt:,.0f}원)"
    else:
        amount = raw
        note = "120일분 적용"

    formulas = [
        f"장례비: {avg_daily:,.0f}원 × {FUNERAL_DAYS}일 = {raw:,.0f}원 → {note} = {amount:,.0f}원"
    ]
    return amount, formulas
```

### 3.6 메인 함수

```python
def calc_industrial_accident(inp: WageInput, ow: OrdinaryWageResult) -> IndustrialAccidentResult:
    """
    산재보상금 통합 계산

    계산 순서:
    1. 평균임금 결정 (average_wage 결과 또는 통상임금 환산)
    2. 유효성 검증
    3. 해당 급여 항목별 계산
    4. 합산 및 결과 조립
    """
    warnings = []
    formulas = []
    legal = [
        "산업재해보상보험법 제36조 (보험급여의 종류)",
        "산업재해보상보험법 제52조 (휴업급여)",
        "산업재해보상보험법 제54조 (휴업급여 최저보상기준)",
        "산업재해보상보험법 제57조 (장해급여)",
        "산업재해보상보험법 제62조 (유족급여)",
        "산업재해보상보험법 제66조 (상병보상연금)",
        "산업재해보상보험법 제71조 (장례비)",
    ]
    year = inp.reference_year

    # ── 1. 평균임금 결정 ──────────────────────────────────────────────────
    avg_daily = ow.daily_ordinary_wage  # 기본: 통상임금 환산일급
    # average_wage 결과가 있으면 facade에서 덮어씀 (아래 연동 설계 참조)
    # 여기서는 inp.monthly_wage 기반 추정도 지원
    if inp.monthly_wage:
        est = inp.monthly_wage / 30
        if est > avg_daily:
            avg_daily = est
            formulas.append(f"평균임금(추정): {inp.monthly_wage:,.0f}원 ÷ 30일 = {avg_daily:,.0f}원/일")

    total_compensation = 0.0
    breakdown = {"적용 평균임금": f"{avg_daily:,.0f}원/일"}

    # ── 2. 휴업급여 ───────────────────────────────────────────────────────
    sl_daily, sl_total, sl_min, sl_formulas = 0, 0, False, []
    if inp.sick_leave_days > 0:
        sl_daily, sl_total, sl_min, sl_formulas = _calc_sick_leave(
            avg_daily, inp.sick_leave_days, year
        )
        total_compensation += sl_total
        formulas.extend(sl_formulas)

    # ── 3. 상병보상연금 ───────────────────────────────────────────────────
    il_daily, il_annual, il_formulas = 0, 0, []
    if inp.severe_illness_grade > 0:
        il_daily, il_annual, il_formulas = _calc_illness_pension(
            avg_daily, inp.severe_illness_grade
        )
        total_compensation += il_annual
        formulas.extend(il_formulas)

    # ── 4. 장해급여 ───────────────────────────────────────────────────────
    dis_amount, dis_type, dis_days, dis_formulas = 0, "", 0, []
    if inp.disability_grade > 0:
        dis_amount, dis_type, dis_days, dis_formulas = _calc_disability(
            avg_daily, inp.disability_grade, inp.disability_pension
        )
        total_compensation += dis_amount
        formulas.extend(dis_formulas)

    # ── 5. 유족급여 ───────────────────────────────────────────────────────
    surv_amount, surv_type, surv_ratio, surv_formulas = 0, "", 0, []
    if inp.is_deceased and inp.num_survivors > 0:
        surv_amount, surv_type, surv_ratio, surv_formulas = _calc_survivor(
            avg_daily, inp.num_survivors, inp.survivor_pension
        )
        total_compensation += surv_amount
        formulas.extend(surv_formulas)

    # ── 6. 장례비 ─────────────────────────────────────────────────────────
    fun_amount, fun_formulas = 0, []
    if inp.is_deceased:
        fun_amount, fun_formulas = _calc_funeral(avg_daily, year)
        total_compensation += fun_amount
        formulas.extend(fun_formulas)

    # ── breakdown 조립 ────────────────────────────────────────────────────
    if sl_total > 0:
        breakdown["휴업급여"] = f"{sl_daily:,.0f}원/일 × {inp.sick_leave_days}일 = {sl_total:,.0f}원"
    if il_annual > 0:
        breakdown["상병보상연금"] = f"{il_annual:,.0f}원/년 (제{inp.severe_illness_grade}급)"
    if dis_amount > 0:
        breakdown["장해급여"] = f"{dis_amount:,.0f}원 ({dis_type}, 제{inp.disability_grade}급, {dis_days}일)"
    if surv_amount > 0:
        breakdown["유족급여"] = f"{surv_amount:,.0f}원 ({surv_type})"
    if fun_amount > 0:
        breakdown["장례비"] = f"{fun_amount:,.0f}원"
    breakdown["보상금 합계"] = f"{total_compensation:,.0f}원"

    return IndustrialAccidentResult(
        avg_daily_wage=avg_daily,
        sick_leave_daily=sl_daily,
        sick_leave_total=sl_total,
        sick_leave_days=inp.sick_leave_days,
        min_comp_applied=sl_min,
        illness_pension_daily=il_daily,
        illness_pension_annual=il_annual,
        illness_grade=inp.severe_illness_grade,
        disability_amount=dis_amount,
        disability_grade=inp.disability_grade,
        disability_type=dis_type,
        disability_days=dis_days,
        survivor_amount=surv_amount,
        survivor_type=surv_type,
        survivor_ratio=surv_ratio,
        funeral_amount=fun_amount,
        total_compensation=total_compensation,
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )
```

---

## 4. Facade 연동 설계

### 4.1 facade.py 수정 사항

```python
# import 추가
from .calculators.industrial_accident import calc_industrial_accident

# CALC_TYPES 추가
"industrial_accident": "산재보상금(휴업·장해·유족·장례비)",

# CALC_TYPE_MAP 추가
"산재보상":   ["industrial_accident", "average_wage"],
"휴업급여":   ["industrial_accident", "average_wage"],
"장해급여":   ["industrial_accident", "average_wage"],
"유족급여":   ["industrial_accident", "average_wage"],
"장례비":     ["industrial_accident", "average_wage"],
"산재":       ["industrial_accident", "average_wage"],

# _pop_industrial_accident 함수
def _pop_industrial_accident(r, result):
    result.summary["적용 평균임금"] = f"{r.avg_daily_wage:,.0f}원/일"
    if r.sick_leave_total > 0:
        result.summary["휴업급여"] = f"{r.sick_leave_total:,.0f}원 ({r.sick_leave_days}일)"
    if r.illness_pension_annual > 0:
        result.summary["상병보상연금"] = f"{r.illness_pension_annual:,.0f}원/년"
    if r.disability_amount > 0:
        result.summary["장해급여"] = f"{r.disability_amount:,.0f}원 ({r.disability_type})"
    if r.survivor_amount > 0:
        result.summary["유족급여"] = f"{r.survivor_amount:,.0f}원 ({r.survivor_type})"
    if r.funeral_amount > 0:
        result.summary["장례비"] = f"{r.funeral_amount:,.0f}원"
    result.summary["산재보상금 합계"] = f"{r.total_compensation:,.0f}원"
    return 0  # 산재보상금은 월급에 합산하지 않음

# _STANDARD_CALCS 등록
("industrial_accident", calc_industrial_accident, "산재보상금", _pop_industrial_accident, None),
```

### 4.2 평균임금 연동

산재보상금은 평균임금이 기초. `average_wage` target이 함께 지정되면:
1. `calc_average_wage()` 가 먼저 실행되어 `AverageWageResult` 생성
2. `calc_industrial_accident()` 내부에서 `avg_daily_wage` 필드 사용
3. facade에서 `_STANDARD_CALCS` 순서를 통해 average_wage → industrial_accident 순서 보장
   - 현재 이미 `average_wage`가 `industrial_accident`보다 앞에 등록됨

**별도 연동 불필요**: facade의 `_STANDARD_CALCS` 순서가 이미 average_wage → industrial_accident이므로, industrial_accident에서 `ow.daily_ordinary_wage` (통상임금 환산일급)을 기본으로 사용하되, 사용자가 `monthly_wage`를 제공하면 `monthly_wage/30`도 비교.

### 4.3 _auto_detect_targets 추가

```python
# 산재보상금 자동 감지
if inp.sick_leave_days > 0 or inp.disability_grade > 0 or inp.is_deceased:
    targets.append("industrial_accident")
    if "average_wage" not in targets:
        targets.append("average_wage")
```

---

## 5. 테스트 케이스 설계

| # | 설명 | 입력 | 검증 포인트 |
|---|------|------|-------------|
| #71 | 휴업급여 기본 | 평균임금 100,000원/일, 요양 30일 | 100,000×0.70×30 = 2,100,000원 |
| #72 | 휴업급여 최저보상기준 | 평균임금 50,000원/일, 요양 30일 | 50,000×0.70=35,000 ≤ 82,560×0.80=66,048 → 50,000×0.90=45,000 적용 |
| #73 | 상병보상연금 제1급 | 평균임금 100,000원/일, 중증 1급 | 100,000×329 = 32,900,000원/년 |
| #74 | 장해급여 연금 제4급 | 평균임금 100,000원/일, 4급 연금 | 100,000×224 = 22,400,000원/년 |
| #75 | 장해급여 일시금 제10급 | 평균임금 100,000원/일, 10급 | 100,000×297 = 29,700,000원 |
| #76 | 유족보상연금 3명 | 평균임금 100,000원/일, 사망, 유족 3명 연금 | 100,000×365×0.62 = 22,630,000원/년 |
| #77 | 유족보상일시금 + 장례비 | 평균임금 100,000원/일, 사망, 유족 1명 일시금 | 일시금 130,000,000원 + 장례비 12,000,000원 |
| #78 | 사망 종합 (유족연금+장례비) | 월급 300만, 사망, 유족 2명 연금 | 평균임금 추정 → 유족연금 + 장례비 합산 |

### 테스트 데이터 상세 (#71)

```python
{
    "case_no": 71,
    "title": "산재 휴업급여 기본",
    "input": {
        "wage_type": "월급",
        "monthly_wage": 3_000_000,
        "sick_leave_days": 30,
    },
    "targets": ["industrial_accident"],
    "expect": {
        "sick_leave_daily": "약 70,000원/일",  # 3,000,000/30 × 0.70
        "sick_leave_total": "약 2,100,000원",
    },
}
```

---

## 6. 법적 근거

```python
legal = [
    "산업재해보상보험법 제36조 (보험급여의 종류)",
    "산업재해보상보험법 제52조 (휴업급여: 평균임금 70%)",
    "산업재해보상보험법 제54조 (휴업급여 최저보상기준)",
    "산업재해보상보험법 제57조 (장해급여: 등급별 연금/일시금)",
    "산업재해보상보험법 제62조 (유족급여: 연금/일시금)",
    "산업재해보상보험법 제66조 (상병보상연금: 중증요양상태 등급별)",
    "산업재해보상보험법 제71조 (장례비: 120일분)",
    "근로기준법 제2조 (평균임금 정의)",
    "근로기준법 시행령 제2조 (평균임금 < 통상임금 시 대체)",
]
```

---

## 7. 구현 순서

| 단계 | 작업 | 파일 |
|------|------|------|
| 1 | constants.py에 상수 추가 (장해등급표, 상병연금, 유족비율, 장례비, 최저보상기준) | constants.py |
| 2 | models.py에 WageInput 신규 필드 8개 추가 | models.py |
| 3 | `calculators/industrial_accident.py` 신규 생성 (6개 헬퍼 + 메인 함수) | industrial_accident.py |
| 4 | facade.py 수정 (import, CALC_TYPES, CALC_TYPE_MAP, _pop, _STANDARD_CALCS, _auto_detect) | facade.py |
| 5 | wage_calculator_cli.py에 테스트 케이스 #71~#78 추가 | wage_calculator_cli.py |

---

## 8. 위험 요소

| 위험 | 대응 |
|------|------|
| 평균임금 미입력 시 부정확 | monthly_wage/30 추정 + 경고 문구 |
| 1~3급 일시금 선택 시도 | 연금만 가능 경고 + 자동 연금 적용 |
| 8~14급 연금 선택 시도 | 일시금만 가능 → 자동 일시금 |
| 장례비 최고/최저액 연도 미등록 | 최신 연도 fallback |
| 유족수 4명 초과 | min() 처리로 67% 상한 |
| 상병보상연금+휴업급여 중복 | 상병보상연금 수급 시 휴업급여 미지급 안내 경고 |
