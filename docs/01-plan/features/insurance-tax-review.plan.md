# Plan: 4대보험료 / 근로소득세 계산식 리뷰 및 보완

## Executive Summary

| Perspective | Description |
|-------------|-------------|
| **Problem** | 현행 insurance.py의 4대보험 계산에서 원단위 절사 규칙 미적용, 건강보험 상·하한액 누락, 근로소득세가 간이세액표 대신 근사 산출식 사용 |
| **Solution** | nodong.kr/insure_cal 및 국세청 간이세액표 로직 기준으로 절사 규칙, 상한/하한, 자녀세액공제 보완 |
| **Function UX Effect** | 실수령액 계산 정확도 향상 (현재 수백~수천원 오차 → 10원 이내 일치) |
| **Core Value** | nodong.kr 공식 계산기와 동일한 결과를 산출하여 신뢰성 확보 |

---

## 1. AS-IS 분석 (현행 구현 리뷰)

### 1.1 현행 파일 구조

| File | Role |
|------|------|
| `wage_calculator/constants.py` | INSURANCE_RATES (연도별 요율), INCOME_TAX_BRACKETS, EARNED_INCOME_DEDUCTION |
| `wage_calculator/calculators/insurance.py` | calc_insurance() (근로자), calc_employer_insurance() (사업주), _calc_freelancer() |
| `wage_calculator/models.py` | WageInput.tax_dependents, monthly_non_taxable, is_freelancer |

### 1.2 발견된 GAP (nodong.kr 대비)

#### GAP-1: 국민연금 기준소득월액 1,000원 미만 절사 미적용
- **nodong.kr**: "1,000원미만은 제외(절사)하고 계산" → 3,512,990원 → 3,512,000원
- **현행 코드**: `round(pension_base * pension_rate)` — Python round() 사용 (반올림)
- **영향**: 최대 450원 오차 (4.5% × 999원)

#### GAP-2: 건강보험 보수월액 상한/하한 누락
- **nodong.kr**: 상한 월 8,481,420원 (근로자 4,240,710원), 하한 월 19,780원
- **현행 코드**: 상한/하한 없이 `gross * health_rate` 그대로 적용
- **영향**: 초고소득자(월 1억+)에서 건강보험료 과다 산출

#### GAP-3: 보험료 원단위 처리 규칙 불일치
- **nodong.kr**: 각 보험별 원단위 절사 규칙 (10원 미만 절사 등)
- **현행 코드**: `round()` (반올림) — 절사(truncation)가 아님
- **영향**: 보험료별 최대 10원 오차

#### GAP-4: 근로소득세 — 간이세액표 vs 근사 산출식
- **nodong.kr**: 국세청 간이세액표 (월급여 구간 × 부양가족 수 → 세액 조회)
- **현행 코드**: 연간 과세표준 산출 → 누진세율 적용 → 12로 나누기 (근사 방식)
- **영향**: 간이세액표와 수만원 차이 가능 (특히 저소득/고소득 구간)
- **평가**: 현행 방식도 합리적이나, nodong.kr과 정확히 일치시키려면 간이세액표 내장 필요

#### GAP-5: 자녀세액공제 미구현
- **nodong.kr**: 8~20세 자녀 공제 (1명: 20,830원/월, 2명: 45,830원/월, 3명+: 45,830 + 33,330 × 추가)
- **현행 코드**: tax_dependents로 인적공제만 반영, 자녀세액공제 별도 미구현
- **영향**: 자녀 있는 근로자의 소득세 과다 산출

#### GAP-6: 산재보험 세부 구성요소 미반영
- **nodong.kr**: 산재보험료 = 업종요율 + 출퇴근(0.6%) + 임금채권(0.9%) + 석면(0.03%)
- **현행 코드**: 단일 요율(기본 0.7%)로 단순화
- **영향**: 사업주 보험료 정확도 저하 (근로자 부담 없으므로 근로자 계산에는 무관)

---

## 2. TO-BE 개선 계획

### 2.1 우선순위 (Impact × Effort)

| Priority | GAP | Impact | Effort | Action |
|:--------:|------|--------|--------|--------|
| P1 | GAP-1 | High | Low | 국민연금 1,000원 절사 적용 |
| P1 | GAP-2 | High | Low | 건강보험 상한/하한 추가 |
| P1 | GAP-3 | Medium | Low | 보험료 절사(truncation) 규칙 적용 |
| P2 | GAP-5 | Medium | Medium | 자녀세액공제 구현 |
| P3 | GAP-4 | Low | High | 간이세액표 내장 (검토 후 결정) |
| P3 | GAP-6 | Low | Low | 산재보험 구성요소 분리 (사업주 계산기만) |

### 2.2 세부 변경 계획

