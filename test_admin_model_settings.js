const test = require('node:test');
const assert = require('node:assert/strict');
const {createClient, saveBody, dirty, renderProvider, renderEvents, render} =
  require('./public/admin_model_settings.js');

const STATE = {
  revision: 3, store_available: true,
  primary: {value: null, source: 'default'},
  providers: {
    claude: {model: 'claude-sonnet-5', source: 'default', available: true},
    openai: {model: 'o3', source: 'settings', available: true},
    gemini: {model: 'gemini-pro-latest', source: 'env', available: false},
  },
  events: [],
};

test('vendor-supplied model names and labels are escaped', () => {
  const attack = '<img src=x onerror=alert(1)>';
  const html = renderProvider('claude', {model: attack, source: 'default', available: true},
    {options: [{id: attack, label: attack, current: true}], model: attack}) +
    renderEvents([{revision: 1, created_at: attack, before: {models: {claude: {model: attack}}}, after: {}}]);
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img/);
});

test('changed model without a test token is refused before the request', () => {
  assert.throws(() => saveBody(STATE, {claude: {model: 'claude-sonnet-5-5'}}, ''), /테스트를 먼저/);
});

test('save body sends changed models with tokens and keeps stored ones', () => {
  const body = saveBody(STATE, {claude: {model: 'claude-sonnet-5-5', token: 't', latency_ms: 900}}, 'claude');
  assert.deepEqual(body, {revision: 3, primary: 'claude', models: {
    claude: {model: 'claude-sonnet-5-5', token: 't', latency_ms: 900},
    openai: {model: 'o3'},        // 저장값 유지 — 빼면 저장 시 기본값으로 돌아간다
  }});
});

test('picking the current model again is not a change', () => {
  assert.equal(dirty(STATE, {claude: {model: 'claude-sonnet-5'}}, ''), false);
  assert.equal(dirty(STATE, {claude: {model: 'claude-sonnet-5-5'}}, ''), true);
  assert.equal(dirty(STATE, {}, 'openai'), true);
});

test('unavailable provider renders no controls and env source explains precedence', () => {
  assert.doesNotMatch(renderProvider('gemini', STATE.providers.gemini, {}), /data-action="test"/);
  const envInfo = {model: 'gpt-x', source: 'env', available: true};
  assert.match(renderProvider('openai', envInfo, {}), /환경변수보다 우선/);
});

test('save button is disabled until something changes; store outage is shown', () => {
  assert.match(render(STATE, {}, '', ''), /data-action="save" disabled/);
  assert.doesNotMatch(render(STATE, {}, 'openai', ''), /data-action="save" disabled/);
  assert.match(render(Object.assign({}, STATE, {store_available: false}), {}, '', ''), /연결할 수 없어/);
});

test('client sends bearer, surfaces server detail and status, and signals 401', async () => {
  let unauthorized = 0;
  const calls = [];
  const client = createClient('/api/admin/model-settings', () => 'tok', async (url, init) => {
    calls.push({url, init});
    return {ok: false, status: calls.length === 1 ? 409 : 401, json: async () => ({detail: '먼저 변경됐습니다'})};
  }, () => { unauthorized += 1; });
  await assert.rejects(client('PUT', '', {revision: 1}), e => e.status === 409 && /먼저 변경/.test(e.message));
  assert.equal(calls[0].init.headers.Authorization, 'Bearer tok');
  assert.equal(calls[0].init.body, JSON.stringify({revision: 1}));
  await assert.rejects(client('GET', ''));
  assert.equal(unauthorized, 1);
});

test('primary radios: env-following label and keyless Gemini disabled', () => {
  const html = render(STATE, {}, '', '');
  assert.match(html, /value="gemini" disabled> Gemini \(키 없음\)/);
  assert.match(html, /기본 순서\(Claude\)/);
  const envState = Object.assign({}, STATE, {primary: {value: 'openai', source: 'env'}});
  assert.match(render(envState, {}, '', ''), /환경변수 따름\(OpenAI\)/);
});
