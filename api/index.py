"""FastAPI 앱 — Vercel 서버리스 함수 진입점"""

import base64
import hashlib
import hmac as _hmac
import json
import logging
import os
import random
import re
import sys
import time
import traceback
from collections import Counter
from datetime import date, timedelta

# 프로젝트 루트를 import 경로에 추가 (wage_calculator, app 패키지 접근)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import AppConfig
from app.models.schemas import ChatRequest, ChatWithFilesRequest
from app.models.session import get_or_create_session
from app.core.storage import restore_session_data
from app.core.pipeline import process_question
from app.core.file_parser import parse_attachment, FileValidationError, MAX_ATTACHMENTS

app = FastAPI(title="AI 노동상담 챗봇")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": "입력 데이터가 올바르지 않습니다. 메시지를 확인해주세요."},
    )

# 앱 설정 (콜드 스타트 시 1회 초기화)
_config: AppConfig | None = None


def get_config() -> AppConfig:
    global _config
    if _config is None:
        _config = AppConfig.from_env()
    return _config


def _restore_fn(session_id: str) -> dict | None:
    """Supabase 세션 복원 함수 (config 의존)"""
    config = get_config()
    if config.supabase:
        return restore_session_data(config.supabase, session_id)
    return None


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/chat")
def chat(req: ChatRequest):
    """동기 응답 — 전체 답변 한 번에 반환"""
    config = get_config()
    session, _ = get_or_create_session(req.session_id, _restore_fn)

    full_text = ""
    calc_result = None

    for event in process_question(req.message, session, config):
        if event["type"] == "meta":
            calc_result = event.get("calc_result")
        elif event["type"] == "chunk":
            full_text += event["text"]
        elif event["type"] == "follow_up":
            return {
                "message": event["text"],
                "session_id": session.id,
                "follow_up": True,
            }

    return {
        "message": full_text,
        "session_id": session.id,
        "calc_result": calc_result,
    }


@app.get("/api/chat/stream")
def chat_stream(message: str, session_id: str | None = None):
    """SSE 스트리밍 응답 (텍스트 전용, 하위 호환)"""
    try:
        config = get_config()
        session, _ = get_or_create_session(session_id, _restore_fn)
    except Exception as e:
        logging.error("SSE 초기화 실패: %s\n%s", e, traceback.format_exc())

        def error_gen():
            yield f"data: {json.dumps({'type': 'error', 'text': f'서버 초기화 오류: {e}'}, ensure_ascii=False)}\n\n"

        return StreamingResponse(error_gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    def event_generator():
        yield f"data: {json.dumps({'type': 'session', 'session_id': session.id})}\n\n"
        try:
            for event in process_question(message, session, config):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            logging.error("답변 생성 실패: %s\n%s", e, traceback.format_exc())
            error_msg = "죄송합니다. 답변 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
            yield f"data: {json.dumps({'type': 'error', 'text': error_msg}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/chat/stream")
