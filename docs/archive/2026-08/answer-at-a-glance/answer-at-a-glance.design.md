# 답변내용 일목요연 정리 Design (answer-at-a-glance)

> **Summary**: Plan v0.2(FR-1~FR-6)을 코드 수준으로 설계한다. 핵심 발견 — 프롬프트 2종(`SYSTEM_PROMPT_TEMPLATE`/`CONSULTATION_SYSTEM_PROMPT`)의 `##` 헤딩 밀도가 크게 달라 FR-1(목차)·FR-2(접기)의 실제 발동률이 답변 유형별로 갈린다. FR-5(프롬프트 정합)는 "있으면 좋은" 항목이 아니라 FR-1/2가 의미를 가지려면 반드시 먼저 풀어야 하는 **전제조건**으로 재확인했다. `finalize()`는 `public/finalize.js`로 분리해 `index.html`·`board.html`이 공유한다(기존 `pwa.js` 선례).
>
> **Project**: laborconsult
> **Author**: DrunkenZealnut
> **Date**: 2026-08-06
> **Status**: Draft
> **Planning Doc**: [answer-at-a-glance.plan.md](../../01-plan/features/answer-at-a-glance.plan.md) (v0.2)

---

## 1. 설계 개요

### 1.1 설계 목표

Plan §2.1의 FR-1~FR-6을 구현 가능한 수준으로 구체화한다. 원칙은 Plan §6 리스크가 이미 지적한 것과 동일 — **접힘이 정보 은닉으로 오인되지 않게, 스트리밍 중 깨지지 않게, 기존 렌더러(콜아웃·스텝·표)를 건드리지 않게** 얹는 순수 후처리 레이어다.

### 1.2 핵심 발견 — 헤딩 밀도는 답변 유형마다 다르다

`app/core/pipeline.py`가 실제로 쓰는 시스템 프롬프트는 2종이다(`app/templates/prompts.py`의 `COMPOSER_SYSTEM`은 레거시 — `compose_follow_up`만 참조하고 파이프라인은 호출하지 않는다, CLAUDE.md 기재 사실):

| 프롬프트 | 사용 조건 | `##` 헤딩 지시 | 법적 근거·판례 형식 |
|----------|-----------|----------------|----------------------|
| `SYSTEM_PROMPT_TEMPLATE`(`pipeline.py:1301`) | 기본 경로(계산기·괴롭힘·일반) | **자유** — "`##` 소제목으로 섹션을 나누세요 (예: ## 계산 결과, ## 법적 근거, ## 주의사항)" | `##` 헤딩 가능 |
| `CONSULTATION_SYSTEM_PROMPT`(`prompts.py:360`) | `consultation_context` 존재(법률상담·판례검색) | **제한** — `## ⚖️ 핵심 답변` + `## 절차`/`## 신청 방법` **뿐** | `> 📘 **법적 근거**: ...` / `> 📘 **관련 판례**: ...` 블록쿼트 고정 |

즉 **계산기 답변은 헤딩이 자연히 여러 개** 생기지만, **법률상담 답변은 프롬프트가 법적 근거·판례를 블록쿼트로 강제**해 보통 1~2개(핵심 답변 + 선택적 절차)뿐이다. Plan FR-1의 "헤딩 3개+" 임계값은 후자 답변군에서 거의 발동하지 않는다.

**설계 결론**: FR-5를 FR-1/FR-2와 **동시 착수**한다(Plan은 FR-5를 Medium으로 뒀으나 순서상 선행 없이는 FR-1/2가 계산기 답변에만 편중 적용된다). `CONSULTATION_SYSTEM_PROMPT`의 법적 근거·관련 판례를 `##` 헤딩으로 승격할지는 §3.5에서 결정한다.

