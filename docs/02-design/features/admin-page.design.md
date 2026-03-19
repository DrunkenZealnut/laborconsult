# admin-page Design Document

> **Summary**: 챗봇 Q&A 관리자 대시보드 — 인증, 통계 API, 대화 조회 UI 상세 설계
>
> **Project**: laborconsult
> **Author**: zealnutkim
> **Date**: 2026-03-08
> **Status**: Draft
> **Planning Doc**: [admin-page.plan.md](../../01-plan/features/admin-page.plan.md)

---

## 1. Overview

### 1.1 Design Goals

1. 기존 FastAPI 앱(`api/index.py`)에 admin 엔드포인트를 추가하여 별도 배포 없이 관리자 기능 제공
2. `public/admin.html` 단일 파일 SPA로 빌드 도구 없이 즉시 사용
3. JWT 기반 인증으로 관리자 외 접근 차단
4. 기존 챗봇 기능에 영향 zero

### 1.2 Design Principles

- **Minimal Footprint**: 파일 2개 수정(api/index.py, requirements.txt) + 1개 신규(admin.html)
- **Consistent UI**: 기존 index.html CSS 변수(--primary, --bg, --card 등) 재사용
- **Server-side Only**: 모든 데이터 조회는 서버에서 Supabase 쿼리 → 클라이언트에 anon key 노출 안 함
- **Read-Only**: 관리자 페이지는 조회 전용, 데이터 수정/삭제 불가

---

## 2. Architecture

### 2.1 Component Diagram

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────┐
│  admin.html     │────▶│  api/index.py    │────▶│  Supabase   │
│  (Browser SPA)  │     │  FastAPI         │     │  PostgreSQL │
│  + Chart.js CDN │◀────│  + JWT Auth      │◀────│  + Storage  │
└─────────────────┘     └──────────────────┘     └─────────────┘
```

### 2.2 Data Flow

```
[로그인]
admin.html → POST /api/admin/login {password}
           ← {token: "jwt..."}

[대시보드]
admin.html → GET /api/admin/stats (Bearer token)
           ← {total, today, sessions, daily_counts[], category_counts[]}

[대화 목록]
admin.html → GET /api/admin/conversations?page=1&search=퇴직금&category=퇴직금 (Bearer token)
           ← {conversations: [...], total: 150, page: 1, pages: 8}

[대화 상세]
admin.html → GET /api/admin/conversations/{id} (Bearer token)
           ← {id, question_text, answer_text, category, calculation_types, attachments[], created_at}
```

### 2.3 Dependencies

| Component | Depends On | Purpose |
|-----------|-----------|---------|
| admin API | `PyJWT` (신규) | JWT 토큰 생성/검증 |
| admin API | `app.config.AppConfig.supabase` (기존) | Supabase 클라이언트 |
| admin.html | Chart.js 4.x (CDN) | 차트 렌더링 |
| admin.html | 기존 `md()` 함수 로직 | 답변 마크다운 렌더링 |

---

## 3. Data Model

### 3.1 기존 테이블 (변경 없음)

```sql
-- qa_sessions: 세션 관리
qa_sessions(id UUID PK, created_at, updated_at)

-- qa_conversations: 대화 저장 (핵심 조회 대상)
qa_conversations(id UUID PK, session_id FK, category TEXT,
                 question_text TEXT, answer_text TEXT,
                 calculation_types TEXT[], metadata JSONB,
                 created_at TIMESTAMPTZ)

-- qa_attachments: 첨부파일
qa_attachments(id UUID PK, conversation_id FK, filename TEXT,
               content_type TEXT, storage_path TEXT, public_url TEXT,
               file_size INTEGER, created_at TIMESTAMPTZ)
