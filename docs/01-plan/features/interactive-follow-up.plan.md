# Plan: Interactive Follow-Up Questions (추가정보 수집 대화)

## Executive Summary

| Item | Detail |
|------|--------|
| Feature | interactive-follow-up |
| Created | 2026-03-07 |
| Status | Plan |

### Value Delivered

| Perspective | Description |
|------------|-------------|
| Problem | 사용자가 불완전한 정보로 질문하면 챗봇이 부정확한 답변을 생성하거나 기본값으로 계산하여 신뢰도가 낮아짐 |
| Solution | 질문 분석 후 누락 정보를 식별하여 사용자에게 추가 질문 → 보충 정보를 합쳐 정확한 답변 생성 |
| Function UX Effect | 사용자가 임금/수당 질문 시 자동으로 필수 정보를 안내받아, 한 번의 추가 입력으로 정확한 계산 결과를 받음 |
| Core Value | 상담 정확도 향상 + 사용자 경험 개선 (노무사 대면 상담과 유사한 대화형 UX) |

---

## 1. Problem Statement

### 현재 상태 (AS-IS)
- `chatbot.py` / `app/core/pipeline.py`가 질문을 받으면 즉시 파라미터 추출 → 계산 → 답변 생성
- `_extract_params()`가 질문에서 추출 가능한 정보만 사용하고, 누락 정보는 무시하거나 기본값(월급, 5인이상 등) 적용
- 예: "퇴직금 얼마인가요?"만 질문하면 → 임금액, 근무기간, 사업장 규모 모두 빠져 계산 불가 → 답변 품질 저하

### 목표 상태 (TO-BE)
- 질문 분석 단계에서 `missing_info` 식별 → 사용자에게 추가 질문
- 사용자가 추가 정보 입력 → 원래 질문 + 추가 정보 병합하여 정확한 계산/답변 생성
- 일반 법률 상담(계산 불필요)은 추가 질문 없이 즉시 답변

### 근거
- `analyze_qna.py` 분석 결과: 10,000건 Q&A 중 계산 필요 질문의 **60% 이상**이 필수 정보(임금액, 근무시간, 사업장 규모) 누락
- 기존 부분 구현체 발견: `app/core/analyzer.py`, `app/core/composer.py`, `app/models/schemas 2.py`, `app/core/pipeline 2.py`, `app/models/session 2.py`

---

## 2. Scope

### In-Scope
1. **질문 분석기** (`analyzer.py`): 질문에서 `requires_calculation`, `extracted_info`, `missing_info` 추출
2. **추가 질문 생성** (`composer.py::compose_follow_up`): 누락 정보를 자연어 추가 질문으로 변환
3. **세션 상태 관리** (`session.py`): pending analysis 저장, 추가 정보 병합
4. **파이프라인 통합** (`pipeline.py`): 분석 → 추가질문 → 병합 → 계산 → 답변 흐름
5. **API 이벤트** (`api/index.py`): `follow_up` 이벤트 타입 처리 (이미 부분 구현됨)
6. **프론트엔드** (`public/index.html`): 추가 질문 UI 표시 + 사용자 응답 처리

### Out-of-Scope
- 다단계 추가 질문 (1회만 추가 질문, 여전히 부족하면 있는 정보로 답변)
- 추가 질문 건너뛰기 기능 (향후 버전)
- CLI chatbot.py 적용 (웹 API 우선)

---

## 3. Architecture Overview

### 파이프라인 흐름

```
사용자 질문
    │
    ▼
① 의도 분석 (analyze_intent)
    ├── requires_calculation = true
    │   ├── missing_info 있음 → ② 추가 질문 생성 → yield follow_up → return
    │   └── missing_info 없음 → ③으로 진행
    └── requires_calculation = false → ③으로 진행

사용자 추가 정보 입력
    │
    ▼
① 재분석 (analyze_intent) → pending 정보 병합
    │
    ▼
③ 임금계산기 실행 (run_calculation)
    │
    ▼
④ RAG 검색 (Q&A + 법령/판례)
    │
    ▼
⑤ 통합 답변 생성 (compose_answer, streaming)
```

### 핵심 컴포넌트

| Component | File | Role |
|-----------|------|------|
| AnalysisResult | `app/models/schemas.py` | 분석 결과 모델 (missing_info 포함) |
| Session | `app/models/session.py` | pending analysis 저장/병합 |
| analyze_intent | `app/core/analyzer.py` | Claude tool_use로 질문 분석 |
| compose_follow_up | `app/core/composer.py` | 추가 질문 텍스트 생성 |
| process_question | `app/core/pipeline.py` | 전체 흐름 오케스트레이션 |
| API handlers | `api/index.py` | follow_up 이벤트 SSE/JSON 처리 |
| Frontend | `public/index.html` | follow_up 이벤트 UI 렌더링 |

---

## 4. Key Design Decisions

