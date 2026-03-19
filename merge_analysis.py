#!/usr/bin/env python3
"""
두 분석 결과 JSONL 파일 통합
- analysis_qna.jsonl (최근 10,000건, pages 1~500)
- analysis_qna_2.jsonl (이전 10,000건, pages 501~1000)
→ analysis_qna_all.jsonl (전체 20,000건)

사용법:
  python3 merge_analysis.py
  python3 merge_analysis.py --check  # 현황만 출력
"""

import os
import json
import argparse
from pathlib import Path
from collections import Counter

BASE_DIR = str(Path(__file__).parent)
JSONL_1  = os.path.join(BASE_DIR, "analysis_qna.jsonl")
JSONL_2  = os.path.join(BASE_DIR, "analysis_qna_2.jsonl")
JSONL_ALL = os.path.join(BASE_DIR, "analysis_qna_all.jsonl")


def load_jsonl(path: str) -> list[dict]:
    records = []
    if not os.path.exists(path):
        return records
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def print_stats(label: str, records: list[dict]):
    if not records:
        print(f"  {label}: 0건")
        return
    total = len(records)
    failed = sum(1 for r in records if r.get('question_type') == '분석실패')
    calc_needed = sum(1 for r in records if r.get('requires_calculation') is True)
    qtype_counts = Counter(r.get('question_type', '미분류') for r in records)
    top3 = qtype_counts.most_common(3)
    print(f"  {label}: {total:,}건 | 실패: {failed}건 | 계산필요: {calc_needed:,}건 ({calc_needed/total*100:.1f}%)")
    print(f"    상위 질문유형: " + ", ".join(f"{t}({c})" for t, c in top3))


def main():
    parser = argparse.ArgumentParser(description="분석 결과 통합")
    parser.add_argument('--check', action='store_true', help="현황 확인만 (파일 생성 안 함)")
    args = parser.parse_args()

    records1 = load_jsonl(JSONL_1)
    records2 = load_jsonl(JSONL_2)

    print("=== 분석 결과 통합 현황 ===\n")
    print_stats("최근 10,000건 (p.1~500)",   records1)
    print_stats("이전 10,000건 (p.501~1000)", records2)

    combined = records1 + records2
    print(f"\n통합 레코드: {len(combined):,}건")

    if args.check:
        return

    if not records1 and not records2:
        print("\n[오류] 분석 파일이 없습니다.")
        return

    # 중복 file_id 처리 (file_id + dataset 구분자로 유니크 보장)
    seen = set()
    deduped = []
    for r in records1:
        key = ('1', r.get('file_id', ''))
        if key not in seen:
            seen.add(key)
            r['_dataset'] = '1'  # 메타 필드: 어느 데이터셋인지
            deduped.append(r)
    for r in records2:
        key = ('2', r.get('file_id', ''))
        if key not in seen:
            seen.add(key)
            r['_dataset'] = '2'
            deduped.append(r)

    with open(JSONL_ALL, 'w', encoding='utf-8') as f:
        for r in deduped:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    print(f"\n저장 완료: {JSONL_ALL}")
    print(f"  총 {len(deduped):,}건 (중복 제거 후)")
    print_stats("통합 전체", deduped)
    print(f"\n다음 단계: git add analysis_qna_all.jsonl && git push")


if __name__ == '__main__':
    main()
