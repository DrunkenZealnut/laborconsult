#!/usr/bin/env python3
"""수험서 목차 체계에서 '관련 쟁점'만 추출해 수집 판례(output_판례_보강/)에 태깅.

저작권 경계: 저자의 해설 문장은 요약·의역 형태로도 가져오지 않는다 — 요약이
원문 표현과 실질적 유사성을 유지하면 2차적저작물 문제가 남는다. 여기서 추출하는
것은 "어느 표제(쟁점) 아래에서 어느 판례를 인용하는가"라는 사실 정보뿐이고,
표제 자체는 노동법 문헌 공통의 표준 강학상 분류(제N절·쟁점명)다.

입력:  pinecone_upload_textbook.BOOKS 전권의 목차 체계 (gitignore, 로컬 전용)
대상:  output_판례_보강/*.md — 메타 테이블 바로 아래에 `## 관련 쟁점` 섹션 삽입
       (멱등: 재실행 시 기존 섹션을 교체)

**전권을 순회한다.** 한때 `BOOKS["win"]` 하나로 고정돼 있었고, 그래서 다른 서적이
인용하는 판례는 수집해도 태그가 붙지 않았다(2026-09-05 실측: yeoncha 신규 10건
전원 0태그). 서적이 늘수록 격차가 벌어지는 구조라 순회로 바꿨다.

병합 규칙 — 태그는 임베딩 텍스트의 접두사가 되므로 **결정적이어야 한다**:
  · 서적 순서는 BOOKS의 선언 순서(win → juhae3 → gaebyeol → ironpanrye → yeoncha)
  · 동일 라벨은 최초 1회만, 상한 MAX_TOPICS_PER_CASE는 **병합 후**에 적용
  · 서적별로 따로 색인한다 — 본문을 이어붙이면 앞 서적의 편/절 상태가 다음 서적의
    첫 표제 앞 구간으로 새어 엉뚱한 상위 표제가 붙는다
  · 대상 서적 중 하나라도 원본이 없으면 중단한다. 조용히 건너뛰면 같은 명령이
    실행 환경에 따라 **다른 태그**를 만들고, 그 차이를 알아챌 방법이 없다

사용법:
  python3 enrich_court_precedents.py --dry-run   # 커버리지만 보고
  python3 enrich_court_precedents.py             # 전권 기준으로 md에 기록
  python3 enrich_court_precedents.py --book win  # 특정 서적만(진단용)
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
# `(가)`류 괄호 열거는 `가.`와 같은 부류인데 빠져 있었다 — Win 한 권만 볼 때는
# 드물어 드러나지 않다가 전권 순회에서 113개(전체 라벨의 3.3%, 주로 주해Ⅲ)로
# 나타났다. OCR이 '가'를 '개'·'사'·'대'로 읽으므로 특정 글자를 나열하지 않는다.
_ENUM_PREFIX = re.compile(
    r"^(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫIVXШ]+\s*[.,]?|\d+\s*[.)]|\(\d+\)|\([가-힣]\)|[가-힣]\s*\.)\s*"
)

# 판례 인용을 소제목으로 쓰는 편집(ironpanrye는 판례가 소제목 단위다)에서 나오는
# 표제. **쟁점 라벨로 쓰면 안 된다** — 태그는 임베딩 텍스트의 접두사이므로, 사건 X의
# 태그에 사건 Y의 번호가 실리면 X가 Y 질의에 검색되고 그 번호가 LLM 컨텍스트까지
# 간다(citation_validator가 다루는 환각 인용과 같은 종류의 오염이다). 자기 자신의
# 번호가 붙는 경우는 동어반복이라 정보가 0이다.
# 실측(2026-09-05): 전권 순회 시 ironpanrye 라벨 1,059개 중 665개(62.8%)가 이 형태.
_CITATION_SUB_RE = re.compile(
    r"\d{2,4}\s*[가-힣]{1,4}\s*\d+"          # 사건번호
    r"|대법원\s*\d{4}|대판\s*\d{4}|헌재\s*\d{4}"
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
    if _CITATION_SUB_RE.search(sub):
        # 판례 인용을 표제로 쓰는 편집(이론판례 노동법은 판례가 소제목 단위다)에서
        # 사건번호가 쟁점 라벨로 올라온다. 상위 표제로 물러난다 — 라벨을 통째로
        # 버리면 그 판례의 진짜 절 표제까지 함께 잃는다.
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
    # 표지·목차 제외 + 헤딩 위생 처리 재사용 (단일 출처)
    from pinecone_upload_textbook import load_body_normalized, BOOKS
    from fetch_court_precedents import OCR_FIXES

    parser = argparse.ArgumentParser(description="판례에 교재 쟁점 태깅")
    parser.add_argument("--dry-run", action="store_true", help="커버리지만 보고")
    parser.add_argument("--book", choices=sorted(BOOKS),
                        help="특정 서적만 사용(진단용). 기본은 전권 순회 — "
                             "일부만 쓰면 전권 실행과 다른 태그가 나온다")
    args = parser.parse_args()

    books = [BOOKS[args.book]] if args.book else list(BOOKS.values())
    # 분할 스캔 서적은 조각이 여러 개다 — 첫 조각만 보면 나머지 부재를 놓치고,
    # 사전 검사의 목적(비싼 작업 전에 실패)이 무너진다.
    # 전량 사전 검사인 이유: 3권까지 태깅한 뒤 4권 부재로 죽으면 파일이 '일부
    # 서적 기준'으로 기록된 채 남고, 멱등 재실행도 그 상태를 정상으로 본다.
    for book in books:
        for path in book.paths:
            if not os.path.exists(path):
                sys.exit(f"[오류] 교재 원본이 없습니다({book.book_id}): {path}")
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

    # 서적별로 색인한 뒤 병합한다. 상한은 병합 후에 적용해야 서적 수가 늘어도
    # 태그 길이가 늘지 않는다 — 서적별로 상한을 걸고 합치면 5권에서 15개가 된다.
    index: dict[str, list[str]] = defaultdict(list)
    per_book: list[tuple[str, int]] = []
    targets = set(docs)
    for book in books:
        body = unicodedata.normalize("NFC", load_body_normalized(book))
        part = build_case_topic_index(body, targets, OCR_FIXES)
        for no, labels in part.items():
            for label in labels:
                if label not in index[no]:
                    index[no].append(label)
        per_book.append((book.book_id, len(part)))
    index = {no: labels[:MAX_TOPICS_PER_CASE] for no, labels in index.items()}

    tagged = sum(1 for no in docs if index.get(no))
    print(f"\n{'=' * 62}")
    print(f"관련 쟁점 태깅 {'(DRY RUN)' if args.dry_run else ''}")
    print(f"교재: {', '.join(f'{b}({n})' for b, n in per_book)}")
    print(f"판례 파일: {len(files)}개 (사건번호 식별 {len(docs)}개)")
    print(f"쟁점 매칭: {tagged}개  |  미매칭: {len(docs) - tagged}개")
    print(f"{'=' * 62}\n")

    # 변경 파일 수를 센다 — 태그가 바뀐 판례는 청크 텍스트가 바뀌므로 **재업로드
    # 대상**이다. 이 수치가 없으면 뒤이을 업로드·BM25 재빌드의 규모를 모른 채
    # 들어가게 된다. dry-run에서도 세므로 실행 전에 규모를 볼 수 있다.
    shown = changed = 0
    for no, (fn, md) in sorted(docs.items()):
        topics = index.get(no)
        new_md = insert_topics(md, topics or [])
        if new_md != md:
            changed += 1
            if not args.dry_run:
                with open(os.path.join(PRECEDENT_DIR, fn), "w",
                          encoding="utf-8") as f:
                    f.write(new_md)
        if topics and shown < 8:
            print(f"  {no}: {' | '.join(topics)}")
            shown += 1

    verb = "변경 예정" if args.dry_run else "변경"
    print(f"\n{verb} 파일: {changed}개 (태그 보유 {tagged}개 중) — "
          f"{'재업로드 대상' if changed else '재업로드 불요'}")
    print()


if __name__ == "__main__":
    main()
