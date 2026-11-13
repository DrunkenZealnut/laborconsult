"""source-pack-refresh 회귀(API 키·네트워크 불요) — 설계 §4 S1~S8.

fixture는 2026-11-12 법제처 현행판 XML에서 해당 `조문단위`만 발췌했다(`data/source_pack_refresh/fixtures/`).
"""
from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path

import source_pack_refresh as spr

ROOT = Path(__file__).resolve().parent
FIX = ROOT / "data" / "source_pack_refresh" / "fixtures"
TARGETS = ROOT / "data" / "source_pack_refresh" / "targets_20261112.json"
HELD = ROOT / "data" / "source_pack_refresh" / "targets_20261113.json"
ALL_TARGETS = sorted((ROOT / "data" / "source_pack_refresh").glob("targets_*.json"))


def _unit(name: str) -> str:
    units = spr.article_units((FIX / f"{name}.xml").read_text(encoding="utf-8"))
    assert len(units) == 1, name
    return units[0]


class BodyRulesTest(unittest.TestCase):
    def test_s1_image_with_box_table_keeps_table_text(self):
        body, status = spr.article_body(_unit("nhis_71"))
        self.assertEqual(status, "ok")
        self.assertNotIn("<img", body)
        self.assertNotIn("</img>", body)
        self.assertIn("(연간 보수 외 소득 - 대통령령으로 정하는 금액) × 1/12", body)
        self.assertIn("┌", body)                       # 상자 표는 다듬지 않는다(D3)

    def test_s2_image_without_box_table_is_held(self):
        self.assertEqual(spr.article_body(_unit("img_only"))[1], "held_image")

    def test_s3_empty_placeholder_article_is_skipped(self):
        body, status = spr.article_body(_unit("wage_guarantee_3_2"))
        self.assertEqual(status, "empty_article")
        self.assertLessEqual(len(body), spr.EMPTY_ARTICLE_MAX)

    def test_plain_article_and_section_title(self):
        unit = _unit("nps_126")
        self.assertEqual(spr.article_body(unit)[1], "ok")
        self.assertEqual(spr.article_key(unit), "126")
        self.assertEqual(spr.section_title(unit), "제126조 외국인에 대한 적용")
        self.assertEqual(spr.article_key(_unit("wage_guarantee_3_2")), "3의2")


class IdsAndLedgerTest(unittest.TestCase):
    def setUp(self):
        self.spec = spr.load_targets(str(TARGETS))
        self.prior = json.loads((ROOT / self.spec["prior_ledger"]).read_text(encoding="utf-8"))

    def test_s4_id_shape_and_work_key_matches_prior_batch(self):
        vid = spr.vector_id(self.spec, "general_law_nps", "제126조 외국인에 대한 적용", 0)
        self.assertRegex(vid, r"^qpack_20261112_[0-9a-f]{16}_[0-9a-f]{10}_\d+$")
        work_key = vid.split("_")[2]
        prior_keys = {i.split("_")[2] for i in self.prior["documents"]["general_law_nps"]["ids"]}
        self.assertEqual(prior_keys, {work_key})       # 기존 배치와 같은 문서 키(D5)
        # 같은 조문은 섹션 해시도 같다 — 날짜 접두사만 다르다(대체 뒤에는 구 원장 revision에 남는다)
        self.assertIn(vid.replace("qpack_20261112_", "qpack_20261009_"), spr.superseded_ids(self.prior, self.spec))

    def test_s6_supersede_selects_only_that_article(self):
        ids = spr.superseded_ids(self.prior, self.spec)
        self.assertEqual(ids, ["qpack_20261009_0faa222030e9b9c3_30e4b8d456_0",
                               "qpack_20261009_0faa222030e9b9c3_30e4b8d456_1"])
        tag = hashlib.sha256("제126조 외국인에 대한 적용".encode()).hexdigest()[:10]
        others = [i for i in self.prior["documents"]["general_law_nps"]["ids"] if i not in ids]
        self.assertTrue(others)
        self.assertFalse(any(f"_{tag}_" in i for i in others))
        if spr.already_superseded(self.prior, self.spec):
            # 대체 뒤 구 원장: 그 ID는 문서에서 빠지고 revision에 남는다, 개수 정합
            self.assertFalse(set(ids) & set(self.prior["documents"]["general_law_nps"]["ids"]))
            self.assertEqual(self.prior["vector_count"], sum(len(d["ids"]) for d in self.prior["documents"].values()))

    def test_s6_supersede_dry_run_writes_nothing(self):
        before = (ROOT / self.spec["prior_ledger"]).read_bytes()
        self.assertEqual(spr.supersede(self.spec, apply=False), 0)
        self.assertEqual((ROOT / self.spec["prior_ledger"]).read_bytes(), before)


