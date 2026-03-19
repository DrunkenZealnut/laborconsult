# 게시판 글쓰기 — 비밀번호 + 보안문자 Planning Document

> **Summary**: 질문게시판(`/board`)에 사용자 직접 글쓰기 기능 추가. 익명 게시를 위한 비밀번호(수정/삭제용) + 스팸 방지 보안문자(CAPTCHA) 적용
>
> **Project**: laborconsult
> **Author**: Claude
> **Date**: 2026-03-19
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 현재 게시판은 AI 챗봇 답변만 읽기 전용으로 표시되며, 사용자가 직접 노동법 질문을 게시할 수 없음. 글쓰기 기능이 없어 커뮤니티 축적이 불가능 |
| **Solution** | 글쓰기 폼(닉네임+비밀번호+카테고리+질문내용) + 서버 사이드 수학 CAPTCHA + bcrypt 비밀번호 해싱. 새 Supabase 테이블 `board_posts`로 AI Q&A와 분리 |
| **Function/UX Effect** | 비회원 익명 글쓰기 → 비밀번호로 본인 글 삭제 가능. 수학 보안문자로 봇 스팸 차단. 기존 게시판 목록에 사용자 질문도 함께 노출 |
| **Core Value** | 사용자 참여형 Q&A 커뮤니티로 전환 → 질문 다양성 증가 + 재방문율 향상. AI 답변 연동 시 자동 답변 제공 가능성 확보 |

---

## 1. Overview

### 1.1 Purpose

질문게시판에 사용자가 직접 노동법 관련 질문을 등록할 수 있는 글쓰기 기능을 추가한다. 로그인 없이 익명으로 작성하되, 비밀번호를 통해 본인 글을 삭제할 수 있게 한다. 봇 스팸을 방지하기 위해 보안문자(수학 CAPTCHA)를 적용한다.

### 1.2 Background

- **현재 상태**: `board.html`은 `qa_conversations` 테이블의 AI 챗봇 Q&A만 읽기 전용으로 표시. 글쓰기 기능 없음.
- **기존 Plan의 Out of Scope**: `qna-board-page.plan.md`에서 "사용자 직접 글쓰기/댓글 기능"을 명시적으로 제외했으나, 이번에 글쓰기 기능을 추가하기로 결정.
- **보안 요구**: 비회원 게시판이므로 (1) 스팸 봇 방지를 위한 CAPTCHA, (2) 글 관리를 위한 비밀번호가 필수.
- **기술 제약**: Vercel 서버리스 환경, 외부 CAPTCHA 서비스(reCAPTCHA 등) 대신 서버 사이드 수학 CAPTCHA로 외부 의존성 최소화.

### 1.3 Related Documents

- 게시판 페이지 Plan: `docs/01-plan/features/qna-board-page.plan.md`
- 게시판 API: `api/index.py:391-545` (board 엔드포인트)
- 게시판 UI: `public/board.html`
- 비식별화 로직: `api/index.py:393-405` (`_anonymize`)

---

## 2. Scope

### 2.1 In Scope

- [ ] FR-01: 글쓰기 모달/폼 UI (닉네임, 비밀번호, 카테고리, 질문 내용)
- [ ] FR-02: 서버 사이드 수학 CAPTCHA (문제 생성 + 검증)
- [ ] FR-03: 비밀번호 해싱 저장 (bcrypt)
- [ ] FR-04: 글 작성 API (`POST /api/board/write`)
- [ ] FR-05: 글 삭제 API (`POST /api/board/{id}/delete`) — 비밀번호 확인 후 삭제
- [ ] FR-06: Supabase `board_posts` 테이블 생성
- [ ] FR-07: 게시판 목록에 사용자 글 통합 표시
- [ ] FR-08: 입력값 검증 및 XSS 방지

### 2.2 Out of Scope

