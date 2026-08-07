# CAPTCHA fetch 오류 처리 Design (captcha-fetch-error-handling)

> **Summary**: Plan v0.1의 FR-1~FR-5를 코드 수준으로 설계한다. 핵심 발견 — **두 페이지의 버튼 게이팅 구조가 다르다**. `index.html`은 제출 버튼이 CAPTCHA 성공에만 열리는 구조라 `r.ok` 검사만 넣으면 FR-3이 자동 충족되지만, `board.html`은 버튼이 애초에 게이팅되지 않아 별도 처리가 필요하다. 또 `board.html`의 `captchaToken`은 모듈 전역이라 **실패 시 이전 토큰이 남는** 문제가 있다.
>
> **Project**: laborconsult
> **Author**: DrunkenZealnut
> **Date**: 2026-08-07
> **Status**: Draft
> **Planning Doc**: [captcha-fetch-error-handling.plan.md](../../01-plan/features/captcha-fetch-error-handling.plan.md) (v0.1)

---

## 1. 설계 개요

### 1.1 설계 목표

Plan §2.1의 FR-1~FR-5를 구현한다. 원칙은 **"서버 오류가 사용자에게 원인 불명의 UI 파손으로 보이지 않게"**다. 이 수정은 CAPTCHA를 발급되게 만들지 않는다 — 발급이 안 되는 이유를 사용자가 알 수 있게 만들 뿐이다(Plan §5 마지막 리스크).

### 1.2 핵심 발견 — 두 페이지의 버튼 게이팅 구조가 다르다

| | `index.html` 이메일 모달 | `board.html` 글쓰기 모달 |
|---|---|---|
| 제출 버튼 초기 상태 | `submitBtn.disabled = true` (`:1547`) | **게이팅 없음** — 항상 활성 |
| 활성화 시점 | CAPTCHA `.then` 안에서 `disabled = false` (`:1557`) | 해당 없음 |
| 토큰 변수 | `emailModalToken`, 모달 열 때 `null`로 초기화(`:1535`) | `captchaToken`, **모듈 전역**(`:898`) — 초기화 없음 |
| 실패 시 현재 동작 | 503이 `.then`을 타서 버튼이 **열림**(버그) | 버튼은 원래 열려 있음. 제출하면 서버 403 → 오류 표시 → `loadCaptcha()` 재시도 |

**설계 결론 두 가지**

1. `index.html`은 `r.ok` 검사를 넣으면 실패 시 `.then` 본문이 실행되지 않아 **FR-3이 자동으로 충족**된다(버튼이 `true`인 채로 남는다). 추가 처리 불필요.
2. `board.html`은 `r.ok`만으로 부족하다.
   - **버튼 게이팅이 없다** → 실패 후에도 제출 가능. 서버가 403으로 막긴 하지만, CAPTCHA가 503인 상황에서는 재시도(`:959` `loadCaptcha()`)도 실패해 **사용자가 무한 루프에 빠진다**.
   - **`captchaToken`이 모듈 전역이고 실패 시 갱신되지 않는다** → 모달을 닫았다 다시 열면 이전 세션의 토큰이 그대로 남아 있다. 서버가 만료(5분)로 거를 것이므로 보안 결함은 아니지만, "왜 실패하는지 알 수 없는" 상태를 한 겹 더 만든다.

### 1.3 왜 `fetch`가 오류를 삼키나 (근거 고정)

`fetch`는 **네트워크 수준 실패에만** reject한다. 4xx·5xx는 정상 이행(resolve)이며 `response.ok`가 `false`일 뿐이다. 따라서:

```js
fetch(url).then(r => r.json()).then(d => use(d)).catch(handleError)
//                ^^^^^^^^^^ 503 본문 {"detail":"..."} 도 정상 파싱된다
//                                      ^^^^^^^^^^^^ d.token = undefined
//                                                    ^^^^^^^^^^^ 실행되지 않음
```

이 저장소는 이미 `if (!resp.ok)` 관례가 12곳에 정착돼 있다(Plan §1.3). CAPTCHA 로딩 2곳만 예외였다.