def chat_stream_with_files(req: ChatWithFilesRequest):
    """SSE 스트리밍 응답 — 파일 첨부 지원"""
    try:
        config = get_config()
        session, _ = get_or_create_session(req.session_id, _restore_fn)
    except Exception as e:
        logging.error("SSE(POST) 초기화 실패: %s\n%s", e, traceback.format_exc())

        def error_gen():
            yield f"data: {json.dumps({'type': 'error', 'text': f'서버 초기화 오류: {e}'}, ensure_ascii=False)}\n\n"

        return StreamingResponse(error_gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # 첨부파일 파싱
    parsed_attachments = []
    validation_error = None

    if req.attachments:
        if len(req.attachments) > MAX_ATTACHMENTS:
            validation_error = f"파일은 최대 {MAX_ATTACHMENTS}개까지 첨부할 수 있습니다."
        else:
            for att in req.attachments:
                try:
                    data = base64.b64decode(att.data)
                    parsed = parse_attachment(data, att.content_type, att.filename)
                    parsed_attachments.append(parsed)
                except FileValidationError as e:
                    validation_error = str(e)
                    break
                except Exception:
                    validation_error = f"파일 처리 중 오류가 발생했습니다. ({att.filename})"
                    break

    def event_generator():
        yield f"data: {json.dumps({'type': 'session', 'session_id': session.id})}\n\n"

        if validation_error:
            yield f"data: {json.dumps({'type': 'error', 'text': validation_error}, ensure_ascii=False)}\n\n"
            return

        try:
            for event in process_question(req.message, session, config,
                                           attachments=parsed_attachments):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            logging.error("답변 생성 실패(POST): %s\n%s", e, traceback.format_exc())
            error_msg = "죄송합니다. 답변 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
            yield f"data: {json.dumps({'type': 'error', 'text': error_msg}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── 관리자 API ────────────────────────────────────────────────────────────────

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
JWT_SECRET = os.environ.get("ADMIN_JWT_SECRET", ADMIN_PASSWORD)
JWT_EXPIRY = 86400  # 24시간


class AdminLoginRequest(BaseModel):
    password: str


def require_admin(authorization: str = Header(None)):
    """JWT Bearer 토큰 검증"""
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


def _get_supabase():
    """Supabase 클라이언트 반환, 없으면 503"""
    config = get_config()
    if config.supabase is None:
        raise HTTPException(503, "Supabase가 설정되지 않았습니다")
    return config.supabase


@app.post("/api/admin/login")
def admin_login(body: AdminLoginRequest):
    if not ADMIN_PASSWORD:
        raise HTTPException(503, "관리자 기능이 설정되지 않았습니다")
    if body.password != ADMIN_PASSWORD:
        raise HTTPException(401, "비밀번호가 올바르지 않습니다")
    token = jwt.encode(
        {"exp": int(time.time()) + JWT_EXPIRY, "role": "admin"},
        JWT_SECRET,
        algorithm="HS256",
    )
    return {"token": token, "expires_in": JWT_EXPIRY}


@app.get("/api/admin/stats")
def admin_stats(_admin=Depends(require_admin)):
    sb = _get_supabase()

    # 총 대화 수
    total_result = sb.table("qa_conversations").select("id", count="exact").execute()
    total_conversations = total_result.count or 0

    # 오늘 대화 수
    today_str = date.today().isoformat()
    today_result = (
        sb.table("qa_conversations")
        .select("id", count="exact")
        .gte("created_at", today_str)
        .execute()
    )
    today_conversations = today_result.count or 0

    # 총 세션 수
    sessions_result = sb.table("qa_sessions").select("id", count="exact").execute()
    total_sessions = sessions_result.count or 0

    # 최근 30일 일별 집계
    since = (date.today() - timedelta(days=30)).isoformat()
    recent = (
        sb.table("qa_conversations")
        .select("created_at")
        .gte("created_at", since)
        .execute()
    )
    day_counter: Counter = Counter()
    for row in recent.data or []:
        day = row["created_at"][:10]
        day_counter[day] += 1
    daily_counts = sorted(
        [{"date": d, "count": c} for d, c in day_counter.items()],
        key=lambda x: x["date"],
    )

    # 카테고리별 집계
    cats_result = sb.table("qa_conversations").select("category").execute()
    cat_counter: Counter = Counter()
    for row in cats_result.data or []:
        cat_counter[row["category"]] += 1
    category_counts = sorted(
        [{"category": c, "count": n} for c, n in cat_counter.items()],
        key=lambda x: x["count"],
        reverse=True,
    )

    return {
        "total_conversations": total_conversations,
        "today_conversations": today_conversations,
        "total_sessions": total_sessions,
        "daily_counts": daily_counts,
        "category_counts": category_counts,
    }


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
    sb = _get_supabase()
    per_page = min(per_page, 100)
    offset = (page - 1) * per_page

    query = sb.table("qa_conversations").select(
        "id, category, question_text, answer_text, calculation_types, created_at",
        count="exact",
    )

    if search:
        query = query.or_(
            f"question_text.ilike.%{search}%,answer_text.ilike.%{search}%"
        )
    if category:
        query = query.eq("category", category)
    if date_from:
        query = query.gte("created_at", date_from)
    if date_to:
        query = query.lte("created_at", date_to + "T23:59:59Z")

    result = (
        query.order("created_at", desc=True)
        .range(offset, offset + per_page - 1)
        .execute()
    )

    conversations = []
    for row in result.data or []:
        answer = row.get("answer_text") or ""
        conversations.append(
            {
                "id": row["id"],
                "category": row.get("category", ""),
                "question_text": row.get("question_text", ""),
                "answer_preview": answer[:100] + ("..." if len(answer) > 100 else ""),
                "calculation_types": row.get("calculation_types", []),
                "created_at": row.get("created_at", ""),
            }
        )

    total = result.count or 0
    return {
        "conversations": conversations,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


@app.get("/api/admin/conversations/{conv_id}")
def admin_conversation_detail(conv_id: str, _admin=Depends(require_admin)):
    sb = _get_supabase()

    result = (
        sb.table("qa_conversations")
        .select("*")
        .eq("id", conv_id)
        .maybe_single()
        .execute()
    )

    if not result.data:
        raise HTTPException(404, "대화를 찾을 수 없습니다")

    attachments = (
        sb.table("qa_attachments")
        .select("filename, content_type, public_url, file_size")
        .eq("conversation_id", conv_id)
        .execute()
    )

    return {**result.data, "attachments": attachments.data or []}


# ── 게시판 글쓰기 (CAPTCHA + 비밀번호) ─────────────────────────────────────────

import bcrypt


class BoardWriteRequest(BaseModel):
    nickname: str
    password: str
    category: str = "일반상담"
    question: str
    captcha_token: str
    captcha_answer: int


class BoardDeleteRequest(BaseModel):
    password: str


# CAPTCHA 헬퍼 ─────────────────────────────────────────────────────────────────

def _generate_captcha():
    """수학 CAPTCHA 생성 → (question_text, token)"""
    ops = [
        ("+", lambda a, b: a + b),
        ("-", lambda a, b: a - b),
        ("×", lambda a, b: a * b),
    ]
    op_symbol, op_func = random.choice(ops)

    if op_symbol == "×":
        a, b = random.randint(2, 9), random.randint(2, 9)
    elif op_symbol == "-":
        a = random.randint(10, 50)
        b = random.randint(1, a)
    else:
        a, b = random.randint(10, 50), random.randint(1, 30)

    answer = op_func(a, b)
    question = f"{a} {op_symbol} {b} = ?"

    expires = int(time.time()) + 300  # 5분
    payload = base64.urlsafe_b64encode(
        json.dumps({"a": answer, "e": expires}).encode()
    ).decode().rstrip("=")
    sig = _hmac.new(
        JWT_SECRET.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()

    return question, f"{payload}.{sig}"


def _verify_captcha(token: str, user_answer: int) -> bool:
    """CAPTCHA 토큰 검증 → True/False"""
    try:
        payload_b64, sig = token.rsplit(".", 1)
        expected_sig = _hmac.new(
            JWT_SECRET.encode(), payload_b64.encode(), hashlib.sha256
        ).hexdigest()
        if not _hmac.compare_digest(sig, expected_sig):
            return False
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded))
        if time.time() > data["e"]:
            return False
        return int(user_answer) == int(data["a"])
    except Exception:
        return False


# Rate Limit (인메모리, Vercel 인스턴스별) ──────────────────────────────────────

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


# 금칙어 필터 ──────────────────────────────────────────────────────────────────

_BAD_WORDS = re.compile(
    r"(시발|씨발|개새끼|병신|ㅅㅂ|ㅂㅅ|https?://\S+|bit\.ly|광고|홍보|대출|카지노)",
    re.IGNORECASE,
)


@app.get("/api/captcha")
def captcha_generate():
    """수학 CAPTCHA 문제 + HMAC 서명 토큰 발급"""
    if not JWT_SECRET:
        raise HTTPException(503, "서버 설정 오류")
    question, token = _generate_captcha()
    return {"question": question, "token": token}


@app.post("/api/board/write")
def board_write(body: BoardWriteRequest, request: Request):
    """게시판 글 작성 — CAPTCHA + 비밀번호 해싱"""
    # 1. CAPTCHA 검증
    if not _verify_captcha(body.captcha_token, body.captcha_answer):
        return JSONResponse(
            status_code=403, content={"error": "보안문자가 올바르지 않습니다"}
        )

    # 2. Rate Limit
    client_ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        return JSONResponse(
            status_code=429, content={"error": "잠시 후 다시 시도해주세요"}
        )

    # 3. 입력값 검증
    nickname = body.nickname.strip()
    question = body.question.strip()
    if not (2 <= len(nickname) <= 10):
        return JSONResponse(
            status_code=400, content={"error": "닉네임은 2~10자여야 합니다"}
        )
    if not (4 <= len(body.password) <= 20):
        return JSONResponse(
            status_code=400, content={"error": "비밀번호는 4~20자여야 합니다"}
        )
    if not (10 <= len(question) <= 2000):
        return JSONResponse(
            status_code=400, content={"error": "질문은 10~2000자여야 합니다"}
        )
    if _BAD_WORDS.search(nickname + " " + question):
        return JSONResponse(
            status_code=400, content={"error": "부적절한 내용이 포함되어 있습니다"}
        )

    # 4. bcrypt 해싱
    pw_hash = bcrypt.hashpw(
        body.password.encode("utf-8"), bcrypt.gensalt(rounds=12)
    ).decode("utf-8")

    # 5. Supabase INSERT
    ip_hash = hashlib.sha256(client_ip.encode()).hexdigest()[:16]
    sb = _get_supabase()
    result = (
        sb.table("board_posts")
        .insert(
            {
                "nickname": nickname,
                "password_hash": pw_hash,
                "category": body.category.strip() or "일반상담",
                "question_text": question,
                "ip_hash": ip_hash,
            }
        )
        .execute()
    )

    post_id = result.data[0]["id"] if result.data else None
    return JSONResponse(
        status_code=201,
        content={"id": post_id, "message": "질문이 등록되었습니다"},
    )


@app.post("/api/board/{post_id}/delete")
def board_post_delete(post_id: str, body: BoardDeleteRequest):
    """게시판 글 삭제 — 비밀번호 확인 후 soft delete"""
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
        return JSONResponse(
            status_code=404, content={"error": "글을 찾을 수 없습니다"}
        )

    stored_hash = result.data["password_hash"].encode("utf-8")
    if not bcrypt.checkpw(body.password.encode("utf-8"), stored_hash):
        return JSONResponse(
            status_code=403, content={"error": "비밀번호가 올바르지 않습니다"}
        )

    sb.table("board_posts").update({"status": "deleted"}).eq("id", post_id).execute()
    return {"message": "삭제되었습니다"}


# ── 질문게시판 (공개) ──────────────────────────────────────────────────────────

_ANON_PATTERNS = [
    (re.compile(r'[가-힣]{2,4}(?=\s*(?:씨|님|사장|대표|과장|부장|팀장|차장|이사))'), 'OOO'),
    (re.compile(r'(?:주\s*\)?\s*|㈜\s*|(?:주식)?회사\s+)[가-힣A-Za-z]+'), '(주)OOO'),
    (re.compile(r'\d{2,3}[-.\s]?\d{3,4}[-.\s]?\d{4}'), '***-****-****'),
    (re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'), '***@***.***'),
]


def _anonymize(text: str) -> str:
    """개인정보 비식별화"""
    for pattern, replacement in _ANON_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


@app.get("/api/board/recent")
def board_recent(page: int = 1, per_page: int = 10):
    """최근 공개 질문/답변 — 비식별화 처리"""
    sb = _get_supabase()
    per_page = min(per_page, 20)
    offset = (page - 1) * per_page

    result = (
        sb.table("qa_conversations")
        .select("id, category, question_text, answer_text, created_at", count="exact")
        .order("created_at", desc=True)
        .range(offset, offset + per_page - 1)
        .execute()
    )

    items = []
    for row in result.data or []:
        q = _anonymize(row.get("question_text", ""))
        a = row.get("answer_text", "")
        a_preview = a[:300] + ("..." if len(a) > 300 else "") if a else ""
        items.append({
            "id": row["id"],
            "category": row.get("category", ""),
            "question": q,
            "answer_preview": _anonymize(a_preview),
            "created_at": row.get("created_at", ""),
        })

    total = result.count or 0
    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "has_more": offset + per_page < total,
    }


@app.get("/api/board/categories")
def board_categories():
    """사용 가능한 카테고리 목록 (건수 포함)"""
    sb = _get_supabase()
    result = (
        sb.table("qa_conversations")
        .select("category")
        .execute()
    )

    counts: dict[str, int] = {}
    for row in result.data or []:
        cat = row.get("category", "일반상담") or "일반상담"
        counts[cat] = counts.get(cat, 0) + 1

    categories = [
        {"name": cat, "count": count}
        for cat, count in sorted(counts.items(), key=lambda x: -x[1])
    ]
    total = sum(c["count"] for c in categories)
    return {"categories": categories, "total": total}


@app.get("/api/board/search")
def board_search(q: str = "", category: str = "", page: int = 1, per_page: int = 15):
    """질문게시판 검색 — qa_conversations + board_posts 통합"""
    sb = _get_supabase()
    per_page = min(per_page, 30)

    # --- qa_conversations 조회 ---
    qa_qb = sb.table("qa_conversations").select(
        "id, category, question_text, answer_text, created_at", count="exact"
    )
    if category:
        qa_qb = qa_qb.eq("category", category)
    if q:
        qa_qb = qa_qb.ilike("question_text", f"%{q}%")
    qa_result = qa_qb.order("created_at", desc=True).execute()

    all_items = []
    for row in qa_result.data or []:
        question = _anonymize(row.get("question_text", ""))
        answer = row.get("answer_text", "")
        answer_preview = answer[:300] + ("..." if len(answer) > 300 else "") if answer else ""
        all_items.append({
            "id": row["id"],
            "category": row.get("category", ""),
            "question": question,
            "answer_preview": _anonymize(answer_preview),
            "created_at": row.get("created_at", ""),
            "source": "ai",
        })

    # --- board_posts 조회 (active만) ---
    try:
        bp_qb = sb.table("board_posts").select(
            "id, nickname, category, question_text, created_at", count="exact"
        ).eq("status", "active")
        if category:
            bp_qb = bp_qb.eq("category", category)
        if q:
            bp_qb = bp_qb.ilike("question_text", f"%{q}%")
        bp_result = bp_qb.order("created_at", desc=True).execute()

        for row in bp_result.data or []:
            all_items.append({
                "id": row["id"],
                "category": row.get("category", ""),
                "question": row.get("question_text", ""),
                "answer_preview": "",
                "created_at": row.get("created_at", ""),
                "source": "user",
                "nickname": row.get("nickname", ""),
            })
    except Exception:
        pass  # board_posts 테이블 미생성 시 graceful fallback

    # --- 병합 + 정렬 + 페이지네이션 ---
    all_items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    total = len(all_items)
    offset = (page - 1) * per_page
    items = all_items[offset : offset + per_page]
    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "has_more": offset + per_page < total,
    }


