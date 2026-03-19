# Conversation Memory (대화 맥락 유지) Design Document

> **Summary**: 3계층 메모리 아키텍처로 세션 영속화, 계산 캐싱, 대화 요약을 구현하여 맥락 참조 질문을 자연스럽게 지원
>
> **Project**: laborconsult (nodong.kr)
> **Version**: 1.0
> **Author**: Claude
> **Date**: 2026-03-13
> **Status**: Draft
> **Planning Doc**: [conversation-memory.plan.md](../01-plan/features/conversation-memory.plan.md)

---

## 1. Overview

### 1.1 Design Goals

1. **세션 영속화**: 페이지 새로고침, Vercel cold start 후에도 대화 맥락 복원
2. **계산 결과 재활용**: 이전 계산의 `extracted_info`를 후속 계산에 자동 프리필
3. **토큰 효율성**: 오래된 대화를 구조화 요약으로 압축하여 Claude API 토큰 절약
4. **하위 호환**: 기존 API 인터페이스(`ChatRequest`, SSE 이벤트)에 변경 없음

### 1.2 Design Principles

- **Graceful Degradation**: 모든 영속 레이어 실패 시 기존 동작(새 세션)으로 fallback
- **Opt-in Complexity**: Supabase 영속 저장은 선택적 — 환경 변수 없으면 인메모리만 동작
- **최소 변경**: 기존 `Session`, `pipeline.py`, `analyzer.py` 인터페이스 유지, 내부 확장만

---

## 2. Architecture

### 2.1 3계층 메모리 아키텍처

```
┌──────────────────────────────────────────────────────────────┐
│ Layer 1: Frontend (sessionStorage)                           │
│                                                              │
│  sessionStorage.setItem('sessionId', id)                     │
│  페이지 로드 시 복원 → 서버 요청에 session_id 포함           │
│  탭 닫으면 자동 정리, 새로고침에는 유지                      │
├──────────────────────────────────────────────────────────────┤
│ Layer 2: Server Session (in-memory + condensation)           │
│                                                              │
│  Session.history     : 최근 6턴 원문 유지 (기존)             │
│  Session.summary     : 6턴 이전 대화의 구조화 요약 (신규)    │
│  Session.calc_cache  : 이전 계산 결과 캐싱 (신규)            │
│  Session.created_at  : 세션 생성 시각 (TTL용, 신규)          │
├──────────────────────────────────────────────────────────────┤
│ Layer 3: Persistent Store (Supabase, optional)               │
│                                                              │
│  qa_sessions.session_data : summary + calc_cache JSON 저장   │
│  cold start 시 session_id로 조회 → Session 복원              │
│  TTL: 24시간 후 자동 만료 (RLS policy 또는 cron)             │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 Data Flow

```
[페이지 로드]
  │
  ├─ sessionStorage에 sessionId 있음?
  │   ├─ YES → 서버에 session_id 포함하여 요청
  │   └─ NO  → sessionId 없이 요청 (새 세션)
  │
[서버 요청 수신]
  │
  ├─ _sessions[session_id] 존재?
  │   ├─ YES → 기존 세션 반환 (기존 동작)
  │   └─ NO  → Supabase에서 session_data 조회 시도
  │       ├─ 성공 → Session 복원 (summary + calc_cache)
  │       └─ 실패 → 새 Session 생성 (graceful fallback)
  │
[응답 완료 후]
  │
  ├─ session.add_user() + session.add_assistant() (기존)
  ├─ session.condense_if_needed() (신규: 6턴 초과 시 요약)
  ├─ pipeline에서 calc_result → session.cache_calculation() (신규)
  └─ Supabase에 session_data 업데이트 (fire-and-forget, 신규)
```

### 2.3 Dependencies

| Component | Depends On | Purpose |
|-----------|-----------|---------|
| `session.py` (변경) | `schemas.py` | Session 모델에 summary, calc_cache, created_at 추가 |
| `pipeline.py` (변경) | `session.py` | 계산 결과 캐싱, 요약 트리거, 맥락 주입 |
| `analyzer.py` (변경) | `session.py` | summary를 히스토리에 포함하여 분석 |
| `storage.py` (변경) | `supabase` | session_data 저장/복원 함수 추가 |
| `public/index.html` (변경) | 없음 | sessionStorage 영속화 |

---

## 3. Data Model

### 3.1 Session 확장 (Python dataclass)

```python
@dataclass
class Session:
    id: str
    history: list = field(default_factory=list)
    _pending_analysis: AnalysisResult | None = field(default=None, repr=False)

    # ── 신규 필드 ──
    summary: str = ""                          # 6턴 이전 대화 요약 텍스트
    calc_cache: dict = field(default_factory=dict)  # {calc_type: extracted_info}
    created_at: float = field(default_factory=time.time)  # 세션 생성 시각
