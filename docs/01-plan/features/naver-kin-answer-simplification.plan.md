# 네이버 지식iN 답변 간소화 Planning Document

> **Summary**: 지식iN 노동상담 질문에 대해 게시 가능한 형태의 짧은 답변을 바로 만들고, 붙여넣기 시 포맷이 깨지지 않게 하며, 질문→게시까지의 수작업을 줄인다
>
> **Project**: laborconsult
> **Author**: Claude
> **Date**: 2026-09-22
> **Status**: Do (FR-02 구현 완료 — 사용자 지식iN 실기 확인 대기)
> **Branch**: `feat/naver-kin-answer-simplification`
>
> ⚠️ **v0.3 범위 축소(2026-09-22, 사용자 결정)**: 현재 답변 출력 형식은 **그대로 두고** "지식iN용 복사" 하나만 추가한다. FR-01(짧은 답변 모드)·FR-03(게시 부적합 판정)·FR-04(일괄 검토 페이지)는 이번 사이클에서 **제외**. 아래 본문의 해당 FR 은 후속 후보로만 남긴다. 확정 설계는 `docs/02-design/features/naver-kin-answer-simplification.design.md`.

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 현재 답변은 평균 2,217자의 마크다운(헤더·표·콜아웃)이고, 웹 UI "복사하기"는 마크다운 **원문**을 복사한다(`index.html:1494`). 지식iN 입력창은 마크다운을 렌더링하지 않아 붙여넣으면 `#`·`**`·`\|` 기호가 그대로 노출되고, 운영자가 기호 제거·축약을 손으로 한다. 질문 198건(본문 중앙값 175자)에 비해 답변이 과도하게 길다 |
| **Solution** | ① 지식iN 답변 모드(짧고 구조 제한된 출력, 면책·기관연락처 유지) ② 마크다운→**인라인 스타일 HTML** 결정적 변환기 + 리치텍스트 클립보드 "지식iN용 복사"(실측으로 표·제목·목록까지 통과 확인, 2026-09-22) ③ 저작권 가드를 재사용한 게시 부적합 판정 ④ 질문 JSON→복사 버튼이 달린 검토 페이지 일괄 생성. 처리 속도·자동 게시는 범위 밖 |
| **Function/UX Effect** | 복사→붙여넣기 한 번으로 볼드·목록·표·구분선까지 유지되는 답변, 길이 2,200자→목표 900자 이내, 게시 전 검토 항목(면책·환각교정·저작권)이 답변에 붙어 나옴. 198건 일괄 초안 생성 가능 |
| **Core Value** | 지식iN 답변 1건당 수작업 시간 단축 + 공개 게시에서의 저작권·법적 리스크를 구조적으로 차단 |

---

## 1. Overview

### 1.1 Purpose

네이버 지식iN 고용·노동 카테고리 질문에 대해, 운영자가 **검토 후 바로 게시할 수 있는 답변**을 만든다. 핵심은 셋이다 — 지식iN에 맞는 길이·형식, 붙여넣기 시 포맷 보존, 게시까지의 사람 손 과정 축소.

### 1.2 Background

