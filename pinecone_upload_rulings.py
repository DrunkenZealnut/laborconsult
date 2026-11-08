#!/usr/bin/env python3
"""재결례(`output_재결례/{eiac,iaciac}/*.md`) → Pinecone laborlaw-v2 업로드 (source_type="ruling").

설계: docs/02-design/features/adjudication-corpus.design.md §4

**적재 대상은 프로덕션이 읽는 NS(`laborlaw-v2`)다.** 업로드 즉시 Dense 검색에 섞이므로 배선 PR(라벨·공공 쿼터·
인용 검증)이 배포된 **뒤에** 올린다(D13). 저작권: 재결은 저작권법 제7조 제3호 비보호 저작물 — 노출 가드 불요.

지킬 것(설계 §4):
  · ID `ruling_{agency}_{serial}_chunk_{idx}`, 원장 그룹 키 `{agency}_{serial}`(iaciac 사건번호 중복 2건) — D10.
  · 모든 청크 `text` 첫 줄은 머리글 `[{기관} {사건번호} · 의결 {YYYY.MM.DD} · {분류}]`(D11) — BM25 hit에는
    case_no가 없고 BM25는 text만 토큰화한다. 의결일자는 낡은 결정의 유일한 본문 신호다.
  · 이유는 소제목 단위로 자르되 **관계법령 절·소절은 제외**한다(D9) — 의결 당시 법령 전문이라 '재결례' 라벨로
    구 조문이 실리는 경로가 된다. 소제목 인식은 짧은 제목·어휘 목록·순차 번호 세 조건을 모두 본다(iaciac
    관계법령 소절 안의 조문 목 `가.~라.`가 소절로 오인됐다 — 설계 검증 H2).
  · 청구인·청구취지는 어떤 청크에도 넣지 않는다(D3·R6). PII 가림 목록(`_pii_redactions.json`)은 청킹 전에 적용한다.
  · `chunk_index`는 정수 — `build_bm25_corpus`가 `{"chunk_index": {"$gte": 0}}` 필터로 페이지를 돈다.

사용법:
  python3 pinecone_upload_rulings.py --dry-run                   # 집계·중단 조건(PII 미확인·잔존 태그·소제목 폴백)
  python3 pinecone_upload_rulings.py --agency eiac --limit 20
  python3 pinecone_upload_rulings.py                             # 전량 적재 + 고아 정리
  python3 pinecone_upload_rulings.py --allow-large-prune         # ID 규격을 바꿨을 때만
  python3 pinecone_upload_rulings.py --exclude-before 2016 --agency iaciac   # md를 _excluded/로 이동만(D2 축소)
  python3 pinecone_upload_rulings.py --prune-missing [--allow-large-prune] [--dry-run]
  python3 pinecone_upload_rulings.py --write-batch-ledger data/vector_ledgers/rulings_202611.json [--verify]
"""
from __future__ import annotations

import os
import re
import sys
import json
import time
import shutil
import hashlib
import argparse
import datetime as _dt
import unicodedata
from dataclasses import dataclass, field

from dotenv import load_dotenv

from vector_ledger import VectorLedger, atomic_write_json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)

# 청킹·임베딩·md 파서는 court 업로더가 단일 출처다(복사하면 드리프트 — 외부감사 M1).
from pinecone_upload_court_precedents import (   # noqa: E402
    CHUNK_MAX, CHUNK_OVERLAP, UPSERT_BATCH, clean_text, split_by_size, embed_texts,
    parse_meta, parse_sections,
)

SOURCE_DIR = os.path.join(BASE_DIR, "output_재결례")
EXCLUDED_DIR = os.path.join(SOURCE_DIR, "_excluded")
UPLOADED_IDS_FILE = os.path.join(SOURCE_DIR, "_uploaded_ids.json")
PII_REPORT_FILE = os.path.join(SOURCE_DIR, "_pii_report.json")
PII_REDACTIONS_FILE = os.path.join(SOURCE_DIR, "_pii_redactions.json")

NAMESPACE = "laborlaw-v2"
SOURCE_TYPE = "ruling"
AGENCIES = ("eiac", "iaciac")
HEADER_MAX = 160
TEXT_CAP = 1000          # 머리글(≤160) + 700 + 겹침이 든다
FALLBACK_LIMIT = 0.05    # `결론|판단` 소제목이 없는 문서 비율 상한(넘으면 소제목 규칙이 틀렸다는 뜻)


