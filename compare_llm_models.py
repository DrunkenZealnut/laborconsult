#!/usr/bin/env python3
"""
답변 생성 LLM 모델 A/B 비교 — OpenAI o3 vs gpt-5.6-luna

ANSWER_PROVIDER=openai로 고정해 답변 생성을 OpenAI API로 강제한 뒤,
OPENAI_CHAT_MODEL만 바꿔가며 동일 질문 세트를 전체 파이프라인
(intent → RAG → 법령 API → 계산기 → LLM 답변 → 인용 검증)으로 실행한다.

측정: 전체 응답시간 / TTFT / LLM 생성 구간 / 답변 길이 / 실사용 제공자 /
      환각 판례 감지 / LLM-as-Judge 블라인드 채점(Claude Sonnet, 순서 교대)

사용법:
  python3 compare_llm_models.py                       # 기본 10문항
  python3 compare_llm_models.py --limit 3             # 3문항만
  python3 compare_llm_models.py --models o3,gpt-5.6-luna
  python3 compare_llm_models.py --no-judge            # 채점 생략
"""

import argparse
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from dotenv import load_dotenv

# override=True — 셸(.zshrc 등)에 낡은 API 키가 export되어 있어도 .env를 우선한다.
# (override=False면 무효 키로 Claude 호출이 401 → intent 분석·계산기 경로가 조용히 우회됨)
load_dotenv(override=True)

# 답변 생성을 OpenAI API로 강제 (Claude 우선순위 무시)
os.environ["ANSWER_PROVIDER"] = "openai"

RESULTS_FILE = Path(__file__).parent / "compare_llm_models_results.json"
REPORT_FILE = Path(__file__).parent / "compare_llm_models_report.md"
JUDGE_MODEL = "claude-sonnet-5"  # 제3벤더 채점자 — OpenAI 모델 간 비교에 중립

DEFAULT_MODELS = ["o3", "gpt-5.6-luna"]

# test_e2e_20.py에서 경로 다양성(개념/계산기/괴롭힘/판례/법령) 기준으로 선별
TEST_CASES = [
    {"id": 1, "cat": "개념", "q": "주휴수당이 뭔가요?"},
    {"id": 2, "cat": "정보부족", "q": "퇴직금 얼마 받을 수 있나요?"},
    {"id": 3, "cat": "임금계산", "q": "월급 300만원, 주5일 하루 8시간 근무, 주당 연장근로 10시간입니다. 연장수당 얼마인가요?"},
    {"id": 4, "cat": "임금계산", "q": "3년 일하고 월급 250만원인데 퇴직금이 얼마인가요?"},
    {"id": 5, "cat": "해고구제", "q": "회사에서 갑자기 해고당했습니다. 구제신청 어떻게 하나요?"},
    {"id": 6, "cat": "판례", "q": "수습기간인데 본채용 거부당했습니다. 부당해고인가요?"},
    {"id": 7, "cat": "산재", "q": "출퇴근 중 교통사고를 당했는데 산재 처리 가능한가요?"},
    {"id": 8, "cat": "괴롭힘", "q": "상사가 매일 폭언하고 업무에서 배제시킵니다. 직장 내 괴롭힘인가요?"},
    {"id": 9, "cat": "연차", "q": "입사 1년 됐는데 연차가 몇 개 발생하나요?"},
    {"id": 10, "cat": "실업급여", "q": "권고사직 받았는데 실업급여 받을 수 있나요?"},
]


# ── 로그 캡처 (환각 판례 경고 등) ────────────────────────────────────────────

