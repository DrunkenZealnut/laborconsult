"""
탄력적 근로시간제 연장수당 계산기 (근로기준법 제51조~제51조의3)

핵심 개념:
  탄력적 근로시간제 = 단위기간 내 총 실근로를 평균하여 법정 기준 판단
  단위기간: 2주 / 3개월 / 6개월

  탄력제 연장근로 = 단위기간 총 실근로 - (40h × 단위기간 주 수)
  → 주별 합산이 아닌 단위기간 전체 평균으로 판단

  추가 가산 조건:
    특정 주 실근로 > 명시된 최대 근로시간 (2주 단위: 48h / 3,6개월: 52h)
    또는 단위기간 내 주 평균 > 40h

  5인 미만 사업장: 가산수당 미적용
"""

from dataclasses import dataclass

from ..base import BaseCalculatorResult
from ..utils import WEEKS_PER_MONTH
from typing import Optional
from ..models import WageInput, BusinessSize
from .ordinary_wage import OrdinaryWageResult
from ..constants import OVERTIME_RATE

# ── 탄력적 근로시간제 단위기간별 최대 근로한도 ────────────────────────────────
FLEXIBLE_WORK_LIMITS = {
    "2주":   {"weeks": 2,   "max_per_week": 48, "max_avg": 40},
    "3개월": {"weeks": 13,  "max_per_week": 52, "max_avg": 40},
    "6개월": {"weeks": 26,  "max_per_week": 52, "max_avg": 40},
}


@dataclass
class FlexibleWorkResult(BaseCalculatorResult):
    # 단위기간 정보
    unit_period: str = ""                      # "2주", "3개월", "6개월"
    unit_weeks: int = 0                        # 단위기간 주 수
    total_actual_hours: float = 0.0            # 단위기간 총 실근로시간

    # 연장수당 계산
    legal_hours: float = 0.0                   # 법정 기준 총시간 (40h × 주수)
    overtime_hours: float = 0.0                # 연장근로시간 (총 초과분)
    overtime_pay_per_period: float = 0.0       # 단위기간 연장수당 합계
    monthly_overtime_pay: float = 0.0          # 월 환산 연장수당

    # 주별 한도 초과 (추가 가산 필요 주)
    weeks_exceeding_limit: int = 0             # 주별 최대 한도 초과 주 수
    extra_premium_pay: float = 0.0             # 추가 가산수당


