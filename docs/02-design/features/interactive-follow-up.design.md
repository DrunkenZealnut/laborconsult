# Design: Interactive Follow-Up Questions (추가정보 수집 대화)

## Executive Summary

| Item | Detail |
|------|--------|
| Feature | interactive-follow-up |
| Plan Reference | `docs/01-plan/features/interactive-follow-up.plan.md` |
| Phase | Design |
| Created | 2026-03-07 |

---

## 1. System Architecture

### 1.1 Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│  Frontend (public/index.html)                                   │
│  ┌──────────┐  ┌─────────────┐  ┌───────────────────────────┐  │
│  │ send()   │→ │ readSSE()   │→ │ follow_up event handler   │  │
│  │          │  │             │  │ → 추가질문을 assistant로 표시│  │
│  └──────────┘  └─────────────┘  └───────────────────────────┘  │
└───────────────────────────┬─────────────────────────────────────┘
                            │ SSE / POST
┌───────────────────────────▼─────────────────────────────────────┐
│  API Layer (api/index.py)                                       │
│  ┌────────────────────────────────────────────┐                 │
│  │ /api/chat/stream  → process_question()     │                 │
│  │ follow_up 이벤트 → {"type":"follow_up",...} │                 │
│  └────────────────────────────────────────────┘                 │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│  Pipeline (app/core/pipeline.py)                                │
│                                                                 │
│  ① analyze_intent()  ─┬→ missing_info 있음 → follow_up yield   │
│                       │   → session.save_pending()              │
│                       │   → return                              │
│                       │                                         │
│                       └→ missing_info 없음 or 이미 pending 병합  │
│                          │                                      │
│  ② _run_calculator() ◄──┘                                       │
│  ③ _run_assessor()                                              │
│  ④ _search() (RAG)                                              │
│  ⑤ Claude streaming answer                                     │
└─────────────────────────────────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│  Supporting Modules                                             │
│  ┌──────────────┐  ┌────────────┐  ┌────────────────────────┐  │
│  │ analyzer.py  │  │ composer.py│  │ session.py             │  │
│  │ (기존 완성)   │  │ (기존 완성) │  │ pending 상태 추가 필요  │  │
│  └──────────────┘  └────────────┘  └────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 Pipeline Flow (상세)

```
process_question(query, session, config, attachments)
│
├─ session.has_pending_info()?
│  ├─ YES: ① analyze_intent(query) → new_analysis
│  │        merged = session.merge_with_pending(new_analysis, query)
│  │        → 기존 extracted + 새 extracted 합쳐 계산 실행
│  │        → ②③④⑤ 이후 단계로 진행
│  │
│  └─ NO:  ① analyze_intent(query)
│          ├─ requires_calculation=true AND missing_info 비어있지 않음
│          │  → session.save_pending(analysis)
│          │  → compose_follow_up(missing_info, question_summary)
│          │  → yield {"type": "follow_up", "text": ...}
│          │  → session.add_turn(query, follow_up_text)
│          │  → return
│          │
│          ├─ requires_calculation=true AND missing_info 비어있음
│          │  → ②③④⑤ 계산 + RAG + 답변 진행
│          │
│          └─ requires_calculation=false
│             → ④⑤ RAG + 답변 (계산 스킵)
│
② tool_type 판별 + 계산/판정 실행
│  ├─ wage: _extract_params() → _run_calculator()
│  └─ harassment: _extract_params() → _run_assessor()
│
③ RAG 검색: _search(query)
│
④ 컨텍스트 구성 + Claude 스트리밍 답변
│
⑤ session.add_turn(query, full_text)
```

---

## 2. Data Models

### 2.1 AnalysisResult (추가)

```python
# app/models/schemas.py에 추가

class AnalysisResult(BaseModel):
    """의도 분석 결과"""
    requires_calculation: bool = False
    calculation_types: list[str] = []        # ["overtime", "severance"]
    extracted_info: dict = {}                 # {wage_type: "시급", wage_amount: 15000, ...}
    relevant_laws: list[str] = []             # ["근로기준법 제56조"]
    missing_info: list[str] = []              # ["사업장 규모(5인 이상/미만)", "주 소정근로시간"]
    question_summary: str = ""                # "시급 15,000원 근로자의 연장수당 계산"
```

