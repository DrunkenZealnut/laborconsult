# Design: 답변 시각화 학습자료 수준 업그레이드

> Plan Reference: `docs/01-plan/features/answer-visual-upgrade.plan.md`

---

## 1. 설계 개요

### 1.1 변경 대상 파일 및 역할

| 파일 | 변경 영역 | 변경 내용 |
|------|-----------|-----------|
| `public/index.html` | CSS (line 9~111) | 콜아웃 박스, 향상된 테이블, 요약 배지, 스텝 인디케이터, 구분선, 면책 고지 스타일 추가 |
| `public/index.html` | JS `md()` (line 437~490) | blockquote→콜아웃, heading→섹션카드, table 향상, ol→스텝 변환, 면책고지 감지 |
| `app/templates/prompts.py` | COMPOSER_SYSTEM (line 236~241) | 시각화 규칙을 콜아웃 트리거 패턴으로 업데이트 |
| `app/templates/prompts.py` | CONSULTATION_SYSTEM_PROMPT (line 288~296) | 동일한 시각화 규칙 동기화 |

### 1.2 설계 원칙

1. **md() 함수 내에서 완결**: 새로운 외부 라이브러리 없이 기존 `stash()` 패턴을 활용
2. **기존 패턴 보존**: 콜아웃 트리거에 매칭되지 않는 blockquote는 현재 스타일 유지
3. **CSS 변수 활용**: 기존 `:root` 변수 체계에 콜아웃 색상 변수 추가
4. **스트리밍 안전**: md()는 `replace` 이벤트의 전체 텍스트에도, `chunk` 누적 텍스트에도 적용되므로 부분 매칭에 안전해야 함

---

## 2. CSS 컴포넌트 상세 설계

### 2.1 CSS 변수 추가

`:root`에 콜아웃 색상 변수 추가 (line 10, 기존 변수 뒤에 이어서):

```css
:root {
  /* 기존 유지 */
  --primary: #2563eb; --bg: #f8fafc; --card: #ffffff; --text: #1e293b; --muted: #64748b; --border: #e2e8f0;
  /* 콜아웃 색상 추가 */
  --co-legal-bg: #eff6ff; --co-legal-border: #2563eb; --co-legal-icon: #1d4ed8;
  --co-warn-bg: #fffbeb; --co-warn-border: #d97706; --co-warn-icon: #b45309;
  --co-danger-bg: #fef2f2; --co-danger-border: #dc2626; --co-danger-icon: #b91c1c;
  --co-tip-bg: #f0fdf4; --co-tip-border: #16a34a; --co-tip-icon: #15803d;
  --co-summary-bg: #eff6ff; --co-summary-border: #2563eb;
}
```

### 2.2 콜아웃 박스 CSS (4종)

기존 `.msg.assistant blockquote` (line 52) 아래에 추가:

```css
/* ── 콜아웃 박스 ── */
.msg.assistant .callout {
  border-left: 4px solid var(--border);
  border-radius: 0 8px 8px 0;
  padding: 10px 14px;
  margin: 10px 0;
  font-size: 14px;
  line-height: 1.6;
  color: var(--text);
}
.msg.assistant .callout-title {
  font-weight: 700;
  font-size: 14px;
  margin-bottom: 4px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.msg.assistant .callout-legal  { background: var(--co-legal-bg);  border-left-color: var(--co-legal-border); }
.msg.assistant .callout-warn   { background: var(--co-warn-bg);   border-left-color: var(--co-warn-border); }
.msg.assistant .callout-danger { background: var(--co-danger-bg); border-left-color: var(--co-danger-border); }
.msg.assistant .callout-tip    { background: var(--co-tip-bg);    border-left-color: var(--co-tip-border); }

.msg.assistant .callout-legal  .callout-title { color: var(--co-legal-icon); }
.msg.assistant .callout-warn   .callout-title { color: var(--co-warn-icon); }
.msg.assistant .callout-danger .callout-title { color: var(--co-danger-icon); }
.msg.assistant .callout-tip    .callout-title { color: var(--co-tip-icon); }
```

### 2.3 요약 배지 CSS

