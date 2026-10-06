"""노동법 지식 그래프 오프라인 구축 스크립트.

사용법:
  python build_graph.py                 # 전체 구축 (Legal API 사용)
  python build_graph.py --skip-api      # Legal API 호출 생략 (매핑만 사용)
  python build_graph.py --stats         # 기존 그래프 통계만 출력
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse


import networkx as nx

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

GRAPH_PATH = Path("data/graph_data.json")
CACHE_DIR = Path("data/article_cache")

# ── 그래프 대상 법률 (법령명 기반 — MST 사전매핑 금지) ───────────────────────
# ⚠️ 과거에는 legal_api.py와 같은 MST 사전매핑을 복제해 두었는데, 원본이
# LM(법령명) 조회로 전환된 뒤(law-version-drift) 이쪽만 낡은 판본 12종이
# 남아 있었다 — 8종이 실측에서 '낡음' 판정된 바로 그 값이었고, 재빌드하면
# 낡은 조문이 그래프에 다시 고정되는 구조였다(분석 G-1). 조회는 법령명 +
# eflaw(legal_api.fetch_law_root)로 한다 — `target=law`는 시행 예정 개정이 섞인다.

GRAPH_LAWS: list[str] = [
    "근로기준법",
    "근로기준법 시행령",
    "최저임금법",
    "고용보험법",
    "산업재해보상보험법",
    "근로자퇴직급여 보장법",
    "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률",
    "소득세법",
    "기간제 및 단시간근로자 보호 등에 관한 법률",
    "파견근로자 보호 등에 관한 법률",
    "임금채권보장법",
    "노동조합 및 노동관계조정법",
]

LAW_NAME_ALIASES: dict[str, str] = {
    "근기법": "근로기준법",
    "최임법": "최저임금법",
    "고보법": "고용보험법",
    "산재법": "산업재해보상보험법",
    "퇴직급여법": "근로자퇴직급여 보장법",
    "기간제법": "기간제 및 단시간근로자 보호 등에 관한 법률",
    "파견법": "파견근로자 보호 등에 관한 법률",
    "임채법": "임금채권보장법",
    "노조법": "노동조합 및 노동관계조정법",
}

# ── 개념 매핑 테이블 ──────────────────────────────────────────────────────────

CONCEPT_MAP: dict[str, dict] = {
    "통상임금":     {"aliases": ["통상시급", "통상급"],
                    "articles": ["근로기준법:2", "근로기준법:56"]},
    "평균임금":     {"aliases": ["평균급"],
                    "articles": ["근로기준법:2", "근로기준법:34"]},
    "연장근로수당": {"aliases": ["연장수당", "초과수당"],
                    "articles": ["근로기준법:56"]},
    "야간근로수당": {"aliases": ["야간수당"],
                    "articles": ["근로기준법:56"]},
    "휴일근로수당": {"aliases": ["휴일수당"],
                    "articles": ["근로기준법:56"]},
    "주휴수당":     {"aliases": [],
                    "articles": ["근로기준법:55"]},
    "최저임금":     {"aliases": ["최저시급"],
                    "articles": ["최저임금법:6"]},
    "퇴직금":       {"aliases": ["퇴직급여"],
                    "articles": ["근로자퇴직급여 보장법:8"]},
    "해고예고수당": {"aliases": [],
                    "articles": ["근로기준법:26"]},
    "부당해고":     {"aliases": ["부당 해고"],
                    "articles": ["근로기준법:23", "근로기준법:28"]},
    "연차유급휴가": {"aliases": ["연차", "연차수당"],
                    "articles": ["근로기준법:60"]},
    "실업급여":     {"aliases": ["구직급여"],
                    "articles": ["고용보험법:40"]},
    "육아휴직":     {"aliases": ["육아휴직급여"],
                    "articles": ["남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률:19"]},
    "출산전후휴가": {"aliases": ["출산휴가", "산전후휴가"],
                    "articles": ["근로기준법:74"]},
    "산재보상":     {"aliases": ["산재", "산업재해"],
                    "articles": ["산업재해보상보험법:36"]},
    "4대보험":      {"aliases": ["사대보험"],
                    "articles": ["고용보험법:8", "산업재해보상보험법:6"]},
    "근로계약":     {"aliases": [],
                    "articles": ["근로기준법:17"]},
    "직장내괴롭힘": {"aliases": ["직장 내 괴롭힘", "괴롭힘", "갑질"],
                    "articles": ["근로기준법:76"]},
    "임금체불":     {"aliases": ["체불", "밀린 임금"],
                    "articles": ["근로기준법:36"]},
    "포괄임금제":   {"aliases": ["포괄임금"],
                    "articles": []},
    "휴업수당":     {"aliases": [],
                    "articles": ["근로기준법:46"]},
    "근로시간":     {"aliases": ["소정근로시간"],
                    "articles": ["근로기준법:50"]},
}

# ── 주제 → 개념 매핑 ─────────────────────────────────────────────────────────

TOPIC_CONCEPT_MAP: dict[str, list[str]] = {
    "해고·징계":     ["부당해고", "해고예고수당"],
    "임금·통상임금": ["통상임금", "평균임금", "최저임금", "임금체불"],
    "근로시간·휴일": ["연장근로수당", "야간근로수당", "휴일근로수당", "주휴수당", "근로시간"],
    "퇴직·퇴직금":   ["퇴직금", "평균임금"],
    "연차휴가":       ["연차유급휴가"],
    "산재보상":       ["산재보상"],
    "비정규직":       ["근로계약"],
    "노동조합":       [],
    "직장내괴롭힘":   ["직장내괴롭힘"],
    "근로계약":       ["근로계약", "포괄임금제"],
    "고용보험":       ["실업급여", "육아휴직", "출산전후휴가"],
    "기타":           [],
}

# ── 계산기 → 개념 매핑 ───────────────────────────────────────────────────────

CALC_CONCEPT_MAP: dict[str, list[str]] = {
    "overtime":          ["연장근로수당", "야간근로수당", "휴일근로수당", "통상임금"],
    "minimum_wage":      ["최저임금"],
    "weekly_holiday":    ["주휴수당"],
    "annual_leave":      ["연차유급휴가"],
    "dismissal":         ["해고예고수당", "부당해고"],
    "severance":         ["퇴직금", "평균임금"],
    "unemployment":      ["실업급여"],
    "insurance":         ["4대보험"],
    "employer_insurance": ["4대보험"],
    "parental_leave":    ["육아휴직"],
    "maternity_leave":   ["출산전후휴가"],
    "wage_arrears":      ["임금체불"],
    "comprehensive":     ["포괄임금제", "통상임금"],
    "compensatory_leave": ["연장근로수당"],
    "flexible_work":     ["연장근로수당", "근로시간"],
    "average_wage":      ["평균임금"],
    "shutdown_allowance": ["휴업수당"],
    "industrial_accident": ["산재보상"],
}

# ── 그래프 판례 — 법제처 원문 기록 + 큐레이션 명세 ──────────────────────────
# ⚠️ 판례 노드의 사실 내용(요약·선고일·변경 관계)을 손으로 쓰지 말 것.
# 손으로 쓴 구 표(MAJOR_PRECEDENTS 8건)는 2건만 맞았다(2026-10-04 법제처 대조):
# 2019다293449(실제 동산인도)를 "주휴수당 산정 기준"으로, 2013다25194(근로계약 취소)를
# "평균임금 기준"으로, 2018다200709(유리한 근로계약 우선)를 "연차 사용촉진"으로 적었고,
# 3건은 법제처에 정확일치가 없었다. 그래프 컨텍스트는 인용 화이트리스트에 들어가므로
# 그 번호들은 **항상 검증을 통과했다** — 지식iN 2차 재평가 오인용 4문항의 출처다.
#
# 이제 사실은 `data/graph_precedents.json`(법제처 판시사항·판결요지·참조판례, 커밋)에서만
# 온다. 아래 명세는 **무엇을 어디에 연결할지**만 정한다. 키는 리터럴로 둘 것 —
# archive_precedents의 코드 인용 스캔이 이 파일의 사건번호를 읽는다(교차검증 H4).
#
#   python3 build_graph.py --refresh-precedents          # 법제처에서 기록 갱신(LAW_API_KEY)
#   python3 build_graph.py --refresh-precedents --verify # 커밋본 = 원격인지 확인(수동 점검)
#   python3 build_graph.py --skip-api                    # 그래프 재빌드(게이트 G1~G5)

# 실행 위치와 무관하게 — 다른 디렉터리에서 돌리면 G1이 "기록 없음"으로 원인을 잘못 가리켰다.
PRECEDENT_RECORDS_PATH = Path(__file__).resolve().parent / "data" / "graph_precedents.json"

GRAPH_PRECEDENT_SPECS: dict[str, dict] = {
    "2023다302838": {"concepts": ["통상임금"], "supersedes": ["2012다89399"]},
    "2012다89399":  {"concepts": ["통상임금"]},
    "2022다291153": {"concepts": ["주휴수당"]},
    "2018다200709": {"concepts": ["근로계약"]},
    "2013다25194":  {"concepts": ["근로계약"]},
}

# 기록에 남기는 필드 — 전문(full_text)은 게이트에 필요 없고 커서 저장하지 않는다.
_RECORD_FIELDS = ("case_no", "court", "date", "judgment_type", "case_name", "serial_id",
                  "source_url", "issue", "summary", "ref_cases")


class PrecedentGateError(RuntimeError):
    """그래프 판례 게이트 위반 — 빌드를 멈춘다(조용히 통과시키지 않는다)."""


def _norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def holding_items(issue: str) -> list[str]:
    """판시사항을 항목으로 나눈다. `[1] … [2] …` 또는 ` / ` 구분(실측 두 형식)."""
    text = _norm_ws(issue)
    items = [p.strip() for p in re.split(r"\[\d+\]", text) if p.strip()]
    if len(items) <= 1:
        items = [p.strip() for p in re.split(r"\s+/\s+", text) if p.strip()]
    return items


def _concept_keywords(concept: str) -> list[str]:
    return [concept] + list(CONCEPT_MAP.get(concept, {}).get("aliases", []))


def _supersede_evidence(ref_cases: str, case_no: str) -> bool:
    """참조판례에서 그 사건번호와 **같은 항목 안에** "(변경)" 표지가 있는가(G4).

    참조판례에는 여러 건이 나열되므로 표지가 문서 어딘가에 있는지만 보면 다른 판례의
    변경 표지를 이 판례의 것으로 오인한다 — 번호부터 다음 사건번호 전까지로 묶는다.
    """
    text = _norm_ws(ref_cases)
    idx = text.find(case_no)
    if idx < 0:
        return False
    rest = text[idx + len(case_no):]
    nxt = re.search(r"\d{2,4}[가-힣]{1,4}\d+", rest)
    segment = rest[:nxt.start()] if nxt else rest
    return "(변경)" in segment


def load_precedent_records(path: Path = PRECEDENT_RECORDS_PATH) -> dict[str, dict]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def precedent_nodes(specs: dict[str, dict] | None = None,
                    records: dict[str, dict] | None = None) -> dict[str, dict]:
    """명세 + 원문 기록 → 판례 노드 속성. 게이트 G1~G5 위반 시 PrecedentGateError.

    순수 함수다 — build_precedents와 오프라인 테스트(재빌드 동등성 E16)가 같이 쓴다.
    """
    from app.core.case_numbers import detail_matches

    specs = GRAPH_PRECEDENT_SPECS if specs is None else specs
    records = load_precedent_records() if records is None else records
    nodes: dict[str, dict] = {}
    for case_no, spec in specs.items():
        rec = records.get(case_no)
        # G1 — 기록 존재 + 사건번호 일치(병합 사건 허용)
        if not rec or not detail_matches(rec.get("case_no", ""), case_no):
            raise PrecedentGateError(f"G1 원문 기록 없음/불일치: {case_no}")
        # G5 — 출처
        url = rec.get("source_url", "")
        host = (urlparse(url).hostname or "") if url.startswith("https://") else ""
        if not (host == "law.go.kr" or host.endswith(".law.go.kr")):
            raise PrecedentGateError(f"G5 출처가 법제처 https가 아님: {case_no} {url!r}")
        if not str(rec.get("serial_id", "")).isdigit():
            raise PrecedentGateError(f"G5 판례일련번호 없음: {case_no}")
        concepts = spec.get("concepts", [])
        holding_text = _norm_ws(rec.get("issue", "")) + " " + _norm_ws(rec.get("summary", ""))
        # G3 — 연결 개념은 원문에 근거가 있어야 한다
        for concept in concepts:
            if not any(k in holding_text for k in _concept_keywords(concept)):
                raise PrecedentGateError(f"G3 개념 근거 없음: {case_no} → {concept}")
        # G2 — 요약 = 판시사항 항목 하나를 그대로(연결 개념 키워드를 포함하는 첫 항목)
        keywords = [k for c in concepts for k in _concept_keywords(c)]
        items = holding_items(rec.get("issue", ""))
        summary = next((it for it in items if any(k in it for k in keywords)), None)
        if summary is None:
            raise PrecedentGateError(f"G2 개념 키워드를 담은 판시사항 항목 없음: {case_no}")
        # G4 — 변경 관계는 변경한 판례의 참조판례 "(변경)" 표지로만
        for older in spec.get("supersedes", []):
            if not _supersede_evidence(rec.get("ref_cases", ""), older):
                raise PrecedentGateError(f"G4 변경 표지 없음: {case_no} → {older}")
        nodes[case_no] = {
            "case_number": case_no,
            "court": rec.get("court", ""),
            "date": rec.get("date", ""),
            "judgment_type": rec.get("judgment_type", ""),
            "summary": summary,
            "concepts": list(concepts),
            "supersedes": list(spec.get("supersedes", [])),
            "superseded_by": [],
        }
    for case_no, node in nodes.items():
        for older in node["supersedes"]:
            if older in nodes:
                nodes[older]["superseded_by"].append(case_no)
    return nodes


def refresh_precedent_records(verify: bool = False) -> int:
    """법제처에서 명세의 판례 원문 기록을 받는다. verify=True면 쓰지 않고 커밋본과 비교한다."""
    from dotenv import load_dotenv
    load_dotenv(override=True)
    api_key = os.getenv("LAW_API_KEY")
    if not api_key:
        print("LAW_API_KEY 미설정 — 법제처 조회가 필요합니다.")
        return 1
    # 스크립트 모듈은 함수 안에서 import — import 시 dotenv를 다시 읽는 부작용을 이 경로로 한정
    import fetch_court_precedents as fc
    from app.core.case_numbers import detail_matches

    from app.core.legal_api import LawApiAuthError

    fetched: dict[str, dict] = {}
    try:
        for case_no in GRAPH_PRECEDENT_SPECS:
            hit = fc.search_case(case_no, "prec", api_key)   # 사건번호 정확일치 + 페이지 순회
            if not hit:
                print(f"  ✗ {case_no}: 법제처 정확일치 없음")
                return 1
            root = fc.fetch_detail(hit["serial_id"], "prec", api_key)
            rec = fc.normalize_record(root, "prec", hit["serial_id"]) if root is not None else None
            if not rec or not detail_matches(rec["case_no"], case_no):   # 수집 스크립트와 같은 재확인
                print(f"  ✗ {case_no}: 상세 응답 사건번호 불일치")
                return 1
            fetched[case_no] = {k: rec.get(k, "") for k in _RECORD_FIELDS}
            print(f"  ✓ {case_no} {rec['date']} {rec['judgment_type']} {rec['case_name'][:30]}")
            time.sleep(0.2)
    except LawApiAuthError as e:   # '정확일치 없음'으로 오진하지 않는다(production-law-api-recovery D6)
        print(f"  ✗ 법제처 인증 오류 — 등록 IP가 아닌 곳에서 실행했거나 키 문제다: {e}")
        return 2

    if verify:
        current = load_precedent_records()
        diffs = [k for k in sorted(set(current) | set(fetched))
                 if {f: (current.get(k) or {}).get(f) for f in _RECORD_FIELDS}
                 != {f: (fetched.get(k) or {}).get(f) for f in _RECORD_FIELDS}]
        print("커밋본 = 원격" if not diffs else f"⚠️ 커밋본과 다름: {diffs}")
        return 1 if diffs else 0

    today = time.strftime("%Y-%m-%d")
    for rec in fetched.values():
        rec["fetched_at"] = today
    PRECEDENT_RECORDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PRECEDENT_RECORDS_PATH, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(fetched.items())), f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"→ {PRECEDENT_RECORDS_PATH} ({len(fetched)}건)")
    return 0

# ── 조문 참조 정규식 ─────────────────────────────────────────────────────────

_STATUTE_NAMES = (
    r"근로기준법|고용보험법|산업재해보상보험법|최저임금법|"
    r"근로자퇴직급여\s*보장법|남녀고용평등.*?법률|"
    r"기간제.*?법률|파견.*?법률|임금채권보장법|노동조합.*?법률|"
    r"소득세법|조세특례제한법"
)

_CITE_CROSS_LAW = re.compile(rf"({_STATUTE_NAMES})\s*제(\d+)조")
_CITE_SAME_LAW = re.compile(r"제(\d+)조(?:의(\d+))?")


# ══════════════════════════════════════════════════════════════════════════════
# Phase 1: 법률 노드
# ══════════════════════════════════════════════════════════════════════════════

def build_statutes(G: nx.DiGraph) -> None:
    alias_reverse = {v: k for k, v in LAW_NAME_ALIASES.items()}
    for name in GRAPH_LAWS:
        node_id = f"statute:{name}"
        G.add_node(node_id, type="statute", name=name,
                   short=alias_reverse.get(name, ""))
    logger.info("Statute 노드: %d개", sum(1 for _, d in G.nodes(data=True) if d.get("type") == "statute"))


# ══════════════════════════════════════════════════════════════════════════════
# Phase 2: 조문 노드 (Legal API 또는 캐시)
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_articles_from_api(law_name: str) -> list[dict]:
    """법제처 API에서 조문 목록 조회 — legal_api.fetch_law_root(eflaw 현행 시행판).

    조회·게이트(미매칭·자격 오류·반환 법령명 대조·폐지 거부)는 legal_api 단일 출처다.
    여기에 복제본을 두면 원본만 고쳐지는 사각이 생긴다 — MST 사전매핑과 `replace(" ", "")`
    법령명 비교가 실제로 이 파일에 복제돼 남아 있었다(effective-law D11).
    미매칭·오해석·오류는 빈 리스트로 강등한다. **인증 오류(LawApiAuthError)는 강등하지 않고
    올린다** — 빈 리스트가 되면 그 법령의 조문 노드가 조용히 빠진 그래프가 커밋된다
    (production-law-api-recovery D6). build_articles가 빌드를 멈춘다.
    """
    from app.core.legal_api import LawApiAuthError

    api_key = os.getenv("LAW_API_KEY")
    if not api_key:
        return []
    try:
        from app.core.legal_api import fetch_law_root
        root = fetch_law_root(law_name, api_key, timeout=10)
        if root is None:
            logger.warning("법령 미매칭·오해석·폐지: %s", law_name)
            return []
        articles = []
        for art_el in root.iter("조문단위"):
            num_text = art_el.findtext("조문번호", "").strip()
            if not num_text:
                continue
            try:
                num = int(re.sub(r"[^\d]", "", num_text))
            except ValueError:
                continue
            title = art_el.findtext("조문제목", "").strip()
            content = art_el.findtext("조문내용", "").strip()
            articles.append({
                "number": num,
                "title": title,
                "text": content[:500],
            })
        return articles
    except LawApiAuthError:
        raise
    except Exception as e:
        logger.warning("API 조회 실패 (%s): %s", law_name, e)
        return []


def build_articles(G: nx.DiGraph, skip_api: bool = False) -> None:
    """각 법률의 핵심 조문 노드를 생성."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    for node_id, data in list(G.nodes(data=True)):
        if data.get("type") != "statute":
            continue
        name = data["name"]
        # 캐시 파일명은 법령명 기반 — 구 MST 기반 파일({mst}.json)은 낡은
        # 판본의 스냅샷이라 재사용하지 않는다(자연 미스 → 현행판 재수집).
        # `.eflaw` 접미사: target=law 시절 파일({name}.json)은 시행 예정 본문이 섞여
        # 있을 수 있어 읽지 않는다(effective-law — 캐시 세대와 같은 원리).
        cache_file = CACHE_DIR / f"{name.replace(' ', '_')}.eflaw.json"

        # 캐시 만료 7일 — 만료 검사 없이 재사용하면 그래프 재빌드가 캐시
        # 시점의 판본을 계속 굳힌다(CodeRabbit #55: "현행성 보장은 캐시
        # 수명까지"). 만료분은 다시 받되, **받는 데 성공한 뒤에** 교체한다 — 먼저 지우면
        # 인증 오류·일시 장애에서 조문 노드가 조용히 빠진 그래프가 나왔다(production-law-api-recovery D6).
        expired = (cache_file.exists() and not skip_api
                   and time.time() - cache_file.stat().st_mtime > 7 * 86400)

        articles = []
        if cache_file.exists() and not expired:
            with open(cache_file, "r", encoding="utf-8") as f:
                articles = json.load(f)
        elif not skip_api:
            articles = _fetch_articles_from_api(name)   # 인증 오류는 여기서 올라와 빌드가 멈춘다
            if articles:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(articles, f, ensure_ascii=False, indent=1)
            elif expired:
                logger.warning("조문 재수집 실패 (%s) — 만료된 캐시를 그대로 쓴다", name)
                with open(cache_file, "r", encoding="utf-8") as f:
                    articles = json.load(f)
            time.sleep(0.5)  # 속도 제한

        for art in articles:
            art_id = f"article:{name}:{art['number']}"
            G.add_node(art_id, type="article", statute=name,
                       number=art["number"], title=art.get("title", ""),
                       text_snippet=art.get("text", "")[:200])
            G.add_edge(node_id, art_id, rel="CONTAINS")

    count = sum(1 for _, d in G.nodes(data=True) if d.get("type") == "article")
    logger.info("Article 노드: %d개", count)


