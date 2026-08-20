#!/usr/bin/env python3
"""구어체→법률용어 매핑 고정 평가 (colloquial-legal-mapping).

세 층을 각각 측정한다:
  [1] 의도분석(LLM) 변환 — analyze_intent의 precedent_keywords가 fixture의
      expect_terms 개념을 담는가 (정상 경로의 1차 방어선)
  [2] 정적 사전 — map_colloquial_terms가 expect_terms 개념을 담는가
      (의도분석 실패 폴백의 2차 방어선, LLM 무호출)
  [3] 검색 A/B — 폴백 경로(원문+사전, G1 재현) vs 정상 경로(LLM 키워드)의
      법률 코퍼스(판례·행정해석·훈령예규·해설서) 도달. Q&A·상담 코퍼스는
      구어-구어 매칭이 돼 변환 없이도 잡히므로 지표에서 분리한다.

판정은 집계 지표로 한다(개별 질의 ±1건은 회귀가 아니다 — eval_retrieval.py와
같은 원칙). 기준선(2026-08-20, Act 완료 후 측정):
  [1] 의도분석 변환 18/18
  [2] 정적 사전 18/18
  [3] 폴백(사전+원문 병기) 9/18 = 50% — 사전 도입 전 0%
      정상(LLM 키워드) 13~15/18 = 72~83% — 반복 2회의 준결정 밴드(법률근거
      승격 도입 전 50%). c15(4대보험)·c16(근로자성)은 두 측정 모두 0 —
      법률 코퍼스의 주제 커버리지 공백(다음 사이클 후보), 검색 로직 문제 아님.
fixture 갱신 시 이 기준선을 재측정할 것.

사용법:
  python3 eval_colloquial.py             # 전 층 측정 (ANTHROPIC·PINECONE 키)
  python3 eval_colloquial.py --dict-only # [2]만 (API 키 불요 — 오프라인)

CI에서는 돌지 않는다(--dict-only 제외 API 키 필요) — 수동 실행 항목이다.
"""
from __future__ import annotations

import os
import sys
import json
import argparse

from dotenv import load_dotenv

# ~/.zshrc의 낡은 키가 .env를 덮은 전력이 있어 override 필수.
load_dotenv(override=True)

FIXTURE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "eval_colloquial_queries.json")

LEGAL_SOURCES = {"precedent", "interpretation", "regulation", "textbook"}


def load_fixture() -> list[dict]:
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["queries"]


def _hits_any(terms: list[str], expects: list[str]) -> bool:
    """추출 용어들이 기대 개념 중 하나라도 담는가(부분 문자열 양방향)."""
    return any(e in t or t in e for t in terms for e in expects)


def eval_dictionary(queries: list[dict]) -> int:
    from app.core.colloquial_map import map_colloquial_terms

    print("\n=== [2] 정적 사전 (오프라인) ===")
    ok = 0
    for q in queries:
        terms = map_colloquial_terms(q["query"])
        hit = _hits_any(terms, q["expect_terms"])
        ok += hit
        mark = "✅" if hit else "▷"  # 사전은 전 항목 커버가 목표가 아니다(고신뢰만)
        print(f"  {mark} [{q['id']}] {q['query'][:30]} → {terms}")
    print(f"  사전 커버: {ok}/{len(queries)}")
    return ok


def eval_llm_and_search(queries: list[dict]) -> None:
    from app.config import AppConfig
    from app.core.analyzer import analyze_intent
    from app.core.colloquial_map import map_colloquial_terms
    from app.core.precedent_query import build_precedent_queries
    from app.core.query_decomposer import classify_complexity, COMPLEXITY_PARAMS
    from app.core import rag
    from app.core import bm25_search as bm

    config = AppConfig.from_env()
    if not config.cohere_api_key:
        print("⚠️ COHERE_API_KEY 없음 — 프로덕션이 타지 않는 경로(참고치)")
    if not bm.load_bm25_corpus():
        print("⚠️ BM25 미적재 — Dense-only 측정")

    print("\n=== [1] 의도분석 변환 + [3] 검색 A/B ===")
    print(f"{'id':<5} {'LLM변환':>7} {'폴백도달':>8} {'정상도달':>8}  키워드(LLM)")
    print("-" * 90)

    llm_ok = fb_reach = normal_reach = 0
    n = len(queries)
    for q in queries:
        query = q["query"]
        complexity = classify_complexity(query)
        params = COMPLEXITY_PARAMS[complexity]

        def legal_count(search_queries: list[str]) -> int:
            hits = rag.search_hybrid(search_queries, config,
                                     top_k=params["search_top_k"])
            if not hits:
                return 0
            ranked = rag.rerank_results(query, hits, config.cohere_api_key,
                                        top_n=params["rerank_top_n"])
            return sum(1 for h in ranked if h.get("source_type") in LEGAL_SOURCES)

        # [1] 의도분석 변환
        try:
            a = analyze_intent(query, [], config)
            kws = list(getattr(a, "precedent_keywords", []) or [])
        except Exception as e:
            a, kws = None, []
            print(f"  !! [{q['id']}] 의도분석 실패: {e}")
        hit_llm = _hits_any(kws, q["expect_terms"])
        llm_ok += hit_llm

        # [3a] 폴백 경로 재현 — pipeline의 합성 주입과 동일 구성(사전 + 원문 폴백)
        dict_terms = map_colloquial_terms(query)
        fb_queries = ([" ".join(dict_terms[:4])] if dict_terms else []) + [query[:80]]
        fb_n = legal_count(fb_queries)
        fb_reach += fb_n > 0

        # [3b] 정상 경로 — LLM 키워드 rule 쿼리(+요약 폴백)
        prec_queries = []
        if a is not None and kws:
            prec_queries = build_precedent_queries(
                precedent_keywords=kws,
                relevant_laws=getattr(a, "relevant_laws", None) or None,
                consultation_topic=getattr(a, "consultation_topic", None),
            )
        fallback = ((getattr(a, "question_summary", "") or query)[:80]
                    if a else query[:80])
        normal_queries = (prec_queries or []) + [fallback]
        nm_n = legal_count(normal_queries)
        normal_reach += nm_n > 0

        print(f"{q['id']:<5} {'✅' if hit_llm else '❌':>6} "
              f"{fb_n:>7} {nm_n:>8}  {', '.join(kws[:4])[:45]}")

    print("-" * 90)
    print(f"[1] 의도분석 변환 적중: {llm_ok}/{n}")
    print(f"[3] 법률 코퍼스 도달 — 폴백(사전+원문): {fb_reach}/{n}  |  "
          f"정상(LLM 키워드): {normal_reach}/{n}")


def main() -> None:
    parser = argparse.ArgumentParser(description="구어 매핑 고정 평가")
    parser.add_argument("--dict-only", action="store_true",
                        help="정적 사전만 측정 (API 키 불요)")
    args = parser.parse_args()

    queries = load_fixture()
    eval_dictionary(queries)
    if not args.dict_only:
        eval_llm_and_search(queries)


if __name__ == "__main__":
    main()
