#!/usr/bin/env python3
"""
법원판례/상담사례 vs 계산기 모듈 정확도 벤치마크

output_legal_cases/*.md 사례에서:
1. Claude Haiku로 질문→입력 데이터 추출 + 답변→정답 금액 추출
2. WageInput 생성 → WageCalculator.calculate() 실행
3. 계산기 결과 vs 전문가 답변 비교 → 벤치마크 리포트 생성

사용법:
  python3 benchmark_legal_cases.py                    # 전체 실행
  python3 benchmark_legal_cases.py --limit 10         # 10건만
  python3 benchmark_legal_cases.py --dry-run          # API 미사용
  python3 benchmark_legal_cases.py --skip-extraction   # 이미 추출된 JSON 사용
"""

import os
import re
import json
import time
import argparse
from pathlib import Path
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv()

# ── 설정 ──────────────────────────────────────────────────────────────────────
CASE_DIR = Path(__file__).parent / "output_legal_cases"
EXTRACTION_FILE = Path(__file__).parent / "benchmark_extractions.json"
RESULTS_FILE = Path(__file__).parent / "benchmark_results.json"
MODEL = "claude-haiku-4-5-20251001"

# ── 프롬프트 ──────────────────────────────────────────────────────────────────

EXTRACT_INPUT_SYSTEM = """당신은 한국 노동법 상담 데이터 분석 전문가입니다.
상담 질문에서 임금 계산에 필요한 수치 정보를 정확하게 추출하세요.
반드시 유효한 JSON만 출력하세요."""

EXTRACT_INPUT_PROMPT = """다음 노동상담 질문에서 임금 계산에 필요한 정보를 JSON으로 추출하세요.

## 질문
{question}

## 추출 규칙
- 숫자가 명시된 것만 추출 (추정하지 마세요)
- 임금액은 원 단위 숫자로 (예: 2000000)
- 근무시간은 시간 단위 숫자로
- 계산 유형은 다음 중 선택: 연장수당, 최저임금, 주휴수당, 연차수당, 퇴직금, 해고예고수당, 실업급여, 4대보험, 임금체불, 육아휴직, 출산휴가, 통상임금, 평균임금, 포괄임금, 보상휴가, 휴업수당, 산재보상, 해당없음

JSON 형식:
{{
  "calculation_type": "계산 유형",
  "wage_type": "시급/일급/월급/연봉/포괄임금제 또는 null",
  "wage_amount": 숫자 또는 null,
  "daily_work_hours": 숫자 또는 null,
  "weekly_work_days": 숫자 또는 null,
  "weekly_overtime_hours": 숫자 또는 null,
  "weekly_night_hours": 숫자 또는 null,
  "weekly_holiday_hours": 숫자 또는 null,
  "business_size": "5인미만/5인이상/10인이상/30인이상/300인이상 또는 null",
  "service_period": "근속기간 문자열 또는 null",
  "hourly_wage_in_answer": "답변에서 통상시급으로 제시된 값 또는 null",
  "fixed_allowances": [{{"name": "수당명", "amount": 숫자}}] 또는 [],
  "has_calculable_numbers": true/false,
  "extraction_note": "추출 시 특이사항"
}}

JSON만 출력하세요 (코드블록 없이)."""

EXTRACT_ANSWER_SYSTEM = """당신은 한국 노동법 전문가입니다.
전문가 답변에서 구체적인 계산 결과 수치를 정확하게 추출하세요.
반드시 유효한 JSON만 출력하세요."""

EXTRACT_ANSWER_PROMPT = """다음 노동상담 전문가 답변에서 구체적인 금액/수치 결과를 추출하세요.

## 질문 유형
{calculation_type}

## 답변
{answer}

## 추출 규칙
- 전문가가 최종적으로 제시한 금액만 추출
- 법률 조문이나 일반 설명의 숫자는 제외
- 금액은 원 단위 숫자로 (예: 187500)
- 여러 금액이 있으면 모두 추출

JSON 형식:
{{
  "amounts": [
    {{"label": "금액 설명", "value": 숫자, "unit": "원/원/일/원/월/원/시간 등"}}
  ],
  "hourly_wage": 숫자 또는 null,
  "daily_wage": 숫자 또는 null,
  "monthly_wage": 숫자 또는 null,
  "judgment": "충족/미달/가능/불가 등 판단 결과 또는 null",
  "formula_shown": "답변에 나온 계산식 또는 null",
  "has_concrete_numbers": true/false,
  "answer_note": "답변 해석 특이사항"
}}

JSON만 출력하세요 (코드블록 없이)."""


# ── Mode 2: 통합 추출 (질문+답변 전체를 보고 테스트 케이스 생성) ─────────────

UNIFIED_EXTRACT_SYSTEM = """당신은 한국 노동법 임금계산 전문가입니다.
상담 사례의 질문과 답변 전체를 읽고, 이 사례에서 임금계산기로 검증할 수 있는
구체적인 테스트 케이스를 생성하세요. 반드시 유효한 JSON만 출력하세요."""