# ══════════════════════════════════════════════════════════════════════════════
# Phase 3: 조문 간 참조 (CITES)
# ══════════════════════════════════════════════════════════════════════════════

def extract_cites(G: nx.DiGraph) -> int:
    added = 0
    for node_id, data in list(G.nodes(data=True)):
        if data.get("type") != "article":
            continue
        text = data.get("text_snippet", "")
        statute = data["statute"]

        # 타법 참조
        for m in _CITE_CROSS_LAW.finditer(text):
            target_statute = m.group(1).strip()
            target_num = int(m.group(2))
            target_id = f"article:{target_statute}:{target_num}"
            if G.has_node(target_id) and target_id != node_id:
                if not G.has_edge(node_id, target_id):
                    G.add_edge(node_id, target_id, rel="CITES")
                    added += 1

        # 같은 법 참조
        for m in _CITE_SAME_LAW.finditer(text):
            target_num = int(m.group(1))
            target_id = f"article:{statute}:{target_num}"
            if G.has_node(target_id) and target_id != node_id:
                if not G.has_edge(node_id, target_id):
                    G.add_edge(node_id, target_id, rel="CITES")
                    added += 1

    logger.info("CITES 엣지: %d개", added)
    return added


# ══════════════════════════════════════════════════════════════════════════════
# Phase 4: 개념 노드
# ══════════════════════════════════════════════════════════════════════════════

