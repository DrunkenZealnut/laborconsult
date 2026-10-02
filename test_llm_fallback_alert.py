"""LLM 폴백 감시 판정 오프라인 테스트 (llm-fallback-alert, API 키·네트워크 불요)."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import check_llm_fallback as c

FB = {"provider": "OpenAI", "attempts": ["Claude", "OpenAI"], "fallback": True}
OK = {"provider": "Claude", "attempts": ["Claude"]}


def row(ts, llm, synthetic=False):
    meta = {"llm": llm} if llm is not None else {}
    if synthetic:
        meta["synthetic"] = True
    return {"id": ts, "created_at": ts, "metadata": meta}


class JudgeTest(unittest.TestCase):
    def test_a1_three_fallbacks_alert(self):
        rows = [row(f"2026-10-0{i}T00:00", FB) for i in (1, 2, 3)]
        self.assertEqual(c.judge(rows).status, "alert")

    def test_a2_latest_ok_clears_even_if_older_degraded(self):
        rows = [row("2026-10-04T00:00", OK)] + [row(f"2026-10-0{i}T00:00", FB) for i in (1, 2, 3)]
        self.assertEqual(c.judge(rows).status, "ok")

    def test_a3_skips_synthetic_and_missing_llm(self):
        rows = [row("2026-10-09T00:00", OK, synthetic=True), row("2026-10-08T00:00", None),
                row("2026-10-03T00:00", FB), row("2026-10-02T00:00", FB), row("2026-10-01T00:00", FB)]
        v = c.judge(rows)
        self.assertEqual(v.status, "alert")
        self.assertEqual([r["id"] for r, _ in v.considered], ["2026-10-03T00:00", "2026-10-02T00:00", "2026-10-01T00:00"])

    def test_duplicate_row_across_pages_is_counted_once(self):
        a = row("2026-10-02T00:00", FB)
        rows = [a, dict(a), row("2026-10-01T00:00", FB)]       # 같은 id가 두 페이지에 걸쳐 옴
        self.assertEqual(c.judge(rows).status, "insufficient")

    def test_a4_insufficient_sample(self):
        self.assertEqual(c.judge([row("2026-10-01T00:00", FB), row("2026-10-02T00:00", FB)]).status, "insufficient")
        self.assertEqual(c.judge([]).status, "insufficient")

    def test_a5_admin_primary_openai_is_not_degraded(self):
        primary_openai = {"provider": "OpenAI", "model": "o3", "attempts": ["OpenAI"]}
        self.assertEqual(c.degraded(primary_openai), [])
        rows = [row(f"2026-10-0{i}T00:00", primary_openai) for i in (1, 2, 3)]
        self.assertEqual(c.judge(rows).status, "ok")

    def test_a6_empty_and_intent_count_truncated_does_not(self):
        self.assertEqual(c.degraded({"attempts": ["Claude"], "empty": ["Claude"]}), ["empty"])
        self.assertEqual(c.degraded({"attempts": ["Claude"], "intent_provider": "OpenAI"}), ["intent_fallback"])
        self.assertEqual(c.degraded({"attempts": ["Claude"], "truncated": True}), [])
        # fallback 플래그가 빠진 구 기록도 attempts 길이로 잡는다
        self.assertEqual(c.degraded({"attempts": ["Claude", "OpenAI"]}), ["fallback"])

    def test_a7_august_outage_would_have_alerted_on_aug_22(self):
        """실측: 8-21~9-28 실사용 폴백. 합성 성공 기록이 사이사이 끼어 있어도 잡혀야 한다."""
        rows = [row("2026-08-19T07:43", OK),
                row("2026-08-21T22:29", FB), row("2026-08-21T22:35", FB),
                row("2026-08-22T12:14", FB),
                row("2026-08-23T13:18", OK, synthetic=True)]
        self.assertEqual(c.judge(rows).status, "alert")

    def test_render_has_no_conversation_text(self):
        r = row("2026-10-01T00:00", FB)
        r["question_text"] = "개인 상담 내용"
        out = c.render(c.judge([r, r, r]), 3)
        self.assertNotIn("개인 상담", out)
        self.assertIn("연속 폴백", out)


class FakeDb:
    """created_at 내림차순 정렬된 rows를 range(a, b) 페이지로 돌려준다."""
    def __init__(self, data):
        self.all = sorted(data, key=lambda r: r["created_at"], reverse=True)
        self.pages = 0

    def table(self, *_):
        return self

    def select(self, *_):
        return self

    def order(self, *_a, **_k):
        return self

    def range(self, a, b):
        self.data = self.all[a:b + 1]
        self.pages += 1
        return self

    def execute(self):
        return self


class FetchTest(unittest.TestCase):
    def test_pages_past_synthetic_burst_to_find_real_rows(self):
        """최신 60건이 합성(벤치마크 폭주)이어도 그 뒤의 실사용 폴백 3건을 찾아 alert."""
        syn = [row(f"2026-10-05T00:{i:02d}", OK, synthetic=True) for i in range(60)]
        real = [row(f"2026-10-0{i}T00:00", FB) for i in (1, 2, 3)]
        db = FakeDb(syn + real)
        rows = c.fetch_recent(db, 3)
        self.assertEqual(c.judge(rows).status, "alert")
        self.assertEqual(db.pages, 2)

    def test_stops_when_history_exhausted(self):
        db = FakeDb([row("2026-10-01T00:00", FB)])
        self.assertEqual(c.judge(c.fetch_recent(db, 3)).status, "insufficient")
        self.assertEqual(db.pages, 1)

    def test_page_cap_bounds_reads(self):
        db = FakeDb([row(f"2026-{m:02d}-{d:02d}T00:00", OK, synthetic=True)
                     for m in range(1, 13) for d in range(1, 29)])          # 336 synthetic
        with patch.object(c, "MAX_PAGES", 3):
            c.fetch_recent(db, 3)
        self.assertEqual(db.pages, 3)


class MainTest(unittest.TestCase):
    def test_a8_fetch_failure_exits_2(self):
        with patch("app.core.storage.make_supabase_client", return_value=None), \
                patch("sys.argv", ["check_llm_fallback.py"]):
            self.assertEqual(c.main(), 2)

    def test_alert_exits_1_and_ok_exits_0(self):

        fb_rows = [row(f"2026-10-0{i}T00:00", FB) for i in (1, 2, 3)]
        with patch("app.core.storage.make_supabase_client", return_value=FakeDb(fb_rows)), \
                patch("sys.argv", ["check_llm_fallback.py"]):
            self.assertEqual(c.main(), 1)
        with patch("app.core.storage.make_supabase_client", return_value=FakeDb([row("2026-10-04T00:00", OK)] + fb_rows)), \
                patch("sys.argv", ["check_llm_fallback.py"]):
            self.assertEqual(c.main(), 0)


if __name__ == "__main__":
    unittest.main(verbosity=1)
