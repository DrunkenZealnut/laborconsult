"""output_legal_cases에서 10개 케이스를 뽑아 파이프라인 E2E 테스트.

각 케이스의 질문을 파이프라인에 보내고, 응답의 판례 환각 여부를 검증한다.
"""

import json
import time
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.config import AppConfig
from app.core.pipeline import process_question
from app.models.session import Session
from app.core.citation_validator import _PREC_PATTERN

# ── 테스트 케이스 10개 (다양한 주제) ─────────────────────────────────────────

TEST_CASES = [
    {
        "id": "case_010",
        "title": "학원강사의 근로자성",
        "query": "한국어 학원 강사를 근로자로 볼 수 있는지, 수업 중 화상을 입은 사고를 산재로 인정받을 수 있는지 궁금합니다.",
        "topic": "근로자성/산재",
        "known_refs": [],  # RAG에서 관련 판례를 찾아야 함
    },
    {
        "id": "case_003",
        "title": "이메일 합격 통보 후 해고통보",
        "query": "이메일로 합격 통보를 받고 입사서류를 제출했는데, 며칠 후 구두로 해고통보를 받았습니다. 부당해고 구제신청이 가능한가요?",
        "topic": "채용내정 취소/부당해고",
        "known_refs": ["2019구합64167", "2019두39314"],
    },
    {
        "id": "case_006",
        "title": "정년퇴직 후 촉탁직 2년 근무",
        "query": "만 60세에 정년퇴직 후 촉탁직으로 3년째 근무 중입니다. 기간제 근로자 2년 초과 시 정규직 전환이 되는지, 회사가 마음대로 해고할 수 있는지 문의합니다.",
        "topic": "기간제/무기계약 전환",
        "known_refs": ["2012두18967"],
    },
    {
        "id": "case_016",
        "title": "공장 토요일 특근 수당 계산",
        "query": "야간 고정 근무(저녁 9시~아침 9시, 휴게 2시간)를 하고 있습니다. 토요일 특근 일당은 어떻게 계산하나요? 최저시급 기준으로 연장+야간+휴일수당 계산법을 알려주세요.",
        "topic": "연장/야간/휴일수당",
        "known_refs": [],
    },
    {
        "id": "case_019",
        "title": "초단시간 근로자 연장근로수당",
        "query": "10인 사업장에서 주 14시간 아르바이트 계약인데 연장근로가 발생해 주 18시간을 일했습니다. 초단시간근로자도 연장근로수당과 주휴수당을 받을 수 있나요?",
        "topic": "초단시간/연장근로",
        "known_refs": [],
    },
    {
        "id": "case_041",
        "title": "육아휴직 종료 후 퇴사 시 퇴직연금",
        "query": "육아휴직 중인데 휴직 종료와 동시에 퇴사하려고 합니다. DC형 퇴직금 적립 중 육아휴직기간이 있는 경우 퇴직금 계산 방법이 어떻게 되나요?",
        "topic": "육아휴직/퇴직금",
        "known_refs": [],
    },
    {
        "id": "case_048",
        "title": "택시기사 최저임금 위반 여부",
        "query": "택시기사인데 운송수입금의 40%를 기본급, 승무수당, 상여금, 성과급으로 나눠 받고 있습니다. 기본급이 최저임금에 미달하면 위반인가요?",
        "topic": "택시/최저임금",
        "known_refs": [],
    },
    {
        "id": "case_059",
        "title": "부제소 특약에 따른 퇴직금 청구 포기",
        "query": "퇴직금을 받으면서 부제소 특약(청구포기)에 동의했습니다. 이 동의가 유효한지, 퇴직금을 못 받게 되는 건지 궁금합니다.",
        "topic": "부제소 합의/퇴직금",
        "known_refs": ["2005다36762"],
    },
    {
        "id": "case_082",
        "title": "만 65세 이후 재취업 실업급여",
        "query": "65세 이후에 용역에서 재단법인으로 촉탁직 직고용되어 3년 근무 후 계약만료 퇴직했습니다. 실업급여를 받을 수 있나요? 고용보험료는 계속 납부했습니다.",
        "topic": "65세/실업급여",
        "known_refs": [],
    },
    {
        "id": "case_088",
        "title": "저성과 해고와 해고예고",
        "query": "저성과를 이유로 해고통지서를 받았는데 해고일까지 10일밖에 안 남았습니다. 해고예고수당을 받을 수 있나요? 저성과가 정당한 해고 사유가 되나요?",
        "topic": "해고예고/부당해고",
        "known_refs": [],
    },
]


