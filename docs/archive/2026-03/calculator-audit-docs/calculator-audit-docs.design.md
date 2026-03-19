# calculator-audit-docs Design Document

> **Summary**: 24개 임금계산기의 설정값·계산과정·법적 근거를 노무사 검토용 감사문서로 체계화
>
> **Project**: laborconsult (nodong.kr AI 노동상담 챗봇)
> **Author**: PDCA
> **Date**: 2026-03-08
> **Status**: Draft
> **Planning Doc**: [calculator-audit-docs.plan.md](../01-plan/features/calculator-audit-docs.plan.md)

---

## 1. Overview

### 1.1 Design Goals

1. 비개발자(노무사)가 코드 없이 모든 계산 로직을 검증할 수 있는 문서 생성
2. 코드 내 실제 상수·공식과 100% 일치하는 정확한 문서
3. 법령 개정 시 수정 포인트를 즉시 파악할 수 있는 구조

### 1.2 Design Principles

- **코드 추적성**: 모든 상수·공식에 소스 파일명과 라인 위치 표시
- **법적 근거 완전성**: 모든 계산 단계에 법조문 또는 판례 번호 1개 이상 매핑
- **독립 리뷰 가능**: 계산기별 분리 → 특정 모듈만 선택하여 리뷰 가능
- **한글 우선**: 공식·변수명 모두 한글 표기 (코드 참조용 영문 병기)

---

## 2. Architecture

### 2.1 문서 구조도

```
docs/calculator-audit/
│
├── README.md                          ← 목차 + 리뷰 가이드 (진입점)
│
├── [공통 참조 문서]
│   ├── 00-constants-reference.md      ← 상수 총람
│   ├── 00-calculator-overview.md      ← 24개 계산기 요약표
│   ├── 00-legal-case-mapping.md       ← 판례 반영 현황
│   └── 00-annual-update-checklist.md  ← 법령 개정 체크리스트
│
└── [개별 감사 시트] (01~24)
    ├── 01-ordinary-wage.audit.md      ← 통상임금
    ├── 02-overtime.audit.md           ← 연장·야간·휴일수당
    ├── ...
    └── 24-eitc.audit.md               ← 근로장려금
```

### 2.2 문서 간 참조 관계

```
README.md (목차)
  │
  ├─→ 00-calculator-overview.md ──→ 각 감사 시트로 링크
  │
  ├─→ 00-constants-reference.md ←── 각 감사 시트에서 참조
  │
  ├─→ 00-legal-case-mapping.md ←── 각 감사 시트에서 판례 참조
  │
  └─→ 01~24-*.audit.md
       ├─→ constants-reference.md (상수 참조)
       └─→ 01-ordinary-wage.audit.md (통상임금 의존 계산기)
```

### 2.3 소스 코드 ↔ 문서 매핑

| 소스 파일 | 문서 |
|-----------|------|
| `wage_calculator/constants.py` | `00-constants-reference.md` |
| `wage_calculator/models.py` | 각 감사 시트 §2 입력 항목 |
| `wage_calculator/legal_hints.py` | `00-legal-case-mapping.md` |
| `wage_calculator/facade.py` | `00-calculator-overview.md` |
| `wage_calculator/calculators/*.py` | `01~24-*.audit.md` |

---

## 3. 공통 참조 문서 상세 설계

### 3.1 README.md — 목차 + 리뷰 가이드

