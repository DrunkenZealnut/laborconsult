# Design: 노동상담 법령·판례 답변모듈

> Plan 참조: `docs/01-plan/features/labor-consultation-module.plan.md`

---

## 1. 시스템 아키텍처

### 1.1 전체 흐름 (변경 후)

```
사용자 질문
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ Intent Analysis (analyzer.py)                                   │
│                                                                 │
│ ANALYZE_TOOL 호출 결과:                                          │
│   requires_calculation: bool                                    │
│   is_harassment_question: bool  (harassment_params tool)        │
│   consultation_type: str | null  ← [신규]                       │
│   consultation_topic: str | null ← [신규]                       │
│   relevant_laws: list[str]                                      │
│                                                                 │
│ 라우팅 우선순위:                                                  │
│   1. requires_calculation=true   → 임금계산기 경로 (기존)         │
│   2. is_harassment=true          → 괴롭힘 판정 경로 (기존)        │
│   3. consultation_type 존재      → [신규] 법률상담 경로           │
│   4. 그 외                       → 기존 RAG-only 경로            │
└─────────────────────────────────────────────────────────────────┘
    ↓ (consultation_type 감지 시)
┌─────────────────────────────────────────────────────────────────┐
│ 법률상담 모듈 (legal_consultation.py)  [신규]                     │
│                                                                 │
│ Step 1. 주제 → 검색 대상 네임스페이스 결정                        │
│ Step 2. 멀티 네임스페이스 벡터 검색 (병렬)                        │
│ Step 3. 법조문 API 조회 (legal_api.py 재활용)                    │
│ Step 4. 소스별 포맷팅 + 컨텍스트 조립                             │
└─────────────────────────────────────────────────────────────────┘
    ↓
pipeline.py → LLM 답변 (법률상담 전용 System Prompt)
```

### 1.2 기존 경로와의 관계

| 경로 | 조건 | 변경 |
|------|------|------|
| 임금계산기 | `requires_calculation=true` | 변경 없음 |
| 괴롭힘 판정 | `is_harassment_question=true` | 변경 없음 |
| **법률상담** | `consultation_type is not None` | **신규** |
| RAG-only | 위 모두 아닐 때 | 변경 없음 (fallback) |

---

## 2. 데이터 계층 설계

### 2.1 Pinecone 네임스페이스 구조

```
인덱스: laborconsult-bestqna (기존, dim=1536, cosine)
│
├── namespace="" (default)
│   └── BEST Q&A 274건 (~1,722 벡터)  ← 기존 유지
│
├── namespace="precedent"        [신규]
│   └── 법원 판례 353건 (~2,100 벡터)
│       metadata: source_type, category, title, url, date, case_no
│
├── namespace="interpretation"   [신규]
│   └── 행정해석 1,441건 (~5,800 벡터)
│       metadata: source_type, category, title, url, date, doc_no
│
├── namespace="regulation"       [신규]
│   └── 훈령/예규/고시/지침 161건 (~800 벡터)
│       metadata: source_type, category, title, url, date, doc_type
│
└── namespace="legal_cases"      [신규]
    └── 법률 상담사례 114건 (~500 벡터)
        metadata: source_type, category, title, url
```

### 2.2 메타데이터 파싱 규칙

각 마크다운 파일의 상단 테이블에서 메타데이터 추출:

```python
# 공통 파서 — 파일 상단 메타 테이블 파싱
def parse_md_metadata(md_content: str) -> dict:
    """
    | 항목 | 내용 |
    | 분류 | 근로기준 |
    | 작성일 | 2024.03.17 |
    | 원문 | https://www.nodong.kr/case/2363346 |
    → {"분류": "근로기준", "작성일": "2024.03.17", "원문": "https://..."}
    """
```

**소스별 메타데이터 매핑**:

