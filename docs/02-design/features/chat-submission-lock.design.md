# chat-submission-lock — Design

> Plan: `docs/01-plan/features/chat-submission-lock.plan.md`(v0.1) · 작성 2026-10-22 · 기준 코드 main `758f694`
> 범위: Plan P0(전송 관문·입력 스냅숏과 실패 복원)와 P1(전송 직후 상태 표시·테스트·문서·배포)이다. Design 중 '새 상담'이 진행 중 요청을 끊지 않는 문제를 찾았다. 관문을 넣으면 그 문제가 모든 진입점으로 번지므로 P0에 넣었다(§0 D6).
> 검증 방법: main `public/index.html` 사본에 이 설계를 적용한 시제품을 만들었다(저장소 밖 `proto_patch.py`, 121줄 변경). 실제 함수를 vm에서 돌리는 행동 테스트(저장소 밖 `test_submission_proto.js`, 10개)를 main과 시제품 양쪽에서 실행했다(§6). 저장소 코드는 바꾸지 않았다.
> 서버·API·DB는 바꾸지 않는다. 바뀌는 파일은 `public/index.html`·`public/sw.js`·`test_chat_lock.js`·`CLAUDE.md`다.

## 0. 설계 결정 요약

| # | 결정 | 이유 |
|---|---|---|
| D1 | **관문은 `beginSubmission()`/`endSubmission()` 한 쌍이다.** `begin`은 '진행 중 OR 이용 제한 잠금'이면 `false`를 돌려주고, 아니면 `submitting = true`로 점유한다. `end`는 점유를 풀고 잠금 상태를 적용한다 | 진입점은 둘뿐이다. `send()`가 버튼·Enter·FAQ·게시판·`?q=`를 받고, `attachRetry`가 다시 시도를 받는다. 둘 다 같은 쌍을 부르면 판정과 해제가 한 곳에 모인다. 래퍼 함수(`runSubmission(task)`)보다 구조 검사(첫 문장·finally)로 고정하기 쉽다 |
| D2 | **버튼 상태는 계속 `applyChatLock()` 하나가 계산한다.** `btn.disabled = locked \|\| submitting`. 첨부 버튼·입력창·안내 문구는 이용 제한 잠금만 본다 | PR #103의 '상태 계산 단일 지점'을 지킨다. 진행 중에 입력과 첨부를 열어 두면 답변을 읽으며 다음 질문을 준비할 수 있다(Plan §4.1). 반환값(잠금 여부)의 의미도 바꾸지 않는다 |
| D3 | **`let submitting`은 `restoreChatLock` IIFE보다 앞에 선언한다** | 그 IIFE가 로드 시점에 `setChatLock → applyChatLock`을 부르는데, 그때 `submitting`이 TDZ면 ReferenceError가 나서 잠금 복원이 죽는다. 구조 검사(L16)로 순서를 고정한다 |
| D4 | **`send()`는 관문 통과 직후 질문·첨부를 스냅숏하고 입력창·미리보기를 비운다.** 인코딩이 실패하면 입력창이 비어 있을 때만 질문을, 대기 첨부가 비어 있을 때만 첨부를 되돌리고 `addNotice(…, 'invalid')`를 띄운다 | 인코딩 뒤에 비우면 그사이 쓴 글이 지워진다(재현 D). 실패를 잡지 않으면 질문 말풍선만 남고 아무 안내도 없다(재현 E). `invalid`이면 '다시 시도'가 붙지 않는다. 같은 파일을 다시 읽어도 같은 결과일 가능성이 높아서다. 질문 말풍선은 남긴다 — server_error와 같은 모양이고, 안내가 바로 아래에 붙는다 |
| D5 | **진행 중 FAQ는 `askQuestion`을 바꾸지 않고 관문이 막게 둔다** | `askQuestion`은 입력창을 채운 뒤 300ms 뒤에 `send()`를 부른다. 관문이 막으면 질문은 입력창에 남고 요청은 나가지 않는다. 답변이 끝난 뒤 Enter 한 번으로 보낼 수 있다 |
| D6 | **'새 상담'(`resetChat`)은 진행 중 요청을 끊는다.** `chatEpoch += 1`, `activeSend.abort()`. 끊긴 요청은 `doSend`의 catch에서 `epoch !== chatEpoch`이면 안내 없이 끝난다. 인코딩 중이면 인코딩 뒤 epoch를 보고 보내지 않는다 | Design 중 찾은 문제다. 지금도 답변 도중 '새 상담'을 누르면, 빈 화면에서 전송 버튼과 Enter가 보이지 않는 옛 답변이 끝날 때까지 잠겨 있다. `doSend`가 잠근 버튼을 옛 요청이 끝나야 풀기 때문이다(main 재현 L14). FAQ만 이 잠금을 우회해 새 요청을 하나 더 보낸다. 관문을 넣으면 그 우회까지 막혀 모든 진입점이 잠기므로, '새 상담'이 진행 중 요청을 끊어야 한다. 중지 버튼이 없는 지금, '새 상담'이 사실상 유일한 중단 수단이기도 하다 |
| D7 | **상태 말풍선은 `ensureStatus(text)` 하나로 띄운다.** `send()`는 사용자 말풍선 직후, `doSend()`는 시작할 때(다시 시도용) 부른다. `readSSE()`는 새로 만들지 않고 이어 쓰며, 문구는 지금과 같은 '질문 분석 중...'으로 바꾼다 | 관문이 요청을 하나로 묶으므로 화면의 상태 말풍선은 하나다. 지금은 응답 헤더를 받은 뒤에야 상태가 생겨, 첨부 인코딩·콜드 스타트 동안 무반응으로 보인다(Plan §2) |
| D8 | **`doSend()`는 버튼을 직접 만지지 않는다.** 첫 줄의 `btn.disabled = true`와 finally의 `applyChatLock()`·focus를 지우고, 그 일은 관문(`endSubmission`)이 한다 | 버튼을 바꾸는 곳이 둘이면 다시 갈라진다. finally에서 버튼을 무조건 열지 않는다는 PR #103 규칙은 `endSubmission`이 이어받는다(L6 갱신) |
| D9 | **Enter 처리기(`keydown`)는 바꾸지 않는다** | 이미 `!btn.disabled`를 본다. 버튼이 관문 점유 시점부터 잠기므로 인코딩 중 Enter도 막힌다. `send()` 첫 문장의 관문이 이중으로 막는다. 막힌 Enter가 줄바꿈을 넣는 지금의 동작과 한글 IME 조합 중 Enter 처리는 그대로 둔다(§9) |
| D10 | **`sw.js` `VERSION`을 올린다**(`v11-…`). 바뀌는 것은 `index.html` 인라인 스크립트뿐이다 | HTML 내비게이션은 network-first라 온라인 사용자에게는 올리지 않아도 새 페이지가 간다. 다만 오프라인 셸 캐시(`'/'`)를 새 판으로 바꾸기 위해 PR #103처럼 올린다 |
| D11 | **PR 1개, 커밋 1개** | 바뀌는 파일 4개가 한 동작을 이룬다. 쪼개면 중간 커밋에서 L6이 깨진다 |

