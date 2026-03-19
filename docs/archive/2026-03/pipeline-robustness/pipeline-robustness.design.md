# Pipeline Robustness (파이프라인 견고성 강화) Design Document

> **Summary**: 정보 충돌 해결·특수 근로자 식별·인용 교정 퇴고·시각화 수렴선 — 4개 FR의 상세 설계
>
> **Project**: laborconsult
> **Author**: Claude
> **Date**: 2026-03-19
> **Status**: Draft
> **Plan Reference**: `docs/01-plan/features/pipeline-robustness.plan.md`

---

## 1. FR-02: 특수 근로자 그룹 식별 (Priority: High)

> 구현 순서 1번 — 가장 독립적이고 효과가 명확한 항목

### 1.1 변경 파일 및 위치

| 파일 | 변경 유형 | 변경 위치 |
|------|----------|----------|
| `app/templates/prompts.py` | 수정 | `ANALYZE_TOOL["input_schema"]["properties"]`에 `worker_group` 필드 추가 |
| `app/models/schemas.py` | 수정 | `AnalysisResult`에 `worker_group` 필드 추가 |
| `app/core/analyzer.py` | 수정 | `analyze_intent()` 내 `worker_group` 추출 로직 추가 |
| `app/core/pipeline.py` | 수정 | 컨텍스트 조립 시 `worker_group`별 특수 법령 컨텍스트 주입 |

### 1.2 상세 설계

#### 1.2.1 prompts.py — ANALYZE_TOOL 필드 추가

`ANALYZE_TOOL["input_schema"]["properties"]`에 다음 필드를 추가한다. 위치: 기존 `is_platform_worker` 필드 바로 아래.

```python
"worker_group": {
    "type": "string",
    "enum": ["general", "youth", "foreign", "disabled", "industrial_accident"],
    "description": (
        "근로자 그룹 분류. 질문에서 파악 가능한 경우에만 설정. "
        "youth: 18세 미만 청소년 근로자 ('중학생', '고등학생', '미성년자', '15세', '16세', '17세', '만17세', '청소년' 등). "
        "foreign: 외국인 근로자 ('E-9 비자', '외국인', '이주노동자', '고용허가제' 등). "
        "disabled: 장애인 근로자 ('장애인', '장애 등급', '중증장애' 등). "
        "industrial_accident: 산업재해 관련 질문 ('산재', '업무상 재해', '산업재해', '산재보험' 등). "
        "general: 위 해당 없는 일반 근로자 (기본값). 확실하지 않으면 general."
    ),
},
```

#### 1.2.2 schemas.py — AnalysisResult 필드 추가

```python
class AnalysisResult(BaseModel):
    # ... 기존 필드 ...
    precedent_keywords: list[str] = []
    worker_group: str | None = None          # ← 추가
```

#### 1.2.3 analyzer.py — 추출 로직

`analyze_intent()` 함수 내 `AnalysisResult` 생성 부분에서 `worker_group` 추출:

```python
return AnalysisResult(
    # ... 기존 필드 ...
    precedent_keywords=inp.get("precedent_keywords", []),
    worker_group=inp.get("worker_group"),         # ← 추가
)
```

#### 1.2.4 pipeline.py — 특수 컨텍스트 주입

컨텍스트 조립 단계(현재 `pipeline.py` ~1028행, `# 3. 컨텍스트 구성` 이후)에 `_build_worker_group_context()` 호출 추가:

```python
# pipeline.py 상단에 함수 정의

# ── 특수 근로자 그룹별 법적 컨텍스트 ──────────────────────────────────

_WORKER_GROUP_CONTEXTS: dict[str, str] = {
    "youth": (
        "[특수 적용: 청소년 근로자 (18세 미만)]\n"
        "이 질문은 청소년(18세 미만) 근로자에 관한 것입니다. 반드시 아래 특칙을 우선 적용하세요:\n"
        "- 근로기준법 제64조: 15세 미만 취업 원칙 금지 (취직인허증 예외)\n"
        "- 근로기준법 제66조: 18세 미만 야간근로(22시~06시) 및 휴일근로 원칙 금지 "
        "(본인 동의 + 고용노동부장관 인가 시 예외)\n"
        "- 근로기준법 제67조: 근로시간 상한 1일 7시간, 1주 35시간 "
        "(당사자 합의 시 1일 1시간, 1주 5시간 한도 연장 가능)\n"
        "- 근로기준법 제66조: 도덕·보건상 유해위험 사업장 사용 금지\n"
        "- 근로기준법 제67조: 친권자 또는 후견인의 근로계약 동의 필요\n"
        "- 근로기준법 제68조: 친권자·후견인 또는 고용노동부장관은 "
        "근로계약이 불리하다고 인정하면 해제 가능\n"
        "- 임금은 미성년자 본인에게 직접 지급해야 함 (제68조)\n"
        "⚠️ 일반 성인 기준(1일 8시간, 주 40시간)을 절대 적용하지 마세요."
    ),
    "foreign": (
        "[특수 적용: 외국인 근로자]\n"
        "이 질문은 외국인 근로자에 관한 것입니다. 참고 법령:\n"
        "- 외국인근로자의 고용 등에 관한 법률 (고용허가제)\n"
        "- 근로기준법은 국적과 무관하게 동일 적용 (제6조 균등처우)\n"
        "- 퇴직금·4대보험·최저임금 모두 내국인과 동일 기준 적용\n"
        "- 사업장 변경 제한 (원칙 3회), 체류기간 등 출입국관리법 관련 사항 안내\n"
        "- 불법체류 외국인도 근로기준법상 권리(임금청구 등) 보호됨"
    ),
    "disabled": (
        "[특수 적용: 장애인 근로자]\n"
        "이 질문은 장애인 근로자에 관한 것입니다. 참고:\n"
        "- 장애인고용촉진 및 직업재활법\n"
        "- 최저임금 적용 제외 인가제도 (최저임금법 제7조): "
        "고용노동부장관 인가 시 최저임금 감액 적용 가능\n"
        "- 장애인 의무고용률 (2026년: 민간 3.1%, 공공 3.6%)\n"
        "- 근로기준법은 장애 유무와 무관하게 동일 적용"
    ),
    "industrial_accident": (
        "[특수 적용: 산업재해]\n"
        "이 질문은 산업재해에 관한 것입니다. 참고 법령:\n"
        "- 산업재해보상보험법 (산재보험법)\n"
        "- 업무상 재해 인정 기준: 업무수행성 + 업무기인성\n"
        "- 급여 종류: 요양급여, 휴업급여(평균임금 70%), 장해급여, 유족급여, 상병보상연금\n"
        "- 요양급여 신청: 4일 이상 요양 시 근로복지공단(1588-0075)에 신청\n"
        "- 산재 인정 절차: 요양급여신청서 → 근로복지공단 심사 → 승인/불승인\n"
        "- 불승인 시 심사청구(90일 이내) → 재심사청구(90일 이내) → 행정소송\n"
        "- 산재보험은 근로자 수와 무관하게 1인 이상 사업장 당연가입"
    ),
}


def _build_worker_group_context(worker_group: str | None) -> str | None:
    """특수 근로자 그룹에 해당하는 법적 컨텍스트 반환."""
    if not worker_group or worker_group == "general":
        return None
    return _WORKER_GROUP_CONTEXTS.get(worker_group)
```

**호출 위치**: 컨텍스트 `parts` 리스트에 추가하는 블록 (`pipeline.py` ~1045행 부근):

```python
# 기존: if legal_articles_text: parts.append(...) 이후에 추가
worker_ctx = _build_worker_group_context(
    getattr(analysis, "worker_group", None) if analysis else None
)
if worker_ctx:
    parts.insert(0, worker_ctx)  # 최상단에 배치 → LLM이 가장 먼저 인지
```

### 1.3 폴백 전략

- LLM이 `worker_group`을 추출하지 않은 경우 → `None` → 기존 동작과 100% 동일
- LLM이 잘못 추출한 경우 (예: 성인인데 youth) → 해당 법령이 추가 컨텍스트로 제공되지만, 시스템 프롬프트의 "참고 자료 기반 답변" 원칙에 의해 부정확한 답변 가능성 낮음
- `_WORKER_GROUP_CONTEXTS`에 없는 값 → `None` 반환 → 무해

### 1.4 테스트 시나리오

| 시나리오 | 입력 | 기대 결과 |
|---------|------|----------|
| 청소년 근로 질문 | "고등학생인데 편의점에서 일하는데 야간에도 일해야 한다고 하네요" | `worker_group=youth`, 야간근로 금지 컨텍스트 주입 |
| 산재 질문 | "작업 중 손가락을 다쳤는데 산재 처리는 어떻게 하나요" | `worker_group=industrial_accident`, 산재보험법 컨텍스트 |
| 일반 질문 | "월급 250만원인데 주휴수당 계산해주세요" | `worker_group=None` 또는 `general`, 기존 동작 유지 |

