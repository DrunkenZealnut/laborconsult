# Design: GraphRAG 구축 — 노동법 지식 그래프 기반 검색 강화

> Plan Reference: `docs/01-plan/features/graphrag.plan.md`

---

## 1. 파일 구조 및 역할

| 파일 | 상태 | 역할 |
|------|------|------|
| `build_graph.py` | **NEW** | 오프라인 그래프 구축 스크립트 (Legal API → NetworkX → JSON) |
| `data/graph_data.json` | **NEW** | 직렬화된 그래프 (node-link format) |
| `app/core/graph.py` | **NEW** | 런타임 GraphRAG 엔진 (로드, 시드 매칭, 순회, 컨텍스트 생성) |
| `app/core/pipeline.py` | MODIFY | `process_question()` 내 그래프 검색 호출 삽입 |
| `app/core/rag.py` | MODIFY | `rerank_results()` 후 그래프 스코어 병합 |
| `requirements.txt` | MODIFY | `networkx>=3.0` 추가 |

---

## 2. NetworkX 그래프 데이터 모델

### 2.1 노드 속성 스키마

```python
# Statute 노드
G.add_node("statute:근로기준법", **{
    "type": "statute",
    "name": "근로기준법",
    "mst": 265959,           # 법제처 MST 일련번호
    "short": "근기법",        # 약칭
})

# Article 노드
G.add_node("article:근로기준법:56", **{
    "type": "article",
    "statute": "근로기준법",
    "number": 56,
    "title": "연장·야간 및 휴일 근로",  # 조문 제목 (API 조회)
    "text_snippet": "...",              # 조문 텍스트 앞 200자 (검색용)
})

# Precedent 노드
G.add_node("precedent:2023다302838", **{
    "type": "precedent",
    "case_number": "2023다302838",
    "court": "대법원",
    "year": 2023,
    "summary": "...",          # 판결 요지 200자
})

# Concept 노드
G.add_node("concept:통상임금", **{
    "type": "concept",
    "name": "통상임금",
    "aliases": ["통상시급", "통상급"],  # 검색 매칭용
    "description": "...",               # 한 줄 설명
})

# Topic 노드
G.add_node("topic:임금·통상임금", **{
    "type": "topic",
    "name": "임금·통상임금",
})

# Calculator 노드
G.add_node("calc:overtime", **{
    "type": "calculator",
    "name": "overtime",
    "label": "연장/야간/휴일 수당",
})
```

### 2.2 노드 ID 규칙

| 타입 | ID 형식 | 예시 |
|------|---------|------|
| Statute | `statute:{법률명}` | `statute:근로기준법` |
| Article | `article:{법률명}:{조번호}` | `article:근로기준법:56` |
| Precedent | `precedent:{사건번호}` | `precedent:2023다302838` |
| Concept | `concept:{개념명}` | `concept:통상임금` |
| Topic | `topic:{주제명}` | `topic:임금·통상임금` |
| Calculator | `calc:{type}` | `calc:overtime` |

### 2.3 엣지 속성 스키마

```python
# 모든 엣지는 "rel" 속성으로 관계 타입을 표시
G.add_edge("statute:근로기준법", "article:근로기준법:56", rel="CONTAINS")
G.add_edge("article:근로기준법:56", "article:근로기준법:50", rel="CITES")
G.add_edge("precedent:2023다302838", "article:근로기준법:56", rel="INTERPRETS")
G.add_edge("article:근로기준법:56", "concept:연장근로수당", rel="APPLIES_TO")
G.add_edge("concept:통상임금", "concept:평균임금", rel="RELATED_TO")
G.add_edge("topic:임금·통상임금", "concept:통상임금", rel="TOPIC_HAS")
G.add_edge("calc:overtime", "concept:연장근로수당", rel="CALC_FOR")
```

---

## 3. `build_graph.py` 상세 설계

### 3.1 구조

