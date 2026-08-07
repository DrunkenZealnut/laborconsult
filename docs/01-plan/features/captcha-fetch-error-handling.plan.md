---
template: plan
version: 1.2
feature: captcha-fetch-error-handling
date: 2026-08-07
author: DrunkenZealnut
project: laborconsult
---

# captcha-fetch-error-handling Planning Document

> **Summary**: CAPTCHA 로딩 `fetch`에 `r.ok` 검사가 없어 서버 503이 정상 경로로 흘러가 화면에 "보안문자: undefined"로 표시되고 발송·등록이 조용히 막히던 문제를 고친다. 서버 설정 오류가 사용자에게 원인 불명의 UI 파손으로 보이지 않게 하는 것이 목적이다.
>
> **Project**: laborconsult
> **Version**: 0.1
> **Author**: DrunkenZealnut
> **Date**: 2026-08-07
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | `/api/captcha`가 `CAPTCHA_SECRET` 미설정 시 503을 반환하는데, 프론트가 `fetch`의 응답 상태를 확인하지 않는다. `fetch`는 HTTP 오류에 reject하지 않으므로 `.catch()`가 안 걸리고 503 본문이 정상 데이터처럼 파싱돼 **"보안문자: undefined"**가 표시된다. 버튼은 활성화되지만 토큰이 없어 전송이 막히고, 사용자는 원인을 알 수 없다. |
| **Solution** | CAPTCHA 로딩 2곳(이메일 모달·게시판 글쓰기)에 `r.ok` 검사를 추가해 서버 오류를 실패 경로로 보내고, "일시적인 서버 문제" 취지의 실행 가능한 안내로 대체한다. 동일 실수가 재발하지 않게 회귀 테스트로 고정한다. |
| **Function/UX Effect** | 서버 설정 오류 시 사용자는 `undefined` 대신 명확한 안내를 받고, 전송 버튼이 활성화되지 않아 "눌리는데 안 되는" 혼란이 사라진다. 정상 동작 시 변화 없음. |
| **Core Value** | 장애가 **"오류"로 보이게** 만든다 — 이 저장소가 `llm-fallback-hardening`에서 세운 원칙("조용히 나빠지는 것은 허용, 조용히 틀리는 것은 차단")을 프론트 계층에 동일하게 적용한다. |

---

## 1. Overview

### 1.1 Purpose

2026-08-07 실제 장애로 드러난 결함을 고친다. 사용자 신고는 "이메일 발송 시 보안문제가 undefined라고 나와서 발송이 안 됩니다"였고, 원인 추적 결과 **서버 설정 문제와 프론트 오류 처리 누락이 겹친 것**이었다.

### 1.2 Background — 장애 실측 (2026-08-07)

**① 서버 측 (운영 이슈, 코드 결함 아님)**

```
api/index.py:416  ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
api/index.py:417  JWT_SECRET     = os.environ.get("ADMIN_JWT_SECRET", ADMIN_PASSWORD)
api/index.py:419  CAPTCHA_SECRET = os.environ.get("CAPTCHA_HMAC_SECRET") or JWT_SECRET
api/index.py:798  if not CAPTCHA_SECRET: raise HTTPException(503, "서버 설정 오류")
```

Vercel 프로덕션에 세 변수가 모두 없어 `CAPTCHA_SECRET`이 빈 문자열이 됐다. 프로덕션 직접 확인:

```
GET https://laborconsult.vercel.app/api/captcha → HTTP 503 {"detail":"서버 설정 오류"}
```

운영자가 환경변수를 설정해 해결 진행 중이다. **본 계획의 범위가 아니다.**

**② 프론트 측 (본 계획의 대상)**

```js
// public/index.html:1552
fetch(API_BASE + '/api/captcha')
  .then(r => r.json())        // ← 503이어도 fetch는 reject 안 함. 본문 파싱 성공
  .then(data => {
    emailModalToken = data.token;                        // undefined
    captchaQ.textContent = '보안문자: ' + data.question;  // "보안문자: undefined"
    submitBtn.disabled = false;                          // 버튼은 활성화
  })
  .catch(() => { /* 절대 실행되지 않음 */ });
```

`fetch`는 **네트워크 실패에만 reject**하고 4xx·5xx는 정상 이행(resolve)한다. `r.ok` 검사가 없으면 오류 응답이 데이터 경로로 그대로 흘러간다. 그 결과:

- 화면: `보안문자: undefined`
- 상태: `emailModalToken = undefined`
- 버튼: 활성화되지만, 제출 시 `if (!emailModalToken || ...)`에 걸려 아무 반응 없음
- 사용자 인지: **원인 불명**

`public/board.html:921`의 게시판 글쓰기 CAPTCHA도 동일 패턴이다(`qEl.textContent = data.question` → `undefined`).

### 1.3 범위 확정을 위한 전수 조사

공개 페이지 3종의 `fetch` 호출 14곳을 전부 확인했다.

