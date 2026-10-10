"""공식 근거 미도달과 단위 추정의 재발을 실제 전달 문맥에서 검사한다."""
from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest import mock

from app.config import AppConfig
from app.core import pipeline
from app.models.schemas import AnalysisResult
from app.models.session import Session


class FollowupPipelineTest(unittest.TestCase):
    def run_question(self, query, *, consultation=False):
        """Run the real pipeline with external answer generation replaced by a captured response."""
        captured = {}
        config = AppConfig(openai_client=object(), pinecone_index=None,
                           claude_client=object(), supabase=None)
        config.law_api_key = None
        analysis = AnalysisResult(requires_calculation=False)
        if consultation:
            analysis.consultation_type = 'law_interpretation'
            analysis.consultation_topic = '실업급여'

        def answer(messages, system, config):
            """Capture the delivered LLM context and yield one deterministic answer."""
            captured.update(user=messages[-1]['content'], system=system)
            yield '확인할 사항을 안내합니다.'

        with mock.patch.object(pipeline, 'analyze_intent', return_value=analysis), \
             mock.patch.object(pipeline, '_answer_providers', lambda c: [('OpenAI', answer)]), \
             mock.patch.object(pipeline, 'process_consultation', return_value=('기존 법률상담 문맥', [])):
            events = list(pipeline.process_question(query, Session(id='followup-offline'), config))
        captured['events'] = events
        return captured

    def test_dismissal_without_size_delivers_scope_and_matching_sources(self):
        """Unknown employer size must deliver statutory scope together with its sources."""
        result = self.run_question('소장이 팀장에게 지시해서 해고했습니다. 부당해고 구제신청 가능한가요?')
        self.assertIn('제11조(적용 범위)', result['user'])
        self.assertIn('상시 4명 이하', result['user'])
        self.assertIn('제28조(부당해고등의 구제신청)', result['user'])
        hits = next(e['hits'] for e in result['events'] if e['type'] == 'sources')
        self.assertTrue(any(h['origin'] == 'official_evidence' and '제11조' in h['section'] for h in hits))

    def test_naked_reduction_is_a_confirmation_not_an_invented_currency(self):
        """A bare wage reduction amount must reach the answer without an invented unit."""
        result = self.run_question('급여를 조정해서 원래받던금액보다 30정도 적게 받고있습니다.')
        self.assertIn('[질문 사실 확인]', result['user'])
        self.assertIn('30정도 적게', result['user'])
        self.assertIn('단위를 확인', result['user'])
        self.assertNotIn('30만', result['user'])

    def test_sickness_deadline_conditions_reach_both_answer_branches(self):
        """Both answer branches must receive the conditional sickness benefit deadlines."""
        for consultation in (False, True):
            result = self.run_question('상병급여는 언제까지 청구해야 하나요?', consultation=consultation)
            self.assertIn('제82조', result['user'])
            self.assertIn('14일', result['user'])
            self.assertIn('30일', result['user'])
            self.assertIn('7일', result['user'])
            self.assertIn('사유가 없어진 날', result['user'])

    def test_all_selected_official_sources_reach_the_source_event(self):
        """Every delivered official source must survive the source event limit."""
        from app.core.consultation_evidence import select_evidence
        query = '소장이 팀장에게 해고를 지시했습니다. 부당해고 구제신청 가능한가요?'
        selected = select_evidence(query)
        result = self.run_question(query)
        hits = next(e['hits'] for e in result['events'] if e['type'] == 'sources')
        self.assertEqual({(h['title'], h['section']) for h in selected.hits},
                         {(h['title'], h['section']) for h in hits if h['origin'] == 'official_evidence'})
        self.assertGreater(len(selected.hits), 5)

    def test_search_limit_is_preserved_alongside_complete_official_evidence(self):
        """Ordinary search results remain capped alongside the complete official sources."""
        issue = [{'title': f'법령{i}', 'section': f'제{i}조'} for i in range(8)]
        search = [{'title': f'검색{i}'} for i in range(9)]
        self.assertEqual(len(pipeline._build_sources_payload(search, [])), 5)
        combined = pipeline._build_sources_payload(search, [], issue_hits=issue)
        self.assertEqual(sum(h['origin'] == 'official_evidence' for h in combined), 8)
        self.assertEqual(sum(h['origin'] == 'rag' for h in combined), 5)


