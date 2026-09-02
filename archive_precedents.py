#!/usr/bin/env python3
"""판례 아카이브 — 문서 번들(jsonl.gz) + 인벤토리 장부(CSV) 생성·검증·복원.

시스템에 입력된 모든 판례(법제처 수집·nodong.kr 크롤·코드 인용·교재 인용)를
사건번호 기본 키의 단일 장부로 통합하고, 비보호 저작물 계층을 저장소에
커밋 가능한 번들로 만든다. 설계: docs/02-design/features/precedent-archive.design.md

서브커맨드:
  build              로컬 원본 → 번들+장부+스냅샷 (오프라인)
  build --pinecone   + ctx·사장 NS 벡터 열거 스냅샷 (유일한 네트워크 경로, 조회 전용)
  gate               크롤 자동 3-버킷 분류 요약 + 육안 표본 목록
  gate --approve --as-of YYYY-MM-DD   육안 완료 후 verbatim 승격 확정
  extract <사건번호>  번들 → md 복원 (--out 지정 시 파일, 기본 stdout)
  verify             정합 검사 V0~V8 (로컬 원본 유무로 범위 자동 축소)

Pinecone에 쓰는 경로는 없다 — --pinecone도 조회 전용이고 원장은 읽기 전용이다.

저작권 경계(설계 §4.3): 커밋 번들에 들어가는 문서는 ① letec 전량(법제처 원문,
저작권법 제7조 비보호) ② crawl 중 육안 게이트를 통과한 verbatim(판결문 원문)뿐.
크롤 게시물의 편집·해설은 공개 커밋 금지 — verify V7이 강제한다.
"""

from __future__ import annotations

import os
import re
import io
import csv
import sys
import ast
import gzip
import json
import hashlib
import argparse
import tokenize
import unicodedata
import dataclasses
from collections import defaultdict

# 단일 출처 import — 사본 금지(설계 D-4·D-10, CLAUDE.md M1 드리프트 교훈).
# case_no_to_ascii는 원장(_uploaded_ids.json)을 만든 바로 그 함수다.
from pinecone_upload_court_precedents import (
    EMBED_SECTIONS, UnknownCaseCode, case_no_to_ascii, _CASE_CODE_MAP)
from fetch_court_precedents import (
    extract_representative_case_no_with_src, normalize_case_no, OCR_FIXES)
from extract_textbook_cases import CASE_RE

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

NFC = lambda s: unicodedata.normalize("NFC", s)


@dataclasses.dataclass
class Paths:
    """입력·출력 경로. letec_dir와 crawl_dir는 **같은 부모**를 가져야 한다 —
    doc_id가 그 부모 기준 상대 경로이기 때문(프로덕션은 BASE_DIR, 테스트는 tmp)."""
    letec_dir: str = os.path.join(BASE_DIR, "output_판례_보강")
    crawl_dir: str = os.path.join(BASE_DIR, "output_법원 노동판례")
    out_dir: str = os.path.join(BASE_DIR, "data", "precedent_archive")
    textbook_csv: str = os.path.join(BASE_DIR, "output_노동법교재", "누락_판례목록.csv")
    code_scan_base: str = BASE_DIR

    @property
    def records_dir(self) -> str:
        return os.path.join(self.out_dir, "records")

    @property
    def doc_root(self) -> str:
        return os.path.dirname(self.letec_dir)

    def doc_path(self, doc_id: str) -> str:
        p = os.path.join(self.doc_root, doc_id)
        if os.path.exists(p):
            return p
        # doc_id는 NFC 규약이지만 실경로의 정규화 형식은 제각각일 수 있다 —
        # macOS 유래 파일명은 NFD, 디렉토리명은 생성 경로에 따라 NFC(소스
        # 리터럴)일 수도 있다. APFS는 정규화-비민감이라 로컬에선 어느 조합도
        # 열리지만 Linux(ext4)는 바이트 보존이라 ENOENT — verify V3가 오탐한다
        # (CI 실측 2026-09-01: 전체 NFD 변환 폴백도 NFC 디렉토리에 막혔다).
        # 컴포넌트별로 NFC-동등 항목을 찾아 실경로를 재조립한다.
        cur = self.doc_root
        for part in doc_id.split("/"):
            nxt = os.path.join(cur, part)
            if not os.path.exists(nxt):
                try:
                    match = next((e for e in os.listdir(cur)
                                  if NFC(e) == NFC(part)), None)
                except OSError:
                    return p
                if match is None:
                    return p
                nxt = os.path.join(cur, match)
            cur = nxt
        return cur

    def snapshot_origins(self) -> dict[str, str]:
        """records/ 스냅샷(ASCII 파일명, 설계 D-8) → 로컬 원본 경로.
        복사·digest·MANIFEST 광고가 전부 이 하나에서 파생된다 — 평행 dict를
        손동기화하면 광고와 실복사가 조용히 갈라진다(simplify 리뷰 2)."""
        return {
            "records/ledger_uploaded_ids.json": os.path.join(self.letec_dir, "_uploaded_ids.json"),
            "records/not_found.csv": os.path.join(self.letec_dir, "_미발견.csv"),
            "records/overlap_targets.csv": os.path.join(self.letec_dir, "_겹침대상.csv"),
            "records/ctx_deleted.json": os.path.join(self.letec_dir, "_ctx_deleted.json"),
            "records/textbook_citations.csv": self.textbook_csv,
        }


# 공개 커밋 번들의 레코드 스키마(설계 §3) — 화이트리스트. read_doc·apply_gate가
# 작업 필드(case_src·gate·bundled·_gate_stats 등)를 늘려도 번들에 새지 않는다.
BUNDLE_FIELDS = ("doc_id", "source", "case_no", "case_key", "doctype",
                 "court", "decided", "title", "category", "category_src",
                 "post_id", "origin_url", "issues", "sha256", "body_md")

INVENTORY_COLS = ["case_no", "case_alias", "case_key", "court", "decided", "title",
                  "doc_letec", "doc_crawl", "vec_chunks", "vec_ctx", "vec_dead",
                  "cited_code", "cited_textbook", "not_found", "overlap", "note"]

# 예시의심 자동 초안의 사람 확정 결과(Do #3, 2026-09-01 코드 원문 판정).
# 자동 규칙(docstring/comment뿐)은 comment 실인용을 구분하지 못한다 — 실측:
# insurance.py:58 "실질 근로자 판단 체크리스트 (대법원 2006다49653 등)"는
# comment지만 계산기 로직의 법적 근거 인용이다. 판정을 상수로 고정해 재실행에도
# 유지한다(멱등). 새 인용이 자동 초안에 잡히면 여기서 재판정할 것.
EXAMPLE_CONFIRMED = {"2021헌마1234", "2017헌바127", "2006다49372"}  # note=예시확정
EXAMPLE_OVERRIDE_REAL = {"2006다49653"}                            # 실인용 — note 없음
DOCUMENTS_COLS = ["doc_id", "source", "case_no", "case_src", "doctype", "category",
                  "category_src", "post_id", "title", "gate", "bundled"]

GATE_RULE_VERSION = 3  # v2: 종결 문구를 말미 앵커에 추가
                       # v3: 육안 게이트 1차에서 발견된 혼입 패턴 반영(§7.2 보수화 절차) —
                       #     ※ 편집자 안내문(홈페이지 참조·이하 생략)과 크롤 JS 잔재

# ── 사건번호 정준형 ───────────────────────────────────────────────────────────

