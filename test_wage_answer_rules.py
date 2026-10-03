"""임금 답변 규칙 회귀 테스트 (2026-10-02 실측 결함 5종, API 키·네트워크 불요).

실측: 시급 없는 단시간 주휴 질문("주3일×6시간")에서
  ① claude-opus-5-5가 긴 컨텍스트에서 첫 토큰 20초 초과 → o3 폴백(짧은 테스트 호출은 통과)
  ② 시급이 없다고 주휴 계산기를 통째로 제외 → LLM이 "주휴 6시간"(맞는 값 3.6시간)
  ③ 최저시급 사실 블록 미주입(판정이 영문 키를 한글로 찾음) → o3가 예시 시급 10,000원
  ④ 판례 정규식이 "2026년 9월"을 판례번호로 오인해 답변에서 지움
"""
from __future__ import annotations

import inspect
import unittest
import unittest.mock
from types import SimpleNamespace as NS

from app.core import pipeline as pl


class WagelessWeeklyHolidayTest(unittest.TestCase):
    def test_part_time_hours_are_proportional(self):
        block = pl._wageless_weekly_holiday(3, 6)
        self.assertIn("3.6h", block)
        self.assertIn("18h ÷ 40h × 8h", block)
        self.assertNotIn("원", block.replace("통상임금", ""), "시급 없는 블록에 금액이 생기면 가정값이 확정처럼 읽힌다")

    def test_full_week_and_ineligible(self):
        self.assertIn("= 4h", pl._wageless_weekly_holiday(5, 4))
        self.assertIn("미발생", pl._wageless_weekly_holiday(2, 7))
        self.assertIn("15h", pl._wageless_weekly_holiday(2, 7))

    def test_missing_or_invalid_inputs_return_none(self):
        for days, daily in ((None, 6), (3, None), (0, 6), (8, 6), (3, 25), ("x", 6)):
            self.assertIsNone(pl._wageless_weekly_holiday(days, daily), (days, daily))

    def test_single_source_with_calculator(self):
        """시급 유무에 따라 같은 근무형태의 주휴시간이 달라지면 안 된다."""
        from wage_calculator import WageCalculator
        from wage_calculator.models import WageInput, WageType, WorkSchedule
        for days, daily in ((3, 6), (5, 4), (4, 7.5), (6, 8), (5, 9)):
            inp = WageInput(wage_type=WageType.HOURLY, hourly_wage=10320,
                            schedule=WorkSchedule(daily_work_hours=daily, weekly_work_days=days))
            res = WageCalculator().calculate(inp, ["weekly_holiday"])
            calc_hours = float(res.breakdown["주휴수당"]["주휴 인정 시간"].rstrip("h"))
            self.assertIn(f"× {calc_hours:g}h", pl._wageless_weekly_holiday(days, daily), (days, daily))

    def test_run_calculator_returns_hours_block_without_wage(self):
        out = pl._run_calculator({"needs_calculation": True, "calculation_types_kr": ["주휴수당"],
                                  "weekly_work_days": 3, "daily_work_hours": 6}, "주휴수당")
        self.assertIn("3.6h", out)

    def test_hours_block_kept_alongside_other_wageless_calculators(self):
        out = pl._run_calculator({"needs_calculation": True,
                                  "calculation_types_kr": ["주휴수당", "근로시간"],
                                  "weekly_work_days": 3, "daily_work_hours": 6}, "주휴수당 근로시간")
        self.assertIn("3.6h", out)
        self.assertIn("주휴시간 산정", out.split("\n\n", 1)[0])
        self.assertGreater(len(out.split("\n\n", 1)), 1, "시급 없는 계산기(working_hours) 결과도 함께 와야 한다")

    def test_platform_worker_gets_no_holiday_block(self):
        out = pl._run_calculator({"needs_calculation": True, "calculation_types_kr": ["주휴수당"],
                                  "weekly_work_days": 3, "daily_work_hours": 6,
                                  "is_platform_worker": True}, "주휴수당")
        self.assertNotIn("주휴시간 산정", out or "")

    def test_assumed_days_do_not_produce_hours(self):
        """근무일수를 5일로 가정한 경우는 확정 블록을 만들지 않는다 — 가정이 확정처럼 읽힌다."""
        out = pl._run_calculator({"needs_calculation": True, "calculation_types_kr": ["주휴수당"],
                                  "weekly_total_hours": 18}, "주휴수당")
        self.assertIsNone(out)


