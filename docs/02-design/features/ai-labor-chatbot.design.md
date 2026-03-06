# Design: AI 노동상담 챗봇 — 계산기 + RAG + Pinecone 법령/판례 통합

> Plan 참조: `docs/01-plan/features/ai-labor-chatbot.plan.md`

---

## 1. 디렉토리 구조

```
app/
├── main.py                 # FastAPI 앱 진입점 + CORS + 라이프사이클
├── config.py               # 환경변수, API 키, 모델 설정
├── routes/
│   ├── chat.py             # POST /chat, GET /chat/stream (SSE)
│   └── health.py           # GET /health
├── core/
│   ├── analyzer.py         # Intent Analyzer (Claude tool_use)
│   ├── converter.py        # extracted_info → WageInput 변환
│   ├── calculator.py       # wage_calculator 호출 래퍼
│   ├── rag.py              # Pinecone 통합 검색 (Q&A + 법령/판례)
│   ├── composer.py         # 통합 답변 생성 (Claude 스트리밍)
│   └── pipeline.py         # 오케스트레이터 (①~⑥ 전체 흐름)
├── models/
│   ├── schemas.py          # Pydantic 요청/응답 스키마
│   └── session.py          # 대화 세션 상태 관리
├── static/
│   └── index.html          # 기본 채팅 UI (vanilla JS)
└── templates/
    └── prompts.py          # 시스템 프롬프트 + tool 정의
```

---

## 2. 전체 파이프라인 설계

### 2.1 요청 흐름 (6단계)

```
사용자 질문
  │
  ▼
① Intent Analyzer (Claude tool_use) ─── analyzer.py
  │  → requires_calculation, calculation_type, extracted_info, missing_info
  │  → relevant_laws: ["근로기준법 제56조", ...] (관련 법조문 키워드 추출)
  │
  ├─ [missing_info 있음] → 추가 질문 응답 반환 (session에 상태 저장)
  │
  ▼
② 계산 실행 (wage_calculator) ─── calculator.py
  │  extracted_info → WageInput → calculate()
  │  → WageResult (breakdown, formulas, warnings, legal_basis)
  │
  ▼
③ RAG 검색 — Q&A (Pinecone) ─── rag.py
  │  질문 + calculation_type → 유사 Q&A 검색
  │  → hits: [{title, chunk_text, url, score}]
  │
  ▼
④ RAG 검색 — 법령/판례 (Pinecone) ─── rag.py
  │  relevant_laws + legal_basis → 법령/판례 벡터 검색
  │  → legal_hits: [{title, chunk_text, score, ...}]
  │
  ▼
⑤ 통합 답변 생성 (Claude 스트리밍) ─── composer.py
  │  계산 결과 + Q&A 컨텍스트 + 법령/판례 컨텍스트 → 구조화 답변
  │
  ▼
⑥ SSE 스트리밍 응답 → 사용자
```

### 2.2 파이프라인 오케스트레이터

```python
# app/core/pipeline.py

async def process_question(
    question: str,
    session: ChatSession,
    config: AppConfig,
) -> AsyncIterator[str]:
    """전체 파이프라인 실행"""

    # ① 의도 분석
    analysis = await analyze_intent(question, session.history, config)

    # 추가 질문 필요 시 즉시 반환
    if analysis.missing_info and not session.has_pending_info():
        session.save_pending(analysis)
        yield format_follow_up_questions(analysis.missing_info)
        return

    # pending 정보가 있으면 병합
    if session.has_pending_info():
        analysis = session.merge_with_pending(analysis, question)

    # ② 계산 실행 (계산 필요 시)
    calc_result = None
    if analysis.requires_calculation:
        wage_input = convert_to_wage_input(analysis.extracted_info)
        calc_result = run_calculation(wage_input, analysis.calculation_types)

    # ③ Q&A RAG 검색
    rag_hits = await search_qna(question, analysis.calculation_type, config)

    # ④ 법령/판례 RAG 검색 (Pinecone)
    legal_hits = await search_legal(
        laws=analysis.relevant_laws,
        legal_basis=calc_result.legal_basis if calc_result else [],
        config=config,
    )

    # ⑤ 통합 답변 생성 (스트리밍)
    async for chunk in compose_answer(
        question=question,
        analysis=analysis,
        calc_result=calc_result,
        rag_hits=rag_hits,
        legal_hits=legal_hits,
        config=config,
    ):
        yield chunk

    # 세션 히스토리 업데이트
    session.add_turn(question, "assistant_response_placeholder")
```

