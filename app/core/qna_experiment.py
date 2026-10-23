"""Explicit offline Q&A experiment routing; defaults preserve production paths."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re

from app.core.provenance import is_nodong_qa

class EvaluationIndex:
    def __init__(self, index, namespace: str, *, enabled: bool = True, frozen_namespaces: dict | None = None):
        if not re.fullmatch(r"qa-eval-[a-z0-9-]+", namespace):
            raise ValueError("invalid evaluation namespace")
        self.index, self.namespace, self.enabled = index, namespace, enabled
        self.frozen_namespaces = frozen_namespaces or {}
        if any(key not in {"counsel","laborlaw-v2"} or not re.fullmatch(r"qa-eval-[a-z0-9-]+",value)
               for key,value in self.frozen_namespaces.items()):
            raise ValueError("invalid frozen namespace mapping")

    def query(self, **kwargs):
        if kwargs.get("namespace") == "qa":
            kwargs["namespace"] = self.namespace
            if not self.enabled:
                # Missing origin belongs to other/unknown corpora; do not drop it.
                exclude = {"$or": [{"corpus_origin": {"$exists": False}},
                                   {"corpus_origin": {"$ne": "nodong_qna"}}]}
                old = kwargs.get("filter")
                kwargs["filter"] = {"$and": [old, exclude]} if old else exclude
        elif kwargs.get("namespace") in self.frozen_namespaces:
            kwargs["namespace"] = self.frozen_namespaces[kwargs["namespace"]]
        return self.index.query(**kwargs)

def include_sparse_document(doc: dict) -> bool:
    return os.getenv("QNA_EVAL_MODE") != "without" or not is_nodong_qa(doc)

def corpus_paths(defaults: list[Path]) -> list[Path]:
    override = os.getenv("QNA_EVAL_BM25_PATH")
    return [Path(override)] if override else defaults

def configure_index(index):
    namespace = os.getenv("QNA_EVAL_NAMESPACE")
    path = os.getenv("QNA_EVAL_BM25_PATH")
    mode = os.getenv("QNA_EVAL_MODE")
    if not any([namespace, path, mode]):
        return index
    if not namespace or not path or mode not in {"with", "without"}:
        raise ValueError("evaluation requires namespace, BM25 snapshot and with/without mode")
    if not Path(path).is_file():
        raise ValueError("evaluation BM25 snapshot is missing")
    if index is None:
        raise ValueError("evaluation vector index is unavailable")
    frozen = json.loads(os.getenv("QNA_EVAL_FIXED_NAMESPACES", "{}"))
    if not isinstance(frozen, dict) or set(frozen) != {"counsel", "laborlaw-v2"}:
        raise ValueError("evaluation requires frozen counsel and laborlaw-v2 namespaces")
    return EvaluationIndex(index, namespace, enabled=mode == "with", frozen_namespaces=frozen)