class EvidenceSelectionTest(unittest.TestCase):
    def test_missing_catalog_is_visible_without_breaking_consultation(self):
        """A missing catalog must log its path while consultation remains available."""
        from app.core import consultation_evidence as evidence
        with tempfile.TemporaryDirectory() as directory:
            evidence.evidence_groups.cache_clear()
            try:
                with mock.patch.object(evidence, 'DATA_DIR', Path(directory)):
                    with self.assertLogs(evidence.logger, level='ERROR') as captured:
                        selected = evidence.select_evidence('상병급여 청구 기한')
                self.assertEqual(selected.hits, [])
                self.assertEqual(selected.text, '')
                self.assertIn(directory, '\n'.join(captured.output))
            finally:
                evidence.evidence_groups.cache_clear()

    def test_benefit_delays_are_not_unpaid_employment_wages(self):
        """Benefit payment delays must not trigger resignation evidence for unpaid wages."""
        from app.core.consultation_evidence import select_evidence
        for query in ('실업급여 지급이 늦어요', '구직급여 지급이 지연돼요',
                      '실업급여와 상병급여 지급이 늦어요'):
            self.assertNotIn('ei_wage_arrears_resignation', select_evidence(query).groups, query)
        self.assertIn('ei_wage_arrears_resignation',
                      select_evidence('급여 지급이 늦어 퇴사하면 실업급여를 받을 수 있나요?').groups)

    def test_health_insurance_is_not_a_health_related_resignation(self):
        """Health insurance terms must not trigger evidence for resignation due to illness."""
        from app.core.consultation_evidence import select_evidence
        for query in ('퇴사 후 건강보험은 어떻게 되나요?',
                      '퇴사 후 건강보험과 실업급여는 어떻게 되나요?',
                      '퇴사 후 건강 보험과 구직급여는 어떻게 되나요?'):
            self.assertNotIn('ei_health_resignation', select_evidence(query).groups, query)
        self.assertIn('ei_health_resignation',
                      select_evidence('건강 악화로 퇴사하면 실업급여를 받을 수 있나요?').groups)

    def source(self, **updates):
        """Build a complete, verified legal source fixture with optional invalid fields."""
        source = {'id': 'verified', 'title': '법령', 'section': '제1조',
                  'content': '검증된 조문 전체입니다.', 'source_type': 'law',
                  'official_url': 'https://www.law.go.kr/법령/근로기준법',
                  'effective_date': '2026-10-08',
                  'provenance': {'sha256': 'a' * 64}}
        return dict(source, **updates)

    def group(self, source=None, **updates):
        """Build a group requiring both an unpaid wage term and an employment wage term."""
        group = {'id': 'example', 'patterns': ['체불'], 'all_patterns': ['임금'],
                 'reviewed_at': '2026-10-10', 'guidance': '조건을 확인합니다.',
                 'sources': [source or self.source()]}
        return dict(group, **updates)

    def select(self, groups, query='임금 체불', **options):
        """Select against a fixed review date using explicitly supplied groups."""
        from app.core.consultation_evidence import select_evidence
        return select_evidence(query, groups=tuple(groups), as_of='2026-10-10', **options)

    def test_complete_content_and_only_rendered_sources_survive_budget(self):
        """Budget omissions must remove whole source groups and their citation hits."""
        selected = self.select([self.group()])
        self.assertIn('검증된 조문 전체입니다.', selected.text)
        self.assertEqual([h['id'] for h in selected.hits], ['verified'])
        limited = self.select([self.group()], max_chars=125)
        self.assertEqual(limited.hits, [])
        self.assertNotIn('검증된 조문', limited.text)
        self.assertLessEqual(len(limited.text), 125)

    def test_future_or_unproven_source_drops_its_guidance_as_well(self):
        """Future or unverified sources must also suppress their dependent guidance."""
        for bad in (self.source(effective_date='2027-01-01'),
                    self.source(provenance={}), self.source(official_url='http://law.go.kr')):
            selected = self.select([self.group(bad)])
            self.assertEqual(selected.hits, [])
            self.assertNotIn('조건을 확인합니다', selected.text)

    def test_all_conditions_and_deduplication(self):
        """Required query conditions and source deduplication must hold across groups."""
        self.assertEqual(self.select([self.group()], query='임대차 체불').groups, [])
        selected = self.select([self.group(), self.group(id='second')])
        self.assertEqual(selected.groups, ['example', 'second'])
        self.assertEqual(len(selected.hits), 1)
        self.assertEqual(selected.text.count('검증된 조문 전체입니다.'), 1)

    def test_company_site_manager_is_not_a_civil_complaint(self):
        """The Korean term for a site manager must not trigger civil complaint evidence."""
        from app.core.consultation_evidence import select_evidence
        selected = select_evidence('소장이 팀장에게 해고를 지시했습니다. 구제신청 가능한가요?')
        self.assertNotIn('labor_civil_damage_and_response', selected.groups)

    def test_civil_terms_with_particles_find_the_same_official_evidence(self):
        """Korean particles must not hide complaint withdrawal or damages questions."""
        from app.core.consultation_evidence import select_evidence
        for query, group in (
            ('임금체불 때문에 고소를 취하하려고 합니다.', 'wage_complaint_withdrawal'),
            ('회사가 퇴사 때문에 손해를 배상하라고 합니다.', 'labor_civil_damage_and_response'),
        ):
            self.assertIn(group, select_evidence(query).groups, query)

    def test_cut_hours_rounding_and_money_demands_are_not_dismissals(self):
        """Reduced hours, numeric rounding and money demands must not imply dismissal."""
        from app.core.consultation_evidence import select_evidence
        for query in ('급여 계산 결과에서 소수점이 잘리는 이유가 뭔가요?',
                      '근무시간이 잘리면 주휴수당이 줄어드나요?',
                      '제가 자진퇴사했는데 사장이 돈을 요구합니다.'):
            self.assertNotIn('dismissal_scope', select_evidence(query).groups, query)

    def test_legacy_official_case_number_can_be_cited_without_becoming_a_date(self):
        """Verified legacy case numbers remain valid while ordinary dates are ignored."""
        from app.core.citation_validator import extract_precedents_from_hits, validate_response_citations
        available = extract_precedents_from_hits([
            {'case_no': '99마5143', 'title': '부동산강제경매기각', 'chunk_text': '공식 판결요지'}])
        self.assertIn('99마5143', available)
        self.assertEqual(available['99마5143']['year'], 1999)
        result = validate_response_citations('대법원 99마5143, 2026년 9월, 99년 5월', available)
        self.assertEqual(result['valid'], ['99마5143'])
        self.assertEqual(result['hallucinated'], [])

    def test_currency_is_never_a_legacy_case_number(self):
        """Currency amounts must not be extracted or validated as legacy case numbers."""
        from app.core.citation_validator import extract_precedents_from_hits, validate_response_citations
        amounts = '월급은 85만5000원입니다. 소액임금 50만 3000원. 2026년 9월.'
        self.assertEqual(extract_precedents_from_hits([{'chunk_text': amounts}]), {})
        self.assertEqual(validate_response_citations(amounts, {})['total_cited'], 0)

    def test_official_decision_dates_reach_the_answer_context(self):
        """Verified judgment dates must accompany the related auction evidence."""
        from app.core.consultation_evidence import select_evidence
        selected = select_evidence('체불임금 지연이자를 경매 배당요구했습니다.')
        self.assertIn('재판일: 2000-02-12', selected.text)
        self.assertIn('재판일: 2022-04-28', selected.text)

    def test_health_resignation_delivers_annex9_and_current_work_capacity(self):
        """Illness resignation must deliver both annex grounds and current work capacity."""
        from app.core.consultation_evidence import select_evidence
        selected = select_evidence('건강 악화로 퇴사했는데 퇴사 후 진단서로 실업급여를 신청할 수 있나요?')
        self.assertIn('ei_health_resignation', selected.groups)
        self.assertIn('9.', selected.text)
        self.assertIn('근로의 의사와 능력', selected.text)

    def test_work_during_benefits_delivers_the_employment_thresholds(self):
        """Work during benefits must deliver the statutory employment thresholds."""
        from app.core.consultation_evidence import select_evidence
        selected = select_evidence('실업급여를 받는 중 주 10시간 알바를 3개월 할 때 취업으로 인정하나요?')
        self.assertIn('ei_short_work_recognition', selected.groups)
        for term in ('제92조', '60시간', '15시간', '3개월'):
            self.assertIn(term, selected.text)

    def test_partial_attendance_is_not_left_to_a_company_absence_label(self):
        """Partial attendance must receive evidence distinguishing full day absence."""
        from app.core.consultation_evidence import select_evidence
        for query in ('주휴수당은 수요일 무급 반차로 4시간 출근하면 없나요?',
                      '주휴수당 계산에서 4시간 조퇴한 날을 결근으로 처리할 수 있나요?'):
            selected = select_evidence(query)
            self.assertIn('weekly_holiday_partial_attendance', selected.groups)
            self.assertTrue(any(h.get('content_kind')=='authored_summary' for h in selected.hits))
            self.assertIn('전일', selected.text)

    def test_explicit_units_and_work_hours_do_not_become_currency_questions(self):
        """Explicit units and changes in work hours must not create currency questions."""
        from app.core.consultation_evidence import question_fact_notes
        for query in ('급여가 30만원 정도 적게 지급됐어요.', '급여가 30% 감액됐어요.',
                      '급여는 그대로이고 근무시간이 30정도 적게 예정돼요.',
                      '근무시간이 30정도 적게 줄었어요.'):
            self.assertEqual(question_fact_notes(query), '', query)


if __name__ == '__main__':
    unittest.main()