---

## 2. 확정된 설계 결정

| # | 결정 | 확정 값 | 근거 |
|---|------|---------|------|
| D1 | 수정 방식 | 각 지점에 `r.ok` 검사(공통 래퍼 미도입) | Plan §6.2. 대상 2곳, 관례 12곳 정착 — 새 추상화는 관례 이탈이자 회귀 표면 증가 |
| D2 | `index.html` 버튼 게이팅 | **추가 처리 없음** | `r.ok` 검사만으로 FR-3 자동 충족(§1.2). 불필요한 코드를 넣지 않는다 |
| D3 | `board.html` 버튼 게이팅 | **CAPTCHA 실패 시 제출 버튼 비활성**, 성공 시 활성 | §1.2 — 실패 후 제출하면 403 → 재시도도 503 → 무한 루프 |
| D4 | `board.html` 토큰 초기화 | `loadCaptcha()` 진입 시 `captchaToken = ''` | 실패 시 이전 토큰 잔존 방지 |
| D5 | 오류 문구 | 고정 안내(서버 `detail` 미노출) | Plan §6.2. `"서버 설정 오류"`는 사용자에게 무의미하고 내부 상태를 노출한다 |
| D6 | 문구 내용 | 원인(일시적 문제) + 다음 행동(잠시 후 재시도) | Plan FR-4. `undefined` 노출 금지 |
| D7 | 재시도 UI | **신규 추가 안 함** | `board.html`은 이미 새로고침 버튼(`:552`)이 있고, `index.html`은 모달을 다시 열면 재요청된다 |
| D8 | 테스트 배치 | `test_answer_glance.js`가 아니라 **신규 `test_public_fetch.js`** | 성격이 다르다 — glance 파일은 조망 레이어 기능 테스트다. 공개 페이지 전반의 fetch 규약은 별도 관심사이고, 파일명이 내용을 정직하게 반영해야 한다 |
| D9 | 테스트 범위 | CAPTCHA 2곳 + **공개 페이지 전 fetch의 `.ok` 검사 존재** | 같은 실수의 재발을 넓게 막는다. 단 오탐을 피하려면 검사 윈도우를 넉넉히(§4.2) |

---

## 3. FR별 상세 설계

### 3.1 FR-1: `index.html` 이메일 모달 (`:1552`)

```js
  fetch(API_BASE + '/api/captcha')
    .then(r => {
      // fetch는 4xx·5xx에 reject하지 않는다. 이 검사가 없으면 오류 본문이
      // 정상 데이터로 흘러가 화면에 "보안문자: undefined"가 찍히고,
      // 토큰 없이 버튼만 열려 "눌리는데 아무 일도 안 나는" 상태가 된다.
      if (!r.ok) throw new Error('captcha ' + r.status);
      return r.json();
    })
    .then(data => {
      if (!data || !data.token || !data.question) throw new Error('captcha payload');
      emailModalToken = data.token;
      captchaQ.textContent = '보안문자: ' + data.question;
      submitBtn.disabled = false;
    })
    .catch(() => {
      captchaQ.textContent = '보안문자를 불러오지 못했습니다';
      errorEl.textContent = '일시적인 문제로 보안문자를 표시할 수 없습니다. 잠시 후 다시 시도해주세요.';
      // submitBtn은 :1547에서 이미 disabled=true — 여기서 건드리지 않는다(D2)
    });
```

**페이로드 검사도 함께 넣는 이유**: 서버가 200을 주면서 필드가 빠지는 경우(스키마 변경·프록시 개입)도 같은 증상을 만든다. `r.ok`만으로는 그 경우를 못 막는다. 한 줄로 닫을 수 있으므로 함께 처리한다.

### 3.2 FR-2 · FR-3 · FR-4: `board.html` 글쓰기 (`:917`)

