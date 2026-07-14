"""세션 관리 — 대화 이력 + 계산 캐시 + 대화 요약"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Session:
    id: str
    history: list = field(default_factory=list)   # [{"role": ..., "content": ...}]

    # ── 대화 맥락 유지 (conversation-memory) ──
    summary: str = ""                                    # 6턴 이전 대화의 구조화 요약
    calc_cache: dict = field(default_factory=dict)       # {calc_type: extracted_info}
    created_at: float = field(default_factory=time.time) # 세션 생성 시각

    def add_user(self, text: str):
        self.history.append({"role": "user", "content": text})

    def add_assistant(self, text: str):
        self.history.append({"role": "assistant", "content": text})

    def recent(self, max_turns: int = 6) -> list:
        """최근 N턴 대화 이력 반환"""
        return self.history[-(max_turns * 2):]

    # ── 계산 결과 캐싱 ──

    def cache_calculation(self, calc_type: str, extracted_info: dict):
        """계산 결과의 입력 파라미터를 캐싱.

        갱신되는 calc_type을 dict 끝으로 재삽입해 삽입 순서가 항상 "최신
        갱신 순서"와 일치하도록 한다 — get_cached_info()의 병합이 실제로는
        "calc_type이 처음 등장한 순서" 기준이라 재질문 시 오래된 다른
        유형 값이 최신 값을 덮어쓰던 문제를 해소한다(CodeRabbit 지적).
        """
        existing = self.calc_cache.pop(calc_type, {})
        existing.update({k: v for k, v in extracted_info.items() if v is not None})
        self.calc_cache[calc_type] = existing

    def get_cached_info(self, calc_types: list[str] | None = None) -> dict:
        """캐시된 계산 파라미터를 병합하여 반환 (최신 갱신 순서 우선).

        calc_types 지정 시 해당 계산 유형의 캐시만 병합 — 무관한 이전 질문
        파라미터가 새 질문에 스며드는 교차오염을 차단한다(CALC-4).
        """
        merged = {}
        for ct, info in self.calc_cache.items():
            if calc_types is not None and ct not in calc_types:
                continue
            for k, v in info.items():
                merged[k] = v
        return merged

    # ── 대화 요약 (condensation) ──

    def condense_if_needed(self, max_turns: int = 6):
        """6턴 초과 시 오래된 대화를 summary로 압축"""
        if len(self.history) <= max_turns * 2:
            return

        old_messages = self.history[:-(max_turns * 2)]
        new_summary_parts = []

        for i in range(0, len(old_messages), 2):
            user_msg = old_messages[i].get("content", "")[:100]
            asst_msg = old_messages[i + 1].get("content", "")[:100] if i + 1 < len(old_messages) else ""
            new_summary_parts.append(f"Q: {user_msg} / A: {asst_msg}")

        condensed = "; ".join(new_summary_parts)

        if self.summary:
            self.summary = self.summary + " | " + condensed
        else:
            self.summary = condensed

        # 2KB 제한
        if len(self.summary) > 2000:
            self.summary = self.summary[-2000:]

        self.history = self.history[-(max_turns * 2):]

    # ── 직렬화 (Supabase 영속 저장용) ──

    def to_snapshot(self) -> dict:
        """Supabase 저장용 스냅샷"""
        return {
            "summary": self.summary,
            "calc_cache": self.calc_cache,
            "history_tail": self.history[-4:],  # 최근 2턴만
        }

    @classmethod
    def from_snapshot(cls, session_id: str, snapshot: dict) -> "Session":
        """스냅샷에서 Session 복원"""
        session = cls(id=session_id)
        session.summary = snapshot.get("summary", "")
        session.calc_cache = snapshot.get("calc_cache", {})
        session.history = snapshot.get("history_tail", [])
        return session


# 인메모리 세션 스토어 (프로덕션에서는 Redis 등으로 교체)
_sessions: dict[str, Session] = {}


def get_or_create_session(
    session_id: str | None = None,
    restore_fn: Callable[[str], dict | None] | None = None,
) -> tuple[Session, bool]:
    """세션 조회/생성. (session, is_restored) 반환."""
    if session_id and session_id in _sessions:
        return _sessions[session_id], False

    # Layer 3: Supabase 복원 시도
    if session_id and restore_fn:
        try:
            snapshot = restore_fn(session_id)
            if snapshot:
                session = Session.from_snapshot(session_id, snapshot)
                _sessions[session_id] = session
                return session, True
        except Exception:
            pass  # graceful fallback

    sid = session_id or uuid.uuid4().hex[:12]
    session = Session(id=sid)
    _sessions[sid] = session
    return session, False
