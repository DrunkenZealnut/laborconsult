# 답변 렌더러 회귀 테스트 하네스 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `answer-ui-readability` Design §6.1의 회귀 하네스(T1~T8)를 저장소에 커밋된 Node 테스트로 정식화하고 기존 오프라인 CI 스위트(`tests.yml`)에 연동해, `public/index.html`의 `md()` 렌더러가 이후 변경돼도 회귀를 자동으로 차단한다.

**Architecture:** `public/index.html`은 별도 빌드 없는 단일 HTML 파일이라 `md()`와 그 헬퍼가 인라인 `<script>`에 정의돼 있어 `require()`로 직접 가져올 수 없다. 테스트 파일이 소스 텍스트에서 필요한 함수/상수 선언을 **줄 번호가 아닌 이름 시그니처**로 찾아 잘라낸 뒤 Node `vm` 컨텍스트에서 평가해 재사용한다. `katex`는 컨텍스트에 아예 선언하지 않아 `renderTex()`의 기존 "KaTeX 없음" 폴백 분기(`typeof katex === 'undefined'`)가 그대로 스텁 역할을 한다.

**Tech Stack:** Node.js 내장 `node:test` + `node:assert/strict` + `node:vm`(외부 패키지 설치 없음, `package.json` 신설 없음). CI는 `actions/setup-node@v4`.

---

## Scope Check

단일 파일(`test_answer_renderer.js`) 신설 + 기존 CI 워크플로 1개 수정. 독립된 서브시스템으로 나눌 필요 없이 단일 플랜으로 충분.

## 배경 (왜 지금 필요한가)

`docs/archive/2026-07/answer-ui-readability/`의 Design §6.1은 Do 완료 후 재검증에 쓴 "하네스 회귀(Node, 스크래치 도구 — 저장소 미커밋)"를 정의한다(T1~T8, 29건 어서션). Report §6 "다음 단계" 4번 항목이 CodeRabbit PR #27 리뷰를 인용해 이 하네스를 저장소 테스트로 커밋하고 CI에 연동할 것을 제안했으나, 우선순위·일정 미정으로 별도 작업으로 분리돼 있었다. 이 플랜이 그 분리된 작업을 구현한다.

## File Structure

- **Create:** `test_answer_renderer.js` (저장소 루트 — 기존 `test_*.py` 전부가 루트에 flat하게 있는 관례와 동일한 위치)
- **Modify:** `.github/workflows/tests.yml` — Node 셋업 스텝 + 실행 스텝 추가
- **변경 없음:** `public/index.html` — 아래 설계 결정 참고

### 설계 결정: 하드코딩 줄 번호 대신 "선언 이름 → 매칭되는 닫는 줄" 추출

기존 스크래치 하네스는 Design 문서에 `md()` **968~1080행** 추출로 기록돼 있다(§1.1, Design 검증 시점 = Wave A/B/C 구현 **이전** 코드 기준). 지금 구현이 끝난 코드에서 `md()`는 이미 **1020~1138행**으로 이동했다 — 같은 PDCA 사이클 안에서도 줄 번호가 깨진 실증 사례다. 두 가지 대안을 검토했다:

| 방식 | 설명 | 장단점 |
|------|------|--------|
| A. 마커 주석 | `public/index.html`에 `// test-extract:start` ~ `end` 주석을 추가하고 그 사이를 잘라냄 | 코드 이동에 강하지만 프로덕션 파일에 테스트 전용 흔적이 남고, 마커가 실수로 삭제/이동되면 조용히 깨질 위험이 있음 |
| **B. 이름 시그니처 매칭 (채택)** | `function md(text) {` 같은 선언 시작 패턴을 찾고, 그 뒤 들여쓰기 없는(칼럼 0) 첫 `}`(또는 `];`) 줄까지 잘라냄 | `public/index.html` 무변경. 줄 번호 무관. 패턴을 못 찾으면 즉시 `Error`를 던짐(조용히 통과하지 않음) |

**B를 채택.** 프로덕션 파일을 건드리지 않고, 실패 시 어떤 선언을 못 찾았는지 에러 메시지로 즉시 드러난다. `function md(text) {` → `function mdRenamed(text) {`로 바꿔 시뮬레이션한 결과 `extractDeclaration: 시작 패턴을 찾지 못함 — /^function md\(text\) \{/m`로 즉시 실패하는 것을 로컬에서 확인했다(검증만 하고 커밋되지 않는 임시 변경으로 테스트).