| 파일 | `fetch` | `r.ok` 검사 누락 | 판정 |
|------|:-------:|------------------|------|
| `index.html` | 6 | `:1552` CAPTCHA | **결함** |
| `board.html` | 6 | `:921` CAPTCHA | **결함** |
| `admin.html` | 2 | 없음 | — |

초기 스캔에서 누락으로 잡혔던 5건은 **오탐**이었다:

| 위치 | 실제 상태 |
|------|-----------|
| `index.html:1679` (chat/stream POST) | `:1693`에 `if (!resp.ok)` — status·detail까지 표시 |
| `admin.html:220` (`adminFetch`) | `:222` 401 → logout, `:226` `!resp.ok` → alert |
| `board.html:949` (글쓰기 POST) | `:955` `!resp.ok` → 403이면 CAPTCHA 재로딩, 429면 30초 잠금 |
| `board.html:1003` (삭제 POST) | `:1009` `!resp.ok` → 토스트 |

즉 **이 저장소는 이미 `r.ok` 검사가 관례로 정착돼 있고, CAPTCHA 로딩 2곳만 빠져 있다.** 범위가 작다는 것이 이 계획의 중요한 결론이다 — 광범위한 리팩터링이 아니라 국소 수정이다.

### 1.4 Related Documents

- `docs/archive/2026-08/llm-fallback-hardening/` — "빈 응답을 실패로 승격"과 같은 문제 유형. 그쪽은 LLM 응답, 이쪽은 HTTP 응답
- `docs/01-plan/features/board-write-security.plan.md` — CAPTCHA 도입 사이클
- `CLAUDE.md` — 게시판 글쓰기 보안 체인(CAPTCHA → rate limit → 검증 → bcrypt → INSERT)

---

## 2. Scope

### 2.1 In Scope

- [ ] **FR-1** `public/index.html:1552` 이메일 모달 CAPTCHA 로딩에 `r.ok` 검사 추가
- [ ] **FR-2** `public/board.html:921` 게시판 글쓰기 CAPTCHA 로딩에 `r.ok` 검사 추가
- [ ] **FR-3** 실패 시 전송/등록 버튼이 활성화되지 않도록 보장(현재 index는 오류에도 `disabled = false`)
- [ ] **FR-4** 사용자 안내 문구를 실행 가능하게(원인 + 다음 행동)
- [ ] **FR-5** 회귀 테스트 — 공개 페이지의 CAPTCHA `fetch`에 `r.ok` 검사가 있는지 정적 단언

### 2.2 Out of Scope

- **Vercel 환경변수 설정** — 운영 조치이며 코드 변경 아님. 다만 §7에 배포 체크리스트로 기재
- `api/index.py`의 503 응답 자체 — 시크릿 없이 CAPTCHA를 발급하면 위조가 가능하므로 **503이 올바른 동작**이다. 변경하지 않음
- 이미 `r.ok` 검사가 있는 fetch 12곳 — §1.3에서 확인 완료
- `fetch` 래퍼 공통 함수 도입 — 2곳 수정에 인프라 도입은 과투자(YAGNI). 관례는 이미 정착돼 있다
- 재시도·백오프 — CAPTCHA는 사용자가 모달을 다시 열면 재요청된다

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | 요구사항 | 우선순위 | 상태 |
|----|----------|:--------:|------|
| FR-1 | 이메일 모달 CAPTCHA: `r.ok` 실패 시 오류 경로로 분기 | High | Pending |
| FR-2 | 게시판 글쓰기 CAPTCHA: 동일 | High | Pending |
| FR-3 | CAPTCHA 미확보 시 제출 버튼 비활성 유지 | High | Pending |
| FR-4 | 안내 문구에 원인·다음 행동 포함 (`undefined` 노출 금지) | Medium | Pending |
| FR-5 | 회귀 테스트로 고정 | Medium | Pending |

### 3.2 Non-Functional Requirements

| 범주 | 기준 | 측정 |
|------|------|------|
| 정상 경로 무회귀 | 200 응답 시 기존 동작과 동일 | 수동 확인 + 기존 테스트 |
| 관례 준수 | 저장소에 정착된 `if (!resp.ok)` 패턴을 따를 것(새 추상화 도입 금지) | 코드 리뷰 |
| 보안 | 서버 오류 상세(`detail`)를 사용자에게 그대로 노출하지 않음 | 문구 검토 |
| 공개 주석 | HTML 주석에 내부 경로·함수명 금지 (CLAUDE.md 규약) | `test_answer_glance.js`의 주석 검사 통과 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] FR-1~FR-5 구현
- [ ] `/api/captcha`가 503일 때 화면에 `undefined`가 나타나지 않음(로컬 재현으로 확인)
- [ ] 503일 때 제출 버튼이 활성화되지 않음
- [ ] 200일 때 기존 동작 무회귀
- [ ] 기존 오프라인 스위트 전부 통과
- [ ] 회귀 테스트가 실제로 위반을 잡는지 변이 테스트로 확인

### 4.2 Quality Criteria

