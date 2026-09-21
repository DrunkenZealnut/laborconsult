# 네이버 지식iN 스타일 복사 Design Document

> **Summary**: 현재 답변 출력 형식은 그대로 두고, 답변 마크다운을 지식iN 에디터가 받아주는 인라인 스타일 HTML로 바꿔 리치텍스트로 클립보드에 싣는 "지식iN용 복사" 액션을 추가한다
>
> **Project**: laborconsult
> **Author**: Claude
> **Date**: 2026-09-22
> **Status**: Draft
> **Plan**: `docs/01-plan/features/naver-kin-answer-simplification.plan.md` (v0.3 — 범위 축소)

---

## 1. 범위 확정 (2026-09-22 사용자 결정)

- **출력 형식 불변.** 짧은 답변 모드(Plan FR-01)·게시 부적합 판정(FR-03)·일괄 검토 페이지(FR-04)는 이번 사이클에서 제외한다.
- **구현 대상은 FR-02 하나** — 변환기 + 리치텍스트 복사 버튼.
- 기존 "복사하기"(질문 포함 전체 대화의 마크다운 원문)는 불변. 새 버튼은 **답변만** 모은다 — 지식iN 답글에 질문 본문이 실리면 안 된다.

## 2. 변환 규칙 — 실측 통과 집합으로 닫는다

허용 태그·속성은 2026-09-22 실측(서식 통과 실험대)에서 **통과한 것만**이다. 새 태그를 쓰려면 실험대에서 먼저 통과시킨다.

| 마크다운 | 출력 HTML | 근거 |
|---|---|---|
| `# 제목` | `<h2>` | h1은 미실측. h2 통과 |
| `## 제목` | `<h3>` | h3 통과 |
| `### `~`###### ` | `<p><span style="font-size:16px"><b>…</b></span></p>` | "가짜 제목" 통과 — h4 이하 미실측 |
| `**굵게**` | `<b>` | 통과 |
| `*기울임*` / `_기울임_` | `<i>` | 통과 |
| `~~취소~~` | `<s>` | 통과 |
| `` `코드` `` | `<span style="font-family:monospace">` | 고정폭 통과 |
| `[글](https://…)` | `<a href="…">` — http/https만, 그 외는 텍스트 | 링크 통과 |
| `![alt](src)` | alt 텍스트만 | **이미지 깨짐** |
| `> 인용` 블록 | `<p>` (빈 `>` 줄로 문단 분리, 문단 내 줄은 `<br>`) | **blockquote 깨짐**. 본문이 이미 `⚠️ **주의사항**:` 라벨을 갖고 있어 볼드 문단으로 충분히 구분된다. border-left 대안은 통과 미확인이라 쓰지 않는다 |
| `---` / `***` / `___` | `<hr>` | 통과 |
| `- ` / `* ` 항목 | `<ul><li>` — 들여쓴 하위 항목은 같은 목록에 **평탄화** | 통과, 중첩은 미확인 |
| `1. ` 항목 | `<ol><li>` — 평탄화 동일 | 통과 |
| 표 (`\|…\|` 연속 줄) | `<table style="border-collapse:collapse">` / 셀 `<td style="border:1px solid #bbb;padding:6px 10px">` / **머리행은 `<td><b>`** / 정렬행(`\|---\|`) 제거 | 표 통과. `<th>`는 미실측이라 td+b |
| ```` ``` ```` 펜스 | `<pre>` | 통과 |
| 일반 문단 | `<p>`, 문단 내 단일 줄바꿈은 `<br>` | 통과 |
| 이모지 | 그대로 | 유니코드 텍스트 |
| 원문의 `<`·`&`·`"` | 이스케이프 | 태그 오프닝 차단. `>`는 이스케이프하지 않는다 — 텍스트 위치의 `>`는 유효하고, 인용구 마커 판정에 필요(`md()`와 같은 선택) |

**금지 출력**: `class`·`id`·`style` 외 속성, `blockquote`, `img`, `h1`, `h4`~`h6`, `th`, `script`, 마크다운 마커 잔존. 단위 테스트가 태그·속성 집합으로 고정한다.

## 3. 복사 방식 — 실험대가 검증한 경로 그대로

```
KinFormat.copyRich(html)
  ① 숨김 contenteditable div 에 html 삽입 → selectNodeContents → execCommand("copy")
     (text/html + text/plain 이 함께 실린다 — 실험대에서 통과 확인)
  ② 실패 시 navigator.clipboard.write(ClipboardItem{text/html, text/plain})
  ③ 둘 다 실패 → false 반환, 버튼이 "복사 실패" 표시
```

지식iN에서 `Ctrl+V`는 서식 유지, `Ctrl+Shift+V`는 텍스트만 — 별도 플레인 변환기는 두지 않는다.

## 4. 구조

```
public/kin_format.js      KinFormat = { toHtml(md), copyRich(html) }  — 순수 변환 + 복사. DOM 은 copyRich 에서만
                          module.exports(node) / window.KinFormat(browser) — admin_legal_rules.js 와 같은 이중 노출
public/index.html         showAnswerActions(): "지식iN용 복사" 버튼 추가
                          actionCopyKin(btn): .msg.assistant:not(.status) 의 dataset.md 를 <hr> 로 이어 붙여 변환·복사
                          <script src="/kin_format.js"> (finalize.js 옆)
test_kin_format.js        node --test — 화이트리스트·매핑·이스케이프·결정성
public/sw.js              VERSION 상향 (ASSET_PATTERN 이 js 를 cache-first — CLAUDE.md 규약)
.github/workflows/tests.yml   node --test 목록에 추가
```

**`md()` 렌더러와 별도 구현인 이유**: `md()`는 `index.html` 인라인 함수라 node 에서 못 부르고(수식 렌더러 의존), 출력에 class 가 섞여 지식iN 에서 전부 버려진다. 변환기의 목적은 화면 렌더링이 아니라 **붙여넣기 생존**이므로 허용 집합이 다르다. 파서 중복은 두 목적이 다르다는 점으로 정당화하되, 답변 마크다운은 LLM 이 만드는 정형 구조(실측 5건: 표·인용구·헤더·목록·볼드·구분선·펜스)라 커버 범위가 좁다.

## 5. 테스트

| 검사 | 방법 |
|---|---|
| 화이트리스트 | 전 구문 fixture → 출력 태그 집합 ⊆ 허용 집합, `class=`·`id=`·`<blockquote`·`<img`·`<h1`·`<th`·`<script` 0건 |
| 마커 잔존 0 | 출력에서 태그 제거 후 `**`·줄머리 `#`·줄머리 `>`·`\|` 0건 |
| 매핑 | 헤더 3단, 표(머리행 볼드·정렬행 제거·셀 인라인 변환), 인용구→p(문단 분리·br), 목록 평탄화, 링크 스킴, 이미지 alt, 펜스 |
| 이스케이프 | `<script>`·`&`·`"` 포함 입력 |
| 결정성 | 같은 입력 두 번 → 동일 출력 |
| 실기 | 변환 출력을 실험대 "내 HTML 시험대"에 넣어 붙여넣기 확인(사용자, 1회) |

## 6. 회귀 영향

- 기존 `actionCopy`·`getQAPair`·`finalize.js` 불변. 새 버튼은 `dataset.md`만 읽는다.
- `test_public_fetch.js`는 `public/*.js`를 디렉터리에서 발견한다 — `kin_format.js`에 `fetch`가 없어 스윕 무영향.
- `sw.js` VERSION 상향 없이는 낡은 `index.html`이 cache-first 로 남아 버튼이 안 보인다.
