#!/usr/bin/env python3
"""
RAG 파이프라인 벤치마크 — 정확도 + 응답시간 측정

output_legal_cases/*.md 114건에 대해:
1. 전체 파이프라인 실행 (intent→RAG→계산기→LLM 답변)
2. LLM-as-Judge로 챗봇 답변 vs 전문가 답변 비교 채점
3. 케이스별 응답시간 프로파일링
4. 카테고리별 집계 + 약점 분석

사용법:
  python3 benchmark_pipeline.py                    # 전체 실행
  python3 benchmark_pipeline.py --limit 10         # 10건만
  python3 benchmark_pipeline.py --skip-to 50       # 50번부터
  python3 benchmark_pipeline.py --dry-run          # 파싱만 (API 미호출)
  python3 benchmark_pipeline.py --category "03"    # Chapter 03만
"""

import json
import re
import sys
import time
import argparse
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── 설정 ──────────────────────────────────────────────────────────────────────
CASE_DIR = Path(__file__).parent / "output_legal_cases"
RESULTS_FILE = Path(__file__).parent / "benchmark_pipeline_results.json"
JUDGE_MODEL = "claude-haiku-4-5-20251001"

# 케이스당 예상 비용 (intent $0.003 + embed $0.001 + LLM $0.05 + judge $0.003)
COST_PER_CASE = 0.055

MAX_RETRIES = 3
RETRY_DELAYS = [5, 15, 30]


# ── 데이터 모델 ──────────────────────────────────────────────────────────────

@dataclass
class ParsedCase:
    case_id: int
    filename: str
    title: str
    chapter: str
    topic: str
    question: str
    expert_answer: str
    related_laws: list = field(default_factory=list)
    has_precedent: bool = False
    has_admin_interp: bool = False


# ── 케이스 파싱 ──────────────────────────────────────────────────────────────

def parse_case_file(filepath: Path) -> ParsedCase | None:
    """마크다운 케이스 파일을 파싱하여 구조화된 데이터로 변환"""
    text = filepath.read_text(encoding="utf-8")

    # 메타데이터 테이블 파싱
    m_id = re.search(r"사례번호\s*\|\s*(\d+)", text)
    if not m_id:
        return None
    case_id = int(m_id.group(1))

    m_ch = re.search(r"챕터\s*\|\s*(.+)", text)
    chapter = m_ch.group(1).strip() if m_ch else ""

    m_tp = re.search(r"주제\s*\|\s*(.+)", text)
    topic = m_tp.group(1).strip() if m_tp else ""

    m_law = re.search(r"관련법령\s*\|\s*(.+)", text)
    related_laws = [s.strip() for s in m_law.group(1).split(",")] if m_law else []

    # 제목 (첫 번째 H1)
    m_title = re.search(r"^#\s+(.+)", text, re.MULTILINE)
    title = m_title.group(1).strip() if m_title else filepath.stem

    # 섹션 분리 — ## 기준
    sections = re.split(r"^##\s+", text, flags=re.MULTILINE)

    question = ""
    answer = ""
    has_precedent = False
    has_admin_interp = False

    for sec in sections:
        sec_lower = sec.strip()
        if sec_lower.startswith("질문"):
            question = sec_lower[2:].strip()
        elif sec_lower.startswith("답변"):
            answer = sec_lower[2:].strip()
        elif sec_lower.startswith("판례"):
            has_precedent = True
        elif sec_lower.startswith("행정해석"):
            has_admin_interp = True

    # 답변이 너무 길면 핵심 부분만 (3000자 제한)
    if len(answer) > 3000:
        answer = answer[:3000] + "..."

    if not question and not answer:
        return None

    return ParsedCase(
        case_id=case_id,
        filename=filepath.name,
        title=title,
        chapter=chapter,
        topic=topic,
        question=question,
        expert_answer=answer,
        related_laws=related_laws,
        has_precedent=has_precedent,
        has_admin_interp=has_admin_interp,
    )


def load_all_cases() -> list[ParsedCase]:
    """모든 케이스 파일 로드 및 정렬"""
    cases = []
    for fp in sorted(CASE_DIR.glob("case_*.md")):
        case = parse_case_file(fp)
        if case:
            cases.append(case)
    return cases


