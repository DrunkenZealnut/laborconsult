# Design: 전체 계산기 모듈 리뷰 및 코드 정돈

> **Plan 참조**: `docs/01-plan/features/calculator-module-review.plan.md`

---

## 1. 설계 개요

본 설계서는 wage_calculator 패키지와 프로젝트 전체의 코드 위생(hygiene) 개선을 위한 구체적 실행 명세를 정의한다. 계산 로직은 변경하지 않으며, 파일 정리·import 표준화·docstring 추가만 수행한다.

---

## 2. 현재 상태 분석

### 2.1 파일 구조

```
wage_calculator/                 # 정상 파일 9개 + 중복 8개
├── __init__.py                  │ __init__ 2.py
├── models.py                   │ models 2.py
├── facade.py                   │ facade 2.py
├── constants.py                │ constants 2.py  ← 2024~2026 누락!
├── result.py                   │ result 2.py
├── legal_hints.py              │ legal_hints 2.py
├── ordinary_wage.py            │ ordinary_wage 2.py
├── base.py                     │ base 2.py
├── utils.py                    │ utils 2.py
└── calculators/                 # 정상 24개 + 중복 20개
    ├── __init__.py              │ __init__ 2.py
    ├── annual_leave.py          │ annual_leave 2.py  ← 287줄 누락!
    ├── average_wage.py          (신규 — 중복 없음)
    ├── business_size.py         │ business_size 2.py
    ├── compensatory_leave.py    │ compensatory_leave 2.py
    ├── comprehensive.py         │ comprehensive 2.py
    ├── dismissal.py             │ dismissal 2.py
    ├── eitc.py                  (신규 — 중복 없음)
    ├── flexible_work.py         │ flexible_work 2.py
    ├── industrial_accident.py   (신규 — 중복 없음)
    ├── insurance.py             │ insurance 2.py
    ├── maternity_leave.py       │ maternity_leave 2.py
    ├── minimum_wage.py          │ minimum_wage 2.py
    ├── ordinary_wage.py         │ ordinary_wage 2.py
    ├── overtime.py              │ overtime 2.py
    ├── parental_leave.py        │ parental_leave 2.py
    ├── prorated.py              │ prorated 2.py
    ├── public_holiday.py        │ public_holiday 2.py
    ├── retirement_pension.py    (신규 — 중복 없음)
    ├── retirement_tax.py        (신규 — 중복 없음)
    ├── severance.py             │ severance 2.py
    ├── unemployment.py          │ unemployment 2.py
    ├── wage_arrears.py          │ wage_arrears 2.py
    └── weekly_holiday.py        │ weekly_holiday 2.py
```

**중복 파일 수**: wage_calculator/ 내 28개, 프로젝트 전체 378개

### 2.2 Import 분석

| 상태 | 파일 수 | 파일 |
|------|---------|------|
| PEP 8 준수 | 2개 | legal_hints.py, 기타 top-level (단순) |
| PEP 8 미준수 | 18개 | 모든 17개 calculator 파일 + facade.py |

**공통 문제**: stdlib 그룹과 local 그룹 사이에 빈 줄 없음

### 2.3 `_pop_*` 함수 (facade.py)

21개 함수 모두 docstring 없음:
`_pop_overtime`, `_pop_minimum_wage`, `_pop_weekly_holiday`, `_pop_annual_leave`,
`_pop_dismissal`, `_pop_comprehensive`, `_pop_prorated`, `_pop_public_holiday`,
`_pop_average_wage`, `_pop_severance`, `_pop_unemployment`, `_pop_insurance`,
`_pop_employer_insurance`, `_pop_compensatory_leave`, `_pop_parental_leave`,
`_pop_maternity_leave`, `_pop_flexible_work`, `_pop_retirement_tax`,
`_pop_retirement_pension`, `_pop_eitc`, `_pop_industrial_accident`

---

## 3. 구현 명세

### 3.1 Phase 1: 중복 파일 삭제 (P0)

#### 3.1.1 wage_calculator/ 중복 삭제 (28개)

삭제 대상 — 파일명에 `" 2"` 포함된 모든 파일:

```bash
# 실행 명령 (단일 커맨드)
find wage_calculator -name "* 2.*" -delete
```

**삭제 확인**: `" 2"` 파일은 공백 포함 파일명이므로 Python에서 직접 import 불가. 어떤 코드에서도 참조되지 않음.

