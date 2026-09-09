'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, 'public/admin.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

// Extract the real top-level functions, including their private render helpers.
function renderers() {
  const context = vm.createContext({});
  const functions = script.match(/^(?:async )?function \w+\([^\n]*\) \{[\s\S]*?^\}/gm);
  vm.runInContext(functions.join('\n'), context);
  for (const name of ['renderEvaluationSummary', 'renderEvaluationRuns', 'renderEvaluationDetail', 'formatEvaluationMetric']) {
    assert.equal(typeof context[name], 'function', `Missing ${name}`);
  }
  return context;
}

const run = {
  run_id: 'eval_20260909_demo', mode: 'live', status: 'completed',
  started_at: '2026-09-09T01:00:00Z', finished_at: '2026-09-09T01:01:00Z',
  fixture_case_count: 60, evaluated_case_count: 1,
  summary: { automatic_pass_rate: 0, intent_accuracy: 1, topic_accuracy: null,
    required_law_coverage: 0.5, required_notice_coverage: 1, disclaimer_rate: 1,
    average_total_ms: 1234, p95_total_ms: 2345 },
  metadata: { commit: 'abc123' },
  results: [{ case_id: 'wage-01', category: '임금', question: '급여 질문',
    scores: { automatic_pass: false, intent_match: true, topic_match: null,
      required_law_coverage: 0.5, forbidden_claims_found: ['단정'], pipeline_ok: false },
    observed: { answer: '제한된 답변', pipeline_error: '실행 오류',
      sources: [{ source_type: 'law', title: '근로기준법' }],
      analysis: { intent: 'wage' }, calc_result: { total: 100 },
      assessment_result: { result: '검토' }, timing: { total_ms: 1234, ttft_ms: 250 } } }],
};

test('missing metrics differ from measured zero and use rate/timing units', () => {
  const { formatEvaluationMetric: format } = renderers();
  for (const value of [null, undefined, NaN, Infinity, '', '<img>', {}]) {
    assert.equal(format(value, 'rate'), '측정 없음');
  }
  assert.equal(format(0, 'rate'), '0.0%');
  assert.equal(format(0.875, 'rate'), '87.5%');
  assert.equal(format(1234, 'ms'), '1,234 ms');
});

test('empty, unexecuted and offline summaries never imply live measurements', () => {
  const { renderEvaluationSummary: render } = renderers();
  for (const value of [null, {}, { ...run, status: 'unexecuted' }, { ...run, mode: 'offline' }]) {
    const result = render(value);
    assert.match(result, /측정 없음/);
    assert.doesNotMatch(result, /0\.0%|1,234 ms/);
  }
  assert.match(render({ ...run, mode: 'offline' }), /구조 검증/);
});

test('completed summary uses the evaluator aggregate keys', () => {
  const result = renderers().renderEvaluationSummary(run);
  for (const value of ['0.0%', '100.0%', '50.0%', '측정 없음', '1,234 ms', '2,345 ms']) assert.ok(result.includes(value), value);
});

test('run list shows empty state, mode, status, dates and counts', () => {
  const { renderEvaluationRuns: render } = renderers();
  assert.match(render([]), /실행 없음/);
  const result = render([run, { ...run, mode: 'offline', status: 'partial' }]);
  for (const value of ['eval_20260909_demo', 'Live', '완료', '구조 검증', '일부 실패', '2026-09-09', '60']) assert.ok(result.includes(value), value);
});

test('detail renders nested case scores, observations and run metadata', () => {
  const result = renderers().renderEvaluationDetail(run);
  for (const value of ['wage-01', '임금', '불합격', '급여 질문', '제한된 답변', '실행 오류', '근로기준법', 'wage', '100', '검토', '1,234 ms', '250 ms', 'abc123', '측정 없음']) assert.ok(result.includes(value), value);
});

test('every server string is escaped in run headers, cases, metadata and nested observations', () => {
  const payload = '<img src=x onerror="alert(1)"> & <script>bad</script>';
  const poisoned = JSON.parse(JSON.stringify(run), (key, value) => typeof value === 'string' ? payload : value);
  poisoned.mode = payload;
  poisoned.status = payload;
  poisoned.fixture_case_count = payload;
  poisoned.evaluated_case_count = payload;
  poisoned.results[0].scores.extra = payload;
  poisoned.metadata[payload] = payload;
  const { renderEvaluationRuns, renderEvaluationDetail, renderEvaluationSummary } = renderers();
  for (const result of [renderEvaluationRuns([poisoned]), renderEvaluationDetail(poisoned), renderEvaluationSummary(poisoned)]) {
    assert.doesNotMatch(result, /<img|<script|onclick=/);
    assert.match(result, /&lt;img/);
    assert.match(result, /&amp;/);
  }
});