- 회원가입/로그인 (익명 게시판 유지)
- 댓글 기능
- 글 수정 (삭제 후 재작성으로 대체)
- AI 자동 답변 연동 (추후 별도 feature)
- 이미지/파일 첨부
- 외부 CAPTCHA 서비스 (reCAPTCHA, hCaptcha, Turnstile)

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | **글쓰기 폼**: `board.html`에 "질문하기" 버튼 → 모달 팝업. 필드: 닉네임(필수, 2~10자), 비밀번호(필수, 4~20자), 카테고리(선택, 기존 12종), 질문 내용(필수, 10~2000자), 보안문자(필수) | High | Pending |
| FR-02 | **수학 CAPTCHA**: `GET /api/captcha` → `{question: "7 + 3 = ?", token: "encrypted_token"}` 반환. 서버에서 토큰에 정답+만료시간 암호화. 글 작성 시 토큰+사용자 답 전송하여 검증. 유효시간 5분 | High | Pending |
| FR-03 | **비밀번호 해싱**: 서버에서 `bcrypt`로 해싱 후 `board_posts.password_hash`에 저장. 평문 비밀번호는 절대 저장하지 않음 | High | Pending |
| FR-04 | **글 작성 API**: `POST /api/board/write` — body: `{nickname, password, category, question, captcha_token, captcha_answer}`. 성공 시 201 + post ID 반환. Rate limit: IP당 1분에 3건 | High | Pending |
| FR-05 | **글 삭제 API**: `POST /api/board/{id}/delete` — body: `{password}`. bcrypt 비교 후 일치 시 삭제(soft delete). 불일치 시 403 | High | Pending |
| FR-06 | **Supabase 테이블**: `board_posts` — id(uuid), nickname(text), password_hash(text), category(text), question_text(text), status(text: active/deleted), created_at(timestamptz), ip_hash(text) | High | Pending |
| FR-07 | **목록 통합**: 기존 게시판 검색/목록 API에 `board_posts` 데이터도 포함. 사용자 글은 `[질문]` 태그로 구분, AI Q&A는 `[답변완료]` 태그로 구분 | Medium | Pending |
| FR-08 | **입력값 검증**: 서버 사이드 — 닉네임 길이, 질문 길이, 금칙어 필터(욕설/광고). 클라이언트 사이드 — 실시간 글자수 표시, 빈 필드 방지 | High | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| Security | 비밀번호 bcrypt 해싱 (cost factor 12), CAPTCHA 토큰 HMAC 서명, SQL injection 방지 | 코드 리뷰 |
| Security | Rate limiting: IP당 분당 3건 글쓰기 제한 | 서버 로그 |
| Security | XSS 방지: 모든 사용자 입력 escape 처리 | 코드 리뷰 |
| Performance | 글 작성 API 응답 < 1초 (bcrypt 해싱 포함) | 로깅 |
| Privacy | IP 주소 SHA-256 해싱 저장 (원본 IP 미보관), 닉네임 외 개인정보 수집 없음 | 코드 리뷰 |
| Accessibility | 폼 필드 라벨, 에러 메시지 접근성 (aria-describedby) | Lighthouse |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] "질문하기" 버튼 클릭 → 글쓰기 모달 표시
- [ ] 보안문자(수학 문제) 정상 표시 및 검증
- [ ] 글 작성 성공 시 게시판 목록에 즉시 반영
- [ ] 비밀번호 입력 후 본인 글 삭제 가능
- [ ] 잘못된 비밀번호로 삭제 시도 시 거부
- [ ] CAPTCHA 오답 시 글 작성 거부
- [ ] 모바일(375px) 반응형 정상 동작

### 4.2 Quality Criteria

- [ ] 비밀번호 평문 저장 0건 (bcrypt만 사용)
- [ ] XSS 취약점 0건
- [ ] Rate limit 정상 동작 확인

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| 수학 CAPTCHA 우회 (봇이 간단한 수학 풀기) | Medium | Medium | 연산 난이도 조절 (덧셈/뺄셈/곱셈 혼합, 2자리 수). 스팸 급증 시 외부 CAPTCHA로 전환 가능하도록 인터페이스 분리 |
| Vercel 서버리스에서 bcrypt 성능 | Low | Low | cost factor 12는 ~250ms. 1초 타임아웃 내 충분. passlib 또는 bcrypt 라이브러리 사용 |
| Rate limit 우회 (IP 변경) | Medium | Low | IP 해시 기반 제한 + CAPTCHA 이중 방어. 심각 시 글쓰기 일시 비활성화 가능 |
| Supabase 새 테이블 스키마 변경 | Low | Low | `board_posts`는 독립 테이블이므로 기존 `qa_conversations`에 영향 없음 |
| 글쓰기 남용/광고 글 | Medium | Medium | 금칙어 필터 + Rate limit + CAPTCHA 3중 방어. 관리자 대시보드에서 삭제 기능 추가 고려 |

---

## 6. Architecture Considerations

### 6.1 파일 구조

```
api/
└── index.py              ← FR-02,04,05: CAPTCHA + 글쓰기/삭제 API 추가
public/
└── board.html            ← FR-01: 글쓰기 모달 UI 추가
(Supabase)
└── board_posts 테이블    ← FR-06: 신규 테이블
```

### 6.2 Supabase 테이블 설계

```sql
CREATE TABLE board_posts (
  id          UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  nickname    TEXT NOT NULL CHECK (char_length(nickname) BETWEEN 2 AND 10),
  password_hash TEXT NOT NULL,
  category    TEXT DEFAULT '일반상담',
  question_text TEXT NOT NULL CHECK (char_length(question_text) BETWEEN 10 AND 2000),
  status      TEXT DEFAULT 'active' CHECK (status IN ('active', 'deleted')),
  ip_hash     TEXT,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_board_posts_status_created ON board_posts(status, created_at DESC);
CREATE INDEX idx_board_posts_category ON board_posts(category) WHERE status = 'active';
```

### 6.3 CAPTCHA 설계

```
[클라이언트]                         [서버]
    │                                   │
    ├─ GET /api/captcha ───────────────►│
    │                                   ├─ 수학 문제 생성 (예: 15 + 8)
    │                                   ├─ 정답(23) + 만료시간 → HMAC 서명 → token
    │◄── {question:"15 + 8 = ?",       │
    │     token:"hmac_signed_token"} ───┤
    │                                   │
    ├─ POST /api/board/write ──────────►│
    │   {captcha_token, captcha_answer} ├─ token 복호화 → 정답 비교 + 만료 확인
    │                                   ├─ 불일치 → 403
    │                                   ├─ 일치 → 글 저장
    │◄── 201 Created ──────────────────┤
```

