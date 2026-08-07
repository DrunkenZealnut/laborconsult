'use strict';

// public/finalize.js 의 판정 로직(접기 대상 화이트리스트·임계값)과 두 페이지의
// 배선을 검증한다. DOM 조작 자체는 jsdom 없이 신뢰성 있게 재현할 수 없으므로
// (CI가 npm 의존성을 설치하지 않는다) 여기서는 다음만 다룬다:
//   1) 순수 판정 로직 — 실제 소스에서 선언을 잘라내 vm 에서 평가
//   2) 배선 — index/board 가 스크립트를 싣고 finalize 를 호출하는지, 생성 요소의
//      CSS 가 양쪽에 정의돼 있는지
// DOM 결과물(목차 삽입·details 래핑) 자체는 Plan §7 의 수동 검증 항목이다.

const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const FINALIZE = fs.readFileSync(path.join(__dirname, 'public', 'finalize.js'), 'utf8');
const INDEX = fs.readFileSync(path.join(__dirname, 'public', 'index.html'), 'utf8');
const BOARD = fs.readFileSync(path.join(__dirname, 'public', 'board.html'), 'utf8');

/** 선언을 시그니처로 찾아 잘라낸다 — 줄 번호가 아니라 시그니처 기준이라
 *  리팩터링으로 위치가 옮겨져도 깨지지 않고, 시그니처가 사라지면 즉시 실패한다.
 *
 *  finalize.js 는 선언이 IIFE 안에 들여쓰기돼 있다. 종료 부호를 `^\s*` 로 찾으면
 *  함수 **내부**의 닫는 중괄호(더 깊은 들여쓰기)를 먼저 잡아 선언이 잘린다.
 *  그래서 선언 자신의 들여쓰기와 정확히 같은 열의 종료 부호만 인정한다. */
function slice(source, startRe, closer) {
  const start = source.match(startRe);
  if (!start) throw new Error(`시작 패턴을 찾지 못함: ${startRe}`);
  const lineStart = source.lastIndexOf('\n', start.index) + 1;
  const indent = source.slice(lineStart, start.index);
  if (/\S/.test(indent)) throw new Error(`선언이 줄 시작이 아님: ${startRe}`);

  const escaped = closer.replace(/[[\]{}]/g, '\\$&');
  const endRe = new RegExp('^' + indent + escaped + '$', 'm');
  const rest = source.slice(start.index);
  const end = rest.match(endRe);
  if (!end) throw new Error(`종료 패턴을 찾지 못함: ${closer} (들여쓰기 ${indent.length}칸)`);
  return rest.slice(0, end.index + end[0].length);
}

