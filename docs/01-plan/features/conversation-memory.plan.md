# Conversation Memory (대화 맥락 유지) Planning Document

> **Summary**: 대화창에서 이전 질문/답변의 맥락을 이어가는 세션 메모리 강화
>
> **Project**: laborconsult (nodong.kr)
> **Version**: 1.0
> **Author**: Claude
> **Date**: 2026-03-12
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | Vercel 서버리스 환경에서 인메모리 세션이 cold start 시 유실되고, 페이지 새로고침 시 sessionId가 초기화되어 대화 맥락이 끊김 |
| **Solution** | 3계층 메모리 아키텍처: (1) 프론트엔드 sessionStorage 영속화, (2) 서버 세션 요약(condensation), (3) Supabase 기반 세션 영속 저장 |
| **Function/UX Effect** | 사용자가 "아까 물어본 연장수당 기준으로 퇴직금도 계산해줘" 같은 맥락 참조 질문을 자연스럽게 할 수 있음 |
| **Core Value** | 노동상담의 특성상 연관 질문이 많으므로(임금→퇴직금→실업급여 등), 맥락 유지가 상담 품질을 크게 향상시킴 |

---

## 1. Overview

### 1.1 Purpose

현재 시스템은 대화 이력을 인메모리(`_sessions: dict[str, Session]`)에 저장하므로:
- Vercel 서버리스 cold start(~15분 유휴) 시 모든 세션 유실
- 페이지 새로고침 시 프론트엔드 `sessionId` 변수 초기화 → 새 세션 시작
- `session.recent(max_turns=6)` — 최근 6턴(12메시지)만 analyzer에 전달, 이전 맥락 완전 소실

이 기능은 대화 맥락을 안정적으로 유지하여, 사용자가 이전 질문/답변을 참조하는 후속 질문을 자연스럽게 할 수 있도록 한다.

### 1.2 Background

노동상담은 단일 질문으로 끝나지 않는 경우가 많다:
1. "월급 250만원인데 연장수당 얼마나 받아야 해요?" → 계산 결과 제공
2. "그러면 이 기준으로 퇴직금은 얼마예요?" → **이전 임금/근무조건 맥락 필요**
3. "실업급여는요?" → **누적된 근무조건 맥락 필요**

현재 시스템은 `analyzer.py`가 `history[-8:]`를 Claude에 전달하여 기본적인 맥락 참조가 가능하지만, 세션 유실 시 모든 맥락이 사라진다.

### 1.3 Related Documents

- 현재 세션 구현: `app/models/session.py`
- 의도 분석기: `app/core/analyzer.py`
- 파이프라인: `app/core/pipeline.py`
- API 엔드포인트: `api/index.py`
- 프론트엔드: `public/index.html`

---

## 2. Scope

### 2.1 In Scope

- [x] 프론트엔드 sessionId 영속화 (sessionStorage/localStorage)
- [ ] 서버 세션 요약(condensation) — 오래된 대화를 요약본으로 압축
- [ ] 세션 영속 저장소 (Supabase 또는 JSON 파일 기반)
- [ ] 맥락 참조 질문 감지 ("아까", "위에서", "그 기준으로" 등)
- [ ] 계산 결과 캐싱 — 이전 계산 결과를 세션에 저장하여 후속 계산에 재활용

### 2.2 Out of Scope

