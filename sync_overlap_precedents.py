#!/usr/bin/env python3
"""교재 인용 ∩ 기존 판례 코퍼스 겹침분의 laborlaw-v2 동기화 유틸.

배경(precedent-corpus-followup 설계 §1): 교재 인용 판례와 겹친 기존 266건 중
139건은 프로덕션이 조회하지 않는 `precedent` NS에만 벡터가 있어 검색 불가였고,
127건은 구버전 contextual 업로드(`ctx_precedent_{게시글ID}_c{n}`)로 검색은 되나
쟁점 태그가 없다. 해법은 266건 전체를 법제처에서 재수집해 기존 파이프라인
(`precedent_{사건번호}` ID)으로 통일 업로드하고, **대체에 성공한 건의 ctx
구벡터만** 명시 ID로 삭제하는 것.

두 하위 명령이 사건번호↔게시글ID 매핑 로직을 단일 소유한다:

  python3 sync_overlap_precedents.py --emit-targets
      교재 인용 ∩ 기존 코퍼스를 재계산해 수집 대상 CSV 생성
      → output_판례_보강/_겹침대상.csv (사건번호,법원,게시글ID)

  python3 sync_overlap_precedents.py --delete-ctx --dry-run   # 대상 확인만
  python3 sync_overlap_precedents.py --delete-ctx             # 실삭제

로컬 전용: --emit-targets는 교재 원본(output_노동법교재/, gitignore)이 필요해
이 머신에서만 실행 가능하다. 삭제 안전 규칙은 설계 §2.3 (5종).
"""

from __future__ import annotations

import os
import re
import csv
import sys
import json
import time
import argparse
import unicodedata

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CORPUS_DIR = os.path.join(BASE_DIR, "output_법원 노동판례")
ENRICH_DIR = os.path.join(BASE_DIR, "output_판례_보강")
TARGETS_CSV = os.path.join(ENRICH_DIR, "_겹침대상.csv")
PROGRESS_FILE = os.path.join(ENRICH_DIR, "_progress.json")
DELETED_LOG = os.path.join(ENRICH_DIR, "_ctx_deleted.json")

NAMESPACE = "laborlaw-v2"
DELETE_BATCH = 1000   # Pinecone delete(ids=) 1회 상한

CASE_NO_RE = re.compile(r"(\d{2,4}[가-힣]{1,4}\d+)")


# ── 매핑 산출 (단일 소유) ─────────────────────────────────────────────────────

def corpus_case_map() -> dict[str, tuple[str, str | None]]:
    """기존 판례 코퍼스: 대표 사건번호 → (파일명, 게시글ID|None).

    게시글ID = 파일명 선두 숫자(nodong.kr 크롤 출신, ctx 벡터 보유).
    사건번호 선두 파일(upload_new_precedents 출신)은 None — ctx 벡터가 없어
    삭제 대상이 될 수 없다.
    """
    from fetch_court_precedents import extract_representative_case_no

    out: dict[str, tuple[str, str | None]] = {}
    for root, _, files in os.walk(CORPUS_DIR):
        for fn in files:
            if fn.startswith("_") or not fn.endswith(".md"):
                continue
            try:
                with open(os.path.join(root, fn), encoding="utf-8") as f:
                    text = unicodedata.normalize("NFC", f.read())
            except Exception:
                continue
            case_no = extract_representative_case_no(text, fn)
            if not case_no or case_no in out:
                continue
            nfc_name = unicodedata.normalize("NFC", fn)
            m = re.match(r"(\d+)_", nfc_name)
            post_id = m.group(1) if m and not CASE_NO_RE.match(nfc_name) else None
            out[case_no] = (fn, post_id)
    return out


def book_cited_cases() -> set[str]:
    """교재 본문에서 인용 사건번호 전체 (공백 표기·OCR 보정 포함)."""
    from enrich_court_precedents import SPACED_CASE_RE
    from fetch_court_precedents import OCR_FIXES
    from pinecone_upload_textbook import load_body, SOURCE_FILE

    body = unicodedata.normalize("NFC", load_body(SOURCE_FILE))
    cases = set()
    for m in SPACED_CASE_RE.finditer(body):
        no = "".join(m.groups())
        cases.add(OCR_FIXES.get(no, no))
    return cases


