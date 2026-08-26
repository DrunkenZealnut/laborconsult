#!/usr/bin/env python3
"""훈령·예규·고시·지침 → Pinecone laborlaw-v2 업로드 (source_type="regulation").

설계: docs/02-design/features/legal-corpus-coverage.design.md §5

**왜 필요한가.** `source_type="regulation"`이 프로덕션에 **0건**인데,
`rag.py::LEGAL_PROMOTE_SOURCES`와 T1 공공저작물 쿼터가 이미 그것을 대상에
넣고 있다 — 뒷받침 문서가 없는 죽은 멤버다. 로컬에 파싱까지 끝난 161건이
적재된 적 없이 방치돼 있었다.

**`pinecone_upload_legal.py`를 복사하지 않는 이유**: 그쪽은 `regulation`이라는
이름의 **프로덕션이 읽지 않는 네임스페이스**에 쓴다(외부감사 H2). 같은
source_type이라도 적재 대상이 다르다 — 여기는 `laborlaw-v2`다.

저작권: 훈령·예규·고시는 저작권법 제7조 비보호 대상이라 노출 가드가 불요하다
(판례·행정해석과 같은 취급). 해설서 가드 G1~G6의 대상이 아니다.

사용법:
  python3 pinecone_upload_regulations.py --dry-run   # 청킹 검증
  python3 pinecone_upload_regulations.py             # 업로드
  python3 pinecone_upload_regulations.py --limit 20  # 부분 검증
  python3 pinecone_upload_regulations.py --allow-large-prune  # ID 규격 변경 시
"""
from __future__ import annotations

import os
import re
import sys
import time
import argparse
import unicodedata

from dotenv import load_dotenv

from vector_ledger import VectorLedger

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
            override=True)

# ── 설정 ──────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_DIR = os.path.join(BASE_DIR, "output_훈령예규고시지침")
UPLOADED_IDS_FILE = os.path.join(SOURCE_DIR, "_uploaded_ids.json")

# 청킹·임베딩 유틸은 court 업로더가 단일 출처다 — 복사하면 드리프트가 생긴다
# (외부감사 M1: legal의 NFD 픽스가 contextual에 3.5개월간 전파되지 않았다).
from pinecone_upload_court_precedents import (   # noqa: E402
    CHUNK_MAX, UPSERT_BATCH, clean_text, split_by_size, embed_texts,
)

NAMESPACE = "laborlaw-v2"     # rag.py::NS_GROUP_LAW가 읽는 유일한 법령 NS
SOURCE_TYPE = "regulation"    # rag.py 라벨 맵에 "훈령/예규"로 이미 존재

# 파일명 앞 숫자 = nodong.kr 게시물 번호. 사건번호가 아니라 순수 숫자라
# court의 NFD·부호 매핑 문제가 없다(그래도 NFC는 건다 — macOS 파일명 규약).
_POST_ID_RE = re.compile(r"^(\d+)_")


def extract_post_id(filename: str) -> str | None:
    return (m.group(1) if (m := _POST_ID_RE.match(
        unicodedata.normalize("NFC", filename))) else None)


def make_vector_id(post_id: str, idx: int) -> str:
    """결정적 ID — 재실행 시 upsert가 덮어쓴다.

    청크 수가 **줄면** 이전 벡터가 남으므로 원장(_LEDGER)이 차집합을 지운다.
    """
    return f"{SOURCE_TYPE}_{post_id}_chunk_{idx}"


_LEDGER = VectorLedger(
    UPLOADED_IDS_FILE,
    group_re=re.compile(r"^\d+$"),
    id_re_for=lambda pid: re.compile(rf"^{SOURCE_TYPE}_{re.escape(pid)}_chunk_\d+$"),
)


# ── 마크다운 파싱 ─────────────────────────────────────────────────────────────

