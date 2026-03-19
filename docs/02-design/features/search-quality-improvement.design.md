# search-quality-improvement Design Document

> **Summary**: Pinecone 검색 품질 개선 — 소스별 네임스페이스 재구축, Contextual Retrieval 전면 적용, 멀티NS 하이브리드 검색
>
> **Project**: nodong.kr RAG 챗봇
> **Version**: 1.0
> **Author**: Claude
> **Date**: 2026-03-13
> **Status**: Draft
> **Planning Doc**: [search-quality-improvement.plan.md](../../01-plan/features/search-quality-improvement.plan.md)

---

## 1. Overview

### 1.1 Design Goals

1. `legal_consultation.py`의 멀티소스 검색 복구 — `precedent`, `interpretation`, `regulation` 네임스페이스를 실제로 생성
2. 모든 법률 소스에 Contextual Retrieval 적용 — 검색 품질 향상
3. `rag.py`와 `pipeline.py`의 검색을 멀티네임스페이스 방식으로 통합
4. 메타데이터 스키마 통일 — 모든 네임스페이스에서 동일한 필드명 사용

### 1.2 Design Principles

- **단일 업로드 파이프라인**: `pinecone_upload_contextual.py` 하나로 모든 소스 처리
- **기존 코드 최소 변경**: `legal_consultation.py`의 `search_multi_namespace()` 패턴을 `rag.py`에 재활용
- **점진적 마이그레이션**: 새 네임스페이스 완성 후 기존 `laborlaw`/`laborlaw-v2` 삭제
- **Graceful Degradation**: 네임스페이스 검색 실패 시 자동 스킵

---

## 2. Architecture

### 2.1 Component Diagram

```
                     ┌─────────────────────────────────────────┐
                     │        semiconductor-lithography         │
                     │             (Pinecone Index)             │
                     ├─────────┬────────────┬──────────┬───────┤
                     │precedent│interpret-  │regulation│  qa   │
                     │(판례)   │ation(행정) │(훈령)    │(Q&A)  │
                     └────┬────┴─────┬──────┴────┬─────┴───┬───┘
                          │          │           │         │
                          └──────────┴───────────┴─────────┘
                                         ▲
                                         │ query (parallel)
                     ┌───────────────────┴──────────────────┐
                     │           rag.py                      │
                     │   search_multi_namespace()            │
                     │   (ThreadPoolExecutor 병렬 검색)       │
                     └───────────────────┬──────────────────┘
                              ▲                    ▲
                              │                    │
                    ┌─────────┴──────┐   ┌────────┴────────┐
                    │  pipeline.py   │   │legal_consultation│
                    │  (_search)     │   │  .py             │
                    └────────────────┘   └─────────────────┘
```

### 2.2 Data Flow

#### Upload Flow (pinecone_upload_contextual.py)

```
소스 디렉토리 (output_*)
  → 마크다운 파싱 (title, meta, body)
  → 섹션 기반 청킹 (max 700자, 80자 overlap)
  → Claude Haiku 맥락 생성 (Contextual Retrieval)
  → "[맥락] {context}\n제목: {title}\n분류: {category}\n섹션: {section}\n\n{chunk_text}"
  → OpenAI 임베딩 (text-embedding-3-small)
  → Pinecone upsert (소스별 네임스페이스)
```

#### Search Flow (rag.py → pipeline.py)

```
사용자 질문
  → analyze_intent() → question_type, consultation_topic, relevant_laws
  → (법률상담) → legal_consultation.process_consultation()
                    → search_multi_namespace(주제별 NS 목록)
                    → fetch_relevant_articles(법제처 API)
                    → build_consultation_context()
  → (임금계산) → rag.search_multi_namespace(["qa", "interpretation"])
  → (일반 Q&A) → rag.search_multi_namespace(["qa"])
  → Claude 답변 생성
```

### 2.3 Dependencies

