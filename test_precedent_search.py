#!/usr/bin/env python3
"""Pinecone precedent 네임스페이스 검색 검증 테스트."""

import os
from dotenv import load_dotenv
from openai import OpenAI
from pinecone import Pinecone

load_dotenv()

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
index = pc.Index(os.getenv("PINECONE_INDEX_NAME", "nodongok-bestqna"))

# 1. 인덱스 통계
stats = index.describe_index_stats()
ns = stats.namespaces.get("precedent")
print(f"{'='*60}")
print(f"1. Pinecone precedent 네임스페이스 통계")
print(f"   총 벡터: {ns.vector_count:,}개" if ns else "   없음")
print(f"{'='*60}\n")

# 2. 검색 테스트 쿼리들
test_queries = [
    ("통상임금 판단 기준", "기존+신규 판례 혼합"),
    ("택배기사 노조활동 정당성", "신규 (2024마6760)"),
    ("진폐 유족급여 평균임금", "신규 (2023두63413)"),
    ("긴급이행명령 과태료", "신규 (2017마5737)"),
    ("파견근로자 직접고용 간주", "비정규직 카테고리"),
    ("업무상 재해 산재보험", "산재보상 카테고리"),
    ("단체협약 시정명령", "신규 (2018재두178)"),
]

print(f"2. 검색 테스트 ({len(test_queries)}개 쿼리)\n")

for query, desc in test_queries:
    resp = openai_client.embeddings.create(model="text-embedding-3-small", input=[query])
    qvec = resp.data[0].embedding

    results = index.query(
        vector=qvec,
        namespace="precedent",
        top_k=3,
        include_metadata=True,
    )

    print(f"─── 쿼리: \"{query}\" ({desc}) ───")
    for j, m in enumerate(results.matches, 1):
        meta = m.metadata
        score = m.score
        title = meta.get("title", "")[:55]
        cat = meta.get("category", "")
        print(f"  {j}. [{score:.3f}] [{cat}] {title}")
    print()

print(f"{'='*60}")
print("✅ 검색 테스트 완료")