def resolve_court(case_no: str) -> str:
    return "헌법재판소" if "헌" in case_no else "대법원"


# ── 삭제 대상 산출 (순수 함수 — 오프라인 테스트 대상) ────────────────────────

def select_deletion_targets(
    targets: list[dict], fetched: dict[str, str]
) -> list[tuple[str, str]]:
    """삭제 대상 = 수집 성공 ∩ 게시글ID 보유 (설계 §2.3 규칙 1).

    수집 실패분은 ctx 벡터가 유일한 검색 경로이므로 제외한다.

    Returns: [(사건번호, 게시글ID), ...]
    """
    out = []
    for row in targets:
        case_no = unicodedata.normalize("NFC", row["사건번호"].strip())
        post_id = (row.get("게시글ID") or "").strip()
        if not post_id:
            continue
        if case_no not in fetched:
            continue
        out.append((case_no, post_id))
    return out


def valid_ctx_id(vector_id: str, post_id: str) -> bool:
    """prefix 나열 결과 재검증 (설계 §2.3 규칙 2 — 부분일치 오폭 차단)."""
    return re.fullmatch(rf"ctx_precedent_{re.escape(post_id)}_c\d+", vector_id) is not None


# ── 명령 구현 ─────────────────────────────────────────────────────────────────

def emit_targets() -> None:
    print("교재 인용 추출 중...")
    cited = book_cited_cases()
    print(f"  인용 사건번호: {len(cited)}개")

    print("기존 코퍼스 대표 사건번호 수집 중...")
    corpus = corpus_case_map()
    print(f"  코퍼스 문서: {len(corpus)}개")

    overlap = sorted(cited & set(corpus))
    with_post = sum(1 for c in overlap if corpus[c][1])
    print(f"\n겹침: {len(overlap)}건 (ctx 게시글ID 보유 {with_post} / 미보유 {len(overlap) - with_post})")

    os.makedirs(ENRICH_DIR, exist_ok=True)
    with open(TARGETS_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["사건번호", "법원", "게시글ID"])
        for c in overlap:
            w.writerow([c, resolve_court(c), corpus[c][1] or ""])
    print(f"저장: {TARGETS_CSV}")