# ── 파이프라인 실행 ──────────────────────────────────────────────────────────

def _phase_ms(phases: dict, start_key: str, *end_keys: str) -> int:
    """단계별 소요 시간 계산 (밀리초)"""
    t_start = phases.get(start_key)
    if t_start is None:
        return 0
    t_end = None
    for ek in end_keys:
        t_end = phases.get(ek)
        if t_end is not None:
            break
    if t_end is None:
        return 0
    return max(0, round((t_end - t_start) * 1000))


def run_single_case(case: ParsedCase, config) -> dict:
    """단일 케이스에 대해 전체 파이프라인 실행 + 타이밍 측정

    추가 정보 요청(follow_up)을 우회하여 항상 답변을 생성하도록 함.
    """
    from app.models.session import Session
    from app.core.pipeline import process_question
    import app.core.pipeline as _pipeline

    # 추가 정보 요청 우회: _compute_missing_info가 항상 빈 리스트 반환
    _orig_compute = _pipeline._compute_missing_info
    _pipeline._compute_missing_info = lambda *args, **kwargs: []

    session = Session(id=f"bench_{case.case_id}")
    t_start = time.perf_counter()
    phases = {}

    chatbot_answer = ""
    calc_result = None
    assessment_result = None
    search_hits = []
    contacts = []
    error = None

    try:
        for event in process_question(case.question, session, config):
            t_now = time.perf_counter()
            etype = event.get("type")

            if etype == "status":
                txt = event.get("text", "")
                if "분석" in txt and "intent_start" not in phases:
                    phases["intent_start"] = t_now
                elif "계산기" in txt or "판정" in txt:
                    phases["calc_start"] = t_now
                elif "검색" in txt:
                    phases["search_start"] = t_now

            elif etype == "meta":
                calc_result = event.get("calc_result")
                assessment_result = event.get("assessment_result")
                phases["calc_end"] = t_now

            elif etype == "sources":
                search_hits = event.get("hits", [])
                phases["search_end"] = t_now

            elif etype == "chunk":
                if "llm_start" not in phases:
                    phases["llm_start"] = t_now
                chatbot_answer += event.get("text", "")

            elif etype == "contacts":
                contacts = event.get("agencies", [])

            elif etype == "follow_up":
                # 추가 질문 요청 — 답변 없이 종료
                chatbot_answer = f"[추가 질문 요청] {event.get('text', '')}"

            elif etype == "done":
                phases["done"] = t_now

            elif etype == "error":
                error = event.get("text", "Unknown error")

    except Exception as e:
        error = str(e)
    finally:
        # monkey-patch 복원
        _pipeline._compute_missing_info = _orig_compute

    t_total = (time.perf_counter() - t_start) * 1000

    timing = {
        "total_ms": round(t_total),
        "intent_ms": _phase_ms(phases, "intent_start", "calc_start", "search_start"),
        "calc_ms": _phase_ms(phases, "calc_start", "calc_end"),
        "search_ms": _phase_ms(phases, "search_start", "search_end"),
        "llm_ms": _phase_ms(phases, "llm_start", "done"),
        "ttft_ms": round((phases.get("llm_start", t_start) - t_start) * 1000),
    }

    return {
        "chatbot_answer": chatbot_answer,
        "calc_result": calc_result,
        "assessment_result": assessment_result,
        "search_hits": search_hits,
        "contacts": contacts,
        "timing": timing,
        "pipeline_error": error,
    }


# ── LLM-as-Judge ─────────────────────────────────────────────────────────────

JUDGE_SYSTEM = """당신은 한국 노동법 전문가이자 답변 품질 평가사입니다.
채팅봇 답변을 전문가 답변과 비교하여 5가지 항목을 0~5점으로 채점하세요.
반드시 유효한 JSON만 출력하세요. 코드블록 없이 순수 JSON만 출력하세요."""

