#!/usr/bin/env python3
"""Pinecone 네임스페이스 검색 품질 비교: laborlaw vs laborlaw-v2

laborlaw: 표준 임베딩 (text-embedding-3-small)
laborlaw-v2: Contextual Retrieval (Claude Haiku 맥락 prefix + 임베딩)

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
PINECONE_INDEX = "semiconductor-lithography"
EMBED_MODEL = "text-embedding-3-small"
NAMESPACES = ["laborlaw", "laborlaw-v2"]
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
    print("검색 품질 비교 테스트: laborlaw vs laborlaw-v2")
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

    # 카테고리별 평균 Top1 점수
    print("\n카테고리별 Top-1 평균 점수:")
    print(f"  {'카테고리':<10} {'laborlaw':>12} {'laborlaw-v2':>12} {'차이':>10} {'승자':>12}")
    print(f"  {'─' * 56}")

    overall = {ns: [] for ns in NAMESPACES}
    wins = {ns: 0 for ns in NAMESPACES}

    for cat in ["법령", "판례", "행정해석", "복합"]:
        scores = category_scores[cat]
        avg1 = sum(scores["laborlaw"]) / len(scores["laborlaw"]) if scores["laborlaw"] else 0
        avg2 = sum(scores["laborlaw-v2"]) / len(scores["laborlaw-v2"]) if scores["laborlaw-v2"] else 0
        diff = avg2 - avg1
        winner = "laborlaw-v2" if diff > 0 else ("laborlaw" if diff < 0 else "동점")
        print(f"  {cat:<10} {avg1:>12.4f} {avg2:>12.4f} {diff:>+10.4f} {winner:>12}")

        overall["laborlaw"].extend(scores["laborlaw"])
        overall["laborlaw-v2"].extend(scores["laborlaw-v2"])

    # 전체 평균
    total_avg1 = sum(overall["laborlaw"]) / len(overall["laborlaw"]) if overall["laborlaw"] else 0
    total_avg2 = sum(overall["laborlaw-v2"]) / len(overall["laborlaw-v2"]) if overall["laborlaw-v2"] else 0
    total_diff = total_avg2 - total_avg1
    total_winner = "laborlaw-v2" if total_diff > 0 else ("laborlaw" if total_diff < 0 else "동점")

    print(f"  {'─' * 56}")
    print(f"  {'전체평균':<10} {total_avg1:>12.4f} {total_avg2:>12.4f} {total_diff:>+10.4f} {total_winner:>12}")

    # 쿼리별 승률
    v1_wins = 0
    v2_wins = 0
    ties = 0
    for result in all_results:
        s1 = result["laborlaw"][0]["score"] if result["laborlaw"] else 0
        s2 = result["laborlaw-v2"][0]["score"] if result["laborlaw-v2"] else 0
        if s1 > s2:
            v1_wins += 1
        elif s2 > s1:
            v2_wins += 1
        else:
            ties += 1

    print(f"\n쿼리별 Top-1 승률 ({len(TEST_QUERIES)}건):")
    print(f"  laborlaw 승: {v1_wins}건 ({v1_wins/len(TEST_QUERIES)*100:.0f}%)")
    print(f"  laborlaw-v2 승: {v2_wins}건 ({v2_wins/len(TEST_QUERIES)*100:.0f}%)")
    print(f"  동점: {ties}건")

    # 0.3 이상 검색 결과 수 비교 (실질적 결과)
    print(f"\n유효 결과 수 비교 (score ≥ 0.3):")
    total_valid_v1 = 0
    total_valid_v2 = 0
    for result in all_results:
        total_valid_v1 += sum(1 for h in result["laborlaw"] if h["score"] >= 0.3)
        total_valid_v2 += sum(1 for h in result["laborlaw-v2"] if h["score"] >= 0.3)
    print(f"  laborlaw: {total_valid_v1}건")
    print(f"  laborlaw-v2: {total_valid_v2}건")

    print(f"\n{'=' * 70}")

    # 결과 JSON 저장
    output = {
        "index": PINECONE_INDEX,
        "namespaces": NAMESPACES,
        "test_count": len(TEST_QUERIES),
        "summary": {
            "total_avg_laborlaw": round(total_avg1, 4),
            "total_avg_laborlaw_v2": round(total_avg2, 4),
            "diff": round(total_diff, 4),
            "winner": total_winner,
            "query_wins": {"laborlaw": v1_wins, "laborlaw-v2": v2_wins, "ties": ties},
            "valid_results_gte_03": {"laborlaw": total_valid_v1, "laborlaw-v2": total_valid_v2},
        },
        "category_avg": {},
        "queries": all_results,
    }

    for cat in ["법령", "판례", "행정해석", "복합"]:
        scores = category_scores[cat]
        output["category_avg"][cat] = {
            "laborlaw": round(sum(scores["laborlaw"]) / len(scores["laborlaw"]), 4) if scores["laborlaw"] else 0,
            "laborlaw-v2": round(sum(scores["laborlaw-v2"]) / len(scores["laborlaw-v2"]), 4) if scores["laborlaw-v2"] else 0,
        }

    with open("search_quality_results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n상세 결과 저장: search_quality_results.json")


if __name__ == "__main__":
    main()