def delete_ctx(dry_run: bool) -> None:
    if not os.path.exists(TARGETS_CSV):
        sys.exit(f"[오류] 대상 CSV가 없습니다. --emit-targets를 먼저 실행: {TARGETS_CSV}")
    if not os.path.exists(PROGRESS_FILE):
        sys.exit(f"[오류] 수집 진행 파일이 없습니다: {PROGRESS_FILE}")

    with open(TARGETS_CSV, encoding="utf-8-sig") as f:
        targets = list(csv.DictReader(f))
    with open(PROGRESS_FILE, encoding="utf-8") as f:
        fetched = json.load(f).get("fetched", {})

    selected = select_deletion_targets(targets, fetched)
    print(f"삭제 후보: {len(selected)}건 (대상 {len(targets)}건 중 수집성공∩게시글ID)")
    if not selected:
        print("삭제할 것이 없습니다.")
        return

    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)
    from pinecone import Pinecone
    from app.config import resolve_index_name
    index = Pinecone(api_key=os.getenv("PINECONE_API_KEY")).Index(resolve_index_name())

    # index.list()는 SDK 버전에 따라 배치를 list[str], list[ListItem],
    # ListResponse(이터러블)로 준다 — 항목 단위로 id를 뽑아 전부 흡수한다.
    def _list_ids(prefix: str) -> list[str]:
        out: list[str] = []
        for batch in index.list(prefix=prefix, namespace=NAMESPACE):
            for item in batch:
                vid = item if isinstance(item, str) else getattr(item, "id", None)
                if isinstance(vid, str):
                    out.append(vid)
        return out

    from pinecone_upload_court_precedents import UnknownCaseCode, case_no_to_ascii

    # 라이브 prefix 나열 + 정규식 재검증 (설계 §2.3 규칙 2)
    # + 대체 벡터 존재 확인 — 수집 성공(fetched)은 업로드 성공을 함의하지
    #   않으므로, laborlaw-v2에 precedent_{사건번호} 벡터가 실재할 때만
    #   해당 건의 ctx를 삭제 대상에 넣는다. 미확인 건은 ctx가 유일한 검색
    #   경로일 수 있어 보류한다.
    plan: dict[str, list[str]] = {}
    held_back: list[str] = []
    for case_no, post_id in selected:
        try:
            ascii_no = case_no_to_ascii(case_no)
        except UnknownCaseCode:
            held_back.append(case_no)
            continue
        if not _list_ids(f"precedent_{ascii_no}_chunk_"):
            held_back.append(case_no)
            continue
        ids = [vid for vid in _list_ids(f"ctx_precedent_{post_id}_")
               if valid_ctx_id(vid, post_id)]
        if ids:
            plan[case_no] = sorted(ids)
    if held_back:
        print(f"대체 벡터 미확인으로 보류: {len(held_back)}건 — {held_back[:5]}")

    total = sum(len(v) for v in plan.values())
    print(f"라이브 확인: {len(plan)}건 / 벡터 {total}개")
    for case_no, ids in list(plan.items())[:5]:
        print(f"  {case_no}: {len(ids)}개  ({ids[0]} …)")

    if dry_run:
        print("\n(DRY RUN — 삭제하지 않음)")
        return

    # 삭제 전 전량 기록 (설계 §2.3 규칙 3 — 복구 경로)
    with open(DELETED_LOG, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    print(f"삭제 목록 기록: {DELETED_LOG}")

    before = index.describe_index_stats().namespaces[NAMESPACE].vector_count
    all_ids = [vid for ids in plan.values() for vid in ids]
    # 배치 중 실패해도 별도 원장은 두지 않는다 — Pinecone 삭제는 멱등이고,
    # 이 스크립트는 매 실행마다 라이브 ID를 다시 나열하므로 재실행하면
    # 이미 지워진 벡터는 목록에서 빠지고 남은 것만 다시 삭제된다.
    for i in range(0, len(all_ids), DELETE_BATCH):
        try:
            index.delete(ids=all_ids[i:i + DELETE_BATCH], namespace=NAMESPACE)
        except Exception as e:
            done = i
            sys.exit(f"[오류] 배치 삭제 실패(완료 {done}/{len(all_ids)}개): {e}\n"
                     f"      전체 계획은 {DELETED_LOG}에 기록돼 있다. 재실행하면 "
                     f"남은 라이브 벡터만 다시 나열·삭제된다(멱등).")
        time.sleep(0.2)

    # stats 반영 지연 재시도 (설계 §2.4)
    expected = before - len(all_ids)
    for attempt in range(3):
        time.sleep(5)
        after = index.describe_index_stats().namespaces[NAMESPACE].vector_count
        if after == expected:
            break
    print(f"\n벡터 수: {before} → {after} (기대 {expected}) "
          f"{'✅' if after == expected else '⚠️ 불일치 — stats 지연 또는 검증 필요'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="겹침 판례 laborlaw-v2 동기화")
    parser.add_argument("--emit-targets", action="store_true", help="수집 대상 CSV 생성")
    parser.add_argument("--delete-ctx", action="store_true", help="수집 성공분의 ctx 구벡터 삭제")
    parser.add_argument("--dry-run", action="store_true", help="삭제 대상 확인만")
    args = parser.parse_args()

    if args.emit_targets == args.delete_ctx:
        sys.exit("--emit-targets 또는 --delete-ctx 중 하나를 지정하세요.")
    if args.emit_targets:
        emit_targets()
    else:
        delete_ctx(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
