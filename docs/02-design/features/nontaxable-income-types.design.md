# nontaxable-income-types Design Document

> **Summary**: NonTaxableIncome 7개 필드 확장 + 카테고리별 비과세 내역 그룹핑 출력
>
> **Project**: laborconsult (nodong.kr 노동법 Q&A + 임금계산기)
> **Date**: 2026-03-13
> **Status**: Draft
> **Planning Doc**: [nontaxable-income-types.plan.md](../../01-plan/features/nontaxable-income-types.plan.md)

---

## 1. Overview

### 1.1 Design Goals

1. nodong.kr/income_tax_except §2~§6 누락 항목 7개를 `NonTaxableIncome`에 추가
2. 기존 `_apply_cap()` 패턴 재사용으로 최소 변경
3. 무한도 항목(학자금·사택·경조금)은 `_apply_unlimited()` 신규 헬퍼로 처리
4. formulas 출력에 카테고리 헤더 추가 (`[§2 근로소득 미포함]` 등)

### 1.2 Design Principles

- **기존 패턴 준수**: `_apply_cap()` 재사용, 연간→월 환산 패턴(invention과 동일)
- **하위 호환**: 신규 필드 기본값 0.0, 기존 코드 영향 없음
- **YAGNI**: 매우 특수한 항목(선원식료품, 입갱수당, 군경특수수당)은 `other_nontaxable`로 위임

---

## 2. Architecture

### 2.1 변경 대상 컴포넌트

```
wage_calculator/
├── constants.py         # [수정] NON_TAXABLE_LIMITS + LEGAL_BASIS 확장
├── models.py            # [수정] NonTaxableIncome 7개 필드 추가
├── calculators/
│   └── insurance.py     # [수정] calc_nontaxable_total() 확장 + 카테고리 분류
└── __init__.py          # [확인] export 변경 불필요 (NonTaxableIncome 이미 export)
```

### 2.2 Dependencies

| Component | Depends On | Purpose |
|-----------|-----------|---------|
| 신규 7개 필드 | `NonTaxableIncome` | 입력 구조체 |
| 신규 4개 한도 | `NON_TAXABLE_LIMITS` | 연도별 한도 |
| `_apply_unlimited()` | `calc_nontaxable_total()` 내부 | 무한도 항목 공통 처리 |
| 카테고리 헤더 | `formulas` list | 출력 그룹핑 |

---

## 3. Data Model

### 3.1 NonTaxableIncome 확장 (models.py)

기존 15개 필드 뒤에 7개 추가:

```python
@dataclass
class NonTaxableIncome:
    # ── 기존 필드 (10+5) — 변경 없음 ─────────────────────────
    meal_allowance: float = 0.0
    car_subsidy: float = 0.0
    childcare_allowance: float = 0.0
    num_childcare_children: int = 0
    overtime_nontax: float = 0.0
    is_production_worker: bool = False
    prev_year_total_salary: float = 0.0
    overseas_pay: float = 0.0
    is_overseas_construction: bool = False
    research_subsidy: float = 0.0
    reporting_subsidy: float = 0.0
    remote_area_subsidy: float = 0.0
    invention_reward_annual: float = 0.0
    childbirth_support: float = 0.0
    other_nontaxable: float = 0.0

    # ── 신규 필드 (§2 근로소득 미포함) ─────────────────────────
    group_insurance_annual: float = 0.0     # 단체보장성보험료 (연간 총액)
    congratulatory_pay: float = 0.0         # 경조금 (월)

    # ── 신규 필드 (§3 실비변상적 급여) ─────────────────────────
    boarding_allowance: float = 0.0         # 승선수당 (월)
    relocation_subsidy: float = 0.0         # 지방이전 이주수당 (월)
    overnight_duty_pay: float = 0.0         # 일직·숙직료 (월)

    # ── 신규 필드 (§7 기타 비과세) ─────────────────────────────
    tuition_support: float = 0.0            # 근로자 학자금 (월 환산)
    company_housing: float = 0.0            # 사택 제공 이익 (월 환산)
```

### 3.2 from_dict() 변경

변경 불필요 — 기존 구현이 `cls.__dataclass_fields__`를 동적으로 참조하므로 신규 필드도 자동 매핑.