| Component | Depends On | Purpose |
|-----------|-----------|---------|
| `pinecone_upload_contextual.py` | OpenAI, Anthropic, Pinecone SDK | 벡터 업로드 |
| `rag.py` | OpenAI (임베딩), Pinecone (검색) | 벡터 검색 |
| `legal_consultation.py` | `rag.py`, `legal_api.py` | 법률상담 컨텍스트 조립 |
| `pipeline.py` | `rag.py`, `legal_consultation.py` | 질문 처리 오케스트레이션 |
| `config.py` | 환경변수 | API 클라이언트 초기화 |

---

## 3. Data Model

### 3.1 통합 메타데이터 스키마

모든 네임스페이스에서 동일한 메타데이터 구조를 사용한다.

```python
# Pinecone 벡터 메타데이터 (모든 네임스페이스 공통)
{
    "source_type": str,       # "precedent" | "interpretation" | "regulation" | "qa"
    "title": str,             # 문서 제목 (최대 200자)
    "category": str,          # 분류/카테고리 (최대 50자)
    "section": str,           # 섹션명 (최대 100자)
    "chunk_text": str,        # 원본 청크 텍스트 (최대 900자)
    "url": str,               # 원문 URL
    "date": str,              # 작성일
    "chunk_index": int,       # 문서 내 청크 순서
    "contextualized": bool,   # Contextual Retrieval 적용 여부 (항상 True)
}
```

### 3.2 네임스페이스 소스 매핑

| 네임스페이스 | source_type | 소스 디렉토리 | 예상 파일 수 | 예상 청크 수 |
|-------------|-------------|--------------|------------|------------|
| `precedent` | `precedent` | `output_법원 노동판례/` | 351 | ~2,100 |
| `interpretation` | `interpretation` | `output_노동부 행정해석/` | 1,439 | ~8,600 |
| `regulation` | `regulation` | `output_훈령예규고시지침/` | 161 | ~960 |
| `qa` | `qa` | `output_qna_2/` + `output_legal_cases/` | 9,921 | ~30,000 |

### 3.3 청크 ID 패턴

```
{source_type}_{post_id}_c{chunk_index}
```

예시: `precedent_1234567_c0`, `interpretation_2345678_c3`, `qa_case_001_c0`

---

## 4. 모듈별 상세 설계

### 4.1 pinecone_upload_contextual.py 확장

**현재 상태**: 행정해석 + 판례만 지원, 단일 네임스페이스(`laborlaw-v2`)에 업로드

**변경 사항**:

```python
# 기존
PINECONE_NAMESPACE = "laborlaw-v2"
SOURCES = [
    {"directory": "output_노동부 행정해석", "source_type": "interpretation", "label": "행정해석"},
    {"directory": "output_법원 노동판례", "source_type": "precedent", "label": "판례"},
]

# 변경: 소스별 네임스페이스 매핑 추가
SOURCES = [
    {
        "directory": "output_법원 노동판례",
        "namespace": "precedent",
        "source_type": "precedent",
        "label": "판례",
    },
    {
        "directory": "output_노동부 행정해석",
        "namespace": "interpretation",
        "source_type": "interpretation",
        "label": "행정해석",
    },
    {
        "directory": "output_훈령예규고시지침",
        "namespace": "regulation",
        "source_type": "regulation",
        "label": "훈령/예규",
    },
    {
        "directory": "output_qna_2",
        "namespace": "qa",
        "source_type": "qa",
        "label": "Q&A 상담",
    },
    {
        "directory": "output_legal_cases",
        "namespace": "qa",
        "source_type": "qa",
        "label": "법률 상담사례",
    },
]
```

**핵심 변경 포인트**:

1. **`PINECONE_NAMESPACE` 상수 삭제** → 소스별 `namespace` 필드 사용
2. **`process_source()`에서 `namespace` 참조**: `index.upsert(vectors=..., namespace=src["namespace"])`
3. **메타데이터 빌드 통일**: `build_vector()` 함수로 표준 스키마 적용
4. **`--source` 플래그 확장**: `--source 훈령` 등 새 소스 지원
5. **Q&A 대량 처리 최적화**: `output_qna_2` (9,807건)는 context 생성 비용이 크므로 `--skip-context` 옵션 추가 (Q&A는 제목+본문으로 충분, 맥락 생성 선택적)