- 지식iN 질문 198건(`test_sample/naver_kin_608_고용_노동.json`)이 이미 파이프라인 벤치마크로 쓰이고 있다(`test_naver_kin.py`, 2026-03 `naver-kin-test-fixes` 사이클).
- 실측(2026-03-20, 5건): 평균 67.1초, 답변 2,217자, 면책 100%, 기관연락처 80%. 답변은 `# ⚖️ 핵심 답변` 헤더·표·콜아웃 구조.
- 질문 본문 중앙값은 **175자**로 짧은 구어체다. 2,200자 마크다운 답변은 지식iN 답변 관행(짧고 직접적, 단락·번호목록)과 맞지 않는다.
- 웹 UI `actionCopy`는 `assistantEl.dataset.md`(마크다운 원문)를 `navigator.clipboard.writeText`로 복사한다. 지식iN 에디터는 마크다운을 렌더링하지 않으므로 기호가 그대로 노출된다 — **포맷 깨짐의 직접 원인**.
- 사용자 확인(2026-09-22): 간소화 대상은 **답변 형식·길이**와 **게시 워크플로우**. 파이프라인 처리 속도는 대상이 아니다. 용도는 "답변을 복사해 지식iN 입력창에 넣었을 때 포맷이 유지되는 것".
- **지식iN 에디터 붙여넣기 실측(2026-09-22, 사용자, "서식 통과 실험대")** — 리치텍스트(`text/html`)로 붙여넣었을 때 살아남는 서식이 예상보다 훨씬 넓다. 이 결과가 설계의 기본 경로를 결정한다:

  | 결과 | 항목 |
  |---|---|
  | **통과** | 굵게·기울임·밑줄·취소선, 글자 크기(px), 글자색·형광펜(background-color), 고정폭 글꼴, 제목 h2/h3, 가짜 제목(큰 볼드 span), 문단 정렬, 불릿 목록, 번호 목록, 구분선 hr, **표**, 링크, 코드/여백 보존 블록 pre, 빈 줄·br |
  | **깨짐** | 인용구 blockquote, 이미지 |

  실험대의 복사 방식(contenteditable 선택 + `execCommand("copy")`, 폴백 `ClipboardItem`)이 그대로 재사용 대상이다. 실험대 안내대로 **class·외부 스타일시트는 전부 버려지므로 서식은 `style` 속성 인라인으로만** 실어야 한다 — 웹 UI가 렌더링한 DOM(콜아웃 class 등)을 그대로 복사하면 안 된다. 미확인: "인용구 (왼쪽 선 흉내)" 대안(border-left div)의 통과 여부, 다른 브라우저·기기(실험대 기록은 브라우저 localStorage 단위).

### 1.3 Related Documents

- 지식iN 붙여넣기 실측 도구: https://claude.ai/artifact/23oLDw2W19iHiYrfiGhGAz ("서식 통과 실험대" — 하단 "내 HTML 시험대"에 변환기 출력을 넣어 재검증 가능)
- 이전 사이클: `docs/01-plan/features/naver-kin-test-fixes.plan.md`, `docs/02-design/features/naver-kin-test-fixes.design.md`
- 벤치마크 스크립트: `test_naver_kin.py`
- 저작권 가드 규약: `CLAUDE.md` § Crawlers(G1~G6), § RAG Pipeline(Q1~Q6)
- 답변 경로 두 갈래: `CLAUDE.md` § Key Conventions — `CONSULTATION_SYSTEM_PROMPT` / `SYSTEM_PROMPT_TEMPLATE`

---

## 2. Scope

### 2.1 In Scope

- [x] FR-02: 마크다운→인라인 스타일 HTML 변환기 + 웹 UI "지식iN용 복사" (`public/kin_format.js`, 2026-09-22 구현)
- ~~FR-01: 지식iN 답변 모드~~ → v0.3에서 제외 (출력 형식 불변 결정)
- ~~FR-03: 게시 부적합 판정~~ → v0.3에서 제외 (후속 후보)
- ~~FR-04: 일괄 검토 페이지~~ → v0.3에서 제외 (후속 후보)

### 2.2 Out of Scope

