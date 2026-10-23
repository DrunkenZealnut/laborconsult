"""Private record of retrieval candidates and final context selections."""
from __future__ import annotations
from collections import Counter
import logging
import math
import uuid

from app.core.provenance import provenance

logger = logging.getLogger(__name__)

def build_trace(candidates: list[dict], selected: list[dict]) -> dict:
    selected_ids = {h["id"] for h in selected if h.get("id")}
    by_id = {h["id"]: h for h in candidates if h.get("id")}
    for hit in selected:
        if hit.get("id"):
            by_id.setdefault(hit["id"], hit)
    items = []
    for chunk_id, hit in by_id.items():
        meta = provenance(hit)
        try:
            score = float(hit.get("score") or 0)
        except (TypeError, ValueError):
            score = 0
        items.append({
            "chunk_id": chunk_id, "source_type": hit.get("source_type", "unknown"),
            "corpus_origin": meta.get("corpus_origin") or ("counsel" if hit.get("source_type") == "counsel" else "unknown"),
            "post_id": meta.get("post_id"), "posted_at": meta.get("posted_at"),
            "document_version": meta.get("document_version"),
            "retrieval_score": score if math.isfinite(score) else 0,
            "selected_for_context": chunk_id in selected_ids,
        })
    return {"trace_id": str(uuid.uuid4()), "items": items,
            "unidentified_selected": sum(not h.get("id") for h in selected),
            "semantics": "retrieved_and_supplied_not_proven_influence"}

def observe(config, candidates: list[dict], selected: list[dict]) -> dict:
    trace = build_trace(candidates, selected)
    observer = getattr(config, "retrieval_observer", None)
    if callable(observer):
        try:
            observer(trace)
        except Exception as exc:
            logger.warning("Retrieval observer failed: %s", type(exc).__name__)
    return trace

def summary(trace: dict) -> dict:
    candidates, selected = Counter(), Counter()
    for row in trace["items"]:
        origin = row["corpus_origin"]
        candidates[origin] += 1
        if row["selected_for_context"]:
            selected[origin] += 1
    return {"candidates": dict(candidates), "selected": dict(selected),
            "unidentified_selected": trace["unidentified_selected"]}
