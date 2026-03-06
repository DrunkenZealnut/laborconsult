# Plan: AI 노동상담 챗봇 — 계산기 + RAG 통합

## Executive Summary

| 관점 | 내용 |
|------|------|
| **Problem** | 현재 chatbot.py는 RAG(벡터 검색+Claude 답변)만 제공하고, wage_calculator의 19개 계산기는 CLI에서만 사용 가능. 사용자가 "월급 250만원인데 연장수당 얼마예요?"라고 물어도 검색 결과를 인용할 뿐 실제 계산을 수행하지 못함. from_analysis()가 존재하지만 자연어 → WageInput 변환이 빈약(6개 필드만 매핑). |
| **Solution** | Claude를 의미/맥락 분석 엔진으로 사용하여 자연어 질문에서 WageInput 53필드를 구조화 추출 → wage_calculator로 정밀 계산 수행 → 계산 결과 + RAG 참고 문서를 결합하여 근거 있는 답변 생성. 웹 UI(Next.js 또는 FastAPI+HTML)로 서비스화. |
| **Function UX Effect** | 사용자가 자연어로 질문하면 (1) 계산 가능 여부 자동 판단 (2) 부족 정보 추가 질문 (3) 정밀 계산 + 법적 근거 + 유사 사례 통합 답변. CLI에서 웹으로 전환하여 비전문가도 접근 가능. |
| **Core Value** | 노동법 지식(RAG) × 정밀 계산(wage_calculator) × AI 맥락 분석(Claude)의 3축 통합으로, 단순 검색 챗봇 대비 실질적 문제 해결 능력 확보 |

---

## 1. 현황 분석

### 1.1 보유 자산

| 자산 | 상태 | 설명 |
|------|------|------|
| wage_calculator | 19개 계산기, 36 테스트 통과 | 통상임금~탄력근무까지 포괄. 최근 리팩토링 완료 (BaseCalculatorResult, 디스패처 패턴) |
| chatbot.py (RAG) | Pinecone + Claude 스트리밍 | 274 BEST Q&A 벡터 DB. 검색→답변 파이프라인 동작 중 |
| from_analysis() | facade.py:322 | 자연어 분석 결과 → WageInput → 계산. 6개 필드만 매핑 (임금형태/임금액/사업장규모/근무기간) |
| analyze_qna.py | Haiku 배치 분석기 | 10,000건 Q&A 구조화 분석 경험. provided_info/calculation_type 추출 프롬프트 검증됨 |
| compare_calculator.py | 계산기 vs 실제 답변 비교 | 100건 층화 샘플링 검증 인프라 |
| Q&A 10,000건 분석 데이터 | analysis_qna.jsonl | question_type, provided_info, missing_info, calculation_type 포함 |

### 1.2 아키텍처 현황

```
[현재] 두 시스템이 분리되어 운영:

사용자 → chatbot.py → Pinecone 검색 → Claude RAG 답변 (법률 지식만)
                                                     ↑ 계산 없음

사용자 → wage_calculator_cli.py → WageInput 수동 구성 → 정밀 계산 (전문가 전용)
                                  ↑ 자연어 불가
```

### 1.3 핵심 Gap

| Gap | 현재 | 목표 |
|-----|------|------|
| 자연어 → 구조화 데이터 | from_analysis()에서 6필드만 추출 | Claude가 53필드 전체를 문맥 기반 추출 |
| 부족 정보 처리 | 무시하고 None 반환 | 대화형 추가 질문으로 수집 |
| 계산+지식 통합 | 별개 시스템 | 계산 결과에 법적 근거+유사 사례 결합 |
| 접근성 | CLI only | 웹 UI (비전문가 접근 가능) |

---

## 2. 시스템 설계 개요

### 2.1 목표 아키텍처

