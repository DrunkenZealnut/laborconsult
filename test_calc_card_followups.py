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
- T11 수습 감액 요건(F3)
- T12 노무제공자 최저임금(F4)
- T13 최저임금 상태·헤더(D6·F4b)
- T14 해고예고 예외(F7)
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
        # 호출자의 입력은 그대로다 — 사본에서 나눈다(CodeRabbit PR #115: 고친 일정을 다시 넘겨도 옛 분리 결과가 남았다)
        self.assertIsNone(inp.hour_split)
        self.assertEqual((inp.schedule.daily_work_hours, inp.schedule.weekly_overtime_hours), (10, 0))


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
        # PR B — 수습 감액 요건(F3), 노무제공자(F4), 해고예고 예외(F7)
        ("mw_act_5", "1년 이상의 기간을 정하여 근로계약을 체결하고 수습 중에 있는 근로자로서 수습을 시작한 날부터 3개월 이내인 사람"),
        ("mw_act_5", "단순노무업무로 고용노동부장관이 정하여 고시한 직종에 종사하는 근로자는 제외한다"),
        ("mw_enf_3", "시간급 최저임금액(최저임금으로 정한 금액을 말한다. 이하 같다)에서 100분의 10을 뺀 금액"),
        ("mw_act_2", "「근로기준법」 제2조에 따른 근로자, 사용자 및 임금을 말한다"),
        ("lsa_act_26", "근로자가 계속 근로한 기간이 3개월 미만인 경우"),
        ("lsa_act_26", "천재ㆍ사변, 그 밖의 부득이한 사유로 사업을 계속하는 것이 불가능한 경우"),
        ("lsa_act_26", "근로자가 고의로 사업에 막대한 지장을 초래하거나 재산상 손해를 끼친 경우로서 고용노동부령으로 정하는 사유"),
        ("civ_act_160", "최종의 월에 해당일이 없는 때에는 그 월의 말일로 기간이 만료한다"),
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


