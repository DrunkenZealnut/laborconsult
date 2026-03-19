#!/usr/bin/env python3
"""
임금계산기 vs 실제 Q&A 답변 비교 스크립트 v2

계산 유형별 층화 샘플링 100건을 실행하여
calculator 결과와 게시글 답변을 비교합니다.

개선사항:
- provided_info.임금액 null 문제를 마크다운 직접 추출로 보완
- 근무 스케줄 정보도 질문 텍스트에서 추출
- 답변의 핵심 수치(통상시급, 수당 합계 등) 정밀 추출

결과:
  ✅ 일치   — 수치 오차 ±5% 이내 또는 판정 일치
  ⚠️ 근접   — 오차 5~20% 이내 (해석 차이 가능)
  ❌ 불일치  — 오차 20% 초과 또는 판정 반대
  ⏭️ 비교불가 — 답변에서 수치를 추출할 수 없음
"""

import json
import os
import re
import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(__file__))
from wage_calculator import WageCalculator, WageInput, WageType, WorkType, BusinessSize, WorkSchedule

RANDOM_SEED = 42
random.seed(RANDOM_SEED)

STRATA_TARGET = {
    "연장수당":    40,
    "최저임금":    30,
    "주휴수당":    12,
    "연차수당":     8,
    "해고예고수당":  5,
    "통상임금":     3,
    "임금계산":     1,
    "일할계산":     1,
}
TOTAL_TARGET = sum(STRATA_TARGET.values())  # 100

WAGE_TYPE_MAP = {
    "시급": WageType.HOURLY, "일급": WageType.DAILY,
    "월급": WageType.MONTHLY, "연봉": WageType.ANNUAL,
    "포괄임금": WageType.COMPREHENSIVE, "포괄임금제": WageType.COMPREHENSIVE,
    "최저임금": WageType.HOURLY,
}

# ── 마크다운에서 임금 정보 추출 ──────────────────────────────────────────────

def _q_section(text: str) -> str:
    """질문 섹션만 추출"""
    m = re.search(r"## 질문(.*?)(?:## 답변|$)", text, re.DOTALL)
    return m.group(1) if m else text[:3000]


def _a_section(text: str) -> str:
    """답변 섹션만 추출"""
    m = re.search(r"## 답변(.*?)$", text, re.DOTALL)
    return m.group(1) if m else ""


def _parse_korean_amount(s: str) -> float | None:
    """'2,200,000', '220만원', '300만원' → float"""
    s = s.strip().replace(",", "")
    if re.search(r"[가-힣]", s):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def extract_base_wage(text: str) -> tuple[str, float] | None:
    """
    질문 텍스트에서 기본 임금 추출.
    Returns (wage_type_key, amount) or None
    """
    q = _q_section(text)

    rules = [
        # 시급 X원
        (r"시급\s*[:：]?\s*([\d,]+)\s*원", "시급"),
        (r"([\d,]+)\s*원\s*시급", "시급"),
        (r"시급\s+([\d,]+)", "시급"),
        # 최저임금 연도별 시급
        (r"최저\s*임금\s*(?:시급)?\s*([\d,]+)\s*원", "시급"),
        # 기본급 X원 (콜론 없는 경우 포함)
        (r"기본급\s*[:：]?\s*([\d,]+(?:,\d{3})*)\s*원", "월급"),
        (r"기본급(?:은|이|으로)?\s+월?\s*([\d,]{6,})\s*원", "월급"),
        # 월급 X원
        (r"월급\s*[:：]?\s*([\d,]+)\s*원", "월급"),
        (r"월\s*급여\s*[:：]?\s*([\d,]+)\s*원", "월급"),
        (r"월\s*([\d,]+)\s*만\s*원", "월급_만"),
        (r"월급\s*([\d,]+)\s*만", "월급_만"),
        (r"급여\s*([\d,]+)\s*만\s*원", "월급_만"),
        # 한국어 수 표현: X백만원, X천만원
        (r"([\d]+)\s*백\s*만\s*원", "월급_백만"),
        (r"월\s*([\d]+)\s*백\s*만", "월급_백만"),
        # 연봉 X원
        (r"연봉\s*[:：]?\s*([\d,]+)\s*원", "연봉"),
        (r"연봉\s*([\d,]+)\s*만\s*원", "연봉_만"),
        (r"연봉\s*([\d,]+)\s*만", "연봉_만"),
        (r"연봉\s+([\d,]+)", "연봉"),
    ]

    for pat, wt_key in rules:
        m = re.search(pat, q, re.IGNORECASE)
        if m:
            s = m.group(1).replace(",", "")
            try:
                v = float(s)
                if "백만" in wt_key:
                    v *= 1_000_000
                    wt_key = wt_key.replace("_백만", "")
                elif "만" in wt_key:
                    v *= 10000
                    wt_key = wt_key.replace("_만", "")
                # 범위 검증
                if wt_key == "시급" and 5000 <= v <= 100000:
                    return wt_key, v
                if wt_key == "월급" and 300000 <= v <= 50_000_000:
                    return wt_key, v
                if wt_key == "연봉" and 5_000_000 <= v <= 500_000_000:
                    return wt_key, v
            except ValueError:
                pass

    return None


def _to_minutes(h: int, m: int) -> int:
    """시:분 → 분(자정 기준 0~1440)"""
    return h * 60 + m