```python
"""노동법 지식 그래프 오프라인 구축 스크립트.

사용법:
  python build_graph.py                 # 전체 구축
  python build_graph.py --stats         # 통계만 출력
  python build_graph.py --skip-api      # Legal API 호출 생략 (캐시만 사용)
"""

import json
import networkx as nx

def build_statutes(G):         # Phase 1: 법률 노드 (18개)
def build_articles(G):         # Phase 2: 조문 노드 (Legal API)
def extract_cites(G):          # Phase 3: 조문 간 참조 (정규식)
def build_concepts(G):         # Phase 4: 개념 노드 (매핑 테이블)
def build_topics(G):           # Phase 5: 주제 노드 (consultation_topic)
def build_calculators(G):      # Phase 6: 계산기 노드 (CALC_TYPES)
def build_precedents(G):       # Phase 7: 판례 노드 (Pinecone 메타)
def link_precedents(G):        # Phase 8: 판례-법조문 연결
def save_graph(G, path):       # JSON 직렬화
def print_stats(G):            # 통계 출력
```

### 3.2 Phase 1: 법률 노드 구축

`_PRELOADED_MST` (legal_api.py line 82~100)의 18개 법률을 직접 가져옴:

```python
from app.core.legal_api import _PRELOADED_MST, _LAW_NAME_ALIASES

def build_statutes(G: nx.DiGraph) -> None:
    # 약칭 역매핑
    alias_reverse = {v: k for k, v in _LAW_NAME_ALIASES.items()}
    for name, mst in _PRELOADED_MST.items():
        node_id = f"statute:{name}"
        G.add_node(node_id, type="statute", name=name, mst=mst,
                   short=alias_reverse.get(name, ""))
```

### 3.3 Phase 2: 조문 노드 구축

Legal API를 통해 각 법률의 조문 목록 조회:

```python
def build_articles(G: nx.DiGraph) -> None:
    """각 법률의 조문을 Legal API로 조회하여 노드 + CONTAINS 엣지 생성."""
    for statute_id, data in G.nodes(data=True):
        if data.get("type") != "statute":
            continue
        mst = data["mst"]
        name = data["name"]

        articles = fetch_article_list(mst)  # Legal API XML 파싱
        for art in articles:
            art_id = f"article:{name}:{art['number']}"
            G.add_node(art_id, type="article", statute=name,
                       number=art["number"], title=art.get("title", ""),
                       text_snippet=art.get("text", "")[:200])
            G.add_edge(statute_id, art_id, rel="CONTAINS")
```

**`fetch_article_list(mst)`** 함수: Legal API의 `lawService.do?MST={mst}` 엔드포인트를 호출하여 XML에서 조항 목록 파싱. 속도 제한을 위해 `time.sleep(0.5)` 삽입. 결과를 `data/article_cache/` 디렉토리에 JSON 캐시.

### 3.4 Phase 3: 조문 간 참조 추출 (CITES)

조문 텍스트에서 다른 조문 참조 패턴을 정규식으로 추출:

```python
# 참조 패턴 정규식
_CITE_PATTERNS = [
    # "제N조" (같은 법률 내 참조)
    re.compile(r'제(\d+)조(?:의(\d+))?'),
    # "동법 제N조" / "같은 법 제N조"
    re.compile(r'(?:동법|같은\s*법)\s*제(\d+)조'),
    # "근로기준법 제N조" (타법 참조)
    re.compile(r'(근로기준법|고용보험법|산업재해보상보험법|최저임금법|'
               r'근로자퇴직급여\s*보장법|남녀고용평등.*?법률|'
               r'기간제.*?법률|파견.*?법률|임금채권보장법|노동조합.*?법률|'
               r'소득세법|조세특례제한법)\s*제(\d+)조'),
]

def extract_cites(G: nx.DiGraph) -> int:
    """조문 텍스트에서 CITES 엣지 추출. 추가된 엣지 수 반환."""
    added = 0
    for node_id, data in list(G.nodes(data=True)):
        if data.get("type") != "article":
            continue
        text = data.get("text_snippet", "")
        statute = data["statute"]

        for pattern in _CITE_PATTERNS:
            for m in pattern.finditer(text):
                # 타법 참조 vs 같은법 참조 구분
                if len(m.groups()) >= 2 and m.group(1) and not m.group(1).isdigit():
                    target_statute = m.group(1)
                    target_num = int(m.group(2))
                else:
                    target_statute = statute
                    target_num = int(m.group(1))

                target_id = f"article:{target_statute}:{target_num}"
                if G.has_node(target_id) and target_id != node_id:
                    G.add_edge(node_id, target_id, rel="CITES")
                    added += 1
    return added
```

