# nontaxable-income-types Plan Document

> **Summary**: nodong.kr/income_tax_except 섹션2~6 전체 비과세 근로소득 종류를 NonTaxableIncome에 반영
>
> **Project**: laborconsult (nodong.kr 노동법 Q&A + 임금계산기)
> **Date**: 2026-03-13
> **Status**: Draft
> **References**: https://www.nodong.kr/income_tax_except, https://www.nodong.kr/income_tax_except#2~6
> **Prerequisite**: income-tax-nontaxable (Match Rate 97%, 완료)

---

## Executive Summary

| Perspective | Detail |
|-------------|--------|
| **Problem** | 현재 NonTaxableIncome은 10개 항목만 지원하며, nodong.kr/income_tax_except의 30+ 비과세 항목 중 한도가 있는 주요 항목(단체보험료, 승선수당, 학자금, 경조금 등)이 누락되어 계산기 커버리지 부족 |
| **Solution** | 섹션2~6 전체 비과세 종류를 분석하여 한도가 있는 6개 항목을 NonTaxableIncome 필드로 추가 + 무한도 항목 3개를 전용 필드로 추가 + 카테고리 분류 체계 도입 |
| **Function/UX** | 단체보험료·승선수당·학자금 등 추가 비과세 항목 입력 시 자동 한도 적용 + 카테고리별 비과세 내역 출력 |
| **Core Value** | nodong.kr 비과세 가이드와 동일한 항목 커버리지 → 챗봇 신뢰도 향상 + 실수령액 정확도 증대 |

---

## 1. Background

### 1.1 현행 구현 (income-tax-nontaxable 완료)

`NonTaxableIncome` dataclass에 10개 필드 + `other_nontaxable` 구현 완료:

| # | 필드 | 항목 | 한도 | 섹션 |
|---|------|------|------|------|
| 1 | `meal_allowance` | 식대 | 월 20만 | §4 |
| 2 | `car_subsidy` | 자가운전보조금 | 월 20만 | §3 |
| 3 | `childcare_allowance` | 보육수당 | 월 20만/자녀 | §7 |
| 4 | `overtime_nontax` | 생산직 연장근로수당 | 연 240만 | §5 |
| 5 | `overseas_pay` | 국외근로소득 | 월 100만/500만 | §6 |
| 6 | `research_subsidy` | 연구보조비 | 월 20만 | §3 |
| 7 | `reporting_subsidy` | 취재수당 | 월 20만 | §3 |
| 8 | `remote_area_subsidy` | 벽지수당 | 월 20만 | §3 |
| 9 | `invention_reward_annual` | 직무발명보상금 | 연 700만 | §7 |
| 10 | `childbirth_support` | 출산지원금 | 무한도 | §7 |

### 1.2 nodong.kr/income_tax_except 전체 항목 vs 미반영 항목

**섹션 2 (근로소득 미포함 소득)** — 한도 있는 미반영:
| 항목 | 한도 | 조건 | 빈도 |
|------|------|------|------|
| 단체보장성보험료 | **연 70만원** | 사망·상해·질병 보장, 만기 환급 없음 | 중 |
| 경조금 | 사회통념상 | 결혼·장례 등 경조사비 | 고 |

**섹션 3 (실비변상적 급여)** — 한도 있는 미반영:
| 항목 | 한도 | 조건 | 빈도 |
|------|------|------|------|
| 승선수당 | **월 20만원** | 선원법상 선원 | 저 |
| 지방이전 이주수당 | **월 20만원** | 공공기관 이전 종사자 | 저 |
| 일직·숙직료 | 실비변상 | 사내 규정 기준, 사회통념상 타당 | 중 |

**섹션 7 (기타 비과세)** — 무한도이나 주요:
| 항목 | 한도 | 조건 | 빈도 |
|------|------|------|------|
| 근로자 학자금 | **무한도** | 업무 관련 교육, 6개월 이상 재직 | 고 |
| 사택 제공 이익 | **무한도** | 회사 소유/임차 주택 무상 제공 | 중 |
| 육아휴직급여 | **무한도** | 고용보험법상 급여 | 고 |

