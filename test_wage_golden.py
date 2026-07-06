#!/usr/bin/env python3
"""임금계산기 골든 회귀 테스트 (C-2b).

기대값을 명시적으로 단언하고 종료코드로 통과/실패를 반영한다.
기존 wage_calculator_cli.py는 출력만 하는 스모크 테스트라 값 오류를 못 잡으므로,
핵심 계산·상수·엣지케이스를 확정 기대값으로 고정해 회귀를 방지한다.

실행: python3 test_wage_golden.py   (전부 통과 시 exit 0, 하나라도 실패 시 exit 1)
"""
from __future__ import annotations

import sys

from wage_calculator.models import WageInput, WorkSchedule, WageType
from wage_calculator.facade import WageCalculator
from wage_calculator.constants import get_insurance_rates, MINIMUM_HOURLY_WAGE

_failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "✅" if cond else "❌"
    print(f"  {mark} {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        _failures.append(name)


def approx(a: float, b: float, tol: float = 0.01) -> bool:
    return abs(a - b) <= max(1.0, abs(b) * tol)


def calc(inp, targets):
    return WageCalculator().calculate(inp, targets)


def main() -> int:
    print("── 상수 골든 ──")
    check("2026 최저임금 시급 = 10,320", MINIMUM_HOURLY_WAGE[2026] == 10320)
    r26 = get_insurance_rates(2026)
    check("2026 국민연금 기준소득월액 상한 = 6,370,000 (C-1)",
          r26["pension_income_max"] == 6_370_000, f"{r26['pension_income_max']:,}")
    check("2026 국민연금 기준소득월액 하한 = 400,000 (C-1)",
          r26["pension_income_min"] == 400_000, f"{r26['pension_income_min']:,}")

    print("── 통상임금(시급/일급은 clean value) ──")
    r_h = calc(WageInput(wage_type=WageType.HOURLY, hourly_wage=10_000, reference_year=2026,
                         schedule=WorkSchedule(daily_work_hours=8, weekly_work_days=5)), ["ordinary"])
    check("시급 10,000원 → 통상시급 10,000", approx(r_h.ordinary_hourly, 10_000), f"{r_h.ordinary_hourly}")
    r_d = calc(WageInput(wage_type=WageType.DAILY, daily_wage=80_000, reference_year=2026,
                         schedule=WorkSchedule(daily_work_hours=8, weekly_work_days=5)), ["ordinary"])
    check("일급 80,000원 ÷ 8h → 통상시급 10,000", approx(r_d.ordinary_hourly, 10_000), f"{r_d.ordinary_hourly}")

    print("── working_hours ↔ ordinary_wage 월 소정근로시간 일치 (불일치 회귀 방지) ──")
    from wage_calculator.calculators.ordinary_wage import calc_ordinary_wage
    from wage_calculator.calculators.working_hours import calc_working_hours
    for daily, days in [(8, 5), (9, 5), (10, 4), (6, 6), (8, 6)]:
        _inp = WageInput(wage_type=WageType.MONTHLY,
                         schedule=WorkSchedule(daily_work_hours=daily, weekly_work_days=days))
        _ow = calc_ordinary_wage(_inp)
        _wh = calc_working_hours(_inp, _ow)
        check(f"{daily}h×{days}일 월 소정근로시간 = ordinary_wage 기준시간",
              approx(_wh.monthly_hours, _ow.monthly_base_hours),
              f"working={_wh.monthly_hours}h / ordinary={_ow.monthly_base_hours}h")

    print("── 엣지케이스 (Wave 0/2 방어) ──")
    r_zero = calc(WageInput(wage_type=WageType.MONTHLY, monthly_wage=2_090_000,
                            schedule=WorkSchedule(daily_work_hours=0, weekly_work_days=0)), ["ordinary", "minimum_wage"])
    check("주0일·일0h 입력 → 크래시 없음 (C-0)", r_zero.ordinary_hourly >= 0, f"{r_zero.ordinary_hourly}")
    r_neg = calc(WageInput(wage_type=WageType.MONTHLY, monthly_wage=-1_000_000), ["ordinary"])
    check("음수 임금 → 0 클램프 (C-2c)", r_neg.ordinary_hourly == 0, f"{r_neg.ordinary_hourly}")

    print("── 자동감지 (C-2a) ──")
    wc = WageCalculator()
    t_multi = wc._auto_detect_targets(WageInput(wage_type=WageType.MONTHLY, monthly_wage=3_000_000, is_multiple_birth=True))
    check("다태아 → maternity_leave 자동감지", "maternity_leave" in t_multi)
    t_single = wc._auto_detect_targets(WageInput(wage_type=WageType.MONTHLY, monthly_wage=3_000_000))
    check("단태아 → maternity_leave 미포함(오탐 없음)", "maternity_leave" not in t_single)

    print()
    if _failures:
        print(f"❌ 실패 {len(_failures)}건: {', '.join(_failures)}")
        return 1
    print("✅ 골든 테스트 전부 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