---

## 3. Intent Analyzer 상세 설계

### 3.1 Claude Tool 정의

```python
# app/templates/prompts.py

ANALYZE_TOOL = {
    "name": "analyze_labor_question",
    "description": "노동상담 질문을 분석하여 계산기 입력 데이터와 관련 법령을 추출합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "requires_calculation": {
                "type": "boolean",
                "description": "이 질문이 임금/수당 등 수치 계산을 필요로 하는지"
            },
            "calculation_types": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "overtime", "minimum_wage", "weekly_holiday",
                        "annual_leave", "dismissal", "severance",
                        "unemployment", "insurance", "comprehensive",
                        "parental_leave", "maternity_leave", "prorated",
                        "wage_arrears", "flexible_work", "compensatory_leave"
                    ]
                },
                "description": "필요한 계산 유형 (복수 가능)"
            },
            # -- 임금 정보 --
            "wage_type": {
                "type": "string",
                "enum": ["시급", "일급", "월급", "연봉", "포괄임금제"],
            },
            "wage_amount": {"type": "number", "description": "임금액 (원)"},
            "business_size": {
                "type": "string",
                "enum": ["5인미만", "5인이상", "30인이상", "300인이상"],
            },
            # -- 근무 스케줄 --
            "weekly_work_days": {"type": "integer", "description": "주당 근무일수"},
            "daily_work_hours": {"type": "number", "description": "1일 소정근로시간"},
            "weekly_overtime_hours": {"type": "number", "description": "주당 연장근로시간"},
            "weekly_night_hours": {"type": "number", "description": "주당 야간근로시간 (22~06시)"},
            "weekly_holiday_hours": {"type": "number", "description": "주당 휴일근로시간 (8h이내)"},
            # -- 재직 정보 --
            "start_date": {"type": "string", "description": "입사일 (YYYY-MM-DD)"},
            "end_date": {"type": "string", "description": "퇴직/예정일 (YYYY-MM-DD)"},
            "service_period_text": {"type": "string", "description": "근무기간 텍스트 ('3년 6개월')"},
            # -- 수당/기타 --
            "fixed_allowances": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "amount": {"type": "number"},
                        "condition": {"type": "string", "enum": ["없음", "근무일수", "재직조건", "성과조건"]}
                    }
                },
                "description": "고정 수당 목록"
            },
            "monthly_wage": {"type": "number", "description": "월급 (포괄임금제 총액 등)"},
            "annual_wage": {"type": "number", "description": "연봉"},
            # -- 특수 계산 입력 --
            "notice_days_given": {"type": "integer", "description": "해고예고 일수 (해고예고수당용)"},
            "parental_leave_months": {"type": "integer", "description": "육아휴직 개월수"},
            "arrear_amount": {"type": "number", "description": "체불임금액"},
            "arrear_due_date": {"type": "string", "description": "체불 발생일"},
            # -- 분석 메타 --
            "relevant_laws": {
                "type": "array",
                "items": {"type": "string"},
                "description": "관련 법조문 키워드 (예: '근로기준법 제56조', '고용보험법 제69조')"
            },
            "missing_info": {
                "type": "array",
                "items": {"type": "string"},
                "description": "계산에 필요하지만 질문에서 확인할 수 없는 정보"
            },
            "question_summary": {
                "type": "string",
                "description": "핵심 질문 한 문장 요약"
            }
        },
        "required": ["requires_calculation", "question_summary"]
    }
}
```

