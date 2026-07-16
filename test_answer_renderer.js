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