def canonicalize(raw: str) -> tuple[str, str | None] | None:
    """사건번호 → (정준형, 병합된 원표기|None). 화이트리스트 밖이면 None.

    CASE_RE(사건부호 화이트리스트, T20)가 재조립과 검증을 겸한다 — 인권위
    '09진차219' 같은 비법원 번호는 여기서 기각된다(설계 §6 ①).
    1946~1999년 4자리 연도 표기는 2자리 정식 표기로 병합한다(설계 §5.1 —
    실측: _미발견.csv에 '1992다28556'류 존재, 정식은 '92다28556').
    """
    s = normalize_case_no(raw)
    m = CASE_RE.fullmatch(s)
    if not m:
        return None
    year, code, num = m.groups()
    # 연도 유효성 — 3자리는 사건번호가 될 수 없다(실측 오탐: 사업장 규모 표기
    # "50~299인 2020"이 '299인2020'으로, 불량 표기 '005두4403'이 그대로 통과).
    if len(year) == 3 or (len(year) == 4 and not 1946 <= int(year) <= 2030):
        return None
    canonical = f"{year}{code}{num}"
    if len(year) == 4 and int(year) <= 1999:
        canonical = f"{year[2:]}{code}{num}"
    return canonical, (s if s != canonical else None)


def case_key_of(case_no: str | None) -> str | None:
    """원장 키 규약의 ASCII 변환. hex 폴백은 없다(설계 D-10 — 원장 키
    공간에 hex 0건 실측, 대조 상대가 없는 규약은 죽은 코드다)."""
    if not case_no:
        return None
    try:
        return case_no_to_ascii(case_no)
    except UnknownCaseCode:
        return None


_REV_CODE_MAP: dict[str, str] = {}
for _k, _v in _CASE_CODE_MAP.items():
    # 값 충돌 시 역매핑이 모호해진다 — 로드 시점에 고정 검증.
    assert _v not in _REV_CODE_MAP, f"case code 역매핑 충돌: {_v}"
    _REV_CODE_MAP[_v] = _k

_KEY_RE = re.compile(r"^(\d+)([a-z]+)(\d+)$")


def reverse_case_key(key: str) -> str | None:
    """원장 ascii 키 → NFC 사건번호. 왕복 검증 실패 시 None."""
    m = _KEY_RE.match(key)
    if not m:
        return None
    year, code, num = m.groups()
    ko = _REV_CODE_MAP.get(code)
    if ko is None:
        return None
    case_no = f"{year}{ko}{num}"
    return case_no if case_key_of(case_no) == key else None


# ── md 파싱 ──────────────────────────────────────────────────────────────────

_META_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*(.*?)\s*\|\s*$", re.MULTILINE)
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")


def parse_meta_table(text: str) -> dict[str, str]:
    """선두 메타 테이블(| 항목 | 내용 |)을 dict로. 섹션명은 열거하지 않는다(설계 §2.1)."""
    head = text.split("\n---\n", 1)[0]
    meta: dict[str, str] = {}
    for k, v in _META_ROW_RE.findall(head):
        if k in ("항목", "---") or set(k) <= {"-", " "}:
            continue
        meta[NFC(k)] = NFC(v)
    return meta


def parse_title(text: str) -> str | None:
    m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    return NFC(m.group(1).strip()) if m else None