### D1: 추가 질문은 1회만
- 사용자 경험상 2회 이상 추가 질문은 이탈률 급증
- 1회 추가 질문 후에도 정보 부족하면 있는 정보 + 기본값으로 계산하고 가정 사항 명시

### D2: 계산 필요 질문만 추가 질문
- `requires_calculation=true` && `missing_info` 비어있지 않을 때만
- 일반 법률 상담은 RAG 기반 즉시 답변

### D3: 기존 `pipeline 2.py` 설계 채택
- 이미 설계된 `pipeline 2.py`의 흐름 (analyze → follow_up → merge → calculate → answer)을 현재 `pipeline.py`에 통합
- `analyzer.py`, `composer.py`는 이미 구현되어 있으므로 활용

### D4: 세션 pending 상태 관리
- `Session`에 `_pending_analysis` 필드 추가
- `save_pending(analysis)`: 분석 결과 임시 저장
- `merge_with_pending(new_analysis, follow_up_text)`: 기존 추출 정보 + 추가 정보 병합
- `has_pending_info()`: pending 상태 확인

### D5: 프론트엔드 follow_up 처리
- `follow_up` 이벤트 수신 시 assistant 메시지로 표시 (일반 답변과 동일 스타일)
- 사용자가 추가 정보 입력하면 일반 질문과 동일하게 전송
- 세션 ID로 서버에서 pending 상태를 자동 복원

---

## 5. Implementation Plan

### Phase 1: 모델 & 세션 확장
- `app/models/schemas.py`에 `AnalysisResult` 추가
- `app/models/session.py`에 `save_pending`, `has_pending_info`, `merge_with_pending` 메서드 추가

### Phase 2: 파이프라인 통합
- `app/core/pipeline.py`에 `analyzer.py` 기반 분석 단계 추가
- `missing_info` → `compose_follow_up` → `yield follow_up` 흐름 구현
- pending 병합 후 기존 계산/RAG/답변 흐름 유지

### Phase 3: 프론트엔드 대응
- `public/index.html`의 `readSSE()`에서 `follow_up` 이벤트 처리
- 추가 질문을 assistant 메시지로 렌더링

### Phase 4: CLI 챗봇 적용 (선택)
- `chatbot.py`에도 동일 로직 적용 (터미널 UX)

---

## 6. Existing Code Assets

이미 구현된 코드 (활용 가능):

| File | Status | Notes |
|------|--------|-------|
| `app/core/analyzer.py` | 완성 | `analyze_intent()` — Claude tool_use 기반 분석 |
| `app/templates/prompts.py` | 완성 | `ANALYZE_TOOL`, `ANALYZER_SYSTEM`, `COMPOSER_SYSTEM` |
| `app/core/composer.py` | 완성 | `compose_follow_up()`, `compose_answer()` |
| `app/core/pipeline 2.py` | 설계 완료 | 참조용 — 현재 pipeline.py에 통합 필요 |
| `app/models/schemas 2.py` | 설계 완료 | `AnalysisResult` 모델 정의 |
| `app/models/session 2.py` | 설계 완료 | pending 관련 메서드 포함 |
| `api/index.py:60-65` | 부분 구현 | `follow_up` 이벤트 처리 핸들러 |

---

## 7. Missing Info Categories (분석 기반)

10,000건 Q&A 분석에서 도출된 주요 누락 정보:

| Category | Missing Info | Calculator Types |
|----------|-------------|------------------|
| 임금정보 | 임금형태(시급/월급), 임금액 | 전체 |
| 근무시간 | 주 소정근로시간, 1일 근로시간 | overtime, weekly_holiday, minimum_wage |
| 근무기간 | 입사일, 퇴직일, 근무기간 | severance, annual_leave, dismissal, unemployment |
| 사업장규모 | 5인미만/이상 여부 | overtime, annual_leave, dismissal |
| 수당정보 | 고정수당 목록, 포괄산입 여부 | comprehensive, minimum_wage |
| 가구정보 | 가구유형, 연소득, 재산 | eitc |

---

## 8. Risk & Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| 추가 질문으로 사용자 이탈 | High | 1회 제한 + 필수 정보만 질문 |
| 분석 모델 비용 증가 | Medium | Haiku 모델 사용 (저비용), 일반 질문은 분석 스킵 |
| pending 상태 유실 (서버 재시작) | Low | 인메모리 세션 → 향후 Redis 전환 가능 |
| 사용자가 추가 질문을 무시하고 새 질문 | Medium | pending 상태 자동 만료 (다음 질문 시 새 분석) |

---

## 9. Success Criteria

- [ ] 계산 필요 질문에서 missing_info 감지 시 추가 질문 생성
- [ ] 사용자 추가 정보 입력 후 원래 질문 + 추가 정보 병합하여 정확한 답변
- [ ] 일반 법률 상담 질문은 추가 질문 없이 즉시 답변
- [ ] 프론트엔드에서 추가 질문이 자연스럽게 표시됨
- [ ] 기존 계산기/RAG/스트리밍 기능 그대로 유지