| 소스 | 파일명에서 추출 | 테이블에서 추출 | 벡터 metadata |
|------|----------------|----------------|---------------|
| 판례 | `{id}_{title}.md` → post_id | 분류, 작성일, 원문 | source_type="precedent", category, title, url, date |
| 행정해석 | `{id}_{title}.md` → post_id | 분류, 작성일, 원문 | source_type="interpretation", category, title, url, date |
| 훈령/예규 | `{id}_{title}.md` → post_id | 분류, 작성일, 원문 | source_type="regulation", category, title, url, date |
| 상담사례 | `case_{no}_{title}.md` → case_no | (파일 내 본문) | source_type="legal_case", category, title |

### 2.3 청킹 전략

기존 `pinecone_upload.py`의 `chunk_post()` 로직을 재활용:

```python
# 동일한 청킹 파라미터
CHUNK_MAX = 700      # 최대 글자 수
CHUNK_OVERLAP = 80   # 오버랩
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536

# 임베딩 텍스트 포맷 (검색 품질 향상)
embed_text = f"제목: {title}\n분류: {category}\n섹션: {section_name}\n\n{chunk_text}"
```

**소스별 본문 추출 규칙**:

| 소스 | 본문 시작 | 제외 영역 |
|------|----------|----------|
| 판례 | `---` 이후 전체 | 상단 메타 테이블 |
| 행정해석 | `---` 이후 전체 (질의 + 회시답변) | 상단 메타 테이블 |
| 훈령/예규 | `---` 이후 전체 | 상단 메타 테이블 |
| 상담사례 | 전체 (`---` 없음) | 없음 |

---

## 3. 모듈 상세 설계

### 3.1 `pinecone_upload_legal.py` (신규 스크립트)

```python
"""법률 데이터 벡터 업로드 — 판례·행정해석·훈령/예규·상담사례"""

# ── 소스 정의 ──
LEGAL_SOURCES = [
    {
        "directory": "output_법원 노동판례",
        "namespace": "precedent",
        "source_type": "precedent",
        "label": "법원 판례",
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
        "label": "훈령/예규/고시",
    },
    {
        "directory": "output_legal_cases",
        "namespace": "legal_cases",
        "source_type": "legal_case",
        "label": "법률 상담사례",
    },
]

# ── 핵심 함수 ──
def parse_md_metadata(md_content: str) -> dict:
    """마크다운 상단 메타 테이블 파싱"""

def extract_legal_body(md_content: str) -> str:
    """메타 테이블 제거 후 본문 추출 (기존 extract_body 변형)"""

def chunk_legal_doc(post_id, title, category, body) -> list[dict]:
    """기존 chunk_post() 재활용, 카테고리 포함 embed_text 생성"""

def build_legal_vector(chunk, embedding, meta) -> dict:
    """Pinecone upsert용 벡터 — namespace 지정"""

def upload_source(source_config, index, openai_client) -> dict:
    """단일 소스 디렉토리 전체 업로드 → 결과 통계 반환"""

def main():
    """CLI: --source (선택 업로드) / --reset (네임스페이스 초기화) / --dry-run"""
```

**CLI 인터페이스**:
```bash
python3 pinecone_upload_legal.py                    # 전체 업로드
python3 pinecone_upload_legal.py --source precedent  # 판례만
python3 pinecone_upload_legal.py --reset             # 네임스페이스 초기화 후 재업로드
python3 pinecone_upload_legal.py --dry-run           # 청킹만 (업로드 안 함)
```

### 3.2 `app/models/schemas.py` (수정)

```python
class AnalysisResult(BaseModel):
    requires_calculation: bool = False
    calculation_types: list[str] = []
    extracted_info: dict = {}
    relevant_laws: list[str] = []
    missing_info: list[str] = []
    question_summary: str = ""
    # ── 신규 필드 ──
    consultation_type: str | None = None    # "law_interpretation" | "precedent_search" | "procedure_guide" | "rights_check" | "system_explanation" | None
    consultation_topic: str | None = None   # "해고·징계" | "임금·통상임금" | ... | None
```

**consultation_type 값 정의**:

| 값 | 설명 | 예시 질문 |
|----|------|----------|
| `law_interpretation` | 법조문 해석 질문 | "5인 미만에서 해고예고가 필요한가요?" |
| `precedent_search` | 판례 조회 요청 | "통상임금 관련 판례 알려주세요" |
| `procedure_guide` | 절차·신청 방법 질문 | "부당해고 구제신청 절차가 어떻게 되나요?" |
| `rights_check` | 권리·자격 확인 질문 | "수습기간에도 퇴직금 받을 수 있나요?" |
| `system_explanation` | 제도 설명 요청 | "탄력근로시간제가 뭔가요?" |
| `None` | 비법률 상담 또는 계산 질문 | (기존 경로) |

**consultation_topic 값 정의**:

| 값 | 매칭 키워드 |
|----|-----------|
| `해고·징계` | 해고, 징계, 부당해고, 해고예고, 감봉, 정리해고, 권고사직 |
| `임금·통상임금` | 통상임금, 평균임금, 임금체불, 임금지급, 상여금, 수당 |
| `근로시간·휴일` | 근로시간, 연장근로, 야간근로, 휴일, 주휴, 휴게시간, 휴업 |
| `퇴직·퇴직금` | 퇴직금, 퇴직연금, 퇴직, 중간정산, 퇴직급여 |
| `연차휴가` | 연차, 연차휴가, 연차수당, 사용촉진, 대체사용 |
| `산재보상` | 산재, 산업재해, 요양급여, 휴업급여, 장해급여 |
| `비정규직` | 비정규직, 기간제, 파견, 계약직, 무기계약 |
| `노동조합` | 노조, 노동조합, 단체교섭, 부당노동행위, 파업 |
| `직장내괴롭힘` | 괴롭힘, 갑질, 폭언, 따돌림, 직장 내 괴롭힘 |
| `근로계약` | 근로계약, 취업규칙, 근로조건, 수습, 계약서 |
| `고용보험` | 실업급여, 구직급여, 고용보험, 육아휴직, 출산휴가 |
| `기타` | (위에 해당하지 않는 노동 상담) |

### 3.3 `app/templates/prompts.py` (수정)

#### 3.3.1 ANALYZE_TOOL 확장

```python
ANALYZE_TOOL["input_schema"]["properties"]["consultation_type"] = {
    "type": "string",
    "enum": [
        "law_interpretation",
        "precedent_search",
        "procedure_guide",
        "rights_check",
        "system_explanation",
    ],
    "description": (
        "계산이 필요 없는 법률상담 질문의 유형. "
        "requires_calculation=false이고 괴롭힘 질문이 아닐 때만 설정. "
        "법조문 해석, 판례 조회, 절차 안내, 권리 확인, 제도 설명 중 해당하는 것을 선택."
    ),
}

ANALYZE_TOOL["input_schema"]["properties"]["consultation_topic"] = {
    "type": "string",
    "enum": [
        "해고·징계", "임금·통상임금", "근로시간·휴일",
        "퇴직·퇴직금", "연차휴가", "산재보상",
        "비정규직", "노동조합", "직장내괴롭힘",
        "근로계약", "고용보험", "기타",
    ],
    "description": "상담 주제 분류. consultation_type이 설정된 경우 반드시 함께 설정.",
}
```

#### 3.3.2 ANALYZER_SYSTEM 프롬프트 확장

```python
# 기존 규칙에 추가:
"""
10. **법률상담 분류** (requires_calculation=false이고 괴롭힘이 아닌 경우):
   - 법조문 의미, 적용 범위, 해석 질문 → consultation_type="law_interpretation"
   - "판례 알려줘", "판례가 있나요" → consultation_type="precedent_search"
   - "절차", "신청 방법", "어떻게 하나요" → consultation_type="procedure_guide"
   - "~할 수 있나요?", "~받을 수 있나요?" → consultation_type="rights_check"
   - "~가 뭔가요?", "~제도 설명" → consultation_type="system_explanation"
   - consultation_type 설정 시 consultation_topic도 반드시 설정하세요
   - 주제 키워드: 해고·징계, 임금·통상임금, 근로시간·휴일, 퇴직·퇴직금, 연차휴가, 산재보상, 비정규직, 노동조합, 직장내괴롭힘, 근로계약, 고용보험
11. relevant_laws는 계산·비계산 모두에서 추출하세요 (법률상담에서 특히 중요)
"""
```

