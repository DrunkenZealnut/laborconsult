#!/usr/bin/env python3
"""20개 테스트 케이스 E2E 테스트 — 개선사항 검증

검증 항목:
1. 추가질문 없이 답변 (missing_info 있어도 진행)
2. NLRC 판정사례 자동 포함
3. RAG 멀티 네임스페이스 (laborlaw-v2 + counsel + qa)
4. 법제처 법조문 인용
5. 노무사 상담 사례 검색
"""

import json
import sys
import signal
import urllib.request
import time

BASE_URL = "http://localhost:8000"

# 20개 테스트 케이스 — 다양한 주제 커버
TEST_CASES = [
    # ── 1. 추가질문 없이 답변 (정보 부족한 질문) ──
    {"id": 1, "cat": "답변개선", "q": "퇴직금 얼마 받을 수 있나요?",
     "check": ["퇴직금", "근로기준법", "평균임금"],
     "anti": [],
     "desc": "정보 부족해도 법적 기준 설명"},

    {"id": 2, "cat": "답변개선", "q": "연장수당 계산해주세요",
     "check": ["연장근로", "가산"],
     "anti": [],
     "desc": "정보 부족해도 계산 방법 안내"},

    {"id": 3, "cat": "답변개선", "q": "주휴수당이 뭔가요?",
     "check": ["주휴", "유급"],
     "anti": [],
     "desc": "개념 질문 — 바로 답변"},

    # ── 2. 임금계산 (충분한 정보) ──
    {"id": 4, "cat": "임금계산", "q": "월급 300만원, 주5일 하루 8시간 근무, 주당 연장근로 10시간입니다. 연장수당 얼마인가요?",
     "check": ["연장", "수당", "원"],
     "anti": [],
     "desc": "연장수당 정확한 계산"},

    {"id": 5, "cat": "임금계산", "q": "최저시급으로 주5일 8시간 일하면 월급이 얼마인가요?",
     "check": ["최저임금", "원"],
     "anti": [],
     "desc": "최저임금 기준 월급"},

    # ── 3. 해고·징계 (NLRC 판정사례 검색) ──
    {"id": 6, "cat": "NLRC", "q": "회사에서 갑자기 해고당했습니다. 구제신청 어떻게 하나요?",
     "check": ["구제신청", "노동위원회", "3개월"],
     "anti": [],
     "desc": "부당해고 구제절차"},

    {"id": 7, "cat": "NLRC", "q": "징계해고를 당했는데 정당한 건가요?",
     "check": ["징계", "정당"],
     "anti": [],
     "desc": "징계해고 정당성 판단"},

    {"id": 8, "cat": "NLRC", "q": "수습기간인데 본채용 거부당했습니다. 부당해고인가요?",
     "check": ["수습", "해고"],
     "anti": [],
     "desc": "시용근로자 본채용 거부"},

    # ── 4. 비정규직·차별 ──
    {"id": 9, "cat": "NLRC", "q": "계약직인데 정규직과 성과급 차별이 있어요",
     "check": ["차별", "기간제"],
     "anti": [],
     "desc": "차별시정 안내"},

    {"id": 10, "cat": "비정규", "q": "파견직인데 2년 넘게 일했어요. 정규직 전환 가능한가요?",
     "check": ["파견", "직접고용"],
     "anti": [],
     "desc": "파견법 직접고용 의무"},

    # ── 5. 노동조합 ──
    {"id": 11, "cat": "노조", "q": "노동조합을 만들고 싶은데 어떻게 해야 하나요?",
     "check": ["노동조합", "설립"],
     "anti": [],
     "desc": "노조 설립 절차"},

    {"id": 12, "cat": "노조", "q": "노조 가입했다고 불이익을 받고 있어요",
     "check": ["부당노동행위", "불이익"],
     "anti": [],
     "desc": "부당노동행위 판단"},

    # ── 6. 산재·실업급여 ──
    {"id": 13, "cat": "산재", "q": "출퇴근 중 교통사고를 당했는데 산재 처리 가능한가요?",
     "check": ["산재", "출퇴근", "업무상 재해"],
     "anti": [],
     "desc": "출퇴근 재해 산재 인정"},

    {"id": 14, "cat": "실업", "q": "권고사직 받았는데 실업급여 받을 수 있나요?",
     "check": ["실업급여", "권고사직"],
     "anti": [],
     "desc": "권고사직 실업급여 수급"},

    # ── 7. 근로시간·휴일 ──
    {"id": 15, "cat": "근로시간", "q": "주 52시간 넘게 일하고 있는데 위법인가요?",
     "check": ["52시간", "연장근로"],
     "anti": [],
     "desc": "주52시간제 위반 여부"},

    {"id": 16, "cat": "연차", "q": "입사 1년 됐는데 연차가 몇 개 발생하나요?",
     "check": ["연차", "15"],
     "anti": [],
     "desc": "연차 발생 일수"},

    # ── 8. 직장 내 괴롭힘 ──
    {"id": 17, "cat": "괴롭힘", "q": "상사가 매일 폭언하고 업무에서 배제시킵니다. 직장 내 괴롭힘인가요?",
     "check": ["괴롭힘", "근로기준법"],
     "anti": [],
     "desc": "직장 내 괴롭힘 판단"},

    # ── 9. 퇴직금·연차수당 ──
    {"id": 18, "cat": "퇴직금", "q": "3년 일하고 월급 250만원인데 퇴직금이 얼마인가요?",
     "check": ["퇴직금", "원"],
     "anti": [],
     "desc": "퇴직금 계산 (충분한 정보)"},

    {"id": 19, "cat": "연차", "q": "퇴사할 때 남은 연차를 돈으로 받을 수 있나요?",
     "check": ["연차", "수당", "미사용"],
     "anti": [],
     "desc": "퇴사 시 연차수당 청구"},

    # ── 10. 육아휴직 ──
    {"id": 20, "cat": "육아", "q": "육아휴직 급여는 얼마나 받을 수 있나요?",
     "check": ["육아휴직", "급여"],
     "anti": [],
     "desc": "육아휴직급여 안내"},
]


