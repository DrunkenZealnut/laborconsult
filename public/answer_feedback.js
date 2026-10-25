/* Voluntary per-answer feedback. Signed tokens remain in the page closure. */
(function (root) {
  'use strict';
  function render(el, event, sessionId, env) {
    if (!el || !event || !event.token || !sessionId) return;
    env = env || root;
    var doc = env.document;
    var box = doc.createElement('div');
    box.className = 'answer-feedback';
    box.setAttribute('aria-label', '답변 도움 평가');
    var status = doc.createElement('span');
    status.setAttribute('role', 'status');
    var reasons = doc.createElement('div');
    reasons.className = 'feedback-reasons';
    reasons.hidden = true;
    var exposed = false;
    var pendingExposure = null;
    var busy = false;
    async function send(kind, positive, reason) {
      var resp = await env.fetch('/api/answer-feedback', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({token: event.token, session_id: sessionId, kind: kind,
                              positive: positive, reason: reason})
      });
      if (!resp.ok) throw new Error('feedback unavailable');
    }
    async function expose() {
      if (exposed) return;
      if (!pendingExposure) pendingExposure = send('exposure', null, null).then(function () {
        exposed = true;
      }).finally(function () { pendingExposure = null; });
      return pendingExposure;
    }
    async function vote(positive, reason) {
      if (busy) return;
      busy = true;
      box.querySelectorAll('button').forEach(function (b) { b.disabled = true; });
      try {
        await expose();
        await send('vote', positive, reason);
        status.textContent = '의견을 저장했습니다.';
        reasons.hidden = true;
      } catch (_) {
        status.textContent = '의견을 저장하지 못했습니다. 잠시 후 다시 시도해주세요.';
      } finally {
        busy = false;
        box.querySelectorAll('button').forEach(function (b) { b.disabled = false; });
      }
    }
    function button(label, action, parent) {
      var b = doc.createElement('button'); b.type = 'button'; b.textContent = label;
      b.addEventListener('click', action); (parent || box).appendChild(b); return b;
    }
    button('도움이 됐어요', function () { return vote(true, null); });
    button('도움이 안 됐어요', function () { reasons.hidden = !reasons.hidden; });
    [['법률·계산 오류', 'legal_calculation_error'], ['설명이 어려움', 'unclear'],
     ['필요한 답이 없음', 'missing_answer'], ['기타', 'other']].forEach(function (pair) {
      button(pair[0], function () { return vote(false, pair[1]); }, reasons);
    });
    box.appendChild(reasons); box.appendChild(status);
    el.insertAdjacentElement('afterend', box);
    expose().catch(function () { /* A later vote retries the exposure receipt. */ });
  }
  var api = {render: render};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.answerFeedback = api;
})(typeof window !== 'undefined' ? window : globalThis);