#### Step 1: constants.py — 상수 보완
```
추가할 상수:
- HEALTH_INSURANCE_UPPER_LIMIT: {2025: 8_481_420, ...}  # 건강보험 보수월액 상한
- HEALTH_INSURANCE_LOWER_LIMIT: {2025: 19_780, ...}     # 건강보험 보수월액 하한
- CHILD_TAX_CREDIT_MONTHLY: 자녀세액공제 월 금액 테이블
- INDUSTRIAL_ACCIDENT_COMPONENTS: 산재보험 구성요소별 요율
```

#### Step 2: insurance.py — 계산 로직 보완

**국민연금 절사 규칙:**
```python
# AS-IS
pension_base = max(pension_min, min(gross, pension_max))
national_pension = round(pension_base * pension_rate)

# TO-BE
pension_base = (max(pension_min, min(gross, pension_max)) // 1000) * 1000  # 1,000원 절사
national_pension = int(pension_base * pension_rate)  # 원 미만 절사
```

**건강보험 상한/하한:**
```python
# TO-BE
health_base = max(health_min, min(gross, health_max))
health_insurance = int(health_base * health_rate)  # 원 미만 절사
```

**장기요양보험:**
```python
# TO-BE: 원 미만 절사
long_term_care = int(health_insurance * ltc_rate)
```

**고용보험:**
```python
# TO-BE: 원 미만 절사
employment_insurance = int(gross * emp_rate)
```

**자녀세액공제:**
```python
# TO-BE
child_credit_monthly = _calc_child_tax_credit(inp.num_children_8_to_20)
income_tax = max(0, income_tax_before_credit - child_credit_monthly)
```

#### Step 3: models.py — 필드 추가
```
추가 필드:
- num_children_8_to_20: int = 0  # 8~20세 자녀 수 (자녀세액공제용)
```

#### Step 4: 사업주 계산기 — 산재보험 구성요소 분리
```python
# TO-BE
commute_rate = 0.006         # 출퇴근보험료율 0.6%
wage_claim_rate = 0.009      # 임금채권부담금 0.9%
asbestos_rate = 0.0003       # 석면피해구제 0.03%
total_accident_rate = industry_rate + commute_rate + wage_claim_rate + asbestos_rate
```

---

## 3. GAP-4 (간이세액표) 검토

### 현행 근사 방식의 타당성
- 연간 과세표준 → 누진세율 → 월 환산 방식은 **법률 기반 계산**으로 원칙적으로 정확
- 간이세액표는 국세청이 이 공식에 부양가족별 보정을 적용하여 **미리 계산한 조회표**
- 현행 방식에서 인적공제(부양가족 × 150만원) + 표준세액공제(13만원)를 적용하고 있어 합리적

### 간이세액표 내장 시 고려사항
- 표 크기: ~500행 × 11열 = 5,500+ 데이터 포인트
- 매년 갱신 필요 (국세청 고시)
- 구현 복잡도 대비 정확도 향상 폭이 제한적

### 결론
- **P3 (후순위)**: 현행 근사 방식 유지, 자녀세액공제 추가로 정확도 개선
- 향후 필요 시 간이세액표 CSV/JSON 내장 가능

---

## 4. 검증 기준

### nodong.kr/insure_cal 교차 검증 케이스
| Case | 월급여 | 비과세 | 부양가족 | 검증 항목 |
|------|--------|--------|----------|-----------|
| A | 3,000,000 | 200,000 | 1인 | 4대보험 + 소득세 전 항목 |
| B | 6,170,000 | 200,000 | 3인 | 국민연금 상한 적용 |
| C | 10,000,000 | 200,000 | 4인(자녀2) | 건강보험 상한 + 자녀공제 |
| D | 2,000,000 | 0 | 1인 | 최저소득 구간 |
| E | 350,000 | 0 | 1인 | 국민연금 하한 적용 |

---

## 5. 영향 범위

### 변경 파일
| File | Change Type |
|------|-------------|
| `wage_calculator/constants.py` | 건강보험 상한/하한, 자녀세액공제 상수 추가 |
| `wage_calculator/models.py` | num_children_8_to_20 필드 추가 |
| `wage_calculator/calculators/insurance.py` | 절사 규칙, 상한/하한, 자녀공제 적용 |
| `wage_calculator_cli.py` | 검증 테스트 케이스 추가 |

### 하위 호환성
- 기존 WageInput에 num_children_8_to_20=0 기본값 → 기존 호출 영향 없음
- 보험료 금액이 소폭 변경 (절사 규칙 적용으로 기존 round()보다 약간 낮아짐)
- 기존 테스트 케이스 일부 기대값 조정 필요할 수 있음

---

## 6. 비적용 항목

| 항목 | 사유 |
|------|------|
| 간이세액표 전체 내장 | 데이터량 과다, 매년 갱신 필요, 현행 근사 방식 충분 |
| 건설업 산재보험 특례 | 건설업 특수 공식 (총공사금액 × 노무비율 × 보험요율) — 범용 아님 |
| 외국인 보험 특례 | 외국인 근로자 국민연금/건강보험 임의가입 — 별도 규정 |