#### 3.3.3 법률상담 전용 System Prompt (신규)

```python
CONSULTATION_SYSTEM_PROMPT = """당신은 한국 노동법 전문 상담사입니다.
아래 '참고 자료'는 실제 법원 판례, 고용노동부 행정해석, 노동OK 상담 사례에서 가져온 것입니다.

오늘 날짜: {today}

답변 원칙:
1. **현행 법조문이 포함된 경우** (최우선):
   - 법제처 국가법령정보센터에서 조회한 최신 법조문을 우선 인용하세요.
   - 출처: "(법제처 국가법령정보센터 조회)"
2. **판례가 포함된 경우**:
   - 판례번호, 선고일, 판결요지를 정확히 인용하세요.
   - 출처: "[출처: nodong.kr/case/{id}]" 형식
3. **행정해석이 포함된 경우**:
   - 문서번호(예: 근로기준정책과-579)와 일자를 정확히 인용하세요.
   - 출처: "[출처: nodong.kr/interpretation/{id}]" 형식
4. **답변 구조** (해당 항목만 포함):
   ① 핵심 답변 (1-2문장 요약)
   ② 관련 법조문 (인용)
   ③ 관련 판례 (요지 + 출처)
   ④ 행정해석 (회시 답변 + 출처)
   ⑤ 유사 상담사례 (있을 경우)
   ⑥ 실무 안내 (신청 절차, 기한, 관할 기관 등)
   ⑦ 주의사항 + 면책 고지
5. 참고 자료에 없는 내용은 "참고 자료에서 확인되지 않습니다"라고 명시하세요.
6. **면책 고지** (반드시 포함):
   "본 답변은 참고용 정보 제공이며 법적 효력이 없습니다.
   구체적인 사안은 관할 고용노동부(☎ 1350) 또는 공인노무사에게 상담하시기 바랍니다."
7. 답변은 마크다운 형식으로 작성하세요.
"""
```

### 3.4 `app/core/analyzer.py` (수정)

변경 최소화 — `analyze_intent()` 반환값 구성 부분만 수정:

```python
# 기존 코드 (line 146~164)의 AnalysisResult 구성에 추가:
return AnalysisResult(
    requires_calculation=inp.get("requires_calculation", False),
    calculation_types=inp.get("calculation_types", []),
    extracted_info=extracted,
    relevant_laws=inp.get("relevant_laws", []),
    missing_info=missing_from_llm,
    question_summary=inp.get("question_summary", ""),
    # ── 신규 ──
    consultation_type=inp.get("consultation_type"),
    consultation_topic=inp.get("consultation_topic"),
)
```

### 3.5 `app/core/legal_consultation.py` (신규 모듈)