_META_ROW_RE = re.compile(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|", re.M)
_LINK_RE = re.compile(r"\[(.+?)\]\((.+?)\)")


def parse_meta(md: str) -> dict:
    """상단 메타 테이블 → dict.

    본문 표까지 훑지 않도록 **구분선(---) 이전만** 본다 — 전체를 훑으면 본문에
    표가 있는 문서에서 뒤쪽 값이 분류·작성일을 덮어쓴다(외부감사 L8과 같은
    실패 모드).
    """
    head = md.split("\n---\n", 1)[0]
    meta = {}
    for m in _META_ROW_RE.finditer(head):
        key, val = m.group(1).strip(), m.group(2).strip()
        if key in ("항목", "---", ""):
            continue
        if link := _LINK_RE.search(val):
            val = link.group(2)
        meta[key] = val
    return meta


def extract_body(md: str) -> str:
    """메타 테이블 이후 본문. 첫 `---` 구분선 뒤 전체를 쓴다."""
    parts = md.split("\n---\n", 1)
    return clean_text(parts[1] if len(parts) > 1 else md)


def parse_doc(path: str) -> dict | None:
    filename = os.path.basename(path)
    post_id = extract_post_id(filename)
    if not post_id:
        return None
    with open(path, encoding="utf-8") as f:
        md = unicodedata.normalize("NFC", f.read())

    title_m = re.search(r"^#\s+(.+)$", md, re.M)
    title = title_m.group(1).strip() if title_m else os.path.splitext(filename)[0]
    meta = parse_meta(md)
    body = extract_body(md)
    if len(body) < 30:            # 본문이 사실상 없는 문서
        return None
    return {
        "post_id": post_id,
        "title": title,
        "category": meta.get("분류", ""),     # 훈령/예규/고시/지침
        "date": meta.get("작성일", ""),
        "url": meta.get("원문", ""),
        "body": body,
    }


def chunk_doc(doc: dict) -> list[dict]:
    """본문을 크기 기준으로 청킹.

    판례(court)와 달리 섹션 화이트리스트가 없다 — 훈령·고시는 문서 구조가
    제각각이고 전문 자체가 규범 내용이라 버릴 부분이 없다.

    분류(훈령/예규/고시/지침)를 embed_text와 저장 텍스트 양쪽에 얹는다 —
    "고시"·"지침" 같은 문서 종류가 질의어로 자주 쓰이고, BM25는 metadata의
    text 필드를 색인하기 때문이다(court의 쟁점 태깅과 같은 이유).
    """
    cat = doc.get("category") or ""
    prefix = f"[{cat}] " if cat else ""
    chunks: list[dict] = []
    for idx, sub in enumerate(split_by_size(doc["body"], CHUNK_MAX)):
        chunks.append({
            "vector_id": make_vector_id(doc["post_id"], idx),
            "chunk_index": idx,
            "section": cat or "본문",
            "embed_text": (f"{cat} {doc['title']}\n"
                           f"시행일: {doc['date']}\n\n{sub}").strip(),
            "chunk_text": prefix + sub,
        })
    return chunks


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="훈령·예규·고시 Pinecone 업로드")
    parser.add_argument("--dry-run", action="store_true", help="청킹만 수행")
    parser.add_argument("--limit", type=int, help="처리할 최대 파일 수")
    parser.add_argument("--allow-large-prune", action="store_true",
                        help="고아 벡터가 현재 청크의 50%%를 넘어도 삭제 진행")
    args = parser.parse_args()

    if not os.path.isdir(SOURCE_DIR):
        sys.exit(f"[오류] 소스 디렉터리가 없습니다: {SOURCE_DIR}")

    md_files = []
    for root, _dirs, files in os.walk(SOURCE_DIR):
        for f in sorted(files):
            if f.endswith(".md") and not f.startswith("_"):
                md_files.append(os.path.join(root, f))
    md_files.sort()
    if args.limit:
        md_files = md_files[:args.limit]
    if not md_files:
        sys.exit(f"[오류] .md 파일이 없습니다: {SOURCE_DIR}")

    openai_client = index = None
    if not args.dry_run:
        from openai import OpenAI
        from pinecone import Pinecone
        from app.config import resolve_index_name
        if not (k := os.getenv("OPENAI_API_KEY")):
            sys.exit("[오류] OPENAI_API_KEY가 없습니다.")
        if not (pk := os.getenv("PINECONE_API_KEY")):
            sys.exit("[오류] PINECONE_API_KEY가 없습니다.")
        openai_client = OpenAI(api_key=k)
        index = Pinecone(api_key=pk).Index(resolve_index_name())

    print(f"\n{'=' * 62}")
    print(f"훈령·예규·고시 업로드 {'(DRY RUN)' if args.dry_run else ''}")
    print(f"소스: {SOURCE_DIR}  ({len(md_files)}개 파일)")
    print(f"네임스페이스: {NAMESPACE}  |  source_type: {SOURCE_TYPE}")
    print(f"{'=' * 62}\n")

    total_chunks = 0
    skipped: list[str] = []
    seen_ids: set[str] = set()
    ready: list[tuple[dict, list[dict]]] = []
    by_cat: dict[str, int] = {}

    for path in md_files:
        fn = os.path.basename(path)
        doc = parse_doc(path)
        if not doc:
            skipped.append(f"{fn} (post_id 없음 또는 본문 30자 미만)")
            continue
        chunks = chunk_doc(doc)
        if not chunks:
            skipped.append(f"{fn} (청크 0)")
            continue
        if dup := [c["vector_id"] for c in chunks if c["vector_id"] in seen_ids]:
            skipped.append(f"{fn} (벡터 ID 충돌: {dup[0]})")
            continue
        seen_ids.update(c["vector_id"] for c in chunks)
        total_chunks += len(chunks)
        by_cat[doc["category"] or "미분류"] = by_cat.get(doc["category"] or "미분류", 0) + 1
        ready.append((doc, chunks))

    print(f"처리 파일: {len(ready)}개  |  총 청크: {total_chunks}개")
    print(f"분류별: {', '.join(f'{k} {v}' for k, v in sorted(by_cat.items()))}")
    if skipped:
        print(f"\n스킵 {len(skipped)}건:")
        for s in skipped[:15]:
            print(f"  - {s}")
        if len(skipped) > 15:
            print(f"  ... 외 {len(skipped) - 15}건")

    if args.dry_run:
        print("\n── 샘플 청크 ──")
        for doc, chunks in ready[:3]:
            c = chunks[0]
            print(f"[{c['vector_id']}] {c['section']}")
            print(f"  {c['chunk_text'][:110]}...\n")
        print(f"{'=' * 62}\n=== 완료 (DRY RUN) ===\n{'=' * 62}")
        return

    # 원장 기록은 upsert보다 **먼저** — 중간에 죽어도 적재분이 추적에 남는다.
    groups = {doc["post_id"]: [c["vector_id"] for c in chunks]
              for doc, chunks in ready}
    previous = _LEDGER.record(groups)
    print(f"\n벡터 ID {total_chunks}건 기록: {UPLOADED_IDS_FILE}\n")

    pending: list[dict] = []
    for i, (doc, chunks) in enumerate(ready, 1):
        embeddings = embed_texts([c["embed_text"] for c in chunks], openai_client)
        time.sleep(0.2)
        # zip은 길이가 다르면 남는 쪽을 조용히 버린다 — 결정적 ID라 재실행이
        # 안전하므로 즉시 중단이 맞다.
        if len(embeddings) != len(chunks):
            sys.exit(f"[오류] 임베딩 수 불일치: {len(embeddings)} != {len(chunks)} "
                     f"({doc['post_id']}) — 중단, 재실행으로 재개")
        for chunk, emb in zip(chunks, embeddings):
            pending.append({
                "id": chunk["vector_id"],
                "values": emb,
                "metadata": {
                    "source_type": SOURCE_TYPE,
                    "title": doc["title"][:200],
                    "section": chunk["section"],
                    "category": doc["category"][:20],
                    "date": doc["date"][:20],
                    "url": doc["url"][:200],
                    "post_id": doc["post_id"],
                    "chunk_index": chunk["chunk_index"],
                    "chunk_text": chunk["chunk_text"][:900],
                    "text": chunk["chunk_text"][:900],
                },
            })
        while len(pending) >= UPSERT_BATCH:
            index.upsert(vectors=pending[:UPSERT_BATCH], namespace=NAMESPACE)
            pending = pending[UPSERT_BATCH:]
            time.sleep(0.1)
        if i % 25 == 0 or i == len(ready):
            print(f"  진행: {i}/{len(ready)} 파일")

    if pending:
        index.upsert(vectors=pending, namespace=NAMESPACE)

    # 고아 정리는 업로드가 전부 성공한 뒤에만 — 중간 실패 시 삭제하면 아직
    # 올리지 못한 벡터를 지운다.
    _LEDGER.prune(groups, previous, index, NAMESPACE,
                  batch_size=UPSERT_BATCH,
                  allow_large=args.allow_large_prune,
                  label="훈령·예규 코퍼스")

    try:
        count = prev = None
        for _ in range(3):
            time.sleep(5)
            count = index.describe_index_stats().namespaces[NAMESPACE].vector_count
            if count == prev:
                break
            prev = count
        print(f"\n업로드 후 {NAMESPACE} 벡터 수: {count:,}")
    except Exception as e:
        print(f"\n[경고] 벡터 수 조회 실패: {e}")

    print(f"\n{'=' * 62}\n=== 완료 ===")
    print("⚠️ BM25 재빌드 필요: python3 build_bm25_corpus.py")
    print(f"{'=' * 62}")


if __name__ == "__main__":
    main()