def build_concepts(G: nx.DiGraph) -> None:
    for concept_name, info in CONCEPT_MAP.items():
        cid = f"concept:{concept_name}"
        G.add_node(cid, type="concept", name=concept_name,
                   aliases=info.get("aliases", []),
                   description="")
        # APPLIES_TO 엣지: Article → Concept
        for art_ref in info.get("articles", []):
            art_id = f"article:{art_ref}"
            if G.has_node(art_id):
                G.add_edge(art_id, cid, rel="APPLIES_TO")

    # 관련 개념 간 RELATED_TO
    relations = [
        ("통상임금", "평균임금"),
        ("통상임금", "최저임금"),
        ("퇴직금", "평균임금"),
        ("연장근로수당", "통상임금"),
        ("야간근로수당", "통상임금"),
        ("휴일근로수당", "통상임금"),
        ("주휴수당", "통상임금"),
        ("해고예고수당", "통상임금"),
        ("연차유급휴가", "통상임금"),
        ("실업급여", "평균임금"),
        ("임금체불", "퇴직금"),
    ]
    for a, b in relations:
        aid = f"concept:{a}"
        bid = f"concept:{b}"
        if G.has_node(aid) and G.has_node(bid):
            G.add_edge(aid, bid, rel="RELATED_TO")
            G.add_edge(bid, aid, rel="RELATED_TO")

    count = sum(1 for _, d in G.nodes(data=True) if d.get("type") == "concept")
    logger.info("Concept 노드: %d개", count)