def _parse_time(s: str) -> int | None:
    """
    '08:00', '08시', '8시30분', '8시 30분' 등 → 분(0~1439)
    익일 접두어가 붙은 경우 +1440 반환
    """
    overnight = 1440 if re.search(r"익일|다음\s*날", s) else 0
    m = re.search(r"(\d{1,2})[시:]\s*(\d{2})?", s)
    if not m:
        m2 = re.search(r"(\d{1,2})\s*시", s)
        if m2:
            return _to_minutes(int(m2.group(1)), 0) + overnight
        return None
    h = int(m.group(1))
    mn = int(m.group(2)) if m.group(2) else 0
    if h > 23:
        return None
    return _to_minutes(h, mn) + overnight


def _parse_break_minutes(text: str) -> int:
    """
    '휴게시간 1시간', '휴계 12:00~13:00', '휴식 30분' 등에서 총 휴게분 합산
    """
    total = 0
    # 명시적 분수
    for m in re.finditer(r"(?:휴게|휴계|휴식|휴무)\s*시간\s*(?:은|:)?\s*([\d.]+)\s*시간", text):
        total += int(float(m.group(1)) * 60)
    for m in re.finditer(r"(?:휴게|휴계|휴식)\s*(?:시간\s*)?(\d+)\s*분", text):
        total += int(m.group(1))
    # 시간범위형 휴게 (12:00~13:00, 22시~04시 등)
    range_pat = r"(?:휴게|휴계|휴식)[^0-9\n]{0,20}(\d{1,2})[시:]\s*\d*\s*[~\-~]\s*(?:익일\s*)?(\d{1,2})[시:]"
    for m in re.finditer(range_pat, text):
        start_h, end_h = int(m.group(1)), int(m.group(2))
        diff = end_h - start_h if end_h > start_h else end_h + 24 - start_h
        if 0 < diff <= 12:
            total += diff * 60
    return total if total <= 720 else 0  # 12시간 초과는 오파싱으로 간주


def _night_overlap_minutes(start_min: int, end_min: int) -> int:
    """
    start~end 범위에서 야간(22:00~06:00) 겹치는 분 계산
    start/end 는 분(0~2879, 익일이면 1440+)
    """
    # 야간 구간: [22*60, 24*60] ∪ [24*60, 30*60] → [1320, 1440] ∪ [1440, 1800]
    # 또는 다음날 관점: [1320, 1800]
    night_start = 22 * 60       # 1320
    night_end = 30 * 60         # 1800 (=익일 06:00)
    # end가 익일 포함이면 이미 +1440 되어 있음
    # start가 익일 06:00(1800) 이후이면 야간 없음
    s = min(start_min, end_min) if start_min < end_min else start_min
    e = max(start_min, end_min) if start_min < end_min else end_min
    # 야간 구간과 교집합
    overlap = max(0, min(e, night_end) - max(s, night_start))
    return overlap


def extract_time_ranges(text: str) -> list[dict]:
    """
    '08:00 ~ 17:00', '09시~20시', '17:30~익일 08:00' 등 근무시간 범위 추출
    Returns list of {"start_min", "end_min", "work_min", "night_min", "label"}
    """
    ranges = []
    seen_labels = set()
    # 패턴 1: "08:00~17:00", "09시~20시", "17:30~익일08:00"
    # 패턴 2: "20시부터 5시까지", "22시부터 익일 6시까지"
    # 그룹: (1)익일?, (2)시작시, (3)시작분, (4)익일?, (5)종료시, (6)종료분
    PAT = (
        r"(?:근무|출근|일하|작업|[주야간]+근무)?\s*"
        r"(익일\s*)?(\d{1,2})[시:]\s*(\d{0,2})"     # groups 1,2,3
        r"\s*[~\-~]\s*"
        r"(익일\s*)?(\d{1,2})[시:]\s*(\d{0,2})"     # groups 4,5,6
    )
    PAT2 = (
        r"(\d{1,2})\s*시\s*(?:부터|~)\s*(익일\s*)?(\d{1,2})\s*시\s*(?:까지|~)"
    )
    # PAT2 처리: "20시부터 5시까지" → (start_h, overnight?, end_h)
    for m in re.finditer(PAT2, text, re.UNICODE):
        s_h, overnight_sfx, e_h_raw = int(m.group(1)), m.group(2) or "", m.group(3)
        e_h = int(e_h_raw)
        if e_h == 24:
            e_h = 0
            overnight_sfx = "익일"
        if not (0 <= s_h <= 23 and 0 <= e_h <= 23):
            continue
        start_min = s_h * 60
        end_min = e_h * 60
        if overnight_sfx or end_min <= start_min:
            end_min += 1440
        total_span = end_min - start_min
        if not (60 <= total_span <= 24 * 60):
            continue
        label = f"{s_h:02d}:00~{e_h:02d}:00"
        if label in seen_labels:
            continue
        seen_labels.add(label)
        ctx_start = max(0, m.start() - 50)
        ctx_end = min(len(text), m.end() + 100)
        break_min = _parse_break_minutes(text[ctx_start:ctx_end])
        if break_min == 0:
            if total_span >= 8 * 60:
                break_min = 60
            elif total_span >= 4 * 60:
                break_min = 30
        work_min = max(0, total_span - break_min)
        night_min = _night_overlap_minutes(start_min, end_min)
        ranges.append({"start_min": start_min, "end_min": end_min,
                        "work_min": work_min, "night_min": night_min, "label": label})

    for m in re.finditer(PAT, text, re.UNICODE):
        overnight_prefix = m.group(1) or ""
        s_h_raw = m.group(2)
        s_mn_raw = m.group(3) or "0"
        overnight_suffix = m.group(4) or ""
        e_h_raw = m.group(5)
        e_mn_raw = m.group(6) or "0"

        try:
            s_h = int(s_h_raw)
            s_mn = int(s_mn_raw) if s_mn_raw else 0
            e_h = int(e_h_raw)
            e_mn = int(e_mn_raw) if e_mn_raw else 0
        except ValueError:
            continue

        # 24:xx → 익일 00:xx 처리
        if e_h == 24:
            e_h = 0
            overnight_suffix = overnight_suffix or "익일"
        if not (0 <= s_h <= 23 and 0 <= s_mn <= 59 and 0 <= e_h <= 23 and 0 <= e_mn <= 59):
            continue

        start_min = s_h * 60 + s_mn
        end_min = e_h * 60 + e_mn
        if overnight_suffix:
            end_min += 1440
        elif end_min <= start_min:
            end_min += 1440  # 익일로 간주

        label = f"{s_h:02d}:{s_mn:02d}~{e_h:02d}:{e_mn:02d}"
        if label in seen_labels:
            continue
        seen_labels.add(label)

        total_span = end_min - start_min
        if not (60 <= total_span <= 24 * 60):  # 1h~24h 범위
            continue

        # 해당 텍스트 주변 휴게시간 찾기 (앞뒤 100자 내)
        ctx_start = max(0, m.start() - 50)
        ctx_end = min(len(text), m.end() + 100)
        ctx = text[ctx_start:ctx_end]
        break_min = _parse_break_minutes(ctx)
        if break_min == 0:
            # 기본 휴게 추정: 8h 이상이면 1h, 4h 이상이면 30min
            if total_span >= 8 * 60:
                break_min = 60
            elif total_span >= 4 * 60:
                break_min = 30

        work_min = max(0, total_span - break_min)
        night_min = _night_overlap_minutes(start_min, end_min)

        ranges.append({
            "start_min": start_min,
            "end_min": end_min,
            "work_min": work_min,
            "night_min": night_min,
            "label": label,
        })

    return ranges


