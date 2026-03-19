# Design: 벤치마크 MISMATCH 원인별 계산기 개선

> **Plan 참조**: `docs/01-plan/features/legal-case-calculator-benchmark.plan.md`

---

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | legal-case-calculator-benchmark |
| Plan 참조 | `docs/01-plan/features/legal-case-calculator-benchmark.plan.md` |
| 작성일 | 2026-03-11 (v2 갱신) |
| 예상 기간 | 2~3일 |

### Value Delivered

| 관점 | 내용 |
|------|------|
| Problem | 통합 벤치마크 MATCH 0건/8건(0%) — 원인 분석 결과 벤치마크 인프라 4건 + 계산기 로직 4건 |
| Solution | Category A(벤치마크 인프라) 4건 + Category B(계산기 로직) 4건, 총 6개 개선 항목 설계 |
| Function UX Effect | 벤치마크 MATCH율 0% → 50%+, 비교 가능 건수 8건 → 15건+ 확대 |
| Core Value | 벤치마크 인프라 정확성 + 계산기 실제 결함 수정으로 상담사례 기반 검증 체계 완성 |

---

## 1. 벤치마크 결과 분석 (현황)

### 1.1 전체 통계

```
전체 104건 → 테스트 가능 31건 → 계산 가능 21건 → 비교 가능 8건
  MATCH: 0건 (0%)
  MISMATCH: 8건 (100%)
  NO_COMPARABLE: 13건
  SKIP: 96건
```

### 1.2 MISMATCH 8건 원인별 분류

| # | 사례 | 유형 | 오차 항목 | 오차율 | Category | 근본 원인 |
|---|------|------|-----------|--------|----------|-----------|
| 1 | case_008 | 최저임금 | 시급 4,794 vs 6,250 | 23.3% | **A4** | 월 기준시간 해석 차이 (208.6h vs 160h) |
| 2 | case_016 | 야간/휴일 | 수당 미계산 | N/A | **A1** | CALC_TYPE_MAP 키 누락 → minimum_wage fallback |
| 3 | case_020 | 연장수당 | 통상임금 11,985 vs 14,423 | 16.9% | **B1** | 고정수당(fixed_allowances) 누락 |
| 4 | case_027 | 주휴수당 | 부족분 60,494 vs 주휴 80,240 | 24.6% | **A2** | 비교 대상 잘못 매칭 (부족분 ↔ 주휴수당) |
| 5 | case_028 | 주휴수당 | 부족분 66,752 vs 주휴 80,000 | 16.6% | **A2** | 동일 패턴 — 비교 대상 오매칭 |
| 6 | case_052 | 연장수당 | 시급 9,931 vs 12,500 | 20.6% | **A3** | 입력 추출 오류 (daily_hours=18 vs 실제 12) |
| 7 | case_059 | 평균임금 | 76,702 vs 64,516 | 18.9% | **B2** | 휴업기간 제외 미구현 |
| 8 | case_090 | 평균임금 | 76,702 vs 66,667 | 15.1% | **B3** | 다중 사업장 평균임금 미지원 |

### 1.3 근본 원인 분류

#### Category A — 벤치마크 인프라 문제 (허위 MISMATCH)

| 코드 | 원인 | 해당 사례 | 수정 난이도 |
|------|------|-----------|-------------|
| A1 | CALC_TYPE_MAP 복합형 키 누락 | #2 | Easy |
| A2 | compare_unified() 비교 대상 오매칭 | #4, #5 | Medium |
| A3 | Claude 입력 데이터 추출 오류 | #6 | Easy |
| A4 | 월 기준시간 해석 차이 (계산기가 법적으로 정확) | #1 | Easy |

#### Category B — 계산기 로직 개선 필요 (진짜 MISMATCH)

| 코드 | 원인 | 해당 사례 | 수정 난이도 |
|------|------|-----------|-------------|
| B1 | 통상임금 산입 범위 누락 (고정수당 미반영) | #3 | Medium |
| B2 | 평균임금 휴업기간 제외 미구현 | #7 | Medium |
| B3 | 다중 사업장 평균임금 산정 미지원 | #8 | Hard |
| B4 | 비교 가능 건수 극히 저조 (구조적 문제) | 전체 | Hard |

---

## 2. 개선 설계

### 2.1 [A1] CALC_TYPE_MAP 보강 + fuzzy matching

