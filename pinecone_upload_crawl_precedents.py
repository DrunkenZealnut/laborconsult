#!/usr/bin/env python3
"""크롤 판례(output_법원 노동판례/) 중 프로덕션 검색에 도달하지 않는 문서를
laborlaw-v2에 적재한다.

**왜 별도 스크립트인가.** 이 코퍼스는 letec(`output_판례_보강/`)과 문서 구조가
다르다 — 법제처 API 산출물은 `판시사항`/`판결요지`/`참조조문` 섹션을 갖지만,
크롤분은 법원 판결문 **전문**(`【주 문】`·`【이 유】`)이라
`pinecone_upload_court_precedents.EMBED_SECTIONS`가 **318건 전부 0건 매칭**한다
(2026-09-14 실측). 그 파일에 분기를 넣으면 두 코퍼스의 청킹 규약이 한 곳에서
얽히고 `EMBED_SECTIONS` 변경 압력이 생긴다.

**EMBED_SECTIONS 규약을 위반하지 않는다.** 그 상수가 전문을 제외한 근거는 둘인데
(`..._court_precedents.py:58`) 이 대상에는 성립하지 않는다:
  · 크기 — 규약이 상정한 52,867자(75청크)와 달리 중앙값 3,770자
  · 보일러플레이트 — 【】 블록 구조로 제거 가능(letec에는 그 수단이 없다)
게다가 letec은 "전문 대신 요지를 쓴다"는 선택이지만 여기는 **전문이 아니면
적재 자체가 0건**이다.

저작권 경계: 대상은 아카이브 게이트가 `verbatim`으로 분류한 것만이다(판결문
원문, 저작권법 제7조 제3호 비보호). editorial(nodong.kr 편집 발췌)은 제외한다 —
게이트 판정을 **이 스크립트가 다시 하지 않고** data/precedent_archive/의
documents.csv를 읽는다. 재구현하면 2026-09-01 승인 절차 밖에서 editorial이
적재될 수 있다.

사용법:
  python3 pinecone_upload_crawl_precedents.py --dry-run   # 청킹 검증
  python3 pinecone_upload_crawl_precedents.py             # 적재
  python3 pinecone_upload_crawl_precedents.py --limit 20  # 부분 실행(재개)
"""

from __future__ import annotations

import os
import re
import csv
import sys
import time
import argparse
import unicodedata

from dotenv import load_dotenv
from openai import OpenAI

from vector_ledger import VectorLedger
# 사본 금지 — 원장·청킹 규약을 letec과 공유해야 두 코퍼스가 갈라지지 않는다.
from pinecone_upload_court_precedents import (
    case_no_to_ascii, clean_text, split_by_size, embed_texts,
    EMBED_MODEL, UPSERT_BATCH,
)

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CRAWL_DIR = os.path.join(BASE_DIR, "output_법원 노동판례")
ARCHIVE_DIR = os.path.join(BASE_DIR, "data", "precedent_archive")

# rag.py::NS_GROUPS가 실제로 조회하는 네임스페이스. 사장 NS(precedent/laborlaw)에
# 올리면 임베딩 비용을 쓰고도 답변에 영원히 쓰이지 않는다 — 이 사이클이 정리하는
# 대상이 정확히 그 상태다.
NAMESPACE = "laborlaw-v2"

# 기존 라벨 맵(rag.py + public/index.html)·법률근거 승격이 이미 아는 값.
# 새 값을 만들면 그 셋을 모두 갱신해야 하고 하나라도 빠지면 raw 값이 노출된다.
SOURCE_TYPE = "precedent"

UPLOADED_IDS_FILE = os.path.join(CRAWL_DIR, "_uploaded_ids.json")

# 그룹 키는 **letec과 같은 ASCII 사건번호**다(`2014da41520`). 한글로 두면
# archive_precedents.reverse_case_key가 해석하지 못해 인벤토리의 vec_chunks가
# 영영 0으로 남고, 그러면 select_targets()가 적재 후에도 같은 318건을 계속
# 반환해 **재실행이 전량을 재임베딩한다**(2026-09-14 실측).
_LEDGER = VectorLedger(
    UPLOADED_IDS_FILE,
    group_re=re.compile(r"^[A-Za-z0-9_]+$"),
    id_re_for=lambda case_key: re.compile(
        rf"^crawlprec_{re.escape(case_key)}_\d+$"),
)


# ── 본문 추출 ─────────────────────────────────────────────────────────────────

# **공백을 반드시 허용한다.** 원문은 `【이 유】`·`【원 고, 상고인】`처럼 자간
# 공백을 쓴다. `【이유】`만 찾으면 318건 전부 0건 매칭되고, 그 실패는 예외 없이
# 조용하다 — EMBED_SECTIONS가 0건 매칭이던 것을 이번에 발견한 경로와 같다.
_BLOCK_RE = re.compile(r"【\s*[^】]{1,20}\s*】")
_REASON_RE = re.compile(r"【\s*이\s*유\s*】")