def extract_schedule(text: str) -> dict:
    """
    질문 텍스트에서 근무 스케줄 정보 추출.
    우선순위: 명시적 수치 > 시간범위 계산 > 일/주 근로시간 명시
    """
    q = _q_section(text)
    sched: dict = {}

    # ── 1. 사업장 규모 ──────────────────────────────────────────────────────
    if re.search(r"5인\s*미만|5인미만|5명\s*미만|4인|3인|2인|1인", q):
        sched["biz_under5"] = True
    elif re.search(r"5인\s*이상|5인이상|[6-9]인|[0-9]+[0-9]인", q):
        sched["biz_under5"] = False

    # ── 2. 주 근무일 ────────────────────────────────────────────────────────
    for pat in [
        r"주\s*(\d)\s*일\s*(?:근무|출근|일)",
        r"(?:월|화|수|목|금|토|일)~(?:월|화|수|목|금|토|일)\s+(\d)\s*일",
        r"(\d)\s*일\s*(?:근무|출근)?\s*(?:주|1주)",
    ]:
        m = re.search(pat, q)
        if m:
            v = float(m.group(1))
            if 1 <= v <= 7:
                sched["weekly_days"] = v
                break
    if "weekly_days" not in sched:
        # 요일 열거로 추정 — "X요일" 접미어 필수 또는 범위 표현 "월~금"
        # (단독 월,수,금은 월급/수당/금액 등의 오탐이 많아 제외)
        weekdays_explicit = re.findall(r"[월화수목금토일]요일", q)
        if 3 <= len(set(weekdays_explicit)) <= 7:
            sched["weekly_days"] = float(len(set(weekdays_explicit)))
        else:
            # 범위 표현: "월~금", "월-금" 등
            m_range = re.search(r"([월화수목금토일])\s*[~\-]\s*([월화수목금토일])", q)
            if m_range:
                day_order = "월화수목금토일"
                s_idx = day_order.find(m_range.group(1))
                e_idx = day_order.find(m_range.group(2))
                if 0 <= s_idx < e_idx:
                    sched["weekly_days"] = float(e_idx - s_idx + 1)

    # ── 3. 명시적 연장근로 시간 ─────────────────────────────────────────────
    OT_EXPLICIT = [
        r"연장\s*근로\s*시간\s*[:：]\s*([\d.]+)\s*시간",
        r"시간외\s*(?:근무|근로)\s*시간\s*[:：]?\s*([\d.]+)\s*시간",
        r"연장\s*근로\s*총?\s*([\d.]+)\s*시간",
        r"(?:주\s*)?연장\s*(?:근무|근로|시간)\s*([\d.]+)\s*시간",
        r"([\d.]+)\s*시간\s*(?:씩\s*)?연장",
        r"O\.?T\.?\s*([\d.]+)\s*시간",
    ]
    for pat in OT_EXPLICIT:
        m = re.search(pat, q, re.IGNORECASE)
        if m:
            v = float(m.group(1))
            if 0 < v <= 52:
                sched["ot_h"] = v
                break

    # ── 4. 명시적 야간근로 시간 ─────────────────────────────────────────────
    NIGHT_EXPLICIT = [
        r"야간\s*근로\s*시간\s*[:：]\s*([\d.]+)\s*시간",
        r"야간\s*근무\s*시간\s*[:：]?\s*([\d.]+)\s*시간",
        r"야간\s*(?:총)?\s*([\d.]+)\s*시간",
        r"([\d.]+)\s*시간\s*야간",
    ]
    for pat in NIGHT_EXPLICIT:
        m = re.search(pat, q, re.IGNORECASE)
        if m:
            v = float(m.group(1))
            if 0 < v <= 24:
                sched["night_h"] = v
                break

    # ── 5. 시간범위 파싱 → 일 근로시간·연장·야간 유도 ─────────────────────
    ranges = extract_time_ranges(q)
    # 소정근로 범위 후보: 가장 많은 시간범위 (보통 하루 주요 근무시간)
    main_ranges = [r for r in ranges if 360 <= r["work_min"] <= 720]  # 6~12h
    if main_ranges:
        # 가장 긴 것(또는 가장 이른 것)을 주 스케줄로 사용
        primary = max(main_ranges, key=lambda r: r["work_min"])
        daily_h_range = primary["work_min"] / 60

        if "daily_h" not in sched:
            sched["daily_h"] = min(daily_h_range, 12.0)

        # 연장 = 일 근로시간 - 8 (양수인 경우)
        if "ot_h" not in sched:
            daily_ot_h = max(0.0, daily_h_range - 8.0)
            if daily_ot_h > 0:
                weekly_days = sched.get("weekly_days", 5.0)
                sched["ot_h"] = round(daily_ot_h * weekly_days, 2)

        # 야간 = 22:00~06:00 교차 분
        if "night_h" not in sched and primary["night_min"] > 0:
            weekly_days = sched.get("weekly_days", 5.0)
            sched["night_h"] = round(primary["night_min"] / 60 * weekly_days, 2)

    # ── 6. 일 근로시간 명시 ─────────────────────────────────────────────────
    if "daily_h" not in sched:
        for pat in [
            r"(?:1일|하루|일일)\s*(?:소정)?\s*근로\s*시간\s*[:：]?\s*([\d.]+)",
            r"(?:1일|하루)\s*([\d.]+)\s*시간\s*근무",
            r"일\s*([\d.]+)\s*시간",
        ]:
            m = re.search(pat, q)
            if m:
                v = float(m.group(1))
                if 1 <= v <= 12:
                    sched["daily_h"] = v
                    break

    # 일 근로시간 > 8이면 추가 연장수당 유도 (명시 없을 때)
    if "ot_h" not in sched and "daily_h" in sched:
        daily_ot = max(0.0, sched["daily_h"] - 8.0)
        if daily_ot > 0:
            sched["ot_h"] = round(daily_ot * sched.get("weekly_days", 5.0), 2)

    # ── 7. 주 총 근로시간 명시 → 주 연장 유도 ─────────────────────────────
    if "ot_h" not in sched:
        for pat in [r"주\s*([\d.]+)\s*시간\s*(?:근무|근로)", r"1주\s*([\d.]+)\s*시간"]:
            m = re.search(pat, q)
            if m:
                wh = float(m.group(1))
                if 40 < wh <= 68:
                    sched["ot_h"] = wh - 40.0
                    break

    # ── 8. 일 근로시간 최종 fallback ──────────────────────────────────────
    if "daily_h" not in sched:
        sched["daily_h"] = 8.0

    return sched


