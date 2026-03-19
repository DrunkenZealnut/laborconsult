"""E2E 테스트: 최저시급 최저임금 연도 버그 수정 검증

실제 Anthropic API를 호출하여:
1. 첫 질문 → analyze_intent (LLM 추출 확인)
2. 추가정보 "최저시급" 답변 → merge_with_pending 동작 확인
3. 최종 계산 결과 검증 (2026년 10,320원 사용 여부)
"""

import json
import sys
from datetime import date
from dotenv import load_dotenv

load_dotenv()

from app.config import AppConfig
from app.core.analyzer import analyze_intent
from app.models.session import Session, get_or_create_session
from app.models.schemas import AnalysisResult
from app.core.pipeline import (
    _analysis_to_extract_params,
    _ensure_minimum_wage_flag,
    _run_calculator,
    _compute_missing_info,
)
from wage_calculator.constants import MINIMUM_HOURLY_WAGE


def pp(label: str, obj):
    """Pretty-print helper"""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    if isinstance(obj, dict):
        print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            print(f"  [{i}] {item}")
    else:
        print(f"  {obj}")


def main():
    config = AppConfig.from_env()
    today = date.today()
    ref_year = today.year
    expected_min_wage = MINIMUM_HOURLY_WAGE.get(ref_year)

    print(f"📅 오늘: {today.isoformat()}")
    print(f"💰 {ref_year}년 법정 최저시급: {expected_min_wage:,}원")
    print(f"💰 2025년 법정 최저시급: {MINIMUM_HOURLY_WAGE.get(2025):,}원")

    # ─────────────────────────────────────────────
    # 시나리오 1: 첫 질문 (최저시급 미언급 → 임금 누락)
    # ─────────────────────────────────────────────
    question1 = (
        "월-일까지 근무하고 하루에 6시간 도우미를 사용하고 있습니다 "
        "오전 11-14시 오후 18-21시 "
        "질문입니다 "
        "1. 주중 야간에 근무하니 야간수당도 지급해야 하는지요 "
        "2. 주휴수당도 지급해야하는지요 "
        "3. 토일 근무시 150%가산금도 지급해야 하는지요 + 야간수당도 지급??? "
        "이왕이면 산출방법도 알려주세요"
    )
    pp("시나리오 1: 첫 질문", question1)

    print("\n🔍 analyze_intent 호출 중 (실제 LLM)...")
    session = get_or_create_session("test-mw-e2e")
    analysis1 = analyze_intent(question1, session.recent(), config)

    pp("LLM 추출 결과 — requires_calculation", analysis1.requires_calculation)
    pp("LLM 추출 결과 — calculation_types", analysis1.calculation_types)
    pp("LLM 추출 결과 — extracted_info", analysis1.extracted_info)
    pp("LLM 추출 결과 — missing_info (LLM)", analysis1.missing_info)

    # 코드 기반 missing_info 재계산
    if analysis1.requires_calculation and analysis1.calculation_types:
        code_missing = _compute_missing_info(
            analysis1.calculation_types, analysis1.extracted_info
        )
        pp("코드 기반 missing_info", code_missing)
        analysis1.missing_info = code_missing

    # use_minimum_wage 확인
    has_mw_flag = analysis1.extracted_info.get("use_minimum_wage")
    has_wage_amount = analysis1.extracted_info.get("wage_amount")
    print(f"\n✅ use_minimum_wage: {has_mw_flag}")
    print(f"{'⚠️' if has_wage_amount else '✅'} wage_amount: {has_wage_amount}")

    if has_wage_amount and not has_mw_flag:
        print(f"  → LLM이 임금을 직접 추출 ({has_wage_amount}원)")
        if has_wage_amount in MINIMUM_HOURLY_WAGE.values():
            wrong_year = [y for y, w in MINIMUM_HOURLY_WAGE.items() if w == has_wage_amount]
            print(f"  ⚠️ 이 값은 {wrong_year}년도 최저임금입니다!")

    # pending 저장 (추가 질문 시뮬레이션)
    if analysis1.missing_info:
        print(f"\n📋 누락 정보 {len(analysis1.missing_info)}건 → pending 저장")
        session.save_pending(analysis1)
        session.add_user(question1)
        session.add_assistant("추가 정보를 알려주세요...")

    # ─────────────────────────────────────────────
    # 시나리오 2: 추가 답변 "1. 최저시급 2. 6인"
    # ─────────────────────────────────────────────
    followup = "1. 최저시급 2. 6인"
    pp("시나리오 2: 추가 답변", followup)

    print("\n🔍 analyze_intent 호출 중 (추가 답변, 실제 LLM)...")
    analysis2 = analyze_intent(followup, session.recent(), config)

    pp("LLM 추출 결과 — extracted_info", analysis2.extracted_info)
    pp("LLM 추출 결과 — missing_info", analysis2.missing_info)

    # use_minimum_wage 확인 (LLM이 올바르게 설정했는지)
    llm_set_mw = analysis2.extracted_info.get("use_minimum_wage")
    llm_wage_amount = analysis2.extracted_info.get("wage_amount")
    print(f"\n📊 LLM 추출 검증:")
    print(f"  use_minimum_wage: {llm_set_mw} {'✅' if llm_set_mw else '⚠️ LLM이 미설정'}")
    print(f"  wage_amount: {llm_wage_amount} {'⚠️ 환각!' if llm_wage_amount else '✅ 미설정'}")

    # merge_with_pending
    if session.has_pending_info():
        print(f"\n🔄 merge_with_pending 실행...")
        merged = session.merge_with_pending(analysis2, followup)

        pp("병합 결과 — extracted_info", merged.extracted_info)
        pp("병합 결과 — missing_info", merged.missing_info)

        # 핵심 검증: merge 후 use_minimum_wage 여부
        merged_mw = merged.extracted_info.get("use_minimum_wage")
        merged_wage = merged.extracted_info.get("wage_amount")
        print(f"\n🎯 병합 후 최종 상태:")
        print(f"  use_minimum_wage: {merged_mw} {'✅' if merged_mw else '❌ 누락!'}")
        print(f"  wage_amount: {merged_wage} {'❌ 환각 남음!' if merged_wage else '✅ 제거됨'}")

        # 파라미터 변환 + 계산
        params = _analysis_to_extract_params(merged)
        pp("계산기 파라미터 (변환 후)", params)

        # _ensure_minimum_wage_flag 적용
        _ensure_minimum_wage_flag(params, followup)
        pp("최저임금 플래그 보정 후", {
            "use_minimum_wage": params.get("use_minimum_wage"),
            "wage_amount": params.get("wage_amount"),
        })

        # 계산 실행
        print("\n🧮 계산기 실행 중...")
        result = _run_calculator(params)
        if result:
            pp("계산기 결과", result)

            # 최종 검증: 10320 사용 여부
            if str(expected_min_wage) in result:
                print(f"\n✅✅✅ 성공: {ref_year}년 최저시급 {expected_min_wage:,}원 적용 확인!")
            elif "10,030" in result or "10030" in result:
                print(f"\n❌❌❌ 실패: 2025년 최저시급 10,030원이 아직 사용되고 있습니다!")
            else:
                print(f"\n⚠️ 결과에서 최저임금 값 확인 필요")
        else:
            print("\n⚠️ 계산기 결과 없음 (파라미터 부족)")
    else:
        print("\n⚠️ pending 정보가 없습니다 (시나리오 1에서 누락 정보가 없었음)")
        # pending 없는 경우에도 직접 계산 시도
        params = _analysis_to_extract_params(analysis2)
        _ensure_minimum_wage_flag(params, followup)
        pp("계산기 파라미터", params)

    # ─────────────────────────────────────────────
    # 시나리오 3: 직접 "최저시급으로 주휴수당" 질문
    # ─────────────────────────────────────────────
    question3 = "최저시급으로 주5일 8시간 근무할 때 주휴수당은 얼마인가요?"
    pp("시나리오 3: 직접 최저시급 질문", question3)

    print("\n🔍 analyze_intent 호출 중 (직접 질문, 실제 LLM)...")
    session3 = get_or_create_session("test-mw-e2e-3")
    analysis3 = analyze_intent(question3, session3.recent(), config)

    pp("LLM 추출 결과 — extracted_info", analysis3.extracted_info)

    mw3 = analysis3.extracted_info.get("use_minimum_wage")
    wa3 = analysis3.extracted_info.get("wage_amount")
    print(f"\n📊 LLM 추출 검증:")
    print(f"  use_minimum_wage: {mw3} {'✅' if mw3 else '⚠️'}")
    print(f"  wage_amount: {wa3} {'⚠️ 환각!' if wa3 else '✅'}")

    params3 = _analysis_to_extract_params(analysis3)
    _ensure_minimum_wage_flag(params3, question3)

    if not params3.get("needs_calculation"):
        params3["needs_calculation"] = True
    if not params3.get("calculation_type"):
        params3["calculation_type"] = "주휴수당"

    pp("계산기 파라미터", params3)

    result3 = _run_calculator(params3)
    if result3:
        pp("계산기 결과", result3)
        if str(expected_min_wage) in result3:
            print(f"\n✅✅✅ 성공: {ref_year}년 최저시급 {expected_min_wage:,}원 적용 확인!")
        elif "10,030" in result3 or "10030" in result3:
            print(f"\n❌❌❌ 실패: 2025년 최저시급 10,030원이 아직 사용되고 있습니다!")

    print(f"\n{'='*60}")
    print("  테스트 완료")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
