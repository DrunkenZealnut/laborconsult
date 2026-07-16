# 답변 UI 가독성 재점검 Plan (answer-ui-readability)

> **Summary**: 챗봇 답변 렌더링(`public/index.html`의 `md()` + `.msg.assistant` CSS)을 재점검하여, 표가 답변 영역 폭을 채우지 못하고 중간에 끊기는 문제(핵심 불만)를 포함해 목록 구성(중첩 미지원·번호 분절), 들여쓰기, 글자 크기 위계, 블록 간 간격 등 가독성 결함 12건을 확정하고 3개 웨이브(표 → 목록 → 타이포/간격·일관성)로 개선한다.
>
> **Project**: laborconsult
> **Author**: DrunkenZealnut
> **Date**: 2026-07-15
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 답변 말풍선은 배경·테두리가 있는 100% 폭 카드인데 내부 표는 `display: block; width: auto`라 내용 폭만큼만 그려져 **중간에 끊긴 것처럼 보이고**, 모든 셀이 `white-space: nowrap`이라 긴 텍스트가 줄바꿈 없이 가로 스크롤을 강제한다. 목록 파서는 들여쓰기를 버려 하위 항목이 같은 레벨로 펴지고, 번호 목록 사이에 하위 불릿이 끼면 뒤 번호 항목이 앞 항목에 병합돼 번호가 깨진다. 헤딩(h2 16px/h3 15px)과 본문(15px)의 크기 차가 거의 없어 위계가 드러나지 않는다 |
| **Solution** | ① `md()`가 표를 `.table-wrap` 스크롤 래퍼로 감싸고 표 자체는 `width: 100%; display: table`로 원복 — 항상 답변 폭을 채우고 넘칠 때만 래퍼가 스크롤 ② 목록 파서에 들여쓰기 기반 중첩 지원 + 번호·불릿 상호작용 버그 수정 ③ 타이포 스케일(h2 18px 액센트/h3 16px/본문 15px)과 블록 간격 리듬 정리, PDF 내보내기 CSS 동기화 |
| **Function/UX Effect** | 표가 답변 폭 전체를 채워 "끊긴 표"가 사라지고, 긴 셀은 줄바꿈되어 모바일에서 불필요한 가로 스크롤 소멸. 들여쓴 하위 항목이 실제 중첩 목록으로 표시되고 1·2·3 번호 연속성이 유지됨. 제목-본문 위계가 한눈에 잡혀 긴 법률 답변의 스캔 가능성(scannability) 향상 |
| **Core Value** | 법률 상담 답변의 핵심 전달 수단인 **표(계산 내역)와 목록(절차·요건)이 구조 그대로 전달**되도록 하여, 내용 품질 개선 없이 렌더링만으로 이해도와 신뢰감을 높인다 |

---

## 1. 개요

### 1.1 목적

사용자 질문에 대한 AI 답변이 화면에 표시되는 최종 단계 — `public/index.html`의 마크다운 렌더러 `md()`(983행)와 `.msg.assistant` CSS(201~265행) — 를 점검하여, 표 폭·목록 구성·들여쓰기·글자 크기·간격의 가독성 결함을 수정한다. 답변 **내용**(프롬프트·파이프라인)은 대상이 아니며 **렌더링 계층**만 다룬다.

### 1.2 배경

- 사용자 보고: "표가 전체 폭을 차지하지 않고 중간에 끝나버린다. 목록 구성, 들여쓰기, 글자 크기 등 가독성을 높이고 깔끔한 답변 구성이 필요하다."
- 직전 답변 UI 작업은 `answer-visual-upgrade`(2026-03, 콜아웃·요약 배지·step-list 도입)로 **리치 컴포넌트 추가**가 목적이었고, 기본 조판(표 폭·중첩 목록·타이포 위계)은 그대로 남았다.
- 본 Plan 작성 전에 렌더러와 CSS 전체를 코드 정독으로 사전 감사했다(§3). 발견사항은 전부 파일:행 근거를 확인했다.

### 1.3 진단 방법

