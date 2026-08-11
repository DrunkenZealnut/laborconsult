#!/usr/bin/env python3
"""
판례 수집·업로드 오프라인 테스트 (API 키 불요 — CI에서 실행).

설계 §7. 이 기능은 조용히 틀리는 실패 모드가 셋이라 회귀를 코드로 고정한다:
  1. 검색 오매칭 — 법제처가 사건명 fuzzy 매칭으로 무관한 판례를 반환
  2. 벡터 ID 충돌 — 사건부호 미매핑 시 ID가 뭉개져 판례가 서로 덮어써짐
  3. NFD — macOS 파일명 자모 분해로 사건번호 정규식이 조용히 실패

실행: python3 test_precedent_ingest.py
"""

from __future__ import annotations

import os
import re
import csv
import sys
import contextlib
import unicodedata
import xml.etree.ElementTree as ET

import fetch_court_precedents as fetch
import pinecone_upload_court_precedents as upload

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_CSV = os.path.join(BASE_DIR, "output_노동법교재", "누락_판례목록.csv")

# 실제 대상 601건에 등장하는 사건부호 전종(12종)의 대표 표본.
# CSV는 gitignore 대상이라 CI에는 없다 — 부호 커버리지·ID 충돌 회귀를
# 데이터 없이도 검증하려면 픽스처가 필요하다. 2자리/4자리 연도를 함께 담아
# NFD·연도자릿수 회귀도 같이 잡는다.
FIXTURE_CASE_NOS = [
    "77다355", "2001다29452",          # 다 (321건)
    "98두7787", "2015두46321",         # 두 (124건)
    "90누9421", "2012누166",           # 누 (65건)
    "90도357", "2007도3192",           # 도 (31건)
    "90다카13465",                     # 다카 (27건)
    "90헌바19", "2011헌바395",         # 헌바 (16건)
    "98헌마141", "2004헌마670",        # 헌마 (9건)
    "2000대8127",                      # 대 — OCR 오인식 (3건)
    "99나41468", "2012나21609",        # 나 (2건)
    "2020도다296321",                  # 도다 — OCR 오인식 (1건)
    "98가합20043",                     # 가합 (1건)
    "89헌가106",                       # 헌가 (1건)
]


def _target_case_numbers() -> tuple[list[str], str]:
    """검증 대상 사건번호 목록. CSV가 있으면 전량, 없으면 픽스처."""
    if os.path.exists(INPUT_CSV):
        with open(INPUT_CSV, encoding="utf-8-sig") as f:
            return [r["사건번호"].strip() for r in csv.DictReader(f)], "CSV 전량"
    return list(FIXTURE_CASE_NOS), "내장 픽스처"


_failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name}  {detail}")
        _failures.append(name)


# ── 픽스처 ────────────────────────────────────────────────────────────────────

# 실측: '90누9421' 검색 시 법제처가 반환한 무관한 결과 (요청 사건 없음)
FIXTURE_MISMATCH = """<?xml version="1.0" encoding="UTF-8"?>
<PrecSearch><target>prec</target><totalCnt>2</totalCnt>
<prec id="1"><판례일련번호>241875</판례일련번호><사건명>부당해고구제재심판정취소</사건명>
<사건번호>2023두57876</사건번호><선고일자>2024.10.25</선고일자><법원명>대법원</법원명></prec>
<prec id="2"><판례일련번호>217381</판례일련번호><사건명>부당해고구제재심판정취소</사건명>
<사건번호>2016두64876</사건번호><선고일자>2021.07.29</선고일자><법원명>대법원</법원명></prec>
</PrecSearch>"""

FIXTURE_EXACT = """<?xml version="1.0" encoding="UTF-8"?>
<PrecSearch><target>prec</target><totalCnt>1</totalCnt>
<prec id="1"><판례일련번호>237583</판례일련번호><사건명>임금</사건명>
<사건번호>2016다255941</사건번호><선고일자>2023.09.21</선고일자><법원명>대법원</법원명></prec>
</PrecSearch>"""

FIXTURE_PREC_DETAIL = """<?xml version="1.0" encoding="UTF-8"?>
<PrecService><판례정보일련번호>237583</판례정보일련번호><사건명>임금</사건명>
<사건번호>2016다255941</사건번호><선고일자>20230921</선고일자><법원명>대법원</법원명>
<사건종류명>민사</사건종류명><판결유형>전원합의체 판결</판결유형>
<판시사항>&lt;br/&gt;  국가가 공무원이 아닌 사람들과 &amp;quot;계약&amp;quot;을 체결한 경우&lt;br/&gt;둘째 줄</판시사항>
<판결요지>[다수의견] 공무원의 경우</판결요지>
<참조조문>헌법 제11조 제1항, 근로기준법 제6조</참조조문>
<참조판례></참조판례>
<판례내용>【원고, 상고인】 별지 원고 명단 기재와 같다.</판례내용>
</PrecService>"""

FIXTURE_DETC_DETAIL = """<?xml version="1.0" encoding="UTF-8"?>
<DetcService><헌재결정례일련번호>24646</헌재결정례일련번호><종국일자>20130725</종국일자>
<사건번호>2011헌바395</사건번호><사건명>구 파견근로자보호 등에 관한 법률 제43조 제1호 등 위헌소원</사건명>
<사건종류명>헌바</사건종류명>
<판시사항>가.법에서 정한 근로자파견대상업무 외에</판시사항>
<결정요지>가.'근로자파견'은 파견사업주가</결정요지>
<전문>[당사자]
청 구 인 류○춘</전문>
<참조조문>구 파견근로자보호 등에 관한 법률 제5조</참조조문>
<참조판례>헌재 2005. 6. 30. 2002헌바83</참조판례>
</DetcService>"""


def _search_from_fixture(xml: str, case_no: str, target: str) -> dict | None:
    """search_case의 정확일치 게이트만 픽스처로 재현 (네트워크 없음)."""
    root = ET.fromstring(xml)
    tag = "Detc" if target == "detc" else "prec"
    id_field = "헌재결정례일련번호" if target == "detc" else "판례일련번호"
    wanted = fetch.normalize_case_no(case_no)
    for el in root.iter(tag):
        if fetch.normalize_case_no(el.findtext("사건번호") or "") != wanted:
            continue
        serial = el.findtext(id_field)
        if serial and serial.strip().isdigit():
            return {"serial_id": int(serial.strip()), "target": target}
    return None


