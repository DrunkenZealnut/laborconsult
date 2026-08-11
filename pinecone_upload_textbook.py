#!/usr/bin/env python3
"""노동법 해설서 marker 변환본을 Pinecone laborlaw-v2 네임스페이스에 업로드.

대상 서적은 BOOKS 레지스트리로 관리한다(현재 2권 — Win 노동법, 근로기준법 주해 Ⅲ).
각 서적의 단일 마크다운을 헤더 단위로 분할 → 청킹 → 임베딩 → 업로드한다.
crawl/metadata 단계 없이 upload 스크립트 하나로 처리하는 점은
pinecone_upload_counsel.py와 동일한 관례를 따름.

저작권 경계 — 본문은 비공개 검색 백엔드에만 적재되고 다음 가드가 함께 적용된다
(설계 §4):
  · G1~G3  답변의 축자 인용 금지·단독 근거 금지·서명 표기  (app/templates/prompts.py)
  · G4     동일 서적 청크 상한 3                            (app/core/rag.py::_cap_by_book)
  · G5     출처 라벨 "노동법 해설서"                         (rag.py + public/index.html)
가드 없이 이 스크립트만 실행하면 설계 전제가 깨진다.

사용법:
  python3 pinecone_upload_textbook.py --book juhae3 --dry-run   # 청킹만
  python3 pinecone_upload_textbook.py --book juhae3             # 1권 업로드
  python3 pinecone_upload_textbook.py --all                     # 전권 업로드
"""

from __future__ import annotations

import os
import re
import sys
import json
import time
import argparse
from dataclasses import dataclass, field

from dotenv import load_dotenv
from openai import OpenAI
from pinecone import Pinecone

load_dotenv()

# ── 설정 ──────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CORPUS_DIR = os.path.join(BASE_DIR, "output_노동법교재")

EMBED_MODEL = "text-embedding-3-small"
CHUNK_MAX = 700
CHUNK_OVERLAP = 80
EMBED_BATCH = 50
UPSERT_BATCH = 100
NAMESPACE = "laborlaw-v2"
SOURCE_TYPE = "textbook"

# 업로드한 벡터 ID 보존 경로. Pinecone Serverless는 메타데이터 필터 삭제를
# 지원하지 않으므로, 이 목록이 서적 단위 롤백의 유일한 수단이다(설계 §9).
UPLOADED_IDS_FILE = os.path.join(CORPUS_DIR, "_uploaded_ids.json")

# 헤딩 폐기율이 이 값을 넘으면 중단. 위생 규칙 오작동이나 새 서적의 마크다운
# 관례 차이로 섹션이 조용히 뭉개지는 것을 막는다(설계 §3.4).
MAX_HEADING_DROP_RATE = 0.10

_BOOK_ID_RE = re.compile(r"^[a-z0-9]+$")


@dataclass(frozen=True)
class Book:
    """업로드 대상 서적.

    book_id는 chunk_id의 구성요소라 구분자('_')를 포함할 수 없다 — 포함하면
    ID 파싱이 모호해진다.
    """
    book_id: str
    title: str
    path: str
    body_start: str            # 표지·목차 절단 마커
    ocr_fixes: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # 레지스트리 상수라 사실상 타입 불변식이다 — main()에서만 검사하면
        # BOOKS를 직접 import하는 소비자들이 검증을 통과하지 않는다.
        if not _BOOK_ID_RE.match(self.book_id):
            raise ValueError(
                f"book_id는 소문자·숫자만 허용합니다(chunk_id 파싱): {self.book_id!r}")


# marker OCR이 헤딩을 깨뜨린 건들. 유효 표제가 남아 있어 복원 가능한 것만
# 명시 치환한다 — 잔해만 남은 헤딩은 sanitize_heading()이 폐기한다.
# 범용 '보정' 로직을 두지 않는 이유: 오폐기는 섹션 경계 하나를 잃을 뿐이지만
# 오복원은 코퍼스에 오정보를 남긴다(설계 §3.1).
# 키는 '#' 접두사를 뗀 헤딩 텍스트다 — sanitize_heading()이 받는 형태와 같아야
# 한다. 한자는 _MEANING_RE에 포함되므로 이 잔해는 비율 판정을 통과한다(즉
# 명시 치환 없이는 그대로 살아남는다).
WIN_OCR_FIXES = {
    "기본원칙 高温 日本 日本 日本 日本 日本 日本 日本 日本 日本 日本 日本 日本 日本":
        "기본원칙",
}