---

## 2. FR-01: 정보 충돌 해결 (Priority: High)

> 구현 순서 2번

### 2.1 변경 파일 및 위치

| 파일 | 변경 유형 | 변경 위치 |
|------|----------|----------|
| `app/core/conflict_resolver.py` | **신규** | 정보 우선순위 규칙 엔진 모듈 |
| `app/core/pipeline.py` | 수정 | 컨텍스트 조립 블록에서 `resolve_conflicts()` 호출 |

### 2.2 상세 설계

#### 2.2.1 conflict_resolver.py (신규 모듈)

```python
"""정보 충돌 해결 모듈 — 소스 유형별 우선순위 규칙

병렬 검색 결과(법제처 법령, Pinecone 판례, NLRC 판정사례, GraphRAG)에서
동일한 법 조항에 대해 상충 정보가 있을 때, 법적 우선순위에 따라 해결한다.

원칙:
  현행 법령 > 대법원 판례 > 하급심 판례 > 행정해석 > 판정사례 > 상담사례

주의:
  - '충돌'은 동일 법 조항에 대해 서로 다른 기준/수치/적용 범위를 제시하는 경우
  - 보완 관계의 정보는 충돌이 아님 (예: 법조문 + 적용 사례)
  - 충돌 감지는 법 조항 참조 패턴 기반 (정규식 매칭)
"""

from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

# ── 소스 유형별 우선순위 (높을수록 우선) ──

SOURCE_PRIORITY: dict[str, int] = {
    "legal_article":     100,   # 법제처 현행 법령 조문
    "supreme_court":      80,   # 대법원 확정 판례
    "high_court":         60,   # 고등법원·지방법원 판례
    "admin_interpret":    50,   # 고용노동부 행정해석
    "nlrc_decision":      40,   # 중앙노동위원회 판정
    "counsel":            20,   # 노무사 상담·Q&A
}

# 법 조항 참조 패턴 (예: "근로기준법 제56조", "최저임금법 제6조")
_LAW_REF_PATTERN = re.compile(
    r"((?:근로기준법|최저임금법|산업재해보상보험법|남녀고용평등법|"
    r"근로자퇴직급여보장법|고용보험법|산업안전보건법|"
    r"파견근로자보호법|기간제법|외국인고용법)"
    r"(?:\s*시행령|\s*시행규칙)?"
    r"\s*제\d+조(?:의\d+)?)"
)


def classify_source_type(hit: dict) -> str:
    """검색 결과의 source_type을 우선순위 키로 매핑."""
    st = hit.get("source_type", "")
    title = hit.get("title", "")

    # 법제처 API 법령 조문
    if st == "legal_article" or "법제처" in title:
        return "legal_article"

    # 판례 분류
    if st == "precedent" or "판례" in title:
        if "대법원" in title or "대법" in title:
            return "supreme_court"
        return "high_court"

    # 행정해석
    if st == "interpretation" or "행정해석" in title or "과-" in title:
        return "admin_interpret"

    # NLRC 판정
    if st == "nlrc" or "노동위원회" in title or "판정" in title:
        return "nlrc_decision"

    # 상담·Q&A
    return "counsel"


def _extract_law_refs(text: str) -> set[str]:
    """텍스트에서 법 조항 참조 추출."""
    return set(_LAW_REF_PATTERN.findall(text))


def annotate_source_priority(
    precedent_text: str | None,
    legal_articles_text: str | None,
    nlrc_text: str | None,
) -> str | None:
    """충돌 가능성이 있는 컨텍스트에 우선순위 주석을 부착.

    동일 법 조항을 참조하는 소스가 여러 개인 경우,
    우선순위가 낮은 소스에 [참고: 하위 출처] 주석을 추가한다.

    Returns:
        conflict_note: LLM에 전달할 충돌 안내 메모. 충돌 없으면 None.
    """
    if not legal_articles_text and not precedent_text:
        return None

    # 각 소스에서 법 조항 참조 추출
    legal_refs = _extract_law_refs(legal_articles_text or "")
    prec_refs = _extract_law_refs(precedent_text or "")
    nlrc_refs = _extract_law_refs(nlrc_text or "")

    # 교집합 = 동일 조항을 다루는 소스들
    overlap_with_prec = legal_refs & prec_refs
    overlap_with_nlrc = legal_refs & nlrc_refs

    if not overlap_with_prec and not overlap_with_nlrc:
        return None

    # 충돌 안내 메모 생성
    conflict_refs = overlap_with_prec | overlap_with_nlrc
    note_lines = [
        "[정보 우선순위 안내]",
        f"다음 법 조항에 대해 복수의 출처가 있습니다: {', '.join(sorted(conflict_refs))}",
        "",
        "적용 우선순위 (반드시 준수):",
        "1. 현행 법조문 (법제처 국가법령정보센터 조회) — 최우선 적용",
        "2. 대법원 판례 — 법조문 해석 기준",
        "3. 행정해석·판정사례 — 참고 자료",
        "",
        "⚠️ 판례나 행정해석이 현행 법조문과 다른 기준을 제시하는 경우, "
        "법령 개정으로 인한 차이일 수 있으므로 현행 법조문을 우선 적용하고 "
        "'과거 판례/해석에서는 다른 기준이 적용되었으나 현행법 기준으로 안내드립니다'로 설명하세요.",
    ]

    logger.info("정보 충돌 감지: %d개 조항 — %s", len(conflict_refs), conflict_refs)
    return "\n".join(note_lines)
```

