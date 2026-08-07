# 답변내용 일목요연 정리 — 설계·구현 갭 분석 (answer-at-a-glance)

> **Summary**: Plan v0.2 / Design v0.2 대비 구현 일치율 87% → **100%** (Act-1 반영, §12 참조). D1~D9 설계 결정은 9/9 준수, 설계 원칙은 P2만 실질 위반. 자동 테스트 12건은 전부 통과하지만 **테스트가 구조적으로 닿지 못하는 DOM 조작 영역에서 High 결함 2건**을 코드 추적으로 확인했다.
>
> **Project**: laborconsult
> **Date**: 2026-08-06
> **Status**: Draft
> **Plan**: [answer-at-a-glance.plan.md](../01-plan/features/answer-at-a-glance.plan.md) (v0.2)
> **Design**: [answer-at-a-glance.design.md](../02-design/features/answer-at-a-glance.design.md) (v0.2)
> **분석 방식**: gap-detector 에이전트 대조 + High 2건·CSS 용량 실측 재검증

---

## 1. 분석 개요

| 항목 | 내용 |
|------|------|
| 구현 산출물 | 신설 `public/finalize.js`(8,828 B), `test_answer_glance.js` / 수정 `public/index.html`, `public/board.html`, `app/templates/prompts.py`, `.github/workflows/tests.yml` |
| 검증 방법 | 6개 파일 직접 판독 + CSS 특이도 계산 + DOM 변이 순서 수기 추적 + `node --test`(12/12 pass) |
| 미검증 영역 | 브라우저 수동 검증(Plan §7 DoD), jsdom 부재로 DOM 결과물 자동 검증 — 구현자가 이미 명시한 한계 |

---

## 2. Match Rate: **87%**

Plan §3.1 우선순위를 가중치로 환산(High = 1.5, Medium = 1.0).

| FR | 우선순위 | 가중 | 달성도 | 점수 | 감점 사유 |
|----|:--------:|:----:|:------:|:----:|-----------|
| FR-1 목차/앵커 | High | 1.5 | 0.70 | 1.05 | 생성·스타일·키보드 정상, 다중 답변에서 점프 대상 오작동(G2) |
| FR-2 접기/펼치기 | High | 1.5 | 0.60 | 0.90 | 접기 판정 정확, 그러나 마지막 섹션이 주의사항·면책을 흡수(G1) |
| FR-3 요약 상시 접근 | Medium | 1.0 | 1.00 | 1.00 | — |
| FR-4 스트리밍 안전 finalize | High | 1.5 | 1.00 | 1.50 | — |
| FR-5 프롬프트 정합 | Medium | 1.0 | 1.00 | 1.00 | — |
| FR-6 게시판 적용 | High | 1.5 | 1.00 | 1.50 | — |
| **합계** | | **8.0** | | **6.95** | |

**6.95 / 8.0 = 87%** → 90% 미만이므로 **Act 단계 필요**.

| 부문 | 점수 |
|------|:----:|
| FR 구현 일치 | 87% ⚠️ |
| 설계 결정 D1~D9 준수 | 9/9 ✅ (D6은 유일성 미규정 — 설계 자체의 한계) |
| 설계 원칙 P1~P5 | 4/5 ⚠️ (P2 실질 위반) |
| Plan NFR | 5/7 ⚠️ |

---

## 3. FR별 판정

