# 맥락 기반 판례 검색(Contextual Precedent Search) Design Document

> **Summary**: Analyzer의 `precedent_keywords` 추출 + 쿼리 확장 모듈 + 다중 병렬 검색으로 법제처 판례 API 적중률을 높인다.
>
> **Project**: nodong.kr 노동법 Q&A 챗봇
> **Author**: Claude + zealnutkim
> **Date**: 2026-03-15
> **Status**: Draft
> **Planning Doc**: [contextual-precedent-search.plan.md](../../01-plan/features/contextual-precedent-search.plan.md)

---

## 1. Overview

### 1.1 Design Goals

1. 사용자의 일상어 질문에서 법적 쟁점 키워드를 추출하여 판례 검색 품질 향상
2. 기존 코드 흐름(analyzer → pipeline → legal_api)을 최소한으로 변경
3. 키워드 추출 실패 시 기존 `question_summary` 폴백 100% 보장
4. 다중 쿼리 병렬 검색으로 latency 증가 최소화

### 1.2 Design Principles

- **최소 변경**: 기존 아키텍처(analyzer → pipeline → legal_api)를 유지하고, 쿼리 구성 부분만 교체
- **폴백 우선**: 새 로직 실패 시 반드시 기존 로직으로 폴백
- **관심사 분리**: 쿼리 확장 로직은 별도 모듈(`precedent_query.py`)로 분리

---

## 2. Architecture

### 2.1 변경 전 (현재)

```
사용자 질문
    │
    ▼
analyzer.py ──→ AnalysisResult { question_summary, relevant_laws, ... }
    │
    ▼
pipeline.py:794
    prec_query = question_summary or query[:80]  ← 단순 전달
    │
    ▼
legal_api.py::search_precedent(prec_query)  ← 단일 쿼리, max 3건
    │
    ▼
법제처 API → 판례 최대 3건
```

### 2.2 변경 후 (설계)

```
사용자 질문
    │
    ▼
analyzer.py ──→ AnalysisResult { ..., precedent_keywords: ["부당해고", "해고예고수당"] }
    │
    ▼
pipeline.py (수정)
    │
    ├─ precedent_keywords 있으면 ──→ precedent_query.py::build_precedent_queries()
    │                                    │
    │                                    ├─ 키워드 조합 쿼리 생성 (2~3개)
    │                                    ├─ relevant_laws → 쟁점 키워드 역매핑
    │                                    └─ consultation_topic → 기본 키워드 보강
    │                                    │
    │                                    ▼
    │                              ["부당해고 해고예고수당",
    │                               "근로기준법 제23조 해고 제한"]
    │
    └─ precedent_keywords 없으면 ──→ 기존 question_summary 폴백
    │
    ▼
legal_api.py::search_precedent_multi(queries, max_total=5)
    │
    ├─ ThreadPoolExecutor 병렬 검색
    ├─ 판례일련번호 기준 중복 제거
    └─ 최대 5건 반환
    │
    ▼
법제처 API → 판례 최대 5건 (기존 3건 → 5건 증가)
```

### 2.3 Dependencies

| Component | Depends On | Purpose |
|-----------|-----------|---------|
| `precedent_query.py` (신규) | `legal_consultation.py::TOPIC_SEARCH_CONFIG` | 주제별 기본 법조문 참조 |
| `pipeline.py` (수정) | `precedent_query.py` | 쿼리 확장 호출 |
| `analyzer.py` (수정) | `prompts.py` | `precedent_keywords` 추출 |
| `legal_api.py` (수정) | 없음 (자체 완결) | `search_precedent_multi()` 추가 |

---

## 3. Data Model

### 3.1 AnalysisResult 변경

**파일**: `app/models/schemas.py`

```python
class AnalysisResult(BaseModel):
    # ... 기존 필드 유지 ...
    question_summary: str = ""
    consultation_type: str | None = None
    consultation_topic: str | None = None
    # ── 신규 필드 ──
    precedent_keywords: list[str] = []   # 판례 검색용 법적 쟁점 키워드 (2~5개)
```

### 3.2 ANALYZE_TOOL 스키마 변경

**파일**: `app/templates/prompts.py`