```python
"""법률상담 전용 모듈 — 멀티소스 검색 + 법조문 API + 컨텍스트 조립"""

from __future__ import annotations
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.config import AppConfig
from app.core.legal_api import fetch_relevant_articles

logger = logging.getLogger(__name__)

# ── 주제별 검색 설정 ──────────────────────────────────────────────

TOPIC_SEARCH_CONFIG: dict[str, dict] = {
    "해고·징계": {
        "namespaces": ["precedent", "interpretation", ""],
        "default_laws": ["근로기준법 제23조", "근로기준법 제26조", "근로기준법 제27조"],
        "boost_keywords": ["해고", "징계", "부당해고"],
    },
    "임금·통상임금": {
        "namespaces": ["precedent", "interpretation", ""],
        "default_laws": ["근로기준법 제2조", "근로기준법 제43조"],
        "boost_keywords": ["통상임금", "평균임금", "임금"],
    },
    "근로시간·휴일": {
        "namespaces": ["interpretation", "regulation", ""],
        "default_laws": ["근로기준법 제50조", "근로기준법 제53조", "근로기준법 제55조"],
        "boost_keywords": ["근로시간", "연장근로", "휴일"],
    },
    "퇴직·퇴직금": {
        "namespaces": ["interpretation", "precedent", ""],
        "default_laws": ["근로자퇴직급여 보장법 제4조", "근로자퇴직급여 보장법 제8조"],
        "boost_keywords": ["퇴직금", "퇴직연금"],
    },
    "연차휴가": {
        "namespaces": ["interpretation", "precedent", ""],
        "default_laws": ["근로기준법 제60조", "근로기준법 제61조"],
        "boost_keywords": ["연차", "연차휴가"],
    },
    "산재보상": {
        "namespaces": ["precedent", "interpretation", ""],
        "default_laws": ["산업재해보상보험법 제37조"],
        "boost_keywords": ["산재", "산업재해"],
    },
    "비정규직": {
        "namespaces": ["precedent", "interpretation", ""],
        "default_laws": [],
        "boost_keywords": ["비정규직", "기간제", "파견"],
    },
    "노동조합": {
        "namespaces": ["precedent", ""],
        "default_laws": [],
        "boost_keywords": ["노조", "노동조합"],
    },
    "직장내괴롭힘": {
        "namespaces": ["interpretation", "precedent", ""],
        "default_laws": ["근로기준법 제76조의2", "근로기준법 제76조의3"],
        "boost_keywords": ["괴롭힘", "갑질"],
    },
    "근로계약": {
        "namespaces": ["interpretation", "regulation", ""],
        "default_laws": ["근로기준법 제17조"],
        "boost_keywords": ["근로계약", "취업규칙"],
    },
    "고용보험": {
        "namespaces": ["interpretation", ""],
        "default_laws": ["고용보험법 제40조", "고용보험법 제69조"],
        "boost_keywords": ["실업급여", "고용보험"],
    },
    "기타": {
        "namespaces": ["", "interpretation"],
        "default_laws": [],
        "boost_keywords": [],
    },
}


# ── 멀티소스 검색 ─────────────────────────────────────────────────

def search_multi_namespace(
    query: str,
    namespaces: list[str],
    config: AppConfig,
    top_k_per_ns: int = 3,
    threshold: float = 0.4,
) -> list[dict]:
    """여러 Pinecone 네임스페이스에서 병렬 검색 후 점수 순 통합.

    Args:
        query: 사용자 질문 텍스트
        namespaces: 검색할 네임스페이스 목록 (""=BEST Q&A)
        config: AppConfig (openai_client, pinecone_index 포함)
        top_k_per_ns: 네임스페이스당 검색 결과 수
        threshold: 최소 유사도 점수

    Returns:
        [{score, source_type, title, section, chunk_text, url, date, category}]
        점수 내림차순, 최대 10개
    """
    # 1. 임베딩 (1회)
    resp = config.openai_client.embeddings.create(
        model="text-embedding-3-small", input=[query]
    )
    qvec = resp.data[0].embedding

    # 2. 병렬 검색
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
                    "source_type": md.get("source_type", "qa" if ns == "" else ns),
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

    # 3. 점수 정렬 + 최대 10개
    all_hits.sort(key=lambda x: x["score"], reverse=True)
    return all_hits[:10]


# ── 컨텍스트 조립 ─────────────────────────────────────────────────

# 소스 유형별 표시명
_SOURCE_LABELS = {
    "precedent": "판례",
    "interpretation": "행정해석",
    "regulation": "훈령/예규",
    "legal_case": "상담사례",
    "qa": "Q&A 사례",
}

def build_consultation_context(
    hits: list[dict],
    legal_articles_text: str | None = None,
) -> str:
    """검색 결과 + 법조문을 소스별로 그룹핑하여 LLM 컨텍스트 구성.

    Returns:
        포맷된 참고 자료 텍스트
    """
    parts = []

    # 1. 현행 법조문 (최우선)
    if legal_articles_text:
        parts.append(
            f"현행 법조문 (법제처 국가법령정보센터 조회):\n\n{legal_articles_text}"
        )

    # 2. 소스별 그룹핑
    grouped: dict[str, list[dict]] = {}
    for h in hits:
        st = h["source_type"]
        grouped.setdefault(st, []).append(h)

    # 판례 → 행정해석 → 훈령/예규 → Q&A → 상담사례 순서
    source_order = ["precedent", "interpretation", "regulation", "qa", "legal_case"]

    for source in source_order:
        group = grouped.get(source, [])
        if not group:
            continue
        label = _SOURCE_LABELS.get(source, source)
        section_parts = []
        for i, h in enumerate(group, 1):
            entry = f"[{label} {i}] {h['title']}"
            if h.get("date"):
                entry += f" ({h['date']})"
            if h.get("url"):
                entry += f"\n출처: {h['url']}"
            entry += f"\n\n{h['chunk_text']}"
            section_parts.append(entry)
        parts.append(f"참고 {label}:\n\n" + "\n\n---\n\n".join(section_parts))

    if not parts:
        return "(관련 법률 자료 없음)"

    return "\n\n===\n\n".join(parts)


# ── 통합 조회 함수 (pipeline.py에서 호출) ─────────────────────────

def process_consultation(
    query: str,
    consultation_topic: str | None,
    relevant_laws: list[str],
    config: AppConfig,
) -> tuple[str, list[dict]]:
    """법률상담 전용 처리 — 멀티소스 검색 + 법조문 API 조회.

    Args:
        query: 사용자 질문
        consultation_topic: 상담 주제 ("해고·징계", "임금·통상임금", ...)
        relevant_laws: LLM이 추출한 관련 법조문 참조 리스트
        config: AppConfig

    Returns:
        (context_text, source_hits) — LLM 컨텍스트 + 검색 결과 목록
    """
    topic_config = TOPIC_SEARCH_CONFIG.get(
        consultation_topic or "기타",
        TOPIC_SEARCH_CONFIG["기타"],
    )

    # 1. 법조문 목록: LLM 추출 + 주제별 기본값 병합
    all_laws = list(relevant_laws or [])
    for law in topic_config["default_laws"]:
        if law not in all_laws:
            all_laws.append(law)

    # 2. 멀티소스 벡터 검색 (병렬)
    namespaces = topic_config["namespaces"]
    hits = search_multi_namespace(query, namespaces, config, top_k_per_ns=3)

    # 3. 법조문 API 조회 (legal_api.py 재활용)
    legal_articles_text = None
    if all_laws and config.law_api_key:
        try:
            legal_articles_text = fetch_relevant_articles(all_laws, config.law_api_key)
        except Exception as e:
            logger.warning("법령 API 조회 실패: %s", e)

    # 4. 컨텍스트 조립
    context = build_consultation_context(hits, legal_articles_text)

    return context, hits
```

