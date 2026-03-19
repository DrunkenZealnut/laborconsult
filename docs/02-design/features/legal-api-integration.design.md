# Design: 법제처 국가법령정보 API 연동

> Plan 참조: `docs/01-plan/features/legal-api-integration.plan.md`

---

## 1. 모듈 설계

### 1.1 신규 파일: `app/core/legal_api.py`

법제처 DRF API 클라이언트. XML 파싱, 인메모리 캐시, 조문 조회를 담당한다.

#### 1.1.1 상수 및 설정

```python
"""법제처 국가법령정보 Open API 클라이언트"""

from __future__ import annotations

import logging
import os
import re
import time
from xml.etree import ElementTree as ET

import requests

logger = logging.getLogger(__name__)

# ── API 설정 ──────────────────────────────────────────────────────────────────
LAW_SEARCH_URL = "http://www.law.go.kr/DRF/lawSearch.do"
LAW_SERVICE_URL = "http://www.law.go.kr/DRF/lawService.do"

LAW_API_TIMEOUT = int(os.getenv("LAW_API_TIMEOUT", "5"))
LAW_CACHE_TTL = int(os.getenv("LAW_API_CACHE_TTL", "86400"))
```

#### 1.1.2 법령 MST 매핑 테이블

초기 기동 시 고정값 사용, API 동적 조회로 폴백:

```python
# ── 노동법 관련 법령 MST 매핑 ─────────────────────────────────────────────────
# key: 법령명 (사용자 입력에서 추출된 형태)
# value: 법령 MST(일련번호) — 최초 조회 후 캐시
# 초기값 None → 첫 호출 시 lawSearch.do로 동적 조회 후 저장

_LAW_NAME_ALIASES: dict[str, str] = {
    # 약칭 → 정식명칭 매핑
    "근기법": "근로기준법",
    "최임법": "최저임금법",
    "고보법": "고용보험법",
    "산재법": "산업재해보상보험법",
    "남녀고용평등법": "남녀고용평등과 일·가정 양립 지원에 관한 법률",
    "퇴직급여법": "근로자퇴직급여 보장법",
}

_MST_CACHE: dict[str, int | None] = {}
```

#### 1.1.3 인메모리 캐시

```python
# ── 조문 캐시 ─────────────────────────────────────────────────────────────────
# key: "근로기준법_56" → value: (timestamp, article_text)
_ARTICLE_CACHE: dict[str, tuple[float, str]] = {}


def _cache_get(key: str) -> str | None:
    """캐시에서 조문 텍스트 조회. TTL 초과 시 None 반환."""
    entry = _ARTICLE_CACHE.get(key)
    if entry is None:
        return None
    ts, text = entry
    if time.time() - ts > LAW_CACHE_TTL:
        del _ARTICLE_CACHE[key]
        return None
    return text


def _cache_set(key: str, text: str) -> None:
    """조문 텍스트를 캐시에 저장."""
    _ARTICLE_CACHE[key] = (time.time(), text)
```

#### 1.1.4 법령 검색 (MST 획득)

```python
def _resolve_law_name(name: str) -> str:
    """약칭을 정식명칭으로 변환."""
    return _LAW_NAME_ALIASES.get(name, name)


def _lookup_mst(law_name: str, api_key: str) -> int | None:
    """법령명으로 MST(일련번호)를 조회. 결과를 _MST_CACHE에 저장."""
    canonical = _resolve_law_name(law_name)

    if canonical in _MST_CACHE:
        return _MST_CACHE[canonical]

    try:
        resp = requests.get(LAW_SEARCH_URL, params={
            "OC": api_key,
            "target": "law",
            "type": "XML",
            "query": canonical,
            "display": "5",
        }, timeout=LAW_API_TIMEOUT)
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        # <law> 요소 중 법령명이 정확히 일치하는 것 찾기
        for law_el in root.iter("law"):
            name_el = law_el.find("법령명한글")
            if name_el is None:
                name_el = law_el.find("법령명_한글")
            if name_el is not None and canonical in name_el.text:
                mst_el = law_el.find("법령일련번호")
                if mst_el is not None and mst_el.text:
                    mst = int(mst_el.text)
                    _MST_CACHE[canonical] = mst
                    return mst
    except Exception as e:
        logger.warning("법령 MST 조회 실패 (%s): %s", law_name, e)

    _MST_CACHE[canonical] = None
    return None
```

