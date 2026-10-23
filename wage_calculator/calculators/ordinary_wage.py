"""
통상임금 계산 엔진

통상임금은 모든 수당(연장·야간·휴일·퇴직금·연차수당 등)의 기반이 됩니다.
판단 기준: 정기성 + 일률성 (대법원 2013다4174)
※ 고정성 요건은 대법원 2023다302838 (2024.12.19) 판결로 폐기됨
  → 재직조건·소정근로일수 이내 조건부 수당도 통상임금 인정 가능
  → AllowanceCondition.EMPLOYMENT / ATTENDANCE 조건부 수당을 자동 포함 처리
"""

from dataclasses import dataclass
from ..models import WageInput, WageType, WorkType
from ..constants import MONTHLY_STANDARD_HOURS, SHIFT_MONTHLY_HOURS, WEEKLY_HOLIDAY_MIN_HOURS
from ..utils import WEEKS_PER_MONTH, WEEKS_PER_MONTH_LABEL, fmt_hours
from .shared import AllowanceClassifier, holiday_divisor, normalize_allowances, split_note
from .shared import weekly_holiday_hours as paid_weekly_holiday_hours


@dataclass
class OrdinaryWageResult:
    """통상임금 계산 결과"""
    hourly_ordinary_wage: float          # 통상시급 (원/시간)
    daily_ordinary_wage: float           # 1일 통상임금 (원/일)
    monthly_ordinary_wage: float         # 월 통상임금 총액 (원)
    monthly_base_hours: float            # 적용된 월 기준시간
    base_hours_detail: str               # 월 기준시간 산출 근거
    included_items: list                 # 통상임금 포함 항목 목록
    excluded_items: list                 # 통상임금 제외 항목 목록
    formula: str                         # 계산식 설명
    # 이름으로 통상임금에서 뺀 고정수당(연장·연차수당 등)의 월액 합계 — 통상임금은 아니어도 매월 받는 돈이라 카드의
    # '월 총 예상 수령액'에는 넣는다(Act-4 리뷰 L8)
    not_ordinary_fixed_total: float = 0.0
    # 1일 통상임금에 곱한 1일 소정근로시간(시행령 제6조 제3항) — 퇴직금 '통상임금 환산' 표기가 같은 값을 쓴다(F2)
    daily_hours_used: float = 8.0