def make_vector_id(agency: str, serial: str, idx: int) -> str:
    return f"{SOURCE_TYPE}_{agency}_{serial}_chunk_{idx}"


_LEDGER = VectorLedger(
    UPLOADED_IDS_FILE,
    group_re=re.compile(r"^(eiac|iaciac)_\d+$"),
    id_re_for=lambda g: re.compile(rf"^{SOURCE_TYPE}_{re.escape(g)}_chunk_\d+$"),
)

# ── 소제목 분할(D9) ───────────────────────────────────────────────────────────

_TOP_RE = re.compile(r"^\s*(\d{1,2})\.\s*(\S.{0,60})$")
_SUB_RE = re.compile(r"^\s*([가-하])\.\s*(\S.{0,60})$")
# 어휘 목록은 1,051건 실측에서 뽑았다(2026-11-08). 빠져 있던 "원처분기관 처분 및 심사기관 결정이유"(276건)·"이 사건
# 재심사청구의 적법 여부"가 상위 소제목으로 인식되지 않아 그 뒤 번호가 전부 밀렸고, 관계법령 안의 "2. 업무상 질병"이
# 상위 절로 오인됐다(연쇄 실패 — 설계 검증 M4). 법조문 목록 항목(길고 문장형)은 길이 조건에서 걸러진다.
_HEADING_VOCAB_RE = re.compile(
    r"관계\s*법령|관련\s*법령|관계\s*법규|사실\s*관계|인정\s*사실|의학적\s*(소견|견해)|판\s*단|결\s*론|"
    r"사건\s*개요|주장|의견|처분\s*내용|처분\s*이유|결정(의)?\s*이유|결정\s*내용|심사\s*결과|진술\s*내용|"
    r"위법.{0,2}부당|부당성?\s*여부|적법\s*여부|쟁점|검토|경위"
)
_EXCLUDE_TITLE_RE = re.compile(r"^관계법령(의내용)?$|^관련법령$|^관계법규$")
_SUB_ORDER = "가나다라마바사아자차카타파하"
_FALLBACK_SIGNAL_RE = re.compile(r"결\s*론|판\s*단")
_IMAGE_PLACEHOLDER_RE = re.compile(r"\[이미지 생략[^\]]*\]")
IMAGE_ONLY_LIMIT = 300
# 잔존 태그 판정은 **알려진 HTML 태그 이름**만 — 본문의 `HORIZON<ALL>`(의료기기 규격)처럼 꺾쇠가 든 내용은 태그가 아니다
RESIDUAL_TAG_RE = re.compile(
    r"</?(?:img|span|div|p|br|table|tbody|thead|tr|td|th|font|b|i|u|strong|em|a|sup|sub|ul|ol|li|h[1-6])\b[^>]*>",
    re.I)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _is_heading_title(title: str, *, strict: bool = False) -> bool:
    """짧은 제목(공백 제거 12자 이하)이거나, 어휘 목록에 맞으면서 25자 이하다(설계 D9 조건 b).

    strict: 어휘 일치가 **필수**다. 제외 중인 절(관계법령)에서 빠져나오는 소제목에 쓴다 — 조문 목록 항목
    "2. 업무상 질병"은 짧지만 어휘가 없어 제외 구간을 끊지 못한다(끊으면 구 조문이 새어 나간다).
    """
    compact = _compact(title)
    if len(compact) > 28:     # 실측 최장 상위 소제목 "관계법령, 사실관계, 의학적 견해, 근로복지공단의 결정 및 판단"(26자)
        return False
    if _HEADING_VOCAB_RE.search(title):
        return True
    return len(compact) <= 12 and not strict


def _top_number_ok(n: int, last_top: int, title: str) -> bool:
    if n == last_top + 1:
        return True
    return last_top > 0 and n in (last_top, last_top + 2) and _is_heading_title(title, strict=True)


