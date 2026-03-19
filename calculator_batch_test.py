#!/usr/bin/env python3
"""
임금계산기 배치 테스트 v3

analysis_qna.jsonl에서 500건 층화 샘플링하여
19개 계산기 모듈을 실제 Q&A 게시글 데이터로 테스트합니다.

기존 compare_calculator.py (v2, 100건/8유형)의 확장 버전:
- 500건 샘플링 (v2: 100건)
- 13개 계산 유형 (v2: 8개) — 퇴직금/실업급여/육아휴직 등 추가
- WageInput 추출 개선 (퇴직금/실업급여/육아휴직 전용 필드)
- 비교불가 원인 세분화
- JSON + MD + 콘솔 3종 보고서

결과:
  ✅ 일치   — 수치 오차 ±5% 이내 또는 판정 일치
  ⚠️ 근접   — 오차 5~20% 이내 (해석 차이 가능)
  ❌ 불일치  — 오차 20% 초과 또는 판정 반대
  ⏭️ 비교불가 — 수치 추출 불가 또는 계산기 오류
"""

import json
import os
import re
import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(__file__))

# ── 기존 compare_calculator.py에서 추출 함수 import ──────────────────────────
from compare_calculator import (
    extract_base_wage,
    extract_schedule,
    extract_allowances,
    extract_post_year,
    extract_answer_info,
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
from wage_calculator import (
    WageCalculator, WageInput, WageType, WorkType, BusinessSize, WorkSchedule,
)
from wage_calculator.facade import CALC_TYPE_MAP

# ── 설정 ─────────────────────────────────────────────────────────────────────

RANDOM_SEED = 42
random.seed(RANDOM_SEED)

STRATA_TARGET_500 = {
    "연차수당":     100,
    "퇴직금":       100,
    "연장수당":      80,
    "주휴수당":      60,
    "최저임금":      50,
    "해고예고수당":   30,
    "실업급여":      25,
    "육아휴직급여":   20,
    "통상임금":      15,
    "임금계산":       8,
    "일할계산":       5,
    "휴업수당":       5,
    "휴일근로수당":    2,
}
TOTAL_TARGET = sum(STRATA_TARGET_500.values())  # 500

# ── 계산 유형 정규화 ─────────────────────────────────────────────────────────

_CALC_TYPE_NORMALIZE = {
    "통상시급":         "통상임금",
    "연장수당/야간수당": "연장수당",
    "임금":            "임금계산",
    "육아휴직":         "육아휴직급여",
    "휴일근로수당":     "휴일근로수당",
}


def normalize_calc_type(ct: str) -> str:
    return _CALC_TYPE_NORMALIZE.get(ct, ct)


# ── 데이터 로딩 & 필터링 ─────────────────────────────────────────────────────

def load_metadata() -> dict[str, list[dict]]:
    """analysis_qna.jsonl에서 메타데이터만 로딩 (파일 본문은 나중에 lazy load)"""
    by_type: dict[str, list[dict]] = defaultdict(list)

    with open("analysis_qna.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if not r.get("requires_calculation"):
                continue
            ct = normalize_calc_type(r.get("calculation_type", ""))
            if ct not in STRATA_TARGET_500:
                continue
            fpath = f"output_qna/{r['filename']}"
            if not os.path.exists(fpath):
                continue
            r["_filepath"] = fpath
            by_type[ct].append(r)

    return by_type


def stratified_sample(by_type: dict[str, list[dict]]) -> list[dict]:
    """계산 유형별 층화 샘플링"""
    sampled = []
    for ct, target_n in STRATA_TARGET_500.items():
        pool = by_type.get(ct, [])
        n = min(target_n, len(pool))
        if n > 0:
            sampled.extend(random.sample(pool, n))
    random.shuffle(sampled)
    return sampled


def load_texts(samples: list[dict]):
    """샘플링된 레코드의 마크다운 파일만 로드 (lazy)"""
    for r in samples:
        with open(r["_filepath"], encoding="utf-8") as f:
            r["_text"] = f.read()


# ── WageInput 추출 v3 ────────────────────────────────────────────────────────

def _guess_start_date(period_str: str) -> str | None:
    """'2년', '1년 6개월', '입사: 2020-01-01' 등에서 시작일 추정"""
    today = date.today()

    # 패턴 1: 명시적 날짜 "YYYY-MM-DD" 또는 "YYYY.MM.DD"
    m = re.search(r"(\d{4})[-.년/]\s*(\d{1,2})[-.월/]\s*(\d{1,2})", period_str)
    if m:
        try:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        except ValueError:
            pass

    # 패턴 2: "N년 N개월"
    years = re.search(r"(\d+)\s*년", period_str)
    months = re.search(r"(\d+)\s*개월", period_str)
    total_days = 0
    if years:
        total_days += int(years.group(1)) * 365
    if months:
        total_days += int(months.group(1)) * 30
    if total_days > 0:
        return (today - timedelta(days=total_days)).isoformat()

    return None


def _extract_service_period(info: dict, text: str) -> tuple[str | None, str | None]:
    """(start_date, end_date) 추출 — 퇴직금/연차/실업급여용"""
    period = info.get("근무기간") or ""

    # 날짜 범위: "입사: 2020-01-01, 퇴사: 2024-12-31" 또는 "2020.5.18~2021.8.31"
    m = re.search(
        r"(\d{4})[-.년/]\s*(\d{1,2})[-.월/]\s*(\d{1,2}).*?"
        r"[~\-,→].*?"
        r"(\d{4})[-.년/]\s*(\d{1,2})[-.월/]\s*(\d{1,2})",
        period,
    )
    if m:
        start = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        end = f"{m.group(4)}-{int(m.group(5)):02d}-{int(m.group(6)):02d}"
        return start, end

    # "N년 N개월" 패턴
    start = _guess_start_date(period)
    if start:
        return start, None

    # 텍스트에서 직접 추출 시도
    q = _q_section(text)
    m2 = re.search(
        r"입사[일:]?\s*(\d{4})[-.년]\s*(\d{1,2})[-.월]\s*(\d{1,2})", q
    )
    if m2:
        start = f"{m2.group(1)}-{int(m2.group(2)):02d}-{int(m2.group(3)):02d}"
        m3 = re.search(
            r"퇴[사직][일:]?\s*(\d{4})[-.년]\s*(\d{1,2})[-.월]\s*(\d{1,2})", q
        )
        end = None
        if m3:
            end = f"{m3.group(1)}-{int(m3.group(2)):02d}-{int(m3.group(3)):02d}"
        return start, end

    return None, None


def _period_to_months(period_str: str) -> int:
    """근무기간 문자열 → 개월 수 변환"""
    total = 0
    years = re.search(r"(\d+)\s*년", period_str)
    months = re.search(r"(\d+)\s*개월", period_str)
    if years:
        total += int(years.group(1)) * 12
    if months:
        total += int(months.group(1))
    return total


def _extract_unemployment_fields(info: dict, text: str) -> dict:
    """실업급여 전용 필드 추출"""
    fields = {}
    q = _q_section(text)

    # 나이
    for pat in [r"만\s*(\d{2})\s*세", r"(\d{2})\s*살"]:
        m = re.search(pat, q)
        if m:
            age = int(m.group(1))
            if 18 <= age <= 75:
                fields["age"] = age
                break

    # 피보험기간
    period = info.get("근무기간") or ""
    months = _period_to_months(period)
    if months > 0:
        fields["insurance_months"] = months

    # 이직사유
    quit_reason = info.get("퇴직사유") or ""
    involuntary_keywords = ["해고", "권고사직", "계약만료", "폐업", "도산", "경영악화"]
    fields["is_involuntary_quit"] = any(k in quit_reason for k in involuntary_keywords)
    if not fields["is_involuntary_quit"]:
        fields["is_involuntary_quit"] = bool(re.search(
            r"해고|권고\s*사직|계약\s*만료|폐업|도산|경영\s*악화", q))

    return fields


def _extract_parental_fields(text: str) -> dict:
    """육아휴직 전용 필드 추출"""
    fields = {}
    q = _q_section(text)

    m = re.search(r"육아\s*휴직\s*(\d+)\s*개월", q)
    if m:
        fields["parental_leave_months"] = min(int(m.group(1)), 18)
    else:
        fields["parental_leave_months"] = 12

    fields["is_second_parent"] = bool(re.search(r"아빠|두\s*번째|배우자", q))
    return fields


def build_wage_input_v3(
    text: str,
    provided_info: dict,
    calc_type: str,
) -> WageInput | None:
    """
    WageInput 생성 v3 — 퇴직금/실업급여/육아휴직 전용 필드 포함.
    기존 compare_calculator.py의 로직 + 확장.
    """
    p_info = provided_info or {}

    # ── 1. 임금 추출 ──────────────────────────────────────────────────────────
    wage_data = None

    p_type = p_info.get("임금형태") or ""
    p_amt_str = str(p_info.get("임금액") or "")

    if p_amt_str:
        wt_candidate = WAGE_TYPE_MAP.get(p_type, WageType.MONTHLY)

        # 시급 패턴 우선
        if wt_candidate == WageType.HOURLY:
            m_h = re.search(r"시급\s*([\d,]+)\s*원?", p_amt_str)
            if m_h:
                try:
                    v = float(m_h.group(1).replace(",", ""))
                    if 5000 <= v <= 100000:
                        wage_data = ("시급", v)
                except ValueError:
                    pass

        if wage_data is None:
            if "연봉" in p_amt_str:
                wt_candidate = WageType.ANNUAL
            m = re.search(r"([\d,]{5,})", p_amt_str)
            if m:
                try:
                    v = float(m.group(1).replace(",", ""))
                    if v > 10000:
                        if wt_candidate == WageType.HOURLY and v > 100000:
                            wage_data = ("월급", v)
                        elif wt_candidate == WageType.ANNUAL:
                            wage_data = ("연봉", v)
                        elif wt_candidate == WageType.MONTHLY and v < 500_000:
                            pass
                        else:
                            wage_data = (p_type or "월급", v)
                except ValueError:
                    pass

    if wage_data is None:
        result = extract_base_wage(text)
        if result:
            wage_data = result

    # 실업급여/육아휴직은 임금 없어도 일부 계산 가능 → 최저임금 기반 기본값
    if wage_data is None:
        if calc_type in ("실업급여", "육아휴직급여"):
            # 기본 월급 가정 (최저임금 기반)
            ref_year = extract_post_year(text)
            from wage_calculator.constants import MINIMUM_HOURLY_WAGE
            mw = MINIMUM_HOURLY_WAGE.get(ref_year, 9860)
            wage_data = ("월급", mw * 209)
        else:
            return None

    wage_type_key, amount = wage_data
    wage_type = WAGE_TYPE_MAP.get(wage_type_key, WageType.MONTHLY)

    # ── 2. 스케줄 추출 ────────────────────────────────────────────────────────
    sched_data = extract_schedule(text)

    ot_h = _parse_h(p_info.get("연장근로시간") or p_info.get("주연장시간") or "") or sched_data.get("ot_h", 0)
    night_h = _parse_h(p_info.get("야간근로시간") or "") or sched_data.get("night_h", 0)
    daily_h = _parse_h(p_info.get("일일근로시간") or p_info.get("소정근로시간") or "") or sched_data.get("daily_h", 8.0)
    work_days = _parse_h(p_info.get("주근무일수") or "") or sched_data.get("weekly_days", 5.0)

    # ── 3. 사업장 규모 ────────────────────────────────────────────────────────
    biz_under5 = sched_data.get("biz_under5")
    size_str = str(p_info.get("사업장규모") or "")
    if biz_under5 is None:
        biz_under5 = "5인 미만" in size_str or "5인미만" in size_str
    biz_size = BusinessSize.UNDER_5 if biz_under5 else BusinessSize.OVER_5

    # ── 4. 근무형태 ──────────────────────────────────────────────────────────
    근무형태 = p_info.get("근무형태") or ""
    work_type = WorkType.REGULAR
    for k, v in {
        "4조2교대": WorkType.SHIFT_4_2, "3조2교대": WorkType.SHIFT_3_2,
        "3교대": WorkType.SHIFT_3, "2교대": WorkType.SHIFT_2,
    }.items():
        if k in 근무형태:
            work_type = v
            break

    # ── 5. WorkSchedule ──────────────────────────────────────────────────────
    weekly_h = daily_h * work_days
    monthly_scheduled = None
    if weekly_h < 40:
        monthly_scheduled = round((weekly_h + weekly_h / 40 * 8) * 365 / 12 / 7, 2)

    schedule = WorkSchedule(
        daily_work_hours=daily_h,
        weekly_work_days=work_days,
        weekly_overtime_hours=ot_h,
        weekly_night_hours=night_h,
        monthly_scheduled_hours=monthly_scheduled,
    )

    # ── 6. 고정수당 ──────────────────────────────────────────────────────────
    allowances = extract_allowances(text)

    ref_year = extract_post_year(text)

    inp = WageInput(
        wage_type=wage_type,
        business_size=biz_size,
        work_type=work_type,
        reference_year=ref_year,
        schedule=schedule,
        fixed_allowances=allowances,
    )

    if wage_type == WageType.HOURLY:
        inp.hourly_wage = amount
    elif wage_type == WageType.DAILY:
        inp.daily_wage = amount
    elif wage_type in (WageType.MONTHLY, WageType.COMPREHENSIVE):
        inp.monthly_wage = amount
    elif wage_type == WageType.ANNUAL:
        inp.annual_wage = amount

    # ── 7. 유형별 추가 필드 ──────────────────────────────────────────────────

    # 퇴직금 / 연차 — 근무기간 추출
    if calc_type in ("퇴직금", "연차수당", "해고예고수당"):
        start, end = _extract_service_period(p_info, text)
        if start:
            inp.start_date = start
        if end:
            inp.end_date = end
        elif calc_type == "퇴직금" and not start:
            # 근무기간 없으면 퇴직금 계산 불가 → 1년 기본값
            inp.start_date = (date.today() - timedelta(days=365)).isoformat()

    # 해고예고
    if calc_type == "해고예고수당":
        notice = _parse_h(p_info.get("예고일수") or "")
        inp.notice_days_given = int(notice) if notice else 0
        inp.dismissal_date = date.today().isoformat()
        if not inp.start_date:
            inp.start_date = (date.today() - timedelta(days=365)).isoformat()

    # 실업급여
    if calc_type == "실업급여":
        uf = _extract_unemployment_fields(p_info, text)
        if uf.get("age"):
            inp.age = uf["age"]
        else:
            inp.age = 35  # 기본값
        if uf.get("insurance_months"):
            inp.insurance_months = uf["insurance_months"]
        inp.is_involuntary_quit = uf.get("is_involuntary_quit", True)
        start, end = _extract_service_period(p_info, text)
        if start:
            inp.start_date = start
        if end:
            inp.end_date = end

    # 육아휴직
    if calc_type == "육아휴직급여":
        pf = _extract_parental_fields(text)
        inp.parental_leave_months = pf.get("parental_leave_months", 12)
        inp.is_second_parent = pf.get("is_second_parent", False)

    # 휴업수당
    if calc_type == "휴업수당":
        inp.shutdown_days = 30  # 기본 1개월

    return inp


# ── 계산기 타겟 매핑 ─────────────────────────────────────────────────────────

def get_targets_v3(calc_type: str) -> list[str]:
    """CALC_TYPE_MAP 활용 + 추가 매핑"""
    # 정규화된 calc_type을 CALC_TYPE_MAP 키에 매핑
    targets = CALC_TYPE_MAP.get(calc_type)
    if targets:
        return targets

    # 추가 매핑
    extra = {
        "휴일근로수당": ["overtime", "minimum_wage"],
        "임금계산":     ["overtime", "minimum_wage", "weekly_holiday"],
    }
    return extra.get(calc_type, ["minimum_wage"])


# ── 비교 로직 v3 ─────────────────────────────────────────────────────────────

def _compare_overtime(post_id, calc_type, result, extracted) -> CompareResult:
    """연장수당 / 임금계산 비교"""
    ot_summary = result.summary.get("연장/야간/휴일수당(월)")
    calc_ot = _parse_summary_num(ot_summary)
    calc_total = result.monthly_total
    calc_val = f"연장수당 {calc_ot:,.0f}원 / 월계 {calc_total:,.0f}원"

    if extracted["hourly"] and result.ordinary_hourly:
        ans_h = extracted["hourly"]
        ratio = ans_h / result.ordinary_hourly
        v, r = _ratio_verdict(ratio, ans_h, result.ordinary_hourly)
        return CompareResult(post_id=post_id, calc_type=calc_type,
            verdict=v, reason=f"통상시급 비교: {r}",
            calc_value=f"통상시급 {result.ordinary_hourly:,.0f}원",
            answer_value=f"시급 {ans_h:,.0f}원", wage_input_ok=True)

    amounts = extracted["amounts"]
    key_amounts = extracted.get("key_amounts", [])
    if not amounts:
        return CompareResult(post_id=post_id, calc_type=calc_type,
            verdict="⏭️", reason="답변에 금액 없음",
            calc_value=calc_val, answer_value="-", wage_input_ok=True)

    target = calc_ot if calc_ot else calc_total
    pool = key_amounts if key_amounts else amounts
    best = _closest(pool, target)

    if target >= 100_000 and best < 50_000:
        return CompareResult(post_id=post_id, calc_type=calc_type,
            verdict="⏭️", reason="단위 불일치 의심",
            calc_value=calc_val, answer_value=f"{best:,.0f}원", wage_input_ok=True)

    ratio = best / target if target else 0
    v, r = _ratio_verdict(ratio, best, target)
    return CompareResult(post_id=post_id, calc_type=calc_type,
        verdict=v, reason=r,
        calc_value=calc_val, answer_value=f"{best:,.0f}원", wage_input_ok=True)


def _compare_minimum_wage(post_id, calc_type, result, extracted) -> CompareResult:
    """최저임금 / 통상임금 비교"""
    calc_ok = result.minimum_wage_ok
    calc_hourly = result.ordinary_hourly
    calc_val = f"{'충족' if calc_ok else '미달'} (시급 {calc_hourly:,.0f}원)"

    if extracted["hourly"]:
        ans_h = extracted["hourly"]
        ratio = ans_h / calc_hourly if calc_hourly else 0
        v, r = _ratio_verdict(ratio, ans_h, calc_hourly)
        return CompareResult(post_id=post_id, calc_type=calc_type,
            verdict=v, reason=f"통상시급 비교: {r}",
            calc_value=calc_val, answer_value=f"시급 {ans_h:,.0f}원", wage_input_ok=True)

    if extracted["compliant"] is not None:
        match = (extracted["compliant"] == calc_ok)
        v = "✅" if match else "❌"
        r = f"최저임금 판정 {'일치' if match else '불일치'}"
        return CompareResult(post_id=post_id, calc_type=calc_type,
            verdict=v, reason=r,
            calc_value=calc_val,
            answer_value="충족" if extracted["compliant"] else "미달",
            wage_input_ok=True)

    amounts = extracted["amounts"]
    if amounts:
        best = _closest(amounts, calc_hourly)
        if 5000 <= best <= 100000:
            ratio = best / calc_hourly if calc_hourly else 0
            v, r = _ratio_verdict(ratio, best, calc_hourly)
            return CompareResult(post_id=post_id, calc_type=calc_type,
                verdict=v, reason=f"금액 비교: {r}",
                calc_value=calc_val, answer_value=f"{best:,.0f}원", wage_input_ok=True)

    return CompareResult(post_id=post_id, calc_type=calc_type,
        verdict="⏭️", reason="답변에 비교 가능한 수치 없음",
        calc_value=calc_val, answer_value="-", wage_input_ok=True)


def _compare_weekly_holiday(post_id, calc_type, result, extracted) -> CompareResult:
    """주휴수당 비교"""
    wh_summary = result.summary.get("주휴수당(월)")
    calc_num = _parse_summary_num(wh_summary) if wh_summary else result.monthly_total
    calc_val = f"주휴수당 {calc_num:,.0f}원/월"

    amounts = extracted["amounts"]
    key_amounts = extracted.get("key_amounts", [])
    if not amounts:
        return CompareResult(post_id=post_id, calc_type=calc_type,
            verdict="⏭️", reason="답변에 금액 없음",
            calc_value=calc_val, answer_value="-", wage_input_ok=True)

    best = _closest(key_amounts or amounts, calc_num)
    if calc_num >= 100_000 and best < 50_000:
        return CompareResult(post_id=post_id, calc_type=calc_type,
            verdict="⏭️", reason="단위 불일치 의심",
            calc_value=calc_val, answer_value=f"{best:,.0f}원", wage_input_ok=True)

    ratio = best / calc_num if calc_num else 0
    v, r = _ratio_verdict(ratio, best, calc_num)
    return CompareResult(post_id=post_id, calc_type=calc_type,
        verdict=v, reason=r,
        calc_value=calc_val, answer_value=f"{best:,.0f}원", wage_input_ok=True)


def _compare_annual_leave(post_id, calc_type, result, extracted) -> CompareResult:
    """연차수당 비교"""
    leave_pay = result.summary.get("연차수당")
    leave_days_calc = result.summary.get("미사용 연차")
    calc_val = f"연차수당 {leave_pay}" if leave_pay else "-"
    calc_num = _parse_summary_num(leave_pay) if leave_pay else None

    if extracted["leave_days"] and leave_days_calc:
        calc_days = _parse_summary_num(leave_days_calc)
        ans_days = extracted["leave_days"]
        diff = abs(calc_days - ans_days)
        v = "✅" if diff <= 1 else ("⚠️" if diff <= 3 else "❌")
        r = f"연차일수 비교: {calc_days:.0f}일 vs {ans_days:.0f}일 (차이 {diff:.0f}일)"
        return CompareResult(post_id=post_id, calc_type=calc_type,
            verdict=v, reason=r,
            calc_value=calc_val, answer_value=f"{ans_days:.0f}일", wage_input_ok=True)

    amounts = extracted["amounts"]
    key_amounts = extracted.get("key_amounts", [])
    if amounts and calc_num:
        best = _closest(key_amounts or amounts, calc_num)
        ratio = best / calc_num if calc_num else 0
        v, r = _ratio_verdict(ratio, best, calc_num)
        return CompareResult(post_id=post_id, calc_type=calc_type,
            verdict=v, reason=r,
            calc_value=calc_val, answer_value=f"{best:,.0f}원", wage_input_ok=True)

    return CompareResult(post_id=post_id, calc_type=calc_type,
        verdict="⏭️", reason="비교 가능한 수치 없음",
        calc_value=calc_val, answer_value="-", wage_input_ok=True)


def _compare_dismissal(post_id, calc_type, result, extracted) -> CompareResult:
    """해고예고수당 비교"""
    ds_pay = result.summary.get("해고예고수당")
    calc_num = _parse_summary_num(ds_pay) if ds_pay else None
    calc_val = f"해고예고수당 {ds_pay}" if ds_pay else "-"

    amounts = extracted["amounts"]
    key_amounts = extracted.get("key_amounts", [])
    if not amounts or not calc_num:
        return CompareResult(post_id=post_id, calc_type=calc_type,
            verdict="⏭️", reason="비교 가능한 수치 없음",
            calc_value=calc_val, answer_value="-", wage_input_ok=True)

    best = _closest(key_amounts or amounts, calc_num)
    ratio = best / calc_num if calc_num else 0
    v, r = _ratio_verdict(ratio, best, calc_num)
    return CompareResult(post_id=post_id, calc_type=calc_type,
        verdict=v, reason=r,
        calc_value=calc_val, answer_value=f"{best:,.0f}원", wage_input_ok=True)


def _compare_prorated(post_id, calc_type, result, extracted) -> CompareResult:
    """일할계산 비교"""
    pr_pay = result.summary.get("일할계산 임금")
    calc_num = _parse_summary_num(pr_pay) if pr_pay else None
    calc_val = f"일할계산 {pr_pay}" if pr_pay else "-"

    amounts = extracted["amounts"]
    key_amounts = extracted.get("key_amounts", [])
    if not amounts or not calc_num:
        return CompareResult(post_id=post_id, calc_type=calc_type,
            verdict="⏭️", reason="비교 가능한 수치 없음",
            calc_value=calc_val, answer_value="-", wage_input_ok=True)

    best = _closest(key_amounts or amounts, calc_num)
    ratio = best / calc_num if calc_num else 0
    v, r = _ratio_verdict(ratio, best, calc_num)
    return CompareResult(post_id=post_id, calc_type=calc_type,
        verdict=v, reason=r,
        calc_value=calc_val, answer_value=f"{best:,.0f}원", wage_input_ok=True)


def _compare_severance(post_id, calc_type, result, extracted) -> CompareResult:
    """퇴직금 비교"""
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
    if calc_num >= 500_000 and best < 100_000:
        return CompareResult(post_id=post_id, calc_type=calc_type,
            verdict="⏭️", reason="단위 불일치 (퇴직금 vs 소액)",
            calc_value=calc_val, answer_value=f"{best:,.0f}원", wage_input_ok=True)

    ratio = best / calc_num if calc_num else 0
    v, r = _ratio_verdict(ratio, best, calc_num)
    return CompareResult(post_id=post_id, calc_type=calc_type,
        verdict=v, reason=r,
        calc_value=calc_val, answer_value=f"{best:,.0f}원", wage_input_ok=True)


def _compare_unemployment(post_id, calc_type, result, extracted) -> CompareResult:
    """실업급여 비교"""
    daily_str = result.summary.get("구직급여 일액")
    total_str = result.summary.get("총 구직급여")
    ineligible = result.summary.get("실업급여 수급")

    if ineligible:
        calc_val = ineligible
        answer_preview = extracted.get("answer_preview", "")
        if re.search(r"수급.*불가|실업급여.*불가|자격.*없", answer_preview):
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

    pool = key_amounts or amounts
    best_daily = _closest(pool, calc_daily) if calc_daily else 0

    if calc_daily and best_daily and 30_000 <= best_daily <= 80_000:
        ratio = best_daily / calc_daily
        v, r = _ratio_verdict(ratio, best_daily, calc_daily)
        return CompareResult(post_id=post_id, calc_type=calc_type,
            verdict=v, reason=f"구직급여 일액 비교: {r}",
            calc_value=calc_val, answer_value=f"{best_daily:,.0f}원", wage_input_ok=True)

    best_total = _closest(pool, calc_total) if calc_total else 0
    if calc_total and best_total:
        ratio = best_total / calc_total
        v, r = _ratio_verdict(ratio, best_total, calc_total)
        return CompareResult(post_id=post_id, calc_type=calc_type,
            verdict=v, reason=f"총 구직급여 비교: {r}",
            calc_value=calc_val, answer_value=f"{best_total:,.0f}원", wage_input_ok=True)

    return CompareResult(post_id=post_id, calc_type=calc_type,
        verdict="⏭️", reason="비교 가능한 수치 부재",
        calc_value=calc_val, answer_value="-", wage_input_ok=True)


def _compare_parental_leave(post_id, calc_type, result, extracted) -> CompareResult:
    """육아휴직 비교"""
    monthly_str = result.summary.get("육아휴직 월 수령액")
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


def _compare_shutdown(post_id, calc_type, result, extracted) -> CompareResult:
    """휴업수당 비교"""
    sd_str = result.summary.get("휴업수당")
    calc_num = _parse_summary_num(sd_str) if sd_str else None
    calc_val = f"휴업수당 {sd_str}" if sd_str else "-"

    amounts = extracted["amounts"]
    key_amounts = extracted.get("key_amounts", [])

    if not amounts or not calc_num:
        return CompareResult(post_id=post_id, calc_type=calc_type,
            verdict="⏭️", reason="비교 가능한 수치 없음",
            calc_value=calc_val, answer_value="-", wage_input_ok=True)

    best = _closest(key_amounts or amounts, calc_num)
    ratio = best / calc_num if calc_num else 0
    v, r = _ratio_verdict(ratio, best, calc_num)
    return CompareResult(post_id=post_id, calc_type=calc_type,
        verdict=v, reason=r,
        calc_value=calc_val, answer_value=f"{best:,.0f}원", wage_input_ok=True)


def _compare_generic(post_id, calc_type, result, extracted) -> CompareResult:
    """기타 유형 — 범용 비교"""
    calc_val = f"월계 {result.monthly_total:,.0f}원"
    amounts = extracted["amounts"]
    key_amounts = extracted.get("key_amounts", [])

    if not amounts:
        return CompareResult(post_id=post_id, calc_type=calc_type,
            verdict="⏭️", reason="답변에 금액 없음",
            calc_value=calc_val, answer_value="-", wage_input_ok=True)

    best = _closest(key_amounts or amounts, result.monthly_total)
    ratio = best / result.monthly_total if result.monthly_total else 0
    v, r = _ratio_verdict(ratio, best, result.monthly_total)
    return CompareResult(post_id=post_id, calc_type=calc_type,
        verdict=v, reason=r,
        calc_value=calc_val, answer_value=f"{best:,.0f}원", wage_input_ok=True)


_COMPARATORS = {
    "퇴직금":       _compare_severance,
    "실업급여":     _compare_unemployment,
    "육아휴직급여": _compare_parental_leave,
    "연장수당":     _compare_overtime,
    "최저임금":     _compare_minimum_wage,
    "통상임금":     _compare_minimum_wage,
    "주휴수당":     _compare_weekly_holiday,
    "연차수당":     _compare_annual_leave,
    "해고예고수당": _compare_dismissal,
    "임금계산":     _compare_overtime,
    "일할계산":     _compare_prorated,
    "휴업수당":     _compare_shutdown,
    "휴일근로수당": _compare_overtime,
}


def compare_v3(record: dict, text: str, result, calc_type: str) -> CompareResult:
    """유형별 비교 디스패처"""
    post_id = record["file_id"]
    extracted = extract_answer_info(text, calc_type)
    fn = _COMPARATORS.get(calc_type, _compare_generic)
    return fn(post_id, calc_type, result, extracted)


# ── 배치 실행 ─────────────────────────────────────────────────────────────────

def run_batch(samples: list[dict]) -> list[CompareResult]:
    calc = WageCalculator()
    results = []
    errors_by_reason = Counter()

    print(f"\n배치 테스트 실행 중 ({len(samples)}건)", end="", flush=True)
    for i, record in enumerate(samples):
        text = record["_text"]
        info = record.get("provided_info", {}) or {}
        calc_type = normalize_calc_type(record.get("calculation_type", ""))

        # 1. WageInput 생성
        inp = build_wage_input_v3(text, info, calc_type)
        if inp is None:
            cr = CompareResult(
                post_id=record["file_id"], calc_type=calc_type,
                verdict="⏭️", reason="WageInput 생성 불가",
                calc_value="-", answer_value="-", wage_input_ok=False)
            results.append(cr)
            errors_by_reason["입력 추출 실패"] += 1
            continue

        # 2. 타겟 결정
        targets = get_targets_v3(calc_type)

        # 3. 계산 실행
        try:
            wage_result = calc.calculate(inp, targets=targets)
        except Exception as e:
            cr = CompareResult(
                post_id=record["file_id"], calc_type=calc_type,
                verdict="⏭️", reason=f"계산기 오류: {type(e).__name__}: {str(e)[:80]}",
                calc_value="-", answer_value="-", wage_input_ok=True)
            results.append(cr)
            errors_by_reason["계산기 오류"] += 1
            continue

        # 4. 비교
        cr = compare_v3(record, text, wage_result, calc_type)
        results.append(cr)

        if (i + 1) % 50 == 0:
            print(f" {i+1}", end="", flush=True)

    print(" 완료\n")
    return results


# ── 보고서: 콘솔 ─────────────────────────────────────────────────────────────

def print_console_report(results: list[CompareResult]):
    print("=" * 72)
    print("📊 임금계산기 배치 테스트 보고서 v3")
    print("=" * 72)

    vc = Counter(r.verdict for r in results)
    total = len(results)

    print(f"\n총 테스트 건수: {total}건")
    print(f"계산 유형 수: {len(set(r.calc_type for r in results))}개\n")

    for v, label in [("✅", "일치"), ("⚠️", "근접"), ("❌", "불일치"), ("⏭️", "비교불가")]:
        cnt = vc.get(v, 0)
        pct = cnt / total * 100 if total else 0
        bar = "█" * int(pct / 2)
        print(f"  {v} {label:5s}: {cnt:3d}건 ({pct:5.1f}%) {bar}")

    comparable = [r for r in results if r.verdict != "⏭️"]
    if comparable:
        ok = sum(1 for r in comparable if r.verdict in ("✅", "⚠️"))
        ok_strict = sum(1 for r in comparable if r.verdict == "✅")
        skip_pct = (total - len(comparable)) / total * 100
        print(f"\n  비교불가율: {skip_pct:.1f}% ({total - len(comparable)}/{total})")
        print(f"  비교가능 {len(comparable)}건 기준:")
        print(f"    ✅+⚠️ (±20% 이내): {ok}/{len(comparable)} = {ok/len(comparable)*100:.1f}%")
        print(f"    ✅    (±5% 이내):  {ok_strict}/{len(comparable)} = {ok_strict/len(comparable)*100:.1f}%")

    # 유형별 결과
    print("\n── 계산 유형별 결과 ──")
    by_type: dict[str, list[CompareResult]] = defaultdict(list)
    for r in results:
        by_type[r.calc_type].append(r)

    for ct in STRATA_TARGET_500:
        recs = by_type.get(ct, [])
        if not recs:
            continue
        sub_vc = Counter(r.verdict for r in recs)
        comparable_ct = [r for r in recs if r.verdict != "⏭️"]
        ok_ct = sum(1 for r in comparable_ct if r.verdict in ("✅", "⚠️"))
        acc = f"{ok_ct}/{len(comparable_ct)}={ok_ct/len(comparable_ct)*100:.0f}%" if comparable_ct else "-"
        print(f"\n  [{ct}] {len(recs)}건 | 비교가능 정확도: {acc}")
        for v, label in [("✅", "일치"), ("⚠️", "근접"), ("❌", "불일치"), ("⏭️", "비교불가")]:
            cnt = sub_vc.get(v, 0)
            if cnt:
                print(f"    {v} {label}: {cnt}건")

    # 불일치 상세
    errors = [r for r in results if r.verdict == "❌"]
    if errors:
        print(f"\n── ❌ 불일치 케이스 ({len(errors)}건) ──")
        for r in errors[:20]:
            print(f"  [{r.calc_type}] {r.post_id}: {r.reason}")

    # 비교불가 원인
    na_reasons = Counter(r.reason for r in results if r.verdict == "⏭️")
    if na_reasons:
        print(f"\n── ⏭️ 비교불가 주요 원인 ({sum(na_reasons.values())}건) ──")
        for reason, cnt in na_reasons.most_common(10):
            print(f"  {cnt:3d}건: {reason[:70]}")


# ── 보고서: JSON ──────────────────────────────────────────────────────────────

def save_json(results: list[CompareResult]):
    vc = Counter(r.verdict for r in results)
    total = len(results)
    comparable = [r for r in results if r.verdict != "⏭️"]

    by_type_summary = {}
    by_type: dict[str, list[CompareResult]] = defaultdict(list)
    for r in results:
        by_type[r.calc_type].append(r)
    for ct, recs in by_type.items():
        sub_vc = Counter(r.verdict for r in recs)
        by_type_summary[ct] = {
            "total": len(recs),
            "match": sub_vc.get("✅", 0),
            "close": sub_vc.get("⚠️", 0),
            "mismatch": sub_vc.get("❌", 0),
            "skip": sub_vc.get("⏭️", 0),
        }

    # 비교불가 원인 분류
    error_analysis = Counter()
    for r in results:
        if r.verdict == "⏭️":
            if "WageInput 생성 불가" in r.reason:
                error_analysis["input_extraction_fail"] += 1
            elif "계산기 오류" in r.reason:
                error_analysis["calculator_error"] += 1
            elif "금액 없음" in r.reason or "수치 없음" in r.reason or "수치 부재" in r.reason:
                error_analysis["answer_no_numbers"] += 1
            elif "단위 불일치" in r.reason:
                error_analysis["unit_mismatch"] += 1
            else:
                error_analysis["other"] += 1

    ok = sum(1 for r in comparable if r.verdict in ("✅", "⚠️"))

    output = {
        "meta": {
            "version": "v3",
            "total_samples": total,
            "random_seed": RANDOM_SEED,
            "run_date": date.today().isoformat(),
            "calc_types_covered": len(by_type),
        },
        "summary": {
            "total": total,
            "match": vc.get("✅", 0),
            "close": vc.get("⚠️", 0),
            "mismatch": vc.get("❌", 0),
            "skip": vc.get("⏭️", 0),
            "comparable_count": len(comparable),
            "comparable_accuracy": f"{ok/len(comparable)*100:.1f}%" if comparable else "N/A",
        },
        "by_type": by_type_summary,
        "error_analysis": dict(error_analysis),
        "results": [
            {
                "post_id": r.post_id,
                "calc_type": r.calc_type,
                "verdict": r.verdict,
                "reason": r.reason,
                "calc_value": r.calc_value,
                "answer_value": r.answer_value,
                "wage_input_ok": r.wage_input_ok,
            }
            for r in results
        ],
    }

    with open("batch_test_results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("결과 저장: batch_test_results.json")


# ── 보고서: 마크다운 ─────────────────────────────────────────────────────────

def save_report_md(results: list[CompareResult]):
    vc = Counter(r.verdict for r in results)
    total = len(results)
    comparable = [r for r in results if r.verdict != "⏭️"]
    ok = sum(1 for r in comparable if r.verdict in ("✅", "⚠️"))
    ok_strict = sum(1 for r in comparable if r.verdict == "✅")

    lines = [
        "# 계산기 배치 테스트 보고서 v3",
        "",
        f"> 실행일: {date.today().isoformat()} | 시드: {RANDOM_SEED} | 총 {total}건",
        "",
        "## 1. 요약",
        "",
        f"| 지표 | 값 |",
        f"|------|-----|",
        f"| 총 테스트 건수 | {total}건 |",
        f"| 계산 유형 수 | {len(set(r.calc_type for r in results))}개 |",
        f"| 비교불가율 | {(total - len(comparable)) / total * 100:.1f}% |",
        f"| 비교가능 건수 | {len(comparable)}건 |",
        f"| ✅+⚠️ 정확도 (±20%) | {ok/len(comparable)*100:.1f}% |" if comparable else "| 정확도 | N/A |",
        f"| ✅ 정확도 (±5%) | {ok_strict/len(comparable)*100:.1f}% |" if comparable else "",
        "",
        "## 2. 전체 결과 분포",
        "",
        "| 판정 | 건수 | 비율 |",
        "|------|------|------|",
    ]

    for v, label in [("✅", "일치 (±5%)"), ("⚠️", "근접 (±20%)"), ("❌", "불일치 (>20%)"), ("⏭️", "비교불가")]:
        cnt = vc.get(v, 0)
        pct = cnt / total * 100 if total else 0
        lines.append(f"| {v} {label} | {cnt}건 | {pct:.1f}% |")

    lines.extend(["", "## 3. 계산 유형별 결과", ""])
    lines.append("| 유형 | 건수 | ✅ | ⚠️ | ❌ | ⏭️ | 비교가능 정확도 |")
    lines.append("|------|------|-----|-----|-----|-----|----------------|")

    by_type: dict[str, list[CompareResult]] = defaultdict(list)
    for r in results:
        by_type[r.calc_type].append(r)

    for ct in STRATA_TARGET_500:
        recs = by_type.get(ct, [])
        if not recs:
            continue
        sub_vc = Counter(r.verdict for r in recs)
        comp = [r for r in recs if r.verdict != "⏭️"]
        ok_ct = sum(1 for r in comp if r.verdict in ("✅", "⚠️"))
        acc = f"{ok_ct/len(comp)*100:.0f}%" if comp else "-"
        lines.append(
            f"| {ct} | {len(recs)} | {sub_vc.get('✅', 0)} | {sub_vc.get('⚠️', 0)} | "
            f"{sub_vc.get('❌', 0)} | {sub_vc.get('⏭️', 0)} | {acc} |"
        )

    # 비교불가 원인
    lines.extend(["", "## 4. 비교불가 원인 분석", ""])
    na_reasons = Counter(r.reason for r in results if r.verdict == "⏭️")
    lines.append("| 원인 | 건수 | 비율 |")
    lines.append("|------|------|------|")
    total_na = sum(na_reasons.values())
    for reason, cnt in na_reasons.most_common(15):
        pct = cnt / total_na * 100 if total_na else 0
        lines.append(f"| {reason[:60]} | {cnt} | {pct:.1f}% |")

    # 불일치 상세
    errors = [r for r in results if r.verdict == "❌"]
    if errors:
        lines.extend(["", f"## 5. 불일치 케이스 ({len(errors)}건)", ""])
        lines.append("| # | 유형 | 포스트 | 계산기 결과 | 답변 수치 | 비고 |")
        lines.append("|---|------|--------|-------------|-----------|------|")
        for i, r in enumerate(errors, 1):
            lines.append(
                f"| {i} | {r.calc_type} | {r.post_id} | "
                f"{r.calc_value[:30]} | {r.answer_value[:20]} | {r.reason[:40]} |"
            )

    # 개선 우선순위
    lines.extend(["", "## 6. 개선 우선순위", ""])
    lines.append("| 순위 | 유형 | 풀 크기 | 불일치 수 | 비교불가 수 | 우선도 |")
    lines.append("|------|------|---------|-----------|-------------|--------|")

    priority_list = []
    for ct, recs in by_type.items():
        mismatch = sum(1 for r in recs if r.verdict == "❌")
        skip = sum(1 for r in recs if r.verdict == "⏭️")
        priority = mismatch * 10 + skip
        priority_list.append((ct, len(recs), mismatch, skip, priority))
    priority_list.sort(key=lambda x: x[4], reverse=True)

    for i, (ct, n, mis, skip, pri) in enumerate(priority_list[:10], 1):
        lines.append(f"| {i} | {ct} | {n} | {mis} | {skip} | {pri} |")

    lines.extend([
        "",
        "## 7. 결론",
        "",
        f"- 총 {total}건 테스트, {len(set(r.calc_type for r in results))}개 유형 커버",
        f"- 비교가능 {len(comparable)}건 중 ✅+⚠️ {ok}건 ({ok/len(comparable)*100:.1f}%)" if comparable else "- 비교가능 건 없음",
        f"- 비교불가율: {(total - len(comparable)) / total * 100:.1f}%",
        f"- 불일치 {len(errors)}건 → 개별 원인 분석 필요",
    ])

    with open("batch_test_report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("보고서 저장: batch_test_report.md")


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    print("임금계산기 배치 테스트 v3 실행 중...")
    print(f"랜덤 시드: {RANDOM_SEED}, 목표: {TOTAL_TARGET}건")
    print("메타데이터 로딩 중...", flush=True)

    by_type = load_metadata()

    print("\n계산 유형별 가용 게시글:")
    total_avail = 0
    for ct, target in STRATA_TARGET_500.items():
        avail = len(by_type.get(ct, []))
        actual = min(target, avail)
        total_avail += actual
        status = "✅" if actual >= target else f"⚠️ 부족 ({avail}/{target})"
        print(f"  {ct:12s}: {avail:5d}건 풀 → {actual:3d}건 샘플링  {status}")

    samples = stratified_sample(by_type)
    print(f"\n총 샘플: {len(samples)}건 (목표: {TOTAL_TARGET}건)")

    print("샘플 마크다운 로딩 중...", flush=True)
    load_texts(samples)

    results = run_batch(samples)

    print_console_report(results)
    save_json(results)
    save_report_md(results)

    print(f"\n완료. 총 {len(results)}건 테스트, "
          f"✅ {sum(1 for r in results if r.verdict == '✅')}건, "
          f"⚠️ {sum(1 for r in results if r.verdict == '⚠️')}건, "
          f"❌ {sum(1 for r in results if r.verdict == '❌')}건, "
          f"⏭️ {sum(1 for r in results if r.verdict == '⏭️')}건")


if __name__ == "__main__":
    main()
