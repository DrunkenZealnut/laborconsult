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
    check("2027 최저임금 시급 = 10,700 (고용노동부 고시 2026-08-05)",
          MINIMUM_HOURLY_WAGE.get(2027) == 10700, f"{MINIMUM_HOURLY_WAGE.get(2027)}")
    # 최저임금법 제10조: 고용노동부장관은 매년 8월 5일까지 다음 연도 최저임금을 고시한다.
    # 표가 그 뒤에도 다음 연도를 갖지 않으면 사실 블록이 "미고시"로 답하고 계산기는
    # 올해 값으로 조용히 폴백한다(2027년 고시 누락 실측 2026-09-22). 그 시점부터 실패시킨다.
    from datetime import date as _date
    _today = _date.today()
    if _today >= _date(_today.year, 8, 5):
        check(f"{_today.year + 1} 최저임금이 표에 있음 (8/5 고시 이후 갱신 필수)",
              _today.year + 1 in MINIMUM_HOURLY_WAGE,
              f"표 최신 연도 {max(MINIMUM_HOURLY_WAGE)}")
    # 최저임금표만 앞서 갱신되면 그 해 출산전후휴가 계산이 **통째로 보류**된다 —
    # 새 최저임금으로 만든 하한이 옛 상한을 넘기 때문이다(실측 2027: 2,236,300 > 2,156,880).
    # 해가 바뀌는 순간 모든 출산휴가 질문에서 터지므로 그 전에 CI가 잡아야 한다.
    from wage_calculator.calculators.maternity_leave import MATERNITY_LEAVE_UPPER
    if _today.year in MINIMUM_HOURLY_WAGE:
        check(f"{_today.year}년 출산전후휴가급여 상한이 표에 있음 (고용노동부 고시 갱신 필수)",
              _today.year in MATERNITY_LEAVE_UPPER,
              f"상한표 최신 연도 {max(MATERNITY_LEAVE_UPPER)} / 최저임금표 {max(MINIMUM_HOURLY_WAGE)}")
    # 기준소득월액 적용기간은 **7월~익년 6월**이다(국민연금법 시행령 제5조제4항).
    # 연 단위 표로는 표현할 수 없어 2026년 하반기 내내 직전 구간 값을 냈다(실측 2026-09-23).
    r26_h1 = get_insurance_rates(2026, "2026-03-01")
    check("2026 상반기 연금 기준소득 상한 = 6,370,000 (2025.7~2026.6 고시)",
          r26_h1["pension_income_max"] == 6_370_000, f"{r26_h1['pension_income_max']:,}")
    check("2026 상반기 연금 기준소득 하한 = 400,000 (2025.7~2026.6 고시)",
          r26_h1["pension_income_min"] == 400_000, f"{r26_h1['pension_income_min']:,}")
    r26_h2 = get_insurance_rates(2026, "2026-07-01")
    check("2026 하반기 연금 기준소득 상한 = 6,590,000 (2026.7~2027.6 고시)",
          r26_h2["pension_income_max"] == 6_590_000, f"{r26_h2['pension_income_max']:,}")
    check("2026 하반기 연금 기준소득 하한 = 410,000 (2026.7~2027.6 고시)",
          r26_h2["pension_income_min"] == 410_000, f"{r26_h2['pension_income_min']:,}")
    # 경계일(6/30 → 7/1)에서 갈려야 한다. 한 칸이라도 밀리면 한 달치가 조용히 틀린다.
    check("연금 기준소득 구간 경계 = 7월 1일",
          get_insurance_rates(2026, "2026-06-30")["pension_income_max"] == 6_370_000,
          f"{get_insurance_rates(2026, '2026-06-30')['pension_income_max']:,}")
    # 건강보험료 상·하한은 고시(개정 2025.12.24)의 **직장가입자 보수월액보험료**이고
    # 계산기는 근로자 부담분(요율 ÷ 2)에 상한을 걸므로 고시값의 절반이 들어가야 한다.
    r26 = get_insurance_rates(2026)
    check("2026 건강보험료 월 상한(근로자) = 4,591,740 = 9,183,480 ÷ 2",
          r26["health_premium_max"] == 9_183_480 // 2, f"{r26['health_premium_max']:,}")
    check("2026 건강보험료 월 하한(근로자) = 10,080 = 20,160 ÷ 2",
          r26["health_premium_min"] == 20_160 // 2, f"{r26['health_premium_min']:,}")

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
    from wage_calculator.models import WorkType

    def _check_wh_consistency(label: str, sched: WorkSchedule, work_type=None):
        kwargs = {"wage_type": WageType.MONTHLY, "schedule": sched}
        if work_type is not None:
            kwargs["work_type"] = work_type
        _inp = WageInput(**kwargs)
        _ow = calc_ordinary_wage(_inp)
        _wh = calc_working_hours(_inp, _ow)
        check(f"{label} 월 소정근로시간 = ordinary_wage 기준시간",
              approx(_wh.monthly_hours, _ow.monthly_base_hours),
              f"working={_wh.monthly_hours}h / ordinary={_ow.monthly_base_hours}h")

    # 일반 스케줄 (daily × days)
    for daily, days in [(8, 5), (9, 5), (10, 4), (6, 6), (8, 6)]:
        _check_wh_consistency(f"{daily}h×{days}일",
                              WorkSchedule(daily_work_hours=daily, weekly_work_days=days))
    # 오버라이드 경로 (PR 주장 범위: 교대근무·월소정 직접입력) — CodeRabbit #18 반영
    _override_cases = [
        ("월소정 직접입력 226h",
         WorkSchedule(daily_work_hours=8, weekly_work_days=5, monthly_scheduled_hours=226.0), None),
        ("교대 월시간 243h",
         WorkSchedule(daily_work_hours=8, weekly_work_days=5, shift_monthly_hours=243.0), None),
        ("4조2교대 유형",
         WorkSchedule(daily_work_hours=8, weekly_work_days=5), WorkType.SHIFT_4_2),
    ]
    for _label, _sched, _wt in _override_cases:
        _check_wh_consistency(_label, _sched, work_type=_wt)

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
