#!/usr/bin/env python3
"""
법제처 Open API로 판례·헌재결정 원문을 수집해 마크다운으로 저장.

입력: output_노동법교재/누락_판례목록.csv (사건번호, 법원, 날짜, 인용횟수)
출력: output_판례_보강/{사건번호}_{사건명}.md

설계: docs/02-design/features/precedent-corpus-expansion.design.md

사용법:
  python3 fetch_court_precedents.py               # 전체 수집 (재개 지원)
  python3 fetch_court_precedents.py --limit 20    # 앞 20건만
  python3 fetch_court_precedents.py --dry-run     # 조회만, 파일 미저장
  python3 fetch_court_precedents.py --force       # 진행상황 무시하고 재수집
"""

from __future__ import annotations

import os
import re
import csv
import sys
import time
import html
import json
import argparse
import unicodedata
import xml.etree.ElementTree as ET

import requests
from dotenv import load_dotenv

from vector_ledger import atomic_write_json

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
            override=True)

# ── 설정 ──────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_CSV = os.path.join(BASE_DIR, "output_노동법교재", "누락_판례목록.csv")
OUTPUT_DIR = os.path.join(BASE_DIR, "output_판례_보강")
PROGRESS_FILE = os.path.join(OUTPUT_DIR, "_progress.json")
NOT_FOUND_CSV = os.path.join(OUTPUT_DIR, "_미발견.csv")

# 중복 대조 대상 — 기존 판례 코퍼스
EXISTING_DIRS = [
    os.path.join(BASE_DIR, "output_법원 노동판례"),
    OUTPUT_DIR,
]

# https 필수 — OC 파라미터에 API 키가 실리므로 평문 전송 금지 (legal_api.py와 동일)
LAW_SEARCH_URL = "https://www.law.go.kr/DRF/lawSearch.do"
LAW_SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do"

REQUEST_DELAY = 0.3     # 초 — 법제처 레이트 리밋이 문서화되어 있지 않아 보수적으로
MAX_RETRIES = 3
TIMEOUT = 20

# 검색이 사건명 fuzzy 매칭이라 요청한 사건이 수백 건 뒤에 밀릴 수 있다.
SEARCH_PAGE_SIZE = 100  # API 상한
SEARCH_MAX_PAGES = 3    # 300건까지 훑고 포기

# 교재 OCR이 "다"를 "대"로 오인식한 건들. 사례가 한정적이라 범용 보정 대신 명시 치환.
OCR_FIXES = {
    "2000대8127": "2000다8127",
    "2006대381": "2006다381",
    "2021대69": "2021다69",
    "2020도다296321": "2020다296321",
}

# 사건번호 추출 — 2자리 연도(90누9421)와 복합 부호(다카/헌바)를 모두 포함해야 한다.
CASE_NO_RE = re.compile(r"(\d{2,4}[가-힣]{1,4}\d+)")


# ── 텍스트 유틸 ───────────────────────────────────────────────────────────────