```python
def build_vector(chunk: dict, embedding: list[float], context: str, source_config: dict) -> dict:
    """통합 메타데이터 스키마로 Pinecone 벡터 구성."""
    return {
        "id": chunk["chunk_id"],
        "values": embedding,
        "metadata": {
            "source_type": source_config["source_type"],
            "title": chunk["title"][:200],
            "category": chunk.get("category", "")[:50],
            "section": chunk["section"][:100],
            "chunk_text": chunk["chunk_text"][:900],
            "url": chunk.get("url", ""),
            "date": chunk.get("date", ""),
            "chunk_index": chunk["chunk_index"],
            "contextualized": bool(context),
        },
    }
```

### 4.2 rag.py 멀티네임스페이스 검색 업그레이드

**현재 상태**: 단일 네임스페이스(`config.namespace`) 검색

**변경 사항**: `legal_consultation.py`의 `search_multi_namespace()` 패턴을 `rag.py`로 이동하고, 두 모듈이 공유

```python
# rag.py — 변경 후

"""Pinecone 멀티네임스페이스 통합 검색"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# 기본 검색 네임스페이스 (question_type별)
DEFAULT_NAMESPACES = {
    "qa": ["qa"],
    "calculation": ["qa", "interpretation"],
    "consultation": ["precedent", "interpretation"],
    "general": ["qa"],
}


def _embed_query(query: str, config) -> list[float]:
    resp = config.openai_client.embeddings.create(
        model=config.embed_model,
        input=[query],
    )
    return resp.data[0].embedding


def search_multi_namespace(
    query: str,
    namespaces: list[str],
    config,
    top_k_per_ns: int = 3,
    threshold: float = 0.4,
) -> list[dict]:
    """여러 Pinecone 네임스페이스에서 병렬 검색 후 점수 순 통합.

    Returns:
        [{score, source_type, title, section, chunk_text, url, date, category}]
        점수 내림차순, 최대 10개
    """
    qvec = _embed_query(query, config)
    all_hits = []

    def _search_ns(ns: str) -> list[dict]:
        try:
            results = config.pinecone_index.query(
                vector=qvec,
                top_k=top_k_per_ns,
                namespace=ns,
                include_metadata=True,
            )
            hits = []
            for m in results.matches:
                if m.score < threshold:
                    continue
                md = m.metadata or {}
                hits.append({
                    "score": round(m.score, 4),
                    "source_type": md.get("source_type", ns),
                    "title": md.get("title", md.get("document_title", "")),
                    "section": md.get("section", md.get("section_title", "")),
                    "chunk_text": md.get("chunk_text", md.get("content", "")),
                    "url": md.get("url", ""),
                    "date": md.get("date", ""),
                    "category": md.get("category", ""),
                })
            return hits
        except Exception as e:
            logger.warning("네임스페이스 '%s' 검색 실패: %s", ns, e)
            return []

    with ThreadPoolExecutor(max_workers=min(len(namespaces), 5)) as pool:
        futures = {pool.submit(_search_ns, ns): ns for ns in namespaces}
        for fut in as_completed(futures):
            all_hits.extend(fut.result())

    all_hits.sort(key=lambda x: x["score"], reverse=True)
    return all_hits[:10]


# 하위 호환용 단일 NS 검색
def search_qna(question: str, calculation_type: str | None, config) -> list[dict]:
    """Q&A 검색 — 멀티NS 래퍼."""
    ns_list = DEFAULT_NAMESPACES.get("calculation" if calculation_type else "qa", ["qa"])
    return search_multi_namespace(question, ns_list, config, top_k_per_ns=3)


def search_legal(laws: list[str], legal_basis: list[str], config) -> list[dict]:
    """법령/판례 검색 — 멀티NS 래퍼."""
    if not laws and not legal_basis:
        return []
    query_parts = list(laws[:5]) + list(legal_basis[:5])
    legal_query = " ".join(query_parts)
    return search_multi_namespace(
        legal_query, ["precedent", "interpretation", "regulation"], config, top_k_per_ns=3
    )
```

