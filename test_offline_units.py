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


def test_board_posts_schema_source() -> None:
    """D5 — board_posts 스키마 단일 출처 (board-posts-schema-fix FR-07)

    ⚠️ 이 테스트는 **DDL 파일 ↔ 코드 상수**만 대조한다. 실제 DB가 어긋났는지는
       CI에서 알 수 없다(자격증명 없음) — 그건 check_schema.py의 몫이고,
       2026-08-13에 발견된 드리프트(8컬럼 중 5개 결손)가 정확히 그 유형이었다.
       "CI가 스키마를 검증한다"고 읽지 말 것.
    """
    import pathlib

    from app.core.storage import (
        BOARD_POST_COLUMNS,
        BOARD_POST_PUBLIC_COLUMNS,
        board_post_select,
    )

    ddl = pathlib.Path("supabase_board_posts.sql").read_text(encoding="utf-8")
    for col in BOARD_POST_COLUMNS:
        assert col in ddl, f"DDL 파일에 컬럼이 없다: {col} (supabase_board_posts.sql)"

    for col in BOARD_POST_PUBLIC_COLUMNS:
        assert col in BOARD_POST_COLUMNS, f"공개 컬럼이 전체 집합에 없다: {col}"

    # 노출 회귀 차단 — 편의로 공개 목록에 넣는 순간 게시판 응답으로 새어나간다.
    for col in ("password_hash", "ip_hash", "status"):
        assert col not in BOARD_POST_PUBLIC_COLUMNS, f"민감 컬럼이 공개 목록에 있다: {col}"

    # select 문자열은 상수에서 생성한다 — 호출부가 각자 나열하면 다시 갈라진다.
    assert board_post_select() == ", ".join(BOARD_POST_PUBLIC_COLUMNS)
    assert "password_hash" not in board_post_select()

    # DDL이 anon DELETE 정책을 만들지 않는지 (CLAUDE.md 규약)
    assert "FOR DELETE" not in ddl.upper(), "anon DELETE 정책이 DDL에 있다"
    # soft delete는 단방향이어야 한다
    assert "status = 'active'" in ddl and "status = 'deleted'" in ddl, \
        "UPDATE 정책의 단방향 조건이 DDL에 없다"

    print("  ✅ board_posts 스키마: DDL↔상수 8컬럼, 민감 컬럼 미노출, DELETE 정책 부재")


_DDL_FILES = (
    "supabase_schema.sql",
    "supabase_abuse_guard.sql",
    "supabase_board_posts.sql",
    "supabase_retention_purge.sql",
)


def _ddl_sources() -> dict[str, str]:
    import pathlib
    return {f: pathlib.Path(f).read_text(encoding="utf-8") for f in _DDL_FILES}


def _strip_sql_comments(sql: str) -> str:
    """주석·블록주석(/* */)을 제거한 실행문만 남긴다."""
    import re
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return "\n".join(l for l in sql.split("\n") if not l.strip().startswith("--"))


def test_ddl_schema_qualified() -> None:
    """D6 — DDL의 객체 참조가 전부 스키마 한정인지 (supabase-schema-migration §3.3)

    스키마를 생략하면 search_path 에 따라 public 의 동명 객체를 건드린다.
    2026-08-13 board_posts 사고가 정확히 그 경로였다 — purge 함수가 다른 앱의
    테이블을 지우도록 작성돼 있었다.
    """
    import re

    ours = {"laborconsult", "storage", "cron", "information_schema", "pg_catalog"}
    # CTE 이름 — 스키마 한정 대상이 아니다.
    allowed_bare = {"expired", "queued", "removed"}
    # 매치가 테이블 참조가 아닌 문맥. GRANT/REVOKE 의 역할, 정책의 FOR ... TO 등.
    not_a_table = {
        "to", "on", "set", "all", "public", "anon", "authenticated", "service_role",
        "select", "insert", "update", "delete", "only", "each", "row",
        "grant", "revoke", "function", "table", "column", "policy",
        "pg_constraint", "pg_policies", "pg_tables", "pg_proc",
        "pg_namespace", "pg_roles", "pg_class",
    }
    pattern = re.compile(
        r"\b(?:FROM|JOIN|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+"
        r"(?:ONLY\s+)?([A-Za-z_%][A-Za-z0-9_]*)(\.[A-Za-z_][A-Za-z0-9_]*)?",
        re.I,
    )

    for name, raw in _ddl_sources().items():
        for m in pattern.finditer(_strip_sql_comments(raw)):
            head, tail = m.group(1), m.group(2)
            if tail:                                          # schema.table 형태
                assert head in ours, f"{name}: 알 수 없는 스키마 참조 {head}{tail}"
                continue
            low = head.lower()
            if low in not_a_table or low in allowed_bare or head.startswith("%"):
                continue
            raise AssertionError(
                f"{name}: 스키마 미지정 참조 '{head}' — laborconsult. 로 한정할 것"
            )
    print("  ✅ DDL 스키마 한정: 미지정 객체 참조 0건")