## 1. 진입점과 현재 검사 (main `758f694`)

| 진입점 | 경로 | 진행 중 검사 | 이용 제한 검사 |
|---|---|---|---|
| 전송 버튼 | `btn` click → `send()` | 버튼 disabled 속성(`doSend` 첫 줄에서야 켜짐) | `send()` 첫 줄 |
| Enter | `keydown` → `!btn.disabled`면 `send()` | 위와 같음 | `send()` 첫 줄 |
| FAQ | `item.onclick` → `askQuestion` → 300ms → `send()` | **없음** | `send()` 첫 줄 |
| 게시판 '질문하기' | `.board-ask-btn` → `askQuestion` | **없음** | `send()` 첫 줄 |
| `?q=` 링크 | 로드 시 `askQuestion(q)` | **없음** | `send()` 첫 줄 |
| 다시 시도 | `attachRetry` click → `doSend()` 직접 | **없음** | 클릭 처리기 첫 줄 |

설계 후에는 여섯 경로 모두 `beginSubmission()`을 지난다. 앞의 다섯은 `send()` 첫 문장에서, 다시 시도는 클릭 처리기 첫 문장에서다.

## 2. 상태와 관문

`let chatLockTimer = null;` 바로 아래에 둔다(D3).

```js
// 전송 관문 상태(아래 beginSubmission). restoreChatLock보다 먼저 선언한다 — applyChatLock이 submitting을 읽는다.
let submitting = false;
let chatEpoch = 0;       // 새 상담마다 1씩 — 그 전에 시작한 전송은 조용히 끝낸다
let activeSend = null;   // 진행 중 요청의 AbortController — 새 상담이 끊는다
```

`applyChatLock()`은 한 줄만 바뀐다.

```js
  btn.disabled = locked || submitting;   // 진행 중에는 전송만 막는다 — 입력·첨부는 다음 질문용으로 연다
```

관문 함수는 전송 절(`send()` 앞)에 둔다.