| ID | 요구사항 | 판정 | 근거 |
|----|----------|:----:|------|
| FR-1 | 헤딩 N개+ 상단 목차 생성·클릭 스크롤 | **부분구현** | 생성 `finalize.js:64-93`, 삽입 `:174`, 임계값 `:23,66`, id `:74`, 핸들러 `:81-89`. CSS `index.html:355-359`·`board.html:227-231`. **결함**: `:84` `document.getElementById`(전역 조회) + `:74` id가 답변마다 0부터 재시작 → 2번째 이후 답변 칩이 첫 답변으로 점프(G2) |
| FR-2 | 상세 섹션 `<details>` 접기, 핵심은 항상 펼침 | **부분구현** | 화이트리스트 `:29-37`, ALWAYS_OPEN 우선 판정 `:103-104`, 200자 하한 `:110`, 라벨 `:117-118`, 래핑 `:112-122`, 중첩 방지 `:99`. **결함**: `collectSectionNodes`(`:52-62`)가 다음 h2/h3 또는 컨테이너 끝까지 무조건 수집 → 마지막 접기 섹션이 후행 주의사항 콜아웃·`<hr>`·면책 고지를 흡수(G1) |
| FR-3 | 핵심 요약 스티키/앵커 접근 | **구현됨** | sticky 목차 `index.html:355`·`board.html:227`, 플로팅 버튼 `finalize.js:136-165`(전역 1개, IntersectionObserver), CSS `index.html:370-372`(`bottom:76px` — `#back-to-top` 바로 위). 첫 칩이 핵심 답변인 점도 기여 |
| FR-4 | 스트리밍 완료 후에만 적용 | **구현됨** | 호출 지점이 `while` 루프·`showAnswerActions` 이후. chunk·replace 분기 어디에도 호출 없음. 중복 가드 `:169`. 정적 검증 `test:136-152` |
| FR-5 | 접기 대상 heading 명명 프롬프트 일관화 | **구현됨** | `prompts.py:409-410` "판례 2건 이상 → `## 관련 판례` heading" 신설. `finalize.js:34` `/^관련\s*판례/`와 매칭 |
| FR-6 | 게시판 상세 적용 | **구현됨** | 로드 `board.html:1049`, 호출 `:801-803`(렌더 직후), CSS 복제 `:223-243` |

---

## 4. 설계 결정 D1~D9 준수

| # | 결정 | 준수 | 근거 |
|---|------|:----:|------|
| D1 | `finalize.js` 분리 + 양쪽 로드 | ✅ | `index.html:1998`, `board.html:1049`. `pwa.js`와 동일 방식이라 별도 라우트 불요 |
| D2 | 목차 포함 / 접기만 제외 | ✅ | 포함: `:65` 필터 없음. 제외: `:100` `h.closest('.summary-badge')` |
| D3 | 목차 임계값 2 | ✅ | `:23,66`. `test:116` 고정 |
| D4 | 화이트리스트 정규식 판정 | ✅ | `:32-37` 13종(설계 8종에서 확장), 전부 `^` 앵커 |
| D5 | summary = 제목 + 60자, 빈 값 금지 | ✅ | `:117-118`. 빈 값 불가 보장: `:107`(섹션 0개 반환) + `:110`(200자 미만 반환) |
| D6 | 인덱스 기반 id, 한글 슬러그 금지 | ⚠️ | `:74` 슬러그 없음 ✅. **답변 간 유일성 미보장** → G2. 설계 결정 자체의 한계이지 구현 이탈 아님 |
| D7 | 내보내기 강제 펼침 / 원문 경로 분리 | ✅ | 변환 `:185-199`(라이브 DOM 불변), 적용 `index.html:1460-1462`(`getQAPair` 단일 진입점이라 PDF·이메일 자동 커버), 원문 `:1455` `a.dataset.md` |
| D8 | sticky + 플로팅 버튼 병행 | ✅ | 둘 다 존재 |
| D9 | board 렌더 직후 즉시 호출 | ✅ | `board.html:798` → `:801-803` |

> **설계 문서 갱신 필요**: `design.md §3.1` 의사코드에 v0.1 잔재(`.filter(h => !h.closest('.summary-badge'))`)가 남아 D2 v0.2와 모순된다(G10).

---

## 5. 설계 원칙 P1~P5

| # | 원칙 | 판정 | 검증 |
|---|------|:----:|------|
| P1 | 완성 DOM만 관측 | ✅ | 호출이 루프 밖. `replace`가 루프 내부 처리라 finalize는 인용 교정 후 최종 텍스트만 본다 |
| P2 | 핵심·결론·주의사항 불접힘 | ❌ | 방어 3중(ALWAYS_OPEN 우선 검사·`.summary-badge` 가드·200자 하한) 모두 존재하나 **heading 단위 방어뿐**. 프롬프트가 주의사항·면책을 heading이 아닌 블록쿼트·평문으로 지시하므로 방어망 아래로 빠진다 → **실질 위반**(G1) |
| P3 | `dataset.md` 불변 | ✅ | 기록 지점 2곳 모두 finalize 이전. `finalize.js`에 `dataset.md` 참조 없음(`glanceDone`만). `expandForExport`는 `tmp` 사본에서만 동작 |
| P4 | h2 태그만 근거, `md()` 클래스 비의존 | ✅ | 선택자는 `h2`·`h2, h3`뿐. `.summary-badge` 참조 2곳 모두 폴백 있는 가드 — 클래스 부재 시 자연 degrade |
| P5 | 공유 코드 정적 파일 분리 | ✅ | D1과 동일. CSS만 양쪽 인라인 복제(설계 §3.6 승인 방식) |