class ProbationTest(unittest.TestCase):
    """T11 — 수습 감액은 요건 셋을 질문에서 확인했을 때만(최저임금법 제5조 제2항·시행령 제3조, D5). main e76ab02는 요건 미상을
    충족으로 보고 수습 기간 기본값 3개월을 써서, 수습 6개월 중 5개월째에도 90% 기준으로 '충족'을 냈다(R11)."""

    BASE = {"calculation_types_kr": ["최저임금"], "wage_type": "시급", "wage_amount": 9300, "is_probation": True,
            "weekly_work_days": 5, "daily_work_hours": 8, "business_size": "5인이상"}

    def test_t11_r10_unknown_requirements_hold(self):
        out = card(self.BASE, "카페에서 수습 기간이라 시급 9,300원을 받고 주 5일 하루 8시간 일합니다. 최저임금 위반 아닌가요?")
        self.assertIn("최저임금 충족: ⏸ 판정 보류", out)
        self.assertIn("최저임금 기준: 10,320원 또는 수습 감액 9,288원(요건을 모두 갖춘 경우)", out)
        self.assertIn("실질시급: 9,300원\n", out)                      # 실질시급은 하나다 — '또는 0원'이 붙지 않는다
        for label in ("1년 이상의 기간을 정한 근로계약", "수습을 시작한 날부터 3개월 이내", "단순노무업무로 고시한 직종이 아님"):
            self.assertIn(label, out)
        self.assertIn("2026년 최저임금: 10,320원/h", out)
        self.assertNotRegex(out, r"최저임금(?:은|이|:)\s*9,288원")    # 감액값을 '최저임금'이라 부르지 않는다

    def test_t11_r11_three_months_passed(self):
        out = card(self.BASE, "정규직으로 입사해 수습 기간 6개월 중 5개월째인데 아직 시급 9,300원을 받고 있습니다. 주 5일 하루 8시간 일합니다.")
        self.assertIn("최저임금 충족: ❌ 미달", out)
        self.assertIn("부족분(월): 212,743원", out)
        self.assertIn("수습을 시작한 날부터 3개월이 지나 최저임금을 감액할 수 없습니다", out)

    def test_t11_all_requirements_met(self):
        out = card(dict(self.BASE, contract_months=12, occupation_code="3"), "1년 계약으로 입사해 수습 2개월째, 사무직입니다.")
        self.assertIn("최저임금 충족: ✅ 충족", out)
        self.assertIn("수습 감액 최저임금: 10,320원 × 90% = 9,288원/h", out)
        self.assertIn("충족: 9,300원 ≥ 9,288원(수습 감액 최저임금)", out)
        self.assertIn("2026년 최저임금: 10,320원/h", out)                  # 고시 금액은 그대로 — 감액값은 따로 적는다
        self.assertNotRegex(out, r"최저임금(?:은|이|:)\s*9,288원")

    def test_t11_requirement_failures(self):
        cases = (({"contract_months": 12, "occupation_code": "9"}, "1년 계약 수습 2개월째, 청소 업무입니다.",
                  "단순노무업무로 고용노동부장관이 고시한 직종(한국표준직업분류 대분류 9)은 수습이어도"),
                 ({"contract_months": 6, "occupation_code": "3"}, "6개월 계약 수습 2개월째, 사무직입니다.",
                  "근로계약기간이 6개월로 1년 미만이라"),
                 ({"contract_months": 6}, "정규직 전환 전 6개월 계약직이고 수습 2개월째입니다.", "근로계약기간이 6개월로 1년 미만이라"))
        for extra, query, reason in cases:
            with self.subTest(query):
                out = card(dict(self.BASE, **extra), query)
                self.assertIn("최저임금 충족: ❌ 미달", out)
                self.assertIn(reason, out)
                self.assertNotIn("수습 감액 최저임금: ", out)

    def test_t11_eighty_percent_is_a_violation_even_with_the_reduction(self):
        out = card(dict(self.BASE, wage_amount=8256, contract_months=12, occupation_code="3"),
                   "1년 계약 수습 2개월째, 최저임금의 80%인 시급 8,256원을 받습니다.")
        self.assertIn("최저임금 충족: ❌ 미달", out)
        self.assertIn("최저임금 미달: 실질시급 8,256원 < 9,288원(수습 감액 최저임금)", out)

    def test_t11_reduced_minimum_is_labeled_in_split_warnings(self):
        """감액 기준이 판정 기준이면 갈림 안내에도 라벨을 단다(2차 리뷰 L5) — 월급 230만 원·하루 10시간이면 연장 별도 11,027원,
        연장 포함 역산 8,402원이라 수습 감액 최저임금 9,288원을 사이에 두고 갈린다."""
        out = card({"wage_type": "월급", "wage_amount": 2300000, "is_probation": True, "contract_months": 12,
                    "occupation_code": "3", "weekly_work_days": 5, "daily_work_hours": 10, "business_size": "5인이상",
                    "calculation_types_kr": ["최저임금"]}, "1년 계약 수습 2개월째, 월급 230만원, 하루 10시간 주 5일 사무직입니다.")
        self.assertIn("이므로 수습 감액 최저임금(9,288원) 충족 여부가 갈립니다", out)
        self.assertNotRegex(out, r"최저임금(?:은|이|:)\s*9,288원")

    def test_t11_unknown_requirements_same_verdict_both_ways(self):
        """요건을 몰라도 감액 기준·고시 기준의 판정이 같으면 판정한다(보류는 갈릴 때만)."""
        ok = card(dict(self.BASE, wage_amount=11000), "수습 중이고 시급 11,000원입니다.")
        self.assertIn("최저임금 충족: ✅ 충족", ok)
        low = card(dict(self.BASE, wage_amount=8000), "수습 중이고 시급 8,000원입니다.")
        self.assertIn("최저임금 충족: ❌ 미달", low)
        self.assertIn("요건을 모두 갖추면 부족분은 월", low)

    def test_t11_legal_hint_lists_three_requirements(self):
        from wage_calculator import WageCalculator, WageInput, WageType
        r = WageCalculator().calculate(WageInput(wage_type=WageType.HOURLY, hourly_wage=9300, reference_year=2026,
                                                 is_probation=True), ["minimum_wage", "legal_hints"])
        text = " ".join(r.breakdown["법률 검토 포인트"].values())
        for phrase in ("1년 이상의 기간을 정한 근로계약", "수습을 시작한 날부터 3개월 이내", "단순노무업무로 고용노동부장관이 고시한 직종"):
            self.assertIn(phrase, text)

    def test_t11_requirement_boundaries(self):
        """요건 경계 — 계약 12개월, 수습 시작일부터 3개월, 한국표준직업분류 대분류 9. 계약기간 숫자가 '정규직'보다 먼저다."""
        from wage_calculator import WageInput, WageType
        from wage_calculator.calculators.minimum_wage import _probation_requirements
        mk = lambda **k: WageInput(wage_type=WageType.HOURLY, hourly_wage=9300, is_probation=True, **k)  # noqa: E731
        cases = (({"contract_months": 12}, "contract", True), ({"contract_months": 11}, "contract", False),
                 ({"contract_open_ended": True}, "contract", True),
                 ({"contract_open_ended": True, "contract_months": 6}, "contract", False), ({}, "contract", None),
                 ({"probation_elapsed_months": 3}, "within", True), ({"probation_elapsed_months": 4}, "within", False),
                 ({"probation_months": 3}, "within", True), ({"probation_months": 6}, "within", None),
                 ({"occupation_code": "3"}, "occupation", True), ({"occupation_code": "91"}, "occupation", False),
                 ({}, "occupation", None))
        for kwargs, key, expected in cases:
            with self.subTest(kwargs=kwargs, key=key):
                self.assertIs(_probation_requirements(mk(**kwargs))[key], expected)

    def test_t11_question_terms(self):
        from app.core.pipeline import _probation_terms
        self.assertEqual(_probation_terms("정규직으로 입사해 수습 기간 6개월 중 5개월째입니다"),
                         {"open_ended": True, "length": 6, "elapsed": 5})
        self.assertEqual(_probation_terms("무기계약으로 입사한 지 2개월 된 수습입니다"),
                         {"open_ended": True, "length": None, "elapsed": 2})
        self.assertEqual(_probation_terms("비정규직 수습 중입니다")["open_ended"], False)
        self.assertEqual(_probation_terms("수습 3개월이고 시급 9,300원")["length"], 3)
        # 지금의 계약 형태가 아닌 '정규직'(2차 리뷰 M4)과 '일한 지 N개월'(L4)
        for q in ("정규직 전환을 약속받고 계약직 수습 2개월째입니다", "정규직이 아니라 계약직이고 수습 1개월째예요",
                  "무기계약직 전환 전 수습 기간입니다", "비 정규직 수습입니다"):
            self.assertFalse(_probation_terms(q)["open_ended"], q)
        self.assertEqual(_probation_terms("수습 3개월인데 일한 지 5개월이 됐어요")["elapsed"], 5)


