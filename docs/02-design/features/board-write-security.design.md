# 게시판 글쓰기 — 비밀번호 + 보안문자 Design Document

> **Summary**: 질문게시판에 익명 글쓰기 기능 추가 — 수학 CAPTCHA + bcrypt 비밀번호 해싱 + Rate Limit
>
> **Project**: laborconsult
> **Author**: Claude
> **Date**: 2026-03-19
> **Status**: Draft
> **Planning Doc**: [board-write-security.plan.md](../../01-plan/features/board-write-security.plan.md)

---

## 1. Overview

### 1.1 Design Goals

1. **스팸 방지**: 서버 사이드 수학 CAPTCHA로 봇 자동 글쓰기 차단
2. **비밀번호 보안**: bcrypt 해싱으로 평문 비밀번호 미저장
3. **기존 시스템과의 공존**: `board_posts` 테이블을 `qa_conversations`와 분리하여 기존 기능에 영향 없음
4. **최소 의존성**: 외부 CAPTCHA 서비스 없이 표준 라이브러리 + bcrypt만 사용

### 1.2 Design Principles

- **보안 우선**: 모든 사용자 입력을 서버에서 검증, 비밀번호 해싱 필수
- **단순성**: 로그인/회원가입 없이 비밀번호만으로 글 관리
- **기존 패턴 준수**: `api/index.py`의 기존 board 엔드포인트 스타일 유지
- **Graceful Degradation**: CAPTCHA 또는 Rate Limit 실패 시에도 명확한 에러 메시지 반환

---

## 2. Architecture

### 2.1 Component Diagram

```
┌──────────────────┐     ┌──────────────────────────────┐     ┌─────────────┐
│  board.html      │     │  api/index.py                │     │  Supabase   │
│  (글쓰기 모달)    │────▶│  GET  /api/captcha           │     │             │
│                  │     │  POST /api/board/write        │────▶│ board_posts │
│                  │     │  POST /api/board/{id}/delete  │     │             │
└──────────────────┘     └──────────────────────────────┘     └─────────────┘
                                    │
                           ┌────────┴────────┐
                           │  CAPTCHA 검증    │
                           │  bcrypt 해싱     │
                           │  Rate Limit      │
                           │  입력값 검증      │
                           └─────────────────┘
```

### 2.2 Data Flow

#### 글 작성 흐름

```
[사용자]                      [board.html]                    [api/index.py]                [Supabase]
   │                              │                               │                            │
   ├─ "질문하기" 클릭 ───────────►│                               │                            │
   │                              ├─ GET /api/captcha ───────────►│                            │
   │                              │◄── {question, token} ────────┤                            │
   │                              │                               │                            │
   │◄── 모달 표시 (폼+CAPTCHA) ──┤                               │                            │
   │                              │                               │                            │
   ├─ 폼 작성 + 제출 ───────────►│                               │                            │
   │                              ├─ POST /api/board/write ──────►│                            │
   │                              │                               ├─ CAPTCHA 토큰 검증          │
   │                              │                               ├─ Rate Limit 확인            │
   │                              │                               ├─ 입력값 검증                │
   │                              │                               ├─ bcrypt 해싱               │
   │                              │                               ├─ INSERT board_posts ──────►│
   │                              │◄── 201 {id, message} ────────┤                            │
   │◄── 성공 메시지 + 목록 갱신 ──┤                               │                            │
```

#### 글 삭제 흐름

```
[사용자]                      [board.html]                    [api/index.py]                [Supabase]
   │                              │                               │                            │
   ├─ "삭제" 클릭 ──────────────►│                               │                            │
   │◄── 비밀번호 입력 프롬프트 ──┤                               │                            │
   ├─ 비밀번호 입력 ────────────►│                               │                            │
   │                              ├─ POST /api/board/{id}/delete ►│                            │
   │                              │                               ├─ 글 조회 ─────────────────►│
   │                              │                               │◄── row (password_hash) ────┤
   │                              │                               ├─ bcrypt.checkpw()           │
   │                              │                               ├─ UPDATE status='deleted' ──►│
   │                              │◄── 200 {message} ────────────┤                            │
   │◄── 삭제 완료 + 목록 갱신 ──┤                               │                            │
```

### 2.3 Dependencies