#### 2.2.2 pipeline.py — 호출 위치

컨텍스트 조립 블록(`# 3. 컨텍스트 구성` 이후)에서 `parts` 리스트에 충돌 메모 삽입:

```python
from app.core.conflict_resolver import annotate_source_priority

# 기존 parts 구성 코드 이후, parts.append(f"질문: {query}") 직전에:
conflict_note = annotate_source_priority(
    precedent_text=precedent_text,
    legal_articles_text=legal_articles_text,
    nlrc_text=nlrc_text,
)
if conflict_note:
    parts.insert(0, conflict_note)  # 최상단 배치
```

### 2.3 설계 원칙

1. **충돌 시에만 개입**: 법 조항 참조가 겹치지 않으면 모든 정보를 그대로 전달
2. **정보 삭제 없음**: 낮은 우선순위 소스를 삭제하지 않고, LLM에 우선순위 안내 메모만 추가
3. **인메모리 연산만**: 정규식 매칭으로 < 1ms. API 호출 없음
4. **Graceful**: `annotate_source_priority()`가 예외 발생 시 → `None` 반환 → 기존 동작 유지

### 2.4 테스트 시나리오

| 시나리오 | 상황 | 기대 결과 |
|---------|------|----------|
| 충돌 없음 | 법령: 제56조, 판례: 제60조 (다른 조항) | `conflict_note=None`, 기존 동작 |
| 법령-판례 충돌 | 법령: 제56조 최신 기준, 판례: 제56조 구 기준 | 우선순위 안내 메모 삽입 |
| 법령-NLRC 충돌 | 법령: 제26조, NLRC: 제26조 다른 해석 | 우선순위 안내 메모 삽입 |

---

## 3. FR-03: 인용 교정 마이크로 퇴고 (Priority: Medium)

> 구현 순서 3번

### 3.1 변경 파일 및 위치

| 파일 | 변경 유형 | 변경 위치 |
|------|----------|----------|
| `app/core/citation_validator.py` | 수정 | `micro_polish()` 함수 추가 |
| `app/core/pipeline.py` | 수정 | 인용 검증 블록에서 환각 3건 이상 시 `micro_polish()` 호출 |

### 3.2 상세 설계

#### 3.2.1 citation_validator.py — micro_polish() 추가

기존 `correct_hallucinated_citations()` 함수 아래에 추가:

```python
MICRO_POLISH_MODEL = "claude-haiku-4-5-20251001"
MICRO_POLISH_TIMEOUT = 2.0  # 초
MICRO_POLISH_THRESHOLD = 3  # 환각 N건 이상 시 발동

MICRO_POLISH_SYSTEM = (
    "당신은 한국어 문장 교정 도우미입니다. "
    "판례 번호가 제거된 문장의 문맥을 자연스럽게 다듬어주세요.\n\n"
    "절대 규칙:\n"
    "1. 사실 정보(법조문, 금액, 날짜, 기준)를 절대 변경하지 마세요.\n"
    "2. 접속사, 연결어, 지시어만 수정하여 문맥을 매끄럽게 하세요.\n"
    "3. 마크다운 형식을 유지하세요.\n"
    "4. 새로운 판례 번호나 출처를 추가하지 마세요.\n"
    "5. 수정된 전체 텍스트만 출력하세요."
)


def micro_polish(
    corrected_text: str,
    hallucinated_count: int,
    anthropic_client,
) -> str | None:
    """환각 교정 후 문맥 자연스러움 보정.

    환각이 MICRO_POLISH_THRESHOLD건 이상이고 교정으로 인해
    문맥이 끊겼을 가능성이 높은 경우에만 발동한다.

    Args:
        corrected_text: 환각 판례 제거 후 텍스트
        hallucinated_count: 제거된 환각 인용 수
        anthropic_client: Anthropic 클라이언트

    Returns:
        퇴고된 텍스트. 실패 또는 불필요 시 None.
    """
    if hallucinated_count < MICRO_POLISH_THRESHOLD:
        return None

    if not anthropic_client:
        return None

    try:
        resp = anthropic_client.messages.create(
            model=MICRO_POLISH_MODEL,
            max_tokens=3000,
            temperature=0,
            system=MICRO_POLISH_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f"{hallucinated_count}개의 판례 번호가 제거되어 "
                    "문맥이 어색할 수 있는 텍스트입니다. "
                    "접속사와 연결어만 수정하여 자연스럽게 다듬어주세요.\n\n"
                    f"{corrected_text}"
                ),
            }],
            timeout=MICRO_POLISH_TIMEOUT,
        )
        polished = resp.content[0].text.strip()
        if polished and len(polished) > len(corrected_text) * 0.7:
            logger.info("마이크로 퇴고 완료: %d건 환각 교정 후 문맥 보정", hallucinated_count)
            return polished
        logger.warning("마이크로 퇴고 결과 길이 이상 — 원본 유지")
        return None

    except Exception as e:
        logger.warning("마이크로 퇴고 실패 (정규식 교정 결과 유지): %s", e)
        return None
```

#### 3.2.2 pipeline.py — 호출 위치 변경

기존 인용 검증 블록(`pipeline.py` ~1210행)에서 `correct_hallucinated_citations()` 호출 후 `micro_polish()` 추가:

```python
# 기존 import에 추가
from app.core.citation_validator import (
    # ... 기존 ...
    micro_polish,         # ← 추가
)

# 기존 인용 검증 블록 수정 (pipeline.py ~1216행):
if citation_check["hallucinated"]:
    # ... 기존 로깅 ...

    corrected = correct_hallucinated_citations(
        response_text=full_text,
        hallucinated=citation_check["hallucinated"],
        gemini_api_key=config.gemini_api_key,
        openai_client=config.openai_client,
    )
    if corrected:
        # ── 마이크로 퇴고: 환각 3건+ 시 문맥 보정 ──
        polished = micro_polish(
            corrected_text=corrected,
            hallucinated_count=len(citation_check["hallucinated"]),
            anthropic_client=config.claude_client,
        )
        full_text = polished or corrected
        yield {"type": "replace", "text": full_text}
        logger.info("환각 판례 교정 완료 — replace 이벤트 전송")
```

### 3.3 비용 분석

| 조건 | Haiku 호출 | 예상 토큰 | 비용/건 |
|------|-----------|----------|--------|
| 환각 0~2건 | 호출 안 함 | 0 | $0 |
| 환각 3건+ | 1회 | ~4K (입력 3K + 출력 1K) | ~$0.004 |

예상 발동 비율: 전체 질문의 5% 미만 → 일 100건 기준 월 ~$0.6

### 3.4 폴백 전략

1. `micro_polish()` → `None` 반환 → `corrected` (기존 정규식 교정) 사용
2. Haiku 타임아웃 (2초) → 기존 교정 결과 유지
3. 퇴고 결과가 원본의 70% 미만 길이 → 이상 감지 → 원본 유지

---

## 4. FR-04: 시각화 수렴 흐름선 (Priority: Medium)

> 구현 순서 4번

### 4.1 변경 파일

| 파일 | 변경 유형 |
|------|----------|
| `Downloads/pipeline-visualization.html` | 수정 — CSS + SVG 추가 |

### 4.2 상세 설계

#### 4.2.1 4단계→5단계 수렴 시각화

3단계(분기)는 현재 `branch-grid`로 4열 분기를 보여준다. 이와 구별되게, 4단계(병렬 수집)→5단계(컨텍스트 조립) 사이에 **수렴(Converge) 커넥터**를 추가한다.