@app.get("/api/board/{item_id}")
def board_detail(item_id: str):
    """질문게시판 상세 — qa_conversations 또는 board_posts (비식별화)"""
    import uuid as _uuid
    try:
        _uuid.UUID(item_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "Invalid ID"})

    sb = _get_supabase()

    # 1) qa_conversations에서 먼저 조회
    result = (
        sb.table("qa_conversations")
        .select("id, category, question_text, answer_text, created_at")
        .eq("id", item_id)
        .maybe_single()
        .execute()
    )
    if result.data:
        row = result.data
        return {
            "id": row["id"],
            "category": row.get("category", ""),
            "question": _anonymize(row.get("question_text", "")),
            "answer": _anonymize(row.get("answer_text", "")),
            "created_at": row.get("created_at", ""),
            "source": "ai",
        }

    # 2) board_posts에서 조회
    try:
        bp_result = (
            sb.table("board_posts")
            .select("id, nickname, category, question_text, created_at")
            .eq("id", item_id)
            .eq("status", "active")
            .maybe_single()
            .execute()
        )
        if bp_result.data:
            row = bp_result.data
            return {
                "id": row["id"],
                "category": row.get("category", ""),
                "question": row.get("question_text", ""),
                "answer": "",
                "created_at": row.get("created_at", ""),
                "source": "user",
                "nickname": row.get("nickname", ""),
            }
    except Exception:
        pass

    return JSONResponse(status_code=404, content={"error": "Not found"})