```

### 3.2 Entity Relationships

```
[qa_sessions] 1 ──── N [qa_conversations] 1 ──── N [qa_attachments]
```

### 3.3 신규 DB 변경: 없음

기존 스키마를 그대로 활용. 신규 테이블/컬럼 불필요.

---

## 4. API Specification

### 4.1 Endpoint List

| Method | Path | Description | Auth |
|--------|------|-------------|:----:|
| POST | `/api/admin/login` | 비밀번호 검증 → JWT 반환 | No |
| GET | `/api/admin/stats` | 대시보드 통계 | Yes |
| GET | `/api/admin/conversations` | 대화 목록 (페이지네이션, 검색, 필터) | Yes |
| GET | `/api/admin/conversations/{id}` | 대화 상세 + 첨부파일 | Yes |

### 4.2 Detailed Specification

#### `POST /api/admin/login`

**Request:**
```json
{
  "password": "string"
}
```

**Response (200 OK):**
```json
{
  "token": "eyJhbGciOiJIUzI1NiIs...",
  "expires_in": 86400
}
```

**Error (401):**
```json
{
  "detail": "비밀번호가 올바르지 않습니다"
}
```

**구현 로직:**
```python
import os, jwt, time

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
JWT_SECRET = os.environ.get("ADMIN_JWT_SECRET", ADMIN_PASSWORD)
JWT_EXPIRY = 86400  # 24시간

@app.post("/api/admin/login")
def admin_login(body: AdminLoginRequest):
    if not ADMIN_PASSWORD:
        raise HTTPException(503, "관리자 기능이 설정되지 않았습니다")
    if body.password != ADMIN_PASSWORD:
        raise HTTPException(401, "비밀번호가 올바르지 않습니다")
    token = jwt.encode(
        {"exp": int(time.time()) + JWT_EXPIRY, "role": "admin"},
        JWT_SECRET, algorithm="HS256"
    )
    return {"token": token, "expires_in": JWT_EXPIRY}
```

---

#### `GET /api/admin/stats`

**Response (200):**
```json
{
  "total_conversations": 1523,
  "today_conversations": 47,
  "total_sessions": 892,
  "daily_counts": [
    {"date": "2026-03-08", "count": 47},
    {"date": "2026-03-07", "count": 52},
    ...
  ],
  "category_counts": [
    {"category": "임금·수당", "count": 423},
    {"category": "퇴직금", "count": 312},
    ...
  ]
}
```

**Supabase 쿼리:**
```python
# 총 건수
total = sb.table("qa_conversations").select("id", count="exact").execute()

# 오늘 건수
today_str = date.today().isoformat()
today = sb.table("qa_conversations").select("id", count="exact") \
    .gte("created_at", today_str).execute()

# 총 세션
sessions = sb.table("qa_sessions").select("id", count="exact").execute()

# 일별 (최근 30일) — RPC 함수 또는 클라이언트 집계
recent = sb.table("qa_conversations") \
    .select("created_at") \
    .gte("created_at", (date.today() - timedelta(days=30)).isoformat()) \
    .order("created_at", desc=True) \
    .execute()
# → Python에서 날짜별 groupby

# 카테고리별
cats = sb.table("qa_conversations") \
    .select("category") \
    .execute()
# → Python에서 Counter 집계
```

---

#### `GET /api/admin/conversations`

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `page` | int | 1 | 페이지 번호 |
| `per_page` | int | 20 | 페이지당 건수 (max 100) |
| `search` | str | "" | 질문/답변 텍스트 검색 (ilike) |
| `category` | str | "" | 카테고리 필터 |
| `date_from` | str | "" | 시작일 (YYYY-MM-DD) |
| `date_to` | str | "" | 종료일 (YYYY-MM-DD) |

**Response (200):**
```json
{
  "conversations": [
    {
      "id": "uuid",
      "category": "퇴직금",
      "question_text": "월급 250만원 3년 근무...",
      "answer_preview": "퇴직금은 약 750만원으로...",
      "calculation_types": ["severance"],
      "created_at": "2026-03-08T14:30:00Z"
    }
  ],
  "total": 150,
  "page": 1,
  "per_page": 20,
  "pages": 8
}
```

**구현 로직:**
```python
@app.get("/api/admin/conversations")
def admin_conversations(
    page: int = 1,
    per_page: int = 20,
    search: str = "",
    category: str = "",
    date_from: str = "",
    date_to: str = "",
    _admin=Depends(require_admin),
):
    per_page = min(per_page, 100)
    offset = (page - 1) * per_page

    query = sb.table("qa_conversations") \
        .select("id, category, question_text, answer_text, calculation_types, created_at",
                count="exact")

    if search:
        query = query.or_(f"question_text.ilike.%{search}%,answer_text.ilike.%{search}%")
    if category:
        query = query.eq("category", category)
    if date_from:
        query = query.gte("created_at", date_from)
    if date_to:
        query = query.lte("created_at", date_to + "T23:59:59Z")

    result = query.order("created_at", desc=True) \
        .range(offset, offset + per_page - 1) \
        .execute()

    conversations = []
    for row in result.data:
        conversations.append({
            **row,
            "answer_preview": (row.get("answer_text") or "")[:100] + "...",
        })
        # answer_text 전문은 목록에서 제외 (상세에서만)
        if "answer_text" in conversations[-1]:
            del conversations[-1]["answer_text"]

    total = result.count or 0
    return {
        "conversations": conversations,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }
```

---

#### `GET /api/admin/conversations/{conv_id}`

**Response (200):**
```json
{
  "id": "uuid",
  "session_id": "uuid",
  "category": "퇴직금",
  "question_text": "월급 250만원으로 3년 근무했는데 퇴직금은 얼마인가요?",
  "answer_text": "## 퇴직금 계산 결과\n\n...(full markdown)...",
  "calculation_types": ["severance"],
  "metadata": {},
  "created_at": "2026-03-08T14:30:00Z",
  "attachments": [
    {
      "filename": "급여명세서.pdf",
      "content_type": "application/pdf",
      "public_url": "https://...",
      "file_size": 245000
    }
  ]
}
```

**구현 로직:**
```python
@app.get("/api/admin/conversations/{conv_id}")
def admin_conversation_detail(conv_id: str, _admin=Depends(require_admin)):
    result = sb.table("qa_conversations") \
        .select("*") \
        .eq("id", conv_id) \
        .single() \
        .execute()

    if not result.data:
        raise HTTPException(404, "대화를 찾을 수 없습니다")

    # 첨부파일 조회
    attachments = sb.table("qa_attachments") \
        .select("filename, content_type, public_url, file_size") \
        .eq("conversation_id", conv_id) \
        .execute()

    return {**result.data, "attachments": attachments.data or []}
```

---

### 4.3 JWT 인증 미들웨어

```python
from fastapi import Depends, HTTPException, Header