# ── 테스트 ────────────────────────────────────────────────────────────────────

def t1_exact_match_gate() -> None:
    """무관한 검색 결과는 채택하지 않는다."""
    got = _search_from_fixture(FIXTURE_MISMATCH, "90누9421", "prec")
    check("T1 오매칭 결과 거부", got is None, f"got={got}")


def t2_exact_match_accepts() -> None:
    got = _search_from_fixture(FIXTURE_EXACT, "2016다255941", "prec")
    check("T2 정확일치 채택", got is not None and got["serial_id"] == 237583,
          f"got={got}")


def t3_nfd_case_number() -> None:
    """NFD(자모 분해) 문자열에서도 사건번호 비교·추출이 동작한다."""
    nfc = "2020다242423"
    nfd = unicodedata.normalize("NFD", nfc)
    check("T3-a NFD/NFC 정규화 일치",
          fetch.normalize_case_no(nfd) == fetch.normalize_case_no(nfc))
    check("T3-b NFD 원본은 정규식 미매치(전제 확인)",
          not fetch.CASE_NO_RE.search(nfd))
    check("T3-c NFC 변환 후 추출 성공",
          fetch.CASE_NO_RE.search(unicodedata.normalize("NFC", nfd)) is not None)
    check("T3-d 업로드측 ASCII 변환도 NFD 흡수",
          upload.case_no_to_ascii(nfd) == "2020da242423",
          upload.case_no_to_ascii(nfd))


def t4_vector_id_uniqueness() -> None:
    """전체 사건번호 → 벡터 ID 충돌 0건.

    이 검사가 없으면 사건부호 미매핑 시 ID가 뭉개져 판례가 서로를 덮어쓴다
    (기존 pinecone_upload_legal.py에서 실제로 발생한 실패 모드).
    """
    cases, src = _target_case_numbers()
    print(f"    (대상: {len(cases)}건 — {src})")

    ids: dict[str, list[str]] = {}
    unmapped: list[str] = []
    for raw in cases:
        case = fetch.OCR_FIXES.get(raw, raw)
        try:
            vid = upload.make_vector_id(case, 0)
        except upload.UnknownCaseCode:
            unmapped.append(case)
            continue
        ids.setdefault(vid, []).append(case)

    collisions = {k: v for k, v in ids.items() if len(v) > 1}
    check("T4-a 미매핑 사건부호 없음", not unmapped, f"{unmapped[:5]}")
    check("T4-b 벡터 ID 충돌 0건", not collisions,
          f"{list(collisions.items())[:3]}")
    check("T4-c ID 개수 = 사건 개수",
          len(ids) + len(unmapped) == len(cases),
          f"{len(ids)}+{len(unmapped)} vs {len(cases)}")

    # 2자리 연도가 4자리 연도와 동등하게 처리되는지 (구 정규식의 실패 지점)
    check("T4-d 2자리 연도 ID 생성",
          upload.make_vector_id("90누9421", 0) == "precedent_90nu9421_chunk_0",
          upload.make_vector_id("90누9421", 0))
    check("T4-e 복합 부호 긴 것 우선 치환",
          upload.make_vector_id("90다카13465", 0) == "precedent_90daka13465_chunk_0",
          upload.make_vector_id("90다카13465", 0))


def t5_case_code_coverage() -> None:
    """모든 사건부호가 매핑에 존재한다."""
    cases, src = _target_case_numbers()
    missing = set()
    for raw in cases:
        case = fetch.OCR_FIXES.get(raw, raw)
        m = re.match(r"^\d{2,4}([가-힣]{1,4})\d+$", unicodedata.normalize("NFC", case))
        if not m:
            missing.add(case)
            continue
        try:
            upload.case_no_to_ascii(case)
        except upload.UnknownCaseCode:
            missing.add(m.group(1))
    check(f"T5-a 전 사건부호 매핑 존재 ({src})", not missing, f"{sorted(missing)[:8]}")
    check("T5-b 미매핑 부호는 예외로 드러남",
          _raises_unknown_code("2020훼1234"), "조용히 통과하면 ID가 뭉개진다")


def _raises_unknown_code(case_no: str) -> bool:
    try:
        upload.case_no_to_ascii(case_no)
    except upload.UnknownCaseCode:
        return True
    return False


def t6_detc_field_mapping() -> None:
    """헌재 스키마(결정요지/전문/종국일자)가 공통 dict로 정규화된다."""
    root = ET.fromstring(FIXTURE_DETC_DETAIL)
    rec = fetch.normalize_record(root, "detc", 24646)
    check("T6-a 법원명 보정", rec["court"] == "헌법재판소", rec["court"])
    check("T6-b 결정요지 → summary", rec["summary"].startswith("가."), rec["summary"][:20])
    check("T6-c 전문 → full_text", "당사자" in rec["full_text"], rec["full_text"][:20])
    check("T6-d 종국일자 포맷", rec["date"] == "2013.07.25", rec["date"])
    check("T6-e 사건번호", rec["case_no"] == "2011헌바395", rec["case_no"])

    prec = fetch.normalize_record(ET.fromstring(FIXTURE_PREC_DETAIL), "prec", 237583)
    check("T6-f prec 판결요지 → summary", prec["summary"].startswith("[다수의견]"))
    check("T6-g prec 판례내용 → full_text", "원고" in prec["full_text"])
    check("T6-h prec 선고일자 포맷", prec["date"] == "2023.09.21", prec["date"])


