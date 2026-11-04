"""LLM 폴백 감시 판정 오프라인 테스트 (llm-fallback-alert, API 키·네트워크 불요)."""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
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
        rows = [row(f"2026-10-0{i}T00:00", FB) for i in (1, 2, 3)]
        for r in rows:
            r["question_text"] = "개인 상담 내용"
        out = c.render(c.judge(rows), 3)
        self.assertNotIn("개인 상담", out)
        self.assertIn("연속 폴백", out)


def warm_ok(**kw):
    """정상 예열 상태 행(production-law-api-recovery D12) — 방금 끝났고 실패·행 감소가 없다."""
    status = {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "rows": 7473,
              "prev_rows": 7473, "laws_ok": ["근로기준법"], "laws_failed": {}}
    status.update(kw)
    return status


class FakeDb:
    """created_at 내림차순 정렬된 rows를 range(a, b) 페이지로 돌려준다.

    `law_article_cache`는 예열 상태 행 조회(select·eq·execute)에 warm을 돌려준다(None이면 행 없음).
    """
    def __init__(self, data, warm="ok"):
        self.all = sorted(data, key=lambda r: r["created_at"], reverse=True)
        self.pages = 0
        self.warm = warm_ok() if warm == "ok" else warm

    def table(self, *_):
        return self

    def select(self, *_):
        return self

    def order(self, *_a, **_k):
        return self

    def eq(self, *_):
        self.data = [] if self.warm is None else [{"content": json.dumps(self.warm, ensure_ascii=False)}]
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


# ── R2: 실패 행 (llm-fallback-alert-blindspot) ──────────────────────────────

UTC = timezone.utc
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
FAILED = {"failed": True, "stage": "answer", "provider": None, "attempts": ["Claude", "OpenAI", "Gemini"],
          "failures": [{"provider": "Claude", "error_class": "AuthenticationError", "status": 401},
                       {"provider": "OpenAI", "error_class": "AuthenticationError", "status": 401},
                       {"provider": "Gemini", "error_class": "ResourceExhausted", "status": 429}],
          "error_class": "ResourceExhausted", "status": 429, "transport": "gateway"}


def iso(dt):
    return dt.isoformat()


def ago(hours, llm=OK, synthetic=False, now=NOW):
    return row(iso(now - timedelta(hours=hours)), llm, synthetic=synthetic)