def extract_reasoning(md: str) -> str | None:
    """판결문에서 `【이 유】` 블록만 추출. 없으면 None.

    당사자 표시(`【원 고, 상고인】` 등)·주문은 절차 보일러플레이트라 검색
    노이즈가 된다. 실측 428건의 당사자 블록이 그 대상이다.

    **다음 【】 블록 직전까지** 자른다. 실측상 315/318은 `【이 유】`가 마지막이라
    차이가 없지만, 3건(원심판결·이하생략·원고,피상고인)에서는 자르지 않으면
    보일러플레이트가 본문에 섞인다 — 다수가 무해하다고 규칙을 느슨하게 두면
    소수에서 조용히 샌다.
    """
    body = md.split("\n---\n", 1)
    body = body[1] if len(body) > 1 else md
    body = unicodedata.normalize("NFC", body)

    m = _REASON_RE.search(body)
    if not m:
        return None
    nxt = _BLOCK_RE.search(body, m.end())
    return clean_text(body[m.end(): nxt.start() if nxt else len(body)])


# ── 대상 선정 ─────────────────────────────────────────────────────────────────

def _read_csv(name: str) -> list[dict]:
    path = os.path.join(ARCHIVE_DIR, name)
    if not os.path.exists(path):
        sys.exit(f"[오류] 아카이브 산출물이 없습니다: {path}\n"
                 f"       python3 archive_precedents.py build 를 먼저 실행하세요.")
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _resolve(doc_id: str) -> str | None:
    """doc_id(확장자 없는 상대 경로) → 실제 파일. 한글 경로라 NFC/NFD 순회."""
    for form in ("NFC", "NFD"):
        p = os.path.join(BASE_DIR, unicodedata.normalize(form, doc_id))
        for cand in (p, p + ".md"):
            if os.path.exists(cand):
                return cand
    return None


def select_targets() -> list[dict]:
    """게이트 verbatim + 문서 보유 + 프로덕션 검색 불가.

    **게이트를 재구현하지 않는다** — documents.csv의 gate 열을 읽는다. 그 분류는
    2026-09-01에 표본 육안을 거쳐 승인됐고(crawl_gate.json), 규칙 변경 시
    GATE_RULE_VERSION으로 승인이 무효화되는 구조다. 독자 판정을 두면 그 절차
    밖에서 editorial(제3자 편집 저작물)이 적재될 수 있다.
    """
    inv = {r["case_no"]: r for r in _read_csv("inventory.csv")}
    unsearched = {
        c for c, r in inv.items()
        if r["doc_crawl"] not in ("", "0")
        and r["vec_chunks"] in ("", "0") and r["vec_ctx"] in ("", "0")
    }
    out = []
    for d in _read_csv("documents.csv"):
        if d["source"] != "crawl" or d["gate"] != "verbatim":
            continue
        if d["case_no"] not in unsearched:
            continue
        path = _resolve(d["doc_id"])
        if path is None:
            sys.exit(f"[오류] 문서를 찾을 수 없습니다: {d['doc_id']}")
        out.append({"case_no": d["case_no"], "title": d["title"],
                    "category": d["category"], "path": path})
    out.sort(key=lambda x: x["case_no"])
    return out


# ── 청킹 ─────────────────────────────────────────────────────────────────────

def chunk_doc(doc: dict) -> list[dict]:
    """문서 1건 → 청크 리스트. `【이 유】` 부재면 빈 리스트."""
    with open(doc["path"], encoding="utf-8") as f:
        md = f.read()
    reasoning = extract_reasoning(md)
    if not reasoning:
        return []

    case_key = case_no_to_ascii(doc["case_no"])
    prefix = f"[{doc['case_no']}] "
    chunks = []
    for idx, text in enumerate(split_by_size(reasoning)):
        chunks.append({
            "vector_id": f"crawlprec_{case_key}_{idx}",
            "chunk_index": idx,
            # **저장 본문에도 사건번호를 접두한다.** 인용 화이트리스트
            # (citation_validator)가 읽는 것이 chunk_text라, 여기 번호가 없으면
            # LLM이 이 판례를 근거로 써도 환각으로 판정돼 지워진다. 판결문 전문은
            # 서두에 사건 표시가 있어 첫 청크는 대개 통과하지만(실측 75%),
            # 2번째 이후 청크는 본문만 남아 누락된다 — 전 청크에 붙인다.
            # 출처 카드는 title만 쓰므로 UI에는 노출되지 않는다.
            "chunk_text": prefix + text,
            "embed_text": f"{doc['case_no']} {doc['title']}\n\n{text}",
        })
    return chunks