```markdown
# 임금계산기 감사 문서

## 리뷰 가이드
- 이 문서는 nodong.kr AI 노동상담 챗봇의 임금계산기 모듈을 노무사가 검토할 수 있도록 작성되었습니다
- 각 감사 시트는 "입력 → 적용 상수 → 계산 과정 → 출력" 순서로 구성됩니다
- 법적 근거(법조문/판례)는 각 계산 단계에 직접 표기됩니다

## 리뷰 우선순위
1. 핵심 계산기 (High): 통상임금, 연장수당, 최저임금, 퇴직금, 4대보험, 연차
2. 중요 계산기 (Medium): 주휴수당, 해고예고, 실업급여, 포괄임금, 육아/출산, 체불
3. 보조 계산기 (Low): 탄력근로, 보상휴가, 일할계산, 유급공휴일, 산재, 세금, EITC 등

## 문서 목록
- [상수 총람](00-constants-reference.md)
- [계산기 개요표](00-calculator-overview.md)
- [판례 반영 현황](00-legal-case-mapping.md)
- [법령 개정 체크리스트](00-annual-update-checklist.md)
- [01. 통상임금](01-ordinary-wage.audit.md) ~ [24. 근로장려금](24-eitc.audit.md)

## 기준 시점
- 상수 기준: 2025년 / 2026년 (코드 내 연도별 상수 반영)
- 판례 기준: 대법원 2023다302838 (2024.12.19 선고) 포함
- 코드 버전: {git commit hash}
```

### 3.2 00-constants-reference.md — 상수 총람

`constants.py`의 모든 상수를 다음 카테고리별 테이블로 정리:

#### 3.2.1 최저임금 (MINIMUM_HOURLY_WAGE)

| 연도 | 시급(원) | 월환산액(209h) | 전년 대비 | 코드 위치 |
|------|---------|---------------|----------|----------|
| 2020 | 8,590 | 1,795,310 | — | constants.py:14 |
| ... | ... | ... | ... | ... |
| 2026 | 10,320 | 2,156,880 | +2.9% | constants.py:20 |

> **법적 근거**: 최저임금법 제10조 (최저임금의 결정)

#### 3.2.2 근로기준법 가산율

| 항목 | 상수명 | 값 | 의미 | 법적 근거 | 코드 위치 |
|------|--------|-----|------|----------|----------|
| 연장근로 | OVERTIME_RATE | 0.5 | 기본 1.0 + 가산 0.5 = 총 1.5배 | 근기법 제56조제1항 | constants.py:36 |
| 야간근로 | NIGHT_PREMIUM_RATE | 0.5 | 22시~06시, 연장과 중복 적용 | 근기법 제56조제2항 | constants.py:37 |
| 휴일근로(8h 이내) | HOLIDAY_RATE | 0.5 | 총 1.5배 | 근기법 제56조제2항 | constants.py:38 |
| 휴일근로(8h 초과) | HOLIDAY_OT_RATE | 0.5 | 총 2.0배 (1.0 + 0.5 + 0.5) | 근기법 제56조제2항 | constants.py:39 |

#### 3.2.3 월 기준시간

| 상수명 | 값 | 산출식 | 법적 근거 | 코드 위치 |
|--------|-----|--------|----------|----------|
| MONTHLY_STANDARD_HOURS | 209h | (주 40h + 주휴 8h) × 52주 ÷ 12월 | 근기법 시행령 제6조 | constants.py:43 |

#### 3.2.4 4대보험 요율 (INSURANCE_RATES)

| 항목 | 2025년 | 2026년 | 전체 요율 | 근로자 부담 | 법적 근거 | 코드 위치 |
|------|--------|--------|----------|------------|----------|----------|
| 국민연금 | 4.5% | 4.75% | 9.0%→9.5% | 절반 | 국민연금법 제88조 | constants.py:115,126 |
| 건강보험 | 3.545% | 3.595% | 7.09%→7.19% | 절반 | 국민건강보험법 제73조 | constants.py:116,127 |
| 장기요양 | 12.95% | 13.14% | 건보료 기준 | 건보료×비율 | 노인장기요양보험법 제9조 | constants.py:117,128 |
| 고용보험 | 0.9% | 0.9% | 1.8% | 절반 | 고용보험법 제56조 | constants.py:118,129 |
| 산재보험 | 0% | 0% | 업종별 | 사업주 전액 | 산재보험법 제13조 | constants.py:152 |

**상·하한액**:

| 항목 | 2025년 | 코드 위치 |
|------|--------|----------|
| 국민연금 상한 | 6,170,000원 | constants.py:119 |
| 국민연금 하한 | 390,000원 | constants.py:120 |
| 건강보험 상한 | 4,240,710원 | constants.py:121 |
| 건강보험 하한 | 9,890원 | constants.py:122 |

#### 3.2.5 근로소득세 세율 (INCOME_TAX_BRACKETS)

| 과세표준 | 세율 | 누진공제 | 코드 위치 |
|---------|------|---------|----------|
| ~1,400만원 | 6% | 0 | constants.py:163 |
| ~5,000만원 | 15% | 126만원 | constants.py:164 |
| ~8,800만원 | 24% | 576만원 | constants.py:165 |
| ~1.5억원 | 35% | 1,544만원 | constants.py:166 |
| ~3억원 | 38% | 1,994만원 | constants.py:167 |
| ~5억원 | 40% | 2,594만원 | constants.py:168 |
| ~10억원 | 42% | 3,594만원 | constants.py:169 |
| 10억원 초과 | 45% | 6,594만원 | constants.py:170 |

> **법적 근거**: 소득세법 제55조 (세율)

#### 3.2.6 기타 상수 (모두 포함)

- 연차 관련 (ANNUAL_LEAVE_BASE_DAYS 등)
- 퇴직 관련 (SEVERANCE_MIN_SERVICE_DAYS, AVG_WAGE_PERIOD_DAYS)
- 해고 관련 (DISMISSAL_NOTICE_DAYS)
- 휴업 관련 (SHUTDOWN_RATE)
- 수습 관련 (PROBATION_MIN_WAGE_RATE)
- 최저임금 산입범위 (MIN_WAGE_INCLUSION_RATES)
- 교대근무 월 소정근로시간 (SHIFT_MONTHLY_HOURS)
- 구직급여 상한액 (UNEMPLOYMENT_BENEFIT_UPPER)
- 산재 관련 (DISABILITY_GRADE_TABLE 등)
- 퇴직소득세 (RETIREMENT_SERVICE_DEDUCTION 등)
- 근로장려금 (EITC_PARAMS 등)
- 자녀세액공제 (CHILD_TAX_CREDIT_MONTHLY 등)

### 3.3 00-calculator-overview.md — 계산기 개요표

| # | 계산기명 | 코드 파일 | 함수명 | 적용 법조문 | 통상임금 의존 | 우선순위 |
|---|---------|----------|--------|-----------|:----------:|:--------:|
| 01 | 통상임금 | ordinary_wage.py | calc_ordinary_wage | 근기법 제6조, 2023다302838 | — (기반) | High |
| 02 | 연장·야간·휴일수당 | overtime.py | calc_overtime | 근기법 제56조 | ✅ | High |
| 03 | 최저임금 | minimum_wage.py | calc_minimum_wage | 최저임금법 제6조 | ✅ | High |
| 04 | 주휴수당 | weekly_holiday.py | calc_weekly_holiday | 근기법 제55조 | ✅ | Medium |
| 05 | 연차수당 | annual_leave.py | calc_annual_leave | 근기법 제60조 | ✅ | High |
| 06 | 해고예고수당 | dismissal.py | calc_dismissal | 근기법 제26조 | ✅ | Medium |
| 07 | 퇴직금 | severance.py | calc_severance | 근퇴법 제8조 | ✅ | High |
| 08 | 평균임금 | average_wage.py | calc_average_wage | 근기법 제2조제1항제6호 | ✅ | Medium |
| 09 | 휴업수당 | shutdown_allowance.py | calc_shutdown_allowance | 근기법 제46조 | ✅ | Medium |
| 10 | 포괄임금제 | comprehensive.py | calc_comprehensive | 판례법 | ✅ | Medium |
| 11 | 중도입사 일할계산 | prorated.py | calc_prorated | 근기법 제43조 | ✅ | Low |
| 12 | 유급공휴일 | public_holiday.py | calc_public_holiday | 근기법 제55조제2항 | ✅ | Low |
| 13 | 4대보험·소득세 | insurance.py | calc_insurance | 국민연금법 등 | ✅ | High |
| 14 | 실업급여 | unemployment.py | calc_unemployment | 고용보험법 제68조 | ✅ | Medium |
| 15 | 보상휴가 | compensatory_leave.py | calc_compensatory_leave | 근기법 제57조 | ✅ | Low |
| 16 | 임금체불 지연이자 | wage_arrears.py | calc_wage_arrears | 근기법 제37조 | ❌ (독립) | Medium |
| 17 | 육아휴직급여 | parental_leave.py | calc_parental_leave | 고용보험법 제70조 | ✅ | Medium |
| 18 | 출산전후휴가급여 | maternity_leave.py | calc_maternity_leave | 고용보험법 제75조 | ✅ | Medium |
| 19 | 탄력적 근로시간제 | flexible_work.py | calc_flexible_work | 근기법 제51조 | ✅ | Low |
| 20 | 산재보상금 | industrial_accident.py | calc_industrial_accident | 산재보험법 | ✅ | Medium |
| 21 | 퇴직소득세 | retirement_tax.py | calc_retirement_tax | 소득세법 제48조 | ✅ | Medium |
| 22 | 퇴직연금 | retirement_pension.py | calc_retirement_pension | 근퇴법 제13조 | ✅ | Medium |
| 23 | 상시근로자 수 | business_size.py | calc_business_size | 근기법 시행령 제7조의2 | ❌ | Low |
| 24 | 근로장려금 | eitc.py | calc_eitc | 조특법 제100조의5 | ✅ | Low |