### 3.2 분석 시스템 프롬프트

```python
ANALYZER_SYSTEM = """당신은 한국 노동법 전문 분석 AI입니다.
사용자의 노동상담 질문을 분석하여 analyze_labor_question 도구를 호출하세요.

분석 규칙:
1. 임금/수당/퇴직금 등 수치 계산이 필요하면 requires_calculation=true
2. 질문에서 추출 가능한 정보는 최대한 추출 (임금액, 근무시간, 근무기간 등)
3. 추출 불가능하지만 계산에 필수인 정보는 missing_info에 추가
4. 관련 법조문을 relevant_laws에 키워드로 추출 (예: "근로기준법 제56조")
5. 맥락 추론 허용: "하루 10시간 주5일" → daily_work_hours=8, weekly_overtime_hours=10
   (소정근로 8h 초과분 = 연장 2h × 5일 = 10h)
6. "5인 미만", "소규모" → business_size="5인미만"
7. 금액에 "만원" 단위 주의: "250만원" → 2500000

계산 유형 판단:
- 연장/야간/휴일 수당 문의 → overtime
- 최저임금 위반 여부 → minimum_wage
- 주휴수당 → weekly_holiday
- 퇴직금 → severance
- 해고예고수당 → dismissal
- 연차수당 → annual_leave
- 실업급여 → unemployment
- 육아휴직급여 → parental_leave
- 복수 유형 동시 가능 (예: 퇴직금+연차수당)
"""
```

### 3.3 분석 결과 타입

```python
# app/models/schemas.py

from pydantic import BaseModel

class AnalysisResult(BaseModel):
    requires_calculation: bool
    calculation_types: list[str] = []
    extracted_info: dict = {}       # WageInput으로 변환할 필드들
    relevant_laws: list[str] = []   # 관련 법조문 키워드
    missing_info: list[str] = []
    question_summary: str = ""
```

---

## 4. Pinecone 통합 검색 설계 (Q&A + 법령/판례)

### 4.1 데이터 현황

법령/판례 데이터를 포함한 모든 지식 데이터는 **이미 Pinecone 서버에 저장**되어 있다.
로컬 DB나 외부 API 연동 없이, Pinecone 벡터 검색만으로 Q&A·법령·판례 정보를 조회한다.

| Pinecone 인덱스 | 내용 | 주요 메타데이터 |
|-----------------|------|----------------|
| `nodongok-bestqna` | BEST Q&A 274건 | post_id, title, date, date_num, views, url, section, chunk_text |
| `nodongok-bestqna-2025` | 2025년 Q&A | + year |
| `nodongok-imgum` | 임금 게시글 (법령/판례 포함) | + board |

### 4.2 검색 전략: Q&A 검색 vs 법령/판례 검색

```
사용자 질문
  │
  ├─ ③ Q&A 검색: 질문 원문 → 임베딩 → Pinecone 유사도 검색
  │     목적: 유사 상담 사례 찾기
  │     쿼리: 사용자 질문 그대로
  │     인덱스: nodongok-bestqna, nodongok-bestqna-2025
  │
  └─ ④ 법령/판례 검색: 법조문 키워드 → 임베딩 → Pinecone 유사도 검색
        목적: 관련 법령 조문, 판례 내용 찾기
        쿼리: relevant_laws + legal_basis를 조합한 법률 검색 쿼리
        인덱스: 전체 (법령/판례 내용이 포함된 인덱스)
```

### 4.3 rag.py 인터페이스

