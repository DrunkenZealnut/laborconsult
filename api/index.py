"""FastAPI 앱 — Vercel 서버리스 함수 진입점"""

import json
import os
import sys

# 프로젝트 루트를 import 경로에 추가 (wage_calculator, app 패키지 접근)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import AppConfig
from app.models.schemas import ChatRequest
from app.models.session import get_or_create_session
from app.core.pipeline import process_question

app = FastAPI(title="AI 노동상담 챗봇")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 앱 설정 (콜드 스타트 시 1회 초기화)
_config: AppConfig | None = None


def get_config() -> AppConfig:
    global _config
    if _config is None:
        _config = AppConfig.from_env()
    return _config


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/chat")
def chat(req: ChatRequest):
    """동기 응답 — 전체 답변 한 번에 반환"""
    config = get_config()
    session = get_or_create_session(req.session_id)

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
    """SSE 스트리밍 응답"""
    config = get_config()
    session = get_or_create_session(session_id)

    def event_generator():
        # 세션 ID 전송
        yield f"data: {json.dumps({'type': 'session', 'session_id': session.id})}\n\n"

        for event in process_question(message, session, config):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# 정적 파일 서빙 (로컬 개발용 — Vercel에서는 public/ 자동 서빙)
@app.get("/")
def serve_index():
    html_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "public", "index.html")
    return FileResponse(html_path, media_type="text/html")