- 파이프라인 단계 축소·응답 시간 개선 (사용자 미선택 — 별도 feature)
- 지식iN 자동 게시(봇·비공식 API) — 네이버 약관 위반 소지, 사람 검토 단계가 필수라 제외
- 지식iN 질문 자동 수집(크롤러) — 기존 198건 JSON 사용, 수집 자동화는 별도
- 답변 정확성·근거 품질 자체의 개선 (RAG 품질은 별도 feature)
- 기존 웹 채팅 답변 형식 변경 — 지식iN 모드는 **별도 모드**이고 기본 동작은 불변

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | **지식iN 답변 모드**: `process_question(output_mode="kin")`(또는 동등 진입점)에서 출력 규칙을 접미한다 — 헤더·표·콜아웃·이모지 금지, 단락+번호목록+`---` 구분선만 허용, 길이 상한(목표 900자, Design에서 확정), 핵심 결론을 첫 문단에, 면책 문구와 기관 연락처는 **간결형으로 유지**. G1~G3·Q1~Q4처럼 **두 답변 경로 모두에** 접미해야 한다 — 한쪽만 바꾸면 임금계산·괴롭힘 판정 경로에서 긴 답변이 그대로 나간다 | High | Pending |
| FR-02 | **게시용 HTML 변환기 + 리치텍스트 복사**: 마크다운→**인라인 스타일 HTML** **결정적** 변환. 허용 집합은 실측 통과 항목으로 한정 — `b/i/u/s`, `span style="font-size\|color\|background-color"`, `h2/h3`, `p style="text-align"`, `ul/ol/li`, `hr`, `table/tr/td`(테두리 인라인), `a`, `pre`, `br`. **금지**: `class`·`id`·외부 CSS(전부 버려짐), `blockquote`(깨짐 — 주의사항 콜아웃은 굵은 라벨 문단 또는 border-left 대안으로 치환, 대안 통과 여부 확인 후 확정), `img`(깨짐 — 제거). 웹 UI "지식iN용 복사" = 변환 HTML을 숨김 contenteditable에 넣고 `execCommand("copy")`(실측 검증된 방식), 폴백 `ClipboardItem`. 기존 "복사하기"(마크다운 원문)는 불변. 플레인 텍스트가 필요하면 붙여넣을 때 `Ctrl+Shift+V` — 별도 변환기 불필요 | High | Pending |
| FR-03 | **게시 부적합 판정**: 답변 메타에 `kin_review` 블록 부착 — ① 해설서(`metadata.textbook`) 또는 상담 지배(`counsel_dominant`) 근거 → **게시 불가** 표시(기존 G6·Q6 판정 재사용, 재선언 금지) ② 환각 교정 발생(`citation_fixed`) → 검토 필요 ③ 면책 문구 포함 여부 ④ 계산기 보류(`legal_rule_status=blocked`) 여부. 변환기 출력 말미에 검토 체크리스트로 함께 출력 | High | Pending |
| FR-04 | **일괄 초안 생성 → 복사 버튼이 달린 검토 페이지**: `generate_kin_answers.py` — 질문 JSON → 지식iN 모드 실행 → `output_kin/_review.html` 한 장. 질문별 카드에 원 질문·변환된 답변 미리보기·**"지식iN용 복사" 버튼**(실험대와 같은 execCommand 방식)·FR-03 판정 배지·길이·소요시간을 담는다. 운영자는 카드에서 복사 → 지식iN 붙여넣기만 한다(`.txt` 중간 단계 없음). 게시 불가 판정 카드는 복사 버튼을 비활성화하고 사유를 표시한다. `test_naver_kin.py`와 파이프라인 호출부를 공유하고 `--field`·`--count`·`--all` 인자 계약을 따른다. 배치 산출물은 `guard_ctx=None` 경로라 `metadata.synthetic`으로 게시판 제외됨(G-A) — 그대로 둔다 | Medium | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| 포맷 보존 | 변환 HTML이 **허용 태그·속성 화이트리스트만** 사용 — `class`·`id`·`blockquote`·`img`·마크다운 기호 잔존 0건 | `test_kin_format.py` — 마크다운 fixture(헤더·표·콜아웃·중첩목록·이미지) → HTML 파싱 후 태그·속성 집합 단언 |
| 실기 재검증 | 변환기 출력을 실험대 "내 HTML 시험대"에 넣어 붙여넣기 통과 확인 | 사용자 실측 1회(변환기 확정 후) |
| 길이 | 지식iN 모드 답변 중앙값 ≤ 900자, 최대 1,500자 (Design에서 확정) | 10건 샘플 재생성 후 측정 |
| 품질 유지 | 면책 포함 100%, 기관연락처 ≥80% (이전 사이클 기준선 유지) | `test_naver_kin.py --mode kin` 지표 |
| 무회귀 | 기본 모드 답변·골든·배선·오프라인 스위트 전량 통과 | 기존 CI 테스트 |
| 저작권 | 게시용 산출물 중 해설서·상담 근거 답변은 **전부 게시 불가 표시** | FR-03 판정 결과 집계, `_review.md`에서 0건 누락 확인 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] FR-01~04 구현
- [ ] `test_kin_format.py` 통과 — 기호 잔존 0
- [ ] 10건 샘플: 길이 중앙값 목표 이내, 면책 100%
- [ ] 사용자가 지식iN 입력창에 붙여넣어 포맷 유지를 확인
- [ ] 기존 테스트 전량 통과(기본 모드 무회귀)
- [ ] CLAUDE.md에 지식iN 모드·변환기·게시 부적합 규약 등재

