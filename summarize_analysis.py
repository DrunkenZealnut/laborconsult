#!/usr/bin/env python3
"""
Q&A 분석 결과 집계 & 계산기 설계 문서 생성

입력:  analysis_qna.jsonl
출력:
  - question_type_stats.json   — 질문 유형별 빈도/비율
  - info_fields_by_type.json   — 유형별 제공 정보 필드 빈도
  - calculator_design.md       — 계산기 설계 문서

사용법:
  python3 summarize_analysis.py
"""

import json
import os
from pathlib import Path
from collections import Counter, defaultdict

_PROJECT_DIR = Path(__file__).parent
INPUT_JSONL     = str(_PROJECT_DIR / "analysis_qna.jsonl")
OUT_TYPE_STATS  = str(_PROJECT_DIR / "question_type_stats.json")
OUT_FIELDS      = str(_PROJECT_DIR / "info_fields_by_type.json")
OUT_DESIGN_MD   = str(_PROJECT_DIR / "calculator_design.md")

# 계산기 설계 상세 정보 (예상 + 분석 기반)
CALCULATOR_SPECS = {
    "퇴직금": {
        "desc": "법정 퇴직금(평균임금 × 30일 × 재직일수/365) 계산",
        "inputs": ["입사일", "퇴직일", "최근 3개월 총 임금", "퇴직사유"],
        "outputs": ["법정 퇴직금액", "평균임금", "재직기간"],
        "law": "근로자퇴직급여 보장법 제8조",
    },
    "연차수당": {
        "desc": "미사용 연차 발생 일수 및 연차수당 계산",
        "inputs": ["입사일", "기준일", "연간 소정근로일수", "출근율", "사용 연차 일수", "통상임금"],
        "outputs": ["발생 연차", "사용 연차", "잔여/미사용 연차", "미사용 연차수당"],
        "law": "근로기준법 제60조",
    },
    "연장수당": {
        "desc": "연장·야간·휴일 근로에 대한 가산 수당 계산",
        "inputs": ["통상임금(시급)", "연장근로시간", "야간근로시간", "휴일근로시간"],
        "outputs": ["연장근로수당(1.5배)", "야간근로수당(0.5배 추가)", "휴일근로수당(1.5배)", "총 수당"],
        "law": "근로기준법 제56조",
    },
    "주휴수당": {
        "desc": "주 소정근로 개근 시 발생하는 유급 주휴일 수당 계산",
        "inputs": ["1주 소정근로시간", "시급"],
        "outputs": ["주휴수당 금액", "주휴일 시간"],
        "law": "근로기준법 제55조",
    },
    "최저임금": {
        "desc": "최저임금 충족 여부 및 차액 계산",
        "inputs": ["지급 시급 또는 월급", "소정근로시간(월)", "적용 연도"],
        "outputs": ["최저임금 충족 여부", "시급 환산", "차액(미달 시)"],
        "law": "최저임금법 제6조",
    },
    "해고예고수당": {
        "desc": "30일 전 예고 없이 해고 시 지급할 해고예고수당 계산",
        "inputs": ["통상임금(일급 또는 시급/근로시간)", "예고일수"],
        "outputs": ["해고예고수당(최대 30일분)"],
        "law": "근로기준법 제26조",
    },
    "실업급여": {
        "desc": "구직급여(실업급여) 수급 자격 및 지급액·기간 계산",
        "inputs": ["피보험 기간", "나이", "이직사유", "일평균임금", "신청일"],
        "outputs": ["수급 자격 여부", "1일 구직급여액(60%)", "소정급여일수", "총 지급 예상액"],
        "law": "고용보험법 제45조~제50조",
    },
    "육아휴직급여": {
        "desc": "육아휴직 기간 중 고용보험 육아휴직급여 계산",
        "inputs": ["통상임금", "육아휴직 기간", "자녀 수", "배우자 육아휴직 여부"],
        "outputs": ["육아휴직급여(첫 3개월 80%, 이후 50%)", "상한/하한 적용 금액"],
        "law": "고용보험법 제70조",
    },
}

# 질문 유형 → 계산기 매핑
TYPE_TO_CALC = {
    "퇴직금":     "퇴직금",
    "연차":       "연차수당",
    "임금":       "연장수당",
    "주휴수당":   "주휴수당",
    "최저임금":   "최저임금",
    "해고":       "해고예고수당",
    "실업급여":   "실업급여",
    "육아휴직":   "육아휴직급여",
}


def load_jsonl(path: str) -> list[dict]:
    records = []
    if not os.path.exists(path):
        print(f"[오류] 파일 없음: {path}")
        print("  먼저 analyze_qna.py를 실행하세요.")
        return records

    with open(path, 'r', encoding='utf-8') as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"  [경고] 라인 {lineno} 파싱 실패: {e}")

    return records