```css
/* ── 요약 배지 (핵심 답변 박스) ── */
.msg.assistant .summary-badge {
  background: var(--co-summary-bg);
  border-left: 5px solid var(--co-summary-border);
  border-radius: 0 10px 10px 0;
  padding: 12px 16px;
  margin: 10px 0;
  font-size: 15px;
  line-height: 1.7;
}
.msg.assistant .summary-badge h2 {
  font-size: 16px;
  margin: 0 0 6px;
  color: var(--co-legal-icon);
}
```

### 2.4 향상된 테이블 CSS

기존 `.msg.assistant table` (line 45~47)을 **교체**:

```css
/* ── 향상된 테이블 ── */
.msg.assistant table {
  border-collapse: collapse;
  margin: 10px 0;
  font-size: 14px;
  width: auto;
  display: block;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  border-radius: 8px;
  border: 1px solid var(--border);
}
.msg.assistant th {
  background: var(--primary);
  color: #ffffff;
  font-weight: 600;
  padding: 8px 14px;
  text-align: left;
  white-space: nowrap;
  border: none;
  border-bottom: 2px solid #1d4ed8;
}
.msg.assistant td {
  padding: 7px 14px;
  text-align: left;
  white-space: nowrap;
  border: none;
  border-bottom: 1px solid var(--border);
}
.msg.assistant tr:nth-child(even) td {
  background: var(--bg);
}
.msg.assistant tr:last-child td {
  border-bottom: none;
}
/* 합계 행 자동 감지 (JS에서 .total-row 클래스 부여) */
.msg.assistant tr.total-row td {
  font-weight: 700;
  border-top: 2px solid var(--primary);
  background: var(--co-legal-bg);
}
/* 금액 컬럼 우측 정렬 (JS에서 .num-cell 클래스 부여) */
.msg.assistant td.num-cell {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
```

### 2.5 스텝 인디케이터 CSS

```css
/* ── 스텝 인디케이터 ── */
.msg.assistant .step-list {
  list-style: none;
  margin: 10px 0;
  padding: 0;
  counter-reset: step-counter;
}
.msg.assistant .step-list li {
  counter-increment: step-counter;
  position: relative;
  padding: 8px 0 8px 40px;
  margin: 0;
  line-height: 1.5;
  font-size: 14px;
}
.msg.assistant .step-list li::before {
  content: counter(step-counter);
  position: absolute;
  left: 0;
  top: 8px;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: var(--primary);
  color: #fff;
  font-size: 13px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}
.msg.assistant .step-list li::after {
  content: '';
  position: absolute;
  left: 12px;
  top: 36px;
  width: 2px;
  height: calc(100% - 28px);
  background: var(--border);
}
.msg.assistant .step-list li:last-child::after {
  display: none;
}
```

### 2.6 구분선 개선 CSS

기존 `<hr>` 스타일 추가:

```css
/* ── 구분선 ── */
.msg.assistant hr {
  border: none;
  height: 1px;
  background: linear-gradient(to right, transparent, var(--border), transparent);
  margin: 18px 0;
}
```

### 2.7 면책 고지 CSS

```css
/* ── 면책 고지 ── */
.msg.assistant .disclaimer-notice {
  font-size: 12px;
  color: var(--muted);
  border-top: 1px solid var(--border);
  margin-top: 14px;
  padding-top: 10px;
  line-height: 1.5;
}
```

### 2.8 모바일 반응형 (600px 이하)

기존 `@media (max-width: 600px)` 블록 (line 95~110)에 추가:

```css
@media (max-width: 600px) {
  /* 기존 규칙 유지 */

  /* 콜아웃 패딩 축소 */
  .msg.assistant .callout { padding: 8px 10px; margin: 8px 0; }
  .msg.assistant .summary-badge { padding: 10px 12px; }

  /* 스텝 인디케이터 축소 */
  .msg.assistant .step-list li { padding-left: 34px; }
  .msg.assistant .step-list li::before { width: 22px; height: 22px; font-size: 11px; }
  .msg.assistant .step-list li::after { left: 10px; top: 32px; }
}
```

---

## 3. JavaScript md() 함수 확장 설계

### 3.1 변경 전략

기존 `md()` 함수의 처리 파이프라인:

```
1. code block stash      (line 441-442)
2. math stash            (line 444-447)
3. table stash           (line 449-462)  ← 향상된 테이블 로직 적용
4. ul stash              (line 464-467)
5. ol stash              (line 468-471)  ← 스텝 인디케이터 변환 추가
6. inline transforms     (line 473-483)  ← blockquote→콜아웃, heading→요약배지
7. paragraph wrapping    (line 485-489)
8. [NEW] 면책 고지 후처리
```

### 3.2 콜아웃 변환 로직

**위치**: line 481 (기존 blockquote 변환) **교체**

기존:
```js
.replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>')
```

교체:
```js
.replace(/^> (.+)$/gm, (_, content) => {
  const calloutMap = [
    { pattern: /^(?:📘\s*)?(?:\*\*)?(?:법적\s*근거|관련\s*법조문|관련\s*법률|법령)(?:\*\*)?/i, type: 'legal', icon: '📘', label: '' },
    { pattern: /^(?:⚠️\s*)?(?:\*\*)?(?:주의사항|주의|유의|예외)(?:\*\*)?/i, type: 'warn', icon: '⚠️', label: '' },
    { pattern: /^(?:🚨\s*)?(?:\*\*)?(?:중요|필수|경고|금지)(?:\*\*)?/i, type: 'danger', icon: '🚨', label: '' },
    { pattern: /^(?:💡\s*)?(?:\*\*)?(?:참고|팁|알아두세요|도움말|안내)(?:\*\*)?/i, type: 'tip', icon: '💡', label: '' },
  ];
  for (const { pattern, type, icon } of calloutMap) {
    const m = content.match(pattern);
    if (m) {
      const title = m[0].replace(/\*\*/g, '');
      const body = content.slice(m[0].length).replace(/^[\s:：\-]+/, '');
      return `<div class="callout callout-${type}"><div class="callout-title">${icon} ${title}</div>${body}</div>`;
    }
  }
  return '<blockquote>' + content + '</blockquote>';
})
```

**핵심 설계 결정:**
- 패턴 매칭 실패 시 기존 `<blockquote>` 그대로 유지 (하위 호환)
- 이모지와 볼드 키워드 양쪽 모두 매칭 (LLM 출력 변동성 대응)
- `callout-title`에 아이콘과 키워드를 표시하고, 나머지는 본문으로

**다중 행 콜아웃 처리:**

기존 `md()` 함수의 blockquote 변환은 **단일 행 매칭** (`^> (.+)$`)이므로, 연속된 `>` 줄은 각각 별도 `<blockquote>`가 됨. 이를 해결하기 위해 blockquote를 inline 변환이 아닌 **블록 단위 stash**로 승격:

**위치**: line 468~471 (ol stash) 바로 뒤, inline transforms 이전에 추가:

```js
// 연속 blockquote 블록 처리 (콜아웃 변환 포함)
text = text.replace(/((?:^> .+$\n?)+)/gm, block => {
  const lines = block.trim().split('\n').map(l => l.replace(/^> ?/, ''));
  const joined = lines.join('\n');

  const calloutMap = [
    { pattern: /^(?:📘\s*)?(?:\*\*)?(?:법적\s*근거|관련\s*법조문|관련\s*법률|법령)(?:\*\*)?/i, type: 'legal', icon: '📘' },
    { pattern: /^(?:⚠️\s*)?(?:\*\*)?(?:주의사항|주의|유의|예외)(?:\*\*)?/i, type: 'warn', icon: '⚠️' },
    { pattern: /^(?:🚨\s*)?(?:\*\*)?(?:중요|필수|경고|금지)(?:\*\*)?/i, type: 'danger', icon: '🚨' },
    { pattern: /^(?:💡\s*)?(?:\*\*)?(?:참고|팁|알아두세요|도움말|안내)(?:\*\*)?/i, type: 'tip', icon: '💡' },
  ];

  for (const { pattern, type, icon } of calloutMap) {
    const m = joined.match(pattern);
    if (m) {
      const title = m[0].replace(/\*\*/g, '');
      const body = joined.slice(m[0].length).replace(/^[\s:：\-]+/, '').replace(/\n/g, '<br>');
      return stash('<div class="callout callout-' + type + '"><div class="callout-title">' + icon + ' ' + title + '</div>' + body + '</div>');
    }
  }

  // 매칭 안 되면 기본 blockquote
  return stash('<blockquote>' + joined.replace(/\n/g, '<br>') + '</blockquote>');
});
```