```python
# app/core/rag.py

from openai import OpenAI
from pinecone import Pinecone

EMBED_MODEL = "text-embedding-3-small"


def _embed_query(query: str, openai_client: OpenAI) -> list[float]:
    resp = openai_client.embeddings.create(model=EMBED_MODEL, input=[query])
    return resp.data[0].embedding


def _search_index(
    query_vec: list[float],
    index,
    top_k: int,
    threshold: float,
) -> list[dict]:
    """Pinecone 인덱스 검색 → 임계값 이상 결과 반환"""
    results = index.query(vector=query_vec, top_k=top_k, include_metadata=True)
    hits = []
    for match in results.matches:
        if match.score < threshold:
            continue
        hits.append({
            "score": round(match.score, 4),
            "post_id": match.metadata.get("post_id", ""),
            "title": match.metadata.get("title", ""),
            "date": match.metadata.get("date", ""),
            "views": match.metadata.get("views", 0),
            "url": match.metadata.get("url", ""),
            "section": match.metadata.get("section", ""),
            "chunk_text": match.metadata.get("chunk_text", ""),
        })
    return hits


async def search_qna(
    question: str,
    calculation_type: str | None,
    config: "AppConfig",
) -> list[dict]:
    """
    ③ Q&A 검색: 사용자 질문으로 유사 상담 사례 검색

    여러 인덱스를 순차 검색하여 결과를 병합하고 score 순 정렬.
    """
    query_vec = _embed_query(question, config.openai_client)
    all_hits = []

    for index in config.qna_indexes:  # [bestqna, bestqna-2025]
        hits = _search_index(query_vec, index, top_k=5, threshold=0.4)
        all_hits.extend(hits)

    # score 기준 정렬, 상위 N개 반환
    all_hits.sort(key=lambda h: h["score"], reverse=True)
    return all_hits[:config.rag_top_k]


async def search_legal(
    laws: list[str],
    legal_basis: list[str],
    config: "AppConfig",
) -> list[dict]:
    """
    ④ 법령/판례 검색: 관련 법조문 키워드로 Pinecone 검색

    relevant_laws + legal_basis를 조합하여 법률 중심 검색 쿼리를 구성.
    예: ["근로기준법 제56조 연장근로", "대법원 2023다302838 통상임금"]
    """
    if not laws and not legal_basis:
        return []

    # 법령 키워드를 하나의 검색 쿼리로 조합
    query_parts = []
    for law in laws:
        query_parts.append(law)
    for basis in legal_basis:
        # wage_calculator legal_basis: "근로기준법 제56조 (연장·야간·휴일 근로)" 형태
        query_parts.append(basis)

    legal_query = " ".join(query_parts[:10])  # 최대 10개 키워드 조합
    query_vec = _embed_query(legal_query, config.openai_client)

    all_hits = []
    for index in config.all_indexes:  # 전체 인덱스에서 법령/판례 검색
        hits = _search_index(query_vec, index, top_k=5, threshold=0.35)
        all_hits.extend(hits)

    all_hits.sort(key=lambda h: h["score"], reverse=True)
    return all_hits[:config.legal_top_k]
```

### 4.4 config.py — Pinecone 인덱스 설정

```python
# app/config.py

from dataclasses import dataclass, field
from openai import OpenAI
from pinecone import Pinecone
import anthropic

@dataclass
class AppConfig:
    # API 클라이언트
    openai_client: OpenAI = None
    anthropic_client: anthropic.AsyncAnthropic = None
    pc: Pinecone = None

    # Pinecone 인덱스
    qna_indexes: list = field(default_factory=list)    # Q&A 검색용
    all_indexes: list = field(default_factory=list)     # 법령/판례 포함 전체

    # 모델 설정
    analyzer_model: str = "claude-sonnet-4-20250514"
    answer_model: str = "claude-sonnet-4-20250514"

    # 검색 설정
    rag_top_k: int = 5
    legal_top_k: int = 5

    @classmethod
    def from_env(cls) -> "AppConfig":
        import os
        openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        anthropic_client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))

        # Pinecone 인덱스 연결
        idx_bestqna = pc.Index("nodongok-bestqna")
        idx_bestqna_2025 = pc.Index("nodongok-bestqna-2025")
        idx_imgum = pc.Index("nodongok-imgum")

        return cls(
            openai_client=openai_client,
            anthropic_client=anthropic_client,
            pc=pc,
            qna_indexes=[idx_bestqna, idx_bestqna_2025],
            all_indexes=[idx_bestqna, idx_bestqna_2025, idx_imgum],
        )
```