def compute_type_stats(records: list[dict]) -> dict:
    """질문 유형별 통계 계산"""
    total = len(records)
    type_counter = Counter()
    calc_counter = Counter()
    sub_type_by_type = defaultdict(Counter)
    requires_calc_by_type = defaultdict(int)

    for r in records:
        qtype = r.get('question_type', '기타')
        sub = r.get('sub_type', '')
        calc = r.get('calculation_type', '해당없음')
        req_calc = r.get('requires_calculation', False)

        type_counter[qtype] += 1
        if sub:
            sub_type_by_type[qtype][sub] += 1
        calc_counter[calc] += 1
        if req_calc:
            requires_calc_by_type[qtype] += 1

    # 계산 필요 비율
    calc_required_total = sum(1 for r in records if r.get('requires_calculation', False))

    stats = {
        "total": total,
        "requires_calculation_count": calc_required_total,
        "requires_calculation_ratio": round(calc_required_total / total * 100, 1) if total else 0,
        "by_type": {},
        "by_calculation_type": {},
    }

    for qtype, count in type_counter.most_common():
        top_subs = sub_type_by_type[qtype].most_common(5)
        stats["by_type"][qtype] = {
            "count": count,
            "ratio": round(count / total * 100, 1) if total else 0,
            "requires_calculation_count": requires_calc_by_type[qtype],
            "top_sub_types": [{"sub_type": s, "count": c} for s, c in top_subs],
        }

    for calc_type, count in calc_counter.most_common():
        if calc_type == '해당없음':
            continue
        stats["by_calculation_type"][calc_type] = {
            "count": count,
            "ratio": round(count / total * 100, 1) if total else 0,
        }

    return stats


def compute_field_stats(records: list[dict]) -> dict:
    """유형별 제공 정보 필드 빈도 계산"""
    field_counter_by_type = defaultdict(Counter)
    type_count = Counter()
    missing_by_type = defaultdict(Counter)

    for r in records:
        qtype = r.get('question_type', '기타')
        type_count[qtype] += 1

        provided = r.get('provided_info', {})
        if isinstance(provided, dict):
            for field, value in provided.items():
                if value and value != 'null' and value is not None:
                    field_counter_by_type[qtype][field] += 1

        missing = r.get('missing_info', [])
        if isinstance(missing, list):
            for item in missing:
                if item:
                    missing_by_type[qtype][item] += 1

    result = {}
    for qtype in type_count:
        n = type_count[qtype]
        field_stats = {}
        for field, cnt in field_counter_by_type[qtype].most_common():
            field_stats[field] = {
                "count": cnt,
                "ratio": round(cnt / n * 100, 1),
            }
        missing_stats = {}
        for field, cnt in missing_by_type[qtype].most_common(10):
            missing_stats[field] = {
                "count": cnt,
                "ratio": round(cnt / n * 100, 1),
            }
        result[qtype] = {
            "total": n,
            "provided_fields": field_stats,
            "frequently_missing": missing_stats,
        }

    return result


