# admin-page Planning Document

> **Summary**: Supabase에 저장된 챗봇 Q&A 대화를 조회·관리하고 사용 통계를 시각화하는 관리자 대시보드 페이지 구현
>
> **Project**: laborconsult
> **Author**: zealnutkim
> **Date**: 2026-03-08
> **Status**: Draft

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 챗봇 운영 현황(일별 사용량, 카테고리 분포, 대화 내용)을 확인할 방법이 없어 Supabase 콘솔에 직접 접속해야 하며, 비개발자는 접근 불가 |
| **Solution** | `/admin` 경로에 비밀번호 인증 기반 관리자 페이지를 구현. Supabase REST API로 대화 데이터를 조회하고, 대시보드·대화목록·대화상세 3개 뷰로 구성 |
| **Function/UX Effect** | 한눈에 일별 상담 건수, 카테고리별 분포, 최근 대화 내역 확인 가능. 비개발자도 브라우저에서 운영 현황 파악 |
| **Core Value** | 챗봇 운영 가시성 확보 → 서비스 품질 모니터링, 자주 묻는 질문 파악, 답변 품질 검수 가능 |

---

## 1. Overview

### 1.1 Purpose

Supabase `qa_conversations` 테이블에 저장된 챗봇 대화 데이터를 웹 기반 관리자 페이지에서 조회·검색·통계 분석할 수 있도록 한다. 현재는 Supabase 대시보드에 직접 로그인해야만 데이터를 볼 수 있어, 운영 모니터링이 불편하다.

### 1.2 Background

**현재 상태 (AS-IS)**:
1. 챗봇 Q&A가 Supabase `qa_conversations`에 자동 저장됨 (session_id, category, question_text, answer_text, calculation_types)
2. 데이터 확인 방법: Supabase 콘솔 직접 접속 → SQL 실행
3. 통계/분석: 없음 — 수동으로 SQL 집계해야 함
4. 답변 품질 검수: 불가

**목표 상태 (TO-BE)**:
1. `/admin` 페이지 접속 → 비밀번호 입력 → 대시보드
2. 일별/주별 상담 건수 그래프, 카테고리 분포 차트
3. 대화 목록 (검색, 필터링, 페이지네이션)
4. 대화 상세 보기 (질문 + 답변 + 첨부파일)

### 1.3 Related Documents

- Supabase 스키마: `supabase_schema.sql`
- 저장 로직: `app/core/storage.py`
- API 서버: `api/index.py`
- 프론트엔드: `public/index.html`

---

## 2. Scope

### 2.1 In Scope

- [ ] 관리자 인증 (환경변수 비밀번호 기반, JWT 토큰 발급)
- [ ] 대시보드 뷰 (통계 요약, 일별 추이, 카테고리 분포)
- [ ] 대화 목록 뷰 (검색, 카테고리 필터, 날짜 필터, 페이지네이션)
- [ ] 대화 상세 뷰 (질문·답변 전문, 첨부파일 링크)
- [ ] 관리자 API 엔드포인트 (`/api/admin/*`)
- [ ] 정적 HTML 기반 SPA (public/admin.html)

### 2.2 Out of Scope

- 사용자 계정 관리 (회원가입/로그인 시스템)
- 대화 삭제/수정 기능 (읽기 전용)
- 실시간 대시보드 (WebSocket)
- 모바일 앱
- 답변 품질 평가/피드백 시스템 (추후 확장)

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | 관리자 로그인 — 환경변수 `ADMIN_PASSWORD` 대비 비밀번호 검증, JWT 토큰 발급 | High | Pending |
| FR-02 | 대시보드 — 총 상담 수, 오늘 상담 수, 총 세션 수, 카테고리별 건수 표시 | High | Pending |
| FR-03 | 일별 상담 추이 — 최근 30일간 일별 상담 건수 차트 (Canvas 기반) | Medium | Pending |
| FR-04 | 카테고리 분포 — 카테고리별 비율 시각화 | Medium | Pending |
| FR-05 | 대화 목록 — 최신순 정렬, 20건 단위 페이지네이션 | High | Pending |
| FR-06 | 대화 검색 — 질문/답변 텍스트 내 키워드 검색 | Medium | Pending |
| FR-07 | 대화 필터 — 카테고리별, 날짜 범위별 필터링 | Medium | Pending |
| FR-08 | 대화 상세 — 질문 전문, 답변 전문 (마크다운 렌더링), 메타데이터 표시 | High | Pending |
| FR-09 | 첨부파일 — 대화에 연결된 첨부파일 목록 및 다운로드 링크 | Low | Pending |
| FR-10 | 인증 보호 — 모든 admin API가 JWT 검증 미들웨어를 통과해야 함 | High | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| 보안 | 관리자 비밀번호 환경변수 보관, JWT 만료 24시간 | 코드 검토 |
| 성능 | 대시보드 로딩 < 2초, 대화 목록 < 1초 | 네트워크 탭 확인 |
| 호환성 | 기존 챗봇 API에 영향 없음 | 기존 엔드포인트 테스트 |
| 배포 | Vercel 서버리스 + 정적 파일 서빙 그대로 활용 | vercel.json 설정 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] `/admin` 접속 시 로그인 화면 표시
- [ ] 올바른 비밀번호 입력 시 대시보드 진입
- [ ] 대시보드에 총 상담 수, 카테고리 분포 표시
- [ ] 대화 목록에서 검색·필터링 작동
- [ ] 대화 클릭 시 상세 내용 표시
- [ ] Vercel 배포 정상 작동

