# Design: 계산기 모듈 배치 테스트 (500건 추출 및 결과 보고)

> Plan: `docs/01-plan/features/calculator-batch-test.plan.md`

## 1. 설계 항목 목록

| # | 항목 | 유형 | 우선순위 |
|---|------|------|----------|
| D-1 | `calculator_batch_test.py` 메인 스크립트 | 신규 파일 | P0 |
| D-2 | 층화 샘플링 로직 (500건) | 함수 설계 | P0 |
| D-3 | `build_wage_input_v3()` — 퇴직금/실업급여/육아 추출 확장 | 함수 설계 | P0 |
| D-4 | 신규 비교 로직 (퇴직금/실업급여/육아/기타) | 함수 설계 | P0 |
| D-5 | 보고서 생성 (JSON + MD + 콘솔) | 출력 설계 | P1 |

## 2. 상세 설계

### D-1: `calculator_batch_test.py` 메인 스크립트

**파일**: `calculator_batch_test.py` (루트, 신규)

**의존성**: `compare_calculator.py`에서 기존 추출 함수 import

```python
# 기존 함수 재사용 (compare_calculator.py에서 import)
from compare_calculator import (
    extract_base_wage,
    extract_schedule,
    extract_allowances,
    extract_post_year,
    extract_answer_info,
    extract_time_ranges,
    CompareResult,
    _q_section,
    _a_section,
    _parse_h,
    _safe_float,
    _parse_summary_num,
    _closest,
    _ratio_verdict,
    WAGE_TYPE_MAP,
)
from wage_calculator import WageCalculator, WageInput, WageType, WorkType, BusinessSize, WorkSchedule
```

**메인 구조**:

```python
RANDOM_SEED = 42
TOTAL_TARGET = 500

def main():
    records_by_type = load_and_filter()     # D-2
    samples = stratified_sample(records_by_type, TOTAL_TARGET)  # D-2
    results = run_batch(samples)            # D-1 core
    save_json(results)                      # D-5
    save_report_md(results)                 # D-5
    print_console_report(results)           # D-5
```

**`run_batch(samples)` 핵심 루프**:

```python
def run_batch(samples: list[dict]) -> list[CompareResult]:
    calc = WageCalculator()
    results = []
    for record in samples:
        text = record["_text"]
        info = record.get("provided_info", {}) or {}
        calc_type = record.get("calculation_type", "")

        # 1. WageInput 생성 (v3 — 퇴직금/실업급여/육아 대응)
        inp = build_wage_input_v3(text, info, calc_type)
        if inp is None:
            results.append(CompareResult(
                post_id=record["file_id"], calc_type=calc_type,
                verdict="⏭️", reason="WageInput 생성 불가",
                calc_value="-", answer_value="-", wage_input_ok=False))
            continue

        # 2. 계산기 타겟 결정
        targets = get_targets_v3(calc_type)

        # 3. 계산 실행
        try:
            result = calc.calculate(inp, targets=targets)
        except Exception as e:
            results.append(CompareResult(
                post_id=record["file_id"], calc_type=calc_type,
                verdict="⏭️", reason=f"계산기 오류: {type(e).__name__}: {e}",
                calc_value="-", answer_value="-", wage_input_ok=True))
            continue

        # 4. 비교 (v3 — 신규 유형 포함)
        cr = compare_v3(record, text, result, calc_type)
        results.append(cr)

    return results
```

---

### D-2: 층화 샘플링 로직

**설계 원칙**:
- 계산 유형별 **비례 배분** + **최소 보장** (풀 ≥ 5 → 최소 5건)
- 풀 < 할당 시 전량 포함
- `analysis_qna.jsonl`에서 `requires_calculation=True` + `output_qna/{filename}` 존재 필터

**층화 할당 테이블** (`STRATA_TARGET_500`):

```python
STRATA_TARGET_500 = {
    "연차수당":     100,
    "퇴직금":       100,
    "연장수당":      80,
    "주휴수당":      60,
    "최저임금":      50,
    "해고예고수당":   30,
    "실업급여":      25,
    "육아휴직급여":   20,   # analysis_qna에서 "육아휴직급여"로 분류됨
    "통상임금":      15,
    "임금계산":       8,
    "일할계산":       5,
    "휴업수당":       5,
    "휴일근로수당":    2,
}
# 합계: 500
```

**`load_and_filter()` 설계**:

```python
def load_and_filter() -> dict[str, list[dict]]:
    """
    analysis_qna.jsonl 로딩 + 필터링
    - requires_calculation=True
    - calculation_type in STRATA_TARGET_500.keys()
    - output_qna/{filename} 파일 존재
    - 마크다운 텍스트 프리로드 (_text 키)
    """
    by_type: dict[str, list[dict]] = defaultdict(list)

    with open("analysis_qna.jsonl") as f:
        for line in f:
            r = json.loads(line)
            if not r.get("requires_calculation"):
                continue
            ct = r.get("calculation_type", "")
            # 유사 유형 매핑 (analysis_qna 분류값 정규화)
            ct = normalize_calc_type(ct)
            if ct not in STRATA_TARGET_500:
                continue
            fpath = f"output_qna/{r['filename']}"
            if not os.path.exists(fpath):
                continue
            with open(fpath, encoding="utf-8") as f2:
                r["_text"] = f2.read()
                r["_filepath"] = fpath
            by_type[ct].append(r)

    return by_type
```

**`normalize_calc_type()` — 유사 유형 정규화**:

```python
_CALC_TYPE_NORMALIZE = {
    "통상시급": "통상임금",
    "연장수당/야간수당": "연장수당",
    "임금": "임금계산",
    "육아휴직": "육아휴직급여",
    "휴일근로수당": "연장수당",     # 연장수당 비교 로직으로 처리
    "연장수당/야간수당": "연장수당",
}

def normalize_calc_type(ct: str) -> str:
    return _CALC_TYPE_NORMALIZE.get(ct, ct)
```

**`stratified_sample()` 설계**:

```python
def stratified_sample(by_type: dict, total: int) -> list[dict]:
    sampled = []
    for ct, target_n in STRATA_TARGET_500.items():
        pool = by_type.get(ct, [])
        n = min(target_n, len(pool))
        sampled.extend(random.sample(pool, n))
    random.shuffle(sampled)
    return sampled
```

---

### D-3: `build_wage_input_v3()` — WageInput 추출 확장

**기존 함수 기반**: `compare_calculator.py::build_wage_input_from_markdown()`을 확장

**신규 추출 항목**:

| 계산 유형 | 추출 필드 | 소스 | 추출 패턴 |
|-----------|-----------|------|-----------|
| 퇴직금 | `start_date`, `end_date` | provided_info["근무기간"] + 마크다운 | "YYYY-MM-DD ~ YYYY-MM-DD", "N년 N개월" |
| 퇴직금 | `last_3m_wages` | 마크다운 질문 | "최근 3개월 급여 XXX원" |
| 실업급여 | `age` | provided_info + 마크다운 | "만 XX세", "XX살" |
| 실업급여 | `insurance_months` | provided_info["근무기간"] | 근무기간 → 개월 변환 |
| 실업급여 | `is_involuntary_quit` | provided_info["퇴직사유"] | "해고/권고/폐업" → True |
| 육아휴직 | `parental_leave_months` | 마크다운 | "육아휴직 N개월" |
| 육아휴직 | `is_second_parent` | 마크다운 | "아빠/두번째" 키워드 |

**함수 시그니처**:

```python
def build_wage_input_v3(
    text: str,
    provided_info: dict,
    calc_type: str,
) -> WageInput | None:
    """
    compare_calculator.py의 build_wage_input_from_markdown() 확장 버전.
    퇴직금/실업급여/육아휴직 전용 필드 추출 추가.

    기존 로직 (임금/스케줄/수당) → 그대로 사용
    신규 로직 (퇴직금/실업급여/육아) → 유형별 추가 추출
    """
```

**퇴직금 추출 로직**:

```python
# provided_info["근무기간"] 파싱 강화
# 패턴 1: "입사: 2020-01-01, 퇴사: 2024-12-31"
# 패턴 2: "3년 6개월"
# 패턴 3: "2020년 1월 ~ 2024년 12월"

def _extract_service_period(info: dict, text: str) -> tuple[str|None, str|None]:
    """(start_date, end_date) 추출"""
    period = info.get("근무기간") or ""

    # 날짜 범위 추출
    m = re.search(r"(\d{4})[-.년]\s*(\d{1,2})[-.월]\s*(\d{1,2})?.*?[~\-].*?(\d{4})[-.년]\s*(\d{1,2})[-.월]\s*(\d{1,2})?", period)
    if m:
        start = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3) or 1):02d}"
        end = f"{m.group(4)}-{int(m.group(5)):02d}-{int(m.group(6) or 28):02d}"
        return start, end

    # "N년 N개월" → _guess_start_date 사용
    start = _guess_start_date(period)
    if start:
        return start, None  # end=None → 오늘

    return None, None
```