### 3.4 00-legal-case-mapping.md — 판례 반영 현황표

| 판례 번호 | 선고일 | 요지 | 반영 모듈 | 코드 위치 |
|-----------|--------|------|----------|----------|
| 대법원 2023다302838 | 2024.12.19 | 통상임금 고정성 요건 폐기 (재직조건·근무일수 자동 포함) | ordinary_wage.py, models.py (AllowanceCondition) | constants.py:9, models.py:33-47 |
| 대법원 2023다302579 | — | 평균임금 유리 원칙 (3개월 vs 1년 중 높은 쪽) | severance.py | 평균임금 비교 로직 |
| 대법원 2022다291153 | 2025.8.14 | 주휴시간 산정 (주 소정근로일 기준) | weekly_holiday.py | 주휴시간 산정 분기 |
| 대법원 2016다243078 | — | 포괄임금제 초과 연장수당 청구 | legal_hints.py | hints_overtime |
| 대법원 2021다201143 | — | 포괄임금제 허용 범위 (근로시간 산정 곤란한 경우만) | legal_hints.py | hints_comprehensive |
| 대법원 2013다4174 | — | 통상임금 판단 기준 (정기성·일률성·고정성) | legal_hints.py | hints_ordinary_wage |

### 3.5 00-annual-update-checklist.md — 법령 개정 체크리스트

```markdown
# 연도별 법령 개정 체크리스트

## 매년 1월 확인 (필수)
- [ ] 최저임금 시급 갱신 → constants.py: MINIMUM_HOURLY_WAGE[{year}]
- [ ] 4대보험 요율 갱신 → constants.py: INSURANCE_RATES[{year}]
- [ ] 구직급여 상한액 갱신 → constants.py: UNEMPLOYMENT_BENEFIT_UPPER[{year}]
- [ ] 산재보험 최저보상기준금액 → constants.py: MIN_COMPENSATION_DAILY[{year}]
- [ ] 장례비 최고·최저액 → constants.py: FUNERAL_LIMITS[{year}]

## 매년 7월 확인 (국민연금 기준소득)
- [ ] 국민연금 상·하한 갱신 → INSURANCE_RATES[{year}]["pension_income_max/min"]

## 수시 확인 (법 개정 시)
- [ ] 근로기준법 가산율 변경 여부
- [ ] 근로소득세율표 변경 여부 → INCOME_TAX_BRACKETS
- [ ] 근로소득공제율 변경 여부 → EARNED_INCOME_DEDUCTION
- [ ] EITC 기준표 변경 여부 → EITC_PARAMS[{year}]
- [ ] 퇴직소득세 공제표 변경 여부

## 대법원 판례 추가 시
- [ ] AllowanceCondition enum 검토
- [ ] legal_hints.py 힌트 추가
- [ ] 관련 계산기 로직 수정
```

