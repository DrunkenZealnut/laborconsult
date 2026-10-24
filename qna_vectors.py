"""Document-scoped Pinecone transactions with durable preimages and verification."""
from __future__ import annotations
import json
import re
import time
from pathlib import Path
from urllib.parse import quote

from qna_ingestion import digest, post_id_from_url
from vector_ledger import atomic_write_json

def as_dict(value):
    return value if isinstance(value, dict) else value.to_dict()

def list_ids(index, namespace: str, prefix: str = "") -> list[str]:
    ids = []
    for page in index.list(namespace=namespace, prefix=prefix, limit=100):
        items = getattr(page, "vectors", page)
        ids.extend(item if isinstance(item, str) else
                   item["id"] if isinstance(item, dict) else item.id for item in items)
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate IDs from pagination")
    return sorted(ids)

def fetch_vectors(index, namespace: str, ids: list[str]) -> dict:
    rows = {}
    batches, batch, size = [], [], 0
    for key in ids:
        cost = len(quote(key, safe="")) + 6
        if cost > 3500:
            raise ValueError("individual vector ID exceeds fetch URI budget")
        if batch and (size + cost > 3500 or len(batch) >= 200):
            batches.append(batch)
            batch, size = [], 0
        batch.append(key)
        size += cost
    if batch:
        batches.append(batch)
    for batch in batches:
        response = as_dict(index.fetch(ids=batch, namespace=namespace))
        for key, value in response.get("vectors", {}).items():
            row = as_dict(value)
            rows[key] = {"id": key, "values": list(row["values"]), "metadata": row.get("metadata") or {}}
    return rows

def _valid(namespace: str, post_id: str, production: bool):
    if not re.fullmatch(r"[0-9]+", post_id):
        raise ValueError("invalid post_id")
    if namespace != "qa" and not re.fullmatch(r"qa-eval-[a-z0-9-]+", namespace):
        raise ValueError("namespace outside Q&A transaction scope")
    if namespace == "qa" and not production:
        raise ValueError("production namespace requires explicit apply flag")

def _matches(actual: dict, expected: dict) -> bool:
    if actual.keys() != expected.keys():
        return False
    for key, row in expected.items():
        got = actual[key]
        if got["metadata"] != row["metadata"] or len(got["values"]) != len(row["values"]):
            return False
        if any(abs(a-b) > 1e-6 for a,b in zip(got["values"], row["values"])):
            return False
    return True

def verify_vectors(index, namespace: str, expected: dict, *, attempts: int = 5):
    for attempt in range(attempts):
        if _matches(fetch_vectors(index, namespace, list(expected)), expected):
            return
        if attempt < attempts - 1:
            time.sleep(2 ** attempt)
    raise RuntimeError("vector fetch verification failed")

def _guard_revision(current: dict, old: dict, new: dict):
    for key,row in current.items():
        if not any(key in allowed and _matches({key:row},{key:allowed[key]}) for allowed in (old,new)):
            raise ValueError("document changed after this transaction; refusing to overwrite a later revision")


def _verify_ids(index, namespace: str, prefix: str, expected: set[str]):
    for attempt in range(5):
        if set(list_ids(index, namespace, prefix)) == expected:
            return
        if attempt < 4:
            time.sleep(2 ** attempt)
    raise RuntimeError("document ID verification failed")

def _write(path: Path, value):
    atomic_write_json(str(path), value)

