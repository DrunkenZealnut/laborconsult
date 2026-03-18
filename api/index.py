"""FastAPI 앱 — Vercel 서버리스 함수 진입점"""

import base64
import json
import logging
import os
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.index:app", host="0.0.0.0", port=5555, reload=True)