JUDGE_PROMPT = """## 질문
{question}

## 전문가 답변 (정답 기준)
{expert_answer}

## 챗봇 답변 (평가 대상)
{chatbot_answer}

## 채점 기준
1. legal_accuracy (법률 정확성): 인용된 법률·판례가 정확한가? 잘못된 법률 인용이 있는가?
2. completeness (완전성): 전문가 답변의 핵심 포인트가 모두 포함되어 있는가?
3. relevance (관련성): 질문에 정확히 대응하는 답변인가? 불필요한 내용이 없는가?
4. practicality (실용성): 구체적 절차·기관 안내·필요 서류 등 실행 가능한 조언을 포함하는가?
5. calculation_accuracy (계산 정확성): 수치 계산이 필요한 경우 정확한가? 계산이 불필요하면 "N/A"로 표기.

점수 기준:
- 0: 완전히 잘못됨 / 무관한 답변
- 1: 심각한 오류 또는 핵심 누락
- 2: 부분적으로 맞지만 주요 오류 존재
- 3: 대체로 맞지만 세부 사항 부족/오류
- 4: 정확하고 충분하나 약간의 개선 여지
- 5: 전문가 답변 수준과 동등 이상

JSON 형식으로만 출력:
{{"legal_accuracy": 0, "completeness": 0, "relevance": 0, "practicality": 0, "calculation_accuracy": 0, "reasoning": "채점 근거"}}"""


def _extract_scores_regex(raw: str) -> dict | None:
    """JSON 파싱 실패 시 regex로 개별 점수 추출"""
    fields = ["legal_accuracy", "completeness", "relevance", "practicality", "calculation_accuracy"]
    scores = {}
    for f in fields:
        m = re.search(rf'"{f}"\s*:\s*(\d+|"N/A")', raw)
        if m:
            val = m.group(1)
            scores[f] = "N/A" if val == '"N/A"' else int(val)

    m = re.search(r'"reasoning"\s*:\s*"(.*?)(?:"\s*[,}])', raw, re.DOTALL)
    if m:
        scores["reasoning"] = m.group(1).replace('\n', ' ')[:500]

    numeric = [v for v in scores.values() if isinstance(v, (int, float))]
    if len(numeric) < 3:
        return None
    return scores


def _retry_judge(case: ParsedCase, chatbot_answer: str, client) -> dict:
    """파싱 실패 시 1회 재시도 — 더 엄격한 JSON 생성 지시"""
    try:
        resp = client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=512,
            temperature=0.1,
            system=JUDGE_SYSTEM + "\n\nIMPORTANT: Output ONLY a single-line JSON object. No newlines inside string values.",
            messages=[{
                "role": "user",
                "content": JUDGE_PROMPT.format(
                    question=case.question[:1500],
                    expert_answer=case.expert_answer[:1500],
                    chatbot_answer=chatbot_answer[:1500],
                ),
            }],
        )
        raw = resp.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        brace_start = raw.find("{")
        brace_end = raw.rfind("}")
        if brace_start >= 0 and brace_end > brace_start:
            raw = raw[brace_start:brace_end + 1]
        return json.loads(raw)
    except Exception as e:
        return {
            "legal_accuracy": -1, "completeness": -1, "relevance": -1,
            "practicality": -1, "calculation_accuracy": "N/A",
            "overall_score": -1.0,
            "reasoning": f"Judge 파싱 오류 (재시도 실패): {e}",
        }