def t7_text_cleaning() -> None:
    """<br/> 변환과 HTML 엔티티 언이스케이프."""
    prec = fetch.normalize_record(ET.fromstring(FIXTURE_PREC_DETAIL), "prec", 237583)
    issue = prec["issue"]
    check("T7-a <br/> 잔존 없음", "<br" not in issue.lower(), issue[:60])
    check("T7-b 개행 변환됨", "\n" in issue, repr(issue[:80]))
    check("T7-c HTML 엔티티 해제", "&quot;" not in issue and '"' in issue, issue[:60])
    check("T7-d 선두 개행 제거", not issue.startswith("\n"), repr(issue[:20]))

    # <br/>이 이스케이프가 아니라 실제 XML 엘리먼트로 오는 경우에도
    # tail 텍스트가 유실되지 않아야 한다 (findtext 대신 itertext 사용).
    mixed = ET.fromstring(
        "<PrecService><사건번호>1다1</사건번호>"
        "<판시사항>앞부분<br/>뒷부분</판시사항></PrecService>"
    )
    rec = fetch.normalize_record(mixed, "prec", 1)
    check("T7-e 실제 br 엘리먼트의 tail 보존",
          "앞부분" in rec["issue"] and "뒷부분" in rec["issue"], repr(rec["issue"]))


def t8_chunk_excludes_full_text() -> None:
    """전문은 임베딩 대상에서 제외된다."""
    check("T8-a EMBED_SECTIONS에 전문 없음", "전문" not in upload.EMBED_SECTIONS)

    rec = fetch.normalize_record(ET.fromstring(FIXTURE_PREC_DETAIL), "prec", 237583)
    md = fetch.to_markdown(rec)
    check("T8-b 마크다운에는 전문 포함", "## 전문" in md)

    doc = {
        "case_no": rec["case_no"],
        "title": rec["case_name"],
        "court": rec["court"],
        "date": rec["date"],
        "category": rec["case_type"],
        "sections": upload.parse_sections(md),
    }
    chunks = upload.chunk_doc(doc)
    sections = {c["section"] for c in chunks}
    check("T8-c 청크에 전문 미포함", "전문" not in sections, sections)
    check("T8-d 대상 섹션은 청킹됨", "판시사항" in sections and "판결요지" in sections,
          sections)
    check("T8-e 청크 인덱스 연속", [c["chunk_index"] for c in chunks] == list(range(len(chunks))))


def t9_markdown_roundtrip() -> None:
    """생성한 마크다운을 업로드측 파서가 되읽을 수 있다."""
    rec = fetch.normalize_record(ET.fromstring(FIXTURE_PREC_DETAIL), "prec", 237583)
    md = fetch.to_markdown(rec)
    meta = upload.parse_meta(md)
    check("T9-a 사건번호 왕복", meta.get("사건번호") == "2016다255941", meta.get("사건번호"))
    check("T9-b 법원 왕복", meta.get("법원") == "대법원", meta.get("법원"))
    check("T9-c 작성일 왕복", meta.get("작성일") == "2023.09.21", meta.get("작성일"))
    check("T9-d 원문 URL 추출", str(meta.get("원문", "")).startswith("https://"),
          meta.get("원문"))
    fn = fetch.safe_filename(rec["case_no"], rec["case_name"])
    check("T9-e 파일명 사건번호 선두", fn.startswith("2016다255941_"), fn)
    check("T9-f 파일명 경로문자 없음", "/" not in fn and ":" not in fn, fn)


def t10_dedup_ignores_citations() -> None:
    """중복 판정은 문서가 '다루는' 사건만 본다 — 참조판례 인용은 무시."""
    doc = """# 해고무효확인

| 항목 | 내용 |
| --- | --- |
| 사건번호 | 2016다255941 |

---

## 판결요지
본문에서 대법원 2010. 3. 11. 선고 2009다82244 판결을 인용한다.

## 참조판례
대법원 2007. 3. 26. 선고 2005두13018 판결 / 대법원 2013. 3. 14. 선고 2010다101011 판결
"""
    rep = fetch.extract_representative_case_no(doc, "2016다255941_해고무효확인.md")
    check("T10-a 대표 사건번호 = 메타필드", rep == "2016다255941", rep)

    all_found = set(fetch.CASE_NO_RE.findall(doc))
    check("T10-b 본문 전체 긁기는 인용까지 포함(전제 확인)",
          {"2009다82244", "2005두13018", "2010다101011"} <= all_found, all_found)
    check("T10-c 인용 사건번호는 대표에서 제외", rep not in {"2009다82244", "2005두13018"})

    # 메타필드가 없으면 파일명 → 본문 앞부분 순으로 폴백
    no_meta = "# 제목\n\n대법원 2012. 9. 27. 선고 2010다99279 판결\n"
    check("T10-d 파일명 폴백",
          fetch.extract_representative_case_no(no_meta, "1219473_제목.md") == "2010다99279"
          or fetch.extract_representative_case_no(no_meta, "2010다99279_제목.md") == "2010다99279")


def t11_target_routing() -> None:
    """조회 대상 API는 사건부호로 정한다 — CSV 법원 컬럼은 틀릴 수 있다."""
    check("T11-a 헌재 사건은 법원 컬럼이 틀려도 detc",
          fetch.resolve_target("2005헌바20", "대법원") == "detc")
    check("T11-b 헌마도 detc", fetch.resolve_target("98헌마141", "대법원") == "detc")
    check("T11-c 일반 사건은 prec", fetch.resolve_target("2016다255941", "대법원") == "prec")
    check("T11-d 법원 컬럼이 헌재면 detc",
          fetch.resolve_target("2004헌마670", "헌법재판소") == "detc")


def t12_merged_case_number() -> None:
    """병합 사건번호('2000다51919, 51926')를 요청 번호와 일치로 인정."""
    check("T12-a 정확 일치", fetch.detail_matches("2016다255941", "2016다255941"))
    check("T12-b 병합 앞 번호", fetch.detail_matches("2000다51919, 51926", "2000다51919"))
    check("T12-c 병합 뒤 번호(부호 생략형)",
          fetch.detail_matches("2000다51919, 51926", "2000다51926"))
    check("T12-d 병합 뒤 번호(부호 포함형)",
          fetch.detail_matches("2015다221903(본소), 2015다221910(반소)", "2015다221910"))
    check("T12-e 무관한 사건은 거부",
          not fetch.detail_matches("2000다51919, 51926", "2000다99999"))