---

## 5. Converter 설계 (extracted_info → WageInput)

### 5.1 기존 from_analysis() 확장

```python
# app/core/converter.py

from wage_calculator.models import (
    WageInput, WageType, BusinessSize, WorkSchedule, AllowanceCondition
)


WAGE_TYPE_MAP = {
    "시급": WageType.HOURLY,
    "일급": WageType.DAILY,
    "월급": WageType.MONTHLY,
    "연봉": WageType.ANNUAL,
    "포괄임금제": WageType.COMPREHENSIVE,
}

BIZ_SIZE_MAP = {
    "5인미만": BusinessSize.UNDER_5,
    "5인이상": BusinessSize.OVER_5,
    "30인이상": BusinessSize.OVER_30,
    "300인이상": BusinessSize.OVER_300,
}


def convert_to_wage_input(info: dict) -> WageInput:
    """
    Claude tool_use 추출 결과 → WageInput 변환

    기존 _provided_info_to_input() 대비 개선:
    - 53필드 중 30+ 필드 매핑 (기존 6필드)
    - 근무 스케줄 세부 설정
    - 고정수당 매핑
    - 특수 계산기 입력 (육아, 출산, 체불 등)
    """
    wage_type = WAGE_TYPE_MAP.get(info.get("wage_type", ""), WageType.MONTHLY)
    biz_size = BIZ_SIZE_MAP.get(info.get("business_size", ""), BusinessSize.OVER_5)

    # 근무 스케줄
    schedule = WorkSchedule(
        weekly_work_days=info.get("weekly_work_days", 5),
        daily_work_hours=info.get("daily_work_hours", 8.0),
        weekly_overtime_hours=info.get("weekly_overtime_hours", 0.0),
        weekly_night_hours=info.get("weekly_night_hours", 0.0),
        weekly_holiday_hours=info.get("weekly_holiday_hours", 0.0),
        weekly_holiday_overtime_hours=info.get("weekly_holiday_overtime_hours", 0.0),
    )

    inp = WageInput(
        wage_type=wage_type,
        business_size=biz_size,
        schedule=schedule,
    )

    # -- 임금 설정 --
    amount = info.get("wage_amount")
    if amount:
        if wage_type == WageType.HOURLY:
            inp.hourly_wage = amount
        elif wage_type == WageType.DAILY:
            inp.daily_wage = amount
        elif wage_type in (WageType.MONTHLY, WageType.COMPREHENSIVE):
            inp.monthly_wage = amount
        elif wage_type == WageType.ANNUAL:
            inp.annual_wage = amount

    # -- 재직 기간 --
    if info.get("start_date"):
        inp.start_date = info["start_date"]
    elif info.get("service_period_text"):
        inp.start_date = _guess_start_date(info["service_period_text"])

    if info.get("end_date"):
        inp.dismissal_date = info["end_date"]

    # -- 고정수당 --
    for a in info.get("fixed_allowances", []):
        inp.fixed_allowances.append({
            "name": a.get("name", "수당"),
            "amount": a.get("amount", 0),
            "condition": a.get("condition", "없음"),
        })

    # -- 특수 계산기 입력 --
    if info.get("notice_days_given") is not None:
        inp.notice_days_given = info["notice_days_given"]
    if info.get("parental_leave_months"):
        inp.parental_leave_months = info["parental_leave_months"]
    if info.get("arrear_amount"):
        inp.arrear_amount = info["arrear_amount"]
    if info.get("arrear_due_date"):
        inp.arrear_due_date = info["arrear_due_date"]
    if info.get("monthly_wage"):
        inp.monthly_wage = info["monthly_wage"]

    return inp
```