### 3.5 Phase 4: 개념 노드 (수동 매핑 테이블)

```python
CONCEPT_MAP = {
    "통상임금":     {"aliases": ["통상시급"], "articles": ["근로기준법:56", "근로기준법:2"]},
    "평균임금":     {"aliases": ["평균급"],   "articles": ["근로기준법:2", "근로기준법:34"]},
    "연장근로수당": {"aliases": ["연장수당"], "articles": ["근로기준법:56"]},
    "야간근로수당": {"aliases": ["야간수당"], "articles": ["근로기준법:56"]},
    "휴일근로수당": {"aliases": ["휴일수당"], "articles": ["근로기준법:56"]},
    "주휴수당":     {"aliases": [],          "articles": ["근로기준법:55"]},
    "최저임금":     {"aliases": ["최저시급"], "articles": ["최저임금법:6"]},
    "퇴직금":       {"aliases": ["퇴직급여"], "articles": ["근로자퇴직급여 보장법:8"]},
    "해고예고수당": {"aliases": [],          "articles": ["근로기준법:26"]},
    "부당해고":     {"aliases": ["부당 해고"], "articles": ["근로기준법:23"]},
    "연차유급휴가": {"aliases": ["연차", "연차수당"], "articles": ["근로기준법:60"]},
    "실업급여":     {"aliases": ["구직급여"], "articles": ["고용보험법:40"]},
    "육아휴직":     {"aliases": ["육아휴직급여"], "articles": ["남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률:19"]},
    "출산전후휴가": {"aliases": ["출산휴가", "산전후휴가"], "articles": ["근로기준법:74"]},
    "산재보상":     {"aliases": ["산재", "산업재해"], "articles": ["산업재해보상보험법:36"]},
    "4대보험":      {"aliases": ["사대보험"], "articles": ["고용보험법:8", "산업재해보상보험법:6"]},
    "근로계약":     {"aliases": [],          "articles": ["근로기준법:17"]},
    "직장내괴롭힘": {"aliases": ["직장 내 괴롭힘", "괴롭힘"], "articles": ["근로기준법:76"]},
    "임금체불":     {"aliases": ["체불", "밀린 임금"], "articles": ["근로기준법:36"]},
    "포괄임금제":   {"aliases": ["포괄임금"], "articles": []},
}
# ~20개 핵심 개념. 초기 구축 후 JSONL 분석에서 추가 발굴 가능.
```

### 3.6 Phase 5~6: 주제/계산기 노드

```python
# consultation_topic enum (prompts.py)
TOPICS = [
    "해고·징계", "임금·통상임금", "근로시간·휴일", "퇴직·퇴직금",
    "연차휴가", "산재보상", "비정규직", "노동조합", "직장내괴롭힘",
    "근로계약", "고용보험", "기타",
]

# Topic → Concept 매핑
TOPIC_CONCEPT_MAP = {
    "해고·징계":     ["부당해고", "해고예고수당"],
    "임금·통상임금": ["통상임금", "평균임금", "최저임금", "임금체불"],
    "근로시간·휴일": ["연장근로수당", "야간근로수당", "휴일근로수당", "주휴수당"],
    "퇴직·퇴직금":   ["퇴직금", "평균임금"],
    "연차휴가":       ["연차유급휴가"],
    "산재보상":       ["산재보상"],
    "직장내괴롭힘":   ["직장내괴롭힘"],
    "근로계약":       ["근로계약", "포괄임금제"],
    "고용보험":       ["실업급여", "육아휴직", "출산전후휴가"],
}

# Calculator → Concept 매핑 (CALC_TYPES에서 파생)
CALC_CONCEPT_MAP = {
    "overtime":        ["연장근로수당", "야간근로수당", "휴일근로수당"],
    "minimum_wage":    ["최저임금"],
    "weekly_holiday":  ["주휴수당"],
    "annual_leave":    ["연차유급휴가"],
    "dismissal":       ["해고예고수당", "부당해고"],
    "severance":       ["퇴직금", "평균임금"],
    "unemployment":    ["실업급여"],
    "insurance":       ["4대보험"],
    "parental_leave":  ["육아휴직"],
    "maternity_leave": ["출산전후휴가"],
    "wage_arrears":    ["임금체불"],
    "comprehensive":   ["포괄임금제", "통상임금"],
}
```