JUHAE3_OCR_FIXES = {
    "**Ⅰ. 최저임금의 결정기준** 나는 다시 보도 모든 이 모든 바로 유료되었다.":
        "Ⅰ. 최저임금의 결정기준",
    "Ⅱ. 최저임금 결정절차 [○ 1901 19121212 - 1910 12 12 12 12 12 12 12 12 12 12 12 12 12":
        "Ⅱ. 최저임금 결정절차",
    "Ⅱ. 출국금지의 해제요청 800 2000 028 28 28 9 10 12":
        "Ⅱ. 출국금지의 해제요청",
    "$\\text{I\\hspace{-.1em}I}$ . 보조ㆍ지원 제한의 예외 $\\text{I\\hspace{-.1em}I}$ "
    "에서 대한 일정 INSES 주립(ASIA)에서 조용자 ① 고몽노동부장관은 제43조의2에 따른 제물사업주":
        "Ⅱ. 보조·지원 제한의 예외",
}

BOOKS: dict[str, Book] = {
    "win": Book(
        book_id="win",
        title="Win 노동법(2025, 공인노무사·5급공채·변호사시험 대비)",
        path=os.path.join(CORPUS_DIR, "Win노동법_merged.md"),
        # 표지·목차(0~17)는 marker OCR이 표 구조를 깨뜨려 글자 스프뿐이라 전량 제외.
        body_start="<!-- page: 18 -->",
        ocr_fixes=WIN_OCR_FIXES,
    ),
    "juhae3": Book(
        book_id="juhae3",
        title="근로기준법 주해 Ⅲ — 임금(제2판 수정증보판)",
        path=os.path.join(CORPUS_DIR, "근로기준법주해3_임금.md"),
        # 1~5페이지가 표지·목차. page 6 직후에 '# 제 3장 임 금'이 나온다.
        body_start="<!-- page: 6 -->",
        ocr_fixes=JUHAE3_OCR_FIXES,
    ),
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


# ── 헤딩 위생 처리 ────────────────────────────────────────────────────────────

_MARK_RE = re.compile(r"</?mark>")
_TEX_RE = re.compile(r"\$[^$]*\$")
_ARTICLE_RE = re.compile(r"(제\d+조(?:의\d+)?\s*\([^)]{1,30}\))")
_MEANING_RE = re.compile(r"[가-힣一-龥ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]")
# 비율 분모에서 공백·구두점을 뺀다 — 원문 헤딩은 '2. 요 건'처럼 자간 공백이
# 흔해서, 전체 길이를 분모로 쓰면 정상 표제가 오폐기된다(2/6=0.33 < 0.35).
_SIGNIF_RE = re.compile(r"[^\s.·…\-—,、]")

HEADING_MIN_LEN = 3
HEADING_MAX_LEN = 60
HEADING_MIN_RATIO = 0.35


def sanitize_heading(raw: str, ocr_fixes: dict[str, str]) -> str | None:
    """정제된 헤딩 문자열, 또는 폐기 대상이면 None.

    헤딩은 section 메타데이터이자 embed_text 접두사로 두 번 쓰이므로,
    OCR 잔해가 들어가면 검색 품질과 출처 표시가 함께 망가진다.

    Returns:
        정제된 헤딩. None이면 섹션 경계로 쓰지 않고 본문을 이웃 섹션에 흡수한다.
    """
    # ocr_fixes는 원문 문자열 기준으로 매칭한다 — 정제 후에 매칭하면 정제
    # 과정이 바뀔 때마다 치환 키가 조용히 무효가 된다.
    heading = ocr_fixes.get(raw.strip(), raw)

    s = _MARK_RE.sub("", heading).replace("**", "")

    # 조문 표기 추출은 길이 검사보다 먼저 — 잡음이 섞여도 59자처럼 상한을
    # 아슬아슬하게 통과하면 그대로 살아남는다.
    m = _ARTICLE_RE.search(s)
    if m:
        return re.sub(r"\s+", "", m.group(1))

    s = _TEX_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip(" .·…-—")

    if not (HEADING_MIN_LEN <= len(s) <= HEADING_MAX_LEN):
        return None

    denom = len(_SIGNIF_RE.findall(s))
    if denom == 0 or len(_MEANING_RE.findall(s)) / denom < HEADING_MIN_RATIO:
        return None
    return s


# ── 본문 파싱 ─────────────────────────────────────────────────────────────────

def load_body(book: Book) -> str:
    """표지·목차를 제외한 본문만 로드."""
    with open(book.path, "r", encoding="utf-8") as f:
        content = f.read()

    marker_pos = content.find(book.body_start)
    if marker_pos == -1:
        sys.exit(f"[오류] body_start 마커를 찾을 수 없습니다: {book.body_start!r} ({book.path})")
    body = content[marker_pos + len(book.body_start):]

    return _PAGE_COMMENT_RE.sub("", body)


def load_body_normalized(book: Book) -> str:
    """본문 + 헤딩 위생 처리를 마크다운 형태 그대로 반환.

    청킹이 아니라 '본문을 통째로 훑는' 소비자(enrich_court_precedents.py의
    표제 경로 추출)를 위한 경로다. 손상 헤딩은 줄 자체를 제거하되 본문은
    남긴다 — 위생 규칙을 두 곳에 복제하지 않기 위한 단일 출처.

    위생 처리 범위는 `_HEADING_RE`와 같은 **h1~h3**이다. enrich의 HEADING_RE는
    `#{1,6}`이라 h4~h6(win 249개, juhae3 29개)은 정제 없이 통과한다 — 청킹
    경계를 h1~h3으로 고정한 결과이며, 넓히면 chunk_id가 밀려 고아 벡터가 생긴다.
    """
    body = load_body(book)

    def _rewrite(m: re.Match) -> str:
        heading = sanitize_heading(m.group(2).strip(), book.ocr_fixes)
        return f"{m.group(1)} {heading}" if heading else ""

    return _HEADING_RE.sub(_rewrite, body)


def parse_sections(body: str, book: Book) -> tuple[list[dict], int, int]:
    """헤더(#/##/###) 단위로 섹션 분할. 손상 헤딩은 경계로 쓰지 않는다.

    폐기된 헤딩의 본문은 직전 섹션에 흡수한다(직전이 없으면 다음 섹션 앞에 붙인다).
    폐기 때문에 본문이 유실되는 경로는 없다.

    단, **첫 헤딩보다 앞선 텍스트는 어떤 섹션에도 들어가지 않는다**(기존 동작).
    body_start 마커 직후에 헤딩이 오는 것을 전제한 것이고, 두 서적 모두 그렇다.

    Returns:
        (sections, kept_headings, dropped_headings)
        sections: [{"heading": "...", "text": "..."}, ...]
        kept_headings는 len(sections)와 다르다 — 본문이 빈 섹션은 sections에서
        빠지기 때문이다. 폐기율 분모는 반드시 kept_headings를 써야 한다.
    """
    matches = list(_HEADING_RE.finditer(body))
    if not matches:
        return ([{"heading": "본문", "text": clean_text(body)}] if body.strip() else []), 0, 0

    sections: list[dict] = []
    dropped = 0
    pending = ""          # 직전 섹션이 없는 상태에서 폐기된 헤딩의 본문

    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        raw_text = body[start:end]

        heading = sanitize_heading(m.group(2).strip(), book.ocr_fixes)
        if heading is None:
            dropped += 1
            if sections:
                sections[-1]["text"] += "\n" + raw_text
            else:
                pending += raw_text + "\n"
            continue

        sections.append({"heading": heading, "text": pending + raw_text})
        pending = ""

    cleaned = []
    for s in sections:
        text = clean_text(s["text"])
        if text:
            cleaned.append({"heading": s["heading"], "text": text})
    return cleaned, len(sections), dropped


def check_drop_rate(book: Book, kept: int, dropped: int) -> None:
    """헤딩 폐기율 상한 검사 — 초과 시 중단."""
    total = kept + dropped
    if total == 0:
        # 게이트가 막으려던 실패(body_start 오배치)가 정확히 이 모습이다 —
        # 헤딩이 하나도 없으면 책 전체가 단일 섹션이 되므로 통과시키면 안 된다.
        sys.exit(f"[오류] '{book.book_id}' 본문에서 헤딩을 찾지 못했습니다 — "
                 f"body_start 마커({book.body_start!r})가 잘못됐을 수 있습니다.")
    rate = dropped / total
    print(f"  헤딩 {total}개 → 유지 {kept} / 폐기 {dropped} ({rate * 100:.1f}%)")
    if rate > MAX_HEADING_DROP_RATE:
        sys.exit(
            f"[오류] '{book.book_id}' 헤딩 폐기율 {rate * 100:.1f}%가 상한 "
            f"{MAX_HEADING_DROP_RATE * 100:.0f}%를 초과했습니다 — 위생 규칙 오작동 "
            f"또는 body_start 마커 오류일 수 있습니다. 업로드를 중단합니다."
        )


# ── 청킹 ─────────────────────────────────────────────────────────────────────

def chunk_section(section: dict, book: Book, section_idx: int) -> list[dict]:
    """섹션 1개 → 청크 리스트.

    chunk_id에 book_id가 반드시 들어가야 한다 — 없으면 서적 간 heading_idx가
    겹쳐 Pinecone upsert가 조용히 덮어쓴다(실측: Win 1,414 / 주해Ⅲ 463청크에서
    177건 충돌).

    section_idx는 '유지된 섹션'의 순번이다. 폐기 헤딩이 번호를 소비하면
    ocr_fixes 한 줄만 바뀌어도 뒤쪽 ID가 전부 밀려 고아 벡터가 생긴다.
    """
    chunks = []
    for idx, sub_text in enumerate(split_by_size(section["text"])):
        embed_text = f"제목: {book.title}\n섹션: {section['heading']}\n\n{sub_text}"
        chunks.append({
            "chunk_id": f"textbook_{book.book_id}_{section_idx:04d}_{idx}",
            "chunk_index": idx,
            "embed_text": embed_text,
            "chunk_text": sub_text,
            "section": section["heading"],
        })
    return chunks


def build_chunks(book: Book) -> list[dict]:
    """서적 1권 → 전체 청크 (임베딩 전 단계까지)."""
    body = load_body(book)
    sections, kept, dropped = parse_sections(body, book)
    check_drop_rate(book, kept, dropped)

    chunks = []
    for section_idx, section in enumerate(sections):
        chunks.extend(chunk_section(section, book, section_idx))
    print(f"  섹션 {len(sections)} → 청크 {len(chunks)}")
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


def record_uploaded_ids(book_id: str, ids: list[str]) -> None:
    """업로드 예정 벡터 ID를 서적별로 기록(롤백용, 설계 §9).

    **upsert보다 먼저** 호출한다 — 업로드 도중 죽으면 이미 적재된 벡터가
    기록 없이 남고, Pinecone Serverless는 메타데이터 필터 삭제를 지원하지
    않아 복구 수단이 사라진다. 존재하지 않는 ID의 delete는 무해하므로
    기록은 실제 적재분의 상위집합이어야 안전하다.

    같은 이유로 기존 기록과 **합집합**을 취한다. 청킹이 바뀌어 ID가 줄면
    교체 방식은 이전 실행의 고아 벡터를 추적 대상에서 지워버린다.
    """
    data: dict[str, list[str]] = {}
    if os.path.exists(UPLOADED_IDS_FILE):
        try:
            with open(UPLOADED_IDS_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            # 조용히 {}로 시작하면 다른 서적의 롤백 기록이 통째로 사라진다.
            backup = UPLOADED_IDS_FILE + ".bak"
            os.replace(UPLOADED_IDS_FILE, backup)
            sys.exit(f"[오류] 롤백 기록을 읽을 수 없습니다 ({e}). "
                     f"원본을 {backup}로 보존했습니다 — 확인 후 재실행하세요.")

    merged = sorted(set(data.get(book_id, [])) | set(ids))
    data[book_id] = merged
    with open(UPLOADED_IDS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"  벡터 ID {len(ids)}건 기록(누적 {len(merged)}): {UPLOADED_IDS_FILE}")


def upload_book(book: Book, chunks: list[dict], openai_client: OpenAI, index) -> None:
    """청크 → 임베딩 → upsert."""
    # 롤백 기록이 먼저다 — 중간에 죽어도 적재분이 추적 대상에 남는다.
    record_uploaded_ids(book.book_id, [c["chunk_id"] for c in chunks])

    pending: list[dict] = []

    for i in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[i:i + EMBED_BATCH]
        embeddings = embed_texts([c["embed_text"] for c in batch], openai_client)

        # zip은 길이가 다르면 남는 쪽을 조용히 버린다 — 부분 성공은 오류로 처리.
        if len(embeddings) != len(batch):
            sys.exit(f"[오류] 임베딩 수 불일치: {len(embeddings)} != {len(batch)} — 업로드 중단")

        for chunk, emb in zip(batch, embeddings):
            pending.append({
                "id": chunk["chunk_id"],
                "values": emb,
                "metadata": {
                    "source_type": SOURCE_TYPE,
                    "book_id": book.book_id,
                    "title": book.title[:200],
                    "section": chunk["section"][:80],
                    "chunk_index": chunk["chunk_index"],
                    "chunk_text": chunk["chunk_text"][:900],
                    "text": chunk["chunk_text"][:900],
                },
            })

        while len(pending) >= UPSERT_BATCH:
            index.upsert(vectors=pending[:UPSERT_BATCH], namespace=NAMESPACE)
            del pending[:UPSERT_BATCH]
            time.sleep(0.1)

        time.sleep(0.2)

    if pending:
        index.upsert(vectors=pending, namespace=NAMESPACE)


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="노동법 해설서 Pinecone 업로드")
    parser.add_argument("--book", choices=sorted(BOOKS), help="업로드할 서적 ID")
    parser.add_argument("--all", action="store_true", help="BOOKS 전권 업로드")
    parser.add_argument("--dry-run", action="store_true", help="청킹만 수행")
    # --reset 없음: laborlaw-v2는 판례 등 다른 소스와 공유하는 네임스페이스라
    # delete_all이 전체를 날린다. Pinecone Serverless는 메타데이터 필터 삭제를
    # 지원하지 않으므로 source_type별 부분 삭제도 불가 — 재업로드는 결정적
    # chunk_id의 upsert 덮어쓰기로 해결한다.
    args = parser.parse_args()

    if not args.book and not args.all:
        parser.error("--book <id> 또는 --all 중 하나가 필요합니다.")

    targets = list(BOOKS.values()) if args.all else [BOOKS[args.book]]

    # 전량 사전 검사 — --all에서 1권을 업로드(임베딩 비용 + 벡터 적재)한 뒤
    # 2권 파일 부재로 죽는 것을 막는다.
    for book in targets:
        if not os.path.exists(book.path):
            sys.exit(f"[오류] 원본 파일이 없습니다: {book.path}")

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

    print(f"\n{'=' * 62}")
    print(f"노동법 해설서 업로드 {'(DRY RUN)' if args.dry_run else ''}")
    print(f"네임스페이스: {NAMESPACE}  |  source_type: {SOURCE_TYPE}")
    print(f"대상: {', '.join(b.book_id for b in targets)}")
    print(f"{'=' * 62}\n")

    all_ids: set[str] = set()
    total_chunks = 0

    for book in targets:
        print(f"── {book.book_id}: {book.title}")
        chunks = build_chunks(book)
        total_chunks += len(chunks)

        # 서적 간 ID 충돌은 조용한 데이터 유실이라 업로드 전에 확정적으로 막는다.
        ids = {c["chunk_id"] for c in chunks}
        collision = all_ids & ids
        if collision:
            sys.exit(f"[오류] chunk_id 충돌 {len(collision)}건 "
                     f"(예: {sorted(collision)[:3]}) — 업로드 중단")
        all_ids |= ids

        for c in chunks[:2]:
            preview = c["chunk_text"][:110].replace("\n", " ")
            print(f"    [{c['chunk_id']}] {c['section']}\n      {preview}...")

        if not args.dry_run:
            upload_book(book, chunks, openai_client, index)
        print()

    print(f"{'=' * 62}")
    print(f"총 청크 수: {total_chunks}  |  고유 벡터 ID: {len(all_ids)}")
    print(f"=== 완료 {'(DRY RUN)' if args.dry_run else ''} ===")
    print(f"{'=' * 62}\n")


if __name__ == "__main__":
    main()