def extract_allowances(text: str) -> list[dict]:
    """질문 텍스트에서 고정수당 정보 추출"""
    q = _q_section(text)
    allowances = []
    # 식대/식비
    m = re.search(r"식대\s*(?:[:：]|수당)?\s*([\d,]+)\s*(?:원|만원)?", q)
    if m:
        s = m.group(1).replace(",", "")
        try:
            v = float(s)
            if v < 1000:  # 만원 단위일 가능성
                v *= 10000
            if 10000 <= v <= 500000:
                allowances.append({"name": "식대", "amount": v, "is_ordinary": True})
        except ValueError:
            pass
    # 직책수당
    m = re.search(r"직책\s*수당\s*(?:[:：])?\s*([\d,]+)\s*(?:원|만원)?", q)
    if m:
        s = m.group(1).replace(",", "")
        try:
            v = float(s)
            if v < 1000:
                v *= 10000
            if 10000 <= v <= 1000000:
                allowances.append({"name": "직책수당", "amount": v, "is_ordinary": True})
        except ValueError:
            pass
    return allowances


def extract_post_year(text: str) -> int:
    """마크다운에서 작성일 연도 추출"""
    m = re.search(r"작성일.*?(\d{4})\.\d+\.\d+", text)
    if m:
        y = int(m.group(1))
        if 2018 <= y <= 2026:
            return y
    return 2025


