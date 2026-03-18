"""Pinecone 메타데이터에서 BM25 코퍼스 JSON 생성

사용법:
    python build_bm25_corpus.py

출력:
    data/bm25_corpus.json — BM25 검색용 코퍼스 데이터
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def build_corpus() -> None:
    api_key = os.getenv("PINECONE_API_KEY")
    if not api_key:
        print("ERROR: PINECONE_API_KEY not set")
        sys.exit(1)

    from pinecone import Pinecone

    index_name = os.getenv("PINECONE_INDEX_NAME", "semiconductor-lithography")
    pc = Pinecone(api_key=api_key)
    index = pc.Index(index_name)

    namespaces = ["laborlaw-v2", "counsel", "qa"]
    corpus: list[dict] = []

    for ns in namespaces:
        print(f"  Fetching namespace: {ns}...")
        try:
            count = 0
            for ids_batch in index.list(namespace=ns):
                if not ids_batch:
                    continue
                fetched = index.fetch(ids=list(ids_batch), namespace=ns)
                for vid, vec in fetched.vectors.items():
                    meta = vec.metadata or {}
                    text = meta.get("text", "")
                    if not text:
                        continue
                    corpus.append({
                        "id": vid,
                        "text": text,
                        "title": meta.get("title", ""),
                        "section": meta.get("section", ""),
                        "source_type": meta.get("source_type", ""),
                    })
                    count += 1
            print(f"    {ns}: {count} documents")
        except Exception as e:
            print(f"    {ns}: ERROR — {e}")

    # 출력 디렉토리 생성
    out_path = Path("data/bm25_corpus.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(corpus, f, ensure_ascii=False)

    print(f"\nBM25 corpus saved: {len(corpus)} documents → {out_path}")


if __name__ == "__main__":
    build_corpus()