def require_admin(authorization: str = Header(None)):
    """JWT Bearer 토큰 검증 미들웨어"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "인증이 필요합니다")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        if payload.get("role") != "admin":
            raise HTTPException(403, "관리자 권한이 필요합니다")
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "토큰이 만료되었습니다")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "유효하지 않은 토큰입니다")
    return payload
```

---

## 5. UI/UX Design

### 5.1 Screen Layout — 로그인

```
┌────────────────────────────────────────┐
│              AI 노동상담 관리자          │
├────────────────────────────────────────┤
│                                        │
│         ┌──────────────────┐           │
│         │  🔒 관리자 로그인  │           │
│         │                  │           │
│         │  [비밀번호 입력]   │           │
│         │  [   로그인   ]   │           │
│         └──────────────────┘           │
│                                        │
└────────────────────────────────────────┘
```

### 5.2 Screen Layout — 대시보드

```
┌────────────────────────────────────────────────────┐
│  AI 노동상담 관리자    [대시보드] [대화목록] [로그아웃] │
├────────────────────────────────────────────────────┤
│                                                    │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐              │
│  │ 총   │ │ 오늘 │ │ 세션 │ │ 일평균│              │
│  │ 1523 │ │  47  │ │ 892  │ │  51  │              │
│  └──────┘ └──────┘ └──────┘ └──────┘              │
│                                                    │
│  ┌──────────────────────┐ ┌──────────────────────┐ │
│  │  일별 상담 추이 (30일) │ │  카테고리 분포        │ │
│  │  ██ ██ ██ ██ ██ ██  │ │      ◉ 임금·수당 28%  │ │
│  │  ██ ██ ██ ██ ██ ██  │ │      ◉ 퇴직금    20%  │ │
│  │  ██ ██ ██ ██ ██ ██  │ │      ◉ 해고      15%  │ │
│  └──────────────────────┘ └──────────────────────┘ │
│                                                    │
└────────────────────────────────────────────────────┘
```

### 5.3 Screen Layout — 대화 목록

```
┌────────────────────────────────────────────────────┐
│  AI 노동상담 관리자    [대시보드] [대화목록] [로그아웃] │
├────────────────────────────────────────────────────┤
│                                                    │
│  [🔍 키워드 검색    ] [카테고리 ▾] [날짜 ▾]          │
│                                                    │
│  ┌──────────────────────────────────────────────┐  │
│  │ 퇴직금  월급 250만원 3년 근무 퇴직금은?       │  │
│  │         2026-03-08 14:30                     │  │
│  ├──────────────────────────────────────────────┤  │
│  │ 임금·수당  시급 15000원 주 4일 주휴수당은?     │  │
│  │           2026-03-08 13:15                   │  │
│  ├──────────────────────────────────────────────┤  │
│  │ 실업급여  계약만료로 퇴사 실업급여 받을 수...  │  │
│  │          2026-03-08 12:00                    │  │
│  └──────────────────────────────────────────────┘  │
│                                                    │
│  [◀ 이전] 1 / 8 페이지 [다음 ▶]                     │
│                                                    │
└────────────────────────────────────────────────────┘
```

### 5.4 Screen Layout — 대화 상세 (모달)

```
┌──────────────────────────────────────────┐
│  대화 상세                          [✕]  │
├──────────────────────────────────────────┤
│  카테고리: 퇴직금                         │
│  시간: 2026-03-08 14:30                  │
│  유형: severance                         │
│  세션: abc123...                         │
├──────────────────────────────────────────┤
│  💬 질문                                 │
│  월급 250만원으로 3년 근무했는데          │
│  퇴직금은 얼마인가요?                     │
├──────────────────────────────────────────┤
│  🤖 답변                                 │
│  ## 퇴직금 계산 결과                      │
│  | 항목 | 금액 |                          │
│  |------|------|                          │
│  | 퇴직금 | 7,500,000원 |                │
│  ...                                     │
├──────────────────────────────────────────┤
│  📎 첨부파일                             │
│  급여명세서.pdf (239KB) [다운로드]         │
└──────────────────────────────────────────┘
```

### 5.5 User Flow

```
/admin 접속
  ↓
로그인 화면 (비밀번호 입력)
  ↓ POST /api/admin/login
  ↓ token → localStorage 저장
대시보드 뷰
  ├── GET /api/admin/stats → 통계 카드 + 차트 렌더링
  └── [대화목록] 클릭
      ↓
대화 목록 뷰
  ├── GET /api/admin/conversations → 목록 렌더링
  ├── 검색/필터 → 재조회
  └── 대화 행 클릭
      ↓
대화 상세 모달
  └── GET /api/admin/conversations/{id} → 전문 + 첨부 렌더링
```

---

## 6. Error Handling

### 6.1 Error Code Definition

| Code | Message | Cause | Handling |
|------|---------|-------|----------|
| 401 | 비밀번호가 올바르지 않습니다 | 로그인 실패 | 에러 메시지 표시 |
| 401 | 인증이 필요합니다 | 토큰 없음 | 로그인 화면으로 리다이렉트 |
| 401 | 토큰이 만료되었습니다 | JWT 만료 | 로그인 화면으로 리다이렉트 |
| 404 | 대화를 찾을 수 없습니다 | 잘못된 conversation_id | 목록으로 복귀 |
| 503 | 관리자 기능이 설정되지 않았습니다 | ADMIN_PASSWORD 미설정 | 안내 메시지 |

### 6.2 프론트엔드 에러 처리

```javascript
async function adminFetch(url) {
    const token = localStorage.getItem('admin_token');
    const resp = await fetch(url, {
        headers: token ? { 'Authorization': 'Bearer ' + token } : {}
    });
    if (resp.status === 401) {
        localStorage.removeItem('admin_token');
        showLogin();
        return null;
    }
    if (!resp.ok) {
        const err = await resp.json();
        alert(err.detail || '오류가 발생했습니다');
        return null;
    }
    return resp.json();
}
```

---

## 7. Security Considerations

- [x] `ADMIN_PASSWORD` 환경변수에만 보관 (코드에 하드코딩 없음)
- [x] JWT HS256 서명, 만료 24시간
- [x] 모든 admin API에 `require_admin` 의존성 주입
- [x] Supabase anon key는 서버사이드에서만 사용 (클라이언트 노출 없음)
- [x] XSS 방지: 답변 마크다운 렌더링 시 HTML escape 후 변환
- [x] `ADMIN_PASSWORD` 미설정 시 admin 기능 자체 비활성화 (503 반환)
- [ ] Rate limiting은 Vercel Edge 레벨에서 처리 (향후)

---

## 8. Test Plan

### 8.1 Test Scope

| Type | Target | Method |
|------|--------|--------|
| API 테스트 | admin 4개 엔드포인트 | curl / httpie 수동 테스트 |
| 인증 테스트 | JWT 발급/검증/만료 | 잘못된 비밀번호, 만료 토큰, 토큰 없음 |
| UI 테스트 | 대시보드/목록/상세 렌더링 | 브라우저 수동 확인 |

### 8.2 Test Cases

- [ ] 올바른 비밀번호로 로그인 → JWT 반환
- [ ] 잘못된 비밀번호 → 401 에러
- [ ] 토큰 없이 /api/admin/stats → 401
- [ ] 만료된 토큰 → 401
- [ ] /api/admin/stats → 통계 JSON 반환
- [ ] /api/admin/conversations?search=퇴직금 → 필터된 목록
- [ ] /api/admin/conversations/{id} → 상세 + 첨부파일
- [ ] 기존 /api/chat, /api/chat/stream → 영향 없음 확인
- [ ] ADMIN_PASSWORD 미설정 시 → 503

---

## 9. Implementation Guide

### 9.1 File Structure

```
변경 파일:
├── api/index.py          # admin 엔드포인트 4개 + JWT 미들웨어 추가
├── requirements.txt      # PyJWT 추가
├── .env.example          # ADMIN_PASSWORD 추가
│
신규 파일:
├── public/admin.html     # 관리자 대시보드 SPA (단일 파일)
```

### 9.2 Implementation Order

1. [ ] **Step 1**: `requirements.txt`에 `PyJWT` 추가
2. [ ] **Step 2**: `api/index.py`에 JWT 인증 함수 + 4개 admin 엔드포인트 추가
   - `AdminLoginRequest` Pydantic 모델
   - `require_admin()` 의존성
   - `POST /api/admin/login`
   - `GET /api/admin/stats`
   - `GET /api/admin/conversations`
   - `GET /api/admin/conversations/{conv_id}`
3. [ ] **Step 3**: `public/admin.html` 작성
   - 로그인 뷰
   - 대시보드 뷰 (Chart.js)
   - 대화 목록 뷰
   - 대화 상세 모달
   - 마크다운 렌더링 (index.html `md()` 함수 재사용)
4. [ ] **Step 4**: `.env.example`에 `ADMIN_PASSWORD` 추가
5. [ ] **Step 5**: 로컬 테스트 (`uvicorn api.index:app --reload`)
6. [ ] **Step 6**: Vercel 배포 + 환경변수 설정

### 9.3 핵심 구현 주의사항

| 항목 | 주의사항 |
|------|---------|
| JWT Secret | `ADMIN_JWT_SECRET` 없으면 `ADMIN_PASSWORD` 자체를 secret으로 사용 |
| Supabase 없음 시 | `config.supabase`가 None이면 admin API 503 반환 |
| 페이지네이션 | Supabase `.range(offset, offset + per_page - 1)` 사용 (0-based) |
| 검색 | `.or_("question_text.ilike.%keyword%,answer_text.ilike.%keyword%")` |
| 일별 집계 | Supabase RPC 없이 Python `Counter` + `date.fromisoformat()` 사용 |
| 마크다운 | admin.html에 `md()` 함수 복사 (index.html과 동일) |
| Chart.js | CDN `https://cdn.jsdelivr.net/npm/chart.js@4` 사용 |
| `/admin` 라우팅 | Vercel `public/admin.html` 자동 서빙 (`/admin` → `public/admin.html`) |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-08 | Initial draft | zealnutkim |