UNIFIED_EXTRACT_PROMPT = """다음 노동상담 사례를 읽고, 임금계산기로 테스트할 수 있는 케이스를 생성하세요.

## 질문
{question}

## 전문가 답변
{answer}

## 생성 규칙
1. 질문+답변에서 구체적 숫자를 모두 수집
2. 답변에서 전문가가 계산한 결과 금액을 "정답"으로 추출
3. 질문에 임금액이 없으면 답변에서 사용한 시급/월급을 사용
4. 계산 유형 선택: 연장수당/최저임금/주휴수당/연차수당/퇴직금/해고예고수당/실업급여/4대보험/임금체불/육아휴직/출산휴가/통상임금/평균임금/포괄임금/보상휴가/휴업수당/산재보상/해당없음
5. "해당없음"은 임금 계산과 무관한 사례에만 사용
6. daily_work_hours는 24 이하, weekly_work_days는 7 이하여야 합니다
7. 답변에서 전문가가 사용한 근로시간과 질문의 근로시간이 다르면, 답변의 값을 우선 사용하세요
8. 기본급 외에 매월 고정 지급되는 수당(직무/직책/식대/교통비/위험수당 등)이 있으면 반드시 fixed_allowances에 항목별로 추출하세요
9. 답변에서 "통상임금 = (기본급 + 수당) ÷ 시간" 형태의 계산이 있으면, 분자에 포함된 수당을 fixed_allowances로 분리하세요

JSON 형식:
{{
  "is_calculator_testable": true/false,
  "skip_reason": "테스트 불가 사유 (testable=false일 때만)",
  "calculation_type": "계산 유형",
  "test_input": {{
    "wage_type": "시급/일급/월급/연봉/포괄임금제",
    "wage_amount": 숫자,
    "daily_work_hours": 숫자 또는 null,
    "weekly_work_days": 숫자 또는 null,
    "weekly_overtime_hours": 숫자 또는 null,
    "weekly_night_hours": 숫자 또는 null,
    "weekly_holiday_hours": 숫자 또는 null,
    "business_size": "5인미만/5인이상/10인이상/30인이상/300인이상",
    "service_period": "근속기간 문자열 또는 null",
    "fixed_allowances": [{{"name": "수당명", "amount": 숫자}}]
  }},
  "expected_results": [
    {{"label": "항목명", "value": 숫자, "unit": "원 또는 기타 단위", "comparison_type": "exact/range/judgment"}}
  ],
  "expert_formula": "전문가가 사용한 계산식 (있으면)",
  "note": "특이사항"
}}

JSON만 출력하세요 (코드블록 없이)."""


# ── 사례 파싱 ──────────────────────────────────────────────────────────────────

def parse_case_file(filepath: Path) -> dict | None:
    """마크다운 사례 파일을 섹션별로 파싱"""
    text = filepath.read_text(encoding="utf-8")
    if not text.strip():
        return None

    # 제목 추출
    title_match = re.match(r"#\s+(.+)", text)
    title = title_match.group(1) if title_match else filepath.stem

    # 메타데이터 테이블 파싱
    meta = {}
    for m in re.finditer(r"\|\s*(\S+)\s*\|\s*(.+?)\s*\|", text):
        meta[m.group(1)] = m.group(2).strip()

    # 섹션 분리
    sections = {}
    current_section = None
    current_lines = []

    for line in text.split("\n"):
        h2_match = re.match(r"^##\s+(.+)", line)
        if h2_match:
            if current_section:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = h2_match.group(1).strip()
            current_lines = []
        elif current_section:
            current_lines.append(line)

    if current_section:
        sections[current_section] = "\n".join(current_lines).strip()

    question = sections.get("질문", "")
    answer = sections.get("답변", "")

    if not question:
        return None

    # 사례번호 추출
    case_num = re.search(r"case_(\d+)", filepath.stem)
    case_id = int(case_num.group(1)) if case_num else 0

    return {
        "case_id": case_id,
        "filename": filepath.name,
        "title": title,
        "subject": meta.get("주제", ""),
        "source": meta.get("출처", ""),
        "laws": meta.get("관련법령", ""),
        "question": question[:3000],  # 토큰 절감
        "answer": answer[:3000],
        "has_answer": bool(answer),
        "full_text_length": len(text),
    }


def load_all_cases(limit: int | None = None) -> list[dict]:
    """모든 사례 파일 로드"""
    files = sorted(CASE_DIR.glob("case_*.md"))
    if limit:
        files = files[:limit]

    cases = []
    for f in files:
        parsed = parse_case_file(f)
        if parsed:
            cases.append(parsed)
    return cases


# ── Claude API 호출 ──────────────────────────────────────────────────────────

def call_claude(system: str, prompt: str, max_retries: int = 3) -> str | None:
    """Claude Haiku API 호출"""
    import anthropic
    client = anthropic.Anthropic()

    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=2000,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()
        except Exception as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"  ⚠️ API 오류 (재시도 {attempt+1}/{max_retries}, {wait}s 대기): {e}")
                time.sleep(wait)
            else:
                print(f"  ❌ API 실패: {e}")
                return None


def parse_json_response(text: str) -> dict | None:
    """Claude 응답에서 JSON 추출"""
    if not text:
        return None

    # 코드블록 제거
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*$", "", text)
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # JSON 부분만 추출 시도
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                return None
    return None


# ── 데이터 추출 ──────────────────────────────────────────────────────────────

def extract_input_and_answer(case: dict) -> dict:
    """사례에서 입력 데이터 + 정답 추출 (Claude 사용)"""
    result = {
        "case_id": case["case_id"],
        "filename": case["filename"],
        "title": case["title"],
        "input_extraction": None,
        "answer_extraction": None,
        "status": "pending",
    }

    # Phase 1: 질문에서 입력 데이터 추출
    prompt1 = EXTRACT_INPUT_PROMPT.format(question=case["question"])
    raw1 = call_claude(EXTRACT_INPUT_SYSTEM, prompt1)
    input_data = parse_json_response(raw1)

    if input_data:
        result["input_extraction"] = input_data
    else:
        result["status"] = "extraction_failed"
        result["error"] = "입력 추출 실패"
        return result

    # Phase 2: 답변에서 정답 추출
    if not case["has_answer"] or not case["answer"].strip():
        result["status"] = "no_answer"
        return result

    calc_type = input_data.get("calculation_type", "해당없음")
    prompt2 = EXTRACT_ANSWER_PROMPT.format(
        calculation_type=calc_type,
        answer=case["answer"],
    )
    raw2 = call_claude(EXTRACT_ANSWER_SYSTEM, prompt2)
    answer_data = parse_json_response(raw2)

    if answer_data:
        result["answer_extraction"] = answer_data
        result["status"] = "extracted"
    else:
        result["status"] = "answer_extraction_failed"

    return result