def build_wage_input_from_markdown(text: str, provided_info: dict, calc_type: str) -> WageInput | None:
    """마크다운 텍스트와 provided_info 결합하여 WageInput 생성"""

    # 1) 임금 추출 — provided_info 우선, 없으면 markdown에서
    wage_data = None
    p_info = provided_info or {}

    # provided_info에서 시도
    p_type = p_info.get("임금형태") or ""
    p_amt_str = p_info.get("임금액") or ""
    if p_amt_str:
        p_amt_str = str(p_amt_str)
        wt_candidate = WAGE_TYPE_MAP.get(p_type, WageType.MONTHLY)

        # 시급인 경우: "시급 X원" 패턴 우선 추출 (복합 문자열에서 월급 오탐 방지)
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
            # 연봉 키워드 감지 → ANNUAL로 강제 변환
            if "연봉" in p_amt_str:
                wt_candidate = WageType.ANNUAL

            # 일반 5자리+ 숫자 추출
            m = re.search(r"([\d,]{5,})", p_amt_str)
            if m:
                try:
                    v = float(m.group(1).replace(",", ""))
                    if v > 10000:
                        if wt_candidate == WageType.HOURLY and v > 100000:
                            wage_data = ("월급", v)  # 시급으로 분류됐지만 금액이 크면 월급
                        elif wt_candidate == WageType.ANNUAL:
                            wage_data = ("연봉", v)
                        elif wt_candidate == WageType.MONTHLY and v < 500_000:
                            pass  # 수당/용돈 수준이면 임금으로 취급 안 함
                        else:
                            wage_data = (p_type or "월급", v)
                except ValueError:
                    pass

    # provided_info에 없으면 마크다운에서 추출
    if wage_data is None:
        result = extract_base_wage(text)
        if result:
            wage_data = result

    if wage_data is None:
        return None

    wage_type_key, amount = wage_data
    wage_type = WAGE_TYPE_MAP.get(wage_type_key, WageType.MONTHLY)

    # 2) 스케줄 추출
    sched_data = extract_schedule(text)
    q = _q_section(text)

    # provided_info에서 스케줄 보완
    ot_h = _parse_h(p_info.get("연장근로시간") or p_info.get("주연장시간") or "") or sched_data.get("ot_h", 0)
    night_h = _parse_h(p_info.get("야간근로시간") or "") or sched_data.get("night_h", 0)
    daily_h = _parse_h(p_info.get("일일근로시간") or p_info.get("소정근로시간") or "") or sched_data.get("daily_h", 8.0)
    work_days = _parse_h(p_info.get("주근무일수") or "") or sched_data.get("weekly_days", 5.0)

    # 3) 사업장 규모
    biz_under5 = sched_data.get("biz_under5")
    size_str = str(p_info.get("사업장규모") or "")
    if biz_under5 is None:
        biz_under5 = "5인 미만" in size_str or "5인미만" in size_str
    biz_size = BusinessSize.UNDER_5 if biz_under5 else BusinessSize.OVER_5

    # 4) 근무형태
    근무형태 = p_info.get("근무형태") or ""
    work_type = WorkType.REGULAR
    for k, v in {
        "4조2교대": WorkType.SHIFT_4_2, "3조2교대": WorkType.SHIFT_3_2,
        "3교대": WorkType.SHIFT_3, "2교대": WorkType.SHIFT_2,
    }.items():
        if k in 근무형태:
            work_type = v
            break

    schedule = WorkSchedule(
        daily_work_hours=daily_h,
        weekly_work_days=work_days,
        weekly_overtime_hours=ot_h,
        weekly_night_hours=night_h,
    )

    # 5) 고정수당
    allowances = extract_allowances(text)

    # 게시글 작성 연도를 reference_year로 사용 (최저임금 연도 정확성)
    ref_year = extract_post_year(text)

    # 파트타임 월 소정시간 계산 (weekly hours < 40)
    weekly_h = daily_h * work_days
    if weekly_h < 40:
        monthly_scheduled = (weekly_h + weekly_h / 40 * 8) * 365 / 12 / 7
        schedule = WorkSchedule(
            daily_work_hours=daily_h,
            weekly_work_days=work_days,
            weekly_overtime_hours=ot_h,
            weekly_night_hours=night_h,
            monthly_scheduled_hours=round(monthly_scheduled, 2),
        )

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

    # 6) 연차 관련
    period = p_info.get("근무기간") or ""
    if period and calc_type in ["연차수당", "해고예고수당"]:
        inp.start_date = _guess_start_date(period)

    # 해고예고
    if calc_type == "해고예고수당":
        notice = _parse_h(p_info.get("예고일수") or "")
        inp.notice_days_given = int(notice) if notice else 0
        inp.dismissal_date = "2025-01-01"

    return inp


def _parse_h(s: str) -> float:
    if not s:
        return 0.0
    m = re.search(r"([\d.]+)", str(s))
    return float(m.group(1)) if m else 0.0


def _guess_start_date(period_str: str) -> str | None:
    from datetime import date, timedelta
    today = date.today()
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


# ── 답변 핵심 수치 추출 ───────────────────────────────────────────────────────

def extract_answer_info(text: str, calc_type: str) -> dict:
    """
    답변 텍스트에서 계산 유형별 핵심 수치 추출
    """
    answer = _a_section(text)
    if not answer:
        return {"amounts": [], "hourly": None, "compliant": None, "leave_days": None}

    # 모든 금액 추출
    amounts = _extract_amounts(answer)

    # 통상시급 (X원이 통상시급 / 시간급 X원)
    hourly = None
    for pat in [
        r"통상\s*시급\s*(?:은|이|:)?\s*([\d,]+)\s*원",
        r"시간급\s*(?:은|이|:)?\s*([\d,]+)\s*원",
        r"([\d,]+)\s*원이\s*통상\s*시급",
        r"시급\s*([\d,]+)\s*원",
        r"통상시급\s+([\d,]+)",
    ]:
        m = re.search(pat, answer)
        if m:
            v = _safe_float(m.group(1))
            if v and 5000 <= v <= 100000:
                hourly = v
                break

    # 최저임금 충족 여부
    compliant = None
    if re.search(r"최저임금을?\s*(?:충족|초과|상회|이상|적법)", answer):
        compliant = True
    if re.search(r"최저임금\s*(?:미달|위반|미충족|이하|부족)", answer):
        compliant = False
    # 일반 충족/미달
    if compliant is None:
        if re.search(r"(?:법률|위법|위반|불법|적법|합법).*(?:되|임)", answer):
            pass  # 단순 법률 언급이므로 생략
        if re.search(r"최저\s*임금", answer):
            if re.search(r"충족|초과|이상", answer):
                compliant = True
            elif re.search(r"미달|위반|미충족|부족", answer):
                compliant = False

    # 연차일수
    leave_days = None
    for pat in [
        r"(\d+(?:\.\d+)?)\s*일\s*(?:의\s*연차|분\s*연차|\s*연차|\s*발생|\s*미사용)",
        r"연차\s*(?:휴가)?\s*(\d+(?:\.\d+)?)\s*일",
        r"(\d+(?:\.\d+)?)\s*일\s*연차",
    ]:
        m = re.search(pat, answer)
        if m:
            v = float(m.group(1))
            if 0 < v <= 25:
                leave_days = v
                break

    # 핵심 계산 결과 — 답변에서 "따라서/계산하면/합계/총" 뒤에 오는 금액
    key_amounts = []
    for pat in [
        r"(?:따라서|계산하면|합계|총|지급|수령)\s+(?:월)?\s*([\d,]+)\s*원",
        r"([\d,]+)\s*원\s*(?:을|이)\s*(?:지급|수령|받)",
        r"합\s+계\s*:\s*([\d,]+)\s*원",
        r"합계\s*[:：]\s*([\d,]+)\s*원",
    ]:
        for m in re.finditer(pat, answer):
            v = _safe_float(m.group(1))
            if v and 10000 <= v <= 100_000_000:
                key_amounts.append(v)

    return {
        "amounts": amounts,
        "key_amounts": key_amounts,
        "hourly": hourly,
        "compliant": compliant,
        "leave_days": leave_days,
        "answer_preview": answer[:300],
    }


