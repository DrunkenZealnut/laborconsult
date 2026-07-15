# 답변 UI 가독성 재점검 Design (answer-ui-readability)

> **Summary**: `public/index.html` 단일 파일에서 ① 표를 `.table-wrap` 스크롤 래퍼로 감싸 항상 답변 폭 100%를 채우게 하고 ② 목록 파서를 "번호 우선 + 들여쓰기 스택" 구조로 재작성해 중첩 불릿·번호 연속성·**중첩 placeholder 내용 소실(신규 확정 P1)**을 해결하며 ③ 타이포 스케일(h2 18/h3 16/본문 15)과 간격 리듬을 정리한다. 렌더러 추출 하네스로 현행 결함 3건을 재현 확정했고, 동일 하네스를 회귀 검증에 재사용한다.
>
> **Plan**: docs/01-plan/features/answer-ui-readability.plan.md
> **Author**: DrunkenZealnut
> **Date**: 2026-07-16
> **Status**: Draft

---

## 1. 개요 및 사전 검증 결과

Plan §3의 발견사항 중 "검증 필요"였던 LST-2를 렌더러 추출 하네스(Node, `md()` 968~1080행 추출 + `renderTex`/`renderMdLink` 스텁)로 **재현 확정**했고, 그 과정에서 신규 P1 결함 1건과 부수 아티팩트 1건을 추가 확인했다.

### 1.1 재현 결과 (하네스 실측)

| 케이스 | 입력 패턴 | 현행 출력 (실측) | 판정 |
|--------|-----------|------------------|------|
| C1 | 들여쓴 하위 불릿 | 4개 항목이 평탄한 단일 `<ul>` — 들여쓰기 소실 | LST-1 확정 |
| C2 | `1.` → 들여쓴 하위 불릿 → `2.` → `3.` | `<li>첫…<br>\x00B0\x002. 두…</li><li>세…</li>` — ② 항목이 ①에 병합되고 **하위 불릿 내용은 미복원 placeholder로 소실**, 원시 `\x00B0\x00` 바이트가 최종 HTML에 잔존 | LST-2 확정 + **LST-5 신규** |
| C3 | 번호 항목 + `→ 계산식` continuation | 단일 `<ol>`에 `<br>` 병합 — 정상 | 보존 대상 |
| C4 | 표 + 뒤따르는 문단 | 표 정상, 단 후속 문단이 `<p><br>이상…` — 잔여 `<br>` | TYP-3 신규(경미) |
| C5 | `1.` → 표(빈 줄 없음) → `2.` | ② 병합 + **표 전체 소실**(미복원 placeholder) | LST-5 동일 계열 |

### 1.2 근본 원인 (3가지)

1. **stash 개행 소비**: 표/목록/콜아웃 블록 정규식이 마지막 줄의 `\n`까지 캡처해 placeholder가 다음 줄과 붙음 → 뒤따르는 `2. …` 줄이 번호 항목으로 인식되지 못하고 continuation으로 병합 (LST-2 병합·TYP-3 잔여 `<br>`의 공통 원인).
2. **단일 패스 복원**: 1075행 `html.replace(/\x00B(\d+)\x00/g, …)`는 치환 결과를 재스캔하지 않으므로, stash된 블록 HTML **안에** 다른 placeholder가 들어 있으면(번호 목록이 불릿 placeholder를 삼킨 경우) 영구 미복원 → 내용 소실 (LST-5).
3. **파싱 순서**: 불릿(1021행)이 번호(1027행)보다 먼저 stash되므로, 번호 항목에 딸린 들여쓴 하위 불릿이 독립 블록으로 찢겨 나감 (LST-1·2의 구조적 원인).

### 1.3 설계 원칙

- **단일 파일 완결**: 변경은 전부 `public/index.html` (CSS `<style>` + `md()` 주변 JS). 외부 라이브러리 도입 없음 (Plan Out of Scope).
- **보존 우선**: C3 continuation 병합, step-list 판별(절차 키워드), 콜아웃/요약 배지/total-row/num-cell/수식/링크 동작은 그대로.
- **스트리밍 내성**: SSE 청크 수신 중 부분 마크다운 재렌더링이 반복되므로 파서는 상태 없는 순수 함수 유지, 구조 변경은 래퍼 1겹 수준으로 최소화.