### 3.7 Phase 7~8: 판례 노드 + 법조문 연결

```python
def build_precedents(G: nx.DiGraph) -> None:
    """Pinecone 메타데이터 + 수동 매핑에서 판례 노드 생성."""
    # 수동 매핑: 주요 판례
    MAJOR_PRECEDENTS = {
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
        # ... 주요 판례 20~30개 수동 매핑
    }

    for case_num, info in MAJOR_PRECEDENTS.items():
        node_id = f"precedent:{case_num}"
        G.add_node(node_id, type="precedent", case_number=case_num,
                   court=info["court"], year=info["year"],
                   summary=info.get("summary", ""))
        # INTERPRETS 엣지
        for art_ref in info.get("articles", []):
            art_id = f"article:{art_ref}"
            if G.has_node(art_id):
                G.add_edge(node_id, art_id, rel="INTERPRETS")
        # 개념 연결
        for concept in info.get("concepts", []):
            cid = f"concept:{concept}"
            if G.has_node(cid):
                G.add_edge(node_id, cid, rel="INTERPRETS")
```

### 3.8 JSON 직렬화

```python
def save_graph(G: nx.DiGraph, path: str = "data/graph_data.json") -> None:
    data = nx.node_link_data(G)  # NetworkX 표준 node-link format
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

def load_graph(path: str = "data/graph_data.json") -> nx.DiGraph:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return nx.node_link_graph(data, directed=True)
```

---

## 4. `app/core/graph.py` — GraphRAG 검색 엔진

### 4.1 모듈 구조

```python
"""GraphRAG 검색 엔진 — NetworkX 기반 법령 지식 그래프 순회

그래프 로드 → 시드 노드 매칭 → 멀티홉 순회 → 컨텍스트 생성
"""

import json
import logging
import os
from pathlib import Path

import networkx as nx

logger = logging.getLogger(__name__)

# ── 글로벌 그래프 캐시 (Vercel serverless) ─────────────────────────
_graph: nx.DiGraph | None = None

def get_graph() -> nx.DiGraph | None:
    """그래프 lazy loading + 글로벌 캐시."""
    global _graph
    if _graph is not None:
        return _graph
    graph_path = Path(__file__).parent.parent.parent / "data" / "graph_data.json"
    if not graph_path.exists():
        logger.warning("graph_data.json not found — GraphRAG disabled")
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
```

### 4.2 시드 노드 매칭

```python
def find_seed_nodes(
    relevant_laws: list[str] | None,
    precedent_keywords: list[str] | None,
    consultation_topic: str | None,
    calculation_types: list[str] | None,
) -> list[str]:
    """AnalysisResult에서 추출한 정보를 그래프 노드 ID로 매칭.

    Returns:
        매칭된 노드 ID 리스트 (중복 제거, 최대 10개)
    """
    G = get_graph()
    if G is None:
        return []

    seeds: list[str] = []

    # 1. relevant_laws → Article 노드
    if relevant_laws:
        for law_ref in relevant_laws:
            node_id = _match_law_ref(G, law_ref)
            if node_id:
                seeds.append(node_id)

    # 2. precedent_keywords → Concept 노드
    if precedent_keywords:
        for kw in precedent_keywords:
            node_id = _match_concept(G, kw)
            if node_id:
                seeds.append(node_id)

    # 3. consultation_topic → Topic 노드
    if consultation_topic:
        tid = f"topic:{consultation_topic}"
        if G.has_node(tid):
            seeds.append(tid)

    # 4. calculation_types → Calculator 노드
    if calculation_types:
        for ct in calculation_types:
            cid = f"calc:{ct}"
            if G.has_node(cid):
                seeds.append(cid)

    # 중복 제거, 최대 10개
    seen = set()
    unique = []
    for s in seeds:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique[:10]
```

### 4.3 법조문 참조 매칭 (`_match_law_ref`)

