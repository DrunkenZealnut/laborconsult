'use strict';

// 채팅 이용 제한 잠금(일일 횟수·자동 차단·분당 한도)과 거절 안내 표시의 회귀 테스트.
//
// 2026-10-06 실측: 일일 쿼터에 걸린 뒤에도 거절 문구가 일반 답변 말풍선으로 그려지고(답변 액션 바·
// 복사 버튼까지 붙음) 전송 버튼이 다시 열려, 겉으로는 정상처럼 보였다. 자동 점검 도구는 같은 거절을
// 계속 받으며(51~54번째 요청) 그 문구를 답변으로 수집했다.
//
// L7~L16은 전송 관문(진행 중 잠금). 2026-10-22 재현: 답변 수신 중 FAQ·다시 시도, 첨부 인코딩 중 버튼·Enter
// 연타가 요청을 하나 더 보냈고, 인코딩 중에 쓴 다음 질문이 지워졌으며, 파일 읽기 실패는 아무 안내가 없었다.
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
  const end = functionBody('endSubmission');
  assert.ok(end.includes('applyChatLock()'), '전송이 끝나면 잠금 상태를 적용');
  assert.ok(!/btn\.disabled\s*=\s*false/.test(end), '결과와 무관하게 버튼을 다시 열면 한도 뒤에도 정상처럼 보인다');
  const doSend = functionBody('doSend');
  assert.ok(!/btn\.disabled\s*=/.test(doSend), '버튼은 관문(applyChatLock)만 바꾼다');
  assert.ok(/code === 'server_error'\) attachRetry/.test(doSend), '서버 오류에만 다시 시도');
  const send = functionBody('send');
  assert.ok(/^async function send\(\) \{\n\s+if \(!beginSubmission\(\)\) return;/.test(send),
            '잠금·진행 중에는 Enter·버튼·FAQ·?q= 진입 모두 보내지 않는다(send가 첫 줄에서 막는다)');
  assert.ok(functionBody('beginSubmission').includes('isLockActive(chatLock, Date.now())'), '관문이 이용 제한 잠금도 본다');
  const addErrorWithRetry = functionBody('addErrorWithRetry');
  assert.ok(addErrorWithRetry.includes('addNotice(') && !addErrorWithRetry.includes("addMsg('assistant'"),
            '네트워크·시간 초과 오류도 답변이 아니라 안내');
});

// ── 전송 관문 행동 테스트 ────────────────────────────────────────────────────
// 실제 send·doSend·attachRetry·askQuestion·resetChat과 관문 함수를 vm에서 돌린다. fetch·FileReader·DOM·SSE
// 읽기는 모의다(네트워크·브라우저 없음). 실제 브라우저 확인은 Design §7(로컬 모의 서버)이 맡는다.

const SUBMISSION_FUNCS = ['isLockActive', 'lockNotice', 'guardLockFromEvent', 'applyChatLock', 'setChatLock',
                          'beginSubmission', 'endSubmission', 'ensureStatus', 'removeStatus',
                          'send', 'doSend', 'attachRetry', 'addErrorWithRetry', 'askQuestion', 'resetChat'];

const abortError = () => Object.assign(new Error('aborted'), { name: 'AbortError' });
const flush = async (n = 5) => { for (let i = 0; i < n; i++) await new Promise(r => setImmediate(r)); };
const settle = (p, ms = 50) => Promise.race([p, new Promise(r => setTimeout(r, ms))]);