---

## 2. Wave A — 표 (TBL-1·2·3)

### 2.1 렌더러 변경 (`md()` 1000~1019행)

표 생성부 앞뒤에 래퍼 1겹 추가:

```js
// before
let h = '<table>';
…
h += '</table>';
return stash(h);

// after
let h = '<div class="table-wrap"><table>';
…
h += '</table></div>';
return stash(h) + '\n';   // ← §4.1 stash 개행 보존과 동시 적용
```

### 2.2 CSS 변경 (233~239행 교체)

```css
/* before (233행): table에 display:block·width:auto·스크롤·테두리·radius가 전부 걸림 */
.msg.assistant table { border-collapse: collapse; margin: 10px 0; font-size: 14px; width: auto; display: block; overflow-x: auto; -webkit-overflow-scrolling: touch; border-radius: 8px; border: 1px solid var(--border); }

/* after: 스크롤·테두리·radius는 래퍼가, 폭은 표가 담당 */
.msg.assistant .table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; margin: 12px 0; border: 1px solid var(--border); border-radius: 8px; }
.msg.assistant table { border-collapse: collapse; font-size: 14px; width: 100%; margin: 0; }
```

셀 줄바꿈 정책 (234~235·239행):

```css
/* th: 헤더는 nowrap 유지(줄바꿈 시 열 제목 가독성 저하) */
.msg.assistant th { background: var(--navy); color: #fff; font-weight: 600; padding: 8px 12px; text-align: left; white-space: nowrap; border: none; border-bottom: 2px solid var(--navy-deep); }
/* td: nowrap 제거 → 설명형 셀 줄바꿈 허용 */
.msg.assistant td { padding: 7px 12px; text-align: left; border: none; border-bottom: 1px solid var(--border); }
/* 숫자 셀만 nowrap 유지 (금액 줄바꿈 방지) */
.msg.assistant td.num-cell { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
```

- zebra(`tr:nth-child(even) td`)·`total-row`·`tr:last-child td` 규칙은 **무변경**.
- radius를 래퍼로 옮겼으므로 래퍼에 `overflow-x: auto`가 이미 있어 모서리 잘림은 자동 해결 (`overflow: hidden` 불요 — auto가 클리핑 겸함).

### 2.3 파급 지점

- PDF 내보내기: `answerHtml`에 `.table-wrap` div가 포함되어 전달됨 → §5.3에서 인쇄 CSS 동기화.
- `getQAPair()`의 마크다운 경로(answerMd)는 원문 마크다운 사용이라 무영향.

---

## 3. Wave B — 목록 (LST-1·2·3·4·5)

### 3.1 파싱 순서 재배치: 번호 우선

현행 `불릿(1021) → 번호(1027)` 순서를 **`번호 → 불릿`으로 교체**. 번호 블록이 자신에게 딸린 들여쓴 하위 불릿을 직접 소비하므로, 하위 불릿이 독립 stash로 찢기는 구조적 원인이 제거된다.

### 3.2 번호 목록 파서 (1027~1042행 교체)

**블록 캡처 정규식** — 현행과의 유일한 차이: continuation 제외 조건 `(?![ \t]*[-*] )`(모든 불릿)을 `(?![-*][ \t])`(들여쓰기 없는 불릿만 제외)로 완화해 **들여쓴 불릿을 블록 안으로 수용**:

```js
/((?:^[ \t]*\d+\.[ \t].+(?:\n(?![ \t]*\d+\.[ \t])(?![-*][ \t]).+)*$\n?)+)/gm
```

**워커 (줄 분류)** — 블록 내 각 줄을 3종으로 분류:

| 패턴 | 분류 | 처리 |
|------|------|------|
| `^[ \t]*(\d+)\.[ \t]+(.*)$` | 번호 항목 | 새 `<li>` 시작 (들여쓴 번호도 현행대로 평탄 항목) |
| `^([ \t]+)[-*][ \t]+(.*)$` | 들여쓴 하위 불릿 | 직전 항목의 `subs` 배열에 `{indent, text}` 추가 |
| 그 외 비어있지 않은 줄 | continuation | 직전 항목 본문에 `\n` 병합 (현행 C3 동작 보존, `.trim()` 유지) |

**렌더링**:

```js
const lis = items.map(it => {
  let inner = inlineTransform(it.text).replace(/\n/g, '<br>');
  if (it.subs.length) inner += buildNestedUl(it.subs);   // §3.4 공통 빌더
  return '<li>' + inner + '</li>';
}).join('');
return stash(isStep ? '<ol class="step-list">' + lis + '</ol>' : '<ol>' + lis + '</ol>') + '\n';
```

- step-list 판별(preceding 200자 절차 키워드 검사)은 **로직 무변경** 유지.
- 하위 불릿이 있는 항목도 continuation(`→ 계산식`)과 공존 가능: continuation은 본문 `<br>` 병합, 하위 불릿은 뒤따르는 `<ul>`.

### 3.3 불릿 목록 파서 (1021~1025행 교체)

캡처 정규식은 현행 유지(`/((?:^[ \t]*[-*][ \t].+$\n?)+)/gm`), 평탄화 대신 들여쓰기 스택으로 중첩 생성:

```js
text = text.replace(/((?:^[ \t]*[-*][ \t].+$\n?)+)/gm, block => {
  const items = block.replace(/\n+$/, '').split('\n').map(l => {
    const m = l.match(/^([ \t]*)[-*][ \t]+(.*)$/);
    return { indent: indentWidth(m[1]), text: m[2] };
  });
  return stash(buildNestedUl(items)) + '\n';
});
```

### 3.4 공통 빌더 `buildNestedUl(items)`

들여쓰기 스택 기반, **최대 중첩 2단계**(level 0·1·2, 초과 들여쓰기는 level 2로 캡):

```
indentWidth(s): 탭=2칸 환산한 공백 수

buildNestedUl(items):
  stack = [items[0].indent]        # 레벨별 기준 들여쓰기
  html = '<ul>'
  for each {indent, text}:
    while stack.length > 1 and indent < stack.top - 1:    # 얕아지면 닫기 (±1 허용)
      html += '</ul></li>'; stack.pop()
    if indent > stack.top + 1 and stack.length < 3:       # 깊어지면 열기 (2단계 캡)
      html = html.rstrip('</li>')                          # 직전 li를 부모로 재개방
      html += '<ul>'; stack.push(indent)
    html += '<li>' + inlineTransform(text) + '</li>'
  while stack.length > 1: html += '</ul></li>'; stack.pop()
  return html + '</ul>'
```

- ±1칸 허용치: LLM 출력의 2·3·4칸 혼용(불릿 하위 2칸, 번호 하위 3칸)을 같은 레벨 전환점으로 흡수.
- "직전 li 재개방"은 문자열 조작(마지막 `</li>` 제거) 방식 — 구현 시 items를 선순회해 트리를 만든 뒤 직렬화해도 무방하며, 결과 HTML 형태(`<li>부모<ul><li>자식</li></ul></li>`)만 계약으로 고정한다.

### 3.5 stash 개행 보존 + 재귀 복원 (LST-5·TYP-3)

**개행 보존**: 줄 단위 블록 정규식 4곳(표·번호·불릿·콜아웃)의 반환을 `stash(html) + '\n'`으로 통일. 캡처가 삼킨 마지막 개행을 되살려 placeholder가 항상 독립 줄이 되게 한다 → 다음 `2. …` 줄이 정상적으로 새 항목 인식(LST-2 병합 해소), 블록 뒤 문단의 잔여 `<br>` 소멸(TYP-3 해소).

**재귀 복원**: 1075행 단일 패스를 고정점 루프로 교체:

```js
// before
html = html.replace(/\x00B(\d+)\x00/g, (_, i) => '</p>' + blocks[+i] + '<p>');

// after — stash된 블록 안의 placeholder(번호 목록이 삼킨 표 등)까지 복원
let prev;
do {
  prev = html;
  html = html.replace(/\x00B(\d+)\x00/g, (_, i) => '</p>' + blocks[+i] + '<p>');
} while (html !== prev);
```

- 종료 보장: stash는 자신보다 **먼저** 저장된 블록의 placeholder만 품을 수 있어(DAG) 순환 불가, 루프는 미해결 placeholder 수가 0이 될 때까지 단조 감소.
- 알려진 한계(수용): `<li>` 안에서 복원되는 블록은 `</p>…<p>` 래핑이 li 내부에 남지만 브라우저 파서가 자동 회복하며 시각 결함 없음 — 현행 표-단독 케이스와 동일한 기존 동작. Do 단계 브라우저 검증(T10)에서 시각 이상 시 "li 내부 placeholder는 래핑 없이 치환"으로 보강한다.

### 3.6 목록 CSS (232행 + 신규)

```css
.msg.assistant ul, .msg.assistant ol { margin: 8px 0 8px 22px; }
.msg.assistant li { margin: 3px 0; }                     /* LST-3: 항목 호흡 */
.msg.assistant li > ul { margin: 3px 0 3px 18px; }       /* LST-4: 중첩 들여쓰기 */
.msg.assistant li > ul li { font-size: 14.5px; }         /* 하위 항목 약간 축소(선택) */
```

**step-list 스코프 수정 (필수)** — 현행 `.step-list li` 선택자(258~261행)는 중첩 `<ul>`의 li에도 원형 번호를 그리므로 직계로 한정:

```css
/* 258~261행: .step-list li → .step-list > li  (모바일 428~430행 동일) */
.msg.assistant .step-list > li { counter-increment: step-counter; … }
.msg.assistant .step-list > li::before { … }
.msg.assistant .step-list > li::after { … }
.msg.assistant .step-list > li:last-child::after { display: none; }
/* step-list 안 하위 불릿은 일반 불릿으로 복원 */
.msg.assistant .step-list ul { list-style: disc; margin: 4px 0 0 18px; padding: 0; }
.msg.assistant .step-list ul li { padding: 2px 0; }
```

---

## 4. Wave C — 타이포·간격·일관성 (TYP-1·2, ETC-1·2·3)

### 4.1 타이포 스케일 (229~231행)

| 요소 | 현행 | 변경 | 근거 |
|------|------|------|------|
| h2 | 16px, margin 14/6 | **18px**, margin 18px 0 8px, `padding-bottom: 4px; border-bottom: 1px solid var(--border)` | 섹션 경계 시각화 |
| h3 | 15px, margin 10/4 | **16px**, margin 14px 0 6px | 본문(15px)과 구분 |
| p | margin 6px | margin **8px** 0 | 문단 호흡 |
| 표/콜아웃/step-list | 14px | 14px 유지 | 밀도 유지 |

summary-badge 내부 h2는 자체 스타일 보존:

```css
.msg.assistant .summary-badge h2 { font-size: 16px; margin: 0 0 6px; border-bottom: none; padding-bottom: 0; color: var(--co-legal-icon); }
```

### 4.2 말풍선 여백 대칭 (210행, ETC-3)

```css
/* before */ .msg.assistant :first-child { margin-top: 0; }
/* after  */ .msg.assistant > :first-child { margin-top: 0; }
            .msg.assistant > :last-child { margin-bottom: 0; }
```

### 4.3 PDF 내보내기 동기화 (1281행, ETC-1)

인쇄 CSS에 폭·zebra·숫자 정렬·중첩 목록 추가:

```
table{width:100%;border-collapse:collapse;margin:12px 0;}
th,td{border:1px solid #ddd;padding:6px 10px;text-align:left;}
th{background:#1B2A4A;color:#fff;}
tr:nth-child(even) td{background:#faf8f5;}
td.num-cell{text-align:right;white-space:nowrap;}
tr.total-row td{font-weight:700;background:#f5efe6;}
.table-wrap{margin:12px 0;}
ul ul{margin:2px 0 2px 18px;}
li{margin:3px 0;}
```