**문제**: Claude가 `"연장수당/야간수당/휴일근로수당"` 같은 복합형을 반환 → CALC_TYPE_MAP에 없어 `["minimum_wage"]` fallback → 수당 미계산

**수정 대상**: `wage_calculator/facade.py`

**수정 내용 ①** — 복합 키 직접 추가:
```python
CALC_TYPE_MAP.update({
    "연장수당/야간수당/휴일근로수당": ["overtime", "minimum_wage"],
    "연장수당/야간수당/휴일수당":    ["overtime", "minimum_wage"],
    "야간수당":                      ["overtime", "minimum_wage"],
    "휴일수당":                      ["overtime", "minimum_wage"],
    "휴일근로수당":                   ["overtime", "minimum_wage"],
    "야간근로수당":                   ["overtime", "minimum_wage"],
    "연장근로수당":                   ["overtime", "minimum_wage"],
    "통상임금":                      ["minimum_wage"],
})
```

**수정 내용 ②** — keyword fallback 함수:
```python
def _resolve_calc_type(calc_type_str: str) -> list[str]:
    """정확 매칭 실패 시 키워드 기반 fallback"""
    if calc_type_str in CALC_TYPE_MAP:
        return CALC_TYPE_MAP[calc_type_str]

    keyword_map = [
        (["연장", "야간", "휴일"], ["overtime", "minimum_wage"]),
        (["주휴"], ["weekly_holiday", "minimum_wage"]),
        (["퇴직"], ["severance", "minimum_wage"]),
        (["최저"], ["minimum_wage"]),
        (["연차"], ["annual_leave"]),
        (["평균"], ["average_wage"]),
        (["실업", "구직"], ["unemployment"]),
        (["육아"], ["parental_leave"]),
        (["출산"], ["maternity_leave"]),
        (["휴업"], ["shutdown_allowance"]),
        (["산재"], ["industrial_accident", "average_wage"]),
    ]
    for keywords, targets in keyword_map:
        if any(kw in calc_type_str for kw in keywords):
            return targets
    return ["minimum_wage"]
```

**적용 위치**: `benchmark_legal_cases.py`의 `build_wage_input_from_unified()`에서 `CALC_TYPE_MAP.get()` 대신 `_resolve_calc_type()` 호출.

---

### 2.2 [A2] 비교 로직 개선 — label 기반 우선 매칭

**문제**: `compare_unified()`가 summary 전체에서 "30% 이내 가장 가까운 숫자"로 매칭 → 주휴수당(348,662원) 대신 부족분(60,494원)이 정답(80,240원)에 더 가까워 잘못 매칭됨

**수정 대상**: `benchmark_legal_cases.py::compare_unified()`

**수정 내용** — label ↔ summary key 의미 매핑 도입:

```python
LABEL_TO_KEY_MAP = {
    "주휴수당":     ["주휴수당(월)", "주휴수당"],
    "연장수당":     ["연장/야간/휴일수당(월)"],
    "야간수당":     ["연장/야간/휴일수당(월)"],
    "휴일수당":     ["연장/야간/휴일수당(월)"],
    "통상시급":     ["실질시급"],
    "시급":         ["실질시급"],
    "부족분":       ["부족분(월)"],
    "퇴직금":       ["퇴직금"],
    "평균임금":     ["1일 평균임금"],
    "월급":         ["월 기본급"],
}
```

매칭 순서:
1. **Phase 1**: label 키워드 → LABEL_TO_KEY_MAP → summary key 직접 매칭
2. **Phase 2**: "시급" 포함 시 `ordinary_hourly` 직접 비교
3. **Phase 3**: 기존 숫자 근접도 매칭 (30% 이내, fallback)

**예상 효과**:
- case_027: "주휴수당 80,240원" → "주휴수당(월) 348,662원" 매칭 → 오차율 77% → MISMATCH 유지 but **정확한 항목 비교**
- case_028: 동일 패턴 해결

> **주의**: label 매칭 후에도 오차가 크면 여전히 MISMATCH. 핵심은 "맞는 항목끼리 비교"하는 것.

---

### 2.3 [A3] 추출 프롬프트 검증 규칙 강화

**문제**: Claude가 `daily_work_hours=18`로 추출 (실제 12시간). 비정상 값 필터링 없음.

**수정 대상**: `benchmark_legal_cases.py` — `UNIFIED_EXTRACT_PROMPT`