function submissionHarness({ files = 0, holdFetch = false } = {}) {
  const items = [];   // 채팅 영역: {role, el}
  const reads = [], requests = [], streams = [], timers = [], created = [];
  const node = extra => Object.assign({
    disabled: false, dataset: {}, listeners: {}, children: [], textContent: '', innerHTML: '',
    appendChild(c) { this.children.push(c); },
    addEventListener(type, fn) { this.listeners[type] = fn; },
    classList: { toggle() {}, add() {}, remove() {}, contains() { return false; } },
    querySelector() { return null; }, scrollIntoView() {},
  }, extra);
  const push = (role, extra) => {
    const el = node(extra);
    el.closest = () => ({ remove() { const i = items.findIndex(x => x.el === el); if (i >= 0) items.splice(i, 1); } });
    items.push({ role, el });
    return el;
  };
  const chat = {
    get children() { return items; },
    set innerHTML(_) { items.length = 0; },
    querySelector(sel) { const it = sel === '.msg.status' && items.find(x => x.role === 'status'); return it ? it.el : null; },
    querySelectorAll(sel) { return sel === '.msg.status' ? items.filter(x => x.role === 'status').map(x => x.el) : []; },
    scrollTop: 0, scrollHeight: 0,
  };
  const ctx = {
    btn: node(), attachBtn: node(),
    msgInput: node({ value: '첫 질문', placeholder: '', style: {}, focus() {}, dispatchEvent() {} }),
    chat, pendingFiles: Array.from({ length: files }, (_, i) => ({ name: `f${i}.txt`, size: 1 })),
    sessionId: null, API_BASE: '',
    expandChat() {}, renderPreview() {}, escHtml: s => s, guessMime: () => 'text/plain',
    addMsg: (role, html) => push(role, { innerHTML: html }),
    addNotice: (text, code) => push('notice', { textContent: text, code }),
    fileToBase64: () => new Promise((resolve, reject) => reads.push({ resolve, reject })),
    fetch: (url, opts) => new Promise((resolve, reject) => {
      const signal = opts && opts.signal;
      requests.push({ url });
      if (signal) signal.addEventListener('abort', () => reject(abortError()));
      if (!holdFetch) resolve({ ok: true, signal });   // 헤더는 바로 오고, 본문(readSSE)은 테스트가 끝낸다
    }),
    readSSE: resp => new Promise((resolve, reject) => {
      ctx.ensureStatus('질문 분석 중...');   // 실제 readSSE 첫 줄과 같다(L15 구조 검사)
      streams.push({ resolve, reject });
      if (resp.signal) resp.signal.addEventListener('abort', () => reject(abortError()));
    }),
    document: {
      getElementById: () => node(),
      createElement: () => { const n = node(); created.push(n); return n; },
    },
    window: { scrollTo() {} }, confirm: () => true,
    sessionStorage: { removeItem() {} }, localStorage: { setItem() {}, removeItem() {}, getItem() { return null; } },
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; }, clearTimeout() {},
    AbortController, URLSearchParams, JSON, Date, Math, Number, String,
    Event: class { constructor(type) { this.type = type; } },
  };
  vm.createContext(ctx);
  const code = [
    "var chatLock = null, chatLockTimer = null, submitting = false, chatEpoch = 0, activeSend = null;",
    "const LOCK_STORAGE_KEY = 'chatLock'; const LOCKING_CODES = ['quota', 'blocked', 'rate_limited'];",
    "const LOCK_MAX_MS = 24 * 3600 * 1000; const INPUT_PLACEHOLDER = '질문을 입력하세요'; const SEND_TIMEOUT_MS = 60000;",
    ...SUBMISSION_FUNCS.map(functionBody),
  ].join('\n\n');
  new vm.Script(code, { filename: 'extracted-submission.vm.js' }).runInContext(ctx);
  return {
    ctx, requests, streams,
    run: expr => vm.runInContext(expr, ctx),
    resolveReads: () => reads.splice(0).forEach(r => r.resolve('eA==')),
    rejectReads: () => reads.splice(0).forEach(r => r.reject(new Error('read'))),
    finishStreams: (outcome = { error: null, notice: null }) => streams.splice(0).forEach(s => s.resolve(outcome)),
    fireTimers: ms => timers.filter(t => t.ms === ms).forEach(t => t.fn()),
    userBubbles: () => items.filter(x => x.role === 'user').length,
    statusCount: () => items.filter(x => x.role === 'status').length,
    notices: () => items.filter(x => x.role === 'notice').map(x => x.el),
    retryButtons: () => created.filter(n => typeof n.listeners.click === 'function'),
  };
}

test('L7: 첨부 인코딩 중 두 번째 전송(버튼·Enter)은 막힌다 — 요청 1건', async () => {
  const h = submissionHarness({ files: 1 });
  const p1 = h.run('send()');
  assert.equal(h.ctx.btn.disabled, true, '인코딩 중에도 전송 버튼이 잠긴다');
  const p2 = h.run('send()');
  assert.equal(h.ctx.btn.disabled, true, '막힌 호출은 남의 관문을 풀지 않는다');
  h.resolveReads();
  await flush();
  assert.equal(h.requests.length, 1);
  assert.equal(h.userBubbles(), 1);
  h.finishStreams();
  await Promise.all([p1, p2]);
  assert.equal(h.ctx.btn.disabled, false, '끝나면 다시 열린다');
});

test('L8: 답변 수신 중 FAQ는 보내지 않고 질문을 입력창에 남긴다', async () => {
  const h = submissionHarness();
  const p1 = h.run('send()');
  await flush();
  h.run('askQuestion("FAQ 후속 질문")');
  h.fireTimers(300);
  await flush();
  assert.equal(h.requests.length, 1);
  assert.equal(h.ctx.msgInput.value, 'FAQ 후속 질문');
  assert.equal(h.ctx.btn.disabled, true, '막힌 FAQ는 남의 관문을 풀지 않는다');
  h.finishStreams();
  await p1;
});