---

## 6. 정밀 검증

| # | 의심 항목 | 판정 | 요지 |
|---|-----------|------|------|
| 6-1 | `wrapCollapsible` 노드 이동 순서 | ✅ 정상 (설계보다 안전) | `section`은 변이 전 수집된 참조 배열. `h.replaceWith`는 h만 제거하고 section의 부모 관계는 유지. `appendChild` 반복이 문서 순서 보존. 설계 의사코드의 `insertBefore(details, section[0] \|\| null)`은 빈 배열일 때 details가 컨테이너 끝에 붙는 버그가 있었는데 구현은 `:107` 조기 반환으로 선차단 |
| 6-2 | 미접힘 h2의 id 잔존 | ✅ 두 경우 모두 동작 | 접힘: `:113` `details.id = h.id` 승계. 미접힘: h2에 id 잔존. 핸들러 `:84-88`이 양쪽 처리 + 접힌 경우 자동 펼침 |
| 6-3 | nav 마지막 삽입 | ✅ 무해 | nav는 `<a>`만 담아 `querySelectorAll('h2, h3')`에 안 걸리고, `firstChild` 앞자리라 어떤 섹션에도 포함 불가. **실제 순서 제약은 `buildOutline` → `wrapCollapsible`**(id 부여 → 승계)이며 현 코드가 준수 |
| 6-4 | h2 안의 COLLAPSIBLE h3 | ✅ 중첩 방지됨 | h2가 먼저 처리되며 내부 h3까지 흡수. 이후 h3 차례에 `container.contains`는 **true**(사실상 도달 불가 방어)이고 실제 차단자는 `h.closest('details')` 하나 |
| 6-5 | 다중 답변 버튼 상태 잔존 | ⚠️ Low | `disconnect()` 직후 `.show`가 잠시 남지만 새 observer 초기 콜백이 다음 프레임에 교정. `jumpTarget`은 이미 최신이라 그 창에서 눌러도 결과가 옳다. 잔존 케이스는 `newChat()`(`index.html:1003`)이 관측 대상을 분리시킬 때 해제·초기화가 없는 것뿐 |
| 6-6 | finalize.js 로드 실패 | ✅ 파손 없음 | `<details>`가 애초에 생성되지 않으므로 "접힌 채 PDF" 상황 자체가 없음. 호출부 3곳 모두 존재 가드. **단 board에 타이밍 레이스 있음**(G7) |
| 6-7 | `expandForExport`의 document | ✅ 항상 존재 | 호출부가 버튼 클릭 시점. document 없는 컨텍스트는 try/catch가 원본 반환(`test:188-195` 검증) |
| 6-8 | board `source === 'user'` | ✅ 안전 | 해당 분기는 `.msg-bubble.bot` 미생성 → `querySelector` null → `finalize(null)`이 첫 줄 반환. 설계 §3.6의 조건 가드 대신 null 안전성에 의존(동작 동등, 주석 부재) |
| 6-9 | `details > *:not(summary)` 여백 | ✅ 붕괴 없음, ⚠️ 페이지별 차이 | 특이도: index `.table-wrap`(0,3,0) > details 규칙(0,2,2) → 표·콜아웃 들여쓰기 미적용. board `table`(0,2,1) < details 규칙 → 적용. 가로 스크롤은 양쪽 다 내부 흡수. 미관 차이만 발생(G8) |
| 6-10 | `slice()` 취약성 | ✅ 즉시 실패 | 선언 줄의 실제 들여쓰기를 읽어 종료 정규식을 동적 생성 → 균일 재들여쓰기에 자동 적응. 시그니처 소실 시 `throw`. **다만 다른 사각지대**: `wrapCollapsible` 본문이 미평가라 판정 순서를 뒤집어도 12건 전부 통과(G11) |

