#!/usr/bin/env python3
"""법제처 OPEN API 재결례 수집 — 고용보험심사위원회(`eiac`)·산업재해보상보험재심사위원회(`iaciac`).

설계: docs/02-design/features/adjudication-corpus.design.md §3

목록(`lawSearch.do`)은 사건명 fuzzy 검색뿐이라 **전량**을 받는다(display 100 페이지 순회, 2026-11-08 실측
118 + 934건). 상세(`lawService.do?ID=결정문일련번호`)를 받아 `output_재결례/{agency}/{일련번호}_{사건번호}.md`로
저장한다(gitignore `output_*/`). 업로드는 `pinecone_upload_rulings.py`.

지킬 것(설계 §3.2·§3.4·§3.5):
  · 인증 오류(`<Response>` 루트)는 `LawApiAuthError`로 **멈춘다**(exit 2). 진행 기록의 failed에 적지 않는다 —
    등록 밖 IP에서 돌리면 1,052건이 전부 '실패'로 남는 것을 막는다.
  · HTTP·파싱 실패·필수 필드 부재는 failed에 사유(클래스명+상태 / 필드명)만 적고 **다음 실행에 재시도**한다.
    court 수집기의 not_found처럼 영구 저장하지 않는다 — 여기는 '없음'이 아니라 '못 받음'이다.
  · 정제는 알려진 HTML 태그만 다룬다. `<근로계약서 발췌>` 같은 꺾쇠 캡션은 보존한다.
  · PII 스캔 결과는 보고만 하고 원문은 그대로 저장한다. 가림은 업로더가 `_pii_redactions.json`으로 적용한다 —
    md를 고치면 재수집이 원본으로 덮어쓴다.

사용법:
  python3 fetch_rulings.py                       # eiac + iaciac 전량(재개)
  python3 fetch_rulings.py --agency iaciac --limit 50
  python3 fetch_rulings.py --list-only           # 목록만(저장 없음)
  python3 fetch_rulings.py --serial 11327 --agency eiac
  python3 fetch_rulings.py --force
"""
from __future__ import annotations

import os
import re
import sys
import html
import json
import time
import argparse
import datetime as _dt
import unicodedata
import xml.etree.ElementTree as ET

import requests
from dotenv import load_dotenv

from app.core import safe_xml
from app.core.legal_api import LawApiAuthError, _raise_if_error_root
from vector_ledger import atomic_write_json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)

OUTPUT_DIR = os.path.join(BASE_DIR, "output_재결례")
PROGRESS_FILE = os.path.join(OUTPUT_DIR, "_progress.json")
PII_REPORT_FILE = os.path.join(OUTPUT_DIR, "_pii_report.json")

LAW_SEARCH_URL = "https://www.law.go.kr/DRF/lawSearch.do"
LAW_SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do"
REQUEST_DELAY = 0.3
MAX_RETRIES = 3
TIMEOUT = 20
PAGE_SIZE = 100


# 기관별 필드 차이(설계 §1.1 실측). iaciac 상세에는 `기관명`이 없어 상수를 쓴다.
AGENCIES: dict[str, dict] = {
    "eiac": {
        "name": "고용보험심사위원회", "title_field": "사건명", "summary_field": "개요",
        "summary_label": "개요", "respondent_field": "피청구인",
        "category_fields": ("사건의분류",), "kind_field": "의결서종류",
    },
    "iaciac": {
        "name": "산업재해보상보험재심사위원회", "title_field": "사건", "summary_field": "쟁점",
        "summary_label": "쟁점", "respondent_field": "원처분기관",
        "category_fields": ("사건대분류", "사건중분류", "사건소분류"), "kind_field": "문서제공구분",
    },
}

# iaciac `사건` 필드의 선행 번호(`2010재결 제2071호 요양불승인처분취소`) — eiac형 표기라 떼어낸다(D8).
_RULING_PREFIX_RE = re.compile(r"^\s*\d{4}\s*재결\s*제\s*\d+\s*호\s*")

# PII 패턴(설계 §3.5) — `\b`는 한글 뒤 숫자에서 경계가 아니므로 lookaround를 쓴다.
PII_PATTERNS = {
    "주민등록번호": re.compile(r"(?<!\d)\d{6}-[1-4]\d{6}(?!\d)"),
    "휴대전화": re.compile(r"(?<!\d)01[016789]-?\d{3,4}-?\d{4}(?!\d)"),
    "이메일": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
}