# ── 정적 파일 서빙 ────────────────────────────────────────────────────────────

@app.get("/")
def serve_index():
    html_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "public", "index.html")
    return FileResponse(html_path, media_type="text/html")


@app.get("/admin")
def serve_admin():
    html_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "public", "admin.html")
    return FileResponse(html_path, media_type="text/html")


@app.get("/calculators")
@app.get("/calculators.html")
def serve_calculators():
    html_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "public", "calculators.html")
    return FileResponse(html_path, media_type="text/html")


@app.get("/calculator_flow/{filename:path}")
def serve_calculator_flow(filename: str):
    base_dir = os.path.abspath(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "public", "calculator_flow")
    )
    file_path = os.path.abspath(os.path.join(base_dir, filename))
    if os.path.commonpath([base_dir, file_path]) != base_dir or not file_path.endswith(".html"):
        raise HTTPException(status_code=404, detail="Not Found")
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(file_path, media_type="text/html")


# ── 이메일 발송 ─────────────────────────────────────────────────────────────

_email_log: list[float] = []  # 레이트 리밋용 타임스탬프
_EMAIL_RATE_LIMIT = 10  # 분당 최대 발송 수
_EMAIL_RATE_WINDOW = 60  # 초


class EmailRequest(BaseModel):
    to: str
    subject: str
    body_html: str


