#!/usr/bin/env python3
"""
Anthropic Contextual Retrieval 방식으로 법률 데이터 → Pinecone 업로드

소스별 네임스페이스로 분리하여 업로드:
  - precedent: 판례
  - interpretation: 행정해석
  - regulation: 훈령/예규
  - qa: Q&A 상담사례 (Contextual Retrieval 선택적)

파이프라인:
  1. 마크다운 파싱 → 메타데이터 + 본문 추출
  2. 섹션 기반 청킹 (max 700자, 80자 overlap)
  3. ★ Contextual Retrieval: Claude Haiku로 각 청크에 문서 맥락 prefix 생성
  4. 맥락화된 텍스트 → OpenAI 임베딩 (text-embedding-3-small)
  5. Pinecone upsert (semiconductor-lithography / 소스별 네임스페이스)

사용법:
  python3 pinecone_upload_contextual.py                  # 전체 업로드
  python3 pinecone_upload_contextual.py --dry-run        # 청킹만 (API 호출/업로드 안 함)
  python3 pinecone_upload_contextual.py --reset          # 대상 네임스페이스 초기화 후 업로드
  python3 pinecone_upload_contextual.py --resume         # 이전 진행상황 이어서
  python3 pinecone_upload_contextual.py --source 판례    # 특정 소스만
  python3 pinecone_upload_contextual.py --skip-context   # 맥락 생성 건너뛰기 (Q&A용)
"""

import os
import re
import sys
import json
import time
import argparse
from datetime import datetime

from dotenv import load_dotenv
import anthropic
from openai import OpenAI
from pinecone import Pinecone

load_dotenv()

# ── 설정 ──────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROGRESS_FILE = os.path.join(BASE_DIR, "_contextual_upload_progress.json")

# Pinecone
PINECONE_INDEX = "semiconductor-lithography"

# 모델
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536
CONTEXT_MODEL = "claude-haiku-4-5-20251001"

# 청킹
CHUNK_MAX = 700
CHUNK_OVERLAP = 80

# 배치
EMBED_BATCH = 50
UPSERT_BATCH = 100
CONTEXT_BATCH_DELAY = 0.05  # Haiku rate limit 여유

# 소스 정의 — 소스별 네임스페이스 분리
SOURCES = [
    {
        "directory": "output_법원 노동판례",
        "namespace": "precedent",
        "source_type": "precedent",
        "label": "판례",
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
        "label": "훈령/예규",
    },
    {
        "directory": "output_qna",
        "namespace": "qa",
        "source_type": "qa",
        "label": "Q&A 상담 (1차)",
        "source": "nodongok",
    },
    {
        "directory": "output_qna_2",
        "namespace": "qa",
        "source_type": "qa",
        "label": "Q&A 상담 (2차)",
        "source": "nodongok",
    },
    {
        "directory": "output_legal_cases",
        "namespace": "qa",
        "source_type": "qa",
        "label": "법률 상담사례",
        "source": "nodongok",
    },
    {
        "directory": "nodong_counsel",
        "namespace": "counsel",
        "source_type": "counsel",
        "label": "노무사 상담",
        "parser": "counsel_qa",  # 전용 파서 사용
    },
]