def _is_excluded_title(title: str) -> bool:
    # 끝의 콜론·마침표("2. 관계법령:")를 떼고 본다(CodeRabbit #155) — 떼지 않으면 그 절의 당시 조문이 실린다
    return bool(_EXCLUDE_TITLE_RE.match(_compact(title).rstrip(":：.·")))


@dataclass
class Section:
    top: str                 # 상위 소제목(없으면 "서두"/"본문")
    sub: str | None
    lines: list[str] = field(default_factory=list)
    excluded: bool = False

    @property
    def label(self) -> str:
        return f"이유 — {self.top}" + (f" / {self.sub}" if self.sub else "")

    @property
    def text(self) -> str:
        return clean_text("\n".join(self.lines))


def split_reasoning(text: str) -> list[Section]:
    """`이유`를 상위·소절 소제목 단위로 나눈다. 번호가 되돌아가는 조문 목록은 소제목이 아니다."""
    sections: list[Section] = []
    cur = Section("서두", None)
    last_top = 0
    next_sub = 0                      # _SUB_ORDER 인덱스
    top_excluded = False
    for line in (text or "").splitlines():
        m = _TOP_RE.match(line)
        # 번호는 직전 +1이 원칙이다. 위원회 원문에 번호 중복("6. 의학적 소견" 뒤 "6. 판단")·건너뜀("5. 인정사실" 뒤
        # "7. 결론")이 실측 20건 있어, 같은 번호·+2는 **어휘가 맞을 때만** 소제목으로 본다(조문 목록 항목은 어휘가 없다).
        if m and _top_number_ok(int(m.group(1)), last_top, m.group(2)) \
                and _is_heading_title(m.group(2), strict=cur.excluded):
            sections.append(cur)
            last_top = int(m.group(1))
            next_sub = 0
            top_excluded = _is_excluded_title(m.group(2))
            cur = Section(m.group(2).strip(), None, excluded=top_excluded)
            continue
        m = _SUB_RE.match(line)
        if (m and last_top > 0 and next_sub < len(_SUB_ORDER) and m.group(1) == _SUB_ORDER[next_sub]
                and _is_heading_title(m.group(2), strict=cur.excluded)):
            sections.append(cur)
            next_sub += 1
            cur = Section(cur.top, m.group(2).strip(),
                          excluded=top_excluded or _is_excluded_title(m.group(2)))
            continue
        cur.lines.append(line)
    sections.append(cur)
    out = [s for s in sections if s.text]
    if last_top == 0:                 # 소제목이 하나도 없다 — 통째로
        for s in out:
            s.top, s.sub = "본문", None
    return out


# ── md 파싱 ───────────────────────────────────────────────────────────────────

def parse_doc(path: str) -> dict | None:
    with open(path, encoding="utf-8") as f:
        md = unicodedata.normalize("NFC", f.read())
    meta = parse_meta(md)
    agency, serial, case_no = meta.get("agency", ""), meta.get("일련번호", ""), meta.get("사건번호", "")
    if agency not in AGENCIES or not serial.isdigit() or not case_no:
        return None
    sections = parse_sections(md)
    title_m = re.match(r"^#\s+(.+)", md.strip())
    case_name = title_m.group(1).strip() if title_m else case_no
    agency_name = meta.get("기관", "")
    decided_at = meta.get("의결일자", "")
    year_m = re.match(r"^(\d{4})(?:\.\d{2}\.\d{2}|\(일자 미상\))$", decided_at)
    summary_label = "개요" if "개요" in sections else ("쟁점" if "쟁점" in sections else "")
    return {
        "agency": agency, "serial": serial, "case_no": case_no, "case_name": case_name,
        "agency_name": agency_name,
        "title": f"{agency_name} {case_no} — {case_name}"[:200],
        "decided_at": decided_at,
        "decided_year": int(year_m.group(1)) if year_m else None,
        "category": meta.get("분류", ""), "doc_kind": meta.get("문서종류", ""),
        "respondent": meta.get("피청구인", ""), "claimant": meta.get("청구인", ""),
        "url": meta.get("원문", ""),
        "summary_label": summary_label,
        "summary": sections.get(summary_label, "") if summary_label else "",
        "disposition": sections.get("주문", ""),
        "claim": sections.get("청구취지", ""),
        "reasoning": sections.get("이유", ""),
        "footnotes": sections.get("각주", ""),
        "path": path,
    }