# ══════════════════════════════════════════════════════════════════════════════
# Phase 5: 주제 노드
# ══════════════════════════════════════════════════════════════════════════════

def build_topics(G: nx.DiGraph) -> None:
    for topic_name, concepts in TOPIC_CONCEPT_MAP.items():
        tid = f"topic:{topic_name}"
        G.add_node(tid, type="topic", name=topic_name)
        for concept in concepts:
            cid = f"concept:{concept}"
            if G.has_node(cid):
                G.add_edge(tid, cid, rel="TOPIC_HAS")
    logger.info("Topic 노드: %d개", len(TOPIC_CONCEPT_MAP))


# ══════════════════════════════════════════════════════════════════════════════
# Phase 6: 계산기 노드
# ══════════════════════════════════════════════════════════════════════════════

def build_calculators(G: nx.DiGraph) -> None:
    for calc_name, concepts in CALC_CONCEPT_MAP.items():
        cid = f"calc:{calc_name}"
        G.add_node(cid, type="calculator", name=calc_name)
        for concept in concepts:
            concept_id = f"concept:{concept}"
            if G.has_node(concept_id):
                G.add_edge(cid, concept_id, rel="CALC_FOR")
    logger.info("Calculator 노드: %d개", len(CALC_CONCEPT_MAP))


