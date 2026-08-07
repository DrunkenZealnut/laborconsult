/* 답변 조망·탐색 레이어 — index.html / board.html 공유 (answer-at-a-glance)
 *
 * 완성된 답변 DOM에만 적용하는 순수 후처리다. 하는 일 셋.
 *   1) 섹션 목차(h2 칩) 생성 — 클릭하면 해당 섹션으로 스크롤한다. 목차는 sticky라
 *      스크롤 중에도 계속 보이고, 첫 칩이 "핵심 답변"이므로 결론으로 되돌아가는
 *      경로가 항상 열려 있다(FR-1과 FR-3을 한 장치로 겸한다 — design D8 참고).
 *   2) 길고 부차적인 섹션(법적 근거 원문·판례 요지·상세 절차)을 <details>로 접는다.
 *      핵심 답변·결론·주의사항은 절대 접지 않는다.
 *   3) 목차 칩으로 접힌 섹션에 점프하면 자동으로 펼친다.
 *
 * 왜 h2 태그만 근거로 동작하나: board.html은 index.html의 md()를 쓰지 않고
 * marked.parse()만 쓴다(콜아웃·요약배지 클래스가 없다). 태그만 보면 같은 코드가
 * 양쪽에서 그대로 돈다.
 *
 * 원문 마크다운(dataset.md)은 건드리지 않는다 — 복사·마크다운 저장이 그 값을 쓴다.
 * 어떤 실패도 답변 표시를 막지 않는다.
 */
