"""인용 판례와 질문의 쟁점 관련성 판정 (kin-answer-accuracy P1-4).

`citation_validator.validate_response_citations`는 "번호가 컨텍스트 어딘가에 있는가"만 본다.
지식iN 검증(2026-10-02)에서 그 기준을 통과한 두 유형이 문제가 됐다.

- **쟁점이 다른 판례 자체**: 2018두63235(공무원 고용보험 가입 시기)가 일반 수급요건의 직접
  판례로 실렸다. 그 판례 문서가 검색됐기 때문에 유효로 판정됐다 → `low_relevance`.
- **다른 글이 언급한 번호**: 상담글 본문에 적힌 번호도 화이트리스트에 오른다. 원문을
  확인하지 않은 2차 인용이다 → `secondhand`.

판정은 번호가 화이트리스트에 들어온 **경로**로 갈린다. 그 hit 자체가 해당 판례(title·case_no에
번호)면 질문과 본문의 임베딩 유사도를 잰다. 본문에만 번호가 있으면 2차 인용이다.

기본 모드는 `monitor`(기록만)다. 임계를 잘못 잡으면 정당한 판례가 지워지고, 오억제가
오탐지보다 비싸다. 임계는 fixture 실측으로 정한 뒤 `enforce`로 전환한다(Design §4.3).
"""

from __future__ import annotations

import logging
import math
import os
import re

logger = logging.getLogger(__name__)

MAX_TARGETS = 6
_TEXT_CHARS = 1500
_QUERY_CHARS = 2000
_STALE_NOTE_RE = re.compile(r"^\[구 기준 주의[^\n]*\n", re.M)


def mode() -> str:
    value = os.getenv("CITATION_RELEVANCE_MODE", "monitor").strip().lower()
    return value if value in {"off", "monitor", "enforce"} else "monitor"


def threshold() -> float:
    try:
        return float(os.getenv("CITATION_RELEVANCE_MIN", "0.30"))
    except ValueError:
        return 0.30


def _norm_key(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def classify_paths(keys: list[str], hits: list[dict]) -> dict[str, dict]:
    """번호별 판정 경로. {key: {"path": "primary"|"secondhand", "text": str}}.

    primary: 그 hit의 title·case_no에 번호가 있다(= hit 자체가 그 판례).
    secondhand: 본문(chunk_text)에만 있다 — 상담글뿐 아니라 법제처 판례·NLRC·그래프 텍스트
    블록 안의 번호도 여기에 든다(블록 단위라 그 판례 자체인지 구분할 수 없다). 어디에도
    없으면 결과에서 뺀다.
    """
    out: dict[str, dict] = {}
    for key in keys:
        primary = None
        mentioned = False
        for h in hits:
            head = _norm_key(h.get("title", "")) + "|" + _norm_key(h.get("case_no", ""))
            if key in head:
                primary = h
                break
            if key in _norm_key(h.get("chunk_text", "")):
                mentioned = True
        if primary is not None:
            # 폐기 기준 주석([구 기준 주의 …])은 판례 본문이 아니다 — 남기면 유사도가 주석 쪽으로 끌린다.
            body = _STALE_NOTE_RE.sub("", primary.get("chunk_text") or "")
            out[key] = {"path": "primary", "text": body[:_TEXT_CHARS]}
        elif mentioned:
            out[key] = {"path": "secondhand", "text": ""}
    return out


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def assess(query: str, valid_keys: list[str], hits: list[dict], config) -> dict[str, dict]:
    """{key: {"verdict": relevant|low_relevance|secondhand, "sim": float|None}}.

    실패는 fail-open — 빈 dict(판정 없음)를 돌려 기존 동작을 유지한다.
    """
    if mode() == "off" or not valid_keys or not query:
        return {}
    try:
        keys = list(dict.fromkeys(valid_keys))[:MAX_TARGETS]
        paths = classify_paths(keys, hits)
        result: dict[str, dict] = {
            k: {"verdict": "secondhand", "sim": None}
            for k, v in paths.items() if v["path"] == "secondhand"
        }
        primary = [(k, v["text"]) for k, v in paths.items()
                   if v["path"] == "primary" and v["text"].strip()]
        if primary:
            resp = config.openai_client.with_options(timeout=10.0, max_retries=0).embeddings.create(
                model=config.embed_model,
                input=[query[:_QUERY_CHARS]] + [t for _, t in primary])
            vecs = [d.embedding for d in sorted(resp.data, key=lambda x: x.index)]
            if len(vecs) != len(primary) + 1:
                logger.warning("인용 관련성: 임베딩 수 불일치 %d != %d", len(vecs), len(primary) + 1)
                return result
            limit = threshold()
            for (k, _), v in zip(primary, vecs[1:]):
                sim = round(_cosine(vecs[0], v), 3)
                result[k] = {"verdict": "relevant" if sim >= limit else "low_relevance", "sim": sim}
        if result:
            logger.info("인용 관련성(%s): %s", mode(), result)
        return result
    except Exception as e:  # 판정 실패가 답변을 막지 않는다
        logger.warning("인용 관련성 판정 실패 (무시): %s", e)
        return {}


def enforcement_targets(verdicts: dict[str, dict]) -> dict[str, list[str]]:
    """enforce 모드에서 교정할 번호를 사유별로 묶는다. monitor/off면 빈 dict."""
    if mode() != "enforce":
        return {}
    out: dict[str, list[str]] = {}
    for key, v in verdicts.items():
        if v.get("verdict") in ("low_relevance", "secondhand"):
            out.setdefault(v["verdict"], []).append(key)
    return out
