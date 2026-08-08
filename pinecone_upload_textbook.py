#!/usr/bin/env python3
"""
"Win 노동법"(법학사, 공인노무사/5급공채/변호사시험 대비 수험서) marker 변환본을
Pinecone laborlaw-v2 네임스페이스에 업로드.

output_노동법교재/Win노동법_merged.md 단일 파일을 헤더 단위로 분할 → 청킹 →
임베딩 → 업로드. crawl/metadata 단계 없이 upload 스크립트 하나로 처리하는 점은
pinecone_upload_counsel.py와 동일한 관례를 따름.

사용법:
  python3 pinecone_upload_textbook.py              # 전체 업로드
  python3 pinecone_upload_textbook.py --dry-run    # 청킹만 (업로드 안 함)
  python3 pinecone_upload_textbook.py --reset      # 네임스페이스 초기화 후 재업로드
"""

import os
import re
import sys
import time
import argparse

from dotenv import load_dotenv
from openai import OpenAI
from pinecone import Pinecone

load_dotenv()

# ── 설정 ──────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_FILE = os.path.join(BASE_DIR, "output_노동법교재", "Win노동법_merged.md")

EMBED_MODEL = "text-embedding-3-small"
CHUNK_MAX = 700
CHUNK_OVERLAP = 80
EMBED_BATCH = 50
UPSERT_BATCH = 100
NAMESPACE = "laborlaw-v2"
SOURCE_TYPE = "textbook"
BOOK_TITLE = "Win 노동법(2025, 공인노무사·5급공채·변호사시험 대비)"

# 표지·목차 페이지(0~17)는 marker OCR이 표 구조를 깨뜨려 의미 없는 글자 스프뿐이라
# 코퍼스에서 전량 제외. 본문은 이 마커 다음 줄부터 시작한다.
BODY_START_MARKER = "<!-- page: 18 -->"

# 1건짜리 OCR 깨짐 — 범용 보정 로직 대신 정확한 문자열 치환으로 처리.
KNOWN_OCR_FIXES = {
    "# 기본원칙 高温 日本 日本 日本 日本 日本 日本 日本 日本 日本 日本 日本 日本 日本":
        "# 기본원칙",
}

_PAGE_COMMENT_RE = re.compile(r"<!--\s*page:\s*\d+\s*-->")
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)


# ── 텍스트 유틸 (기존 pinecone_upload_*.py와 동일 로직) ─────────────────────