---

## 4. 개별 감사 시트 상세 설계

### 4.1 감사 시트 표준 템플릿

모든 감사 시트는 아래 8개 섹션 구조를 따름:

```
┌───────────────────────────────────────────────┐
│  § 1. 개요                                     │
│    - 계산기명, 코드 파일, 함수명                  │
│    - 적용 법조문 (1차 근거)                       │
│    - 5인 미만 적용 여부                           │
├───────────────────────────────────────────────┤
│  § 2. 입력 항목                                 │
│    - WageInput 중 해당 필드만 추출                 │
│    - 필드명(한/영), 타입, 기본값, 필수 여부         │
├───────────────────────────────────────────────┤
│  § 3. 적용 상수                                 │
│    - 이 계산기에서 사용하는 상수 테이블              │
│    - 값, 단위, 법적 근거, 코드 위치                 │
├───────────────────────────────────────────────┤
│  § 4. 계산 과정 (핵심)                           │
│    - Step 1 → Step 2 → ... 순서로 서술            │
│    - 각 Step: 공식 + 법적 근거 + 코드 참조         │
│    - 조건 분기: if/else 로직 한글 서술              │
├───────────────────────────────────────────────┤
│  § 5. 출력 항목                                 │
│    - 결과 필드명, 설명, 단위                       │
├───────────────────────────────────────────────┤
│  § 6. 예외 처리 / 엣지 케이스                     │
│    - 조건, 처리 방식, 법적 근거                     │
├───────────────────────────────────────────────┤
│  § 7. 계산 예시 (1~2개)                          │
│    - 시나리오명                                   │
│    - 입력값 테이블                                │
│    - Step별 계산 과정 전개                         │
│    - 최종 결과                                    │
├───────────────────────────────────────────────┤
│  § 8. 관련 판례                                  │
│    - 판례 번호, 요지, 코드 반영 위치               │
└───────────────────────────────────────────────┘
```

### 4.2 핵심 감사 시트 설계 (6개)

#### 4.2.1 통상임금 (01-ordinary-wage.audit.md)

**§4 계산 과정**:

```
Step 1: 기본 통상임금 산정
  ├─ 시급 → 그대로 사용
  ├─ 일급 → 일급 ÷ 1일 소정근로시간
  ├─ 월급 → 월급 ÷ 월 기준시간
  └─ 연봉 → 연봉 ÷ 12 ÷ 월 기준시간
  법적 근거: 근로기준법 시행령 제6조

Step 2: 월 기준시간 결정
  ├─ monthly_scheduled_hours 명시값 → 사용
  ├─ shift_monthly_hours 직접 지정 → 사용
  ├─ 교대근무 유형 조회 → SHIFT_MONTHLY_HOURS[work_type]
  └─ 스케줄 기반: (주 소정근로시간 + 주휴시간) × (365 ÷ 7 ÷ 12)
  법적 근거: 고용노동부 행정해석

Step 3: 고정수당 통상임금 포함 판단
  ├─ condition == "없음" or "근무일수" or "재직조건" → 포함 (2023다302838)
  ├─ condition == "성과조건" → 제외
  ├─ condition == "최소보장성과" → guaranteed_amount만 포함
  └─ annual=True → amount ÷ 12 환산
  법적 근거: 대법원 2023다302838 (2024.12.19)

Step 4: 최종 통상임금 산출
  통상시급 = 기본시급 + Σ(포함 수당 월액) ÷ 월 기준시간
  1일 통상임금 = 통상시급 × 1일 소정근로시간
  월 통상임금 = 통상시급 × 월 기준시간
```