# ══════════════════════════════════════════════════════════════════════════════
# Phase 7~8: 판례 노드 + 법조문 연결
# ══════════════════════════════════════════════════════════════════════════════

def build_precedents(G: nx.DiGraph) -> None:
    """명세 + 원문 기록으로 판례 노드를 만든다. 게이트 위반이면 예외로 빌드를 멈춘다."""
    for case_num, node in precedent_nodes().items():
        pid = f"precedent:{case_num}"
        G.add_node(pid, type="precedent", **{k: v for k, v in node.items() if k != "concepts"})
        # INTERPRETS: Precedent → Concept (원문 근거가 확인된 개념만 — G3)
        for concept in node["concepts"]:
            cid = f"concept:{concept}"
            if G.has_node(cid):
                G.add_edge(pid, cid, rel="INTERPRETS")

    count = sum(1 for _, d in G.nodes(data=True) if d.get("type") == "precedent")
    logger.info("Precedent 노드: %d개", count)


# ══════════════════════════════════════════════════════════════════════════════
# 직렬화 / 통계
# ══════════════════════════════════════════════════════════════════════════════

def save_graph(G: nx.DiGraph, path: Path = GRAPH_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = nx.node_link_data(G)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    size_kb = path.stat().st_size / 1024
    logger.info("그래프 저장: %s (%.1f KB)", path, size_kb)


def print_stats(G: nx.DiGraph) -> None:
    type_counts: dict[str, int] = {}
    for _, d in G.nodes(data=True):
        t = d.get("type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1

    rel_counts: dict[str, int] = {}
    for _, _, d in G.edges(data=True):
        r = d.get("rel", "unknown")
        rel_counts[r] = rel_counts.get(r, 0) + 1

    print("\n" + "=" * 50)
    print(f"총 노드: {G.number_of_nodes()}")
    for t, c in sorted(type_counts.items()):
        print(f"  {t}: {c}")
    print(f"\n총 엣지: {G.number_of_edges()}")
    for r, c in sorted(rel_counts.items()):
        print(f"  {r}: {c}")
    print("=" * 50)


# ══════════════════════════════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="노동법 지식 그래프 구축")
    parser.add_argument("--skip-api", action="store_true", help="Legal API 호출 생략")
    parser.add_argument("--stats", action="store_true", help="기존 그래프 통계만 출력")
    parser.add_argument("--refresh-precedents", action="store_true",
                        help="법제처에서 그래프 판례 원문 기록(data/graph_precedents.json) 갱신")
    parser.add_argument("--verify", action="store_true",
                        help="--refresh-precedents와 함께: 쓰지 않고 커밋본과 원격을 비교")
    args = parser.parse_args()

    if args.refresh_precedents:
        sys.exit(refresh_precedent_records(verify=args.verify))

    if args.stats:
        if not GRAPH_PATH.exists():
            print("그래프 파일이 없습니다:", GRAPH_PATH)
            sys.exit(1)
        with open(GRAPH_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        G = nx.node_link_graph(data, directed=True)
        print_stats(G)
        return

    G = nx.DiGraph()

    logger.info("Phase 1: 법률 노드 구축...")
    build_statutes(G)

    logger.info("Phase 2: 조문 노드 구축...")
    from app.core.legal_api import LawApiAuthError
    try:
        build_articles(G, skip_api=args.skip_api)
    except LawApiAuthError as e:   # 조문 노드가 빠진 그래프를 저장하지 않는다(production-law-api-recovery D6)
        print(f"❌ 법제처 인증 오류 — 그래프를 저장하지 않고 멈춘다(등록 IP·키 확인, 또는 --skip-api): {e}")
        sys.exit(2)

    logger.info("Phase 3: 조문 간 참조 추출...")
    extract_cites(G)

    logger.info("Phase 4: 개념 노드 구축...")
    build_concepts(G)

    logger.info("Phase 5: 주제 노드 구축...")
    build_topics(G)

    logger.info("Phase 6: 계산기 노드 구축...")
    build_calculators(G)

    logger.info("Phase 7~8: 판례 노드 및 연결...")
    build_precedents(G)

    save_graph(G)
    print_stats(G)


if __name__ == "__main__":
    main()
