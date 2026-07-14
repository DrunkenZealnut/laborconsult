#!/usr/bin/env python3
"""Pinecone 네임스페이스 검색 품질 비교 (수동 도구 — 라이브 API 키 필요)

프로덕션 검색 네임스페이스(app/core/rag.py NS_GROUPS)를 기준으로 N개
네임스페이스의 검색 품질을 비교한다. (과거 laborlaw vs laborlaw-v2
2원 비교에서, 프로덕션 실제 조합인 laborlaw-v2/counsel/qa 다원 비교로 전환)

사용법:
  python3 search_quality_test.py
"""

import os
import json
from dotenv import load_dotenv
from openai import OpenAI
from pinecone import Pinecone

load_dotenv()

# ── 설정 ──────────────────────────────────────────────────────────────────────
from app.config import resolve_index_name
PINECONE_INDEX = resolve_index_name()
EMBED_MODEL = "text-embedding-3-small"
from app.core.rag import NS_GROUP_LAW, NS_GROUP_COUNSEL
NAMESPACES = NS_GROUP_LAW + NS_GROUP_COUNSEL  # 프로덕션과 동일 대상 (TEST-3)
TOP_K = 5

# ── 테스트 쿼리 ──────────────────────────────────────────────────────────────
TEST_QUERIES = [
    # 법령정보 (법조문 키워드)
    {"query": "근로기준법 제56조 연장근로 가산수당", "category": "법령"},
    {"query": "근로기준법 제26조 해고예고수당 30일분 통상임금", "category": "법령"},
    {"query": "근로기준법 제60조 연차유급휴가 발생요건", "category": "법령"},
    {"query": "최저임금법 제6조 최저임금 산입범위", "category": "법령"},

    # 판례 (대법원 판결)
    {"query": "대법원 2023다302838 통상임금 정기상여금 포함", "category": "판례"},
    {"query": "대법원 판결 해고 정당한 이유 부당해고", "category": "판례"},
    {"query": "근로자성 판단 기준 사용종속관계", "category": "판례"},
    {"query": "포괄임금제 유효성 판단 기준", "category": "판례"},

    # 행정해석 (고용노동부 행정해석)
    {"query": "5인 미만 사업장 근로기준법 적용범위", "category": "행정해석"},
    {"query": "주 52시간 상한 특별연장근로 인가", "category": "행정해석"},
    {"query": "퇴직금 중간정산 사유 제한", "category": "행정해석"},
    {"query": "연차유급휴가 미사용수당 산정 방법", "category": "행정해석"},

    # 복합 질의 (실제 사용자 질문 형태)
    {"query": "월급 250만원 받는 근로자 연장근로수당 계산 방법", "category": "복합"},
    {"query": "1년 미만 근로자 퇴직금 받을 수 있나요", "category": "복합"},
    {"query": "야간근로수당 계산 시 통상임금에 포함되는 수당", "category": "복합"},
    {"query": "직장내 괴롭힘 신고 절차와 사업주 의무", "category": "복합"},
]


def embed_query(query: str, client: OpenAI) -> list[float]:
    resp = client.embeddings.create(model=EMBED_MODEL, input=[query])
    return resp.data[0].embedding


def search_namespace(index, vector: list[float], namespace: str) -> list[dict]:
    results = index.query(
        vector=vector,
        top_k=TOP_K,
        include_metadata=True,
        namespace=namespace,
    )
    hits = []
    for match in results.matches:
        md = match.metadata or {}
        hits.append({
            "score": round(match.score, 4),
            "title": md.get("document_title", md.get("title", "")),
            "section": md.get("section_title", md.get("section", "")),
            "content_preview": (md.get("content", md.get("chunk_text", "")))[:200],
            "source_type": md.get("source_type", md.get("source_collection", "")),
            "contextualized": md.get("contextualized", False),
        })
    return hits