### 4.3 legal_consultation.py 변경 사항

**최소 변경**: `search_multi_namespace()`를 `rag.py`에서 import하도록 변경

```python
# 기존 (자체 구현)
def search_multi_namespace(query, namespaces, config, top_k_per_ns=3, threshold=0.4):
    ...

# 변경 후 (rag.py에서 import)
from app.core.rag import search_multi_namespace
```

나머지 `TOPIC_SEARCH_CONFIG`, `build_consultation_context()`, `process_consultation()`는 변경 없음.

### 4.4 pipeline.py 변경 사항

**`_search()` 함수를 `rag.search_multi_namespace()`로 교체**:

```python
# 기존
def _search(query, config, top_k=5, threshold=0.4):
    qvec = _embed(query, config)
    results = config.pinecone_index.query(vector=qvec, top_k=top_k, include_metadata=True)
    ...

# 변경 후
from app.core.rag import search_multi_namespace

# _search() 호출부를 search_multi_namespace()로 교체
# 기본 NS: ["qa"] (일반 Q&A 검색)
```

### 4.5 config.py 변경 사항

**`namespace` 속성 제거, `embed_model` 속성 추가**:

```python
@dataclass
class AppConfig:
    openai_client: OpenAI
    pinecone_index: object
    claude_client: anthropic.Anthropic
    gemini_api_key: str | None = None
    supabase: SupabaseClient | None = None
    law_api_key: str | None = None
    analyzer_model: str = EXTRACT_MODEL
    embed_model: str = EMBED_MODEL           # 추가 (rag.py에서 사용)
    # namespace: str — 삭제 (멀티NS로 전환)
```

### 4.6 .env 변경 사항

```bash
# 삭제
# PINECONE_NAMESPACE=laborlaw
# PINECONE_HOST=https://...

# 유지
PINECONE_INDEX_NAME=semiconductor-lithography
```

### 4.7 search_quality_test.py 벤치마크 업데이트

```python
# 기존
NAMESPACES = ["laborlaw", "laborlaw-v2"]

# 변경: 새 네임스페이스 대상
NAMESPACES = ["precedent", "interpretation", "regulation", "qa"]

# 추가: 멀티NS 통합 검색 테스트
def search_multi_ns(index, vector, namespaces, top_k_per_ns=3):
    """여러 NS에서 검색 후 점수 순 통합 (rag.py 로직과 동일)"""
    ...
```

---

## 5. Error Handling

### 5.1 검색 실패 처리

| 시나리오 | 처리 | 로깅 |
|---------|------|------|
| 네임스페이스 미존재 | 해당 NS 스킵, 나머지 NS 결과 반환 | `logger.warning` |
| Pinecone 타임아웃 | 빈 결과 반환, 다른 NS 결과로 대체 | `logger.warning` |
| 임베딩 API 실패 | 3회 재시도 후 빈 결과 반환 | `logger.error` |
| 모든 NS 검색 실패 | 빈 컨텍스트로 LLM 답변 생성 (검색 없이) | `logger.error` |

### 5.2 업로드 실패 처리

| 시나리오 | 처리 |
|---------|------|
| 파일 읽기 실패 | 스킵, 에러 카운트 증가 |
| Claude Haiku 맥락 생성 실패 | 빈 맥락으로 fallback (표준 임베딩) |
| Pinecone upsert 실패 | 3회 재시도 후 스킵 |
| 진행 중단 | `--resume`로 이어서 처리 (progress file) |

---

## 6. Test Plan

### 6.1 Test Scope

