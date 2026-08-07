# Swiss Modernism 2.0 디자인 시스템 — 설계서

> **요약**: 이 문서가 프로젝트 전체 디자인 스타일의 **단일 관리 지점**이다. 색·타이포·스페이싱·그리드·모션·컴포넌트 규격을 규범으로 정의하며, `public/tokens.css`는 이 문서의 기계적 구현물이다. 둘이 어긋나면 이 문서가 옳다.
>
> **프로젝트**: laborconsult
> **작성일**: 2026-08-07
> **상태**: Draft
> **기획서**: [swiss-modernism-design-system.plan.md](../../01-plan/features/swiss-modernism-design-system.plan.md)
> **원본 규격**: https://designmd.app/library/swiss-modernism-2-0

---

## 0. 이 문서의 위치

`design.md`가 스타일을 관리한다는 것은 다음을 뜻한다.

| 규칙 | 내용 |
|------|------|
| **선행성** | 색·간격·서체를 바꾸려면 이 문서를 먼저 고친다. 코드를 먼저 고치는 것은 드리프트다. |
| **완결성** | 구현에 필요한 모든 값이 여기 있다. "코드를 보라"는 서술을 두지 않는다. |
| **검증 기록** | 대비비 등 계산으로 얻은 값은 계산 결과를 함께 적는다. 재검증 없이 신뢰할 수 있어야 한다. |
| **경계 명시** | 규격을 따르지 않기로 한 예외는 근거와 함께 §8에 기록한다. 암묵적 예외를 두지 않는다. |

---

## 1. 개요

### 1.1 설계 목표

1. 33개 공개 HTML에 흩어진 색·서체 정의를 `public/tokens.css` 하나로 수렴시킨다.
2. Swiss Modernism 2.0 규격(무채색 베이스 + 단일 액센트, 8px 격자, 산세리프 단일, `transform`/`opacity` 전용 모션)을 적용한다.
3. 접근성을 후퇴시키지 않는다 — 모든 색 조합은 WCAG 2.1 AA를 만족하거나, 만족하지 못하는 조합은 **사용 금지 규칙으로 명문화**한다.

### 1.2 설계 원칙

- **격자는 구조이지 장식이 아니다** — 요소 위치는 8px 배수와 12칼럼으로 결정된다. 눈대중 값을 두지 않는다.
- **타이포그래피가 위계를 독립적으로 전달한다** — 색을 빼도 정보 구조가 읽혀야 한다.
- **여백은 능동적으로 작동한다** — 빈 공간은 남은 자리가 아니라 배치된 요소다.
- **액센트는 하나다** — 색으로 의미를 나누고 싶어질 때, 먼저 타이포·굵기·간격으로 해결한다.
- **모든 규칙에는 검증이 따른다** — 대비비는 계산하고, 회귀는 CI가 잡는다.

### 1.3 미결정 사항 해소 (기획서 §5.1)

| ID | 사항 | 결정 | 근거 |
|----|------|------|------|
| D-1 | 다크모드 정책 | **33개 전체 지원** | 토큰 단일 출처의 이점을 살리려면 정책도 단일이어야 한다. 흐름도 26개가 이미 지원하므로 미지원 선택은 기존 경험의 후퇴다. |
| D-2 | 액센트 색 | **코퍼 #C08050 유지** | 채도 47%로 상한 80% 통과. 브랜드 연속성을 남기는 유일한 요소. 단 대비 한계로 §3.1.3 사용 제약이 붙는다. |
| D-3 | `body max-width` | **이중 컨테이너** | 읽기 영역 800px(`--reading-max`), 구조 영역 1280px(`--container-max`). 채팅 답변은 행 길이가 가독성을 좌우하므로 1280px로 넓히지 않는다. |
| D-4 | 아이콘 시스템 | **인라인 SVG** | 빌드 스텝이 없는 정적 HTML 구조에 외부 의존을 추가하지 않는다. `currentColor` 상속으로 다크모드가 자동 해결된다. |
| D-5 | 흐름도 토큰 매핑 | **6색 데이터시각화 예외로 확정, 적용은 이연** | §8 참조. 이번 사이클 범위에서 제외한다. |

### 1.4 이번 사이클 범위 변경

기획서는 33개 파일을 범위로 잡았으나, **계산기 흐름도 25종은 이번 사이클에서 제외**한다(사용자 결정, 2026-08-07).

| 대상 | 파일 | 줄 수 | 이번 사이클 |
|------|-----:|------:|:-----------:|
| `public/*.html` | 8 | 4,642 | **포함** |
| `public/finalize.js` | 1 | 225 | **포함** (이모지 3곳) |
| `public/sw.js` | 1 | 108 | **포함** (VERSION·캐시) |
| `public/calculator_flow/*.html` | 25 | 14,589 | 이연 |

흐름도 색 정책(§8)은 확정해 기록해 두므로, 후속 사이클은 설계 없이 구현부터 착수할 수 있다.

---

## 2. 아키텍처

### 2.1 파일 구조와 로드 순서

```
public/
├── tokens.css              ← 신설. 이 문서의 구현물. 유일한 토큰 정의처
│     :root { … }                       라이트 토큰
│     @media (prefers-color-scheme: dark) { :root { … } }   다크 오버라이드
│     기본 요소 리셋 · 타이포 스케일 · 컴포넌트 클래스
│
├── index.html      ┐
├── board.html      │
├── calculators.html│  <link rel="stylesheet" href="/tokens.css">  ← <style> 보다 먼저
├── admin.html      │  각 파일의 <style>에는 페이지 고유 레이아웃만 남긴다
├── privacy.html    │  색·서체·간격 리터럴 값은 남기지 않는다
├── terms.html      │
├── install.html    │
└── offline.html    ┘
```