**§6 엣지 케이스**:

| 조건 | 처리 | 법적 근거 |
|------|------|----------|
| 교대근무(4조2교대 등) | SHIFT_MONTHLY_HOURS 상수 조회 | 고용부 행정해석 |
| 격월·분기·연 지급 수당 | 월 환산(÷N) 후 포함 | 2023다302838 |
| 성과조건 + 최소보장 | 보장분만 포함 | 2023다302838 |

#### 4.2.2 연장·야간·휴일수당 (02-overtime.audit.md)

**§4 계산 과정**:

```
Step 1: 가산율 결정
  ├─ 5인 이상: 연장 1.5배, 야간 0.5배(추가), 휴일 1.5배, 휴일초과 2.0배
  └─ 5인 미만: 가산 없음 (기본 1.0배만)
  법적 근거: 근기법 제56조, 제11조

Step 2: 월 수당 산출
  연장수당(월) = 통상시급 × 주 연장시간 × 1.5 × (365÷7÷12)
  야간수당(월) = 통상시급 × 주 야간시간 × 0.5 × (365÷7÷12)
  휴일수당(월) = 통상시급 × [8h이내 × 1.5 + 8h초과 × 2.0] × (365÷7÷12)
  법적 근거: 근기법 제56조

Step 3: 주 52시간 체크 (5인 이상만)
  총 주간 근로시간 = 소정(40h) + 연장 + 휴일
  위반 여부 = 총시간 > 52h
  법적 근거: 근기법 제53조
```

#### 4.2.3 최저임금 (03-minimum-wage.audit.md)

**§4 계산 과정**:

```
Step 1: 법정 최저임금 조회
  최저시급 = MINIMUM_HOURLY_WAGE[reference_year]
  수습 특례: is_probation=True → 최저시급 × 0.9
  법적 근거: 최저임금법 제5조, 제5조제2항

Step 2: 산입범위 판단 (2024년 이후 전액 산입)
  ├─ 정기상여금: 법정 최저월액 × 제외율 초과분만 산입
  ├─ 복리후생비: 법정 최저월액 × 제외율 초과분만 산입
  └─ 2024년+: 전액 산입 (0.0, 0.0)
  법적 근거: 최저임금법 제6조제4항

Step 3: 실질시급 산출
  실질시급 = (기본급 + 산입 가능 수당) ÷ 월 기준시간

Step 4: 충족 여부 판단
  is_compliant = 실질시급 ≥ 최저시급
  부족분(월) = (최저시급 - 실질시급) × 월 기준시간
```

#### 4.2.4 퇴직금 (07-severance.audit.md)

**§4 계산 과정**:

```
Step 1: 자격 요건 확인
  ├─ 계속근로 1년 이상 (start_date ~ end_date ≥ 365일)
  ├─ 4주 평균 주 15시간 이상
  └─ 일용직: 월 4~15일 이상 계속 근무 시 인정 (대법원 2023다302579)
  법적 근거: 근로자퇴직급여보장법 제4조

Step 2: 평균임금 산정 (3개월 기준)
  1일 평균임금 = (3개월 임금총액 + 상여금×3/12 + 연차수당×3/12) ÷ 3개월 총일수
  법적 근거: 근기법 제2조제1항제6호

Step 3: 평균임금 산정 (1년 기준 — 유리 원칙)
  1일 평균임금_1y = 1년 임금총액 ÷ 1년 총일수
  법적 근거: 대법원 2023다302579

Step 4: 유리 원칙 적용
  적용 평균임금 = max(3개월 기준, 1년 기준, 통상임금)
  법적 근거: 근기법 시행령 제2조

Step 5: 퇴직금 산출
  퇴직금 = 적용 평균임금 × 30일 × (계속근로일수 ÷ 365)
  법적 근거: 근퇴법 제8조제1항
```