test('L9: 답변 수신 중 다시 시도는 막히고, 끝난 뒤에는 다시 누를 수 있다', async () => {
  const h = submissionHarness();
  h.run('addErrorWithRetry("이전 오류", "이전 질문", [])');
  const retry = h.retryButtons()[0];
  const p1 = h.run('send()');
  await flush();
  await settle(retry.listeners.click());
  await flush();
  assert.equal(h.requests.length, 1, '진행 중에는 다시 시도가 요청을 보내지 않는다');
  assert.equal(retry.disabled, false, '막힌 클릭은 버튼을 소비하지 않는다');
  assert.equal(h.ctx.btn.disabled, true, '막힌 다시 시도는 남의 관문을 풀지 않는다');
  h.finishStreams();
  await p1;
  const p2 = retry.listeners.click();
  assert.equal(h.statusCount(), 1, '다시 시도도 전송 직후(응답 헤더 전) 상태를 보인다');
  await flush();
  assert.equal(h.requests.length, 2, '진행 중이 아니면 다시 시도가 나간다');
  h.finishStreams();
  await p2;
});

test('L10: 인코딩 중에 쓴 다음 질문은 지워지지 않는다', async () => {
  const h = submissionHarness({ files: 1 });
  const p1 = h.run('send()');
  assert.equal(h.ctx.msgInput.value, '', '전송을 시작하면 입력창을 바로 비운다');
  h.ctx.msgInput.value = '다음 질문';
  h.resolveReads();
  await flush();
  assert.equal(h.ctx.msgInput.value, '다음 질문');
  h.finishStreams();
  await p1;
});

test('L11: 파일 읽기 실패 — 관문이 풀리고 질문·첨부가 돌아오며 안내가 뜬다(요청 0)', async () => {
  const h = submissionHarness({ files: 1 });
  const p1 = h.run('send()');
  h.rejectReads();
  await p1;
  assert.equal(h.requests.length, 0);
  assert.equal(h.ctx.msgInput.value, '첫 질문');
  assert.equal(h.ctx.pendingFiles.length, 1);
  assert.deepEqual(h.notices().map(n => n.code), ['invalid']);
  assert.equal(h.ctx.btn.disabled, false);
  assert.equal(h.statusCount(), 0);

  const h2 = submissionHarness({ files: 1 });
  const p2 = h2.run('send()');
  h2.ctx.msgInput.value = '그사이 쓴 글';
  h2.ctx.pendingFiles = [{ name: 'new.txt', size: 1 }];
  h2.rejectReads();
  await p2;
  assert.equal(h2.ctx.msgInput.value, '그사이 쓴 글', '그사이 쓴 글은 덮지 않는다');
  assert.deepEqual(h2.ctx.pendingFiles.map(f => f.name), ['new.txt'], '그사이 고른 첨부도 덮지 않는다');

  // 진행 중에 누른 Enter는 막히지만 줄바꿈을 넣는다 — 줄바꿈뿐이면 빈칸으로 보고 되돌린다
  const h3 = submissionHarness({ files: 1 });
  const p3 = h3.run('send()');
  h3.ctx.msgInput.value = '\n';
  h3.rejectReads();
  await p3;
  assert.equal(h3.ctx.msgInput.value, '첫 질문');

  // 입력 거절(invalid) 응답의 복원도 같은 기준이다
  const h4 = submissionHarness();
  const p4 = h4.run('send()');
  await flush();
  h4.ctx.msgInput.value = '\n';
  h4.finishStreams({ error: { code: 'invalid' }, notice: {} });
  await p4;
  assert.equal(h4.ctx.msgInput.value, '첫 질문');
});

test('L12: 진행 중에 이용 제한 거절이 오면 끝난 뒤에도 잠긴 채다', async () => {
  const h = submissionHarness();
  const p1 = h.run('send()');
  await flush();
  h.run("setChatLock(guardLockFromEvent({ code: 'quota', retry_after: 3600 }, Date.now()))");
  h.finishStreams({ error: { code: 'quota' }, notice: null });
  await p1;
  assert.equal(h.ctx.btn.disabled, true);
  h.ctx.msgInput.value = '다음 질문';   // 막는 이유가 빈 입력이 아니라 잠금이어야 한다
  await h.run('send()');
  assert.equal(h.requests.length, 1);
  assert.equal(h.ctx.msgInput.value, '다음 질문', '막힌 전송은 입력을 지우지 않는다');
});

test('L13: 요청이 실패해도 관문이 풀린다', async () => {
  const h = submissionHarness();
  const p1 = h.run('send()');
  await flush();
  h.streams.splice(0).forEach(s => s.reject(new Error('stream broke')));
  await p1;
  assert.equal(h.ctx.btn.disabled, false);
  assert.equal(h.notices()[0].code, 'server_error');
  h.ctx.msgInput.value = '두 번째 질문';
  const p2 = h.run('send()');
  await flush();
  assert.equal(h.requests.length, 2);
  h.finishStreams();
  await p2;
});