**실업급여 추출 로직**:

```python
def _extract_unemployment_fields(info: dict, text: str) -> dict:
    """실업급여 전용 필드 추출"""
    fields = {}
    q = _q_section(text)

    # 나이
    m = re.search(r"만\s*(\d{2})\s*세", q)
    if m:
        fields["age"] = int(m.group(1))
    else:
        m2 = re.search(r"(\d{2})\s*살", q)
        if m2:
            fields["age"] = int(m2.group(1))

    # 피보험기간 (근무기간에서 개월 환산)
    period = info.get("근무기간") or ""
    months = _period_to_months(period)
    if months > 0:
        fields["insurance_months"] = months

    # 이직사유
    quit_reason = info.get("퇴직사유") or ""
    involuntary_keywords = ["해고", "권고사직", "계약만료", "폐업", "도산"]
    fields["is_involuntary_quit"] = any(k in quit_reason for k in involuntary_keywords)
    if not fields["is_involuntary_quit"]:
        # 텍스트에서도 확인
        fields["is_involuntary_quit"] = bool(re.search(
            r"해고|권고\s*사직|계약\s*만료|폐업|도산|경영\s*악화", q))

    return fields
```

**육아휴직 추출 로직**:

```python
def _extract_parental_fields(text: str) -> dict:
    """육아휴직 전용 필드 추출"""
    fields = {}
    q = _q_section(text)

    # 육아휴직 개월 수
    m = re.search(r"육아\s*휴직\s*(\d+)\s*개월", q)
    if m:
        fields["parental_leave_months"] = int(m.group(1))
    else:
        fields["parental_leave_months"] = 12  # 기본 12개월

    # 두번째 부모 (아빠 보너스)
    fields["is_second_parent"] = bool(re.search(r"아빠|두\s*번째|배우자", q))

    return fields
```

---

### D-4: 신규 비교 로직

**`compare_v3()` 함수 — 통합 비교 디스패처**:

```python
def compare_v3(record: dict, text: str, result: WageResult, calc_type: str) -> CompareResult:
    """
    유형별 비교 디스패처.
    기존 8개 유형: compare_calculator.py의 compare_one() 로직 재사용
    신규 3개 유형: 퇴직금/실업급여/육아휴직 추가
    """
    post_id = record["file_id"]
    extracted = extract_answer_info(text, calc_type)

    # 유형별 디스패치
    comparators = {
        "퇴직금":     _compare_severance,
        "실업급여":   _compare_unemployment,
        "육아휴직급여": _compare_parental_leave,
        "연장수당":   _compare_overtime,       # 기존 로직
        "최저임금":   _compare_minimum_wage,   # 기존 로직
        "통상임금":   _compare_minimum_wage,   # 최저임금과 동일 비교
        "주휴수당":   _compare_weekly_holiday,  # 기존 로직
        "연차수당":   _compare_annual_leave,    # 기존 로직
        "해고예고수당": _compare_dismissal,      # 기존 로직
        "임금계산":   _compare_overtime,        # 연장수당과 동일 비교
        "일할계산":   _compare_prorated,        # 기존 로직
        "휴업수당":   _compare_shutdown,        # 신규
    }

    fn = comparators.get(calc_type, _compare_generic)
    return fn(post_id, calc_type, result, extracted)
```

**퇴직금 비교 (`_compare_severance`)**:

```python
def _compare_severance(post_id, calc_type, result, extracted) -> CompareResult:
    sev_pay_str = result.summary.get("퇴직금")
    calc_num = _parse_summary_num(sev_pay_str) if sev_pay_str else None
    calc_val = f"퇴직금 {sev_pay_str}" if sev_pay_str else "-"

    amounts = extracted["amounts"]
    key_amounts = extracted.get("key_amounts", [])

    if not amounts or not calc_num:
        return CompareResult(post_id=post_id, calc_type=calc_type,
            verdict="⏭️", reason="비교 가능한 수치 없음",
            calc_value=calc_val, answer_value="-", wage_input_ok=True)

    best = _closest(key_amounts or amounts, calc_num)
    # 퇴직금은 수백만~수천만 단위 → 시급/일급 수준 소액 필터
    if calc_num >= 500_000 and best < 100_000:
        return CompareResult(post_id=post_id, calc_type=calc_type,
            verdict="⏭️", reason="단위 불일치 (퇴직금 vs 소액)",
            calc_value=calc_val, answer_value=f"{best:,.0f}원", wage_input_ok=True)

    ratio = best / calc_num if calc_num else 0
    v, r = _ratio_verdict(ratio, best, calc_num)
    return CompareResult(post_id=post_id, calc_type=calc_type,
        verdict=v, reason=r,
        calc_value=calc_val, answer_value=f"{best:,.0f}원", wage_input_ok=True)
```