def judge_answer(case: ParsedCase, chatbot_answer: str, client) -> dict:
    """LLM-as-Judge로 답변 품질 채점"""
    if not chatbot_answer or chatbot_answer.startswith("[추가 질문 요청]"):
        return {
            "legal_accuracy": 0, "completeness": 0, "relevance": 0,
            "practicality": 0, "calculation_accuracy": "N/A",
            "overall_score": 0.0,
            "reasoning": "답변 생성 실패 또는 추가 질문만 반환",
        }

    try:
        resp = client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=1024,
            temperature=0,
            system=JUDGE_SYSTEM,
            messages=[{
                "role": "user",
                "content": JUDGE_PROMPT.format(
                    question=case.question[:2000],
                    expert_answer=case.expert_answer[:2000],
                    chatbot_answer=chatbot_answer[:2000],
                ),
            }],
        )
        raw = resp.content[0].text.strip()

        # 코드블록 제거
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        # JSON 객체 추출 — 첫 번째 { 부터 마지막 } 까지
        brace_start = raw.find("{")
        brace_end = raw.rfind("}")
        if brace_start >= 0 and brace_end > brace_start:
            raw = raw[brace_start:brace_end + 1]

        try:
            scores = json.loads(raw)
        except json.JSONDecodeError:
            # 2단계: reasoning 필드의 줄바꿈 치환
            try:
                raw_fixed = re.sub(r'("reasoning"\s*:\s*")(.*?)(")\s*\}',
                                  lambda m: m.group(1) + m.group(2).replace('\n', ' ').replace('"', '\\"') + m.group(3) + '}',
                                  raw, flags=re.DOTALL)
                scores = json.loads(raw_fixed)
            except json.JSONDecodeError:
                # 3단계: regex로 개별 점수 추출
                scores = _extract_scores_regex(raw)
                if scores is None:
                    # 4단계: 1회 재시도 (temperature=0.1)
                    scores = _retry_judge(case, chatbot_answer, client)
    except Exception as e:
        return {
            "legal_accuracy": -1, "completeness": -1, "relevance": -1,
            "practicality": -1, "calculation_accuracy": "N/A",
            "overall_score": -1.0,
            "reasoning": f"Judge 파싱 오류: {e}",
        }

    # overall_score 계산
    calc_acc = scores.get("calculation_accuracy")
    if calc_acc == "N/A" or calc_acc is None or not isinstance(calc_acc, (int, float)):
        numeric_keys = ["legal_accuracy", "completeness", "relevance", "practicality"]
    else:
        numeric_keys = ["legal_accuracy", "completeness", "relevance", "practicality", "calculation_accuracy"]

    numeric_vals = [scores.get(k, 0) for k in numeric_keys if isinstance(scores.get(k), (int, float))]
    scores["overall_score"] = round(sum(numeric_vals) / max(len(numeric_vals), 1), 2)

    return scores


# ── 집계 ─────────────────────────────────────────────────────────────────────

def aggregate_results(results: list[dict]) -> dict:
    """카테고리별 집계 + 약점 분석"""
    valid = [r for r in results if not r.get("pipeline_error") and r.get("overall_score", -1) >= 0]

    if not valid:
        return {"by_chapter": {}, "by_topic": {}, "weak_areas": [], "overall_avg_score": 0, "overall_avg_time_ms": 0}

    by_chapter = defaultdict(list)
    by_topic = defaultdict(list)

    for r in valid:
        by_chapter[r["chapter"]].append(r)
        by_topic[r["topic"]].append(r)

    def _stats(group: list) -> dict:
        scores = [r["overall_score"] for r in group]
        times = [r["timing"]["total_ms"] for r in group]
        return {
            "count": len(group),
            "avg_score": round(sum(scores) / len(scores), 2),
            "min_score": min(scores),
            "max_score": max(scores),
            "avg_time_ms": round(sum(times) / len(times)),
            "min_time_ms": min(times),
            "max_time_ms": max(times),
        }

    chapter_stats = {ch: _stats(g) for ch, g in sorted(by_chapter.items())}
    topic_stats = {tp: _stats(g) for tp, g in sorted(by_topic.items())}

    all_scores = [r["overall_score"] for r in valid]
    all_times = [r["timing"]["total_ms"] for r in valid]

    weak_areas = [
        {"topic": tp, "avg_score": s["avg_score"], "count": s["count"],
         "recommendation": f"{tp} 관련 RAG 데이터 보강 또는 프롬프트 개선 필요"}
        for tp, s in topic_stats.items()
        if s["avg_score"] < 3.0 and s["count"] >= 2
    ]

    return {
        "overall_avg_score": round(sum(all_scores) / len(all_scores), 2),
        "overall_avg_time_ms": round(sum(all_times) / len(all_times)),
        "by_chapter": chapter_stats,
        "by_topic": topic_stats,
        "weak_areas": sorted(weak_areas, key=lambda x: x["avg_score"]),
    }