def calc_ordinary_wage(inp: WageInput) -> OrdinaryWageResult:
    """
    임금 형태별 통상시급 산출

    계산 순서:
    1. 기준 월 근로시간 결정 (교대근무 여부 확인)
    2. 임금 형태 → 기본 통상임금 환산
    3. 고정수당(fixed_allowances) 중 통상임금 포함분 합산
    4. 월 통상임금 / 기준시간 = 통상시급
    """
    base_hours, base_hours_detail = _get_base_hours(inp)
    # 방어: 소정근로시간이 0/음수(예: 주 0일·일 0시간 입력)면 법정 기준시간으로 폴백.
    # 통상임금은 모든 계산의 기반이라 여기서 ZeroDivisionError가 나면 전체 계산기가 마비된다.
    if not base_hours or base_hours <= 0:
        base_hours = MONTHLY_STANDARD_HOURS
        base_hours_detail += f" → 유효하지 않은 근로시간, 기본 {MONTHLY_STANDARD_HOURS:.0f}h로 대체"
    included_items = []
    excluded_items = []

    # ── Step 1: 기본 통상임금 산출 ───────────────────────────────────────────
    if inp.wage_type == WageType.HOURLY:
        hourly = inp.hourly_wage or 0.0
        monthly_base = hourly * base_hours
        formula = f"시급 {hourly:,.0f}원 × {fmt_hours(base_hours)}h = {monthly_base:,.0f}원"
        included_items.append(f"기본 시급: {hourly:,.0f}원")

    elif inp.wage_type == WageType.DAILY:
        daily = inp.daily_wage or 0.0
        daily_hours = inp.schedule.daily_work_hours or 8.0
        hourly = daily / daily_hours
        monthly_base = hourly * base_hours
        formula = (f"일급 {daily:,.0f}원 ÷ {fmt_hours(daily_hours)}h = 시급 {hourly:,.0f}원"
                   f" × {fmt_hours(base_hours)}h = {monthly_base:,.0f}원")
        included_items.append(f"기본 일급: {daily:,.0f}원")

    elif inp.wage_type == WageType.MONTHLY:
        monthly_base = inp.monthly_wage or 0.0
        formula = f"월 기본급: {monthly_base:,.0f}원"
        included_items.append(f"월 기본급: {monthly_base:,.0f}원")

    elif inp.wage_type == WageType.ANNUAL:
        annual = inp.annual_wage or 0.0
        monthly_base = annual / 12
        formula = f"연봉 {annual:,.0f}원 ÷ 12 = {monthly_base:,.0f}원"
        included_items.append(f"연봉 월 환산: {monthly_base:,.0f}원")

    elif inp.wage_type == WageType.COMPREHENSIVE:
        # 포괄임금제: breakdown이 있으면 base만 사용, 없으면 총액 사용
        if inp.comprehensive_breakdown:
            monthly_base = inp.comprehensive_breakdown.get("base", inp.monthly_wage or 0.0)
            formula = f"포괄임금 중 기본급: {monthly_base:,.0f}원"
        else:
            monthly_base = inp.monthly_wage or 0.0
            formula = f"포괄임금 총액(기본급 구분 없음): {monthly_base:,.0f}원"
        included_items.append(f"포괄임금 기본급: {monthly_base:,.0f}원")

    else:
        monthly_base = 0.0
        formula = "임금 형태 미확인"

    # ── Step 2: 고정수당 중 통상임금 포함분 합산 ─────────────────────────────
    # 대법원 2023다302838: 재직조건·근무일수 조건부도 통상임금 포함 가능
    allowance_total = 0.0
    allowance_terms = []
    excluded_brief: list[str] = []
    excluded_notes: list[str] = []
    not_ordinary_fixed_total = 0.0
    allowances = normalize_allowances(inp.fixed_allowances)
    for a in allowances:
        is_ordinary, note = _resolve_is_ordinary_fa(a)

        # 최소보장 성과급: guaranteed_amount가 있으면 그 금액만 산입
        if a.condition == "최소보장성과" and is_ordinary:
            guaranteed = a.guaranteed_amount if a.guaranteed_amount is not None else a.amount
            effective_amount = min(max(0, guaranteed), a.amount)
        else:
            effective_amount = a.amount

        monthly_amount = a.monthly_amount * effective_amount / a.amount if a.amount else a.monthly_amount

        if is_ordinary:
            allowance_total += monthly_amount
            allowance_terms.append(f"{a.name} 월 환산 {monthly_amount:,.0f}원")
            label = f"{a.name}: {monthly_amount:,.0f}원/월"
            if note:
                label += f" ({note})"
            included_items.append(label)
        else:
            label = f"{a.name}: {monthly_amount:,.0f}원/월 (통상임금 제외)"
            if note:
                label += f" — {note}"
            excluded_items.append(label)
            excluded_brief.append(f"{a.name} {monthly_amount:,.0f}원")
            if note == NOT_ORDINARY_NOTE:
                not_ordinary_fixed_total += monthly_amount
            if note and note not in excluded_notes:
                excluded_notes.append(note)

    monthly_ordinary = monthly_base + allowance_total

    if allowance_total > 0:
        terms = (" + ".join(allowance_terms) if any(a.annual or a.payment_cycle != "매월" for a in allowances)
                 else f"통상임금 포함 수당 {allowance_total:,.0f}원")
        formula += f" + {terms} = {monthly_ordinary:,.0f}원"
    if excluded_brief:
        # 제외한 수당을 밝힌다 — 질문에 적힌 수당이 계산식에서 말없이 사라지면 빠뜨린 것처럼 읽힌다
        reasons = f" — {'; '.join(excluded_notes)}" if excluded_notes else ""
        formula += f" (통상임금 제외: {', '.join(excluded_brief)}{reasons})"

    for a in allowances:
        if a.annual or a.payment_cycle != "매월":
            cycle = "연간 총액" if a.annual else f"{a.payment_cycle} 지급 회차액"
            formula += f"; {a.name}: {cycle} {a.amount:,.0f}원 → 월 환산 {a.monthly_amount:,.0f}원 (동일 항목의 환산)"

    hourly_ordinary = monthly_ordinary / base_hours
    daily_work_hours = inp.schedule.daily_work_hours or 8.0
    daily_ordinary = hourly_ordinary * daily_work_hours

    return OrdinaryWageResult(
        hourly_ordinary_wage=round(hourly_ordinary, 2),
        daily_ordinary_wage=round(daily_ordinary, 0),
        monthly_ordinary_wage=round(monthly_ordinary, 0),
        monthly_base_hours=base_hours,
        daily_hours_used=daily_work_hours,
        base_hours_detail=base_hours_detail,
        included_items=included_items,
        excluded_items=excluded_items,
        formula=formula,
        not_ordinary_fixed_total=not_ordinary_fixed_total,
    )