---

## 7. Plan NFR 충족

| 범주 | 기준 | 실측/판정 | 상태 |
|------|------|-----------|:----:|
| CSS 용량 | 추가 < 4KB | **index 약 2.3~2.9 KB / board 약 2.2~2.6 KB** (측정 방식에 따라 편차, 양쪽 모두 4KB 미만). Plan §4.2가 "board 몫 별도 산정" 명시 | ✅ |
| 실행시간 | `md()`+finalize 증가 < 10ms | **미측정**. 구조상 `querySelectorAll` 2회 + O(n) 노드 이동이라 위험은 낮으나 근거 없음 | ⚠️ |
| 안정성 | 스트리밍 중 깨짐 0건 | 구조적으로 스트리밍 중 미적용(FR-4 검증 완료). finalize 시점 목차 삽입으로 1회 시프트는 설계 의도. 수동 확인 미수행 | ⚠️ |
| 접근성(키보드) | 목차 칩 포커스 | `<a href="#…">` 네이티브 포커스 + `:focus-visible` 아웃라인 | ✅ |
| 접근성(시맨틱) | `<details>` 네이티브, 색상 단독 전달 금지 | 네이티브 요소라 Enter/Space·상태 전달 브라우저 처리. `nav aria-label`, 버튼 `aria-label`, summary에 요지 텍스트 병기. 화살표는 `::before` 장식 | ✅ |
| 접근성(숨김) | — | **위반**: `#glance-jump-core`가 `opacity:0; pointer-events:none`만으로 숨겨져 탭 순서에 잔존(G4). 기존 `#back-to-top`과 같은 패턴이라 신규 회귀는 아님 | ❌ |
| 하위호환 | heading 2개 미만 목차 미생성 | `:66` `return null` → `:174` `if (nav)` 스킵. 기존 `md()` 렌더·`dataset.md`·`DOMPurify.sanitize()` 무변경 | ✅ |
| 모바일(가로 스크롤) | 목차 칩 가로 스크롤 | `overflow-x:auto` + `flex:0 0 auto` + `white-space:nowrap`. 페이지 가로 스크롤 유발 없음 | ✅ |
| 모바일(터치 타겟) | 접기 ≥ 44px | `summary { min-height:44px }` 양쪽 충족(`test:162-163` 검증). **그러나** 점프 버튼 40px(G3), 목차 칩 약 29px(G5) | ⚠️ |

---

## 8. 발견된 갭

### 🔴 High

#### G1. 마지막 접기 섹션이 주의사항·면책 고지를 삼킨다 (P2 위반)

**근거 (실측 확인)**
- `finalize.js:52-62` — `collectSectionNodes` 종료 조건이 `H2`/`H3` **뿐**. heading 외 마커 없음
- `finalize.js:103` — ALWAYS_OPEN 방어는 **heading 텍스트**만 검사
- `prompts.py:411` — 주의사항은 `> ⚠️ **주의사항**:` **블록쿼트**
- `prompts.py:417` — 면책은 `"⚠️ 본 답변은 참고용이며…"` **평문**
- `prompts.py:382` — 답변 구조가 `⑥ 실무 안내(절차) → ⑦ 주의사항 + 면책` 순서로 고정
- `prompts.py:415` — 절차는 `## 절차`/`## 신청 방법` heading → `finalize.js:35` COLLAPSIBLE에 매칭

**재현 시나리오** (CONSULTATION 경로의 전형)
```
## ⚖️ 핵심 답변        ← summary-badge, 접기 제외
> 📘 법적 근거: …
## 절차                ← COLLAPSIBLE 매칭, 뒤에 h2 없음
1. … 2. …
> ⚠️ 주의사항: …        ← 흡수
---                     ← 흡수
⚠️ 본 답변은 참고용…      ← 흡수
```

`## 절차`가 접히면서 **주의사항·구분선·면책 고지가 기본 접힘 상태로 숨는다.** 설계 D3이 임계값을 2로 낮춰 목차를 살려낸 바로 그 답변군(핵심 답변 + 절차)에서 가장 잘 재현된다.

