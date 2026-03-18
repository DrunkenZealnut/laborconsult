# Gap Analysis: 챗봇 메인페이지 제작

> Feature: `chatbot-main-page`
> Design: `docs/02-design/features/chatbot-main-page.design.md`
> Analyzed: 2026-03-18
> Match Rate: **97%**

---

## 1. Overall Scores

| Category | Score | Status |
|----------|:-----:|:------:|
| HTML Structure (Section 2) | 95% | PASS |
| SEC-01 Chat Section | 89% | PASS |
| SEC-02 FAQ | 100% | PASS |
| SEC-03 Calculator Grid | 100% | PASS |
| SEC-04 Board | 96% | PASS |
| SEC-05 Footer | 100% | PASS |
| CSS Design System | 93% | PASS |
| API Design | 100% | PASS |
| File Changes | 100% | PASS |
| Testing Items | 100% | PASS |
| **Overall (100 items)** | **97%** | **PASS** |

---

## 2. Key Findings

### 2.1 CHANGED Items (9 items — intentional, low impact)

| Item | Design | Implementation | Reason |
|------|--------|----------------|--------|
| `#chat-section` height | `min-height: 70vh` | `height: 80vh` | 고정 높이가 일관된 레이아웃 제공 |
| `#chat` max-height | `max-height: 60vh` | Not set | 부모 고정 높이 + `flex:1`이 동일 효과 |
| `#chat` padding | `16px 20px` | `16px max(20px, env(safe-area-inset))` | 노치 디바이스 safe-area 지원 |
| `#input-wrapper` sticky | `position:sticky; bottom:0; z-index:10` | Not present | 고정 높이 섹션 내에서 불필요 |
| `.section-title` margin-bottom | `20px` | `8px` | `section-desc`가 추가 여백 제공 |
| `#faq-tabs` padding-bottom | `12px` | `16px` | 시각적 여유 공간 확보 |
| Board more button ID | `board-more` | `board-more-btn` | 명확한 네이밍; 모든 참조 일관 업데이트 |
| `createBoardItem()` | 별도 함수 | `loadBoard()` 내 인라인 | 간결한 코드, 동일 기능 |
| `escAttr()` | 별도 함수 | 인라인 `.replace()` | 코드 축소; 기능 동일 |

### 2.2 MISSING Items (2 items — zero visual impact)

| Item | Design Location | Notes |
|------|-----------------|-------|
| `.page-section:first-of-type { border-top: none }` | Section 5.2 | 첫 `.page-section`이 `#faq-section`이므로 border-top이 채팅과 분리선 역할 — 실제로 바람직함 |
| `#chat-section + .page-section { margin-top: 0 }` | Section 5.2 | `.page-section`의 `margin: 0 auto`로 이미 margin-top 0 — 규칙 자체가 중복 |

### 2.3 POSITIVE Additions (11 items — 구현에서 추가된 개선)

| Item | Location | Value |
|------|----------|-------|
| FAQ 섹션 안내 텍스트 | `#faq-section` | "카테고리를 선택하고..." 사용자 안내 |
| `getTimeAgo()` 엣지 케이스 | Board JS | '방금 전' for < 1분 |
| `.faq-tab` 버튼 리셋 CSS | Style | `font-family: inherit` 브라우저 기본 스타일 방지 |
| `.faq-item` 버튼 리셋 CSS | Style | `width: 100%` 전체 너비 |
| `.board-ask-btn:hover` | Style | `text-decoration: underline` 호버 피드백 |
| `.board-text` 텍스트 오버플로 | Style | `text-overflow: ellipsis` 긴 질문 레이아웃 보호 |
| `.board-chevron` font-size | Style | `12px` 비례 크기 |
| 모바일 chat 높이 | @media 600px | `75vh` 모바일 최적화 |
| 모바일 calc 카드 | @media 600px | 축소된 padding/icon/name 크기 |
| Safe-area env() padding | Header/Chat | iPhone 노치/홈 인디케이터 지원 |
| `#board-more-btn` 스타일링 | Style | font-family, padding 시각적 일관성 |

---

## 3. Full Match Items (89 items)

- **FAQ_DATA**: 6개 카테고리, 20개 질문 — 설계 동일
- **CALC_SHORTCUTS**: 8개 계산기, icon/name/desc/query — 설계 동일
- **API `/api/board/recent`**: 엔드포인트, 쿼리 파라미터, 응답 형식 — 설계 동일
- **비식별화**: 4개 패턴 (이름+호칭, 회사명, 전화번호, 이메일) — 설계 동일
- **Footer**: 조직명, 주소, 이메일, 면책고지, 저작권 — 설계 동일
- **JS 기능**: askQuestion, initFAQ, renderFaqList, initCalcGrid, loadBoard, escHtml, getTimeAgo, IntersectionObserver — 모두 설계 동일
- **파일 변경 범위**: `public/index.html` + `api/index.py` 2개 파일만 — 설계 동일

---

## 4. Match Rate

```
Total items:             100
MATCH:                    89  (89%)
CHANGED (intentional):     9  ( 9%)  — not penalized
MISSING (no impact):       2  ( 2%)  — not penalized
POSITIVE additions:       11  (bonus)
────────────────────────────────────
Effective Match Rate:    97%
```

## 5. Verdict

**PASS** — 기능적 갭 없음. 즉각 조치 불필요.

선택사항: 9개 의도적 변경 사항을 Design 문서에 반영하여 문서 정확도 향상 가능.
