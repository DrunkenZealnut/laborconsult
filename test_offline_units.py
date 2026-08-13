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

    # 법령API/NLRC/GraphRAG도 sources에 노출 — 인용 화이트리스트와 동일 소스 집합이어야 함
    hits2 = _build_sources_payload(
        [], [], legal_articles_text="법조문", nlrc_text="NLRC", graph_context="그래프",
    )
    assert {h["origin"] for h in hits2} == {"legal_api", "nlrc", "graph"}, hits2

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


def test_dedupe_normalization() -> None:
    """D1 — 중복 판정 정규화 (board-duplicate-cleanup FR-01)"""
    import unicodedata
    from dedupe_board import _norm_question

    base = "주휴수당이 뭔가요?"
    variants = [
        base,
        " 주휴수당이  뭔가요 ",           # 공백 차이
        "주휴수당이뭔가요",                # 구두점·공백 없음
        "주휴수당이 뭔가요???",            # 구두점 반복
        unicodedata.normalize("NFD", base),  # 자모 분해 — NFC 선행이 없으면 갈라진다
    ]
    keys = {_norm_question(v) for v in variants}
    assert len(keys) == 1, f"같은 질문이 {len(keys)}개 키로 갈림: {keys}"

    assert _norm_question("연차수당이 뭔가요?") != _norm_question(base), \
        "다른 질문이 같은 키로 병합됨"
    assert _norm_question("???") == "", "기호만 있는 질문은 빈 키여야 함"
    print("  ✅ dedupe 정규화: NFD/공백/구두점 흡수, 다른 질문은 분리")


def test_dedupe_representative() -> None:
    """D2 — 대표 선정: 최신 1건 유지 + 동률 시 결정론적 (FR-02)"""
    from dedupe_board import pick_representative, plan_dedupe, keep_of, drop_of

    group = [
        {"id": "a", "created_at": "2026-03-16T00:00:00Z", "question_text": "Q"},
        {"id": "b", "created_at": "2026-08-06T00:00:00Z", "question_text": "Q"},
        {"id": "c", "created_at": "2026-07-01T00:00:00Z", "question_text": "Q"},
    ]
    rep, rest = pick_representative(group)
    assert rep["id"] == "b", f"최신이 아닌 {rep['id']}가 선택됨"
    assert {r["id"] for r in rest} == {"a", "c"}, rest

    # created_at 동률 → id 사전순 최댓값, 그리고 재실행 시 동일 결과(멱등)
    tie = [
        {"id": "x1", "created_at": "2026-08-06T00:00:00Z", "question_text": "Q"},
        {"id": "x9", "created_at": "2026-08-06T00:00:00Z", "question_text": "Q"},
    ]
    assert pick_representative(tie)[0]["id"] == "x9"
    assert pick_representative(list(reversed(tie)))[0]["id"] == "x9", "순서에 따라 결과가 달라짐"

    # 카테고리 불일치 그룹 검출
    rows = [
        {"id": "p", "created_at": "2026-01-01T00:00:00Z", "question_text": "같은 질문", "category": "해고"},
        {"id": "q", "created_at": "2026-02-01T00:00:00Z", "question_text": "같은  질문", "category": "임금·수당"},
        {"id": "r", "created_at": "2026-01-01T00:00:00Z", "question_text": "다른 질문", "category": "퇴직금"},
    ]
    plan = plan_dedupe(rows)
    keep, drop = keep_of(plan), drop_of(plan)
    assert len(keep) == 2, keep
    assert len(drop) == 1, drop
    assert drop[0]["id"] == "p", drop
    conflicts = [(rep, rest) for rep, rest in plan
                 if {r.get("category") for r in rest} - {rep.get("category")}]
    assert len(conflicts) == 1, conflicts
    print("  ✅ dedupe 대표 선정: 최신 유지·동률 결정론적·카테고리 불일치 검출")


