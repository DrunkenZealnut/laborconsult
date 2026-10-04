'use strict';

// 지식iN 붙여넣기용 변환기 계약 (naver-kin-answer-simplification).
//
// 허용 태그·속성은 2026-09-22 실측(서식 통과 실험대)에서 **통과한 것만**이다.
// 여기 없는 태그가 출력되면 지식iN 에디터가 조용히 버리거나 평문으로 뭉갠다.
// 새 태그를 허용하려면 실험대에서 먼저 통과시키고 이 목록을 함께 갱신할 것.

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { toHtml } = require('./public/kin_format.js');

const ALLOWED_TAGS = new Set(['h2', 'h3', 'p', 'b', 'i', 's', 'span', 'a', 'br', 'hr',
  'ul', 'ol', 'li', 'table', 'tr', 'td', 'pre']);
const FORBIDDEN_TAGS = ['blockquote', 'img', 'h1', 'h4', 'h5', 'h6', 'th', 'script',
  'div', 'strong', 'em', 'code', 'del', 'thead', 'tbody'];

function tagsOf(html) {
  const out = new Set();
  for (const m of html.matchAll(/<\/?([a-z0-9]+)\b/g)) out.add(m[1]);
  return out;
}
function stripTags(html) { return html.replace(/<[^>]+>/g, ''); }
function attrsOf(html) {
  const out = new Set();
  for (const m of html.matchAll(/<[a-z0-9]+\s+([^>]*)>/g)) {
    for (const a of m[1].matchAll(/([a-z-]+)=/g)) out.add(a[1]);
  }
  return out;
}

// 실측 5건에 등장한 모든 구문을 한 fixture 에 모았다.
const FIXTURE = [
  '# ⚖️ 핵심 답변',
  '',
  '부동산업자와 건물주 **양측 모두**에게 청구가 가능합니다.',
  '두 번째 줄은 단일 줄바꿈으로 이어집니다.',
  '',
  '---',
  '',
  '## 📋 상황 정리',
  '',
  '| 항목 | 내용 |',
  '|------|------|',
  '| 청구 금액 | **1,300,000원** (13개월치) |',
  '| 지급 의무자 | 건물주 — 실질적 수익자 |',
  '',
  '### 근로자 여부 판단 기준',
  '',
  '> ⚠️ **주의사항**: 근로관계인지 vs 민사 청구인지에 따라 달라집니다.',
  '> 이어지는 줄입니다.',
  '>',
  '> 다만 지시를 받았다면 근로자성이 인정될 수 있습니다.',
  '',
  '- 이직일 이전 18개월간 180일 이상',
  '- 비자발적 이직일 것',
  '  - 들여쓴 하위 항목',
  '',
  '1. 이직확인서 처리 여부 확인',
  '2. 워크넷 구직등록',
  '',
  '자세한 내용은 [국가법령정보센터](https://www.law.go.kr)에서 확인하세요. `근로기준법 제56조` 참고.',
  '*기울임*과 ~~취소선~~도 있습니다. ![도식](https://example.com/a.png)',
  '',
  '```',
  '평균임금 = 임금총액 ÷ 총일수',
  '구직급여일액 = 평균임금 × 60%',
  '```',
  '',
  '#### 넷째 단계 제목',
].join('\n');

test('출력은 실측 통과 태그·style 속성만 쓴다', () => {
  const html = toHtml(FIXTURE);
  const tags = tagsOf(html);
  for (const t of tags) assert.ok(ALLOWED_TAGS.has(t), `허용되지 않은 태그 <${t}>`);
  for (const t of FORBIDDEN_TAGS) assert.ok(!tags.has(t), `금지 태그 <${t}> 출력됨`);
  const attrs = attrsOf(html);
  for (const a of attrs) assert.ok(a === 'style' || a === 'href', `허용되지 않은 속성 ${a}=`);
  assert.doesNotMatch(html, /\bclass=/);
  assert.doesNotMatch(html, /\bid=/);
});