**로드 순서 규칙**: `tokens.css`는 페이지 인라인 `<style>`보다 **앞**에 온다. 뒤에 오면 페이지 고유 스타일을 토큰이 덮어써서 레이아웃이 깨진다.

**FOUC 방지**: `tokens.css`는 렌더 블로킹 `<link>`로 둔다(`preload`+`onload` 비동기 로드 금지). 비동기로 두면 토큰 없는 첫 프레임이 노출된다. 파일 크기를 작게 유지하는 것이 대응책이다.

### 2.2 서빙 경로

`vercel.json`의 기존 라우트 `{"src": "/(.*\\..*)", "dest": "/public/$1"}`가 `.css` 확장자를 이미 처리한다. **`vercel.json` 수정은 불필요하다.**

### 2.3 서비스워커 영향

`sw.js`의 `ASSET_PATTERN`이 현재 `/\.(?:png|svg|ico|webmanifest)$/i`라 **CSS가 자산 캐시 대상이 아니다**. 두 가지를 함께 처리한다.

```js
// 변경 1 — CSS·JS를 자산 캐시(cache-first + 백그라운드 갱신) 대상에 포함
const ASSET_PATTERN = /\.(?:css|js|png|svg|ico|webmanifest)$/i;

// 변경 2 — VERSION 갱신. 이 값이 그대로면 브라우저가 sw.js 변경을 감지하지 못한다
const VERSION = 'v3-2026-08-XX';   // 배포일로 확정
```

> **주의**: `VERSION`을 올리지 않으면 실패가 조용하다. 배포는 성공하고 사용자에게는 구 디자인이 계속 보인다. 검증 절차는 §10.3.

---

## 3. 디자인 토큰

### 3.1 색

#### 3.1.1 라이트 모드

| 토큰 | 값 | 용도 |
|------|-----|------|
| `--color-bg` | `#FFFFFF` | 페이지 배경 |
| `--color-surface` | `#F5F5F5` | 카드·패널·코드블록 배경 |
| `--color-text` | `#111111` | 본문 (순수 흑 `#000000` 금지 — 규격 제약) |
| `--color-text-muted` | `#666666` | 보조 텍스트·캡션·메타 |
| `--color-border` | `#D4D4D4` | 구조 구분선 |
| `--color-border-strong` | `#949494` | 인터랙티브 요소 테두리 (3:1 필요 지점) |
| `--accent` | `#C08050` | 유일 액센트 |
| `--accent-hover` | `#C58A5E` | 액센트 hover (명도 **+4%** — §8.5 참조) |
| `--accent-on` | `#111111` | **액센트 면 위의 글자색** |

#### 3.1.2 다크 모드

| 토큰 | 값 | 용도 |
|------|-----|------|
| `--color-bg` | `#111111` | 페이지 배경 |
| `--color-surface` | `#1C1C1C` | 카드·패널 배경 |
| `--color-text` | `#F5F5F5` | 본문 |
| `--color-text-muted` | `#A0A0A0` | 보조 텍스트 |
| `--color-border` | `#333333` | 구조 구분선 |
| `--color-border-strong` | `#555555` | 인터랙티브 테두리 |
| `--accent` | `#D9A273` | 액센트 (라이트 코퍼를 명도 상향) |
| `--accent-hover` | `#E8B98C` | 액센트 hover (명도 상향) |
| `--accent-on` | `#111111` | 액센트 면 위의 글자색 |

#### 3.1.3 대비 검증 결과 — 규범

계산 결과다(WCAG 2.1 상대휘도 공식). 이 표가 색 사용 규칙의 근거다.

**라이트 모드**

| 조합 | 대비 | 판정 | 규칙 |
|------|-----:|------|------|
| `#111111` on `#FFFFFF` | 18.88:1 | AA 통과 | 본문 기본 |
| `#111111` on `#F5F5F5` | 17.32:1 | AA 통과 | 서피스 위 본문 |
| `#666666` on `#FFFFFF` | 5.74:1 | AA 통과 | 보조 텍스트 |
| `#666666` on `#F5F5F5` | 5.27:1 | AA 통과 | 서피스 위 보조 텍스트 |
| `#111111` on `#C08050` | **5.80:1** | AA 통과 | **액센트 버튼의 글자색** |
| `#111111` on `#C58A5E` | **6.45:1** | AA 통과 | 액센트 버튼 hover — 기본보다 대비 상승 |
| ~~`#111111` on `#A66B3F`~~ | ~~4.31:1~~ | ~~미달~~ | 어둡게 하는 hover 후보. **기각** (§8.5) |
| `#C08050` on `#FFFFFF` | **3.26:1** | 큰 텍스트만 | **본문 텍스트 금지** |
| `#C08050` on `#F5F5F5` | **2.99:1** | 미달 | **텍스트 전면 금지** |
| `#FFFFFF` on `#C08050` | 3.26:1 | 큰 텍스트만 | **흰 글씨 금지** |

**다크 모드**

| 조합 | 대비 | 판정 |
|------|-----:|------|
| `#F5F5F5` on `#111111` | 17.32:1 | AA 통과 |
| `#F5F5F5` on `#1C1C1C` | 15.63:1 | AA 통과 |
| `#A0A0A0` on `#111111` | 7.22:1 | AA 통과 |
| `#D9A273` on `#111111` | 8.42:1 | AA 통과 |
| `#D9A273` on `#1C1C1C` | 7.60:1 | AA 통과 |
| `#111111` on `#D9A273` | 8.42:1 | AA 통과 |
| `#111111` on `#E8B98C` | 10.57:1 | AA 통과 (hover) |

#### 3.1.4 액센트 사용 규칙 (강제)

대비 계산에서 직접 도출된 규칙이다. 위반하면 접근성이 후퇴한다.

