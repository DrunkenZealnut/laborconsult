# Design: 직장 내 괴롭힘 판정 및 해설

> Plan Reference: `docs/01-plan/features/workplace-harassment.plan.md`

---

## 1. Architecture Overview

기존 임금계산기(`wage_calculator/`)와 **독립된 패키지** `harassment_assessor/`를 생성한다.
임금계산기와 달리 수치 계산이 아닌 **법적 프레임워크 기반 평가**이므로, `WageResult`를 사용하지 않고 자체 `AssessmentResult`와 `format_assessment()`를 사용한다.

```
harassment_assessor/
├── __init__.py              # Public API exports
├── constants.py             # 법 조문, 유형 키워드, 절차 안내, 판정 가중치
├── models.py                # HarassmentInput dataclass, Enum들
├── assessor.py              # assess_harassment() — 3요소 판정 핵심 로직
└── result.py                # AssessmentResult dataclass, format_assessment()
```

**호출 흐름:**
```
사용자 질문 → chatbot.py extract_harassment_params() [Claude tool_use]
           → HarassmentInput 구성
           → assess_harassment(inp) → AssessmentResult
           → format_assessment(result) → 텍스트
           → Claude 최종 답변 생성 (판정 결과 + RAG 문서 + 해설)
```

**핵심 차이점 (임금계산기 vs 괴롭힘 판정):**
- 임금계산기: `WageInput` → `WageCalculator.calculate()` → `WageResult` → `format_result()`
- 괴롭힘 판정: `HarassmentInput` → `assess_harassment()` → `AssessmentResult` → `format_assessment()`
- 별도 facade 클래스 없이 함수 직접 호출 (단일 판정 로직이므로)

---

## 2. Data Design

### 2.1 constants.py