**추가할 검증 규칙**:
```
## 검증 규칙 (추가)
- daily_work_hours는 24시간을 초과할 수 없습니다
- weekly_work_days는 7일을 초과할 수 없습니다
- wage_amount가 시급일 때 100원 미만이거나 100,000원 이상이면 단위를 재확인하세요
- 답변에서 전문가가 사용한 근로시간과 질문의 근로시간이 다르면, 답변의 값을 우선 사용하세요
- 고정수당(매월 정기 지급)이 있으면 반드시 fixed_allowances에 포함하세요
```

**추가**: `build_wage_input_from_unified()`에 입력 검증:
```python
# 비정상 값 클램핑
daily_hours = min(float(test_input.get("daily_work_hours") or 8), 24.0)
weekly_days = min(float(test_input.get("weekly_work_days") or 5), 7.0)
```

---

### 2.4 [A4] 기준시간 차이 별도 분류

**문제**: case_008 — 전문가가 160h(주40h×4주, 주휴 미포함)로 간이 계산, 계산기는 208.6h(주휴 포함)로 법적으로 정확하게 계산. 이는 "계산기 오류"가 아니라 "해석 기준 차이".

**수정**: MISMATCH 사유에 `mismatch_type` 추가:

```python
# 비교 결과 verdict 확장
VERDICT_EXTENDED = {
    "MATCH":                    "일치 (5% 이내)",
    "MISMATCH":                 "불일치 (5% 초과)",
    "MISMATCH_BASEHOURS":       "기준시간 해석 차이 (계산기가 법적으로 정확)",
    "MISMATCH_EXTRACTION":      "입력 추출 오류",
    "MISMATCH_MAPPING":         "비교 대상 매칭 오류",
    "PARTIAL":                  "일부 일치",
    "NO_COMPARABLE":            "비교 가능 수치 없음",
}
```

자동 분류 로직:
```python
def _classify_mismatch(item: str, diff_pct: float, calc_val: float, answer_val: float) -> str:
    """MISMATCH 원인 유형 자동 분류"""
    if "시급" in item and 15 < diff_pct < 35:
        ratio = max(calc_val, answer_val) / min(calc_val, answer_val)
        if 1.2 < ratio < 1.35:  # 208.6/160 ≈ 1.30
            return "MISMATCH_BASEHOURS"
    return "MISMATCH"
```

---

### 2.5 [B1] 통상임금 산입 범위 — 고정수당 반영 강화

**문제**: case_020 — 전문가 답변에서 고정수당을 포함하여 시급 14,423원 산출, 벤치마크는 `fixed_allowances` 미추출 → 기본급만으로 11,985원

**이미 존재하는 코드**:
- `build_wage_input_from_unified()`에 `fixed_allowances` 처리 로직 있음 (line 414~419)
- `ordinary_wage.py`에 `fixed_allowances` 통상임금 산입 로직 있음

**원인**: Claude 추출 프롬프트에서 고정수당 구분이 불충분 → 추출 자체가 안 됨

**수정 대상**: `benchmark_legal_cases.py` — `UNIFIED_EXTRACT_PROMPT`

```
## 추출 규칙 (보강)
4-1. 기본급 외에 매월 고정 지급되는 수당(직무수당, 직책수당, 식대, 교통비,
     위험수당 등)이 있으면 반드시 fixed_allowances에 항목별로 추출하세요
4-2. 답변에서 "통상임금 = (기본급 + 수당) ÷ 시간" 형태의 계산이 있으면,
     분자에 포함된 수당 항목을 fixed_allowances로 분리하세요
```

---

### 2.6 [B2] 평균임금 휴업기간 제외 (case_059)

**법률 근거**: 근로기준법 시행령 제2조 제1항 제6호 ~ 제8호
> 사용자의 귀책사유로 휴업한 기간, 산전후 휴가, 업무상 부상/질병으로 요양한 기간 등과 해당 기간 지급 임금은 평균임금 산정에서 제외

**수정 대상 ①**: `wage_calculator/models.py`

```python
@dataclass
class WageInput:
    # ... 기존 필드 ...

    # ── 평균임금 산정 제외 기간 (근기법 시행령 제2조) ────────────────────────
    excluded_periods: Optional[list] = None
    # 예: [{"start": "2022-02-01", "end": "2022-03-31",
    #        "reason": "사용자귀책휴업", "paid": 0}]
```