```python
# ANALYZE_TOOL["input_schema"]["properties"]에 추가
"precedent_keywords": {
    "type": "array",
    "items": {"type": "string"},
    "description": (
        "이 질문과 관련된 판례를 검색하기 위한 법적 쟁점 키워드 2~5개. "
        "사용자의 일상어가 아닌 법률 용어를 사용하세요. "
        "예: '사장이 갑자기 나가라고 함' → ['부당해고', '해고예고수당', '해고 제한'] "
        "예: '야근비를 안 줘요' → ['연장근로수당', '통상임금', '가산임금'] "
        "예: '퇴직금이 적은 것 같아요' → ['퇴직금 산정', '평균임금', '통상임금 포함범위']"
    ),
},
```

---

## 4. 모듈 상세 설계

### 4.1 `app/core/precedent_query.py` (신규)

```python
"""판례 검색 쿼리 확장 모듈

Analyzer가 추출한 precedent_keywords + relevant_laws + consultation_topic을
조합하여 법제처 판례 API에 보낼 검색 쿼리 리스트를 생성한다.
"""

# ── 법조문 → 쟁점 키워드 역매핑 ─────────────────────────────────────────────
LAW_TO_ISSUE: dict[str, list[str]] = {
    "근로기준법 제23조": ["부당해고", "해고 제한"],
    "근로기준법 제26조": ["해고예고", "해고예고수당"],
    "근로기준법 제27조": ["해고 서면통지"],
    "근로기준법 제28조": ["부당해고 구제신청"],
    "근로기준법 제36조": ["금품 청산", "임금 체불"],
    "근로기준법 제43조": ["임금 지급", "임금 체불"],
    "근로기준법 제46조": ["휴업수당"],
    "근로기준법 제50조": ["근로시간", "법정근로시간"],
    "근로기준법 제53조": ["연장근로 제한"],
    "근로기준법 제55조": ["휴일", "주휴일"],
    "근로기준법 제56조": ["연장근로수당", "야간근로수당", "휴일근로수당", "가산임금"],
    "근로기준법 제60조": ["연차 유급휴가", "연차수당"],
    "근로기준법 제2조":  ["통상임금", "평균임금"],
    "근로기준법 제18조": ["단시간근로자", "초단시간근로"],
    "근로기준법 제76조의2": ["직장 내 괴롭힘"],
    "최저임금법 제6조": ["최저임금", "최저임금 산입범위"],
    "근로자퇴직급여 보장법 제8조": ["퇴직금", "퇴직금 산정"],
    "고용보험법 제40조": ["실업급여", "구직급여"],
    "고용보험법 제69조": ["육아휴직급여"],
    "산업재해보상보험법 제37조": ["업무상 재해", "산재"],
    "임금채권보장법 제7조": ["대지급금", "체당금"],
}

# ── 주제별 기본 판례 검색 키워드 ──────────────────────────────────────────────
TOPIC_DEFAULT_KEYWORDS: dict[str, list[str]] = {
    "해고·징계": ["부당해고", "해고 제한", "해고예고"],
    "임금·통상임금": ["통상임금", "평균임금", "임금 체불"],
    "근로시간·휴일": ["연장근로", "야간근로", "휴일근로", "가산임금"],
    "퇴직·퇴직금": ["퇴직금 산정", "평균임금", "퇴직금 중간정산"],
    "연차휴가": ["연차 유급휴가", "연차수당", "사용 촉진"],
    "산재보상": ["업무상 재해", "산재 인정", "출퇴근 재해"],
    "비정규직": ["기간제 근로자", "차별 시정", "무기계약"],
    "직장내괴롭힘": ["직장 내 괴롭힘", "사용자 조치 의무"],
    "근로계약": ["근로조건 명시", "근로계약 위반"],
    "고용보험": ["실업급여", "구직급여", "수급 자격"],
}


def build_precedent_queries(
    precedent_keywords: list[str],
    relevant_laws: list[str] | None = None,
    consultation_topic: str | None = None,
    max_queries: int = 3,
) -> list[str]:
    """판례 검색용 쿼리 리스트 생성 (최대 max_queries개).

    전략:
    1. precedent_keywords를 1개 쿼리로 합침 (핵심 쿼리)
    2. relevant_laws에서 쟁점 키워드를 추출하여 보조 쿼리 생성
    3. consultation_topic 기본 키워드로 보충 쿼리 생성
    중복 쿼리 제거 후 max_queries개 반환.
    """
    queries: list[str] = []
    seen_terms: set[str] = set()

    # 1. 핵심 쿼리: precedent_keywords 합침
    if precedent_keywords:
        core_query = " ".join(precedent_keywords[:4])
        queries.append(core_query)
        seen_terms.update(precedent_keywords)

    # 2. 법조문 역매핑 쿼리
    if relevant_laws:
        law_issues: list[str] = []
        for law_ref in relevant_laws:
            # "근로기준법 제56조" → 매핑 테이블 조회
            for law_key, issues in LAW_TO_ISSUE.items():
                if law_key in law_ref:
                    for issue in issues:
                        if issue not in seen_terms:
                            law_issues.append(issue)
                            seen_terms.add(issue)
        if law_issues and len(queries) < max_queries:
            queries.append(" ".join(law_issues[:4]))

    # 3. 주제 기본 키워드 보충
    if consultation_topic and len(queries) < max_queries:
        topic_kws = TOPIC_DEFAULT_KEYWORDS.get(consultation_topic, [])
        unseen = [kw for kw in topic_kws if kw not in seen_terms]
        if unseen:
            queries.append(" ".join(unseen[:3]))

    # 쿼리가 0개이면 빈 리스트 반환 (호출측에서 폴백 처리)
    return queries[:max_queries]
```

