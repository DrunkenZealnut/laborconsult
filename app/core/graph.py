"""GraphRAG 검색 엔진 — NetworkX 기반 법령 지식 그래프 순회

그래프 로드 → 시드 노드 매칭 → 멀티홉 BFS → 컨텍스트 텍스트 생성.
기존 Pinecone 벡터 검색에 그래프 관계 정보를 보강하는 하이브리드 검색 모듈.

- Vercel serverless: global _graph 변수로 warm start 시 재파싱 방지
- 그래프 로드 실패 시 graceful fallback (빈 결과 반환)
"""

from __future__ import annotations

import json
import logging
import re
from collections import deque
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import networkx as nx
except ImportError:
    nx = None  # type: ignore
    logger.warning("networkx not installed — GraphRAG disabled")


# ── 글로벌 그래프 캐시 (Vercel serverless) ─────────────────────────────────
_graph = None  # nx.DiGraph | None


def get_graph():
    """그래프 lazy loading + 글로벌 캐시."""
    global _graph
    if _graph is not None:
        return _graph
    if nx is None:
        return None

    graph_path = Path(__file__).parent.parent.parent / "data" / "graph_data.json"
    if not graph_path.exists():
        logger.info("graph_data.json not found — GraphRAG disabled")
        return None
    try:
        with open(graph_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _graph = nx.node_link_graph(data, directed=True)
        logger.info("GraphRAG loaded: %d nodes, %d edges",
                     _graph.number_of_nodes(), _graph.number_of_edges())
        return _graph
    except Exception as e:
        logger.warning("GraphRAG load failed: %s", e)
        return None


# ── 법조문 참조 정규식 ─────────────────────────────────────────────────────
_STATUTE_NAMES = (
    r"근로기준법|고용보험법|산업재해보상보험법|최저임금법|"
    r"근로자퇴직급여\s*보장법|남녀고용평등.*?법률|"
    r"기간제.*?법률|파견.*?법률|임금채권보장법|노동조합.*?법률|"
    r"소득세법|조세특례제한법"
)
_LAW_REF_RE = re.compile(rf"({_STATUTE_NAMES})\s*제?(\d+)조")


# ── 시드 노드 매칭 ─────────────────────────────────────────────────────────

def _match_law_ref(G, ref: str) -> str | None:
    """법조문 참조 문자열 → Article 또는 Statute 노드 ID."""
    m = _LAW_REF_RE.search(ref)
    if m:
        statute_name = m.group(1).strip()
        art_num = m.group(2)
        art_id = f"article:{statute_name}:{art_num}"
        if G.has_node(art_id):
            return art_id
        statute_id = f"statute:{statute_name}"
        if G.has_node(statute_id):
            return statute_id
    return None


def _match_concept(G, keyword: str) -> str | None:
    """키워드를 Concept 노드 이름/aliases로 매칭."""
    cid = f"concept:{keyword}"
    if G.has_node(cid):
        return cid
    for node_id, data in G.nodes(data=True):
        if data.get("type") != "concept":
            continue
        if keyword in data.get("aliases", []):
            return node_id
        if keyword == data.get("name"):
            return node_id
    return None


def find_seed_nodes(
    relevant_laws: list[str] | None = None,
    precedent_keywords: list[str] | None = None,
    consultation_topic: str | None = None,
    calculation_types: list[str] | None = None,
) -> list[str]:
    """AnalysisResult 필드 → 그래프 노드 ID 리스트 (중복 제거, 최대 10개)."""
    G = get_graph()
    if G is None:
        return []

    seeds: list[str] = []

    if relevant_laws:
        for ref in relevant_laws:
            nid = _match_law_ref(G, ref)
            if nid:
                seeds.append(nid)

    if precedent_keywords:
        for kw in precedent_keywords:
            nid = _match_concept(G, kw)
            if nid:
                seeds.append(nid)

    if consultation_topic:
        tid = f"topic:{consultation_topic}"
        if G.has_node(tid):
            seeds.append(tid)

    if calculation_types:
        for ct in calculation_types:
            cid = f"calc:{ct}"
            if G.has_node(cid):
                seeds.append(cid)

    seen: set[str] = set()
    unique: list[str] = []
    for s in seeds:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique[:10]


# ── 멀티홉 BFS 순회 ───────────────────────────────────────────────────────

def traverse_graph(
    seed_nodes: list[str],
    max_hops: int = 2,
    max_results: int = 30,
) -> list[dict]:
    """시드 노드에서 BFS 멀티홉 순회 (양방향).

    Returns:
        [{"node_id", "data", "distance", "path"}, ...] distance 오름차순
    """
    G = get_graph()
    if G is None or not seed_nodes:
        return []

    visited: dict[str, dict] = {}

    for seed in seed_nodes:
        if not G.has_node(seed):
            continue
        queue: deque[tuple[str, int, list[str]]] = deque()
        queue.append((seed, 0, [seed]))

        while queue:
            current, dist, path = queue.popleft()
            if current in visited and visited[current]["distance"] <= dist:
                continue
            visited[current] = {"distance": dist, "path": path}

            if dist < max_hops:
                neighbors = set(G.successors(current)) | set(G.predecessors(current))
                for neighbor in neighbors:
                    if neighbor not in visited or visited[neighbor]["distance"] > dist + 1:
                        queue.append((neighbor, dist + 1, path + [neighbor]))

    seed_set = set(seed_nodes)
    results = []
    for node_id, info in sorted(visited.items(), key=lambda x: x[1]["distance"]):
        if node_id in seed_set:
            continue
        data = dict(G.nodes[node_id])
        results.append({
            "node_id": node_id,
            "data": data,
            "distance": info["distance"],
            "path": info["path"],
        })
        if len(results) >= max_results:
            break

    return results


# ── 컨텍스트 텍스트 생성 ───────────────────────────────────────────────────

def _node_display_name(G, node_id: str) -> str:
    d = G.nodes.get(node_id, {})
    ntype = d.get("type", "")
    if ntype == "article":
        return f"{d.get('statute', '')} 제{d.get('number', '')}조"
    if ntype == "statute":
        return d.get("name", node_id)
    if ntype == "precedent":
        return f"{d.get('court', '')} {d.get('case_number', '')}"
    if ntype == "concept":
        return d.get("name", node_id)
    if ntype == "topic":
        return d.get("name", node_id)
    if ntype == "calculator":
        return d.get("name", node_id)
    return node_id


def _describe_path(G, path: list[str]) -> str:
    if len(path) < 3:
        return ""
    parts = []
    for i in range(len(path) - 1):
        edge = G.get_edge_data(path[i], path[i + 1]) or G.get_edge_data(path[i + 1], path[i]) or {}
        rel = edge.get("rel", "연결")
        parts.append(f"{_node_display_name(G, path[i])} →({rel})→ {_node_display_name(G, path[i + 1])}")
    return " / ".join(parts)


def build_graph_context(
    seed_nodes: list[str],
    traversal_results: list[dict],
    max_chars: int = 2000,
) -> str:
    """순회 결과 → LLM 컨텍스트 텍스트."""
    G = get_graph()
    if G is None:
        return ""

    sections: list[str] = []

    # 1. 관련 법조문
    articles = [r for r in traversal_results if r["data"].get("type") == "article"]
    if articles:
        lines = ["[관련 법조문]"]
        for a in articles[:8]:
            d = a["data"]
            title = d.get("title", "")
            line = f"- {d.get('statute', '')} 제{d.get('number', '')}조"
            if title:
                line += f" ({title})"
            lines.append(line)
            if a["distance"] > 1:
                desc = _describe_path(G, a["path"])
                if desc:
                    lines.append(f"  연결: {desc}")
        sections.append("\n".join(lines))

    # 2. 관련 판례
    precedents = [r for r in traversal_results if r["data"].get("type") == "precedent"]
    if precedents:
        lines = ["[관련 판례 (그래프 탐색)]"]
        for p in precedents[:5]:
            d = p["data"]
            summary = d.get("summary", "")[:100]
            lines.append(f"- {d.get('court', '')} {d.get('case_number', '')}: {summary}")
        sections.append("\n".join(lines))

    # 3. 법률 체계 관계
    statutes: set[str] = set()
    for r in traversal_results:
        if r["data"].get("type") == "article":
            statutes.add(r["data"].get("statute", ""))
    for s in seed_nodes:
        sd = G.nodes.get(s, {})
        if sd.get("type") == "article":
            statutes.add(sd.get("statute", ""))
        elif sd.get("type") == "statute":
            statutes.add(sd.get("name", ""))
    statutes.discard("")
    if len(statutes) > 1:
        sections.append(f"[관련 법률 체계]\n이 질문은 다음 법률들이 관련됩니다: {', '.join(sorted(statutes))}")

    result = "\n\n".join(sections)
    return result[:max_chars] if result else ""


# ── 통합 API ──────────────────────────────────────────────────────────────

def graph_search(
    relevant_laws: list[str] | None = None,
    precedent_keywords: list[str] | None = None,
    consultation_topic: str | None = None,
    calculation_types: list[str] | None = None,
    max_hops: int = 2,
) -> tuple[str, list[dict]]:
    """GraphRAG 메인 검색 API.

    Returns:
        (context_text, traversal_results)
    """
    seeds = find_seed_nodes(relevant_laws, precedent_keywords,
                            consultation_topic, calculation_types)
    if not seeds:
        return "", []

    results = traverse_graph(seeds, max_hops=max_hops)
    context = build_graph_context(seeds, results)

    logger.info("GraphRAG: %d seeds → %d results, context=%d chars",
                len(seeds), len(results), len(context))
    return context, results
