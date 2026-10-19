"""calc-card-consistency 회귀 테스트(오프라인, API 키 불요) — Design §7.

계산 카드의 숫자는 LLM에 "이 수치를 사용하세요"로 들어가 답변 금액이 된다. 한 카드 안의 금액이 서로 다른 입력에서 나오면 세후가
세전보다 큰 모순이 답변으로 옮겨진다(G2). 이 테스트는 그 결함이 돌아오지 않게 고정한다.
- T1 G2 재현(연장시간을 따로 적고 연장수당은 묻지 않은 질문)
- T2 카드 금액 불변식 격자(I1~I3)
- T3 규칙의 효과 범위(연장시간 없는 입력은 그대로)
- T4 대상이 아닌 경로(그 임금이 이미 든 금액·노무제공자·미확인 모드·임금 없음), 관리 모드 보류 승격(T4b), 52시간 경고(T4c)
- T5 구성 미상(D4)과 겹치는 카드
- T6 정기성 안내
- T7 미확인 모드의 조건부 예시(kin-01)
- T8 예시 경계(Design §4.3 조건 1~5)
- T9 1주 15시간 미만·기준선 표현
- T10 바뀌지 않는 것(구성 보류·확정 카드·예시 없는 미확인 카드)
- T11 질문의 시간 표현 해석(_HourMention)
- T12 답변 규칙(WAGE_CALC_RULES)
"""
from __future__ import annotations

import difflib
import itertools
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def card(params: dict, query: str) -> str:
    """파이프라인 계산 카드(의도분석 결과 형태의 params를 직접 넣는다 — LLM 호출 없음)."""
    from app.core.pipeline import _run_calculator
    base = {"needs_calculation": True, "reference_year": 2026}   # 오늘 날짜에 묶이지 않게
    base.update(params)
    return _run_calculator(base, query) or ""


def card_without_rule(params: dict, query: str) -> str:
    """G2 규칙을 끈 카드 — 파이프라인이 연장수당을 더하지 않던 때와 비교한다(Design §7 T3)."""
    from app.core import pipeline
    with mock.patch.object(pipeline, "adds_premium_pay", lambda inp: False):
        return card(params, query)


def money(text: str, pattern: str) -> float | None:
    m = re.search(pattern, text)
    return float(m.group(1).replace(",", "")) if m else None


MONTHLY_TOTAL_RE = r"월 총 예상 수령액\(세전\):\s*([\d,]+)원"
NET_RE = r"월 실수령액\(세후\):\s*([\d,]+)원"
GROSS_RE = r"(?m)^\s*세전 월 급여:\s*([\d,]+)원\s*$"     # 단일 값만(D4의 'A 또는 B'는 뺀다)
OT_LINE = "연장/야간/휴일수당(월)"
HOURLY = {"wage_type": "시급", "wage_amount": 12000, "weekly_work_days": 5, "daily_work_hours": 8, "business_size": "5인이상"}
TWO_YEARS = {"start_date": "2024-01-01", "end_date": "2026-01-01"}

# 격자(Design §2.2·§5) — 고정수당 축은 넣지 않는다(D8: 기준 월액이 계산기마다 달라 갈리는 별도 결함, 후속 사이클의 완료 조건)
GRID_WAGES = (("시급", 12000), ("일급", 100000), ("월급", 2500000), ("연봉", 30000000))
GRID_PREMIUMS = ({}, {"weekly_overtime_hours": 10}, {"weekly_night_hours": 8}, {"weekly_holiday_work_hours": 8},
                 {"weekly_overtime_hours": 10, "weekly_night_hours": 4})
GRID_ASKS = (
    (["4대보험"], {}), (["퇴직금"], TWO_YEARS), (["평균임금"], {}), (["실업급여"], dict(TWO_YEARS, age=35)),
    (["산재보상금"], {}), (["근로장려금"], {}), (["퇴직연금"], TWO_YEARS), (["휴업수당"], {"shutdown_days": 10}),
    (["4대보험", "퇴직금"], TWO_YEARS), (["최저임금"], {}), (["주휴수당"], {}), (["연차수당"], {"start_date": "2024-01-01"}),
)
GRID_SIZES = ("5인이상", "5인미만", None)
GRID_STATEMENTS = ("", " 연장수당은 따로 받습니다.", " 이번 주에만 그렇게 일했습니다.")
AVERAGE_WAGE_TARGETS = ("severance", "average_wage", "unemployment", "industrial_accident", "retirement_pension",
                        "shutdown_allowance")
# 휴업수당은 월급이 없으면 '시급 × 1일 시간 × 근무일수 × 52/12'(주휴분 없음)로 월 금액을 추정해 월 총액과 갈린다 — 이 사이클 전부터
# 있던 결함이라 기준 월액 단일화(후속, Design §11-1)에서 고친다. 고치면 test_t2_known_gap가 '예상 밖 통과'로 알린다(독립 리뷰 M3)
KNOWN_BASIS_GAPS = frozenset({"shutdown_allowance"})


def grid():
    """(params, query, 연장시간 유무) — 2,160카드."""
    for (wage_type, amount), premium, (labels, extra), size, statement in itertools.product(
            GRID_WAGES, GRID_PREMIUMS, GRID_ASKS, GRID_SIZES, GRID_STATEMENTS):
        params = {"wage_type": wage_type, "wage_amount": amount, "weekly_work_days": 5, "daily_work_hours": 8,
                  "calculation_types_kr": labels, **premium, **extra}
        if size:
            params["business_size"] = size
        yield params, f"{wage_type} {amount:,}원, 하루 8시간 주 5일 근무합니다.{statement} 계산해 주세요.", bool(premium)


class CapturedCalculation:
    """facade 호출을 감싸 첫 계산(본 카드)의 입력·대상·결과를 잡는다 — D4 대안 계산이 다시 부르는 호출은 뒤에 쌓인다."""

    def __enter__(self):
        from wage_calculator.facade import WageCalculator
        self.calls = []
        original = WageCalculator.calculate

        def wrapped(calc, inp, targets=None, **kw):
            result = original(calc, inp, targets, **kw)
            self.calls.append((inp, list(targets or []), result))
            return result
        self._patch = mock.patch.object(WageCalculator, "calculate", wrapped)
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()

    @property
    def first(self):
        return self.calls[0] if self.calls else None


