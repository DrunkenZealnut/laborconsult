#!/usr/bin/env python3
"""커밋된 벡터 배치 원장(`data/vector_ledgers/*.json`)으로 적재분을 검증·롤백한다.

**왜 저장소에 두는가.** 다른 원장(`output_*/_uploaded_ids.json`)은 gitignore 대상이라
디스크를 잃으면 롤백 수단도 함께 사라진다. 2026-10-09 공식 자료팩 7,111벡터는 업로드
스크립트·원장이 저장소 밖(`laborconsult_eval/`)에만 있었다. Pinecone Serverless는
메타데이터 필터 삭제를 지원하지 않으므로 **ID 목록이 유일한 삭제 수단**이다.

    python3 source_pack_ledger.py verify   data/vector_ledgers/qpack_20261009.json
    python3 source_pack_ledger.py rollback data/vector_ledgers/qpack_20261009.json        # dry-run
    python3 source_pack_ledger.py rollback data/vector_ledgers/qpack_20261009.json \\
        --document <source_pack_id> --apply                                              # 문서 단위

삭제 안전장치: ID는 원장의 `id_pattern`을 전부 만족해야 하고, 네임스페이스는 원장 값만
쓰며(`delete_all`·필터 삭제 없음), 원장 인덱스명이 현재 설정과 다르면 중단한다.
롤백 후에는 `build_bm25_corpus.py` 재빌드 → `data/bm25_corpus.jsonl.gz` 커밋이 필요하다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FETCH_BATCH = 100
DELETE_BATCH = 1000


def load_ledger(path: str) -> dict:
    """원장을 읽고 ID 형식·개수·중복을 검증한다. 어긋나면 어떤 쓰기도 하지 않는다."""
    with open(path, encoding="utf-8") as f:
        ledger = json.load(f)
    pattern = re.compile(ledger["id_pattern"])
    ids = ledger_ids(ledger)
    bad = [i for i in ids if not pattern.fullmatch(i)]
    if bad:
        raise ValueError(f"id_pattern 불일치 {len(bad)}건: {bad[:3]}")
    if len(set(ids)) != len(ids):
        raise ValueError("원장 ID 중복")
    if len(ids) != ledger["vector_count"]:
        raise ValueError(f"vector_count {ledger['vector_count']} != ID {len(ids)}")
    return ledger


def ledger_ids(ledger: dict, document: str | None = None) -> list[str]:
    """원장의 ID를 문서 순서대로 펼친다. document를 주면 그 문서만."""
    docs = ledger["documents"]
    if document is not None:
        if document not in docs:
            raise KeyError(f"원장에 없는 문서: {document}")
        return list(docs[document]["ids"])
    return [i for d in docs.values() for i in d["ids"]]


def open_index(ledger: dict):
    """원장의 인덱스와 현재 설정이 같을 때만 오프라인 핸들을 연다."""
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)
    from app.config import open_offline_index, resolve_index_name
    if resolve_index_name() != ledger["index"]:
        raise SystemExit(f"인덱스 불일치: 원장 {ledger['index']} / 설정 {resolve_index_name()}")
    return open_offline_index()


def verify(ledger: dict, index) -> int:
    """원장 ID가 모두 존재하고 배치 표식이 맞는지 본다(읽기 전용). 이상 시 1."""
    ids, ns = ledger_ids(ledger), ledger["namespace"]
    flags = ledger.get("metadata_flags", {})
    missing, mismatched = [], []
    for start in range(0, len(ids), FETCH_BATCH):
        batch = ids[start:start + FETCH_BATCH]
        got = index.fetch(ids=batch, namespace=ns).vectors
        for vid in batch:
            vec = got.get(vid)
            if vec is None:
                missing.append(vid)
            elif any(vec.metadata.get(k) != v for k, v in flags.items()):
                mismatched.append(vid)
    print(f"{ledger['batch']}: 존재 {len(ids) - len(missing)}/{len(ids)} · "
          f"표식 불일치 {len(mismatched)} · ns={ns}")
    for label, rows in (("누락", missing), ("불일치", mismatched)):
        if rows:
            print(f"  {label} 예: {rows[:5]}")
    return 1 if missing or mismatched else 0


def rollback(ledger: dict, index, *, document: str | None, apply: bool) -> int:
    """원장 ID만 명시 삭제한다. 기본은 dry-run."""
    ids, ns = ledger_ids(ledger, document), ledger["namespace"]
    scope = document or "전체"
    if not apply:
        print(f"[dry-run] {ledger['batch']} {scope}: {len(ids)}벡터 삭제 예정 (ns={ns}). "
              f"실행하려면 --apply")
        return 0
    for start in range(0, len(ids), DELETE_BATCH):
        index.delete(ids=ids[start:start + DELETE_BATCH], namespace=ns)
    print(f"{ledger['batch']} {scope}: {len(ids)}벡터 삭제 요청 완료 (ns={ns}). "
          f"verify로 반영을 확인하고 build_bm25_corpus.py를 재실행할 것")
    if document is not None:
        print("  문서 단위 롤백: 원장에서 그 문서를 지우고 vector_count·composition·document_count를 "
              "갱신해 커밋할 것(그대로 두면 verify가 누락으로 보고한다)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=["verify", "rollback"])
    parser.add_argument("ledger")
    parser.add_argument("--document", help="rollback 범위를 한 source_pack_id로 좁힌다")
    parser.add_argument("--apply", action="store_true", help="rollback 실제 실행")
    args = parser.parse_args(argv)
    ledger = load_ledger(args.ledger)
    if args.action == "rollback" and not args.apply:
        return rollback(ledger, None, document=args.document, apply=False)
    index = open_index(ledger)
    if args.action == "verify":
        return verify(ledger, index)
    return rollback(ledger, index, document=args.document, apply=True)


if __name__ == "__main__":
    sys.exit(main())
