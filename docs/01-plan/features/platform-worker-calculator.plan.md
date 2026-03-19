# Plan: 특수고용직(노무제공자) 사회보험 계산 반영

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | platform-worker-calculator |
| 작성일 | 2026-03-17 |
| 예상 기간 | 2~3일 |
| 난이도 | Medium-High |

### Value Delivered

| 관점 | 내용 |
|------|------|
| **Problem** | 현재 계산기는 일반 근로자 기준으로만 작동하여, 택배기사·배달기사·보험설계사·학습지교사 등 특수고용직의 고용보험(수급요건·보험료율·상한액), 산재보험(50% 분담), 출산휴가급여(요건·상한) 차이를 반영하지 못함 |
| **Solution** | WorkType에 `PLATFORM_WORKER` 추가, 4개 계산기(unemployment, insurance, maternity_leave, industrial_accident)에 노무제공자 분기 로직 삽입, 특수고용직 전용 상수(보험료율 0.8%, 구직급여 상한 66,000원 등) 추가 |
| **Function UX Effect** | "택배기사인데 실업급여 얼마나 받을 수 있나요?"에 대해 노무제공자 전용 수급요건(24개월 중 12개월)·상한액(66,000원)·소득감소 이직 인정 기준으로 정확한 답변 제공 |
| **Core Value** | 2021년 이후 고용·산재보험 적용 확대에 따라 급증하는 특수고용직 상담 수요에 정확한 계산 결과를 제공하여 챗봇 신뢰도 향상 |

---

## 1. 배경

### 1.1 특수고용직(노무제공자) 사회보험 현황

> 소스: `wage_calculator/calculator_flow/platform.md`

- **2021.7~**: 고용보험법 개정으로 특수고용직에 고용보험 확대 적용
  - 1차(2021.7): 보험설계사, 학습지교사, 택배기사 등
  - 2차(2022.1): 퀵서비스, 대리운전
  - 3차(2022.7): SW기술자, 관광안내원, 골프장캐디
- **산재보험**: 2021.7부터 적용 제외 사유 제한으로 사실상 의무화, 직종 확대
- **적용 범위**: 구직급여 + 출산전후휴가급여에 **한정** (육아휴직·고용안정 등은 미적용)

### 1.2 현재 계산기의 한계

| 계산기 | 일반 근로자 | 특수고용직(노무제공자) | 현재 반영 |
|--------|-----------|---------------------|----------|
| **실업급여** | 18개월 중 180일 피보험, 상한 68,100원 | **24개월 중 12개월 보험료 납부**, 상한 **66,000원** | ❌ |
| **고용보험** | 근로자 0.9% | 노무제공자 **0.8%** (사업주 0.8%) | ❌ |
| **출산휴가급여** | 통상임금 기준, 상한 ~216만 | 직전 1년 **월 평균 보수 100%**, 상한 **200만원** | ❌ |
| **산재보험** | 사업주 전액 부담 | 사업주 **50%** + 노무제공자 **50%** | ❌ |
| **4대보험 합계** | 4대보험 가입 | 고용+산재만 (국민연금·건강보험은 **지역가입자**) | ❌ |

### 1.3 현재 유사 처리

`is_freelancer=True`: 3.3% 사업소득 원천징수만 적용 (4대보험 전부 미가입).
→ 프리랜서와 특수고용직은 다름. 특수고용직은 고용+산재 가입 의무.

---

## 2. 변경 항목

### 2.1 models.py — WorkType 확장

```python
class WorkType(Enum):
    REGULAR      = "정규직"
    CONTRACT     = "계약직"
    PART_TIME    = "파트타임"
    DAILY_WORKER = "일용직"
    PLATFORM_WORKER = "특수고용직"   # NEW: 노무제공자/플랫폼 종사자
    ...
```

### 2.2 WageInput — 노무제공자 전용 필드 추가

```python
# 특수고용직(노무제공자) 전용
is_platform_worker: bool = False           # 특수고용직 여부
platform_monthly_income: float | None = None  # 월 보수액 (총수입 - 비과세 - 경비)
platform_insured_months: int = 0           # 고용보험 피보험기간 (개월)
platform_income_decreased: bool = False    # 소득 30%↑ 감소 이직 여부
```

### 2.3 constants.py — 특수고용직 전용 상수

```python
# ── 특수고용직(노무제공자) 사회보험 ──
PLATFORM_EMP_INSURANCE_RATE = 0.008     # 고용보험 노무제공자 부담 0.8%
PLATFORM_EMP_INSURANCE_BIZ  = 0.008     # 고용보험 사업주 부담 0.8%
PLATFORM_UNEMPLOYMENT_UPPER = 66_000    # 구직급여 일 상한
PLATFORM_INSURED_REQ_MONTHS = 12        # 피보험 요건: 24개월 중 12개월
PLATFORM_INSURED_REQ_WINDOW = 24        # 피보험 요건: 기준 기간 24개월
PLATFORM_MIN_MONTHLY_INCOME = 800_000   # 고용보험 가입 최소 월 보수
PLATFORM_MATERNITY_UPPER    = 2_000_000 # 출산휴가급여 상한 200만원
PLATFORM_INDUSTRIAL_WORKER_SHARE = 0.5  # 산재보험 노무제공자 부담 50%
```

### 2.4 계산기별 변경

#### unemployment.py — 노무제공자 구직급여