class MonthlyBasisCapture:
    """평균임금 계열 계산기가 실제로 쓴 월 금액(monthly_pay_estimate 결과)을 모듈별로 잡는다. 같은 식으로 다시 계산해 비교하면
    계산기가 다른 기준 월액을 넘기는 결함을 못 본다 — 첫 판의 I3가 휴업수당에서 그렇게 공허하게 통과했다(독립 리뷰 M3)."""

    def __enter__(self):
        import importlib
        from wage_calculator.calculators import shared
        self.values = []
        self._patches = []
        for name in AVERAGE_WAGE_TARGETS:
            module = importlib.import_module(f"wage_calculator.calculators.{name}")

            def wrapped(inp, hourly, base, _name=name):
                value = shared.monthly_pay_estimate(inp, hourly, base)
                self.values.append((_name, value))
                return value
            patch = mock.patch.object(module, "monthly_pay_estimate", wrapped)
            patch.start()
            self._patches.append(patch)
        return self

    def __exit__(self, *exc):
        for patch in self._patches:
            patch.stop()


class G2ReproTest(unittest.TestCase):
    """T1 — 시급 12,000원·8h×5·매주 연장 10시간. 월 총 예상 수령액이 세전 월 급여·평균임금과 같은 월 금액을 쓴다(Design §6)."""

    def test_t1_a_insurance_only(self):
        out = card(dict(HOURLY, weekly_overtime_hours=10, calculation_types_kr=["4대보험"]),
                   "시급 12,000원으로 하루 8시간 주 5일 일하고, 매주 연장근로를 10시간 합니다. 4대보험 공제 후 실수령액이 얼마인가요?")
        self.assertIn(f"{OT_LINE}: 782,143원", out)
        self.assertEqual(money(out, MONTHLY_TOTAL_RE), 3285000)          # main: 2,502,857원
        self.assertEqual(money(out, GROSS_RE), 3285000)                  # F6 그대로
        self.assertEqual(money(out, NET_RE), 2885875)                    # 세후 그대로 — 이제 세전보다 작다

    def test_t1_b_severance_only(self):
        out = card(dict(HOURLY, weekly_overtime_hours=10, calculation_types_kr=["퇴직금"], **TWO_YEARS),
                   "시급 12,000원, 하루 8시간 주 5일, 매주 연장 10시간을 2년 했습니다. 퇴직금은 얼마인가요?")
        self.assertIn("퇴직금: 6,435,978원", out)                        # F6 그대로
        self.assertIn("적용 평균임금: 107,120원/일", out)
        self.assertIn(f"{OT_LINE}: 782,143원", out)
        self.assertEqual(money(out, MONTHLY_TOTAL_RE), 3285000)

    def test_t1_c_overtime_asked_is_the_control(self):
        out = card(dict(HOURLY, weekly_overtime_hours=10, calculation_types_kr=["4대보험", "연장수당"]),
                   "시급 12,000원으로 하루 8시간 주 5일 일하고 매주 연장 10시간입니다. 연장수당과 실수령액은?")
        self.assertEqual(money(out, MONTHLY_TOTAL_RE), 3285000)
        self.assertEqual(money(out, GROSS_RE), 3285000)

    def test_t1_d_unemployment_only(self):
        out = card(dict(HOURLY, weekly_overtime_hours=10, calculation_types_kr=["실업급여"], age=35, **TWO_YEARS),
                   "시급 12,000원, 하루 8시간 주 5일, 매주 연장 10시간을 2년 하다 권고사직했습니다. 실업급여는?")
        self.assertIn("구직급여 일액: 66,048원/일", out)
        self.assertIn("총 구직급여: 9,907,200원", out)                   # F6 그대로
        self.assertEqual(money(out, MONTHLY_TOTAL_RE), 3285000)

    def test_t1_e_monthly_wage_with_premium_paid_separately(self):
        out = card(dict(HOURLY, wage_type="월급", wage_amount=2500000, weekly_overtime_hours=10, calculation_types_kr=["4대보험"]),
                   "월급 250만 원(기본급), 하루 8시간 주 5일, 매주 연장 10시간 하고 연장수당은 따로 받습니다. 실수령액은?")
        self.assertIn(f"{OT_LINE}: 781,250원", out)
        self.assertEqual(money(out, MONTHLY_TOTAL_RE), 3281250)          # main: 2,500,000원
        self.assertEqual(money(out, GROSS_RE), 3281250)
        self.assertEqual(money(out, NET_RE), 2882971)

    def test_t1_one_predicate_for_the_estimate_and_the_rule(self):
        """D3 — 파이프라인 규칙과 월 임금총액 추정이 같은 함수로 판정해야 둘이 다시 갈리지 않는다."""
        from app.core import pipeline
        from wage_calculator.calculators import shared
        self.assertIs(pipeline.adds_premium_pay, shared.adds_premium_pay)
        self.assertIs(pipeline._has_premium_hours, shared.has_premium_hours)