def build_header(doc: dict) -> str:
    category = doc.get("category", "")[:80]
    head = f"[{doc['agency_name']} {doc['case_no']} · 의결 {doc['decided_at']}"
    head += f" · {category}]" if category else "]"
    return head[:HEADER_MAX]


# ── 청킹(§4.2) ───────────────────────────────────────────────────────────────

def load_redactions() -> dict[tuple[str, str], list[str]]:
    """`_pii_redactions.json` [{agency, serial, field, literal}] → {(agency, serial): [literal, …]}."""
    if not os.path.exists(PII_REDACTIONS_FILE) or os.path.getsize(PII_REDACTIONS_FILE) == 0:
        return {}
    with open(PII_REDACTIONS_FILE, encoding="utf-8") as f:
        entries = json.load(f)
    out: dict[tuple[str, str], list[str]] = {}
    for e in entries:
        out.setdefault((e["agency"], str(e["serial"])), []).append(e["literal"])
    return out


def pii_unreviewed() -> int:
    if not os.path.exists(PII_REPORT_FILE) or os.path.getsize(PII_REPORT_FILE) == 0:
        return 0
    with open(PII_REPORT_FILE, encoding="utf-8") as f:
        return sum(1 for e in json.load(f) if not e.get("reviewed"))


def _redact(text: str, literals: list[str]) -> str:
    for lit in literals:
        if lit:
            text = text.replace(lit, "***")
    return text


def redact_doc(doc: dict, literals: list[str] | None) -> dict:
    """문서의 모든 문자열 필드에 가림 목록을 적용한 사본 — 머리글·메타데이터(title·disposition·category…)도
    청크 본문과 같은 가림을 받아야 한다. 본문만 가리면 승인된 가림이 메타데이터로 그대로 올라간다(Codex 리뷰 #155)."""
    if not literals:
        return doc
    return {k: (_redact(v, literals) if isinstance(v, str) and k != "path" else v) for k, v in doc.items()}


def chunk_doc(doc: dict, redactions: list[str] | None = None) -> tuple[list[dict], dict]:
    """(청크 목록, 집계). 청구인·청구취지는 넣지 않는다."""
    doc = redact_doc(doc, redactions)      # 머리글·개요·주문·이유·각주 전부 가린 사본으로 청킹한다
    header = build_header(doc)
    chunks: list[dict] = []
    idx = 0

    def _emit(body: str, section: str) -> None:
        nonlocal idx
        for piece in split_by_size(body, CHUNK_MAX, CHUNK_OVERLAP):
            text = f"{header}\n{piece}"
            chunks.append({
                "vector_id": make_vector_id(doc["agency"], doc["serial"], idx),
                "chunk_index": idx, "section": section[:80], "text": text,
            })
            idx += 1

    lead = []
    if doc.get("summary"):
        lead.append(f"{doc['summary_label']}: {doc['summary']}")
    if doc.get("disposition"):
        lead.append(f"주문: {doc['disposition']}")
    if lead:
        _emit("\n".join(lead), f"{doc['summary_label'] or '개요'}·주문")

    sections = split_reasoning(doc.get("reasoning", ""))
    excluded_chars = sum(len(s.text) for s in sections if s.excluded)
    excluded_titles = [s.label for s in sections if s.excluded]
    tops = []
    for s in sections:
        if s.top not in tops:
            tops.append(s.top)
    # 작은 절은 순서대로 묶는다(CHUNK_MAX 안에서) — 1,051건 실측에서 청크 28%가 300자 미만이었다("원처분기관
    # 처분내용" 54자·"결 론" 56자 같은 절이 머리글만 단 청크가 됐다). 묶인 청크의 section은 절 이름을 ' · '로 잇는다.
    for body, label in pack_sections([s for s in sections if not s.excluded]):
        _emit(body, label)
    if doc.get("footnotes"):
        _emit(doc["footnotes"], "각주")

    body_text = _IMAGE_PLACEHOLDER_RE.sub("", doc.get("reasoning", "")).strip()
    image_only = len(body_text) < IMAGE_ONLY_LIMIT
    stats = {
        "chunks": len(chunks), "excluded_chars": excluded_chars, "excluded_titles": excluded_titles,
        "tops": tops,
        "image_only": image_only,   # 이유가 스캔 이미지뿐(2016~2018 iaciac 실측 152건) — 쟁점·주문만 적재된다
        "fallback": (not image_only) and not any(_FALLBACK_SIGNAL_RE.search(s.label) for s in sections),
        "residual_tags": sum(1 for c in chunks if RESIDUAL_TAG_RE.search(c["text"])),
    }
    return chunks, stats