class MinwageFactsTest(unittest.TestCase):
    def test_wage_topics_in_english_keys_trigger_facts(self):
        for t in ("weekly_holiday", "overtime", "annual_leave", "minimum_wage"):
            self.assertTrue(pl._wants_minwage_facts("질문", NS(calculation_types=[t])), t)
        self.assertFalse(pl._wants_minwage_facts("해고 예고", NS(calculation_types=["dismissal"])))
        self.assertTrue(pl._wants_minwage_facts("최저시급 얼마", None))

    def test_block_forbids_round_number_examples(self):
        block = pl._build_minwage_facts("주휴수당", NS(calculation_types=["weekly_holiday"]))
        self.assertIn("10,320", block)
        self.assertIn("10,000원 같은 어림값", block)


class PromptRulesTest(unittest.TestCase):
    def test_rules_appended_on_both_answer_branches(self):
        """한쪽 프롬프트 본문에만 넣으면 다른 분기에서 빠진다 — 접미 지점이 분기 뒤여야 한다."""
        from app.templates.prompts import WAGE_CALC_RULES
        self.assertIn("18 ÷ 40 × 8 = 3.6시간", WAGE_CALC_RULES)
        self.assertIn("주 5일 이상", WAGE_CALC_RULES)      # 계산기와 같은 분기(5일 이상 = 1일 시간, 최대 8)
        src = inspect.getsource(pl)
        branch = src.index("system_prompt = SYSTEM_PROMPT_TEMPLATE.format(")
        append = src.index("system_prompt = system_prompt + WAGE_CALC_RULES")
        self.assertGreater(append, branch)


class CitationRegexTest(unittest.TestCase):
    def test_dates_are_not_case_numbers(self):
        from app.core.citation_validator import _PREC_PATTERN as P
        for text in ("2026년9월", "2026년 9월 30일", "2025년 12월 31일까지"):
            self.assertEqual(P.findall(text), [], text)

    def test_real_case_codes_still_match(self):
        from app.core.citation_validator import _PREC_PATTERN as P
        for text in ("대법원 2023다302838", "2021헌마1234", "2014가합5678", "2020구합123",
                     "2018두12345", "2019도1234", "2017누12", "2016나1",
                     "2024차123", "2020초기456", "2019주1"):     # 차=독촉 등 한 글자 부호
            self.assertEqual(len(P.findall(text)), 1, text)


