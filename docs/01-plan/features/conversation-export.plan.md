# conversation-export Plan

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | 대화 내용 전체를 마크다운 파일로 저장/다운로드 |
| 시작일 | 2026-03-16 |
| 예상 기간 | 반나절 |

### Value Delivered

| 관점 | 내용 |
|------|------|
| Problem | 사용자가 상담 받은 대화 내용을 보관하거나 공유할 방법이 없음 |
| Solution | 프론트엔드에 "대화 저장" 버튼 → 전체 대화를 마크다운 파일로 다운로드 |
| Function UX Effect | 한 번의 클릭으로 상담 내용을 .md 파일로 저장, 나중에 참조 가능 |
| Core Value | 노동 상담의 접근성·재활용성 향상 — 증빙자료·기록 보관 용도 |

---

## 1. 현황 분석

### 1.1 현재 저장 방식

| 구분 | 위치 | 내용 | 사용자 접근 |
|------|------|------|-----------|
| Supabase `qa_conversations` | 서버 DB | 질문+답변 개별 저장 | ❌ 불가 |
| Supabase `qa_sessions` | 서버 DB | 세션 스냅샷 (대화 이력) | ❌ 불가 |
| 브라우저 DOM | 프론트엔드 | 렌더링된 대화 | ❌ 새로고침 시 소멸 |
| `d.dataset.md` | 프론트엔드 | 원본 마크다운 텍스트 | ❌ 접근 불가 |

**문제**: 사용자가 대화 내용을 다운로드하거나 복사하는 기능 없음 (개별 복사 버튼만 존재).

### 1.2 마크다운 데이터 흐름

```
Claude 스트리밍 → SSE chunk → fullText (원본 md) → md(fullText) (HTML 변환) → DOM 렌더링
                                     ↓
                              d.dataset.md = rawMarkdown  (assistant 메시지에 저장)
```

`addMsg('assistant', html, rawMarkdown)` 호출 시 `dataset.md`에 원본 마크다운이 저장됨.
사용자 메시지는 `addMsg('user', displayHtml)`로 HTML만 저장, 원본 텍스트는 `input` 값.

---

## 2. 구현 계획

### 2.1 프론트엔드 전용 구현 (서버 변경 불필요)

**구현 위치**: `public/index.html`에 JavaScript 함수 추가

#### 마크다운 내보내기 포맷

```markdown
# 노동OK 상담 기록

> 날짜: 2026-03-16
> 세션 ID: abc123

---

## 질문 1

{사용자 질문 텍스트}

## 답변 1

{AI 답변 마크다운 원본}

---

## 질문 2

{사용자 질문 텍스트}

## 답변 2

{AI 답변 마크다운 원본}

---

> 본 상담 기록은 AI가 제공한 참고 정보이며, 법적 효력이 없습니다.
> 정확한 사항은 고용노동부(☎ 1350) 또는 공인노무사에게 확인하시기 바랍니다.
```

#### 핵심 함수

```javascript
function exportChatMarkdown() {
    // 1. DOM에서 모든 msg-wrapper를 순회
    // 2. user → 질문 텍스트 추출 (innerText)
    // 3. assistant → dataset.md (원본 마크다운) 또는 innerText 폴백
    // 4. 마크다운 포맷으로 조합
    // 5. Blob → URL.createObjectURL → <a download> 트리거
}
```

#### UI

- 헤더 영역에 "대화 저장" 버튼 (📥 아이콘)
- 대화가 1건 이상일 때만 활성화
- 클릭 시 `노동OK_상담_YYYYMMDD_HHMMSS.md` 파일 자동 다운로드

---

## 3. 파일 변경 목록

| 파일 | 변경 | 내용 |
|------|------|------|
| `public/index.html` | MODIFY | 내보내기 함수 + 버튼 추가 |

서버 측 변경 없음 (프론트엔드 전용 기능).

---

## 4. 의사결정 사항

| # | 질문 | 권장 |
|---|------|------|
| 1 | 저장 형식 | `.md` (마크다운) — 가독성 + 범용성 |
| 2 | 파일명 | `노동OK_상담_YYYYMMDD_HHMMSS.md` |
| 3 | 면책 고지 포함 | ✅ 파일 하단에 자동 포함 |
| 4 | 서버 API 필요? | ❌ 프론트엔드 전용으로 충분 |