def extract_unified(case: dict) -> dict:
    """통합 추출: 질문+답변 전체를 보고 테스트 케이스 생성 (Mode 2)"""
    result = {
        "case_id": case["case_id"],
        "filename": case["filename"],
        "title": case["title"],
        "unified_extraction": None,
        "status": "pending",
    }

    if not case["has_answer"] or not case["answer"].strip():
        result["status"] = "no_answer"
        return result

    prompt = UNIFIED_EXTRACT_PROMPT.format(
        question=case["question"],
        answer=case["answer"],
    )
    raw = call_claude(UNIFIED_EXTRACT_SYSTEM, prompt)
    data = parse_json_response(raw)

    if data:
        # Claude가 배열로 반환하는 경우 첫 번째 요소 사용
        if isinstance(data, list):
            data = data[0] if data else {}
        result["unified_extraction"] = data
        if data.get("is_calculator_testable"):
            result["status"] = "testable"
        else:
            result["status"] = "not_testable"
            result["skip_reason"] = data.get("skip_reason", "")
    else:
        result["status"] = "extraction_failed"

    return result


def build_wage_input_from_unified(extraction: dict) -> "tuple[object, list[str]] | None":
    """통합 추출 결과 → WageInput + targets"""
    from wage_calculator.models import WageInput, WageType, BusinessSize, WorkSchedule
    from wage_calculator.facade import resolve_calc_type

    udata = extraction.get("unified_extraction")
    if not udata or not udata.get("is_calculator_testable"):
        return None

    test_input = udata.get("test_input", {})
    if isinstance(test_input, list):
        test_input = test_input[0] if test_input else {}
    if not isinstance(test_input, dict) or not test_input.get("wage_amount"):
        return None

    wage_type_map = {
        "시급": WageType.HOURLY,
        "일급": WageType.DAILY,
        "월급": WageType.MONTHLY,
        "연봉": WageType.ANNUAL,
        "포괄임금제": WageType.COMPREHENSIVE,
    }
    wt_str = test_input.get("wage_type", "월급")
    wage_type = wage_type_map.get(wt_str, WageType.MONTHLY)
    wage_amount = float(test_input["wage_amount"])

    size_map = {
        "5인미만": BusinessSize.UNDER_5,
        "5인이상": BusinessSize.OVER_5,
        "10인이상": BusinessSize.OVER_10,
        "30인이상": BusinessSize.OVER_30,
        "300인이상": BusinessSize.OVER_300,
    }
    biz_size = size_map.get(test_input.get("business_size", "5인이상"), BusinessSize.OVER_5)

    # 입력 클램핑 — 비정상 값 방지
    daily_hours = min(float(test_input.get("daily_work_hours") or 8), 24.0)
    weekly_days = min(float(test_input.get("weekly_work_days") or 5), 7.0)

    schedule = WorkSchedule(
        daily_work_hours=daily_hours,
        weekly_work_days=weekly_days,
        weekly_overtime_hours=float(test_input.get("weekly_overtime_hours") or 0),
        weekly_night_hours=float(test_input.get("weekly_night_hours") or 0),
        weekly_holiday_hours=float(test_input.get("weekly_holiday_hours") or 0),
    )

    inp = WageInput(wage_type=wage_type, business_size=biz_size, schedule=schedule)

    if wage_type == WageType.HOURLY:
        inp.hourly_wage = wage_amount
    elif wage_type == WageType.DAILY:
        inp.daily_wage = wage_amount
    elif wage_type in (WageType.MONTHLY, WageType.COMPREHENSIVE):
        inp.monthly_wage = wage_amount
    elif wage_type == WageType.ANNUAL:
        inp.annual_wage = wage_amount

    for a in (test_input.get("fixed_allowances") or []):
        if isinstance(a, dict) and a.get("amount"):
            inp.fixed_allowances.append({
                "name": a.get("name", "기타수당"),
                "amount": float(a["amount"]),
            })

    service_period = test_input.get("service_period")
    if service_period:
        start = _guess_start_date(service_period)
        if start:
            inp.start_date = start

    calc_type = udata.get("calculation_type", "해당없음")
    targets = resolve_calc_type(calc_type)

    return inp, targets


# ── label ↔ summary key 의미 매핑 ─────────────────────────────────────────────
LABEL_TO_KEY_MAP = {
    "주휴수당":     ["주휴수당(월)", "주휴수당"],
    "연장수당":     ["연장/야간/휴일수당(월)"],
    "야간수당":     ["연장/야간/휴일수당(월)"],
    "야간근로수당":  ["연장/야간/휴일수당(월)"],
    "휴일수당":     ["연장/야간/휴일수당(월)"],
    "휴일근로수당":  ["연장/야간/휴일수당(월)"],
    "통상시급":     ["실질시급"],
    "시급":         ["실질시급"],
    "최저임금":     ["최저임금 충족"],
    "부족분":       ["부족분(월)"],
    "퇴직금":       ["퇴직금"],
    "평균임금":     ["1일 평균임금"],
    "구직급여":     ["구직급여 일액"],
}


def _extract_number(val_str: str) -> float | None:
    """summary 값 문자열에서 첫 번째 숫자 추출"""
    nums = re.findall(r"[\d,]+", str(val_str).replace(",", ""))
    for num_str in nums:
        try:
            v = float(num_str.replace(",", ""))
            if v > 0:
                return v
        except (ValueError, TypeError):
            continue
    return None


def _classify_mismatch(item: str, diff_pct: float, calc_val: float, answer_val: float) -> str:
    """MISMATCH 원인 유형 자동 분류"""
    if "시급" in item and 15 < diff_pct < 35:
        lo, hi = min(calc_val, answer_val), max(calc_val, answer_val)
        if lo > 0 and 1.2 < hi / lo < 1.35:
            return "MISMATCH_BASEHOURS"
    return "MISMATCH"


