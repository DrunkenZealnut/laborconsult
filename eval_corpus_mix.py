#!/usr/bin/env python3
"""답변 근거 구성 평가 — 공공저작물 / 해설서 / 상담 비율 (legal-corpus-coverage).

`eval_retrieval.py`(해설서 도달률)와 목적이 다르다. 이쪽은 **답변 컨텍스트의
저작권 구성**을 본다 — 공공저작물(판례·행정해석·훈령)을 주 근거로, 타인
저작물(해설서·상담 게시물)을 보조로 되돌리는 것이 이 지표의 목적이다.

평가셋은 `data/eval_corpus_mix.json`(상담 어휘 12주제) 고정. baseline은
2026-08-23 실측이며 **재측정 없이 수정하지 말 것** — 바꾸면 개선폭이 무의미해진다.

사용법:
  python3 eval_corpus_mix.py               # 검색 경로만 (빠름, LLM 답변 없음)
  python3 eval_corpus_mix.py --baseline    # 기준선과 대조 출력
  python3 eval_corpus_mix.py --production  # process_question 전 경로 (느림, 정확)

⚠️ **목표 달성 판정은 `--production`으로 할 것.** 기본 모드는 원문 쿼리 1개를
넘기지만 프로덕션은 의도분석이 만든 분해·규칙 쿼리 목록을 쓴다 — `queries[0]`이
원문이 아니라 규칙 생성 키워드라 공공 쿼터 조회가 다른 쿼리로 나간다.
Self-RAG·wider도 기본 모드에서는 돌지 않는다(Check 리뷰 A-4).
"""
from __future__ import annotations

import os
import sys
import json
import time
import argparse

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)

EVAL_FILE = os.path.join(BASE_DIR, "data", "eval_corpus_mix.json")


def classify(meta: dict) -> str:
    from app.core.rag import POOL_PUBLIC_SOURCES, is_counsel_source

    st = meta.get("source_type")
    if st == "textbook":
        return "textbook"
    if st in POOL_PUBLIC_SOURCES:
        return "public"
    if is_counsel_source(meta):
        return "counsel"
    return "other"



def _measure_production(query: str, config):
    """`process_question`을 그대로 태워 **프로덕션과 같은 쿼리 구성**으로 측정한다.

    검색 경로만 재면 원문 쿼리 1개를 넘기게 되는데, 프로덕션은 의도분석이 만든
    분해·규칙 쿼리 목록을 쓴다(`_merge_search_queries`). 실제 `queries[0]`은
    원문이 아니라 규칙 생성 키워드다 — 공공 쿼터 조회가 그 쿼리로 나가므로
    두 조건의 결과가 다르다(Check 리뷰 A-4). Self-RAG·wider도 이 경로에서만 돈다.

    답변 LLM 호출이 포함되므로 느리고 비용이 든다. 기본값이 아닌 이유다.
    """
    from app.core import rag as _rag
    import app.core.pipeline as P
    from app.models.session import Session

    captured: list[list[dict]] = []
    orig = _rag.format_pinecone_hits

    def spy(hits, top_n=None, max_chars=None):
        text, meta = orig(hits, top_n, max_chars)
        captured.append(meta)
        return text, meta

    _rag.format_pinecone_hits = spy
    P.format_pinecone_hits = spy
    try:
        for _ev in P.process_question(query, Session(id="evalmix00001"), config):
            pass
    except Exception as e:
        print(f"    [실행 실패] {type(e).__name__}: {str(e)[:80]}")
        return None
    finally:
        _rag.format_pinecone_hits = orig
        P.format_pinecone_hits = orig
    # wider 경로에서 여러 번 불릴 수 있다 — 마지막이 실제 답변 컨텍스트다
    return captured[-1] if captured else []