class MissingField(ValueError):
    """상세 응답에 필수 필드가 없다 — failed에 기록하고 재시도한다."""


class SerialMismatch(ValueError):
    """상세 응답의 결정문일련번호가 요청과 다르다 — 다른 결정문을 요청 번호로 저장하지 않는다(CodeRabbit #155)."""


# ── 정제 ─────────────────────────────────────────────────────────────────────

_HIDDEN_SPAN_RE = re.compile(r"<span[^>]*display\s*:\s*none[^>]*>.*?</span>", re.S | re.I)
_IMG_RE = re.compile(r"<img\b([^>]*)>(?:\s*</img>)?", re.I)
_IMG_ALT_RE = re.compile(r'alt\s*=\s*"([^"]*)"', re.I)
_FOOTNOTE_BREAK_RE = re.compile(r"<각주>\s*(\d+)\s*</각주>(?=\s*(?:\d+|[가-하])\.\s)")
_FOOTNOTE_RE = re.compile(r"<각주>\s*(\d+)\s*</각주>")
_BLOCK_TAG_RE = re.compile(r"</?(?:p|div|br|tr|li|table|tbody|thead)\b[^>]*/?>", re.I)
_INLINE_TAG_RE = re.compile(r"</?(?:span|font|b|i|u|strong|em|a|td|th|sup|sub)\b[^>]*/?>", re.I)
# 잔존 태그 판정은 알려진 HTML 태그 이름만 — `HORIZON<ALL>`(의료기기 규격, 실측 1건)처럼 꺾쇠가 든 본문은 태그가 아니다
RESIDUAL_TAG_RE = re.compile(
    r"</?(?:img|span|div|p|br|table|tbody|thead|tr|td|th|font|b|i|u|strong|em|a|sup|sub|ul|ol|li|h[1-6])\b[^>]*>",
    re.I)
_IMG_CLOSE_RE = re.compile(r"</img\s*>", re.I)   # 여는 태그 없이 홀로 남은 닫는 태그(eiac 2022~2023 실측 18건)


def clean_ruling_text(text: str | None) -> str:
    """법제처 재결 본문 정제(설계 §3.4). 알려진 HTML 태그만 다루고 그 밖의 꺾쇠는 보존한다."""
    if not text:
        return ""
    t = _HIDDEN_SPAN_RE.sub("", text)
    t = _IMG_RE.sub(lambda m: f"[이미지 생략: {(_IMG_ALT_RE.search(m.group(1)) or [None, ''])[1]}]"
                    if _IMG_ALT_RE.search(m.group(1)) else "[이미지 생략]", t)
    t = _IMG_CLOSE_RE.sub("", t)
    # 각주 뒤에 소항목이 같은 줄에 붙는 경우(eiac 실측 `…하였다.<각주>1</각주>다. 이에`) — 개행을 넣어야
    # 업로더의 소제목 인식이 `다.` 줄머리를 본다.
    t = _FOOTNOTE_BREAK_RE.sub(lambda m: f"[각주 {m.group(1)}]\n", t)
    t = _FOOTNOTE_RE.sub(lambda m: f"[각주 {m.group(1)}]", t)
    t = _BLOCK_TAG_RE.sub("\n", t)
    t = _INLINE_TAG_RE.sub("", t)
    t = html.unescape(t)
    t = t.replace("\xa0", " ").replace("　", " ")
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def format_date(raw: str | None) -> tuple[str, int | None]:
    """'2010.8.27' → ('2010.08.27', 2010). 파싱 실패면 (원문, None) — 날짜를 모르는 결정을 낡았다고
    단정하지 않는다(설계 §3.3)."""
    raw = (raw or "").strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 8:
        y, m, d = digits[:4], digits[4:6], digits[6:]
    else:
        parts = [p for p in re.split(r"[.\-/\s]+", raw) if p]
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            return raw, None
        y, m, d = parts[0], parts[1].zfill(2), parts[2].zfill(2)
    if len(y) != 4:
        return raw, None
    try:
        _dt.date(int(y), int(m), int(d))     # 달력 유효성(2019.02.31 같은 값은 일자 미상 경로로)
    except ValueError:
        return raw, None
    return f"{y}.{m}.{d}", int(y)


def strip_ruling_prefix(title: str) -> str:
    return _RULING_PREFIX_RE.sub("", title or "").strip()


