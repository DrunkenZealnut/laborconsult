# rerank Design Document

> **Summary**: Cohere Rerank를 Pinecone 검색 결과에 적용하여 정밀도 향상
>
> **Plan Reference**: `docs/01-plan/features/rerank.plan.md`
> **Date**: 2026-03-16
> **Status**: Draft

---

## 1. Overview

Pinecone 벡터 검색 결과를 Cohere Rerank API(cross-encoder)로 재정렬하여 LLM에 전달되는 검색 결과의 정밀도를 높인다.

**변경 범위:**
- 수정: `app/core/rag.py` — `rerank_results()` 함수 추가
- 수정: `app/core/pipeline.py` — 검색 후 rerank 호출 (top_k 확대 + rerank)
- 수정: `app/config.py` — `cohere_api_key` 필드 추가
- 수정: `requirements.txt` — `cohere` 패키지 추가
- 수정: `.env.example` — `COHERE_API_KEY` 안내 추가

---

## 2. Module Design

### 2.1 `app/core/rag.py` — `rerank_results()` 추가

```python
import cohere

RERANK_MODEL = "rerank-v3.5"
RERANK_TOP_N = 5
RERANK_TIMEOUT = 3.0  # 초


def rerank_results(
    query: str,
    hits: list[dict],
    cohere_api_key: str,
    top_n: int = RERANK_TOP_N,
) -> list[dict]:
    """Cohere Rerank로 검색 결과 재정렬.

    Args:
        query: 원본 사용자 질문 (rerank 기준)
        hits: Pinecone 검색 결과 리스트
        cohere_api_key: Cohere API 키
        top_n: 반환할 상위 결과 수

    Returns:
        재정렬된 상위 top_n건. 실패 시 원본 hits[:top_n] 반환.
    """
    if not hits or not cohere_api_key:
        return hits[:top_n]

    try:
        co = cohere.ClientV2(api_key=cohere_api_key)

        # Rerank용 문서 텍스트 추출
        documents = []
        for h in hits:
            text = ""
            if h.get("title"):
                text += h["title"] + " "
            if h.get("section"):
                text += h["section"] + " "
            if h.get("content"):
                text += h["content"]
            documents.append(text.strip() or "(empty)")

        result = co.rerank(
            model=RERANK_MODEL,
            query=query,
            documents=documents,
            top_n=min(top_n, len(hits)),
        )

        # 재정렬된 인덱스로 hits 재구성
        reranked = []
        for item in result.results:
            hit = hits[item.index].copy()
            hit["rerank_score"] = round(item.relevance_score, 4)
            reranked.append(hit)

        logger.info(
            "Rerank 완료: %d건 → %d건 (model=%s)",
            len(hits), len(reranked), RERANK_MODEL,
        )
        return reranked

    except Exception as e:
        logger.warning("Rerank 실패, cosine 정렬 폴백: %s", e)
        return hits[:top_n]
```

### 2.2 핵심 설계 결정

| 항목 | 결정 | 근거 |
|------|------|------|
| 모델 | `rerank-v3.5` | 최신, 다국어(한국어) 지원 |
| 클라이언트 | `cohere.ClientV2` | V2 API가 최신, rerank 지원 |
| top_n | 5 | 기존 LLM 컨텍스트 크기 유지 |
| 타임아웃 | 3.0초 | 네트워크 지연 포함 여유 |
| 문서 텍스트 | title + section + content 결합 | rerank에 충분한 맥락 제공 |
| 실패 처리 | 원본 hits[:top_n] 반환 | 기존 동작 100% 보장 |
| 클라이언트 생성 | 함수 내 매번 생성 | import cycle 방지, 호출 빈도 낮아 오버헤드 무시 가능 |

---

## 3. Pipeline Integration

### 3.1 수정 위치: `app/core/pipeline.py` (~line 853-859)

**현재 코드:**
```python
# ① Pinecone 벡터 검색 (우선)
pinecone_hits = search_pinecone_multi(
    pinecone_search_queries, config, top_k=5,
)
if pinecone_hits:
    precedent_text, precedent_meta = format_pinecone_hits(pinecone_hits)
    logger.info("Pinecone 판례·행정해석 %d건 사용", len(pinecone_hits))
```

**변경 후:**
```python
from app.core.rag import search_pinecone_multi, format_pinecone_hits, rerank_results

# ① Pinecone 벡터 검색 (우선) — rerank 시 후보 확대
search_top_k = 15 if config.cohere_api_key else 5
pinecone_hits = search_pinecone_multi(
    pinecone_search_queries, config, top_k=search_top_k,
)

# ② Cohere Rerank (API 키 설정 시)
if pinecone_hits and config.cohere_api_key:
    pinecone_hits = rerank_results(
        query, pinecone_hits, config.cohere_api_key,
    )

if pinecone_hits:
    precedent_text, precedent_meta = format_pinecone_hits(pinecone_hits)
    logger.info("Pinecone 판례·행정해석 %d건 사용", len(pinecone_hits))
```

