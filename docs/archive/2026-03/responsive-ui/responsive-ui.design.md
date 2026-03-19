# responsive-ui Design Document

> **Summary**: 모바일/태블릿 반응형 UI 개선 — CSS 미디어쿼리 확장 + safe area + 터치 최적화
>
> **Project**: AI 노동상담 챗봇 (nodong.kr)
> **Date**: 2026-03-08
> **Status**: Draft
> **Planning Doc**: [responsive-ui.plan.md](../../01-plan/features/responsive-ui.plan.md)

---

## 1. Overview

### 1.1 Design Goals

- `public/index.html` 단일 파일 수정으로 모바일 UX 문제 6건 해결
- 기존 데스크톱(>768px) 레이아웃 변경 없음
- CSS 추가량 < 2KB

### 1.2 Design Principles

- **CSS Only**: JS 로직 변경 최소화, CSS 미디어쿼리와 속성으로 해결
- **Desktop-First 유지**: 기존 `max-width` 미디어쿼리 패턴 유지
- **Progressive Enhancement**: safe area 미지원 브라우저에서도 정상 동작

---

## 2. 현재 상태 분석

### 2.1 기존 CSS 구조

```
:root (CSS 변수) → 전역 스타일 → 컴포넌트별 스타일 → @media (max-width: 600px)
```

기존 미디어쿼리 (3줄):
```css
@media (max-width: 600px) {
  .msg { max-width: 92%; }
  #input-area { padding: 10px; }
  #file-preview { padding: 8px 10px 0; }
}
```

### 2.2 문제 요소별 현재 CSS

| 요소 | 현재 CSS | 문제점 |
|------|----------|--------|
| `.msg.assistant table` | `width: auto;` + `th,td { white-space: nowrap; }` | 가로 오버플로우, 스크롤 불가 |
| `.msg.assistant pre` | `overflow-x: auto;` | 이미 스크롤 가능하나 `max-width` 제약 없음 |
| `#send-btn` | `padding: 10px 20px;` | 높이 ~37px (44px 미만) |
| `#attach-btn` | `padding: 8px;` | 크기 ~36px (44px 미만) |
| `.file-chip .remove` | 크기 미지정 | 터치 타겟 매우 작음 |
| `<meta viewport>` | `width=device-width, initial-scale=1.0` | `viewport-fit=cover` 없어 safe area 미작동 |
| `header`, `#input-wrapper`, `.disclaimer` | 일반 padding | safe area inset 미적용 |
| `.contact-bar` | `flex-wrap: wrap; max-width: 80%` | 모바일에서 `max-width` 제한으로 좁음 |

---

## 3. 구현 명세

### 3.1 수정 파일 목록

| # | 파일 | 작업 | FR |
|:-:|------|:----:|:---:|
| 1 | `public/index.html` | 수정 | FR-01~06 전체 |

단일 파일 수정. 변경 영역: (A) `<meta viewport>` 태그, (B) CSS `<style>` 블록.

### 3.2 FR-01: 테이블 가로 스크롤

**변경 위치**: `.msg.assistant table` 스타일 (기존 line 45-46)

**현재:**
```css
.msg.assistant table { border-collapse: collapse; margin: 8px 0; font-size: 14px; width: auto; }
.msg.assistant th, .msg.assistant td { border: 1px solid var(--border); padding: 6px 12px; text-align: left; white-space: nowrap; }
```

**변경:**
```css
.msg.assistant table { border-collapse: collapse; margin: 8px 0; font-size: 14px; width: auto; display: block; overflow-x: auto; -webkit-overflow-scrolling: touch; }
.msg.assistant th, .msg.assistant td { border: 1px solid var(--border); padding: 6px 12px; text-align: left; white-space: nowrap; }
```

**추가된 속성:**
- `display: block` — 테이블을 블록 요소로 변환하여 `overflow-x` 적용 가능
- `overflow-x: auto` — 내용이 넘칠 때 가로 스크롤바 표시
- `-webkit-overflow-scrolling: touch` — iOS에서 관성 스크롤