---

## 6. Answer Composer 설계

### 6.1 통합 답변 프롬프트

```python
# app/core/composer.py

COMPOSER_SYSTEM = """당신은 한국 노동법 전문 상담사입니다.
아래 제공된 정보를 활용하여 정확하고 친절한 답변을 생성하세요.

답변 구조 (해당 항목이 있을 때만 포함):

1. **답변 요약**: 핵심 답변 1-2문장
2. **계산 결과**: 계산기 결과 표 (있을 경우)
3. **산출 근거**: 계산식 단계별 설명
4. **법적 근거**: 관련 법조문 인용
5. **관련 판례**: 참고 판례 (있을 경우)
6. **유사 사례**: RAG 검색 결과에서 관련 Q&A 인용
7. **주의사항**: 계산기 경고 + 면책 고지

규칙:
- 법령/판례 정보는 제공된 검색 결과에서 정확히 인용하세요
- 계산 결과는 표 형식으로 깔끔하게 정리하세요
- 불확실한 내용은 "확인이 필요합니다"라고 명시하세요
- 마지막에 "본 답변은 참고용이며 법적 효력이 없습니다" 면책 고지 포함"""


async def compose_answer(
    question: str,
    analysis: "AnalysisResult",
    calc_result: "WageResult | None",
    rag_hits: list[dict],
    legal_hits: list[dict],
    config: "AppConfig",
) -> AsyncIterator[str]:
    """계산 결과 + Q&A RAG + 법령/판례 RAG를 통합하여 스트리밍 답변 생성"""

    # 컨텍스트 구성
    context_parts = []

    # 계산 결과
    if calc_result:
        context_parts.append(_format_calc_context(calc_result))

    # 법령/판례 (Pinecone 검색 결과)
    if legal_hits:
        context_parts.append(_format_legal_context(legal_hits))

    # Q&A 유사 사례
    if rag_hits:
        context_parts.append(_format_rag_context(rag_hits))

    user_message = (
        f"질문: {question}\n\n"
        f"질문 분석: {analysis.question_summary}\n\n"
        + "\n\n---\n\n".join(context_parts)
    )

    # Claude 스트리밍
    async with config.anthropic_client.messages.stream(
        model=config.answer_model,
        max_tokens=3000,
        system=COMPOSER_SYSTEM,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        async for text in stream.text_stream:
            yield text
```

### 6.2 컨텍스트 포맷 함수

```python
def _format_calc_context(result: "WageResult") -> str:
    """계산 결과를 컨텍스트 문자열로 변환"""
    lines = ["[계산 결과]"]
    for key, val in result.summary.items():
        lines.append(f"  {key}: {val}")
    lines.append(f"\n  통상시급: {result.ordinary_hourly:,.0f}원")
    lines.append(f"  월 총액(세전): {result.monthly_total:,.0f}원")
    if result.monthly_net > 0:
        lines.append(f"  월 실수령액: {result.monthly_net:,.0f}원")
    lines.append(f"\n[계산식]")
    for f in result.formulas[:10]:
        lines.append(f"  {f}")
    if result.warnings:
        lines.append(f"\n[주의사항]")
        for w in result.warnings[:5]:
            lines.append(f"  - {w}")
    return "\n".join(lines)


def _format_legal_context(hits: list[dict]) -> str:
    """법령/판례 Pinecone 검색 결과를 컨텍스트 문자열로 변환"""
    lines = ["[관련 법령/판례]"]
    for i, h in enumerate(hits[:5], 1):
        lines.append(f"\n  [{i}] {h['title']} (유사도: {h['score']})")
        if h.get("date"):
            lines.append(f"  날짜: {h['date']}")
        if h.get("url"):
            lines.append(f"  출처: {h['url']}")
        lines.append(f"  {h['chunk_text'][:500]}")
    return "\n".join(lines)


def _format_rag_context(hits: list[dict]) -> str:
    """Q&A Pinecone 검색 결과를 컨텍스트 문자열로 변환"""
    lines = ["[유사 상담 사례]"]
    for i, h in enumerate(hits[:5], 1):
        lines.append(f"\n  [{i}] {h['title']} (유사도: {h['score']})")
        lines.append(f"  출처: {h['url']}  |  작성일: {h['date']}")
        lines.append(f"  {h['chunk_text'][:400]}")
    return "\n".join(lines)
```

