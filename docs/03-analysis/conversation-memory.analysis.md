# Conversation Memory (대화 맥락 유지) Analysis Report

> **Analysis Type**: Gap Analysis (Design vs Implementation)
>
> **Project**: laborconsult (nodong.kr)
> **Analyst**: Claude (gap-detector)
> **Date**: 2026-03-13
> **Design Doc**: [conversation-memory.design.md](../02-design/features/conversation-memory.design.md)
> **Plan Doc**: [conversation-memory.plan.md](../01-plan/features/conversation-memory.plan.md)

---

## 1. Analysis Overview

### 1.1 Analysis Purpose

Design document(v1.0, 2026-03-13) 대비 실제 구현 코드의 일치율을 측정하고, 누락/변경/추가 항목을 식별한다.

### 1.2 Analysis Scope

| File | Role | Lines Analyzed |
|------|------|:--------------:|
| `app/models/session.py` | Session 모델 확장 | 180 |
| `app/core/pipeline.py` | 캐싱, 프리필, 요약 트리거 | 1040 |
| `app/core/analyzer.py` | summary 주입 | 180 |
| `app/core/storage.py` | save/restore session data | 252 |
| `api/index.py` | 튜플 언팩, restore_fn | 385 |
| `public/index.html` | sessionStorage 영속화 | 554 |

---

## 2. Gap Analysis (Design vs Implementation)

### 2.1 Data Model — Session 확장 (Design Section 3.1)

| Design Item | Design Spec | Implementation | Status |
|-------------|-------------|----------------|:------:|
| `summary: str = ""` | 6턴 이전 대화 요약 | `session.py:20` — `summary: str = ""` | MATCH |
| `calc_cache: dict = field(default_factory=dict)` | {calc_type: extracted_info} | `session.py:21` — `calc_cache: dict = field(default_factory=dict)` | MATCH |
| `created_at: float = field(default_factory=time.time)` | 세션 생성 시각 | `session.py:22` — `created_at: float = field(default_factory=time.time)` | MATCH |
| `import time` | time 모듈 필요 | `session.py:3` — `import time` | MATCH |
| `from typing import Callable` | restore_fn 타입용 | `session.py:8` — `from typing import Callable` | MATCH |

**Data Model Score**: 5/5 (100%)

### 2.2 Session Methods (Design Sections 5.1.2 ~ 5.1.5)

| Design Method | Design Signature | Implementation | Status |
|---------------|-----------------|----------------|:------:|
| `condense_if_needed()` | `max_turns: int = 6` | `session.py:107-131` — exact match | MATCH |
| condense: history slicing | `self.history[:-(max_turns * 2)]` | `session.py:112` | MATCH |
| condense: Q/A format | `f"Q: {user_msg} / A: {asst_msg}"` | `session.py:118` | MATCH |
| condense: summary join | `"; ".join(...)` | `session.py:120` | MATCH |
| condense: append separator | `" \| "` | `session.py:123` | MATCH |
| condense: 2KB limit | `self.summary[-2000:]` | `session.py:129` | MATCH |
| condense: trim history | `self.history[-(max_turns * 2):]` | `session.py:131` | MATCH |
| `cache_calculation()` | `calc_type: str, extracted_info: dict` | `session.py:89-95` — exact match | MATCH |
| cache: None filter | `{k: v for k, v in ... if v is not None}` | `session.py:94` | MATCH |
| `get_cached_info()` | returns merged dict | `session.py:97-103` — exact match | MATCH |
| `to_snapshot()` | returns dict with summary, calc_cache, history_tail[-4:] | `session.py:135-141` — exact match | MATCH |
| `from_snapshot()` | classmethod, restores from snapshot | `session.py:143-150` — exact match | MATCH |

**Session Methods Score**: 12/12 (100%)

### 2.3 `get_or_create_session()` (Design Section 5.1.6)

| Design Item | Design Spec | Implementation | Status |
|-------------|-------------|----------------|:------:|
| Signature change | `restore_fn: Callable \| None = None` | `session.py:159` — `restore_fn: Callable[[str], dict \| None] \| None = None` | MATCH (more precise type) |
| Return type | `tuple[Session, bool]` | `session.py:160` — `-> tuple[Session, bool]` | MATCH |
| Existing session lookup | `return _sessions[session_id], False` | `session.py:163` | MATCH |
| Supabase restore attempt | `if session_id and restore_fn: ...` | `session.py:166-174` | MATCH |
| from_snapshot call | `Session.from_snapshot(session_id, snapshot)` | `session.py:170` | MATCH |
| Graceful fallback | `except Exception: pass` | `session.py:173-174` | MATCH |
| New session creation | `sid = session_id or uuid.uuid4().hex[:12]` | `session.py:176` | MATCH |
| Return tuple | `return session, False` | `session.py:179` | MATCH |