```python
# ── 괴롭힘 유형별 키워드 매핑 ────────────────────────────────────────────────
# Claude가 추출한 behavior_types를 정규화하는 데 사용
BEHAVIOR_TYPE_KEYWORDS: dict[str, list[str]] = {
    "폭행_협박":   ["폭행", "폭력", "때리", "물건 던", "협박", "위협", "살해"],
    "폭언_모욕":   ["욕설", "폭언", "모욕", "비하", "인격", "막말", "외모"],
    "따돌림_무시": ["따돌림", "왕따", "무시", "배제", "소외", "소문", "뒷담화", "정보 차단"],
    "부당업무":    ["허드렛일", "과도한 업무", "업무 배제", "전문성 무시", "잡일", "청소"],
    "사적용무":    ["심부름", "사적", "개인 용무", "종교", "정치", "모임 강요"],
    "감시_통제":   ["감시", "CCTV", "SNS", "사생활", "보고", "미행", "위치 추적"],
    "부당인사":    ["전보", "좌천", "승진 누락", "연봉 차별", "해고 압박", "사직 강요", "퇴사 종용"],
}

# ── 3요소 판정 가중치 ────────────────────────────────────────────────────────
# 각 요소별 점수 가중치 (합산으로 가능성 수준 결정)

# 요소1: 지위·관계 우위 점수
SUPERIORITY_SCORES: dict[str, float] = {
    "상급자":         1.0,   # 직급상 상위 (팀장→팀원 등)
    "사용자":         1.0,   # 사장, 대표, 임원
    "정규직_비정규직": 0.8,   # 고용형태 우위
    "다수_소수":       0.7,   # 인원수 우위 (3명→1명 등)
    "선임_후임":       0.6,   # 연차/나이 우위
    "동료":           0.3,   # 동등 관계 (우위 불분명)
    "하급자":         0.1,   # 하급자가 가해 (특수 상황)
    "고객":           0.0,   # 직장 내 괴롭힘 비해당 → 산안법
}

# 요소2: 업무 적정범위 초과 가중 요인
BEYOND_SCOPE_FACTORS: dict[str, float] = {
    "폭행_협박":   1.0,   # 명백히 업무 범위 초과
    "폭언_모욕":   0.9,
    "사적용무":    0.9,
    "따돌림_무시": 0.8,
    "감시_통제":   0.7,
    "부당인사":    0.7,
    "부당업무":    0.6,   # 업무 지시와 경계가 모호할 수 있음
}

# 빈도·기간 가중치
FREQUENCY_MULTIPLIER: dict[str, float] = {
    "1회":      0.3,
    "수회":     0.6,
    "반복":     0.8,
    "매일":     1.0,
    "수개월간":  1.0,
}

DURATION_MULTIPLIER: dict[str, float] = {
    "1회성":    0.3,
    "1주":      0.5,
    "1개월":    0.7,
    "3개월":    0.8,
    "6개월":    0.9,
    "1년이상":  1.0,
}

# ── 가능성 수준 임계값 ──────────────────────────────────────────────────────
# 3요소 종합 점수 (0.0~1.0) → 가능성 수준
LIKELIHOOD_THRESHOLDS = {
    "높음": 0.65,   # >= 0.65
    "보통": 0.40,   # >= 0.40
    "낮음": 0.0,    # < 0.40
}

# ── 법 조문 참조 ────────────────────────────────────────────────────────────
LEGAL_REFERENCES = [
    "근로기준법 제76조의2 (직장 내 괴롭힘의 금지)",
    "근로기준법 제76조의3 (직장 내 괴롭힘 발생 시 조치)",
    "근로기준법 제109조 제2항 (불리한 처우 벌칙: 3년 이하 징역/3천만원 이하 벌금)",
    "근로기준법 제116조 제2항 (조사·조치 의무 위반 과태료: 500만원 이하)",
]

CUSTOMER_HARASSMENT_LEGAL = [
    "산업안전보건법 제41조 (고객의 폭언 등으로 인한 건강장해 예방조치)",
]

# ── 대응 절차 ────────────────────────────────────────────────────────────────
RESPONSE_STEPS = [
    {
        "step": 1,
        "title": "증거 확보",
        "description": "녹음(대화 참여자로서 합법), 문자·이메일·메신저 캡처, 목격자 확인, 진단서 등",
    },
    {
        "step": 2,
        "title": "사내 신고",
        "description": "인사부서 또는 직장 내 괴롭힘 고충처리위원회에 서면 신고",
    },
    {
        "step": 3,
        "title": "회사 조사·조치",
        "description": "사용자는 지체 없이 조사 실시 의무 (제76조의3 제2항). "
                       "조사 중 피해자 보호조치(근무장소 변경, 유급휴가 등) 의무.",
    },
    {
        "step": 4,
        "title": "노동청 진정",
        "description": "회사 미조치 시 관할 지방고용노동관서에 진정 (전화 1350). "
                       "조사·조치 의무 위반 시 500만원 이하 과태료.",
    },
    {
        "step": 5,
        "title": "불리한 처우 시 형사고소",
        "description": "신고를 이유로 해고 등 불리한 처우 시 3년 이하 징역/3천만원 이하 벌금 "
                       "(제109조 제2항).",
    },
]

# ── 면책 문구 ────────────────────────────────────────────────────────────────
DISCLAIMER = (
    "⚠️ 본 판정은 법적 효력이 없는 참고 정보입니다. "
    "직장 내 괴롭힘 여부는 구체적 사실관계에 따라 달라질 수 있으며, "
    "정확한 판단은 고용노동부(1350) 또는 노무사·변호사에게 문의하세요."
)
```

### 2.2 models.py