---

## 7. FastAPI 서버 설계

### 7.1 API 엔드포인트

```python
# app/routes/chat.py

@router.post("/chat")
async def chat(req: ChatRequest) -> ChatResponse:
    """동기 응답 (전체 답변 한 번에 반환)"""
    session = get_or_create_session(req.session_id)
    result = await pipeline.process_question_sync(req.message, session, config)
    return ChatResponse(
        message=result.text,
        calc_result=result.calc_summary,
        session_id=session.id,
    )


@router.get("/chat/stream")
async def chat_stream(
    message: str,
    session_id: str | None = None,
) -> EventSourceResponse:
    """SSE 스트리밍 응답"""
    session = get_or_create_session(session_id)

    async def event_generator():
        # 메타데이터 먼저 전송
        yield {"event": "meta", "data": json.dumps({"session_id": session.id})}

        async for chunk in pipeline.process_question(message, session, config):
            yield {"event": "chunk", "data": chunk}

        yield {"event": "done", "data": ""}

    return EventSourceResponse(event_generator())
```

### 7.2 세션 관리

```python
# app/models/session.py

@dataclass
class ChatSession:
    id: str
    history: list[dict] = field(default_factory=list)    # [{role, content}]
    pending_analysis: AnalysisResult | None = None        # 추가 질문 대기 상태
    created_at: float = 0.0
    last_active: float = 0.0

    def has_pending_info(self) -> bool:
        return self.pending_analysis is not None

    def save_pending(self, analysis: AnalysisResult):
        self.pending_analysis = analysis

    def merge_with_pending(self, new_analysis, user_reply: str) -> AnalysisResult:
        """사용자 추가 응답을 pending 분석에 병합"""
        merged = self.pending_analysis
        # 새로 추출된 정보로 기존 missing 필드 채움
        for key, val in new_analysis.extracted_info.items():
            if val is not None:
                merged.extracted_info[key] = val
        merged.missing_info = [
            m for m in merged.missing_info
            if m not in new_analysis.extracted_info
        ]
        self.pending_analysis = None
        return merged


# 인메모리 세션 스토어 (프로덕션에서는 Redis)
_sessions: dict[str, ChatSession] = {}
SESSION_TTL = 3600  # 1시간
```

---

## 8. 웹 UI 설계

### 8.1 기본 UI (Phase 1: vanilla HTML+JS)

```
┌────────────────────────────────────────┐
│  노동법 AI 상담                         │
│  ─────────────────────────────          │
│                                          │
│  사용자: 월급 250만원인데 주 5일         │
│  하루 10시간 근무합니다. 연장수당        │
│  얼마나 받을 수 있나요?                  │
│                                          │
│  AI:                                     │
│  ┌──────────────────────────────┐       │
│  │ 계산 결과                     │       │
│  │ 통상시급: 11,962원           │       │
│  │ 연장수당(월): 389,730원      │       │
│  │ ───────────────               │       │
│  │ 법적 근거:                    │       │
│  │ 근로기준법 제56조제1항:       │       │
│  │ "사용자는 연장근로에 대하여   │       │
│  │  통상임금의 50%를 가산..."    │       │
│  │ ───────────────               │       │
│  │ 관련 판례:                    │       │
│  │ 대법원 2023다302838          │       │
│  │ (통상임금 고정성 요건 폐기)   │       │
│  └──────────────────────────────┘       │
│                                          │
│  [────────────── 입력 ──────────] [전송] │
└────────────────────────────────────────┘
```

