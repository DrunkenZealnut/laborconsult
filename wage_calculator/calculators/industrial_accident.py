"""
산재보상금 계산기 (산업재해보상보험법)

6개 급여 항목 계산:
- 휴업급여 (제52조): 평균임금 × 70% × 요양일수
- 상병보상연금 (제66조): 평균임금 × 등급별 연금일수
- 장해급여 (제57조): 등급별 연금/일시금
- 유족급여 (제62조): 연금(47%+5%×인원) / 일시금(1,300일)
- 장례비 (제71조): 평균임금 × 120일 (최고/최저 적용)

■ 참조: https://www.nodong.kr/IndustrialAccidentCompensationCal
"""

from dataclasses import dataclass

from ..base import BaseCalculatorResult
from ..models import WageInput
from ..constants import (
    MINIMUM_HOURLY_WAGE,
    DISABILITY_GRADE_TABLE,
    SEVERE_ILLNESS_DAYS,
    SURVIVOR_BASE_RATIO,
    SURVIVOR_ADD_RATIO,
    SURVIVOR_MAX_RATIO,
    SURVIVOR_LUMP_SUM_DAYS,
    FUNERAL_DAYS,
    FUNERAL_LIMITS,
    SICK_LEAVE_RATE,
    SICK_LEAVE_LOW_RATE,
    MIN_COMP_THRESHOLD,
    MIN_COMPENSATION_DAILY,
)
from .ordinary_wage import OrdinaryWageResult


@dataclass
class IndustrialAccidentResult(BaseCalculatorResult):
    """산재보상금 계산 결과"""
    avg_daily_wage: float = 0.0              # 적용 1일 평균임금

    # 휴업급여
    sick_leave_daily: float = 0.0            # 1일 휴업급여
    sick_leave_total: float = 0.0            # 휴업급여 총액
    sick_leave_days: int = 0                 # 요양일수
    min_comp_applied: bool = False           # 최저보상기준 적용 여부

    # 상병보상연금
    illness_pension_daily: float = 0.0       # 상병보상연금 1일분
    illness_pension_annual: float = 0.0      # 상병보상연금 연간액
    illness_grade: int = 0                   # 중증요양상태 등급

    # 장해급여
    disability_amount: float = 0.0           # 장해급여 금액
    disability_grade: int = 0                # 장해등급
    disability_type: str = ""                # "연금" / "일시금"
    disability_days: int = 0                 # 적용 보상일수

    # 유족급여
    survivor_amount: float = 0.0             # 유족급여 금액
    survivor_type: str = ""                  # "연금" / "일시금"
    survivor_ratio: float = 0.0              # 유족연금 지급비율

    # 장례비
    funeral_amount: float = 0.0              # 장례비

    # 합산
    total_compensation: float = 0.0          # 전체 보상금 합산