```python
from dataclasses import dataclass, field
from enum import Enum


class RelationType(Enum):
    """가해자-피해자 관계 유형"""
    SUPERIOR    = "상급자"         # 직급상 상위자
    EMPLOYER    = "사용자"         # 사장/대표/임원
    REGULAR_IRR = "정규직_비정규직"  # 고용형태 우위
    MAJORITY    = "다수_소수"       # 인원수 우위
    SENIOR      = "선임_후임"       # 연차/나이 우위
    PEER        = "동료"           # 동등 관계
    SUBORDINATE = "하급자"         # 하급자가 가해
    CUSTOMER    = "고객"           # 고객 (직장 내 괴롭힘 비해당)


class BehaviorType(Enum):
    """괴롭힘 행위 유형"""
    ASSAULT        = "폭행_협박"
    VERBAL_ABUSE   = "폭언_모욕"
    OSTRACISM      = "따돌림_무시"
    UNFAIR_WORK    = "부당업무"
    PERSONAL_ERRAND = "사적용무"
    SURVEILLANCE   = "감시_통제"
    UNFAIR_HR      = "부당인사"


class Likelihood(Enum):
    """판정 가능성 수준"""
    HIGH   = "높음"
    MEDIUM = "보통"
    LOW    = "낮음"
    NA     = "비해당"  # 고객 괴롭힘 등 직장 내 괴롭힘 범위 밖


class ElementStatus(Enum):
    """3요소 개별 판정 상태"""
    MET     = "해당"
    NOT_MET = "미해당"
    UNCLEAR = "불분명"


@dataclass
class HarassmentInput:
    """괴롭힘 판정 입력 데이터"""
    # 관계
    perpetrator_role: str = ""           # 가해자 직위/역할 (자유 텍스트)
    victim_role: str = ""                # 피해자 직위/역할
    relationship_type: str = ""          # RelationType 값 또는 자유 텍스트

    # 행위
    behavior_description: str = ""       # 행위 내용 (자유 텍스트)
    behavior_types: list[str] = field(default_factory=list)  # 행위 유형 (복수)

    # 빈도·기간
    frequency: str = ""                  # "1회", "수회", "매일", "수개월간"
    duration: str = ""                   # "1개월", "6개월", "1년 이상"

    # 증거·상황
    witnesses: bool = False              # 목격자 유무
    evidence: list[str] = field(default_factory=list)  # ["녹음", "문자", "이메일"]
    impact: str = ""                     # 피해 결과

    # 회사 대응
    company_response: str = ""           # "미조치", "조사 중", "가해자 징계"

    # 사업장
    business_size: str = ""              # "5인미만", "5인이상" 등
```

### 2.3 result.py — AssessmentResult

```python
from dataclasses import dataclass, field

from .constants import DISCLAIMER


@dataclass
class ElementAssessment:
    """3요소 개별 판정 결과"""
    element_name: str = ""       # "지위·관계 우위" 등
    status: str = ""             # "해당", "미해당", "불분명"
    score: float = 0.0           # 0.0~1.0
    reasoning: str = ""          # 판정 근거 설명


@dataclass
class AssessmentResult:
    """직장 내 괴롭힘 판정 종합 결과"""
    # 3요소 판정
    element_1_superiority: ElementAssessment = field(default_factory=ElementAssessment)
    element_2_beyond_scope: ElementAssessment = field(default_factory=ElementAssessment)
    element_3_harm: ElementAssessment = field(default_factory=ElementAssessment)

    # 종합 판정
    likelihood: str = ""                # "높음", "보통", "낮음", "비해당"
    overall_score: float = 0.0          # 0.0~1.0
    behavior_types_detected: list[str] = field(default_factory=list)

    # 고객 괴롭힘 여부
    is_customer_harassment: bool = False

    # 법적 근거
    legal_basis: list[str] = field(default_factory=list)

    # 대응 절차
    response_steps: list[dict] = field(default_factory=list)

    # 주의사항
    warnings: list[str] = field(default_factory=list)

    # 면책
    disclaimer: str = DISCLAIMER


def format_assessment(result: AssessmentResult) -> str:
    """AssessmentResult를 사람이 읽기 쉬운 텍스트로 변환"""
    lines = []
    lines.append("=" * 50)
    lines.append("⚖️ 직장 내 괴롭힘 판정 결과")
    lines.append("=" * 50)

    # 고객 괴롭힘인 경우
    if result.is_customer_harassment:
        lines.append("")
        lines.append("→ 직장 내 괴롭힘(근기법 제76조의2)에는 해당하지 않습니다.")
        lines.append("  고객에 의한 괴롭힘은 산업안전보건법 제41조가 적용됩니다.")
        lines.append("")
        for lb in result.legal_basis:
            lines.append(f"  • {lb}")
        lines.append("")
        lines.append(result.disclaimer)
        return "\n".join(lines)

    # 3요소 판정
    status_icon = {"해당": "✅", "미해당": "❌", "불분명": "❓"}

    lines.append("")
    for elem in [result.element_1_superiority, result.element_2_beyond_scope, result.element_3_harm]:
        icon = status_icon.get(elem.status, "❓")
        lines.append(f"  {icon} {elem.element_name}: {elem.status}")
        lines.append(f"     → {elem.reasoning}")
    lines.append("")

    # 종합 판정
    lines.append(f"  → 직장 내 괴롭힘 해당 가능성: {result.likelihood}")
    if result.behavior_types_detected:
        types_str = ", ".join(result.behavior_types_detected)
        lines.append(f"  → 감지된 행위 유형: {types_str}")
    lines.append("")

    # 법적 근거
    if result.legal_basis:
        lines.append("── 관련 법 조문 ──")
        for lb in result.legal_basis:
            lines.append(f"  • {lb}")
        lines.append("")

    # 대응 절차
    if result.response_steps:
        lines.append("── 대응 절차 안내 ──")
        for step in result.response_steps:
            lines.append(f"  {step['step']}단계: {step['title']}")
            lines.append(f"         {step['description']}")
        lines.append("")

    # 주의사항
    if result.warnings:
        lines.append("── ⚠️ 주의사항 ──")
        for w in result.warnings:
            lines.append(f"  • {w}")
        lines.append("")

    lines.append(result.disclaimer)
    return "\n".join(lines)
```

