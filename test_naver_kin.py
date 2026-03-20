"""네이버 지식iN 고용·노동 질문 자동 테스트

사용법:
  python3 test_naver_kin.py                     # 분야별 대표 10건 테스트
  python3 test_naver_kin.py --all               # 198건 전량 테스트
  python3 test_naver_kin.py --count 20          # 분야별 N건 테스트
  python3 test_naver_kin.py --field 근로기준     # 특정 분야만 테스트
"""

import argparse
import json
import os
import sys
import time
import uuid
from collections import defaultdict
from pathlib import Path

# .env 로드
for line in Path(".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from app.config import AppConfig
from app.models.session import Session
from app.core.pipeline import process_question

INPUT_PATH = "test_sample/naver_kin_608_고용_노동.json"
OUTPUT_MD = "test_sample/naver_kin_608_test_results.md"
OUTPUT_JSON = "test_sample/naver_kin_608_test_results.json"


def select_questions(data, args):
    """분야별 대표 질문 선별."""
    questions = data["questions"]

    if args.field:
        questions = [q for q in questions if args.field in q.get("field", "")]
        if not questions:
            print(f"분야 '{args.field}'에 해당하는 질문이 없습니다.")
            sys.exit(1)

    if args.all:
        return questions

    by_field = defaultdict(list)
    for q in questions:
        by_field[q.get("field", "기타")].append(q)

    per_field = max(1, args.count // len(by_field)) if args.count else 1
    selected = []
    for field, qs in sorted(by_field.items(), key=lambda x: -len(x[1])):
        sorted_qs = sorted(qs, key=lambda x: len(x.get("content", "")), reverse=True)
        selected.extend(sorted_qs[:per_field])

    # count 지정 시 조정
    if args.count and len(selected) < args.count:
        remaining = [q for q in questions if q not in selected]
        selected.extend(remaining[: args.count - len(selected)])

    return selected[:args.count] if args.count else selected


def run_test(questions, config):
    """파이프라인으로 질문 처리."""
    results = []
    total = len(questions)

    for i, q in enumerate(questions):
        title = q["title"]
        content = q["content"]
        field = q.get("field", "")
        doc_id = q.get("doc_id", "")

        print(f"[{i+1}/{total}] {title[:45]}...", end=" ", flush=True)

        session = Session(id=str(uuid.uuid4()))
        full_answer = ""
        calc_result = None
        error = None

        try:
            start = time.time()
            for event in process_question(content, session, config):
                etype = event.get("type", "")
                if etype == "chunk":
                    full_answer += event.get("text", "")
                elif etype == "replace":
                    full_answer = event.get("text", "")
                elif etype == "meta":
                    if "calc_result" in event:
                        calc_result = event["calc_result"]
                elif etype == "error":
                    error = event.get("text", "")
            elapsed = time.time() - start
            print(f"{elapsed:.1f}s / {len(full_answer)}자", flush=True)
        except Exception as e:
            elapsed = time.time() - start
            error = str(e)
            print(f"ERROR {elapsed:.1f}s: {e}", flush=True)

        results.append({
            "index": i + 1,
            "doc_id": doc_id,
            "field": field,
            "title": title,
            "question": content,
            "answer": full_answer if full_answer else f"[오류: {error}]",
            "has_calc": bool(calc_result),
            "answer_length": len(full_answer),
            "elapsed": round(elapsed, 1),
            "error": error,
        })

    return results


def verify_quality(results):
    """품질 지표 자동 검증."""
    if not results:
        return [("성공률", "100%", "N/A", False)]
    checks = []

    # 성공률
    success = sum(1 for r in results if not r["error"])
    rate = success / len(results) * 100
    checks.append(("성공률", "100%", f"{rate:.0f}%", rate == 100))

    # 면책 포함률
    markers = ["법적 효력", "참고용", "공인노무사", "참고 정보", "법적 조언이 아"]
    has_disclaimer = sum(
        1 for r in results if any(m in r["answer"] for m in markers)
    )
    d_rate = has_disclaimer / len(results) * 100
    checks.append(("면책 고지 포함률", "≥90%", f"{d_rate:.0f}%", d_rate >= 90))

    # 평균 응답 시간
    avg_time = sum(r["elapsed"] for r in results) / len(results)
    checks.append(("평균 응답 시간", "≤60초", f"{avg_time:.1f}초", avg_time <= 60))

    # 기관 연락처
    contact_markers = [
        "1350", "1588-0075", "고용노동부", "근로복지공단", "노동위원회", "고용센터",
    ]
    has_contact = sum(
        1 for r in results if any(m in r["answer"] for m in contact_markers)
    )
    c_rate = has_contact / len(results) * 100
    checks.append(("기관 연락처 포함률", "≥80%", f"{c_rate:.0f}%", c_rate >= 80))

    return checks


def generate_report(results, checks):
    """마크다운 보고서 생성."""
    lines = []
    lines.append("# 네이버 지식iN 고용·노동 질문 테스트 결과\n")
    lines.append(f"> **테스트 일시**: {time.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"> **데이터 소스**: `{INPUT_PATH}`")
    lines.append(f"> **테스트 건수**: {len(results)}건\n")

    # 품질 지표
    lines.append("---\n\n## 품질 지표\n")
    lines.append("| 지표 | 목표 | 실제 | 상태 |")
    lines.append("|------|------|------|:----:|")
    all_pass = True
    for name, target, actual, passed in checks:
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        lines.append(f"| {name} | {target} | {actual} | {status} |")
    lines.append("")

    # 요약
    avg_time = sum(r["elapsed"] for r in results) / len(results)
    avg_len = sum(r["answer_length"] for r in results) / len(results)
    lines.append("## 요약 통계\n")
    lines.append(f"- 평균 응답 시간: **{avg_time:.1f}초**")
    lines.append(f"- 평균 답변 길이: **{avg_len:.0f}자**")
    lines.append(f"- 계산기 호출: **{sum(1 for r in results if r['has_calc'])}건**\n")

    # 결과 테이블
    lines.append("## 분야별 결과\n")
    lines.append("| # | 분야 | 질문 제목 | 시간 | 길이 | 계산기 | 상태 |")
    lines.append("|:-:|------|----------|:----:|:----:|:-----:|:----:|")
    for r in results:
        calc = "O" if r["has_calc"] else "-"
        status = "OK" if not r["error"] else "ERR"
        title = r["title"][:30] + ("..." if len(r["title"]) > 30 else "")
        lines.append(
            f"| {r['index']} | {r['field'][:10]} | {title} "
            f"| {r['elapsed']}s | {r['answer_length']}자 | {calc} | {status} |"
        )

    # 상세
    lines.append("\n---\n\n## 질문-답변 상세\n")
    for r in results:
        lines.append(f"### {r['index']}. [{r['field']}] {r['title']}\n")
        lines.append(f"**응답시간**: {r['elapsed']}s | **답변길이**: {r['answer_length']}자\n")
        q_text = r["question"][:500] + ("..." if len(r["question"]) > 500 else "")
        lines.append(f"#### 질문\n\n> {q_text}\n")
        lines.append(f"#### 답변\n\n{r['answer']}\n\n---\n")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="네이버 지식iN 테스트")
    parser.add_argument("--all", action="store_true", help="198건 전량 테스트")
    parser.add_argument("--count", type=int, help="테스트할 질문 수")
    parser.add_argument("--field", type=str, help="특정 분야만 테스트")
    args = parser.parse_args()

    with open(INPUT_PATH, encoding="utf-8") as f:
        data = json.load(f)

    questions = select_questions(data, args)
    print(f"\n테스트 대상: {len(questions)}건\n")

    config = AppConfig.from_env()
    results = run_test(questions, config)
    checks = verify_quality(results)

    # 보고서 생성
    report = generate_report(results, checks)
    with open(OUTPUT_MD, "w", encoding="utf-8") as f:
        f.write(report)

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # 결과 출력
    print(f"\n{'='*50}")
    print(f"테스트 완료: {len(results)}건")
    print(f"{'='*50}")
    for name, target, actual, passed in checks:
        icon = "PASS" if passed else "FAIL"
        print(f"  [{icon}] {name}: {actual} (목표: {target})")
    print(f"\n보고서: {OUTPUT_MD}")
    print(f"JSON:   {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
