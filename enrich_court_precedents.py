#!/usr/bin/env python3
"""수험서 목차 체계에서 '관련 쟁점'만 추출해 수집 판례(output_판례_보강/)에 태깅.

저작권 경계: 저자의 해설 문장은 요약·의역 형태로도 가져오지 않는다 — 요약이
원문 표현과 실질적 유사성을 유지하면 2차적저작물 문제가 남는다. 여기서 추출하는
것은 "어느 표제(쟁점) 아래에서 어느 판례를 인용하는가"라는 사실 정보뿐이고,
표제 자체는 노동법 문헌 공통의 표준 강학상 분류(제N절·쟁점명)다.

입력:  output_노동법교재/Win노동법_merged.md  (gitignore, 로컬 전용)
대상:  output_판례_보강/*.md — 메타 테이블 바로 아래에 `## 관련 쟁점` 섹션 삽입
       (멱등: 재실행 시 기존 섹션을 교체)

사용법:
  python3 enrich_court_precedents.py --dry-run   # 커버리지만 보고
  python3 enrich_court_precedents.py             # md 파일에 기록
"""

from __future__ import annotations

import os
import re
import sys
import argparse
import unicodedata
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRECEDENT_DIR = os.path.join(BASE_DIR, "output_판례_보강")

CASE_NO_RE = re.compile(r"(\d{2,4}[가-힣]{1,4}\d+)")
# 교재 원문엔 "95다 53188"처럼 번호 내부에 공백이 낀 표기가 있다. 공백 허용
# 패턴은 "2020년 5"류 오탐을 내지만, 대상 500건 집합 필터가 걸러낸다.
SPACED_CASE_RE = re.compile(r"(\d{2,4})\s*([가-힣]{1,4})\s*(\d{1,7})")
HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)

MAX_TOPICS_PER_CASE = 3

# 로마숫자·번호 등 표제 열거 접두사 (OCR이 Ⅲ을 Ш(키릴)로 읽는 사례 포함)
_ENUM_PREFIX = re.compile(
    r"^(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫIVXШ]+\s*[.,]?|\d+\s*[.)]|\(\d+\)|[가-힣]\s*\.)\s*"
)

# 단독으로는 쟁점 정보가 없는 범용 표제 — 절 표제만 남긴다.
_GENERIC_SUBS = (
    "서설", "의의", "내용", "효과", "기타", "학설", "판례", "검토의견",
    "문제의소재", "판례의입장", "판례의태도", "법적성질", "인정여부", "요건",
)


def _clean(t: str) -> str:
    t = unicodedata.normalize("NFC", t)
    t = re.sub(r"\s+", " ", t).strip(" ●◈■□◦·*—-")
    t = re.sub(r"[·.]{3,}.*$", "", t).strip()      # 목차 점선 잔재
    return t


def classify_heading(raw: str) -> tuple[str, str] | None:
    """표제 한 줄을 (종류, 텍스트)로 분류. 무의미하면 None.

    marker 변환이 #/##/### 레벨을 실제 위계와 무관하게 매기므로 레벨이 아니라
    텍스트 패턴으로 판별한다.
    """
    t = _clean(raw)
    if not t or t.startswith("Win 노동법"):
        return None
    m = re.match(r"^제\s*(\d+)\s*절\s*(.+)$", t)
    if m:
        title = _clean(m.group(2))
        return ("jeol", title) if title else None
    # 편 표제 — OCR로 '편'이 '면', 숫자가 ']'로 깨진 사례가 있다("제]편", "제2면")
    m = re.match(r"^제\s*[\d\]lI]*\s*[편면](?:\s+(.+))?$", t)
    if m:
        return ("pyeon", _clean(m.group(1) or ""))
    sub = _clean(_ENUM_PREFIX.sub("", t))
    norm = re.sub(r"\s+", "", sub)
    if not (2 <= len(sub) <= 40) or not re.search(r"[가-힣]", sub):
        return None
    if any(norm.startswith(g) for g in _GENERIC_SUBS):
        return ("generic", "")
    return ("sub", sub)