---

## 3. Algorithm Design — assess_harassment()

### 3.1 전체 흐름

```python
def assess_harassment(inp: HarassmentInput) -> AssessmentResult:
    """
    직장 내 괴롭힘 3요소 판정

    1. 고객 괴롭힘 사전 체크 → is_customer_harassment
    2. 요소1: 지위·관계 우위 평가
    3. 요소2: 업무 적정범위 초과 평가
    4. 요소3: 고통·근무환경 악화 평가
    5. 종합 점수 → 가능성 수준 결정
    6. 법적 근거 + 대응 절차 + 주의사항 구성
    """
```

### 3.2 요소1: 지위·관계 우위 평가

```python
def _assess_superiority(inp: HarassmentInput) -> ElementAssessment:
    """
    relationship_type을 SUPERIORITY_SCORES에 매핑하여 점수 산출.
    자유 텍스트(perpetrator_role, victim_role)에서 키워드 매칭으로 보완.

    매핑 로직:
      1. inp.relationship_type이 SUPERIORITY_SCORES에 있으면 직접 사용
      2. 없으면 perpetrator_role/victim_role 키워드로 추론:
         - "팀장/부장/과장/대표/사장/임원" → 상급자/사용자
         - "동기/동료" → 동료
         - "고객/민원인" → 고객
      3. "3명", "여러 명" 등 인원수 키워드 → 다수_소수

    점수 → 상태:
      score >= 0.6 → "해당"
      score >= 0.3 → "불분명"
      score <  0.3 → "미해당"
    """
```

### 3.3 요소2: 업무 적정범위 초과 평가

```python
def _assess_beyond_scope(inp: HarassmentInput) -> ElementAssessment:
    """
    behavior_types를 BEYOND_SCOPE_FACTORS에 매핑.
    복수 유형이면 최대값 사용.
    빈도(FREQUENCY_MULTIPLIER)와 기간(DURATION_MULTIPLIER) 가중.

    최종 점수 = max(유형별 점수) * max(빈도 가중, 기간 가중)
    (빈도/기간 미입력 시 기본 0.5)

    behavior_description에서 BEHAVIOR_TYPE_KEYWORDS로 추가 유형 감지.

    점수 → 상태:
      score >= 0.5 → "해당"
      score >= 0.25 → "불분명"
      score <  0.25 → "미해당"
    """
```

### 3.4 요소3: 고통·근무환경 악화 평가

```python
def _assess_harm(inp: HarassmentInput) -> ElementAssessment:
    """
    impact + behavior_types + behavior_description으로 판정.

    기본 점수: 행위 유형이 1개라도 있으면 0.5 (행위 자체가 고통 유발)
    가산 요인:
      - impact 키워드: "우울증/진단서/병원/퇴사/사직/부서이동/업무배제" → +0.1~0.3
      - 폭행_협박 유형 → +0.3 (신체적 고통 명백)
      - 따돌림_무시 → +0.2 (근무환경 악화 명백)
      - duration >= 3개월 → +0.1

    점수 → 상태:
      score >= 0.5 → "해당"
      score >= 0.3 → "불분명"
      score <  0.3 → "미해당"
    """
```

### 3.5 종합 점수 산출

