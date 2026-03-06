# Plan: 임금계산기 전체모듈 분석 및 효율화

## Executive Summary

| 관점 | 내용 |
|------|------|
| **Problem** | 19개 계산기 모듈이 개별적으로 성장하면서 중복 코드(parse_date 4곳, Result 보일러플레이트 18곳), 243줄짜리 facade.calculate(), 53필드 WageInput 등 유지보수성이 악화됨 |
| **Solution** | BaseResult 추출, 공통 유틸리티 통합, facade 디스패처 패턴 적용, WageInput 분리로 코드량 30% 감소 목표 |
| **Function UX Effect** | 계산 결과 동일 보장 (모든 테스트 36건 통과) + 신규 계산기 추가 시 보일러플레이트 90% 제거 |
| **Core Value** | 법률 변경·신규 계산기 추가 시 수정 포인트 최소화로 장기 유지보수 비용 절감 |

---

## 1. 현황 분석

### 1.1 코드베이스 규모

| 항목 | 수치 |
|------|------|
| 전체 파일 | 26개 (.py) |
| 전체 라인 | 6,097줄 |
| 계산기 모듈 | 19개 (calculators/ 17 + ordinary_wage + shift_work) |
| 테스트 케이스 | 36건 (wage_calculator_cli.py) |
| 지원 계산 유형 | 19종 (overtime ~ business_size) |

### 1.2 아키텍처 현황

```
WageInput → facade.calculate()
              ├── ordinary_wage.calc_ordinary_wage()  ← 모든 계산의 기반
              ├── calc_overtime(inp, ow)
              ├── calc_minimum_wage(inp, ow)
              ├── calc_weekly_holiday(inp, ow)
              ├── ... (14개 더)
              ├── calc_business_size(bsi)              ← 독립 함수
              └── generate_legal_hints(inp, ow, result)
           → WageResult
```

---

## 2. 발견된 문제점 (우선순위순)

### P1: 중복 코드 (HIGH)

| 중복 항목 | 발생 위치 | 영향 |
|-----------|----------|------|
| `_parse_date()` 함수 | annual_leave:187, severance:254, prorated:98, business_size:185 | 4곳 동일 함수 |
| Result 보일러플레이트 | 18개 계산기 전체 (breakdown/formulas/warnings/legal_basis) | 90줄 중복 |
| facade 계산기 호출 패턴 | facade.py:114-279 (18회 반복) | 165줄 → 50줄 가능 |
| 법적 근거 문자열 | 모든 계산기에 하드코딩 | 동일 법조문 여러 곳 산재 |
| `_ineligible()` 헬퍼 | severance:228, unemployment:287 | 유사 패턴 2곳 |

### P2: 구조적 문제 (MEDIUM)

| 문제 | 위치 | 설명 |
|------|------|------|
| WageInput 비대 | models.py:62-202 | 53개 필드, 단일 계산기 전용 필드 혼재 |
| facade.calculate() 과장 | facade.py:37-279 | 243줄 단일 메서드 |
| 파일 위치 불일치 | ordinary_wage.py, shift_work.py | calculators/ 밖에 위치 |
| 주당→월 환산 상수 미정의 | overtime:121, weekly_holiday:99 등 | 4.345 매직넘버 반복 |
| legal_hints 중복 분석 | legal_hints.py:64-95 | ordinary_wage와 동일 로직 재실행 |

### P3: 일관성 부족 (LOW)

| 문제 | 설명 |
|------|------|
| 검증 패턴 불통일 | _ineligible() vs 인라인 early return vs 없음 |
| 경고 중복 발행 | ordinary_wage + facade + legal_hints 다층 경고 |
| 하위 호환 상수 | constants.py:139-146 — get_insurance_rates() 사용 시 불필요 |
| WorkSchedule 모호성 | monthly_scheduled_hours vs shift_monthly_hours 우선순위 불명확 |

---

## 3. 리팩토링 계획

### Phase 1: 공통 기반 추출 (핵심)

**FR-01: `wage_calculator/base.py` 생성**

```python
@dataclass
class BaseCalculatorResult:
    breakdown: dict = field(default_factory=dict)
    formulas: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    legal_basis: list = field(default_factory=list)
```

- 18개 Result 데이터클래스가 이 클래스를 상속
- 각 Result는 도메인 특화 필드만 추가 정의
- 예상 삭제: 90줄 보일러플레이트

**FR-02: `wage_calculator/utils.py` 생성**

```python
def parse_date(s: str) -> date           # 4곳 통합
def format_krw(amount: int) -> str       # 원화 포맷
WEEKS_PER_MONTH = 365 / 7 / 12          # 매직넘버 제거
```