```

### 3.2 calc_cache 구조

```python
# calc_cache 예시
{
    "overtime": {
        "wage_amount": 2500000,
        "wage_type": "월급",
        "daily_work_hours": 8,
        "weekly_work_days": 5,
        "business_size": "5인 이상"
    },
    "severance": {
        "wage_amount": 2500000,
        "start_date": "2023-03-01",
        "service_years": 3
    }
}
```

**저장 규칙**:
- 키: 계산기 타입 문자열 (e.g., `"overtime"`, `"severance"`)
- 값: 해당 계산에 사용된 `extracted_info` dict
- 새 계산 시 기존 캐시에 merge (새 값이 기존 값을 덮어씀)

### 3.3 summary 구조

```python
# summary 예시 (일반 텍스트, 2KB 이내)
"이전 대화 요약: 사용자는 월급 250만원, 주 5일 8시간 근무 조건으로 "
"연장수당을 질문했고 계산 결과를 받았습니다. "
"이후 같은 조건으로 퇴직금 계산을 요청했습니다."
```

**요약 규칙**:
- 규칙 기반 추출 (LLM 호출 없음, 비용 절약)
- `calc_cache`에 이미 숫자 데이터가 있으므로 summary는 맥락/주제만 포함
- 최대 길이: 2,000자 (초과 시 가장 오래된 요약 부분 잘라냄)

### 3.4 Supabase 스키마 변경

```sql
-- 기존 qa_sessions 테이블에 컬럼 추가
ALTER TABLE qa_sessions
ADD COLUMN IF NOT EXISTS session_data JSONB DEFAULT '{}';

-- session_data 구조:
-- {
--   "summary": "이전 대화 요약...",
--   "calc_cache": {"overtime": {...}, "severance": {...}},
--   "history_tail": [최근 2턴 원문 (4 메시지)]
-- }
```

**TTL 정책**: `qa_sessions.updated_at`이 24시간 이상 지난 행은 복원 대상에서 제외 (쿼리 조건으로 처리, 행 삭제는 별도 cron).

---

## 4. API Specification

### 4.1 기존 API 변경 없음

| Method | Path | 변경 사항 |
|--------|------|----------|
| GET | `/api/chat/stream?message=...&session_id=...` | 없음 |
| POST | `/api/chat/stream` | 없음 |

프론트엔드가 `session_id`를 보내는 방식은 동일. 서버 내부에서 세션 복원 로직만 추가.

### 4.2 SSE 이벤트 변경

| 이벤트 | 변경 사항 |
|--------|----------|
| `session` | 기존: `{type: "session", session_id}` → 변경 없음 |
| `context` (신규) | `{type: "context", resumed: true/false}` — 세션 복원 여부 알림 |

`context` 이벤트는 선택적(optional). 프론트엔드가 "이전 대화가 복원되었습니다" 같은 UX를 제공하려면 이 이벤트를 활용.

---

## 5. 핵심 모듈별 변경 상세

### 5.1 `app/models/session.py` — Session 모델 확장

#### 5.1.1 신규 필드

```python
summary: str = ""
calc_cache: dict = field(default_factory=dict)
created_at: float = field(default_factory=time.time)
```

#### 5.1.2 신규 메서드: `condense_if_needed()`

```python
def condense_if_needed(self, max_turns: int = 6):
    """6턴 초과 시 오래된 대화를 summary로 압축"""
    if len(self.history) <= max_turns * 2:
        return  # 압축 불필요

    # 요약 대상: 최근 6턴을 제외한 오래된 메시지
    old_messages = self.history[:-(max_turns * 2)]
    new_summary_parts = []

    for i in range(0, len(old_messages), 2):
        user_msg = old_messages[i].get("content", "")[:100]
        asst_msg = old_messages[i + 1].get("content", "")[:100] if i + 1 < len(old_messages) else ""
        new_summary_parts.append(f"Q: {user_msg} / A: {asst_msg}")

    condensed = "; ".join(new_summary_parts)

    # 기존 summary에 추가
    if self.summary:
        self.summary = self.summary + " | " + condensed
    else:
        self.summary = condensed

    # 2KB 제한
    if len(self.summary) > 2000:
        self.summary = self.summary[-2000:]

    # 오래된 메시지 제거
    self.history = self.history[-(max_turns * 2):]
