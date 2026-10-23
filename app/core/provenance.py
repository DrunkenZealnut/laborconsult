"""Small shared provenance contract for vector, sparse and internal retrieval."""
from __future__ import annotations
from datetime import date
import re
from urllib.parse import urlparse

PROVENANCE_FIELDS = ("corpus_origin", "post_id", "posted_at", "answer_updated_at",
                     "fetched_at", "document_version", "url", "namespace", "answer_status")

def is_nodong_qa(meta: dict) -> bool:
    if meta.get("corpus_origin") == "nodong_qna":
        return True
    parsed = urlparse(meta.get("url") or meta.get("canonical_url") or "")
    return (parsed.netloc in {"www.nodong.kr", "nodong.kr"}
            and re.fullmatch(r"/qna/[0-9]+", parsed.path) is not None)

def provenance(meta: dict) -> dict:
    out = {key: meta[key] for key in PROVENANCE_FIELDS if meta.get(key)}
    if "posted_at" not in out and meta.get("date"):
        raw = str(meta["date"])[:10].replace(".", "-")
        try:
            out["posted_at"] = date.fromisoformat(raw).isoformat()
        except ValueError:
            pass
    if is_nodong_qa(meta):
        out["corpus_origin"] = "nodong_qna"
        match = re.search(r"/qna/([0-9]+)(?:$|[?#])", meta.get("url", ""))
        if match:
            out.setdefault("post_id", match[1])
    return out
