#!/usr/bin/env python3
"""상담 평가 fixture 계약 오프라인 테스트.

실행: ./.venv/bin/python test_consultation_eval.py
"""

from __future__ import annotations

import json
import traceback
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from eval_consultation import REQUIRED_CASE_KEYS, load_cases, validate_cases


FIXTURE = Path(__file__).resolve().parent / "data/eval_consultation_queries.json"


def test_fixture_has_exactly_60_unique_cases() -> None:
    cases = load_cases(FIXTURE)
    assert len(cases) == 60
    assert len({case.id for case in cases}) == 60


def test_fixture_has_required_fields_and_valid_enums() -> None:
    cases = load_cases(FIXTURE)
    assert validate_cases(cases) == []
    for case in cases:
        assert set(case.__dataclass_fields__) == REQUIRED_CASE_KEYS
        assert case.risk_level in {"low", "medium", "high"}
        assert case.allowed_sources
        for value in (case.id, case.category, case.question):
            assert isinstance(value, str) and value.strip()
        assert isinstance(case.expected_intent, str)
        assert case.expected_topic is None or isinstance(case.expected_topic, str)
        assert case.expected_calculation is None or isinstance(case.expected_calculation, str)
        for values in (case.required_laws, case.allowed_sources,
                       case.required_notices, case.forbidden_claims):
            assert isinstance(values, list)
            assert all(isinstance(value, str) and value.strip() for value in values)
        assert isinstance(case.expected_values, dict)
        assert all(isinstance(key, str) and type(value) in (float, int, str)
                   for key, value in case.expected_values.items())


def test_fixture_category_distribution_matches_design() -> None:
    cases = load_cases(FIXTURE)
    counts: dict[str, int] = {}
    for case in cases:
        counts[case.category] = counts.get(case.category, 0) + 1
    assert counts == {
        "임금·계산": 10,
        "해고·징계·구제절차": 10,
        "근로시간·휴일·연차": 10,
        "퇴직금·퇴직·고용보험": 8,
        "산재·괴롭힘·차별": 8,
        "판례·행정해석·법령 조회": 8,
        "정보 부족·복합·구어체 질문": 6,
    }


def test_fixture_ids_match_design_ranges() -> None:
    cases = load_cases(FIXTURE)
    expected_ids = {
        f"{prefix}-{index:02d}"
        for prefix, count in (("wage", 10), ("dismissal", 10), ("hours", 10),
                              ("retirement", 8), ("risk", 8), ("law", 8), ("missing", 6))
        for index in range(1, count + 1)
    }
    assert {case.id for case in cases} == expected_ids


def test_load_cases_rejects_invalid_root_and_records() -> None:
    valid = json.loads(FIXTURE.read_text(encoding="utf-8"))[0]
    missing_field = dict(valid)
    del missing_field["question"]
    invalid_documents = [
        {}, None, "not a list", [None], ["not a record"], [[]],
        [missing_field], [dict(valid, unexpected=True)],
    ]
    with TemporaryDirectory() as directory:
        path = Path(directory) / "cases.json"
        for document in invalid_documents:
            path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            try:
                load_cases(path)
            except ValueError:
                pass
            else:
                raise AssertionError(f"malformed fixture accepted: {document!r}")


def test_validate_cases_reports_contract_errors() -> None:
    case = load_cases(FIXTURE)[0]
    invalid = replace(case, question=" \n\t", risk_level="urgent", allowed_sources=[])
    assert validate_cases([case, invalid]) == [
        f"duplicate id: {case.id}",
        f"empty question: {case.id}",
        f"invalid risk level: {case.id}",
        f"missing allowed_sources: {case.id}",
    ]


def main() -> int:
    tests = [
        test_fixture_has_exactly_60_unique_cases,
        test_fixture_has_required_fields_and_valid_enums,
        test_fixture_category_distribution_matches_design,
        test_fixture_ids_match_design_ranges,
        test_load_cases_rejects_invalid_root_and_records,
        test_validate_cases_reports_contract_errors,
    ]
    try:
        for test in tests:
            test()
            print(f"  ✅ {test.__name__}")
    except Exception:
        traceback.print_exc()
        return 1
    print("\n✅ 상담 평가 fixture 계약 테스트 전부 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