**주의(향후 유지보수자에게):** 이 방식은 `md()`와 헬퍼들이 계속 칼럼 0에서 여닫히는 최상위 `function`/`const` 선언으로 유지된다는 전제에 의존한다. 이 함수들을 다른 함수 안에 중첩하거나 클래스 메서드로 옮기면 추출이 실패한다 — 단 "조용한 통과"가 아니라 CI에서 즉시 에러로 드러나므로, 그 시점에 `test_answer_renderer.js`의 `extractDeclaration` 호출부 패턴을 새 위치에 맞게 수정하면 된다.

---

## Task 1: 답변 렌더러 회귀 테스트 파일 신설

**Files:**
- Create: `test_answer_renderer.js`

이 테스트는 이미 구현된 `public/index.html`의 기존 동작(버그 아님)에 대한 회귀 테스트이므로, "실패하는 테스트 먼저" 단계는 적용하지 않는다 — 대신 전체 파일을 작성한 뒤 실제 소스에 대해 실행해 8/8 통과를 확인하는 순서로 진행한다. 아래 코드는 사전에 저장소의 실제 `public/index.html`을 대상으로 `node --test`를 직접 실행해 8/8 통과를 확인한 내용이다.

- [x] **Step 1: `test_answer_renderer.js` 작성**