| # | 규칙 | 근거 |
|---|------|------|
| A-1 | **라이트 모드에서 코퍼를 텍스트 색으로 쓰지 않는다.** 본문·링크·레이블 전부 해당 | 흰 배경 3.26:1, 서피스 2.99:1로 AA 미달 |
| A-2 | **액센트 면 위의 글자는 `--accent-on`(`#111111`)이다. 흰색을 쓰지 않는다** | 흰 글씨 3.26:1 미달 / 오프블랙 5.80:1 통과 |
| A-3 | 코퍼는 **면·테두리·포커스링·비텍스트 강조**에만 쓴다 | 비텍스트 UI 요소는 3:1 기준이며 3.26:1로 통과 |
| A-4 | 링크는 색이 아니라 **밑줄**로 구분한다 | 원칙 "타이포그래피가 위계를 독립적으로 전달한다" + A-1 |
| A-5 | 다크 모드에서는 `--accent`(`#D9A273`)를 텍스트로 써도 된다 | 8.42:1 통과 |
| A-6 | 액센트는 페이지당 하나의 의미로만 쓴다. 상태 구분(성공/경고/오류)에 색을 늘리지 않는다 | 단일 액센트 규격 |
| A-7 | **액센트 면의 hover는 밝아진다. 어두워지지 않는다** | 라벨이 오프블랙이라 어두워지면 대비가 떨어진다. 어둡게 하는 후보 `#A66B3F`는 4.31:1로 AA 미달 (§8.5) |

> A-1과 A-5가 모드별로 갈리는 것은 의도된 것이다. 토큰 `--accent`가 모드마다 다른 값을 가지므로 `color: var(--accent)`를 쓰면 라이트에서 A-1을 위반한다. **텍스트에는 `--accent`를 직접 쓰지 말고, 다크 전용 규칙으로 분리한다.**

#### 3.1.5 제거되는 색

| 제거 대상 | 현재 위치 |
|-----------|-----------|
| `--navy` `--navy-light` `--navy-deep` | index, board, privacy, terms, install, offline |
| `--copper-light` `--copper-glow` | index, board |
| `--cream` `--warm-white` | index, board, privacy, terms, install, offline |
| `--text-secondary` `--text-muted` | index, board (→ `--color-text-muted`로 통합) |
| `--border-light` | index, board |
| `--primary` `--bg` `--card` `--muted` `--accent-hover` (블루 계열) | calculators, admin |
| `--co-*` 콜아웃 12종 | index (→ §5.5 무채색 재정의) |
| 그라디언트 3곳 | index 1, board 2 |

`<meta name="theme-color" content="#1B2A4A">`도 함께 교체한다(라이트 `#FFFFFF`, 다크 `#111111` — `media` 속성으로 분기).

### 3.2 타이포그래피

#### 3.2.1 서체

```css
--font-body: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
--font-mono: ui-monospace, SFMono-Regular, 'SF Mono', Menlo, monospace;
```

Swiss 규격은 Inter/Helvetica를 지정하나 **한글 글립이 없다**. Pretendard는 한글을 포함한 동일 계열 지오메트릭 산세리프이므로 규격의 의도를 만족하는 대체다. 이는 §8의 기록된 예외가 아니라 **규격 준수를 위한 현지화**다.

**제거**: `--font-display`(Noto Serif KR), `--font-title`(Do Hyeon), 그리고 이를 불러오는 Google Fonts `<link>`.

> 로고(`Do Hyeon`)가 사라지므로 헤더 인상이 확정적으로 바뀐다. 사용자 승인 완료(전면 도입 선택, 2026-08-07).

#### 3.2.2 스케일

| 토큰 | 크기 | 굵기 | 행간 | 용도 |
|------|------|:----:|:----:|------|
| `--text-display` | `clamp(2.5rem, 5vw, 4rem)` | 700 | 1.1 | 랜딩 히어로 |
| `--text-h1` | `2.25rem` | 700 | 1.2 | 페이지 제목 |
| `--text-h2` | `1.5rem` | 700 | 1.3 | 섹션 제목 |
| `--text-h3` | `1.125rem` | 700 | 1.4 | 하위 제목 |
| `--text-body` | `1rem` | 400 | **1.6** | 본문 |
| `--text-sm` | `0.875rem` | 400 | 1.5 | 보조 |
| `--text-label` | `0.75rem` | 500 | 1.4 | 레이블·캡션 |

**자간**: 한글은 `letter-spacing: -0.01em`을 본문에 적용한다(Pretendard 기본 자간이 한글 조합에서 다소 성기다). 제목(`h1`·`display`)은 `-0.02em`.

#### 3.2.3 h3 추가에 대한 기록

원본 규격은 H1/H2/Body/Label/Display 5단계만 정의한다. 본 프로젝트는 답변 렌더링에 h3가 실제로 쓰이므로(`app/templates/prompts.py`가 h2/h3 구조를 생성) 1단계를 추가했다. 추가 없이 h3를 h2와 같게 두면 답변 내 위계가 붕괴한다.

### 3.3 스페이싱

기본 단위 8px. 토큰명의 숫자가 8px의 배수를 뜻한다.

| 토큰 | 값 | px |
|------|-----|---:|
| `--space-half` | `0.25rem` | 4 |
| `--space-1` | `0.5rem` | 8 |
| `--space-2` | `1rem` | 16 |
| `--space-3` | `1.5rem` | 24 |
| `--space-4` | `2rem` | 32 |
| `--space-6` | `3rem` | 48 |
| `--space-8` | `4rem` | 64 |
| `--space-12` | `6rem` | 96 |
| `--space-section` | `clamp(4rem, 8vw, 8rem)` | 64–128 |

**규칙**: 여백·패딩·간격은 위 토큰만 쓴다. `--space-half`(4px)는 아이콘 정렬 등 8px 격자가 과한 지점에만 허용한다.

### 3.4 그리드와 컨테이너