def main() -> None:
    ap = argparse.ArgumentParser(description="답변 근거 구성 평가")
    ap.add_argument("--baseline", action="store_true", help="기준선 대조 출력")
    ap.add_argument("--production", action="store_true",
                    help="process_question을 그대로 태워 측정 (기본은 검색 경로만)")
    args = ap.parse_args()

    with open(EVAL_FILE, encoding="utf-8") as f:
        spec = json.load(f)

    from app.config import AppConfig
    from app.core import rag
    from app.core.query_decomposer import classify_complexity, COMPLEXITY_PARAMS

    config = AppConfig.from_env()
    if not config.pinecone_index:
        sys.exit("[오류] Pinecone 초기화 실패 — 측정 불가")
    cohere_key = os.getenv("COHERE_API_KEY", "")

    totals = {"public": 0, "textbook": 0, "counsel": 0, "other": 0}
    reached = 0
    rows = []
    elapsed: list[float] = []

    for q in spec["queries"]:
        comp = classify_complexity(q["query"])
        params = COMPLEXITY_PARAMS[comp]
        t0 = time.perf_counter()
        if args.production:
            meta = _measure_production(q["query"], config)
            if meta is None:
                print(f"  {q['id']} {q['topic']}: 실행 실패")
                continue
        else:
            # search_hybrid는 쿼리 **리스트**를 받는다 — 문자열을 넘기면 `for q in
            # queries`가 문자 단위로 돌아 한 글자씩 검색하고, queries[0]이 첫 글자가
            # 되어 공공 쿼터 조회까지 엉뚱한 쿼리로 나간다(측정 중 실제로 겪음).
            hits = rag.search_hybrid([q["query"]], config, top_k=params["search_top_k"])
            if not hits:
                print(f"  {q['id']} {q['topic']}: pool 0건")
                continue
            ranked = rag.rerank_results(q["query"], hits, cohere_key,
                                        top_n=params["rerank_top_n"])
            _text, meta = rag.format_pinecone_hits(
                ranked, top_n=params["rerank_top_n"])
        elapsed.append(time.perf_counter() - t0)
        counts = {"public": 0, "textbook": 0, "counsel": 0, "other": 0}
        for m in meta:
            counts[classify(m)] += 1
        for k, v in counts.items():
            totals[k] += v
        if counts["public"]:
            reached += 1
        cur = f"{counts['public']}/{counts['textbook']}/{counts['counsel']}"
        rows.append({"id": q["id"], "topic": q["topic"], "current": cur})
        base = f"  (기준 {q['baseline']})" if args.baseline and q.get("baseline") else ""
        print(f"  {q['id']} {q['topic']:14s} {comp.name:8s} "
              f"공공/해설서/상담 = {cur}{base}")

    n = len(spec["queries"])
    total = sum(totals.values()) or 1
    print("\n" + "=" * 62)
    print(f"공공저작물 {totals['public']}건 | 해설서 {totals['textbook']}건 | "
          f"상담 {totals['counsel']}건 | 계 {total}건")
    print(f"상담 비중 {totals['counsel'] / total * 100:.0f}%  |  "
          f"저작물 비중 {(totals['textbook'] + totals['counsel']) / total * 100:.0f}%")
    print(f"법률 근거 도달: {reached}/{n}")
    if elapsed:
        ordered = sorted(elapsed)
        p50 = ordered[len(ordered) // 2]
        p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
        print(f"지연: p50 {p50:.1f}s | p95 {p95:.1f}s | 최대 {ordered[-1]:.1f}s")

    if args.baseline:
        b = spec["baseline_totals"]
        bt = b["public"] + b["textbook"] + b["counsel"]
        print("\n[기준선 2026-08-23] "
              f"공공 {b['public']} | 해설서 {b['textbook']} | 상담 {b['counsel']} | "
              f"상담비중 {b['counsel'] / bt * 100:.0f}%")
        print(f"[변화]             공공 {b['public']} → {totals['public']} | "
              f"상담비중 {b['counsel'] / bt * 100:.0f}% → "
              f"{totals['counsel'] / total * 100:.0f}%")
    print("=" * 62)


if __name__ == "__main__":
    main()