class _WarnCollector(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.records: list[str] = []

    def emit(self, record):
        try:
            self.records.append(record.getMessage())
        except Exception:
            pass

    def reset(self):
        self.records = []


@dataclass
class RunResult:
    case_id: int
    cat: str
    question: str
    model: str
    provider: str | None = None          # 실제 답변한 제공자 (폴백 감지용)
    answer: str = ""
    total_sec: float = 0.0
    ttft_sec: float = 0.0                # 첫 chunk까지
    gen_sec: float = 0.0                 # 첫 chunk ~ 마지막 chunk
    answer_len: int = 0
    n_sources: int = 0
    has_calc: bool = False
    hallucinated: list = field(default_factory=list)
    error: str | None = None


def run_case(case: dict, model: str, config, warn_collector: _WarnCollector) -> RunResult:
    """단일 케이스를 지정 모델로 전체 파이프라인 실행"""
    from app.models.session import Session
    from app.core.pipeline import process_question

    os.environ["OPENAI_CHAT_MODEL"] = model
    warn_collector.reset()

    res = RunResult(case_id=case["id"], cat=case["cat"], question=case["q"], model=model)
    session = Session(id=f"cmp_{model}_{case['id']}")

    t0 = time.perf_counter()
    t_first = None
    t_last = None
    try:
        for event in process_question(case["q"], session, config):
            etype = event.get("type")
            if etype == "status":
                txt = event.get("text", "")
                # "OpenAI로 답변 생성 중..." / "Gemini로 답변 생성 중..."
                if "답변 생성 중" in txt:
                    res.provider = txt.split("로 답변")[0].strip()
            elif etype in ("chunk", "text"):
                if t_first is None:
                    t_first = time.perf_counter()
                t_last = time.perf_counter()
                res.answer += event.get("text", "")
            elif etype == "replace":
                res.answer = event.get("text", res.answer)
            elif etype == "sources":
                res.n_sources = len(event.get("hits", []) or [])
            elif etype == "meta":
                if event.get("calc_result"):
                    res.has_calc = True
            elif etype == "error":
                res.error = event.get("text", "unknown error")
    except Exception as e:  # noqa: BLE001 — 케이스 단위 격리
        res.error = f"{type(e).__name__}: {e}"

    res.total_sec = time.perf_counter() - t0
    if t_first:
        res.ttft_sec = t_first - t0
        res.gen_sec = (t_last or t_first) - t_first
    res.answer_len = len(res.answer)
    # provider status는 Claude일 때 미발행 → 미검출 시 OpenAI(1순위)로 간주
    if res.provider is None and res.answer:
        res.provider = "OpenAI"
    res.hallucinated = [m for m in warn_collector.records if "환각 판례 감지" in m]
    return res


# ── LLM-as-Judge ────────────────────────────────────────────────────────────

JUDGE_PROMPT = """당신은 한국 노동법 전문 노무사이자 AI 답변 평가자입니다.
동일한 상담 질문에 대한 두 AI 답변을 블라인드 평가하세요.

[질문]
{question}

[답변 A]
{answer_a}

[답변 B]
{answer_b}

다음 4개 축을 각각 1~5점으로 채점하세요.
1. legal_accuracy: 법령·요건·수치의 정확성 (근로기준법 조문, 금액, 기준일 등)
2. completeness: 질문이 요구한 내용을 빠짐없이 다뤘는지 (누락 정보 안내 포함)
3. grounding: 근거 제시의 구체성 (조문·판례·행정해석 인용, 출처 없는 단정 여부)
4. readability: 상담 이용자 기준 가독성·구조·실행가능성

반드시 아래 JSON만 출력하세요 (설명 금지):
{{"A": {{"legal_accuracy": n, "completeness": n, "grounding": n, "readability": n}},
 "B": {{"legal_accuracy": n, "completeness": n, "grounding": n, "readability": n}},
 "winner": "A" | "B" | "tie",
 "reason": "80자 이내 한국어 근거"}}"""


def judge_pair(question: str, ans_a: str, ans_b: str, config) -> dict | None:
    """블라인드 A/B 채점. 실패 시 None (비교는 계속 진행)"""
    try:
        msg = config.claude_client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": JUDGE_PROMPT.format(
                question=question, answer_a=ans_a or "(답변 없음)", answer_b=ans_b or "(답변 없음)")}],
        )
        text = "".join(b.text for b in msg.content if b.type == "text").strip()
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < 0:
            return None
        return json.loads(text[start:end + 1])
    except Exception as e:  # noqa: BLE001
        print(f"    [judge 실패] {type(e).__name__}: {str(e)[:120]}")
        return None


