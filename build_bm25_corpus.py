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
    failed_namespaces: list[str] = []

    for ns in namespaces:
        print(f"  Fetching namespace: {ns}...")
        try:
            count = 0
            pagination_token = None
            while True:
                # index.list()+fetch(by id)는 이 계정에서 list()가 반환한 ID가
                # fetch()에서 일관되게 0건으로 돌아오는 문제가 있어(list()의
                # ID 인덱스가 실제 벡터 데이터와 어긋난 것으로 보임 —
                # query()/fetch_by_metadata는 정상 동작함을 확인) 메타데이터
                # 필터 기반 페이지네이션으로 우회한다. chunk_index는 모든
                # 청크에 항상 존재하는 정수 필드라 전체 매치용으로 사용.
                resp = index.fetch_by_metadata(
                    filter={"chunk_index": {"$gte": 0}},
                    namespace=ns,
                    limit=100,
                    pagination_token=pagination_token,
                )
                for vid, vec in resp.vectors.items():
                    meta = vec.metadata or {}
                    # laborlaw-v2(Contextual Retrieval)는 "text" 없이 "chunk_text"만 존재
                    text = meta.get("text") or meta.get("chunk_text", "")
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
                pagination_token = resp.pagination.next if resp.pagination else None
                if not pagination_token:
                    break
            print(f"    {ns}: {count} documents")
        except Exception as e:
            print(f"    {ns}: ERROR — {e}")
            failed_namespaces.append(ns)

    # 일부 네임스페이스라도 실패하면 부분 코퍼스로 기존 정상 파일을 덮어쓰지 않는다
    # — 이전엔 실패 후에도 무조건 저장해 불완전한 코퍼스가 커밋될 위험이 있었다.
    if failed_namespaces:
        print(f"\nERROR: 다음 네임스페이스 조회 실패 — 저장 건너뜀 (기존 파일 보존): "
              f"{failed_namespaces}")
        sys.exit(1)

    # gzip 출력 — Vercel 배포용 커밋 대상 (raw json은 .gitignore) (DB-1)
    # 임시 파일에 먼저 쓰고 성공 시에만 교체 — 쓰기 도중 중단돼도 기존 파일이 손상되지 않음
    import gzip
    out_path = Path("data/bm25_corpus.json.gz")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")

    with gzip.open(tmp_path, "wt", encoding="utf-8") as f:
        json.dump(corpus, f, ensure_ascii=False, separators=(",", ":"))
    tmp_path.replace(out_path)

    size_mb = out_path.stat().st_size / 1e6
    print(f"\nBM25 corpus saved: {len(corpus)} documents → {out_path} ({size_mb:.1f}MB gz)")
    if size_mb > 10:
        print("⚠️ 10MB 초과 — 리포 커밋 대신 외부 저장(design 부록 A) 검토 필요")


if __name__ == "__main__":
    build_corpus()