| 항목 | 일반 근로자 | 노무제공자 |
|------|-----------|-----------|
| 피보험 요건 | 18개월 중 180일 | **24개월 중 12개월 보험료 납부** |
| 비자발적 이직 | 표준 사유 | + **소득 30% 감소 이직 인정** |
| 1일 상한 | 68,100원 | **66,000원** |
| 1일 기초액 | 평균임금 × 60% | 기초액 × 60% (동일) |
| 소정급여일수 | 동일 테이블 | 동일 |

#### insurance.py — 노무제공자 보험료

| 항목 | 일반 근로자 | 노무제공자 |
|------|-----------|-----------|
| 국민연금 | 4.75% | **미가입** (지역가입자 별도) |
| 건강보험 | 3.595% | **미가입** (지역가입자 별도) |
| 장기요양 | 건보 × 13.14% | **미가입** |
| 고용보험 | 0.9% | **0.8%** |
| 산재보험 | 사업주 전액 | 사업주 50% + **노무제공자 50%** |
| 소득세 | 간이세액표 | 3.3% 원천징수 (사업소득) |

#### maternity_leave.py — 노무제공자 출산휴가급여

| 항목 | 일반 근로자 | 노무제공자 |
|------|-----------|-----------|
| 수급 요건 | 고용보험 가입 | 피보험 단위기간 **3개월 이상** |
| 급여 수준 | 통상임금 기준 | **직전 1년 월 평균 보수 100%** |
| 상한 | ~216만 (최저임금×209h) | **200만원** |
| 기간 | 90일/120일 | 동일 |

#### industrial_accident.py — 노무제공자 산재보험

| 항목 | 일반 근로자 | 노무제공자 |
|------|-----------|-----------|
| 보험료 부담 | 사업주 전액 | 사업주 50% + 노무제공자 **50%** |
| 급여 산정 | 평균임금 기준 | 동일 (평균임금 기준) |

### 2.5 analyzer (prompts.py) — 특수고용직 자동 감지

ANALYZE_TOOL에 `is_platform_worker` 필드 추가:

```python
"is_platform_worker": {
    "type": "boolean",
    "description": (
        "특수고용직(노무제공자/플랫폼 종사자) 여부. "
        "택배기사, 배달기사, 대리운전, 퀵서비스, 보험설계사, 학습지교사, "
        "골프장캐디, 관광안내원, 화물차주 등 언급 시 true."
    ),
}
```

### 2.6 conversion.py — 연동

```python
if info.get("is_platform_worker"):
    inp.is_platform_worker = True
    inp.work_type = WorkType.PLATFORM_WORKER
```

---

## 3. 변경 대상 파일

| 파일 | 변경 |
|------|------|
| `wage_calculator/models.py` | WorkType에 PLATFORM_WORKER 추가, WageInput에 4개 필드 |
| `wage_calculator/constants.py` | 특수고용직 전용 상수 8개 |
| `wage_calculator/calculators/unemployment.py` | 노무제공자 수급요건/상한 분기 |
| `wage_calculator/calculators/insurance.py` | 노무제공자 보험료 계산 분기 (고용만, 국민연금·건보 제외) |
| `wage_calculator/calculators/maternity_leave.py` | 노무제공자 출산휴가 요건/상한 분기 |
| `wage_calculator/calculators/industrial_accident.py` | 노무제공자 산재보험료 50% 분담 |
| `app/templates/prompts.py` | ANALYZE_TOOL에 is_platform_worker 추가 |
| `app/core/analyzer.py` | info_keys에 is_platform_worker 추가 |
| `wage_calculator/facade/conversion.py` | 연동 매핑 |

---

## 4. 구현 순서

```
Phase 1: 모델 + 상수 (0.5일)
├── WorkType.PLATFORM_WORKER 추가
├── WageInput 필드 4개 추가
└── constants.py 상수 8개 추가

Phase 2: 계산기 분기 로직 (1일)
├── unemployment.py — 수급요건/상한 분기
├── insurance.py — 보험료 분기 (고용만 + 3.3% 세금)
├── maternity_leave.py — 요건/상한 분기
└── industrial_accident.py — 50% 분담 반영

Phase 3: 파이프라인 연동 (0.5일)
├── prompts.py — ANALYZE_TOOL 필드 추가
├── analyzer.py — info_keys 추가
├── conversion.py — 매핑 로직
└── ANALYZER_SYSTEM — 특수고용직 감지 규칙

Phase 4: 테스트 (0.5일)
├── 택배기사 실업급여 계산 (노무제공자 요건)
├── 대리운전 보험료 계산 (고용보험만)
├── 노무제공자 출산휴가 (200만 상한)
└── 기존 116개 테스트 회귀 확인
```

---

## 5. 리스크 및 완화

| 리스크 | 완화 |
|--------|------|
| 기존 is_freelancer와 혼동 | is_freelancer(3.3%만)와 is_platform_worker(고용+산재 가입)를 명확히 분리. 둘 다 True면 is_platform_worker 우선 |
| 노무제공자 평균임금 산정 방식 차이 | 초기에는 일반 근로자와 동일한 평균임금 로직 사용. 추후 "월 보수액" 기반으로 세분화 |
| 직종별 적용 시기 차이 (2021.7/2022.1/2022.7) | reference_year로 분기하지 않고, 현재 기준(전부 적용)으로 단순화 |

---

## 6. 제외 범위 (YAGNI)

- 직종별 적용 시기 분기 (2021/2022 구분) — 현재 모두 적용 중
- 노무제공자 고용안정·직업능력개발 급여 — 현행법상 미적용
- 이중 보상 금지 계산 — 계산기가 아닌 상담 안내로 처리
- 플랫폼 사업자 의무 안내 — 법적 안내는 LLM 답변에서 처리