### 3.3 FR-02: 코드블록 가로 스크롤

**현재** (line 49):
```css
.msg.assistant pre { background: var(--bg); padding: 10px; border-radius: 6px; overflow-x: auto; margin: 8px 0; }
```

**변경:** `max-width` 추가로 부모(.msg) 내에서 제한
```css
.msg.assistant pre { background: var(--bg); padding: 10px; border-radius: 6px; overflow-x: auto; -webkit-overflow-scrolling: touch; margin: 8px 0; max-width: calc(100% + 0px); }
```

> 참고: `overflow-x: auto`는 이미 있으므로 `-webkit-overflow-scrolling: touch`만 추가. `max-width`는 부모 `.msg`의 `word-break: break-word`와 함께 이미 제약되므로 실질적 변경 최소.

### 3.4 FR-03: 터치 타겟 44px 보장

**모바일 미디어쿼리 내부에 추가** (`@media (max-width: 600px)`):

```css
@media (max-width: 600px) {
  /* 기존 규칙 유지 */
  .msg { max-width: 92%; }
  #input-area { padding: 10px; }
  #file-preview { padding: 8px 10px 0; }

  /* FR-03: 터치 타겟 */
  #send-btn { min-height: 44px; min-width: 44px; padding: 10px 16px; }
  #attach-btn { min-width: 44px; min-height: 44px; }
  .file-chip .remove { display: inline-flex; align-items: center; justify-content: center; min-width: 28px; min-height: 28px; font-size: 18px; }
}
```

**설계 근거:**
- Apple HIG 최소 터치 타겟: 44×44pt
- `#send-btn`: `min-height: 44px` 추가, padding 소폭 축소로 너비 절약
- `#attach-btn`: `min-width/min-height: 44px` 추가
- `.file-chip .remove`: 28px (주요 CTA가 아니므로 약간 작게, 단 터치 가능 수준)

### 3.5 FR-04: Safe Area 대응

**A. HTML 변경** — `<meta viewport>` 태그 수정 (line 5):

**현재:**
```html
<meta name="viewport" content="width=device-width, initial-scale=1.0">
```

**변경:**
```html
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
```

**B. CSS 변경** — safe area padding 추가 (전역, 미디어쿼리 밖):

```css
/* Safe area — 노치/홈인디케이터 대응 */
header { padding-left: max(20px, env(safe-area-inset-left)); padding-right: max(20px, env(safe-area-inset-right)); padding-top: max(12px, env(safe-area-inset-top)); }
#input-wrapper { padding-bottom: env(safe-area-inset-bottom); }
.disclaimer { padding-bottom: max(6px, env(safe-area-inset-bottom)); }
#chat { padding-left: max(16px, env(safe-area-inset-left)); padding-right: max(16px, env(safe-area-inset-right)); }
```

**설계 근거:**
- `viewport-fit=cover`가 있어야 `env(safe-area-inset-*)` 활성화
- `max()` 함수로 safe area가 없는 기기에서도 기존 padding 유지
- `header`: 상단 safe area (노치/Dynamic Island)
- `#input-wrapper`: 하단 safe area (홈인디케이터)
- `#chat`: 좌우 safe area (가로모드)

### 3.6 FR-05: 연락처 카드 모바일 레이아웃

**모바일 미디어쿼리 내부에 추가:**

```css
@media (max-width: 600px) {
  /* FR-05: 연락처 카드 */
  .contact-bar { max-width: 100%; }
  .contact-chip { flex: 1 1 100%; min-width: 0; }
}
```

**설계 근거:**
- 현재 `.contact-bar`의 `max-width: 80%`는 데스크톱용 — 모바일에서 100%로 확대
- `.contact-chip`에 `flex: 1 1 100%`로 한 줄에 하나씩 스택
- `min-width: 0`으로 flex 축소 허용

### 3.7 FR-06: 헤더 축소

