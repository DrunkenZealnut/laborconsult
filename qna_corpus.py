"""Prepare redacted candidate chunks while keeping the existing embedding contract."""
from __future__ import annotations
import copy
import math
import re

from app.anonymize import anonymize
from app.core.provenance import provenance, is_nodong_qa
from pinecone_upload_contextual import chunk_document, contextualize_chunk
from qna_ingestion import digest

EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536
CHUNK_VERSION = "contextual-700-80-v1"
REDACTION_VERSION = "app-anonymize-v1"

def _redact(text: str) -> str:
    # External image URLs can contain upload identifiers; do not embed them.
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "[첨부 이미지]", text)
    return anonymize(text)

def prepare_document(record: dict) -> tuple[list[dict], list[str]]:
    title, category = _redact(record["title"]), _redact(record.get("category", ""))
    parts = ["## 질문\n" + _redact(record["question"])]
    for i, answer in enumerate(record["answers"], 1):
        parts.append(f"## 답변 {i}\n" + _redact(answer))
    chunks = chunk_document(record["post_id"], title, category, "\n\n".join(parts), "qa")
    if not chunks or any(not c["chunk_text"].strip() for c in chunks):
        raise ValueError("empty chunks")
    return chunks, [contextualize_chunk("", chunk) for chunk in chunks]

def make_vectors(record: dict, chunks: list[dict], embeddings: list[list[float]]) -> list[dict]:
    if len(chunks) != len(embeddings):
        raise ValueError("embedding cardinality mismatch")
    vectors = []
    for chunk, values in zip(chunks, embeddings):
        if len(values) != EMBED_DIM or any(not math.isfinite(v) for v in values):
            raise ValueError("invalid embedding dimension or values")
        meta = {
            "source_type": "qa", "source": "laborconsult", "corpus_origin": "nodong_qna",
            "post_id": record["post_id"], "url": record["canonical_url"],
            "title": chunk["title"][:200], "category": chunk["category"][:50],
            "section": chunk["section"][:100], "chunk_index": chunk["chunk_index"],
            "text": chunk["chunk_text"], "chunk_text": chunk["chunk_text"], "contextualized": False,
            "document_version": record["content_hash"], "chunk_hash": digest(chunk["chunk_text"]),
            "chunking_version": CHUNK_VERSION, "parse_version": record["parse_version"],
            "embedding_model": EMBED_MODEL, "embedding_dimensions": EMBED_DIM,
            "redaction_version": REDACTION_VERSION, "answer_status": record["status"],
        }
        if record.get("posted_at"):
            meta["posted_at"] = record["posted_at"]
            meta["date"] = record["posted_at"]
        for key in ["fetched_at", "answer_updated_at", "run_id"]:
            if record.get(key):
                meta[key] = record[key]
        vectors.append({"id": chunk["chunk_id"], "values": values, "metadata": meta})
    return vectors

def enrich_baseline(vector: dict, namespace: str) -> dict:
    """Adds verified provenance only; values and legacy text are preserved."""
    row = copy.deepcopy(vector)
    meta = row["metadata"]
    meta.update(provenance(meta))
    meta["namespace"] = namespace
    if is_nodong_qa(meta):
        # A single legacy chunk cannot determine a whole-document hash.
        # Snapshot builders replace this marker with the frozen corpus version.
        meta.setdefault("document_version", "legacy-unknown")
    return row