| 토큰 | 값 | 용도 |
|------|-----|------|
| `--grid-columns` | `12` | 칼럼 수 |
| `--grid-gap` | `1rem` | 칼럼 간격 |
| `--container-max` | `1280px` | 구조 영역 최대 폭 |
| `--reading-max` | `800px` | 읽기 영역 최대 폭 |
| `--bp-mobile` | `768px` | 단일 칼럼 붕괴 기준 |

**이중 컨테이너 (D-3)**

| 영역 | 폭 | 대상 |
|------|-----|------|
| 읽기 | `--reading-max` (800px) | 채팅 답변, 게시글 본문, 약관·개인정보처리방침 |
| 구조 | `--container-max` (1280px) | 랜딩 히어로, 계산기 메뉴 그리드, 관리자 대시보드 |

현행 `index.html`의 `body { max-width: 800px }`는 **읽기 영역에만** 남기고, 랜딩·FAQ 그리드는 1280px 컨테이너로 승격한다.

**붕괴 규칙**: `768px` 미만에서 모든 그리드는 단일 칼럼(`grid-template-columns: 1fr`)이 된다.

**비대칭 원칙**: 3칼럼 균등 분할을 쓰지 않는다(규격 제약). 12칼럼 위에서 `8/4`, `7/5`, `9/3` 같은 비대칭 배분을 쓴다.

### 3.5 모서리·그림자

| 토큰 | 값 | 용도 |
|------|-----|------|
| `--radius-sm` | `4px` | 뱃지·태그 |
| `--radius` | `8px` | **기본** — 버튼·카드·입력·모달 |
| `--radius-pill` | `999px` | 칩·필터 토글 **한정** |
| `--shadow-card` | `0 2px 12px rgba(0,0,0,0.06)` | 카드 |
| `--shadow-lift` | `0 4px 16px rgba(0,0,0,0.10)` | hover 상승 |

**제거**: `--radius-md`(14px), `--radius-lg`(20px), `--shadow-sm/md/lg` 3단계 체계.

다크 모드 그림자는 검정 위에서 보이지 않으므로 **테두리로 대체**한다 — 다크에서 `--shadow-card: none`, `--color-border`로 구분한다.

### 3.6 모션

| 토큰 | 값 | 용도 |
|------|-----|------|
| `--dur-fast` | `200ms` | hover·포커스 |
| `--dur-base` | `300ms` | 상태 전환·펼침 |
| `--dur-enter` | `420ms` | 진입 애니메이션 |
| `--ease-out` | `cubic-bezier(0, 0, 0.2, 1)` | 전 구간 공통 |
| `--stagger` | `80ms` | 리스트 순차 지연 |

**규칙**

| # | 규칙 |
|---|------|
| M-1 | `transform`과 `opacity`만 애니메이션한다. `width`·`height`·`top`·`background-color` 전이 금지 |
| M-2 | 진입은 `opacity 0→1` + `translateY(16px→0)`, `--dur-enter` |
| M-3 | 리스트 진입은 항목마다 `--stagger`씩 지연. 최대 10개까지만 (그 이상은 지연 누적이 체감된다) |
| M-4 | `prefers-reduced-motion: reduce`에서 모든 애니메이션을 `0.01ms`로 무력화한다 |

M-4는 원본 규격에 없으나 접근성상 필수다. 규격의 "고대비 검증 요구" 정신과 일치한다.

---

## 4. `tokens.css` 구조

```css
/* ── 1. 토큰 ── */
:root {
  /* 색 — 라이트 */
  --color-bg: #FFFFFF;
  --color-surface: #F5F5F5;
  --color-text: #111111;
  --color-text-muted: #666666;
  --color-border: #D4D4D4;
  --color-border-strong: #949494;
  --accent: #C08050;
  --accent-hover: #C58A5E;   /* 밝아진다 — A-7 */
  --accent-on: #111111;

  /* 타이포 */
  --font-body: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, 'SF Mono', Menlo, monospace;
  --text-display: clamp(2.5rem, 5vw, 4rem);
  --text-h1: 2.25rem;  --text-h2: 1.5rem;   --text-h3: 1.125rem;
  --text-body: 1rem;   --text-sm: 0.875rem; --text-label: 0.75rem;

  /* 스페이싱 */
  --space-half: 0.25rem; --space-1: 0.5rem; --space-2: 1rem;  --space-3: 1.5rem;
  --space-4: 2rem;       --space-6: 3rem;   --space-8: 4rem;  --space-12: 6rem;
  --space-section: clamp(4rem, 8vw, 8rem);

  /* 그리드 */
  --grid-columns: 12; --grid-gap: 1rem;
  --container-max: 1280px; --reading-max: 800px;

  /* 형태 */
  --radius-sm: 4px; --radius: 8px; --radius-pill: 999px;
  --shadow-card: 0 2px 12px rgba(0,0,0,0.06);
  --shadow-lift: 0 4px 16px rgba(0,0,0,0.10);

  /* 모션 */
  --dur-fast: 200ms; --dur-base: 300ms; --dur-enter: 420ms;
  --ease-out: cubic-bezier(0, 0, 0.2, 1); --stagger: 80ms;
}

/* ── 2. 다크 오버라이드 (색만) ── */
@media (prefers-color-scheme: dark) {
  :root {
    --color-bg: #111111;
    --color-surface: #1C1C1C;
    --color-text: #F5F5F5;
    --color-text-muted: #A0A0A0;
    --color-border: #333333;
    --color-border-strong: #555555;
    --accent: #D9A273;
    --accent-hover: #E8B98C;
    --accent-on: #111111;
    --shadow-card: none;
    --shadow-lift: none;
  }
}

/* ── 3. 리셋 · 기본 요소 ── */
/* ── 4. 타이포 클래스 ── */
/* ── 5. 레이아웃 유틸 (.container, .container-reading, .grid-12) ── */
/* ── 6. 컴포넌트 (.btn, .card, .field, .chip, .callout, .icon) ── */
/* ── 7. 모션 유틸 (.enter, .stagger) + prefers-reduced-motion ── */
```