| Type | Target | Method |
|------|--------|--------|
| 업로드 검증 | 4개 NS 벡터 수 확인 | `index.describe_index_stats()` |
| 검색 품질 | 16건 벤치마크 쿼리 | `search_quality_test.py` |
| 멀티NS 검색 | `search_multi_namespace()` 동작 | Python unit test |
| 통합 테스트 | `legal_consultation.py` 12개 주제 | 주제별 샘플 쿼리 |
| Regression | 기존 chatbot 응답 품질 | 수동 E2E 테스트 |

### 6.2 Test Cases (Key)

- [ ] Happy path: 판례 쿼리 → `precedent` NS에서 관련 결과 반환 (score ≥ 0.5)
- [ ] Happy path: "해고 정당한 이유" → `legal_consultation.py` → precedent + interpretation 결과 반환
- [ ] Happy path: 멀티NS 검색 → 결과가 score 내림차순 정렬
- [ ] Edge case: 존재하지 않는 NS 검색 → 에러 없이 빈 결과
- [ ] Edge case: 모든 NS 검색 결과 threshold 미만 → 빈 리스트 반환
- [ ] Performance: 3개 NS 병렬 검색 총 시간 < 1.5초

---

## 7. Implementation Guide

### 7.1 File Structure (변경 파일)

```
laborconsult/
├── pinecone_upload_contextual.py    # [수정] 소스별 NS 분리 + 통합 메타데이터
├── app/
│   ├── config.py                    # [수정] embed_model 속성 추가, namespace 관련 정리
│   └── core/
│       ├── rag.py                   # [수정] search_multi_namespace() 추가
│       ├── legal_consultation.py    # [수정] rag.py의 search_multi_namespace() import
│       └── pipeline.py             # [수정] _search()를 rag.search_multi_namespace()로 교체
├── search_quality_test.py           # [수정] 새 NS 대상 벤치마크
└── .env                             # [수정] PINECONE_NAMESPACE 삭제
```

### 7.2 Implementation Order

1. [ ] **Step 1: rag.py 멀티NS 검색 구현** — `search_multi_namespace()` 추가, 기존 `search_qna`/`search_legal` 래퍼 유지
2. [ ] **Step 2: config.py 업데이트** — `embed_model` 속성 추가
3. [ ] **Step 3: legal_consultation.py 리팩터링** — 자체 `search_multi_namespace()` 삭제, `rag.py`에서 import
4. [ ] **Step 4: pipeline.py 리팩터링** — `_search()` → `rag.search_multi_namespace()` 교체
5. [ ] **Step 5: pinecone_upload_contextual.py 확장** — 4개 소스 + 소스별 NS + 통합 메타데이터
6. [ ] **Step 6: 네임스페이스 업로드 실행** — `--dry-run` 후 실제 업로드 (소스별 단계적)
7. [ ] **Step 7: .env 정리** — `PINECONE_NAMESPACE`, `PINECONE_HOST` 삭제
8. [ ] **Step 8: 벤치마크 재실행** — `search_quality_test.py` 업데이트 + 실행
9. [ ] **Step 9: 기존 NS 삭제** — `laborlaw`, `laborlaw-v2` 네임스페이스 삭제 (확인 후)

### 7.3 예상 API 비용

| 소스 | 파일 수 | 예상 청크 | Claude Haiku (맥락) | OpenAI Embed | 합계 |
|------|---------|----------|-------------------|-------------|------|
| 판례 | 351 | ~2,100 | ~$1.70 | ~$0.01 | ~$1.71 |
| 행정해석 | 1,439 | ~8,600 | ~$6.90 | ~$0.05 | ~$6.95 |
| 훈령/예규 | 161 | ~960 | ~$0.77 | ~$0.01 | ~$0.78 |
| Q&A (skip-ctx) | 9,921 | ~30,000 | $0 (skip) | ~$0.18 | ~$0.18 |
| **합계** | **11,872** | **~41,660** | **~$9.37** | **~$0.25** | **~$9.62** |

> Q&A 30,000건에 Contextual Retrieval 적용 시 추가 ~$24. `--skip-context` 옵션으로 Q&A는 표준 임베딩만 사용 권장.

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-13 | Initial draft | Claude |
