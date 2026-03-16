#!/usr/bin/env python3
"""
법률 데이터 → Pinecone 네임스페이스별 벡터 업로드

판례·행정해석·훈령/예규·상담사례 마크다운 파일을 청킹 → 임베딩 → Pinecone 업로드.
기존 pinecone_upload.py의 청킹/임베딩 로직을 재활용하되, 네임스페이스 분리.

사용법:
  python3 pinecone_upload_legal.py                     # 전체 업로드
  python3 pinecone_upload_legal.py --source precedent   # 판례만
  python3 pinecone_upload_legal.py --reset              # 네임스페이스 초기화 후 재업로드
  python3 pinecone_upload_legal.py --dry-run            # 청킹만 (업로드 안 함)
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

EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536
CHUNK_MAX = 700
CHUNK_OVERLAP = 80
EMBED_BATCH = 50
UPSERT_BATCH = 100

# ── 소스 정의 ─────────────────────────────────────────────────────────────────

LEGAL_SOURCES = [
    {
        "directory": "output_법원 노동판례",
        "namespace": "precedent",
        "source_type": "precedent",
        "label": "법원 판례",
    },
    {
        "directory": "output_노동부 행정해석",
        "namespace": "interpretation",
        "source_type": "interpretation",
        "label": "행정해석",
    },
    {
        "directory": "output_훈령예규고시지침",
        "namespace": "regulation",
        "source_type": "regulation",
        "label": "훈령/예규/고시",
    },
    {
        "directory": "output_legal_cases",
        "namespace": "legal_cases",
        "source_type": "legal_case",
        "label": "법률 상담사례",
    },
]


# ── 텍스트 유틸 (pinecone_upload.py에서 재활용) ──────────────────────────────

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
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            broke = False
            for delimiter in ["\n\n", "\n", ". ", ", "]:
                pos = text.rfind(delimiter, start + max(overlap, 50), end)
                if pos > start:
                    end = pos + len(delimiter)
                    broke = True
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = end - overlap
    return chunks


# ── 메타데이터 파싱 ───────────────────────────────────────────────────────────

def parse_md_metadata(md_content: str) -> dict:
    """마크다운 상단 메타 테이블 파싱.

    | 항목 | 내용 |
    | 분류 | 근로기준 |
    → {"분류": "근로기준", ...}
    """
    meta = {}
    for m in re.finditer(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|", md_content, re.MULTILINE):
        key = m.group(1).strip()
        val = m.group(2).strip()
        if key in ("항목", "---", ""):
            continue
        # URL 링크 처리: [url](url) → url
        link = re.search(r"\[(.+?)\]\((.+?)\)", val)
        if link:
            val = link.group(2)
        meta[key] = val
    return meta


def extract_title(md_content: str) -> str:
    """마크다운 첫 줄의 # 제목 추출."""
    m = re.match(r"^#\s+(.+)", md_content.strip())
    return m.group(1).strip() if m else ""


def extract_legal_body(md_content: str) -> str:
    """메타 테이블 제거 후 본문 추출."""
    # --- 구분선 이후 전체
    parts = md_content.split("\n---\n", 1)
    if len(parts) > 1:
        return clean_text(parts[1])
    # 구분선 없으면 메타 테이블 이후 (상담사례 등)
    # ## 이후 전체
    m = re.search(r"^## ", md_content, re.MULTILINE)
    if m:
        return clean_text(md_content[m.start():])
    return clean_text(md_content)


# 한글 → ASCII 매핑 (Pinecone ID는 ASCII만 허용)
_KR_TO_ASCII = {
    "다": "da", "두": "du", "도": "do", "가": "ga", "누": "nu",
    "나": "na", "마": "ma", "추": "chu", "재": "jae", "허": "heo",
}


def _korean_to_ascii(text: str) -> str:
    """한글 문자를 ASCII로 변환 (Pinecone ID용)."""
    for kr, en in _KR_TO_ASCII.items():
        text = text.replace(kr, en)
    return re.sub(r"[^\x00-\x7F]", "", text)


def extract_post_id(filepath: str, source_type: str) -> str:
    """파일명에서 post_id 추출 (Pinecone ID용 ASCII 변환 포함)."""
    basename = os.path.splitext(os.path.basename(filepath))[0]
    if source_type == "legal_case":
        # case_001_제목 → case_001
        m = re.match(r"(case_\d+)", basename)
        return m.group(1) if m else basename[:20]
    # 사건번호 패턴 (예: 2019다297496, 2017마5737) → ASCII 변환
    case_m = re.match(r"(\d{4}[다두도가누마재추허][A-Za-z가-힣]*\d+)", basename)
    if case_m:
        return _korean_to_ascii(case_m.group(1))
    # 기존 숫자ID 패턴 (예: 1219473_제목)
    m = re.match(r"(\d+)", basename)
    return m.group(1) if m else _korean_to_ascii(basename[:30])