#### 3.1.2 프로젝트 루트 중복 삭제 (~350개)

```bash
# 프로젝트 전체 (wage_calculator 외)
find . -name "* 2*" -not -path "./.git/*" -not -path "./wage_calculator/*" -delete
```

**삭제 제외**: `.git/` 디렉토리

#### 3.1.3 검증

```bash
# 중복 파일 0개 확인
find . -name "* 2*" -not -path "./.git/*" | wc -l
# 예상 결과: 0

# 테스트 통과 확인
python3 wage_calculator_cli.py
# 예상 결과: ✅ 85개 테스트 완료
```

---

### 3.2 Phase 2: Import 정렬 (P1)

#### 3.2.1 표준 Import 순서

모든 `.py` 파일에 적용:

```python
# 그룹 1: stdlib
from dataclasses import dataclass, field
from datetime import date, timedelta
import math

# 그룹 2: local (relative imports)
from ..base import BaseCalculatorResult
from ..constants import MINIMUM_WAGES
from ..models import WageInput, WageType
from ..utils import parse_date
from .ordinary_wage import OrdinaryWageResult
```

규칙:
1. **stdlib 그룹** → **빈 줄 1개** → **local 그룹**
2. 각 그룹 내 알파벳 순 정렬
3. `from X import Y` 형태 우선, 다중 import는 줄 바꿈

#### 3.2.2 수정 대상 파일 (18개)