### 3.2 import 변경

```python
# 기존
from app.core.rag import search_pinecone_multi, format_pinecone_hits
# 변경
from app.core.rag import search_pinecone_multi, format_pinecone_hits, rerank_results
```

---

## 4. Config Changes

### 4.1 `app/config.py`

```python
@dataclass
class AppConfig:
    openai_client: OpenAI
    pinecone_index: object
    claude_client: anthropic.Anthropic
    gemini_api_key: str | None = None
    supabase: SupabaseClient | None = None
    law_api_key: str | None = None
    odcloud_api_key: str | None = None
    cohere_api_key: str | None = None          # ← 추가
    analyzer_model: str = EXTRACT_MODEL
    embed_model: str = EMBED_MODEL
```

`from_env()`에 추가:
```python
cohere_api_key = os.getenv("COHERE_API_KEY")
return cls(
    ...
    cohere_api_key=cohere_api_key,
)
```

### 4.2 `requirements.txt`

```
cohere>=5.0.0
```

### 4.3 `.env.example`

```
# Cohere - Rerank 검색 결과 재정렬용 (선택)
COHERE_API_KEY=your_cohere_api_key_here
```

---

## 5. Data Flow Diagram

```
사용자 질문: "5년 근무 후 정리해고 당하면 퇴직금이랑 실업급여?"
    │
    ├─ decompose_query() → 3개 쿼리 (multi-query)
    ├─ build_precedent_queries() → 2개 쿼리
    └─ _merge_search_queries() → 5개 쿼리
            │
            ▼
    search_pinecone_multi(top_k=15)
            │  3개 NS × 5개 쿼리 × 15건 = 최대 225건 → 중복 제거 → ~30건 후보
            ▼
    rerank_results(query, 30건, cohere_api_key)
            │  Cohere rerank-v3.5: 쿼리-문서 쌍 분석
            ▼
    상위 5건 (relevance_score 정렬)
            │
            ▼
    format_pinecone_hits() → LLM 컨텍스트
```

---

## 6. Error Handling & Fallback

```
rerank_results() 호출
    ├─ cohere_api_key 없음 → hits[:top_n] 그대로 반환
    ├─ hits 빈 리스트 → 빈 리스트 반환
    ├─ API 성공 → 재정렬된 top_n 반환
    ├─ API 타임아웃 → hits[:top_n] 폴백 + WARNING 로그
    ├─ API 에러 (rate limit 등) → hits[:top_n] 폴백 + WARNING 로그
    └─ 기타 예외 → hits[:top_n] 폴백 + WARNING 로그
```

**원칙**: Rerank 실패는 정밀도 저하만 야기하고, 전체 파이프라인을 중단시키지 않는다. API 키 미설정 환경(CI/CD, 신규 개발자)에서도 100% 정상 동작.

---

## 7. Implementation Order

| 순서 | 작업 | 파일 | 의존성 |
|:----:|------|------|--------|
| 1 | `requirements.txt`에 `cohere` 추가 | `requirements.txt` | 없음 |
| 2 | `AppConfig`에 `cohere_api_key` 추가 | `app/config.py` | 없음 |
| 3 | `.env.example`에 `COHERE_API_KEY` 추가 | `.env.example` | 없음 |
| 4 | `rerank_results()` 함수 추가 | `app/core/rag.py` | 1 |
| 5 | pipeline.py 검색 부분에 rerank 통합 | `app/core/pipeline.py` | 2, 4 |
| 6 | 수동 테스트 — rerank 유무 비교 | CLI / API | 1~5 |

---

## 8. Testing Strategy

### 8.1 테스트 항목

| 함수/시나리오 | 테스트 내용 |
|---------------|-------------|
| `rerank_results()` — 정상 | 30건 입력 → 5건 재정렬 반환, rerank_score 포함 |
| `rerank_results()` — API 키 없음 | 원본 hits[:5] 반환 |
| `rerank_results()` — 빈 hits | 빈 리스트 반환 |
| `rerank_results()` — API 실패 | 원본 hits[:5] 폴백 |
| pipeline — COHERE_API_KEY 있음 | top_k=15 → rerank → 5건 |
| pipeline — COHERE_API_KEY 없음 | top_k=5, rerank 건너뜀 (기존 동작) |

### 8.2 통합 테스트

기존 `test_e2e.py` — API 키 없는 환경에서도 통과 확인.

---

## 9. Cost & Performance

| 항목 | 수치 |
|------|------|
| Rerank 입력 | ~15건 × 평균 200자 = ~3,000자 |
| 호출 비용 | ~$0.002/검색 (rerank-v3.5) |
| 일 1,000건 기준 | ~$2/일 |
| 지연 추가 | ~200-400ms |
| Pinecone 추가 호출 | top_k 5→15 (같은 쿼리, 더 많은 결과) |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-16 | Initial design | Claude |
