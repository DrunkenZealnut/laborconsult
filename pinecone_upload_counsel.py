#!/usr/bin/env python3
"""
민주노총 노동법률지원센터 상담 Q&A → Pinecone counsel 네임스페이스 업로드.

nodong_counsel/*.md의 Q&A 쌍을 파싱 → 청킹 → 임베딩 → Pinecone 업로드.

사용법:
  python3 pinecone_upload_counsel.py              # 전체 업로드
  python3 pinecone_upload_counsel.py --dry-run    # 청킹만 (업로드 안 함)
  python3 pinecone_upload_counsel.py --reset      # 네임스페이스 초기화 후 재업로드
"""

import os
import re
import sys
import json
import time
import argparse

from dotenv import load_dotenv
from openai import OpenAI
from pinecone import Pinecone

load_dotenv()

# ── 설정 ──────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COUNSEL_DIR = os.path.join(BASE_DIR, "nodong_counsel")
CACHE_FILE = os.path.join(COUNSEL_DIR, "_pairs_cache.json")

EMBED_MODEL = "text-embedding-3-small"
CHUNK_MAX = 700
CHUNK_OVERLAP = 80
EMBED_BATCH = 50
UPSERT_BATCH = 100
NAMESPACE = "counsel"

# ── 카테고리 매핑 (파일명 → 정규 카테고리명) ────────────────────────────────
FILE_TO_CATEGORY = {
    "4대보험실업급여등": "4대보험·실업급여",
    "근로계약_채용": "근로계약·채용",
    "근로시간_휴일_휴게": "근로시간·휴일·휴게",
    "기타": "기타",
    "노동조합가입": "노동조합 가입",
    "노동조합운영": "노동조합 운영",
    "부당노동행위": "부당노동행위",
    "비정규직": "비정규직",
    "산업재해": "산업재해",
    "여성": "여성",
    "임금_퇴직금": "임금·퇴직금",
    "쟁의행위": "쟁의행위",
    "징계_인사이동": "징계·인사이동",
    "해고_구조조정": "해고·구조조정",
}


# ── 텍스트 유틸 ───────────────────────────────────────────────────────────────

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


# ── Q&A 파싱 ─────────────────────────────────────────────────────────────────

def parse_qa_pairs(md_content: str) -> list[dict]:
    """마크다운에서 ## 단위로 Q&A 쌍 추출.

    Returns:
        [{"seq": 1, "title": "...", "question": "...", "answer": "..."}, ...]
    """
    # ## N. 제목 패턴으로 분할
    pattern = re.compile(r"^## (\d+)\.\s*(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(md_content))

    pairs = []
    for i, m in enumerate(matches):
        seq = int(m.group(1))
        title = m.group(2).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md_content)
        body = md_content[start:end].strip()

        # --- 구분선 제거
        body = re.sub(r"\n---\s*$", "", body).strip()

        # 질문/답변 분리
        question = ""
        answer = ""
        q_match = re.search(r"### 질문\s*\n(.*?)(?=### 답변|$)", body, re.DOTALL)
        a_match = re.search(r"### 답변\s*\n(.*)", body, re.DOTALL)
        if q_match:
            question = clean_text(q_match.group(1))
        if a_match:
            answer = clean_text(a_match.group(1))

        if question or answer:
            pairs.append({
                "seq": seq,
                "title": title,
                "question": question,
                "answer": answer,
            })

    return pairs


# ── 청킹 ─────────────────────────────────────────────────────────────────────