def derive_case_no(agency: str, title_raw: str) -> str:
    """`사건번호`가 빈 상세의 폴백 — `사건`/`사건명`의 선행 `YYYY재결 제N호`에서 그 기관 표기로 만든다."""
    m = re.match(r"^\s*(\d{4})\s*재결\s*제\s*(\d+)\s*호", title_raw or "")
    if not m:
        return ""
    return f"{m.group(1)}-{int(m.group(2))}호" if agency == "iaciac" else f"{m.group(1)}재결 제{int(m.group(2))}호"


def case_no_ascii(case_no: str) -> str:
    """파일명용. `2019재결 제117호` → `2019jg117`, `2010-2071호` → `2010-2071`. ID에는 쓰지 않는다."""
    s = unicodedata.normalize("NFC", case_no or "")
    m = re.match(r"^\s*(\d{4})\s*재결\s*제?\s*(\d+)\s*호", s)
    if m:
        return f"{m.group(1)}jg{int(m.group(2))}"
    m = re.match(r"^\s*(\d{4})\s*-\s*(\d+)\s*호?", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2))}"
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_") or "unknown"


def official_url(agency: str, serial: str) -> str:
    """판례(`fetch_court_precedents.normalize_record`)와 같은 DRF 규약, OC 빈값(D17)."""
    return f"https://www.law.go.kr/DRF/lawService.do?OC=&target={agency}&ID={serial}&type=HTML"


# ── HTTP ─────────────────────────────────────────────────────────────────────

_session = requests.Session()
_last_error: str | None = None   # 직전 _get_xml 실패 사유(클래스명+상태) — 진행 기록의 reason에 쓴다


def _get_xml(url: str, params: dict) -> ET.Element | None:
    """재시도 포함 GET → XML 루트. 실패 시 None. 인증 오류는 LawApiAuthError로 올린다(재시도 없음)."""
    global _last_error
    _last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = _session.get(url, params=params, timeout=TIMEOUT)
            resp.raise_for_status()
            root = safe_xml.fromstring(resp.content)
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                _last_error = _exc_label(e)
                print(f"    [실패] {_last_error}")
                return None
            time.sleep(2 ** attempt)
            continue
        _raise_if_error_root(root)
        return root
    return None


