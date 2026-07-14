"""검색·인용·세션 모듈 오프라인 단위 테스트 (TEST-2)

LLM·네트워크·API 키 불요. 순수 함수와 파일 로더만 검증한다.
파이프라인 배선은 test_pipeline_wiring.py, 계산 엔진은 test_wage_golden.py 담당.

실행: python3 test_offline_units.py
"""

from __future__ import annotations


def test_citation_validator() -> None:
    from app.core.citation_validator import (
        extract_precedents_from_hits,
        validate_response_citations,
        build_available_citations_text,
    )

    hits = [
        {"title": "판례A", "chunk_text": "대법원 2023다302838 판결 참조"},
        {"title": "법제처 법령 조문", "chunk_text": "근로기준법 제60조, 대법원 2018다239110"},
    ]
    precs = extract_precedents_from_hits(hits)
    assert "2023다302838" in precs and "2018다239110" in precs, precs

    check = validate_response_citations(
        "대법원 2023다302838에 따르면… 한편 대법원 2006다49372는…", precs, {},
    )
    assert check["valid"] == ["2023다302838"], check
    assert check["hallucinated"] == ["2006다49372"], check

    listing = build_available_citations_text(hits)
    assert "2023다302838" in listing and "2018다239110" in listing
    print("  ✅ citation_validator: 화이트리스트 추출·환각 검출·인용 목록")


def test_rrf() -> None:
    from app.core.bm25_search import reciprocal_rank_fusion, rrf_merge_ranked_lists

    dense = [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}]
    bm25 = [{"id": "b", "title": "B"}, {"id": "c", "title": "C"}]
    fused = reciprocal_rank_fusion(dense, bm25, alpha=0.5, top_k=3)
    assert [h["id"] for h in fused][0] == "b", fused  # 양쪽 등장 → 최상위

    merged = rrf_merge_ranked_lists([
        [{"id": "x"}, {"id": "y"}],
        [{"id": "y"}, {"id": "z"}],
    ], top_k=3)
    assert [h["id"] for h in merged][0] == "y", merged  # 두 쿼리 모두 등장 → 최상위
    print("  ✅ RRF: dense+bm25 결합 / 멀티쿼리 순위 병합")


def test_merge_search_queries() -> None:
    from app.core.pipeline import _merge_search_queries

    merged = _merge_search_queries(
        decomposed=["연차수당 산정", "연차수당 산정 "],  # 중복(공백 차이)
        rule_based=["연차 발생 기준"],
        fallback="원본 질문",
        max_total=5,
    )
    assert merged == ["연차수당 산정", "연차 발생 기준"], merged
    assert _merge_search_queries([], [], "폴백") == ["폴백"]
    print("  ✅ _merge_search_queries: 중복 제거·우선순위·폴백")


def test_conflict_resolver() -> None:
    from app.core.conflict_resolver import annotate_source_priority

    note = annotate_source_priority(
        precedent_text="대법원은 근로기준법 제60조를 근거로…",
        legal_articles_text="근로기준법 제60조(연차 유급휴가) …",
        nlrc_text=None,
    )
    assert note and "우선순위" in note, note

    assert annotate_source_priority(
        precedent_text="근로기준법 제56조 관련 판례",
        legal_articles_text="근로기준법 제60조 조문",
        nlrc_text=None,
    ) is None  # 조항 겹침 없음
    print("  ✅ conflict_resolver: 동일 조항 겹침 시에만 우선순위 주석")


def test_nlrc_bundle() -> None:
    from app.core.nlrc_cases import _load_bundle

    cases = _load_bundle()
    assert len(cases) >= 300, f"번들 로드 실패 또는 데이터 축소: {len(cases)}건"
    assert "제목" in cases[0], cases[0].keys()
    print(f"  ✅ NLRC 번들 로더: {len(cases)}건 (네트워크 0회)")


def test_pipeline_helpers() -> None:
    from app.core.pipeline import (
        _normalize_wage_units, _cap, _build_sources_payload, _citation_source_hits,
    )

    p = {"wage_type": "월급", "wage_amount": 250}
    assert _normalize_wage_units(p) and p["wage_amount"] == 2_500_000
    p2 = {"wage_type": "연봉", "wage_amount": 3600}
    assert _normalize_wage_units(p2) and p2["wage_amount"] == 36_000_000
    for untouched in ({"wage_type": "시급", "wage_amount": 9000},
                      {"wage_type": "월급", "wage_amount": 3_000_000},
                      {"wage_type": "월급", "wage_amount": 5}):  # 하한 10 미만은 보정 안 함
        before = untouched["wage_amount"]
        assert not _normalize_wage_units(untouched) and untouched["wage_amount"] == before

    assert _cap("가" * 100, 10).startswith("가" * 10)
    assert "생략" in _cap("가" * 100, 10)
    assert _cap("짧음", 10) == "짧음" and _cap(None, 10) is None

    hits = _build_sources_payload(
        [{"title": "판례1", "section": "s", "source_type": "precedent", "score": 0.91},
         {"title": "판례1", "section": "s", "source_type": "precedent", "score": 0.91},  # 중복
         {"case_name": "대법원 2020다1", "score": "bad"}],  # 법제처 API 형식 + 비정상 score
        [],
    )
    assert len(hits) == 2 and hits[0]["origin"] == "rag", hits
    assert hits[1]["title"] == "대법원 2020다1" and hits[1]["score"] == 0.0, hits

    wl = _citation_source_hits(None, [{"title": "t", "chunk_text": "c"}],
                               "법조문 텍스트", None, "그래프 텍스트")
    assert len(wl) == 3, wl  # precedent_meta + 법조문 + 그래프
    print("  ✅ pipeline 헬퍼: 단위 가드·컨텍스트 캡·sources·화이트리스트 수집")


def test_session_cache_scope() -> None:
    from app.models.session import Session

    s = Session(id="t")
    s.cache_calculation("severance", {"monthly_wage": 3_000_000, "start_date": "2023-01-01"})
    s.cache_calculation("minimum_wage", {"wage_amount": 10_320})

    assert "wage_amount" not in s.get_cached_info(["severance"])  # 교차오염 차단
    assert s.get_cached_info(["severance"])["monthly_wage"] == 3_000_000
    assert s.get_cached_info(["annual_leave"]) == {}  # 무관 유형 → 빈 캐시
    assert "wage_amount" in s.get_cached_info()  # 미지정 = 전체 (하위호환)
    print("  ✅ session.get_cached_info: 계산 유형 스코프 캐시")


def test_analysis_schema() -> None:
    from app.models.schemas import AnalysisResult

    a = AnalysisResult(validation_warnings=["임금액"])
    assert a.validation_warnings == ["임금액"] and a.missing_info == []
    print("  ✅ AnalysisResult.validation_warnings 필드")


def main() -> None:
    test_citation_validator()
    test_rrf()
    test_merge_search_queries()
    test_conflict_resolver()
    test_nlrc_bundle()
    test_pipeline_helpers()
    test_session_cache_scope()
    test_analysis_schema()
    print("\n✅ 오프라인 단위 테스트 전부 통과")


if __name__ == "__main__":
    main()