def t13_topic_enrichment() -> None:
    """교재 쟁점 태그가 md → 업로드 파이프라인으로 흐른다 (별도 청크 없이)."""
    import enrich_court_precedents as enrich

    rec = fetch.normalize_record(ET.fromstring(FIXTURE_PREC_DETAIL), "prec", 237583)
    md = fetch.to_markdown(rec)
    topics = ["균등처우의 원칙 › 비교대상 근로자", "차별적 처우의 금지"]

    enriched = enrich.insert_topics(md, topics)
    check("T13-a 섹션 삽입", "## 관련 쟁점" in enriched)
    check("T13-b 멱등(재삽입해도 1개)",
          enrich.insert_topics(enriched, topics).count("## 관련 쟁점") == 1)
    check("T13-c 빈 목록이면 기존 섹션 제거",
          "## 관련 쟁점" not in enrich.insert_topics(enriched, []))

    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                     encoding="utf-8") as f:
        f.write(enriched)
        path = f.name
    try:
        doc = upload.parse_doc(path)
    finally:
        os.unlink(path)

    check("T13-d topics 파싱", doc["topics"] == topics, doc["topics"])
    chunks = upload.chunk_doc(doc)
    sections = {c["section"] for c in chunks}
    check("T13-e 쟁점은 별도 청크가 아님", "관련 쟁점" not in sections, sections)
    check("T13-f embed_text에 쟁점 포함",
          all("쟁점: 균등처우의 원칙" in c["embed_text"] for c in chunks))
    check("T13-g 저장 텍스트에 쟁점 프리픽스(BM25 색인용)",
          all(c["chunk_text"].startswith("[관련 쟁점:") for c in chunks))
    check("T13-h 쟁점 유무와 무관하게 벡터 ID 동일",
          chunks[0]["vector_id"] == "precedent_2016da255941_chunk_0",
          chunks[0]["vector_id"])

    # 교재 공백 낀 표기("95다 53188")도 스캔에 잡힌다
    body = "## 제9절 취업규칙\n\n#### 1. 불이익 변경\n\n대법원 1996.10.15. 선고 95다 53188 판결에 따르면...\n"
    idx = enrich.build_case_topic_index(body, {"95다53188"}, {})
    check("T13-i 공백 낀 사건번호 매칭", "95다53188" in idx, idx)
    check("T13-j 표제 경로 추출", idx.get("95다53188") == ["취업규칙 › 불이익 변경"],
          idx.get("95다53188"))


def t14_nfd_bug_sealed() -> None:
    """기존 업로드 스크립트 2종의 NFD·정규식 결함이 봉인됐는지 (Track A)."""
    import pinecone_upload_legal as legal
    import upload_new_precedents as newprec

    # T14-a: NFD 파일명에서 post_id 추출
    nfd = unicodedata.normalize("NFD", "2020다242423_추가 법정수당.md")
    check("T14-a legal NFD 파일명", legal.extract_post_id(nfd, "precedent") == "2020da242423",
          legal.extract_post_id(nfd, "precedent"))

    # T14-b: 2자리 연도·복합 부호
    for raw, want in [("90누9421_제목.md", "90nu9421"),
                      ("86다카24445_제목.md", "86daka24445"),
                      ("2011헌바395_제목.md", "2011heonba395")]:
        got = legal.extract_post_id(unicodedata.normalize("NFD", raw), "precedent")
        check(f"T14-b {raw.split('_')[0]}", got == want, got)

    # T14-c: 고유성 시뮬레이션 — CSV가 있으면 601건 전량, 없으면 부호 픽스처.
    # 전부 NFD 파일명으로 변환해 macOS 실환경을 재현한다.
    cases, src = _target_case_numbers()
    ids = {}
    for c in cases:
        case = fetch.OCR_FIXES.get(c, c)
        pid = legal.extract_post_id(
            unicodedata.normalize("NFD", f"{case}_제목.md"), "precedent")
        ids.setdefault(pid, []).append(case)
    collisions = {k: v for k, v in ids.items() if len(v) > 1}
    check(f"T14-c post_id 충돌 0 ({len(cases)}건 — {src})", not collisions,
          list(collisions.items())[:3])
    check("T14-d 미매핑 부호는 hex 폴백(숫자 폴백 금지)",
          legal.extract_post_id("2020훼1234_x.md", "precedent").startswith("case_x"),
          legal.extract_post_id("2020훼1234_x.md", "precedent"))

    # T14-e: upload_new_precedents 대표 사건번호 — NFD 원문·NFD 파일명을
    # 정규화 없이 그대로 넘겨 내부 NFC 처리를 검증한다.
    doc_nfd = unicodedata.normalize("NFD", """# 제목

| 항목 | 내용 |
| --- | --- |
| 사건번호 | 86다카24445 |

---
본문에서 대법원 2010. 3. 11. 선고 2009다82244 판결을 인용한다.
""")
    # 메타필드는 호출부(collect_existing_case_numbers)가 NFC 정규화 후 넘기는
    # 계약이므로 NFC 경로 검증 + 파일명 폴백은 NFD 그대로 넘겨 내부 처리 검증.
    rep = newprec._representative_case_no(
        unicodedata.normalize("NFC", doc_nfd), "86다카24445_제목.md")
    check("T14-e newprec 대표 사건번호(다카)", rep == "86다카24445", rep)
    rep_fn = newprec._representative_case_no(
        "메타 없음", unicodedata.normalize("NFD", "2011헌바395_제목.md"))
    check("T14-e2 newprec NFD 파일명 폴백(헌바)", rep_fn == "2011헌바395", rep_fn)
    check("T14-f newprec 정규식 2자리 연도",
          newprec.CASE_NO_PATTERN.search("90누9421") is not None)
    check("T14-g newprec chunk_id 미매핑 부호 hex 폴백",
          newprec.case_no_to_ascii("2020훼1234").startswith("case_x"),
          newprec.case_no_to_ascii("2020훼1234"))
    check("T14-h newprec chunk_id 복합 부호",
          newprec.case_no_to_ascii("2011헌바395") == "2011heonba395",
          newprec.case_no_to_ascii("2011헌바395"))

    # T14-i: hex 폴백은 절단하지 않는다 — 앞 바이트를 공유하는 두 사건이
    # 같은 ID로 충돌하면 upsert가 서로를 덮어쓴다.
    a = newprec.case_no_to_ascii("2020훼123456")
    b = newprec.case_no_to_ascii("2020훼123457")
    check("T14-i hex 폴백 절단 없음(앞바이트 공유 사건 구분)", a != b, f"{a} == {b}")
    la = legal.extract_post_id("2020훼123456_x.md", "precedent")
    lb = legal.extract_post_id("2020훼123457_x.md", "precedent")
    check("T14-i2 legal도 동일", la != lb, f"{la} == {lb}")

    # T14-j: NFC/NFD 입력이 같은 hex ID를 생성한다 — 호출 경로에 따라
    # 같은 사건이 다른 ID를 갖게 되면 결정성이 깨진다.
    nfc_in = "2020훼1234"
    nfd_in = unicodedata.normalize("NFD", nfc_in)
    check("T14-j hex 폴백 NFC/NFD 동일",
          newprec.case_no_to_ascii(nfc_in) == newprec.case_no_to_ascii(nfd_in))
    check("T14-j2 legal도 동일",
          legal.extract_post_id(f"{nfc_in}_x.md", "precedent")
          == legal.extract_post_id(unicodedata.normalize("NFD", f"{nfc_in}_x.md"), "precedent"))


