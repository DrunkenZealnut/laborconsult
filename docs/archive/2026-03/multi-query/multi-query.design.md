# multi-query Design Document

> **Summary**: LLM 기반 쿼리 분해 모듈 설계 — Pinecone RAG 검색 recall 향상
>
> **Plan Reference**: `docs/01-plan/features/multi-query.plan.md`
> **Date**: 2026-03-16
> **Status**: Draft

---

## 1. Overview

사용자 질문을 Claude Haiku로 2~4개 관점별 검색 쿼리로 분해하여 `search_pinecone_multi()`에 전달, 검색 recall을 향상시킨다.

**변경 범위:**
- 신규: `app/core/query_decomposer.py`
- 수정: `app/core/pipeline.py` (검색 쿼리 구성 부분)
- 수정: `app/config.py` (분해용 모델 상수 추가)

---

## 2. Module Design

### 2.1 `app/core/query_decomposer.py` (신규)

```python
"""RAG 멀티쿼리 분해 모듈

사용자 질문을 LLM으로 여러 관점의 검색 쿼리로 분해하여
Pinecone 벡터 검색의 recall을 향상시킨다.
"""

from __future__ import annotations

import json
import logging
import time

import anthropic

logger = logging.getLogger(__name__)

DECOMPOSE_MODEL = "claude-haiku-4-5-20251001"
DECOMPOSE_TIMEOUT = 3.0   # 초 (Haiku 500ms 목표, 여유 포함)
MAX_QUERIES = 4
MIN_QUERY_LENGTH = 15     # 이 길이 미만의 질문은 분해 건너뜀


DECOMPOSE_SYSTEM = """당신은 한국 노동법 전문 검색 어시스턴트입니다.
사용자의 노동법 관련 질문을 벡터 검색에 최적화된 2~4개의 검색 쿼리로 분해하세요.

규칙:
1. 각 쿼리는 질문의 서로 다른 관점이나 하위 주제를 커버해야 합니다.
2. 법률 용어와 일상 용어를 혼합하여 다양한 문서를 검색할 수 있게 하세요.
3. 관련 법조문명이 있으면 쿼리에 포함하세요 (예: "근로기준법 제60조 연차휴가").
4. 각 쿼리는 20~60자 범위로 작성하세요.
5. 원본 질문의 핵심 의도를 반드시 하나 이상의 쿼리에 포함하세요.

JSON 배열로만 응답하세요. 설명 없이 쿼리 문자열 배열만 반환합니다."""


DECOMPOSE_USER_TEMPLATE = """다음 노동법 질문을 2~4개 검색 쿼리로 분해하세요:

질문: {query}
{context_line}
JSON 배열로 응답:"""


def _should_decompose(query: str) -> bool:
    """분해가 필요한 질문인지 판단.

    단순 질문(짧은 키워드, 단일 주제)은 분해 없이 원본 사용이 효율적.
    """
    if len(query.strip()) < MIN_QUERY_LENGTH:
        return False
    # 복합 질문 신호: 접속사, 쉼표, 물음표 2개 이상, "~하고", "~랑" 등
    complexity_markers = ["그리고", "또한", "그런데", "하고", "이랑", "랑", ",", "?"]
    marker_count = sum(1 for m in complexity_markers if m in query)
    # 길이가 충분히 길거나 복합 신호가 있으면 분해
    return len(query) >= 40 or marker_count >= 1


def decompose_query(
    query: str,
    client: anthropic.Anthropic,
    *,
    consultation_topic: str | None = None,
    question_summary: str | None = None,
) -> list[str]:
    """사용자 질문을 2~4개 검색 쿼리로 분해.

    Args:
        query: 원본 사용자 질문
        client: Anthropic 클라이언트
        consultation_topic: 분석된 상담 주제 (있으면 컨텍스트로 활용)
        question_summary: 분석된 질문 요약 (있으면 컨텍스트로 활용)

    Returns:
        분해된 검색 쿼리 리스트 (2~4개).
        분해 불필요/실패 시 빈 리스트 반환.
    """
    if not _should_decompose(query):
        logger.debug("쿼리 분해 건너뜀 (단순 질문): %r", query[:40])
        return []

    # 컨텍스트 라인 구성
    context_parts = []
    if consultation_topic:
        context_parts.append(f"주제: {consultation_topic}")
    if question_summary and question_summary != query[:len(question_summary)]:
        context_parts.append(f"요약: {question_summary}")
    context_line = "\n".join(context_parts)
    if context_line:
        context_line = f"\n{context_line}\n"

    user_msg = DECOMPOSE_USER_TEMPLATE.format(
        query=query,
        context_line=context_line,
    )

    start = time.monotonic()
    try:
        resp = client.messages.create(
            model=DECOMPOSE_MODEL,
            max_tokens=256,
            temperature=0.3,
            system=DECOMPOSE_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            timeout=DECOMPOSE_TIMEOUT,
        )
        raw = resp.content[0].text.strip()

        # JSON 파싱
        queries = json.loads(raw)
        if not isinstance(queries, list):
            raise ValueError(f"배열이 아닌 응답: {type(queries)}")

        # 문자열만 필터링, 빈 문자열 제거, 최대 개수 제한
        queries = [q.strip() for q in queries if isinstance(q, str) and q.strip()]
        queries = queries[:MAX_QUERIES]

        elapsed = (time.monotonic() - start) * 1000
        logger.info(
            "쿼리 분해 완료: %d개 쿼리, %.0fms — %r → %s",
            len(queries), elapsed, query[:40], queries,
        )
        return queries

    except json.JSONDecodeError as e:
        logger.warning("쿼리 분해 JSON 파싱 실패: %s (raw=%r)", e, raw[:200])
        return []
    except anthropic.APITimeoutError:
        elapsed = (time.monotonic() - start) * 1000
        logger.warning("쿼리 분해 타임아웃 (%.0fms)", elapsed)
        return []
    except Exception as e:
        logger.warning("쿼리 분해 실패: %s", e)
        return []
```