def build_case_topic_index(body: str, target_cases: set[str],
                           ocr_fixes: dict[str, str]) -> dict[str, list[str]]:
    """본문 1패스로 사건번호 → 인용 지점의 표제 경로(절 › 세부) 목록을 만든다."""
    events: list[tuple[int, str, str]] = []
    for m in HEADING_RE.finditer(body):
        events.append((m.start(), "h", m.group(1)))
    for m in SPACED_CASE_RE.finditer(body):
        events.append((m.start(), "c", "".join(m.groups())))
    events.sort(key=lambda e: e[0])

    pyeon: str | None = None
    jeol: str | None = None
    sub: str | None = None
    pending_pyeon = False
    topics: dict[str, list[str]] = defaultdict(list)

    for _, kind, val in events:
        if kind == "h":
            c = classify_heading(val)
            if c is None:
                continue
            k, text = c
            if pending_pyeon and k in ("sub", "jeol"):
                # 직전 편 표제가 제목 없이 깨진 경우("제]편") 다음 표제가 편 제목
                pending_pyeon = False
                if k == "sub":
                    pyeon = text
                    continue
            if k == "pyeon":
                if text:
                    pyeon = text
                    pending_pyeon = False
                else:
                    pending_pyeon = True
                jeol = sub = None
            elif k == "jeol":
                jeol = text
                sub = None
            elif k == "generic":
                sub = None
            else:
                sub = text
        else:
            no = unicodedata.normalize("NFC", val)
            no = ocr_fixes.get(no, no)
            if no not in target_cases:
                continue
            head = jeol or pyeon
            label = " › ".join(p for p in (head, sub) if p)
            if label and label not in topics[no] \
                    and len(topics[no]) < MAX_TOPICS_PER_CASE:
                topics[no].append(label)
    return dict(topics)


# ── 판례 md 갱신 ──────────────────────────────────────────────────────────────

_TOPIC_SECTION_RE = re.compile(r"## 관련 쟁점\n\n(?:- .*\n)+\n?")


def insert_topics(md: str, topics: list[str]) -> str:
    """메타 테이블 구분선 직후에 관련 쟁점 섹션 삽입(멱등)."""
    md = _TOPIC_SECTION_RE.sub("", md)
    if not topics:
        return md
    block = "## 관련 쟁점\n\n" + "\n".join(f"- {t}" for t in topics) + "\n\n"
    sep = "\n---\n\n"
    i = md.find(sep)
    if i == -1:
        return md + "\n" + block
    i += len(sep)
    return md[:i] + block + md[i:]


def file_case_no(md: str, filename: str) -> str | None:
    m = re.search(r"\|\s*사건번호\s*\|\s*([^|]+?)\s*\|", md)
    if m:
        f = CASE_NO_RE.search(unicodedata.normalize("NFC", m.group(1)))
        if f:
            return f.group(1)
    f = CASE_NO_RE.search(unicodedata.normalize("NFC", filename))
    return f.group(1) if f else None


def main() -> None:
    parser = argparse.ArgumentParser(description="판례에 교재 쟁점 태깅")
    parser.add_argument("--dry-run", action="store_true", help="커버리지만 보고")
    args = parser.parse_args()

    # 표지·목차 제외 + 알려진 OCR 표제 보정 재사용
    from pinecone_upload_textbook import load_body, SOURCE_FILE
    from fetch_court_precedents import OCR_FIXES

    if not os.path.exists(SOURCE_FILE):
        sys.exit(f"[오류] 교재 원본이 없습니다: {SOURCE_FILE}")
    if not os.path.isdir(PRECEDENT_DIR):
        sys.exit(f"[오류] 판례 디렉토리가 없습니다: {PRECEDENT_DIR}")

    files = sorted(f for f in os.listdir(PRECEDENT_DIR)
                   if f.endswith(".md") and not f.startswith("_"))
    docs: dict[str, tuple[str, str]] = {}      # case_no → (filename, md)
    for fn in files:
        with open(os.path.join(PRECEDENT_DIR, fn), encoding="utf-8") as f:
            md = f.read()
        no = file_case_no(md, fn)
        if not no:
            continue
        if no in docs:
            # 조용히 덮어쓰면 앞 파일만 태깅에서 빠지고 로그에 안 남는다.
            print(f"  [경고] 사건번호 중복 파일: {docs[no][0]} ↔ {fn} — 첫 파일 기준으로 태깅")
            continue
        docs[no] = (fn, md)

    body = unicodedata.normalize("NFC", load_body(SOURCE_FILE))
    index = build_case_topic_index(body, set(docs), OCR_FIXES)

    tagged = sum(1 for no in docs if index.get(no))
    print(f"\n{'=' * 62}")
    print(f"관련 쟁점 태깅 {'(DRY RUN)' if args.dry_run else ''}")
    print(f"판례 파일: {len(files)}개 (사건번호 식별 {len(docs)}개)")
    print(f"쟁점 매칭: {tagged}개  |  미매칭: {len(docs) - tagged}개")
    print(f"{'=' * 62}\n")

    shown = 0
    for no, (fn, md) in sorted(docs.items()):
        topics = index.get(no)
        if not topics:
            continue
        if shown < 8:
            print(f"  {no}: {' | '.join(topics)}")
            shown += 1
        if not args.dry_run:
            new_md = insert_topics(md, topics)
            if new_md != md:
                with open(os.path.join(PRECEDENT_DIR, fn), "w",
                          encoding="utf-8") as f:
                    f.write(new_md)

    if not args.dry_run:
        print(f"\n기록 완료: {tagged}개 파일에 관련 쟁점 삽입")
    print()


if __name__ == "__main__":
    main()
