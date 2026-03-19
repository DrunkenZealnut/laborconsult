# Gap Analysis: responsive-ui

> Design: `docs/02-design/features/responsive-ui.design.md`
> 분석일: 2026-03-09

---

## 1. 파일 완성도 (30%)

Design §3.1 기준 1개 파일 → 실제 1개 파일 수정.

| # | 파일 | Design 작업 | 존재 | 비고 |
|:-:|------|:----------:|:----:|------|
| 1 | `public/index.html` | 수정 | ✅ | HTML 1건 + CSS 변경 전체 포함 |

**파일 완성도: 100% (1/1)**

---

## 2. FR 구현율 (40%)

### FR-01: 테이블 가로 스크롤 ✅

| 항목 | Design 요구 | 구현 상태 | 코드 위치 |
|------|-----------|:--------:|----------|
| `display: block` | 테이블 블록 변환 | ✅ | line 45 |
| `overflow-x: auto` | 가로 스크롤 | ✅ | line 45 |
| `-webkit-overflow-scrolling: touch` | iOS 관성 스크롤 | ✅ | line 45 |

**FR-01: 3/3 속성 구현 (100%)**

### FR-02: 코드블록 가로 스크롤 ✅

| 항목 | Design 요구 | 구현 상태 | 코드 위치 |
|------|-----------|:--------:|----------|
| `-webkit-overflow-scrolling: touch` | iOS 관성 스크롤 추가 | ✅ | line 49 |

> `overflow-x: auto`는 기존부터 존재. Design에서 `max-width: calc(100% + 0px)` 추가 제안이 있었으나, 실질적 효과 없는 속성이므로 생략. 기능적으로 동일 목적 달성.

**FR-02: 핵심 속성 구현 (100%)**

### FR-03: 터치 타겟 44px ✅

| 항목 | Design 요구 | 구현 상태 | 코드 위치 |
|------|-----------|:--------:|----------|
| `#send-btn` min-height: 44px | 최소 높이 44px | ✅ | line 96 |
| `#send-btn` min-width: 44px | 최소 너비 44px | ✅ | line 96 |
| `#attach-btn` min-width/height: 44px | 최소 크기 44px | ✅ | line 97 |
| `.file-chip .remove` min 28px | 삭제 버튼 28px | ✅ | line 98 |

**FR-03: 4/4 항목 구현 (100%)**

### FR-04: Safe Area 대응 ✅

| 항목 | Design 요구 | 구현 상태 | 코드 위치 |
|------|-----------|:--------:|----------|
| `viewport-fit=cover` | meta 태그 수정 | ✅ | line 5 |
| `header` safe area padding | top/left/right inset | ✅ | line 14 |
| `#chat` safe area padding | left/right inset | ✅ | line 18 |
| `#input-wrapper` safe area | bottom inset | ✅ | line 70 |
| `.disclaimer` safe area | bottom inset | ✅ | line 89 |

**FR-04: 5/5 항목 구현 (100%)**

### FR-05: 연락처 카드 모바일 레이아웃 ✅

| 항목 | Design 요구 | 구현 상태 | 코드 위치 |
|------|-----------|:--------:|----------|
| `.contact-bar` max-width: 100% | 모바일 전체 너비 | ✅ | line 100 |
| `.contact-chip` flex: 1 1 100% | 세로 스택 | ✅ | line 101 |

**FR-05: 2/2 항목 구현 (100%)**

### FR-06: 헤더 축소 ✅

| 항목 | Design 요구 | 구현 상태 | 코드 위치 |
|------|-----------|:--------:|----------|
| `header h1` font-size: 16px | 18→16px 축소 | ✅ | line 103 |
| `header span` font-size: 11px | 13→11px 축소 | ✅ | line 104 |

**FR-06: 2/2 항목 구현 (100%)**

**FR 전체 구현율: 6/6 = 100%**

---

## 3. NFR 준수 (20%)

| NFR | 기준 | 충족 | 근거 |
|-----|------|:----:|------|
| NFR-01 CSS < 2KB | 추가 CSS 2KB 미만 | ✅ | 약 15줄 추가, ~800 bytes |
| NFR-02 브라우저 호환 | iOS Safari 15+, Chrome Android 100+ | ✅ | `env()`, `max()`, `display: block` 모두 지원 |
| NFR-03 320px 동작 | 320px에서 기능 사용 가능 | ✅ | 모든 overflow 처리, 터치 타겟 확보 |
| NFR-04 데스크톱 보존 | >768px 레이아웃 변경 없음 | ✅ | 전역 변경은 `max()`로 기존값 유지, 나머지는 `@media (max-width: 600px)` 내부 |

**NFR 준수: 4/4 = 100%**

---

## 4. 기존 동작 보존 (10%)

| 항목 | 검증 |
|------|:----:|
| 데스크톱 header padding 유지 | ✅ `max(12px, env(...))` → safe area 없으면 기존 12px |
| 데스크톱 chat padding 유지 | ✅ `max(20px, env(...))` → safe area 없으면 기존 20px |
| 테이블 데스크톱 렌더링 | ✅ `display: block`이지만 `width: auto` 유지 |
| JS 코드 변경 없음 | ✅ CSS + HTML meta 속성만 변경 |
| 기존 미디어쿼리 규칙 유지 | ✅ 3줄 그대로 + 새 규칙 추가 |

**기존 동작 보존: 100%**

---

## 5. Gap 목록

| # | 유형 | 항목 | 영향 |
|:-:|:----:|------|:----:|
| G-01 | Deviation | FR-02 `max-width: calc(100% + 0px)` 생략 | Positive |

### G-01 상세 (Positive Deviation)
Design에서 `pre`에 `max-width: calc(100% + 0px)` 추가를 제안했으나, 이 속성은 `calc(100%)`와 동일하며 `word-break: break-word`가 이미 부모 `.msg`에 적용되어 실질적 효과가 없다. 불필요한 CSS 제거는 NFR-01(파일 크기 최소화)에 부합.

---

## 6. Match Rate 산출

| 항목 | 비중 | 점수 |
|------|:----:|:----:|
| 파일 완성도 | 30% | 100% → 30.0 |
| FR 구현율 | 40% | 100% → 40.0 |
| NFR 준수 | 20% | 100% → 20.0 |
| 기존 동작 보존 | 10% | 100% → 10.0 |
| **합계** | **100%** | **100.0%** |

---

## 7. 결론

**Match Rate: 100%** — Report 생성 가능

- Gap 0건 (Minor/Major 없음)
- Positive Deviation 1건 (불필요한 CSS 속성 생략)

---

*분석일: 2026-03-09*