### 4.2 Quality Criteria

- [ ] 변환기는 순수 함수(네트워크·상태 없음)로 CI에서 실행
- [ ] 저작권 판정은 `storage.py`의 기존 판정을 import — 재선언 없음(회귀 테스트로 동일성 고정)
- [ ] 두 답변 경로 모두에 규칙이 접미됨을 테스트로 고정(`test_pipeline_wiring.py` 방식)

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| ~~지식iN 에디터의 붙여넣기 동작이 미확인~~ → **해소(2026-09-22 실측)**. 잔여 리스크: ① 인용구 대안(border-left div)의 통과 여부 미확인 ② 실측이 한 브라우저·기기 기준 ③ 에디터가 업데이트되면 허용 규칙이 조용히 바뀐다 | Medium | Medium | ① 주의사항 콜아웃은 **굵은 라벨 문단**을 기본 치환으로 두고(통과 확실), border-left는 확인 후 옵션 ② Design 확정 전 다른 브라우저에서 실험대 1회 더 ③ 실험대 링크를 CLAUDE.md에 등재해 "포맷이 깨졌다" 보고 시 첫 진단 수단으로 쓴다 |
| **변환 HTML에 `class`가 섞여 들어간다** — 웹 UI가 렌더링한 DOM(`md()`의 콜아웃·`.summary-badge`)을 그대로 복사하면 에디터가 class를 전부 버려 서식이 사라진다 | High | Medium | 변환기는 렌더링 DOM이 아니라 **`dataset.md` 마크다운 원문**에서 인라인 스타일 HTML을 새로 만든다. 화이트리스트 단위 테스트가 `class`·`id` 0건을 고정 |
| **공개 게시의 저작권 노출** — 지식iN은 웹 게시판보다 노출이 크고 영구적이다. 해설서·상담글 근거 답변이 G1(소프트 가드)을 뚫고 게시되면 1:1 상담이 공개 배포로 확대된다 | High | Medium | FR-03이 기존 G6·Q6 판정을 **그대로 재사용**해 게시 불가를 표시한다. 판정을 복제하면 한쪽만 어긋나는 실패 모드(CLAUDE.md G6)가 재현되므로 import로 고정. 게시 불가 답변은 변환기가 본문 대신 사유만 출력 |
| **길이 축약이 근거·안전장치를 깎는다** — 면책·기관연락처·법조문이 빠지면 이전 사이클(면책 100%)이 회귀한다 | High | Medium | 규칙에 "면책·기관연락처는 간결형으로 반드시 유지"를 명시하고 `test_naver_kin.py` 지표로 고정. 길이 상한은 결론·근거·안내 3단을 담을 수 있는 값으로 Design에서 실측해 정한다 |
| **한 경로에만 규칙 접미** — 답변 경로가 두 갈래라 한쪽만 바꾸면 계산·괴롭힘 경로에서 긴 답변이 그대로 나간다(해설서 가드에서 실제로 발생) | Medium | Medium | G1~G3과 같은 접미 지점(`pipeline.py`가 두 분기 모두에 접미)을 쓰고 배선 테스트로 고정 |
| **변환기가 LLM 출력 변이에 취약** — 헤더 레벨·표 형식·이모지 접두가 매번 달라 정규식이 놓친다 | Medium | Medium | FR-01이 형식을 먼저 제약하므로 변환기는 방어선이다. 기호 잔존 0을 단위 테스트로 고정하고, 실측 답변 10건을 fixture로 추가 |
| **기존 "복사하기" 동작 변경으로 웹 사용자 혼란** | Low | Low | 기존 버튼은 불변, "지식iN용 복사"를 별도 액션으로 추가 |