class InvariantGridTest(unittest.TestCase):
    """T2 — 카드 금액 불변식(Design §5). I1 월 총 = 세전 월 급여, I2 세후 ≤ 세전, I3 평균임금 계열이 실제로 쓴 월 금액 = 월 총."""

    @classmethod
    def setUpClass(cls):
        cls.checked = {"I1": 0, "I2": 0, "I3": 0}
        cls.violations, cls.gaps = [], []
        cls.cards = 0
        with CapturedCalculation() as cap, MonthlyBasisCapture() as basis:
            for params, query, _ in grid():
                cap.calls.clear()
                basis.values.clear()
                out = card(params, query)
                if not cap.first:
                    continue
                cls.cards += 1
                asked = params["calculation_types_kr"]
                total, net, gross = money(out, MONTHLY_TOTAL_RE), money(out, NET_RE), money(out, GROSS_RE)
                if total and gross:
                    cls.checked["I1"] += 1
                    if abs(total - gross) > 1:
                        cls.violations.append(("I1", query, asked, total, gross))
                if net and (total or gross):
                    cls.checked["I2"] += 1
                    for value in (total, gross):
                        if value and net > value + 1:
                            cls.violations.append(("I2", query, asked, net, value))
                if not total:
                    continue
                used = [(name, value) for name, value in basis.values if value]
                if any(name not in KNOWN_BASIS_GAPS for name, _ in used):
                    cls.checked["I3"] += 1
                for name, value in used:
                    if abs(value - total) > 1:
                        (cls.gaps if name in KNOWN_BASIS_GAPS else cls.violations).append(
                            ("I3", name, query, asked, round(value), total))

    def test_t2_invariants_hold_across_the_grid(self):
        self.assertEqual(self.cards, 2160)
        for name, count in self.checked.items():
            self.assertGreater(count, 0, f"{name}를 검사한 카드가 없다 — 공허한 통과")
        self.assertEqual(self.violations[:5], [])

    @unittest.expectedFailure
    def test_t2_known_gap_shutdown_allowance_basis(self):
        """휴업수당의 시급제 월 금액(주휴분 없음)은 아직 월 총액과 갈린다 — 후속에서 고치면 이 테스트가 통과해 실패로 알린다."""
        self.assertEqual(self.gaps[:3], [])


class RuleScopeTest(unittest.TestCase):
    """T3 — 규칙의 효과 범위. 규칙을 끈 카드와 비교한다: 바뀌는 카드는 연장시간이 있는 입력뿐이고, '월 총' 줄만 값이 바뀌며(나머지
    줄은 그대로 남는다) 연장수당 줄·계산식·근거·경고가 더해질 뿐이다."""

    def test_t3_only_additions_and_the_monthly_total(self):
        changed = unchanged = 0
        with CapturedCalculation() as cap:
            for params, query, has_premium in grid():
                cap.calls.clear()
                on = card(params, query)
                on_result = cap.first[2] if cap.first else None
                cap.calls.clear()
                off = card_without_rule(params, query)
                off_result = cap.first[2] if cap.first else None
                if on == off:
                    unchanged += 1
                    self.assertNotIn(OT_LINE, on, query)
                    continue
                self.assertTrue(has_premium, query)
                changed += 1
                removed = [ln[2:] for ln in difflib.ndiff(off.splitlines(), on.splitlines()) if ln.startswith("- ")]
                self.assertTrue(all(ln.startswith("월 총 예상 수령액(세전):") for ln in removed), (query, removed))
                self.assertIn(OT_LINE, on)
                added = set(on_result.summary) - set(off_result.summary)
                self.assertLessEqual(added, {OT_LINE}, query)
                for key, value in off_result.summary.items():
                    self.assertEqual(on_result.summary.get(key), value, (query, key))
                remaining = iter(on_result.warnings)
                self.assertTrue(all(w in remaining for w in off_result.warnings), query)   # 순서를 지킨 부분열 — 추가만
        # 연장시간이 있어도 더할 금액이 0이면(상시 4명 이하의 야간근로 — 가산 없음) 바뀌지 않는다(리뷰 L1): 임금 4 × 질문 12 × 진술 3 = 144
        self.assertEqual(changed, 1728 - 144)
        self.assertEqual(unchanged, 432 + 144)


class NotTargetedPathTest(unittest.TestCase):
    """T4 — 그 임금이 이미 든 금액·노무제공자·미확인 모드·임금 없음에는 묻지 않은 연장수당을 더하지 않는다(Design §3.3)."""

    BASE = {"weekly_work_days": 5, "daily_work_hours": 8, "weekly_overtime_hours": 10}
    CASES = {
        "정확 경로(기본급 + 총액)": (
            {"wage_type": "월급", "wage_amount": 3000000, "business_size": "5인이상", "calculation_types_kr": ["4대보험"]},
            "월급 3,000,000원(기본급 2,500,000원, 고정연장수당 500,000원)이고 주 5일 하루 8시간, 매주 연장 10시간 일해요. "
            "직원 10명. 4대보험은?"),
        "월급 포함 보류": (
            {"wage_type": "월급", "wage_amount": 3000000, "business_size": "5인이상", "calculation_types_kr": ["4대보험"]},
            "월급 300만원에 연장수당이 포함돼 있어요. 주 5일 하루 8시간에 매주 연장 10시간 일해요. 직원 10명. 4대보험은?"),
        "연봉 포함 보류": (
            {"wage_type": "연봉", "wage_amount": 36000000, "business_size": "5인이상", "calculation_types_kr": ["퇴직금"],
             "start_date": "2023-01-02", "end_date": "2026-01-01"},
            "연봉 3,600만원이고 연장수당이 연봉에 포함돼 있어요. 주 5일 하루 8시간에 매주 연장 10시간 일합니다. 퇴직금은?"),
        "일급 포함 보류": (
            {"wage_type": "일급", "wage_amount": 120000, "business_size": "5인이상", "calculation_types_kr": ["4대보험"]},
            "일당 12만원에 연장근무 수당까지 다 포함이라고 들었어요. 하루 8시간 주 5일, 매주 연장 10시간 일해요. 4대보험은?"),
        "포괄임금제 라벨": (
            {"wage_type": "포괄임금제", "wage_amount": 2700000, "business_size": "5인이상", "calculation_types_kr": ["4대보험"]},
            "월 270만원 받고 주 5일 하루 8시간에 매주 연장 10시간 일해요. 직원 10명. 4대보험은?"),
        "포괄임금제 진술(역산)": (
            {"wage_type": "포괄임금제", "wage_amount": 2700000, "business_size": "5인이상",
             "calculation_types_kr": ["4대보험", "퇴직금"], "start_date": "2023-01-02", "end_date": "2026-01-01"},
            "포괄임금제로 월 270만원, 주 5일 하루 8시간에 매주 연장 10시간 일해요. 직원 10명. 4대보험과 퇴직금은?"),
        "노무제공자": (
            {"wage_type": "월급", "wage_amount": 3000000, "is_platform_worker": True, "calculation_types_kr": ["4대보험"]},
            "배달 라이더(특고)로 월 300만원 벌어요. 하루 8시간 주 5일에 매주 10시간 더 일해요. 4대보험은?"),
        "미확인 모드": (
            {"wage_type": "시급", "wage_amount": 12000, "business_size": "5인이상", "calculation_types_kr": ["최저임금", "4대보험"],
             "daily_work_hours": None},
            "시급 12,000원으로 주 5일 일하고 매주 연장 10시간을 합니다. 직원 10명. 최저임금 넘나요? 4대보험은?"),
        "임금 없음": ({"calculation_types_kr": ["주휴수당"]}, "하루 8시간 주 5일 일하고 매주 연장 10시간 합니다. 주휴수당 몇 시간인가요?"),
        # 주휴 블록만 내고 끝나지 않고 계산까지 가는 임금 없음 경로 — has_wage 조건을 시험한다(독립 리뷰 L2)
        "임금 없음(계산까지 가는 대상)": ({"calculation_types_kr": ["주52시간"]},
                                    "하루 8시간 주 5일에 매주 연장 10시간 합니다. 주 52시간 넘나요?"),
    }

    def test_t4_no_unasked_overtime(self):
        from app.core.pipeline import _PREMIUM_ADDED_NOTE
        for name, (extra, query) in self.CASES.items():
            with self.subTest(name):
                params = dict(self.BASE, **extra)
                if params.get("daily_work_hours") is None:
                    params.pop("daily_work_hours")
                on = card(params, query)
                self.assertTrue(on)
                self.assertNotIn(OT_LINE, on)
                self.assertNotIn(_PREMIUM_ADDED_NOTE, on)
                self.assertEqual(on, card_without_rule(params, query))      # 보류 목록·안내까지 그대로

    def test_t4_unknown_mode_still_runs_the_hourly_verdict(self):
        """미확인 모드 사례가 계산까지 가는지 — 보류만 내고 끝나면 `not unknown_mode` 조건을 시험하지 못한다."""
        extra, query = self.CASES["미확인 모드"]
        params = dict(self.BASE, **extra)
        params.pop("daily_work_hours")
        out = card(params, query)
        self.assertIn("[소정근로시간 미확인", out)
        self.assertIn("최저임금 충족: ✅ 충족", out)