### 4.2 Quality Criteria

- [ ] 잘못된 비밀번호로는 API 접근 불가
- [ ] 기존 `/api/chat` 엔드포인트에 영향 없음
- [ ] 모바일 반응형 레이아웃

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Supabase anon key 노출로 데이터 직접 접근 가능 | High | Medium | RLS 정책으로 SELECT만 허용, admin API는 서버사이드에서 service_role key 사용 검토 |
| JWT 토큰 탈취 | Medium | Low | 만료 24시간, HTTPS only, HttpOnly cookie 고려 |
| Vercel Cold Start로 대시보드 느림 | Low | Medium | 통계 쿼리 최적화, 캐시 헤더 활용 |
| 대화 데이터 대량 증가 시 페이지네이션 성능 | Medium | Low | DB 인덱스 활용 (이미 created_at DESC 인덱스 존재) |

---

## 6. Architecture Considerations

### 6.1 기술 스택

| Decision | Options | Selected | Rationale |
|----------|---------|----------|-----------|
| 프론트엔드 | React SPA / Next.js / 정적 HTML | 정적 HTML (public/admin.html) | 기존 index.html과 동일 패턴, 빌드 불필요 |
| 차트 라이브러리 | Chart.js / D3.js / Canvas 직접 | Chart.js (CDN) | 경량, CDN 로딩, 바 차트+파이 차트 충분 |
| 인증 방식 | Supabase Auth / 자체 JWT / Basic Auth | 자체 JWT (PyJWT) | 단일 관리자, 외부 의존 최소화 |
| API | 별도 서버 / 기존 FastAPI 확장 | 기존 FastAPI 확장 | 추가 배포 불필요, Vercel 동일 함수 |
| CSS | Tailwind / 기존 커스텀 CSS | 기존 CSS 변수 확장 | index.html과 일관된 디자인 시스템 |

### 6.2 페이지 구조

```
public/admin.html (정적 SPA)
├── 로그인 화면 (비밀번호 입력)
├── 대시보드 뷰
│   ├── 통계 카드 (총 상담, 오늘 상담, 총 세션, 평균 일일)
│   ├── 일별 상담 추이 (바 차트, 30일)
│   └── 카테고리 분포 (도넛 차트)
├── 대화 목록 뷰
│   ├── 검색바 + 카테고리 필터 + 날짜 필터
│   ├── 대화 카드 리스트 (카테고리 뱃지, 질문 미리보기, 날짜)
│   └── 페이지네이션
└── 대화 상세 뷰 (모달 또는 사이드 패널)
    ├── 질문 전문
    ├── 답변 전문 (마크다운 렌더링)
    ├── 메타데이터 (calculation_types, session_id)
    └── 첨부파일 링크
```

### 6.3 API 엔드포인트

| Method | Path | Description | Auth |
|--------|------|-------------|:----:|
| POST | `/api/admin/login` | 비밀번호 검증 → JWT 반환 | No |
| GET | `/api/admin/stats` | 대시보드 통계 (총 건수, 카테고리, 일별) | Yes |
| GET | `/api/admin/conversations` | 대화 목록 (page, search, category, date_from, date_to) | Yes |
| GET | `/api/admin/conversations/{id}` | 대화 상세 (답변 전문 + 첨부파일) | Yes |

### 6.4 변경 대상 파일

| 파일 | 변경 유형 | 내용 |
|------|----------|------|
| `public/admin.html` | 신규 | 관리자 대시보드 SPA |
| `api/index.py` | 수정 | admin API 엔드포인트 4개 추가 |
| `.env.example` | 수정 | `ADMIN_PASSWORD` 추가 |
| `requirements.txt` | 수정 | `PyJWT` 추가 |
| `vercel.json` | 확인 | rewrite 규칙이 `/api/admin/*` 커버하는지 확인 (기존 `/api/(.*)` 패턴이면 OK) |

### 6.5 데이터 흐름

```
[admin.html]
  ↓ POST /api/admin/login {password}
[api/index.py]
  ↓ ADMIN_PASSWORD 검증 → JWT 토큰 반환
[admin.html]
  ↓ GET /api/admin/stats (Authorization: Bearer <token>)
[api/index.py]
  ↓ JWT 검증 → Supabase 조회
  ↓ SELECT count(*), category 집계
  ↓ 통계 JSON 반환
[admin.html]
  ↓ Chart.js 렌더링
```

---

## 7. 환경변수

| Variable | Purpose | Scope | To Be Created |
|----------|---------|-------|:-------------:|
| `ADMIN_PASSWORD` | 관리자 로그인 비밀번호 | Server | Yes |
| `ADMIN_JWT_SECRET` | JWT 서명 비밀키 (없으면 ADMIN_PASSWORD 해시 사용) | Server | Optional |
| `SUPABASE_URL` | Supabase 프로젝트 URL | Server | 기존 |
| `SUPABASE_KEY` | Supabase anon key | Server | 기존 |

---

## 8. Next Steps

1. [ ] Design 문서 작성 (`admin-page.design.md`)
2. [ ] 구현: API 엔드포인트 → 관리자 HTML → 테스트
3. [ ] Vercel 환경변수 `ADMIN_PASSWORD` 설정
4. [ ] 배포 및 동작 확인

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-08 | Initial draft | zealnutkim |
