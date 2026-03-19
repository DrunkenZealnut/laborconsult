#!/usr/bin/env python3
"""
노동OK 임금(imgum) 게시글 → Pinecone 벡터 업로드

파이프라인:
  1. metadata_imgum.json 로드 (없으면 generate_metadata_imgum.py 자동 실행)
  2. 각 markdown 파일을 섹션 단위로 청킹
  3. OpenAI text-embedding-3-small 로 임베딩 생성
  4. Pinecone에 배치 upsert (인덱스: laborconsult-imgum)
  5. metadata_imgum.json의 chunk_count, upload_status 갱신

사용법:
  python3 pinecone_upload_imgum.py              # 전체 업로드
  python3 pinecone_upload_imgum.py --reset      # 인덱스 초기화 후 재업로드
  python3 pinecone_upload_imgum.py --pending    # pending 상태만 업로드
"""

import os
import re
import sys
import json
import time
import argparse
from datetime import datetime

from dotenv import load_dotenv
from openai import OpenAI
from pinecone import Pinecone, ServerlessSpec

load_dotenv()

# ── 설정 ──────────────────────────────────────────────────────────────────────
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR    = os.path.join(BASE_DIR, "output_imgum")
METADATA_FILE = os.path.join(BASE_DIR, "metadata_imgum.json")

EMBED_MODEL   = "text-embedding-3-small"
EMBED_DIM     = 1536
CHUNK_MAX     = 700
CHUNK_OVERLAP = 80

EMBED_BATCH   = 50
UPSERT_BATCH  = 100


# ── 텍스트 청킹 ───────────────────────────────────────────────────────────────