def pack_sections(sections: list[Section]) -> list[tuple[str, str]]:
    """연속한 절을 CHUNK_MAX 안에서 묶는다 → [(본문, section 라벨)]. 큰 절은 그대로(뒤에서 split_by_size)."""
    packs: list[tuple[list[str], list[str]]] = []
    for s in sections:
        text = s.text
        if not text:
            continue
        if packs and sum(len(t) for t in packs[-1][0]) + len(text) + 1 <= CHUNK_MAX:
            packs[-1][0].append(text)
            packs[-1][1].append(s.label)
        else:
            packs.append(([text], [s.label]))
    out = []
    for texts, labels in packs:
        names = [lb.replace("이유 — ", "", 1) for lb in labels]
        out.append(("\n".join(texts), "이유 — " + " · ".join(dict.fromkeys(names))))
    return out


# ── 소스 파일 ─────────────────────────────────────────────────────────────────

def source_files(agency_filter: str | None = None) -> list[str]:
    """`output_재결례/{eiac,iaciac}/*.md` 비재귀(`_excluded/`는 보지 않는다)."""
    out = []
    for agency in AGENCIES:
        if agency_filter and agency != agency_filter:
            continue
        d = os.path.join(SOURCE_DIR, agency)
        if not os.path.isdir(d):
            continue
        out += sorted(os.path.join(d, f) for f in os.listdir(d)
                      if f.endswith(".md") and not f.startswith("_"))
    return out


def exclude_before(year: int, agency: str, *, dry_run: bool = False) -> list[str]:
    """`decided_year < year`인 md를 `_excluded/{agency}/`로 이동한다(dry_run이면 목록만). 날짜 미상은 제외하지 않는다."""
    moved = []
    for path in source_files(agency):
        doc = parse_doc(path)
        if doc and doc["decided_year"] is not None and doc["decided_year"] < year:
            if not dry_run:
                dst_dir = os.path.join(EXCLUDED_DIR, agency)
                os.makedirs(dst_dir, exist_ok=True)
                shutil.move(path, os.path.join(dst_dir, os.path.basename(path)))
            moved.append(os.path.basename(path))
    return moved


def pii_problems(doc: dict, reviewed: set[tuple[str, str, str, str]]) -> list[dict]:
    """문서 자체를 다시 스캔해 보고서에서 검토(reviewed)되지 않은 적중을 돌려준다(CodeRabbit #155).

    `_pii_report.json`의 reviewed 수만 보면 보고서가 없거나(다른 기계에서 수집) 지워진 경우 미검토 개인정보가 그대로
    올라간다. 가림 목록이 적용된 사본을 스캔하므로 "검토 뒤 가림"은 적중이 사라져 통과하고, "검토했지만 가리지 않음"
    (오탐)은 보고서의 reviewed 항목으로 통과한다.
    """
    from fetch_rulings import scan_pii
    return [h for h in scan_pii(doc)
            if (doc["agency"], str(doc["serial"]), h["field"], h["pattern"]) not in reviewed]


def reviewed_pii_index() -> set[tuple[str, str, str, str]]:
    if not os.path.exists(PII_REPORT_FILE) or os.path.getsize(PII_REPORT_FILE) == 0:
        return set()
    with open(PII_REPORT_FILE, encoding="utf-8") as f:
        return {(e["agency"], str(e["serial"]), e["field"], e["pattern"]) for e in json.load(f) if e.get("reviewed")}


def groups_without_source() -> list[str]:
    """원장에 있는데 소스 md가 없는 그룹."""
    present = set()
    for path in source_files():
        doc = parse_doc(path)
        if doc:
            present.add(f"{doc['agency']}_{doc['serial']}")
    return sorted(g for g in _LEDGER.read() if g not in present)


