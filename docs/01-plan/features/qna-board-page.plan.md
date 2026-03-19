# 질문게시판 독립 페이지 Planning Document

> **Summary**: 메인페이지 하단의 질문게시판 섹션을 독립 `/board` 페이지로 분리하고, 검색·카테고리 필터·답변 전문 보기·페이지네이션을 갖춘 본격적인 게시판 UI 구현
>
> **Project**: laborconsult
> **Author**: Claude
> **Date**: 2026-03-19
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 현재 질문게시판은 메인페이지 하단에 최근 10건만 미리보기로 표시되며, 검색·필터·전문 보기가 불가능하여 과거 Q&A 활용도가 낮음 |
| **Solution** | 독립 `public/board.html` 페이지 신규 생성 + 백엔드 API 2개 추가 (검색, 상세 조회). 메인페이지 게시판 섹션은 "전체 보기" 링크로 연결 |
| **Function/UX Effect** | 카테고리 필터 12종, 키워드 검색, 답변 전문 마크다운 렌더링, 반응형 페이지네이션으로 축적된 Q&A 자산의 재활용 극대화 |
| **Core Value** | SEO 유입 증가 (개별 Q&A가 검색엔진에 노출) + 사용자 셀프서비스 비율 향상 (챗봇 질문 전에 유사 사례 탐색) |

---

## 1. Overview

### 1.1 Purpose

챗봇이 처리한 질문·답변을 축적 자산으로 활용하기 위해 독립적인 게시판 페이지를 구축한다. 사용자는 카테고리 필터와 키워드 검색으로 과거 Q&A를 탐색하고, 답변 전문을 마크다운 형태로 읽을 수 있다.

### 1.2 Background

- **현재 상태**: `public/index.html` 하단에 `#board-section`으로 최근 10건 표시. 답변은 300자 미리보기만 제공. 검색/필터 없음.
- **기존 API**: `GET /api/board/recent` — 페이지네이션 + 비식별화 지원. 검색/필터 미지원.
- **기존 데이터**: `qa_conversations` 테이블에 category, question_text, answer_text 저장. 카테고리 12종 (`CATEGORY_MAP` in `storage.py`).
- **수요**: 동일한 노동법 질문이 반복됨 → 과거 답변을 검색 가능하게 하면 챗봇 부하 감소 + 사용자 만족도 향상.

### 1.3 Related Documents

- 메인페이지 설계: `docs/archive/2026-03/chatbot-main-page/chatbot-main-page.design.md` (질문게시판 섹션)
- 기존 API: `api/index.py:391-443` (`board_recent`)
- 카테고리 매핑: `app/core/storage.py:16-42` (`CATEGORY_MAP`)
- 비식별화: `api/index.py:393-405` (`_anonymize`)

---

## 2. Scope

### 2.1 In Scope

- [ ] FR-01: `public/board.html` 독립 페이지 생성 (반응형, 메인페이지 디자인 계승)
- [ ] FR-02: 카테고리 필터 (12종 카테고리 버튼/탭)
- [ ] FR-03: 키워드 검색 (질문 텍스트 대상)
- [ ] FR-04: 답변 전문 보기 (마크다운 렌더링, 비식별화)
- [ ] FR-05: 페이지네이션 (숫자 페이지 + 이전/다음)
- [ ] FR-06: 백엔드 API 확장 (`/api/board/search`, `/api/board/{id}`)
- [ ] FR-07: 메인페이지 게시판 섹션에서 "전체 보기 →" 링크 추가
- [ ] FR-08: Vercel 라우팅 (`/board` → `board.html`)

### 2.2 Out of Scope