def compare_unified(calc_result: dict, expected_results: list) -> dict:
    """통합 추출의 expected_results와 계산기 결과 비교 — label 기반 우선 매칭"""
    comparison = {
        "verdict": "SKIP",
        "matches": [],
        "mismatches": [],
        "details": "",
    }

    if "error" in calc_result:
        comparison["verdict"] = "ERROR"
        comparison["details"] = calc_result["error"]
        return comparison

    if not expected_results:
        comparison["verdict"] = "NO_EXPECTED"
        comparison["details"] = "기대 결과 없음"
        return comparison

    calc_summary = calc_result.get("summary", {})
    calc_hourly = calc_result.get("ordinary_hourly", 0)

    for exp in expected_results:
        label = exp.get("label", "")
        value = exp.get("value")

        if not value or not isinstance(value, (int, float)):
            continue

        best_match = None
        best_pct = 999

        # Phase 1: label 키워드 → LABEL_TO_KEY_MAP → summary key 직접 매칭
        for keyword, target_keys in LABEL_TO_KEY_MAP.items():
            if keyword in label:
                for tkey in target_keys:
                    if tkey in calc_summary:
                        calc_val = _extract_number(calc_summary[tkey])
                        if calc_val is not None:
                            pct = (abs(calc_val - value) / value * 100) if value > 0 else 0
                            if pct < best_pct:
                                best_match = (tkey, calc_val)
                                best_pct = pct
                break  # 첫 매칭 키워드에서 중단

        # Phase 2: 통상시급 직접 비교
        if best_match is None and ("시급" in label or "hourly" in label.lower()):
            if calc_hourly > 0:
                pct = (abs(calc_hourly - value) / value * 100) if value > 0 else 0
                if pct < best_pct:
                    best_match = ("통상시급", calc_hourly)
                    best_pct = pct

        # Phase 3: 숫자 근접도 fallback (30% 이내)
        if best_match is None:
            for key, val_str in calc_summary.items():
                calc_val = _extract_number(val_str)
                if calc_val is not None:
                    pct = (abs(calc_val - value) / value * 100) if value > 0 else 0
                    if pct < best_pct:
                        best_match = (key, calc_val)
                        best_pct = pct

        if best_match and best_pct <= 30:
            entry = {
                "item": f"{label} ↔ {best_match[0]}",
                "calculator": round(best_match[1]),
                "answer": round(value),
                "diff_pct": round(best_pct, 1),
            }
            if best_pct <= 5:
                comparison["matches"].append(entry)
            else:
                entry["mismatch_type"] = _classify_mismatch(
                    label, best_pct, best_match[1], value
                )
                comparison["mismatches"].append(entry)

    total = len(comparison["matches"]) + len(comparison["mismatches"])
    if total == 0:
        comparison["verdict"] = "NO_COMPARABLE"
        comparison["details"] = "비교 가능한 수치 없음"
    elif len(comparison["mismatches"]) == 0:
        comparison["verdict"] = "MATCH"
        comparison["details"] = f"{len(comparison['matches'])}건 일치"
    elif len(comparison["matches"]) == 0:
        comparison["verdict"] = "MISMATCH"
        comparison["details"] = f"{len(comparison['mismatches'])}건 불일치"
    else:
        comparison["verdict"] = "PARTIAL"
        comparison["details"] = (
            f"{len(comparison['matches'])}건 일치, "
            f"{len(comparison['mismatches'])}건 불일치"
        )

    return comparison


# ── WageInput 변환 & 계산기 실행 ──────────────────────────────────────────────

def build_wage_input(extraction: dict) -> "tuple[object, list[str]] | None":
    """추출된 데이터 → WageInput + targets 생성"""
    from wage_calculator.models import WageInput, WageType, BusinessSize, WorkSchedule
    from wage_calculator.facade import CALC_TYPE_MAP
    from wage_calculator.constants import MINIMUM_HOURLY_WAGE

    inp_data = extraction.get("input_extraction")
    if not inp_data:
        return None

    if not inp_data.get("has_calculable_numbers", False):
        return None

    # 임금 유형 매핑
    wage_type_map = {
        "시급": WageType.HOURLY,
        "일급": WageType.DAILY,
        "월급": WageType.MONTHLY,
        "연봉": WageType.ANNUAL,
        "포괄임금제": WageType.COMPREHENSIVE,
    }
    wt_str = inp_data.get("wage_type") or "월급"
    wage_type = wage_type_map.get(wt_str, WageType.MONTHLY)

    wage_amount = inp_data.get("wage_amount")
    if not wage_amount or not isinstance(wage_amount, (int, float)):
        # Fallback: 답변의 시급 또는 2022년 최저임금 사용 (사례집은 2022년 기준)
        answer_hourly = inp_data.get("hourly_wage_in_answer")
        if answer_hourly:
            try:
                wage_amount = float(str(answer_hourly).replace(",", ""))
                wage_type = WageType.HOURLY
            except (ValueError, TypeError):
                pass
        if not wage_amount:
            # 근무시간 정보가 있으면 2022 최저임금으로 시급 설정
            has_hours = (inp_data.get("daily_work_hours") or
                         inp_data.get("weekly_overtime_hours") or
                         inp_data.get("weekly_work_days"))
            if has_hours:
                wage_amount = MINIMUM_HOURLY_WAGE.get(2022, 9160)  # 2022년 최저임금
                wage_type = WageType.HOURLY
            else:
                return None

    # 사업장 규모
    size_map = {
        "5인미만": BusinessSize.UNDER_5,
        "5인이상": BusinessSize.OVER_5,
        "10인이상": BusinessSize.OVER_10,
        "30인이상": BusinessSize.OVER_30,
        "300인이상": BusinessSize.OVER_300,
    }
    biz_str = inp_data.get("business_size") or "5인이상"
    biz_size = size_map.get(biz_str, BusinessSize.OVER_5)

    # 근무 스케줄
    schedule = WorkSchedule(
        daily_work_hours=float(inp_data.get("daily_work_hours") or 8),
        weekly_work_days=float(inp_data.get("weekly_work_days") or 5),
        weekly_overtime_hours=float(inp_data.get("weekly_overtime_hours") or 0),
        weekly_night_hours=float(inp_data.get("weekly_night_hours") or 0),
        weekly_holiday_hours=float(inp_data.get("weekly_holiday_hours") or 0),
    )

    inp = WageInput(
        wage_type=wage_type,
        business_size=biz_size,
        schedule=schedule,
    )

    # 임금액 설정
    if wage_type == WageType.HOURLY:
        inp.hourly_wage = wage_amount
    elif wage_type == WageType.DAILY:
        inp.daily_wage = wage_amount
    elif wage_type in (WageType.MONTHLY, WageType.COMPREHENSIVE):
        inp.monthly_wage = wage_amount
    elif wage_type == WageType.ANNUAL:
        inp.annual_wage = wage_amount

    # 고정수당
    allowances = inp_data.get("fixed_allowances") or []
    for a in allowances:
        if isinstance(a, dict) and a.get("amount"):
            inp.fixed_allowances.append({
                "name": a.get("name", "기타수당"),
                "amount": float(a["amount"]),
            })

    # 근속기간 → start_date
    service_period = inp_data.get("service_period")
    if service_period:
        start = _guess_start_date(service_period)
        if start:
            inp.start_date = start

    # 계산 유형 → targets
    calc_type = inp_data.get("calculation_type", "해당없음")
    targets = CALC_TYPE_MAP.get(calc_type, ["minimum_wage"])

    return inp, targets


