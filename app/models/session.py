"""대화 세션 상태 관리"""

import time
import uuid
from dataclasses import dataclass, field

from app.models.schemas import AnalysisResult


@dataclass
class ChatSession:
    id: str = ""
    history: list[dict] = field(default_factory=list)
    pending_analysis: AnalysisResult | None = None
    created_at: float = 0.0
    last_active: float = 0.0

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        now = time.time()
        if not self.created_at:
            self.created_at = now
        self.last_active = now

    def has_pending_info(self) -> bool:
        return self.pending_analysis is not None

    def save_pending(self, analysis: AnalysisResult):
        self.pending_analysis = analysis

    def merge_with_pending(self, new_analysis: AnalysisResult, user_reply: str) -> AnalysisResult:
        merged = self.pending_analysis
        for key, val in new_analysis.extracted_info.items():
            if val is not None:
                merged.extracted_info[key] = val
        merged.missing_info = [
            m for m in merged.missing_info
            if m not in new_analysis.extracted_info
        ]
        self.pending_analysis = None
        return merged

    def add_turn(self, user_msg: str, assistant_msg: str):
        self.history.append({"role": "user", "content": user_msg})
        self.history.append({"role": "assistant", "content": assistant_msg})
        # 최근 10턴만 유지
        if len(self.history) > 20:
            self.history = self.history[-20:]
        self.last_active = time.time()


# 인메모리 세션 스토어
_sessions: dict[str, ChatSession] = {}
SESSION_TTL = 3600


def get_or_create_session(session_id: str | None) -> ChatSession:
    now = time.time()
    # 만료 세션 정리
    expired = [k for k, v in _sessions.items() if now - v.last_active > SESSION_TTL]
    for k in expired:
        del _sessions[k]

    if session_id and session_id in _sessions:
        session = _sessions[session_id]
        session.last_active = now
        return session

    session = ChatSession()
    _sessions[session.id] = session
    return session