def main():
    openai_key = os.getenv("OPENAI_API_KEY")
    pinecone_key = os.getenv("PINECONE_API_KEY")

    if not openai_key or not pinecone_key:
        print("[오류] OPENAI_API_KEY 또는 PINECONE_API_KEY가 설정되지 않았습니다.")
        return

    openai_client = OpenAI(api_key=openai_key)
    pc = Pinecone(api_key=pinecone_key)
    index = pc.Index(PINECONE_INDEX)

    # 인덱스 통계 출력
    stats = index.describe_index_stats()
    print("=" * 70)
    print("Pinecone 인덱스 통계")
    print("=" * 70)
    print(f"  인덱스: {PINECONE_INDEX}")
    print(f"  총 벡터: {stats.total_vector_count:,}개")
    if hasattr(stats, "namespaces"):
        for ns_name, ns_info in stats.namespaces.items():
            print(f"  namespace='{ns_name}': {ns_info.vector_count:,}개")
    print()

    # 검색 테스트 실행
    all_results = []
    category_scores = {cat: {ns: [] for ns in NAMESPACES} for cat in ["법령", "판례", "행정해석", "복합"]}

    print("=" * 70)
    print(f"검색 품질 비교 테스트: {' vs '.join(NAMESPACES)}")
    print("=" * 70)

    for i, test in enumerate(TEST_QUERIES, 1):
        query = test["query"]
        category = test["category"]

        print(f"\n{'─' * 70}")
        print(f"[{i}/{len(TEST_QUERIES)}] [{category}] {query}")
        print(f"{'─' * 70}")

        vector = embed_query(query, openai_client)

        result_entry = {"query": query, "category": category}

        for ns in NAMESPACES:
            hits = search_namespace(index, vector, ns)
            result_entry[ns] = hits

            avg_score = sum(h["score"] for h in hits) / len(hits) if hits else 0
            top_score = hits[0]["score"] if hits else 0
            category_scores[category][ns].append(top_score)

            print(f"\n  [{ns}] 결과 {len(hits)}건 (Top1: {top_score:.4f}, Avg: {avg_score:.4f})")
            for j, hit in enumerate(hits, 1):
                title_short = hit["title"][:45] if hit["title"] else "(제목없음)"
                src = hit["source_type"][:15] if hit["source_type"] else ""
                ctx_mark = " [CTX]" if hit["contextualized"] else ""
                print(f"    {j}. [{hit['score']:.4f}] {title_short} ({src}){ctx_mark}")
                if hit["content_preview"]:
                    preview = hit["content_preview"][:100].replace("\n", " ")
                    print(f"       → {preview}...")

        all_results.append(result_entry)

    # ── 종합 통계 ──────────────────────────────────────────────────────────────
    print(f"\n\n{'=' * 70}")
    print("종합 비교 분석")
    print("=" * 70)

    # 카테고리별 평균 Top1 점수 (N개 네임스페이스 일반화)
    col_w = max(12, max(len(ns) for ns in NAMESPACES) + 2)
    print("\n카테고리별 Top-1 평균 점수:")
    header = f"  {'카테고리':<10}" + "".join(f"{ns:>{col_w}}" for ns in NAMESPACES) + f"{'최고':>{col_w}}"
    print(header)
    print(f"  {'─' * (10 + col_w * (len(NAMESPACES) + 1))}")

    overall = {ns: [] for ns in NAMESPACES}
    wins = {ns: 0 for ns in NAMESPACES}

    for cat in ["법령", "판례", "행정해석", "복합"]:
        scores = category_scores[cat]
        avgs = {ns: (sum(scores[ns]) / len(scores[ns]) if scores[ns] else 0) for ns in NAMESPACES}
        best_ns = max(avgs, key=avgs.get)
        row = f"  {cat:<10}" + "".join(f"{avgs[ns]:>{col_w}.4f}" for ns in NAMESPACES) + f"{best_ns:>{col_w}}"
        print(row)
        for ns in NAMESPACES:
            overall[ns].extend(scores[ns])

    # 전체 평균
    total_avg = {ns: (sum(overall[ns]) / len(overall[ns]) if overall[ns] else 0) for ns in NAMESPACES}
    total_best = max(total_avg, key=total_avg.get)

    print(f"  {'─' * (10 + col_w * (len(NAMESPACES) + 1))}")
    print(f"  {'전체평균':<10}" + "".join(f"{total_avg[ns]:>{col_w}.4f}" for ns in NAMESPACES) + f"{total_best:>{col_w}}")

    # 쿼리별 Top-1 승리 네임스페이스 집계
    for result in all_results:
        top_scores = {ns: (result[ns][0]["score"] if result[ns] else 0) for ns in NAMESPACES}
        best = max(top_scores, key=top_scores.get)
        wins[best] += 1

    print(f"\n쿼리별 Top-1 승률 ({len(TEST_QUERIES)}건):")
    for ns in NAMESPACES:
        print(f"  {ns} 승: {wins[ns]}건 ({wins[ns]/len(TEST_QUERIES)*100:.0f}%)")

    # 0.3 이상 검색 결과 수 비교 (실질적 결과)
    print(f"\n유효 결과 수 비교 (score ≥ 0.3):")
    total_valid = {ns: 0 for ns in NAMESPACES}
    for result in all_results:
        for ns in NAMESPACES:
            total_valid[ns] += sum(1 for h in result[ns] if h["score"] >= 0.3)
    for ns in NAMESPACES:
        print(f"  {ns}: {total_valid[ns]}건")

    print(f"\n{'=' * 70}")

    # 결과 JSON 저장
    output = {
        "index": PINECONE_INDEX,
        "namespaces": NAMESPACES,
        "test_count": len(TEST_QUERIES),
        "summary": {
            "total_avg": {ns: round(total_avg[ns], 4) for ns in NAMESPACES},
            "best_namespace": total_best,
            "query_wins": wins,
            "valid_results_gte_03": total_valid,
        },
        "category_avg": {},
        "queries": all_results,
    }

    for cat in ["법령", "판례", "행정해석", "복합"]:
        scores = category_scores[cat]
        output["category_avg"][cat] = {
            ns: (round(sum(scores[ns]) / len(scores[ns]), 4) if scores[ns] else 0) for ns in NAMESPACES
        }

    with open("search_quality_results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n상세 결과 저장: search_quality_results.json")


if __name__ == "__main__":
    main()