AXES = ["legal_accuracy", "completeness", "grounding", "readability"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=len(TEST_CASES))
    ap.add_argument("--models", type=str, default=",".join(DEFAULT_MODELS))
    ap.add_argument("--no-judge", action="store_true")
    args = ap.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    cases = TEST_CASES[:args.limit]

    logging.basicConfig(level=logging.WARNING)
    warn_collector = _WarnCollector()
    logging.getLogger().addHandler(warn_collector)

    from app.config import AppConfig
    config = AppConfig.from_env()

    print(f"비교 대상: {' vs '.join(models)}  |  케이스 {len(cases)}건  |  ANSWER_PROVIDER=openai")
    print(f"RAG(Pinecone): {'활성' if config.pinecone_index else '비활성'}\n")

    runs: dict[int, dict[str, RunResult]] = {}
    for case in cases:
        runs[case["id"]] = {}
        # 캐시 워밍 편향 방지: 케이스마다 모델 실행 순서 교대
        order = models if case["id"] % 2 == 1 else list(reversed(models))
        for model in order:
            print(f"  [{case['id']:>2}/{len(cases)}] {case['cat']:<6} {model:<14} ", end="", flush=True)
            r = run_case(case, model, config, warn_collector)
            runs[case["id"]][model] = r
            flag = ""
            if r.error:
                flag = f" ⚠️ {r.error[:60]}"
            elif r.provider != "OpenAI":
                flag = f" ⚠️ 폴백={r.provider}"
            elif r.hallucinated:
                flag = " ⚠️ 환각판례"
            calc_mark = " 🧮" if r.has_calc else ""
            print(f"{r.total_sec:>6.1f}s (TTFT {r.ttft_sec:>5.1f}s) "
                  f"{r.answer_len:>5}자 src={r.n_sources}{calc_mark}{flag}")

    # ── 채점 ──
    judgments: dict[int, dict] = {}
    if not args.no_judge and len(models) == 2:
        print("\nLLM-as-Judge 채점 중...")
        m1, m2 = models
        for case in cases:
            r1, r2 = runs[case["id"]][m1], runs[case["id"]][m2]
            # 위치 편향 제거: 홀수 케이스는 m1이 A, 짝수 케이스는 m2가 A
            swap = case["id"] % 2 == 0
            a_model, b_model = (m2, m1) if swap else (m1, m2)
            a_ans, b_ans = (r2.answer, r1.answer) if swap else (r1.answer, r2.answer)
            j = judge_pair(case["q"], a_ans, b_ans, config)
            if not j:
                continue
            # A/B 라벨을 모델명으로 환원
            scores = {a_model: j.get("A", {}), b_model: j.get("B", {})}
            winner_label = j.get("winner", "tie")
            winner = {"A": a_model, "B": b_model}.get(winner_label, "tie")
            judgments[case["id"]] = {"scores": scores, "winner": winner,
                                     "reason": j.get("reason", ""), "a_model": a_model}
            print(f"  [{case['id']:>2}] 승자={winner}  {j.get('reason','')[:60]}")

    # ── 집계 ──
    summary = {}
    for m in models:
        rs = [runs[c["id"]][m] for c in cases]
        ok = [r for r in rs if not r.error and r.answer]
        agg = {
            "cases": len(rs),
            "success": len(ok),
            "fallback": sum(1 for r in rs if r.answer and r.provider != "OpenAI"),
            "hallucinated": sum(1 for r in rs if r.hallucinated),
            "avg_total_sec": round(sum(r.total_sec for r in ok) / max(len(ok), 1), 2),
            "avg_ttft_sec": round(sum(r.ttft_sec for r in ok) / max(len(ok), 1), 2),
            "avg_gen_sec": round(sum(r.gen_sec for r in ok) / max(len(ok), 1), 2),
            "avg_len": round(sum(r.answer_len for r in ok) / max(len(ok), 1)),
        }
        if judgments:
            for ax in AXES:
                vals = [j["scores"].get(m, {}).get(ax) for j in judgments.values()]
                vals = [v for v in vals if isinstance(v, (int, float))]
                agg[ax] = round(sum(vals) / len(vals), 2) if vals else None
            axis_means = [agg[ax] for ax in AXES if agg.get(ax) is not None]
            agg["overall"] = round(sum(axis_means) / len(axis_means), 2) if axis_means else None
            agg["wins"] = sum(1 for j in judgments.values() if j["winner"] == m)
        summary[m] = agg

    ties = sum(1 for j in judgments.values() if j["winner"] == "tie")

    payload = {
        "models": models,
        "answer_provider": "openai",
        "n_cases": len(cases),
        "summary": summary,
        "ties": ties,
        "judgments": judgments,
        "runs": {str(cid): {m: asdict(r) for m, r in d.items()} for cid, d in runs.items()},
    }
    RESULTS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── 리포트 ──
    lines = ["# 답변 LLM 모델 비교 — " + " vs ".join(models), ""]
    lines.append(f"- 케이스: {len(cases)}건 (전체 파이프라인, ANSWER_PROVIDER=openai)")
    lines.append(f"- 채점: {JUDGE_MODEL} 블라인드 A/B (케이스별 제시 순서 교대)")
    lines.append("")
    hdr = ["지표"] + models
    rows = [
        ["성공/전체"] + [f"{summary[m]['success']}/{summary[m]['cases']}" for m in models],
        ["폴백 발생"] + [str(summary[m]["fallback"]) for m in models],
        ["환각 판례 감지"] + [str(summary[m]["hallucinated"]) for m in models],
        ["평균 총 응답(s)"] + [str(summary[m]["avg_total_sec"]) for m in models],
        ["평균 TTFT(s)"] + [str(summary[m]["avg_ttft_sec"]) for m in models],
        ["평균 생성구간(s)"] + [str(summary[m]["avg_gen_sec"]) for m in models],
        ["평균 답변 길이(자)"] + [str(summary[m]["avg_len"]) for m in models],
    ]
    if judgments:
        for ax in AXES:
            rows.append([ax] + [str(summary[m].get(ax)) for m in models])
        rows.append(["종합 점수(5점)"] + [str(summary[m].get("overall")) for m in models])
        rows.append(["승수"] + [str(summary[m].get("wins")) for m in models])
        rows.append(["무승부"] + [str(ties)] + [""] * (len(models) - 1))
    lines.append("| " + " | ".join(hdr) + " |")
    lines.append("|" + "---|" * len(hdr))
    for r in rows:
        lines.append("| " + " | ".join(r) + " |")

    lines += ["", "## 케이스별", "", "| # | 분류 | 승자 | 근거 | " +
              " | ".join(f"{m} (s/자)" for m in models) + " |",
              "|---|---|---|---|" + "---|" * len(models)]
    for c in cases:
        j = judgments.get(c["id"], {})
        cells = [f"{runs[c['id']][m].total_sec:.1f} / {runs[c['id']][m].answer_len}" for m in models]
        lines.append(f"| {c['id']} | {c['cat']} | {j.get('winner','-')} | "
                     f"{j.get('reason','-')} | " + " | ".join(cells) + " |")
    REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "\n".join(lines[:6 + len(rows) + 2]))
    print(f"\n결과: {RESULTS_FILE.name} / {REPORT_FILE.name}")


if __name__ == "__main__":
    main()