### 2.2 Session 확장

```python
# app/models/session.py 수정

@dataclass
class Session:
    id: str
    history: list = field(default_factory=list)
    _pending_analysis: AnalysisResult | None = None    # 추가

    def has_pending_info(self) -> bool:
        return self._pending_analysis is not None

    def save_pending(self, analysis: AnalysisResult):
        self._pending_analysis = analysis

    def merge_with_pending(self, new_analysis: AnalysisResult, user_reply: str) -> AnalysisResult:
        """기존 pending analysis + 새로 추출된 정보를 병합"""
        merged = self._pending_analysis
        # 새로 추출된 정보로 업데이트
        for key, val in new_analysis.extracted_info.items():
            if val is not None:
                merged.extracted_info[key] = val
        # 이미 제공된 정보는 missing_info에서 제거
        merged.missing_info = [
            m for m in merged.missing_info
            if m not in new_analysis.extracted_info
        ]
        self._pending_analysis = None
        return merged

    def clear_pending(self):
        self._pending_analysis = None
```

### 2.3 SSE Event Types

| Event Type | Payload | When |
|-----------|---------|------|
| `session` | `{session_id}` | 연결 시작 |
| `status` | `{text}` | 진행 상태 표시 |
| `follow_up` | `{text, missing_fields}` | 추가 질문 필요 시 |
| `meta` | `{calc_result}` | 계산 결과 (있을 때) |
| `sources` | `{hits}` | RAG 검색 결과 |
| `chunk` | `{text}` | 스트리밍 답변 텍스트 |
| `done` | `{}` | 완료 |

**`follow_up` event 상세:**
```json
{
  "type": "follow_up",
  "text": "**퇴직금 계산**에 대해 답변드리기 위해 추가 정보가 필요합니다:\n\n1. 임금 형태와 금액 (시급/월급/연봉)\n2. 근무 기간 (입사일~퇴직일 또는 총 근무기간)\n3. 사업장 규모 (5인 이상/미만)\n\n위 정보를 알려주시면 정확한 계산 결과를 제공해 드리겠습니다.",
  "missing_fields": ["임금 형태와 금액", "근무 기간", "사업장 규모"]
}
```

---

## 3. Module-Level Design

### 3.1 pipeline.py 수정사항

**현재 구조 유지 + analyze_intent 단계 삽입:**

현재 `pipeline.py`의 `process_question()` 함수 시작 부분에 분석 단계를 추가한다. 기존 `_extract_params()` → `_run_calculator()` / `_run_assessor()` 로직은 그대로 유지하되, 분석 단계에서 `missing_info`가 감지되면 follow_up을 먼저 발행하고 return한다.

```python
def process_question(query, session, config, attachments=None):
    # 0. 첨부파일 처리 (기존 로직 유지)
    ...

    # 1. [NEW] pending 정보 병합 또는 새 분석
    yield {"type": "status", "text": "질문 분석 중..."}

    if session.has_pending_info():
        # 추가 정보를 제공한 경우 → 분석 후 pending과 병합
        new_analysis = analyze_intent(combined_query, session.recent(), config)
        analysis = session.merge_with_pending(new_analysis, query)
        # → 아래 계산 단계로 진행 (follow_up 다시 안 함)

    else:
        # 새 질문 → 분석
        analysis = analyze_intent(combined_query, session.recent(), config)

        # missing_info가 있고 계산이 필요한 질문이면 → follow_up
        if analysis.requires_calculation and analysis.missing_info:
            session.save_pending(analysis)
            follow_up_text = compose_follow_up(
                analysis.missing_info, analysis.question_summary
            )
            yield {"type": "follow_up", "text": follow_up_text,
                   "missing_fields": analysis.missing_info}
            session.add_user(query)
            session.add_assistant(follow_up_text)
            yield {"type": "done"}
            return

    # 2. 기존 로직: _extract_params → _run_calculator / _run_assessor
    #    단, analysis.extracted_info가 있으면 그것을 우선 사용
    ...

    # 3~5. RAG 검색, 컨텍스트, Claude 스트리밍 (기존 로직 유지)
```