**영향**: Plan §6 리스크 2행("접기가 정보 은닉으로 오해") 정면 실현. 면책 고지는 `prompts.py:402`가 "반드시 포함"으로 규정한 고지 성격 문구다. `index.html`·`board.html` 양쪽 해당.

**수정 제안** — 태그·텍스트 기반이라 P4 유지:
```js
function isTerminator(n) {
  if (n.tagName === 'HR') return true;
  if (n.classList && n.classList.contains('disclaimer-notice')) return true;
  var t = norm(n.textContent);
  if (/본\s*답변은[\s\S]{0,30}참고용|법적\s*효력이\s*없습니다/.test(t)) return true;
  if (/^(?:⚠️\s*)?주의\s*사항/.test(t)) return true;
  return false;
}
// while 루프: … || isTerminator(n)) break;
```
`HR` 종료만으로도 프롬프트가 `---` 구분선을 지시하는(`prompts.py:416`) 대부분을 커버한다.

#### G2. 다중 답변에서 목차 앵커 id가 충돌한다

**근거 (실측 확인)**
- `finalize.js:74` — `var id = 'ans-h2-' + i;` — 인덱스가 **답변마다 0부터 재시작**
- `finalize.js:84` — `document.getElementById(id)` — **문서 전역** 조회
- `index.html:1027` — `chat.appendChild(wrapper)`로 답변 누적. `:1003` `chat.innerHTML=''`는 "새 상담" 리셋에서만

**증상**: 두 번째 이후 답변의 목차 칩을 누르면 `getElementById`가 **첫 번째 답변**의 동일 인덱스 헤딩을 반환해 그쪽으로 스크롤하고, 그 섹션의 `<details>`를 대신 펼친다. `chip.href='#ans-h2-N'` 네이티브 앵커도 동일 대상.

**영향**: Plan §5 성공 지표 "목차 클릭 → 정확한 섹션 스크롤 100%" 미달. `board.html`은 상세당 봇 말풍선 1개라 무관.

**원인**: 설계 D6이 "한글 슬러그 충돌 회피"만 규정하고 답변 간 유일성을 다루지 않았다. 구현은 설계를 정확히 따랐으므로 **설계 결함의 전파**다.

**수정 제안**:
```js
var seq = 0;                                  // 모듈 스코프
var pfx = 'ans-h2-' + (seq++) + '-';          // finalize() 진입 시
var id = pfx + i;                             // buildOutline
```

### 🟡 Medium

| # | 갭 | 근거 | 수정 제안 |
|---|----|------|-----------|
| G3 | 점프 버튼 터치 타겟 40px (<44px) | `index.html:370`, `board.html:241` `min-height:40px`. 같은 파일의 `#back-to-top`(44×44)·`#send-btn`은 44px 준수 | `min-height: 44px` 통일 |
| G4 | 숨김 버튼이 탭 순서·접근성 트리 잔존 | `finalize.js:146` body 상주 + `opacity:0; pointer-events:none`만. `visibility`/`inert` 없음 | `visibility: hidden` ↔ `.show { visibility: visible }` 또는 `btn.hidden` 토글 |
| G5 | 목차 칩 높이 약 29px(모바일 27px) | padding 4px + font 12px + line-height 1.6 + border | `min-height: 32px; display: inline-flex; align-items: center` (44px는 목차 밀도상 과함) |

### 🔵 Low