```

#### 5.1.3 신규 메서드: `cache_calculation()`

```python
def cache_calculation(self, calc_type: str, extracted_info: dict):
    """계산 결과의 입력 파라미터를 캐싱"""
    if calc_type not in self.calc_cache:
        self.calc_cache[calc_type] = {}
    self.calc_cache[calc_type].update(
        {k: v for k, v in extracted_info.items() if v is not None}
    )
```

#### 5.1.4 신규 메서드: `get_cached_info()`

```python
def get_cached_info(self) -> dict:
    """모든 캐시된 계산 파라미터를 병합하여 반환 (최신 값 우선)"""
    merged = {}
    for calc_type, info in self.calc_cache.items():
        for k, v in info.items():
            merged[k] = v  # 나중에 캐시된 값이 우선
    return merged
```

#### 5.1.5 신규 메서드: `to_snapshot()` / `from_snapshot()`

```python
def to_snapshot(self) -> dict:
    """Supabase 저장용 스냅샷"""
    return {
        "summary": self.summary,
        "calc_cache": self.calc_cache,
        "history_tail": self.history[-4:],  # 최근 2턴만
    }

@classmethod
def from_snapshot(cls, session_id: str, snapshot: dict) -> "Session":
    """스냅샷에서 Session 복원"""
    session = cls(id=session_id)
    session.summary = snapshot.get("summary", "")
    session.calc_cache = snapshot.get("calc_cache", {})
    session.history = snapshot.get("history_tail", [])
    return session
```

#### 5.1.6 `get_or_create_session()` 변경

```python
def get_or_create_session(
    session_id: str | None = None,
    restore_fn: Callable | None = None,  # Supabase 복원 함수 (optional)
) -> tuple[Session, bool]:
    """세션 조회/생성. (session, is_restored) 반환."""
    if session_id and session_id in _sessions:
        return _sessions[session_id], False

    # Layer 3: Supabase 복원 시도
    if session_id and restore_fn:
        try:
            snapshot = restore_fn(session_id)
            if snapshot:
                session = Session.from_snapshot(session_id, snapshot)
                _sessions[session_id] = session
                return session, True
        except Exception:
            pass  # graceful fallback

    # 새 세션 생성
    sid = session_id or uuid.uuid4().hex[:12]
    session = Session(id=sid)
    _sessions[sid] = session
    return session, False
```

**하위 호환**: 기존 호출 `get_or_create_session(session_id)` — `restore_fn=None`이므로 기존 동작 유지. 반환값이 `(session, bool)` 튜플로 변경되므로 `api/index.py`에서 언팩 필요.

### 5.2 `app/core/pipeline.py` — 계산 캐싱 & 맥락 주입

#### 5.2.1 계산 결과 캐싱 (process_question 내부)

```python
# 계산 완료 후 (기존 calc_result 생성 이후)
if calc_result and analysis.calculation_types:
    for ct in analysis.calculation_types:
        session.cache_calculation(ct, analysis.extracted_info)
```

#### 5.2.2 캐시 기반 extracted_info 프리필

```python
# analyze_intent() 호출 직후, missing_info 계산 전
cached = session.get_cached_info()
for key, val in cached.items():
    if key not in analysis.extracted_info or analysis.extracted_info[key] is None:
        analysis.extracted_info[key] = val
```

**주의**: 사용자가 새 값을 명시한 경우 캐시보다 새 값이 우선. `if key not in analysis.extracted_info or analysis.extracted_info[key] is None` 조건으로 보장.

#### 5.2.3 대화 요약 트리거

```python
# session.add_assistant(full_answer) 직후
session.condense_if_needed()
```

#### 5.2.4 Supabase 세션 데이터 업데이트

```python
# 기존 save_conversation() 호출 이후
if sb:
    _save_session_data(sb, session)  # fire-and-forget
