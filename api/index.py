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
from app.anonymize import anonymize as _anonymize
from app.core import abuse_guard
from app.core.abuse_guard import GuardContext, GuardRejection

app = FastAPI(title="AI 노동상담 챗봇")

# CORS 오리진: ALLOWED_ORIGINS(쉼표구분) 설정 시 제한, 미설정 시 "*"(비파괴 기본).
_allowed_origins_env = os.environ.get("ALLOWED_ORIGINS", "*").strip()
_ALLOWED_ORIGINS = (
    ["*"] if _allowed_origins_env == "*"
    else [o.strip() for o in _allowed_origins_env.split(",") if o.strip()]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    """모든 응답에 기본 보안 헤더 부여 (clickjacking·MIME sniffing 방어)."""
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return resp


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": "입력 데이터가 올바르지 않습니다. 메시지를 확인해주세요."},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """DB/외부 API 등에서 발생한 미처리 예외를 안전한 JSON으로 통일(F-2f).

    HTTPException은 FastAPI 기본 핸들러가 더 구체적으로 매칭되어 이 핸들러보다
    우선 처리되므로 여기서는 진짜 미처리 예외만 잡힌다. traceback은 노출하지
    않고 서버 로그에만 남긴다.
    """
    logging.error("미처리 예외: %s\n%s", exc, traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"detail": "일시적인 서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요."},
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


# ── 챗봇 남용 가드 (chatbot-security) ────────────────────────────────────────

_chat_rate: dict[str, list[float]] = {}   # 채팅 전용 버킷 (게시판·이메일과 분리)


def _client_ip(request: Request) -> str:
    """ProxyFix 없이 Vercel 프록시 뒤의 실 IP 추출 (기존 관례와 동일)."""
    ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if not ip:
        ip = request.client.host if request.client else "unknown"
    return ip


def _guard_chat_request(
    request: Request, message: str, session_id: str | None,
) -> tuple[str, str | None, GuardContext]:
    """채팅 3경로 공통 사전 검사 (Design §5.0).

    반환: (정제된 message, 검증된 session_id|None, GuardContext)
    거절 시 GuardRejection을 raise — 호출부가 HTTP 상태/SSE error로 변환한다.

    반드시 get_or_create_session()·첨부 파싱보다 먼저 호출해야 한다:
    session_id 형식 검증이 세션 생성 이전이어야 의미가 있고, 차단 대상이
    base64 디코드·파일 파싱 비용을 지불하지 않도록 하기 위함이다.
    """
    client_ip = _client_ip(request)
    subject_key = abuse_guard.subject_key_for(client_ip)

    # Supabase 핸들 확보 (장애 시 None → 이벤트·쿼터 생략, fail-open)
    sb = None
    try:
        sb = get_config().supabase
    except Exception as e:
        logging.warning("가드: config 로드 실패 (쿼터 생략): %s", e)

    # 1. 입력 검증 (FR-01)
    ok, cleaned, valid_sid, err = abuse_guard.validate_message(message, session_id)
    if not ok:
        # 길이 위반은 자동 차단 카운트 대상(FR-11)이라 반드시 기록한다
        abuse_guard.record_violation(
            sb, subject_key, "length", "",
            f"len={len(message) if isinstance(message, str) else 0}", "block",
        )
        raise GuardRejection(400, err or abuse_guard.MSG_EMPTY)

    # 2. Rate limit (FR-02) — 인메모리, Vercel 인스턴스별 베스트에포트
    if not _check_rate_limit(
        client_ip,
        max_count=abuse_guard.CHAT_RATE_LIMIT,
        window=abuse_guard.CHAT_RATE_WINDOW,
        store=_chat_rate,
    ):
        # 의도적으로 DB 기록하지 않는다 — 이미 인메모리로 차단된 요청마다
        # INSERT하면 요청 폭주가 그대로 DB 쓰기 증폭이 된다. 자동 차단 카운트
        # 대상도 아니므로(RPC는 injection|quota|length만 집계) 로그로 충분하다.
        logging.info("채팅 rate limit 초과: %s", subject_key)
        raise GuardRejection(429, abuse_guard.MSG_RATE_LIMITED)

    # 3. 차단 목록 + 일일 쿼터 (FR-03/11) — Supabase RPC 1왕복, 장애 시 fail-open
    check = abuse_guard.check_guard(sb, subject_key)
    if not check.allowed:
        if check.reason == "blocked":
            raise GuardRejection(429, abuse_guard.MSG_RATE_LIMITED, check.retry_after)
        abuse_guard.record_violation(
            sb, subject_key, "quota", valid_sid or "", f"count={check.count}", "block",
        )
        raise GuardRejection(429, abuse_guard.MSG_QUOTA_EXCEEDED)

    ctx = GuardContext(
        subject_key=subject_key,
        session_id=valid_sid or "",
        injection_mode=abuse_guard.get_injection_mode(),
        scope_mode=abuse_guard.get_scope_mode(),
    )
    return cleaned, valid_sid, ctx


def _sse_error(detail: str) -> StreamingResponse:
    """가드 거절을 SSE error 이벤트로 반환 (기존 초기화 실패 패턴과 동일).

    'detail'을 기본 인자로 바인딩 — 지연 실행되는 제너레이터가 지역변수를
    참조하면 NameError가 나는 기존 관례를 따른다.
    """
    def error_gen(msg=detail):
        yield f"data: {json.dumps({'type': 'error', 'text': msg}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        error_gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/chat")
def chat(req: ChatRequest, request: Request):
    """동기 응답 — 전체 답변 한 번에 반환"""
    try:
        message, session_id, guard_ctx = _guard_chat_request(
            request, req.message, req.session_id,
        )
    except GuardRejection as e:
        headers = {"Retry-After": str(e.retry_after)} if e.retry_after else None
        raise HTTPException(e.status, e.detail, headers=headers)

    config = get_config()
    session, _ = get_or_create_session(session_id, _restore_fn)

    full_text = ""
    calc_result = None

    for event in process_question(message, session, config, guard_ctx=guard_ctx):
        if event["type"] == "meta":
            calc_result = event.get("calc_result")
        elif event["type"] == "chunk":
            full_text += event["text"]

    return {
        "message": full_text,
        "session_id": session.id,
        "calc_result": calc_result,
    }


@app.get("/api/chat/stream")
def chat_stream(request: Request, message: str, session_id: str | None = None):
    """SSE 스트리밍 응답 (텍스트 전용, 하위 호환)"""
    try:
        message, session_id, guard_ctx = _guard_chat_request(request, message, session_id)
    except GuardRejection as e:
        return _sse_error(e.detail)

    try:
        config = get_config()
        session, _ = get_or_create_session(session_id, _restore_fn)
    except Exception as e:
        logging.error("SSE 초기화 실패: %s\n%s", e, traceback.format_exc())
        err_text = "서버 초기화에 실패했습니다. 환경설정(API 키)을 확인해주세요."

        # 'e'는 except 블록을 벗어나면 자동 삭제됨 → 지연 실행되는 제너레이터가
        # 직접 참조하면 NameError 발생. 기본 인자로 메시지를 바인딩해 회피한다.
        def error_gen(msg=err_text):
            yield f"data: {json.dumps({'type': 'error', 'text': msg}, ensure_ascii=False)}\n\n"

        return StreamingResponse(error_gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    def event_generator():
        yield f"data: {json.dumps({'type': 'session', 'session_id': session.id})}\n\n"
        try:
            for event in process_question(message, session, config, guard_ctx=guard_ctx):
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
def chat_stream_with_files(req: ChatWithFilesRequest, request: Request):
    """SSE 스트리밍 응답 — 파일 첨부 지원"""
    # 가드를 첨부 파싱(base64 디코드·파일 파싱)보다 먼저 수행 — 차단 대상이
    # 파싱 비용을 지불하지 않도록(저비용→고비용 원칙, Design §2.2)
    try:
        message, session_id, guard_ctx = _guard_chat_request(
            request, req.message, req.session_id,
        )
    except GuardRejection as e:
        return _sse_error(e.detail)

    try:
        config = get_config()
        session, _ = get_or_create_session(session_id, _restore_fn)
    except Exception as e:
        logging.error("SSE(POST) 초기화 실패: %s\n%s", e, traceback.format_exc())
        err_text = "서버 초기화에 실패했습니다. 환경설정(API 키)을 확인해주세요."

        # 'e'는 except 블록을 벗어나면 자동 삭제됨 → 지연 실행되는 제너레이터가
        # 직접 참조하면 NameError 발생. 기본 인자로 메시지를 바인딩해 회피한다.
        def error_gen(msg=err_text):
            yield f"data: {json.dumps({'type': 'error', 'text': msg}, ensure_ascii=False)}\n\n"

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
            for event in process_question(message, session, config,
                                           attachments=parsed_attachments,
                                           guard_ctx=guard_ctx):
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


# ── 공용 보안 헬퍼 ────────────────────────────────────────────────────────────

# metadata에 이 키가 있으면 공개 게시판에서 제외한다.
#   guard_flag — 가드 의심(monitor) 대화 (chatbot-security FR-09)
#   truncated  — 스트림 절단으로 완결되지 않은 답변 (llm-fallback-hardening FR-02)
#   textbook   — 저작권 있는 해설서를 근거로 쓴 답변 (textbook-corpus-embedding).
#                축자 인용 금지(G1)는 소프트 가드라 실패할 수 있고, 그 산출물이
#                크롤 가능한 공개 페이지로 재게시되면 노출이 크게 확대된다.
_PUBLIC_EXCLUDE_KEYS = ("guard_flag", "truncated", "textbook")


def _apply_guard_filter(query, apply_filter: bool = True):
    """qa_conversations 조회에서 공개 부적합 대화를 제외.

    ⚠️ qa_conversations 전용 — board_posts에는 metadata 컬럼이 없어 필터를
    걸면 PostgREST 400이 나고, 호출부의 try/except에 삼켜져 사용자 게시글이
    통째로 사라진다(Design §3.2).
    """
    if not apply_filter:
        return query
    for key in _PUBLIC_EXCLUDE_KEYS:
        query = query.is_(f"metadata->>{key}", "null")
    return query


def _is_public_excluded(meta) -> bool:
    return isinstance(meta, dict) and any(meta.get(k) for k in _PUBLIC_EXCLUDE_KEYS)


def _drop_flagged(rows: list[dict] | None) -> list[dict]:
    """Python 레벨 후처리 — 필터 성공 시엔 이중 안전망, 실패 시엔 유일한 방어선."""
    return [row for row in (rows or []) if not _is_public_excluded(row.get("metadata"))]


def _fetch_qa_public(build) -> tuple[list[dict], int | None]:
    """qa_conversations 공개 조회 — 필터 실행이 실패하면 무필터로 재실행한다.

    `.is_("metadata->>guard_flag", ...)`는 쿼리 빌드 시점엔 문자열을 붙일 뿐이라
    예외를 던지지 않는다. 실제 거부는 `.execute()`의 PostgREST 400으로 나타나므로
    빌드가 아니라 **실행까지** 감싸야 설계 §6.1의 "빈 목록·500 회피"가 성립한다.

    build(apply_filter: bool) -> query   (execute() 직전 상태의 쿼리)
    반환: (guard_flag 제거된 rows, count)
    """
    try:
        res = build(True).execute()
        return _drop_flagged(res.data), res.count
    except Exception as e:
        logging.warning("guard_flag 필터 조회 실패 — 무필터 재조회 후 Python 후처리: %s", e)
        res = build(False).execute()
        return _drop_flagged(res.data), res.count


def _safe_like(term: str) -> str:
    """PostgREST ilike/or_ 필터용 검색어 새니타이즈 — 필터 인젝션 방지.

    LIKE 와일드카드(%,_)와 PostgREST 구문 문자(,()\\*)를 공백으로 치환해
    무력화한다. 검색은 정상 동작하되 구문 조작·와일드카드 남용을 차단한다.
    """
    term = (term or "")[:100]
    for ch in ("\\", "%", "_", ",", "(", ")", "*"):
        term = term.replace(ch, " ")
    return " ".join(term.split())


# ── 관리자 API ────────────────────────────────────────────────────────────────

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
JWT_SECRET = os.environ.get("ADMIN_JWT_SECRET", ADMIN_PASSWORD)
# CAPTCHA 서명키는 JWT와 용도 분리(S-1b). 미설정 시 JWT_SECRET로 폴백(비파괴적).
CAPTCHA_SECRET = os.environ.get("CAPTCHA_HMAC_SECRET") or JWT_SECRET
JWT_EXPIRY = 86400  # 24시간

# 시크릿 강도 경고(비파괴적 — 기존 배포 유지, 강화만 권고)
if not os.environ.get("ADMIN_JWT_SECRET"):
    logging.warning(
        "보안: ADMIN_JWT_SECRET 미설정 → ADMIN_PASSWORD를 서명키로 재사용 중. "
        "고엔트로피(≥32자) ADMIN_JWT_SECRET 설정을 권장합니다."
    )
elif len(JWT_SECRET) < 32:
    logging.warning("보안: ADMIN_JWT_SECRET이 32자 미만입니다. 더 긴 랜덤 시크릿을 권장합니다.")

# 관리자 로그인 브루트포스 방어용 IP 버킷(인메모리)
_login_rate: dict[str, list[float]] = {}


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
def admin_login(body: AdminLoginRequest, request: Request):
    if not ADMIN_PASSWORD:
        raise HTTPException(503, "관리자 기능이 설정되지 않았습니다")
    # 브루트포스 방어: IP당 5회/5분
    client_ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() \
        or (request.client.host if request.client else "unknown")
    if not _check_rate_limit(client_ip, max_count=5, window=300, store=_login_rate):
        raise HTTPException(429, "로그인 시도가 너무 많습니다. 잠시 후 다시 시도하세요.")
    if not _hmac.compare_digest(body.password, ADMIN_PASSWORD):  # 상수시간 비교
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
        safe = _safe_like(search)
        query = query.or_(
            f"question_text.ilike.%{safe}%,answer_text.ilike.%{safe}%"
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
    total_pages = max(1, (total + per_page - 1) // per_page)
    return {
        "conversations": conversations,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": total_pages,  # 하위 호환(admin.html 참조)
        "total_pages": total_pages,  # 표준 필드명 (board 엔드포인트와 통일, F-2f)
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
        .select("filename, content_type, public_url, file_size, storage_path")
        .eq("conversation_id", conv_id)
        .execute()
    )

    # 버킷은 비공개다(supabase_attachments_private.sql). 첨부 열람은 이 시점에
    # 발급하는 1시간 만료 signed URL이 유일한 경로이며, 저장된 public_url은 항상
    # NULL이다(storage.py::upload_attachment). 발급이 실패하면 URL 없이 내려가고
    # admin.html이 "링크 발급 실패"로 표시한다.
    # 응답 키는 admin.html 호환을 위해 public_url 유지.
    att_rows = []
    for att in (attachments.data or []):
        row = {k: att.get(k) for k in ("filename", "content_type", "public_url", "file_size")}
        storage_path = att.get("storage_path")
        if storage_path:
            try:
                signed = sb.storage.from_("chat-attachments").create_signed_url(storage_path, 3600)
                url = signed.get("signedUrl") or signed.get("signedURL")
                if url:
                    row["public_url"] = url
            except Exception as e:
                logging.warning("signed URL 발급 실패 (%s): %s", storage_path, e)
        att_rows.append(row)

    return {**result.data, "attachments": att_rows}


# ── 관리자: 남용 현황 (chatbot-security FR-12) ───────────────────────────────

class UnblockRequest(BaseModel):
    subject_key: str


@app.get("/api/admin/abuse")
def admin_abuse(days: int = 7, limit: int = 100, _admin=Depends(require_admin)):
    """남용 이벤트 집계·최근 목록·활성 차단 (관리자 전용).

    abuse_events/block_list는 anon 직접 접근이 차단돼 있어 SECURITY DEFINER
    RPC로만 조회한다.
    """
    sb = _get_supabase()
    days = max(1, min(days, 90))
    limit = max(1, min(limit, 500))
    try:
        resp = sb.rpc("abuse_summary", {"p_days": days, "p_limit": limit}).execute()
        data = resp.data
        if isinstance(data, list) and data:
            data = data[0]
        if not isinstance(data, dict):
            data = {}
        return {
            "counts": data.get("counts") or {},
            "events": data.get("events") or [],
            "blocked": data.get("blocked") or [],
            "days": days,
        }
    except Exception as e:
        logging.warning("남용 현황 조회 실패: %s", e)
        raise HTTPException(503, "남용 현황을 조회할 수 없습니다. DB 스키마(abuse_summary)를 확인하세요.")


@app.post("/api/admin/abuse/unblock")
def admin_abuse_unblock(body: UnblockRequest, _admin=Depends(require_admin)):
    """수동 차단 해제 (오탐 대응)."""
    sb = _get_supabase()
    key = (body.subject_key or "").strip()
    if not key:
        raise HTTPException(400, "subject_key가 필요합니다")
    try:
        sb.rpc("abuse_unblock", {"p_subject_key": key}).execute()
        return {"ok": True, "subject_key": key}
    except Exception as e:
        logging.warning("차단 해제 실패 (%s): %s", key, e)
        raise HTTPException(503, "차단 해제에 실패했습니다")


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
        CAPTCHA_SECRET.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()

    return question, f"{payload}.{sig}"


def _verify_captcha(token: str, user_answer: int) -> bool:
    """CAPTCHA 토큰 검증 → True/False"""
    try:
        payload_b64, sig = token.rsplit(".", 1)
        expected_sig = _hmac.new(
            CAPTCHA_SECRET.encode(), payload_b64.encode(), hashlib.sha256
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


def _check_rate_limit(
    ip: str, max_count: int = 3, window: int = 60, store: dict | None = None
) -> bool:
    """IP당 window초 내 max_count건 초과 시 False. store 미지정 시 게시판 버킷 사용."""
    store = _write_rate if store is None else store
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16]
    now = time.time()
    times = store.get(ip_hash, [])
    times = [t for t in times if now - t < window]
    if len(times) >= max_count:
        return False
    times.append(now)
    store[ip_hash] = times
    return True


# 금칙어 필터 ──────────────────────────────────────────────────────────────────

_BAD_WORDS = re.compile(
    r"(시발|씨발|개새끼|병신|ㅅㅂ|ㅂㅅ|https?://\S+|bit\.ly|광고|홍보|대출|카지노)",
    re.IGNORECASE,
)


@app.get("/api/captcha")
def captcha_generate():
    """수학 CAPTCHA 문제 + HMAC 서명 토큰 발급"""
    if not CAPTCHA_SECRET:
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

@app.get("/api/board/recent")
def board_recent(page: int = 1, per_page: int = 10):
    """최근 공개 질문/답변 — 비식별화 처리"""
    sb = _get_supabase()
    per_page = min(per_page, 20)
    offset = (page - 1) * per_page

    def _build(apply_filter: bool):
        return _apply_guard_filter(
            sb.table("qa_conversations").select(
                "id, category, question_text, answer_text, created_at, metadata",
                count="exact",
            ),
            apply_filter,
        ).order("created_at", desc=True).range(offset, offset + per_page - 1)

    rows, total_count = _fetch_qa_public(_build)

    items = []
    for row in rows:
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

    total = total_count or 0
    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),  # board_search와 스키마 통일(F-2f)
        "has_more": offset + per_page < total,
    }


@app.get("/api/board/categories")
def board_categories():
    """사용 가능한 카테고리 목록 (건수 포함)"""
    sb = _get_supabase()

    def _build(apply_filter: bool):
        return _apply_guard_filter(
            sb.table("qa_conversations").select("category, metadata"), apply_filter,
        )

    rows, _ = _fetch_qa_public(_build)

    counts: dict[str, int] = {}
    for row in rows:
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

    # --- qa_conversations 조회 (가드 flag 제외) ---
    def _build(apply_filter: bool):
        qb = _apply_guard_filter(
            sb.table("qa_conversations").select(
                "id, category, question_text, answer_text, created_at, metadata",
                count="exact",
            ),
            apply_filter,
        )
        if category:
            qb = qb.eq("category", category)
        if q:
            qb = qb.ilike("question_text", f"%{_safe_like(q)}%")
        return qb.order("created_at", desc=True)

    qa_rows, _qa_count = _fetch_qa_public(_build)

    all_items = []
    for row in qa_rows:
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
            bp_qb = bp_qb.ilike("question_text", f"%{_safe_like(q)}%")
        bp_result = bp_qb.order("created_at", desc=True).execute()

        for row in bp_result.data or []:
            all_items.append({
                "id": row["id"],
                "category": row.get("category", ""),
                "question": _anonymize(row.get("question_text", "")),
                "answer_preview": "",
                "created_at": row.get("created_at", ""),
                "source": "user",
                "nickname": _anonymize(row.get("nickname", "")),
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
    #    metadata를 함께 select해야 공개 제외 검사가 작동한다 (Design §3.2)
    result = (
        sb.table("qa_conversations")
        .select("id, category, question_text, answer_text, created_at, metadata")
        .eq("id", item_id)
        .maybe_single()
        .execute()
    )
    if result.data:
        row = result.data
        if _is_public_excluded(row.get("metadata")):
            return JSONResponse(status_code=404, content={"error": "Not found"})
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
                "question": _anonymize(row.get("question_text", "")),
                "answer": "",
                "created_at": row.get("created_at", ""),
                "source": "user",
                "nickname": _anonymize(row.get("nickname", "")),
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


@app.get("/board")
def serve_static_page(request: Request):
    """정적 페이지의 확장자 없는 경로 — /board.

    프로덕션은 vercel.json 라우트가 먼저 처리하므로 이 핸들러까지 오지 않는다.
    로컬 `uvicorn api.index:app` 개발·검증 시 프로덕션과 같은 URL로 열기 위한 것.
    /terms·/privacy·/install 은 sitemap·canonical·모든 내부 링크가 `.html` 버전만
    참조해 확장자 없는 형태로는 어디서도 쓰이지 않으므로, vercel.json의 동일 라우트와
    함께 제거했다(CodeRabbit 리뷰). 라우트 목록을 늘릴 때는 vercel.json 과 반드시 함께 고칠 것.
    """
    name = request.url.path.strip("/")
    if name != "board":
        raise HTTPException(status_code=404, detail="Not Found")
    # name이 고정 집합과 등호 비교만 거치므로 현재는 순회 위험이 없지만,
    # 이 파일의 다른 파일 서빙 엔드포인트(serve_calculator_flow)와 패턴을
    # 통일해 향후 라우트가 동적 인자를 받게 되어도 안전하도록 한다.
    base_dir = os.path.abspath(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "public")
    )
    html_path = os.path.abspath(os.path.join(base_dir, f"{name}.html"))
    if os.path.commonpath([base_dir, html_path]) != base_dir or not html_path.endswith(".html"):
        raise HTTPException(status_code=404, detail="Not Found")
    if not os.path.isfile(html_path):
        raise HTTPException(status_code=404, detail="Not Found")
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

_email_rate: dict[str, list[float]] = {}  # IP별 레이트 리밋 버킷
_EMAIL_RATE_LIMIT = 5  # IP당 분당 최대 발송 수
_EMAIL_RATE_WINDOW = 60  # 초
_EMAIL_MAX_SUBJECT = 200  # 제목 최대 길이
_EMAIL_MAX_BODY = 50_000  # 본문 HTML 최대 길이


class EmailRequest(BaseModel):
    to: str
    subject: str
    body_html: str
    captcha_token: str
    captcha_answer: int


try:
    import nh3

    _SANITIZE_TAGS = {
        "p", "br", "hr", "strong", "b", "em", "i", "u", "s",
        "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6",
        "blockquote", "code", "pre", "table", "thead", "tbody",
        "tr", "th", "td", "a", "span", "div",
    }
    _SANITIZE_ATTRS = {"a": {"href", "title"}, "span": {"style"}, "div": {"style"}}

    def _sanitize_html(html: str) -> str:
        """allowlist 기반 HTML 새니타이즈 (nh3) — 태그·속성·URL 스킴 화이트리스트."""
        return nh3.clean(
            html,
            tags=_SANITIZE_TAGS,
            attributes=_SANITIZE_ATTRS,
            url_schemes={"http", "https", "mailto"},
        )
except ImportError:
    def _sanitize_html(html: str) -> str:
        """nh3 미설치 폴백 — 정규식 기반(제한적): script/iframe/style/on*/javascript: 제거."""
        html = re.sub(r"<(script|iframe|object|embed|style|link|meta)\b[^>]*>[\s\S]*?</\1>", "", html, flags=re.IGNORECASE)
        html = re.sub(r"<(script|iframe|object|embed|style|link|meta)\b[^>]*/?>", "", html, flags=re.IGNORECASE)
        html = re.sub(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", html, flags=re.IGNORECASE)
        html = re.sub(r"(href|src)\s*=\s*([\"']?)\s*(?:javascript|data|vbscript):[^\"'>\s]*", r"\1=\2#", html, flags=re.IGNORECASE)
        return html


@app.post("/api/send-email")
async def send_email(req: EmailRequest, request: Request):
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    # 1. CAPTCHA 검증 — 무인증 오픈 메일 릴레이(브랜드 사칭 피싱) 차단
    if not _verify_captcha(req.captcha_token, req.captcha_answer):
        raise HTTPException(status_code=403, detail="보안문자가 올바르지 않습니다.")

    # 2. IP별 레이트 리밋
    client_ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(
        client_ip, max_count=_EMAIL_RATE_LIMIT, window=_EMAIL_RATE_WINDOW, store=_email_rate
    ):
        raise HTTPException(status_code=429, detail="이메일 발송 한도를 초과했습니다. 잠시 후 다시 시도해주세요.")

    # 3. 페이로드 크기 제한
    if len(req.subject) > _EMAIL_MAX_SUBJECT or len(req.body_html) > _EMAIL_MAX_BODY:
        raise HTTPException(status_code=400, detail="전송 내용이 너무 깁니다.")

    smtp_host = os.getenv("MAIL_SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("MAIL_SMTP_PORT", "587"))
    smtp_user = os.getenv("MAIL_SMTP_USERNAME", "")
    smtp_pass = os.getenv("MAIL_SMTP_PASSWORD", "")
    from_email = os.getenv("MAIL_FROM_EMAIL", smtp_user)
    from_name = os.getenv("MAIL_FROM_NAME", "기초 노동상담")

    if not smtp_user or not smtp_pass:
        # 설정 미비는 클라이언트/코드 결함이 아닌 서버 설정 문제 → 503(F-2f)
        raise HTTPException(status_code=503, detail="메일 서버가 설정되지 않았습니다.")

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