def calc_flexible_work(inp: WageInput, ow: OrdinaryWageResult) -> FlexibleWorkResult:
    """
    탄력적 근로시간제 연장수당 계산

    Args:
        inp: 임금 입력 데이터
          - flexible_work_unit: "2주", "3개월", "6개월"
          - weekly_hours_list: 단위기간 내 주별 실근로시간 리스트
        ow: 통상임금 계산 결과
    """
    warnings = []
    formulas = []
    legal = [
        "근로기준법 제51조 (탄력적 근로시간제 — 2주 단위)",
        "근로기준법 제51조의2 (탄력적 근로시간제 — 3개월 단위)",
        "근로기준법 제51조의3 (탄력적 근로시간제 — 6개월 단위)",
    ]

    hourly = ow.hourly_ordinary_wage
    is_small = inp.business_size == BusinessSize.UNDER_5

    unit = getattr(inp, "flexible_work_unit", "") or ""
    weekly_hours_list = getattr(inp, "weekly_hours_list", None) or []

    # ── 단위기간 설정 ─────────────────────────────────────────────────────
    if unit not in FLEXIBLE_WORK_LIMITS:
        unit = "2주"
        warnings.append(f"탄력근로 단위기간 미설정 — '2주' 기준 적용")

    config = FLEXIBLE_WORK_LIMITS[unit]
    unit_weeks    = config["weeks"]
    max_per_week  = config["max_per_week"]
    max_avg_hours = config["max_avg"]

    # ── 주별 실근로 데이터 처리 ───────────────────────────────────────────
    if not weekly_hours_list:
        # weekly_hours_list 없으면 schedule 기반으로 단순 추정
        base_weekly = inp.schedule.daily_work_hours * inp.schedule.weekly_work_days
        extra_weekly = inp.schedule.weekly_overtime_hours
        weekly_hours_list = [base_weekly + extra_weekly] * unit_weeks
        warnings.append(
            f"주별 실근로시간 미입력 — 스케줄 기반 {base_weekly + extra_weekly}h/주 × {unit_weeks}주 가정"
        )
    else:
        # 리스트 길이가 unit_weeks보다 짧으면 패딩
        if len(weekly_hours_list) < unit_weeks:
            avg = sum(weekly_hours_list) / len(weekly_hours_list)
            weekly_hours_list = weekly_hours_list + [avg] * (unit_weeks - len(weekly_hours_list))
            warnings.append(
                f"주별 시간 데이터 부족 ({len(weekly_hours_list)}주 < {unit_weeks}주) — 평균값으로 보완"
            )
        elif len(weekly_hours_list) > unit_weeks:
            weekly_hours_list = weekly_hours_list[:unit_weeks]

    total_actual = sum(weekly_hours_list)
    legal_hours  = max_avg_hours * unit_weeks  # 40h × 주수

    # ── 탄력제 기준 연장근로 ─────────────────────────────────────────────
    overtime_hours = max(0.0, total_actual - legal_hours)

    formulas.append(
        f"단위기간({unit}) 총 실근로: {total_actual:.1f}h"
    )
    formulas.append(
        f"법정 기준시간: {max_avg_hours}h × {unit_weeks}주 = {legal_hours:.0f}h"
    )
    if overtime_hours > 0:
        formulas.append(
            f"탄력제 연장근로: {total_actual:.1f}h - {legal_hours:.0f}h = {overtime_hours:.1f}h"
        )
    else:
        formulas.append("탄력제 연장근로 없음 (평균 40h 이하)")

    # ── 주별 한도 초과 체크 (추가 가산 필요) ─────────────────────────────
    weeks_over = sum(1 for h in weekly_hours_list if h > max_per_week)
    extra_hours_total = sum(max(0, h - max_per_week) for h in weekly_hours_list)
    extra_premium_pay = 0.0

    if weeks_over > 0:
        # 주별 한도 초과분은 별도 가산수당 적용 (이미 수당을 받고 있는 경우)
        extra_premium_pay = hourly * extra_hours_total * OVERTIME_RATE if not is_small else 0.0
        formulas.append(
            f"주별 최대 근로한도({max_per_week}h) 초과 주: {weeks_over}주, 초과시간: {extra_hours_total:.1f}h"
        )
        if not is_small:
            formulas.append(
                f"추가 가산수당: {hourly:,.1f}원 × {extra_hours_total:.1f}h × 0.5 = {extra_premium_pay:,.0f}원"
            )
        warnings.append(
            f"⚠️ 주별 최대 근로시간({max_per_week}h) 초과 {weeks_over}주 발생 — 추가 가산수당 적용 가능"
        )

    # ── 단위기간 연장수당 ─────────────────────────────────────────────────
    if is_small:
        overtime_pay = hourly * overtime_hours  # 가산 없음 (× 1.0)
        warnings.append("5인 미만 사업장: 가산수당 미적용 (× 1.0)")
    else:
        overtime_pay = hourly * overtime_hours * (1 + OVERTIME_RATE)  # × 1.5

    if overtime_hours > 0:
        rate = 1.0 if is_small else (1 + OVERTIME_RATE)
        formulas.append(
            f"탄력제 연장수당: {hourly:,.1f}원 × {overtime_hours:.1f}h × {rate} = {overtime_pay:,.0f}원"
        )

    # ── 월 환산 ──────────────────────────────────────────────────────────
    # 단위기간 → 월 환산 (단위기간이 1개월 미만인 경우 월에 여러 기간 포함)
    months_per_period = unit_weeks / WEEKS_PER_MONTH  # 단위기간이 몇 달인지
    # 月수당 = 단위기간 수당 ÷ months_per_period (2주 단위면 0.46개월이므로 ÷0.46 = ×2.17)
    monthly_overtime = (overtime_pay + extra_premium_pay) / months_per_period

    formulas.append(
        f"월 환산: ({overtime_pay:,.0f} + {extra_premium_pay:,.0f})원 ÷ {months_per_period:.2f}개월 "
        f"= {monthly_overtime:,.0f}원/월"
    )

    # ── 주의사항 ─────────────────────────────────────────────────────────
    if unit == "2주":
        warnings.append("2주 단위 탄력제: 취업규칙에 명시 필요 (서면합의 불필요)")
    elif unit in ("3개월", "6개월"):
        warnings.append(f"{unit} 단위 탄력제: 근로자 대표와 서면합의 필수")

    warnings.append("탄력제 적용 중에도 11시간 연속휴식 보장 의무 (근로기준법 제51조의4)")

    # ── 주별 상세 ─────────────────────────────────────────────────────────
    weekly_detail = {f"제{i+1}주": f"{h:.1f}h" for i, h in enumerate(weekly_hours_list[:min(len(weekly_hours_list), 10)])}
    if len(weekly_hours_list) > 10:
        weekly_detail["..."] = f"(총 {len(weekly_hours_list)}주)"

    breakdown = {
        "단위기간": unit,
        "단위기간 주 수": f"{unit_weeks}주",
        "단위기간 총 실근로": f"{total_actual:.1f}h",
        "법정 기준시간": f"{legal_hours:.0f}h ({max_avg_hours}h × {unit_weeks}주)",
        "탄력제 연장근로": f"{overtime_hours:.1f}h",
        "탄력제 연장수당": f"{overtime_pay:,.0f}원",
        "주별 한도 초과 주": f"{weeks_over}주 (한도 {max_per_week}h)",
        "추가 가산수당": f"{extra_premium_pay:,.0f}원",
        "월 환산 수당": f"{monthly_overtime:,.0f}원",
        **{f"주별 실근로({k})": v for k, v in weekly_detail.items()},
    }

    return FlexibleWorkResult(
        unit_period=unit,
        unit_weeks=unit_weeks,
        total_actual_hours=round(total_actual, 1),
        legal_hours=legal_hours,
        overtime_hours=round(overtime_hours, 1),
        overtime_pay_per_period=round(overtime_pay, 0),
        monthly_overtime_pay=round(monthly_overtime, 0),
        weeks_exceeding_limit=weeks_over,
        extra_premium_pay=round(extra_premium_pay, 0),
        breakdown=breakdown,
        formulas=formulas,
        warnings=warnings,
        legal_basis=legal,
    )