**실업급여 비교 (`_compare_unemployment`)**:

```python
def _compare_unemployment(post_id, calc_type, result, extracted) -> CompareResult:
    daily_str = result.summary.get("구직급여 일액")
    total_str = result.summary.get("총 구직급여")
    days_str = result.summary.get("소정급여일수")
    ineligible = result.summary.get("실업급여 수급")

    if ineligible:
        calc_val = ineligible
        # 답변에서도 "불가" 판정인지 확인
        answer = extracted.get("answer_preview", "")
        if re.search(r"수급.*불가|실업급여.*불가|자격.*없", answer):
            return CompareResult(post_id=post_id, calc_type=calc_type,
                verdict="✅", reason="수급 불가 판정 일치",
                calc_value=calc_val, answer_value="수급 불가", wage_input_ok=True)
        return CompareResult(post_id=post_id, calc_type=calc_type,
            verdict="⏭️", reason="수급 불가 — 답변 비교 불가",
            calc_value=calc_val, answer_value="-", wage_input_ok=True)

    calc_daily = _parse_summary_num(daily_str) if daily_str else 0
    calc_total = _parse_summary_num(total_str) if total_str else 0
    calc_val = f"일액 {calc_daily:,.0f}원, 총 {calc_total:,.0f}원"

    amounts = extracted["amounts"]
    key_amounts = extracted.get("key_amounts", [])

    if not amounts:
        return CompareResult(post_id=post_id, calc_type=calc_type,
            verdict="⏭️", reason="답변에 금액 없음",
            calc_value=calc_val, answer_value="-", wage_input_ok=True)

    # 일액 또는 총액 비교 (더 가까운 쪽)
    pool = key_amounts or amounts
    best_daily = _closest(pool, calc_daily) if calc_daily else 0
    best_total = _closest(pool, calc_total) if calc_total else 0

    # 일액이 더 정확한 비교 대상인 경우 우선
    if calc_daily and best_daily and 30_000 <= best_daily <= 80_000:
        ratio = best_daily / calc_daily
        v, r = _ratio_verdict(ratio, best_daily, calc_daily)
        return CompareResult(post_id=post_id, calc_type=calc_type,
            verdict=v, reason=f"구직급여 일액 비교: {r}",
            calc_value=calc_val, answer_value=f"{best_daily:,.0f}원", wage_input_ok=True)

    if calc_total and best_total:
        ratio = best_total / calc_total
        v, r = _ratio_verdict(ratio, best_total, calc_total)
        return CompareResult(post_id=post_id, calc_type=calc_type,
            verdict=v, reason=f"총 구직급여 비교: {r}",
            calc_value=calc_val, answer_value=f"{best_total:,.0f}원", wage_input_ok=True)

    return CompareResult(post_id=post_id, calc_type=calc_type,
        verdict="⏭️", reason="비교 가능한 수치 부재",
        calc_value=calc_val, answer_value="-", wage_input_ok=True)
```

**육아휴직 비교 (`_compare_parental_leave`)**:

```python
def _compare_parental_leave(post_id, calc_type, result, extracted) -> CompareResult:
    monthly_str = result.summary.get("육아휴직 월 수령액")
    total_str = result.summary.get("육아휴직 총 수령액")
    calc_monthly = _parse_summary_num(monthly_str) if monthly_str else 0
    calc_val = f"월 {calc_monthly:,.0f}원"

    amounts = extracted["amounts"]
    key_amounts = extracted.get("key_amounts", [])

    if not amounts:
        return CompareResult(post_id=post_id, calc_type=calc_type,
            verdict="⏭️", reason="답변에 금액 없음",
            calc_value=calc_val, answer_value="-", wage_input_ok=True)

    best = _closest(key_amounts or amounts, calc_monthly)
    if calc_monthly and best:
        ratio = best / calc_monthly
        v, r = _ratio_verdict(ratio, best, calc_monthly)
        return CompareResult(post_id=post_id, calc_type=calc_type,
            verdict=v, reason=f"육아휴직 월액 비교: {r}",
            calc_value=calc_val, answer_value=f"{best:,.0f}원", wage_input_ok=True)

    return CompareResult(post_id=post_id, calc_type=calc_type,
        verdict="⏭️", reason="비교 불가",
        calc_value=calc_val, answer_value="-", wage_input_ok=True)
```