def _sanitize_html(html: str) -> str:
    """스크립트 태그 제거 — 허용: 기본 서식 태그만."""
    html = re.sub(r"<script[^>]*>[\s\S]*?</script>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"\bon\w+\s*=", "", html, flags=re.IGNORECASE)
    return html


@app.post("/api/send-email")
async def send_email(req: EmailRequest):
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    # 레이트 리밋
    now = time.time()
    _email_log[:] = [t for t in _email_log if now - t < _EMAIL_RATE_WINDOW]
    if len(_email_log) >= _EMAIL_RATE_LIMIT:
        raise HTTPException(status_code=429, detail="이메일 발송 한도를 초과했습니다. 잠시 후 다시 시도해주세요.")
    _email_log.append(now)

    smtp_host = os.getenv("MAIL_SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("MAIL_SMTP_PORT", "587"))
    smtp_user = os.getenv("MAIL_SMTP_USERNAME", "")
    smtp_pass = os.getenv("MAIL_SMTP_PASSWORD", "")
    from_email = os.getenv("MAIL_FROM_EMAIL", smtp_user)
    from_name = os.getenv("MAIL_FROM_NAME", "기초 노동상담")

    if not smtp_user or not smtp_pass:
        raise HTTPException(status_code=500, detail="메일 서버가 설정되지 않았습니다.")

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", req.to):
        raise HTTPException(status_code=400, detail="올바른 이메일 주소를 입력해주세요.")

    safe_html = _sanitize_html(req.body_html)

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = req.to
    msg["Subject"] = req.subject

    html_content = (
        '<!DOCTYPE html><html><head><meta charset="UTF-8"></head>'
        '<body style="font-family:-apple-system,sans-serif;max-width:700px;margin:0 auto;padding:20px;color:#222;line-height:1.7;">'
        '<h1 style="font-size:20px;border-bottom:2px solid #1B2A4A;padding-bottom:8px;margin-bottom:16px;">기초 노동상담</h1>'
        + safe_html
        + '<p style="font-size:12px;color:#888;border-top:1px solid #ddd;margin-top:24px;padding-top:12px;">'
        'AI가 생성한 답변으로, 법적 효력이 없습니다. 중요한 사안은 전문가 상담을 권장합니다.</p>'
        '</body></html>'
    )
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        return {"ok": True, "message": "이메일이 전송되었습니다."}
    except Exception as e:
        logging.exception("이메일 전송 실패: %s", e)
        raise HTTPException(status_code=500, detail="이메일 전송에 실패했습니다.") from e


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.index:app", host="0.0.0.0", port=5555, reload=True)