**다크 오버라이드는 색과 그림자만 바꾼다.** 스페이싱·타이포·그리드는 모드와 무관하다.

---

## 5. 컴포넌트 규격

### 5.1 버튼

| 변형 | 배경 | 글자 | 테두리 |
|------|------|------|--------|
| Primary | `--accent` | `--accent-on` | 없음 |
| Secondary | 투명 | `--color-text` | `1px solid --color-border-strong` |
| Ghost | 투명 | `--color-text-muted` | 없음 |

```
padding      : 12px 24px   (--space-1 + half / --space-3)
border-radius: --radius (8px)
font         : --text-body / 500
transition   : transform --dur-fast --ease-out, box-shadow --dur-fast --ease-out
hover        : 배경 --accent-hover (밝아짐, A-7), translateY(-1px), --shadow-lift
active       : translateY(0)          ← 눌림 복귀
focus-visible: outline 2px solid --accent; outline-offset 2px
disabled     : opacity .45; cursor not-allowed; hover 효과 없음
```

> `transition`에 `background-color`가 없는 것은 M-1 때문이다. 배경색은 전이 없이 즉시 바뀐다.

> **`board.html` 주의**: CAPTCHA 게이팅 버튼은 "토큰이 있고 rate limit이 풀렸을 때만 열린다"는 단일 불변식으로 3개 지점이 통일돼 있다. 이번 작업은 **CSS만 손대고 JS 로직은 건드리지 않는다.** 비활성 시각 처리는 `[disabled]` 셀렉터로 한다.

### 5.2 카드

```
background   : --color-surface
border       : 1px solid --color-border
border-radius: --radius (8px)
padding      : --space-3 (24px)
box-shadow   : --shadow-card      (다크에서는 none, 테두리가 대신함)
```

### 5.3 입력 필드

```
레이블       : 입력 위에 배치. --text-label / 500 / --color-text-muted
              margin-bottom --space-half
input        : padding 12px; border 1px solid --color-border-strong;
               border-radius --radius; background --color-bg; color --color-text
focus        : outline 2px solid --accent; outline-offset 2px
오류         : border-color --color-text; 메시지는 --text-sm
```

오류를 빨강이 아니라 굵은 테두리 + 텍스트로 표시하는 것은 A-6(단일 액센트) 때문이다. 색맹 사용자에게도 동일하게 전달된다.

### 5.4 아이콘 (D-4)

```
형식 : 인라인 SVG
크기 : 20px 기본 / 16px 소형 / 24px 대형
선   : stroke-width 1.5, stroke=currentColor, fill=none
정렬 : vertical-align: -0.125em
```

`currentColor`를 쓰므로 다크모드 대응이 자동이다.

#### 이모지 → 아이콘 대체표

규격 제약 "UI에 이모지를 쓰지 않는다(아이콘 시스템만)"에 따른 전체 대체 목록이다.

| 파일 | 위치 | 현재 | 대체 아이콘 | 의미 |
|------|------|:----:|-------------|------|
| `index.html` | 1165 | 📘 | `book` | 법령 콜아웃 |
| `index.html` | 1166 | ⚠ | `alert-triangle` | 주의 콜아웃 |
| `index.html` | 1167 | 🚨 | `alert-octagon` | 위험 콜아웃 |
| `index.html` | 1168 | 💡 | `lightbulb` | 팁 콜아웃 |
| `index.html` | 1263 | ⚖ | `scale` | 판례 표기 |
| `index.html` | 1263 | 📋 | `clipboard` | 행정해석 표기 |
| `index.html` | 1287 | ⚠ | `alert-triangle` | 경고 |
| `index.html` | 1974 | ⚠ 📢 | `alert-triangle` / `megaphone` | 공지 배너 |
| `calculators.html` | 292 | 📊 | `bar-chart` | 임금 계산 |
| `calculators.html` | 300 | 💰 | `banknote` | 수당 |
| `calculators.html` | 340 | 🏢 | `building` | 사업장 |
| `calculators.html` | 356 | 🛡 | `shield` | 보험 |
| `calculators.html` | 384 | 👶 | `baby` | 모성보호 |
| `calculators.html` | 400 | ⚙ | `settings` | 근로시간 |
| `calculators.html` | 427 | 📐 | `ruler` | 기타 |
| `finalize.js` | 53, 63 | ⚠ | `alert-triangle` | 접기 종료 마커 표시 |
| `finalize.js` | 164 | ⚖ | `scale` | 핵심 복귀 버튼 |

> **`finalize.js` 주의**: 53·63행 ⚠는 접기 종료 마커(`isTerminator`) 판정과 인접한다. 아이콘 교체 시 **마커 판정 로직이 문자에 의존하는지 먼저 확인**한다. 의존한다면 판정은 문자 그대로 두고 표시만 SVG로 바꾼다. 면책 고지가 접힌 채 숨는 회귀가 여기서 난다.

### 5.5 콜아웃 (답변 렌더링)

현행 `--co-*` 12토큰은 4색(파랑·주황·빨강·초록)으로 종류를 구분한다. A-6에 따라 **색이 아니라 아이콘 + 좌측 굵은 선**으로 구분한다.

```
공통 : background --color-surface
       border-left 3px solid --color-border-strong
       border-radius 0 --radius --radius 0
       padding --space-2
       아이콘 20px + 제목 --text-label/500
```

| 종류 | 아이콘 | 좌측선 |
|------|--------|--------|
| 법령 | `book` | `--color-border-strong` |
| 주의 | `alert-triangle` | `--color-text` |
| 위험 | `alert-octagon` | `--color-text` (3px → **4px**) |
| 팁 | `lightbulb` | `--color-border` |
| 요약 | `list` | `--accent` ← 유일하게 액센트를 쓰는 지점 |