#### 1.1.5 조문 조회 핵심 함수

```python
def fetch_article(law_name: str, article_no: int, api_key: str,
                  paragraph: int | None = None) -> str | None:
    """
    특정 법률의 조문 텍스트를 조회.

    Args:
        law_name: 법령명 (예: "근로기준법")
        article_no: 조 번호 (예: 56)
        api_key: 법제처 API 키 (OC 파라미터)
        paragraph: 항 번호 (선택, 예: 2)

    Returns:
        조문 텍스트 문자열 또는 None (실패 시)
    """
    cache_key = f"{law_name}_{article_no}"
    if paragraph:
        cache_key += f"_{paragraph}"

    # 캐시 확인
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # MST 조회
    mst = _lookup_mst(law_name, api_key)
    if mst is None:
        return None

    # 조문 API 호출
    try:
        resp = requests.get(LAW_SERVICE_URL, params={
            "OC": api_key,
            "target": "law",
            "MST": str(mst),
            "type": "XML",
        }, timeout=LAW_API_TIMEOUT)
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        article_text = _extract_article(root, article_no, paragraph)
        if article_text:
            _cache_set(cache_key, article_text)
            return article_text

    except Exception as e:
        logger.warning("조문 조회 실패 (%s 제%d조): %s", law_name, article_no, e)

    return None


def _extract_article(root: ET.Element, article_no: int,
                     paragraph: int | None = None) -> str | None:
    """XML 응답에서 특정 조문 텍스트를 추출."""
    # 법제처 XML 구조: <조문단위> 안에 <조문번호>, <조문내용>, <항> 등
    for jo in root.iter("조문단위"):
        jo_no_el = jo.find("조문번호")
        if jo_no_el is None or not jo_no_el.text:
            continue
        # "제56조" → 56 추출
        match = re.search(r"(\d+)", jo_no_el.text)
        if match and int(match.group(1)) == article_no:
            if paragraph is not None:
                # 특정 항만 추출
                for hang in jo.iter("항"):
                    hang_no_el = hang.find("항번호")
                    if hang_no_el is not None and hang_no_el.text:
                        h_match = re.search(r"(\d+)", hang_no_el.text)
                        if h_match and int(h_match.group(1)) == paragraph:
                            return _format_article_text(jo_no_el.text, hang)
                return None
            else:
                # 조문 전체
                return _format_full_article(jo)
    return None


def _format_full_article(jo_el: ET.Element) -> str:
    """조문 전체를 읽기 좋은 텍스트로 포맷팅."""
    parts = []

    # 조문 제목
    title_el = jo_el.find("조문제목")
    jo_no_el = jo_el.find("조문번호")
    if jo_no_el is not None and jo_no_el.text:
        header = jo_no_el.text.strip()
        if title_el is not None and title_el.text:
            header += f"({title_el.text.strip()})"
        parts.append(header)

    # 조문 내용
    content_el = jo_el.find("조문내용")
    if content_el is not None and content_el.text:
        parts.append(content_el.text.strip())

    # 항 목록
    for hang in jo_el.iter("항"):
        hang_content = hang.find("항내용")
        if hang_content is not None and hang_content.text:
            parts.append(hang_content.text.strip())
        # 호 목록
        for ho in hang.iter("호"):
            ho_content = ho.find("호내용")
            if ho_content is not None and ho_content.text:
                parts.append(f"  {ho_content.text.strip()}")

    return "\n".join(parts) if parts else None


def _format_article_text(jo_no_text: str, hang_el: ET.Element) -> str:
    """특정 항을 포맷팅."""
    parts = [jo_no_text.strip()]
    hang_content = hang_el.find("항내용")
    if hang_content is not None and hang_content.text:
        parts.append(hang_content.text.strip())
    for ho in hang_el.iter("호"):
        ho_content = ho.find("호내용")
        if ho_content is not None and ho_content.text:
            parts.append(f"  {ho_content.text.strip()}")
    return "\n".join(parts)
```

#### 1.1.6 `relevant_laws` 파싱 함수