| # | 갭 | 근거 | 수정 제안 |
|---|----|------|-----------|
| G6 | `index.html:352` CSS 주석이 설계 결론과 정반대 | 주석은 "sticky가 **성립**한다"고 하나 설계 §3.3·`finalize.js:127-131`은 "데스크톱 무효"로 결론 | 주석을 `finalize.js` 설명과 일치시킬 것. 방향이 반대인 주석은 미수정 코드보다 위험 |
| G7 | board 첫 상세 로드 레이스 | `board.html:1044` `setTimeout(openDetail,100)` vs `:1049` 스크립트 로드. 외부 스크립트 대기 중 타이머 발화 시 첫 렌더 미적용(가드로 조용히 스킵) | 스크립트를 부트스트랩보다 앞에 배치하거나 `DOMContentLoaded`에서 호출 |
| G8 | 접힌 섹션 들여쓰기가 두 페이지에서 다름 | §6-9 특이도 계산 | index에 `details > .table-wrap, details > .callout` 여백 규칙 추가 |
| G9 | board 인쇄 시 접힌 내용 누락 | `board.html:430` `@media print`가 `<details>` 미처리. D7은 index 전용 | `@media print { .answer-outline{display:none} details > *:not(summary){display:block !important} }` |
| G10 | 설계 §3.1이 D2 v0.2와 모순 | v0.1 잔재 필터가 남음 | 설계 §3.1 코드블록에서 해당 줄 삭제 |
| G11 | 테스트가 판정 '순서'·임계값 적용 미검증 | `wrapCollapsible` 본문 미평가 → 검사 순서를 뒤집어도 12건 통과 | `wrapCollapsible` 소스를 잘라 `ALWAYS_OPEN` 인덱스 < `COLLAPSIBLE` 인덱스, `MIN_COLLAPSE_LEN` 등장을 정적 단언 |
| G12 | board에 모바일 조정 없음 | `board.html:305` 미디어쿼리에 `.outline-chip`/`#glance-jump-core` 규칙 부재(index는 존재) | 동일 규칙 복제 |

---

## 9. 범위 초과 구현 (설계 X, 구현 O — 전부 긍정적)

| # | 항목 | 위치 |
|---|------|------|
| 1 | 중복 실행 가드 `dataset.glanceDone` | `finalize.js:169,176` |
| 2 | `finalize` try/catch + `console.warn` | `:170,177-179` — CLAUDE.md graceful degradation 관례 |
| 3 | `expandForExport` try/catch → 원본 반환 | `:186,196-198` |
| 4 | 목차 클릭 시 접힌 섹션 자동 펼침 | `:86-87` — 설계에 없던 UX 보완 |
| 5 | 중첩 접기 방지 가드 2종 | `:98-99` |
| 6 | `section.length` 0 조기 반환 | `:107` — 설계 의사코드 버그 원천 차단 |
| 7 | COLLAPSIBLE 8종 → 13종 확장 | `:32-37` |
| 8 | ALWAYS_OPEN에 `답변 요약` 명시 | `:30` — `md()` 판정 정규식과 표기 정렬 |
| 9 | `norm()` 공백 정규화 | `:46-48` |
| 10 | `aria-label` 2종 | `:70,142` |
| 11 | `test_answer_glance.js` 12건 + CI 스텝 | 설계 §6에 자동 테스트 항목 자체가 없었음 |
| 12 | index 모바일 미디어쿼리 조정 | `index.html:538-539` |

**명명 차이(무해)**: 설계 §3.4는 `addJumpToCore`, §3.3은 `trackJumpToCore`로 문서 내부가 불일치. 구현은 §3.3을 따랐다.

---

## 10. 설계에 있으나 미구현

| # | 항목 | 상태 |
|---|------|------|
| 1 | 브라우저 수동 검증(3유형 × 2페이지 × 모바일) | **미수행** — 알려진 한계, 갭으로 계상하지 않음 |
| 2 | `CONSULTATION_SYSTEM_PROMPT` 골든셋 회귀 | **미수행** — 프롬프트 변경 자체는 완료 |
| 3 | CSS `<4KB` 확인 기록 | 본 문서 §7에서 대신 실측 |
| 4 | `data.source !== 'user' && data.answer` 조건 가드 | null 안전성에 의존(동작 동등, 주석 미흡) |
| 5 | 설계 §3.2의 `insertBefore(details, section[0])` | `h.replaceWith`로 대체 — **개선된 이탈**(§6-1) |

---

## 11. 결론 및 권고

### 종합 판단

Match Rate **87%** — 설계 준수도 자체는 높다. D1~D9는 9/9 준수했고 특히 D2 v0.2 개정, D7(내보내기 분리), D8(병행), D9(즉시 호출)가 코드에서 정확히 확인된다. FR-4는 호출 지점·chunk 분기 양쪽을 확인해 완전 준수다. graceful degradation·중첩 방지·자동 펼침 등 설계를 넘어서는 방어가 12건 추가됐다.