NOT_ORDINARY_NOTE = "소정근로의 대가가 아닌 연장·야간·휴일근로·연차수당(근로기준법 시행령 제6조 제1항)"


def _resolve_is_ordinary_fa(allowance) -> tuple[bool, str]:
    """
    수당의 통상임금 포함 여부 결정 (대법원 2023다302838 반영)
    FixedAllowance 속성 접근 방식 사용

    Returns:
        (is_ordinary, note) — note는 판결 적용 시 설명 문자열
    """
    condition = allowance.condition
    explicit = allowance.is_ordinary
    name = allowance.name

    # 성과조건: 통상임금 제외 (명시적으로 포함 설정해도 경고)
    if condition == "성과조건":
        if explicit is True:
            return False, "성과조건부로 통상임금 제외 처리 (명시 설정 무시)"
        return False, ""

    # 연장·야간·휴일근로·연차수당은 조건과 무관하게 제외 — 고정 지급이어도 통상임금으로 계산하는 수당이다(근로기준법 제56조·
    # 제60조 제5항). 의도분석이 고정수당으로 뽑으면 조건 '없음'으로 와서 통상시급·연장수당이 부풀었다(audit-50 Act-4).
    # 명시적으로 포함한 값만 존중한다
    if explicit is not True and AllowanceClassifier.is_not_ordinary_by_name(name):
        return False, NOT_ORDINARY_NOTE

    # 최소보장 성과급: 보장분만 통상임금 포함 (대법원 2023다302838)
    if condition == "최소보장성과":
        if explicit is False:
            return False, "명시적 제외 설정"
        return True, "최소보장분 통상임금 포함 (대법원 2023다302838)"

    # 재직조건·근무일수 조건: 2023다302838 판결로 통상임금 인정
    if condition in ["재직조건", "근무일수"]:
        if explicit is False:
            return True, f"재직/근무일수 조건부이나 대법원 2023다302838에 따라 통상임금 포함"
        return True, ""

    # 조건 없음(기본): 명시적 설정 우선, 없으면 True
    return (explicit if explicit is not None else True), ""