# ── 배치 원장(D14) ────────────────────────────────────────────────────────────

def write_batch_ledger(path: str, *, verify: bool = False, index=None) -> dict:
    """커밋용 원장 — `source_pack_ledger.py` 형식. 빈 그룹·md 없는 그룹이 있으면 중단한다."""
    from app.config import resolve_index_name

    ledger_groups = _LEDGER.read()
    redactions = load_redactions()
    docs_by_group: dict[str, dict] = {}
    for p in source_files():
        d = parse_doc(p)
        if d:
            docs_by_group[f"{d['agency']}_{d['serial']}"] = redact_doc(d, redactions.get((d["agency"], d["serial"])))
    documents: dict[str, dict] = {}
    for group, ids in sorted(ledger_groups.items()):
        if not ids:
            raise RuntimeError(f"빈 그룹 {group} — --prune-missing으로 정리한 뒤 다시 생성하세요.")
        d = docs_by_group.get(group)
        if d is None:
            raise RuntimeError(f"소스 md 없는 그룹 {group} — --prune-missing으로 정리한 뒤 다시 생성하세요.")
        with open(d["path"], "rb") as f:
            sha = hashlib.sha256(f.read()).hexdigest()
        documents[group] = {"title": d["title"], "source_type": SOURCE_TYPE,
                            "official_url": d["url"], "source_sha256": sha, "ids": sorted(ids)}
    total = sum(len(v["ids"]) for v in documents.values())
    ledger = {
        "batch": os.path.splitext(os.path.basename(path))[0],
        "id_prefix": f"{SOURCE_TYPE}_",
        "id_pattern": rf"^{SOURCE_TYPE}_(eiac|iaciac)_\d+_chunk_\d+$",
        "index": resolve_index_name(),
        "namespace": NAMESPACE,
        "uploaded_on": _dt.date.today().isoformat(),
        "state": "uploaded",
        "vector_count": total,
        "document_count": len(documents),
        "composition": {SOURCE_TYPE: total},
        "documents": documents,
    }
    if verify:
        import source_pack_ledger as spl
        idx = index or spl.open_index(ledger)
        missing = spl.verify(ledger, idx)
        ledger["state"] = "verified" if missing == 0 else "uploaded"
    atomic_write_json(path, ledger)
    return ledger