def _extract_amounts(text: str) -> list[float]:
    amounts = set()
    # X,XXX원
    for m in re.finditer(r"([\d,]+(?:\.\d+)?)\s*원", text):
        v = _safe_float(m.group(1))
        if v and 1000 <= v <= 100_000_000:
            amounts.add(v)
    # X만원
    for m in re.finditer(r"([\d.]+)\s*만\s*원", text):
        try:
            amounts.add(float(m.group(1)) * 10000)
        except ValueError:
            pass
    return list(amounts)


def _safe_float(s: str) -> float | None:
    try:
        return float(str(s).replace(",", ""))
    except (ValueError, AttributeError):
        return None


# ── 계산기 결과 vs 답변 비교 ─────────────────────────────────────────────────

@dataclass
class CompareResult:
    post_id: str
    calc_type: str
    verdict: str          # ✅ ⚠️ ❌ ⏭️
    reason: str
    calc_value: str       # 계산기 핵심 결과
    answer_value: str     # 답변 핵심 수치
    wage_input_ok: bool


def _get_targets(calc_type: str) -> list[str]:
    return {
        "연장수당":    ["overtime", "minimum_wage"],
        "최저임금":    ["minimum_wage"],
        "주휴수당":    ["weekly_holiday", "minimum_wage"],
        "연차수당":    ["annual_leave"],
        "해고예고수당": ["dismissal"],
        "통상임금":    ["minimum_wage"],
        "임금계산":    ["overtime", "minimum_wage", "weekly_holiday"],
        "일할계산":    ["prorated", "minimum_wage"],
    }.get(calc_type, ["minimum_wage"])


def _parse_summary_num(s: str | None) -> float:
    if not s:
        return 0.0
    cleaned = re.sub(r"[,원일\s]", "", str(s))
    m = re.search(r"[\d.]+", cleaned)
    return float(m.group()) if m else 0.0


def _closest(amounts: list[float], target: float) -> float:
    return min(amounts, key=lambda x: abs(x - target)) if amounts else 0.0


def _ratio_verdict(ratio: float, ans: float, calc: float) -> tuple[str, str]:
    if ratio == 0 or calc == 0:
        return "⏭️", "수치 비교 불가"
    diff_pct = abs(ratio - 1) * 100
    if diff_pct <= 5:
        return "✅", f"±{diff_pct:.1f}% (계산: {calc:,.0f}원, 답변: {ans:,.0f}원)"
    elif diff_pct <= 20:
        return "⚠️", f"±{diff_pct:.1f}% (계산: {calc:,.0f}원, 답변: {ans:,.0f}원)"
    else:
        return "❌", f"±{diff_pct:.1f}% (계산: {calc:,.0f}원, 답변: {ans:,.0f}원)"


