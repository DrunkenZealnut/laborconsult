"""calc-card-followups 회귀 테스트(오프라인, API 키 불요) — Design §8.

계산 카드는 LLM 컨텍스트에 "이 수치를 사용하세요"로 들어가 답변 금액이 된다. 이 테스트는 카드가 법적 정의와 다른 시간·금액을
내던 결함이 돌아오지 않게 고정한다.
- T1 소정·연장 분리 규칙(D1·D9)
- T2 시간 축 카드(R1~R4)
- T3 규모(D2·규모 미상 안내)
- T4 근로시간 제도 신호(D3)
- T5 기간급 두 구성(D4)
- T6 연장시간 조정(D8)
- T7 시급 없는 주휴 블록
- T8 1일 통상임금 표기·연차수당(F2)
- T9 실업급여(F5)
- T10 평균임금·보수(F6)
- T15 원문 앵커·고정 8시간 구조 검사
- T16 흐름도 JS
- T17 PR A 독립 리뷰 지적 회귀(H1~H4·M1~M4·L1~L4)
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def card(params: dict, query: str) -> str:
    """파이프라인 계산 카드(의도분석 결과 형태의 params를 직접 넣는다 — LLM 호출 없음)."""
    from app.core.pipeline import _run_calculator
    base = {"needs_calculation": True, "reference_year": 2026}   # 오늘 날짜에 묶이지 않게(2차 리뷰 M5)
    base.update(params)
    return _run_calculator(base, query) or ""


HOURLY = {"wage_type": "시급", "wage_amount": 12000, "business_size": "5인이상"}


class SplitRuleTest(unittest.TestCase):
    """T1 — 1일 8시간·1주 40시간을 넘는 시간은 연장근로(근로기준법 제2조 제1항 제8호·제50조, 대법원 2022다291153 [2]①)."""

    # (1일, 근무일수) → (1일 평균 소정, 소정근로일, 1주 연장)
    TABLE = {(8, 5): (8, 5, 0), (10, 5): (8, 5, 10), (10, 4): (8, 4, 8), (16, 3.5): (8, 3.5, 28), (8, 6): (8, 5, 8),
             (7, 6): (40 / 6, 6, 2), (6, 7): (40 / 7, 7, 2), (12, 2): (8, 2, 8), (16, 1): (8, 1, 8), (9, 5): (8, 5, 5),
             (7, 5.8): (40 / 5.8, 5.8, 0.6)}

    def test_t1_split_table(self):
        from wage_calculator.calculators.shared import split_hours
        for (daily, days), (s_daily, s_days, excess) in self.TABLE.items():
            with self.subTest((daily, days)):
                split = split_hours(daily, days)
                self.assertAlmostEqual(split.daily, s_daily, places=9)
                self.assertAlmostEqual(split.days, s_days, places=9)
                self.assertAlmostEqual(split.excess, excess, places=9)
                self.assertEqual(split.mode, "applied" if excess else "none")
                self.assertLessEqual(split.weekly, 40 + 1e-9)

    def test_t1_holiday_hours_through_the_split(self):
        """주휴 함수의 입력은 나눈 소정근로시간이다 — 예전 단언 (4, 10) → 8h는 '1일 소정 10h'라는 불가능한 입력의 값이었다."""
        from wage_calculator.calculators.shared import split_hours, weekly_holiday_hours
        for (daily, days), hours in {(10, 4): 6.4, (9, 5): 8, (10, 6): 8, (16, 3.5): 5.6, (8, 6): 8, (12, 2): 3.2}.items():
            split = split_hours(daily, days)
            self.assertAlmostEqual(weekly_holiday_hours(split.days, split.daily)[0], hours, places=9, msg=(daily, days))
        self.assertLess(split_hours(16, 1).weekly, 15)        # 주 1회 16시간은 소정 8시간 — 주휴 요건(15시간) 미달

    def test_t1_apply_is_idempotent_and_reconciles_stated_overtime(self):
        from wage_calculator.calculators.shared import apply_hour_split
        from wage_calculator.models import WageInput, WorkSchedule
        inp = WageInput(schedule=WorkSchedule(daily_work_hours=10, weekly_work_days=5, weekly_overtime_hours=10))
        first = apply_hour_split(inp)
        self.assertEqual((inp.schedule.daily_work_hours, inp.schedule.weekly_work_days, inp.schedule.weekly_overtime_hours),
                         (8, 5, 10))   # 같은 10시간을 두 필드에 적은 추출 — 더하지 않는다(D8)
        self.assertIs(apply_hour_split(inp), first)
        self.assertEqual(inp.schedule.weekly_overtime_hours, 10)

    def test_t1_inputs_that_are_not_split(self):
        from wage_calculator.calculators.shared import apply_hour_split
        from wage_calculator.models import WageInput, WorkSchedule, WorkType
        cases = {"platform": dict(is_platform_worker=True),
                 "shift_table": dict(work_type=WorkType.SHIFT_4_2),
                 "flexible": dict(flexible_work_unit="3개월")}
        for reason, extra in cases.items():
            inp = WageInput(schedule=WorkSchedule(daily_work_hours=12, weekly_work_days=4), **extra)
            with self.subTest(reason):
                self.assertEqual((apply_hour_split(inp).mode, inp.hour_split.reason), ("skipped", reason))
                self.assertEqual(inp.schedule.daily_work_hours, 12)
        inp = WageInput(schedule=WorkSchedule(daily_work_hours=12, weekly_work_days=4, monthly_scheduled_hours=209))
        self.assertEqual(apply_hour_split(inp).reason, "direct_hours")

    def test_t1_facade_splits_direct_callers_too(self):
        """CLI·직접 호출도 같은 일정을 읽는다 — facade 첫머리에서 나눈다."""
        from wage_calculator import WageCalculator, WageInput, WageType
        from wage_calculator.models import BusinessSize, WorkSchedule
        inp = WageInput(wage_type=WageType.HOURLY, hourly_wage=12000, business_size=BusinessSize.OVER_5, reference_year=2026,
                        schedule=WorkSchedule(daily_work_hours=10, weekly_work_days=4))
        result = WageCalculator().calculate(inp, ["weekly_holiday"])
        self.assertIn("주휴수당(월)", result.summary)
        self.assertEqual(result.summary["주휴수당(월)"], "333,714원")


class TimeAxisCardTest(unittest.TestCase):
    """T2 — 재현 R1~R4(main e76ab02에서 '주 소정근로: 10h×5일 = 50h'·연장 가산 없음·주휴 부풀림)."""

    def test_t2_r1_five_days_ten_hours(self):
        out = card(dict(HOURLY, calculation_types_kr=["주휴수당", "최저임금"], weekly_work_days=5, daily_work_hours=10),
                   "시급 12,000원이고 주 5일 하루 10시간씩 일하기로 계약했어요. 직원은 10명이에요. 주휴수당은 얼마인가요?")
        self.assertIn("주 근로 10h×5일 = 50h → 소정근로 8h×5일 = 40h + 연장 10h", out)
        self.assertIn("연장/야간/휴일수당(월): 782,143원", out)
        self.assertIn("월 총 예상 수령액(세전): 3,285,000원", out)
        self.assertNotIn("주 소정근로: 10h×5일", out)

    def test_t2_r2_four_days_ten_hours(self):
        out = card(dict(HOURLY, calculation_types_kr=["주휴수당"], weekly_work_days=4, daily_work_hours=10),
                   "시급 12,000원, 주 4일 하루 10시간 근무 계약입니다. 직원 10명. 주휴수당은요?")
        self.assertIn("주휴: min(32h ÷ 5, 8h) = 6.4h", out)
        self.assertIn("주휴수당(월): 333,714원", out)
        self.assertIn("월 총 예상 수령액(세전): 2,628,000원", out)

    def test_t2_r3_alternate_day_sixteen_hours(self):
        out = card(dict(HOURLY, calculation_types_kr=["주휴수당"], weekly_work_days=3.5, daily_work_hours=16,
                        business_size="30인이상"),
                   "공장에서 격일제로 하루 16시간씩 일하고 다음 날 쉽니다(주 평균 3.5일). 시급 12,000원, 직원 20명입니다.")
        self.assertIn("소정근로 8h×3.5일 = 28h + 연장 28h", out)
        self.assertIn("주휴: min(28h ÷ 5, 8h) = 5.6h", out)
        self.assertIn("휴게·수면시간은 근로시간에서 뺍니다(근로기준법 제54조)", out)
        self.assertIn("월 총 예상 수령액(세전): 3,942,000원", out)

    def test_t2_r4_six_days_eight_hours(self):
        out = card(dict(HOURLY, calculation_types_kr=["주휴수당"], weekly_work_days=6, daily_work_hours=8),
                   "시급 12,000원, 주 6일 하루 8시간 근무 계약입니다. 직원 10명. 주휴수당은요?")
        self.assertIn("주 40시간을 넘는 1일분은 연장근로일로 보아 소정근로일 5일", out)
        self.assertIn("주휴: min(8h, 8h) = 8h", out)
        self.assertIn("월 총 예상 수령액(세전): 3,128,571원", out)

    def test_t2_no_change_within_limits(self):
        """1일 8시간·1주 40시간 이하는 그대로다."""
        out = card(dict(HOURLY, calculation_types_kr=["주휴수당"], weekly_work_days=5, daily_work_hours=8),
                   "시급 12,000원, 주 5일 하루 8시간 근무 계약입니다. 직원 10명.")
        self.assertIn("[기준시간] 주 소정근로: 8h×5일 = 40h", out)
        self.assertNotIn("연장", out.split("── 계산식 ──")[1].split("── ⚠️")[0])


class BusinessSizeTest(unittest.TestCase):
    """T3 — 상시 4명 이하도 소정근로시간 상한은 같고 가산만 없다(근로기준정책과-2668·-5106). 규모를 모르면 가정을 밝힌다."""

    def test_t3_small_business_splits_without_premium(self):
        out = card(dict(HOURLY, business_size="5인미만", calculation_types_kr=["주휴수당"], weekly_work_days=5,
                        daily_work_hours=10), "시급 12,000원, 주 5일 하루 10시간, 직원 3명인 가게입니다.")
        self.assertIn("소정근로 8h×5일 = 40h + 연장 10h", out)
        self.assertIn("연장수당: 12,000.0원 × 10h × 1.0 = 120,000원/주", out)
        self.assertIn("월 총 예상 수령액(세전): 3,024,286원", out)
        self.assertNotIn("상시 5명 이상 사업장 기준으로", out)

    def test_t3_unknown_size_states_the_assumption(self):
        from app.core.pipeline import _SIZE_ASSUMED_NOTE
        params = dict(HOURLY, calculation_types_kr=["주휴수당"], weekly_work_days=5, daily_work_hours=10)
        params.pop("business_size")
        self.assertIn(_SIZE_ASSUMED_NOTE, card(params, "시급 12,000원, 주 5일 하루 10시간 일해요."))
        self.assertNotIn(_SIZE_ASSUMED_NOTE, card(dict(HOURLY, calculation_types_kr=["주휴수당"], weekly_work_days=5,
                                                       daily_work_hours=10), "시급 12,000원, 주 5일 하루 10시간, 직원 10명."))


class RegimeSignalTest(unittest.TestCase):
    """T4 — 근로시간 제도 신호 + 초과 시간이면 나누지 않고 제도 확인을 안내한다(D3)."""

    def test_t4_signal_with_excess_holds(self):
        cases = {"탄력적 근로시간제로 하루 10시간씩 주 4일 일합니다. 시급 12,000원, 직원 50명입니다.":
                 "탄력적·선택적·간주·재량 근로시간제",
                 "아파트 경비원으로 하루 16시간 격일제 근무합니다. 시급 12,000원입니다.": "감시·단속적 근로(적용 제외 승인)"}
        for query, label in cases.items():
            days, daily = (4, 10) if "탄력" in query else (3.5, 16)
            with self.subTest(label):
                out = card(dict(HOURLY, calculation_types_kr=["주휴수당"], weekly_work_days=days, daily_work_hours=daily), query)
                self.assertIn("[근로시간 제도 확인 필요", out)
                self.assertIn(f"질문에 {label} 언급이 있어", out)
                self.assertIn("금액 보류: 근로시간 제도를 확인해야 해", out)
                self.assertNotIn("소정근로 8h", out)

    def test_t4_signal_without_excess_does_nothing(self):
        out = card(dict(HOURLY, calculation_types_kr=["주휴수당"], weekly_work_days=5, daily_work_hours=8),
                   "아파트 경비원으로 주 5일 하루 8시간 일합니다. 시급 12,000원, 직원 10명.")
        self.assertNotIn("근로시간 제도 확인 필요", out)
        self.assertIn("[기준시간] 주 소정근로: 8h×5일 = 40h", out)

    def test_t4_signal_words_in_the_evaluation_sets(self):
        """평가 질문 148개(점검 14·지식iN 20·상담 60·구어 18·코퍼스 12·검색 24) 중 신호어 출현은 셋 — 모두 그 제도를 묻는 질문이다."""
        from app.core.pipeline import _hour_regime_signal
        hits = set()
        for path in sorted((ROOT / "data").glob("eval_*.json")):
            if path.name == "eval_calc_card_queries.json":
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
            items = raw if isinstance(raw, list) else raw.get("cases") or raw.get("queries") or raw.get("items") or []
            for item in items:
                if isinstance(item, dict) and _hour_regime_signal(item.get("question") or item.get("query") or ""):
                    hits.add(item.get("id"))
        self.assertEqual(hits, {"hours-08", "q14", "q15"})


class PeriodWageCompositionTest(unittest.TestCase):
    """T5 — 일급·월급·연봉에 연장 등이 있고 임금 구성을 모르면 '연장 별도'와 '연장 포함 역산'의 최저임금 판정이 갈릴 때 보류(D4)."""

    MONTHLY = {"wage_type": "월급", "business_size": "5인이상", "calculation_types_kr": ["최저임금"], "weekly_work_days": 5,
               "daily_work_hours": 10}

    def test_t5_r5_both_readings_comply(self):
        out = card(dict(self.MONTHLY, wage_amount=3000000), "월급 300만원, 주 5일 하루 10시간 근무 계약입니다. 직원 10명.")
        self.assertIn("최저임금 충족: ✅ 충족", out)
        self.assertIn("역산): 2,285,714원 ÷ 208.5714h = 10,958.90원", out)
        self.assertIn("월급이 소정근로(1일 8시간·주 40시간)와 주휴의 대가라면", out)
        self.assertNotIn("월 총 예상 수령액(세전)", out)     # 총액은 구성을 몰라 싣지 않는다

    def test_t5_r6_readings_split(self):
        out = card(dict(self.MONTHLY, wage_amount=2700000), "월급 270만원, 주 5일 하루 10시간 근무 계약입니다. 직원 10명.")
        self.assertIn("최저임금 충족: ⏸ 판정 보류", out)
        self.assertIn("실질시급: 12,945원 또는 9,863원", out)
        self.assertIn("최저임금법 제6조 제4항 제1호", out)
        self.assertNotIn("노동청 신고", out)

    def test_t5_daily_wage(self):
        params = dict(self.MONTHLY, wage_type="일급")
        out = card(dict(params, wage_amount=120000), "일급 12만원, 주 5일 하루 10시간 일합니다. 직원 10명.")
        self.assertIn("최저임금 충족: ✅ 충족", out)
        self.assertIn("일급에 포함된 경우, 역산", out)
        out = card(dict(params, wage_amount=100000), "일급 10만원, 주 5일 하루 10시간 일합니다. 직원 10명.")
        self.assertIn("실질시급: 12,500원 또는 9,091원", out)

    def test_t5_stated_overtime_uses_the_same_rule(self):
        out = card({"wage_type": "월급", "wage_amount": 2500000, "business_size": "5인이상",
                    "calculation_types_kr": ["최저임금"], "weekly_work_days": 5, "daily_work_hours": 8,
                    "weekly_overtime_hours": 12}, "월급 250만원, 주 5일 8시간에 매주 연장 12시간을 합니다. 직원 10명.")
        self.assertIn("최저임금 충족: ⏸ 판정 보류", out)
        self.assertIn("역산)", out)

    def test_t5_comprehensive_label_reverses_with_derived_overtime(self):
        """포괄임금제 + 1일 10시간 — 역산 계수에 파생 연장 10시간이 들어간다(예전에는 연장 0시간으로 나눴다)."""
        out = card(dict(self.MONTHLY, wage_type="포괄임금제", wage_amount=2700000),
                   "포괄임금제로 월 270만원, 주 5일 하루 10시간 일합니다. 직원 10명. 최저임금 위반인가요?")
        self.assertIn("총계수시간(월): 273.75h", out)
        self.assertIn("포괄임금 역산 시급: 9,863원", out)
        self.assertIn("최저임금 충족: ❌ 미달", out)

    def test_t5_known_composition_has_no_reverse_reading(self):
        from wage_calculator import WageCalculator, WageInput, WageType
        from wage_calculator.models import BusinessSize, WorkSchedule
        inp = WageInput(wage_type=WageType.MONTHLY, monthly_wage=2700000, business_size=BusinessSize.OVER_5,
                        reference_year=2026, wage_composition_known=True,
                        schedule=WorkSchedule(daily_work_hours=8, weekly_work_days=5, weekly_overtime_hours=10))
        result = WageCalculator().calculate(inp, ["minimum_wage"])
        self.assertFalse(any("역산" in f for f in result.formulas))
        self.assertIs(result.minimum_wage_ok, True)


class OvertimeReconcileTest(unittest.TestCase):
    """T6 — 질문의 연장시간과 1일 초과분(D8)."""

    BASE = dict(HOURLY, calculation_types_kr=["연장수당"], weekly_work_days=5, daily_work_hours=10)

    def test_t6_same_hours_are_not_added(self):
        out = card(dict(self.BASE, weekly_overtime_hours=10), "시급 12,000원, 주 5일 하루 10시간, 연장 10시간. 직원 10명.")
        self.assertIn("연장수당: 12,000.0원 × 10h × 1.5 = 180,000원/주", out)
        self.assertNotIn("별개라면", out)

    def test_t6_different_hours_use_the_larger_and_say_so(self):
        out = card(dict(self.BASE, weekly_overtime_hours=5), "시급 12,000원, 주 5일 하루 10시간, 연장 5시간. 직원 10명.")
        self.assertIn("× 10h × 1.5", out)
        self.assertIn("둘이 별개라면 주 15시간입니다", out)
        out = card(dict(self.BASE, weekly_overtime_hours=12), "시급 12,000원, 주 5일 하루 10시간, 연장 12시간. 직원 10명.")
        self.assertIn("× 12h × 1.5", out)
        self.assertIn("둘이 별개라면 주 22시간입니다", out)


class MissingInfoTest(unittest.TestCase):
    """T6b — 1일 8시간·1주 40시간을 넘는 근무시간이 있으면 연장시간은 계산기가 나눠 구한다 — '주당 연장근로시간'을 묻지 않는다
    (의도분석 프롬프트 5번 예시 변경과 짝, Design §14 C1)."""

    def test_t6b_overtime_is_not_asked_when_derivable(self):
        from app.core.pipeline import _compute_missing_info
        asked = lambda info: "주당 연장근로시간" in _compute_missing_info(["overtime"], dict(info, wage_amount=12000))  # noqa: E731
        self.assertFalse(asked({"daily_work_hours": 10, "weekly_work_days": 5}))     # 1일 8시간 초과
        self.assertFalse(asked({"daily_work_hours": 8, "weekly_work_days": 6}))      # 1주 40시간 초과
        self.assertFalse(asked({"weekly_total_hours": 50}))
        self.assertTrue(asked({"daily_work_hours": 8, "weekly_work_days": 5}))
        self.assertTrue(asked({}))


class WagelessHolidayBlockTest(unittest.TestCase):
    """T7 — 시급 없는 주휴 블록도 같은 분리를 쓴다."""

    def test_t7_block(self):
        from app.core.pipeline import _wageless_weekly_holiday
        block = _wageless_weekly_holiday(4, 10)
        self.assertIn("1주 소정근로시간: 8h × 4일 = 32h + 연장 8h", block)
        self.assertIn("6.4h", block)
        self.assertIn("1주 소정근로시간: 3일 × 6h = 18h", _wageless_weekly_holiday(3, 6))
        self.assertIn("주휴수당 미발생", _wageless_weekly_holiday(1, 16))


class DailyOrdinaryWageTest(unittest.TestCase):
    """T8 — 1일 통상임금 = 시간급 × 1일 소정근로시간(시행령 제6조 제3항). 8시간 고정이 표기·연차수당에 남지 않게(F2)."""

    def test_t8_severance_label(self):
        out = card(dict(HOURLY, calculation_types_kr=["퇴직금"], weekly_work_days=5, daily_work_hours=6,
                        start_date="2024-01-02", end_date="2026-01-01"),
                   "시급 12,000원, 주 5일 하루 6시간 근무로 2024년 1월 2일부터 2026년 1월 1일까지 일했어요. 퇴직금은?")
        self.assertIn("통상임금 환산:  72,000원/일 (12,000원 × 6h)", out)

    def test_t8_ineligible_result_uses_the_daily_ordinary_wage(self):
        from wage_calculator.calculators.ordinary_wage import calc_ordinary_wage
        from wage_calculator.calculators.severance import calc_severance
        from wage_calculator.models import WageInput, WageType, WorkSchedule
        inp = WageInput(wage_type=WageType.HOURLY, hourly_wage=12000, start_date="2026-01-02", end_date="2026-06-01",
                        schedule=WorkSchedule(daily_work_hours=6, weekly_work_days=5))
        ow = calc_ordinary_wage(inp)
        result = calc_severance(inp, ow)
        self.assertFalse(result.is_eligible)
        self.assertEqual(result.avg_daily_ordinary, ow.daily_ordinary_wage)

    def test_t8_part_time_annual_leave_pay(self):
        """주 5일 × 4h: 별표 2 제4호 15일 × 20h/40h × 8시간 = 60시간 → 600,000원(예전 1,200,000원)."""
        from wage_calculator import WageCalculator, WageInput, WageType
        from wage_calculator.models import BusinessSize, WorkSchedule
        for daily, pay in ((4, "600,000원"), (8, "1,200,000원")):
            inp = WageInput(wage_type=WageType.HOURLY, hourly_wage=10000, business_size=BusinessSize.OVER_5,
                            reference_year=2026, start_date="2024-01-02", end_date="2026-01-01",
                            schedule=WorkSchedule(daily_work_hours=daily, weekly_work_days=5))
            with self.subTest(daily):
                self.assertEqual(WageCalculator().calculate(inp, ["annual_leave"]).summary["연차수당"], pay)


class UnemploymentTest(unittest.TestCase):
    """T9 — 최저기초일액 = 이직 전 1일 소정근로시간 × 최저임금(고용보험법 제45조 제4항), 기초일액은 통상임금 하한(제2항)."""

    BASE = {"calculation_types_kr": ["실업급여"], "wage_type": "시급", "age": 30, "start_date": "2024-09-01",
            "end_date": "2026-09-30"}

    def _card(self, **extra):
        return card(dict(self.BASE, **extra), "권고사직으로 2026년 9월 30일 퇴사했어요. 만 30세입니다. 실업급여는?")

    def test_t9_r9_part_time_floor(self):
        out = self._card(wage_amount=10320, weekly_work_days=5, daily_work_hours=4)
        self.assertIn("하한액(최저구직급여일액): 최저임금 10,320원 × 1일 소정근로시간 4h × 80% = 33,024원", out)
        self.assertIn("구직급여 일액: 33,024원/일", out)
        self.assertIn("총 구직급여: 4,953,600원", out)

    def test_t9_full_time_unchanged(self):
        out = self._card(wage_amount=10320, weekly_work_days=5, daily_work_hours=8)
        self.assertIn("구직급여 일액: 66,048원/일", out)

    def test_t9_ordinary_wage_floor_of_the_basic_daily_amount(self):
        out = self._card(wage_amount=15000, weekly_work_days=5, daily_work_hours=4)
        self.assertIn("기초일액: 평균임금 51,009원 < 1일 통상임금 60,000원 → 통상임금 적용 (고용보험법 제45조 제2항)", out)
        self.assertIn("구직급여 일액: 36,000원/일", out)

    def test_t9_weekly_defined_hours(self):
        """'주 15시간'으로 정했으면 (주 소정 + 유급휴일 소정) ÷ 48 × 8 = (15 + 3) ÷ 48 × 8 = 3h(시행규칙 제91조의2 제1항 제2호)."""
        out = card(dict(self.BASE, wage_amount=10320, weekly_work_days=3, weekly_total_hours=15),
                   "시급 10,320원, 주 3일 주 15시간 일하다 권고사직으로 2026년 9월 30일 퇴사했어요. 만 30세.")
        self.assertIn("1일 소정근로시간 3h × 80% = 24,768원", out)

    def test_t9_platform_branch_is_unchanged(self):
        from wage_calculator import WageCalculator, WageInput, WageType
        from wage_calculator.models import WorkSchedule
        inp = WageInput(wage_type=WageType.MONTHLY, monthly_wage=1200000, is_platform_worker=True, reference_year=2026,
                        start_date="2024-09-01", end_date="2026-09-30", age=30, platform_insured_months=24,
                        schedule=WorkSchedule(daily_work_hours=4, weekly_work_days=5))
        result = WageCalculator().calculate(inp, ["unemployment"])
        self.assertFalse(any("1일 소정근로시간" in f for f in result.formulas))
        self.assertFalse(any("제45조 제2항" in f for f in result.formulas))


class MonthlyPayEstimateTest(unittest.TestCase):
    """T10 — 평균임금·보수월액에 연장·야간·휴일 근로 임금을 넣는다. 카드의 '월 총 예상 수령액'과 같은 산식이다(F6)."""

    def test_t10_r15_stated_overtime(self):
        out = card(dict(HOURLY, calculation_types_kr=["퇴직금", "연장수당", "4대보험"], weekly_work_days=5,
                        daily_work_hours=8, weekly_overtime_hours=10, start_date="2024-01-02", end_date="2026-01-01"),
                   "시급 12,000원, 주 5일 하루 8시간에 매주 연장근로 10시간을 했고 2024년 1월 2일부터 2026년 1월 1일까지 "
                   "일했어요. 직원 10명. 퇴직금은?")
        self.assertIn("월 총 예상 수령액(세전): 3,285,000원", out)
        self.assertIn("3개월 평균임금: 107,120원/일 (월 임금 + 연장·야간·휴일 근로 임금 월 782,143원(매주 같은 시간으로 봄) 기준 추정)",
                      out)
        self.assertIn("퇴직금: 6,427,174원", out)
        self.assertIn("세전 월 급여: 3,285,000원", out)

    def test_t10_r8_daily_ten_hours_severance(self):
        out = card(dict(HOURLY, calculation_types_kr=["퇴직금"], weekly_work_days=5, daily_work_hours=10,
                        start_date="2024-01-02", end_date="2026-01-01"),
                   "시급 12,000원, 주 5일 하루 10시간 근무로 2024년 1월 2일부터 2026년 1월 1일까지 일했어요. 직원 10명.")
        self.assertIn("통상임금 환산:  96,000원/일 (12,000원 × 8h)", out)
        self.assertIn("퇴직금: 6,427,174원", out)

    def test_t10_helper_contract(self):
        from wage_calculator.calculators.shared import monthly_pay_estimate
        from wage_calculator.models import WageInput, WageType, WorkSchedule
        plain = WageInput(wage_type=WageType.MONTHLY, monthly_wage=2700000,
                          schedule=WorkSchedule(daily_work_hours=8, weekly_work_days=5))
        self.assertEqual(monthly_pay_estimate(plain, 12000, 2700000), 2700000)          # 연장 등이 없으면 그대로
        with_ot = WageInput(wage_type=WageType.MONTHLY, monthly_wage=2700000,
                            schedule=WorkSchedule(daily_work_hours=8, weekly_work_days=5, weekly_overtime_hours=10))
        self.assertGreater(monthly_pay_estimate(with_ot, 12000, 2700000), 2700000)
        for extra in (dict(wage_type=WageType.COMPREHENSIVE), dict(wage_composition_known=True)):
            inp = WageInput(**{**dict(monthly_wage=2700000, wage_type=WageType.MONTHLY), **extra},
                            schedule=WorkSchedule(daily_work_hours=8, weekly_work_days=5, weekly_overtime_hours=10))
            self.assertEqual(monthly_pay_estimate(inp, 12000, 2700000), 2700000, extra)   # 이미 들어 있는 총액
        given = WageInput(monthly_wage=2096270, monthly_total_pay=2700000,
                          schedule=WorkSchedule(daily_work_hours=8, weekly_work_days=5, weekly_overtime_hours=10))
        self.assertEqual(monthly_pay_estimate(given, 12000, 2096270), 2700000)


class StructureTest(unittest.TestCase):
    """T15 — 손으로 쓴 법률 문구의 원문 앵커(로컬 관문)와 고정 8시간 구조 검사(CI)."""

    # 계산기 안에 남는 고정 8시간과 근거 — 새로 생기면 1일 소정근로시간을 써야 하는지 먼저 따질 것(F2·F5)
    ALLOWED_FIXED_EIGHT = {
        ("industrial_accident.py", "get_minimum_hourly_wage(year) * 8"): "산업재해보상보험법 제36조 제7항 '최저임금액'의 정의",
        ("unemployment.py", "(weekly + holiday) / 48 * 8"): "고용보험법 시행규칙 제91조의2 제1항 제2호",
    }
    ANCHORS = (
        ("lsa_act_2", "제50조, 제69조 본문 또는 「산업안전보건법」 제139조제1항에 따른 근로시간의 범위에서"),
        ("lsa_act_50", "1일의 근로시간은 휴게시간을 제외하고 8시간을 초과할 수 없다"),
        ("lsa_enf_6", "시간급 금액에 1일의 소정근로시간 수를 곱하여 계산한다"),
        ("ei_act_45", "이직 전 1일 소정근로시간에 이직일 당시 적용되던 「최저임금법」에 따른 시간 단위에 해당하는 최저임금액을 곱한 금액"),
        ("ei_act_45", "그 근로자의 통상임금보다 적을 경우에는 그 통상임금액을 기초일액으로 한다"),
        ("ei_act_46", "제45조제4항의 경우에는 그 수급자격자의 기초일액에 100분의 80을 곱한 금액"),
        ("ei_rule_91_2", "(주 소정근로시간 + 해당 기간 유급휴일의 소정근로시간 합계) ÷ 48시간 × 8시간"),
        ("lsa_act_63", "감시(監視) 또는 단속적(斷續的)으로 근로에 종사하는 사람으로서 사용자가 고용노동부장관의 승인을 받은 사람"),
        ("lsa_act_69", "15세 이상 18세 미만인 사람의 근로시간은 1일에 7시간, 1주에 35시간을 초과하지 못한다"),
        ("ei_act_45", "마지막 사업에서 이직 당시 일용근로자였던 사람의 경우에는 그러하지 아니하다"),
    )

    def test_t15_fixed_eight_hours_are_justified(self):
        found = set()
        for path in sorted((ROOT / "wage_calculator" / "calculators").glob("*.py")):
            for line in path.read_text(encoding="utf-8").splitlines():
                code = line.split("#", 1)[0]
                if re.search(r"\*\s*8\b(?!\s*[0-9.])", code) and "f\"" not in code:
                    found.add((path.name, code.strip().split("= ", 1)[-1].strip()))
        unexpected = {(name, code) for name, code in found
                      if not any(name == a and frag in code for a, frag in self.ALLOWED_FIXED_EIGHT)}
        self.assertEqual(unexpected, set())

    def test_t15_fixture_detector_examples(self):
        """측정 fixture의 감지 규칙 — 기준선 오류 문장은 잡고 정답 문장·수정 후 카드 줄은 잡지 않는다(Design §9 매처 타당성).
        CI에서 보지 않던 사이 calc-10 규칙이 '해고예고수당: 95,890원'의 끝자리를 '0원'으로 읽었다(PR B 실측)."""
        import eval_consultation as ev
        cases = ev.load_cases(ROOT / "data" / "eval_calc_card_queries.json")
        self.assertEqual(ev.validate_cases(cases), [])
        for case in cases:
            examples = case.detector_examples or {}
            self.assertTrue(examples.get("positive") and examples.get("negative"), case.id)
            for text in examples["positive"]:
                self.assertTrue([c for c in case.forbidden_claims if ev.claim_found(c, text)], f"{case.id} 감지 누락: {text[:50]}")
            for text in examples["negative"]:
                self.assertEqual([c for c in case.forbidden_claims if ev.claim_found(c, text)], [],
                                 f"{case.id} 정답 오검출: {text[:50]}")

    def test_t15_anchors_exist_in_official_text(self):
        base = ROOT / "output_공식법령"
        if not base.is_dir():
            self.skipTest("output_공식법령/ 없음 — fetch_official_rules.py --doc 로 수집 후 로컬에서 확인")
        import fetch_official_rules as fo
        ids = {a[0] for a in fo.ARTICLES}
        norm = lambda t: re.sub(r"\s+", "", t)  # noqa: E731
        for doc_id, phrase in self.ANCHORS:
            with self.subTest(doc_id):
                self.assertIn(doc_id, ids)
                path = base / f"{doc_id}.md"
                if not path.exists():
                    self.fail(f"{doc_id}.md 없음 — fetch_official_rules.py --doc {doc_id}")
                self.assertIn(norm(phrase), norm(path.read_text(encoding="utf-8").split("## 본문", 1)[-1]))


class FlowchartTest(unittest.TestCase):
    """T16 — 흐름도(브라우저 계산)도 같은 분리 규칙이다. 공개본과 wage_calculator 사본 둘 다."""

    WEEKLY = ("public/calculator_flow/weekly_holiday_pay_calc.html", "wage_calculator/calculator_flow/weekly_holiday_pay_calc.html")
    COMPREHENSIVE = ("public/calculator_flow/comprehensive_wage_reverse_calc.html",
                     "wage_calculator/calculator_flow/comprehensive_wage_reverse_calc.html")

    def test_t16_formula_strings(self):
        for path in self.WEEKLY:
            src = (ROOT / path).read_text(encoding="utf-8")
            with self.subTest(path):
                self.assertIn("var sDaily=Math.min(daily,8), sDays=days;", src)
                self.assertIn("holH=Math.min(sDaily,8);", src)
                self.assertNotIn("holH=Math.min(daily,8);", src)
        for path in self.COMPREHENSIVE:
            src = (ROOT / path).read_text(encoding="utf-8")
            with self.subTest(path):
                self.assertIn("var weekly = Math.min(dailyH, 8) * days;", src)
                self.assertIn("var cOt = otUsed * 1.5 * WPM;", src)

    @unittest.skipIf(shutil.which("node") is None, "node 없음")
    def test_t16_flowchart_values(self):
        """가짜 DOM으로 계산 함수를 실행해 계산기와 같은 값인지 본다(주 4일 × 10h → 주휴 6.4h, 포괄 주 40h/3일 → 계수 229.42h)."""
        script = r"""
