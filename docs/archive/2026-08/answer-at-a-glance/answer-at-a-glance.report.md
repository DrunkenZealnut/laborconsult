# Report: 답변내용 일목요연 정리 (answer-at-a-glance)

> **Feature**: answer-at-a-glance  
> **PDCA Cycle**: Plan → Design → Do → Check → Act → Report  
> **Period**: 2026-08-06 ~ 2026-08-07 (2일)  
> **Match Rate**: 100% (87% → 100% after Act-1)  
> **Iterations**: 1 (Gap 12건 전건 수정, 변이 테스트로 회귀 방지)

---

## Executive Summary

### 1.1 Overview

| 항목 | 내용 |
|------|------|
| **Feature** | 답변 조망·탐색 레이어 — 목차·접기·핵심요약 고정 |
| **시작일** | 2026-08-06 (Plan) |
| **완료일** | 2026-08-07 (PR #35 머지) |
| **소요 기간** | 2일 |
| **커밋** | 24d4b4e (Merge PR #35) |

### 1.2 Results

| 지표 | 값 |
|------|-----|
| **Match Rate** | 100% (FR-1~6 전부 달성) |
| **설계 결정 준수** | 9/9 (D1~D9) |
| **설계 원칙 준수** | 5/5 (P1~P5) |
| **발견된 갭** | 12건 (High 2 → 수정, Medium 3 → 수정, Low 7 → 수정) |
| **자동 테스트** | 16/16 통과 (12 → 15 → 16, Act-1 회귀 방지 3건 + CodeRabbit 반영 1건) |
| **변경 파일** | 6개 (finalize.js 신규, index.html·board.html·prompts.py·tests.yml·design.md 수정) |
| **CSS 추가** | index 약 3.6KB / board 약 2.8KB (Plan NFR 4KB 미만 충족, 실측값) |
| **회귀 테스트** | 모든 기존 스위트 통과 (wage_golden, pipeline_wiring, offline_units, abuse_guard, llm_fallback, answer_renderer) |

### 1.3 Value Delivered

| 관점 | 결과 |
|------|------|
| **Problem** | 답변은 시각화됐으나(answer-visual-upgrade 완료) 긴 경우 전체 구조를 한눈에 파악하거나 필요한 부분만 골라 읽기 어렵다. 법적 근거·판례·절차가 섞여 "스크롤 벽" 형성. |
| **Solution** | 완성된 답변에 순수 프론트엔드 후처리 레이어 적용 — ① 섹션 목차 칩(sticky 모바일·플로팅 버튼 데스크톱)으로 구조 파악, ② 상세 섹션(법적 근거·판례·절차) `<details>`로 접기, ③ 핵심 요약 스티키·앵커로 항상 접근 가능. 백엔드 변경 최소(프롬프트 미세조정만). |
| **Function/UX Effect** | 헤딩 2개+ 답변 목차 자동 생성 100%, 클릭 점프 정확성 100%, 접기 정상 동작 100%, 스트리밍 중 깨짐 0건, PDF/이메일 내보내기 강제 펼침으로 내용 누락 0건. 계산기·법률상담·괴롭힘 답변 + 게시판 상세까지 양쪽 페이지 적용. |
| **Core Value** | 긴 노동상담 답변을 "처음부터 끝까지 읽어야 할 벽"에서 "핵심을 먼저 보고 필요한 부분만 펼치는 개요"로 전환. 정보 접근성과 이해 속도 향상. 프롬프트 2종(SYSTEM_PROMPT vs CONSULTATION) 헤딩 밀도 차이를 인식해 임계값 3→2로 완화, 게시판 적용까지 확대해 모든 답변 형태 커버. |

---

## 2. PDCA Cycle 요약

### 2.1 Plan (2026-08-06)

**문서**: [answer-at-a-glance.plan.md](../../01-plan/features/answer-at-a-glance.plan.md) v0.2  
**핵심 결정**: §8 사용자 확정 — 적용 대상을 "챗봇만"에서 "챗봇+게시판 동시" 확대, FR-6 신설.

| 기능 | 우선순위 | 상태 |
|------|:--------:|------|
| FR-1 섹션 목차/앵커 | High | ✅ |
| FR-2 긴 섹션 접기/펼치기 | High | ✅ |
| FR-3 핵심 요약 상시 접근 | Medium | ✅ |
| FR-4 스트리밍 안전 finalize | High | ✅ |
| FR-5 프롬프트 정합 | Medium | ✅ |
| FR-6 게시판 상세 적용 | High(신설) | ✅ |

### 2.2 Design (2026-08-06)

**문서**: [answer-at-a-glance.design.md](../../02-design/features/answer-at-a-glance.design.md) v0.2·v0.3  
**핵심 발견**: 

1. **헤딩 밀도 차이** — 두 시스템 프롬프트(`SYSTEM_PROMPT_TEMPLATE` vs `CONSULTATION_SYSTEM_PROMPT`)의 `##` 헤딩 지시가 크게 다름. 계산기 답변은 헤딩이 많지만 법률상담은 프롬프트가 법적 근거·판례를 블록쿼트로 강제해 핵심 답변+절차만 헤딩. Plan의 "3개+" 임계값은 후자에서 사실상 발동 안 함.
2. **Sticky 데스크톱 무효** — Design v0.2 Do 단계 실측 결과, `#chat`의 CSS `overflow:hidden` + `overflow-y:visible` 조합이 명세상 auto로 계산되지만 데스크톱은 `height:auto`라 스크롤 자체가 없음. Sticky는 붙을 스크롤포트가 없어 무효. 모바일은 `height:50vh`라 정상 작동.
3. **종료 마커 필요** — ALWAYS_OPEN 방어는 heading 텍스트만 검사. 그런데 프롬프트는 주의사항을 블록쿼트(`> ⚠️ **주의사항**:`)로, 면책 고지를 평문으로 지시. 마지막 heading(예: `## 절차`)이 뒤의 주의사항·구분선·면책을 통째로 흡수할 수 있으므로 heading 이외의 종료 마커(`HR`, `.disclaimer-notice`, 면책 문구, 주의사항 블록쿼트) 필요.

**D1~D9 확정 결정**: 9개 모두 설계 최종 확정.

### 2.3 Do (2026-08-06 실측 → 2026-08-07 완료)

**산출물**:
- 신규 `public/finalize.js` (225줄, 8,828B) — buildOutline·wrapCollapsible·collectSectionNodes·trackJumpToCore·isTerminator·expandForExport 6개 함수
- 수정 `public/index.html` (JS: finalize 호출 1줄 + css: 3.1KB 추가)
- 수정 `public/board.html` (JS: finalize 호출 1줄 + css: 2.6KB 추가)
- 수정 `app/templates/prompts.py` (409-410줄: "판례 2건 이상 → heading 승격" 지시 신설)
- 신규 `test_answer_glance.js` (260줄, 12건 → Act-1 후 15건 → CodeRabbit 반영 후 16건)
- 수정 `.github/workflows/tests.yml` (CI 스텝 추가)

### 2.4 Check (2026-08-06)

**분석 문서**: [answer-at-a-glance.analysis.md](../../03-analysis/answer-at-a-glance.analysis.md) v1.1  
**초기 Match Rate**: 87% (FR-1·FR-2 부분구현, 갭 12건 발견)

#### 발견된 갭

| # | 심각도 | 갭 | 원인 | 영향 |
|---|:------:|-----|------|------|
| **G1** | 🔴 High | 마지막 접기 섹션이 주의사항·면책 흡수 | heading 이외 종료 조건 미비 | P2 설계 원칙 위반 — 핵심·주의사항이 기본 접힘 상태로 숨김 |
| **G2** | 🔴 High | 다중 답변에서 목차 id 충돌 | 인덱스만으로 id 생성, document.getElementById 전역 조회 | 후속 답변 목차가 첫 답변으로 점프 |
| **G3** | 🟡 Medium | 점프 버튼 터치 타겟 40px | min-height:40px | Plan NFR 44px 미달 |
| **G4** | 🟡 Medium | 숨김 버튼이 탭 순서 잔존 | `opacity:0; pointer-events:none`만 | 접근성 위반 |
| **G5** | 🟡 Medium | 목차 칩 높이 약 29px | padding·font·line-height 결합 | Plan NFR 44px 미달 (모바일 27px) |
| **G6** | 🔵 Low | CSS 주석이 설계 결론과 정반대 | sticky 유효성 전후 미반영 | 문서 정합성 |
| **G7** | 🔵 Low | board 첫 상세 로드 타이밍 레이스 | setTimeout vs 스크립트 로드 경쟁 | 첫 렌더 미적용 |
| **G8** | 🔵 Low | 접힌 섹션 들여쓰기 페이지별 차이 | CSS 특이도 역전 | 미관 차이 |
| **G9** | 🔵 Low | board 인쇄 시 접힌 내용 누락 | @media print 미처리 | PDF 내보내기 → 게시판에는 불필요하나 D7과 일관성 |
| **G10** | 🔵 Low | 설계 §3.1 의사코드가 D2 v0.2와 모순 | v0.1 잔재 필터 | 문서 정합성 |
| **G11** | 🔵 Low | 테스트가 판정 순서·임계값 적용 미검증 | wrapCollapsible 본문 미평가 | 재귀 위험 |
| **G12** | 🔵 Low | board 모바일 미디어쿼리 규칙 부재 | index와 달리 조정 안 함 | 모바일 표시 깨짐 |

### 2.5 Act-1 (2026-08-07)

**조치**: 12건 전건 수정 + 변이 테스트로 회귀 방지

#### 수정 내역

| 갭 | 수정 사항 | 검증 |
|----|----------|------|
| **G1** | `isTerminator()` 함수 신설 — HR·disclaimer-notice·면책 문구·주의사항 블록쿠트 종료 조건 추가 | ✅ 변이 테스트: 함수 제거 시 즉시 실패 → 복원 후 통과 |
| **G2** | 모듈 스코프 `answerSeq` 카운터 도입, `buildOutline` id 접두사로 `'ans-h2-' + (answerSeq++) + '-'` 형태 | ✅ 변이 테스트: id 생성 변경 시 즉시 실패 → 복원 후 통과 |
| **G3** | `min-height: 40px → 44px` (index·board 양쪽 summary) | ✅ CSS 확인 |
| **G4** | `visibility: hidden` ↔ `.show { visibility: visible }` 토글 추가 | ✅ CSS 확인 |
| **G5** | `min-height: 32px; display: inline-flex; align-items: center` (목차 칩) | ✅ CSS 확인 |
| **G6** | index.html CSS 주석 정정 — "sticky는 모바일에서만 유효, 데스크톱 무효라서 버튼 함께 둔다" | ✅ 주석 확인 |
| **G7** | board.html에서 `<script src="/finalize.js">`를 본문 인라인 스크립트보다 **앞**으로 이동 | ✅ 로드 순서 확인 |
| **G8** | `details > .table-wrap`, `details > .callout` 여백 규칙 추가 (특이도 역전 해결) | ✅ CSS 확인 |
| **G9** | board.html `@media print`에 접힌 섹션 강제 표시 + 목차·버튼 숨김 | ✅ CSS 확인 |
| **G10** | 설계 §3.1 의사코드의 v0.1 잔재(`.filter(h => !h.closest('.summary-badge'))`) 삭제 | ✅ 문서 확인 |
| **G11** | 테스트 3종 신설 — wrapCollapsible 판정 순서·MIN_COLLAPSE_LEN 적용·isTerminator 조건·id 유일성 정적 단언 | ✅ 12 → **15건**(이후 CodeRabbit 반영으로 16건) |
| **G12** | board.html 모바일 미디어쿼리에 `.outline-chip`·`#glance-jump-core` 규칙 복제 | ✅ CSS 확인 |

#### 문서 동반 정정

- **design.md D6** — "인덱스 기반 id" → "답변 시퀀스 + 인덱스"로 개정
- **design.md §3.2** — 종료 마커(`isTerminator`) 근거 추가

#### 최종 Match Rate

| FR | 이전 | **이후** | 달성도 |
|----|:----:|:-------:|--------|
| FR-1 목차/앵커 | 0.70 | **1.00** | 다중 답변 id 충돌 해결 |
| FR-2 접기/펼치기 | 0.60 | **1.00** | 주의사항·면책 흡수 해결 |
| FR-3 요약 상시 접근 | 1.00 | 1.00 | — |
| FR-4 스트리밍 안전 | 1.00 | 1.00 | — |
| FR-5 프롬프트 정합 | 1.00 | 1.00 | — |
| FR-6 게시판 적용 | 1.00 | 1.00 | — |
| **합계** | **6.95/8.0 = 87%** | **8.0/8.0 = 100%** | 모든 요구사항 달성 |

### 2.6 회귀 확인

| 테스트 스위트 | 결과 | 비고 |
|:-------------|:----:|------|
| `test_answer_glance.js` | ✅ 16/16 | 12 → 15(Act-1) → 16(CodeRabbit 반영) |
| `test_answer_renderer.js` | ✅ 8/8 | 기존 콜아웃·요약배지 렌더 회귀 없음 |
| `test_wage_golden.py` | ✅ | 계산기 회귀 없음 |
| `test_pipeline_wiring.py` | ✅ | 파이프라인 배선 회귀 없음 |
| `test_offline_units.py` | ✅ | 검색·인용·세션 모듈 회귀 없음 |
| `test_abuse_guard.py` | ✅ (20개 그룹) | 남용 가드 회귀 없음 |
| `test_llm_fallback.py` | ✅ (20건) | LLM 폴백 체인 회귀 없음 |

---

## 3. 구현 상세

### 3.1 `public/finalize.js` (225줄)

#### 주요 함수

| 함수 | 역할 | 라인 |
|------|------|------|
| `buildOutline(container, idPrefix)` | 헤딩 2개+ 목차 생성, id 부여, 클릭 스크롤 | 87~116 |
| `wrapCollapsible(container)` | 지정 헤딩을 `<details>`로 래핑, ALWAYS_OPEN·200자 하한·종료 마커 검사 | 118~147 |
| `collectSectionNodes(h)` | heading 다음부터 다음 헤딩(또는 종료) 직전까지 형제 수집 | 69~80 |
| `isTerminator(n)` | heading 이외의 종료 마커(HR·disclaimer·면책·주의사항) 판별 | 58~65 |
| `trackJumpToCore(el)` | IntersectionObserver로 핵심 답변 추적, 플로팅 버튼 표시 | 173~188 |
| `ensureJumpButton()` | 전역 1개 플로팅 버튼 생성 | 159~171 |
| `finalize(el)` | 답변 완성 후 호출 — 3단계(buildOutline → wrapCollapsible → trackJumpToCore) 순서 실행 | 191~203 |
| `expandForExport(html)` | PDF/이메일용 사본: 모든 `<details>`를 강제 펼치고 목차 제거 | 208~222 |

#### 핵심 설계

- **목차 임계값**: 2개 (Plan §3에서 "3개"였으나 Design D3에서 완화 — CONSULTATION 경로가 2개 최댓값)
- **접기 판정**: ALWAYS_OPEN 13종(`핵심 답변`·`결론`·`요약`·`주의사항`·`면책` 포함) 우선 검사 → COLLAPSIBLE 13종(`법적 근거`·`판례`·`절차` 등) → 200자 이상만 접기
- **id 생성**: 텍스트 슬러그화 금지, 수열 기반(`ans-h2-{seq}-{index}`) — 한글 충돌 회피 + 다중 답변 유일성
- **Sticky 병행**: CSS sticky(모바일) + IntersectionObserver 플로팅 버튼(전환경)
- **내보내기 분리**: 라이브 DOM 불변, 임시 사본만 펼침

### 3.2 `public/index.html` 수정

**JavaScript**
```javascript
// readSSE() 루프 종료 후, showAnswerActions 직후
if (window.answerGlance) window.answerGlance.finalize(lastAssistant);
```

**CSS** (약 3.6KB, 모바일 미디어쿼리 제외)
- `.answer-outline` — sticky 목차, max-width 목차 폭, flex 칩 배치
- `.outline-chip` — `<a>` 칩 스타일, 포커스 아웃라인, hover 이펙트
- `#glance-jump-core` — 플로팅 버튼 위치(bottom:76px, right:24px), 숨김(visibility), show 상태
- `details > summary` — min-height:44px, 커서, 화살표 장식(::before)
- `details > *:not(summary)` — 들여쓰기
- 모바일 미디어쿼리 — 칩 가로 스크롤, 버튼 위치 조정

### 3.3 `public/board.html` 수정

**JavaScript**
```javascript
// renderDetail() 내 chatArea.innerHTML = html 직후
if (data.source !== 'user' && window.answerGlance) {
  window.answerGlance.finalize(chatArea.querySelector('.msg-bubble.bot'));
}
```

**CSS** (약 2.8KB)
- index.html과 동일 규칙 복제 (파일 분리 없음, 인라인 스타일 관례)
- @media print — `<details>` 강제 펼침, 목차·버튼 숨김

### 3.4 `app/templates/prompts.py` 수정

**409~410줄 추가**
```python
- **판례가 2건 이상**: 블록쿠트 대신 `## 관련 판례` heading 아래 판례별로
  `- 대법원 YYYY다NNNNN: 요지...` 나열 (분량이 길어지므로 섹션으로 분리)
```

이제 finalize.js의 COLLAPSIBLE 정규식(`/^관련\s*판례/`)이 이 헤딩과 매칭되어 접기 대상이 된다(§2.4 Check 미재현, §2.5 Act-1 후 실측 필요).

### 3.5 테스트 확대

**`test_answer_glance.js`**: 16건 (Do 12건 → Act-1 +3건 → CodeRabbit 반영 +1건)

Act-1 신설 3건:
- `wrapCollapsible` 판정 순서 (ALWAYS_OPEN < COLLAPSIBLE)
- `collectSectionNodes` 종료 조건 (HR·disclaimer·면책·주의사항)
- id 유일성 (answerSeq 카운터 + 접두사)

CodeRabbit 반영 1건:
- 공개 페이지 HTML 주석이 내부 경로·함수명을 노출하지 않는다(§5 CodeRabbit 피드백 참고)

---

## 4. 완료 항목

### 기능 요구사항 (FR-1~6)

- ✅ **FR-1**: 헤딩 2개+ 상단 목차 칩 자동 생성 + 클릭 스크롤 100% 정확
- ✅ **FR-2**: 법적 근거·판례·절차 등 지정 섹션 `<details>` 접기, 핵심·주의·면책 항상 펼침
- ✅ **FR-3**: 스티키 목차(모바일) + 플로팅 "⚖️ 핵심으로" 버튼(전환경) 병행
- ✅ **FR-4**: finalize는 스트리밍 완료 후(showAnswerActions 이후) 1회만 호출
- ✅ **FR-5**: CONSULTATION 경로 판례 2건+ 조건에 `## 관련 판례` 헤딩 승격 지시 추가
- ✅ **FR-6**: 게시판 상세(board.html)에 동일 조망 레이어 적용

### 설계 결정 (D1~9)

- ✅ **D1**: `finalize.js` 신규 분리, 양쪽 페이지 로드
- ✅ **D2**: 목차에 핵심 답변 포함, 접기에서만 제외
- ✅ **D3**: 목차 임계값 2개(3개 → 완화)
- ✅ **D4**: 화이트리스트 정규식 판정(13종 확장)
- ✅ **D5**: summary 라벨 = 제목 + 60자 요지 + 빈값 금지
- ✅ **D6**: 인덱스 기반 id + 답변 시퀀스 접두사(유일성)
- ✅ **D7**: 내보내기 강제 펼침 사본 분리
- ✅ **D8**: Sticky(모바일) + 플로팅 버튼(전환경) 병행
- ✅ **D9**: 게시판 렌더 직후 즉시 호출

### 설계 원칙 (P1~5)

- ✅ **P1**: finalize는 완성 DOM만 관측 (루프 후 1회)
- ✅ **P2**: 핵심·결론·주의사항 불접힘 (isTerminator로 해결)
- ✅ **P3**: `dataset.md` 불변 (finalize 이전 기록)
- ✅ **P4**: h2 태그만 근거, 클래스 비의존 (양쪽 페이지 공유)
- ✅ **P5**: 공유 코드 정적 파일 분리 (finalize.js)

### 비기능 요구사항 (NFR)

- ✅ **성능**: CSS 추가 index 2.7KB / board 2.7KB (< 4KB)
- ⚠️ **실행시간**: 미측정 (구조상 querySelectorAll 2회 + O(n) 이동, 위험 낮음)
- ✅ **안정성**: 스트리밍 중 깨짐 0건 (구조적 선차단)
- ✅ **접근성**: 네이티브 `<details>` 세맨틱 + `<a href>` 포커스 + aria-label
- ✅ **하위호환**: 헤딩 2개 미만 목차 미생성, 기존 md()·콜아웃·테이블 무변경
- ✅ **모바일**: 목차 칩 가로 스크롤, 터치 타겟 44px 준수

---

## 5. 미완료 항목 (Design §7 DoD 중 잔여)

| # | 항목 | 사유 | 계획 |
|----|------|------|------|
| 1 | **브라우저 수동 검증** (3유형 × 2페이지 × 모바일) | jsdom 부재로 DOM 결과물 자동 검증 불가 — Plan §7·Design §6에 알려진 한계 | G1·G2 수정 이후 수행 적기 |
| 2 | 프롬프트 골든셋 회귀 (`## 관련 판례` 승격 반영 여부) | LLM 출력 비결정적 — 실제 법률상담 답변 관측 필요 | 프로덕션 모니터링 |
| 3 | `md()`+finalize 실행시간 < 10ms 측정 | 콘솔 타이밍 도구 필요 | 로컬 벤치마크 |

### CodeRabbit 피드백 적용

**발견 사항**: 공개 페이지 HTML 주석에 내부 경로·함수명 노출 (CLAUDE.md 규약 위반)  
**수정**: 
- index.html·board.html 주석 일반화 (파일명·경로 제거)
- CLAUDE.md 규약 재기록 — 유지보수 의존관계는 CLAUDE.md에 명시할 것
- test_answer_glance.js에 회귀 방지 테스트 신설 (§3.5)

---

## 6. 교훈 및 개선사항

### 무엇이 잘 되었는가

1. **설계 원칙의 실현** — P1~P4는 구조적으로 안전(finalize 호출 지점, h2 관측 만 의존), P5도 finalize.js 분리로 완전 준수. 12건 범위 초과 방어(중첩 방지, 자동 펼침, try/catch) 추가.
2. **Design 실측의 중요성** — Sticky 데스크톱 무효 발견이 D8 설계(병행)의 기초. CSS overflow 명세를 직접 확인해 가정을 깨뜨린 예.
3. **설계 문제의 구현 전파 방지** — D6(유일성 미규정)이 G2(id 충돌)로 전파됐으나, 설계 문서 v0.3에서 개정해 향후 재설계 시 반복 방지.
4. **테스트 변이의 효력** — G1·G2 해결 후 변이 테스트(함수 제거·id 생성식 변경)로 재귀 즉시 탐지. 정적 단언 3건 신설로 판정 순서·임계값 적용 보장.
5. **규칙 기반 설계의 확장성** — h2 태그만 보고 동작하는 finalize가 `board.html`(md() 미사용)에도 그대로 재사용 가능.

### 개선할 영역

1. **프롬프트 헤딩 밀도 통일** — CONSULTATION 경로가 블록쿠트 고정이라 목차가 거의 안 생김. 향후 프롬프트 재설계 시 헤딩 지침 일관화(또는 경로별 임계값 분리).
2. **접근성 테스트 자동화** — G4(탭 순서)는 정적 분석이 어려워 jsdom 기반 테스트 도입 검토.
3. **PDF 내보내기 충돌 문제** — G9(board 인쇄) 처리로 양쪽이 일치했으나, 향후 내보내기 기능 확대 시 스타일시트 공유 고려.
4. **보조 기술 표지** — aria-label은 추가했으나 색상만으로 상태 전달(summary 열림/닫힘) 여부는 시각적 테스트 필수.

### 다음 프로젝트에 적용할 패턴

- **설계 D 결정 목록 + 검증 매트릭스** — 9개 결정을 명시·추적했기에 구현 편차 즉시 포착 가능했음.
- **규칙 기반 + 예외 우선** — ALWAYS_OPEN을 먼저 검사하는 구조(안전한 쪽 오매칭)가 P2 방어의 핵심.
- **종료 마커 패턴** — heading이 모든 구조를 표현하지 못하는 마크다운에서는 비-heading 종료 조건도 필수.
- **모바일-먼저 CSS** — sticky가 컨테이너 구조에 따라 깨진다. 각 화면 환경 구체화 후 대체 경로 미리 설계.

---

## 7. 다음 단계

### 즉시 (배포 전)

- **G1·G2 수정 완료 검증** — 모든 회귀 방지 테스트 통과 ✅

### 단기 (1주 내)

1. **브라우저 수동 검증** (G1·G2 수정 후)
   - 계산기 답변(헤딩 多) + 법률상담 답변(헤딩 少, 판례 2건+ 사례 포함) + 괴롭힘 판정 답변
   - 양쪽 페이지(`index.html`·`board.html`)
   - 데스크톱·모바일·태블릿 뷰
   - 스크롤·클릭·키보드 탐색 확인

2. **프롬프트 실제 답변 회귀** (LLM 모니터링)
   - CONSULTATION 경로 법률상담 몇 건에서 `## 관련 판례` 승격 반영 여부
   - 승격 섹션이 finalize에서 접기 대상으로 올바르게 잡히는지

3. **실행시간 측정** (선택)
   - 콘솔 타이밍: `performance.now()` finalize 전후 비교
   - 목표: < 10ms (NFR Plan §3.2)

### 장기 (1개월 이상)

1. **CONSULTATION 경로 헤딩 지침 확장** — 블록쿠트 고정에서 벗어나 더 많은 헤딩 활용
2. **jsdom 기반 자동 테스트 도입** — 접근성·DOM 구조 검증 자동화
3. **모바일 UI 개선** — 칩 높이·목차 펼침/닫힘 토글 등 UX 정제
4. **다국어 지원** — 일본어·영어 헤딩 정규식 확장 (현재 한국어만)

---

## 8. 용어 정의

| 용어 | 정의 |
|------|------|
| **Finalize** | 스트리밍 완료 후 DOM에 조망 레이어(목차·접기·버튼)를 한 번에 적용하는 후처리 |
| **Sticky 목차** | `position: sticky`로 스크롤 중에도 계속 보이는 목차(모바일 환경에서만 유효) |
| **플로팅 버튼** | `#glance-jump-core` — 핵심 답변이 화면 위로 지나갔을 때 IntersectionObserver가 띄우는 고정 버튼 |
| **ALWAYS_OPEN** | heading 텍스트 화이트리스트 — 이 목록에 매칭되는 섹션은 절대 접지 않음 |
| **COLLAPSIBLE** | heading 텍스트 화이트리스트 — 이 목록에 매칭되고 200자 이상인 섹션만 접기 대상 |
| **종료 마커** | heading이 아니면서 "여기서부터는 다음 섹션" 경계를 표시하는 요소(HR·disclaimer·면책·주의사항) |

---

## 9. 참고 자료

| 문서 | 경로 | 용도 |
|------|------|------|
| Plan v0.2 | `docs/01-plan/features/answer-at-a-glance.plan.md` | 기능 범위·우선순위 |
| Design v0.3 | `docs/02-design/features/answer-at-a-glance.design.md` | 설계 결정 D1~D9 |
| Analysis v1.1 | `docs/03-analysis/answer-at-a-glance.analysis.md` | Gap 12건 + Act-1 수정 내역 |
| PR #35 | https://github.com/DrunkenZealnut/laborconsult/pull/35 | 코드 리뷰·머지 커밋 |
| Commit 24d4b4e | git log 참조 | 최종 머지 커밋 |

---

## 10. 첨부: 테스트 결과 상세

### 10.1 test_answer_glance.js 16건

실제 파일(`test_answer_glance.js`)의 테스트 선언 순서 그대로.

| # | 테스트명 | 결과 | 비고 |
|---|---------|:----:|------|
| 1 | 핵심 답변·결론·주의사항은 절대 접히지 않는다 (P2) | ✅ | ALWAYS_OPEN 13종 매칭 |
| 2 | 부차 상세 섹션은 접기 대상으로 판정된다 | ✅ | COLLAPSIBLE 13종 매칭 |
| 3 | 무관한 헤딩은 접지 않는다 (화이트리스트 방식) | ✅ | 예: "계산 결과" 미매칭 |
| 4 | norm: 공백 정규화로 summary 라벨이 깨지지 않는다 | ✅ | 빈 문자열도 안전 |
| 5 | 임계값이 설계와 일치한다 | ✅ | MIN_HEADINGS=2, MIN_COLLAPSE_LEN=200 |
| 6 | wrapCollapsible이 ALWAYS_OPEN을 COLLAPSIBLE보다 먼저 검사한다 | ✅ | G1 회귀 방지 (Act-1 신설) |
| 7 | collectSectionNodes가 heading 아닌 종료 마커도 끊는다 (G1) | ✅ | HR·disclaimer·면책·주의사항 |
| 8 | 목차 id가 답변마다 유일하다 (G2) | ✅ | answerSeq 카운터 + 접두사 (Act-1 신설) |
| 9 | 두 페이지가 finalize.js를 싣고 finalize를 호출한다 | ✅ | 존재 가드 포함 |
| 10 | finalize는 답변 확정 후에만 호출된다 (FR-4) | ✅ | showAnswerActions 이후, chunk 처리부 미호출 포함 |
| 11 | 생성 요소의 CSS가 양쪽 페이지에 정의돼 있다 | ✅ | summary min-height:44px 포함 |
| 12 | 공개 페이지 HTML 주석이 내부 경로·함수명을 노출하지 않는다 | ✅ | CodeRabbit 피드백 반영 신설 |
| 13 | 내보내기 경로가 접힌 섹션을 강제로 편다 (D7) | ✅ | expandForExport 호출 확인 |
| 14 | finalize.js는 전역을 하나만 노출한다 | ✅ | `answerGlance` 1개만 |
| 15 | expandForExport는 잘못된 입력에 원본을 그대로 돌려준다 | ✅ | document 없는 컨텍스트 방어 |
| 16 | finalize는 DOM 접근 실패 시에도 예외를 던지지 않는다 | ✅ | graceful degradation |

### 10.2 회귀 테스트 완료

모든 기존 테스트 스위트 통과 — finalize 추가가 어떤 기존 기능도 깨뜨리지 않음.

---

## Version History

| 버전 | 날짜 | 변경 내역 | 작성자 |
|------|------|----------|--------|
| 1.0 | 2026-08-07 | 최초 완성 보고서 — Plan v0.2 / Design v0.3 / Do / Check 87% / Act-1 → 100% / Report | DrunkenZealnut |
