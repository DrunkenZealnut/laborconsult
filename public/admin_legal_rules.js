(function (root) {
  'use strict';
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g,
    c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const labels = {pending: '검토 대기', approved: '승인', rejected: '반려', revoked: '승인 취소', reviewed: '코드 검토 기록'};
  const scanLabels = {completed: '검색 완료', partial: '부분 검색 — 공식 원문 조회 실패', empty: '검색 결과 없음', failed: '검색 실패'};
  const scanStatusLabel = status => scanLabels[status] || status;
  const num = value => typeof value === 'number' && Number.isFinite(value);
  const fmt = value => !num(value) ? '—'
    : Number.isInteger(value) ? value.toLocaleString('en-US') : String(value);

  function renderRows(records) {
    if (!records.length) return '<p>변경 후보가 없습니다. 검색하거나 수동 등록하세요.</p>';
    return '<table><thead><tr><th>상태</th><th>주제 / 기준</th><th>값</th><th>적용기간 (종료일 제외)</th><th>근거</th><th>상세</th></tr></thead><tbody>' + records.map(r =>
      `<tr><td>${esc(labels[r.status] || r.status)}</td><td>${esc(r.topic)}<br>${esc(r.key || '산식·자격 검토')}</td>` +
      `<td>${esc(r.value)}</td><td>${esc(r.effective_from)} ~ ${esc(r.effective_to || '미지정')}</td>` +
      `<td>${esc(r.citation || (r.evidence || {}).title)}</td><td><button type="button" data-action="select" data-id="${esc(r.id)}">검토</button></td></tr>`
    ).join('') + '</tbody></table>';
  }

  function renderEvidence(evidence) {
    if (!evidence) return '<p>문서 ID로 근거를 조회하세요.</p>';
    let link = '';
    try {
      const url = new URL(evidence.official_url || evidence.url);
      if (url.protocol === 'https:') link = `<a href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">출처 열기</a>`;
    } catch (_) { /* a missing source is displayed without a link */ }
    // 목록 응답에는 원문이 없다(응답 크기). 선택 시 상세로 받아 채운다.
    const body = evidence.text === undefined
      ? `<p>저장된 근거 원문 ${esc(evidence.text_length || 0)}자 — 불러오는 중…</p>`
      : `<pre class="legal-evidence">${esc(evidence.text)}</pre>`;
    return `<h4>${esc(evidence.title)}</h4><p>${esc(evidence.source_type)} · ${esc(evidence.id)} ${link}</p>` +
      body + `<small>원문 해시: ${esc(evidence.sha256)}</small>`;
  }

  /** 인용구절을 저장 원문 그대로의 부분문자열로 맞춘다(공백 표기 차이 흡수).
   *  배경과 근거는 CLAUDE.md 의 Legal Rule Registry 절. */
  function alignQuote(quote, text) {
    const raw = String(quote == null ? '' : quote).trim();
    const body = String(text == null ? '' : text);
    if (!raw) return {quote: '', exact: false, adjusted: false};
    if (body.indexOf(raw) !== -1) return {quote: raw, exact: true, adjusted: false};
    const index = [];
    let compact = '';
    for (let i = 0; i < body.length; i += 1) {
      if (!/\s/.test(body[i])) { index.push(i); compact += body[i]; }
    }
    const needle = raw.replace(/\s+/g, '');
    const at = needle ? compact.indexOf(needle) : -1;
    if (at === -1) return {quote: raw, exact: false, adjusted: false};
    return {quote: body.slice(index[at], index[at + needle.length - 1] + 1),
            exact: true, adjusted: true};
  }

  // 입력값이 현재값과 이만큼 벌어지면 경고하는 임계. 근거는 CLAUDE.md.
  const DRIFT_WARN = 0.3;

  /** 기준 값 입력란 옆의 "현재 적용값" 표시. 입력한 값을 실제 적용값과 대조하게 한다.
   *  `enabled`(적용 모드)에서 승인 기준이 없으면 계산기는 내장표로 폴백하지 않고 **보류**
   *  하므로, 그 상태를 "적용값"으로 단언하면 안 된다. */
  function renderCurrent(key, current, typed, enabled) {
    const entry = ((current || {}).values || {})[key];
    if (!entry) return '<small>연결된 기준 키를 선택하세요.</small>';
    const blocked = !!enabled && entry.approved == null;
    const baseline = entry.approved == null ? entry.builtin : entry.approved;
    const origin = entry.approved == null
      ? '내장표 (승인된 기준 없음)'
      : `승인 ${esc(entry.effective_from)} ~ ${esc(entry.effective_to || '미지정')}` +
        (entry.citation ? ' · ' + esc(entry.citation) : '');
    let line = blocked
      ? `<small class="legal-warn">적용 모드가 켜져 있고 이 기준은 승인되지 않았습니다 — ` +
        `해당 계산은 <b>보류</b>됩니다(내장표 참고값 ${esc(fmt(baseline))}).</small>`
      : `<small>현재 적용값 <b>${esc(fmt(baseline))}</b> · ${origin}</small>`;
    const value = Number(typed);
    if (String(typed == null ? '' : typed).trim() === '' || !Number.isFinite(value)) return line;
    if (!num(baseline) || baseline === 0) return line + `<small>입력값 ${esc(fmt(value))}</small>`;
    const ratio = (value - baseline) / baseline;
    const shift = `${ratio >= 0 ? '+' : ''}${(ratio * 100).toFixed(1)}%`;
    if (Math.abs(ratio) < 1e-9) return line + '<small>입력값이 현재 적용값과 같습니다.</small>';
    return line + `<small class="${Math.abs(ratio) >= DRIFT_WARN ? 'legal-warn' : ''}">` +
      `입력값 ${esc(fmt(value))} · 현재 대비 ${esc(shift)}` +
      (Math.abs(ratio) >= DRIFT_WARN
        ? ' — 통상 개정폭을 벗어납니다. 요율은 <b>근로자 부담분</b>(법령 전체요율 ÷ 2), 단계 인상은 <b>부칙</b>을 확인하세요.'
        : '') + '</small>';
  }

  /** 그 계산기(topic)에 연결된 기준 키만 고른다. 연결이 하나뿐이면 그것을 돌려준다.
   *
   *  검색 후보는 키가 비어 있어, 그대로 두면 브라우저가 **첫 옵션**을 고른다. 그러면
   *  4대보험 후보 옆에 최저시급 현재값이 뜨고, topic 이 maternity_leave·minimum_wage 면
   *  서버 게이트(topic↔key 연결 검사)마저 통과해 드리프트 경고만 마지막 방어선이 된다. */
  function keysForTopic(parameters, topic) {
    return Object.keys(parameters || {}).filter(
      key => ((parameters[key] || {}).topics || []).indexOf(topic) !== -1);
  }

  /** 자동 검색 후보는 `legal_review` 로 만들어지는데 승인은 `parameter` 만 받는다.
   *  화면에 그 사실이 없어 "검색 → 승인"을 누르면 거절 메시지만 돌아왔다. */
  function scanHint(record) {
    if (!record || record.status !== 'pending' || record.origin !== 'scan' || record.kind !== 'legal_review') return '';
    return '<p class="legal-warn">자동 검색 후보는 <b>이 상태로 승인할 수 없습니다</b> — 검색은 법률 검토 기록만 만듭니다. ' +
      '수치를 계산에 반영하려면 유형을 수치 기준 변경으로 바꾸고 기준 값·시행일·인용구절을 채워 저장하세요. ' +
      '<button type="button" data-action="to-parameter">수치 기준 변경으로 전환</button></p>';
  }

  /** 빈 드롭다운의 이유를 문장으로 만든다. 조회 실패·적재 0건·상한 절단이 화면에서
   *  똑같이 "선택지 없음"으로 보이면 관리자가 없는 원인을 찾게 된다. */
  function documentPlaceholder(documents, detail) {
    if (detail) return '— ' + detail + ' —';
    return (documents || []).length ? '— 공식 원문 선택 —' : '— 목록 조회 전 —';
  }

  /** 문서 목록을 선택한 기준 키 기준으로 정렬한다(연결 문서 우선).
   *  연결이 없는 문서도 남긴다 — 연결 표시는 수집 단계가 붙인 힌트일 뿐이고
   *  확정은 관리자가 원문을 보고 한다. */
  function documentOptions(documents, key) {
    return (Array.isArray(documents) ? documents : [])
      .map(d => ({...d, linked: ((d.rule_keys || []).indexOf(key) !== -1)}))
      .sort((a, b) => (b.linked - a.linked) || String(a.id).localeCompare(String(b.id)));
  }

  function createClient(base, token, fetcher, unauthorized) {
    return async function (method, path, body) {
      const response = await fetcher(base + path, {method,
        headers: {Authorization: 'Bearer ' + token(), 'Content-Type': 'application/json'},
        ...(body === undefined ? {} : {body: JSON.stringify(body)})});
      const data = await response.json().catch(() => ({}));
      if (response.status === 401 && unauthorized) unauthorized();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '입력 또는 서버 연결을 확인하세요.');
      return data;
    };
  }

  function proposalFromFields(fields) {
    let value = null;
    if (fields.kind === 'parameter') {
      // 키를 고르지 않은 채 보내면 서버가 "연결되지 않은 기준 키"로 거절한다. 그보다
      // 어느 칸이 비었는지 여기서 말해주는 편이 낫다.
      if (!String(fields.key || '').trim()) throw new Error('계산 기준(키)을 선택하세요.');
      if (!String(fields.value).trim() || !Number.isFinite(Number(fields.value))) throw new Error('기준 값을 숫자로 입력하세요.');
      value = Number(fields.value);
    }
    return {topic: fields.topic, kind: fields.kind, key: fields.kind === 'parameter' ? fields.key : '', value,
      effective_from: fields.effective_from || null, effective_to: fields.effective_to || null,
      evidence_id: fields.evidence_id, quote: fields.quote, citation: fields.citation, note: fields.note};
  }

  function mount(container, options) {
    const request = createClient(options.base, options.token, options.fetcher || root.fetch.bind(root), options.unauthorized);
    let state = {records: [], scans: [], topics: {}, parameters: {}, revision: 0, current: {values: {}},
                 documents: [], documentsDetail: ''};
    let selected = null;
    let busy = false;
    let generation = 0;
    // 화면에 떠 있는 근거 원문. 인용구절 대조·공백 교정의 기준이라 표시와 같은 것을 써야 한다.
    let shown = null;
    // 목록 응답에서 뺀 저장 근거 원문. sha256 이 같을 때만 재사용한다 —
    // 후보를 수정하면 근거가 교체되므로 옛 원문을 계속 보여주면 안 된다.
    const storedEvidence = new Map();
    const withStoredEvidence = record => {
      if (!record || !record.evidence) return record;
      const cached = storedEvidence.get(record.id);
      return cached && cached.sha256 === record.evidence.sha256 ? {...record, evidence: cached} : record;
    };
    const q = name => container.querySelector('[data-legal="' + name + '"]');
    const field = name => container.querySelector('[data-legal="form"] [name="' + name + '"]');
    const status = message => { q('status').textContent = message; };
    const optionsHtml = (items, current) => Object.entries(items).map(([key, label]) =>
      `<option value="${esc(key)}" ${key === current ? 'selected' : ''}>${esc(label)}</option>`).join('');

    container.innerHTML = `<h2>법률 기준 관리</h2>
      <p>자동 검색은 검토 후보를 만듭니다. 수치 기준은 관리자 승인 후 시행일부터 적용됩니다.</p>
      <p data-legal="mode"></p><p data-legal="progress"></p>
      <p data-legal="status" role="status" aria-live="polite"></p>
      <div class="legal-toolbar"><label>검색 주제 <select data-legal="topic"></select></label>
        <button type="button" data-action="scan">Pinecone 변경 후보 검색</button>
        <button type="button" data-action="reload">새로고침</button>
        <button type="button" data-action="new">수동 등록</button></div>
      <details><summary>최근 검색 실행 / 실패</summary><div data-legal="scans"></div></details>
      <div class="legal-table" data-legal="rows"></div>
      <section data-legal="editor"></section>
      <details><summary>변경 이력</summary><button type="button" data-action="events">이력 조회</button><pre data-legal="events"></pre></details>`;

    function refreshCurrent() {
      const target = q('current');
      if (!target) return;
      const kind = field('kind') ? field('kind').value : 'parameter';
      target.innerHTML = kind === 'parameter'
        ? renderCurrent(field('key').value, state.current, field('value').value, state.enabled)
        : '<small>법률 검토 후보는 계산 값을 바꾸지 않습니다.</small>';
    }

    function refreshDocuments() {
      const picker = q('doc-picker');
      if (!picker) return;
      const current = field('evidence_id').value;
      const items = documentOptions(state.documents, field('key') ? field('key').value : '');
      picker.innerHTML = `<option value="">${esc(documentPlaceholder(state.documents, state.documentsDetail))}</option>` + items.map(d =>
        `<option value="${esc(d.id)}" ${d.id === current ? 'selected' : ''}>` +
        `${d.linked ? '★ ' : ''}${esc(d.title || d.id)} · ${esc(d.id)}</option>`).join('');
      picker.disabled = !items.length;
    }

    function refreshQuote() {
      const target = q('quote-check');
      if (!target) return;
      const value = field('quote').value;
      if (!value.trim()) { target.innerHTML = '<small>근거 원문에서 수치가 적힌 구절을 그대로 옮기세요(8자 이상).</small>'; return; }
      if (!shown || shown.text === undefined || shown.id !== field('evidence_id').value) {
        target.innerHTML = '<small>근거 원문을 조회하면 대조 결과를 표시합니다.</small>'; return;
      }
      const aligned = alignQuote(value, shown.text);
      target.innerHTML = aligned.exact
        ? `<small>원문과 일치합니다${aligned.adjusted ? ' — 저장 시 원문의 공백 표기로 교정됩니다.' : '.'}</small>`
        : '<small class="legal-warn">원문에 없는 구절입니다. 위 근거 원문에서 드래그해 선택한 뒤 “선택 구절 → 인용구절”을 누르세요.</small>';
    }

    function editor(record) {
      selected = record || null;
      const r = record || {kind: 'parameter', topic: q('topic').value || 'minimum_wage', key: 'minimum_hourly_wage'};
      const pending = !record || record.status === 'pending';
      const fields = (name, label, type = 'text') => `<label>${label}<input name="${name}" type="${type}" value="${esc(r[name])}" ${pending ? '' : 'disabled'}></label>`;
      q('editor').innerHTML = `<h3>${record ? '변경 검토' : '수동 후보 등록'}</h3>
        <p>${record ? esc(record.id) + ' · ' + esc(labels[record.status]) : '등록 후 별도 승인 필요'}</p>
        ${scanHint(record)}
        <form data-legal="form"><fieldset ${pending ? '' : 'disabled'}><div class="legal-form-grid">
          <label>영향 계산기<select name="topic">${optionsHtml(state.topics, r.topic)}</select></label>
          <label>유형<select name="kind">${optionsHtml({parameter: '수치 기준 변경', legal_review: '산식·자격 법률 검토'}, r.kind)}</select></label>
          <label>계산 기준<select name="key">${r.key ? '' : '<option value="" selected>— 기준 선택 —</option>'}${optionsHtml(Object.fromEntries(Object.entries(state.parameters).map(([k,v]) => [k, v.label + ' (' + v.unit + ')'])), r.key)}</select></label>
          <label>기준 값 (비율은 0.05 형식)<input name="value" type="number" value="${esc(r.value)}" ${pending ? '' : 'disabled'}>
            <span data-legal="current"></span></label>
          ${fields('effective_from', '시행일', 'date')}${fields('effective_to', '종료일 (해당일 제외)', 'date')}
          <label>공식 원문 선택<select data-legal="doc-picker"></select></label>
          ${fields('evidence_id', 'Pinecone 문서 ID')}${fields('citation', '조문·판례·고시 번호')}
          <label class="legal-wide">원문 인용구절<textarea name="quote" maxlength="10000">${esc(r.quote)}</textarea>
            <span data-legal="quote-check"></span></label>
          <label class="legal-wide">등록 메모<textarea name="note" maxlength="2000">${esc(r.note)}</textarea></label>
        </div><button type="button" data-action="evidence">근거 원문 조회</button>
        <button type="button" data-action="quote-from-selection">선택 구절 → 인용구절</button>
        <button type="submit">${record ? '후보 수정 저장' : '후보 등록'}</button></fieldset></form>
        <div data-legal="evidence">${renderEvidence(r.evidence)}</div>
        <p>같은 기준의 승인 기간은 겹칠 수 없습니다. 값·인용구절·시행일의 관계는 관리자가 원문과 대조합니다.</p>
        <p>판례/행정지침의 산식·자격 변경은 개발 검토가 필요합니다. 검토 기록만으로 계산 코드가 바뀌지 않습니다.</p>
        <div data-legal="actions">${record ? `<label>검토/처리 사유<textarea data-legal="review-note" maxlength="2000">${esc(r.review_note)}</textarea></label>
          ${pending ? (r.kind === 'parameter' ? '<button type="button" data-action="approve">저장된 후보 승인</button>' : '<button type="button" data-action="reviewed">코드 검토 기록</button>') + '<button type="button" data-action="reject">반려</button>' : ''}
          ${record.status === 'approved' ? '<button type="button" data-action="revoke">승인 취소</button>' : ''}
          <button type="button" data-action="clone">이 값으로 새 버전 등록</button>` : ''}</div>`;
      field('value').step = 'any';
      shown = r.evidence || null;
      refreshCurrent();
      refreshDocuments();
      refreshQuote();
    }

    async function reload() {
      const current = ++generation;
      const data = await request('GET', '');
      if (current !== generation) return;
      state = {...data, documents: state.documents, documentsDetail: state.documentsDetail};
      q('mode').textContent = data.enabled ? '승인 기준 적용 모드: 켜짐. 개별 산식 감사 상태는 별도입니다.' : '승인 기준 적용 모드: 꺼짐. 현재 계산은 기존 코드 기준을 사용합니다.';
      const progress = state.current || {};
      // 적용 모드를 켜기 전에 11개 키가 오늘 구간으로 모두 승인돼 있어야 한다 —
      // 하나라도 비면 그 계산이 통째로 보류된다(보험 8키는 한 번에 요구된다).
      q('progress').textContent = `오늘(${progress.as_of || '-'}) 기준 승인된 기준 ${progress.approved_count || 0}/${progress.total || 0}건` +
        ((progress.approved_count || 0) < (progress.total || 0)
          ? ' — 전부 승인되기 전에 적용 모드를 켜면 해당 계산이 보류됩니다.' : '');
      const topic = q('topic').value;
      q('topic').innerHTML = optionsHtml(state.topics, topic);
      q('rows').innerHTML = renderRows([...state.records].reverse());
      q('scans').innerHTML = state.scans.slice(-28).reverse().map(s => `<p>${esc(s.searched_at)} · ${esc(state.topics[s.topic])} · ${esc(scanStatusLabel(s.status))} · 후보 ${esc(s.new_count)}건</p>`).join('') || '<p>검색 이력 없음</p>';
      if (selected) editor(withStoredEvidence(state.records.find(r => r.id === selected.id)));
      else editor(null);
      // 공식 원문 목록은 한 번만 받는다. 실패해도 문서 ID 직접 입력으로 계속 쓸 수 있어야
      // 하므로 여기서 예외를 삼킨다 — 목록 없이 화면이 멈추면 개선이 아니라 후퇴다.
      if (!state.documents.length) {
        try {
          const catalog = await request('GET', '/documents');
          state.documents = catalog.documents || [];
          state.documentsDetail = catalog.detail || '';
        } catch (error) {
          state.documentsDetail = '공식 원문 목록을 불러오지 못했습니다. 문서 ID를 직접 입력하세요.';
        }
        refreshDocuments();
        if (state.documentsDetail) status(state.documentsDetail);
      }
    }

    async function run(operation) {
      if (busy) return;
      busy = true;
      container.setAttribute('aria-busy', 'true');
      status('처리 중…');
      try { await operation(); }
      catch (error) { status(error.message); }
      finally { busy = false; container.setAttribute('aria-busy', 'false'); }
    }

    function showEvidence(evidence) {
      shown = evidence;
      q('evidence').innerHTML = renderEvidence(evidence);
      refreshQuote();
    }

    // 버튼을 누르는 순간 선택이 풀리면 이 기능은 **항상** "먼저 선택하세요"만 낸다.
    // Chrome 에서는 실측상 선택이 유지되지만(실제 드래그 + 실제 클릭으로 확인), 선택 영역
    // 바깥의 mousedown 에서 선택을 collapse 하는 엔진이 있어 리치텍스트 툴바가 쓰는 관용구를
    // 그대로 둔다. 포커스만 막을 뿐 click 은 정상 발생한다.
    container.addEventListener('mousedown', event => {
      if (event.target.closest('[data-action="quote-from-selection"]')) event.preventDefault();
    });

    container.addEventListener('input', event => {
      if (!event.target.name) return;
      if (event.target.name === 'value') refreshCurrent();
      if (event.target.name === 'quote') refreshQuote();
    });

    container.addEventListener('change', event => {
      if (event.target === q('doc-picker')) {
        if (!event.target.value) return;
        field('evidence_id').value = event.target.value;
        const picked = state.documents.find(d => d.id === event.target.value);
        if (picked) showEvidence(picked);
        return;
      }
      if (event.target.name === 'key') { refreshCurrent(); refreshDocuments(); }
      if (event.target.name === 'kind') refreshCurrent();
      if (event.target.name === 'evidence_id') refreshQuote();
    });

    container.addEventListener('submit', event => {
      if (event.target !== q('form')) return;
      event.preventDefault();
      run(async () => {
        const payload = proposalFromFields(Object.fromEntries(new FormData(event.target)));
        let adjusted = false;
        if (shown && shown.text !== undefined && shown.id === payload.evidence_id) {
          const aligned = alignQuote(payload.quote, shown.text);
          adjusted = aligned.adjusted;
          if (aligned.exact) payload.quote = aligned.quote;
        }
        const response = await request(selected ? 'PUT' : 'POST', '/candidates' + (selected ? '/' + encodeURIComponent(selected.id) : ''), {revision: state.revision, payload});
        selected = response.record;
        if (response.record.evidence) storedEvidence.set(response.record.id, response.record.evidence);
        await reload();
        status('후보가 저장되었습니다. 원문과 적용일 검토 후 승인하세요.' +
          (adjusted ? ' 인용구절의 공백을 저장 원문 표기에 맞춰 교정했습니다.' : ''));
      });
    });

    container.addEventListener('click', event => {
      const button = event.target.closest('[data-action]');
      if (!button || !container.contains(button) || busy) return;
      const action = button.dataset.action;
      if (action === 'select') {
        const id = button.dataset.id;
        editor(withStoredEvidence(state.records.find(r => r.id === id)));
        if (selected && selected.evidence && selected.evidence.text === undefined) {
          run(async () => {
            const result = await request('GET', '/candidates/' + encodeURIComponent(id));
            storedEvidence.set(id, result.record.evidence);
            if (selected && selected.id === id) {
              selected = result.record;
              showEvidence(result.record.evidence);
            }
            status('저장된 근거 원문을 불러왔습니다.');
          });
        }
        return;
      }
      if (action === 'new') { editor(null); return; }
      if (action === 'to-parameter') {
        // 검색 후보를 승인 가능한 형태로 바꾼다. 값·시행일·인용구절은 사람이 채운다 —
        // 수치 추출을 자동화하면 잘못된 기준(전체요율 등)을 그대로 집어넣는다.
        field('kind').value = 'parameter';
        // 키는 **추측하지 않는다**. 이 계산기에 연결된 기준이 하나뿐일 때만 골라준다.
        const candidates = keysForTopic(state.parameters, field('topic').value);
        if (candidates.length === 1) field('key').value = candidates[0];
        refreshCurrent();
        refreshDocuments();
        field('value').focus();
        status(candidates.length === 1
          ? '유형을 수치 기준 변경으로 바꾸고 계산 기준을 선택했습니다. 기준 값·시행일·인용구절을 채워 저장하세요.'
          : '유형을 수치 기준 변경으로 바꿨습니다. 계산 기준을 직접 고르고 기준 값·시행일·인용구절을 채워 저장하세요.');
        return;
      }
      if (action === 'quote-from-selection') {
        const selection = String(root.getSelection ? root.getSelection() : '').trim();
        if (!selection) { status('근거 원문에서 인용할 구절을 먼저 드래그해 선택하세요.'); return; }
        const aligned = alignQuote(selection, (shown || {}).text);
        field('quote').value = aligned.quote;
        refreshQuote();
        status(aligned.exact ? '선택한 구절을 인용구절로 옮겼습니다.'
          : '선택한 구절이 조회된 근거 원문에 없습니다. 근거 원문 창 안에서 선택하세요.');
        return;
      }
      if (action === 'clone' && selected) {
        const previous = selected;
        editor(null);
        for (const name of ['topic', 'kind', 'key', 'value', 'effective_from', 'effective_to', 'evidence_id', 'quote', 'citation', 'note']) {
          field(name).value = previous[name] == null ? '' : previous[name];
        }
        showEvidence(previous.evidence);
        refreshCurrent();
        refreshDocuments();
        status('이전 값을 복사했습니다. 시행기간을 확인하고 새 후보로 등록하세요. 별도 승인이 필요합니다.');
        return;
      }
      run(async () => {
        if (action === 'reload') { await reload(); status('갱신했습니다.'); }
        else if (action === 'scan') {
          const result = await request('POST', '/scan', {topic: q('topic').value});
          await reload();
          status(result.status === 'failed' ? '검색에 실패했습니다. 연결 상태를 확인하세요.'
            : result.status === 'partial' ? `일반 검색 ${result.hit_count}건을 보존했지만 공식 원문 조회에 실패했습니다. 새 후보 ${result.new_count}건을 신뢰하기 전에 재검색하세요.`
            : `검색 결과 ${result.hit_count}건, 새 후보 ${result.new_count}건. 법률 검토 기록으로 만들어지므로, 수치를 반영하려면 후보를 열어 수치 기준 변경으로 전환하세요.`);
        } else if (action === 'evidence') {
          const id = field('evidence_id').value;
          const result = await request('GET', '/evidence?id=' + encodeURIComponent(id));
          showEvidence(result.evidence);
          status('원문을 조회했습니다.');
        } else if (action === 'events') {
          const result = await request('GET', '/events');
          q('events').textContent = result.events.map(e => `${e.created_at} · #${e.revision} · ${e.actor}\n${JSON.stringify(e.action)}`).join('\n\n') || '변경 이력 없음';
          status('이력을 조회했습니다.');
        } else if (selected && ['approve', 'reject', 'revoke', 'reviewed'].includes(action)) {
          const note = q('review-note').value;
          if (action === 'approve' && !root.confirm(approvalPrompt(selected, state.current))) { status('승인을 취소했습니다.'); return; }
          if (action === 'revoke' && !root.confirm('승인을 취소하면 해당 기간의 계산이 보류될 수 있습니다. 취소하시겠습니까?')) { status('변경하지 않았습니다.'); return; }
          await request('POST', '/candidates/' + encodeURIComponent(selected.id) + '/' + action, {revision: state.revision, note});
          await reload();
          status('처리 내용을 저장했습니다.');
        }
      });
    });
    run(reload);
    return {reload: () => run(reload)};
  }

  /** 승인 직전 확인 문구. **저장된 값과 현재값을 나란히 보여준다** — 지금까지는
   *  "대조했습니까?"만 물어 무엇을 대조하는지가 화면에 없었다. */
  function approvalPrompt(record, current) {
    const entry = ((current || {}).values || {})[record.key] || {};
    const baseline = entry.approved == null ? entry.builtin : entry.approved;
    return `${record.key}: ${fmt(record.value)} 로 승인합니다.\n` +
      `현재 적용값 ${fmt(baseline)} (${entry.approved == null ? '내장표' : '승인'})\n` +
      `적용기간 ${record.effective_from} ~ ${record.effective_to || '미지정'}\n\n` +
      '저장된 값·시행일·인용구절을 공식 원문과 대조했습니까? 저장하지 않은 폼 변경은 적용되지 않습니다.';
  }

  const api = {renderRows, renderEvidence, createClient, proposalFromFields, scanStatusLabel,
    alignQuote, renderCurrent, scanHint, keysForTopic, documentOptions, documentPlaceholder,
    approvalPrompt, mount};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.LegalRules = api;
})(typeof window !== 'undefined' ? window : globalThis);