이후 line 481의 기존 `^> (.+)` 변환은 **제거** (블록 stash에서 이미 처리).

### 3.3 요약 배지 변환

**위치**: line 476 (heading 변환) 교체

기존:
```js
.replace(/^## (.+)$/gm, '<h2>$1</h2>')
```

교체:
```js
.replace(/^## (.+)$/gm, (_, title) => {
  if (/^(?:⚖️\s*|📋\s*)?(?:핵심\s*답변|결론|답변\s*요약|요약)/.test(title)) {
    return '<div class="summary-badge"><h2>' + title + '</h2></div>';
  }
  return '<h2>' + title + '</h2>';
})
```

**주의**: `summary-badge`의 `<div>` 시작은 이후 paragraph wrapping에서 깨질 수 있으므로 stash 처리 필요. 실제로는 heading이 paragraph 내부에 들어가지 않으므로 안전함 (line 485의 `\n\n+` split이 heading 전후에 paragraph를 분리).

### 3.4 향상된 테이블 로직

**위치**: line 449~462 (table stash) 교체

```js
text = text.replace(/((?:^\|.+\|[ \t]*$\n?)+)/gm, block => {
  const rows = block.trim().split('\n');
  let html = '<table>';
  let headerDone = false;
  for (const row of rows) {
    if (/^\|[\s:|-]+\|$/.test(row.trim())) { headerDone = true; continue; }
    const cells = row.replace(/^\||\|$/g, '').split('|').map(c => c.trim());
    const tag = !headerDone ? 'th' : 'td';

    // 합계 행 감지
    const isTotal = cells.some(c => /^(?:합\s*계|총\s*계|소\s*계|total|sum)/i.test(c));
    const trClass = isTotal ? ' class="total-row"' : '';

    html += '<tr' + trClass + '>';
    for (const c of cells) {
      // 금액 셀 감지 (숫자+원 또는 숫자+콤마 패턴)
      const isNum = /^[\d,]+(?:\.\d+)?(?:\s*원)?$/.test(c.replace(/\*\*/g, '').trim());
      const cellClass = (tag === 'td' && isNum) ? ' class="num-cell"' : '';
      html += '<' + tag + cellClass + '>' + c + '</' + tag + '>';
    }
    html += '</tr>';
    if (!headerDone) headerDone = true;
  }
  html += '</table>';
  return stash(html);
});
```

**핵심 변경:**
- `합계`/`총계`/`소계` 키워드가 포함된 행 → `.total-row` 클래스
- `숫자,숫자원` 패턴의 셀 → `.num-cell` 클래스 (우측 정렬, tabular-nums)

### 3.5 스텝 인디케이터 변환

**위치**: line 468~471 (ol stash) 교체

```js
text = text.replace(/((?:^[ \t]*\d+\. .+$\n?)+)/gm, (block, _, offset) => {
  // 스텝 인디케이터 트리거: 직전 heading이 절차/방법/순서 관련인지 체크
  // 간단한 휴리스틱: 블록 직전 텍스트에서 heading 패턴 감지
  const preceding = text.slice(Math.max(0, offset - 200), offset);
  const isStepContext = /(?:절차|방법|순서|과정|단계|대응|신청|진행)\s*$/m.test(preceding)
    || /^#{2,3}\s.*(?:절차|방법|순서|과정|단계|대응|신청|진행)/m.test(preceding);

  const items = block.trim().split('\n').map(l => '<li>' + l.replace(/^[ \t]*\d+\. /, '') + '</li>');

  if (isStepContext) {
    return stash('<ol class="step-list">' + items.join('') + '</ol>');
  }
  return stash('<ol>' + items.join('') + '</ol>');
});
```

**설계 결정:** 모든 ol을 스텝 인디케이터로 변환하면 일반 번호 목록까지 영향을 받으므로, **직전 heading 문맥**을 체크하여 절차/방법/순서 관련일 때만 적용.

### 3.6 면책 고지 후처리

**위치**: line 489 (return html 직전) 추가