**반영 제외 (매우 특수)**: 선원 식료품, 입갱·발파수당, 군경 특수수당, 병사급여, 외국군주둔자, 제복·작업복, 보육교사 처우개선비, 위원 회의수당, 재해급여 → `other_nontaxable`로 커버

---

## 2. Scope

### 2.1 In Scope

#### Tier 1: 한도 있는 항목 추가 (4개 필드)

| 필드명 | 항목 | 한도 | 섹션 |
|--------|------|------|------|
| `group_insurance` | 단체보장성보험료 | 연 70만원 | §2 |
| `boarding_allowance` | 승선수당 | 월 20만원 | §3 |
| `relocation_subsidy` | 지방이전 이주수당 | 월 20만원 | §3 |
| `overnight_duty_pay` | 일직·숙직료 | 월 20만원 (실비변상 상한 설정) | §3 |

#### Tier 2: 무한도이나 빈도 높은 항목 추가 (3개 필드)

| 필드명 | 항목 | 한도 | 섹션 |
|--------|------|------|------|
| `tuition_support` | 근로자 학자금 | 무한도 | §7 |
| `company_housing` | 사택 제공 이익 | 무한도 | §7 |
| `congratulatory_pay` | 경조금 | 무한도 (사회통념상) | §2 |

#### Tier 3: 상수·법령 보강

- `NON_TAXABLE_LIMITS`에 `group_insurance_annual`, `boarding`, `relocation`, `overnight_duty` 추가
- `NON_TAXABLE_INCOME_LEGAL_BASIS`에 7개 항목 법적 근거 추가
- `calc_nontaxable_total()`에 7개 항목 처리 로직 추가

#### Tier 4: 카테고리 분류 출력

- formulas 출력 시 섹션별 그룹핑: `[§2 근로소득 미포함]`, `[§3 실비변상]`, `[§5 연장근로]`, `[§6 국외근로]`, `[§7 기타]`

### 2.2 Out of Scope

- 매우 특수한 직종 전용 항목 (선원 식료품, 입갱수당, 군경 특수수당 등) → `other_nontaxable` 사용
- 현물 식사 (금액 산정 불가, 식대와 택일) → 기존 meal_allowance로 커버
- 산재·장해급여 (이미 별도 산재 계산기로 처리)
- 육아휴직급여 (이미 별도 parental_leave 계산기로 처리)

---

## 3. Functional Requirements

### FR-01: NonTaxableIncome 필드 확장

`models.py`의 `NonTaxableIncome`에 7개 필드 추가:

```python
# ── §2 근로소득 미포함 ─────────────────────────────────────
group_insurance: float = 0.0          # 단체보장성보험료 (연간 총액)
congratulatory_pay: float = 0.0       # 경조금 (월)

# ── §3 실비변상적 급여 (추가분) ─────────────────────────────
boarding_allowance: float = 0.0       # 승선수당 (월)
relocation_subsidy: float = 0.0       # 지방이전 이주수당 (월)
overnight_duty_pay: float = 0.0       # 일직·숙직료 (월)

# ── §7 기타 비과세 (추가분) ─────────────────────────────────
tuition_support: float = 0.0          # 근로자 학자금 (월 환산)
company_housing: float = 0.0          # 사택 제공 이익 (월 환산)
```

### FR-02: NON_TAXABLE_LIMITS 확장

`constants.py`에 연도별 한도 추가:

```python
# 2025/2026 공통
"group_insurance_annual": 700_000,  # 단체보장성보험 연 70만원
"boarding":    200_000,             # 승선수당 월 20만원
"relocation":  200_000,             # 지방이전 이주수당 월 20만원
"overnight_duty": 200_000,          # 일직·숙직료 월 20만원 (실비변상 상한)
```