### 8.2 프론트엔드 기술

| Phase | 기술 | 설명 |
|-------|------|------|
| **Phase 1** | FastAPI + `static/index.html` | Vanilla JS, SSE(EventSource), 단일 서버 |
| **Phase 3** | Next.js 14 App Router | React, shadcn/ui, Tailwind, SSE 클라이언트 |

---

## 9. 변경하지 않는 것 (명시적)

| 항목 | 이유 |
|------|------|
| `wage_calculator/` 내부 로직 | 19개 계산기 로직 변경 없음. facade.calculate() 인터페이스만 사용 |
| `chatbot.py` | 기존 CLI 챗봇은 독립 유지 (app/은 별도) |
| `WageInput` 53필드 구조 | 기존 구조 그대로 활용, 재설계하지 않음 |
| Pinecone 인덱스 구조/데이터 | 기존 인덱스·임베딩·메타데이터 그대로 검색만 수행 |
| `constants.py` | 기존 상수 구조 유지 |

---

## 10. 구현 순서 (8단계)

| Step | 작업 | 파일 | 검증 |
|------|------|------|------|
| **1** | 프로젝트 구조 생성 + config.py | `app/__init__.py`, `app/config.py` | import 확인, Pinecone 인덱스 연결 |
| **2** | Intent Analyzer (Claude tool_use) | `app/core/analyzer.py`, `app/templates/prompts.py` | 샘플 질문 10개 분석 |
| **3** | Converter (extracted_info → WageInput) | `app/core/converter.py` | wage_calculator 36건 호환 |
| **4** | Calculator 래퍼 + RAG 통합 검색 | `app/core/calculator.py`, `app/core/rag.py` | Q&A 검색 + 법령/판례 검색 동작 |
| **5** | Answer Composer (통합 답변 생성) | `app/core/composer.py` | E2E: 질문→답변 |
| **6** | Pipeline 오케스트레이터 | `app/core/pipeline.py` | 전체 파이프라인 통합 |
| **7** | FastAPI 서버 + 세션 관리 | `app/main.py`, `app/routes/`, `app/models/session.py` | /chat API 동작 |
| **8** | 웹 UI + SSE 스트리밍 | `app/static/index.html` | 브라우저 E2E |

**검증 기준**: 매 Step 후 해당 모듈 단독 테스트 통과. Step 5 이후 10개 대표 시나리오 E2E 통과.

---

## 11. 예상 결과

### 11.1 파일 수 / 라인 수

| 컴포넌트 | 예상 파일 | 예상 라인 |
|----------|----------|----------|
| app/core/ (6파일) | analyzer, converter, calculator, rag, composer, pipeline | ~650 |
| app/routes/ (2파일) | chat, health | ~80 |
| app/models/ (2파일) | schemas, session | ~100 |
| app/templates/ (1파일) | prompts | ~80 |
| app/static/ (1파일) | index.html | ~200 |
| app/ 기타 | main.py, config.py, __init__.py | ~80 |
| **합계** | ~12파일 | ~1,190 |

### 11.2 답변 품질 기대치

| 시나리오 | 기존 chatbot.py | AI 노동상담 챗봇 |
|----------|-----------------|------------------|
| "월급 250만원, 연장 10시간" | RAG 유사 사례만 | 계산 결과 + 법령 검색 결과 + 유사 사례 |
| "퇴직금 얼마" (정보 부족) | 모호한 일반 답변 | "근무기간과 임금을 알려주세요" 후속 질문 |
| "5인 미만인데 연장수당" | RAG 답변 | 계산(가산 미적용) + 근기법 관련 내용 Pinecone 검색 |
| "통상임금에 상여금 포함?" | RAG 답변 | 2023다302838 관련 Pinecone 검색 결과 인용 |