---

## 4. Constants 확장 (constants.py)

### 4.1 NON_TAXABLE_LIMITS 추가 키

```python
# 2025/2026 공통 (연도별 차이 없음)
"group_insurance_annual": 700_000,   # 단체보장성보험 연 70만원
"boarding":              200_000,    # 승선수당 월 20만원
"relocation":            200_000,    # 지방이전 이주수당 월 20만원
"overnight_duty":        200_000,    # 일직·숙직료 월 20만원 (실비변상 상한)
```

### 4.2 NON_TAXABLE_INCOME_LEGAL_BASIS 추가 엔트리

```python
"group_insurance": "소득세법 제12조제3호다목 (단체보장성보험료)",
"congratulatory":  "소득세법 시행규칙 제10조 (경조금)",
"boarding":        "소득세법 시행령 제12조제10호 (승선수당)",
"relocation":      "소득세법 시행령 제12조제17호 (지방이전 이주수당)",
"overnight_duty":  "소득세법 시행령 제12조제1호 (일직·숙직료)",
"tuition":         "소득세법 제12조제3호마목 (근로자 학자금)",
"company_housing": "소득세법 시행령 제38조 (사택 제공 이익)",
```

---

## 5. 핵심 함수 확장 (insurance.py)

### 5.1 _apply_unlimited() 신규 헬퍼

`_apply_cap()`과 대칭되는 무한도 항목용 내부 함수:

```python
def _apply_unlimited(value: float, label: str, legal_key: str) -> float:
    """한도 없는 비과세 항목 처리"""
    nonlocal total
    if value <= 0:
        return 0.0
    total += value
    formulas.append(f"{label} 비과세: {value:,.0f}원 (한도 없음)")
    legal.append(NON_TAXABLE_INCOME_LEGAL_BASIS[legal_key])
    return value
```

**위치**: `calc_nontaxable_total()` 내부, `_apply_cap()` 바로 아래.

### 5.2 calc_nontaxable_total() 확장 — 7개 항목 추가

기존 `# ── 기타 비과세` 블록 직전에 삽입:

```python
# ── §2 단체보장성보험료 (연간 → 월 환산) ─────────────────
if nti.group_insurance_annual > 0:
    cap = limits["group_insurance_annual"]
    applied_annual = min(nti.group_insurance_annual, cap)
    applied_monthly = applied_annual / 12
    total += applied_monthly
    formulas.append(
        f"단체보장성보험료 비과세: 연 {applied_annual:,.0f}원 "
        f"→ 월 {applied_monthly:,.0f}원 (한도 연 {cap:,.0f}원)"
    )
    legal.append(NON_TAXABLE_INCOME_LEGAL_BASIS["group_insurance"])
    if nti.group_insurance_annual > cap:
        warnings.append(
            f"단체보장성보험료: 연 {nti.group_insurance_annual:,.0f}원 중 "
            f"{cap:,.0f}원만 비과세"
        )

# ── §2 경조금 (무한도) ───────────────────────────────────
_apply_unlimited(nti.congratulatory_pay, "경조금", "congratulatory")

# ── §3 승선수당 ──────────────────────────────────────────
_apply_cap(nti.boarding_allowance, limits["boarding"], "승선수당", "boarding")

# ── §3 지방이전 이주수당 ─────────────────────────────────
_apply_cap(nti.relocation_subsidy, limits["relocation"], "지방이전 이주수당", "relocation")

# ── §3 일직·숙직료 ──────────────────────────────────────
if nti.overnight_duty_pay > 0:
    cap = limits["overnight_duty"]
    _apply_cap(nti.overnight_duty_pay, cap, "일직·숙직료", "overnight_duty")
    warnings.append("일직·숙직료: 실비변상 범위는 사내 규정 기준이며, 사회통념상 타당한 범위 내 비과세")

# ── §7 근로자 학자금 (무한도) ─────────────────────────────
_apply_unlimited(nti.tuition_support, "근로자 학자금", "tuition")

# ── §7 사택 제공 이익 (무한도) ────────────────────────────
_apply_unlimited(nti.company_housing, "사택 제공 이익", "company_housing")
```

