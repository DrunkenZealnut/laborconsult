"""수정 후 추가정보 요구 일관성 테스트

동일 질문 3회 → compose_follow_up 결과가 매번 같은지 확인
"""

import json
from datetime import date
from dotenv import load_dotenv

load_dotenv()

from app.config import AppConfig
from app.core.analyzer import analyze_intent
from app.core.pipeline import _compute_missing_info, _code_based_summary
from app.core.composer import compose_follow_up


def test_question(question: str, config: AppConfig, runs: int = 3):
    print(f"\n{'#'*60}")
    print(f"  질문: {question[:60]}...")
    print(f"{'#'*60}")

    followup_list = []
    for i in range(runs):
        analysis = analyze_intent(question, [], config)

        code_missing = (
            _compute_missing_info(analysis.calculation_types, analysis.extracted_info)
            if analysis.requires_calculation and analysis.calculation_types
            else []
        )

        # 코드 기반 요약 (LLM question_summary 대신)
        deterministic_summary = _code_based_summary(analysis.calculation_types)

        followup = compose_follow_up(code_missing, deterministic_summary)
        followup_list.append(followup)

        print(f"\n--- {i+1}회차 ---")
        print(f"  calc_types: {analysis.calculation_types}")
        print(f"  code_missing: {code_missing}")
        print(f"  summary(코드): {deterministic_summary}")
        print(f"  summary(LLM):  {analysis.question_summary}")

    all_same = all(f == followup_list[0] for f in followup_list)
    print(f"\n{'='*60}")
    print(f"  {'✅ 3회 모두 동일!' if all_same else '❌ 차이 발견!'}")
    print(f"{'='*60}")
    print(followup_list[0])
    if not all_same:
        for i, f in enumerate(followup_list):
            print(f"\n  [{i+1}회] {f}")

    return all_same


def main():
    config = AppConfig.from_env()
    print(f"📅 {date.today().isoformat()}")

    results = []

    results.append(test_question(
        "월-일까지 근무하고 하루에 6시간 도우미를 사용하고 있습니다 "
        "오전 11-14시 오후 18-21시 질문입니다 "
        "1. 주중 야간에 근무하니 야간수당도 지급해야 하는지요 "
        "2. 주휴수당도 지급해야하는지요 "
        "3. 토일 근무시 150%가산금도 지급해야 하는지요",
        config,
    ))

    results.append(test_question(
        "아르바이트 주휴수당 계산해주세요. 주 4일 근무합니다.",
        config,
    ))

    print(f"\n\n{'#'*60}")
    print(f"  전체 결과: {'✅ 모두 통과' if all(results) else '❌ 일부 실패'}")
    print(f"{'#'*60}")


if __name__ == "__main__":
    main()