class FailedRowTest(unittest.TestCase):
    def test_b1_recent_failed_alerts_even_with_one_sample(self):
        v = c.judge([ago(11, FAILED)], now=NOW)
        self.assertEqual(v.status, "alert")
        self.assertEqual(len(v.recent_failed), 1)

    def test_b2_failed_outside_window_and_r1_not_met_is_ok(self):
        rows = [ago(1, OK), ago(2, FB), ago(3, OK), ago(13, FAILED)]
        v = c.judge(rows, now=NOW)
        self.assertEqual(v.status, "ok")
        self.assertEqual(v.recent_failed, [])
        self.assertEqual(v.failed_24h, 1)            # 요약에는 센다(알림 아님)

    def test_b2b_failed_exactly_at_window_edge_alerts(self):
        """CodeRabbit #150 — 창 경계(정확히 12h 전)는 포함(`>=`). `>`로 바뀌면 잡힌다."""
        v = c.judge([ago(12, FAILED)], now=NOW)
        self.assertEqual(v.status, "alert")
        self.assertEqual(len(v.recent_failed), 1)

    def test_b3_synthetic_failed_rows_are_ignored(self):
        v = c.judge([ago(1, FAILED, synthetic=True), ago(2, FAILED, synthetic=True)], now=NOW)
        self.assertEqual(v.status, "insufficient")
        self.assertEqual(v.recent_failed, [])

    def test_b4_oct14_outage_would_have_alerted(self):
        """실측 2026-10-14: 마지막 실사용 10-11 17:22 KST + 전 제공자 실패. 구 동작은 실패가 저장되지 않아 ✅였다."""
        now = datetime(2026, 10, 14, 6, 0, tzinfo=UTC)                          # 15:00 KST 실행
        rows = [row("2026-10-11T08:22:00+00:00", OK),
                row("2026-10-12T03:00:00+00:00", OK, synthetic=True),
                row("2026-10-14T00:12:00+00:00", FAILED)]                        # 09:12 KST 실패
        self.assertEqual(c.judge(rows, now=now).status, "alert")
        without = [r for r in rows if not c._is_failed(r)]                        # 실패가 저장되지 않던 시절
        self.assertEqual(c.judge(without, now=now).status, "insufficient")

    def test_b5_fetch_covers_fail_window_past_recent_successes(self):
        """최근 12시간 안에 성공 3건이 앞에 있고, 합성 폭주 뒤 페이지에 실패 행이 있어도 R2가 본다(D-7)."""
        recent_ok = [ago(h, OK) for h in (0.5, 1.0, 1.5)]
        burst = [ago(2 + i / 60, OK, synthetic=True) for i in range(55)]
        failed = [ago(5, FAILED)]
        db = FakeDb(recent_ok + burst + failed)
        rows = c.fetch_recent(db, 3, now=NOW)
        self.assertGreaterEqual(db.pages, 2, "창을 덮기 전에 멈추면 실패 행이 페이지 밖에 남는다")
        self.assertEqual(c.judge(rows, now=NOW).status, "alert")

    def test_b5b_fetch_stops_once_window_covered(self):
        rows_in = [ago(h, OK) for h in (0.5, 1.0, 1.5)] + [ago(20, OK)] + [ago(30 + i, OK, synthetic=True) for i in range(60)]
        db = FakeDb(rows_in)
        c.fetch_recent(db, 3, now=NOW)
        self.assertEqual(db.pages, 1, "실사용 3건 + 창 밖 행이 첫 페이지에 있으면 더 읽지 않는다")

    def test_b5c_fetch_covers_summary_window_for_failed_24h(self):
        """CodeRabbit #150 — R2 창(12h)만 덮고 멈추면 12~24h 전 실패가 페이지 밖에 남아 요약 건수가 준다."""
        rows_in = [ago(h, OK) for h in (0.5, 1.0, 1.5)] \
            + [ago(13 + i / 60, OK, synthetic=True) for i in range(50)] + [ago(15, FAILED)]
        db = FakeDb(rows_in)
        v = c.judge(c.fetch_recent(db, 3, now=NOW), now=NOW)
        self.assertGreaterEqual(db.pages, 2, "24시간 창을 덮기 전에 멈추면 요약의 실패 수가 준다")
        self.assertEqual(v.failed_24h, 1)
        self.assertEqual(v.status, "ok")             # 12h 밖이라 알림은 아니다

    def test_b6_render_r2_title_summary_hint_and_no_text(self):
        rows = [ago(3, FAILED), ago(30, OK)]
        for r in rows:
            r["question_text"] = "개인 상담 내용 eyJhbGciOi"
        v = c.judge(rows, now=NOW)
        out = c.render(v, 3)
        self.assertIn("전 제공자 실패 1건", out)
        self.assertIn("마지막 성공 답변", out)
        self.assertIn("30.0시간 전", out)            # 실패 행(3h)이 아니라 성공 행(30h)의 시각(CodeRabbit #150)
        self.assertNotIn("3.0시간 전", out)
        self.assertIn("OIDC 토큰", out)                 # 401 힌트
        self.assertIn("한도", out)                      # 429 힌트
        self.assertNotIn("크레딧", out)                 # 402가 없으면 credit 힌트도 없다
        self.assertIn("failed:ResourceExhausted", out)
        self.assertNotIn("개인 상담", out)
        self.assertNotIn("eyJ", out)

    def test_b11_hints_cover_credit_auth_other(self):
        """L-4 — 402 → 크레딧, 상태 없는 GatewayAuthError → 토큰, NoProvider → 로그 힌트. 중복 없이."""
        credit = dict(FAILED, failures=[{"provider": "Claude", "error_class": "APIStatusError", "status": 402}],
                      error_class="APIStatusError", status=402)
        auth_noline = dict(FAILED, failures=[{"provider": "OpenAI", "error_class": "GatewayAuthError", "status": None}],
                           error_class="GatewayAuthError"); auth_noline.pop("status", None)
        other = dict(FAILED, failures=[{"provider": None, "error_class": "NoProvider", "status": None}],
                     error_class="NoProvider"); other.pop("status", None)
        out = c.render(c.judge([ago(1, credit), ago(2, auth_noline), ago(3, other), ago(4, credit)], now=NOW), 3)
        self.assertIn("크레딧 잔액", out)
        self.assertIn("OIDC 토큰", out)
        self.assertIn("답변 생성 실패, 다음 제공자로 전환", out)
        self.assertEqual(out.count("크레딧 잔액"), 1, "같은 힌트는 한 번만")
        legacy = dict(FAILED, failures=[], error_class="PaymentRequiredError", status=402)   # failures 없는 옛 모양
        self.assertIn("크레딧 잔액", c.render(c.judge([ago(1, legacy)], now=NOW), 3))

    def test_b12_pipeline_stage_is_not_called_provider_failure(self):
        """M-2 — stage=pipeline(답변 처리 예외)은 제목·힌트에서 전 제공자 실패와 구분한다."""
        pipe = {"failed": True, "stage": "pipeline", "provider": None, "attempts": [],
                "failures": [{"provider": None, "error_class": "KeyError", "status": None}], "error_class": "KeyError"}
        v = c.judge([ago(1, pipe)], now=NOW)
        out = c.render(v, 3)
        self.assertIn("답변 처리 예외 1건", out)
        self.assertNotIn("전 제공자 실패", out)
        self.assertIn("코드 결함", out)
        self.assertNotIn("OIDC 토큰", out)
        mixed = c.render(c.judge([ago(1, pipe), ago(2, FAILED)], now=NOW), 3)
        self.assertIn("전 제공자 실패 1건 · 답변 처리 예외 1건", mixed)
        self.assertEqual(c._failure_label([ago(1, FAILED)]), "전 제공자 실패 1건")

    def test_b13_all_failed_sample_says_failure_not_fallback(self):
        """CodeRabbit #150(Check L-5) — 표본 3건이 전부 실패 행이면 R1 문구는 '연속 폴백'이 아니라 '연속 실패'."""
        v = c.judge([ago(1, FAILED), ago(2, FAILED), ago(3, FAILED)], now=NOW)
        out = c.render(v, 3)
        self.assertTrue(c._all_failed(v))
        self.assertIn("3건 연속 실패", out)
        self.assertNotIn("연속 폴백", out)
        self.assertNotIn("폴백(1순위 실패 후 전환)", out)
        self.assertIn("마지막 성공 답변: 기록 없음(조회 범위 안 성공 답변 0건) · 최근 24시간 실패 3건", out)
        mixed = c.judge([ago(1, FB), ago(2, FB), ago(3, FB)], now=NOW)
        self.assertFalse(c._all_failed(mixed))
        self.assertIn("3건 연속 폴백", c.render(mixed, 3))

    def test_b7_degraded_failed_is_sole_reason(self):
        self.assertEqual(c.degraded(FAILED), ["failed:ResourceExhausted"])
        self.assertEqual(c.degraded({"failed": True, "attempts": ["a", "b"]}), ["failed:?"])

    def test_b8_no_real_rows_summary(self):
        v = c.judge([ago(1, OK, synthetic=True)], now=NOW)
        self.assertEqual(v.status, "insufficient")
        self.assertIn("기록 없음", c.render(v, 3))

    def test_b9_unparsable_created_at_is_counted_not_dropped_silently(self):
        bad = row("언제인지-모름", FAILED)
        v = c.judge([bad, ago(1, OK)], now=NOW)
        self.assertEqual(v.recent_failed, [])
        self.assertEqual(v.unparsed, 1)
        self.assertIn("해석 불가로 R2에서 제외한 실패 행 1건", c.render(v, 3))

    def test_b10_fail_window_cli_wiring(self):
        real_now = datetime.now(UTC)
        rows = [ago(8, FAILED, now=real_now)]
        with patch("app.core.storage.make_supabase_client", return_value=FakeDb(rows)), \
                patch("sys.argv", ["check_llm_fallback.py"]):
            self.assertEqual(c.main(), 1)                # 기본 12h 안
        with patch("app.core.storage.make_supabase_client", return_value=FakeDb(rows)), \
                patch("sys.argv", ["check_llm_fallback.py", "--fail-window", "6"]):
            self.assertEqual(c.main(), 0)                # 6h 밖·표본 1건 → 판정 불가 → 0


if __name__ == "__main__":
    unittest.main(verbosity=1)