function loadDecisionLogic() {
  const parts = [
    slice(FINALIZE, /var ALWAYS_OPEN = \[/, '];'),
    slice(FINALIZE, /var COLLAPSIBLE = \[/, '];'),
    slice(FINALIZE, /function matches\(list, text\) \{/, '}'),
    slice(FINALIZE, /function norm\(s\) \{/, '}'),
  ];
  const ctx = {};
  vm.createContext(ctx);
  vm.runInContext(parts.join('\n\n'), ctx);
  return ctx;
}

function constOf(name) {
  const m = FINALIZE.match(new RegExp('var ' + name + ' = (\\d+);'));
  if (!m) throw new Error(`상수 ${name} 을 찾지 못함`);
  return Number(m[1]);
}

// ── 1. 접기 판정 로직 ────────────────────────────────────────────────────────

test('핵심 답변·결론·주의사항은 절대 접히지 않는다 (P2)', () => {
  const { ALWAYS_OPEN, COLLAPSIBLE, matches } = loadDecisionLogic();

  // 실제 프롬프트가 만들어내는 헤딩 표기들
  const neverCollapse = [
    '⚖️ 핵심 답변', '핵심 답변', '결론', '답변 요약', '요약',
    '주의사항', '주의 사항', '면책 고지',
  ];
  for (const title of neverCollapse) {
    assert.equal(matches(ALWAYS_OPEN, title), true,
      `ALWAYS_OPEN 에 걸리지 않음 — 접힐 위험: ${title}`);
  }

  // ALWAYS_OPEN 이 COLLAPSIBLE 보다 먼저 검사되므로 양쪽에 걸려도 안전하지만,
  // 애초에 겹치지 않는 편이 의도가 분명하다.
  for (const title of ['핵심 답변', '결론', '요약']) {
    assert.equal(matches(COLLAPSIBLE, title), false,
      `핵심 항목이 COLLAPSIBLE 에도 매칭됨: ${title}`);
  }
});

test('부차 상세 섹션은 접기 대상으로 판정된다', () => {
  const { COLLAPSIBLE, ALWAYS_OPEN, matches } = loadDecisionLogic();

  const shouldCollapse = [
    '법적 근거', '법적근거', '관련 법조문', '관련 법률', '법령',
    '관련 판례', '판례', '행정해석',
    '절차', '신청 방법', '대응 방법',
    '산출 근거', '계산 과정', '계산 근거',
  ];
  for (const title of shouldCollapse) {
    assert.equal(matches(COLLAPSIBLE, title), true, `접기 대상 미매칭: ${title}`);
    assert.equal(matches(ALWAYS_OPEN, title), false,
      `접기 대상인데 ALWAYS_OPEN 에도 걸려 영원히 안 접힘: ${title}`);
  }
});

test('무관한 헤딩은 접지 않는다 (화이트리스트 방식)', () => {
  const { COLLAPSIBLE, matches } = loadDecisionLogic();
  for (const title of ['계산 결과', '추가 안내', '참고 자료', '질문', '답변']) {
    assert.equal(matches(COLLAPSIBLE, title), false, `무관한 헤딩이 접힘: ${title}`);
  }
});

test('norm: 공백 정규화로 summary 라벨이 깨지지 않는다', () => {
  const { norm } = loadDecisionLogic();
  assert.equal(norm('  법적   근거\n\n원문  '), '법적 근거 원문');
  assert.equal(norm(''), '');
  assert.equal(norm(null), '');
});

test('임계값이 설계와 일치한다', () => {
  // 목차 2개+: 3개로 잡으면 법률상담 답변(헤딩이 핵심답변+절차 뿐)에서 발동하지 않는다
  assert.equal(constOf('MIN_HEADINGS'), 2);
  // 짧은 섹션까지 접으면 클릭만 늘어난다
  assert.equal(constOf('MIN_COLLAPSE_LEN'), 200);
  assert.equal(constOf('HINT_LEN'), 60);
});

// ── 1-2. 판정 '적용' 검증 ────────────────────────────────────────────────────
// 위 테스트들은 화이트리스트 내용만 본다. 실제로 그 순서·임계값이 적용되는지는
// wrapCollapsible 본문을 봐야 한다(jsdom 없이 가능한 정적 단언 범위).

test('wrapCollapsible 이 ALWAYS_OPEN 을 COLLAPSIBLE 보다 먼저 검사한다', () => {
  const src = slice(FINALIZE, /function wrapCollapsible\(container\) \{/, '}');
  const alwaysAt = src.indexOf('ALWAYS_OPEN');
  const collapseAt = src.indexOf('COLLAPSIBLE');
  assert.ok(alwaysAt > 0 && collapseAt > 0, '두 화이트리스트를 모두 참조하지 않음');
  assert.ok(alwaysAt < collapseAt,
    'COLLAPSIBLE 을 먼저 검사함 — 오매칭 시 핵심 항목이 접힐 수 있다');
  // 200자 하한이 실제로 적용되는지
  assert.match(src, /MIN_COLLAPSE_LEN/, '길이 하한이 적용되지 않음');
  // 핵심 답변 배지 가드
  assert.match(src, /summary-badge/, '.summary-badge 접기 제외 가드가 없음');
});

test('collectSectionNodes 가 heading 아닌 종료 마커도 끊는다 (G1)', () => {
  // 프롬프트가 주의사항을 블록쿼트로, 면책을 평문으로 지시하므로 heading 방어만으로는
  // 마지막 접기 섹션이 이들을 통째로 삼킨다.
  const src = slice(FINALIZE, /function collectSectionNodes\(h\) \{/, '}');
  assert.match(src, /isTerminator\(n\)/,
    'collectSectionNodes 가 종료 마커를 검사하지 않음 — 면책 고지가 접힌다');

  const term = slice(FINALIZE, /function isTerminator\(n\) \{/, '}');
  assert.match(term, /HR/, '구분선(<hr>) 종료 조건 없음');
  assert.match(term, /disclaimer-notice/, '면책 고지 클래스 종료 조건 없음');
  assert.match(term, /법적\\s\*효력이/, '면책 문구 종료 조건 없음');
  assert.match(term, /주의\\s\*사항/, '주의사항 종료 조건 없음');
});

test('목차 id 가 답변마다 유일하다 (G2)', () => {
  // 채팅은 후속 답변이 누적된다. 인덱스만 쓰면 답변마다 0부터 재시작해
  // document.getElementById 가 항상 첫 답변을 잡는다.
  assert.match(FINALIZE, /var answerSeq = 0;/, '답변 시퀀스 카운터가 없음');
  assert.match(FINALIZE, /buildOutline\(el, ['"]ans-h2-['"] \+ \(answerSeq\+\+\)/,
    'finalize 가 답변별 id 접두사를 넘기지 않음');

  const outline = slice(FINALIZE, /function buildOutline\(container, idPrefix\) \{/, '}');
  assert.match(outline, /var id = idPrefix \+ i;/,
    'buildOutline 이 접두사를 쓰지 않고 인덱스만으로 id 를 만든다');
});

// ── 2. 페이지 배선 ───────────────────────────────────────────────────────────

test('두 페이지가 finalize.js 를 싣고 finalize 를 호출한다', () => {
  for (const [name, src] of [['index.html', INDEX], ['board.html', BOARD]]) {
    assert.match(src, /<script src="\/finalize\.js"><\/script>/,
      `${name} 이 finalize.js 를 싣지 않음`);
    assert.match(src, /window\.answerGlance\.finalize\(/,
      `${name} 이 finalize 를 호출하지 않음`);
    // 로드 실패해도 페이지가 죽지 않아야 한다
    assert.match(src, /if \(window\.answerGlance\)/,
      `${name} 의 finalize 호출에 존재 가드가 없음`);
  }
});

test('finalize 는 답변 확정 후에만 호출된다 (FR-4)', () => {
  // 스트리밍 중 호출되면 미완성 heading 으로 목차가 어긋난다.
  // showAnswerActions(최종 후처리) 뒤에 있어야 한다.
  const actionsAt = INDEX.indexOf('showAnswerActions(lastAssistant)');
  const finalizeAt = INDEX.indexOf('window.answerGlance.finalize(lastAssistant)');
  assert.ok(actionsAt > 0, 'showAnswerActions 호출을 찾지 못함');
  assert.ok(finalizeAt > actionsAt,
    'finalize 가 스트리밍 완료 지점(showAnswerActions) 이후에 있지 않음');

  // chunk 이벤트 처리부에서 호출되면 안 된다
  const chunkBlock = INDEX.slice(
    INDEX.indexOf("event.type === 'chunk'"),
    INDEX.indexOf('if (streamDone) break;', INDEX.indexOf("event.type === 'chunk'"))
  );
  assert.ok(!chunkBlock.includes('answerGlance'),
    'chunk 처리부에서 finalize 를 호출함 — 스트리밍 중 적용됨');
});

test('생성 요소의 CSS 가 양쪽 페이지에 정의돼 있다', () => {
  // finalize.js 가 만드는 클래스들. 한쪽에만 있으면 그 페이지에서 스타일이 깨진다.
  for (const [name, src] of [['index.html', INDEX], ['board.html', BOARD]]) {
    assert.match(src, /\.answer-outline\s*\{/, `${name} 에 .answer-outline CSS 없음`);
    assert.match(src, /\.outline-chip\s*\{/, `${name} 에 .outline-chip CSS 없음`);
    assert.match(src, /#glance-jump-core\s*\{/, `${name} 에 #glance-jump-core CSS 없음`);
    assert.match(src, /details > summary\s*\{/, `${name} 에 details/summary CSS 없음`);
    // 접기 토글 터치 타겟 ≥ 44px (Plan NFR)
    assert.match(src, /details > summary \{[^}]*min-height: 44px/,
      `${name} 의 summary 터치 타겟이 44px 미만`);
  }
});

test('공개 페이지 HTML 주석이 내부 경로·함수명을 노출하지 않는다', () => {
  // CLAUDE.md 규약 — 소스 보기로 그대로 공개된다. 유지보수 의존관계는 CLAUDE.md에 적는다.
  const leaky = /\.(?:js|py|html|json|sql)\b|::|function\s+\w+|\w+\(\)/;
  for (const [name, src] of [['index.html', INDEX], ['board.html', BOARD]]) {
    const comments = src.match(/<!--[\s\S]*?-->/g) || [];
    for (const c of comments) {
      if (c.startsWith('<!--[if') || c.includes('═══')) continue;  // 조건부 주석·섹션 구분선
      assert.ok(!leaky.test(c),
        `${name} 의 HTML 주석에 내부 경로/함수명 노출:\n${c.trim().slice(0, 160)}`);
    }
  }
});

test('내보내기 경로가 접힌 섹션을 강제로 편다 (D7)', () => {
  // 접힌 채 PDF/이메일로 나가면 내용이 빠진 것처럼 보인다.
  assert.match(INDEX, /window\.answerGlance\.expandForExport\(a\.innerHTML\)/,
    'getQAPair 가 내보내기용 펼침 처리를 거치지 않음');
  // 복사·마크다운 저장은 원문(dataset.md)을 쓰므로 이 처리와 무관해야 한다
  assert.match(INDEX, /const aMd = a\.dataset\.md/,
    '마크다운 경로가 원문 대신 렌더 결과를 씀');
});

// ── 3. finalize.js 자체 계약 ─────────────────────────────────────────────────

test('finalize.js 는 전역을 하나만 노출한다', () => {
  const ctx = { window: {}, console: { warn() {} } };
  ctx.global = ctx;
  vm.createContext(ctx);
  vm.runInContext(FINALIZE, ctx);
  assert.deepEqual(Object.keys(ctx.window), ['answerGlance']);
  assert.equal(typeof ctx.window.answerGlance.finalize, 'function');
  assert.equal(typeof ctx.window.answerGlance.expandForExport, 'function');
});

test('expandForExport 는 잘못된 입력에 원본을 그대로 돌려준다', () => {
  // document 가 없는 컨텍스트 = DOM 접근 실패. 답변 내보내기가 죽으면 안 된다.
  const ctx = { window: {}, console: { warn() {} } };
  vm.createContext(ctx);
  vm.runInContext(FINALIZE, ctx);
  const html = '<p>원본</p>';
  assert.equal(ctx.window.answerGlance.expandForExport(html), html);
});

test('finalize 는 DOM 접근 실패 시에도 예외를 던지지 않는다', () => {
  // 조망 레이어 실패가 답변 표시를 막으면 안 된다(전 계층 graceful degradation).
  const ctx = { window: {}, console: { warn() {} } };
  vm.createContext(ctx);
  vm.runInContext(FINALIZE, ctx);
  assert.doesNotThrow(() => ctx.window.answerGlance.finalize(null));
  assert.doesNotThrow(() => ctx.window.answerGlance.finalize({ dataset: {} }));
});