```
사용자 (웹 UI)
  │
  ▼
[API 서버 (FastAPI)]
  │
  ├─① 의도 분석 (Claude) ───────────────────────────┐
  │   "이 질문이 계산을 필요로 하는가?"               │
  │   → calculation_needed: bool                     │
  │   → calculation_type: str                        │
  │   → extracted_info: dict (WageInput 필드)         │
  │   → missing_info: list (추가 질문 필요 항목)      │
  │                                                   │
  ├─② 정보 수집 (대화형)                              │
  │   missing_info가 있으면 사용자에게 추가 질문       │
  │   "임금 형태(시급/월급/연봉)가 어떻게 되시나요?"   │
  │                                                   │
  ├─③ 계산 실행 (wage_calculator)                     │
  │   extracted_info → WageInput → calculate()        │
  │   → WageResult (breakdown, formulas, warnings)    │
  │                                                   │
  ├─④ RAG 검색 (Pinecone)                            │
  │   질문 + 계산 유형으로 유사 사례 검색              │
  │                                                   │
  └─⑤ 통합 답변 생성 (Claude)                        │
      계산 결과 + RAG 컨텍스트 + 법적 근거             │
      → 구조화된 최종 답변                             │
```

### 2.2 핵심 컴포넌트

| 컴포넌트 | 역할 | 기술 |
|----------|------|------|
| **Intent Analyzer** | 자연어 → 의도/데이터 추출 | Claude API (tool_use) |
| **Info Collector** | 부족 정보 대화형 수집 | 상태 관리 + 추가 질문 생성 |
| **Calc Engine** | WageInput → WageResult | wage_calculator (기존) |
| **RAG Search** | 유사 사례/법적 근거 검색 | Pinecone + OpenAI embed |
| **Answer Composer** | 계산+RAG+법률 통합 답변 | Claude API (스트리밍) |
| **Web UI** | 대화형 인터페이스 | Next.js 또는 FastAPI + Jinja2 |
| **Session Manager** | 대화 상태/히스토리 관리 | Redis 또는 인메모리 |

---

## 3. Intent Analyzer 설계 (핵심)

### 3.1 Claude Tool Use 기반 구조화 추출

```python
# Claude에게 제공할 tool 정의
tools = [{
    "name": "analyze_labor_question",
    "description": "노동상담 질문을 분석하여 계산기 입력 데이터를 추출",
    "input_schema": {
        "type": "object",
        "properties": {
            "requires_calculation": {"type": "boolean"},
            "calculation_type": {
                "type": "string",
                "enum": ["overtime", "minimum_wage", "weekly_holiday",
                         "annual_leave", "dismissal", "severance",
                         "unemployment", "insurance", "comprehensive",
                         "parental_leave", "maternity_leave", "prorated",
                         "wage_arrears", "flexible_work", "none"]
            },
            "wage_type": {"type": "string", "enum": ["시급", "일급", "월급", "연봉", "포괄임금제"]},
            "wage_amount": {"type": "number"},
            "business_size": {"type": "string"},
            "weekly_work_days": {"type": "integer"},
            "daily_work_hours": {"type": "number"},
            "weekly_overtime_hours": {"type": "number"},
            "weekly_night_hours": {"type": "number"},
            "start_date": {"type": "string"},
            # ... 53필드 중 질문에서 추출 가능한 것들
            "missing_info": {
                "type": "array",
                "items": {"type": "string"},
                "description": "계산에 필요하지만 질문에서 확인할 수 없는 정보"
            },
            "question_summary": {"type": "string"}
        }
    }
}]
```

### 3.2 맥락 기반 추론 규칙

| 상황 | 추론 | 예시 |
|------|------|------|
| "최저임금 이하" 언급 | minimum_wage 계산 필요 | "시급 9000원인데 최저임금 위반 아닌가요?" |
| "연장근무", "야근" 언급 | overtime 계산 + 시간 추출 | "주 5일 하루 10시간 근무하는데 수당이 안 나와요" |
| "퇴직", "퇴사" 언급 | severance 계산 + 기간 추출 | "3년 근무 후 퇴직하는데 퇴직금 얼마인가요?" |
| 임금 금액 없이 질문 | missing_info에 "임금액" 추가 | "연장수당이 적게 나오는 것 같아요" |
| "5인 미만" 직접 언급 | business_size = UNDER_5 | "직원 3명인 가게에서 일하는데..." |
| 복수 계산 유형 | targets 복수 지정 | "퇴직금이랑 연차수당 같이 계산해주세요" |

### 3.3 부족 정보 수집 전략

**우선순위별 필수 정보 (계산 유형에 따라 동적)**:

| 계산 유형 | 필수 정보 | 선택 정보 |
|-----------|----------|----------|
| overtime | 임금형태, 임금액, 주당 연장시간, 사업장규모 | 야간시간, 휴일시간 |
| severance | 임금형태, 임금액, 근무시작일, 퇴직일 | 고정수당 내역 |
| minimum_wage | 임금형태, 임금액, 주당 근무일/시간 | 수당 포함 여부 |
| weekly_holiday | 임금형태, 임금액, 주당 근무일/시간 | - |
| annual_leave | 근무시작일 | 연차 사용일수 |

**추가 질문 패턴**:
```
"계산을 위해 몇 가지 정보가 더 필요합니다:
1. 임금 형태가 시급/월급/연봉 중 어떤 것인가요?
2. 현재 받고 계신 임금은 얼마인가요?
(대략적인 금액이라도 괜찮습니다)"
```

---

## 4. 답변 생성 설계

### 4.1 통합 답변 구조

```
┌─────────────────────────────────────────┐
│ 📊 계산 결과                             │
│ ─────────────────────────────────        │
│ 통상시급: 12,019원                       │
│ 연장수당(월): 390,620원                  │
│ 야간수당(월): 60,095원                   │
│ 합계(월): 450,715원                     │
│                                          │
│ 📋 산출 근거                             │
│ ─────────────────────────────────        │
│ • 통상시급 = 2,500,000원 ÷ 209h         │
│ • 연장수당 = 12,019원 × 10h × 1.5 × 4.345│
│                                          │
│ ⚖️ 법적 근거                             │
│ ─────────────────────────────────        │
│ • 근로기준법 제56조 (연장·야간·휴일 근로)  │
│                                          │
│ 📚 참고 사례                             │
│ ─────────────────────────────────        │
│ • [유사 Q&A 1] www.nodong.kr/qna/...    │
│ • [유사 Q&A 2] www.nodong.kr/qna/...    │
│                                          │
│ ⚠️ 주의사항                              │
│ • 고정수당이 있는 경우 통상임금에 포함될   │
│   수 있어 결과가 달라질 수 있습니다        │
│ • 법적 조언이 아닌 참고 정보입니다         │
└─────────────────────────────────────────┘
```

### 4.2 답변 유형별 처리

| 질문 유형 | 처리 흐름 |
|-----------|----------|
| **계산 가능** (정보 충분) | 즉시 계산 → 결과 + RAG + 법률 근거 |
| **계산 가능** (정보 부족) | 추가 질문 → 수집 후 계산 → 통합 답변 |
| **계산 불필요** (법률 해석) | RAG 검색 → Claude 답변 (기존 chatbot 방식) |
| **복합 질문** | 복수 계산 + RAG → 각각 결과 병합 |

---

## 5. 기술 스택

### 5.1 백엔드

| 기술 | 용도 | 이유 |
|------|------|------|
| **FastAPI** | API 서버 | async 지원, 스트리밍 SSE 네이티브, Python 생태계 호환 |
| **Claude API** (tool_use) | 의도 분석 + 답변 생성 | 구조화 추출에 최적, 한국어 이해도 높음 |
| **OpenAI Embedding** | 벡터 검색 | 기존 Pinecone 인프라 호환 |
| **Pinecone** | 벡터 DB | 이미 274 BEST Q&A + 10K Q&A 인덱싱 완료 |
| **wage_calculator** | 계산 엔진 | 19개 계산기, 36 테스트 검증 완료 |

### 5.2 프론트엔드

| 기술 | 용도 | 이유 |
|------|------|------|
| **Next.js 14+ (App Router)** | 웹 UI | SSR/SSE 지원, React 생태계 |
| **Tailwind CSS** | 스타일링 | 빠른 프로토타이핑 |
| **shadcn/ui** | UI 컴포넌트 | 커스터마이징 가능한 컴포넌트 |

> 대안: 초기에는 FastAPI + Jinja2 단일 서버로 시작하고, 이후 Next.js로 분리 가능

### 5.3 인프라

| 기술 | 용도 |
|------|------|
| **Vercel** 또는 **Railway** | 배포 |
| **Redis** (선택) | 세션/대화 히스토리 |
| **.env** | API 키 관리 (OPENAI, PINECONE, ANTHROPIC) |

---