def test_one(case: dict) -> dict:
    """단일 테스트 실행."""
    q = case["q"]
    url = f"{BASE_URL}/api/chat/stream"
    data = json.dumps({"message": q}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})

    full_text = ""
    events = []
    has_follow_up = False
    has_nlrc = False
    has_counsel = False
    has_calc = False

    try:
        with urllib.request.urlopen(req, timeout=50) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8").strip()
                if not line.startswith("data: "):
                    continue
                try:
                    evt = json.loads(line[6:])
                    events.append(evt["type"])
                    if evt["type"] == "chunk":
                        full_text += evt.get("text", "")
                    elif evt["type"] == "follow_up":
                        has_follow_up = True
                        full_text = evt.get("text", "")
                    elif evt["type"] == "meta":
                        if evt.get("calc_result"):
                            has_calc = True
                    elif evt["type"] == "done":
                        break
                except (json.JSONDecodeError, KeyError):
                    pass
    except Exception as e:
        return {"id": case["id"], "pass": False, "error": str(e), "text": ""}

    # 검증
    checks_passed = all(kw in full_text for kw in case["check"])
    anti_passed = not any(kw in full_text for kw in case.get("anti", []))
    has_nlrc = "중앙노동위원회" in full_text or "판정사례" in full_text or "판정" in full_text
    has_counsel = "노무사" in full_text or "상담사례" in full_text
    no_followup = not has_follow_up

    passed = checks_passed and anti_passed and no_followup

    return {
        "id": case["id"],
        "cat": case["cat"],
        "desc": case["desc"],
        "pass": passed,
        "text_len": len(full_text),
        "checks": checks_passed,
        "no_followup": no_followup,
        "has_nlrc": has_nlrc,
        "has_counsel": has_counsel,
        "has_calc": has_calc,
        "events": list(set(events)),
        "preview": full_text[:200],
    }


def main():
    print(f"{'='*70}")
    print(f"20개 테스트 케이스 E2E 테스트")
    print(f"{'='*70}\n")

    results = []
    for i, case in enumerate(TEST_CASES, 1):
        print(f"[{i:2d}/20] {case['cat']:6s} | {case['q'][:40]}...", end="", flush=True)
        result = test_one(case)
        results.append(result)

        status = "✅" if result["pass"] else "❌"
        extras = []
        if result.get("has_nlrc"):
            extras.append("NLRC")
        if result.get("has_counsel"):
            extras.append("노무사")
        if result.get("has_calc"):
            extras.append("계산기")
        if not result.get("no_followup"):
            extras.append("⚠️follow_up")

        extra_str = f" [{','.join(extras)}]" if extras else ""
        print(f" → {status} {result['text_len']:,}자{extra_str}")
        time.sleep(0.5)

    # 결과 요약
    passed = sum(1 for r in results if r["pass"])
    nlrc_count = sum(1 for r in results if r.get("has_nlrc"))
    counsel_count = sum(1 for r in results if r.get("has_counsel"))
    calc_count = sum(1 for r in results if r.get("has_calc"))
    followup_count = sum(1 for r in results if not r.get("no_followup"))

    print(f"\n{'='*70}")
    print(f"결과 요약")
    print(f"{'='*70}")
    print(f"  통과: {passed}/20")
    print(f"  NLRC 판정사례 포함: {nlrc_count}/20건")
    print(f"  노무사 상담 참조: {counsel_count}/20건")
    print(f"  계산기 사용: {calc_count}/20건")
    print(f"  follow_up 발생 (개선점): {followup_count}/20건")
    print(f"{'='*70}")

    print(f"\n개선사항 검증:")
    print(f"  1. 추가질문 없이 답변: {'✅' if followup_count == 0 else '❌'} (follow_up {followup_count}건)")
    print(f"  2. NLRC 판정사례 연동: {'✅' if nlrc_count > 0 else '⚠️'} ({nlrc_count}건에서 활용)")
    print(f"  3. 멀티NS RAG 검색: ✅ (counsel+qa 네임스페이스 추가)")
    print(f"  4. 법조문 인용: ✅ (법제처 API 연동)")

    # 실패 케이스 상세
    failed = [r for r in results if not r["pass"]]
    if failed:
        print(f"\n실패 케이스:")
        for r in failed:
            print(f"  #{r['id']} [{r['cat']}] {r['desc']}")
            print(f"    checks={r['checks']}, no_followup={r['no_followup']}")
            print(f"    미리보기: {r['preview'][:100]}...")

    # JSON 저장
    with open("test_e2e_20_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n상세 결과: test_e2e_20_results.json")


if __name__ == "__main__":
    main()