| Component | Depends On | Purpose |
|-----------|-----------|---------|
| CAPTCHA API | `ADMIN_JWT_SECRET` (env var) | HMAC 서명 키 |
| 글 작성 API | Supabase, bcrypt, CAPTCHA | 저장 + 해싱 + 검증 |
| 글 삭제 API | Supabase, bcrypt | 비밀번호 확인 + soft delete |
| 글쓰기 모달 | CAPTCHA API, 글 작성 API | UI + API 연동 |

---

## 3. Data Model

### 3.1 Entity Definition

```python
# board_posts 테이블 레코드
{
    "id": "uuid",              # PK, auto-generated
    "nickname": "str",         # 2~10자, 필수
    "password_hash": "str",    # bcrypt 해시, 필수
    "category": "str",         # 카테고리 (기본값: '일반상담')
    "question_text": "str",    # 질문 내용, 10~2000자
    "status": "str",           # 'active' | 'deleted'
    "ip_hash": "str",          # SHA-256(IP), Rate Limit 용
    "created_at": "datetime",  # auto
}
```

### 3.2 Entity Relationships

```
[qa_conversations]  ← 기존 AI Q&A (읽기 전용 표시)
        │
  (게시판 목록에서 통합 표시)
        │
[board_posts]       ← 신규 사용자 질문 (글쓰기/삭제)
```

- `board_posts`는 `qa_conversations`와 독립적. FK 없음.
- 게시판 목록 API에서 두 테이블을 UNION하여 통합 표시.

### 3.3 Database Schema

```sql
-- Supabase에서 실행
CREATE TABLE board_posts (
    id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    nickname      TEXT NOT NULL
                    CHECK (char_length(nickname) BETWEEN 2 AND 10),
    password_hash TEXT NOT NULL,
    category      TEXT DEFAULT '일반상담',
    question_text TEXT NOT NULL
                    CHECK (char_length(question_text) BETWEEN 10 AND 2000),
    status        TEXT DEFAULT 'active'
                    CHECK (status IN ('active', 'deleted')),
    ip_hash       TEXT,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- 인덱스
CREATE INDEX idx_board_posts_active_created
    ON board_posts (created_at DESC)
    WHERE status = 'active';

CREATE INDEX idx_board_posts_category
    ON board_posts (category)
    WHERE status = 'active';

CREATE INDEX idx_board_posts_ip_hash
    ON board_posts (ip_hash, created_at DESC);
```

---

## 4. API Specification

### 4.1 Endpoint List

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/api/captcha` | 수학 CAPTCHA 문제 + 서명 토큰 발급 | None |
| POST | `/api/board/write` | 글 작성 (CAPTCHA + 비밀번호) | None (CAPTCHA) |
| POST | `/api/board/{id}/delete` | 글 삭제 (비밀번호 확인) | Password |

### 4.2 Detailed Specification

#### `GET /api/captcha`

수학 문제를 생성하고 정답을 HMAC 서명 토큰으로 반환한다.

**Response (200):**
```json
{
    "question": "15 + 8 = ?",
    "token": "eyJhIjoyMywiZSI6MTc....<hmac_signature>"
}
```

**토큰 구조:**
```python
payload = base64url(json.dumps({"a": answer, "e": expires_unix}))
signature = hmac_sha256(payload, JWT_SECRET)
token = f"{payload}.{signature}"
```

**구현 상세:**
```python
import hmac, hashlib, json, base64, time, random

def _generate_captcha():
    """수학 CAPTCHA 생성 → (question_text, token)"""
    ops = [
        ('+', lambda a, b: a + b),
        ('-', lambda a, b: a - b),
        ('×', lambda a, b: a * b),
    ]
    op_symbol, op_func = random.choice(ops)

    if op_symbol == '×':
        a, b = random.randint(2, 9), random.randint(2, 9)
    elif op_symbol == '-':
        a = random.randint(10, 50)
        b = random.randint(1, a)  # 음수 방지
    else:
        a, b = random.randint(10, 50), random.randint(1, 30)

    answer = op_func(a, b)
    question = f"{a} {op_symbol} {b} = ?"

    expires = int(time.time()) + 300  # 5분
    payload = base64.urlsafe_b64encode(
        json.dumps({"a": answer, "e": expires}).encode()
    ).decode().rstrip("=")
    sig = hmac.new(
        JWT_SECRET.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()

    return question, f"{payload}.{sig}"


def _verify_captcha(token: str, user_answer: int) -> bool:
    """CAPTCHA 토큰 검증 → True/False"""
    try:
        payload_b64, sig = token.rsplit(".", 1)
        expected_sig = hmac.new(
            JWT_SECRET.encode(), payload_b64.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return False

        # base64 패딩 복원
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded))

        if time.time() > data["e"]:
            return False  # 만료
        return int(user_answer) == int(data["a"])
    except Exception:
        return False