```javascript
'use strict';

// public/index.html은 별도 빌드 없이 <script> 인라인으로 렌더러(md 등)를 정의하는
// 단일 HTML 파일이라 require()로 직접 불러올 수 없다. 이 파일은 소스에서 필요한
// 함수/상수 선언만 "이름 시그니처"로 찾아 잘라낸 뒤 vm 컨텍스트에서 평가해 재사용한다.
// 줄 번호가 아니라 선언 시그니처로 찾으므로 index.html 리팩터링으로 위치가 옮겨져도
// 깨지지 않고, 시그니처 자체가 사라지면 조용히 통과하는 대신 즉시 에러로 실패한다.

const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const INDEX_HTML_PATH = path.join(__dirname, 'public', 'index.html');

function extractDeclaration(source, startPattern, endMarker) {
  const startMatch = source.match(startPattern);
  if (!startMatch) {
    throw new Error(`extractDeclaration: 시작 패턴을 찾지 못함 — ${startPattern}`);
  }
  const rest = source.slice(startMatch.index);
  const endLineRe = new RegExp(`^${endMarker}$`, 'm');
  const endMatch = rest.match(endLineRe);
  if (!endMatch) {
    throw new Error(`extractDeclaration: 닫는 패턴(${endMarker})을 찾지 못함 — 시작 패턴: ${startPattern}`);
  }
  return rest.slice(0, endMatch.index + endMatch[0].length);
}

function loadRenderer() {
  const source = fs.readFileSync(INDEX_HTML_PATH, 'utf8');
  const parts = [
    extractDeclaration(source, /^function renderTex\(tex, displayMode\) \{/m, '\\}'),
    extractDeclaration(source, /^function renderMdLink\(txt, url\) \{/m, '\\}'),
    extractDeclaration(source, /^function inlineTransform\(t\) \{/m, '\\}'),
    extractDeclaration(source, /^function indentWidth\(s\) \{/m, '\\}'),
    extractDeclaration(source, /^function buildNestedUl\(items\) \{/m, '\\}'),
    extractDeclaration(source, /^const CALLOUT_MAP = \[/m, '\\];'),
    extractDeclaration(source, /^function md\(text\) \{/m, '\\}'),
  ];
  const code = parts.join('\n\n') +
    '\n\nmodule.exports = { md, renderTex, renderMdLink, inlineTransform, indentWidth, buildNestedUl, CALLOUT_MAP };';
  // katex는 vm 컨텍스트에 선언하지 않는다 — renderTex는 `typeof katex === 'undefined'`로
  // 분기하므로 미선언 상태 자체가 곧 "KaTeX 없음" 스텁 역할을 한다.
  const sandbox = { module: { exports: {} } };
  sandbox.exports = sandbox.module.exports;
  vm.createContext(sandbox);
  new vm.Script(code, { filename: 'extracted-renderer.vm.js' }).runInContext(sandbox);
  return sandbox.module.exports;
}

const { md } = loadRenderer();

test('T1: 표 뒤 문단에 잔여 br 없음 (C4)', () => {
  const html = md('| 항목 | 금액 |\n|---|---|\n| 기본급 | 2,000,000원 |\n이상입니다.');
  assert.equal(
    html,
    '<div class="table-wrap"><table><tr><th>항목</th><th>금액</th></tr><tr><td>기본급</td><td class="num-cell">2,000,000원</td></tr></table></div><p>이상입니다.</p>'
  );
});

test('T2: 중첩 불릿 구조 보존 (C1)', () => {
  const html = md('- 상위 항목 1\n  - 하위 항목 1-1\n  - 하위 항목 1-2\n- 상위 항목 2');
  assert.equal(
    html,
    '<ul><li>상위 항목 1<ul><li>하위 항목 1-1</li><li>하위 항목 1-2</li></ul></li><li>상위 항목 2</li></ul>'
  );
});

test('T3: 번호+하위불릿 — 병합/소실 없음 (C2)', () => {
  const html = md('1. 첫 번째 항목\n   - 하위 불릿 A\n   - 하위 불릿 B\n2. 두 번째 항목\n3. 세 번째 항목');
  assert.equal(
    html,
    '<ol><li>첫 번째 항목<ul><li>하위 불릿 A</li><li>하위 불릿 B</li></ul></li><li>두 번째 항목</li><li>세 번째 항목</li></ol>'
  );
  assert.ok(!html.includes('\x00'), 'stash placeholder 바이트가 남아있으면 안 됨');
});

test('T4: continuation 병합 유지 (C3)', () => {
  const html = md('1. 연장근로수당\n→ 시급 × 1.5 × 연장시간\n2. 다음 항목');
  assert.equal(html, '<ol><li>연장근로수당<br>→ 시급 × 1.5 × 연장시간</li><li>다음 항목</li></ol>');
});

test('T5: 번호 사이 표 — 소실 없음 (C5)', () => {
  const html = md('1. 첫 항목\n| 항목 | 금액 |\n|---|---|\n| 기본급 | 2,000,000원 |\n2. 두 번째 항목');
  assert.ok(!html.includes('\x00'), 'stash placeholder 바이트가 남아있으면 안 됨');
  assert.match(html, /<div class="table-wrap"><table>/, '표 HTML이 실제로 존재해야 함');
  assert.equal((html.match(/<li>/g) || []).length, 2, '<ol> 항목 수는 2여야 함');
});

test('T6: 절차 키워드 → step-list 판별 유지', () => {
  const html = md('## 이의제기 절차\n1. 신청서 작성\n2. 관할 기관 제출\n3. 결과 통보 대기');
  assert.equal(
    html,
    '<p><h2>이의제기 절차</h2><br></p><ol class="step-list"><li>신청서 작성</li><li>관할 기관 제출</li><li>결과 통보 대기</li></ol>'
  );
});

test('T7: 3단계 이상 들여쓰기 — level 2 캡', () => {
  const html = md('- 레벨0\n  - 레벨1\n    - 레벨2\n      - 레벨3');
  assert.equal(
    html,
    '<ul><li>레벨0<ul><li>레벨1<ul><li>레벨2</li><li>레벨3</li></ul></li></ul></li></ul>'
  );
  assert.equal((html.match(/<ul>/g) || []).length, 3, '4단계 중첩 ul이 새로 생기면 안 됨(level 2 캡)');
});

test('T8: 리치 컴포넌트 무회귀 (콜아웃/요약배지/총계행/num-cell/수식/링크)', () => {
  const html = md(
    '## 핵심 답변\n결론입니다.\n\n> 주의: 이 계산은 예시입니다.\n\n' +
    '| 항목 | 금액 |\n|---|---|\n| 기본급 | 2,000,000원 |\n| 합계 | 2,000,000원 |\n\n' +
    '시급은 $10000$ 원입니다.\n\n자세한 내용은 [고용노동부](https://www.moel.go.kr)에서 확인하세요.'
  );
  assert.match(html, /<div class="summary-badge"><h2>핵심 답변<\/h2><\/div>/, '요약배지 무회귀');
  assert.match(html, /<div class="callout callout-warn">/, '콜아웃 무회귀');
  assert.match(html, /<tr class="total-row">/, '합계행 무회귀');
  assert.match(html, /<td class="num-cell">2,000,000원<\/td>/, 'num-cell 무회귀');
  assert.match(html, /data-tex="10000"/, '수식(katex 부재 스텁 경로) 무회귀');
  assert.match(
    html,
    /<a href="https:\/\/www\.moel\.go\.kr" target="_blank" rel="noopener noreferrer">고용노동부<\/a>/,
    '링크 무회귀'
  );
});
```

- [x] **Step 2: 실행해 8/8 통과 확인**