- 사용자 인증/로그인 기반 영구 프로필
- 크로스 디바이스 세션 동기화
- 대화 내보내기/공유 기능
- 다중 대화 탭/윈도우 동시 관리

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | 프론트엔드 sessionId를 sessionStorage에 저장하여 새로고침 후에도 유지 | High | Pending |
| FR-02 | 서버 세션이 cold start로 유실된 경우, 최근 세션 요약을 복원할 수 있는 메커니즘 | High | Pending |
| FR-03 | 대화 이력이 6턴을 초과하면 오래된 대화를 요약(condense)하여 컨텍스트 효율화 | Medium | Pending |
| FR-04 | 이전 계산 결과(WageResult)를 세션에 캐싱하여 후속 계산 시 extracted_info 재활용 | High | Pending |
| FR-05 | 맥락 참조 표현("아까", "위에서 말한", "그 기준으로") 감지 시 이전 맥락 자동 주입 | Medium | Pending |
| FR-06 | Supabase에 세션 데이터를 저장/복원 (선택적 — Supabase 연동 시) | Low | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| Performance | 세션 복원 시간 < 200ms | API 응답시간 측정 |
| 데이터 크기 | 세션 요약본 < 2KB (토큰 효율) | 문자열 길이 확인 |
| 호환성 | 기존 API 인터페이스 변경 없음 (하위 호환) | 기존 테스트 통과 |
| 안정성 | 세션 복원 실패 시 새 세션으로 graceful fallback | 에러 핸들링 테스트 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] 페이지 새로고침 후에도 대화 맥락 유지 확인
- [ ] "아까 물어본 임금 기준으로 퇴직금 계산해줘" 시나리오 정상 동작
- [ ] Vercel cold start 후에도 최소 요약 맥락 복원 가능
- [ ] 기존 32개 테스트 케이스 전부 통과 (회귀 없음)
- [ ] 프론트엔드 기존 UX 변경 없음

### 4.2 Quality Criteria

- [ ] 세션 복원 실패 시 에러 없이 새 세션 생성
- [ ] 10턴 이상 대화에서도 맥락 참조 질문 정상 동작
- [ ] 세션 데이터 크기가 과도하게 증가하지 않음 (요약 기반)

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Vercel 서버리스 cold start 빈번 발생 | High | High | sessionStorage + 서버 세션 복원 2중 보호 |
| 세션 요약 시 중요 정보 누락 | Medium | Medium | 계산 결과(숫자값)는 별도 캐싱, 요약은 맥락만 |
| Supabase 의존성 추가 시 장애 전파 | Medium | Low | Supabase는 선택적(optional), 실패 시 인메모리 fallback |
| 토큰 사용량 증가 (맥락 주입) | Low | Medium | 요약본 2KB 제한, 최근 2턴 원문 + 나머지 요약 전략 |
| localStorage/sessionStorage 비활성 브라우저 | Low | Low | try-catch로 감싸고, 실패 시 기존 동작 유지 |

---

## 6. Architecture Considerations

### 6.1 Project Level Selection

| Level | Characteristics | Recommended For | Selected |
|-------|-----------------|-----------------|:--------:|
| **Starter** | Simple structure | Static sites | ☐ |
| **Dynamic** | Feature-based modules, BaaS integration | Web apps with backend | ☒ |
| **Enterprise** | Strict layer separation, DI | High-traffic systems | ☐ |

### 6.2 Key Architectural Decisions

| Decision | Options | Selected | Rationale |
|----------|---------|----------|-----------|
| 세션 저장소 | 인메모리 / Supabase / Redis | 인메모리 + Supabase(optional) | Vercel 서버리스에서 Redis 불가, Supabase는 이미 프로젝트에 연동 가능 |
| 프론트엔드 영속화 | localStorage / sessionStorage / cookie | sessionStorage | 탭 단위 격리, 브라우저 닫으면 자동 정리 |
| 세션 요약 방식 | LLM 요약 / 규칙 기반 추출 / 하이브리드 | 규칙 기반 추출 | 토큰/비용 절약, 계산 결과 캐싱은 구조화된 데이터로 충분 |
| 세션 복원 전략 | 전체 복원 / 요약 복원 / 캐시 복원 | 캐시(계산결과) + 최근 2턴 원문 | 토큰 효율과 맥락 품질 균형 |

### 6.3 3계층 메모리 아키텍처