```

### 5.3 `app/core/analyzer.py` — summary 주입

#### 5.3.1 history 구성 변경

```python
def analyze_intent(question: str, history: list, config, summary: str = "") -> AnalysisResult:
    # 기존: 최근 4턴만 사용
    recent = history[-(4 * 2):]

    # 신규: summary가 있으면 맨 앞에 시스템 컨텍스트로 추가
    messages = []
    if summary:
        messages.append({
            "role": "user",
            "content": f"[이전 대화 요약] {summary}"
        })
        messages.append({
            "role": "assistant",
            "content": "네, 이전 대화 내용을 참고하겠습니다."
        })
    messages.extend(recent)
    messages.append({"role": "user", "content": question})
    # ... Claude API 호출
```

**토큰 영향**: summary 2KB + 최근 4턴 ≈ 기존 대비 +500~1000 토큰 (허용 범위)

### 5.4 `app/core/storage.py` — 세션 데이터 영속화

#### 5.4.1 신규 함수: `save_session_data()`

```python
def save_session_data(sb: SupabaseClient, session_id: str, snapshot: dict):
    """세션 스냅샷을 qa_sessions.session_data에 저장"""
    try:
        sb.table("qa_sessions").update({
            "session_data": snapshot,
            "updated_at": "now()",
        }).eq("id", session_id).execute()
    except Exception as e:
        logger.warning("세션 데이터 저장 실패: %s", e)
```

#### 5.4.2 신규 함수: `restore_session_data()`

```python
def restore_session_data(sb: SupabaseClient, session_id: str) -> dict | None:
    """qa_sessions에서 세션 데이터 복원. 24시간 TTL 초과 시 None 반환."""
    try:
        result = sb.table("qa_sessions").select(
            "session_data, updated_at"
        ).eq("id", session_id).execute()

        if not result.data:
            return None

        row = result.data[0]
        session_data = row.get("session_data")
        if not session_data:
            return None

        # TTL 검사: 24시간 초과 시 무시
        updated_at = row.get("updated_at")
        if updated_at:
            from datetime import datetime, timezone, timedelta
            updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - updated > timedelta(hours=24):
                return None

        return session_data
    except Exception as e:
        logger.warning("세션 복원 실패 (session_id=%s): %s", session_id, e)
        return None
```

### 5.5 `public/index.html` — sessionStorage 영속화

#### 5.5.1 변경 내용

```javascript
// ── 기존 ──
let sessionId = null;

// ── 변경 ──
let sessionId = null;
try {
    sessionId = sessionStorage.getItem('chatSessionId');
} catch (e) { /* sessionStorage 비활성 환경 */ }

// SSE session 이벤트 수신 시 (기존 line 450 부근)
if (event.type === 'session') {
    sessionId = event.session_id;
    try {
        sessionStorage.setItem('chatSessionId', sessionId);
    } catch (e) { /* ignore */ }
}
```

### 5.6 `api/index.py` — 세션 복원 연결

```python
# 기존
session = get_or_create_session(req.session_id)

# 변경
restore_fn = None
if sb:
    from app.core.storage import restore_session_data
    restore_fn = lambda sid: restore_session_data(sb, sid)

