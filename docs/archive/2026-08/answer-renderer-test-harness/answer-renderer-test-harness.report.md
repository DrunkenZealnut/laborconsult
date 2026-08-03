# 답변 렌더러 회귀 테스트 하네스 완료 보고서

> **Summary**: `answer-ui-readability` 사이클에서 스크래치 도구로만 존재하던 렌더러 회귀 하네스(Design §6.1, T1~T8)를 저장소에 커밋된 정식 테스트(`test_answer_renderer.js`)로 승격하고 오프라인 CI 스위트에 연동했다. 핵심 난점이던 "인라인 `<script>` 렌더러를 어떻게 가져올 것인가"는 **줄 번호 하드코딩 대신 선언 이름 시그니처 매칭**으로 해결해 `public/index.html` 무변경을 달성했다. Plan의 6개 Step 전부 구현·커밋 완료, `node --test` **8/8 통과**.
>
> **Feature**: answer-renderer-test-harness
> **Owner**: DrunkenZealnut
> **Duration**: 2026-07-16 (1일)
> **Status**: ✅ Completed

---

## Executive Summary

### Overview

- **문제**: `public/index.html`의 `md()` 렌더러 회귀 검증이 세션 스크래치 도구에만 존재해, 이후 렌더러를 수정하면 회귀를 자동으로 차단할 수단이 없었음 (CodeRabbit PR #27 리뷰 지적)
- **해결 방식**: 소스에서 렌더러 선언 7개를 **이름 시그니처로 추출** → Node `vm` 컨텍스트에서 평가 → `node:test`로 T1~T8 검증. 외부 의존성·빌드 도구·`package.json` 신설 없음
- **결과**: Plan Task 2개 / Step 6개 전부 완료, 커밋 3건, `node --test` 8/8 통과, CI 오프라인 스위트에 상시 편입
- **수치**: 신규 파일 1개(`test_answer_renderer.js` 129행, 테스트 8건·어서션 18건), 수정 파일 1개(`.github/workflows/tests.yml` — Node 셋업 + 실행 스텝 2개 추가), **프로덕션 코드 변경 0행**

### 1.3 Value Delivered

| Perspective | Content |
|-------------|---------|
| **Problem** | `answer-ui-readability`에서 `md()` 렌더러를 ~80행 재설계(중첩 목록 파서, placeholder 고정점 복원 등)했으나, 이를 검증한 하네스 29건은 스크래치 도구여서 커밋되지 않았다. 즉 **복잡도가 가장 높은 코드에 회귀 안전망이 없는 상태**로 남았고, 이후 누가 `md()`를 손대면 표 렌더링·번호 연속성·내용 소실 같은 P1급 결함이 조용히 재발할 수 있었다. 정식화의 걸림돌은 `public/index.html`이 빌드 없는 단일 HTML이라 `require()`로 렌더러를 가져올 수 없다는 구조적 제약이었다 |
| **Solution** | ① **이름 시그니처 매칭 추출** — `extractDeclaration()`이 `function md(text) {` 같은 선언 시작 패턴을 찾고 칼럼 0의 닫는 `}`(또는 `];`)까지 잘라냄. `renderTex`/`renderMdLink`/`inlineTransform`/`indentWidth`/`buildNestedUl`/`CALLOUT_MAP`/`md` 7개를 추출해 `vm` 컨텍스트에서 평가 ② **KaTeX 스텁 불필요** — 컨텍스트에 `katex`를 아예 선언하지 않아 `renderTex()`의 기존 "KaTeX 없음" 폴백 분기가 그대로 동작 ③ **CI 연동** — 새 job이 아니라 기존 `offline-tests` job에 `setup-node@v4`(Node 22) + `node --test` 스텝을 추가해 오프라인 스위트의 일부로 취급 |
| **Function/UX Effect** | `md()` 또는 그 헬퍼를 수정하는 모든 PR에서 T1~T8이 자동 실행된다 — 표 뒤 잔여 `<br>`(C4), 중첩 불릿 보존(C1), 번호+하위불릿 소실(C2), continuation 병합(C3), 번호 사이 표 소실(C5), step-list 판별, 3단계 들여쓰기 level 2 캡, 리치 컴포넌트(콜아웃·요약배지·총계행·num-cell·수식·링크) 무회귀. 추출 대상 선언이 사라지면 **조용히 통과하는 대신 즉시 에러로 실패**하므로 안전망이 무력화된 사실이 CI에서 드러난다. 개발자 입장에서는 `node --test test_answer_renderer.js` 한 줄로 로컬 재현 가능 |
| **Core Value** | **프로덕션 파일을 전혀 건드리지 않고** 빌드 시스템 없는 레거시 단일 HTML에 회귀 안전망을 부착했다. 줄 번호 하드코딩(같은 사이클 안에서 968~1080 → 1020~1138로 이미 깨진 실증 사례)을 피한 추출 전략 덕에, 향후 `index.html` 리팩터링에도 테스트가 살아남는다. 답변 렌더링은 법률 상담 답변의 신뢰도와 직결되는 최종 표현 계층이므로, 이 계층의 회귀 차단은 콘텐츠 품질과 독립적으로 서비스 품질을 지탱한다 |

---

## PDCA Cycle Summary

### Plan (2026-07-16)

- 문서: `docs/01-plan/features/answer-renderer-test-harness.plan.md` (283행)
- 근거: `answer-ui-readability.report.md` §Next Steps 4번 (CodeRabbit PR #27 리뷰 인용)
- 범위 판단: 파일 1개 신설 + 워크플로 1개 수정 — 서브시스템 분할 불필요, 단일 플랜으로 충분
- Task 2개 / Step 6개로 분해

### Design

**별도 Design 문서 없음** — 플랜 내 "설계 결정" 절이 설계 역할을 겸했다. 핵심 결정은 추출 전략 선택이며, 2개 대안을 비교 후 채택 근거를 문서화했다:

| 방식 | 장단점 | 판정 |
|------|--------|------|
| A. 마커 주석 (`// test-extract:start`~`end`) | 코드 이동에 강하나 프로덕션 파일에 테스트 전용 흔적이 남고, 마커 삭제 시 조용히 깨질 위험 | 미채택 |
| **B. 이름 시그니처 매칭** | `public/index.html` 무변경, 줄 번호 무관, 패턴 미발견 시 즉시 `Error` | **채택** |

채택 근거는 실증으로 뒷받침했다 — `function md(text) {` → `function mdRenamed(text) {`로 시뮬레이션해 `extractDeclaration: 시작 패턴을 찾지 못함 — /^function md\(text\) \{/m`로 즉시 실패함을 로컬 확인(커밋되지 않는 임시 변경).

### Do (2026-07-16)

| Task | Step | 결과 |
|------|------|------|
| **Task 1** — 테스트 파일 신설 | Step 1 작성 → Step 2 실행 확인 → Step 3 커밋 | ✅ `82cc6b1` |
| **Task 2** — CI 연동 | Step 1 `tests.yml` 교체 → Step 2 커맨드 일치 재확인 → Step 3 커밋 | ✅ `824c563` |
| (플랜 외 후속) | T6 어서션 보강 — CodeRabbit 리뷰 반영 | ✅ `fca4cb4` |

`fca4cb4`는 플랜에 없던 후속 대응이다. T6이 `<p><h2>` 문자열 exact-match에 의존하고 있었는데, 이는 브라우저가 `<p>`를 자동으로 먼저 닫는 **무효한 중첩**에 결합된 형태라 실제 렌더링과 무관한 문자열 변화에도 깨질 수 있었다. 검증을 제목·step-list 두 축으로 분리해 취약성을 제거했다.

### Check

**gap-detector 정식 Gap 분석은 수행하지 않았다.** 이 작업은 산출물이 "테스트가 통과하는가"로 직접 검증되는 성격이라, 설계-구현 대조보다 실행 결과가 상위 증거다. 대신 아래로 갈음했다:

- `node --test test_answer_renderer.js` → `# tests 8 / # pass 8 / # fail 0`, 종료 코드 0
- 플랜 Step 6개 전부 커밋 이력(`82cc6b1`, `824c563`)과 파일 실재로 대조 확인
- `tests.yml`에 적힌 커맨드와 로컬 검증 커맨드가 문자 그대로 일치함을 확인

미검증으로 남은 항목은 GitHub Actions 실제 실행이다(로컬에 `act` 등 러너 없음) — 아래 Next Steps 참고.

---

## Results

### Completed Items

**신규: `test_answer_renderer.js` (129행, 테스트 8건 / 어서션 18건)**

- `extractDeclaration(source, startPattern, endMarker)` — 선언 시그니처 기반 소스 추출, 미발견 시 `Error` throw
- 추출 대상 7개: `renderTex`, `renderMdLink`, `inlineTransform`, `indentWidth`, `buildNestedUl`, `CALLOUT_MAP`, `md`
- 검증 항목:

| ID | 검증 내용 |
|----|-----------|
| T1 | 표 뒤 문단에 잔여 `<br>` 없음 (C4) |
| T2 | 중첩 불릿 구조 보존 (C1) |
| T3 | 번호+하위불릿 — 병합/소실 없음 (C2) |
| T4 | continuation 병합 유지 (C3) |
| T5 | 번호 사이 표 — 소실 없음 (C5) |
| T6 | 절차 키워드 → step-list 판별 유지 (제목·step-list 2축 분리) |
| T7 | 3단계 이상 들여쓰기 — level 2 캡 |
| T8 | 리치 컴포넌트 무회귀 (콜아웃/요약배지/총계행/num-cell/수식/링크) |

**수정: `.github/workflows/tests.yml` (39행)**

- `actions/setup-node@v4` (Node 22) 셋업 스텝 추가
- `답변 렌더러 회귀 테스트` 실행 스텝 추가 — 기존 `offline-tests` job 내부, Python 테스트 3종 뒤
- 워크플로 주석을 "계산 엔진 골든 + 파이프라인 배선 + 검색/인용 단위 + **답변 렌더러 회귀**"로 갱신

**변경 없음: `public/index.html`** — 설계 결정 B의 목표대로 프로덕션 코드 무변경 달성

### Incomplete/Deferred Items

없음. Plan에 정의된 Task 2개 / Step 6개 전부 완료.

---

## Implementation Metrics

| 항목 | 값 |
|------|-----|
| 신규 파일 | 1개 (`test_answer_renderer.js`, 129행) |
| 수정 파일 | 1개 (`.github/workflows/tests.yml`, +2 스텝) |
| 프로덕션 코드 변경 | **0행** |
| 테스트 | 8건 (T1~T8) / 어서션 18건 |
| 실행 결과 | `# pass 8 / # fail 0` |
| 신규 의존성 | 0개 (Node 내장 `node:test`·`node:assert/strict`·`node:vm`만 사용) |
| 커밋 | 3건 (`82cc6b1`, `824c563`, `fca4cb4`) |
| 소요 | 1일 (2026-07-16) |

---

## Lessons Learned

### What Went Well

1. **줄 번호 하드코딩을 실증으로 반박한 것** — "줄 번호는 언젠가 깨진다"는 일반론이 아니라, *같은 PDCA 사이클 안에서* `md()`가 968~1080 → 1020~1138로 이동한 구체 사례를 플랜에 기록했다. 대안 비교표의 판정 근거가 추상론이 아니라 관측값이 되었다.

2. **실패 모드를 먼저 검증한 것** — 채택안이 "잘 동작하는가"뿐 아니라 "**깨질 때 시끄럽게 깨지는가**"를 함수명 변경 시뮬레이션으로 확인했다. 조용히 통과하는 테스트는 없느니만 못한데, 이 검증이 그 위험을 배제했다.

3. **기존 관례에 맞춘 배치** — 새 job·새 워크플로·`package.json`을 만들지 않고 기존 `offline-tests` job과 루트 flat `test_*` 관례를 따랐다. 신규 개념 도입이 0이라 유지보수자가 새로 배울 것이 없다.

4. **CodeRabbit 리뷰의 2단 활용** — PR #27 리뷰가 이 작업의 착수 근거였고, 구현 후 리뷰가 다시 T6의 무효 HTML 중첩 결합을 잡아냈다(`fca4cb4`). 외부 리뷰를 문서(Next Steps)와 코드 양쪽에 반영하는 경로가 작동했다.

### Areas for Improvement

1. **정식 Check 단계를 건너뛴 것** — 실행 결과가 직접 증거인 작업이라 실용적 판단이었으나, 그 결정을 사전에 문서화하지 않아 사후 설명이 필요해졌다. 플랜 단계에서 "이 작업은 Check를 테스트 실행으로 갈음한다"를 명시했다면 더 깔끔했다.

2. **플랜 문서 커밋이 구현보다 늦어진 것** — 산출물(`test_answer_renderer.js`, `tests.yml`)은 2026-07-16에 커밋됐으나 플랜 문서는 미추적으로 남아 있다가 2026-08-02에야 커밋됐다(`ef23d10`). 그 사이 저장소만 보면 "근거 문서 없는 테스트"로 보였다. **플랜은 Task 1 커밋과 함께 나가야 한다.**

3. **T6의 취약한 어서션이 최초 작성 때 걸러지지 않은 것** — `<p><h2>` 문자열 매칭은 작성 시점에 통과했기 때문에 문제로 인식되지 않았다. "통과하는 어서션"과 "옳은 어서션"은 다르며, 특히 **무효 HTML을 전제로 한 문자열 매칭**은 작성 즉시 의심 대상이어야 한다.

### To Apply Next Time

1. 빌드 없는 단일 HTML에 테스트를 붙일 때는 **이름 시그니처 추출 + 미발견 시 throw**를 기본형으로 삼는다.
2. 회귀 테스트를 만들 때 통과 확인뿐 아니라 **의도적으로 깨뜨려 실패 메시지를 읽어본다.**
3. 문서와 코드는 같은 커밋 묶음으로 내보낸다.
4. 문자열 exact-match 어서션은 그 문자열이 **유효한 구조를 표현하는지** 먼저 확인한다.

---

## Next Steps

### 즉시 권고 (Priority: High)

1. **GitHub Actions 실제 성공 확인** — YAML 문법은 기존 스텝과 동일한 2-space 스타일을 따라 위험이 낮으나, `actions/setup-node` 포함 워크플로 실행 자체는 로컬 재현이 불가하다. 현재 브랜치(`fix/answer-ui-readability`) push 후 Actions 탭에서 `답변 렌더러 회귀 테스트` 스텝이 실제로 통과하는지 1회 확인. (예상 소요: 3분)

### 선택사항 (Priority: Low)

2. **어서션 커버리지 보강** — 현재 8 테스트 / 18 어서션은 Design §6.1의 29건보다 축약된 형태다. 스크래치 하네스에만 있던 나머지 검증을 옮겨올지 검토. (단 T1~T8의 결함 클래스는 전부 커버됨)

3. **모바일 뷰포트 자동 회귀와의 통합** — `answer-ui-readability.report.md` Next Steps 3번(Playwright 기반 375/411/320px 검증)이 실현되면, 문자열 레벨(현 하네스)과 렌더링 레벨(Playwright) 검증을 하나의 스위트로 묶는 편이 관리에 유리하다.

4. **추출 전제 조건의 문서화 위치 재검토** — "`md()`와 헬퍼가 칼럼 0 최상위 선언으로 유지되어야 한다"는 전제는 현재 플랜 문서에만 있다. `test_answer_renderer.js` 상단 주석에도 있으나, `public/index.html` 쪽에서는 이 결합을 알 수 없다. (다만 위반 시 CI가 즉시 실패하므로 위험도는 낮음)

---

## 최종 판정

| 기준 | 결과 |
|------|------|
| Plan Task 완료 | 2/2 ✅ |
| Plan Step 완료 | 6/6 ✅ |
| 테스트 통과 | 8/8 ✅ |
| 프로덕션 영향 | 0행 변경 ✅ |
| 미완료 항목 | 없음 |

**✅ Completed** — `answer-ui-readability`가 남긴 마지막 후속 항목이 해소되었다. 렌더러 재설계로 가장 복잡해진 코드 경로에 상시 작동하는 회귀 안전망이 부착되었고, 그 안전망 자체가 무력화되면 조용히 통과하는 대신 CI에서 실패하도록 설계되었다. 반복(Act) 불필요.

---

## Appendix: 관련 문서

| 문서 | 경로 |
|------|------|
| Plan | `docs/01-plan/features/answer-renderer-test-harness.plan.md` |
| 선행 사이클 Report | `docs/archive/2026-07/answer-ui-readability/answer-ui-readability.report.md` (§Next Steps 4번 = 본 작업 착수 근거) |
| 선행 사이클 Design | `docs/archive/2026-07/answer-ui-readability/answer-ui-readability.design.md` (§6.1 = T1~T8 원본 정의) |
| 산출물 | `test_answer_renderer.js`, `.github/workflows/tests.yml` |
| 대상 코드 | `public/index.html` (`md()` 및 헬퍼 — 변경 없음) |