```
┌─────────────────────────────────────────────────────┐
│ Layer 1: Frontend (sessionStorage)                  │
│   - sessionId 영속화                                │
│   - 최근 대화 이력 캐싱 (optional)                  │
├─────────────────────────────────────────────────────┤
│ Layer 2: Server Session (in-memory + condensation)  │
│   - Session.history: 최근 6턴 원문 유지             │
│   - Session.summary: 이전 대화 요약 (규칙 기반)     │
│   - Session.calc_cache: 이전 계산 결과 캐싱         │
├─────────────────────────────────────────────────────┤
│ Layer 3: Persistent Store (Supabase, optional)      │
│   - 세션 스냅샷 저장 (summary + calc_cache)         │
│   - cold start 시 복원                              │
│   - TTL: 24시간 후 자동 삭제                        │
└─────────────────────────────────────────────────────┘
```

---

## 7. Convention Prerequisites

### 7.1 Existing Project Conventions

- [x] `CLAUDE.md` has coding conventions section
- [x] Python dataclass pattern (`app/models/session.py`)
- [x] Generator-based streaming (`pipeline.py`)
- [x] In-memory store pattern (`_sessions: dict[str, Session]`)

### 7.2 Conventions to Define/Verify

| Category | Current State | To Define | Priority |
|----------|---------------|-----------|:--------:|
| **세션 데이터 직렬화** | 없음 | `Session.to_dict()` / `Session.from_dict()` | High |
| **세션 TTL** | 없음 (Vercel cold start까지) | 24시간 TTL, sessionStorage는 탭 수명 | Medium |
| **요약 포맷** | 없음 | 구조화된 dict: `{topics, calc_results, key_params}` | Medium |

### 7.3 Environment Variables Needed

| Variable | Purpose | Scope | To Be Created |
|----------|---------|-------|:-------------:|
| `SUPABASE_URL` | Supabase 프로젝트 URL | Server | ☐ (이미 존재할 수 있음) |
| `SUPABASE_KEY` | Supabase anon key | Server | ☐ (이미 존재할 수 있음) |

---

## 8. Implementation Phases

### Phase 1: 프론트엔드 sessionId 영속화 (FR-01) — Quick Win

```javascript
// public/index.html 변경
// 1. 페이지 로드 시 sessionStorage에서 sessionId 복원
// 2. SSE session 이벤트 수신 시 sessionStorage에 저장
```

예상 변경: `public/index.html` — 약 5줄 수정

### Phase 2: 계산 결과 캐싱 (FR-04) — Core

```python
# app/models/session.py 변경
# Session에 calc_cache: dict 추가
# pipeline.py에서 계산 결과를 calc_cache에 저장
# 후속 질문 시 calc_cache에서 extracted_info 프리필
```

예상 변경: `session.py`, `pipeline.py` — 약 30줄 추가

### Phase 3: 대화 요약(Condensation) (FR-03, FR-05) — Enhancement

```python
# Session.condense() 메서드 추가
# 6턴 초과 시 오래된 대화를 규칙 기반 요약
# 요약 포맷: {topics: [...], key_params: {...}, calc_results: [...]}
```

예상 변경: `session.py` — 약 50줄 추가

### Phase 4: 세션 영속 저장소 (FR-02, FR-06) — Optional

```python
# Supabase sessions 테이블에 요약+캐시 저장
# cold start 시 sessionId로 복원 시도
# 실패 시 새 세션으로 graceful fallback
```

예상 변경: 새 파일 `app/models/session_store.py` — 약 60줄

---

## 9. Next Steps

1. [ ] Write design document (`conversation-memory.design.md`)
2. [ ] Phase 1 (프론트엔드 영속화) 우선 구현 — 즉시 효과
3. [ ] Phase 2 (계산 결과 캐싱) 구현 — 핵심 가치
4. [ ] Phase 3-4는 사용자 피드백 기반으로 결정

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-12 | Initial draft | Claude |