**인용 검증 영향 없음 확인**: `citation_validator.py`의 `_PREC_PATTERN`/`_ADMIN_PATTERN`(`:54,63`)은 `response_text` 전체를 정규식으로 훑는다(`validate_response_citations:202,220`) — 블록쿼트냐 헤딩이냐와 무관하다. 헤딩 승격이 인용 검증을 깨뜨리지 않는다.

### 1.3 설계 원칙

| # | 원칙 | 근거 |
|---|------|------|
| P1 | finalize는 **완성된 DOM만** 본다(스트리밍 중 미적용) | Plan FR-4, 리스크 §6 1행 |
| P2 | 접힘 대상은 **부차 상세뿐** — 핵심 답변·요약·주의사항은 항상 펼침 | Plan 리스크 §6 2행 |
| P3 | `.dataset.md`(원문 마크다운)는 **불변** — finalize는 렌더된 DOM만 변형 | 복사·마크다운 내보내기가 이 값을 그대로 읽는다(§4.4) |
| P4 | 신규 로직은 **h2 태그만 근거**로 동작 — `md()`의 콜아웃 클래스에 의존하지 않음 | `board.html`이 `md()`를 안 쓰므로 공유 가능해야 한다(FR-6) |
| P5 | 공유 코드는 **정적 파일 분리** | `public/pwa.js` 선례("index/board/calculators 공유") 그대로 따름 |

---

## 2. 확정된 설계 결정

| # | 결정 | 확정 값 | 근거 |
|---|------|---------|------|
| D1 | finalize 공유 방식 | 신규 `public/finalize.js`, 양쪽 페이지 `<script src="/finalize.js">` | P5. `vercel.json:52`의 `/(.*\..*)` 캐치올 라우트가 별도 설정 없이 서빙 |
| D2 | 목차·접기 대상 | 말풍선 내부의 `h2` 전부를 **목차에 포함**(핵심 답변이 첫 칩이 되어 결론 복귀 경로가 된다). **접기에서만** `.summary-badge` 내부 `h2`를 제외 | P4. 초안은 목차에서도 제외했으나, 핵심 답변을 첫 칩으로 두는 편이 FR-3에 직접 기여하고 `board.html`(`.summary-badge` 없음)과도 동작이 일치한다 |
| D3 | 목차 발동 임계값 | Plan의 "3개+"를 **"2개+"로 완화** | §1.2 실측 — `CONSULTATION_SYSTEM_PROMPT` 경로는 핵심답변+절차=2개가 최댓값인 경우가 흔함. 3개 고정 시 이 경로에서 FR-1이 사실상 죽는다 |
| D4 | 접기 대상 판정 | heading 텍스트 화이트리스트 매칭(정규식), 신규 `##` 헤딩 승격분 포함 | §3.5 |
| D5 | `<details>` summary 라벨 | **섹션 제목 + 앞 60자 요지** 병기(빈 summary 금지) | CodeRabbit 이전 리뷰(§1.4 인용) — "비어 있지 않은 summary, 내용 요지 포함" 요구를 이번엔 반영 |
| D6 | heading id 부여 | 텍스트 슬러그화 금지, **답변 시퀀스 + 인덱스**(`ans-h2-0-0`, `ans-h2-0-1`, `ans-h2-1-0`, ...) | Plan 리스크 §6 3행 — 한글 헤딩 id 충돌 방지. **초안은 인덱스만 썼으나(`ans-h2-0`) 채팅은 후속 답변이 누적되므로 답변마다 0부터 재시작해 `getElementById`가 항상 첫 답변을 잡는 충돌이 발생했다**(Check 단계 G2). 답변 시퀀스를 접두사로 붙여 유일성을 보장한다 |
| D7 | PDF/이메일 내보내기의 `<details>` 상태 | **강제로 모두 펼친 사본**을 만들어 내보낸다(라이브 DOM은 접힌 상태 유지) | §4.4 — 접힌 채 인쇄되면 내용 누락처럼 보임(P2 위반) |
| D8 | 스티키 요약(FR-3) 구현 | **양쪽 다 채택** — sticky 목차(모바일에서 유효) + "핵심으로" 플로팅 버튼(전 환경). Do 단계 실측으로 확정(§3.3) | `position: sticky`는 말풍선이 `overflow` 컨테이너 안에 있을 때 깨지는 사례가 흔함 — Do 단계에서 실측한 결과 **데스크톱에서 실제로 무효**였다 |
| D9 | 게시판 적용 시점 | 스트리밍이 없으므로(`renderDetail()`은 fetch 후 동기 렌더) finalize를 **`chatArea.innerHTML = html` 직후 즉시** 호출 | FR-6, P1은 애초에 게시판에 해당 없음 |