- HMAC 키: `ADMIN_JWT_SECRET` 환경변수 재활용 (별도 키 불필요)
- 토큰 구조: `base64(json({answer, expires}))` + `.` + `hmac_sha256(payload, secret)`
- 만료시간: 5분

### 6.4 API 설계

#### `GET /api/captcha`

```json
Response 200:
{
  "question": "15 + 8 = ?",
  "token": "eyJhbnN3ZXIiOjIzLC...signature"
}
```

#### `POST /api/board/write`

```json
Request:
{
  "nickname": "노동자A",
  "password": "1234",
  "category": "임금·수당",
  "question": "주휴수당 계산 방법이 궁금합니다...",
  "captcha_token": "eyJhbnN3ZXIi...",
  "captcha_answer": 23
}

Response 201:
{
  "id": "uuid",
  "message": "질문이 등록되었습니다"
}

Error 400: { "error": "닉네임은 2~10자여야 합니다" }
Error 403: { "error": "보안문자가 올바르지 않습니다" }
Error 429: { "error": "잠시 후 다시 시도해주세요 (1분 제한)" }
```

#### `POST /api/board/{id}/delete`

```json
Request:
{ "password": "1234" }

Response 200: { "message": "삭제되었습니다" }
Error 403:   { "error": "비밀번호가 올바르지 않습니다" }
Error 404:   { "error": "글을 찾을 수 없습니다" }
```

### 6.5 UI 구성 (글쓰기 모달)

```
┌─────────────────────────────────────────────┐
│  ✕                                          │
│                                             │
│  질문하기                                    │
│                                             │
│  닉네임 *                                    │
│  ┌───────────────────────────────────────┐  │
│  │ (2~10자)                              │  │
│  └───────────────────────────────────────┘  │
│                                             │
│  비밀번호 * (삭제 시 필요)                     │
│  ┌───────────────────────────────────────┐  │
│  │ ●●●●                                 │  │
│  └───────────────────────────────────────┘  │
│                                             │
│  카테고리                                    │
│  ┌───────────────────────────────────────┐  │
│  │ 일반상담                          ▾   │  │
│  └───────────────────────────────────────┘  │
│                                             │
│  질문 내용 *                                 │
│  ┌───────────────────────────────────────┐  │
│  │                                       │  │
│  │                                       │  │
│  │                               12/2000 │  │
│  └───────────────────────────────────────┘  │
│                                             │
│  보안문자 *                                  │
│  15 + 8 = ?   [      ] [🔄 새로고침]        │
│                                             │
│  ┌───────────────────────────────────────┐  │
│  │           질문 등록하기                 │  │
│  └───────────────────────────────────────┘  │
│                                             │
└─────────────────────────────────────────────┘
```

---

## 7. Implementation Order

| Phase | Task | 의존성 | 예상 변경량 |
|-------|------|--------|------------|
| 1 | FR-06: Supabase `board_posts` 테이블 생성 (SQL 실행) | 없음 | SQL 1건 |
| 2 | FR-02: CAPTCHA API (`GET /api/captcha`) | 없음 | `api/index.py` +30줄 |
| 3 | FR-03 + FR-04: 글 작성 API (`POST /api/board/write`) + bcrypt | FR-06, FR-02 | `api/index.py` +60줄 |
| 4 | FR-05: 글 삭제 API (`POST /api/board/{id}/delete`) | FR-06 | `api/index.py` +30줄 |
| 5 | FR-01 + FR-08: 글쓰기 모달 UI + 입력값 검증 | FR-02, FR-04 | `board.html` +200줄 |
| 6 | FR-07: 게시판 목록에 사용자 글 통합 | FR-06 | `api/index.py` +40줄, `board.html` +20줄 |

---

## 8. Dependencies

### 8.1 Python 패키지

| 패키지 | 용도 | 현재 상태 |
|--------|------|----------|
| `bcrypt` | 비밀번호 해싱 | 확인 필요 (`requirements.txt`) |
| `hmac` / `hashlib` | CAPTCHA 토큰 서명 | 표준 라이브러리 (추가 불필요) |

### 8.2 환경변수

| 변수 | 용도 | 신규 여부 |
|------|------|----------|
| `ADMIN_JWT_SECRET` | CAPTCHA HMAC 서명 키 | 기존 (재활용) |
| `SUPABASE_URL` / `SUPABASE_KEY` | board_posts 테이블 접근 | 기존 |

---

## 9. Next Steps

1. [ ] Design 문서 작성 (`board-write-security.design.md`)
2. [ ] Supabase 테이블 생성
3. [ ] 백엔드 API 구현 (CAPTCHA → 글쓰기 → 삭제)
4. [ ] 프론트엔드 글쓰기 모달 구현
5. [ ] 통합 테스트

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-19 | Initial draft — 8 FRs defined | Claude |