```python
def _calculate_overall(e1: ElementAssessment, e2: ElementAssessment,
                       e3: ElementAssessment) -> tuple[float, str]:
    """
    종합 점수 = (e1.score * 0.30) + (e2.score * 0.35) + (e3.score * 0.35)

    가중치 근거:
      - 요소1(우위): 30% — 전제 조건이지만, 관계적 우위만으로는 괴롭힘 불성립
      - 요소2(범위초과): 35% — 핵심 판단 요소
      - 요소3(고통/악화): 35% — 핵심 판단 요소

    종합 점수 → 가능성:
      >= 0.65 → "높음"
      >= 0.40 → "보통"
      <  0.40 → "낮음"

    예외: 3요소 모두 "해당"이면 무조건 "높음"
    예외: 요소1이 "미해당"이면 최대 "보통" (우위 관계 없이 괴롭힘 인정 어려움)
    """
```

### 3.6 고객 괴롭힘 분기

```python
def _check_customer_harassment(inp: HarassmentInput) -> bool:
    """
    relationship_type == "고객" 또는
    perpetrator_role에 "고객/민원인/손님/환자/학부모" 키워드 포함 시 True.

    True이면 assess_harassment()에서 조기 반환:
      - is_customer_harassment = True
      - legal_basis = CUSTOMER_HARASSMENT_LEGAL
      - 산안법 제41조 기반 사업주 조치 의무 안내
    """
```

### 3.7 주의사항 생성

```python
def _generate_warnings(inp: HarassmentInput, result: AssessmentResult) -> list[str]:
    """
    상황별 주의사항:
    - 증거 미확보 시: 합법적 녹음 안내 (대화 참여자 녹음은 적법)
    - 1회성 행위: "1회 행위도 괴롭힘 성립 가능하나, 반복 시 입증 용이"
    - 5인 미만 사업장: "제76조의2는 모든 사업장 적용. 단, 제76조의3 조치 의무도 동일 적용."
    - 회사 미조치: "사용자의 조사·조치 의무 위반 시 500만원 이하 과태료 (제116조)"
    - 불리한 처우 발생: "신고 후 해고 등 불이익 시 형사처벌 대상 (제109조)"
    """
```

---

## 4. Chatbot Integration

### 4.1 새 Tool 정의 — HARASSMENT_TOOL

`chatbot.py`와 `pipeline.py`에 추가할 두 번째 tool:

```python
HARASSMENT_TOOL = {
    "name": "harassment_params",
    "description": (
        "직장 내 괴롭힘 관련 질문에서 판정에 필요한 사실관계를 추출합니다. "
        "괴롭힘, 갑질, 폭언, 따돌림, 부당대우 등의 상황 질문이면 "
        "is_harassment_query=true로 설정하고 파라미터를 채우세요."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "is_harassment_query": {
                "type": "boolean",
                "description": "직장 내 괴롭힘 판정이 필요한 질문인지 여부",
            },
            "perpetrator_role": {
                "type": "string",
                "description": "가해자 직위/관계 (팀장, 사장, 동료, 고객 등)",
            },
            "victim_role": {
                "type": "string",
                "description": "피해자 직위/관계 (팀원, 계약직, 신입 등)",
            },
            "relationship_type": {
                "type": "string",
                "description": "관계유형: 상급자/사용자/동료/고객/선임_후임/다수_소수",
            },
            "behavior_description": {
                "type": "string",
                "description": "구체적 행위 내용 (자유 텍스트)",
            },
            "behavior_types": {
                "type": "array",
                "items": {"type": "string"},
                "description": "행위 유형: 폭행_협박/폭언_모욕/따돌림_무시/부당업무/사적용무/감시_통제/부당인사",
            },
            "frequency": {
                "type": "string",
                "description": "빈도: 1회/수회/반복/매일/수개월간",
            },
            "duration": {
                "type": "string",
                "description": "기간: 1회성/1주/1개월/3개월/6개월/1년이상",
            },
            "impact": {
                "type": "string",
                "description": "피해 결과 (우울증, 퇴사, 업무 배제 등)",
            },
            "company_response": {
                "type": "string",
                "description": "회사 대응 상태: 미조치/조사중/가해자징계/불리한처우",
            },
            "business_size": {
                "type": "string",
                "description": "사업장 규모: 5인미만/5인이상",
            },
        },
        "required": ["is_harassment_query"],
    },
}
```

### 4.2 질문 분류 전략 — 2-tool 접근

현재 `extract_calc_params`는 **모든 질문**에 대해 호출된다. 괴롭힘 판정 도구를 추가하면 비용이 2배가 될 수 있으므로, **단일 tool_use 호출**에서 두 가지를 동시에 판별하는 방식을 사용한다:

```python
# chatbot.py — extract_params() (기존 extract_calc_params 대체)
def extract_params(query: str, claude_client) -> dict | None:
    """질문 유형 분류 + 파라미터 추출 (1회 호출로 임금계산 or 괴롭힘 판정 구분)"""
    resp = claude_client.messages.create(
        model=EXTRACT_MODEL,
        max_tokens=512,
        tools=[WAGE_CALC_TOOL, HARASSMENT_TOOL],
        tool_choice={"type": "any"},
        messages=[{
            "role": "user",
            "content": (
                "다음 질문을 분석하세요.\n"
                "- 임금 계산이 필요하면 wage_params 도구를 사용하세요.\n"
                "- 직장 내 괴롭힘/갑질/폭언/따돌림 판정이 필요하면 harassment_params 도구를 사용하세요.\n"
                "- 둘 다 아니면 wage_params에서 needs_calculation=false로 설정하세요.\n\n"
                f"질문: {query}"
            ),
        }],
    )
    for block in resp.content:
        if block.type == "tool_use":
            return {"tool": block.name, **block.input}
    return None
```

### 4.3 run_assessor() — chatbot.py에 추가

```python
def run_assessor(params: dict) -> str | None:
    """추출된 파라미터로 괴롭힘 판정 실행"""
    if not params or not params.get("is_harassment_query"):
        return None

    from harassment_assessor.models import HarassmentInput
    from harassment_assessor.assessor import assess_harassment
    from harassment_assessor.result import format_assessment

    inp = HarassmentInput(
        perpetrator_role=params.get("perpetrator_role", ""),
        victim_role=params.get("victim_role", ""),
        relationship_type=params.get("relationship_type", ""),
        behavior_description=params.get("behavior_description", ""),
        behavior_types=params.get("behavior_types", []),
        frequency=params.get("frequency", ""),
        duration=params.get("duration", ""),
        impact=params.get("impact", ""),
        company_response=params.get("company_response", ""),
        business_size=params.get("business_size", ""),
    )

    result = assess_harassment(inp)
    return format_assessment(result)
```

### 4.4 메인 루프 수정 (chatbot.py)

```python
# 기존: params = extract_calc_params(query, claude_client)
# 변경: params = extract_params(query, claude_client)

# 기존: calc_result = run_calculator(params)
# 변경:
calc_result = None
assessment_result = None

if params:
    tool_name = params.get("tool", "wage_params")
    if tool_name == "wage_params" and params.get("needs_calculation"):
        calc_result = run_calculator(params)
    elif tool_name == "harassment_params" and params.get("is_harassment_query"):
        assessment_result = run_assessor(params)

# Claude 호출 시 context에 assessment_result도 포함
```

### 4.5 pipeline.py 동일 적용

`pipeline.py`의 `_extract_calc_params`, `_run_calculator`, `process_question`도 동일한 패턴으로 수정.

---

## 5. Output Format Examples

### 5.1 시나리오 1: 팀장이 팀원에게 매일 욕설 + 업무 배제

```
==================================================
⚖️ 직장 내 괴롭힘 판정 결과
==================================================

  ✅ ① 지위·관계 우위: 해당
     → 팀장→팀원: 직급상 상위자로서 지위 우위 인정

  ✅ ② 업무 적정범위 초과: 해당
     → 욕설(폭언·모욕)과 업무 배제는 업무상 적정 범위를 명백히 초과

  ✅ ③ 고통·근무환경 악화: 해당
     → 매일 반복되는 폭언으로 인한 정신적 고통 및 업무 배제로 근무환경 악화

  → 직장 내 괴롭힘 해당 가능성: 높음
  → 감지된 행위 유형: 폭언·모욕, 부당업무

── 관련 법 조문 ──
  • 근로기준법 제76조의2 (직장 내 괴롭힘의 금지)
  • 근로기준법 제76조의3 (직장 내 괴롭힘 발생 시 조치)

── 대응 절차 안내 ──
  1단계: 증거 확보 — 녹음, 문자·메신저 캡처, 목격자 확인 등
  2단계: 사내 신고 — 인사부서 또는 괴롭힘 고충처리위원회에 서면 신고
  3단계: 회사 조사·조치 — 사용자는 지체 없이 조사 실시 의무
  4단계: 노동청 진정 — 회사 미조치 시 1350 전화
  5단계: 불리한 처우 시 형사고소 — 제109조 제2항

⚠️ 본 판정은 법적 효력이 없는 참고 정보입니다. ...
```