class ReviewGateTest(unittest.TestCase):
    def test_s8_every_target_has_a_verdict(self):
        """적재 전 관문 — 검토 파일의 판정 칸이 대상 조문 전부에 채워져 있어야 한다(D4). 대상 파일 전부."""
        checked = 0
        for targets in ALL_TARGETS:
            spec = spr.load_targets(str(targets))
            verdicts = spr.review_verdicts(spec)
            if not verdicts:
                if not list((ROOT / "data" / "source_pack_refresh").glob("review_*.md")):
                    continue                                                        # 검토 파일이 하나도 없는 환경
                self.fail(f"{targets.name}: 커밋된 대상 파일에 review_{spec['batch']}.md가 없다")
            checked += 1
            for law in spec["laws"]:
                for art in law["articles"]:
                    label = f"{law['law']} {spr.article_heading(art)}"
                    self.assertTrue(verdicts.get(label), label)
                    self.assertRegex(verdicts[label], r"^(적재|보류)", label)
        if not checked:
            self.skipTest("review 파일 없음 — prepare 후 로컬 관문")

    def test_targets_exclude_empty_and_out_of_scope_laws(self):
        spec = spr.load_targets(str(TARGETS))
        laws = {l["law"] for l in spec["laws"]}
        self.assertNotIn("임금채권보장법", laws)      # 빈 자리 조문(D1)
        self.assertNotIn("민사집행규칙", laws)


class MetadataSchemaTest(unittest.TestCase):
    def test_s5_metadata_keys_match_prior_batch_schema(self):
        """기존 배치(`qpack_20261009_`)와 같은 메타데이터 키 — 공식 증거 2차 조회·BM25 빌더가 같은 필드를 읽는다."""
        want = {"source_type", "title", "section", "text", "chunk_text", "official_url", "url", "official", "issuer",
                "date", "effective_date", "retrieved_on", "source_batch", "source_pack_id", "source_sha256",
                "chunk_sha256", "chunk_index", "version_scope", "rights_basis"}
        paths = sorted((ROOT / "data" / "source_pack_refresh").glob("2*/prepared_vectors.jsonl"))
        if not paths:
            self.skipTest("prepare 산출물 없음 — 로컬 관문")
        for path in paths:
            batch = path.parent.name
            for line in path.read_text(encoding="utf-8").splitlines():
                meta = json.loads(line)["metadata"]
                self.assertEqual(set(meta), want)
                self.assertIs(meta["official"], True)
                self.assertEqual(meta["source_batch"], f"sourcepack_{batch}")
                self.assertIsInstance(meta["chunk_index"], int)


BOX = "┌──┐\n│1 － A ÷ 180일 ? B ÷ 9개월 + C │\n└──┘"