---

## 3. FR별 상세 설계

### 3.1 FR-1: 섹션 목차/앵커

```js
// public/finalize.js
function buildOutline(container, idPrefix) {
  // D2 v0.2: 목차에는 핵심 답변(.summary-badge 내 h2)도 **포함**한다.
  // 첫 칩이 결론 복귀 경로가 되어 FR-3에 직접 기여한다. 제외는 접기에서만.
  const heads = [...container.querySelectorAll('h2')];
  if (heads.length < 2) return null;               // D3

  const chips = document.createElement('nav');
  chips.className = 'answer-outline';
  heads.forEach((h, i) => {
    const id = idPrefix + i;   // D6 — idPrefix = 'ans-h2-{답변시퀀스}-'
    h.id = id;
    const chip = document.createElement('a');
    chip.href = '#' + id;
    chip.className = 'outline-chip';
    chip.textContent = h.textContent;
    chip.onclick = (e) => {
      e.preventDefault();
      h.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };
    chips.appendChild(chip);
  });
  return chips;
}
```

- 목차는 말풍선(`.msg.assistant`) **내부 최상단**에 삽입(`container.insertBefore(chips, container.firstChild)`). 별도 고정 헤더를 두지 않는 이유는 여러 답변이 쌓이는 채팅 로그 구조상 "화면 상단 고정"이 어느 답변 것인지 모호해지기 때문(대화가 길어지면 목차가 안 맞는 답변 위에 떠 있게 됨).
- 헤딩 2개 미만이면 `null` 반환 → 호출부가 삽입을 건너뜀(빈 nav 방지).

### 3.2 FR-2: 긴 섹션 접기/펼치기

**접기 대상 판정** — Plan 예시("법적 근거(상세)")를 그대로 쓰지 않고 §1.2 실측에 맞춘 화이트리스트:

```js
const COLLAPSIBLE_HEADINGS = [
  /^법적\s*근거/, /^관련\s*판례/, /^판례/, /^행정해석/,
  /^절차/, /^신청\s*방법/, /^산출\s*근거/, /^계산\s*과정/,
];
const ALWAYS_OPEN = [
  /핵심\s*답변/, /결론/, /요약/, /주의사항/, /면책/,
];
```

`ALWAYS_OPEN`을 먼저 검사해 매칭되면 접지 않는다(P2 — 화이트리스트 오매칭 시 안전 방향). `COLLAPSIBLE_HEADINGS`에 매칭되고 섹션 본문이 **200자 이상**일 때만 접는다 — 한두 줄짜리 짧은 절차 안내까지 접으면 오히려 클릭을 강요하게 된다(Plan 리스크 §6 2행의 "정보 은닉 오해"를 실질적으로 방지).