**수정 대상 ②**: `wage_calculator/calculators/average_wage.py`

```python
def _calc_period_days(inp: WageInput) -> tuple[int, float]:
    """
    산정기간 일수 + 제외 임금 계산

    Returns: (유효_일수, 제외_임금)
    """
    base_days = _get_base_period_days(inp)  # 기존 로직 (이름만 변경)

    if not inp.excluded_periods:
        return base_days, 0.0

    excluded_days = 0
    excluded_wages = 0.0
    for period in inp.excluded_periods:
        start = parse_date(period["start"])
        end = parse_date(period["end"])
        if start and end:
            excluded_days += (end - start).days + 1
            excluded_wages += float(period.get("paid", 0))

    effective_days = max(base_days - excluded_days, 1)
    return effective_days, excluded_wages
```

`calc_average_wage()` 수정:
```python
period_days, excluded_wages = _calc_period_days(inp)
wage_total -= excluded_wages  # 제외 기간 임금 차감
# ... 1일 평균임금 = (wage_total + bonus + leave) / period_days
```

**하위 호환**: `excluded_periods=None`이면 기존 동작 그대로 (제외 없음).

**예상 효과**:
- case_059: 200만원 ÷ 31일 = 64,516원 (전문가 답변과 일치)

---

### 2.7 [B3] 다중 사업장 평균임금 산정 (case_090)

**법률 근거**: 고용보험법 제45조 제1항 단서
> 최종 이직일 이전 3개월 내 2회 이상 피보험자격 취득 시, 모든 사업장 임금 합산

**수정 대상 ①**: `wage_calculator/models.py`

```python
@dataclass
class WageInput:
    # ... 기존 필드 ...

    # ── 다중 사업장 임금 (고용보험법 제45조) ────────────────────────
    multi_employer_wages: Optional[list] = None
    # 예: [{"employer": "A사", "monthly_wage": 4200000, "months": 2},
    #      {"employer": "B사", "monthly_wage": 2000000, "months": 1}]
```

**수정 대상 ②**: `wage_calculator/calculators/unemployment.py`

`multi_employer_wages`가 존재하면:
1. 모든 사업장 임금 합산 = Σ(monthly_wage × months)
2. 3개월 총일수(92일)로 나누어 기초일액 산정
3. 기초일액 × 60% = 구직급여 일액
4. 상/하한선 적용 (하한 60,120원, 상한 66,000원)

**하위 호환**: `multi_employer_wages=None`이면 기존 단일 사업장 로직 유지.

---

### 2.8 [B4] 비교 가능 건수 확대 — 구조적 개선

**현황**: 104건 중 비교 가능 8건(7.7%). SKIP 96건의 원인:

| 단계 | 현재 건수 | 병목 원인 |
|------|----------|-----------|
| 전체 사례 | 104건 | - |
| 답변 있음 | ~97건 | 답변 없는 7건 제외 |
| testable(Claude 판정) | 31건 | Claude가 66건을 "테스트 불가" 판정 |
| WageInput 변환 성공 | 21건 | 10건 변환 실패 |
| 비교 가능 | 8건 | 13건 NO_COMPARABLE |

**개선 방안**:

1. **WageInput 변환률 향상** (21 → 25건+):
   - `wage_amount` fallback 강화: 답변에서 시급/월급 추출 → WageInput에 자동 설정
   - `service_period` → `start_date` 변환 정확도 향상 (개월 단위 포함)

2. **비교 가능률 향상** (8 → 15건+):
   - label 기반 의미 매칭 도입 (2.2절)
   - formulas 문자열에서 중간 계산값 추출 후 비교 대상 확대
   - `skip_details` 필드 추가로 SKIP 원인 상세 기록

3. **formulas 기반 비교** (신규):
   ```python
   # calc_result["formulas"]에서 숫자 추출하여 비교 대상 확대
   # 예: "연장수당: 11,984.7원 × 10.0h × 1.5 = 179,770원/주"
   # → {"연장수당(주)": 179770} 추출
   ```

---

## 3. 구현 순서

### Phase 1: 벤치마크 인프라 수정 (1일) — 최대 효과