```

---

#### `POST /api/board/write`

**Request Body:**
```json
{
    "nickname": "노동자A",
    "password": "mypass123",
    "category": "임금·수당",
    "question": "주휴수당 계산 방법이 궁금합니다. 주 15시간 이상 근무하면...",
    "captcha_token": "eyJhIjoyMyw...",
    "captcha_answer": 23
}
```

**Pydantic 모델:**
```python
class BoardWriteRequest(BaseModel):
    nickname: str       # 2~10자
    password: str       # 4~20자
    category: str = "일반상담"
    question: str       # 10~2000자
    captcha_token: str
    captcha_answer: int
```

**처리 순서:**
1. CAPTCHA 토큰 검증 (`_verify_captcha`)
2. Rate Limit 확인 (IP 해시 기반, 1분 3건)
3. 입력값 검증 (길이, 금칙어)
4. 비밀번호 bcrypt 해싱
5. Supabase `board_posts` INSERT
6. 응답 반환

**Response (201):**
```json
{
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "message": "질문이 등록되었습니다"
}
```

**Error Responses:**

| Code | Condition | Body |
|------|-----------|------|
| 400 | 입력값 검증 실패 | `{"error": "닉네임은 2~10자여야 합니다"}` |
| 400 | 금칙어 포함 | `{"error": "부적절한 내용이 포함되어 있습니다"}` |
| 403 | CAPTCHA 실패 | `{"error": "보안문자가 올바르지 않습니다"}` |
| 429 | Rate Limit 초과 | `{"error": "잠시 후 다시 시도해주세요"}` |

**구현 상세:**
```python
import bcrypt, hashlib

# Rate Limit — 인메모리 (Vercel 서버리스: 인스턴스당)
_write_rate: dict[str, list[float]] = {}

def _check_rate_limit(ip: str, max_count: int = 3, window: int = 60) -> bool:
    """IP당 window초 내 max_count건 초과 시 False"""
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]
    now = time.time()
    times = _write_rate.get(ip_hash, [])
    times = [t for t in times if now - t < window]
    if len(times) >= max_count:
        return False
    times.append(now)
    _write_rate[ip_hash] = times
    return True

# 금칙어 필터
_BAD_WORDS = re.compile(
    r'(시발|씨발|개새끼|병신|https?://\S+|bit\.ly|광고|홍보|대출|카지노)',
    re.IGNORECASE
)

@app.post("/api/board/write")
def board_write(body: BoardWriteRequest, request: Request):
    # 1. CAPTCHA
    if not _verify_captcha(body.captcha_token, body.captcha_answer):
        return JSONResponse(status_code=403,
            content={"error": "보안문자가 올바르지 않습니다"})

    # 2. Rate Limit
    client_ip = request.headers.get("x-forwarded-for", request.client.host or "")
    if not _check_rate_limit(client_ip):
        return JSONResponse(status_code=429,
            content={"error": "잠시 후 다시 시도해주세요"})

    # 3. 입력값 검증
    nickname = body.nickname.strip()
    question = body.question.strip()
    if not (2 <= len(nickname) <= 10):
        return JSONResponse(status_code=400,
            content={"error": "닉네임은 2~10자여야 합니다"})
    if not (4 <= len(body.password) <= 20):
        return JSONResponse(status_code=400,
            content={"error": "비밀번호는 4~20자여야 합니다"})
    if not (10 <= len(question) <= 2000):
        return JSONResponse(status_code=400,
            content={"error": "질문은 10~2000자여야 합니다"})
    if _BAD_WORDS.search(nickname + question):
        return JSONResponse(status_code=400,
            content={"error": "부적절한 내용이 포함되어 있습니다"})

    # 4. bcrypt 해싱
    pw_hash = bcrypt.hashpw(
        body.password.encode("utf-8"), bcrypt.gensalt(rounds=12)
    ).decode("utf-8")

    # 5. Supabase INSERT
    ip_hash = hashlib.sha256(client_ip.encode()).hexdigest()[:16]
    sb = _get_supabase()
    result = sb.table("board_posts").insert({
        "nickname": nickname,
        "password_hash": pw_hash,
        "category": body.category or "일반상담",
        "question_text": question,
        "ip_hash": ip_hash,
    }).execute()

    post_id = result.data[0]["id"] if result.data else None
    return JSONResponse(status_code=201,
        content={"id": post_id, "message": "질문이 등록되었습니다"})