> **`finalize.js` 제약**: 답변 조망 레이어는 **h2 태그만 근거로 동작**해야 한다. `board.html`은 `md()`가 아니라 `marked.parse()`만 쓰므로 콜아웃 클래스·`.summary-badge`가 없다. 위 콜아웃 스타일에 의존하는 로직을 `finalize.js`에 추가하지 않는다.

### 5.6 레이아웃 유틸

```css
.container         { max-width: var(--container-max); margin-inline: auto;
                     padding-inline: var(--space-2); }
.container-reading { max-width: var(--reading-max);   margin-inline: auto;
                     padding-inline: var(--space-2); }
.grid-12           { display: grid;
                     grid-template-columns: repeat(var(--grid-columns), 1fr);
                     gap: var(--grid-gap); }
@media (max-width: 768px) {
  .grid-12 { grid-template-columns: 1fr; }
}
```

---

## 6. 페이지별 이행 계획

### 6.1 토큰 대응표

기존 토큰 → 신규 토큰. 기계적 치환이 가능하도록 1:1로 정리했다.

**네이비/코퍼 계열** (index, board, privacy, terms, install, offline)

| 기존 | 신규 | 비고 |
|------|------|------|
| `--navy` `#1B2A4A` | `--color-text` | 제목·강조 텍스트로 쓰이던 자리 |
| `--navy-light` `#2D4A7A` | `--color-text-muted` | |
| `--navy-deep` `#0F1B30` | `--color-text` | |
| `--copper` `#C08050` | `--accent` | 값 동일. **단 텍스트 용례는 A-1 위반 → `--color-text`로** |
| `--copper-light` `#E6C4A8` | 제거 | 액센트 단일화 |
| `--copper-glow` | 제거 | |
| `--cream` `#F7F5F2` | `--color-bg` | 배경이 크림 → 흰색 |
| `--warm-white` `#FFFFFF` | `--color-surface` | 카드 배경이 흰색 → `#F5F5F5`로 반전 |
| `--text` `#1E293B` | `--color-text` | |
| `--text-secondary` `#526070` | `--color-text-muted` | |
| `--text-muted` `#8B95A5` | `--color-text-muted` | 2개 → 1개 통합 |
| `--border` `#E4E1DB` | `--color-border` | |
| `--border-light` `#F0EDE8` | `--color-border` | 통합 |
| `--shadow-sm/md/lg` | `--shadow-card` / `--shadow-lift` | 3단계 → 2단계 |
| `--radius-sm` `8px` | `--radius` | |
| `--radius-md` `14px` | `--radius` | 8px로 통일 |
| `--radius-lg` `20px` | `--radius` | 8px로 통일 |
| `--radius-pill` `50px` | `--radius-pill` `999px` | 칩 한정 |
| `--font-display` | 제거 | Pretendard 단일화 |
| `--font-title` | 제거 | |
| `--font-body` | `--font-body` | 값 유지 |

> **배경 반전 주의**: 현행은 `크림 배경 + 흰 카드`, 신규는 `흰 배경 + 회색 카드`다. 명도 관계가 뒤집히므로 카드가 배경보다 어두워진다. 육안 검수에서 카드 경계가 살아 있는지 확인해야 한다.

**블루/슬레이트 계열** (calculators, admin)

| 기존 | 신규 |
|------|------|
| `--primary` `#2563eb` | `--accent` |
| `--bg` `#f8fafc` | `--color-bg` |
| `--card` `#ffffff` | `--color-surface` |
| `--text` `#1e293b` | `--color-text` |
| `--muted` `#64748b` | `--color-text-muted` |
| `--border` `#e2e8f0` | `--color-border` |
| `--accent-hover` `#eff6ff` | `--color-surface` |
| `--danger` `#ef4444` (admin) | `--color-text` + 아이콘 | A-6 |
| `--success` `#16a34a` (admin) | `--color-text-muted` + 아이콘 | A-6 |
| `--sidebar-w` `280px` | 유지 | 레이아웃 값, 토큰 대상 아님 |

`calculators.html`의 기존 다크 블록은 `tokens.css` 다크 오버라이드로 대체하고 페이지에서 제거한다.

### 6.2 페이지별 작업

| 페이지 | 줄 수 | 주요 작업 |
|--------|------:|-----------|
| `index.html` | 2,017 | 토큰 교체, 서체 3종→1종, 그라디언트 1곳, 이모지 8곳, 콜아웃 12토큰 재정의, 랜딩 1280px 그리드 승격, 다크 신규, `theme-color` 분기 |
| `board.html` | 1,084 | 토큰 교체, 그라디언트 2곳, 다크 신규, **CAPTCHA 버튼 로직 무수정** |
| `calculators.html` | 527 | 블루→무채색, 이모지 7곳, 자체 다크 제거→토큰 상속, 메뉴 1280px 그리드 |
| `admin.html` | 472 | 블루→무채색, `--danger`/`--success` 제거, 다크 신규 |
| `privacy.html` | 202 | 토큰 교체, 서체, 다크 신규. **본문 문구 무수정** |
| `terms.html` | 176 | 동일. **제5조 수치 무수정** |
| `install.html` | 124 | 토큰 교체, 서체, 다크 신규 |
| `offline.html` | 40 | 토큰 교체, 다크 신규 |
| `finalize.js` | 225 | 이모지 3곳 → SVG. **접기 로직 무수정** |
| `sw.js` | 108 | `ASSET_PATTERN`에 css·js 추가, `VERSION` 갱신 |

### 6.3 구현 순서 (Wave)

