# responsive-ui Planning Document

> **Summary**: 모바일/태블릿/데스크톱 전 기기에서 최적 UX를 제공하는 반응형 UI 개선
>
> **Project**: AI 노동상담 챗봇 (nodong.kr)
> **Date**: 2026-03-08
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 현재 `@media (max-width: 600px)` 규칙 3줄뿐으로, 모바일에서 테이블 가로 스크롤 불가, 터치 타겟 부족, safe area 미지원, 가로모드 미대응 등 실사용 문제 다수 |
| **Solution** | CSS 미디어쿼리 확장 + 터치 최적화 + safe area 대응 + 테이블/코드블록 오버플로우 처리를 `public/index.html` 단일 파일에서 해결 |
| **Function/UX Effect** | 320px~1440px 전 해상도에서 읽기·입력·파일첨부·복사 기능이 자연스럽게 동작, 노치/홈인디케이터 영역 침범 제거 |
| **Core Value** | 노동 상담 챗봇의 주 사용층(근로자)이 스마트폰으로 즉시 질문할 수 있는 접근성 확보 |

---

## 1. Overview

### 1.1 Purpose

모바일 기기에서 AI 노동상담 챗봇을 사용할 때 발생하는 레이아웃 깨짐, 터치 불편, 콘텐츠 오버플로우 문제를 해결한다.

### 1.2 Background

현재 `public/index.html`의 반응형 처리는 `@media (max-width: 600px)` 규칙 3줄에 불과하다:
```css
@media (max-width: 600px) {
  .msg { max-width: 92%; }
  #input-area { padding: 10px; }
  #file-preview { padding: 8px 10px 0; }
}
```

실제 모바일 사용 시 다음 문제가 발생한다:
1. **테이블 오버플로우**: 임금계산 결과 테이블이 화면 밖으로 넘침 (가로 스크롤 불가)
2. **코드블록 오버플로우**: 긴 코드/수식이 화면 밖으로 넘침
3. **터치 타겟 부족**: 전송 버튼, 첨부 버튼이 44px 미만
4. **safe area 미지원**: iPhone 노치/Dynamic Island, 하단 홈인디케이터 영역과 UI 겹침
5. **가로모드 미대응**: 가로 모드에서 채팅 영역이 비효율적으로 배치
6. **연락처 카드 넘침**: 여러 기관 연락처가 좁은 화면에서 잘림

### 1.3 Related Documents

- 현재 UI: `public/index.html`
- API: `api/index.py`

---

## 2. Scope

### 2.1 In Scope

- [x] CSS 미디어쿼리 확장 (320px, 600px, 768px 브레이크포인트)
- [x] 테이블/코드블록 가로 스크롤 래퍼
- [x] 터치 타겟 최소 44px 보장
- [x] iOS/Android safe area 대응 (`env(safe-area-inset-*)`)
- [x] 연락처 카드 모바일 레이아웃
- [x] 가로모드 기본 대응

### 2.2 Out of Scope

- 다크모드 (별도 feature로 분리)
- PWA 변환 (Service Worker, manifest)
- 데스크톱 사이드바/분할 레이아웃
- 접근성(WCAG) 전면 개선 (별도 feature)

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | 테이블 가로 스크롤: `.msg.assistant table`이 화면 너비 초과 시 가로 스크롤 가능 | High | Pending |
| FR-02 | 코드블록 가로 스크롤: `pre` 요소가 화면 너비 초과 시 가로 스크롤 가능 | High | Pending |
| FR-03 | 터치 타겟: 전송 버튼, 첨부 버튼, 파일 삭제(×) 버튼 최소 44×44px | High | Pending |
| FR-04 | safe area: 노치/Dynamic Island 영역과 UI 겹침 방지, 하단 홈인디케이터 위 여백 | High | Pending |
| FR-05 | 연락처 카드: 모바일에서 세로 스택 또는 가로 스크롤 처리 | Medium | Pending |
| FR-06 | 헤더 축소: 모바일에서 불필요한 부제목 숨기거나 축소 | Low | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| Performance | CSS 추가로 인한 파일 크기 증가 < 2KB | 파일 크기 비교 |
| Compatibility | iOS Safari 15+, Chrome Android 100+, Samsung Internet 20+ | 수동 확인 또는 BrowserStack |
| UX | 320px 화면에서 모든 기능 사용 가능 | 320px viewport 테스트 |
| Existing Behavior | 데스크톱(>768px) 레이아웃 변경 없음 | 비교 확인 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] 6개 FR 전부 구현
- [ ] iPhone SE (375px), iPhone 15 Pro (393px), iPad (768px) 뷰포트에서 정상 동작
- [ ] 기존 데스크톱 레이아웃 변경 없음
- [ ] `public/index.html` 단일 파일 수정으로 완료

### 4.2 Quality Criteria

- [ ] 테이블이 포함된 답변에서 가로 스크롤 정상 동작
- [ ] 모든 터치 타겟 44px 이상
- [ ] safe area 적용 확인 (padding 적용)

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| CSS 추가가 기존 데스크톱 레이아웃 깨뜨림 | High | Low | 미디어쿼리 내부에서만 변경, 기존 규칙 유지 |
| safe area CSS가 구형 브라우저 미지원 | Low | Medium | `@supports` 또는 fallback padding 사용 |
| 테이블 스크롤 래퍼가 JS 마크다운 렌더링과 충돌 | Medium | Low | CSS만으로 해결 (`overflow-x: auto` on parent) |

---

## 6. Architecture Considerations

### 6.1 Project Level Selection

| Level | Selected |
|-------|:--------:|
| **Starter** | ✅ |

순수 CSS 변경, `public/index.html` 단일 파일 수정.

### 6.2 Key Architectural Decisions

| Decision | Selected | Rationale |
|----------|----------|-----------|
| 변경 범위 | CSS only | JS 로직 변경 불필요, CSS 미디어쿼리로 충분 |
| 브레이크포인트 | 600px (기존) + 768px (태블릿) | 기존 600px 유지하며 태블릿 추가 |
| safe area 방식 | `env(safe-area-inset-*)` | 표준 CSS 환경변수, 폭넓은 지원 |

---

## 7. Convention Prerequisites

### 7.1 Existing Conventions

- [x] `CLAUDE.md` 코딩 컨벤션 존재
- [x] `.env.example` 환경변수 정의 완료
- 별도 lint/prettier 없음 (단일 HTML 파일)

### 7.2 Conventions to Follow

| Category | Rule |
|----------|------|
| CSS 변수 | 기존 `:root` 변수 체계 유지 (`--primary`, `--bg`, `--card` 등) |
| 미디어쿼리 | mobile-first 아닌 기존 desktop-first 유지 (`max-width`) |
| 단위 | `px` 기본, safe area만 `env()` 사용 |

---

## 8. Next Steps

1. [ ] Design 문서 작성 (`/pdca design responsive-ui`)
2. [ ] 구현 (CSS 수정)
3. [ ] 모바일 뷰포트 테스트

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 0.1 | 2026-03-08 | Initial draft |