```js
async function loadCaptcha() {
  var qEl = document.getElementById('captcha-q');
  var submitBtn = document.getElementById('w-submit');
  qEl.textContent = '로딩 중...';
  captchaToken = '';               // D4 — 실패 시 이전 토큰이 남지 않게 먼저 비운다
  submitBtn.disabled = true;       // D3 — 확보 전까지 제출 차단
  try {
    var resp = await fetch(API_BASE + '/api/captcha');
    if (!resp.ok) throw new Error('captcha ' + resp.status);
    var data = await resp.json();
    if (!data || !data.token || !data.question) throw new Error('captcha payload');
    qEl.textContent = data.question;
    captchaToken = data.token;
    document.getElementById('w-captcha').value = '';
    submitBtn.disabled = false;
  } catch (e) {
    qEl.textContent = '불러오지 못했습니다 — 잠시 후 새로고침(↻)';
    submitBtn.disabled = true;
  }
}
```

**`submitPost`와의 상호작용 확인**: `submitPost`는 시작 시 `submitBtn.disabled = true`(`:936`), 종료 시 `finally`에서 `disabled = false`(`:976`)로 되돌린다. 403 응답이면 `loadCaptcha()`를 호출하는데(`:959`), 그 안에서 다시 게이팅되므로 **`finally`가 버튼을 여는 것과 순서 경합이 생길 수 있다**.

- `:959` `loadCaptcha()`는 `await` 없이 호출되고, `:965` `return` 후 `finally`(`:976`)가 버튼을 연다.
- `loadCaptcha()`가 성공하면 자기도 `disabled = false`로 두므로 결과가 같다.
- `loadCaptcha()`가 실패하면 `disabled = true`로 두지만, 그 뒤에 `finally`가 `false`로 덮을 수 있다(비동기 순서에 따라).

**설계 결정**: `:959`를 `await loadCaptcha();`로 바꾼다. `submitPost`가 이미 `async`이므로 비용이 없고, 재로딩 결과가 `finally`보다 **먼저** 확정된다. 다만 `finally`가 무조건 `false`로 덮으므로 `finally`도 조건부로 바꾼다.

**429 분기와의 상호작용 (Check 단계 GAP-2·GAP-3에서 추가 발견)**: 같은 함수에 **두 번째 비동기 상태 변경원**이 있다 — 429 분기가 예약하는 `setTimeout(… 30000)`이다. 초안은 이를 보지 못해 두 결함이 남았다.

- **GAP-3(선행 결함)**: `return`이 `finally`를 트리거하므로 429의 `disabled = true`가 같은 틱에 덮인다 → **30초 잠금이 죽은 코드**였다.
- **GAP-2**: 잔여 타이머가 무조건 `disabled = false`라, 30초 사이에 CAPTCHA가 실패하면 **토큰 없이 버튼이 열린다** → 403 루프로 복귀.

**확정**: 버튼 상태를 단일 불변식으로 통일한다 — **"토큰이 있고 rate limit이 풀렸을 때만 열린다."** 상태를 만지는 세 지점이 모두 같은 식을 쓴다.

```js
var rateLimitedUntil = 0;   // 모듈 스코프. 모달을 닫았다 열어도 유지(서버 기준)

// 429 분기
rateLimitedUntil = Date.now() + 30000;
submitBtn.disabled = true;
setTimeout(function () {
  rateLimitedUntil = 0;
  submitBtn.disabled = !captchaToken;          // 토큰 없으면 계속 잠금
}, 30000);

// finally
submitBtn.disabled = !captchaToken || Date.now() < rateLimitedUntil;

// loadCaptcha 성공 경로
submitBtn.disabled = Date.now() < rateLimitedUntil;   // 잠금 중이면 새 토큰이 와도 유지
```

### 3.3 FR-5: 회귀 테스트 — 신규 `test_public_fetch.js` (D8)