class _EmptyRuleStore:
    """승인 기록 0건 저장소 — 관리 모드에서 4대보험 기준이 모두 없다."""

    def load(self):
        return 1, {"records": []}


class ManagedModeTest(unittest.TestCase):
    """T4b — 관리 모드(LEGAL_RULES_ENABLED=true)에서 물은 계산이 전부 보류면 요청 보류다. 파이프라인이 더한 연장수당(G2·파생 연장)이
    성공해도 그 신호를 지우지 않는다(facade auxiliary — 독립 리뷰 M2: 예전에는 세전 총액과 '이 수치를 사용하세요'가 나갔다)."""

    BASE = dict(HOURLY, reference_date="2026-10-18")      # 기준일을 날짜로 — 연도만이면 해가 바뀐 뒤 요청 전체가 보류된다

    def test_t4b_all_asked_sections_held(self):
        from app.core import legal_rule_store
        from app.core.pipeline import _calculation_context_heading
        cases = {"G2": dict(self.BASE, weekly_overtime_hours=10, calculation_types_kr=["4대보험"]),
                 "파생 연장": dict(self.BASE, daily_work_hours=10, calculation_types_kr=["4대보험"])}
        with mock.patch.object(legal_rule_store, "rules_enabled", lambda: True), \
                mock.patch.object(legal_rule_store, "configured_store", lambda: _EmptyRuleStore()):
            for name, params in cases.items():
                with self.subTest(name):
                    out = card(params, "시급 12,000원이고 연장근로가 있습니다. 직원 10명. 4대보험 떼면 얼마예요?")
                    self.assertRegex(out, r"(?m)^계산 보류 \(")
                    self.assertNotIn(OT_LINE, out)
                    self.assertTrue(_calculation_context_heading(out).startswith("계산 보류 안내 — 금액 추정 금지"))
            control = card(dict(self.BASE, weekly_overtime_hours=10, calculation_types_kr=["주휴수당"]),
                           "시급 12,000원, 하루 8시간 주 5일에 매주 연장 10시간. 직원 10명. 주휴수당은?")
            self.assertNotRegex(control, r"(?m)^계산 보류 \(")
            self.assertIn(OT_LINE, control)         # 물은 계산이 계산되면 규칙은 관리 모드에서도 그대로다


class WeeklyLimitWarningTest(unittest.TestCase):
    """T4c — 연장수당 섹션의 주 52시간 경고. 규칙으로 그 섹션이 묻지 않은 카드에도 실리므로 법률 사실과 맞아야 한다 — 상시 4명
    이하는 연장 근로의 제한(제53조)이 적용되지 않고(근로기준법 제11조, 주 52시간 체크와 같은 판정) 한도는 5명 이상 전체다(리뷰 M4)."""

    def test_t4c_small_workplace_and_label(self):
        small = card(dict(HOURLY, business_size="5인미만", weekly_overtime_hours=15, calculation_types_kr=["4대보험"]),
                     "시급 12,000원, 하루 8시간 주 5일에 매주 연장 15시간. 직원 3명. 4대보험은?")
        self.assertIn(OT_LINE, small)
        self.assertNotIn("법정 한도 52h 초과", small)
        large = card(dict(HOURLY, weekly_overtime_hours=20, calculation_types_kr=["연장수당"]),
                     "시급 12,000원, 하루 8시간 주 5일에 매주 연장 20시간. 직원 10명. 연장수당은?")
        self.assertIn("주 총 근로시간 60.0h — 법정 한도 52h 초과 (상시 5명 이상 사업장, 근로기준법 제53조)", large)
        self.assertNotIn("30인 이상", large)