---

## 6. Architecture Considerations

### 6.1 Project Level Selection

| Level | Characteristics | Selected |
|-------|-----------------|:--------:|
| **Starter** | Simple structure | ☐ |
| **Dynamic** | Feature-based modules, BaaS integration | ☑ |
| **Enterprise** | Microservices, K8s | ☐ |

기존 프로젝트 레벨(Dynamic) 유지. 인프라 변경 없음.

### 6.2 변경 대상

```
app/templates/prompts.py       ← FR-01: KIN_OUTPUT_RULES 상수 (G1~G3과 같은 접미 방식)
app/core/pipeline.py           ← FR-01: output_mode 파라미터, 두 경로 접미 / FR-03: kin_review 메타
public/kin_format.js           ← FR-02: 마크다운→인라인 스타일 HTML 변환 + 리치텍스트 복사 (신규, 웹 UI·배치 공유)
public/index.html              ← FR-02: "지식iN용 복사" 액션 (기존 actionCopy 불변)
generate_kin_answers.py        ← FR-04: 일괄 실행 → output_kin/_review.html 생성 (신규, test_naver_kin.py와 호출부 공유)
test_kin_format.js             ← 변환기 화이트리스트 단위 테스트 (신규, node --test, CI 편입)
test_naver_kin.py              ← --mode kin 인자 + 길이·게시판정 지표 추가
test_public_fetch.js           ← kin_format.js는 디렉터리 발견으로 자동 편입(fetch 없음이면 무영향)
CLAUDE.md                      ← 규약 + 실험대 링크 등재
```

### 6.3 설계 방향 (Design에서 확정)

- **프롬프트 제약 + 후처리 변환의 2중 구조.** 프롬프트만으로는 LLM이 형식을 어기고, 후처리만으로는 길이가 줄지 않는다. FR-01이 1차, FR-02가 2차 방어선이다.
- **변환 대상은 텍스트가 아니라 인라인 스타일 HTML이다.** 실측으로 표·제목·목록·색이 전부 통과했으므로 정보를 버릴 이유가 없다. 다만 허용 집합은 실측 통과 항목으로 **닫아 둔다** — 새 태그를 쓰려면 실험대에서 먼저 통과시킨다.
- **복사 방식은 실험대가 검증한 것을 그대로 쓴다.** 숨김 contenteditable에 변환 HTML을 넣고 선택 → `execCommand("copy")` → 클립보드에 `text/html`+`text/plain`이 함께 실린다. 폴백은 `navigator.clipboard.write(ClipboardItem)`. 지식iN에서 `Ctrl+V`는 서식 유지, `Ctrl+Shift+V`는 텍스트만 — 사용자에게 이 구분을 안내한다.
- **변환기는 웹 UI와 배치가 공유한다.** 웹 UI(JS)와 배치 검토 페이지(파이썬이 생성하는 HTML) 양쪽에 필요하다. 배치 검토 페이지도 브라우저에서 열어 복사 버튼을 누르므로 **JS 변환기 하나를 양쪽이 로드**하는 구조가 가능하다 — `public/kin_format.js`를 웹 UI가 `<script src>`로, 배치가 생성 HTML에 인라인 삽입으로 공유하면 이중 구현이 필요 없다. 파이썬 쪽은 마크다운 원문과 판정 메타만 JSON으로 심고 변환은 브라우저가 한다. Design에서 이 방식과 (b) JS·파이썬 이중 구현 + fixture 동일성 테스트 중 선택 — 단일 구현이 CLAUDE.md의 "유틸 복사" 실패 모드를 피한다.
- **게시 부적합 판정은 `app/core/storage.py`의 기존 판정을 import한다** — `is_public_excluded()`·`PUBLIC_EXCLUDE_KEYS`가 단일 출처다. 지식iN 게시 기준이 게시판 기준보다 엄격해야 한다면(예: 상담 1건 근거도 불가) 그 차이만 `kin_format.py`에 둔다.
- **길이 상한은 실측으로 정한다.** 결론 1문단 + 근거(법조문 1~2개) + 안내(기관·면책) 3단이 담기는 최소 길이를 10건에서 재서 상한을 잡는다.

