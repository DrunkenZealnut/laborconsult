"""Pinecone 메타데이터에서 BM25 코퍼스 생성

사용법:
    python build_bm25_corpus.py

출력:
    data/bm25_corpus.json.gz — BM25 검색용 코퍼스 (커밋 대상, raw json은 gitignore)
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

    from app.config import resolve_index_name
    index_name = resolve_index_name()
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

    # gzip 출력 — Vercel 배포용 커밋 대상 (raw json은 .gitignore) (DB-1)
    import gzip
    out_path = Path("data/bm25_corpus.json.gz")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with gzip.open(out_path, "wt", encoding="utf-8") as f:
        json.dump(corpus, f, ensure_ascii=False, separators=(",", ":"))

    size_mb = out_path.stat().st_size / 1e6
    print(f"\nBM25 corpus saved: {len(corpus)} documents → {out_path} ({size_mb:.1f}MB gz)")
    if size_mb > 10:
        print("⚠️ 10MB 초과 — 리포 커밋 대신 외부 저장(design 부록 A) 검토 필요")


if __name__ == "__main__":
    build_corpus()