## 6. 구현 범위 (Phase 분리)

### Phase 1: 핵심 파이프라인 (MVP)
- Intent Analyzer (Claude tool_use로 질문 분석)
- WageInput 변환 강화 (_provided_info_to_input 53필드 매핑)
- 계산 + RAG 통합 답변 생성
- FastAPI 서버 + 기본 HTML UI
- **목표**: 자연어 → 계산 → 답변 E2E 동작

### Phase 2: 대화형 정보 수집
- 부족 정보 감지 → 추가 질문 생성
- 세션 상태 관리 (multi-turn 대화)
- 대화 히스토리 표시
- **목표**: "임금 형태가 뭔가요?" 같은 후속 질문

### Phase 3: 웹 UI 고도화
- Next.js SPA (채팅 UI, 스트리밍 답변)
- 계산 결과 시각화 (차트, 표)
- 모바일 반응형
- **목표**: 비전문가가 쉽게 사용 가능한 UI

### Phase 4: 데이터 강화
- 10,000건 Q&A 인덱싱 추가 (기존 274 BEST + 확장)
- 계산 결과 캐싱
- 사용자 피드백 수집
- **목표**: 검색 정확도 및 답변 품질 향상

---

## 7. 범위 외 (명시적 제외)

| 제외 항목 | 이유 |
|-----------|------|
| 사용자 인증/로그인 | MVP에 불필요, 추후 필요 시 추가 |
| 결제 시스템 | 무료 서비스로 시작 |
| 관리자 대시보드 | 초기에는 로그로 모니터링 |
| 모바일 앱 (네이티브) | 웹 반응형으로 충분 |
| 법률 상담 면책 시스템 | 면책 문구로 대체 |
| WageInput 53필드 분리/재설계 | 기존 구조 그대로 활용 |

---

## 8. 성공 기준

| 기준 | 목표 |
|------|------|
| 계산 정확도 | compare_calculator.py 기준 일치율 ≥80% |
| 정보 추출 정확도 | Claude tool_use에서 필드 추출 정확도 ≥90% |
| 응답 시간 | 계산 포함 답변 5초 이내 |
| 대화 완료율 | 추가 질문 후 계산 완료 비율 ≥70% |
| 사용자 만족도 | 면책 문구 포함 답변에 대한 유용성 평가 |

---

## 9. 리스크

| 리스크 | 영향 | 대응 |
|--------|------|------|
| Claude tool_use 추출 정확도 부족 | 잘못된 계산 결과 | 핵심 필드(임금액, 시간) 추출 검증 로직 추가 |
| API 비용 급증 | 운영 비용 | Haiku 모델 사용 (의도 분석), Sonnet (답변 생성) 분리 |
| 자연어 모호성 | "주 52시간" = 법정+연장? 소정만? | 모호 시 추가 질문으로 확인 |
| 법률 변경 미반영 | 오래된 답변 | RAG 데이터 정기 업데이트 + constants.py 연도별 관리 |
| 동시 사용자 급증 | 서버 부하 | Rate limiting + 큐 기반 처리 |

---

## 10. 구현 순서 (이번 PDCA)

| 순서 | 작업 | 예상 파일 | 검증 |
|------|------|----------|------|
| 1 | Intent Analyzer 모듈 (Claude tool_use) | `app/analyzer.py` | 샘플 질문 10개 추출 정확도 |
| 2 | WageInput 변환 강화 | `app/converter.py` + facade.py 연동 | 기존 36 테스트 + 신규 변환 테스트 |
| 3 | 계산 + RAG 통합 파이프라인 | `app/pipeline.py` | E2E 테스트 (질문→답변) |
| 4 | FastAPI 서버 | `app/main.py`, `app/routes.py` | /chat API 동작 |
| 5 | 기본 웹 UI (HTML+JS) | `app/static/`, `app/templates/` | 브라우저 접속 + 대화 |
| 6 | 부족 정보 수집 (multi-turn) | `app/session.py` | 추가 질문 시나리오 테스트 |
| 7 | 스트리밍 답변 (SSE) | `app/routes.py` 수정 | 실시간 답변 스트리밍 |
| 8 | 테스트 + 배포 준비 | 통합 테스트 | 10개 대표 시나리오 통과 |
