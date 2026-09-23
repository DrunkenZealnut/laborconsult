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
    # 미래 연도는 **실패시키지 않는다.** 최저임금은 8월 5일에 고시되지만 출산휴가 상한
    # 고시는 그보다 늦게 나오므로, 그 사이 기간에 두 표가 어긋나는 것은 코드 결함이 아니라
    # 사실이다(2026-09 실측: 최저임금 2027 有, 상한 고시 無 — 고시는 2026-12-31까지만 유효).
    # 없는 고시를 CI로 강제하면 값을 추정해 채우도록 압박하게 된다. 대신 매 실행에 보이게
    # 두고, 실제로 계산이 막히는 시점(그 해가 오늘이 되는 때)에 위 검사가 실패시킨다.
    _pending = [y for y in sorted(MINIMUM_HOURLY_WAGE)
                if y > _today.year and y not in MATERNITY_LEAVE_UPPER]
    if _pending:
        print(f"  ℹ️  출산전후휴가급여 상한 미등록 연도: {_pending} — 해당 연도 계산은 보류된다."
              " 고시 발표 후 MATERNITY_LEAVE_UPPER 갱신 필요(추정값 입력 금지)")
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

    print("── 출산전후휴가급여: 고시 총액 상한과 일치 ──")
    # 고시는 기간 총액으로 쓰지만 내부 산식은 월 상한 ÷ 30 × 일수다. 코드가 연 365일 환산
    # (×12/365)을 쓰고 상한도 최저임금×209였던 탓에 90일 총액이 638만원으로 217,999원
    # 모자랐다. 이 검사가 고시값과의 일치를 고정한다.
    from wage_calculator.calculators.maternity_leave import calc_maternity_leave

    def _maternity(year, monthly, multiple=False, date=None, priority=True):
        # facade 는 summary 문자열만 노출하므로 계산기를 직접 부른다(통상임금 계산기와 같은 방식).
        _inp = WageInput(wage_type=WageType.MONTHLY, monthly_wage=monthly, reference_year=year,
                         is_multiple_birth=multiple, is_priority_support_company=priority,
                         schedule=WorkSchedule(daily_work_hours=8, weekly_work_days=5))
        _inp.reference_date = date
        return calc_maternity_leave(_inp, calc_ordinary_wage(_inp))

    _m26 = _maternity(2026, 5_000_000)
    check("2026 출산전후휴가 90일 총액 = 6,600,000 (고용노동부고시 제2025-124호)",
          approx(_m26.total_insurance_benefit, 6_600_000, 0.0001),
          f"{_m26.total_insurance_benefit:,.0f}")
    _m26m = _maternity(2026, 5_000_000, multiple=True)
    check("2026 다태아 120일 총액 = 8,800,000 (동 고시)",
          approx(_m26m.total_insurance_benefit, 8_800_000, 0.0001),
          f"{_m26m.total_insurance_benefit:,.0f}")
    # 고시 상한은 **고용보험 급여**의 상한이고 유급 의무는 사업주에게 남는다 — 상한을
    # 유급액에 걸면 대규모기업 근로자의 법정 유급액이 줄어든 것처럼 보인다(CodeRabbit PR #78).
    check("2026 배우자 고용보험 급여 상한 = 1,684,210 (동 고시)",
          approx(_m26.spouse_insurance_benefit, 1_684_210, 0.0001),
          f"{_m26.spouse_insurance_benefit:,.0f}")
    check("배우자 유급액은 상한에 깎이지 않는다 (사업주가 차액 부담)",
          _m26.spouse_leave_pay > _m26.spouse_insurance_benefit,
          f"유급 {_m26.spouse_leave_pay:,.0f} / 보험 {_m26.spouse_insurance_benefit:,.0f}")
    _big = _maternity(2026, 5_000_000, priority=False)
    check("대규모기업은 배우자 고용보험 지원 0원 (유급액은 유지)",
          _big.spouse_insurance_benefit == 0 and _big.spouse_leave_pay > 0,
          f"보험 {_big.spouse_insurance_benefit:,.0f} / 유급 {_big.spouse_leave_pay:,.0f}")
    check("2025-01-10 고용보험 지원은 5일분 (개정 시행 전)",
          _maternity(2025, 5_000_000, date="2025-01-10").spouse_insurance_days == 5)
    check("2025-06-01 고용보험 지원은 20일분·상한 1,607,650",
          approx(_maternity(2025, 5_000_000, date="2025-06-01").spouse_insurance_benefit,
                 1_607_650, 0.0001))
    # 남녀고용평등법 제18조의2 개정(2025-02-23): 10일 → 20일. 연중 시행이라 날짜로 갈린다.
    check("배우자 출산휴가 일수: 2025-01-10 → 10일",
          _maternity(2025, 3_000_000, date="2025-01-10").spouse_leave_days == 10)
    check("배우자 출산휴가 일수: 2025-06-01 → 20일 (개정 시행 이후)",
          _maternity(2025, 3_000_000, date="2025-06-01").spouse_leave_days == 20)
    check("배우자 출산휴가 일수: 2026 → 20일",
          _maternity(2026, 3_000_000).spouse_leave_days == 20)

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