**get_or_create_session Score**: 8/8 (100%)

### 2.4 Pipeline Integration (Design Section 5.2)

| Design Item | Design Spec | Implementation | Status |
|-------------|-------------|----------------|:------:|
| Cache prefill | `cached = session.get_cached_info()` + loop | `pipeline.py:732-735` — exact match | MATCH |
| Prefill condition | `if key not in analysis.extracted_info or ... is None` | `pipeline.py:734` | MATCH |
| Calculation caching | `session.cache_calculation(ct, analysis.extracted_info)` | `pipeline.py:782-783` — in for loop | MATCH |
| Caching trigger | after `calc_result` success + `analysis.calculation_types` | `pipeline.py:781-783` | MATCH |
| Condensation trigger | `session.condense_if_needed()` after add_assistant | `pipeline.py:991` | MATCH |
| Supabase save | `save_session_data(sb, session.id, session.to_snapshot())` | `pipeline.py:1035` | MATCH |
| Fire-and-forget pattern | Inside try/except, after save_conversation | `pipeline.py:1034-1035` | MATCH |
| summary param to analyze_intent | `summary=session.summary` | `pipeline.py:720, 728` — both call sites | MATCH |

**Pipeline Score**: 8/8 (100%)

### 2.5 Analyzer Integration (Design Section 5.3)

| Design Item | Design Spec | Implementation | Status |
|-------------|-------------|----------------|:------:|
| `summary` parameter | `summary: str = ""` added to `analyze_intent` | `analyzer.py:109` — `summary: str = ""` | MATCH |
| Summary injection format | `[이전 대화 요약] {summary}` as user message | `analyzer.py:115-118` — exact match | MATCH |
| Assistant ack message | `"네, 이전 대화 내용을 참고하겠습니다."` | `analyzer.py:121-123` — exact match | MATCH |
| Recent history | `history[-8:]` (4 turns) | `analyzer.py:125` — `history[-8:]` | MATCH |
| Message order | summary pair → recent → question | `analyzer.py:113-127` | MATCH |

**Analyzer Score**: 5/5 (100%)

### 2.6 Storage Functions (Design Section 5.4)

| Design Item | Design Spec | Implementation | Status |
|-------------|-------------|----------------|:------:|
| `save_session_data()` | `sb, session_id, snapshot` params | `storage.py:181` — `sb: SupabaseClient, session_id: str, snapshot: dict` | MATCH |
| save: update query | `.update({"session_data": snapshot, "updated_at": "now()"})` | `storage.py:184-186` | MATCH |
| save: error handling | `logger.warning("세션 데이터 저장 실패: %s", e)` | `storage.py:189` | MATCH |
| `restore_session_data()` | `sb, session_id` params, returns `dict \| None` | `storage.py:192` | MATCH |
| restore: select query | `select("session_data, updated_at")` | `storage.py:195-196` | MATCH |
| restore: empty check | `if not result.data: return None` | `storage.py:199-200` | MATCH |
| restore: session_data check | `if not session_data: return None` | `storage.py:204-205` | MATCH |
| restore: TTL 24h check | `timedelta(hours=24)` comparison | `storage.py:212-213` | MATCH |
| restore: TTL timezone | `datetime.now(timezone.utc)` | `storage.py:212` | MATCH |
| restore: error handling | `logger.warning("세션 복원 실패 ...")` | `storage.py:217` | MATCH |

**Storage Score**: 10/10 (100%)

### 2.7 Frontend — sessionStorage (Design Section 5.5)

| Design Item | Design Spec | Implementation | Status |
|-------------|-------------|----------------|:------:|
| Restore on load | `sessionStorage.getItem('chatSessionId')` | `index.html:156` — `sessionId = sessionStorage.getItem('chatSessionId');` | MATCH |
| try-catch guard | `try { ... } catch (e) { /* ignore */ }` | `index.html:156` — `try { ... } catch (e) { /* ignore */ }` | MATCH |
| Save on session event | `sessionStorage.setItem('chatSessionId', sessionId)` | `index.html:452` — inside `event.type === 'session'` handler | MATCH |
| Save try-catch | `try { ... } catch (e) { /* ignore */ }` | `index.html:452` — `try { ... } catch (e) { /* ignore */ }` | MATCH |