### 2.2 핵심 설계 결정

| 항목 | 결정 | 근거 |
|------|------|------|
| 모델 | `claude-haiku-4-5-20251001` | 저비용($0.25/1M input), 빠른 응답(~300ms), 한국어 가능 |
| 온도 | `0.3` | 다양성과 일관성 사이 균형. 0이면 너무 보수적, 0.7이면 불안정 |
| max_tokens | `256` | 쿼리 4개 × 60자 ≈ 120토큰이면 충분 |
| 타임아웃 | `3.0s` | Haiku 평균 300ms, 네트워크 지연 + 콜드 스타트 대비 |
| 분해 판단 | 길이 ≥ 40자 또는 복합 신호 | 짧은 질문은 원본이 더 효과적 |
| 출력 형식 | JSON 배열 | 파싱 확실, 별도 구분자 불필요 |

---

## 3. Pipeline Integration

### 3.1 수정 위치: `app/core/pipeline.py` (~line 800)

**현재 코드** (line 800-815):
```python
# 맥락 기반 쿼리 확장
prec_queries = []
if getattr(analysis, "precedent_keywords", None):
    prec_queries = build_precedent_queries(
        precedent_keywords=analysis.precedent_keywords,
        relevant_laws=analysis.relevant_laws or None,
        consultation_topic=analysis.consultation_topic,
    )

# ① Pinecone 벡터 검색 (우선)
pinecone_search_queries = prec_queries or [
    getattr(analysis, "question_summary", None) or query[:80]
]
pinecone_hits = search_pinecone_multi(
    pinecone_search_queries, config, top_k=5,
)
```

**변경 후:**
```python
from app.core.query_decomposer import decompose_query

# 맥락 기반 쿼리 확장 (기존 규칙 기반)
prec_queries = []
if getattr(analysis, "precedent_keywords", None):
    prec_queries = build_precedent_queries(
        precedent_keywords=analysis.precedent_keywords,
        relevant_laws=analysis.relevant_laws or None,
        consultation_topic=analysis.consultation_topic,
    )

# LLM 멀티쿼리 분해 (신규)
decomposed = decompose_query(
    query,
    config.claude_client,
    consultation_topic=getattr(analysis, "consultation_topic", None),
    question_summary=getattr(analysis, "question_summary", None),
)

# 쿼리 병합: LLM 분해 + 규칙 기반 + 폴백(원본)
merged_queries = _merge_search_queries(
    decomposed=decomposed,
    rule_based=prec_queries,
    fallback=getattr(analysis, "question_summary", None) or query[:80],
)

# ① Pinecone 벡터 검색
pinecone_hits = search_pinecone_multi(
    merged_queries, config, top_k=5,
)
```