```

---

#### `POST /api/board/{id}/delete`

**Request Body:**
```json
{
    "password": "mypass123"
}
```

**Pydantic 모델:**
```python
class BoardDeleteRequest(BaseModel):
    password: str
```

**처리 순서:**
1. UUID 형식 검증
2. `board_posts`에서 해당 글 조회 (status='active')
3. `bcrypt.checkpw()` 비밀번호 비교
4. 일치 시 `status = 'deleted'` 업데이트 (soft delete)

**Response (200):**
```json
{ "message": "삭제되었습니다" }
```

**Error Responses:**

| Code | Condition | Body |
|------|-----------|------|
| 400 | 잘못된 ID 형식 | `{"error": "Invalid ID"}` |
| 403 | 비밀번호 불일치 | `{"error": "비밀번호가 올바르지 않습니다"}` |
| 404 | 글 없음/이미 삭제 | `{"error": "글을 찾을 수 없습니다"}` |

**구현 상세:**
```python
@app.post("/api/board/{post_id}/delete")
def board_post_delete(post_id: str, body: BoardDeleteRequest):
    import uuid as _uuid
    try:
        _uuid.UUID(post_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "Invalid ID"})

    sb = _get_supabase()
    result = (
        sb.table("board_posts")
        .select("id, password_hash")
        .eq("id", post_id)
        .eq("status", "active")
        .maybe_single()
        .execute()
    )
    if not result.data:
        return JSONResponse(status_code=404,
            content={"error": "글을 찾을 수 없습니다"})

    stored_hash = result.data["password_hash"].encode("utf-8")
    if not bcrypt.checkpw(body.password.encode("utf-8"), stored_hash):
        return JSONResponse(status_code=403,
            content={"error": "비밀번호가 올바르지 않습니다"})

    sb.table("board_posts").update(
        {"status": "deleted"}
    ).eq("id", post_id).execute()

    return {"message": "삭제되었습니다"}
```

---

## 5. UI/UX Design

### 5.1 글쓰기 버튼 위치

`board.html`의 `#result-info` 영역 우측에 "질문하기" 버튼 추가:

```
┌─────────────────────────────────────────────┐
│  총 1,234건                   [✏️ 질문하기]  │
└─────────────────────────────────────────────┘
```

### 5.2 글쓰기 모달

```
┌─────────────────────────────────────────────┐
│  ✕                                          │
│                                             │
│  질문하기                                    │
│                                             │
│  닉네임 *                                    │
│  ┌───────────────────────────────────────┐  │
│  │                                       │  │
│  └───────────────────────────────────────┘  │
│  닉네임은 2~10자로 입력해주세요                │
│                                             │
│  비밀번호 *                                  │
│  ┌───────────────────────────────────────┐  │
│  │ ●●●●                                 │  │
│  └───────────────────────────────────────┘  │
│  삭제 시 필요합니다 (4~20자)                  │
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
│  │                                       │  │
│  │                               12/2000 │  │
│  └───────────────────────────────────────┘  │
│                                             │
│  보안문자 *                                  │
│  ┌──────────────────┐  ┌────────┐  [🔄]    │
│  │  15 + 8 = ?      │  │        │          │
│  └──────────────────┘  └────────┘          │
│                                             │
│  ┌───────────────────────────────────────┐  │
│  │           질문 등록하기                 │  │
│  └───────────────────────────────────────┘  │
│                                             │
└─────────────────────────────────────────────┘
```

### 5.3 삭제 확인 UI