그럼에도 90%에 못 미치는 이유는 **자동 테스트가 구조적으로 닿을 수 없는 DOM 조작 영역에 High 결함 2건**이 있기 때문이다. 12건 전원 통과는 판정 로직과 배선의 정확성만 보증하며, `collectSectionNodes`의 수집 범위(G1)나 `getElementById`의 조회 범위(G2)는 애초에 검증 대상이 아니었다.

특히 **G1은 이 기능의 존재 이유와 충돌한다**. 설계 P2와 Plan §6 리스크가 한목소리로 "핵심·주의는 절대 접지 않는다"고 못박고 heading 단위 방어를 3중으로 깔았는데, 정작 프롬프트가 주의사항·면책을 heading이 아닌 블록쿼트·평문으로 지시하기 때문에 방어망 아래로 빠져나간다. D3이 임계값을 2로 낮춰 살려낸 바로 그 답변군에서 가장 잘 재현된다.

### 권고 조치

**즉시 (배포 전 필수)**
1. **G1 수정** — `collectSectionNodes`에 `HR`·면책·주의사항 종료 조건 추가. 면책 고지는 `prompts.py:402`가 "반드시 포함"으로 규정한 사항이며 접힌 채 숨는 것은 고지 취지에 반한다
2. **G2 수정** — finalize 호출별 id 접두사(시퀀스) 도입. 후속 질문이 일상적인 구조라 재현율이 높다
3. 두 수정에 회귀 방지 테스트 추가(jsdom 없이 가능한 정적 단언 범위)

**단기**
4. G3/G4/G5 — 터치 타겟 44px, 숨김 버튼 `visibility`, 칩 최소 높이
5. G6 — `index.html:352` 주석 정정(방향이 반대인 주석은 미수정 코드보다 위험)
6. G10 — `design.md §3.1` v0.1 잔재 삭제

**DoD 잔여**
7. 브라우저 수동 검증 — **G1·G2 수정 이후에** 수행해야 의미가 있다
8. 프롬프트 골든셋 회귀 — `## 관련 판례` 승격이 실제 답변에 반영되는지 + 승격 섹션이 접기 대상으로 올바로 잡히는지
9. `md()`+finalize 실행시간 측정(NFR < 10ms)

### 다음 단계

```
/pdca iterate answer-at-a-glance
```
G1·G2 수정 후 FR-1/FR-2가 1.00으로 회복되면 Match Rate는 100%(8.0/8.0)가 된다. Medium/Low 갭은 FR 달성도가 아니라 NFR 부문에 반영된다.

---

---

## 12. Act-1 반영 결과 (2026-08-07)

### 12-1. 처리 내역 — 12건 전건 수정

| 갭 | 심각도 | 조치 | 검증 |
|----|:------:|------|------|
| **G1** | High | `isTerminator()` 신설 + `collectSectionNodes`에 종료 조건 추가(`HR`·`.disclaimer-notice`·면책 문구·주의사항 블록쿼트) | **변이 테스트**: `isTerminator(n)` 호출을 제거하니 테스트 7번이 즉시 실패 → 복원 후 통과 |
| **G2** | High | 모듈 스코프 `answerSeq` 도입, `buildOutline(el, 'ans-h2-{seq}-')`로 답변별 접두사 부여 | **변이 테스트**: id 생성식을 `'ans-h2-' + i`로 되돌리니 테스트 8번이 즉시 실패 → 복원 후 통과 |
| **G3** | Medium | 점프 버튼 `min-height: 40px → 44px` (양쪽 페이지) | CSS 확인 |
| **G4** | Medium | `visibility: hidden` ↔ `.show { visibility: visible }` 추가 — 숨김 상태에서 탭 순서 이탈 | CSS 확인 |
| **G5** | Medium | 목차 칩 `min-height: 32px; display: inline-flex; align-items: center` | CSS 확인 |
| **G6** | Low | `index.html` CSS 주석을 설계 결론과 일치하게 정정("sticky는 모바일에서만 유효, 그래서 버튼을 함께 둔다") | 주석 확인 |
| **G7** | Low | `board.html`의 `<script src="/finalize.js">`를 본문 인라인 스크립트(580행)보다 **앞**으로 이동 → `?id=` 딥링크 레이스 해소 | 로드 순서 확인 |
| **G8** | Low | `details > .table-wrap`, `details > .callout` 여백 규칙 추가 — 특이도 역전으로 표·콜아웃만 좌측에 붙던 문제 | CSS 확인 |
| **G9** | Low | `board.html` `@media print`에 접힌 섹션 강제 표시 + 목차·버튼 숨김 | CSS 확인 |
| **G10** | Low | 설계 §3.1 의사코드의 v0.1 잔재 필터 삭제 + D2 v0.2 근거 주석 | 문서 확인 |
| **G11** | Low | 테스트 3종 신설 — `wrapCollapsible` 판정 순서·`MIN_COLLAPSE_LEN` 적용·`isTerminator` 조건·id 유일성을 소스 정적 단언 | 12 → **15건** |
| **G12** | Low | `board.html` 모바일 미디어쿼리에 칩·버튼 규칙 복제 | CSS 확인 |