test('flat case rendering escapes answer and error and bounds oversized answers', () => {
  const { renderEvaluationDetail: render } = renderers();
  const result = render({ question: '<script>bad</script>', answer: '<b>answer</b>', pipeline_error: '<i>error</i>' });
  assert.match(result, /&lt;script&gt;/);
  assert.match(result, /&lt;b&gt;answer/);
  assert.match(result, /&lt;i&gt;error/);
  assert.doesNotMatch(result, /<script>|<b>|<i>/);
  assert.doesNotMatch(render({ answer: 'a'.repeat(3000) + 'TAIL' }), /TAIL/);
});

test('malformed saved data does not break renderers', () => {
  const { renderEvaluationRuns, renderEvaluationDetail, renderEvaluationSummary } = renderers();
  for (const value of [undefined, null, 'broken', 4, [], { summary: null, results: [null, 'broken'], metadata: null }]) {
    assert.equal(typeof renderEvaluationDetail(value), 'string');
    assert.equal(typeof renderEvaluationSummary(value), 'string');
    assert.equal(typeof renderEvaluationRuns(value), 'string');
  }
});

// Minimal document/network boundary: execute the whole Admin script so navigation,
// bearer-token fetches and asynchronous rendering stay covered without npm packages.
function browser(respond) {
  const elements = new Map();
  for (const match of html.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)) {
    const classes = new Set((match[0].match(/class="([^"]*)"/)?.[1] || '').split(/\s+/));
    elements.set(match[1], { innerHTML: '', textContent: '', value: '', onclick: null,
      addEventListener() {}, classList: {
        add: name => classes.add(name), remove: name => classes.delete(name),
        contains: name => classes.has(name),
        toggle(name, enabled) { if (enabled) classes.add(name); else classes.delete(name); },
      } });
  }
  const requests = [];
  let reloaded = false;
  const context = vm.createContext({
    document: { getElementById: id => elements.get(id), addEventListener() {} },
    location: { hostname: 'localhost', reload() { reloaded = true; } },
    localStorage: { getItem() { return null; }, removeItem() {}, setItem() {} },
    fetch: async (url, options) => { requests.push({ url, options }); return respond(url, options); },
    alert() {}, URLSearchParams,
  });
  vm.runInContext(script, context);
  vm.runInContext('token = "admin-test-token";', context);
  return { context, elements, requests, reloaded: () => reloaded };
}
const response = (data, status = 200) => ({ ok: status < 400, status, json: async () => data });
const flush = () => new Promise(resolve => setImmediate(resolve));

test('quality navigation loads using the existing bearer helper and preserves other views', async () => {
  const app = browser(() => response({ runs: [run], total: 1 }));
  app.context.showView('quality');
  await flush();
  assert.equal(app.elements.get('quality-view').classList.contains('hidden'), false);
  assert.equal(app.elements.get('dashboard-view').classList.contains('hidden'), true);
  assert.equal(app.elements.get('conversations-view').classList.contains('hidden'), true);
  assert.equal(app.requests[0].url, '/api/admin/evaluation-runs');
  assert.equal(app.requests[0].options.headers.Authorization, 'Bearer admin-test-token');
  assert.match(app.elements.get('quality-run-list').innerHTML, /eval_20260909_demo/);
  for (const name of ['doLogin', 'logout', 'loadStats', 'loadConversations', 'openDetail', 'closeModal', 'md']) assert.equal(typeof app.context[name], 'function');
  app.context.loadStats = () => {};
  app.context.loadConversations = () => {};
  for (const view of ['dashboard', 'conversations']) {
    app.context.showView(view);
    assert.equal(app.elements.get('quality-view').classList.contains('hidden'), true);
    assert.equal(app.elements.get(`${view}-view`).classList.contains('hidden'), false);
  }
});

test('run selection requests encoded detail and renders selected cases', async () => {
  const app = browser(url => response(url.endsWith('/evaluation-runs') ? { runs: [run] } : run));
  await app.context.loadEvaluationRuns();
  app.elements.get('quality-run-list').onclick({ target: { closest: () => ({ dataset: { evaluationIndex: '0' } }) } });
  await flush();
  assert.equal(app.requests[1].url, '/api/admin/evaluation-runs/eval_20260909_demo');
  assert.match(app.elements.get('quality-detail').innerHTML, /급여 질문/);
});

