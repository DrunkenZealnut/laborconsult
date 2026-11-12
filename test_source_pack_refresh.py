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
        """적재 전 관문 — 검토 파일의 판정 칸이 대상 조문 전부에 채워져 있어야 한다(D4)."""
        spec = spr.load_targets(str(TARGETS))
        verdicts = spr.review_verdicts(spec)
        if not verdicts:
            self.skipTest("review 파일 없음 — prepare 후 로컬 관문")
        for law in spec["laws"]:
            for art in law["articles"]:
                m = re.fullmatch(r"(\d+)(?:의(\d+))?", art)
                label = f"{law['law']} 제{m.group(1)}조" + (f"의{m.group(2)}" if m.group(2) else "")
                self.assertTrue(verdicts.get(label), label)
                self.assertRegex(verdicts[label], r"^(적재|보류)", label)

    def test_targets_exclude_empty_and_out_of_scope_laws(self):
        spec = spr.load_targets(str(TARGETS))
        laws = {l["law"] for l in spec["laws"]}
        self.assertNotIn("임금채권보장법", laws)      # 빈 자리 조문(D1)
        self.assertNotIn("민사집행규칙", laws)


class MetadataSchemaTest(unittest.TestCase):
    def test_s5_metadata_keys_match_prior_batch_schema(self):
        """기존 배치(`qpack_20261009_`)와 같은 메타데이터 키 — 공식 증거 2차 조회·BM25 빌더가 같은 필드를 읽는다."""
        path = ROOT / "data" / "source_pack_refresh" / "20261112" / "prepared_vectors.jsonl"
        if not path.exists():
            self.skipTest("prepare 산출물 없음 — 로컬 관문")
        want = {"source_type", "title", "section", "text", "chunk_text", "official_url", "url", "official", "issuer",
                "date", "effective_date", "retrieved_on", "source_batch", "source_pack_id", "source_sha256",
                "chunk_sha256", "chunk_index", "version_scope", "rights_basis"}
        for line in path.read_text(encoding="utf-8").splitlines():
            meta = json.loads(line)["metadata"]
            self.assertEqual(set(meta), want)
            self.assertIs(meta["official"], True)
            self.assertEqual(meta["source_batch"], "sourcepack_20261112")
            self.assertIsInstance(meta["chunk_index"], int)


if __name__ == "__main__":
    unittest.main(verbosity=2)
