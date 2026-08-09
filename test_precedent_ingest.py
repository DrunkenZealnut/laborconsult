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


def main() -> int:
    print("\n판례 수집·업로드 오프라인 테스트\n" + "=" * 50)
    for fn in (t1_exact_match_gate, t2_exact_match_accepts, t3_nfd_case_number,
               t4_vector_id_uniqueness, t5_case_code_coverage,
               t6_detc_field_mapping, t7_text_cleaning,
               t8_chunk_excludes_full_text, t9_markdown_roundtrip,
               t10_dedup_ignores_citations, t11_target_routing,
               t12_merged_case_number, t13_topic_enrichment):
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