```js
// 공개 페이지의 fetch 오류 처리 규약을 고정한다.
// fetch는 4xx·5xx에 reject하지 않으므로, .ok 검사가 없으면 오류 본문이
// 정상 데이터로 흘러가 화면에 undefined 가 찍힌다(2026-08-07 실장애).

test('CAPTCHA 로딩이 응답 상태를 검사한다', () => {
  for (const [name, src] of PAGES) {
    const m = src.match(/fetch\([^)]*\/api\/captcha[\s\S]{0,400}/);
    if (!m) continue;                       // 해당 페이지에 CAPTCHA 없음
    assert.match(m[0], /\.ok\b/, `${name}: CAPTCHA fetch에 응답 상태 검사 없음`);
    assert.match(m[0], /token/, `${name}: 토큰 존재 검사 없음`);
  }
});

test('공개 페이지의 모든 fetch가 응답 상태를 검사한다', () => {
  // 오탐 방지: 검사가 몇 줄 아래 오는 패턴이 흔하므로 윈도우를 넉넉히 잡는다(§4.2)
  for (const [name, src] of PAGES) {
    const idx = [...src.matchAll(/\bfetch\(/g)].map(m => m.index);
    for (const i of idx) {
      const window = src.slice(i, i + 600);
      assert.match(window, /\.ok\b|catch\s*\(/,
        `${name}: fetch 응답 상태·예외 처리 없음 — ${src.slice(i, i + 70)}`);
    }
  }
});

test('CAPTCHA 실패 시 제출 버튼이 잠긴 채 유지된다', () => {
  // index: 초기 disabled=true 이고 성공 경로에서만 열린다
  const email = slice(INDEX, /function openEmailModal\(btn\) \{/, '}');
  assert.match(email, /submitBtn\.disabled = true/, 'index: 초기 잠금 없음');
  const enableAt = email.indexOf('submitBtn.disabled = false');
  const okAt = email.indexOf('.ok');
  assert.ok(okAt > 0 && okAt < enableAt, 'index: .ok 검사 이후에 버튼이 열려야 한다');

  // board: loadCaptcha 가 진입 시 잠그고 성공 시에만 연다
  const load = slice(BOARD, /async function loadCaptcha\(\) \{/, '}');
  assert.match(load, /submitBtn\.disabled = true/, 'board: 로딩 시작 시 잠금 없음');
  assert.match(load, /captchaToken = ''/, 'board: 이전 토큰 초기화 없음');
});
```

`slice()` 헬퍼는 `test_answer_glance.js`에 이미 있으므로 **중복 정의하지 않고 공용 모듈로 뽑지도 않는다** — 두 파일에 각자 두면 결합이 없고, 20줄짜리 헬퍼라 중복 비용이 낮다. (공용화는 세 번째 사용처가 생기면 검토)

---

## 4. 검증 설계

### 4.1 503 재현 방법 (로컬)

환경변수를 비워 서버를 띄우면 `/api/captcha`가 503을 준다:

```bash
CAPTCHA_HMAC_SECRET= ADMIN_JWT_SECRET= ADMIN_PASSWORD= \
  uvicorn api.index:app --port 5555
curl -s -o /dev/null -w "%{http_code}\n" localhost:5555/api/captcha   # 503 기대
```

이 상태에서 브라우저로 이메일 모달·글쓰기 모달을 열어 **`undefined`가 보이지 않고 버튼이 잠긴 채인지** 확인한다.

### 4.2 전수 검사의 오탐 회피

Plan §1.3에서 6줄 윈도우로 스캔했을 때 **5건이 오탐**이었다(검사가 7~10줄 아래 있었다). 테스트는 **800자 윈도우**를 쓰고 `.ok` 또는 `catch(` 중 하나만 있어도 통과시킨다. 목적이 "모든 fetch에 오류 처리 의도가 있는가"이지 특정 스타일 강제가 아니기 때문이다. (초안은 600자였으나 실측 최장 거리가 약 520자로 한도의 87%에 달해 Act-1에서 800자로 완화했다.)

**한계 — 이 검사는 원 결함 형태를 통과시킨다**: `catch(`만 있어도 되므로 "try/catch는 있으나 `resp.ok` 검사가 없는" 코드가 빠져나간다. 변경 전 `loadCaptcha`가 정확히 그 형태였다. 따라서 중요한 엔드포인트는 CAPTCHA처럼 **개별 테스트로 별도 고정**해야 한다.

### 4.3 변이 테스트 (회귀 방지 실증)