def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\\\n", "\n", text)
    text = re.sub(r"\\([*_\[\]()#!])", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_by_size(text: str, max_chars: int = CHUNK_MAX, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks = []
    start  = 0
    while start < len(text):
        end = min(start + max_chars, len(text))

        if end < len(text):
            for delimiter in ["\n\n", "\n", ". ", ", "]:
                pos = text.rfind(delimiter, start + max(overlap, 50), end)
                if pos > start:
                    end = pos + len(delimiter)
                    break

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= len(text):
            break

        start = end - overlap

    return chunks


def extract_body(md_content: str) -> str:
    match = re.search(r"^## 본문\s*\n\n(.*)", md_content, re.MULTILINE | re.DOTALL)
    if match:
        return clean_text(match.group(1))
    after_meta = re.sub(r"^.*?\n---\n\n", "", md_content, count=1, flags=re.DOTALL)
    return clean_text(after_meta)


def chunk_post(post_id: str, title: str, body: str) -> list[dict]:
    header_pat = re.compile(r"^(#{2,3})\s+(.+)$", re.MULTILINE)
    headers    = list(header_pat.finditer(body))

    sections: list[tuple[str, str]] = []

    if not headers or headers[0].start() > 0:
        pre = body[: headers[0].start() if headers else len(body)].strip()
        if pre:
            sections.append(("본문", pre))

    for i, h in enumerate(headers):
        section_name  = h.group(2).strip()
        content_start = h.end()
        content_end   = headers[i + 1].start() if i + 1 < len(headers) else len(body)
        content       = body[content_start:content_end].strip()
        if content:
            sections.append((section_name, content))

    chunks = []
    idx    = 0
    for section_name, content in sections:
        for sub_text in split_by_size(content):
            if not sub_text.strip():
                continue
            embed_text = f"제목: {title}\n섹션: {section_name}\n\n{sub_text}"
            chunks.append({
                "chunk_id":    f"{post_id}_chunk_{idx}",
                "chunk_index": idx,
                "section":     section_name,
                "embed_text":  embed_text,
                "chunk_text":  sub_text,
            })
            idx += 1

    if not chunks:
        for sub_text in split_by_size(body):
            embed_text = f"제목: {title}\n\n{sub_text}"
            chunks.append({
                "chunk_id":    f"{post_id}_chunk_{idx}",
                "chunk_index": idx,
                "section":     "본문",
                "embed_text":  embed_text,
                "chunk_text":  sub_text,
            })
            idx += 1

    return chunks


# ── 임베딩 ────────────────────────────────────────────────────────────────────

def embed_texts(texts: list[str], client: OpenAI) -> list[list[float]]:
    for attempt in range(3):
        try:
            resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
            return [d.embedding for d in sorted(resp.data, key=lambda x: x.index)]
        except Exception as e:
            if attempt == 2:
                raise
            print(f"  임베딩 재시도 ({attempt+1}/3): {e}")
            time.sleep(2 ** attempt)
    return []


def embed_all(chunks: list[dict], client: OpenAI) -> list[list[float]]:
    embeddings = []
    total = len(chunks)
    for i in range(0, total, EMBED_BATCH):
        batch = chunks[i : i + EMBED_BATCH]
        texts = [c["embed_text"] for c in batch]
        vecs  = embed_texts(texts, client)
        embeddings.extend(vecs)
        print(f"  임베딩: {min(i + EMBED_BATCH, total)}/{total}", end="\r")
        time.sleep(0.3)
    print()
    return embeddings


# ── Pinecone ──────────────────────────────────────────────────────────────────

def get_or_create_index(pc: Pinecone, index_name: str) -> any:
    existing_names = [idx.name for idx in pc.list_indexes()]
    if index_name not in existing_names:
        print(f"인덱스 생성: {index_name} (dim={EMBED_DIM}, metric=cosine, AWS us-east-1)")
        pc.create_index(
            name=index_name,
            dimension=EMBED_DIM,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
        for _ in range(30):
            if pc.describe_index(index_name).status["ready"]:
                break
            time.sleep(2)
        print("인덱스 생성 완료")
    else:
        print(f"기존 인덱스 사용: {index_name}")
    return pc.Index(index_name)


def build_pinecone_vector(chunk: dict, embedding: list[float], post_meta: dict) -> dict:
    return {
        "id":     chunk["chunk_id"],
        "values": embedding,
        "metadata": {
            "post_id":     post_meta["post_id"],
            "title":       post_meta["title"],
            "date":        post_meta["date"],
            "date_num":    post_meta["date_num"],
            "views":       post_meta["views"],
            "url":         post_meta["url"],
            "board":       "imgum",
            "section":     chunk["section"],
            "chunk_index": chunk["chunk_index"],
            "chunk_text":  chunk["chunk_text"][:900],
        },
    }


def upsert_vectors(index, vectors: list[dict]):
    total = len(vectors)
    for i in range(0, total, UPSERT_BATCH):
        batch = vectors[i : i + UPSERT_BATCH]
        index.upsert(vectors=batch)
        print(f"  upsert: {min(i + UPSERT_BATCH, total)}/{total}", end="\r")
        time.sleep(0.1)
    print()


# ── 메인 ──────────────────────────────────────────────────────────────────────

def load_metadata() -> dict:
    if not os.path.exists(METADATA_FILE):
        print("metadata_imgum.json이 없습니다. generate_metadata_imgum.py를 먼저 실행합니다...\n")
        import subprocess
        subprocess.run(
            [sys.executable, os.path.join(BASE_DIR, "generate_metadata_imgum.py")],
            check=True,
        )
    with open(METADATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_metadata(metadata: dict):
    metadata["last_upload"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with open(METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Pinecone imgum 업로드")
    parser.add_argument("--reset",   action="store_true", help="인덱스 초기화 후 전체 재업로드")
    parser.add_argument("--pending", action="store_true", help="pending 상태만 업로드")
    args = parser.parse_args()

    openai_key   = os.getenv("OPENAI_API_KEY")
    pinecone_key = os.getenv("PINECONE_API_KEY")
    index_name   = os.getenv("PINECONE_INDEX_NAME_IMGUM", "laborconsult-imgum")

    if not openai_key:
        sys.exit("[오류] OPENAI_API_KEY가 설정되지 않았습니다.")
    if not pinecone_key:
        sys.exit("[오류] PINECONE_API_KEY가 설정되지 않았습니다.")

    openai_client = OpenAI(api_key=openai_key)
    pc = Pinecone(api_key=pinecone_key)

    if args.reset:
        existing = [idx.name for idx in pc.list_indexes()]
        if index_name in existing:
            print(f"인덱스 삭제: {index_name}")
            pc.delete_index(index_name)
            time.sleep(3)
    index = get_or_create_index(pc, index_name)

    metadata = load_metadata()
    posts    = metadata["posts"]

    if args.pending:
        targets = [p for p in posts if p.get("upload_status") != "uploaded"]
        print(f"\n업로드 대상: {len(targets)}개 (pending/failed)")
    elif args.reset:
        for p in posts:
            p["upload_status"] = "pending"
            p["chunk_count"]   = 0
        targets = posts
        print(f"\n업로드 대상: {len(targets)}개 (전체 초기화)")
    else:
        targets = [p for p in posts if p.get("upload_status") != "uploaded"]
        if not targets:
            print("\n모든 게시글이 이미 업로드됨. --reset 또는 --pending 사용.")
            return
        print(f"\n업로드 대상: {len(targets)}개")

    print(f"인덱스: {index_name}  |  임베딩 모델: {EMBED_MODEL}\n")
    print("=" * 60)

    total_chunks = 0
    failed       = []

    for i, post_meta in enumerate(targets, 1):
        post_id  = post_meta["post_id"]
        title    = post_meta["title"]
        filename = post_meta["filename"]
        filepath = os.path.join(OUTPUT_DIR, filename)

        print(f"\n[{i}/{len(targets)}] {title[:50]}...")

        if not os.path.exists(filepath):
            print(f"  [스킵] 파일 없음: {filename}")
            post_meta["upload_status"] = "failed"
            failed.append(post_id)
            continue

        with open(filepath, "r", encoding="utf-8") as f:
            md_content = f.read()

        body = extract_body(md_content)
        if not body:
            print(f"  [스킵] 본문 없음")
            post_meta["upload_status"] = "failed"
            failed.append(post_id)
            continue

        chunks = chunk_post(post_id, title, body)
        if not chunks:
            print(f"  [스킵] 청크 생성 실패")
            post_meta["upload_status"] = "failed"
            failed.append(post_id)
            continue

        print(f"  청크: {len(chunks)}개  |  본문: {len(body):,}자")

        try:
            embeddings = embed_all(chunks, openai_client)
        except Exception as e:
            print(f"  [오류] 임베딩 실패: {e}")
            post_meta["upload_status"] = "failed"
            failed.append(post_id)
            continue

        vectors = [
            build_pinecone_vector(chunk, emb, post_meta)
            for chunk, emb in zip(chunks, embeddings)
        ]

        try:
            upsert_vectors(index, vectors)
        except Exception as e:
            print(f"  [오류] upsert 실패: {e}")
            post_meta["upload_status"] = "failed"
            failed.append(post_id)
            continue

        post_meta["chunk_count"]   = len(chunks)
        post_meta["upload_status"] = "uploaded"
        total_chunks += len(chunks)
        print(f"  완료 ✓")

    save_metadata(metadata)

    stats = index.describe_index_stats()

    print("\n" + "=" * 60)
    print(f"=== 업로드 완료 ===")
    print(f"성공: {len(targets) - len(failed)}개 / 실패: {len(failed)}개")
    print(f"총 벡터 수: {total_chunks:,}개")
    print(f"Pinecone 총 벡터: {stats.total_vector_count:,}개")
    print(f"인덱스: {index_name}")
    if failed:
        print(f"\n실패 post_id: {failed}")


if __name__ == "__main__":
    main()
