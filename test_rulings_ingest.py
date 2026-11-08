#!/usr/bin/env python3
"""재결례 코퍼스 회귀 — adjudication-corpus RU1~RU20 (오프라인, API 키 불요, CI).

수집 정규화·정제·PII · md 왕복 · 소제목 청킹(관계법령 제외) · ID·원장 · 배선(공공 집합·라벨 G5·우선순위·stale) ·
인용 검증(기관 문맥·마스킹·별칭·기관 판정·고시 번호 음성) · pipeline 접미·4인자 호출 · BM25 코퍼스 비재결 문서 패턴 0건.

fixture는 2026-11-08 법제처 실제 응답(`data/ruling_fixtures/`, OC 제거·청구인 합성 치환). HTTP는 `_session.get`을
가짜로 바꿔 함수를 **실제로 호출**한다(test_legal_api_nlrc 방식 — fixture만 따로 파싱하면 코드의 추출 로직이 무방비다).
"""
from __future__ import annotations

import ast
import gzip
import json
import os
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
FIX = ROOT / "data" / "ruling_fixtures"
SYN_CLAIMANT = "○○○(남자, 40세, 사무직, (주)○○, 입사일 : 2000. 1. 1.)"


def _root(name: str) -> ET.Element:
    return ET.parse(FIX / name).getroot()


class _FakeResp:
    def __init__(self, content: bytes, status: int = 200) -> None:
        self.content = content
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests
            err = requests.HTTPError(f"{self.status_code} Server Error")
            err.response = self
            raise err


def _record(agency: str, serial: str) -> dict:
    import fetch_rulings as fr
    return fr.normalize_record(_root(f"{agency}_detail_{serial}.xml"), agency, serial)


def _doc_and_chunks(agency: str, serial: str, redactions=None):
    import fetch_rulings as fr
    import pinecone_upload_rulings as up
    rec = _record(agency, serial)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, f"{serial}_x.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(fr.to_markdown(rec))
        doc = up.parse_doc(path)
    assert doc is not None
    chunks, stats = up.chunk_doc(doc, redactions)
    return rec, doc, chunks, stats