- 사용자 직접 글쓰기/댓글 기능 (커뮤니티 기능)
- 로그인/회원가입
- 좋아요/추천 기능
- SEO를 위한 SSR (현재 정적 HTML + CSR 유지)

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | **독립 페이지**: `public/board.html` — 히어로(제목+설명), 검색바, 카테고리 필터, 질문 목록, 페이지네이션, 푸터. 메인페이지 디자인 톤 유지 (Noto Serif KR + Pretendard, 네이비+코퍼) | High | Pending |
| FR-02 | **카테고리 필터**: 전체/임금·수당/퇴직금/해고/실업급여/휴가·휴일/4대보험/산업재해/직장내 괴롭힘/육아·출산/임금체불/근로장려금/일반상담. 클릭 시 해당 카테고리만 표시. URL 파라미터 반영 (`?category=해고`) | High | Pending |
| FR-03 | **키워드 검색**: 검색 입력 → `question_text` ILIKE 검색. 디바운스 300ms. URL 파라미터 반영 (`?q=주휴수당`) | High | Pending |
| FR-04 | **답변 전문 보기**: 질문 클릭 시 해당 Q&A 상세 영역 확장 (아코디언). 답변은 마크다운 렌더링 (marked.js). 비식별화 적용. "이 질문과 비슷한 질문하기" 버튼 → 메인페이지 챗봇으로 이동 | High | Pending |
| FR-05 | **페이지네이션**: 숫자 페이지 버튼 (최대 7개 표시) + 이전/다음 화살표. URL 파라미터 반영 (`?page=3`). 총 건수 표시 | Medium | Pending |
| FR-06 | **백엔드 API 확장**: `GET /api/board/search?q=...&category=...&page=1&per_page=15` (기존 `board_recent` 확장), `GET /api/board/{id}` (상세 조회, 답변 전문 + 비식별화) | High | Pending |
| FR-07 | **메인페이지 연결**: `#board-section`에 "전체 보기 →" 링크 추가 → `/board` 이동 | Low | Pending |
| FR-08 | **Vercel 라우팅**: `vercel.json`에 `/board` → `board.html` 라우트 추가 | Low | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| Performance | 게시판 목록 API 응답 < 500ms (Supabase 쿼리 + 비식별화) | 로깅 |
| Performance | 초기 로딩 < 2초 (CDN 라이브러리 포함) | Lighthouse |
| Security | 모든 출력 비식별화 (`_anonymize`) + XSS 방지 (`escHtml` 또는 marked sanitize) | 코드 리뷰 |
| Accessibility | WCAG 2.1 AA — 키보드 탐색, ARIA 라벨, 색상 대비 | Lighthouse |
| Mobile | 375px 뷰포트에서 정상 동작. 카테고리 필터 가로 스크롤 | 수동 테스트 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] `/board` 페이지 접근 시 질문 목록 정상 표시
- [ ] 카테고리 클릭 시 필터링 동작 + URL 파라미터 반영
- [ ] 검색어 입력 시 관련 질문 필터링 + URL 파라미터 반영
- [ ] 질문 클릭 시 답변 전문 마크다운 렌더링
- [ ] 페이지네이션 정상 동작 (1, 2, ... 7 형태)
- [ ] 메인페이지 "전체 보기" 링크 → `/board` 이동
- [ ] 모바일(375px) 반응형 정상 동작
- [ ] 모든 개인정보 비식별화 확인

### 4.2 Quality Criteria

- [ ] Lighthouse Performance ≥ 85
- [ ] 비식별화 누락 0건
- [ ] 기존 API (`/api/board/recent`) 하위 호환 유지

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Supabase ILIKE 검색 성능 저하 (대량 데이터) | Medium | Low | `question_text`에 GIN trigram 인덱스 추가 고려. 현재 데이터량(~10K건)에서는 문제 없음 |
| marked.js XSS 취약점 | High | Low | `marked` sanitize 옵션 활성화 + `DOMPurify` 병용 |
| 비식별화 누락으로 개인정보 노출 | High | Low | 기존 `_anonymize()` 재사용. 상세 API에서도 동일 적용 |
| 메인페이지 게시판 섹션과 중복 유지보수 | Low | Medium | 메인페이지 섹션은 최소한의 미리보기만 유지. 독립 페이지가 canonical |

---

## 6. Architecture Considerations

### 6.1 파일 구조

```
public/
├── board.html              ← FR-01: 신규 독립 페이지
├── index.html              ← FR-07: "전체 보기" 링크 추가
api/
└── index.py                ← FR-06: /api/board/search, /api/board/{id} 추가
vercel.json                 ← FR-08: /board 라우트 추가
```