def _get_base_hours(inp: WageInput) -> tuple[float, str]:
    """
    월 기준시간 결정 (주휴시간 포함)

    우선순위:
    1. monthly_scheduled_hours 명시값
    2. shift_monthly_hours (교대근무 직접 지정)
    3. 교대근무 유형별 조회
    4. 스케줄 기반 자동 계산: (주 소정근로 + 주휴시간) × WEEKS_PER_MONTH
       - 주휴시간 = shared.weekly_holiday_hours(주휴수당 계산기와 같은 함수, 대법원 2022다291153)
       - 주 15시간 미만이면 주휴 0

    Returns:
        (월 기준시간, 계산 근거 문자열)
    """
    # 1) 명시적 월 소정근로시간
    if inp.schedule.monthly_scheduled_hours is not None:
        h = inp.schedule.monthly_scheduled_hours
        return h, f"월 소정근로시간(직접 입력): {h}h"

    # 2) 교대근무: shift_monthly_hours 직접 지정
    if inp.schedule.shift_monthly_hours is not None:
        h = inp.schedule.shift_monthly_hours
        return h, f"교대근무 월 소정근로시간(직접 입력): {h}h"

    # 3) 교대근무 유형에서 조회
    shift_key_map = {
        WorkType.SHIFT_4_2: "4조2교대",
        WorkType.SHIFT_3_2: "3조2교대",
        WorkType.SHIFT_3:   "3교대",
        WorkType.SHIFT_2:   "2교대",
    }
    if inp.work_type in shift_key_map:
        key = shift_key_map[inp.work_type]
        h = SHIFT_MONTHLY_HOURS.get(key, MONTHLY_STANDARD_HOURS)
        return h, f"{key} 월 소정근로시간: {h}h"

    # 4) 일반: 스케줄 기반 자동 계산
    s = inp.schedule
    weekly_work_hours = s.daily_work_hours * s.weekly_work_days
    if weekly_work_hours >= WEEKLY_HOLIDAY_MIN_HOURS:
        # 주휴수당 계산기와 같은 함수 — 여기만 '÷5'를 따로 쓰던 때 주 6일 × 4.1667h 카드에 기준시간 주휴 5h와 주휴수당
        # 4.1667h가 함께 실렸다(외부 점검 40번 후속)
        weekly_holiday_hours, _ = paid_weekly_holiday_hours(s.weekly_work_days, s.daily_work_hours)
        divisor = holiday_divisor(s.weekly_work_days)
        holiday_detail = (f"min({fmt_hours(weekly_work_hours)}h÷{fmt_hours(divisor)}"
                          f"{'일' if s.weekly_work_days >= 5 else ''}, 8h) = {fmt_hours(weekly_holiday_hours)}h")
    else:
        weekly_holiday_hours = 0.0
        holiday_detail = f"0h (주 {fmt_hours(weekly_work_hours)}h < {WEEKLY_HOLIDAY_MIN_HOURS}h)"
    total_weekly = weekly_work_hours + weekly_holiday_hours
    # 반올림하지 않는다 — 월 기준시간 = 1주 기준시간 × 1년 평균 주 수 ÷ 12(근로기준법 시행령 제6조②4호·최저임금법 시행령
    # 제5조①3호, 둘 다 반올림 규정 없음).
    # 소수 첫째 자리로 반올림해 계산하면 단시간 근로자 월 환산액이 달라졌다(83.4286h → 83.4h: 860,983원 → 860,688원, 외부 점검 #45)
    monthly_hours = total_weekly * WEEKS_PER_MONTH

    # 1일 8시간·1주 40시간을 넘는 시간은 이미 연장근로로 나눴다(apply_hour_split) — 원래 시간과 나눈 결과를 함께 밝힌다
    note = split_note(getattr(inp, "hour_split", None))
    lead = (note if note else
            f"주 소정근로: {fmt_hours(s.daily_work_hours)}h×{fmt_hours(s.weekly_work_days)}일 = {fmt_hours(weekly_work_hours)}h")
    detail = (
        f"{lead}, "
        f"주휴시간: {holiday_detail}, "
        f"월 환산: ({fmt_hours(weekly_work_hours)}h+{fmt_hours(weekly_holiday_hours)}h)×{WEEKS_PER_MONTH_LABEL} = "
        f"{fmt_hours(monthly_hours)}h"
    )
    return monthly_hours, detail