**calculators/**:
1. `overtime.py` — `dataclasses` ↔ `..base` 사이 빈 줄 추가
2. `minimum_wage.py` — 동일
3. `weekly_holiday.py` — `dataclasses, datetime` ↔ local 사이 빈 줄 추가
4. `annual_leave.py` — 동일
5. `dismissal.py` — 동일
6. `comprehensive.py` — 동일
7. `prorated.py` — `calendar, dataclasses` ↔ local 사이 빈 줄 추가
8. `public_holiday.py` — `dataclasses, datetime` ↔ local 사이 빈 줄 추가
9. `insurance.py` — 동일
10. `severance.py` — 동일
11. `unemployment.py` — 동일
12. `compensatory_leave.py` — 동일
13. `wage_arrears.py` — `dataclasses, typing, datetime` ↔ local 사이 빈 줄 추가
14. `parental_leave.py` — 동일
15. `maternity_leave.py` — 동일
16. `flexible_work.py` — `dataclasses, typing` ↔ local 사이 빈 줄 추가
17. `business_size.py` — `calendar, dataclasses` ↔ local 사이 빈 줄 추가

**top-level**:
18. `facade.py` — import 블록 정리 (현재도 기능상 문제 없으나 그룹 구분 추가)

#### 3.2.3 facade.py import 재정렬

현재 (모든 import가 한 블록):
```python
from .models import WageInput, WageType, BusinessSize
from .calculators.ordinary_wage import calc_ordinary_wage
from .calculators.overtime import calc_overtime, check_weekly_hours_compliance
...
```

변경 후:
```python
from .calculators.average_wage import calc_average_wage
from .calculators.business_size import calc_business_size
from .calculators.compensatory_leave import calc_compensatory_leave
from .calculators.comprehensive import calc_comprehensive
from .calculators.dismissal import calc_dismissal
from .calculators.eitc import calc_eitc
from .calculators.flexible_work import calc_flexible_work
from .calculators.industrial_accident import calc_industrial_accident
from .calculators.insurance import calc_insurance, calc_employer_insurance
from .calculators.maternity_leave import calc_maternity_leave
from .calculators.minimum_wage import calc_minimum_wage
from .calculators.ordinary_wage import calc_ordinary_wage
from .calculators.overtime import calc_overtime, check_weekly_hours_compliance
from .calculators.parental_leave import calc_parental_leave
from .calculators.prorated import calc_prorated
from .calculators.public_holiday import calc_public_holiday
from .calculators.retirement_pension import calc_retirement_pension
from .calculators.retirement_tax import calc_retirement_tax
from .calculators.severance import calc_severance
from .calculators.unemployment import calc_unemployment
from .calculators.wage_arrears import calc_wage_arrears
from .calculators.weekly_holiday import calc_weekly_holiday
from .legal_hints import generate_legal_hints, format_hints, LegalHint
from .models import WageInput, WageType, BusinessSize
from .result import WageResult, format_result, format_result_json
```

> 모든 local import이므로 빈 줄 구분 없이 알파벳 순 정렬.

---

### 3.3 Phase 3: `_pop_*` Docstring 추가 (P2)

#### 3.3.1 Docstring 형식

```python
def _pop_overtime(r, result):
    """result.summary에 연장/야간/휴일수당(월) 추가. 반환: monthly_overtime_pay."""
```

#### 3.3.2 전체 docstring 목록

| 함수 | docstring | 반환값 설명 |
|------|-----------|------------|
| `_pop_overtime` | `연장/야간/휴일수당(월) 추가` | `monthly_overtime_pay` |
| `_pop_minimum_wage` | `최저임금 충족 여부·실질시급 추가` | `0` |
| `_pop_weekly_holiday` | `주휴수당(월) 추가` | `0` |
| `_pop_annual_leave` | `연차수당·미사용일수·차감·비례·정산 추가` | `0` |
| `_pop_dismissal` | `해고예고수당 추가` | `0` |
| `_pop_comprehensive` | `포괄임금 역산 시급·계수시간·최저임금 충족 추가` | `0` |
| `_pop_prorated` | `일할계산 임금·근무일수 추가` | `0` |
| `_pop_public_holiday` | `유급공휴일 수당·적용여부 추가` | `holiday_pay/12 or 0` |
| `_pop_average_wage` | `1일 평균임금·적용기준·3개월 임금총액 추가` | `0` |
| `_pop_severance` | `퇴직금·평균임금·계속근로기간 추가` | `0` |
| `_pop_unemployment` | `구직급여 일액·급여일수·총급여·조기재취업수당 추가` | `0` |
| `_pop_insurance` | `세전급여·세후실수령액·공제액·4대보험합계 추가` | `0` |
| `_pop_employer_insurance` | `사업주 4대보험 합계·총인건비 추가` | `0` |
| `_pop_compensatory_leave` | `보상휴가 시간·미사용수당(월) 추가` | `0` |
| `_pop_parental_leave` | `육아휴직 월수령액·총수령액·사후지급금 추가` | `0` |
| `_pop_maternity_leave` | `출산전후휴가 급여·보험지급액·배우자휴가 추가` | `0` |
| `_pop_flexible_work` | `탄력제 연장수당(월)·연장근로시간 추가` | `monthly_overtime_pay` |
| `_pop_retirement_tax` | `퇴직소득세·지방소득세·실수령퇴직금 추가` | `0` |
| `_pop_retirement_pension` | `퇴직연금 유형·수령액·운용수익 추가` | `0` |
| `_pop_eitc` | `근로장려금·자녀장려금·합계·소득구간 추가` | `0` |
| `_pop_industrial_accident` | `평균임금·휴업/장해/유족/장례비·산재합계 추가` | `0` |

---

## 4. 구현 순서

```
Step 1: 중복 파일 삭제 (wage_calculator/ 28개)
  ↓
Step 2: 테스트 실행 → 85/85 확인
  ↓
Step 3: 프로젝트 루트 중복 파일 삭제 (~350개)
  ↓
Step 4: 테스트 재실행 → 85/85 확인
  ↓
Step 5: Import 정렬 (18개 파일)
  ↓
Step 6: 테스트 재실행 → 85/85 확인
  ↓
Step 7: _pop_* docstring 추가 (facade.py, 21개 함수)
  ↓
Step 8: 최종 테스트 → 85/85 확인
```

---

## 5. 변경 범위 요약

| 카테고리 | 파일 수 | 변경 유형 |
|----------|---------|-----------|
| 중복 삭제 (wage_calculator/) | 28개 삭제 | 파일 삭제 |
| 중복 삭제 (프로젝트 루트) | ~350개 삭제 | 파일 삭제 |
| Import 정렬 | 18개 수정 | 빈 줄 추가 + 순서 정렬 |
| Docstring 추가 | 1개 수정 (facade.py) | 21줄 추가 |
| **코드 로직 변경** | **0개** | **없음** |

---

## 6. 검증 기준

- [ ] `find . -name "* 2*" -not -path "./.git/*" | wc -l` → **0**
- [ ] `python3 wage_calculator_cli.py` → **✅ 85개 테스트 완료**
- [ ] 모든 calculator 파일 stdlib↔local 사이 빈 줄 존재
- [ ] facade.py import 알파벳 순 정렬
- [ ] 21개 `_pop_*` 함수 모두 docstring 보유
- [ ] `python3 -c "from wage_calculator import WageCalculator"` → 에러 없음
