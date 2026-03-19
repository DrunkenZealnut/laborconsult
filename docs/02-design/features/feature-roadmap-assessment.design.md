# Feature Roadmap Assessment — Design Document

> Plan 참조: `docs/01-plan/features/feature-roadmap-assessment.plan.md`

---

## 1. 설계 범위

Plan의 FR-01~FR-10 중 **배포 전 권장 (Priority 2)** 4개 기능을 상세 설계한다.

| FR | 기능 | 설계 섹션 |
|----|------|:---------:|
| FR-01 | E2E 통합 테스트 | §2 |
| FR-02 | 계산기 정확도 교차검증 | §3 |
| FR-03 | API 에러 핸들링 강화 | §4 |
| FR-04 | 환경변수·시크릿 관리 | §5 |

Priority 3~4 (FR-05~FR-10)은 런칭 후 별도 PDCA 사이클로 진행.

---

## 2. FR-01: E2E 통합 테스트

### 2.1 목적

웹 UI → API 서버 → 파이프라인 → 계산기 → 응답까지 전체 흐름이 정상 동작하는지 검증.

### 2.2 테스트 시나리오

| # | 시나리오 | 엔드포인트 | 검증 항목 |
|:-:|---------|-----------|----------|
| T-01 | 단순 노동법 질문 | `GET /api/chat/stream` | SSE 스트리밍, Claude 응답 포함 |
| T-02 | 임금계산 요청 | `GET /api/chat/stream` | calc_result 포함, 금액 > 0 |
| T-03 | 파일 첨부 질문 | `POST /api/chat/stream` | 첨부 파싱 성공, 응답 반환 |
| T-04 | 동기 채팅 | `POST /api/chat` | JSON 응답, message 필드 존재 |
| T-05 | 헬스체크 | `GET /api/health` | `{"status": "ok"}` |
| T-06 | 관리자 로그인 | `POST /api/admin/login` | JWT 토큰 반환 |
| T-07 | 관리자 통계 | `GET /api/admin/stats` | 인증 필요, 데이터 반환 |
| T-08 | 잘못된 입력 | `POST /api/chat` | 422 또는 에러 메시지 |

### 2.3 구현 방식

**수동 테스트 스크립트** (`test_e2e.py`):

```python
# 파일: test_e2e.py
# 로컬 서버 (uvicorn) 기동 후 실행
# 의존성: requests (requirements.txt에 이미 포함)

import requests
import json

BASE_URL = "http://localhost:5555"

def test_health():
    r = requests.get(f"{BASE_URL}/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

def test_chat_sync():
    r = requests.post(f"{BASE_URL}/api/chat", json={
        "message": "최저임금이 얼마인가요?"
    })
    assert r.status_code == 200
    assert "message" in r.json()

def test_chat_stream():
    r = requests.get(f"{BASE_URL}/api/chat/stream",
                     params={"message": "퇴직금 계산해주세요"},
                     stream=True)
    assert r.status_code == 200
    events = []
    for line in r.iter_lines(decode_unicode=True):
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    assert len(events) >= 2  # session + chunk(s)

def test_invalid_input():
    r = requests.post(f"{BASE_URL}/api/chat", json={})
    assert r.status_code == 422

def test_admin_login():
    r = requests.post(f"{BASE_URL}/api/admin/login", json={
        "password": "wrong"
    })
    assert r.status_code == 401
```

### 2.4 산출물

| 산출물 | 경로 |
|--------|------|
| E2E 테스트 스크립트 | `test_e2e.py` |

---

## 3. FR-02: 계산기 정확도 교차검증

### 3.1 목적

감사 문서(`docs/calculator-audit/`)의 계산 예시와 실제 계산기 출력을 자동 비교.

### 3.2 설계

기존 `wage_calculator_cli.py` (32 케이스)에 **감사 문서 기반 추가 검증** 로직 추가:

```
감사 문서 예시 → 입력값 추출 → WageCalculator.calculate() → 예상 결과 비교
```

### 3.3 검증 대상 (우선순위)

| 계산기 | 감사 시트 | 검증 포인트 |
|--------|----------|------------|
| 통상임금 | 01-ordinary-wage | 시급, 일급, 월급 환산 |
| 퇴직금 | 07-severance | 평균임금 유리 원칙 적용 |
| 4대보험 | 13-insurance | 보험료율 × 과세표준 |
| 연차수당 | 05-annual-leave | 1년 미만/이상 발생일수 |
| 최저임금 | 03-minimum-wage | 산입범위 계산 |

### 3.4 구현 방식