def t15_cases_mode() -> None:
    """--cases 명시 대상 모드 (Track B §2.2)."""
    import sync_overlap_precedents as sync

    # T15-a: 대상 CSV 파싱 — 게시글ID 빈 값 허용·추가 컬럼 무시는
    # csv.DictReader 사용 계약이므로 select_deletion_targets로 검증
    targets = [
        {"사건번호": "2020다1111", "법원": "대법원", "게시글ID": "403778", "메모": "무시"},
        {"사건번호": "2020다2222", "법원": "대법원", "게시글ID": ""},
    ]
    fetched = {"2020다1111": "f1.md", "2020다2222": "f2.md"}
    sel = sync.select_deletion_targets(targets, fetched)
    check("T15-a 게시글ID 빈 값은 삭제 제외", sel == [("2020다1111", "403778")], sel)

    # T15-b: --cases 모드의 L2 생략을 함수 반환값으로 검증 (문자열 매칭 아님)
    orig = fetch.collect_existing_case_numbers
    try:
        fetch.collect_existing_case_numbers = lambda dirs: {"2020다9999"}
        check("T15-b cases 모드 → 빈 집합(L2 생략)",
              fetch.resolve_existing(cases_mode=True) == set())
        check("T15-c 기본 모드 → 수집기 호출",
              fetch.resolve_existing(cases_mode=False) == {"2020다9999"})
    finally:
        fetch.collect_existing_case_numbers = orig


def t16_ctx_deletion_safety() -> None:
    """ctx 삭제 안전 규칙 (설계 §2.3)."""
    import sync_overlap_precedents as sync

    targets = [
        {"사건번호": "2020다1111", "법원": "대법원", "게시글ID": "403778"},   # 성공+ID
        {"사건번호": "2020다2222", "법원": "대법원", "게시글ID": "403779"},   # 수집 실패
        {"사건번호": "2020다3333", "법원": "대법원", "게시글ID": ""},         # ID 없음
    ]
    fetched = {"2020다1111": "a.md", "2020다3333": "c.md"}
    sel = sync.select_deletion_targets(targets, fetched)
    check("T16-a 성공∩게시글ID 교집합만", sel == [("2020다1111", "403778")], sel)

    check("T16-b 정상 ID 통과", sync.valid_ctx_id("ctx_precedent_403778_c3", "403778"))
    check("T16-c 부분일치 오폭 거부", not sync.valid_ctx_id("ctx_precedent_4037789_c0", "403778"))
    check("T16-d 접미 변형 거부", not sync.valid_ctx_id("ctx_precedent_403778_c3x", "403778"))
    check("T16-e 타 소스 거부", not sync.valid_ctx_id("ctx_interpretation_403778_c0", "403778"))



# ── T17~T20: 해설서 코퍼스 (textbook-corpus-embedding) ──────────────────────
#
# 이 기능도 조용히 틀리는 실패 모드를 갖는다:
#   · chunk_id에 서적 식별자가 없으면 두 번째 서적이 첫 번째를 덮어쓴다
#     (실측: Win 1,414 / 주해Ⅲ 463청크에서 177건 충돌)
#   · 헤딩 위생 규칙이 정상 표제를 오폐기하면 섹션 경계가 사라진다
#   · 인용 가드 G4가 BM25 경로에서 우회되면 저작물이 대량 노출된다
#   · 사건부호 화이트리스트가 없으면 조문 표기가 사건번호로 오인된다