- _parse_date() 4곳 → utils.parse_date() 1곳
- 4.345 매직넘버 → WEEKS_PER_MONTH 상수

### Phase 2: facade 디스패처 패턴

**FR-03: facade.calculate() 리팩토링**

현재 (165줄 반복):
```python
if "overtime" in targets:
    ot = calc_overtime(inp, ow)
    result.summary["연장수당"] = f"{ot.monthly_overtime_pay:,.0f}원"
    result.breakdown["연장·야간·휴일수당"] = ot.breakdown
    result.formulas.extend(ot.formulas)
    all_warnings.extend(ot.warnings)
    all_legal.extend(ot.legal_basis)
    monthly_total += ot.monthly_overtime_pay
```

개선 (디스패처 + 헬퍼):
```python
CALCULATOR_REGISTRY = {
    "overtime": CalcEntry(calc_overtime, "연장·야간·휴일수당", ...),
    "minimum_wage": CalcEntry(calc_minimum_wage, "최저임금 검증", ...),
    ...
}

def _run_calculator(key, inp, ow, result, ...):
    entry = CALCULATOR_REGISTRY[key]
    calc_result = entry.func(inp, ow)
    # 공통 결과 병합 로직 (1곳)
```

- 243줄 → ~100줄 예상
- 신규 계산기 추가 시 registry 1줄 + 계산기 파일만 필요

### Phase 3: 모델 정리

**FR-04: 법적 근거 상수화**

```python
# wage_calculator/legal_constants.py
LABOR_LAW = {
    "ch56": "근로기준법 제56조 (연장·야간·휴일 근로)",
    "ch60": "근로기준법 제60조 (연차유급휴가)",
    ...
}
```

**FR-05: WEEKS_PER_MONTH 등 매직넘버 상수화**

```python
# constants.py 추가
WEEKS_PER_MONTH = 365 / 7 / 12   # ≈ 4.345
```

### Phase 4: 파일 구조 정리

**FR-06: ordinary_wage.py, shift_work.py 위치 이동**

- `wage_calculator/ordinary_wage.py` → `wage_calculator/calculators/ordinary_wage.py`
- `wage_calculator/shift_work.py` → shift_work 함수를 ordinary_wage.py에 병합
- import 경로 업데이트 (facade.py, __init__.py)

---

## 4. 범위 외 (명시적 제외)

| 제외 항목 | 이유 |
|-----------|------|
| WageInput 53필드 분리 | 챗봇 연동 인터페이스(from_analysis) 변경 필요 → 별도 PDCA |
| 테스트 프레임워크 도입 (pytest) | 현재 CLI 테스트 충분, 별도 과제 |
| legal_hints 로직 통합 | 경고 중복 제거만, 구조 변경은 별도 |
| 하위 호환 상수 제거 | 외부 참조 가능성 확인 후 별도 처리 |

---

## 5. 성공 기준

| 기준 | 목표 |
|------|------|
| 전체 테스트 통과 | 36/36 케이스 통과 (기능 동일 보장) |
| 코드 라인 감소 | 6,097줄 → 5,000줄 이하 (~18% 감소) |
| _parse_date 중복 제거 | 4곳 → 1곳 |
| Result 보일러플레이트 | 18곳 × 5줄 → 상속으로 0줄 |
| facade.calculate() 축소 | 243줄 → 120줄 이하 |
| 신규 계산기 추가 비용 | registry 1줄 + 계산기 파일만 |

---

## 6. 리스크

| 리스크 | 대응 |
|--------|------|
| import 경로 변경으로 외부 참조 깨짐 | __init__.py에서 기존 경로 re-export |
| 리팩토링 중 계산 로직 변경 | 매 단계 후 36건 테스트 실행 |
| chatbot.py의 from_analysis() 호환 | facade 인터페이스(WageCalculator.calculate) 유지 |

---

## 7. 구현 순서

| 순서 | 작업 | 예상 변경 파일 |
|------|------|---------------|
| 1 | base.py 생성 + BaseCalculatorResult | 신규 1 + 계산기 18 |
| 2 | utils.py 생성 + parse_date, WEEKS_PER_MONTH | 신규 1 + 4~6파일 |
| 3 | facade 디스패처 패턴 적용 | facade.py |
| 4 | ordinary_wage.py/shift_work.py 이동 + 병합 | 3~4파일 |
| 5 | 법적 근거 상수화 (선택) | constants.py + 계산기 일부 |
| 6 | 전체 테스트 + 정리 | wage_calculator_cli.py |