**Frontend Score**: 4/4 (100%)

### 2.8 API Endpoint (Design Section 5.6)

| Design Item | Design Spec | Implementation | Status |
|-------------|-------------|----------------|:------:|
| `_restore_fn` function | `lambda sid: restore_session_data(sb, sid)` | `api/index.py:56-61` — standalone function with `get_config()` | MATCH (improved: reusable) |
| Import restore_session_data | `from app.core.storage import restore_session_data` | `api/index.py:24` | MATCH |
| Tuple unpacking | `session, is_restored = get_or_create_session(...)` | `api/index.py:73, 101, 127` — `session, _ = get_or_create_session(req.session_id, _restore_fn)` | MATCH |
| Pass restore_fn | `get_or_create_session(req.session_id, restore_fn)` | `api/index.py:73` — `get_or_create_session(req.session_id, _restore_fn)` | MATCH |
| All 3 endpoints updated | GET /stream, POST /stream, POST /chat | `api/index.py:73, 101, 127` | MATCH |

**API Score**: 5/5 (100%)

### 2.9 SSE Context Event (Design Section 4.2)

| Design Item | Design Spec | Implementation | Status |
|-------------|-------------|----------------|:------:|
| `context` SSE event | `{type: "context", resumed: true/false}` — optional | Not implemented in pipeline or api/index.py | MISSING (optional) |

**SSE Event Score**: 0/1 (0%)

### 2.10 Error Handling (Design Section 6)

| Design Scenario | Design Handling | Implementation | Status |
|-----------------|----------------|----------------|:------:|
| sessionStorage inaccessible | try-catch, ignore | `index.html:156, 452` — try-catch | MATCH |
| Supabase failure | log warning, in-memory only | `storage.py:189, 217` — logger.warning | MATCH |
| session_data JSON parse fail | new session (graceful) | `session.py:173-174` — except pass | MATCH |
| calc_cache bad value | user new value overrides | `pipeline.py:734` — only fills if None | MATCH |
| summary > 2KB | truncate oldest | `session.py:128-129` — `self.summary[-2000:]` | MATCH |
| Cold start + TTL expired | new session | `storage.py:212-213` — returns None after 24h | MATCH |

**Error Handling Score**: 6/6 (100%)

### 2.11 Import & Dependency Wiring

| Design Item | Design Spec | Implementation | Status |
|-------------|-------------|----------------|:------:|
| pipeline imports save_session_data | from storage | `pipeline.py:13` — `from app.core.storage import save_conversation, save_session_data, ...` | MATCH |
| api/index.py imports restore_session_data | from storage | `api/index.py:24` — `from app.core.storage import restore_session_data` | MATCH |
| api/index.py imports get_or_create_session | from session | `api/index.py:23` — `from app.models.session import get_or_create_session` | MATCH |

**Import Score**: 3/3 (100%)

---

## 3. Match Rate Summary

```
Total Design Items:          67
  MATCH:                     66  (98.5%)
  MISSING (optional):        1   (1.5%)
  CHANGED:                   0   (0%)
  ADDED (not in design):     3   (positive deviations)
```

### 3.1 Overall Scores

| Category | Score | Status |
|----------|:-----:|:------:|
| Data Model (Section 3) | 100% (5/5) | PASS |
| Session Methods (Section 5.1) | 100% (12/12) | PASS |
| get_or_create_session (Section 5.1.6) | 100% (8/8) | PASS |
| Pipeline Integration (Section 5.2) | 100% (8/8) | PASS |
| Analyzer Integration (Section 5.3) | 100% (5/5) | PASS |
| Storage Functions (Section 5.4) | 100% (10/10) | PASS |
| Frontend sessionStorage (Section 5.5) | 100% (4/4) | PASS |
| API Endpoint (Section 5.6) | 100% (5/5) | PASS |
| SSE Context Event (Section 4.2) | 0% (0/1) | PARTIAL (optional) |
| Error Handling (Section 6) | 100% (6/6) | PASS |
| Import Wiring | 100% (3/3) | PASS |
| **Overall Match Rate** | **98.5% (66/67)** | **PASS** |

---

## 4. Detailed Findings

### 4.1 Missing Features (Design O, Implementation X)

| Item | Design Location | Description | Impact |
|------|-----------------|-------------|:------:|
| SSE `context` event | Design 4.2 | `{type: "context", resumed: true/false}` not emitted | Low |