**핵심: 최소 변경 원칙**
- `_extract_params()`, `_run_calculator()`, `_run_assessor()` 기존 함수는 **그대로 유지**
- `analyze_intent()`는 기존 `_extract_params()` 앞에 **선행 단계**로만 추가
- pending 병합 시 `analysis.extracted_info`에서 `_extract_params()` 파라미터를 직접 구성 가능

### 3.2 analyzer.py (기존 활용 — 변경 없음)

```python
# 이미 구현 완료: app/core/analyzer.py
def analyze_intent(question, history, config) -> AnalysisResult:
    """Claude tool_use로 의도 분석 + 파라미터 추출 + missing_info 식별"""
    ...
```

**ANALYZE_TOOL** (`app/templates/prompts.py`):
- `requires_calculation`: bool
- `calculation_types`: list[str]
- `wage_type`, `wage_amount`, `business_size`, ... (extracted_info)
- `missing_info`: list[str] — **핵심: 계산에 필요하지만 질문에서 확인 불가한 정보**
- `question_summary`: str

### 3.3 composer.py (기존 활용 — 변경 없음)

```python
# 이미 구현 완료: app/core/composer.py
def compose_follow_up(missing_info: list[str], question_summary: str) -> str:
    """missing_info를 자연어 추가 질문으로 변환"""
    lines = [f"**{question_summary}**에 대해 답변드리기 위해 추가 정보가 필요합니다:\n"]
    for i, info in enumerate(missing_info, 1):
        lines.append(f"{i}. {info}")
    lines.append("\n위 정보를 알려주시면 정확한 계산 결과를 제공해 드리겠습니다.")
    return "\n".join(lines)
```

### 3.4 session.py 수정사항

현재 `Session` dataclass에 3개 메서드 추가:

```python
from app.models.schemas import AnalysisResult   # import 추가

@dataclass
class Session:
    id: str
    history: list = field(default_factory=list)
    _pending_analysis: AnalysisResult | None = field(default=None, repr=False)

    # 기존 메서드 유지: add_user, add_assistant, recent

    def has_pending_info(self) -> bool:
        return self._pending_analysis is not None

    def save_pending(self, analysis: AnalysisResult):
        self._pending_analysis = analysis

    def merge_with_pending(self, new_analysis: AnalysisResult, user_reply: str) -> AnalysisResult:
        merged = self._pending_analysis
        for key, val in new_analysis.extracted_info.items():
            if val is not None:
                merged.extracted_info[key] = val
        merged.missing_info = [
            m for m in merged.missing_info
            if m not in new_analysis.extracted_info
        ]
        self._pending_analysis = None
        return merged

    def clear_pending(self):
        self._pending_analysis = None
```

### 3.5 schemas.py 수정사항

`AnalysisResult` 모델 추가:

```python
class AnalysisResult(BaseModel):
    requires_calculation: bool = False
    calculation_types: list[str] = []
    extracted_info: dict = {}
    relevant_laws: list[str] = []
    missing_info: list[str] = []
    question_summary: str = ""
```

### 3.6 api/index.py (변경 최소)

**이미 follow_up 핸들링 존재** (`index.py:60-65`):
```python
elif event["type"] == "follow_up":
    return {
        "message": event["text"],
        "session_id": session.id,
        "follow_up": True,
    }
```

SSE 스트리밍 엔드포인트에서는 별도 처리 불필요 — `event_generator()`가 이미 모든 event를 `json.dumps`로 전송.

### 3.7 public/index.html 수정사항

`readSSE()` 함수에 `follow_up` 이벤트 처리 추가:

```javascript
// 기존 event handling 부분에 추가
} else if (event.type === 'follow_up') {
    removeStatus();
    // follow_up 메시지를 assistant 메시지로 표시 (마크다운 렌더링)
    const el = addMsg('assistant', md(event.text));
    renderPendingMath(el);
}
```