def calc_industrial_accident(
    inp: WageInput, ow: OrdinaryWageResult
) -> IndustrialAccidentResult:
    """
    산재보상금 통합 계산

    계산 순서:
    1. 평균임금 결정 (monthly_wage/30 또는 통상임금 환산일급)
    2. 해당 급여 항목별 계산
    3. 합산 및 결과 조립
    """
    warnings: list[str] = []
    formulas: list[str] = []
    legal = [
        "산업재해보상보험법 제36조 (보험급여의 종류)",
        "산업재해보상보험법 제52조 (휴업급여: 평균임금 70%)",
        "산업재해보상보험법 제54조 (휴업급여 최저보상기준)",
        "산업재해보상보험법 제57조 (장해급여: 등급별 연금/일시금)",
        "산업재해보상보험법 제62조 (유족급여: 연금/일시금)",
        "산업재해보상보험법 제66조 (상병보상연금: 중증요양상태 등급별)",
        "산업재해보상보험법 제71조 (장례비: 120일분)",
    ]
    year = inp.reference_year

    if getattr(inp, "is_platform_worker", False):
        warnings.append(
            "특수고용직(노무제공자)은 산재보험료를 사업주와 50%씩 분담합니다 "
            "(산업재해보상보험법 제126조의2). "
            "산재 급여 산정(휴업급여·장해급여 등)은 일반 근로자와 동일합니다."
        )
        legal.append("산업재해보상보험법 제125조 (특수형태근로종사자 특례)")
        legal.append("산업재해보상보험법 제126조의2 (보험료 분담)")

    # ── 1. 평균임금 결정 ──────────────────────────────────────────────────
    avg_daily = ow.daily_ordinary_wage  # 기본: 통상임금 환산일급
    if inp.monthly_wage:
        est = inp.monthly_wage / 30
        if est > avg_daily:
            avg_daily = est
            formulas.append(
                f"평균임금(추정): {inp.monthly_wage:,.0f}원 ÷ 30일 = {avg_daily:,.0f}원/일"
            )
        else:
            formulas.append(f"평균임금: 통상임금 환산일급 {avg_daily:,.0f}원/일 적용")
    else:
        formulas.append(f"평균임금: 통상임금 환산일급 {avg_daily:,.0f}원/일 적용")

    total_compensation = 0.0
    breakdown: dict = {"적용 평균임금": f"{avg_daily:,.0f}원/일"}

    # ── 2. 휴업급여 ───────────────────────────────────────────────────────
    sl_daily, sl_total, sl_min = 0.0, 0.0, False
    if inp.sick_leave_days > 0:
        sl_daily, sl_total, sl_min, sl_f = _calc_sick_leave(
            avg_daily, inp.sick_leave_days, year
        )
        total_compensation += sl_total
        formulas.extend(sl_f)
        breakdown["휴업급여"] = (
            f"{sl_daily:,.0f}원/일 × {inp.sick_leave_days}일 = {sl_total:,.0f}원"
        )

    # ── 3. 상병보상연금 ───────────────────────────────────────────────────
    il_daily, il_annual = 0.0, 0.0
    if inp.severe_illness_grade > 0:
        il_daily, il_annual, il_f = _calc_illness_pension(
            avg_daily, inp.severe_illness_grade
        )
        total_compensation += il_annual
        formulas.extend(il_f)
        if il_annual > 0:
            breakdown["상병보상연금"] = (
                f"{il_annual:,.0f}원/년 (제{inp.severe_illness_grade}급)"
            )
        # 상병보상연금 수급 시 휴업급여 미지급 안내
        if inp.sick_leave_days > 0 and il_annual > 0:
            warnings.append(
                "상병보상연금 수급 시 휴업급여는 지급되지 않습니다 "
                "(산재보험법 제66조 제2항)"
            )

    # ── 4. 장해급여 ───────────────────────────────────────────────────────
    dis_amount, dis_type, dis_days = 0.0, "", 0
    if inp.disability_grade > 0:
        dis_amount, dis_type, dis_days, dis_f, dis_w = _calc_disability(
            avg_daily, inp.disability_grade, inp.disability_pension
        )
        total_compensation += dis_amount
        formulas.extend(dis_f)
        warnings.extend(dis_w)
        if dis_amount > 0:
            breakdown["장해급여"] = (
                f"{dis_amount:,.0f}원 ({dis_type}, 제{inp.disability_grade}급, {dis_days}일)"
            )

    # ── 5. 유족급여 ───────────────────────────────────────────────────────
    surv_amount, surv_type, surv_ratio = 0.0, "", 0.0
    if inp.is_deceased and inp.num_survivors > 0:
        surv_amount, surv_type, surv_ratio, surv_f = _calc_survivor(
            avg_daily, inp.num_survivors, inp.survivor_pension
        )
        total_compensation += surv_amount
        formulas.extend(surv_f)
        if surv_amount > 0:
            breakdown["유족급여"] = f"{surv_amount:,.0f}원 ({surv_type})"

    # ── 6. 장례비 ─────────────────────────────────────────────────────────
    fun_amount = 0.0
    if inp.is_deceased:
        fun_amount, fun_f = _calc_funeral(avg_daily, year)
        total_compensation += fun_amount
        formulas.extend(fun_f)
        breakdown["장례비"] = f"{fun_amount:,.0f}원"

    breakdown["보상금 합계"] = f"{total_compensation:,.0f}원"

    return IndustrialAccidentResult(
        avg_daily_wage=round(avg_daily, 2),
        sick_leave_daily=round(sl_daily, 0),
        sick_leave_total=round(sl_total, 0),
        sick_leave_days=inp.sick_leave_days,
        min_comp_applied=sl_min,
        illness_pension_daily=round(il_daily, 0),
        illness_pension_annual=round(il_annual, 0),
        illness_grade=inp.severe_illness_grade,
        disability_amount=round(dis_amount, 0),
        disability_grade=inp.disability_grade,
        disability_type=dis_type,
        disability_days=dis_days,
        survivor_amount=round(surv_amount, 0),
        survivor_type=surv_type,
        survivor_ratio=surv_ratio,
        funeral_amount=round(fun_amount, 0),
        total_compensation=round(total_compensation, 0),
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )


# ── 헬퍼 함수 ─────────────────────────────────────────────────────────────────

def _calc_sick_leave(
    avg_daily: float, days: int, year: int
) -> tuple[float, float, bool, list[str]]:
    """
    휴업급여 계산 (산재보험법 제52조, 제54조)

    최저보상기준 적용 로직:
    1단계: avg_daily × 70%
    2단계: 결과 ≤ 최저보상기준 × 80% → avg_daily × 90%
    3단계: avg_daily × 90% > 최저보상기준 × 80% → 최저보상기준 × 80%
    4단계: 위 금액 < 최저임금 일급 → 최저임금 일급
    """
    formulas: list[str] = []
    min_comp_applied = False

    base = avg_daily * SICK_LEAVE_RATE  # 70%
    min_comp = MIN_COMPENSATION_DAILY.get(year, MIN_COMPENSATION_DAILY[max(MIN_COMPENSATION_DAILY.keys())])
    min_comp_80 = min_comp * MIN_COMP_THRESHOLD

    min_wage_daily = MINIMUM_HOURLY_WAGE.get(year, MINIMUM_HOURLY_WAGE[max(MINIMUM_HOURLY_WAGE.keys())]) * 8

    daily = base
    formulas.append(f"기본 휴업급여: {avg_daily:,.0f}원 × 70% = {base:,.0f}원")

    if base <= min_comp_80:
        daily_90 = avg_daily * SICK_LEAVE_LOW_RATE
        if daily_90 > min_comp_80:
            daily = min_comp_80
            formulas.append(
                f"90%({daily_90:,.0f}원) > 최저보상기준 80%({min_comp_80:,.0f}원) "
                f"→ 최저보상기준 80% 적용"
            )
        else:
            daily = daily_90
            formulas.append(
                f"90%({daily_90:,.0f}원) ≤ 최저보상기준 80%({min_comp_80:,.0f}원) "
                f"→ 90% 적용"
            )
        min_comp_applied = True

    if daily < min_wage_daily:
        daily = min_wage_daily
        formulas.append(f"최저임금 일급({min_wage_daily:,.0f}원) 하한 적용")
        min_comp_applied = True

    total = daily * days
    formulas.append(f"휴업급여 총액: {daily:,.0f}원 × {days}일 = {total:,.0f}원")

    return daily, total, min_comp_applied, formulas


def _calc_illness_pension(
    avg_daily: float, grade: int
) -> tuple[float, float, list[str]]:
    """상병보상연금 계산 (산재보험법 제66조)"""
    days = SEVERE_ILLNESS_DAYS.get(grade, 0)
    if days == 0:
        return 0, 0, []

    daily = avg_daily  # 100% 기준
    annual = daily * days
    formulas = [
        f"상병보상연금 (제{grade}급): "
        f"{avg_daily:,.0f}원 × {days}일 = {annual:,.0f}원/년",
    ]
    return daily, annual, formulas