### 3.6 `app/core/pipeline.py` (수정)

변경 범위 최소화 — `process_question()` 함수 내 분기 추가:

```python
# ── 수정 위치: import 추가 (파일 상단) ──
from app.core.legal_consultation import process_consultation

# ── 수정 위치: Step 2 이후, Step 3 (RAG 검색) 이전 ──
# 2-2. 법률상담 전용 경로 (consultation_type 감지 시)
consultation_context = None
consultation_hits = []
if (analysis
    and analysis.consultation_type
    and not calc_result
    and not assessment_result):
    yield {"type": "status", "text": "법률 자료 검색 중..."}
    try:
        consultation_context, consultation_hits = process_consultation(
            query=query,
            consultation_topic=analysis.consultation_topic,
            relevant_laws=analysis.relevant_laws,
            config=config,
        )
    except Exception as e:
        logger.warning("법률상담 처리 실패: %s", e)

# ── 수정 위치: 컨텍스트 조립 (parts 구성) ──
if consultation_context:
    # 법률상담 경로: 전용 컨텍스트 사용
    parts = [f"참고 자료:\n\n{consultation_context}"]
    # 기존 RAG 결과도 보조로 포함 (검색된 경우)
    if hits and not consultation_hits:
        parts.append(f"추가 참고 (Q&A):\n\n{context}")
else:
    # 기존 경로: 변경 없음
    parts = [f"참고 문서:\n\n{context}"]

# ── 수정 위치: System Prompt 선택 ──
if consultation_context:
    from app.templates.prompts import CONSULTATION_SYSTEM_PROMPT
    system_prompt = CONSULTATION_SYSTEM_PROMPT.format(today=_date.today().isoformat())
else:
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(today=_date.today().isoformat())
```