| Wave | 내용 | 산출물 | 단독 배포 |
|:----:|------|--------|:---------:|
| 0 | `tokens.css` 작성 + `offline.html`(40줄)로 파일럿 검증 | 신규 1 + 검증 1 | ✓ |
| 1 | 소형 정적 페이지 — `install` `privacy` `terms` | 3파일 502줄 | ✓ |
| 2 | `admin` `calculators` — 블루 계열 통합 | 2파일 999줄 | ✓ |
| 3 | `board` — CAPTCHA 불변식 주의 | 1파일 1,084줄 | ✓ |
| 4 | `index` — 최대 난도. 콜아웃·랜딩 그리드·다크 신규 | 1파일 2,017줄 | ✓ |
| 5 | 아이콘 시스템 (`finalize.js` 포함) + `sw.js` + 전체 검수 | 전역 | — |

**순서 근거**: 작은 페이지부터 올라간다. Wave 0의 `offline.html`은 40줄이라 `tokens.css`의 오류를 싸게 발견할 수 있다. `index.html`을 마지막에 두는 것은 콜아웃·조망 레이어·랜딩 그리드가 겹쳐 회귀 위험이 가장 크기 때문이다.

---

## 7. 지켜야 할 기존 제약

`CLAUDE.md` Key Conventions 중 이번 작업이 깨뜨리기 쉬운 항목이다.

| # | 제약 | 이번 작업에서의 의미 |
|---|------|---------------------|
| C-1 | 공개 HTML 주석에 내부 경로·함수명 금지 | `tokens.css` 주석에도 적용된다. 소스가 그대로 공개된다 |
| C-2 | 프론트 `fetch`는 `resp.ok` 검사 필수 | 스타일 작업 중 `fetch` 코드를 건드리지 않는다 |
| C-3 | CAPTCHA 버튼 단일 불변식 | `board.html` JS 무수정. CSS만 |
| C-4 | `finalize.js`는 h2만 근거, 접기 종료 마커 보존 | 콜아웃 클래스 의존 금지. 마커 문자 판정 확인 후 아이콘 교체 |
| C-5 | `privacy.html` 5·7항, `terms.html` 5조 문구는 코드와 동기 | **문구 무수정.** 스타일만 |
| C-6 | `calculator_flow`의 `sendPrompt()`는 `window.parent?.` 형태 | 이번 사이클 범위 밖이나 `calculators.html` iframe 연동 확인 시 유의 |

---

## 8. 기록된 예외

규격을 따르지 않기로 한 지점이다. 암묵적으로 두지 않고 근거와 함께 남긴다.

### 8.1 계산기 흐름도 6색 — 데이터시각화 예외 (적용 이연)

**결정**: 21개 흐름도의 `c-blue / c-teal / c-amber / c-coral / c-purple / c-gray` 6색 체계를 유지한다. 단일 액센트 규칙을 적용하지 않는다.

**근거**: 흐름도는 UI 크롬이 아니라 다이어그램이다. 노드 종류(계산 단계·결과·주의·경고·분기·보조)를 구분하는 것이 기능이며, 단일 액센트로 축소하면 판단 분기와 계산 단계를 시각적으로 구별할 수 없다. 규격의 "단일 액센트"는 인터페이스 크롬을 겨냥한 것이지 정보 그래픽을 겨냥한 것이 아니다.

**적용 시 토큰화 방향** (후속 사이클)

| 현행 클래스 | 신규 토큰 | 의미 | 라이트 fill/stroke | 다크 fill/stroke |
|-------------|-----------|------|--------------------|------------------|
| `c-blue` | `--chart-1` | 계산 단계 | `#E6F1FB` / `#185FA5` | `#042C53` / `#85B7EB` |
| `c-teal` | `--chart-2` | 결과 | `#E1F5EE` / `#0F6E56` | `#04342C` / `#5DCAA5` |
| `c-amber` | `--chart-3` | 주의 | `#FAEEDA` / `#854F0B` | `#412402` / `#FAC775` |
| `c-coral` | `--chart-4` | 경고 | `#FAECE7` / `#993C1D` | `#4A1B0C` / `#F0997B` |
| `c-purple` | `--chart-5` | 분기 | `#EEEDFE` / `#534AB7` | `#26215C` / `#AFA9EC` |
| `c-gray` | `--chart-6` | 보조 | `#F1EFE8` / `#5F5E5A` | `#2C2C2A` / `#B4B2A9` |

각 클래스는 `rect{fill,stroke}` + `.th{fill}`(제목) + `.ts{fill}`(부제) 3규칙 × 라이트/다크 2모드로 정의된다. 후속 적용 시 **채도 80% 상한과 대비 AA를 재검증**한 뒤 값을 조정한다. 위 표는 현행 값이며 검증 전이다.

**미적용 상태의 부작용**: `calculators.html`은 이번에 무채색으로 바뀌지만 iframe 안 흐름도는 기존 색을 유지한다. 메뉴와 내용 사이에 시각적 이음매가 생긴다. 후속 사이클까지 감수한다.

### 8.2 Pretendard 대체

원본 규격은 Inter/Helvetica를 지정하나 한글 글립이 없다. Pretendard는 동일 계열의 한글 지원 산세리프이므로 규격 의도를 만족하는 현지화다. 예외라기보다 필수 대체다.

### 8.3 h3 단계 추가

§3.2.3 참조. 답변 렌더링이 h3를 실제로 생성하므로 규격의 5단계에 1단계를 더했다.

### 8.4 `prefers-reduced-motion` 추가

원본 규격에 없으나 접근성상 필수다(§3.6 M-4).

### 8.5 hover 방향 반전 — "8% 어둡게" 미적용

**규격**: "Hover: 8% darken + subtle lift shadow"
**결정**: 어둡게 하지 않고 **밝게** 한다(명도 +4%, `#C08050` → `#C58A5E`).