```js
// 면책 고지 감지 및 스타일링
html = html.replace(
  /(<p>(?:⚠️\s*)?본\s*(?:답변|계산\s*결과|판정\s*결과)은?\s*참고용[\s\S]*?<\/p>)$/,
  '<div class="disclaimer-notice">$1</div>'
);
```

---

## 4. 시스템 프롬프트 변경 설계

### 4.1 COMPOSER_SYSTEM 변경

**위치**: `app/templates/prompts.py` line 236~241

기존:
```python
- **시각화 규칙** (가독성 극대화):
  `##` 소제목으로 섹션 구분. 금액·비교 데이터는 표 사용.
  핵심 결론·금액은 **볼드**. 법조문 원문·판례 요지는 `>` 인용문.
  절차·조건은 번호 목록. 섹션 사이 `---` 구분선.
  핵심 결론 1~2문장 먼저, 그 후 상세 설명.
```

교체:
```python
- **시각화 규칙** (학습자료 수준 — 반드시 준수):
  - **핵심 답변**: 첫 섹션은 `## ⚖️ 핵심 답변`으로 시작하고 결론 1~2문장 작성
  - **법적 근거**: 법조문·판례는 `> 📘 **법적 근거**: 근로기준법 제N조...` 형식
  - **주의사항**: 예외·제외·주의는 `> ⚠️ **주의사항**: ...` 형식
  - **중요 경고**: 위반 시 불이익 등은 `> 🚨 **중요**: ...` 형식
  - **참고/팁**: 실무 팁·추가 안내는 `> 💡 **참고**: ...` 형식
  - **표**: 금액·비교 데이터는 반드시 표. 합계 행에 "합계" 명시
  - **절차**: 신청 절차·대응 방법은 `## 절차` 또는 `## 신청 방법` heading 아래 번호 목록
  - **구분선**: 주요 섹션 사이 `---`
  - **면책**: 마지막에 "⚠️ 본 답변은 참고용이며 법적 효력이 없습니다."
```

### 4.2 CONSULTATION_SYSTEM_PROMPT 변경

**위치**: `app/templates/prompts.py` line 288~296

기존 `7. **답변 시각화 규칙**` 블록을 위와 **동일한 내용**으로 교체.

단, `CONSULTATION_SYSTEM_PROMPT`에서는 `## 핵심 답변` 대신 구조에 맞게:
```python
  - **핵심 답변**: `## ⚖️ 핵심 답변`으로 시작 (1~2문장 요약)
  - **법적 근거**: `> 📘 **법적 근거**: 근로기준법 제N조...` (법조문 원문 인용)
  - **판례 인용**: `> 📘 **관련 판례**: 대법원 YYYY다NNNNN...` (판례 요지)
  - **주의사항**: `> ⚠️ **주의사항**: ...` (적용 예외, 조건)
  - **중요 경고**: `> 🚨 **중요**: ...` (필수 확인, 기한 주의)
  - **참고/팁**: `> 💡 **참고**: ...` (실무 조언, 기관 안내)
  - **표**: 비교 데이터·요건 충족 여부는 표. 합계 행에 "합계" 명시
  - **절차**: `## 절차` 또는 `## 신청 방법` heading 아래 번호 목록
  - **구분선**: `---`
  - **면책**: "⚠️ 본 답변은 참고용이며 법적 효력이 없습니다."
```

---

## 5. 컴포넌트 렌더링 예시

### 5.1 콜아웃 박스 — LLM 출력 → HTML

**LLM 출력 (markdown):**
```
> 📘 **법적 근거**: 근로기준법 제56조에 따르면 사용자는 연장근로에 대해
> 통상임금의 50% 이상을 가산하여 지급해야 합니다.
```

**md() 변환 결과 (HTML):**
```html
<div class="callout callout-legal">
  <div class="callout-title">📘 법적 근거</div>
  근로기준법 제56조에 따르면 사용자는 연장근로에 대해<br>통상임금의 50% 이상을 가산하여 지급해야 합니다.
</div>
```

**렌더링 결과:**
```
┌ 📘 법적 근거 ─────────────────────────────┐
│ 근로기준법 제56조에 따르면 사용자는         │
│ 연장근로에 대해 통상임금의 50% 이상을       │
│ 가산하여 지급해야 합니다.                   │
└─────────────────────────── (파란 배경+보더) ┘
```

### 5.2 요약 배지 — 핵심 답변

**LLM 출력:**
```
## ⚖️ 핵심 답변