The `context` event was explicitly marked as "optional" in the design document: "context 이벤트는 선택적(optional)." The frontend does not handle this event either. This is an intentional deferral, not a gap.

### 4.2 Positive Deviations (Implementation O, Design X)

| Item | Implementation Location | Description |
|------|------------------------|-------------|
| More precise type annotation | `session.py:159` | `Callable[[str], dict \| None]` instead of just `Callable` |
| `_restore_fn` as standalone function | `api/index.py:56-61` | Design showed inline lambda; impl uses a reusable module-level function |
| All 3 API endpoints wired | `api/index.py:73, 101, 127` | Design only showed 1 example; impl updated GET /stream, POST /stream, POST /chat |

### 4.3 Code Quality Observations

| Observation | Location | Assessment |
|-------------|----------|------------|
| Consistent error handling pattern | All storage/session code | logger.warning + graceful fallback throughout |
| No dead code introduced | All files | Clean additions, no unused imports or functions |
| Backward compatible | `get_or_create_session` | Default `restore_fn=None` preserves old call sites |
| `save_session_data` import | `pipeline.py:13` | Imported alongside existing `save_conversation` |

---

## 5. Functional Requirements Traceability

| FR | Description | Design Section | Implementation | Status |
|----|-------------|:--------------:|----------------|:------:|
| FR-01 | sessionStorage sessionId 영속화 | 5.5 | `index.html:156, 452` | DONE |
| FR-02 | Cold start 시 세션 복원 | 5.6, 5.4.2 | `api/index.py:56-61`, `storage.py:192-218` | DONE |
| FR-03 | 6턴 초과 시 대화 요약(condensation) | 5.1.2 | `session.py:107-131` | DONE |
| FR-04 | 계산 결과 캐싱 + 프리필 | 5.1.3, 5.1.4, 5.2.1, 5.2.2 | `session.py:89-103`, `pipeline.py:731-735, 782-783` | DONE |
| FR-05 | 맥락 참조 질문 지원 (summary 주입) | 5.3 | `analyzer.py:105-127` | DONE |
| FR-06 | Supabase 세션 데이터 저장/복원 | 5.4 | `storage.py:181-218` | DONE |

**FR Coverage**: 6/6 (100%)

---

## 6. Recommended Actions

### 6.1 Optional Enhancement

| Priority | Item | Impact | Effort |
|----------|------|--------|--------|
| Low | Implement SSE `context` event | UX: "이전 대화가 복원되었습니다" 표시 가능 | ~10줄 |

The `is_restored` boolean from `get_or_create_session()` is already available but not sent as an SSE event. If desired:

```python
# api/index.py event_generator() 내부, session 이벤트 직후
if is_restored:
    yield f"data: {json.dumps({'type': 'context', 'resumed': True})}\n\n"
```

### 6.2 No Immediate Actions Required

All 66 mandatory design items are implemented with exact match. No gaps require remediation.

---

## 7. Supabase Schema Verification

| Design Item | Design Spec | Status |
|-------------|-------------|:------:|
| `ALTER TABLE qa_sessions ADD COLUMN session_data JSONB DEFAULT '{}'` | Section 3.4 | Cannot verify (DB migration is external) |
| TTL policy: 24h in query condition | Section 3.4 | MATCH (`storage.py:212-213`) |

Note: The Supabase DDL migration (`ALTER TABLE`) is an operational task outside the code implementation scope. The code correctly queries and filters by `updated_at` for 24h TTL.

---

## 8. Overall Assessment

```
+----------------------------------------------------+
|  Overall Match Rate: 97%                            |
+----------------------------------------------------+
|  MATCH:              66 items (98.5%)               |
|  MISSING (optional):  1 item  (1.5%)               |
|  CHANGED:             0 items (0%)                  |
|  POSITIVE:            3 items (improvements)        |
+----------------------------------------------------+
|  FR Coverage:        6/6 (100%)                     |
|  Error Handling:     6/6 (100%)                     |
|  Backward Compat:    Verified (default params)      |
+----------------------------------------------------+
```

**Verdict**: Design and implementation are in near-perfect alignment. The single missing item (`context` SSE event) was explicitly marked optional in the design. All 6 functional requirements are fully implemented. Three positive deviations improve on the design (more precise types, reusable restore function, all endpoints wired).

---

## 9. Next Steps

- [x] Gap analysis complete
- [ ] (Optional) Implement SSE `context` event for "세션 복원" UX indicator
- [ ] Write completion report (`conversation-memory.report.md`)

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-03-13 | Initial analysis — 97% match rate | Claude (gap-detector) |