def chunk_qa_pair(
    pair: dict, category: str, q_seq: int | None, file_key: str
) -> list[dict]:
    """Q&A 쌍을 청크로 분할."""
    title = pair["title"]
    question = pair["question"]
    answer = pair["answer"]

    # 질문+답변 결합 텍스트
    combined = ""
    if question:
        combined += f"[질문]\n{question}\n\n"
    if answer:
        combined += f"[답변]\n{answer}"
    combined = combined.strip()

    if not combined or len(combined) < 10:
        return []

    # chunk_id 베이스
    if q_seq:
        id_base = f"counsel_{q_seq}"
    else:
        id_base = f"counsel_{file_key}_{pair['seq']}"

    chunks = []
    idx = 0
    for sub_text in split_by_size(combined):
        embed_text = f"카테고리: {category}\n제목: {title}\n\n{sub_text}"
        chunks.append({
            "chunk_id": f"{id_base}_chunk_{idx}",
            "chunk_index": idx,
            "embed_text": embed_text,
            "chunk_text": sub_text,
            "title": title,
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
            print(f"  임베딩 재시도 ({attempt + 1}/3): {e}")
            time.sleep(2 ** attempt)
    return []


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="노무사 상담 Q&A Pinecone 업로드")
    parser.add_argument("--dry-run", action="store_true", help="청킹만 수행")
    parser.add_argument("--reset", action="store_true", help="네임스페이스 초기화 후 재업로드")
    args = parser.parse_args()

    openai_key = os.getenv("OPENAI_API_KEY")
    pinecone_key = os.getenv("PINECONE_API_KEY")
    index_name = os.getenv("PINECONE_INDEX_NAME", "laborconsult-bestqna")

    if not openai_key:
        sys.exit("[오류] OPENAI_API_KEY가 설정되지 않았습니다.")
    if not args.dry_run and not pinecone_key:
        sys.exit("[오류] PINECONE_API_KEY가 설정되지 않았습니다.")

    openai_client = OpenAI(api_key=openai_key)

    index = None
    if not args.dry_run:
        pc = Pinecone(api_key=pinecone_key)
        index = pc.Index(index_name)

    # 네임스페이스 초기화
    if args.reset and not args.dry_run:
        print(f"네임스페이스 초기화: '{NAMESPACE}'")
        try:
            index.delete(delete_all=True, namespace=NAMESPACE)
            time.sleep(1)
        except Exception as e:
            print(f"  초기화 실패 (무시): {e}")

    # _pairs_cache.json 로드
    cache_map = {}  # title → {q_seq, category}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
        for item in cache_data:
            cache_map[item["title"]] = {
                "q_seq": item["q_seq"],
                "category": item.get("category", ""),
            }
        print(f"캐시 로드: {len(cache_map)}건")

    # .md 파일 처리
    md_files = sorted([
        f for f in os.listdir(COUNSEL_DIR)
        if f.endswith(".md") and not f.startswith("_")
    ])

    print(f"\n{'=' * 60}")
    print(f"노무사 상담 Q&A 업로드 {'(DRY RUN)' if args.dry_run else ''}")
    print(f"인덱스: {index_name}  |  네임스페이스: {NAMESPACE}")
    print(f"대상 파일: {len(md_files)}개")
    print(f"{'=' * 60}\n")

    total_pairs = 0
    total_chunks = 0
    all_vectors = []
    category_counts = {}

    for md_file in md_files:
        filepath = os.path.join(COUNSEL_DIR, md_file)
        file_key = os.path.splitext(md_file)[0]
        file_category = FILE_TO_CATEGORY.get(file_key, file_key)

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        pairs = parse_qa_pairs(content)
        if not pairs:
            continue

        total_pairs += len(pairs)
        category_counts[file_category] = len(pairs)

        for pair in pairs:
            # 캐시에서 q_seq, category 조회
            cached = cache_map.get(pair["title"])
            q_seq = cached["q_seq"] if cached else None
            category = cached["category"] if cached and cached["category"] else file_category

            chunks = chunk_qa_pair(pair, category, q_seq, file_key)
            if not chunks:
                continue
            total_chunks += len(chunks)

            if args.dry_run:
                continue

            # 임베딩
            texts = [c["embed_text"] for c in chunks]
            embeddings = embed_texts(texts, openai_client)
            time.sleep(0.2)

            # 벡터 구성
            for chunk, emb in zip(chunks, embeddings):
                all_vectors.append({
                    "id": chunk["chunk_id"],
                    "values": emb,
                    "metadata": {
                        "source_type": "counsel",
                        "title": chunk["title"][:200],
                        "category": category[:50],
                        "section": "Q&A",
                        "chunk_index": chunk["chunk_index"],
                        "chunk_text": chunk["chunk_text"][:900],
                        "text": chunk["chunk_text"][:900],
                    },
                })

            # 배치 upsert
            if len(all_vectors) >= UPSERT_BATCH:
                index.upsert(vectors=all_vectors, namespace=NAMESPACE)
                all_vectors = []
                time.sleep(0.1)

        print(f"  {md_file}: {len(pairs)} Q&A → {file_category}")

    # 남은 벡터 upsert
    if all_vectors and not args.dry_run:
        index.upsert(vectors=all_vectors, namespace=NAMESPACE)

    # 결과 출력
    print(f"\n{'=' * 60}")
    print(f"=== 완료 {'(DRY RUN)' if args.dry_run else ''} ===")
    print(f"총 Q&A: {total_pairs}건")
    print(f"총 청크: {total_chunks}개")
    print(f"\n카테고리별:")
    for cat, cnt in sorted(category_counts.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {cnt}건")

    if not args.dry_run and index:
        time.sleep(2)
        stats = index.describe_index_stats()
        ns = stats.namespaces.get(NAMESPACE)
        print(f"\nPinecone {NAMESPACE}: {ns.vector_count:,}개 벡터" if ns else f"\nPinecone {NAMESPACE}: 없음")

    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