| 트랙 | 대상 | 방식 |
|------|------|------|
| CSS 조판 | `.msg.assistant` 하위 표·목록·헤딩·간격 규칙(201~265행), 모바일 미디어쿼리(411~432행) | 규칙 정독 + 렌더링 모델 분석(display:block 표의 폭 축소 등) |
| 렌더러 로직 | `md()`(983~1080행), `inlineTransform()`(968행), stash/placeholder 매커니즘 | 정규식 상호작용 추적(불릿→번호 순서, trailing newline 소비) |
| 내보내기 일관성 | PDF `actionPDF()` 인라인 CSS(1277~1282행), 마크다운/복사 경로 | 화면 스타일과 대조 |

---

## 2. 범위

### 2.1 In Scope

- [ ] 표 렌더링: `.table-wrap` 래퍼 도입, `width: 100%` 원복, 셀 줄바꿈 정책(`nowrap` 재설계), 모서리 radius 일관성
- [ ] 목록 렌더링: 들여쓰기 기반 중첩 `<ul>` 지원, 번호 목록·하위 불릿 상호작용 버그 수정, `li` 간격
- [ ] 타이포 위계: h2/h3/본문/표/콜아웃 글자 크기 스케일 정리
- [ ] 간격 리듬: 문단·목록·블록(표/콜아웃/헤딩) 상하 마진 일관화, 말풍선 첫/마지막 요소 여백
- [ ] 모바일(≤600px) 표·목록 대응 규칙
- [ ] PDF 내보내기 인라인 CSS를 화면 표 스타일과 동기화
- [ ] 회귀 검증: 표·중첩 목록·계산 결과·콜아웃이 포함된 대표 샘플로 브라우저 확인

### 2.2 Out of Scope

- 답변 내용·구조를 만드는 프롬프트/파이프라인 변경 (`app/` 전체)
- 신규 시각 컴포넌트 추가(콜아웃·카드 종류 확장 — `answer-visual-upgrade` 계열)
- `meta` 이벤트 수치 카드 UI(제품 결정 대기 중, CLAUDE.md 명시)
- 랜딩·FAQ·게시판 등 답변 영역 외 페이지 조판
- `public/calculator_flow/*.html`·`admin.html`의 자체 스타일
- 마크다운 렌더러의 외부 라이브러리 교체(marked 등 도입) — 현행 자체 파서 유지·보수

---

## 3. 사전 감사 발견사항 (심각도별)

ID 규칙: `TBL-*` 표, `LST-*` 목록, `TYP-*` 타이포/간격, `ETC-*` 일관성·부수.

### 3.1 🔴 P1 — 사용자 체감 직결