(function (global) {
  'use strict';

  // 목차는 헤딩 2개부터. 3개로 잡으면 법률상담 답변(프롬프트가 핵심답변+절차만
  // 헤딩으로 허용)에서 사실상 발동하지 않는다 — design §1.2 실측.
  var MIN_HEADINGS = 2;
  // 짧은 섹션까지 접으면 클릭만 늘어난다. 접힘이 정보 은닉으로 오해되지 않게 하는 하한.
  var MIN_COLLAPSE_LEN = 200;
  var HINT_LEN = 60;

  // 텍스트 매칭이라 클래스 유무와 무관하게 양쪽 페이지에서 동일하게 방어된다.
  var ALWAYS_OPEN = [
    /핵심\s*답변/, /결론/, /답변\s*요약/, /요약/, /주의\s*사항/, /면책/
  ];
  var COLLAPSIBLE = [
    /^법적\s*근거/, /^관련\s*법조문/, /^관련\s*법률/, /^법령/,
    /^관련\s*판례/, /^판례/, /^행정해석/,
    /^절차/, /^신청\s*방법/, /^대응\s*방법/,
    /^산출\s*근거/, /^계산\s*과정/, /^계산\s*근거/
  ];

  function matches(list, text) {
    for (var i = 0; i < list.length; i++) {
      if (list[i].test(text)) return true;
    }
    return false;
  }

  function norm(s) {
    return (s || '').replace(/\s+/g, ' ').trim();
  }

  /* 섹션 종료 마커 — heading 이 아닌데도 "여기서부터는 접으면 안 되는 것"들.
   *
   * ALWAYS_OPEN 은 heading 텍스트만 검사한다. 그런데 프롬프트는 주의사항을
   * 블록쿼트(`> ⚠️ **주의사항**:`)로, 면책 고지를 평문으로 지시한다
   * (app/templates/prompts.py). 답변 구조도 "⑥ 실무 안내(절차) → ⑦ 주의사항 +
   * 면책" 순서라, `## 절차`가 마지막 heading 이면 그 뒤의 주의사항·구분선·면책이
   * 통째로 <details> 안으로 빨려 들어가 기본 접힘 상태로 숨는다.
   * heading 단위 방어만으로는 못 막는 구멍이라 여기서 따로 끊는다. */
  function isTerminator(n) {
    if (n.tagName === 'HR') return true;                       // 프롬프트가 지시하는 `---`
    if (n.classList && n.classList.contains('disclaimer-notice')) return true;
    var t = norm(n.textContent);
    if (/본\s*답변은[\s\S]{0,30}참고용|법적\s*효력이\s*없습니다/.test(t)) return true;
    if (/^(?:⚠️\s*)?주의\s*사항/.test(t)) return true;
    return false;
  }

  /* h 다음 형제부터 다음 섹션 헤딩(또는 종료 마커) 직전까지 수집.
   * h2 섹션은 내부 h3를 품어야 하므로 h2에서만 멈춘다. */
  function collectSectionNodes(h) {
    var stopAtH2Only = (h.tagName === 'H2');
    var out = [];
    var n = h.nextElementSibling;
    while (n) {
      if (n.tagName === 'H2' || (!stopAtH2Only && n.tagName === 'H3')) break;
      if (isTerminator(n)) break;
      out.push(n);
      n = n.nextElementSibling;
    }
    return out;
  }

  // 답변마다 증가한다. 채팅은 후속 질문의 답변이 계속 쌓이는데(chat.appendChild),
  // 인덱스만 쓰면 답변마다 id가 0부터 재시작해 document.getElementById 가 항상
  // 첫 답변을 잡는다 — 목차 칩이 엉뚱한 답변으로 점프한다.
  var answerSeq = 0;

  function buildOutline(container, idPrefix) {
    var heads = Array.prototype.slice.call(container.querySelectorAll('h2'));
    if (heads.length < MIN_HEADINGS) return null;

    var nav = document.createElement('nav');
    nav.className = 'answer-outline';
    nav.setAttribute('aria-label', '답변 목차');

    heads.forEach(function (h, i) {
      // 텍스트 슬러그가 아니라 인덱스로 id를 만든다 — 한글 헤딩은 중복·충돌이 쉽다.
      var id = idPrefix + i;
      h.id = id;

      var chip = document.createElement('a');
      chip.className = 'outline-chip';
      chip.href = '#' + id;
      chip.textContent = norm(h.textContent);
      chip.addEventListener('click', function (e) {
        e.preventDefault();
        // wrapCollapsible이 h2를 <details>로 치환했을 수 있으므로 id로 다시 찾는다.
        var target = document.getElementById(id);
        if (!target) return;
        var box = (target.tagName === 'DETAILS') ? target : target.closest('details');
        if (box) box.open = true;   // 접힌 섹션으로 점프하면 펼쳐서 보여준다
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
      nav.appendChild(chip);
    });
    return nav;
  }

  function wrapCollapsible(container) {
    var heads = Array.prototype.slice.call(container.querySelectorAll('h2, h3'));
    heads.forEach(function (h) {
      if (!container.contains(h)) return;          // 앞선 섹션에 흡수돼 사라짐
      if (h.closest('details')) return;            // 중첩 접기 금지
      if (h.closest('.summary-badge')) return;     // 핵심 답변 배지는 대상 아님

      var title = norm(h.textContent);
      if (matches(ALWAYS_OPEN, title)) return;     // 먼저 검사 — 오매칭 시 안전한 쪽
      if (!matches(COLLAPSIBLE, title)) return;

      var section = collectSectionNodes(h);
      if (!section.length) return;

      var body = norm(section.map(function (n) { return n.textContent; }).join(' '));
      if (body.length < MIN_COLLAPSE_LEN) return;

      var details = document.createElement('details');
      if (h.id) details.id = h.id;                 // 목차 앵커를 잃지 않게 승계

      // summary는 절대 비우지 않는다 — <details>의 접근성 이름이 여기서 나온다.
      // 제목만 두면 "무엇이 접혔는지" 알 수 없어 내용 요지를 함께 붙인다.
      var summary = document.createElement('summary');
      summary.textContent = title + ' — ' + body.slice(0, HINT_LEN) + '…';
      details.appendChild(summary);

      h.replaceWith(details);
      section.forEach(function (n) { details.appendChild(n); });
    });
  }

  /* ── 핵심 답변으로 되돌아가기 (FR-3) ──────────────────────────────────────
   * sticky 목차만으로는 부족하다. index.html의 #chat은 `overflow:hidden` +
   * `overflow-y:visible` 조합이라 명세상 overflow-y가 auto로 계산돼 스크롤
   * 컨테이너가 되는데, 데스크톱은 height:auto라 실제로는 스크롤되지 않는다.
   * 그래서 그 안의 sticky는 붙을 스크롤포트가 없어 데스크톱에서 무효다
   * (모바일은 height:50vh라 정상 동작). 두 환경 모두에서 도는 경로가 필요하다. */
  var jumpTarget = null;
  var jumpBtn = null;
  var jumpObserver = null;

  function ensureJumpButton() {
    if (jumpBtn) return jumpBtn;
    jumpBtn = document.createElement('button');
    jumpBtn.id = 'glance-jump-core';
    jumpBtn.type = 'button';
    jumpBtn.textContent = '⚖️ 핵심으로';
    jumpBtn.setAttribute('aria-label', '핵심 답변으로 이동');
    jumpBtn.addEventListener('click', function () {
      if (jumpTarget) jumpTarget.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    document.body.appendChild(jumpBtn);
    return jumpBtn;
  }

  function trackJumpToCore(el) {
    var core = el.querySelector('.summary-badge') || el.querySelector('h2');
    if (!core || typeof IntersectionObserver === 'undefined') return;

    jumpTarget = core;
    var btn = ensureJumpButton();
    if (jumpObserver) jumpObserver.disconnect();   // 항상 최신 답변만 추적

    jumpObserver = new IntersectionObserver(function (entries) {
      var e = entries[0];
      // 핵심 답변이 화면 위로 지나갔을 때만 띄운다(아직 아래에 있으면 불필요).
      var scrolledPast = !e.isIntersecting && e.boundingClientRect.top < 0;
      btn.classList.toggle('show', scrolledPast);
    }, { threshold: 0 });
    jumpObserver.observe(core);
  }

  /* 완성된 답변 요소(말풍선)에 조망 레이어를 얹는다. 중복 호출은 무시된다. */
  function finalize(el) {
    if (!el || el.dataset.glanceDone === '1') return;
    try {
      // 순서 중요: 목차가 h2에 id를 붙인 뒤 접기가 그 id를 <details>로 승계한다.
      var nav = buildOutline(el, 'ans-h2-' + (answerSeq++) + '-');
      wrapCollapsible(el);
      if (nav) el.insertBefore(nav, el.firstChild);
      trackJumpToCore(el);
      el.dataset.glanceDone = '1';
    } catch (err) {
      if (global.console) global.console.warn('[glance] finalize 실패:', err);
    }
  }

  /* 내보내기(PDF·이메일)용 사본 변환.
   * 접힌 채로 인쇄되면 내용이 통째로 빠진 것처럼 보이므로 강제로 펼치고,
   * 목차는 종이에서 쓸모가 없으니 뺀다. 라이브 DOM은 건드리지 않는다. */
  function expandForExport(html) {
    try {
      var tmp = document.createElement('div');
      tmp.innerHTML = html;
      Array.prototype.forEach.call(tmp.querySelectorAll('details'), function (d) {
        d.open = true;
      });
      Array.prototype.forEach.call(tmp.querySelectorAll('.answer-outline'), function (n) {
        n.remove();
      });
      return tmp.innerHTML;
    } catch (err) {
      return html;
    }
  }

  global.answerGlance = { finalize: finalize, expandForExport: expandForExport };
})(window);
