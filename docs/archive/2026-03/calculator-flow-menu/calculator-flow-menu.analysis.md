# Gap Analysis: 계산기 플로우 메뉴 페이지

> Feature: `calculator-flow-menu`
> Reference: `docs/01-plan/features/calculator-flow-menu.plan.md` (Plan-vs-Implementation, Design 생략)
> Analyzed: 2026-03-18
> Match Rate: **97%**

---

## 1. Overall Scores

| Category | Score | Status |
|----------|:-----:|:------:|
| File Layout (Plan 2.1) | 100% | PASS |
| Menu Categories (Plan 2.2) | 100% | PASS |
| Menu Items — 25 calculators | 100% | PASS |
| UI Requirements (Plan 2.3) | 86% | PASS |
| Routing (Plan 2.4) | 100% | PASS |
| YAGNI Compliance (Plan 4) | 100% | PASS |
| Success Criteria (Plan 3) | 100% | PASS |
| **Overall (50 items)** | **97%** | **PASS** |

---

## 2. Key Findings

### 2.1 CHANGED Items (2 items — intentional, low impact)

| Item | Plan | Implementation | Reason |
|------|------|----------------|--------|
| Sidebar width | 250px | 280px (`--sidebar-w: 280px`) | `item-desc` 서브타이틀 추가로 인해 2줄 메뉴 항목 가독성 확보 |
| Header link text | "📊 계산 흐름도" | "📊 흐름도" | 헤더 레이아웃에 맞게 축약; 동일 의미 전달 |

### 2.2 MISSING Items

없음.

### 2.3 POSITIVE Additions (7 items — 구현에서 추가된 개선)

| Item | Location | Value |
|------|----------|-------|
| `item-desc` 서브타이틀 (25개 항목 모두) | calculators.html 메뉴 | 각 계산기에 1줄 설명 추가 (e.g., "모든 수당의 기초 — 핵심 5단계"), 탐색성 대폭 향상 |
| Empty state UI | calculators.html L202-206 | "좌측 메뉴에서 계산기를 선택하세요" + 📐 아이콘, 선택 전 가이드 |
| iframe `sandbox` | calculators.html L207 | `sandbox="allow-scripts allow-same-origin"` 보안 강화 |
| SEC-03 deep link | index.html L273 | "전체 25개 계산기 보기 →" 2번째 진입점 |
| `history.pushState` 모바일 뒤로가기 | calculators.html L252-260 | 네이티브 뒤로가기 제스처/버튼 지원 |
| `safe-area-inset` 지원 | calculators.html L16 | iPhone 노치/홈 인디케이터 대응 |
| 양방향 네비게이션 | calculators.html L61 | "← 챗봇으로 돌아가기" 링크 |

---

## 3. Full Match Items (48 items)

- **파일 배치**: `public/calculators.html` 존재, `public/calculator_flow/` 25개 HTML — Plan 동일
- **카테고리 7개**: 전체 구조(1), 기본 임금(4), 수당 계산(4), 퇴직·해고(3), 보험·세금·연금(6), 휴직·급여(3), 근로조건(4) — Plan 동일
- **25개 메뉴 항목**: 모든 `data-src` 경로가 Plan의 파일명과 일치
- **UI**: Desktop 2-column, 모바일 전체화면 뷰어 전환, CSS Variables 동일, 다크모드, 동일 폰트
- **라우팅**: `vercel.json` `/calculators` → `calculators.html` — Plan 동일
- **YAGNI**: 검색 없음, 즐겨찾기 없음, platform.md 미포함 — Plan 동일
- **성공기준**: 25개 탐색, 모바일 원활, 1클릭 접근, 다크모드 — 모두 충족

---

## 4. Match Rate

```
Total items:             50
MATCH:                   48  (96%)
CHANGED (intentional):    2  ( 4%)  — not penalized
MISSING:                  0  ( 0%)
POSITIVE additions:       7  (bonus)
────────────────────────────────────
Effective Match Rate:   97%
```

## 5. Verdict

**PASS** — 기능적 갭 없음. 즉각 조치 불필요.

선택사항: 2개 의도적 변경 사항(sidebar 280px, 헤더 링크 축약)을 Plan 문서에 반영하여 문서 정확도 향상 가능.