주 5일 근무, 일 8시간 기준으로 월 예상 실수령액은 **약 2,150,000원**입니다.
```

**HTML:**
```html
<div class="summary-badge">
  <h2>⚖️ 핵심 답변</h2>
</div>
<p>주 5일 근무, 일 8시간 기준으로 월 예상 실수령액은 <strong>약 2,150,000원</strong>입니다.</p>
```

### 5.3 향상된 테이블

**LLM 출력:**
```
| 항목 | 금액 |
|------|------|
| 기본급 | 2,000,000원 |
| 연장수당 | 150,000원 |
| 합계 | 2,150,000원 |
```

**HTML:**
```html
<table>
  <tr><th>항목</th><th>금액</th></tr>
  <tr><td>기본급</td><td class="num-cell">2,000,000원</td></tr>
  <tr><td>연장수당</td><td class="num-cell">150,000원</td></tr>
  <tr class="total-row"><td>합계</td><td class="num-cell">2,150,000원</td></tr>
</table>
```

### 5.4 스텝 인디케이터

**LLM 출력:**
```
## 신청 방법

1. 관할 고용노동부 확인
2. 진정서 작성 (서식 다운로드)
3. 고용노동부 제출 (온라인/방문)
4. 조사 및 시정지시 대기
```

**HTML:**
```html
<h2>신청 방법</h2>
<ol class="step-list">
  <li>관할 고용노동부 확인</li>
  <li>진정서 작성 (서식 다운로드)</li>
  <li>고용노동부 제출 (온라인/방문)</li>
  <li>조사 및 시정지시 대기</li>
</ol>
```

---

## 6. 처리 순서 및 충돌 방지

### 6.1 md() 내 처리 파이프라인 (최종)

```
[Phase 1: 블록 레벨 stash — 순서 중요]
 ① code block stash          (기존 유지)
 ② math stash                (기존 유지)
 ③ table stash               (향상: total-row, num-cell)
 ④ ul stash                  (기존 유지)
 ⑤ ol stash                  (향상: step-list 조건부 적용)
 ⑥ blockquote stash [NEW]    (콜아웃 변환 포함, 연속 > 블록 처리)

[Phase 2: 인라인 변환]
 ⑦ inline code               (기존 유지)
 ⑧ headings                  (향상: summary-badge 조건부 적용)
 ⑨ bold/italic               (기존 유지)
 ⑩ blockquote 단일행         [제거 — ⑥에서 처리]
 ⑪ links                     (기존 유지)
 ⑫ hr                        (기존 유지)

[Phase 3: 후처리]
 ⑬ paragraph wrapping        (기존 유지)
 ⑭ stash 복원                (기존 유지)
 ⑮ 빈 p 제거                 (기존 유지)
 ⑯ 면책 고지 감지 [NEW]
```

### 6.2 충돌 방지 규칙

| 잠재 충돌 | 해결 방법 |
|-----------|-----------|
| 콜아웃 내부에 `**볼드**` | stash 시점에서 이미 raw text → Phase 2에서 bold 변환 안 됨 → stash 전에 bold 처리 필요 → 콜아웃 body에 `.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')` 적용 |
| 콜아웃 내부에 테이블 | 콜아웃은 `> ` 접두사가 있어 테이블 패턴 `|...|`와 충돌 없음 |
| 스텝 인디케이터 내부 볼드 | stash 전에 bold 처리 → `items` 생성 시 bold 변환 포함 |
| 요약 배지 heading 내 이모지 | heading 변환 시 이모지 포함한 전체 텍스트를 h2로 감싸므로 문제 없음 |

### 6.3 콜아웃 내부 인라인 처리

stash 전에 body 텍스트에 인라인 변환 적용:

```js
function inlineTransform(text) {
  return text
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
}
```

콜아웃 및 스텝 인디케이터 stash 시 `body` 및 `items`에 `inlineTransform()` 적용.

---

## 7. 스트리밍 안전성

### 7.1 현재 스트리밍 동작

`readSSE()`에서 `chunk` 이벤트마다 `accum += event.text` → `el.innerHTML = md(accum)` 호출.
즉, **매 청크마다 누적된 전체 텍스트를 다시 md() 변환**.