### FR-03: calc_nontaxable_total() 확장

`insurance.py`의 `calc_nontaxable_total()`에 7개 항목 처리 추가:
- 한도 있는 4개: 기존 `_apply_cap()` 패턴 적용
- 무한도 3개: 전액 비과세 처리 + formulas 생성

### FR-04: NON_TAXABLE_INCOME_LEGAL_BASIS 확장

```python
"group_insurance": "소득세법 제12조제3호다목 (단체보장성보험료)",
"congratulatory": "소득세법 시행규칙 제10조 (경조금)",
"boarding":       "소득세법 시행령 제12조제10호 (승선수당)",
"relocation":     "소득세법 시행령 제12조제17호 (지방이전 이주수당)",
"overnight_duty": "소득세법 시행령 제12조제1호 (일직·숙직료)",
"tuition":        "소득세법 제12조제3호마목 (근로자 학자금)",
"company_housing":"소득세법 시행령 제38조 (사택 제공 이익)",
```

### FR-05: 카테고리 분류 출력

formulas에 비과세 항목을 섹션별로 그룹핑하여 출력:
```
[실비변상적 급여]
  자가운전보조금 비과세: 200,000원 (한도 200,000원/월)
  벽지수당 비과세: 200,000원 (한도 200,000원/월)
[비과세 식사대]
  식대 비과세: 200,000원 (한도 200,000원/월)
[기타 비과세]
  출산지원금 비과세: 500,000원 (한도 없음)
```

### FR-06: 테스트 케이스 추가

NT-09 ~ NT-14 (6개):
| ID | 설명 | 검증 포인트 |
|----|------|------------|
| NT-09 | 단체보장성보험료 연 70만 한도 | 연 80만 입력 → 비과세 70만, 초과 10만 과세 |
| NT-10 | 승선수당 월 20만 한도 | 25만 입력 → 비과세 20만 |
| NT-11 | 근로자 학자금 무한도 | 100만 입력 → 전액 비과세 |
| NT-12 | 경조금 무한도 | 30만 입력 → 전액 비과세 |
| NT-13 | 사택 제공 이익 무한도 | 50만 입력 → 전액 비과세 |
| NT-14 | 복합 (기존10 + 신규3) | 13개 항목 동시 입력 → 합산 정확성 |

---

## 4. Risk Analysis

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| 일직·숙직료 "실비변상" 한도 모호 | 중 | 중 | 월 20만원 상한 적용, warning에 "실비변상 기준은 사내 규정 확인" 안내 |
| 경조금 "사회통념상" 한도 모호 | 저 | 저 | 무한도 처리 + warning "과다 경조금은 과세 전환 가능" |
| 기존 10개 항목 회귀 | 고 | 저 | 기존 NT-01~NT-08 테스트 + 전체 110개 유지 |
| 필드 수 과다 (22개) | 중 | 저 | from_dict()로 필요한 필드만 입력, 미사용 필드는 0.0 기본값 |

---

## 5. Implementation Priority

1. **constants.py** — `NON_TAXABLE_LIMITS` + `NON_TAXABLE_INCOME_LEGAL_BASIS` 확장
2. **models.py** — `NonTaxableIncome` 7개 필드 추가
3. **insurance.py** — `calc_nontaxable_total()` 7개 항목 처리 + 카테고리 분류
4. **__init__.py** — export 확인 (변경 불필요)
5. **legal_hints.py** — 신규 항목 관련 힌트 추가 (선택)
6. **wage_calculator_cli.py** — NT-09~NT-14 테스트 추가

---

## 6. Success Criteria

- [ ] nodong.kr/income_tax_except §2~§6의 한도 있는 항목 100% 커버
- [ ] 기존 110개 테스트 전부 통과 (회귀 없음)
- [ ] 신규 6개 테스트 (NT-09~NT-14) 통과
- [ ] formulas에 카테고리별 그룹핑 출력
- [ ] Gap Analysis Match Rate >= 90%