`calculator_batch_test.py`가 이미 존재 (32 케이스). 감사 문서 예시를 추가 케이스로 확장:

```python
# calculator_batch_test.py에 AUDIT_CASES 추가
AUDIT_CASES = [
    {
        "name": "감사문서-통상임금-예시1",
        "input": {"monthly_salary": 3_000_000, "weekly_hours": 40, ...},
        "expected": {"hourly_wage": 14354, ...},  # 감사 시트 값
        "source": "01-ordinary-wage.audit.md §7"
    },
    ...
]
```

### 3.5 산출물

| 산출물 | 경로 |
|--------|------|
| 추가 테스트 케이스 | `calculator_batch_test.py` (AUDIT_CASES 추가) |

---

## 4. FR-03: API 에러 핸들링 강화

### 4.1 현재 상태

`api/index.py` 현재 에러 처리:
- 파일 첨부 검증: `FileValidationError` 캐치 → SSE error 이벤트 (L121-126)
- 관리자 API: `HTTPException` 401/403/404/503 (L163-173)
- Pydantic 검증: FastAPI 기본 422 응답

### 4.2 개선 영역

| # | 현재 문제 | 개선안 |
|:-:|---------|--------|
| E-01 | process_question 내부 예외 시 SSE 끊김 | try/except로 감싸서 error 이벤트 전송 |
| E-02 | 환경변수 누락 시 500 에러 (스택트레이스 노출) | 시작 시 검증, 친절한 메시지 |
| E-03 | Pinecone/OpenAI 타임아웃 시 무응답 | 타임아웃 에러 캐치 → 안내 메시지 |
| E-04 | 422 에러가 영어 (FastAPI 기본) | 한국어 에러 메시지 커스텀 |

### 4.3 구현 설계

#### E-01: SSE 스트리밍 에러 보호

```python
# api/index.py — chat_stream 내 event_generator()
def event_generator():
    yield f"data: {json.dumps({'type': 'session', 'session_id': session.id})}\n\n"
    try:
        for event in process_question(message, session, config):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    except Exception as e:
        error_msg = "죄송합니다. 답변 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
        yield f"data: {json.dumps({'type': 'error', 'text': error_msg}, ensure_ascii=False)}\n\n"
```

#### E-02: 환경변수 시작 시 검증

```python
# app/config.py — from_env() 내부
REQUIRED_KEYS = ["OPENAI_API_KEY", "PINECONE_API_KEY", "ANTHROPIC_API_KEY"]

@classmethod
def from_env(cls) -> "AppConfig":
    missing = [k for k in REQUIRED_KEYS if not os.environ.get(k)]
    if missing:
        raise EnvironmentError(
            f"필수 환경변수가 설정되지 않았습니다: {', '.join(missing)}\n"
            f".env 파일 또는 Vercel 환경변수를 확인하세요."
        )
    ...
```

#### E-03: 외부 API 타임아웃 핸들링

```python
# app/core/pipeline.py — process_question() 내부
try:
    results = pinecone_index.query(...)
except Exception:
    yield {"type": "chunk", "text": "검색 서비스에 일시적 오류가 발생했습니다. 잠시 후 다시 시도해주세요."}
    return
```

#### E-04: 한국어 Validation 에러

```python
# api/index.py — FastAPI 앱에 추가
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    return JSONResponse(
        status_code=422,
        content={"detail": "입력 데이터가 올바르지 않습니다. 메시지를 확인해주세요."}
    )
```

### 4.4 수정 대상 파일

| 파일 | 수정 내용 |
|------|----------|
| `api/index.py` | E-01 try/except, E-04 validation handler |
| `app/config.py` | E-02 환경변수 검증 |
| `app/core/pipeline.py` | E-03 외부 API 에러 핸들링 |

---

## 5. FR-04: 환경변수·시크릿 관리

### 5.1 현재 환경변수 목록

`.env.example` 기준:

| 변수 | 필수 | 용도 |
|------|:----:|------|
| `OPENAI_API_KEY` | ✅ | 임베딩 생성 |
| `PINECONE_API_KEY` | ✅ | 벡터 DB |
| `ANTHROPIC_API_KEY` | ✅ | Claude 응답 |
| `PINECONE_INDEX_NAME` | - | 인덱스명 (기본: laborconsult-bestqna) |
| `GEMINI_API_KEY` | - | 폴백 LLM |
| `SUPABASE_URL` | - | QA 저장 |
| `SUPABASE_KEY` | - | QA 저장 |
| `LAW_API_KEY` | - | 법제처 API |
| `ADMIN_PASSWORD` | - | 관리자 로그인 |
| `ADMIN_JWT_SECRET` | - | JWT 서명 (미설정 시 ADMIN_PASSWORD 사용) |