class AnswerEffortTest(unittest.TestCase):
    """Claude 5 계열은 effort 미지정 시 답 전에 길게 추론해 읽기 타임아웃(20초)에 걸린다(실측 24.7~55.6초)."""

    def _kwargs(self, model, events=()):
        captured = {}

        class Stream:
            def __enter__(self):
                return iter(events)

            def __exit__(self, *a):
                return False

        class Messages:
            def stream(self, **kw):
                captured.update(kw)
                return Stream()

        class Client:
            def with_options(self, **_):
                return NS(messages=Messages())

        captured["_out"] = list(pl._stream_claude([{"role": "user", "content": "q"}], "s",
                                                  NS(claude_client=Client()), model=model))
        return captured

    def test_effort_sent_for_claude_5_models(self):
        from app.config import ANSWER_EFFORT
        for m in ("claude-sonnet-5", "claude-sonnet-5-5", "claude-opus-5-5"):
            kw = self._kwargs(m)
            self.assertEqual(kw.get("output_config"), {"effort": ANSWER_EFFORT}, m)
            # summarized가 아니면 추론 중 바이트가 끊겨 읽기 타임아웃(실측 공백 25.9초)
            self.assertEqual(kw.get("thinking"), {"type": "adaptive", "display": "summarized"}, m)

    def test_thinking_events_become_throttled_heartbeats_and_never_leak(self):
        events = [NS(type="thinking", thinking="비밀 추론")] * 3 + [
            NS(type="text", text="답변"), NS(type="content_block_stop")]
        with unittest.mock.patch.object(pl, "THINKING_HEARTBEAT_SECONDS", 0.0):
            out = self._kwargs("claude-opus-5-5", events)["_out"]
        self.assertEqual(out, ["", "", "", "답변"])
        self.assertNotIn("비밀 추론", "".join(out))
        with unittest.mock.patch.object(pl, "THINKING_HEARTBEAT_SECONDS", 3600.0):
            out = self._kwargs("claude-opus-5-5", events)["_out"]
        self.assertEqual(out, ["답변"], "간격 안의 추론 이벤트는 하트비트로 내지 않는다")

    def test_stream_answer_passes_provider_heartbeat_without_counting_it(self):
        def fake(messages, system, config, model=None):
            yield ""
            yield ""
            yield "본문"
        outcome = pl.AnswerOutcome()
        real = pl._answer_providers
        pl._answer_providers = lambda cfg: [("Claude", fake)]
        try:
            out = list(pl._stream_answer([], "", NS(gemini_api_key=None), outcome))
        finally:
            pl._answer_providers = real
        self.assertEqual(out, [("Claude", ""), ("Claude", ""), ("Claude", "본문")])
        self.assertEqual(outcome.provider, "Claude")
        self.assertEqual(outcome.attempts, ["Claude"])

    def test_heartbeat_only_stream_is_still_an_empty_response(self):
        """하트비트만 내고 끝나면 빈 응답 = 실패(다음 제공자로) — 하트비트가 성공으로 세지면 안 된다."""
        def beats(messages, system, config, model=None):
            yield ""

        def ok(messages, system, config, model=None):
            yield "대체 답변"
        outcome = pl.AnswerOutcome()
        real = pl._answer_providers
        pl._answer_providers = lambda cfg: [("Claude", beats), ("OpenAI", ok)]
        try:
            list(pl._stream_answer([], "", NS(gemini_api_key=None), outcome))
        finally:
            pl._answer_providers = real
        self.assertEqual(outcome.provider, "OpenAI")
        self.assertEqual(outcome.empty_providers, ["Claude"])

    def test_effort_omitted_for_unsupported_models(self):
        for m in ("claude-haiku-4-5", "claude-haiku-4-5-20251001", "claude-sonnet-4-5",
                  "claude-sonnet-4-5-20250929", "claude-3-7-sonnet-latest", "unknown-model"):
            self.assertNotIn("output_config", self._kwargs(m), m)

    def test_supports_effort_versions(self):
        for m in ("claude-sonnet-4-6", "claude-opus-4-6", "claude-opus-4-8", "claude-sonnet-5",
                  "claude-opus-5-5", "claude-fable-5-1"):
            self.assertTrue(pl._supports_effort(m), m)


class ModelTestCallSizeTest(unittest.TestCase):
    def test_test_call_uses_production_sized_prompt(self):
        """짧은 프롬프트로는 opus가 통과했다 — 실제 답변 크기로 첫 응답 시간을 재야 한다."""
        from api.model_settings import TEST_CONTEXT_CHARS, test_messages
        from app.templates.prompts import INJECTION_RESISTANCE, WAGE_CALC_RULES
        system, user = test_messages()
        self.assertIn(INJECTION_RESISTANCE.strip()[:30], system)
        self.assertIn(WAGE_CALC_RULES.strip()[:10], system)
        self.assertGreaterEqual(len(user), TEST_CONTEXT_CHARS)


if __name__ == "__main__":
    unittest.main(verbosity=1)
