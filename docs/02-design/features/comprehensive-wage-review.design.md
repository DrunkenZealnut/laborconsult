# Design: 포괄임금제 계산기 보완 (comprehensive-wage-review)

## 참조
- Plan: `docs/01-plan/features/comprehensive-wage-review.plan.md`
- 참조: https://www.nodong.kr/inclusiveWageCal

---

## 1. 데이터 모델

### 1.1 ComprehensiveResult 변경 (comprehensive.py)

기존 필드 유지 + 신규 필드 추가:

```python
@dataclass
class ComprehensiveResult(BaseCalculatorResult):
    # 기존 유지
    base_wage: float = 0.0                    # 역산 기본급 (월)
    effective_hourly: float = 0.0             # 역산 통상시급
    included_allowances: dict = field(...)    # 포함 수당 내역
    is_minimum_wage_ok: bool = False          # 최저임금 충족 여부
    legal_minimum: float = 0.0               # 법정 최저임금
    shortage: float = 0.0                    # 월 부족분

    # 신규 추가
    total_coefficient_hours: float = 0.0      # 총계수시간 (월)
    allowance_comparison: dict = field(...)   # 수당별 적정액 vs 포함액 비교
    is_valid_comprehensive: bool = True       # 포괄임금제 유효성
    validity_issues: list = field(...)        # 유효성 문제 목록
```

### 1.2 comprehensive_breakdown 확장 키

기존 키: `base`, `overtime_pay`, `night_pay`, `holiday_pay`, `other`

추가 지원 키:
```python
{
    "base": 2000000,           # 기본급
    "overtime_pay": 500000,    # 고정OT수당 (기존)
    "night_pay": 200000,       # 야간수당 (기존)
    "holiday_pay": 0,          # 휴일수당 (기존)
    "holiday_ot_pay": 0,       # 휴일8h초과수당 (신규)
    "duty_allowance": 100000,  # 직무수당 등 (신규)
    "welfare": 0,              # 복리후생비 (신규)
    "monthly_bonus": 0,        # 매월 지급 상여금 (신규)
    "annual_bonus": 0,         # 연간 고정 상여금 (신규, ÷12 월환산)
    "other": 0,                # 기타 (기존)
}
```

---

## 2. 핵심 로직 설계

### 2.1 역산 공식 (G1, G9)

```python
WEEKS_PER_MONTH = 365 / 7 / 12  # ≈ 4.345

def _calc_coefficient_hours(inp: WageInput) -> tuple[float, dict]:
    """총계수시간 산출 — 가산율 반영"""
    s = inp.schedule
    is_under5 = inp.business_size == BusinessSize.UNDER_5
    wpm = WEEKS_PER_MONTH

    # 기본시간 = (소정근로 + 주휴) × 주→월 환산
    weekly_paid = s.daily_work_hours * s.weekly_work_days
    weekly_holiday_hours_paid = s.daily_work_hours  # 주휴 8h (주15h 이상 시)
    if weekly_paid < 15:
        weekly_holiday_hours_paid = 0
    base_hours = (weekly_paid + weekly_holiday_hours_paid) * wpm

    # 가산율 (5인 미만 시 가산 없음)
    ot_mult   = 1.5 if not is_under5 else 1.0
    night_mult = 0.5 if not is_under5 else 0.0
    hol_mult  = 1.5 if not is_under5 else 1.0
    hol_ot_mult = 2.0 if not is_under5 else 1.0

    ot_coeff    = s.weekly_overtime_hours * ot_mult * wpm
    night_coeff = s.weekly_night_hours * night_mult * wpm
    hol_coeff   = s.weekly_holiday_hours * hol_mult * wpm
    hol_ot_coeff = s.weekly_holiday_overtime_hours * hol_ot_mult * wpm

    total = base_hours + ot_coeff + night_coeff + hol_coeff + hol_ot_coeff

    detail = {
        "기본시간": base_hours,
        "연장계수": ot_coeff,
        "야간계수": night_coeff,
        "휴일계수": hol_coeff,
        "휴일OT계수": hol_ot_coeff,
    }
    return total, detail
```

### 2.2 기본시급 역산

```python
# 역산 대상 총액 산출
total_monthly = monthly_wage  # 또는 breakdown 각 항목 합산
if annual_bonus > 0:
    total_monthly += annual_bonus / 12

# 기본시급 역산
effective_hourly = total_monthly / total_coefficient_hours
```