**설계 문서도 함께 정정**: G2의 근본 원인이 설계 D6에 "답변 간 유일성" 규정이 없던 것이므로, D6을 "답변 시퀀스 + 인덱스"로 개정하고 §3.2에 종료 마커(G1) 근거를 추가했다(design v0.3 예정 항목).

### 12-2. Act-1 후 Match Rate

| FR | 가중 | 이전 | 이후 | 점수 |
|----|:----:|:----:|:----:|-----:|
| FR-1 목차/앵커 | 1.5 | 0.70 | **1.00** | 1.50 |
| FR-2 접기/펼치기 | 1.5 | 0.60 | **1.00** | 1.50 |
| FR-3 요약 상시 접근 | 1.0 | 1.00 | 1.00 | 1.00 |
| FR-4 스트리밍 안전 | 1.5 | 1.00 | 1.00 | 1.50 |
| FR-5 프롬프트 정합 | 1.0 | 1.00 | 1.00 | 1.00 |
| FR-6 게시판 적용 | 1.5 | 1.00 | 1.00 | 1.50 |
| **합계** | **8.0** | 6.95 | | **8.00** |

**8.00 / 8.0 = 100%**

설계 원칙 P2 위반(G1) 해소 → **P1~P5 전건 준수**. NFR도 접근성(G4)·터치 타겟(G3·G5) 해소로 7/7 중 5건 충족, 잔여 2건은 미측정 항목(실행시간·수동 검증)이다.

### 12-3. 회귀 확인

| 스위트 | 결과 |
|--------|------|
| `test_answer_glance.js` | ✅ **15건**(12 → 15) |
| `test_answer_renderer.js` | ✅ 8 pass / 0 fail |
| `test_wage_golden.py` | ✅ |
| `test_pipeline_wiring.py` | ✅ |
| `test_offline_units.py` | ✅ |
| `test_abuse_guard.py` | ✅ (20개 그룹) |
| `test_llm_fallback.py` | ✅ (20건) |
| CSS 용량 | index 약 2,704 B / board 약 2,661 B — 양쪽 4KB 미만 ✅ |

### 12-4. 잔여 (DoD 미충족 — 코드 결함 아님)

| # | 항목 | 사유 |
|---|------|------|
| 1 | 브라우저 수동 검증(3유형 × 2페이지 × 모바일) | jsdom 부재로 DOM 결과물은 자동 검증 불가. **G1·G2 수정 이후인 지금이 수행 적기** |
| 2 | 프롬프트 골든셋 회귀(`## 관련 판례` 승격 반영 여부) | LLM 지시라 비결정적 — 실제 답변 관측 필요 |
| 3 | `md()`+finalize 실행시간 < 10ms 측정 | 콘솔 타이밍 필요 |

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 0.1 | 2026-08-06 | 초안 — FR-1~6 판정, D1~D9·P1~P5 검증, 정밀 검증 10항목, 갭 12건(High 2·Medium 3·Low 7), 범위 초과 12건 |
| 0.2 | 2026-08-07 | Act-1 반영 — 갭 12건 전건 수정, Match Rate 87% → 100%. G1·G2는 변이 테스트로 회귀 방지 확인. 설계 D6·§3.1·§3.2 동반 정정 |