def test_synthetic_session_guard() -> None:
    """D3 — 합성 세션 판정 G-C (board-duplicate-cleanup FR-05)"""
    from app.core.storage import _is_synthetic_session, SYNTHETIC_SESSION_PREFIXES

    for sid in ("bench_1", "test_x", "cmp_o3_1", "verify_gpt", "eval_a"):
        assert _is_synthetic_session(sid), f"합성 세션 미검출: {sid}"

    # 실사용 세션은 uuid4().hex[:12] — 16진수라 예약 접두사와 겹칠 수 없다
    for sid in ("a1b2c3d4e5f6", "0123456789ab", "deadbeefcafe", "", None):
        assert not _is_synthetic_session(sid), f"정상 세션 오탐: {sid}"

    assert all(p.endswith("_") for p in SYNTHETIC_SESSION_PREFIXES), \
        "접두사는 '_'로 끝나야 hex12와 충돌하지 않는다"

    # 호출부의 metadata 원본을 제자리 변경하면 파이프라인이 이후 참조하는 값이
    # 오염된다(Design §4.3). 실제 save_conversation을 거쳐야 방어력이 있으므로
    # Supabase 클라이언트를 스텁으로 주입한다.
    from app.core.storage import save_conversation, ConversationRecord

    captured: dict = {}

    class _StubSB:
        def table(self, *a, **kw): return self
        def select(self, *a, **kw): return self
        def eq(self, *a, **kw): return self
        def update(self, *a, **kw): return self
        def insert(self, payload, *a, **kw):
            captured.update(payload)
            return self
        def execute(self, *a, **kw):
            return type("R", (), {"data": []})()

    original = {"has_attachments": False}
    rec = ConversationRecord(session_id="bench_42", category="임금·수당",
                             question_text="Q", answer_text="A", metadata=original)
    save_conversation(_StubSB(), rec)
    assert captured["metadata"].get("synthetic") is True, captured["metadata"]
    assert "synthetic" not in original, f"호출부 metadata 원본이 변형됨: {original}"
    assert rec.metadata is original, "record.metadata 참조가 교체됨"

    captured.clear()
    save_conversation(_StubSB(), ConversationRecord(
        session_id="a1b2c3d4e5f6", category="해고", question_text="Q", answer_text="A"))
    assert "synthetic" not in captured["metadata"], captured["metadata"]

    print("  ✅ 합성 세션 판정: 예약 접두사 5종 검출, hex12 오탐 0, 원본 metadata 비변형")


def test_public_exclude_keys() -> None:
    """D4 — 공개 제외 집행 G-D (board-duplicate-cleanup FR-06)

    게시판(api/index.py)·정리 스크립트(dedupe_board.py)·저장부(pipeline.py)가
    같은 집합을 보는지는 **import가 구조적으로 보장**한다(단일 출처는
    app/core/storage.py). 여기서는 계약 내용만 고정한다.
    """
    from app.core.storage import PUBLIC_EXCLUDE_KEYS, is_public_excluded
    from dedupe_board import PUBLIC_EXCLUDE_KEYS as SCRIPT_KEYS

    for key in ("guard_flag", "truncated", "textbook", "synthetic"):
        assert key in PUBLIC_EXCLUDE_KEYS, f"제외 키 누락: {key}"
    assert SCRIPT_KEYS is PUBLIC_EXCLUDE_KEYS, "정리 스크립트가 별도 집합을 씀"

    assert is_public_excluded({"synthetic": True})
    assert is_public_excluded({"guard_flag": "scope_monitor"})
    assert not is_public_excluded({"has_attachments": True})
    # PostgREST 필터는 키 부재(IS NULL)로 판정하므로 명시적 False를 쓰면 두 경로가
    # 갈라진다 — 이 키들은 True로만 기록한다는 계약을 여기서 고정한다.
    assert not is_public_excluded({"synthetic": False}), "False는 제외 대상이 아니다"
    assert not is_public_excluded(None) and not is_public_excluded("문자열")
    print("  ✅ 공개 제외 키 4종 계약 + 단일 출처(app/core/storage.py) 공유")


def main() -> None:
    test_citation_validator()
    test_rrf()
    test_merge_search_queries()
    test_conflict_resolver()
    test_nlrc_bundle()
    test_pipeline_helpers()
    test_session_cache_scope()
    test_analysis_schema()
    test_dedupe_normalization()
    test_dedupe_representative()
    test_synthetic_session_guard()
    test_public_exclude_keys()
    print("\n✅ 오프라인 단위 테스트 전부 통과")


if __name__ == "__main__":
    main()