test('마크다운 마커가 본문에 남지 않는다', () => {
  const text = stripTags(toHtml(FIXTURE));
  assert.doesNotMatch(text, /\*\*/, '볼드 마커 잔존');
  assert.doesNotMatch(text, /^#+\s/m, '헤더 마커 잔존');
  assert.doesNotMatch(text, /^>\s?/m, '인용 마커 잔존');
  assert.doesNotMatch(text, /\|---/, '표 정렬행 잔존');
  assert.doesNotMatch(text, /~~/, '취소선 마커 잔존');
  assert.doesNotMatch(text, /```/, '펜스 마커 잔존');
  assert.doesNotMatch(text, /!\[|\]\(/, '이미지·링크 마커 잔존');
});

test('제목 3단: h1→h2, h2→h3, h3 이하→큰 볼드 문단', () => {
  const html = toHtml(FIXTURE);
  assert.match(html, /<h2>⚖️ 핵심 답변<\/h2>/);
  assert.match(html, /<h3>📋 상황 정리<\/h3>/);
  assert.match(html, /<p><span style="font-size:16px"><b>근로자 여부 판단 기준<\/b><\/span><\/p>/);
  assert.match(html, /<p><span style="font-size:16px"><b>넷째 단계 제목<\/b><\/span><\/p>/);
});

test('표: 셀 인라인 테두리, 머리행은 td+b, 정렬행 제거, 셀 안 볼드 변환', () => {
  const html = toHtml(FIXTURE);
  assert.match(html, /<table style="border-collapse:collapse">/);
  assert.match(html, /<td style="border:1px solid #bbb;padding:6px 10px"><b>항목<\/b><\/td>/);
  assert.match(html, /<td style="border:1px solid #bbb;padding:6px 10px"><b>1,300,000원<\/b> \(13개월치\)<\/td>/);
  assert.doesNotMatch(html, /<th/);
  assert.equal((html.match(/<tr>/g) || []).length, 3, '정렬행이 행으로 렌더됨');
});

test('인용구는 p 로 — 빈 > 줄이 문단 경계, 문단 안 줄은 br', () => {
  const html = toHtml(FIXTURE);
  assert.doesNotMatch(html, /<blockquote/);
  assert.match(html, /<p>⚠️ <b>주의사항<\/b>: 근로관계인지 vs 민사 청구인지에 따라 달라집니다\.<br>이어지는 줄입니다\.<\/p>/);
  assert.match(html, /<p>다만 지시를 받았다면 근로자성이 인정될 수 있습니다\.<\/p>/);
});

test('목록: ul/ol, 들여쓴 하위 항목은 같은 목록에 평탄화', () => {
  const html = toHtml(FIXTURE);
  assert.match(html, /<ul><li>이직일 이전 18개월간 180일 이상<\/li><li>비자발적 이직일 것<\/li><li>들여쓴 하위 항목<\/li><\/ul>/);
  assert.match(html, /<ol><li>이직확인서 처리 여부 확인<\/li><li>워크넷 구직등록<\/li><\/ol>/);
});

test('인라인: 링크는 http(s)만, 코드는 고정폭 span, 이미지는 alt 만, 기울임·취소선', () => {
  const html = toHtml(FIXTURE);
  assert.match(html, /<a href="https:\/\/www\.law\.go\.kr">국가법령정보센터<\/a>/);
  assert.match(html, /<span style="font-family:monospace">근로기준법 제56조<\/span>/);
  assert.match(html, /<i>기울임<\/i>과 <s>취소선<\/s>도 있습니다\. 도식/);
  assert.doesNotMatch(html, /<img|example\.com\/a\.png/);
  const bad = toHtml('[클릭](javascript:alert(1)) [파일](file:///etc/passwd)');
  assert.doesNotMatch(bad, /<a /);
  assert.match(bad, /클릭.*파일/);
});

test('문단·구분선·펜스', () => {
  const html = toHtml(FIXTURE);
  assert.match(html, /<p>부동산업자와 건물주 <b>양측 모두<\/b>에게 청구가 가능합니다\.<br>두 번째 줄은 단일 줄바꿈으로 이어집니다\.<\/p>/);
  assert.match(html, /<hr>/);
  assert.match(html, /<pre>평균임금 = 임금총액 ÷ 총일수\n구직급여일액 = 평균임금 × 60%<\/pre>/);
});

test('원문의 <·&·" 는 이스케이프된다 — > 는 일부러 남긴다 (인용 마커 판정·md() 와 동일)', () => {
  const html = toHtml('<script>alert(1)</script> A & B "인용" **굵게** > 화살표');
  assert.doesNotMatch(html, /<script/, '태그가 열리면 안 된다');
  assert.match(html, /&lt;script>alert\(1\)&lt;\/script> A &amp; B &quot;인용&quot; <b>굵게<\/b> > 화살표/);
});

test('짝이 안 맞는 마커는 글자로 남긴다 — 반쪽 변환·삼킴 금지', () => {
  // 절단된 답변(실측 샘플 #1 이 그랬다)에서 닫히지 않은 **는 원문 그대로 보여야
  // 운영자가 절단을 알아챈다. 앞쪽 짝 맞는 볼드까지 깨지면 안 된다.
  const html = toHtml('> 💡 **참고**: 효력보다는 **지급 의사');
  assert.match(html, /<b>참고<\/b>: 효력보다는 \*\*지급 의사/);
  // 표 머리행도 같은 원칙이다 — 머리셀은 <b> 로 감싸므로 짝 맞는 **만 벗기고
  // (중첩 방지), 짝 없는 **는 남긴다. (CodeRabbit PR #75 지적)
  const th = toHtml('| **구분** | **지급 의사 |\n|---|---|\n| a | b |');
  assert.match(th, /<td[^>]*><b>구분<\/b><\/td>/, '짝 맞는 볼드는 중첩 없이 한 번만');
  assert.match(th, /<td[^>]*><b>\*\*지급 의사<\/b><\/td>/, '짝 없는 마커가 머리셀에서 사라짐');
});

test('목록 마커 판정은 화면 렌더러 md() 와 같다 — `1)`·`+`·①·• 는 글자로 남는다', () => {
  // 실기 보고(2026-09-22): 화면엔 `1)` 로 보이던 줄이 지식iN 에서 `1.` 로 바뀌었다.
  // 변환기가 `1)` 를 목록으로 잡아 <ol> 을 만들면 에디터가 번호를 다시 매기기 때문.
  // md() 는 `\d+\.` 와 `[-*]` 만 마커로 본다 — 붙여넣기 결과는 화면과 같아야 한다.
  const html = toHtml('1) 이직확인서 확인\n2) 워크넷 등록\n+ 플러스 항목\n① 원문자 항목\n• 점문자 항목');
  assert.doesNotMatch(html, /<ol|<ul|<li/, '괄호 번호·플러스·원문자·점문자가 목록으로 잡힘');
  assert.match(html, /1\) 이직확인서 확인<br>2\) 워크넷 등록<br>\+ 플러스 항목<br>① 원문자 항목<br>• 점문자 항목/);
  // 진짜 마커는 여전히 목록이다.
  assert.match(toHtml('1. 하나\n2. 둘'), /<ol><li>하나<\/li><li>둘<\/li><\/ol>/);
  assert.match(toHtml('- 하나\n* 둘'), /<ul><li>하나<\/li><li>둘<\/li><\/ul>/);
});

test('결정적이다 — 같은 입력은 같은 출력', () => {
  assert.equal(toHtml(FIXTURE), toHtml(FIXTURE));
});

test('빈 입력·공백만 있는 입력은 빈 문자열', () => {
  assert.equal(toHtml(''), '');
  assert.equal(toHtml('   \n\n  '), '');
});