class FetchNormalizeTest(unittest.TestCase):
    """RU1~RU5 — 목록·상세 정규화·정제·PII."""

    def test_ru1_list_parsing_dedupes_across_pages(self):
        import fetch_rulings as fr
        for agency, total in (("eiac", 118), ("iaciac", 934)):
            xml = (FIX / f"{agency}_list_p1.xml").read_bytes()
            calls = []

            def fake_get(url, params=None, timeout=None):
                calls.append(dict(params or {}))
                return _FakeResp(xml)

            with mock.patch.object(fr._session, "get", fake_get), mock.patch.object(fr.time, "sleep", lambda s: None):
                items, got_total = fr.fetch_list(agency, "fake-key")
            self.assertEqual(got_total, total)
            self.assertEqual(len(items), 3, items)                       # 모든 페이지가 같은 3건 → 중복 제거
            self.assertEqual(len(calls), -(-total // fr.PAGE_SIZE), "display 100 → eiac 2·iaciac 10페이지")
            self.assertTrue(all(c["target"] == agency and c["type"] == "XML" for c in calls))
            self.assertEqual([c["page"] for c in calls], [str(pg) for pg in range(1, -(-total // fr.PAGE_SIZE) + 1)])
            self.assertTrue(all(i["serial"].isdigit() and i["case_no"] and i["decided_at_raw"] for i in items))
        self.assertEqual(items[0]["serial"], "12699")
        self.assertEqual(items[0]["case_no"], "2010-2071호")

    def test_ru2_eiac_detail_normalization(self):
        rec = _record("eiac", "11327")
        self.assertEqual(rec["agency_name"], "고용보험심사위원회")
        self.assertEqual(rec["case_no"], "2019재결 제117호")
        self.assertEqual(rec["case_name"], "고용보험 구직급여일액 결정 처분 변경 청구")
        self.assertEqual(rec["title"], "고용보험심사위원회 2019재결 제117호 — 고용보험 구직급여일액 결정 처분 변경 청구")
        self.assertEqual((rec["decided_at"], rec["decided_year"]), ("2019.10.23", 2019))
        self.assertEqual(rec["category"], "수급자격에 관한 사례")
        self.assertEqual(rec["doc_kind"], "재결서")
        self.assertEqual(rec["summary_label"], "개요")
        self.assertTrue(rec["summary"].startswith("3조2교대"))
        self.assertTrue(rec["disposition"].startswith("피청구인이"))
        self.assertTrue(rec["reasoning"].startswith("1. 사건개요"))
        self.assertEqual(len(rec["footnotes"]), 4)
        self.assertTrue(rec["footnotes"][0].startswith("[각주 1] 청구인의 소정급여 일수는 210일"), rec["footnotes"][0])
        self.assertEqual(rec["claimant"], SYN_CLAIMANT)
        self.assertEqual(rec["official_url"],
                         "https://www.law.go.kr/DRF/lawService.do?OC=&target=eiac&ID=11327&type=HTML")

    def test_ru3_iaciac_detail_normalization(self):
        import fetch_rulings as fr
        rec = _record("iaciac", "12699")
        self.assertEqual(rec["agency_name"], "산업재해보상보험재심사위원회")
        self.assertEqual(rec["case_no"], "2010-2071호")
        self.assertEqual(rec["case_name"], "요양불승인처분취소")               # `2010재결 제2071호 ` 접두사 제거(D8)
        self.assertEqual(rec["title"], "산업재해보상보험재심사위원회 2010-2071호 — 요양불승인처분취소")
        self.assertEqual((rec["decided_at"], rec["decided_year"]), ("2010.08.27", 2010))   # 0 채움
        self.assertEqual(rec["category"], "업무상 재해 여부 관련 > 업무상 사고 > 작업시간 중 사고")
        self.assertEqual(rec["summary_label"], "쟁점")
        self.assertEqual(rec["doc_kind"], "데이터 개방")
        self.assertEqual(rec["footnotes"], [])
        # 날짜 파싱 실패는 원문 유지 + 연도 None(낡았다고 단정하지 않는다)
        self.assertEqual(fr.format_date("2010.8"), ("2010.8", None))
        self.assertEqual(fr.format_date("2019.02.31"), ("2019.02.31", None))          # 달력에 없는 날(CodeRabbit #155)
        root3 = _root("iaciac_detail_12699.xml")
        with self.assertRaises(fr.SerialMismatch):                                    # 다른 결정문이 오면 저장하지 않는다
            fr.normalize_record(root3, "iaciac", "99999")
        self.assertEqual(fr.format_date("2019.10.23"), ("2019.10.23", 2019))
        self.assertEqual(fr.format_date("20100827"), ("2010.08.27", 2010))
        self.assertEqual(fr.strip_ruling_prefix("2010재결 제348호 유족급여부지급처분취소"), "유족급여부지급처분취소")
        self.assertEqual(fr.strip_ruling_prefix("2010 재결 제 348 호  X"), "X")
        self.assertEqual(fr.derive_case_no("iaciac", "2012재결 제3198호 요양불승인처분취소"), "2012-3198호")
        self.assertEqual(fr.derive_case_no("eiac", "2019재결 제117호 X"), "2019재결 제117호")
        self.assertEqual(fr.derive_case_no("iaciac", "요양불승인처분취소"), "")
        # 사건번호가 빈 상세(실측 iaciac 13063)는 `사건` 접두사로 번호를 만든다; 깨진 의결일자(6427 `202.0.0`)는 **의결 연도
        # 미상**이다 — 재결 번호의 연도는 접수 연도라 143/1,050건이 다음 해 의결(CodeRabbit #155). 머리글엔 접수 연도만 참고로
        root2 = _root("iaciac_detail_12699.xml")
        root2.find("사건번호").text = ""
        root2.find("의결일자").text = "202.0.0"
        rec2 = fr.normalize_record(root2, "iaciac", "12699")
        self.assertEqual(rec2["case_no"], "2010-2071호")
        self.assertEqual((rec2["decided_at"], rec2["decided_year"]), ("미상(2010년 접수)", None))
        import pinecone_upload_rulings as up
        with tempfile.TemporaryDirectory() as tmp:
            pth = os.path.join(tmp, "12699_x.md")
            with open(pth, "w", encoding="utf-8") as f:
                f.write(fr.to_markdown(rec2))
            doc2 = up.parse_doc(pth)
            self.assertIsNone(doc2["decided_year"])                                   # --exclude-before가 제외하지 않는다
            self.assertIn("· 의결 미상(2010년 접수) ·", up.build_header(doc2))
        self.assertEqual(fr.case_no_ascii("2019재결 제117호"), "2019jg117")
        self.assertEqual(fr.case_no_ascii("2010-2071호"), "2010-2071")
        # 필수 필드 부재 → MissingField
        root = _root("iaciac_detail_12699.xml")
        root.remove(root.find("이유"))
        with self.assertRaises(fr.MissingField):
            fr.normalize_record(root, "iaciac", "12699")

    def test_ru4_clean_known_tags_only(self):
        import fetch_rulings as fr
        c = fr.clean_ruling_text
        self.assertEqual(c('주문과 같다.<span style="display:none;">○ 사건번호 및 사건명 2019재결</span> 끝'), "주문과 같다. 끝")
        self.assertEqual(c("…하였다.<각주>1</각주>다. 이에 청구인은"), "…하였다.[각주 1]\n다. 이에 청구인은")
        self.assertEqual(c("동료<각주>2</각주>의 소정근로시간"), "동료[각주 2]의 소정근로시간")
        self.assertEqual(c('<img src="http://x/fl?flSeq=1" alt="1번째 이미지"></img>'), "[이미지 생략: 1번째 이미지]")
        self.assertEqual(c("<근로계약서 발췌>"), "<근로계약서 발췌>")           # 태그가 아닌 캡션은 보존
        self.assertEqual(c("</img>\n\n1. 사건개요"), "1. 사건개요")                 # 홀로 남은 닫는 태그(실측 18건)
        self.assertEqual(c("SCREW HORIZON<ALL>×4개"), "SCREW HORIZON<ALL>×4개")   # 꺾쇠 내용은 태그가 아니다
        self.assertFalse(fr.RESIDUAL_TAG_RE.search("HORIZON<ALL>×4개 <근로계약서 발췌>"))
        self.assertTrue(fr.RESIDUAL_TAG_RE.search("a </img> b"))
        self.assertEqual(c("가<br/>나<p>다</p>라 &amp; 마"), "가\n나\n다\n라 & 마")
        self.assertEqual(c("<b>굵게</b> <a href='x'>링크</a>"), "굵게 링크")
        # 실제 fixture 정제 뒤 잔존 ASCII 태그 0
        rec = _record("eiac", "11327")
        self.assertFalse(fr.RESIDUAL_TAG_RE.search(rec["reasoning"]), rec["reasoning"][:200])
        self.assertIn("[이미지 생략: 1번째 이미지]", rec["reasoning"])
        self.assertIn("<근로계약서 발췌>", rec["reasoning"])
        self.assertNotIn("display:none", rec["claim"])

    def test_ru5_pii_scan_and_redaction(self):
        import fetch_rulings as fr
        rec = _record("iaciac", "12699")
        self.assertEqual(fr.scan_pii(rec), [])                               # 원본 fixture 0건
        bad = dict(rec, claimant="번호880101-1234567 홍길동", respondent="연락 010-1234-5678",
                   reasoning=rec["reasoning"] + " 메일 a.b@example.com")
        found = fr.scan_pii(bad)
        self.assertEqual(sorted(f["pattern"] for f in found), ["이메일", "주민등록번호", "휴대전화"], found)
        self.assertTrue(all("snippet" in f and f["field"] for f in found))
        # 가림 목록은 업로더가 청킹 시점에 적용한다(§3.5) — 본문뿐 아니라 머리글·메타 필드도(Codex #155)
        import pinecone_upload_rulings as up
        _, doc, chunks, _ = _doc_and_chunks("iaciac", "12699", redactions=["기계기능공", "작업시간 중 사고", "기각한다"])
        joined = "\n".join(c["text"] for c in chunks)
        self.assertNotIn("기계기능공", joined)
        self.assertNotIn("작업시간 중 사고", joined)                          # 머리글의 분류도 가려진다
        self.assertIn("***", joined)
        red = up.redact_doc(doc, ["기각한다", "작업시간 중 사고"])
        self.assertNotIn("기각한다", red["disposition"])
        self.assertNotIn("작업시간 중 사고", up.build_header(red))
        self.assertEqual(red["path"], doc["path"])
        self.assertIs(up.redact_doc(doc, None), doc)


class ChunkingTest(unittest.TestCase):
    """RU6~RU9 — md 왕복·소제목 청킹·관계법령 제외·ID·원장."""

    def test_ru6_markdown_roundtrip_excludes_claimant_and_claim(self):
        import fetch_rulings as fr
        import pinecone_upload_rulings as up
        for agency, serial in (("eiac", "11327"), ("iaciac", "12699")):
            rec, doc, chunks, _ = _doc_and_chunks(agency, serial)
            self.assertEqual(doc["agency"], agency)
            self.assertEqual(doc["serial"], serial)
            self.assertEqual(doc["case_no"], rec["case_no"])
            self.assertEqual(doc["case_name"], rec["case_name"])
            self.assertEqual(doc["title"], rec["title"])
            self.assertEqual(doc["decided_at"], rec["decided_at"])
            self.assertEqual(doc["decided_year"], rec["decided_year"])
            self.assertEqual(doc["category"], rec["category"])
            self.assertEqual(doc["url"], rec["official_url"])
            self.assertEqual(doc["claimant"], SYN_CLAIMANT)                  # md에는 있다
            joined = "\n".join(c["text"] for c in chunks)
            self.assertNotIn(SYN_CLAIMANT, joined)                           # 청크에는 없다(D3·R6)
            self.assertNotIn("(남자, 40세", joined)
            self.assertNotIn(rec["claim"][:25], joined)                      # 청구취지 제외
            self.assertTrue(all(c["text"].startswith("[") for c in chunks))
        # 파일명 규약·court 파서 호환
        self.assertTrue(fr.output_path(rec).endswith(os.path.join("iaciac", "12699_2010-2071.md")))
        self.assertIn("| --- | --- |", fr.to_markdown(rec))

    def test_ru7_sections_and_law_text_exclusion(self):
        import pinecone_upload_rulings as up
        # iaciac 12699 — 관계법령 소절(조문 전문) 제외, 실제 소절(사실관계·의학적 소견·판 단) 유지
        rec, doc, chunks, st = _doc_and_chunks("iaciac", "12699")
        self.assertEqual(st["tops"], ["사건개요", "청구인 주장", "원처분기관 의견", "원처분기관 처분내용",
                                      "관계법령, 사실관계 및 판단", "결 론"], st["tops"])
        sections = {c["section"] for c in chunks}
        self.assertTrue(any("/ 사실관계" in s for s in sections), sections)
        self.assertTrue(any("/ 의학적 소견" in s for s in sections), sections)
        self.assertTrue(any("/ 판 단" in s for s in sections), sections)
        self.assertFalse(any(re.search(r"관계법령(\s*·|$)", s) for s in sections), sections)
        self.assertFalse(st["image_only"])
        joined = "\n".join(c["text"] for c in chunks)
        for law_text in ("사업주가 제공한 교통수단", "시설물 등의 결함이나 관리소홀", "유해ㆍ위험 요인을 취급하거나 그에 노출되어 발생한 질병"):
            self.assertNotIn(law_text, joined, law_text)                     # 당시 조문 전문은 임베딩하지 않는다
        self.assertGreaterEqual(st["excluded_chars"], 2000, st)
        self.assertEqual(st["excluded_titles"], ["이유 — 관계법령, 사실관계 및 판단 / 관계법령"])
        self.assertFalse(st["fallback"])
        self.assertEqual(st["residual_tags"], 0)
        header = "[산업재해보상보험재심사위원회 2010-2071호 · 의결 2010.08.27 · 업무상 재해 여부 관련 > 업무상 사고 > 작업시간 중 사고]"
        self.assertTrue(all(c["text"].splitlines()[0] == header for c in chunks))
        self.assertEqual(chunks[0]["section"], "쟁점·주문")
        self.assertIn("쟁점: 2008. 10. 22.", chunks[0]["text"])
        self.assertIn("주문: 청구인의 재심사청구를 기각한다.", chunks[0]["text"])
        self.assertTrue(all(len(c["text"]) <= up.HEADER_MAX + up.CHUNK_MAX + up.CHUNK_OVERLAP + 2 for c in chunks))
        self.assertTrue(all(isinstance(c["chunk_index"], int) for c in chunks))
        self.assertEqual([c["chunk_index"] for c in chunks], list(range(len(chunks))))

        # eiac 11327 — `4. 관계법령` 절과 `6. … / 가. 관계법령의 내용` 소절 제외, 판단·결론·각주 유지, 각주 뒤 소항목
        rec, doc, chunks, st = _doc_and_chunks("eiac", "11327")
        self.assertEqual(st["tops"], ["사건개요", "청구인 주장", "피청구인 주장", "관계법령", "인정사실",
                                      "이 사건 처분의 위법ㆍ부당 여부", "결론"], st["tops"])
        sections = {c["section"] for c in chunks}
        self.assertNotIn("이유 — 관계법령", sections)
        self.assertFalse(any(s.endswith("관계법령의 내용") for s in sections), sections)
        self.assertTrue(any("이 사건 처분의 위법ㆍ부당 여부 / 판단" in s for s in sections), sections)
        self.assertTrue(any("결론" in s for s in sections), sections)
        self.assertIn("각주", sections)
        self.assertEqual(st["excluded_titles"], ["이유 — 관계법령", "이유 — 이 사건 처분의 위법ㆍ부당 여부 / 관계법령의 내용"])
        joined = "\n".join(c["text"] for c in chunks)
        self.assertIn("[각주 1]", joined)
        intro = "\n".join(c["text"] for c in chunks if "사건개요" in c["section"])
        self.assertIn("\n다. 이에", intro)                                    # 각주 뒤 같은 줄 소항목이 분리됐다
        self.assertIn("[이미지 생략: 1번째 이미지]", joined)
        self.assertEqual(chunks[0]["section"], "개요·주문")
        self.assertFalse(st["fallback"])
        # 패킹 — 작은 절이 머리글만 단 청크로 남지 않는다(300자 미만 본문은 마지막 조각 정도)
        bodies = [len(c["text"]) - len(c["text"].splitlines()[0]) for c in chunks]
        self.assertLessEqual(sum(1 for b in bodies if b < 200), 2, bodies)

    def test_ru7c_image_only_and_packing(self):
        import pinecone_upload_rulings as up
        rec, doc, chunks, st = _doc_and_chunks("iaciac", "12699")
        doc_img = dict(doc, reasoning="[이미지 생략: 1번째 이미지]\n[이미지 생략: 2번째 이미지]")
        chunks2, st2 = up.chunk_doc(doc_img)
        self.assertTrue(st2["image_only"])
        self.assertFalse(st2["fallback"])                                    # 이미지 전용은 폴백 통계에 넣지 않는다
        self.assertEqual([c["section"] for c in chunks2][:1], ["쟁점·주문"])  # 쟁점·주문만 적재
        packs = up.pack_sections([up.Section("원처분기관 의견", None, ["짧은 의견"]), up.Section("원처분기관 처분내용", None, ["처분"]),
                                  up.Section("관계법령, 사실관계 및 판단", "판 단", ["긴 판단 " * 200]), up.Section("결 론", None, ["기각"])])
        self.assertEqual([lb for _, lb in packs], ["이유 — 원처분기관 의견 · 원처분기관 처분내용",
                                                   "이유 — 관계법령, 사실관계 및 판단 / 판 단", "이유 — 결 론"])

    def test_ru7b_heading_rules(self):
        import pinecone_upload_rulings as up
        text = ("1. 사건개요\n내용\n가. 청구인 전○○은 회사에서 일했다 어쩌구 저쩌구 길게 적은 문장이다\n"
                "2. 관계법령\n1. 업무상 사고\n가. 근로자가 근로계약에 따른 업무나 그에 따르는 행위를 하던 중 발생한 사고\n"
                "나. 사업주가 제공한 시설물 등을 이용하던 중 그 시설물 등의 결함으로 발생한 사고\n6. 천재지변 등 돌발 사고에 따른 긴급피난\n"
                "3. 판단\n판단 내용\n4. 결론\n기각")
        secs = up.split_reasoning(text)
        labels = [(s.label, s.excluded) for s in secs]
        self.assertEqual(labels, [("이유 — 사건개요", False), ("이유 — 관계법령", True), ("이유 — 판단", False), ("이유 — 결론", False)], labels)
        self.assertIn("긴급피난", secs[1].text)                               # 관계법령 안의 `6.`은 절이 아니다(순차 아님)
        self.assertIn("가. 청구인 전○○", secs[0].text)                        # 긴 문장형 `가.`는 소절이 아니다
        # 소제목이 없으면 통째로
        self.assertEqual([(s.label, s.excluded) for s in up.split_reasoning("그냥 본문\n둘째 줄")], [("이유 — 본문", False)])
        # 짧은 제목·어휘 조건
        self.assertTrue(up._is_heading_title("결 론"))
        self.assertTrue(up._is_heading_title("이 사건 처분의 위법ㆍ부당 여부"))
        self.assertFalse(up._is_heading_title("위 '1. 사건개요'의 '가'부터 '라'까지의 기재 내용과 같다."))
        self.assertTrue(up._is_excluded_title("관계법령의 내용"))
        self.assertTrue(up._is_excluded_title("관계법령:"))                             # 끝 콜론(CodeRabbit #155)
        self.assertTrue(up._is_excluded_title("관련 법령."))
        self.assertFalse(up._is_excluded_title("관계법령, 사실관계 및 판단"))
        # 실측 어휘 — 276건에서 빠져 있던 상위 소제목
        self.assertTrue(up._is_heading_title("원처분기관 처분 및 심사기관 결정이유"))
        self.assertTrue(up._is_heading_title("이 사건 재심사청구의 적법 여부"))
        # 제외 절(관계법령)에서 빠져나오는 소제목은 어휘가 필수 — "2. 업무상 질병"은 짧지만 조문 목록이다
        self.assertFalse(up._is_heading_title("업무상 질병", strict=True))
        self.assertTrue(up._is_heading_title("업무상 질병"))
        text2 = ("1. 사건개요\n내용\n2. 관계법령\n1. 업무상 사고\n3. 업무상 질병\n가. 유해요인에 노출되어 발생한 질병\n"
                 "3. 판단\n판단 내용\n4. 결론\n기각")
        secs2 = up.split_reasoning(text2)
        self.assertEqual([(s.label, s.excluded) for s in secs2],
                         [("이유 — 사건개요", False), ("이유 — 관계법령", True), ("이유 — 판단", False), ("이유 — 결론", False)])
        self.assertIn("업무상 질병", secs2[1].text)                         # 조문 목록 "3. 업무상 질병"은 제외 구간을 끊지 못한다
        # 번호 중복·건너뜀(실측 20건): "6. 의학적 소견" 뒤 "6. 판단", "5. 인정사실" 뒤 "7. 결론"은 어휘가 맞아 소제목이다
        text3 = "1. 사건개요\n내용\n2. 청구인 주장\n주장\n4. 결론\n기각\n7. 인정사실\n사실"
        self.assertEqual([s.top for s in up.split_reasoning(text3)], ["사건개요", "청구인 주장", "결론"])   # +2는 어휘로, +3은 아니다
        text4 = "1. 사건개요\n내용\n2. 의학적 소견\n소견\n2. 판단\n판단\n4. 결론\n기각\n6. 그 밖에 노동부령으로 정하는 사항\n법문"
        self.assertEqual([s.top for s in up.split_reasoning(text4)], ["사건개요", "의학적 소견", "판단", "결론"])
        self.assertIn("노동부령", up.split_reasoning(text4)[-1].text)                 # 어휘 없는 +2는 소제목이 아니다

    def test_ru8_vector_id_and_ledger_regex(self):
        import pinecone_upload_rulings as up
        self.assertEqual(up.make_vector_id("eiac", "11327", 0), "ruling_eiac_11327_chunk_0")
        self.assertTrue(up._LEDGER._id_re_for("eiac_11327").match("ruling_eiac_11327_chunk_0"))
        self.assertFalse(up._LEDGER._id_re_for("eiac_11327").match("ruling_eiac_11327_000"))
        self.assertFalse(up._LEDGER._id_re_for("eiac_11327").match("ruling_eiac_113270_chunk_0"))
        self.assertTrue(up._LEDGER._group_re.match("iaciac_12699"))
        for bad in ("eiac-11327", "nlrc_1", "ruling_eiac_1", "eiac_"):
            self.assertFalse(up._LEDGER._group_re.match(bad), bad)
        self.assertEqual(up.NAMESPACE, "laborlaw-v2")
        self.assertEqual(up.SOURCE_TYPE, "ruling")

    def test_ru9_duplicate_case_no_distinct_groups(self):
        import fetch_rulings as fr
        import pinecone_upload_rulings as up
        rec = _record("iaciac", "12699")
        ids: set[str] = set()
        groups: set[str] = set()
        with tempfile.TemporaryDirectory() as tmp:
            for serial in ("12699", "12700"):                                # 같은 사건번호, 다른 일련번호
                r = dict(rec, serial=serial, official_url=fr.official_url("iaciac", serial))
                path = os.path.join(tmp, f"{serial}_x.md")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(fr.to_markdown(r))
                doc = up.parse_doc(path)
                chunks, _ = up.chunk_doc(doc)
                groups.add(f"{doc['agency']}_{doc['serial']}")
                new = {c["vector_id"] for c in chunks}
                self.assertFalse(ids & new)
                ids |= new
        self.assertEqual(groups, {"iaciac_12699", "iaciac_12700"})


class WiringTest(unittest.TestCase):
    """RU10~RU16 — rag 집합·라벨 G5·인용 검증·pipeline·우선순위·stale."""

    def test_ru10_public_sources_include_ruling(self):
        from app.core import rag
        self.assertIn("ruling", rag.POOL_PUBLIC_SOURCES)
        self.assertIs(rag.LEGAL_PROMOTE_SOURCES, rag.POOL_PUBLIC_SOURCES)
        hit = {"id": "ruling_eiac_1_chunk_0", "source_type": "ruling", "title": "t", "section": "s",
               "content": "c", "score": 0.5}
        self.assertTrue(rag._is_public_source(hit))
        self.assertTrue(rag._is_legal_source(hit))
        self.assertIs(rag._diversity_class_of(hit), rag._is_legal_source)
        self.assertEqual(rag.POOL_PUBLIC_SOURCES, {"precedent", "interpretation", "regulation", "ruling"})

    def test_ru11_label_both_sides(self):
        from app.core.rag import format_pinecone_hits
        html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
        m = re.search(r"ruling:\s*'([^']+)'", html)
        self.assertIsNotNone(m, "index.html renderSources labels에 ruling 없음")
        text, meta = format_pinecone_hits([{"id": "ruling_eiac_1_chunk_0", "source_type": "ruling",
                                            "title": "고용보험심사위원회 2019재결 제117호 — 사건명", "section": "개요·주문",
                                            "content": "[머리글]\n본문", "score": 0.9, "case_no": "2019재결 제117호"}])
        self.assertTrue(text.startswith(f"[{m.group(1)}] "), text[:40])
        self.assertEqual(m.group(1), "재결례")
        self.assertEqual(meta[0]["case_no"], "2019재결 제117호")

    @staticmethod
    def _hits():
        return [
            {"source_type": "ruling", "case_no": "2019재결 제117호",
             "title": "고용보험심사위원회 2019재결 제117호 — 고용보험 구직급여일액 결정 처분 변경 청구",
             "chunk_text": "[고용보험심사위원회 2019재결 제117호 · 의결 2019.10.23 · 수급자격에 관한 사례]\n본문"},
            {"source_type": "ruling", "case_no": "2010-2071호",
             "title": "산업재해보상보험재심사위원회 2010-2071호 — 요양불승인처분취소",
             "chunk_text": "[산업재해보상보험재심사위원회 2010-2071호 · 의결 2010.08.27 · 업무상 재해 여부 관련]\n본문"},
            {"title": "판례A", "chunk_text": "대법원 2023다302838 판결 참조"},
        ]

    def test_ru12_citation_patterns(self):
        from app.core import citation_validator as cv
        hits = self._hits()
        rulings = cv.extract_rulings_from_hits(hits)
        self.assertEqual(rulings["2019재결제117호"]["agencies"], ["eiac"])
        self.assertEqual(rulings["2010-2071호"]["agencies"], ["iaciac"])
        self.assertEqual(rulings["2010재결제2071호"]["alias_of"], "2010-2071호")   # iaciac 별칭
        self.assertNotIn("alias_of", rulings["2019재결제117호"])
        precs = cv.extract_precedents_from_hits(hits)
        self.assertEqual(set(precs), {"2023다302838"})                          # 재결 번호 조각이 판례 키로 새지 않는다

        def check(answer: str, rulings_=None):
            return cv.validate_response_citations(answer, precs, {}, rulings if rulings_ is None else rulings_)

        # 양성
        r = check("고용보험심사위원회 2019재결 제117호(2019. 10. 23. 의결)에 따르면")
        self.assertEqual((r["valid"], r["hallucinated"]), (["2019재결제117호"], []))
        r = check("산업재해보상보험재심사위원회 2010-2071호(2010. 8. 27. 의결)와 재심사위원회 2010-2071 재결")
        self.assertEqual((r["valid"], r["hallucinated"]), (["2010-2071호", "2010-2071호"], []))
        r = check("2010재결 제2071호에서는")                                    # 별칭, 기관 미기재 → valid
        self.assertEqual((r["valid"], r["hallucinated"]), (["2010재결제2071호"], []))
        r = check("고용보험심사위원회 2010재결 제2071호에서는")                  # 기관 불일치 → hallucinated
        self.assertEqual((r["valid"], r["hallucinated"]), ([], ["2010재결제2071호"]))
        # 음성 — 고시·공고 번호와 날짜·문맥 없는 번호는 검증 대상이 아니다(total_cited 불변)
        for benign in ("2026년 적용 고시(2025-124호)", "(고용노동부 고시 2018-23호)", "고용노동부고시 제2026-67호",
                       "2024-01-15 기준", "2010-2071호", "고용노동부 공고 2021-244호", "25-124호",
                       "산재재심사위원회에 2026-11-08 재심사청구를 접수했습니다",          # ISO 날짜(Codex #155)
                       "재심사위원회 결정일 2026-11-08", "재심사위원회(2026. 11. 08.)"):
            r = check(benign)
            self.assertEqual((r["total_cited"], r["hallucinated"]), (0, []), benign)
        r = check("고용보험심사위원회 2019재결 제999호")
        self.assertEqual(r["hallucinated"], ["2019재결제999호"])
        # 마스킹 — `…재심사위원회 2015-1987호 2015. 8. 27.`의 `1987호 2015`가 판례가 되지 않는다(검증·추출 양쪽)
        s = "산업재해보상보험재심사위원회 2015-1987호 2015. 8. 27. 의결"
        self.assertEqual([m.group(0) for m in cv._PREC_PATTERN.finditer(cv._mask_ruling_spans(s))], [])
        self.assertEqual([m.group(0) for m in cv._PREC_PATTERN.finditer(s)], ["1987호 2015"])   # 가리지 않으면 잡힌다
        r = check(s)
        self.assertEqual((r["valid"], r["hallucinated"]), ([], ["2015-1987호"]))                  # 재결로만 판정
        self.assertEqual(set(cv.extract_precedents_from_hits([{"title": "x", "chunk_text": s}])), set())
        # 가림은 번호 구간만 — 기관명과 번호 사이의 판례는 살아 있어야 한다(Codex #155)
        s2 = "산재재심사위원회는 대법원 2020두12345 및 2010-2071호를 참고했습니다."
        self.assertIn("2020두12345", cv._mask_ruling_spans(s2))
        self.assertNotIn("2010-2071호", cv._mask_ruling_spans(s2))
        self.assertEqual(set(cv.extract_precedents_from_hits([{"title": "x", "chunk_text": s2}])), {"2020두12345"})
        r = cv.validate_response_citations(s2, {"2020두12345": {}}, {}, rulings)
        self.assertEqual((sorted(r["valid"]), r["hallucinated"]), (["2010-2071호", "2020두12345"], []))
        self.assertEqual(cv._ADMIN_PATTERN.findall("2019재결 제117호 2010-2071호"), [])
        # 3인자 호출 호환(기존 test_offline_units) — 재결 검증은 건너뛰되 마스킹은 한다
        r = cv.validate_response_citations("재심사위원회 2010-2071호 대법원 2023다302838", precs, {})
        self.assertEqual((r["valid"], r["hallucinated"]), (["2023다302838"], []))
        # 인용 목록 — 머리글·재결례 블록·기관명 포함·별칭 미표시
        listing = cv.build_available_citations_text(hits)
        self.assertIn("[인용 가능한 판례·행정해석·재결례 목록]", listing)
        self.assertIn("재결례(기관명과 함께 인용):", listing)
        self.assertIn("  - 고용보험심사위원회 2019재결 제117호 (출처:", listing)
        self.assertIn("  - 산업재해보상보험재심사위원회 2010-2071호 (출처:", listing)
        self.assertNotIn("2010재결 제2071호", listing)
        # 별칭 충돌 — eiac 실키가 있으면 iaciac 별칭이 덮어쓰지 않는다(실키 우선, 순서 무관)
        for order in (0, 1):
            pair = [{"source_type": "ruling", "case_no": "2010재결 제348호", "title": "고용보험심사위원회 2010재결 제348호 — A",
                     "chunk_text": "[고용보험심사위원회 2010재결 제348호 · 의결 2010.05.01 · 기타]\n"},
                    {"source_type": "ruling", "case_no": "2010-348호", "title": "산업재해보상보험재심사위원회 2010-348호 — B",
                     "chunk_text": "[산업재해보상보험재심사위원회 2010-348호 · 의결 2010.03.11 · 기타]\n"}]
            if order:
                pair.reverse()
            rr = cv.extract_rulings_from_hits(pair)
            self.assertEqual(rr["2010재결제348호"]["agencies"], ["eiac"], order)
            self.assertNotIn("alias_of", rr["2010재결제348호"])
            self.assertEqual(rr["2010-348호"]["agencies"], ["iaciac"])
        # 혼합 기관 문맥 — 번호에 가까운 기관으로 판정한다(CodeRabbit #155)
        r = check("산업재해보상보험재심사위원회와 고용보험심사위원회 2019재결 제117호에 따르면")
        self.assertEqual((r["valid"], r["hallucinated"]), (["2019재결제117호"], []))
        r = check("고용보험심사위원회가 아니라 산업재해보상보험재심사위원회 2010-2071호")
        self.assertEqual((r["valid"], r["hallucinated"]), (["2010-2071호"], []))
        # 기관 미확인 번호 — 재결례 hit 본문의 선례 인용은 그 hit의 기관을 물려받고, 상담글 본문의 번호는 미확인이다
        body_hits = [dict(hits[0], chunk_text=hits[0]["chunk_text"] + "\n위원회는 2018재결 제45호에서 같은 취지로 판단했다"),
                     {"source_type": "qa", "title": "상담글", "chunk_text": "심사위에서 2017재결 제9호가 있다고 들었어요"}]
        rr = cv.extract_rulings_from_hits(body_hits)
        self.assertEqual(rr["2018재결제45호"]["agencies"], ["eiac"])
        self.assertEqual(rr["2017재결제9호"]["agencies"], [])
        listing2 = cv.build_available_citations_text(body_hits)
        self.assertIn("고용보험심사위원회 2018재결 제45호", listing2)
        self.assertNotIn("2017재결 제9호", listing2)                                  # 기관 미확인은 목록에 없다
        r = cv.validate_response_citations("고용보험심사위원회 2017재결 제9호", precs, {}, rr)
        self.assertEqual((r["valid"], r["hallucinated"]), ([], ["2017재결제9호"]))     # 기관을 붙이면 확인 불가 → 환각
        r = cv.validate_response_citations("2017재결 제9호에서는", precs, {}, rr)
        self.assertEqual((r["valid"], r["hallucinated"]), (["2017재결제9호"], []))      # 기관 없이 쓰면 존재는 인정
        self.assertEqual(cv.resolve_ruling_aliases(["2010재결제2071호", "2019재결제117호", "2010-2071호"], rulings),
                         ["2010-2071호", "2019재결제117호"])
        # 교정 문구 — 머리말만 바뀌고 라벨은 그대로(test_kin_accuracy K12)
        self.assertIn("판례·재결 번호", cv._CORRECTION_TEXT["hallucinated"][0])
        self.assertEqual(cv._CORRECTION_TEXT["hallucinated"][1], "확인되지 않은 판례 번호")

    def test_ru13_bm25_path_hit_without_case_no(self):
        from app.core import citation_validator as cv
        hit = {"source_type": "ruling", "title": "산업재해보상보험재심사위원회 2010-2071호 — 요양불승인처분취소",
               "chunk_text": "[산업재해보상보험재심사위원회 2010-2071호 · 의결 2010.08.27 · 업무상 재해 여부 관련]\n본문"}
        rulings = cv.extract_rulings_from_hits([hit])
        self.assertEqual(rulings["2010-2071호"]["agencies"], ["iaciac"])
        self.assertIn("2010재결제2071호", rulings)
        hit_ei = {"source_type": "ruling", "title": "고용보험심사위원회 2019재결 제117호 — X",
                  "chunk_text": "[고용보험심사위원회 2019재결 제117호 · 의결 2019.10.23 · 수급자격에 관한 사례]\n본문"}
        self.assertEqual(cv.extract_rulings_from_hits([hit_ei])["2019재결제117호"]["agencies"], ["eiac"])

    def test_ru14_pipeline_wiring(self):
        from app.core import pipeline
        from app.templates import prompts
        self.assertTrue(pipeline.uses_ruling([{"source_type": "qa"}, {"source_type": "ruling"}]))
        self.assertFalse(pipeline.uses_ruling([{"source_type": "precedent"}, None]))
        self.assertFalse(pipeline.uses_ruling(None))
        src = (ROOT / "app" / "core" / "pipeline.py").read_text(encoding="utf-8")
        attach = [src.index(f"system_prompt = system_prompt + {name}")
                  for name in ("TEXTBOOK_CITATION_RULES", "COUNSEL_CITATION_RULES", "RULING_CITATION_RULES")]
        self.assertEqual(attach, sorted(attach))
        self.assertLess(attach[2], src.index("system_prompt + WAGE_CALC_RULES + ANSWER_ACCURACY_RULES"))
        self.assertNotIn("## 재결례 인용 규칙", pipeline.SYSTEM_PROMPT_TEMPLATE)   # 인라인 분기(pipeline)
        self.assertNotIn("## 재결례 인용 규칙", prompts.CONSULTATION_SYSTEM_PROMPT)
        self.assertIn("## 재결례 인용 규칙", prompts.RULING_CITATION_RULES)
        self.assertNotRegex(prompts.RULING_CITATION_RULES, r"20\d{2}\s*재결\s*제\s*\d+\s*호|20\d{2}-\d+호")   # 자리표시만
        self.assertIn("YYYY재결 제N호", prompts.RULING_CITATION_RULES)
        self.assertLess(len(prompts.RULING_CITATION_RULES), 520)
        # validate_response_citations 호출은 4인자(available_rulings)
        tree = ast.parse(src)
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", None) == "validate_response_citations"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0].args) + len(calls[0].keywords), 4)
        self.assertIn("extract_rulings_from_hits(whitelist_hits)", src)
        self.assertIn("resolve_ruling_aliases(citation_check[\"valid\"], available_rulings)", src)
        # 파이프라인 경로 그대로: precedent_meta → _citation_source_hits → 화이트리스트 → 검증(빈 사전이면 회귀)
        from app.core import citation_validator as cv
        meta = [{"title": "산업재해보상보험재심사위원회 2010-2071호 — 요양불승인처분취소", "source_type": "ruling",
                 "case_no": "2010-2071호", "chunk_text": "[산업재해보상보험재심사위원회 2010-2071호 · 의결 2010.08.27 · X]\n본문",
                 "section": "쟁점·주문", "score": 0.9}]
        wl = pipeline._citation_source_hits(None, meta, None, None, None)
        rulings = cv.extract_rulings_from_hits(wl)
        r = cv.validate_response_citations("산업재해보상보험재심사위원회 2010-2071호(2010. 8. 27. 의결)에서", {}, {}, rulings)
        self.assertEqual((r["valid"], r["hallucinated"]), (["2010-2071호"], []))
        self.assertIn('conv_metadata["rag_sources"]', src)
        self.assertIn("관련 판례·재결례 (법제처 국가법령정보센터)", src)
        from app.core import storage
        self.assertNotIn("rag_sources", storage.PUBLIC_EXCLUDE_KEYS)       # 관측 키 — 게시판 제외 사유가 아니다

    def test_ru15_conflict_note_mentions_rulings(self):
        from app.core.conflict_resolver import annotate_source_priority
        note = annotate_source_priority("재결례는 근로기준법 제60조를…", "근로기준법 제60조(연차 유급휴가) …", None)
        self.assertIn("재결례", note)
        self.assertIn("3. 행정해석·판정사례·재결례", note)

    def test_ru16_stale_rule_annotates_not_drops_ruling(self):
        from app.core.stale_rules import filter_stale_hits
        hits = [{"id": "ruling_eiac_1_chunk_0", "source_type": "ruling", "title": "t",
                 "content": "일용근로자는 신청일 이전 1개월 근로일수가 10일 미만이어야 한다"},
                {"id": "qa_1", "source_type": "qa", "title": "q", "content": "일용근로자 10일 미만이면 됩니다"}]
        with mock.patch.dict(os.environ, {"STALE_FILTER": "on"}):
            kept, ids = filter_stale_hits(hits)
        self.assertEqual(ids, ["daily_10days"])
        self.assertEqual([h["id"] for h in kept], ["ruling_eiac_1_chunk_0"])  # 상담글은 제외, 재결례는 주석
        self.assertTrue(kept[0]["content"].startswith("[구 기준 주의"))


class OperationsTest(unittest.TestCase):
    """RU18~RU20 — 인증 오류 경로·BM25 코퍼스 패턴 스캔·그룹 삭제."""

    def test_ru18_auth_error_stops_without_failed_record(self):
        import fetch_rulings as fr
        auth_xml = b'<?xml version="1.0" encoding="UTF-8"?><Response><result>FAIL</result><message>x</message></Response>'
        list_xml = (FIX / "eiac_list_p1.xml").read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            patches = dict(OUTPUT_DIR=tmp, PROGRESS_FILE=os.path.join(tmp, "_progress.json"),
                           PII_REPORT_FILE=os.path.join(tmp, "_pii_report.json"))
            with mock.patch.multiple(fr, **patches), mock.patch.object(fr.time, "sleep", lambda s: None), \
                    mock.patch.dict(os.environ, {"LAW_API_KEY": "fake"}):
                with mock.patch.object(fr._session, "get", lambda url, params=None, timeout=None: _FakeResp(auth_xml)):
                    rc = fr.main(["--agency", "eiac"])
                self.assertEqual(rc, 2)
                progress = fr.load_progress()
                self.assertEqual(progress["eiac"]["failed"], {})
                self.assertEqual(progress["eiac"]["fetched"], {})

                detail_tpl = (FIX / "eiac_detail_11327.xml").read_text(encoding="utf-8")

                def detail_for(serial: str, body: str = detail_tpl) -> bytes:
                    return body.replace("<결정문일련번호>11327</결정문일련번호>",
                                        f"<결정문일련번호>{serial}</결정문일련번호>").encode("utf-8")

                # HTTP 500 상세 → failed에 클래스명+상태만, 다음 실행에 재시도 대상
                def fake_get(url, params=None, timeout=None):
                    if (params or {}).get("ID"):
                        return _FakeResp(b"boom", status=500)
                    return _FakeResp(list_xml)
                with mock.patch.object(fr._session, "get", fake_get):
                    rc = fr.main(["--agency", "eiac", "--limit", "1"])
                self.assertEqual(rc, 0)
                progress = fr.load_progress()
                self.assertEqual(len(progress["eiac"]["failed"]), 1)
                reason = next(iter(progress["eiac"]["failed"].values()))["reason"]
                self.assertIn("HTTPError 500", reason)
                self.assertNotIn("OC=", reason)

                # 필수 필드 부재 → failed(필드명만), 정상(요청 일련번호와 같은 상세) → 저장 + PII 보고 없음,
                # 다른 결정문(11279 요청에 11327 응답) → 일련번호 불일치 failed
                broken = re.sub(r"<이유>.*?</이유>", "<이유></이유>", detail_tpl, flags=re.S)

                def fake_get2(url, params=None, timeout=None):
                    sid = (params or {}).get("ID")
                    if sid == "11327":
                        return _FakeResp(detail_for(sid, broken))
                    if sid == "11279":
                        return _FakeResp(detail_tpl.encode("utf-8"))                 # 11327 상세가 그대로 온다
                    if sid:
                        return _FakeResp(detail_for(sid))
                    return _FakeResp(list_xml)
                with mock.patch.object(fr._session, "get", fake_get2):
                    rc = fr.main(["--agency", "eiac", "--force"])
                self.assertEqual(rc, 0)
                progress = fr.load_progress()
                self.assertEqual(progress["eiac"]["failed"]["11327"]["reason"], "필수 필드 없음: 이유")
                self.assertEqual(progress["eiac"]["failed"]["11279"]["reason"], "일련번호 불일치: 응답 11327")
                self.assertEqual(sorted(progress["eiac"]["fetched"]), ["11165"])
                saved = sorted(os.listdir(os.path.join(tmp, "eiac")))
                self.assertEqual(saved, ["11165_2019jg117.md"])
                self.assertFalse(os.path.exists(patches["PII_REPORT_FILE"]))

                # failed에 있는 번호는 fetched에 있어도 일반 실행이 재시도하고, 같은 일련번호의 이전 파일은 지운다
                progress["eiac"]["failed"]["11165"] = {"reason": "HTTPError 500", "at": "x"}
                fr.save_progress(progress)
                with open(os.path.join(tmp, "eiac", "11165_oldname.md"), "w", encoding="utf-8") as f:
                    f.write("stale")
                with mock.patch.object(fr._session, "get",
                                       lambda url, params=None, timeout=None:
                                       _FakeResp(detail_for(params["ID"])) if (params or {}).get("ID") else _FakeResp(list_xml)):
                    rc = fr.main(["--agency", "eiac"])
                self.assertEqual(rc, 0)
                progress = fr.load_progress()
                self.assertEqual(progress["eiac"]["failed"], {})
                self.assertEqual(sorted(os.listdir(os.path.join(tmp, "eiac"))),
                                 ["11165_2019jg117.md", "11279_2019jg117.md", "11327_2019jg117.md"])

    def test_ru19_bm25_corpus_has_no_ruling_pattern_hits_outside_rulings(self):
        from app.core import citation_validator as cv
        path = ROOT / "data" / "bm25_corpus.jsonl.gz"
        self.assertTrue(path.exists())
        hits = {"ei": [], "ia": []}
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                if d.get("source_type") == "ruling":
                    continue
                text = (d.get("text") or "") + " " + (d.get("title") or "")
                for m in cv._RULING_EI_PATTERN.finditer(text):
                    hits["ei"].append((d["id"], text[max(0, m.start() - 20):m.end() + 5]))
                for m in cv._RULING_IA_PATTERN.finditer(text):
                    hits["ia"].append((d["id"], text[max(0, m.start() - 20):m.end() + 5]))
        self.assertEqual(hits["ei"], [], hits["ei"][:5])
        self.assertEqual(hits["ia"], [], hits["ia"][:5])

    def test_ru20_ledger_drop_groups(self):
        from vector_ledger import VectorLedger

        class FakeIndex:
            def __init__(self):
                self.deleted = []

            def delete(self, ids, namespace):
                self.deleted.append((tuple(ids), namespace))

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "_uploaded_ids.json")
            led = VectorLedger(path, group_re=re.compile(r"^(eiac|iaciac)_\d+$"),
                               id_re_for=lambda g: re.compile(rf"^ruling_{re.escape(g)}_chunk_\d+$"))
            led.write({"iaciac_1": [f"ruling_iaciac_1_chunk_{i}" for i in range(6)],
                       "iaciac_2": ["ruling_iaciac_2_chunk_0", "ruling_iaciac_2_chunk_1"],
                       "eiac_3": ["ruling_eiac_3_chunk_0", "ruling_eiac_3_chunk_1"]})
            idx = FakeIndex()
            # dry-run: 삭제 목록만, 쓰기 없음
            ids = led.drop_groups(["iaciac_2"], idx, "laborlaw-v2", dry_run=True)
            self.assertEqual(ids, ["ruling_iaciac_2_chunk_0", "ruling_iaciac_2_chunk_1"])
            self.assertEqual(idx.deleted, [])
            self.assertIn("iaciac_2", led.read())
            # 50% 초과(6/10)는 가드 — 분모는 원장 전체
            with self.assertRaises(SystemExit):
                led.drop_groups(["iaciac_1"], idx, "laborlaw-v2")
            self.assertEqual(idx.deleted, [])
            # 없는 그룹은 중단
            with self.assertRaises(SystemExit):
                led.drop_groups(["iaciac_9"], idx, "laborlaw-v2", dry_run=True)
            # 실제 삭제 + 키 제거
            ids = led.drop_groups(["iaciac_2"], idx, "laborlaw-v2")
            self.assertEqual(len(ids), 2)
            self.assertEqual(idx.deleted, [(("ruling_iaciac_2_chunk_0", "ruling_iaciac_2_chunk_1"), "laborlaw-v2")])
            self.assertEqual(set(led.read()), {"iaciac_1", "eiac_3"})
            # allow_large로 대량 삭제
            ids = led.drop_groups(["iaciac_1"], idx, "laborlaw-v2", allow_large=True)
            self.assertEqual(len(ids), 6)
            self.assertEqual(set(led.read()), {"eiac_3"})

    def test_ru21_uploader_flags_and_pii_rescan(self):
        import fetch_rulings as fr
        import pinecone_upload_rulings as up
        rec = _record("iaciac", "12699")
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            os.makedirs(os.path.join(src, "iaciac"))
            path = os.path.join(src, "iaciac", "12699_2010-2071.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(fr.to_markdown(rec))
            with mock.patch.multiple(up, SOURCE_DIR=src, EXCLUDED_DIR=os.path.join(src, "_excluded"),
                                     PII_REPORT_FILE=os.path.join(src, "_pii_report.json")):
                # --exclude-before --dry-run 은 이동하지 않는다
                self.assertEqual(up.exclude_before(2016, "iaciac", dry_run=True), ["12699_2010-2071.md"])
                self.assertTrue(os.path.exists(path))
                self.assertEqual(up.exclude_before(2016, "iaciac"), ["12699_2010-2071.md"])
                self.assertFalse(os.path.exists(path))
                self.assertTrue(os.path.exists(os.path.join(src, "_excluded", "iaciac", "12699_2010-2071.md")))
                # --prune-missing 은 --agency·--limit 과 함께 받지 않는다
                self.assertEqual(up.main(["--prune-missing", "--agency", "eiac"]), 1)
                self.assertEqual(up.main(["--prune-missing", "--limit", "3"]), 1)
            # 문서 재스캔 — 보고서 없이 PII 가 있으면 문제, reviewed 또는 가림이면 통과
            doc = {"agency": "iaciac", "serial": "12699", "disposition": "연락 010-1234-5678", "title": "t", "path": "/x"}
            self.assertEqual(len(up.pii_problems(doc, set())), 1)
            self.assertEqual(up.pii_problems(doc, {("iaciac", "12699", "disposition", "휴대전화")}), [])
            self.assertEqual(up.pii_problems(up.redact_doc(doc, ["010-1234-5678"]), set()), [])

    def test_ru17_batch_ledger_generator_rejects_empty_or_orphan_groups(self):
        import fetch_rulings as fr
        import pinecone_upload_rulings as up
        import source_pack_ledger as spl
        from vector_ledger import VectorLedger
        rec = _record("eiac", "11327")
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            os.makedirs(os.path.join(src, "eiac"))
            with open(os.path.join(src, "eiac", "11327_2019jg117.md"), "w", encoding="utf-8") as f:
                f.write(fr.to_markdown(rec))
            ledger_path = os.path.join(src, "_uploaded_ids.json")
            led = VectorLedger(ledger_path, group_re=up._LEDGER._group_re, id_re_for=up._LEDGER._id_re_for)
            doc = up.parse_doc(os.path.join(src, "eiac", "11327_2019jg117.md"))
            chunks, _ = up.chunk_doc(doc)
            led.write({"eiac_11327": [c["vector_id"] for c in chunks]})
            out = os.path.join(tmp, "rulings_test.json")
            with mock.patch.multiple(up, SOURCE_DIR=src, UPLOADED_IDS_FILE=ledger_path, _LEDGER=led), \
                    mock.patch("app.config.resolve_index_name", lambda: "laborconsult"):
                ledger = up.write_batch_ledger(out)
                self.assertEqual(ledger["vector_count"], len(chunks))
                self.assertEqual(ledger["document_count"], 1)
                self.assertEqual(ledger["composition"], {"ruling": len(chunks)})
                self.assertEqual(ledger["state"], "uploaded")
                loaded = spl.load_ledger(out)                               # 롤백 도구 형식 통과
                self.assertEqual(spl.ledger_ids(loaded), sorted(c["vector_id"] for c in chunks))
                self.assertEqual(loaded["documents"]["eiac_11327"]["source_type"], "ruling")
                self.assertTrue(loaded["documents"]["eiac_11327"]["official_url"].startswith("https://www.law.go.kr/"))
                # 빈 그룹·md 없는 그룹은 중단
                led.write({"eiac_11327": [c["vector_id"] for c in chunks], "eiac_99": []})
                with self.assertRaises(RuntimeError):
                    up.write_batch_ledger(out)
                led.write({"eiac_11327": [c["vector_id"] for c in chunks], "eiac_99": ["ruling_eiac_99_chunk_0"]})
                with self.assertRaises(RuntimeError):
                    up.write_batch_ledger(out)


if __name__ == "__main__":
    unittest.main()
