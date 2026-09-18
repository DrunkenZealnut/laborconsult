const test = require('node:test');
const assert = require('node:assert/strict');
const {renderRows, renderEvidence, createClient, proposalFromFields, scanStatusLabel} = require('./public/admin_legal_rules.js');

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