```js
function wrapCollapsible(container) {
  const heads = [...container.querySelectorAll('h2, h3')];
  heads.forEach((h, i) => {
    if (h.closest('.summary-badge')) return;
    const title = h.textContent.trim();
    if (ALWAYS_OPEN.some(re => re.test(title))) return;
    if (!COLLAPSIBLE_HEADINGS.some(re => re.test(title))) return;

    const section = collectSectionNodes(h);   // h부터 다음 h2/h3 직전까지 형제 노드 수집
    const bodyText = section.map(n => n.textContent).join('').trim();
    if (bodyText.length < 200) return;

    const details = document.createElement('details');
    const summary = document.createElement('summary');
    summary.textContent = title + ' — ' + bodyText.slice(0, 60).trim() + '…';  // D5
    details.appendChild(summary);
    h.remove();                                // 원래 h2/h3는 summary가 대체
    section.forEach(n => details.appendChild(n));
    heads[i].replaceWith ? null : null;         // (아래 실제 삽입 지점 처리)
    container.insertBefore(details, section[0] || null);
  });
}
```

- `<details>`/`<summary>`는 네이티브 요소라 **키보드 Enter/Space 토글, 스크린리더 상태 전달이 브라우저가 자동 처리**한다(추가 ARIA 불필요 — MDN·WHATWG 명세와 일치). D5로 summary가 항상 비지 않게 보장했으므로 접근성 요구는 구조적으로 충족된다.
- `collectSectionNodes(h)`: `h.nextElementSibling`을 따라가며 다음 `h2`/`h3` **또는 종료 마커** 직전까지 형제 요소를 모으는 헬퍼.

**종료 마커가 필요한 이유 (Check 단계 G1)**: `ALWAYS_OPEN`은 heading 텍스트만 검사한다. 그런데 프롬프트는 주의사항을 블록쿼트(`> ⚠️ **주의사항**:`, `prompts.py:411`)로, 면책 고지를 평문(`:417`)으로 지시하고, 답변 구조도 `⑥ 실무 안내(절차) → ⑦ 주의사항 + 면책` 순서(`:382`)다. 따라서 `## 절차`(COLLAPSIBLE 매칭)가 마지막 heading이면 **그 뒤의 주의사항·구분선·면책이 통째로 `<details>`에 흡수돼 기본 접힘 상태로 숨는다.** heading 단위 방어로는 못 막는 구멍이므로 별도로 끊는다.

```js
function isTerminator(n) {
  if (n.tagName === 'HR') return true;                     // 프롬프트가 지시하는 `---`
  if (n.classList && n.classList.contains('disclaimer-notice')) return true;
  var t = norm(n.textContent);
  if (/본\s*답변은[\s\S]{0,30}참고용|법적\s*효력이\s*없습니다/.test(t)) return true;
  if (/^(?:⚠️\s*)?주의\s*사항/.test(t)) return true;
  return false;
}
```

### 3.3 FR-3: 핵심 요약 상시 접근 (D8) — Do 단계 실측으로 확정

**실측 결과: sticky는 데스크톱에서 무효다.**

`public/index.html`의 CSS를 대조했다:

```css
#chat { overflow: hidden; }                                   /* 기본 */
.chat-card.active #chat { height: auto; overflow-y: visible; } /* 활성 시 */
@media (max-width: 768px) {
  .chat-card.active #chat { height: 50vh; min-height: 300px; } /* 모바일 */
}
```

CSS Overflow 명세상 **한 축이 `visible`이고 다른 축이 아니면 `visible`은 `auto`로 계산**된다. 따라서 `overflow-x: hidden` + `overflow-y: visible` → `overflow-y: auto` → `#chat`은 스크롤 컨테이너가 된다.

| 환경 | `#chat` height | 내부 스크롤 발생 | sticky |
|------|----------------|------------------|--------|
| 데스크톱 | `auto`(내용만큼 늘어남) | **없음** | **무효** — 붙을 스크롤포트가 없어 페이지가 스크롤돼도 상대 이동이 없다 |
| 모바일(≤768px) | `50vh` | 발생 | 유효 |

**확정**: 둘 다 채택한다.
- `.answer-outline`을 sticky로 둔다 — 모바일에서 유효하고, 데스크톱에서는 정적으로 자연 degrade한다(해가 없다).
- **플로팅 "⚖️ 핵심으로" 버튼**을 전 환경 경로로 추가한다. `IntersectionObserver`로 핵심 답변이 화면 위로 지나갔을 때만 표시한다.