**`get_targets_v3()` — 계산기 타겟 매핑 확장**:

```python
def get_targets_v3(calc_type: str) -> list[str]:
    """CALC_TYPE_MAP 활용 + 추가 매핑"""
    from wage_calculator.facade import CALC_TYPE_MAP
    return CALC_TYPE_MAP.get(calc_type, ["minimum_wage"])
```

---

### D-5: 보고서 생성

**3종 출력물 설계**:

#### 5-1: JSON 결과 (`batch_test_results.json`)

```json
{
  "meta": {
    "version": "v3",
    "total_samples": 500,
    "random_seed": 42,
    "run_date": "2026-03-08",
    "calc_types_covered": 13
  },
  "summary": {
    "total": 500,
    "match": 50,        // ✅
    "close": 30,        // ⚠️
    "mismatch": 20,     // ❌
    "skip": 400,        // ⏭️
    "comparable_accuracy": "80.0%"  // (✅+⚠️)/비교가능
  },
  "by_type": {
    "연장수당": {"total": 80, "match": 10, "close": 5, "mismatch": 3, "skip": 62},
    ...
  },
  "results": [
    {
      "post_id": "2332600",
      "calc_type": "최저임금",
      "verdict": "⏭️",
      "reason": "답변에 비교 가능한 수치 없음",
      "calc_value": "충족 (시급 11,962원)",
      "answer_value": "-",
      "wage_input_ok": true
    },
    ...
  ],
  "error_analysis": {
    "input_extraction_fail": 80,
    "answer_no_numbers": 250,
    "calculator_error": 10,
    "unit_mismatch": 30,
    "comparison_logic_na": 30
  }
}
```

#### 5-2: 마크다운 보고서 (`batch_test_report.md`)

구조:
```markdown
# 계산기 배치 테스트 보고서 v3

## 1. 요약
- 총 건수, 유형 수, 비교가능률, 정확도

## 2. 전체 결과 분포
- ✅/⚠️/❌/⏭️ 바 차트 (텍스트)

## 3. 계산 유형별 결과
- 유형별 테이블 (건수, 각 verdict 수, 비교가능 정확도)

## 4. 비교불가 원인 분석
- 원인별 건수 + 비율

## 5. 불일치(❌) 케이스 상세
- 각 불일치 건의 post_id, 오차율, 원인

## 6. 개선 우선순위
- 유형별 (불일치 건수 × 풀 크기) 순위

## 7. 결론 및 제언
```

#### 5-3: 콘솔 보고서

기존 `compare_calculator.py::print_report()` 패턴 확장:
- 전체 요약 (4가지 verdict 분포)
- 비교가능 건 기준 정확도
- 유형별 결과 (축약)
- 상위 10건 불일치 상세

---

## 3. 구현 순서

| 순서 | 항목 | 의존성 |
|------|------|--------|
| 1 | D-1: 메인 스크립트 뼈대 | 없음 |
| 2 | D-2: 층화 샘플링 + load_and_filter | D-1 |
| 3 | D-3: build_wage_input_v3() | D-1, compare_calculator.py |
| 4 | D-4: compare_v3() + 신규 비교 로직 | D-1, D-3 |
| 5 | D-5: 보고서 생성 3종 | D-1, D-4 |
| 6 | 실행 + 결과 확인 | D-1~D-5 전부 |

## 4. 테스트 전략

- **스크립트 실행**: `python3 calculator_batch_test.py` → 정상 종료 확인
- **출력물 검증**: `batch_test_results.json` (500건), `batch_test_report.md` 생성 확인
- **비교불가율**: ≤ 50% 목표 달성 여부
- **에러 없음**: 계산기 오류로 인한 중단 없음 (모두 try/except 포착)

## 5. 설계 결정 근거

| 결정 | 근거 |
|------|------|
| compare_calculator.py에서 import | 기존 추출 함수 1,000줄+ 중복 방지 |
| 퇴직금에 severance+minimum_wage 타겟 | CALC_TYPE_MAP 기존 매핑 준수 |
| 비교불가(⏭️) 세분화 | 원인별 개선 포인트 식별 필요 |
| JSON+MD+콘솔 3종 출력 | JSON=기계분석, MD=보고, 콘솔=즉시확인 |
| normalize_calc_type() | analysis_qna.jsonl 분류값 불일치 해소 (통상시급→통상임금 등) |
