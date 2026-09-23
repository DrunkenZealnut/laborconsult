"""파이프라인 배선 테스트 — analyzer 추출값이 계산기까지 도달하는지 검증 (CALC-1/2/3)

LLM·네트워크·API 키 불요. analysis 스텁 → _analysis_to_extract_params →
_run_calculator 경로를 오프라인으로 검증한다.
(엔진 자체의 수치 검증은 test_wage_golden.py 담당 — 여기서는 '배선'만 본다)

실행: python3 test_pipeline_wiring.py
"""

from __future__ import annotations

from types import SimpleNamespace

import app.core.pipeline as pl
from app.core.pipeline import _analysis_to_extract_params, _run_calculator


def stub(types: list[str], info: dict) -> SimpleNamespace:
    return SimpleNamespace(
        requires_calculation=True,
        calculation_types=types,
        extracted_info=info,
    )


def run(types: list[str], info: dict, query: str = "") -> str | None:
    params = _analysis_to_extract_params(stub(types, info))
    return _run_calculator(params, query)


def main() -> None:
    # ── W1. 체불 배선: arrear_* 가 WageInput까지 도달해 지연이자 계산 실행 ──
    r = run(["wage_arrears"], {
        "wage_type": "월급", "monthly_wage": 3_000_000,
        "arrear_amount": 10_000_000, "arrear_due_date": "2026-01-10",
    })
    assert r and "임금체불 지연이자" in r, f"W1 실패:\n{r}"
    print("  ✅ W1 체불 배선 → 지연이자 섹션 생성")

    # ── W2. 체불 + 임금 정보 없음: wageless 부분 실행 경로에서도 계산됨 ──
    r = run(["wage_arrears"], {
        "arrear_amount": 5_000_000, "arrear_due_date": "2026-03-01",
    })
    assert r and "임금체불 지연이자" in r, f"W2 실패:\n{r}"
    print("  ✅ W2 임금 없는 체불 질문도 지연이자 계산 실행")

    # ── W3. 육아휴직 배선 ──
    r = run(["parental_leave"], {
        "wage_type": "월급", "monthly_wage": 3_000_000,
        "parental_leave_months": 12,
    })
    assert r and "육아휴직" in r, f"W3 실패:\n{r}"
    print("  ✅ W3 육아휴직 개월수 배선 → 급여 계산 실행")

    # ── W4. 수습 감액: is_probation + contract_months ≥ 12개월 → 90% 적용 ──
    r4 = run(["minimum_wage"], {
        "wage_type": "시급", "wage_amount": 9_000,
        "is_probation": True, "contract_months": 12,
        "reference_year": 2026,
    })
    assert r4 and "수습" in r4, f"W4 실패:\n{r4}"
    print("  ✅ W4 수습·계약기간 배선 → 수습 감액 반영")

    # ── W5. 수습 + 단순노무(직종코드 9): 감액 제외 → W4와 판정이 달라야 함 ──
    r5 = run(["minimum_wage"], {
        "wage_type": "시급", "wage_amount": 9_000,
        "is_probation": True, "contract_months": 12,
        "occupation_code": "9", "reference_year": 2026,
    })
    assert r5, f"W5 실패:\n{r5}"
    assert r4 != r5, "W5 실패: 단순노무 직종코드가 감액 판정에 반영되지 않음"
    print("  ✅ W5 직종코드 배선 → 단순노무 수습 감액 제외")

    # ── W6. 복수 계산유형: 퇴직금 + 연차 모두 계산 (첫 유형만 계산되던 결함) ──
    r = run(["severance", "annual_leave"], {
        "wage_type": "월급", "monthly_wage": 3_000_000,
        "start_date": "2023-01-01", "end_date": "2026-01-01",
    })
    assert r and "퇴직금" in r, f"W6 실패(퇴직금 누락):\n{r}"
    assert "연차" in r, f"W6 실패(연차 누락 — 복수 유형 라우팅 결함):\n{r}"
    print("  ✅ W6 복수 계산유형 union 라우팅 (퇴직금+연차 동시)")

    # ── W7. 계산기 예외 → 오류 문자열 대신 None (LLM 주입 차단) ──
    class _Boom:
        def calculate(self, *a, **k):
            raise RuntimeError("intentional")

    orig = pl.WageCalculator
    pl.WageCalculator = _Boom
    try:
        r = run(["minimum_wage"], {"wage_type": "시급", "wage_amount": 10_320})
    finally:
        pl.WageCalculator = orig
    assert r is None, f"W7 실패: 예외가 오류 문자열로 반환됨 → {r!r}"
    print("  ✅ W7 계산 예외 시 None 반환 (오류 문자열 주입 차단)")

    # ── W8. 고정수당 배선: 통상임금에 수당 합산 ──
    r = run(["minimum_wage"], {
        "wage_type": "월급", "monthly_wage": 3_000_000,
        "fixed_allowances": [{"name": "식대", "amount": 200_000, "condition": "없음"}],
    })
    assert r and "3,200,000" in r, f"W8 실패(수당 미합산):\n{r}"
    print("  ✅ W8 고정수당 배선 → 통상임금 합산 (300만+식대 20만)")

    # ── W9. 기존 경로 회귀: 단일 유형 최저임금 검증 형식 불변 ──
    r = run(["minimum_wage"], {
        "wage_type": "시급", "wage_amount": 10_320, "reference_year": 2026,
    })
    assert r and "최저임금" in r, f"W9 실패:\n{r}"
    print("  ✅ W9 기존 단일 유형 경로 회귀 없음")

    # ── W10. 최저임금 사실 블록: 표의 최신 연도가 실리고, 표에 없는 연도를 "미고시"로 단정하지 않음 ──
    # 2027년 고시(2026-08-05)가 표에 없어 챗봇이 "아직 고시되지 않았다"고 답한 실장애(2026-09-22).
    # 표 누락은 데이터 갱신 문제이지만, 그것을 사용자에게 "고시 안 됨"이라는 거짓 사실로 바꾸는
    # 문구가 두 번째 원인이었다 — 시스템은 미등록만 알 수 있고 미고시는 알 수 없다.
    from wage_calculator.constants import MINIMUM_HOURLY_WAGE
    block = pl._build_minwage_facts("2027년 최저임금 얼마인가요?", None)
    assert block, "W10 실패: 최저임금 신호에 사실 블록 미생성"
    latest = max(MINIMUM_HOURLY_WAGE)
    assert f"{latest}년: 시급 {MINIMUM_HOURLY_WAGE[latest]:,}원" in block, f"W10 실패(최신 연도 누락):\n{block}"
    assert "고시되지 않은" not in block, f"W10 실패(미고시 단정 문구 잔존):\n{block}"
    print(f"  ✅ W10 최저임금 사실 블록 → 표 최신 연도({latest}) 포함, 미고시 단정 없음")

    # ── W11. 4대보험 사실 블록이 계산기와 같은 수치를 말한다 ──
    # 기준소득월액은 연중 7월에 바뀌는데(시행령 제5조④) 사실 블록이 연 단위 표를 직접
    # 읽고 있어, 하반기에는 같은 답변 안에서 블록과 계산 결과가 갈렸다(실측 2026-09-23).
    from wage_calculator.constants import get_insurance_rates
    from wage_calculator.legal_rules import kst_today
    block = pl._build_insurance_facts("4대보험 얼마나 떼나요?", None)
    assert block, "W11 실패: 4대보험 신호에 사실 블록 미생성"
    today = kst_today()
    rates = get_insurance_rates(int(today[:4]), today)
    for label, key in (("기준소득 상한", "pension_income_max"), ("기준소득 하한", "pension_income_min"),
                       ("건보료 상한", "health_premium_max"), ("건보료 하한", "health_premium_min")):
        assert f"{rates[key]:,}원" in block, f"W11 실패({label} 불일치 {rates[key]:,}):\n{block}"
    assert "7월부터 다음 해 6월" in block, f"W11 실패(적용기간 고지 누락):\n{block}"
    print(f"  ✅ W11 4대보험 사실 블록 → 계산기와 동일 수치(기준일 {today})")

    # ── W12. 요율 표가 낡아도 사실 블록과 계산기가 같은 구간을 읽는다 ──
    # 표에 올해가 없으면 표시용 연도가 뒤로 밀리는데, 그 연도를 조회에까지 쓰면 기준일이
    # 연도 불일치로 버려져 계산기와 다른 기준소득월액이 나온다(CodeRabbit PR #77).
    from unittest.mock import patch as _patch
    from wage_calculator.constants import INSURANCE_RATES
    _future = f"{max(INSURANCE_RATES) + 1}-03-01"
    with _patch("wage_calculator.legal_rules.kst_today", return_value=_future):
        block = pl._build_insurance_facts("4대보험 얼마나 떼나요?", None)
        rates = get_insurance_rates(int(_future[:4]), _future)
        for key in ("pension_income_max", "pension_income_min"):
            assert f"{rates[key]:,}원" in block, (
                f"W12 실패({key} 불일치 {rates[key]:,} — 표 최신연도 {max(INSURANCE_RATES)}):\n{block}")
    print(f"  ✅ W12 요율표 미갱신({_future[:4]}년) 상태에서도 사실 블록 = 계산기")

    # ── W13. 출산 유형 배선: 다태아·미숙아가 휴가 일수를 바꾼다 ──
    # 두 필드는 계산기·흐름도만 지원하고 상담 경로에는 배선이 없어, 챗봇이 다태아
    # 질문에도 90일로 답했다(실측 2026-09-23). 일수는 급여 총액을 직접 바꾼다.
    base = {"wage_type": "월급", "monthly_wage": 5_000_000, "reference_year": 2026}
    r90 = run(["maternity_leave"], base)
    r120 = run(["maternity_leave"], {**base, "is_multiple_birth": True})
    r100 = run(["maternity_leave"], {**base, "is_premature_birth": True,
                                     "reference_date": "2026-05-01"})
    assert r90 and "90일" in r90, f"W13 실패(단태아 90일 누락):\n{r90}"
    assert r120 and "120일" in r120, f"W13 실패(다태아 배선 없음):\n{r120}"
    assert r100 and "100일" in r100, f"W13 실패(미숙아 배선 없음):\n{r100}"
    print("  ✅ W13 출산 유형 배선 → 단태아 90일 / 다태아 120일 / 미숙아 100일")

    # ── 파라미터 변환 계층 자체 검증 ──
    p = _analysis_to_extract_params(stub(
        ["severance", "annual_leave"],
        {"monthly_wage": 3_000_000, "notice_days_given": 10,
         "occupation_code": "9", "fixed_allowances": [{"name": "a", "amount": 1}]},
    ))
    assert p["calculation_types_kr"] == ["퇴직금", "연차수당"], p
    assert p["notice_days_given"] == 10 and p["occupation_code"] == "9", p
    assert p["fixed_allowances"], p
    print("  ✅ 변환 계층: calculation_types_kr + 신규 6필드 전달")

    print("\n✅ 배선 테스트 전부 통과")


if __name__ == "__main__":
    main()