session, is_restored = get_or_create_session(req.session_id, restore_fn)
```

---

## 6. Error Handling

### 6.1 에러 시나리오별 처리

| 시나리오 | 영향 | 처리 |
|---------|------|------|
| sessionStorage 접근 불가 (시크릿 모드 등) | Layer 1 비활성 | try-catch로 무시, 기존 동작 유지 |
| Supabase 장애/연결 실패 | Layer 3 비활성 | 로그 경고, 인메모리만 사용 |
| session_data JSON 파싱 실패 | 복원 실패 | 새 세션 생성 (graceful fallback) |
| calc_cache에 잘못된 값 캐시 | 후속 계산 오류 | 사용자가 새 값 명시 시 덮어씀 |
| summary가 2KB 초과 | 토큰 낭비 | 앞부분 잘라내기 (최신 유지) |
| Vercel cold start + Supabase TTL 만료 | 완전 유실 | 새 세션 (기존 동작과 동일) |

### 6.2 에러 응답 형식

에러 시에도 기존 SSE 이벤트 형식 유지. 세션 복원 관련 에러는 사용자에게 노출하지 않음 (내부 로그만).

---

## 7. Security Considerations

- [x] sessionStorage는 same-origin 정책으로 보호 (XSS 외 접근 불가)
- [x] session_data에 민감 정보 미포함 (임금/근무조건은 상담 맥락이므로 PII 아님)
- [x] Supabase RLS로 세션 데이터 접근 제한 (session_id 소유자만)
- [x] TTL 24시간으로 데이터 자동 만료
- [ ] sessionId가 URL 파라미터로 전송 → HTTPS 필수 (기존 Vercel은 HTTPS 기본)

---

## 8. Test Plan

### 8.1 테스트 범위

| Type | Target | Tool |
|------|--------|------|
| 단위 테스트 | `Session.condense_if_needed()`, `cache_calculation()`, `to_snapshot()/from_snapshot()` | pytest |
| 통합 테스트 | 캐시 프리필 → 후속 계산 정상 동작 | `wage_calculator_cli.py` |
| 수동 E2E | 새로고침 후 맥락 유지 | 브라우저 |

### 8.2 핵심 테스트 케이스

- [ ] **새로고침 영속화**: `sessionStorage.setItem` → 새로고침 → `sessionStorage.getItem` → 동일 sessionId 확인
- [ ] **계산 캐시 프리필**: 연장수당 계산(월급 250만) → "퇴직금도 계산해줘" → `wage_amount=2500000` 자동 프리필 확인
- [ ] **대화 요약**: 7턴 이상 대화 → `session.summary` 비어있지 않음 확인
- [ ] **cold start 복원**: `_sessions` 비우기 → 동일 session_id로 요청 → Supabase에서 복원 확인
- [ ] **graceful fallback**: Supabase 연결 없이 → 새 세션 정상 생성 확인
- [ ] **기존 테스트 회귀**: `wage_calculator_cli.py` 32개 케이스 전부 통과

---

## 9. Implementation Guide

### 9.1 파일 구조 (변경 파일만)

```
app/
├── models/
│   └── session.py          # Session 확장 (summary, calc_cache, condense, snapshot)
├── core/
│   ├── pipeline.py         # 캐싱 트리거, 프리필 로직
│   ├── analyzer.py         # summary 주입
│   └── storage.py          # save/restore_session_data 추가
api/
└── index.py                # get_or_create_session() 튜플 언팩, restore_fn 연결
public/
└── index.html              # sessionStorage 영속화 (~5줄)
```

### 9.2 Implementation Order

1. [ ] **Phase 1 — 프론트엔드 sessionId 영속화** (FR-01)
   - `public/index.html`: sessionStorage 저장/복원 (5줄)
   - 즉시 효과: 새로고침 후 대화 유지 (서버 warm 상태일 때)

2. [ ] **Phase 2 — Session 모델 확장** (FR-03, FR-04)
   - `session.py`: `summary`, `calc_cache`, `created_at` 필드 추가
   - `session.py`: `condense_if_needed()`, `cache_calculation()`, `get_cached_info()` 메서드
   - `session.py`: `to_snapshot()`, `from_snapshot()` 직렬화
   - `session.py`: `get_or_create_session()` 반환값 변경

3. [ ] **Phase 3 — Pipeline 연동** (FR-04, FR-05)
   - `pipeline.py`: 계산 완료 후 `cache_calculation()` 호출
   - `pipeline.py`: 분석 직후 `get_cached_info()` 프리필
   - `pipeline.py`: 응답 완료 후 `condense_if_needed()` 호출
   - `analyzer.py`: `summary` 파라미터 추가, 히스토리 앞에 삽입

4. [ ] **Phase 4 — API 연결 & Supabase 영속화** (FR-02, FR-06)
   - `api/index.py`: 튜플 언팩, `restore_fn` 연결
   - `storage.py`: `save_session_data()`, `restore_session_data()` 추가
   - `pipeline.py`: 응답 후 `save_session_data()` fire-and-forget 호출
   - Supabase `qa_sessions` 테이블에 `session_data JSONB` 컬럼 추가

### 9.3 예상 코드량

| Phase | 파일 | 추가/변경 라인 |
|-------|------|---------------|
| Phase 1 | `index.html` | ~5줄 변경 |
| Phase 2 | `session.py` | ~80줄 추가 |
| Phase 3 | `pipeline.py`, `analyzer.py` | ~25줄 추가 |
| Phase 4 | `storage.py`, `index.py` | ~50줄 추가 |
| **합계** | | **~160줄** |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-13 | Initial draft | Claude |