# ── main ─────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="재결례 Pinecone 업로드")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--agency", choices=AGENCIES)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--allow-large-prune", action="store_true")
    parser.add_argument("--exclude-before", type=int, metavar="YEAR")
    parser.add_argument("--prune-missing", action="store_true")
    parser.add_argument("--write-batch-ledger", metavar="PATH")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)

    if args.exclude_before:
        if not args.agency:
            print("[오류] --exclude-before에는 --agency가 필요합니다.")
            return 1
        moved = exclude_before(args.exclude_before, args.agency, dry_run=args.dry_run)
        print(f"{'[dry-run] ' if args.dry_run else ''}{args.agency} {args.exclude_before}년 이전 {len(moved)}건"
              f"{' → ' + EXCLUDED_DIR if not args.dry_run else ' (이동 없음)'}")
        for m in moved[:10]:
            print("  ", m)
        return 0

    if args.prune_missing:
        if args.limit or args.agency:
            # 소스 없는 그룹은 두 기관 전부에서 계산한다 — --agency를 받으면 다른 기관까지 지우는데 그렇게 보이지 않는다
            print("[오류] --prune-missing은 단독으로 실행합니다(--agency·--limit 불가).")
            return 1
        groups = groups_without_source()
        if not groups:
            print("소스 없는 그룹 없음.")
            return 0
        index = None if args.dry_run else _open_index()
        ids = _LEDGER.drop_groups(groups, index, NAMESPACE, allow_large=args.allow_large_prune,
                                  dry_run=args.dry_run, label="재결례")
        print(f"{'[dry-run] ' if args.dry_run else ''}소스 없는 그룹 {len(groups)}개 · 벡터 {len(ids)}건"
              f" (예: {groups[:3]})")
        return 0

    if args.write_batch_ledger:
        ledger = write_batch_ledger(args.write_batch_ledger, verify=args.verify)
        print(f"배치 원장 {args.write_batch_ledger}: 문서 {ledger['document_count']} · 벡터 "
              f"{ledger['vector_count']} · state={ledger['state']}")
        return 0

    files = source_files(args.agency)
    if args.limit:
        files = files[:args.limit]
    if not files:
        print(f"[오류] 소스 md가 없습니다: {SOURCE_DIR}")
        return 1

    redactions = load_redactions()
    reviewed = reviewed_pii_index()
    print(f"\n{'=' * 62}\n재결례 업로드 {'(DRY RUN)' if args.dry_run else ''}\n"
          f"소스: {len(files)}개 파일  |  네임스페이스: {NAMESPACE}  |  source_type: {SOURCE_TYPE}\n{'=' * 62}\n")

    ready: list[tuple[dict, list[dict]]] = []
    agg = {"chunks": 0, "excluded_chars": 0, "fallback_docs": [], "residual_docs": [], "image_only": 0,
           "date_fail": 0, "skipped": [], "excluded_titles": {}, "pii_docs": [], "pii_hits": 0}
    seen_ids: set[str] = set()
    empty_groups: list[str] = []
    for path in files:
        doc = parse_doc(path)
        if not doc:
            agg["skipped"].append(os.path.basename(path))
            continue
        # 메타데이터(title·disposition·category…)도 가림을 받는다 — chunk_doc 안의 가림과 같은 목록
        doc = redact_doc(doc, redactions.get((doc["agency"], doc["serial"])))
        problems = pii_problems(doc, reviewed)
        if problems:
            agg["pii_docs"].append(os.path.basename(path))
            agg["pii_hits"] += len(problems)
        chunks, st = chunk_doc(doc)
        if not chunks:
            # 청크가 0인 문서(재수집으로 관계법령만 남은 경우)도 이전 벡터는 지워야 한다(CodeRabbit #155)
            agg["skipped"].append(f"{os.path.basename(path)} (청크 0)")
            empty_groups.append(f"{doc['agency']}_{doc['serial']}")
            continue
        dup = [c["vector_id"] for c in chunks if c["vector_id"] in seen_ids]
        if dup:
            agg["skipped"].append(f"{os.path.basename(path)} (ID 충돌 {dup[0]})")
            continue
        seen_ids.update(c["vector_id"] for c in chunks)
        agg["chunks"] += st["chunks"]
        agg["excluded_chars"] += st["excluded_chars"]
        for t in st["excluded_titles"]:
            agg["excluded_titles"][t] = agg["excluded_titles"].get(t, 0) + 1
        if st["fallback"]:
            agg["fallback_docs"].append(os.path.basename(path))
        if st["image_only"]:
            agg["image_only"] += 1
        if st["residual_tags"]:
            agg["residual_docs"].append(os.path.basename(path))
        if doc["decided_year"] is None:
            agg["date_fail"] += 1
        ready.append((doc, chunks))

    n_docs = len(ready)
    unreviewed = pii_unreviewed() + agg["pii_hits"]
    print(f"문서 {n_docs} · 청크 {agg['chunks']} · 평균 {agg['chunks'] / max(n_docs, 1):.1f}청크/문서")
    print(f"관계법령 제외 {agg['excluded_chars']:,}자 · 제외 제목 상위: "
          f"{sorted(agg['excluded_titles'].items(), key=lambda x: -x[1])[:5]}")
    print(f"소제목 폴백(결론·판단 없음) {len(agg['fallback_docs'])}건 · 이유 이미지만 {agg['image_only']}건 · "
          f"잔존 태그 {len(agg['residual_docs'])}건 · 날짜 미상 {agg['date_fail']}건 · 스킵 {len(agg['skipped'])}건 · "
          f"PII 미확인 {unreviewed}건")
    if agg["skipped"]:
        print("  스킵:", agg["skipped"][:5])
    if agg["fallback_docs"]:
        print("  폴백:", agg["fallback_docs"][:5])
    if agg["residual_docs"]:
        print("  잔존 태그:", agg["residual_docs"][:5])

    # 중단 조건(설계 §4.4) — dry-run도 같은 조건을 출력하되 결과는 실제 실행이 결정한다.
    stop = []
    if unreviewed:
        stop.append(f"PII 미검토 {unreviewed}건(보고 미확인 {pii_unreviewed()} + 문서 재스캔 적중 {agg['pii_hits']}: "
                    f"{agg['pii_docs'][:3]}) — _pii_report.json에 reviewed를 표시하거나 _pii_redactions.json으로 가리세요")
    if agg["residual_docs"]:
        stop.append(f"잔존 HTML 태그 {len(agg['residual_docs'])}건")
    if n_docs and len(agg["fallback_docs"]) > n_docs * FALLBACK_LIMIT:
        stop.append(f"소제목 폴백 {len(agg['fallback_docs'])}건이 {FALLBACK_LIMIT:.0%}를 넘음 — 소제목 규칙 점검")
    if stop:
        print("\n⛔ 중단 조건:")
        for s in stop:
            print("  -", s)
        return 3
    if args.dry_run:
        return 0

    openai_client, index = _open_clients()
    groups = {f"{doc['agency']}_{doc['serial']}": [c["vector_id"] for c in chunks] for doc, chunks in ready}
    previous = _LEDGER.record(groups)
    print(f"벡터 ID {agg['chunks']}건 기록: {UPLOADED_IDS_FILE}\n")

    pending: list[dict] = []
    for n, (doc, chunks) in enumerate(ready, 1):
        embeddings = embed_texts([c["text"] for c in chunks], openai_client)
        time.sleep(0.2)
        if len(embeddings) != len(chunks):
            sys.exit(f"[오류] 임베딩 수 불일치 {len(embeddings)} != {len(chunks)} ({doc['path']}) — 재실행으로 재개")
        for c, emb in zip(chunks, embeddings):
            meta = {
                "source_type": SOURCE_TYPE,
                "title": doc["title"][:200],
                "case_name": doc["case_name"][:120],
                "section": c["section"],
                "case_no": doc["case_no"],
                "agency": doc["agency"],
                "serial": str(doc["serial"]),
                "date": doc["decided_at"][:20],
                "category": doc["category"][:120],
                "disposition": doc["disposition"][:120],
                "url": doc["url"][:200],
                "chunk_index": int(c["chunk_index"]),
                "chunk_text": c["text"][:TEXT_CAP],
                "text": c["text"][:TEXT_CAP],
            }
            if doc["decided_year"] is not None:
                meta["decided_year"] = int(doc["decided_year"])
            pending.append({"id": c["vector_id"], "values": emb, "metadata": meta})
        while len(pending) >= UPSERT_BATCH:
            index.upsert(vectors=pending[:UPSERT_BATCH], namespace=NAMESPACE)
            pending = pending[UPSERT_BATCH:]
            time.sleep(0.1)
        if n % 50 == 0 or n == len(ready):
            print(f"  {n}/{len(ready)} 문서 업로드")
    if pending:
        index.upsert(vectors=pending, namespace=NAMESPACE)

    _LEDGER.prune(groups, previous, index, NAMESPACE, batch_size=UPSERT_BATCH,
                  allow_large=args.allow_large_prune, label="재결례")
    stale_empty = [g for g in empty_groups if g in _LEDGER.read()]
    if stale_empty:
        _LEDGER.drop_groups(stale_empty, index, NAMESPACE, batch_size=UPSERT_BATCH, label="재결례(청크 0)")
    try:
        count = index.describe_index_stats().namespaces[NAMESPACE].vector_count
        print(f"\n업로드 후 {NAMESPACE} 벡터 수: {count:,}")
    except Exception as e:  # noqa: BLE001 — 스냅샷 실패는 업로드 실패가 아니다
        print(f"\n벡터 수 조회 실패: {type(e).__name__}")
    return 0


def _open_index():
    from pinecone import Pinecone
    from app.config import resolve_index_name
    key = os.getenv("PINECONE_API_KEY")
    if not key:
        sys.exit("[오류] PINECONE_API_KEY가 설정되지 않았습니다.")
    return Pinecone(api_key=key).Index(resolve_index_name())


def _open_clients():
    from openai import OpenAI
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        sys.exit("[오류] OPENAI_API_KEY가 설정되지 않았습니다.")
    return OpenAI(api_key=openai_key), _open_index()


if __name__ == "__main__":
    sys.exit(main())