**모바일 미디어쿼리 내부에 추가:**

```css
@media (max-width: 600px) {
  /* FR-06: 헤더 축소 */
  header h1 { font-size: 16px; }
  header span { font-size: 11px; }
}
```

**설계 근거:**
- `h1` 18px → 16px, `span` 13px → 11px로 축소
- 부제목 완전 숨기지 않음 (정보 손실 방지)

---

## 4. 전체 변경 요약

### 4.1 HTML 변경 (1건)

```diff
- <meta name="viewport" content="width=device-width, initial-scale=1.0">
+ <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
```

### 4.2 전역 CSS 변경 (미디어쿼리 밖)

| 선택자 | 추가 속성 | FR |
|--------|-----------|:---:|
| `.msg.assistant table` | `display: block; overflow-x: auto; -webkit-overflow-scrolling: touch;` | FR-01 |
| `.msg.assistant pre` | `-webkit-overflow-scrolling: touch;` | FR-02 |
| `header` | `padding-*: max(기존값, env(safe-area-inset-*));` | FR-04 |
| `#chat` | `padding-left/right: max(16px, env(safe-area-inset-*));` | FR-04 |
| `#input-wrapper` | `padding-bottom: env(safe-area-inset-bottom);` | FR-04 |
| `.disclaimer` | `padding-bottom: max(6px, env(safe-area-inset-bottom));` | FR-04 |

### 4.3 모바일 미디어쿼리 추가 (`@media (max-width: 600px)`)

| 선택자 | 속성 | FR |
|--------|------|:---:|
| `#send-btn` | `min-height: 44px; min-width: 44px; padding: 10px 16px;` | FR-03 |
| `#attach-btn` | `min-width: 44px; min-height: 44px;` | FR-03 |
| `.file-chip .remove` | `display: inline-flex; align-items: center; justify-content: center; min-width: 28px; min-height: 28px; font-size: 18px;` | FR-03 |
| `.contact-bar` | `max-width: 100%;` | FR-05 |
| `.contact-chip` | `flex: 1 1 100%; min-width: 0;` | FR-05 |
| `header h1` | `font-size: 16px;` | FR-06 |
| `header span` | `font-size: 11px;` | FR-06 |

---

## 5. NFR 검증 기준

| NFR | 기준 | 검증 방법 |
|-----|------|-----------|
| NFR-01 | CSS 추가 < 2KB | 수정 전후 파일 크기 diff |
| NFR-02 | iOS Safari 15+, Chrome Android 100+ 정상 | DevTools 모바일 에뮬레이션 |
| NFR-03 | 320px 뷰포트에서 모든 기능 사용 가능 | Chrome DevTools 320px 설정 |
| NFR-04 | 데스크톱(>768px) 레이아웃 변경 없음 | 수정 전후 데스크톱 비교 |

---

## 6. 구현 순서

1. [ ] `<meta viewport>`에 `viewport-fit=cover` 추가 (FR-04 전제조건)
2. [ ] 전역 CSS: 테이블 `display: block; overflow-x: auto` (FR-01)
3. [ ] 전역 CSS: `pre`에 `-webkit-overflow-scrolling: touch` (FR-02)
4. [ ] 전역 CSS: safe area padding — `header`, `#chat`, `#input-wrapper`, `.disclaimer` (FR-04)
5. [ ] 모바일 미디어쿼리: 터치 타겟 확대 (FR-03)
6. [ ] 모바일 미디어쿼리: 연락처 카드 스택 (FR-05)
7. [ ] 모바일 미디어쿼리: 헤더 축소 (FR-06)

---

## 7. Gap Analysis 기준

| 항목 | 비중 |
|------|:----:|
| 파일 완성도 (1개 파일) | 30% |
| FR 구현율 (6개 항목) | 40% |
| NFR 준수 (4개 항목) | 20% |
| 기존 동작 보존 | 10% |

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 0.1 | 2026-03-08 | Initial draft |