### 3.2 쿼리 병합 함수 (pipeline.py 내 헬퍼)

```python
def _merge_search_queries(
    decomposed: list[str],
    rule_based: list[str],
    fallback: str,
    max_total: int = 5,
) -> list[str]:
    """LLM 분해 + 규칙 기반 쿼리를 병합, 중복 제거.

    우선순위: decomposed > rule_based > fallback
    """
    seen: set[str] = set()
    merged: list[str] = []

    for q in decomposed + rule_based:
        normalized = q.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            merged.append(q.strip())

    # 결과가 없으면 폴백
    if not merged:
        merged.append(fallback)

    return merged[:max_total]
```

### 3.3 config.py 수정

```python
# 기존 상수 옆에 추가
DECOMPOSE_MODEL = "claude-haiku-4-5-20251001"
```

실제로는 `query_decomposer.py` 내부에서 상수로 관리 (config.py import cycle 방지).

---

## 4. Prompt Design

### 4.1 시스템 프롬프트

```
당신은 한국 노동법 전문 검색 어시스턴트입니다.
사용자의 노동법 관련 질문을 벡터 검색에 최적화된 2~4개의 검색 쿼리로 분해하세요.

규칙:
1. 각 쿼리는 질문의 서로 다른 관점이나 하위 주제를 커버해야 합니다.
2. 법률 용어와 일상 용어를 혼합하여 다양한 문서를 검색할 수 있게 하세요.
3. 관련 법조문명이 있으면 쿼리에 포함하세요.
4. 각 쿼리는 20~60자 범위로 작성하세요.
5. 원본 질문의 핵심 의도를 반드시 하나 이상의 쿼리에 포함하세요.

JSON 배열로만 응답하세요.
```

### 4.2 사용자 프롬프트

```
다음 노동법 질문을 2~4개 검색 쿼리로 분해하세요:

질문: {query}
주제: {consultation_topic}  (있을 때만)
요약: {question_summary}    (있을 때만)

JSON 배열로 응답:
```

### 4.3 예상 입출력

| 사용자 질문 | 분해 결과 |
|-------------|-----------|
| "5년 근무 후 정리해고 당하면 퇴직금이랑 실업급여 얼마나 받을 수 있나요?" | `["정리해고 요건 근로기준법 제24조", "퇴직금 산정 방법 5년 근속 평균임금", "실업급여 수급 요건 구직급여 금액 산정"]` |
| "연차 안 쓰면 돈으로 받을 수 있나요? 근데 회사가 사용 촉진을 했대요" | `["미사용 연차 수당 지급 의무", "연차 사용 촉진 제도 근로기준법 제61조", "사용 촉진 후 연차수당 청구 가능 여부"]` |
| "주휴수당" | (분해 건너뜀 — 15자 미만) → `[]` |
| "야간근무 수당 계산" | (분해 건너뜀 — 40자 미만, 복합 신호 없음) → `[]` |

---

## 5. Error Handling & Fallback

### 5.1 폴백 전략

```
decompose_query() 호출
    ├─ 성공 → 분해 쿼리 반환 (2~4개)
    ├─ JSON 파싱 실패 → [] 반환 → 규칙 기반/폴백 쿼리 사용
    ├─ 타임아웃 → [] 반환 → 규칙 기반/폴백 쿼리 사용
    └─ 기타 예외 → [] 반환 → 규칙 기반/폴백 쿼리 사용

_merge_search_queries()
    ├─ decomposed + rule_based 모두 있음 → 병합 (최대 5개)
    ├─ decomposed만 있음 → decomposed 사용
    ├─ rule_based만 있음 → rule_based 사용
    └─ 둘 다 없음 → fallback (question_summary 또는 query[:80])
```

### 5.2 에러별 처리

