(function (root) {
  'use strict';
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g,
    c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const PROVIDERS = ['claude', 'openai', 'gemini'];
  const NAMES = {claude: 'Claude', openai: 'OpenAI', gemini: 'Gemini'};
  const SOURCES = {settings: '저장값', env: '환경변수', default: '기본값'};

  function createClient(base, token, fetcher, unauthorized) {
    return async function (method, path, body) {
      const response = await fetcher(base + path, {method,
        headers: {Authorization: 'Bearer ' + token(), 'Content-Type': 'application/json'},
        ...(body === undefined ? {} : {body: JSON.stringify(body)})});
      const data = await response.json().catch(() => ({}));
      if (response.status === 401 && unauthorized) unauthorized();
      if (!response.ok) {
        const error = new Error(typeof data.detail === 'string' ? data.detail : '입력 또는 서버 연결을 확인하세요.');
        error.status = response.status;
        throw error;
      }
      return data;
    };
  }

  /** 저장 요청 본문. 바뀐 모델만 보내고, 바뀐 모델은 테스트 토큰이 있어야 한다.
   *  서버도 같은 검사를 하지만(화면 우회 방지), 여기서 먼저 막아 어느 모델이 문제인지 말해준다. */
  function saveBody(state, drafts, primary) {
    const models = {};
    for (const p of PROVIDERS) {
      const d = drafts[p];
      if (!d || !d.model || d.model === (state.providers[p] || {}).model) continue;
      if (!d.token) throw new Error(NAMES[p] + ' ' + d.model + ': 테스트를 먼저 통과해야 합니다.');
      models[p] = {model: d.model, token: d.token, latency_ms: d.latency_ms};
    }
    // 이미 저장된 모델은 그대로 유지되도록 함께 보낸다(서버가 미변경으로 판정 — 토큰 불요).
    for (const p of PROVIDERS) {
      const cur = state.providers[p] || {};
      if (!models[p] && cur.source === 'settings') models[p] = {model: cur.model};
    }
    return {revision: state.revision || 0, primary: primary || null, models};
  }

  function dirty(state, drafts, primary) {
    const primaryChanged = (primary || null) !== ((state.primary || {}).source === 'settings' ? state.primary.value : null);
    return primaryChanged || PROVIDERS.some(p => drafts[p] && drafts[p].model &&
      drafts[p].model !== (state.providers[p] || {}).model);
  }

  function renderProvider(p, info, draft) {
    info = info || {};
    draft = draft || {};
    if (!info.available) {
      return `<div class="model-row"><strong>${NAMES[p]}</strong> <span>API 키가 없어 사용할 수 없습니다</span></div>`;
    }
    const options = (draft.options || []).map(m =>
      `<option value="${esc(m.id)}"${m.id === (draft.model || info.model) ? ' selected' : ''}>` +
      `${esc(m.label && m.label !== m.id ? m.label + ' — ' + m.id : m.id)}${m.current ? ' (현재)' : ''}</option>`).join('');
    const result = draft.error ? `<span class="model-fail">✗ ${esc(draft.error)}</span>`
      : draft.token ? `<span class="model-ok">✓ 통과 ${esc((draft.latency_ms / 1000).toFixed(1))}초</span>` : '';
    return `<div class="model-row" data-provider="${p}">` +
      `<div><strong>${NAMES[p]}</strong> 현재 <code>${esc(info.model)}</code> ` +
      `<span class="badge">${esc(SOURCES[info.source] || info.source)}</span>` +
      (info.source === 'env' ? ' <small>저장하면 환경변수보다 우선합니다</small>' : '') + '</div>' +
      `<div class="model-controls"><button type="button" data-action="list" data-provider="${p}">목록 불러오기</button>` +
      (options ? `<select data-action="pick" data-provider="${p}">${options}</select>` +
        `<button type="button" data-action="test" data-provider="${p}">테스트</button>` : '') +
      ` ${result}</div></div>`;
  }

  function renderEvents(events) {
    if (!events || !events.length) return '<p>변경 이력이 없습니다.</p>';
    const summary = s => {
      const m = (s && s.models) || {};
      const parts = PROVIDERS.filter(p => m[p]).map(p => NAMES[p] + ' ' + m[p].model);
      return (s && s.primary ? '1순위 ' + NAMES[s.primary] + ' · ' : '') + (parts.join(', ') || '기본값');
    };
    return '<ul>' + events.map(e => `<li>rev ${esc(e.revision)} · ${esc(String(e.created_at || '').slice(0, 16).replace('T', ' '))} · ` +
      `${esc(summary(e.before))} → ${esc(summary(e.after))}</li>`).join('') + '</ul>';
  }

  function render(state, drafts, primary, message) {
    // 빈 값 = 저장하지 않음. 그때 실제로 쓰이는 것은 환경변수일 수 있으므로 라벨이 그것을 말해야 한다(R-5).
    const envPrimary = state.primary && state.primary.source === 'env' ? state.primary.value : null;
    const blankLabel = envPrimary ? '환경변수 따름(' + (NAMES[envPrimary] || envPrimary) + ')' : '기본 순서(Claude)';
    const radios = [['', blankLabel]].concat(PROVIDERS.map(p => [p, NAMES[p]])).map(([v, label]) => {
      const off = v && state.providers[v] && state.providers[v].available === false;
      return `<label><input type="radio" name="model-primary" value="${v}"${(primary || '') === v ? ' checked' : ''}` +
        `${off ? ' disabled' : ''}> ${esc(label)}${off ? ' (키 없음)' : ''}</label>`;
    }).join(' ');
    return '<div class="conv-header"><h2>답변 모델</h2><small>저장 후 최대 1분 안에 모든 서버에 반영됩니다</small></div>' +
      (state.store_available === false ? '<p class="model-fail">설정 저장소에 연결할 수 없어 기본값으로 동작 중입니다(저장 불가).</p>' : '') +
      `<div class="model-primary"><strong>1순위</strong> ${radios} <span class="badge">${esc(SOURCES[(state.primary || {}).source] || '')}</span></div>` +
      PROVIDERS.map(p => renderProvider(p, state.providers[p], drafts[p])).join('') +
      `<div class="model-actions"><button type="button" data-action="save"${dirty(state, drafts, primary) ? '' : ' disabled'}>저장</button> ` +
      '<button type="button" data-action="reset">기본값으로</button> ' +
      `<span class="model-message">${esc(message || '')}</span></div>` +
      '<h3>변경 이력</h3>' + renderEvents(state.events);
  }

  function mount(container, options) {
    const request = createClient(options.base, options.token, options.fetcher || root.fetch.bind(root), options.unauthorized);
    let state = {providers: {}, primary: {}, events: [], revision: 0};
    let drafts = {};
    let primary = '';
    let message = '';
    const paint = () => { container.innerHTML = render(state, drafts, primary, message); };

    async function reload() {
      try {
        state = await request('GET', '');
        drafts = {};
        primary = state.primary && state.primary.source === 'settings' ? state.primary.value : '';
        message = '';
      } catch (e) { message = e.message; }
      paint();
    }

    container.addEventListener('change', event => {
      const t = event.target;
      if (t.name === 'model-primary') { primary = t.value; paint(); }
      if (t.dataset.action === 'pick') {
        // 선택을 바꾸면 이전 테스트 결과·토큰은 무효 — 다른 모델 토큰의 재사용을 막는다.
        const p = t.dataset.provider;
        drafts[p] = {options: (drafts[p] || {}).options, model: t.value};
        paint();
      }
    });

    container.addEventListener('click', async event => {
      const t = event.target.closest('button[data-action]');
      if (!t) return;
      const p = t.dataset.provider;
      t.disabled = true;
      try {
        if (t.dataset.action === 'list') {
          const data = await request('GET', '/models?provider=' + encodeURIComponent(p));
          drafts[p] = {options: data.models, model: (state.providers[p] || {}).model};
        } else if (t.dataset.action === 'test') {
          const d = drafts[p] || {};
          const data = await request('POST', '/test', {provider: p, model: d.model});
          drafts[p] = Object.assign({}, d, {token: data.token, latency_ms: data.latency_ms, error: ''});
        } else if (t.dataset.action === 'save') {
          await request('PUT', '', saveBody(state, drafts, primary));
          await reload();
          message = '저장했습니다.';
        } else if (t.dataset.action === 'reset') {
          await request('POST', '/reset', {revision: state.revision || 0});
          await reload();
          message = '기본값으로 되돌렸습니다.';
        }
      } catch (e) {
        if (t.dataset.action === 'test' && p) drafts[p] = Object.assign({}, drafts[p], {token: '', error: e.message});
        else message = e.message;
        if (e.status === 409) { await reload(); message = e.message; }
      }
      paint();
    });

    reload();
    return {reload};
  }

  const api = {createClient, saveBody, dirty, renderProvider, renderEvents, render, mount};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.ModelSettings = api;
})(typeof window !== 'undefined' ? window : globalThis);