test('L14: 새 상담은 진행 중 요청을 끊고 관문을 바로 푼다 — 빈 화면에 오류를 띄우지 않는다', async () => {
  const h = submissionHarness();
  const p1 = h.run('send()');
  await flush();
  h.run('resetChat()');
  await settle(p1);
  await flush();
  assert.equal(h.ctx.btn.disabled, false);
  assert.equal(h.notices().length, 0);
  assert.equal(h.statusCount(), 0);

  // 인코딩 중 새 상담 — 읽기가 끝나도 새 대화로 보내지 않는다
  const h2 = submissionHarness({ files: 1 });
  const p2 = h2.run('send()');
  h2.run('resetChat()');
  h2.resolveReads();
  await settle(p2);   // 회귀하면 요청이 나가 스트림을 기다리며 멈춘다 — 멈추지 말고 단언으로 실패하게
  assert.equal(h2.requests.length, 0);
  assert.equal(h2.ctx.btn.disabled, false);

  // 인코딩 중 새 상담 뒤 읽기 실패 — 새 대화에 옛 질문을 되돌리거나 안내하지 않는다
  const h3 = submissionHarness({ files: 1 });
  const p3 = h3.run('send()');
  h3.run('resetChat()');
  h3.rejectReads();
  await settle(p3);
  assert.equal(h3.ctx.msgInput.value, '');
  assert.equal(h3.notices().length, 0);

  // 응답 헤더 전(콜드 스타트 중) 초기화 — fetch 자체가 AbortError로 끝나도 안내 없이 관문이 풀린다
  const h4 = submissionHarness({ holdFetch: true });
  const p4 = h4.run('send()');
  await flush();
  assert.equal(h4.requests.length, 1);
  h4.run('resetChat()');
  await settle(p4);
  assert.equal(h4.ctx.btn.disabled, false);
  assert.equal(h4.notices().length, 0, '끊긴 요청에 시간 초과 안내를 띄우지 않는다');
});

test('L15: 전송 직후(응답 헤더 전) 상태 말풍선이 하나 보이고, 응답 처리는 그것을 이어 쓴다', async () => {
  const h = submissionHarness({ files: 1 });
  const p1 = h.run('send()');
  assert.equal(h.statusCount(), 1, '첨부 인코딩 중에도 상태가 보인다');
  h.resolveReads();
  await flush();
  assert.equal(h.statusCount(), 1, '응답 처리는 상태 말풍선을 새로 만들지 않는다');
  h.finishStreams();
  await p1;
  assert.equal(h.statusCount(), 0);
  const readSSE = functionBody('readSSE');
  assert.ok(readSSE.includes("ensureStatus('질문 분석 중...')") && !readSSE.includes("addMsg('status'"));
});

test('L16: 진입점은 모두 관문을 지난다(구조)', () => {
  assert.match(functionBody('send'), /\} finally \{\n\s+endSubmission\(\);/);
  const retry = functionBody('attachRetry');
  assert.match(retry, /addEventListener\('click', async \(\) => \{\n\s+if \(!beginSubmission\(\)\) return;/,
               '다시 시도의 관문은 try 밖 첫 문장 — 막힌 클릭이 finally로 남의 관문을 풀면 안 된다');
  assert.ok(retry.includes('endSubmission()'), '다시 시도도 끝나면 관문을 푼다');
  assert.equal((SOURCE.match(/(?<!function )\bdoSend\(/g) || []).length, 2,
               'doSend는 send와 다시 시도에서만 부른다 — 새 호출처는 관문을 우회한다');
  assert.ok(SOURCE.includes("btn.addEventListener('click', send);"), '전송 버튼은 send를 지난다');
  assert.match(SOURCE, /msgInput\.addEventListener\('keydown', e => \{\n\s+if \(e\.key === 'Enter' && !e\.shiftKey && !btn\.disabled\) \{\n\s+e\.preventDefault\(\);\n\s+send\(\);/,
               'Enter는 send를 지난다');
  const ask = functionBody('askQuestion');
  assert.ok(ask.includes('send()') && !ask.includes('doSend('), 'FAQ·게시판·?q=는 send()를 지난다');
  assert.ok(/btn\.disabled = locked \|\| submitting/.test(functionBody('applyChatLock')), '버튼 상태는 진행 중도 함께 본다');
  assert.ok(SOURCE.indexOf('let submitting') >= 0 && SOURCE.indexOf('let submitting') < SOURCE.indexOf('(function restoreChatLock'),
            'restoreChatLock이 applyChatLock을 부르기 전에 선언해야 한다(TDZ)');
});