| # | 발견 | 근거 위치 |
|---|------|-----------|
| TBL-1 | **표가 답변 폭을 채우지 못하고 중간에 끝남** — `width: auto; display: block`. `display: block`인 표는 내용 폭만큼만 그려지는데, 답변 말풍선(`.msg.assistant`)은 배경(#f8f7f5)·테두리가 있는 100% 폭 카드라 좁은 표가 "끊긴 것"으로 보임. 사용자 명시 불만 | `public/index.html:233` |
| TBL-2 | **모든 셀 `white-space: nowrap`** — 설명형 텍스트 열도 줄바꿈 금지라 셀 하나가 길면 표 전체가 가로 스크롤로 밀림(모바일 특히). 폭을 채우게 바꿔도 nowrap을 함께 풀지 않으면 좁은 화면에서 여전히 스크롤 강제 | `public/index.html:234-235` |
| LST-1 | **중첩 목록 미지원** — 불릿 정규식 `((?:^[ \t]*[-*] .+$\n?)+)`이 들여쓰기 정보를 버리고 연속 불릿을 전부 평탄한 단일 `<ul>`로 병합. LLM이 들여쓰기로 표현한 하위 항목이 같은 레벨로 펴져 구조 소실 | `public/index.html:1021-1025` |
| LST-2 | **번호 목록 사이 하위 불릿 → 번호 분절·병합** — 불릿 블록이 먼저 stash되며 trailing newline까지 소비해 placeholder가 다음 `2. …` 줄 앞에 붙음 → 그 줄이 `^[ \t]*\d+\. ` 매칭에 실패해 항목 1의 continuation으로 병합(번호 소실) 또는 목록 분절. `1.\n  - 하위\n2.` 패턴에서 재현 예상(Do 단계에서 검증 후 수정) | `public/index.html:1021,1027-1042` 상호작용 |

### 3.2 🟡 P2 — 가독성 개선

| # | 발견 | 근거 위치 |
|---|------|-----------|
| TYP-1 | **헤딩 위계 부재** — h2 16px, h3 15px, 본문 15px. h3는 본문과 동일 크기, h2도 1px 차이라 굵기 외 구분 없음. 긴 답변에서 섹션 스캔 곤란 | `public/index.html:229-230` |
| LST-3 | **`li` 간격 규칙 없음** — 항목이 빽빽하게 붙어 다항목 목록(권리 요건·절차)이 덩어리로 보임 | `public/index.html:232` (li 규칙 부재) |
| LST-4 | **목록 들여쓰기 고정 20px** — 중첩 도입 시 단계별 들여쓰기 및 모바일 과들여쓰기 방지 규칙 필요 | `public/index.html:232` |
| TYP-2 | **블록 간격 리듬 불균일** — p 6px, 표 10px, 콜아웃 10px, h2 상단 14px 등 제각각이고 섹션 경계가 약함. 간격 스케일(예: 본문 6~8px / 블록 12px / 섹션 16px) 정리 필요 | `public/index.html:229-245` |
| TBL-3 | **표 radius·테두리 처리** — 현재 `border-radius: 8px`이 `display: block` 표에 걸려 있음. 래퍼 도입 시 radius+`overflow: hidden`을 래퍼로 이전해야 모서리가 일관되게 잘림 | `public/index.html:233` |

### 3.3 🟢 P3 — 일관성·부수

| # | 발견 | 근거 위치 |
|---|------|-----------|
| ETC-1 | PDF 내보내기 인라인 CSS가 화면과 불일치(구식 1px 회색 보더 표, 폭·zebra 없음) — 화면 개선 후 격차 확대 예정이라 최소 동기화 필요 | `public/index.html:1277-1282` |
| ETC-2 | 모바일(≤600px) 미디어쿼리에 표 규칙 없음 — 셀 패딩·글자 크기 축소로 좁은 화면 밀도 대응 여지 | `public/index.html:411-432` |
| ETC-3 | `.msg.assistant :first-child`만 상단 여백 제거, `:last-child` 하단 미처리 — 말풍선 위아래 여백 비대칭 | `public/index.html:210` |

---

## 4. 개선 방향 (Design 단계에서 상세화)

### Wave A — 표 (TBL-1·2·3, 핵심)

1. `md()` 표 생성부(1002행)에서 `<div class="table-wrap"><table>…</table></div>` 로 래핑.
2. CSS 재작성:
   - `.table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; margin: 10px 0; border: 1px solid var(--border); border-radius: 8px; }`
   - `.msg.assistant table { width: 100%; border-collapse: collapse; margin: 0; }` (display: block 제거)
   - `td`는 `white-space: normal`로 줄바꿈 허용, `th`·`.num-cell`은 nowrap 유지(숫자 정렬 보존). 필요 시 `td { min-width }` 하한 검토.
3. zebra(`nth-child(even)`)·`total-row`·`num-cell` 등 기존 규칙은 그대로 유지.

### Wave B — 목록 (LST-1·2·3·4)

1. 불릿 파서를 들여쓰기 깊이(2칸 단위) 스택 기반으로 확장 → 중첩 `<ul>` 생성. 과도한 깊이는 2단계로 캡.
2. 번호 목록 정규식과 불릿 stash의 상호작용 수정 — 번호 항목에 딸린 들여쓴 하위 불릿을 해당 `<li>` 내부의 하위 `<ul>`로 귀속시켜 번호 연속성 보장(LST-2 재현 케이스를 수정 전 확보).
3. `li + li` 간격(약 3~4px), 중첩 `ul ul` 들여쓰기·마진 규칙 추가.

### Wave C — 타이포·간격·일관성 (TYP-1·2, ETC-1·2·3)

1. 타이포 스케일: h2 17~18px(+코퍼 액센트 등 시각 구분), h3 15.5~16px, 본문 15px, 표·콜아웃 14px 유지 — Design에서 확정.
2. 간격 리듬: 문단 6~8px / 블록(표·콜아웃·목록) 10~12px / 섹션(h2 상단) 16~18px로 통일. `:last-child` 하단 여백 제거.
3. PDF 인라인 CSS에 표 폭·zebra·헤더 스타일 동기화, 모바일 표 패딩·글자 축소 규칙 추가.

### 검증 방법

- 표(넓은 표·좁은 표)·중첩 목록·번호+하위 불릿·콜아웃·계산 결과·수식이 포함된 대표 마크다운 샘플을 준비해 로컬 서버(`uvicorn`, port 5555)에서 렌더링 확인.
- Chrome 브라우저(데스크톱 폭 + 600px 이하)로 전후 스크린샷 비교.
- 기존 회귀 축: 콜아웃 4종, summary-badge, step-list, total-row, num-cell, 수식(TeX), 링크, 복사/PDF/MD 내보내기.

---

## 5. 성공 기준 (Acceptance Criteria)

- [ ] 열 수가 적은 표도 답변 영역 폭 100%를 채운다 (내용이 넘칠 때만 래퍼 내부 가로 스크롤)
- [ ] 긴 텍스트 셀은 줄바꿈되고, 숫자 셀(`num-cell`)은 nowrap·우측 정렬·tabular-nums 유지
- [ ] 들여쓴 하위 불릿이 실제 중첩 `<ul>`로 렌더링된다
- [ ] `1. → (하위 불릿) → 2.` 패턴에서 번호 연속성(1, 2, 3…)이 유지된다
- [ ] h2/h3/본문 크기·스타일 위계가 시각적으로 구분된다
- [ ] 600px 이하에서 표가 잘리지 않고 스크롤 또는 줄바꿈으로 수용된다
- [ ] 기존 리치 컴포넌트(콜아웃·요약 배지·step-list·합계행)와 내보내기 3종(복사/PDF/MD) 회귀 없음
- [ ] Gap 분석 Match Rate ≥ 90%

---

## 6. 단계 계획

| 단계 | 내용 | 산출물 |
|------|------|--------|
| Design | 표 래퍼 구조·목록 파서 알고리즘·타이포 스케일 수치 확정, LST-2 재현 케이스 작성 | `docs/02-design/features/answer-ui-readability.design.md` |
| Do | Wave A → B → C 순 구현 (전부 `public/index.html` 단일 파일) | 코드 변경 |
| Check | 대표 샘플 브라우저 검증 + gap-detector 분석 | `docs/03-analysis/answer-ui-readability.analysis.md` |
| Act/Report | 필요 시 반복 개선 후 완료 보고 | `docs/04-report/answer-ui-readability.report.md` |

**예상 규모**: 단일 파일(`public/index.html`) 내 CSS ~40행 + JS 파서 ~30행 수정. 난이도 Medium(파서 정규식 상호작용 주의).

---

## 7. 리스크

| 리스크 | 영향 | 완화 |
|--------|------|------|
| 목록 파서 수정이 기존 답변 패턴(step-list 판별, continuation 병합)을 깨뜨림 | 절차 안내 렌더링 회귀 | 수정 전 현행 동작 스냅샷 확보, step-list·continuation 케이스를 검증 샘플에 포함 |
| `nowrap` 해제로 숫자 열이 어색하게 줄바꿈 | 계산 내역 가독성 저하 | `num-cell`·`th` nowrap 유지, 필요 시 열 최소폭 |
| SSE 스트리밍 중 부분 마크다운 재렌더링 성능 | 타이핑 중 표 깜빡임 | 구조 변경 최소화(래퍼 1겹), 기존 재렌더 방식 유지 |
| PDF 내보내기 창의 인라인 CSS 누락 | 화면-인쇄 불일치 지속 | Wave C에 동기화 항목 포함, 내보내기 검증 체크리스트화 |

---

## 8. 다음 단계

1. `/pdca design answer-ui-readability` — 파서 알고리즘·CSS 수치 상세 설계
2. Do 구현 → `/pdca analyze answer-ui-readability`