### 2.3 수당별 적정액 비교 (G2)

```python
def _calc_allowance_comparison(hourly: float, inp: WageInput, bd: dict) -> dict:
    """수당별 적정액 vs 포함액 비교"""
    s = inp.schedule
    is_under5 = inp.business_size == BusinessSize.UNDER_5
    wpm = WEEKS_PER_MONTH

    comparison = {}
    items = [
        ("연장수당", s.weekly_overtime_hours, 1.5 if not is_under5 else 1.0,
         bd.get("overtime_pay", 0)),
        ("야간수당", s.weekly_night_hours, 0.5 if not is_under5 else 0.0,
         bd.get("night_pay", 0)),
        ("휴일수당(8h이내)", s.weekly_holiday_hours, 1.5 if not is_under5 else 1.0,
         bd.get("holiday_pay", 0)),
        ("휴일수당(8h초과)", s.weekly_holiday_overtime_hours, 2.0 if not is_under5 else 1.0,
         bd.get("holiday_ot_pay", 0)),
    ]
    for name, hours, rate, included in items:
        if hours <= 0:
            continue
        proper = hourly * hours * rate * wpm
        diff = included - proper
        comparison[name] = {
            "적정액": round(proper),
            "포함액": round(included),
            "차액": round(diff),
            "판정": "적정" if diff >= -100 else "부족",  # 100원 오차 허용
        }
    return comparison
```

### 2.4 유효성 판단 (G3)

```python
def _check_validity(inp: WageInput) -> tuple[bool, list]:
    """포괄임금제 유효성 검사"""
    issues = []

    # 1. 교대제 + 일급/시급 → 적용 불가
    if inp.work_type in (WorkType.SHIFT_4_2, WorkType.SHIFT_3_2,
                         WorkType.SHIFT_3, WorkType.SHIFT_2, WorkType.ROTATING):
        issues.append(
            "교대제 근무자에게는 포괄임금제를 적용할 수 없습니다 "
            "(근로시간 산정이 객관적으로 어렵지 않음)"
        )
    if inp.wage_type in (WageType.HOURLY, WageType.DAILY):
        issues.append(
            "시급제·일급제 근로자에게는 포괄임금제를 적용할 수 없습니다"
        )

    # 2. 연장/야간/휴일 근로가 전혀 없는 경우
    s = inp.schedule
    if (s.weekly_overtime_hours == 0 and s.weekly_night_hours == 0
            and s.weekly_holiday_hours == 0 and s.weekly_holiday_overtime_hours == 0):
        issues.append(
            "연장·야간·휴일 근로가 없으면 포괄임금제 명목의 수당 미지급은 위법입니다 "
            "(대법원 2008다6052)"
        )

    is_valid = len(issues) == 0
    return is_valid, issues
```

### 2.5 5인 미만 사업장 처리 (G8)

- 가산수당 미적용: 연장 × 1.0, 야간 × 0.0, 휴일 × 1.0, 휴일OT × 1.0
- `_calc_coefficient_hours()`에서 `is_under5` 플래그로 자동 처리
- 경고 메시지: "5인 미만 사업장은 가산수당(×0.5) 미적용"

---

## 3. 법적 근거 (G6)

```python
legal = [
    "근로기준법 제56조 (연장·야간·휴일 근로)",
    "대법원 2024.12.26. 선고 2020다300299 (포괄임금 최저임금 판단 계산방법)",
    "대법원 2023.11.30. 선고 2019다29778 (연차수당 포함 시 법정 미달분 무효)",
    "대법원 2016.9.8. 선고 2014도8873 (근로시간 산정 곤란 요건)",
    "대법원 2010.5.13. 선고 2008다6052 (근로시간 계산 어렵지 않으면 포괄임금 불허)",
    "대법원 2009.12.10. 선고 2008다57852 (포괄임금제 성립 판단방법)",
    "대법원 1998.3.24. 선고 96다24699 (연차수당 포괄 포함 가능 여부)",
    "근로기준정책과-818 (2022.3.8, 포괄임금제 임금명세서 작성방법)",
]
```

---

## 4. 함수 리팩토링 계획

### 4.1 calc_comprehensive() 리팩토링

