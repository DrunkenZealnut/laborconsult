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

    def test_ru10_public_sources_exclude_ruling(self):
        """ruling-quota-cap D2·D8: 재결례는 쿼터·법률근거 집합 밖, 공공저작물 집합(파생)에는 포함, 자기 다양성 클래스."""
        from app.core import rag
        self.assertNotIn("ruling", rag.POOL_PUBLIC_SOURCES)
        self.assertEqual(rag.POOL_PUBLIC_SOURCES, {"precedent", "interpretation", "regulation"})
        self.assertEqual(rag.RULING_SOURCES, {"ruling"})
        self.assertEqual(rag.PUBLIC_DOMAIN_SOURCES, rag.POOL_PUBLIC_SOURCES | rag.RULING_SOURCES)
        self.assertIs(rag.LEGAL_PROMOTE_SOURCES, rag.POOL_PUBLIC_SOURCES)
        hit = {"id": "ruling_eiac_1_chunk_0", "source_type": "ruling", "title": "t", "section": "s",
               "content": "c", "score": 0.5}
        self.assertFalse(rag._is_public_source(hit))
        self.assertFalse(rag._is_legal_source(hit))
        self.assertTrue(rag._is_ruling_source(hit))
        self.assertTrue(rag.is_public_domain(hit))
        self.assertIs(rag._diversity_class_of(hit), rag._is_ruling_source)
        prec = dict(hit, id="precedent_1", source_type="precedent")
        self.assertTrue(rag._is_public_source(prec) and rag._is_legal_source(prec) and rag.is_public_domain(prec))
        self.assertIs(rag._diversity_class_of(prec), rag._is_legal_source)

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


    def test_ru22_uploader_rejects_silently_ignored_flag_combinations(self):
        """Check B-3: 각 분기가 자기 플래그만 보고 return 0 하던 조합은 거절한다(부작용 없이 1)."""
        import pinecone_upload_rulings as up
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "ledger.json")
            self.assertEqual(up.main(["--write-batch-ledger", out, "--dry-run"]), 1)
            self.assertFalse(os.path.exists(out))          # 원장 파일을 쓰지 않았다
            self.assertEqual(up.main(["--verify"]), 1)       # 단독 --verify는 아무 일도 하지 않으므로 거절
            self.assertEqual(up.main(["--exclude-before", "2016", "--agency", "iaciac", "--prune-missing"]), 1)
            # 원장 생성은 이동·삭제·부분 선택 플래그와 함께 받지 않는다(PR #157 CodeRabbit — 분기가 먼저 끝나 원장을 안 썼다)
            self.assertEqual(up.main(["--write-batch-ledger", out, "--prune-missing"]), 1)
            self.assertEqual(up.main(["--write-batch-ledger", out, "--exclude-before", "2016", "--agency", "iaciac"]), 1)
            self.assertEqual(up.main(["--write-batch-ledger", out, "--limit", "5"]), 1)
            self.assertFalse(os.path.exists(out))

    def test_ru23_empty_list_exits_nonzero(self):
        """Check B-4: 목록 0건(첫 페이지 실패·형식 변경)은 요약만 찍고 0으로 끝나지 않는다."""
        import fetch_rulings as fr
        empty_xml = b'<?xml version="1.0" encoding="UTF-8"?><Eiac><totalCnt>0</totalCnt></Eiac>'
        with tempfile.TemporaryDirectory() as tmp:
            patches = dict(OUTPUT_DIR=tmp, PROGRESS_FILE=os.path.join(tmp, "_progress.json"),
                           PII_REPORT_FILE=os.path.join(tmp, "_pii_report.json"))
            with mock.patch.multiple(fr, **patches), mock.patch.object(fr.time, "sleep", lambda s: None), \
                    mock.patch.dict(os.environ, {"LAW_API_KEY": "fake"}):
                with mock.patch.object(fr._session, "get", lambda url, params=None, timeout=None: _FakeResp(empty_xml)):
                    self.assertEqual(fr.main(["--agency", "eiac", "--list-only"]), 1)
                    self.assertEqual(fr.main(["--agency", "eiac"]), 1)
                self.assertEqual(fr.load_progress()["eiac"]["failed"], {})   # 목록 실패는 건별 failed가 아니다

    def test_ru23b_later_page_failure_exits_nonzero(self):
        """PR #157 CodeRabbit: 첫 페이지 뒤의 조회 실패도 부분 목록으로 exit 0 하지 않는다(ListFetchError → 1)."""
        import fetch_rulings as fr
        page1 = (FIX / "eiac_list_p1.xml").read_bytes()      # totalCnt 118 → 2페이지

        def fake_get(url, params=None, timeout=None):
            return _FakeResp(page1) if (params or {}).get("page") == "1" else _FakeResp(b"", 500)

        with tempfile.TemporaryDirectory() as tmp:
            patches = dict(OUTPUT_DIR=tmp, PROGRESS_FILE=os.path.join(tmp, "_progress.json"),
                           PII_REPORT_FILE=os.path.join(tmp, "_pii_report.json"))
            with mock.patch.multiple(fr, **patches), mock.patch.object(fr.time, "sleep", lambda s: None), \
                    mock.patch.dict(os.environ, {"LAW_API_KEY": "fake"}), \
                    mock.patch.object(fr._session, "get", fake_get):
                with self.assertRaises(fr.ListFetchError):
                    fr.fetch_list("eiac", "fake")
                self.assertEqual(fr.main(["--agency", "eiac", "--list-only"]), 1)
                self.assertEqual(fr.load_progress()["eiac"]["failed"], {})

    def test_ru24_residual_tag_regex_single_source(self):
        """Check G-3: 업로더 dry-run 중단 조건의 정규식은 수집기 것과 같은 객체다(복제 금지)."""
        import fetch_rulings as fr
        import pinecone_upload_rulings as up
        self.assertIs(up.RESIDUAL_TAG_RE, fr.RESIDUAL_TAG_RE)
        self.assertFalse(hasattr(fr, "REQUIRED_FIELDS"))   # 쓰이지 않는 상수는 두지 않는다
        # 잔존 태그 중단 안내는 수집기가 실제로 받는 형태여야 한다 — --serial은 --agency 없이는 exit 1(PR #157 CodeRabbit)
        src = open(os.path.join(ROOT, "pinecone_upload_rulings.py"), encoding="utf-8").read()
        self.assertRegex(src, r"잔존 HTML 태그.*\n.*--agency <기관> --serial")
        self.assertEqual(fr.main(["--serial", "1"]), 1)

    def test_ru25_eval_corpus_mix_spy_passes_keyword_args(self):
        """Check B-6: 파이프라인이 넘기는 stale_out= 등 키워드 인자를 spy가 투과한다(AST — 실행은 LLM 비용)."""
        import ast
        tree = ast.parse(open(os.path.join(ROOT, "eval_corpus_mix.py"), encoding="utf-8").read())
        spies = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "spy"]
        self.assertTrue(spies)
        for fn in spies:
            self.assertIsNotNone(fn.args.kwarg, "spy는 **kwargs를 받아야 한다")
            calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call)
                     and isinstance(c.func, ast.Name) and c.func.id == "orig"]
            self.assertTrue(calls and all(any(k.arg is None for k in c.keywords) for c in calls),
                            "orig 호출에 **kwargs를 넘겨야 한다")