```html
<!-- 4단계 parallel-grid 직후, 5단계 직전에 삽입 -->
<div class="converge-connector">
  <svg class="converge-svg" viewBox="0 0 800 80" preserveAspectRatio="xMidYMid meet">
    <!-- 왼쪽 라인 -->
    <path d="M100,0 Q100,40 400,70" stroke="var(--accent)" stroke-width="1.5"
          fill="none" opacity="0.3" />
    <!-- 중앙-왼쪽 라인 -->
    <path d="M280,0 Q280,30 400,70" stroke="var(--accent)" stroke-width="1.5"
          fill="none" opacity="0.3" />
    <!-- 중앙-오른쪽 라인 -->
    <path d="M520,0 Q520,30 400,70" stroke="var(--accent)" stroke-width="1.5"
          fill="none" opacity="0.3" />
    <!-- 오른쪽 라인 -->
    <path d="M700,0 Q700,40 400,70" stroke="var(--accent)" stroke-width="1.5"
          fill="none" opacity="0.3" />
    <!-- 수렴점 -->
    <circle cx="400" cy="70" r="5" fill="var(--accent)" opacity="0.6" />
    <!-- 흐름 입자 애니메이션 -->
    <circle r="3" fill="var(--accent)">
      <animateMotion dur="2s" repeatCount="indefinite"
        path="M100,0 Q100,40 400,70" />
    </circle>
    <circle r="3" fill="var(--accent)">
      <animateMotion dur="2s" repeatCount="indefinite" begin="0.5s"
        path="M520,0 Q520,30 400,70" />
    </circle>
    <circle r="3" fill="var(--accent)">
      <animateMotion dur="2s" repeatCount="indefinite" begin="1s"
        path="M700,0 Q700,40 400,70" />
    </circle>
  </svg>
  <div class="converge-label">컨텍스트 수렴</div>
</div>
```

#### 4.2.2 CSS 추가

```css
.converge-connector {
  text-align: center;
  padding: 8px 0 4px;
  position: relative;
}
.converge-svg {
  width: 100%;
  max-width: 800px;
  height: 80px;
}
.converge-label {
  font-size: 0.8rem;
  color: var(--text-secondary);
  font-weight: 500;
  margin-top: 4px;
}

/* 모바일: SVG 숨기고 단순 세로 커넥터 표시 */
@media (max-width: 768px) {
  .converge-svg { display: none; }
  .converge-connector::before {
    content: '';
    display: block;
    width: 2px; height: 32px;
    background: linear-gradient(to bottom, var(--connector), var(--accent));
    margin: 0 auto;
  }
}
```

#### 4.2.3 3단계 분기와의 시각적 구별

| 요소 | 3단계 (분기) | 4단계→5단계 (수렴) |
|------|-------------|-------------------|
| 방향 | 1→N (발산) | N→1 (수렴) |
| 커넥터 | `branch-indicator` (수평 점선) | `converge-connector` (SVG 곡선) |
| 애니메이션 | 없음 (정적) | 입자가 수렴점으로 이동 |
| 레이블 | "4가지 경로로 분기" | "컨텍스트 수렴" |

---

## 5. 구현 순서 및 의존성 그래프

```
FR-02 (특수 근로자)  ──┐
                       │
FR-01 (정보 충돌)    ──┼── 독립 (병렬 구현 가능)
                       │
FR-03 (마이크로 퇴고) ──┤
                       │
FR-04 (시각화 수렴)  ──┘
```

모든 FR은 서로 독립적이며, 병렬 구현이 가능하다. 권장 순서:

1. **FR-02** — 가장 직접적인 사용자 가치 (청소년 보호)
2. **FR-01** — 답변 정확도의 근본적 개선
3. **FR-03** — 답변 품질 Polish (비용 대비 효과 검증 필요)
4. **FR-04** — 시각화 개선 (기능 영향 없음)

---

## 6. 변경 영향도 요약

| 파일 | 변경량 | FR |
|------|--------|-----|
| `app/templates/prompts.py` | +12줄 | FR-02 |
| `app/models/schemas.py` | +1줄 | FR-02 |
| `app/core/analyzer.py` | +2줄 | FR-02 |
| `app/core/pipeline.py` | +25줄 | FR-01, FR-02, FR-03 |
| `app/core/conflict_resolver.py` | **신규 ~90줄** | FR-01 |
| `app/core/citation_validator.py` | +50줄 | FR-03 |
| `Downloads/pipeline-visualization.html` | +60줄 (CSS/SVG) | FR-04 |

**총계**: 기존 파일 5개 수정 + 신규 1개. 코드 변경 ~240줄.

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-19 | Initial design — 4 FRs detailed | Claude |