def _exc_label(exc: Exception) -> str:
    """클래스명 + HTTP 상태만 — requests 메시지는 쿼리 URL(OC 포함)을 담는다."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return f"{type(exc).__name__}{' ' + str(status) if status else ''}"


# ── 목록·상세 ─────────────────────────────────────────────────────────────────

def _text(el: ET.Element | None) -> str:
    return "".join(el.itertext()).strip() if el is not None else ""


class ListFetchError(RuntimeError):
    """목록 페이지 조회가 재시도 뒤에도 실패했다 — 부분 목록으로 '수집 완료'처럼 끝나지 않게 main이 exit 1로 올린다(PR #157 CodeRabbit)."""


def fetch_list(agency: str, api_key: str) -> tuple[list[dict], int]:
    """목록 전량 → ([{serial, case_no, title_raw, decided_at_raw}], totalCnt). 일련번호로 중복 제거.
    어느 페이지든 조회 실패면 ListFetchError — 첫 페이지 실패는 totalCnt 0, 뒤 페이지 실패는 '건수 불일치' 경고만
    남기고 exit 0으로 끝났다(종료 코드로 완료를 판단하는 자동화가 성공으로 읽는다)."""
    items: dict[str, dict] = {}
    total = 0
    page = 1
    while True:
        root = _get_xml(LAW_SEARCH_URL, {
            "OC": api_key, "target": agency, "type": "XML",
            "display": str(PAGE_SIZE), "page": str(page),
        })
        if root is None:
            raise ListFetchError(f"{agency} 목록 page={page} ({_last_error})")
        total = int(root.findtext("totalCnt") or total or 0)
        spec = AGENCIES[agency]
        got = 0
        for el in root.iter(agency):
            serial = _text(el.find("결정문일련번호"))
            if not serial:
                continue
            got += 1
            items.setdefault(serial, {
                "serial": serial,
                "case_no": _text(el.find("사건번호")),
                "title_raw": _text(el.find(spec["title_field"])),
                "decided_at_raw": _text(el.find("의결일자")),
            })
        if got == 0 or page * PAGE_SIZE >= total:
            break
        page += 1
        time.sleep(REQUEST_DELAY)
    return list(items.values()), total


def fetch_detail(agency: str, serial: str, api_key: str) -> ET.Element | None:
    return _get_xml(LAW_SERVICE_URL, {"OC": api_key, "target": agency, "ID": str(serial), "type": "XML"})


def parse_footnotes(root: ET.Element) -> list[str]:
    """`각주목록`의 `각주번호`·`각주내용` 쌍 → `[각주 n] 내용`(D16). itertext로 이으면 번호와 내용이 줄로 섞인다."""
    fn = root.find("각주목록")
    if fn is None:
        return []
    out, number = [], None
    for child in fn:
        if child.tag == "각주번호":
            number = _text(child)
        elif child.tag == "각주내용":
            body = clean_ruling_text(_text(child))
            if body:
                out.append(f"[각주 {number}] {body}" if number else body)
            number = None
    return out


def normalize_record(root: ET.Element, agency: str, serial: str) -> dict:
    """상세 XML → 공통 dict(설계 §3.3). 필수 필드가 비면 MissingField."""
    spec = AGENCIES[agency]

    def f(name: str) -> str:
        return clean_ruling_text(_text(root.find(name)))

    got_serial = _text(root.find("결정문일련번호"))
    if got_serial and got_serial != str(serial):
        raise SerialMismatch(f"일련번호 불일치: 응답 {got_serial}")

    case_no = unicodedata.normalize("NFC", _text(root.find("사건번호")))
    if not case_no:
        # iaciac 13063(실측): 사건번호가 비고 `사건`에만 `2012재결 제3198호 …`가 있다 → 그 기관 표기(`YYYY-N호`)로 만든다
        case_no = derive_case_no(agency, _text(root.find(spec["title_field"])))
    if not case_no:
        raise MissingField("필수 필드 없음: 사건번호")
    if not _text(root.find("이유")):
        raise MissingField("필수 필드 없음: 이유")

    case_name = unicodedata.normalize("NFC", strip_ruling_prefix(f(spec["title_field"])))
    agency_name = _text(root.find("기관명")) or spec["name"]
    decided_at, decided_year = format_date(_text(root.find("의결일자")))
    if decided_year is None:
        # 의결일자가 깨졌거나(실측 iaciac 6427 `202.0.0`) 없는 건(13063 — 필드 자체가 없다). 재결 번호의 연도는 **접수
        # 연도**라 의결 연도로 쓰면 안 된다 — 1,050건 실측에서 143건(13.6%)이 다음 해에 의결됐다(CodeRabbit #155).
        # 의결 연도는 미상으로 두고(--exclude-before가 제외하지 않는다) 머리글에는 접수 연도만 참고로 적는다.
        year = re.match(r"^\s*(\d{4})", case_no)
        if not year:
            raise MissingField("필수 필드 없음: 의결일자")
        decided_at = f"미상({year.group(1)}년 접수)"
    category = " > ".join(v for v in (f(n) for n in spec["category_fields"]) if v)
    return {
        "agency": agency,
        "agency_name": agency_name,
        "serial": str(serial),
        "case_no": case_no,
        "case_name": case_name,
        "title": f"{agency_name} {case_no} — {case_name}"[:200],
        "decided_at": decided_at,
        "decided_year": decided_year,
        "category": category,
        "doc_kind": f(spec["kind_field"]),
        "summary": f(spec["summary_field"]),
        "summary_label": spec["summary_label"],
        "respondent": f(spec["respondent_field"]),
        "claimant": f("청구인"),
        "disposition": f("주문"),
        "claim": f("청구취지"),
        "reasoning": f("이유"),
        "footnotes": parse_footnotes(root),
        "official_url": official_url(agency, str(serial)),
    }


# ── PII ──────────────────────────────────────────────────────────────────────

def scan_pii(rec: dict) -> list[dict]:
    """전 필드(청구인 포함)에서 PII 패턴 적중 → [{field, pattern, snippet}]."""
    found = []
    fields = {k: v for k, v in rec.items() if isinstance(v, str) and k != "path"}
    fn = rec.get("footnotes") or []
    fields["footnotes"] = fn if isinstance(fn, str) else "\n".join(fn)
    for field, value in fields.items():
        for name, pat in PII_PATTERNS.items():
            for m in pat.finditer(value):
                found.append({"field": field, "pattern": name,
                              "snippet": value[max(0, m.start() - 20):m.end() + 20]})
    return found


# ── 마크다운 ──────────────────────────────────────────────────────────────────

def to_markdown(rec: dict) -> str:
    """court 업로더의 parse_meta·parse_sections가 그대로 읽는 형식(설계 §3.6)."""
    url = rec["official_url"]
    lines = [
        f"# {rec['case_name'] or rec['case_no']}",
        "",
        "| 항목 | 내용 |",
        "| --- | --- |",
        f"| 기관 | {rec['agency_name']} |",
        f"| agency | {rec['agency']} |",
        f"| 일련번호 | {rec['serial']} |",
        f"| 사건번호 | {rec['case_no']} |",
        f"| 의결일자 | {rec['decided_at']} |",
        f"| 분류 | {rec['category']} |",
        f"| 문서종류 | {rec['doc_kind']} |",
        f"| 피청구인 | {rec['respondent']} |",
        f"| 청구인 | {rec['claimant']} |",
        f"| 원문 | [{url}]({url}) |",
        "",
        "---",
        "",
    ]
    for heading, key in ((rec["summary_label"], "summary"), ("주문", "disposition"),
                         ("청구취지", "claim"), ("이유", "reasoning")):
        if rec.get(key):
            lines += [f"## {heading}", "", rec[key], ""]
    if rec.get("footnotes"):
        lines += ["## 각주", "", "\n".join(rec["footnotes"]), ""]
    return "\n".join(lines).rstrip() + "\n"


def output_path(rec: dict) -> str:
    return os.path.join(OUTPUT_DIR, rec["agency"], f"{rec['serial']}_{case_no_ascii(rec['case_no'])}.md")


# ── 진행 기록 ─────────────────────────────────────────────────────────────────

def _empty_progress() -> dict:
    return {a: {"fetched": {}, "failed": {}} for a in AGENCIES}


def load_progress() -> dict:
    if os.path.exists(PROGRESS_FILE) and os.path.getsize(PROGRESS_FILE) > 0:
        with open(PROGRESS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        for a in AGENCIES:
            data.setdefault(a, {"fetched": {}, "failed": {}})
        return data
    return _empty_progress()


def save_progress(progress: dict) -> None:
    atomic_write_json(PROGRESS_FILE, progress)


def _append_pii_report(entries: list[dict]) -> None:
    existing = []
    if os.path.exists(PII_REPORT_FILE) and os.path.getsize(PII_REPORT_FILE) > 0:
        with open(PII_REPORT_FILE, encoding="utf-8") as f:
            existing = json.load(f)
    seen = {(e["agency"], e["serial"], e["field"], e["pattern"], e["snippet"]) for e in existing}
    for e in entries:
        key = (e["agency"], e["serial"], e["field"], e["pattern"], e["snippet"])
        if key not in seen:
            existing.append(e)
            seen.add(key)
    atomic_write_json(PII_REPORT_FILE, existing)


def _now() -> str:
    return _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=9))).isoformat(timespec="seconds")