```python
# ── 법조문 참조 파싱 ──────────────────────────────────────────────────────────

_ARTICLE_PATTERN = re.compile(
    r"([\w·]+(?:법|령|규칙))\s*제?(\d+)조(?:의(\d+))?(?:\s*제?(\d+)항)?"
)


def parse_law_reference(ref: str) -> dict | None:
    """
    법조문 참조 문자열을 파싱.

    Examples:
        "근로기준법 제56조"      → {"law": "근로기준법", "article": 56}
        "최저임금법 제6조 제2항"  → {"law": "최저임금법", "article": 6, "paragraph": 2}
        "근로기준법 제51조의2"    → {"law": "근로기준법", "article": 51, "sub": 2}
        "대법원 2023다302838"     → None (판례는 Phase 2)
    """
    m = _ARTICLE_PATTERN.search(ref)
    if not m:
        return None
    result = {
        "law": m.group(1),
        "article": int(m.group(2)),
    }
    if m.group(3):
        result["sub"] = int(m.group(3))
    if m.group(4):
        result["paragraph"] = int(m.group(4))
    return result
```

#### 1.1.7 통합 조회 함수 (pipeline.py에서 호출)

```python
def fetch_relevant_articles(
    relevant_laws: list[str],
    api_key: str | None,
) -> str | None:
    """
    relevant_laws 목록에서 법조문을 조회하여 통합 텍스트 반환.

    pipeline.py의 process_question()에서 호출.
    API 키가 없거나 모든 조회 실패 시 None 반환 → 기존 흐름 유지.
    """
    if not api_key or not relevant_laws:
        return None

    articles = []
    for ref in relevant_laws[:5]:  # 최대 5개 법조문만 조회
        parsed = parse_law_reference(ref)
        if parsed is None:
            continue

        text = fetch_article(
            law_name=parsed["law"],
            article_no=parsed["article"],
            api_key=api_key,
            paragraph=parsed.get("paragraph"),
        )
        if text:
            law_display = _resolve_law_name(parsed["law"])
            articles.append(f"[{law_display} 제{parsed['article']}조]\n{text}")

    if not articles:
        return None

    return "\n\n".join(articles)
```

---

### 1.2 수정 파일: `app/config.py`

#### 변경 내용

```python
# 추가할 필드 (AppConfig dataclass)
law_api_key: str | None = None

# from_env()에 추가
law_api_key = os.getenv("LAW_API_KEY")
```

#### 변경 위치 상세

| 위치 | 변경 |
|------|------|
| Line 27 (supabase 필드 아래) | `law_api_key: str | None = None` 추가 |
| Line 45 (supabase 초기화 아래) | `law_api_key = os.getenv("LAW_API_KEY")` 추가 |
| Line 46-52 (cls 리턴) | `law_api_key=law_api_key` 인자 추가 |

---

### 1.3 수정 파일: `app/core/pipeline.py`

#### 1.3.1 import 추가

```python
# 기존 import 아래 (Line 21 근처)
from app.core.legal_api import fetch_relevant_articles
```

#### 1.3.2 법령 API 조회 삽입 위치

`process_question()` 함수 내, 의도 분석 완료 후 ~ RAG 검색 전:

```
Line 570 (analysis 완료) 이후
Line 603 (RAG 검색) 이전
```

#### 1.3.3 구체적 코드 삽입

```python
    # ── [신규] 법령 API 조문 조회 ──────────────────────────────────────────────
    legal_articles_text = None
    if analysis and analysis.relevant_laws and config.law_api_key:
        try:
            legal_articles_text = fetch_relevant_articles(
                analysis.relevant_laws, config.law_api_key
            )
            if legal_articles_text:
                logger.info("법령 API 조문 %d건 조회 완료", len(analysis.relevant_laws))
        except Exception as e:
            logger.warning("법령 API 조회 실패 (무시하고 진행): %s", e)
```

#### 1.3.4 컨텍스트 주입 위치

`parts` 리스트 구성 시 (Line 615-621 영역), `calc_result` 다음에 삽입:

```python
    # 기존: parts = [f"참고 문서:\n\n{context}"]
    # 기존: if calc_result: parts.append(...)
    # 기존: if assessment_result: parts.append(...)

    # [신규] 현행 법조문 삽입
    if legal_articles_text:
        parts.append(f"현행 법조문 (법제처 국가법령정보센터 조회):\n\n{legal_articles_text}")
```

#### 1.3.5 SYSTEM_PROMPT 추가 규칙

Line 512 (마지막 규칙 뒤)에 규칙 14 추가:

```python
14. **현행 법조문이 포함된 경우**:
    - 법제처 국가법령정보센터에서 조회한 최신 법조문이 제공됩니다.
    - 이 법조문을 우선 참조하여 답변하세요. RAG 참고 문서의 법조문과 내용이 다를 경우, 현행 법조문이 최신입니다.
    - 법조문 출처를 "(법제처 국가법령정보센터 조회)" 로 명시하세요.
```

---

### 1.4 수정 파일: `.env.example`

이미 Plan 단계에서 추가 완료:
```bash
# 법제처 국가법령정보 Open API - 실시간 법조문 조회용 (선택)
LAW_API_KEY=your_law_api_key_here
```

---

## 2. 데이터 흐름도

```
process_question(query, session, config)
│
├─ 1. analyze_intent(query) ──────────────────────────────────────┐
│      returns AnalysisResult {                                    │
│        relevant_laws: ["근로기준법 제56조", "최저임금법 제6조"]   │
│        calculation_types: ["overtime"]                            │
│        ...                                                       │
│      }                                                           │
│                                                                  │
├─ 2. [신규] fetch_relevant_articles(relevant_laws, api_key) ─────┤
│      ├─ parse_law_reference("근로기준법 제56조")                 │
│      │   → {"law": "근로기준법", "article": 56}                  │
│      ├─ _cache_get("근로기준법_56") → HIT? → return              │
│      ├─ _lookup_mst("근로기준법", api_key) → MST                 │
│      │   ├─ _MST_CACHE HIT? → return MST                        │
│      │   └─ GET lawSearch.do?query=근로기준법 → XML → MST        │
│      ├─ GET lawService.do?MST=xxx → XML                          │
│      ├─ _extract_article(xml, 56) → 조문 텍스트                  │
│      └─ _cache_set("근로기준법_56", text)                        │
│      returns: "[근로기준법 제56조]\n제56조(연장·야간..."           │
│                                                                  │
├─ 3. _run_calculator(params) ── (기존)                            │
│                                                                  │
├─ 4. _search(query, config) ── RAG 검색 (기존)                   │
│                                                                  │
├─ 5. parts 조립:                                                  │
│      [참고 문서] + [현행 법조문] + [계산기 결과] + [질문]        │
│                                                                  │
└─ 6. _stream_answer(messages, SYSTEM_PROMPT, config)              │
       LLM이 현행 법조문을 우선 참조하여 답변 생성                 │
```

---

## 3. 에러 처리 매트릭스

| 실패 지점 | 원인 | 처리 | 사용자 영향 |
|-----------|------|------|------------|
| `config.law_api_key` 없음 | 미설정 | 법령 API 스킵, 기존 흐름 | 없음 |
| `analyze_intent` 실패 | LLM 오류 | `relevant_laws=[]` → API 스킵 | 없음 |
| `parse_law_reference` 실패 | 파싱 불가 패턴 | 해당 항목 건너뜀 | 없음 |
| `_lookup_mst` 타임아웃 | API 느림 | 5초 타임아웃, None 반환 | 없음 |
| `_lookup_mst` 미발견 | 법령명 불일치 | `_MST_CACHE[name]=None`, 재시도 안 함 | 없음 |
| `fetch_article` 타임아웃 | API 느림 | 5초 타임아웃, None 반환 | 없음 |
| `_extract_article` XML 파싱 오류 | 예상외 구조 | 로깅 후 None | 없음 |
| 전체 `fetch_relevant_articles` 예외 | 알 수 없는 오류 | try/except, 기존 흐름 유지 | 없음 |

**핵심 원칙**: 법령 API는 보조 소스. 실패 시 **항상** 기존 RAG+LLM 방식으로 동작.

---

## 4. 캐시 설계

### 4.1 2단계 캐시

| 캐시 | Key | Value | TTL | 용도 |
|------|-----|-------|-----|------|
| `_MST_CACHE` | 법령명 (정식) | MST 번호 or None | 영구 (세션 내) | 법령 검색 API 호출 최소화 |
| `_ARTICLE_CACHE` | `{법령명}_{조번호}` | `(timestamp, text)` | 24시간 | 조문 조회 API 호출 최소화 |

### 4.2 Vercel 서버리스 환경 고려

- 콜드스타트 시 모든 캐시 초기화됨
- 워밍 상태에서는 동일 함수 인스턴스 내 캐시 유지 (≈5~15분)
- 법령은 자주 변경되지 않으므로 콜드스타트마다 재조회해도 무방
- 향후 Supabase `law_article_cache` 테이블로 영구 캐시 확장 가능

