#!/usr/bin/env python3
"""노동법 해설서 marker 변환본을 Pinecone laborlaw-v2 네임스페이스에 업로드.

대상 서적은 BOOKS 레지스트리로 관리한다(현재 3권 — Win 노동법, 근로기준법 주해 Ⅲ,
개별 노동법실무). 각 서적의 마크다운을 헤더 단위로 분할 → 청킹 → 임베딩 → 업로드한다.
원본 스캔이 여러 파일로 쪼개진 서적은 Book.extra_parts로 조각을 이어붙인다.
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
class BookPart:
    """스캔이 여러 파일로 쪼개진 서적의 후속 조각.

    조각마다 앞머리(속표지·중간 목차)의 위치가 다르므로 절단 마커를 따로 갖는다.
    """
    path: str
    body_start: str


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
    # 원본 스캔이 분할된 서적의 나머지 조각. 나열 순서가 곧 본문 순서다.
    # **뒤에만 추가할 것** — 중간에 끼우면 section_idx가 통째로 밀려 기존
    # chunk_id가 전부 바뀌고, 이전 벡터가 고아로 남는다(설계 §2.3의 ID 안정성).
    extra_parts: tuple[BookPart, ...] = ()

    def __post_init__(self) -> None:
        # 레지스트리 상수라 사실상 타입 불변식이다 — main()에서만 검사하면
        # BOOKS를 직접 import하는 소비자들이 검증을 통과하지 않는다.
        if not _BOOK_ID_RE.match(self.book_id):
            raise ValueError(
                f"book_id는 소문자·숫자만 허용합니다(chunk_id 파싱): {self.book_id!r}")

    @property
    def parts(self) -> tuple[BookPart, ...]:
        """본문 순서대로의 전체 조각 — 단일 파일 서적은 길이 1."""
        return (BookPart(self.path, self.body_start),) + tuple(self.extra_parts)

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(p.path for p in self.parts)


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

# marker가 '테'를 '데'로 읽은 건들. 이 책의 조직 단위가 '실무테마'다.
# 헤딩으로 잡힌 4건만 대상 — 나머지 31개 테마 제목은 스캔에서 장식 이미지라
# 애초에 헤딩이 되지 못했다.
# 이 4건은 뒤이어 하위 헤딩이 바로 오는 탓에 본문이 비어 섹션에서 탈락하므로
# 지금은 벡터 메타데이터에 나타나지 않는다. 그래도 두는 이유는
# load_body_normalized()를 쓰는 표제 경로 추출(enrich_court_precedents.py)이
# 이 헤딩을 그대로 읽고, 원본 재변환으로 구조가 바뀌면 바로 노출되기 때문이다.
GAEBYEOL_OCR_FIXES = {
    "실무데마 1. 근로기준법의 적용범위": "실무테마 1. 근로기준법의 적용범위",
    "실무데마 2. 근로자, 근로자 대표": "실무테마 2. 근로자, 근로자 대표",
    "실무데마 19.": "실무테마 19. 연소자, 청소년, 미성년자",
    "실무데마 35.": "실무테마 35. 근로시간·휴게·휴일 등의 적용특례",
}

# 스캔이 3파일로 분할된 서적. 각 조각의 앞머리는 속표지(해당 PART의 테마 목록)라
# 본문에서 제외한다 — 목차는 페이지 번호만 담고 있어 검색에 노이즈다.
_GAEBYEOL_DIR = os.path.join(CORPUS_DIR, "개별노동법실무1")


def _gaebyeol_md(name: str) -> str:
    return os.path.join(_GAEBYEOL_DIR, name, "_markdown", name, f"{name}.md")


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
    "gaebyeol": Book(
        book_id="gaebyeol",
        title="개별 노동법실무(최영우, 개정증보 12판)",
        # part1의 0~12페이지는 표지·차례·색인(용어→페이지 번호)이라 전량 제외.
        # page 13에서 '실무테마 1. 근로기준법의 적용범위'로 본문이 시작한다.
        path=_gaebyeol_md("part1"),
        body_start="<!-- page: 13 -->",
        # part2·part3는 page 0이 해당 PART의 속표지다.
        extra_parts=(
            BookPart(_gaebyeol_md("part2"), "<!-- page: 1 -->"),
            BookPart(_gaebyeol_md("part3"), "<!-- page: 1 -->"),
        ),
        ocr_fixes=GAEBYEOL_OCR_FIXES,
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
    """표지·목차를 제외한 본문만 로드. 분할 서적은 조각을 순서대로 이어붙인다.

    조각 하나라도 없거나 마커를 못 찾으면 중단한다 — 조용히 건너뛰면 책의
    중간이 빠진 채 업로드되고, 그 사실을 알아챌 방법이 없다.
    """
    segments = []
    for part in book.parts:
        if not os.path.exists(part.path):
            sys.exit(f"[오류] 원본 파일이 없습니다: {part.path}")
        with open(part.path, "r", encoding="utf-8") as f:
            content = f.read()

        marker_pos = content.find(part.body_start)
        if marker_pos == -1:
            sys.exit(f"[오류] body_start 마커를 찾을 수 없습니다: "
                     f"{part.body_start!r} ({part.path})")
        segments.append(content[marker_pos + len(part.body_start):])

    # 조각 경계에 빈 줄을 둔다 — 마지막 문단과 다음 조각의 첫 헤딩이 붙으면
    # _HEADING_RE(^ 기준)가 그 헤딩을 인식하지 못해 섹션 하나가 통째로 사라진다.
    return _PAGE_COMMENT_RE.sub("", "\n\n".join(segments))


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


def _read_ledger() -> dict[str, list[str]]:
    """롤백 원장 로드. 손상 시엔 백업 후 중단한다.

    조용히 {}로 시작하면 **다른 서적의 롤백 기록이 통째로 사라진다** —
    Pinecone Serverless는 메타데이터 필터 삭제를 지원하지 않아 이 목록이
    유일한 복구 수단이다. 빈 파일은 정상(최초 실행)으로 본다.
    """
    backup = UPLOADED_IDS_FILE + ".bak"

    if not os.path.exists(UPLOADED_IDS_FILE) or os.path.getsize(UPLOADED_IDS_FILE) == 0:
        # .bak만 남아 있다는 건 직전 실행이 손상을 감지하고 격리했다는 뜻이다.
        # 여기서 {}를 반환하면 이전 ID를 잃고 기존 고아 벡터를 영영 정리하지
        # 못한다 — 사람이 복구하거나 명시적으로 초기화할 때까지 막는다.
        if os.path.exists(backup):
            sys.exit(f"[오류] 손상 격리된 롤백 기록이 있습니다: {backup}\n"
                     f"       내용을 확인해 {UPLOADED_IDS_FILE}로 복구하거나, "
                     f"의도적 초기화라면 .bak을 삭제한 뒤 재실행하세요.")
        return {}

    def _abort(reason: str):
        os.replace(UPLOADED_IDS_FILE, backup)
        sys.exit(f"[오류] 롤백 기록이 올바르지 않습니다 ({reason}). "
                 f"원본을 {backup}로 보존했습니다 — 확인 후 재실행하세요.")

    try:
        with open(UPLOADED_IDS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        _abort(str(e))

    # 스키마 검증 — 이 값은 index.delete()로 들어간다. 형태가 어긋나면 엉뚱한
    # 벡터를 지우게 되고, 삭제는 되돌릴 수 없다.
    if not isinstance(data, dict):
        _abort(f"최상위가 dict가 아님: {type(data).__name__}")
    for book_id, ids in data.items():
        if not _BOOK_ID_RE.match(str(book_id)):
            _abort(f"book_id 형식 위반: {book_id!r}")
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            _abort(f"'{book_id}' 항목이 문자열 리스트가 아님")
        # 접두사만 보면 textbook_win_x_y 같은 잘못된 ID가 통과한다.
        # chunk_id 규격 전체를 확인한다: textbook_{book_id}_{section:04d}_{chunk}
        id_re = re.compile(rf"^textbook_{re.escape(book_id)}_\d{{4}}_\d+$")
        bad = [i for i in ids if not id_re.match(i)]
        if bad:
            _abort(f"'{book_id}' 항목에 chunk_id 규격 위반 {len(bad)}건 (예: {bad[:2]})")
    return data


def _write_ledger(data: dict[str, list[str]]) -> None:
    """원자적 교체로 기록 — 쓰기 중 죽어도 원장이 비지 않는다.

    truncate 후 쓰는 방식은 중단 시 빈 파일을 남기고, _read_ledger()가 그것을
    '최초 실행'으로 읽어 **이전 ID를 통째로 잃는다**. 그러면 기존 고아 벡터를
    영영 정리할 수 없다.
    """
    tmp = UPLOADED_IDS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, UPLOADED_IDS_FILE)


def record_uploaded_ids(book_id: str, ids: list[str]) -> set[str]:
    """업로드 예정 벡터 ID를 서적별로 기록(롤백용, 설계 §9).

    **upsert보다 먼저** 호출한다 — 업로드 도중 죽으면 이미 적재된 벡터가
    기록 없이 남고, Pinecone Serverless는 메타데이터 필터 삭제를 지원하지
    않아 복구 수단이 사라진다. 존재하지 않는 ID의 delete는 무해하므로
    기록은 실제 적재분의 상위집합이어야 안전하다.

    같은 이유로 기존 기록과 **합집합**을 취한다. 청킹이 바뀌어 ID가 줄면
    교체 방식은 이전 실행의 고아 벡터를 추적 대상에서 지워버린다.

    Returns:
        이전 기록 ID 집합 — 업로드 성공 후 prune_stale_vectors()가 차집합을
        삭제하는 데 쓴다.
    """
    data = _read_ledger()
    previous = set(data.get(book_id, []))
    merged = sorted(previous | set(ids))
    data[book_id] = merged
    _write_ledger(data)
    print(f"  벡터 ID {len(ids)}건 기록(누적 {len(merged)}): {UPLOADED_IDS_FILE}")
    return previous


def finalize_uploaded_ids(book_id: str, current_ids: list[str]) -> None:
    """업로드·정리가 모두 성공한 뒤 원장을 현재 집합으로 확정한다.

    이걸 하지 않으면 원장이 합집합으로 남아 다음 실행이 **이미 삭제한 ID를
    또 stale로 계산**한다. 삭제 자체는 멱등이라 무해하지만, 대량 삭제 가드가
    한 번 걸리면 원장이 그대로라 이후 실행이 매번 같은 지점에서 멈춘다.
    """
    data = _read_ledger()
    data[book_id] = sorted(current_ids)
    _write_ledger(data)


def prune_stale_vectors(book: Book, current_ids: list[str], previous_ids: set[str],
                        index, allow_large: bool = False) -> None:
    """이번 업로드에 없는 이전 chunk_id 벡터를 삭제한다.

    청킹이 줄면(`ocr_fixes` 추가로 섹션이 병합되는 등) 이전 실행의 벡터가
    Pinecone에 남아 **검색 결과에 계속 섞인다.** upsert는 덮어쓸 뿐 지우지
    않으므로 차집합을 명시 삭제해야 한다.

    업로드가 전부 성공한 뒤에만 호출한다 — 중간 실패 시 삭제하면 아직
    올리지 못한 벡터를 지울 수 있다. 삭제까지 성공하면 원장을 현재 집합으로
    확정한다(실패 시엔 합집합을 유지해 추적을 잃지 않는다).
    """
    stale = sorted(previous_ids - set(current_ids))
    if not stale:
        finalize_uploaded_ids(book.book_id, current_ids)
        return

    # 대량 삭제는 청킹 규격이 통째로 바뀐 신호다. 조용히 지우면 되돌릴 수 없다.
    # 탈출구를 '원장 비우기'로 두면 안 된다 — previous가 사라져 stale이 0이 되고
    # 고아 벡터가 영구히 남는다. 명시 플래그로만 통과시킨다.
    if not allow_large and len(stale) > len(current_ids) * 0.5:
        sys.exit(
            f"[오류] '{book.book_id}' 고아 벡터가 {len(stale)}건으로 현재 청크"
            f"({len(current_ids)})의 50%를 넘습니다 — chunk_id 규격이 바뀌었을 수 "
            f"있습니다. 의도한 변경이면 --allow-large-prune 으로 재실행하세요 "
            f"(원장을 직접 비우면 삭제 대상을 잃어 고아가 영구히 남습니다)."
        )

    for i in range(0, len(stale), UPSERT_BATCH):
        index.delete(ids=stale[i:i + UPSERT_BATCH], namespace=NAMESPACE)
    print(f"  고아 벡터 {len(stale)}건 삭제 (예: {stale[:2]})")
    finalize_uploaded_ids(book.book_id, current_ids)


def upload_book(book: Book, chunks: list[dict], openai_client: OpenAI, index,
                allow_large_prune: bool = False) -> None:
    """청크 → 임베딩 → upsert."""
    # 롤백 기록이 먼저다 — 중간에 죽어도 적재분이 추적 대상에 남는다.
    chunk_ids = [c["chunk_id"] for c in chunks]
    previous_ids = record_uploaded_ids(book.book_id, chunk_ids)

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

    # 전량 성공 후에만 정리 — upsert는 덮어쓸 뿐 지우지 않으므로, 청킹이 줄면
    # 이전 실행의 벡터가 남아 검색에 계속 섞인다.
    prune_stale_vectors(book, chunk_ids, previous_ids, index, allow_large_prune)


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="노동법 해설서 Pinecone 업로드")
    parser.add_argument("--book", choices=sorted(BOOKS), help="업로드할 서적 ID")
    parser.add_argument("--all", action="store_true", help="BOOKS 전권 업로드")
    parser.add_argument("--dry-run", action="store_true", help="청킹만 수행")
    parser.add_argument("--allow-large-prune", action="store_true",
                        help="고아 벡터가 현재 청크의 50%%를 넘어도 삭제 진행 "
                             "(chunk_id 규격을 의도적으로 바꿨을 때만)")
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
        for path in book.paths:
            if not os.path.exists(path):
                sys.exit(f"[오류] 원본 파일이 없습니다: {path}")

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
            upload_book(book, chunks, openai_client, index, args.allow_large_prune)
        print()

    print(f"{'=' * 62}")
    print(f"총 청크 수: {total_chunks}  |  고유 벡터 ID: {len(all_ids)}")
    print(f"=== 완료 {'(DRY RUN)' if args.dry_run else ''} ===")
    print(f"{'=' * 62}\n")


if __name__ == "__main__":
    main()