def _calc_disability(
    avg_daily: float, grade: int, prefer_pension: bool
) -> tuple[float, str, int, list[str], list[str]]:
    """
    장해급여 계산 (산재보험법 제57조)

    Returns: (금액, 지급형태, 적용일수, formulas, warnings)
    """
    if grade < 1 or grade > 14:
        return 0, "", 0, [], []

    pension_days, lump_days, pay_type = DISABILITY_GRADE_TABLE[grade]
    formulas: list[str] = []
    warnings: list[str] = []

    if pay_type == "pension_only":
        days = pension_days
        dtype = "연금"
        amount = avg_daily * days
        formulas.append(
            f"장해급여 (제{grade}급, 연금): "
            f"{avg_daily:,.0f}원 × {days}일 = {amount:,.0f}원/년"
        )
        if not prefer_pension:
            warnings.append(
                f"제{grade}급은 연금만 가능합니다 (일시금 선택 불가)"
            )

    elif pay_type == "lump_sum":
        days = lump_days
        dtype = "일시금"
        amount = avg_daily * days
        formulas.append(
            f"장해급여 (제{grade}급, 일시금): "
            f"{avg_daily:,.0f}원 × {days}일 = {amount:,.0f}원"
        )

    else:  # "choice" — 4~7급
        if prefer_pension:
            days = pension_days
            dtype = "연금"
            amount = avg_daily * days
            formulas.append(
                f"장해급여 (제{grade}급, 연금 선택): "
                f"{avg_daily:,.0f}원 × {days}일 = {amount:,.0f}원/년"
            )
        else:
            days = lump_days
            dtype = "일시금"
            amount = avg_daily * days
            formulas.append(
                f"장해급여 (제{grade}급, 일시금 선택): "
                f"{avg_daily:,.0f}원 × {days}일 = {amount:,.0f}원"
            )

    return amount, dtype, days, formulas, warnings


def _calc_survivor(
    avg_daily: float, num: int, prefer_pension: bool
) -> tuple[float, str, float, list[str]]:
    """유족급여 계산 (산재보험법 제62조)"""
    if num <= 0:
        return 0, "", 0, []

    formulas: list[str] = []

    if prefer_pension:
        ratio = min(
            SURVIVOR_BASE_RATIO + SURVIVOR_ADD_RATIO * num,
            SURVIVOR_MAX_RATIO,
        )
        amount = avg_daily * 365 * ratio
        formulas.append(
            f"유족보상연금: {avg_daily:,.0f}원 × 365일 × {ratio*100:.0f}% "
            f"(47% + {num}명×5%) = {amount:,.0f}원/년"
        )
        return amount, "연금", ratio, formulas
    else:
        amount = avg_daily * SURVIVOR_LUMP_SUM_DAYS
        formulas.append(
            f"유족보상일시금: {avg_daily:,.0f}원 × {SURVIVOR_LUMP_SUM_DAYS}일 "
            f"= {amount:,.0f}원"
        )
        return amount, "일시금", 0, formulas


def _calc_funeral(
    avg_daily: float, year: int
) -> tuple[float, list[str]]:
    """장례비 계산 (산재보험법 제71조)"""
    raw = avg_daily * FUNERAL_DAYS
    max_amt, min_amt = FUNERAL_LIMITS.get(
        year, FUNERAL_LIMITS[max(FUNERAL_LIMITS.keys())]
    )

    if raw > max_amt:
        amount = max_amt
        note = f"최고액 적용 ({max_amt:,.0f}원)"
    elif raw < min_amt:
        amount = min_amt
        note = f"최저액 적용 ({min_amt:,.0f}원)"
    else:
        amount = raw
        note = "120일분 적용"

    formulas = [
        f"장례비: {avg_daily:,.0f}원 × {FUNERAL_DAYS}일 = {raw:,.0f}원 → {note}"
    ]
    return amount, formulas