| 에러 | 처리 | 로그 레벨 |
|------|------|-----------|
| `APITimeoutError` | `[]` 반환, 원본 쿼리로 진행 | WARNING |
| `JSONDecodeError` | `[]` 반환, raw 응답 200자 기록 | WARNING |
| `APIError` (rate limit 등) | `[]` 반환 | WARNING |
| 네트워크 에러 | `[]` 반환 | WARNING |

**원칙**: 분해 실패는 검색 품질 저하만 야기하고, 전체 파이프라인을 중단시키지 않는다.

---

## 6. Data Flow Diagram

```
사용자 질문: "5년 근무 후 정리해고 당하면 퇴직금이랑 실업급여?"
    │
    ├─① analyze_intent() ──────────────────────────────────────┐
    │   └→ AnalysisResult:                                      │
    │       precedent_keywords: ["정리해고", "퇴직금"]         │
    │       relevant_laws: ["근기법 제24조", "퇴직급여법 제8조"] │
    │       consultation_topic: "퇴직·퇴직금"                   │
    │       question_summary: "5년 근무 정리해고 시 퇴직금..."   │
    │                                                           │
    ├─② decompose_query() ← Claude Haiku (신규)                │
    │   └→ ["정리해고 요건 근로기준법 제24조",                   │
    │       "퇴직금 산정 방법 5년 근속 평균임금",                │
    │       "실업급여 수급 요건 구직급여 금액"]                  │
    │                                                           │
    ├─③ build_precedent_queries() (기존 규칙 기반)              │
    │   └→ ["정리해고 퇴직금",                                  │
    │       "부당해고 해고 제한"]                                │
    │                                                           │
    └─④ _merge_search_queries() ────────────────────────────────┘
        └→ ["정리해고 요건 근로기준법 제24조",
            "퇴직금 산정 방법 5년 근속 평균임금",
            "실업급여 수급 요건 구직급여 금액",
            "정리해고 퇴직금",
            "부당해고 해고 제한"]  ← 최대 5개, 중복 제거
                │
                └─⑤ search_pinecone_multi() → Pinecone 3개 NS 병렬 검색
                    └→ 검색 결과 (score 내림차순, 중복 ID 제거)
```

---

## 7. Implementation Order

| 순서 | 작업 | 파일 | 의존성 |
|:----:|------|------|--------|
| 1 | `query_decomposer.py` 신규 모듈 작성 | `app/core/query_decomposer.py` | 없음 |
| 2 | `_merge_search_queries()` 헬퍼 추가 | `app/core/pipeline.py` | 없음 |
| 3 | pipeline.py 검색 쿼리 구성 부분 수정 | `app/core/pipeline.py` (~line 800) | 1, 2 |
| 4 | 수동 테스트 — 복합 질문 3건 이상 | CLI / API | 1, 2, 3 |

---

## 8. Testing Strategy

### 8.1 단위 테스트 대상

| 함수 | 테스트 항목 |
|------|-------------|
| `_should_decompose()` | 짧은 질문 → False, 복합 질문 → True, 경계값 |
| `decompose_query()` | 정상 분해, JSON 파싱 실패 폴백, 타임아웃 폴백 |
| `_merge_search_queries()` | 병합 로직, 중복 제거, 빈 입력, max_total 제한 |

### 8.2 통합 테스트

기존 `test_e2e.py` 20건 통과 확인 — 분해 모듈 추가 후에도 기존 답변 품질 유지.

### 8.3 벤치마크 (선택)

복합 질문 셋에서 before/after recall 비교:
- 기존: `build_precedent_queries()` only → Pinecone hits
- 변경: `decompose_query()` + `build_precedent_queries()` 병합 → Pinecone hits

---

## 9. Cost & Performance Estimate

| 항목 | 수치 |
|------|------|
| Haiku 입력 | ~250 토큰/호출 (시스템 + 사용자) |
| Haiku 출력 | ~80 토큰/호출 (JSON 배열 3~4개) |
| 호출 비용 | ~$0.0001/호출 (Haiku $0.80/1M input, $4.00/1M output) |
| 일 1,000건 기준 | ~$0.10/일 |
| 지연 추가 | ~300ms (Haiku 평균) |
| Pinecone 추가 호출 | +2~3 쿼리 × 3 NS = +6~9 호출 (기존 대비) |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-16 | Initial design | Claude |