class CompositionUnknownOverlapTest(unittest.TestCase):
    """T5 — 월급 + 연장 + 구성 미상(D4)에 4대보험만 물으면 D4 안내가 가리키는 '위 연장수당'이 이제 카드에 있다(Design §3.5)."""

    def test_t5_overtime_line_without_monthly_total(self):
        out = card({"wage_type": "월급", "wage_amount": 2500000, "business_size": "5인이상", "calculation_types_kr": ["4대보험"],
                    "weekly_work_days": 5, "daily_work_hours": 8, "weekly_overtime_hours": 10},
                   "월급 250만원, 주 5일 하루 8시간에 매주 연장 10시간 일해요. 직원 10명. 4대보험 떼면 얼마예요?")
        self.assertIn(f"{OT_LINE}: 781,250원", out)                        # A(연장 별도) 한 값 — _D4_SINGLE_READING_KEYS
        self.assertNotIn("또는", next(ln for ln in out.splitlines() if OT_LINE in ln))
        self.assertIsNone(money(out, MONTHLY_TOTAL_RE))                    # 안내문은 '월 총 예상 수령액은 … 싣지 않았습니다'
        self.assertIn("위 연장수당 등을 그 기준으로 계산했습니다", out)
        self.assertIn("세전 월 급여: 3,281,250원(연장수당 별도) 또는 2,500,000원(월급에 포함)", out)
        self.assertNotIn("월 실수령액(세후):", out)


class PremiumAddedNoteTest(unittest.TestCase):
    """T6 — 정기성 안내는 규칙이 연장수당을 더한 카드에만 한 번(D5)."""

    def test_t6_note_only_where_the_rule_added_overtime(self):
        from app.core.pipeline import _PREMIUM_ADDED_NOTE
        added = card(dict(HOURLY, weekly_overtime_hours=10, calculation_types_kr=["4대보험"]),
                     "시급 12,000원, 하루 8시간 주 5일에 매주 연장 10시간. 4대보험은?")
        self.assertEqual(added.count(_PREMIUM_ADDED_NOTE), 1)
        asked = card(dict(HOURLY, weekly_overtime_hours=10, calculation_types_kr=["4대보험", "연장수당"]),
                     "시급 12,000원, 하루 8시간 주 5일에 매주 연장 10시간. 연장수당과 4대보험은?")
        no_premium = card(dict(HOURLY, calculation_types_kr=["4대보험"]), "시급 12,000원, 하루 8시간 주 5일. 4대보험은?")
        derived = card(dict(HOURLY, daily_work_hours=10, calculation_types_kr=["4대보험"]),
                       "시급 12,000원, 하루 10시간 주 5일 근무 계약입니다. 4대보험은?")
        unknown = card({"wage_type": "시급", "wage_amount": 12000, "weekly_work_days": 5, "weekly_overtime_hours": 10,
                        "calculation_types_kr": ["최저임금", "4대보험"]}, "시급 12,000원, 주 5일에 매주 연장 10시간. 최저임금은?")
        # 상시 4명 이하의 야간근로는 가산이 없어 더할 금액이 0이다 — 0원 섹션과 '월 금액에 들어간다'는 안내를 붙이지 않는다(리뷰 L1)
        small_night = card(dict(HOURLY, business_size="5인미만", weekly_night_hours=8, calculation_types_kr=["4대보험"]),
                           "시급 12,000원, 하루 8시간 주 5일에 야간 8시간. 직원 3명. 4대보험은?")
        self.assertNotIn(OT_LINE, small_night)
        for name, out in {"asked": asked, "no_premium": no_premium, "derived": derived, "unknown": unknown,
                          "small_night": small_night}.items():
            with self.subTest(name):
                self.assertTrue(out)
                self.assertNotIn(_PREMIUM_ADDED_NOTE, out)
        self.assertIn(OT_LINE, derived)              # 파생 연장(1일 10시간)은 앞의 규칙이 이미 더했다 — 정기성은 계약상 매일이다


def kin01_question() -> str:
    return next(c for c in json.loads((ROOT / "data" / "eval_kin_queries.json").read_text(encoding="utf-8"))
                if c["id"] == "kin-01")["question"]


def holiday_card(query: str, **params) -> str:
    """주휴수당만 물은 카드 — 의도분석이 근무일수만 뽑은 회차(K1-a)처럼 시간은 넣지 않는다."""
    return card(dict({"calculation_types_kr": ["주휴수당"]}, **params), query)


EXAMPLE_HOLD = ("금액 보류: 질문에 1일·1주 소정근로시간이 없어 다음은 확정하지 않았습니다 — 주휴시간·주휴수당. 질문의 근무시간을 "
                "소정근로시간으로 단정하지 마세요 — 위 조건부 예시만 그 조건과 함께 쓰고, 다른 시간을 가정해 추정하지 마세요.")
PLAIN_HOLD = ("금액 보류: 질문에 1일·1주 소정근로시간이 없어 다음은 계산하지 않았습니다 — 주휴시간·주휴수당. "
              "가정한 시간이나 실제로 일한 시간으로 추정하지 마세요.")
HOLD_HEADING = "임금계산기 결과 — 이 수치를 사용하세요. 금액을 보류한 항목은 추정하지 마세요"
CONDITION_SENTENCE = ". '조건부 예시'는 그 조건을 함께 밝혀서만 쓰세요"