def compare_one(record: dict, text: str, calc: WageCalculator) -> CompareResult:
    post_id = record["file_id"]
    calc_type = record.get("calculation_type", "")
    info = record.get("provided_info", {}) or {}

    # WageInput 생성
    inp = build_wage_input_from_markdown(text, info, calc_type)
    if inp is None:
        return CompareResult(post_id=post_id, calc_type=calc_type,
            verdict="⏭️", reason="임금액 정보 추출 불가",
            calc_value="-", answer_value="-", wage_input_ok=False)

    # 계산기 실행
    targets = _get_targets(calc_type)
    try:
        result = calc.calculate(inp, targets=targets)
    except Exception as e:
        return CompareResult(post_id=post_id, calc_type=calc_type,
            verdict="⏭️", reason=f"계산기 오류: {e}",
            calc_value="-", answer_value="-", wage_input_ok=True)

    # 답변 수치 추출
    extracted = extract_answer_info(text, calc_type)
    amounts = extracted["amounts"]
    key_amounts = extracted.get("key_amounts", [])

    # ── 유형별 비교 ──────────────────────────────────────────────────────────

    # 최저임금 / 통상임금
    if calc_type in ("최저임금", "통상임금", "통상시급"):
        calc_ok = result.minimum_wage_ok
        calc_hourly = result.ordinary_hourly
        calc_val = f"{'충족' if calc_ok else '미달'} (시급 {calc_hourly:,.0f}원)"

        # 통상시급 수치 비교 우선
        if extracted["hourly"]:
            ans_h = extracted["hourly"]
            ratio = ans_h / calc_hourly if calc_hourly else 0
            v, r = _ratio_verdict(ratio, ans_h, calc_hourly)
            return CompareResult(post_id=post_id, calc_type=calc_type,
                verdict=v, reason=f"통상시급 비교: {r}",
                calc_value=calc_val, answer_value=f"시급 {ans_h:,.0f}원", wage_input_ok=True)

        # 충족 여부 비교
        if extracted["compliant"] is not None:
            match = (extracted["compliant"] == calc_ok)
            v = "✅" if match else "❌"
            r = f"최저임금 판정 {'일치' if match else '불일치'}"
            return CompareResult(post_id=post_id, calc_type=calc_type,
                verdict=v, reason=r,
                calc_value=calc_val,
                answer_value="충족" if extracted["compliant"] else "미달",
                wage_input_ok=True)

        # 금액 비교
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

    # 연장수당
    if calc_type in ("연장수당", "임금계산"):
        ot_summary = result.summary.get("연장/야간/휴일수당(월)")
        calc_ot = _parse_summary_num(ot_summary)
        calc_total = result.monthly_total
        calc_val = f"연장수당 {calc_ot:,.0f}원 / 월계 {calc_total:,.0f}원"

        # 통상시급 비교 우선 (답변에 통상시급이 있는 경우)
        if extracted["hourly"] and result.ordinary_hourly:
            ans_h = extracted["hourly"]
            ratio = ans_h / result.ordinary_hourly
            v, r = _ratio_verdict(ratio, ans_h, result.ordinary_hourly)
            return CompareResult(post_id=post_id, calc_type=calc_type,
                verdict=v, reason=f"통상시급 비교: {r}",
                calc_value=f"통상시급 {result.ordinary_hourly:,.0f}원",
                answer_value=f"시급 {ans_h:,.0f}원", wage_input_ok=True)

        if not amounts:
            return CompareResult(post_id=post_id, calc_type=calc_type,
                verdict="⏭️", reason="답변에 금액 없음",
                calc_value=calc_val, answer_value="-", wage_input_ok=True)

        # 핵심 금액 우선
        target = calc_ot if calc_ot else calc_total
        pool = key_amounts if key_amounts else amounts
        best = _closest(pool, target)

        # 단위 불일치 방지: 월급 수준 vs 시급/일급 수준
        if target >= 100_000 and best < 50_000:
            return CompareResult(post_id=post_id, calc_type=calc_type,
                verdict="⏭️", reason="단위 불일치 의심 (월급 수준 vs 시급/일급 수준)",
                calc_value=calc_val, answer_value=f"{best:,.0f}원", wage_input_ok=True)

        ratio = best / target if target else 0
        v, r = _ratio_verdict(ratio, best, target)
        return CompareResult(post_id=post_id, calc_type=calc_type,
            verdict=v, reason=r,
            calc_value=calc_val, answer_value=f"{best:,.0f}원", wage_input_ok=True)

    # 주휴수당
    if calc_type == "주휴수당":
        wh_summary = result.summary.get("주휴수당(월)")
        calc_num = _parse_summary_num(wh_summary) if wh_summary else result.monthly_total
        calc_val = f"주휴수당 {calc_num:,.0f}원/월"

        if not amounts:
            return CompareResult(post_id=post_id, calc_type=calc_type,
                verdict="⏭️", reason="답변에 금액 없음",
                calc_value=calc_val, answer_value="-", wage_input_ok=True)

        best = _closest(key_amounts or amounts, calc_num)

        # 단위 불일치 방지 (월 주휴수당 vs 일/시간 단위 소액)
        if calc_num >= 100_000 and best < 50_000:
            return CompareResult(post_id=post_id, calc_type=calc_type,
                verdict="⏭️", reason="단위 불일치 의심 (월 주휴수당 vs 일/시급 수준)",
                calc_value=calc_val, answer_value=f"{best:,.0f}원", wage_input_ok=True)

        ratio = best / calc_num if calc_num else 0
        v, r = _ratio_verdict(ratio, best, calc_num)
        return CompareResult(post_id=post_id, calc_type=calc_type,
            verdict=v, reason=r,
            calc_value=calc_val, answer_value=f"{best:,.0f}원", wage_input_ok=True)

    # 연차수당
    if calc_type == "연차수당":
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

    # 해고예고수당
    if calc_type == "해고예고수당":
        ds_pay = result.summary.get("해고예고수당")
        calc_num = _parse_summary_num(ds_pay) if ds_pay else None
        calc_val = f"해고예고수당 {ds_pay}" if ds_pay else "-"

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

    # 일할계산
    if calc_type == "일할계산":
        pr_pay = result.summary.get("일할계산 임금")
        calc_num = _parse_summary_num(pr_pay) if pr_pay else None
        calc_val = f"일할계산 {pr_pay}" if pr_pay else "-"

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

    return CompareResult(post_id=post_id, calc_type=calc_type,
        verdict="⏭️", reason="비교 로직 미구현",
        calc_value="-", answer_value="-", wage_input_ok=True)


# ── 데이터 로딩 & 샘플링 ─────────────────────────────────────────────────────

def load_records() -> dict[str, list[dict]]:
    wage_types = set(STRATA_TARGET.keys())
    by_type: dict[str, list[dict]] = defaultdict(list)
    with open("analysis_qna.jsonl") as f:
        for line in f:
            r = json.loads(line)
            ct = r.get("calculation_type", "")
            qt = r.get("question_type", "")
            if qt != "임금" or not r.get("requires_calculation"):
                continue
            if ct not in wage_types:
                continue
            fpath = f"output_qna/{r['filename']}"
            if not os.path.exists(fpath):
                continue
            # 임금 추출 가능 여부 사전 확인
            with open(fpath, encoding="utf-8") as f2:
                text = f2.read()
            info = r.get("provided_info", {}) or {}
            inp_test = build_wage_input_from_markdown(text, info, ct)
            if inp_test is not None:
                r["_filepath"] = fpath
                r["_text"] = text
                by_type[ct].append(r)
    return by_type