def parse_issues(text: str) -> list[str]:
    m = re.search(r"^## 관련 쟁점\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    if not m:
        return []
    return [NFC(ln[2:].strip()) for ln in m.group(1).splitlines()
            if ln.startswith("- ") and ln[2:].strip()]


def origin_url_of(meta: dict[str, str]) -> str | None:
    raw = meta.get("원문")
    if not raw:
        return None
    m = _MD_LINK_RE.search(raw)
    return (m.group(2) if m else raw).strip() or None


# ── 문서 수집 ─────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class Collected:
    docs: list[dict] = dataclasses.field(default_factory=list)
    errors: list[str] = dataclasses.field(default_factory=list)      # 형식 위반 — 조용한 폐기 금지
    rejects: list[str] = dataclasses.field(default_factory=list)     # 화이트리스트 기각(설계 §6 ①)
    mismatches: list[str] = dataclasses.field(default_factory=list)  # 파일명 vs 메타 불일치(§6 ③)


# 크롤 파일명 선두 토큰 — post_id(구세대) 또는 사건번호(신세대). index_missing의
# 차집합 대조와 색인 누락 note 부착이 같은 정의를 써야 "탐지됐는데 note가 안
# 붙는" 어긋남이 없다(simplify 리뷰 F9).
_HEAD_TOKEN_RE = re.compile(r"^(\d{2,4}[가-힣]{1,4}\d+|\d+)_")


def head_token(name: str) -> str:
    m = _HEAD_TOKEN_RE.match(NFC(name))
    return m.group(1) if m else NFC(name)


def _representative(text: str, filename: str, meta: dict[str, str],
                    overlap_by_postid: dict[str, str], post_id: str | None,
                    col: Collected, rel: str) -> tuple[str | None, str | None, str | None]:
    """대표 사건번호 판정 3단(설계 §6). 반환 (정준형, 병합원표기, case_src)."""
    # 판정·채택 경로 모두 fetch의 함수 — 후속 수집 L2와 같은 답(설계 D-4),
    # src를 값 대조로 역추적하면 fetch 우선순위 변경 시 조용히 오표기된다(F5)
    raw, src = extract_representative_case_no_with_src(text, filename)
    if raw:
        canon = canonicalize(raw)
        if canon is None:
            col.rejects.append(f"{rel}: 비법원 번호 기각 {raw!r}")
        else:
            # 불일치 보고 — 채택은 함수의 메타 우선을 따르되 조용한 선택 금지
            fn_m = CASE_RE.search(NFC(filename))
            meta_no = meta.get("사건번호", "")
            if fn_m and meta_no:
                fn_no = normalize_case_no("".join(fn_m.groups()))
                if normalize_case_no(meta_no) != fn_no:
                    col.mismatches.append(f"{rel}: 파일명 {fn_no!r} vs 메타 {meta_no!r}")
            return canon[0], canon[1], src
    # 겹침 대응 채택(§6 ②) — 편집자 큐레이션 산출물, 참조판례 함정 무관
    if post_id and post_id in overlap_by_postid:
        canon = canonicalize(overlap_by_postid[post_id])
        if canon:
            return canon[0], canon[1], "overlap"
    return None, None, None


def read_doc(path: str, rel: str, source: str, category: str | None,
             category_src: str | None, overlap_by_postid: dict[str, str],
             col: Collected) -> dict | None:
    try:
        with open(path, "rb") as f:
            raw_bytes = f.read()
        body = raw_bytes.decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        col.errors.append(f"{rel}: 읽기 실패 {e}")
        return None

    filename = os.path.basename(path)
    meta = parse_meta_table(body)
    post_id = None
    if source == "crawl":
        m = re.match(r"^(\d+)_", NFC(filename))
        if m:
            post_id = m.group(1)

    case_no, alias, case_src = _representative(
        body, filename, meta, overlap_by_postid, post_id, col, rel)
    if source == "letec":
        if case_no is None:
            col.errors.append(f"{rel}: letec 파일에서 대표 사건번호 추출 실패")
        category, category_src = meta.get("분류"), "meta"

    doctype = "post" if case_no is None else ("detc" if "헌" in case_no else "prec")
    return {
        "doc_id": NFC(rel),
        "source": source,
        "case_no": case_no,
        "case_alias": alias,
        "case_src": case_src,
        "case_key": case_key_of(case_no),
        "doctype": doctype,
        "court": meta.get("법원"),
        "decided": meta.get("작성일"),
        "title": parse_title(body),
        "category": category,
        "category_src": category_src,
        "post_id": post_id,
        "origin_url": origin_url_of(meta),
        "issues": parse_issues(body) if source == "letec" else [],
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "body_md": body,
    }


def load_overlap_by_postid(paths: Paths) -> dict[str, str]:
    """`_겹침대상.csv` → {게시글ID: 정준 사건번호}. build·gate·inventory가 공유 —
    파싱 규칙이 갈라지면 gate의 버킷과 build의 번들 판정이 어긋난다(F7)."""
    out: dict[str, str] = {}
    for r in _read_csv(os.path.join(paths.letec_dir, "_겹침대상.csv")):
        canon = _canon_or_none(r.get("사건번호", ""))
        if canon and r.get("게시글ID"):
            out[r["게시글ID"].strip()] = canon[0]
    return out


def collect_docs(paths: Paths, overlap_by_postid: dict[str, str]) -> Collected:
    col = Collected()
    # letec: 밑줄로 시작하지 않는 .md (설계 §2.1)
    for fn in sorted(os.listdir(paths.letec_dir)):
        if fn.startswith("_") or not fn.endswith(".md"):
            continue
        full = os.path.join(paths.letec_dir, fn)
        rel = NFC(os.path.relpath(full, paths.doc_root))
        doc = read_doc(full, rel, "letec", None, None, overlap_by_postid, col)
        if doc:
            col.docs.append(doc)
    # crawl: 카테고리 하위 폴더, _index.md 제외 (설계 §2.2)
    for root, _dirs, files in sorted(os.walk(paths.crawl_dir)):
        for fn in sorted(files):
            if fn.startswith("_") or not fn.endswith(".md"):
                continue
            full = os.path.join(root, fn)
            rel = NFC(os.path.relpath(full, paths.doc_root))
            category = NFC(os.path.basename(root)) if root != paths.crawl_dir else None
            doc = read_doc(full, rel, "crawl", category, "folder",
                           overlap_by_postid, col)
            if doc:
                col.docs.append(doc)
    col.docs.sort(key=lambda d: d["doc_id"])
    return col


def index_missing(paths: Paths, docs: list[dict]) -> list[str]:
    """_index.md 링크 중 실파일이 없는 것 — 크롤 쪽 유일의 '있어야 할 것'
    기록이므로 버리지 않고 대조한다(설계 §2.2, 검증 M8)."""
    idx = os.path.join(paths.crawl_dir, "_index.md")
    if not os.path.exists(idx):
        return []
    with open(idx, encoding="utf-8") as f:
        text = NFC(f.read())

    # 선두 토큰(post_id·사건번호) 기준 대조 — 파일명 전체 문자열 대조는 색인
    # 생성 후 제목이 조금만 바뀌어도 유실로 오탐한다(실측: 105건 → 토큰 대조로 재판정).
    have = {head_token(os.path.basename(d["doc_id"]))
            for d in docs if d["source"] == "crawl"}
    missing = []
    for _label, target in _MD_LINK_RE.findall(text):
        name = NFC(os.path.basename(target))
        if name.endswith(".md") and head_token(name) not in have:
            missing.append(name)
    return sorted(set(missing))


# ── 크롤 게이트 (설계 §7) ────────────────────────────────────────────────────

_MARKER_RE = re.compile(r"【[^】]{1,20}】")
_REQUIRED_MARKERS = (re.compile(r"【\s*주\s*문\s*】"),
                     re.compile(r"【\s*이\s*유\s*】"))
_DETC_MARKER = re.compile(r"【\s*결정요지\s*】")
_SIGN_RE = re.compile(r"^\s*(재판장\s*)?(대법관|판사|법관|헌법재판관)\s")
# 판결문 종결 문구 — 크롤 판결문은 서명줄 없이 이 문구로 끝나는 서식이 다수라
# (실측: 신세대 473건이 서명 부재로 이유 본문 전체가 '블록 밖'으로 오계산),
# 마지막 앵커 후보에 포함한다. 진짜 말미 해설은 이 문구 **뒤**에 오므로 여전히 잡힌다.
_TERMINAL_RE = re.compile(r"주문과 같이\s*(판결|결정)(한다|함)|관여\s*(대법관|법관)의?\s*일치된\s*의견")
_SUBSTANTIVE_SKIP = re.compile(r"^\s*$|^---\s*$|^#\s|^\|.*\|\s*$|^>\s")
# 육안 게이트 1차(2026-09-01, 표본 73건)에서 발견된 혼입 2유형 — 발견 즉시 규칙에
# 추가하고 전량 재분류하는 §7.2 절차의 산물. 판결문 블록 안팎을 가리지 않는다.
_EDIT_NOTICE_RE = re.compile(r"※[^\n]*(홈페이지|참고자료|준회원|이하\s*생략|바로가기)")
_JS_DEBRIS_RE = re.compile(r"document\.on\w+|CheckKeyPress|<script|// *-->|event\.keyCode")

MAX_EDGE_LINES = 5  # 블록 앞/뒤 각각 허용 실질 줄 수 — 실측 확정(2026-09-01, 규칙 v3:
                    # verbatim 후보의 front/back 분포가 (1,0) 중심, 5 초과는 혼입·오염뿐)


def classify_gate_bucket(doc: dict) -> tuple[str, dict]:
    """자동 3-버킷. 판정 순서: ①대표 유무 → ②구조 마커(설계 §7.1)."""
    if doc["case_no"] is None:
        return "post", {}
    body = doc["body_md"]
    tail = body.split("\n---\n", 1)[1] if "\n---\n" in body else body

    has_required = (all(p.search(tail) for p in _REQUIRED_MARKERS)
                    or _DETC_MARKER.search(tail))
    has_sentence = bool(re.search(r"선고\s*" + re.escape(doc["case_no"]), NFC(tail))
                        or (doc["case_alias"] and
                            re.search(r"선고\s*" + re.escape(doc["case_alias"]), NFC(tail))))
    if not (has_required and has_sentence):
        return "editorial", {"reason": "marker" if not has_required else "sentence"}
    if _EDIT_NOTICE_RE.search(tail):
        return "editorial", {"reason": "edit_notice"}
    if _JS_DEBRIS_RE.search(tail):
        return "editorial", {"reason": "js_debris"}

    lines = tail.splitlines()
    anchor_idx = [i for i, ln in enumerate(lines)
                  if _MARKER_RE.search(ln) or _SIGN_RE.match(ln) or _TERMINAL_RE.search(ln)]
    if not anchor_idx:
        # 마커 내부에 개행이 낀 문서(【주\n문】)는 has_required(\s가 개행 포함)를
        # 통과하지만 줄 단위 앵커에는 안 잡힌다 — 빈 리스트로 build를 죽이는 대신
        # 보수 방향인 editorial로(CodeRabbit PR#61 지적).
        return "editorial", {"reason": "no_anchor"}
    first, last = anchor_idx[0], anchor_idx[-1]
    front = sum(1 for ln in lines[:first] if not _SUBSTANTIVE_SKIP.match(ln))
    back = sum(1 for ln in lines[last + 1:] if not _SUBSTANTIVE_SKIP.match(ln))
    stats = {"front": front, "back": back}
    if front > MAX_EDGE_LINES or back > MAX_EDGE_LINES:
        return "editorial", {**stats, "reason": "edge_text"}
    return "verbatim", stats


# ── 코드 인용 스캔 (설계 §2.4) ───────────────────────────────────────────────

CODE_SCAN_DIRS = ("app", "wage_calculator", "harassment_assessor")
CODE_SCAN_FILES = ("wage_calculator_cli.py", "build_graph.py")


def _docstring_lines(src: str) -> set[int]:
    out: set[int] = set()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                out.update(range(body[0].value.lineno, body[0].value.end_lineno + 1))
    return out


def scan_code_citations(base: str) -> list[dict]:
    """프로덕션 코드의 사건번호 인용 → [{case_no,file,line,context}].

    컨텍스트: data(문자열 리터럴)/docstring/comment/cli_case(CLI 테스트 케이스).
    파이프라인·테스트 스크립트는 제외 — OCR 정정 맵·픽스처는 인용이 아니다.
    """
    targets: list[str] = []
    for d in CODE_SCAN_DIRS:
        for root, _dirs, files in os.walk(os.path.join(base, d)):
            targets += [os.path.join(root, f) for f in files if f.endswith(".py")]
    targets += [os.path.join(base, f) for f in CODE_SCAN_FILES
                if os.path.exists(os.path.join(base, f))]

    rows: list[dict] = []
    for path in sorted(targets):
        rel = os.path.relpath(path, base)
        try:
            with open(path, encoding="utf-8") as f:
                src = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        doc_lines = _docstring_lines(src)
        cli = os.path.basename(path) == "wage_calculator_cli.py"
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        except tokenize.TokenError:
            continue
        for tok in tokens:
            if tok.type == tokenize.COMMENT:
                kind = "comment"
            elif tok.type == tokenize.STRING:
                kind = "docstring" if tok.start[0] in doc_lines else "data"
            else:
                continue
            if cli:
                kind = "cli_case"
            for m in CASE_RE.finditer(NFC(tok.string)):
                canon = canonicalize("".join(m.groups()))
                if canon:
                    row = {"case_no": canon[0], "file": rel,
                           "line": tok.start[0], "context": kind}
                    if row not in rows:  # 한 토큰 안의 같은 번호 반복은 1건(gap L6)
                        rows.append(row)

    # MAJOR_PRECEDENTS 교차검증 — 지식그래프 노드는 공백이 가장 치명적(검증 H4).
    # build_graph.py도 스캔 대상이라 정규식으로 이미 잡혀야 하며, 구조 열거는
    # 그 완전성을 확인하는 안전망이다. base 스코프를 지킨다 — 실저장소 모듈을
    # 무조건 import하면 격리 base(테스트 픽스처)에 실데이터가 섞인다(F8).
    if os.path.exists(os.path.join(base, "build_graph.py")):
        try:
            import build_graph
            scanned = {r["case_no"] for r in rows}
            for k in build_graph.MAJOR_PRECEDENTS:
                canon = canonicalize(k)
                if canon and canon[0] not in scanned:
                    rows.append({"case_no": canon[0], "file": "build_graph.py",
                                 "line": 0, "context": "data"})
        except ImportError as e:
            print(f"  [경고] build_graph import 실패 — MAJOR_PRECEDENTS 교차검증 생략: {e}")
    rows.sort(key=lambda r: (r["case_no"], r["file"], r["line"]))
    return rows


# ── records 로드 ──────────────────────────────────────────────────────────────

def _read_csv(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _read_json(path: str):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_ledger(paths: Paths) -> dict[str, list[str]]:
    """원장 — 로컬 원본 우선, 없으면(CI) 스냅샷. 읽기 전용."""
    origin = os.path.join(paths.letec_dir, "_uploaded_ids.json")
    snap = os.path.join(paths.records_dir, "ledger_uploaded_ids.json")
    return _read_json(origin) or _read_json(snap) or {}


# ── 결정적 직렬화 (설계 §4.4) ────────────────────────────────────────────────

def _atomic_bytes(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def bundle_bytes(records: list[dict]) -> bytes:
    """레코드 → 결정적 jsonl.gz 바이트. gzip 기본 mtime 삽입 차단(mtime=0)."""
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        for rec in sorted(records, key=lambda r: r["doc_id"]):
            gz.write(json.dumps(rec, ensure_ascii=False, sort_keys=True).encode("utf-8"))
            gz.write(b"\n")
    return buf.getvalue()


def read_bundle(path: str) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def csv_bytes(rows: list[dict], cols: list[str]) -> bytes:
    """utf-8-sig CSV(기존 records 관례·한국어 Excel). 개행 \\n 고정 — 결정성."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
    w.writeheader()
    for row in rows:
        w.writerow({c: ("" if row.get(c) is None else row[c]) for c in cols})
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


# ── Pinecone 열거 (조회 전용) ────────────────────────────────────────────────

def snapshot_pinecone(paths: Paths) -> None:
    """laborlaw-v2의 ctx_precedent_* + 사장 NS ID 열거 → records/ 스냅샷.

    유일한 네트워크 경로이고 조회 전용이다. 이후 build는 스냅샷만 읽는다.
    """
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)
    from pinecone import Pinecone
    from app.config import resolve_index_name
    index = Pinecone(api_key=os.getenv("PINECONE_API_KEY")).Index(resolve_index_name())

    def _list_ids(prefix: str, namespace: str) -> list[str]:
        out: list[str] = []
        for batch in index.list(prefix=prefix, namespace=namespace):
            for item in batch:
                vid = item if isinstance(item, str) else getattr(item, "id", None)
                if isinstance(vid, str):
                    out.append(vid)
        return sorted(out)

    ctx = _list_ids("ctx_precedent_", "laborlaw-v2")
    dead = {ns: _list_ids("", ns) for ns in ("precedent", "laborlaw")}
    os.makedirs(paths.records_dir, exist_ok=True)
    _atomic_bytes(os.path.join(paths.records_dir, "ctx_vector_ids.json"),
                  json.dumps(ctx, ensure_ascii=False, indent=1).encode("utf-8"))
    _atomic_bytes(os.path.join(paths.records_dir, "dead_ns_ids.json"),
                  json.dumps(dead, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8"))
    print(f"  Pinecone 스냅샷: ctx {len(ctx)}개, 사장 NS "
          + ", ".join(f"{k} {len(v)}" for k, v in dead.items()))


# ── 인벤토리 조립 (설계 §5) ──────────────────────────────────────────────────

def _canon_or_none(raw: str) -> tuple[str, str | None] | None:
    """OCR 정정(교재 유래 CSV용) → 정준형. 기각은 None."""
    fixed = OCR_FIXES.get(normalize_case_no(raw), raw)
    return canonicalize(fixed)


def build_inventory(docs: list[dict], ledger: dict[str, list[str]],
                    code_rows: list[dict], paths: Paths, summary: dict,
                    overlap_by_postid: dict[str, str],
                    index_missing_names: list[str]) -> tuple[list[dict], list[dict]]:
    # 벡터 스냅샷은 행 생성 전에 로드 — 존재 여부가 row() 초기값(0=확인/None=미확인,
    # 설계 §5.1)을 결정하므로, 사후 스윕으로 보정하면 생성 순서에 의존하게 된다(F6).
    ctx_ids = _read_json(os.path.join(paths.records_dir, "ctx_vector_ids.json"))
    dead = _read_json(os.path.join(paths.records_dir, "dead_ns_ids.json"))

    rows: dict[str, dict] = {}
    alias_of: dict[str, set[str]] = defaultdict(set)
    notes: dict[str, set[str]] = defaultdict(set)

    def row(case_no: str) -> dict:
        if case_no not in rows:
            rows[case_no] = {c: None for c in INVENTORY_COLS}
            rows[case_no].update(case_no=case_no, doc_letec=0, doc_crawl=0,
                                 vec_chunks=0, cited_code=0, cited_textbook=0,
                                 not_found=0, overlap=0,
                                 vec_ctx=0 if ctx_ids is not None else None,
                                 vec_dead=0 if dead is not None else None)
        return rows[case_no]

    dropped: list[str] = []

    def union_rows(path: str):
        """CSV 행 → (inventory 행, 원본 행). 화이트리스트 기각은 dropped로,
        표기 병합은 alias·note로 처리한 뒤 넘긴다."""
        for r in _read_csv(path):
            canon = _canon_or_none(r.get("사건번호", ""))
            if canon is None:
                dropped.append(f"{os.path.basename(path)}: {r.get('사건번호', '')!r}")
                continue
            if canon[1]:
                alias_of[canon[0]].add(canon[1])
                notes[canon[0]].add("표기병합")
            yield row(canon[0]), r

    # 문서 (letec 우선 정본 규칙 — 설계 §5.1)
    for d in docs:
        if d["case_no"] is None:
            continue
        rec = row(d["case_no"])
        if d["case_alias"]:
            alias_of[d["case_no"]].add(d["case_alias"])
            notes[d["case_no"]].add("표기병합")
        key = "doc_letec" if d["source"] == "letec" else "doc_crawl"
        rec[key] += 1
        # letec이 정본이라 무조건 덮어쓰고, crawl은 빈 자리만 채운다(설계 §5.1)
        for f in ("court", "decided", "title"):
            if d[f] and (d["source"] == "letec" or not rec.get(f)):
                rec[f] = d[f]

    # 원장 역매핑 — 검색에는 있는데 문서·인용 어디에도 없는 사건도 행이 된다
    rev_fail: list[str] = []
    for key, ids in ledger.items():
        case_no = reverse_case_key(key)
        if case_no is None:
            rev_fail.append(key)
            continue
        canon = canonicalize(case_no)
        rec = row(canon[0] if canon else case_no)
        rec["vec_chunks"] = len(ids)

    # 코드 인용 — docstring/comment뿐인 사건은 예시의심 자동 초안(설계 §2.4)
    ctx_by_case: dict[str, set[str]] = defaultdict(set)
    for r in code_rows:
        rec = row(r["case_no"])
        rec["cited_code"] += 1
        ctx_by_case[r["case_no"]].add(r["context"])
    for case_no, ctxs in ctx_by_case.items():
        if case_no in EXAMPLE_CONFIRMED:
            notes[case_no].add("예시확정")
        elif case_no not in EXAMPLE_OVERRIDE_REAL and ctxs <= {"docstring", "comment"}:
            notes[case_no].add("예시의심")

    # 교재 인용·미발견·겹침 (OCR 정정 적용 — 교재 OCR 유래 표기)
    for rec, r in union_rows(paths.textbook_csv):
        rec["cited_textbook"] += int(r.get("인용횟수") or 1)
        # 문서가 없는 사건의 법원·날짜 폴백(설계 §5.1 채움 규칙 3순위)
        if not rec.get("court") and r.get("법원"):
            rec["court"] = NFC(r["법원"].strip())
        if not rec.get("decided") and r.get("날짜"):
            rec["decided"] = NFC(r["날짜"].strip())
    for rec, _r in union_rows(os.path.join(paths.letec_dir, "_미발견.csv")):
        rec["not_found"] = 1
    for rec, _r in union_rows(os.path.join(paths.letec_dir, "_겹침대상.csv")):
        rec["overlap"] = 1
    ctx_deleted = _read_json(os.path.join(paths.letec_dir, "_ctx_deleted.json")) or {}
    for case_no in ctx_deleted:
        canon = canonicalize(case_no)
        if canon:
            row(canon[0])

    # vec_ctx — ctx 벡터 스냅샷(post_id 키) → 겹침·ctx_deleted·크롤 문서 대응(설계 §5.1)
    if ctx_ids is not None:
        post_to_case = dict(overlap_by_postid)
        for case_no, ids in ctx_deleted.items():
            canon = canonicalize(case_no)
            if canon:
                for vid in ids:
                    m = re.match(r"ctx_precedent_(\d+)_", vid)
                    if m:
                        post_to_case.setdefault(m.group(1), canon[0])
        for d in docs:
            if d["source"] == "crawl" and d["post_id"] and d["case_no"]:
                post_to_case.setdefault(d["post_id"], d["case_no"])
        counts: dict[str, int] = defaultdict(int)
        unmapped_ctx = 0
        for vid in ctx_ids:
            m = re.match(r"ctx_precedent_(\d+)_", vid)
            case_no = post_to_case.get(m.group(1)) if m else None
            if case_no:
                counts[case_no] += 1
            else:
                unmapped_ctx += 1
        for case_no, n in counts.items():
            row(case_no)["vec_ctx"] = n
        summary["ctx_unmapped"] = unmapped_ctx

    # vec_dead — 사장 NS 존재 사실(설계 D-11). 역매핑 가능분만.
    if dead is not None:
        for ids in dead.values():
            for vid in ids:
                m = re.match(r"precedent_([0-9a-z]+)_chunk_", vid)
                if not m:
                    continue
                case_no = reverse_case_key(m.group(1))
                if case_no:
                    canon = canonicalize(case_no)
                    if canon:
                        row(canon[0])["vec_dead"] = 1

    # 크롤 색인 누락 — 사건번호형 선두 토큰이면 해당 사건 note에도 기록(설계 §2.2)
    for name in index_missing_names:
        token = head_token(name)
        canon = canonicalize(token) if not token.isdigit() else None
        if canon:
            notes[row(canon[0])["case_no"]].add("크롤색인누락")

    # 원장미수록 사유 자동 판정 — 실측(2026-09-01): 10건 전부 하급심·헌재로
    # 법제처가 요지를 제공하지 않아 EMBED_SECTIONS가 비고 업로더가 스킵한 것.
    letec_has_sections = {
        d["case_no"]: any(f"## {s}" in d["body_md"] for s in EMBED_SECTIONS)
        for d in docs if d["source"] == "letec" and d["case_no"]}

    # note 확정 — 원장미수록(R4 후보)·미매핑부호
    for rec in rows.values():
        if rec["doc_letec"] and not rec["vec_chunks"]:
            notes[rec["case_no"]].add(
                "원장미수록" if letec_has_sections.get(rec["case_no"], True)
                else "원장미수록(섹션없음)")
        if rec["doc_letec"] > 1:
            notes[rec["case_no"]].add("letec중복")
        rec["case_key"] = case_key_of(rec["case_no"])
        if rec["case_key"] is None:
            notes[rec["case_no"]].add("미매핑부호")
        rec["case_alias"] = ";".join(sorted(alias_of[rec["case_no"]])) or None
        rec["note"] = ";".join(sorted(notes[rec["case_no"]])) or None

    summary["union_dropped"] = dropped
    summary["ledger_reverse_fail"] = rev_fail
    summary["index_missing"] = index_missing_names
    inv = sorted(rows.values(), key=lambda r: r["case_no"])

    documents = [{
        "doc_id": d["doc_id"], "source": d["source"], "case_no": d["case_no"],
        "case_src": d["case_src"], "doctype": d["doctype"], "category": d["category"],
        "category_src": d["category_src"], "post_id": d["post_id"], "title": d["title"],
        "gate": d["gate"], "bundled": d["bundled"],
    } for d in sorted(docs, key=lambda x: x["doc_id"])]
    return inv, documents


# ── 게이트 상태 (설계 §7.3) ──────────────────────────────────────────────────

def load_gate_state(paths: Paths) -> dict:
    return _read_json(os.path.join(paths.records_dir, "crawl_gate.json")) or {
        "rule_version": GATE_RULE_VERSION, "approved": False}


def apply_gate(docs: list[dict], gate_state: dict) -> dict:
    """자동 분류 + 승인 상태 반영. 비공개 방향(editorial·post)은 자동 확정,
    공개 방향(verbatim)은 육안 승인 전까지 pending(설계 §7 — 오공개 비대칭)."""
    approved = bool(gate_state.get("approved")) and \
        gate_state.get("rule_version") == GATE_RULE_VERSION
    buckets: dict[str, list[str]] = {"verbatim": [], "editorial": [], "post": []}
    for d in docs:
        if d["source"] == "letec":
            d["gate"], d["bundled"] = "exempt", 1
            continue
        bucket, stats = classify_gate_bucket(d)
        d["_gate_stats"] = stats
        buckets[bucket].append(d["doc_id"])
        if bucket == "verbatim" and not approved:
            d["gate"], d["bundled"] = "pending", 0
        else:
            d["gate"] = bucket
            d["bundled"] = 1 if bucket == "verbatim" else 0
    return buckets


# ── build ────────────────────────────────────────────────────────────────────

def run_build(paths: Paths, pinecone: bool = False, quiet: bool = False) -> dict:
    say = (lambda *a: None) if quiet else print
    if pinecone:
        snapshot_pinecone(paths)

    col = collect_docs(paths, load_overlap_by_postid(paths))
    gate_state = load_gate_state(paths)
    buckets = apply_gate(col.docs, gate_state)

    summary: dict = {}
    ledger = load_ledger(paths)
    code_rows = scan_code_citations(paths.code_scan_base)
    inv, documents = build_inventory(
        col.docs, ledger, code_rows, paths, summary,
        overlap_by_postid=load_overlap_by_postid(paths),
        index_missing_names=index_missing(paths, col.docs))

    os.makedirs(paths.records_dir, exist_ok=True)

    # 번들 — letec 전량 + (승인 시) crawl verbatim (설계 §4.3).
    # 공개 커밋 산출물이므로 스키마는 화이트리스트(BUNDLE_FIELDS) — 작업 필드가
    # 늘어도 조용히 실리지 않는다(F3). V1이 필드 정합을 검사한다.
    def _write_bundle(name: str, records: list[dict]) -> dict:
        data = bundle_bytes([{k: d[k] for k in BUNDLE_FIELDS} for d in records])
        _atomic_bytes(os.path.join(paths.out_dir, name), data)
        return {"path": name, "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data), "records": len(records)}

    letec_records = [d for d in col.docs if d["source"] == "letec"]
    bundles = [_write_bundle("letec_precedents.jsonl.gz", letec_records)]
    crawl_records = [d for d in col.docs if d["source"] == "crawl" and d["bundled"]]
    crawl_path = os.path.join(paths.out_dir, "crawl_verbatim.jsonl.gz")
    if crawl_records:
        bundles.append(_write_bundle("crawl_verbatim.jsonl.gz", crawl_records))
    elif os.path.exists(crawl_path):
        os.remove(crawl_path)

    _atomic_bytes(os.path.join(paths.out_dir, "inventory.csv"),
                  csv_bytes(inv, INVENTORY_COLS))
    _atomic_bytes(os.path.join(paths.out_dir, "documents.csv"),
                  csv_bytes(documents, DOCUMENTS_COLS))
    _atomic_bytes(os.path.join(paths.records_dir, "code_citations.csv"),
                  csv_bytes(code_rows, ["case_no", "file", "line", "context"]))

    # 스냅샷 — 원본 바이트 그대로 단방향 복사(설계 §9)
    origin_digests = {}
    for snap_rel, origin in paths.snapshot_origins().items():
        if not os.path.exists(origin):
            continue
        with open(origin, "rb") as f:
            data = f.read()
        _atomic_bytes(os.path.join(paths.out_dir, snap_rel), data)
        origin_digests[snap_rel] = {"sha256": hashlib.sha256(data).hexdigest()}
        if snap_rel.endswith("ledger_uploaded_ids.json"):
            # 원본 우선 load_ledger와 같은 파일이므로 재파싱 불요(효율 리뷰 1)
            origin_digests[snap_rel]["groups"] = len(ledger)

    # crawl_gate.json은 gate 서브커맨드가 단독 소유한다 — build가 buckets를
    # 리프레시하면 "추첨→파일변경→build→approve" 순서에서 승인 드리프트 가드가
    # 자기 자신과 비교해 무력화된다(simplify 리뷰 F1). build는 읽기 전용.

    manifest = {
        "counts": {"letec": len(letec_records),
                   "crawl": sum(1 for d in col.docs if d["source"] == "crawl"),
                   "inventory_rows": len(inv), "documents_rows": len(documents)},
        "bundles": bundles,
        "snapshot_map": {k: os.path.relpath(v, BASE_DIR)
                         for k, v in paths.snapshot_origins().items()},
        "snapshot_origin_digests": origin_digests,
        "scope_notes": [
            "NLRC 제외 — data/nlrc_cases.json에 사건번호·본문 필드 없음(설계 §5.3)",
            "사장 NS는 vec_dead 존재 표시만 — NFD 손상 이력으로 역매핑은 가능분만(설계 D-11)",
        ],
        "gate_rule_version": GATE_RULE_VERSION,
    }
    _atomic_bytes(os.path.join(paths.out_dir, "MANIFEST.json"),
                  json.dumps(manifest, ensure_ascii=False, indent=1,
                             sort_keys=True).encode("utf-8"))

    say(f"\n[build] letec {len(letec_records)} / crawl {manifest['counts']['crawl']}"
        f" / inventory {len(inv)}행 / documents {len(documents)}행")
    say(f"  게이트 버킷: " + ", ".join(f"{k} {len(v)}" for k, v in buckets.items())
        + (" (verbatim은 승인 전 pending)" if not gate_state.get("approved") else ""))
    for label, items in (("오류", col.errors), ("화이트리스트 기각", col.rejects),
                         ("파일명-메타 불일치", col.mismatches),
                         ("크롤 색인 누락", summary.get("index_missing", [])),
                         ("union 기각", summary.get("union_dropped", [])),
                         ("원장 역매핑 실패", summary.get("ledger_reverse_fail", []))):
        say(f"  {label}: {len(items)}건")
        for it in items[:10]:
            say(f"    - {it}")
        if len(items) > 10:
            say(f"    … 외 {len(items) - 10}건")
    if "ctx_unmapped" in summary:
        say(f"  ctx 벡터 사건 미대응: {summary['ctx_unmapped']}개")
    return {"manifest": manifest, "collected": col, "inventory": inv,
            "documents": documents, "buckets": buckets, "summary": summary}


# ── gate 서브커맨드 ──────────────────────────────────────────────────────────

def run_gate(paths: Paths, approve: bool, as_of: str | None, seed: int = 20260901) -> int:
    import random
    col = collect_docs(paths, load_overlap_by_postid(paths))
    prev = load_gate_state(paths)
    # 분류 드라이버는 apply_gate 하나 — 별도 루프를 두면 gate 화면의 버킷과
    # build 기록이 갈라질 수 있고, 승인 드리프트 가드가 그 일치를 전제한다(F7).
    buckets = apply_gate(col.docs, prev)

    print(f"[gate] 규칙 v{GATE_RULE_VERSION} — "
          + ", ".join(f"{k} {len(v)}" for k, v in buckets.items()))

    bucket_counts = {k: len(v) for k, v in buckets.items()}

    if approve:
        # 표본을 재추첨하지 않는다 — 승인은 "기록된 표본을 육안했다"는 진술이므로
        # 재추첨하면 기록과 실제 육안 대상이 조용히 어긋난다(gap 분석 M1).
        if not as_of:
            print("  --approve에는 --as-of YYYY-MM-DD가 필요합니다 (판정일 기록)")
            return 1
        if prev.get("rule_version") != GATE_RULE_VERSION or not prev.get("sample"):
            print("  승인 불가 — 현재 규칙으로 추첨된 표본 기록이 없습니다. gate를 먼저 실행하세요.")
            return 1
        if prev.get("buckets") != bucket_counts:
            print("  승인 불가 — 분류 결과가 표본 추첨 시점과 다릅니다(파일 변경). "
                  "gate 재실행 후 재육안하세요.")
            return 1
        state = dict(prev)
        state["approved"] = True
        state["approved_as_of"] = as_of
        for rnd in state.get("rounds", []):
            if rnd["seed"] == prev.get("seed") and rnd["rule_version"] == GATE_RULE_VERSION:
                rnd.update(approved=True, as_of=as_of)
        print(f"  승인 기록(표본 seed={prev.get('seed')}, {len(prev['sample'])}건) — "
              f"다음 build부터 verbatim {bucket_counts['verbatim']}건이 번들 대상입니다")
    else:
        by_id = {d["doc_id"]: d for d in col.docs}
        verbatim = [by_id[did] for did in buckets["verbatim"]]
        rng = random.Random(seed)  # 결정적 추첨 — 판정 이력의 재현성(설계 §7.2)
        sample = rng.sample(verbatim, min(60, len(verbatim)))
        edge = sorted(verbatim, key=lambda d: -(d["_gate_stats"].get("front", 0)
                                                + d["_gate_stats"].get("back", 0)))[:20]
        sample_ids = sorted({d["doc_id"] for d in sample} | {d["doc_id"] for d in edge})
        state = {
            "rule_version": GATE_RULE_VERSION,
            "buckets": bucket_counts,
            "sample": sample_ids,
            "seed": seed,
            "approved": False,
            # 라운드 이력 — 규칙 진화(v1→v3)와 재추첨의 감사 추적
            "rounds": prev.get("rounds", []) + [{
                "rule_version": GATE_RULE_VERSION, "seed": seed,
                "buckets": bucket_counts, "sample_size": len(sample_ids),
                "approved": False,
            }],
        }
        print(f"  육안 표본 {len(sample_ids)}건 (무작위 {len(sample)} + 경계 {len(edge)}, seed={seed})")
        for did in sample_ids:
            print(f"    {did}")
        print("  육안 완료 후: python3 archive_precedents.py gate --approve --as-of YYYY-MM-DD")
    os.makedirs(paths.records_dir, exist_ok=True)
    _atomic_bytes(os.path.join(paths.records_dir, "crawl_gate.json"),
                  json.dumps(state, ensure_ascii=False, indent=1,
                             sort_keys=True).encode("utf-8"))
    return 0


# ── verify (설계 §8) ─────────────────────────────────────────────────────────

def run_verify(paths: Paths) -> int:
    failures: list[str] = []

    def check(vid: str, cond: bool, detail: str = "") -> None:
        mark = "✅" if cond else "❌"
        print(f"  {mark} {vid}" + ("" if cond else f"  {detail}"))
        if not cond:
            failures.append(vid)

    manifest = _read_json(os.path.join(paths.out_dir, "MANIFEST.json"))
    if manifest is None:
        print("  MANIFEST.json 없음 — build를 먼저 실행하세요")
        return 1
    local = os.path.isdir(paths.letec_dir)

    # V0 — MANIFEST 대조
    det0: list[str] = []
    bundle_recs: dict[str, list[dict]] = {}
    for b in manifest["bundles"]:
        p = os.path.join(paths.out_dir, b["path"])
        if not os.path.exists(p):
            det0.append(f"{b['path']} 없음")
            continue
        with open(p, "rb") as f:
            data = f.read()
        if hashlib.sha256(data).hexdigest() != b["sha256"]:
            det0.append(f"{b['path']} sha256 불일치")
        # 방금 읽은 바이트에서 파싱 — 같은 파일 디스크 재읽기 제거
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
            bundle_recs[b["path"]] = [
                json.loads(line) for line in gz.read().decode("utf-8").splitlines() if line]
        if len(bundle_recs[b["path"]]) != b["records"]:
            det0.append(f"{b['path']} 레코드 수 불일치")
    inv = _read_csv(os.path.join(paths.out_dir, "inventory.csv"))
    documents = _read_csv(os.path.join(paths.out_dir, "documents.csv"))
    if len(inv) != manifest["counts"]["inventory_rows"]:
        det0.append("inventory 행 수 불일치")
    if len(documents) != manifest["counts"]["documents_rows"]:
        det0.append("documents 행 수 불일치")
    if sum(1 for d in documents if d["source"] == "crawl") != manifest["counts"]["crawl"]:
        det0.append("counts.crawl 불일치")
    check("V0 MANIFEST 대조", not det0, "; ".join(det0))

    all_recs = [r for recs in bundle_recs.values() for r in recs]

    # V1 — 파싱·스키마 정합·doc_id 유일. 공개 산출물이라 여분 필드도 결함이다
    # (화이트리스트 스키마 — 포함 검사만 하면 새는 작업 필드를 못 잡는다).
    bad_schema = [r.get("doc_id", "?") for r in all_recs
                  if set(r) != set(BUNDLE_FIELDS)]
    ids = [r["doc_id"] for r in all_recs]
    check("V1 번들 파싱·스키마 정합·doc_id 유일",
          not bad_schema and len(ids) == len(set(ids)),
          f"스키마 불일치 {len(bad_schema)}건, 중복 {len(ids) - len(set(ids))}건")

    # V2 — 자기 정합
    bad2 = [r["doc_id"] for r in all_recs
            if hashlib.sha256(r["body_md"].encode("utf-8")).hexdigest() != r["sha256"]]
    check("V2 body_md sha256 자기 정합", not bad2, f"{len(bad2)}건: {bad2[:3]}")

    # V3 — 원본 대조 (로컬 전용, 전 건)
    if local:
        bad3 = []
        for r in all_recs:
            path = paths.doc_path(r["doc_id"])
            try:
                with open(path, "rb") as f:
                    if f.read() != r["body_md"].encode("utf-8"):
                        bad3.append(r["doc_id"])
            except OSError:
                bad3.append(r["doc_id"] + " (원본 없음)")
        check("V3 원본 바이트 대조(전수)", not bad3, f"{len(bad3)}건: {bad3[:3]}")
    else:
        print("  ⏭️ V3 생략(로컬 원본 없음)")

    # V4 — 원장 포섭 + 스냅샷 낡음 탐지
    ledger = load_ledger(paths)
    inv_keys = {r["case_key"] for r in inv if r["case_key"]}
    orphan = sorted(set(ledger) - inv_keys)
    ok4, det4 = not orphan, f"원장에만 있는 키 {len(orphan)}건: {orphan[:3]}"
    if local:
        origin = os.path.join(paths.letec_dir, "_uploaded_ids.json")
        digest = manifest.get("snapshot_origin_digests", {}).get(
            "records/ledger_uploaded_ids.json", {})
        if os.path.exists(origin) and digest:
            with open(origin, "rb") as f:
                data4 = f.read()
            if hashlib.sha256(data4).hexdigest() != digest.get("sha256"):
                ok4, det4 = False, "원장 원본이 스냅샷 이후 변경됨 — build 재실행 필요"
            elif len(ledger) != digest.get("groups"):
                # sha256이 같으면 load_ledger가 읽은 그 파일 — 재파싱 불요
                ok4, det4 = False, "원장 그룹 수가 MANIFEST 기록과 불일치"
    check("V4 원장 포섭(S2)·스냅샷 신선도", ok4, det4)

    # V5 — 장부 정합
    inv_by_no = {r["case_no"]: r for r in inv}
    cnt: dict[str, dict[str, int]] = defaultdict(lambda: {"letec": 0, "crawl": 0})
    for d in documents:
        if d["case_no"]:
            cnt[d["case_no"]][d["source"]] += 1
    bad5 = [no for no, c in cnt.items()
            if no not in inv_by_no
            or int(inv_by_no[no]["doc_letec"] or 0) != c["letec"]
            or int(inv_by_no[no]["doc_crawl"] or 0) != c["crawl"]]
    check("V5 inventory↔documents 정합", not bad5, f"{len(bad5)}건: {bad5[:3]}")

    # V6 — 인용 완결(S3)
    code_rows = _read_csv(os.path.join(paths.records_dir, "code_citations.csv"))
    bad6 = [r["case_no"] for r in code_rows
            if r["case_no"] not in inv_by_no
            or int(inv_by_no[r["case_no"]]["cited_code"] or 0) < 1]
    gaps = [r["case_no"] for r in inv
            if not any(int(r[c] or 0) for c in
                       ("doc_letec", "doc_crawl", "vec_chunks", "vec_ctx"))]
    check("V6 코드 인용 완결(S3)", not bad6, f"{len(bad6)}건: {sorted(set(bad6))[:5]}")
    print(f"     공백(문서·벡터 전무): {len(gaps)}건 — 후속 수집 대상(G3)")

    # V7 — 공개 불변식(S5)
    doc_gate = {d["doc_id"]: d for d in documents}
    bad7 = [r["doc_id"] for r in all_recs
            if doc_gate.get(r["doc_id"], {}).get("gate") not in ("exempt", "verbatim")]
    bad7 += [d["doc_id"] for d in documents
             if d["bundled"] == "1" and d["gate"] not in ("exempt", "verbatim")]
    check("V7 공개 불변식(S5)", not bad7, f"{len(bad7)}건: {bad7[:3]}")

    # V8 — 멱등(로컬 전용)
    if local:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            p2 = dataclasses.replace(paths, out_dir=tmp)
            # 게이트 상태는 산출물 records/에 있으므로 재빌드 전에 복사
            os.makedirs(p2.records_dir, exist_ok=True)
            for name in ("crawl_gate.json", "ctx_vector_ids.json", "dead_ns_ids.json"):
                src = os.path.join(paths.records_dir, name)
                if os.path.exists(src):
                    with open(src, "rb") as f:
                        _atomic_bytes(os.path.join(p2.records_dir, name), f.read())
            run_build(p2, quiet=True)
            bad8 = []
            # records/ 스냅샷·판정 기록도 멱등 대상 — 전부 커밋되는 산출물이다(gap L3)
            rec_rels = sorted(
                os.path.join("records", f)
                for f in os.listdir(paths.records_dir) if not f.endswith(".tmp"))
            for rel in (["inventory.csv", "documents.csv", "MANIFEST.json"]
                        + [b["path"] for b in manifest["bundles"]] + rec_rels):
                a, b = os.path.join(paths.out_dir, rel), os.path.join(tmp, rel)
                try:
                    with open(a, "rb") as fa, open(b, "rb") as fb:
                        if fa.read() != fb.read():
                            bad8.append(rel)
                except OSError:
                    bad8.append(rel + " (재빌드 산출물 없음)")
            check("V8 멱등(S6)", not bad8, f"불일치: {bad8}")
    else:
        print("  ⏭️ V8 생략(로컬 원본 없음)")

    print(f"\n[verify] {'실패 ' + str(len(failures)) + '건: ' + ', '.join(failures) if failures else '전체 통과'}")
    return 1 if failures else 0


# ── extract (설계 §10) ───────────────────────────────────────────────────────

def run_extract(paths: Paths, case_no: str, doc_id: str | None,
                out: str | None) -> int:
    canon = canonicalize(case_no)
    target_no = canon[0] if canon else normalize_case_no(case_no)
    hits: list[dict] = []
    for name in ("letec_precedents.jsonl.gz", "crawl_verbatim.jsonl.gz"):
        p = os.path.join(paths.out_dir, name)
        if os.path.exists(p):
            hits += [r for r in read_bundle(p) if r.get("case_no") == target_no]
    if not hits:
        print(f"번들에 {target_no} 문서가 없습니다 (inventory.csv에서 소재 확인)")
        return 1
    if len(hits) > 1 and not doc_id:
        print(f"{target_no} 문서가 {len(hits)}건입니다 — --doc-id로 선택하세요:")
        for r in hits:
            print(f"  {r['doc_id']}")
        return 1
    rec = hits[0] if len(hits) == 1 else next(
        (r for r in hits if r["doc_id"] == doc_id), None)
    if rec is None:
        print(f"doc_id 불일치: {doc_id}")
        return 1
    if out:
        _atomic_bytes(out, rec["body_md"].encode("utf-8"))
        print(f"복원 완료: {out}")
    else:
        sys.stdout.write(rec["body_md"])
    return 0


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="번들+장부+스냅샷 생성 (오프라인)")
    b.add_argument("--pinecone", action="store_true",
                   help="ctx·사장 NS 벡터 열거 스냅샷 갱신 (조회 전용)")
    g = sub.add_parser("gate", help="크롤 3-버킷 분류 + 육안 표본")
    g.add_argument("--approve", action="store_true")
    g.add_argument("--as-of", dest="as_of")
    g.add_argument("--seed", type=int, default=20260901,
                   help="표본 추첨 seed — 재분류 후 재추첨 시 새 값(§7.2)")
    e = sub.add_parser("extract", help="번들 → md 복원")
    e.add_argument("case_no")
    e.add_argument("--doc-id", dest="doc_id")
    e.add_argument("--out")
    sub.add_parser("verify", help="정합 검사 V0~V8")
    args = ap.parse_args(argv)

    paths = Paths()
    if args.cmd == "build":
        run_build(paths, pinecone=args.pinecone)
        return 0
    if args.cmd == "gate":
        return run_gate(paths, args.approve, args.as_of, seed=args.seed)
    if args.cmd == "extract":
        return run_extract(paths, args.case_no, args.doc_id, args.out)
    if args.cmd == "verify":
        return run_verify(paths)
    return 2


if __name__ == "__main__":
    sys.exit(main())