### 6.4 Convention 준수

- 답변 규칙 접미는 시스템 프롬프트 본문이 아니라 `pipeline.py`의 두 분기 접미 지점(`CLAUDE.md` G1~G3 규약)
- 공개 게시 제외 판정은 `storage.py` 단일 출처, 재선언 금지
- 프론트 `fetch` 추가 시 `resp.ok` 검사, `test_public_fetch.js` 디렉터리 발견 대상
- `public/index.html` 주석에 내부 경로·함수명 기재 금지

---

## 7. Implementation Order

| Phase | Task | 산출물 |
|-------|------|--------|
| 0 | ~~지식iN 붙여넣기 실측~~ **완료(2026-09-22)** — 통과/깨짐 매트릭스 §1.2 | 실험대 기록 |
| 1 | FR-02 변환기(JS) + 화이트리스트 단위 테스트 — 순수 함수, 먼저 만들어 fixture 확보 | `public/kin_format.js`, `test_kin_format.js` |
| 2 | 변환기 출력을 실험대 "내 HTML 시험대"에 넣어 재검증 + 인용구 대안 확인 | 실측 기록(사용자) |
| 3 | FR-01 지식iN 모드 프롬프트 + 두 경로 접미 + 배선 테스트 | `prompts.py`, `pipeline.py` |
| 4 | FR-03 게시 부적합 판정 메타 | `pipeline.py` |
| 5 | FR-04 일괄 실행 → 복사 버튼 검토 페이지 + `test_naver_kin.py --mode kin` | `generate_kin_answers.py` |
| 6 | 10건 샘플 실행 → 길이·면책·판정 측정 → 상한 확정 | 측정표 |
| 7 | FR-02 웹 UI "지식iN용 복사" 액션 | `index.html` |
| 8 | CLAUDE.md 등재(규약 + 실험대 링크) | 문서 |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-09-22 | Initial draft — 사용자 확인(형식·길이 + 게시 워크플로우, 포맷 유지 복사) 기반 4 FRs | Claude |
| 0.3 | 2026-09-22 | 사용자 결정으로 범위 축소 — 출력 형식 불변, FR-02만 구현. `public/kin_format.js` + `test_kin_format.js`(12건) + `index.html` 버튼 + `sw.js` v9. 실측 답변 5건 변환 검증(#1은 저장본 자체가 절단), Playwright로 버튼→변환→복사 배선 확인 | Claude |
| 0.2 | 2026-09-22 | 지식iN 붙여넣기 실측 반영 — 리스크 ① 해소, 기본 경로를 플레인 텍스트→**인라인 스타일 HTML 리치텍스트**로 전환. FR-02 허용 집합을 실측 통과 항목으로 한정, FR-04를 복사 버튼 검토 페이지로 변경, 변환기를 JS 단일 구현으로 공유하는 방향 추가 | Claude |