### 4.2 `app/core/legal_api.py` 변경 — `search_precedent_multi()` 추가

기존 `search_precedent()` 함수는 변경하지 않고, 다중 쿼리 함수를 추가한다.

```python
def search_precedent_multi(
    queries: list[str],
    api_key: str,
    max_total: int = 5,
) -> list[dict]:
    """복수 쿼리로 판례 병렬 검색 → 중복 제거 후 max_total건 반환.

    각 쿼리당 max_results=3으로 검색하고, 판례일련번호 기준 중복 제거.
    """
    if not queries or not api_key:
        return []

    seen_ids: set[int] = set()
    all_results: list[dict] = []

    def _search_one(q: str) -> list[dict]:
        return search_precedent(q, api_key, max_results=3)

    with ThreadPoolExecutor(max_workers=min(len(queries), 3)) as pool:
        futures = {pool.submit(_search_one, q): q for q in queries}
        for fut in as_completed(futures):
            try:
                results = fut.result()
                for r in results:
                    if r["id"] not in seen_ids:
                        seen_ids.add(r["id"])
                        all_results.append(r)
            except Exception as e:
                logger.warning("판례 다중검색 개별 실패 (%s): %s",
                               futures[fut], e)

    return all_results[:max_total]
```

**위치**: `search_precedent()` 함수 바로 아래 (약 513줄 이후)

### 4.3 `app/templates/prompts.py` 변경

**변경 1**: ANALYZE_TOOL 스키마에 `precedent_keywords` 추가

```python
# 기존 consultation_topic 추가 코드 아래에 추가 (약 116줄 이후)
ANALYZE_TOOL["input_schema"]["properties"]["precedent_keywords"] = {
    "type": "array",
    "items": {"type": "string"},
    "description": (
        "이 질문과 관련된 판례를 검색하기 위한 법적 쟁점 키워드 2~5개. "
        "사용자의 일상어가 아닌 법률 용어를 사용하세요. "
        "예: '사장이 갑자기 나가라고 함' → ['부당해고', '해고예고수당', '해고 제한'] "
        "예: '야근비를 안 줘요' → ['연장근로수당', '통상임금', '가산임금'] "
        "예: '퇴직금이 적은 것 같아요' → ['퇴직금 산정', '평균임금', '통상임금 포함범위']"
    ),
}
```

**변경 2**: ANALYZER_SYSTEM 프롬프트에 키워드 추출 지침 추가

