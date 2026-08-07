'use strict';

// 공개 페이지(public/*.html)의 fetch 오류 처리 규약을 고정한다.
//
// 왜 필요한가: fetch는 **네트워크 실패에만 reject**하고 4xx·5xx는 정상 이행한다.
// `.then(r => r.json())`으로 바로 넘기면 오류 응답 본문이 정상 데이터처럼 파싱돼
// 화면에 undefined 가 찍히고, 사용자는 원인을 알 수 없다.
// 2026-08-07 실장애: CAPTCHA_SECRET 미설정 → /api/captcha 503 →
// "보안문자: undefined" → 이메일 발송·게시판 등록 불가.
//
// jsdom 없이 소스 정적 단언으로 검증한다(CI가 npm 의존성을 설치하지 않는다).

const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const PAGES = ['index.html', 'board.html', 'admin.html'].map(function (name) {
  return [name, fs.readFileSync(path.join(__dirname, 'public', name), 'utf8')];
});

const INDEX = PAGES.find(function (p) { return p[0] === 'index.html'; })[1];
const BOARD = PAGES.find(function (p) { return p[0] === 'board.html'; })[1];

/** 선언을 시그니처로 찾아 잘라낸다 — 선언 자신의 들여쓰기와 같은 열의 종료 부호만 인정.
 *  (함수 내부의 더 깊은 닫는 중괄호를 먼저 잡아 잘리는 것을 막는다) */
function slice(source, startRe, closer) {
  const start = source.match(startRe);
  if (!start) throw new Error(`시작 패턴을 찾지 못함: ${startRe}`);
  const lineStart = source.lastIndexOf('\n', start.index) + 1;
  const indent = source.slice(lineStart, start.index);
  if (/\S/.test(indent)) throw new Error(`선언이 줄 시작이 아님: ${startRe}`);
  const escaped = closer.replace(/[[\]{}]/g, '\\$&');
  const rest = source.slice(start.index);
  const end = rest.match(new RegExp('^' + indent + escaped + '$', 'm'));
  if (!end) throw new Error(`종료 패턴을 찾지 못함: ${closer}`);
  return rest.slice(0, end.index + end[0].length);
}

// ── 1. CAPTCHA 로딩 (실장애 지점) ────────────────────────────────────────────

test('CAPTCHA 로딩이 응답 상태와 페이로드를 검사한다', () => {
  for (const [name, src] of PAGES) {
    const m = src.match(/fetch\([^)]*\/api\/captcha[\s\S]{0,700}/);
    if (!m) continue;   // 해당 페이지에 CAPTCHA 없음(admin)
    assert.match(m[0], /\.ok\b/,
      `${name}: CAPTCHA fetch에 응답 상태 검사 없음 — 503이 undefined로 위장된다`);
    // `.token` 출현만 보면 `emailModalToken = data.token`(대입)에도 통과한다.
    // 200인데 필드가 빠지는 경우를 막으려면 **거부하는 가드**가 있어야 하고,
    // 화면에 찍히는 건 question이므로 둘 다 확인해야 한다.
    assert.match(m[0], /!data\.token/,
      `${name}: 토큰 부재를 거부하는 가드 없음 — 200인데 필드가 빠지면 같은 증상`);
    assert.match(m[0], /!data\.question/,
      `${name}: question 부재를 거부하는 가드 없음 — 화면에 undefined가 찍힌다`);
  }
});

