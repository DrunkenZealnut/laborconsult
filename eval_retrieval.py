#!/usr/bin/env python3
"""검색 품질 고정 평가 — 해설서 다양성 승격(textbook-retrieval-balance) A/B 비교.

프로덕션 RAG 경로 중 결정적 구간만 재현한다:
  fixture의 [query + decomposed] → search_hybrid → 전체 랭킹(rerank) →
  같은 pool에서 기준선(ranked[:top_n])과 승격(_ensure_textbook_presence)을
  **한 번에 파생** → 각각 format_pinecone_hits

두 모드를 한 pass에서 파생하는 이유: 분기점이 rerank 이후의 결정적 인프로세스
단계라, 실행을 2번 돌리면 외부 API(임베딩·Pinecone·Cohere) 비용이 2배가 되고
두 실행이 서로 다른 pool을 샘플링하는 잡음까지 생긴다 — 같은 pool 파생은
비용 절반에 그 잡음이 원리적으로 없다.

의도적 근사(전부 문서화 — 이 목록 밖의 복제는 드리프트다):
  · analyze_intent 기반 rule 쿼리(build_precedent_queries)는 재현하지 않는다
    — LLM 의도분석이 비결정적이고, 측정 대상(rerank 절단)에 닿는 경로는 동일하다.
  · Self-RAG(COMPLEX)는 돌리지 않는다 — Haiku 판정이 비결정적.
    승격→Self-RAG 상호작용은 프리뷰 실측으로 본다.
  · classify_complexity를 질의 원문만으로 호출한다 — 프로덕션은 의도분석의
    relevant_laws·calculation_types를 함께 넘기므로 같은 질의가 다른 복잡도
    (→다른 top_k/top_n)로 측정될 수 있다.
  · Cohere 무키면 프로덕션은 rerank 호출 자체를 생략한다(절단 없음) — 무키
    측정은 프로덕션이 타지 않는 경로이므로 참고치로만 쓸 것.

결정성 한계: 임베딩·Pinecone ANN·Cohere는 준결정적이다. 판정은 개별 질의가
아니라 집계 지표(도달률·발동률)로 한다. ±1건 수준의 흔들림은 회귀가 아니다.

⚠️ --freeze는 decompose_query(LLM)를 다시 호출해 fixture의 분해 쿼리를
갈아치운다. 재생성하면 기존 기준선 수치와 비교할 수 없다 — 갱신했다면
반드시 재측정해 analysis 기록을 갱신할 것.

사용법:
  python3 eval_retrieval.py --freeze        # 분해 쿼리 1회 고정 (ANTHROPIC 키)
  python3 eval_retrieval.py                 # 기준선·승격 동시 측정
  python3 eval_retrieval.py --out r.json    # 결과 JSON 저장 (로컬 전용, 커밋 금지)

CI에서는 돌지 않는다(API 키 필요) — check_schema.py처럼 수동 실행 항목이다.
"""

from __future__ import annotations

import os
import json
import argparse
from collections import Counter

from dotenv import load_dotenv

# ~/.zshrc의 낡은 키가 .env를 덮은 전력이 있어 override 필수.
load_dotenv(override=True)

FIXTURE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "eval_retrieval_queries.json")


