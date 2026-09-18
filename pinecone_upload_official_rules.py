#!/usr/bin/env python3
"""output_공식법령/ 의 공식 원문을 laborlaw-v2 에 적재한다.

이 업로더의 존재 이유는 **메타데이터의 `official_url`** 하나다. 승인 게이트
(`app/core/legal_updates.py::official_evidence`)는 그 필드만 보고 공식 원문 여부를
판정하며, 본문에 주소가 적혀 있어도 승인하지 않는다. 기존 코퍼스의 훈령·예규는 전부
nodong.kr 재수록이고 판례는 url 자체가 없어, 2026-09-18 실측 기준 승인 가능한 근거가
**0건**이었다.

    python3 pinecone_upload_official_rules.py --dry-run   # 청킹·메타데이터 검증
    python3 pinecone_upload_official_rules.py             # 업로드 + 고아 정리
    python3 pinecone_upload_official_rules.py --allow-large-prune   # ID 규격을 의도적으로 바꿨을 때만

업로드 후 `build_bm25_corpus.py` 재실행이 필요하다(BM25 코퍼스는 별도 파일이다).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time

from vector_ledger import VectorLedger

SRC_DIR = "output_공식법령"
UPLOADED_IDS_FILE = os.path.join(SRC_DIR, "_uploaded_ids.json")
NAMESPACE = "laborlaw-v2"          # 프로덕션 검색 대상 (rag.py::NS_GROUPS)
ID_PREFIX = "official"
CHUNK_SIZE = 700
CHUNK_OVERLAP = 80
EMBED_BATCH = 64
UPSERT_BATCH = 100
# 메타데이터 본문 상한. 청크가 CHUNK_SIZE 라 평시엔 걸리지 않지만, 상한에 걸려 잘리면
# 인용구절 검사(`quote in evidence["text"]`)가 조용히 실패하므로 여유를 둔다.
TEXT_CAP = 1200

# 그룹 키 = doc_id. "한 번의 실행이 항상 통째로 다루는 단위"여야 prune 이 부분 실행을
# 고아로 오판하지 않는다(--only 로 한 문서만 돌려도 그 문서만 비교된다).
_LEDGER = VectorLedger(
    UPLOADED_IDS_FILE,
    group_re=re.compile(r"^[a-z0-9_]+$"),
    id_re_for=lambda doc_id: re.compile(rf"^{ID_PREFIX}_{re.escape(doc_id)}_\d+$"),
)

_HEADER_RE = re.compile(r"^-\s*([A-Za-z_]+):\s*(.*)$")


def parse_doc(path: str) -> dict | None:
    """fetch_official_rules.py 가 쓴 헤더 + 본문을 읽는다."""
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    head, marker, body = raw.partition("\n## 본문")
    if not marker or not body.strip():
        return None
    meta = {}
    for line in head.splitlines():
        m = _HEADER_RE.match(line.strip())
        if m:
            meta[m.group(1)] = m.group(2).strip()
    required = ("doc_id", "source_type", "title", "official_url")
    if any(not meta.get(k) for k in required):
        return None
    if not re.fullmatch(r"[a-z0-9_]+", meta["doc_id"]):
        return None
    if not meta["official_url"].startswith("https://"):
        # https 가 아니면 승인 게이트를 통과하지 못한다 — 올려도 쓸모가 없다.
        return None
    meta["keys"] = [k.strip() for k in meta.get("keys", "").split(",") if k.strip()]
    meta["body"] = body.strip()
    return meta


def split_text(text: str) -> list[str]:
    """고정 크기 분할. 조문·고시는 짧아 대개 1~2청크로 끝난다."""
    text = text.strip()
    if len(text) <= CHUNK_SIZE:
        return [text] if text else []
    chunks, start = [], 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunks.append(text[start:end].strip())
        if end >= len(text):           # 이 가드가 없으면 끝에 자투리 청크가 생긴다
            break
        start = end - CHUNK_OVERLAP
    return [c for c in chunks if c]


def build_vectors(doc: dict) -> list[dict]:
    out = []
    for i, chunk in enumerate(split_text(doc["body"])):
        meta = {
            "source_type": doc["source_type"],
            "title": doc["title"][:200],
            "section": doc["title"][:80],
            # 승인 게이트가 보는 필드. url 도 같이 넣는다 — official_url 이 빠진
            # 구 벡터와 섞여도 폴백이 같은 값을 보게 하려는 것이다.
            "official_url": doc["official_url"],
            "url": doc["official_url"],
            # 검색에서 공식 원문만 따로 뽑기 위한 표식. Pinecone 메타데이터 필터에는
            # "필드가 존재하는가"가 없어(=$exists 미지원) official_url 유무로는 거를 수
            # 없다. 이 불리언이 없으면 신규 17건이 기존 수만 건에 묻혀 top_k 8 에
            # 영원히 못 들고, 자동 검색이 공식 근거를 한 건도 후보로 못 만든다(실측).
            "official": True,
            "issuer": doc.get("issuer", "")[:100],
            "date": doc.get("date", "")[:20],
            "chunk_index": i,
            # rag.py::_query_namespaces 가 text/chunk_text 이중 폴백이라 둘 다 쓴다.
            "text": chunk[:TEXT_CAP],
            "chunk_text": chunk[:TEXT_CAP],
        }
        if doc["keys"]:
            meta["rule_keys"] = doc["keys"]
        out.append({"id": f"{ID_PREFIX}_{doc['doc_id']}_{i}", "metadata": meta,
                    "chunk": chunk})
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="청킹·메타데이터만 검증")
    parser.add_argument("--only", help="이 doc_id 만 처리")
    parser.add_argument("--allow-large-prune", action="store_true",
                        help="고아 벡터가 현재 청크의 50%%를 넘어도 진행(ID 규격 변경 시에만)")
    args = parser.parse_args(argv)

    if not os.path.isdir(SRC_DIR):
        print(f"[오류] {SRC_DIR}/ 가 없습니다 — fetch_official_rules.py 를 먼저 실행하세요",
              file=sys.stderr)
        return 1

    docs, skipped = [], []
    for name in sorted(os.listdir(SRC_DIR)):
        if not name.endswith(".md"):
            continue
        doc = parse_doc(os.path.join(SRC_DIR, name))
        if doc is None:
            skipped.append(name)
            continue
        if args.only and doc["doc_id"] != args.only:
            continue
        docs.append(doc)

    if skipped:
        print(f"[경고] 헤더/본문/https 요건 미충족 {len(skipped)}건 건너뜀: {', '.join(skipped)}")
    if not docs:
        print("[오류] 적재할 문서가 없습니다", file=sys.stderr)
        return 1

    groups: dict[str, list[str]] = {}
    prepared: list[dict] = []
    for doc in docs:
        vectors = build_vectors(doc)
        groups[doc["doc_id"]] = [v["id"] for v in vectors]
        prepared.extend(vectors)
        print(f"  {doc['doc_id']:<14} {len(vectors)}청크  {doc['source_type']:<10} "
              f"{doc['title'][:38]}")

    print(f"\n문서 {len(docs)}건 → 벡터 {len(prepared)}건")
    if args.dry_run:
        sample = prepared[0]["metadata"]
        print("\n[dry-run] 첫 벡터 메타데이터:")
        for k, v in sample.items():
            shown = v if not isinstance(v, str) or len(v) <= 90 else v[:90] + "…"
            print(f"  {k}: {shown}")
        return 0

    from dotenv import load_dotenv
    load_dotenv(override=True)
    from openai import OpenAI
    from pinecone import Pinecone
    from app.config import EMBED_MODEL, resolve_index_name

    openai = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    index = Pinecone(api_key=os.environ["PINECONE_API_KEY"]).Index(resolve_index_name())

    # 원장 기록은 upsert보다 **먼저** — 도중에 죽어도 적재분이 추적에서 빠지지 않는다.
    previous = _LEDGER.record(groups)

    pending = []
    for i in range(0, len(prepared), EMBED_BATCH):
        batch = prepared[i:i + EMBED_BATCH]
        res = openai.embeddings.create(model=EMBED_MODEL, input=[b["chunk"] for b in batch])
        if len(res.data) != len(batch):
            # 부분 임베딩으로 진행하면 일부 청크가 조용히 빠진다. 결정적 ID라 재실행이
            # 안전하므로 즉시 중단이 맞다.
            sys.exit(f"[오류] 임베딩 수 불일치: {len(res.data)} != {len(batch)} — 중단")
        for item, emb in zip(batch, res.data):
            pending.append({"id": item["id"], "values": emb.embedding,
                            "metadata": item["metadata"]})
        while len(pending) >= UPSERT_BATCH:
            index.upsert(vectors=pending[:UPSERT_BATCH], namespace=NAMESPACE)
            pending = pending[UPSERT_BATCH:]
            time.sleep(0.1)
    if pending:
        index.upsert(vectors=pending, namespace=NAMESPACE)

    print(f"업로드 완료: {len(prepared)}벡터 → {NAMESPACE}")
    _LEDGER.prune(groups, previous, index, NAMESPACE,
                  allow_large=args.allow_large_prune, label="공식 법령")
    print("\n다음 단계: python3 build_bm25_corpus.py (BM25 코퍼스는 별도 파일이라 "
          "재빌드하지 않으면 키워드 검색에 반영되지 않는다)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