- 추가 질문 메시지는 일반 assistant 메시지와 동일하게 렌더링
- 사용자가 답변을 입력하면 기존 `send()` 함수로 전송
- 서버에서 session_id로 pending 상태를 자동 복원하므로 프론트엔드에서 별도 상태 관리 불필요

---

## 4. analysis → 기존 계산기 브릿지

`analyze_intent()`가 반환하는 `AnalysisResult.extracted_info`와 기존 `_extract_params()`가 반환하는 파라미터를 연결하는 방법:

### 4.1 extracted_info → _extract_params 파라미터 매핑

| extracted_info key | _extract_params key | Notes |
|---|---|---|
| `wage_type` | `wage_type` | 동일 (시급/월급/연봉 등) |
| `wage_amount` | `wage_amount` | 동일 |
| `business_size` | `business_size` | 동일 |
| `weekly_work_days` | `weekly_work_days` | 동일 |
| `daily_work_hours` × `weekly_work_days` | `weekly_total_hours` | 변환 필요 |
| `weekly_overtime_hours` | `weekly_overtime_hours` | 동일 |
| `weekly_night_hours` | `weekly_night_hours` | 동일 |
| `weekly_holiday_hours` | `weekly_holiday_work_hours` | key 이름 다름 |
| `start_date` | `start_date` | 동일 |
| `end_date` | `end_date` | 동일 |
| `service_period_text` | `start_date` | _guess_start_date() 적용 |
| `calculation_types` | `calculation_type` | list→str 변환 (첫 번째 또는 매핑) |

### 4.2 브릿지 함수

```python
def _analysis_to_extract_params(analysis: AnalysisResult) -> tuple[str, dict]:
    """AnalysisResult를 기존 _extract_params() 반환 형식으로 변환"""
    info = analysis.extracted_info
    params = {
        "needs_calculation": analysis.requires_calculation,
        "calculation_type": _map_calc_type(analysis.calculation_types),
        "wage_type": info.get("wage_type"),
        "wage_amount": info.get("wage_amount") or info.get("monthly_wage") or info.get("annual_wage"),
        "weekly_work_days": info.get("weekly_work_days"),
        "weekly_total_hours": _calc_weekly_total(info),
        "weekly_overtime_hours": info.get("weekly_overtime_hours"),
        "weekly_night_hours": info.get("weekly_night_hours"),
        "weekly_holiday_work_hours": info.get("weekly_holiday_hours"),
        "business_size": info.get("business_size"),
        "start_date": info.get("start_date") or info.get("service_period_text"),
        "end_date": info.get("end_date"),
    }
    # None 값 제거
    params = {k: v for k, v in params.items() if v is not None}
    params["needs_calculation"] = analysis.requires_calculation
    return ("wage", params)


def _map_calc_type(types: list[str]) -> str:
    """calculation_types → 한국어 calculation_type 매핑"""
    REVERSE_MAP = {
        "overtime": "연장수당",
        "weekly_holiday": "주휴수당",
        "minimum_wage": "최저임금",
        "severance": "퇴직금",
        "annual_leave": "연차수당",
        "dismissal": "해고예고수당",
        "unemployment": "실업급여",
        "insurance": "임금계산",
        "parental_leave": "육아휴직",
        "maternity_leave": "출산휴가",
        "wage_arrears": "임금체불",
        "compensatory_leave": "보상휴가",
        "flexible_work": "탄력근무",
        "comprehensive": "포괄임금제",
        "eitc": "근로장려금",
    }
    if types:
        return REVERSE_MAP.get(types[0], "임금계산")
    return "임금계산"


def _calc_weekly_total(info: dict) -> float | None:
    """daily_work_hours × weekly_work_days → weekly_total_hours"""
    daily = info.get("daily_work_hours")
    days = info.get("weekly_work_days")
    if daily and days:
        return daily * days
    return None
```

---

## 5. Config 확장

`AppConfig`에 analyzer 모델 설정 추가 (기존 `EXTRACT_MODEL`과 동일한 Haiku 사용):

```python
# app/config.py
@dataclass
class AppConfig:
    openai_client: OpenAI
    pinecone_index: object
    claude_client: anthropic.Anthropic
    analyzer_model: str = EXTRACT_MODEL    # claude-haiku-4-5 (저비용)
```