class PlatformWorkerTest(unittest.TestCase):
    """T12 — 노무제공자는 최저임금법의 근로자가 아니어서 판정하지 않는다(최저임금법 제2조, F4). main은 '❌ 미달·노동청 신고·
    3년 이하 징역'을 단정했다(R13)."""

    BASE = {"calculation_types_kr": ["최저임금"], "wage_type": "시급", "is_platform_worker": True, "weekly_work_days": 5,
            "daily_work_hours": 8}

    def test_t12_r12_r13(self):
        for wage, sign, verdict in ((12000, "≥", "충족"), (9000, "<", "미달")):
            with self.subTest(wage=wage):
                out = card(dict(self.BASE, wage_amount=wage), f"배달 라이더(노무제공자)로 시간당 {wage:,}원 법니다. 최저임금 위반인가요?")
                self.assertIn("최저임금 충족: ➖ 해당 없음 — 노무제공자(근로자성이 인정되면 적용)", out)
                self.assertIn(f"실질시급 {wage:,}원 {sign} 10,320원({verdict})입니다", out)
                self.assertIn("최저임금법 제2조", out)
                for banned in ("노동청 신고", "징역", "❌ 미달", "✅ 충족"):
                    self.assertNotIn(banned, out)


class MinimumWageStateTest(unittest.TestCase):
    """T13 — 최저임금 상태(D6)와 헤더(F4b). 계산하지 않았으면 헤더 줄이 없다 — 보류가 아니다.

    보류 네 경로 중 승인 기준 보류(facade blocked)는 test_legal_rule_updates, 구성 진술 보류(파이프라인)는 test_audit50의
    '최저임금 충족: ⏸ 판정 보류' 단언이 지킨다 — 상태를 'held'로 두지 않으면 헤더 줄이 사라져 그 단언이 실패한다."""

    def test_t13_r14_no_header_without_the_check(self):
        out = card({"calculation_types_kr": ["연차수당"], "wage_type": "시급", "wage_amount": 12000, "weekly_work_days": 5,
                    "daily_work_hours": 8, "start_date": "2024-01-01", "business_size": "5인이상"}, "연차수당은 얼마인가요?")
        self.assertTrue(out)
        self.assertNotIn("최저임금 충족", out)

    def test_t13_held_paths_keep_the_header(self):
        from wage_calculator import WageCalculator, WageInput, WageType
        from wage_calculator.result import format_result, format_result_json
        # ① 기준에 따라 판정이 갈림(수습 요건 미상)
        held = WageCalculator().calculate(WageInput(wage_type=WageType.HOURLY, hourly_wage=9300, reference_year=2026,
                                                    is_probation=True), ["minimum_wage"])
        self.assertEqual(held.minimum_wage_state, "held")
        self.assertIn("최저임금 충족: ⏸ 판정 보류", format_result(held))
        # ② 소정근로시간 미확인 — '충족'을 싣지 않는다(PR #114 hold_compliant)
        unknown = WageCalculator().calculate(WageInput(wage_type=WageType.MONTHLY, monthly_wage=3000000, reference_year=2026),
                                             ["minimum_wage"], hold_compliant=("minimum_wage",))
        self.assertEqual(unknown.minimum_wage_state, "held")
        self.assertIn("최저임금 충족: ⏸ 판정 보류", format_result(unknown))
        # ③ JSON
        self.assertEqual(format_result_json(held)["minimum_wage_state"], "held")
        ok = WageCalculator().calculate(WageInput(wage_type=WageType.HOURLY, hourly_wage=12000, reference_year=2026),
                                        ["minimum_wage"])
        self.assertEqual((ok.minimum_wage_state, format_result_json(ok)["minimum_wage_state"]), ("compliant", "compliant"))