**핵심 원칙**: 법률상담 경로는 기존 코드를 감싸는 형태로 추가. `consultation_context`가 None이면 기존 동작 그대로.

---

## 4. 데이터 흐름도

### 4.1 법률상담 경로 시퀀스

```
User: "5인 미만 사업장에서 부당해고 구제신청이 가능한가요?"
  │
  ├─[1] analyzer.py → analyze_intent()
  │   ANALYZE_TOOL 호출 결과:
  │     requires_calculation: false
  │     consultation_type: "rights_check"
  │     consultation_topic: "해고·징계"
  │     relevant_laws: ["근로기준법 제23조", "근로기준법 제11조"]
  │
  ├─[2] pipeline.py → consultation_type 감지
  │   → process_consultation() 호출
  │
  ├─[3] legal_consultation.py
  │   │
  │   ├─[3a] TOPIC_SEARCH_CONFIG["해고·징계"]
  │   │   namespaces: ["precedent", "interpretation", ""]
  │   │   default_laws: ["근로기준법 제23조", "근로기준법 제26조", "근로기준법 제27조"]
  │   │
  │   ├─[3b] search_multi_namespace (병렬)
  │   │   precedent NS → 해고 관련 판례 3건
  │   │   interpretation NS → 해고 관련 행정해석 3건
  │   │   default NS → BEST Q&A 해고 사례 3건
  │   │   → 점수 정렬 → 상위 10건
  │   │
  │   ├─[3c] fetch_relevant_articles (legal_api.py)
  │   │   근로기준법 제23조 → API 조회 → 조문 텍스트
  │   │   근로기준법 제11조 → API 조회 → 조문 텍스트
  │   │   근로기준법 제26조 → default_laws → 조문 텍스트
  │   │
  │   └─[3d] build_consultation_context
  │       현행 법조문 + 판례 + 행정해석 + Q&A → 구조화된 컨텍스트
  │
  ├─[4] pipeline.py → CONSULTATION_SYSTEM_PROMPT + 컨텍스트
  │   → LLM 스트리밍 답변
  │
  └─[5] 답변:
      ① 5인 미만 사업장은 근기법 제23조 미적용 → 구제신청 불가
      ② [근로기준법 제11조] 상시 5명 이상의 근로자를 사용하는...
      ③ [관련 판례] 대법원 YYYY다NNNN...
      ④ [행정해석] 근로기준정책과-XXX...
      ⑤ 다만 민사상 해고무효 소송은 가능...
```

---

## 5. 구현 순서 및 파일 목록

### 5.1 Step별 구현 순서

| Step | 파일 | 변경유형 | 설명 | 의존 |
|------|------|---------|------|------|
| 1 | `pinecone_upload_legal.py` | 신규 | 법률 데이터 벡터 업로드 스크립트 | 없음 |
| 2 | `app/models/schemas.py` | 수정 | AnalysisResult에 consultation_type/topic 추가 | 없음 |
| 3 | `app/templates/prompts.py` | 수정 | ANALYZE_TOOL 확장 + CONSULTATION_SYSTEM_PROMPT 추가 | Step 2 |
| 4 | `app/core/analyzer.py` | 수정 | consultation_type/topic 추출 (2줄 추가) | Step 2, 3 |
| 5 | `app/core/legal_consultation.py` | 신규 | 멀티소스 검색 + 컨텍스트 조립 | Step 1 (데이터) |
| 6 | `app/core/pipeline.py` | 수정 | 법률상담 경로 분기 추가 | Step 4, 5 |

### 5.2 변경 파일 상세