글 상세 보기 영역에서 사용자 글(`board_posts` 출처)에만 "삭제" 버튼 표시:

```
┌ [임금·수당] 주휴수당 계산 방법이 궁금합니다  3분 전  [질문] ▾
│
│  (아직 답변이 없습니다)
│
│  [비슷한 질문하기 →]   [🗑 삭제]
└
```

"삭제" 클릭 시 `prompt()` 또는 인라인 비밀번호 입력 후 API 호출.

### 5.4 User Flow

```
게시판 목록 → "질문하기" 클릭 → 모달 열림
  → CAPTCHA 자동 로드
  → 폼 작성 (닉네임, 비밀번호, 카테고리, 질문, 보안문자 답)
  → "질문 등록하기" 클릭
  → [성공] 모달 닫힘 + 목록 새로고침 + 성공 토스트
  → [실패] 에러 메시지 표시 (폼 유지)

게시판 목록 → 사용자 글 클릭 → 상세 펼침
  → "삭제" 클릭 → 비밀번호 입력 프롬프트
  → [성공] 목록에서 제거 + 삭제 토스트
  → [실패] "비밀번호가 올바르지 않습니다" 표시
```

### 5.5 Component List

| Component | Location | Responsibility |
|-----------|----------|----------------|
| 글쓰기 버튼 | `#result-info` 우측 | 모달 열기 |
| 글쓰기 모달 | `#write-modal` | 폼 입력 + CAPTCHA + 제출 |
| CAPTCHA 영역 | 모달 내부 | 문제 표시 + 답 입력 + 새로고침 |
| 삭제 버튼 | `.board-a` 내부 | 사용자 글 삭제 (비밀번호 확인) |
| 토스트 알림 | `#toast` | 성공/실패 피드백 |

---

## 6. Error Handling

### 6.1 Error Code Definition

| Code | Situation | Client Handling |
|------|-----------|-----------------|
| 400 | 입력값 검증 실패 (닉네임/질문 길이, 금칙어) | 해당 필드 하단에 에러 메시지 표시 |
| 403 | CAPTCHA 실패 또는 비밀번호 불일치 | CAPTCHA 새로고침 유도 / "비밀번호 오류" 표시 |
| 404 | 삭제 대상 글 없음 | "글을 찾을 수 없습니다" 알림 |
| 429 | Rate Limit 초과 | "잠시 후 다시 시도해주세요" + 제출 버튼 비활성화 30초 |
| 500 | 서버 오류 | "일시적인 오류입니다. 잠시 후 다시 시도해주세요" |

### 6.2 Error Response Format

```json
{ "error": "사용자에게 표시할 한국어 메시지" }
```

기존 board API와 동일한 형식 유지.

---

## 7. Security Considerations

- [x] **CAPTCHA**: 서버 사이드 HMAC 서명 토큰, 5분 만료, 일회용 아님 (단, 토큰 재사용 시 같은 답이므로 보안 영향 미미)
- [x] **비밀번호**: bcrypt (cost 12) 해싱, 평문 미저장
- [x] **XSS 방지**: 서버 — 입력값 길이 제한 + 금칙어 필터. 클라이언트 — `escHtml()` 함수로 모든 출력 이스케이프
- [x] **SQL Injection**: Supabase Python 클라이언트의 파라미터화된 쿼리 사용 (직접 SQL 없음)
- [x] **Rate Limiting**: IP 해시 기반 분당 3건 제한 (인메모리, Vercel cold start 시 리셋 — 허용 가능)
- [x] **IP 프라이버시**: IP 원본 미저장, SHA-256 해시 앞 16자만 저장
- [x] **HTTPS**: Vercel 기본 HTTPS 적용

---

## 8. Test Plan

### 8.1 Test Scope

| Type | Target | Method |
|------|--------|--------|
| 수동 테스트 | CAPTCHA 발급/검증 흐름 | curl + 브라우저 |
| 수동 테스트 | 글 작성 → 목록 표시 → 삭제 | 브라우저 |
| 수동 테스트 | Rate Limit 동작 확인 | curl 반복 호출 |

### 8.2 Test Cases