```
14. **판례 검색 키워드 추출** (precedent_keywords):
   - 질문의 법적 쟁점을 2~5개 법률 용어로 추출하세요.
   - 사용자의 일상어를 법률 용어로 변환하세요:
     "짤리다/나가라고 함" → "부당해고"
     "야근비/잔업수당" → "연장근로수당"
     "월급이 적다" → "최저임금"
     "그만둔다고 했더니 안 준다" → "퇴직금"
     "다쳤는데 회사가 안 해줘요" → "산재보상"
   - 계산이 필요한 질문(requires_calculation=true)에도 설정하세요.
   - 법률상담 질문에는 특히 중요합니다.
```

### 4.4 `app/core/analyzer.py` 변경

`analyze_intent()` 함수의 반환부에서 `precedent_keywords` 필드를 추출.

```python
# 기존 (약 168줄)
return AnalysisResult(
    requires_calculation=inp.get("requires_calculation", False),
    ...
    consultation_topic=inp.get("consultation_topic"),
)

# 변경 후
return AnalysisResult(
    requires_calculation=inp.get("requires_calculation", False),
    ...
    consultation_topic=inp.get("consultation_topic"),
    precedent_keywords=inp.get("precedent_keywords", []),  # 추가
)
```

### 4.5 `app/core/pipeline.py` 변경

**수정 구간**: 789~801줄 (판례 검색 호출부)

```python
# ── 변경 전 ──
# 2-1b. 법제처 API 키워드 기반 판례 검색
precedent_text = None
precedent_meta: list[dict] = []
if analysis and config.law_api_key:
    prec_query = getattr(analysis, "question_summary", None) or query[:80]
    try:
        yield {"type": "status", "text": "관련 판례 검색 중..."}
        precedent_text, precedent_meta = fetch_relevant_precedents(
            prec_query, config.law_api_key, max_results=3,
        )
    except Exception as e:
        logger.warning("판례 키워드 검색 실패 (무시하고 진행): %s", e)

# ── 변경 후 ──
# 2-1b. 법제처 API 맥락 기반 판례 검색
precedent_text = None
precedent_meta: list[dict] = []
if analysis and config.law_api_key:
    # 맥락 기반 쿼리 확장 시도 → 실패 시 기존 question_summary 폴백
    prec_queries = []
    if getattr(analysis, "precedent_keywords", None):
        from app.core.precedent_query import build_precedent_queries
        prec_queries = build_precedent_queries(
            precedent_keywords=analysis.precedent_keywords,
            relevant_laws=analysis.relevant_laws or None,
            consultation_topic=analysis.consultation_topic,
        )

    try:
        yield {"type": "status", "text": "관련 판례 검색 중..."}
        if prec_queries:
            # 다중 쿼리 검색 → 판결요지 조회
            from app.core.legal_api import search_precedent_multi
            prec_results = search_precedent_multi(
                prec_queries, config.law_api_key, max_total=5,
            )
            if prec_results:
                precedent_text, precedent_meta = _fetch_precedent_details(
                    prec_results, config.law_api_key,
                )
            else:
                # 다중 쿼리 결과 없음 → 기존 방식 폴백
                prec_query = getattr(analysis, "question_summary", None) or query[:80]
                precedent_text, precedent_meta = fetch_relevant_precedents(
                    prec_query, config.law_api_key, max_results=3,
                )
        else:
            # 키워드 없음 → 기존 방식
            prec_query = getattr(analysis, "question_summary", None) or query[:80]
            precedent_text, precedent_meta = fetch_relevant_precedents(
                prec_query, config.law_api_key, max_results=3,
            )
    except Exception as e:
        logger.warning("판례 검색 실패 (무시하고 진행): %s", e)
```

**추가 헬퍼**: `_fetch_precedent_details()` — `search_precedent_multi()`의 결과를 `fetch_precedent()`로 병렬 조회.

이 함수는 기존 `fetch_relevant_precedents()` 내부 로직(762~800줄)과 동일한 패턴이므로,
`fetch_relevant_precedents()`의 내부 조회 부분을 재사용하거나 `legal_api.py`에
`fetch_precedent_details(prec_results, api_key)` 함수로 추출한다.

