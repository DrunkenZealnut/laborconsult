#!/usr/bin/env python3
"""법제처(law.go.kr)에서 **공식 원문**을 수집해 output_공식법령/ 에 저장한다.

왜 필요한가 — 승인 게이트(`app/core/legal_updates.py::official_evidence`)는 Pinecone
**메타데이터**의 `official_url` 이 공식 호스트의 https 주소일 것을 요구한다. 본문에 주소가
적혀 있어도 승인되지 않는다. 2026-09-18 실측에서 laborlaw-v2 표본 439건 중 공식 호스트
벡터가 **0건**이었고(훈령·예규·행정해석은 전부 nodong.kr 재수록, 판례는 url 자체가 없음),
그래서 관리 화면에서 무엇을 눌러도 승인할 수 없었다. 이 스크립트가 그 공백을 메운다.

수집 대상은 `wage_calculator/legal_rules.py::PARAMETERS` 11개 키의 근거가 되는 법령 조문과
고시다. **어떤 문서가 어떤 키의 확정 근거인지는 여기서 정하지 않는다** — 관리자가 승인
화면에서 원문을 대조해 정한다. `keys` 필드는 검색·검토를 돕는 힌트일 뿐이다.

    python3 fetch_official_rules.py             # 전량 수집
    python3 fetch_official_rules.py --dry-run   # 조회만, 저장 없음
    python3 fetch_official_rules.py --only minimum_hourly_wage

읽기 전용 외부 호출만 한다(법제처 조회 + URL 확인). Pinecone·Supabase 를 건드리지 않는다.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
import urllib.parse as urlparse
import xml.etree.ElementTree as ET
from datetime import date, timezone, timedelta

import requests

OUT_DIR = "output_공식법령"
SEARCH_URL = "https://www.law.go.kr/DRF/lawSearch.do"
SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do"
TIMEOUT = 20

# ── 수집 대상 ────────────────────────────────────────────────────────────────
# doc_id 는 **벡터 ID 에 그대로 들어간다**. ASCII·소문자·숫자·밑줄만 쓰고 한 번 정한 값을
# 바꾸지 말 것 — 바꾸면 기존 벡터가 고아로 남는다(원장이 정리하지만 ID 가 전부 갈린다).
ARTICLES = [
    # (doc_id, 법령명, 조, 조의N, 관련 기준 키)
    ("mw_act_5",      "최저임금법",                     5,   None, ["minimum_hourly_wage"]),
    ("ei_enf_101",    "고용보험법 시행령",               101, None, ["maternity.monthly_upper"]),
    ("ei_act_77_9",   "고용보험법",                     77,  9,    ["maternity.platform_upper"]),
    ("np_act_88",     "국민연금법",                     88,  None, ["insurance.national_pension"]),
    ("np_enf_5",      "국민연금법 시행령",               5,   None, ["insurance.pension_income_max",
                                                                   "insurance.pension_income_min"]),
    ("nhi_enf_44",    "국민건강보험법 시행령",            44,  None, ["insurance.health_insurance"]),
    ("nhi_enf_32",    "국민건강보험법 시행령",            32,  None, ["insurance.health_premium_max",
                                                                   "insurance.health_premium_min"]),
    ("ltc_enf_4",     "노인장기요양보험법 시행령",         4,   None, ["insurance.long_term_care"]),
    ("eisi_enf_12",   "고용보험 및 산업재해보상보험의 보험료징수 등에 관한 법률 시행령",
                                                        12,  None, ["insurance.employment_insurance"]),
]

# 조문이 "고용노동부장관이 고시하는 금액"으로 **위임**하는 수치들 — 조문만으로는
# 금액을 알 수 없어 고시 원문이 반드시 필요하다.
ADMRULS = [
    # (doc_id, 검색어, 행정규칙명 정확일치, 소관부처, 관련 기준 키)
    ("mw_notice",   "최저임금",              "2026년 적용 최저임금 고시",       "고용노동부",
     ["minimum_hourly_wage"]),
    # 2027년 고시(고용노동부고시 제2026–60호, 시급 10,700원)는 **노동부 게시판에서** 받는다.
    # law.go.kr 은 시행일(2027-01-01)에야 페이지를 열어 2026-09 기준으로도 오류페이지지만,
    # 소관부처 게시판에는 발령 당일(2026-08-05)부터 올라와 있었다. 한동안 "시행 전이라
    # 수집 불가"로 미뤄 뒀던 것은 법제처만 본 탓이다 — 고시는 게시판을 먼저 볼 것.
    ("mw_notice_2027", "최저임금", "2027년 적용 최저임금 고시", "고용노동부",
     ["minimum_hourly_wage"]),
    ("np_income",   "국민연금 기준소득월액",   "국민연금 기준소득월액 하한액과 상한액", "보건복지부",
     ["insurance.pension_income_max", "insurance.pension_income_min"]),
    ("mat_upper",   "출산전후휴가 급여 상한액", "출산전후휴가 급여등 상한액 고시",   "고용노동부",
     ["maternity.monthly_upper", "maternity.platform_upper"]),
    # 국민건강보험법 시행령 제32조가 금액을 다시 고시로 위임한다 — 조문만 넣으면
    # "보건복지부장관이 정하여 고시하는 금액"에서 끝나 근거로 쓸 수 없다.
    ("nhi_cap",     "월별 보험료액의 상한과 하한", "월별 건강보험료액의 상한과 하한에 관한 고시",
     "보건복지부", ["insurance.health_premium_max", "insurance.health_premium_min"]),
]


def kst_today() -> str:
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    except Exception:
        return datetime.now(timezone(timedelta(hours=9))).date().isoformat()


def law_article_url(law_name: str, article_no: int, sub: int | None) -> str:
    suffix = f"제{article_no}조" + (f"의{sub}" if sub else "")
    return "https://www.law.go.kr/" + urlparse.quote(f"법령/{law_name}/{suffix}", safe="/")


def admrul_url(rule_name: str) -> str:
    return "https://www.law.go.kr/" + urlparse.quote(f"행정규칙/{rule_name}", safe="/")


def url_resolves(url: str) -> bool:
    """official_url 이 실제로 열리는지. 깨진 주소는 **없는 것보다 나쁘다** —
    게이트는 통과하면서 대조할 원문이 없어 승인자가 확인할 수단이 사라진다.

    law.go.kr 은 없는 문서에도 HTTP 200 을 준다(프레임 셸). 정상 응답은 <title>이
    문서명이고, 오류는 '오류페이지' 이거나 title 이 없다(실측 2026-09-18).
    """
    try:
        res = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
    except requests.RequestException:
        return False
    if res.status_code != 200:
        return False
    match = re.search(r"<title>(.*?)</title>", res.text, re.S)
    title = (match.group(1).strip() if match else "")
    return bool(title) and "오류" not in title and "찾을 수 없" not in title


def fetch_article_xml(api_key: str, law_name: str, article_no: int, sub: int | None) -> dict | None:
    """조문 본문. `legal_api.fetch_article` 은 캐시·서킷브레이커가 붙은 **상담용** 경로라
    배치 수집에 쓰지 않는다(L2 캐시를 수집 트래픽으로 오염시키지 않기 위함)."""
    res = requests.get(SERVICE_URL, params={"OC": api_key, "target": "law", "type": "XML",
                                            "LM": law_name}, timeout=TIMEOUT)
    res.raise_for_status()
    try:
        root = ET.fromstring(res.text)
    except ET.ParseError:
        return None
    if root.tag != "법령":                      # 미매칭·자격증명 오류도 HTTP 200 이다
        return None
    returned = (root.findtext(".//법령명_한글") or "").replace(" ", "")
    if returned and returned != law_name.replace(" ", ""):
        print(f"    ⚠️ 다른 법령이 반환됨: {returned} (요청 {law_name}) — 건너뜀")
        return None
    want = f"{article_no:04d}" + (f"{sub:02d}" if sub else "00")
    # **목(目)까지 반드시 포함한다.** 조문이 "다음 각 목과 같다"로 넘기고 실제 수치는
    # 목에 있는 경우가 흔하다 — 국민건강보험법 시행령 제32조(보험료 상·하한)를 항·호만
    # 모으면 본문 7자가 나오고 금액이 통째로 빠진다(실측). 근거로 쓸 수 없는 껍데기다.
    # 호가 항 밑에 있는 조문과 조문단위 바로 밑에 있는 조문이 섞여 있으므로 중첩을
    # 가정하지 말고 문서 순서(iter는 DFS)대로 훑는다.
    wanted_tags = {"조문내용", "항내용", "호내용", "목내용"}
    for jo in root.iter("조문단위"):
        # 편·장·절 제목도 `조문단위`이고 **뒤따르는 조문과 같은 조문번호**를 갖는다
        # (조문여부="전문"). 걸러내지 않으면 제32조 조회가 "제6장 보험료" 7자를
        # 반환하고, 그게 근거 원문으로 코퍼스에 들어간다 — 조용한 오염이다(실측).
        if (jo.findtext("조문여부") or "").strip() != "조문":
            continue
        key = (jo.findtext("조문번호") or "").zfill(4) + (jo.findtext("조문가지번호") or "0").zfill(2)
        if key != want:
            continue
        parts = [("".join(el.itertext())).strip()
                 for el in jo.iter() if el.tag in wanted_tags]
        # 수집일을 문서 날짜로 쓰면 동일 조문도 다음 날 새 근거가 된다. 법제처가
        # 제공하는 시행일을 내용 버전 날짜로 저장하고, 조회 시각은 별도 provenance가 맡는다.
        official_date = (root.findtext(".//시행일자") or
                         root.findtext(".//공포일자") or "").strip()
        return {"body": "\n".join(p for p in parts if p), "date": official_date}
    return None


def pdf_attachment_text(droot: ET.Element) -> str:
    """첨부 PDF 본문. **원문 그대로 저장한다.**

    PDF 텍스트 레이어는 한국어 낱말 사이 공백이 빠져 나오는 일이 흔하다
    (실측: "고용노동부고시제2025–47호"). 보기 좋게 공백을 넣고 싶어지지만
    **넣지 말 것** — 저장된 본문이 승인 인용구절의 대조 기준이고, 손대는 순간
    코퍼스에 원문과 다른 문자열이 남는다. 관리자는 화면에 보이는 그대로 인용한다.
    """
    for att in droot.findall(".//첨부파일"):
        link = (att.findtext("첨부파일링크") or "").strip()
        name = (att.findtext("첨부파일명") or "").strip()
        if not link or not name.lower().endswith(".pdf"):
            continue
        try:
            from pypdf import PdfReader
        except ImportError:
            try:
                from PyPDF2 import PdfReader
            except ImportError:
                print("    ⚠️ pypdf 미설치 — 첨부 PDF 본문을 읽을 수 없습니다")
                return ""
        try:
            res = requests.get(link.replace("http://", "https://", 1), timeout=40,
                               headers={"User-Agent": "Mozilla/5.0"})
            res.raise_for_status()
            if res.content[:4] != b"%PDF":
                continue
            import io
            reader = PdfReader(io.BytesIO(res.content))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
            if text.strip():
                return text.strip()
        except Exception as exc:
            print(f"    ⚠️ 첨부 PDF 추출 실패({name}): {type(exc).__name__}")
    return ""


# ── 소관부처 게시판 ─────────────────────────────────────────────────────────
# **법제처보다 먼저 본다.** law.go.kr 은 행정규칙 페이지를 *시행일*에야 열어, 발령만 된
# 고시를 통째로 놓친다 — 2027년 최저임금 고시(제2026–60호)가 2026-08-05 발령인데 2026-09
# 기준으로도 오류페이지였고, 그 탓에 "시행 전이라 수집 불가"로 넉 달을 미뤄 뒀다.
# 게시판에는 발령 당일부터 올라온다.
#
# 두 부처의 게시판은 **검색 가능 여부가 다르다**:
#   고용노동부 — 검색 파라미터(query·searchWord)가 동작하지 않는다(기본 목록을 돌려준다).
#                pageUnit=100 으로 목록을 훑는다.
#   보건복지부 — 제목 검색이 동작한다(keyField=TITLE). 게시물이 하루 수십 건이라 목록
#                훑기로는 못 찾는다(실측: 150건 안에 없음).
BOARDS = {
    "고용노동부": {
        "host": "https://www.moel.go.kr",
        "list": "https://www.moel.go.kr/info/lawinfo/instruction/list.do",
        "view": "https://www.moel.go.kr/info/lawinfo/instruction/view.do?bbs_seq={id}",
        "id_re": re.compile(r"bbs_seq=(\d+)[^>]*>\s*([^<]{3,90})"),
        "pages": 5,
        "params": lambda page, word: {"pageIndex": page, "pageUnit": 100},
        "file_re": re.compile(r"(/common/downloadFile\.do\?[^\"']+)"),
    },
    "보건복지부": {
        "host": "https://www.mohw.go.kr",
        "list": "https://www.mohw.go.kr/board.es",
        "view": "https://www.mohw.go.kr/board.es?mid=a10409020000&bid=0026&act=view&list_no={id}",
        "id_re": re.compile(r"list_no=(\d+)[^>]*>\s*([^<]{4,90})"),
        "pages": 1,
        "params": lambda page, word: {"mid": "a10409020000", "bid": "0026", "cg_code": "C03",
                                      "keyField": "TITLE", "keyWord": word, "nPage": page},
        "file_re": re.compile(r"(/boardDownload\.es\?[^\"']+)"),
    },
}
_UA = {"User-Agent": "Mozilla/5.0"}
NOTICE_NO_RE = re.compile(r"제\s*(\d{4})\s*[-\u2013\u2014]\s*(\d+)\s*호")


def _norm_title(text: str) -> str:
    """게시판 제목 정규화. `[고시]` 말머리와 「」를 떼고 공백을 접는다 —
    보건복지부는 제목이 「…」 고시 일부개정 형태라 정확일치가 성립하지 않는다."""
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^\[(고시|훈령|예규|지침|공고)\]\s*", "", text)
    return text.replace("\u300c", "").replace("\u300d", "")


def board_find(dept: str, exact_name: str) -> dict | None:
    """게시판에서 그 고시의 **가장 최근** 글을 찾는다. 첨부는 받지 않는다.

    발령번호는 view 페이지 HTML 에 있으므로(고용노동부는 첨부 파일명, 보건복지부는 본문)
    갱신 점검은 첨부 다운로드 없이 끝난다.
    """
    board = BOARDS.get(dept)
    if board is None:
        return None
    session = requests.Session()
    session.headers.update(_UA)
    for page in range(1, board["pages"] + 1):
        try:
            res = session.get(board["list"], params=board["params"](page, exact_name),
                              timeout=TIMEOUT)
            res.raise_for_status()
        except requests.RequestException:
            return None
        rows = board["id_re"].findall(res.text)
        if not rows:
            break
        for found, title in rows:              # 목록은 최신순이라 첫 일치가 최신이다
            if exact_name in _norm_title(title):
                url = board["view"].format(id=found)
                try:
                    page_res = session.get(url, timeout=TIMEOUT)
                    page_res.raise_for_status()
                except requests.RequestException:
                    return None
                number = NOTICE_NO_RE.search(page_res.text)
                posted = re.search(r"(\d{4})[-.](\d{2})[-.](\d{2})", page_res.text)
                return {"url": url, "title": _norm_title(title), "html": page_res.text,
                        "notice_no": "-".join(number.groups()) if number else "",
                        "posted": "".join(posted.groups()) if posted else "",
                        "session": session, "board": board}
    return None


def _attachment_text(raw: bytes, name: str) -> str:
    """첨부 본문 추출(PDF / HWPX). 추출 문자열을 **다듬지 않는다** — pdf_attachment_text 참조."""
    if raw[:4] == b"%PDF":
        try:
            from pypdf import PdfReader
        except ImportError:
            try:
                from PyPDF2 import PdfReader
            except ImportError:
                print("    \u26a0\ufe0f pypdf 미설치 — 첨부 PDF 본문을 읽을 수 없습니다")
                return ""
        import io
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(io.BytesIO(raw)).pages).strip()
    if raw[:2] == b"PK":            # HWPX = zip 컨테이너, 본문은 Contents/section*.xml
        import io
        import zipfile
        try:
            z = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile:
            return ""
        out = []
        for entry in sorted(n for n in z.namelist() if "section" in n and n.endswith(".xml")):
            xml = z.read(entry).decode("utf-8", "ignore")
            out.append(re.sub(r"<[^>]+>", "", xml.replace("</hp:t>", "</hp:t> ")))
        return re.sub(r"[ \t]+", " ", "\n".join(out)).strip()
    print(f"    \u26a0\ufe0f 지원하지 않는 첨부 형식: {name}")
    return ""


def fetch_board_instruction(dept: str, exact_name: str) -> dict | None:
    """소관부처 게시판에서 고시 본문까지 가져온다(첨부 PDF/HWPX 추출)."""
    hit = board_find(dept, exact_name)
    if not hit:
        return None
    session, board = hit["session"], hit["board"]
    body = ""
    for link in board["file_re"].findall(hit["html"])[:3]:
        url = board["host"] + link.replace("&amp;", "&")
        try:
            # Referer 없이 받으면 게시판이 HTML 안내문을 돌려준다(실측).
            blob = session.get(url, headers={"Referer": hit["url"]}, timeout=40)
            blob.raise_for_status()
        except requests.RequestException:
            continue
        body = _attachment_text(blob.content, exact_name)
        if body:
            break
    if not body:
        return None
    return {"name": exact_name, "body": body, "body_source": "소관부처 게시판 첨부",
            "official_url": hit["url"], "notice_no": hit["notice_no"],
            "issued": hit["posted"], "effective": ""}


def fetch_admrul(api_key: str, query: str, exact_name: str, dept: str) -> dict | None:
    res = requests.get(SEARCH_URL, params={"OC": api_key, "target": "admrul", "type": "XML",
                                           "query": query, "display": 20}, timeout=TIMEOUT)
    res.raise_for_status()
    try:
        root = ET.fromstring(res.text)
    except ET.ParseError:
        return None
    hit = None
    for item in root.findall(".//admrul"):
        name = (item.findtext("행정규칙명") or "").strip()
        # 정확일치만 채택한다 — 법제처 검색은 부분일치라 '선원 최저임금 고시' 같은
        # 다른 부처 고시가 같은 질의로 섞여 나온다(실측).
        if name == exact_name and (item.findtext("소관부처명") or "").strip() == dept:
            hit = item
            break
    if hit is None:
        return None
    rule_id = (hit.findtext("행정규칙일련번호") or "").strip()
    if not rule_id:
        return None
    detail = requests.get(SERVICE_URL, params={"OC": api_key, "target": "admrul",
                                               "type": "XML", "ID": rule_id}, timeout=TIMEOUT)
    detail.raise_for_status()
    try:
        droot = ET.fromstring(detail.text)
    except ET.ParseError:
        return None
    # `itertext()` 로 통째로 긁으면 담당자 전화번호·부칙 이력·파일링크까지 본문이 된다.
    # 근거 원문은 고시 **내용**이어야 하므로 조문내용만 취한다.
    body = "\n".join(
        " ".join(("".join(el.itertext()) or "").split())
        for el in droot.findall(".//조문내용")).strip()
    source = "조문내용"
    if not body:
        # 내용이 XML 에 없고 **첨부 PDF 에만** 있는 고시가 있다(실측: 최저임금 고시).
        # 그 경우 본문 없이 올리면 금액이 없어 인용구절 검사를 통과할 수 없고,
        # 그 키는 영영 승인 불가로 남는다.
        body = pdf_attachment_text(droot)
        source = "첨부 PDF"
    return {
        "name": exact_name,
        "kind": (hit.findtext("행정규칙종류") or "").strip(),
        "dept": dept,
        "issued": (hit.findtext("발령일자") or "").strip(),
        "effective": (droot.findtext(".//시행일자") or "").strip(),
        "body": body,
        "body_source": source,
    }


HEADER_FIELDS = ("doc_id", "source_type", "title", "official_url", "issuer", "date",
                 "notice_no", "keys")


def write_doc(path: str, header: dict, body: str) -> None:
    lines = [f"# {header['title']}", ""]
    for field in HEADER_FIELDS:
        value = header[field]
        lines.append(f"- {field}: {', '.join(value) if isinstance(value, list) else value}")
    lines += ["", "## 본문", "", body.strip(), ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def stored_notice(doc_id: str) -> dict | None:
    """수집해 둔 고시의 헤더·고시번호. 없으면 None."""
    path = os.path.join(OUT_DIR, f"{doc_id}.md")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    head, _, body = raw.partition("\n## 본문")
    meta = dict(m.groups() for m in re.finditer(r"^-\s*([A-Za-z_]+):\s*(.*)$", head, re.M))
    if not meta.get("notice_no"):
        number = NOTICE_NO_RE.search(body)
        meta["notice_no"] = "-".join(number.groups()) if number else ""
    return meta


def check_updates() -> int:
    """소관부처 게시판에 **저장본보다 새 고시**가 올라왔는지만 본다(수집·저장 없음).

    이 점검이 따로 필요한 이유: 고시는 예고 없이 개정되고 법제처 반영은 늦다. 실제로
    출산전후휴가 급여등 상한액 고시가 2026-09-17 제2026-67호로 개정돼 배우자 유산·사산휴가가
    신설됐는데, 저장본은 제2025-124호였다 — 게시판을 보지 않았으면 낡은 근거로 승인할 뻔했다.
    금액이 그대로여도 본문이 바뀌면 sha256 이 달라져 승인 근거가 무효가 되므로 재수집이 필요하다.

    **'확인 불가'를 '낡음'으로 보고하지 말 것.** 법제처 XML 본문에는 발령번호가 없어
    그 경로로 수집한 문서는 번호를 알 수 없다. 재수집하면 헤더(`notice_no`)에 기록돼
    다음부터 판정된다. 보건복지부 고시 2건이 그 상태인데, 게시판 본문은 "제1호 가목 중
    '400천원'을 '410천원'으로" 같은 **일부개정 형식**이라 인용 근거로는 법제처 통합본이
    낫다 — 번호만 헤더에 넣고 본문은 법제처에서 받는 것이 맞다(법제처 API 는 등록 IP 필요).
    """
    stale, unknown, checked = [], [], 0
    for doc_id, _query, exact, dept, _keys in ADMRULS:
        if dept not in BOARDS:
            print(f"  · {exact}: {dept} — 게시판 파서 없음, 수동 확인 필요")
            continue
        checked += 1
        stored = stored_notice(doc_id)
        board = board_find(dept, exact)          # 첨부는 받지 않는다(발령번호만 본다)
        if not board:
            print(f"  ✗ {exact}: 게시판에서 찾지 못함")
            continue
        board_no = board["notice_no"]
        if stored is None:
            stale.append((doc_id, exact, "미수집", board_no))
            print(f"  ⚠️ {exact}: 아직 수집하지 않았습니다 (게시판 {board_no or '?'})")
            continue
        mine = stored.get("notice_no") or ""
        if not mine:
            # 법제처 XML 본문에는 발령번호가 없다. 번호를 모르면 "낡았다"가 아니라
            # "확인할 수 없다"가 맞다 — 재수집하면 헤더에 번호가 남아 다음부터 판정된다.
            unknown.append((doc_id, exact, board_no or "?"))
            print(f"  ? {exact}: 저장본에 발령번호 없음 (게시판 제{board_no or '?'}호) — 확인 불가")
        elif board_no and board_no == mine:
            print(f"  ✓ {exact}: 최신 (제{board_no}호)")
        else:
            stale.append((doc_id, exact, mine, board_no or "?"))
            print(f"  ⚠️ {exact}: 저장본 제{mine}호 → 게시판 제{board_no or '?'}호 — 재수집 필요")
        time.sleep(0.2)
    print(f"\n점검 {checked}건 · 갱신 필요 {len(stale)}건 · 확인 불가 {len(unknown)}건")
    for doc_id, exact, old, new in stale:
        print(f"  - {doc_id}: {exact}  제{old}호 → 제{new}호")
    for doc_id, exact, new in unknown:
        print(f"  ? {doc_id}: {exact}  (게시판 제{new}호, 저장본 번호 미기록)")
    if stale or unknown:
        print("\n  재수집: python3 fetch_official_rules.py --only <기준키>")
        print("  이후:   python3 pinecone_upload_official_rules.py")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="조회만 하고 파일을 쓰지 않는다")
    parser.add_argument("--only", help="이 기준 키에 관련된 문서만 수집")
    parser.add_argument("--skip-url-check", action="store_true",
                        help="official_url 확인 생략(오프라인 점검용 — 운영 수집에는 쓰지 말 것)")
    parser.add_argument("--check-updates", action="store_true",
                        help="수집하지 않고, 소관부처 게시판에 저장본보다 새 고시가 올라왔는지만 확인")
    args = parser.parse_args(argv)

    from dotenv import load_dotenv
    load_dotenv(override=True)
    api_key = os.getenv("LAW_API_KEY")
    if args.check_updates:
        return check_updates()
    if not api_key:
        print("[오류] LAW_API_KEY 가 없습니다 — 법제처 조회 불가", file=sys.stderr)
        return 1

    if not args.dry_run:
        os.makedirs(OUT_DIR, exist_ok=True)
    today = kst_today()
    saved, failed = [], []

    print(f"=== 법령 조문 {len(ARTICLES)}건 ===")
    for doc_id, law, no, sub, keys in ARTICLES:
        if args.only and args.only not in keys:
            continue
        label = f"{law} 제{no}조" + (f"의{sub}" if sub else "")
        try:
            article = fetch_article_xml(api_key, law, no, sub)
        except Exception as exc:
            article = None
            print(f"  ✗ {label}: {type(exc).__name__}")
        if not article or not article["body"]:
            failed.append((doc_id, label, "조문 조회 실패"))
            print(f"  ✗ {label}")
            continue
        url = law_article_url(law, no, sub)
        if not args.skip_url_check and not url_resolves(url):
            failed.append((doc_id, label, f"official_url 미확인: {url}"))
            print(f"  ✗ {label}: official_url 이 열리지 않음")
            continue
        header = {"doc_id": doc_id, "source_type": "law", "title": label,
                  "official_url": url, "issuer": "법제처 국가법령정보센터",
                  "date": article["date"], "keys": keys}
        print(f"  ✓ {label}  ({len(article['body'])}자)")
        if not args.dry_run:
            write_doc(os.path.join(OUT_DIR, f"{doc_id}.md"), header, article["body"])
        saved.append(doc_id)
        time.sleep(0.2)

    print(f"\n=== 행정규칙(고시) {len(ADMRULS)}건 ===")
    for doc_id, query, exact, dept, keys in ADMRULS:
        if args.only and args.only not in keys:
            continue
        # ① 소관부처 게시판 우선. 법제처는 시행일에야 페이지를 열어, 발령만 된 고시를
        #    놓친다(2027년 최저임금 고시 실측). 게시판에는 발령 즉시 올라온다.
        doc, url, issuer = None, None, None
        if dept in BOARDS:
            try:
                doc = fetch_board_instruction(dept, exact)
            except Exception as exc:
                print(f"    ⚠️ {dept} 게시판 조회 실패({exact}): {type(exc).__name__}")
            if doc:
                # 본문은 게시판에서 받되, **법제처 페이지가 열리면 그 URL 을 쓴다** —
                # 행정규칙 주소가 정식 인용이고 게시판 bbs_seq 보다 안정적이다. 이미 수집한
                # 고시의 official_url 이 바뀌면 sha256 이 달라져 승인 근거가 무효가 되므로
                # 불필요한 교체를 만들지 않는 쪽이 낫다. 시행 전 고시만 게시판 주소가 남는다.
                canonical = admrul_url(exact)
                use_canonical = not args.skip_url_check and url_resolves(canonical)
                url = canonical if use_canonical else doc["official_url"]
                issuer = (f"{dept} / 법제처 국가법령정보센터" if use_canonical
                          else f"{dept} 훈령·예규·고시 게시판")
        # ② 법제처 폴백 — 타 부처 고시와, 게시판에서 못 찾은 경우.
        if not doc:
            try:
                doc = fetch_admrul(api_key, query, exact, dept)
            except Exception as exc:
                doc = None
                print(f"  ✗ {exact}: {type(exc).__name__}")
            if doc and doc["body"]:
                url = admrul_url(exact)
                issuer = f"{dept} / 법제처 국가법령정보센터"
                if not args.skip_url_check and not url_resolves(url):
                    failed.append((doc_id, exact, f"official_url 미확인: {url}"))
                    print(f"  ✗ {exact}: official_url 이 열리지 않음")
                    continue
        if not doc or not doc["body"]:
            failed.append((doc_id, exact, "고시 조회 실패/미수록"))
            print(f"  ✗ {exact}")
            continue
        # 발령번호는 **헤더에 남긴다.** 법제처 XML 본문에는 번호가 없어, 본문에서만 찾으면
        # 그 문서는 영원히 "갱신 확인 불가"로 남는다. 본문을 법제처에서 받았더라도 번호는
        # 게시판에서 가져온다(board_find 는 첨부를 받지 않아 싸다).
        notice_no = doc.get("notice_no", "")
        if not notice_no and dept in BOARDS:
            try:
                hit = board_find(dept, exact)
                notice_no = hit["notice_no"] if hit else ""
            except Exception:
                notice_no = ""
        header = {"doc_id": doc_id, "source_type": "regulation",
                  "title": f"{exact} ({dept})", "official_url": url,
                  "issuer": issuer,
                  "date": doc["effective"] or doc["issued"] or today,
                  "notice_no": notice_no, "keys": keys}
        print(f"  ✓ {exact}  ({len(doc['body'])}자 / {doc['body_source']}, "
              f"시행 {doc['effective'] or '?'})")
        if not args.dry_run:
            write_doc(os.path.join(OUT_DIR, f"{doc_id}.md"), header, doc["body"])
        saved.append(doc_id)
        time.sleep(0.2)

    print(f"\n{'(dry-run) ' if args.dry_run else ''}수집 {len(saved)}건"
          f"{'' if args.dry_run else f' → {OUT_DIR}/'}, 실패 {len(failed)}건")
    for doc_id, label, why in failed:
        print(f"  - {doc_id} / {label}: {why}")
    # 부분 실패는 1로 알린다 — 조용히 넘어가면 특정 키의 근거가 빠진 채
    # 업로드까지 진행돼 그 키만 영영 승인 불가로 남는다.
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