class ConditionalExampleTest(unittest.TestCase):
    """T7 — 의도분석이 근무일수만 뽑은 회차에도 카드가 질문의 시간으로 조건부 예시를 계산한다(D1). 예전에는 '추정하지 마세요'가
    조건을 밝힌 산식까지 막아 답변에서 3.6시간이 빠졌다(calc-card-followups 최종 실측 kin-01)."""

    def test_t7_kin01_block(self):
        from app.core.pipeline import _calculation_context_heading
        out = holiday_card(kin01_question(), weekly_work_days=3)
        lines = out.splitlines()
        self.assertEqual(lines[0], "[소정근로시간 미확인 — 근로시간에 따라 달라지는 시간·금액은 계산하지 않음]")
        self.assertIn("조건부 예시 — 근로계약상 1주 소정근로시간이 질문의 근무(주 3일 × 6시간 = 18시간)와 같다면: "
                      "주 소정근로일 3일 < 5일 → 주휴: min(18h ÷ 5, 8h) = 3.6h (= 18h ÷ 40h × 8h — 1주 소정근로일을 5일로 봄)", lines)
        self.assertEqual(lines[-1], EXAMPLE_HOLD)
        self.assertLess(next(i for i, ln in enumerate(lines) if ln.startswith("주휴시간 = ")),
                        next(i for i, ln in enumerate(lines) if ln.startswith("조건부 예시 —")))
        self.assertNotIn("[주휴시간 산정", out)                 # 확정 카드가 아니다 — 실근로를 소정근로로 단정하지 않는다
        self.assertEqual(_calculation_context_heading(out), HOLD_HEADING + CONDITION_SENTENCE)

    def test_t7_hourly_wage_adds_the_amount(self):
        out = holiday_card(kin01_question(), weekly_work_days=3, wage_type="시급", wage_amount=10320)
        self.assertIn("1주 소정근로일을 5일로 봄) → 주휴수당 = 시급 10,320원 × 3.6h = 37,152원", out)
        self.assertIn(EXAMPLE_HOLD, out)
        self.assertIn("최저임금 충족: ✅ 충족", out)            # 시급제 판정은 그대로 남는다