### 6.2 API 설계

#### `GET /api/board/search` (신규)

```
Parameters:
  q        (optional) — 검색 키워드 (question_text ILIKE)
  category (optional) — 카테고리 필터 (예: "해고", "임금·수당")
  page     (optional, default: 1) — 페이지 번호
  per_page (optional, default: 15, max: 30) — 페이지당 건수

Response:
{
  "items": [
    {
      "id": "uuid",
      "category": "해고",
      "question": "비식별화된 질문",
      "answer_preview": "비식별화된 답변 300자...",
      "created_at": "2026-03-19T..."
    }
  ],
  "total": 1234,
  "page": 1,
  "per_page": 15,
  "has_more": true
}
```

#### `GET /api/board/{id}` (신규)

```
Response:
{
  "id": "uuid",
  "category": "해고",
  "question": "비식별화된 질문 전문",
  "answer": "비식별화된 답변 전문 (마크다운)",
  "created_at": "2026-03-19T..."
}
```

### 6.3 UI 구성

```
┌─────────────────────────────────────────────────┐
│  노동법률 질문게시판                               │
│  다른 분들이 물어본 질문과 답변을 검색해보세요         │
├─────────────────────────────────────────────────┤
│  🔍 [검색어를 입력하세요...]                       │
├─────────────────────────────────────────────────┤
│  [전체] [임금·수당] [퇴직금] [해고] [실업급여]       │
│  [휴가·휴일] [4대보험] [산업재해] [괴롭힘] [더보기▾] │
├─────────────────────────────────────────────────┤
│  총 1,234건                                      │
│                                                  │
│  ┌ [임금·수당] 최저시급으로 주휴수당...  3시간 전  ▾ │
│  │  답변: ## 주휴수당 계산 결과 ...               │
│  │  [비슷한 질문하기 →]                           │
│  └                                               │
│  ┌ [해고] 갑자기 내일부터 나오지...     1일 전   ▾ │
│  └                                               │
│  ...                                              │
├─────────────────────────────────────────────────┤
│  ◀ 1  2  3  4  5  6  7 ▶                        │
└─────────────────────────────────────────────────┘
```

### 6.4 CDN 라이브러리

- `marked.js` — 마크다운 렌더링 (답변 전문 표시)
- `DOMPurify` — XSS 방지 (marked 출력 sanitize)

### 6.5 디자인 원칙

- 메인페이지와 동일한 디자인 토큰: `Noto Serif KR` (제목) + `Pretendard` (본문), 네이비(`#1B2A4A`) + 코퍼(`#C08050`), max-width 800px
- 메인페이지 상단 네비게이션 바에서 "질문게시판" 링크 추가
- 게시판 → 메인 챗봇 전환 흐름: "비슷한 질문하기" 버튼 → `index.html?q=질문내용`

---

## 7. Implementation Order

| Phase | Task | 의존성 | 예상 변경량 |
|-------|------|--------|------------|
| 1 | FR-06: 백엔드 API (`/api/board/search`, `/api/board/{id}`) | 없음 | `api/index.py` +60줄 |
| 2 | FR-01 + FR-04: `board.html` 기본 구조 + 답변 전문 보기 | FR-06 | 신규 ~400줄 |
| 3 | FR-02 + FR-03: 카테고리 필터 + 키워드 검색 | FR-01 | `board.html` +100줄 |
| 4 | FR-05: 페이지네이션 | FR-01 | `board.html` +80줄 |
| 5 | FR-07 + FR-08: 메인페이지 링크 + Vercel 라우팅 | FR-01 | `index.html` +5줄, `vercel.json` +3줄 |

---

## 8. Next Steps

1. [ ] Design 문서 작성 (`qna-board-page.design.md`)
2. [ ] FR-06 백엔드 API 우선 구현
3. [ ] FR-01 독립 페이지 HTML/CSS/JS 구현
4. [ ] 통합 테스트 + 비식별화 검증

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-19 | Initial draft — 8 FRs defined | Claude |