`analyzer.py`에서 `config.claude_client`와 `config.analyzer_model`을 사용하므로 `anthropic_client` alias 또는 직접 속성 접근 필요. 현재 config에는 `claude_client`로 되어 있으므로 analyzer.py에서 `config.claude_client`로 참조.

---

## 6. Implementation Order

### Step 1: schemas.py — AnalysisResult 추가
- File: `app/models/schemas.py`
- 변경: `AnalysisResult` 클래스 추가
- 의존성: 없음

### Step 2: session.py — pending 상태 관리
- File: `app/models/session.py`
- 변경: `_pending_analysis` 필드 + 3개 메서드 (`has_pending_info`, `save_pending`, `merge_with_pending`)
- 의존성: Step 1 (AnalysisResult import)

### Step 3: config.py — analyzer_model 추가
- File: `app/config.py`
- 변경: `analyzer_model` 속성 추가
- 의존성: 없음

### Step 4: pipeline.py — 분석 단계 삽입 + 브릿지 함수
- File: `app/core/pipeline.py`
- 변경:
  - `analyze_intent` import 추가
  - `compose_follow_up` import 추가
  - `process_question()` 시작 부분에 분석 로직 추가
  - `_analysis_to_extract_params()` 브릿지 함수 추가
- 의존성: Step 1, 2, 3

### Step 5: index.html — follow_up 이벤트 핸들링
- File: `public/index.html`
- 변경: `readSSE()`에 `follow_up` case 추가
- 의존성: Step 4 (서버 측 follow_up 이벤트 발생)

### Step 6: 통합 테스트
- 시나리오 1: "퇴직금 얼마인가요?" → 추가 질문 → "월급 300만원, 3년 근무" → 정확한 계산
- 시나리오 2: "시급 15,000원, 주 5일 근무, 주휴수당은?" → 추가 질문 없이 즉시 계산
- 시나리오 3: "5인 미만에서 연차 발생하나요?" → 계산 불필요 → 즉시 RAG 답변
- 시나리오 4: 추가 질문 후 사용자가 다른 질문 → pending 자동 만료 (새 분석)

---

## 7. Edge Cases

| Case | Handling |
|------|----------|
| 추가 질문 후 사용자가 전혀 다른 질문 | `analyze_intent()` 결과 `calculation_types`가 다르면 pending을 버리고 새 분석 |
| missing_info가 5개 이상 | 상위 3개만 질문 (나머지는 기본값 적용) |
| 괴롭힘 질문에 missing_info | 괴롭힘은 follow_up 스킵 (계산 불필요이므로 `requires_calculation=false`) |
| 첨부파일 + 불완전 질문 | 첨부파일 텍스트도 analyze_intent에 전달 → 추출 가능 정보 최대화 |
| 세션 만료 후 추가 정보 입력 | pending 없으므로 새 질문으로 처리 (정상) |
| EITC (근로장려금) 질문 | `requires_calculation=true` + `missing_info=["가구유형", "연소득"]` → follow_up |

---

## 8. File Change Summary

| File | Change Type | Description |
|------|------------|-------------|
| `app/models/schemas.py` | ADD | `AnalysisResult` 모델 추가 |
| `app/models/session.py` | MODIFY | pending 관련 필드 + 3개 메서드 추가 |
| `app/config.py` | MODIFY | `analyzer_model` 속성 추가 |
| `app/core/pipeline.py` | MODIFY | 분석 단계 삽입, 브릿지 함수, follow_up yield |
| `public/index.html` | MODIFY | `readSSE()`에 follow_up 이벤트 핸들러 추가 |
| `app/core/analyzer.py` | NONE | 기존 코드 그대로 활용 |
| `app/core/composer.py` | NONE | 기존 `compose_follow_up()` 그대로 활용 |
| `app/templates/prompts.py` | NONE | 기존 `ANALYZE_TOOL`, `ANALYZER_SYSTEM` 그대로 활용 |
| `api/index.py` | NONE | 이미 follow_up 핸들링 존재 |

**총 수정 파일: 5개** (신규 0개)