# ── main ─────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="법제처 재결례 수집(eiac·iaciac)")
    parser.add_argument("--agency", choices=("eiac", "iaciac", "all"), default="all")
    parser.add_argument("--limit", type=int, help="기관별 상세 수집 상한")
    parser.add_argument("--list-only", action="store_true", help="목록만 받아 집계(저장 없음)")
    parser.add_argument("--serial", action="append", help="특정 일련번호만 재수집(--agency 필수)")
    parser.add_argument("--force", action="store_true", help="진행 기록 무시")
    args = parser.parse_args(argv)

    api_key = os.getenv("LAW_API_KEY", "").strip()
    if not api_key:
        print("[오류] LAW_API_KEY가 없습니다.")
        return 1
    if args.serial and args.agency == "all":
        print("[오류] --serial에는 --agency를 함께 지정하세요.")
        return 1

    agencies = list(AGENCIES) if args.agency == "all" else [args.agency]
    progress = _empty_progress() if args.force else load_progress()
    summary: dict[str, dict] = {}
    list_failed: list[str] = []
    try:
        for agency in agencies:
            spec = AGENCIES[agency]
            print(f"\n[{agency}] {spec['name']} — 목록 조회")
            if args.serial:
                items, total = [{"serial": s} for s in args.serial], len(args.serial)
            else:
                try:
                    items, total = fetch_list(agency, api_key)
                except ListFetchError as e:
                    print(f"  [실패] 목록 조회 실패 — {e}(수집 완료가 아니다)")
                    list_failed.append(agency)
                    summary[agency] = {"error": "list_fetch", "detail": str(e)}
                    continue
            years: dict[str, int] = {}
            for it in items:
                y = (it.get("decided_at_raw") or "")[:4]
                years[y] = years.get(y, 0) + 1
            print(f"  totalCnt={total} 수집 목록={len(items)}"
                  + (f"  ⚠️ 건수 불일치" if total and len(items) != total else "")
                  + f"  연도={dict(sorted(years.items()))}")
            if not items:
                # 첫 페이지 조회 실패·응답 형식 변경이면 totalCnt도 0이라 '건수 불일치' 경고가 뜨지 않는다 —
                # 0건 요약 뒤 exit 0은 수집 완료로 읽힌다(Check B-4). 재개 실행이라 피해는 없지만 종료 코드로 알린다.
                print(f"  [실패] 목록 0건 — 조회 실패 또는 응답 형식 변경(수집 완료가 아니다)")
                list_failed.append(agency)
                summary[agency] = {"total": total, "listed": 0, "error": "empty_list"}
                continue
            if args.list_only:
                summary[agency] = {"total": total, "listed": len(items)}
                continue

            stats = {"saved": 0, "skipped": 0, "failed": 0, "missing": 0, "pii": 0, "date_fail": 0}
            fetched = progress[agency]["fetched"]
            failed = progress[agency]["failed"]
            # failed에 있는 번호는 fetched에 있어도(--serial 재수집 실패) 다시 시도한다(CodeRabbit #155)
            todo = [it for it in items if args.force or args.serial or it["serial"] not in fetched
                    or it["serial"] in failed]
            if args.limit:
                todo = todo[:args.limit]
            stats["skipped"] = len(items) - len(todo)
            for n, it in enumerate(todo, 1):
                serial = str(it["serial"])
                time.sleep(REQUEST_DELAY)
                root = fetch_detail(agency, serial, api_key)
                if root is None:
                    failed[serial] = {"reason": f"상세 조회 실패: {_last_error or '알 수 없음'}", "at": _now()}
                    stats["failed"] += 1
                    save_progress(progress)
                    continue
                try:
                    rec = normalize_record(root, agency, serial)
                except (MissingField, SerialMismatch) as e:
                    failed[serial] = {"reason": str(e), "at": _now()}
                    stats["missing"] += 1
                    save_progress(progress)
                    continue
                if rec["decided_year"] is None:
                    stats["date_fail"] += 1
                pii = scan_pii(rec)
                if pii:
                    stats["pii"] += len(pii)
                    _append_pii_report([{"agency": agency, "serial": serial, "reviewed": False, **p}
                                        for p in pii])
                path = output_path(rec)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(to_markdown(rec))
                # 같은 일련번호의 이전 파일(사건번호가 바뀌어 이름이 다른 것)은 지운다 — 남으면 업로더가 둘을 다 읽는다
                for old in os.listdir(os.path.dirname(path)):
                    if old.startswith(f"{serial}_") and old.endswith(".md") and old != os.path.basename(path):
                        os.remove(os.path.join(os.path.dirname(path), old))
                fetched[serial] = os.path.basename(path)
                failed.pop(serial, None)
                stats["saved"] += 1
                if n % 25 == 0 or n == len(todo):
                    print(f"  {n}/{len(todo)} 저장 {stats['saved']} · 실패 {stats['failed']} · "
                          f"필드부재 {stats['missing']} · PII {stats['pii']}")
                    save_progress(progress)
            save_progress(progress)
            summary[agency] = {"total": total, **stats}
    except LawApiAuthError as e:
        # 인증 오류 — failed에 적지 않고 멈춘다(설계 §3.2). 지금까지의 진행은 이미 저장돼 있다.
        save_progress(progress)
        print(f"\n[중단] 법제처 인증 오류({type(e).__name__}) — 등록 IP에서 실행 중인지 확인하세요.")
        return 2

    print("\n요약:", json.dumps(summary, ensure_ascii=False))
    if not args.list_only:
        print(f"진행 기록: {PROGRESS_FILE}\nPII 보고: {PII_REPORT_FILE} (업로드 전 reviewed 표시 필요)")
    if list_failed:
        print(f"[실패] 목록 조회 실패·0건 기관: {list_failed}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
