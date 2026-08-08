#!/usr/bin/env python3
"""
output_판례_보강/*.md (법제처 수집 판례) → Pinecone laborlaw-v2 업로드.

설계: docs/02-design/features/precedent-corpus-expansion.design.md

pinecone_upload_legal.py를 재사용하지 않는 이유:
그쪽 extract_post_id()는 사건번호 정규식이 완성형 글자 클래스 + 4자리 연도를
전제해, macOS NFD 파일명과 2자리 연도 사건번호에서 매치가 실패한다. 폴백이
연도만 잡으면서 같은 해 판례들이 동일 post_id로 충돌해 서로를 덮어쓴다
(실측: 이 데이터 601건 중 259건 소실). 여기서는 벡터 ID 생성을 직접 통제한다.

사용법:
  python3 pinecone_upload_court_precedents.py             # 업로드
  python3 pinecone_upload_court_precedents.py --dry-run   # 청킹만
  python3 pinecone_upload_court_precedents.py --limit 20  # 부분 검증
"""

from __future__ import annotations

import os
import re
import sys
import time
import argparse
import unicodedata

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
            override=True)

# ── 설정 ──────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_DIR = os.path.join(BASE_DIR, "output_판례_보강")

EMBED_MODEL = "text-embedding-3-small"
CHUNK_MAX = 700
CHUNK_OVERLAP = 80
UPSERT_BATCH = 100

# rag.py::NS_GROUP_LAW가 실제로 조회하는 유일한 법령 네임스페이스.
# 스크립트에만 존재하는 'precedent' NS에 올리면 검색되지 않는다.
NAMESPACE = "laborlaw-v2"

# rag.py:318 / public/index.html:1365의 라벨 맵에 이미 "판례"로 존재하는 값.
SOURCE_TYPE = "precedent"

# 임베딩 대상 섹션. 전문(판례내용)은 제외한다 — 최대 52,867자로 단일 판례가
# 75청크가 되고, 【원고, 상고인】 같은 절차 보일러플레이트가 검색 노이즈가 된다.
EMBED_SECTIONS = ("판시사항", "판결요지", "참조조문")

# 사건부호 → ASCII. Pinecone 벡터 ID는 ASCII만 허용한다.
# 긴 부호가 먼저 치환돼야 '86다카24445'가 '86daka24445'가 된다.
_CASE_CODE_MAP = {
    "다카": "daka", "헌바": "heonba", "헌마": "heonma", "헌가": "heonga",
    "헌라": "heonra", "헌사": "heonsa", "재두": "jaedu", "재다": "jaeda",
    "가합": "gahap", "가단": "gadan", "가소": "gaso",
    "구합": "guhap", "구단": "gudan", "나합": "nahap",
    "다": "da", "두": "du", "누": "nu", "도": "do", "가": "ga",
    "나": "na", "마": "ma", "라": "ra", "바": "ba", "카": "ka",
    "자": "ja", "차": "cha", "모": "mo", "므": "meu", "브": "beu",
    "즈": "jeu", "추": "chu", "초": "cho", "오": "o", "우": "u",
    "허": "heo", "후": "hu", "그": "geu", "노": "no", "고": "go",
    "구": "gu", "단": "dan", "합": "hap", "재": "jae", "머": "meo",
    "인": "in", "감": "gam", "코": "ko", "토": "to", "푸": "pu",
}
_CODE_KEYS = sorted(_CASE_CODE_MAP, key=len, reverse=True)

CASE_NO_RE = re.compile(r"(\d{2,4}[가-힣]{1,4}\d+)")


# ── 텍스트 유틸 (기존 pinecone_upload_*.py와 동일 로직) ─────────────────────

def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_by_size(text: str, max_chars: int = CHUNK_MAX,
                  overlap: int = CHUNK_OVERLAP) -> list[str]:
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


# ── 벡터 ID ───────────────────────────────────────────────────────────────────

class UnknownCaseCode(ValueError):
    """매핑에 없는 사건부호 — 조용히 제거하면 ID가 뭉개지므로 예외로 올린다."""


def case_no_to_ascii(case_no: str) -> str:
    """사건번호를 ASCII로 변환. 알 수 없는 부호는 예외."""
    s = unicodedata.normalize("NFC", case_no).strip()
    for code in _CODE_KEYS:
        if code in s:
            s = s.replace(code, _CASE_CODE_MAP[code])
    if re.search(r"[^\x00-\x7F]", s):
        raise UnknownCaseCode(f"매핑되지 않은 사건부호: {case_no!r} → {s!r}")
    return s