```python
# "근로기준법 제56조" → "article:근로기준법:56"
_LAW_REF_RE = re.compile(
    r'(근로기준법|고용보험법|산업재해보상보험법|최저임금법|'
    r'근로자퇴직급여\s*보장법|남녀고용평등.*?법률|'
    r'기간제.*?법률|파견.*?법률|임금채권보장법|노동조합.*?법률|'
    r'소득세법|조세특례제한법)\s*제?(\d+)조'
)

def _match_law_ref(G: nx.DiGraph, ref: str) -> str | None:
    """법조문 참조 문자열을 Article 노드 ID로 매칭."""
    m = _LAW_REF_RE.search(ref)
    if m:
        node_id = f"article:{m.group(1)}:{m.group(2)}"
        if G.has_node(node_id):
            return node_id
        # Statute 노드라도 반환 (조문 번호 없는 경우)
        statute_id = f"statute:{m.group(1)}"
        if G.has_node(statute_id):
            return statute_id
    return None
```

### 4.4 개념 매칭 (`_match_concept`)

```python
def _match_concept(G: nx.DiGraph, keyword: str) -> str | None:
    """키워드를 Concept 노드 이름/aliases와 매칭."""
    # 정확 매칭
    cid = f"concept:{keyword}"
    if G.has_node(cid):
        return cid
    # aliases 검색
    for node_id, data in G.nodes(data=True):
        if data.get("type") != "concept":
            continue
        aliases = data.get("aliases", [])
        if keyword in aliases or keyword == data.get("name"):
            return node_id
    return None
```

### 4.5 멀티홉 순회

```python
def traverse_graph(
    seed_nodes: list[str],
    max_hops: int = 2,
    max_results: int = 30,
) -> list[dict]:
    """시드 노드에서 BFS 멀티홉 순회.

    Returns:
        [{"node_id": str, "data": dict, "distance": int, "path": list[str]}, ...]
        distance 오름차순 정렬
    """
    G = get_graph()
    if G is None or not seed_nodes:
        return []

    visited: dict[str, dict] = {}  # node_id → {distance, path}

    for seed in seed_nodes:
        if not G.has_node(seed):
            continue
        # BFS
        queue = [(seed, 0, [seed])]
        while queue:
            current, dist, path = queue.pop(0)
            if current in visited and visited[current]["distance"] <= dist:
                continue
            visited[current] = {"distance": dist, "path": path}

            if dist < max_hops:
                # 양방향 탐색 (successors + predecessors)
                for neighbor in set(G.successors(current)) | set(G.predecessors(current)):
                    if neighbor not in visited or visited[neighbor]["distance"] > dist + 1:
                        queue.append((neighbor, dist + 1, path + [neighbor]))

    # 결과 정렬: distance 오름차순, 시드 노드 자체 제외
    results = []
    for node_id, info in sorted(visited.items(), key=lambda x: x[1]["distance"]):
        if node_id in seed_nodes:
            continue  # 시드 자체는 제외
        data = G.nodes[node_id]
        results.append({
            "node_id": node_id,
            "data": dict(data),
            "distance": info["distance"],
            "path": info["path"],
        })
        if len(results) >= max_results:
            break

    return results
```

### 4.6 그래프 관련도 스코어

```python
def compute_graph_relevance(distance: int) -> float:
    """시드 노드로부터의 거리 → 0~1 관련도 스코어."""
    return 1.0 / (1.0 + distance)
    # distance=1 → 0.5, distance=2 → 0.333
```

### 4.7 컨텍스트 텍스트 생성