def run_test(config: AppConfig, case: dict) -> dict:
    """단일 케이스 테스트 실행."""
    t0 = time.time()
    full_text = ""
    events = []
    replaced = False

    session = Session(id=f"test_{case['id']}")
    for event in process_question(
        query=case["query"],
        session=session,
        config=config,
    ):
        events.append(event)
        if event.get("type") == "chunk":
            full_text += event["text"]
        elif event.get("type") == "replace":
            full_text = event["text"]
            replaced = True

    elapsed = time.time() - t0

    # 판례 번호 추출
    cited = []
    for m in _PREC_PATTERN.finditer(full_text):
        year = int(m.group(1))
        case_type = m.group(2)
        number = int(m.group(3))
        if 1950 <= year <= 2030 and number <= 999999:
            cited.append(f"{year}{case_type}{number}")
    cited = list(set(cited))

    return {
        "id": case["id"],
        "title": case["title"],
        "topic": case["topic"],
        "query": case["query"][:60],
        "elapsed_sec": round(elapsed, 1),
        "response_length": len(full_text),
        "cited_precedents": cited,
        "cited_count": len(cited),
        "replaced": replaced,
        "has_disclaimer": "법적 효력" in full_text or "참고용" in full_text,
        "has_contact": "1350" in full_text or "노동위원회" in full_text,
        "response_preview": full_text[:200].replace("\n", " "),
    }


def main():
    config = AppConfig.from_env()
    results = []
    total_cited = 0
    total_replaced = 0

    print("=" * 70)
    print("노동법 상담 E2E 테스트 — 10개 법률 케이스")
    print("=" * 70)

    for i, case in enumerate(TEST_CASES, 1):
        print(f"\n[{i}/10] {case['id']}: {case['title']}")
        print(f"  질문: {case['query'][:60]}...")

        try:
            result = run_test(config, case)
            results.append(result)

            total_cited += result["cited_count"]
            if result["replaced"]:
                total_replaced += 1

            print(f"  ✅ 완료 ({result['elapsed_sec']}초, {result['response_length']}자)")
            print(f"  판례 인용: {result['cited_count']}건 {result['cited_precedents']}")
            if result["replaced"]:
                print(f"  ⚠️ 환각 교정 발생 (replace 이벤트)")
            print(f"  면책고지: {'✅' if result['has_disclaimer'] else '❌'}")
            print(f"  연락처: {'✅' if result['has_contact'] else '—'}")
        except Exception as e:
            print(f"  ❌ 오류: {e}")
            results.append({
                "id": case["id"],
                "title": case["title"],
                "error": str(e),
            })

    # 요약
    print("\n" + "=" * 70)
    print("테스트 결과 요약")
    print("=" * 70)
    success = [r for r in results if "error" not in r]
    errors = [r for r in results if "error" in r]

    print(f"성공: {len(success)}/10")
    print(f"실패: {len(errors)}/10")
    if success:
        avg_time = sum(r["elapsed_sec"] for r in success) / len(success)
        avg_len = sum(r["response_length"] for r in success) / len(success)
        print(f"평균 응답 시간: {avg_time:.1f}초")
        print(f"평균 응답 길이: {avg_len:.0f}자")
        print(f"총 판례 인용: {total_cited}건")
        print(f"환각 교정 발생: {total_replaced}건")
        disclaimer_count = sum(1 for r in success if r.get("has_disclaimer"))
        print(f"면책고지 포함: {disclaimer_count}/{len(success)}")

    print("\n─── 케이스별 상세 ───")
    for r in results:
        if "error" in r:
            print(f"  ❌ {r['id']}: {r['error'][:60]}")
        else:
            status = "🔄" if r["replaced"] else "✅"
            print(f"  {status} {r['id']} ({r['topic']}): "
                  f"{r['elapsed_sec']}s, 판례 {r['cited_count']}건, "
                  f"{'면책✅' if r['has_disclaimer'] else '면책❌'}")

    # JSON 저장
    with open("test_legal_cases_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n상세 결과 저장: test_legal_cases_results.json")


if __name__ == "__main__":
    main()