- [ ] 수정 범위가 CAPTCHA 로딩 2곳을 넘지 않음(§1.3에서 다른 곳은 이미 정상임을 확인)
- [ ] 오류 문구가 사용자 언어로 작성되고 다음 행동을 안내

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| 정상 경로 회귀(200인데 오류로 처리) | High | Low | `r.ok`만 검사, 응답 파싱 로직 무변경 |
| 오류 문구가 서버 내부 정보 노출 | Medium | Low | `detail` 미표시, 고정 문구 사용 |
| 같은 실수가 새 fetch에서 재발 | Medium | Medium | FR-5 회귀 테스트 + CLAUDE.md 관례 기재 |
| 환경변수 미설정이 근본 원인인데 코드 수정으로 해결됐다고 오인 | **High** | Medium | 본 계획이 고치는 것은 **증상 표시**이지 원인이 아님을 문서·PR에 명시. §7 배포 체크리스트로 환경변수 확인 강제 |

> 마지막 항목이 가장 중요하다. `r.ok` 검사를 넣어도 **CAPTCHA는 여전히 발급되지 않는다** — 다만 사용자가 이유를 알 수 있게 될 뿐이다.

---

## 6. Architecture Considerations

### 6.1 Project Level Selection

| Level | Selected |
|-------|:--------:|
| Starter | ☐ |
| **Dynamic** | ☑ (기존 단일 HTML 파일 인라인 스크립트에 국소 수정) |
| Enterprise | ☐ |

### 6.2 Key Decisions

| Decision | Options | 권고 | Rationale |
|----------|---------|------|-----------|
| 수정 방식 | 공통 `fetchJson` 래퍼 도입 / 각 지점에 `r.ok` 검사 | **각 지점 검사** | 대상이 2곳뿐이고 저장소에 이미 `if (!resp.ok)` 관례가 12곳에 정착돼 있다. 새 추상화는 관례와 어긋나고 회귀 표면만 늘린다 |
| 오류 시 버튼 상태 | 활성 유지 / 비활성 유지 | **비활성 유지** | "눌리는데 아무 일도 안 일어남"이 이번 신고의 핵심 혼란 지점이다 |
| 문구 | 서버 `detail` 표시 / 고정 안내 | **고정 안내** | 내부 오류 문구("서버 설정 오류")는 사용자에게 무의미하고 내부 상태를 노출한다 |
| 테스트 방식 | jsdom 도입 / 소스 정적 단언 | **정적 단언** | CI가 npm 의존성을 설치하지 않는다. `test_answer_glance.js`가 이미 같은 방식으로 공개 페이지를 검사한다 |

### 6.3 변경 대상 파일 (예상)

```
수정: public/index.html      (이메일 모달 CAPTCHA 로딩 + 버튼 상태)
      public/board.html      (글쓰기 CAPTCHA 로딩)
      test_answer_glance.js  (FR-5 회귀 테스트 — 공개 페이지 검사 파일이 이미 여기 있음)
      CLAUDE.md              (fetch 오류 처리 관례 기재)
```

> 테스트를 신규 파일로 만들지 않고 `test_answer_glance.js`에 얹는 이유: 그 파일이 이미 "공개 페이지 소스를 훑어 규약 위반을 잡는" 역할을 하고 있어(HTML 주석 검사) 성격이 같다. 다만 파일명이 기능 특화라 **범용 이름으로의 리네이밍은 설계 단계에서 검토**한다.

---

## 7. Convention Prerequisites

### 7.1 Existing Conventions

- [x] `if (!resp.ok)` 후 사용자 안내 — 12곳에 정착(§1.3)
- [x] 공개 페이지 HTML 주석에 내부 경로·함수명 금지 (CLAUDE.md)
- [x] 오프라인 테스트는 API 키·npm 의존성 없이 CI 실행

### 7.2 배포 체크리스트 (코드 외 — 운영자 확인 필요)

| 항목 | 확인 방법 |
|------|-----------|
| `CAPTCHA_HMAC_SECRET`(또는 `ADMIN_JWT_SECRET`/`ADMIN_PASSWORD`) Production에 설정 | Vercel → Settings → Environment Variables |
| **환경변수 저장 후 재배포** | Vercel은 저장만으로 재배포하지 않는다 |
| 반영 확인 | `curl -s -o /dev/null -w "%{http_code}" .../api/captcha` → `200` |
| `/admin` 로그인 | `ADMIN_PASSWORD` 미설정 시 관리자 대시보드도 동작하지 않는다 |

---

## 8. Next Steps

1. [ ] 설계 문서 작성 (`/pdca design captcha-fetch-error-handling`) — 문구 확정, 버튼 상태 전이, 테스트 배치(파일 리네이밍 여부 포함)
2. [ ] 구현 → 503 재현 확인 → 회귀 테스트 변이 검증
3. [ ] 갭 분석 → PR

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-08-07 | 초안 — 2026-08-07 실장애 원인 분석, `fetch` 14곳 전수 조사로 범위를 CAPTCHA 2곳으로 확정(오탐 5건 배제), FR-1~5 정의 | DrunkenZealnut |