---

## 5. 성능 예산

| 항목 | 예산 | 비고 |
|------|------|------|
| 법령 MST 조회 | ≤2초 | lawSearch.do 1회 |
| 조문 텍스트 조회 | ≤3초 | lawService.do 1회 |
| 캐시 히트 시 | <1ms | 딕셔너리 룩업 |
| 전체 법령 API 오버헤드 | ≤5초 | 타임아웃 한도 |
| 컨텍스트 토큰 증가 | +200~500 토큰 | 조문 1~3개 기준 |

Vercel 60초 maxDuration 내 충분히 수용 가능 (기존 LLM 스트리밍이 대부분 시간 소비).

---

## 6. 구현 순서

```
Step 1: app/config.py
        └─ law_api_key 필드 + from_env() 수정

Step 2: app/core/legal_api.py (신규)
        ├─ 상수 및 캐시 구조
        ├─ _resolve_law_name(), _lookup_mst()
        ├─ fetch_article(), _extract_article()
        ├─ parse_law_reference()
        └─ fetch_relevant_articles()

Step 3: app/core/pipeline.py
        ├─ import 추가
        ├─ SYSTEM_PROMPT 규칙 14 추가
        ├─ process_question(): 법령 API 조회 코드 삽입
        └─ parts 리스트에 법조문 블록 추가

Step 4: 통합 테스트
        ├─ API 키 있을 때: 법조문 포함 답변 확인
        ├─ API 키 없을 때: 기존 방식 정상 동작 확인
        └─ 캐시 히트 확인
```

---

## 7. 테스트 케이스

| # | 시나리오 | 입력 | 기대 동작 | 검증 방법 |
|---|---------|------|----------|----------|
| 1 | 직접 법조문 질문 | "근로기준법 제56조가 뭔가요?" | `relevant_laws=["근로기준법 제56조"]` → API 조회 → 조문 포함 답변 | 답변에 "제56조" 원문 존재 |
| 2 | 간접 법조문 (계산기 연동) | "월급 250만원, 주5일, 연장근로 10시간, 수당은?" | 분석 → `relevant_laws=["근로기준법 제56조"]` → 조문 + 계산 결과 | 법조문 + 계산 수치 모두 존재 |
| 3 | 캐시 히트 | 동일 법조문 2회 연속 질문 | 2번째 호출 시 API 미호출, 캐시에서 반환 | 로그에 API 호출 없음 |
| 4 | API 키 미설정 | `LAW_API_KEY` 없이 서버 실행 | 법령 API 스킵, 기존 RAG만 사용 | 정상 답변, 법조문 블록 없음 |
| 5 | API 타임아웃 | API 서버 응답 지연 (>5초) | 타임아웃 후 기존 흐름 유지 | 답변 정상 생성, 경고 로그 |
| 6 | 법령명 불일치 | `relevant_laws=["존재하지않는법 제1조"]` | MST 미발견, None 반환 | 답변에 법조문 블록 없음, 에러 없음 |
| 7 | `relevant_laws` 없는 질문 | "안녕하세요" (일반 인사) | 법령 API 호출 안 함 | 기존 흐름 동일 |
| 8 | 복수 법조문 | "연장근로와 최저임금 위반" | 2개 법조문 조회 | 두 조문 모두 parts에 포함 |
| 9 | 약칭 법령명 | `relevant_laws=["근기법 제56조"]` | `_resolve_law_name` → "근로기준법" 변환 → 정상 조회 | 법조문 포함 |
| 10 | 항 단위 조회 | `relevant_laws=["근로기준법 제56조 제2항"]` | paragraph=2로 해당 항만 추출 | 제2항 내용만 포함 |

---

## 8. 파일 변경 요약

| # | 파일 | 변경 유형 | 변경 내용 | 예상 줄 수 |
|---|------|----------|----------|-----------|
| 1 | `app/config.py` | 수정 | `law_api_key` 필드 + `from_env()` | +3줄 |
| 2 | `app/core/legal_api.py` | **신규** | API 클라이언트, XML 파싱, 캐시, 파싱 | ~200줄 |
| 3 | `app/core/pipeline.py` | 수정 | import + SYSTEM_PROMPT 규칙 14 + 법령 조회 + parts 삽입 | +15줄 |
| 4 | `.env.example` | 수정 | (이미 완료) | 0줄 |