```python
# legal_api.py에 추가
def fetch_precedent_details(
    prec_results: list[dict],
    api_key: str,
) -> tuple[str | None, list[dict]]:
    """검색된 판례 리스트의 판결요지를 병렬 조회하여 포매팅.

    fetch_relevant_precedents()의 후반부 로직을 재사용.
    """
    if not prec_results:
        return None, []

    t0 = time.time()
    texts: dict[int, str] = {}
    meta_list: list[dict] = []

    def _fetch_one(idx: int, prec: dict) -> tuple[int, str | None]:
        text = fetch_precedent(prec["id"], api_key)
        if text:
            header = f"[{prec['court']} {prec['case_name']}] (선고일: {prec['date']})"
            return idx, f"{header}\n{text}"
        return idx, None

    with ThreadPoolExecutor(max_workers=min(len(prec_results), 5)) as pool:
        futures = {
            pool.submit(_fetch_one, i, p): i
            for i, p in enumerate(prec_results)
        }
        for fut in as_completed(futures):
            try:
                idx, prec_text = fut.result()
                if prec_text:
                    texts[idx] = prec_text
                    p = prec_results[idx]
                    meta_list.append({
                        "case_name": p["case_name"],
                        "date": p["date"],
                        "court": p["court"],
                    })
            except Exception as e:
                logger.warning("판례 상세 조회 실패: %s", e)

    elapsed = time.time() - t0
    logger.info("판례 상세 조회 완료: %d/%d건 / %.2fs",
                len(texts), len(prec_results), elapsed)

    if not texts:
        return None, []

    formatted = "\n\n---\n\n".join(texts[k] for k in sorted(texts))
    return formatted, meta_list
```

---

## 5. 변경 파일 요약

| # | 파일 | 변경 유형 | 변경 내용 | 예상 줄수 |
|---|------|-----------|-----------|-----------|
| 1 | `app/models/schemas.py` | 수정 | `precedent_keywords: list[str] = []` 필드 추가 | +1줄 |
| 2 | `app/templates/prompts.py` | 수정 | ANALYZE_TOOL 스키마 + ANALYZER_SYSTEM 프롬프트 추가 | +25줄 |
| 3 | `app/core/analyzer.py` | 수정 | `precedent_keywords` 반환 필드 추가 | +1줄 |
| 4 | `app/core/precedent_query.py` | **신규** | 쿼리 확장 모듈 (매핑 테이블 + build_precedent_queries) | ~100줄 |
| 5 | `app/core/legal_api.py` | 수정 | `search_precedent_multi()` + `fetch_precedent_details()` 추가 | ~60줄 |
| 6 | `app/core/pipeline.py` | 수정 | 판례 검색 호출부 교체 (789~801줄) | ~30줄 |

**총 변경량**: 신규 1파일(~100줄) + 수정 5파일(~120줄) = 약 220줄

---

## 6. Error Handling

### 6.1 폴백 전략

| 실패 지점 | 폴백 행동 |
|-----------|-----------|
| Analyzer가 `precedent_keywords` 미반환 | 기존 `question_summary` 사용 |
| `build_precedent_queries()` 예외 | 기존 `question_summary` 사용 |
| `search_precedent_multi()` 결과 0건 | 기존 `fetch_relevant_precedents(question_summary)` |
| 개별 쿼리 API 타임아웃 | 해당 쿼리만 무시, 나머지 결과 사용 |
| 전체 검색 실패 | `precedent_text = None`, 판례 없이 답변 |

### 6.2 Circuit Breaker 호환

`search_precedent_multi()`는 내부에서 기존 `search_precedent()`를 호출하므로, 기존 circuit breaker가 그대로 적용된다. 다중 쿼리 시 첫 번째 쿼리에서 circuit이 열리면 나머지 쿼리도 즉시 빈 결과 반환.

---

## 7. Test Plan

### 7.1 벤치마크 시나리오 (15개)