Run: `node --test test_answer_renderer.js`
Expected: 마지막 요약에 `# pass 8` / `# fail 0`, 프로세스 종료 코드 `0`.

- [x] **Step 3: 커밋**

```bash
git add test_answer_renderer.js
git commit -m "test: 답변 렌더러(md()) 회귀 테스트 추가 — Design §6.1 T1~T8"
```

---

## Task 2: CI에 Node 테스트 스텝 연동

**Files:**
- Modify: `.github/workflows/tests.yml:1-29`

현재 `tests.yml`은 Python(`actions/setup-python@v5`)만 셋업하고 Python 테스트 3개만 순차 실행한다. 같은 `offline-tests` job에 Node 셋업과 새 테스트 실행 스텝을 추가한다(새 job을 만들지 않음 — 기존 오프라인 스위트의 일부로 취급).

- [x] **Step 1: `.github/workflows/tests.yml`을 아래 내용으로 교체**

```yaml
name: Offline Tests

# API 키 없이 도는 오프라인 스위트 — 계산 엔진 골든 + 파이프라인 배선 + 검색/인용 단위 + 답변 렌더러 회귀
on:
  push:
    branches: [main]
  pull_request:

jobs:
  offline-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - uses: actions/setup-node@v4
        with:
          node-version: "22"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: 계산 엔진 골든 테스트
        run: python3 test_wage_golden.py

      - name: 파이프라인 배선 테스트
        run: python3 test_pipeline_wiring.py

      - name: 검색·인용 모듈 단위 테스트
        run: python3 test_offline_units.py

      - name: 답변 렌더러 회귀 테스트
        run: node --test test_answer_renderer.js
```

- [x] **Step 2: 로컬에서 CI가 실행할 커맨드와 동일하게 재확인**

Run: `node --test test_answer_renderer.js`
Expected: PASS (Task 1 Step 2와 동일 — `tests.yml`에 적은 커맨드와 로컬에서 검증한 커맨드가 문자 그대로 일치하는지만 재확인하는 용도)

Note: `actions/setup-node`·`actions/checkout` 등 GitHub Actions 실행 자체는 로컬에서 완전히 재현할 수 없다(로컬에 `act` 등의 러너가 없음). YAML 들여쓰기는 기존 스텝과 동일한 2-space 스타일을 그대로 따랐으므로 문법 오류 위험은 낮지만, 최종 확인은 push 후 GitHub Actions 탭에서 워크플로가 실제로 성공하는지 보는 것으로 한다.

- [x] **Step 3: 커밋**

```bash
git add .github/workflows/tests.yml
git commit -m "ci: 답변 렌더러 회귀 테스트를 오프라인 스위트에 연동"
```

---

## Self-Review 메모

- **Spec coverage**: 사용자 요청 3항목 — (1) 정식 테스트 파일 작성+커밋 → Task 1, (2) tests.yml에 Node 스텝 추가 → Task 2, (3) 하드코딩 줄 번호 문제 해결 → "설계 결정" 절에서 이름 시그니처 매칭 채택 + 실패 시나리오 검증. 3항목 모두 태스크/절로 매핑됨.
- **Placeholder 스캔**: 코드 블록은 전부 저장소의 실제 `public/index.html`에 대해 `node --test`로 사전 실행해 통과를 확인한 완성 코드 — TODO/추정치 없음.
- **범위 제한**: `docs/archive/2026-07/answer-ui-readability/answer-ui-readability.report.md`의 "다음 단계 4번" 항목은 이미 uncommitted 변경사항이 있어(집계 수치 정정) 이 플랜에서는 건드리지 않음 — Task 1·2 커밋 후 별도로 체크 처리할지는 사용자 판단.

---

## Execution Handoff

**Two execution options:**

1. **Subagent-Driven (recommended)** — 태스크별로 새 subagent를 띄워 실행 후 리뷰, 빠른 반복
2. **Inline Execution** — 이 세션에서 executing-plans로 배치 실행, 체크포인트마다 확인

**실행 결과 (Inline Execution 채택, 완료):**

| 커밋 | 내용 |
|------|------|
| `82cc6b1` | Task 1 — `test_answer_renderer.js` 신설 (T1~T8) |
| `824c563` | Task 2 — `.github/workflows/tests.yml`에 Node 셋업·실행 스텝 연동 |
| `fca4cb4` | 플랜 외 후속 — T6 검증을 제목·step-list로 분리 (CodeRabbit PR #27 리뷰 반영) |

최종 확인: `node --test test_answer_renderer.js` → `# pass 8 / # fail 0`.