def parse_date(md: str) -> str:
    m = re.search(r"^\|\s*작성일\s*\|\s*(.+?)\s*\|", md, re.MULTILINE)
    return m.group(1).strip() if m else ""


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="크롤 판례 → laborlaw-v2 적재")
    ap.add_argument("--dry-run", action="store_true", help="청킹만 수행")
    ap.add_argument("--limit", type=int, help="처리할 최대 문서 수(재개 지원)")
    # --allow-large-prune 없음: 최초 적재라 이전 집합이 없고, 규격 변경 시에만
    # 필요한 플래그를 미리 만들면 오용 경로만 생긴다.
    args = ap.parse_args()

    targets = select_targets()
    if args.limit:
        targets = targets[:args.limit]

    print(f"\n{'=' * 62}")
    print(f"크롤 판례 적재 {'(DRY RUN)' if args.dry_run else ''}")
    print(f"네임스페이스: {NAMESPACE}  |  source_type: {SOURCE_TYPE}")
    print(f"대상: {len(targets)}건 (게이트 verbatim · 검색 불가)")
    print(f"{'=' * 62}\n")

    groups: dict[str, list[str]] = {}
    built: list[tuple[dict, list[dict], str]] = []
    skipped: list[str] = []

    for doc in targets:
        chunks = chunk_doc(doc)
        if not chunks:
            skipped.append(doc["case_no"])
            continue
        with open(doc["path"], encoding="utf-8") as f:
            date = parse_date(f.read())
        groups[case_no_to_ascii(doc["case_no"])] = [c["vector_id"] for c in chunks]
        built.append((doc, chunks, date))

    total = sum(len(c) for _, c, _ in built)
    print(f"문서 {len(built)}건 → 청크 {total}개")
    if skipped:
        # 조용히 넘기지 않는다 — 크롤 형식이 바뀌면 0건 적재가 되고, 그 실패는
        # 성공 메시지와 구분되지 않는다.
        print(f"⚠️  【이 유】 부재로 스킵: {len(skipped)}건 {skipped[:5]}")

    ids = [c["vector_id"] for _, cs, _ in built for c in cs]
    if len(set(ids)) != len(ids):
        sys.exit(f"[오류] vector_id 중복 {len(ids) - len(set(ids))}건 — 적재 중단")

    for doc, cs, _ in built[:2]:
        print(f"    [{cs[0]['vector_id']}] {doc['case_no']} {doc['title'][:34]}")
        print(f"      {cs[0]['chunk_text'][:96]}...")

    if args.dry_run:
        print(f"\n{'=' * 62}\n=== 완료 (DRY RUN) ===\n{'=' * 62}\n")
        return

    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        sys.exit("[오류] OPENAI_API_KEY가 설정되지 않았습니다.")
    client = OpenAI(api_key=openai_key)

    from app.config import open_offline_index
    index = open_offline_index()

    # 롤백 기록이 upsert보다 **먼저** — 중간에 죽어도 적재분이 추적에 남는다.
    previous = _LEDGER.record(groups)
    print(f"  벡터 ID {len(ids)}건 기록: {UPLOADED_IDS_FILE}")

    pending = []
    for doc, cs, date in built:
        embeddings = embed_texts([c["embed_text"] for c in cs], client)
        if len(embeddings) != len(cs):
            sys.exit(f"[오류] 임베딩 수 불일치: {len(embeddings)} != {len(cs)} "
                     f"({doc['case_no']}) — 중단, 재실행으로 재개")
        for c, emb in zip(cs, embeddings):
            pending.append({
                "id": c["vector_id"],
                "values": emb,
                "metadata": {
                    "source_type": SOURCE_TYPE,
                    "title": doc["title"][:200],
                    "section": "이유",
                    "case_no": doc["case_no"],
                    "court": "대법원",
                    "date": date[:20],
                    "category": doc["category"][:30],
                    "chunk_index": c["chunk_index"],
                    # 양쪽을 채운다 — rag.py::_query_namespaces가 text/chunk_text
                    # 이중 폴백인 것은 NS에 두 스키마가 섞여 있기 때문이고,
                    # 한쪽만 채우면 content가 빈 채 흘러가 조용히 버려진다.
                    "chunk_text": c["chunk_text"][:900],
                    "text": c["chunk_text"][:900],
                },
            })
        while len(pending) >= UPSERT_BATCH:
            index.upsert(vectors=pending[:UPSERT_BATCH], namespace=NAMESPACE)
            del pending[:UPSERT_BATCH]
            time.sleep(0.1)
        time.sleep(0.2)

    if pending:
        index.upsert(vectors=pending, namespace=NAMESPACE)

    # 전량 성공 후에만 정리 — upsert는 덮어쓸 뿐 지우지 않는다.
    _LEDGER.prune(groups, previous, index, NAMESPACE,
                  batch_size=UPSERT_BATCH, label="crawl precedent")
    _LEDGER.finalize(groups)

    print(f"\n{'=' * 62}")
    print(f"적재 완료: 문서 {len(built)}건 · 청크 {total}개")
    print(f"{'=' * 62}\n")


if __name__ == "__main__":
    main()
