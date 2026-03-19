"""추가정보 요구 질문의 일관성 테스트

동일한 질문을 3회 analyze_intent에 보내서
calculation_types, extracted_info, missing_info, question_summary가
매번 같은지 확인한다.
"""

import json
from datetime import date
from dotenv import load_dotenv

load_dotenv()

from app.config import AppConfig
from app.core.analyzer import analyze_intent
from app.core.pipeline import _compute_missing_info
from app.core.composer import compose_follow_up


def pp_diff(label, results):
    """3회 결과 비교"""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")

    all_same = all(r == results[0] for r in results)
    if all_same:
        print(f"  ✅ 3회 모두 동일")
        print(f"  값: {json.dumps(results[0], ensure_ascii=False, default=str)}")
    else:
        print(f"  ❌ 차이 발견!")
        for i, r in enumerate(results):
            print(f"  [{i+1}회] {json.dumps(r, ensure_ascii=False, default=str)}")


def test_question(question: str, config: AppConfig, runs: int = 3):
    print(f"\n{'#'*60}")
    print(f"  질문: {question[:60]}...")
    print(f"{'#'*60}")

    calc_types_list = []
    extracted_list = []
    missing_llm_list = []
    missing_code_list = []
    summary_list = []
    followup_list = []

    for i in range(runs):
        print(f"\n--- {i+1}회차 실행 ---")
        analysis = analyze_intent(question, [], config)

        calc_types_list.append(sorted(analysis.calculation_types))
        extracted_list.append(sorted(analysis.extracted_info.keys()))
        missing_llm_list.append(sorted(analysis.missing_info))
        summary_list.append(analysis.question_summary)

        # 코드 기반 missing_info
        if analysis.requires_calculation and analysis.calculation_types:
            code_missing = _compute_missing_info(
                analysis.calculation_types, analysis.extracted_info
            )
        else:
            code_missing = []
        missing_code_list.append(sorted(code_missing))

        # follow-up 텍스트
        followup = compose_follow_up(code_missing, analysis.question_summary)
        followup_list.append(followup)

        print(f"  calc_types: {analysis.calculation_types}")
        print(f"  extracted_keys: {sorted(analysis.extracted_info.keys())}")
        print(f"  extracted_vals: {json.dumps(analysis.extracted_info, ensure_ascii=False, default=str)}")
        print(f"  missing (LLM): {analysis.missing_info}")
        print(f"  missing (code): {code_missing}")
        print(f"  summary: {analysis.question_summary}")

    # 비교
    pp_diff("calculation_types", calc_types_list)
    pp_diff("extracted_info 키", extracted_list)
    pp_diff("missing_info (LLM)", missing_llm_list)
    pp_diff("missing_info (코드)", missing_code_list)
    pp_diff("question_summary", summary_list)

    # follow-up 텍스트 비교
    all_same_followup = all(f == followup_list[0] for f in followup_list)
    print(f"\n{'='*60}")
    print(f"  추가질문 텍스트 일관성")
    print(f"{'='*60}")
    if all_same_followup:
        print(f"  ✅ 3회 모두 동일")
        print(f"  ---")
        print(followup_list[0])
    else:
        print(f"  ❌ 차이 발견!")
        for i, f in enumerate(followup_list):
            print(f"\n  [{i+1}회]")
            print(f"  {f}")


def main():
    config = AppConfig.from_env()
    print(f"📅 오늘: {date.today().isoformat()}")
    print(f"🤖 분석 모델: {config.analyzer_model}")

    # 테스트 질문 1: 도우미 야간수당 (최저시급 버그 때 사용한 질문)
    test_question(
        "월-일까지 근무하고 하루에 6시간 도우미를 사용하고 있습니다 "
        "오전 11-14시 오후 18-21시 "
        "질문입니다 "
        "1. 주중 야간에 근무하니 야간수당도 지급해야 하는지요 "
        "2. 주휴수당도 지급해야하는지요 "
        "3. 토일 근무시 150%가산금도 지급해야 하는지요",
        config,
    )

    # 테스트 질문 2: 퇴직금 계산
    test_question(
        "월급 300만원 받고 3년 근무했는데 퇴직금 얼마 받을 수 있나요?",
        config,
    )

    # 테스트 질문 3: 주휴수당 (정보 부분 누락)
    test_question(
        "아르바이트 주휴수당 계산해주세요. 주 4일 근무합니다.",
        config,
    )

    print(f"\n\n{'#'*60}")
    print("  전체 테스트 완료")
    print(f"{'#'*60}")


if __name__ == "__main__":
    main()