def build_calculator_design_md(type_stats: dict, field_stats: dict) -> str:
    """계산기 설계 문서 생성"""
    lines = [
        "# 노동OK 계산기 설계 문서",
        "",
        "> **기반 데이터**: nodong.kr/qna Q&A 분석 결과",
        f"> **분석 건수**: {type_stats.get('total', 0):,}건",
        f"> **계산 필요 비율**: {type_stats.get('requires_calculation_ratio', 0)}%",
        "",
        "---",
        "",
        "## 1. 질문 유형 분포",
        "",
        "| 유형 | 건수 | 비율 | 계산 필요 |",
        "| --- | ---: | ---: | ---: |",
    ]

    for qtype, info in type_stats.get("by_type", {}).items():
        calc_cnt = info.get("requires_calculation_count", 0)
        lines.append(
            f"| {qtype} | {info['count']:,} | {info['ratio']}% | {calc_cnt:,}건 |"
        )

    lines += [
        "",
        "---",
        "",
        "## 2. 계산기 유형별 수요",
        "",
        "| 계산기 | 건수 | 비율 |",
        "| --- | ---: | ---: |",
    ]

    for calc_type, info in type_stats.get("by_calculation_type", {}).items():
        lines.append(f"| {calc_type} | {info['count']:,} | {info['ratio']}% |")

    lines += [
        "",
        "---",
        "",
        "## 3. 계산기별 설계 명세",
        "",
    ]

    # 계산기 빈도 기반 정렬
    calc_freq = type_stats.get("by_calculation_type", {})
    sorted_calcs = sorted(
        CALCULATOR_SPECS.keys(),
        key=lambda k: calc_freq.get(k, {}).get("count", 0),
        reverse=True,
    )

    for i, calc_name in enumerate(sorted_calcs, 1):
        spec = CALCULATOR_SPECS[calc_name]
        freq_info = calc_freq.get(calc_name, {})
        count = freq_info.get("count", 0)
        ratio = freq_info.get("ratio", 0)

        lines += [
            f"### {i}. {calc_name} 계산기",
            "",
            f"**수요**: {count:,}건 ({ratio}%)  ",
            f"**설명**: {spec['desc']}  ",
            f"**관련법**: {spec['law']}",
            "",
            "**필수 입력값**:",
        ]
        for inp in spec["inputs"]:
            lines.append(f"- {inp}")

        lines += ["", "**출력값**:"]
        for out in spec["outputs"]:
            lines.append(f"- {out}")

        # 실제 분석에서 자주 제공되는 필드 추가
        related_types = [t for t, c in TYPE_TO_CALC.items() if c == calc_name]
        provided_fields = Counter()
        for rt in related_types:
            if rt in field_stats:
                for field, info in field_stats[rt]["provided_fields"].items():
                    provided_fields[field] += info["count"]

        if provided_fields:
            lines += ["", "**사용자가 자주 제공하는 정보** (분석 기반):"]
            for field, cnt in provided_fields.most_common(8):
                lines.append(f"- {field} ({cnt:,}건)")

        lines += ["", "---", ""]

    # 우선순위 요약
    lines += [
        "## 4. 구현 우선순위",
        "",
        "분석 데이터 기반 우선순위 (수요 빈도 순):",
        "",
    ]

    priority_list = sorted(
        [(k, calc_freq.get(k, {}).get("count", 0)) for k in CALCULATOR_SPECS],
        key=lambda x: x[1],
        reverse=True,
    )

    for rank, (name, count) in enumerate(priority_list, 1):
        lines.append(f"{rank}. **{name}** — {count:,}건")

    lines += [
        "",
        "---",
        "",
        "## 5. 공통 설계 원칙",
        "",
        "- **법정 기준 준수**: 최신 근로기준법, 최저임금법 등 반영",
        "- **연도별 기준**: 최저임금, 고용보험료율 등 연도별 자동 적용",
        "- **경계 조건 처리**: 수습기간 제외, 5인 미만 사업장 예외 등",
        "- **단계별 입력**: 필수 → 선택 순서로 사용자 친화적 UX",
        "- **계산 근거 표시**: 계산식과 법적 근거를 결과와 함께 표시",
        "- **면책 고지**: 참고용 계산이며 법적 효력 없음을 명시",
        "",
    ]

    return "\n".join(lines)


def main():
    print("=== Q&A 분석 결과 집계 시작 ===\n")

    records = load_jsonl(INPUT_JSONL)
    if not records:
        return

    print(f"로드된 레코드: {len(records):,}건\n")

    # 1. 질문 유형 통계
    print("질문 유형 통계 계산 중...")
    type_stats = compute_type_stats(records)

    with open(OUT_TYPE_STATS, 'w', encoding='utf-8') as f:
        json.dump(type_stats, f, ensure_ascii=False, indent=2)
    print(f"  → 저장: {OUT_TYPE_STATS}")

    # 상위 10개 유형 미리보기
    print("\n  [상위 질문 유형]")
    for qtype, info in list(type_stats["by_type"].items())[:10]:
        print(f"  {qtype:15s} {info['count']:5,}건 ({info['ratio']}%)")

    # 2. 유형별 제공 정보 필드 빈도
    print("\n유형별 필드 빈도 계산 중...")
    field_stats = compute_field_stats(records)

    with open(OUT_FIELDS, 'w', encoding='utf-8') as f:
        json.dump(field_stats, f, ensure_ascii=False, indent=2)
    print(f"  → 저장: {OUT_FIELDS}")

    # 3. 계산기 설계 문서
    print("\n계산기 설계 문서 생성 중...")
    design_md = build_calculator_design_md(type_stats, field_stats)

    with open(OUT_DESIGN_MD, 'w', encoding='utf-8') as f:
        f.write(design_md)
    print(f"  → 저장: {OUT_DESIGN_MD}")

    print(f"\n=== 완료 ===")
    print(f"총 분석 건수:          {type_stats['total']:,}건")
    print(f"계산 필요 건수:        {type_stats['requires_calculation_count']:,}건 "
          f"({type_stats['requires_calculation_ratio']}%)")

    print("\n[계산기 수요 (상위 5개)]")
    for calc_type, info in list(type_stats["by_calculation_type"].items())[:5]:
        print(f"  {calc_type:15s} {info['count']:5,}건 ({info['ratio']}%)")

    print(f"\n생성 파일:")
    print(f"  {OUT_TYPE_STATS}")
    print(f"  {OUT_FIELDS}")
    print(f"  {OUT_DESIGN_MD}")


if __name__ == '__main__':
    main()
