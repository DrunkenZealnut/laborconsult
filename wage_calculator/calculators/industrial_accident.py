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

from dataclasses import dataclass, replace

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
    COMPENSATION_LIMITS_DAILY,
    ORDINARY_WORK_COEFFICIENT,
    get_minimum_hourly_wage,
)
from .ordinary_wage import OrdinaryWageResult
from .average_wage import calc_average_wage


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
    1. 평균임금 결정 (평균임금 계산기 — 산정 기준일은 재해일)
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
            "(고용보험 및 산업재해보상보험의 보험료징수 등에 관한 법률 제48조의6 제6항 — "
            "대통령령으로 정하는 일부 직종은 사업주가 전액 부담). "
            "산재 급여 산정(휴업급여·장해급여 등)은 일반 근로자와 동일합니다."
        )
        legal.append("산업재해보상보험법 제91조의15~제91조의21 (노무제공자에 대한 특례)")
        legal.append("고용보험 및 산업재해보상보험의 보험료징수 등에 관한 법률 제48조의6 (보험료 분담)")

    # ── 재해 유형별 안내 ─────────────────────────────────────────────────
    injury_type = getattr(inp, "injury_type", "") or ""

    if getattr(inp, "is_commute_injury", False) or injury_type == "출퇴근":
        warnings.append(
            "출퇴근 재해: 통상적인 경로와 방법으로 출퇴근 중 발생한 사고는 "
            "업무상 재해로 인정됩니다 (산재보험법 제37조 제1항 제3호). "
            "자가용·대중교통 모두 포함되나, 통상 경로 이탈 시 제외될 수 있습니다."
        )
        legal.append("산업재해보상보험법 제37조 제1항 제3호 (출퇴근 재해)")

    if getattr(inp, "is_traffic_accident", False) or injury_type == "사고":
        from ..constants import TRAFFIC_GROSS_NEGLIGENCE
        warnings.append(
            "교통사고 산재 인정: 업무 수행 중 교통사고는 원칙적으로 산재 인정되나, "
            "12대 중과실 사고(신호위반, 중앙선 침범, 음주운전 등)에 해당하면 "
            "불인정될 수 있습니다. 다만 불가피한 위반은 예외 인정 가능합니다."
        )
        legal.append("교통사고처리 특례법 제3조 (12대 중과실)")

    if injury_type == "뇌심혈관":
        from ..constants import (
            CEREBROVASCULAR_WEEKLY_HOURS_ACUTE,
            CEREBROVASCULAR_WEEKLY_HOURS_CAUTION,
            CEREBROVASCULAR_OBSERVATION_WEEKS,
        )
        warnings.append(
            f"뇌심혈관 질환 산재 인정 기준: 발병 전 {CEREBROVASCULAR_OBSERVATION_WEEKS}주간 "
            f"주 평균 {CEREBROVASCULAR_WEEKLY_HOURS_ACUTE}시간 이상 근무 시 인정. "
            f"주 {CEREBROVASCULAR_WEEKLY_HOURS_CAUTION}시간 초과 + 업무 가중요인"
            "(스트레스, 교대근무, 유해환경 등) 복합 시에도 인정 추세."
        )
        legal.append("고용노동부 고시 '뇌혈관 질병 또는 심장 질병의 업무상 질병 인정 여부 결정에 필요한 사항'")

    if injury_type in ("질병", "뇌심혈관"):
        # 직업병 평균임금 특례(제36조⑥·시행령 제25조) — 진폐는 고시 금액, 그 밖은 비슷한 근로자의 월평균 임금총액. 공단이 적용하고
        # 계산기는 재현할 수 없어 안내만 한다(calculator-statute-audit D9)
        warnings.append("직업병(진폐 등)은 공단이 평균임금 산정 특례를 적용할 수 있습니다 — 진폐는 매년 고시하는 금액, 그 밖의 직업병은 "
                        "성별·직종·업종·규모가 비슷한 근로자의 월평균 임금총액 기준(산재보험법 제36조 제6항, 시행령 제25조). "
                        "이 카드는 일반 평균임금으로 계산했습니다.")
        legal.append("산업재해보상보험법 제36조 제6항·시행령 제25조 (직업병 평균임금 산정 특례)")

    # ── 1. 평균임금 결정 ──────────────────────────────────────────────────
    # 산재보험의 평균임금은 근로기준법의 평균임금이다(산재보험법 제5조 제2호) — 평균임금 계산기 하나로 구한다(monthly-base-unification).
    # 분모는 3개월 총일수(근로기준법 제2조 제1항 제6호), 평균임금이 통상임금보다 적으면 통상임금(제2조 제2항). 산정 사유 발생일은
    # 사고가 발생한 날이다(근로기준법 시행령 제52조). 예전에는 '월 금액 ÷ 30'과 1일 통상임금 중 큰 쪽이었다
    is_daily = bool(getattr(inp, "is_daily_worker", False))
    daily_wage = getattr(inp, "daily_wage", None)
    use_coefficient = is_daily and bool(daily_wage) and not _continued_three_months(inp)
    if use_coefficient:
        # 1-1. 일용근로자: 일당 × 통상근로계수(제36조⑤, 시행령 제23조·제24조①1호, 고용노동부고시 제2025-90호 73/100 —
        #      calculator-statute-audit D8). 3개월 이상 계속 근로면 일용으로 보지 않아 일반 평균임금(제23조①1호 단서 가목)
        avg_daily = float(daily_wage) * ORDINARY_WORK_COEFFICIENT
        formulas.append(f"평균임금(일용근로자): 일당 {float(daily_wage):,.0f}원 × 통상근로계수 73/100 = {avg_daily:,.0f}원 "
                        "(산재보험법 제36조 제5항, 시행령 제23조·제24조, 고용노동부고시 제2025-90호)")
        warnings.append("근로관계가 3개월 이상 계속되거나 근로 형태가 상용근로자와 비슷하면 일용근로자로 보지 않고 일반 평균임금으로 "
                        "산정합니다(시행령 제23조 제1항 제1호 단서). 1개월 이상 근로한 일용근로자는 실제 임금·근로일수로 적용 "
                        "제외를 신청할 수 있습니다(제24조 제2항).")
        legal.append("산업재해보상보험법 제36조 제5항·시행령 제23조·제24조 (일용근로자 평균임금 — 통상근로계수)")
    else:
        avg = calc_average_wage(replace(inp, end_date=inp.accident_date or inp.end_date), ow)
        if avg.held_reason:
            return IndustrialAccidentResult(held_reason=avg.held_reason, warnings=avg.warnings)
        avg_daily = avg.avg_daily_wage
        if avg.used_basis == "통상임금":
            formulas.append(f"평균임금: {avg_daily:,.0f}원/일 (3개월 평균임금 {avg.avg_daily_3m:,.0f}원 < 1일 통상임금 "
                            f"{avg.avg_daily_ordinary:,.0f}원 → 통상임금, 근로기준법 제2조 제2항)")
            legal.append("근로기준법 제2조 제2항 (평균임금이 통상임금보다 적으면 통상임금)")
        else:
            formulas.append(f"평균임금: {avg_daily:,.0f}원/일 (3개월 기준)")
        if is_daily and not daily_wage:
            warnings.append("일용근로자의 산재 평균임금은 일당 × 통상근로계수(73/100)로 산정합니다(시행령 제24조 제1항 제1호) — "
                            "일당을 알면 그 기준으로 계산합니다. 이 카드는 일반 평균임금입니다.")
        elif is_daily:
            warnings.append("근로관계가 3개월 이상 계속돼 일용근로자 특례(통상근로계수)를 적용하지 않고 일반 평균임금으로 산정했습니다"
                            "(시행령 제23조 제1항 제1호 단서 가목).")
    if inp.accident_date:
        legal.append("근로기준법 시행령 제52조 (재해보상 시의 평균임금 산정 사유 발생일)")

    # ── 1-2. 최고·최저 보상기준(제36조⑦) — 장례비 외 급여의 평균임금 상한, 장해·유족급여의 하한 ────────────────────
    # 휴업급여·상병보상연금에는 최저를 적용하지 않는다(단서). 장례비는 자체 최고·최저(제71조②)가 있어 제외다(calculator-statute-audit D5).
    comp_high, comp_low = _compensation_limits(year)
    avg_capped = avg_daily
    if comp_high is not None and avg_daily > comp_high:
        avg_capped = comp_high
        formulas.append(
            f"최고 보상기준 금액 적용: 평균임금 {avg_daily:,.0f}원 > {comp_high:,.0f}원 → 휴업·장해·유족·상병보상연금은 "
            f"{comp_high:,.0f}원으로 산정(산재보험법 제36조 제7항, 장례비 제외)"
        )
        legal.append("산업재해보상보험법 제36조 제7항 (최고·최저 보상기준 금액)")
    elif comp_high is None and avg_daily > comp_low * 3.6:
        # 최고/최저 = 1.8배 ÷ 1/2 = 3.6배(제36조⑦) — 최저만 아는 해에 최고를 넘었을 가능성이 큰 구간만 알린다
        warnings.append(
            f"{year}년 최고 보상기준 금액을 확인하지 못했습니다 — 평균임금이 전체 근로자 임금 평균액의 1.8배를 넘으면 그 금액으로 "
            "제한됩니다(산재보험법 제36조 제7항). 이 카드는 상한 없이 계산했습니다."
        )
    avg_floor = avg_capped
    if avg_capped < comp_low:
        avg_floor = comp_low
        formulas.append(
            f"최저 보상기준 금액 적용: 평균임금 {avg_daily:,.0f}원 < {comp_low:,.0f}원 → 장해·유족급여는 {comp_low:,.0f}원으로 "
            "산정(산재보험법 제36조 제7항 — 휴업급여·상병보상연금에는 적용하지 않음)"
        )
        if "산업재해보상보험법 제36조 제7항 (최고·최저 보상기준 금액)" not in legal:
            legal.append("산업재해보상보험법 제36조 제7항 (최고·최저 보상기준 금액)")

    total_compensation = 0.0
    breakdown: dict = {"적용 평균임금": f"{avg_daily:,.0f}원/일"
                       + (f" (휴업·상병 {avg_capped:,.0f}원, 장해·유족 {avg_floor:,.0f}원 — 보상기준 적용)"
                          if (avg_capped, avg_floor) != (avg_daily, avg_daily) else "")}

    # ── 2. 휴업급여 ───────────────────────────────────────────────────────
    sl_daily, sl_total, sl_min = 0.0, 0.0, False
    if inp.sick_leave_days > 0:
        sl_daily, sl_total, sl_min, sl_f, sl_w, sl_l = _calc_sick_leave(
            avg_capped, inp.sick_leave_days, year, age=getattr(inp, "age", 0) or 0
        )
        total_compensation += sl_total
        formulas.extend(sl_f)
        warnings.extend(sl_w)
        legal.extend(l for l in sl_l if l not in legal)
        breakdown["휴업급여"] = (
            f"{sl_daily:,.0f}원/일 × {inp.sick_leave_days}일 = {sl_total:,.0f}원"
            if sl_total else f"0원 (요양 {inp.sick_leave_days}일 ≤ 3일 — 제52조 단서)"
        )

    # ── 3. 상병보상연금 ───────────────────────────────────────────────────
    il_daily, il_annual = 0.0, 0.0
    if inp.severe_illness_grade > 0:
        il_daily, il_annual, il_f = _calc_illness_pension(
            avg_capped, inp.severe_illness_grade
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
            avg_floor, inp.disability_grade, inp.disability_pension
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
            avg_floor, inp.num_survivors, inp.survivor_pension
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

def _continued_three_months(inp: WageInput) -> bool:
    """입사일과 재해일(없으면 퇴직일)이 있고 그 사이가 3개월 이상이면 True — 시행령 제23조①1호 단서 가목(일용으로 보지 않음)."""
    end = inp.accident_date or inp.end_date
    if not inp.start_date or not end:
        return False
    from .shared import DateRange
    return DateRange(inp.start_date, end).months_approx >= 3


def _compensation_limits(year: int) -> tuple[float | None, float]:
    """(최고, 최저) 보상기준 금액. 최저는 최저임금액(시급 × 8)과 비교해 큰 쪽(제36조⑦ 후단). 표에 없는 해는 (None, 최저임금액)."""
    high, low = COMPENSATION_LIMITS_DAILY.get(year, (None, 0.0))
    return high, max(float(low), get_minimum_hourly_wage(year) * 8)


# 61세 이후 휴업급여 계수(산재보험법 제55조·별표 1) — {연령: (제52조 기준 n/70, 제54조 기준 n/90)}, 65세 이후는 (50, 70)
_SENIOR_FACTORS: dict[int, tuple[int, int]] = {61: (66, 86), 62: (62, 82), 63: (58, 78), 64: (54, 74)}
_SENIOR_FACTOR_65 = (50, 70)


def _senior_factor(age: int) -> tuple[int, int] | None:
    """만 나이가 61세 이상이면 별표 1 계수 (n70, n90). 모르거나(0) 60세 이하면 None."""
    if not age or age < 61:
        return None
    return _SENIOR_FACTORS.get(age, _SENIOR_FACTOR_65)


def _calc_sick_leave(
    avg_daily: float, days: int, year: int, age: int = 0
) -> tuple[float, float, bool, list[str], list[str], list[str]]:
    """
    휴업급여 계산 (산재보험법 제52조·제54조·제55조)

    Returns: (1일 지급액, 총액, 최저보상기준 적용 여부, formulas, warnings, legal)

    1단계: 요양 3일 이내면 미지급(제52조 단서) — 사용자의 요양보상·휴업보상(근로기준법 제78조·제79조)
    2단계: avg_daily × 70% (제52조)
    3단계: 결과 ≤ 최저보상기준 × 80% → avg_daily × 90% (제54조① 본문); 90%가 최저보상기준 × 80%보다 많으면 최저보상기준 × 80% (제54조① 단서)
    4단계: 위 금액 < 최저임금액(시급 × 8) → 최저임금액 (제54조②)
    5단계: 61세 이후면 별표 1 계수 — 제52조 기준은 n/70, 제54조 기준은 n/90(단서 기준은 최저보상 × 80% × n/90).
          제52조 기준 금액이 제3호(단서 기준) 금액보다 적으면 제3호 금액(별표 1 제1호 단서)
    avg_daily는 호출부가 최고 보상기준으로 자른 값이다(제36조⑦ — 최저 보상기준은 휴업급여에 적용하지 않는다).
    """
    formulas: list[str] = []
    warnings: list[str] = []
    legal: list[str] = []
    if days <= 3:
        formulas.append(
            f"휴업급여: 취업하지 못한 기간 {days}일 ≤ 3일 → 산재 휴업급여 미지급(산재보험법 제52조 단서). "
            "이 기간은 사업주가 요양보상·휴업보상(평균임금의 60%)을 합니다(근로기준법 제78조·제79조)"
        )
        legal.append("근로기준법 제78조·제79조 (사용자의 요양보상·휴업보상)")
        return 0.0, 0.0, False, formulas, warnings, legal

    min_comp_applied = False
    base = avg_daily * SICK_LEAVE_RATE  # 70%
    min_comp = MIN_COMPENSATION_DAILY.get(year, MIN_COMPENSATION_DAILY[max(MIN_COMPENSATION_DAILY.keys())])
    min_comp_80 = min_comp * MIN_COMP_THRESHOLD
    min_wage_daily = get_minimum_hourly_wage(year) * 8

    daily = base
    route = "base70"                       # 제52조
    formulas.append(f"기본 휴업급여: {avg_daily:,.0f}원 × 70% = {base:,.0f}원")

    if base <= min_comp_80:
        daily_90 = avg_daily * SICK_LEAVE_LOW_RATE
        if daily_90 > min_comp_80:
            daily = min_comp_80
            route = "low_min80"            # 제54조① 단서
            formulas.append(f"90%({daily_90:,.0f}원) > 최저보상기준 80%({min_comp_80:,.0f}원) → 최저보상기준 80% 적용")
        else:
            daily = daily_90
            route = "low90"                # 제54조① 본문
            formulas.append(f"90%({daily_90:,.0f}원) ≤ 최저보상기준 80%({min_comp_80:,.0f}원) → 90% 적용")
        min_comp_applied = True

    if daily < min_wage_daily:
        daily = min_wage_daily
        route = "min_wage"                 # 제54조②
        formulas.append(f"최저임금 일급({min_wage_daily:,.0f}원) 하한 적용")
        min_comp_applied = True

    factor = _senior_factor(age)
    if factor:
        n70, n90 = factor
        if route == "base70":
            reduced = daily * n70 / 70
            floor3 = min_comp_80 * n90 / 90          # 별표 1 제1호 단서 — 제3호 금액보다 적으면 제3호
            daily, label = max(reduced, floor3), f"{n70}/70"
        else:
            daily, label = daily * n90 / 90, f"{n90}/90"
        formulas.append(f"고령자 감액(만 {age}세): 1일 휴업급여 × {label} = {daily:,.0f}원 (산재보험법 제55조·별표 1)")
        warnings.append(
            f"61세 이후 휴업급여는 별표 1에 따라 감액됩니다(만 {age}세 계수 {label}). 각 연령에 도달하는 날부터 계수가 바뀌며, "
            "61세 이후 취업 중 재해 등 제55조 단서 사유는 일정 기간 감액하지 않습니다."
        )
        legal.append("산업재해보상보험법 제55조·별표 1 (고령자의 휴업급여)")

    daily = round(daily)
    total = daily * days
    formulas.append(f"휴업급여 총액: {daily:,.0f}원 × {days}일 = {total:,.0f}원")
    return daily, total, min_comp_applied, formulas, warnings, legal


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