```
calc_comprehensive(inp, ow)
├── _check_validity(inp)           # 유효성 검사 (신규)
├── _calc_coefficient_hours(inp)   # 총계수시간 산출 (신규)
├── _calc_reverse_hourly(...)      # 기본시급 역산 (보완)
├── _calc_allowance_comparison(...)# 수당별 비교표 (신규)
├── _check_minimum_wage(...)       # 최저임금 검증 (기존 보완)
└── 결과 조립                      # ComprehensiveResult 반환
```

### 4.2 기존 로직과의 호환성

- `comprehensive_breakdown` 있는 경우: **경로 2** (기본급+수당 구분) → 기존처럼 breakdown에서 base 추출, 추가로 역산 검증
- `comprehensive_breakdown` 없는 경우: **경로 1** (정액급여) → 총액에서 역산하여 기본시급·수당 분리
- 기존 테스트 #3 호환 유지

---

## 5. 결과 출력 (G10)

### 5.1 breakdown 구조

```python
breakdown = {
    "역산 통상시급": "9,569원",
    "총계수시간(월)": "313.5h",
    "2026년 최저임금": "10,320원",
    "최저임금 충족": "❌",
    "월 부족분": "235,000원",
    "포괄임금 유효성": "✅" or "⚠️ 유효성 문제 있음",
    # 수당별 비교표
    "수당별 비교": {
        "연장수당": "적정 652,000원 / 포함 500,000원 / 부족 152,000원",
        "야간수당": "적정 104,000원 / 포함 200,000원 / 적정",
    },
    # 계수시간 상세
    "계수시간 상세": {
        "기본시간": "209.0h",
        "연장계수": "65.2h (10h × 1.5 × 4.345)",
        "야간계수": "8.7h (4h × 0.5 × 4.345)",
    },
}
```

### 5.2 _pop_comprehensive 보강 (facade.py)

```python
def _pop_comprehensive(r, result):
    result.summary["포괄임금 역산 시급"] = f"{r.effective_hourly:,.0f}원"
    result.summary["최저임금 충족"] = "✅" if r.is_minimum_wage_ok else "❌"
    result.summary["총계수시간"] = f"{r.total_coefficient_hours:.1f}h"
    if not r.is_valid_comprehensive:
        result.summary["포괄임금 유효성"] = "⚠️ 문제 있음"
    result.minimum_wage_ok = r.is_minimum_wage_ok
    return 0
```

---

## 6. 테스트 케이스 설계

| # | 설명 | 검증 포인트 |
|---|------|-------------|
| #65 | 정액급여 역산 (breakdown 없음, 월 300만, 연장 10h, 야간 4h) | 총계수시간, 역산 시급, 최저임금 판정 |
| #66 | 5인 미만 정액급여 역산 (월 250만, 연장 10h) | 가산수당 미적용, 계수시간 차이 |
| #67 | breakdown 있음 + 수당 부족 (OT포함 50만 < 적정 65만) | allowance_comparison 부족 판정 |
| #68 | 포괄임금 유효성 실패 — 교대제 | is_valid_comprehensive=False |
| #69 | 연간 상여금 월환산 포함 (연 240만 → 월 +20만) | annual_bonus ÷ 12 반영 |
| #70 | 휴일근로 8h 초과분 분리 (휴일 8h + 초과 4h) | holiday_ot_coeff 2.0배 반영 |

---

## 7. 구현 순서

| 단계 | 작업 | 파일 |
|------|------|------|
| 1 | ComprehensiveResult 필드 추가 | comprehensive.py |
| 2 | `_check_validity()` 구현 | comprehensive.py |
| 3 | `_calc_coefficient_hours()` 구현 | comprehensive.py |
| 4 | `calc_comprehensive()` 리팩토링 (역산 + 비교표) | comprehensive.py |
| 5 | `_pop_comprehensive()` 보강 | facade.py |
| 6 | 테스트 케이스 #65~#70 추가 + 기존 #3 호환 검증 | wage_calculator_cli.py |

---

## 8. 위험 요소

| 위험 | 대응 |
|------|------|
| 기존 테스트 #3 깨짐 | breakdown 있으면 기존 로직 우선 → 역산 검증은 추가 정보로 제공 |
| 역산 시급이 기존과 다른 값 | 역산은 `effective_hourly`에 반영, 기존 base÷hours는 `base_wage_hourly`로 분리 |
| 5인 미만 야간가산 0 처리 | 야간 근무 자체는 인정하되 가산수당(×0.5)만 미적용, 통상임금은 지급 |
