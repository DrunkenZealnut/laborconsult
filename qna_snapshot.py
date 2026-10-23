"""Assemble immutable BM25 candidates from verified vector snapshots."""
from __future__ import annotations
from collections import defaultdict
import gzip
import json
from pathlib import Path
import re

from app.core.provenance import provenance, is_nodong_qa
from qna_corpus import enrich_baseline
from qna_ingestion import digest

NAMESPACES = ("laborlaw-v2", "counsel", "qa")

def iter_namespace(snapshot: Path, namespace: str):
    folder = snapshot/namespace
    if not (folder/"complete.json").is_file() or not (folder/"ids.json").is_file():
        raise ValueError(f"incomplete snapshot: {namespace}")
    ids = json.loads((folder/"ids.json").read_text())
    complete = json.loads((folder/"complete.json").read_text())
    if not ids or len(ids) != len(set(ids)) or complete["count"] != len(ids):
        raise ValueError("invalid snapshot ID manifest")
    seen = set()
    for shard in sorted(folder.glob("*.json.gz")):
        with gzip.open(shard, "rt") as stream:
            rows = json.load(stream)
        for key, row in rows.items():
            if key in seen or key != row["id"]:
                raise ValueError("duplicate or mismatched snapshot ID")
            seen.add(key)
            yield row
    if seen != set(ids):
        raise ValueError(f"incomplete shards: {namespace}")

def legacy_versions(snapshot: Path) -> dict[str, str]:
    by_post = defaultdict(list)
    for row in iter_namespace(snapshot, "qa"):
        meta = provenance(row["metadata"])
        if is_nodong_qa(meta) and meta.get("post_id"):
            by_post[meta["post_id"]].append((row["id"], digest(row["metadata"])))
    return {key: "legacy-" + digest(sorted(parts)) for key, parts in by_post.items()}

def sparse_row(vector: dict, namespace: str) -> dict:
    meta = vector["metadata"]
    row = {"id": vector["id"], "text": meta.get("text") or meta.get("chunk_text", ""),
           "title": meta.get("title", ""), "section": meta.get("section", ""),
           "source_type": meta.get("source_type", ""), **provenance(meta), "namespace": namespace}
    if meta.get("book_id"):
        row["book_id"] = meta["book_id"]
    return row

def build_sparse(snapshot: Path, replacements: dict[str, list[dict]], output: Path) -> dict:
    versions = legacy_versions(snapshot)
    for post_id, rows in replacements.items():
        if not re.fullmatch(r"[0-9]+", post_id) or not rows:
            raise ValueError("empty or invalid replacement")
        if any(not re.fullmatch(rf"ctx_qa_{post_id}_c[0-9]+", r["id"]) for r in rows):
            raise ValueError("replacement ID outside document")
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix+".tmp")
    counts = defaultdict(int)
    originals = defaultdict(int)
    seen = set()
    try:
        with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as stream:
            def emit(vector, ns):
                row = sparse_row(vector, ns)
                if not row["text"]:
                    return
                if row["id"] in seen:
                    raise ValueError("duplicate sparse document ID")
                seen.add(row["id"])
                counts[ns] += 1
                stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"))+"\n")
            for ns in NAMESPACES:
                for raw in iter_namespace(snapshot, ns):
                    originals[ns] += 1
                    row = enrich_baseline(raw, ns)
                    meta = row["metadata"]
                    if ns == "qa" and is_nodong_qa(meta):
                        post_id = meta.get("post_id")
                        if post_id in replacements:
                            continue
                        if post_id in versions:
                            meta["document_version"] = versions[post_id]
                    emit(row, ns)
                if ns == "qa":
                    for rows in replacements.values():
                        for row in rows:
                            emit(row, ns)
            if any(counts[ns] == 0 for ns in NAMESPACES):
                raise ValueError("empty namespace")
            if sum(counts.values()) < sum(originals.values()) * 0.8:
                raise ValueError("corpus decreased by more than 20%")
        tmp.replace(output)
    finally:
        tmp.unlink(missing_ok=True)
    return {"count": sum(counts.values()), "namespaces": dict(counts),
            "original_namespaces": dict(originals), "replacement_documents": len(replacements)}


def clone_qa(snapshot: Path, index, namespace: str, ledger: Path, *, source_namespace: str = "qa") -> dict:
    """Copy a frozen QA snapshot to an owned evaluation namespace, resumably."""
    from qna_vectors import list_ids, verify_vectors, fetch_vectors, _matches
    from vector_ledger import atomic_write_json
    if not re.fullmatch(r"qa-eval-[a-z0-9-]+", namespace):
        raise ValueError("clone destination must be an evaluation namespace")
    if source_namespace not in NAMESPACES:
        raise ValueError("unknown source namespace")
    versions = legacy_versions(snapshot) if source_namespace == "qa" else {}
    ids = sorted(json.loads((snapshot/source_namespace/"ids.json").read_text()))
    identity = {"namespace": namespace, "ids_hash": digest(ids), "versions_hash": digest(versions),
                "snapshot": str(snapshot.resolve())}
    if source_namespace != "qa":
        identity["source_namespace"] = source_namespace
    ledger.mkdir(parents=True, exist_ok=True)
    manifest = ledger/"clone.json"
    existing = list_ids(index, namespace)
    if manifest.exists():
        if json.loads(manifest.read_text()) != identity:
            raise ValueError("clone ledger identity mismatch")
        if set(existing) - set(ids):
            raise ValueError("unexpected vectors in owned namespace")
    elif existing:
        raise ValueError("refusing to overwrite an unowned populated namespace")
    atomic_write_json(str(manifest), identity)
    (ledger/"complete.json").unlink(missing_ok=True)
    batch, count = [], 0
    existing_ids = set(existing)
    def flush(rows):
        expected = {r["id"]: r for r in rows}
        if set(expected) <= existing_ids and _matches(fetch_vectors(index, namespace, list(expected)), expected):
            return
        index.upsert(vectors=rows, namespace=namespace)
        verify_vectors(index, namespace, {r["id"]: r for r in rows})
    for raw in iter_namespace(snapshot, source_namespace):
        row = enrich_baseline(raw, source_namespace)
        post_id = row["metadata"].get("post_id")
        if post_id in versions:
            row["metadata"]["document_version"] = versions[post_id]
        batch.append(row)
        if len(batch) == 100:
            flush(batch)
            count += len(batch)
            batch = []
            if count % 2500 == 0:
                print(f"clone {namespace}: {count}/{len(ids)}", flush=True)
    if batch:
        flush(batch)
        count += len(batch)
    # Fetches above confirm content, enumeration confirms no missing/extra chunks.
    if list_ids(index, namespace) != ids:
        raise RuntimeError("clone ID verification failed")
    result = {**identity, "count": count, "status": "complete"}
    atomic_write_json(str(ledger/"complete.json"), result)
    return result
