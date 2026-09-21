(function (root) {
  'use strict';

  // 답변 마크다운을 네이버 지식iN 답변 에디터에 붙여넣어도 살아남는 HTML 로 바꾼다.
  //
  // 허용 태그·속성은 2026-09-22 실측(서식 통과 실험대)에서 통과한 것만이다:
  //   h2 h3 p b i s span[style] a[href] br hr ul ol li table[style] tr td[style] pre
  // 깨지는 것: blockquote(→ p), img(→ alt 텍스트), class/id(전부 버려짐).
  // 새 태그를 쓰려면 실험대에서 먼저 통과시키고 test_kin_format.js 의 허용 집합을 함께 갱신할 것.
  //
  // 화면 렌더러(md)와 별도 구현이다 — 그쪽은 class 기반이라 붙여넣기에서 서식이 전부 사라진다.

  var CELL = 'border:1px solid #bbb;padding:6px 10px';
  var FAKE_HEADING = 'font-size:16px';
  var MONO = 'font-family:monospace';

  // `>` 는 이스케이프하지 않는다 — 텍스트 위치의 `>` 는 유효한 HTML 이고,
  // 줄머리 인용 마커 판정에 원문 그대로 필요하다.
  function esc(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
  }

  function inline(s) {
    var stash = [];
    function keep(html) { stash.push(html); return '\x00' + (stash.length - 1) + '\x00'; }

    // 이미지는 alt 만 남긴다 — 외부 이미지는 예외 없이 잘린다(실측). 링크보다 먼저.
    s = s.replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1');
    // 코드 안의 * _ ~ 가 서식으로 오인되지 않도록 먼저 격리한다.
    s = s.replace(/`([^`\n]+)`/g, function (_, code) {
      return keep('<span style="' + MONO + '">' + code + '</span>');
    });
    // 링크: http(s) 만 살린다. URL 의 _ 가 기울임으로 오인되지 않도록 격리한다.
    s = s.replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/g, function (_, text, url) {
      if (!/^https?:\/\//i.test(url)) return text;
      return keep('<a href="' + url + '">' + text + '</a>');
    });
    s = s.replace(/\*\*([^*\n]+?)\*\*/g, '<b>$1</b>');
    s = s.replace(/~~([^~\n]+?)~~/g, '<s>$1</s>');
    s = s.replace(/(^|[^*\w])\*([^*\n]+?)\*(?!\*)/g, '$1<i>$2</i>');
    s = s.replace(/(^|\s)_([^_\n]+?)_(?=\s|$|[.,;:!?)])/g, '$1<i>$2</i>');
    return s.replace(/\x00(\d+)\x00/g, function (_, i) { return stash[Number(i)]; });
  }

  function tableHtml(lines) {
    var rows = [];
    for (var k = 0; k < lines.length; k++) {
      var line = lines[k].trim();
      if (/^\|?[\s:|-]+\|?$/.test(line)) continue;   // 정렬행(|---|---|)
      rows.push(line.replace(/^\||\|$/g, '').split('|').map(function (c) { return c.trim(); }));
    }
    if (!rows.length) return '';
    var html = '<table style="border-collapse:collapse">';
    for (var r = 0; r < rows.length; r++) {
      html += '<tr>';
      for (var c = 0; c < rows[r].length; c++) {
        // 머리행은 th 가 아니라 td+b — th 는 미실측이다. 셀의 자체 **x** 는 벗겨 <b> 중첩을
        // 막되, **짝이 맞는 것만** 벗긴다 — 전부 지우면 절단된 답변의 닫히지 않은 ** 가
        // 사라져 운영자가 절단을 못 알아챈다(다른 곳과 같은 원칙).
        var cell = r === 0
          ? '<b>' + inline(rows[r][c].replace(/\*\*([^*\n]+?)\*\*/g, '$1')) + '</b>'
          : inline(rows[r][c]);
        html += '<td style="' + CELL + '">' + cell + '</td>';
      }
      html += '</tr>';
    }
    return html + '</table>';
  }

  // blockquote 는 지식iN 에서 깨진다(실측). 본문이 이미 `⚠️ **주의사항**:` 라벨을 갖고
  // 있어 볼드 문단으로 충분히 구분된다. 빈 `>` 줄이 문단 경계다.
  function quoteHtml(lines) {
    var paras = [[]];
    for (var k = 0; k < lines.length; k++) {
      var body = lines[k].replace(/^>\s?/, '');
      if (!body.trim()) { if (paras[paras.length - 1].length) paras.push([]); continue; }
      paras[paras.length - 1].push(body.trim());
    }
    return paras.filter(function (p) { return p.length; })
      .map(function (p) { return '<p>' + p.map(inline).join('<br>') + '</p>'; }).join('\n');
  }

  var BULLET = /^\s*[-*+]\s+(.+)$/;
  var NUMBER = /^\s*\d+[.)]\s+(.+)$/;

  // 중첩 목록은 평탄화한다 — 중첩 통과 여부가 미실측이라 한 단계로 편다. 다른 종류의
  // 하위 항목(번호 밑의 불릿)은 번호를 새로 매기지 않도록 현재 항목에 이어 붙인다.
  function listHtml(lines, ordered) {
    var own = ordered ? NUMBER : BULLET;
    var other = ordered ? BULLET : NUMBER;
    var items = [];
    for (var k = 0; k < lines.length; k++) {
      var m = lines[k].match(own);
      if (m) { items.push(inline(m[1].trim())); continue; }
      var o = lines[k].match(other);
      if (o && items.length) items[items.length - 1] += '<br>' + (ordered ? '- ' : '') + inline(o[1].trim());
    }
    var tag = ordered ? 'ol' : 'ul';
    return '<' + tag + '>' + items.map(function (i) { return '<li>' + i + '</li>'; }).join('') + '</' + tag + '>';
  }

  function headingHtml(level, text) {
    var t = inline(text.trim());
    if (level === 1) return '<h2>' + t + '</h2>';
    if (level === 2) return '<h3>' + t + '</h3>';
    // h4 이하는 미실측 — "가짜 제목"(큰 볼드 span)은 통과했다.
    return '<p><span style="' + FAKE_HEADING + '"><b>' + t + '</b></span></p>';
  }

  function toHtml(markdown) {
    var text = String(markdown == null ? '' : markdown).replace(/\r\n?/g, '\n').trim();
    if (!text) return '';

    // 펜스는 이스케이프·블록 파싱 전에 통째로 떼어 둔다. 내용은 그대로(줄바꿈 보존).
    var fences = [];
    text = text.replace(/```[^\n]*\n([\s\S]*?)```/g, function (_, code) {
      fences.push('<pre>' + esc(code.replace(/\n$/, '')) + '</pre>');
      return '\x00F' + (fences.length - 1) + '\x00';
    });
    text = esc(text);

    var lines = text.split('\n');
    var out = [];
    var para = [];
    function flush() {
      if (para.length) { out.push('<p>' + para.map(inline).join('<br>') + '</p>'); para = []; }
    }
    function gather(i, test) {
      var buf = [];
      while (i < lines.length && test(lines[i])) buf.push(lines[i++]);
      return { lines: buf, next: i };
    }

    for (var i = 0; i < lines.length;) {
      var line = lines[i];
      var m;
      if (!line.trim()) { flush(); i++; continue; }
      if ((m = line.match(/^\x00F(\d+)\x00$/))) { flush(); out.push(fences[Number(m[1])]); i++; continue; }
      if ((m = line.match(/^(#{1,6})\s+(.+?)\s*#*\s*$/))) { flush(); out.push(headingHtml(m[1].length, m[2])); i++; continue; }
      if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) { flush(); out.push('<hr>'); i++; continue; }
      if (/^\s*\|.*\|\s*$/.test(line)) {
        flush();
        var t = gather(i, function (l) { return /^\s*\|.*\|\s*$/.test(l); });
        out.push(tableHtml(t.lines)); i = t.next; continue;
      }
      if (/^>/.test(line)) {
        flush();
        var q = gather(i, function (l) { return /^>/.test(l); });
        out.push(quoteHtml(q.lines)); i = q.next; continue;
      }
      if (BULLET.test(line) || NUMBER.test(line)) {
        flush();
        var ordered = NUMBER.test(line) && !BULLET.test(line);
        var own = ordered ? NUMBER : BULLET;
        var l = gather(i, function (x) {
          // 같은 종류는 들여쓰기와 무관하게 이어지고, 다른 종류는 들여쓴 경우만 하위 항목이다.
          return own.test(x) || (/^\s+/.test(x) && (BULLET.test(x) || NUMBER.test(x)));
        });
        out.push(listHtml(l.lines, ordered)); i = l.next; continue;
      }
      para.push(line.trim()); i++;
    }
    flush();
    return out.join('\n');
  }

  // 실험대가 검증한 복사 경로 그대로: 렌더된 리치 콘텐츠를 선택해 복사하면
  // text/html 과 text/plain 이 함께 실린다. 샌드박스·구형 브라우저에서 가장 관대하다.
  function copyRich(html) {
    if (typeof document === 'undefined') return Promise.resolve(false);
    var holder = document.createElement('div');
    holder.setAttribute('contenteditable', 'true');
    holder.style.cssText = 'position:fixed;left:-99999px;top:0;width:640px;white-space:normal;opacity:0';
    holder.innerHTML = html;
    document.body.appendChild(holder);
    var ok = false;
    try {
      var range = document.createRange();
      range.selectNodeContents(holder);
      var sel = root.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      ok = document.execCommand('copy');
      sel.removeAllRanges();
    } catch (_) { ok = false; }
    document.body.removeChild(holder);
    if (ok) return Promise.resolve(true);

    if (root.ClipboardItem && navigator.clipboard && navigator.clipboard.write) {
      var tmp = document.createElement('div');
      tmp.innerHTML = html;
      return navigator.clipboard.write([new root.ClipboardItem({
        'text/html': new Blob([html], { type: 'text/html' }),
        'text/plain': new Blob([tmp.innerText || tmp.textContent || ''], { type: 'text/plain' })
      })]).then(function () { return true; }, function () { return false; });
    }
    return Promise.resolve(false);
  }

  var api = { toHtml: toHtml, copyRich: copyRich };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.KinFormat = api;
})(typeof window !== 'undefined' ? window : globalThis);