| 순서 | 작업 | 파일 | 해결 사례 |
|------|------|------|-----------|
| 1-1 | CALC_TYPE_MAP 복합키 추가 + `_resolve_calc_type()` | `facade.py` | #2 (A1) |
| 1-2 | `compare_unified()` label 기반 매칭 | `benchmark_legal_cases.py` | #4, #5 (A2) |
| 1-3 | 추출 프롬프트 검증 규칙 + 입력 클램핑 | `benchmark_legal_cases.py` | #6 (A3) |
| 1-4 | MISMATCH 유형 분류 (`mismatch_type`) | `benchmark_legal_cases.py` | #1 (A4) |
| 1-5 | 추출 프롬프트에 fixed_allowances 강조 | `benchmark_legal_cases.py` | #3 (B1) |
| 1-6 | 벤치마크 재실행 (`--unified --skip-extraction`) | - | 전체 |

### Phase 2: 계산기 로직 개선 (1~2일)

| 순서 | 작업 | 파일 | 해결 사례 |
|------|------|------|-----------|
| 2-1 | `excluded_periods` 필드 추가 | `models.py` | #7 (B2) |
| 2-2 | `calc_average_wage()` 제외 기간 반영 | `calculators/average_wage.py` | #7 (B2) |
| 2-3 | `multi_employer_wages` 필드 추가 | `models.py` | #8 (B3) |
| 2-4 | `calc_unemployment()` 다중 사업장 로직 | `calculators/unemployment.py` | #8 (B3) |
| 2-5 | CLI 테스트 케이스 #33~#36 추가 | `wage_calculator_cli.py` | 회귀 방지 |

### Phase 3: 검증 (0.5일)

| 순서 | 작업 |
|------|------|
| 3-1 | 기존 CLI 테스트 #1~#32 전체 통과 확인 |
| 3-2 | 벤치마크 재실행 (`--unified`) → MATCH율 변화 측정 |
| 3-3 | MISMATCH 유형별 분류 결과 확인 |

---

## 4. 수정 대상 파일 목록

| 파일 | 수정 유형 | 영향 범위 |
|------|----------|-----------|
| `wage_calculator/facade.py` | CALC_TYPE_MAP 확장 + `_resolve_calc_type()` | chatbot 연동에도 적용 (개선) |
| `wage_calculator/models.py` | `excluded_periods`, `multi_employer_wages` 추가 | Optional 필드, 하위 호환 |
| `wage_calculator/calculators/average_wage.py` | 제외 기간 반영 | 퇴직금/산재 등 평균임금 의존 계산기에 영향 |
| `wage_calculator/calculators/unemployment.py` | 다중 사업장 로직 | 실업급여 전용 |
| `benchmark_legal_cases.py` | 비교 로직 + 프롬프트 + 분류 | 벤치마크 전용 |
| `wage_calculator_cli.py` | 테스트 케이스 #33~#36 | 검증용 |

---

## 5. 성공 기준

| 지표 | 현재 | 목표 |
|------|------|------|
| MATCH율 (비교 가능 건 중) | 0/8 = 0% | ≥4/8 = 50%+ |
| 비교 가능 건수 | 8/104 | ≥15/104 |
| MISMATCH 원인 분류 | 없음 | 100% 분류됨 |
| 기존 CLI 테스트 | 32/32 | 36/36 (신규 4건 포함) |
| CALC_TYPE_MAP 매핑 실패 | 다수 | 0건 |

---

## 6. 리스크 및 대응

| 리스크 | 대응 |
|--------|------|
| 벤치마크 재추출 필요 (Claude API 재호출) | Phase 1은 `--skip-extraction` 가능. B1(프롬프트 변경)만 재추출 필요 |
| average_wage 수정이 퇴직금/산재에 영향 | `excluded_periods=None`이면 기존 동작 유지 |
| CALC_TYPE_MAP 확장이 chatbot에 영향 | 추가만 하므로 기존 매핑 변경 없음 |
| label 기반 매칭 후에도 사례 답변이 간이 계산 사용 | MISMATCH_BASEHOURS로 별도 분류하여 구분 |

---

## 7. 구현하지 않을 것

- 연장/야간/휴일 가산율 로직 변경 (이미 정확)
- 주휴수당 공식 변경 (대법원 2022다291153 기준 정확)
- 통상임금 산정 로직 변경 (2023다302838 반영 완료)
- Claude 모델 업그레이드 (Haiku → Sonnet) — 비용 증가 대비 효과 불확실, 후속 이슈화
- `output_qna/` 10,000건 대상 벤치마크 확장 — 별도 PDCA 사이클