def stratified_sample(by_type: dict) -> list[dict]:
    sampled = []
    for ct, target_n in STRATA_TARGET.items():
        pool = by_type.get(ct, [])
        n = min(target_n, len(pool))
        sampled.extend(random.sample(pool, n))
    random.shuffle(sampled)
    return sampled


# ── 보고서 출력 ───────────────────────────────────────────────────────────────

def print_report(results: list[CompareResult]):
    print("\n" + "=" * 72)
    print("📊 임금계산기 vs 실제 Q&A 답변 비교 보고서 (v2)")
    print("=" * 72)

    vc = Counter(r.verdict for r in results)
    total = len(results)

    print(f"\n총 비교 건수: {total}건\n")
    for v, label in [("✅", "일치"), ("⚠️", "근접"), ("❌", "불일치"), ("⏭️", "비교불가")]:
        cnt = vc.get(v, 0)
        pct = cnt / total * 100 if total else 0
        bar = "█" * int(pct / 2)
        print(f"  {v} {label:5s}: {cnt:3d}건 ({pct:5.1f}%) {bar}")

    comparable = [r for r in results if r.verdict != "⏭️"]
    if comparable:
        ok = sum(1 for r in comparable if r.verdict in ("✅", "⚠️"))
        ok_strict = sum(1 for r in comparable if r.verdict == "✅")
        print(f"\n  비교가능 {len(comparable)}건 기준:")
        print(f"    ✅+⚠️ (±20% 이내): {ok}/{len(comparable)} = {ok/len(comparable)*100:.1f}%")
        print(f"    ✅    (±5% 이내):  {ok_strict}/{len(comparable)} = {ok_strict/len(comparable)*100:.1f}%")

    print("\n── 계산 유형별 결과 ──")
    by_type: dict[str, list[CompareResult]] = defaultdict(list)
    for r in results:
        by_type[r.calc_type].append(r)

    for ct in STRATA_TARGET:
        recs = by_type.get(ct, [])
        if not recs:
            continue
        sub_vc = Counter(r.verdict for r in recs)
        total_ct = len(recs)
        print(f"\n  [{ct}] {total_ct}건")
        for v, label in [("✅", "일치"), ("⚠️", "근접"), ("❌", "불일치"), ("⏭️", "비교불가")]:
            cnt = sub_vc.get(v, 0)
            if cnt:
                print(f"    {v} {label}: {cnt}건")

    print("\n\n── 상세 비교 결과 ──")
    hdr = f"{'#':>3} {'유형':8} {'판정':4} {'포스트ID':>10}  {'계산기 결과':38} {'답변 수치':25} {'비고'}"
    print(hdr)
    print("-" * 135)
    for i, r in enumerate(results, 1):
        calc_s = r.calc_value[:36] if len(r.calc_value) > 36 else r.calc_value
        ans_s = r.answer_value[:23] if len(r.answer_value) > 23 else r.answer_value
        reason_s = r.reason[:45] if len(r.reason) > 45 else r.reason
        print(f"{i:3d} {r.calc_type:8} {r.verdict:4} {r.post_id:>10}  {calc_s:38} {ans_s:25} {reason_s}")

    errors = [r for r in results if r.verdict == "❌"]
    if errors:
        print(f"\n── ❌ 불일치 케이스 ({len(errors)}건) 분석 ──")
        for r in errors:
            print(f"  [{r.calc_type}] {r.post_id}: {r.reason}")

    na_reasons = Counter(r.reason for r in results if r.verdict == "⏭️")
    if na_reasons:
        print(f"\n── ⏭️ 비교불가 주요 원인 ──")
        for reason, cnt in na_reasons.most_common(8):
            print(f"  {cnt}건: {reason}")


def main():
    print("임금계산기 vs Q&A 답변 비교 v2 실행 중...")
    print(f"랜덤 시드: {RANDOM_SEED}, 목표: {TOTAL_TARGET}건")
    print("임금 추출 가능한 게시글 필터링 중...", flush=True)

    by_type = load_records()
    print("\n계산 유형별 임금 추출 가능 게시글:")
    total_avail = 0
    for ct, target in STRATA_TARGET.items():
        avail = len(by_type.get(ct, []))
        actual = min(target, avail)
        total_avail += actual
        print(f"  {ct:10s}: {avail:4d}건 풀 중 {actual:3d}건 샘플링")

    samples = stratified_sample(by_type)
    print(f"\n총 샘플: {len(samples)}건")

    calc = WageCalculator()
    results = []

    print("\n비교 실행 중", end="", flush=True)
    for i, record in enumerate(samples):
        text = record["_text"]
        res = compare_one(record, text, calc)
        results.append(res)
        if (i + 1) % 10 == 0:
            print(f" {i+1}", end="", flush=True)
    print(" 완료")

    print_report(results)

    # JSON 저장
    out = [
        {
            "post_id": r.post_id,
            "calc_type": r.calc_type,
            "verdict": r.verdict,
            "reason": r.reason,
            "calc_value": r.calc_value,
            "answer_value": r.answer_value,
        }
        for r in results
    ]
    with open("comparison_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\n결과 저장: comparison_results.json")


if __name__ == "__main__":
    main()
