#!/usr/bin/env python3
"""노동법 해설서가 인용하는 판례 사건번호를 뽑아 '수집 대상' CSV를 만든다.

해설서 본문은 저작물이지만 **사건번호는 사실 정보**라 추출·사용에 제약이 없다.
여기서 뽑은 목록으로 fetch_court_precedents.py가 법제처 공개 API에서 판례
원문을 받아온다(판결문은 저작권법 제7조 제3호에 따라 보호 대상이 아니다).

출력에서 제외되는 것:
  · 기존 코퍼스에 이미 있는 사건 (fetch의 L2 대조 로직 재사용)
  · 이전 사이클에서 법제처 미수록으로 확인된 사건 (_미발견.csv)

사용법:
  python3 extract_textbook_cases.py                      # 전권 → 통합 CSV
  python3 extract_textbook_cases.py --book juhae3        # 1권만
  python3 extract_textbook_cases.py --no-dedup           # 대조 없이 전량 출력
"""

from __future__ import annotations

import os
import re
import csv
import sys
import argparse
import unicodedata
from collections import Counter, defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_CSV = os.path.join(BASE_DIR, "output_노동법교재", "누락_판례목록_교재통합.csv")
NOT_FOUND_CSV = os.path.join(BASE_DIR, "output_판례_보강", "_미발견.csv")

# 사건부호 화이트리스트 — 없으면 조문 표기를 사건번호로 오인한다.
# 실측(주해Ⅲ): 화이트리스트 없이 308건 추출 시 113건이 노이즈였다
#   상위 오탐 '43조의2'(31회) '43조의4'(28) '43조의3'(19) '109조2'(7)
# 조문 해설서는 판례 수험서보다 조문 표기 밀도가 훨씬 높아 이 오염이 크다.
#
# 긴 부호를 먼저 나열해야 한다 — '다'가 '다카'보다 앞서면 87다카2803이
# '87다'로 잘린다.
CASE_CODES = (
    "다카|재다|재두|재누|"
    "헌바|헌마|헌가|헌라|헌나|헌사|헌아|"
    "가합|가단|가소|구합|구단|고합|고단|카합|카단|카기|비합|"
    "다|두|도|누|므|프|마|카|그|후|허|초|오|모|추|우|즈|드|나|노|라|인"
)
# \s*는 교재 원문의 '95다 53188'처럼 번호 내부에 공백이 낀 표기를 흡수한다.
# 앞뒤 경계로 긴 숫자열 중간의 오매칭을 막는다.
CASE_RE = re.compile(rf"(?<![0-9])(\d{{2,4}})\s*({CASE_CODES})\s*(\d+)(?![0-9])")

_HEONJAE_RE = re.compile(r"^\d{2,4}헌")


def normalize_body(body: str) -> str:
    """추출 전 본문 정규화 — NFC → OCR 오인식 정정.

    **치환은 반드시 추출 이전, 본문 단계**여야 한다. 추출 결과에 사후 remap을
    걸면 아무것도 고치지 못한다 — 오인식 부호('대', '도다')는 CASE_CODES
    화이트리스트에 없어 애초에 추출되지 않기 때문이다(실측: Win 본문에 오인식
    표기가 6회 있으나 사후 remap으로는 0건 정정).

    NFC가 치환보다 먼저다 — OCR_FIXES 키가 NFC라 NFD 원문에는 매치되지 않는다.
    이 프로젝트는 NFD로 474벡터를 잃은 전력이 있다(CLAUDE.md).

    생산 흐름과 테스트가 **같은 함수**를 써야 순서 역전이 회귀로 잡힌다.
    """
    from fetch_court_precedents import OCR_FIXES

    body = unicodedata.normalize("NFC", body)
    for wrong, right in OCR_FIXES.items():
        body = body.replace(wrong, right)
    return body


def extract_cases(body: str) -> Counter:
    """본문 → {사건번호: 인용횟수}. 정규화는 normalize_body()가 담당한다."""
    body = unicodedata.normalize("NFC", body)
    return Counter(f"{y}{code}{n}" for y, code, n in CASE_RE.findall(body))


def guess_court(case_no: str) -> str:
    """사건부호로 법원 추정.

    fetch_court_precedents.py::resolve_target()이 사건번호 부호로 최종
    판정하므로 이 컬럼이 틀려도 라우팅은 안전하다.
    """
    return "헌법재판소" if _HEONJAE_RE.match(case_no) else "대법원"


def load_not_found() -> set[str]:
    """이전 사이클에서 법제처 미수록으로 확인된 사건번호."""
    if not os.path.exists(NOT_FOUND_CSV):
        return set()
    with open(NOT_FOUND_CSV, encoding="utf-8-sig") as f:
        return {r["사건번호"].strip() for r in csv.DictReader(f) if r.get("사건번호")}


def main() -> None:
    parser = argparse.ArgumentParser(description="해설서 인용 판례 추출")
    parser.add_argument("--book", help="특정 서적만 (기본: 전권)")
    parser.add_argument("--no-dedup", action="store_true",
                        help="기존 코퍼스·미발견 대조 없이 전량 출력")
    parser.add_argument("--out", default=OUTPUT_CSV, help="출력 CSV 경로")
    args = parser.parse_args()

    from pinecone_upload_textbook import BOOKS, load_body
    from fetch_court_precedents import collect_existing_case_numbers, EXISTING_DIRS

    if args.book and args.book not in BOOKS:
        sys.exit(f"[오류] 알 수 없는 서적: {args.book} (가능: {', '.join(sorted(BOOKS))})")
    books = [BOOKS[args.book]] if args.book else list(BOOKS.values())

    print(f"\n{'=' * 62}")
    print("해설서 인용 판례 추출")
    print(f"{'=' * 62}\n")

    freq: Counter = Counter()
    origin: defaultdict[str, set[str]] = defaultdict(set)

    for book in books:
        if not os.path.exists(book.path):
            sys.exit(f"[오류] 원본이 없습니다: {book.path}")
        cases = extract_cases(normalize_body(load_body(book)))
        print(f"  {book.book_id}: 고유 {len(cases)}건 / 총인용 {sum(cases.values())}회")
        freq.update(cases)
        for c in cases:
            origin[c].add(book.book_id)

    print(f"\n합집합 고유 사건번호: {len(freq)}건")

    if args.no_dedup:
        targets = list(freq)
    else:
        print("  기존 코퍼스 스캔 중...")
        existing = collect_existing_case_numbers(EXISTING_DIRS)
        not_found = load_not_found()
        print(f"  기존 코퍼스 수록: {len(existing)}건  |  이전 미발견: {len(not_found)}건")
        after_existing = [c for c in freq if c not in existing]
        targets = [c for c in after_existing if c not in not_found]
        print(f"  → 기보유 차감 {len(freq) - len(after_existing)}건, "
              f"미발견 차감 {len(after_existing) - len(targets)}건")

    targets.sort(key=lambda c: (-freq[c], c))

    out_dir = os.path.dirname(args.out)
    if out_dir:                      # 파일명만 주면 dirname이 ""라 makedirs가 죽는다
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["사건번호", "법원", "인용횟수", "출처서적"])
        for c in targets:
            w.writerow([c, guess_court(c), freq[c], "+".join(sorted(origin[c]))])

    print(f"\n{'=' * 62}")
    print(f"수집 대상: {len(targets)}건 → {args.out}")
    print(f"상위 10: {[(c, freq[c]) for c in targets[:10]]}")
    print(f"{'=' * 62}\n")


if __name__ == "__main__":
    main()