const fs = require('fs');
function run(file, inputs) {
  const html = fs.readFileSync(file, 'utf8');
  const code = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]).filter(s => s.includes('function calc'));
  const els = {};
  const document = {getElementById: id => (els[id] ||= {value: inputs[id] ?? '0', textContent: '', innerHTML: '', style: {}}),
                    querySelectorAll: () => []};
  new Function('document', 'window', code.join('\n') + '\n;calc();')(document, {innerWidth: 1000, self: 1, top: 1});
  return els;
}
const out = {};
for (const f of process.argv.slice(1)) {   // node -e: 추가 인자는 argv[1]부터
  if (f.includes('weekly_holiday')) {
    const e = run(f, {wage: '12000', days: '4', daily: '10'});
    out[f] = [e.weeklyH.textContent, e.holH.textContent];
  } else {
    const e = run(f, {total: '300', weekly: '40', days: '3', ot: '10', night: '0', hol: '0', holOt: '0'});
    out[f] = [e.coeffTotal.textContent, e.revWage.textContent];
  }
}
console.log(JSON.stringify(out));
"""
        files = [str(ROOT / p) for p in (*self.WEEKLY, *self.COMPREHENSIVE)]
        res = subprocess.run(["node", "-e", script, *files], capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        values = json.loads(res.stdout)
        for path in self.WEEKLY:
            self.assertEqual(values[str(ROOT / path)], ["32.0h", "6.4h"], path)
        for path in self.COMPREHENSIVE:
            self.assertEqual(values[str(ROOT / path)], ["229.42h", "13,077원"], path)


class ReviewRegressionTest(unittest.TestCase):
    """T17 — PR A 독립 리뷰(2026-10-15) 지적의 회귀. 각 테스트 이름의 H·M·L 번호가 리뷰 항목이다."""

    def test_t17_h1_converter_params_use_the_daily_definition(self):
        """실제 경로의 변환기는 주 합계를 1일 × 근무일수로 늘 채운다 — 그 값만 보면 주 3일 × 8시간의 1일 소정이 4.8시간이었다."""
        from types import SimpleNamespace
        from app.core.pipeline import _analysis_to_extract_params, _run_calculator
        for days, daily, floor in ((3, 8, "8h × 80% = 66,048원"), (6, 6, "6h × 80% = 49,536원"), (4, 5, "5h × 80% = 41,280원")):
            with self.subTest(days=days, daily=daily):
                info = {"wage_type": "시급", "wage_amount": 10320, "weekly_work_days": days, "daily_work_hours": daily,
                        "start_date": "2024-09-01", "end_date": "2026-09-30", "age": 30, "reference_year": 2026}
                params = _analysis_to_extract_params(SimpleNamespace(extracted_info=info, calculation_types=["unemployment"],
                                                                     requires_calculation=True))
                self.assertEqual(params["weekly_total_hours"], days * daily)
                out = _run_calculator(params, f"주 {days}일 하루 {daily}시간 일하다 권고사직으로 퇴사했어요. 실업급여는?")
                self.assertIn(f"1일 소정근로시간 {floor}", out)

    def test_t17_h2_unknown_composition_shows_both_pay_readings(self):
        out = card({"wage_type": "월급", "business_size": "5인이상", "wage_amount": 2700000,
                    "calculation_types_kr": ["퇴직금", "4대보험"], "weekly_work_days": 5, "daily_work_hours": 10,
                    "start_date": "2023-01-02", "end_date": "2026-01-01"},
                   "월급 270만원, 주 5일 하루 10시간 근무, 2023년 1월 2일 입사 2026년 1월 1일 퇴사, 직원 10명. 퇴직금과 4대보험은?")
        self.assertIn("퇴직금: 10,400,136원(연장수당 별도) 또는 7,923,913원(월급에 포함)", out)
        self.assertIn("세전 월 급여: 3,543,750원(연장수당 별도) 또는 2,700,000원(월급에 포함)", out)
        self.assertNotIn("월 실수령액(세후):", out)          # 머리줄은 한 값을 단정한다
        self.assertNotIn("월 총 예상 수령액", out.split("── 계산식 ──")[0])
        self.assertIn("두 값을 적었습니다", out)

    def test_t17_h3_annual_and_daily_inclusion_statements(self):
        annual = card({"wage_type": "연봉", "business_size": "5인이상", "wage_amount": 36000000, "calculation_types_kr": ["퇴직금"],
                       "weekly_work_days": 5, "daily_work_hours": 10, "start_date": "2023-01-02", "end_date": "2026-01-01"},
                      "연봉 3,600만원이고 연장수당이 연봉에 포함돼 있어요. 주 5일 하루 10시간 일합니다. 퇴직금은?")
        self.assertIn("연봉 36,000,000원을 12로 나눈 월 3,000,000원으로 계산했습니다", annual)
        self.assertNotIn("11,555,707", annual)
        daily = card({"wage_type": "일급", "business_size": "5인이상", "wage_amount": 120000, "calculation_types_kr": ["퇴직금"],
                      "weekly_work_days": 5, "daily_work_hours": 10, "start_date": "2023-01-02", "end_date": "2026-01-01"},
                     "일당 12만원에 연장근무 수당까지 다 포함이라고 들었어요. 주 5일 하루 10시간 일해요. 퇴직금은?")
        self.assertIn("일급 기준 시급(포함 수당 때문에 통상시급 아님): 15,000원", daily)
        self.assertIn("그 수당이 섞인 일급을 1일 소정근로시간으로 나눈 값", daily)
        self.assertNotIn("월 총 예상 수령액", daily)
        self.assertNotIn("12,050,950", daily)

    def test_t17_h4_l1_regime_signal_words(self):
        from app.core.pipeline import _hour_regime_signal
        guard = "감시·단속적 근로(적용 제외 승인)"
        for q in ("아파트 경비로 24시간 격일제 근무합니다.", "경비업체 소속으로 아파트에서 24시간 맞교대 근무해요.",
                  "현재 야간 시설경비를 하고 있습니다.", "경비대원 연차수당 관련 문의"):
            self.assertEqual(_hour_regime_signal(q), guard, q)
        for q in ("월급날 사장이 잠수 탔어요", "이사는 그돈을가지고 잠수탐", "청소년수련관 시설관리직", "축산물 가공 공장 생산직",
                  "농업회사법인 식품공장에서 포장 일", "아파트 경비비가 올랐어요", "회사 경비 절감 차원에서", "건축사무소 입니다"):
            self.assertIsNone(_hour_regime_signal(q), q)
        self.assertEqual(_hour_regime_signal("작물 재배를 주업으로 하는 농업법인"), "농림·축산·수산 사업")
        self.assertEqual(_hour_regime_signal("근로기준법 제63조 적용 사업장"), "근로시간 적용 제외(근로기준법 제63조)")
        # '탄력근무(제)'는 일부러 신호로 둔다 — 탄력적 근로시간제를 그렇게 부르는 질문이 많다(코퍼스 30건)
        self.assertIsNotNone(_hour_regime_signal("3개월 이내 탄력근무제 시행 시 근로시간"))
        out = card(dict(HOURLY, wage_amount=10320, calculation_types_kr=["주휴수당", "연장수당"], weekly_work_days=3.5,
                        daily_work_hours=24), "아파트 경비로 24시간 격일제 근무합니다. 시급 10,320원이에요. 주휴수당이랑 연장수당은요?")
        self.assertIn("근로시간 제도 확인 필요", out)
        self.assertNotIn("연장수당: ", out)

    def test_t17_l3_minor_limits(self):
        held = card(dict(HOURLY, wage_amount=10320, calculation_types_kr=["주휴수당"], weekly_work_days=5, daily_work_hours=8),
                    "고등학생인데 편의점에서 하루 8시간 주 5일 알바해요. 시급 10,320원. 주휴수당은?")
        self.assertIn("1일 7시간·1주 35시간을 넘지 못해(근로기준법 제69조)", held)
        self.assertIn("근로시간 제도 확인 필요", held)
        within = card(dict(HOURLY, wage_amount=10320, calculation_types_kr=["주휴수당"], weekly_work_days=5, daily_work_hours=7),
                      "고등학생인데 편의점에서 하루 7시간 주 5일 알바해요. 시급 10,320원. 주휴수당은?")
        self.assertNotIn("근로시간 제도 확인 필요", within)

    def test_t17_m1_stated_separate_premium(self):
        from app.core.pipeline import _states_premium_paid_separately
        self.assertTrue(_states_premium_paid_separately("월급 270만원이고 연장수당은 별도로 받아요."))
        self.assertTrue(_states_premium_paid_separately("월급 270만원(연장수당은 따로 받음), 주 5일"))
        self.assertFalse(_states_premium_paid_separately("연장수당을 따로 받은 적은 없습니다."))
        self.assertFalse(_states_premium_paid_separately("연장수당은 별도로 받지 못했어요."))
        self.assertFalse(_states_premium_paid_separately("주휴수당과 연장수당을 각각 계산해 주세요."))
        base = {"wage_type": "월급", "business_size": "5인이상", "wage_amount": 2700000, "calculation_types_kr": ["최저임금"],
                "weekly_work_days": 5, "daily_work_hours": 10}
        sep = card(base, "월급 270만원이고 연장수당은 별도로 받아요. 주 5일 하루 10시간 근무, 직원 10명. 최저임금 위반인가요?")
        self.assertIn("최저임금 충족: ✅ 충족", sep)
        self.assertNotIn("또는 9,863원", sep)
        self.assertNotIn("구성을 몰라", sep)                               # D4 안내·총액 숨김도 없다
        self.assertIn("월 총 예상 수령액(세전): 3,543,750원", sep)
        none = card(base, "월급 270만원, 주 5일 하루 10시간 일하고 연장수당을 따로 받은 적은 없습니다. 최저임금 위반인가요?")
        self.assertIn("최저임금 충족: ⏸ 판정 보류", none)

    def test_t17_m2_fixed_overtime_allowance_is_not_added_twice(self):
        base = dict(HOURLY, calculation_types_kr=["주휴수당", "퇴직금"], weekly_work_days=5, daily_work_hours=10,
                    start_date="2023-01-02", end_date="2026-01-01")
        q = "시급 12,000원에 하루 10시간 주 5일, 고정연장수당을 받아요. 직원 10명. 2023년 1월 2일 입사 2026년 1월 1일 퇴사."
        low = card(dict(base, fixed_allowances=[{"name": "고정연장수당", "amount": 500000, "condition": "없음"}]), q)
        self.assertIn("월 총 예상 수령액(세전): 3,285,000원", low)          # 2,502,857 + max(500,000, 782,143)
        self.assertIn("3개월 평균임금: 107,120원/일", low)
        self.assertIn("계산한 금액이 고정연장수당보다 월 282,143원 많습니다", low)
        high = card(dict(base, fixed_allowances=[{"name": "고정연장수당", "amount": 1000000, "condition": "없음"}]), q)
        self.assertIn("월 총 예상 수령액(세전): 3,502,857원", high)         # 2,502,857 + max(1,000,000, 782,143)
        self.assertIn("3개월 평균임금: 114,224원/일", high)                 # 평균임금도 같은 월액(3,502,857 × 3 ÷ 92)
        self.assertNotIn("계산한 금액이 고정연장수당보다", high)

    def test_t17_m3_platform_worker_gets_no_premium_addition(self):
        out = card({"wage_type": "월급", "wage_amount": 3000000, "is_platform_worker": True, "calculation_types_kr": ["4대보험"],
                    "weekly_work_days": 5, "daily_work_hours": 8, "weekly_overtime_hours": 10},
                   "배달 라이더(특고)로 월 300만원 벌어요. 하루 8시간 주 5일에 매주 10시간 더 일해요. 4대보험은?")
        self.assertIn("세전 월 급여: 3,000,000원", out)
        self.assertNotIn("구성을 몰라", out)
        self.assertNotIn("937,500", out)

    def test_t17_m4_exact_path_total_is_the_stated_total(self):
        out = card({"wage_type": "월급", "business_size": "5인이상", "wage_amount": 2700000,
                    "calculation_types_kr": ["최저임금", "퇴직금"], "weekly_work_days": 5, "daily_work_hours": 10,
                    "start_date": "2023-01-02", "end_date": "2026-01-01"},
                   "월급 2,700,000원(기본급 2,096,270원, 고정연장수당 603,730원)이고 주 5일 하루 10시간 일해요. 직원 10명. "
                   "2023년 1월 2일 입사해 2026년 1월 1일 퇴사했어요. 최저임금 위반인지, 퇴직금은 얼마인지 궁금해요.")
        self.assertIn("월 총 예상 수령액(세전): 2,700,000원", out)
        self.assertIn("기본급·산입 수당 외 몫(연장수당 등) 603,730원이 위에서 계산한 연장·야간·휴일 근로 임금 월 655,084원", out)

    def test_t17_l2_daily_worker_basic_amount(self):
        out = card({"wage_type": "일급", "wage_amount": 80000, "business_size": "5인이상", "calculation_types_kr": ["실업급여"],
                    "weekly_work_days": 5, "daily_work_hours": 4, "start_date": "2024-09-01", "end_date": "2026-09-30", "age": 30},
                   "건설 일용직으로 일당 8만원, 하루 4시간 주 5일 일하다 2026년 9월 30일 일이 끊겼어요. 실업급여는?")
        self.assertIn("이직 당시 일용근로자는 평균임금을 통상임금과 비교하지 않습니다(고용보험법 제45조 제2항 단서)", out)
        self.assertIn("구직급여 일액: 40,807원/일", out)

    def test_t17_l4_hours_are_printed_short(self):
        out = card({"wage_type": "일급", "business_size": "5인이상", "wage_amount": 70000, "calculation_types_kr": ["최저임금"],
                    "weekly_work_days": 6, "daily_work_hours": 7}, "일당 7만원에 주 6일 하루 7시간 일해요. 최저임금은요?")
        self.assertIn("일급 70,000원 ÷ 6.6667h", out)
        self.assertNotRegex(out, r"\d\.\d{5,}")

    def test_t17_r2_separate_statement_needs_a_positive_paid_clause(self):
        """2차 리뷰 H2 — 부정·의문·연차수당은 '연장 별도' 진술이 아니다(예전 규칙은 아래 여섯 문장을 모두 진술로 읽었다)."""
        from app.core.pipeline import _states_premium_paid_separately as sep
        for q in ("연장수당은 따로 없고 월급만 받아요", "회사가 연장수당을 별도로 지급하지 않고 있어요",
                  "연장수당은 따로 받을 수 있나요?", "연차수당은 따로 받아요", "연장수당은 따로 안 줘요",
                  "연장수당은 별도라고 들었는데 실제로는 안 나와요"):
            self.assertFalse(sep(q), q)
        for q in ("연장수당은 별도로 받아요", "(연장수당은 따로 받음)", "야근수당은 별도로 지급받고 있습니다",
                  "연장수당은 따로 받는데 최저임금 위반인가요?"):
            self.assertTrue(sep(q), q)
        out = card({"wage_type": "월급", "business_size": "5인이상", "wage_amount": 2700000, "calculation_types_kr": ["최저임금"],
                    "weekly_work_days": 5, "daily_work_hours": 10}, "월급 270만원, 주 5일 하루 10시간. 연장수당은 따로 없고 월급만 받아요.")
        self.assertIn("최저임금 충족: ⏸ 판정 보류", out)

    def test_t17_r2_daily_wage_b_total(self):
        """2차 리뷰 M1 — 일급의 B 총액은 B 통상임금 + B 시급으로 센 연장 등이다(주휴를 연장분이 섞인 일급으로 세지 않는다)."""
        out = card({"wage_type": "일급", "business_size": "5인이상", "wage_amount": 120000, "calculation_types_kr": ["4대보험"],
                    "weekly_work_days": 5, "daily_work_hours": 10}, "일당 12만원, 하루 10시간 주 5일 일해요. 4대보험은요?")
        self.assertIn("또는 2,986,364원(일급에 포함)", out)

    def test_t17_r2_daily_inclusion_holds_pay_amounts(self):
        """2차 리뷰 M2 — 일급 '포함' 진술 보류는 월 보수·소득 금액도 뺀다(세후 실수령액 머리줄도 없다)."""
        out = card({"wage_type": "일급", "business_size": "5인이상", "wage_amount": 120000,
                    "calculation_types_kr": ["4대보험", "실업급여"], "weekly_work_days": 5, "daily_work_hours": 10,
                    "start_date": "2024-09-01", "end_date": "2026-09-30", "age": 30},
                   "일당 12만원에 연장근무 수당까지 다 포함이라고 들었어요. 하루 10시간 주 5일 일하다 권고사직했어요. 4대보험이랑 실업급여는?")
        self.assertNotIn("월 실수령액(세후):", out)
        self.assertNotIn("세전 월 급여: 3,128,571원", out)
        self.assertIn("월 보수·소득으로 계산하는 항목", out)

    def test_t17_r2_minor_signal_is_about_the_worker(self):
        """2차 리뷰 M3 — 자녀·대상·기관·과거('고등학생 때')는 근로자 본인이 연소자라는 신호가 아니다."""
        from app.core.pipeline import _hour_regime_signal
        for q in ("고등학생 딸이 있는 직장인인데 하루 8시간 주 5일 일해요", "미성년 자녀를 둔 엄마예요",
                  "청소년 캠프 운영 기관에서 일해요", "고등학생 때 아르바이트를 했는데요"):
            self.assertIsNone(_hour_regime_signal(q), q)
        for q in ("고등학생인데 편의점에서 하루 8시간 일해요", "미성년자 아르바이트생입니다"):
            self.assertEqual(_hour_regime_signal(q), "연소자(만 18세 미만)", q)

    def test_t17_r2_other_signal_and_daily_worker_words(self):
        """2차 리뷰 L2·L3 — '넘어선'의 '어선', 짓지 않는 '농사', 부정·전환 문맥의 '일용직'."""
        from app.core.pipeline import _hour_regime_signal, _states_daily_worker
        self.assertIsNone(_hour_regime_signal("주 52시간을 넘어선 근무"))
        self.assertIsNone(_hour_regime_signal("농사는 짓지 않고 공장에서 일해요"))
        self.assertEqual(_hour_regime_signal("원양 어선에서 일합니다"), "농림·축산·수산 사업")
        self.assertFalse(_states_daily_worker("일용직이 아니라 정규직으로 월급 300만원 받아요"))
        self.assertFalse(_states_daily_worker("일용직으로 일하다가 상용직으로 전환됐어요"))
        self.assertTrue(_states_daily_worker("건설 일용직으로 일당 8만원 받았어요"))

    def test_t17_c27_stated_weekly_days(self):
        """C27 — 의도분석이 놓친 '주 N일'을 질문에서 읽고, 그래도 모르면 주 5일 가정을 밝힌다(PR B 실측 calc-03 r2)."""
        from app.core.pipeline import _stated_weekly_days
        self.assertEqual(_stated_weekly_days("평균 주 3.5일 근무합니다"), 3.5)
        self.assertEqual(_stated_weekly_days("주 5일제 회사예요"), 5.0)
        for q in ("지난주 3일 동안 25시간 일했어요", "이번 주 2일 근무했어요", "주 3일 일하다 주 5일로 늘었어요",
                  "주 6일 근무, 주 1일 휴무"):
            self.assertIsNone(_stated_weekly_days(q), q)
        out = card(dict(HOURLY, calculation_types_kr=["주휴수당"], daily_work_hours=16),
                   "공장에서 격일제로 근무합니다. 하루 16시간(휴게시간 제외) 일하고 다음 날은 쉬어서 평균 주 3.5일 근무합니다. "
                   "시급 12,000원이고 직원은 20명입니다.")
        self.assertIn("주휴: min(28h ÷ 5, 8h) = 5.6h", out)
        assumed = card(dict(HOURLY, calculation_types_kr=["주휴수당"], daily_work_hours=8), "시급 12,000원, 하루 8시간 일해요. 주휴수당은요?")
        self.assertIn("근무일수를 질문에서 확인하지 못해 주 5일로 계산", assumed)


if __name__ == "__main__":
    unittest.main()