class ExampleBoundaryTest(unittest.TestCase):
    """T8 — 조건이 하나라도 어긋나면 예시 없이 지금 카드(Design §4.3). 틀린 예시보다 예시 없음이 안전하다."""

    NONE = {
        "1일 8시간 초과(10h×2일)": ("이번 주 이틀 동안 하루 10시간씩 일했어요. 주휴수당은?", 2),
        "1일 8시간 초과(9h×2일)": ("이번 주 이틀 동안 하루 9시간씩 일했어요. 주휴수당은?", 2),
        "1주 40시간 초과(7h×6일)": ("주 6일 하루 7시간씩 일했어요. 주휴수당은?", 6),
        "범위": ("하루 6~7시간씩 3일 일했어요. 주휴수당은?", 3),
        "범위 + 합계": ("지난주 하루 6~7시간씩 3일, 총 20시간 일했어요. 주휴수당은?", 3),
        "1일 × 일수 ≠ 합계": ("지난주 월·화·수 하루 6시간, 총 20시간 일했어요. 주휴수당은?", 3),
        "기간 일수 ≠ 근무일수(a50-40)": ("주 6일, 시급 없이 일합니다. 9월 28일~30일 3일 동안 25시간 일했는데 주휴수당은?", 6),
        "근무일수 없음": ("지난주 하루 6시간씩 일했어요. 주휴수당은?", None),
        "시간 없음": ("지난주 사흘 일했는데 주휴수당은?", 3),
        "값이 둘(1일 6시간·연장 2시간)": ("지난주 3일 일했고 하루 6시간씩, 연장 2시간도 했어요.", 3),
        # 독립 리뷰 H1 — 표지 없는 값은 1일 시간인지 합계인지 모른다(예전에는 합계로 나눠 대개 '미발생'이 나왔다)
        "표지 없는 값(월수금 6시간)": ("지난주 월수금 6시간 일했는데 주휴수당 받을 수 있나요?", 3),
        "표지 없는 값(각 6시간)": ("월수금 각 6시간 일해요. 주휴수당은?", 3),
        "시각 범위 뒤의 시간": ("주 3일 10시~16시(6시간) 일해요. 주휴수당은?", 3),
        "맞교대 시간": ("12시간 맞교대로 주 3일 일해요. 주휴수당은?", 3),
        "연장근무 시간": ("주 5일 출근하는데 매일 2시간씩 연장근무해요. 주휴수당은?", 5),
        "야간 근무 시간": ("야간 8시간 근무를 주 3일 해요. 주휴수당은?", 3),
        "휴일 근무 시간": ("휴일근무 8시간을 주 3일 해요. 주휴수당은?", 3),
        "주휴 시간 언급(3시간분)": ("주 3일 일하는데 주휴수당을 3시간분만 준대요. 맞나요?", 3),
        "1주가 아닌 기간의 합계": ("지난 2주 동안 총 24시간 일했어요. 주 3일이에요. 주휴수당은?", 3),
        "한 달 합계": ("한 달에 60시간 일하고 주 3일 나가요. 주휴수당은?", 3),
        "한 달 합계 + 1일 값(서로 안 맞음)": ("한 달에 총 30시간 일했고, 하루 6시간씩 주 3일 나가요. 주휴수당은?", 3),
        "기준선 + 조사('15시간을 넘어야')": ("주 15시간을 넘어야 받는다던데 주 3일 일해요. 주휴수당은?", 3),
        "기간 일수가 다른 절": ("주 6일 근무인데, 이번 주는 3일 동안 일했고 하루 6시간씩 했어요. 주휴수당은?", 6),
        # 월을 넘는 범위는 일수를 정할 수 없다 — 그대로 두면 4일 실근로 합계가 '주 6일 × 5시간' 예시가 됐다(CodeRabbit #118)
        "월을 넘는 범위('28일부터 10월 1일')": ("주 6일 일해요. 9월 28일부터 10월 1일까지 총 30시간 일했는데 주휴수당은?", 6),
        "월을 넘는 범위('9/28~10/1')": ("주 6일 일해요. 9/28~10/1 총 30시간 일했는데 주휴수당은?", 6),
        # 끝 날짜 숫자가 더 크면 _span_days가 3일로 센다 — 33일 합계가 '주 3일 × 6시간' 예시가 됐다(CodeRabbit #118 재검토)
        "월을 넘는 범위(끝 날짜가 더 큼, '9/28~10/30')": ("주 3일 일해요. 9/28~10/30 총 18시간 일했는데 주휴수당은?", 3),
        "월을 넘는 범위(끝 날짜가 더 큼, '28일부터 10월 30일')": (
            "주 3일 일해요. 9월 28일부터 10월 30일까지 하루 6시간씩 일했어요. 주휴수당은?", 3),
        "날짜의 '1일'(21일 3시간)": ("지난 21일 3시간 일했어요. 주휴수당은?", 5),
        "다른 표지 없는 값(주휴 3시간분)": ("하루 6시간씩 주 3일 일하는데 주휴수당을 3시간분만 준대요. 맞나요?", 3),
    }
    SOME = {
        "8h×5일(40시간 경계)": ("지난주 5일 동안 하루 8시간씩 일했어요. 주휴수당은?", 5,
                             "(주 5일 × 8시간 = 40시간)와 같다면: 주 소정근로일 5일 ≥ 5일 → 주휴: min(8h, 8h) = 8h"),
        "5h×3일(15시간 경계)": ("지난주 화·목·토 하루 5시간씩(총 15시간) 일했어요. 주휴수당은?", 3,
                             "(주 3일 × 5시간 = 15시간)와 같다면: 주 소정근로일 3일 < 5일 → 주휴: min(15h ÷ 5, 8h) = 3h"),
        "휴게시간은 근무시간이 아니다": ("하루 6시간씩 3일 일했고 휴게시간 1시간이 있었어요. 주휴수당은?", 3, "= 3.6h"),
        "합계만": ("지난주 3일 동안 총 18시간 일했어요. 주휴수당은?", 3, "(주 3일 × 6시간 = 18시간)"),
        "분 단위": ("지난주 3일 동안 하루 6시간 30분씩 일했어요. 주휴수당은?", 3, "(주 3일 × 6.5시간 = 19.5시간)"),
        "'일 N시간'": ("주 3일, 일 6시간 근무해요. 주휴수당은?", 3, "(주 3일 × 6시간 = 18시간)"),
        "'주 N시간씩'(긴 기간 안의 1주 합계)": ("1년 6개월 동안 주 15시간씩 일하고 있어요. 주 3일이에요. 주휴수당은?", 3,
                                        "(주 3일 × 5시간 = 15시간)"),
        "같은 값을 되풀이한 표지 없는 값": ("하루 6시간씩 3일 일했어요. 6시간 일하고 퇴근했어요.", 3, "(주 3일 × 6시간 = 18시간)"),
        "'총' 표지만 있는 합계": ("지난주 총 18시간 일했어요. 주 3일이에요. 주휴수당은?", 3, "(주 3일 × 6시간 = 18시간)"),
        "같은 달 범위('9/28~30')": ("9/28~30 하루 6시간씩 일했어요. 주 3일이에요. 주휴수당은?", 3, "(주 3일 × 6시간 = 18시간)"),
    }

    def test_t8_no_example(self):
        for name, (query, days) in self.NONE.items():
            with self.subTest(name):
                out = holiday_card(query, **({"weekly_work_days": days} if days else {}))
                self.assertNotIn("조건부 예시", out)
                if days:
                    self.assertIn(PLAIN_HOLD, out)

    def test_t8_example(self):
        for name, (query, days, expected) in self.SOME.items():
            with self.subTest(name):
                out = holiday_card(query, weekly_work_days=days)
                self.assertIn(expected, out)
                self.assertIn(EXAMPLE_HOLD, out)

    def test_t8_regime_signal_comes_first(self):
        """제도 신호 카드는 제도 확인이 먼저다(조건 1) — 연소자 1일 8시간은 법정 한도(7시간) 밖이라 예시를 만들면 틀린 값이다."""
        query = "고등학생 알바생이에요. 하루 8시간씩 주 5일 일해요. 주휴수당은요?"
        for extra in ({}, {"wage_type": "시급", "wage_amount": 12000}):
            with self.subTest(extra):
                out = holiday_card(query, weekly_work_days=5, daily_work_hours=8, **extra)
                self.assertIn("[근로시간 제도 확인 필요", out)
                self.assertNotIn("조건부 예시", out)

    def test_t8_regime_signal_in_the_unknown_mode(self):
        """1일 시간이 없어 제도 판정(regime)이 생기지 않는 미확인 모드에서도 질문의 제도 신호로 막는다(독립 리뷰 M1 — 연소자
        4.8h·시급 77,400원, 감시·단속이면 주휴 자체가 제외될 수 있다)."""
        for query in ("고등학생 알바생이에요. 지난주 하루 8시간씩 3일 일했어요. 주휴수당은요?",
                      "아파트 경비로 지난주 하루 8시간씩 3일 일했어요. 주휴수당은요?"):
            for extra in ({}, {"wage_type": "시급", "wage_amount": 10320}):
                with self.subTest((query[:10], extra)):
                    out = holiday_card(query, weekly_work_days=3, **extra)
                    self.assertIn("[소정근로시간 미확인", out)
                    self.assertNotIn("조건부 예시", out)

    def test_t8_grounded_out_hours(self):
        """출처 대조가 버린 의도분석 시간(실근로)으로 미확인 모드가 된 카드(독립 리뷰 H1 재현 1). 예전에는 '질문의 6시간은 실제로 일한
        시간'이라는 줄과 '주 3일 × 2시간 → 미발생' 예시가 함께 실렸다. 표지 없는 값이면 예시가 없고, '하루 6시간씩'이면 예시가 있다."""
        params = {"weekly_work_days": 3, "daily_work_hours": 6}
        loose = holiday_card("지난주 월수금 6시간 일했는데 주휴수당 받을 수 있나요?", **params)
        self.assertIn("질문의 6시간은 그 기간에 실제로 일한 시간이라", loose)
        self.assertNotIn("조건부 예시", loose)
        marked = holiday_card("지난주 월수금 하루 6시간씩 일했는데 주휴수당 받을 수 있나요?", **params)
        self.assertIn("질문의 6시간은 그 기간에 실제로 일한 시간이라", marked)
        self.assertIn("(주 3일 × 6시간 = 18시간)와 같다면: 주 소정근로일 3일 < 5일 → 주휴: min(18h ÷ 5, 8h) = 3.6h", marked)