**근거**: 구조적 충돌이다. A-2에 따라 액센트 면의 라벨은 오프블랙(`#111111`)이며, 기본 상태 대비는 5.80:1로 AA 여유가 크지 않다. 배경을 어둡게 하면 오프블랙 라벨과의 대비가 **떨어진다** — 규격대로 8% 어둡게 한 `#A66B3F`는 4.31:1로 AA 미달이다.

대안을 모두 검토한 결과다.

| 대안 | 결과 | 판정 |
|------|------|------|
| 어둡게 + 오프블랙 라벨 유지 | 4.31:1 | 기각 — AA 미달 |
| 어둡게 + hover 시 라벨을 흰색으로 전환 | `#FFFFFF` on `#A66B3F` = 4.38:1 | 기각 — 여전히 미달이고, 상태별 글자색 전환은 깜빡임을 만든다 |
| 충분히 어둡게 해 흰 라벨을 성립시킴 | 명도를 크게 낮춰야 함 | 기각 — "8%"를 훨씬 넘어서 규격에서 더 멀어진다 |
| **밝게 (+4%)** | **6.45:1, 기본보다 상승** | **채택** |

"subtle lift shadow"는 그대로 적용하므로 상승 은유는 유지된다. 오히려 밝아지는 것이 상승과 더 부합한다. 다크 모드도 같은 방향(`#D9A273` → `#E8B98C`, 8.42 → 10.57:1)이라 두 모드의 동작이 일치한다.

---

## 9. 테스트 전략

### 9.1 기존 회귀 자산

CI(`.github/workflows/tests.yml`)에 이미 있는 프론트 3종이 방어선이다.

| 테스트 | 방어 대상 |
|--------|-----------|
| `test_public_fetch.js` | 공개 페이지 전 `fetch`의 `resp.ok` 검사 (C-2) |
| `test_answer_renderer.js` | 답변 마크다운 렌더링 |
| `test_answer_glance.js` | 조망 레이어 — 목차·접기·복귀 버튼·**면책 고지 노출** (C-4) |

Wave마다 이 3종을 돌린다. 특히 Wave 4(`index`)·Wave 5(`finalize.js`)에서 필수다.

### 9.2 육안 검수 항목

| 항목 | 대상 | 확인 |
|------|------|------|
| 레이아웃 붕괴 | 8페이지 × 라이트/다크 | 텍스트 잘림·겹침 없음 |
| 카드 경계 | 배경 반전 지점 (§6.1) | 흰 배경 위 회색 카드가 구분됨 |
| 모바일 붕괴 | <768px | 단일 칼럼 정상 |
| 액센트 규칙 | 전 페이지 | A-1 위반(라이트 코퍼 텍스트) 0건 |
| 다크 신규 7페이지 | index·board·admin·privacy·terms·install·offline | 대비 확보, 그림자 대신 테두리 |
| 조망 레이어 | index(채팅), board(상세) | 목차·접기·복귀 버튼 동작 |
| CAPTCHA 게이팅 | board 글쓰기 | 토큰 전 비활성, 획득 후 활성 |

### 9.3 배포 검증 (필수)

`sw.js` 실패는 조용하다. 배포 후 반드시 확인한다.

1. 배포 완료 후 **하드 리로드 없이** 일반 새로고침
2. 신규 디자인이 보이면 통과. 구 디자인이 남으면 `VERSION` 미갱신
3. DevTools → Application → Cache Storage에 `shell-v3-*` 신규 캐시 확인
4. 오프라인 전환 후 `/`·`/board`·`/calculators` 열림 확인

---

## 10. 위험

기획서 §5의 위험 중 설계로 해소된 것과 남은 것을 구분한다.

| ID | 위험 | 상태 | 설계상 대응 |
|----|------|------|-------------|
| R-01 | 다크모드 비대칭 | **해소** | D-1 전체 지원. `tokens.css` 단일 오버라이드 |
| R-02 | 하드코딩 hex 2,888회 | **범위 밖으로 이동** | 흐름도 이연(§1.4). 공개 8페이지 69색은 §6.1 대응표로 처리 |
| R-03 | `sw.js` VERSION 미갱신 | 잔존 | §2.3 명시 + §9.3 배포 검증 절차 |
| R-04 | 브랜드 인상 전환 | 수용 | 사용자 승인 완료 |
| R-05 | `finalize.js` 회귀 | 잔존 | C-4 + `test_answer_glance.js` + Wave 5 분리 |
| R-06 | CAPTCHA 불변식 훼손 | 잔존 | C-3 JS 무수정 원칙 + Wave 3 분리 |
| R-07 | 작업량 과소평가 | **해소** | 흐름도 이연으로 4,642줄로 축소 |
| R-08 | 액센트 접근성 후퇴 | **해소** | §3.1.3 대비 실측 + §3.1.4 A-1~A-6 강제 규칙 |
| R-09 | **배경 명도 반전** | 신규 | 크림+흰카드 → 흰배경+회색카드. §9.2 카드 경계 검수 |
| R-10 | **`calculators` iframe 이음매** | 신규 | 흐름도 이연에 따른 부작용. §8.1에 기록, 후속 해소 |

---

## 11. 다음 단계

1. [ ] 이 문서 검토·승인
2. [ ] Wave 0 — `tokens.css` 작성 + `offline.html` 파일럿
3. [ ] Wave 1~5 순차 구현, 각 Wave 종료 시 CI 3종 통과 확인
4. [ ] `CLAUDE.md` 디자인 서술 갱신 (네이비+코퍼 → 무채색+코퍼 액센트)
5. [ ] `/pdca analyze swiss-modernism-design-system`

---

## 변경 이력

| 버전 | 날짜 | 변경 | 작성자 |
|------|------|------|--------|
| 0.1 | 2026-08-07 | 최초 작성. D-1~D-5 해소, 대비 실측 반영, 흐름도 이연 | Claude |