def _guess_start_date(period_str: str) -> str | None:
    """근속기간 문자열 → 시작일 추정"""
    today = date.today()
    years = re.search(r"(\d+)\s*년", period_str)
    months = re.search(r"(\d+)\s*개월", period_str)

    total_days = 0
    if years:
        total_days += int(years.group(1)) * 365
    if months:
        total_days += int(months.group(1)) * 30

    if total_days > 0:
        start = today - timedelta(days=total_days)
        return start.isoformat()
    return None


def run_calculator(inp, targets: list[str]) -> dict | None:
    """WageCalculator 실행"""
    from wage_calculator.facade import WageCalculator
    try:
        calc = WageCalculator()
        result = calc.calculate(inp, targets)
        return {
            "summary": result.summary,
            "monthly_total": result.monthly_total,
            "ordinary_hourly": result.ordinary_hourly,
            "warnings": result.warnings,
            "legal_basis": result.legal_basis,
            "formulas": result.formulas,
        }
    except Exception as e:
        return {"error": str(e)}


# ── 비교 엔진 ────────────────────────────────────────────────────────────────

def compare_results(calc_result: dict, answer_extraction: dict, input_extraction: dict) -> dict:
    """계산기 결과 vs 전문가 답변 비교"""
    comparison = {
        "verdict": "SKIP",  # MATCH, MISMATCH, PARTIAL, SKIP
        "matches": [],
        "mismatches": [],
        "details": "",
    }

    if not answer_extraction or not answer_extraction.get("has_concrete_numbers"):
        comparison["verdict"] = "SKIP_ANSWER"
        comparison["details"] = "답변에 구체적 숫자 없음"
        return comparison

    if "error" in calc_result:
        comparison["verdict"] = "ERROR"
        comparison["details"] = calc_result["error"]
        return comparison

    calc_hourly = calc_result.get("ordinary_hourly", 0)
    answer_amounts = answer_extraction.get("amounts", [])
    answer_hourly = answer_extraction.get("hourly_wage")
    answer_daily = answer_extraction.get("daily_wage")
    answer_monthly = answer_extraction.get("monthly_wage")
    answer_judgment = answer_extraction.get("judgment")
    calc_summary = calc_result.get("summary", {})

    # 1) 시급 비교
    if answer_hourly and calc_hourly:
        try:
            ans_h = float(answer_hourly)
            diff = abs(calc_hourly - ans_h)
            pct = (diff / ans_h * 100) if ans_h > 0 else 0
            entry = {
                "item": "통상시급",
                "calculator": round(calc_hourly),
                "answer": round(ans_h),
                "diff": round(diff),
                "diff_pct": round(pct, 1),
            }
            if pct <= 5:
                comparison["matches"].append(entry)
            else:
                comparison["mismatches"].append(entry)
        except (ValueError, TypeError):
            pass

    # 2) 답변 금액들 vs 계산기 summary 비교
    for amt in answer_amounts:
        label = amt.get("label", "")
        value = amt.get("value")
        if not value or not isinstance(value, (int, float)):
            continue

        # summary에서 매칭되는 항목 찾기
        matched = False
        for key, val_str in calc_summary.items():
            # 금액 추출
            nums = re.findall(r"[\d,]+", str(val_str).replace(",", ""))
            for num_str in nums:
                try:
                    calc_val = float(num_str.replace(",", ""))
                    if calc_val == 0:
                        continue
                    diff = abs(calc_val - value)
                    pct = (diff / value * 100) if value > 0 else 0
                    if pct <= 20:  # 20% 이내면 매칭 후보
                        entry = {
                            "item": f"{label} ↔ {key}",
                            "calculator": round(calc_val),
                            "answer": round(value),
                            "diff": round(diff),
                            "diff_pct": round(pct, 1),
                        }
                        if pct <= 5:
                            comparison["matches"].append(entry)
                        else:
                            comparison["mismatches"].append(entry)
                        matched = True
                        break
                except (ValueError, TypeError):
                    continue
            if matched:
                break

    # 3) Yes/No 판단 비교
    if answer_judgment:
        j = answer_judgment.lower()
        if "충족" in j or "가능" in j:
            expected = True
        elif "미달" in j or "불가" in j or "위반" in j:
            expected = False
        else:
            expected = None

        if expected is not None:
            calc_ok = calc_summary.get("최저임금 충족", "")
            if calc_ok:
                actual = "✅" in calc_ok
                entry = {
                    "item": "판단(최저임금)",
                    "calculator": "충족" if actual else "미달",
                    "answer": "충족" if expected else "미달",
                }
                if actual == expected:
                    comparison["matches"].append(entry)
                else:
                    comparison["mismatches"].append(entry)

    # 종합 판정
    total = len(comparison["matches"]) + len(comparison["mismatches"])
    if total == 0:
        comparison["verdict"] = "NO_COMPARABLE"
        comparison["details"] = "비교 가능한 수치 없음"
    elif len(comparison["mismatches"]) == 0:
        comparison["verdict"] = "MATCH"
        comparison["details"] = f"{len(comparison['matches'])}건 일치"
    elif len(comparison["matches"]) == 0:
        comparison["verdict"] = "MISMATCH"
        comparison["details"] = f"{len(comparison['mismatches'])}건 불일치"
    else:
        comparison["verdict"] = "PARTIAL"
        comparison["details"] = (
            f"{len(comparison['matches'])}건 일치, "
            f"{len(comparison['mismatches'])}건 불일치"
        )

    return comparison