# ── 청킹 ─────────────────────────────────────────────────────────────────────

def chunk_legal_doc(
    post_id: str, title: str, category: str, body: str, source_type: str
) -> list[dict]:
    """법률 문서를 섹션 단위로 청킹."""
    header_pat = re.compile(r"^(#{2,3})\s+(.+)$", re.MULTILINE)
    headers = list(header_pat.finditer(body))

    sections: list[tuple[str, str]] = []

    # 첫 헤더 이전 내용
    if not headers or headers[0].start() > 0:
        pre = body[:headers[0].start() if headers else len(body)].strip()
        if pre:
            sections.append(("본문", pre))

    for i, h in enumerate(headers):
        section_name = h.group(2).strip()
        content_start = h.end()
        content_end = headers[i + 1].start() if i + 1 < len(headers) else len(body)
        content = body[content_start:content_end].strip()
        if content:
            sections.append((section_name, content))

    chunks = []
    idx = 0
    for section_name, content in sections:
        for sub_text in split_by_size(content):
            if not sub_text.strip():
                continue
            embed_text = f"제목: {title}\n분류: {category}\n섹션: {section_name}\n\n{sub_text}"
            chunks.append({
                "chunk_id": f"{source_type}_{post_id}_chunk_{idx}",
                "chunk_index": idx,
                "section": section_name,
                "embed_text": embed_text,
                "chunk_text": sub_text,
            })
            idx += 1

    # 섹션 없으면 전체를 하나의 청크로
    if not chunks:
        for sub_text in split_by_size(body):
            embed_text = f"제목: {title}\n분류: {category}\n\n{sub_text}"
            chunks.append({
                "chunk_id": f"{source_type}_{post_id}_chunk_{idx}",
                "chunk_index": idx,
                "section": "본문",
                "embed_text": embed_text,
                "chunk_text": sub_text,
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


# ── Pinecone 벡터 ────────────────────────────────────────────────────────────

def build_legal_vector(
    chunk: dict, embedding: list[float], meta: dict, source_type: str
) -> dict:
    return {
        "id": chunk["chunk_id"],
        "values": embedding,
        "metadata": {
            "source_type": source_type,
            "title": meta.get("title", "")[:200],
            "category": meta.get("category", "")[:50],
            "date": meta.get("date", ""),
            "url": meta.get("url", ""),
            "section": chunk["section"][:100],
            "chunk_index": chunk["chunk_index"],
            "chunk_text": chunk["chunk_text"][:900],
        },
    }


# ── 단일 소스 업로드 ─────────────────────────────────────────────────────────

def upload_source(
    source_config: dict, index, openai_client: OpenAI, dry_run: bool = False
) -> dict:
    """단일 소스 디렉토리의 모든 마크다운 파일을 처리하여 업로드."""
    directory = os.path.join(BASE_DIR, source_config["directory"])
    namespace = source_config["namespace"]
    source_type = source_config["source_type"]
    label = source_config["label"]

    if not os.path.isdir(directory):
        print(f"  [스킵] 디렉토리 없음: {directory}")
        return {"files": 0, "chunks": 0, "errors": 0}

    # 재귀적으로 모든 .md 파일 수집 (인덱스/진행상황 파일 제외)
    md_files = []
    for root, dirs, files in os.walk(directory):
        for f in files:
            if f.endswith(".md") and not f.startswith("_"):
                md_files.append(os.path.join(root, f))
    md_files.sort()

    print(f"\n{'='*60}")
    print(f"[{label}] {len(md_files)}개 파일 → namespace='{namespace}'")
    print(f"{'='*60}")

    total_chunks = 0
    errors = 0
    all_vectors = []

    for i, filepath in enumerate(md_files, 1):
        try:
            with open(filepath, "r", encoding="utf-8") as fh:
                md_content = fh.read()
        except Exception as e:
            print(f"  [{i}] 파일 읽기 실패: {e}")
            errors += 1
            continue

        title = extract_title(md_content)
        meta_table = parse_md_metadata(md_content)
        post_id = extract_post_id(filepath, source_type)

        # 카테고리: 메타 테이블 또는 상위 디렉토리명
        category = meta_table.get("분류", "")
        if not category:
            parent_dir = os.path.basename(os.path.dirname(filepath))
            if parent_dir != os.path.basename(directory):
                category = parent_dir

        url = meta_table.get("원문", "")
        date_str = meta_table.get("작성일", "")

        body = extract_legal_body(md_content)
        if not body or len(body) < 20:
            continue

        chunks = chunk_legal_doc(post_id, title, category, body, source_type)
        if not chunks:
            continue

        doc_meta = {
            "title": title,
            "category": category,
            "url": url,
            "date": date_str,
        }

        if dry_run:
            total_chunks += len(chunks)
            if i <= 3 or i % 100 == 0:
                print(f"  [{i}/{len(md_files)}] {title[:40]}... → {len(chunks)} 청크")
            continue

        # 임베딩
        texts = [c["embed_text"] for c in chunks]
        embeddings = []
        for batch_start in range(0, len(texts), EMBED_BATCH):
            batch = texts[batch_start:batch_start + EMBED_BATCH]
            embeddings.extend(embed_texts(batch, openai_client))
            time.sleep(0.3)

        # 벡터 구성
        for chunk, emb in zip(chunks, embeddings):
            all_vectors.append(build_legal_vector(chunk, emb, doc_meta, source_type))

        total_chunks += len(chunks)

        if i % 50 == 0 or i == len(md_files):
            print(f"  진행: {i}/{len(md_files)} 파일, {total_chunks} 청크")

        # 벡터 배치 upsert (메모리 관리)
        if len(all_vectors) >= UPSERT_BATCH:
            index.upsert(vectors=all_vectors, namespace=namespace)
            all_vectors = []
            time.sleep(0.1)

    # 남은 벡터 upsert
    if all_vectors and not dry_run:
        index.upsert(vectors=all_vectors, namespace=namespace)

    print(f"\n  [{label}] 완료: {len(md_files) - errors}개 파일, {total_chunks} 청크, {errors} 오류")
    return {"files": len(md_files), "chunks": total_chunks, "errors": errors}


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="법률 데이터 Pinecone 업로드")
    parser.add_argument("--source", type=str, help="특정 소스만 업로드 (precedent/interpretation/regulation/legal_cases)")
    parser.add_argument("--reset", action="store_true", help="대상 네임스페이스 초기화 후 재업로드")
    parser.add_argument("--dry-run", action="store_true", help="청킹만 수행 (업로드 안 함)")
    args = parser.parse_args()

    openai_key = os.getenv("OPENAI_API_KEY")
    pinecone_key = os.getenv("PINECONE_API_KEY")
    index_name = os.getenv("PINECONE_INDEX_NAME", "nodongok-bestqna")

    if not openai_key:
        sys.exit("[오류] OPENAI_API_KEY가 설정되지 않았습니다.")
    if not args.dry_run and not pinecone_key:
        sys.exit("[오류] PINECONE_API_KEY가 설정되지 않았습니다.")

    openai_client = OpenAI(api_key=openai_key)

    index = None
    if not args.dry_run:
        pc = Pinecone(api_key=pinecone_key)
        index = pc.Index(index_name)

    # 소스 필터링
    sources = LEGAL_SOURCES
    if args.source:
        sources = [s for s in LEGAL_SOURCES if s["namespace"] == args.source]
        if not sources:
            sys.exit(f"[오류] 알 수 없는 소스: {args.source}. 가능한 값: {[s['namespace'] for s in LEGAL_SOURCES]}")

    # 네임스페이스 초기화
    if args.reset and not args.dry_run:
        for src in sources:
            ns = src["namespace"]
            print(f"네임스페이스 초기화: '{ns}'")
            try:
                index.delete(delete_all=True, namespace=ns)
                time.sleep(1)
            except Exception as e:
                print(f"  초기화 실패 (무시): {e}")

    # 업로드 실행
    print(f"\n{'='*60}")
    print(f"법률 데이터 벡터 업로드 {'(DRY RUN)' if args.dry_run else ''}")
    print(f"인덱스: {index_name}  |  모델: {EMBED_MODEL}")
    print(f"대상 소스: {[s['label'] for s in sources]}")
    print(f"{'='*60}")

    grand_total = {"files": 0, "chunks": 0, "errors": 0}

    for src in sources:
        result = upload_source(src, index, openai_client, dry_run=args.dry_run)
        for k in grand_total:
            grand_total[k] += result[k]

    # 최종 통계
    print(f"\n{'='*60}")
    print(f"=== 전체 완료 {'(DRY RUN)' if args.dry_run else ''} ===")
    print(f"총 파일: {grand_total['files']}개")
    print(f"총 청크: {grand_total['chunks']}개")
    print(f"총 오류: {grand_total['errors']}개")

    if not args.dry_run and index:
        time.sleep(2)
        stats = index.describe_index_stats()
        print(f"\nPinecone 인덱스 통계:")
        print(f"  총 벡터: {stats.total_vector_count:,}개")
        if hasattr(stats, 'namespaces'):
            for ns_name, ns_info in stats.namespaces.items():
                print(f"  namespace='{ns_name}': {ns_info.vector_count:,}개")

    print(f"{'='*60}")


if __name__ == "__main__":
    main()