test('loading, empty, offline-only and API failures have visible states', async () => {
  let resolve;
  const app = browser(() => new Promise(done => { resolve = done; }));
  const pending = app.context.loadEvaluationRuns();
  assert.match(app.elements.get('quality-status').textContent, /불러오는 중/);
  resolve(response({ runs: [] }));
  await pending;
  assert.match(app.elements.get('quality-status').textContent, /실행 없음/);
  const offline = browser(() => response({ runs: [{ ...run, mode: 'offline' }] }));
  await offline.context.loadEvaluationRuns();
  assert.match(offline.elements.get('quality-status').textContent, /Live 미실행/);
  assert.doesNotMatch(offline.elements.get('quality-stat-cards').innerHTML, /0\.0%/);
  for (const respond of [() => response({ detail: '<script>bad</script>' }, 503), () => { throw new Error('network'); }]) {
    const failure = browser(respond);
    await failure.context.loadEvaluationRuns();
    assert.match(failure.elements.get('quality-status').textContent, /불러오지 못/);
    assert.equal(failure.elements.get('quality-run-list').innerHTML, '');
  }
});

test('expired authentication follows existing logout behavior', async () => {
  const app = browser(() => response({}, 401));
  await app.context.loadEvaluationRuns();
  assert.equal(app.reloaded(), true);
  assert.doesNotMatch(app.elements.get('quality-detail').innerHTML, /급여 질문/);
});

test('late detail responses cannot replace a more recently selected run', async () => {
  const pending = [];
  const app = browser(() => new Promise(resolve => pending.push(resolve)));
  const first = app.context.loadEvaluationRun('eval_first');
  const second = app.context.loadEvaluationRun('eval_second');
  pending[1](response({ ...run, run_id: 'eval_second' }));
  await second;
  pending[0](response({ ...run, run_id: 'eval_first' }));
  await first;
  assert.match(app.elements.get('quality-detail').innerHTML, /eval_second/);
  assert.doesNotMatch(app.elements.get('quality-detail').innerHTML, /eval_first/);
});

test('detail IDs are encoded and failures clear the previous detail', async () => {
  const app = browser(() => response({}, 404));
  app.elements.get('quality-detail').innerHTML = 'old answer';
  await app.context.loadEvaluationRun('eval/a?b');
  assert.equal(app.requests[0].url, '/api/admin/evaluation-runs/eval%2Fa%3Fb');
  assert.match(app.elements.get('quality-detail').textContent, /불러오지 못/);
  assert.doesNotMatch(app.elements.get('quality-detail').innerHTML, /old answer/);
});

test('refresh discards stale list and detail responses', async () => {
  const pending = [];
  const app = browser(() => new Promise(resolve => pending.push(resolve)));
  const firstList = app.context.loadEvaluationRuns();
  const detail = app.context.loadEvaluationRun('eval_old');
  const latestList = app.context.loadEvaluationRuns();
  pending[2](response({ runs: [] }));
  await latestList;
  pending[0](response({ runs: [run] }));
  pending[1](response(run));
  await Promise.all([firstList, detail]);
  assert.match(app.elements.get('quality-status').textContent, /실행 없음/);
  assert.doesNotMatch(app.elements.get('quality-run-list').innerHTML, /eval_20260909_demo/);
  assert.doesNotMatch(app.elements.get('quality-detail').innerHTML, /급여 질문/);
});

test('latest run drives summary and failed requests clear old summary values', async () => {
  let fail = false;
  const app = browser(() => fail ? response({}, 503) : response({ runs: [run] }));
  await app.context.loadEvaluationRuns();
  assert.match(app.elements.get('quality-stat-cards').innerHTML, /1,234 ms/);
  assert.match(app.elements.get('quality-status').textContent, /완료/);
  fail = true;
  await app.context.loadEvaluationRuns();
  assert.doesNotMatch(app.elements.get('quality-stat-cards').innerHTML, /1,234 ms/);
});

test('malformed list payload shows an error instead of reporting no runs', async () => {
  const app = browser(() => response({ runs: 'broken' }));
  await app.context.loadEvaluationRuns();
  assert.match(app.elements.get('quality-status').textContent, /불러오지 못/);
});