class DismissalNoticeTest(unittest.TestCase):
    """T14 — 해고예고 예외는 현행 근로기준법 제26조 단서 세 호뿐이다(F7). main은 조문에 없는 수습·일용·계절 면제를 적용했다."""

    BASE = {"calculation_types_kr": ["해고예고수당"], "wage_type": "월급", "wage_amount": 2500000}

    def test_t14_r16_probation_is_not_exempt(self):
        out = card(dict(self.BASE, is_probation=True, start_date="2026-05-15", end_date="2026-10-15"),
                   "수습으로 2026년 5월 15일에 입사해 월급 250만 원을 받았는데, 10월 15일에 해고 통보를 받았습니다.")
        self.assertIn("해고예고수당: 2,876,712원", out)
        self.assertIn("수습이라는 사정만으로는 해고예고 의무가 면제되지 않습니다", out)
        self.assertNotIn("면제", out.split("수습이라는 사정만으로는")[0])

    def test_t14_r17_under_three_months_is_exempt(self):
        out = card(dict(self.BASE, start_date="2026-08-15", end_date="2026-10-15"),
                   "정규직으로 2026년 8월 15일에 입사해 월급 250만 원을 받고 있는데 10월 15일에 해고 통보를 받았습니다.")
        self.assertIn("해고예고수당: 0원", out)
        self.assertIn("근로기준법 제26조 단서 제1호", out)

    def test_t14_three_month_boundary(self):
        from wage_calculator.calculators.dismissal import _tenure_under_three_months
        from wage_calculator import WageInput, WageType
        mk = lambda **k: WageInput(wage_type=WageType.MONTHLY, monthly_wage=2500000, **k)  # noqa: E731
        self.assertTrue(_tenure_under_three_months(mk(start_date="2026-07-16", end_date="2026-10-15")))
        self.assertFalse(_tenure_under_three_months(mk(start_date="2026-07-15", end_date="2026-10-15")))
        # 그달에 같은 날이 없으면 다음 달 1일이 경계다(민법 제160조 제3항 — 종료일은 마지막 근무일 다음 날)
        for start, end, under in (("2025-11-30", "2026-02-28", True), ("2025-11-30", "2026-03-01", False),
                                  ("2026-01-31", "2026-04-30", True), ("2026-01-31", "2026-05-01", False),
                                  ("2026-02-01", "2026-04-30", True), ("2026-02-01", "2026-05-01", False)):
            self.assertIs(_tenure_under_three_months(mk(start_date=start, end_date=end)), under, (start, end))
        self.assertTrue(_tenure_under_three_months(mk(tenure_months=2)))
        self.assertIsNone(_tenure_under_three_months(mk()))

    def test_t14_start_date_without_end_date(self):
        """종료일이 없으면 오늘(KST)로 본다 — kst_today()가 문자열이라 비교에서 TypeError가 나 카드 전체가 사라졌다(2차 리뷰 H1)."""
        from unittest import mock
        with mock.patch("wage_calculator.calculators.dismissal.kst_today", return_value="2026-10-15"):
            five = card(dict(self.BASE, start_date="2026-05-15"), "5월 15일 입사했는데 오늘 해고 통보를 받았어요.")
            two = card(dict(self.BASE, start_date="2026-08-15", calculation_types_kr=["해고예고수당", "퇴직금", "연차수당"]),
                       "8월 15일 입사했는데 오늘 해고 통보를 받았어요.")
        self.assertIn("해고예고수당: 2,876,712원", five)
        self.assertIn("해고예고수당: 0원", two)
        self.assertIn("근로기준법 제26조 단서 제1호", two)

    def test_t14_period_phrase_is_counted_in_months(self):
        """'입사 3개월'은 날짜로 바꾸지 않고 개월 수로 센다 — 30일 × 3으로 바꾸면 3개월 미만(면제)이 됐다."""
        three = card(dict(self.BASE, start_date="3개월"), "입사한 지 3개월 됐는데 오늘 해고 통보를 받았어요.")
        two = card(dict(self.BASE, start_date="2개월"), "입사한 지 2개월 됐는데 오늘 해고 통보를 받았어요.")
        self.assertIn("해고예고수당: 2,876,712원", three)
        self.assertIn("해고예고수당: 0원", two)
        from app.core.pipeline import _period_months
        self.assertEqual((_period_months("1년 2개월"), _period_months("3개월"), _period_months("2024년 3월")), (14, 3, None))

    def test_t14_unknown_start_date(self):
        out = card(dict(self.BASE), "월급 250만 원인데 오늘 갑자기 해고 통보를 받았습니다. 해고예고수당은?")
        self.assertIn("입사일을 몰라 계속근로기간을 확인하지 못했습니다", out)
        self.assertIn("해고예고수당: 2,876,712원", out)

    def test_t14_other_exemptions(self):
        from wage_calculator import WageCalculator, WageInput, WageType
        from wage_calculator.models import WorkType
        base = dict(wage_type=WageType.MONTHLY, monthly_wage=2500000, reference_year=2026, tenure_months=6)
        force = WageCalculator().calculate(WageInput(**base, is_force_majeure=True), ["dismissal"])
        self.assertIn("근로기준법 제26조 단서 제2호·제3호", force.legal_basis)
        for extra in ({"is_seasonal_worker": True}, {"work_type": WorkType.DAILY_WORKER}, {"is_probation": True}):
            with self.subTest(extra):
                r = WageCalculator().calculate(WageInput(**base, **extra), ["dismissal"])
                self.assertEqual(r.summary.get("해고예고수당"), "2,876,712원")
                self.assertFalse(any("단서 4호" in b or "수습 3개월" in b or "1개월 미만" in b for b in r.legal_basis))
                self.assertTrue(any("사정만으로는 해고예고 의무가 면제되지 않습니다" in w for w in r.warnings))


if __name__ == "__main__":
    unittest.main()