def replace_document(index, namespace: str, post_id: str, vectors: list[dict],
                     ledger_dir: Path, *, production: bool = False) -> dict:
    _valid(namespace, post_id, production)
    pattern = re.compile(rf"ctx_qa_{post_id}_c[0-9]+")
    if not vectors or any(not pattern.fullmatch(v["id"]) for v in vectors):
        raise ValueError("empty or wrong document replacement")
    expected = {v["id"]: v for v in vectors}
    if len(expected) != len(vectors):
        raise ValueError("duplicate replacement IDs")
    for row in vectors:
        if not row["values"] or post_id_from_url(row["metadata"].get("url", "")) != post_id:
            raise ValueError("missing vector values or mismatched provenance")
    ledger = ledger_dir/post_id
    ledger.mkdir(parents=True, exist_ok=True)
    identity = {"namespace": namespace, "post_id": post_id, "replacement_hash": digest(vectors)}
    tx_path = ledger/"transaction.json"
    if tx_path.exists() and json.loads(tx_path.read_text()) != identity:
        raise ValueError("ledger belongs to a different replacement; use another ledger")
    prefix = f"ctx_qa_{post_id}_c"
    current_ids = list_ids(index, namespace, prefix)
    if any(not pattern.fullmatch(key) for key in current_ids):
        raise ValueError("unexpected ID within document prefix")
    before_path = ledger/"before.json"
    if not before_path.exists():
        before = fetch_vectors(index, namespace, current_ids)
        if set(before) != set(current_ids):
            raise RuntimeError("preimage fetch incomplete")
        if any(post_id_from_url(v["metadata"].get("url", "")) != post_id for v in before.values()):
            raise ValueError("preimage belongs to another source")
        _write(before_path, {"namespace": namespace, "post_id": post_id, "vectors": before})
    else:
        before = json.loads(before_path.read_text())
        if before["namespace"] != namespace or before["post_id"] != post_id:
            raise ValueError("preimage identity mismatch")
    old_vectors = json.loads(before_path.read_text())["vectors"]
    current = fetch_vectors(index, namespace, current_ids)
    if set(current) != set(current_ids):
        raise RuntimeError("current document fetch incomplete")
    _guard_revision(current, old_vectors, expected)
    _write(ledger/"replacement.json", expected)
    _write(tx_path, identity)
    (ledger/"complete.json").unlink(missing_ok=True)
    for start in range(0, len(vectors), 100):
        index.upsert(vectors=vectors[start:start+100], namespace=namespace)
    verify_vectors(index, namespace, expected)
    stale = sorted(set(current_ids) - set(expected))
    for start in range(0, len(stale), 100):
        index.delete(ids=stale[start:start+100], namespace=namespace)
    _verify_ids(index, namespace, prefix, set(expected))
    result = {**identity, "chunk_ids": sorted(expected), "removed_ids": stale, "status": "complete"}
    _write(ledger/"complete.json", result)
    return result

def restore_document(index, namespace: str, post_id: str, ledger_dir: Path, *,
                     production: bool = False):
    _valid(namespace, post_id, production)
    ledger = ledger_dir/post_id
    before = json.loads((ledger/"before.json").read_text())
    if before["namespace"] != namespace or before["post_id"] != post_id:
        raise ValueError("preimage identity mismatch")
    tx = json.loads((ledger/"transaction.json").read_text())
    if tx["namespace"] != namespace or tx["post_id"] != post_id:
        raise ValueError("transaction identity mismatch")
    expected = before["vectors"]
    pattern = re.compile(rf"ctx_qa_{post_id}_c[0-9]+")
    if any(not pattern.fullmatch(key) for key in expected):
        raise ValueError("preimage IDs outside document scope")
    replacement = json.loads((ledger/"replacement.json").read_text())
    current_ids = list_ids(index, namespace, f"ctx_qa_{post_id}_c")
    current = fetch_vectors(index, namespace, current_ids)
    if set(current) != set(current_ids):
        raise RuntimeError("rollback current fetch incomplete")
    _guard_revision(current, expected, replacement)
    for start in range(0, len(expected), 100):
        rows = list(expected.values())[start:start+100]
        index.upsert(vectors=rows, namespace=namespace)
    if expected:
        verify_vectors(index, namespace, expected)
    prefix = f"ctx_qa_{post_id}_c"
    current = list_ids(index, namespace, prefix)
    if any(not pattern.fullmatch(key) for key in current):
        raise ValueError("unexpected rollback target")
    stale = sorted(set(current) - set(expected))
    for start in range(0, len(stale), 100):
        index.delete(ids=stale[start:start+100], namespace=namespace)
    _verify_ids(index, namespace, prefix, set(expected))
    (ledger/"complete.json").unlink(missing_ok=True)
    _write(ledger/"restored.json", {"namespace": namespace, "post_id": post_id, "status": "restored"})
