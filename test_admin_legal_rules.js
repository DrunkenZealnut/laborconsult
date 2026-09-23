const test = require('node:test');
const assert = require('node:assert/strict');
const {renderRows, renderEvidence, createClient, proposalFromFields, scanStatusLabel,
  alignQuote, renderCurrent, scanHint, keysForTopic, documentOptions, documentPlaceholder,
  approvalPrompt} = require('./public/admin_legal_rules.js');

test('untrusted evidence and candidate values are escaped and unsafe links removed', () => {
  const attack = '<img src=x onerror=alert(1)>';
  const html = renderRows([{id: attack, status: 'pending', topic: attack, kind: 'legal_review',
    evidence: {title: attack}, citation: attack}]) + renderEvidence({text: attack, title: attack, url: 'javascript:alert(1)'});
  assert.doesNotMatch(html, /<img|javascript:|onerror="/);
  assert.match(html, /&lt;img/);
});

test('state labels distinguish pending, approved, revoked and code review', () => {
  const html = renderRows(['pending', 'approved', 'revoked', 'reviewed'].map((status, i) =>
    ({id: String(i), status, topic: 'minimum_wage', kind: 'parameter', value: 12345,
      key: 'minimum_hourly_wage', effective_from: '2031-01-01', effective_to: '2032-01-01', evidence: {}})));
  for (const label of ['검토 대기', '승인', '승인 취소', '코드 검토 기록']) assert.ok(html.includes(label), label);
  assert.match(html, /2031-01-01/);
});

test('client sends bearer and optimistic revision, encodes IDs, and surfaces conflicts', async () => {
  const requests = [];
  const client = createClient('/api/admin/legal-rules', () => 'token', async (url, init) => {
    requests.push({url, init});
    return {ok: false, status: 409, json: async () => ({detail: '새로고침 필요'})};
  });
  await assert.rejects(client('POST', '/candidates/' + encodeURIComponent('id/a') + '/approve',
    {revision: 2, note: '검토 확인'}), /새로고침 필요/);
  assert.equal(requests[0].init.headers.Authorization, 'Bearer token');
  assert.equal(JSON.parse(requests[0].init.body).revision, 2);
  assert.match(requests[0].url, /id%2Fa/);
});

test('numeric form rejects blank, nonfinite and invalid values before submission', () => {
  const fields = {kind: 'parameter', topic: 'minimum_wage', key: 'minimum_hourly_wage', value: '',
    effective_from: '2031-01-01', effective_to: '2032-01-01', evidence_id: 'x', quote: '원문', citation: '고시', note: ''};
  for (const value of ['', 'Infinity', 'not-a-number']) {
    assert.throws(() => proposalFromFields({...fields, value}));
  }
  assert.equal(proposalFromFields({...fields, value: '12345'}).value, 12345);
  const review = proposalFromFields({...fields, kind: 'legal_review', key: 'ignored'});
  assert.equal(review.value, null);
  assert.equal(review.key, '');
});

test('partial search status tells the administrator official evidence lookup failed', () => {
  assert.match(scanStatusLabel('partial'), /공식 원문 조회 실패/);
  assert.equal(scanStatusLabel('completed'), '검색 완료');
});

// 고시 본문은 PDF 추출물이라 낱말 사이 공백이 없다. 웹 화면에서 복사한 정확한 인용이
// `quote in evidence["text"]` 에 걸려 거절되던 것이 승인 실패의 최다 원인이었다.
test('quote alignment restores the stored text spacing instead of rejecting the copy', () => {
  const stored = '가. 모든산업 10,320원';
  assert.deepEqual(alignQuote('모든 산업 10,320원', stored),
    {quote: '모든산업 10,320원', exact: true, adjusted: true});
  assert.deepEqual(alignQuote('모든산업 10,320원', stored),
    {quote: '모든산업 10,320원', exact: true, adjusted: false});
  assert.equal(alignQuote('없는 구절', stored).exact, false);
  assert.equal(alignQuote('  ', stored).quote, '');
});

// 게이트는 출처만 검증하고 값 자체는 보지 않는다 — 전체요율(근로자분의 2배)과
// 조문 본문의 최종연도 값이 실제로 승인을 통과했다. 이 표시가 유일한 대조 장치다.
test('current value panel shows the applied baseline and flags out-of-range input', () => {
  const current = {values: {
    'insurance.health_insurance': {builtin: 0.03595, approved: null},
    minimum_hourly_wage: {builtin: 10030, approved: 10320, effective_from: '2026-01-01',
      effective_to: '2027-01-01', citation: '고용노동부고시 제2025-47호'},
  }};
  const doubled = renderCurrent('insurance.health_insurance', current, '0.0719');
  assert.match(doubled, /현재 적용값 <b>0\.03595<\/b>/);
  assert.match(doubled, /legal-warn/);
  assert.match(doubled, /근로자 부담분/);
  // 승인값이 있으면 내장표가 아니라 승인값이 기준이고, 통상 개정폭은 경고하지 않는다.
  const normal = renderCurrent('minimum_hourly_wage', current, '10700');
  assert.match(normal, /현재 적용값 <b>10,320<\/b>/);
  assert.match(normal, /고용노동부고시 제2025-47호/);
  assert.doesNotMatch(normal, /legal-warn/);
  assert.match(renderCurrent('unknown.key', current, ''), /연결된 기준 키/);
});

// 적용 모드에서 승인 기준이 없으면 계산기는 내장표로 폴백하지 않고 보류한다.
// 그 상태를 "현재 적용값"으로 단언하면 대조 장치가 거짓말을 한다.
test('current value panel says blocked, not applied, when managed mode lacks approval', () => {
  const current = {values: {minimum_hourly_wage: {builtin: 10320, approved: null}}};
  const managed = renderCurrent('minimum_hourly_wage', current, '', true);
  assert.match(managed, /보류/);
  assert.match(managed, /legal-warn/);
  assert.doesNotMatch(managed, /현재 적용값/);
  assert.match(renderCurrent('minimum_hourly_wage', current, '', false), /현재 적용값/);
  // 승인이 있으면 적용 모드여도 그 값이 실제 적용값이다.
  const approved = {values: {minimum_hourly_wage: {builtin: 10030, approved: 10320,
    effective_from: '2026-01-01', effective_to: null, citation: '고시'}}};
  assert.match(renderCurrent('minimum_hourly_wage', approved, '', true), /현재 적용값/);
});

// 검색 후보는 key 가 비어 있어, 그대로 두면 브라우저가 첫 옵션(최저시급)을 고른다.
// topic 이 maternity_leave·minimum_wage 면 서버의 topic↔key 검사마저 통과한다.
test('key candidates are scoped to the topic so conversion cannot assert a wrong key', () => {
  const parameters = {
    minimum_hourly_wage: {topics: ['minimum_wage', 'maternity_leave']},
    'maternity.monthly_upper': {topics: ['maternity_leave']},
    'insurance.national_pension': {topics: ['insurance', 'employer_insurance']},
  };
  assert.deepEqual(keysForTopic(parameters, 'insurance'), ['insurance.national_pension']);
  assert.equal(keysForTopic(parameters, 'maternity_leave').length, 2, '둘이면 자동 선택하지 않는다');
  assert.deepEqual(keysForTopic(parameters, 'severance'), []);
  assert.deepEqual(keysForTopic(undefined, 'insurance'), []);
});

test('numeric proposals name the missing key instead of letting the server reject it', () => {
  assert.throws(() => proposalFromFields({kind: 'parameter', topic: 'insurance', key: '',
    value: '0.0475', effective_from: '2026-07-01', evidence_id: 'x', quote: 'q', citation: 'c'}),
    /계산 기준/);
});

test('scan candidates say they cannot be approved as-is and offer the conversion', () => {
  const scanned = {status: 'pending', origin: 'scan', kind: 'legal_review'};
  assert.match(scanHint(scanned), /이 상태로 승인할 수 없습니다/);
  assert.match(scanHint(scanned), /data-action="to-parameter"/);
  assert.equal(scanHint({...scanned, kind: 'parameter'}), '');
  assert.equal(scanHint({...scanned, status: 'approved'}), '');
  assert.equal(scanHint(null), '');
});

test('official document picker puts key-linked sources first but keeps the rest', () => {
  const documents = [{id: 'official_np_act_88_0', rule_keys: []},
    {id: 'official_mw_notice_0', rule_keys: ['minimum_hourly_wage']}];
  const sorted = documentOptions(documents, 'minimum_hourly_wage');
  assert.equal(sorted[0].id, 'official_mw_notice_0');
  assert.equal(sorted[0].linked, true);
  assert.equal(sorted.length, 2, '연결 힌트가 없는 문서도 선택 가능해야 한다');
  assert.deepEqual(documentOptions(undefined, 'x'), []);
});

// 조회 실패 / 적재 0건 / 상한 절단이 전부 "빈 드롭다운"으로 보이면 관리자가 없는 원인을 찾는다.
test('empty document picker explains why instead of just being disabled', () => {
  assert.match(documentPlaceholder([], '공식 원문 목록을 불러오지 못했습니다. 문서 ID를 직접 입력하세요.'),
    /불러오지 못했습니다/);
  assert.match(documentPlaceholder([], '적재된 공식 원문이 없습니다.'), /적재된 공식 원문이 없습니다/);
  assert.match(documentPlaceholder([{id: 'a'}], ''), /공식 원문 선택/);
});

test('approval confirmation states the value being approved next to the current one', () => {
  const prompt = approvalPrompt({key: 'minimum_hourly_wage', value: 10700,
    effective_from: '2027-01-01', effective_to: null},
    {values: {minimum_hourly_wage: {builtin: 10320, approved: null}}});
  assert.match(prompt, /10,700/);
  assert.match(prompt, /현재 적용값 10,320 \(내장표\)/);
  assert.match(prompt, /2027-01-01/);
});