수정 후 가드를 되돌려 테스트가 실제로 잡는지 확인한다 — 이 저장소가 `llm-fallback-hardening`·`answer-at-a-glance`에서 쓴 방식이다.

| 변이 | 기대 |
|------|------|
| `index.html`의 `if (!r.ok) throw` 제거 | CAPTCHA 테스트 실패 |
| `board.html`의 `submitBtn.disabled = true` 제거 | 버튼 게이팅 테스트 실패 |
| `board.html`의 `captchaToken = ''` 제거 | 토큰 초기화 테스트 실패 |

---

## 5. 변경 대상 파일

| 파일 | 변경 | 근거 |
|------|------|------|
| `public/index.html` | `openEmailModal`의 CAPTCHA fetch에 `r.ok` + 페이로드 검사, 문구 교체 | FR-1·4 |
| `public/board.html` | `loadCaptcha` 전면 보강(상태 검사·토큰 초기화·버튼 게이팅), `submitPost`의 `await loadCaptcha()` + `finally` 조건부 해제 | FR-2·3·4 |
| **신설** `test_public_fetch.js` | 공개 페이지 fetch 규약 회귀 테스트 3종 | FR-5, D8 |
| `.github/workflows/tests.yml` | 신규 스위트 등록 | 기존 관례 |
| `CLAUDE.md` | fetch 오류 처리 관례 기재 | Plan §7.1 |

---

## 6. 리스크 재확인 (Plan §5 대비)

| Plan 리스크 | 설계 대응 |
|-------------|-----------|
| 정상 경로 회귀 | `r.ok` 검사만 추가, 파싱·표시 로직 무변경. 200이면 기존과 동일 경로 |
| 오류 문구가 내부 정보 노출 | D5 — 고정 문구, `detail` 미사용 |
| 같은 실수 재발 | FR-5 전수 테스트 + CLAUDE.md 관례 기재 |
| **환경변수가 근본 원인인데 코드로 해결됐다고 오인** | 설계 §1.1에 명시. PR 본문·커밋 메시지에도 "발급되게 만들지 않는다"를 적는다 |
| **(신규)** `submitPost`의 `finally`가 게이팅을 덮음 | §3.2 — `await loadCaptcha()` + `finally`를 `!captchaToken` 조건부로 |
| **(신규)** `board.html`의 전역 토큰 잔존 | D4 — `loadCaptcha` 진입 시 초기화 |

---

## 7. 구현 순서 (Do 단계 체크리스트)

- [ ] `index.html` `openEmailModal` CAPTCHA fetch 보강(§3.1)
- [ ] `board.html` `loadCaptcha` 보강(§3.2) — 상태 검사·토큰 초기화·버튼 게이팅
- [ ] `board.html` `submitPost` — `await loadCaptcha()`, `finally` 조건부 해제(§3.2)
- [ ] `test_public_fetch.js` 신설 + CI 등록(§3.3)
- [ ] 변이 테스트 3종으로 회귀 방지 실증(§4.3)
- [ ] 503 재현으로 `undefined` 미노출·버튼 잠금 확인(§4.1)
- [ ] 200 정상 경로 무회귀 확인
- [ ] 기존 오프라인 스위트 전부 통과
- [ ] `CLAUDE.md`에 fetch 오류 처리 관례 기재

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-08-07 | 초안 — 두 페이지의 버튼 게이팅 구조 차이 발견(핵심), D1~D9 결정, `submitPost` finally 경합·전역 토큰 잔존 신규 리스크 2건 도출, 테스트를 별도 파일로 분리 확정 | DrunkenZealnut |
| 0.2 | 2026-08-07 | Check·Act-1 반영 — **429 분기가 두 번째 비동기 상태 변경원**임을 놓쳤던 것을 §3.2에 보강. 버튼 상태를 "토큰 있음 AND rate limit 해제" 단일 불변식으로 통일(세 지점 동일 식). 전수 검사 윈도우 600→800자, 검사 한계(`catch(`만 있어도 통과) 명문화 | DrunkenZealnut |