### 5.2 시나리오 5: 고객 폭언

```
==================================================
⚖️ 직장 내 괴롭힘 판정 결과
==================================================

→ 직장 내 괴롭힘(근기법 제76조의2)에는 해당하지 않습니다.
  고객에 의한 괴롭힘은 산업안전보건법 제41조가 적용됩니다.

  • 산업안전보건법 제41조 (고객의 폭언 등으로 인한 건강장해 예방조치)

⚠️ 본 판정은 법적 효력이 없는 참고 정보입니다. ...
```

---

## 6. SYSTEM_PROMPT 수정

chatbot.py와 pipeline.py의 SYSTEM_PROMPT에 괴롭힘 판정 관련 규칙 추가:

```
기존 규칙 1 뒤에 추가:

1-2. **괴롭힘 판정 결과가 포함된 경우**:
   - 판정 결과의 3요소 평가와 가능성 수준을 그대로 사용하세요.
   - 각 요소별 판정 근거를 사용자의 상황에 맞게 풀어서 설명하세요.
   - 대응 절차 안내를 반드시 포함하세요.
   - 면책 문구를 답변 끝에 반드시 포함하세요.
```

---

## 7. Test Specifications

| # | 입력 | 기대 결과 |
|---|------|----------|
| 1 | perpetrator="팀장", victim="팀원", types=["폭언_모욕", "부당업무"], freq="매일" | likelihood="높음", 3요소 모두 "해당" |
| 2 | perpetrator="동료", victim="동료", types=["폭언_모욕"], freq="1회" | likelihood="낮음", 요소1="불분명" |
| 3 | perpetrator="사장", types=["사적용무"], freq="반복" | likelihood="높음", 요소1/2 "해당" |
| 4 | perpetrator="선배", victim="후배", types=["부당업무"], behavior_desc="업무상 엄격한 지도" | likelihood="낮음", 요소2="불분명" |
| 5 | relationship_type="고객", types=["폭언_모욕"] | is_customer_harassment=True |
| 6 | perpetrator="사장", types=["폭언_모욕"], business_size="5인미만" | likelihood="높음", warning에 5인미만 안내 |
| 7 | relationship_type="다수_소수", types=["따돌림_무시"], duration="6개월" | likelihood="높음" |

---

## 8. Implementation Order

| 순서 | 파일 | 작업 내용 | 예상 LoC |
|------|------|----------|---------|
| 1 | `harassment_assessor/constants.py` | 키워드, 점수표, 법 조문, 절차, 면책 | ~90 |
| 2 | `harassment_assessor/models.py` | Enum 4개 + HarassmentInput dataclass | ~70 |
| 3 | `harassment_assessor/result.py` | ElementAssessment + AssessmentResult + format_assessment() | ~100 |
| 4 | `harassment_assessor/assessor.py` | assess_harassment() + 4개 내부 함수 | ~220 |
| 5 | `harassment_assessor/__init__.py` | Public API exports | ~15 |
| 6 | `chatbot.py` | HARASSMENT_TOOL + extract_params() 리팩터 + run_assessor() + 루프 수정 | ~60 |
| 7 | `app/core/pipeline.py` | 동일 패턴 적용 (HARASSMENT_TOOL + 분기 로직) | ~40 |

**총 예상: ~595 LoC** (신규 ~495 + 수정 ~100)

---

## 9. File Impact Matrix

| File | Action | Changes |
|------|--------|---------|
| `harassment_assessor/constants.py` | NEW | ~90 lines |
| `harassment_assessor/models.py` | NEW | ~70 lines |
| `harassment_assessor/result.py` | NEW | ~100 lines |
| `harassment_assessor/assessor.py` | NEW | ~220 lines |
| `harassment_assessor/__init__.py` | NEW | ~15 lines |
| `chatbot.py` | MODIFY | +60 lines (HARASSMENT_TOOL, extract_params 리팩터, run_assessor, 루프 수정) |
| `app/core/pipeline.py` | MODIFY | +40 lines (동일 패턴) |
| **Total** | | **~595 lines** |