test('CAPTCHA 실패 시 제출 버튼이 잠긴 채 유지된다', () => {
  // index: 모달을 열 때 잠그고, .ok 검사를 통과한 뒤에만 연다
  const email = slice(INDEX, /function openEmailModal\(btn\) \{/, '}');
  assert.match(email, /submitBtn\.disabled = true/, 'index: 초기 잠금 없음');
  const okAt = email.indexOf('.ok');
  const enableAt = email.indexOf('submitBtn.disabled = false');
  assert.ok(okAt > 0, 'index: .ok 검사 없음');
  assert.ok(enableAt > okAt,
    'index: .ok 검사보다 먼저 버튼이 열린다 — 오류 응답에도 활성화된다');

  // board: 로딩 시작 시 잠그고 성공 경로에서만 연다
  const load = slice(BOARD, /async function loadCaptcha\(\) \{/, '}');
  assert.match(load, /submitBtn\.disabled = true/, 'board: 로딩 시작 시 잠금 없음');
  assert.match(load, /captchaToken = ''/,
    'board: 전역 토큰 초기화 없음 — 실패해도 이전 토큰이 남는다');
  // board의 해제는 rate limit도 함께 보므로 리터럴 false가 아니다(429 충돌 방지).
  const bOkAt = load.indexOf('.ok');
  const bEnableAt = load.indexOf('submitBtn.disabled = Date.now()');
  assert.ok(bOkAt > 0, 'board: .ok 검사 없음');
  assert.ok(bEnableAt > bOkAt,
    'board: .ok 검사 이후에 버튼 해제가 와야 한다');
});

test('board: 제출 종료 후 보안문자 없이 버튼이 열리지 않는다', () => {
  const submit = slice(BOARD, /async function submitPost\(e\) \{/, '}');
  // finally가 무조건 열면 403 후 재로딩 실패 시 게이팅이 무력화된다
  assert.match(submit, /submitBtn\.disabled = !captchaToken/,
    'finally가 토큰 유무와 무관하게 버튼을 연다');
  // 403 재로딩은 await 해야 finally보다 먼저 확정된다
  assert.match(submit, /await loadCaptcha\(\)/,
    '403 재로딩이 await 되지 않아 finally와 순서 경합이 생긴다');
});

test('board: 429 잠금이 버튼 게이팅과 충돌하지 않는다', () => {
  const submit = slice(BOARD, /async function submitPost\(e\) \{/, '}');

  // ① 잔여 타이머가 무조건 열면, 그 사이 CAPTCHA가 실패했을 때 토큰 없이 열린다
  assert.ok(!/setTimeout\([^)]*\{\s*submitBtn\.disabled = false;/.test(submit),
    '429 타이머가 토큰 유무와 무관하게 버튼을 연다');
  assert.match(submit, /rateLimitedUntil = 0;[\s\S]{0,200}submitBtn\.disabled = !captchaToken/,
    '429 타이머 해제 시 토큰 유무를 확인하지 않는다');

  // ② finally가 rate limit을 무시하면 30초 잠금이 같은 틱에 죽는다
  assert.match(submit, /submitBtn\.disabled = !captchaToken \|\| Date\.now\(\) < rateLimitedUntil/,
    'finally가 rate limit 잠금을 덮어써 30초 잠금이 무효가 된다');

  // ③ loadCaptcha 성공 경로도 같은 불변식을 지켜야 한다
  const load = slice(BOARD, /async function loadCaptcha\(\) \{/, '}');
  assert.match(load, /submitBtn\.disabled = Date\.now\(\) < rateLimitedUntil/,
    'loadCaptcha 성공이 rate limit 잠금을 덮어쓴다');
});

// ── 2. 공개 페이지 전반 ──────────────────────────────────────────────────────

test('공개 페이지의 모든 fetch가 응답 상태 또는 예외를 처리한다', () => {
  // ⚠️ 이 검사의 한계를 알고 쓸 것.
  // `catch(`만 있어도 통과하므로 "try/catch는 있으나 resp.ok 검사가 없는" 형태를
  // 잡지 못한다 — 2026-08-07 실장애를 일으킨 loadCaptcha가 정확히 그 형태였다.
  // 즉 이 테스트는 "오류 처리 의도가 있는가"만 보증한다. 상태 검사까지 강제하려면
  // CAPTCHA처럼 **개별 테스트로 따로 고정**해야 한다(위 테스트 1 참고).
  //
  // 윈도우 800자: 검사가 몇 줄 아래 오는 패턴이 흔하다(실측 최장 약 520자 —
  // index.html의 chat POST가 공유 가드까지). 좁히면 정상 코드가 실패한다.
  for (const [name, src] of PAGES) {
    const positions = [];
    const re = /\bfetch\(/g;
    let m;
    while ((m = re.exec(src)) !== null) positions.push(m.index);

    for (const i of positions) {
      const window = src.slice(i, i + 800);
      assert.ok(/\.ok\b/.test(window) || /catch\s*[({]/.test(window),
        `${name}: fetch 오류 처리 없음 — ${src.slice(i, i + 70).replace(/\s+/g, ' ')}\n` +
        '  가드가 800자 밖에 있으면 가드를 앞당기거나 이 윈도우를 넓힐 것');
    }
  }
});

test('오류 문구가 서버 내부 상세를 노출하지 않는다', () => {
  // api/index.py 의 503 detail 은 "서버 설정 오류" — 사용자에게 무의미하고
  // 내부 상태를 드러낸다. 고정 안내 문구를 쓴다.
  for (const [name, src] of PAGES) {
    assert.ok(!/서버 설정 오류/.test(src),
      `${name}: 서버 내부 오류 문구를 그대로 노출한다`);
  }
});