#### 4.2.5 4대보험·소득세 (13-insurance.audit.md)

**§4 계산 과정**:

```
[근로자 경로]
Step 1: 과세 대상 월급 산정
  과세급여 = 세전급여 - 비과세소득(월 200,000원)

Step 2: 4대보험료 산출
  국민연금  = min(max(과세급여, 하한), 상한) × 4.5%
  건강보험  = min(max(과세급여×3.545%, 하한), 상한)
  장기요양  = 건강보험료 × 12.95%
  고용보험  = 과세급여 × 0.9%

Step 3: 근로소득세 산출
  과세표준 = 연간급여 - 근로소득공제 - 인적공제(부양가족×150만)
  산출세액 = 과세표준 × 세율 - 누진공제
  자녀세액공제 적용 (8~20세 자녀)
  월 소득세 = 산출세액 ÷ 12
  지방소득세 = 소득세 × 10%

Step 4: 실수령액 산출
  세후급여 = 세전급여 - 4대보험합계 - 소득세 - 지방소득세

[프리랜서 경로]
  원천징수 = 지급액 × 3.3% (소득세 3% + 지방 0.3%)
  4대보험 없음
```

#### 4.2.6 연차수당 (05-annual-leave.audit.md)

**§4 계산 과정**:

```
Step 1: 연차 발생일수 산정
  ├─ 1년 미만: 매월 개근 시 1일 (최대 11일)
  ├─ 1년 이상: 15일 + (근속연수-1) ÷ 2 (최대 25일)
  └─ 단시간: 주 15h 미만 → 0일 / 15~40h → 비례 산정
  법적 근거: 근기법 제60조제1~4항

Step 2: 차감 처리
  G1 차감: 2년차에 1년 미만 사용분 차감 (제60조제3항)
  사용촉진제도: leave_use_promotion=True → 미사용분 수당 면제 가능 (제61조)

Step 3: 회계기준일 (use_fiscal_year=True)
  ├─ 1.1~12.31 기준으로 비례 산정
  └─ 퇴직 시 입사일 기준 vs 회계 기준 차이 추가 지급

Step 4: 연차수당 산출
  미사용일수 = 발생일수 - 사용일수
  연차수당 = 1일 통상임금 × 미사용일수
```

---

## 5. 문서 작성 규칙

### 5.1 표기 규칙

| 항목 | 규칙 | 예시 |
|------|------|------|
| 금액 | 원 단위, 천단위 콤마 | 2,500,000원 |
| 비율 | % 표기 | 4.5%, 0.5배 |
| 법조문 | "법명 제N조제M항" | 근로기준법 제56조제1항 |
| 판례 | "대법원 YYYY다NNNN" | 대법원 2023다302838 |
| 공식 | 한글 변수명 | 통상시급 × 연장시간 × 1.5 |
| 코드 위치 | "파일명:라인" | constants.py:36 |
| 연도 | "YYYY년 기준" | 2025년 기준 |

### 5.2 공식 표기 스타일

```
기본 공식:
  결과 = A × B ÷ C

조건부 공식:
  결과 = {
    A × 1.5  (5인 이상인 경우)
    A × 1.0  (5인 미만인 경우)
  }

복합 공식:
  월 수당 = 통상시급 × 주 연장시간 × 가산배수 × (365 ÷ 7 ÷ 12)
         = 12,000원 × 10h × 1.5 × 4.345
         = 782,142원
```

---

## 6. 구현 순서

### 6.1 Implementation Order