def make_vector_id(case_no: str, idx: int) -> str:
    """결정적 ID — 재실행 시 upsert가 덮어써 중복 벡터가 생기지 않는다."""
    return f"{SOURCE_TYPE}_{case_no_to_ascii(case_no)}_chunk_{idx}"


# ── 마크다운 파싱 ─────────────────────────────────────────────────────────────

def parse_meta(md: str) -> dict:
    """상단 메타 테이블 → dict."""
    meta = {}
    for m in re.finditer(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|", md, re.MULTILINE):
        key, val = m.group(1).strip(), m.group(2).strip()
        if key in ("항목", "---", ""):
            continue
        link = re.search(r"\[(.+?)\]\((.+?)\)", val)
        if link:
            val = link.group(2)
        meta[key] = val
    return meta


def parse_sections(md: str) -> dict[str, str]:
    """`## 제목` 단위 섹션 → {제목: 본문}."""
    body = md.split("\n---\n", 1)
    body = body[1] if len(body) > 1 else md

    sections: dict[str, str] = {}
    matches = list(re.finditer(r"^##\s+(.+)$", body, re.MULTILINE))
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        text = clean_text(body[start:end])
        if text:
            sections[title] = text
    return sections


def parse_doc(path: str) -> dict | None:
    with open(path, encoding="utf-8") as f:
        md = unicodedata.normalize("NFC", f.read())

    title_m = re.match(r"^#\s+(.+)", md.strip())
    meta = parse_meta(md)
    case_no = meta.get("사건번호", "")
    if not case_no:
        found = CASE_NO_RE.search(os.path.basename(path))
        case_no = found.group(1) if found else ""
    if not case_no:
        return None

    sections = parse_sections(md)
    # 교재 목차에서 온 쟁점 태그(enrich_court_precedents.py). 별도 청크로 만들지
    # 않고 각 청크의 embed_text·검색 텍스트에 얹는다.
    topics = [ln[2:].strip() for ln in sections.get("관련 쟁점", "").splitlines()
              if ln.startswith("- ")]

    return {
        "case_no": unicodedata.normalize("NFC", case_no),
        "title": title_m.group(1).strip() if title_m else case_no,
        "court": meta.get("법원", ""),
        "date": meta.get("작성일", ""),
        "category": meta.get("분류", ""),
        "topics": topics,
        "sections": sections,
    }


# ── 청킹 ─────────────────────────────────────────────────────────────────────

def chunk_doc(doc: dict) -> list[dict]:
    """임베딩 대상 섹션만 청킹. 전문은 제외.

    관련 쟁점은 모든 청크의 embed_text와 저장 텍스트에 얹는다 — 판시사항에
    쟁점 용어가 그대로 안 나오는 판례도 쟁점 질의에 걸리게 하는 게 목적이라,
    별도 청크가 아니라 각 청크의 맥락이어야 한다. 저장 텍스트에 넣는 이유는
    BM25(키워드) 검색이 metadata의 text 필드를 색인하기 때문.
    """
    topics = doc.get("topics") or []
    topic_line = f"쟁점: {' / '.join(topics)}\n" if topics else ""
    text_prefix = f"[관련 쟁점: {' · '.join(topics)}]\n" if topics else ""

    chunks: list[dict] = []
    idx = 0
    for section in EMBED_SECTIONS:
        text = doc["sections"].get(section)
        if not text:
            continue
        for sub in split_by_size(text):
            embed_text = (f"판례: {doc['title']}\n사건번호: {doc['case_no']}\n"
                          f"{topic_line}섹션: {section}\n\n{sub}")
            chunks.append({
                "vector_id": make_vector_id(doc["case_no"], idx),
                "chunk_index": idx,
                "section": section,
                "embed_text": embed_text,
                "chunk_text": text_prefix + sub,
            })
            idx += 1
    return chunks


# ── 임베딩 ────────────────────────────────────────────────────────────────────

def embed_texts(texts: list[str], client) -> list[list[float]]:
    for attempt in range(3):
        try:
            resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
            return [d.embedding for d in sorted(resp.data, key=lambda x: x.index)]
        except Exception as e:
            if attempt == 2:
                raise
            print(f"    임베딩 재시도 ({attempt + 1}/3): {e}")
            time.sleep(2 ** attempt)
    return []


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="법제처 판례 Pinecone 업로드")
    parser.add_argument("--dry-run", action="store_true", help="청킹만 수행")
    parser.add_argument("--limit", type=int, help="처리할 최대 파일 수")
    # --reset 없음: laborlaw-v2는 다른 소스와 공유하는 네임스페이스라
    # delete_all이 기존 9,000여 벡터를 통째로 날린다.
    args = parser.parse_args()

    if not os.path.isdir(SOURCE_DIR):
        sys.exit(f"[오류] 소스 디렉토리가 없습니다: {SOURCE_DIR}")

    md_files = sorted(
        f for f in os.listdir(SOURCE_DIR)
        if f.endswith(".md") and not f.startswith("_")
    )
    if args.limit:
        md_files = md_files[:args.limit]

    openai_client = None
    index = None
    if not args.dry_run:
        openai_key = os.getenv("OPENAI_API_KEY")
        pinecone_key = os.getenv("PINECONE_API_KEY")
        if not openai_key:
            sys.exit("[오류] OPENAI_API_KEY가 설정되지 않았습니다.")
        if not pinecone_key:
            sys.exit("[오류] PINECONE_API_KEY가 설정되지 않았습니다.")
        from openai import OpenAI
        from pinecone import Pinecone
        from app.config import resolve_index_name
        openai_client = OpenAI(api_key=openai_key)
        index = Pinecone(api_key=pinecone_key).Index(resolve_index_name())

    print(f"\n{'=' * 62}")
    print(f"법제처 판례 업로드 {'(DRY RUN)' if args.dry_run else ''}")
    print(f"소스: {SOURCE_DIR}  ({len(md_files)}개 파일)")
    print(f"네임스페이스: {NAMESPACE}  |  source_type: {SOURCE_TYPE}")
    print(f"임베딩 섹션: {', '.join(EMBED_SECTIONS)}  (전문 제외)")
    print(f"{'=' * 62}\n")

    total_chunks = 0
    skipped: list[str] = []
    seen_ids: set[str] = set()
    pending: list[dict] = []
    samples: list[dict] = []

    for fn in md_files:
        path = os.path.join(SOURCE_DIR, fn)
        doc = parse_doc(path)
        if not doc:
            skipped.append(f"{fn} (사건번호 없음)")
            continue

        try:
            chunks = chunk_doc(doc)
        except UnknownCaseCode as e:
            skipped.append(f"{fn} ({e})")
            continue

        if not chunks:
            skipped.append(f"{fn} (임베딩 대상 섹션 없음)")
            continue

        dup = [c["vector_id"] for c in chunks if c["vector_id"] in seen_ids]
        if dup:
            skipped.append(f"{fn} (벡터 ID 충돌: {dup[0]})")
            continue
        seen_ids.update(c["vector_id"] for c in chunks)

        total_chunks += len(chunks)
        if len(samples) < 5:
            samples.append({**chunks[0], "case_no": doc["case_no"]})

        if args.dry_run:
            continue

        embeddings = embed_texts([c["embed_text"] for c in chunks], openai_client)
        time.sleep(0.2)

        for chunk, emb in zip(chunks, embeddings):
            meta = {
                "source_type": SOURCE_TYPE,
                "title": doc["title"][:200],
                "section": chunk["section"],
                "case_no": doc["case_no"],
                "court": doc["court"][:30],
                "date": doc["date"][:20],
                "chunk_index": chunk["chunk_index"],
                "chunk_text": chunk["chunk_text"][:900],
                "text": chunk["chunk_text"][:900],
            }
            if doc.get("topics"):
                meta["topics"] = doc["topics"]
            pending.append({
                "id": chunk["vector_id"],
                "values": emb,
                "metadata": meta,
            })

        if len(pending) >= UPSERT_BATCH:
            index.upsert(vectors=pending, namespace=NAMESPACE)
            pending = []
            time.sleep(0.1)

    if pending and not args.dry_run:
        index.upsert(vectors=pending, namespace=NAMESPACE)

    print(f"처리 파일: {len(md_files) - len(skipped)}개")
    print(f"총 청크: {total_chunks}개")
    print(f"고유 벡터 ID: {len(seen_ids)}개  (충돌 {total_chunks - len(seen_ids)}건)")
    if skipped:
        print(f"\n스킵 {len(skipped)}건:")
        for s in skipped[:15]:
            print(f"  - {s}")

    print("\n── 샘플 청크 ──")
    for s in samples:
        preview = s["chunk_text"][:120].replace("\n", " ")
        print(f"[{s['vector_id']}] {s['section']}")
        print(f"  {preview}...\n")

    print(f"{'=' * 62}")
    print(f"=== 완료 {'(DRY RUN)' if args.dry_run else ''} ===")
    print(f"{'=' * 62}\n")


if __name__ == "__main__":
    main()