# ── 메인 파이프라인 ──────────────────────────────────────────────────────────

def run_benchmark(cases: list[dict], skip_extraction: bool = False, dry_run: bool = False):
    """벤치마크 전체 실행"""
    extractions = []

    if skip_extraction and EXTRACTION_FILE.exists():
        print(f"📂 기존 추출 파일 로드: {EXTRACTION_FILE}")
        extractions = json.loads(EXTRACTION_FILE.read_text(encoding="utf-8"))
    else:
        print(f"\n{'='*60}")
        print(f"Phase 1: 데이터 추출 (Claude Haiku)")
        print(f"{'='*60}")

        for i, case in enumerate(cases):
            tag = f"[{i+1}/{len(cases)}] case_{case['case_id']:03d}"
            print(f"\n{tag} {case['title'][:40]}...")

            if dry_run:
                print(f"  📋 질문 길이: {len(case['question'])}자, 답변: {'있음' if case['has_answer'] else '없음'}")
                extractions.append({
                    "case_id": case["case_id"],
                    "filename": case["filename"],
                    "title": case["title"],
                    "status": "dry_run",
                })
                continue

            ext = extract_input_and_answer(case)
            extractions.append(ext)

            calc_type = "?"
            if ext.get("input_extraction"):
                calc_type = ext["input_extraction"].get("calculation_type", "?")
            print(f"  → 유형: {calc_type}, 상태: {ext['status']}")

            time.sleep(0.3)  # rate limit

        # 추출 결과 저장
        EXTRACTION_FILE.write_text(
            json.dumps(extractions, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n💾 추출 결과 저장: {EXTRACTION_FILE}")

    if dry_run:
        print(f"\n🏁 Dry run 완료 ({len(cases)}건)")
        return

    # Phase 2: 계산기 실행 & 비교
    print(f"\n{'='*60}")
    print(f"Phase 2: 계산기 실행 & 비교")
    print(f"{'='*60}")

    results = []
    stats = {
        "total": len(extractions),
        "calculable": 0,
        "match": 0,
        "mismatch": 0,
        "partial": 0,
        "skip": 0,
        "error": 0,
        "by_type": {},
    }

    for ext in extractions:
        case_id = ext["case_id"]
        tag = f"[case_{case_id:03d}]"

        entry = {
            "case_id": case_id,
            "filename": ext["filename"],
            "title": ext["title"],
            "extraction_status": ext["status"],
            "input_extraction": ext.get("input_extraction"),
            "answer_extraction": ext.get("answer_extraction"),
            "calc_result": None,
            "comparison": None,
        }

        if ext["status"] != "extracted":
            entry["comparison"] = {"verdict": f"SKIP_{ext['status'].upper()}", "details": ext.get("error", "")}
            stats["skip"] += 1
            results.append(entry)
            continue

        # WageInput 생성
        built = build_wage_input(ext)
        if built is None:
            entry["comparison"] = {"verdict": "SKIP_INPUT", "details": "WageInput 변환 불가"}
            stats["skip"] += 1
            results.append(entry)
            print(f"  {tag} ⏭️ 입력 변환 불가")
            continue

        inp, targets = built
        stats["calculable"] += 1
        calc_type = ext["input_extraction"].get("calculation_type", "기타")

        # 계산기 실행
        calc_result = run_calculator(inp, targets)
        entry["calc_result"] = calc_result
        entry["targets"] = targets

        # 비교
        comparison = compare_results(calc_result, ext.get("answer_extraction"), ext.get("input_extraction"))
        entry["comparison"] = comparison

        verdict = comparison["verdict"]
        print(f"  {tag} {calc_type:10s} → {verdict:15s} | {comparison['details']}")

        # 통계
        if verdict == "MATCH":
            stats["match"] += 1
        elif verdict == "MISMATCH":
            stats["mismatch"] += 1
        elif verdict == "PARTIAL":
            stats["partial"] += 1
        elif verdict == "ERROR":
            stats["error"] += 1
        else:
            stats["skip"] += 1

        # 유형별 통계
        if calc_type not in stats["by_type"]:
            stats["by_type"][calc_type] = {"total": 0, "match": 0, "mismatch": 0, "partial": 0, "skip": 0}
        stats["by_type"][calc_type]["total"] += 1
        if verdict in ("MATCH", "MISMATCH", "PARTIAL"):
            stats["by_type"][calc_type][verdict.lower()] += 1
        else:
            stats["by_type"][calc_type]["skip"] += 1

        results.append(entry)

    # Phase 3: 리포트 생성
    print(f"\n{'='*60}")
    print(f"📊 벤치마크 결과 요약")
    print(f"{'='*60}")

    comparable = stats["match"] + stats["mismatch"] + stats["partial"]
    match_rate = (stats["match"] / comparable * 100) if comparable > 0 else 0

    print(f"\n총 사례:        {stats['total']}건")
    print(f"계산 가능:      {stats['calculable']}건")
    print(f"비교 가능:      {comparable}건")
    print(f"─────────────────────────────")
    print(f"✅ 일치(MATCH):  {stats['match']}건 ({match_rate:.1f}%)")
    print(f"⚠️ 부분(PARTIAL): {stats['partial']}건")
    print(f"❌ 불일치(MISMATCH): {stats['mismatch']}건")
    print(f"⏭️ 스킵:         {stats['skip']}건")
    print(f"💥 에러:         {stats['error']}건")

    if stats["by_type"]:
        print(f"\n📈 유형별 결과:")
        print(f"{'유형':15s} {'전체':>5s} {'일치':>5s} {'부분':>5s} {'불일치':>5s} {'스킵':>5s}")
        print(f"{'─'*50}")
        for t, s in sorted(stats["by_type"].items(), key=lambda x: x[1]["total"], reverse=True):
            print(f"{t:15s} {s['total']:5d} {s['match']:5d} {s['partial']:5d} {s['mismatch']:5d} {s['skip']:5d}")

    # MISMATCH 상세
    mismatches = [r for r in results if r.get("comparison", {}).get("verdict") in ("MISMATCH", "PARTIAL")]
    if mismatches:
        print(f"\n🔍 불일치/부분일치 상세 ({len(mismatches)}건):")
        for r in mismatches[:20]:
            comp = r["comparison"]
            print(f"\n  case_{r['case_id']:03d}: {r['title'][:50]}")
            for m in comp.get("mismatches", []):
                print(f"    ❌ {m['item']}: 계산기={m.get('calculator', '?')} vs 정답={m.get('answer', '?')} (차이 {m.get('diff_pct', '?')}%)")
            for m in comp.get("matches", []):
                print(f"    ✅ {m['item']}: {m.get('calculator', '?')}")

    # JSON 저장
    report = {
        "benchmark_date": date.today().isoformat(),
        "model": MODEL,
        "stats": stats,
        "match_rate_pct": round(match_rate, 1),
        "comparable_count": comparable,
        "results": results,
    }
    RESULTS_FILE.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n💾 상세 결과 저장: {RESULTS_FILE}")


# ── 통합 모드 벤치마크 (Mode 2) ──────────────────────────────────────────────

UNIFIED_EXTRACTION_FILE = Path(__file__).parent / "benchmark_unified_extractions.json"
UNIFIED_RESULTS_FILE = Path(__file__).parent / "benchmark_unified_results.json"


def run_unified_benchmark(cases: list[dict], skip_extraction: bool = False, dry_run: bool = False):
    """통합 모드 벤치마크: 질문+답변 전체를 한번에 분석"""
    extractions = []

    if skip_extraction and UNIFIED_EXTRACTION_FILE.exists():
        print(f"📂 기존 통합 추출 파일 로드: {UNIFIED_EXTRACTION_FILE}")
        extractions = json.loads(UNIFIED_EXTRACTION_FILE.read_text(encoding="utf-8"))
    else:
        print(f"\n{'='*60}")
        print(f"Phase 1: 통합 데이터 추출 (질문+답변 → 테스트 케이스)")
        print(f"{'='*60}")

        for i, case in enumerate(cases):
            tag = f"[{i+1}/{len(cases)}] case_{case['case_id']:03d}"
            print(f"\n{tag} {case['title'][:40]}...")

            if dry_run:
                print(f"  📋 질문: {len(case['question'])}자, 답변: {'있음' if case['has_answer'] else '없음'}")
                extractions.append({
                    "case_id": case["case_id"],
                    "filename": case["filename"],
                    "title": case["title"],
                    "status": "dry_run",
                })
                continue

            ext = extract_unified(case)
            extractions.append(ext)

            calc_type = "?"
            if ext.get("unified_extraction"):
                calc_type = ext["unified_extraction"].get("calculation_type", "?")
            testable = ext["unified_extraction"].get("is_calculator_testable") if ext.get("unified_extraction") else False
            print(f"  → 유형: {calc_type}, 테스트가능: {'예' if testable else '아니오'}, 상태: {ext['status']}")

            time.sleep(0.3)

        UNIFIED_EXTRACTION_FILE.write_text(
            json.dumps(extractions, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n💾 통합 추출 결과 저장: {UNIFIED_EXTRACTION_FILE}")

    if dry_run:
        print(f"\n🏁 Dry run 완료 ({len(cases)}건)")
        return

    # Phase 2: 계산기 실행 & 비교
    print(f"\n{'='*60}")
    print(f"Phase 2: 계산기 실행 & 비교")
    print(f"{'='*60}")

    results = []
    stats = {
        "total": len(extractions),
        "testable": 0,
        "calculable": 0,
        "match": 0,
        "mismatch": 0,
        "partial": 0,
        "skip": 0,
        "error": 0,
        "by_type": {},
    }

    for ext in extractions:
        case_id = ext["case_id"]
        tag = f"[case_{case_id:03d}]"

        entry = {
            "case_id": case_id,
            "filename": ext["filename"],
            "title": ext["title"],
            "extraction_status": ext["status"],
            "unified_extraction": ext.get("unified_extraction"),
            "calc_result": None,
            "comparison": None,
        }

        if ext["status"] != "testable":
            reason = ext.get("skip_reason", ext["status"])
            entry["comparison"] = {"verdict": "SKIP", "details": reason}
            stats["skip"] += 1
            results.append(entry)
            continue

        stats["testable"] += 1
        udata = ext["unified_extraction"]
        calc_type = udata.get("calculation_type", "기타")

        # WageInput 생성
        built = build_wage_input_from_unified(ext)
        if built is None:
            entry["comparison"] = {"verdict": "SKIP_INPUT", "details": "WageInput 변환 불가"}
            stats["skip"] += 1
            results.append(entry)
            print(f"  {tag} ⏭️ 입력 변환 불가 ({calc_type})")
            continue

        inp, targets = built
        stats["calculable"] += 1

        # 계산기 실행
        calc_result = run_calculator(inp, targets)
        entry["calc_result"] = calc_result
        entry["targets"] = targets

        # 비교
        expected = udata.get("expected_results", [])
        comparison = compare_unified(calc_result, expected)
        entry["comparison"] = comparison

        verdict = comparison["verdict"]
        print(f"  {tag} {calc_type:10s} → {verdict:15s} | {comparison['details']}")

        # 통계
        if verdict == "MATCH":
            stats["match"] += 1
        elif verdict == "MISMATCH":
            stats["mismatch"] += 1
        elif verdict == "PARTIAL":
            stats["partial"] += 1
        elif verdict == "ERROR":
            stats["error"] += 1
        else:
            stats["skip"] += 1

        if calc_type not in stats["by_type"]:
            stats["by_type"][calc_type] = {"total": 0, "match": 0, "mismatch": 0, "partial": 0, "skip": 0}
        stats["by_type"][calc_type]["total"] += 1
        if verdict in ("MATCH", "MISMATCH", "PARTIAL"):
            stats["by_type"][calc_type][verdict.lower()] += 1
        else:
            stats["by_type"][calc_type]["skip"] += 1

        results.append(entry)

    # Phase 3: 리포트
    print(f"\n{'='*60}")
    print(f"📊 통합 벤치마크 결과 요약")
    print(f"{'='*60}")

    comparable = stats["match"] + stats["mismatch"] + stats["partial"]
    match_rate = (stats["match"] / comparable * 100) if comparable > 0 else 0
    partial_rate = ((stats["match"] + stats["partial"]) / comparable * 100) if comparable > 0 else 0

    print(f"\n총 사례:        {stats['total']}건")
    print(f"테스트 가능:    {stats['testable']}건")
    print(f"계산 가능:      {stats['calculable']}건")
    print(f"비교 가능:      {comparable}건")
    print(f"─────────────────────────────")
    print(f"✅ 일치(MATCH):  {stats['match']}건 ({match_rate:.1f}%)")
    print(f"⚠️ 부분(PARTIAL): {stats['partial']}건")
    print(f"❌ 불일치(MISMATCH): {stats['mismatch']}건")
    print(f"⏭️ 스킵:         {stats['skip']}건")
    print(f"💥 에러:         {stats['error']}건")
    if comparable > 0:
        print(f"\n정확도(완전일치): {match_rate:.1f}%")
        print(f"정확도(부분포함): {partial_rate:.1f}%")

    if stats["by_type"]:
        print(f"\n📈 유형별 결과:")
        print(f"{'유형':15s} {'전체':>5s} {'일치':>5s} {'부분':>5s} {'불일치':>5s} {'스킵':>5s}")
        print(f"{'─'*50}")
        for t, s in sorted(stats["by_type"].items(), key=lambda x: x[1]["total"], reverse=True):
            print(f"{t:15s} {s['total']:5d} {s['match']:5d} {s['partial']:5d} {s['mismatch']:5d} {s['skip']:5d}")

    # MISMATCH 상세
    mismatches = [r for r in results if r.get("comparison", {}).get("verdict") in ("MISMATCH", "PARTIAL")]
    if mismatches:
        print(f"\n🔍 불일치/부분일치 상세 ({len(mismatches)}건):")
        for r in mismatches[:30]:
            comp = r["comparison"]
            calc_type = r.get("unified_extraction", {}).get("calculation_type", "?")
            print(f"\n  case_{r['case_id']:03d} [{calc_type}]: {r['title'][:50]}")
            for m in comp.get("mismatches", []):
                print(f"    ❌ {m['item']}: 계산기={m.get('calculator', '?')} vs 정답={m.get('answer', '?')} (차이 {m.get('diff_pct', '?')}%)")
            for m in comp.get("matches", []):
                print(f"    ✅ {m['item']}: {m.get('calculator', '?')}")

    # JSON 저장
    report = {
        "benchmark_date": date.today().isoformat(),
        "mode": "unified",
        "model": MODEL,
        "stats": stats,
        "match_rate_pct": round(match_rate, 1),
        "partial_rate_pct": round(partial_rate, 1),
        "comparable_count": comparable,
        "results": results,
    }
    UNIFIED_RESULTS_FILE.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n💾 상세 결과 저장: {UNIFIED_RESULTS_FILE}")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="법원판례 vs 계산기 벤치마크")
    parser.add_argument("--limit", type=int, help="처리할 사례 수 제한")
    parser.add_argument("--dry-run", action="store_true", help="API 호출 없이 파일 목록만")
    parser.add_argument("--skip-extraction", action="store_true", help="기존 추출 파일 사용")
    parser.add_argument("--unified", action="store_true", help="통합 모드 (질문+답변 전체 분석)")
    args = parser.parse_args()

    print(f"📁 사례 디렉토리: {CASE_DIR}")
    cases = load_all_cases(limit=args.limit)
    print(f"📄 로드된 사례: {len(cases)}건")

    if not cases:
        print("❌ 사례 파일이 없습니다.")
        return

    if args.unified:
        run_unified_benchmark(cases, skip_extraction=args.skip_extraction, dry_run=args.dry_run)
    else:
        run_benchmark(cases, skip_extraction=args.skip_extraction, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