def clean_api_text(text: str | None) -> str:
    """법제처 XML 텍스트 정규화.

    prec는 개행을 <br/> 태그로, detc는 실제 개행으로 준다 — 둘 다 흡수한다.
    """
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = html.unescape(text)
    text = text.replace("\xa0", " ").replace("　", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_case_no(case_no: str) -> str:
    """비교용 정규화 — NFC 통일 + 공백 제거.

    macOS 파일명은 NFD로 저장되므로 NFC 정규화가 없으면 '다'(U+B2E4)와
    'ᄃ+ᅡ'(U+1103 U+1161)가 다른 문자로 취급돼 매칭이 조용히 실패한다.
    """
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", case_no or ""))


def format_date(raw: str) -> str:
    """'20190314' 또는 '2019.03.14' → '2019.03.14'"""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 8:
        return f"{digits[:4]}.{digits[4:6]}.{digits[6:]}"
    return (raw or "").strip()


def safe_filename(case_no: str, case_name: str) -> str:
    """{사건번호}_{사건명 60자}.md — 사건번호가 맨 앞이어야 파일명 대조가 동작."""
    name = unicodedata.normalize("NFC", case_name or "").strip()
    name = re.sub(r"[/\\:*?\"<>|\n\r\t]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()[:60]
    case = normalize_case_no(case_no)
    return f"{case}_{name}.md" if name else f"{case}.md"


# ── HTTP ─────────────────────────────────────────────────────────────────────

_session = requests.Session()


def _get_xml(url: str, params: dict) -> ET.Element | None:
    """재시도 포함 GET → XML 루트. 실패 시 None."""
    for attempt in range(MAX_RETRIES):
        try:
            resp = _session.get(url, params=params, timeout=TIMEOUT)
            resp.raise_for_status()
            return ET.fromstring(resp.content)
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                print(f"    [실패] {e}")
                return None
            time.sleep(2 ** attempt)
    return None


def probe_api_key(api_key: str) -> bool:
    """알려진 사건 1건으로 키 유효성 선검증.

    키가 죽어 있으면 601건을 전부 헛돌기 전에 멈춘다.
    """
    root = _get_xml(LAW_SEARCH_URL, {
        "OC": api_key, "target": "prec", "type": "XML",
        "query": "2016다255941", "display": "3",
    })
    if root is None:
        return False
    for el in root.iter("prec"):
        if normalize_case_no(el.findtext("사건번호") or "") == "2016다255941":
            return True
    return False


# ── 검색 (정확일치 게이트) ────────────────────────────────────────────────────

def resolve_target(case_no: str, court: str) -> str:
    """조회 대상 API 결정.

    CSV의 법원 컬럼만 믿으면 안 된다 — 교재 인용 추출 과정에서 법원이 잘못
    붙는 경우가 있어 헌재 사건('2005헌바20')이 대법원으로 분류돼 prec로
    조회되면 영영 못 찾는다. 사건부호가 더 신뢰할 수 있는 신호다.
    """
    if "헌" in unicodedata.normalize("NFC", case_no):
        return "detc"
    return "detc" if court.strip() == "헌법재판소" else "prec"


def search_case(case_no: str, target: str, api_key: str) -> dict | None:
    """사건번호로 검색 후 <사건번호> 정확일치만 채택.

    법제처 검색은 사건명 기준 fuzzy 매칭이라 무관한 판례를 반환한다
    (실측: '90누9421' 조회 시 2023두57876 등 6건). 정확일치 게이트가 없으면
    엉뚱한 판례가 코퍼스를 오염시킨다.

    fuzzy 매칭 탓에 결과가 수백 건까지 나오고 정작 요청한 사건이 뒤쪽에
    밀리므로(실측: '82다카90' totalCnt=279) 페이지를 넘겨가며 찾는다.
    """
    tag = "Detc" if target == "detc" else "prec"
    id_field = "헌재결정례일련번호" if target == "detc" else "판례일련번호"
    wanted = normalize_case_no(case_no)

    for page in range(1, SEARCH_MAX_PAGES + 1):
        root = _get_xml(LAW_SEARCH_URL, {
            "OC": api_key, "target": target, "type": "XML",
            "query": case_no, "display": str(SEARCH_PAGE_SIZE), "page": str(page),
        })
        if root is None:
            return None

        items = list(root.iter(tag))
        for el in items:
            if normalize_case_no(el.findtext("사건번호") or "") != wanted:
                continue
            serial = el.findtext(id_field)
            if not serial or not serial.strip().isdigit():
                continue
            return {"serial_id": int(serial.strip()), "target": target}

        try:
            total = int(root.findtext("totalCnt") or "0")
        except ValueError:
            total = 0
        if len(items) < SEARCH_PAGE_SIZE or page * SEARCH_PAGE_SIZE >= total:
            break
        time.sleep(REQUEST_DELAY)

    return None


def detail_matches(detail_case_no: str, wanted: str) -> bool:
    """상세 응답의 사건번호가 요청 사건을 포함하는지.

    병합 사건은 사건번호가 '2000다51919, 51926'처럼 온다. 엄격 일치만 보면
    실제로 맞는 판례를 버리게 된다.
    """
    # 병합 사건은 '2015다221903(본소), 2015다221910(반소)'처럼 괄호 주기가 붙는다.
    detail = re.sub(r"\([^)]*\)", "", normalize_case_no(detail_case_no))
    want = re.sub(r"\([^)]*\)", "", normalize_case_no(wanted))
    if detail == want:
        return True
    # '2000다51919,51926' → 앞 조각의 연도·부호를 뒤 번호에 붙여 비교
    parts = [p for p in detail.split(",") if p]
    if not parts:
        return False
    if want in parts:
        return True
    prefix = re.match(r"^(\d{2,4}[가-힣]{1,4})", parts[0])
    if prefix:
        expanded = {parts[0]} | {
            p if re.match(r"^\d{2,4}[가-힣]", p) else prefix.group(1) + p
            for p in parts[1:]
        }
        return want in expanded
    return False


# ── 상세 조회 + 정규화 ────────────────────────────────────────────────────────

def fetch_detail(serial_id: int, target: str, api_key: str) -> ET.Element | None:
    return _get_xml(LAW_SERVICE_URL, {
        "OC": api_key, "target": target, "ID": str(serial_id), "type": "XML",
    })


def normalize_record(root: ET.Element, target: str, serial_id: int) -> dict:
    """prec/detc의 서로 다른 XML 스키마를 공통 dict로 흡수.

    두 target은 필드명이 다르다: 판결요지↔결정요지, 판례내용↔전문,
    선고일자↔종국일자. 법원명·판결유형은 detc에 아예 없다.
    """
    def f(name: str) -> str:
        # findtext()는 자식 엘리먼트 뒤의 tail 텍스트를 버린다. 법제처는 보통
        # <br/>을 이스케이프해 보내지만, 실제 엘리먼트로 오는 경우 본문이
        # 조용히 잘리므로 itertext()로 전량 수집한다.
        el = root.find(f".//{name}")
        if el is None:
            return ""
        return clean_api_text("".join(el.itertext()))

    if target == "detc":
        court = "헌법재판소"
        date = f("종국일자")
        summary = f("결정요지")
        full_text = f("전문")
        judgment_type = f("사건종류명")
    else:
        court = f("법원명") or "대법원"
        date = f("선고일자")
        summary = f("판결요지")
        full_text = f("판례내용")
        judgment_type = f("판결유형")

    return {
        "serial_id": serial_id,
        "target": target,
        "case_no": normalize_case_no(f("사건번호")),
        "case_name": f("사건명"),
        "date": format_date(date),
        "court": court,
        "case_type": f("사건종류명"),
        "judgment_type": judgment_type,
        "issue": f("판시사항"),
        "summary": summary,
        "ref_articles": f("참조조문"),
        "ref_cases": f("참조판례"),
        "full_text": full_text,
        "source_url": (f"https://www.law.go.kr/DRF/lawService.do"
                       f"?OC=&target={target}&ID={serial_id}&type=HTML"),
    }


# ── 마크다운 생성 ─────────────────────────────────────────────────────────────

def to_markdown(rec: dict) -> str:
    """기존 판례 파일의 메타 테이블 관례를 따른다 (\\n---\\n 구분선 필수).

    헌재 문서도 헤더 라벨을 '판결요지'로 통일한다 — 다운스트림 파서를
    하나로 유지하기 위함.
    """
    lines = [
        f"# {rec['case_name'] or rec['case_no']}",
        "",
        "| 항목 | 내용 |",
        "| --- | --- |",
        f"| 분류 | {rec['case_type']} |",
        f"| 작성일 | {rec['date']} |",
        f"| 사건번호 | {rec['case_no']} |",
        f"| 법원 | {rec['court']} |",
        f"| 판결유형 | {rec['judgment_type']} |",
        f"| 원문 | [{rec['source_url']}]({rec['source_url']}) |",
        "",
        "---",
        "",
    ]
    for heading, key in (("판시사항", "issue"), ("판결요지", "summary"),
                         ("참조조문", "ref_articles"), ("참조판례", "ref_cases"),
                         ("전문", "full_text")):
        if rec.get(key):
            lines.append(f"## {heading}")
            lines.append("")
            lines.append(rec[key])
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ── 중복 대조 (L2) ────────────────────────────────────────────────────────────

def extract_representative_case_no(text: str, filename: str) -> str | None:
    """문서 1건이 '다루는' 사건번호 하나를 뽑는다.

    본문 전체를 긁으면 안 된다 — 판례 본문의 참조판례 목록에 실린 인용
    사건번호까지 잡혀서 "A가 B를 인용" 을 "B가 코퍼스에 있음" 으로 오판한다
    (실측: 836개 파일에서 819개가 아니라 2,450개가 잡혀 수집 대상 601건 중
    133건이 부당 스킵됐다).

    우선순위: 메타 테이블 → 파일명 → 본문 앞부분.
    """
    case_no, _src = extract_representative_case_no_with_src(text, filename)
    return case_no


def extract_representative_case_no_with_src(
        text: str, filename: str) -> tuple[str | None, str | None]:
    """extract_representative_case_no + 채택 경로(meta/filename/body_head).

    어느 분기가 채택됐는지는 이 함수만 안다 — 호출부가 값 대조로 역추적하면
    우선순위 변경 시 라벨이 조용히 오표기된다(archive_precedents의 case_src가
    소비자, simplify 리뷰 F5).
    """
    meta = re.search(r"\|\s*사건번호\s*\|\s*([^|]+?)\s*\|", text)
    if meta:
        m = CASE_NO_RE.search(meta.group(1))
        if m:
            return m.group(1), "meta"

    m = CASE_NO_RE.search(unicodedata.normalize("NFC", filename))
    if m:
        return m.group(1), "filename"

    m = CASE_NO_RE.search(text[:1500])
    return (m.group(1), "body_head") if m else (None, None)


def resolve_existing(cases_mode: bool) -> set[str]:
    """L2 중복검사에 쓸 기존 사건번호 집합.

    --cases(명시 대상 재수집 모드)에서는 있는 걸 알고 재수집하는 것이므로
    L2를 통째로 생략한다 — 빈 집합이면 어떤 사건도 중복으로 스킵되지 않는다.
    재개(_progress.json)는 별도 경로라 중복 API 호출은 그대로 방지된다.
    """
    if cases_mode:
        return set()
    return collect_existing_case_numbers(EXISTING_DIRS)


def collect_existing_case_numbers(dirs: list[str]) -> set[str]:
    """기존 코퍼스에서 '수록된' 사건번호 집합.

    파일명만 보면 안 된다 — 기존 nodong.kr 크롤 파일은 파일명이 사건번호가
    아니라 게시글 ID인 경우가 많다. 파일당 대표 1건씩 추출한다.
    """
    seen: set[str] = set()
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for root, _, files in os.walk(d):
            for fn in files:
                if fn.startswith("_") or not fn.endswith(".md"):
                    continue
                try:
                    with open(os.path.join(root, fn), encoding="utf-8") as f:
                        text = unicodedata.normalize("NFC", f.read())
                except Exception:
                    continue
                case_no = extract_representative_case_no(text, fn)
                if case_no:
                    seen.add(case_no)
    return seen


# ── 진행상황 ──────────────────────────────────────────────────────────────────

def load_progress() -> dict:
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"fetched": {}, "not_found": {}}


def save_progress(progress: dict) -> None:
    """재개 상태를 원자적으로 저장한다.

    수집 루프가 건건이 호출하므로 중단 확률이 높은 지점이다. 직접 쓰기는
    truncate 직후 죽으면 빈 파일을 남기고, `load_progress()`가 그것을 '최초
    실행'으로 읽어 **수백 건의 수집 이력을 통째로 잃는다**(외부감사 M8).
    법제처 API가 실제로 전면 장애를 낸 적이 있어(2026-08-22) 중단은 가정이
    아니라 겪은 일이다.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    atomic_write_json(PROGRESS_FILE, progress, indent=2)


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="법제처 판례 수집")
    parser.add_argument("--limit", type=int, help="처리할 최대 건수")
    parser.add_argument("--dry-run", action="store_true", help="조회만, 파일 미저장")
    parser.add_argument("--force", action="store_true", help="진행상황 무시하고 재수집")
    parser.add_argument("--cases", metavar="CSV",
                        help="명시 대상 CSV(사건번호,법원[,추가컬럼 무시]). "
                             "기존 코퍼스 중복검사(L2)를 생략한다 — 이미 있는 걸 "
                             "알고 재수집하는 모드(예: 겹침분 laborlaw-v2 통일)")
    parser.add_argument("--input", metavar="CSV",
                        help=f"입력 CSV 경로 (기본: {os.path.relpath(INPUT_CSV, BASE_DIR)}). "
                             "L2 중복검사는 유지된다 — 신규 수집용. "
                             "--cases와 달리 이미 보유한 판례를 다시 받지 않는다")
    args = parser.parse_args()

    api_key = os.getenv("LAW_API_KEY")
    if not api_key:
        sys.exit("[오류] LAW_API_KEY가 설정되지 않았습니다.")
    # --cases(L2 생략)와 --input(L2 유지)은 의미가 다르다. 동시에 오면
    # 중복검사를 끄는 --cases가 이긴다(기존 동작 보존).
    input_csv = args.cases or args.input or INPUT_CSV
    if not os.path.exists(input_csv):
        sys.exit(f"[오류] 입력 CSV가 없습니다: {input_csv}")

    print("API 키 검증 중...", end=" ", flush=True)
    if not probe_api_key(api_key):
        sys.exit("실패\n[오류] LAW_API_KEY로 판례를 조회할 수 없습니다. 키 등록 상태를 확인하세요.")
    print("정상")

    with open(input_csv, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    progress = {"fetched": {}, "not_found": {}} if args.force else load_progress()
    existing = resolve_existing(cases_mode=bool(args.cases))

    print(f"\n{'=' * 62}")
    print(f"법제처 판례 수집 {'(DRY RUN)' if args.dry_run else ''}"
          f"{'  [명시 대상 모드]' if args.cases else ''}")
    print(f"입력: {input_csv}")
    print(f"대상: {len(rows)}건  |  기존 코퍼스 사건번호: "
          f"{'L2 생략' if args.cases else f'{len(existing)}개'}")
    print(f"이미 수집됨: {len(progress['fetched'])}건  |  기존 미발견: {len(progress['not_found'])}건")
    print(f"{'=' * 62}\n")

    if not args.dry_run:
        os.makedirs(OUTPUT_DIR, exist_ok=True)

    stats = {"saved": 0, "skip_dup": 0, "skip_done": 0, "not_found": 0}
    processed = 0

    for row in rows:
        if args.limit and processed >= args.limit:
            break

        raw_no = row["사건번호"].strip()
        case_no = OCR_FIXES.get(raw_no, raw_no)
        case_no = normalize_case_no(case_no)

        if case_no in progress["fetched"] or case_no in progress["not_found"]:
            stats["skip_done"] += 1
            continue
        if case_no in existing:
            stats["skip_dup"] += 1
            continue

        processed += 1
        target = resolve_target(case_no, row["법원"])

        hit = search_case(case_no, target, api_key)
        time.sleep(REQUEST_DELAY)

        if not hit:
            stats["not_found"] += 1
            progress["not_found"][case_no] = "검색 정확일치 없음"
            print(f"  [{processed}] {case_no} ({row['법원']}) — 미발견")
            continue

        root = fetch_detail(hit["serial_id"], target, api_key)
        time.sleep(REQUEST_DELAY)

        if root is None:
            stats["not_found"] += 1
            progress["not_found"][case_no] = "상세 조회 실패"
            print(f"  [{processed}] {case_no} — 상세 조회 실패")
            continue

        rec = normalize_record(root, target, hit["serial_id"])
        if not detail_matches(rec["case_no"], case_no):
            # 상세 응답이 다른 사건이면 채택하지 않는다.
            stats["not_found"] += 1
            progress["not_found"][case_no] = f"상세 사건번호 불일치({rec['case_no']})"
            print(f"  [{processed}] {case_no} — 상세 불일치")
            continue
        # 병합 사건(2000다51919, 51926)은 요청한 번호로 파일명을 고정한다.
        rec["case_no"] = case_no

        filename = safe_filename(rec["case_no"], rec["case_name"])
        if not args.dry_run:
            with open(os.path.join(OUTPUT_DIR, filename), "w", encoding="utf-8") as f:
                f.write(to_markdown(rec))

        progress["fetched"][case_no] = filename
        existing.add(case_no)
        stats["saved"] += 1
        print(f"  [{processed}] {case_no} → {rec['case_name'][:40]} "
              f"(요지 {len(rec['summary'])}자, 전문 {len(rec['full_text'])}자)")

        if not args.dry_run and stats["saved"] % 25 == 0:
            save_progress(progress)

    if not args.dry_run:
        save_progress(progress)
        if progress["not_found"]:
            with open(NOT_FOUND_CSV, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["사건번호", "사유"])
                for c, reason in sorted(progress["not_found"].items()):
                    w.writerow([c, reason])

    print(f"\n{'=' * 62}")
    print(f"저장: {stats['saved']}건  |  기존 중복 스킵: {stats['skip_dup']}건")
    print(f"이미 처리됨 스킵: {stats['skip_done']}건  |  미발견: {stats['not_found']}건")
    if not args.dry_run:
        print(f"출력: {OUTPUT_DIR}")
        if progress["not_found"]:
            print(f"미발견 목록: {NOT_FOUND_CSV}")
    print(f"{'=' * 62}\n")


if __name__ == "__main__":
    main()