| # | 사용자 질문 (일상어) | 기대 법적 쟁점 | 기대 키워드 |
|---|---------------------|---------------|------------|
| 1 | "사장이 갑자기 나가라고 해요" | 부당해고 | 부당해고, 해고예고수당 |
| 2 | "야근비를 안 줘요" | 연장근로수당 | 연장근로수당, 통상임금 |
| 3 | "퇴직금이 적은 것 같아요" | 퇴직금 산정 | 퇴직금 산정, 평균임금 |
| 4 | "최저시급도 안 되는 것 같은데" | 최저임금 위반 | 최저임금, 산입범위 |
| 5 | "주휴수당 포함 안 시켜줘요" | 주휴수당 | 주휴수당, 유급휴일 |
| 6 | "연차를 못 쓰게 해요" | 연차 사용 방해 | 연차 유급휴가, 사용 촉진 |
| 7 | "일하다 다쳤는데 회사가 모른 척해요" | 산재보상 | 업무상 재해, 산재 인정 |
| 8 | "계약직인데 3년 넘게 일했어요" | 기간제 한도 | 기간제 근로자, 무기계약 |
| 9 | "상여금이 통상임금인가요" | 통상임금 범위 | 통상임금, 정기상여금 |
| 10 | "실업급여 받을 수 있나요" | 실업급여 수급 | 실업급여, 구직급여 |
| 11 | "임금이 3개월째 안 들어와요" | 임금 체불 | 임금 체불, 금품 청산 |
| 12 | "직장에서 따돌림을 당하고 있어요" | 직장 내 괴롭힘 | 직장 내 괴롭힘, 사용자 조치 |
| 13 | "정년 지나서 다시 계약했는데 퇴직금은?" | 정년 후 재고용 | 퇴직금, 촉탁 |
| 14 | "육아휴직 중인데 급여가 얼마인지" | 육아휴직급여 | 육아휴직급여, 고용보험 |
| 15 | "포괄임금제라서 야근비 안 준다는데" | 포괄임금제 유효성 | 포괄임금제, 연장근로수당, 가산임금 |

### 7.2 검증 방법

1. **Analyzer 키워드 추출 테스트**: 15개 시나리오에 대해 `analyze_intent()` 호출 → `precedent_keywords` 품질 확인
2. **쿼리 확장 단위 테스트**: `build_precedent_queries()` 입력/출력 검증
3. **판례 적중률 비교**: before(현재 `question_summary`) vs after(새 쿼리) → 적중률 비교
4. **latency 비교**: 기존 vs 새 로직의 판례 검색 소요 시간

### 7.3 기존 테스트 영향

- `calculator_batch_test.py` (102건): 영향 없음 — 계산기 로직 변경 없음
- `wage_calculator_cli.py` (32건): 영향 없음

---

## 8. Implementation Order

1. [ ] `app/models/schemas.py` — `precedent_keywords` 필드 추가
2. [ ] `app/templates/prompts.py` — ANALYZE_TOOL 스키마 + ANALYZER_SYSTEM 프롬프트
3. [ ] `app/core/analyzer.py` — `precedent_keywords` 반환 추가
4. [ ] `app/core/precedent_query.py` — 신규 모듈 (매핑 테이블 + build_precedent_queries)
5. [ ] `app/core/legal_api.py` — `search_precedent_multi()` + `fetch_precedent_details()`
6. [ ] `app/core/pipeline.py` — 판례 검색 호출부 교체
7. [ ] 벤치마크 테스트 실행 및 결과 비교

---

## 9. Coding Convention Reference

### 9.1 This Feature's Conventions

| Item | Convention Applied |
|------|-------------------|
| 신규 모듈 | `app/core/precedent_query.py` — snake_case, 기존 `legal_consultation.py` 패턴 |
| 함수 명명 | `build_*`, `search_*_multi`, `fetch_*_details` — 기존 패턴 |
| 매핑 테이블 | `UPPER_SNAKE_CASE` dict — 기존 `TOPIC_SEARCH_CONFIG` 패턴 |
| 로깅 | `logger.info` 검색 쿼리·결과·latency — 기존 패턴 |
| 병렬 처리 | `ThreadPoolExecutor`, `as_completed` — 기존 `legal_api.py` 패턴 |
| 에러 처리 | `try/except` + `logger.warning` + 폴백 — 기존 패턴 |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-15 | Initial draft | Claude + zealnutkim |
