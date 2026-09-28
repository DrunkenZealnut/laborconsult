"""공유 인덱스 → 전용 인덱스 이전 (pinecone-index-separation).

`semiconductor-lithography`는 타 프로젝트 11개 NS(34,561벡터)와 공유하는 인덱스라
우리 쪽 작업 실수가 남의 프로덕션을 지울 수 있다(CLAUDE.md "Pinecone 인덱스는 다른
프로젝트와 공유한다"). 검색 대상 3개 NS(`rag.NS_GROUPS`)만 전용 인덱스로 **그대로 복사**한다
— 재임베딩 없음, 메타데이터 무변경(승인 근거 sha256이 메타 본문에 묶여 있다).

사용법:
    python3 migrate_index.py create     # 대상 인덱스 생성(삭제 보호 ON), 있으면 사양 대조만
    python3 migrate_index.py copy       # 복사 — 재실행하면 체크포인트에서 재개(upsert는 멱등)
    python3 migrate_index.py verify     # V1 벡터 수 · V2 ID 집합 · V3 표본 값/메타 · V4 official
    python3 migrate_index.py compare    # V5 고정 평가 질의 top-5 일치율(OpenAI 임베딩 필요, ≥95%)

주의 셋(전부 조용히 실패한다):
- **`list()`가 주는 것은 문자열이 아니라 `ListItem`이다.** 그대로 `fetch(ids=...)`에 넘기면
  예외 없이 0건이 온다(2026-09-27 실측 — `build_bm25_corpus.py` 주석의 "list→fetch 0건"도
  이것으로 보인다). `.id`로 풀면 정상 동작하지만 처리량 이득은 없어(부하 중 99건 39초)
  열거는 `fetch_by_metadata(chunk_index >= 0)`를 쓴다. 이 필터가 전량을 덮는 근거는
  BM25 코퍼스 82,184건 = 3개 NS 벡터 수 합계(같은 필터로 만들었다).
- 처리량은 서버 쪽이 병목이다(순차 6.5건/s, 8스트림 병렬도 ~8건/s → 약 3시간). NS × chunk_index 구간
  (0/1/2/≥3 — 서로소이고 합집합이 전체)으로 나눠 병렬 스트림으로 돈다.
- 원천 인덱스명은 env가 아니라 **상수**다. 전환 후 `PINECONE_INDEX_NAME`이 새 인덱스를
  가리키면 `resolve_index_name()`을 쓰는 코드는 대상을 원천으로 착각해 자기 자신에 복사한다.

`pc.delete_index()`는 쓰지 않는다. 구 NS 정리는 관찰 기간 뒤 NS 단위 delete로 따로 한다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env", override=True)

from pinecone import Pinecone, ServerlessSpec  # noqa: E402

from app.core.rag import NS_GROUPS  # noqa: E402

SOURCE_INDEX = "semiconductor-lithography"
DEFAULT_TARGET = "laborconsult"
DIMENSION = 1536
METRIC = "cosine"
NAMESPACES = [ns for group in NS_GROUPS for ns in group]
PARTITIONS = {"c0": {"$eq": 0}, "c1": {"$eq": 1}, "c2": {"$eq": 2}, "c3+": {"$gte": 3}}
PAGE_LIMIT = 100
TIMEOUT = 180.0
ATTEMPTS = 4
WORKERS = 8
STATE = Path("output_index_migration/_checkpoint.json")

_lock = threading.Lock()


def _pc() -> Pinecone:
    return Pinecone(api_key=os.environ["PINECONE_API_KEY"], timeout=TIMEOUT)


def _retry(fn, label):
    for attempt in range(ATTEMPTS - 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — 네트워크 일시 오류는 같은 커서로 재시도
            wait = 2 ** attempt
            print(f"  [{label}] 재시도 {attempt + 1}/{ATTEMPTS - 1} ({wait}s): {e}", flush=True)
            time.sleep(wait)
    return fn()


def _load_state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def _save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    tmp.replace(STATE)


def create(target: str) -> None:
    pc = _pc()
    if target == SOURCE_INDEX:
        sys.exit("대상이 원천과 같다")
    names = [i.name for i in pc.list_indexes()]
    if target not in names:
        pc.create_index(name=target, dimension=DIMENSION, metric=METRIC,
                        spec=ServerlessSpec(cloud="aws", region="us-east-1"),
                        deletion_protection="enabled")
        print(f"생성: {target}")
    d = pc.describe_index(target)
    problems = [f"{k}={v}" for k, v, want in [
        ("dimension", d.dimension, DIMENSION), ("metric", d.metric, METRIC),
        ("deletion_protection", d.deletion_protection, "enabled")] if v != want]
    if problems:
        sys.exit(f"사양 불일치: {problems}")
    print(f"OK {target}: {d.dimension}d {d.metric} protection={d.deletion_protection}")


def _copy_stream(src, dst, ns: str, part: str, state: dict) -> int:
    key = f"{ns}|{part}"
    with _lock:
        entry = state.setdefault(key, {"token": None, "copied": 0, "done": False})
    if entry["done"]:
        return entry["copied"]
    while True:
        resp = _retry(lambda: src.fetch_by_metadata(
            filter={"chunk_index": PARTITIONS[part]}, namespace=ns, limit=PAGE_LIMIT,
            pagination_token=entry["token"], timeout=TIMEOUT), key)
        vectors = [{"id": vid, "values": list(v.values), "metadata": v.metadata or {}}
                   for vid, v in resp.vectors.items()]
        bad = [v["id"] for v in vectors if len(v["values"]) != DIMENSION]
        if bad:
            raise RuntimeError(f"[{key}] 값이 없는 벡터: {bad[:3]}")
        if vectors:
            _retry(lambda: dst.upsert(vectors=vectors, namespace=ns), key)
        token = resp.pagination.next if resp.pagination else None
        # 커서는 upsert 성공 뒤에만 전진 — 중단 시 같은 페이지를 다시 쓴다(멱등).
        with _lock:
            entry["copied"] += len(vectors)
            entry["token"] = token
            entry["done"] = not token
            _save_state(state)
        if not token:
            print(f"  [{key}] 완료 {entry['copied']:,}", flush=True)
            return entry["copied"]


def copy(target: str) -> None:
    pc = _pc()
    src, dst = pc.Index(SOURCE_INDEX), pc.Index(target)
    state = _load_state()
    streams = [(ns, part) for ns in NAMESPACES for part in PARTITIONS]
    stop = threading.Event()

    def progress():
        while not stop.wait(60):
            with _lock:
                total = sum(e["copied"] for e in state.values())
                done = sum(e["done"] for e in state.values())
            print(f"  … {total:,}건 · 스트림 {done}/{len(streams)} 완료", flush=True)

    threading.Thread(target=progress, daemon=True).start()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {pool.submit(_copy_stream, src, dst, ns, part, state): (ns, part)
                for ns, part in streams}
        for f in as_completed(futs):
            f.result()
    stop.set()
    print(f"복사 완료: {sum(e['copied'] for e in state.values()):,}건")


def _list_ids(index, ns: str) -> set[str]:
    ids: set[str] = set()
    for page in index.list(namespace=ns, limit=99):
        ids.update(getattr(item, "id", item) for item in page)  # ListItem → str
    return ids


def verify(target: str) -> None:
    pc = _pc()
    src, dst = pc.Index(SOURCE_INDEX), pc.Index(target)
    s_stats, d_stats = src.describe_index_stats(), dst.describe_index_stats()
    ok = True
    for ns in NAMESPACES:
        s = s_stats.namespaces[ns].vector_count
        d = d_stats.namespaces[ns].vector_count if ns in d_stats.namespaces else 0
        print(f"V1 {ns}: 원천 {s:,} / 대상 {d:,} {'✅' if s == d else '❌'}")
        ok &= s == d
    extra = set(d_stats.namespaces) - set(NAMESPACES)
    print(f"V1 대상에 여분 NS 없음: {'✅' if not extra else '❌ ' + str(extra)}")
    ok &= not extra

    for ns in NAMESPACES:
        s_ids, d_ids = _list_ids(src, ns), _list_ids(dst, ns)
        miss, more = s_ids - d_ids, d_ids - s_ids
        print(f"V2 {ns}: 누락 {len(miss)} · 초과 {len(more)} "
              f"{'✅' if not miss and not more else '❌ ' + str(sorted(miss | more)[:5])}")
        ok &= not miss and not more

    # V3 — 원천은 fetch(ids)가 0건이라 원천 페이지를 기준으로 대상에서 조회해 대조한다.
    for ns in NAMESPACES:
        checked = mismatched = 0
        for part in PARTITIONS:
            resp = src.fetch_by_metadata(filter={"chunk_index": PARTITIONS[part]}, namespace=ns,
                                         limit=50, timeout=TIMEOUT)
            got = dst.fetch(ids=list(resp.vectors), namespace=ns).vectors
            for vid, v in resp.vectors.items():
                checked += 1
                t = got.get(vid)
                if t is None or list(t.values) != list(v.values) or t.metadata != v.metadata:
                    mismatched += 1
        print(f"V3 {ns}: 표본 {checked}건 중 불일치 {mismatched} {'✅' if not mismatched else '❌'}")
        ok &= mismatched == 0 and checked > 0

    probe = [0.0] * DIMENSION
    probe[0] = 1.0
    counts = []
    for index in (src, dst):
        r = index.query(vector=probe, top_k=100, namespace="laborlaw-v2",
                        filter={"official": True}, include_metadata=False)
        counts.append(len(r.matches))
    print(f"V4 official=True: 원천 {counts[0]} / 대상 {counts[1]} "
          f"{'✅' if counts[0] == counts[1] > 0 else '❌'}")
    ok &= counts[0] == counts[1] > 0
    print("전체 통과" if ok else "실패 항목 있음 — 전환 금지")
    sys.exit(0 if ok else 1)


def compare(target: str) -> None:
    """V5 — 같은 질의 벡터로 두 인덱스의 NS별 top-5 ID를 대조한다. 값이 같으면 순위도 같아야
    하지만 ANN 근사라 동점 부근에서 흔들릴 수 있어 95%를 기준으로 둔다."""
    from openai import OpenAI

    from app.config import EMBED_MODEL
    queries = [q["query"] for q in json.loads(
        Path("data/eval_retrieval_queries.json").read_text())["queries"]][:20]
    vecs = [e.embedding for e in OpenAI().embeddings.create(model=EMBED_MODEL, input=queries).data]
    pc = _pc()
    src, dst = pc.Index(SOURCE_INDEX), pc.Index(target)
    same = total = 0
    for vec in vecs:
        for ns in NAMESPACES:
            a = [m.id for m in src.query(vector=vec, top_k=5, namespace=ns).matches]
            b = [m.id for m in dst.query(vector=vec, top_k=5, namespace=ns).matches]
            same += len(set(a) & set(b))
            total += len(a)
    rate = same / total if total else 0.0
    print(f"V5 top-5 일치율: {same}/{total} = {rate:.1%} {'✅' if rate >= 0.95 else '❌'}")
    sys.exit(0 if rate >= 0.95 else 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["create", "copy", "verify", "compare"])
    ap.add_argument("--target", default=DEFAULT_TARGET)
    args = ap.parse_args()
    {"create": create, "copy": copy, "verify": verify, "compare": compare}[args.action](args.target)


if __name__ == "__main__":
    main()