```js
function trackJumpToCore(el) {
  var core = el.querySelector('.summary-badge') || el.querySelector('h2');
  if (!core || typeof IntersectionObserver === 'undefined') return;
  jumpTarget = core;
  var btn = ensureJumpButton();
  if (jumpObserver) jumpObserver.disconnect();   // 항상 최신 답변만 추적
  jumpObserver = new IntersectionObserver(function (entries) {
    var e = entries[0];
    var scrolledPast = !e.isIntersecting && e.boundingClientRect.top < 0;
    btn.classList.toggle('show', scrolledPast);
  }, { threshold: 0 });
  jumpObserver.observe(core);
}
```

버튼은 전역 1개만 만들고(답변마다 생성 금지) 최신 답변을 가리킨다. 위치는 `bottom: 76px; right: 24px` — 기존 `#back-to-top`(`bottom: 24px`, 44px)의 **바로 위**에 쌓아 겹침을 피한다.

### 3.4 FR-4: 스트리밍 안전 finalize — 훅 위치 확정

`public/index.html::readSSE()`(`:1280`)의 흐름을 실측 확인했다:

```
for (line of lines) { ... }        // chunk/replace 이벤트 처리 — replace도 이 루프 안에서 발생
if (streamDone) break;
...
showAnswerActions(lastAssistant);  // :1355 — 기존 마지막 후처리 호출
finalize(lastAssistant);           // ← 신규 삽입 지점, 바로 다음 줄
```

**`replace` 이벤트(citation_validator의 환각 교정)는 `streamDone` 이전, 즉 루프 내부에서 처리된다** — `finalize()`가 루프 종료 후 1회만 실행되므로 교정된 최종 텍스트를 항상 본다. 별도 재실행 로직 불필요.

```js
function finalize(el) {
  if (!el) return;
  const outline = buildOutline(el);
  if (outline) el.insertBefore(outline, el.firstChild);
  wrapCollapsible(el);
  addJumpToCore(el.closest('.msg-wrapper'), el.querySelector('.summary-badge'));
}
```

### 3.5 FR-5: 프롬프트 정합 — 결정

**선택**: `CONSULTATION_SYSTEM_PROMPT`(`prompts.py:405-415`)의 "법적 근거"·"판례 인용" 항목을 블록쿼트 유지 **+ 관련 판례가 2건 이상일 때만** `## 관련 판례` 헤딩 신설 지시를 추가한다. 전면적으로 블록쿼트를 헤딩으로 바꾸지 않는 이유:

- 블록쿼트(`callout-legal`)는 짧은 1~2줄 인용에 최적화된 기존 시각 문법이고, `answer-visual-upgrade`가 이미 검증한 패턴이다. 짧은 법적 근거 한 줄까지 `##` 헤딩+접기로 바꾸면 오히려 클릭이 늘어난다(P2 위반 소지).
- 반면 "판례가 여러 건"인 경우는 실제로 길어지고(요지+출처 반복), 이때만 헤딩으로 승격해 접는 대상이 되는 것이 Plan의 문제의식("길지만 부차적인 내용")과 정확히 맞는다.

프롬프트 diff(설계 수준, 최종 문구는 Do 단계):