# ── 저장/로드 ────────────────────────────────────────────────────────────────

def load_existing_results(path: Path = RESULTS_FILE) -> dict:
    """기존 결과 로드 (resume 지원)"""
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"run_metadata": {}, "summary": {}, "results": []}


def save_results(results: list[dict], path: Path = RESULTS_FILE):
    """중간 결과 저장"""
    data = {
        "run_metadata": {
            "date": datetime.now().isoformat(),
            "completed": len([r for r in results if not r.get("pipeline_error")]),
            "errors": len([r for r in results if r.get("pipeline_error")]),
            "total_cases": len(results),
        },
        "results": results,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def save_final_report(results: list[dict], summary: dict, path: Path = RESULTS_FILE):
    """최종 리포트 저장"""
    data = {
        "run_metadata": {
            "date": datetime.now().isoformat(),
            "completed": len([r for r in results if not r.get("pipeline_error")]),
            "errors": len([r for r in results if r.get("pipeline_error")]),
            "total_cases": len(results),
            "pipeline_model": "claude-sonnet-4-6",
            "judge_model": JUDGE_MODEL,
        },
        "summary": summary,
        "results": results,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Console 출력 ─────────────────────────────────────────────────────────────

def print_summary(summary: dict, results: list[dict]):
    """최종 요약 출력"""
    n_errors = len([r for r in results if r.get("pipeline_error")])
    n_ok = len(results) - n_errors

    print("\n" + "=" * 60)
    print("벤치마크 결과 요약")
    print("=" * 60)
    print(f"전체 평균 점수: {summary['overall_avg_score']:.2f} / 5.0")
    print(f"전체 평균 시간: {summary['overall_avg_time_ms'] / 1000:.1f}초")
    print(f"완료: {n_ok}건 | 에러: {n_errors}건")

    print("\n── 챕터별 ──")
    for ch, s in summary.get("by_chapter", {}).items():
        print(f"  {ch:<40s} ({s['count']:>3d}건): {s['avg_score']:.1f}점 | {s['avg_time_ms']/1000:.1f}초")

    print("\n── 주제별 ──")
    for tp, s in summary.get("by_topic", {}).items():
        print(f"  {tp:<40s} ({s['count']:>3d}건): {s['avg_score']:.1f}점 | {s['avg_time_ms']/1000:.1f}초")

    weak = summary.get("weak_areas", [])
    if weak:
        print("\n── 약점 영역 (3.0 미만) ──")
        for w in weak:
            print(f"  ⚠️  {w['topic']}: {w['avg_score']:.1f}점 → {w['recommendation']}")

    print(f"\n결과 저장: {RESULTS_FILE}")
    print("=" * 60)


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="RAG 파이프라인 벤치마크 — 정확도 + 응답시간 측정")
    parser.add_argument("--limit", type=int, help="최대 실행 건수")
    parser.add_argument("--skip-to", type=int, default=1, help="이 케이스 번호부터 실행")
    parser.add_argument("--category", type=str, help="특정 챕터만 (예: '03')")
    parser.add_argument("--dry-run", action="store_true", help="파싱만 실행, API 미호출")
    parser.add_argument("--delay", type=float, default=1.5, help="케이스 간 딜레이(초)")
    parser.add_argument("--output", type=str, help="결과 파일 경로")
    args = parser.parse_args()

    if args.output:
        global RESULTS_FILE
        RESULTS_FILE = Path(args.output)

    # 케이스 로드
    all_cases = load_all_cases()
    print(f"로드된 케이스: {len(all_cases)}건 (전체 파일 중 파싱 성공)")

    # 필터링
    cases = all_cases
    if args.skip_to > 1:
        cases = [c for c in cases if c.case_id >= args.skip_to]
    if args.category:
        cases = [c for c in cases if args.category in c.chapter]
    if args.limit:
        cases = cases[:args.limit]

    # 비용/시간 예측
    est_cost = len(cases) * COST_PER_CASE
    est_min = len(cases) * 25 / 60
    print(f"실행 대상: {len(cases)}건 | 예상 비용: ~${est_cost:.2f} | 예상 시간: ~{est_min:.0f}분")

    if args.dry_run:
        print("\n── Dry Run: 케이스 목록 ──")
        for c in cases:
            q_preview = c.question[:50].replace("\n", " ") if c.question else "(질문 없음)"
            has_ans = "답변 있음" if c.expert_answer else "답변 없음"
            print(f"  #{c.case_id:>3d}: {c.title[:40]:<40s} | {c.topic[:20]:<20s} | {has_ans}")
        print(f"\n질문 있는 케이스: {len([c for c in cases if c.question])}건")
        print(f"답변 있는 케이스: {len([c for c in cases if c.expert_answer])}건")
        return

    # API 초기화
    from app.config import AppConfig
    config = AppConfig.from_env()

    # 기존 결과 로드 (resume)
    existing = load_existing_results()
    results = existing.get("results", [])
    done_ids = {r["case_id"] for r in results}

    total = len(cases)
    t_run_start = time.time()

    for i, case in enumerate(cases):
        if case.case_id in done_ids:
            print(f"[{i+1:>3d}/{total}] #{case.case_id}: (이미 완료, skip)")
            continue

        if not case.question:
            print(f"[{i+1:>3d}/{total}] #{case.case_id}: (질문 없음, skip)")
            continue

        label = case.title[:35] if len(case.title) <= 35 else case.title[:32] + "..."
        print(f"[{i+1:>3d}/{total}] #{case.case_id}: {label}...", end=" ", flush=True)

        # 파이프라인 실행 (retry 포함)
        pipeline_result = None
        for attempt in range(MAX_RETRIES):
            try:
                pipeline_result = run_single_case(case, config)
                break
            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_DELAYS[attempt]
                    print(f"\n  ⚠️  오류, {wait}초 후 재시도: {e}")
                    time.sleep(wait)
                else:
                    pipeline_result = {
                        "chatbot_answer": "",
                        "calc_result": None,
                        "assessment_result": None,
                        "search_hits": [],
                        "contacts": [],
                        "timing": {"total_ms": 0, "intent_ms": 0, "calc_ms": 0,
                                   "search_ms": 0, "llm_ms": 0, "ttft_ms": 0},
                        "pipeline_error": f"Max retries exceeded: {e}",
                    }

        # Judge 채점
        if pipeline_result.get("pipeline_error"):
            scores = {
                "overall_score": 0.0,
                "reasoning": f"Pipeline error: {pipeline_result['pipeline_error']}",
            }
        else:
            for attempt in range(MAX_RETRIES):
                try:
                    scores = judge_answer(case, pipeline_result["chatbot_answer"], config.claude_client)
                    break
                except Exception as e:
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(RETRY_DELAYS[attempt])
                    else:
                        scores = {"overall_score": -1.0, "reasoning": f"Judge error: {e}"}

        # 결과 조립
        result_dict = {
            "case_id": case.case_id,
            "filename": case.filename,
            "chapter": case.chapter,
            "topic": case.topic,
            "chatbot_answer": pipeline_result["chatbot_answer"][:3000],
            "expert_answer": case.expert_answer[:2000],
            "calc_result": pipeline_result.get("calc_result"),
            "search_hits": pipeline_result.get("search_hits", []),
            "timing": pipeline_result["timing"],
            "pipeline_error": pipeline_result.get("pipeline_error"),
            **scores,
        }
        results.append(result_dict)

        # 즉시 저장
        save_results(results)

        # 진행 상황 출력
        score = scores.get("overall_score", 0)
        time_s = pipeline_result["timing"]["total_ms"] / 1000
        calc_tag = " [CALC]" if pipeline_result.get("calc_result") else ""
        err_tag = " [ERR]" if pipeline_result.get("pipeline_error") else ""
        print(f"score={score:.1f}  time={time_s:.1f}s{calc_tag}{err_tag}")

        time.sleep(args.delay)

    # 최종 집계
    elapsed = time.time() - t_run_start
    print(f"\n전체 소요 시간: {elapsed / 60:.1f}분")

    summary = aggregate_results(results)
    save_final_report(results, summary)
    print_summary(summary, results)


if __name__ == "__main__":
    main()