### 5.2 개선 설계

#### 5.2.1 환경변수 검증 스크립트

```python
# check_env.py — 배포 전 검증용
import os
from dotenv import load_dotenv

load_dotenv()

REQUIRED = ["OPENAI_API_KEY", "PINECONE_API_KEY", "ANTHROPIC_API_KEY"]
OPTIONAL = ["GEMINI_API_KEY", "SUPABASE_URL", "SUPABASE_KEY",
            "LAW_API_KEY", "ADMIN_PASSWORD", "ADMIN_JWT_SECRET"]

print("=== 환경변수 검증 ===")
ok = True
for key in REQUIRED:
    val = os.environ.get(key, "")
    if not val:
        print(f"  ❌ {key}: 미설정 (필수)")
        ok = False
    else:
        print(f"  ✅ {key}: 설정됨 ({val[:8]}...)")

for key in OPTIONAL:
    val = os.environ.get(key, "")
    status = "설정됨" if val else "미설정 (선택)"
    symbol = "✅" if val else "⚠️"
    print(f"  {symbol} {key}: {status}")

if not ok:
    print("\n⚠️  필수 환경변수가 누락되었습니다!")
    exit(1)
print("\n✅ 모든 필수 환경변수 확인 완료")
```

#### 5.2.2 Vercel 배포 체크리스트

`.env.example`에 Vercel 설정 안내 추가:

```
# Vercel 배포 시: Settings → Environment Variables에 추가
# 1. OPENAI_API_KEY (필수)
# 2. PINECONE_API_KEY (필수)
# 3. ANTHROPIC_API_KEY (필수)
# 4. SUPABASE_URL + SUPABASE_KEY (QA 저장 기능 사용 시)
# 5. ADMIN_PASSWORD (관리자 페이지 사용 시)
```

### 5.3 산출물

| 산출물 | 경로 |
|--------|------|
| 환경변수 검증 스크립트 | `check_env.py` |
| .env.example 업데이트 | `.env.example` (Vercel 안내 추가) |

---

## 6. 구현 순서

```
Step 1: FR-03 API 에러 핸들링 (기존 파일 수정 3개)
  ├── api/index.py — try/except + validation handler
  ├── app/config.py — 환경변수 검증
  └── app/core/pipeline.py — 외부 API 에러

Step 2: FR-04 환경변수 관리 (신규 파일 1개 + 수정 1개)
  ├── check_env.py — 검증 스크립트 생성
  └── .env.example — Vercel 안내 추가

Step 3: FR-01 E2E 테스트 (신규 파일 1개)
  └── test_e2e.py — 통합 테스트 스크립트

Step 4: FR-02 교차검증 (기존 파일 수정 1개)
  └── calculator_batch_test.py — AUDIT_CASES 추가
```

---

## 7. 수정 파일 요약

| 파일 | 작업 | FR |
|------|:----:|:--:|
| `api/index.py` | 수정 | FR-03 |
| `app/config.py` | 수정 | FR-03 |
| `app/core/pipeline.py` | 수정 | FR-03 |
| `check_env.py` | 신규 | FR-04 |
| `.env.example` | 수정 | FR-04 |
| `test_e2e.py` | 신규 | FR-01 |
| `calculator_batch_test.py` | 수정 | FR-02 |

총 수정: 4개 파일, 신규: 2개 파일, 총 6개 파일 변경

---

## 8. NFR (비기능 요구사항)

| NFR | 기준 |
|-----|------|
| NFR-01 에러 메시지 한국어 | 모든 사용자 대면 에러는 한국어 |
| NFR-02 스택트레이스 미노출 | 프로덕션에서 내부 에러 상세 숨김 |
| NFR-03 테스트 독립성 | test_e2e.py는 로컬 서버 기동 후 독립 실행 |
| NFR-04 기존 동작 보존 | 에러 핸들링 추가가 정상 흐름에 영향 없음 |

---

## 9. Gap Analysis 기준

| 항목 | 기준 | 비중 |
|------|------|:----:|
| 파일 완성도 | 6개 파일 모두 존재 | 30% |
| FR 구현율 | FR-01~FR-04 각 요구사항 충족 | 40% |
| NFR 준수 | NFR-01~NFR-04 충족 | 20% |
| 기존 동작 보존 | 기존 API·계산기 정상 동작 | 10% |

---

*작성일: 2026-03-08 | Plan 참조: feature-roadmap-assessment.plan.md*
