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
from xml.etree import ElementTree as ET

import networkx as nx
import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

GRAPH_PATH = Path("data/graph_data.json")
CACHE_DIR = Path("data/article_cache")

# ── 법률 MST 매핑 (legal_api.py와 동일) ──────────────────────────────────────

PRELOADED_MST: dict[str, int] = {
    "근로기준법": 265959,
    "근로기준법 시행령": 270551,
    "최저임금법": 218303,
    "고용보험법": 276843,
    "산업재해보상보험법": 279733,
    "근로자퇴직급여 보장법": 279829,
    "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률": 276851,
    "소득세법": 276127,
    "기간제 및 단시간근로자 보호 등에 관한 법률": 232201,
    "파견근로자 보호 등에 관한 법률": 223983,
    "임금채권보장법": 259881,
    "노동조합 및 노동관계조정법": 273667,
}

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

# ── 주요 판례 수동 매핑 ──────────────────────────────────────────────────────

MAJOR_PRECEDENTS: dict[str, dict] = {
    "2023다302838": {
        "court": "대법원", "year": 2023,
        "articles": ["근로기준법:2", "근로기준법:56"],
        "concepts": ["통상임금"],
        "summary": "고정성 요건 폐지, 정기적·일률적으로 지급되는 수당은 통상임금에 포함",
    },
    "2012다89399": {
        "court": "대법원", "year": 2013,
        "articles": ["근로기준법:2"],
        "concepts": ["통상임금"],
        "summary": "통상임금 판단 기준에 관한 전원합의체 판결",
    },
    "2010다111757": {
        "court": "대법원", "year": 2013,
        "articles": ["근로기준법:23"],
        "concepts": ["부당해고"],
        "summary": "부당해고 판단 기준과 사용자의 입증 책임",
    },
    "2013다25194": {
        "court": "대법원", "year": 2014,
        "articles": ["근로기준법:34"],
        "concepts": ["퇴직금", "평균임금"],
        "summary": "퇴직금 산정 시 평균임금 산정 기준",
    },
    "2018다200709": {
        "court": "대법원", "year": 2019,
        "articles": ["근로기준법:60"],
        "concepts": ["연차유급휴가"],
        "summary": "연차유급휴가 사용촉진 제도의 적법 요건",
    },
    "2020나2016258": {
        "court": "서울고등법원", "year": 2021,
        "articles": ["근로기준법:76"],
        "concepts": ["직장내괴롭힘"],
        "summary": "직장 내 괴롭힘 판단 요소와 사용자 조치 의무",
    },
    "2019다293449": {
        "court": "대법원", "year": 2020,
        "articles": ["근로기준법:55"],
        "concepts": ["주휴수당"],
        "summary": "주휴수당 산정 기준과 소정근로시간",
    },
    "2017다261387": {
        "court": "대법원", "year": 2019,
        "articles": ["최저임금법:6"],
        "concepts": ["최저임금"],
        "summary": "최저임금 산입 범위와 상여금 포함 여부",
    },
}

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
    for name, mst in PRELOADED_MST.items():
        node_id = f"statute:{name}"
        G.add_node(node_id, type="statute", name=name, mst=mst,
                   short=alias_reverse.get(name, ""))
    logger.info("Statute 노드: %d개", sum(1 for _, d in G.nodes(data=True) if d.get("type") == "statute"))


# ══════════════════════════════════════════════════════════════════════════════
# Phase 2: 조문 노드 (Legal API 또는 캐시)
# ══════════════════════════════════════════════════════════════════════════════

LAW_SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do"


def _fetch_articles_from_api(mst: int) -> list[dict]:
    """법제처 API에서 조문 목록 조회."""
    api_key = os.getenv("LAW_API_KEY")
    if not api_key:
        return []
    try:
        resp = requests.get(LAW_SERVICE_URL, params={
            "OC": api_key, "target": "law", "MST": mst, "type": "XML",
        }, timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
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
    except Exception as e:
        logger.warning("API 조회 실패 MST=%d: %s", mst, e)
        return []


def build_articles(G: nx.DiGraph, skip_api: bool = False) -> None:
    """각 법률의 핵심 조문 노드를 생성."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    for node_id, data in list(G.nodes(data=True)):
        if data.get("type") != "statute":
            continue
        name = data["name"]
        mst = data["mst"]
        cache_file = CACHE_DIR / f"{mst}.json"

        articles = []
        if cache_file.exists():
            with open(cache_file, "r", encoding="utf-8") as f:
                articles = json.load(f)
        elif not skip_api:
            articles = _fetch_articles_from_api(mst)
            if articles:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(articles, f, ensure_ascii=False, indent=1)
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
    for case_num, info in MAJOR_PRECEDENTS.items():
        pid = f"precedent:{case_num}"
        G.add_node(pid, type="precedent", case_number=case_num,
                   court=info["court"], year=info["year"],
                   summary=info.get("summary", ""))
        # INTERPRETS: Precedent → Article
        for art_ref in info.get("articles", []):
            art_id = f"article:{art_ref}"
            if G.has_node(art_id):
                G.add_edge(pid, art_id, rel="INTERPRETS")
        # INTERPRETS: Precedent → Concept
        for concept in info.get("concepts", []):
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
    args = parser.parse_args()

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
    build_articles(G, skip_api=args.skip_api)

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