### 5.3 카테고리 그룹핑 출력

`formulas` 리스트에 카테고리 헤더를 삽입하는 방식 대신, **기존 항목 순서를 섹션별로 정렬**하여 자연스럽게 그룹핑. 항목 출력 순서:

```
1. [§3 실비변상적 급여]: 자가운전보조금, 벽지수당, 연구보조비, 취재수당, 승선수당, 지방이전이주수당, 일직숙직료
2. [§4 비과세 식사대]: 식대
3. [§5 연장근로수당]: 생산직 OT
4. [§6 국외근로소득]: 국외근로, 해외건설
5. [§2 근로소득 미포함]: 단체보장성보험료, 경조금
6. [§7 기타 비과세]: 보육수당, 직무발명, 출산지원금, 학자금, 사택, 기타
```

구현 방식: 항목별 처리 순서를 위 순서로 재배치. 기존 동작 변경 없이 출력 순서만 조정.

---

## 6. Integration Point

### 6.1 _calc_employee() 변경

**변경 없음** — 기존 `calc_nontaxable_total()` 호출부가 그대로 동작. NonTaxableIncome의 신규 필드는 자동으로 `calc_nontaxable_total()`에서 처리.

### 6.2 __init__.py 변경

**변경 없음** — `NonTaxableIncome`은 이미 export되어 있고 dataclass 필드 추가는 import에 영향 없음.

---

## 7. Legal Hints 확장 (선택)

`legal_hints.py`의 `_hints_nontaxable()` — 기존 2개 힌트 유지. 신규 항목에 대한 힌트 추가는 불필요 (이미 `other_nontaxable` 안내와 상세 입력 권유 힌트가 존재).

---

## 8. Test Cases

### 8.1 신규 테스트

| ID | Test Case | Input | Expected |
|----|-----------|-------|----------|
| NT-09 (#111) | 단체보장성보험료 연 70만 한도 | `group_insurance_annual=800_000`, 월급 300만 | 비과세 연70만→월58,333원, warning "초과분 10만" |
| NT-10 (#112) | 승선수당 월 20만 한도 | `boarding_allowance=250_000`, 월급 300만 | 비과세 20만, warning "초과분 5만" |
| NT-11 (#113) | 근로자 학자금 무한도 | `tuition_support=1_000_000`, 월급 300만 | 비과세 100만 전액, warning 없음 |
| NT-12 (#114) | 경조금 무한도 | `congratulatory_pay=300_000`, 월급 300만 | 비과세 30만 전액 |
| NT-13 (#115) | 사택 제공 이익 무한도 | `company_housing=500_000`, 월급 400만 | 비과세 50만 전액 |
| NT-14 (#116) | 복합 13개 항목 | 기존10 + 신규3 (단체보험+학자금+승선), 월급 400만 | 합산 정확, 항목별 formulas 출력 |

### 8.2 기존 테스트 회귀

- `wage_calculator_cli.py` 전체 테스트 (#1~#110) 통과 확인
- NT-01~NT-08 결과 변경 없음 (신규 필드 기본값 0.0)

---

## 9. Implementation Order

### 9.1 순서 (6단계)

1. [ ] `constants.py` — `NON_TAXABLE_LIMITS`에 4개 키 추가 (2025, 2026 모두)
2. [ ] `constants.py` — `NON_TAXABLE_INCOME_LEGAL_BASIS`에 7개 엔트리 추가
3. [ ] `models.py` — `NonTaxableIncome`에 7개 필드 추가
4. [ ] `insurance.py` — `_apply_unlimited()` 헬퍼 추가 + 7개 항목 처리 로직 추가
5. [ ] `wage_calculator_cli.py` — NT-09~NT-14 테스트 케이스 추가
6. [ ] 기존 전체 테스트 통과 확인

### 9.2 변경 규모 예상

| File | Added Lines | Modified Lines |
|------|-------------|----------------|
| `constants.py` | ~15 | 0 |
| `models.py` | ~10 | 0 |
| `insurance.py` | ~40 | 0 |
| `wage_calculator_cli.py` | ~80 | 1 (import) |
| **Total** | **~145** | **1** |