### 4.4 모바일 (≤600px 미디어쿼리, ETC-2)

```css
.msg.assistant table { font-size: 13px; }
.msg.assistant th, .msg.assistant td { padding: 6px 10px; }
.msg.assistant ul, .msg.assistant ol { margin-left: 18px; }
.msg.assistant li > ul { margin-left: 14px; }
```

(기존 모바일 step-list 3행은 `> li`로 스코프만 교체)

---

## 5. 변경 지점 요약

전 항목 `public/index.html` 단일 파일:

| # | 위치(현행 행) | 변경 | Wave |
|---|---------------|------|------|
| 1 | 210 | first/last-child 직계 스코프 + last 추가 | C |
| 2 | 229~232 | h2/h3/p/ul·ol 타이포·간격 | C |
| 3 | 233~239 | 표 CSS 재편(`.table-wrap` 신설, td nowrap 제거) | A |
| 4 | 256 | summary-badge h2 border 예외 | C |
| 5 | 257~261 | step-list `> li` 스코프 + 중첩 ul 복원 규칙 | B |
| 6 | 신규(232 부근) | `li` 간격·`li > ul` 중첩 규칙 | B |
| 7 | 411~432 | 모바일: 표 패딩·폰트, 목록 들여쓰기, step-list 스코프 | C |
| 8 | 968 부근 신규 | `indentWidth()`·`buildNestedUl()` 헬퍼 | B |
| 9 | 1000~1019 | 표 래퍼 + stash 개행 | A |
| 10 | 1021~1025 | 불릿 파서 → 중첩 빌더 호출 | B |
| 11 | 1027~1042 | 번호 파서 → 하위 불릿 수용 워커 (번호 pass를 불릿 pass **앞**으로 이동) | B |
| 12 | 1044~1056 | 콜아웃 stash 개행 보존(`+'\n'`) | B |
| 13 | 1074~1075 | 복원 고정점 루프 | B |
| 14 | 1277~1282 | PDF 인쇄 CSS 동기화 | C |

---

## 6. 테스트 설계

### 6.1 하네스 회귀 (Node, 스크래치 도구 — 저장소 미커밋)

Design 검증에 쓴 추출 하네스를 Do 완료 후 재실행해 어서션으로 판정:

| # | 입력 | 어서션 |
|---|------|--------|
| T1 | C4 표 | `<div class="table-wrap"><table>` 래핑, 뒤 문단에 잔여 `<br>` 없음 |
| T2 | C1 중첩 불릿 | `<ul><li>상위…<ul><li>하위…` 중첩 구조, 최상위 `<li>` 2개 |
| T3 | C2 번호+하위불릿 | 단일 `<ol>`에 `<li>` 3개, li① 안에 `<ul>` 2항목, 출력에 `\x00` 부재 |
| T4 | C3 continuation | 현행과 동일 출력 (`<br>→ 계산식` 병합 유지) |
| T5 | C5 표 인접 | `\x00` 부재, 표 HTML 실존, `<ol>` 항목 수 2 |
| T6 | 절차 키워드 + 번호 | `<ol class="step-list">` 판별 유지 |
| T7 | 3단계 이상 들여쓰기 | level 2로 캡(4중 `<ul>` 미생성) |
| T8 | 콜아웃/요약배지/합계행/num-cell/수식/링크 각 1건 | 현행 출력과 동일(무회귀) |

### 6.2 브라우저 검증 (uvicorn :5555 + Chrome)