@contextlib.contextmanager
def _tmp_book(book_id: str, body: str, ocr_fixes: dict | None = None):
    """임시 마크다운 파일을 가진 Book. 원본 .md는 gitignore라 CI에 없다."""
    import tempfile
    import pinecone_upload_textbook as tb
    fd, path = tempfile.mkstemp(suffix=".md", prefix=f"tb_{book_id}_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("표지 잡음\n<!-- BODY -->\n" + body)
    try:
        yield tb.Book(book_id=book_id, title=f"테스트 서적 {book_id}", path=path,
                      body_start="<!-- BODY -->", ocr_fixes=ocr_fixes or {})
    finally:
        os.unlink(path)


def t17_textbook_chunk_id_scope() -> None:
    import pinecone_upload_textbook as tb

    body = "\n".join(f"# 표제 {i}\n\n본문 {i} " + "가나다라마바사" * 20
                     for i in range(6))
    with _tmp_book("alpha", body) as a, _tmp_book("beta", body) as b:
        ca = tb.build_chunks(a)
        cb = tb.build_chunks(b)
        ida = {c["chunk_id"] for c in ca}
        idb = {c["chunk_id"] for c in cb}

        check("T17-a 동일 구조 두 서적의 chunk_id 교집합 0",
              not (ida & idb), sorted(ida & idb)[:3])
        check("T17-b chunk_id에 book_id 포함",
              all(c["chunk_id"].startswith("textbook_alpha_") for c in ca))
        check("T17-c 서적 내 chunk_id 유일", len(ida) == len(ca))

        # 생산자(chunk_id)와 소비자(rag._book_id_of)가 수동 동기화 대상이라
        # 실제 산출물로 교차검증한다 — 포맷을 바꾸면 여기서 걸린다.
        from app.core.rag import _book_id_of
        check("T17-i 생산 chunk_id → _book_id_of 왕복",
              {_book_id_of({"id": c["chunk_id"]}) for c in ca} == {"alpha"},
              {_book_id_of({"id": c["chunk_id"]}) for c in ca})

    # 폐기 헤딩이 section_idx를 소비하면 ocr_fixes 한 줄 변경에 뒤쪽 ID가 전부
    # 밀려 고아 벡터가 생긴다. 폐기율 상한(10%)에 걸리지 않도록 유효 헤딩을
    # 충분히 둔다 — 상한 자체는 T17-h가 따로 검증한다.
    dirty = ("# $I.9$\n\n버려질 본문\n\n" +
             "\n".join(f"# 유효 표제 {i}\n\n본문 {i} " + "가나다라마" * 10
                       for i in range(20)))
    with _tmp_book("gamma", dirty) as d:
        chunks = tb.build_chunks(d)
        first = [c for c in chunks if c["chunk_id"].startswith("textbook_gamma_0000_")]
        check("T17-d 폐기 헤딩은 section_idx를 소비하지 않음",
              bool(first) and first[0]["section"] == "유효 표제 0",
              [c["chunk_id"] for c in chunks[:3]])
        check("T17-e 폐기 헤딩의 본문은 유실되지 않음",
              any("버려질 본문" in c["chunk_text"] for c in chunks))

    # 위생 규칙 오작동·body_start 오류로 섹션이 조용히 뭉개지는 것을 막는 게이트.
    noisy = "\n".join(f"# $I.{i}$\n\n본문 {i}" for i in range(5))
    with _tmp_book("delta", noisy) as n:
        raised = False
        try:
            tb.build_chunks(n)
        except SystemExit:
            raised = True
        check("T17-h 폐기율 상한 초과 시 중단", raised)

    # 청킹이 줄면 이전 실행의 벡터가 Pinecone에 남아 검색에 계속 섞인다 —
    # upsert는 덮어쓸 뿐 지우지 않는다(CodeRabbit #46 지적).
    class _FakeIndex:
        def __init__(self): self.deleted = []
        def delete(self, ids, namespace): self.deleted.extend(ids)

    # prune_stale_vectors는 성공 시 원장을 기록한다 — 패치하지 않으면 테스트가
    # 실제 output_노동법교재/_uploaded_ids.json 을 덮어써 롤백 수단을 파괴한다.
    import tempfile, json as _json
    _fd, _ledger = tempfile.mkstemp(suffix=".json"); os.close(_fd)
    _orig_ledger = tb.UPLOADED_IDS_FILE
    tb.UPLOADED_IDS_FILE = _ledger

    book = tb.BOOKS["win"]
    idx = _FakeIndex()
    current = [f"textbook_win_{i:04d}_0" for i in range(10)]
    previous = set(current) | {"textbook_win_0010_0", "textbook_win_0011_0"}
    tb.prune_stale_vectors(book, current, previous, idx)
    check("T17-j 사라진 이전 ID만 삭제",
          sorted(idx.deleted) == ["textbook_win_0010_0", "textbook_win_0011_0"], idx.deleted)

    idx2 = _FakeIndex()
    tb.prune_stale_vectors(book, current, set(current), idx2)
    check("T17-k 차집합 없으면 삭제 0", idx2.deleted == [], idx2.deleted)

    # 대량 삭제는 chunk_id 규격이 바뀐 신호다 — 조용히 지우면 되돌릴 수 없다.
    idx3 = _FakeIndex()
    raised = False
    try:
        tb.prune_stale_vectors(book, current, set(f"old_{i}" for i in range(50)), idx3)
    except SystemExit:
        raised = True
    check("T17-l 50% 초과 고아는 중단", raised and idx3.deleted == [], idx3.deleted)

    # 원장이 합집합으로 남으면 다음 실행이 이미 지운 ID를 또 stale로 계산하고,
    # 50% 가드가 한 번 걸리면 매번 같은 지점에서 멈춘다(CodeRabbit 재리뷰 지적).
    ledger = _ledger
    try:
        with open(ledger, "w", encoding="utf-8") as f:
            _json.dump({"win": current + ["textbook_win_0010_0"], "juhae3": ["x"]}, f)
        idx4 = _FakeIndex()
        tb.prune_stale_vectors(book, current, set(current) | {"textbook_win_0010_0"}, idx4)
        after = _json.load(open(ledger, encoding="utf-8"))
        check("T17-m 삭제 성공 후 원장이 현재 집합으로 확정",
              after["win"] == sorted(current), after["win"][-2:])
        check("T17-n 다른 서적 원장은 보존", after["juhae3"] == ["x"], after.get("juhae3"))

        # 재실행 시 stale이 0이어야 한다 — 아니면 무한 재삭제/무한 중단
        idx5 = _FakeIndex()
        tb.prune_stale_vectors(book, current, set(after["win"]), idx5)
        check("T17-o 재실행 시 재삭제 없음", idx5.deleted == [], idx5.deleted)

        # 50% 초과라도 명시 플래그로는 통과해야 한다 — 원장 비우기가 탈출구면
        # previous가 사라져 고아가 영구히 남는다
        with open(ledger, "w", encoding="utf-8") as f:
            _json.dump({"win": [f"old_{i}" for i in range(50)]}, f)
        idx6 = _FakeIndex()
        tb.prune_stale_vectors(book, current, {f"old_{i}" for i in range(50)},
                               idx6, allow_large=True)
        check("T17-p --allow-large-prune 로 대량 삭제 통과", len(idx6.deleted) == 50,
              len(idx6.deleted))
    finally:
        tb.UPLOADED_IDS_FILE = _orig_ledger
        os.unlink(_ledger)

    check("T17-q 테스트가 실제 원장을 건드리지 않음",
          tb.UPLOADED_IDS_FILE == _orig_ledger, tb.UPLOADED_IDS_FILE)

    check("T17-f book_id 정규식은 밑줄 거부", not tb._BOOK_ID_RE.match("my_book"))
    check("T17-g book_id 정규식은 소문자·숫자 허용", bool(tb._BOOK_ID_RE.match("juhae3")))


def t18_heading_sanitizer() -> None:
    from pinecone_upload_textbook import sanitize_heading

    # 자간 공백 오폐기 회귀 — 분모를 전체 길이로 잡으면 2/6=0.33 < 0.35로
    # 정상 표제가 버려진다.
    check("T18-a '2. 요 건' 유지", sanitize_heading("2. 요 건", {}) == "2. 요 건",
          sanitize_heading("2. 요 건", {}))
    check("T18-b 'I. 근 로 자' 유지", sanitize_heading("I. 근 로 자", {}) is not None)

    for garbage in ("$I.99$", "$/대 모 키$", "$I.7$ $A$",
                    "!" * 40, "(K M 3장 임 금 C K", "$1.9$ 의"):
        check(f"T18-c 잔해 폐기 {garbage[:14]!r}",
              sanitize_heading(garbage, {}) is None, sanitize_heading(garbage, {}))

    # 조문 표기 추출은 길이 검사보다 먼저 — 59자짜리가 상한 60을 통과해
    # 잡음째로 살아남던 실측 케이스.
    noisy = "지역 이 이 이 시 시 <mark>제43조의5(업무위탁 등)</mark> 기회에 대한 기업이 있습니다. 11"
    check("T18-d 잡음 속 조문 표기 추출",
          sanitize_heading(noisy, {}) == "제43조의5(업무위탁등)", sanitize_heading(noisy, {}))

    # ocr_fixes는 원문 키로 매칭 — 정제 후 매칭하면 정제 로직이 바뀔 때마다
    # 치환 키가 조용히 무효가 된다.
    raw = "Ⅱ. 출국금지의 해제요청 800 2000 028 28 28 9 10 12"
    check("T18-e ocr_fixes는 원문 키 매칭",
          sanitize_heading(raw, {raw: "Ⅱ. 출국금지의 해제요청"}) == "Ⅱ. 출국금지의 해제요청")

    # 한자는 의미문자로 세므로 비율 판정을 통과한다 — 명시 치환 없이는 남는다.
    hanja = "기본원칙 高温 " + "日本 " * 12
    check("T18-f 한자 잔해는 비율 판정을 통과(명시 치환 필요)",
          sanitize_heading(hanja.strip(), {}) is not None)
    check("T18-g 명시 치환으로 해소",
          sanitize_heading(hanja.strip(), {hanja.strip(): "기본원칙"}) == "기본원칙")


def t19_citation_guard_cap() -> None:
    from app.core.rag import _cap_by_book, _book_id_of, MAX_CHUNKS_PER_BOOK

    hits = [{"id": f"textbook_win_{i:04d}_0", "book_id": "win",
             "source_type": "textbook", "score": 1.0 - i * 0.01} for i in range(5)]
    capped = _cap_by_book(hits)
    check("T19-a 동일 서적 5건 → 3건", len(capped) == MAX_CHUNKS_PER_BOOK, len(capped))
    check("T19-b rerank 순서 보존",
          [h["id"] for h in capped] == [h["id"] for h in hits[:3]])

    mixed = hits + [{"id": "prec_2020da1", "source_type": "precedent", "score": 0.5},
                    {"id": "prec_2020da2", "source_type": "precedent", "score": 0.4}]
    check("T19-c 비해설서 소스는 무제한", len(_cap_by_book(mixed)) == 5)

    two = ([{"id": f"textbook_win_{i:04d}_0", "book_id": "win"} for i in range(4)] +
           [{"id": f"textbook_juhae3_{i:04d}_0", "book_id": "juhae3"} for i in range(4)])
    check("T19-d 서적별로 독립 카운트", len(_cap_by_book(two)) == 6, len(_cap_by_book(two)))

    # BM25 코퍼스는 book_id를 담지 않았던 시기가 있다 — 메타데이터만 믿으면
    # BM25로 올라온 청크가 가드를 그대로 빠져나간다.
    bm25 = [{"id": f"textbook_win_{i:04d}_0", "source_type": "textbook"} for i in range(5)]
    check("T19-e book_id 없어도 벡터 ID에서 복원", _book_id_of(bm25[0]) == "win")
    check("T19-f BM25 경로도 상한 적용", len(_cap_by_book(bm25)) == MAX_CHUNKS_PER_BOOK)

    unknown = [{"id": "weird", "source_type": "textbook"} for _ in range(5)]
    check("T19-g 식별 불가 해설서도 상한 적용",
          len(_cap_by_book(unknown)) == MAX_CHUNKS_PER_BOOK)
    check("T19-h 판례는 book_id 없음", _book_id_of({"id": "x", "source_type": "precedent"}) == "")

    # 컨텍스트에서 빠진 청크는 인용 화이트리스트에서도 빠져야 한다.
    from app.core.rag import format_pinecone_hits
    rich = [dict(h, title="교재", section=f"s{i}", content=f"본문 {i}")
            for i, h in enumerate(hits)]
    _, meta = format_pinecone_hits(rich)
    check("T19-i meta_list도 함께 컷", len(meta) == MAX_CHUNKS_PER_BOOK, len(meta))


def t19b_citation_rules_attachment() -> None:
    """G1~G3 부착 조건 — 끊겨도 로그도 예외도 없어 조용히 무가드가 된다."""
    from app.templates.prompts import TEXTBOOK_CITATION_RULES, CONSULTATION_SYSTEM_PROMPT
    from app.core.pipeline import SYSTEM_PROMPT_TEMPLATE

    # 규칙은 어느 시스템 프롬프트 '본문'에도 있으면 안 된다 — 한쪽에만 들어가면
    # 다른 분기(임금계산·괴롭힘·법제처 실패)가 무가드가 된다.
    for name, tmpl in (("CONSULTATION", CONSULTATION_SYSTEM_PROMPT),
                       ("SYSTEM_PROMPT_TEMPLATE", SYSTEM_PROMPT_TEMPLATE)):
        check(f"T19b-a {name} 본문에 해설서 규칙 없음",
              "해설서 인용 규칙" not in tmpl)

    check("T19b-b 규칙 상수에 G1(축자 인용 금지)", "그대로 옮기지 마세요" in TEXTBOOK_CITATION_RULES)
    check("T19b-c 규칙 상수에 G2(단독 근거 금지)", "해설서만을 근거로" in TEXTBOOK_CITATION_RULES)
    check("T19b-d 규칙 상수에 G3(서명 표기)", "서명을 표기" in TEXTBOOK_CITATION_RULES)

    # 생산 코드의 공용 판정을 그대로 호출한다 — 테스트가 판정식을 재구현하면
    # pipeline이 바뀌어도 통과해버려 회귀를 못 잡는다(CodeRabbit #46 지적).
    from app.core.pipeline import uses_textbook as attaches

    check("T19b-e 해설서 있으면 부착",
          attaches([{"source_type": "precedent"}, {"source_type": "textbook"}]))
    check("T19b-f 해설서 없으면 미부착",
          not attaches([{"source_type": "precedent"}, {"source_type": "qa"}]))
    check("T19b-g 빈 목록이면 미부착", not attaches([]))
    # 법제처 폴백 경로의 dict에는 source_type 키가 없다(legal_api.fetch_precedent_details)
    check("T19b-h source_type 없는 dict 안전",
          not attaches([{"case_name": "x", "date": "2020", "court": "대법원"}]))
    check("T19b-i None 원소가 섞여도 판정 유지",
          attaches([None, {"source_type": "textbook"}]) and not attaches([None]))

    # 공개 게시판 제외 — 부착 조건과 같은 값(used_textbook)을 써야 한다.
    # 판정이 갈라지면 가드는 붙는데 게시판엔 올라가는(또는 반대) 상태가 된다.
    import api.index as api_index
    check("T19b-k _PUBLIC_EXCLUDE_KEYS에 textbook 포함",
          "textbook" in api_index._PUBLIC_EXCLUDE_KEYS, api_index._PUBLIC_EXCLUDE_KEYS)
    check("T19b-l 해설서 대화는 공개 제외 대상",
          api_index._is_public_excluded({"textbook": True}))
    check("T19b-m 일반 대화는 공개 유지",
          not api_index._is_public_excluded({"has_attachments": False}))

    # 부착 대상 hit이 컨텍스트에도 실제로 들어갔는지 — 두 값이 같은
    # format_pinecone_hits 반환에서 나오므로 구조적으로 어긋날 수 없어야 한다.
    from app.core.rag import format_pinecone_hits
    hits = [{"id": "textbook_win_0000_0", "book_id": "win", "source_type": "textbook",
             "title": "Win 노동법", "section": "s", "content": "본문", "score": 0.9}]
    text, meta = format_pinecone_hits(hits)
    check("T19b-j 컨텍스트 라벨과 부착 판정이 동기",
          ("[노동법 해설서]" in (text or "")) == attaches(meta))


def t20_textbook_case_extraction() -> None:
    import extract_textbook_cases as ex

    # 조문 표기 오인 — 조문 해설서에서 실측된 최다 오탐.
    for noise in ("제43조의2", "제43조의4", "제109조2", "제43조1"):
        check(f"T20-a 조문 표기 배제 {noise}", not ex.CASE_RE.search(noise),
              ex.CASE_RE.findall(noise))

    got = set(ex.extract_cases("대법원 2006다64245 판결과 87다카2803, 98헌마141 참조"))
    check("T20-b 복합 부호 절단 없음", "87다카2803" in got, sorted(got))
    check("T20-c 4자리 연도", "2006다64245" in got, sorted(got))
    check("T20-d 헌재 부호", "98헌마141" in got, sorted(got))

    check("T20-e 공백 낀 표기 흡수", "95다53188" in ex.extract_cases("95다 53188 판결"))
    check("T20-f 인용횟수 집계",
          ex.extract_cases("94도1477 그리고 94도1477")["94도1477"] == 2)

    check("T20-g 헌재 법원 추정", ex.guess_court("98헌마141") == "헌법재판소")
    check("T20-h 일반 법원 추정", ex.guess_court("2006다64245") == "대법원")

    # OCR 오인식 정정은 '추출 이전 본문 단계'여야 한다 — 오인식 부호('대',
    # '도다')는 화이트리스트에 없어 추출 자체가 안 되므로 사후 remap은
    # 어떤 입력에도 발동하지 않는 사문 코드가 된다.
    import fetch_court_precedents as fetch
    for wrong, right in fetch.OCR_FIXES.items():
        check(f"T20-j 사후 remap으로는 정정 불가 {wrong}",
              not ex.extract_cases(wrong), dict(ex.extract_cases(wrong)))
        # 생산 흐름과 같은 helper를 호출한다 — 여기서 치환을 재구현하면
        # extract_textbook_cases가 순서를 되돌려도 테스트가 통과한다.
        got = ex.extract_cases(ex.normalize_body(f"대법원 {wrong} 판결"))
        check(f"T20-k 생산 정규화 경로가 정정 {wrong}→{right}",
              right in got, list(got))

    import unicodedata
    nfd = unicodedata.normalize("NFD", "대법원 2000대8127 판결")
    check("T20-l NFD 본문도 정정됨(NFC 선행)",
          "2000다8127" in ex.extract_cases(ex.normalize_body(nfd)),
          list(ex.extract_cases(ex.normalize_body(nfd))))

    # fetch의 추출 정규식과 부호 커버리지가 어긋나면 수집 단계에서 탈락한다.
    for case in ("87다카2803", "98헌마141", "2006다64245", "90누9421"):
        check(f"T20-i fetch 정규식 호환 {case}",
              bool(fetch.CASE_NO_RE.fullmatch(case)), case)


def main() -> int:
    print("\n판례 수집·업로드 오프라인 테스트\n" + "=" * 50)
    for fn in (t1_exact_match_gate, t2_exact_match_accepts, t3_nfd_case_number,
               t4_vector_id_uniqueness, t5_case_code_coverage,
               t6_detc_field_mapping, t7_text_cleaning,
               t8_chunk_excludes_full_text, t9_markdown_roundtrip,
               t10_dedup_ignores_citations, t11_target_routing,
               t12_merged_case_number, t13_topic_enrichment,
               t14_nfd_bug_sealed, t15_cases_mode, t16_ctx_deletion_safety,
               t17_textbook_chunk_id_scope, t18_heading_sanitizer,
               t19_citation_guard_cap, t19b_citation_rules_attachment,
               t20_textbook_case_extraction):
        print(f"\n[{fn.__name__}]")
        fn()

    print("\n" + "=" * 50)
    if _failures:
        print(f"실패 {len(_failures)}건: {_failures}")
        return 1
    print("전체 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