class SuspectGlyphTest(unittest.TestCase):
    """source-pack-held-articles G1·정정(설계 §5 H1~H7)."""

    def test_h1_counts_only_box_lines(self):
        self.assertEqual(spr.suspect_glyphs(BOX), 1)
        self.assertEqual(spr.suspect_glyphs("근로자인가요? 아닌가요?"), 0)          # 상자 밖 문장
        self.assertEqual(spr.suspect_glyphs("│값 \ufffd 깨짐│"), 1)
        body, _ = spr.article_body(_unit("ei_decree_60_2"))
        self.assertNotIn("flDownload", body)                                        # 이미지 URL의 ?는 이미 없다
        self.assertEqual(spr.suspect_glyphs(body), 1)

    def test_h2_apply_corrections_exactly_once_one_glyph(self):
        fx = {"article": "x", "find": "180일 ? B", "replace": "180일 ≤ B"}
        self.assertIn("180일 ≤ B", spr.apply_corrections(BOX, [fx]))
        with self.assertRaises(SystemExit):                                         # 0회
            spr.apply_corrections(BOX, [dict(fx, find="없는 ? 문맥", replace="없는 ≤ 문맥")])
        with self.assertRaises(SystemExit):                                         # 2회
            spr.apply_corrections(BOX + "\n" + BOX, [fx])
        with self.assertRaises(SystemExit):                                         # 다른 글자까지 바꿈
            spr.apply_corrections(BOX, [dict(fx, replace="181일 ≤ B")])
        with self.assertRaises(SystemExit):                                         # 의심 문자 두 개를 한꺼번에
            spr.apply_corrections("│x ? y ? z│", [{"article": "x", "find": "x ? y ?", "replace": "x ≤ y ≤"}])
        with self.assertRaises(SystemExit):                                         # 의심 문자가 아닌 글자 치환
            spr.apply_corrections(BOX, [dict(fx, find="180일 ? B", replace="180일 ? C")])

    def test_h2b_correction_glyph_allowlist_and_latex_token(self):
        fx = {"article": "x", "find": "180일 ? B", "replace": "180일 ≤ B", "latex_token": "\\leq"}
        self.assertIn("≤", spr.apply_corrections(BOX, [fx]))
        with self.assertRaises(SystemExit):                                         # 허용 목록 밖 기호
            spr.apply_corrections(BOX, [dict(fx, replace="180일 가 B")])
        with self.assertRaises(SystemExit):                                         # latex_token과 기호가 어긋남
            spr.apply_corrections(BOX, [dict(fx, latex_token="\\geq")])

    def _sources(self, tmp: Path, img: bytes, alt: str, recorded: str | None = None):
        (tmp / "img_111.gif").write_bytes(img)
        page = (f'<p><img alt="@@LATEX@@{alt}@@/LATEX@@" src="/LSW/flDownload.do?flSeq=111" /></p>\r\n'
                '<img alt="other \\leq" src="/LSW/flDownload.do?flSeq=1112" />')      # 실제 화면처럼 CRLF
        (tmp / "w.screen.html").write_bytes(page.encode())
        digest = hashlib.sha256(img).hexdigest()
        fx = {"work_id": "w", "article": "1", "image_flseq": "111", "image_sha256": recorded or digest,
              "latex_token": "\\leq"}
        return {"corrections": [fx]}, {"w": {"assets": {"111": digest,
                                                      "screen:w": hashlib.sha256(page.encode()).hexdigest()}}}

    def test_h3_correction_sources_fail_closed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            spec, man = self._sources(tmp, b"GIF89a-1", "1- A \\leq B")
            spr.verify_correction_sources(spec, tmp, man)                            # 정상
            spec, man = self._sources(tmp, b"GIF89a-1", "1- A \\leq B", recorded="0" * 64)
            with self.assertRaises(SystemExit):                                     # 이미지 sha 불일치
                spr.verify_correction_sources(spec, tmp, man)
            spec, man = self._sources(tmp, b"GIF89a-1", "1- A + B")
            with self.assertRaises(SystemExit):                                     # 그 이미지 alt에 \leq 없음(옆 flSeq=1112는 무관)
                spr.verify_correction_sources(spec, tmp, man)
            spec, man = self._sources(tmp, b"GIF89a-1", "1- A \\leq B")
            spec["corrections"][0]["image_flseq"] = "999"
            with self.assertRaises(SystemExit):                                     # 이미지·태그 없음
                spr.verify_correction_sources(spec, tmp, man)
            spec, man = self._sources(tmp, b"GIF89a-1", "1- A \\leq B")
            (tmp / "img_222.gif").write_bytes(b"GIF89a-2")                           # 이미지는 맞는데 화면에 그 flSeq 태그가 없음
            fx = spec["corrections"][0]
            fx.update(image_flseq="222", image_sha256=hashlib.sha256(b"GIF89a-2").hexdigest())
            man["w"]["assets"]["222"] = fx["image_sha256"]
            with self.assertRaisesRegex(SystemExit, "화면 수식"):
                spr.verify_correction_sources(spec, tmp, man)
            spec, man = self._sources(tmp, b"GIF89a-1", "1- A \\leq B")
            (tmp / "w.screen.html").write_text("<p>바뀐 화면</p>", encoding="utf-8")  # fetch 이후 화면이 바뀜
            with self.assertRaisesRegex(SystemExit, "화면 HTML이 바뀌었다"):
                spr.verify_correction_sources(spec, tmp, man)

    def test_h4_committed_corrections_match_fixture_once(self):
        spec = spr.load_targets(str(HELD))
        self.assertEqual(len(spec["corrections"]), 3)
        for fx in spec["corrections"]:
            unit = _unit("ei_decree_" + fx["article"].replace("의", "_"))
            body, status = spr.article_body(unit)
            self.assertEqual(status, "ok")
            self.assertEqual(body.count(fx["find"]), 1, fx["article"])
            fixed = spr.apply_corrections(body, spr.corrections_for(spec, fx["work_id"], fx["article"]))
            self.assertEqual(spr.suspect_glyphs(fixed), 0, fx["article"])
            self.assertIn("≤", fixed)
            self.assertIn("1 － ", fixed)                                             # 빼기 기호는 그대로(P1)
            self.assertEqual(fx["latex_token"], "\\leq")
            self.assertRegex(fx["image_sha256"], r"^[0-9a-f]{64}$")

    def _workdir(self, tmp: Path, body: str, verdict: str, section: str = "제60조의2 피보험 단위기간 산정"):
        spec = {"batch": "20990101"}
        out = tmp / "20990101"; out.mkdir(exist_ok=True)
        meta = {"title": "고용보험법 시행령", "section": section[:spr.SECTION_MAX], "source_pack_id": "ei-decree"}
        vec = {"id": "v0", "metadata": meta, "embed_text": "머리글\n정정: '?'를 '≤'로\n\n" + body}
        (out / "prepared_vectors.jsonl").write_text(json.dumps(vec, ensure_ascii=False) + "\n", encoding="utf-8")
        (tmp / "review_20990101.md").write_text(f"### 고용보험법 시행령 제60조의2\n\n판정: {verdict}\n", encoding="utf-8")
        return spec

    def test_h5_upload_gate_on_remaining_suspects(self):
        """G1은 적재할 본문에서 직접 센다 — prepare_rows.json이 없어도·섹션이 길어도 관문이 꺼지지 않는다."""
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            with mock.patch.object(spr, "work_dir", lambda s: tmp / s["batch"]), \
                 mock.patch.object(spr, "review_verdicts",
                                   lambda s: dict(spr._VERDICT_RE.findall((tmp / f"review_{s['batch']}.md").read_text()))):
                spec = self._workdir(tmp, BOX, "적재")
                self.assertFalse((tmp / "20990101" / "prepare_rows.json").exists())
                with self.assertRaises(SystemExit):
                    spr.approved_vectors(spec)
                spec = self._workdir(tmp, BOX, "적재", section="제60조의2 " + "아주 긴 제목" * 40)
                with self.assertRaises(SystemExit):                                 # 160자 넘는 섹션
                    spr.approved_vectors(spec)
                spec = self._workdir(tmp, BOX, "적재(의심 문자 확인: 원문 문장부호)")
                self.assertEqual(len(spr.approved_vectors(spec)), 1)
                spec = self._workdir(tmp, BOX, "보류(근거 없음)")
                self.assertEqual(spr.approved_vectors(spec), [])
                spec = self._workdir(tmp, BOX.replace("?", "≤"), "적재")              # 머리글의 '?'는 세지 않는다
                self.assertEqual(len(spr.approved_vectors(spec)), 1)

    def _prepare(self, tmp: Path, spec_extra: dict):
        """fixture XML로 prepare를 실제로 돌린다(정정 근거 대조는 H3가 맡아 여기서는 건너뛴다)."""
        from unittest import mock
        out = tmp / "20990101"; out.mkdir(exist_ok=True)
        units = "".join((FIX / f"ei_decree_{n}.xml").read_text(encoding="utf-8").replace("<법령>", "").replace("</법령>", "")
                        for n in ("60_2", "104_8"))
        xml = "<법령>" + units + "</법령>"
        (out / "ei-decree.xml").write_text(xml, encoding="utf-8")
        (out / "fetch_manifest.json").write_text(json.dumps({"ei-decree": {
            "url": "u", "sha256": hashlib.sha256(xml.encode()).hexdigest()}}), encoding="utf-8")
        spec = {"batch": "20990101", "as_of": "2099-01-01",
                "laws": [{"work_id": "ei-decree", "law": "고용보험법 시행령", "articles": ["60의2", "104의8"]}]}
        spec.update(spec_extra)
        with mock.patch.object(spr, "work_dir", lambda s: out), \
             mock.patch.object(spr, "verify_correction_sources", lambda *a: None):
            return spr.prepare(spec)

    def test_h6_correction_header_only_on_corrected_article(self):
        import tempfile
        held = spr.load_targets(str(HELD))
        with tempfile.TemporaryDirectory() as d:
            vectors, rows = self._prepare(Path(d), {"corrections": spr.corrections_for(held, "ei-decree", "60의2")})
        by = {r["article"]: r for r in rows}
        self.assertEqual((by["60의2"]["corrected"], by["60의2"]["suspect_glyph"]), (1, 0))
        self.assertEqual((by["104의8"]["corrected"], by["104의8"]["suspect_glyph"]), (0, 1))
        for v in vectors:
            has_note = "\n정정: " in v["embed_text"].split("\n\n", 1)[0]
            self.assertEqual(has_note, v["metadata"]["section"].startswith("제60조의2"), v["id"])
            if has_note:
                self.assertIn("'?'를 '≤'로", v["embed_text"])

    def test_h6b_review_handles_long_section_titles(self):
        import tempfile
        from unittest import mock
        long = "제60조의2 " + "아주 긴 제목" * 40
        meta = {"source_pack_id": "ei-decree", "section": long[:spr.SECTION_MAX]}
        vec = {"metadata": meta, "embed_text": "머리글\n\n본문"}
        row = {"work_id": "ei-decree", "law": "고용보험법 시행령", "article": "60의2", "section": long, "status": "ok",
               "chunks": 1}
        with tempfile.TemporaryDirectory() as d, mock.patch.object(spr, "ROOT", Path(d)):
            (Path(d) / "data" / "source_pack_refresh").mkdir(parents=True)
            path = spr.write_review({"batch": "20990101"}, [vec], [row])
            self.assertIn("### 고용보험법 시행령 제60조의2", path.read_text(encoding="utf-8"))

    def test_h8_unused_correction_aborts(self):
        import tempfile
        held = spr.load_targets(str(HELD))
        with tempfile.TemporaryDirectory() as d:                                    # 104의15는 대상 조문 밖
            with self.assertRaisesRegex(SystemExit, "적용되지 않은 정정"):
                self._prepare(Path(d), {"corrections": spr.corrections_for(held, "ei-decree", "104의15")})

    def test_h6_correction_note_names_the_glyph(self):
        spec = spr.load_targets(str(HELD))
        note = spr.correction_note(spr.corrections_for(spec, "ei-decree", "60의2"))
        self.assertTrue(note.startswith("정정: "))
        self.assertIn("'?'를 '≤'로", note)
        self.assertEqual(spr.correction_note([]).count("'"), 0)

    def test_h7_ledger_records_corrections_only_for_loaded_articles(self):
        import tempfile
        from unittest import mock
        spec = spr.load_targets(str(HELD))
        vectors = [{"id": f"qpack_20261113_{k}", "metadata": {
            "source_pack_id": "ei-decree", "title": "고용보험법 시행령", "source_type": "regulation",
            "section": sec}} for k, sec in enumerate(["제60조의2 피보험 단위기간 산정", "제104조의8 예술인의 피보험 단위기간 산정"])]
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            (tmp / "fetch_manifest.json").write_text(json.dumps({"ei-decree": {"url": "u", "sha256": "s"}}))
            with mock.patch.object(spr, "work_dir", lambda s: tmp):
                led = spr.build_ledger(spec, vectors)
        fixes = led["documents"]["ei-decree"]["corrections"]
        self.assertEqual([f["article"] for f in fixes], ["60의2", "104의8"])     # 104의15는 적재되지 않았다
        self.assertEqual(set(fixes[0]), {"article", "find", "replace", "image_flseq", "image_sha256", "screen_url",
                                         "latex_token", "reviewed_by"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
