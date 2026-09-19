(function (root) {
  'use strict';
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g,
    c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const labels = {pending: '검토 대기', approved: '승인', rejected: '반려', revoked: '승인 취소', reviewed: '코드 검토 기록'};
  const scanLabels = {completed: '검색 완료', partial: '부분 검색 — 공식 원문 조회 실패', empty: '검색 결과 없음', failed: '검색 실패'};
  const scanStatusLabel = status => scanLabels[status] || status;

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
      if (!String(fields.value).trim() || !Number.isFinite(Number(fields.value))) throw new Error('기준 값을 숫자로 입력하세요.');
      value = Number(fields.value);
    }
    return {topic: fields.topic, kind: fields.kind, key: fields.kind === 'parameter' ? fields.key : '', value,
      effective_from: fields.effective_from || null, effective_to: fields.effective_to || null,
      evidence_id: fields.evidence_id, quote: fields.quote, citation: fields.citation, note: fields.note};
  }

  function mount(container, options) {
    const request = createClient(options.base, options.token, options.fetcher || root.fetch.bind(root), options.unauthorized);
    let state = {records: [], scans: [], topics: {}, parameters: {}, revision: 0};
    let selected = null;
    let busy = false;
    let generation = 0;
    // 목록 응답에서 뺀 저장 근거 원문. sha256 이 같을 때만 재사용한다 —
    // 후보를 수정하면 근거가 교체되므로 옛 원문을 계속 보여주면 안 된다.
    const storedEvidence = new Map();
    const withStoredEvidence = record => {
      if (!record || !record.evidence) return record;
      const cached = storedEvidence.get(record.id);
      return cached && cached.sha256 === record.evidence.sha256 ? {...record, evidence: cached} : record;
    };
    const q = name => container.querySelector('[data-legal="' + name + '"]');
    const status = message => { q('status').textContent = message; };
    const optionsHtml = (items, current) => Object.entries(items).map(([key, label]) =>
      `<option value="${esc(key)}" ${key === current ? 'selected' : ''}>${esc(label)}</option>`).join('');

    container.innerHTML = `<h2>법률 기준 관리</h2>
      <p>자동 검색은 검토 후보를 만듭니다. 수치 기준은 관리자 승인 후 시행일부터 적용됩니다.</p>
      <p data-legal="mode"></p><p data-legal="status" role="status" aria-live="polite"></p>
      <div class="legal-toolbar"><label>검색 주제 <select data-legal="topic"></select></label>
        <button type="button" data-action="scan">Pinecone 변경 후보 검색</button>
        <button type="button" data-action="reload">새로고침</button>
        <button type="button" data-action="new">수동 등록</button></div>
      <details><summary>최근 검색 실행 / 실패</summary><div data-legal="scans"></div></details>
      <div class="legal-table" data-legal="rows"></div>
      <section data-legal="editor"></section>
      <details><summary>변경 이력</summary><button type="button" data-action="events">이력 조회</button><pre data-legal="events"></pre></details>`;

    function editor(record) {
      selected = record || null;
      const r = record || {kind: 'parameter', topic: q('topic').value || 'minimum_wage', key: 'minimum_hourly_wage'};
      const pending = !record || record.status === 'pending';
      const fields = (name, label, type = 'text') => `<label>${label}<input name="${name}" type="${type}" value="${esc(r[name])}" ${pending ? '' : 'disabled'}></label>`;
      q('editor').innerHTML = `<h3>${record ? '변경 검토' : '수동 후보 등록'}</h3>
        <p>${record ? esc(record.id) + ' · ' + esc(labels[record.status]) : '등록 후 별도 승인 필요'}</p>
        <form data-legal="form"><fieldset ${pending ? '' : 'disabled'}><div class="legal-form-grid">
          <label>영향 계산기<select name="topic">${optionsHtml(state.topics, r.topic)}</select></label>
          <label>유형<select name="kind">${optionsHtml({parameter: '수치 기준 변경', legal_review: '산식·자격 법률 검토'}, r.kind)}</select></label>
          <label>계산 기준<select name="key">${optionsHtml(Object.fromEntries(Object.entries(state.parameters).map(([k,v]) => [k, v.label + ' (' + v.unit + ')'])), r.key)}</select></label>
          ${fields('value', '기준 값 (비율은 0.05 형식)', 'number')}
          ${fields('effective_from', '시행일', 'date')}${fields('effective_to', '종료일 (해당일 제외)', 'date')}
          ${fields('evidence_id', 'Pinecone 문서 ID')}${fields('citation', '조문·판례·고시 번호')}
          <label class="legal-wide">원문 인용구절<textarea name="quote" maxlength="10000">${esc(r.quote)}</textarea></label>
          <label class="legal-wide">등록 메모<textarea name="note" maxlength="2000">${esc(r.note)}</textarea></label>
        </div><button type="button" data-action="evidence">근거 원문 조회</button>
        <button type="submit">${record ? '후보 수정 저장' : '후보 등록'}</button></fieldset></form>
        <div data-legal="evidence">${renderEvidence(r.evidence)}</div>
        <p>같은 기준의 승인 기간은 겹칠 수 없습니다. 값·인용구절·시행일의 관계는 관리자가 원문과 대조합니다.</p>
        <p>판례/행정지침의 산식·자격 변경은 개발 검토가 필요합니다. 검토 기록만으로 계산 코드가 바뀌지 않습니다.</p>
        <div data-legal="actions">${record ? `<label>검토/처리 사유<textarea data-legal="review-note" maxlength="2000">${esc(r.review_note)}</textarea></label>
          ${pending ? (r.kind === 'parameter' ? '<button type="button" data-action="approve">저장된 후보 승인</button>' : '<button type="button" data-action="reviewed">코드 검토 기록</button>') + '<button type="button" data-action="reject">반려</button>' : ''}
          ${record.status === 'approved' ? '<button type="button" data-action="revoke">승인 취소</button>' : ''}
          <button type="button" data-action="clone">이 값으로 새 버전 등록</button>` : ''}</div>`;
      const valueInput = q('form').querySelector('[name="value"]');
      valueInput.step = 'any';
    }

    async function reload() {
      const current = ++generation;
      const data = await request('GET', '');
      if (current !== generation) return;
      state = data;
      q('mode').textContent = data.enabled ? '승인 기준 적용 모드: 켜짐. 개별 산식 감사 상태는 별도입니다.' : '승인 기준 적용 모드: 꺼짐. 현재 계산은 기존 코드 기준을 사용합니다.';
      const topic = q('topic').value;
      q('topic').innerHTML = optionsHtml(state.topics, topic);
      q('rows').innerHTML = renderRows([...state.records].reverse());
      q('scans').innerHTML = state.scans.slice(-28).reverse().map(s => `<p>${esc(s.searched_at)} · ${esc(state.topics[s.topic])} · ${esc(scanStatusLabel(s.status))} · 후보 ${esc(s.new_count)}건</p>`).join('') || '<p>검색 이력 없음</p>';
      if (selected) editor(withStoredEvidence(state.records.find(r => r.id === selected.id)));
      else editor(null);
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

    container.addEventListener('submit', event => {
      if (event.target !== q('form')) return;
      event.preventDefault();
      run(async () => {
        const payload = proposalFromFields(Object.fromEntries(new FormData(event.target)));
        const response = await request(selected ? 'PUT' : 'POST', '/candidates' + (selected ? '/' + encodeURIComponent(selected.id) : ''), {revision: state.revision, payload});
        selected = response.record;
        if (response.record.evidence) storedEvidence.set(response.record.id, response.record.evidence);
        await reload();
        status('후보가 저장되었습니다. 원문과 적용일 검토 후 승인하세요.');
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
              q('evidence').innerHTML = renderEvidence(result.record.evidence);
            }
            status('저장된 근거 원문을 불러왔습니다.');
          });
        }
        return;
      }
      if (action === 'new') { editor(null); return; }
      if (action === 'clone' && selected) {
        const previous = selected;
        editor(null);
        for (const name of ['topic', 'kind', 'key', 'value', 'effective_from', 'effective_to', 'evidence_id', 'quote', 'citation', 'note']) {
          q('form').querySelector('[name="' + name + '"]').value = previous[name] == null ? '' : previous[name];
        }
        q('evidence').innerHTML = renderEvidence(previous.evidence);
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
            : `검색 결과 ${result.hit_count}건, 새 후보 ${result.new_count}건. 개정 여부를 검토하세요.`);
        } else if (action === 'evidence') {
          const id = q('form').querySelector('[name="evidence_id"]').value;
          const result = await request('GET', '/evidence?id=' + encodeURIComponent(id));
          q('evidence').innerHTML = renderEvidence(result.evidence);
          status('원문을 조회했습니다.');
        } else if (action === 'events') {
          const result = await request('GET', '/events');
          q('events').textContent = result.events.map(e => `${e.created_at} · #${e.revision} · ${e.actor}\n${JSON.stringify(e.action)}`).join('\n\n') || '변경 이력 없음';
          status('이력을 조회했습니다.');
        } else if (selected && ['approve', 'reject', 'revoke', 'reviewed'].includes(action)) {
          const note = q('review-note').value;
          if (action === 'approve' && !root.confirm('저장된 값·시행일·인용구절을 공식 원문과 대조했습니까? 저장하지 않은 폼 변경은 적용되지 않습니다.')) { status('승인을 취소했습니다.'); return; }
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

  const api = {renderRows, renderEvidence, createClient, proposalFromFields, scanStatusLabel, mount};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.LegalRules = api;
})(typeof window !== 'undefined' ? window : globalThis);