| 파일 | 변경 라인수 (추정) | 변경 내용 |
|------|-------------------|----------|
| `pinecone_upload_legal.py` | ~250 (신규) | 4개 소스 디렉토리 → Pinecone 네임스페이스별 업로드 |
| `app/models/schemas.py` | +2 | `consultation_type`, `consultation_topic` 필드 |
| `app/templates/prompts.py` | +45 | ANALYZE_TOOL 프로퍼티 2개 + 시스템 프롬프트 규칙 + CONSULTATION_SYSTEM_PROMPT |
| `app/core/analyzer.py` | +2 | AnalysisResult 생성 시 신규 필드 전달 |
| `app/core/legal_consultation.py` | ~200 (신규) | TOPIC_SEARCH_CONFIG + search_multi_namespace + build_consultation_context + process_consultation |
| `app/core/pipeline.py` | +25 | import 1줄 + 법률상담 분기 ~20줄 + System Prompt 선택 |

---

## 6. 에러 처리 및 Fallback

| 단계 | 실패 시나리오 | Fallback |
|------|-------------|----------|
| Intent 분류 | consultation_type 추출 실패 | consultation_type=None → 기존 RAG-only 경로 |
| 네임스페이스 검색 | 특정 NS 검색 오류 | 해당 NS 생략, 나머지 NS 결과 사용 |
| 법조문 API | API 키 미등록/타임아웃 | legal_articles_text=None → 법조문 없이 진행 |
| 전체 검색 실패 | 모든 NS에서 결과 없음 | consultation_context=None → 기존 RAG-only fallback |
| 벡터 데이터 미업로드 | 네임스페이스 비어있음 | 해당 NS 결과 0건 → 다른 NS로 보완 |

---

## 7. 테스트 전략

### 7.1 단위 테스트

| 테스트 | 대상 함수 | 검증 |
|--------|----------|------|
| 메타데이터 파싱 | `parse_md_metadata()` | 판례/행정해석 메타 테이블 → dict |
| 본문 추출 | `extract_legal_body()` | 메타 테이블 제거, 본문만 반환 |
| 멀티 검색 | `search_multi_namespace()` | 복수 NS 병렬 검색, 점수 정렬 |
| 컨텍스트 조립 | `build_consultation_context()` | 소스별 그룹핑, 법조문 우선 배치 |
| 주제 매핑 | `TOPIC_SEARCH_CONFIG` 조회 | 올바른 NS + default_laws 반환 |

### 7.2 통합 테스트 (E2E)

Plan 문서의 검증 시나리오 #1~#10 그대로 사용.

### 7.3 회귀 테스트

```bash
python3 wage_calculator_cli.py  # 기존 32개 테스트 케이스 전부 통과 확인
```

---

## 8. 성능 고려사항

| 항목 | 현재 | 추가 후 | 대응 |
|------|------|---------|------|
| 벡터 검색 횟수 | 1회 (default NS) | 최대 4회 (병렬) | ThreadPoolExecutor 병렬 실행 |
| 응답 시간 | ~3초 | ~5초 (법률상담 경로) | 벡터 검색 병렬화 + 법조문 캐시 |
| 임베딩 호출 | 1회 | 1회 (동일 벡터 재사용) | 변경 없음 |
| Pinecone 벡터 수 | ~1,722 | ~10,000 (+8,300) | 무료 플랜 100K 이내 |
| 법조문 API | 0~5회 | 0~5회 (동일) | 3단계 캐시 기존 활용 |

---

## 9. 파일 구조 (변경 후)

```
app/
├── core/
│   ├── analyzer.py             # [수정] consultation_type/topic 추출 추가
│   ├── legal_api.py            # [유지] 법제처 API 클라이언트 (재활용)
│   ├── legal_consultation.py   # [신규] 법률상담 전용 모듈
│   ├── pipeline.py             # [수정] 법률상담 경로 분기 추가
│   └── ...                     # 나머지 유지
├── models/
│   └── schemas.py              # [수정] AnalysisResult 필드 추가
└── templates/
    └── prompts.py              # [수정] ANALYZE_TOOL 확장 + CONSULTATION_SYSTEM_PROMPT

pinecone_upload_legal.py        # [신규] 법률 데이터 벡터 업로드 스크립트
```