### 7.2 안전성 보장

- **블록 stash 패턴**: 연속 `> ` 줄이 완성되기 전에는 블록 매칭 안 됨 → 부분 텍스트에서 미완성 콜아웃이 나타나지 않음
- **테이블**: 기존과 동일 — 줄이 완성돼야 `|...|` 패턴 매칭
- **heading**: 줄 단위 매칭이므로 `## `이 나오면 즉시 변환 → 스트리밍 중에도 안전
- **스텝 인디케이터**: preceding context 체크가 누적 텍스트에서 수행되므로 heading이 먼저 도착해야 함 → 자연스러운 순서로 안전

### 7.3 레이아웃 시프트 최소화

- 콜아웃 박스 높이가 스트리밍 중 변동되는 것은 불가피하지만, `margin: 10px 0` 고정으로 급격한 시프트 방지
- `summary-badge`는 첫 heading에만 적용되므로 초반에 한 번 시프트

---

## 8. 구현 순서 (Do Phase 가이드)

```
Step 1: CSS 변수 + 콜아웃 CSS 추가
        → public/index.html :root 변수 + .callout 4종 스타일

Step 2: 향상된 테이블 CSS 교체
        → 기존 table/th/td 스타일 교체 + .total-row, .num-cell 추가

Step 3: 요약 배지 + 구분선 + 면책 고지 + 스텝 인디케이터 CSS 추가
        → .summary-badge, hr, .disclaimer-notice, .step-list

Step 4: 모바일 반응형 CSS 추가
        → @media (max-width: 600px) 블록에 새 컴포넌트 대응

Step 5: inlineTransform() 헬퍼 함수 추가
        → md() 함수 상단에 정의

Step 6: blockquote 블록 stash 추가 (콜아웃 변환)
        → ol stash 뒤, inline transforms 앞에 삽입
        → 기존 line 481 blockquote 변환 제거

Step 7: heading 변환 확장 (요약 배지)
        → ## 변환에 조건 분기 추가

Step 8: table stash 교체 (합계 행, 금액 셀)
        → 기존 table stash 교체

Step 9: ol stash 교체 (스텝 인디케이터)
        → preceding context 체크 로직 추가

Step 10: 면책 고지 후처리 추가
         → return html 직전

Step 11: 시스템 프롬프트 업데이트
         → COMPOSER_SYSTEM, CONSULTATION_SYSTEM_PROMPT 시각화 규칙 교체

Step 12: 통합 테스트
         → 다양한 질문 유형으로 답변 확인 (계산, 법률상담, 괴롭힘)
```

---

## 9. 테스트 시나리오

| 시나리오 | 검증 항목 | 기대 결과 |
|----------|-----------|-----------|
| 연장수당 계산 질문 | 콜아웃(법적 근거), 향상된 테이블(합계 행), 요약 배지 | 파란 콜아웃 + 합계 하이라이트 + 핵심 답변 배지 |
| 부당해고 법률상담 | 콜아웃(법적 근거, 주의사항), 스텝 인디케이터(절차) | 파란/주황 콜아웃 + 원형 번호 스텝 |
| 괴롭힘 판정 | 콜아웃(중요), 요약 배지(핵심 답변) | 빨간 콜아웃 + 핵심 판정 배지 |
| 콜아웃 패턴 없는 일반 blockquote | 기존 스타일 유지 | 회색 왼쪽 보더 blockquote |
| 합계 없는 일반 테이블 | 교대 행 색상만 적용 | zebra striping, 합계 강조 없음 |
| 절차 아닌 일반 ol | 기본 ol 스타일 | 스텝 인디케이터 아닌 일반 번호 목록 |
| 모바일 (320px~600px) | 콜아웃 패딩 축소, 스텝 인디케이터 축소 | 레이아웃 깨짐 없음 |
| 스트리밍 중 부분 텍스트 | 미완성 콜아웃 미표시 | 깨진 HTML 없음 |
| 면책 고지 | 별도 스타일 적용 | 작은 폰트 + muted 색상 |
| `replace` 이벤트 (citation correction) | 전체 재렌더링 | 모든 리치 컴포넌트 정상 표시 |