def _h(i, st, score=0.5, **kw):
    return {"id": i, "score": score, "source_type": st, "title": "t", "section": "", "content": "c",
            "book_id": kw.pop("book_id", ""), **kw}


def _R(i):
    return _h(f"ruling_iaciac_{i}_chunk_0", "ruling")


class QuotaCapTest(unittest.TestCase):
    """RU26~RU35 — ruling-quota-cap: 집합 3종·킬스위치·총량 상한(교체형)·1단 victim 확장·I-9·평가 스크립트·CLAUDE.md·Self-RAG 복원."""

    def test_ru26_set_literals_single_source(self):
        """D8: rag.py의 집합 리터럴 중 'precedent'를 담은 것 하나, 'ruling'을 담은 것 하나, PUBLIC_DOMAIN은 합집합 식."""
        import ast
        tree = ast.parse(open(os.path.join(ROOT, "app", "core", "rag.py"), encoding="utf-8").read())
        literal_sets = []
        for node in ast.walk(tree):
            elts = None
            if isinstance(node, ast.Set):
                elts = node.elts
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                  and node.func.id in ("frozenset", "set") and node.args
                  and isinstance(node.args[0], (ast.List, ast.Tuple))):
                elts = node.args[0].elts
            if elts is not None:
                literal_sets.append({e.value for e in elts if isinstance(e, ast.Constant)})
        self.assertEqual(sum(1 for s in literal_sets if "precedent" in s), 1, literal_sets)
        self.assertEqual(sum(1 for s in literal_sets if "ruling" in s), 1, literal_sets)
        assigns = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "PUBLIC_DOMAIN_SOURCES" for t in n.targets)]
        self.assertEqual(len(assigns), 1)
        self.assertIsInstance(assigns[0].value, ast.BinOp)
        self.assertIsInstance(assigns[0].value.op, ast.BitOr)

    def test_ru27_ruling_retrieval_kill_switch(self):
        """D1·D9: RULING_RETRIEVAL=off면 search_hybrid가 Dense·BM25 결과의 재결례를 RRF 전에 뺀다. on·미지정·알 수 없는 값은 불변."""
        from app.core import rag
        from app.core import bm25_search as bm
        dense = [_h("ruling_eiac_1_chunk_0", "ruling", 0.9), _h("precedent_1", "precedent", 0.8),
                 _h("ctx_qa_1_c0", "qa", 0.7), _h("ruling_iaciac_2_chunk_0", "ruling", 0.6)]
        bm_hits = [_h("ruling_iaciac_3_chunk_0", "ruling", 20.0), _h("ctx_qa_2_c0", "qa", 10.0)]
        cfg = mock.Mock()
        with mock.patch.object(rag, "search_pinecone_multi", side_effect=lambda *a, **k: list(dense)), \
             mock.patch.object(bm, "load_bm25_corpus", return_value=True), \
             mock.patch.object(bm, "search_bm25", side_effect=lambda *a, **k: list(bm_hits)), \
             mock.patch.object(rag, "_fetch_public_hits", return_value=[]):
            with mock.patch.dict(os.environ, {"RULING_RETRIEVAL": "off"}):
                off = rag.search_hybrid(["q"], cfg, top_k=8)
            self.assertEqual({x["id"] for x in off}, {"precedent_1", "ctx_qa_1_c0", "ctx_qa_2_c0"})
            for val in ("on", "whatever"):
                with mock.patch.dict(os.environ, {"RULING_RETRIEVAL": val}):
                    on = rag.search_hybrid(["q"], cfg, top_k=8)
                self.assertEqual(sum(1 for x in on if x["source_type"] == "ruling"), 3, val)
            env = {k: v for k, v in os.environ.items() if k != "RULING_RETRIEVAL"}
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertTrue(rag._ruling_retrieval_enabled())
            # Dense-only 폴백(BM25 예외)에도 걸린다
            with mock.patch.object(bm, "load_bm25_corpus", side_effect=RuntimeError("no bm25")), \
                 mock.patch.dict(os.environ, {"RULING_RETRIEVAL": "off"}):
                off2 = rag.search_hybrid(["q"], cfg, top_k=8)
            self.assertEqual({x["id"] for x in off2}, {"precedent_1", "ctx_qa_1_c0"})
        # 공공 전용 조회의 $in 집합에 ruling이 없다(D8 — 집합이 바뀌어 자동)
        captured = {}
        def fake_query(namespaces, vector, top_k, source_type, index):
            captured["source_type"] = source_type
            return []
        cfg.openai_client.with_options.return_value.embeddings.create.return_value.data = [mock.Mock(embedding=[0.0])]
        with mock.patch.object(rag, "_query_namespaces", side_effect=fake_query):
            rag._fetch_public_hits("q", cfg, 4)
        self.assertEqual(captured["source_type"], rag.POOL_PUBLIC_SOURCES)
        self.assertNotIn("ruling", captured["source_type"])

    def test_ru28_ruling_cap_swap_invariants(self):
        """D4·D12·D13: 상한 값, 교체형 불변식(길이·상위 유지·후보 순서 ①주입 공공 → ②top_n 밖 자연 공공(Act-2 A) → ③창 상담·해설서 제외·말미·마커·비변이·후보 없음·스위치)."""
        from app.core import rag
        self.assertEqual([rag._ruling_cap(n) for n in (3, 5, 7, 6, 8, 10)], [1, 2, 3, 3, 4, 5])
        tb = _h("textbook_win_0001_0", "textbook", book_id="win")
        ranked = [_R(1), _R(2), _R(3), _R(4), _h("qa1", "qa"),                       # top_n=5
                  _h("qa2", "qa"), _h("prec_nat", "precedent"), tb, _R(5), _h("qa3", "qa"),  # 창 5~10
                  _h("x", "qa"), _h("y", "qa"), _h("prec_inj", "precedent", quota_injected=True)]  # 창 밖 주입 공공
        out = rag._cap_rulings_in_top_n(ranked[:5], ranked, 5)
        self.assertEqual(len(out), 5)
        self.assertEqual([x["id"] for x in out[:3]], ["ruling_iaciac_1_chunk_0", "ruling_iaciac_2_chunk_0", "qa1"])
        self.assertEqual([x["id"] for x in out[3:]], ["prec_inj", "prec_nat"])       # ① 창 밖 주입 → ② 자연 공공, 해설서 건너뜀
        # Act-2 A: 창 밖(순위 ≥ 2×top_n)의 **자연** 공공도 후보 ②다 — 창 안 상담보다 먼저. 창 밖 상담은 후보가 아니다.
        ranked_far = [_R(1), _R(2), _R(3), _R(4), _h("qa1", "qa"),
                      _h("qa2", "qa"), _R(5), tb, _R(6), _h("qa3", "qa"),            # 창: 상담 2·해설서 1·재결 2
                      _h("x", "qa"), _h("y", "qa"), _h("prec_far", "precedent"), _h("z", "qa")]  # 창 밖: 자연 공공 1·상담 3
        out_far = rag._cap_rulings_in_top_n(ranked_far[:5], ranked_far, 5)
        self.assertEqual([x["id"] for x in out_far[3:]], ["prec_far", "qa2"])        # ② 창 밖 자연 공공 → ③ 창 안 상담
        self.assertNotIn("x", [x["id"] for x in out_far]); self.assertNotIn("z", [x["id"] for x in out_far])
        self.assertTrue(all(x.get("promoted") == "ruling-cap" for x in out[3:]))
        self.assertNotIn("promoted", ranked[12])                                       # 원본 비변이
        self.assertEqual(sum(1 for x in out if x["source_type"] == "textbook"), 0)
        cnt = lambda hs, pred: sum(1 for x in hs if pred(x))
        self.assertGreaterEqual(cnt(out, rag.is_counsel_source), cnt(ranked[:5], rag.is_counsel_source))   # 상담 비감소
        self.assertGreaterEqual(cnt(out, lambda x: bool(rag._book_id_of(x))), cnt(ranked[:5], lambda x: bool(rag._book_id_of(x))))  # 해설서 비감소
        # 후보가 창 상담뿐 → 상담(해설서는 아님)
        ranked3 = [_R(1), _R(2), _R(3), _h("qa1", "qa"), _h("qa2", "qa"), _h("qa3", "qa"), _R(6), tb]
        out3 = rag._cap_rulings_in_top_n(ranked3[:5], ranked3, 5)
        self.assertEqual(sum(1 for x in out3 if x["source_type"] == "ruling"), 2)
        self.assertEqual(out3[-1]["id"], "qa3")
        # 후보 없음 → 그대로(강제 공백 없음)
        ranked2 = [_R(i) for i in range(1, 11)]
        self.assertEqual(rag._cap_rulings_in_top_n(ranked2[:5], ranked2, 5), ranked2[:5])
        # 상한 이하 → 무변경
        sel = [_R(1), _h("qa1", "qa"), _h("qa2", "qa")]
        self.assertEqual(rag._cap_rulings_in_top_n(sel, sel + [_R(2)], 3), sel)
        # RULING_CAP=off → 무변경
        with mock.patch.dict(os.environ, {"RULING_CAP": "off"}):
            self.assertEqual(rag._cap_rulings_in_top_n(ranked[:5], ranked, 5), ranked[:5])

    def test_ru29_finalize_order_three_exits(self):
        """D11: 상한 → 2단 → 승격. 창 밖 quota_injected 판례가 상한 ①로 들어온다(2단으로는 못 들어오는 배치). 세 exit 동일."""
        import types
        from app.core import rag
        ranked = [_R(1), _R(2), _R(3), _R(4), _h("qa1", "qa"),
                  _h("qa2", "qa"), _R(5), _h("qa3", "qa"), _h("qa4", "qa"), _R(6),
                  _h("qa5", "qa"), _h("qa6", "qa"), _h("prec_inj", "precedent", quota_injected=True)]

        def verify(out, label):
            self.assertEqual(len(out), 5, label)
            self.assertEqual(sum(1 for x in out if x["source_type"] == "ruling"), 2, label)
            inj = [x for x in out if x["id"] == "prec_inj"]
            self.assertEqual(len(inj), 1, label)
            self.assertEqual(inj[0].get("promoted"), "ruling-cap", label)
            self.assertEqual(sum(1 for x in out if x["source_type"] == "textbook"), 0, label)

        verify(rag.rerank_results("q", ranked, cohere_api_key="", top_n=5), "무키")
        with mock.patch.object(rag.llm_transport, "rerank_client", side_effect=RuntimeError("down")):
            verify(rag.rerank_results("q", ranked, cohere_api_key="k", top_n=5), "예외")

        class _Co:
            def rerank(self, **kw):
                return types.SimpleNamespace(results=[
                    types.SimpleNamespace(index=i, relevance_score=1.0 - i * 0.01) for i in range(len(ranked))])
        with mock.patch.object(rag.llm_transport, "rerank_client", return_value=_Co()), \
             mock.patch.object(rag.llm_transport, "rerank_model", return_value="rerank-v3.5"):
            verify(rag.rerank_results("q", ranked, cohere_api_key="k", top_n=5), "성공")
        # ensure_textbook=False(A/B 기준선)에서도 상한은 적용된다
        verify(rag.rerank_results("q", ranked, cohere_api_key="", top_n=5, ensure_textbook=False), "기준선")

    def test_ru30_i9_protects_last_ruling_and_last_precedent_separately(self):
        """D3: 전원 단일 출처 [qa, ruling, precedent] — 현행(재결례=법률근거 클래스)은 precedent(2), 신규는 qa(0)."""
        from app.core import rag
        sel = [_h("qa1", "qa"), _R(1), _h("p1", "precedent")]
        self.assertEqual(rag._pick_swap_victim(sel), 0)
        sel2 = [_R(1), _R(2), _h("qa1", "qa")]
        self.assertEqual(rag._pick_swap_victim(sel2), 1)       # 재결례 2건이면 하위 재결례가 victim

    def test_ru31_eval_scripts_use_derived_sets(self):
        """D20·D21(AST — import는 load_dotenv 부작용): eval_corpus_mix.classify가 ruling을 따로 분류, eval_colloquial 집합은 파생."""
        import ast
        mix = ast.parse(open(os.path.join(ROOT, "eval_corpus_mix.py"), encoding="utf-8").read())
        fn = next(n for n in ast.walk(mix) if isinstance(n, ast.FunctionDef) and n.name == "classify")
        names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        consts = {n.value for n in ast.walk(fn) if isinstance(n, ast.Constant)}
        self.assertTrue({"RULING_SOURCES", "POOL_PUBLIC_SOURCES"} <= names, names)
        self.assertIn("ruling", consts)
        totals = [n for n in ast.walk(mix) if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id in ("totals", "counts") for t in n.targets)]
        self.assertTrue(totals)
        for a in totals:
            self.assertIsInstance(a.value, ast.Dict)
            self.assertIn("ruling", {k.value for k in a.value.keys if isinstance(k, ast.Constant)})
        col = ast.parse(open(os.path.join(ROOT, "eval_colloquial.py"), encoding="utf-8").read())
        lcs = [n for n in ast.walk(col) if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "LEGAL_CORPUS_SOURCES" for t in n.targets)]
        self.assertEqual(len(lcs), 1)
        self.assertIsInstance(lcs[0].value, ast.BinOp)
        self.assertEqual({n.id for n in ast.walk(lcs[0].value) if isinstance(n, ast.Name)}, {"PUBLIC_DOMAIN_SOURCES"})

    def test_ru32_self_rag_restore_wiring(self):
        """D14·Act-2 C: Self-RAG 뒤 복원은 `_restore_public_after_self_rag` 한 함수이고(AST), 쿼터 집합만 복원한다."""
        import ast
        src = open(os.path.join(ROOT, "app", "core", "pipeline.py"), encoding="utf-8").read()
        tree = ast.parse(src)
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == "_restore_public_after_self_rag"]
        self.assertEqual(len(calls), 1, "Self-RAG 복원 호출부는 한 곳이어야 한다")
        self.assertEqual(ast.unparse(calls[0].args[0]), "_before_self_rag")
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_restore_public_after_self_rag")
        names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        self.assertIn("_is_public_source", names); self.assertIn("_pool_public_quota_for_top_n", names)
        self.assertNotIn("is_public_domain", names); self.assertNotIn("_is_ruling_source", names)
        # 옛 '전멸 시 1건' 분기는 남아 있지 않다
        self.assertFalse(any("_is_public_source(h) for h in _before_self_rag" in ast.unparse(n.test)
                             for n in ast.walk(tree) if isinstance(n, ast.If)))

    def test_ru35_self_rag_restore_to_quota_target(self):
        """Act-2 C: 쿼터 집합 공공이 2단 목표 미만이면 제거된 공공을 rerank 순위대로 목표까지 되살린다. 재결례는 아니다."""
        from app.core.pipeline import _restore_public_after_self_rag as restore
        P = lambda i: _h(f"prec_{i}", "precedent"); C = lambda i: _h(f"qa{i}", "qa")
        before = [_R(1), P(1), C(1), P(2), _R(2), C(2), P(3)]          # rerank 순
        # 전부 제거 → 목표 2(top_n 7)까지 상위 2건 복원, 말미
        after, got = restore(before, [_R(1), C(1)], 7)
        self.assertEqual([h["id"] for h in got], ["prec_1", "prec_2"]); self.assertEqual([h["id"] for h in after][-2:], ["prec_1", "prec_2"])
        # 1건 남음 → 1건만 복원(남은 것은 다시 넣지 않는다)
        after, got = restore(before, [_R(1), P(2), C(1)], 7)
        self.assertEqual([h["id"] for h in got], ["prec_1"]); self.assertEqual(len(after), 4)
        # 목표 충족 → 무변경
        after, got = restore(before, [P(1), P(3), C(1)], 7)
        self.assertEqual(got, []); self.assertEqual(len(after), 3)
        # SIMPLE(top_n 3)은 목표 1 — 이전 규칙과 같다
        after, got = restore(before, [_R(1), C(1)], 3)
        self.assertEqual([h["id"] for h in got], ["prec_1"])
        # 재결례만 제거됐으면 복원하지 않는다(쿼터 집합 밖, D14)
        after, got = restore([_R(1), _R(2), P(1), C(1)], [P(1), C(1)], 7)
        self.assertEqual(got, [])
        # before에 공공이 없으면 무변경
        after, got = restore([_R(1), C(1), C(2)], [C(1)], 7)
        self.assertEqual(got, []); self.assertEqual(len(after), 1)

    def test_ru33_claude_md_documents_switches(self):
        """CLAUDE.md: 킬스위치 부재 서술 제거, 스위치 2종·1단 victim 규칙 서술."""
        text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertNotIn("킬스위치는 **없다**", text)
        for key in ("RULING_RETRIEVAL", "RULING_CAP", "PUBLIC_DOMAIN_SOURCES"):
            self.assertIn(key, text, key)

        def section(start_marker: str) -> str:
            i = text.index(start_marker)
            j = text.find("\n- **", i + 1)
            return text[i: j if j > 0 else None]
        quota = section("- **공공저작물 쿼터는 2단이고")
        self.assertIn("초과 재결례", quota)                    # 1단 victim 규칙은 공공 쿼터 절 안에
        self.assertIn("충족하지 않는다", quota)
        promote = section("- **다양성 승격 2종**")
        self.assertIn("재결례", promote)                         # I-9 클래스 3종
        self.assertIn("재결례 승격은 두지 않는다", promote)

    def test_ru34_pool_quota_ruling_victims(self):
        """D22: 1단 victim은 상담(하한 2) → pool 상한(top_k//2) 초과 재결례(점수 하위부터). 해설서는 victim이 아니다."""
        from app.core import rag
        self.assertEqual([rag._pool_ruling_floor(k) for k in (8, 15, 20)], [4, 7, 10])
        pub = [_h(f"p{i}", "precedent") for i in range(4)]
        kinds = lambda out, st: sum(1 for x in out if x["source_type"] == st)
        # R×13 + C×2 → quota 3 주입, 상담 2 유지, 재결례 13 → 10(끝 3건 제거)
        hits = [_R(i) for i in range(13)] + [_h("qa1", "qa"), _h("qa2", "qa")]
        out = rag._apply_public_quota(hits, pub, top_k=15)
        self.assertEqual(len(out), 15)
        self.assertEqual((kinds(out, "precedent"), kinds(out, "qa"), kinds(out, "ruling")), (3, 2, 10))
        self.assertEqual([x["id"] for x in out if x["source_type"] == "ruling"], [_R(i)["id"] for i in range(10)])
        self.assertTrue(all(x.get("quota_injected") for x in out if x["source_type"] == "precedent"))
        # 하한: R×7 + C×2 → 주입 0(기존 동작과 동일)
        hits2 = [_R(i) for i in range(7)] + [_h("qa1", "qa"), _h("qa2", "qa")]
        self.assertEqual(rag._apply_public_quota(hits2, pub, top_k=15), hits2)
        # 해설서는 victim이 아니다: R×3 + T×5 + C×2 → 주입 0
        hits3 = ([_R(i) for i in range(3)]
                 + [_h(f"textbook_win_000{i}_0", "textbook", book_id="win") for i in range(5)]
                 + [_h("qa1", "qa"), _h("qa2", "qa")])
        self.assertEqual(rag._apply_public_quota(hits3, pub, top_k=15), hits3)
        # 상담 우선: R×13 + C×5 → 상담 5 → 2, 재결례 13 유지
        hits4 = [_R(i) for i in range(13)] + [_h(f"qa{i}", "qa") for i in range(5)]
        out4 = rag._apply_public_quota(hits4, pub, top_k=15)
        self.assertEqual((kinds(out4, "precedent"), kinds(out4, "qa"), kinds(out4, "ruling")), (3, 2, 13))
        # 상담 하한에서 재결례로 넘어간다: R×13 + C×3 → 상담 1건 뒤 재결례 2건
        hits5 = [_R(i) for i in range(13)] + [_h(f"qa{i}", "qa") for i in range(3)]
        out5 = rag._apply_public_quota(hits5, pub, top_k=15)
        self.assertEqual((kinds(out5, "precedent"), kinds(out5, "qa"), kinds(out5, "ruling")), (3, 2, 11))
        # 상담만 있는 pool은 기존과 같다(T26-a)
        hits6 = [_h(f"qa{i}", "qa") for i in range(8)]
        out6 = rag._apply_public_quota(hits6, pub, top_k=8)
        self.assertEqual((kinds(out6, "precedent"), kinds(out6, "qa")), (2, 6))


if __name__ == "__main__":
    unittest.main()