| # | 확인 | 기준 |
|---|------|------|
| B1 | 2열 좁은 표 | 표 폭 = 말풍선 내부 폭 (중간 끊김 소멸) |
| B2 | 8열 넓은 표 | `.table-wrap` 내부 가로 스크롤, body 가로 스크롤 없음 |
| B3 | 긴 텍스트 셀 | 줄바꿈 발생, num-cell은 한 줄 유지·우측 정렬 |
| B4 | step-list + 하위 불릿 | 원형 번호는 직계 li만, 하위는 disc 불릿 |
| B5 | 375px 뷰포트 | 표 스크롤 정상, 목록 들여쓰기 과다 없음 |
| B6 | h2/h3 위계 | 섹션 경계 식별 가능 (스크린샷 전후 비교) |
| B7 | 내보내기 3종 | 복사 정상, PDF 표 스타일 일치, MD 원문 무변화 |

### 6.3 회귀 고정 축

콜아웃 4종, summary-badge, step-list 판별 키워드, total-row, num-cell, zebra, TeX 수식, 링크, disclaimer-notice, SSE 스트리밍 중 점진 재렌더.

---

## 7. 구현 순서 (Do)

1. **Wave A**: 표 래퍼(§2.1) + 표 CSS(§2.2) → T1·B1~B3
2. **복원 기반**: stash 개행 보존(§3.5) + 고정점 루프 → T5 선행 확보 (파서 교체 전에도 C5 소실이 병합-렌더로 완화됨)
3. **Wave B**: `indentWidth`/`buildNestedUl` 헬퍼 → 번호 파서 교체·pass 순서 이동(§3.2) → 불릿 파서 교체(§3.3) → T2~T7
4. **step-list CSS 스코프**(§3.6) → B4
5. **Wave C**: 타이포·간격·여백(§4.1~2) → 모바일(§4.4) → PDF(§4.3) → T8·B5~B7
6. 하네스 전체 재실행 + 브라우저 스크린샷 전후 비교

각 단계 후 하네스 실행으로 즉시 회귀 검출. 단일 파일이므로 롤백은 git 단위로 자명.

---

## 8. 구현 확정 사항 (Do 단계 반영 — 설계 보완 4건)

구현·브라우저 검증 중 확정되어 본 설계에 편입된 사항:

| # | 내용 | 근거 |
|---|------|------|
| D1 | **표 셀에 `inlineTransform()` 적용** — 셀 내 `**볼드**`가 별표 원문째 노출되던 기존 버그(스크린샷 검증에서 발견). num-cell·total-row 판정은 볼드 제거 후 검사라 무영향 | B1 스크린샷 — `**합계**` 원문 노출 |
| D2 | **`.msg.assistant { width: 100% }`** — 짧은 답변일 때 말풍선이 shrink-to-fit으로 좁아져 표가 여전히 "중간에 끝나 보이는" 체감 문제 해소. 답변 폭 일관성 확보(전역 `* { box-sizing: border-box }` 확인됨). user 말풍선은 기존 유지 | B1 실측 — 말풍선 444px vs 카드 676px |
| D3 | **`td { word-break: keep-all }`** — `.msg`의 `word-break: break-word` 상속으로 모바일에서 "8시간"이 글자 단위 세로 분해되던 문제. 어절 단위 줄바꿈으로 짧은 셀은 온전히 유지, 넘치면 래퍼 스크롤 발동 | B5 스크린샷 — 375px 셀 분해 |
| D4 | **`<p><br>` → `<p>` 정리 패스 추가** — stash 개행 보존 후에도 블록-텍스트가 빈 줄 없이 붙은 케이스에서 문단 선두 `<br>`이 남는 경로 차단 (기존 `<p></p>` 정리와 함께 수행) | T1 어서션 |

## 9. 성공 기준 매핑 (Plan §5)

| Plan 기준 | 검증 |
|-----------|------|
| 표 폭 100% (넘칠 때만 스크롤) | B1·B2 |
| 긴 셀 줄바꿈·num-cell 보존 | B3·T8 |
| 하위 불릿 실제 중첩 | T2·T3 |
| 번호 연속성 유지 | T3·T5 |
| h2/h3/본문 위계 | B6 |
| 600px 이하 표 수용 | B5 |
| 리치 컴포넌트·내보내기 무회귀 | T4·T6·T8·B4·B7 |
| (신규) placeholder 내용 소실 해소 | T3·T5의 `\x00` 부재 어서션 |