def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_by_size(text: str, max_chars: int = CHUNK_MAX, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks = []
    start = 0
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


# ── 본문 파싱 ─────────────────────────────────────────────────────────────────

def load_body(filepath: str) -> str:
    """표지·목차를 제외한 본문만 로드하고 알려진 OCR 오류를 수정."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    marker_pos = content.find(BODY_START_MARKER)
    if marker_pos == -1:
        sys.exit(f"[오류] BODY_START_MARKER를 찾을 수 없습니다: {BODY_START_MARKER!r}")
    body = content[marker_pos + len(BODY_START_MARKER):]

    for broken, fixed in KNOWN_OCR_FIXES.items():
        body = body.replace(broken, fixed)

    body = _PAGE_COMMENT_RE.sub("", body)
    return body


def parse_sections(body: str) -> list[dict]:
    """헤더(#/##/###) 단위로 섹션 분할.

    Returns:
        [{"heading": "...", "text": "..."}, ...]
    """
    matches = list(_HEADING_RE.finditer(body))
    if not matches:
        return [{"heading": "본문", "text": clean_text(body)}] if body.strip() else []

    sections = []
    for i, m in enumerate(matches):
        heading = m.group(2).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        text = clean_text(body[start:end])
        if text:
            sections.append({"heading": heading, "text": text})
    return sections


# ── 청킹 ─────────────────────────────────────────────────────────────────────

def chunk_section(section: dict, heading_idx: int) -> list[dict]:
    chunks = []
    for idx, sub_text in enumerate(split_by_size(section["text"])):
        embed_text = f"제목: {BOOK_TITLE}\n섹션: {section['heading']}\n\n{sub_text}"
        chunks.append({
            "chunk_id": f"textbook_{heading_idx:04d}_chunk_{idx}",
            "chunk_index": idx,
            "embed_text": embed_text,
            "chunk_text": sub_text,
            "section": section["heading"],
        })
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
            print(f"  임베딩 재시도 ({attempt + 1}/3): {e}")
            time.sleep(2 ** attempt)
    return []


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Win 노동법 교재 Pinecone 업로드")
    parser.add_argument("--dry-run", action="store_true", help="청킹만 수행")
    parser.add_argument("--reset", action="store_true", help="네임스페이스 초기화 후 재업로드")
    args = parser.parse_args()

    if not os.path.exists(SOURCE_FILE):
        sys.exit(f"[오류] 원본 파일이 없습니다: {SOURCE_FILE}")

    openai_key = os.getenv("OPENAI_API_KEY")
    pinecone_key = os.getenv("PINECONE_API_KEY")

    if not args.dry_run and not openai_key:
        sys.exit("[오류] OPENAI_API_KEY가 설정되지 않았습니다.")
    if not args.dry_run and not pinecone_key:
        sys.exit("[오류] PINECONE_API_KEY가 설정되지 않았습니다.")

    openai_client = OpenAI(api_key=openai_key) if not args.dry_run else None

    index = None
    if not args.dry_run:
        from app.config import resolve_index_name
        pc = Pinecone(api_key=pinecone_key)
        index = pc.Index(resolve_index_name())

        if args.reset:
            print(f"네임스페이스 초기화: '{NAMESPACE}' (source_type='{SOURCE_TYPE}'만 대상 아님 — 전체 삭제 후 재업로드 필요 시 수동 확인)")
            index.delete(delete_all=True, namespace=NAMESPACE)
            time.sleep(1)

    body = load_body(SOURCE_FILE)
    sections = parse_sections(body)

    print(f"\n{'=' * 60}")
    print(f"Win 노동법 교재 업로드 {'(DRY RUN)' if args.dry_run else ''}")
    print(f"원본: {SOURCE_FILE}")
    print(f"네임스페이스: {NAMESPACE}  |  source_type: {SOURCE_TYPE}")
    print(f"파싱된 섹션 수: {len(sections)}")
    print(f"{'=' * 60}\n")

    total_chunks = 0
    all_vectors = []
    sample_chunks = []

    for heading_idx, section in enumerate(sections):
        chunks = chunk_section(section, heading_idx)
        if not chunks:
            continue
        total_chunks += len(chunks)

        if len(sample_chunks) < 8:
            sample_chunks.extend(chunks[:1])

        if args.dry_run:
            continue

        texts = [c["embed_text"] for c in chunks]
        embeddings = embed_texts(texts, openai_client)
        time.sleep(0.2)

        for chunk, emb in zip(chunks, embeddings):
            all_vectors.append({
                "id": chunk["chunk_id"],
                "values": emb,
                "metadata": {
                    "source_type": SOURCE_TYPE,
                    "title": BOOK_TITLE[:200],
                    "section": chunk["section"][:80],
                    "chunk_index": chunk["chunk_index"],
                    "chunk_text": chunk["chunk_text"][:900],
                    "text": chunk["chunk_text"][:900],
                },
            })

        if len(all_vectors) >= UPSERT_BATCH:
            index.upsert(vectors=all_vectors, namespace=NAMESPACE)
            all_vectors = []
            time.sleep(0.1)

    if all_vectors and not args.dry_run:
        index.upsert(vectors=all_vectors, namespace=NAMESPACE)

    print(f"총 청크 수: {total_chunks}\n")
    print("── 샘플 청크 미리보기 ──")
    for c in sample_chunks:
        preview = c["chunk_text"][:150].replace("\n", " ")
        print(f"[{c['chunk_id']}] 섹션: {c['section']}")
        print(f"  {preview}...\n")

    print(f"{'=' * 60}")
    print(f"=== 완료 {'(DRY RUN)' if args.dry_run else ''} ===")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