# ── nodong_counsel 카테고리 매핑 ──────────────────────────────────────────────
_COUNSEL_CATEGORY = {
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

# ── Contextual Retrieval 프롬프트 ─────────────────────────────────────────────

CONTEXT_SYSTEM = "당신은 한국 노동법 문서 분석 전문가입니다. 검색 품질 향상을 위해 청크의 문서 내 맥락을 간결하게 요약합니다."

CONTEXT_PROMPT = """<document>
{document}
</document>

위 문서에서 추출한 아래 청크가 문서 전체에서 어떤 맥락에 해당하는지 1-2문장으로 간결하게 설명하세요.
검색 시 이 청크를 찾는 데 도움이 되는 핵심 키워드와 법적 쟁점을 포함하세요.

<chunk>
{chunk}
</chunk>

맥락 설명만 출력하세요:"""


# ── 텍스트 유틸 ───────────────────────────────────────────────────────────────

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


# ── 마크다운 파싱 ─────────────────────────────────────────────────────────────

def parse_md_metadata(md_content: str) -> dict:
    meta = {}
    for m in re.finditer(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|", md_content, re.MULTILINE):
        key = m.group(1).strip()
        val = m.group(2).strip()
        if key in ("항목", "---", ""):
            continue
        link = re.search(r"\[(.+?)\]\((.+?)\)", val)
        if link:
            val = link.group(2)
        meta[key] = val
    return meta


def extract_title(md_content: str) -> str:
    m = re.match(r"^#\s+(.+)", md_content.strip())
    return m.group(1).strip() if m else ""


def extract_body(md_content: str) -> str:
    parts = md_content.split("\n---\n", 1)
    if len(parts) > 1:
        return clean_text(parts[1])
    m = re.search(r"^## ", md_content, re.MULTILINE)
    if m:
        return clean_text(md_content[m.start():])
    return clean_text(md_content)


def extract_post_id(filepath: str) -> str:
    basename = os.path.splitext(os.path.basename(filepath))[0]
    m = re.match(r"(\d+)", basename)
    return m.group(1) if m else basename[:20]


# ── 청킹 ─────────────────────────────────────────────────────────────────────

def chunk_document(post_id: str, title: str, category: str, body: str, source_type: str) -> list[dict]:
    header_pat = re.compile(r"^(#{2,3})\s+(.+)$", re.MULTILINE)
    headers = list(header_pat.finditer(body))

    sections: list[tuple[str, str]] = []
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
            chunks.append({
                "chunk_id": f"ctx_{source_type}_{post_id}_c{idx}",
                "chunk_index": idx,
                "section": section_name,
                "chunk_text": sub_text,
                "title": title,
                "category": category,
            })
            idx += 1

    if not chunks:
        for sub_text in split_by_size(body):
            chunks.append({
                "chunk_id": f"ctx_{source_type}_{post_id}_c{idx}",
                "chunk_index": idx,
                "section": "본문",
                "chunk_text": sub_text,
                "title": title,
                "category": category,
            })
            idx += 1

    return chunks


# ── Contextual Retrieval: 맥락 생성 ──────────────────────────────────────────

def generate_chunk_context(
    claude_client: anthropic.Anthropic,
    full_document: str,
    chunk_text: str,
) -> str:
    """Claude Haiku로 청크의 문서 내 맥락을 생성.

    Anthropic Contextual Retrieval 핵심:
    전체 문서를 보고 해당 청크가 어떤 맥락인지 1-2문장으로 요약.
    이 맥락을 청크 앞에 prepend하여 임베딩 품질을 향상시킨다.
    """
    # 문서가 너무 길면 앞부분 잘라서 사용 (Haiku 컨텍스트 절약)
    doc_truncated = full_document[:6000] if len(full_document) > 6000 else full_document

    try:
        resp = claude_client.messages.create(
            model=CONTEXT_MODEL,
            max_tokens=150,
            temperature=0,
            system=CONTEXT_SYSTEM,
            messages=[{
                "role": "user",
                "content": CONTEXT_PROMPT.format(
                    document=doc_truncated,
                    chunk=chunk_text,
                ),
            }],
        )
        context = resp.content[0].text.strip()
        return context
    except Exception as e:
        # 맥락 생성 실패 시 빈 문자열 → 일반 임베딩으로 fallback
        return ""


def contextualize_chunk(context: str, chunk: dict) -> str:
    """맥락 + 제목 + 카테고리 + 청크 텍스트를 결합하여 임베딩용 텍스트 생성."""
    parts = []
    if context:
        parts.append(f"[맥락] {context}")
    parts.append(f"제목: {chunk['title']}")
    if chunk.get("category"):
        parts.append(f"분류: {chunk['category']}")
    parts.append(f"섹션: {chunk['section']}")
    parts.append("")
    parts.append(chunk["chunk_text"])
    return "\n".join(parts)


# ── nodong_counsel 전용 파서 ──────────────────────────────────────────────────

def parse_counsel_qa_pairs(md_content: str) -> list[dict]:
    """nodong_counsel/*.md에서 ## 단위로 Q&A 쌍 추출.

    Returns:
        [{"seq": 1, "title": "...", "question": "...", "answer": "...", "full_text": "..."}, ...]
    """
    pattern = re.compile(r"^## (\d+)\.\s*(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(md_content))

    pairs = []
    for i, m in enumerate(matches):
        seq = int(m.group(1))
        title = m.group(2).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md_content)
        body = md_content[start:end].strip()
        body = re.sub(r"\n---\s*$", "", body).strip()

        question = ""
        answer = ""
        q_match = re.search(r"### 질문\s*\n(.*?)(?=### 답변|$)", body, re.DOTALL)
        a_match = re.search(r"### 답변\s*\n(.*)", body, re.DOTALL)
        if q_match:
            question = clean_text(q_match.group(1))
        if a_match:
            answer = clean_text(a_match.group(1))

        combined = ""
        if question:
            combined += f"[질문]\n{question}\n\n"
        if answer:
            combined += f"[답변]\n{answer}"
        combined = combined.strip()

        if combined and len(combined) >= 20:
            pairs.append({
                "seq": seq,
                "title": title,
                "question": question,
                "answer": answer,
                "full_text": combined,
            })
    return pairs


def process_counsel_source(
    source_config: dict,
    claude_client,
    openai_client: OpenAI,
    index,
    completed_files: set[str],
    dry_run: bool = False,
    skip_context: bool = False,
    cache_map: dict | None = None,
) -> dict:
    """nodong_counsel/ 전용 처리 — Q&A 쌍 단위로 청킹 + Contextual Retrieval."""
    directory = os.path.join(BASE_DIR, source_config["directory"])
    namespace = source_config["namespace"]
    source_type = source_config["source_type"]
    label = source_config["label"]

    if not os.path.isdir(directory):
        print(f"  [스킵] 디렉토리 없음: {directory}")
        return {"files": 0, "chunks": 0, "contexts": 0, "errors": 0}

    md_files = sorted([
        os.path.join(directory, f) for f in os.listdir(directory)
        if f.endswith(".md") and not f.startswith("_")
    ])
    pending_files = [f for f in md_files if f not in completed_files]

    print(f"\n{'='*60}")
    print(f"[{label}] 총 {len(md_files)}개 파일, 미처리 {len(pending_files)}개")
    print(f"{'='*60}")

    if not pending_files:
        print("  모든 파일 처리 완료")
        return {"files": 0, "chunks": 0, "contexts": 0, "errors": 0}

    # _pairs_cache.json 로드 (title → q_seq 매핑)
    if cache_map is None:
        cache_map = {}
        cache_file = os.path.join(directory, "_pairs_cache.json")
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                for item in json.load(f):
                    cache_map[item["title"]] = item.get("q_seq")

    total_chunks = 0
    total_contexts = 0
    total_pairs = 0
    errors = 0
    all_vectors = []

    for file_idx, filepath in enumerate(pending_files, 1):
        try:
            with open(filepath, "r", encoding="utf-8") as fh:
                content = fh.read()
        except Exception as e:
            print(f"  [{file_idx}] 읽기 실패: {e}")
            errors += 1
            continue

        file_key = os.path.splitext(os.path.basename(filepath))[0]
        category = _COUNSEL_CATEGORY.get(file_key, file_key)
        pairs = parse_counsel_qa_pairs(content)
        total_pairs += len(pairs)

        for pair in pairs:
            q_seq = cache_map.get(pair["title"])
            if q_seq:
                id_base = f"ctx_counsel_{q_seq}"
            else:
                # 한글 파일명 → ASCII 해시로 변환
                import hashlib
                fk_hash = hashlib.md5(file_key.encode()).hexdigest()[:8]
                id_base = f"ctx_counsel_{fk_hash}_{pair['seq']}"

            # Q&A 텍스트 청킹
            chunks = []
            idx = 0
            for sub_text in split_by_size(pair["full_text"]):
                chunks.append({
                    "chunk_id": f"{id_base}_c{idx}",
                    "chunk_index": idx,
                    "section": "Q&A",
                    "chunk_text": sub_text,
                    "title": pair["title"],
                    "category": category,
                })
                idx += 1

            if not chunks:
                continue
            total_chunks += len(chunks)

            # Contextual Retrieval: 맥락 생성
            full_doc = f"카테고리: {category}\n제목: {pair['title']}\n\n{pair['full_text']}"
            contextualized_texts = []

            for chunk in chunks:
                if skip_context:
                    context = ""
                elif not dry_run:
                    context = generate_chunk_context(
                        claude_client, full_doc, chunk["chunk_text"]
                    )
                    if context:
                        total_contexts += 1
                    time.sleep(CONTEXT_BATCH_DELAY)
                else:
                    context = "(dry-run)"

                embed_text = contextualize_chunk(context, chunk)
                contextualized_texts.append(embed_text)

            # 임베딩 + 벡터
            if not dry_run:
                embeddings = embed_texts(contextualized_texts, openai_client)
                time.sleep(0.2)

                for chunk, emb in zip(chunks, embeddings):
                    all_vectors.append({
                        "id": chunk["chunk_id"],
                        "values": emb,
                        "metadata": {
                            "source_type": source_type,
                            "title": pair["title"][:200],
                            "category": category[:50],
                            "section": "Q&A",
                            "chunk_index": chunk["chunk_index"],
                            "chunk_text": chunk["chunk_text"][:900],
                            "text": chunk["chunk_text"][:900],
                            "contextualized": not skip_context,
                        },
                    })

            if not dry_run and len(all_vectors) >= UPSERT_BATCH:
                index.upsert(vectors=all_vectors, namespace=namespace)
                all_vectors = []
                time.sleep(0.1)

        completed_files.add(filepath)
        print(f"  {os.path.basename(filepath)}: {len(pairs)} Q&A → {category}")

    # 남은 벡터 upsert
    if all_vectors and not dry_run:
        index.upsert(vectors=all_vectors, namespace=namespace)

    print(f"\n  [{label}] 완료: {total_pairs} Q&A, "
          f"{total_chunks} 청크, {total_contexts} 맥락 생성, {errors} 오류")

    return {
        "files": len(pending_files),
        "chunks": total_chunks,
        "contexts": total_contexts,
        "errors": errors,
    }


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


# ── 진행상황 관리 ─────────────────────────────────────────────────────────────

def load_progress() -> set[str]:
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r") as f:
            data = json.load(f)
            return set(data.get("completed_files", []))
    return set()


def save_progress(completed: set[str], stats: dict):
    with open(PROGRESS_FILE, "w") as f:
        json.dump({
            "completed_files": list(completed),
            "stats": stats,
            "last_updated": datetime.now().isoformat(),
        }, f, ensure_ascii=False, indent=2)


# ── 메인 처리 ─────────────────────────────────────────────────────────────────

def process_source(
    source_config: dict,
    claude_client: anthropic.Anthropic,
    openai_client: OpenAI,
    index,
    completed_files: set[str],
    dry_run: bool = False,
    skip_context: bool = False,
) -> dict:
    directory = os.path.join(BASE_DIR, source_config["directory"])
    source_type = source_config["source_type"]
    namespace = source_config["namespace"]
    label = source_config["label"]

    if not os.path.isdir(directory):
        print(f"  [스킵] 디렉토리 없음: {directory}")
        return {"files": 0, "chunks": 0, "contexts": 0, "errors": 0}

    # 재귀적으로 모든 .md 파일 수집
    md_files = []
    for root, dirs, files in os.walk(directory):
        for f in files:
            if f.endswith(".md") and not f.startswith("_"):
                md_files.append(os.path.join(root, f))
    md_files.sort()

    # 이미 처리된 파일 제외
    pending_files = [f for f in md_files if f not in completed_files]

    print(f"\n{'='*60}")
    print(f"[{label}] 총 {len(md_files)}개 파일, 미처리 {len(pending_files)}개")
    print(f"{'='*60}")

    if not pending_files:
        print("  모든 파일 처리 완료")
        return {"files": 0, "chunks": 0, "contexts": 0, "errors": 0}

    total_chunks = 0
    total_contexts = 0
    errors = 0
    all_vectors = []

    for file_idx, filepath in enumerate(pending_files, 1):
        try:
            with open(filepath, "r", encoding="utf-8") as fh:
                md_content = fh.read()
        except Exception as e:
            print(f"  [{file_idx}] 파일 읽기 실패: {e}")
            errors += 1
            continue

        title = extract_title(md_content)
        meta = parse_md_metadata(md_content)
        post_id = extract_post_id(filepath)

        category = meta.get("분류", "")
        if not category:
            parent_dir = os.path.basename(os.path.dirname(filepath))
            base_dir_name = os.path.basename(directory)
            if parent_dir != base_dir_name:
                category = parent_dir

        url = meta.get("원문", "")
        date_str = meta.get("작성일", "")

        body = extract_body(md_content)
        if not body or len(body) < 20:
            completed_files.add(filepath)
            continue

        # 청킹
        chunks = chunk_document(post_id, title, category, body, source_type)
        if not chunks:
            completed_files.add(filepath)
            continue

        # ★ Contextual Retrieval: 각 청크에 맥락 생성
        full_doc_text = f"# {title}\n분류: {category}\n\n{body}"
        contextualized_texts = []

        for chunk in chunks:
            if skip_context:
                context = ""
            elif not dry_run:
                context = generate_chunk_context(
                    claude_client, full_doc_text, chunk["chunk_text"]
                )
                if context:
                    total_contexts += 1
                time.sleep(CONTEXT_BATCH_DELAY)
            else:
                context = "(dry-run: 맥락 미생성)"

            embed_text = contextualize_chunk(context, chunk)
            contextualized_texts.append(embed_text)

        # 임베딩 + 벡터 구성
        if not dry_run:
            embeddings = []
            for batch_start in range(0, len(contextualized_texts), EMBED_BATCH):
                batch = contextualized_texts[batch_start:batch_start + EMBED_BATCH]
                embeddings.extend(embed_texts(batch, openai_client))
                time.sleep(0.2)

            for chunk, emb, ctx_text in zip(chunks, embeddings, contextualized_texts):
                all_vectors.append({
                    "id": chunk["chunk_id"],
                    "values": emb,
                    "metadata": {
                        "source_type": source_type,
                        "source": source_config.get("source", ""),
                        "title": title[:200],
                        "category": category[:50],
                        "date": date_str,
                        "url": url,
                        "section": chunk["section"][:100],
                        "chunk_index": chunk["chunk_index"],
                        "chunk_text": chunk["chunk_text"][:900],
                        "text": chunk["chunk_text"][:900],
                        "contextualized": not skip_context,
                    },
                })

        total_chunks += len(chunks)

        # 진행 표시
        if file_idx % 10 == 0 or file_idx == len(pending_files) or file_idx <= 3:
            print(
                f"  [{file_idx}/{len(pending_files)}] {title[:35]}... "
                f"→ {len(chunks)} 청크, 맥락 {total_contexts}건"
            )

        # 배치 upsert
        if not dry_run and len(all_vectors) >= UPSERT_BATCH:
            index.upsert(vectors=all_vectors, namespace=namespace)
            all_vectors = []
            time.sleep(0.1)

        completed_files.add(filepath)

        # 50개마다 진행상황 저장
        if file_idx % 50 == 0:
            save_progress(completed_files, {
                "total_chunks": total_chunks,
                "total_contexts": total_contexts,
                "errors": errors,
            })
            print(f"  [진행상황 저장] {file_idx}개 완료")

    # 남은 벡터 upsert
    if all_vectors and not dry_run:
        index.upsert(vectors=all_vectors, namespace=namespace)

    print(f"\n  [{label}] 완료: {len(pending_files)-errors}개 파일, "
          f"{total_chunks} 청크, {total_contexts} 맥락 생성, {errors} 오류")

    return {
        "files": len(pending_files),
        "chunks": total_chunks,
        "contexts": total_contexts,
        "errors": errors,
    }


def main():
    parser = argparse.ArgumentParser(description="Contextual Retrieval 방식 Pinecone 업로드")
    parser.add_argument("--dry-run", action="store_true", help="청킹만 (API 호출/업로드 안 함)")
    parser.add_argument("--reset", action="store_true", help="대상 네임스페이스 초기화 후 업로드")
    parser.add_argument("--resume", action="store_true", help="이전 진행상황 이어서")
    parser.add_argument("--source", type=str, help="특정 소스만 (판례/행정해석/훈령/Q&A/상담사례)")
    parser.add_argument("--skip-context", action="store_true", help="맥락 생성 건너뛰기 (Q&A 대량 처리용)")
    args = parser.parse_args()

    # API 키 확인
    openai_key = os.getenv("OPENAI_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    pinecone_key = os.getenv("PINECONE_API_KEY")

    if not openai_key:
        sys.exit("[오류] OPENAI_API_KEY가 설정되지 않았습니다.")
    if not anthropic_key:
        sys.exit("[오류] ANTHROPIC_API_KEY가 설정되지 않았습니다.")
    if not args.dry_run and not pinecone_key:
        sys.exit("[오류] PINECONE_API_KEY가 설정되지 않았습니다.")

    openai_client = OpenAI(api_key=openai_key)
    claude_client = anthropic.Anthropic(api_key=anthropic_key)

    index = None
    if not args.dry_run:
        pc = Pinecone(api_key=pinecone_key)
        index = pc.Index(PINECONE_INDEX)

    # 소스 필터링 (reset보다 먼저 실행해야 sources 변수 사용 가능)
    sources = SOURCES
    if args.source:
        sources = [s for s in SOURCES if args.source in s["label"]]
        if not sources:
            sys.exit(f"[오류] 알 수 없는 소스: {args.source}. 가능: {[s['label'] for s in SOURCES]}")

    # 네임스페이스 초기화 (대상 소스의 NS만)
    if args.reset and not args.dry_run:
        reset_namespaces = sorted(set(s["namespace"] for s in sources))
        for ns in reset_namespaces:
            print(f"네임스페이스 '{ns}' 초기화 중...")
            try:
                index.delete(delete_all=True, namespace=ns)
                time.sleep(1)
                print(f"  '{ns}' 초기화 완료")
            except Exception as e:
                print(f"  '{ns}' 초기화 실패: {e}")
        time.sleep(1)

    # 진행상황 로드
    completed_files = set()
    if args.resume:
        completed_files = load_progress()
        print(f"이전 진행상황 로드: {len(completed_files)}개 파일 처리 완료")
    elif not args.reset:
        if os.path.exists(PROGRESS_FILE):
            os.remove(PROGRESS_FILE)

    target_namespaces = sorted(set(s["namespace"] for s in sources))
    print(f"\n{'='*60}")
    print(f"Anthropic Contextual Retrieval 업로드 {'(DRY RUN)' if args.dry_run else ''}")
    print(f"  인덱스: {PINECONE_INDEX}")
    print(f"  대상 NS: {target_namespaces}")
    print(f"  맥락 모델: {CONTEXT_MODEL}{' (skip-context)' if args.skip_context else ''}")
    print(f"  임베딩 모델: {EMBED_MODEL}")
    print(f"  대상: {[s['label'] for s in sources]}")
    print(f"{'='*60}")

    grand_total = {"files": 0, "chunks": 0, "contexts": 0, "errors": 0}

    for src in sources:
        if src.get("parser") == "counsel_qa":
            result = process_counsel_source(
                src, claude_client, openai_client, index,
                completed_files, dry_run=args.dry_run,
                skip_context=args.skip_context,
            )
        else:
            result = process_source(
                src, claude_client, openai_client, index,
                completed_files, dry_run=args.dry_run,
                skip_context=args.skip_context,
            )
        for k in grand_total:
            grand_total[k] += result[k]

    # 최종 진행상황 저장
    save_progress(completed_files, grand_total)

    # 최종 통계
    print(f"\n{'='*60}")
    print(f"=== 전체 완료 {'(DRY RUN)' if args.dry_run else ''} ===")
    print(f"  처리 파일: {grand_total['files']}개")
    print(f"  총 청크: {grand_total['chunks']}개")
    print(f"  맥락 생성: {grand_total['contexts']}개")
    print(f"  오류: {grand_total['errors']}개")

    if not args.dry_run and index:
        time.sleep(2)
        stats = index.describe_index_stats()
        for ns in target_namespaces:
            ns_stats = stats.namespaces.get(ns, None)
            if ns_stats:
                print(f"\n  Pinecone '{ns}' 벡터: {ns_stats.vector_count:,}개")
        print(f"  Pinecone 총 벡터: {stats.total_vector_count:,}개")

    print(f"{'='*60}")

    # 예상 비용 표시
    est_input_tokens = grand_total["contexts"] * 1500
    est_output_tokens = grand_total["contexts"] * 80
    est_claude_cost = (est_input_tokens * 0.80 + est_output_tokens * 4.0) / 1_000_000
    est_embed_cost = grand_total["chunks"] * 300 * 0.02 / 1_000_000
    print(f"\n예상 API 비용:")
    print(f"  Claude Haiku: ~${est_claude_cost:.2f}")
    print(f"  OpenAI Embed: ~${est_embed_cost:.2f}")
    print(f"  합계: ~${est_claude_cost + est_embed_cost:.2f}")


if __name__ == "__main__":
    main()