```diff
   - **판례 인용**: `> 📘 **관련 판례**: 대법원 YYYY다NNNNN...` (판례 요지)
+  - **판례 2건 이상**: `> ` 대신 `## 관련 판례` heading 아래 판례별로 `- 대법원 ...` 나열
```

`SYSTEM_PROMPT_TEMPLATE`(계산기 경로)은 이미 자유 헤딩이라 변경 불필요.

### 3.6 FR-6: 게시판 상세 적용

`public/board.html::renderDetail()`(`:746`)의 `data.source !== 'user'` 분기, `chatArea.innerHTML = html;`(`:776`) 직후:

```js
// board.html 수정
chatArea.innerHTML = html;
if (data.source !== 'user' && data.answer) {
  finalize(chatArea.querySelector('.msg-bubble.bot'));   // D9 — 즉시 호출, 스트리밍 판단 불필요
}
```

`finalize()`가 `h2` 태그만 근거로 동작하므로(P4) `board.html`이 `md()`(콜아웃·요약배지 변환)를 쓰지 않고 `marked.parse()`만 써도 `<h2>` 자체는 동일하게 존재해 그대로 작동한다. 단, **`.summary-badge` 클래스가 없으므로** D2("`.summary-badge` 안 h2는 제외")가 `board.html`에서는 항상 false — "핵심 답변" 헤딩도 목차·접기 후보에 포함된다. 이는 `ALWAYS_OPEN` 화이트리스트(§3.2)가 텍스트 매칭으로 별도 방어하므로 안전하다(클래스 유무와 무관).

**CSS 공유**: `public/finalize.js`가 생성하는 요소(`.answer-outline`, `.outline-chip`, `.jump-to-core`)의 스타일은 `index.html`과 `board.html` 양쪽 `<style>` 블록에 각각 추가한다(두 페이지 모두 단일 파일 인라인 스타일 관례 — CLAUDE.md 기재 구조, 별도 CSS 파일 분리는 이번 범위 밖).

---

## 4. 변경 대상 파일

| 파일 | 변경 내용 | 근거 |
|------|-----------|------|
| **신설** `public/finalize.js` | `buildOutline`·`wrapCollapsible`·`collectSectionNodes`·`addJumpToCore`·`finalize` | D1 |
| `public/index.html` (JS) | `<script src="/finalize.js">` 추가(pwa.js 옆), `readSSE()`에 `finalize(lastAssistant)` 1줄 추가(§3.4) | FR-1~4 |
| `public/index.html` (CSS) | `.answer-outline`/`.outline-chip`/`.jump-to-core`/`details`/`summary` 스타일(<4KB, 기존 콜아웃 CSS 블록 옆) | Plan NFR |
| `public/board.html` (JS) | `<script src="/finalize.js">` 추가, `renderDetail()`에 `finalize()` 호출 1줄 추가(§3.6) | FR-6 |
| `public/board.html` (CSS) | index.html과 동일 규칙(중복 정의, 파일 분리 없음) | §3.6 |
| `app/templates/prompts.py` | `CONSULTATION_SYSTEM_PROMPT`에 "판례 2건+ → 헤딩 승격" 지시 추가(§3.5) | FR-5 |
| §4.4 별도 처리 | PDF 내보내기 경로(`actionPDF` 부근) — `<details>` 강제 오픈 사본 생성 | D7 |

### 4.4 PDF/이메일 내보내기 처리 (D7)

`getQAPair()`(`index.html`)가 `a.innerHTML`(렌더된 DOM)을 그대로 써서 PDF를 만든다. finalize 적용 후 `<details>`가 접힌 채로 내보내지면 내용이 통째로 빠진 것처럼 보인다. 내보내기 직전에 사본에서 강제로 편다:

```js
function expandDetailsForExport(html) {
  const tmp = document.createElement('div');
  tmp.innerHTML = html;
  tmp.querySelectorAll('details').forEach(d => d.open = true);
  tmp.querySelectorAll('.answer-outline').forEach(n => n.remove());  // 목차는 PDF에 불필요
  return tmp.innerHTML;
}
```

`actionPDF()`·`openEmailModal()` 호출 직전에 `fullHtml`을 이 함수로 한 번 통과시킨다. 복사(`actionCopy`)·마크다운 저장은 `.dataset.md`(원문)를 쓰므로 이 처리가 필요 없다(P3).

---

## 5. 리스크 재확인 (Plan §6 대비)

| Plan 리스크 | 설계 대응 |
|-------------|-----------|
| 스트리밍 중 부분 heading 오작동 | §3.4 — finalize는 루프 종료 후 1회, `replace`도 이미 반영된 최종 텍스트를 봄 |
| 접기가 정보 은닉으로 오해 | §3.2 — `ALWAYS_OPEN` 우선 판정 + 200자 미만 미접기 + summary에 요지 60자 병기(D5) |
| 한글 heading 앵커 id 충돌 | D6 — 인덱스 기반 id |
| 모바일 목차 공간 | Plan NFR 그대로(가로 스크롤 칩) — CSS만으로 해결, 별도 설계 불요 |
| 방향이 사용자 의도와 어긋남 | Plan §8이 사용자 확정으로 종결(2026-08-06) — 본 설계는 그 확정을 전제로 진행 |
| **(신규)** PDF 내보내기에 접힌 섹션 포함 | D7 — 내보내기 전용 강제 펼침 사본 |
| **(신규)** 스티키 요약이 스크롤 컨테이너 제약으로 깨짐 | D8 — 앵커 버튼 폴백 경로 사전 설계 |
| **(신규)** `board.html`은 `.summary-badge` 클래스가 없어 D2가 무력화 | §3.6 — `ALWAYS_OPEN` 텍스트 매칭이 클래스 무관하게 방어 |

---

## 6. 구현 순서 (Do 단계 체크리스트)

- [ ] `public/finalize.js` 신설 — `buildOutline`·`wrapCollapsible`·`collectSectionNodes`·`addJumpToCore`(§3.1~3.3)
- [ ] `index.html`에 스크립트 로드 + `readSSE()` 훅 1줄(§3.4)
- [ ] `index.html` CSS 추가(목차 칩·details·jump-to-core, <4KB 확인)
- [ ] 스티키 시도 → 실패 시 D8 폴백 전환(둘 중 하나로 확정)
- [ ] `CONSULTATION_SYSTEM_PROMPT` 판례 2건+ 헤딩 승격 지시 추가(§3.5) — 골든셋 답변 몇 건으로 회귀 확인
- [ ] `board.html`에 스크립트 로드 + `renderDetail()` 훅 1줄(§3.6), CSS 복제
- [ ] PDF/이메일 내보내기 강제 펼침 처리(§4.4)
- [ ] 수동 검증: 계산기 답변(헤딩 多)·법률상담 답변(헤딩 少, 판례 2건+ 케이스 포함)·괴롭힘 판정 답변, 양쪽 페이지, 모바일 뷰
- [ ] 기존 콜아웃/스텝/테이블/`board.html` 마크다운 렌더 회귀 없음 확인
- [ ] `md()` XSS 이스케이프, `board.html`의 `DOMPurify.sanitize()` 무변경 확인(finalize는 이미 살균된 DOM만 다룸 — 신규 XSS 표면 없음)

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-08-06 | 초안 — 프롬프트 헤딩 밀도 실측(핵심 발견), D1~D9 설계 결정, FR-1~6 상세 설계, PDF 내보내기·스티키 폴백 신규 리스크 도출 | DrunkenZealnut |
| 0.2 | 2026-08-06 | Do 단계 실측 반영 — **sticky가 데스크톱에서 무효**임을 CSS overflow 계산으로 확인(§3.3), D8을 "sticky + 플로팅 버튼 병행"으로 확정. D2를 "목차에는 핵심 답변 포함, 접기에서만 제외"로 정정 | DrunkenZealnut |
| 0.3 | 2026-08-07 | Check·Act-1 반영 — **D6 개정**(인덱스만으로는 답변 누적 시 id 충돌 → 답변 시퀀스 접두사). **§3.2에 종료 마커 근거 추가**(프롬프트가 주의사항·면책을 heading이 아닌 형식으로 지시해 heading 단위 방어로는 못 막던 구멍). §3.1 v0.1 잔재 필터 삭제 | DrunkenZealnut |