| 순서 | 파일 | FR | 의존 |
|:----:|------|-----|------|
| 1 | `docs/calculator-audit/` 디렉토리 생성 | — | — |
| 2 | `00-constants-reference.md` | FR-01 | constants.py 읽기 |
| 3 | `00-calculator-overview.md` | FR-02 | facade.py 읽기 |
| 4 | `01-ordinary-wage.audit.md` | FR-03 | ordinary_wage.py, models.py |
| 5 | `02-overtime.audit.md` | FR-04 | overtime.py |
| 6 | `03-minimum-wage.audit.md` | FR-05 | minimum_wage.py |
| 7 | `05-annual-leave.audit.md` | FR-08 | annual_leave.py |
| 8 | `07-severance.audit.md` | FR-06 | severance.py |
| 9 | `13-insurance.audit.md` | FR-07 | insurance.py |
| 10 | `04-weekly-holiday.audit.md` | FR-09 | weekly_holiday.py |
| 11 | `06-dismissal.audit.md` | FR-10 | dismissal.py |
| 12 | `14-unemployment.audit.md` | FR-11 | unemployment.py |
| 13 | `10-comprehensive.audit.md` | FR-12 | comprehensive.py |
| 14 | `17-parental-leave.audit.md` + `18-maternity-leave.audit.md` | FR-13 | parental_leave.py, maternity_leave.py |
| 15 | `16-wage-arrears.audit.md` | FR-14 | wage_arrears.py |
| 16 | `19-flexible-work.audit.md` + `15-compensatory-leave.audit.md` + `11-prorated.audit.md` + `12-public-holiday.audit.md` | FR-15 | 각 계산기 |
| 17 | `20-industrial-accident.audit.md` | FR-16 | industrial_accident.py |
| 18 | `21-retirement-tax.audit.md` + `22-retirement-pension.audit.md` | FR-17 | retirement_tax.py, retirement_pension.py |
| 19 | `08-average-wage.audit.md` + `09-shutdown-allowance.audit.md` | — | average_wage.py, shutdown_allowance.py |
| 20 | `23-business-size.audit.md` | FR-19 | business_size.py |
| 21 | `24-eitc.audit.md` | FR-18 | eitc.py |
| 22 | `00-legal-case-mapping.md` | FR-20 | legal_hints.py + 전체 스캔 |
| 23 | `00-annual-update-checklist.md` | FR-21 | constants.py 분석 |
| 24 | `README.md` | — | 모든 문서 완성 후 |

### 6.2 구현 원칙

1. **코드 직접 참조**: 각 감사 시트 작성 시 해당 `.py` 파일을 먼저 읽고 상수·공식 추출
2. **계산 예시 검증**: `wage_calculator_cli.py`의 테스트 케이스에서 해당 시나리오 참조
3. **법조문 교차 확인**: `legal_hints.py`와 각 계산기의 `legal_basis` 필드 참조
4. **코드 위치 표기**: 상수·로직의 `파일명:라인번호` 반드시 포함

---

## 7. 검증 방법

### 7.1 Gap Analysis 기준

| 항목 | 검증 방법 | 합격 기준 |
|------|----------|----------|
| 상수 일치 | constants.py의 모든 상수가 문서에 존재 | 100% 커버 |
| 공식 일치 | 각 계산기의 핵심 공식이 코드와 동일 | 100% 커버 |
| 법적 근거 | 모든 Step에 법조문 또는 판례 매핑 | 100% 커버 |
| 계산 예시 | 예시 결과가 CLI 테스트와 일치 | 최소 1개/계산기 |
| 엣지 케이스 | 5인 미만, 수습, 일용직 등 예외 처리 문서화 | 주요 케이스 커버 |
| 파일 수 | 29개 문서 (README + 4공통 + 24감사시트) | 29개 |

### 7.2 노무사 리뷰 체크포인트

- [ ] 통상임금 포함 기준이 2023다302838 판결을 정확히 반영하는가?
- [ ] 4대보험 요율이 최신 연도 기준과 일치하는가?
- [ ] 퇴직금 평균임금 유리 원칙(3개월 vs 1년)이 정확한가?
- [ ] 연차 발생 로직(1년 미만/이상, 차감, 비례)이 법 조문과 일치하는가?
- [ ] 최저임금 산입범위 계산이 정확한가?
- [ ] 실업급여 소정급여일수 테이블이 최신 기준인가?

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-08 | Initial draft | PDCA |