```js
function beginSubmission() {
  if (submitting || isLockActive(chatLock, Date.now())) { applyChatLock(); return false; }   // 입력창 안내가 잠금 사유를 보여 준다
  submitting = true;
  applyChatLock();
  return true;
}

function endSubmission() {
  submitting = false;
  // 잠금(일일 횟수·차단)이면 계속 막는다 — 결과와 무관하게 버튼을 다시 열면 한도에 걸린 뒤에도 정상처럼 보인다
  if (!applyChatLock()) msgInput.focus();
}
```

- 판정과 점유 사이에 `await`가 없다. 그래서 같은 틱에 들어온 두 클릭도 하나만 통과한다.
- 진행 중 상태(`submitting`)는 저장하지 않는다. 새로고침하면 요청 자체가 끊기기 때문이다. 이용 제한 잠금(`chatLock`)만 localStorage에 남는다(PR #103 그대로).

## 3. 전송 흐름

### 3.1 `send()`

```js
async function send() {
  if (!beginSubmission()) return;
  try {
    const text = msgInput.value.trim();
    const files = pendingFiles.slice();
    if (!text && files.length === 0) return;
    const epoch = chatEpoch;

    expandChat();
    // (사용자 말풍선 — 지금 코드 그대로, pendingFiles → files)
    addMsg('user', displayHtml);

    // 입력은 인코딩 전에 비운다 — 인코딩 중에 쓴 다음 질문이 지워지지 않게
    msgInput.value = '';
    msgInput.style.height = 'auto';
    pendingFiles = [];
    renderPreview();
    ensureStatus('질문 보내는 중...');

    const attachments = [];
    try {
      for (const f of files) {
        attachments.push({ filename: f.name, content_type: guessMime(f), data: await fileToBase64(f) });
      }
    } catch (e) {
      removeStatus();
      if (epoch !== chatEpoch) return;   // 그사이 새 상담 — 조용히 끝낸다
      // 그사이 쓴 글·고른 파일은 덮지 않는다
      if (!msgInput.value.trim()) { msgInput.value = text; msgInput.dispatchEvent(new Event('input')); }   // §12 C2
      if (!pendingFiles.length) { pendingFiles = files; renderPreview(); }
      addNotice('첨부 파일을 읽지 못해 보내지 않았습니다. 파일을 확인한 뒤 다시 보내 주세요.', 'invalid');
      return;
    }
    if (epoch !== chatEpoch) return;     // 인코딩 중 새 상담
    await doSend(text, attachments);
  } finally {
    endSubmission();
  }
}
```

- 빈 입력이면 관문을 잡았다가 finally에서 바로 푼다. 따로 분기하지 않아도 된다. 이때 입력창으로 포커스가 간다. main은 빈 입력 전송에서 포커스를 옮기지 않았지만, 해는 없다(Check GAP-2).
- 관문에 막힌 호출은 입력창을 건드리지 않는다. 그래서 진행 중 FAQ의 질문이 입력창에 남는다(D5, L8).

### 3.2 `doSend()`

바뀌는 부분만 적는다.

```js
async function doSend(text, attachments) {
  const epoch = chatEpoch;
  const ctrl = new AbortController();
  activeSend = ctrl;
  // … resetIdleTimeout 그대로 …
  ensureStatus('질문 보내는 중...');   // 다시 시도도 전송 직후 상태를 보인다
  try {
    // … fetch·readSSE·outcome 처리 그대로 …
  } catch (e) {
    removeStatus();
    if (epoch !== chatEpoch) return;   // 새 상담이 끊은 요청 — 빈 화면에 오류를 띄우지 않는다
    // … 시간 초과·오류 안내 그대로 …
  } finally {
    clearTimeout(timeoutId);
    if (activeSend === ctrl) activeSend = null;
    removeStatus();
  }
}
```

지우는 것: 첫 줄 `btn.disabled = true;`, finally의 `if (!applyChatLock()) msgInput.focus();`(D8).

### 3.3 다시 시도 (`attachRetry`)

```js
  retryBtn.addEventListener('click', async () => {
    if (!beginSubmission()) return;   // 진행 중·잠금이면 아무 일도 없고, 버튼은 나중에 다시 누를 수 있다
    retryBtn.disabled = true;
    try { await doSend(text, attachments); } finally { endSubmission(); }
  });
```

지금은 이용 제한만 보고, 누르는 즉시 비활성이 된다. 바꾼 뒤에는 막힌 클릭이 버튼을 소비하지 않는다.

### 3.4 새 상담 (`resetChat`)

확인 대화상자 다음 줄에 넣는다.

```js
  // 진행 중인 전송은 끊고 조용히 끝낸다 — 그대로 두면 관문이 보이지 않는 옛 답변이 끝날 때까지 새 질문을 막는다
  chatEpoch += 1;
  if (activeSend) activeSend.abort();
```

`abort()`가 일으키는 거절은 마이크로태스크로 처리된다. 그래서 `resetChat`의 나머지(대화 비우기·입력 초기화)가 먼저 끝나고, 그 뒤 `doSend` catch(안내 없음) → finally → `endSubmission` 순으로 관문이 풀린다(L14).

### 3.5 상태 말풍선

```js
// 진행 중 상태 말풍선. 관문이 요청을 하나로 묶으므로 화면에는 하나만 있다 — 전송 직후 띄우고 readSSE가 이어 쓴다.
function ensureStatus(text) {
  return chat.querySelector('.msg.status') || addMsg('status', text);
}
```

`readSSE()` 첫 줄의 `let statusEl = addMsg('status', '질문 분석 중...');`는 아래 두 줄로 바꾼다.

```js
  let statusEl = ensureStatus('질문 분석 중...');
  statusEl.textContent = '질문 분석 중...';
```

응답 헤더 뒤의 문구가 지금과 같아진다('질문 분석 중...' → 서버 status 이벤트가 덮어씀). 헤더 전에는 '질문 보내는 중...'이 보인다.

## 4. 바뀌지 않는 것

- 서버 계약(SSE 이벤트·거절 코드·`retry_after`), 이용 제한 잠금의 판정·저장·해제(`guardLockFromEvent`·`setChatLock`·localStorage), L1~L5.
- `askQuestion`, `keydown`, 첨부 선택·미리보기(`fileInput`·`renderPreview`), 답변 렌더링(`readSSE` 본문·`md()`·`finalize.js`).
- 입력 거절(`invalid`) 때 지운 질문을 되돌리는 `doSend`의 기존 분기. 이번 스냅숏은 인코딩 실패에만 쓴다. 단 복원 조건은 §12 C2에서 `.trim()`으로 바꿨다(줄바꿈뿐인 입력창을 빈칸으로 본다).

## 5. 재현 대비 (vm 시제품, 2026-10-22)

| 재현 | main | 시제품 |
|---|---|---|
| A 첨부 인코딩 중 두 번째 전송 | 요청 2건, 인코딩 중 버튼 열림 | 요청 1건, 인코딩 중 버튼 잠김 |
| B 진행 중 FAQ | 요청 2건 | 요청 1건, 질문은 입력창에 남음 |
| C 진행 중 다시 시도 | 요청 2건 | 요청 1건, 다시 시도 버튼은 남음 → 끝난 뒤 누르면 나감 |
| D 인코딩 중 입력 | 지워짐 | 남음 |
| E 파일 읽기 실패 | 예외, 안내 0 | 관문 해제, 질문·첨부 복원, 안내 1(invalid), 요청 0 |
| (D6) 진행 중 새 상담 | 버튼·Enter가 옛 요청이 끝날 때까지 잠김(FAQ로는 하나 더 보냄) | 요청 끊김, 버튼 즉시 열림, 안내 0. 첨부 인코딩 중이면 끊을 요청이 없어 파일 읽기가 끝날 때(ms 단위) 풀린다(Check DG-2) |

## 6. 테스트 (`test_chat_lock.js`, 노드, CI 등록됨)

### 6.1 L6 갱신 — 불변식은 그대로, 위치만 옮긴다

| 지금 단언 | 바뀐 단언 |
|---|---|
| `doSend` finally에 `applyChatLock()`, `btn.disabled = false` 없음 | `endSubmission`에 `applyChatLock()`, `btn.disabled = false` 없음. `doSend`에는 `btn.disabled =` 대입 자체가 없음 |
| `send` 첫 문장 `if (isLockActive(chatLock, Date.now()))` | `send` 첫 문장 `if (!beginSubmission()) return;`. 이용 제한 검사는 `beginSubmission`이 한다 |
| `code === 'server_error') attachRetry`, `addErrorWithRetry`는 `addNotice` | 그대로 |

### 6.2 L7~L16 — 행동 테스트(vm)와 구조 검사

실제 함수(`send`·`doSend`·`attachRetry`·`addErrorWithRetry`·`askQuestion`·`resetChat`·`applyChatLock`·`setChatLock`·`removeStatus`·관문·`ensureStatus`)를 선언 시그니처로 잘라 vm에서 돌린다. 다음은 모의로 바꾼다.
- `fetch`: 신호 abort 시 AbortError
- `readSSE`: 테스트가 끝내는 Promise, abort 시 거절
- `fileToBase64`: 테스트가 resolve·reject
- 채팅 영역·DOM, `setTimeout`

| # | 사례 | main | 시제품 |
|---|---|---|---|
| L7 | 첨부 인코딩 중 두 번째 `send()` → 요청 1, 말풍선 1, 인코딩 중 버튼 잠김, 끝나면 열림 | 실패 | 통과 |
| L8 | 진행 중 `askQuestion` + 300ms → 요청 1, 입력창에 FAQ 질문 | 실패 | 통과 |
| L9 | 진행 중 다시 시도 → 요청 1, 버튼 남음 / 끝난 뒤 → 요청 2 | 실패 | 통과 |
| L10 | 전송 시작 시 입력창 비움, 인코딩 중 쓴 글 보존 | 실패 | 통과 |
| L11 | 읽기 실패 → 요청 0, 질문·첨부 복원, 안내 `invalid` 1, 버튼 열림, 상태 0 / 그사이 쓴 글은 덮지 않음 | 실패 | 통과 |
| L12 | 진행 중 quota 잠금 → 끝난 뒤에도 버튼 잠김, 다음 `send()` 요청 0(입력 유지) | 통과 | 통과 |
| L13 | 스트림 실패 → 관문 해제, 안내 `server_error`, 다음 전송 가능 | 통과 | 통과 |
| L14 | 진행 중 `resetChat()` → 관문 즉시 해제, 안내 0, 상태 0 | 실패 | 통과 |
| L15 | 인코딩 중에도 상태 1, 응답 처리 중에도 1(새로 만들지 않음), 끝나면 0 / `readSSE`가 `ensureStatus` 사용 | 실패 | 통과 |
| L16 | 구조: `send` 첫 문장·finally, `attachRetry` 관문, `askQuestion`은 `send()`만, `doSend`에 버튼 대입 없음, `applyChatLock` 병합, `let submitting`이 `restoreChatLock` 앞 | 실패 | 통과 |

L12·L13은 main에서도 통과한다. 관문을 넣으면서 깨지기 쉬운 기존 동작을 지키는 회귀 방지용이다. 시제품 기준 기존 L1~L5는 통과했고, L6은 §6.1처럼 고쳐야 한다(시제품에서 옛 L6 실패 확인).

### 6.3 변이 검사

하나씩 되돌려 L6~L16 중 하나 이상이 실패해야 한다.

| # | 변이 | 잡는 테스트(예상) |
|---|---|---|
| M1 | `send` 첫 문장의 관문 검사 삭제 | L7·L8·L16 |
| M2 | `beginSubmission`의 `submitting = true` 삭제 | L7·L8·L9 |
| M3 | `endSubmission`을 finally 밖으로(예외 시 미해제) | L11·L14·L16. L13은 못 잡는다 — `doSend`가 예외를 안에서 처리해 `send`가 정상 종료한다(Check GAP-3) |
| M4 | `applyChatLock`이 `submitting`을 무시 | L7·L16 |
| M5 | 입력창 비우기를 인코딩 뒤로 | L10 |
| M6 | 인코딩 실패 복원 삭제 | L11 |
| M7 | 복원이 그사이 쓴 글을 덮음(빈칸 검사 삭제) | L11 |
| M8 | `attachRetry`가 관문 없이 `doSend` | L9·L16 |
| M9 | `resetChat`의 `abort()` 삭제 | L14 |
| M10 | `doSend` catch의 epoch 검사 삭제 | L14(안내 1) |
| M11 | `readSSE`가 `addMsg('status')`로 되돌아감 | L15 |
| M12 | `let submitting`을 `restoreChatLock` 뒤로 | L16 |
| M13 | `endSubmission`이 `btn.disabled = false`로 무조건 열기 | L6·L12 |

## 7. 브라우저 확인 (Do)

vm 테스트는 브라우저가 아니다(Plan R5). 그래서 로컬 모의 서버와 Playwright로 실제 클릭을 확인한다.
- **모의 서버:** 저장소 밖 스크립트로, `public/`을 정적으로 서비스한다. `/api/chat/stream`(GET·POST)은 지연 SSE를 돌려준다(session → status → chunk 여러 개 → done, 약 3초). 받은 요청 수를 세는 엔드포인트를 두고, 다음 요청을 `server_error`로 만드는 제어 엔드포인트도 둔다.
- **포트:** 5571. 5556은 다른 작업이 쓰고 있다.
- **DB·LLM·프로덕션은 쓰지 않는다.**

| 시나리오 | 기대 |
|---|---|
| 첨부(큰 텍스트 파일) + 전송 버튼 연타·Enter 연타 | 서버 수신 1 |
| 답변 수신 중 FAQ 선택 | 수신 1, 입력창에 질문 |
| `server_error` 뒤 새 질문 수신 중 다시 시도 | 수신 변화 없음, 끝난 뒤 다시 시도 → +1 |
| 답변 수신 중 새 상담 | 버튼 즉시 열림, 빈 화면에 안내 없음 |
| 콘솔 오류 | 0 |

## 8. 구현 순서

1. `public/index.html`에 §2~§3을 넣는다. 시제품 `proto_patch.py`의 치환과 같은 내용이다.
2. `test_chat_lock.js`의 L6을 갱신하고 L7~L16을 옮긴다. 시제품 `test_submission_proto.js`의 하네스를 그대로 가져온다.
3. 노드 테스트 전부(`test_chat_lock.js`·`test_answer_renderer.js`·`test_answer_glance.js`·`test_public_fetch.js`)와 CI 동등 오프라인 스위트를 돌린다.
4. 변이 M1~M13을 돌린다.
5. 모의 서버와 Playwright로 §7을 확인한다.
6. `sw.js` `VERSION`을 올리고 CLAUDE.md를 갱신한다(§10).
7. 독립 리뷰(code-analyzer)를 받는다. 지적은 재현한 뒤 고치고 PR을 연다.

## 9. 위험·롤백

| # | 위험 | 대응 |
|---|---|---|
| R1 | 관문이 풀리지 않아 전송이 영구히 막힌다 | 해제는 `send`·다시 시도의 finally 두 곳이 같은 `endSubmission`을 부르는 방식뿐이다. 다음 경우가 모두 finally를 지난다(L11·L13·L14): 인코딩 예외, fetch·readSSE 예외, 60초 무활동 abort, 새 상담 abort |
| R2 | 이용 제한 잠금과 겹친다 | 상태 계산은 `applyChatLock` 하나다. L12가 진행 중 quota 잠금을 고정하고, L1~L5는 바꾸지 않는다 |
| R3 | 입력을 일찍 비우면 실패 시 질문이 사라진다 | 복원한다(빈칸일 때만). L11이 두 경우를 고정한다 |
| R4 | 막힌 Enter·FAQ가 고장으로 보인다 | 버튼 비활성 표시와 전송 직후 상태 말풍선을 쓴다. 진행 중 FAQ는 입력창에 질문을 남긴다 |
| R5 | `AbortController.abort()`를 쓰므로 오래된 브라우저에서는 끊기지 않는다 | 이미 `doSend`가 무활동 상한에 같은 API를 쓴다. 새 의존이 아니다 |
| R6 | 새 상담이 끊어도 서버는 그 요청을 끝까지 처리할 수 있다(쿼터 1회 소비) | 지금도 같다(옛 요청이 화면 밖에서 돈다). 서버 측 중단은 범위 밖이다 |
| R7 | 한글 IME 조합 중 Enter가 전송과 겹친다 | D9로 동작을 바꾸지 않는다. 관문이 이중 전송은 막는다. 조합 중 전송(마지막 글자 누락) 자체는 별도 과제(§11) |

**롤백.** `public/index.html`·`public/sw.js`·`test_chat_lock.js`·`CLAUDE.md` 한 커밋이다. 되돌리면 끝나고, 서버·DB·환경 변경은 없다.

## 10. CLAUDE.md 갱신안

Abuse Guard 절의 '거절 계약' 항목에서 지킬 것 ②를 다음으로 바꾼다.

> ② 전송이 끝날 때(`endSubmission`) 버튼을 무조건 열지 말 것(`applyChatLock()`)

그 바로 아래에 한 항목을 더한다.

> - **전송 관문(진행 중 잠금)** — 전송을 시작하는 경로(전송 버튼·Enter·FAQ·게시판 '질문하기'·`?q=`·다시 시도)는 모두 `beginSubmission()`을 지나고 finally의 `endSubmission()`이 푼다.
>   - 판정은 '진행 중 OR 이용 제한 잠금'이다.
>   - 버튼 상태는 `applyChatLock()` 하나가 계산하고(`btn.disabled = locked || submitting`), 진행 중에는 전송 버튼만 잠근다.
>   - `send()`는 관문 통과 직후 입력을 스냅숏해 비우고, 첨부 인코딩이 실패하면 빈칸일 때만 되돌린다.
>   - '새 상담'은 진행 중 요청을 끊는다(`chatEpoch`·`activeSend`). 끊지 않으면 관문이 보이지 않는 옛 답변이 끝날 때까지 새 질문을 막는다.
>   - `let submitting`은 `restoreChatLock` IIFE보다 앞에 둔다(TDZ).
>   - 2026-10-22 재현: 진행 중 FAQ·다시 시도·첨부 인코딩 중 연타가 요청을 하나 더 보냈다.
>   - 회귀는 `test_chat_lock.js` L6~L16.

## 11. 범위 밖·후속

1. **한글 IME 조합 중 Enter**(`e.isComposing`). 조합 중인 마지막 글자가 빠진 채 보내질 수 있다. 브라우저마다 다르고 Playwright로 재현하기 어려워 따로 다룬다.
2. **답변 중지 버튼.** 지금은 '새 상담'(D6)이 대화를 비우면서 끊는다. 대화를 유지한 채 끊는 기능은 별도 과제다.
3. **`?q=` 외부 링크 자동 전송**(도입 검토 #5).
4. **서버 측 중복 방지.**
5. **진행 중 FAQ가 써 둔 초안을 덮는다**(Check DG-1). `askQuestion`은 입력창을 조건 없이 채운다. 진행 중에 FAQ·게시판·`?q=`를 누르면, 답변을 읽으며 써 둔 다음 질문이 그 질문으로 바뀐다. main에서는 FAQ가 바로 전송돼 초안이 역시 사라졌으므로 회귀는 아니다. D4의 '빈칸일 때만' 원칙을 넓힐지는 후속으로 정한다.
6. **드래그앤드롭 첨부는 이용 제한 잠금을 보지 않는다**(Check DG-3, PR #103부터 있던 동작). 잠금 중에도 파일은 들어가지만, 전송은 관문이 막아 요청은 0이다.

## 12. 구현 중 변경 (Do, 2026-10-22)

### 12.1 구현

- **`public/index.html`.** 시제품 `proto_patch.py`를 그대로 적용했다. 검증한 시제품과 바이트까지 같은 것을 확인한 뒤, 전송 절 머리 주석 두 줄을 하나로 합쳤다.
- **나머지 파일.**
  - `public/sw.js`: `VERSION`을 `v11-2026-10-22`로 올렸다.
  - `test_chat_lock.js`: L6을 갱신하고 L7~L16을 더했다.
  - CLAUDE.md: §10대로 고쳤다. 문구는 C4로 정정했다. 그 밖에 기록하지 않았던 차이가 셋 있다(Check GAP-4). Commands 줄의 `test_chat_lock.js` 설명에 '전송 관문'을 넣었다. 새 항목은 하위 목록이 아니라 한 문단이다. 재현 문구에 '(실제 브라우저)'와 '(연타 3번에 요청 3건)'을 더했다.
- 설계와 어긋난 곳은 없다. 아래 C1~C4는 보강이다.

### 12.2 보강

| # | 변경 | 계기 |
|---|---|---|
| C1 | L14에 '대화 초기화'를 인코딩 중에 누르는 사례 둘을 더했다. 읽기가 끝나면 요청 0건이어야 하고, 읽기가 실패하면 복원·안내가 없어야 한다. 대기는 `settle()`로 바꿨다 | D6의 나머지 두 갈래를 지키는 테스트가 없었다. 처음 변이 검사에서 M14는 L14가 멈추는 바람에 뒤 테스트가 취소돼 '검출'로 보였다. 회귀가 생기면 멈추지 않고 단언으로 실패하게 했다 |
| C2 | 복원 조건 `!msgInput.value`를 `!msgInput.value.trim()`으로 바꿨다. 인코딩 실패 복원과 기존 입력 거절(`invalid`) 복원 두 곳이다 | 리뷰 1(재현됨). 진행 중 Enter는 막히지만 입력창에 줄바꿈을 넣는다. 그래서 읽기에 실패하면 첨부만 돌아오고 질문은 사라졌다 |
| C3 | 테스트 단언을 보강했다. ① 막힌 호출 뒤에도 버튼이 잠겨 있다(L7·L8·L9) ② 다시 시도 직후, 마이크로태스크 전에 상태 말풍선이 1개다(L9) ③ 새로 고른 첨부 보존, 줄바꿈뿐인 입력, `invalid` 복원(L11) ④ 구조: 다시 시도의 관문이 try 밖 첫 문장, `doSend` 호출처가 정확히 2곳, Enter·버튼 배선(L16) | 리뷰 2~5. 리뷰어 변이 MA(다시 시도 관문을 try 안으로)·MB(send 관문을 try 안으로)·MD(새 첨부를 덮음)·ME(다시 시도 직후 상태 삭제)가 16/16 통과하던 공백이다. MA 상태에서는 막힌 다시 시도가 남의 관문을 풀어 FAQ가 요청 2건을 보냈다 |
| C4 | CLAUDE.md의 '새 상담'을 "'대화 초기화'(`resetChat`)"로 고쳤다 | 리뷰 6. 화면 라벨(`#menu-reset-btn`)은 '대화 초기화'다 |

### 12.3 검증

- `test_chat_lock.js` 16/16(L1~L16).
- CI 동등 28단계 PASS(오프라인 26단계 + `test_chat_lock.js` + PostgreSQL 17). 리뷰 반영 뒤 다시 돌렸다.
- 변이 22/22 검출(저장소 밖 `mutate.py`, 작업 트리를 건드리지 않는 사본에서 실행):
  - M1~M13: 설계 §6.3
  - M14~M16: 인코딩 중 초기화, `activeSend`
  - M17~M20: 리뷰 MA·MB·MD·ME
  - M21~M22: C2 되돌림
- 브라우저 확인. 로컬 모의 서버(새 코드는 5571, main은 5572)와 Playwright로 했고, DB·LLM은 쓰지 않았다. C2는 이 확인 뒤에 들어갔지만 실패 복원 경로만 바꾸며, 그 경로는 L11이 고정한다.

| 시나리오 | main | 새 코드 |
|---|---|---|
| 첨부(900KB) + 전송 버튼 2번 + Enter를 같은 틱에 | 요청 3건, 사용자 말풍선 3개, 버튼 열림, 상태 0 | 요청 1건, 말풍선 1개, 버튼 즉시 잠김, 상태 1, 입력창 즉시 비움 |
| 답변 중 FAQ | 요청 2건 | 1건. 입력창에 FAQ 질문이 남고, 답변이 끝난 뒤 보내면 그 질문이 나감 |
| 서버 오류 뒤 새 질문 수신 중 다시 시도 | 요청 +1(총 3) | 변화 없음(총 2), 버튼 남음. 답변이 끝난 뒤 누르면 +1 |
| 답변 중 대화 초기화 | 옛 답변이 끝날 때까지 버튼 잠김 | 300ms 안에 버튼 열림, 안내 0, 새 질문 전송 가능 |
| 콘솔 오류·경고 | — | 0·0 |

### 12.4 리뷰 미반영

- **막힌 Enter도 `preventDefault`.** D9(한글 IME 조합 중 Enter 영향 미확인)에 따라 그대로 두고, 그 결과로 생기던 문제만 C2로 막았다.
- **`done` 뒤 `reader.cancel()` 대기 중의 창.** 1ms 미만의 이 창에서 초기화가 일어나면, 액션 바가 새 화면에 붙을 수 있다. 이론상 창이라 수용한다.
- **진행 중 다시 시도 버튼의 시각적 비활성.** 범위 밖이다. 버튼은 남아 있어 나중에 누를 수 있다.
- **L14의 '상태 0' 단언.** 대화를 비우기만 해도 참이 된다. 의미 있는 단언은 버튼 잠김 해제와 안내 0건이다.

### 12.5 Check 반영 (2026-10-22)

- gap-detector Match Rate 99.4%(81항목: 일치 78·의도된 변경 2·부분 1·누락 0). 분석은 `docs/03-analysis/chat-submission-lock.analysis.md`.
- 문서 갭 GAP-1~4는 이 문서에 반영했다(§3.1 코드·§4·§6.3 M3·§12.1). 설계 공백 DG-1·DG-3은 §11에 후속으로, DG-2는 §5에 적었다.
- 테스트 공백 중 '응답 헤더 전 초기화'를 L14에 더했다. 콜드 스타트 중 fetch 자체가 AbortError로 끝나는 경로다. 이 사례 추가 뒤 `test_chat_lock.js`는 16/16이고, 겨냥한 변이 M9(abort 삭제)·M10(끊긴 요청 안내 억제 삭제)는 사본에서 L14가 잡는다. 전체 변이 재실행은 하지 않았다. 세션 재시작으로 저장소 밖 스크립트가 지워졌고, 이번 변경은 단언 추가뿐이라 기존 검출이 줄 수 없다.

## Version History

| 버전 | 날짜 | 내용 | 작성 |
|---|---|---|---|
| 0.1 | 2026-10-22 | 초안 — 관문 한 쌍(D1~D3), 스냅숏·복원(D4), 새 상담 끊기(D6, Design 중 찾은 문제), 상태 말풍선(D7). 시제품 vm 테스트 10개: main 8 실패, 시제품 10 통과 | Claude |
| 0.2 | 2026-10-22 | Do 기록(§12): 시제품 그대로 구현, 보강 C1~C4(인코딩 중 초기화 사례·trim 복원·리뷰 테스트 공백·CLAUDE.md 라벨), 변이 22/22, CI 28단계, 브라우저 main 대비 | Claude |
| 0.3 | 2026-10-22 | Check 반영(§12.5): 문서 갭 4건 정정, 설계 공백 DG-1~3 기록, L14에 헤더 전 초기화 사례 | Claude |