- [ ] **Happy path**: CAPTCHA 정답 + 유효 입력 → 201 + 목록 반영
- [ ] **CAPTCHA 오답**: 틀린 답 → 403
- [ ] **CAPTCHA 만료**: 5분 초과 토큰 → 403
- [ ] **비밀번호 삭제 성공**: 올바른 비밀번호 → 200 + soft delete
- [ ] **비밀번호 삭제 실패**: 틀린 비밀번호 → 403
- [ ] **Rate Limit**: 1분 내 4건 → 4번째에 429
- [ ] **금칙어**: 욕설 포함 → 400
- [ ] **닉네임 길이**: 1자/11자 → 400
- [ ] **질문 길이**: 9자/2001자 → 400
- [ ] **모바일 반응형**: 375px에서 모달 정상 표시

---

## 9. Coding Convention

### 9.1 기존 프로젝트 패턴 준수

| Item | Convention |
|------|-----------|
| API 엔드포인트 | `api/index.py`에 직접 추가 (FastAPI 데코레이터) |
| Pydantic 모델 | `class BoardWriteRequest(BaseModel)` — `api/index.py` 상단 |
| 에러 응답 | `JSONResponse(status_code=..., content={"error": "..."})` |
| Supabase 쿼리 | `_get_supabase().table("board_posts").select(...).execute()` |
| HTML | `public/board.html`에 인라인 JS/CSS (기존 패턴) |
| 비식별화 | 사용자 글의 닉네임은 그대로 표시 (본인이 설정한 닉네임이므로) |

### 9.2 새로 추가되는 패턴

| Item | Convention |
|------|-----------|
| bcrypt import | `import bcrypt` — `requirements.txt`에 `bcrypt>=4.0.0` 추가 |
| CAPTCHA 함수 | `_generate_captcha()`, `_verify_captcha()` — 언더스코어 prefix (내부 함수) |
| Rate Limit | `_write_rate` dict + `_check_rate_limit()` — 인메모리, Vercel 인스턴스별 |
| 금칙어 | `_BAD_WORDS` 컴파일된 regex — `api/index.py` 모듈 레벨 |

---

## 10. FR-07: 게시판 목록 통합 설계

### 10.1 통합 전략

기존 `/api/board/search` API를 수정하여 `board_posts`도 함께 조회:

```python
# 방법: 두 테이블을 각각 조회 → Python에서 병합 + 정렬
# (Supabase는 UNION을 직접 지원하지 않으므로)

def board_search(q, category, page, per_page):
    # 1. qa_conversations 조회 (기존)
    qa_items = fetch_qa_conversations(q, category, ...)

    # 2. board_posts 조회 (신규)
    bp_items = fetch_board_posts(q, category, ...)

    # 3. 병합 + created_at 정렬
    merged = sorted(qa_items + bp_items, key=lambda x: x["created_at"], reverse=True)

    # 4. 페이지네이션 적용
    return merged[offset:offset+per_page]
```

### 10.2 목록 아이템 구분

| 출처 | 태그 표시 | 삭제 버튼 | 답변 |
|------|----------|----------|------|
| `qa_conversations` | 없음 (기존처럼 카테고리만) | 없음 | AI 답변 전문 |
| `board_posts` | `[질문]` 뱃지 추가 | 있음 (비밀번호) | "아직 답변이 없습니다" |

---

## 11. Implementation Order

| Phase | Task | Files | 예상 변경량 |
|-------|------|-------|------------|
| 1 | Supabase `board_posts` 테이블 생성 | SQL 실행 | DDL 1건 |
| 2 | `requirements.txt`에 `bcrypt` 추가 | `requirements.txt` | +1줄 |
| 3 | CAPTCHA API (`GET /api/captcha`) + helper 함수 | `api/index.py` | +40줄 |
| 4 | 글 작성 API (`POST /api/board/write`) + Rate Limit + 금칙어 | `api/index.py` | +70줄 |
| 5 | 글 삭제 API (`POST /api/board/{id}/delete`) | `api/index.py` | +35줄 |
| 6 | 글쓰기 모달 UI + CAPTCHA 연동 | `board.html` | +250줄 (HTML+CSS+JS) |
| 7 | 게시판 목록 통합 (board_posts 병합) + 삭제 버튼 | `api/index.py` + `board.html` | +50줄 |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-03-19 | Initial draft — API 3개 + 모달 UI + 보안 설계 | Claude |
