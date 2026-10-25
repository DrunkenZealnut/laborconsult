"""Current and historical questions must use the right temporal filter."""
import unittest
import subprocess
import sys
from app.core.stale_rules import filter_stale_hits

def hit(text, key="old"):
    return {"id":key,"source_type":"qa","content":text,"title":"상담","score":0.9}

class TemporalTests(unittest.TestCase):
    def filt(self, text, query):
        try:
            return filter_stale_hits([hit(text),hit("일반적인 다른 근거", "other")],
                                     query=query, reference_date="2026-10-24")
        except TypeError:
            self.fail("question time not supported")

    def test_past_daily_worker_rule_is_preserved(self):
        hits,_=self.filt("일용직은 근무 10일 미만이어야 합니다.","2018년에 신청한 일용직 실업급여")
        self.assertEqual(len(hits),2)

    def test_current_parental_old_cap_is_excluded(self):
        hits,ids=self.filt("육아휴직 급여 상한은 월 150만원입니다.","2026년 육아휴직 급여")
        self.assertEqual([h["id"] for h in hits],["other"])
        self.assertIn("parental_old_cap",ids)

    def test_current_explanation_comparing_old_cap_is_preserved(self):
        hits,_=self.filt("육아휴직 급여 상한은 종전 월 150만원, 2025년부터 첫 3개월 250만원입니다.","2026년 육아휴직 급여")
        self.assertEqual(len(hits),2)

    def test_mixed_years_are_annotated_not_deleted(self):
        hits,_=self.filt("육아휴직 급여 상한은 월 150만원입니다.","2024년부터 2025년까지 육아휴직")
        self.assertEqual(len(hits),2)
        self.assertIn("기준",hits[0]["content"])

    def test_current_in_service_six_percent_is_excluded(self):
        hits,ids=self.filt("재직 중 체불임금의 지연이자는 연 6%입니다.","2026년 1월분 체불이자")
        self.assertEqual([h["id"] for h in hits],["other"])
        self.assertIn("arrears_in_service_old",ids)

    def test_old_annual_deduction_is_excluded_for_current_question(self):
        hits,ids=self.filt("근로기준법 제60조 제3항에 따라 1년 미만 사용한 연차를 다음해 15일에서 공제합니다.","2026년 연차")
        self.assertEqual([h["id"] for h in hits],["other"])
        self.assertIn("annual_old_deduction",ids)

    def test_other_benefits_and_valid_historical_amounts_are_kept(self):
        hits,ids=self.filt("구직급여 66,000원. 이직사유의 자녀 8세 이하 요건.","2024년 실업급여")
        self.assertEqual(len(hits),2)
        self.assertEqual(ids,[])

    def test_retirement_twenty_percent_does_not_validate_old_in_service_rule(self):
        hits,_=self.filt("퇴직 후 미지급금은 연 20%입니다. 재직 중 체불임금은 연 6%입니다.","2026년 재직자 체불")
        self.assertEqual([h["id"] for h in hits],["other"])

    def test_do_not_deduct_is_not_mistaken_for_deduct(self):
        hits,_=self.filt("근로기준법 제60조 제3항 개정 후에는 사용 일수를 공제하지 말고 별도로 보장합니다.","2026년 연차")
        self.assertEqual(len(hits),2)

    def test_year_attached_to_korean_text_still_controls_history(self):
        hits,_=self.filt("일용직은 근무 10일 미만이어야 합니다.","저는2018년에 신청했습니다")
        self.assertEqual(len(hits),2)

    def test_scan_export_includes_all_matches_not_only_printed_samples(self):
        import gzip,json,tempfile
        from pathlib import Path
        from app.core.stale_rules import _scan
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"corpus.jsonl.gz"; out=Path(tmp)/"matches.jsonl"
            with gzip.open(path,"wt") as f:
                for i in range(7):
                    f.write(json.dumps({"id":str(i),"source_type":"qa","text":"육아휴직 상한 150만원"})+"\n")
            try:
                _scan(str(path), samples=1, output=str(out))
            except TypeError:
                self.fail("full scan export missing")
            self.assertEqual(len(out.read_text().splitlines()),7)

class ScanCommandTests(unittest.TestCase):
    def test_requested_audit_without_scan_action_fails(self):
        result=subprocess.run([sys.executable,'-m','app.core.stale_rules','--path','missing-corpus.gz','--output','missing-report.jsonl'],text=True,capture_output=True)
        self.assertNotEqual(result.returncode,0,'missing audit action must not look successful')
        self.assertIn('--scan',result.stderr)

if __name__=="__main__":
    unittest.main()
