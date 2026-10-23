"""Q0/Q1 behavior tests using synthetic documents, never copied user posts."""
import tempfile
import unittest
import unicodedata
from pathlib import Path
from unittest.mock import patch

import crawl_qna
import importlib.util


def html_post(date="2026.03.04 03:55", answer=""):
    return f'''<div class="rd" data-docsrl="123"><div class="rd_hd">
    <h1>연차 질문</h1><span class="date">{date}</span></div>
    <div class="rd_body"><article><div class="xe_content">
    <p>2025.01.01 입사했습니다. 휴가가 궁금합니다.</p></div></article></div>
    <div class="fdb_lst_wrp"><ul class="fdb_lst_ul">{answer}</ul>
    <a>답변 글 '0'</a><p>댓글 쓰기 권한이 없습니다.</p></div></div>'''


class ParserTests(unittest.TestCase):
    def parse(self, text):
        class Response:
            status_code = 200
            def raise_for_status(self): pass
        response = Response()
        response.text = text
        with patch.object(crawl_qna.session, "get", return_value=response):
            return crawl_qna.extract_post("https://www.nodong.kr/qna/123")

    def test_empty_comments_are_not_answers(self):
        self.assertEqual(self.parse(html_post())["answers"], [])

    def test_event_date_never_becomes_posted_date(self):
        self.assertEqual(self.parse(html_post(date=""))["date"], "")

    def test_real_answer_preserves_post_date(self):
        ans = '<li class="fdb_itm"><div class="meta"><span class="date">2026.03.19 15:19</span></div><div class="xe_content"><p>실제 상담 답변입니다.</p></div></li>'
        result = self.parse(html_post(answer=ans))
        self.assertEqual(result["date"], "2026.03.04")
        self.assertEqual(result["answers"], ["실제 상담 답변입니다."])

    def test_http_200_challenge_is_error(self):
        result = self.parse("<h1>Please prove that you are human.</h1>")
        self.assertIn("error", result)

    def test_http_200_wrong_document_is_error(self):
        self.assertIn("error", self.parse(html_post().replace('data-docsrl="123"', 'data-docsrl="124"')))


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("qna_ingestion"), "manifest module not implemented")
        import qna_ingestion
        self.q = qna_ingestion

    def test_legacy_zero_answer_and_date_are_parsed_separately(self):
        text = "# 질문\n\n| 작성일 | 2026.03.04 |\n\n## 질문\n2025.01.01 입사\n\n## 답변\n[답변 글 '0'](#)\n댓글 쓰기 권한이 없습니다."
        d = self.q.parse_legacy(text, "123")
        self.assertEqual(d["posted_at"], "2026-03-04")
        self.assertEqual(d["answers"], [])
        self.assertEqual(d["answer_updated_at"], None)

    def test_hashes_ignore_unicode_and_layout_but_detect_answer_changes(self):
        a = self.q.document("123", "연차", "2026-03-04", "질문입니다.\n\n퇴사했습니다.", [])
        b = self.q.document("123", unicodedata.normalize("NFD", "연차"), "2026-03-04", "질문입니다.  퇴사했습니다.", [])
        c = self.q.document("123", "연차", "2026-03-04", "질문입니다. 퇴사했습니다.", ["추가 답변"])
        self.assertEqual(a["content_hash"], b["content_hash"])
        self.assertNotEqual(a["content_hash"], c["content_hash"])
        self.assertEqual(a["question_hash"], c["question_hash"])

    def test_inventory_preserves_duplicate_conflict_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            dirs = [Path(tmp)/"a", Path(tmp)/"b"]
            for n, p in enumerate(dirs):
                p.mkdir()
                (p/"123_연차.md").write_text(f"# 연차\n\n| 작성일 | 2026.03.04 |\n\n## 질문\n질문\n\n## 답변\n답변 {n}")
            inv = self.q.inventory(dirs)
            self.assertEqual(len(inv), 1)
            self.assertEqual(len(inv["123"]["local_paths"]), 2)
            self.assertEqual(inv["123"]["status"], "conflict")

    def test_listing_ignores_notices_related_links_and_duplicates(self):
        html = '''<a href="/qna/999">관련글</a><table class="bd_lst"><tbody>
        <tr class="notice"><td class="title"><a href="/qna/1">공지</a></td></tr>
        <tr><td class="title"><a href="/index.php?mid=qna&amp;document_srl=123">질문</a><a href="/qna/123">댓글</a></td><td class="time">2026.03.04</td></tr>
        </tbody></table>'''
        rows = self.q.parse_listing(html)
        self.assertEqual([r["post_id"] for r in rows], ["123"])
        self.assertEqual(rows[0]["posted_at"], "2026-03-04")

    def test_missing_listing_is_failure_not_empty_success(self):
        with self.assertRaises(ValueError):
            self.q.parse_listing("<h1>보안절차</h1>")

    def test_url_identity_is_numeric_only(self):
        with self.assertRaises(ValueError):
            self.q.document("../123", "제목", None, "질문", [])


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("crawl_qna_refresh"), "refresh runner not implemented")
        import crawl_qna_refresh
        self.r = crawl_qna_refresh

    def test_resume_rechecks_failed_posts_and_preserves_original(self):
        import qna_ingestion as q
        listing = '<table class="bd_lst"><tbody><tr><td class="title"><a href="/qna/123">질문</a></td><td class="time">2026.03.04</td></tr></tbody></table>'
        previous = q.public_manifest(q.document("123", "연차 질문", "2026-03-04", "기존 질문", []))
        calls = []
        def fetch(url):
            calls.append(url)
            if "page=" in url: return listing
            return "<h1>접근 불가</h1>" if len(calls) == 2 else html_post()
        with tempfile.TemporaryDirectory() as tmp:
            kwargs = dict(run_dir=Path(tmp), baseline={"123": previous}, fetch=fetch, start_page=1, end_page=1,
                          since="2026-03-01", until="2026-10-24T07:00:00+09:00", revisit_pending=True)
            first = self.r.refresh(**kwargs)
            self.assertEqual(first["failed"], 1)
            self.assertFalse((Path(tmp)/"documents/123.md").exists())
            second = self.r.refresh(**kwargs)
            self.assertEqual(second["failed"], 0)
            self.assertEqual(second["changed"], 1)
            self.assertEqual(previous["question_hash"], q.digest("기존 질문"))
            self.r.refresh(**kwargs)
            self.assertEqual(len(calls), 3)

    def test_page_failure_remains_gap_and_never_means_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.r.refresh(run_dir=Path(tmp), baseline={}, fetch=lambda url: "<h1>차단됨</h1>",
                                 start_page=1, end_page=2, since="2026-03-01",
                                 until="2026-10-24T07:00:00+09:00", revisit_pending=False)
            self.assertEqual(out["failed_pages"], [1, 2])
            self.assertFalse(out["complete"])

    def test_page_order_does_not_stop_at_first_old_date(self):
        old = '<tr><td class="title"><a href="/qna/123">오래된 글</a></td><td class="time">2025.01.01</td></tr>'
        new = '<tr><td class="title"><a href="/qna/124">새 글</a></td><td class="time">2026.03.05</td></tr>'
        def fetch(url):
            if "page=" in url:
                return '<table class="bd_lst"><tbody>' + (old if "page=1" in url else new) + '</tbody></table>'
            return html_post("2026.03.05 10:00").replace('data-docsrl="123"', 'data-docsrl="124"')
        with tempfile.TemporaryDirectory() as tmp:
            out = self.r.refresh(run_dir=Path(tmp), baseline={}, fetch=fetch,
                                 start_page=1, end_page=2, since="2026-03-01",
                                 until="2026-10-24T07:00:00+09:00", revisit_pending=False)
            self.assertEqual(out["new"], 1)
            self.assertEqual(out["visited_pages"], [1, 2])

    def test_posts_after_cutoff_time_are_not_included_on_same_day(self):
        listing='<table class="bd_lst"><tbody><tr><td class="title"><a href="/qna/123">질문</a></td><td class="time">2026.10.24</td></tr></tbody></table>'
        with tempfile.TemporaryDirectory() as tmp:
            out=self.r.refresh(run_dir=Path(tmp),baseline={},
                fetch=lambda url: listing if "page=" in url else html_post("2026.10.24 08:00"),
                start_page=1,end_page=1,since="2026-03-01",until="2026-10-24T07:00:00+09:00",
                revisit_pending=False)
            self.assertEqual(out["new"],0)
            self.assertFalse((Path(tmp)/"documents/123.md").exists())


if __name__ == "__main__":
    unittest.main()