def test_ddl_search_path() -> None:
    """D7 — SECURITY DEFINER 함수의 search_path 에 public 이 없을 것

    SECURITY DEFINER 는 정의자 권한으로 실행되고 미지정 참조는 search_path 로
    해석된다. public 이 목록에 있으면 함수가 다른 앱의 테이블을 읽고 쓴다.
    """
    import re

    found = 0
    for name, raw in _ddl_sources().items():
        # 주석에는 "구 버전은 search_path = public 이었다" 같은 설명이 있다.
        # 실행문만 검사해야 한다.
        for m in re.finditer(r"SET\s+search_path\s*=\s*([^\n;]+)",
                             _strip_sql_comments(raw), re.I):
            entries = [e.strip().strip("'\"") for e in m.group(1).split(",")]
            found += 1
            assert "public" not in entries, (
                f"{name}: search_path 에 public 이 있다 ({m.group(1).strip()}) — "
                "미지정 참조가 다른 앱 스키마로 샌다"
            )
            assert "laborconsult" in entries, (
                f"{name}: search_path 에 laborconsult 가 없다 ({m.group(1).strip()})"
            )
    assert found >= 7, f"search_path 지정 함수가 너무 적다: {found}개"
    print(f"  ✅ SECURITY DEFINER search_path {found}건: public 부재·laborconsult 포함")


def test_ddl_no_quoted_identifiers() -> None:
    """D8 — DDL 실행문에 큰따옴표 인용 식별자가 없을 것

    SQL Editor 붙여넣기에서 큰따옴표가 스마트 따옴표(U+201C)로 바뀌면
    `syntax error at or near ...` 로 죽는다(2026-08-13 실제 발생).
    검증용 SELECT 의 컬럼 별칭은 예외로 둔다.
    """
    import re

    for name, raw in _ddl_sources().items():
        body = _strip_sql_comments(raw)
        for m in re.finditer(r'"([^"]+)"', body):
            ident = m.group(1)
            # AS "별칭" 형태(검증 SELECT의 한글 헤더)만 허용
            head = body[max(0, m.start() - 4):m.start()].rstrip().upper()
            assert head.endswith("AS"), (
                f"{name}: 큰따옴표 식별자 \"{ident}\" — 인용부호 없는 이름을 쓸 것"
            )
    print("  ✅ DDL 인용 식별자: AS 별칭 외 0건")


def test_code_tables_defined_in_ddl() -> None:
    """D9 — 코드가 .table()로 접근하는 이름이 DDL에 정의돼 있을 것

    2026-08-13 이전 프로젝트 전환에서 law_article_cache 가 DDL 에 없어 조용히
    누락됐다(법령 L2 캐시가 404). CI 가 그것을 잡을 수 있는 유일한 지점이다.
    """
    import pathlib
    import re

    ddl = "\n".join(_ddl_sources().values())
    defined = set(re.findall(r"CREATE TABLE IF NOT EXISTS\s+laborconsult\.(\w+)", ddl))

    used: set[str] = set()
    for path in ("app", "api"):
        for py in pathlib.Path(path).rglob("*.py"):
            used |= set(re.findall(r'\.table\("(\w+)"\)', py.read_text(encoding="utf-8")))
    for py in ("dedupe_board.py", "check_schema.py", "purge_storage_orphans.py"):
        p = pathlib.Path(py)
        if p.exists():
            used |= set(re.findall(r'\.table\("(\w+)"\)', p.read_text(encoding="utf-8")))

    missing = used - defined
    assert not missing, f"코드가 쓰는데 DDL에 없는 테이블: {sorted(missing)}"
    print(f"  ✅ 테이블 정의 대조: 코드 사용 {len(used)}종 ⊆ DDL 정의 {len(defined)}종")


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
    test_board_posts_schema_source()
    test_ddl_schema_qualified()
    test_ddl_search_path()
    test_ddl_no_quoted_identifiers()
    test_code_tables_defined_in_ddl()
    print("\n✅ 오프라인 단위 테스트 전부 통과")


if __name__ == "__main__":
    main()
