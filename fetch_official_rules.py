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
    # 2027년 고시는 **일부러 뺐다**. 발령(2026-08-05)은 됐으나 시행 전이라 law.go.kr 의
    # 정식 페이지(`/행정규칙/{명}`)가 아직 오류페이지다(실측 2026-09-18). 승인 저장소는
    # 미래 시행일을 지원하지만 official_url 을 확인할 수 없어 근거로 올릴 수 없다 —
    # 시행이 가까워지면 이 줄을 되살려 다시 수집할 것.
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


HEADER_FIELDS = ("doc_id", "source_type", "title", "official_url", "issuer", "date", "keys")


def write_doc(path: str, header: dict, body: str) -> None:
    lines = [f"# {header['title']}", ""]
    for field in HEADER_FIELDS:
        value = header[field]
        lines.append(f"- {field}: {', '.join(value) if isinstance(value, list) else value}")
    lines += ["", "## 본문", "", body.strip(), ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="조회만 하고 파일을 쓰지 않는다")
    parser.add_argument("--only", help="이 기준 키에 관련된 문서만 수집")
    parser.add_argument("--skip-url-check", action="store_true",
                        help="official_url 확인 생략(오프라인 점검용 — 운영 수집에는 쓰지 말 것)")
    args = parser.parse_args(argv)

    from dotenv import load_dotenv
    load_dotenv(override=True)
    api_key = os.getenv("LAW_API_KEY")
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
        try:
            doc = fetch_admrul(api_key, query, exact, dept)
        except Exception as exc:
            doc = None
            print(f"  ✗ {exact}: {type(exc).__name__}")
        if not doc or not doc["body"]:
            failed.append((doc_id, exact, "고시 조회 실패/미수록"))
            print(f"  ✗ {exact}")
            continue
        url = admrul_url(exact)
        if not args.skip_url_check and not url_resolves(url):
            failed.append((doc_id, exact, f"official_url 미확인: {url}"))
            print(f"  ✗ {exact}: official_url 이 열리지 않음")
            continue
        header = {"doc_id": doc_id, "source_type": "regulation",
                  "title": f"{exact} ({dept})", "official_url": url,
                  "issuer": f"{dept} / 법제처 국가법령정보센터",
                  "date": doc["effective"] or doc["issued"] or today, "keys": keys}
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
