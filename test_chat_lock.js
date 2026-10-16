'use strict';

// 채팅 이용 제한 잠금(일일 횟수·자동 차단·분당 한도)과 거절 안내 표시의 회귀 테스트.
//
// 2026-10-06 실측: 일일 쿼터에 걸린 뒤에도 거절 문구가 일반 답변 말풍선으로 그려지고(답변 액션 바·
// 복사 버튼까지 붙음) 전송 버튼이 다시 열려, 겉으로는 정상처럼 보였다. 자동 점검 도구는 같은 거절을
// 계속 받으며(51~54번째 요청) 그 문구를 답변으로 수집했다.
//
// public/index.html은 인라인 <script>라 require()로 못 부른다 — test_answer_renderer.js와 같이 선언
// 시그니처로 잘라 vm에서 평가하고(순수 함수), DOM이 필요한 배선은 소스 구조로 고정한다.

const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SOURCE = fs.readFileSync(path.join(__dirname, 'public', 'index.html'), 'utf8');

function extractDeclaration(source, startPattern, endMarker) {
  const startMatch = source.match(startPattern);
  if (!startMatch) throw new Error(`시작 패턴을 찾지 못함 — ${startPattern}`);
  const rest = source.slice(startMatch.index);
  const endMatch = rest.match(new RegExp(`^${endMarker}$`, 'm'));
  if (!endMatch) throw new Error(`닫는 패턴(${endMarker})을 찾지 못함 — ${startPattern}`);
  return rest.slice(0, endMatch.index + endMatch[0].length);
}

function functionBody(name) {
  return extractDeclaration(SOURCE, new RegExp(`^(async )?function ${name}\\(`, 'm'), '\\}');
}

function loadLock() {
  const code = [
    extractDeclaration(SOURCE, /^const LOCKING_CODES = /m, "const LOCKING_CODES = \\['quota', 'blocked', 'rate_limited'\\];"),
    "const LOCK_MAX_MS = 24 * 3600 * 1000;",
    functionBody('guardLockFromEvent'),
    functionBody('isLockActive'),
    functionBody('lockNotice'),
  ].join('\n\n') + '\n\nmodule.exports = { guardLockFromEvent, isLockActive, lockNotice, LOCKING_CODES };';
  const sandbox = { module: { exports: {} } };
  vm.createContext(sandbox);
  new vm.Script(code, { filename: 'extracted-chat-lock.vm.js' }).runInContext(sandbox);
  return sandbox.module.exports;
}

const { guardLockFromEvent, isLockActive, lockNotice } = loadLock();
const NOW = Date.UTC(2026, 9, 6, 12, 0, 0);

test('L1: 일일 쿼터 거절은 retry_after(다음 KST 자정까지) 동안 잠근다', () => {
  const lock = guardLockFromEvent({ type: 'error', code: 'quota', retry_after: 3600, text: '오늘…' }, NOW);
  assert.equal(lock.code, 'quota');
  assert.equal(lock.until, NOW + 3600 * 1000);
  assert.equal(isLockActive(lock, NOW + 3599 * 1000), true);
  assert.equal(isLockActive(lock, NOW + 3600 * 1000), false, '시각이 지나면 풀린다');
  assert.match(lockNotice(lock), /자정/);
});

test('L2: 자동 차단·분당 한도도 잠그고, 풀리는 시각을 안내한다', () => {
  for (const code of ['blocked', 'rate_limited']) {
    const lock = guardLockFromEvent({ code, retry_after: 60 }, NOW);
    assert.equal(lock.until, NOW + 60000, code);
    assert.match(lockNotice(lock), /이후 다시 시도/, code);
  }
});

test('L3: 서버 오류·입력 거절·코드 없는 옛 응답은 잠그지 않는다', () => {
  for (const event of [{ code: 'server_error', retry_after: 60 }, { code: 'invalid', retry_after: 0 },
                       { type: 'error', text: '옛 형식' }, null]) {
    assert.equal(guardLockFromEvent(event, NOW), null, JSON.stringify(event));
  }
});

test('L4: 풀리는 시각을 모르면 잠그지 않고(영구 잠금 방지), 잠금은 최대 24시간', () => {
  assert.equal(guardLockFromEvent({ code: 'quota' }, NOW), null);
  assert.equal(guardLockFromEvent({ code: 'quota', retry_after: 'x' }, NOW), null);
  const capped = guardLockFromEvent({ code: 'quota', retry_after: 10 * 86400 }, NOW);
  assert.equal(capped.until, NOW + 24 * 3600 * 1000);
  assert.equal(isLockActive(null, NOW), false);
  assert.equal(isLockActive({ until: 'soon' }, NOW), false, '저장값이 손상돼도 잠기지 않는다');
});

test('L5: 거절은 답변 말풍선이 아니라 안내 요소로 그린다(답변 액션 바·복사·수집 대상 아님)', () => {
  const readSSE = functionBody('readSSE');
  const errorBranch = readSSE.slice(readSSE.indexOf("event.type === 'error'"), readSSE.indexOf("event.type === 'sources'"));
  assert.ok(errorBranch.includes('addNotice('), '오류는 addNotice로');
  assert.ok(!errorBranch.includes("addMsg('assistant'"), '답변 말풍선으로 그리지 않는다');
  assert.ok(!errorBranch.includes('ensureCopyBtn'), '복사 버튼을 붙이지 않는다');
  assert.ok(errorBranch.includes('guardLockFromEvent(event'), '거절 사유로 잠금 판정');
  assert.ok(/errorEvent \? null/.test(readSSE), '거절만 온 응답에는 이전 답변의 액션 바를 붙이지 않는다');

  const addNotice = functionBody('addNotice');
  assert.ok(addNotice.includes("'msg notice'") && !/assistant/.test(addNotice.split('\n').slice(1).join('\n')),
            '답변 선택자(.msg.assistant)에 걸리지 않는 클래스');
  assert.ok(addNotice.includes('textContent') && !addNotice.includes('innerHTML'), '서버 문구는 평문으로');
  assert.ok(addNotice.includes("'role', 'alert'"), '보조기술·자동화 도구가 안내임을 알 수 있게');
});

test('L6: 전송이 끝나면 잠금 상태대로 버튼을 연다 — 무조건 열지 않는다', () => {
  const doSend = functionBody('doSend');
  const fin = doSend.slice(doSend.lastIndexOf('} finally {'));
  assert.ok(fin.includes('applyChatLock()'), 'finally는 잠금 상태를 적용');
  assert.ok(!/btn\.disabled\s*=\s*false/.test(fin), '결과와 무관하게 버튼을 다시 열면 한도 뒤에도 정상처럼 보인다');
  assert.ok(/code === 'server_error'\) attachRetry/.test(doSend), '서버 오류에만 다시 시도');
  const send = functionBody('send');
  assert.ok(/^async function send\(\) \{\n\s+if \(isLockActive\(chatLock, Date\.now\(\)\)\)/.test(send),
            '잠금 중에는 Enter·버튼·FAQ·?q= 진입 모두 보내지 않는다(send가 첫 줄에서 막는다)');
  const addErrorWithRetry = functionBody('addErrorWithRetry');
  assert.ok(addErrorWithRetry.includes('addNotice(') && !addErrorWithRetry.includes("addMsg('assistant'"),
            '네트워크·시간 초과 오류도 답변이 아니라 안내');
});