def load_fixture() -> dict:
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def freeze(fixture: dict) -> None:
    """decompose_query를 1회 호출해 분해 쿼리를 fixture에 고정."""
    import datetime
    from app.config import AppConfig
    from app.core.query_decomposer import (
        classify_complexity, decompose_query, COMPLEXITY_PARAMS,
    )

    config = AppConfig.from_env()
    for q in fixture["queries"]:
        params = COMPLEXITY_PARAMS[classify_complexity(q["query"])]
        if params["max_queries"] <= 1:
            q["decomposed"] = []
            print(f"  {q['id']} SIMPLE — 분해 생략")
            continue
        dq = decompose_query(q["query"], config.claude_client,
                             force=params.get("force_decompose", False))
        q["decomposed"] = [x for x in dq if x != q["query"]]
        print(f"  {q['id']} 분해 {len(q['decomposed'])}건")

    fixture["frozen_at"] = datetime.date.today().isoformat()
    with open(FIXTURE_PATH, "w", encoding="utf-8") as f:
        json.dump(fixture, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\nfixture 고정 완료: {FIXTURE_PATH} (frozen_at={fixture['frozen_at']})")


def _final_textbook_count(hits: list[dict]) -> tuple[int, int, list[str]]:
    """가드(format_pinecone_hits) 통과 후 (해설서 수, 총 건수, source_type들)."""
    from app.core.rag import format_pinecone_hits
    _, meta = format_pinecone_hits(hits)
    kinds = [m.get("source_type", "?") for m in meta]
    return sum(1 for k in kinds if k == "textbook"), len(meta), kinds


def run(fixture: dict, out_path: str | None) -> None:
    from app.config import AppConfig
    from app.core.query_decomposer import (
        classify_complexity, COMPLEXITY_PARAMS, QUERY_MERGE_HEADROOM,
    )
    from app.core import rag
    from app.core import bm25_search as bm

    if not fixture.get("frozen_at"):
        raise SystemExit("[오류] fixture가 고정되지 않았습니다 — --freeze를 먼저 실행하세요.")

    config = AppConfig.from_env()
    if not config.cohere_api_key:
        print("⚠️ COHERE_API_KEY 없음 — 프로덕션은 무키면 rerank 절단 자체가 없으므로 "
              "이 측정은 프로덕션이 타지 않는 경로다(참고치로만).")
    # search_hybrid가 내부에서 캐시 로드하지만, 실패는 조용한 Dense-only 폴백이라
    # 측정 도구에서는 미리 진단을 출력한다(캐시라 이중 비용 없음).
    if not bm.load_bm25_corpus():
        print("⚠️ BM25 코퍼스 미적재 — Dense-only로 측정됨(프로덕션과 다를 수 있음)")

    rows = []
    dist_base = Counter()
    dist_promo = Counter()

    print(f"\n{'id':<5} {'expect':<6} {'cx':<9} {'pool_tb':>7} {'base_tb':>7} "
          f"{'promo_tb':>8} {'승격':>4}")
    print("-" * 56)
    for q in fixture["queries"]:
        complexity = classify_complexity(q["query"])
        params = COMPLEXITY_PARAMS[complexity]
        queries = ([q["query"]] + list(q.get("decomposed") or []))[
            : params["max_queries"] + QUERY_MERGE_HEADROOM]

        hits = rag.search_hybrid(queries, config, top_k=params["search_top_k"])
        pool_tb = sum(1 for h in hits if rag._book_id_of(h))
        top_n = params["rerank_top_n"]

        # 전체 랭킹 1회 — 기준선·승격을 같은 pool에서 파생한다(모듈 docstring).
        ranked = rag.rerank_results(q["query"], hits, config.cohere_api_key,
                                    top_n=len(hits), ensure_textbook=False)
        baseline = ranked[:top_n]
        promoted = rag._ensure_textbook_presence(ranked, top_n)
        was_promoted = any(h.get("promoted") for h in promoted)

        base_tb, base_n, base_kinds = _final_textbook_count(baseline)
        promo_tb, promo_n, promo_kinds = _final_textbook_count(promoted)
        dist_base.update(base_kinds)
        dist_promo.update(promo_kinds)

        rows.append({
            "id": q["id"], "expect": q["expect"], "complexity": complexity.value,
            "pool_n": len(hits), "pool_tb": pool_tb,
            "base_rerank_tb": sum(1 for h in baseline if rag._book_id_of(h)),
            "promo_rerank_tb": sum(1 for h in promoted if rag._book_id_of(h)),
            "base_n": base_n, "base_tb": base_tb,
            "promo_n": promo_n, "promo_tb": promo_tb,
            "promoted": was_promoted,
        })
        print(f"{q['id']:<5} {q['expect']:<6} {complexity.value:<9} "
              f"{pool_tb:>4}/{len(hits):<3} {base_tb:>4}/{base_n:<3} "
              f"{promo_tb:>4}/{promo_n:<4} {'★' if was_promoted else '':>3}")

    # ── 집계 (설계 §5.4) ──
    def reach(tb_key: str) -> tuple[int, int, float]:
        denom = [r for r in rows if r["pool_tb"] > 0]
        num = [r for r in denom if r[tb_key] > 0]
        return len(num), len(denom), round(len(num) / len(denom) * 100, 1) if denom else 0.0

    b_num, denom_n, b_rate = reach("base_tb")
    p_num, _, p_rate = reach("promo_tb")
    promotions = sum(1 for r in rows if r["promoted"])
    cap_reduced = {
        "baseline": sum(1 for r in rows if r["base_rerank_tb"] > r["base_tb"]),
        "promote": sum(1 for r in rows if r["promo_rerank_tb"] > r["promo_tb"]),
    }

    summary = {
        "frozen_at": fixture["frozen_at"],
        "queries": len(rows),
        "pool_has_textbook": denom_n,
        "reach": {"baseline": {"n": b_num, "rate_pct": b_rate},
                  "promote": {"n": p_num, "rate_pct": p_rate}},
        "promotions": promotions,
        "promote_rate_pct": round(promotions / len(rows) * 100, 1) if rows else 0.0,
        "cap_reduced_queries": cap_reduced,
        "final_source_dist": {"baseline": dict(dist_base), "promote": dict(dist_promo)},
        "final_total": {"baseline": sum(dist_base.values()),
                        "promote": sum(dist_promo.values())},
        "by_expect": {
            tag: {
                "n": len([r for r in rows if r["expect"] == tag]),
                "pool_tb": len([r for r in rows if r["expect"] == tag and r["pool_tb"] > 0]),
                "base_tb": len([r for r in rows if r["expect"] == tag and r["base_tb"] > 0]),
                "promo_tb": len([r for r in rows if r["expect"] == tag and r["promo_tb"] > 0]),
            }
            # 태그 어휘는 fixture가 단일 출처 — 하드코딩하면 태그 추가 시 조용히 누락된다.
            for tag in sorted({r["expect"] for r in rows})
        },
        "rows": rows,
    }

    print("-" * 56)
    print(f"fixture frozen_at={fixture['frozen_at']}  (분모: pool에 해설서 있던 질의 {denom_n}건)")
    print(f"도달률: 기준선 {b_num}/{denom_n} = {b_rate}%  →  "
          f"승격 {p_num}/{denom_n} = {p_rate}%")
    print(f"승격 발동: {promotions}건 ({summary['promote_rate_pct']}%) "
          f"| 상한(G4/G4-T) 차감 질의: base {cap_reduced['baseline']} / promo {cap_reduced['promote']}")
    print(f"최종 출처 분포(기준선): {dict(dist_base)} (총 {sum(dist_base.values())}건)")
    print(f"최종 출처 분포(승격):   {dict(dist_promo)} (총 {sum(dist_promo.values())}건)")
    for tag, s in summary["by_expect"].items():
        print(f"  {tag:<5} n={s['n']} pool_tb={s['pool_tb']} "
              f"base_tb={s['base_tb']} promo_tb={s['promo_tb']}")

    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"\n결과 저장: {out_path} (로컬 전용 — 커밋하지 말 것)")


def main() -> None:
    parser = argparse.ArgumentParser(description="검색 품질 고정 평가 (기준선·승격 동시)")
    parser.add_argument("--freeze", action="store_true",
                        help="분해 쿼리를 LLM으로 1회 생성해 fixture에 고정")
    parser.add_argument("--out", help="결과 JSON 저장 경로 (로컬 전용)")
    args = parser.parse_args()

    fixture = load_fixture()
    if args.freeze:
        freeze(fixture)
        return
    run(fixture, out_path=args.out)


if __name__ == "__main__":
    main()