```python
def build_graph_context(
    seed_nodes: list[str],
    traversal_results: list[dict],
    max_chars: int = 2000,
) -> str:
    """그래프 순회 결과를 LLM 컨텍스트 텍스트로 변환.

    Returns:
        "=== 법령 관계 분석 ===" 형식의 텍스트
    """
    G = get_graph()
    if G is None:
        return ""

    sections = []

    # 1. 관련 법조문
    articles = [r for r in traversal_results if r["data"].get("type") == "article"]
    if articles:
        lines = ["[관련 법조문]"]
        for a in articles[:8]:
            d = a["data"]
            lines.append(f"- {d['statute']} 제{d['number']}조 ({d.get('title', '')})")
            if a["distance"] > 1:
                # 경로 설명
                path_desc = _describe_path(G, a["path"])
                if path_desc:
                    lines.append(f"  → 연결 경로: {path_desc}")
        sections.append("\n".join(lines))

    # 2. 관련 판례
    precedents = [r for r in traversal_results if r["data"].get("type") == "precedent"]
    if precedents:
        lines = ["[관련 판례]"]
        for p in precedents[:5]:
            d = p["data"]
            lines.append(f"- {d.get('court', '')} {d['case_number']}: {d.get('summary', '')[:100]}")
        sections.append("\n".join(lines))

    # 3. 법령 간 관계
    statutes = set()
    for r in traversal_results:
        if r["data"].get("type") == "article":
            statutes.add(r["data"]["statute"])
    for s in seed_nodes:
        sd = G.nodes.get(s, {})
        if sd.get("type") == "article":
            statutes.add(sd["statute"])
    if len(statutes) > 1:
        sections.append(f"[관련 법률 체계]\n관련 법률: {', '.join(sorted(statutes))}")

    result = "\n\n".join(sections)
    return result[:max_chars] if result else ""


def _describe_path(G: nx.DiGraph, path: list[str]) -> str:
    """그래프 경로를 사람이 읽을 수 있는 문장으로 변환."""
    if len(path) < 3:
        return ""
    parts = []
    for i in range(len(path) - 1):
        edge_data = G.get_edge_data(path[i], path[i+1]) or G.get_edge_data(path[i+1], path[i]) or {}
        rel = edge_data.get("rel", "연결")
        from_name = _node_display_name(G, path[i])
        to_name = _node_display_name(G, path[i+1])
        parts.append(f"{from_name} →({rel})→ {to_name}")
    return " → ".join(parts)


def _node_display_name(G: nx.DiGraph, node_id: str) -> str:
    """노드 ID → 사람이 읽을 수 있는 이름."""
    d = G.nodes.get(node_id, {})
    ntype = d.get("type", "")
    if ntype == "article":
        return f"{d['statute']} 제{d['number']}조"
    elif ntype == "statute":
        return d.get("name", node_id)
    elif ntype == "precedent":
        return d.get("case_number", node_id)
    elif ntype == "concept":
        return d.get("name", node_id)
    return node_id
```

### 4.8 통합 API (pipeline.py에서 호출)

```python
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
        context_text: LLM 컨텍스트용 텍스트
        traversal_results: 순회 결과 (하이브리드 스코어링용)
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
```

---

## 5. `pipeline.py` 통합 설계

### 5.1 삽입 위치

`process_question()` 내 컨텍스트 조립 직전 (현재 line ~940 부근, `# 3. 컨텍스트 구성` 직전):

```python
    # ── GraphRAG 검색 (NEW) ─────────────────────────────────────────
    graph_context = ""
    if analysis:
        try:
            from app.core.graph import graph_search
            graph_context, graph_results = graph_search(
                relevant_laws=analysis.relevant_laws,
                precedent_keywords=getattr(analysis, "precedent_keywords", None),
                consultation_topic=getattr(analysis, "consultation_topic", None),
                calculation_types=analysis.calculation_types if analysis.requires_calculation else None,
            )
        except Exception as e:
            logger.warning("GraphRAG 검색 실패 (fallback): %s", e)

    # 3. 컨텍스트 구성 (기존 코드)
    ...
```

### 5.2 컨텍스트 삽입

기존 `parts` 리스트에 그래프 컨텍스트 추가 (line ~970 부근, precedent_text 삽입 직전):

```python
    if graph_context:
        parts.append(f"법령 관계 분석 (지식 그래프):\n\n{graph_context}")
```

---

## 6. `rag.py` 하이브리드 스코어링 (선택적 — Phase 5에서 검증 후 적용)

### 6.1 그래프 스코어 병합

`rerank_results()` 이후, 그래프 순회 결과와 벡터 검색 결과를 매칭하여 스코어 보정:

```python
def merge_graph_scores(
    hits: list[dict],
    graph_results: list[dict],
    alpha: float = 0.7,     # 벡터/rerank 가중치
    beta: float = 0.3,      # 그래프 가중치
) -> list[dict]:
    """벡터 검색 결과에 그래프 관련도 스코어를 병합."""
    # 그래프 결과를 빠르게 조회할 수 있도록 인덱스
    graph_boost = {}
    for r in graph_results:
        d = r["data"]
        # article 노드 → Pinecone 제목 매칭
        if d.get("type") == "article":
            key = f"{d['statute']} 제{d['number']}조"
            graph_boost[key] = 1.0 / (1.0 + r["distance"])

    for hit in hits:
        title = hit.get("title", "")
        content = hit.get("content", "")
        boost = 0.0
        for key, score in graph_boost.items():
            if key in title or key in content:
                boost = max(boost, score)

        if boost > 0:
            original = hit.get("rerank_score", hit["score"])
            hit["graph_score"] = boost
            hit["final_score"] = alpha * original + beta * boost
        else:
            hit["final_score"] = hit.get("rerank_score", hit["score"])

    hits.sort(key=lambda x: x.get("final_score", x["score"]), reverse=True)
    return hits
```

**주의**: 이 하이브리드 스코어링은 Phase 5 테스트에서 효과를 검증한 뒤 적용. 초기에는 그래프 컨텍스트만 추가하는 것으로 시작.

---

## 7. Vercel 배포 고려사항

### 7.1 `data/graph_data.json` 배포

- `vercel.json`의 functions 설정에 영향 없음 (static 파일)
- 파일 크기 < 10MB → Vercel serverless 함수의 50MB 제한 이내
- `data/` 디렉토리를 `.gitignore`에 추가하지 않음 (커밋 대상)

### 7.2 글로벌 캐시 전략

```python
# app/core/graph.py의 _graph 변수
# Vercel serverless는 warm start 시 모듈 레벨 변수 유지
# cold start 시에만 JSON 재파싱 (~100ms)
_graph: nx.DiGraph | None = None
```

### 7.3 `requirements.txt` 변경

```
networkx>=3.0
```

NetworkX는 pure Python이므로 Vercel 빌드에 추가 설정 불필요.

---

## 8. 구현 순서 (Do Phase 가이드)

```
Step 1:  requirements.txt에 networkx 추가
Step 2:  data/ 디렉토리 생성 확인
Step 3:  build_graph.py 작성 — Phase 1~3 (법률/조문/참조)
Step 4:  build_graph.py 작성 — Phase 4~6 (개념/주제/계산기)
Step 5:  build_graph.py 작성 — Phase 7~8 (판례/연결)
Step 6:  build_graph.py 실행 → data/graph_data.json 생성
Step 7:  app/core/graph.py 작성 — 로드 + 시드 매칭
Step 8:  app/core/graph.py 작성 — 멀티홉 순회 + 컨텍스트 생성
Step 9:  app/core/graph.py 작성 — graph_search() 통합 API
Step 10: app/core/pipeline.py 수정 — 그래프 검색 호출 삽입
Step 11: app/core/pipeline.py 수정 — 컨텍스트 조립에 graph_context 추가
Step 12: 통합 테스트 (교차 법령 질문, 판례 연결 질문)
```

---

## 9. 테스트 시나리오

| 시나리오 | 시드 노드 | 기대 결과 |
|----------|----------|----------|
| "연장수당 계산해주세요" | `calc:overtime`, `concept:연장근로수당` | 근기법 제56조, 제50조 연결. 2023다302838 판례 포함 |
| "실업급여 받으면서 퇴직금도 받을 수 있나요?" | `concept:실업급여`, `concept:퇴직금` | 고용보험법 + 퇴직급여보장법 교차 법조문 |
| "부당해고 구제신청 절차" | `concept:부당해고`, `topic:해고·징계` | 근기법 제23조, 제28조 + 관련 판례 |
| "최저임금 위반인지 확인" | `calc:minimum_wage`, `concept:최저임금` | 최저임금법 제6조 + 근기법 관련 조문 |
| "그래프에 없는 법률 질문" | (매칭 없음) | graceful fallback — graph_context="" |
| "통상임금 판례 알려줘" | `concept:통상임금` | 2023다302838, 2012다89399 등 판례 노드 |
| Vercel cold start | N/A | graph_data.json 로드 < 200ms |