class UnderFifteenHoursTest(unittest.TestCase):
    """T9 — 1주 15시간 미만이면 산식 대신 '미발생'(근로기준법 제18조 제3항). '주 15시간 이상'은 기준선이라 값에서 뺀다."""

    def test_t9_threshold_is_not_a_work_hour(self):
        out = holiday_card("주 15시간 이상이어야 주휴수당이 나온다던데, 지난주 월화 하루 6시간씩 일했어요.", weekly_work_days=2)
        self.assertIn("조건부 예시 — 근로계약상 1주 소정근로시간이 질문의 근무(주 2일 × 6시간 = 12시간)와 같다면: "
                      "1주 소정근로시간 12h < 15h → 주휴수당 미발생(근로기준법 제18조 제3항)", out)
        self.assertNotIn("min(12h", out)
        self.assertIn(EXAMPLE_HOLD, out)


class UnchangedCardTest(unittest.TestCase):
    """T10 — 예시가 없는 카드의 문구는 그대로다(D7). 구성 보류의 추정 금지는 유지해야 한다(Plan R3)."""

    def test_t10_composition_hold_keeps_its_wording(self):
        from app.core.pipeline import _calculation_context_heading
        out = card({"wage_type": "월급", "wage_amount": 3000000, "business_size": "5인이상", "weekly_work_days": 5,
                    "daily_work_hours": 8, "calculation_types_kr": ["최저임금", "퇴직금"],
                    "start_date": "2023-01-02", "end_date": "2026-01-01"},
                   "월급 300만원에 연장수당이 포함돼 있어요. 주 5일 하루 8시간 일해요. 직원 10명. 최저임금 위반인지와 퇴직금은?")
        self.assertIn("최저임금 충족 여부는 판정하지 않았습니다", out)
        self.assertIn("금액 보류:", out)
        self.assertIn("추정하지 마세요", out)
        self.assertNotIn("조건부 예시", out)
        self.assertEqual(_calculation_context_heading(out), HOLD_HEADING)

    def test_t10_confirmed_holiday_card(self):
        out = holiday_card(kin01_question(), weekly_work_days=3, daily_work_hours=6)
        self.assertEqual(out.splitlines()[:3], [
            "[주휴시간 산정 — 시급 미제공으로 금액은 산정하지 않음]",
            "1주 소정근로시간: 3일 × 6h = 18h",
            "주휴 유급시간: 주 소정근로일 3일 < 5일 → 주휴: min(18h ÷ 5, 8h) = 3.6h (= 18h ÷ 40h × 8h — 1주 소정근로일을 5일로 봄)"])
        self.assertNotIn("조건부 예시", out)

    def test_t10_unknown_card_without_example(self):
        from app.core.pipeline import _calculation_context_heading
        out = holiday_card("지난주 사흘 일했는데 주휴수당은?", weekly_work_days=3)
        self.assertEqual(out.splitlines()[-1], PLAIN_HOLD)
        self.assertEqual(_calculation_context_heading(out), HOLD_HEADING)


class HourMentionTest(unittest.TestCase):
    """T11 — 질문의 'N시간' 해석(_HourMention). 출처 대조가 읽는 앞 세 필드의 회귀는 test_audit50 T10이 본다."""

    def test_t11_daily_total_and_aside(self):
        from app.core.pipeline import _hours_mentions
        cases = {   # (시간, 1일, 표지 있는 합계, 제외 표현)
            "하루 6시간씩 일했어요": [(6.0, True, False, "")],
            "주 3일, 총 18시간": [(18.0, False, True, "")],
            "6시간씩 총 18시간": [(6.0, True, False, ""), (18.0, False, True, "")],
            "하루 6시간 30분씩": [(6.5, True, False, "")],
            "3일 동안 18시간": [(18.0, False, True, "")],
            "주 15시간씩": [(15.0, False, True, "")],
            "일평균 7시간": [(7.0, True, False, "")],
            "월수금 6시간 일했어요": [(6.0, False, False, "")],
            "지난 21일 3시간": [(3.0, False, False, "")],
            "주 15시간 이상이어야 한대요": [(15.0, False, True, "threshold")],
            "주 15시간을 넘어야 받는대요": [(15.0, False, True, "threshold")],
            "15시간 미만이면 안 나와요": [(15.0, False, False, "threshold")],
            "휴게시간 1시간이 있었어요": [(1.0, False, False, "break")],
            "점심 1시간 빼고": [(1.0, False, False, "break")],
            "하루 6~7시간씩": [(7.0, True, False, "range")],
            "매일 2시간씩 연장근무": [(2.0, True, False, "premium")],
            "야간 8시간 근무": [(8.0, False, False, "premium")],
            "월 60시간 일해요": [(60.0, False, False, "period")],
            "2주 동안 총 24시간": [(24.0, False, True, "period")],
        }
        for query, expected in cases.items():
            with self.subTest(query):
                self.assertEqual([(m.value, m.daily, m.total, m.aside) for m in _hours_mentions(query)], expected)

    def test_t11_named_fields_keep_the_grounding_order(self):
        from app.core.pipeline import _HourMention, _hours_mentions
        mention = _hours_mentions("9월 28일~30일 3일 동안 25시간 일했는데")[0]
        self.assertIsInstance(mention, _HourMention)
        self.assertEqual(mention[:3], (25.0, True, (3, 3)))


class WageCalcRulesTest(unittest.TestCase):
    """T12 — 두 답변 분기 공통 규칙에 조건부 예시 지시가 있다. 이 상수는 .format()을 거치는 경로가 있어 중괄호를 쓰지 않는다."""

    def test_t12_rule_present_without_braces(self):
        from app.templates.prompts import WAGE_CALC_RULES
        self.assertIn("계산 카드의 '조건부 예시'는 그 조건(근로계약상 소정근로시간이 질문의 근무와 같다면)을 함께 적어 쓰세요", WAGE_CALC_RULES)
        self.assertIn("질문의 실제 근무시간을 소정근로시간으로 단정하지 마세요", WAGE_CALC_RULES)
        self.assertNotIn("{", WAGE_CALC_RULES)
        self.assertNotIn("}", WAGE_CALC_RULES)


if __name__ == "__main__":
    unittest.main()
