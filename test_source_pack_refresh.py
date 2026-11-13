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
                continue
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

    def _sources(self, tmp: Path, img: bytes, alt: str, recorded: str | None = None):
        (tmp / "img_111.gif").write_bytes(img)
        (tmp / "w.screen.html").write_text(
            f'<p><img alt="@@LATEX@@{alt}@@/LATEX@@" src="/LSW/flDownload.do?flSeq=111" /></p>'
            '<img alt="other \\leq" src="/LSW/flDownload.do?flSeq=1112" />', encoding="utf-8")
        digest = hashlib.sha256(img).hexdigest()
        fx = {"work_id": "w", "article": "1", "image_flseq": "111", "image_sha256": recorded or digest,
              "latex_token": "\\leq"}
        return {"corrections": [fx]}, {"w": {"assets": {"111": digest}}}

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

    def _workdir(self, tmp: Path, suspect: int, verdict: str):
        spec = {"batch": "20990101"}
        out = tmp / "20990101"; out.mkdir(exist_ok=True)
        meta = {"title": "고용보험법 시행령", "section": "제60조의2 피보험 단위기간 산정", "source_pack_id": "ei-decree"}
        (out / "prepared_vectors.jsonl").write_text(json.dumps({"id": "v0", "metadata": meta}) + "\n", encoding="utf-8")
        (out / "prepare_rows.json").write_text(json.dumps([{"work_id": "ei-decree", "section": meta["section"],
                                                            "suspect_glyph": suspect}]), encoding="utf-8")
        (tmp / "review_20990101.md").write_text(f"### 고용보험법 시행령 제60조의2\n\n판정: {verdict}\n", encoding="utf-8")
        return spec

    def test_h5_upload_gate_on_remaining_suspects(self):
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            with mock.patch.object(spr, "work_dir", lambda s: tmp / s["batch"]), \
                 mock.patch.object(spr, "review_verdicts",
                                   lambda s: dict(spr._VERDICT_RE.findall((tmp / f"review_{s['batch']}.md").read_text()))):
                spec = self._workdir(tmp, 1, "적재")
                with self.assertRaises(SystemExit):
                    spr.approved_vectors(spec)
                spec = self._workdir(tmp, 1, "적재(의심 문자 확인: 원문 문장부호)")
                self.assertEqual(len(spr.approved_vectors(spec)), 1)
                spec = self._workdir(tmp, 1, "보류(근거 없음)")
                self.assertEqual(spr.approved_vectors(spec), [])
                spec = self._workdir(tmp, 0, "적재")
                self.assertEqual(len(spr.approved_vectors(spec)), 1)

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
